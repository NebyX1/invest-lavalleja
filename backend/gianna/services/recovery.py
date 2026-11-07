"""Restore physical indexes from immutable SQL snapshots; never publish or edit versions."""
import hashlib
import json
import logging
import math
import re
import struct
import threading
import uuid

from ..chunking import input_prefix
from ..errors import Cancelled, DomainError
from .neural import DIMENSIONS, MODEL_PROFILES
from .storage import atomic_json, storage_identity, writer_lock

LOG = logging.getLogger(__name__)
MESSAGES = {
    'initializing': 'Inicializando conocimiento.',
    'restoring_models': 'Restaurando el motor de conocimiento.',
    'restoring_index': 'Recuperando el índice de conocimiento.',
    'ready': 'Listo para consultar.',
    'no_knowledge': 'Todavía no hay una base publicada.',
    'failed': 'El conocimiento no está disponible temporalmente. El equipo debe revisar el diagnóstico.',
}


def digest(rows):
    return hashlib.sha256(json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def vector(value):
    if not isinstance(value, list) or len(value) != DIMENSIONS:
        raise ValueError('dimension')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value):
        raise ValueError('finite')
    result = list(struct.unpack('<' + 'f' * DIMENSIONS, struct.pack('<' + 'f' * DIMENSIONS, *value)))
    if not all(math.isfinite(v) for v in result) or sum(v*v for v in result) < 1e-20:
        raise ValueError('norm')
    return result


def physical_row(chunk, dense):
    return {'id': chunk['id'], 'record_id': chunk['record_id'], 'text': chunk['sparse_text'],
            'audience': 'public', 'topic': chunk['topic'], 'zones': chunk.get('zones', []),
            'opportunity_id': chunk.get('opportunity_id') or '', 'record_type': chunk.get('record_type', 'fact'),
            'vector': dense}


def snapshot(db, cfg, version):
    """Validate metadata before using a backup, SQL vector or fingerprint-scoped cache."""
    try:
        profile = json.loads(version['profile_json'])
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', version['id']):
            raise ValueError('version id')
        if version['status'] != 'ready' or profile.get('engine') not in MODEL_PROFILES:
            raise ValueError('version')
        if profile.get('dim') != DIMENSIONS or not re.fullmatch(r'[a-f0-9]{64}', profile.get('fingerprint', '')):
            raise ValueError('profile')
        expected_context = 'bekko-context-v2' if profile['engine'] == 'bekko-horizon-lance-v2' else 'cards-context-v5'
        if profile.get('contextualizer_version') != expected_context:
            raise ValueError('context')
        records = {r['record_key']: json.loads(r['content_json']) for r in db.all(
            'SELECT record_key,content_json FROM version_records WHERE version_id=?', (version['id'],))}
        sources = {r['source_key']: json.loads(r['content_json']) for r in db.all(
            'SELECT source_key,content_json FROM version_sources WHERE version_id=?', (version['id'],))}
        if not records or any(r.get('audience') != 'public' or not r.get('enabled', True) for r in records.values()):
            raise ValueError('audience')
        rows = db.all('SELECT * FROM chunks WHERE version_id=? ORDER BY id', (version['id'],))
        if not rows or len(rows) != version['chunk_count']:
            raise ValueError('count')
        chunks = []
        for row in rows:
            c = json.loads(row['content_json']); record = records[row['record_key']]
            if (c['id'] != row['id'] or c['record_id'] != row['record_key'] or c['position'] != row['position']
                    or c['audience'] != 'public' or c['text'] != row['text']
                    or c['contextualizer_version'] != expected_context or c['embedding_hash'] != row['embedding_hash']
                    or c['title'] != record['title'] or c['topic'] != record['topic']
                    or not set(c.get('source_refs', [])) <= set(sources)):
                raise ValueError('metadata')
            if record['text'][c['char_start']:c['char_end']].strip() != c['text']:
                raise ValueError('content')
            for key,default in (('zones',[]),('source_refs',[]),('opportunity_id',None),('section','')):
                if c.get(key,default) != record.get(key,default):
                    raise ValueError('record metadata')
            if (c['char_start'] < 0 or c['char_end'] > len(record['text']) or c['char_end'] <= c['char_start']
                    or c['text'] not in c['embedding_text'] or c['text'] not in c['sparse_text']):
                raise ValueError('representation')
            if profile['engine'] != 'bekko-horizon-lance-v2':
                expected_text=input_prefix(record)+c['text']
                if c['embedding_text'] != expected_text or c['sparse_text'] != expected_text:
                    raise ValueError('context representation')
            expected_hash = hashlib.sha256((expected_context+'\0'+c['embedding_text']+'\0'+c['sparse_text']).encode()).hexdigest()
            if expected_hash != c['embedding_hash']:
                raise ValueError('embedding hash')
            chunks.append(c)
        if {c['record_id'] for c in chunks} != set(records):
            raise ValueError('record coverage')
        metadata = digest({'version_id':version['id'],'profile':profile,'chunks':chunks,'records':records,'sources':sources})
        backup_path = cfg.data_dir / 'recovery' / 'backups' / (version['id']+'.json')
        backup = None
        if backup_path.exists():
            try:
                candidate = json.loads(backup_path.read_text(encoding='utf-8'))
                if (candidate['version_id'] == version['id'] and candidate['metadata'] == metadata
                        and candidate['fingerprint'] == profile['fingerprint']
                        and digest(candidate['rows']) == candidate['digest']):
                    backup = candidate['rows']
            except (OSError, ValueError, KeyError, TypeError):
                LOG.warning('Respaldo físico no válido para versión %s; se comprobará SQL.', version['id'])
        restored = []
        for i, (row, c) in enumerate(zip(rows, chunks, strict=True)):
            # Check an independent backup before SQL/cache fallbacks.
            dense = None
            if backup is not None and len(backup) == len(rows):
                proposed = vector(backup[i]['vector'])
                if physical_row(c, proposed) == backup[i]:
                    dense = proposed
            raw = row['vector_json']
            if raw is None:
                cached = db.one('SELECT dense_json FROM embedding_cache WHERE fingerprint=? AND embedding_hash=?',
                                (profile['fingerprint'], row['embedding_hash']))
                raw = cached['dense_json'] if cached else None
            if raw:
                sql_dense = vector(json.loads(raw))
                if dense is not None and dense != sql_dense:
                    raise ValueError('backup disagrees with SQL')
                dense = sql_dense
            if dense is None:
                raise ValueError('missing vector')
            restored.append(physical_row(c, dense))
        return {'version_id': version['id'], 'fingerprint': profile['fingerprint'], 'metadata': metadata,
                'digest': digest(restored), 'rows': restored, 'profile': profile,
                'backup_used': bool(backup and backup == restored)}
    except (ValueError, KeyError, TypeError, OverflowError, struct.error) as exc:
        raise DomainError('La fotografía publicada no permite una restauración exacta. Se requiere revisión supervisada; la publicación se conserva.',
                          503, 'snapshot_invalid') from exc


class KnowledgeRecovery:
    def __init__(self, db, cfg, knowledge, embeddings, store):
        self.db, self.cfg, self.knowledge, self.embeddings, self.store = db, cfg, knowledge, embeddings, store
        self._lock = threading.RLock()
        self._state = 'initializing'; self._code = None; self._version = None
        self._verified = {}  # Physical content digest last validated by this process.
        self.enqueue = None

    def state(self, value, code=None, version=None):
        with self._lock:
            self._state, self._code, self._version = value, code, version
        LOG.info('Conocimiento: estado=%s codigo=%s version=%s', value, code, version)

    def status(self, version=None):
        """Cheap live collection checks. No downloads, model loads or editorial writes."""
        try:version = version or self.knowledge.active()
        except Exception:
            return {'state':'failed','code':'database_unavailable','available':False,'message':MESSAGES['failed']}
        if not version:
            return {'state': 'no_knowledge', 'code': 'no_knowledge', 'available': False, 'message': MESSAGES['no_knowledge']}
        try:
            storage_identity(self.db, self.cfg)
            if version['status'] != 'ready':
                raise DomainError('Versión no lista.', 503, 'version_not_ready')
            profile = json.loads(version['profile_json'])
            if not self.embeddings.ready_for(profile):
                engine = self.embeddings.for_profile(profile)
                if engine.model is not None:
                    raise DomainError('El motor cargado no coincide con la publicación.',503,'embedding_mismatch')
                raise DomainError('El motor se está preparando.', 503, 'warming_up')
            index = self.store.inspect(version['collection_name'], version['chunk_count'])
            if not index['ready']:
                raise DomainError('El índice publicado requiere recuperación.', 503, index['code'])
            if self._verified.get(version['id']) != index['signature']:
                raise DomainError('Verificando integridad del conocimiento.', 503, 'knowledge_initializing')
            return {'state': 'ready', 'code': None, 'available': True, 'message': MESSAGES['ready']}
        except DomainError as exc:
            with self._lock:
                state = self._state if self._version in {None, version['id']} and self._state != 'ready' else 'initializing'
                code = (self._code if state=='failed' and self._version==version['id'] and self._code
                        and exc.code in {'warming_up','knowledge_initializing'} else exc.code)
            if state == 'initializing':
                last = self.db.one("SELECT status,attempts FROM jobs WHERE kind='warmup' AND version_id=? ORDER BY created_at DESC LIMIT 1",(version['id'],))
                if last and last['status'] == 'failed' and last['attempts'] >= 3:state='failed'
            if exc.code in {'storage_mismatch','storage_not_mounted','snapshot_invalid','embedding_mismatch'}:
                state = 'failed'
            return {'state': state, 'code': code, 'available': False, 'message': MESSAGES.get(state, MESSAGES['failed'])}
        except Exception:
            LOG.exception('No se pudo verificar la disponibilidad del conocimiento.')
            return {'state': 'failed', 'code': 'knowledge_unavailable', 'available': False, 'message': MESSAGES['failed']}

    def require(self, version):
        status = self.status(version)
        if not status['available']:
            if self.enqueue:
                try:self.enqueue(version=version)
                except Exception:LOG.warning('No se pudo programar la recuperación técnica.')
            raise DomainError(status['message'], 503, status['code'])

    def verify(self, version, data=None):
        """Worker-only integrity gate, also used after an explicit editorial build."""
        data = data or snapshot(self.db, self.cfg, version)
        if not self.embeddings.ready_for(data['profile']):
            raise DomainError('La huella del motor no coincide con la publicación.',503,'embedding_mismatch')
        if not self.store.matches(version['collection_name'],data['rows']):
            raise DomainError('Falló la verificación del índice.',503,'index_integrity_failed')
        engine = self.embeddings.for_profile(data['profile'])
        dense, lexical = engine.query('información territorial')
        vector(dense)
        scores=engine.rerank('información territorial',['Información territorial de Lavalleja.'])
        if len(scores)!=1 or not math.isfinite(scores[0]):
            raise DomainError('El reranker no superó la prueba local.',503,'local_inference_failed')
        found = self.store.search(version['collection_name'],dense,lexical,4,4)
        if not found or not {r['id'] for r in found} <= {r['id'] for r in data['rows']}:
            raise DomainError('La búsqueda de prueba no recuperó evidencia válida.',503,'index_integrity_failed')
        self._backup(data)
        storage_identity(self.db,self.cfg,write=True)
        with self._lock:
            self._verified[version['id']] = self.store.inspect(version['collection_name'],len(data['rows']))['signature']

    def recover(self, version=None, *, apply=False, adopt_storage=False, progress=None):
        version = version or self.knowledge.active()
        if not version:
            self.state('no_knowledge')
            return {'state': 'no_knowledge', 'changed': False}
        def stage(state):
            self.state(state, version=version['id'])
            if progress: progress(MESSAGES[state])
        if not apply:
            storage_identity(self.db,self.cfg,adopt=adopt_storage)
            data=snapshot(self.db,self.cfg,version)
            return {'state':'diagnostic','version_id':version['id'],'vectors':len(data['rows']),
                    'fingerprint':data['fingerprint'],'backup_used':data['backup_used'],
                    'index_valid':self.store.matches(version['collection_name'],data['rows']),'changed':False}
        try:
            with self.db.physical_lock(), writer_lock(self.cfg):
                storage_identity(self.db, self.cfg, adopt=adopt_storage)
                data = snapshot(self.db, self.cfg, version)
                matches = self.store.matches(version['collection_name'], data['rows'])
                plan = {'version_id': version['id'], 'vectors': len(data['rows']), 'fingerprint': data['fingerprint'],
                        'backup_used': data['backup_used'], 'index_valid': matches, 'changed': False}
                stage('restoring_models')
                engine = self.embeddings.for_profile(data['profile'])
                from .artifacts import ensure_models
                ensure_models(self.cfg, engine.engine_version, progress)
                engine.load(progress)
                if engine.profile['fingerprint'] != data['fingerprint']:
                    raise DomainError('La huella del motor no coincide con la publicación. No se modificó la versión.', 503, 'embedding_mismatch')
                if not matches:
                    stage('restoring_index')
                    self._restore(version, data, progress)
                    plan['changed'] = True
                storage_identity(self.db,self.cfg,write=True,adopt=adopt_storage)
                self.verify(version,data)
                self.state('ready', version=version['id'])
                return {**plan, 'state': 'ready'}
        except Cancelled:
            self.state('initializing', 'recovery_interrupted', version['id'])
            raise
        except DomainError as exc:
            self.state('failed', exc.code, version['id'])
            raise
        except Exception as exc:
            self.state('failed', 'recovery_failed', version['id'])
            raise DomainError('Falló la recuperación técnica. La publicación se conserva.', 503, 'recovery_failed') from exc

    def _restore(self, version, data, progress):
        name = version['collection_name']
        staging = 'gianna_restore_' + version['id'] + '_' + data['digest'][:12]
        if not self.store.matches(staging, data['rows']):
            try:self.store.create(staging)
            except Exception:
                # Preserve an interrupted/corrupt staging directory, then retry
                # creation at the same deterministic name. Never touch a valid
                # canonical dataset here.
                self.store.rename(staging,'gianna_quarantine_stage_'+uuid.uuid4().hex)
                self.store.create(staging)
            # Resume only our own IDs. Preserve unrelated/corrupt staging data.
            if not self.store.ids(staging) <= {r['id'] for r in data['rows']}:
                staging += '_' + uuid.uuid4().hex[:8]
                self.store.create(staging)
            for start in range(0, len(data['rows']), self.cfg.embedding_batch_size):
                if progress: progress(MESSAGES['restoring_index'])
                self.store.restore_rows(staging, data['rows'][start:start+self.cfg.embedding_batch_size])
            self.store.finalize(staging)
            if not self.store.matches(staging, data['rows']):
                raise DomainError('La colección restaurada no superó la verificación.', 503, 'index_integrity_failed')
        if self.store.matches(name, data['rows']):
            return
        if self.store.exists(name):
            # Preserve invalid originals for diagnosis; never drop published collections.
            self.store.rename(name, 'gianna_quarantine_' + version['id'] + '_' + uuid.uuid4().hex[:12])
        self.store.rename(staging, name)
        if not self.store.matches(name, data['rows']):
            raise DomainError('Falló la verificación final del índice.', 503, 'index_integrity_failed')

    def _backup(self, data):
        path = self.cfg.data_dir / 'recovery' / 'backups' / (data['version_id'] + '.json')
        if path.exists():
            try:
                existing=json.loads(path.read_text(encoding='utf-8'))
                if (existing['digest']==data['digest'] and digest(existing['rows'])==data['digest']
                        and existing['metadata']==data['metadata']):
                    return
            except (OSError, ValueError, KeyError, TypeError):
                pass
            path.rename(path.with_name(path.name + '.' + uuid.uuid4().hex + '.previous'))
        atomic_json(path, {k: v for k, v in data.items() if k not in {'profile', 'backup_used'}})
