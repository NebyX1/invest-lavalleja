from types import SimpleNamespace
import subprocess

import pytest

from scripts.backup import create_backup


def config():
    return SimpleNamespace(
        database_url='mariadb+mariadbconnector://gianna:db-secret@db.example.test:3306/gianna_test'
    )


def test_create_backup_uses_secret_outside_command_and_keeps_dump_private(tmp_path, monkeypatch):
    calls = []

    def dump(command, *, env, stdout, stderr, check):
        calls.append((command, env, stderr, check))
        stdout.write(b'-- MariaDB dump\n')

    monkeypatch.setattr(subprocess, 'run', dump)
    destination = tmp_path / 'backup.sql'

    result = create_backup(config(), destination)

    command, env, stderr, checked = calls[0]
    assert result == destination.resolve()
    assert result.read_bytes() == b'-- MariaDB dump\n'
    assert 'db-secret' not in ' '.join(command)
    assert env['MYSQL_PWD'] == 'db-secret'
    assert stderr == subprocess.PIPE
    assert checked is True
    assert '--single-transaction' in command


def test_create_backup_never_overwrites_existing_file(tmp_path, monkeypatch):
    destination = tmp_path / 'backup.sql'
    destination.write_text('keep', encoding='utf-8')
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: pytest.fail('dump should not run'))

    with pytest.raises(FileExistsError):
        create_backup(config(), destination)

    assert destination.read_text(encoding='utf-8') == 'keep'


def test_create_backup_removes_partial_file_when_dump_fails(tmp_path, monkeypatch):
    destination = tmp_path / 'backup.sql'

    def fail(command, *, stdout, **kwargs):
        stdout.write(b'partial')
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(subprocess, 'run', fail)

    with pytest.raises(SystemExit, match='MariaDB no pudo generar'):
        create_backup(config(), destination)

    assert not destination.exists()


def test_create_backup_rejects_empty_dump(tmp_path, monkeypatch):
    destination = tmp_path / 'backup.sql'
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError, match='respaldo vacío'):
        create_backup(config(), destination)

    assert not destination.exists()


def test_create_backup_requires_mariadb_url(tmp_path):
    with pytest.raises(SystemExit, match='DATABASE_URL MariaDB'):
        create_backup(SimpleNamespace(database_url='sqlite:///old.sqlite3'), tmp_path / 'backup.sql')


def test_create_backup_rejects_invalid_port_without_creating_a_file(tmp_path):
    destination = tmp_path / 'backup.sql'
    invalid = SimpleNamespace(database_url='mariadb+mariadbconnector://gianna:secret@db.example.test:invalid/gianna')

    with pytest.raises(SystemExit, match='puerto inválido'):
        create_backup(invalid, destination)

    assert not destination.exists()
