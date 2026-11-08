"""Structured operational logs, with correlation and no application payloads.

Exception diagnostics deliberately describe types and code locations rather than
formatting exception messages: SQL drivers and HTTP clients can put credentials,
bound parameters or response bodies in those messages.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
from itertools import islice
import logging
import math
import os
from pathlib import Path
import re
import sys
import threading
import traceback
from urllib.parse import urlsplit, urlunsplit
import uuid


_CONTEXT = ContextVar('gianna_log_context', default={})
_BOOT_PID = os.getpid()
_BOOT_ID = uuid.uuid4().hex
_LOCK = threading.RLock()
_SECRETS = frozenset()
_REDACTED = '[redacted]'
_SENSITIVE = re.compile(
    r'password|passwd|secret|token|api.?key|authorization|cookie|payload|prompt|'
    r'messages?|content|body|history|statement|parameters|params|database_url|'
    r'email|question|answer|captcha|totp|otp|verification_code|headers|^sql$|^query$', re.I)
_URL = re.compile(r'[a-zA-Z][a-zA-Z0-9+.-]*://[^\s<>\"\']+')
_ASSIGNMENT = re.compile(
    r'(?i)\b((?:[a-z][a-z0-9_-]*_)?(?:password|passwd|secret(?:_key)?|api[_-]?key|token|encryption_key))'
    r'[\"\']?\s*[:=]\s*(?:\"[^\"]*\"|\'[^\']*\'|[^\s,;}]+)')
_HEADER = re.compile(r'(?im)\b(?:authorization|proxy-authorization|cookie|set-cookie)[\"\']?\s*[:=][^\r\n]*')
_EMAIL = re.compile(r'[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}', re.I)
_JWT = re.compile(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+')
_SQL = re.compile(r'(?i)\[SQL:|\[parameters:|\bSELECT\s+.+?\s+FROM\b|\bINSERT\s+INTO\b|\bUPDATE\s+\w+\s+SET\b|\bDELETE\s+FROM\b')
_EVENT = re.compile(r'^[a-z][a-z0-9_.-]{0,100}$')
_SAFE_NUMERIC = {'sql', 'prompt_tokens', 'output_tokens', 'input_tokens', 'token_count', 'max_tokens'}


def _reset_after_fork():
    global _BOOT_PID, _BOOT_ID, _LOCK
    _BOOT_PID, _BOOT_ID, _LOCK = os.getpid(), uuid.uuid4().hex, threading.RLock()
    _CONTEXT.set({})


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_reset_after_fork)


def boot_id():
    """One identifier per process lifetime, including pre-fork WSGI servers."""
    if _BOOT_PID != os.getpid():
        with _LOCK:
            if _BOOT_PID != os.getpid():
                _reset_after_fork()
    return _BOOT_ID


def _text(value):
    value = str(value)
    for secret in sorted(_SECRETS, key=len, reverse=True):
        value = value.replace(secret, _REDACTED)
    if _SQL.search(value):
        return '[SQL statement and parameters omitted]'
    def url(match):
        try:
            parsed = urlsplit(match.group())
            host = parsed.netloc.rsplit('@', 1)[-1]
            authority = (_REDACTED + '@' if '@' in parsed.netloc else '') + host
            return urlunsplit((parsed.scheme, authority, parsed.path, '', ''))
        except ValueError:
            return '[URL omitted]'
    value = _URL.sub(url, value)
    value = _HEADER.sub('[credential header omitted]', value)
    value = _ASSIGNMENT.sub(lambda match: match.group(1) + '=' + _REDACTED, value)
    value = _EMAIL.sub('[email omitted]', value)
    value = _JWT.sub(_REDACTED, value)
    value = re.sub(r'(?i)\bBearer\s+\S+', 'Bearer ' + _REDACTED, value)
    value = re.sub(r'(^|\s)(/[^\s?#]*)(?:\?[^\s]*)', r'\1\2?[query omitted]', value)
    return value[:1200]


def _safe(value, depth=0):
    if depth > 6:
        return '[nested value omitted]'
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, BaseException):
        return safe_exception(value)
    if isinstance(value, (str, Path)):
        return _text(value)
    if isinstance(value, dict):
        return {_text(key)[:100]: _REDACTED if _SENSITIVE.search(str(key)) and not (
                    str(key) in _SAFE_NUMERIC and type(item) is int and item >= 0
                    or str(key) == 'content_matches' and type(item) is bool) else _safe(item, depth+1)
                for key, item in islice(value.items(), 60)}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_safe(item, depth+1) for item in islice(value, 40)]
    # Never invoke arbitrary __str__/__repr__: clients may embed request payloads.
    return {'type': type(value).__name__}


def sanitize_fields(data):
    """JSON-safe operational metadata shared by stdout and the SQL journal.

    Callers supply IDs/counts/codes, not free-form content. Message, query,
    credential, header and payload fields are omitted even when nested.
    """
    return _safe(data)


def current_context():
    """A detached safe copy, usable by the SQL journal without importing Flask."""
    return _safe(_CONTEXT.get())


def safe_exception(exc):
    """A bounded causal trace, without messages, source lines, locals or SQL."""
    def describe(error):
        detail = {'type': type(error).__name__, 'frames': []}
        code = getattr(error, 'code', None)
        if isinstance(code, str) and re.fullmatch(r'[a-z][a-z0-9_.-]{0,79}', code):
            detail['code'] = _text(code)
        number = getattr(error, 'errno', None)
        if type(number) is int:
            detail['errno'] = number
        response = getattr(error, 'response', None)
        status = getattr(response, 'status_code', getattr(error, 'status', None))
        if type(status) is int and 100 <= status <= 599:
            detail['http_status'] = status
        for frame, line in list(traceback.walk_tb(error.__traceback__))[-18:]:
            detail['frames'].append({
                'module': _text(frame.f_globals.get('__name__', 'unknown')),
                'function': _text(frame.f_code.co_name),
                'file': _text(Path(frame.f_code.co_filename).name),
                'line': line,
            })
        return detail
    result = describe(exc)
    seen = {id(exc)}
    causes = []
    current = exc
    for _ in range(6):
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        causes.append(describe(current))
    if causes:
        result['causes'] = causes
    return result


@contextmanager
def bind_context(**fields):
    """Bind safe metadata for this request/job; other threads do not inherit it."""
    token = _CONTEXT.set({**_CONTEXT.get(), **_safe(fields)})
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def _protect_record(record):
    record.gianna_context = _safe(_CONTEXT.get())
    record.gianna_boot_id = boot_id()
    if record.exc_info and record.exc_info[1] is not None:
        record.gianna_exception = safe_exception(record.exc_info[1])
    record.exc_info = None
    record.exc_text = None
    record.stack_info = None
    if record.name.startswith('gianna'):
        try:
            # Prevent exception/object __str__ and mapping arguments from
            # smuggling payloads into an otherwise safe legacy format string.
            record.args = _safe(record.args) if isinstance(record.args, dict) else tuple(_safe(item) for item in record.args)
            record.msg = _text(record.getMessage())
        except Exception:
            record.msg = '[log message unavailable]'
    else:
        # Third-party text can contain arbitrary remote bodies, chat messages,
        # SQL parameters and signed URLs. Keep component/location/causal types.
        record.msg = 'Registro de biblioteca externa; consultar componente y ubicación.'
    record.args = ()
    return record


class StructuredFormatter(logging.Formatter):
    def format(self, record):
        if not hasattr(record, 'gianna_boot_id'):
            _protect_record(record)
        fields = {**getattr(record, 'gianna_context', {}), **getattr(record, 'event_fields', {})}
        result = {
            'time': datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
            'level': record.levelname,
            'event': getattr(record, 'event_name', 'legacy_log' if record.name.startswith('gianna') else 'external_log'),
            'logger': record.name,
            'boot_id': getattr(record, 'gianna_boot_id', boot_id()),
            'pid': record.process,
            'thread': record.threadName,
            'location': {'module': record.module, 'function': record.funcName, 'line': record.lineno},
            'fields': _safe(fields),
        }
        if not hasattr(record, 'event_name'):
            result['message'] = _text(record.getMessage())
        if hasattr(record, 'gianna_exception'):
            result['exception'] = record.gianna_exception
        return json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


class _JsonHandler(logging.Handler):
    """Resolve stderr at emit time so pytest capture and worker fork stay valid."""
    def emit(self, record):
        try:
            sys.stderr.write(self.format(record) + '\n')
            sys.stderr.flush()
        except Exception:
            # Never fall back to logging's raw record/exception dump on a closed
            # stream, and never make an application operation fail for logging.
            pass


def configure_logging(cfg=None):
    """Install JSON stderr once, preserving existing handlers and caplog capture."""
    global _SECRETS
    with _LOCK:
        if cfg is not None:
            names = ('secret_key', 'encryption_key', 'database_url', 'ollama_api_key', 'smtp_password', 'smtp_username',
                     'minio_access_key', 'minio_secret_key')
            _SECRETS = _SECRETS | frozenset(
                value for name in names if isinstance((value := getattr(cfg, name, None)), str) and len(value) >= 4)
        factory = logging.getLogRecordFactory()
        if not getattr(factory, '_gianna_safe_factory', False):
            def protected_factory(*args, **kwargs):
                return _protect_record(factory(*args, **kwargs))
            protected_factory._gianna_safe_factory = True
            logging.setLogRecordFactory(protected_factory)
        root = logging.getLogger()
        if not any(isinstance(handler, _JsonHandler) for handler in root.handlers):
            handler = _JsonHandler(logging.INFO)
            handler.setFormatter(StructuredFormatter())
            root.addHandler(handler)
        logging.getLogger('gianna').setLevel(logging.INFO)


def event(logger, name, *, level=logging.INFO, **fields):
    """Emit an operational event; callers pass counts/IDs/codes, never payloads."""
    name = name if isinstance(name, str) and _EVENT.fullmatch(name) else 'invalid_event_name'
    logger.log(level, name, extra={'event_name': name, 'event_fields': _safe(fields)}, stacklevel=2)
