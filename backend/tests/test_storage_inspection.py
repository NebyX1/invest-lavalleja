"""Storage evidence is read-only; a mount source/environment is never disclosed."""
from dataclasses import replace
import json
import os
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest

from gianna.errors import DomainError
from gianna.services.storage import inspect_storage, mounted_data_dir, storage_identity


def mount_line(point, fs='ext4', options='rw', source='/dev/not-disclosed'):
    escaped = str(point).replace('\\', '\\134').replace(' ', '\\040').replace('\t', '\\011')
    return f'1 0 8:1 / {escaped} {options} - {fs} {source} {options}\n'


def mountinfo(monkeypatch, text):
    read = Path.read_text
    def reader(path, *args, **kwargs):
        if str(path) == str(Path('/proc/self/mountinfo')):
            return text
        return read(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', reader)


@pytest.mark.parametrize('point,fs,rw,expected', [
    ('exact', 'ext4', 'rw', True), ('parent', 'ext4', 'rw', True),
    ('root', 'ext4', 'rw', False), ('exact', 'tmpfs', 'rw', False),
    ('exact', 'overlay', 'rw', False), ('exact', 'ext4', 'ro', False),
])
def test_mount_evidence_for_exact_parent_ephemeral_and_read_only(cfg, monkeypatch, point, fs, rw, expected):
    selected = cfg.data_dir if point == 'exact' else cfg.data_dir.parent if point == 'parent' else Path(cfg.data_dir.anchor)
    mountinfo(monkeypatch, mount_line(selected, fs, rw))
    assert mounted_data_dir(cfg.data_dir) is expected


def test_nested_temporary_mount_overrides_durable_parent(cfg, monkeypatch):
    mountinfo(monkeypatch, mount_line(cfg.data_dir.parent) + mount_line(cfg.data_dir, 'tmpfs'))
    report = inspect_storage(None, replace(cfg, production=True))
    assert report['code'] == 'storage_not_mounted'
    assert report['mount']['filesystem'] == 'tmpfs'


def test_mountinfo_all_escapes_and_source_credentials_are_not_exposed(cfg, monkeypatch):
    mountinfo(monkeypatch, mount_line(cfg.data_dir, source='//user:secret@network/share'))
    report = inspect_storage(None, replace(cfg, production=True))
    assert report['ok'] and report['mount']['mountpoint'] == str(cfg.data_dir)
    assert 'secret' not in json.dumps(report) and 'network/share' not in json.dumps(report)


def test_missing_mountinfo_is_distinct_and_does_not_claim_missing_volume(cfg, monkeypatch):
    read = Path.read_text
    def reader(path, *args, **kwargs):
        if str(path) == str(Path('/proc/self/mountinfo')):
            raise PermissionError('Sensitive path')
        return read(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', reader)
    report = inspect_storage(None, replace(cfg, production=True))
    assert report['code'] == 'storage_mount_unknown'
    assert 'Sensitive path' not in json.dumps(report)


def test_readonly_mount_and_process_permissions_have_separate_codes(cfg, monkeypatch):
    mountinfo(monkeypatch, mount_line(cfg.data_dir, options='ro'))
    assert inspect_storage(None, replace(cfg, production=True))['code'] == 'storage_read_only'
    mountinfo(monkeypatch, mount_line(cfg.data_dir))
    monkeypatch.setattr(os, 'access', lambda *args: False)
    assert inspect_storage(None, replace(cfg, production=True))['code'] == 'storage_permission_denied'


def test_full_volume_is_reported_before_a_download_or_writer_probe(cfg, monkeypatch):
    monkeypatch.setattr('gianna.services.storage.shutil.disk_usage',
                        lambda path: SimpleNamespace(total=1000, used=1000, free=0))
    report = inspect_storage(None, cfg)
    assert report['code'] == 'storage_full' and report['disk']['free_bytes'] == 0


def test_storage_inspection_does_not_create_missing_directory_or_bind_identity(db, cfg):
    target = replace(cfg, data_dir=cfg.data_dir / 'not-created' / 'data')
    before = db.all('SELECT * FROM settings')
    report = inspect_storage(db, target)
    assert report['ok'] and not report['exists']
    assert report['identity']['state'] == 'uninitialized'
    assert not target.data_dir.exists() and db.all('SELECT * FROM settings') == before


def test_identity_mismatch_is_reported_without_mutations_and_adoption_stays_explicit(db, cfg):
    storage_identity(db, cfg, write=True)
    registered = db.setting('physical_storage_identity')
    marker = cfg.data_dir / '.gianna-storage.json'
    other = str(uuid.uuid4())
    marker.write_text(json.dumps({'id': other, 'format': 1}))
    report = inspect_storage(db, cfg)
    assert report['code'] == 'storage_mismatch' and report['identity']['actual'] == other
    with pytest.raises(DomainError) as error:
        storage_identity(db, cfg, write=True)
    assert error.value.code == 'storage_mismatch'
    assert db.setting('physical_storage_identity') == registered
    storage_identity(db, cfg, adopt=True, write=True)
    assert inspect_storage(db, cfg)['ok'] and db.setting('physical_storage_identity') == other


def test_malformed_identity_is_not_silently_adopted(db, cfg):
    marker = cfg.data_dir / '.gianna-storage.json'
    original = '{"password":"never-disclose"}'
    marker.write_text(original)
    report = inspect_storage(db, cfg)
    assert report['code'] == 'storage_identity_invalid'
    assert 'never-disclose' not in json.dumps(report)
    with pytest.raises(DomainError):
        storage_identity(db, cfg, adopt=True, write=True)
    assert marker.read_text() == original and db.setting('physical_storage_identity') is None


def test_unavailable_sql_does_not_disclose_connection_string(cfg):
    def unavailable(*args):
        raise RuntimeError('mariadb://admin:secret@host/database')
    report = inspect_storage(SimpleNamespace(setting=unavailable), cfg)
    assert report['code'] == 'database_unavailable' and report['retryable']
    assert 'secret' not in json.dumps(report)
