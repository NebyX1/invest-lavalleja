import json
import math
import pytest
from gianna.errors import DomainError
from gianna.services.neural import ENGINE_VERSION,artifact_specs,verified_manifest
from gianna.services.vector_store import LanceStore
from gianna.services.harness import AgentHarness


def test_lance_hybrid_is_idempotent_and_prefilters_public_zones(cfg):
    store=LanceStore(cfg);name='gianna_contract'
    store.create(name)
    chunks=[{'id':str(i),'record_id':'r'+str(i),'audience':'public','topic':'Permisos',
        'zones':[zone],'record_type':'requirement','opportunity_id':None}
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


def test_bekko_runtime_uses_onnx_and_invalidates_previous_vector_fingerprint():
    bekko=artifact_specs()[0][3]
    assert 'onnx/model.onnx' in bekko
    assert not any(name.startswith('openvino/') for name in bekko)
    assert ENGINE_VERSION=='bekko-horizon-lance-v2'


def test_boliche_is_answered_as_a_bar_pub_or_dance_venue_without_asking_first():
    plan=AgentHarness.retrieval_plan('Quiero invertir poniendo un boliche, ¿qué me recomendás?',[])
    assert 'bar' in plan.activity and 'bailable' in plan.activity and not plan.clarification
    assert plan.intent=='locations' and {'premises','business'}<=set(plan.facets)
    assert len(plan.searches)<=4


def test_bailable_followup_resolves_previous_ambiguity():
    plan=AgentHarness.retrieval_plan('Un local bailable',[
        {'role':'user','content':'Quiero abrir un boliche'},
        {'role':'assistant','mode':'knowledge','content':'Orientación documentada. [C1]',
         'state':{'zones':[],'opportunity_ids':[],'activity':'local de ocio','facets':['premises','safety']}},
    ])
    assert plan.activity=='local bailable o de ocio nocturno' and not plan.clarification
