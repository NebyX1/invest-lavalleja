import concurrent.futures
import time
import pytest
from gianna.security import token_hash,verify_password
from gianna.errors import DomainError

def email_login(security,db):
    sent=[];security.mailer=lambda address,code:sent.append((address,code))
    id=security.create_user('owner@example.test','Owner','a-long-test-password','owner')
    token,kind=security.begin_login('owner@example.test','a-long-test-password','127.0.0.1');assert kind=='email'
    code=sent[0][1]
    challenge=security.challenge_info(token)
    assert sent[0][0]=='owner@example.test' and len(code)==6 and code.isascii() and code.isdigit()
    assert challenge['secret'] is None and challenge['code_hash']!=code
    assert challenge['code_hash'].startswith('$argon2id$') and verify_password(challenge['code_hash'],code)
    assert 599<challenge['expires_at']-time.time()<=600
    session,user=security.finish_login(token,code,'127.0.0.1')
    return id,session


def test_email_code_hash_and_session(security,db):
    id,session=email_login(security,db)
    row=db.one('SELECT * FROM users WHERE id=?',(id,))
    assert row['mfa_method']=='email' and row['totp_secret'] is None and row['mfa_enrolled']==1
    assert db.one('SELECT id_hash FROM admin_sessions')['id_hash']!=session
    assert db.all('SELECT code_hash FROM recovery_codes')==[]
    assert security.session_user(session)['id']==id


def test_otp_replay_rejected(security,db):
    id,_=email_login(security,db)
    sent=[];security.mailer=lambda address,code:sent.append(code)
    token,_=security.begin_login('owner@example.test','a-long-test-password','127.0.0.1')
    security.finish_login(token,sent[0],'127.0.0.1')
    with pytest.raises(DomainError):security.finish_login(token,sent[0],'127.0.0.1')


def test_new_login_invalidates_previous_code_and_codes_are_bound_to_account(security,db,monkeypatch):
    digits=iter('000000111111222222')
    monkeypatch.setattr('gianna.security.secrets.choice',lambda alphabet:next(digits))
    security.create_user('owner@example.test','Owner','a-long-test-password','owner')
    security.create_user('other@example.test','Other','a-long-test-password')
    first,_=security.begin_login('owner@example.test','a-long-test-password','a')
    second,_=security.begin_login('owner@example.test','a-long-test-password','a')
    other,_=security.begin_login('other@example.test','a-long-test-password','a')
    for token,code in ((first,'000000'),(second,'000000'),(other,'111111')):
        with pytest.raises(DomainError):security.finish_login(token,code,'a')
    security.finish_login(second,'111111','a')
    security.finish_login(other,'222222','a')


def test_six_failed_attempts_consume_challenge(security,db):
    security.create_user('person@example.test','P','a-long-test-password')
    token,_=security.begin_login('person@example.test','a-long-test-password','a')
    for _ in range(6):
        with pytest.raises(DomainError):security.finish_login(token,'INVALID','a')
    with pytest.raises(DomainError):security.challenge_info(token)
    assert db.one('SELECT attempts FROM auth_challenges')['attempts']==6


def test_email_mfa_expiry_and_consumption(security,db):
    sent=[];security.mailer=lambda address,code:sent.append(code)
    security.create_user('email@example.test','E','a-long-test-password',mfa_method='email')
    token,kind=security.begin_login('email@example.test','a-long-test-password','a');assert kind=='email'
    db.execute('UPDATE auth_challenges SET expires_at=?',(time.time()-1,))
    with pytest.raises(DomainError):security.finish_login(token,sent[-1],'a')
    token,_=security.begin_login('email@example.test','a-long-test-password','a')
    security.finish_login(token,sent[-1],'a')
    with pytest.raises(DomainError):security.finish_login(token,sent[-1],'a')


def test_inactive_user_and_idle_session(security,db):
    id,sid=email_login(security,db)
    db.execute('UPDATE admin_sessions SET touched_at=?',(time.time()-1900,))
    assert security.session_user(sid) is None
    db.execute('UPDATE users SET active=0 WHERE id=?',(id,))
    with pytest.raises(DomainError):security.begin_login('owner@example.test','a-long-test-password','a')


def test_persistent_atomic_limiter(security,db,cfg):
    security.rate_limit('key',2,60,now=60);security.rate_limit('key',2,60,now=60)
    from gianna.security import Security
    second=Security(db,cfg)
    with pytest.raises(DomainError) as exc:second.rate_limit('key',2,60,now=61)
    assert exc.value.status==429
    second.rate_limit('key',2,60,now=120)


def test_password_change_revokes_all_sessions(security,db):
    id,sid=email_login(security,db)
    security.change_password(id,'a-long-test-password','another-long-test-password')
    assert security.session_user(sid) is None


@pytest.mark.parametrize('code',['１２３４５６','12345','1234567','abcdef','A'*24])
def test_only_six_ascii_digits_are_accepted(security,db,code):
    security.create_user('owner@example.test','Owner','a-long-test-password')
    token,_=security.begin_login('owner@example.test','a-long-test-password','a')
    with pytest.raises(DomainError):security.finish_login(token,code,'a')
    assert db.all('SELECT id_hash FROM admin_sessions')==[]


def test_smtp_failure_invalidates_challenge_and_does_not_log_code(security,db,caplog):
    security.create_user('owner@example.test','Owner','a-long-test-password')
    sent=[]
    def fail(address,code):
        sent.append(code)
        raise RuntimeError('SMTP rejected '+code)
    security.mailer=fail
    with pytest.raises(DomainError) as exc:security.begin_login('owner@example.test','a-long-test-password','a')
    assert exc.value.code=='mail_unavailable' and exc.value.status==503
    assert sent[0] not in str(exc.value)+caplog.text
    assert db.one('SELECT consumed FROM auth_challenges')['consumed']==1
    assert db.all('SELECT id_hash FROM admin_sessions')==[]


def test_email_otp_is_consumed_atomically(security,db):
    security.create_user('owner@example.test','Owner','a-long-test-password')
    sent=[];security.mailer=lambda address,code:sent.append(code)
    token,_=security.begin_login('owner@example.test','a-long-test-password','a')
    def finish(_):
        try:security.finish_login(token,sent[0],'a');return True
        except DomainError:return False
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(finish,range(2)))==[False,True]
    assert len(db.all('SELECT id_hash FROM admin_sessions'))==1


def test_reauthentication_also_sends_email(security,db):
    _,sid=email_login(security,db)
    user=security.session_user(sid)
    sent=[];security.mailer=lambda address,code:sent.append(code)
    token,kind=security.begin_reauth(user,'a-long-test-password')
    assert kind=='email' and len(sent)==1
    security.finish_login(token,sent[0],'a')


def test_captcha_is_atomic_and_bound_to_purpose_and_origin(security,db):
    challenge=security.create_captcha('chat-session','http://localhost','127.0.0.1')
    left,right=map(int,challenge['question'].split(' + '));answer=str(left+right)
    assert not security.consume_captcha(challenge['id'],answer,'chat-session','http://other.test','127.0.0.1')
    assert not security.consume_captcha(challenge['id'],answer,'admin-login','http://localhost','127.0.0.1')
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:security.consume_captcha(challenge['id'],answer,'chat-session','http://localhost','127.0.0.1'),range(2)))
    assert sorted(results)==[False,True]
    assert db.one('SELECT id_hash FROM captcha_challenges WHERE id_hash=?',(token_hash(challenge['id']),)) is None


def test_captcha_invalid_answer_is_consumed_and_expiry_enforced(security,db):
    challenge=security.create_captcha('chat-session','http://localhost','127.0.0.1')
    left,right=map(int,challenge['question'].split(' + '));answer=str(left+right)
    assert not security.consume_captcha(challenge['id'],'not a number','chat-session','http://localhost','127.0.0.1')
    assert not security.consume_captcha(challenge['id'],answer,'chat-session','http://localhost','127.0.0.1')
    challenge=security.create_captcha('chat-session','http://localhost','127.0.0.1')
    left,right=map(int,challenge['question'].split(' + '));answer=str(left+right)
    db.execute('UPDATE captcha_challenges SET expires_at=? WHERE id_hash=?',(time.time()-1,token_hash(challenge['id'])))
    assert not security.consume_captcha(challenge['id'],answer,'chat-session','http://localhost','127.0.0.1')
