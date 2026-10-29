"""Pinned CPU-only inference profiles. Preparation is explicit, never inside HTTP."""
import hashlib
import importlib.metadata
import json
import logging
from pathlib import Path
import threading
import time
import numpy as np
from ..errors import DomainError

LOG=logging.getLogger(__name__)

EMBEDDING_ID='ibm-granite/granite-embedding-97m-multilingual-r2'
EMBEDDING_REVISION='835ad14087e140460703cf0fae09f97d469d65c2'
RERANK_ID='cross-encoder/mmarco-mMiniLMv2-L12-H384-v1'
RERANK_REVISION='1427fd652930e4ba29e8149678df786c240d8825'
DIMENSIONS=384
ENGINE_VERSION='granite-mmarco-lance-v3'
LEGACY_ENGINE_VERSION='bekko-horizon-lance-v2'
GRANITE_ENGINE_VERSION='granite-mmarco-lance-v3'
MODEL_PROFILES={
    LEGACY_ENGINE_VERSION:{'embedding':('bekko','hotchpotch/bekko-embedding-v1-a8m','c721113d59a1d91b447450324f51c4b3332c924a',
        ['tokenizer.json','tokenizer_config.json','config.json','1_Pooling/config.json','onnx/model.onnx']),
        'reranker':('horizon','Horizon-Labs/multilingual-reranker-small','c2ec8fb3e499725b168bbed2164bfee095360f77',
        ['tokenizer.json','tokenizer_config.json','config.json','onnx/model_quantized.onnx']),
        'pooling':'masked_mean','rank_tokens':384,'rank_pad':0,'label':'Bekko y Horizon'},
    GRANITE_ENGINE_VERSION:{'embedding':('granite','ibm-granite/granite-embedding-97m-multilingual-r2',
        '835ad14087e140460703cf0fae09f97d469d65c2',
        ['tokenizer.json','tokenizer_config.json','config.json','1_Pooling/config.json','onnx/model_quint8_avx2.onnx']),
        'reranker':('mmarco','cross-encoder/mmarco-mMiniLMv2-L12-H384-v1','1427fd652930e4ba29e8149678df786c240d8825',
        ['tokenizer.json','tokenizer_config.json','config.json','onnx/model_quint8_avx2.onnx']),
        'pooling':'cls','rank_tokens':512,'rank_pad':1,'label':'Granite y mMARCO'},
}


def artifact_specs(engine_version=None):
    profile=MODEL_PROFILES[engine_version or ENGINE_VERSION]
    return [profile['embedding'],profile['reranker']]


def verified_manifest(folder,model_id,revision,required):
    try:
        manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        if manifest['model_id']!=model_id or manifest['revision']!=revision:raise ValueError('identity')
        if not set(required)<=set(manifest['files']):raise ValueError('missing entries')
        for name in required:
            info=manifest['files'][name]
            path=(folder/name).resolve()
            if not path.is_relative_to(folder.resolve()):raise ValueError('path')
            with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
            if path.stat().st_size!=info['bytes'] or digest!=info['sha256']:raise ValueError('integrity')
        return manifest
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise DomainError('Faltan modelos verificados. Ejecutá python -m scripts.prepare_models.',503,'models_not_prepared') from exc


class Embeddings:
    """A pinned encoder/ranker pair; old published snapshots keep their own pair."""
    def __init__(self,cfg,engine_version=None):
        self.cfg=cfg;self.model=None;self.ranker=None;self.profile=None
        self.engine_version=engine_version or ENGINE_VERSION
        self.spec=MODEL_PROFILES[self.engine_version]
        self._profiles={self.engine_version:self}
        self._load_lock=threading.Lock();self._infer_lock=threading.Lock()

    def for_profile(self,profile):
        version=profile.get('engine')
        if version not in MODEL_PROFILES:
            raise DomainError('La versión usa un motor no compatible. Creá una versión nueva.',503,'index_profile_mismatch')
        with self._load_lock:
            if version not in self._profiles:
                engine=Embeddings(self.cfg,version)
                engine._infer_lock=self._infer_lock  # Both profiles share the CPU budget.
                self._profiles[version]=engine
            return self._profiles[version]

    def ready_for(self,profile):
        engine=self._profiles.get(profile.get('engine'))
        return bool(engine and engine.model is not None and engine.profile
                    and engine.profile.get('fingerprint')==profile.get('fingerprint'))

    def load(self,on_progress=None):
        if self.model is not None:return
        with self._load_lock:
            if self.model is not None:return
            def stage(message):
                LOG.info('Inicialización del motor vectorial: %s',message)
                if on_progress:on_progress(message)

            label=self.spec['label']
            stage('Verificando integridad de '+label)
            from tokenizers import Tokenizer
            import onnxruntime as ort
            manifests={}
            specs=artifact_specs(self.engine_version)
            for kind,model_id,revision,files in specs:
                folder=self.cfg.model_dir/kind/revision
                manifests[kind]=verified_manifest(folder,model_id,revision,files)
            encoder_kind,encoder_id,encoder_revision,encoder_files=specs[0]
            rank_kind,rank_id,rank_revision,rank_files=specs[1]
            encoder_folder=self.cfg.model_dir/encoder_kind/encoder_revision
            rank_folder=self.cfg.model_dir/rank_kind/rank_revision
            stage('Cargando tokenizadores de '+label)
            self.tokenizer=Tokenizer.from_file(str(encoder_folder/'tokenizer.json'))
            self.tokenizer.no_truncation();self.tokenizer.no_padding()
            self.encoder_tokenizer=Tokenizer.from_file(str(encoder_folder/'tokenizer.json'))
            self.encoder_tokenizer.enable_padding(pad_id=0,pad_token='<pad>')
            self.encoder_tokenizer.enable_truncation(max_length=512)
            self.rank_tokenizer=Tokenizer.from_file(str(rank_folder/'tokenizer.json'))
            self.rank_tokenizer.enable_padding(pad_id=self.spec['rank_pad'],pad_token='<pad>')
            self.rank_tokenizer.enable_truncation(max_length=self.spec['rank_tokens'],strategy='only_second')
            self.query_tokenizer=Tokenizer.from_file(str(rank_folder/'tokenizer.json'))
            self.query_tokenizer.enable_truncation(max_length=120)
            options=ort.SessionOptions();options.intra_op_num_threads=self.cfg.embedding_threads
            options.inter_op_num_threads=1;options.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
            stage('Inicializando '+rank_kind+' ONNX en CPU')
            ranker=ort.InferenceSession(str(rank_folder/rank_files[-1]),sess_options=options,providers=['CPUExecutionProvider'])
            stage('Inicializando '+encoder_kind+' ONNX en CPU')
            model=ort.InferenceSession(str(encoder_folder/encoder_files[-1]),sess_options=options,providers=['CPUExecutionProvider'])
            self.input_names={item.name for item in model.get_inputs()}
            profile={'engine':self.engine_version,'model':encoder_id,'revision_resolved':encoder_revision,
                'dim':DIMENSIONS,'pooling':self.spec['pooling'],'normalize':True,'query_prefix':'','passage_prefix':'',
                'runtime':'onnx-cpu','max_input_tokens':512,'sparse':'lancedb/bm25-spanish',
                'reranker':rank_id,'reranker_revision':rank_revision,'reranker_tokens':self.spec['rank_tokens'],
                'onnxruntime':importlib.metadata.version('onnxruntime'),
                'artifact_hashes':{kind:{name:manifests[kind]['files'][name]['sha256'] for name in files}
                    for kind,_,_,files in specs}}
            profile['fingerprint']=hashlib.sha256(json.dumps(profile,sort_keys=True).encode()).hexdigest()
            self.profile=profile;self.ranker=ranker;self.model=model
            stage(label+' quedaron inicializados')

    def count(self,text):
        self.load();return len(self.tokenizer.encode(text,add_special_tokens=True).ids)

    def _encode(self,texts):
        enc=self.encoder_tokenizer.encode_batch(texts)
        data={'input_ids':np.asarray([e.ids for e in enc],dtype=np.int64),
              'attention_mask':np.asarray([e.attention_mask for e in enc],dtype=np.int64),
              'token_type_ids':np.asarray([e.type_ids for e in enc],dtype=np.int64)}
        feeds={key:value for key,value in data.items() if key in self.input_names}
        output=self._onnx(self.model,feeds)
        if output.ndim==3:
            if self.spec['pooling']=='cls':output=output[:,0,:]
            else:
                mask=data['attention_mask'][...,None]
                output=(output*mask).sum(axis=1)/np.maximum(mask.sum(axis=1),1)
        if output.shape!=(len(texts),DIMENSIONS) or not np.isfinite(output).all():
            raise DomainError('El encoder devolvió vectores inválidos.',503,'invalid_vectors')
        output=output/np.maximum(np.linalg.norm(output,axis=1,keepdims=True),1e-12)
        return output.tolist()

    @staticmethod
    def _onnx(session,feeds,timeout=30):
        import onnxruntime as ort
        options=ort.RunOptions();timer=threading.Timer(timeout,lambda:setattr(options,'terminate',True));timer.daemon=True
        timer.start()
        try:return session.run(None,feeds,options)[0]
        except Exception as exc:
            raise DomainError('No se pudo completar la inferencia local dentro del plazo. Reintentá la consulta.',503,'local_inference_failed') from exc
        finally:timer.cancel()

    def documents(self,texts,lexical_texts):
        self.load()
        if any(self.count(text)>512 for text in texts):raise DomainError('La entrada del encoder excede 512 tokens.')
        with self._infer_lock:dense=self._encode(texts)
        return dense,list(lexical_texts)

    def query(self,text):
        self.load();tokens=self.tokenizer.encode(text,add_special_tokens=False).ids[:500]
        with self._infer_lock:dense=self._encode([self.tokenizer.decode(tokens)])[0]
        return dense,text

    def rerank(self,query,texts):
        self.load()
        if not texts:return []
        with self._infer_lock:
            deadline=time.monotonic()+30
            query=self.query_tokenizer.decode(self.query_tokenizer.encode(query,add_special_tokens=False).ids)
            scores=[];names={item.name for item in self.ranker.get_inputs()}
            for start in range(0,len(texts),4):
                enc=self.rank_tokenizer.encode_batch([(query,text) for text in texts[start:start+4]])
                data={'input_ids':np.asarray([e.ids for e in enc],dtype=np.int64),
                      'attention_mask':np.asarray([e.attention_mask for e in enc],dtype=np.int64),
                      'token_type_ids':np.asarray([e.type_ids for e in enc],dtype=np.int64)}
                remaining=deadline-time.monotonic()
                if remaining<=0:raise DomainError('Se agotó el plazo de reordenación.',503,'rerank_timeout')
                output=self._onnx(self.ranker,{k:v for k,v in data.items() if k in names},remaining)
                scores.extend((1/(1+np.exp(-np.clip(output[:,0],-60,60)))).tolist())
        if len(scores)!=len(texts) or not np.isfinite(scores).all():raise DomainError('El reranker devolvió puntajes inválidos.',503,'invalid_rerank')
        return scores
