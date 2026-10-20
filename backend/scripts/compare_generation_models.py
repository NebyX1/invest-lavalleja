"""Opt-in, small paired public-chat comparison; not an independent benchmark."""
import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean,median
from gianna.config import Config
from gianna.db import Database
from gianna.services.runtime import Ollama,thinking_mode
from gianna.services.settings import get_settings,save_settings
from scripts.evaluate_public_chat import evaluate


def summarize(report):
    results=report['results']
    answered=[r for r in results if r['status']=='answered']
    def average(key):
        values=[r['timings'][key] for r in answered if key in r.get('timings',{})]
        return round(mean(values),2) if values else None
    times=[r['total_ms'] for r in answered]
    return {'answered':len(answered),'total':len(results),'checks_passed':report['passed'],
        'mean_http_ms':round(mean(times),2) if times else None,
        'median_http_ms':round(median(times),2) if times else None,
        'mean_generation_ms':average('generation_ms'),'mean_retrieval_ms':average('retrieval_ms'),
        'repairs':sum(r.get('trace',{}).get('repair_attempted') is True for r in results),
        'output_tokens_total':sum(r.get('usage',{}).get('output_tokens') or 0 for r in results)}


def run(base,origin,output):
    cfg=Config.from_env()
    if not cfg.human_test_mode or cfg.production:
        raise RuntimeError('Comparación permitida solo en la pila local de prueba humana.')
    db=Database(cfg.data_dir/'gianna.sqlite3');original=get_settings(db,cfg)
    active=db.setting('active_knowledge')
    client=Ollama(cfg);catalogue=client.models()
    models=('beam','deepseek-v4.1-flash:1017')
    if not set(models)<=set(catalogue):raise RuntimeError('Falta un modelo solicitado en el catálogo real.')
    source_root=Path(__file__).resolve().parents[1]/'gianna'/'services'
    hashes={name:hashlib.sha256((source_root/name).read_bytes()).hexdigest() for name in (
        'harness.py','rag.py','planning.py','response_policy.py','response_validation.py','runtime.py')}
    paired={'scope':'One fresh three-turn public API session per model, in listed order. Synthetic known cases; '
                    'not factual certification or a statistically controlled benchmark. Cache/order/load can affect latency.',
        'parameters':{'temperature':0.1,'max_output_tokens':4096,'scenario':'locations'},
        'source_hashes':hashes,'models':[]}
    output.parent.mkdir(parents=True,exist_ok=True)
    try:
        for model in models:
            metadata=client.client.post('/api/show',json={'model':model});metadata.raise_for_status()
            supported=metadata.json().get('thinking',{}).get('values',[])
            if thinking_mode(model)!='low' or 'low' not in supported:
                raise RuntimeError('El perfil no usa el nivel low confirmado por el proveedor.')
            settings=save_settings(db,cfg,original.model_copy(update={
                'model':model,'temperature':0.1,'max_output_tokens':4096}).model_dump(),'paired-model-trial')
            print(json.dumps({'starting_model':model,'think':'low','tokens':settings.max_output_tokens}),flush=True)
            report=evaluate(base,origin,'locations')
            if get_settings(db,cfg)!=settings:raise RuntimeError('Los ajustes cambiaron durante la corrida.')
            for result in report['results']:
                if not result.get('id'):continue
                row=db.one('SELECT version_id,prompt_tokens,output_tokens,retrieval_trace_json FROM queries WHERE id=?',(result['id'],))
                trace=json.loads(row['retrieval_trace_json']);validation=trace.get('response_validation',{})
                result['version_id']=row['version_id']
                result['usage']={key:row[key] for key in ('prompt_tokens','output_tokens')}
                result['trace']={'intent':trace.get('intent'),'activity':trace.get('activity'),
                    'inherited_context':trace.get('inherited_context'),
                    'selected_record_ids':trace.get('selected_record_ids',[]),
                    'coverage':trace.get('coverage'),'repair_attempted':validation.get('repair_attempted'),
                    'removed_uncited_lines':validation.get('removed_uncited_line_numbers',[]),
                    'removed_attribution_paragraphs':validation.get('removed_attribution_paragraphs',[])}
            entry={'model':model,'think':'low','summary':summarize(report),'report':report}
            paired['models'].append(entry)
            output.write_text(json.dumps(paired,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'model':model,'summary':entry['summary']},ensure_ascii=False),flush=True)
        pairs=zip(*(entry['report']['results'] for entry in paired['models']),strict=True)
        paired['same_context_ids_by_turn']=[
            bool(a.get('trace') and b.get('trace')) and
            a['trace']['selected_record_ids']==b['trace']['selected_record_ids'] for a,b in pairs]
        if not paired['models'][-1]['summary']['answered']:
            save_settings(db,cfg,original.model_dump(),'restore-after-unusable-trial')
        paired['final_model']=get_settings(db,cfg).model
        output.write_text(json.dumps(paired,ensure_ascii=False,indent=2),encoding='utf-8')
        return paired
    except Exception:
        save_settings(db,cfg,original.model_dump(),'restore-interrupted-comparison')
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-provider',action='store_true',required=True)
    parser.add_argument('--base',default='http://127.0.0.1:8000')
    parser.add_argument('--origin',default='http://127.0.0.1:4321')
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();run(args.base.rstrip('/'),args.origin,args.output)
