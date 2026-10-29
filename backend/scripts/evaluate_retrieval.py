#!/usr/bin/env python3
"""Evalúa la recuperación contra el conjunto de oro (sin llamar al modelo generativo).

Uso: python scripts/evaluate_retrieval.py [--version ID] [--modes fused hybrid rerank] [--verbose]

Un caso acierta en k si alguna ficha esperada aparece entre las k primeras. Un id esperado
también acierta si la ficha recuperada es su versión fusionada (``s27-01`` cubre ``s27-01-03``).
"""
import argparse
import json
from pathlib import Path

import local_env

BACKEND = local_env.prepare()

from gianna.config import Config
from gianna.db import Database
from gianna.security import Security
from gianna.services.knowledge import Knowledge
from gianna.services.rag import RAG
from gianna.services.runtime import Embeddings, LanceStore, Ollama
from gianna.services.settings import get_settings


def matches(record_id, expected):
    return record_id == expected or expected.startswith(record_id + '-')


def first_hit(ids, expected_any):
    for rank, record_id in enumerate(ids, 1):
        if any(matches(record_id, e) for e in expected_any):
            return rank
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version')
    parser.add_argument('--gold', type=Path, default=BACKEND / 'evals' / 'retrieval_gold.json')
    parser.add_argument('--modes', nargs='+', default=['fused'])
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    cfg = Config.from_env()
    db = Database(cfg.database_target)
    knowledge = Knowledge(db, cfg)
    embeddings = Embeddings(cfg)
    rag = RAG(db, cfg, knowledge, embeddings, LanceStore(cfg), Ollama(cfg), Security(db, cfg))
    settings = get_settings(db, cfg)
    version = rag.retriever.version(args.version)
    embeddings.for_profile(json.loads(version['profile_json'])).load()
    cases = json.loads(args.gold.read_text(encoding='utf-8'))
    for mode in args.modes:
        ranks, misses, total_ms = [], [], 0.0
        for case in cases:
            cards, trace = rag.retriever.search(case['q'], settings, version['id'], limit=10, mode=mode)
            total_ms += trace['ms']
            rank = first_hit([c['record_id'] for c in cards], case['any'])
            ranks.append(rank)
            if rank is None or rank > 5:
                misses.append((case['q'], rank, [c['record_id'] for c in cards][:6], case['any']))
        n = len(cases)
        report = {f'hit@{k}': round(sum(1 for r in ranks if r and r <= k) / n, 3) for k in (1, 3, 5, 8, 10)}
        report['mrr'] = round(sum(1 / r for r in ranks if r) / n, 3)
        report['avg_ms'] = round(total_ms / n, 1)
        print(mode, json.dumps(report))
        if args.verbose:
            for q, rank, got, want in misses:
                print(f'  rank={rank} | {q}\n     got={got}\n     want={want}')


if __name__ == '__main__':
    main()
