"""Real retrieval checks against the active serving snapshot; no provider calls."""
import argparse
import json
from pathlib import Path
import time

from backend_path import add_backend_path

ROOT = add_backend_path(__file__)
from gianna.config import Config
from gianna.db import Database
from gianna.services.knowledge import Knowledge
from gianna.services.settings import get_settings
from gianna.services.neural import Embeddings
from gianna.services.vector_store import LanceStore
from gianna.services.rag import RAG
from gianna.services.harness import AgentHarness

CASES = [
    ('¿Qué información hay sobre parques eólicos existentes en Lavalleja?', {'EN-007', 'EN-008'}),
    ('¿Qué trámite corresponde para autoconsumo eléctrico de hasta 150 kW?', {'EN-017', 'EN-018'}),
    ('¿Qué se sabe de olivicultura y oleoturismo en Lavalleja?', {'AG-012'}),
    ('¿Cuál es el régimen de calidad de agua y vertidos del Decreto 226/025?', {'TR-003', 'TR-004'}),
    ('¿Qué información hay sobre mantenimiento y automatización industrial?', {'O01'}),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    cfg = Config.from_env(); db = Database(cfg.database_target); knowledge = Knowledge(db, cfg)
    if knowledge.active()['id'] != args.version:
        raise SystemExit('La versión solicitada no es la activa.')
    print(json.dumps({'stage': 'loading_verified_models', 'version': args.version}), flush=True)
    embeddings = Embeddings(cfg); embeddings.load()
    rag = RAG(db, cfg, knowledge, embeddings, LanceStore(cfg), None, None)
    settings = get_settings(db, cfg)
    cases = []
    for question, expected in CASES:
        if knowledge.active()['id'] != args.version:
            raise RuntimeError('La versión activa cambió durante la comprobación.')
        selected, elapsed, trace = rag.retrieve_plan(AgentHarness.retrieval_plan(question, []), settings, knowledge.active()['id'])
        ids = [hit['record_id'] for hit in selected]
        case = {'question': question, 'expected_any': sorted(expected), 'selected': ids,
                'expected_in_context': bool(expected & set(ids)),
                'version_ids': sorted({hit['version_id'] for hit in selected}),
                'public_only': bool(selected) and all(hit['record']['audience'] == 'public' for hit in selected),
                'global_search': bool(trace['rounds']) and all(r['global_public_search'] for r in trace['rounds']),
                'horizon_reranked': bool(trace['reranked']), 'elapsed_ms': round(elapsed, 2)}
        cases.append(case); print(json.dumps(case, ensure_ascii=True), flush=True)
    result = {'active_version': knowledge.active()['id'], 'model': settings.model, 'cases': cases,
              'passed': sum(c['expected_in_context'] and c['public_only'] and c['global_search'] and c['horizon_reranked']
                            and c['version_ids'] == [args.version] for c in cases), 'total': len(cases),
              'provider_calls': 0, 'generation_tested': False,
              'limitation': 'Context retrieval checks, not factual certification or an evaluation of generated replies.'}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('active_version', 'passed', 'total', 'provider_calls')}))
    if result['passed'] != result['total']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
