"""Operational diagnosis is authenticated, read-only and useful without models."""
import json
import time
from dataclasses import replace

import pytest

from gianna import create_app
from gianna.db import Database
from gianna.errors import DomainError
from gianna.services.operations import record_event
from test_web import authenticate


@pytest.fixture
def app(cfg):
    instance=create_app(cfg)
    instance.config['TESTING']=True
    return instance


def test_empty_installation_diagnostic_is_read_only_and_explains_components(app):
    service=app.extensions['gianna']
    client=app.test_client()
    assert client.get('/admin/api/diagnostics').status_code in {302,401,403}
    authenticate(app,client)
    before=set(service.cfg.data_dir.rglob('*'))
    result=client.get('/admin/api/diagnostics')
    assert result.status_code==200
    report=result.json['installation']
    assert report['state']=='empty'
    assert report['database']['counts']['bases']==0
    assert report['lance']['collections']==[]
    assert result.json['worker']['enabled'] is False
    assert before==set(service.cfg.data_dir.rglob('*'))
    assert service.db.setting('runtime_installation_report') is None
    page=client.get('/admin/diagnostics')
    assert page.status_code==200
    assert report['boot_id'] in page.get_data(as_text=True)


def test_preflight_binds_new_storage_once_without_modifying_editorial_data(app):
    s=app.extensions['gianna']
    before={name:s.db.all('SELECT * FROM '+name) for name in ('bases','versions','chunks','active_knowledge')}
    first=s.installation.reconcile()
    assert first['state']=='empty'
    identity=s.db.setting('physical_storage_identity')
    assert identity
    first_events=s.db.one('SELECT COUNT(*) n FROM operational_events')['n']
    second=s.installation.reconcile()
    assert second['report_id']==first['report_id']
    assert s.db.setting('physical_storage_identity')==identity
    assert s.db.one('SELECT COUNT(*) n FROM operational_events')['n']==first_events
    assert {name:s.db.all('SELECT * FROM '+name) for name in before}==before


def test_job_status_shows_worker_attempt_action_and_preserves_privacy(app):
    s=app.extensions['gianna'];client=app.test_client();authenticate(app,client)
    job=s.jobs.enqueue('warmup',{'private':'never-return-this-payload'})
    row=s.jobs.describe_job(job)
    assert row['status']=='queued' and row['attempts']==0
    response=client.get('/admin/api/jobs/'+job)
    assert response.status_code==200
    body=response.get_data(as_text=True)
    assert 'never-return-this-payload' not in body and 'owner_token' not in body
    assert 'worker' in response.json and 'installation' in response.json
    assert 'events' in response.json and 'available_at' in response.json


def test_operations_journal_is_correlated_and_redacted(app):
    s=app.extensions['gianna'];client=app.test_client();authenticate(app,client)
    event=record_event(s.db,'test.job_failed',job_id='test-job',stage='storage',code='storage_read_only',
                       password='private-password',payload={'document':'private-document'},
                       exception={'type':'PermissionError','frames':[{'module':'storage','line':42}]})
    row=s.db.one('SELECT * FROM operational_events WHERE id=?',(event,))
    assert row['boot_id'] and row['job_id']=='test-job'
    assert 'private-password' not in row['details_json'] and 'private-document' not in row['details_json']
    assert json.loads(row['details_json'])['exception']['frames'][0]['line']==42
    response=client.get('/admin/api/operations?job_id=test-job')
    assert response.status_code==200 and response.json['events'][0]['id']==event
    assert client.get('/admin/diagnostics').status_code==200


def test_schema_history_gap_is_explicit_and_no_migration_is_replayed(db):
    db.execute('DELETE FROM schema_versions WHERE version=2')
    before=db.all('SELECT * FROM schema_versions')
    with pytest.raises(DomainError) as failed:db.migrate()
    assert failed.value.code=='database_schema_history_invalid'
    assert db.all('SELECT * FROM schema_versions')==before


def test_future_schema_does_not_run_an_older_image(db):
    db.execute('INSERT INTO schema_versions VALUES(?,?)',(999,time.time()))
    with pytest.raises(DomainError) as failed:db.migrate()
    assert failed.value.code=='database_schema_newer'


def test_installation_cli_inspects_empty_database_without_writes(app,monkeypatch,capsys):
    from gianna.config import Config
    from scripts.recover_knowledge import main
    s=app.extensions['gianna']
    monkeypatch.setattr(Config,'from_env',lambda **kwargs:s.cfg)
    before=set(s.cfg.data_dir.rglob('*'))
    assert main(['--inspect-installation'])==0
    assert json.loads(capsys.readouterr().out)['state']=='empty'
    assert before==set(s.cfg.data_dir.rglob('*'))


def test_http_enqueue_and_sql_event_share_the_request_id(app):
    s=app.extensions['gianna'];client=app.test_client();authenticate(app,client)
    response=client.post('/admin/warmup',data={'csrf':'csrf-test-value'})
    assert response.status_code==302
    event=s.db.one("SELECT request_id FROM operational_events WHERE event='queue.enqueued' ORDER BY at DESC LIMIT 1")
    assert event['request_id']==response.headers['X-Request-ID']


def test_generated_schema_contract_tracks_all_migration_columns():
    from scripts.schema_contract import main
    assert main([])==0
