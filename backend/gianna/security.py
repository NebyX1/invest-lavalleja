"""Authentication primitives. TOTP follows RFC 6238; replay protection is transactional."""
import base64
import hashlib
import hmac
import json
import re
import secrets
import struct
import time
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from cryptography.fernet import Fernet
from .db import uid
from .errors import DomainError

PASSWORDS=PasswordHasher(time_cost=2,memory_cost=19456,parallelism=1)
DUMMY_HASH=PASSWORDS.hash(secrets.token_urlsafe(32))
CAPTCHA_TTL_SECONDS=600


def token_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def keyed_hash(key, value):
    return hmac.new(key.encode(),value.encode(),hashlib.sha256).hexdigest()


def totp(secret, step, digits=6, digest='sha1'):
    """RFC 4226 HOTP with the time step supplied by the caller (RFC 6238)."""
    key=base64.b32decode(secret.upper() + '='*((-len(secret))%8))
    mac=hmac.new(key,struct.pack('>Q',int(step)),getattr(hashlib,digest)).digest()
    offset=mac[-1]&15
    value=struct.unpack('>I',mac[offset:offset+4])[0]&0x7fffffff
    return str(value%(10**digits)).zfill(digits)


def matching_step(secret, code, last_step=-1, now=None):
    if not isinstance(code,str) or len(code)!=6 or not code.isascii() or not code.isdigit():
        return None
    current=int((time.time() if now is None else now)//30)
    for step in (current,current-1,current+1):
        if step>last_step and hmac.compare_digest(totp(secret,step),code):
            return step
    return None


def validate_password(password):
    if not isinstance(password,str) or len(password)<12 or len(password)>256:
        raise DomainError('Usá una contraseña de entre 12 y 256 caracteres.')


def verify_password(encoded, password):
    try: return PASSWORDS.verify(encoded or DUMMY_HASH,password)
    except (VerificationError,InvalidHashError,TypeError): return False


class Security:
    def __init__(self, db, cfg, mailer=None):
        self.db=db; self.cfg=cfg; self.fernet=Fernet(cfg.encryption_key.encode()); self.mailer=mailer

    def seal(self, text):
        return self.fernet.encrypt(text.encode()).decode()

    def unseal(self, text):
        return self.fernet.decrypt(text.encode()).decode()

    def rate_limit(self, key, limit, seconds, now=None):
        now=time.time() if now is None else now
        bucket=int(now//seconds)
        key=keyed_hash(self.cfg.secret_key,key)+f':{seconds}'
        with self.db.tx(immediate=True) as db:
            db.execute('INSERT INTO rate_limits(key,bucket,count) VALUES(?,?,1) ON CONFLICT(key,bucket) DO UPDATE SET count=count+1',(key,bucket))
            n=db.execute('SELECT count FROM rate_limits WHERE key=? AND bucket=?',(key,bucket)).fetchone()[0]
        if n>limit:
            raise DomainError('Demasiados intentos. Esperá antes de volver a intentar.',429,'rate_limited')

    def create_captcha(self, purpose, origin, ip):
        """Issue a short-lived arithmetic challenge without storing its answer in a cookie."""
        if purpose not in {'admin-login','chat-session'}:
            raise ValueError('Invalid CAPTCHA purpose')
        self.rate_limit('captcha-issue:'+purpose+':'+ip,20,60)
        left=secrets.randbelow(20)+1
        right=secrets.randbelow(20)+1
        challenge_id=secrets.token_urlsafe(32)
        answer_digest=keyed_hash(self.cfg.secret_key,f'captcha:{purpose}:{challenge_id}:{left+right}')
        now=time.time()
        with self.db.tx(immediate=True) as db:
            db.execute('DELETE FROM captcha_challenges WHERE expires_at<=?',(now,))
            db.execute('INSERT INTO captcha_challenges(id_hash,purpose,origin,answer_digest,expires_at) VALUES(?,?,?,?,?)',
                       (token_hash(challenge_id),purpose,origin,answer_digest,now+CAPTCHA_TTL_SECONDS))
        return {'id':challenge_id,'question':f'{left} + {right}','expires_in':CAPTCHA_TTL_SECONDS}

    def consume_captcha(self, challenge_id, answer, purpose, origin, ip):
        """Claim a challenge atomically. A wrong answer consumes it as well."""
        self.rate_limit('captcha-check:'+purpose+':'+ip,10,60)
        if not isinstance(challenge_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',challenge_id):
            return False
        normalized=answer.strip() if isinstance(answer,str) else ''
        valid_format=bool(re.fullmatch(r'[0-9]{1,2}',normalized))
        with self.db.tx(immediate=True) as db:
            row=db.execute('SELECT answer_digest,expires_at FROM captcha_challenges WHERE id_hash=? AND purpose=? AND origin=?',
                           (token_hash(challenge_id),purpose,origin)).fetchone()
            if row is None:
                return False
            db.execute('DELETE FROM captcha_challenges WHERE id_hash=?',(token_hash(challenge_id),))
            if not valid_format or row['expires_at']<=time.time():
                return False
            expected=keyed_hash(self.cfg.secret_key,f'captcha:{purpose}:{challenge_id}:{int(normalized)}')
            return hmac.compare_digest(row['answer_digest'],expected)

    def create_user(self,email,name,password,role='editor',mfa_method='totp',temporary=False):
        email=email.strip().lower()
        if not email or '@' not in email or len(email)>254 or '\n' in email or '\r' in email:
            raise DomainError('Correo inválido.')
        if role not in {'owner','editor','viewer'} or mfa_method not in {'totp','email'}:
            raise DomainError('Rol o método de verificación inválido.')
        if mfa_method=='email' and not self.cfg.smtp_host:
            raise DomainError('Configurá SMTP antes de habilitar doble factor por correo.')
        validate_password(password)
        id=uid()
        self.db.execute('INSERT INTO users(id,email,name,role,password_hash,mfa_method,mfa_enrolled,created_at,must_change_password) VALUES(?,?,?,?,?,?,?,?,?)',
          (id,email,name[:100],role,PASSWORDS.hash(password),mfa_method,int(mfa_method=='email'),time.time(),int(temporary)))
        return id

    def begin_login(self,email,password,ip):
        email=email.strip().lower()[:254]
        self.rate_limit('login-ip:'+ip,10,60)
        self.rate_limit('login-account:'+email,20,3600)
        user=self.db.one('SELECT * FROM users WHERE email=?',(email,))
        valid=verify_password(user['password_hash'] if user else DUMMY_HASH,password[:257])
        if not user or not valid or not user['active']:
            self.db.audit(None,'LOGIN_DENIED',details={'account_hash':keyed_hash(self.cfg.secret_key,email)})
            raise DomainError('Correo o contraseña incorrectos.',401,'invalid_credentials')
        if PASSWORDS.check_needs_rehash(user['password_hash']):
            self.db.execute('UPDATE users SET password_hash=? WHERE id=?',(PASSWORDS.hash(password),user['id']))
        return self._challenge(user)

    def _challenge(self,user,reauth=False):
        id=secrets.token_urlsafe(32)
        kind='totp' if user['mfa_method']=='totp' else 'email'
        secret=None; code_hash=None; raw_code=None
        if kind=='totp' and not user['mfa_enrolled']:
            kind='enroll'; secret=self.seal(base64.b32encode(secrets.token_bytes(20)).decode().rstrip('='))
        if kind=='email':
            raw_code=''.join(secrets.choice('0123456789') for _ in range(6))
            code_hash=keyed_hash(self.cfg.secret_key,id+':'+raw_code)
        with self.db.tx(immediate=True) as db:
            db.execute('UPDATE auth_challenges SET consumed=1 WHERE user_id=?',(user['id'],))
            db.execute('INSERT INTO auth_challenges(id,user_id,kind,code_hash,secret,expires_at) VALUES(?,?,?,?,?,?)',
                        (token_hash(id),user['id'],kind,code_hash,secret,time.time()+300))
        if raw_code:
            try:
                if not self.mailer: raise RuntimeError('SMTP no configurado')
                self.mailer(user['email'],raw_code)
            except Exception:
                self.db.execute('UPDATE auth_challenges SET consumed=1 WHERE id=?',(token_hash(id),))
                raise DomainError('No se pudo enviar el código. Revisá la configuración de correo.',503,'mail_unavailable')
        return id,kind

    def challenge_info(self, token):
        row=self.db.one('SELECT c.*,u.email FROM auth_challenges c JOIN users u ON u.id=c.user_id WHERE c.id=?',(token_hash(token),))
        if not row or row['consumed'] or row['expires_at']<time.time() or row['attempts']>=6:
            raise DomainError('La verificación venció. Iniciá sesión nuevamente.',401,'challenge_expired')
        return row

    def finish_login(self, token, code, ip):
        self.rate_limit('mfa-ip:'+ip,15,300)
        now=time.time(); result=None; recovery=[]
        with self.db.tx(immediate=True) as db:
            ch=db.execute('SELECT * FROM auth_challenges WHERE id=?',(token_hash(token),)).fetchone()
            if ch and not ch['consumed'] and ch['expires_at']>=now and ch['attempts']<6:
                db.execute('UPDATE auth_challenges SET attempts=attempts+1 WHERE id=?',(ch['id'],))
                user=db.execute('SELECT * FROM users WHERE id=?',(ch['user_id'],)).fetchone()
                valid=False; step=None
                if user and user['active']:
                    if ch['kind']=='email':
                        valid=hmac.compare_digest(ch['code_hash'] or '',keyed_hash(self.cfg.secret_key,token+':'+code.strip()))
                    else:
                        encrypted=ch['secret'] if ch['kind']=='enroll' else user['totp_secret']
                        if encrypted:
                            step=matching_step(self.unseal(encrypted),code.strip(),user['totp_last_step'])
                            valid=step is not None
                        if not valid and ch['kind']=='totp':
                            digest=keyed_hash(self.cfg.secret_key,'recovery:'+code.strip().upper())
                            valid=db.execute('DELETE FROM recovery_codes WHERE user_id=? AND code_hash=?',(user['id'],digest)).rowcount==1
                if valid:
                    db.execute('UPDATE auth_challenges SET consumed=1 WHERE user_id=?',(user['id'],))
                    if ch['kind']=='enroll':
                        db.execute('UPDATE users SET totp_secret=?,mfa_enrolled=1,totp_last_step=? WHERE id=?',(ch['secret'],step,user['id']))
                        recovery=[secrets.token_hex(12).upper() for _ in range(10)]
                        for item in recovery:
                            db.execute('INSERT INTO recovery_codes VALUES(?,?)',(user['id'],keyed_hash(self.cfg.secret_key,'recovery:'+item)))
                    elif step is not None:
                        db.execute('UPDATE users SET totp_last_step=? WHERE id=?',(step,user['id']))
                    session_token=secrets.token_urlsafe(40)
                    db.execute('INSERT INTO admin_sessions VALUES(?,?,?,?,?,?)',(token_hash(session_token),user['id'],now,now,now+28800,now))
                    db.execute('UPDATE users SET last_login=? WHERE id=?',(now,user['id']))
                    result=(session_token,dict(user),recovery)
        if result is None:
            raise DomainError('Código incorrecto, usado o vencido.',401,'invalid_otp')
        self.db.audit(result[1]['id'],'LOGIN_SUCCESS')
        return result

    def session_user(self,token):
        now=time.time()
        row=self.db.one('SELECT u.*,s.id_hash AS session_hash,s.reauthenticated_at,s.expires_at,s.touched_at FROM admin_sessions s JOIN users u ON u.id=s.user_id WHERE s.id_hash=?',(token_hash(token),))
        if not row or not row['active'] or not row['mfa_enrolled'] or row['expires_at']<now or row['touched_at']<now-1800:
            return None
        if row['touched_at']<now-60:
            self.db.execute('UPDATE admin_sessions SET touched_at=? WHERE id_hash=?',(now,row['session_hash']))
        return row

    def begin_reauth(self,user,password):
        self.rate_limit('reauth:'+user['id'],10,300)
        if not verify_password(user['password_hash'],password):
            raise DomainError('Contraseña incorrecta.',401,'invalid_credentials')
        return self._challenge(user,True)

    def change_password(self,user_id,old,new):
        row=self.db.one('SELECT * FROM users WHERE id=?',(user_id,))
        if not row or not verify_password(row['password_hash'],old):
            raise DomainError('Contraseña actual incorrecta.',401)
        validate_password(new)
        with self.db.tx(immediate=True) as db:
            db.execute('UPDATE users SET password_hash=?,must_change_password=0 WHERE id=?',(PASSWORDS.hash(new),user_id))
            db.execute('DELETE FROM admin_sessions WHERE user_id=?',(user_id,))
        self.db.audit(user_id,'PASSWORD_CHANGED')
