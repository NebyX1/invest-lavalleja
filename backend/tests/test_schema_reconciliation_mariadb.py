"""Physical schema drift on disposable, strict MariaDB; no history reset as repair."""
import time

import pytest

from gianna.db import dumps
from gianna.errors import DomainError
from test_mariadb_import import maria_db, maria_server  # noqa: F401 -- shared opt-in fixtures


def seed_sentinels(db):
    now = time.time()
    db.execute('INSERT INTO settings(`key`,value) VALUES(?,?)',
               ('schema-reconciliation-sentinel', dumps({'keep': 'configuration'})))
    db.execute('INSERT INTO users(id,email,name,role,password_hash,created_at) VALUES(?,?,?,?,?,?)',
               ('layout-user', 'layout@example.test', 'Schema fixture', 'owner', 'fixture-hash', now))
    db.execute('INSERT INTO bases(id,name,description,created_at,updated_at) VALUES(?,?,?,?,?)',
               ('layout-base', 'Preserve editorial state', 'Existing description', now, now))
    db.execute('INSERT INTO versions(id,base_id,revision,status,collection_name,profile_json,created_at,published_at) '
               'VALUES(?,?,?,?,?,?,?,?)',
               ('layout-version', 'layout-base', 1, 'ready', 'gianna_layout_version', dumps({'keep': 'profile'}), now, now))
    db.execute('UPDATE active_knowledge SET version_id=? WHERE singleton=1', ('layout-version',))
    db.execute('INSERT INTO jobs(id,kind,status,version_id,payload_json,created_at,attempts,stage,error_code) '
               'VALUES(?,?,?,?,?,?,?,?,?)',
               ('layout-job', 'evaluation', 'failed', 'layout-version', dumps({'keep': 'job payload'}), now, 2, 'failed', 'fixture-failure'))
    db.execute('INSERT INTO job_events(job_id,at,event,attempt,stage,message,details_json) VALUES(?,?,?,?,?,?,?)',
               ('layout-job', now, 'fixture-event', 2, 'failed', 'Preserve event', dumps({'keep': 'history'})))


def preserved(db):
    return {
        'users': db.all('SELECT * FROM users ORDER BY id'),
        'settings': db.all('SELECT * FROM settings ORDER BY `key`'),
        'bases': db.all('SELECT * FROM bases ORDER BY id'),
        'versions': db.all('SELECT * FROM versions ORDER BY id'),
        'publication': db.all('SELECT * FROM active_knowledge'),
        # stage may be the deliberately dropped field: the surviving job data
        # must remain unchanged while its known operational column is restored.
        'jobs': db.all('SELECT id,kind,status,version_id,payload_json,created_at,attempts,error_code '
                       'FROM jobs ORDER BY id'),
        'job_events': db.all('SELECT * FROM job_events ORDER BY id'),
    }


def test_default_drift_is_detected_and_repaired_without_removing_history(maria_db):
    db = maria_db
    seed_sentinels(db)
    state = preserved(db)
    history = db.all('SELECT * FROM schema_versions ORDER BY version')
    db.execute('ALTER TABLE bases ALTER COLUMN description DROP DEFAULT')
    review = db.review_schema()
    assert not review['ok'] and review['repairs'] == []
    assert {'table': 'bases', 'column': 'description', 'expected': ''} in review['default_drift']
    db.migrate()
    assert db.review_schema()['ok']
    assert preserved(db) == state
    assert db.all('SELECT * FROM schema_versions ORDER BY version') == history
    now = time.time()
    db.execute('INSERT INTO bases(id,name,created_at,updated_at) VALUES(?,?,?,?)',
               ('after-repair', 'Minimal insert works', now, now))
    assert db.one('SELECT description FROM bases WHERE id=?', ('after-repair',))['description'] == ''


def test_default_containing_a_literal_apostrophe_is_not_mistaken_for_empty(maria_db):
    db = maria_db
    seed_sentinels(db)
    state = preserved(db)
    history = db.all('SELECT * FROM schema_versions ORDER BY version')
    db.execute("ALTER TABLE bases ALTER COLUMN description SET DEFAULT ''''")
    review = db.review_schema()
    assert not review['ok']
    assert {'table': 'bases', 'column': 'description', 'expected': ''} in review['default_drift']
    db.migrate()
    assert db.review_schema()['ok'] and preserved(db) == state
    assert db.all('SELECT * FROM schema_versions ORDER BY version') == history


def test_known_queue_column_and_missing_journal_are_repaired_without_clobbering_data(maria_db):
    db = maria_db
    seed_sentinels(db)
    state = preserved(db)
    history = db.all('SELECT * FROM schema_versions ORDER BY version')
    db.execute('ALTER TABLE jobs DROP COLUMN stage')
    db.execute('DROP TABLE operational_events')
    review = db.review_schema()
    assert 'stage' in review['missing_columns']['jobs']
    assert 'operational_events' in review['missing_columns']
    db.migrate()
    assert db.review_schema()['ok']
    assert preserved(db) == state
    assert db.all('SELECT * FROM schema_versions ORDER BY version') == history
    assert db.one('SELECT COUNT(*) AS n FROM operational_events')['n'] == 0


def test_partial_idempotent_migration_reenters_and_preserves_existing_columns_and_rows(maria_db):
    db = maria_db
    seed_sentinels(db)
    state = preserved(db)
    earlier = db.all('SELECT * FROM schema_versions WHERE version<5 ORDER BY version')
    # Simulate an interrupted 005 before its completion marker: most added
    # columns and job_events already exist, but the final pieces do not.
    db.execute('DELETE FROM schema_versions WHERE version=5')
    db.execute('ALTER TABLE jobs DROP COLUMN recovery_boot_id')
    db.execute('DROP TABLE operational_events')
    db.migrate()
    db.migrate()
    assert db.review_schema()['ok']
    assert preserved(db) == state
    assert db.all('SELECT * FROM schema_versions WHERE version<5 ORDER BY version') == earlier
    assert db.one('SELECT COUNT(*) AS n FROM schema_versions WHERE version=5')['n'] == 1


def test_missing_editorial_column_blocks_before_other_repairs(maria_db):
    db = maria_db
    seed_sentinels(db)
    history = db.all('SELECT * FROM schema_versions ORDER BY version')
    db.execute('ALTER TABLE versions DROP COLUMN profile_json')
    db.execute('ALTER TABLE jobs DROP COLUMN stage')
    db.execute('ALTER TABLE bases ALTER COLUMN description DROP DEFAULT')
    state = preserved(db)
    review = db.review_schema()
    assert 'profile_json' in review['missing_columns']['versions']
    with pytest.raises(DomainError) as error:
        db.migrate()
    assert error.value.code == 'database_schema_incompatible'
    after = db.review_schema()
    assert after['repairs'] == [] and 'stage' in after['missing_columns']['jobs']
    assert {'table': 'bases', 'column': 'description', 'expected': ''} in after['default_drift']
    assert preserved(db) == state
    assert db.all('SELECT * FROM schema_versions ORDER BY version') == history
