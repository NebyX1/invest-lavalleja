"""Read-only real-model candidate-window sweep on an existing isolated test index."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import time

from cryptography.fernet import Fernet
from gianna.config import Config
from gianna.services.knowledge import Knowledge
from gianna.services.neural import Embeddings
from gianna.services.retrieval import Retriever
from gianna.services.reranking import RerankBudget
from gianna.services.settings import Settings
from gianna.services.vector_store import LanceStore
from scripts.evaluate_invest_prompts import ReadOnlyDatabase
from scripts.benchmark_reranker import load_cases, quality, timings


class SnapshotDatabase:
    """Immutable evaluation snapshot; never creates WAL/SHM on a read-only mount."""
    def __init__(self,path):
        if Path(str(path)+'-wal').exists():raise ValueError('Checkpoint the isolated snapshot before mounting it')
        self.uri=path.as_uri()+'?mode=ro&immutable=1'
    def all(self,sql,args=()):
        if not sql.lstrip().upper().startswith('SELECT '):raise ValueError('Read-only snapshot')
        with sqlite3.connect(self.uri,uri=True) as connection:
            connection.row_factory=sqlite3.Row
            return [dict(row) for row in connection.execute(sql,args).fetchall()]
    def one(self,sql,args=()):
        rows=self.all(sql,args)
        return rows[0] if rows else None


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',action='store_true');p.add_argument('--state',type=Path,required=True)
    p.add_argument('--benchmark',type=Path,required=True);p.add_argument('--models',type=Path,required=True)
    p.add_argument('--gold',type=Path,required=True);p.add_argument('--holdout',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if not a.run or a.output.exists():p.error('Explicit run and new output required')
    bench=json.loads(a.benchmark.read_bytes());version=bench['versions']['new']
    gold=load_cases(a.gold);holdout=load_cases(a.holdout);cases=gold+holdout
    class PreparedConfig(Config):
        @property
        def model_dir(self):return a.models.resolve()
    cfg=PreparedConfig.from_env({'data_dir':a.state.resolve(),'embedding_threads':2,
      'secret_key':secrets.token_urlsafe(48),'encryption_key':Fernet.generate_key().decode()},
      environ={'FLASK_ENV':'testing','DATABASE_URL':''},initialize_storage=False)
    db=ReadOnlyDatabase(SnapshotDatabase(cfg.db_path))
    retriever=Retriever(db,Knowledge(db,cfg),Embeddings(cfg),LanceStore(cfg))
    meta=retriever.version(version);retriever.embeddings.for_profile(json.loads(meta['profile_json'])).load()
    files=[Path(__file__),Path(__file__).parents[1]/'gianna/services/retrieval.py',a.gold,a.holdout]
    frozen={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    report={'scope':'read_only_existing_test_index','benchmark_sha256':hashlib.sha256(a.benchmark.read_bytes()).hexdigest(),
      'corpus_sha256':bench['corpus_sha256'],'source_sha256':frozen,'provider_calls':0,'sql_writes':False,
      'production_changed':False,'cpu_limit':2,'memory_gib':2,'results':{}}
    def save():a.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    def search(number,count):
        if any(hashlib.sha256(Path(f).read_bytes()).hexdigest()!=h for f,h in frozen.items()):raise RuntimeError('Source changed')
        settings=Settings(rerank_candidates=count)
        t=time.perf_counter();cards,trace=retriever.search(cases[number]['q'],settings,version,rerank_budget=RerankBudget(1500))
        ids=[c['record_id'] for c in cards]
        rank=next((i for i,key in enumerate(ids,1) if key in cases[number]['any']),None)
        return {'case':number,'rank':rank,'ids':ids,'wall_ms':1000*(time.perf_counter()-t),'rerank':trace['rerank']}
    save()
    for count in (6,4):
        retriever.clear_rerank_cache();cold=[search(i,count) for i in range(len(cases))]
        hot=[search(i,count) for i in range(len(cases))]
        with ThreadPoolExecutor(max_workers=3) as pool:burst=list(pool.map(lambda i:search(i,count),range(9)))
        report['results'][str(count)]={'gold':quality(cold[:len(gold)]),'holdout':quality(cold[len(gold):]),
          'cold':timings(cold),'hot':timings(hot),'concurrent_hot':timings(burst),'rows':cold,'burst':burst,
          'cold_applied':sum(r['rerank']['state']=='applied' for r in cold),
          'hot_hits':sum(r['rerank']['state']=='cache_hit' for r in hot),
          'burst_hits':sum(r['rerank']['state']=='cache_hit' for r in burst)}
        save();print(json.dumps({'candidates':count,**{k:v for k,v in report['results'][str(count)].items() if k not in {'rows','burst'}}}),flush=True)


if __name__=='__main__':main()
