"""Administrative screens. All mutations require role checks and CSRF protection."""
import csv
import io
import json
import secrets
import time
from pathlib import Path
from flask import Blueprint,Response,flash,g,jsonify,redirect,render_template,request,send_file,url_for
from ..corpus import Record,Source,export_jsonl
from ..db import dumps,uid
from ..errors import DomainError
from ..security import PASSWORDS
from ..services.analytics import summary
from ..services.settings import Settings,get_settings,save_settings
from .common import access,bounded_int,json_body,services

bp=Blueprint('admin',__name__,url_prefix='/admin')


def base_record(row):
    return {**row,'record':json.loads(row['content_json'])}


@bp.get('/')
@access()
def index():return redirect(url_for('admin.dashboard'))


@bp.get('/dashboard')
@access()
def dashboard():
    s=services();active=s.knowledge.active();stats=summary(s.db,7)
    counts={name:s.db.one(f'SELECT COUNT(*) n FROM {name}')['n'] for name in ('bases','records','chunks')}
    jobs=s.db.all('SELECT id,kind,status,progress,total,message,error,created_at FROM jobs ORDER BY created_at DESC LIMIT 5')
    return render_template('dashboard.html',active=active,stats=stats,counts=counts,jobs=jobs,
        engine_ready=s.embeddings.model is not None,cloud_ready=bool(s.cfg.ollama_api_key))


@bp.get('/bases')
@access()
def bases():
    s=services();rows=s.db.all('SELECT b.*,(SELECT COUNT(*) FROM records r WHERE r.base_id=b.id) AS records_count FROM bases b ORDER BY b.created_at DESC')
    return render_template('bases.html',bases=rows,active=s.knowledge.active(),max_mb=s.cfg.max_upload_mb)


@bp.post('/bases/import')
@access('owner','editor')
def import_base():
    s=services();s.security.rate_limit('upload:'+g.user['id'],12,3600)
    upload=request.files.get('file')
    if not upload or not upload.filename:raise DomainError('Seleccioná un archivo.')
    suffix=Path(upload.filename).suffix.lower()
    if suffix not in {'.json','.jsonl','.docx','.md','.txt'}:raise DomainError('Formatos admitidos: .json, .jsonl, .docx, .md y .txt.')
    if s.db.one("SELECT COUNT(*) n FROM jobs WHERE status IN ('queued','running')")['n']>=20:raise DomainError('La cola tiene demasiados trabajos pendientes.',429)
    path=s.cfg.data_dir/'uploads'/(uid()+suffix)
    try:
        upload.save(path);path.chmod(0o600)
        if not path.stat().st_size:raise DomainError('El archivo está vacío.')
        job=s.jobs.enqueue('import',{'path':str(path),'filename':Path(upload.filename.replace('\\','/')).name[:250],
            'name':request.form.get('name','').strip()[:150],'audience':'internal','actor':g.user['id']})
    except Exception:
        path.unlink(missing_ok=True);raise
    s.db.audit(g.user['id'],'IMPORT_QUEUED',job,{'format':suffix})
    flash('Archivo recibido. Se convertirá en borrador, sin publicarlo.','success')
    return redirect(url_for('admin.job_detail',job_id=job))


@bp.get('/bases/<base_id>')
@access()
def base_detail(base_id):
    s=services();base=s.knowledge.require_base(base_id);page=bounded_int(request.args.get('page'),1,1,10000)
    topic=request.args.get('topic','')[:160];audience=request.args.get('audience','');review=request.args.get('review','');q=request.args.get('q','').strip()[:200]
    where='base_id=?';args=[base_id]
    if topic:where+=' AND topic=?';args.append(topic)
    if audience in {'public','internal'}:where+=' AND audience=?';args.append(audience)
    if review in {'pending','approved'}:where+=' AND approved=?';args.append(int(review=='approved'))
    if q:where+=' AND (title LIKE ? OR content_json LIKE ?)';args.extend(['%'+q+'%','%'+q+'%'])
    count=s.db.one('SELECT COUNT(*) n FROM records WHERE '+where,args)['n']
    rows=s.db.all('SELECT * FROM records WHERE '+where+' ORDER BY id LIMIT 30 OFFSET ?',args+[(page-1)*30])
    topics=s.db.all('SELECT topic,COUNT(*) n FROM records WHERE base_id=? GROUP BY topic ORDER BY topic',(base_id,))
    counts=s.db.one("SELECT COUNT(*) total,SUM(audience='public') public,SUM(audience='internal') internal,SUM(approved=0 AND audience='public' AND enabled=1) pending FROM records WHERE base_id=?",(base_id,))
    versions=s.db.all('SELECT * FROM versions WHERE base_id=? ORDER BY created_at DESC',(base_id,))
    sources=[json.loads(r['content_json']) for r in s.db.all('SELECT * FROM sources WHERE base_id=? ORDER BY source_key',(base_id,))]
    return render_template('base_detail.html',base=base,records=rows,topics=topics,counts=counts,versions=versions,sources=sources,
        active=s.knowledge.active(),page=page,pages=max(1,(count+29)//30),count=count,filters=dict(topic=topic,audience=audience,review=review,q=q),report=json.loads(base['report_json']))


@bp.post('/bases/<base_id>/approve')
@access('owner','editor')
def approve(base_id):
    if request.form.get('review_confirm')!='yes':raise DomainError('Confirmá que revisaste el contenido público y sus condiciones.')
    selected=request.form.getlist('record_ids')
    try:ids=[int(x) for x in selected] if selected else None
    except ValueError:raise DomainError('Selección inválida.')
    n=services().knowledge.approve_public(base_id,g.user['id'],ids)
    flash(f'{n} registros públicos aprobados. Aprobar no publica ni verifica automáticamente sus afirmaciones.','success')
    return redirect(url_for('admin.base_detail',base_id=base_id))


@bp.post('/bases/<base_id>/build')
@access('owner','editor')
def build(base_id):
    s=services();job,version=s.knowledge.enqueue_build(base_id,get_settings(s.db,s.cfg),g.user['id']);s.jobs.wake.set()
    return redirect(url_for('admin.job_detail',job_id=job))


@bp.post('/bases/<base_id>/delete')
@access('owner',fresh=True)
def delete_base(base_id):
    s=services();base=s.knowledge.require_base(base_id)
    if request.form.get('confirm_name')!=base['name']:raise DomainError('Escribí exactamente el nombre de la base para eliminarla.')
    job=s.knowledge.enqueue_delete(base_id,g.user['id']);s.jobs.wake.set()
    return redirect(url_for('admin.job_detail',job_id=job))


@bp.get('/bases/<base_id>/export')
@access()
def export_base(base_id):
    s=services();corpus=s.knowledge.export(base_id)
    content=export_jsonl(corpus) if request.args.get('format')=='jsonl' else corpus.model_dump_json(indent=2)
    suffix='jsonl' if request.args.get('format')=='jsonl' else 'gianna.json'
    s.db.audit(g.user['id'],'CORPUS_EXPORTED',base_id,{'includes_internal':True})
    return Response(content,mimetype='application/json',headers={'Content-Disposition':f'attachment; filename="gianna-{base_id[:12]}.{suffix}"'})


@bp.route('/bases/<base_id>/records/new',methods=['GET','POST'])
@bp.route('/bases/<base_id>/records/<int:row_id>',methods=['GET','POST'])
@access('owner','editor')
def record_edit(base_id,row_id=None):
    s=services();base=s.knowledge.require_base(base_id)
    row=s.db.one('SELECT * FROM records WHERE id=? AND base_id=?',(row_id,base_id)) if row_id else None
    if row_id and not row:raise DomainError('Registro inexistente.',404)
    initial=json.loads(row['content_json']) if row else Record(id='registro-'+uid()[:12],title='Nuevo registro',text='Contenido pendiente de edición.',audience='internal').model_dump()
    if request.method=='POST':
        data={**initial}
        for field in ('id','title','topic','audience','evidence_type','section','text','period','source_locator'):
            data[field]=request.form.get(field,data.get(field,''))
        data['enabled']=request.form.get('enabled')=='yes'
        data['cutoff_date']=request.form.get('cutoff_date','').strip() or None
        data['conditions']=[x.strip() for x in request.form.get('conditions','').split('\n---\n') if x.strip()]
        data['source_refs']=[x.strip() for x in request.form.get('source_refs','').split(',') if x.strip()]
        data['zones']=[x.strip() for x in request.form.get('zones','').split(',') if x.strip()]
        s.knowledge.save_record(base_id,data,g.user['id'],row_id)
        flash('Registro guardado como pendiente de revisión. La versión pública no cambió.','success')
        return redirect(url_for('admin.base_detail',base_id=base_id))
    sources=s.db.all('SELECT source_key FROM sources WHERE base_id=? ORDER BY source_key',(base_id,))
    return render_template('record_edit.html',base=base,record=initial,row=row,sources=sources)


@bp.post('/bases/<base_id>/records/<int:row_id>/delete')
@access('owner','editor')
def delete_record(base_id,row_id):
    if request.form.get('confirm')!='yes':raise DomainError('Confirmá la eliminación del registro del borrador.')
    services().knowledge.delete_record(base_id,row_id,g.user['id'])
    flash('Registro eliminado del borrador. Las versiones previas permanecen intactas.','success')
    return redirect(url_for('admin.base_detail',base_id=base_id))


@bp.route('/bases/<base_id>/sources',methods=['GET','POST'])
@access('owner','editor')
def source_edit(base_id):
    s=services();base=s.knowledge.require_base(base_id);key=request.args.get('id','')
    row=s.db.one('SELECT content_json FROM sources WHERE base_id=? AND source_key=?',(base_id,key)) if key else None
    data=json.loads(row['content_json']) if row else Source(id='fuente-'+uid()[:8],title='Nueva fuente').model_dump()
    if request.method=='POST':
        for field in ('id','title','description','url','locator','verification'):data[field]=request.form.get(field,'').strip()
        data['accessed_at']=request.form.get('accessed_at','').strip() or None
        s.knowledge.save_source(base_id,data,g.user['id'])
        flash('Fuente guardada. La base debe revisarse nuevamente antes de otra indexación.','success')
        return redirect(url_for('admin.base_detail',base_id=base_id))
    return render_template('source_edit.html',base=base,source=data)


@bp.get('/versions/<version_id>')
@access()
def version_detail(version_id):
    s=services();v=s.db.one('SELECT v.*,b.name FROM versions v JOIN bases b ON b.id=v.base_id WHERE v.id=?',(version_id,))
    if not v:raise DomainError('Versión inexistente.',404)
    page=bounded_int(request.args.get('page'),1,1,10000);topic=request.args.get('topic','')[:160];q=request.args.get('q','')[:200]
    where='version_id=?';args=[version_id]
    if topic:where+=' AND topic=?';args.append(topic)
    if q:where+=' AND (title LIKE ? OR text LIKE ?)';args.extend(['%'+q+'%']*2)
    count=s.db.one('SELECT COUNT(*) n FROM chunks WHERE '+where,args)['n']
    rows=s.db.all('SELECT * FROM chunks WHERE '+where+' ORDER BY record_key,position LIMIT 20 OFFSET ?',args+[(page-1)*20])
    topics=s.db.all('SELECT topic,COUNT(*) n FROM chunks WHERE version_id=? GROUP BY topic ORDER BY n DESC',(version_id,))
    return render_template('version_detail.html',v=v,profile=json.loads(v['profile_json']),report=json.loads(v['report_json']),chunks=rows,
        topics=topics,page=page,pages=max(1,(count+19)//20),q=q,topic=topic,count=count,active=s.knowledge.active())


@bp.post('/versions/<version_id>/publish')
@access('owner',fresh=True)
def publish(version_id):
    s=services()
    if request.form.get('confirm_tested')!='yes':raise DomainError('Confirmá que revisaste y probaste esta versión en el laboratorio.')
    v=s.db.one('SELECT * FROM versions WHERE id=?',(version_id,))
    if not v or v['status']!='ready':raise DomainError('La versión no está lista.',409)
    if s.embeddings.model is None:raise DomainError('Prepará el motor antes de publicar.',409)
    if json.loads(v['profile_json']).get('fingerprint')!=s.embeddings.profile['fingerprint']:raise DomainError('La versión pertenece a otro perfil de embeddings.',409)
    if s.qdrant.count(v['collection_name'])!=v['chunk_count']:raise DomainError('La cantidad de puntos no coincide. No se puede publicar.',409)
    s.knowledge.activate(version_id,g.user['id'],request.form.get('rollback')=='yes')
    flash('Versión publicada. Las nuevas consultas usarán esta base.','success')
    return redirect(url_for('admin.version_detail',version_id=version_id))


@bp.post('/unpublish')
@access('owner',fresh=True)
def unpublish():
    if request.form.get('confirm')!='yes':raise DomainError('Confirmá la despublicación.')
    services().knowledge.unpublish(g.user['id']);flash('El chat quedó sin base publicada.','success')
    return redirect(url_for('admin.dashboard'))


@bp.get('/api/versions/<version_id>/points')
@access()
def points(version_id):
    rows=services().db.all('SELECT id,title,topic,record_key,token_count,projection_x AS x,projection_y AS y FROM chunks WHERE version_id=? AND projection_x IS NOT NULL ORDER BY id LIMIT 1200',(version_id,))
    return jsonify(points=rows,method='PCA',warning='Aproximación visual, no medida de exactitud; hasta 1.200 puntos.')


@bp.get('/jobs')
@access()
def jobs():
    rows=services().db.all('SELECT id,kind,status,progress,total,message,error,created_at FROM jobs ORDER BY created_at DESC LIMIT 100')
    return render_template('jobs.html',jobs=rows)


@bp.get('/jobs/<job_id>')
@access()
def job_detail(job_id):
    row=services().db.one('SELECT * FROM jobs WHERE id=?',(job_id,))
    if not row:raise DomainError('Trabajo inexistente.',404)
    return render_template('job_detail.html',job=row)


@bp.get('/api/jobs/<job_id>')
@access()
def job_status(job_id):
    row=services().db.one('SELECT id,kind,status,base_id,version_id,progress,total,message,error,created_at,finished_at FROM jobs WHERE id=?',(job_id,))
    if not row:raise DomainError('Trabajo inexistente.',404)
    return jsonify(row)


@bp.post('/jobs/<job_id>/cancel')
@access('owner','editor')
def cancel_job(job_id):
    s=services();row=s.db.one('SELECT * FROM jobs WHERE id=?',(job_id,))
    if not row or row['status'] not in {'queued','running'}:raise DomainError('Este trabajo no admite cancelación.',409)
    if row['kind']=='delete':raise DomainError('La eliminación no se cancela a mitad de camino. Si falla puede reintentarse.',409)
    s.db.execute('UPDATE jobs SET cancel_requested=1 WHERE id=?',(job_id,));s.db.audit(g.user['id'],'JOB_CANCEL_REQUESTED',job_id)
    flash('Cancelación solicitada. Se aplicará en el siguiente límite seguro del trabajo.','success')
    return redirect(url_for('admin.job_detail',job_id=job_id))


@bp.post('/jobs/<job_id>/retry')
@access('owner','editor')
def retry_job(job_id):
    s=services()
    with s.db.tx(immediate=True) as db:
        row=db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
        if not row or row['status'] not in {'failed','cancelled'}:raise DomainError('Este trabajo no admite reintento.',409)
        if row['kind']=='delete' and g.user['role']!='owner':raise DomainError('Solo un administrador propietario puede eliminar bases.',403)
        if row['base_id'] and db.execute("SELECT 1 FROM jobs WHERE base_id=? AND status IN ('queued','running')",(row['base_id'],)).fetchone():raise DomainError('Ya existe un trabajo pendiente para esta base.',409)
        db.execute("UPDATE jobs SET status='queued',cancel_requested=0,lease_until=NULL,owner_token=NULL,error=NULL,finished_at=NULL,message='Reintento solicitado' WHERE id=?",(job_id,))
    s.jobs.wake.set();s.db.audit(g.user['id'],'JOB_RETRY',job_id)
    return redirect(url_for('admin.job_detail',job_id=job_id))


@bp.route('/lab',methods=['GET','POST'])
@access()
def lab():
    s=services();result=None;question='';selected=request.values.get('version_id','')
    if request.method=='POST':
        s.security.rate_limit('lab:'+g.user['id'],15,60)
        question=request.form.get('question','').strip()
        if not question or len(question)>2500:raise DomainError('Pregunta de hasta 2.500 caracteres.')
        setting=get_settings(s.db,s.cfg)
        if request.form.get('mode')=='answer':
            result={'answer':s.rag.answer(question,setting,version_id=selected or None,preview=True)}
        else:
            hits,ms=s.rag.retrieve(question,setting,selected or None)
            result={'hits':hits,'ms':round(ms,2)}
    versions=s.db.all("SELECT v.id,v.revision,b.name FROM versions v JOIN bases b ON b.id=v.base_id WHERE v.status='ready' ORDER BY v.created_at DESC")
    return render_template('lab.html',result=result,question=question,versions=versions,selected=selected)


@bp.post('/versions/<version_id>/evaluate')
@access('owner','editor')
def evaluate(version_id):
    s=services();raw=request.form.get('tests','')
    try:tests=json.loads(raw)
    except ValueError:raise DomainError('El archivo de preguntas debe contener un array JSON válido.')
    if not isinstance(tests,list) or not 1<=len(tests)<=200:raise DomainError('Ingresá entre 1 y 200 preguntas.')
    for t in tests:
        if not isinstance(t,dict) or not isinstance(t.get('question'),str) or not 1<=len(t['question'])<=2500:raise DomainError('Cada prueba debe incluir una pregunta válida.')
        ids=t.get('expected_any_record_ids',[])
        if not isinstance(ids,list) or len(ids)>50 or any(not isinstance(i,str) or len(i)>140 for i in ids):raise DomainError('Referencias de prueba inválidas.')
    v=s.db.one('SELECT * FROM versions WHERE id=?',(version_id,))
    if not v or v['status']!='ready':raise DomainError('La versión no está lista.',409)
    job=s.jobs.enqueue('evaluation',{'tests':tests},base_id=v['base_id'],version_id=version_id)
    s.db.audit(g.user['id'],'RETRIEVAL_EVALUATION_QUEUED',version_id)
    return redirect(url_for('admin.job_detail',job_id=job))


@bp.route('/settings',methods=['GET','POST'])
@access('owner')
def settings_page():
    s=services();settings=get_settings(s.db,s.cfg)
    if request.method=='POST':
        values=settings.model_dump()
        for field in Settings.model_fields:
            if field=='chat_enabled':values[field]=request.form.get(field)=='yes'
            elif field in request.form:values[field]=request.form[field]
        save_settings(s.db,s.cfg,values,g.user['id']);flash('Ajustes guardados. Los cambios de fragmentación se aplican a la próxima versión.','success')
        return redirect(url_for('admin.settings_page'))
    return render_template('settings.html',cfg=s.cfg,values=settings.model_dump())


@bp.get('/api/models')
@access('owner')
def models():
    s=services();s.security.rate_limit('models:'+g.user['id'],6,60)
    return jsonify(models=s.ollama.models())


@bp.get('/api/diagnostics')
@access()
def diagnostics():
    import psutil
    s=services();s.security.rate_limit('diagnostics:'+g.user['id'],10,60)
    qdrant_ok=False
    try:s.qdrant.health();qdrant_ok=True
    except DomainError:pass
    disk=psutil.disk_usage(str(s.cfg.data_dir))
    return jsonify(model_loaded=s.embeddings.model is not None,profile=s.embeddings.profile,
        qdrant_ok=qdrant_ok,ollama_token_configured=bool(s.cfg.ollama_api_key),smtp_configured=bool(s.cfg.smtp_host),
        worker_alive=bool(s.jobs.thread and s.jobs.thread.is_alive()),
        process_rss_mib=round(psutil.Process().memory_info().rss/1024**2,1),data_disk_free_mib=round(disk.free/1024**2,1),
        sqlite_mib=round(s.cfg.db_path.stat().st_size/1024**2,2),note='RAM del proceso, no de todo el VPS. No se realizó una generación de pago.')


@bp.post('/warmup')
@access('owner','editor')
def warmup():
    s=services()
    existing=s.db.one("SELECT id FROM jobs WHERE kind='warmup' AND status IN ('queued','running') LIMIT 1")
    job=existing['id'] if existing else s.jobs.enqueue('warmup')
    return redirect(url_for('admin.job_detail',job_id=job))


@bp.get('/analytics')
@access()
def analytics():
    days=bounded_int(request.args.get('days'),30,1,180)
    return render_template('analytics.html',stats=summary(services().db,days))


@bp.get('/analytics/export')
@access()
def analytics_export():
    s=services();days=bounded_int(request.args.get('days'),30,1,180)
    rows=s.db.all("SELECT at,status,topic,retrieval_ms,generation_ms,total_ms,prompt_tokens,output_tokens,feedback FROM queries WHERE mode='public' AND at>=? ORDER BY at",(time.time()-days*86400,))
    stream=io.StringIO();writer=csv.writer(stream);columns=['at','status','topic','retrieval_ms','generation_ms','total_ms','prompt_tokens','output_tokens','feedback'];writer.writerow(columns)
    def safe(value):
        text='' if value is None else str(value)
        return "'"+text if text[:1] in ('=','+','-','@','\t','\r') else text
    for row in rows:writer.writerow([safe(row[k]) for k in columns])
    s.db.audit(g.user['id'],'ANALYTICS_EXPORTED',details={'rows':len(rows)})
    return Response('\ufeff'+stream.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename="gianna-analitica.csv"'})


@bp.get('/audit')
@access('owner')
def audit():
    rows=services().db.all('SELECT a.*,u.email FROM audit a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 300')
    return render_template('audit.html',rows=rows)


@bp.route('/users',methods=['GET','POST'])
@access('owner',fresh=True)
def users():
    s=services();temporary=None
    if request.method=='POST':
        temporary=secrets.token_urlsafe(18)
        id=s.security.create_user(request.form.get('email',''),request.form.get('name',''),temporary,
            request.form.get('role','editor'),request.form.get('mfa_method','totp'),temporary=True)
        s.db.audit(g.user['id'],'USER_CREATED',id)
    rows=s.db.all('SELECT id,email,name,role,active,mfa_method,mfa_enrolled,created_at,last_login FROM users ORDER BY created_at')
    return render_template('users.html',rows=rows,temporary=temporary,smtp=bool(s.cfg.smtp_host))


@bp.post('/users/<user_id>/update')
@access('owner',fresh=True)
def update_user(user_id):
    s=services();role=request.form.get('role');active=int(request.form.get('active')=='yes')
    if role not in {'owner','editor','viewer'}:raise DomainError('Rol inválido.')
    with s.db.tx(immediate=True) as db:
        old=db.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
        if not old:raise DomainError('Usuario inexistente.',404)
        owners=db.execute("SELECT COUNT(*) FROM users WHERE active=1 AND role='owner'").fetchone()[0]
        if old['active'] and old['role']=='owner' and owners<=1 and (not active or role!='owner'):
            raise DomainError('Debe quedar al menos un propietario activo.',409)
        db.execute('UPDATE users SET role=?,active=? WHERE id=?',(role,active,user_id))
        db.execute('DELETE FROM admin_sessions WHERE user_id=?',(user_id,))
        db.execute('UPDATE auth_challenges SET consumed=1 WHERE user_id=?',(user_id,))
    s.db.audit(g.user['id'],'USER_ACCESS_CHANGED',user_id,{'role':role,'active':active})
    flash('Permisos actualizados y sesiones revocadas.','success')
    return redirect(url_for('admin.users'))
