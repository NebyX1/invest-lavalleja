"""Expected login errors stay inside the form, matching Buzón Ciudadano."""
import re
import time

import pytest

from gianna import create_app
from gianna.security import token_hash


PASSWORD='a-long-test-password'


@pytest.fixture
def app(cfg):
    app=create_app(cfg);app.config['TESTING']=True
    app.extensions['test_mail']=[]
    app.extensions['gianna'].security.mailer=lambda address,code:app.extensions['test_mail'].append((address,code))
    return app


def submission(client,page,email='owner@example.test',password=PASSWORD):
    left,right=map(int,re.search(r'(\d+) \+ (\d+)',page.get_data(as_text=True)).groups())
    with client.session_transaction(path='/admin/login') as sess:csrf=sess['csrf']
    return {'email':email,'password':password,'csrf':csrf,'captcha':str(left+right)}


def assert_inline(response,message,status=200):
    assert response.status_code==status and 'Location' not in response.headers
    html=response.get_data(as_text=True)
    form=re.search(r'<form\b[^>]*>(.*?)</form>',html,re.S).group(1)
    assert message in form and 'role="alert"' in form
    assert html.count(message)==1
    assert 'name="email"' in form and 'name="password"' in form and 'name="captcha"' in form
    assert 'No se completó la operación.' not in html
    assert not re.search(r'<input[^>]*name="password"[^>]*\bvalue=',form)
    return form


@pytest.mark.parametrize('reason',['wrong_password','unknown_account','inactive_account'])
def test_credentials_errors_stay_in_form_and_do_not_send_otp(app,reason):
    s=app.extensions['gianna'];client=app.test_client()
    if reason!='unknown_account':
        user=s.security.create_user('owner@example.test','Owner',PASSWORD,'owner')
        if reason=='inactive_account':s.db.execute('UPDATE users SET active=0 WHERE id=?',(user,))
    page=client.get('/admin/login')
    with client.session_transaction(path='/admin/login') as sess:previous_captcha=sess['login_captcha_id']
    entered='wrong-password-must-not-be-returned' if reason=='wrong_password' else PASSWORD
    response=client.post('/admin/login',data=submission(client,page,password=entered))
    form=assert_inline(response,'Correo o contraseña incorrectos.')
    assert 'value="owner@example.test"' in form and entered not in response.get_data(as_text=True)
    with client.session_transaction(path='/admin/login') as sess:
        assert sess['login_captcha_id']!=previous_captcha
        assert 'pending' not in sess and 'sid' not in sess
    assert s.db.one('SELECT id_hash FROM captcha_challenges WHERE id_hash=?',(token_hash(previous_captcha),)) is None
    assert s.db.all('SELECT * FROM auth_challenges')==[] and s.db.all('SELECT * FROM admin_sessions')==[]
    assert app.extensions['test_mail']==[]


@pytest.mark.parametrize('reason',['wrong','missing','expired','consumed'])
def test_captcha_errors_stay_in_form_with_fresh_challenge(app,reason):
    s=app.extensions['gianna'];client=app.test_client()
    s.security.create_user('owner@example.test','Owner',PASSWORD,'owner')
    page=client.get('/admin/login');data=submission(client,page)
    with client.session_transaction(path='/admin/login') as sess:previous_captcha=sess['login_captcha_id']
    if reason=='wrong':data['captcha']='99'
    elif reason=='missing':data.pop('captcha')
    elif reason=='expired':s.db.execute('UPDATE captcha_challenges SET expires_at=?',(time.time()-1,))
    else:assert s.security.consume_captcha(previous_captcha,data['captcha'],'admin-login','http://localhost','127.0.0.1')
    response=client.post('/admin/login',data=data)
    assert_inline(response,'El CAPTCHA es incorrecto o venció.')
    with client.session_transaction(path='/admin/login') as sess:
        assert sess['login_captcha_id']!=previous_captcha and 'pending' not in sess
    assert app.extensions['test_mail']==[] and s.db.all('SELECT * FROM auth_challenges')==[]


def test_user_can_retry_from_error_response_and_then_complete_email_2fa(app):
    s=app.extensions['gianna'];client=app.test_client()
    s.security.create_user('owner@example.test','Owner',PASSWORD,'owner')
    page=client.get('/admin/login')
    response=client.post('/admin/login',data=submission(client,page,password='wrong-password'))
    assert_inline(response,'Correo o contraseña incorrectos.')
    # Submit the refreshed form directly, without navigating away or an extra GET.
    corrected=client.post('/admin/login',data=submission(client,response))
    assert corrected.status_code==302 and corrected.location.endswith('/admin/mfa')
    assert len(app.extensions['test_mail'])==1
    with client.session_transaction(path='/admin/mfa') as sess:csrf=sess['csrf']
    verified=client.post('/admin/mfa',data={'csrf':csrf,'code':app.extensions['test_mail'][0][1]})
    assert verified.status_code==302 and verified.location.endswith('/admin/dashboard')
    assert client.get('/admin/dashboard').status_code==200


def test_retained_email_is_escaped_and_password_is_not_returned(app):
    client=app.test_client();email='"><script>alert(1)</script>@example.test'
    page=client.get('/admin/login')
    response=client.post('/admin/login',data=submission(client,page,email=email))
    form=assert_inline(response,'Correo o contraseña incorrectos.')
    assert email not in form and '&lt;script&gt;' in form and PASSWORD not in form


def test_mail_failure_is_displayed_in_login_form_without_opening_session(app):
    s=app.extensions['gianna'];client=app.test_client()
    s.security.create_user('owner@example.test','Owner',PASSWORD,'owner')
    def unavailable(address,code):raise RuntimeError('private-smtp-details')
    s.security.mailer=unavailable
    page=client.get('/admin/login')
    response=client.post('/admin/login',data=submission(client,page))
    assert_inline(response,'No se pudo enviar el código.',503)
    assert 'private-smtp-details' not in response.get_data(as_text=True)
    assert s.db.all('SELECT * FROM admin_sessions')==[]
    with client.session_transaction(path='/admin/login') as sess:assert 'sid' not in sess and 'pending' not in sess
