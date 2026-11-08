"""Inspect an installation before processing durable jobs; never change editorial data.

MariaDB owns publication and snapshots. A physical collection or an old model is
evidence to preserve, never authority to publish, recreate SQL or adopt a volume.
"""
import importlib.metadata
import json
import logging
from itertools import islice
import threading
import time
import uuid

from ..errors import DomainError
from ..observability import boot_id, event, safe_exception
from .neural import MODEL_PROFILES, artifact_specs
from .recovery import snapshot
from .storage import inspect_storage, storage_identity, writer_lock
from .operations import record_event

LOG = logging.getLogger(__name__)
_COUNTS = ('users', 'bases', 'records', 'sources', 'versions', 'version_records', 'version_sources', 'chunks')


def _check(name, status, code, message, action='', **details):
    return dict(name=name, status=status, code=code, message=message, action=action,
                details=details)


class Installation:
    """Bounded, cached preflight. Inspection is read-only; reconcile stores a report.

    No network downloads, generation, content migration, index writes or pointer
    changes occur here. Safe physical repairs are delegated to the recovery job.
    """
    def __init__(self, db, cfg, knowledge, store, recovery):
        self.db, self.cfg, self.knowledge = db, cfg, knowledge
        self.store, self.recovery = store, recovery
        self._lock = threading.RLock()
        self._report = None
        self._at = 0.0
        self._pointer = object()
        self._persisted = None
        self._signature = None

    def inspect(self):
        started = time.perf_counter()
        report = dict(report_id=uuid.uuid4().hex, boot_id=boot_id(), checked_at=time.time(),
                      state='checking', code=None, message='Inspeccionando la instalación.',
                      checks=[], plan=[], database={}, storage={}, lance={}, models={})
        checks = report['checks']
        try:
            database = self._database()
            report['database'] = database
            checks.append(_check('database', 'ok', None,
                                 'Esquema y datos administrativos inspeccionados.',
                                 engine=database['engine'], schema_version=database['schema_version'],
                                 counts=database['counts']))
            if not database['layout']['ok']:
                checks.append(_check('database_layout','blocked',database['layout']['code'],
                                     'El esquema físico no coincide con el historial de migraciones.',
                                     database['layout']['action'],layout=database['layout']))
        except Exception as exc:
            event(LOG, 'installation.database_failed', level=logging.ERROR,
                  report_id=report['report_id'], exception=safe_exception(exc))
            checks.append(_check('database', 'blocked', 'database_unavailable',
                                 'No se pudo inspeccionar el esquema de la base administrativa.',
                                 'Revisá conectividad, permisos y migraciones de MariaDB; conservá su respaldo.'))
            # SQL failure must not hide the physical volume that is still there.
            report['storage']=inspect_storage(None,self.cfg)
            try:
                report['lance']=self._physical_inventory({'versions':[],'inventory_truncated':True})
                report['lance']['references_unknown']=True
            except OSError:
                report['lance']={'exists':self.cfg.lance_dir.exists(),'references_unknown':True,'readable':False}
            return self._finish(report, started)

        storage = inspect_storage(self.db, self.cfg)
        report['storage'] = storage
        checks.append(_check('storage', 'ok' if storage['ok'] else 'blocked', storage['code'],
                             storage['message'], storage.get('action', ''), path=storage.get('path'),
                             mount=storage.get('mount'), identity=storage.get('identity'),
                             backend=storage.get('backend'), bucket=storage.get('bucket')))
        # Inventory existing names even when an identity mismatch blocks writes.
        # Files are not opened through LanceDB until persistence passes.
        try:
            report['lance'] = self._physical_inventory(database)
        except OSError as exc:
            checks.append(_check('physical_inventory', 'blocked', 'storage_unreadable',
                                 'No se pudieron enumerar los índices existentes.',
                                 'Revisá los permisos del volumen para UID/GID 10001.'))
            event(LOG, 'installation.inventory_failed', level=logging.ERROR,
                  report_id=report['report_id'], exception=safe_exception(exc))
            return self._finish(report, started)

        pointer = database['active_version_id']
        if not database['layout']['ok']:
            checks.append(_check('publication','blocked','database_schema_incompatible',
                                 'La publicación se conserva sin interpretarla hasta verificar el esquema SQL.',
                                 database['layout']['action']))
        elif pointer:
            version = self.knowledge.active()
            if not version:
                checks.append(_check('publication', 'blocked', 'active_reference_invalid',
                                     'La publicación apunta a una versión o base que no existe.',
                                     'Restaurá los metadatos desde un respaldo compatible; no se modificó el puntero.',
                                     version_id=pointer))
            else:
                self._published(report, version, allow_physical=storage['ok'])
        else:
            physical = report['lance'].get('collections', [])
            if physical and not database['counts']['versions']:
                checks.append(_check('publication', 'blocked', 'database_state_missing',
                                     'Hay índices físicos anteriores pero MariaDB no tiene sus versiones.',
                                     'Comprobá que DATABASE_URL y el volumen pertenezcan a la misma instalación, o restaurá el respaldo SQL. Los índices se conservaron.',
                                     physical_collections=len(physical)))
            else:
                checks.append(_check('publication', 'ok', 'no_knowledge',
                                     'No hay una publicación activa; los borradores y versiones existentes se conservan.',
                                     versions=database['counts']['versions']))
                report['plan'].append(dict(action='preserve_unpublished', automatic=True,
                                           message='Permitir trabajo editorial sin publicar ni elegir una versión automáticamente.'))

        if report['lance'].get('orphans'):
            checks.append(_check('unreferenced_indexes', 'warning', 'unreferenced_indexes',
                                 'Hay colecciones sin referencia SQL; se conservan sin adoptarlas ni borrarlas.',
                                 'Contrastá el inventario con tus respaldos antes de decidir su destino.',
                                 count=len(report['lance']['orphans'])))
        if storage['ok'] and not storage.get('identity', {}).get('initialized'):
            report['plan'].append(dict(action='initialize_identity', automatic=True,
                                       message=('Vincular el bucket privado de MinIO tras verificar SQL y su identidad; conservar el almacenamiento anterior.'
                                                if self.cfg.storage_backend == 'minio' else
                                                'Vincular el volumen sólo después de validar la instalación; no adoptar otro UUID.')))
        return self._finish(report, started)

    def _database(self):
        from ..schema_review import CORE_COLUMNS
        layout=self.db.review_schema()
        missing=layout['missing_columns']
        revision = None if missing.get('schema_versions') else self.db.one('SELECT COALESCE(MAX(version),0) AS n FROM schema_versions')['n']
        counts = {name: None if set(missing.get(name,[]))==CORE_COLUMNS[name] else
                  self.db.one('SELECT COUNT(*) AS n FROM ' + name)['n'] for name in _COUNTS}
        pointer = None if missing.get('active_knowledge') else self.db.one('SELECT version_id FROM active_knowledge WHERE singleton=1')
        versions = [] if set(missing.get('versions',[])) & {'id','collection_name','status'} else self.db.all('SELECT id,collection_name,status FROM versions ORDER BY id LIMIT 1001')
        queue = [] if 'status' in missing.get('jobs',[]) else self.db.all('SELECT status,COUNT(*) AS n FROM jobs GROUP BY status')
        return dict(engine='MariaDB' if self.db.is_mariadb else 'SQLite (pruebas)',
                    schema_version=revision, counts=counts,
                    layout=layout,
                    active_version_id=pointer['version_id'] if pointer else None,
                    versions=versions[:1000], inventory_truncated=len(versions) > 1000,
                    queue={row['status']: row['n'] for row in queue})

    def _physical_inventory(self, database):
        root = self.cfg.lance_dir
        collections = []
        if root.exists():
            if root.is_symlink() or not root.is_dir():
                raise OSError('invalid LanceDB directory')
            collections = sorted(islice((path.name[:-6] for path in root.iterdir()
                                         if path.name.endswith('.lance') and path.is_dir()), 1001))
        referenced = {v['collection_name'] for v in database['versions']}
        names = collections[:1000]
        return dict(path=str(root), exists=root.exists(), collections=names,
                    orphans=[] if database['inventory_truncated'] else [name for name in names if name not in referenced],
                    referenced_missing=sorted(referenced - set(names)),
                    inventory_truncated=len(collections) > 1000,
                    retained_staging=sum(name.startswith('gianna_restore_') for name in names),
                    retained_quarantine=sum(name.startswith('gianna_quarantine_') for name in names))

    def _published(self, report, version, *, allow_physical=True):
        checks = report['checks']
        try:
            profile = json.loads(version['profile_json'])
            if not isinstance(profile, dict) or profile.get('engine') not in MODEL_PROFILES:
                raise DomainError('Perfil publicado desconocido.', 503, 'published_profile_unknown')
            runtime = profile.get('onnxruntime')
            installed = importlib.metadata.version('onnxruntime') if runtime else None
            if runtime and installed != runtime:
                mismatch = DomainError('El runtime instalado no coincide con el de la publicación.',
                                       503, 'runtime_profile_mismatch')
                mismatch.details = {'expected_runtime': runtime, 'installed_runtime': installed}
                raise mismatch
            data = snapshot(self.db, self.cfg, version)
            checks.append(_check('snapshot', 'ok', None,
                                 'Fotografía SQL y fuentes de vectores verificadas.',
                                 version_id=version['id'], vectors=len(data['rows']),
                                 fingerprint=data['fingerprint'], backup_used=data['backup_used'],
                                 source_counts=data.get('source_counts', {}),
                                 invalid_sources=data.get('invalid_sources', {})))
            report['models'] = self._models(profile['engine'])
            if any(item['missing_files'] or not item['manifest_present'] for item in report['models']['artifacts']):
                report['plan'].append(dict(action='restore_models', automatic=True,
                                           message='Recuperar únicamente los artefactos fijados del perfil publicado y comprobar sus hashes.'))
            if not allow_physical:
                checks.append(_check('index', 'blocked', 'physical_inspection_blocked',
                                     'Los archivos se inventariaron sin abrir LanceDB porque el volumen no superó el diagnóstico.',
                                     'Corregí el bloqueo de almacenamiento para comprobar el índice físico.'))
                return
            index = self.store.inspect(version['collection_name'], version['chunk_count'])
            # Even a matching count/schema cannot prove content integrity.
            matches = index['ready'] and self.store.matches(version['collection_name'], data['rows'])
            report['lance']['active_index'] = dict(index, content_matches=bool(matches))
            if not matches:
                report['plan'].append(dict(action='restore_index', automatic=True,
                                           message='Restaurar la misma colección desde vectores verificados, conservando la colección anterior.'))
            report['plan'].append(dict(action='verify_runtime', automatic=True,
                                       message='Verificar artefactos, perfil e inferencia local antes de habilitar consultas.'))
            checks.append(_check('index', 'ok' if matches else 'recoverable',
                                 None if matches else index.get('code') or 'index_integrity_failed',
                                 'Índice físico coherente.' if matches else 'El índice requiere restauración verificable.',
                                 version_id=version['id']))
        except DomainError as exc:
            checks.append(_check('published_knowledge', 'blocked', exc.code, exc.message,
                                 'Conservá SQL, volumen y claves; revisá la fotografía y su perfil antes de reintentar.',
                                 version_id=version['id'], validation=getattr(exc, 'details', {})))
            event(LOG, 'installation.publication_blocked', level=logging.ERROR,
                  report_id=report['report_id'], version_id=version['id'], code=exc.code,
                  exception=safe_exception(exc))
        except (ValueError, TypeError, importlib.metadata.PackageNotFoundError) as exc:
            checks.append(_check('published_knowledge', 'blocked', 'published_profile_invalid',
                                 'El perfil publicado o una dependencia de inferencia no pudo verificarse.',
                                 'Restaurá un runtime compatible con la publicación; no se cambiarán sus vectores.'))
            event(LOG, 'installation.profile_invalid', level=logging.ERROR,
                  report_id=report['report_id'], exception=safe_exception(exc))
        except OSError as exc:
            checks.append(_check('published_knowledge', 'blocked', 'storage_permission_denied',
                                 'No se pudieron inspeccionar los archivos del conocimiento publicado.',
                                 'Revisá acceso al volumen y sus subdirectorios con el UID/GID del proceso.'))
            event(LOG, 'installation.files_unreadable', level=logging.ERROR,
                  report_id=report['report_id'], exception=safe_exception(exc))

    def _models(self, engine):
        models = []
        for kind, _model, revision, files in artifact_specs(engine):
            folder = self.cfg.model_dir / kind / revision
            absent = [name for name in files if not (folder / name).is_file()]
            models.append(dict(kind=kind, revision=revision, missing_files=absent,
                               manifest_present=(folder / 'manifest.json').is_file(),
                               checksum_verification='pending_worker'))
        return dict(engine=engine, artifacts=models,
                    action='restore_missing_and_verify_checksums')

    def _finish(self, report, started):
        blocked = next((c for c in report['checks'] if c['status'] == 'blocked'), None)
        if blocked:
            report.update(state='blocked', code=blocked['code'], message=blocked['message'], action=blocked['action'])
        elif report['database'].get('active_version_id'):
            available = self.recovery.status().get('available', False)
            report.update(state='ready' if available else 'recoverable', code=None,
                          message='Conocimiento listo.' if available else 'Instalación inspeccionada; se verificará y recuperará la publicación existente.')
        else:
            report.update(state='empty', code='no_knowledge',
                          message='Instalación inspeccionada; no hay una publicación activa.')
        report['duration_ms'] = round((time.perf_counter() - started) * 1000, 2)
        return report

    def reconcile(self, force=False):
        with self._lock:
            now = time.monotonic()
            try:
                pointer = self.db.one('SELECT version_id FROM active_knowledge WHERE singleton=1')
                pointer = pointer['version_id'] if pointer else None
            except Exception:
                pointer = 'database_unavailable'
            if not force and self._report and now - self._at < 15 and pointer == self._pointer:
                return self._report
            report = self.inspect()
            was_registered=report.get('storage',{}).get('identity',{}).get('initialized',False)
            if report['state'] != 'blocked':
                try:
                    # Configuration and HTTP startup never create data paths.
                    # Only a successful inventory may initialize missing folders.
                    self.cfg.data_dir.mkdir(parents=True, exist_ok=True)
                    for sub in ('uploads', 'exports', 'models'):
                        (self.cfg.data_dir / sub).mkdir(exist_ok=True)
                    with self.db.physical_lock(), writer_lock(self.cfg):
                        storage_identity(self.db, self.cfg, write=True)
                    report['storage'] = inspect_storage(self.db, self.cfg)
                    if not was_registered:
                        record_event(self.db, 'installation.identity_initialized',
                                     stage='storage', report_id=report['report_id'])
                except DomainError as exc:
                    report.update(state='blocked', code=exc.code, message=exc.message,
                                  action=getattr(exc, 'details', {}).get('action', 'Revisá el diagnóstico de almacenamiento antes de procesar trabajos.'))
                except OSError as exc:
                    report.update(state='blocked', code='storage_permission_denied',
                                  message='No se pudieron inicializar los directorios del volumen.',
                                  action='Revisá permisos y espacio del volumen para el usuario del contenedor.')
                    event(LOG, 'installation.initialize_failed', level=logging.ERROR,
                          report_id=report['report_id'], exception=safe_exception(exc))
            self._report, self._at, self._pointer = report, now, pointer
            signature = json.dumps({key: report.get(key) for key in
                                    ('state', 'code', 'database', 'storage', 'lance', 'models', 'plan')}, sort_keys=True)
            if signature == self._signature:
                return report
            self._signature = signature
            record_event(self.db, 'installation.reconciled',
                         level='warning' if report['state'] == 'blocked' else 'info',
                         code=report['code'], stage='preflight', report_id=report['report_id'],
                         state=report['state'], duration_ms=report['duration_ms'],
                         counts=report['database'].get('counts', {}))
            # Reporting metadata is separate from immutable editorial snapshots.
            try:
                from ..db import dumps
                self.db.execute('INSERT INTO settings(`key`,value) VALUES(?,?) ON CONFLICT(`key`) DO UPDATE SET value=excluded.value',
                                ('runtime_installation_report', dumps(report)))
                self._persisted = report['report_id']
            except Exception as exc:
                event(LOG, 'installation.report_not_persisted', level=logging.WARNING,
                      report_id=report['report_id'], exception=safe_exception(exc))
            return report

    def status(self):
        with self._lock:
            if self._report:
                return self._report
        return dict(state='checking', code='installation_initializing', boot_id=boot_id(),
                    checked_at=None, report_id=None, message='El worker todavía no completó el inventario.',
                    checks=[], plan=[])

    def public_status(self):
        report = self.status()
        return {key: report.get(key) for key in ('state', 'code', 'report_id', 'checked_at')}
