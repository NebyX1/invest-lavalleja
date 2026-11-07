"""Download only pinned model artifacts, verify hashes, persist a local manifest."""
import argparse
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace
from gianna.services.neural import Embeddings,artifact_specs,ENGINE_VERSION,MODEL_PROFILES
from gianna.services.artifacts import ensure_models
from gianna.services.storage import writer_lock


def prepare(model_dir,specs=None):
    model_dir=Path(model_dir)
    engine=next((key for key in MODEL_PROFILES if artifact_specs(key)==specs),ENGINE_VERSION) if specs else ENGINE_VERSION
    if specs is not None and specs!=artifact_specs(engine):raise ValueError('Solo se preparan revisiones fijadas.')
    cfg=SimpleNamespace(model_dir=model_dir,data_dir=model_dir.parent)
    cfg.data_dir.mkdir(parents=True,exist_ok=True)
    with writer_lock(cfg):
        ensure_models(cfg,engine,lambda message:print(json.dumps({'preparation':message},ensure_ascii=False),flush=True))


def verify_runtime(model_dir,threads=None,engine_version=None):
    """Load both pinned runtimes and run one local embedding/reranker smoke check."""
    threads=threads or int(os.environ.get('EMBEDDING_THREADS','2'))
    if not 1<=threads<=8:raise ValueError('EMBEDDING_THREADS debe estar entre 1 y 8.')
    cfg=SimpleNamespace(model_dir=model_dir,embedding_threads=threads)
    engine=Embeddings(cfg,engine_version) if engine_version else Embeddings(cfg)
    def report(message):
        print(json.dumps({'runtime_stage':message},ensure_ascii=False),flush=True)
    engine.load(report)
    sample='Información de inversión y territorio en Lavalleja.'
    vectors,_=engine.documents([sample],[sample])
    norm=math.sqrt(sum(value*value for value in vectors[0])) if len(vectors)==1 else 0
    if len(vectors)!=1 or len(vectors[0])!=384 or not all(math.isfinite(value) for value in vectors[0]) or norm<=1e-12:
        raise RuntimeError('El encoder no superó la verificación de dimensión y valores finitos.')
    scores=engine.rerank('información territorial',[sample])
    if len(scores)!=1 or not math.isfinite(scores[0]):
        raise RuntimeError('El reranker no devolvió un puntaje finito.')
    label=MODEL_PROFILES[engine_version or ENGINE_VERSION]['label'].replace(' y ','/')
    report('Verificación de inferencia '+label+' superada')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-dir',type=Path,default=Path(os.environ.get('DATA_DIR','/app/data'))/'models')
    parser.add_argument('--engine',choices=tuple(MODEL_PROFILES),default=ENGINE_VERSION)
    args=parser.parse_args();prepare(args.model_dir,artifact_specs(args.engine))
    verify_runtime(args.model_dir,engine_version=args.engine)
