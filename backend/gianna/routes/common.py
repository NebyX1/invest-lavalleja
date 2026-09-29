from functools import wraps
import time
from flask import current_app,g,redirect,url_for,request
from ..errors import DomainError


def services():return current_app.extensions['gianna']


def access(*roles,fresh=False):
    def decorate(fn):
        @wraps(fn)
        def guarded(*args,**kwargs):
            if not g.get('user'):
                if request.path.startswith('/admin/api/'):
                    raise DomainError('Iniciá sesión.',401,'login_required')
                return redirect(url_for('auth.login'))
            if roles and g.user['role'] not in roles:
                raise DomainError('Tu rol no permite esta acción.',403,'forbidden')
            if g.user['must_change_password'] and request.endpoint not in {'auth.security_page','auth.logout','auth.reauth'}:
                return redirect(url_for('auth.security_page'))
            if fresh and time.time()-g.user['reauthenticated_at']>300:
                raise DomainError('Para esta acción, confirmá tu identidad desde Seguridad y volvé a intentarlo.',403,'reauth_required')
            return fn(*args,**kwargs)
        return guarded
    return decorate


def json_body():
    if not request.is_json:raise DomainError('Se requiere JSON.',415)
    body=request.get_json(silent=True)
    if not isinstance(body,dict):raise DomainError('El cuerpo debe ser un objeto JSON.')
    return body


def bounded_int(value,default,low,high):
    try:return max(low,min(high,int(value)))
    except (ValueError,TypeError):return default
