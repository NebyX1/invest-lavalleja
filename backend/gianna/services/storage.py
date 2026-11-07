"""Persistent storage identity and cross-process writer exclusion. No editorial writes."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import uuid

from ..errors import DomainError


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.partial')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def writer_lock(cfg):
    """One local volume writer, including CLI processes; never removes another lock."""
    path = cfg.data_dir / '.physical-recovery.lock'
    with path.open('a+b') as stream:
        try:
            if os.name == 'nt':
                import msvcrt
                stream.seek(0)
                if not stream.read(1):
                    stream.write(b'0'); stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise DomainError('Hay otra operación sobre el almacenamiento.', 503, 'recovery_busy') from exc
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def mounted_data_dir(path):
    """Require an actual mount at DATA_DIR in Linux containers, not an image layer."""
    try:
        target = str(Path(path).resolve())
        mounts = Path('/proc/self/mountinfo').read_text().splitlines()
        for line in mounts:
            fields,filesystem=line.split(' - ',1)
            if fields.split()[4].replace('\\040',' ')==target:
                return filesystem.split()[0] not in {'tmpfs','ramfs','overlay','aufs'}
        return False
    except (OSError, IndexError, ValueError):
        return False


def storage_identity(db, cfg, *, adopt=False, write=False):
    if cfg.production and not mounted_data_dir(cfg.data_dir):
        raise DomainError('Falta un montaje persistente en DATA_DIR. Revisá el recurso de despliegue.', 503, 'storage_not_mounted')
    path = cfg.data_dir / '.gianna-storage.json'
    expected = db.setting('physical_storage_identity')
    try:
        actual = json.loads(path.read_text(encoding='utf-8'))['id'] if path.exists() else None
        if actual is not None:
            uuid.UUID(actual)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise DomainError('El identificador del almacenamiento es inválido.', 503, 'storage_mismatch') from exc
    if expected and actual != expected and not adopt:
        raise DomainError('El almacenamiento no coincide con el registrado. Verificá montajes y respaldos antes de adoptarlo.', 503, 'storage_mismatch')
    if not write:
        return {'matched': bool(actual and actual == expected), 'initialized': bool(expected)}
    identity = actual or str(uuid.uuid4())
    if not actual:
        atomic_json(path, {'id': identity, 'format': 1})
    with db.tx(immediate=True) as connection:
        row = connection.execute('SELECT value FROM settings WHERE `key`=?',('physical_storage_identity',)).fetchone()
        expected = json.loads(row['value']) if row else None
        if expected != identity:
            if expected and not adopt:
                raise DomainError('Se requiere adopción explícita del almacenamiento.', 503, 'storage_mismatch')
            connection.execute('INSERT INTO settings(`key`,value) VALUES(?,?) ON CONFLICT(`key`) DO UPDATE SET value=excluded.value',
                               ('physical_storage_identity', json.dumps(identity)))
    return {'matched': True, 'initialized': True}
