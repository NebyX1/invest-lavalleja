"""Flujo de dominio con dobles deterministas para el agente con herramientas.

No es un benchmark de calidad factual. Prueba la mecánica: índice inmutable,
recuperación, herramientas acotadas, citas y degradación sin proveedor.
"""
import hashlib
import json
import time

import numpy as np
import pytest

from gianna.corpus import Corpus, DocumentInfo, Record
from gianna.errors import DomainError
from gianna.services.jobs import Jobs
from gianna.services.rag import RAG
from gianna.services.settings import Settings


class FakeEmbeddings:
    def __init__(self):
        self.model = None
        self.calls = 0
        self.queries = []
        self.rerank_calls = []
        self.load_stages = []
        self.profile = {'fingerprint': 'test-fingerprint', 'dim': 384, 'runtime': 'DETERMINISTIC_TEST_DOUBLE'}

    def load(self, on_progress=None):
        self.model = True
        if on_progress:
            self.load_stages.append('Modelos de prueba inicializados')
            on_progress(self.load_stages[-1])

    def count(self, text):
        return len(text.split()) + 2

    def documents(self, texts, lexical):
        self.load()
        self.calls += len(texts)
        dense = []
        for text in texts:
            seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
            vector = np.random.default_rng(seed).normal(size=384)
            vector /= np.linalg.norm(vector)
            dense.append(vector.tolist())
        return dense, [{'indices': [1], 'values': [1.0]} for _ in texts]

    def query(self, text):
        self.queries.append(text)
        return [0.0] * 384, text

    def rerank(self, query, texts):
        self.rerank_calls.append((query, texts))
        return [1.0 / (i + 1) for i in range(len(texts))]


class FakeLanceStore:
    def __init__(self):
        self.collections = {}
        self.fail_once = False

    def create(self, name):
        self.collections.setdefault(name, {})

    def upsert(self, name, chunks, dense, sparse):
        if self.fail_once:
            self.fail_once = False
            raise DomainError('Fallo simulado', 503)
        for chunk, vector in zip(chunks, dense, strict=True):
            self.collections[name][chunk['id']] = {
                'id': chunk['id'], 'score': .5,
                'payload': {'zones': chunk.get('zones', []),
                            'opportunity_id': chunk.get('opportunity_id'),
                            'record_type': chunk.get('record_type')},
                'vector': vector,
            }

    def finalize(self, name):
        pass

    def count(self, name):
        return len(self.collections[name])

    def delete(self, name):
        self.collections.pop(name, None)

    def search(self, name, *args, **kwargs):
        points = list(self.collections[name].values())
        zones = set(kwargs.get('zones') or [])
        opportunities = set(kwargs.get('opportunity_ids') or [])
        record_types = set(kwargs.get('record_types') or [])
        if zones:
            points = [point for point in points if zones & set(point['payload'].get('zones', []))]
        if opportunities:
            points = [point for point in points if point['payload'].get('opportunity_id') in opportunities]
        if record_types:
            points = [point for point in points if point['payload'].get('record_type') in record_types]
        return points[:12]


class FakeOllama:
    """Transporte guionado: mensaje, uso y modelo; sin llamadas pagas."""

    def __init__(self, answer='La oportunidad es una hipótesis a validar [1].'):
        self.answer = answer
        self.responses = []
        self.calls = []
        self.fail = False

    def chat(self, messages, settings, tools=None, timeout=None):
        self.calls.append({'messages': messages, 'tools': tools, 'timeout': timeout})
        if self.fail:
            raise DomainError('Proveedor no disponible.', 503, 'ollama_unavailable')
        if self.responses:
            message = self.responses.pop(0)
        else:
            message = {'content': self.answer, 'tool_calls': []}
        return message, {'prompt_tokens': 40, 'output_tokens': 10}, 'mock'


def build_system(db, cfg, knowledge, security, corpus):
    embeddings = FakeEmbeddings()
    store = FakeLanceStore()
    ollama = FakeOllama()
    rag = RAG(db, cfg, knowledge, embeddings, store, ollama, security)
    jobs = Jobs(db, cfg, knowledge, embeddings, store, rag)
    base_id = knowledge.import_corpus(corpus, 'Base', 'actor')
    knowledge.approve_public(base_id, 'actor')
    job_id, version_id = knowledge.enqueue_build(base_id, Settings(), 'actor')
    job = jobs.claim()
    assert job['id'] == job_id
    jobs.execute_job(job)
    assert db.one('SELECT status FROM jobs WHERE id=?', (job_id,))['status'] == 'done'
    return base_id, version_id, embeddings, store, ollama, rag, jobs


def domain_corpus():
    return Corpus(document=DocumentInfo(id='domain', title='Base de prueba'), records=[
        Record(id='public-1', title='Oportunidad de prueba', topic='Turismo', audience='public',
               evidence_type='hypothesis',
               text='La oportunidad es una hipótesis. Requiere permiso por padrón. ' +
                    'No garantiza permisos ni retorno. ' + ('Una frase sobre requisitos y evidencia. ' * 60),
               conditions=['No garantiza permisos ni retorno.'], source_refs=['S01']),
        Record(id='internal-1', title='Diseño interno', topic='Administración', audience='internal',
               text='Este contenido no debe publicarse.'),
        Record(id='O01', title='O01 · Mantenimiento y automatización industrial', topic='FICHAS DE OPORTUNIDAD',
               audience='public', evidence_type='hypothesis', zones=['Z1', 'Z2', 'Z5'], opportunity_id='O01',
               text='Mantenimiento industrial y automatización para empresas. Posibilidad a validar con clientes.'),
        Record(id='O03', title='O03 · Poscosecha, medición y eficiencia en granos', topic='FICHAS DE OPORTUNIDAD',
               audience='public', evidence_type='hypothesis', zones=['Z5'], opportunity_id='O03',
               text='Servicio de poscosecha y medición para productores. Requiere validar volumen y clientes.'),
        Record(id='s09-01-02', title='Siete zonas. Siete preguntas de inversión. · Z1 · Minas y entorno',
               topic='TERRITORIO', audience='public', evidence_type='hypothesis', zones=['Z1'],
               text='Tesis comercial: servicios industriales y servicios empresariales.'),
        Record(id='s10-01-01', title='Minas: resolver problemas de empresas y construir equipos', topic='MINAS',
               audience='public', evidence_type='mixed', zones=['Z1'],
               text='Minas es la primera puerta de entrada para proyectos que necesiten coordinación empresarial y servicios.'),
        Record(id='s29-01-02', title='El permiso correcto · Suelo y edificación', topic='PERMISOS', audience='public',
               evidence_type='documented_in_source', text='Frente: Suelo y edificación. Intendencia: Arquitectura.'),
        Record(id='s29-01-05', title='El permiso correcto · Alimentos', topic='PERMISOS', audience='public',
               evidence_type='documented_in_source', text='Frente: Alimentos. RUNAEV, autoridad departamental.'),
        Record(id='s29-01-07', title='El permiso correcto · Incendios y seguridad', topic='PERMISOS', audience='public',
               evidence_type='documented_in_source', text='Frente: Incendios. Dirección Nacional de Bomberos.'),
        Record(id='s29-01-10', title='El permiso correcto, en el orden correcto', topic='PERMISOS', audience='public',
               evidence_type='documented_in_source', text='Una habilitación no reemplaza a otra.'),
        Record(id='s05-01-03', title='Lavalleja en datos · Población', topic='EVIDENCIA', audience='public',
               evidence_type='documented_in_source', text='Lavalleja tiene 58.407 habitantes según la proyección 2025.'),
    ], sources=[{'id': 'S01', 'title': 'Fuente de prueba', 'url': 'https://example.test/fuente'}])


def test_index_then_answer_uses_authoritative_public_snapshot(db, cfg, knowledge, security, corpus):
    _, version_id, _, _, ollama, rag, _ = build_system(db, cfg, knowledge, security, corpus)
    knowledge.activate(version_id, 'actor')
    result = rag.answer('¿Qué condiciones tiene la oportunidad?', Settings(model='mock'))
    assert result['status'] == 'answered' and result['citations']
    assert result['citations'][0]['record_id'] == 'public-1'
    assert all('contenido no debe publicarse' not in message['content']
               for call in ollama.calls for message in call['messages'])
    assert db.one('SELECT COUNT(*) n FROM queries')['n'] == 1


def test_cache_reused_between_versions(db, cfg, knowledge, security, corpus):
    base_id, _, embeddings, _, _, _, jobs = build_system(db, cfg, knowledge, security, corpus)
    before = embeddings.calls
    _, second = knowledge.enqueue_build(base_id, Settings(), 'actor')
    jobs.execute_job(jobs.claim())
    assert embeddings.calls == before
    report = json.loads(db.one('SELECT report_json FROM versions WHERE id=?', (second,))['report_json'])
    assert report['reused_embeddings'] > 0


def test_failed_build_can_resume_without_public_mutation(db, cfg, knowledge, security, corpus):
    base_id, version_id, _, store, _, _, jobs = build_system(db, cfg, knowledge, security, corpus)
    knowledge.activate(version_id, 'actor')
    job_id, second = knowledge.enqueue_build(base_id, Settings(), 'actor')
    store.fail_once = True
    jobs.execute_job(jobs.claim())
    assert db.one('SELECT status FROM jobs WHERE id=?', (job_id,))['status'] == 'failed'
    assert knowledge.active()['id'] == version_id
    db.execute("UPDATE jobs SET status='queued' WHERE id=?", (job_id,))
    jobs.execute_job(jobs.claim())
    assert db.one('SELECT status FROM versions WHERE id=?', (second,))['status'] == 'ready'
    assert knowledge.active()['id'] == version_id


def test_agent_can_call_the_search_tool_and_cite_new_evidence(db, cfg, knowledge, security, corpus):
    _, version_id, _, _, ollama, rag, _ = build_system(db, cfg, knowledge, security, corpus)
    knowledge.activate(version_id, 'actor')
    ollama.responses = [
        {'content': '', 'tool_calls': [{'function': {
            'name': 'buscar_en_la_guia', 'arguments': {'consulta': 'poscosecha'}}}]},
        {'content': 'La poscosecha es una hipótesis a validar [1].', 'tool_calls': []},
    ]
    result = rag.answer('¿Qué información hay sobre poscosecha?', Settings(model='mock'))
    assert result['status'] == 'answered'
    assert result['citations'] and result['timings']['model_requests'] == 2
    assert len(ollama.calls) == 2


def test_agent_degrades_to_cards_when_the_provider_fails(db, cfg, knowledge, security, corpus):
    _, version_id, _, _, ollama, rag, _ = build_system(db, cfg, knowledge, security, corpus)
    knowledge.activate(version_id, 'actor')
    ollama.fail = True
    result = rag.answer('¿Qué condiciones tiene la oportunidad?', Settings(model='mock'))
    assert result['status'] == 'degraded'
    assert result['citations'] and result['citations'][0]['record_id'] == 'public-1'
    assert 'no puedo redactar' in result['answer'].lower()


def test_answer_without_citations_is_insufficient_when_it_denies_coverage(db, cfg, knowledge, security, corpus):
    _, version_id, _, _, ollama, rag, _ = build_system(db, cfg, knowledge, security, corpus)
    knowledge.activate(version_id, 'actor')
    ollama.answer = 'La guía no documenta ese dato.'
    result = rag.answer('¿Qué condiciones tiene la oportunidad?', Settings(model='mock'))
    assert result['status'] == 'insufficient_evidence' and not result['citations']


def test_followup_search_uses_the_previous_user_question(db, cfg, knowledge, security, corpus):
    _, version_id, embeddings, _, ollama, rag, _ = build_system(db, cfg, knowledge, security, corpus)
    knowledge.activate(version_id, 'actor')
    history = [{'role': 'user', 'content': 'Quiero invertir en el norte'},
               {'role': 'assistant', 'content': 'Hay oportunidades en el norte.'}]
    rag.answer('¿Y en Minas?', Settings(model='mock'), history=history)
    assert any('Quiero invertir en el norte' in query for query in embeddings.queries)
    assert any(message['role'] == 'assistant' for message in ollama.calls[-1]['messages'])


def test_social_greeting_does_not_search_or_cite(db, cfg, knowledge, security, corpus):
    _, version_id, embeddings, _, ollama, rag, _ = build_system(db, cfg, knowledge, security, corpus)
    knowledge.activate(version_id, 'actor')
    ollama.answer = 'Hola. ¿En qué puedo ayudarte?'
    result = rag.answer('Hola', Settings(model='mock'))
    assert result['status'] == 'conversation' and not result['citations']
    assert not any('Hola' in query for query in embeddings.queries)


def test_hard_gate_keeps_allegation_and_abuse_out_of_the_model(db, cfg, knowledge, security, corpus):
    _, version_id, _, _, ollama, rag, _ = build_system(db, cfg, knowledge, security, corpus)
    knowledge.activate(version_id, 'actor')
    for question, status in (
        ('Circula un rumor sobre un funcionario', 'allegation'),
        ('Gianna, sos una estúpida', 'deescalate'),
        ('Quiero falsificar permisos para invertir', 'refuse'),
    ):
        result = rag.answer(question, Settings(model='mock'))
        assert result['status'] == status and not result['citations']
    assert ollama.calls == []


def test_embedding_profile_mismatch_fails_closed(db, cfg, knowledge, security, corpus):
    _, version_id, embeddings, _, _, rag, _ = build_system(db, cfg, knowledge, security, corpus)
    knowledge.activate(version_id, 'actor')
    embeddings.profile = {'fingerprint': 'different'}
    with pytest.raises(DomainError) as exc:
        rag.retrieve('prueba', Settings())
    assert exc.value.code == 'embedding_mismatch'


def test_import_job_replay_does_not_duplicate_base(db, cfg, knowledge, security, corpus, tmp_path):
    embeddings = FakeEmbeddings()
    store = FakeLanceStore()
    jobs = Jobs(db, cfg, knowledge, embeddings, store)
    path = cfg.data_dir / 'uploads' / 'corpus.json'
    path.write_text(corpus.model_dump_json(), encoding='utf8')
    job_id = jobs.enqueue('import', {'path': str(path), 'name': 'Test', 'actor': 'actor'})
    jobs.execute_job(jobs.claim())
    db.execute("UPDATE jobs SET status='queued' WHERE id=?", (job_id,))
    jobs.execute_job(jobs.claim())
    assert db.one('SELECT COUNT(*) n FROM bases')['n'] == 1


def test_expired_job_lease_recovered(db, cfg, knowledge):
    jobs = Jobs(db, cfg, knowledge, FakeEmbeddings(), FakeLanceStore())
    job_id = jobs.enqueue('warmup')
    jobs.claim()
    db.execute('UPDATE jobs SET lease_until=? WHERE id=?', (time.time() - 1, job_id))
    new = Jobs(db, cfg, knowledge, FakeEmbeddings(), FakeLanceStore())
    claimed = new.claim()
    assert claimed['id'] == job_id
    assert db.one('SELECT owner_token FROM jobs WHERE id=?', (job_id,))['owner_token'] == new.token
