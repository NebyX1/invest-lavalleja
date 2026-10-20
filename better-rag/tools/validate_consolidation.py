"""Validate an ingestion artifact with actual backend contracts in isolated storage.

--native additionally runs Bekko/OpenVINO, Horizon/ONNX and LanceDB. No generation,
provider request, .env access, live import, publication or live data changes.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from gianna.config import Config
from gianna.corpus import Corpus, load_corpus
from gianna.db import Database
from gianna.errors import DomainError
from gianna.services.knowledge import Knowledge
from gianna.services.settings import Settings

CASES = [
    ('¿Qué información hay sobre parques eólicos existentes en Lavalleja?', {'EN-007', 'EN-008'}),
    ('¿Están permitidos los parques eólicos dentro del Parque Nacional Arequita?', {'EN-004', 'TR-024'}),
    ('¿Qué trámite corresponde para autoconsumo eléctrico de hasta 150 kW?', {'EN-017', 'EN-018'}),
    ('¿Qué información hay sobre biogás y biometano en Lavalleja?', {'EN-024', 'EN-025'}),
    ('¿Qué se sabe de olivicultura y oleoturismo en Lavalleja?', {'AG-012'}),
    ('¿Qué información hay de vitivinicultura y bodegas en Solís de Mataojo?', {'AG-013', 'TS-013'}),
    ('¿Cuáles son las condiciones para una fosa séptica en Villa Serrana?', {'TS-034', 'TS-003', 'TS-004'}),
    ('¿Qué información hay sobre habilitación de residencias para personas mayores?', {'TS-031'}),
    ('¿Qué se documentó del rodaje Caza y Pesca en Arequita?', {'TR-013', 'TR-014'}),
    ('¿Cuál es el régimen de calidad de agua y vertidos del Decreto 226/025?', {'TR-003', 'TR-004'}),
    ('¿Cuántos ecopuntos del Plan VALE se instalaron en Minas y cuántos estaban previstos?', {'AG-032'}),
    ('¿Qué información hay sobre mantenimiento y automatización industrial?', {'O01'}),
    ('¿Qué dice la guía sobre poscosecha, medición y eficiencia en granos?', {'O03', 'AG-005'}),
]


def by_id(items):
    return {item.id: item.model_dump() for item in items}


def validate(path, original_path, native=False, model_dir=None):
    start = time.perf_counter()
    corpus = load_corpus(path)
    original = load_corpus(original_path)
    report = corpus.conversion_report
    checks = {}
    def check(name, condition):
        checks[name] = bool(condition)
        assert condition, name
    current = by_id(corpus.records)
    check('all_original_records_preserved_exactly', all(current[r.id] == r.model_dump() for r in original.records))
    sources = by_id(corpus.sources)
    check('all_original_sources_preserved_exactly', all(sources[s.id] == s.model_dump() for s in original.sources))
    check('counts_407_records_332_public_75_internal', len(current) == 407 and Counter(r.audience for r in corpus.records) == {'public': 332, 'internal': 75})
    check('all_128_fiches_accounted_for', len(report['fiche_to_record']) == 128 and all(target in current for target in report['fiche_to_record'].values()))
    check('all_127_source_entries_resolved', len(report['source_aliases']) == 127 and all(target in sources for target in report['source_aliases'].values()))
    check('all_docx_blocks_accounted_for', set(report['block_coverage']) == {b['id'] for b in report['supplement_archive']['blocks']} and not report['unaccounted_block_ids'])
    check('internal_audiences_unchanged', {r.id for r in corpus.records if r.audience == 'internal'} == {r.id for r in original.records if r.audience == 'internal'})
    check('dates_not_recertified', all(current[r.id]['cutoff_date'] == r.cutoff_date for r in original.records))
    check('ecopoints_duplicate_merged', 'TS-022' not in current and report['fiche_to_record']['TS-022'] == 'AG-032')
    check('no_orphan_references', all(set(r.source_refs) <= set(sources) for r in corpus.records))
    check('parcel_record_no_invented_zone', current['AG-012']['zones'] == [] and current['AG-002']['zones'] == [])
    for name, info in report['inputs'].items():
        check('original_sha256_' + name, hashlib.sha256((original_path.parent / name).read_bytes()).hexdigest() == info['sha256'])
    # Reject invalid records with the actual schema, not a parallel imitation.
    invalid = corpus.model_dump()
    invalid['records'].append(invalid['records'][0])
    try:
        Corpus.model_validate(invalid)
    except ValueError:
        checks['duplicate_ids_rejected'] = True
    else:
        raise AssertionError('duplicate IDs accepted')

    with TemporaryDirectory(prefix='gianna-knowledge-consolidation-') as folder:
        cfg = Config(data_dir=Path(folder), secret_key='isolated-validation-not-used-for-auth-2026', encryption_key='', production=False, worker_enabled=False)
        db = Database(cfg.db_path); db.migrate()
        knowledge = Knowledge(db, cfg)
        base_id = knowledge.import_corpus(corpus, 'Consolidación: prueba aislada', None, path.name)
        check('imported_as_draft', knowledge.require_base(base_id)['status'] == 'draft')
        check('no_approval_on_import', db.one('SELECT COUNT(*) n FROM records WHERE approved=1')['n'] == 0)
        exported = knowledge.export(base_id)
        check('import_export_roundtrip_records', by_id(exported.records) == current)
        check('import_export_roundtrip_sources', by_id(exported.sources) == sources)
        check('import_export_document_and_audit', exported.document == corpus.document and exported.conversion_report == report)
        try:
            knowledge.enqueue_build(base_id, Settings(), None)
        except DomainError as exc:
            check('review_gate_rejects_unapproved_corpus', exc.code == 'review_required')
        else:
            raise AssertionError('review gate bypassed')
        check('no_automatic_active_knowledge', knowledge.active() is None)
        native_result = None
        if native:
            assert model_dir and model_dir.is_dir(), 'Verified local model directory required'
            # Only this temporary data folder is writable; weights are read by inference.
            (cfg.data_dir / 'models').symlink_to(model_dir.resolve(), target_is_directory=True)
            from gianna.services.neural import Embeddings
            from gianna.services.vector_store import LanceStore
            from gianna.services.jobs import Jobs
            from gianna.services.rag import RAG
            from gianna.services.harness import AgentHarness
            embeddings = Embeddings(cfg); embeddings.load()
            store = LanceStore(cfg)
            # No Ollama client or credentials; only retrieve_plan is exercised.
            rag = RAG(db, cfg, knowledge, embeddings, store, None, None)
            approved = knowledge.approve_public(base_id, None)
            check('approval_is_public_only_in_temporary_database', approved == 332)
            settings = Settings()
            _, version_id = knowledge.enqueue_build(base_id, settings, None)
            jobs = Jobs(db, cfg, knowledge, embeddings, store, rag)
            print(json.dumps({'stage': 'native_build', 'records': 332}), flush=True)
            jobs.execute_job(jobs.claim())
            version = db.one('SELECT * FROM versions WHERE id=?', (version_id,))
            check('native_build_ready', version['status'] == 'ready')
            stats = json.loads(version['report_json'])
            chunks = db.all('SELECT record_key,token_count,text,content_json FROM chunks WHERE version_id=? ORDER BY record_key,position', (version_id,))
            public_ids = {r.id for r in corpus.records if r.audience == 'public'}
            check('every_public_record_chunked', {c['record_key'] for c in chunks} == public_ids)
            check('zero_internal_chunks', not ({r.id for r in original.records if r.audience == 'internal'} & {c['record_key'] for c in chunks}))
            check('exact_bekko_budget_420', max(c['token_count'] for c in chunks) <= settings.chunk_tokens)
            check('lancedb_count_matches_sqlite', store.count(version['collection_name']) == len(chunks))
            offsets = {}
            for chunk in chunks:
                data = json.loads(chunk['content_json'])
                offsets.setdefault(chunk['record_key'], []).append((data['char_start'], data['char_end']))
                check('exact_token_count_' + str(data['id']), embeddings.count(data['embedding_text']) == data['token_count'])
            continuous = True
            for rid, spans in offsets.items():
                end = 0
                for lo, hi in spans:
                    continuous &= lo <= end
                    end = max(end, hi)
                continuous &= end == len(current[rid]['text'])
            check('chunk_offsets_cover_full_public_text', continuous)
            cases = []
            for question, expected in CASES:
                plan = AgentHarness.retrieval_plan(question, [])
                selected, elapsed, trace = rag.retrieve_plan(plan, settings, version_id)
                ids = [hit['record_id'] for hit in selected]
                case = {'question': question, 'expected_any': sorted(expected), 'selected': ids,
                        'expected_in_context': bool(expected & set(ids)),
                        'public_only': set(ids) <= public_ids,
                        'global_search': bool(trace['rounds']) and all(r['global_public_search'] for r in trace['rounds']),
                        'horizon_reranked': bool(trace['reranked']), 'elapsed_ms': round(elapsed, 2)}
                cases.append(case)
                print(json.dumps({'stage': 'retrieval', **case}, ensure_ascii=True), flush=True)
            check('native_all_cases_public_global_and_reranked', all(c['public_only'] and c['global_search'] and c['horizon_reranked'] for c in cases))
            # Retrieval relevance failures are reported, not hidden by changing expectations.
            check('no_activation_even_in_native_test', knowledge.active() is None)
            native_result = {'engine_profile': embeddings.profile, 'index': stats, 'cases': cases,
                             'expected_in_context': sum(c['expected_in_context'] for c in cases), 'total_cases': len(cases),
                             'generation_tested': False, 'provider_calls': 0, 'active_knowledge_changed': False}
    return {'checks': checks, 'checks_passed': sum(checks.values()), 'checks_total': len(checks),
            'native': native_result, 'elapsed_seconds': round(time.perf_counter() - start, 3),
            'limitations': ['Import, audience and tokenizer checks do not certify every factual/legal claim.',
                            'Retrieval cases test context selection, not generated answers or conversational quality.',
                            'The service knowledge base was neither imported nor activated.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, required=True)
    parser.add_argument('--original', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--native', action='store_true')
    parser.add_argument('--model-dir', type=Path)
    args = parser.parse_args()
    result = validate(args.corpus, args.original, args.native, args.model_dir)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'checks_passed': result['checks_passed'], 'checks_total': result['checks_total'],
                      'native_retrieval': result['native']['expected_in_context'] if result['native'] else None,
                      'elapsed_seconds': result['elapsed_seconds']}))
