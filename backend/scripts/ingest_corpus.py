#!/usr/bin/env python3
"""Importa un corpus .gianna.json, lo indexa (denso + BM25) y opcionalmente lo publica.

Uso:
  python scripts/ingest_corpus.py CORPUS.gianna.json [--approve-technical] [--activate]

``--approve-technical`` marca los registros públicos como aprobados para poder
indexar; es un atajo de pruebas locales y NO sustituye la revisión editorial del
panel de administración.
"""
import argparse
import json
import sys
from pathlib import Path

import local_env

local_env.prepare()

from gianna.config import Config
from gianna.corpus import load_corpus
from gianna.db import Database
from gianna.security import Security
from gianna.services.jobs import Jobs
from gianna.services.knowledge import Knowledge
from gianna.services.rag import RAG
from gianna.services.runtime import Embeddings, LanceStore, Ollama
from gianna.services.settings import get_settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('corpus', type=Path)
    parser.add_argument('--approve-technical', action='store_true')
    parser.add_argument('--activate', action='store_true')
    parser.add_argument('--actor', default=None, help='id de usuario que figura en la auditoría')
    args = parser.parse_args()

    cfg = Config.from_env()
    db = Database(cfg.database_target)
    db.migrate()
    knowledge = Knowledge(db, cfg)
    embeddings, vector_store, ollama = Embeddings(cfg), LanceStore(cfg), Ollama(cfg)
    rag = RAG(db, cfg, knowledge, embeddings, vector_store, ollama, Security(db, cfg))
    jobs = Jobs(db, cfg, knowledge, embeddings, vector_store, rag)

    corpus = load_corpus(args.corpus, 'internal', None)
    existing = db.one('SELECT id FROM bases WHERE source_sha256=?', (corpus.document.sha256,))
    base_id = existing['id'] if existing else knowledge.import_corpus(corpus, corpus.document.title, args.actor, args.corpus.name)
    print(json.dumps({'stage': 'imported', 'base_id': base_id, 'reused': bool(existing)}), flush=True)
    if args.approve_technical:
        print(json.dumps({'stage': 'approved', 'records': knowledge.approve_public(base_id, args.actor)}), flush=True)
    job_id, version_id = knowledge.enqueue_build(base_id, get_settings(db, cfg), args.actor)
    claimed = jobs.claim()
    if not claimed or claimed['id'] != job_id:
        sys.exit('No se pudo reclamar el trabajo de indexación (¿hay otro trabajo en curso?).')
    jobs.execute_job(claimed)
    job = db.one('SELECT status,error,result_json FROM jobs WHERE id=?', (job_id,))
    if job['status'] != 'done':
        sys.exit('Falló la indexación: ' + str(job['error']))
    print(json.dumps({'stage': 'built', 'version_id': version_id, 'result': json.loads(job['result_json'])}, ensure_ascii=False), flush=True)
    if args.activate:
        knowledge.activate(version_id, args.actor)
        print(json.dumps({'stage': 'activated', 'version_id': version_id}), flush=True)


if __name__ == '__main__':
    main()
