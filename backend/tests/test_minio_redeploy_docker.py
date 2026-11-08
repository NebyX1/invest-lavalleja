"""Actual MinIO + MariaDB + LanceDB + pinned ONNX; replace the entire API cache.

Every resource is exclusive and disposable. No .env, production data, generator,
external MinIO endpoint or local persistent mount is used by the API containers.
"""
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time

from cryptography.fernet import Fernet
import httpx
import pytest

from test_minio_storage import MINIO_IMAGE

ROOT=Path(__file__).resolve().parents[1]


def test_real_minio_redeploy_without_local_volume(request):
    if not request.config.getoption('--recovery-docker'):
        pytest.skip('Pass --recovery-docker for pinned ONNX + real MinIO container recovery.')
    suffix=secrets.token_hex(6);prefix='gianna-minio-redeploy-'+suffix
    image=prefix+':test';network=prefix;db_name=prefix+'-db';object_name=prefix+'-objects';api=prefix+'-api';seed=prefix+'-seed'
    password=secrets.token_hex(24);secret=secrets.token_urlsafe(48);sid=secrets.token_urlsafe(40)
    access=secrets.token_hex(12);private=secrets.token_urlsafe(40)
    env={**os.environ,'MARIADB_ROOT_PASSWORD':password,'MARIADB_PASSWORD':password,
         'DATABASE_URL':'mariadb+mariadbconnector://gianna:'+password+'@maria:3306/gianna_recovery',
         'SECRET_KEY':secret,'ENCRYPTION_KEY':Fernet.generate_key().decode(),'GIANNA_TEST_SESSION':sid,
         'MINIO_ROOT_USER':access,'MINIO_ROOT_PASSWORD':private,'MINIO_ACCESS_KEY':access,'MINIO_SECRET_KEY':private}
    events=[];scenarios=[];resources=set();created_network=False
    def docker(*args,timeout=1800):
        result=subprocess.run(['docker',*map(str,args)],env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
        if result.returncode:
            # Do not echo argv/env; redact generated credentials from failure text.
            detail=result.stderr[-1800:]
            for value in (password,secret,sid,access,private,env['ENCRYPTION_KEY']):detail=detail.replace(value,'[redacted]')
            pytest.fail('Disposable MinIO regression operation failed: '+detail,pytrace=False)
        return (result.stdout+'\n'+result.stderr).strip() if args[0]=='logs' else result.stdout.strip()
    def record(name,**fields):
        scenarios.append(dict(scenario=name,passed=True,**fields))
        print('MinIO regression passed: '+name,flush=True)
    environment=['--env','FLASK_ENV=production','--env','DATABASE_URL','--env','SECRET_KEY','--env','ENCRYPTION_KEY',
                 '--env','MINIO_ENDPOINT=objectstore:9000','--env','MINIO_ACCESS_KEY','--env','MINIO_SECRET_KEY',
                 '--env','MINIO_SECURE=False','--env','MINIO_BUCKET_NAME=gianna-recovery',
                 '--env','MINIO_PUBLIC_URL=https://objects.example.test',
                 '--env','CORS_ORIGINS=https://portal.example.test,https://localhost',
                 '--env','OLLAMA_API_KEY=','--env','OLLAMA_MODEL=',
                 '--env','MAIL_SERVER=smtp.example.test','--env','MAIL_DEFAULT_SENDER=regression@example.test',
                 '--env','GIANNA_RECOVERY_REGRESSION=isolated','--env','GIANNA_TEST_SESSION']
    headers={'Host':'localhost','X-Forwarded-Proto':'https','Origin':'https://portal.example.test'}
    def collect():
        raw=docker('logs',api)
        for value in (password,secret,sid,access,private,env['ENCRYPTION_KEY']):assert value not in raw
        assert 'storage_not_mounted' not in raw
        for line in raw.splitlines():
            try:item=json.loads(line)
            except ValueError:continue
            if isinstance(item,dict) and item.get('event'):events.append(item)
    def start():
        docker('run','-d','--name',api,'--network',network,'--publish','127.0.0.1::8000',
               '--memory','2g','--cpus','2','--cap-drop','ALL','--security-opt','no-new-privileges:true',
               *environment,image)
        resources.add(api)
        assert json.loads(docker('inspect','--format','{{json .Mounts}}',api))==[]
        port=docker('port',api,'8000/tcp').rsplit(':',1)[1]
        return 'http://127.0.0.1:'+port
    def wait_ready(base):
        deadline=time.monotonic()+300
        while time.monotonic()<deadline:
            try:
                response=httpx.get(base+'/health/knowledge',headers=headers,timeout=20)
                if response.status_code==200:return response.json()
            except httpx.HTTPError:pass
            time.sleep(.5)
        collect();pytest.fail('MinIO API recovery did not finish; inspect structured test events.',pytrace=False)
    try:
        docker('build','--tag',image,ROOT)
        with tempfile.TemporaryDirectory(prefix='gianna-minio-build-') as directory:
            definition=Path(directory)/'Dockerfile'
            definition.write_text('FROM '+image+'\nCOPY --chown=10001:10001 tests /app/tests\n',encoding='utf-8')
            docker('build','--file',definition,'--tag',image,ROOT)
        docker('network','create',network);created_network=True
        docker('run','-d','--name',object_name,'--network',network,'--network-alias','objectstore',
               '--tmpfs','/data:mode=1777','--env','MINIO_ROOT_USER','--env','MINIO_ROOT_PASSWORD',MINIO_IMAGE,'server','/data')
        resources.add(object_name)
        docker('run','-d','--name',db_name,'--network',network,'--network-alias','maria','--tmpfs','/var/lib/mysql',
               '--env','MARIADB_ROOT_PASSWORD','--env','MARIADB_PASSWORD','--env','MARIADB_USER=gianna',
               '--env','MARIADB_DATABASE=gianna_recovery','mariadb:11.4')
        resources.add(db_name)
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            ready=subprocess.run(['docker','exec',db_name,'healthcheck.sh','--connect','--innodb_initialized'],capture_output=True)
            if ready.returncode==0:break
            time.sleep(.5)
        else:pytest.fail('Disposable MariaDB did not start.',pytrace=False)
        output=docker('run','--rm','--name',seed,'--network',network,'--memory','2g','--cpus','2',
                      *environment,'--env','WORKER_ENABLED=false',image,'python','-m','tests.recovery_probe','seed')
        expected=json.loads(output.splitlines()[-1]);record('real_build_and_private_minio_persistence',chunks=expected['chunks'])
        base=start();wait_ready(base)
        state=json.loads(docker('exec',api,'python','-m','tests.recovery_probe','assert'))
        assert state['editorial_unchanged'];record('fresh_cache_restored_without_volume',**state)
        storage=httpx.get(base+'/health/installation',headers=headers,timeout=20)
        assert storage.status_code==200 and storage.json()['code']!='storage_not_mounted'
        record('installation_and_knowledge_healthy')
        collect();docker('rm','-f',api);resources.remove(api)
        base=start();wait_ready(base)
        again=json.loads(docker('exec',api,'python','-m','tests.recovery_probe','assert'))
        assert again['version_id']==expected['version_id'] and again['editorial_unchanged']
        record('second_replacement_preserves_publication_and_evidence',**again)
        collect()
        assert any(row['event']=='artifacts.restored_from_minio' for row in events)
        record('pinned_models_restored_from_minio')
        assert len({row['boot_id'] for row in events if row.get('boot_id')})>=2
        record('correlated_logs_across_replacements_without_secrets')
        destination=ROOT/'reports/minio';destination.mkdir(parents=True,exist_ok=True)
        (destination/'redeploy.json').write_text(json.dumps(dict(scenarios=scenarios,api_persistent_mounts=0,
            generator_calls=0,editorial_unchanged=True,events=len(events)),indent=2)+'\n',encoding='utf-8')
        (destination/'redeploy-events.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in events),encoding='utf-8')
    finally:
        for container in [api,seed,db_name,object_name]:
            if container in resources or container==seed:subprocess.run(['docker','rm','-f',container],capture_output=True,timeout=60)
        if created_network:subprocess.run(['docker','network','rm',network],capture_output=True,timeout=60)
        subprocess.run(['docker','image','rm','--force',image],capture_output=True,timeout=60)
