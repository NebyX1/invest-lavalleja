"""Pinned Bekko and Horizon inference on CPU. Models are prepared outside HTTP."""
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

EMBEDDING_ID='hotchpotch/bekko-embedding-v1-a8m'
EMBEDDING_REVISION='c721113d59a1d91b447450324f51c4b3332c924a'
RERANK_ID='Horizon-Labs/multilingual-reranker-small'
RERANK_REVISION='c2ec8fb3e499725b168bbed2164bfee095360f77'
DIMENSIONS=384
ENGINE_VERSION='bekko-horizon-lance-v1'


def artifact_specs():
    return [
        ('bekko',EMBEDDING_ID,EMBEDDING_REVISION,[
            'tokenizer.json','tokenizer_config.json','config.json','1_Pooling/config.json',
            'openvino/openvino_model.xml','openvino/openvino_model.bin','onnx/model.onnx']),
        ('horizon',RERANK_ID,RERANK_REVISION,[
            'tokenizer.json','tokenizer_config.json','config.json','onnx/model_quantized.onnx']),
    ]


def verified_manifest(folder,model_id,revision,required):
    try:
        manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        if manifest['model_id']!=model_id or manifest['revision']!=revision:raise ValueError('identity')
        if not set(required)<=set(manifest['files']):raise ValueError('missing entries')
        for name,info in manifest['files'].items():
            path=(folder/name).resolve()
            if not path.is_relative_to(folder.resolve()):raise ValueError('path')
            with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
            if path.stat().st_size!=info['bytes'] or digest!=info['sha256']:raise ValueError('integrity')
        return manifest
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise DomainError('Faltan modelos verificados. Ejecutá python -m scripts.prepare_models.',503,'models_not_prepared') from exc


class Embeddings:
    """One Bekko encoder and one Horizon cross-encoder, sharing a CPU gate."""
    def __init__(self,cfg):
        self.cfg=cfg;self.model=None;self.ranker=None;self.profile=None
        self._load_lock=threading.Lock();self._infer_lock=threading.Lock()

    def load(self,on_progress=None):
        if self.model is not None:return
        with self._load_lock:
            if self.model is not None:return
            def stage(message):
                LOG.info('Inicialización del motor vectorial: %s',message)
                if on_progress:on_progress(message)

            stage('Verificando integridad de Bekko y Horizon')
            from tokenizers import Tokenizer
            import onnxruntime as ort
            manifests={}
            for kind,model_id,revision,files in artifact_specs():
                folder=self.cfg.model_dir/kind/revision
                manifests[kind]=verified_manifest(folder,model_id,revision,files)
            bekko=self.cfg.model_dir/'bekko'/EMBEDDING_REVISION
            horizon=self.cfg.model_dir/'horizon'/RERANK_REVISION
            stage('Cargando tokenizadores de Bekko y Horizon')
            self.tokenizer=Tokenizer.from_file(str(bekko/'tokenizer.json'))
            self.tokenizer.no_truncation();self.tokenizer.no_padding()
            self.encoder_tokenizer=Tokenizer.from_file(str(bekko/'tokenizer.json'))
            self.encoder_tokenizer.enable_padding(pad_id=0,pad_token='<pad>')
            self.encoder_tokenizer.enable_truncation(max_length=512)
            self.rank_tokenizer=Tokenizer.from_file(str(horizon/'tokenizer.json'))
            self.rank_tokenizer.enable_padding(pad_id=0,pad_token='<pad>')
            self.rank_tokenizer.enable_truncation(max_length=384,strategy='only_second')
            self.query_tokenizer=Tokenizer.from_file(str(horizon/'tokenizer.json'))
            self.query_tokenizer.enable_truncation(max_length=120)
            options=ort.SessionOptions();options.intra_op_num_threads=self.cfg.embedding_threads
            options.inter_op_num_threads=1;options.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
            stage('Inicializando Horizon ONNX en CPU')
            ranker=ort.InferenceSession(str(horizon/'onnx/model_quantized.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
            if self.cfg.embedding_backend=='openvino':
                import openvino as ov
                stage('Compilando Bekko OpenVINO en CPU')
                model=ov.Core().compile_model(str(bekko/'openvino/openvino_model.xml'),'CPU',{
                    'INFERENCE_NUM_THREADS':self.cfg.embedding_threads,'NUM_STREAMS':1,'PERFORMANCE_HINT':'LATENCY'})
                self.input_names={port.any_name for port in model.inputs}
            else:
                model=ort.InferenceSession(str(bekko/'onnx/model.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
                self.input_names={item.name for item in model.get_inputs()}
            profile={'engine':ENGINE_VERSION,'model':EMBEDDING_ID,'revision_resolved':EMBEDDING_REVISION,
                'dim':DIMENSIONS,'pooling':'masked_mean','normalize':True,'query_prefix':'','passage_prefix':'',
                'runtime':self.cfg.embedding_backend,'max_input_tokens':512,'sparse':'lancedb/bm25-spanish',
                'reranker':RERANK_ID,'reranker_revision':RERANK_REVISION,'reranker_tokens':384,
                'onnxruntime':importlib.metadata.version('onnxruntime'),
                'openvino':importlib.metadata.version('openvino'),
                'artifact_hashes':{kind:{name:meta['sha256'] for name,meta in m['files'].items()} for kind,m in manifests.items()}}
            profile['fingerprint']=hashlib.sha256(json.dumps(profile,sort_keys=True).encode()).hexdigest()
            self.profile=profile;self.ranker=ranker;self.model=model
            stage('Bekko y Horizon quedaron inicializados')

    def count(self,text):
        self.load();return len(self.tokenizer.encode(text,add_special_tokens=True).ids)

    def _encode(self,texts):
        enc=self.encoder_tokenizer.encode_batch(texts)
        data={'input_ids':np.asarray([e.ids for e in enc],dtype=np.int64),
              'attention_mask':np.asarray([e.attention_mask for e in enc],dtype=np.int64)}
        feeds={key:value for key,value in data.items() if key in self.input_names}
        if self.cfg.embedding_backend=='openvino':
            request=self.model.create_infer_request();request.start_async(feeds)
            if not request.wait_for(30000):
                request.cancel()
                try:request.wait()
                except RuntimeError:pass
                raise DomainError('Se agotó el plazo de inferencia.',503,'inference_timeout')
            output=np.array(request.get_output_tensor(0).data,copy=True)
        else:output=self._onnx(self.model,feeds)
        if output.ndim==3:
            mask=data['attention_mask'][...,None]
            output=(output*mask).sum(axis=1)/np.maximum(mask.sum(axis=1),1)
        if output.shape!=(len(texts),DIMENSIONS) or not np.isfinite(output).all():
            raise DomainError('Bekko devolvió vectores inválidos.',503,'invalid_vectors')
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
        if any(self.count(text)>512 for text in texts):raise DomainError('Entrada Bekko excede 512 tokens.')
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
                      'attention_mask':np.asarray([e.attention_mask for e in enc],dtype=np.int64)}
                remaining=deadline-time.monotonic()
                if remaining<=0:raise DomainError('Se agotó el plazo de reordenación.',503,'rerank_timeout')
                output=self._onnx(self.ranker,{k:v for k,v in data.items() if k in names},remaining)
                scores.extend((1/(1+np.exp(-np.clip(output[:,0],-60,60)))).tolist())
        if len(scores)!=len(texts) or not np.isfinite(scores).all():raise DomainError('Horizon devolvió puntajes inválidos.',503,'invalid_rerank')
        return scores
