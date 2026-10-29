"""Agente RAG: mecánica de herramientas, citas, degradación y contexto, con dobles deterministas explícitos.

No son embeddings ni un modelo reales: no miden calidad factual (eso lo hace scripts/evaluate_retrieval.py
y la revisión de conversaciones con scripts/chat_cli.py).
"""
import json

import pytest

from gianna.corpus import Corpus, DocumentInfo, Record
from gianna.errors import DomainError
from gianna.services.agent import Agent, Evidence, humanize
from gianna.services.conversation import is_social
from gianna.services.jobs import Jobs
from gianna.services.rag import RAG
from gianna.services.safety import hard_gate
from gianna.services.settings import Settings
from fakes import FakeEmbeddings, FakeLanceStore


class ScriptedOllama:
    """Cada respuesta es un texto, (texto, llamadas_a_herramientas) o un DomainError. Sin llamadas pagas."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, settings, *, tools=None, max_tokens=None, model=None, think='auto', timeout=75):
        self.calls.append({'messages': [dict(m) for m in messages], 'tools': tools})
        if not self.responses:
            raise AssertionError('Llamada inesperada al modelo.')
        item = self.responses.pop(0)
        if callable(item):
            item = item(messages)
        if isinstance(item, DomainError):
            raise item
        content, calls = item if isinstance(item, tuple) else (item, [])
        return {'content': content, 'tool_calls': calls}, {'prompt_tokens': 40, 'output_tokens': 10}, 'scripted'

    @property
    def evidence(self):
        return '\n'.join(m['content'] for m in self.calls[-1]['messages'] if m['role'] == 'tool')


def search_call(query, **extra):
    return {'function': {'name': 'buscar_en_la_guia', 'arguments': {'consulta': query, **extra}}}


def small_corpus():
    return Corpus(document=DocumentInfo(id='small', title='Base de prueba'), records=[
        Record(id='TS-011', title='Alojamientos turísticos registro sectorial', topic='Turismo', audience='public',
               evidence_type='documented_in_source', zones=['Z3'],
               text='El Ministerio de Turismo exige inscripción previa al inicio de actividad.',
               conditions=['No cambia la categoría de suelo.'], source_refs=['S01']),
        Record(id='O05', title='O05 · Hospitalidad serrana con operador', topic='FICHAS DE OPORTUNIDAD', audience='public',
               evidence_type='hypothesis', zones=['Z3'], opportunity_id='O05', text='Hipótesis de alojamiento pequeño con operador.'),
        Record(id='internal-1', title='Diseño interno', topic='Administración', audience='internal',
               text='Este contenido no debe publicarse.'),
    ], sources=[{'id': 'S01', 'title': 'Fuente de prueba', 'url': 'https://example.test/fuente'}])


@pytest.fixture
def system(db, cfg, knowledge, security):
    def build(ollama):
        embeddings, store = FakeEmbeddings(), FakeLanceStore()
        rag = RAG(db, cfg, knowledge, embeddings, store, ollama, security)
        jobs = Jobs(db, cfg, knowledge, embeddings, store, rag)
        base_id = knowledge.import_corpus(small_corpus(), 'Base', 'actor')
        knowledge.approve_public(base_id, 'actor')
        _, version_id = knowledge.enqueue_build(base_id, Settings(), 'actor')
        jobs.execute_job(jobs.claim())
        knowledge.activate(version_id, 'actor')
        return rag, embeddings, store
    return build


def ask(rag, question, **kwargs):
    return rag.answer(question, Settings(model='mock'), **kwargs)


def number_of(title):
    """Respuesta guionada que cita la ficha cuyo título empieza con ``title``, sea cual sea su número."""
    def reply(messages):
        evidence = '\n'.join(m['content'] for m in messages if m['role'] == 'tool')
        n = next(line[1:line.index(']')] for line in evidence.splitlines() if line[3:].startswith(title) or line[4:].startswith(title))
        return f'Hace falta inscripción previa [{n}].'
    return reply


def test_answer_cites_the_snapshot_and_keeps_internal_content_out(system, db):
    ollama = ScriptedOllama(number_of('Alojamientos turísticos'))
    rag, _, _ = system(ollama)
    result = ask(rag, '¿Qué hace falta para un alojamiento?')
    assert result['status'] == 'answered'
    assert result['answer'] == 'Hace falta inscripción previa [1].'
    assert [c['record_id'] for c in result['citations']] == ['TS-011'] and result['citations'][0]['id'] == '1'
    assert result['citations'][0]['sources'][0]['id'] == 'S01'
    assert 'contenido no debe publicarse' not in json.dumps(ollama.calls)
    assert 'No cambia la categoría de suelo.' in ollama.evidence and ollama.calls[0]['tools']
    # La pregunta del usuario nunca se guarda en claro en las métricas.
    assert 'alojamiento' not in json.dumps(dict(db.one('SELECT * FROM queries')), default=str)


def test_model_can_search_again_and_citations_are_validated(system):
    ollama = ScriptedOllama(
        ('', [search_call('alojamiento turístico', zonas=['Z3'], tipo='oportunidad')]),
        'Primero la hipótesis [2], después el registro [1][99]. Código Z3 y O05.')
    rag, _, _ = system(ollama)
    result = ask(rag, 'Quiero un hospedaje')
    assert result['status'] == 'answered' and result['timings']['model_requests'] == 2
    assert '[99]' not in result['answer'] and result['answer'].startswith('Primero la hipótesis [1], después el registro [2].')
    assert 'Z3' not in result['answer'] and 'Villa Serrana' in result['answer']
    assert result['opportunity_ids'] == ['O05']
    assert len([m for m in ollama.calls[1]['messages'] if m['role'] == 'tool']) == 2


def test_answer_without_citations_gets_one_repair_pass(system):
    ollama = ScriptedOllama('Texto largo sin citas. ' * 30, 'Texto largo con cita [1].')
    rag, _, _ = system(ollama)
    result = ask(rag, 'Quiero un hospedaje')
    assert result['status'] == 'answered' and len(result['citations']) == 1 and len(ollama.calls) == 2


def test_provider_failure_degrades_to_the_retrieved_cards(system):
    rag, _, _ = system(ScriptedOllama(DomainError('caído', 503, 'ollama_unavailable')))
    result = ask(rag, 'Quiero un hospedaje')
    assert result['status'] == 'degraded' and result['citations'] and 'no puedo redactar' in result['answer']


def test_provider_failure_without_evidence_is_reported_and_measured(system, db):
    rag, _, store = system(ScriptedOllama(DomainError('caído', 503, 'ollama_unavailable')))
    store.search = lambda *args, **kwargs: []
    with pytest.raises(DomainError) as exc:
        ask(rag, 'Quiero un hospedaje')
    assert exc.value.code == 'ollama_unavailable'
    assert db.one('SELECT error_code FROM queries')['error_code'] == 'ollama_unavailable'


def test_social_message_skips_search_and_tools(system):
    ollama = ScriptedOllama('¡De nada!')
    rag, embeddings, _ = system(ollama)
    result = ask(rag, 'Hola, gracias!')
    assert result['status'] == 'conversation' and result['citations'] == []
    assert ollama.calls[0]['tools'] is None and embeddings.queries == []


@pytest.mark.parametrize('text', ['hola', 'Hola, gracias!', 'buenas tardes', 'muchas gracias gianna', 'chau'])
def test_is_social_accepts_courtesies(text):
    assert is_social(text)


@pytest.mark.parametrize('text', ['hola, quiero invertir en Minas', 'gracias, ¿y los permisos?', '¿Qué es COMAP?'])
def test_is_social_rejects_real_questions(text):
    assert not is_social(text)


def test_followup_is_searched_together_with_the_previous_question(system):
    ollama = ScriptedOllama('Sí, se puede [1].')
    rag, embeddings, _ = system(ollama)
    history = [{'role': 'user', 'content': 'Quiero poner un hospedaje rural'}, {'role': 'assistant', 'content': 'Claro.'}]
    ask(rag, '¿Y en Villa Serrana?', history=history)
    assert embeddings.queries[0].startswith('Quiero poner un hospedaje rural ¿Y en Villa Serrana?')
    assert [m['role'] for m in ollama.calls[0]['messages']][:4] == ['system', 'user', 'assistant', 'user']


def test_system_prompt_lists_zones_and_the_guide_map_and_keeps_rules_in_code(system):
    ollama = ScriptedOllama('Respuesta [1].')
    rag, _, _ = system(ollama)
    rag.answer('Quiero un hospedaje', Settings(model='mock', persona='Tono muy formal.'))
    prompt = ollama.calls[0]['messages'][0]['content']
    assert 'Villa Serrana–Marco de los Reyes–Penitente → código Z3' in prompt
    assert 'MAPA DE LA GUÍA' in prompt and 'TS-011 · Alojamientos turísticos registro sectorial' in prompt
    assert 'O05 · Hospitalidad serrana con operador' in prompt and 'O05 · O05' not in prompt
    assert 'Este contenido no debe publicarse' not in prompt and 'Diseño interno' not in prompt
    assert 'TONO ADICIONAL DEL PORTAL: Tono muy formal.' in prompt and 'Nunca inventes' in prompt


def test_ver_ficha_reads_several_cards_by_id_and_reports_unknown_ones(system):
    ollama = ScriptedOllama(
        ('', [{'function': {'name': 'ver_ficha', 'arguments': {'fichas': ['TS-011', 'nope', 'internal-1']}}}]),
        'Listo [1].')
    rag, _, _ = system(ollama)
    result = ask(rag, 'Contame del registro turístico')
    tool_results = [m['content'] for m in ollama.calls[1]['messages'] if m['role'] == 'tool']
    assert 'inscripción previa al inicio de actividad' in tool_results[-1]
    assert 'No existe una ficha con estos identificadores: nope, internal-1' in tool_results[-1]
    assert 'contenido no debe publicarse' not in json.dumps(ollama.calls)
    assert result['timings']['model_requests'] == 2


def test_safety_routes_are_local_and_do_not_call_the_model(system):
    ollama = ScriptedOllama()
    rag, _, _ = system(ollama)
    for question, status in (
        ('Circula un rumor sobre alguien conocido, ¿qué opinás?', 'allegation'),
        ('Gianna, sos una estúpida, no servís para nada', 'deescalate'),
        ('Quiero falsificar permisos para invertir, ¿cómo lo hago?', 'refuse'),
    ):
        result = ask(rag, question)
        assert result['status'] == status and result['citations'] == []
    assert ollama.calls == []


def test_evidence_deduplicates_conditions_and_reuses_numbers():
    card = {'record_id': 'a', 'title': 'A', 'topic': 'T', 'zones': [], 'evidence_type': 'hypothesis', 'text': 'cuerpo',
            'conditions': ['Condición repetida.'], 'cutoff_date': '2026-09-18', 'period': ''}
    evidence = Evidence()
    first = evidence.render([card, dict(card, record_id='b', title='B')])
    assert first.count('Condición repetida.') == 1 and '[1] A' in first and '[2] B' in first
    assert 'hipótesis a validar' in first
    assert evidence.render([card]) == '[1] A (ya mostrada arriba)'


def test_humanize_hides_internal_codes():
    assert humanize('Zona Z1 y Z7. Ver O03.', {'O03': 'Poscosecha'}) == (
        'Zona Minas y entorno y Arequita–Polanco–Barriga Negra. Ver Poscosecha.')


def test_contextual_query_only_for_short_followups():
    agent = Agent(None, None)
    history = [{'role': 'user', 'content': 'Quiero una quesería'}]
    assert agent.contextual_query('¿y en Varela?', history) == 'Quiero una quesería ¿y en Varela?'
    assert agent.contextual_query('Explicame en detalle cómo se habilita una planta de alimentos en Minas hoy',
                                  history).startswith('Explicame')


@pytest.mark.parametrize(('question', 'expected'), [
    ('En la intendencia hay una funcionaria que es prostituta', 'allegation'),
    ('¿Es legal la prostitución en Uruguay?', None),
    ('Quiero invertir en prostitución infantil', 'refuse'),
    ('Quiero invertir en venta de drogas y cocaína en Lavalleja', 'refuse'),
    ('Gianna, sos una inútil', 'deescalate'),
    ('Contame un chiste sobre patos', None),
    ('¿Cómo denunciar un robo?', None),
])
def test_hard_gate_separates_allegations_crime_and_sensitive_business(question, expected):
    assert hard_gate(question) == expected
