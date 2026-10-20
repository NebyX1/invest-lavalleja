"""Versioned LanceDB tables: exact cosine + Spanish BM25 with RRF fusion."""
import math
import re
import threading
from ..errors import DomainError
from .neural import DIMENSIONS


def literal(value):
    return "'"+str(value).replace("'","''")+"'"


class LanceStore:
    def __init__(self,cfg):
        self.cfg=cfg;self._db=None;self.lock=threading.RLock()

    @property
    def db(self):
        with self.lock:
            if self._db is None:
                import lancedb
                self._db=lancedb.connect(str(self.cfg.lance_dir))
            return self._db

    @staticmethod
    def name(name):
        if not re.fullmatch(r'gianna_[a-zA-Z0-9_]+',name):raise DomainError('Nombre de índice inválido.')
        return name

    def exists(self,name):
        name=self.name(name);token=None
        while True:
            result=self.db.list_tables(page_token=token,limit=100)
            if name in result.tables:return True
            token=result.page_token
            if not token:return False

    def create(self,name):
        import pyarrow as pa
        schema=pa.schema([
            pa.field('id',pa.string()),pa.field('record_id',pa.string()),pa.field('text',pa.string()),
            pa.field('audience',pa.string()),pa.field('topic',pa.string()),pa.field('zones',pa.list_(pa.string())),
            pa.field('opportunity_id',pa.string()),pa.field('record_type',pa.string()),
            pa.field('vector',pa.list_(pa.float32(),DIMENSIONS))])
        with self.lock:
            self.db.create_table(self.name(name),schema=schema,exist_ok=True)

    def upsert(self,name,chunks,dense,lexical):
        rows=[]
        for chunk,vector,text in zip(chunks,dense,lexical,strict=True):
            if chunk.get('audience')!='public':raise DomainError('El índice público rechaza registros internos.')
            if len(vector)!=DIMENSIONS or not all(math.isfinite(v) for v in vector):raise DomainError('Vector incompatible.')
            rows.append({'id':chunk['id'],'record_id':chunk['record_id'],'text':text,'vector':vector,
                'audience':'public','topic':chunk['topic'],'zones':chunk.get('zones',[]),
                'opportunity_id':chunk.get('opportunity_id') or '', 'record_type':chunk.get('record_type','fact')})
        with self.lock:
            self.db.open_table(self.name(name)).merge_insert('id').when_matched_update_all().when_not_matched_insert_all().execute(rows)

    def finalize(self,name):
        from lancedb.index import FTS
        with self.lock:
            self.db.open_table(self.name(name)).create_index('text',config=FTS(
                language='Spanish',stem=True,ascii_folding=True,remove_stop_words=True),replace=True)

    def count(self,name):
        with self.lock:return self.db.open_table(self.name(name)).count_rows()

    def search(self,name,dense,lexical,candidates=30,limit=20,zones=None,opportunity_ids=None,record_types=None):
        clauses=["audience = 'public'"]
        if zones:clauses.append('('+' OR '.join('array_contains(zones, '+literal(z)+')' for z in zones)+')')
        if opportunity_ids:clauses.append('opportunity_id IN ('+','.join(literal(o) for o in opportunity_ids)+')')
        if record_types:clauses.append('record_type IN ('+','.join(literal(t) for t in record_types)+')')
        expression=' AND '.join(clauses)
        with self.lock:
            table=self.db.open_table(self.name(name))
            dense_rows=table.search(dense,query_type='vector').distance_type('cosine').where(expression,prefilter=True).limit(candidates).to_list()
            lexical_rows=(table.search(lexical[:4000],query_type='fts',fts_columns='text').where(expression,prefilter=True).limit(candidates).to_list()
                          if lexical.strip() else [])
        scores={};channels={}
        for channel,rows in (('dense',dense_rows),('bm25',lexical_rows)):
            for rank,row in enumerate(rows,1):
                scores[row['id']]=scores.get(row['id'],0)+1/(60+rank)
                channels.setdefault(row['id'],[]).append(channel)
        return [{'id':key,'score':scores[key],'channels':channels[key]}
                for key in sorted(scores,key=lambda key:(-scores[key],key))[:limit]]

    def delete(self,name):
        with self.lock:
            if self.exists(name):self.db.drop_table(self.name(name))

    def health(self):
        self.db.list_tables(limit=1)
        return {'engine':'LanceDB','ready':True}
