"""Opt-in real container replacement, MariaDB, LanceDB and pinned ONNX inference.

Run on a Docker host: python -m pytest tests/test_recovery_docker.py --recovery-docker -q.
Never reads .env; every container, network and volume is created by this test.
No generation provider is configured or called. Downloads the pinned model pair.
"""
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import time

from cryptography.fernet import Fernet
from flask import Flask
import httpx
import pytest


ROOT=Path(__file__).resolve().parents[1]


def docker(*args,env=None,timeout=1800):
    result=subprocess.run(['docker',*map(str,args)],env=env,capture_output=True,text=True,timeout=timeout)
    if result.returncode:
        # Commands can contain generated test credentials. Never echo argv/env.
        detail=result.stderr[-2500:]
        for key,value in (env or {}).items():
            if re.search('password|secret|token|key|session',key,re.I) and len(value)>=4:
                detail=detail.replace(value,'[redacted]')
        pytest.fail('Disposable Docker operation failed: '+detail,pytrace=False)
    # Runtime JSON is emitted on stderr. Docker forwards those logs on its own
    # stderr, even for a successful `docker logs` operation.
    return (result.stdout+(result.stderr if args and args[0]=='logs' else '')).strip()


def test_real_redeploy_and_incident_recovery(request):
    if not request.config.getoption('--recovery-docker'):
        pytest.skip('Pass --recovery-docker for real ONNX/MariaDB/LanceDB container tests.')
    suffix=secrets.token_hex(5);prefix='gianna-recovery-'+suffix
    image=prefix+':test';network=prefix;volume=prefix+'-data';db_name=prefix+'-db'
    api_name=prefix+'-api';seed_name=prefix+'-seed'
    password=secrets.token_hex(24);secret=secrets.token_urlsafe(48);sid=secrets.token_urlsafe(40)
    env={**os.environ,'MARIADB_ROOT_PASSWORD':password,'MARIADB_PASSWORD':password,
         'DATABASE_URL':'mariadb+mariadbconnector://gianna:'+password+'@maria:3306/gianna_recovery',
         'SECRET_KEY':secret,'ENCRYPTION_KEY':Fernet.generate_key().decode(),'GIANNA_TEST_SESSION':sid}
    steps=[];api_running=False;network_created=False;volume_created=False
    mount_path='/app/data';data_path=mount_path+'/runtime'
    captured_logs={}
    test_secrets=(password,secret,sid,env['ENCRYPTION_KEY'],'only-a-generated-test-password')
    def record(name,**extra):
        steps.append({'scenario':name,'passed':True,**extra})
        print('Container regression passed: '+name,flush=True)
    def probe(action,*args):
        return docker('exec',api_name,'python','-m','tests.recovery_probe',action,*args,env=env)
    def collect_logs():
        identifier=docker('inspect','--format','{{.Id}}',api_name)
        output=docker('logs',api_name)
        assert all(value not in output for value in test_secrets), 'A disposable secret appeared in runtime logs'
        rows=[json.loads(line) for line in output.splitlines() if line.startswith('{')]
        assert rows and all('event' in row and 'boot_id' in row for row in rows)
        captured_logs[identifier]=rows
        return rows
    def admin_headers():
        app=Flask('regression');app.secret_key=secret
        cookie=app.session_interface.get_signing_serializer(app).dumps({'sid':sid,'csrf':'regression-csrf'})
        return {'Host':'localhost','X-Forwarded-Proto':'https','Origin':'https://localhost',
                'Cookie':'gianna_admin='+cookie}
    def diagnostics():
        response=httpx.get(base+'/admin/api/diagnostics',headers=admin_headers(),timeout=20)
        assert response.status_code==200, 'Authenticated diagnostics failed'
        assert all(value not in response.text for value in test_secrets), 'A disposable secret appeared in diagnostics'
        return response.json()
    def job_status(identifier):
        response=httpx.get(base+'/admin/api/jobs/'+identifier,headers=admin_headers(),timeout=10)
        assert response.status_code==200
        return response.json()
    def start(worker=True,mounted=True):
        nonlocal api_running,base
        storage=['--mount','type=volume,source='+volume+',target='+mount_path] if mounted else []
        docker('run','--detach','--name',api_name,'--network',network,'--publish','127.0.0.1::8000',
               *storage,'--read-only','--tmpfs','/tmp:size=128m,mode=1777',
               '--memory','2g','--cpus','2','--init',*environment,'--env','WORKER_ENABLED='+str(worker).lower(),image,env=env)
        api_running=True
        port=int(docker('port',api_name,'8000/tcp').rsplit(':',1)[1])
        base='http://127.0.0.1:'+str(port)
    def stop():
        nonlocal api_running
        docker('stop','--time','5',api_name)
        collect_logs()
        docker('rm',api_name);api_running=False
    def get_config():
        return httpx.get(base+'/api/config',headers={'Host':'localhost','Origin':'https://portal.example.test','X-Forwarded-Proto':'https'},timeout=5)
    def wait_http(ready=True,deadline=240):
        until=time.monotonic()+deadline
        while time.monotonic()<until:
            try:
                response=get_config()
                if response.status_code==200 and (not ready or response.json()['available']):return response.json()
            except httpx.HTTPError:pass
            time.sleep(.5)
        pytest.fail('Regression API readiness timed out; logs: '+docker('logs','--tail','35',api_name)[-3500:],pytrace=False)
    def evidence():
        response=httpx.post(base+'/admin/lab',data={'csrf':'regression-csrf','mode':'retrieve','question':'¿Qué dice la evidencia territorial PINO-314?'},
            headers=admin_headers(),timeout=50)
        assert response.status_code==200, response.text[:300]
        assert 'PINO-314' in response.text and 'Evidencia de persistencia' in response.text
        return json.loads(probe('assert'))
    environment=['--env','FLASK_ENV=production','--env','DATA_DIR='+data_path,'--env','GIANNA_RECOVERY_REGRESSION=isolated',
                 '--env','HF_HOME='+data_path+'/models/huggingface','--env','XDG_CACHE_HOME='+data_path+'/cache',
                 '--env','HF_XET_CACHE='+data_path+'/models/xet',
                 '--env','CORS_ORIGINS=https://portal.example.test,https://localhost','--env','DATABASE_URL','--env','SECRET_KEY',
                 '--env','ENCRYPTION_KEY','--env','GIANNA_TEST_SESSION','--env','OLLAMA_API_KEY=','--env','OLLAMA_MODEL=',
                 '--env','MAIL_SERVER=smtp.example.test','--env','MAIL_DEFAULT_SENDER=regression@example.test']
    base=''
    try:
        docker('build','--tag',image,ROOT)
        with tempfile.TemporaryDirectory(prefix='gianna-recovery-build-') as directory:
            definition=Path(directory)/'Dockerfile'
            definition.write_text('FROM '+image+'\nCOPY --chown=10001:10001 tests /app/tests\n',encoding='utf-8')
            docker('build','--file',definition,'--tag',image,ROOT)
        docker('network','create','--label','gianna.test=recovery',network);network_created=True
        docker('volume','create','--label','gianna.test=recovery',volume);volume_created=True
        docker('run','--detach','--name',db_name,'--network',network,'--network-alias','maria',
               '--tmpfs','/var/lib/mysql','--env','MARIADB_ROOT_PASSWORD','--env','MARIADB_PASSWORD',
               '--env','MARIADB_USER=gianna','--env','MARIADB_DATABASE=gianna_recovery','mariadb:11.4',env=env)
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            ping=subprocess.run(['docker','exec',db_name,'healthcheck.sh','--connect','--innodb_initialized'],capture_output=True)
            if ping.returncode==0:break
            time.sleep(.5)
        else:pytest.fail('Disposable MariaDB startup timed out.',pytrace=False)
        output=docker('run','--rm','--name',seed_name,'--network',network,'--mount','type=volume,source='+volume+',target='+mount_path,
               '--memory','2g','--cpus','2',*environment,'--env','WORKER_ENABLED=false',image,
               'python','-m','tests.recovery_probe','seed',env=env,timeout=1800)
        seed=json.loads(output.splitlines()[-1]);record('real_build_and_publication',chunks=seed['chunks'],fingerprint=seed['fingerprint'])
        start();wait_http();record('automatic_startup',**evidence())
        inventory=diagnostics()['installation']['storage']
        assert inventory['path']==data_path and inventory['mount']['mountpoint']==mount_path
        assert inventory['mount']['durable'] and inventory['identity']['matched']
        record('durable_parent_mount',data_dir=inventory['path'],mountpoint=inventory['mount']['mountpoint'])
        docker('restart','--time','5',api_name)
        # Docker may reassign a randomly published host port on restart.
        base='http://127.0.0.1:'+str(int(docker('port',api_name,'8000/tcp').rsplit(':',1)[1]))
        wait_http();record('process_restart',**evidence())
        stop();start();wait_http();record('container_replacement_same_volume',**evidence())
        # Same MariaDB, replacement API without its data volume. HTTP/admin must
        # remain actionable; a blocked preflight must not spend job attempts or
        # start a model download into the container's ephemeral layer.
        stop();start(mounted=False);wait_http(ready=False)
        until=time.monotonic()+30
        while time.monotonic()<until:
            blocked=diagnostics()
            if blocked['worker']['state']=='blocked':break
            time.sleep(.5)
        else:pytest.fail('Missing-volume preflight was not reported by the worker',pytrace=False)
        assert blocked['installation']['state']=='blocked'
        assert blocked['installation']['code']=='storage_not_mounted'
        assert blocked['installation']['storage']['path']==data_path
        assert blocked['installation']['action']
        assert blocked['model_loaded'] is False and blocked['build_model_loaded'] is False
        response=httpx.post(base+'/admin/warmup',headers=admin_headers(),data={'csrf':'regression-csrf'},timeout=10)
        assert response.status_code==302
        queued_job=response.headers['location'].rstrip('/').rsplit('/',1)[1]
        assert re.fullmatch('[a-f0-9]{32}',queued_job)
        pending=job_status(queued_job)
        assert pending['status']=='queued' and pending['attempts']==0 and pending['started_at'] is None
        state=json.loads(probe('state',queued_job))
        assert state['editorial_digest']==seed['editorial_digest'] and state['version_id']==seed['version_id']
        assert state['data_dir_exists'] is False and state['models_exist'] is False
        blocked_log=collect_logs()
        assert any(row['event']=='worker.blocked' and row['fields'].get('code')=='storage_not_mounted' for row in blocked_log)
        assert not any(row['event']=='queue.claimed' and row['fields'].get('job_id')==queued_job for row in blocked_log)
        record('missing_volume_actionable_preflight',job_id=queued_job,attempts=0,
               code=blocked['installation']['code'],editorial_unchanged=True,models_downloaded=False)
        # Represent the persisted failed row left by the previous release. It
        # belongs to this fixture and was created through the actual admin UI.
        legacy=json.loads(probe('legacy-failed-job',queued_job))
        assert legacy['status']=='failed' and legacy['attempts']==3
        stop();start();wait_http()
        completed=job_status(queued_job)
        assert completed['status']=='done' and completed['attempts']==1
        assert sum(row['event']=='job_resumed_after_preflight' for row in completed['events'])==1
        restored_log=collect_logs()
        for name in ('queue.recovered','queue.claimed','queue.completed'):
            assert any(row['event']==name and row['fields'].get('job_id')==queued_job for row in restored_log)
        blocked_boots={row['boot_id'] for row in blocked_log if row['event']=='worker.blocked'}
        restored_boots={row['boot_id'] for row in restored_log if row['event']=='queue.completed' and row['fields'].get('job_id')==queued_job}
        assert blocked_boots and restored_boots and blocked_boots.isdisjoint(restored_boots)
        record('same_job_automatic_recovery_after_mount_repair',job_id=queued_job,
               attempts=completed['attempts'],correlated_across_redeploy=True,**evidence())
        for damage in ('missing','incomplete'):
            held=subprocess.Popen(['docker','exec',api_name,'python','-m','tests.recovery_probe',damage],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                deadline=time.monotonic()+20
                while time.monotonic()<deadline:
                    if json.loads(probe('held'))['held']:break
                    time.sleep(.1)
                else:pytest.fail('Regression damage lock not established.',pytrace=False)
                config=get_config().json();assert config['available'] is False
                assert config['knowledge_code'] in {'index_missing','index_incomplete'}
                headers={'Host':'localhost','X-Forwarded-Proto':'https','Origin':'https://portal.example.test'}
                captcha=httpx.get(base+'/api/captcha',headers=headers).json()
                a,b=map(int,re.findall(r'\d+',captcha['question']))
                session=httpx.post(base+'/api/sessions',headers=headers,json={'captcha_id':captcha['id'],'captcha_answer':str(a+b)}).json()['token']
                reply=httpx.post(base+'/api/chat',headers={**headers,'Authorization':'Bearer '+session},json={'message':'¿Qué evidencia territorial hay?'}).status_code
                assert reply==503
            finally:
                probe('release');held.communicate(timeout=15)
            wait_http();record(damage+'_collection',controlled_http_status=reply,**evidence())
        # No local weights on the next container: automatic, pinned download.
        probe('models-away');stop();start();wait_http(ready=False)
        wait_http(deadline=900);record('missing_models_auto_recovery',**evidence())
        stats=json.loads(docker('stats','--no-stream','--format','{{json .}}',api_name))
        record('bounded_resources',memory=stats['MemUsage'],cpu=stats['CPUPerc'])
        collect_logs()
        events=[row for rows in captured_logs.values() for row in rows]
        report={'test':'real MariaDB + LanceDB + pinned ONNX, no generation',
                'data_dir':data_path,'mountpoint':mount_path,'runtime_events':len(events),'scenarios':steps}
        destination=ROOT/'reports/persistence';destination.mkdir(parents=True,exist_ok=True)
        (destination/'recovery-docker.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        (destination/'recovery-docker-events.jsonl').write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in events),encoding='utf-8')
    finally:
        if api_running:
            subprocess.run(['docker','rm','--force',api_name],capture_output=True)
        subprocess.run(['docker','rm','--force',seed_name,db_name],capture_output=True)
        # Remove ONLY resources whose names were generated and created above.
        if volume_created:subprocess.run(['docker','volume','rm',volume],capture_output=True)
        if network_created:subprocess.run(['docker','network','rm',network],capture_output=True)
        subprocess.run(['docker','image','rm',image],capture_output=True)
