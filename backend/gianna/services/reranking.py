"""Optional bounded reranking: per-answer admission and private, versioned cache.

These are serving controls, not model/profile changes. No cache key or value
retains a question or passage, and no caller waits for cache/CPU admission.
"""
from collections import OrderedDict
import hashlib
import hmac
import json
import logging
import math
from numbers import Real
import secrets
import threading
import time

from ..errors import DomainError
from ..observability import event, safe_exception

LOG = logging.getLogger(__name__)
MAX_CANDIDATES = 6
MAX_TOKENS = 160
MAX_BUDGET_MS = 1500
POLICY = 'bounded-window-v4'
_MISS = object()
_BUSY = object()


class RerankBudget:
    """One lazy deadline and at most one neural attempt for an entire answer."""
    def __init__(self, timeout_ms=MAX_BUDGET_MS, *, clock=None):
        if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, Real) or not math.isfinite(timeout_ms):
            raise ValueError('Invalid rerank budget')
        self.timeout_ms = max(0.0, min(MAX_BUDGET_MS, float(timeout_ms)))
        self._clock = clock or time.monotonic
        self._deadline = None
        self._attempts = 0
        self._lock = threading.Lock()

    @property
    def attempts(self):
        return self._attempts

    def start(self):
        """Start once before retrieval, so encoder/CPU admission consumes time too."""
        if not self._lock.acquire(blocking=False):
            return False
        try:
            if self._deadline is None:
                self._deadline = self._clock() + self.timeout_ms / 1000
            return self.remaining() > 0
        finally:
            self._lock.release()

    def claim(self):
        if not self._lock.acquire(blocking=False):
            return None
        try:
            if self._attempts or self.timeout_ms <= 0:
                return None
            now = self._clock()
            if self._deadline is None:
                self._deadline = now + self.timeout_ms / 1000
            if now >= self._deadline:
                return None
            self._attempts = 1
            return min(self.timeout_ms / 1000, self._deadline - now)
        finally:
            self._lock.release()

    def remaining(self):
        return (self.timeout_ms / 1000 if self._deadline is None
                else max(0.0, min(self.timeout_ms / 1000, self._deadline - self._clock())))


class RerankCache:
    """Bounded TTL/LRU cache of score tuples, never prompt/document content."""
    def __init__(self, max_entries=256, ttl=300, *, clock=None):
        self.max_entries = max_entries
        self.ttl = ttl
        self._clock = clock or time.monotonic
        self._values = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        if not self._lock.acquire(blocking=False):
            return _BUSY
        try:
            item = self._values.get(key)
            if item is None:
                return _MISS
            expires, scores = item
            if expires <= self._clock():
                del self._values[key]
                return _MISS
            self._values.move_to_end(key)
            return scores
        finally:
            self._lock.release()

    def put(self, key, scores):
        if not self._lock.acquire(blocking=False):
            return
        try:
            now = self._clock()
            # Expired entries do not displace live values during a burst.
            for stale in [k for k, (expires, _) in self._values.items() if expires <= now]:
                del self._values[stale]
            self._values[key] = (now + self.ttl, tuple(scores))
            self._values.move_to_end(key)
            while len(self._values) > self.max_entries:
                self._values.popitem(last=False)
        finally:
            self._lock.release()

    def clear(self):
        # Maintenance/tests call this outside requests; requests never wait.
        with self._lock:
            self._values.clear()


class BoundedReranker:
    def __init__(self, *, cache=None, clock=None):
        self.cache = cache if cache is not None else RerankCache()
        self._clock = clock or time.monotonic
        self._key = secrets.token_bytes(32)
        self._flight = threading.Lock()

    def _cache_key(self, version, fingerprint, query, ids, texts):
        digest = hmac.new(self._key, digestmod=hashlib.sha256)
        for value in (POLICY, version, fingerprint, query, json.dumps(ids), str(MAX_TOKENS)):
            encoded = str(value).encode('utf-8')
            digest.update(len(encoded).to_bytes(8, 'big'))
            digest.update(encoded)
        for text in texts:
            digest.update(hashlib.sha256(text.encode('utf-8')).digest())
        return digest.digest()

    @staticmethod
    def _valid(scores, count):
        return (isinstance(scores, (list, tuple)) and len(scores) == count and
                all(isinstance(value, Real) and not isinstance(value, bool) and
                    math.isfinite(value) for value in scores))

    def score(self, engine, query, ids, texts, budget, *, version, fingerprint):
        began = self._clock()
        trace = dict(mode='bounded', policy=POLICY, state='skipped', reason='too_few_candidates',
                     applied=False, candidates=len(ids), budget_ms=budget.timeout_ms,
                     max_tokens=MAX_TOKENS, attempts=budget.attempts)

        def finish(state, reason, scores=None):
            trace.update(state=state, reason=reason, applied=scores is not None,
                         attempts=budget.attempts, ms=round(max(0, self._clock()-began)*1000, 2))
            event(LOG, 'retrieval.rerank_completed', version_id=version, **trace)
            return scores, trace

        if len(ids) < 2:
            return finish('skipped', 'too_few_candidates')
        key = self._cache_key(version, fingerprint, query, ids, texts)
        cached = self.cache.get(key)
        if cached is _BUSY:
            return finish('fallback', 'busy')
        if cached is not _MISS:
            return finish('cache_hit', 'cached', cached)
        bounded = getattr(engine, 'rerank_bounded', None)
        if not callable(bounded):
            return finish('fallback', 'unavailable')
        if not self._flight.acquire(blocking=False):
            return finish('fallback', 'busy')
        try:
            remaining = budget.claim()
            if remaining is None:
                return finish('skipped', 'budget_spent')
            try:
                scores = bounded(query, texts, timeout=min(remaining, budget.remaining()), max_tokens=MAX_TOKENS)
            except DomainError as exc:
                reason = {'rerank_busy': 'busy', 'rerank_timeout': 'timeout',
                          'rerank_unavailable': 'unavailable', 'models_not_prepared': 'unavailable',
                          'rerank_not_ready': 'unavailable',
                          'invalid_rerank': 'invalid_scores'}.get(exc.code, 'error')
                if reason == 'error':
                    event(LOG, 'retrieval.rerank_failed', level=logging.WARNING,
                          version_id=version, exception=safe_exception(exc))
                return finish('fallback', reason)
            except Exception as exc:
                event(LOG, 'retrieval.rerank_failed', level=logging.WARNING,
                      version_id=version, exception=safe_exception(exc))
                return finish('fallback', 'error')
            if budget.remaining() <= 0:
                return finish('fallback', 'timeout')
            if not self._valid(scores, len(ids)):
                return finish('fallback', 'invalid_scores')
            values = tuple(float(value) for value in scores)
            self.cache.put(key, values)
            return finish('applied', 'scored', values)
        finally:
            self._flight.release()
