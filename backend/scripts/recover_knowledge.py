"""Diagnose or restore the same immutable version. No publication operations."""
import argparse
import json
import logging
import sys

from gianna.config import Config
from gianna.db import Database
from gianna.errors import DomainError
from gianna.services.knowledge import Knowledge
from gianna.services.neural import Embeddings
from gianna.services.recovery import KnowledgeRecovery
from gianna.services.vector_store import LanceStore


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version-id',help='Defaults to the active immutable version.')
    parser.add_argument('--apply',action='store_true',help='Restore missing technical dependencies after validating the snapshot.')
    parser.add_argument('--adopt-storage',action='store_true',help='Explicitly accept an inspected replacement volume; requires --apply and a recoverable backup.')
    args=parser.parse_args(argv)
    if args.adopt_storage and not args.apply:parser.error('--adopt-storage requiere --apply.')
    logging.basicConfig(level=logging.INFO)
    try:
        cfg=Config.from_env(initialize_storage=args.apply)
        db=Database(cfg.database_target)
        # No migrate(), create_app() or workers: diagnosis never edits SQL.
        knowledge=Knowledge(db,cfg)
        version=db.one('SELECT * FROM versions WHERE id=?',(args.version_id,)) if args.version_id else knowledge.active()
        if args.version_id and not version:raise DomainError('Versión no encontrada.',404,'no_knowledge')
        recovery=KnowledgeRecovery(db,cfg,knowledge,Embeddings(cfg),LanceStore(cfg))
        result=recovery.recover(version,apply=args.apply,adopt_storage=args.adopt_storage)
        print(json.dumps(result,ensure_ascii=False,sort_keys=True))
        return 0
    except DomainError as exc:
        print(json.dumps({'state':'failed','code':exc.code,'message':exc.message},ensure_ascii=False))
        return 1
    except Exception as exc:
        # Do not echo URLs, connection strings, tracebacks or filesystem paths.
        print(json.dumps({'state':'failed','code':'diagnostic_failed','type':type(exc).__name__}))
        return 1


if __name__=='__main__':
    sys.exit(main())
