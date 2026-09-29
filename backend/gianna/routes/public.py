"""Anonymous chat capabilities do not grant administrative privileges."""
import json
import secrets
import time
from flask import Blueprint,jsonify,render_template,request,redirect
from ..db import dumps
from ..errors import DomainError
from ..security import token_hash
from ..services.settings import get_settings
from .common import json_body,services

bp=Blueprint('public',__name__)


def allowed_origin():
    s=services();origin=request.headers.get('Origin') or request.host_url.rstrip('/')
    if origin not in s.cfg.public_origins+(request.host_url.rstrip('/'),):
        raise DomainError('Origen no permitido.',403,'origin_denied')
    return origin


def capability():
    origin=allowed_origin();auth=request.headers.get('Authorization','')
    if not auth.startswith('Bearer ') or len(auth)>160:raise DomainError('Iniciá una conversación.',401,'session_required')
    digest=token_hash(auth[7:]);row=services().db.one('SELECT * FROM chat_sessions WHERE id_hash=?',(digest,))
    if not row or row['expires_at']<time.time() or row['origin']!=origin:raise DomainError('La conversación venció. Iniciá una nueva.',401,'session_expired')
    return row


@bp.get('/')
def home():return redirect('/admin/login')


@bp.get('/chat')
def chat_page():return render_template('chat.html')


@bp.get('/api/config')
def chat_config():
    allowed_origin();s=services();settings=get_settings(s.db,s.cfg)
    return jsonify(name=settings.brand_name,greeting=settings.greeting,notice=settings.knowledge_notice,
        enabled=settings.chat_enabled,available=bool(s.knowledge.active() and s.embeddings.model is not None),
        history_hours=settings.chat_history_hours,test_mode=s.cfg.human_test_mode)


@bp.get('/api/captcha')
def captcha():
    """Public contract: GET with allowed Origin -> {id, question, expires_in}.

    The answer stays server-side. Challenges expire after 600 seconds and are
    consumed once. Clients must request a new one after captcha_invalid.
    """
    origin=allowed_origin();s=services()
    challenge=s.security.create_captcha('chat-session',origin,request.remote_addr or 'unknown')
    return jsonify(challenge)


@bp.post('/api/sessions')
def create_session():
    """POST JSON {captcha_id, captcha_answer} with the same allowed Origin.

    Returns 201 {token, expires_at}, 400 captcha_invalid or 429 rate_limited.
    The anonymous token is never an administrative session or Ollama API key.
    """
    origin=allowed_origin();s=services();settings=get_settings(s.db,s.cfg)
    if not settings.chat_enabled:raise DomainError('El chat está pausado temporalmente.',503,'chat_paused')
    s.security.rate_limit('new-chat:'+str(request.remote_addr),20,900)
    body=json_body()
    if set(body)-{'captcha_id','captcha_answer'}:
        raise DomainError('Solo se admiten captcha_id y captcha_answer.')
    if not s.security.consume_captcha(body.get('captcha_id'),body.get('captcha_answer'),
                                      'chat-session',origin,request.remote_addr or 'unknown'):
        raise DomainError('La verificación es incorrecta, venció o ya fue utilizada. Resolvé una nueva suma.',
                          400,'captcha_invalid')
    raw=secrets.token_urlsafe(40);now=time.time()
    s.db.execute('INSERT INTO chat_sessions(id_hash,created_at,expires_at,origin) VALUES(?,?,?,?)',
        (token_hash(raw),now,now+settings.chat_history_hours*3600,origin))
    return jsonify(token=raw,expires_at=now+settings.chat_history_hours*3600),201


@bp.post('/api/chat')
def chat():
    row=capability();s=services();settings=get_settings(s.db,s.cfg);body=json_body()
    if set(body)-{'message'}:raise DomainError('Solo se admite el campo message.')
    question=body.get('message')
    if not isinstance(question,str) or not question.strip() or len(question)>2500:raise DomainError('Pregunta de entre 1 y 2.500 caracteres.')
    if not settings.chat_enabled:raise DomainError('El chat está pausado temporalmente.',503,'chat_paused')
    s.security.rate_limit('chat-session:'+row['id_hash'],settings.query_per_minute,60)
    s.security.rate_limit('chat-ip:'+str(request.remote_addr),max(settings.query_per_minute*2,12),60)
    s.security.rate_limit('chat-global',settings.global_queries_per_minute,60)
    s.security.rate_limit('chat-budget',settings.daily_query_budget,86400)
    now=time.time()
    with s.db.tx(immediate=True) as db:
        current=db.execute('SELECT * FROM chat_sessions WHERE id_hash=?',(row['id_hash'],)).fetchone()
        if not current or current['expires_at']<now:raise DomainError('La conversación venció.',401,'session_expired')
        if current['busy_until']>now:raise DomainError('Ya hay una respuesta en curso en esta conversación.',409,'conversation_busy')
        db.execute('UPDATE chat_sessions SET busy_until=? WHERE id_hash=?',(now+180,row['id_hash']))
        history=json.loads(s.security.unseal(current['history_encrypted'])) if current['history_encrypted'] else []
    try:
        result=s.rag.answer(question,settings,history=history,session_hash=row['id_hash'])
        updated=(history+[{'role':'user','content':question},{'role':'assistant','content':result['answer'],'mode':result.get('mode','knowledge')}])[-12:]
        s.db.execute('UPDATE chat_sessions SET history_encrypted=? WHERE id_hash=?',
            (s.security.seal(dumps(updated)),row['id_hash']))
        return jsonify(result)
    finally:s.db.execute('UPDATE chat_sessions SET busy_until=0 WHERE id_hash=?',(row['id_hash'],))


@bp.delete('/api/sessions/current')
def forget_session():
    row=capability();s=services()
    with s.db.tx(immediate=True) as db:
        db.execute('DELETE FROM chat_sessions WHERE id_hash=?',(row['id_hash'],))
        # Keep aggregate, non-content measurements but sever the conversation linkage.
        db.execute('UPDATE queries SET session_hash=NULL WHERE session_hash=?',(row['id_hash'],))
    return jsonify(deleted=True)


@bp.post('/api/feedback/<query_id>')
def feedback(query_id):
    row=capability();body=json_body();value=body.get('value')
    if type(value) is not int or value not in (-1,1):raise DomainError('La valoración debe ser 1 o -1.')
    s=services();s.security.rate_limit('feedback:'+row['id_hash'],20,60)
    changed=s.db.execute('UPDATE queries SET feedback=? WHERE id=? AND session_hash=? AND mode=?',(value,query_id,row['id_hash'],'public'))
    if not changed:raise DomainError('Consulta inexistente para esta conversación.',404)
    return jsonify(saved=True)
