"""Opt-in pre-evidence intent, source-bound statements and atomic review on an isolated index."""
import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import secrets
import time

from cryptography.fernet import Fernet
from dotenv import dotenv_values
import httpx

from gianna.config import Config
from gianna.db import Database
from gianna.services.agent import Evidence
from gianna.services.knowledge import Knowledge
from gianna.services.neural import Embeddings
from gianna.services.retrieval import Retriever
from gianna.services.vector_store import LanceStore
from gianna.services.settings import Settings
from gianna.services.reranking import RerankBudget
from gianna.services.answer_contract import (
    Intent,AnswerPlan,Review,InvalidContract,INTENT_TOOL,ANSWER_TOOL,REVIEW_TOOL,
    INTENT_POLICY,ANSWER_POLICY,REVIEW_POLICY,parse,validate_plan,review_payload,accepted,render,
)
from scripts.evaluate_invest_prompts import NoRetryOllama,ReadOnlyDatabase


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',action='store_true');p.add_argument('--benchmark',type=Path,required=True)
    p.add_argument('--models-dir',type=Path,required=True);p.add_argument('--cases',type=Path,default=Path('evals/invest_rebuild.json'))
    p.add_argument('--output',type=Path,required=True);p.add_argument('--model',default='deepseek-v4.1-flash:1017')
    p.add_argument('--review-model',default='');p.add_argument('--max-http',type=int,default=48)
    p.add_argument('--all',action='store_true');a=p.parse_args()
    if not a.run or a.output.exists() or not 1<=a.max_http<=160:p.error('Explicit bounded run and new output required')
    root=Path(__file__).resolve().parents[1];bench=json.loads(a.benchmark.read_bytes());cases=json.loads(a.cases.read_bytes())
    if not a.all:
        ids={'varela','solar_best','wind_best','north_nightlife','water_setbacks','tourism_steps','prices','solar_followup'}
        cases=[c for c in cases if c['id'] in ids]
    class PreparedConfig(Config):
        @property
        def model_dir(self):return a.models_dir.resolve()
    cfg=PreparedConfig.from_env({'data_dir':a.benchmark.resolve().parent/'runtime','embedding_threads':2,
      'secret_key':secrets.token_urlsafe(48),'encryption_key':Fernet.generate_key().decode()},
      environ={'FLASK_ENV':'testing','DATABASE_URL':''},initialize_storage=False)
    db=ReadOnlyDatabase(Database(cfg.db_path));r=Retriever(db,Knowledge(db,cfg),Embeddings(cfg),LanceStore(cfg))
    version=bench['versions']['new'];meta=r.version(version)
    r.embeddings.for_profile(json.loads(meta['profile_json'])).load()
    settings=Settings(model=a.model,temperature=.1,max_output_tokens=4096)
    reviewer=settings.model_copy(update={'model':a.review_model or a.model})
    v=dotenv_values(root/'.env');pcfg=SimpleNamespace(ollama_url=v['OLLAMA_HOST'].rstrip('/'),
      ollama_api_key=v['OLLAMA_API_KEY'],ollama_fallback_models=())
    files=[Path(__file__),root/'gianna/services/answer_contract.py',a.cases]
    frozen={str(f.resolve()):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    state={'scope':'component_pre_evidence_intent_grounded_statements_atomic_review','source_sha256':frozen,
      'index_corpus_sha256':bench['corpus_sha256'],'model':a.model,'review_model':reviewer.model,'http_attempts':0,
      'max_http':a.max_http,'cases':[],'production_changed':False,'safety_flow_evaluated':False,
      'automatic_quality_verdict':False}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    for f in files:
        if f.suffix=='.py':(a.output.parent/(a.output.stem+'-'+f.name)).write_bytes(f.read_bytes())
    def save():a.output.write_bytes((json.dumps(state,ensure_ascii=False,indent=2)+'\n').encode())
    def reserve(request):
        if state['http_attempts']>=a.max_http:raise RuntimeError('Paid batch limit reached')
        if any(hashlib.sha256(Path(f).read_bytes()).hexdigest()!=h for f,h in frozen.items()):raise RuntimeError('Frozen source changed')
        state['http_attempts']+=1;save()
    def chat(policy,payload,tool,selected=settings):
        m,usage,_=provider.chat([{'role':'system','content':policy},
          {'role':'user','content':json.dumps(payload,ensure_ascii=False)}],selected,tools=[tool],
          think=False if selected.model.startswith('deepseek') else 'auto',timeout=60)
        return m,usage
    histories={}
    with httpx.Client(base_url=pcfg.ollama_url,headers={'Authorization':'Bearer '+pcfg.ollama_api_key},timeout=60,
         trust_env=False,follow_redirects=False,event_hooks={'request':[reserve]}) as client:
        provider=NoRetryOllama(pcfg,client);save()
        for case in cases:
            history=histories.get(case.get('parent'),[]);start=time.perf_counter();before=state['http_attempts']
            result={'id':case['id'],'question':case['q'],'history':history,'attempts':[]}
            try:
                m,u=chat(INTENT_POLICY,{'question':case['q'],'history':history},INTENT_TOOL)
                result['intent_response']=m;intent=parse(m,'interpretar_pedido',Intent);result['intent']=intent.model_dump()
                cards,trace=r.search(intent.query,settings,version,rerank_budget=RerankBudget(1500))
                result['retrieval']=trace;e=Evidence();e.render(cards)
                if any(ask.kind in {'fact','procedure','methodology'} for ask in intent.asks):
                    e.render(cards,force=True,documentary=True,methodology=any(ask.kind=='methodology' for ask in intent.asks))
                result['evidence']=e.for_writing()
                payload={'question':case['q'],'history':history,'intent':intent.model_dump(),'evidence_text':e.for_writing()}
                feedback=None
                for attempt in range(2):
                    body=payload if feedback is None else payload|{'previous_attempt':previous,'correction':feedback}
                    correction_policy=''
                    if feedback:
                        if 'structural_error' in feedback:
                            correction_policy='\nCORRECCIÓN OBLIGATORIA: el intento anterior no cumplió el contrato. Entregá un plan nuevo que corrija la estructura y use citas literales reales de la evidencia.'
                        else:
                            bad=[c['statement'] for c in feedback['review']['checks'] if not all(c[k] for k in ('supported','answers_ask','informative','material_conditions_preserved'))]
                            correction_policy='\nCORRECCIÓN OBLIGATORIA: el control rechazó los índices '+','.join(map(str,bad))+'. Redactá un plan nuevo que atienda los criterios fallidos de correction. Los temas ajenos al pedido quedan fuera del nuevo plan; conservá los hechos pertinentes y condiciones sustantivas. No copies el intento rechazado.'
                    m,u=chat(ANSWER_POLICY+correction_policy,body,ANSWER_TOOL);previous=m
                    step={'message':m,'usage':u};result['attempts'].append(step)
                    try:
                        plan=validate_plan(parse(m,'redactar_informacion',AnswerPlan),intent,e.presented)
                    except InvalidContract as exc:
                        step['invalid_code']=exc.code;feedback={'structural_error':exc.code};continue
                    step['plan']=plan.model_dump()
                    rm,ru=chat(REVIEW_POLICY,review_payload(plan,intent,e.presented),REVIEW_TOOL,reviewer)
                    step['review_message']=rm;step['review_usage']=ru
                    review=parse(rm,'comprobar_afirmaciones',Review);step['review']=review.model_dump()
                    if accepted(review,plan,intent):
                        result.update(status='machine_accepted',answer=render(plan));break
                    feedback={'review':review.model_dump()}
                else:result['status']='rejected'
                histories[case['id']]=history+[{'role':'user','content':case['q']}]
                if 'answer' in result:histories[case['id']].append({'role':'assistant','content':result['answer']})
            except Exception as exc:result.update(status='failed',error_type=type(exc).__name__,error_code=getattr(exc,'code',None))
            result.update(http_attempts=state['http_attempts']-before,ms=round((time.perf_counter()-start)*1000))
            state['cases'].append(result);save();print(json.dumps({'case':case['id'],'status':result['status'],
              'calls':result['http_attempts'],'attempts':state['http_attempts']}),flush=True)


if __name__=='__main__':main()
