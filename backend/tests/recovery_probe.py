"""Helper executed ONLY inside disposable regression containers, never production."""
import json
import os
from pathlib import Path
import sys
import time
import uuid
from urllib.parse import urlparse

from gianna import create_app
from gianna.config import Config
from gianna.corpus import Corpus, DocumentInfo, Record
from gianna.db import Database, dumps
from gianna.security import token_hash
from gianna.services.knowledge import Knowledge
from gianna.services.recovery import digest
from gianna.services.settings import Settings
from gianna.services.storage import writer_lock
from gianna.services.vector_store import LanceStore


def editorial(db):
    return digest({name:db.all('SELECT * FROM '+name+' ORDER BY 1') for name in
                   ('bases','records','sources','versions','version_records','version_sources','chunks','active_knowledge')})


def main():
    if os.environ.get('GIANNA_RECOVERY_REGRESSION')!='isolated':
        raise SystemExit('Only a disposable regression environment is allowed.')
    action=sys.argv[1];cfg=Config.from_env(initialize_storage=action=='seed')
    database=urlparse(cfg.database_url)
    if database.hostname!='maria' or database.path!='/gianna_recovery':
        raise SystemExit('Only the disposable regression database is allowed.')
    folder=cfg.data_dir/'recovery-tests'
    if action=='seed':
        folder.mkdir(exist_ok=True)
        app=create_app(cfg);s=app.extensions['gianna']
        corpus=Corpus(document=DocumentInfo(id='recovery-test',title='Prueba de persistencia'),records=[
            Record(id='persist-1',title='Evidencia de persistencia',topic='Prueba',audience='public',
                   text='Evidencia local de recuperación territorial: código PINO-314. Los proyectos deben verificar sus permisos.'),
            Record(id='persist-2',title='Continuidad del índice',topic='Prueba',audience='public',
                   text='El índice conserva la fotografía publicada y sus fuentes a través de los reinicios. Código SIERRA-271.'),
            Record(id='private-1',title='Registro interno de prueba',topic='Prueba',audience='internal',
                   text='Este registro interno nunca debe ingresar al índice público.')])
        base=s.knowledge.import_corpus(corpus,'Prueba aislada','test')
        s.knowledge.approve_public(base,'test')
        jid,vid=s.knowledge.enqueue_build(base,Settings(),'test')
        s.jobs.execute_job(s.jobs.claim())  # Real ONNX preparation + embedding + Lance FTS, no generator.
        result=s.db.one('SELECT status,error FROM jobs WHERE id=?',(jid,))
        if result['status']!='done':raise RuntimeError('Seed build failed: '+str(result))
        s.knowledge.activate(vid,'test')
        user=s.security.create_user('regression@example.test','Regresión aislada','only-a-generated-test-password','owner')
        now=time.time();sid=os.environ['GIANNA_TEST_SESSION']
        s.db.execute('INSERT INTO admin_sessions VALUES(?,?,?,?,?,?)',(token_hash(sid),user,now,now,now+7200,now))
        expected={'editorial_digest':editorial(s.db),'version_id':vid,'fingerprint':s.embeddings.profile['fingerprint'],
                  'chunks':s.knowledge.active()['chunk_count']}
        (folder/'expected.json').write_text(dumps(expected))
        print(dumps(expected))
        return
    db=Database(cfg.database_target);knowledge=Knowledge(db,cfg);version=knowledge.active()
    if action=='state':
        job=db.one('SELECT id,kind,status,attempts,started_at,error_code FROM jobs WHERE id=?',(sys.argv[2],))
        print(dumps({'editorial_digest':editorial(db),'version_id':version['id'] if version else None,
                     'data_dir_exists':cfg.data_dir.exists(),'models_exist':cfg.model_dir.exists(),'job':job}))
    elif action=='legacy-failed-job':
        identifier=sys.argv[2]
        job=db.one('SELECT * FROM jobs WHERE id=?',(identifier,))
        assert job and job['kind']=='warmup' and job['version_id']==version['id'] and job['status']=='queued'
        assert job['attempts']==0
        db.execute("UPDATE jobs SET status='failed',stage='failed',attempts=3,error_code=NULL,"
                   "error='Falta un montaje persistente en DATA_DIR. Revisá el recurso de despliegue.',"
                   "message='El trabajo no se completó. La base activa no cambió.',finished_at=? WHERE id=?",
                   (time.time(),identifier))
        print(dumps(db.one('SELECT id,status,attempts FROM jobs WHERE id=?',(identifier,))))
    elif action=='assert':
        expected=json.loads((folder/'expected.json').read_text())
        assert expected['editorial_digest']==editorial(db)
        assert expected['version_id']==version['id']
        store=LanceStore(cfg)
        assert store.inspect(version['collection_name'],expected['chunks'])['ready']
        print(dumps({'editorial_unchanged':True,'version_id':version['id'],'vectors':store.count(version['collection_name'])}))
    elif action=='models-away':
        with writer_lock(cfg):cfg.model_dir.rename(cfg.data_dir/('models-saved-'+uuid.uuid4().hex[:8]))
        print(dumps({'models_moved':True}))
    elif action in {'missing','incomplete'}:
        store=LanceStore(cfg)
        with db.physical_lock(),writer_lock(cfg):
            saved='gianna_test_saved_'+uuid.uuid4().hex
            rows=store.db.open_table(version['collection_name']).to_arrow().to_pylist()
            store.rename(version['collection_name'],saved)
            if action=='incomplete':
                store.create(version['collection_name']);store.restore_rows(version['collection_name'],rows[:-1]);store.finalize(version['collection_name'])
            (folder/'held').write_text('held')
            deadline=time.monotonic()+60
            while (folder/'held').exists():
                if time.monotonic()>deadline:raise TimeoutError('Regression lock release deadline')
                time.sleep(.1)
        print(dumps({'simulated':action,'original_preserved':True}))
    elif action=='release':(folder/'held').unlink(missing_ok=True)
    elif action=='held':print(dumps({'held':(folder/'held').exists()}))
    else:raise ValueError('Unknown regression action')


if __name__=='__main__':main()
