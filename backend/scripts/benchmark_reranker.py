"""Opt-in, isolated neural retrieval/load study. Never reads .env or calls a provider.

Run this module in the deployment image with read-only model/input mounts and
--network none --cpus 2 --memory 2g. All SQL/index writes are temporary testing
resources. The source corpus and the published knowledge pointer are untouched.
Reports contain case numbers, record IDs, controlled state labels and metrics;
questions, passages, source documents and provider output are never retained.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import logging
import math
from pathlib import Path
import re
import secrets
import statistics
import sys
import tempfile
import threading
import time


LABELS = {'applied', 'cache_hit', 'fallback', 'skipped'}
REASONS = {'busy', 'budget_spent', 'timeout', 'unavailable', 'invalid_scores',
           'error', 'too_few_candidates', 'disabled', 'cache_hit', 'cached', 'scored'}


def percentile(values, percent):
    values = sorted(values)
    if not values:
        return None
    position = (len(values) - 1) * percent / 100
    lower, upper = math.floor(position), math.ceil(position)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def first_hit(ids, expected):
    return next((index for index, identifier in enumerate(ids, 1)
                 if any(identifier == value or value.startswith(identifier + '-')
                        for value in expected)), None)


def quality(rows):
    ranks = [row['rank'] for row in rows]
    count = len(ranks)
    return {**{f'hit@{k}': sum(rank is not None and rank <= k for rank in ranks) / count
               for k in (1, 3, 5, 8)},
            'mrr': sum(1 / rank for rank in ranks if rank is not None) / count}


def quality_nonregression(baseline, candidate):
    return all(candidate[name] >= baseline[name] for name in ('hit@1', 'hit@3', 'hit@5', 'hit@8', 'mrr'))


def timings(rows):
    values = [row['wall_ms'] for row in rows]
    return {'responses': len(values), 'p50_ms': percentile(values, 50),
            'p95_ms': percentile(values, 95), 'max_ms': max(values),
            'mean_ms': statistics.mean(values)}


def load_cases(path):
    data = json.loads(Path(path).read_bytes())
    if not isinstance(data, list) or not 1 <= len(data) <= 200:
        raise ValueError('invalid_cases')
    for case in data:
        if (not isinstance(case, dict) or set(case) != {'q', 'any'} or
                not isinstance(case['q'], str) or not 1 <= len(case['q']) <= 2500 or
                not isinstance(case['any'], list) or not case['any'] or
                any(not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,160}', identifier)
                    for identifier in case['any'])):
            raise ValueError('invalid_case')
    return data


def controlled_trace(trace):
    raw = trace.get('rerank') if isinstance(trace, dict) else None
    if not isinstance(raw, dict):
        return {'state': 'skipped', 'reason': 'disabled'}
    result = {}
    if raw.get('state') in LABELS:
        result['state'] = raw['state']
    if raw.get('reason') in REASONS:
        result['reason'] = raw['reason']
    for key in ('ms', 'budget_ms', 'candidates'):
        value = raw.get(key)
        if type(value) in {int, float} and math.isfinite(value) and value >= 0:
            result[key] = value
    for key in ('applied', 'reordered'):
        if type(raw.get(key)) is bool:
            result[key] = raw[key]
    return result


def summarize(rows):
    states, reasons = {}, {}
    for row in rows:
        trace = row.get('rerank', {})
        for field, target in (('state', states), ('reason', reasons)):
            value = trace.get(field)
            if value is not None:
                target[value] = target.get(value, 0) + 1
    return {**timings(rows), 'states': states, 'reasons': reasons}


def cpu_seconds():
    import resource
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_utime + usage.ru_stime


@contextmanager
def measure_phase(report, key, cpu_limit):
    started, cpu = time.perf_counter(), cpu_seconds()
    yield
    wall, consumed = time.perf_counter() - started, cpu_seconds() - cpu
    report[key] = {'wall_s': wall, 'cpu_s': consumed,
                   'mean_cpu_cores': consumed / max(wall, 1e-9),
                   'quota_cpu_percent': 100 * consumed / max(wall * cpu_limit, 1e-9)}


def run(args):
    # Imports stay lazy so validation/default invocation cannot initialize an app.
    import resource
    from cryptography.fernet import Fernet
    from gianna.config import Config
    from gianna.corpus import Corpus
    from gianna.services.reranking import RerankBudget
    from gianna.services.settings import Settings
    from gianna.web import create_app

    class PreparedConfig(Config):
        @property
        def model_dir(self):
            return args.models_dir.resolve()

    raw = args.corpus.read_bytes()
    corpus = Corpus.model_validate_json(raw)
    old = json.loads(args.private_corpus.read_bytes()) if args.private_corpus else {'records': []}
    private = {record['id'] for record in old['records'] if record.get('audience') != 'public'}
    original_count = len(corpus.records)
    records = [record for record in corpus.records if record.audience == 'public' and record.id not in private]
    corpus = corpus.model_copy(update={'records': records})
    cases = load_cases(args.gold)
    holdout_cases = load_cases(args.holdout) if args.holdout is not None else None
    phase_times = {}
    print(json.dumps({'stage': 'building_isolated_index', 'public_records': len(records)}), flush=True)

    with tempfile.TemporaryDirectory(prefix='gianna-rerank-benchmark-') as directory:
        cfg = PreparedConfig.from_env({'data_dir': Path(directory), 'secret_key': secrets.token_urlsafe(48),
            'encryption_key': Fernet.generate_key().decode(), 'worker_enabled': False, 'embedding_threads': 2,
            'public_origins': ('http://localhost',), 'trusted_hosts': ('localhost', '127.0.0.1'),
            'max_concurrent_chat': args.concurrency}, environ={'FLASK_ENV': 'testing'})
        app = create_app(cfg)
        logging.disable(logging.INFO)
        services = app.extensions['gianna']
        settings = Settings(retrieval_candidates=28)
        with measure_phase(phase_times, 'build', args.cpu_limit):
            base = services.knowledge.import_corpus(corpus, 'Isolated reranker benchmark', 'benchmark')
            services.knowledge.approve_public(base, 'benchmark')
            job, version = services.knowledge.enqueue_build(base, settings, 'benchmark')
            services.jobs.execute_job(services.jobs.claim())
            status = services.db.one('SELECT status,error_code FROM jobs WHERE id=?', (job,))
            if status['status'] != 'done':
                raise RuntimeError('isolated_index_failed')
        assert services.knowledge.active() is None
        retriever = services.rag.retriever
        engine = services.embeddings
        fingerprint = engine.profile['fingerprint']

        def search(number, *, bounded=False, budget=None, barrier=None, case_set=None):
            if barrier is not None:
                barrier.wait(timeout=30)
            selected = cases if case_set is None else case_set
            started = time.perf_counter()
            options = {'rerank_budget': budget or RerankBudget(args.budget_ms)} if bounded else {}
            cards, trace = retriever.search(selected[number]['q'], settings, version, limit=8, **options)
            ids = [card['record_id'] for card in cards]
            return {'case': number, 'ids': ids, 'rank': first_hit(ids, selected[number]['any']),
                    'wall_ms': (time.perf_counter() - started) * 1000,
                    'rerank': controlled_trace(trace)}

        def sequential(bounded, case_set=None, label='gold'):
            selected = cases if case_set is None else case_set
            rows = []
            for index in range(len(selected)):
                rows.append(search(index, bounded=bounded, case_set=selected))
                if (index + 1) % 10 == 0:
                    print(json.dumps({'stage': 'quality', 'set': label, 'bounded': bounded,
                                      'complete': index + 1, 'total': len(selected)}), flush=True)
            return rows

        retriever.clear_rerank_cache()
        with measure_phase(phase_times, 'hybrid_quality', args.cpu_limit):
            baseline = sequential(False)
        retriever.clear_rerank_cache()
        with measure_phase(phase_times, 'bounded_quality', args.cpu_limit):
            bounded = sequential(True)
        with measure_phase(phase_times, 'cached_quality', args.cpu_limit):
            cached = sequential(True)

        holdout = None
        if holdout_cases is not None:
            retriever.clear_rerank_cache()
            with measure_phase(phase_times, 'holdout_hybrid', args.cpu_limit):
                holdout_baseline = sequential(False, holdout_cases, 'holdout')
            retriever.clear_rerank_cache()
            with measure_phase(phase_times, 'holdout_bounded', args.cpu_limit):
                holdout_bounded = sequential(True, holdout_cases, 'holdout')
            holdout_metrics = {'hybrid': quality(holdout_baseline), 'bounded': quality(holdout_bounded)}
            holdout = {'cases': len(holdout_cases),
                       'sha256': hashlib.sha256(args.holdout.read_bytes()).hexdigest(),
                       'scope': 'predeclared_local_paraphrases_not_used_for_gold_tuning_not_external_curated',
                       'quality': holdout_metrics,
                       'timing': {'hybrid': summarize(holdout_baseline), 'bounded': summarize(holdout_bounded)},
                       'results': {'hybrid': holdout_baseline, 'bounded': holdout_bounded},
                       'passed': quality_nonregression(holdout_metrics['hybrid'], holdout_metrics['bounded'])}

        count = min(len(cases), args.concurrency * args.rounds)
        indices = list(range(count))

        def concurrent(bounded_mode):
            rows = []
            with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                for start in range(0, count, args.concurrency):
                    batch = indices[start:start + args.concurrency]
                    barrier = threading.Barrier(len(batch))
                    futures = [pool.submit(search, index, bounded=bounded_mode, barrier=barrier) for index in batch]
                    rows.extend(future.result(timeout=60) for future in futures)
            return rows

        concurrency_rows = {}
        for name, enabled, warm in [('hybrid', False, False), ('bounded_cold', True, False),
                                    ('bounded_warm', True, True)]:
            retriever.clear_rerank_cache()
            if warm:
                for number in indices:
                    search(number, bounded=True)
            print(json.dumps({'stage': 'concurrency', 'scenario': name, 'workers': args.concurrency}), flush=True)
            with measure_phase(phase_times, 'concurrent_' + name, args.cpu_limit):
                concurrency_rows[name] = concurrent(enabled)

        # Real bounded API and full retrieval fallback under controlled mutex contention.
        retriever.clear_rerank_cache()
        original = engine.rerank_bounded
        def held_lock(query, texts, **kwargs):
            acquired = threading.Event()
            release = threading.Event()
            def hold():
                with engine._infer_lock:
                    acquired.set()
                    release.wait(timeout=5)
            worker = threading.Thread(target=hold)
            worker.start()
            if not acquired.wait(timeout=5):
                raise RuntimeError('controlled_lock_failed')
            try:
                return original(query, texts, **kwargs)
            finally:
                release.set()
                worker.join(timeout=5)
        engine.rerank_bounded = held_lock
        try:
            busy = search(0, bounded=True)
        finally:
            engine.rerank_bounded = original
        retriever.clear_rerank_cache()
        timeout = search(0, bounded=True, budget=RerankBudget(1))
        retriever.clear_rerank_cache()
        shared = RerankBudget(args.budget_ms)
        calls = []
        def counted(query, texts, **kwargs):
            calls.append(1)
            return original(query, texts, **kwargs)
        engine.rerank_bounded = counted
        try:
            shared_first = search(0, bounded=True, budget=shared)
            shared_second = search(min(1, len(cases)-1), bounded=True, budget=shared)
        finally:
            engine.rerank_bounded = original

        base_metrics = quality(baseline)
        candidate_metrics = quality(bounded)
        quality_gate = (quality_nonregression(base_metrics, candidate_metrics)
                        and candidate_metrics['hit@1'] > base_metrics['hit@1']
                        and candidate_metrics['mrr'] > base_metrics['mrr'])
        concurrency_metrics = {name: summarize(rows) for name, rows in concurrency_rows.items()}
        extra_p95 = (concurrency_metrics['bounded_cold']['p95_ms'] - concurrency_metrics['hybrid']['p95_ms'])
        hot_limit = concurrency_metrics['hybrid']['p95_ms'] + max(20, concurrency_metrics['hybrid']['p95_ms'] * .25)
        cache_hits = sum(row['rerank'].get('state') == 'cache_hit' for row in cached)
        # A cold fallback is intentionally not cached. A later successful miss
        # may change its order; only actual cache hits must reproduce it exactly.
        exact_cache_quality = all(a['ids'] == b['ids'] for a, b in zip(bounded, cached)
                                  if b['rerank'].get('state') == 'cache_hit')
        controls = {'busy_returns_hybrid': busy['ids'] == baseline[0]['ids'] and busy['rerank'].get('state') in {'fallback', 'skipped'},
                    'deadline_returns_hybrid': timeout['ids'] == baseline[0]['ids'] and timeout['rerank'].get('state') in {'fallback', 'skipped'},
                    'shared_budget_maximum_one_neural_attempt': len(calls) <= 1,
                    'fingerprint_unchanged': engine.profile['fingerprint'] == fingerprint,
                    'published_pointer_untouched': services.knowledge.active() is None,
                    'cached_order_identical': exact_cache_quality}
        report = {'schema_version': 1, 'scope': 'isolated_neural_retrieval_not_production_or_answer_generation',
            'corpus_sha256': hashlib.sha256(raw).hexdigest(), 'gold_sha256': hashlib.sha256(args.gold.read_bytes()).hexdigest(),
            'source_sha256': {filename: hashlib.sha256(Path(__file__).resolve().parents[1].joinpath('gianna/services', filename).read_bytes()).hexdigest()
                              for filename in ('neural.py', 'retrieval.py', 'reranking.py')},
            'public_records': len(records), 'excluded_records': original_count-len(records), 'gold_cases': len(cases),
            'provider_calls': 0, 'production_data_modified': False, 'profile': engine.profile,
            'cpu_limit': args.cpu_limit, 'onnx_threads': 2, 'memory_limit_gib': args.memory_limit_gib,
            'peak_rss_mib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
            'budget_ms': args.budget_ms, 'concurrency': args.concurrency,
            'quality': {'hybrid': base_metrics, 'bounded': candidate_metrics,
                        'cached': quality(cached), 'improved_cases': sum((a['rank'] or 1000) > (b['rank'] or 1000) for a, b in zip(baseline, bounded)),
                        'regressed_cases': sum((a['rank'] or 1000) < (b['rank'] or 1000) for a, b in zip(baseline, bounded))},
            'sequential': {'hybrid': summarize(baseline), 'bounded': summarize(bounded), 'cached': summarize(cached)},
            'cache_hit_fraction': cache_hits/len(cached), 'concurrent': concurrency_metrics,
            'holdout': holdout,
            'phase_resources': phase_times, 'controls': controls,
            'control_traces': {'busy': busy, 'deadline': timeout, 'shared': [shared_first, shared_second]},
            'results': {'hybrid': baseline, 'bounded': bounded, 'cached': cached,
                        'concurrent': concurrency_rows},
            'thresholds': {'concurrent_cold_p95_extra_ms': args.budget_ms,
                           'concurrent_warm_p95_max_ms': hot_limit,
                           'quality_strict_improvement': ['hit@1', 'mrr'],
                           'quality_nonregression': ['hit@3', 'hit@5', 'hit@8']},
            'gates': {'quality_improvement_on_this_gold_set': quality_gate,
                      'concurrent_p95_overhead_within_budget': extra_p95 <= args.budget_ms,
                      'concurrent_cached_p95_near_baseline': concurrency_metrics['bounded_warm']['p95_ms'] <= hot_limit,
                      'all_controls': all(controls.values()), 'cached_quality': exact_cache_quality,
                      'cache_hit_fraction_at_least_95_percent': cache_hits/len(cached) >= .95},
            'limitations': {'production_deployment_tested': False, 'answers_evaluated': False,
                            'semantic_safety_evaluated': False,
                            'independent_holdout': False, 'latency_is_environment_specific': True,
                            'holdout_externally_curated': False,
                            'controlled_contention_is_instrumented': True}}
        if holdout is not None:
            report['gates']['predeclared_holdout_nonregression'] = holdout['passed']
            report['thresholds']['holdout_nonregression'] = ['hit@1', 'hit@3', 'hit@5', 'hit@8', 'mrr']
        report['passed'] = all(report['gates'].values())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n', encoding='utf-8', newline='\n')
        print(json.dumps({'stage': 'complete', 'passed': report['passed'], 'quality': report['quality'],
                          'sequential': report['sequential'], 'concurrent': report['concurrent'],
                          'holdout': None if holdout is None else {'cases': holdout['cases'], 'quality': holdout['quality'], 'passed': holdout['passed']},
                          'gates': report['gates']}), flush=True)
        return 0 if report['passed'] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='Explicitly run isolated ONNX/index/load measurements.')
    parser.add_argument('--corpus', type=Path)
    parser.add_argument('--private-corpus', type=Path)
    parser.add_argument('--gold', type=Path, default=Path(__file__).resolve().parents[1]/'evals/retrieval_gold.json')
    parser.add_argument('--holdout', type=Path, help='Optional predeclared cases, reported/gated separately without rebuilding the index.')
    parser.add_argument('--models-dir', type=Path)
    parser.add_argument('--output', type=Path, default=Path('reports/rerank/integrated.json'))
    parser.add_argument('--concurrency', type=int, default=3, choices=(1, 2, 3))
    parser.add_argument('--rounds', type=int, default=20, choices=range(1, 21))
    parser.add_argument('--budget-ms', type=int, default=400, choices=range(1, 1001))
    parser.add_argument('--cpu-limit', type=float, default=2)
    parser.add_argument('--memory-limit-gib', type=float, default=2)
    args = parser.parse_args(argv)
    if not args.run:
        print(json.dumps({'mode': 'dry_run', 'execution_performed': False, 'provider_calls': 0}))
        return 0
    if args.corpus is None or args.models_dir is None:
        parser.error('--run requires --corpus and --models-dir; no automatic environment discovery.')
    if not math.isfinite(args.cpu_limit) or args.cpu_limit <= 0 or not math.isfinite(args.memory_limit_gib) or args.memory_limit_gib <= 0:
        parser.error('Resource labels must be positive finite values matching actual container limits.')
    try:
        return run(args)
    except Exception as exc:
        # Validation errors may contain private corpus values. Never render them.
        print(json.dumps({'stage': 'failed', 'error_type': type(exc).__name__}), flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
