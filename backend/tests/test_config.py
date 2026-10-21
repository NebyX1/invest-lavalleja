"""Configuration, compatibility and secret-preserving migration; no external calls."""
from dataclasses import asdict, replace
from io import StringIO
import json
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import MagicMock

from cryptography.fernet import Fernet
from dotenv import dotenv_values
import pytest

from gianna import create_app
from gianna.config import BACKEND_ROOT, Config
from gianna.web import smtp_sender
from scripts import provision_mariadb
from scripts.simplify_env import FIELDS, migrate, prepare, quote


@pytest.fixture
def env():
    return {'SECRET_KEY': 'test-session-secret-not-a-real-key-' * 2,
            'ENCRYPTION_KEY': Fernet.generate_key().decode(),
            'FLASK_ENV': 'production',
            'DATABASE_URL': 'mariadb+mariadbconnector://gianna:secret@db.example.test:3306/gianna_test',
            'CORS_ORIGINS': 'https://portal.example.test,https://api.example.test'}


def load(env, tmp_path, **overrides):
    return Config.from_env({'data_dir': tmp_path, 'worker_enabled': False, **overrides}, environ=env)


def test_minimal_production_uses_internal_defaults(env, tmp_path):
    cfg = load(env, tmp_path)
    assert cfg.production and cfg.proxy_hops == 1
    assert set(cfg.trusted_hosts) == {'portal.example.test', 'api.example.test', 'localhost', '127.0.0.1'}
    assert (cfg.embedding_backend, cfg.embedding_threads, cfg.embedding_batch_size) == ('openvino', 2, 8)
    assert (cfg.max_concurrent_chat, cfg.max_upload_mb, cfg.max_records) == (3, 12, 10000)
    assert cfg.ollama_url == 'https://ollama.com'


@pytest.mark.parametrize('profile', ['development', 'testing'])
def test_local_profiles_do_not_trust_forwarded_headers(env, tmp_path, profile):
    env['FLASK_ENV'] = profile
    del env['CORS_ORIGINS']
    cfg = load(env, tmp_path)
    assert not cfg.production and cfg.proxy_hops == 0
    assert set(cfg.trusted_hosts) == {'localhost', '127.0.0.1'}
    assert 'http://127.0.0.1:4321' in cfg.public_origins


@pytest.mark.parametrize('origin', ['*', 'https://*.example.test', 'https://api.example.test/path',
    'http://api.example.test', 'https://user:password@api.example.test',
    'https://api.example.test:wrong', 'https://api.example.test?bad=1', ''])
def test_production_cors_stays_strict(env, tmp_path, origin):
    env['CORS_ORIGINS'] = origin
    with pytest.raises(ValueError):
        load(env, tmp_path)


def test_missing_secrets_fail_closed(env, tmp_path):
    for key in ('SECRET_KEY', 'ENCRYPTION_KEY'):
        with pytest.raises((ValueError, TypeError)):
            load({**env, key: ''}, tmp_path)


def test_production_requires_mariadb_and_rejects_sqlite(env, tmp_path):
    with pytest.raises(ValueError, match='DATABASE_URL'):
        load({**env, 'DATABASE_URL': ''}, tmp_path)
    with pytest.raises(ValueError, match='SQLite'):
        load({**env, 'DATABASE_URL': 'sqlite:///temporary.db'}, tmp_path)


def test_unknown_profile_does_not_accidentally_disable_https(env, tmp_path):
    with pytest.raises(ValueError, match='FLASK_ENV'):
        load({**env, 'FLASK_ENV': 'prodution'}, tmp_path)


def test_legacy_names_remain_compatible(env, tmp_path):
    canonical = {**env, 'OLLAMA_HOST': 'https://ollama.example.test', 'MAIL_SERVER': 'mail.example.test',
        'MAIL_PORT': '465', 'MAIL_USE_TLS': 'False', 'MAIL_USE_SSL': 'True',
        'MAIL_USERNAME': 'test-user', 'MAIL_PASSWORD': 'test-password', 'MAIL_DEFAULT_SENDER': 'test@example.test'}
    legacy = {key: value for key, value in env.items() if key not in ('FLASK_ENV', 'CORS_ORIGINS')}
    legacy.update(APP_ENV='production', PUBLIC_ORIGINS=env['CORS_ORIGINS'],
        OLLAMA_BASE_URL=canonical['OLLAMA_HOST'], SMTP_HOST=canonical['MAIL_SERVER'], SMTP_PORT='465',
        SMTP_MODE='ssl', SMTP_USERNAME='test-user', SMTP_PASSWORD='test-password', SMTP_FROM='test@example.test')
    assert asdict(load(canonical, tmp_path)) == asdict(load(legacy, tmp_path))


def test_canonical_names_take_precedence_including_empty_values(env, tmp_path):
    cfg = load({**env, 'APP_ENV': 'development', 'PUBLIC_ORIGINS': 'http://bad.test',
        'MAIL_PASSWORD': '', 'SMTP_PASSWORD': 'old-secret', 'OLLAMA_HOST': 'https://ollama.com',
        'OLLAMA_BASE_URL': 'http://old.test'}, tmp_path)
    assert cfg.production and cfg.smtp_password == '' and cfg.ollama_url == 'https://ollama.com'


@pytest.mark.parametrize('origin', ['http://ollama.example.test', 'https://user:pass@ollama.test',
    'https://ollama.test/path', 'https://ollama.test?key=x', 'not-an-origin'])
def test_invalid_provider_settings_fail_without_echoing_values(env, tmp_path, origin):
    with pytest.raises(ValueError) as exc:
        load({**env, 'OLLAMA_HOST': origin}, tmp_path)
    assert origin not in str(exc.value)


@pytest.mark.parametrize('tls,ssl,expected,port', [('True', 'False', 'starttls', 587),
    ('False', 'True', 'ssl', 465), ('False', 'False', 'plain', 587)])
def test_mail_flags_follow_boilerplate_names(env, tmp_path, tls, ssl, expected, port):
    cfg = load({**env, 'FLASK_ENV': 'development', 'MAIL_USE_TLS': tls, 'MAIL_USE_SSL': ssl}, tmp_path)
    assert cfg.smtp_mode == expected and cfg.smtp_port == port


def test_conflicting_or_insecure_mail_flags_are_rejected(env, tmp_path):
    for values in ({'MAIL_USE_TLS': 'True', 'MAIL_USE_SSL': 'True'},
                   {'MAIL_SERVER': 'mail.example.test', 'MAIL_USE_TLS': 'False', 'MAIL_USE_SSL': 'False'},
                   {'MAIL_USE_SSL': 'maybe'}, {'MAIL_PORT': '0'}):
        with pytest.raises(ValueError):
            load({**env, **values}, tmp_path)


@pytest.mark.parametrize('mode', ['ssl', 'starttls', 'plain'])
def test_mail_transport_matches_flags_without_sending_real_mail(env, tmp_path, monkeypatch, mode):
    secure, regular = MagicMock(), MagicMock()
    monkeypatch.setattr('gianna.web.smtplib.SMTP_SSL', secure)
    monkeypatch.setattr('gianna.web.smtplib.SMTP', regular)
    cfg = load({**env, 'FLASK_ENV': 'development'}, tmp_path,
        smtp_mode=mode, smtp_host='mail.example.test', smtp_from='test@example.test')
    smtp_sender(cfg)('recipient@example.test', '123456')
    chosen = secure if mode == 'ssl' else regular
    other = regular if mode == 'ssl' else secure
    assert chosen.call_count == 1 and other.call_count == 0
    client = chosen.return_value.__enter__.return_value
    assert client.starttls.call_count == (1 if mode == 'starttls' else 0)
    assert client.send_message.call_count == 1


def test_secrets_are_not_in_config_repr(env, tmp_path):
    cfg = load({**env, 'DATABASE_URL': 'mariadb+mariadbconnector://gianna:db-password-not-in-repr@db.example.test:3306/gianna_test',
        'OLLAMA_API_KEY': 'private-ollama-token', 'MAIL_PASSWORD': 'private-mail-password'}, tmp_path)
    for secret in (cfg.secret_key, cfg.encryption_key, cfg.ollama_api_key, cfg.smtp_password, 'db-password-not-in-repr'):
        assert secret not in repr(cfg)


def test_sqlite_url_is_only_available_to_test_profile(env, tmp_path):
    cfg = load({**env, 'FLASK_ENV': 'testing', 'DATABASE_URL': ''}, tmp_path)
    assert cfg.database_target == cfg.db_path


def test_development_requires_mariadb_and_rejects_sqlite(env, tmp_path):
    with pytest.raises(ValueError, match='DATABASE_URL'):
        load({**env, 'FLASK_ENV': 'development', 'DATABASE_URL': ''}, tmp_path)
    with pytest.raises(ValueError, match='SQLite'):
        load({**env, 'FLASK_ENV': 'development', 'DATABASE_URL': 'sqlite:///local.db'}, tmp_path)


def test_minimal_config_preserves_http_security(env, tmp_path):
    cfg = replace(load({**env, 'FLASK_ENV': 'testing', 'DATABASE_URL': ''}, tmp_path), production=True)
    app = create_app(cfg)
    client = app.test_client()
    response = client.get('/admin/login', base_url='https://api.example.test')
    assert response.status_code == 200
    assert 'Secure' in response.headers['Set-Cookie'] and 'SameSite=Strict' in response.headers['Set-Cookie']
    assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']
    assert client.get('/admin/login', base_url='https://evil.example.test').status_code == 400
    assert client.get('/api/config', base_url='https://evil.example.test',
        headers={'Origin': 'https://portal.example.test'}).status_code == 400
    assert client.get('/admin/login', base_url='http://api.example.test').status_code == 400
    assert client.get('/admin/bases', base_url='https://api.example.test').status_code == 302
    bad_origin = client.get('/api/captcha', base_url='https://api.example.test', headers={'Origin': 'https://evil.example.test'})
    assert bad_origin.status_code == 403
    allowed = client.get('/api/captcha', base_url='https://api.example.test', headers={'Origin': 'https://portal.example.test'})
    assert allowed.status_code == 200 and allowed.headers['Access-Control-Allow-Origin'] == 'https://portal.example.test'
    assert client.post('/admin/login', base_url='https://api.example.test', data={}).status_code == 403


def test_local_profile_ignores_forwarded_https_and_host(env, tmp_path):
    cfg = load({**env, 'FLASK_ENV': 'testing', 'DATABASE_URL': '', 'CORS_ORIGINS': 'http://localhost'}, tmp_path)
    client = create_app(cfg).test_client()
    response = client.get('/admin/login', headers={'X-Forwarded-Proto': 'https', 'X-Forwarded-Host': 'evil.example.test'})
    assert response.status_code == 200 and 'Secure;' not in response.headers['Set-Cookie']
    assert 'Strict-Transport-Security' not in response.headers


def legacy_text(env):
    return '\n'.join(key + '=' + quote(value) for key, value in {
        'APP_ENV': 'production', 'SECRET_KEY': env['SECRET_KEY'], 'ENCRYPTION_KEY': env['ENCRYPTION_KEY'],
        'DATABASE_URL': env['DATABASE_URL'], 'DATABASE_URL_HUMAN_TEST': '',
        'PUBLIC_ORIGINS': env['CORS_ORIGINS'], 'OLLAMA_API_KEY': 'test-ollama-token',
        'OLLAMA_MODEL': 'deepseek-v4.1-flash:1017', 'OLLAMA_BASE_URL': 'https://ollama.com',
        'SMTP_HOST': 'mail.example.test', 'SMTP_MODE': 'ssl', 'SMTP_PORT': '465',
        'SMTP_PASSWORD': "fake p@ss # $literal 'quoted' \\windows", 'SMTP_USERNAME': 'test',
        'SMTP_FROM': 'test@example.test', 'QDRANT_URL': 'http://unused.test', 'E5_REVISION': 'unused',
    }.items()) + '\n'


def test_migration_keeps_keys_model_mail_and_effective_settings(env, tmp_path):
    path = tmp_path / '.env'
    original = legacy_text(env).encode()
    path.write_bytes(original)
    plan = migrate(path)
    assert not plan['applied'] and path.read_bytes() == original
    result = migrate(path, apply=True)
    assert result['variables_after'] == 15 and result['effective_config_unchanged']
    assert (tmp_path / result['backup']).read_bytes() == original
    after = dict(dotenv_values(path))
    assert set(after) == set(FIELDS)
    assert after['SECRET_KEY'] == env['SECRET_KEY'] and after['ENCRYPTION_KEY'] == env['ENCRYPTION_KEY']
    assert after['OLLAMA_MODEL'] == 'deepseek-v4.1-flash:1017'
    assert after['MAIL_PASSWORD'] == dotenv_values(stream=StringIO(original.decode()))['SMTP_PASSWORD']
    assert after['OLLAMA_API_KEY'] not in json.dumps(result)
    assert 'QDRANT' not in path.read_text() and 'E5_' not in path.read_text()


@pytest.mark.parametrize('extra', ['MAX_UPLOAD_MB=20', 'UNRECOGNIZED=keep-me', 'OMP_NUM_THREADS=7',
    'SECRET_KEY=duplicate-value', 'THIS IS NOT AN ENV ASSIGNMENT'])
def test_migration_does_not_silently_discard_custom_settings(env, tmp_path, extra):
    path = tmp_path / '.env'
    original = (legacy_text(env) + extra + '\n').encode()
    path.write_bytes(original)
    with pytest.raises(ValueError):
        migrate(path, apply=True)
    assert path.read_bytes() == original and len(list(tmp_path.iterdir())) == 1


def test_migration_roundtrip_is_idempotent(env):
    compact, _, _ = prepare(legacy_text(env).encode())
    again, old_count, new_count = prepare(compact)
    assert compact == again and old_count == new_count == 15


def test_migration_removes_secondary_url_without_changing_primary_database(env):
    secondary = 'mariadb+mariadbconnector://test:unused@db.example.test:3306/other_schema'
    original = legacy_text(env).replace("DATABASE_URL_HUMAN_TEST=''", 'DATABASE_URL_HUMAN_TEST=' + quote(secondary))
    compact, _, _ = prepare(original.encode())
    values = dotenv_values(stream=StringIO(compact.decode()))
    assert values['DATABASE_URL'] == env['DATABASE_URL']
    assert 'DATABASE_URL_HUMAN_TEST' not in values
    assert values['SECRET_KEY'] == env['SECRET_KEY']
    assert values['ENCRYPTION_KEY'] == env['ENCRYPTION_KEY']


def test_provisioning_creates_one_schema_and_saves_one_database_url(env, tmp_path, monkeypatch):
    bootstrap = tmp_path / 'bootstrap.env'
    bootstrap.write_text('DATABASE_URL=mariadb+mariadbconnector://bootstrap:fake@localhost:3306/reference\n')
    backend = tmp_path / '.env'
    backend.write_text(legacy_text(env))
    connection = MagicMock()
    connection.exec_driver_sql.return_value.fetchall.return_value = []
    engine = MagicMock()
    engine.begin.return_value.__enter__.return_value = connection
    monkeypatch.setattr(provision_mariadb, 'create_engine', lambda *args, **kwargs: engine)
    monkeypatch.setattr(sys, 'argv', ['provision_mariadb', '--bootstrap-env', str(bootstrap), '--backend-env', str(backend)])
    provision_mariadb.main()
    statements = [call.args[0] for call in connection.exec_driver_sql.call_args_list]
    creates = [sql for sql in statements if sql.startswith('CREATE DATABASE')]
    grants = [sql for sql in statements if sql.startswith('GRANT')]
    assert len(creates) == len(grants) == 1
    assert '`gianna_invest`' in creates[0] and '`gianna_invest`.*' in grants[0]
    values = dotenv_values(backend)
    assert set(values) == set(FIELDS)
    assert values['DATABASE_URL'].endswith('/gianna_invest')
    assert 'DATABASE_URL_HUMAN_TEST' not in values


def test_setup_generates_minimal_local_env_and_refuses_to_rotate(tmp_path):
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    shutil.copyfile(BACKEND_ROOT / 'scripts/setup_env.py', scripts / 'setup_env.py')
    shutil.copyfile(BACKEND_ROOT / '.env.example', tmp_path / '.env.example')
    result = subprocess.run([sys.executable, str(scripts / 'setup_env.py'), '--local'], capture_output=True, text=True)
    assert result.returncode == 0
    path = tmp_path / '.env'
    original = path.read_bytes()
    values = dotenv_values(path)
    assert set(values) == set(FIELDS) and values['FLASK_ENV'] == 'development'
    assert len(values['SECRET_KEY']) >= 32 and Fernet(values['ENCRYPTION_KEY'].encode())
    again = subprocess.run([sys.executable, str(scripts / 'setup_env.py')], capture_output=True, text=True)
    assert again.returncode != 0 and path.read_bytes() == original
    assert values['SECRET_KEY'] not in result.stdout + again.stdout


def test_dotenv_location_is_independent_of_working_directory(env, tmp_path, monkeypatch):
    loaded = []
    monkeypatch.setattr('dotenv.load_dotenv', lambda path: loaded.append(Path(path)))
    monkeypatch.chdir(tmp_path)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    Config.from_env({'data_dir': tmp_path})
    assert loaded == [BACKEND_ROOT / '.env']
