"""Authenticated operational screens expose causes without changing knowledge."""
import json
import os
from pathlib import Path
import subprocess
import threading
import time

import pytest

from gianna import create_app
from gianna.security import token_hash


@pytest.fixture
def console(cfg):
    app = create_app(cfg)
    app.config['TESTING'] = True
    return app


def authenticated(app, role='owner'):
    client = app.test_client()
    services = app.extensions['gianna']
    user = services.security.create_user('operator@example.test', 'Operación de prueba',
                                         'long-test-password-123', role, 'email')
    now = time.time()
    raw = 'isolated-monitoring-session'
    services.db.execute('INSERT INTO admin_sessions VALUES(?,?,?,?,?,?)',
                        (token_hash(raw), user, now, now, now+1000, now))
    with client.session_transaction() as session:
        session['sid'] = raw
        session['csrf'] = 'isolated-monitoring-csrf'
    return client


def test_job_screen_is_complete_without_javascript_and_does_not_expose_payload(console):
    client = authenticated(console)
    services = console.extensions['gianna']
    job_id = services.jobs.enqueue('warmup', {'private_document':'never-show-this-corpus'})
    services.db.execute("UPDATE jobs SET status='failed',attempts=1,error_code='storage_not_mounted',"
                        "error_stage='storage',stage='failed',error=?,action=?,boot_id=? WHERE id=?",
                        ('<script>private-display-test</script>', 'Verificá el montaje /app/data.', 'test-boot', job_id))
    response = client.get('/admin/jobs/'+job_id)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    for expected in ('storage_not_mounted','Verificá el montaje /app/data.','test-boot',
                     'Historial de ejecución','El intento terminó sin un total','job-retry-form','job-cancel-form',
                     '/admin/diagnostics','Actualizar ahora'):
        assert expected in html
    assert 'never-show-this-corpus' not in html
    assert '<script>private-display-test</script>' not in html
    assert '&lt;script&gt;private-display-test&lt;/script&gt;' in html
    progress = html.split('<progress',1)[1].split('>',1)[0]
    assert 'value=' not in progress and 'max=' not in progress
    assert 'unsafe-inline' not in response.headers['Content-Security-Policy']


def test_job_api_keeps_retry_deadline_cause_and_history_separate(console):
    client = authenticated(console)
    services = console.extensions['gianna']
    job_id = services.jobs.enqueue('warmup', {'private_document':'never-show-this-corpus'})
    services.db.execute("UPDATE jobs SET status='queued',attempts=1,available_at=?,error=NULL,"
                        "error_code='models_recovery_failed',stage='waiting_retry',"
                        "owner_token='private-worker-token' WHERE id=?", (time.time()+45,job_id))
    response = client.get('/admin/api/jobs/'+job_id)
    assert response.status_code == 200
    data = response.json
    assert data['status'] == 'queued' and data['error'] is None
    assert data['error_code'] == 'models_recovery_failed'
    assert 40 <= data['retry_in_seconds'] <= 45
    assert data['attempts'] == 1 and data['max_attempts'] == 3
    assert 'worker' in data and 'events' in data and 'installation' in data
    assert 'owner_token' not in data and 'payload_json' not in data
    assert 'private-worker-token' not in response.get_data(as_text=True)
    assert 'never-show-this-corpus' not in response.get_data(as_text=True)


def test_diagnostics_page_and_api_inspect_without_creating_storage_or_models(console):
    client = authenticated(console)
    services = console.extensions['gianna']
    before = set(services.cfg.data_dir.rglob('*'))
    publication = services.db.all('SELECT * FROM active_knowledge')
    response = client.get('/admin/diagnostics')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    for expected in ('Diagnóstico de la instalación','MariaDB','LanceDB','Modelos',
                     'Comprobaciones','Plan según el estado encontrado','Últimos eventos operativos',
                     'Arranque del proceso','Informe'):
        assert expected in html
    result = client.get('/admin/api/diagnostics')
    assert result.status_code == 200 and 'installation' in result.json
    assert services.db.all('SELECT * FROM active_knowledge') == publication
    assert set(services.cfg.data_dir.rglob('*')) == before
    assert not services.cfg.lance_dir.exists()
    assert not (services.cfg.data_dir/'.gianna-storage.json').exists()


@pytest.mark.parametrize('role',['owner','editor','viewer'])
def test_diagnostics_require_an_admin_session_and_mutation_actions_respect_role(console, role):
    anonymous = console.test_client()
    assert anonymous.get('/admin/diagnostics').status_code == 302
    assert anonymous.get('/admin/api/diagnostics').status_code == 401
    client = authenticated(console, role)
    job_id = console.extensions['gianna'].jobs.enqueue('warmup')
    assert client.get('/admin/diagnostics').status_code == 200
    page = client.get('/admin/jobs/'+job_id).get_data(as_text=True)
    assert ('id="job-retry-form"' in page) is (role != 'viewer')
    assert ('id="job-cancel-form"' in page) is (role != 'viewer')


def test_diagnostic_details_escape_untrusted_strings(console, monkeypatch):
    client = authenticated(console)
    report = console.extensions['gianna'].installation.inspect()
    report['message'] = '<img src=x onerror="window.unsafe=true">'
    report['checks'].append({'name':'storage','status':'blocked','code':'unsafe_markup_test',
                             'message':'<script>window.unsafe=true</script>',
                             'action':'Revisá el volumen.', 'details':{'path':'<private>'}})
    monkeypatch.setattr(console.extensions['gianna'].installation, 'inspect', lambda:report)
    page = client.get('/admin/diagnostics').get_data(as_text=True)
    assert '<img src=x onerror=' not in page and '<script>window.unsafe' not in page
    assert '&lt;img src=x' in page and '&lt;script&gt;' in page


def test_correlated_events_are_available_only_to_admin_sessions(console):
    from gianna.services.operations import record_event
    services = console.extensions['gianna']
    record_event(services.db,'test.operational',job_id='test-job',code='storage_not_mounted',
                 details={'path':'/app/data','payload':'private-content','secret_key':'private-key'})
    assert console.test_client().get('/admin/api/operations').status_code == 401
    client = authenticated(console)
    response = client.get('/admin/api/operations?job_id=test-job')
    assert response.status_code == 200
    assert any(row['event']=='test.operational' for row in response.json['events'])
    content = response.get_data(as_text=True)
    assert 'private-content' not in content and 'private-key' not in content


@pytest.mark.skipif(os.environ.get('GIANNA_BROWSER_MONITOR_TEST') != '1',
                    reason='Set GIANNA_BROWSER_MONITOR_TEST=1 for real Chromium/WebKit monitoring tests.')
def test_real_browser_monitor_recovers_polling_and_updates_actions(console):
    """Real Flask/SQL/JS, with one simulated HTTP outage; no provider or models."""
    from flask import jsonify
    from werkzeug.serving import make_server
    client = authenticated(console)
    services = console.extensions['gianna']
    job_id = services.jobs.enqueue('warmup')
    @console.post('/__isolated_monitor_test__/<state>')
    def transition(state):
        assert state in {'queued','running','failed','done'}
        failed = state == 'failed'
        services.db.execute('UPDATE jobs SET status=?,stage=?,attempts=2,error=?,error_code=?,action=?,total=?,progress=?,result_json=? WHERE id=?',
                            (state,'storage' if failed else state,
                             '<img src=x onerror="window.monitorXSS=true">' if failed else None,
                             'storage_not_mounted' if failed else None,
                             'Verificá el montaje /app/data.' if failed else None,
                             0 if state in {'queued','failed'} else 3,
                             3 if state=='done' else 1 if state=='running' else 0,
                             json.dumps({'verified':True}) if state=='done' else None,job_id))
        if failed:
            services.db.execute('INSERT INTO job_events(job_id,at,event,attempt,boot_id,stage,code,message,details_json) VALUES(?,?,?,?,?,?,?,?,?)',
                                (job_id,time.time(),'test.failure',2,'isolated-test-boot','storage','storage_not_mounted',
                                 '<script>window.monitorXSS=true</script>',json.dumps({'action':'Verificá el montaje /app/data.'})))
        return jsonify(ok=True)
    root = Path(__file__).resolve().parents[1]
    module = Path(os.environ.get('GIANNA_PLAYWRIGHT_MODULE', root.parent/'node_modules/playwright/index.mjs'))
    if not module.is_file():
        raise AssertionError('Install Playwright and set GIANNA_PLAYWRIGHT_MODULE to its index.mjs.')
    cookie = client.get_cookie('gianna_admin',path='/admin').value
    server = make_server('127.0.0.1',0,console,threaded=True)
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    settings = {'origin':f'http://127.0.0.1:{server.server_port}', 'job_id':job_id,
                'cookie':cookie,
                'playwright_module':str(module), 'artifacts':str(root/'reports/monitoring')}
    try:
        result = subprocess.run([os.environ.get('GIANNA_NODE_BINARY','node'), str(root/'tests/monitor_browser.mjs')],
                                input=json.dumps(settings),capture_output=True,text=True,encoding='utf-8',timeout=120)
        assert result.returncode == 0, result.stderr[-3000:]
        evidence = json.loads(result.stdout.strip().splitlines()[-1])
        assert evidence['profiles'] == ['chromium','webkit']
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
