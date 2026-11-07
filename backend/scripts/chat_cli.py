#!/usr/bin/env python3
"""Conversación de prueba contra el agente, sin HTTP ni captcha.

Uso: python scripts/chat_cli.py "pregunta 1" "pregunta 2" [--version ID] [--trace]
Las preguntas se hacen en orden dentro de una misma conversación.
"""
import argparse
import sys
import time

import local_env

local_env.prepare()

from gianna.config import Config
from gianna.db import Database
from gianna.security import Security
from gianna.services.context_budget import retain_history
from gianna.services.knowledge import Knowledge
from gianna.services.rag import RAG
from gianna.services.runtime import Embeddings, LanceStore, Ollama
from gianna.services.settings import get_settings


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('questions', nargs='+')
    parser.add_argument('--version')
    parser.add_argument('--trace', action='store_true')
    parser.add_argument('--separate', action='store_true', help='cada pregunta es una conversación nueva')
    args = parser.parse_args()
    cfg = Config.from_env()
    db = Database(cfg.database_target)
    knowledge = Knowledge(db, cfg)
    embeddings = Embeddings(cfg)
    rag = RAG(db, cfg, knowledge, embeddings, LanceStore(cfg), Ollama(cfg), Security(db, cfg))
    settings = get_settings(db, cfg)
    version = rag.retriever.version(args.version)
    import json
    embeddings.for_profile(json.loads(version['profile_json'])).load()
    history = []
    for question in args.questions:
        started = time.time()
        result = rag.answer(question, settings, history=history, version_id=version['id'], preview=True)
        print('=' * 90)
        print('PREGUNTA:', question, f'  [{time.time() - started:.1f}s, {result["status"]}, llamadas={result["timings"]["model_requests"]}]')
        print(result['answer'])
        print('FUENTES:', ' | '.join(f'[{c["id"]}] {c["title"]}' for c in result['citations']) or '(ninguna)')
        if args.trace:
            row = db.one('SELECT retrieval_trace_json FROM queries WHERE id=?', (result['id'],))
            print('TRAZA:', row['retrieval_trace_json'])
        history = [] if args.separate else retain_history(history + [{'role': 'user', 'content': question},
                                            {'role': 'assistant', 'content': result['answer']}])


if __name__ == '__main__':
    main()
