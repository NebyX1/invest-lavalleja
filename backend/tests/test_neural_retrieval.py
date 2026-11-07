import json
import math
import pytest
from gianna.errors import DomainError
from gianna.services.neural import ENGINE_VERSION,artifact_specs,verified_manifest
from gianna.services.vector_store import LanceStore
from gianna.services.neural import Embeddings,MODEL_PROFILES,LEGACY_ENGINE_VERSION,GRANITE_ENGINE_VERSION


def test_lance_hybrid_is_idempotent_and_prefilters_public_zones(cfg):
    store=LanceStore(cfg);name='gianna_contract'
    store.create(name)
    chunks=[{'id':str(i),'record_id':'r'+str(i),'audience':'public','topic':'Permisos',
        'zones':[zone],'record_type':'ficha','opportunity_id':None}
        for i,zone in enumerate(['Z1','Z5'])]
    vectors=[[1.0]+[0.0]*383,[0.0,1.0]+[0.0]*382]
    texts=['Bomberos incendios seguridad local','Granos poscosecha campaña']
    store.upsert(name,chunks,vectors,texts);store.upsert(name,chunks,vectors,texts);store.finalize(name)
    assert store.count(name)==2
    hits=store.search(name,vectors[0],'incendios seguridad',zones=['Z1'])
    assert [hit['id'] for hit in hits]==['0'] and hits[0]['channels']==['dense','bm25']
    assert store.search(name,vectors[0],'seguridad',zones=["Z1') OR true --"])==[]
    with pytest.raises(DomainError):store.upsert(name,[dict(chunks[0],audience='internal')],[vectors[0]],[texts[0]])
    with pytest.raises(DomainError):store.upsert(name,[chunks[0]],[[math.nan]*384],[texts[0]])
    store.delete(name);assert not store.exists(name)


def test_model_manifest_rejects_corruption(tmp_path):
    folder=tmp_path/'model';folder.mkdir()
    (folder/'tokenizer.json').write_text('{}')
    (folder/'manifest.json').write_text(json.dumps({'model_id':'test','revision':'pinned','files':{
        'tokenizer.json':{'bytes':2,'sha256':'wrong'}}}))
    with pytest.raises(DomainError) as exc:verified_manifest(folder,'test','pinned',['tokenizer.json'])
    assert exc.value.code=='models_not_prepared'


def test_model_manifest_ignores_unused_runtime_artifacts(tmp_path):
    folder=tmp_path/'model';folder.mkdir()
    artifact=folder/'tokenizer.json';artifact.write_text('{}')
    digest=__import__('hashlib').sha256(artifact.read_bytes()).hexdigest()
    (folder/'manifest.json').write_text(json.dumps({'model_id':'test','revision':'pinned','files':{
        'tokenizer.json':{'bytes':2,'sha256':digest},
        'openvino/openvino_model.xml':{'bytes':999,'sha256':'unused'}}}))
    assert verified_manifest(folder,'test','pinned',['tokenizer.json'])['model_id']=='test'


def test_default_runtime_uses_pinned_cpu_onnx_and_preserves_explicit_legacy_profile():
    granite=artifact_specs()[0][3]
    assert 'onnx/model_quint8_avx2.onnx' in granite
    assert not any(name.startswith('openvino/') for name in granite)
    assert ENGINE_VERSION=='granite-mmarco-lance-v3'
    assert 'onnx/model.onnx' in artifact_specs(LEGACY_ENGINE_VERSION)[0][3]


def test_model_profiles_are_pinned_and_do_not_share_pooling_or_fingerprints(cfg):
    old=Embeddings(cfg,LEGACY_ENGINE_VERSION);new=old.for_profile({'engine':GRANITE_ENGINE_VERSION})
    assert new is old.for_profile({'engine':GRANITE_ENGINE_VERSION}) and new is not old
    assert new._infer_lock is old._infer_lock
    assert old.spec['pooling']=='masked_mean' and new.spec['pooling']=='cls'
    assert new.spec['rank_pad']==1 and old.spec['rank_pad']==0
    assert all(len(spec[2])==40 for profile in MODEL_PROFILES.values() for spec in (profile['embedding'],profile['reranker']))
    assert not old.ready_for({'engine':GRANITE_ENGINE_VERSION,'fingerprint':'missing'})
    with pytest.raises(DomainError):old.for_profile({'engine':'unrecognized'})


def test_cls_and_masked_mean_execute_the_profile_contract(cfg,monkeypatch):
    import numpy as np
    from types import SimpleNamespace
    output=np.zeros((1,2,384));output[0,0,0]=2;output[0,1,1]=2
    for version,expected in ((LEGACY_ENGINE_VERSION,[2**-.5,2**-.5]),(GRANITE_ENGINE_VERSION,[1.,0.])):
        engine=Embeddings(cfg,version)
        engine.encoder_tokenizer=SimpleNamespace(encode_batch=lambda texts:[SimpleNamespace(ids=[1,2],attention_mask=[1,1],type_ids=[0,0])])
        engine.input_names={'input_ids','attention_mask'}
        monkeypatch.setattr(engine,'_onnx',lambda *args:output)
        vector=engine._encode(['test'])[0]
        assert np.allclose(vector[:2],expected) and np.isclose(np.linalg.norm(vector),1.)
