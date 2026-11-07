"""Verified frozen sources are independent; malformed fallbacks cannot poison SQL."""
import copy
import json

import pytest

from gianna.errors import DomainError
from gianna.services.recovery import digest, snapshot
from gianna.services.storage import atomic_json
from test_knowledge_recovery import seed


@pytest.fixture
def sources(db, cfg, knowledge, corpus):
    engine, version = seed(db, cfg, knowledge, corpus)
    data = snapshot(db, cfg, version)
    path = cfg.data_dir / 'recovery' / 'backups' / (version['id'] + '.json')
    return db, cfg, version, data, path


@pytest.mark.parametrize('damage', ['vector', 'metadata', 'coverage', 'digest', 'json'])
def test_invalid_optional_backup_does_not_block_valid_sql(sources, damage):
    db, cfg, version, data, path = sources
    backup = copy.deepcopy(data)
    if damage == 'vector':
        backup['rows'][0]['vector'] = [1, 2]
    elif damage == 'metadata':
        backup['rows'][0]['audience'] = 'internal'
    elif damage == 'coverage':
        backup['rows'] = backup['rows'][:-1]
    backup['digest'] = 'invalid' if damage == 'digest' else digest(backup['rows'])
    if damage == 'json':
        path.parent.mkdir(parents=True)
        path.write_text('{')
    else:
        atomic_json(path, backup)
    original = path.read_bytes()
    result = snapshot(db, cfg, version)
    assert result['rows'] == data['rows']
    assert result['source_counts']['sql'] == len(data['rows'])
    assert result['invalid_sources']['backup'] == 1
    assert path.read_bytes() == original


def test_verified_backup_recovers_invalid_sql_without_rewriting_snapshot(sources):
    db, cfg, version, data, path = sources
    atomic_json(path, data)
    db.execute("UPDATE chunks SET vector_json='[1,2]'")
    before = db.all('SELECT * FROM chunks ORDER BY id')
    result = snapshot(db, cfg, version)
    assert result['rows'] == data['rows'] and result['backup_used']
    assert result['invalid_sources']['sql'] == len(data['rows'])
    assert db.all('SELECT * FROM chunks ORDER BY id') == before


def test_valid_disagreeing_backup_and_sql_still_require_supervision(sources):
    db, cfg, version, data, path = sources
    backup = copy.deepcopy(data)
    backup['rows'][0]['vector'] = [0.0, 1.0] + [0.0] * 382
    backup['digest'] = digest(backup['rows'])
    atomic_json(path, backup)
    with pytest.raises(DomainError) as error:
        snapshot(db, cfg, version)
    assert error.value.code == 'snapshot_invalid'
    assert error.value.details['reason'] == 'backup_sql_disagreement'


def test_invalid_cache_cannot_poison_valid_backup(sources):
    db, cfg, version, data, path = sources
    atomic_json(path, data)
    for row in db.all('SELECT * FROM chunks'):
        db.execute('INSERT INTO embedding_cache VALUES(?,?,?,?,?)',
                   (data['fingerprint'], row['embedding_hash'], 'malformed', '"unused"', 0))
    db.execute('UPDATE chunks SET vector_json=NULL')
    result = snapshot(db, cfg, version)
    assert result['rows'] == data['rows']
    assert result['invalid_sources']['cache'] == len(data['rows'])


def test_valid_cache_disagreeing_with_backup_does_not_choose_arbitrarily(sources):
    db, cfg, version, data, path = sources
    atomic_json(path, data)
    for row in db.all('SELECT * FROM chunks'):
        db.execute('INSERT INTO embedding_cache VALUES(?,?,?,?,?)',
                   (data['fingerprint'], row['embedding_hash'], json.dumps([0, 1] + [0] * 382), '"unused"', 0))
    db.execute('UPDATE chunks SET vector_json=NULL')
    with pytest.raises(DomainError) as error:
        snapshot(db, cfg, version)
    assert error.value.details['reason'] == 'vector_sources_disagree'


def test_malformed_profile_shape_reports_profile_validation(sources):
    db, cfg, version, data, path = sources
    broken = {**version, 'profile_json': '[]'}
    with pytest.raises(DomainError) as error:
        snapshot(db, cfg, broken)
    assert error.value.details['reason'] == 'profile'


def test_exact_fingerprint_cache_recovers_invalid_sql_and_rejects_other_profiles(sources):
    db, cfg, version, data, path = sources
    for row in db.all('SELECT * FROM chunks'):
        db.execute('INSERT INTO embedding_cache VALUES(?,?,?,?,?)',
                   (data['fingerprint'], row['embedding_hash'], row['vector_json'], '"unused"', 0))
    db.execute("UPDATE chunks SET vector_json='not-json'")
    result = snapshot(db, cfg, version)
    assert result['rows'] == data['rows'] and result['source_counts']['cache'] == len(data['rows'])
    db.execute("UPDATE embedding_cache SET fingerprint='other-profile'")
    with pytest.raises(DomainError) as error:
        snapshot(db, cfg, version)
    assert error.value.details['reason'] == 'missing_vector'


def test_snapshot_diagnostic_reason_has_counts_but_no_record_text(sources):
    db, cfg, version, data, path = sources
    db.execute('DELETE FROM chunks WHERE id=?', (data['rows'][0]['id'],))
    with pytest.raises(DomainError) as error:
        snapshot(db, cfg, version)
    assert error.value.details['reason'] == 'count'
    assert error.value.details['expected_chunks'] == len(data['rows'])
    assert error.value.details['actual_chunks'] == len(data['rows']) - 1
    assert 'Requiere permiso' not in json.dumps(error.value.details)
