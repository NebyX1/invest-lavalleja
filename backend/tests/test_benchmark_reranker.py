"""Check measurement semantics/privacy without running a model or touching data."""
import json
from pathlib import Path

import pytest

from scripts import benchmark_reranker as benchmark


def test_default_invocation_never_reads_inputs_or_initializes_application(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail('Dry-run must not read files or create an application')
    monkeypatch.setattr(Path, 'read_bytes', forbidden)
    monkeypatch.setattr(benchmark, 'run', forbidden)
    assert benchmark.main(['--corpus', 'unread-private.json', '--models-dir', 'unread-models',
                           '--holdout', 'unread-holdout.json']) == 0
    report = json.loads(capsys.readouterr().out)
    assert report == {'mode': 'dry_run', 'execution_performed': False, 'provider_calls': 0}


def test_quality_metrics_count_misses_and_parent_matches():
    assert benchmark.first_hit(['s27-01', 'other'], ['s27-01-03']) == 1
    assert benchmark.first_hit(['s27-01-03'], ['s27-01']) is None
    scores = benchmark.quality([{'rank': value} for value in (1, 2, None, 8)])
    assert scores == {'hit@1': .25, 'hit@3': .5, 'hit@5': .5, 'hit@8': .75, 'mrr': .40625}
    assert benchmark.percentile([40, 10, 30, 20], 95) == pytest.approx(38.5)


def test_holdout_nonregression_allows_ties_but_no_metric_regression():
    baseline = {'hit@1': .5, 'hit@3': .75, 'hit@5': .75, 'hit@8': 1., 'mrr': .625}
    assert benchmark.quality_nonregression(baseline, dict(baseline))
    assert benchmark.quality_nonregression(baseline, {**baseline, 'mrr': .7})
    for name in baseline:
        assert not benchmark.quality_nonregression(baseline, {**baseline, name: baseline[name] - .01})


def test_controlled_traces_do_not_copy_questions_or_unknown_provider_fields():
    trace = benchmark.controlled_trace({'query': 'sentinel-private-question', 'rerank': {
        'state': 'fallback', 'reason': 'timeout', 'ms': 400.2, 'budget_ms': 400,
        'candidates': 6, 'applied': False, 'reordered': False,
        'provider_output': 'sentinel-provider-prose', 'private': 'sentinel-secret'}})
    assert trace == {'state': 'fallback', 'reason': 'timeout', 'ms': 400.2, 'budget_ms': 400,
                     'candidates': 6, 'applied': False, 'reordered': False}
    assert 'sentinel' not in json.dumps(trace)
    assert benchmark.controlled_trace({'rerank': {'state': 'sentinel', 'ms': float('nan'),
                                                  'reason': 'sentinel', 'candidates': True}}) == {}


def test_run_failures_do_not_render_private_exception_messages(monkeypatch, capsys):
    def failed(args):
        raise RuntimeError('sentinel-private-corpus-or-provider-content')
    monkeypatch.setattr(benchmark, 'run', failed)
    assert benchmark.main(['--run', '--corpus', 'x', '--models-dir', 'y']) == 1
    raw = capsys.readouterr().out
    assert 'sentinel' not in raw
    assert json.loads(raw) == {'stage': 'failed', 'error_type': 'RuntimeError'}


@pytest.mark.parametrize('value', [[], [{'q': 'x', 'any': []}],
                                 [{'q': 'x', 'any': ['private/id']}],
                                 [{'q': 'x', 'any': ['id'], 'unexpected': 'private'}]])
def test_malformed_gold_cases_are_rejected(value, tmp_path):
    source = tmp_path/'cases.json'
    source.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(ValueError):
        benchmark.load_cases(source)
