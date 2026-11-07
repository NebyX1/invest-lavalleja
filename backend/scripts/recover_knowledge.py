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
from gianna.services.installation import Installation
from gianna.observability import configure_logging, event, safe_exception


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version-id',help='Defaults to the active immutable version.')
    parser.add_argument('--apply',action='store_true',help='Restore missing technical dependencies after validating the snapshot.')
    parser.add_argument('--adopt-storage',action='store_true',help='Explicitly accept an inspected replacement volume; requires --apply and a recoverable backup.')
    parser.add_argument('--inspect-installation',action='store_true',help='Inspect SQL, storage, indexes, models and queue without changing the installation.')
    args=parser.parse_args(argv)
    if args.adopt_storage and not args.apply:parser.error('--adopt-storage requiere --apply.')
    configure_logging()
    try:
        cfg=Config.from_env(initialize_storage=False)
        db=Database(cfg.database_target)
        # No migrate(), create_app() or workers: diagnosis never edits SQL.
        knowledge=Knowledge(db,cfg)
        version=db.one('SELECT * FROM versions WHERE id=?',(args.version_id,)) if args.version_id else knowledge.active()
        if args.version_id and not version:raise DomainError('Versión no encontrada.',404,'no_knowledge')
        store=LanceStore(cfg)
        recovery=KnowledgeRecovery(db,cfg,knowledge,Embeddings(cfg),store)
        installation=Installation(db,cfg,knowledge,store,recovery)
        if args.inspect_installation:
            if args.apply or args.adopt_storage:parser.error('--inspect-installation no admite opciones de escritura.')
            result=installation.inspect()
            print(json.dumps(result,ensure_ascii=False,sort_keys=True))
            return 1 if result['state']=='blocked' else 0
        report=installation.inspect()
        blocking=[check for check in report['checks'] if check['status']=='blocked']
        adoption_only=args.adopt_storage and all(check['code'] in {'storage_mismatch','physical_inspection_blocked'} for check in blocking)
        if report['state']=='blocked' and not adoption_only:
            print(json.dumps(report,ensure_ascii=False,sort_keys=True))
            return 1
        if args.apply and not args.adopt_storage:
            report=installation.reconcile(force=True)
            if report['state']=='blocked':
                print(json.dumps(report,ensure_ascii=False,sort_keys=True))
                return 1
        result=recovery.recover(version,apply=args.apply,adopt_storage=args.adopt_storage)
        result['installation']=report
        print(json.dumps(result,ensure_ascii=False,sort_keys=True))
        return 0
    except DomainError as exc:
        event(logging.getLogger(__name__),'cli.recovery_blocked',level=logging.ERROR,
              code=exc.code,exception=safe_exception(exc))
        print(json.dumps({'state':'failed','code':exc.code,'message':exc.message,
                          'details':getattr(exc,'details',{})},ensure_ascii=False))
        return 1
    except Exception as exc:
        event(logging.getLogger(__name__),'cli.recovery_failed',level=logging.ERROR,
              exception=safe_exception(exc))
        # Do not echo URLs, connection strings, tracebacks or filesystem paths.
        print(json.dumps({'state':'failed','code':'diagnostic_failed','type':type(exc).__name__}))
        return 1


if __name__=='__main__':
    sys.exit(main())
