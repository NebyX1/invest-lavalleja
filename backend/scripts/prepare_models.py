"""Download only pinned model artifacts, verify hashes, persist a local manifest."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request
from gianna.services.neural import artifact_specs


def prepare(model_dir):
    for kind,model_id,revision,files in artifact_specs():
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


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-dir',type=Path,default=Path('/app/data/models'))
    args=parser.parse_args();prepare(args.model_dir)
