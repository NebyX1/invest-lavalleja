"""Account CLI compatibility and authorization, without real accounts or SMTP."""
import json
import re

import pytest

from gianna import create_app
from gianna.security import verify_password


PASSWORD='a-long-cli-test-password'


@pytest.fixture
def app(cfg):
    result=create_app(cfg)
    result.config['TESTING']=True
    return result


@pytest.mark.parametrize('flag,role',[
    ('true','owner'),('false','editor'),('TRUE','owner'),('False','editor'),(None,'editor'),
])
def test_create_admin_buzon_syntax(app,flag,role,caplog):
    args=['create-admin','Nombre del administrador',' CLI@Example.Test ',PASSWORD]
    if flag is not None:args.append(flag)
    result=app.test_cli_runner().invoke(args=args)
    assert result.exit_code==0,result.output
    s=app.extensions['gianna']
    user=s.db.one('SELECT * FROM users WHERE email=?',('cli@example.test',))
    assert user['name']=='Nombre del administrador'
    assert user['role']==role and user['active']==1 and user['must_change_password']==0
    assert user['mfa_method']=='email' and user['mfa_enrolled']==1
    assert user['password_hash']!=PASSWORD and verify_password(user['password_hash'],PASSWORD)
    audit=s.db.one('SELECT * FROM audit WHERE user_id=?',(user['id'],))
    assert audit['action']==('OWNER_CREATED_BY_CONSOLE' if role=='owner' else 'ADMIN_CREATED_BY_CONSOLE')
    assert json.loads(audit['details_json'])=={'role':role,'mfa_method':'email'}
    assert PASSWORD not in result.output+audit['details_json']+caplog.text
    assert ('Superadministrador creado' if role=='owner' else 'Administrador creado') in result.output


@pytest.mark.parametrize('flag,restricted_status',[('true',200),('false',403)])
def test_cli_accounts_login_with_mfa_and_keep_role_permissions(app,flag,restricted_status):
    result=app.test_cli_runner().invoke(args=['create-admin','Cuenta CLI','cli@example.test',PASSWORD,flag])
    assert result.exit_code==0,result.output
    s=app.extensions['gianna']
    codes=[];s.security.mailer=lambda address,code:codes.append(code)
    client=app.test_client()
    page=client.get('/admin/login')
    left,right=map(int,re.search(r'(\d+) \+ (\d+)',page.get_data(as_text=True)).groups())
    with client.session_transaction(path='/admin/login') as session:csrf=session['csrf']
    login=client.post('/admin/login',data={'email':'cli@example.test','password':PASSWORD,
                                         'csrf':csrf,'captcha':str(left+right)})
    assert login.status_code==302 and login.location.endswith('/admin/mfa')
    assert client.get('/admin/dashboard').status_code==302
    with client.session_transaction(path='/admin/mfa') as session:
        pending=session['pending'];csrf=session['csrf']
    challenge=s.security.challenge_info(pending)
    assert challenge['kind']=='email' and challenge['secret'] is None
    page=client.get('/admin/mfa').get_data(as_text=True)
    visible_text=re.sub(r'<[^>]+>','',page)
    # Random CSRF/nonces can contain the letters QR without rendering a QR code.
    assert 'correo' in visible_text and 'diez minutos' in visible_text and 'QR' not in visible_text
    assert '<img' not in page and 'otpauth://' not in page
    response=client.post('/admin/mfa',data={'csrf':csrf,'code':codes[0]})
    assert response.status_code==302
    assert client.get('/admin/dashboard').status_code==200
    assert client.get('/admin/bases').status_code==200
    for path in ('/admin/users','/admin/settings','/admin/audit'):
        assert client.get(path).status_code==restricted_status,path
    with client.session_transaction(path='/admin/users') as session:csrf=session['csrf']
    response=client.post('/admin/users',data={'csrf':csrf,'name':'Otro usuario',
        'email':'another@example.test','role':'owner','mfa_method':'totp'})
    assert response.status_code==restricted_status
    assert bool(s.db.one('SELECT id FROM users WHERE email=?',('another@example.test',)))==(flag=='true')
    if flag=='true':
        assert s.db.one('SELECT mfa_method FROM users WHERE email=?',('another@example.test',))=={'mfa_method':'email'}


@pytest.mark.parametrize('flag,role',[('true','owner'),('false','editor')])
def test_positional_accounts_support_email_mfa(app,flag,role):
    result=app.test_cli_runner().invoke(args=['create-admin','Cuenta CLI','cli@example.test',PASSWORD,flag])
    assert result.exit_code==0,result.output
    s=app.extensions['gianna']
    user=s.db.one('SELECT role,mfa_method,mfa_enrolled FROM users WHERE email=?',('cli@example.test',))
    assert user=={'role':role,'mfa_method':'email','mfa_enrolled':1}
    codes=[]
    s.security.mailer=lambda address,code:codes.append(code)
    challenge,kind=s.security.begin_login('cli@example.test',PASSWORD,'127.0.0.1')
    assert kind=='email' and len(codes)==1
    _,logged_in=s.security.finish_login(challenge,codes[0],'127.0.0.1')
    assert logged_in['role']==role


@pytest.mark.parametrize('args',[
    ['Nombre'],['Nombre','cli@example.test'],
    ['Nombre','cli@example.test',PASSWORD,'yes'],
    ['Nombre','cli@example.test',PASSWORD,'1'],
    ['Nombre','cli@example.test',PASSWORD,'false','extra'],
    ['Nombre','cli@example.test',PASSWORD,'true','--email','other@example.test'],
    ['Nombre','cli@example.test',PASSWORD,'false','--name','Otro nombre'],
    [' ','cli@example.test',PASSWORD,'false'],
    ['x'*101,'cli@example.test',PASSWORD,'true'],
    ['Nombre','correo-invalido',PASSWORD,'false'],
    ['Nombre','cli@example.test','corta','true'],
    ['Nombre','cli@example.test','x'*257,'false'],
])
def test_invalid_creation_does_not_create_accounts_or_reveal_password(app,args):
    result=app.test_cli_runner().invoke(args=['create-admin',*args])
    assert result.exit_code!=0
    assert PASSWORD not in result.output
    s=app.extensions['gianna']
    assert s.db.all('SELECT id FROM users')==[]
    assert s.db.all('SELECT id FROM audit')==[]


def test_duplicate_email_cannot_overwrite_password_or_elevate_role(app):
    runner=app.test_cli_runner()
    assert runner.invoke(args=['create-admin','Administrador','cli@example.test',PASSWORD,'false']).exit_code==0
    result=runner.invoke(args=['create-admin','Superadministrador','CLI@example.test','another-long-password','true'])
    assert result.exit_code==1 and 'Ya existe una cuenta con ese correo.' in result.output
    s=app.extensions['gianna']
    users=s.db.all('SELECT * FROM users')
    assert len(users)==1 and users[0]['role']=='editor'
    assert users[0]['name']=='Administrador' and verify_password(users[0]['password_hash'],PASSWORD)
    assert 'another-long-password' not in result.output and PASSWORD not in result.output
    assert len(s.db.all('SELECT id FROM audit'))==1


def test_email_mfa_requires_smtp(cfg):
    from dataclasses import replace
    app=create_app(replace(cfg,smtp_host=''))
    result=app.test_cli_runner().invoke(args=['create-admin','Administrador','cli@example.test',PASSWORD,'false'])
    assert result.exit_code==1 and 'Configurá SMTP' in result.output
    assert app.extensions['gianna'].db.all('SELECT id FROM users')==[]


def test_interactive_bootstrap_still_creates_owner_with_hidden_password(app):
    result=app.test_cli_runner().invoke(args=['create-admin'],
        input=f'owner@example.test\nPropietario\n{PASSWORD}\n{PASSWORD}\n')
    assert result.exit_code==0,result.output
    assert PASSWORD not in result.output
    assert app.extensions['gianna'].db.one('SELECT role FROM users')['role']=='owner'
