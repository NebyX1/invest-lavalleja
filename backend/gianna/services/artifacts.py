"""Pinned, resumable artifact preparation. Called by workers/CLI only, never by HTTP."""
import hashlib
import errno
import json
import logging
import time
import urllib.error
import urllib.request

from ..errors import DomainError, Cancelled
from ..observability import bind_context, event, safe_exception
from .neural import artifact_specs, verified_manifest
from .storage import atomic_json

LOG = logging.getLogger(__name__)
MIB = 1024 * 1024


class ArtifactValidationError(ValueError):
    """Fixed operational codes, never transport bodies or provider messages."""
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def failure_code(exc):
    if isinstance(exc, ArtifactValidationError):
        return exc.code
    if isinstance(exc, (TimeoutError,)):
        return 'model_download_timeout'
    if isinstance(exc, urllib.error.HTTPError):
        return 'artifact_download_denied' if exc.code in {401, 403} else 'artifact_download_unavailable'
    if isinstance(exc, urllib.error.URLError):
        return 'model_download_timeout' if isinstance(exc.reason, TimeoutError) else 'artifact_network_unavailable'
    if isinstance(exc, OSError):
        if exc.errno == errno.ENOSPC:
            return 'storage_full'
        if exc.errno in {errno.EACCES, errno.EPERM}:
            return 'storage_permission_denied'
        if exc.errno == errno.EROFS:
            return 'storage_read_only'
    return 'artifact_preparation_failed'


def ensure_models(cfg, engine_version, progress=None):
    specs = artifact_specs(engine_version)
    for kind, model_id, revision, files in specs:
        with bind_context(profile=engine_version, artifact_kind=kind, revision=revision):
            began = time.monotonic()
            event(LOG, 'artifacts.prepare_started', model_id=model_id, files=len(files))
            folder = cfg.model_dir / kind / revision
            try:
                manifest = verified_manifest(folder, model_id, revision, files)
                event(LOG, 'artifacts.verified', model_id=model_id, offline=True,
                      verified_bytes=sum(manifest['files'][name]['bytes'] for name in files),
                      duration_ms=round((time.monotonic()-began)*1000, 2))
                continue  # Verified offline path never contacts the model hub.
            except DomainError:
                pass
            failure = None
            for attempt in range(3):
                try:
                    with bind_context(download_attempt=attempt+1):
                        _prepare(folder, model_id, revision, files, progress)
                    manifest = verified_manifest(folder, model_id, revision, files)
                    event(LOG, 'artifacts.verified', model_id=model_id, offline=False,
                          verified_bytes=sum(manifest['files'][name]['bytes'] for name in files),
                          duration_ms=round((time.monotonic()-began)*1000, 2))
                    failure = None
                    break
                except Cancelled:
                    event(LOG, 'artifacts.prepare_cancelled', model_id=model_id,
                          duration_ms=round((time.monotonic()-began)*1000, 2))
                    raise
                except DomainError:
                    raise
                except Exception as exc:
                    failure = exc
                    event(LOG, 'artifacts.prepare_failed', level=logging.WARNING,
                          model_id=model_id, download_attempt=attempt+1,
                          code=failure_code(exc), exception=safe_exception(exc),
                          retry_seconds=2 ** attempt if attempt < 2 else None,
                          duration_ms=round((time.monotonic()-began)*1000, 2))
                    if attempt < 2:
                        time.sleep(2 ** attempt)
            if failure:
                error = DomainError('No se pudieron recuperar los artefactos fijados. Revisá conectividad, espacio y permisos.',
                                    503, 'models_recovery_failed')
                error.details = {'cause_code': failure_code(failure), 'profile': engine_version,
                                 'artifact_kind': kind, 'revision': revision}
                raise error from failure


def _download(path, model_id, revision, name, expected_bytes, verify, deadline, headers, progress):
    """Bounded file transfer, with checkpoints rather than a fake job percentage."""
    began = time.monotonic()
    total = last_bytes = 0
    last_at = began
    fields = {'model_id': model_id, 'revision': revision,
              'artifact_file': name, 'expected_bytes': expected_bytes}
    event(LOG, 'artifacts.download_started', downloaded_bytes=0, **fields)

    def checkpoint(force=False):
        nonlocal last_at, last_bytes
        now = time.monotonic()
        if force or now-last_at >= 2 or total-last_bytes >= 10*MIB:
            event(LOG, 'artifacts.download_progress', downloaded_bytes=total,
                  duration_ms=round((now-began)*1000, 2), **fields)
            if progress:
                quantity = (f'{total/MIB:.1f} MiB de {expected_bytes/MIB:.1f} MiB'
                            if expected_bytes >= MIB else f'{total} de {expected_bytes} bytes')
                progress(f'Descargando artefactos del motor: {name}, {quantity}.')
            last_at, last_bytes = now, total

    temporary = path.with_name(path.name + '.download')
    try:
        checkpoint(force=True)
        request = urllib.request.Request(f'https://huggingface.co/{model_id}/resolve/{revision}/{name}', headers=headers)
        with urllib.request.urlopen(request, timeout=45) as response, temporary.open('wb') as target:
            while block := response.read(MIB):
                total += len(block)
                if total > expected_bytes:
                    raise ArtifactValidationError('artifact_size_mismatch')
                if time.monotonic() > deadline:
                    raise TimeoutError('artifact download bound')
                target.write(block)
                checkpoint()
            target.flush()
            import os
            os.fsync(target.fileno())
        checksum = verify(temporary)
        if checksum is None:
            raise ArtifactValidationError('artifact_integrity_failed')
        temporary.replace(path)
        checkpoint(force=True)
        event(LOG, 'artifacts.download_completed', downloaded_bytes=total,
              duration_ms=round((time.monotonic()-began)*1000, 2), **fields)
        return checksum
    except Cancelled:
        event(LOG, 'artifacts.download_cancelled', downloaded_bytes=total,
              duration_ms=round((time.monotonic()-began)*1000, 2), **fields)
        raise
    except Exception as exc:
        cause = getattr(exc, 'reason', None)
        event(LOG, 'artifacts.download_failed', level=logging.WARNING,
              code=failure_code(exc), downloaded_bytes=total,
              duration_ms=round((time.monotonic()-began)*1000, 2),
              cause_type=type(cause).__name__ if isinstance(cause, BaseException) else None,
              exception=safe_exception(exc), **fields)
        raise


def _prepare(folder, model_id, revision, files, progress):
    deadline = time.monotonic() + 900
    headers = {'User-Agent': 'Gianna-Pinned-Recovery/1.0'}
    request = urllib.request.Request(f'https://huggingface.co/api/models/{model_id}/revision/{revision}?blobs=true', headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        metadata = json.load(response)
    if metadata.get('sha') != revision:
        raise ArtifactValidationError('artifact_revision_mismatch')
    entries = {entry['rfilename']: entry for entry in metadata['siblings']}
    manifest = {'model_id': model_id, 'revision': revision, 'files': {}}
    for name in files:
        if progress: progress('Restaurando artefactos verificados del motor.')
        info = entries[name]; expected = (info.get('lfs') or {}).get('sha256')
        # Non-LFS files are identified by the Git blob hash of the pinned commit.
        blob = info.get('blobId')
        if not expected and not blob:
            raise ArtifactValidationError('artifact_digest_missing')
        if type(info.get('size')) is not int or info['size'] < 0:
            raise ArtifactValidationError('artifact_size_invalid')
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        def verify(candidate):
            if not candidate.is_file() or candidate.stat().st_size != info['size']:
                return None
            sha256 = hashlib.sha256(); sha1 = hashlib.sha1()
            sha1.update(f"blob {info['size']}\0".encode())
            with candidate.open('rb') as stream:
                while block := stream.read(1024*1024):
                    sha256.update(block); sha1.update(block)
            if (expected and sha256.hexdigest() != expected) or (not expected and sha1.hexdigest() != blob):
                return None
            return sha256.hexdigest()
        checksum = verify(path)
        if checksum is None:
            checksum = _download(path, model_id, revision, name, info['size'], verify,
                                 deadline, headers, progress)
        manifest['files'][name] = {'bytes': info['size'], 'sha256': checksum}
    atomic_json(folder / 'manifest.json', manifest)
