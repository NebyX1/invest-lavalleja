#!/usr/bin/env python3
"""Static preview of actual Jinja templates without claiming a running Flask service."""
from pathlib import Path
from types import SimpleNamespace
from collections import Counter
import json
import shutil
import sys
from urllib.parse import urlencode
from jinja2 import Environment,FileSystemLoader,select_autoescape,StrictUndefined
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gianna.corpus import Corpus
from gianna.services.settings import Settings
root=Path(__file__).resolve().parents[1];out=root/'reports/preview';out.mkdir(parents=True,exist_ok=True)
shutil.copytree(root/'gianna/static',out/'static',dirs_exist_ok=True)
c=Corpus.model_validate_json((root/'knowledge/invest_lavalleja_2026.gianna.json').read_text())
settings=Settings();user={'id':'preview','name':'Administración','role':'owner','mfa_method':'totp','must_change_password':False,'session_hash':'preview'}
base={'id':'preview-base','name':c.document.title,'revision':1,'status':'draft','created_at':0,'records_count':len(c.records)}
rows=[{'id':i+1,'record_key':r.id,**r.model_dump(),'approved':0} for i,r in enumerate(c.records)]
counts={'total':len(c.records),'public':sum(r.audience=='public' for r in c.records),'internal':sum(r.audience=='internal' for r in c.records),'pending':sum(r.audience=='public' for r in c.records)}
stats={'days':7,'total':0,'sessions':0,'p50_ms':None,'p95_ms':None,'answered':0,'unanswered':0,'positive_feedback':0,'negative_feedback':0,'prompt_tokens':0,'output_tokens':0,'token_reporting_queries':0,'topics':{},'daily':{},'statuses':{},'sources':{}}
baseurls={'admin.dashboard':'dashboard.html','admin.bases':'bases.html','admin.base_detail':'base_detail.html','admin.settings_page':'settings.html','admin.lab':'lab.html','admin.analytics':'analytics.html','auth.security_page':'security.html','admin.jobs':'jobs.html','admin.audit':'audit.html','admin.users':'users.html','auth.login':'login.html','public.chat_page':'chat.html'}
def url_for(endpoint,**kwargs):
    if endpoint=='static':return '/static/'+kwargs['filename']
    return '/'+baseurls.get(endpoint,endpoint.replace('.','-')+'.html')+('?' + urlencode(kwargs) if kwargs else '')
env=Environment(loader=FileSystemLoader(root/'gianna/templates'),autoescape=select_autoescape(['html']),undefined=StrictUndefined)
env.filters['when']=lambda x:'Sin actividad todavía' if not x else 'Vista previa'
env.filters['pretty']=lambda x:json.dumps(json.loads(x) if isinstance(x,str) else x,ensure_ascii=False,indent=2)
env.globals.update(url_for=url_for,csrf_token=lambda:'STATIC-PREVIEW-NOT-A-SESSION',get_flashed_messages=lambda **kw:[('info','Vista estática de las plantillas reales. No conectada a Flask, Qdrant ni Ollama.')])
ctx=dict(user=user,settings=settings,version='1.0.0-rc1',g=SimpleNamespace(request_id='preview'),request=SimpleNamespace(endpoint='admin.dashboard'),
    active=None,stats=stats,counts={'bases':1,'records':len(c.records),'chunks':0},jobs=[],engine_ready=False,cloud_ready=False)
params={
 'dashboard.html':{},'bases.html':dict(bases=[base],max_mb=12),
 'base_detail.html':dict(base=base,records=rows[:30],topics=[{'topic':k,'n':v} for k,v in Counter(r.topic for r in c.records).items()],counts=counts,versions=[],sources=[s.model_dump() for s in c.sources],page=1,pages=10,count=len(c.records),filters=dict(q='',topic='',audience='',review=''),report=c.conversion_report),
 'record_edit.html':dict(base=base,record=next(r for r in c.records if r.id=='O05').model_dump(),row={'id':1},sources=[{'source_key':s.id} for s in c.sources]),
 'source_edit.html':dict(base=base,source=c.sources[0].model_dump()),
 'version_detail.html':dict(v={'id':'preview-version','name':base['name'],'base_id':base['id'],'revision':1,'status':'queued','chunk_count':0,'published_at':None},profile={'model':'E5-small','state':'No indexado en la vista estática'},report={},chunks=[],topics=[],page=1,pages=1,q='',topic='',count=0),
 'job_detail.html':dict(job={'id':'preview-job','kind':'build','message':'Vista de trabajo sin ejecución','status':'queued','total':0,'progress':0,'error':None,'base_id':'preview-base','version_id':None,'result_json':None}),
 'jobs.html':{},'lab.html':dict(result=None,question='',versions=[],selected=''),
 'settings.html':dict(cfg=SimpleNamespace(ollama_api_key=''),values=settings.model_dump()),
 'security.html':dict(sessions=[]),'users.html':dict(rows=[],temporary=None,smtp=False),
 'analytics.html':{},'audit.html':dict(rows=[]),'login.html':dict(user=None),'mfa.html':dict(user=None,kind='totp',secret=None,qr=None),
 'recovery.html':dict(user=None,codes=['VISTA-PREVIA-SIN-CODIGOS-REALES']),
 'error.html':dict(status=403,message='Ejemplo de mensaje de error, sin operación real.'),'chat.html':{}}
for template in env.list_templates():env.get_template(template)
for name,extra in params.items():
    combined={**ctx,**extra};combined['request']=SimpleNamespace(endpoint=next((k for k,v in baseurls.items() if v==name),'admin.dashboard'))
    (out/name).write_text(env.get_template(name).render(**combined),encoding='utf8')
(root/'reports/templates.json').write_text(json.dumps({'engine':'Jinja2 StrictUndefined','parsed':len(env.list_templates()),'rendered':len(params),'flask_server_tested':False},indent=2),encoding='utf8')
print(f'{len(env.list_templates())} plantillas compiladas; {len(params)} pantallas renderizadas con StrictUndefined.')
