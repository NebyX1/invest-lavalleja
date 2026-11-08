"""Durable work lifecycle: inspect installation, claim with fencing, report each attempt."""
import errno
from contextlib import contextmanager
import json
import logging
import threading
import time
from pathlib import Path

from ..db import IntegrityError, uid, dumps
from ..errors import DomainError, Cancelled
from ..corpus import load_corpus
from ..chunking import CONTEXTUALIZER_VERSION, chunks_for_record
from ..observability import bind_context, boot_id, event, safe_exception, sanitize_fields
from .settings import get_settings
from .operations import record_event

LOG = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
LEASE_SECONDS = 120
TRANSIENT_CODES = {
    'minio_unavailable',
    'database_unavailable', 'database_busy', 'recovery_busy', 'models_recovery_failed',
    'model_download_timeout', 'model_download_unavailable', 'index_unavailable',
    'network_unavailable', 'download_interrupted', 'recovery_interrupted',
}
ENVIRONMENT_CODES = TRANSIENT_CODES | {
    'minio_configuration_missing', 'minio_configuration_invalid', 'minio_access_denied',
    'minio_bucket_not_private', 'minio_identity_invalid', 'minio_identity_mismatch',
    'minio_storage_missing', 'minio_namespace_unbound', 'cache_not_writable', 'cache_full',
    'storage_not_mounted', 'storage_not_writable', 'storage_read_only',
    'storage_space_low', 'schema_not_ready', 'schema_migration_failed',
    'storage_permission_denied', 'storage_full', 'storage_mount_unknown',
    'storage_path_invalid', 'storage_mismatch', 'storage_identity_invalid',
    'database_schema_incompatible',
}
ACTION_BY_CODE = {
    'storage_not_mounted': 'Revisá el montaje persistente de la carpeta de datos en el recurso de despliegue.',
    'storage_mismatch': 'Reconectá el almacenamiento registrado; la adopción de otro volumen requiere revisión explícita.',
    'storage_not_writable': 'Revisá los permisos de escritura del volumen para el usuario del contenedor.',
    'storage_read_only': 'Revisá el modo de lectura/escritura del volumen de datos.',
    'storage_space_low': 'Liberá o ampliá espacio en el volumen conservando los datos y sus respaldos.',
    'storage_permission_denied': 'Revisá los permisos del volumen para el usuario del contenedor.',
    'storage_full': 'Ampliá o liberá espacio preservando los datos y los respaldos existentes.',
    'storage_mount_unknown': 'Revisá el diagnóstico de montajes dentro del contenedor de la API.',
    'storage_path_invalid': 'Revisá que la ruta de datos apunte a un directorio.',
    'storage_identity_invalid': 'Revisá la identidad del almacenamiento y sus respaldos.',
    'snapshot_invalid': 'Revisá la fotografía y los vectores conservados en MariaDB y los respaldos. La publicación se mantiene.',
    'embedding_mismatch': 'Restaurá el perfil compatible de esta versión; no mezcles vectores de perfiles diferentes.',
    'invalid_job_payload': 'Revisá el registro del trabajo. El contenido guardado no permite ejecutarlo de forma segura.',
    'database_unavailable': 'Revisá la conectividad y disponibilidad de MariaDB.',
    'database_schema_incompatible': 'Revisá el diagnóstico de esquema y las migraciones de MariaDB; el redeploy aplica únicamente reparaciones idempotentes verificadas.',
    'database_constraint_violation': 'Revisá las restricciones de MariaDB y los datos del trabajo antes de reintentar.',
    'recovery_busy': 'Esperá a que termine la otra operación sobre el mismo almacenamiento.',
    'models_recovery_failed': 'Revisá conectividad, espacio y permisos para descargar los artefactos fijados.',
    'job_interrupted': 'Revisá el estado del worker y los reinicios antes de reintentar este trabajo.',
    'job_target_unverified': 'El trabajo anterior no identifica una versión verificable; solicitá una verificación explícita de la publicación actual.',
}


def failure_policy(exc):
    """Only known temporary dependencies merit an automatic retry."""
    details = getattr(exc, 'details', {})
    details = details if isinstance(details, dict) else {}
    if isinstance(exc, DomainError):
        code = exc.code
        message = exc.message
    elif isinstance(exc, IntegrityError):
        cause = exc
        number = None
        seen = set()
        while cause is not None and id(cause) not in seen:
            seen.add(id(cause))
            value = getattr(cause, 'errno', None)
            if isinstance(value, int) and not isinstance(value, bool):
                number = value
                break
            cause = cause.__cause__ or cause.__context__
        if number in {1364, 1054, 1146}:
            code = 'database_schema_incompatible'
            message = 'IntegrityError: el esquema efectivo de MariaDB no coincide con el requerido por el backend.'
        else:
            code = 'database_constraint_violation'
            message = 'IntegrityError: los datos no cumplen una restricción de MariaDB.'
    elif isinstance(exc, (TimeoutError, ConnectionError)) or type(exc).__name__ in {
        'OperationalError', 'InterfaceError', 'PoolTimeout', 'TimeoutException',
    }:
        code = 'database_unavailable' if type(exc).__name__ in {'OperationalError', 'InterfaceError', 'PoolTimeout'} else 'network_unavailable'
        message = 'Una dependencia temporal no está disponible.'
    elif isinstance(exc, OSError) and exc.errno in {errno.ENOSPC, errno.EACCES, errno.EPERM, errno.EROFS}:
        code = 'storage_space_low' if exc.errno == errno.ENOSPC else 'storage_read_only' if exc.errno == errno.EROFS else 'storage_not_writable'
        message = 'El almacenamiento no permite completar la operación.'
    else:
        code = 'job_failed'
        message = 'El trabajo falló. Revisá el diagnóstico y su identificador en el registro técnico.'
    retryable = details.get('retryable', code in TRANSIENT_CODES)
    if code.startswith(('storage_', 'schema_', 'snapshot_', 'embedding_', 'database_schema_', 'database_constraint_')):
        retryable = False
    action = details.get('action') or ACTION_BY_CODE.get(code, 'Revisá el diagnóstico de la instalación y el registro de este trabajo antes de reintentar.')
    safe = sanitize_fields({'reason': message, 'action': action})
    stage = next((stage for prefix, stage in (
        ('storage_', 'storage'), ('schema_', 'schema'), ('snapshot_', 'snapshot'),
        ('embedding_', 'profile'), ('model', 'models'), ('database_schema_', 'schema'), ('database_', 'database'),
        ('index_', 'index')) if code.startswith(prefix)), None)
    return {'code': code, 'message': str(safe.get('reason', 'El trabajo no se completó.'))[:1200],
            'retryable': bool(retryable), 'action': str(safe.get('action', 'Revisá el diagnóstico.'))[:1200],
            'stage': stage}


class Jobs:
    def __init__(self, db, cfg, knowledge, embeddings, vector_store, rag=None):
        self.db, self.cfg, self.knowledge = db, cfg, knowledge
        self.embeddings, self.vector_store, self.rag = embeddings, vector_store, rag
        self.stop_event = threading.Event()
        self.thread = None
        self.wake = threading.Event()
        self.token = uid()
        self.boot_id = boot_id()
        self.current_job = None
        self.installation = None
        self._heartbeat_thread = None
        self._phase = 'created'
        self._last_poll_at = None
        self._heartbeat_at = None
        self._last_error = None
        self._lost_owner = None
        self._boot_reconciled = False
        self._last_resume_report = None
        self._announced_block = None
        if rag:
            rag.recovery.enqueue = self.ensure_warmup

    def _record(self, job_id, name, *, attempt=0, stage=None, code=None, message='', connection=None, **details):
        """History contains operational metadata, never payloads, credentials or SQL."""
        details = sanitize_fields(details)
        message = str(sanitize_fields({'reason': message}).get('reason', ''))
        journal_name = {
            'job_started': 'queue.claimed', 'job_queued': 'queue.enqueued',
            'job_completed': 'queue.completed', 'job_attempt_failed': 'queue.failed',
            'job_lease_recovered': 'queue.reclaimed', 'job_cancelled': 'queue.cancelled',
            'job_retry_requested': 'queue.retry_requested', 'job_cancel_requested': 'queue.cancel_requested',
            'job_resumed_after_preflight': 'queue.recovered', 'job_paused': 'queue.paused',
            'job_ownership_lost': 'queue.ownership_lost',
            'job_stage_changed': 'job.stage_changed',
            'job_automatic_recovery_blocked': 'queue.recovery_blocked',
        }.get(name, 'queue.event')
        record_event(connection or self.db, journal_name, job_id=job_id, attempt=attempt,
                     stage=stage, code=code, level='error' if name == 'job_attempt_failed' else 'info', **details)
        if details.get('retry_seconds'):
            record_event(connection or self.db, 'queue.retry_scheduled', job_id=job_id,
                         attempt=attempt, stage='waiting_retry', code=code,
                         retry_seconds=details['retry_seconds'], level='warning')
        args = (job_id, time.time(), name, attempt, self.boot_id, stage, code, message[:1200], dumps(details))
        sql = 'INSERT INTO job_events(job_id,at,event,attempt,boot_id,stage,code,message,details_json) VALUES(?,?,?,?,?,?,?,?,?)'
        if connection is not None:
            connection.execute(sql, args)
        else:
            try:
                self.db.execute(sql, args)
            except Exception as exc:
                event(LOG, 'job_history_unavailable', level=logging.WARNING,
                      job_id=job_id, failure=safe_exception(exc))

    def enqueue(self, kind, payload=None, base_id=None, version_id=None):
        if kind not in {'import', 'warmup', 'evaluation'}:
            raise DomainError('Tipo de trabajo no válido.')
        if payload is not None and not isinstance(payload, dict):
            raise DomainError('El contenido del trabajo debe ser un objeto.', 400, 'invalid_job_payload')
        identifier = uid()
        self.db.execute('INSERT INTO jobs(id,kind,base_id,version_id,payload_json,created_at) VALUES(?,?,?,?,?,?)',
                        (identifier, kind, base_id, version_id, dumps(payload or {}), time.time()))
        self._record(identifier, 'job_queued', stage='queued')
        self.wake.set()
        return identifier

    def start(self):
        """HTTP can start even while SQL/preflight is temporarily unavailable."""
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self._phase = 'preflight'
        self.thread = threading.Thread(target=self.run, name='gianna-jobs', daemon=True)
        self.thread.start()
        if not self._heartbeat_thread or not self._heartbeat_thread.is_alive():
            self._heartbeat_thread = threading.Thread(target=self.heartbeat, name='gianna-job-lease', daemon=True)
            self._heartbeat_thread.start()

    def ensure_warmup(self, retry=False, version=None):
        active = version or self.knowledge.active()
        if not active:
            return None
        with self.db.tx(immediate=True) as db:
            row = db.execute("SELECT * FROM jobs WHERE kind='warmup' AND (version_id=? OR payload_json=?) ORDER BY created_at DESC LIMIT 1",
                             (active['id'], dumps({'version_id': active['id']}))).fetchone()
            if row:
                # The version column is authoritative; malformed old payloads
                # are handled in execution, never allowed to prevent startup.
                if row['status'] in {'queued', 'running'}:
                    return row['id']
                if row['status'] in {'failed', 'cancelled'} and not retry:
                    return row['id']
            identifier = uid()
            db.execute('INSERT INTO jobs(id,kind,version_id,payload_json,created_at) VALUES(?,?,?,?,?)',
                       (identifier, 'warmup', active['id'], dumps({'version_id': active['id']}), time.time()))
        self._record(identifier, 'job_queued', stage='queued', version_id=active['id'])
        self.wake.set()
        return identifier

    def heartbeat(self):
        while not self.stop_event.wait(5):
            self._heartbeat_at = time.time()
            try:
                if self.current_job:
                    job_id = self.current_job
                    changed = self.db.execute(
                        "UPDATE jobs SET lease_until=?,heartbeat_at=? WHERE id=? AND status='running' AND owner_token=? AND lease_until>=?",
                        (time.time()+LEASE_SECONDS, time.time(), job_id, self.token, time.time()))
                    if not changed:
                        self._lost_owner = job_id
            except Exception as exc:
                event(LOG, 'job_heartbeat_failed', level=logging.WARNING,
                      job_id=self.current_job, failure=safe_exception(exc))

    def _resume_environment_jobs(self, report=None):
        """One recovery opportunity per process boot after a healthy preflight."""
        if self.installation is not None:
            return self._resume_verified_publication(report)
        if self._boot_reconciled:
            return
        with self.db.tx(immediate=True) as db:
            rows = db.execute("SELECT * FROM jobs WHERE kind='warmup' AND status='failed' AND cancel_requested=0 ORDER BY created_at DESC LIMIT 100").fetchall()
            for row in rows:
                code = row['error_code']
                if not code and (row['error'] or '').startswith('Falta un montaje persistente'):
                    code = 'storage_not_mounted'
                if code not in ENVIRONMENT_CODES or row['recovery_boot_id'] == self.boot_id:
                    continue
                if not row['version_id'] or not db.execute('SELECT id FROM versions WHERE id=?', (row['version_id'],)).fetchone():
                    continue
                latest = db.execute("SELECT id FROM jobs WHERE kind='warmup' AND version_id=? ORDER BY created_at DESC LIMIT 1", (row['version_id'],)).fetchone()
                if latest and latest['id'] != row['id']:
                    continue
                if db.execute("SELECT id FROM jobs WHERE kind='warmup' AND version_id=? AND status IN ('queued','running')", (row['version_id'],)).fetchone():
                    continue
                db.execute("UPDATE jobs SET status='queued',stage='queued',attempts=0,available_at=0,owner_token=NULL,lease_until=NULL,finished_at=NULL,error=NULL,error_code=NULL,error_stage=NULL,action=NULL,retryable=0,recovery_boot_id=?,message='La instalación se verificó; recuperación automática tras el arranque' WHERE id=? AND status='failed' AND cancel_requested=0",
                           (self.boot_id, row['id']))
                self._record(row['id'], 'job_resumed_after_preflight', connection=db,
                             stage='queued', code=code, version_id=row['version_id'])
        self._boot_reconciled = True

    def _resume_verified_publication(self, report):
        """The current verified publication, not an old error string, drives recovery.

        This only reschedules existing technical work. It neither repairs a
        payload nor changes publication, snapshots, profiles or vectors.
        """
        if not isinstance(report, dict) or report.get('state') != 'recoverable':
            return
        database = report.get('database', {})
        target = database.get('active_version_id') if isinstance(database, dict) else None
        checks = report.get('checks', [])
        plan = report.get('plan', [])
        if not isinstance(target, str) or not target or not isinstance(checks, list) or not isinstance(plan, list):
            return
        if not report.get('storage', {}).get('ok') or any(
            not isinstance(item, dict) or item.get('status') == 'blocked' for item in checks
        ):
            return
        verified = any(item.get('name') == 'snapshot' and item.get('status') == 'ok'
                       and isinstance(item.get('details'), dict)
                       and item['details'].get('version_id') == target for item in checks)
        automatic = any(isinstance(item, dict) and item.get('action') == 'verify_runtime'
                        and item.get('automatic') is True for item in plan)
        if not verified or not automatic:
            return
        signature = (target, report.get('report_id'))
        if signature == self._last_resume_report:
            return
        with self.db.tx(immediate=True) as db:
            pointer = db.execute('SELECT version_id FROM active_knowledge WHERE singleton=1').fetchone()
            if not pointer or pointer['version_id'] != target:
                return  # The cached inventory belongs to a previous publication.
            candidates = db.execute("SELECT * FROM jobs WHERE kind='warmup' AND (version_id=? OR version_id IS NULL) ORDER BY created_at DESC LIMIT 1000", (target,)).fetchall()
            for row in candidates:
                try:
                    payload = self._payload(dict(row))
                except DomainError:
                    if row['status'] == 'failed' and not row['cancel_requested']:
                        self._block_automatic_resume(db, row, 'invalid_job_payload',
                                                     'El contenido guardado del trabajo no permite verificar su destino.')
                    # A corrupt newer request with the explicit active target
                    # also prevents resurrecting an older request for it.
                    if row['version_id'] == target:
                        break
                    continue
                actual_target = row['version_id'] or payload.get('version_id')
                if actual_target != target:
                    if actual_target is None and row['status'] == 'failed' and not row['cancel_requested']:
                        self._block_automatic_resume(db, row, 'job_target_unverified',
                                                     'No se pudo comprobar la versión solicitada por el trabajo anterior.')
                    continue
                # Only the latest explicit request for this target controls its
                # lifecycle. A later cancellation or running task always wins.
                if (row['status'] != 'failed' or row['cancel_requested']
                        or row['recovery_boot_id'] == self.boot_id):
                    break
                previous = row['error_code'] or 'legacy_failure'
                db.execute("UPDATE jobs SET status='queued',stage='queued',attempts=0,available_at=0,owner_token=NULL,lease_until=NULL,finished_at=NULL,error=NULL,error_code=NULL,error_stage=NULL,action=NULL,retryable=0,recovery_boot_id=?,message='La publicación se verificó; recuperación técnica automática tras el diagnóstico' WHERE id=? AND status='failed' AND cancel_requested=0",
                           (self.boot_id, row['id']))
                self._record(row['id'], 'job_resumed_after_preflight', connection=db,
                             stage='queued', code=previous, version_id=target,
                             report_id=report.get('report_id'), publication_verified=True)
                break
        self._last_resume_report = signature

    def _block_automatic_resume(self, db, row, code, message):
        """Explain unusable old work without inventing or rewriting its payload."""
        action = ACTION_BY_CODE[code]
        if row['error_code'] == code and row['action'] == action:
            return
        db.execute("UPDATE jobs SET error=?,error_code=?,error_stage='validate_payload',action=?,retryable=0,stage='failed' WHERE id=? AND status='failed' AND cancel_requested=0",
                   (message, code, action, row['id']))
        self._record(row['id'], 'job_automatic_recovery_blocked', stage='validate_payload',
                     code=code, message=message, connection=db, action=action)

    def claim(self):
        now = time.time()
        with self.db.tx(immediate=True) as db:
            interrupted = db.execute("SELECT * FROM jobs WHERE status='running' AND (lease_until<? OR lease_until IS NULL)", (now,)).fetchall()
            for row in interrupted:
                cancelled = bool(row['cancel_requested'])
                exhausted = row['attempts'] >= MAX_ATTEMPTS
                status = 'cancelled' if cancelled else 'failed' if exhausted else 'queued'
                code = 'job_interrupted' if exhausted and not cancelled else None
                db.execute("UPDATE jobs SET status=?,stage=?,owner_token=NULL,lease_until=NULL,available_at=?,finished_at=?,error=?,error_code=?,error_stage=?,action=?,retryable=0,message=? WHERE id=? AND status='running' AND (lease_until<? OR lease_until IS NULL)",
                           (status, status, now, now if status != 'queued' else None,
                            'El proceso se interrumpió repetidamente.' if code else None,
                            code, row['stage'] if code else None, ACTION_BY_CODE.get(code),
                            'Cancelado por solicitud del administrador' if cancelled else 'Interrupciones agotadas; revisión requerida' if exhausted else 'Reanudando después de una interrupción', row['id'], now))
                self._record(row['id'], 'job_lease_recovered', attempt=row['attempts'],
                             stage=status, code=code, connection=db)
            # Older releases recorded only the cancel flag on queued jobs.
            # Honor it before backoff/exhaustion so a redeploy cannot revive it.
            db.execute("UPDATE jobs SET status='cancelled',stage='cancelled',finished_at=?,owner_token=NULL,lease_until=NULL,error=NULL,error_code=NULL,error_stage=NULL,action=NULL,retryable=0,message='Cancelación anterior confirmada antes de ejecutar' WHERE status='queued' AND cancel_requested=1 AND kind!='delete'", (now,))
            # Covers old queued rows already exhausted by earlier releases.
            db.execute("UPDATE jobs SET status='failed',stage='failed',finished_at=?,owner_token=NULL,lease_until=NULL,error='Se agotaron los intentos de ejecución.',error_code='job_interrupted',retryable=0,action=?,message='Revisión requerida antes de reintentar' WHERE status='queued' AND attempts>=?",
                       (now, ACTION_BY_CODE['job_interrupted'], MAX_ATTEMPTS))
            if db.execute("SELECT 1 FROM jobs WHERE status='running' AND lease_until>=?", (now,)).fetchone():
                return None
            row = db.execute("SELECT * FROM jobs WHERE status='queued' AND available_at<=? ORDER BY CASE WHEN kind='warmup' THEN 0 ELSE 1 END,created_at LIMIT 1", (now,)).fetchone()
            if not row:
                return None
            db.execute("UPDATE jobs SET status='running',stage='validate_payload',attempts=attempts+1,started_at=COALESCE(started_at,?),last_attempt_at=?,heartbeat_at=?,lease_until=?,owner_token=?,boot_id=?,finished_at=NULL,error=NULL,error_code=NULL,error_stage=NULL,action=NULL,retryable=0,result_json=NULL WHERE id=? AND status='queued'",
                       (now, now, now, now+LEASE_SECONDS, self.token, self.boot_id, row['id']))
            claimed = dict(db.execute('SELECT * FROM jobs WHERE id=?', (row['id'],)).fetchone())
            self._record(row['id'], 'job_started', attempt=claimed['attempts'], stage='validate_payload', connection=db)
        self._lost_owner = None
        return claimed

    def _owned(self, connection, job_id):
        row = connection.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if (not row or row['status'] != 'running' or row['owner_token'] != self.token
                or row['lease_until'] is None or row['lease_until'] < time.time() or self._lost_owner == job_id):
            raise Cancelled()
        return row

    def progress(self, job_id, message, progress=None, total=None, *, stage=None):
        with self.db.tx(immediate=True) as db:
            row = self._owned(db, job_id)
            if row['cancel_requested'] or self.stop_event.is_set():
                raise Cancelled()
            if stage:
                self._phase = stage
            now = time.time()
            args = [message[:400], now+LEASE_SECONDS, now, self._phase]
            sql = 'UPDATE jobs SET message=?,lease_until=?,heartbeat_at=?,stage=?'
            if progress is not None:
                sql += ',progress=?'; args.append(progress)
            if total is not None:
                sql += ',total=?'; args.append(total)
            sql += " WHERE id=? AND status='running' AND owner_token=? AND cancel_requested=0 AND lease_until>=?"
            args.extend([job_id, self.token, now])
            if not db.execute(sql, args).rowcount:
                raise Cancelled()
            if row['stage'] != self._phase:
                self._record(job_id, 'job_stage_changed', attempt=row['attempts'],
                             stage=self._phase, connection=db, checkpoint=message[:400])

    @contextmanager
    def _owned_transaction(self, job_id):
        """Fence application writes as well as lifecycle metadata."""
        with self.db.tx(immediate=True) as db:
            row = self._owned(db, job_id)
            if row['cancel_requested'] or self.stop_event.is_set():
                raise Cancelled()
            yield db
            # Cancellation/ownership cannot be changed by another writer while
            # the SQL writer lock is held. Renew before releasing that lock.
            if self.stop_event.is_set() or self._lost_owner == job_id:
                raise Cancelled()
            db.execute("UPDATE jobs SET lease_until=?,heartbeat_at=? WHERE id=? AND status='running' AND owner_token=?",
                       (time.time()+LEASE_SECONDS, time.time(), job_id, self.token))

    def _wait(self, seconds):
        self.wake.wait(seconds)
        self.wake.clear()

    def run(self):
        last_maintenance = 0
        failures = 0
        record_event(self.db, 'worker.started', stage='preflight')
        while not self.stop_event.is_set():
            try:
                self._heartbeat_at = self._last_poll_at = time.time()
                self._phase = 'preflight'
                report = None
                if self.installation is not None:
                    report = self.installation.reconcile()
                    if report.get('state') == 'blocked':
                        self._phase = 'blocked'
                        self._boot_reconciled = False
                        self._last_error = {'code': report.get('code'), 'message': report.get('message'), 'action': report.get('action')}
                        if self._announced_block != report.get('code'):
                            record_event(self.db, 'worker.blocked', code=report.get('code'),
                                         stage='preflight', state='blocked')
                            self._announced_block = report.get('code')
                        self._wait(5)
                        continue
                if self._announced_block is not None:
                    record_event(self.db, 'worker.recovered', stage='preflight')
                    self._announced_block = None
                self._last_error = None
                self._resume_environment_jobs(report)
                job = self.claim()
                if not job:
                    if self.rag and self.knowledge.active() and not self.rag.recovery.status()['available']:
                        self.ensure_warmup()
                    if time.time()-last_maintenance > 3600:
                        self.maintenance(); last_maintenance = time.time()
                    self._phase = 'idle'
                    self._last_error = None
                    failures = 0
                    self._wait(2)
                    continue
                self.current_job = job['id']
                with bind_context(job_id=job['id'], attempt=job['attempts'], boot_id=self.boot_id):
                    self.execute_job(job)
                failures = 0
                self._last_error = None
            except Exception as exc:
                failures += 1
                policy = failure_policy(exc)
                self._last_error = {key: policy[key] for key in ('code', 'message', 'action')}
                self._phase = 'waiting_dependency'
                delay = min(15, 2 ** min(failures-1, 4))
                event(LOG, 'worker_dependency_failed', level=logging.ERROR,
                      failure=safe_exception(exc), retry_seconds=delay, code=policy['code'])
                self._wait(delay)
            finally:
                self.current_job = None
        self._phase = 'stopped'

    @staticmethod
    def _payload(job):
        try:
            value = json.loads(job['payload_json'])
            if not isinstance(value, dict):
                raise ValueError('object required')
            if job['kind'] == 'warmup' and value.get('version_id') is not None and not isinstance(value['version_id'], str):
                raise ValueError('invalid version')
            if job['kind'] == 'warmup' and job.get('version_id') and value.get('version_id') not in {None, job['version_id']}:
                raise ValueError('version mismatch')
            if job['kind'] == 'import' and (not isinstance(value.get('path'), str) or not value['path']):
                raise ValueError('invalid path')
            if job['kind'] == 'evaluation' and not isinstance(value.get('tests'), list):
                raise ValueError('invalid tests')
            return value
        except (ValueError, TypeError, KeyError) as exc:
            raise DomainError('El contenido guardado del trabajo no es válido. No se ejecutó.', 409, 'invalid_job_payload') from exc

    def _complete(self, job, result, message='Finalizado'):
        with self.db.tx(immediate=True) as db:
            row = self._owned(db, job['id'])
            if row['cancel_requested'] or self.stop_event.is_set():
                raise Cancelled()
            base_id = result.get('base_id') if isinstance(result, dict) else None
            db.execute("UPDATE jobs SET status='done',stage='done',base_id=COALESCE(base_id,?),finished_at=?,message=?,result_json=?,lease_until=NULL,owner_token=NULL,error=NULL,error_code=NULL,error_stage=NULL,action=NULL,retryable=0 WHERE id=? AND status='running' AND owner_token=?",
                       (base_id, time.time(), message, dumps(result), job['id'], self.token))
            duration = time.monotonic()-job.get('_execution_started', time.monotonic())
            self._record(job['id'], 'job_completed', attempt=row['attempts'], stage='done',
                         connection=db, duration_ms=round(max(0,duration)*1000,2))

    def execute_job(self, job):
        job = dict(job)
        identifier, kind = job['id'], job['kind']
        started = time.monotonic()
        job['_execution_started'] = started
        self._phase = 'validate_payload'
        try:
            self.progress(identifier, 'Validando el trabajo y sus dependencias')
            payload = self._payload(job)
            self._phase = {'warmup': 'recovery', 'build': 'build', 'import': 'import', 'delete': 'delete', 'evaluation': 'evaluation'}.get(kind, 'execute')
            self.progress(identifier, 'Preparando trabajo')
            if kind == 'import':
                self.progress(identifier, 'Leyendo y validando el archivo', stage='read_upload')
                existing = self.db.one('SELECT id FROM bases WHERE id=?', (identifier,))
                if existing:
                    self._complete(job, {'base_id': identifier, 'recovered': True}, 'Importación recuperada sin duplicar la base')
                    return
                if self.cfg.storage_backend == 'minio' and payload.get('object_name'):
                    from .objects import objects
                    name = payload['object_name']
                    if (not isinstance(name, str) or Path(name).name != name or '/' in name or '\\' in name
                            or name in {'.', '..'}):
                        raise DomainError('Referencia de importación inválida.', 409, 'invalid_job_payload')
                    path = (self.cfg.data_dir/'uploads'/name).resolve()
                    objects(self.cfg).restore_upload(name, path, payload.get('object_sha256'))
                else:
                    path = Path(payload['path']).resolve()
                if not path.is_relative_to((self.cfg.data_dir/'uploads').resolve()):
                    raise DomainError('Ruta de importación inválida.', 409, 'invalid_job_payload')
                if self.cfg.storage_backend == 'minio' and not payload.get('object_name'):
                    from .objects import objects
                    if not path.is_file():
                        failure=DomainError('El archivo de una importación anterior no está disponible.',503,'legacy_upload_missing')
                        failure.details={'action':'Recuperá el archivo original o volvé a cargarlo; no se modificó ningún borrador ni publicación.'}
                        raise failure
                    objects(self.cfg).put('uploads/'+path.name,path.read_bytes())
                corpus = load_corpus(path, payload.get('audience', 'internal'), payload.get('cutoff_date'))
                corpus.document.filename = payload.get('filename', path.name)
                self.progress(identifier, 'Guardando borrador; no se publicará automáticamente', len(corpus.records), len(corpus.records), stage='import_draft')
                base_id = self.knowledge.import_corpus(corpus, payload.get('name', ''), payload.get('actor'), payload.get('filename', ''), import_id=identifier)
                with self._owned_transaction(identifier) as db:
                    changed = db.execute("UPDATE jobs SET base_id=? WHERE id=? AND status='running' AND owner_token=?", (base_id, identifier, self.token)).rowcount
                    if not changed:
                        raise Cancelled()
                    path.unlink(missing_ok=True)
                result = {'base_id': base_id, 'records': len(corpus.records)}
            elif kind == 'warmup':
                target = job.get('version_id') or payload.get('version_id')
                active = self.db.one('SELECT * FROM versions WHERE id=?', (target,)) if target else self.knowledge.active()
                if target and not active:
                    raise DomainError('Versión no encontrada.', 404, 'version_not_found')
                if self.rag:
                    def recovery_progress(message):
                        phase = getattr(self.rag.recovery, 'phase', None)
                        self.progress(identifier, message, stage=phase() if callable(phase) else 'recovery')
                    result = self.rag.recovery.recover(active, apply=True, progress=recovery_progress)
                else:
                    self.embeddings.load(); result = self.embeddings.profile
            elif kind in {'build', 'delete'}:
                from .storage import writer_lock
                with self.db.physical_lock(), writer_lock(self.cfg):
                    self.progress(identifier, 'Dependencias verificadas; ejecutando operación')
                    result = self.build(job) if kind == 'build' else self.delete(job)
            elif kind == 'evaluation':
                result = self.evaluate(job, payload)
            else:
                raise DomainError('Tipo de trabajo desconocido.', 409, 'invalid_job_payload')
            self._complete(job, result)
        except Cancelled:
            with self.db.tx(immediate=True) as db:
                try:
                    row = self._owned(db, identifier)
                except Cancelled:
                    self._record(identifier, 'job_ownership_lost', attempt=job.get('attempts',0), stage=self._phase, connection=db)
                    return
                requested = bool(row['cancel_requested'])
                stopped = self.stop_event.is_set() and not requested
                status = 'queued' if stopped else 'cancelled'
                db.execute("UPDATE jobs SET status=?,stage=?,owner_token=NULL,lease_until=NULL,available_at=?,message=?,finished_at=?,error=NULL,error_code=NULL,error_stage=NULL,action=NULL,retryable=0 WHERE id=? AND status='running' AND owner_token=?",
                           (status, status, time.time()+2 if stopped else 0,
                            'Pendiente tras detener el proceso' if stopped else 'Cancelado. La base activa no cambió.',
                            None if stopped else time.time(), identifier, self.token))
                if requested and job.get('version_id') and kind == 'build':
                    db.execute("UPDATE versions SET status='cancelled' WHERE id=? AND status!='ready' AND published_at IS NULL", (job['version_id'],))
                self._record(identifier, 'job_paused' if stopped else 'job_cancelled', attempt=row['attempts'], stage=status, connection=db)
        except Exception as exc:
            policy = failure_policy(exc)
            failed_stage = policy.get('stage') or self._phase
            with self.db.tx(immediate=True) as db:
                try:
                    row = self._owned(db, identifier)
                except Cancelled:
                    self._record(identifier, 'job_ownership_lost', attempt=job.get('attempts',0), stage=self._phase, connection=db)
                    return
                retry = policy['retryable'] and row['attempts'] < MAX_ATTEMPTS and not row['cancel_requested']
                delay = min(300, 30 * 2 ** max(0, row['attempts']-1)) if retry else 0
                status = 'queued' if retry else 'failed'
                self._record(identifier, 'job_attempt_failed', attempt=row['attempts'], stage=failed_stage,
                             code=policy['code'], message=policy['message'], connection=db,
                             retryable=policy['retryable'], retry_seconds=delay, action=policy['action'],
                             duration_ms=round((time.monotonic()-started)*1000, 2))
                db.execute("UPDATE jobs SET status=?,stage=?,available_at=?,finished_at=?,lease_until=NULL,owner_token=NULL,error=?,error_code=?,error_stage=?,action=?,retryable=?,message=? WHERE id=? AND status='running' AND owner_token=?",
                           (status, 'waiting_retry' if retry else 'failed', time.time()+delay,
                            None if retry else time.time(), None if retry else policy['message'],
                            policy['code'], failed_stage, policy['action'], int(policy['retryable']),
                            f'Reintento automático en {delay} segundos' if retry else 'El trabajo no se completó. La base activa no cambió.', identifier, self.token))
                if job.get('version_id') and kind == 'build':
                    db.execute("UPDATE versions SET status='failed' WHERE id=? AND status!='ready' AND published_at IS NULL", (job['version_id'],))
            event(LOG, 'job_failed', level=logging.WARNING, job_id=identifier,
                  code=policy['code'], failure=safe_exception(exc))

    def retry(self, job_id):
        with self.db.tx(immediate=True) as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not row or row['status'] not in {'failed', 'cancelled'}:
                raise DomainError('Este trabajo no admite reintento.', 409)
            if row['base_id'] and db.execute("SELECT 1 FROM jobs WHERE base_id=? AND status IN ('queued','running')", (row['base_id'],)).fetchone():
                raise DomainError('Ya existe un trabajo pendiente para esta base.', 409)
            if row['kind'] == 'warmup' and row['version_id'] and db.execute("SELECT 1 FROM jobs WHERE kind='warmup' AND version_id=? AND status IN ('queued','running')", (row['version_id'],)).fetchone():
                raise DomainError('Ya existe una recuperación pendiente para esta versión.', 409)
            db.execute("UPDATE jobs SET status='queued',stage='queued',attempts=0,available_at=0,cancel_requested=0,owner_token=NULL,lease_until=NULL,error=NULL,error_code=NULL,error_stage=NULL,action=NULL,retryable=0,finished_at=NULL,result_json=NULL,message='Reintento solicitado' WHERE id=? AND status IN ('failed','cancelled')", (job_id,))
            self._record(job_id, 'job_retry_requested', stage='queued', connection=db)
        self.wake.set()
        return job_id

    def cancel(self, job_id):
        with self.db.tx(immediate=True) as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not row or row['status'] not in {'queued', 'running'} or row['kind'] == 'delete':
                raise DomainError('Este trabajo no admite cancelación.', 409)
            if row['status'] == 'queued':
                db.execute("UPDATE jobs SET cancel_requested=1,status='cancelled',stage='cancelled',finished_at=?,owner_token=NULL,lease_until=NULL,error=NULL,error_code=NULL,error_stage=NULL,action=NULL,retryable=0,message='Cancelado antes de empezar. La base activa no cambió.' WHERE id=? AND status='queued'", (time.time(), job_id))
            else:
                db.execute("UPDATE jobs SET cancel_requested=1 WHERE id=? AND status='running'", (job_id,))
            self._record(job_id, 'job_cancel_requested', attempt=row['attempts'], stage=row['stage'], connection=db)
        self.wake.set()

    def status(self):
        result = {
            'enabled': bool(self.cfg.worker_enabled), 'alive': bool(self.thread and self.thread.is_alive()),
            'boot_id': self.boot_id, 'state': self._phase, 'heartbeat_at': self._heartbeat_at,
            'last_poll_at': self._last_poll_at, 'current_job': self.current_job,
            'last_error': self._last_error, 'queue': {},
        }
        try:
            result['queue'] = {row['status']: row['n'] for row in self.db.all('SELECT status,COUNT(*) n FROM jobs GROUP BY status')}
            row = self.db.one("SELECT MIN(available_at) next_at FROM jobs WHERE status='queued'")
            result['next_run_at'] = row['next_at'] if row else None
            running = self.db.one("SELECT id,lease_until,heartbeat_at,boot_id FROM jobs WHERE status='running' ORDER BY lease_until LIMIT 1")
            result['blocking_job'] = running if running and running['id'] != self.current_job else None
            if running and self._phase == 'idle' and self.current_job is None:
                result['state'] = 'waiting_for_lease'
        except Exception as exc:
            result['queue_available'] = False
            result['last_error'] = failure_policy(exc)
        return result

    def describe_job(self, row_or_id):
        row = self.db.one('SELECT * FROM jobs WHERE id=?', (row_or_id,)) if isinstance(row_or_id, str) else dict(row_or_id)
        if not row:
            raise DomainError('Trabajo inexistente.', 404)
        allowed = {'id', 'kind', 'status', 'base_id', 'version_id', 'progress', 'total', 'message', 'error',
                   'created_at', 'started_at', 'finished_at', 'result_json', 'cancel_requested', 'attempts',
                   'available_at', 'error_code', 'error_stage', 'stage', 'action', 'retryable',
                   'heartbeat_at', 'last_attempt_at', 'boot_id'}
        result = {key: value for key, value in row.items() if key in allowed}
        for key, default in {'attempts': 0, 'available_at': 0, 'stage': row['status'],
                             'error_code': None, 'error_stage': None, 'action': None,
                             'retryable': False, 'heartbeat_at': None,
                             'last_attempt_at': None, 'boot_id': None}.items():
            result.setdefault(key, default)
        result['max_attempts'] = MAX_ATTEMPTS
        result['retry_in_seconds'] = max(0, round((row.get('available_at') or 0)-time.time())) if row['status'] == 'queued' else None
        result['worker'] = self.status()
        try:
            result['events'] = self.db.all('SELECT at,event,attempt,boot_id,stage,code,message,details_json FROM job_events WHERE job_id=? ORDER BY id DESC LIMIT 30', (row['id'],))
            result['history_available'] = True
        except Exception as exc:
            # A schema-blocked installation must still explain the old job;
            # its missing history table must not turn diagnostics into a 500.
            result['events'] = []
            result['history_available'] = False
            event(LOG, 'job_history_unavailable', level=logging.WARNING,
                  job_id=row['id'], failure=safe_exception(exc))
        for entry in result['events']:
            try:
                entry['details'] = json.loads(entry.pop('details_json'))
            except (ValueError, TypeError):
                entry['details'] = {}
            entry['action'] = entry['details'].get('action')
        return result

    def build(self,job):
        from .storage import storage_identity
        storage_identity(self.db,self.cfg)
        id=job['id'];vid=job['version_id']
        version=self.db.one('SELECT * FROM versions WHERE id=?',(vid,))
        if not version:raise DomainError('Versión no encontrada.',404)
        if version['published_at'] is not None:
            raise DomainError('Una versión publicada solo admite recuperación exacta; no se vuelve a construir.',409,'published_version_protected')
        profile=json.loads(version['profile_json'])
        with self._owned_transaction(id) as db:
            db.execute("UPDATE versions SET status='building' WHERE id=? AND published_at IS NULL",(vid,))
        from .artifacts import ensure_models
        ensure_models(self.cfg,self.embeddings.engine_version,lambda message:self.progress(id,message,stage='restoring_models'))
        self.embeddings.load(lambda message:self.progress(id,message,stage='loading_models'))
        if profile.get('fingerprint') and profile['fingerprint']!=self.embeddings.profile['fingerprint']:
            raise DomainError('Cambió el modelo durante una reanudación. Creá una versión nueva; no mezcles vectores.',409,'embedding_mismatch')
        profile.update(self.embeddings.profile)
        with self._owned_transaction(id) as db:
            db.execute('UPDATE versions SET profile_json=? WHERE id=? AND published_at IS NULL',(dumps(profile),vid))
        existing=self.db.one('SELECT COUNT(*) AS n FROM chunks WHERE version_id=?',(vid,))['n']
        if not existing:
            records=self.db.all('SELECT content_json FROM version_records WHERE version_id=? ORDER BY record_key',(vid,))
            all_chunks=[]
            for i,r in enumerate(records):
                self.progress(id,'Dividiendo contenido con el tokenizador exacto del encoder',i,len(records),stage='chunking')
                record=json.loads(r['content_json'])
                if record['audience']!='public':raise DomainError('Se detectó contenido interno en una versión pública.')
                all_chunks.extend(chunks_for_record(vid,record,self.embeddings.count,profile['chunk_tokens'],profile['overlap_tokens']))
            if len(all_chunks)>30000:raise DomainError('Se excedió el máximo de 30.000 chunks para este perfil.')
            with self._owned_transaction(id) as db:
                for c in all_chunks:
                    db.execute('INSERT INTO chunks(id,version_id,record_key,position,title,topic,token_count,text,content_json,embedding_hash) VALUES(?,?,?,?,?,?,?,?,?,?)',
                        (c['id'],vid,c['record_id'],c['position'],c['title'],c['topic'],c['token_count'],c['text'],dumps(c),c['embedding_hash']))
        rows=self.db.all('SELECT id FROM chunks WHERE version_id=? ORDER BY record_key,position',(vid,))
        total=len(rows)
        if not total:raise DomainError('No se generaron chunks.')
        self.progress(id,'Creando colección aislada de la base publicada',0,total,stage='create_index')
        self.vector_store.create(version['collection_name'])
        reused=0;started=time.perf_counter()
        for offset in range(0,total,self.cfg.embedding_batch_size):
            self.progress(id,'Calculando embeddings y guardando lote',offset,total,stage='embedding_batches')
            rowids=[r['id'] for r in rows[offset:offset+self.cfg.embedding_batch_size]]
            batch=[json.loads(self.db.one('SELECT content_json FROM chunks WHERE id=?',(r,))['content_json']) for r in rowids]
            dense=[None]*len(batch);sparse=[None]*len(batch);missing=[]
            for i,c in enumerate(batch):
                cached=self.db.one('SELECT * FROM embedding_cache WHERE fingerprint=? AND embedding_hash=?',(profile['fingerprint'],c['embedding_hash']))
                if cached:
                    dense[i]=json.loads(cached['dense_json']);sparse[i]=json.loads(cached['sparse_json']);reused+=1
                else:missing.append(i)
            if missing:
                d,s=self.embeddings.documents([batch[i]['embedding_text'] for i in missing],[batch[i]['sparse_text'] for i in missing])
                for i,dv,sv in zip(missing,d,s,strict=True):dense[i]=dv;sparse[i]=sv
            self.vector_store.upsert(version['collection_name'],batch,dense,sparse)
            with self._owned_transaction(id) as db:
                for c,dv,sv in zip(batch,dense,sparse,strict=True):
                    db.execute('UPDATE chunks SET vector_json=? WHERE id=?',(dumps(dv),c['id']))
                    db.execute('INSERT OR IGNORE INTO embedding_cache VALUES(?,?,?,?,?)',(profile['fingerprint'],c['embedding_hash'],dumps(dv),dumps(sv),time.time()))
            # Release CPU between batches. Query inference shares the same model and lock.
            time.sleep(0.03)
        self.progress(id,'Comprobando cantidad de puntos y calculando visualización',total,total,stage='projection')
        if self.vector_store.count(version['collection_name'])!=total:raise DomainError('El conteo de LanceDB no coincide. No se habilita la publicación.')
        self.vector_store.finalize(version['collection_name'])
        projection=self.project(vid,id)
        self.progress(id,'Verificando integridad e inferencia local antes de habilitar la versión',total,total,stage='verify_index')
        report={'chunks':total,'reused_embeddings':reused,'build_seconds':round(time.perf_counter()-started,3),
            'max_tokens':self.db.one('SELECT MAX(token_count) n FROM chunks WHERE version_id=?',(vid,))['n'],
            'projection':projection,'public_only':True,'contextualizer_version':CONTEXTUALIZER_VERSION,
            'semantic_accuracy_evaluated':False}
        if self.rag:
            # Validate the completed candidate without advertising it as ready
            # in SQL before its physical index and local inference pass.
            candidate=self.db.one('SELECT * FROM versions WHERE id=?',(vid,))
            candidate.update(status='ready',chunk_count=total,report_json=dumps(report))
            self.rag.recovery.verify(candidate)
        with self._owned_transaction(id) as db:
            db.execute("UPDATE versions SET status='ready',chunk_count=?,report_json=? WHERE id=? AND published_at IS NULL",(total,dumps(report),vid))
        return report

    def project(self,vid,job_id):
        import numpy as np
        rows=self.db.all('SELECT id,vector_json FROM chunks WHERE version_id=? AND vector_json IS NOT NULL ORDER BY id LIMIT 1200',(vid,))
        if len(rows)<2:return {'method':'PCA','points':0,'note':'Se necesitan dos puntos.'}
        matrix=np.array([json.loads(r['vector_json']) for r in rows],dtype=np.float32)
        matrix-=matrix.mean(axis=0)
        cov=matrix.T@matrix
        vals,vecs=np.linalg.eigh(cov)
        xy=matrix@vecs[:,-2:]
        for axis in range(2):
            extent=float(np.abs(xy[:,axis]).max())
            if extent:xy[:,axis]/=extent
        with self._owned_transaction(job_id) as db:
            for row,p in zip(rows,xy,strict=True):
                db.execute('UPDATE chunks SET projection_x=?,projection_y=? WHERE id=?',(float(p[0]),float(p[1]),row['id']))
        explained=float(max(0,vals[-2:].sum())/max(float(vals.sum()),1e-12))
        return {'method':'PCA','points':len(rows),'max_points':1200,'explained_variance_ratio':round(explained,5),
                'note':'Proyección aproximada, no clasificación ni prueba de calidad semántica. Muestra determinista por ID cuando hay más de 1200 puntos.'}

    def delete(self,job):
        bid=job['base_id'];active=self.knowledge.active()
        if active and active['base_id']==bid:raise DomainError('No se puede eliminar una base activa.',409)
        with self._owned_transaction(job['id']) as db:
            active=db.execute('SELECT 1 FROM active_knowledge a JOIN versions v ON a.version_id=v.id WHERE v.base_id=?',(bid,)).fetchone()
            if active:raise DomainError('No se puede eliminar una base activa.',409)
            db.execute("UPDATE bases SET status='deleting' WHERE id=?",(bid,))
        versions=self.db.all('SELECT * FROM versions WHERE base_id=?',(bid,))
        for i,v in enumerate(versions):
            self.progress(job['id'],'Eliminando colección de conocimiento',i,len(versions),stage='delete_collections')
            self.vector_store.delete(v['collection_name'])
        with self._owned_transaction(job['id']) as db:
            db.execute('DELETE FROM bases WHERE id=?',(bid,))
        return {'deleted_base_id':bid}

    def evaluate(self,job,payload):
        if not self.rag:raise DomainError('Laboratorio no disponible.')
        tests=payload.get('tests',[])
        if not tests or len(tests)>200:raise DomainError('La evaluación admite entre 1 y 200 preguntas.')
        settings=get_settings(self.db,self.cfg);results=[]
        for i,test in enumerate(tests):
            self.progress(job['id'],'Evaluando la recuperación; no se llama al modelo generativo',i,len(tests),stage='retrieval_evaluation')
            found,trace=self.rag.retriever.search(test['question'],settings,job['version_id'],limit=settings.retrieval_limit)
            ms=trace['ms']
            ids=[x['record_id'] for x in found]
            expected=set(test.get('expected_any_record_ids',[]))
            groups=[]
            for index,group in enumerate(test.get('expected_groups',[]),1):
                group_expected=set(group.get('any_record_ids',[]))
                groups.append({'name':group.get('name') or f'grupo-{index}',
                    'expected':sorted(group_expected),'hit':bool(group_expected & set(ids))})
            success=(all(group['hit'] for group in groups) if groups
                     else bool(expected&set(ids)) if expected else None)
            results.append({'question':test['question'],'expected':sorted(expected),'expected_groups':groups,
                'retrieved':ids,'hit':success,'latency_ms':round(ms,2),'retrieval_trace':trace})
        assessed=[r for r in results if r['hit'] is not None]
        return {'kind':'final_context_coverage','questions':len(results),'assessed':len(assessed),
                'hit_rate':sum(r['hit'] for r in assessed)/len(assessed) if assessed else None,
                'warning':'La cobertura del contexto final no garantiza la exactitud de una respuesta generada.', 'results':results}

    def maintenance(self):
        now=time.time();settings=get_settings(self.db,self.cfg)
        with self.db.tx(immediate=True) as db:
            db.execute('DELETE FROM admin_sessions WHERE expires_at<? OR touched_at<?',(now,now-1800))
            db.execute('DELETE FROM auth_challenges WHERE expires_at<?',(now-3600,))
            db.execute('DELETE FROM chat_sessions WHERE expires_at<?',(now,))
            db.execute('DELETE FROM queries WHERE at<?',(now-settings.analytics_days*86400,))
            for window in (60,300,900,3600,86400):
                db.execute("DELETE FROM rate_limits WHERE `key` LIKE ? AND bucket<?",(f'%:{window}',int(now//window)-max(2,172800//window)))
        # Cache expiry is separate from the authoritative corpus and vector versions.
        self.db.execute('DELETE FROM embedding_cache WHERE created_at<?',(now-180*86400,))
