"""Durable SQLite queue, one worker thread, short embedding batches and restart leases."""
import json
import logging
import threading
import time
from pathlib import Path
from ..db import uid,dumps
from ..errors import DomainError,Cancelled
from ..corpus import load_corpus
from ..chunking import chunks_for_record
from .settings import get_settings

LOG=logging.getLogger(__name__)


class Jobs:
    def __init__(self,db,cfg,knowledge,embeddings,qdrant,rag=None):
        self.db=db;self.cfg=cfg;self.knowledge=knowledge;self.embeddings=embeddings;self.qdrant=qdrant;self.rag=rag
        self.stop_event=threading.Event();self.thread=None;self.wake=threading.Event()
        self.token=uid();self.current_job=None

    def enqueue(self,kind,payload=None,base_id=None,version_id=None):
        if kind not in {'import','warmup','evaluation'}:raise DomainError('Tipo de trabajo no válido.')
        id=uid();self.db.execute('INSERT INTO jobs(id,kind,base_id,version_id,payload_json,created_at) VALUES(?,?,?,?,?,?)',
            (id,kind,base_id,version_id,dumps(payload or {}),time.time()))
        self.wake.set();return id

    def start(self):
        if self.thread and self.thread.is_alive():return
        self.stop_event.clear()
        self.thread=threading.Thread(target=self.run,name='gianna-jobs',daemon=True)
        self.thread.start()
        threading.Thread(target=self.heartbeat,name='gianna-job-lease',daemon=True).start()
        if self.knowledge.active():self.enqueue('warmup')

    def heartbeat(self):
        while not self.stop_event.wait(20):
            try:
                if self.current_job:
                    self.db.execute("UPDATE jobs SET lease_until=? WHERE id=? AND status='running' AND owner_token=?",(time.time()+120,self.current_job,self.token))
            except Exception:LOG.warning('No se pudo renovar lease del trabajo.')

    def claim(self):
        now=time.time()
        with self.db.tx(immediate=True) as db:
            db.execute("UPDATE jobs SET status='queued',owner_token=NULL,message='Reanudando después de una interrupción' WHERE status='running' AND lease_until<?",(now,))
            if db.execute("SELECT 1 FROM jobs WHERE status='running' AND lease_until>=?",(now,)).fetchone():return None
            r=db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if not r:return None
            db.execute("UPDATE jobs SET status='running',started_at=COALESCE(started_at,?),lease_until=?,owner_token=?,error=NULL WHERE id=?",(now,now+120,self.token,r['id']))
            return dict(r)

    def progress(self,job_id,message,progress=None,total=None):
        row=self.db.one('SELECT cancel_requested,owner_token FROM jobs WHERE id=?',(job_id,))
        if not row or row['cancel_requested'] or row['owner_token']!=self.token or self.stop_event.is_set():raise Cancelled()
        args=[message[:400],time.time()+120]
        sql='UPDATE jobs SET message=?,lease_until=?'
        if progress is not None:sql+=',progress=?';args.append(progress)
        if total is not None:sql+=',total=?';args.append(total)
        sql+=' WHERE id=?';args.append(job_id)
        self.db.execute(sql,args)

    def run(self):
        last_maintenance=0
        while not self.stop_event.is_set():
            try:
                job=self.claim()
                if not job:
                    if time.time()-last_maintenance>3600:
                        self.maintenance();last_maintenance=time.time()
                    self.wake.wait(2);self.wake.clear();continue
                self.current_job=job['id']
                self.execute_job(job)
            except Exception:LOG.exception('Error en el bucle de trabajos; se reintentará la lectura de la cola.')
            finally:self.current_job=None

    def execute_job(self,job):
        id=job['id'];kind=job['kind'];payload=json.loads(job['payload_json'])
        try:
            self.progress(id,'Preparando trabajo')
            if kind=='import':
                self.progress(id,'Leyendo y validando el archivo')
                existing_import=self.db.one('SELECT id FROM bases WHERE id=?',(id,))
                if existing_import:
                    self.db.execute("UPDATE jobs SET status='done',base_id=?,finished_at=?,message='Importación recuperada sin duplicar la base',lease_until=NULL WHERE id=?",(id,time.time(),id))
                    return
                path=Path(payload['path']).resolve()
                if not path.is_relative_to((self.cfg.data_dir/'uploads').resolve()):raise DomainError('Ruta de importación inválida.')
                corpus=load_corpus(path,payload.get('audience','internal'),payload.get('cutoff_date'))
                corpus.document.filename=payload.get('filename',path.name)
                self.progress(id,'Guardando borrador; no se publicará automáticamente',len(corpus.records),len(corpus.records))
                base_id=self.knowledge.import_corpus(corpus,payload.get('name',''),payload.get('actor'),payload.get('filename',''),import_id=id)
                self.db.execute('UPDATE jobs SET base_id=? WHERE id=?',(base_id,id))
                path.unlink(missing_ok=True)
                result={'base_id':base_id,'records':len(corpus.records)}
            elif kind=='warmup':
                self.progress(id,'Preparando E5 y BM25. La primera ejecución descarga los modelos.')
                self.embeddings.load();result=self.embeddings.profile
            elif kind=='build':result=self.build(job)
            elif kind=='delete':result=self.delete(job)
            elif kind=='evaluation':result=self.evaluate(job,payload)
            else:raise DomainError('Trabajo desconocido.')
            self.db.execute("UPDATE jobs SET status='done',finished_at=?,message='Finalizado',result_json=?,lease_until=NULL WHERE id=? AND owner_token=?",
                (time.time(),dumps(result),id,self.token))
        except Cancelled:
            self.db.execute("UPDATE jobs SET status='cancelled',message='Cancelado. La base activa no cambió.',finished_at=?,lease_until=NULL WHERE id=? AND owner_token=?",(time.time(),id,self.token))
            if job.get('version_id'):self.db.execute("UPDATE versions SET status='cancelled' WHERE id=? AND status!='ready'",(job['version_id'],))
        except Exception as exc:
            message=exc.message if isinstance(exc,DomainError) else f'{type(exc).__name__}. Revisá el registro del servidor antes de reintentar.'
            self.db.execute("UPDATE jobs SET status='failed',error=?,message='El trabajo no se completó. La base activa no cambió.',finished_at=?,lease_until=NULL WHERE id=? AND owner_token=?",
                (message[:1200],time.time(),id,self.token))
            if job.get('version_id'):self.db.execute("UPDATE versions SET status='failed' WHERE id=? AND status!='ready'",(job['version_id'],))
            LOG.exception('Trabajo %s de tipo %s falló',id,kind)

    def build(self,job):
        id=job['id'];vid=job['version_id']
        version=self.db.one('SELECT * FROM versions WHERE id=?',(vid,))
        if not version:raise DomainError('Versión no encontrada.',404)
        profile=json.loads(version['profile_json'])
        self.db.execute("UPDATE versions SET status='building' WHERE id=?",(vid,))
        self.progress(id,'Preparando E5 multilingüe y el tokenizador exacto')
        self.embeddings.load()
        if profile.get('fingerprint') and profile['fingerprint']!=self.embeddings.profile['fingerprint']:
            raise DomainError('Cambió el modelo durante una reanudación. Creá una versión nueva; no mezcles vectores.')
        profile.update(self.embeddings.profile)
        self.db.execute('UPDATE versions SET profile_json=? WHERE id=?',(dumps(profile),vid))
        existing=self.db.one('SELECT COUNT(*) AS n FROM chunks WHERE version_id=?',(vid,))['n']
        if not existing:
            records=self.db.all('SELECT content_json FROM version_records WHERE version_id=? ORDER BY record_key',(vid,))
            all_chunks=[]
            for i,r in enumerate(records):
                self.progress(id,'Dividiendo contenido con el tokenizador de E5',i,len(records))
                record=json.loads(r['content_json'])
                if record['audience']!='public':raise DomainError('Se detectó contenido interno en una versión pública.')
                all_chunks.extend(chunks_for_record(vid,record,self.embeddings.count,profile['chunk_tokens'],profile['overlap_tokens']))
            if len(all_chunks)>30000:raise DomainError('Se excedió el máximo de 30.000 chunks para este perfil.')
            with self.db.tx(immediate=True) as db:
                for c in all_chunks:
                    db.execute('INSERT INTO chunks(id,version_id,record_key,position,title,topic,token_count,text,content_json,embedding_hash) VALUES(?,?,?,?,?,?,?,?,?,?)',
                        (c['id'],vid,c['record_id'],c['position'],c['title'],c['topic'],c['token_count'],c['text'],dumps(c),c['embedding_hash']))
        rows=self.db.all('SELECT id FROM chunks WHERE version_id=? ORDER BY record_key,position',(vid,))
        total=len(rows)
        if not total:raise DomainError('No se generaron chunks.')
        self.progress(id,'Creando colección aislada de la base publicada',0,total)
        self.qdrant.create(version['collection_name'])
        reused=0;started=time.perf_counter()
        for offset in range(0,total,self.cfg.embedding_batch_size):
            self.progress(id,'Calculando embeddings y guardando lote',offset,total)
            rowids=[r['id'] for r in rows[offset:offset+self.cfg.embedding_batch_size]]
            batch=[json.loads(self.db.one('SELECT content_json FROM chunks WHERE id=?',(r,))['content_json']) for r in rowids]
            dense=[None]*len(batch);sparse=[None]*len(batch);missing=[]
            for i,c in enumerate(batch):
                cached=self.db.one('SELECT * FROM embedding_cache WHERE fingerprint=? AND embedding_hash=?',(profile['fingerprint'],c['embedding_hash']))
                if cached:
                    dense[i]=json.loads(cached['dense_json']);sparse[i]=json.loads(cached['sparse_json']);reused+=1
                else:missing.append(i)
            if missing:
                d,s=self.embeddings.documents([batch[i]['embedding_text'] for i in missing],[batch[i]['title']+'\n'+batch[i]['text'] for i in missing])
                for i,dv,sv in zip(missing,d,s,strict=True):dense[i]=dv;sparse[i]=sv
            self.qdrant.upsert(version['collection_name'],batch,dense,sparse)
            with self.db.tx(immediate=True) as db:
                for c,dv,sv in zip(batch,dense,sparse,strict=True):
                    db.execute('UPDATE chunks SET vector_json=? WHERE id=?',(dumps(dv),c['id']))
                    db.execute('INSERT OR IGNORE INTO embedding_cache VALUES(?,?,?,?,?)',(profile['fingerprint'],c['embedding_hash'],dumps(dv),dumps(sv),time.time()))
            # Release CPU between batches. Query inference shares the same model and lock.
            time.sleep(0.03)
        self.progress(id,'Comprobando cantidad de puntos y calculando visualización',total,total)
        if self.qdrant.count(version['collection_name'])!=total:raise DomainError('El conteo de Qdrant no coincide. No se habilita la publicación.')
        projection=self.project(vid)
        self.progress(id,'Validación terminada; lista para prueba y publicación',total,total)
        report={'chunks':total,'reused_embeddings':reused,'build_seconds':round(time.perf_counter()-started,3),
            'max_tokens':self.db.one('SELECT MAX(token_count) n FROM chunks WHERE version_id=?',(vid,))['n'],
            'projection':projection,'public_only':True,'semantic_accuracy_evaluated':False}
        self.db.execute("UPDATE versions SET status='ready',chunk_count=?,report_json=? WHERE id=?",(total,dumps(report),vid))
        return report

    def project(self,vid):
        import numpy as np
        rows=self.db.all('SELECT id,vector_json FROM chunks WHERE version_id=? AND vector_json IS NOT NULL ORDER BY id LIMIT 1200',(vid,))
        if len(rows)<2:return {'method':'PCA','points':0,'note':'Se necesitan dos puntos.'}
        matrix=np.array([json.loads(r['vector_json']) for r in rows],dtype=np.float32)
        matrix-=matrix.mean(axis=0)
        cov=matrix.T@matrix
        vals,vecs=np.linalg.eigh(cov)
        xy=matrix@vecs[:,-2:]
        for axis in range(2):
            extent=float(np.abs(xy[:,axis]).max())
            if extent:xy[:,axis]/=extent
        with self.db.tx(immediate=True) as db:
            for row,p in zip(rows,xy,strict=True):
                db.execute('UPDATE chunks SET projection_x=?,projection_y=? WHERE id=?',(float(p[0]),float(p[1]),row['id']))
        explained=float(max(0,vals[-2:].sum())/max(float(vals.sum()),1e-12))
        return {'method':'PCA','points':len(rows),'max_points':1200,'explained_variance_ratio':round(explained,5),
                'note':'Proyección aproximada, no clasificación ni prueba de calidad semántica. Muestra determinista por ID cuando hay más de 1200 puntos.'}

    def delete(self,job):
        bid=job['base_id'];active=self.knowledge.active()
        if active and active['base_id']==bid:raise DomainError('No se puede eliminar una base activa.',409)
        versions=self.db.all('SELECT * FROM versions WHERE base_id=?',(bid,))
        for i,v in enumerate(versions):
            self.progress(job['id'],'Eliminando colección de conocimiento',i,len(versions))
            self.qdrant.delete(v['collection_name'])
        with self.db.tx(immediate=True) as db:
            db.execute('DELETE FROM bases WHERE id=?',(bid,))
        return {'deleted_base_id':bid}

    def evaluate(self,job,payload):
        if not self.rag:raise DomainError('Laboratorio no disponible.')
        tests=payload.get('tests',[])
        if not tests or len(tests)>200:raise DomainError('La evaluación admite entre 1 y 200 preguntas.')
        settings=get_settings(self.db,self.cfg);results=[]
        for i,test in enumerate(tests):
            self.progress(job['id'],'Evaluando recuperación; no se llama al modelo generativo',i,len(tests))
            found,ms=self.rag.retrieve(test['question'],settings,job['version_id'])
            ids=[x['record_id'] for x in found]
            expected=set(test.get('expected_any_record_ids',[]))
            success=bool(expected&set(ids)) if expected else None
            results.append({'question':test['question'],'expected':sorted(expected),'retrieved':ids,'hit':success,'latency_ms':round(ms,2)})
        assessed=[r for r in results if r['hit'] is not None]
        return {'kind':'retrieval_only','questions':len(results),'assessed':len(assessed),
                'hit_rate':sum(r['hit'] for r in assessed)/len(assessed) if assessed else None,
                'warning':'Encontrar un fragmento no garantiza la exactitud de una respuesta generada.', 'results':results}

    def maintenance(self):
        now=time.time();settings=get_settings(self.db,self.cfg)
        with self.db.tx(immediate=True) as db:
            db.execute('DELETE FROM admin_sessions WHERE expires_at<? OR touched_at<?',(now,now-1800))
            db.execute('DELETE FROM auth_challenges WHERE expires_at<?',(now-3600,))
            db.execute('DELETE FROM chat_sessions WHERE expires_at<?',(now,))
            db.execute('DELETE FROM queries WHERE at<?',(now-settings.analytics_days*86400,))
            for window in (60,300,900,3600,86400):
                db.execute("DELETE FROM rate_limits WHERE key LIKE ? AND bucket<?",(f'%:{window}',int(now//window)-max(2,172800//window)))
        # Cache expiry is separate from the authoritative corpus and vector versions.
        self.db.execute('DELETE FROM embedding_cache WHERE created_at<?',(now-180*86400,))
