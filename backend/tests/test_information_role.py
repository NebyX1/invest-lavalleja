"""General evidence-driven regression; doubles are not factual certification."""
import json
import pytest
from gianna.corpus import Corpus,DocumentInfo,Record
from gianna.services.harness import AgentHarness,ProposedDecision
from gianna.services.project_memory import state_for
from gianna.services.settings import (Settings,DEFAULT_PERSONA,DEFAULT_GREETING,LEGACY_PERSONA,LEGACY_GREETING,
    PREVIOUS_INFORMATION_PERSONA,PREVIOUS_INFORMATION_GREETING,INFORMATION_ONLY_PERSONA,get_settings)
from test_jobs_and_rag import build_system


@pytest.mark.parametrize('persona,greeting',[
    (LEGACY_PERSONA,LEGACY_GREETING),
    (PREVIOUS_INFORMATION_PERSONA,PREVIOUS_INFORMATION_GREETING),
    (INFORMATION_ONLY_PERSONA,DEFAULT_GREETING),
])
def test_former_defaults_upgrade_without_changing_model_or_custom_persona(db,cfg,persona,greeting):
    from gianna.db import dumps
    values=Settings(model='deepseek-v4.1-flash:1017',persona=persona,greeting=greeting).model_dump()
    db.execute('INSERT INTO settings(key,value) VALUES(?,?)',('runtime',dumps(values)))
    current=get_settings(db,cfg)
    assert current.persona==DEFAULT_PERSONA and current.greeting==DEFAULT_GREETING
    assert current.model==values['model']
    values['persona']='Estilo institucional personalizado.'
    values['greeting']='Bienvenido al portal.'
    db.execute('UPDATE settings SET value=? WHERE key=?',(dumps(values),'runtime'))
    custom=get_settings(db,cfg)
    assert custom.persona==values['persona'] and custom.greeting==values['greeting']


def test_identity_stays_about_investing_in_lavalleja_and_orients_the_investor():
    import re
    from gianna.services.conversation import SOCIAL_SYSTEM,SOCIAL_FALLBACK
    for text in (DEFAULT_PERSONA,DEFAULT_GREETING,SOCIAL_SYSTEM,SOCIAL_FALLBACK):
        assert re.search(r'invers|invert',text) and 'Lavalleja' in text
        assert 'desarrollo económico' not in text
    assert 'base de conocimiento' in DEFAULT_PERSONA and 'No asesores inversiones' not in DEFAULT_PERSONA
    assert 'No recomendás dónde invertir' not in SOCIAL_SYSTEM



def missing(text,ids=()):
    return 'ESTADO: SIN_INFORMACION\n'+text


@pytest.mark.parametrize(('question','source','answer'),[
    ('Quiero invertir en energías renovables',
     'Datos ficticios de prueba: se describen instalaciones que transforman la luz del sol en electricidad.',
     'La documentación de prueba describe instalaciones que transforman luz del sol en electricidad.'),
    ('¿Qué consta sobre micropropagación?',
     'Datos ficticios de prueba: la multiplicación in vitro de plantas se describe en este documento.',
     'El documento de prueba describe multiplicación in vitro de plantas.'),
    ('Necesito información sobre calibración de sensores hidropónicos',
     'Datos ficticios de prueba: el documento explica el ajuste de instrumentos que miden nutrientes en cultivos sin suelo.',
     'El documento de prueba trata el ajuste de instrumentos que miden nutrientes en cultivos sin suelo.'),
])
def test_any_topic_reaches_hybrid_reranking_and_generator_without_keyword_veto(
        db,cfg,knowledge,security,question,source,answer):
    corpus=Corpus(document=DocumentInfo(id='semantic-test',title='Información sintética de prueba'),records=[
        Record(id='unlisted-source',title='Documento técnico de prueba',topic='Nuevo tema',
            audience='public',evidence_type='documented_in_source',text=source),
        Record(id='private',title='Documento privado',topic='Reservado',audience='internal',
            evidence_type='reference',text='No publicar esta información.')])
    _,vid,e,_,o,rag,_=build_system(db,cfg,knowledge,security,corpus);knowledge.activate(vid,'actor')
    o.text=answer+' [C1]'
    result=rag.answer(question,Settings(model='mock'))
    assert result['status']=='answered' and result['citations'][0]['record_id']=='unlisted-source'
    assert e.queries and e.rerank_calls and any(question in query for query in e.queries)
    generation=[call for call in o.calls if 'EVIDENCIA DOCUMENTAL' in call[1]['content']]
    assert len(generation)==1 and source in generation[0][1]['content']
    assert all('No publicar esta información' not in message['content'] for call in o.calls for message in call)
    trace=json.loads(db.one('SELECT retrieval_trace_json FROM queries WHERE id=?',(result['id'],))['retrieval_trace_json'])
    assert trace['rounds'][0]['global_public_search']
    assert trace['candidate_record_ids']==['unlisted-source'] and trace['selected_record_ids']==['unlisted-source']


def test_same_question_does_not_determine_missing_information_before_reading_sources(db,cfg,knowledge,security):
    corpus=Corpus(document=DocumentInfo(id='unrelated',title='Datos sintéticos'),records=[
        Record(id='other-topic',title='Otros servicios documentados',topic='Servicios',audience='public',
            evidence_type='reference',text='Datos de prueba sobre servicios de reparación.')])
    _,vid,e,_,o,rag,_=build_system(db,cfg,knowledge,security,corpus);knowledge.activate(vid,'actor')
    o.text=missing('No encontré información sobre los proyectos energéticos que preguntás en mi base de conocimiento.')
    result=rag.answer('Quiero invertir en energías renovables',Settings(model='mock'))
    assert result['status']=='insufficient_evidence' and not result['citations']
    assert e.queries and e.rerank_calls and len(o.calls)==1
    assert result['answer']=='No encontré información sobre los proyectos energéticos que preguntás en mi base de conocimiento.'


def test_partial_information_is_not_replaced_by_a_return_figures_template(db,cfg,knowledge,security,corpus):
    _,vid,_,_,o,rag,_=build_system(db,cfg,knowledge,security,corpus);knowledge.activate(vid,'actor')
    o.text='La guía presenta una hipótesis y exige permiso por padrón; no garantiza permisos ni retorno [C1].'
    result=rag.answer('¿Qué información hay y qué rentabilidad tiene esa inversión?',Settings(model='mock'))
    assert result['status']=='answered' and [c['id'] for c in result['citations']]==['C1']
    assert result['answer']=='Mi base de conocimiento presenta una posibilidad y exige permiso por padrón; no garantiza permisos ni retorno.'


def test_the_investor_never_sees_internal_ids_or_the_excluded_wording(db,cfg,knowledge,security,corpus):
    _,vid,_,_,o,rag,_=build_system(db,cfg,knowledge,security,corpus);knowledge.activate(vid,'actor')
    o.text='ESTADO: RESPONDE\nSegún la guía hay dos hipótesis [C1]. La hipótesis 2 exige permiso.\nFUENTES: C1'
    answer=rag.answer('¿Qué oportunidades hay en turismo?',Settings(model='mock'))['answer']
    assert answer.startswith('Según mi base de conocimiento hay dos posibilidades')
    assert 'guía' not in answer.lower() and 'hipótesis' not in answer.lower()
    assert '[C1]' not in answer and 'ESTADO' not in answer and 'FUENTES' not in answer


def test_the_model_receives_the_conversation_as_native_turns_but_never_as_evidence(db,cfg,knowledge,security,corpus):
    _,vid,_,_,o,rag,_=build_system(db,cfg,knowledge,security,corpus);knowledge.activate(vid,'actor')
    history=[{'role':'user','content':'Quiero un bar en Minas'},
             {'role':'assistant','content':'Hay opciones en Minas [C9].','mode':'knowledge'}]
    rag.answer('¿Y en Villa Serrana?',Settings(model='mock'),history=history)
    roles=[m['role'] for m in o.messages]
    assert roles==['system','user','assistant','user']
    assert o.messages[1]['content']=='Quiero un bar en Minas' and o.messages[2]['content']=='Hay opciones en Minas.'
    assert '¿Y en Villa Serrana?' in o.messages[-1]['content'] and 'Quiero un bar en Minas' not in o.evidence_message


def test_valid_abstention_is_not_repaired_into_a_forced_answer(db,cfg,knowledge,security,corpus):
    _,vid,_,_,o,rag,_=build_system(db,cfg,knowledge,security,corpus);knowledge.activate(vid,'actor')
    o.text=missing('No encontré el dato solicitado en los fragmentos consultados.')
    result=rag.answer('¿Qué condiciones faltan para invertir?',Settings(model='mock'))
    assert result['status']=='insufficient_evidence' and len(o.calls)==1


def test_invalid_generated_output_is_not_claimed_as_lack_of_knowledge(db,cfg,knowledge,security,corpus):
    _,vid,_,_,o,rag,_=build_system(db,cfg,knowledge,security,corpus);knowledge.activate(vid,'actor')
    o.text='Llamá a Marta al 123456, sin ningún formato reconocible.'
    result=rag.answer('Quiero información sobre cualquier inversión',Settings(model='mock'))
    assert result['status']=='citation_guard_failed' and len(o.calls)==3  # first reply plus two native output retries
    assert 'Marta' not in result['answer'] and 'No cuento' not in result['answer']


def test_empty_search_still_uses_model_to_describe_missing_information(db,cfg,knowledge,security,corpus):
    _,vid,e,q,o,rag,_=build_system(db,cfg,knowledge,security,corpus);knowledge.activate(vid,'actor')
    q.search=lambda *args,**kwargs:[{'id':'forged-id','score':1}]
    o.text=missing('No se recuperaron documentos que permitan responder esa consulta.')
    result=rag.answer('Quiero información sobre un tema nuevo',Settings(model='mock'))
    assert e.queries and result['status']=='insufficient_evidence' and not result['citations']
    assert sum('EVIDENCIA DOCUMENTAL' in call[1]['content'] for call in o.calls)==1
    assert 'no recuperó fragmentos' in o.messages[1]['content']


def test_public_context_keeps_all_source_sections_instead_of_literal_topic_projections(db,cfg,knowledge,security,corpus):
    _,vid,_,_,_,rag,_=build_system(db,cfg,knowledge,security,corpus)
    hit=rag.exact_records(['public-1'],vid)[0]
    hit['record']['text']='Descripción.\n\nEntrada y prueba. Un dato.\n\nMEDIR: Otro dato.'
    selected=rag.context([hit],Settings())
    assert 'Entrada y prueba' in selected[0]['context'] and 'MEDIR:' in selected[0]['context']


def test_followup_keeps_user_context_without_an_enumerated_topic():
    previous=AgentHarness.retrieval_plan('Quiero información sobre micropropagación.',[])
    next_plan=AgentHarness.retrieval_plan('¿Y dónde lo menciona la guía?',[],project_state=state_for(previous))
    assert next_plan.inherited_context and 'micropropagación' in next_plan.standalone_query
    changed=AgentHarness.retrieval_plan('Información sobre robótica.',[],project_state=state_for(previous))
    assert not changed.inherited_context and 'micropropagación' not in changed.standalone_query
