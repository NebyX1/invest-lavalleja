"""Import the canonical guide as a draft; optionally exercise isolated, unpublished RAG.

The technical smoke database is separate from the serving database. Its automated
approval is solely a test fixture and must never be treated as editorial sign-off.
"""
import argparse
import json
from pathlib import Path

from gianna.config import Config
from gianna.corpus import load_corpus
from gianna.db import Database
from gianna.security import Security
from gianna.services.jobs import Jobs
from gianna.services.knowledge import Knowledge
from gianna.services.rag import RAG
from gianna.services.runtime import Embeddings, Ollama, Qdrant
from gianna.services.settings import get_settings


def import_draft(corpus, cfg):
    db = Database(cfg.db_path)
    db.migrate()
    knowledge = Knowledge(db, cfg)
    existing = db.one('SELECT id,status FROM bases WHERE source_sha256=?', (corpus.document.sha256,))
    base_id = existing['id'] if existing else knowledge.import_corpus(
        corpus, corpus.document.title, None, corpus.document.filename
    )
    counts = db.one('''SELECT COUNT(*) AS records,
        SUM(CASE WHEN audience='public' THEN 1 ELSE 0 END) AS public_records,
        SUM(CASE WHEN audience='internal' THEN 1 ELSE 0 END) AS internal_records,
        SUM(approved) AS approved_records FROM records WHERE base_id=?''', (base_id,))
    return {'base_id': base_id, **counts, 'status': existing['status'] if existing else 'draft',
            'created': existing is None}


def technical_smoke(corpus, cfg, evaluations_path=None, question=None, show_answer=False):
    if not cfg.ollama_api_key or not cfg.ollama_model:
        raise RuntimeError('El smoke RAG requiere OLLAMA_API_KEY y OLLAMA_MODEL.')
    db = Database(cfg.data_dir / 'technical-smoke.sqlite3')
    db.migrate()
    knowledge = Knowledge(db, cfg)
    embeddings, qdrant, ollama = Embeddings(cfg), Qdrant(cfg), Ollama(cfg)
    rag = RAG(db, cfg, knowledge, embeddings, qdrant, ollama, Security(db, cfg))
    jobs = Jobs(db, cfg, knowledge, embeddings, qdrant, rag)
    version = db.one("SELECT * FROM versions WHERE status='ready' ORDER BY created_at DESC LIMIT 1")
    if version is None:
        base_id = knowledge.import_corpus(corpus, corpus.document.title, 'technical-smoke', corpus.document.filename)
        # Isolated fixture only: this DB is not used by the HTTP service and is never activated.
        approved = knowledge.approve_public(base_id, 'technical-smoke')
        if approved != sum(r.audience == 'public' and r.enabled for r in corpus.records):
            raise RuntimeError('La selección técnica de registros públicos no coincide.')
        job_id, version_id = knowledge.enqueue_build(base_id, get_settings(db, cfg), 'technical-smoke')
        claimed = jobs.claim()
        if not claimed or claimed['id'] != job_id:
            raise RuntimeError('No se pudo iniciar el trabajo de vectorización.')
        print(json.dumps({'stage': 'indexing', 'public_records': approved, 'internal_excluded':
                          sum(r.audience == 'internal' for r in corpus.records)}, ensure_ascii=False), flush=True)
        jobs.execute_job(claimed)
        job = db.one('SELECT status,error FROM jobs WHERE id=?', (job_id,))
        if job['status'] != 'done':
            raise RuntimeError('Falló la vectorización técnica: ' + str(job['error']))
        version = db.one('SELECT * FROM versions WHERE id=?', (version_id,))
    if knowledge.active() is not None:
        raise RuntimeError('El entorno de prueba no debe publicar la versión.')
    embeddings.load()
    if db.one('SELECT COUNT(*) AS n FROM version_records WHERE version_id=? AND '
              "json_extract(content_json,'$.audience')='internal'", (version['id'],))['n']:
        raise RuntimeError('Se encontró contenido interno en la colección pública de prueba.')
    question = question or '¿Qué debo verificar antes de invertir en Lavalleja?'
    hits, latency_ms = rag.retrieve(question, get_settings(db, cfg), version['id'])
    if not hits:
        raise RuntimeError('La búsqueda híbrida no recuperó documentos.')
    evaluation = None
    if evaluations_path:
        questions = json.loads(evaluations_path.read_text(encoding='utf-8'))
        passed = 0
        for case in questions:
            matches, _ = rag.retrieve(case['question'], get_settings(db, cfg), version['id'])
            passed += bool({hit['record_id'] for hit in matches} &
                           set(case['expected_any_record_ids']))
        evaluation = {'questions': len(questions), 'top_k_hits': passed,
                      'top_k_hit_rate': round(passed / len(questions), 3) if questions else None}
    answer = rag.answer(question, get_settings(db, cfg), version_id=version['id'], preview=True)
    result = {'version_id': version['id'], 'chunks': version['chunk_count'],
            'retrieved': len(hits), 'retrieval_ms': round(latency_ms, 1),
            'answer_status': answer['status'], 'citations': len(answer['citations']),
            'ollama_model': cfg.ollama_model, 'published': False,
            'retrieval_evaluation': evaluation}
    if show_answer:
        result['answer_for_human_review'] = answer['answer']
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('corpus', type=Path)
    parser.add_argument('--technical-smoke', action='store_true',
                        help='Indexar y preguntar en una base de prueba aislada, sin publicar.')
    parser.add_argument('--evaluations', type=Path,
                        help='JSON de preguntas de recuperación para el smoke técnico.')
    parser.add_argument('--question', help='Pregunta de prueba; no se publica la versión técnica.')
    parser.add_argument('--show-answer', action='store_true',
                        help='Imprimir la respuesta pública para revisión humana.')
    args = parser.parse_args()
    cfg = Config.from_env()
    corpus = load_corpus(args.corpus)
    print(json.dumps({'stage': 'draft_import', **import_draft(corpus, cfg)}, ensure_ascii=False), flush=True)
    if args.technical_smoke:
        print(json.dumps({'stage': 'technical_smoke', **technical_smoke(
            corpus, cfg, args.evaluations, args.question, args.show_answer)},
                         ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
