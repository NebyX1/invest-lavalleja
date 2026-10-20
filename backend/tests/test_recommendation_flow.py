from dataclasses import replace
from gianna.errors import DomainError
from gianna.services.harness import AgentHarness,ProposedDecision
from gianna.services.project_memory import state_for,unpack_session
from gianna.services.recommendations import recommendation_context
from gianna.services.response_validation import evidence_coverage
from gianna.services.settings import Settings
from gianna.services.planning import policy_for


def records():
    return [
        {'id':'O03','opportunity_id':'O03','title':'Poscosecha y granos','text':'Granos, poscosecha, calidad y eficiencia.','zones':['Z5'],'audience':'public'},
        {'id':'O12','opportunity_id':'O12','title':'Servicios rurales y mantenimiento','text':'Servicios ganaderos reparación y oficios.','zones':['Z6'],'audience':'public'},
        {'id':'O09','opportunity_id':'O09','title':'Energía','text':'Energía eléctrica.','zones':['Z5'],'audience':'public'},
        {'id':'O16','opportunity_id':'O16','title':'Sucesión de empresas','text':'Sucesión.','zones':['Z5'],'audience':'public'},
        {'id':'s14-01-01','title':'José Pedro Varela','text':'Cadena del grano.','zones':['Z5'],'audience':'public'},
        {'id':'s14-04-01','title':'Prueba comercial','text':'Probar un servicio acotado.','zones':['Z5'],'audience':'public'},
    ]


def northern_state():
    plan=AgentHarness.retrieval_plan('¿Qué me recomendás para invertir en el norte?',[])
    return state_for(plan,records()[:2])


def test_recommendation_and_development_are_distinct_and_do_not_create_user_preferences():
    state=northern_state()
    assert state['intent']=='recommend' and state['opportunity_ids']==[]
    assert [r['id'] for r in state['offered_options']]==['O03','O12']
    plan=AgentHarness.retrieval_plan('Profundiza con Varela',[],project_state=state)
    assert plan.intent=='develop' and plan.zones==('Z5',) and plan.focus_opportunities==('O03',)
    assert not plan.opportunity_ids
    primary,allowed=recommendation_context(records(),plan)
    assert primary==['O03'] and set(allowed)=={'O03','s14-01-01','s14-04-01'}
    assert not {'O09','O16','O12'}&set(allowed)


def test_old_session_without_offered_options_still_narrows_to_the_zone_primary():
    plan=AgentHarness.retrieval_plan('Profundiza con Varela',[],project_state={
        'intent':'explore','zones':['Z5','Z6'],'brief':'Inversiones en el norte'})
    assert recommendation_context(records(),plan)[0]==['O03']


def test_narrowing_to_the_other_zone_uses_the_other_offered_option():
    plan=AgentHarness.retrieval_plan('Y en Batlle',[],project_state=northern_state())
    assert plan.intent=='develop' and plan.focus_opportunities==('O12',)


def test_new_sector_clears_old_focus_and_uses_current_topic():
    plan=AgentHarness.retrieval_plan('Prefiero energía en Varela',[],project_state=northern_state())
    assert not plan.focus_opportunities and not plan.inherited_context
    primary,allowed=recommendation_context(records(),plan)
    assert primary==['O09'] and allowed==['O09']


def test_concrete_next_step_survives_social_turn_and_falls_back_when_the_planner_is_unavailable():
    narrow=AgentHarness.retrieval_plan('Profundiza con Varela',[],project_state=northern_state())
    state=state_for(narrow,records()[:1])
    _,state=unpack_session({'messages':[{'role':'assistant','mode':'conversation','content':'¡De nada!'}], 'project':state})
    class UnavailablePlanner:
        def chat(self,*args,**kwargs):raise DomainError('Proveedor no disponible.',503,'ollama_unavailable')
    decision=AgentHarness(UnavailablePlanner()).decide('¿Cómo arranco?',[],Settings(),state)
    assert decision.action=='rag'
    assert decision.plan.intent=='develop' and decision.plan.focus_opportunities==('O03',)
    assert decision.plan.zones==('Z5',)
    assert decision.plan.next_step and 'cómo avanzar' in policy_for(decision.plan)


def test_offered_options_never_override_public_snapshot_or_explicit_scope():
    plan=AgentHarness.retrieval_plan('Profundiza con Varela',[],project_state=northern_state())
    internal=[dict(r,audience='internal') if r['id']=='O03' else r for r in records()]
    assert recommendation_context(internal,plan)[0]==[]
    proposed=ProposedDecision(action='rag',zones=['Z1'],opportunity_ids=['O16'])
    secured=AgentHarness.retrieval_plan('Profundiza con Varela',[],proposed,northern_state())
    assert secured.focus_opportunities==('O03',) and secured.zones==('Z5',)


def test_factual_locality_question_is_not_treated_as_a_recommendation():
    plan=AgentHarness.retrieval_plan('¿Cuántos habitantes tiene Varela?',[],project_state=northern_state())
    assert plan.intent=='fact'


def test_policies_guide_a_useful_orientation_instead_of_forbidding_it():
    locations=AgentHarness.retrieval_plan('¿Dónde puedo poner un bar?',[])
    text=policy_for(locations)
    assert locations.intent=='locations' and 'varias opciones' in text and 'ventaja' in text
    assert 'No construyas' not in text and 'hipótesis' not in text
    exploring=AgentHarness.retrieval_plan('¿Qué oportunidades hay en turismo?',[])
    assert 'comparar' in policy_for(exploring) and 'No las ordenes' not in policy_for(exploring)
    assert not evidence_coverage(locations,[])['ok']
    assert evidence_coverage(exploring,[{'record':records()[0]}])['ok']


def test_planner_searches_come_before_the_persons_own_wording():
    proposed=ProposedDecision(action='rag',intent='locations',standalone_query='Dónde abrir un bar en Lavalleja',
        searches=['gastronomía y hospitalidad','habilitación de locales y uso de suelo','zonas turísticas'])
    plan=AgentHarness.retrieval_plan('Quiero abrir un bar, ¿dónde?',[],proposed)
    assert plan.searches[1:4]==('gastronomía y hospitalidad','habilitación de locales y uso de suelo','zonas turísticas')
    assert len(plan.searches)<=4


def test_planner_failure_or_invalid_output_keeps_the_deterministic_plan():
    class Broken:
        def chat(self,*args,**kwargs):return 'esto no es JSON',{'prompt_tokens':1,'output_tokens':1}
    decision=AgentHarness(Broken()).decide('¿Qué oportunidades hay en turismo?',[],Settings())
    assert decision.action=='rag' and decision.plan.searches==('¿Qué oportunidades hay en turismo?',)


def test_valid_interpreter_output_drives_the_retrieval_plan_and_memory_without_changing_scope():
    class Interpreter:
        def chat(self,messages,*args,**kwargs):
            assert 'intérprete de turnos' in messages[0]['content']
            return ('{"act":"knowledge","kind":"places","need":"Dónde instalar un parque eólico en Lavalleja",'
                    '"standalone_question":"Dónde instalar un parque eólico en Lavalleja",'
                    '"searches":["energía eólica recurso eólico","autorización en suelo rural y estudio de impacto"],'
                    '"memory":{"project":"Instalar un parque eólico","interests":["energía eólica"]}}'),{'prompt_tokens':3,'output_tokens':2}
    decision=AgentHarness(Interpreter()).decide('¿Dónde puedo instalar un parque eólico?',[],Settings())
    plan=decision.plan
    assert decision.action=='rag' and plan.intent=='locations' and plan.need.startswith('Dónde instalar')
    assert 'energía eólica recurso eólico' in plan.searches and len(plan.searches)<=4
    assert plan.activity=='Instalar un parque eólico' and plan.memory['interests']==['energía eólica']
    assert plan.facets==() and not plan.clarification
    assert decision.usage=={'prompt_tokens':3,'output_tokens':2}


def test_interpreter_reads_intent_not_keywords_so_wanting_to_open_a_venue_is_not_a_permits_request():
    class Interpreter:
        def chat(self,messages,*args,**kwargs):
            return '{"act":"knowledge","kind":"places","need":"Dónde poner un boliche y qué ofrece cada zona"}',{}
    decision=AgentHarness(Interpreter()).decide('Quiero poner un boliche',[],Settings())
    assert decision.plan.intent=='locations' and decision.plan.need.startswith('Dónde poner un boliche')


def test_next_step_is_current_task_not_a_persistent_user_preference():
    narrow=AgentHarness.retrieval_plan('Profundiza con Varela',[],project_state=northern_state())
    state=state_for(narrow,records()[:1])
    for question in ('¿Cómo empiezo?','¿Por dónde empezar?','¿Qué hago ahora?','¿Cuál es el primer paso?'):
        plan=AgentHarness.retrieval_plan(question,[],project_state=state)
        assert plan.intent=='develop' and plan.next_step
    state=state_for(plan,records()[:1])
    details=AgentHarness.retrieval_plan('Profundizá un poco más',[],project_state=state)
    assert details.intent=='develop' and not details.next_step
