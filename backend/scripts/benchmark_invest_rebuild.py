"""Isolated real ONNX/LanceDB comparison; never reads .env or calls a provider.

SQLite is used only inside this disposable evaluation fixture. No application
database, published pointer or source file is modified. Results are retrieval
measurements, not certification of generated answers or source claims.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import logging
from pathlib import Path
import secrets
import time

from cryptography.fernet import Fernet
from gianna.config import Config
from gianna.corpus import load_corpus
from gianna.services.reranking import RerankBudget
from gianna.services.settings import Settings
from gianna.web import create_app


ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rank(ids, expected):
    return next((i for i,k in enumerate(ids,1) if k in expected), None)


def summarize(rows):
    ranks = [r['rank'] for r in rows]
    times = sorted(r['ms'] for r in rows)
    counts = {}
    for row in rows:
        key = row['rerank']['state'] + '/' + row['rerank']['reason']
        counts[key] = counts.get(key,0)+1
    n = len(rows)
    return {**{f'hit@{k}':sum(r is not None and r<=k for r in ranks)/n for k in (1,3,5,8)},
            'mrr':sum(1/r for r in ranks if r)/n,
            'p50_ms':times[len(times)//2], 'p95_ms':times[min(n-1,int(n*.95))],
            'reranker_states':counts}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original',type=Path,required=True)
    parser.add_argument('--corpus',type=Path,required=True)
    parser.add_argument('--models-dir',type=Path,required=True)
    parser.add_argument('--cases',type=Path,default=ROOT/'evals/invest_rebuild.json')
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--baseline',type=Path,help='Reuse an archived original_400 baseline; never its timings as a simultaneous comparison.')
    args=parser.parse_args()
    if args.output_dir.exists():parser.error('Use a new evaluation directory')
    args.output_dir.mkdir(parents=True)
    protected=[ROOT/'gianna/services'/f'{name}.py' for name in
               ('agent','prompts','writing','retrieval','reranking','neural','settings')]
    protected += [ROOT/'gianna/chunking.py',Path(__file__),args.cases,args.original,args.corpus]
    fingerprints={str(p.resolve()):sha(p) for p in protected}
    for path in protected:
        if path.suffix=='.py':
            (args.output_dir/(path.stem+'-'+sha(path)+'.py')).write_bytes(path.read_bytes())
    def frozen():
        if any(sha(Path(p))!=s for p,s in fingerprints.items()):raise RuntimeError('Source changed during evaluation')
    class PreparedConfig(Config):
        @property
        def model_dir(self):return args.models_dir.resolve()
    cfg=PreparedConfig.from_env({'data_dir':args.output_dir.resolve()/'runtime',
        'secret_key':secrets.token_urlsafe(48),'encryption_key':Fernet.generate_key().decode(),
        'worker_enabled':False,'embedding_threads':2,'public_origins':('http://localhost',),
        'trusted_hosts':('localhost','127.0.0.1'),'max_concurrent_chat':3},
        environ={'FLASK_ENV':'testing','DATABASE_URL':''})
    app=create_app(cfg)
    logging.disable(logging.INFO)
    services=app.extensions['gianna']
    settings=Settings()
    cases=json.loads(args.cases.read_text(encoding='utf8'))
    state={'scope':'isolated_real_onnx_lancedb_retrieval','provider_calls':0,'production_changed':False,
           'sql_backend':'SQLite evaluation fixture only; application MariaDB untouched',
           'original_sha256':sha(args.original),'corpus_sha256':sha(args.corpus),
           'cases_sha256':sha(args.cases),'source_sha256':fingerprints,'versions':{},
           'phases':{},'onnx_threads':2,'os_cpu_limit_enforced':False,
           'independent_blind_test':False,'answer_quality_evaluated':False}
    def save():
        (args.output_dir/'retrieval.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    save()
    try:
        baseline=None
        if args.baseline:
            baseline=json.loads(args.baseline.read_text(encoding='utf8'))
            if baseline['original_sha256']!=state['original_sha256'] or baseline['cases_sha256']!=state['cases_sha256']:
                raise ValueError('Archived baseline uses different source data or questions')
            state['phases']['original_400']=baseline['phases']['original_400']
            state['archived_baseline']={'sha256':sha(args.baseline),'same_time_measurement':False}
        for label,path in [('original',args.original),('new',args.corpus)]:
            if label=='original' and baseline is not None:continue
            frozen()
            corpus=load_corpus(path)
            public={r.id for r in corpus.records if r.audience=='public' and r.enabled}
            for case in cases:
                key='old_any' if label=='original' else 'new_any'
                if not public.intersection(case[key]):
                    state.setdefault('unscorable_expected_ids',[]).append({'corpus':label,'case':case['id']})
            base=services.knowledge.import_corpus(corpus,'Isolated '+label,None)
            services.knowledge.approve_public(base,None)
            job,version=services.knowledge.enqueue_build(base,settings,None)
            print(json.dumps({'stage':'building','corpus':label,'public':len(public)}),flush=True)
            claimed=services.jobs.claim()
            if not claimed or claimed['id']!=job:raise RuntimeError('Unexpected isolated queue state')
            services.jobs.execute_job(claimed)
            status=services.db.one('SELECT status,error_code FROM jobs WHERE id=?',(job,))
            if status['status']!='done':raise RuntimeError('Isolated build failed: '+str(status['error_code']))
            state['versions'][label]=version
            state.setdefault('public_counts',{})[label]=len(public)
            save()
        retriever=services.rag.retriever
        def search(case,label,budget):
            frozen()
            opts={} if budget is None else {'rerank_budget':RerankBudget(budget)}
            started=time.perf_counter()
            cards,trace=retriever.search(case['q'],settings,state['versions'][label],limit=8,**opts)
            ids=[c['record_id'] for c in cards]
            return {'id':case['id'],'split':case['split'],'query':case['q'],'ids':ids,
                    'rank':rank(ids,case['old_any' if label=='original' else 'new_any']),
                    'ms':round((time.perf_counter()-started)*1000,2),'rerank':trace['rerank']}
        for phase,label,budget in [('original_400','original',400),('new_hybrid','new',None),
                                   ('new_400','new',400),('new_1500','new',1500),('new_cached','new',1500)]:
            if label=='original' and baseline is not None:continue
            if phase!='new_cached':retriever.clear_rerank_cache()
            rows=[]
            for case in cases:rows.append(search(case,label,budget))
            state['phases'][phase]={'summary':summarize(rows),'rows':rows,
                'additional':summarize([r for r in rows if r['split']=='additional'])}
            save();print(json.dumps({'stage':phase,**state['phases'][phase]['summary']}),flush=True)
        retriever.clear_rerank_cache()
        with ThreadPoolExecutor(max_workers=3) as pool:
            rows=list(pool.map(lambda c:search(c,'new',1500),cases[8:17]))
        state['phases']['concurrent_three']={'summary':summarize(rows),'rows':rows}
        state['completed']=True
        save()
        print(json.dumps({'stage':'finished','report':str(args.output_dir/'retrieval.json')}),flush=True)
    except Exception as exc:
        state['completed']=False;state['error_type']=type(exc).__name__;save()
        raise


if __name__=='__main__':main()
