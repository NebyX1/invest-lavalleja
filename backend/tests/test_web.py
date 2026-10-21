"""Real Flask request tests. Explicitly skipped when Flask is unavailable in the execution environment."""
import json
import re
import time
import pytest
pytest.importorskip('flask',reason='Flask is not installed in this execution environment; run the suite after installing requirements.')
from gianna import create_app
from gianna.security import token_hash
from gianna.config import Config

@pytest.fixture
def app(cfg):
    result=create_app(cfg);result.config['TESTING']=True
    result.extensions['gianna'].security.mailer=lambda address,code:None
    return result


def csrf(client):
    client.get('/admin/login')
    with client.session_transaction(path='/admin/login') as session:return session['csrf']


def public_captcha(client,origin='http://localhost'):
    response=client.get('/api/captcha',headers={'Origin':origin})
    assert response.status_code==200
    left,right=map(int,re.search(r'(\d+) \+ (\d+)',response.json['question']).groups())
    return response,left+right


def admin_captcha(client):
    response=client.get('/admin/login')
    assert response.status_code==200
    left,right=map(int,re.search(r'(\d+) \+ (\d+)',response.get_data(as_text=True)).groups())
    with client.session_transaction(path='/admin/login') as sess:return sess['csrf'],left+right


def authenticate(app,client,role='owner'):
    s=app.extensions['gianna'];uid=s.security.create_user('test@example.test','Test','a-long-test-password',role,'email')
    s.security.mailer=lambda email,code:None
    token,kind=s.security.begin_login('test@example.test','a-long-test-password','127.0.0.1')
    # Establish a legitimate session in the DB to test HTTP authorization separately from OTP unit tests.
    raw='test-session-opaque';now=time.time()
    s.db.execute('INSERT INTO admin_sessions VALUES(?,?,?,?,?,?)',(token_hash(raw),uid,now,now,now+1000,now))
    with client.session_transaction() as sess:sess['sid']=raw;sess['csrf']='csrf-test-value'
    return uid


def test_login_security_headers(app):
    c=app.test_client();r=c.get('/admin/login')
    assert r.status_code==200
    assert r.headers['Referrer-Policy']=='same-origin'
    assert "frame-ancestors 'none'" in r.headers['Content-Security-Policy']
    assert 'unsafe-inline' not in r.headers['Content-Security-Policy']
    assert 'HttpOnly' in r.headers['Set-Cookie'] and 'SameSite=Strict' in r.headers['Set-Cookie']


def test_admin_forms_keep_origin_through_login_and_second_factor(cfg):
    from dataclasses import replace

    origin='https://api.example.test'
    app=create_app(replace(cfg,production=True,proxy_hops=1,
        trusted_hosts=('api.example.test',),public_origins=(origin,'https://portal.example.test')))
    app.config['TESTING']=True
    s=app.extensions['gianna'];codes=[]
    s.security.mailer=lambda address,code:codes.append(code)
    s.security.create_user('owner@example.test','Owner','a-long-test-password','owner')
    client=app.test_client()
    # Coolify terminates TLS: the application receives HTTP plus the trusted
    # forwarded scheme, while browser forms send the public HTTPS origin.
    base_url='http://api.example.test'
    proxy_headers={'X-Forwarded-Proto':'https'}
    form_headers={**proxy_headers,'Origin':origin}
    page=client.get('/admin/login',base_url=base_url,headers=proxy_headers)
    assert page.status_code==200 and page.headers['Referrer-Policy']=='same-origin'
    assert 'Secure' in page.headers['Set-Cookie']
    html=page.get_data(as_text=True)
    csrf_token=re.search(r'name="csrf" value="([^"]+)"',html).group(1)
    left,right=map(int,re.search(r'(\d+) \+ (\d+)',html).groups())
    data={'csrf':csrf_token,'captcha':str(left+right),'email':'owner@example.test','password':'a-long-test-password'}
    for denied_origin in ('null','https://portal.example.test','https://evil.example.test'):
        denied=client.post('/admin/login',base_url=base_url,data=data,
            headers={**proxy_headers,'Origin':denied_origin})
        assert denied.status_code==403 and 'Origen del formulario no permitido' in denied.get_data(as_text=True)
    login=client.post('/admin/login',base_url=base_url,data=data,headers=form_headers)
    assert login.status_code==302 and login.location.endswith('/admin/mfa')
    page=client.get('/admin/mfa',base_url=base_url,headers=proxy_headers)
    assert page.status_code==200 and page.headers['Referrer-Policy']=='same-origin'
    with client.session_transaction(base_url=origin,path='/admin/mfa') as sess:
        pending=sess['pending'];csrf_token=sess['csrf']
    challenge=s.security.challenge_info(pending)
    assert challenge['kind']=='email' and challenge['secret'] is None
    code=codes[0]
    data={'csrf':csrf_token,'code':code}
    for denied_origin in ('null','https://portal.example.test','https://evil.example.test'):
        denied=client.post('/admin/mfa',base_url=base_url,data=data,
            headers={**proxy_headers,'Origin':denied_origin})
        assert denied.status_code==403 and 'Origen del formulario no permitido' in denied.get_data(as_text=True)
    assert client.post('/admin/mfa',base_url=base_url,data={'code':code},headers=form_headers).status_code==403
    assert s.security.challenge_info(pending)['attempts']==0
    wrong=client.post('/admin/mfa',base_url=base_url,data={'csrf':csrf_token,'code':'incorrecto'},headers=form_headers)
    assert wrong.status_code==401
    assert 'enviado a tu correo' in wrong.get_data(as_text=True) and 'name="code"' in wrong.get_data(as_text=True)
    assert client.get('/admin/dashboard',base_url=base_url,headers=proxy_headers).status_code==302
    verified=client.post('/admin/mfa',base_url=base_url,data=data,headers=form_headers)
    assert verified.status_code==302
    assert client.get('/admin/dashboard',base_url=base_url,headers=proxy_headers).status_code==200


def test_human_test_mode_is_loopback_only(cfg, tmp_path):
    from dataclasses import asdict
    options = asdict(cfg) | {'data_dir': tmp_path / 'human-test', 'human_test_mode': True}
    test_environment = {'FLASK_ENV': 'testing', 'DATABASE_URL': ''}
    assert Config.from_env(options, environ=test_environment).human_test_mode is True
    for invalid in (
        {'production': True},
        {'trusted_hosts': ('example.com',)},
        {'public_origins': ('https://example.com',)},
    ):
        with pytest.raises(ValueError, match='prueba humana'):
            Config.from_env(options | invalid, environ=test_environment)


def test_public_config_identifies_human_test(app):
    response = app.test_client().get('/api/config', headers={'Origin': 'http://localhost'})
    assert response.status_code == 200
    assert response.json['test_mode'] is False


def test_csrf_is_required_on_mutation(app):
    c=app.test_client();c.get('/admin/login')
    assert c.post('/admin/login',data={'email':'x@example.test','password':'x'}).status_code==403


def test_anonymous_admin_not_accessible(app):
    c=app.test_client();assert c.get('/admin/dashboard').status_code==302
    assert c.get('/admin/api/diagnostics').status_code==401


def test_viewer_cannot_import_or_change_settings(app):
    c=app.test_client();authenticate(app,c,'viewer')
    assert c.get('/admin/settings').status_code==403
    assert c.post('/admin/bases/import',data={'csrf':'csrf-test-value'}).status_code==403


def test_logout_get_not_a_mutation(app):
    c=app.test_client();authenticate(app,c)
    assert c.get('/admin/logout').status_code==405
    assert c.post('/admin/logout',data={'csrf':'csrf-test-value'}).status_code==302


def test_last_owner_cannot_be_disabled(app):
    c=app.test_client();id=authenticate(app,c)
    response=c.post('/admin/users/'+id+'/update',data={'csrf':'csrf-test-value','role':'viewer'})
    assert response.status_code==409


def test_public_capability_cannot_access_admin(app):
    c=app.test_client();challenge,answer=public_captcha(c)
    r=c.post('/api/sessions',json={'captcha_id':challenge.json['id'],'captcha_answer':str(answer)},headers={'Origin':'http://localhost'})
    assert r.status_code==201
    token=r.json['token'];assert c.get('/admin/api/diagnostics',headers={'Authorization':'Bearer '+token}).status_code==401


def test_public_bad_origin(app):
    c=app.test_client();r=c.post('/api/sessions',json={},headers={'Origin':'https://evil.example.test'})
    assert r.status_code==403


def test_public_captcha_contract_and_replay(app):
    c=app.test_client();challenge,answer=public_captcha(c)
    assert set(challenge.json)=={'id','question','expires_in'}
    assert challenge.json['expires_in']==600
    assert challenge.headers['Cache-Control']=='no-store'
    assert challenge.headers['Access-Control-Allow-Origin']=='http://localhost'
    assert app.extensions['gianna'].db.one('SELECT id_hash FROM captcha_challenges')['id_hash']!=challenge.json['id']
    data={'captcha_id':challenge.json['id'],'captcha_answer':str(answer)}
    assert c.post('/api/sessions',json={},headers={'Origin':'http://localhost'}).json['error']['code']=='captcha_invalid'
    assert c.post('/api/sessions',json=data,headers={'Origin':'http://localhost'}).status_code==201
    replay=c.post('/api/sessions',json=data,headers={'Origin':'http://localhost'})
    assert replay.status_code==400 and replay.json['error']['code']=='captcha_invalid'


def test_public_captcha_wrong_answer_expiry_and_origin(app):
    c=app.test_client();challenge,answer=public_captcha(c)
    data={'captcha_id':challenge.json['id'],'captcha_answer':str(answer)}
    wrong=c.post('/api/sessions',json={**data,'captcha_answer':'99'},headers={'Origin':'http://localhost'})
    assert wrong.status_code==400 and wrong.json['error']['code']=='captcha_invalid'
    assert c.post('/api/sessions',json=data,headers={'Origin':'http://localhost'}).status_code==400
    challenge,answer=public_captcha(c);data={'captcha_id':challenge.json['id'],'captcha_answer':str(answer)}
    app.extensions['gianna'].db.execute('UPDATE captcha_challenges SET expires_at=? WHERE id_hash=?',
                                         (time.time()-1,token_hash(challenge.json['id'])))
    assert c.post('/api/sessions',json=data,headers={'Origin':'http://localhost'}).status_code==400
    challenge,answer=public_captcha(c);data={'captcha_id':challenge.json['id'],'captcha_answer':str(answer)}
    assert c.post('/api/sessions',json=data,headers={'Origin':'https://evil.example.test'}).status_code==403
    assert c.post('/api/sessions',json=data,headers={'Origin':'http://localhost'}).status_code==201


def test_public_captcha_issue_rate_limit(app):
    c=app.test_client()
    for _ in range(20):assert c.get('/api/captcha',headers={'Origin':'http://localhost'}).status_code==200
    response=c.get('/api/captcha',headers={'Origin':'http://localhost'})
    assert response.status_code==429 and response.json['error']['code']=='rate_limited'


def test_public_captcha_verification_rate_limit(app):
    c=app.test_client();headers={'Origin':'http://localhost'}
    for _ in range(10):
        response=c.post('/api/sessions',json={},headers=headers)
        assert response.status_code==400 and response.json['error']['code']=='captcha_invalid'
    response=c.post('/api/sessions',json={},headers=headers)
    assert response.status_code==429 and response.json['error']['code']=='rate_limited'


def test_backend_chat_renders_human_challenge_controls(app):
    response=app.test_client().get('/chat')
    assert response.status_code==200
    html=response.get_data(as_text=True)
    assert 'id="chat-captcha"' in html and 'id="captcha-answer"' in html
    assert 'id="refresh-captcha"' in html


def test_project_memory_is_encrypted_private_and_survives_transcript_trimming(app):
    from gianna.services.project_memory import state_for
    from gianna.services.harness import AgentHarness
    c=app.test_client();s=app.extensions['gianna'];headers={'Origin':'http://localhost'}
    challenge,answer=public_captcha(c)
    created=c.post('/api/sessions',json={'captcha_id':challenge.json['id'],'captcha_answer':str(answer)},headers=headers)
    headers['Authorization']='Bearer '+created.json['token']
    state=state_for(AgentHarness.retrieval_plan('Quiero instalar un boliche',[]))
    received=[]
    def reply(question,settings,**kwargs):
        received.append(kwargs['project_state'])
        result={'id':'test','answer':'Respuesta','status':'insufficient_evidence','mode':'knowledge','citations':[]}
        if len(received)==1:result['_conversation_state']=state
        return result
    s.rag.answer=reply
    for index in range(8):
        # Keep rate limiting enabled; reset only this test's counters to
        # exercise >12 retained messages without spending a minute waiting.
        s.db.execute('DELETE FROM rate_limits')
        response=c.post('/api/chat',json={'message':'Quiero instalar un boliche' if index==0 else 'Gracias'},headers=headers)
        assert response.status_code==200 and '_conversation_state' not in response.json
    assert all(item.get('activity')==state['activity'] for item in received[1:])
    row=s.db.one('SELECT history_encrypted FROM chat_sessions')
    assert 'boliche' not in row['history_encrypted']
    stored=json.loads(s.security.unseal(row['history_encrypted']))
    assert len(stored['messages'])==12 and stored['project']==state
    assert c.post('/api/chat',json={'message':'Hola','project_state':state},headers=headers).status_code==400
    assert c.delete('/api/sessions/current',headers=headers).status_code==200
    assert not s.db.one('SELECT id_hash FROM chat_sessions')


def test_admin_login_requires_fresh_captcha(app):
    c=app.test_client();s=app.extensions['gianna'];s.security.create_user('owner@example.test','Owner','a-long-test-password','owner')
    csrf_token,answer=admin_captcha(c)
    login={'csrf':csrf_token,'email':'owner@example.test','password':'a-long-test-password'}
    assert c.post('/admin/login',data=login).status_code==302
    with c.session_transaction(path='/admin/login') as sess:assert 'pending' not in sess and 'login_captcha_id' not in sess
    csrf_token,answer=admin_captcha(c);login['csrf']=csrf_token
    assert c.post('/admin/login',data={**login,'captcha':'99'}).status_code==302
    assert c.post('/admin/login',data={**login,'captcha':str(answer)}).status_code==302
    with c.session_transaction(path='/admin/login') as sess:assert 'pending' not in sess
    csrf_token,answer=admin_captcha(c);login['csrf']=csrf_token
    response=c.post('/admin/login',data={**login,'captcha':str(answer)})
    assert response.status_code==302 and response.location.endswith('/admin/mfa')
    with c.session_transaction(path='/admin/login') as sess:assert 'pending' in sess and 'login_captcha_id' not in sess


def test_dashboard_templates_render(app):
    c=app.test_client();authenticate(app,c)
    for path in ['/admin/dashboard','/admin/bases','/admin/jobs','/admin/lab','/admin/analytics','/admin/settings','/admin/users','/admin/audit','/admin/security']:
        r=c.get(path);assert r.status_code==200,(path,r.status_code)


def test_console_can_bootstrap_email_mfa_owner(app):
    result=app.test_cli_runner().invoke(args=['create-admin','--email','owner@example.test',
                                            '--name','Owner'],
                                     input='a-long-test-password\na-long-test-password\n')
    assert result.exit_code==0,result.output
    user=app.extensions['gianna'].db.one('SELECT mfa_method,mfa_enrolled FROM users WHERE email=?',
                                          ('owner@example.test',))
    assert user=={'mfa_method':'email','mfa_enrolled':1}
    reset=app.test_cli_runner().invoke(args=['reset-admin','--email','owner@example.test'],
                                      input='y\nanother-long-password\nanother-long-password\n')
    assert reset.exit_code==0,reset.output
    user=app.extensions['gianna'].db.one('SELECT mfa_method,mfa_enrolled FROM users WHERE email=?',
                                          ('owner@example.test',))
    assert user=={'mfa_method':'email','mfa_enrolled':1}
