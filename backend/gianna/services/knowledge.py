from pathlib import Path
import json
import time
import hashlib
from ..db import uid,dumps
from ..corpus import Corpus,Record,Source,DocumentInfo
from ..errors import DomainError


class Knowledge:
    def __init__(self,db,cfg):self.db=db;self.cfg=cfg

    def require_base(self,id):
        base=self.db.one('SELECT * FROM bases WHERE id=?',(id,))
        if not base: raise DomainError('La base no existe.',404)
        return base

    def import_corpus(self,corpus,name,actor,filename='',import_id=None):
        if len(corpus.records)>self.cfg.max_records: raise DomainError('Demasiados registros para este despliegue.')
        id=import_id or uid(); now=time.time()
        if import_id and self.db.one("SELECT id FROM bases WHERE id=?",(import_id,)):return import_id
        with self.db.tx(immediate=True) as db:
            db.execute('INSERT INTO bases(id,name,created_at,updated_at,source_filename,source_sha256,document_json,report_json) VALUES(?,?,?,?,?,?,?,?)',
                (id,(name or corpus.document.title)[:150],now,now,filename,corpus.document.sha256,dumps(corpus.document.model_dump()),dumps(corpus.conversion_report)))
            for source in corpus.sources:
                db.execute('INSERT INTO sources VALUES(?,?,?)',(id,source.id,dumps(source.model_dump())))
            for r in corpus.records:
                db.execute('INSERT INTO records(base_id,record_key,title,topic,audience,evidence_type,enabled,content_json,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                    (id,r.id,r.title,r.topic,r.audience,r.evidence_type,int(r.enabled),dumps(r.model_dump()),now))
        self.db.audit(actor,'CORPUS_IMPORTED',id,{'records':len(corpus.records),'sources':len(corpus.sources)})
        return id

    def export(self,id):
        base=self.require_base(id)
        return Corpus(document=DocumentInfo.model_validate_json(base['document_json']),
            records=[Record.model_validate_json(r['content_json']) for r in self.db.all('SELECT * FROM records WHERE base_id=? ORDER BY id',(id,))],
            sources=[Source.model_validate_json(s['content_json']) for s in self.db.all('SELECT * FROM sources WHERE base_id=? ORDER BY source_key',(id,))],
            conversion_report=json.loads(base['report_json']))

    def save_record(self,base_id,data,actor,record_row_id=None):
        self.require_base(base_id); record=Record.model_validate(data)
        sources={s['source_key'] for s in self.db.all('SELECT source_key FROM sources WHERE base_id=?',(base_id,))}
        if set(record.source_refs)-sources: raise DomainError('Hay referencias sin fuente en esta base.')
        with self.db.tx(immediate=True) as db:
            if record_row_id:
                old=db.execute('SELECT * FROM records WHERE id=? AND base_id=?',(record_row_id,base_id)).fetchone()
                if not old:raise DomainError('Registro inexistente.',404)
                if record.id!=old['record_key']:raise DomainError('El identificador de un registro existente no puede cambiarse.')
                db.execute('UPDATE records SET title=?,topic=?,audience=?,evidence_type=?,enabled=?,approved=0,content_json=?,updated_at=?,reviewed_by=NULL WHERE id=?',
                    (record.title,record.topic,record.audience,record.evidence_type,int(record.enabled),dumps(record.model_dump()),time.time(),record_row_id))
            else:
                n=db.execute('SELECT COUNT(*) FROM records WHERE base_id=?',(base_id,)).fetchone()[0]
                if n>=self.cfg.max_records:raise DomainError('Se alcanzó el máximo de registros.')
                db.execute('INSERT INTO records(base_id,record_key,title,topic,audience,evidence_type,enabled,content_json,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                    (base_id,record.id,record.title,record.topic,record.audience,record.evidence_type,int(record.enabled),dumps(record.model_dump()),time.time()))
            self._touch(db,base_id)
        self.db.audit(actor,'RECORD_SAVED',base_id,{'record_id':record.id})
        return record

    @staticmethod
    def _touch(db,base_id):
        row=db.execute('SELECT status FROM bases WHERE id=?',(base_id,)).fetchone()
        if not row or row['status']=='deleting':raise DomainError('La base no admite cambios mientras se elimina.',409)
        db.execute("UPDATE bases SET revision=revision+1,status='draft',updated_at=? WHERE id=?",(time.time(),base_id))

    def delete_record(self,base_id,row_id,actor):
        with self.db.tx(immediate=True) as db:
            count=db.execute('DELETE FROM records WHERE id=? AND base_id=?',(row_id,base_id)).rowcount
            if not count:raise DomainError('Registro inexistente.',404)
            self._touch(db,base_id)
        self.db.audit(actor,'RECORD_DELETED',base_id,{'row_id':row_id})

    def approve_public(self,base_id,actor,ids=None):
        self.require_base(base_id)
        with self.db.tx(immediate=True) as db:
            sql="UPDATE records SET approved=1,reviewed_by=?,updated_at=? WHERE base_id=? AND audience='public' AND enabled=1 AND approved=0"
            args=[actor,time.time(),base_id]
            if ids is not None:
                if not ids:return 0
                if len(ids)>self.cfg.max_records:raise DomainError('Selección demasiado grande.')
                sql+=' AND id IN ('+','.join('?'*len(ids))+')';args.extend(ids)
            count=db.execute(sql,args).rowcount
            if count:self._touch(db,base_id)
        self.db.audit(actor,'PUBLIC_CONTENT_APPROVED',base_id,{'count':count})
        return count

    def save_source(self,base_id,data,actor):
        self.require_base(base_id);source=Source.model_validate(data)
        with self.db.tx(immediate=True) as db:
            db.execute('INSERT INTO sources VALUES(?,?,?) ON CONFLICT(base_id,source_key) DO UPDATE SET content_json=excluded.content_json',
                (base_id,source.id,dumps(source.model_dump())))
            db.execute('UPDATE records SET approved=0,reviewed_by=NULL WHERE base_id=?',(base_id,))
            self._touch(db,base_id)
        self.db.audit(actor,'SOURCE_SAVED',base_id,{'source_id':source.id})

    def enqueue_build(self,base_id,settings,actor):
        version_id=uid();job_id=uid();now=time.time()
        with self.db.tx(immediate=True) as db:
            base=db.execute('SELECT * FROM bases WHERE id=?',(base_id,)).fetchone()
            if not base:raise DomainError('Base inexistente.',404)
            if base['status']=='deleting':raise DomainError('La base se está eliminando.',409)
            if db.execute("SELECT 1 FROM jobs WHERE base_id=? AND status IN ('queued','running')",(base_id,)).fetchone():
                raise DomainError('Esta base ya tiene un trabajo pendiente.',409)
            pending=db.execute("SELECT COUNT(*) FROM records WHERE base_id=? AND audience='public' AND enabled=1 AND approved=0",(base_id,)).fetchone()[0]
            if pending:raise DomainError(f'Falta revisar y aprobar {pending} registros públicos.',409,'review_required')
            rows=db.execute("SELECT * FROM records WHERE base_id=? AND audience='public' AND approved=1 AND enabled=1 ORDER BY id",(base_id,)).fetchall()
            if not rows:raise DomainError('No hay contenido público aprobado para indexar.')
            profile={'chunk_tokens':settings.chunk_tokens,'overlap_tokens':settings.overlap_tokens,'model':'intfloat/multilingual-e5-small','sparse':'Qdrant/bm25','language':'spanish','dim':384}
            db.execute('INSERT INTO versions(id,base_id,revision,collection_name,profile_json,created_at) VALUES(?,?,?,?,?,?)',
                (version_id,base_id,base['revision'],'gianna_'+version_id,dumps(profile),now))
            for r in rows:
                db.execute('INSERT INTO version_records VALUES(?,?,?)',(version_id,r['record_key'],r['content_json']))
            source_ids={s for r in rows for s in json.loads(r['content_json'])['source_refs']}
            for s in db.execute('SELECT * FROM sources WHERE base_id=?',(base_id,)).fetchall():
                if s['source_key'] in source_ids:db.execute('INSERT INTO version_sources VALUES(?,?,?)',(version_id,s['source_key'],s['content_json']))
            db.execute('INSERT INTO jobs(id,kind,base_id,version_id,payload_json,created_at) VALUES(?,?,?,?,?,?)',(job_id,'build',base_id,version_id,dumps(profile),now))
        self.db.audit(actor,'BUILD_QUEUED',version_id)
        return job_id,version_id

    def activate(self,version_id,actor,rollback=False):
        # This SQLite pointer is the ONLY activation authority; no distributed SQL/Qdrant alias update.
        with self.db.tx(immediate=True) as db:
            v=db.execute('SELECT v.*,b.revision AS current_revision,b.status AS base_status FROM versions v JOIN bases b ON b.id=v.base_id WHERE v.id=?',(version_id,)).fetchone()
            if not v or v['status']!='ready' or v['base_status']=='deleting':raise DomainError('La versión todavía no está lista.',409)
            if not rollback and v['revision']!=v['current_revision']:
                raise DomainError('La base cambió desde la indexación. Generá otra versión.',409,'stale_version')
            if rollback and not v['published_at']:
                raise DomainError('Solo se puede volver a una versión publicada previamente.',409)
            db.execute('UPDATE active_knowledge SET version_id=? WHERE singleton=1',(version_id,))
            db.execute('UPDATE versions SET published_at=COALESCE(published_at,?) WHERE id=?',(time.time(),version_id))
        self.db.audit(actor,'KNOWLEDGE_ROLLBACK' if rollback else 'KNOWLEDGE_PUBLISHED',version_id)

    def active(self):
        return self.db.one('SELECT v.*,b.name FROM active_knowledge a JOIN versions v ON v.id=a.version_id JOIN bases b ON b.id=v.base_id WHERE a.singleton=1')

    def unpublish(self,actor):
        self.db.execute('UPDATE active_knowledge SET version_id=NULL WHERE singleton=1')
        self.db.audit(actor,'KNOWLEDGE_UNPUBLISHED')

    def enqueue_delete(self,base_id,actor):
        base=self.require_base(base_id)
        active=self.active()
        if active and active['base_id']==base_id:raise DomainError('Primero despublicá esta base o publicá otra.',409)
        with self.db.tx(immediate=True) as db:
            if db.execute('SELECT 1 FROM active_knowledge a JOIN versions v ON v.id=a.version_id WHERE v.base_id=?',(base_id,)).fetchone():
                raise DomainError('No se puede eliminar una base activa.',409)
            if db.execute("SELECT 1 FROM jobs WHERE base_id=? AND status IN ('queued','running')",(base_id,)).fetchone():
                raise DomainError('Hay un trabajo pendiente para esta base.',409)
            id=uid();db.execute('INSERT INTO jobs(id,kind,base_id,payload_json,created_at) VALUES(?,?,?,?,?)',(id,'delete',base_id,dumps({'name':base['name']}),time.time()))
            db.execute("UPDATE bases SET status='deleting' WHERE id=?",(base_id,))
        self.db.audit(actor,'BASE_DELETE_QUEUED',base_id)
        return id
