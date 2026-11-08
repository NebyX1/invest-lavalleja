"""Real LanceDB/FTS and SQL snapshots; deterministic model double, no paid calls.

These tests validate storage/recovery mechanics, not embedding quality. Real
pinned ONNX inference and container replacement live in test_recovery_docker.py.
"""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import time
import uuid

import pytest

from gianna import create_app
from gianna.chunking import chunks_for_record
from gianna.db import dumps
from gianna.errors import Cancelled, DomainError
from gianna.services.jobs import Jobs
from gianna.services.knowledge import Knowledge
from gianna.services.neural import ENGINE_VERSION, LEGACY_ENGINE_VERSION
from gianna.services.rag import RAG
from gianna.services.recovery import KnowledgeRecovery, digest, snapshot
from gianna.services.settings import Settings
from gianna.services.storage import storage_identity, writer_lock
from gianna.services.vector_store import LanceStore


class LocalEngine:
    """Deterministic model double; physical index and SQL are real."""
    def __init__(self, engine_version=ENGINE_VERSION):
        self.engine_version=engine_version
        self.profile={'engine':engine_version,'dim':384,'fingerprint':hashlib.sha256(engine_version.encode()).hexdigest()}
        self.model=None
        self.loads=0
        self._profiles={engine_version:self}

    def for_profile(self,profile):
        version=profile['engine']
        if version not in self._profiles:self._profiles[version]=LocalEngine(version)
        return self._profiles[version]

    def ready_for(self,profile):
        engine=self._profiles.get(profile.get('engine'))
        return bool(engine and engine.model and engine.profile['fingerprint']==profile.get('fingerprint'))

    def load(self,progress=None):
        if not self.model:
            self.model=True;self.loads+=1
        if progress:progress('Motor de prueba preparado')

    def count(self,text):return len(text.split())+2
    def documents(self,texts,lexical):return [[1.0]+[0.0]*383 for _ in texts],lexical
    def query(self,text):return [1.0]+[0.0]*383,text
    def rerank(self,query,texts):return [1.0]*len(texts)


def seed(db,cfg,knowledge,corpus,engine_version=ENGINE_VERSION):
    base=knowledge.import_corpus(corpus,'Base de recuperación','test')
    knowledge.approve_public(base,'test')
    job,vid=knowledge.enqueue_build(base,Settings(),'test')
    engine=LocalEngine(engine_version)
    profile={**json.loads(db.one('SELECT profile_json FROM versions WHERE id=?',(vid,))['profile_json']),**engine.profile}
    context='bekko-context-v2' if engine_version==LEGACY_ENGINE_VERSION else 'cards-context-v5'
    profile['contextualizer_version']=context
    chunks=[]
    for r in db.all('SELECT content_json FROM version_records WHERE version_id=?',(vid,)):
        record=json.loads(r['content_json'])
        for c in chunks_for_record(vid,record,engine.count,420,40):
            if engine_version==LEGACY_ENGINE_VERSION:
                # Preserve the old distinct embedding/lexical representation.
                c['contextualizer_version']=context
                c['embedding_text']=c['title']+'\nContenido:\n'+c['text']
                c['sparse_text']=c['title']+'\n'+c['text']
                c['embedding_hash']=hashlib.sha256((context+'\0'+c['embedding_text']+'\0'+c['sparse_text']).encode()).hexdigest()
                c['id']=str(uuid.uuid5(uuid.NAMESPACE_URL,f"gianna:{vid}:{c['record_id']}:{c['position']}:{c['embedding_hash']}"))
            chunks.append(c)
    for c in chunks:
        db.execute('INSERT INTO chunks(id,version_id,record_key,position,title,topic,token_count,text,content_json,embedding_hash,vector_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                   (c['id'],vid,c['record_id'],c['position'],c['title'],c['topic'],c['token_count'],c['text'],dumps(c),c['embedding_hash'],dumps([1.0]+[0.0]*383)))
    db.execute("UPDATE versions SET status='ready',chunk_count=?,profile_json=? WHERE id=?",(len(chunks),dumps(profile),vid))
    db.execute("UPDATE jobs SET status='done' WHERE id=?",(job,))
    if engine_version==LEGACY_ENGINE_VERSION:
        db.execute('UPDATE versions SET published_at=? WHERE id=?',(time.time(),vid))
        knowledge.activate(vid,'test',rollback=True)
    else:knowledge.activate(vid,'test')
    return engine,knowledge.active()


def editorial_state(db):
    return digest({name:db.all('SELECT * FROM '+name+' ORDER BY 1') for name in
                   ('bases','records','sources','versions','version_records','version_sources','chunks','active_knowledge')})


@pytest.fixture
def physical(db,cfg,knowledge,corpus,monkeypatch):
    pytest.importorskip('lancedb')
    monkeypatch.setattr('gianna.services.artifacts.ensure_models',lambda *args:None)
    engine,version=seed(db,cfg,knowledge,corpus)
    store=LanceStore(cfg)
    recovery=KnowledgeRecovery(db,cfg,knowledge,engine,store)
    return SimpleNamespace(db=db,cfg=cfg,knowledge=knowledge,engine=engine,version=version,store=store,recovery=recovery)


def test_missing_collection_and_loaded_models_never_report_ready_or_http500(physical):
    p=physical;p.engine.load()
    app=create_app(p.cfg);s=app.extensions['gianna']
    s.rag=RAG(p.db,p.cfg,p.knowledge,p.engine,p.store,s.ollama,s.security)
    # Isolate physical readiness AFTER a valid semantic verdict; never call a
    # paid provider from this storage regression.
    from test_agent import ScriptedOllama
    evaluator=ScriptedOllama()
    s.rag.agent.ollama=evaluator
    client=app.test_client()
    response=client.get('/api/config')
    assert response.status_code==200 and response.json['available'] is False
    assert response.json['knowledge_code']=='index_missing'
    # A legitimate anonymous capability, with all normal origin/session checks.
    captcha=client.get('/api/captcha').json
    import re
    a,b=map(int,re.findall(r'\d+',captcha['question']))
    token=client.post('/api/sessions',json={'captcha_id':captcha['id'],'captcha_answer':str(a+b)}).json['token']
    result=client.post('/api/chat',json={'message':'¿Qué condiciones tiene la oportunidad?'},headers={'Authorization':'Bearer '+token})
    assert result.status_code==503 and result.json['error']['code']=='index_missing'
    assert len(evaluator.semantic_calls)==1 and not evaluator.calls
    # The health endpoint closes over the original RAG, so test the new service directly too.
    assert s.rag.recovery.status()['available'] is False
    assert client.get('/health/live').status_code==200
    assert client.get('/health/ready').status_code==200


def test_exact_restore_then_new_process_recovers_real_hybrid_evidence(physical):
    p=physical;before=editorial_state(p.db)
    dry=p.recovery.recover()
    assert dry['index_valid'] is False and not (p.cfg.lance_dir).exists()
    result=p.recovery.recover(apply=True)
    assert result['changed'] and p.recovery.status()['available']
    assert p.store.count(p.version['collection_name'])==p.version['chunk_count']
    found=p.store.search(p.version['collection_name'],[1.0]+[0.0]*383,'requisitos evidencia')
    assert found and {'dense','bm25'} <= set(found[0]['channels'])
    assert editorial_state(p.db)==before
    # Fresh service objects read the SAME data, no process-local loaded state.
    fresh_engine=LocalEngine();fresh_store=LanceStore(p.cfg)
    fresh=KnowledgeRecovery(p.db,p.cfg,p.knowledge,fresh_engine,fresh_store)
    assert fresh.status()['available'] is False
    assert fresh.recover(apply=True)['changed'] is False
    assert fresh.status()['available'] and fresh_engine.loads==1
    assert fresh.recover(apply=True)['changed'] is False and fresh_engine.loads==1
    assert editorial_state(p.db)==before


@pytest.mark.parametrize('damage',['incomplete','fts','fts-incompatible','wrong-content'])
def test_invalid_index_is_detected_and_preserved_before_restore(physical,damage):
    p=physical;p.recovery.recover(apply=True)
    name=p.version['collection_name']
    table=p.store.db.open_table(name)
    if damage=='incomplete':table.delete("id = '"+p.store.ids(name).pop()+"'")
    elif damage=='fts':table.drop_index(table.list_indices()[0].name)
    elif damage=='fts-incompatible':
        from lancedb.index import FTS
        table.create_index('text',config=FTS(language='English'),replace=True)
    else:table.update(values={'topic':'corrupted'})
    assert not p.recovery.status()['available']
    before=editorial_state(p.db)
    assert p.recovery.recover(apply=True)['changed']
    assert p.recovery.status()['available']
    assert any(path.name.startswith('gianna_quarantine_') for path in p.cfg.lance_dir.iterdir())
    assert editorial_state(p.db)==before


def test_interrupted_restore_resumes_without_duplicates_or_pointer_changes(physical,monkeypatch):
    p=physical;before=editorial_state(p.db)
    original=p.store.restore_rows
    def interrupted(name,rows):
        original(name,rows)
        raise Cancelled()
    monkeypatch.setattr(p.store,'restore_rows',interrupted)
    with pytest.raises(Cancelled):p.recovery.recover(apply=True)
    assert not p.store.exists(p.version['collection_name'])
    monkeypatch.setattr(p.store,'restore_rows',original)
    fresh=KnowledgeRecovery(p.db,p.cfg,p.knowledge,LocalEngine(),LanceStore(p.cfg))
    fresh.recover(apply=True)
    assert fresh.status()['available']
    assert p.store.count(p.version['collection_name'])==p.version['chunk_count']
    assert editorial_state(p.db)==before


@pytest.mark.parametrize('damage',['internal','hash','dimension','nonfinite','missing','source'])
def test_unprovable_snapshot_is_never_automatically_reindexed(physical,damage):
    p=physical
    row=p.db.one('SELECT * FROM chunks LIMIT 1');c=json.loads(row['content_json'])
    if damage=='internal':c['audience']='internal'
    if damage=='hash':c['embedding_hash']='wrong'
    if damage=='source':c['source_refs']=['private-source']
    if damage in {'internal','hash','source'}:p.db.execute('UPDATE chunks SET content_json=? WHERE id=?',(dumps(c),row['id']))
    elif damage=='missing':p.db.execute('UPDATE chunks SET vector_json=NULL')
    else:p.db.execute('UPDATE chunks SET vector_json=? WHERE id=?',(json.dumps([float('nan')]+[0.0]*383) if damage=='nonfinite' else '[1,0]',row['id']))
    before=editorial_state(p.db)
    with pytest.raises(DomainError) as error:p.recovery.recover(apply=True)
    assert error.value.code=='snapshot_invalid'
    assert editorial_state(p.db)==before and not p.recovery.status()['available']
    assert not p.store.exists(p.version['collection_name'])


def test_pinned_fingerprint_mismatch_stays_degraded(physical):
    p=physical;p.engine.profile['fingerprint']='b'*64
    before=editorial_state(p.db)
    with pytest.raises(DomainError) as error:p.recovery.recover(apply=True)
    assert error.value.code=='embedding_mismatch'
    assert not p.recovery.status()['available'] and editorial_state(p.db)==before


def test_cache_and_independent_backup_are_scoped_to_exact_snapshot(physical):
    p=physical
    for row in p.db.all('SELECT * FROM chunks'):
        p.db.execute('INSERT INTO embedding_cache VALUES(?,?,?,?,?)',(p.engine.profile['fingerprint'],row['embedding_hash'],row['vector_json'],'"unused"',time.time()))
    p.db.execute('UPDATE chunks SET vector_json=NULL')
    assert snapshot(p.db,p.cfg,p.version)['rows']
    p.recovery.recover(apply=True)
    p.db.execute('DELETE FROM embedding_cache')
    data=snapshot(p.db,p.cfg,p.version)
    assert data['backup_used']
    # An unrelated cache fingerprint must not substitute for missing vectors.
    backup=p.cfg.data_dir/'recovery/backups'/ (p.version['id']+'.json')
    backup.rename(backup.with_suffix('.saved'))
    for row in p.db.all('SELECT * FROM chunks'):
        p.db.execute('INSERT INTO embedding_cache VALUES(?,?,?,?,?)',('different-space',row['embedding_hash'],dumps([1.0]+[0.0]*383),'"unused"',time.time()))
    with pytest.raises(DomainError):snapshot(p.db,p.cfg,p.version)


def test_changed_volume_requires_supervised_adoption(physical,tmp_path):
    p=physical;p.recovery.recover(apply=True)
    cfg=replace(p.cfg,data_dir=tmp_path/'new-volume')
    cfg.data_dir.mkdir();other=KnowledgeRecovery(p.db,cfg,p.knowledge,LocalEngine(),LanceStore(cfg))
    before=editorial_state(p.db)
    with pytest.raises(DomainError) as error:other.recover(apply=True)
    assert error.value.code=='storage_mismatch' and not cfg.lance_dir.exists()
    other.recover(apply=True,adopt_storage=True)
    assert other.status()['available'] and editorial_state(p.db)==before
    assert p.recovery.status()['code']=='storage_mismatch'


def test_production_rejects_ephemeral_layer_and_excludes_other_writers(physical,monkeypatch):
    p=physical
    monkeypatch.setattr('gianna.services.storage._mount_report',lambda path:{
        'observed':True,'mountpoint':str(path),'filesystem':'overlay',
        'read_only':False,'durable':False,'code':'storage_not_mounted'})
    with pytest.raises(DomainError) as error:storage_identity(p.db,replace(p.cfg,production=True))
    assert error.value.code=='storage_not_mounted'
    with writer_lock(p.cfg):
        with pytest.raises(DomainError) as error:
            with writer_lock(p.cfg):pytest.fail('Two writers acquired the same volume')
        assert error.value.code=='recovery_busy'


def test_legacy_keeps_its_own_vectors_representation_and_models(db,cfg,knowledge,corpus,monkeypatch):
    pytest.importorskip('lancedb')
    monkeypatch.setattr('gianna.services.artifacts.ensure_models',lambda *args:None)
    legacy,version=seed(db,cfg,knowledge,corpus,LEGACY_ENGINE_VERSION)
    root=LocalEngine();root._profiles[LEGACY_ENGINE_VERSION]=legacy
    recovery=KnowledgeRecovery(db,cfg,knowledge,root,LanceStore(cfg))
    before=editorial_state(db)
    recovery.recover(apply=True)
    assert recovery.status()['available'] and legacy.loads==1 and root.loads==0
    assert editorial_state(db)==before
    assert snapshot(db,cfg,version)['profile']['contextualizer_version']=='bekko-context-v2'


def test_restart_claims_expired_jobs_deduplicates_and_stops_after_three_attempts(physical,monkeypatch):
    p=physical
    rag=SimpleNamespace(recovery=p.recovery)
    jobs=Jobs(p.db,p.cfg,p.knowledge,p.engine,p.store,rag)
    job_id=jobs.ensure_warmup()
    assert jobs.ensure_warmup()==job_id
    first=jobs.claim();assert first['id']==job_id
    p.db.execute('UPDATE jobs SET lease_until=NULL WHERE id=?',(job_id,))
    restarted=Jobs(p.db,p.cfg,p.knowledge,p.engine,p.store,rag)
    reclaimed=restarted.claim();assert reclaimed['id']==job_id
    def offline(*args,**kwargs):raise DomainError('Red no disponible.',503,'models_recovery_failed')
    monkeypatch.setattr(p.recovery,'recover',offline)
    restarted.execute_job(reclaimed)
    row=p.db.one('SELECT * FROM jobs WHERE id=?',(job_id,))
    assert row['attempts']==2 and row['status']=='queued' and row['available_at']>time.time()
    assert restarted.claim() is None
    p.db.execute('UPDATE jobs SET available_at=0 WHERE id=?',(job_id,))
    restarted.execute_job(restarted.claim())
    row=p.db.one('SELECT * FROM jobs WHERE id=?',(job_id,))
    assert row['attempts']==3 and row['status']=='failed'
    assert restarted.ensure_warmup()==job_id and restarted.claim() is None
    assert restarted.ensure_warmup(retry=True)!=job_id


def test_new_editorial_build_prepares_and_verifies_without_publishing(db,cfg,knowledge,corpus,security,monkeypatch):
    pytest.importorskip('lancedb')
    calls=[]
    monkeypatch.setattr('gianna.services.artifacts.ensure_models',lambda *args:calls.append(args[1]))
    engine=LocalEngine();store=LanceStore(cfg)
    rag=RAG(db,cfg,knowledge,engine,store,None,security)
    base=knowledge.import_corpus(corpus,'Nueva','test');knowledge.approve_public(base,'test')
    job_id,vid=knowledge.enqueue_build(base,Settings(),'test')
    jobs=Jobs(db,cfg,knowledge,engine,store,rag);jobs.execute_job(jobs.claim())
    assert db.one('SELECT status,error FROM jobs WHERE id=?',(job_id,))=={'status':'done','error':None}
    version=db.one('SELECT * FROM versions WHERE id=?',(vid,))
    assert rag.recovery.status(version)['available'] and knowledge.active() is None
    assert calls==[ENGINE_VERSION] and engine.loads==1


def test_graceful_shutdown_requeues_instead_of_cancelling_publication_recovery(physical):
    p=physical;rag=SimpleNamespace(recovery=p.recovery)
    jobs=Jobs(p.db,p.cfg,p.knowledge,p.engine,p.store,rag)
    jid=jobs.ensure_warmup();job=jobs.claim();jobs.stop_event.set()
    before=editorial_state(p.db);jobs.execute_job(job)
    result=p.db.one('SELECT status,owner_token,lease_until FROM jobs WHERE id=?',(jid,))
    assert result=={'status':'queued','owner_token':None,'lease_until':None}
    assert editorial_state(p.db)==before


@pytest.mark.parametrize('filesystem,point,expected',[('ext4','exact',True),('tmpfs','exact',False),('overlay','exact',False),('ext4','parent',True)])
def test_mount_guard_requires_covering_durable_mount(cfg,monkeypatch,filesystem,point,expected):
    from gianna.services.storage import mounted_data_dir
    target=str(cfg.data_dir if point=='exact' else cfg.data_dir.parent).replace(' ','\\040')
    monkeypatch.setattr(Path,'read_text',lambda *args,**kwargs:f'1 0 8:1 / {target} rw - {filesystem} /dev/sda rw\n')
    assert mounted_data_dir(cfg.data_dir) is expected


def test_interrupted_staging_directory_is_preserved_and_recovered(physical):
    p=physical;data=snapshot(p.db,p.cfg,p.version)
    path=p.cfg.lance_dir/('gianna_restore_'+p.version['id']+'_'+data['digest'][:12]+'.lance')
    path.mkdir(parents=True);(path/'interrupted-marker').write_text('interrupted before manifest')
    p.recovery.recover(apply=True)
    assert p.recovery.status()['available']


def test_diagnostic_cli_never_loads_models_or_mutates_data(physical,monkeypatch,capsys):
    from gianna.config import Config
    from scripts.recover_knowledge import main
    p=physical
    def configuration(**kwargs):
        assert kwargs['initialize_storage'] is False
        return p.cfg
    monkeypatch.setattr(Config,'from_env',configuration)
    before=editorial_state(p.db);files=set(p.cfg.data_dir.rglob('*'))
    assert main([])==0
    result=json.loads(capsys.readouterr().out)
    assert result['state']=='diagnostic' and not result['changed']
    assert editorial_state(p.db)==before and files==set(p.cfg.data_dir.rglob('*'))


def test_http_database_outage_is_503_while_process_health_stays_alive(cfg,monkeypatch):
    from sqlalchemy.exc import OperationalError
    app=create_app(cfg);s=app.extensions['gianna'];client=app.test_client()
    def disconnected(*args,**kwargs):raise OperationalError('SELECT',None,RuntimeError('isolated database outage'))
    monkeypatch.setattr(s.db,'one',disconnected)
    assert client.get('/health/live').status_code==200
    for path in ('/health/ready','/health/knowledge','/api/config'):
        response=client.get(path)
        assert response.status_code==503
        assert 'database_unavailable' in response.get_data(as_text=True)


def test_transient_writer_contention_does_not_hide_missing_collection(physical):
    p=physical;p.engine.load();p.recovery.state('failed','recovery_busy',p.version['id'])
    assert p.recovery.status()['code']=='index_missing'
