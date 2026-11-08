"""Opt-in, bounded real-agent evaluation; SQL/index stay read-only.

Optional --corpus supplies additive information views bound to the exact source
records in the existing published snapshot. It does not import or activate data.
Results require manual review; completion and phrase flags do not certify tone,
grounding, legal accuracy, production deployment or HTTP authentication.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
from dotenv import dotenv_values
from sqlalchemy.engine import make_url

from gianna.config import Config
from gianna.corpus import Record, information_source_hash, load_corpus
from gianna.db import Database
from gianna.services.agent import Agent
from gianna.services.knowledge import Knowledge
from gianna.services.neural import Embeddings
from gianna.services.retrieval import Retriever
from gianna.services.runtime import Ollama
from gianna.services.settings import get_settings


class ReadOnlyDatabase:
    """Read-only adapter; never persists the optional presentation overlay."""
    def __init__(self, db, views=None):
        self.db = db
        self.views = views or {}
        self.applied = set()

    def _row(self, row):
        if not row or 'record_key' not in row or 'content_json' not in row:
            return row
        view = self.views.get(row['record_key'])
        if view is None:
            return row
        original = Record.model_validate_json(row['content_json'])
        if original.audience != 'public':
            return row
        if information_source_hash(original) != view.source_sha256:
            raise ValueError('The evaluated view belongs to a different source revision')
        result = dict(row)
        result['content_json'] = json.dumps({**original.model_dump(mode='json'),
                                             'information_view': view.model_dump()}, ensure_ascii=False)
        self.applied.add(original.id)
        return result

    @staticmethod
    def _check(sql):
        if not sql.lstrip().upper().startswith('SELECT '):
            raise ValueError('Evaluation permits SELECT only')

    def one(self, sql, args=()):
        self._check(sql)
        return self._row(self.db.one(sql, args))

    def all(self, sql, args=()):
        self._check(sql)
        return [self._row(row) for row in self.db.all(sql, args)]

    def setting(self, key, default):
        row = self.one('SELECT value FROM settings WHERE `key`=?', (key,))
        return json.loads(row['value']) if row else default


class NoRetryOllama(Ollama):
    def chat(self, messages, settings, *, tools=None, max_tokens=None, model=None, think='auto', timeout=75):
        name = model or settings.model
        message, usage = self._once(name, messages, settings, tools, max_tokens, think, timeout)
        return message, usage, name


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='Explicitly permit paid generation.')
    parser.add_argument('--corpus', type=Path, help='Native corpus with reviewed additive views.')
    parser.add_argument('--cases', type=Path, default=ROOT / 'evals/information_style.json')
    parser.add_argument('--output', type=Path, required=True, help='New private evaluation JSON.')
    parser.add_argument('--max-http', type=int, default=80, help='Bound includes safety and tool-loop calls.')
    args = parser.parse_args()
    if not args.run or not 1 <= args.max_http <= 120:
        parser.error('Explicit --run and a bounded --max-http 1..120 are required')
    if args.output.exists():
        parser.error('Results are immutable; choose a new output path')
    cases = json.loads(args.cases.read_text(encoding='utf8'))
    ids = [case['id'] for case in cases]
    if not cases or len(ids) != len(set(ids)):
        parser.error('Unique nonempty cases required')
    values = dotenv_values(ROOT / '.env')
    url = make_url(values.get('DATABASE_URL', ''))
    if url.host not in {'localhost', '127.0.0.1', 'host.docker.internal'}:
        parser.error('Only a read-only local database is permitted')
    if url.host == 'host.docker.internal':
        values['DATABASE_URL'] = url.set(host='127.0.0.1').render_as_string(hide_password=False)
    cfg = Config.from_env(environ=values, initialize_storage=False)
    views = {}
    if args.corpus:
        corpus = load_corpus(args.corpus)
        views = {r.id: r.information_view for r in corpus.records
                 if r.audience == 'public' and r.enabled and r.information_view is not None}
        if not views:
            parser.error('The overlay corpus contains no valid public information views')
    db = ReadOnlyDatabase(Database(cfg.database_target), views)
    knowledge = Knowledge(db, cfg)
    embeddings = Embeddings(cfg)
    from gianna.services.vector_store import LanceStore
    retriever = Retriever(db, knowledge, embeddings, LanceStore(cfg))
    version = retriever.version()
    if not retriever.vector_store.exists(version['collection_name']):
        raise ValueError('Existing index required; the evaluator does not recover or build data')
    # Reject source/view revision mismatches before the first paid safety call.
    retriever.outline(version['id'])
    embeddings.for_profile(json.loads(version['profile_json'])).load()
    settings = get_settings(db, cfg)
    state = {'scope': 'real_local_agent_safety_hybrid_onnx_tools_memory_generation_read_only',
             'started_at': datetime.now(timezone.utc).isoformat(), 'model': settings.model,
             'temperature': settings.temperature, 'max_output_tokens': settings.max_output_tokens,
             'version_id': version['id'], 'views_available': len(views),
             'overlay_corpus_sha256': sha(args.corpus) if args.corpus else None,
             'cases_sha256': sha(args.cases), 'max_http': args.max_http, 'http_attempts': 0,
             'source_sha256': {}, 'cases': [], 'production_changed': False,
             'sql_writes': False, 'automatic_quality_verdict': False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for path in (Path(__file__), ROOT / 'gianna/corpus.py',
                 *(ROOT / 'gianna/services' / (name + '.py') for name in ('agent', 'prompts', 'settings', 'retrieval'))):
        digest = sha(path)
        state['source_sha256'][str(path.relative_to(ROOT))] = digest
        snapshot = args.output.with_name(args.output.stem + '-' + path.stem + '-' + digest + '.py')
        if not snapshot.exists():
            snapshot.write_bytes(path.read_bytes())

    def save():
        args.output.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf8')

    def reserve(request):
        if request.method == 'POST' and request.url.path == '/api/chat':
            if state['http_attempts'] >= args.max_http:
                raise RuntimeError('Evaluation HTTP budget exhausted')
            state['http_attempts'] += 1
            save()

    save()
    client = httpx.Client(base_url=cfg.ollama_url, headers={'Authorization': 'Bearer ' + cfg.ollama_api_key},
                          timeout=75, trust_env=False, follow_redirects=False,
                          event_hooks={'request': [reserve]})
    agent = Agent(retriever, NoRetryOllama(cfg, client=client))
    try:
        for spec in cases:
            previous = next((case for case in state['cases'] if case['id'] == spec.get('parent')), None)
            history = spec.get('history', []) if previous is None else [
                *previous['history'], {'role': 'user', 'content': previous['question']},
                {'role': 'assistant', 'content': previous.get('answer', '')}]
            case = {**spec, 'history': history}
            before = state['http_attempts']
            started = time.perf_counter()
            print(json.dumps({'starting': case['id'], 'http_attempts': before}), flush=True)
            try:
                result = agent.run(case['question'], settings, history, version['id'])
                case.update(status=result.status, answer=result.answer, usage=result.usage,
                            trace=result.trace, cited=[c['record_id'] for c in result.cards])
                # Audit flags only: never delete/rewrite a model sentence, and
                # never equate absence of these phrases with semantic success.
                case['review_flags'] = re.findall(
                    r'(?i)ten[eé]s que|deb[eé]s|hay que confirmar|antes de invertir|te recomiendo', result.answer
                ) if spec.get('mode') == 'information' else []
            except Exception as exc:
                case.update(status='failed', answer='', error_type=type(exc).__name__,
                            error_code=getattr(exc, 'code', None))
            case['duration_ms'] = round((time.perf_counter() - started) * 1000)
            case['http_attempts'] = state['http_attempts'] - before
            state['cases'].append(case)
            state['views_applied_read_only'] = sorted(db.applied)
            save()
            print(json.dumps({'completed': case['id'], 'status': case['status'],
                              'http_attempts': state['http_attempts']}), flush=True)
            if state['http_attempts'] >= args.max_http:
                break
    finally:
        state['finished_at'] = datetime.now(timezone.utc).isoformat()
        save()
        client.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Provider/config exceptions must never echo credentials or document bodies.
        print(json.dumps({'fatal_type': type(exc).__name__, 'code': getattr(exc, 'code', None)}))
        sys.exit(1)
