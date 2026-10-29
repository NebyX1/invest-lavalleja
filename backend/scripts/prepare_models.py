"""Download only pinned model artifacts, verify hashes, persist a local manifest."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace
import urllib.request
from gianna.services.neural import Embeddings,artifact_specs,ENGINE_VERSION,MODEL_PROFILES


def prepare(model_dir,specs=None):
    for kind,model_id,revision,files in artifact_specs() if specs is None else specs:
        request=urllib.request.Request(f'https://huggingface.co/api/models/{model_id}/revision/{revision}?blobs=true',
            headers={'User-Agent':'Gianna-Invest-Model-Preparation/2.0'})
        with urllib.request.urlopen(request,timeout=60) as response:metadata=json.load(response)
        if metadata['sha']!=revision:raise RuntimeError('La revisión remota no coincide.')
        entries={entry['rfilename']:entry for entry in metadata['siblings']}
        folder=model_dir/kind/revision;manifest={'model_id':model_id,'revision':revision,'files':{}}
        for name in files:
            path=folder/name;path.parent.mkdir(parents=True,exist_ok=True)
            info=entries[name];expected=(info.get('lfs') or {}).get('sha256')
            digest=None
            if path.is_file() and path.stat().st_size==info['size']:
                with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
            if digest is None or expected and digest!=expected:
                temporary=path.with_name(path.name+'.download')
                request=urllib.request.Request(f'https://huggingface.co/{model_id}/resolve/{revision}/{name}',
                    headers={'User-Agent':'Gianna-Invest-Model-Preparation/2.0'})
                try:
                    total=0;hasher=hashlib.sha256()
                    with urllib.request.urlopen(request,timeout=180) as response,temporary.open('wb') as target:
                        while block:=response.read(1024*1024):
                            target.write(block);hasher.update(block);total+=len(block)
                    digest=hasher.hexdigest()
                    if total!=info['size'] or expected and digest!=expected:raise RuntimeError('Falló integridad de '+name)
                    temporary.replace(path)
                finally:temporary.unlink(missing_ok=True)
            manifest['files'][name]={'bytes':info['size'],'sha256':digest}
            print(json.dumps({'model':kind,'file':name,'verified':True,'bytes':info['size']}),flush=True)
        (folder/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')


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
    parser.add_argument('--model-dir',type=Path,default=Path('/app/data/models'))
    parser.add_argument('--engine',choices=tuple(MODEL_PROFILES),default=ENGINE_VERSION)
    args=parser.parse_args();prepare(args.model_dir,artifact_specs(args.engine))
    verify_runtime(args.model_dir,engine_version=args.engine)
