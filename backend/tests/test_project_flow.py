"""Dialogue/selection contracts, not a factual benchmark of model answers."""
import pytest
from gianna.errors import DomainError
from gianna.services.harness import AgentHarness,ProposedDecision
from gianna.services.project_memory import state_for,unpack_session
from gianna.services.response_validation import evidence_coverage
from gianna.services.territory import location_candidates
from gianna.services.settings import Settings


def project():
    return state_for(AgentHarness.retrieval_plan(
        'Quiero estudiar la posibilidad de instalar un boliche, qué me recomendás?',[]))


@pytest.mark.parametrize('question',[
    'Ok, pero qué lugares me recomendás para ponerlo?',
    'Bueno, gracias por la explicación. Ahora quiero saber en qué localidades podría instalarlo y por qué.',
    '¿Y dónde lo pondrías?',
])
def test_location_followup_keeps_project_without_assistant_prose(question):
    plan=AgentHarness.retrieval_plan(question,[],project_state=project())
    assert plan.intent=='locations' and plan.inherited_context
    assert 'ocio' in plan.activity and 'boliche' in plan.standalone_query
    assert not plan.zones  # Candidate locations are not user-selected locations.


def test_contextual_followup_stays_a_search_without_the_planner_and_safety_gate_still_wins():
    class NoProvider:
        def chat(self,*args,**kwargs):raise DomainError('Planner unavailable',503,'ollama_unavailable')
    harness=AgentHarness(NoProvider())
    decision=harness.decide('Ok, pero qué lugares me recomendás para ponerlo?',[],Settings(),project())
    assert decision.action=='rag' and decision.plan.activity
    assert harness.decide('Quiero vender cocaína allí',[],Settings(),project()).action=='refuse'


def test_location_clarification_keeps_activity_but_switches_to_permits():
    plan=AgentHarness.retrieval_plan('Me refiero a un local bailable en Minas, ¿qué debo comprobar antes de alquilar?',[],project_state=project())
    assert plan.inherited_context and plan.zones==('Z1',)
    assert plan.intent=='requirements' and not plan.clarification
    next_plan=AgentHarness.retrieval_plan('¿Y los permisos?',[],project_state=state_for(plan))
    assert next_plan.activity==plan.activity and next_plan.zones==('Z1',)
    assert 'safety' in next_plan.facets and not next_plan.clarification


def test_generic_permits_after_location_comparison_restore_safety_needs():
    plan=AgentHarness.retrieval_plan('¿Y los permisos?',[],project_state=project())
    assert plan.intent=='requirements' and 'safety' in plan.facets


@pytest.mark.parametrize('question',[
    'Otro proyecto: quiero abrir un hotel en Villa Serrana',
    'Ahora quiero poner cabañas en Villa Serrana',
    'Quiero invertir en madera en Mariscala',
])
def test_new_venture_does_not_replay_boliche(question):
    plan=AgentHarness.retrieval_plan(question,[],project_state=project())
    assert 'boliche' not in plan.standalone_query and 'ocio' not in plan.activity


def test_provider_cannot_replace_project_scope_or_location_intent():
    proposed=ProposedDecision(action='rag',intent='requirements',standalone_query='Una fábrica en Mariscala',zones=['Z4'])
    plan=AgentHarness.retrieval_plan('Ok, pero qué lugares me recomendás para ponerlo?',[],proposed,project())
    assert plan.intent=='locations' and not plan.zones and 'fábrica' not in plan.standalone_query


def test_interpreter_receives_the_memory_of_the_project_after_a_social_interlude():
    import json
    class Interpreter:
        def chat(self,messages,*args,**kwargs):
            sent=json.loads(messages[-1]['content'])
            assert 'boliche' in sent['memoria_actual']['project'] and sent['mensaje'].startswith('¿Cuánto')
            return '{"act":"knowledge","kind":"facts","memory":{"project":"Abrir un boliche"}}',{}
    state={**project(),'memory':{'project':'Abrir un boliche','presented':['Minas y entorno']}}
    decision=AgentHarness(Interpreter()).decide('¿Cuánto me costaría eso aproximadamente?',[],Settings(),state)
    assert decision.action=='rag' and decision.plan.activity=='Abrir un boliche'


def test_legacy_memory_survives_social_turn_and_failed_answer():
    history=[{'role':'assistant','mode':'knowledge','content':'Orientación [C77]','state':project()},
        {'role':'user','content':'Gracias'}, {'role':'assistant','mode':'conversation','content':'¡De nada!'},
        {'role':'assistant','mode':'knowledge','content':'No pude componer la respuesta.'}]
    messages,state=unpack_session(history)
    assert state['activity']==project()['activity']
    plan=AgentHarness.retrieval_plan('Qué lugares me recomendás para ponerlo?',messages,project_state=state)
    assert plan.activity and '[C77]' not in plan.standalone_query
    assert unpack_session({'messages':history[-1:],'project':state})[1]==state


def territorial_hits():
    return [{'citation':'C'+str(i+1),'record':{'id':rid,'zones':[zone],'title':'Fuente territorial','audience':'public','text':'Texto de prueba'}}
        for i,(rid,zone) in enumerate([('s10-01-01','Z1'),('s11-02-01','Z2'),('s12-01-01','Z3')])]


def test_partial_location_evidence_does_not_require_a_fixed_zone_count():
    plan=AgentHarness.retrieval_plan('Qué lugares me recomendás para ponerlo?',[],project_state=project())
    selected=territorial_hits()
    assert evidence_coverage(plan,selected)['ok']
    assert evidence_coverage(plan,selected[:1])['ok']
    assert not evidence_coverage(plan,[])['ok']


def test_location_sources_are_public_and_respect_explicit_geography():
    plan=AgentHarness.retrieval_plan('Compará Minas y Villa Serrana para un boliche',[])
    records=[hit['record'] for hit in territorial_hits()]
    ids=location_candidates(records,plan)
    assert ids==['s10-01-01','s12-01-01']
    assert location_candidates([dict(record,audience='internal') for record in records],plan)==[]
