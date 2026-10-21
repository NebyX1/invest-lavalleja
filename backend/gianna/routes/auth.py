import secrets
from flask import Blueprint,render_template,request,session,redirect,url_for,g,flash
from .common import services,access
from ..errors import DomainError
from ..security import token_hash

bp=Blueprint('auth',__name__,url_prefix='/admin')


def login_form(email=''):
    challenge=services().security.create_captcha('admin-login',request.host_url.rstrip('/'),request.remote_addr or 'unknown')
    session['login_captcha_id']=challenge['id']
    return render_template('login.html',captcha_question=challenge['question'],email=email)


@bp.route('/login',methods=['GET','POST'])
def login():
    s=services()
    if request.method=='POST':
        email=request.form.get('email','').strip()[:254]
        challenge_id=session.pop('login_captcha_id',None)
        if not s.security.consume_captcha(challenge_id,request.form.get('captcha',''),'admin-login',
                                          request.host_url.rstrip('/'),request.remote_addr or 'unknown'):
            flash('El CAPTCHA es incorrecto o venció. Resolvé una nueva suma.','error')
            return login_form(email)
        try:
            token,kind=s.security.begin_login(email,request.form.get('password',''),request.remote_addr or 'unknown')
        except DomainError as exc:
            if exc.code not in {'invalid_credentials','mail_unavailable'}:raise
            flash(str(exc),'error')
            return login_form(email),(503 if exc.code=='mail_unavailable' else 200)
        previous=session.get('sid')
        if previous:s.db.execute('DELETE FROM admin_sessions WHERE id_hash=?',(token_hash(previous),))
        session.clear();session['pending']=token;session['csrf']=secrets.token_urlsafe(32)
        return redirect(url_for('auth.mfa'))
    if g.get('user'):return redirect(url_for('admin.dashboard'))
    return login_form()


@bp.route('/mfa',methods=['GET','POST'])
def mfa():
    s=services();pending=session.get('pending')
    if not pending:return redirect(url_for('auth.login'))
    try:s.security.challenge_info(pending)
    except DomainError as exc:
        if exc.code!='challenge_expired':raise
        session.pop('pending',None)
        flash('El código venció o agotó sus intentos. Iniciá sesión para recibir uno nuevo.','error')
        return redirect(url_for('auth.login'))
    if request.method=='POST':
        old=session.get('sid')
        try:token,user=s.security.finish_login(pending,request.form.get('code','')[:100],request.remote_addr or 'unknown')
        except DomainError as exc:
            if exc.code!='invalid_otp':raise
            flash('Código incorrecto, usado o vencido. Revisá el código enviado a tu correo.','error')
            return render_template('mfa.html'),401
        if old:s.db.execute('DELETE FROM admin_sessions WHERE id_hash=?',(token_hash(old),))
        session.clear();session['sid']=token;session['csrf']=secrets.token_urlsafe(32);session.permanent=True
        return redirect(url_for('auth.security_page') if user['must_change_password'] else url_for('admin.dashboard'))
    return render_template('mfa.html')


@bp.post('/logout')
@access()
def logout():
    s=services();s.db.execute('DELETE FROM admin_sessions WHERE id_hash=?',(g.user['session_hash'],))
    s.db.audit(g.user['id'],'LOGOUT');session.clear()
    return redirect(url_for('auth.login'))


@bp.route('/security',methods=['GET','POST'])
@access()
def security_page():
    s=services()
    if request.method=='POST':
        action=request.form.get('action')
        if action=='password':
            s.security.rate_limit('password:'+g.user['id'],6,300)
            s.security.change_password(g.user['id'],request.form.get('old_password',''),request.form.get('new_password',''))
            session.clear();return redirect(url_for('auth.login'))
        if action=='revoke':
            s.db.execute('DELETE FROM admin_sessions WHERE user_id=? AND id_hash!=?',(g.user['id'],g.user['session_hash']))
            s.db.audit(g.user['id'],'OTHER_SESSIONS_REVOKED');flash('Las demás sesiones quedaron cerradas.','success')
        else:raise DomainError('Acción inválida.')
    rows=s.db.all('SELECT created_at,touched_at,expires_at,id_hash FROM admin_sessions WHERE user_id=? ORDER BY created_at DESC',(g.user['id'],))
    return render_template('security.html',sessions=rows)


@bp.post('/reauth')
@access()
def reauth():
    token,kind=services().security.begin_reauth(g.user,request.form.get('password',''))
    session['pending']=token
    return redirect(url_for('auth.mfa'))
