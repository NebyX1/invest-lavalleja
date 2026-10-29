import json
from scripts import prepare_models


def test_runtime_verification_loads_and_exercises_both_models(monkeypatch,tmp_path,capsys):
    calls={}

    class FakeEmbeddings:
        profile={'runtime':'test'}
        def __init__(self,cfg):calls['cfg']=cfg
        def load(self,progress):
            calls['load']=True
            progress('Bekko y Horizon quedaron inicializados')
        def documents(self,texts,lexical):
            calls['documents']=(texts,lexical)
            return [[1.0]+[0.0]*383],[]
        def rerank(self,query,texts):
            calls['rerank']=(query,texts)
            return [.75]

    monkeypatch.setattr(prepare_models,'Embeddings',FakeEmbeddings)
    prepare_models.verify_runtime(tmp_path,threads=2)

    assert calls['cfg'].model_dir==tmp_path
    assert calls['cfg'].embedding_threads==2
    assert calls['load'] and calls['documents'] and calls['rerank']
    output=[json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert output[-1]['runtime_stage']=='Verificación de inferencia Granite/mMARCO superada'
