"""Deterministic transport tests for pinned downloads, hashes and bounded retries."""
import hashlib
import io
import json
from types import SimpleNamespace

import pytest

from gianna.errors import Cancelled,DomainError
from gianna.services import artifacts


@pytest.fixture
def transport(tmp_path,monkeypatch):
    revision='a'*40;model='example/pinned-fixture'
    content={'tokenizer.json':b'{"version":"1.0"}','onnx/model.onnx':b'fixture-weights'}
    entries=[]
    for name,value in content.items():
        entry={'rfilename':name,'size':len(value)}
        if name.endswith('.onnx'):entry['lfs']={'sha256':hashlib.sha256(value).hexdigest()}
        else:entry['blobId']=hashlib.sha1(f'blob {len(value)}\0'.encode()+value).hexdigest()
        entries.append(entry)
    metadata={'sha':revision,'siblings':entries};calls=[];sleeps=[]
    def open_url(request,timeout):
        calls.append(request.full_url)
        if '/api/models/' in request.full_url:return io.BytesIO(json.dumps(metadata).encode())
        name=request.full_url.split('/resolve/'+revision+'/')[1]
        return io.BytesIO(content[name])
    monkeypatch.setattr(artifacts,'artifact_specs',lambda engine:[('fixture',model,revision,list(content))])
    monkeypatch.setattr(artifacts.urllib.request,'urlopen',open_url)
    monkeypatch.setattr(artifacts.time,'sleep',sleeps.append)
    return SimpleNamespace(cfg=SimpleNamespace(model_dir=tmp_path/'models'),folder=tmp_path/'models'/'fixture'/revision,
                           calls=calls,content=content,metadata=metadata,sleeps=sleeps)


def test_verified_offline_restart_has_no_network_requests(transport):
    t=transport;artifacts.ensure_models(t.cfg,'fixture')
    assert len(t.calls)==3
    manifest=json.loads((t.folder/'manifest.json').read_text())
    assert manifest['files']['onnx/model.onnx']['sha256']==hashlib.sha256(t.content['onnx/model.onnx']).hexdigest()
    t.calls.clear();artifacts.ensure_models(t.cfg,'fixture');assert t.calls==[]


@pytest.mark.parametrize('damage',['missing','partial','manifest'])
def test_missing_partial_and_invalid_manifest_recover_idempotently(transport,damage):
    t=transport;artifacts.ensure_models(t.cfg,'fixture');t.calls.clear()
    if damage=='missing':(t.folder/'onnx/model.onnx').rename(t.folder/'onnx/model.saved')
    elif damage=='partial':(t.folder/'tokenizer.json').write_bytes(b'partial')
    else:(t.folder/'manifest.json').write_text('invalid')
    artifacts.ensure_models(t.cfg,'fixture')
    assert (t.folder/'onnx/model.onnx').read_bytes()==t.content['onnx/model.onnx']
    assert (t.folder/'tokenizer.json').read_bytes()==t.content['tokenizer.json']
    assert len(t.calls)==(1 if damage=='manifest' else 2)
    t.calls.clear();artifacts.ensure_models(t.cfg,'fixture');assert not t.calls


@pytest.mark.parametrize('failure',['network','revision','checksum','size'])
def test_untrusted_or_unavailable_download_stops_with_bounded_backoff(transport,monkeypatch,failure):
    t=transport
    if failure=='network':
        def unavailable(*args,**kwargs):raise TimeoutError('isolated fixture network')
        monkeypatch.setattr(artifacts.urllib.request,'urlopen',unavailable)
    elif failure=='revision':t.metadata['sha']='b'*40
    elif failure=='checksum':t.metadata['siblings'][0]['blobId']='b'*40
    else:t.metadata['siblings'][0]['size']=1
    with pytest.raises(DomainError) as error:artifacts.ensure_models(t.cfg,'fixture')
    assert error.value.status==503 and error.value.code=='models_recovery_failed'
    assert t.sleeps==[1,2] and not (t.folder/'manifest.json').exists()


def test_interrupted_download_does_not_commit_manifest_and_can_resume(transport):
    t=transport
    def cancel(message):raise Cancelled()
    with pytest.raises(Cancelled):artifacts.ensure_models(t.cfg,'fixture',cancel)
    assert not (t.folder/'manifest.json').exists()
    artifacts.ensure_models(t.cfg,'fixture')
    assert (t.folder/'manifest.json').exists()
