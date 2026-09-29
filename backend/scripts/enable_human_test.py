"""Activate public records in the isolated loopback-only human-test stack.

This is a technical test selection, not editorial approval. Never run in the
operational or production stack. The Config guard enforces local test mode.
"""
import argparse
import json
import time
from pathlib import Path

from gianna.config import Config
from gianna.corpus import load_corpus
from gianna.db import Database
from gianna.services.knowledge import Knowledge
from gianna.services.runtime import Qdrant
from gianna.services.settings import get_settings


ACTOR = 'local-human-test-not-editorial-review'


def announce(stage, **data):
    print(json.dumps({'stage': stage, **data}, ensure_ascii=False), flush=True)


def enable(corpus_path: Path, cfg: Config, timeout: int = 900):
    if not cfg.human_test_mode or cfg.production:
        raise RuntimeError('Solo se puede activar en modo de prueba humana local.')
    if not cfg.ollama_api_key or not cfg.ollama_model:
        raise RuntimeError('Falta configurar Ollama para la prueba humana.')
    corpus = load_corpus(corpus_path)
    public_count = sum(r.audience == 'public' and r.enabled for r in corpus.records)
    internal_count = sum(r.audience == 'internal' for r in corpus.records)
    if not public_count:
        raise RuntimeError('El corpus no tiene registros públicos habilitados.')
    db = Database(cfg.db_path)
    db.migrate()
    knowledge = Knowledge(db, cfg)
    existing = db.one('SELECT id FROM bases WHERE source_sha256=?', (corpus.document.sha256,))
    base_id = existing['id'] if existing else knowledge.import_corpus(
        corpus, corpus.document.title, ACTOR, corpus.document.filename
    )
    actual = db.one("""SELECT COUNT(*) AS total,
        SUM(CASE WHEN audience='public' AND enabled=1 THEN 1 ELSE 0 END) AS public,
        SUM(CASE WHEN audience='internal' THEN 1 ELSE 0 END) AS internal
        FROM records WHERE base_id=?""", (base_id,))
    if (actual['total'] != len(corpus.records) or actual['public'] != public_count
            or actual['internal'] != internal_count):
        raise RuntimeError('La base importada no coincide con el corpus local.')
    announce('corpus', public_records=public_count, internal_excluded=internal_count)

    active = knowledge.active()
    if active:
        if active['base_id'] != base_id:
            raise RuntimeError('Hay otra base activa en este entorno de prueba.')
        version_id = active['id']
    else:
        knowledge.approve_public(base_id, ACTOR)
        base = knowledge.require_base(base_id)
        ready = db.one("""SELECT * FROM versions WHERE base_id=? AND revision=?
            AND status='ready' ORDER BY created_at DESC LIMIT 1""", (base_id, base['revision']))
        if ready:
            version_id = ready['id']
        else:
            pending = db.one("""SELECT version_id,id FROM jobs WHERE base_id=? AND kind='build'
                AND status IN ('queued','running') ORDER BY created_at DESC LIMIT 1""", (base_id,))
            if pending:
                job_id, version_id = pending['id'], pending['version_id']
            else:
                job_id, version_id = knowledge.enqueue_build(base_id, get_settings(db, cfg), ACTOR)
            announce('indexing', job_id=job_id)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                job = db.one('SELECT status,error FROM jobs WHERE id=?', (job_id,))
                if job['status'] == 'done':
                    break
                if job['status'] in {'failed', 'cancelled'}:
                    raise RuntimeError('Falló la indexación: ' + str(job['error']))
                time.sleep(2)
            else:
                raise TimeoutError('La indexación no terminó dentro del plazo; revisá el trabajo.')

    version = db.one('SELECT * FROM versions WHERE id=?', (version_id,))
    if not version or version['status'] != 'ready' or not version['chunk_count']:
        raise RuntimeError('La versión de prueba no está lista.')
    records = db.one("""SELECT COUNT(*) AS total,
        SUM(CASE WHEN json_extract(content_json,'$.audience')='internal' THEN 1 ELSE 0 END) AS internal
        FROM version_records WHERE version_id=?""", (version_id,))
    if records['total'] != public_count or records['internal']:
        raise RuntimeError('La versión no contiene exactamente los registros públicos esperados.')
    if Qdrant(cfg).count(version['collection_name']) != version['chunk_count']:
        raise RuntimeError('El índice vectorial de prueba está incompleto.')
    if not active:
        knowledge.activate(version_id, ACTOR)
    announce('active_for_local_human_test', version_id=version_id,
             public_records=public_count, chunks=version['chunk_count'], editorially_approved=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('corpus', type=Path)
    args = parser.parse_args()
    enable(args.corpus, Config.from_env())


if __name__ == '__main__':
    main()
