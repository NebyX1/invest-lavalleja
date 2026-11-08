"""Real private MinIO, no production endpoints, credentials, data or generation."""
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import time

import httpx
from minio import Minio
import pytest

from gianna import create_app
from gianna.config import Config
from gianna.errors import DomainError
from gianna.services.objects import MARKER, PREFIX, SETTING, Objects, objects
from gianna.services.storage import inspect_storage, storage_identity

MINIO_IMAGE = 'coollabsio/minio@sha256:69b55a1c1c5dc285ce04db96689f5b2102317fc77a50680a1874ca6efd1c87f9'


@pytest.fixture(scope='session')
def minio_server(request):
    if not request.config.getoption('--minio-docker'):
        pytest.skip('Pass --minio-docker for real isolated MinIO.')
    name = 'gianna-minio-test-'+secrets.token_hex(6)
    user, key = secrets.token_hex(12), secrets.token_urlsafe(32)
    env = {**os.environ, 'MINIO_ROOT_USER':user, 'MINIO_ROOT_PASSWORD':key}
    def docker(*args):
        result = subprocess.run(['docker', *args], capture_output=True, text=True, env=env, timeout=180)
        assert result.returncode == 0, 'Disposable MinIO container operation failed.'
        return result.stdout.strip()
    try:
        docker('run','-d','--name',name,'--publish','127.0.0.1::9000','--tmpfs','/data:mode=1777',
               '--memory','512m','--cpus','1','--env','MINIO_ROOT_USER','--env','MINIO_ROOT_PASSWORD',
               MINIO_IMAGE,'server','/data','--console-address',':9001')
        port = docker('port',name,'9000/tcp').rsplit(':',1)[1]
        endpoint = '127.0.0.1:'+port
        for _ in range(80):
            try:
                if httpx.get('http://'+endpoint+'/minio/health/live', timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(.25)
        else:
            pytest.fail('Disposable MinIO did not become ready.')
        yield endpoint,user,key
    finally:
        subprocess.run(['docker','rm','-f',name],capture_output=True,timeout=30)


@pytest.fixture
def minio_cfg(cfg, minio_server):
    endpoint,user,key = minio_server
    return replace(cfg, storage_backend='minio', production=True, minio_endpoint=endpoint,
                   minio_access_key=user, minio_secret_key=key, minio_secure=False,
                   minio_bucket_name='gianna-'+secrets.token_hex(10),
                   minio_public_url='https://objects.example.test')


def test_production_defaults_to_minio_and_uses_exact_idl_environment_names(cfg):
    env = {'FLASK_ENV':'production','SECRET_KEY':cfg.secret_key,'ENCRYPTION_KEY':cfg.encryption_key,
           'DATABASE_URL':'mariadb+mariadbconnector://test:test@db.example.test/gianna',
           'CORS_ORIGINS':'https://portal.example.test', 'MINIO_ENDPOINT':'minio.example.test:9000',
           'MINIO_ACCESS_KEY':'private-access', 'MINIO_SECRET_KEY':'private-secret',
           'MINIO_SECURE':'True','MINIO_BUCKET_NAME':'gianna-test',
           'MINIO_PUBLIC_URL':'https://objects.example.test/'}
    actual = Config.from_env({'data_dir':cfg.data_dir},environ=env,initialize_storage=False)
    assert actual.storage_backend == 'minio' and actual.minio_bucket_name=='gianna-test'
    assert actual.minio_public_url=='https://objects.example.test'
    assert actual.minio_secure
    assert 'private-secret' not in repr(actual) and 'private-access' not in repr(actual)


def test_missing_minio_has_actionable_error_and_never_inspects_mount(db, cfg, monkeypatch):
    from gianna.services import storage
    monkeypatch.setattr(storage,'_mount_report',lambda _:pytest.fail('MinIO must not require a local mount'))
    actual = replace(cfg, production=True, storage_backend='minio')
    report = inspect_storage(db, actual)
    assert report['code']=='minio_configuration_missing'
    assert 'MINIO_BUCKET_NAME' in report['action'] and 'storage_not_mounted' not in json.dumps(report)


def test_empty_bucket_is_initialized_by_worker_not_diagnostic(db, minio_cfg):
    client=objects(minio_cfg)
    before=client.inspect(db)
    assert not before['bucket_exists'] and db.setting(SETTING) is None
    assert inspect_storage(db,minio_cfg)['ok']
    result=storage_identity(db,minio_cfg,write=True)
    assert result=={'matched':True,'initialized':True}
    assert client.inspect(db)['identity']['matched']
    assert client.read_json(MARKER)['id']==db.setting(SETTING)['id']


def test_new_cache_directory_keeps_remote_binding_without_local_volume(db,minio_cfg,tmp_path,monkeypatch):
    from gianna.services import storage
    storage_identity(db,minio_cfg,write=True)
    new_cfg=replace(minio_cfg,data_dir=tmp_path/'new-container-cache')
    monkeypatch.setattr(storage,'_mount_report',lambda _:pytest.fail('Unexpected local mount requirement'))
    report=inspect_storage(db,new_cfg)
    assert report['ok'] and report['identity']['matched'] and not report['mount']['required']
    assert not new_cfg.data_dir.exists()  # Inventory remains read-only.


def test_private_object_roundtrip_and_conflict_preserve_original(db,minio_cfg):
    storage_identity(db,minio_cfg,write=True)
    store=objects(minio_cfg)
    sha=store.put('uploads/example.json',b'{"internal":"private"}')
    assert sha==hashlib.sha256(b'{"internal":"private"}').hexdigest()
    store.put('uploads/example.json',b'{"internal":"private"}')
    with pytest.raises(DomainError) as caught:store.put('uploads/example.json',b'other')
    assert caught.value.code=='object_conflict'
    assert store.read('uploads/example.json')==b'{"internal":"private"}'


@pytest.mark.parametrize('name',['../foreign','/absolute','dir/../foreign','dir\\foreign',''])
def test_object_namespace_rejects_untrusted_paths(name):
    with pytest.raises(DomainError):Objects.key(name)


def test_existing_foreign_namespace_cannot_be_adopted(db,minio_cfg):
    store=objects(minio_cfg)
    store.client.make_bucket(minio_cfg.minio_bucket_name)
    store.client.put_object(minio_cfg.minio_bucket_name,PREFIX+'foreign.json',io.BytesIO(b'{}'),2)
    report=inspect_storage(db,minio_cfg)
    assert report['code']=='minio_namespace_unbound'
    assert db.setting(SETTING) is None


def test_different_bucket_cannot_replace_registered_objects(db,minio_cfg):
    storage_identity(db,minio_cfg,write=True)
    changed=replace(minio_cfg,minio_bucket_name='other-'+secrets.token_hex(8))
    assert inspect_storage(db,changed)['code']=='minio_identity_mismatch'
    assert not objects(changed).client.bucket_exists(changed.minio_bucket_name)


def test_endpoint_alias_preserves_verified_bucket_identity(db,minio_cfg):
    storage_identity(db,minio_cfg,write=True)
    original=db.setting(SETTING)
    alias=replace(minio_cfg,minio_endpoint=minio_cfg.minio_endpoint.replace('127.0.0.1','localhost'))
    report=inspect_storage(db,alias)
    assert report['ok'] and report['identity']['matched']
    assert db.setting(SETTING)==original  # Read-only inspection.
    storage_identity(db,alias,write=True)
    assert db.setting(SETTING)['id']==original['id']


def test_bad_credentials_are_specific_and_sanitized(db,minio_cfg):
    changed=replace(minio_cfg,minio_secret_key='wrong-private-secret-key')
    report=inspect_storage(db,changed)
    assert report['code']=='minio_access_denied'
    assert 'wrong-private-secret-key' not in json.dumps(report)


def test_public_bucket_is_blocked_without_changing_its_policy(db,minio_cfg):
    store=objects(minio_cfg);bucket=minio_cfg.minio_bucket_name
    store.client.make_bucket(bucket)
    policy=json.dumps({'Version':'2012-10-17','Statement':[{'Effect':'Allow','Principal':{'AWS':['*']},
                       'Action':['s3:GetObject'],'Resource':['arn:aws:s3:::'+bucket+'/*']}]})
    store.client.set_bucket_policy(bucket,policy)
    original=store.client.get_bucket_policy(bucket)
    assert inspect_storage(db,minio_cfg)['code']=='minio_bucket_not_private'
    assert store.client.get_bucket_policy(bucket)==original


def test_sql_vectors_and_minio_backup_restore_after_cache_loss(db,minio_cfg,knowledge,corpus,tmp_path):
    from test_knowledge_recovery import seed
    from gianna.services.recovery import KnowledgeRecovery,snapshot
    from gianna.services.vector_store import LanceStore
    storage_identity(db,minio_cfg,write=True)
    engine,version=seed(db,minio_cfg,knowledge,corpus)
    data=snapshot(db,minio_cfg,version)
    recovery=KnowledgeRecovery(db,minio_cfg,knowledge,engine,LanceStore(minio_cfg))
    recovery._backup(data)
    db.execute('UPDATE chunks SET vector_json=NULL')
    db.execute('DELETE FROM embedding_cache')
    new_cfg=replace(minio_cfg,data_dir=tmp_path/'replacement-container')
    restored=snapshot(db,new_cfg,version)
    assert restored['rows']==data['rows'] and restored['backup_used']
    assert inspect_storage(db,new_cfg)['ok']
    assert not new_cfg.data_dir.exists()


def test_queued_upload_is_recovered_in_new_cache(db,minio_cfg,knowledge,corpus,tmp_path):
    from gianna.services.jobs import Jobs
    from gianna.services.vector_store import LanceStore
    from test_knowledge_recovery import LocalEngine
    storage_identity(db,minio_cfg,write=True)
    content=corpus.model_dump_json().encode()
    name=secrets.token_hex(16)+'.json'
    sha=objects(minio_cfg).put('uploads/'+name,content)
    new_cfg=replace(minio_cfg,data_dir=tmp_path/'upload-replacement')
    new_cfg.data_dir.mkdir()
    jobs=Jobs(db,new_cfg,knowledge,LocalEngine(),LanceStore(new_cfg),None)
    jid=jobs.enqueue('import',{'path':str(minio_cfg.data_dir/'uploads'/name),
                             'object_name':name,'object_sha256':sha,'name':'Recovered upload'})
    jobs.execute_job(jobs.claim())
    row=db.one('SELECT status,error_code,result_json FROM jobs WHERE id=?',(jid,))
    assert row['status']=='done',row['error_code']
    assert db.one('SELECT id FROM bases WHERE id=?',(json.loads(row['result_json'])['base_id'],))
    assert objects(minio_cfg).read('uploads/'+name)==content  # Durable source retained.


def test_model_files_stream_to_and_from_minio(db,minio_cfg,tmp_path):
    storage_identity(db,minio_cfg,write=True)
    payload=b'verified-onnx-model'*100000
    original=tmp_path/'model.onnx';original.write_bytes(payload)
    sha=hashlib.sha256(payload).hexdigest()
    store=objects(minio_cfg)
    store.persist_file('models/pinned/model.onnx',original,sha)
    destination=tmp_path/'new-cache/model.onnx'
    assert store.restore_file('models/pinned/model.onnx',destination,sha,len(payload))
    assert destination.read_bytes()==payload
    assert not list(destination.parent.glob('*.partial'))


def test_marker_loss_does_not_create_empty_replacement(db,minio_cfg):
    storage_identity(db,minio_cfg,write=True)
    store=objects(minio_cfg)
    store.client.remove_object(minio_cfg.minio_bucket_name,PREFIX+MARKER)
    report=inspect_storage(db,minio_cfg)
    assert report['code']=='minio_storage_missing'
    with pytest.raises(DomainError):storage_identity(db,minio_cfg,write=True)


def test_first_minio_boot_preserves_existing_published_sql(db,minio_cfg,knowledge,corpus):
    from test_knowledge_recovery import seed
    from gianna.services.installation import Installation
    from gianna.services.recovery import KnowledgeRecovery
    from gianna.services.vector_store import LanceStore
    engine,version=seed(db,minio_cfg,knowledge,corpus)
    store=LanceStore(minio_cfg)
    recovery=KnowledgeRecovery(db,minio_cfg,knowledge,engine,store)
    install=Installation(db,minio_cfg,knowledge,store,recovery)
    before=db.one('SELECT version_id FROM active_knowledge WHERE singleton=1')
    report=install.reconcile(force=True)
    assert report['state']!='blocked', (report['code'],report['message'])
    assert objects(minio_cfg).inspect(db)['identity']['matched']
    assert db.one('SELECT version_id FROM active_knowledge WHERE singleton=1')==before
