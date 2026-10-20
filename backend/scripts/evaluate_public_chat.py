"""Opt-in public API dialogue regression using the configured provider."""
import argparse
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.request
from gianna.services.conversation import fold


INFORMATION_CASES=[
    'Quiero información sobre eficiencia energética en Lavalleja.',
    '¿En qué zonas la menciona la guía?',
    'En dónde puedo invertir en energías renovables en Lavalleja?',
    '¿Cuáles son los padrones disponibles para instalar un parque eólico?',
    'Quiero información sobre poscosecha en José Pedro Varela.',
    '¿Me asegurás una rentabilidad del 20%?',
]


def information_checks(index,reply):
    text=fold(reply['answer']);ids={c['record_id'] for c in reply['citations']}
    # A separate, server-verified topic menu is allowed on missing information;
    # it must not be mistaken for a fabricated answer about renewable sites.
    requested_answer=fold(reply['answer'].split('\n\nSí puedo darte información de la guía sobre otros temas:',1)[0])
    checks={'valid_status':reply['status'] in {'answered','insufficient_evidence'},
        'brief':len(reply['answer'].split())<=160,
        'not_adviser':not bool(re.search(r'\b(?:recomiend\w*|recomendaria|miraria|evaluaria|empezaria|arrancaria|priorizaria)\b|te propongo|hipotesis mia',text)),
        'no_unsolicited_question':'?' not in reply['answer'],
        'no_private_state':'_conversation_state' not in reply}
    if index==0:checks.update(energy_source='O09' in ids,answered=reply['status']=='answered')
    if index==1:checks.update(energy_source='O09' in ids,documented_zones=all(z in text for z in ('minas','solis','varela')))
    if index in {2,3,5}:
        checks['explicit_limit']=bool(re.search(r'no (?:cuento|dispongo|tengo|encontre|contiene|hay)|no esta documentad|no se (?:identifica|detalla|indica|documenta)',text))
    if index in {2,3}:checks['no_tourism_detour']=not any(t in requested_answer for t in ('villa serrana','hospitalidad','piloto a 90'))
    if index==3:checks.update(abstains=reply['status']=='insufficient_evidence',no_unrelated_sources=not ids)
    if index==4:checks.update(grain_source='O03' in ids,no_other_business=not bool(ids&{'O09','O16'}))
    return checks


def evaluate(base,origin,scenario='permits'):
    headers={'Origin':origin,'Content-Type':'application/json'}
    def call(path,body=None,method=None):
        request=urllib.request.Request(base+path,headers=headers,
            data=json.dumps(body).encode() if body is not None else None,method=method)
        with urllib.request.urlopen(request,timeout=180) as response:return json.load(response)
    config=call('/api/config')
    if not config['available']:raise RuntimeError('Esperá a que la base y los modelos estén listos.')
    challenge=call('/api/captcha')
    answer=sum(map(int,re.findall(r'\d+',challenge['question'])))
    session=call('/api/sessions',{'captcha_id':challenge['id'],'captcha_answer':str(answer)})
    headers['Authorization']='Bearer '+session['token']
    cases=[
        'Quiero invertir poniendo un boliche, ¿qué debo revisar antes de alquilar?',
        'Me refiero a un local bailable en Minas, ¿qué debo comprobar antes de alquilar?',
    ]
    if scenario=='locations':
        cases=[
            'Quiero estudiar la posibilidad de instalar un boliche, qué me recomendás?',
            'Ok, pero qué lugares me recomendás para ponerlo?',
            'Me refiero a un local bailable en Minas, ¿qué debo comprobar antes de alquilar?',
        ]
    if scenario=='recommendations':
        cases=['Hola','¿Cómo estás?','¿Qué me recomendás para invertir en el norte?',
               'Profundiza con Varela','¿Cómo arranco?']
    if scenario=='information':cases=INFORMATION_CASES
    results=[]
    for index,question in enumerate(cases):
        start=time.perf_counter()
        try:reply=call('/api/chat',{'message':question})
        except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError) as exc:
            failure={'question':question,'status':'error','http_status':getattr(exc,'code',None),
                'checks':{'answered':False},'total_ms':round((time.perf_counter()-start)*1000,2)}
            results.append(failure)
            print(json.dumps({'case':index+1,**failure},ensure_ascii=False),flush=True)
            continue
        record_ids=[citation['record_id'] for citation in reply['citations']]
        text=reply['answer'].lower()
        checks={'answered':reply['status']=='answered','sources':bool(record_ids),
            'fire_source':'s29-01-07' in record_ids,
            'premises_source':bool(set(record_ids)&{'s26-01-03','s29-01-02'}),
            'private_state_absent':'_conversation_state' not in reply,
            'activity_preserved':('bailable' in text),
            'clarification':('bar' in text and '?' in text) if index==0 else '¿con boliche' not in text}
        if scenario=='locations' and index<2:
            territorial_groups=[{'s10-01-01','s09-01-02'},
                                {'s11-02-01','s09-01-03'},
                                {'s12-01-01','s12-02-01','s09-01-04'}]
            checks={key:value for key,value in checks.items() if key not in {'fire_source','premises_source','clarification'}}
            checks.update(territorial_sources=sum(bool(set(record_ids)&group) for group in territorial_groups)>=2,
                named_places=sum(name in text for name in ('minas','solís','villa serrana'))>=2,
                no_sector_reset='contame el rubro' not in text,
                conditional=any(term in text for term in ('hipótesis','investigaría','evaluaría','exploraría','estudiaría')))
        if scenario=='recommendations':
            words=len(reply['answer'].split());normalized=fold(reply['answer'])
            if index<2:
                checks={'conversation':reply['status']=='conversation','no_sources':not record_ids,
                    'brief':words<=55,'no_repeated_mission':index==0 or 'oportunidades zonas sectores' not in normalized}
            else:
                lead=fold(reply['answer'].split('\n\n')[0])
                if reply['answer'].startswith('#'):lead=fold(reply['answer'].split('\n\n')[1])
                checks={'answered':reply['status']=='answered','sources':bool(record_ids),'concise':words<=280,
                    'clear_recommendation':bool(re.search(r'\b(?:recomendaria|empezaria|arrancaria|evaluaria|priorizaria|probaria|comenzaria|miraria|apuntaria)\b|te propongo|me enfocaria|me centraria',lead)),
                    'no_distractors':not bool(set(record_ids)&{'O09','O16'}),'single_question':reply['answer'].count('¿')<=1}
                if index==2:checks['north_choices']={'O03','O12'}<=set(record_ids)
                else:checks['grain_focus']='O03' in record_ids and 'O12' not in record_ids
                if index==4:
                    checks.pop('clear_recommendation')
                    checks['action_first']=bool(re.search(r'\b(?:habl\w*|contact\w*|ped\w*|solicit\w*|acord\w*|consult\w*|identific\w*|obten\w*)\b',lead))
                    checks['short_next_step']=words<=180
        if scenario=='information':checks=information_checks(index,reply)
        results.append({'question':question,'id':reply['id'],'status':reply['status'],
            'answer':reply['answer'],'citation_record_ids':record_ids,'checks':checks,
            'timings':reply.get('timings'),'total_ms':round((time.perf_counter()-start)*1000,2)})
        print(json.dumps({'case':index+1,'status':reply['status'],'checks':checks},ensure_ascii=False),flush=True)
    call('/api/sessions/current',method='DELETE')
    return {'scope':'Public API dialogue regression; observable routing, sources and relevance, not exhaustive factual certification.',
            'passed':sum(all(result['checks'].values()) for result in results),'total':len(results),'results':results}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-provider',action='store_true',required=True,help='Explicitly allow provider calls through the public API.')
    parser.add_argument('--base',default='http://127.0.0.1:8000')
    parser.add_argument('--origin',default='http://127.0.0.1:4321')
    parser.add_argument('--scenario',choices=['permits','locations','recommendations','information'],default='permits')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();report=evaluate(args.base.rstrip('/'),args.origin,args.scenario)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'total':report['total']}))
    if report['passed']!=report['total']:raise SystemExit(1)
