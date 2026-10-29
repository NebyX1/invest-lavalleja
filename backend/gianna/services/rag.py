"""Orquestación de una consulta pública o de vista previa: agente, citas, métricas y concurrencia."""
import logging
import time

from ..db import dumps, uid
from ..errors import DomainError
from ..security import keyed_hash
from .agent import Agent
from .retrieval import Retriever

LOG = logging.getLogger(__name__)


class RAG:
    def __init__(self, db, cfg, knowledge, embeddings, vector_store, ollama, security):
        import threading
        self.db = db
        self.cfg = cfg
        self.knowledge = knowledge
        self.embeddings = embeddings
        self.vector_store = vector_store
        self.ollama = ollama
        self.security = security
        self.retriever = Retriever(db, knowledge, embeddings, vector_store)
        self.agent = Agent(self.retriever, ollama)
        self.semaphore = threading.BoundedSemaphore(cfg.max_concurrent_chat)

    def engine_for(self, profile):
        return self.embeddings.for_profile(profile) if hasattr(self.embeddings, 'for_profile') else self.embeddings

    def retrieve(self, question, settings, version_id=None, **filters):
        """Fichas recuperadas sin llamar al modelo generativo (laboratorio y evaluación)."""
        cards, trace = self.retriever.search(question, settings, version_id, **filters)
        return cards, trace['ms']

    def citation(self, card):
        sources = self.retriever.sources(card['version_id'], {'source_refs': card['source_refs']})
        return {'id': str(card['n']), 'title': card['title'], 'record_id': card['record_id'],
                'version_id': card['version_id'], 'cutoff_date': card['cutoff_date'],
                'evidence_type': card['evidence_type'], 'locator': card['locator'],
                'excerpt': card['text'][:1400], 'sources': sources}

    def answer(self, question, settings, history=None, session_hash=None, version_id=None, preview=False):
        question = question.strip()
        if not question or len(question) > 2500:
            raise DomainError('Escribí una pregunta de hasta 2.500 caracteres.')
        # Una ráfaga espera su turno (hasta 30 s) en lugar de recibir un rechazo inmediato.
        if not self.semaphore.acquire(timeout=30):
            raise DomainError('Gianna está atendiendo otras consultas. Volvé a intentar.', 429, 'busy')
        query_id = uid()
        started = time.perf_counter()
        status, error_code, result = 'error', None, None
        try:
            active = self.db.one('SELECT * FROM versions WHERE id=?', (version_id,)) if version_id else self.knowledge.active()
            if not active:
                raise DomainError('Todavía no hay una base publicada.', 503, 'no_knowledge')
            version_id = active['id']
            result = self.agent.run(question, settings, history or [], version_id)
            status = result.status
            return {
                'id': query_id, 'answer': result.answer, 'citations': [self.citation(c) for c in result.cards],
                'status': status, 'mode': 'knowledge', 'notice': settings.knowledge_notice, 'version_id': version_id,
                'opportunity_ids': list(dict.fromkeys(c['opportunity_id'] for c in result.cards if c.get('opportunity_id'))),
                'follow_up': None, 'timings': {'total_ms': round((time.perf_counter() - started) * 1000, 1),
                                               'model_requests': result.requests},
            }
        except DomainError as exc:
            error_code = exc.code
            raise
        finally:
            self.semaphore.release()
            self.log(query_id, session_hash, version_id, preview, status, result, question, started, error_code)

    def log(self, query_id, session_hash, version_id, preview, status, result, question, started, error_code):
        elapsed = (time.perf_counter() - started) * 1000
        cards = result.cards if result else []
        trace = result.trace if result else {}
        usage = result.usage if result else {}
        # La consulta del usuario nunca se guarda en claro: solo hash, ids y tiempos.
        stored = {**trace, 'searches': [{k: v for k, v in s.items() if k != 'query'} for s in trace.get('searches', [])]}
        try:
            self.db.execute(
                'INSERT INTO queries(id,at,session_hash,version_id,mode,status,topic,retrieval_ms,generation_ms,total_ms,source_ids_json,'
                'prompt_tokens,output_tokens,question_hash,error_code,retrieval_trace_json,cited_source_ids_json) '
                'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (query_id, time.time(), session_hash, version_id, 'preview' if preview else 'public', status,
                 cards[0]['topic'] if cards else None,
                 sum(s.get('ms', 0) for s in trace.get('searches', [])), 0, elapsed,
                 dumps(trace.get('retrieved', [])), usage.get('prompt_tokens'), usage.get('output_tokens'),
                 keyed_hash(self.cfg.secret_key, question), error_code, dumps(stored), dumps(trace.get('cited', []))))
        except Exception:
            LOG.exception('No se pudo registrar la métrica de consulta.')
