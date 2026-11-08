"""Serving deadline/CPU contracts with doubles; not a ranking quality benchmark."""
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from gianna.errors import DomainError
from gianna.services.neural import Embeddings, LEGACY_ENGINE_VERSION


class Tokens:
    def __init__(self):
        self.truncation = None
        self.on_encode = lambda: None

    def enable_truncation(self, **kwargs):
        self.truncation = kwargs

    def no_truncation(self):
        self.truncation = None

    def encode(self, text, **kwargs):
        return SimpleNamespace(ids=[1, 2])

    def decode(self, ids):
        return 'bounded synthetic question'

    def encode_batch(self, pairs):
        self.on_encode()
        return [SimpleNamespace(ids=[1, 2], attention_mask=[1, 1], type_ids=[0, 0]) for _ in pairs]


@pytest.fixture
def prepared(cfg, monkeypatch):
    engine = Embeddings(cfg)
    engine.model = object()
    engine.ranker = SimpleNamespace(get_inputs=lambda: [SimpleNamespace(name='input_ids')])
    engine.rank_tokenizer = Tokens()
    engine.query_tokenizer = Tokens()
    engine.rank_tokenizer.enable_truncation(max_length=512)
    engine.query_tokenizer.enable_truncation(max_length=120)
    engine.profile = {'fingerprint': 'unchanged-published-fingerprint'}
    monkeypatch.setattr(engine, 'load', lambda: pytest.fail('Serving must not load models'))
    return engine


def unlocked(engine):
    assert engine._infer_lock.acquire(blocking=False)
    try:
        if hasattr(engine, 'rank_tokenizer'):
            assert engine.rank_tokenizer.truncation == {'max_length': 512}
            assert engine.query_tokenizer.truncation == {'max_length': 120}
    finally:
        engine._infer_lock.release()


def test_unprepared_bounded_reranker_never_loads_models(cfg, monkeypatch):
    engine = Embeddings(cfg)
    monkeypatch.setattr(engine, 'load', lambda: pytest.fail('No model loading inside bounded reranking'))
    with pytest.raises(DomainError) as caught:
        engine.rerank_bounded('synthetic', ['passage'], timeout=.2)
    assert caught.value.code == 'rerank_not_ready'
    unlocked(engine)


def test_bounded_reranker_does_not_queue_behind_embedding_inference(prepared, monkeypatch):
    monkeypatch.setattr(prepared, '_onnx', lambda *args: pytest.fail('Busy CPU must not run a second inference'))
    prepared._infer_lock.acquire()
    try:
        with pytest.raises(DomainError) as caught:
            prepared.rerank_bounded('synthetic', ['passage'], timeout=1)
        assert caught.value.code == 'rerank_busy'
        assert prepared._infer_lock.locked()  # Never release another request's ownership.
    finally:
        prepared._infer_lock.release()


def test_bounded_batches_preserve_legacy_tokenizers_and_profile(prepared, monkeypatch):
    calls = []
    def infer(session, feeds, timeout):
        calls.append((len(feeds['input_ids']), timeout, set(feeds)))
        assert prepared.rank_tokenizer.truncation == {'max_length': 128, 'strategy': 'only_second'}
        assert prepared.query_tokenizer.truncation is None
        return np.zeros((len(feeds['input_ids']), 1))
    monkeypatch.setattr(prepared, '_onnx', infer)
    assert prepared.rerank_bounded('synthetic', ['passage'] * 6, timeout=1, max_tokens=128) == [.5] * 6
    assert [size for size, _, _ in calls] == [4, 2]
    assert all(0 < remaining <= 1 and names == {'input_ids'} for _, remaining, names in calls)
    assert prepared.rank_tokenizer.truncation == {'max_length': 512}
    assert prepared.query_tokenizer.truncation == {'max_length': 120}
    assert prepared.profile == {'fingerprint': 'unchanged-published-fingerprint'}
    unlocked(prepared)


def test_long_contextual_query_preserves_subject_and_current_question(prepared, monkeypatch):
    seen = {}
    prepared.query_tokenizer.encode = lambda *args, **kwargs: SimpleNamespace(ids=list(range(100)))
    def decode(ids):
        seen['ids'] = ids
        return 'head and current question tail'
    prepared.query_tokenizer.decode = decode
    monkeypatch.setattr(prepared, '_onnx', lambda *args: np.zeros((1, 1)))
    prepared.rerank_bounded('earlier subject then a long context then the current question',
                             ['passage'], timeout=1)
    assert seen['ids'] == list(range(24)) + list(range(60, 100))
    assert len(seen['ids']) == 64
    assert prepared.query_tokenizer.truncation == {'max_length': 120}


@pytest.mark.parametrize('timeout', [0, -1, float('nan'), float('inf'), True, '0.3'])
def test_expired_or_invalid_budget_never_runs_inference(prepared, monkeypatch, timeout):
    monkeypatch.setattr(prepared, '_onnx', lambda *args: pytest.fail('Invalid budget reached inference'))
    with pytest.raises(DomainError) as caught:
        prepared.rerank_bounded('synthetic', ['passage'], timeout=timeout)
    assert caught.value.code == 'rerank_timeout'
    unlocked(prepared)


@pytest.mark.parametrize('output', [
    np.array([[float('nan')]]), np.array([[float('inf')]]),
    np.array([[0., 1.]]), np.array([[0.], [1.]]), np.array([0.]),
])
def test_invalid_model_output_is_rejected_without_reusing_partial_scores(prepared, monkeypatch, output):
    monkeypatch.setattr(prepared, '_onnx', lambda *args: output)
    with pytest.raises(DomainError) as caught:
        prepared.rerank_bounded('synthetic', ['passage'], timeout=1)
    assert caught.value.code == 'invalid_rerank'
    unlocked(prepared)


def test_tokenization_time_is_inside_the_same_deadline(prepared, monkeypatch):
    clock = [10.]
    monkeypatch.setattr('gianna.services.neural.time.monotonic', lambda: clock[0])
    prepared.rank_tokenizer.on_encode = lambda: clock.__setitem__(0, clock[0] + .5)
    monkeypatch.setattr(prepared, '_onnx', lambda *args: pytest.fail('Tokenization exhausted the budget'))
    with pytest.raises(DomainError) as caught:
        prepared.rerank_bounded('synthetic', ['passage'], timeout=.2)
    assert caught.value.code == 'rerank_timeout'
    unlocked(prepared)


def test_late_second_batch_discards_the_whole_result_and_releases_cpu(prepared, monkeypatch):
    clock = [10.]
    monkeypatch.setattr('gianna.services.neural.time.monotonic', lambda: clock[0])
    calls = []
    def infer(session, feeds, timeout):
        calls.append(timeout)
        clock[0] += .1
        return np.zeros((len(feeds['input_ids']), 1))
    monkeypatch.setattr(prepared, '_onnx', infer)
    with pytest.raises(DomainError) as caught:
        prepared.rerank_bounded('synthetic', ['passage'] * 6, timeout=.15)
    assert caught.value.code == 'rerank_timeout'
    assert len(calls) == 2 and calls[1] < calls[0]
    unlocked(prepared)


def test_deadline_sets_onnx_termination_flag_and_releases_cpu(prepared):
    terminated = threading.Event()
    class Session:
        def get_inputs(self):
            return [SimpleNamespace(name='input_ids')]
        def run(self, names, feeds, options):
            until = time.monotonic() + 5
            while not options.terminate and time.monotonic() < until:
                time.sleep(.001)
            if options.terminate:
                terminated.set()
            raise RuntimeError('synthetic terminated inference')
    prepared.ranker = Session()
    with pytest.raises(DomainError) as caught:
        prepared.rerank_bounded('synthetic', ['passage'], timeout=.04)
    assert caught.value.code == 'rerank_timeout'
    assert terminated.is_set()
    unlocked(prepared)


def test_unexpected_tokenizer_failure_is_typed_without_content(prepared, monkeypatch):
    def fail():
        raise RuntimeError('sentinel-private-passage')
    prepared.rank_tokenizer.on_encode = fail
    with pytest.raises(DomainError) as caught:
        prepared.rerank_bounded('synthetic', ['passage'], timeout=1)
    assert caught.value.code == 'rerank_failed'
    assert 'sentinel' not in caught.value.message
    unlocked(prepared)


def test_legacy_profile_capacity_remains_the_upper_bound(prepared, monkeypatch):
    from gianna.services.neural import MODEL_PROFILES
    prepared.spec = MODEL_PROFILES[LEGACY_ENGINE_VERSION]
    def infer(*args):
        assert prepared.rank_tokenizer.truncation['max_length'] == 384
        return np.zeros((1, 1))
    monkeypatch.setattr(prepared, '_onnx', infer)
    prepared.rerank_bounded('synthetic', ['passage'], timeout=1, max_tokens=512)
    assert prepared.rank_tokenizer.truncation['max_length'] == 512


@pytest.mark.parametrize('untruncated', [False, True])
def test_real_tokenizer_configuration_is_restored_before_legacy_rerank(prepared, monkeypatch, untruncated):
    from tokenizers import Tokenizer, models, pre_tokenizers
    vocab = {'[UNK]': 0, **{f'word{i}': i + 1 for i in range(200)}}
    def tokenizer():
        result = Tokenizer(models.WordLevel(vocab, unk_token='[UNK]'))
        result.pre_tokenizer = pre_tokenizers.Whitespace()
        return result
    prepared.rank_tokenizer = tokenizer()
    prepared.query_tokenizer = tokenizer()
    if not untruncated:
        prepared.rank_tokenizer.enable_truncation(max_length=512, stride=7, strategy='only_second', direction='left')
        prepared.query_tokenizer.enable_truncation(max_length=120, stride=3, strategy='only_first', direction='left')
    saved_rank = prepared.rank_tokenizer.truncation
    saved_query = prepared.query_tokenizer.truncation
    query = ' '.join(f'word{i}' for i in range(200))
    stage = ['bounded']
    def infer(session, feeds, timeout):
        assert prepared._infer_lock.locked()
        if stage[0] == 'bounded':
            assert prepared.rank_tokenizer.truncation['max_length'] == 160
            assert prepared.query_tokenizer.truncation is None
            expected = list(range(1, 25)) + list(range(161, 201))
            assert list(feeds['input_ids'][0][:64]) == expected
        else:
            assert prepared.rank_tokenizer.truncation == saved_rank
            assert prepared.query_tokenizer.truncation == saved_query
        return np.zeros((1, 1))
    monkeypatch.setattr(prepared, '_onnx', infer)
    prepared.rerank_bounded(query, ['word70 word80'], timeout=1, max_tokens=160)
    assert prepared.rank_tokenizer.truncation == saved_rank
    assert prepared.query_tokenizer.truncation == saved_query
    stage[0] = 'legacy'
    monkeypatch.setattr(prepared, 'load', lambda: None)
    assert prepared.rerank(query, ['word70 word80']) == [.5]
    assert prepared.rank_tokenizer.truncation == saved_rank
    assert prepared.query_tokenizer.truncation == saved_query


def test_tokenizer_restore_holds_cpu_ownership_even_after_failure(prepared, monkeypatch):
    restored = []
    rank = prepared.rank_tokenizer.enable_truncation
    query = prepared.query_tokenizer.enable_truncation
    def restore_rank(**config):
        if config == {'max_length': 512}:
            assert prepared._infer_lock.locked()
            restored.append('rank')
        rank(**config)
    def restore_query(**config):
        assert prepared._infer_lock.locked()
        restored.append('query')
        query(**config)
    prepared.rank_tokenizer.enable_truncation = restore_rank
    prepared.query_tokenizer.enable_truncation = restore_query
    def fail(*args):
        raise RuntimeError('synthetic inference failure')
    monkeypatch.setattr(prepared, '_onnx', fail)
    with pytest.raises(DomainError):
        prepared.rerank_bounded('synthetic', ['passage'], timeout=1, max_tokens=160)
    assert restored == ['rank', 'query']
    unlocked(prepared)
