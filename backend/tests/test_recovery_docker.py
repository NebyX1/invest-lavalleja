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
        pytest.fail('Disposable Docker operation failed: '+result.stderr[-2500:],pytrace=False)
    return result.stdout.strip()


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
    def record(name,**extra):
        steps.append({'scenario':name,'passed':True,**extra})
        print('Container regression passed: '+name,flush=True)
    def probe(action):
        return docker('exec',api_name,'python','-m','tests.recovery_probe',action,env=env)
    def start(worker=True):
        nonlocal api_running,base
        docker('run','--detach','--name',api_name,'--network',network,'--publish','127.0.0.1::8000',
               '--mount','type=volume,source='+volume+',target=/app/data','--read-only','--tmpfs','/tmp:size=128m,mode=1777',
               '--memory','2g','--cpus','2','--init',*environment,'--env','WORKER_ENABLED='+str(worker).lower(),image,env=env)
        api_running=True
        port=int(docker('port',api_name,'8000/tcp').rsplit(':',1)[1])
        base='http://127.0.0.1:'+str(port)
    def stop():
        nonlocal api_running
        docker('stop','--time','5',api_name)
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
        app=Flask('regression');app.secret_key=secret
        cookie=app.session_interface.get_signing_serializer(app).dumps({'sid':sid,'csrf':'regression-csrf'})
        response=httpx.post(base+'/admin/lab',data={'csrf':'regression-csrf','mode':'retrieve','question':'¿Qué dice la evidencia territorial PINO-314?'},
            headers={'Host':'localhost','X-Forwarded-Proto':'https','Origin':'https://localhost',
                     'Cookie':'gianna_admin='+cookie},timeout=50)
        assert response.status_code==200, response.text[:300]
        assert 'PINO-314' in response.text and 'Evidencia de persistencia' in response.text
        return json.loads(probe('assert'))
    environment=['--env','FLASK_ENV=production','--env','DATA_DIR=/app/data','--env','GIANNA_RECOVERY_REGRESSION=isolated',
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
        output=docker('run','--rm','--name',seed_name,'--network',network,'--mount','type=volume,source='+volume+',target=/app/data',
               '--memory','2g','--cpus','2',*environment,'--env','WORKER_ENABLED=false',image,
               'python','-m','tests.recovery_probe','seed',env=env,timeout=1800)
        seed=json.loads(output.splitlines()[-1]);record('real_build_and_publication',chunks=seed['chunks'],fingerprint=seed['fingerprint'])
        start();wait_http();record('automatic_startup',**evidence())
        docker('restart','--time','5',api_name)
        # Docker may reassign a randomly published host port on restart.
        base='http://127.0.0.1:'+str(int(docker('port',api_name,'8000/tcp').rsplit(':',1)[1]))
        wait_http();record('process_restart',**evidence())
        stop();start();wait_http();record('container_replacement_same_volume',**evidence())
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
        report={'test':'real MariaDB + LanceDB + pinned ONNX, no generation','scenarios':steps}
        destination=ROOT/'reports/persistence';destination.mkdir(parents=True,exist_ok=True)
        (destination/'recovery-docker.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    finally:
        if api_running:
            subprocess.run(['docker','rm','--force',api_name],capture_output=True)
        subprocess.run(['docker','rm','--force',seed_name,db_name],capture_output=True)
        # Remove ONLY resources whose names were generated and created above.
        if volume_created:subprocess.run(['docker','volume','rm',volume],capture_output=True)
        if network_created:subprocess.run(['docker','network','rm',network],capture_output=True)
