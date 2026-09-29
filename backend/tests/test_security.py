import base64
import concurrent.futures
import time
import pytest
from gianna.security import totp,matching_step,token_hash,keyed_hash
from gianna.errors import DomainError

# Published RFC 6238 SHA-1 test vectors (8 digits), not generated from our implementation.
@pytest.mark.parametrize('seconds,expected',[(59,'94287082'),(1111111109,'07081804'),(1111111111,'14050471'),(1234567890,'89005924'),(2000000000,'69279037'),(20000000000,'65353130')])
def test_rfc6238_vectors(seconds,expected):
    secret=base64.b32encode(b'12345678901234567890').decode()
    assert totp(secret,seconds//30,digits=8)==expected


def enroll(security,db):
    id=security.create_user('owner@example.test','Owner','a-long-test-password','owner')
    token,kind=security.begin_login('owner@example.test','a-long-test-password','127.0.0.1');assert kind=='enroll'
    challenge=security.challenge_info(token);secret=security.unseal(challenge['secret'])
    code=totp(secret,int(time.time()//30))
    session,user,recovery=security.finish_login(token,code,'127.0.0.1')
    return id,secret,session,recovery


def test_enrollment_encrypts_secret_and_session(security,db):
    id,secret,session,codes=enroll(security,db)
    row=db.one('SELECT * FROM users WHERE id=?',(id,))
    assert row['totp_secret']!=secret and row['mfa_enrolled']==1
    assert db.one('SELECT id_hash FROM admin_sessions')['id_hash']!=session
    assert len(codes)==10 and len(codes[0])==24
    assert db.one('SELECT code_hash FROM recovery_codes')['code_hash'] not in codes
    assert security.session_user(session)['id']==id


def test_otp_replay_rejected(security,db):
    id,secret,session,codes=enroll(security,db)
    token,_=security.begin_login('owner@example.test','a-long-test-password','127.0.0.1')
    with pytest.raises(DomainError):security.finish_login(token,totp(secret,int(time.time()//30)),'127.0.0.1')


def test_recovery_code_single_use(security,db):
    _,_,_,codes=enroll(security,db)
    token,_=security.begin_login('owner@example.test','a-long-test-password','127.0.0.1')
    security.finish_login(token,codes[0],'127.0.0.1')
    another,_=security.begin_login('owner@example.test','a-long-test-password','127.0.0.1')
    with pytest.raises(DomainError):security.finish_login(another,codes[0],'127.0.0.1')


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
    id,_,sid,_=enroll(security,db)
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
    id,_,sid,_=enroll(security,db)
    security.change_password(id,'a-long-test-password','another-long-test-password')
    assert security.session_user(sid) is None


def test_malformed_codes_and_step_monotonicity():
    secret=base64.b32encode(b'12345678901234567890').decode();now=1234567890;step=now//30
    assert matching_step(secret,totp(secret,step),last_step=step,now=now) is None
    assert matching_step(secret,'１２３４５６',now=now) is None
    assert matching_step(secret,'invalid',now=now) is None


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
