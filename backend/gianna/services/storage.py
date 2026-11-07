"""Persistent storage identity and cross-process writer exclusion. No editorial writes."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
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


def _unescape_mount(value):
    return re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), value)


def _mount_report(path):
    """Read the most specific mount covering a resolved path, without probes.

    A nested tmpfs/readonly mount overrides its durable parent. Mount sources
    are deliberately omitted: network mount names can contain credentials.
    """
    report = {'observed': False, 'mountpoint': None, 'filesystem': None,
              'read_only': None, 'durable': False}
    try:
        lines = Path('/proc/self/mountinfo').read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeError):
        return {**report, 'code': 'storage_mount_unknown'}
    target = Path(path).resolve()
    matches = []
    for line in lines:
        try:
            before, after = line.split(' - ', 1)
            fields, filesystem = before.split(), after.split()
            point = Path(_unescape_mount(fields[4]))
            if not target.is_relative_to(point):
                continue
            options = set(fields[5].split(',')) | set(filesystem[2].split(','))
            matches.append((len(point.parts), point, filesystem[0], 'ro' in options))
        except (IndexError, ValueError):
            continue
    if not matches:
        return {**report, 'observed': True, 'code': 'storage_not_mounted'}
    _, point, filesystem, readonly = max(matches, key=lambda match: match[0])
    ephemeral = {'tmpfs', 'ramfs', 'overlay', 'aufs', 'devtmpfs', 'proc', 'sysfs'}
    durable = point.parent != point and filesystem not in ephemeral
    return {'observed': True, 'mountpoint': str(point), 'filesystem': filesystem,
            'read_only': readonly, 'durable': durable,
            'code': None if durable else 'storage_not_mounted'}


def mounted_data_dir(path):
    """A durable, writable mount may cover DATA_DIR itself or a parent."""
    mount = _mount_report(path)
    return mount['durable'] and not mount['read_only']


def inspect_storage(db, cfg):
    """Pure local/SQL inventory. No mkdir, write probe, binding or adoption.

    The result is safe for authenticated diagnostics and CLI JSON. It never
    returns database URLs, mount sources, environment values or file contents.
    """
    path = Path(cfg.data_dir).resolve()
    issues = []
    def issue(code, message, action, retryable=False):
        issues.append({'code': code, 'message': message, 'action': action,
                       'retryable': retryable})

    mount = _mount_report(path) if cfg.production else {
        'observed': False, 'mountpoint': None, 'filesystem': None,
        'read_only': None, 'durable': None, 'code': None}
    if cfg.production:
        if mount['code'] == 'storage_mount_unknown':
            issue('storage_mount_unknown', 'No se pudo comprobar el montaje de DATA_DIR.',
                  'Revisá /proc/self/mountinfo y los montajes del contenedor antes de ejecutar recuperación.')
        elif not mount['durable']:
            issue('storage_not_mounted', 'DATA_DIR no está cubierto por un montaje persistente.',
                  'Montá el almacenamiento existente en la ruta efectiva indicada; conservá sus archivos antes de recrear el contenedor.')
        elif mount['read_only']:
            issue('storage_read_only', 'El montaje que contiene DATA_DIR es de solo lectura.',
                  'Configurá este volumen de datos como lectura/escritura y redesplegá el recurso.')

    writable = False
    exists = False
    disk = {'available': False}
    try:
        exists = path.exists()
        if exists and not path.is_dir():
            issue('storage_path_invalid', 'DATA_DIR apunta a un archivo, no a un directorio.',
                  'Corregí la ruta efectiva del directorio de datos; preservá el archivo existente.')
        else:
            parent = path
            while not parent.exists() and parent.parent != parent:
                parent = parent.parent
            writable = os.access(parent, os.W_OK | os.X_OK)
            if not writable:
                issue('storage_permission_denied', 'El proceso no puede escribir en DATA_DIR.',
                      'Revisá permisos y propietario del volumen para el UID/GID del proceso, sin abrir permisos globales.')
            try:
                usage = shutil.disk_usage(parent)
                disk = {'available': True, 'total_bytes': usage.total, 'free_bytes': usage.free}
                if usage.free == 0:
                    issue('storage_full', 'El volumen no tiene espacio libre.',
                          'Liberá capacidad mediante el mantenimiento de respaldos o ampliá el volumen; no borres índices ni datos publicados automáticamente.')
            except OSError:
                pass
    except OSError:
        issue('storage_permission_denied', 'El proceso no puede inspeccionar DATA_DIR.',
              'Revisá acceso y permisos del volumen para el UID/GID del proceso.')

    expected = actual = None
    identity_valid = True
    try:
        expected = db.setting('physical_storage_identity') if db is not None else None
        if expected is not None:
            uuid.UUID(expected)
    except (ValueError, TypeError, AttributeError):
        identity_valid = False
        issue('storage_identity_invalid', 'La identidad de almacenamiento registrada en SQL es inválida.',
              'Revisá la configuración registrada y los respaldos; no regeneres la identidad automáticamente.')
    except Exception:
        issue('database_unavailable', 'No se pudo consultar la identidad del volumen en la base de datos.',
              'Restablecé la conexión MariaDB y repetí el diagnóstico.', True)
    marker = path / '.gianna-storage.json'
    try:
        if marker.is_symlink():
            raise ValueError('Storage identity must be on its own volume')
        if marker.exists():
            document = json.loads(marker.read_text(encoding='utf-8'))
            actual = document['id']
            uuid.UUID(actual)
            if document.get('format', 1) != 1:
                raise ValueError('Unsupported identity format')
    except (ValueError, TypeError, KeyError, AttributeError):
        actual = None
        identity_valid = False
        issue('storage_identity_invalid', 'El identificador del volumen es inválido.',
              'Conservá el identificador y revisá el volumen original o un respaldo antes de una adopción explícita.')
    except OSError:
        identity_valid = False
        issue('storage_permission_denied', 'No se pudo leer la identidad del volumen.',
              'Revisá los permisos del identificador de almacenamiento y del volumen.')
    matched = bool(identity_valid and actual and actual == expected)
    identity_state = ('invalid' if not identity_valid else 'matched' if matched else
                      'mismatch' if expected else 'unregistered' if actual else 'uninitialized')
    if identity_valid and expected and not matched:
        issue('storage_mismatch', 'El volumen conectado no coincide con el registrado en SQL.',
              'Reconectá el volumen original; la adopción de otro volumen requiere inspección y respaldo explícitos.')
    identity = {'state': identity_state, 'expected': expected if identity_valid else None,
                'actual': actual if identity_valid else None, 'matched': matched,
                'initialized': bool(expected)}
    first = issues[0] if issues else {'code': None, 'message': 'Almacenamiento disponible para verificar el conocimiento.',
                                      'action': '', 'retryable': False}
    return {'ok': not issues, **first, 'path': str(path), 'exists': exists,
            'writable': writable, 'mount': mount, 'identity': identity, 'issues': issues, 'disk': disk,
            'uid': os.getuid() if hasattr(os, 'getuid') else None,
            'gid': os.getgid() if hasattr(os, 'getgid') else None}


def storage_identity(db, cfg, *, adopt=False, write=False):
    inspection = inspect_storage(db, cfg)
    blockers = [item for item in inspection['issues'] if not (adopt and item['code'] == 'storage_mismatch')]
    if blockers:
        blocker = blockers[0]
        error = DomainError(blocker['message'] + ' ' + blocker['action'], 503, blocker['code'])
        error.details = {'action': blocker['action'], 'retryable': blocker['retryable'],
                         'path': inspection['path'], 'mount': inspection['mount'],
                         'identity': inspection['identity']}
        raise error
    path = cfg.data_dir / '.gianna-storage.json'
    expected = inspection['identity']['expected']
    actual = inspection['identity']['actual']
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
