"""Existing accounts switch to institutional email 2FA without losing their data."""
import time

import pytest

from gianna.security import token_hash
from gianna.errors import DomainError


@pytest.mark.parametrize('enrolled',[0,1])
def test_legacy_account_migration_preserves_password_permissions_and_email_sessions(security,db,enrolled):
    legacy=security.create_user('legacy@example.test','Existing administrator','a-long-test-password','owner')
    email=security.create_user('email@example.test','Email administrator','another-long-password','editor')
    db.execute("UPDATE users SET mfa_method='totp',mfa_enrolled=?,totp_secret='legacy-encrypted-secret',totp_last_step=123 WHERE id=?",(enrolled,legacy))
    original=db.one('SELECT id,email,name,password_hash,role,active,created_at,must_change_password FROM users WHERE id=?',(legacy,))
    now=time.time()
    for user,sid in ((legacy,'legacy-session'),(email,'email-session')):
        db.execute('INSERT INTO admin_sessions VALUES(?,?,?,?,?,?)',(token_hash(sid),user,now,now,now+3600,now))
    db.execute('INSERT INTO recovery_codes VALUES(?,?)',(legacy,'legacy-recovery-hash'))
    db.execute("INSERT INTO auth_challenges(id,user_id,kind,secret,expires_at) VALUES(?,?,'enroll','legacy-secret',?)",(token_hash('legacy-challenge'),legacy,now+300))
    db.execute('DELETE FROM schema_versions WHERE version=5')

    db.migrate()

    assert db.one('SELECT id,email,name,password_hash,role,active,created_at,must_change_password FROM users WHERE id=?',(legacy,))==original
    assert db.one('SELECT mfa_method,mfa_enrolled,totp_secret,totp_last_step FROM users WHERE id=?',(legacy,))=={
        'mfa_method':'email','mfa_enrolled':1,'totp_secret':None,'totp_last_step':-1}
    assert security.session_user('legacy-session') is None
    assert security.session_user('email-session')['id']==email
    assert db.all('SELECT * FROM recovery_codes')==[]
    assert db.all('SELECT * FROM auth_challenges')==[]
    sent=[];security.mailer=lambda address,code:sent.append((address,code))
    token,kind=security.begin_login('legacy@example.test','a-long-test-password','a')
    assert kind=='email' and sent[0][0]=='legacy@example.test'
    db.migrate()  # A normal subsequent startup must preserve pending email codes.
    security.finish_login(token,sent[0][1],'a')


def test_unmigrated_totp_challenge_cannot_be_used_or_rendered(security,db):
    user=security.create_user('legacy@example.test','Existing administrator','a-long-test-password')
    db.execute("INSERT INTO auth_challenges(id,user_id,kind,secret,expires_at) VALUES(?,?,'enroll','legacy-secret',?)",(token_hash('old'),user,time.time()+300))
    with pytest.raises(DomainError):security.challenge_info('old')
    with pytest.raises(DomainError):security.finish_login('old','123456','a')
    assert db.all('SELECT * FROM admin_sessions')==[]
