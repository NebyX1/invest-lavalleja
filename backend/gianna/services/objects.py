"""Private MinIO objects; local files are expendable, verified working copies.

No global bucket listing, public URLs, bucket policies, deletes or credentials in
logs. Inspection never creates a bucket or writes an object. SQL owns the binding
and publication; provisioning runs under the existing physical-writer lock.
"""
from functools import lru_cache
import copy
import hashlib
import io
import json
import logging
from pathlib import Path, PurePosixPath
import re
import time
from urllib.parse import urlparse
import uuid

from ..errors import Cancelled, DomainError
from ..observability import event, safe_exception

LOG = logging.getLogger(__name__)
PREFIX = 'gianna/v1/'
MARKER = '.gianna-storage.json'
SETTING = 'minio_storage_identity'
MAX_JSON_BYTES = 256 * 1024 * 1024
TRANSIENT = {'SlowDown', 'ServiceUnavailable', 'InternalError', 'RequestTimeout'}


def error(code, message, action, *, retryable=False):
    failure = DomainError(message, 503, code)
    failure.details = {'action': action, 'retryable': retryable}
    return failure


@lru_cache(maxsize=8)
def objects(cfg):
    return Objects(cfg)


class Objects:
    def __init__(self, cfg):
        self.cfg = cfg
        self._client = None
        self._health = None

    @property
    def client(self):
        cfg = self.cfg
        missing = [name for name in ('MINIO_ENDPOINT', 'MINIO_ACCESS_KEY', 'MINIO_SECRET_KEY', 'MINIO_BUCKET_NAME')
                   if not getattr(cfg, name.lower())]
        if missing:
            raise error('minio_configuration_missing', 'Falta configurar el almacenamiento MinIO de Gianna.',
                        'Configurá en el backend: ' + ', '.join(missing) + '. Las claves se guardan en el entorno del servicio.')
        endpoint = urlparse('//'+cfg.minio_endpoint)
        try:
            valid = (endpoint.hostname and not endpoint.username and not endpoint.password and
                     not endpoint.path and not endpoint.query and not endpoint.fragment and
                     not any(c.isspace() for c in cfg.minio_endpoint))
            endpoint.port
            from minio.helpers import check_bucket_name
            check_bucket_name(cfg.minio_bucket_name, strict=True)
            if not valid:
                raise ValueError()
        except ValueError:
            raise error('minio_configuration_invalid', 'La configuración de MinIO no es válida.',
                        'MINIO_ENDPOINT debe ser host:puerto, sin esquema, ruta ni credenciales; revisá también MINIO_BUCKET_NAME.') from None
        if self._client is None:
            import urllib3
            from minio import Minio
            self._client = Minio(cfg.minio_endpoint, access_key=cfg.minio_access_key,
                                 secret_key=cfg.minio_secret_key, secure=cfg.minio_secure,
                                 http_client=urllib3.PoolManager(timeout=urllib3.Timeout(connect=3, read=15), retries=False))
        return self._client

    def _call(self, operation, function):
        started = time.perf_counter()
        try:
            result = function()
            event(LOG, 'minio.operation_completed', operation=operation,
                  duration_ms=round((time.perf_counter()-started)*1000, 2))
            return result
        except (DomainError, Cancelled):
            raise
        except Exception as exc:
            vendor = getattr(exc, 'code', '')
            denied = vendor in {'AccessDenied', 'InvalidAccessKeyId', 'SignatureDoesNotMatch', 'InvalidToken'}
            code = 'minio_access_denied' if denied else 'minio_unavailable'
            failure = error(code, 'MinIO rechazó el acceso del backend.' if denied else 'MinIO no está disponible.',
                            'Revisá endpoint, TLS y permisos de las credenciales sobre el bucket de Gianna.',
                            retryable=not denied)
            event(LOG, 'minio.operation_failed', level=logging.ERROR, operation=operation, code=code,
                  duration_ms=round((time.perf_counter()-started)*1000, 2), exception=safe_exception(exc))
            raise failure from exc

    @staticmethod
    def key(name):
        p = PurePosixPath(name)
        if (not name or '\\' in name or '\x00' in name or p.is_absolute() or
                '..' in p.parts or str(p) != name):
            raise error('object_key_invalid', 'La referencia del archivo no es válida.', 'Revisá el trabajo y conservá el objeto original.')
        return PREFIX+name

    def read(self, name, *, limit=MAX_JSON_BYTES):
        key = self.key(name)
        def receive():
            response = None
            try:
                response = self.client.get_object(self.cfg.minio_bucket_name, key)
                data = response.read(limit+1)
                if len(data) > limit:
                    raise error('object_too_large', 'El objeto supera el tamaño admitido.', 'Revisá el objeto y su procedencia.')
                expected = response.headers.get('x-amz-meta-sha256')
                if expected and hashlib.sha256(data).hexdigest() != expected:
                    raise error('object_checksum_invalid', 'La integridad del objeto no coincide.', 'Conservá el objeto y recuperá una copia íntegra.')
                return data
            except Exception as exc:
                if getattr(exc, 'code', '') in {'NoSuchKey', 'NoSuchObject', 'NoSuchBucket'}:
                    return None
                raise
            finally:
                if response is not None:
                    response.close()
                    response.release_conn()
        return self._call('read', receive)

    def read_json(self, name, *, limit=MAX_JSON_BYTES):
        data = self.read(name, limit=limit)
        if data is None:
            return None
        try:
            return json.loads(data)
        except (ValueError, UnicodeError):
            raise error('object_json_invalid', 'El objeto JSON no es válido.', 'Conservá el objeto y revisá su respaldo.') from None

    def put(self, name, data, content_type='application/octet-stream', *, immutable=True):
        key = self.key(name)
        if immutable:
            previous = self.read(name, limit=max(len(data), 8192))
            if previous is not None:
                if previous != data:
                    raise error('object_conflict', 'Ya existe otro contenido para esta referencia.',
                                'Conservá ambos orígenes; no se sobrescribió el objeto existente.')
                return hashlib.sha256(data).hexdigest()
        sha = hashlib.sha256(data).hexdigest()
        self._call('write', lambda: self.client.put_object(self.cfg.minio_bucket_name, key, io.BytesIO(data), len(data),
                                                         content_type=content_type, metadata={'sha256': sha}))
        event(LOG, 'minio.object_persisted', bytes=len(data), sha256=sha)
        return sha

    def put_json(self, name, data):
        return self.put(name, json.dumps(data, ensure_ascii=False, sort_keys=True, allow_nan=False).encode(), 'application/json')

    def persist_file(self, name, path, expected_sha):
        """Stream verified model files; never read a whole ONNX model into RAM."""
        path = Path(path)
        key = self.key(name)
        def inspect():
            try:
                return self.client.stat_object(self.cfg.minio_bucket_name, key)
            except Exception as exc:
                if getattr(exc, 'code', '') in {'NoSuchKey', 'NoSuchObject'}:
                    return None
                raise
        previous = self._call('artifact_inspect', inspect)
        if previous:
            if previous.size != path.stat().st_size or previous.metadata.get('x-amz-meta-sha256') != expected_sha:
                raise error('object_conflict', 'Un artefacto remoto no coincide con el modelo verificado.', 'Conservá el objeto y revisá el respaldo del modelo.')
            return
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != expected_sha:
                raise error('object_checksum_invalid', 'El archivo local cambió antes de persistirlo.', 'Repetí la preparación del modelo fijado.')
        self._call('artifact_persist', lambda: self.client.fput_object(self.cfg.minio_bucket_name, key, str(path),
                                                                      metadata={'sha256':expected_sha}))
        event(LOG, 'minio.artifact_persisted', bytes=path.stat().st_size, sha256=expected_sha)

    def restore_file(self, name, path, expected_sha, expected_bytes, progress=None):
        path = Path(path)
        key = self.key(name)
        temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.partial')
        def restore():
            response = None
            try:
                response = self.client.get_object(self.cfg.minio_bucket_name, key)
                path.parent.mkdir(parents=True, exist_ok=True)
                sha = hashlib.sha256(); size = 0
                with temporary.open('xb') as stream:
                    for data in response.stream(1024*1024):
                        size += len(data)
                        if size > expected_bytes:
                            raise error('object_checksum_invalid', 'El modelo remoto tiene un tamaño inesperado.', 'Revisá el respaldo de artefactos.')
                        sha.update(data); stream.write(data)
                        if progress:progress('Recuperando modelo desde MinIO: '+path.name)
                if size != expected_bytes or sha.hexdigest() != expected_sha:
                    raise error('object_checksum_invalid', 'El modelo remoto no coincide con su manifiesto.', 'Revisá el respaldo de artefactos.')
                temporary.replace(path)
                event(LOG, 'minio.artifact_restored', bytes=size, sha256=expected_sha)
                return True
            except Exception as exc:
                if getattr(exc, 'code', '') in {'NoSuchKey', 'NoSuchObject'}:
                    return False
                raise
            finally:
                temporary.unlink(missing_ok=True)
                if response is not None:
                    response.close(); response.release_conn()
        return self._call('artifact_restore', restore)

    def restore_upload(self, name, destination, expected):
        data = self.read('uploads/'+name, limit=self.cfg.max_upload_mb*1024*1024)
        if data is None:
            raise error('upload_missing', 'El archivo de importación no está en MinIO.', 'Revisá el objeto y los respaldos de la importación.')
        if not re.fullmatch(r'[a-f0-9]{64}', expected or '') or hashlib.sha256(data).hexdigest() != expected:
            raise error('object_checksum_invalid', 'El archivo no coincide con la importación recibida.', 'Conservá el objeto y revisá el trabajo original.')
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name+'.'+uuid.uuid4().hex+'.partial')
        try:
            with temporary.open('xb') as stream:
                stream.write(data)
            temporary.chmod(0o600)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)

    def inspect(self, db):
        """Read only, including namespace identity; never bless an unrelated bucket."""
        binding = db.setting(SETTING) if db is not None else None
        if self._health and self._health[1] == binding and time.monotonic()-self._health[0] < 5:
            return copy.deepcopy(self._health[2])
        exists = self._call('bucket_inspect', lambda: self.client.bucket_exists(self.cfg.minio_bucket_name))
        scope = hashlib.sha256((self.cfg.minio_endpoint+'\0'+self.cfg.minio_bucket_name+'\0'+str(self.cfg.minio_secure)).encode()).hexdigest()
        if binding is not None:
            try:
                uuid.UUID(binding['id'])
                if (binding['state'] not in {'initializing', 'bound'} or
                        (binding['state'] == 'initializing' and binding['scope'] != scope)):
                    raise ValueError()
            except (ValueError, TypeError, KeyError, IndexError, AttributeError):
                raise error('minio_identity_mismatch', 'El bucket configurado no coincide con esta instalación.',
                            'Revisá endpoint, bucket y respaldo SQL. No se adoptó otro almacenamiento.') from None
        actual = None
        if exists:
            def private():
                try:
                    policy = self.client.get_bucket_policy(self.cfg.minio_bucket_name)
                except Exception as exc:
                    if getattr(exc, 'code', '') == 'NoSuchBucketPolicy':
                        return
                    raise
                if policy:
                    raise error('minio_bucket_not_private', 'El bucket de Gianna debe ser privado.',
                                'Usá un bucket dedicado sin política pública. No se modificó la política existente.')
            self._call('bucket_policy', private)
            actual = self.read_json(MARKER, limit=8192)
            if actual is not None:
                try:
                    uuid.UUID(actual['id'])
                    if actual.get('format') != 1:
                        raise ValueError()
                except (ValueError, TypeError, KeyError, IndexError, AttributeError):
                    raise error('minio_identity_invalid', 'La identidad de MinIO no es válida.', 'Revisá el marcador y su respaldo.') from None
        if actual and (not binding or actual['id'] != binding['id']):
            raise error('minio_identity_mismatch', 'El bucket pertenece a otra instalación.', 'Reconectá el bucket y la base SQL correspondientes.')
        if binding and binding['scope'] != scope and actual is None:
            raise error('minio_identity_mismatch', 'El destino configurado no contiene el almacenamiento registrado.',
                        'Revisá endpoint y bucket; no se creó otro almacenamiento vacío.')
        if binding and binding['state'] == 'bound' and actual is None:
            raise error('minio_storage_missing', 'Falta la identidad del almacenamiento registrado en MinIO.',
                        'Revisá el bucket y recuperá su contenido original. No se creó un reemplazo vacío.')
        if exists and not binding and actual is None:
            occupied = self._call('namespace_inspect', lambda: next(iter(self.client.list_objects(self.cfg.minio_bucket_name, prefix=PREFIX, recursive=True)), None))
            if occupied is not None:
                raise error('minio_namespace_unbound', 'Hay objetos anteriores sin una identidad SQL verificable.',
                            'Contrastá el bucket con sus respaldos antes de adoptar el almacenamiento.')
        result = dict(backend='minio', bucket=self.cfg.minio_bucket_name, bucket_exists=exists, scope=scope,
                    identity=dict(state='matched' if actual else 'initializing' if binding else 'uninitialized',
                                  expected=binding['id'] if binding else None, actual=actual['id'] if actual else None,
                                  matched=bool(actual and binding), initialized=bool(binding and binding['state']=='bound')))
        if binding and binding['state'] == 'bound' and actual:
            self._health = (time.monotonic(), copy.deepcopy(binding), copy.deepcopy(result))
        return result

    def initialize(self, db):
        report = self.inspect(db)
        binding = db.setting(SETTING)
        if not binding:
            binding = {'id':str(uuid.uuid4()), 'scope':report['scope'], 'state':'initializing'}
            db.execute('INSERT INTO settings(`key`,value) VALUES(?,?)', (SETTING, json.dumps(binding)))
        if not report['bucket_exists']:
            def create():
                try:
                    self.client.make_bucket(self.cfg.minio_bucket_name)
                except Exception as exc:
                    if getattr(exc, 'code', '') != 'BucketAlreadyOwnedByYou':
                        raise
            self._call('bucket_initialize', create)
            # Recheck privacy and scope after creation/race, before writing.
            self.inspect(db)
        self.put_json(MARKER, {'id':binding['id'], 'format':1})
        binding['state'] = 'bound'
        binding['scope'] = report['scope']
        db.execute('UPDATE settings SET value=? WHERE `key`=?', (json.dumps(binding), SETTING))
        self._health = None
        return {'matched':True, 'initialized':True}
