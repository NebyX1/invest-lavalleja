import json
import httpx
import pytest
from gianna.services.runtime import Qdrant,Ollama,thinking_mode
from gianna.services.harness import parse_proposed
from gianna.services.settings import Settings
from gianna.services.rag import validate_answer
from gianna.errors import DomainError


def test_qdrant_hybrid_request_has_public_filter(cfg):
    requests=[]
    def handler(request):
        requests.append(json.loads(request.content));return httpx.Response(200,json={'result':{'points':[]}})
    q=Qdrant(cfg,httpx.Client(base_url='https://q.test',transport=httpx.MockTransport(handler)))
    assert q.search('gianna_test',[0.0]*384,{'indices':[1],'values':[1.]})==[]
    body=requests[0];assert body['query']=={'fusion':'rrf'}
    assert all(p['filter']['must'][0]['match']['value']=='public' for p in body['prefetch'])
    assert {p['using'] for p in body['prefetch']}=={'dense','bm25'}


def test_cloud_contract_no_unsupported_schema(cfg):
    captured=[]
    def handler(request):
        captured.append(json.loads(request.content));return httpx.Response(200,json={'message':{'content':'Respuesta [C1]'},'prompt_eval_count':123,'eval_count':20})
    cloud=Ollama(cfg,httpx.Client(base_url='https://ollama.test',transport=httpx.MockTransport(handler)))
    text,usage=cloud.chat([{'role':'user','content':'Pregunta'}],Settings(model='example'))
    assert text=='Respuesta [C1]' and usage['output_tokens']==20
    assert captured[0]['stream'] is False and 'format' not in captured[0]


def test_cloud_router_can_request_low_thinking_without_schema(cfg):
    captured=[]
    def handler(request):
        captured.append(json.loads(request.content));return httpx.Response(200,json={'message':{'content':'{"action":"rag","reply":""}'}})
    cloud=Ollama(cfg,httpx.Client(base_url='https://ollama.test',transport=httpx.MockTransport(handler)))
    text,usage=cloud.chat([{'role':'user','content':'Clasificá'}],Settings(model='example'),think='low')
    assert json.loads(text)['action']=='rag'
    assert captured[0]['think']=='low' and 'format' not in captured[0]


def test_deepseek_thinking_off_and_wrapped_router_json():
    assert thinking_mode('deepseek-v4.1-flash') is False
    assert thinking_mode('gpt-oss:20b')=='low'
    assert parse_proposed('```json\n{"action":"chat"}\n```').action=='chat'
    assert parse_proposed('Ruta elegida: {"action":"rag"}').action=='rag'
    with pytest.raises(ValueError):parse_proposed('No sé qué hacer')


def test_empty_cloud_content_retries_once_with_larger_cap(cfg):
    captured=[]
    def handler(request):
        captured.append(json.loads(request.content))
        if len(captured)==1:return httpx.Response(200,json={'message':{'content':'','thinking':'internal only'},'done_reason':'length'})
        return httpx.Response(200,json={'message':{'content':'Respuesta útil'}})
    cloud=Ollama(cfg,httpx.Client(base_url='https://ollama.test',transport=httpx.MockTransport(handler)))
    answer,_=cloud.chat([{'role':'user','content':'Hola'}],Settings(model='deepseek-v4.1-flash',max_output_tokens=200),think=False)
    assert answer=='Respuesta útil' and len(captured)==2
    assert captured[1]['options']['num_predict']>=1000
    assert captured[1]['think'] is False


def test_citation_guard_is_structural_not_truth_estimator():
    assert validate_answer('Orientación [C1]',['C1'])
    assert not validate_answer('Inventado [C99]',['C1'])
    assert not validate_answer('Sin referencias',['C1'])
    assert not validate_answer('Enlace https://evil.test [C1]',['C1'])
    assert validate_answer('Una afirmación falsa [C1]',['C1']) # explicit limitation, not concealed
    assert not validate_answer('Dato citado [C1].\n\nOtra afirmación sin respaldo.',['C1'])
    assert not validate_answer('Dato citado [C1].\n\n1. Paso sin cita\n2. Otro paso [C1]',['C1'])
    assert validate_answer('Dato citado [C1].\n\nPróximo paso respaldado [C1].',['C1'])


def test_provider_error_does_not_expose_body(cfg):
    cloud=Ollama(cfg,httpx.Client(base_url='https://ollama.test',transport=httpx.MockTransport(lambda r:httpx.Response(500,text='private-provider-error'))))
    with pytest.raises(DomainError) as exc:cloud.chat([],Settings(model='example'))
    assert 'private-provider-error' not in str(exc.value)


def test_transient_503_retries_once_without_exposing_provider_body(cfg):
    calls=[]
    def handler(request):
        calls.append(request)
        if len(calls)==1:return httpx.Response(503,text='private-provider-error')
        return httpx.Response(200,json={'message':{'content':'Respuesta [C1]'}})
    cloud=Ollama(cfg,httpx.Client(base_url='https://ollama.test',transport=httpx.MockTransport(handler)))
    text,usage=cloud.chat([{'role':'user','content':'Pregunta'}],Settings(model='example'))
    assert text=='Respuesta [C1]' and len(calls)==2
