"""Versioned LanceDB tables: exact cosine + Spanish BM25 with RRF fusion."""
import logging
import math
import re
import threading
from pathlib import Path
from ..errors import DomainError
from .neural import DIMENSIONS

LOG = logging.getLogger(__name__)


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

    def ids(self,name):
        with self.lock:
            return set(self.db.open_table(self.name(name)).to_arrow().column('id').to_pylist())

    def search(self,name,dense,lexical,candidates=30,limit=20,zones=None,opportunity_ids=None,record_types=None):
        try:
            return self._search(name,dense,lexical,candidates,limit,zones,opportunity_ids,record_types)
        except DomainError:
            raise
        except Exception as exc:
            LOG.warning('Búsqueda física no disponible: colección=%s tipo=%s', name, type(exc).__name__)
            raise DomainError('El índice de conocimiento no está disponible temporalmente.',503,'index_unavailable') from exc

    def _search(self,name,dense,lexical,candidates,limit,zones,opportunity_ids,record_types):
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

    def inspect(self, name, expected):
        """Bounded collection readiness, separate from connectivity to LanceDB."""
        try:
            if not (self.cfg.lance_dir / (self.name(name)+'.lance')).is_dir():
                return {'ready': False, 'code': 'index_missing'}
            with self.lock:
                if not self.exists(name):
                    return {'ready': False, 'code': 'index_missing'}
                table = self.db.open_table(self.name(name))
                count = table.count_rows()
                required = {'id','record_id','text','audience','topic','zones','opportunity_id','record_type','vector'}
                if not required <= set(table.schema.names) or table.schema.field('vector').type.list_size != DIMENSIONS:
                    return {'ready': False, 'code': 'index_schema_invalid'}
                if count != expected or count <= 0:
                    return {'ready': False, 'code': 'index_incomplete', 'count': count}
                indices = list(table.list_indices())
                fts=next((i for i in indices if str(i.index_type).upper()=='FTS' and 'text' in i.columns),None)
                if fts is None:
                    return {'ready': False, 'code': 'index_fts_missing', 'count': count}
                if fts.num_indexed_rows!=count or fts.num_unindexed_rows:
                    return {'ready':False,'code':'index_fts_incomplete','count':count}
                details=fts.index_details or {}
                if (str(details.get('language','')).lower()!='spanish' or not details.get('stem')
                        or not details.get('ascii_folding') or not details.get('remove_stop_words')):
                    return {'ready':False,'code':'index_fts_incompatible','count':count}
                table.search('información', query_type='fts', fts_columns='text').limit(1).to_list()
                signature = [table.version, (self.cfg.lance_dir / (name+'.lance')).stat().st_ino]
                return {'ready': True, 'code': None, 'count': count, 'signature': signature}
        except Exception:
            return {'ready': False, 'code': 'index_unavailable'}

    def restore_rows(self, name, rows):
        from .recovery import vector
        if any(r.get('audience') != 'public' for r in rows):
            raise DomainError('La restauración rechaza contenido interno.', 503, 'snapshot_invalid')
        for row in rows:
            vector(row['vector'])
        with self.lock:
            self.db.open_table(self.name(name)).merge_insert('id').when_matched_update_all().when_not_matched_insert_all().execute(rows)

    def matches(self, name, expected_rows):
        """Full physical content verification, only in the recovery worker/CLI."""
        from .recovery import digest, vector
        if not self.inspect(name, len(expected_rows))['ready']:
            return False
        try:
            with self.lock:
                rows = self.db.open_table(self.name(name)).to_arrow().to_pylist()
            for row in rows:
                row['vector'] = vector(row['vector'])
            return digest(sorted(rows, key=lambda r:r['id'])) == digest(sorted(expected_rows, key=lambda r:r['id']))
        except Exception:
            return False

    def rename(self, old, new):
        """Promote a local dataset atomically on the same volume.

        LanceDB OSS 0.40 doesn't implement rename_table. Data and FTS references
        in these .lance datasets are relative (covered by real tests). The caller
        holds database and volume writer locks. Never overwrite a destination.
        """
        with self.lock:
            root = self.cfg.lance_dir.resolve()
            source = root / (self.name(old)+'.lance')
            target = root / (self.name(new)+'.lance')
            if source.is_symlink() or target.is_symlink() or not source.is_dir():
                raise DomainError('La colección local no permite promoción segura.',503,'index_integrity_failed')
            if target.exists():
                raise DomainError('El destino físico ya existe; no se sobrescribió.', 503, 'recovery_conflict')
            source.rename(target)
            self._db = None
