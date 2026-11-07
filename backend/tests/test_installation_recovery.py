"""SQL state + real LanceDB inventory, with an explicitly deterministic model double."""
from dataclasses import replace
import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest

from gianna.db import dumps
from gianna.services.installation import Installation
from gianna.services.recovery import KnowledgeRecovery, snapshot
from gianna.services.storage import atomic_json, storage_identity
from gianna.services.vector_store import LanceStore
from test_knowledge_recovery import LocalEngine, editorial_state, seed


@pytest.fixture
def existing_installation(db, cfg, knowledge, corpus, monkeypatch):
    pytest.importorskip('lancedb')
    monkeypatch.setattr('gianna.services.artifacts.ensure_models', lambda *args: None)
    engine, version = seed(db, cfg, knowledge, corpus)
    store = LanceStore(cfg)
    recovery = KnowledgeRecovery(db, cfg, knowledge, engine, store)
    inspection = Installation(db, cfg, knowledge, store, recovery)
    return SimpleNamespace(db=db, cfg=cfg, knowledge=knowledge, engine=engine,
                           version=version, store=store, recovery=recovery, inspection=inspection)


def files(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file()}


def test_fresh_database_and_no_physical_data_are_empty_without_publishing(db, cfg, knowledge):
    pytest.importorskip('lancedb')
    engine = LocalEngine()
    store = LanceStore(cfg)
    recovery = KnowledgeRecovery(db, cfg, knowledge, engine, store)
    inspection = Installation(db, cfg, knowledge, store, recovery)
    before = editorial_state(db)
    report = inspection.inspect()
    assert report['state'] == 'empty' and report['code'] == 'no_knowledge'
    assert report['database']['counts']['versions'] == 0
    assert report['lance']['collections'] == []
    assert not cfg.lance_dir.exists() and knowledge.active() is None
    assert editorial_state(db) == before


def test_lance_without_sql_versions_is_preserved_and_requires_sql_recovery(db, cfg, knowledge):
    pytest.importorskip('lancedb')
    engine = LocalEngine()
    store = LanceStore(cfg)
    store.create('gianna_orphan')
    recovery = KnowledgeRecovery(db, cfg, knowledge, engine, store)
    before = files(cfg.lance_dir)
    report = Installation(db, cfg, knowledge, store, recovery).inspect()
    assert report['state'] == 'blocked' and report['code'] == 'database_state_missing'
    assert report['lance']['orphans'] == ['gianna_orphan']
    assert files(cfg.lance_dir) == before and knowledge.active() is None


def test_dangling_sql_publication_is_not_treated_as_empty(existing_installation):
    p = existing_installation
    # Only this disposable SQLite fixture bypasses FK checks to represent an
    # inconsistent imported database. Application connections always enforce FKs.
    with sqlite3.connect(p.db.path) as connection:
        connection.execute("UPDATE active_knowledge SET version_id='missing-version'")
    before = editorial_state(p.db)
    report = p.inspection.inspect()
    assert report['state'] == 'blocked' and report['code'] == 'active_reference_invalid'
    assert editorial_state(p.db) == before


def test_verified_backup_makes_invalid_sql_vectors_recoverable_without_rewriting_them(existing_installation):
    p = existing_installation
    data = snapshot(p.db, p.cfg, p.version)
    atomic_json(p.cfg.data_dir / 'recovery/backups' / (p.version['id'] + '.json'), data)
    p.db.execute("UPDATE chunks SET vector_json='invalid-json'")
    before = editorial_state(p.db)
    report = p.inspection.inspect()
    assert report['state'] == 'recoverable'
    assert any(step['action'] == 'restore_index' for step in report['plan'])
    assert editorial_state(p.db) == before
    p.recovery.recover(apply=True)
    assert p.recovery.status()['available']
    assert p.store.count(p.version['collection_name']) == p.version['chunk_count']
    assert editorial_state(p.db) == before


def test_runtime_incompatibility_is_classified_before_model_preparation(existing_installation):
    p = existing_installation
    profile = json.loads(p.version['profile_json'])
    profile['onnxruntime'] = '0.0-unavailable-runtime'
    p.db.execute('UPDATE versions SET profile_json=? WHERE id=?', (dumps(profile), p.version['id']))
    before = editorial_state(p.db)
    report = p.inspection.inspect()
    assert report['state'] == 'blocked' and report['code'] == 'runtime_profile_mismatch'
    assert p.engine.loads == 0 and not p.cfg.lance_dir.exists()
    assert editorial_state(p.db) == before


def test_inspection_of_healthy_publication_does_not_write_or_load_models(existing_installation):
    p = existing_installation
    p.recovery.recover(apply=True)
    before = editorial_state(p.db)
    settings = p.db.all('SELECT * FROM settings ORDER BY `key`')
    physical = files(p.cfg.data_dir)
    loads = p.engine.loads
    report = p.inspection.inspect()
    assert report['state'] == 'ready'
    assert p.engine.loads == loads
    assert editorial_state(p.db) == before and p.db.all('SELECT * FROM settings ORDER BY `key`') == settings
    assert files(p.cfg.data_dir) == physical


def test_inspection_never_adopts_an_unexpected_existing_volume(existing_installation, tmp_path):
    p = existing_installation
    storage_identity(p.db, p.cfg, write=True)
    before = p.db.setting('physical_storage_identity')
    replacement = replace(p.cfg, data_dir=tmp_path / 'other-volume')
    replacement.data_dir.mkdir()
    inspection = Installation(p.db, replacement, p.knowledge, LanceStore(replacement), p.recovery)
    report = inspection.inspect()
    assert report['state'] == 'blocked' and report['code'] == 'storage_mismatch'
    assert p.db.setting('physical_storage_identity') == before
    assert list(replacement.data_dir.iterdir()) == []
