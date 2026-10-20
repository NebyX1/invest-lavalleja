"""Explicit, audited local knowledge publication; never deletes an old version.

Run only on the authorized serving host. Uses backend domain services, not schema
changes or weakened HTTP controls. No credentials or private content are printed.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from backend_path import add_backend_path

ROOT = add_backend_path(__file__)
from gianna.config import Config
from gianna.corpus import load_corpus
from gianna.db import Database
from gianna.services.knowledge import Knowledge
from gianna.services.settings import get_settings
from scripts.backup import create_backup

EXPECTED_SHA256 = 'f6405e1db9cc1cd96dcd7b6d12245d619cc72ea5f01632750293c090d522562e'


def stamp():
    return datetime.now(timezone.utc).isoformat()


def write_state(path, state):
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.chmod(0o600)
    temporary.replace(path)


def snapshot_checks(db, knowledge, cfg, state):
    from gianna.services.vector_store import LanceStore
    version = db.one('SELECT * FROM versions WHERE id=?', (state['version_id'],))
    if not version or version['status'] != 'ready':
        raise RuntimeError('La nueva versión no está lista; no se activó.')
    exported = knowledge.export(state['base_id'])
    expected = {r.id: r.model_dump() for r in exported.records if r.audience == 'public' and r.enabled}
    rows = db.all('SELECT record_key,content_json FROM version_records WHERE version_id=?', (version['id'],))
    actual = {r['record_key']: json.loads(r['content_json']) for r in rows}
    if actual != expected or len(actual) != 332:
        raise RuntimeError('El snapshot público no coincide exactamente con los 332 registros autorizados.')
    private = {r.id for r in exported.records if r.audience == 'internal'}
    chunks = db.all('SELECT record_key,token_count FROM chunks WHERE version_id=?', (version['id'],))
    if {c['record_key'] for c in chunks} != set(expected) or private & {c['record_key'] for c in chunks}:
        raise RuntimeError('La cobertura de los fragmentos o las audiencias no coincide.')
    profile = json.loads(version['profile_json'])
    if max(c['token_count'] for c in chunks) > profile['chunk_tokens']:
        raise RuntimeError('Hay fragmentos fuera del presupuesto.')
    store = LanceStore(cfg)
    if store.count(version['collection_name']) != len(chunks):
        raise RuntimeError('El conteo de LanceDB no coincide con MariaDB.')
    old = db.one('SELECT * FROM versions WHERE id=?', (state['previous_version'],))
    if not old or not old['published_at'] or not store.exists(old['collection_name']):
        raise RuntimeError('La versión anterior no está preservada para reversión.')
    return {'public_records': len(actual), 'internal_excluded': len(private), 'chunks': len(chunks),
            'max_tokens': max(c['token_count'] for c in chunks), 'collection': version['collection_name'],
            'fingerprint': profile['fingerprint'], 'old_collection_preserved': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'status', 'activate'])
    parser.add_argument('--corpus', type=Path)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--confirm-user-authorized-publication', action='store_true')
    args = parser.parse_args()
    if args.action != 'status' and not args.confirm_user_authorized_publication:
        raise SystemExit('Se requiere autorización explícita de publicación.')
    cfg = Config.from_env()  # Secrets remain in process memory, never in state/logs.
    db = Database(cfg.database_target); knowledge = Knowledge(db, cfg)
    if not args.state.resolve().is_relative_to((cfg.data_dir / 'operations').resolve()):
        raise SystemExit('El estado debe guardarse en DATA_DIR/operations.')
    args.state.parent.mkdir(parents=True, exist_ok=True)
    if args.action == 'prepare':
        if args.state.exists():
            raise SystemExit('Ya existe la operación. Consultá status; no se duplicó la importación.')
        if not args.corpus or hashlib.sha256(args.corpus.read_bytes()).hexdigest() != EXPECTED_SHA256:
            raise SystemExit('La huella del corpus no coincide con el consolidado revisado.')
        corpus = load_corpus(args.corpus)
        if Counter(r.audience for r in corpus.records) != {'public': 332, 'internal': 75} or len(corpus.sources) != 172:
            raise SystemExit('El corpus no coincide con los conteos revisados.')
        before = knowledge.active()
        if not before or before['status'] != 'ready':
            raise SystemExit('Se esperaba una base activa lista para reemplazar y conservar.')
        if not cfg.worker_enabled:
            raise SystemExit('El trabajador del servidor debe estar habilitado.')
        backup = cfg.data_dir / 'backups' / (args.state.stem + '-before.sql')
        if backup.exists():
            raise SystemExit('Ya existe el respaldo; no se sobrescribió.')
        backup = create_backup(cfg, backup)
        backup_hash = hashlib.sha256()
        with backup.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                backup_hash.update(block)
        state = {'created_at': stamp(), 'corpus_sha256': EXPECTED_SHA256,
                 'previous_version': before['id'], 'previous_base': before['base_id'],
                 'backup_path': str(backup), 'backup_integrity': 'mariadb_dump_nonempty',
                 'backup_sha256': backup_hash.hexdigest(), 'backup_size_bytes': backup.stat().st_size,
                 'authorization': 'Explicit user request: Debes reemplazar la base de conocimiento actual con la nueva',
                 'stage': 'backed_up'}
        write_state(args.state, state)
        db.audit(None, 'LOCAL_USER_KNOWLEDGE_REPLACEMENT_AUTHORIZED', before['id'],
                 {'corpus_sha256': EXPECTED_SHA256, 'public': 332, 'internal_excluded': 75,
                  'basis': 'User explicitly requested publication after consolidation review; not blanket factual certification.'})
        base_id = knowledge.import_corpus(corpus, corpus.document.title, None, corpus.document.filename)
        state.update(base_id=base_id, stage='imported_draft'); write_state(args.state, state)
        exported = knowledge.export(base_id)
        if {r.id:r.model_dump() for r in exported.records} != {r.id:r.model_dump() for r in corpus.records}:
            raise RuntimeError('La importación no conservó exactamente los registros.')
        ids = [r['id'] for r in db.all("SELECT id FROM records WHERE base_id=? AND audience='public' AND enabled=1", (base_id,))]
        if knowledge.approve_public(base_id, None, ids) != 332:
            raise RuntimeError('No se aprobó la selección pública esperada.')
        if db.one("SELECT COUNT(*) n FROM records WHERE base_id=? AND audience='internal' AND approved=1", (base_id,))['n']:
            raise RuntimeError('Se aprobó contenido interno inesperadamente.')
        job_id, version_id = knowledge.enqueue_build(base_id, get_settings(db, cfg), None)
        state.update(job_id=job_id, version_id=version_id, stage='index_queued', model=get_settings(db, cfg).model)
        write_state(args.state, state)
    else:
        state = json.loads(args.state.read_text(encoding='utf-8'))
        if state['corpus_sha256'] != EXPECTED_SHA256:
            raise SystemExit('La operación pertenece a otro documento.')
        if args.action == 'activate':
            if knowledge.active()['id'] not in {state['previous_version'], state['version_id']}:
                raise RuntimeError('La versión activa cambió por otra operación. No se reemplazó.')
            check = snapshot_checks(db, knowledge, cfg, state)
            if knowledge.active()['id'] != state['version_id']:
                knowledge.activate(state['version_id'], None)
            state.update(stage='activated', activated_at=stamp(), validation=check)
            write_state(args.state, state)
    state['active_version_now'] = knowledge.active()['id'] if knowledge.active() else None
    if state.get('job_id'):
        state['job'] = db.one('SELECT status,progress,total,message,error FROM jobs WHERE id=?', (state['job_id'],))
    print(json.dumps(state, ensure_ascii=True))


if __name__ == '__main__':
    main()
