"""Pinned, resumable artifact preparation. Called by workers/CLI only, never by HTTP."""
import hashlib
import json
import logging
import time
import urllib.request

from ..errors import DomainError, Cancelled
from .neural import artifact_specs, verified_manifest
from .storage import atomic_json

LOG = logging.getLogger(__name__)


def ensure_models(cfg, engine_version, progress=None):
    specs = artifact_specs(engine_version)
    for kind, model_id, revision, files in specs:
        folder = cfg.model_dir / kind / revision
        try:
            verified_manifest(folder, model_id, revision, files)
            continue  # Offline fast path: don't contact the model hub for verified artifacts.
        except DomainError:
            pass
        failure = None
        for attempt in range(3):
            try:
                _prepare(folder, model_id, revision, files, progress)
                verified_manifest(folder, model_id, revision, files)
                failure = None
                break
            except (DomainError, Cancelled):
                raise
            except Exception as exc:
                failure = exc
                LOG.warning('Recuperación de artefactos: perfil=%s modelo=%s intento=%s tipo=%s',
                            engine_version, kind, attempt+1, type(exc).__name__)
                if attempt < 2:
                    time.sleep(2 ** attempt)
        if failure:
            raise DomainError('No se pudieron recuperar los artefactos fijados. Revisá conectividad, espacio y permisos.',
                              503, 'models_recovery_failed') from failure


def _prepare(folder, model_id, revision, files, progress):
    deadline = time.monotonic() + 900
    headers = {'User-Agent': 'Gianna-Pinned-Recovery/1.0'}
    request = urllib.request.Request(f'https://huggingface.co/api/models/{model_id}/revision/{revision}?blobs=true', headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        metadata = json.load(response)
    if metadata.get('sha') != revision:
        raise ValueError('revision')
    entries = {entry['rfilename']: entry for entry in metadata['siblings']}
    manifest = {'model_id': model_id, 'revision': revision, 'files': {}}
    for name in files:
        if progress: progress('Restaurando artefactos verificados del motor.')
        info = entries[name]; expected = (info.get('lfs') or {}).get('sha256')
        # Non-LFS files are identified by the Git blob hash of the pinned commit.
        blob = info.get('blobId')
        if not expected and not blob:
            raise ValueError('missing trusted digest')
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
            temporary = path.with_name(path.name + '.download')
            total = 0
            request = urllib.request.Request(f'https://huggingface.co/{model_id}/resolve/{revision}/{name}', headers=headers)
            with urllib.request.urlopen(request, timeout=45) as response, temporary.open('wb') as target:
                while block := response.read(1024*1024):
                    if progress: progress('Descargando artefactos del perfil publicado.')
                    total += len(block)
                    if total > info['size'] or time.monotonic() > deadline:
                        raise TimeoutError('artifact download bound')
                    target.write(block)
                target.flush()
                import os
                os.fsync(target.fileno())
            checksum = verify(temporary)
            if checksum is None:
                raise ValueError('integrity')
            temporary.replace(path)
        manifest['files'][name] = {'bytes': info['size'], 'sha256': checksum}
    atomic_json(folder / 'manifest.json', manifest)
