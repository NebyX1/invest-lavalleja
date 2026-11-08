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
from ..observability import event, safe_exception
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
    reason = 'profile'
    actual_count = None
    source_counts = {'sql': 0, 'backup': 0, 'cache': 0}
    invalid_sources = {'sql': 0, 'backup': 0, 'cache': 0}
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
        reason = 'metadata'
        records = {r['record_key']: json.loads(r['content_json']) for r in db.all(
            'SELECT record_key,content_json FROM version_records WHERE version_id=?', (version['id'],))}
        sources = {r['source_key']: json.loads(r['content_json']) for r in db.all(
            'SELECT source_key,content_json FROM version_sources WHERE version_id=?', (version['id'],))}
        if not records or any(r.get('audience') != 'public' or not r.get('enabled', True) for r in records.values()):
            reason = 'audience'
            raise ValueError('audience')
        rows = db.all('SELECT * FROM chunks WHERE version_id=? ORDER BY id', (version['id'],))
        actual_count = len(rows)
        if not rows or len(rows) != version['chunk_count']:
            reason = 'count'
            raise ValueError('count')
        reason = 'metadata'
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
        readers = []
        if backup_path.exists():
            readers.append(lambda: json.loads(backup_path.read_text(encoding='utf-8')))
        if cfg.storage_backend == 'minio':
            from .objects import objects
            candidate = objects(cfg).read_json('recovery/backups/'+version['id']+'.json')
            if candidate is not None:
                readers.append(lambda candidate=candidate: candidate)
        for candidate_reader in readers:
            try:
                candidate = candidate_reader()
                if not (candidate['version_id'] == version['id'] and candidate['metadata'] == metadata
                        and candidate['fingerprint'] == profile['fingerprint']
                        and isinstance(candidate['rows'], list) and len(candidate['rows']) == len(chunks)
                        and digest(candidate['rows']) == candidate['digest']):
                    raise ValueError('backup metadata')
                indexed = {row['id']: row for row in candidate['rows']}
                if len(indexed) != len(chunks) or set(indexed) != {c['id'] for c in chunks}:
                    raise ValueError('backup coverage')
                validated = {}
                for chunk in chunks:
                    proposed = indexed[chunk['id']]
                    dense = vector(proposed['vector'])
                    if physical_row(chunk, dense) != proposed:
                        raise ValueError('backup row metadata')
                    validated[chunk['id']] = dense
                if backup is not None and backup != validated:
                    reason = 'vector_sources_disagree'
                    raise ValueError('backup sources disagree')
                backup = validated
            except (OSError, ValueError, KeyError, TypeError, OverflowError, struct.error) as exc:
                if reason == 'vector_sources_disagree':
                    raise
                invalid_sources['backup'] += 1
                event(LOG, 'recovery.backup_rejected', level=logging.WARNING,
                      version_id=version['id'], code='backup_invalid', exception=safe_exception(exc))
        restored = []
        for row, c in zip(rows, chunks, strict=True):
            # Each source is independently validated. A corrupt optional source
            # cannot poison another verified source, while two valid sources
            # disagreeing must never be resolved by guessing.
            candidates = {}
            if backup is not None:
                candidates['backup'] = backup[c['id']]
            raw = row['vector_json']
            if raw is not None:
                try:
                    candidates['sql'] = vector(json.loads(raw))
                except (ValueError, TypeError, OverflowError, struct.error):
                    invalid_sources['sql'] += 1
            if 'sql' not in candidates:
                cached = db.one('SELECT dense_json FROM embedding_cache WHERE fingerprint=? AND embedding_hash=?',
                                (profile['fingerprint'], row['embedding_hash']))
                if cached:
                    try:
                        candidates['cache'] = vector(json.loads(cached['dense_json']))
                    except (ValueError, TypeError, OverflowError, struct.error):
                        invalid_sources['cache'] += 1
            if not candidates:
                reason = 'missing_vector'
                raise ValueError('missing vector')
            source = next(name for name in ('sql', 'backup', 'cache') if name in candidates)
            dense = candidates[source]
            if any(value != dense for value in candidates.values()):
                reason = 'backup_sql_disagreement' if 'sql' in candidates else 'vector_sources_disagree'
                raise ValueError('verified sources disagree')
            source_counts[source] += 1
            restored.append(physical_row(c, dense))
        return {'version_id': version['id'], 'fingerprint': profile['fingerprint'], 'metadata': metadata,
                'digest': digest(restored), 'rows': restored, 'profile': profile,
                'backup_used': bool(source_counts['backup']), 'source_counts': source_counts,
                'invalid_sources': invalid_sources}
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError, struct.error) as exc:
        error = DomainError('La fotografía publicada no permite una restauración exacta. Se requiere revisión supervisada; la publicación se conserva.',
                            503, 'snapshot_invalid')
        error.details = {'reason': reason, 'source_counts': source_counts,
                         'invalid_sources': invalid_sources}
        version_id = version.get('id')
        if isinstance(version_id, str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', version_id):
            error.details['version_id'] = version_id
        if isinstance(version.get('chunk_count'), int):
            error.details['expected_chunks'] = version['chunk_count']
        if actual_count is not None:
            error.details['actual_chunks'] = actual_count
        raise error from exc


class KnowledgeRecovery:
    def __init__(self, db, cfg, knowledge, embeddings, store):
        self.db, self.cfg, self.knowledge, self.embeddings, self.store = db, cfg, knowledge, embeddings, store
        self._lock = threading.RLock()
        self._state = 'initializing'; self._code = None; self._version = None
        self._verified = {}  # Physical content digest last validated by this process.
        self.enqueue = None

    def state(self, value, code=None, version=None):
        with self._lock:
            previous = self._state
            self._state, self._code, self._version = value, code, version
        event(LOG, 'recovery.state_changed', previous=previous, state=value, code=code, version_id=version)

    def phase(self):
        """Cheap worker progress label; no SQL, filesystem checks or inference."""
        with self._lock:
            return self._state

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
            if exc.code.startswith(('storage_', 'minio_', 'cache_')) or exc.code in {'snapshot_invalid','embedding_mismatch','database_unavailable'}:
                state = 'failed'
            return {'state': state, 'code': code, 'available': False, 'message': MESSAGES.get(state, MESSAGES['failed'])}
        except Exception as exc:
            event(LOG, 'recovery.availability_failed', level=logging.ERROR,
                  code='knowledge_unavailable', exception=safe_exception(exc))
            return {'state': 'failed', 'code': 'knowledge_unavailable', 'available': False, 'message': MESSAGES['failed']}

    def require(self, version):
        status = self.status(version)
        if not status['available']:
            if self.enqueue:
                try:self.enqueue(version=version)
                except Exception as exc:
                    event(LOG, 'recovery.enqueue_failed', level=logging.WARNING,
                          version_id=version['id'], exception=safe_exception(exc))
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
                    'source_counts':data['source_counts'],'invalid_sources':data['invalid_sources'],
                    'index_valid':self.store.matches(version['collection_name'],data['rows']),'changed':False}
        try:
            # Diagnose infrastructure before even creating the writer lock.
            # Recheck under exclusion as a deployment can change the volume.
            storage_identity(self.db, self.cfg, adopt=adopt_storage)
            with self.db.physical_lock(), writer_lock(self.cfg):
                storage_identity(self.db, self.cfg, adopt=adopt_storage)
                data = snapshot(self.db, self.cfg, version)
                matches = self.store.matches(version['collection_name'], data['rows'])
                plan = {'version_id': version['id'], 'vectors': len(data['rows']), 'fingerprint': data['fingerprint'],
                        'backup_used': data['backup_used'], 'source_counts':data['source_counts'],
                        'invalid_sources':data['invalid_sources'], 'index_valid': matches, 'changed': False}
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
            event(LOG, 'recovery.blocked', level=logging.ERROR,
                  version_id=version['id'], code=exc.code,
                  validation=getattr(exc, 'details', {}), exception=safe_exception(exc))
            raise
        except Exception as exc:
            self.state('failed', 'recovery_failed', version['id'])
            event(LOG, 'recovery.failed', level=logging.ERROR,
                  version_id=version['id'], code='recovery_failed', exception=safe_exception(exc))
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
        document = {k: v for k, v in data.items() if k not in {'profile', 'backup_used', 'source_counts', 'invalid_sources'}}
        if self.cfg.storage_backend == 'minio':
            from .objects import objects
            objects(self.cfg).put_json('recovery/backups/'+data['version_id']+'.json', document)
        atomic_json(path, document)
