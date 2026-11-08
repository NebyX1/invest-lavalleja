"""Opt-in real Agent/safety/ONNX/LanceDB evaluation against an isolated read-only index."""
import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import secrets
import time

from cryptography.fernet import Fernet
from dotenv import dotenv_values
import httpx

from gianna.config import Config
from gianna.db import Database
from gianna.services.agent import Agent
from gianna.services.knowledge import Knowledge
from gianna.services.neural import Embeddings
from gianna.services.retrieval import Retriever
from gianna.services.runtime import Ollama
from gianna.services.settings import Settings
from gianna.services.vector_store import LanceStore
from scripts.evaluate_invest_prompts import ReadOnlyDatabase


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', action='store_true')
    p.add_argument('--benchmark', type=Path, required=True)
    p.add_argument('--models-dir', type=Path, required=True)
    p.add_argument('--cases', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--model', required=True)
    p.add_argument('--max-http', type=int, default=160)
    a = p.parse_args()
    if not a.run or a.output.exists() or not 1 <= a.max_http <= 300:
        p.error('Explicit bounded run and new output required')
    root = Path(__file__).resolve().parents[1]
    bench = json.loads(a.benchmark.read_bytes())
    cases = json.loads(a.cases.read_bytes())
    class PreparedConfig(Config):
        @property
        def model_dir(self): return a.models_dir.resolve()
    cfg = PreparedConfig.from_env({'data_dir': a.benchmark.resolve().parent / 'runtime', 'embedding_threads': 2,
        'secret_key': secrets.token_urlsafe(48), 'encryption_key': Fernet.generate_key().decode()},
        environ={'FLASK_ENV': 'testing', 'DATABASE_URL': ''}, initialize_storage=False)
    db = ReadOnlyDatabase(Database(cfg.db_path))
    retriever = Retriever(db, Knowledge(db, cfg), Embeddings(cfg), LanceStore(cfg))
    version = bench['versions']['new']
    retriever.embeddings.for_profile(json.loads(retriever.version(version)['profile_json'])).load()
    settings = Settings(model=a.model, temperature=.1, max_output_tokens=4096)
    env = dotenv_values(root / '.env')
    pcfg = SimpleNamespace(ollama_url=env['OLLAMA_HOST'].rstrip('/'),
                          ollama_api_key=env['OLLAMA_API_KEY'], ollama_fallback_models=())
    files = [Path(__file__), a.cases, *(root/'gianna/services'/f'{name}.py' for name in
             ['agent', 'information', 'answer_contract', 'prompts', 'risk', 'retrieval', 'reranking', 'runtime'])]
    frozen = {str(f.resolve()): hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    state = {'scope': 'actual_agent_real_safety_provider_onnx_lance_read_only_fixture', 'model': a.model,
             'source_sha256': frozen, 'corpus_sha256': bench['corpus_sha256'], 'http_attempts': 0,
             'production_changed': False, 'automatic_quality_verdict': False, 'cases': []}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    for f in files:
        if f.suffix == '.py': (a.output.parent / (a.output.stem+'-'+f.name)).write_bytes(f.read_bytes())
    def save(): a.output.write_bytes((json.dumps(state, ensure_ascii=False, indent=2)+'\n').encode())
    def reserve(request):
        if state['http_attempts'] >= a.max_http: raise RuntimeError('Paid batch limit reached')
        if any(hashlib.sha256(Path(f).read_bytes()).hexdigest() != h for f,h in frozen.items()):
            raise RuntimeError('Frozen evaluation source changed')
        state['http_attempts'] += 1; save()
    current = None
    class RecordingOllama(Ollama):
        def _once(self, model, messages, settings, tools, max_tokens, think, timeout):
            record = {'messages': messages, 'tools': tools, 'timeout': timeout}
            current['provider'].append(record)
            result = super()._once(model, messages, settings, tools, max_tokens, think, timeout)
            record['response'], record['usage'] = result
            return result
    histories = {}
    with httpx.Client(base_url=pcfg.ollama_url, headers={'Authorization':'Bearer '+pcfg.ollama_api_key},
        timeout=60, trust_env=False, follow_redirects=False, event_hooks={'request':[reserve]}) as client:
        agent = Agent(retriever, RecordingOllama(pcfg, client))
        save()
        for case in cases:
            history = histories.get(case.get('parent'), case.get('history', []))
            before = state['http_attempts']; started = time.perf_counter()
            current = {'id':case['id'], 'question':case['q'], 'history':history, 'provider':[]}
            try:
                result = agent.run(case['q'], settings, history, version)
                current.update(status=result.status, answer=result.answer, trace=result.trace,
                               cited=[c['record_id'] for c in result.cards], usage=result.usage)
                histories[case['id']] = history + [{'role':'user','content':case['q']},
                                                  {'role':'assistant','content':result.answer}]
            except Exception as exc:
                current.update(status='failed', error_type=type(exc).__name__, error_code=getattr(exc,'code',None))
                histories[case['id']] = history + [{'role':'user','content':case['q']}]
            current.update(http_attempts=state['http_attempts']-before, ms=round((time.perf_counter()-started)*1000))
            state['cases'].append(current); save()
            print(json.dumps({k:current[k] for k in ['id','status','http_attempts','ms']}), flush=True)


if __name__ == '__main__': main()
