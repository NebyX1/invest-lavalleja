"""Information flow protocol with explicit scripted tools; no quality benchmark."""
import json

import pytest

from gianna.errors import DomainError
from gianna.services.agent import Agent
from gianna.services.settings import Settings
from test_agent import ScriptedOllama, semantic_assessment


CARD = {'record_id':'public-profile', 'title':'Perfil del lugar', 'topic':'Territorio', 'zones':[],
        'evidence_type':'documented_in_source', 'text':'El lugar está conectado por la ruta principal.',
        'conditions':[], 'information_view':{'text':'El lugar está conectado por la ruta principal.', 'kind':'descriptive'},
        'documentary':{'text':'El lugar está conectado por la ruta principal. El autor indica validar contratos.',
                       'conditions':['Condición del procedimiento.']}}


def tool(name, args): return ('', [{'function':{'name':name,'arguments':args}}])


def interpret(query='perfil territorial', kind='description'):
    return tool('interpretar_pedido', {'asks':[{'text':'Información sobre el lugar','kind':kind}], 'query':query})


def draft(text='El lugar tiene conexión por una ruta principal.', quote=CARD['text']):
    return tool('redactar_informacion', {'statements':[{'ask':0,'paragraph':0,'kind':'fact', 'text':text,
                                                     'support':[{'source':1,'quote':quote}]}]})


def review(**changes):
    return tool('comprobar_afirmaciones', {'checks':[{'statement':0,'function':'information','supported':True,'answers_ask':True,
                   'informative':True,'material_conditions_preserved':True} | changes], 'missing_asks':[]})


class Retriever:
    def __init__(self, model): self.searches=[]; self.model=model
    def search(self, query, settings, version, **kw):
        assert self.model.sequence[0] == 'safety'
        self.searches.append((query, kw))
        return [dict(CARD)], {'ms':1,'rerank':{'state':'applied'}, 'query':query}
    def outline(self, version): return {}, [{'id':'public-profile','title':'Perfil del lugar','topic':'Territorio'}]
    def get(self, ref, version): return dict(CARD) if ref == CARD['record_id'] else None


def run(*responses, question='Contame sobre el lugar', history=None):
    model = ScriptedOllama(*responses)
    retriever = Retriever(model)
    result = Agent(retriever, model).run(question, Settings(model='scripted'), history or [], 'test-version')
    return result, model, retriever


def test_intent_precedes_sources_and_every_knowledge_answer_passes_review():
    result, model, retriever = run(interpret(), draft(), review())
    assert model.sequence == ['safety','business','business','business']
    payload = json.loads(model.calls[0]['messages'][1]['content'])
    assert set(payload) == {'question','history'} and CARD['text'] not in json.dumps(model.calls[0])
    assert result.status == 'answered' and result.trace['writing_verified']
    assert result.answer == 'El lugar tiene conexión por una ruta principal. [1]'
    assert retriever.searches[0][0] == 'perfil territorial'


def test_rejected_advice_is_rewritten_whole_not_trimmed_or_returned():
    bad = 'Antes de invertir tenés que investigar.'
    result, model, _ = run(interpret(), draft(bad), review(informative=False), draft(), review())
    assert bad not in result.answer and result.trace['writing_plans'] == 2
    payload = json.loads(model.calls[3]['messages'][1]['content'])
    assert payload['correction']['review']['checks'][0]['informative'] is False
    assert bad in json.dumps(payload['previous_attempt'], ensure_ascii=False)
    assert result.trace['writing_rejections'] == [{'phase':'review','code':'semantic_rejection'}]


def test_bad_quote_regenerates_before_semantic_review():
    result, model, _ = run(interpret(), draft(quote='Un fragmento inventado.'), draft(), review())
    assert result.trace['writing_plans'] == 2
    correction = json.loads(model.calls[2]['messages'][1]['content'])['correction']
    assert correction == {'structural_error':'quote_not_in_source','statement':0,'source':1}


def test_exhausted_review_never_delivers_the_rejected_plan():
    bad = 'Te recomiendo otro negocio.'
    result, _, _ = run(interpret(), draft(bad), review(informative=False),
                       draft(bad), review(informative=False), draft(bad), review(informative=False))
    assert result.status == 'degraded' and bad not in result.answer
    assert result.trace['writing_error'] == 'answer_not_verified'


def test_followup_and_user_correction_reach_intent_and_writer_unchanged():
    history = [{'role':'user','content':'Quiero un boliche en el norte.'},
               {'role':'assistant','content':'Te recomiendo otra actividad.'},
               {'role':'user','content':'No quiero recomendaciones, quiero información territorial.'}]
    _, model, _ = run(interpret(), draft(), review(), question='¿Y en esa localidad?', history=history)
    for call in model.calls[:2]:
        payload = json.loads(call['messages'][1]['content'])
        assert payload['history'] == history and payload['question'] == '¿Y en esa localidad?'


@pytest.mark.parametrize('kind, original', [('description',False),('fact',True),('procedure',True),('methodology',True)])
def test_documentary_access_depends_on_pre_evidence_request(kind, original):
    result, model, _ = run(interpret(kind=kind), draft(), review())
    payload = json.loads(model.calls[1]['messages'][1]['content'])
    assert ('validar contratos' in payload['evidence_text']) is original
    assert result.trace['intent_kinds'] == [kind]


def test_read_only_discovery_keeps_one_rerank_budget_for_all_searches():
    searches = tool('buscar_en_la_guia', {'consulta':'otra consulta'})
    result, model, retriever = run(interpret(), searches, draft(), review())
    assert len(retriever.searches) == 2 and result.trace['steps'] == 1
    assert retriever.searches[0][1]['rerank_budget'] is retriever.searches[1][1]['rerank_budget']
    assert result.status == 'answered'


def test_invalid_intent_cannot_reach_retrieval():
    model = ScriptedOllama('prosa sin contrato', 'otra prosa')
    retriever = Retriever(model)
    with pytest.raises(DomainError) as exc:
        Agent(retriever,model).run('Pregunta válida',Settings(model='scripted'),[],'version')
    assert exc.value.code == 'answer_not_verified' and retriever.searches == []


def test_reviewer_cannot_accept_an_unrequested_caveat_with_other_checks_true():
    result, _, _ = run(interpret(), draft('La guía no garantiza resultados.'),
                       review(function='unrequested_caveat'), draft(), review())
    assert result.status == 'answered' and 'garantiza' not in result.answer
    assert result.trace['writing_plans'] == 2


def test_evidence_limit_does_not_promote_a_skipped_original_into_writer_context(monkeypatch):
    from gianna.services.agent import Evidence
    monkeypatch.setattr('gianna.services.agent.MAX_EVIDENCE_CHARS', 180)
    evidence=Evidence();evidence.render([CARD])
    assert len(evidence.for_writing()) <= 180
    evidence.render([CARD | {'documentary':{'text':'PRIVATE-TO-THIS-READ '*100,'conditions':[]}}],
                    force=True,documentary=True)
    assert 'PRIVATE-TO-THIS-READ' not in evidence.for_writing()
    assert evidence.cards[1]['text'] == CARD['text']
