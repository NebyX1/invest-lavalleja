"""The answer contract is structural: it cannot judge truth, only shape, sources and wording."""
import pytest
from gianna.services.response_policy import ANSWER_SYSTEM,parse_model_reply,refine_voice


def test_answer_with_declared_sources_is_parsed_without_ids_in_the_text():
    reply=parse_model_reply('ESTADO: RESPONDE\nSegún mi base de conocimiento hay varias opciones.\n\nFUENTES: C1, C3',['C1','C2','C3'])
    assert reply.has_answer and reply.source_ids==('C1','C3')
    assert reply.text=='Según mi base de conocimiento hay varias opciones.'


def test_inline_ids_are_removed_from_the_text_and_count_as_declared_sources():
    reply=parse_model_reply('ESTADO: RESPONDE\nVilla Serrana tiene vocación turística [C2], con servicios [C1, C3].',['C1','C2','C3'])
    assert reply.source_ids==('C2','C1','C3')
    assert '[C' not in reply.text and 'turística, con servicios.' in reply.text.replace(' ,',',').replace(' .','.')


def test_missing_information_needs_no_sources_and_keeps_the_models_wording():
    reply=parse_model_reply('ESTADO: SIN_INFORMACION\nNo encontré información sobre ese tema en mi base de conocimiento.',['C1'])
    assert not reply.has_answer and reply.source_ids==() and reply.text.startswith('No encontré')


def test_status_header_is_tolerant_to_markdown_and_code_fences():
    reply=parse_model_reply('```\n**ESTADO: RESPONDE**\nLa zona ofrece alojamiento serrano.\nFUENTES: C1\n```',['C1'])
    assert reply.has_answer and reply.source_ids==('C1',)


@pytest.mark.parametrize('raw',[
    '',
    'ESTADO: RESPONDE',
    'ESTADO: RESPONDE\nUna respuesta sin fuentes declaradas.',
    'ESTADO: RESPONDE\nRespuesta con una fuente inventada.\nFUENTES: C99',
    'Texto libre sin estado ni fuentes que el servidor no puede respaldar.',
])
def test_structurally_invalid_replies_are_rejected(raw):
    with pytest.raises(ValueError):parse_model_reply(raw,['C1'])


def test_unknown_sources_are_dropped_when_a_valid_one_remains():
    assert parse_model_reply('ESTADO: RESPONDE\nRespuesta válida con apoyo.\nFUENTES: C9, C2',['C1','C2']).source_ids==('C2',)


def test_urls_are_never_forwarded_to_the_investor():
    reply=parse_model_reply('ESTADO: RESPONDE\nMás datos en https://evil.test/x y www.otro.test para ver.\nFUENTES: C1',['C1'])
    assert 'http' not in reply.text and 'www' not in reply.text


@pytest.mark.parametrize('raw,expected',[
    ('Según la guía, hay tres zonas.','Según mi base de conocimiento, hay tres zonas.'),
    ('La guía indica que se requiere autorización.','Mi base de conocimiento indica que se requiere autorización.'),
    ('Esto surge de la guía de inversiones publicada.','Esto surge de mi base de conocimiento publicada.'),
    ('La documentación consultada consigna un antecedente.','Mi base de conocimiento consigna un antecedente.'),
    ('Según la documentación disponible, no hay predios.','Según mi base de conocimiento, no hay predios.'),
    ('Se presenta como hipótesis de oportunidad.','Se presenta como posibilidad de oportunidad.'),
    ('Hay dos hipótesis para estudiar.','Hay dos posibilidades para estudiar.'),
    ('La hipótesis 2 propone madera.','La posibilidad propone madera.'),
    ('Una hipótesis a validar con datos.','Una posibilidad a validar con datos.'),
])
def test_refine_voice_replaces_excluded_wording(raw,expected):
    assert refine_voice(raw)==expected


def test_refine_voice_leaves_clean_text_and_unrelated_documentation_untouched():
    text='La documentación ambiental requerida incluye un estudio de impacto.'
    assert refine_voice(text)==text


@pytest.mark.parametrize('text',[
    'La guía técnica del Ministerio de Ambiente pide analizar paisaje, ruido y sombra.',
    'Según la guía de evaluación eólica, se estudian aves y murciélagos.',
])
def test_refine_voice_keeps_the_real_title_of_an_official_document(text):
    assert refine_voice(text)==text


def test_prompt_states_the_wording_and_scope_rules_the_investor_asked_for():
    for needle in ('mi base de conocimiento','hipótesis','varias opciones','ESTADO: SIN_INFORMACION','FUENTES:'):
        assert needle in ANSWER_SYSTEM
    assert 'No te quedes en el "no hay"' in ANSWER_SYSTEM


def test_prompt_separates_fit_reasoning_from_attributing_unsupported_facts_to_a_zone():
    assert 'Orientar no es inventar' in ANSWER_SYSTEM
    assert 'no permite asignar aptitud' in ANSWER_SYSTEM and 'perfil comercial' in ANSWER_SYSTEM
