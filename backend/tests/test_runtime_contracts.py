import json
import httpx
import pytest
from gianna.services.runtime import Qdrant,Ollama,thinking_mode
from gianna.services.harness import AgentHarness,parse_proposed
from gianna.services.settings import Settings
from gianna.services.response_validation import remove_uncited_lines,validate_citation_syntax
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


def test_empty_cloud_content_retries_once_without_ignoring_configured_cap(cfg):
    captured=[]
    def handler(request):
        captured.append(json.loads(request.content))
        if len(captured)==1:return httpx.Response(200,json={'message':{'content':'','thinking':'internal only'},'done_reason':'length'})
        return httpx.Response(200,json={'message':{'content':'Respuesta útil'}})
    cloud=Ollama(cfg,httpx.Client(base_url='https://ollama.test',transport=httpx.MockTransport(handler)))
    answer,_=cloud.chat([{'role':'user','content':'Hola'}],Settings(model='deepseek-v4.1-flash',max_output_tokens=200),think=False)
    assert answer=='Respuesta útil' and len(captured)==2
    assert captured[1]['options']['num_predict']==200
    assert captured[1]['think'] is False


def test_citation_guard_is_structural_not_truth_estimator():
    assert validate_citation_syntax('Orientación [C1]',['C1'])
    assert not validate_citation_syntax('Inventado [C99]',['C1'])
    assert not validate_citation_syntax('Sin referencias',['C1'])
    assert not validate_citation_syntax('Enlace https://evil.test [C1]',['C1'])
    assert validate_citation_syntax('Una afirmación falsa [C1]',['C1']) # explicit limitation, not concealed
    assert not validate_citation_syntax('Dato citado [C1].\n\nOtra afirmación sin respaldo.',['C1'])
    assert not validate_citation_syntax('Dato citado [C1].\n\n1. Paso sin cita\n2. Otro paso [C1]',['C1'])
    assert validate_citation_syntax('Dato citado [C1].\n\n¿Qué actividad querés priorizar?',['C1'])
    assert validate_citation_syntax('## Opciones\n\n**Poscosecha y medición**\n\nComparación respaldada [C1, C2]',['C1','C2'])
    assert not validate_citation_syntax('¿Afirmación retórica?\n\nComparación respaldada [C1]',['C1'])
    assert validate_citation_syntax('Opciones para explorar:\n\nComparación respaldada [C1]\n\nPara afinar, ¿qué priorizás?',['C1'])
    assert not validate_citation_syntax('Afirmación factual sin respaldo.\n\nComparación respaldada [C1]',['C1'])
    cleaned,removed=remove_uncited_lines('Opciones:\n\nAfirmación sin cita.\n- Evidencia válida [C1]\n\n¿En cuál querés profundizar?')
    assert removed==[3] and 'Afirmación sin cita' not in cleaned and '[C1]' in cleaned


def test_router_suggestions_cannot_broaden_grounded_entity_scope():
    proposed=parse_proposed('{"action":"rag","intent":"requirements","zones":["Z1"],"opportunity_ids":["O01"]}')
    plan=AgentHarness.retrieval_plan('¿Y qué debería validar?',[
        {'role':'user','content':'Quiero invertir en el norte de Lavalleja.'},
        {'role':'assistant','content':'Opciones respaldadas. [C1]','mode':'knowledge',
         'state':{'zones':['Z5','Z6'],'opportunity_ids':['O03','O12']}},
    ],proposed)
    assert plan.zones==('Z5','Z6') and plan.opportunity_ids==('O03','O12')


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
