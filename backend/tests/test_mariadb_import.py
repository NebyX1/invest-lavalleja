"""Real strict MariaDB regressions; opt in with pytest --mariadb-docker.

No production URL, .env or existing container/database is used. The Docker fixture
creates its own loopback-only server and removes only that server at teardown.
"""
from dataclasses import replace
from pathlib import Path
import io
import json
import os
import re
import secrets
import subprocess
import time

import pytest
from sqlalchemy.engine import URL

from gianna import create_app
from gianna.corpus import load_corpus
from gianna.db import Database, dumps, uid
from gianna.services.knowledge import Knowledge
from gianna.services.settings import Settings


@pytest.fixture(scope='module')
def maria_server(request):
    if not request.config.getoption('--mariadb-docker'):
        pytest.skip('Pass --mariadb-docker to start an isolated MariaDB server.')
    name='gianna-import-regression-'+uid()[:12]
    password=secrets.token_hex(24)
    env={**os.environ,'MARIADB_ROOT_PASSWORD':password}
    subprocess.run(['docker','run','--detach','--name',name,'--label','gianna.test=import-regression',
        '--publish','127.0.0.1::3306','--tmpfs','/var/lib/mysql',
        '--env','MARIADB_ROOT_PASSWORD','--env','MARIADB_ROOT_HOST=%','mariadb:11.4',
        '--sql-mode=STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION'],
        env=env,check=True,capture_output=True,text=True)
    server=None
    try:
        port=int(subprocess.run(['docker','port',name,'3306/tcp'],check=True,capture_output=True,text=True).stdout.strip().rsplit(':',1)[1])
        url=URL.create('mariadb+mariadbconnector',username='root',password=password,host='127.0.0.1',port=port,database='mysql')
        server=Database(url.render_as_string(hide_password=False))
        deadline=time.monotonic()+55
        while True:
            try:
                server.one('SELECT 1 AS ready')
                break
            except Exception:
                if time.monotonic()>=deadline:
                    pytest.fail('Disposable MariaDB did not become ready; no production server was contacted.',pytrace=False)
                time.sleep(.5)
        assert 'STRICT_TRANS_TABLES' in server.one('SELECT @@SESSION.sql_mode AS mode')['mode']
        yield url,server
    finally:
        if server:server._engine.dispose()
        subprocess.run(['docker','rm','--force',name],check=True,capture_output=True)


@pytest.fixture(params=['fresh','upgrade-v2'])
def maria_db(maria_server,request):
    url,server=maria_server
    name='test_'+uid()
    server.execute(f'CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
    db=Database(url.set(database=name).render_as_string(hide_password=False))
    try:
        if request.param=='upgrade-v2':
            with db.tx() as connection:
                connection.execute('CREATE TABLE schema_versions(version INTEGER PRIMARY KEY,applied_at DOUBLE NOT NULL)')
                migrations=Path(__file__).resolve().parents[1]/'gianna/migrations_mariadb'
                for version in (1,2):
                    db._execute_statements(connection,(migrations/f'{version:03}.sql').read_text(encoding='utf-8'))
                    connection.execute('INSERT INTO schema_versions VALUES(?,?)',(version,time.time()))
            db.execute('INSERT INTO settings(`key`,value) VALUES(?,?)',('migration-sentinel',dumps('unchanged')))
        db.migrate()
        if request.param=='upgrade-v2':assert db.setting('migration-sentinel')=='unchanged'
        assert 'STRICT_TRANS_TABLES' in db.one('SELECT @@SESSION.sql_mode AS mode')['mode']
        yield db
    finally:
        db._engine.dispose()
        server.execute(f'DROP DATABASE `{name}`')


def test_schema_defaults_support_the_same_minimal_inserts_as_sqlite(maria_db):
    db=maria_db;now=time.time()
    db.execute('INSERT INTO bases(id,name,created_at,updated_at) VALUES(?,?,?,?)',('base','Test',now,now))
    base=db.one('SELECT description,document_json,report_json FROM bases WHERE id=?',('base',))
    assert base=={'description':'','document_json':'{}','report_json':'{}'}
    db.execute('INSERT INTO versions(id,base_id,revision,collection_name,created_at) VALUES(?,?,?,?,?)',('version','base',1,'test_collection',now))
    assert db.one('SELECT profile_json,report_json FROM versions WHERE id=?',('version',))=={'profile_json':'{}','report_json':'{}'}
    db.execute('INSERT INTO audit(at,action) VALUES(?,?)',(now,'TEST'))
    assert db.one('SELECT details_json FROM audit WHERE action=?',('TEST',))['details_json']=='{}'
    db.execute('INSERT INTO queries(id,at,mode,status) VALUES(?,?,?,?)',('query',now,'knowledge','ok'))
    assert db.one('SELECT source_ids_json,retrieval_trace_json,cited_source_ids_json FROM queries WHERE id=?',('query',))=={
        'source_ids_json':'[]','retrieval_trace_json':'{}','cited_source_ids_json':'[]'}
    before=db.one('SELECT * FROM bases WHERE id=?',('base',))
    db.migrate()
    assert db.one('SELECT * FROM bases WHERE id=?',('base',))==before


def test_import_and_enqueue_public_snapshot_on_real_mariadb(maria_db,cfg,corpus):
    knowledge=Knowledge(maria_db,cfg)
    bid=knowledge.import_corpus(corpus,'Strict MariaDB','test-actor')
    assert knowledge.export(bid).model_dump()==corpus.model_dump()
    assert knowledge.require_base(bid)['description']==''
    assert maria_db.one('SELECT SUM(approved) AS n FROM records WHERE base_id=?',(bid,))['n']==0
    assert knowledge.active() is None
    assert knowledge.approve_public(bid,'test-actor')==1
    job,version=knowledge.enqueue_build(bid,Settings(),'test-actor')
    assert json.loads(maria_db.one('SELECT report_json FROM versions WHERE id=?',(version,))['report_json'])=={}
    assert maria_db.one('SELECT status FROM jobs WHERE id=?',(job,))['status']=='queued'
    records=maria_db.all('SELECT content_json FROM version_records WHERE version_id=?',(version,))
    assert len(records)==1 and json.loads(records[0]['content_json'])['audience']=='public'
    assert knowledge.active() is None


def authenticated_app(cfg,db):
    app=create_app(replace(cfg,database_url=db.target));app.config['TESTING']=True
    services=app.extensions['gianna'];sent=[]
    services.security.mailer=lambda address,code:sent.append(code)
    services.security.create_user('import@example.test','Test owner','test-password-long-enough','owner')
    client=app.test_client()
    page=client.get('/admin/login').get_data(as_text=True)
    a,b=map(int,re.search(r'(\d+) \+ (\d+)',page).groups())
    with client.session_transaction(path='/admin/login') as session:csrf=session['csrf']
    response=client.post('/admin/login',data={'csrf':csrf,'email':'import@example.test',
        'password':'test-password-long-enough','captcha':str(a+b)})
    assert response.status_code==302 and response.location.endswith('/admin/mfa')
    with client.session_transaction(path='/admin/mfa') as session:csrf=session['csrf']
    assert client.post('/admin/mfa',data={'csrf':csrf,'code':sent.pop()}).location.endswith('/admin/dashboard')
    return app,services,client


@pytest.mark.parametrize('guide',['fixture','private-guide'])
def test_authenticated_upload_job_and_replay(maria_db,cfg,corpus,guide):
    if guide=='private-guide':
        path=Path(__file__).resolve().parents[1]/'docs/Invest_Lavalleja_2026.gianna.json'
        if not path.exists():pytest.skip('Private guide is not available in this checkout.')
        corpus=load_corpus(path)
    corpus=corpus.model_copy(update={'document':corpus.document.model_copy(update={'filename':'test.gianna.json'})})
    app,s,client=authenticated_app(cfg,maria_db)
    try:
        with client.session_transaction(path='/admin/bases/import') as session:csrf=session['csrf']
        response=client.post('/admin/bases/import',data={'csrf':csrf,'name':'Uploaded test guide',
            'file':(io.BytesIO(corpus.model_dump_json().encode()),'test.gianna.json')})
        assert response.status_code==302 and '/admin/jobs/' in response.location
        job=s.jobs.claim();assert job['kind']=='import'
        s.jobs.execute_job(job)
        status=s.db.one('SELECT * FROM jobs WHERE id=?',(job['id'],))
        assert status['status']=='done',status['error']
        bid=status['base_id']
        assert s.knowledge.export(bid).model_dump()==corpus.model_dump()
        assert s.db.one('SELECT COUNT(*) AS n FROM records WHERE base_id=?',(bid,))['n']==len(corpus.records)
        assert s.db.one('SELECT SUM(approved) AS n FROM records WHERE base_id=?',(bid,))['n']==0
        assert s.knowledge.active() is None and client.get('/admin/bases/'+bid).status_code==200
        # Simulate recovery after the import committed but before the job finished.
        s.db.execute("UPDATE jobs SET status='queued',owner_token=NULL,lease_until=NULL WHERE id=?",(job['id'],))
        s.jobs.execute_job(s.jobs.claim())
        assert s.db.one('SELECT status FROM jobs WHERE id=?',(job['id'],))['status']=='done'
        assert s.db.one('SELECT COUNT(*) AS n FROM bases')['n']==1
        assert s.db.one("SELECT COUNT(*) AS n FROM audit WHERE action='CORPUS_IMPORTED'")['n']==1
    finally:s.db._engine.dispose()


def test_retry_failed_import_after_migration_without_reupload(maria_db,cfg,corpus):
    app,s,client=authenticated_app(cfg,maria_db)
    try:
        # Reproduce the previous production schema after app startup.
        s.db.execute('ALTER TABLE bases ALTER COLUMN description DROP DEFAULT')
        s.db.execute('DELETE FROM schema_versions WHERE version=3')
        with client.session_transaction(path='/admin/bases/import') as session:csrf=session['csrf']
        response=client.post('/admin/bases/import',data={'csrf':csrf,'name':'Retry original job',
            'file':(io.BytesIO(corpus.model_dump_json().encode()),'retry.gianna.json')})
        assert response.status_code==302
        job=s.jobs.claim();s.jobs.execute_job(job)
        failed=s.db.one('SELECT * FROM jobs WHERE id=?',(job['id'],))
        assert failed['status']=='failed' and failed['progress']==len(corpus.records)
        assert 'IntegrityError' in failed['error']
        upload=Path(json.loads(failed['payload_json'])['path'])
        assert upload.is_file() and s.db.all('SELECT * FROM bases')==[]
        assert s.db.all('SELECT * FROM records')==[] and s.db.all('SELECT * FROM sources')==[]
        s.db.migrate()
        response=client.post('/admin/jobs/'+job['id']+'/retry',data={'csrf':csrf})
        assert response.status_code==302
        retried=s.jobs.claim();assert retried['id']==job['id']
        s.jobs.execute_job(retried)
        result=s.db.one('SELECT * FROM jobs WHERE id=?',(job['id'],))
        assert result['status']=='done' and result['error'] is None
        assert s.db.one('SELECT COUNT(*) AS n FROM bases')['n']==1
        assert s.db.one('SELECT COUNT(*) AS n FROM records')['n']==len(corpus.records)
        assert not upload.exists() and s.knowledge.active() is None
    finally:s.db._engine.dispose()


def test_defaults_migration_preserves_existing_data_accounts_and_active_version(maria_db,cfg,corpus):
    app,s,client=authenticated_app(cfg,maria_db)
    try:
        bid=s.knowledge.import_corpus(corpus,'Existing knowledge','test-actor')
        s.knowledge.approve_public(bid,'test-actor')
        job,version=s.knowledge.enqueue_build(bid,Settings(),'test-actor')
        s.db.execute("UPDATE bases SET description='Keep description',report_json=? WHERE id=?",(dumps({'keep':'report'}),bid))
        s.db.execute("UPDATE versions SET status='ready',chunk_count=1,report_json=? WHERE id=?",(dumps({'keep':'version report'}),version))
        s.db.execute("UPDATE jobs SET status='done' WHERE id=?",(job,))
        s.knowledge.activate(version,'test-actor')
        tables=('users','admin_sessions','auth_challenges','bases','records','sources','versions',
            'version_records','version_sources','active_knowledge','jobs','settings','audit')
        before={table:s.db.all(f'SELECT * FROM {table}') for table in tables}
        s.db.execute('DELETE FROM schema_versions WHERE version=3')
        s.db.migrate();s.db.migrate()
        assert {table:s.db.all(f'SELECT * FROM {table}') for table in tables}==before
        assert s.knowledge.active()['id']==version
        assert client.get('/admin/dashboard').status_code==200
    finally:s.db._engine.dispose()
