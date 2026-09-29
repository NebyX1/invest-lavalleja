"""One E5 model instance per process. No CUDA, PyTorch, reranker or LLM process."""
from pathlib import Path
import hashlib
import json
import importlib.metadata
import threading
import time
import httpx
from ..errors import DomainError


class Embeddings:
    def __init__(self,cfg):
        self.cfg=cfg;self._load_lock=threading.Lock();self._infer_lock=threading.Lock()
        self.model=None;self.sparse=None;self.tokenizer=None;self.profile=None

    def load(self):
        if self.model is not None:return
        with self._load_lock:
            if self.model is not None:return
            from fastembed import TextEmbedding,SparseTextEmbedding
            from fastembed.common.model_description import PoolingType,ModelSource
            from huggingface_hub import snapshot_download
            from tokenizers import Tokenizer
            model_file=self.cfg.e5_model_file
            if model_file!='onnx/model.onnx':
                raise DomainError('Esta versión valida únicamente la exportación E5 onnx/model.onnx. Cambiarla exige pruebas y reindexación.')
            path=Path(snapshot_download(repo_id='intfloat/multilingual-e5-small',revision=self.cfg.e5_revision,
                cache_dir=str(self.cfg.model_dir/'hub'),allow_patterns=['config.json','tokenizer.json','tokenizer_config.json','special_tokens_map.json','sentencepiece.bpe.model',model_file,model_file+'_data']))
            tokenizer=Tokenizer.from_file(str(path/'tokenizer.json'))
            tokenizer.no_truncation();tokenizer.no_padding()
            alias='gianna-multilingual-e5-small'
            supported={x['model'] for x in TextEmbedding.list_supported_models()}
            if alias not in supported:
                TextEmbedding.add_custom_model(model=alias,pooling=PoolingType.MEAN,normalization=True,
                  sources=ModelSource(hf='intfloat/multilingual-e5-small'),dim=384,model_file=model_file)
            model=TextEmbedding(model_name=alias,specific_model_path=str(path),cache_dir=str(self.cfg.model_dir/'fastembed'),
                threads=self.cfg.embedding_threads,providers=['CPUExecutionProvider'],cuda=False)
            sparse=SparseTextEmbedding(model_name='Qdrant/bm25',language='spanish',avg_len=256,
                cache_dir=str(self.cfg.model_dir/'fastembed'))
            digest=hashlib.sha256()
            for f in sorted([path/model_file,path/'tokenizer.json']+[p for p in (path/'onnx').glob('*.onnx_data')]):
                with f.open('rb') as stream:
                    for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
            digest.update(json.dumps({'pooling':'mean','normalize':True,'fastembed':importlib.metadata.version('fastembed'),
                'sparse':'Qdrant/bm25','language':'spanish','avg_len':256,'passage_prefix':'passage: ','query_prefix':'query: '},sort_keys=True).encode())
            self.profile={'model':'intfloat/multilingual-e5-small','revision_resolved':path.name,'model_file':model_file,
                'fingerprint':digest.hexdigest(),'dim':384,'pooling':'mean','normalize':True,'query_prefix':'query: ',
                'passage_prefix':'passage: ','runtime':'CPUExecutionProvider','fastembed':importlib.metadata.version('fastembed'),
                'sparse':'Qdrant/bm25','sparse_language':'spanish','sparse_avg_len':256}
            self.tokenizer=tokenizer;self.sparse=sparse;self.model=model

    def count(self,text):
        self.load()
        return len(self.tokenizer.encode(text,add_special_tokens=True).ids)

    def documents(self,texts,lexical_texts):
        self.load()
        if any(self.count(t)>512 for t in texts):raise DomainError('Se rechazó una entrada E5 de más de 512 tokens.')
        with self._infer_lock:
            dense=list(self.model.embed(texts,batch_size=self.cfg.embedding_batch_size,parallel=None))
            sparse=list(self.sparse.embed(lexical_texts,batch_size=self.cfg.embedding_batch_size,parallel=None))
        if len(dense)!=len(texts) or any(len(v)!=384 for v in dense):raise DomainError('Salida de embeddings inválida.',503)
        return [v.tolist() for v in dense],[{'indices':v.indices.tolist(),'values':v.values.tolist()} for v in sparse]

    def query(self,text):
        self.load();text=text.strip()
        # Explicit bounded query condensation; source passages are never truncated by the model runtime.
        while self.count('query: '+text)>500:
            text=text[:max(1,int(len(text)*0.85))]
        with self._infer_lock:
            dense=next(self.model.embed(['query: '+text],batch_size=1,parallel=None)).tolist()
            sparse=next(self.sparse.query_embed(text))
        return dense,{'indices':sparse.indices.tolist(),'values':sparse.values.tolist()}


class Qdrant:
    """REST API through an HTTP connection pool; no extra inference service."""
    def __init__(self,cfg,client=None):
        self.client=client or httpx.Client(base_url=cfg.qdrant_url,headers={'api-key':cfg.qdrant_api_key} if cfg.qdrant_api_key else {},
             timeout=httpx.Timeout(30,connect=5),limits=httpx.Limits(max_connections=6,max_keepalive_connections=3),follow_redirects=False,trust_env=False)

    def request(self,method,path,**kw):
        try:
            response=self.client.request(method,path,**kw)
            response.raise_for_status()
            return response.json().get('result')
        except (httpx.HTTPError,ValueError) as exc:
            raise DomainError('Qdrant no pudo completar la operación. Revisá conexión y estado del servicio.',503,'qdrant_unavailable') from exc

    def exists(self,name):
        try:
            r=self.client.get('/collections/'+name)
            if r.status_code==404:return False
            r.raise_for_status();return True
        except httpx.HTTPError as exc:raise DomainError('No se pudo consultar Qdrant.',503,'qdrant_unavailable') from exc

    def create(self,name):
        if self.exists(name):return
        self.request('PUT','/collections/'+name,json={'vectors':{'dense':{'size':384,'distance':'Cosine'}},
            'sparse_vectors':{'bm25':{'modifier':'idf'}},'shard_number':1,
            'hnsw_config':{'m':8},'optimizers_config':{'default_segment_number':1}})
        for field in ('audience','record_id','topic'):
            self.request('PUT',f'/collections/{name}/index',params={'wait':'true'},json={'field_name':field,'field_schema':'keyword'})

    def upsert(self,name,chunks,dense,sparse):
        points=[]
        for c,d,s in zip(chunks,dense,sparse,strict=True):
            points.append({'id':c['id'],'vector':{'dense':d,'bm25':s},'payload':{
                'record_id':c['record_id'],'audience':'public','topic':c['topic'],'title':c['title'],
                'evidence_type':c['evidence_type'],'cutoff_date':c['cutoff_date'],'source_refs':c['source_refs']}})
        self.request('PUT',f'/collections/{name}/points',params={'wait':'true'},json={'points':points})

    def count(self,name):
        return self.request('POST',f'/collections/{name}/points/count',json={'exact':True})['count']

    def search(self,name,dense,sparse,candidates=20,limit=8):
        filters={'must':[{'key':'audience','match':{'value':'public'}}]}
        payload={'prefetch':[{'query':dense,'using':'dense','limit':candidates,'filter':filters},
                    {'query':sparse,'using':'bm25','limit':candidates,'filter':filters}],
                 'query':{'fusion':'rrf'},'limit':limit,'with_payload':True,'with_vector':False}
        return self.request('POST',f'/collections/{name}/points/query',json=payload)['points']

    def delete(self,name):
        if self.exists(name):self.request('DELETE','/collections/'+name)

    def health(self):
        return self.request('GET','/collections')


def thinking_mode(model):
    # Verified against the Cloud catalogue: this model accepts false and
    # returns its user-facing answer without spending the cap on thought.
    return False if model.startswith('deepseek-v4.1-flash') else 'low'


class Ollama:
    def __init__(self,cfg,client=None):
        self.cfg=cfg
        self.client=client or httpx.Client(base_url=cfg.ollama_url,headers={'Authorization':'Bearer '+cfg.ollama_api_key},
              timeout=httpx.Timeout(80,connect=8),limits=httpx.Limits(max_connections=4,max_keepalive_connections=3),follow_redirects=False,trust_env=False)

    def models(self):
        if not self.cfg.ollama_api_key:raise DomainError('Falta OLLAMA_API_KEY en .env.',503,'ollama_not_configured')
        try:
            r=self.client.get('/api/tags');r.raise_for_status()
            return sorted({x.get('name',x.get('model','')) for x in r.json().get('models',[]) if x.get('name') or x.get('model')})
        except (httpx.HTTPError,ValueError) as exc:raise DomainError('No se pudo consultar el catálogo de Ollama Cloud.',503,'ollama_unavailable') from exc

    def chat(self,messages,settings,think=None):
        if not self.cfg.ollama_api_key or not settings.model:
            raise DomainError('Configurá OLLAMA_API_KEY y seleccioná un modelo en Ajustes.',503,'ollama_not_configured')
        payload={'model':settings.model,'messages':messages,'stream':False,
                 'options':{'temperature':settings.temperature,'num_predict':settings.max_output_tokens}}
        if think is not None:
            payload['think']=think
        for attempt in range(2):
            try:
                response=self.client.post('/api/chat',json=payload)
                response.raise_for_status(); data=response.json()
                text=data.get('message',{}).get('content','')
                if not isinstance(text,str) or not text.strip():
                    if attempt==0:
                        payload['options']['num_predict']=min(2000,max(1000,settings.max_output_tokens*2))
                        continue
                    raise ValueError('empty response')
                return text[:18000],{'prompt_tokens':data.get('prompt_eval_count'),'output_tokens':data.get('eval_count')}
            except httpx.HTTPStatusError as exc:
                # Retry only explicit throttling/unavailable responses; do not
                # duplicate a possibly completed generation after a timeout.
                if attempt==0 and exc.response.status_code in {429,503}:
                    time.sleep(0.8)
                    continue
                raise DomainError('El proveedor de respuestas no está disponible. La base de conocimiento no se modificó.',503,'ollama_unavailable') from exc
            except httpx.ConnectError as exc:
                if attempt==0:
                    time.sleep(0.8)
                    continue
                raise DomainError('El proveedor de respuestas no está disponible. La base de conocimiento no se modificó.',503,'ollama_unavailable') from exc
            except (httpx.HTTPError,ValueError) as exc:
                raise DomainError('El proveedor de respuestas no está disponible. La base de conocimiento no se modificó.',503,'ollama_unavailable') from exc
