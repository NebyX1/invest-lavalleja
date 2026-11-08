"""Isolated local feasibility study. No provider, production DB, or .env."""
import hashlib
import json
import logging
from pathlib import Path
import resource
import secrets
import tempfile
import time
import numpy as np
from cryptography.fernet import Fernet
from gianna.config import Config
from gianna.corpus import Corpus
from gianna.services.settings import Settings
from gianna.chunking import input_prefix
from gianna.web import create_app


class PreparedConfig(Config):
    @property
    def model_dir(self):
        return Path('/models')


def first_hit(ids, expected):
    return next((i for i, key in enumerate(ids, 1)
                 if any(key == value or value.startswith(key + '-') for value in expected)), None)


def metrics(rows):
    ranks = [row['rank'] for row in rows]
    return {**{f'hit@{k}': sum(r is not None and r <= k for r in ranks) / len(ranks)
               for k in (1, 3, 5, 8)},
            'mrr': sum(1 / r for r in ranks if r is not None) / len(ranks),
            'p50_ms': float(np.percentile([r['ms'] for r in rows], 50)),
            'p95_ms': float(np.percentile([r['ms'] for r in rows], 95)),
            'max_ms': max(r['ms'] for r in rows)}


def main():
    document = Path('/inputs/corpus.json').read_bytes()
    corpus = Corpus.model_validate_json(document)
    source = json.loads(Path('/inputs/source.json').read_bytes())
    known_private = {r['id'] for r in source['records'] if r.get('audience') != 'public'}
    records = [r for r in corpus.records if r.audience == 'public' and r.id not in known_private]
    corpus = corpus.model_copy(update={'records': records})
    cases = json.loads(Path('/inputs/gold.json').read_bytes())
    with tempfile.TemporaryDirectory() as directory:
        cfg = PreparedConfig.from_env({'data_dir': Path(directory), 'secret_key': secrets.token_urlsafe(48),
            'encryption_key': Fernet.generate_key().decode(), 'worker_enabled': False,
            'embedding_threads': 2, 'public_origins': ('http://localhost',),
            'trusted_hosts': ('localhost', '127.0.0.1')}, environ={'FLASK_ENV': 'testing'})
        app = create_app(cfg)
        logging.disable(logging.INFO)
        s = app.extensions['gianna']
        settings = Settings(retrieval_candidates=28)
        began = time.monotonic()
        base = s.knowledge.import_corpus(corpus, 'Isolated local feasibility fixture', 'benchmark')
        s.knowledge.approve_public(base, 'benchmark')
        job, version = s.knowledge.enqueue_build(base, settings, 'benchmark')
        print(json.dumps({'stage': 'building_isolated_index', 'public_records': len(records)}), flush=True)
        s.jobs.execute_job(s.jobs.claim())
        status = s.db.one('SELECT status,error_code FROM jobs WHERE id=?', (job,))
        if status['status'] != 'done':
            print(json.dumps({'stage': 'index_failed', 'code': status['error_code']}), flush=True)
            return 1
        engine = s.embeddings
        original = engine.rerank
        print(json.dumps({'stage': 'index_ready', 'seconds': round(time.monotonic()-began, 2)}), flush=True)
        all_rows = {'hybrid': [], 'top4_tokens128': [], 'top6_tokens192': []}
        candidate_snapshot = []
        for number, case in enumerate(cases):
            captured = []
            def collect(query, texts):
                captured.extend(texts)
                return []
            engine.rerank = collect
            try:
                cards, trace = s.rag.retriever.search(case['q'], settings, version, limit=28, mode='fused')
            finally:
                engine.rerank = original
            assert len(captured) == len(cards)
            ids = [card['record_id'] for card in cards]
            prepared = []
            for card, text in zip(cards, captured):
                record = s.rag.retriever.records(version, [card['record_id']])[card['record_id']]
                prefix = input_prefix(record)
                prepared.append(text[len(prefix):] if text.startswith(prefix + prefix) else text)
            all_rows['hybrid'].append({'case': number, 'rank': first_hit(ids, case['any']),
                                       'ms': trace['ms'], 'ids': ids[:10]})
            candidate_snapshot.append({'case': number, 'ids': ids, 'texts': prepared})
            for name, count, tokens in [('top4_tokens128', 4, 128), ('top6_tokens192', 6, 192)]:
                engine.rank_tokenizer.enable_truncation(max_length=tokens, strategy='only_second')
                engine.query_tokenizer.enable_truncation(max_length=64)
                started = time.perf_counter()
                scores = original(case['q'], prepared[:count])
                elapsed = (time.perf_counter()-started)*1000
                top = [key for key, _ in sorted(zip(ids[:count], scores), key=lambda item: -item[1])]
                order = top + ids[count:]
                all_rows[name].append({'case': number, 'rank': first_hit(order, case['any']),
                                      'ms': elapsed, 'ids': order[:10]})
            if (number + 1) % 10 == 0:
                print(json.dumps({'stage': 'scoring', 'complete': number+1, 'total': len(cases)}), flush=True)
        result = {'scope': 'local_fixture_neural_retrieval_not_production_or_answer_eval',
                  'corpus_sha256': hashlib.sha256(document).hexdigest(), 'public_records': len(records),
                  'known_private_removed': len(corpus.records)-len(records), 'gold_cases': len(cases),
                  'profile': engine.profile, 'provider_calls': 0, 'production_data_modified': False,
                  'cpu_limit': 2, 'onnx_threads': 2, 'memory_limit_gib': 2,
                  'peak_rss_mib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                  'modes': {name: metrics(rows) for name, rows in all_rows.items()},
                  'results': all_rows}
        baseline = all_rows['hybrid']
        for name in ('top4_tokens128', 'top6_tokens192'):
            result['modes'][name]['improved_cases'] = sum((b['rank'] or 1000) > (r['rank'] or 1000)
                                                       for b, r in zip(baseline, all_rows[name]))
            result['modes'][name]['regressed_cases'] = sum((b['rank'] or 1000) < (r['rank'] or 1000)
                                                        for b, r in zip(baseline, all_rows[name]))
        Path('/reports/feasibility.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        # Private candidate passages remain only in this disposable runtime.
        Path('/tmp/candidates.json').write_text(json.dumps(candidate_snapshot), encoding='utf-8')
        print(json.dumps({'stage': 'complete', 'modes': result['modes']}), flush=True)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({'stage': 'failed', 'error_type': type(exc).__name__}), flush=True)
        raise SystemExit(1) from None
