"""Opt-in real RAG checks, including paired synthetic corpora kept out of the portal."""
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import time
import urllib.request

from gianna.config import Config
from gianna.corpus import Corpus,DocumentInfo,Record
from gianna.db import Database
from gianna.security import Security
from gianna.services.jobs import Jobs
from gianna.services.knowledge import Knowledge
from gianna.services.rag import RAG
from gianna.services.runtime import Embeddings,LanceStore,Ollama
from gianna.services.settings import get_settings


def observed(db,reply):
    row=db.one('SELECT retrieval_trace_json,prompt_tokens,generation_ms FROM queries WHERE id=?',(reply['id'],))
    trace=json.loads(row['retrieval_trace_json'])
    cited=[c['record_id'] for c in reply['citations']]
    checks={'searched':bool(trace.get('rounds')) and all(r.get('global_public_search') for r in trace['rounds']),
        'reranked':bool(trace.get('reranked')),'generator_used':bool(row['prompt_tokens']) and row['generation_ms']>0,
        'valid_status':reply['status'] in {'answered','insufficient_evidence'},
        'citations_from_context':set(cited)<=set(trace.get('selected_record_ids',[])),
        'no_private_state':'_conversation_state' not in reply}
    return {'status':reply['status'],'answer':reply['answer'],'citation_record_ids':cited,'checks':checks,'trace':trace}


def public_cases(base,origin,db):
    headers={'Origin':origin,'Content-Type':'application/json'}
    def call(path,body=None,method=None):
        req=urllib.request.Request(base+path,headers=headers,method=method,
            data=json.dumps(body).encode() if body is not None else None)
        with urllib.request.urlopen(req,timeout=150) as response:return json.load(response)
    if not call('/api/config')['available']:raise RuntimeError('La API todavía no está lista.')
    challenge=call('/api/captcha')
    captcha_answer=sum(int(n) for n in re.findall(r'\d+',challenge['question']))
    session=call('/api/sessions',{'captcha_id':challenge['id'],
        'captcha_answer':str(captcha_answer)})
    headers['Authorization']='Bearer '+session['token']
    results=[]
    cases=[('Quiero invertir en energías renovables',None),
           ('¿Qué información figura sobre soluciones de agua y efluentes?','O10'),
           ('¿Qué dice la guía sobre equipos digitales para problemas productivos?','O08'),
           ('¿Qué documentación hay sobre micropropagación de orquídeas?',None),
           ('¿Qué dice la documentación sobre eficiencia energética?','O09')]
    try:
        for question,expected in cases:
            start=time.perf_counter()
            reply=call('/api/chat',{'message':question});result=observed(db,reply)
            if expected:result['checks']['expected_source']=expected in result['citation_record_ids']
            result.update(question=question,elapsed_ms=round((time.perf_counter()-start)*1000))
            results.append(result)
            print(json.dumps({'kind':'public',**result},ensure_ascii=False),flush=True)
    finally:
        call('/api/sessions/current',method='DELETE')
    return results


def paired_synthetic(cfg,settings):
    # Models are read from their existing cache. Only the dedicated temporary
    # SQLite/LanceDB directories are built/activated; user snapshots stay intact.
    embeddings=Embeddings(cfg);embeddings.load();results=[]
    subjects=[('¿Qué información hay sobre generación de electricidad con energías renovables?',
        'Documento sintético de prueba: se describen instalaciones que transforman la luz del sol en electricidad. '
        'Están en la zona ficticia Alfa y no son una oferta comercial real.'),
        ('¿Qué documentación hay sobre micropropagación?',
        'Documento sintético de prueba: un laboratorio multiplica plantas a partir de tejidos en recipientes estériles. '
        'El procedimiento se realiza in vitro y no describe una oferta comercial real.'),
        ('Quiero invertir en energías renovables',
        'Catálogo sintético de evaluación: propuesta de prueba abierta a capital privado para generar electricidad '
        'utilizando la luz del sol. Ubicación ficticia: Alfa, Lavalleja. Etapa ficticia: estudio de factibilidad. '
        'No hay permisos ni rentabilidad garantizados. Estos datos son exclusivamente sintéticos y no son una oferta real.')]
    for question,relevant in subjects:
        for present in (True,False):
            with TemporaryDirectory(prefix='gianna-rag-generality-') as folder:
                isolated=replace(cfg,data_dir=Path(folder),worker_enabled=False)
                db=Database(isolated.db_path);db.migrate();knowledge=Knowledge(db,isolated)
                security=Security(db,isolated,lambda *args:None)
                rag=RAG(db,isolated,knowledge,embeddings,LanceStore(isolated),Ollama(cfg),security)
                jobs=Jobs(db,isolated,knowledge,embeddings,rag.vector_store,rag)
                corpus=Corpus(document=DocumentInfo(id='synthetic',title='Prueba sintética, no publicar en el portal'),records=[
                    Record(id='synthetic-public',title='Documento técnico de prueba',topic='Documentación',audience='public',
                        evidence_type='documented_in_source',text=relevant if present else
                        'Documento sintético de prueba: este taller repara máquinas de coser. Es el único tema del documento.'),
                    Record(id='synthetic-private',title='Contenido reservado',topic='Interno',audience='internal',
                        evidence_type='reference',text='Información privada de prueba, no pública.')])
                bid=knowledge.import_corpus(corpus,'Regresión aislada','local-test');knowledge.approve_public(bid,'local-test')
                _,vid=knowledge.enqueue_build(bid,settings,'local-test');jobs.execute_job(jobs.claim())
                assert db.one('SELECT status FROM versions WHERE id=?',(vid,))['status']=='ready'
                knowledge.activate(vid,'local-test')
                start=time.perf_counter();reply=rag.answer(question,settings)
                # Internal state is stripped by HTTP in public_cases; here we
                # invoke the exact same domain pipeline without a public session.
                reply.pop('_conversation_state',None)
                result=observed(db,reply)
                result['checks']['changes_with_evidence']=reply['status']==('answered' if present else 'insufficient_evidence')
                result['checks']['no_private_citation']='synthetic-private' not in result['citation_record_ids']
                result.update(question=question,relevant_source_present=present,
                    elapsed_ms=round((time.perf_counter()-start)*1000))
                results.append(result)
                print(json.dumps({'kind':'synthetic',**result},ensure_ascii=False),flush=True)
    return results


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-provider',action='store_true',required=True)
    parser.add_argument('--base',default='http://127.0.0.1:8000')
    parser.add_argument('--origin',default='http://127.0.0.1:4321')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();cfg=Config.from_env();db=Database(cfg.db_path);settings=get_settings(db,cfg)
    active_before=Knowledge(db,cfg).active()['id']
    public=public_cases(args.base.rstrip('/'),args.origin,db)
    synthetic=paired_synthetic(cfg,settings)
    assert Knowledge(db,cfg).active()['id']==active_before
    services=Path(__file__).resolve().parents[1]/'gianna'/'services'
    report={'scope':'Small real-provider regression and isolated synthetic corpus pairs, not a factual certification.',
        'version_id':active_before,'model':settings.model,'public_session_deleted':True,'public_snapshot_unchanged':True,
        'evaluator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'source_hashes':{name:hashlib.sha256((services/name).read_bytes()).hexdigest() for name in (
            'harness.py','rag.py','information.py','context_builder.py','response_policy.py','response_validation.py','project_memory.py')},
        'public':public,'synthetic':synthetic}
    all_results=public+synthetic
    report.update(passed=sum(all(r['checks'].values()) for r in all_results),total=len(all_results))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'total':report['total']}),flush=True)
    if report['passed']!=report['total']:raise SystemExit(1)
