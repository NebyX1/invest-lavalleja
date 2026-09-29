"""Flask composition root. Model loading belongs to the single background worker."""
import datetime
import hmac
import json
import logging
import secrets
import smtplib
import sqlite3
import ssl
import time
from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace
from flask import Flask, g, jsonify, render_template, request, session
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from pydantic import ValidationError
from .config import Config
from .db import Database
from .errors import DomainError
from .security import Security
from .services.knowledge import Knowledge
from .services.runtime import Embeddings, Qdrant, Ollama
from .services.jobs import Jobs
from .services.rag import RAG
from .services.settings import get_settings


def smtp_sender(cfg):
    def send(address, code):
        if not cfg.smtp_host or not cfg.smtp_from:
            raise RuntimeError('SMTP no configurado')
        message=EmailMessage()
        message['Subject']='Tu código de acceso a Gianna'
        message['From']=cfg.smtp_from
        message['To']=address
        message.set_content(f'Tu código de verificación es {code}. Vence en 5 minutos. No lo compartas. Si no iniciaste este acceso, ignorá este mensaje.')
        context=ssl.create_default_context()
        connection=(smtplib.SMTP_SSL(cfg.smtp_host,cfg.smtp_port,timeout=12,context=context)
                    if cfg.smtp_mode=='ssl' else smtplib.SMTP(cfg.smtp_host,cfg.smtp_port,timeout=12))
        with connection as client:
            if cfg.smtp_mode!='ssl':
                client.ehlo();client.starttls(context=context);client.ehlo()
            if cfg.smtp_username:client.login(cfg.smtp_username,cfg.smtp_password)
            client.send_message(message)
    return send


def create_app(overrides=None):
    cfg=Config.from_env(overrides)
    app=Flask(__name__)
    app.config.update(SECRET_KEY=cfg.secret_key,MAX_CONTENT_LENGTH=cfg.max_upload_mb*1024*1024,
        MAX_FORM_MEMORY_SIZE=1024*1024,MAX_FORM_PARTS=100,
        SESSION_COOKIE_NAME='gianna_admin',SESSION_COOKIE_PATH='/admin',SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=cfg.production,SESSION_COOKIE_SAMESITE='Strict',
        PERMANENT_SESSION_LIFETIME=datetime.timedelta(hours=8),TRUSTED_HOSTS=list(cfg.trusted_hosts) or None)
    if cfg.proxy_hops:
        # Only enable behind a trusted proxy which overwrites incoming forwarding headers.
        app.wsgi_app=ProxyFix(app.wsgi_app,x_for=cfg.proxy_hops,x_proto=cfg.proxy_hops,x_host=0,x_port=0,x_prefix=0)
    db=Database(cfg.db_path);db.migrate()
    security=Security(db,cfg,smtp_sender(cfg));knowledge=Knowledge(db,cfg)
    embeddings=Embeddings(cfg);qdrant=Qdrant(cfg);ollama=Ollama(cfg)
    rag=RAG(db,cfg,knowledge,embeddings,qdrant,ollama,security)
    jobs=Jobs(db,cfg,knowledge,embeddings,qdrant,rag)
    app.extensions['gianna']=SimpleNamespace(cfg=cfg,db=db,security=security,knowledge=knowledge,
        embeddings=embeddings,qdrant=qdrant,ollama=ollama,rag=rag,jobs=jobs)

    @app.before_request
    def request_security():
        g.request_id=secrets.token_hex(12);g.user=None
        if request.path.startswith('/admin'):
            sid=session.get('sid')
            if sid:g.user=security.session_user(sid)
            if not session.get('csrf'):session['csrf']=secrets.token_urlsafe(32)
            if request.method not in {'GET','HEAD','OPTIONS'}:
                csrf=request.headers.get('X-CSRF-Token') or request.form.get('csrf','')
                if not isinstance(csrf,str) or not hmac.compare_digest(csrf,session['csrf']):
                    raise DomainError('La sesión del formulario venció. Recargá la página.',403,'csrf_failed')
                origin=request.headers.get('Origin')
                if origin and origin!=request.host_url.rstrip('/'):
                    raise DomainError('Origen del formulario no permitido.',403,'origin_denied')
        if cfg.production and not request.is_secure and request.path!='/health/live':
            # No redirects for unsafe requests, and no reliance on arbitrary X-Forwarded-* headers.
            raise DomainError('Este servicio requiere HTTPS.',400,'https_required')

    @app.after_request
    def response_security(response):
        response.headers['X-Request-ID']=g.get('request_id','')
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=()'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
        if cfg.production and request.is_secure:response.headers['Strict-Transport-Security']='max-age=31536000'
        if request.path.startswith(('/admin','/api')):
            response.headers['Cache-Control']='no-store'
        if request.path.startswith('/api/'):
            origin=request.headers.get('Origin')
            if origin and origin in cfg.public_origins+(request.host_url.rstrip('/'),):
                response.headers['Access-Control-Allow-Origin']=origin
                response.headers.add('Vary','Origin')
                response.headers['Access-Control-Allow-Headers']='Authorization, Content-Type'
                response.headers['Access-Control-Allow-Methods']='POST, GET, DELETE, OPTIONS'
                response.headers['Access-Control-Max-Age']='600'
        return response

    @app.context_processor
    def context():
        return dict(user=g.get('user'),settings=get_settings(db,cfg),csrf_token=lambda:session.get('csrf',''),
                    version='1.0.0-rc1')

    @app.template_filter('when')
    def when(value):
        if not value:return 'Sin fecha'
        from zoneinfo import ZoneInfo
        return datetime.datetime.fromtimestamp(value,ZoneInfo('America/Montevideo')).strftime('%d/%m/%Y %H:%M')

    @app.template_filter('pretty')
    def pretty(value):
        if isinstance(value,str):
            try:value=json.loads(value)
            except ValueError:return value
        return json.dumps(value,ensure_ascii=False,indent=2)

    def render_error(message,status,code):
        if request.path.startswith(('/api/','/admin/api/')):
            response=jsonify(error={'message':message,'code':code,'request_id':g.get('request_id')})
            response.status_code=status
        else:response=app.make_response((render_template('error.html',message=message,status=status),status))
        if status==429:response.headers['Retry-After']='60'
        return response

    @app.errorhandler(DomainError)
    def domain_error(exc):return render_error(str(exc),exc.status,exc.code)

    @app.errorhandler(ValidationError)
    def validation_error(exc):
        # Do not echo submitted values: they can contain secrets or oversized content.
        fields=', '.join('.'.join(str(x) for x in e['loc']) for e in exc.errors()[:8])
        return render_error('Revisá los campos: '+fields,400,'validation_error')

    @app.errorhandler(sqlite3.IntegrityError)
    def constraint_error(exc):return render_error('El identificador o correo ya existe, o la operación contradice una relación vigente.',409,'conflict')

    @app.errorhandler(HTTPException)
    def http_error(exc):return render_error('La solicitud no pudo procesarse.' if exc.code!=413 else 'El archivo excede el tamaño permitido.',exc.code or 500,'http_error')

    @app.errorhandler(Exception)
    def unexpected_error(exc):
        logging.getLogger(__name__).exception('Error no controlado; request_id=%s',g.get('request_id'))
        return render_error('No se pudo completar la operación. El identificador de solicitud permite revisar el registro técnico.',500,'internal_error')

    @app.get('/health/live')
    def live():return jsonify(status='alive')

    @app.get('/health/ready')
    def ready():
        # Readiness of the HTTP/admin service is distinct from readiness of public knowledge.
        db.one('SELECT 1 AS ok')
        return jsonify(status='ready')

    from .routes.auth import bp as auth
    from .routes.admin import bp as admin
    from .routes.public import bp as public
    app.register_blueprint(auth);app.register_blueprint(admin);app.register_blueprint(public)
    from .commands import register_commands
    register_commands(app)
    return app
