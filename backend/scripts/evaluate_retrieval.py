"""Reproducible public retrieval checks. Never calls the generation provider."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import time
from gianna import create_app
from gianna.services.settings import get_settings


def evaluate(cases, services):
    s=services;s.embeddings.load();settings=get_settings(s.db,s.cfg)
    model_checks={}
    if hasattr(s.embeddings,'rerank') and s.embeddings.profile.get('engine'):
        samples=['Texto sobre medidas de seguridad de incendios y verificación de un local.',
                 'Texto sobre cosechas de trigo, granos y rendimiento de una campaña.']
        vectors,_=s.embeddings.documents(samples,samples)
        scores=s.embeddings.rerank('Verificar seguridad de incendios en un local',samples)
        model_checks={'dimensions':len(vectors[0]),
            'normalized':all(abs(math.sqrt(sum(value*value for value in v))-1)<1e-5 for v in vectors),
            'relevant_pair_first':scores[0]>scores[1],'rerank_scores':scores}
        if model_checks['dimensions']!=384 or not model_checks['normalized'] or not model_checks['relevant_pair_first']:
            raise RuntimeError('Falló la comprobación real de los modelos.')
    active=s.knowledge.active()
    results=[]
    for case in cases:
        start=time.perf_counter()
        plan=s.rag.harness.retrieval_plan(case['question'],[])
        selected,_,trace=s.rag.retrieve_plan(plan,settings,active['id'])
        ids=[hit['record_id'] for hit in selected]
        covered=[bool(set(group)&set(ids)) for group in case['groups']]
        results.append({'id':case['id'],'question':case['question'],'record_ids':ids,
            'groups_covered':covered,'pass':all(covered),'ms':round((time.perf_counter()-start)*1000,2),
            'trace':trace})
        print(json.dumps({'case':case['id'],'pass':all(covered),'record_ids':ids},ensure_ascii=False),flush=True)
    service_dir=Path(__file__).resolve().parents[1]/'gianna'/'services'
    source_hashes={name:hashlib.sha256((service_dir/name).read_bytes()).hexdigest()
        for name in ('neural.py','vector_store.py','rag.py','planning.py','harness.py','evidence_guard.py','response_policy.py')}
    return {'version_id':active['id'],'profile':s.embeddings.profile,'model_checks':model_checks,'source_hashes':source_hashes,
        'passed':sum(r['pass'] for r in results),'total':len(results),
        'group_coverage':sum(sum(r['groups_covered']) for r in results)/sum(len(r['groups_covered']) for r in results),
        'scope':'Public corpus retrieval/context coverage; not a factual generation benchmark.',
        'results':results}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=evaluate(json.loads(args.cases.read_text(encoding='utf-8')),create_app().extensions['gianna'])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:report[key] for key in ('version_id','passed','total','group_coverage')},ensure_ascii=False))
