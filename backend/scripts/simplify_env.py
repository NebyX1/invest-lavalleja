#!/usr/bin/env python3
"""Migrate only this backend's .env, with a backup and equivalent effective config."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from io import StringIO
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import dotenv_values
from dotenv.parser import parse_stream
from gianna.config import BACKEND_ROOT, Config

SECTIONS = (
    ('Flask y seguridad', ('FLASK_ENV', 'SECRET_KEY', 'ENCRYPTION_KEY')),
    ('Base MariaDB', ('DATABASE_URL',)),
    ('Portal y API: origenes exactos separados por coma', ('CORS_ORIGINS',)),
    ('Ollama Cloud', ('OLLAMA_HOST', 'OLLAMA_API_KEY', 'OLLAMA_MODEL')),
    ('Correo SMTP', ('MAIL_SERVER', 'MAIL_PORT', 'MAIL_USE_TLS', 'MAIL_USE_SSL',
                      'MAIL_USERNAME', 'MAIL_PASSWORD', 'MAIL_DEFAULT_SENDER')),
)
FIELDS = tuple(key for _, keys in SECTIONS for key in keys)
LEGACY_FIELDS = {
    'APP_ENV', 'DATA_DIR', 'TRUSTED_HOSTS', 'PUBLIC_ORIGINS', 'PROXY_HOPS',
    'OLLAMA_BASE_URL', 'SMTP_HOST', 'SMTP_PORT', 'SMTP_USERNAME', 'SMTP_PASSWORD',
    'SMTP_FROM', 'SMTP_MODE', 'EMBEDDING_BACKEND', 'EMBEDDING_THREADS',
    'EMBEDDING_BATCH_SIZE', 'MAX_CONCURRENT_CHAT', 'WORKER_ENABLED',
    'MAX_UPLOAD_MB', 'MAX_RECORDS', 'QDRANT_URL', 'QDRANT_API_KEY',
    'E5_REVISION', 'E5_MODEL_FILE', 'GIANNA_HUMAN_TEST_MODE',
    'DATABASE_URL_HUMAN_TEST',
}
CPU_DEFAULTS = {'OMP_NUM_THREADS': '2', 'OPENBLAS_NUM_THREADS': '1',
                'MKL_NUM_THREADS': '1', 'TOKENIZERS_PARALLELISM': 'false'}


def quote(value):
    return "'" + str(value).replace('\\', '\\\\').replace("'", "\\'") + "'"


def prepare(original, replacements=None):
    text = original.decode('utf-8-sig')
    bindings = list(parse_stream(StringIO(text)))
    keys = [item.key for item in bindings if item.key is not None]
    if any(item.error for item in bindings) or len(keys) != len(set(keys)):
        raise ValueError('Revisá sintaxis o variables repetidas. No se modificó .env.')
    original_values = dict(dotenv_values(stream=StringIO(text)))
    old = dict(original_values)
    old.update(replacements or {})
    if set(old) - set(FIELDS) - LEGACY_FIELDS - set(CPU_DEFAULTS):
        raise ValueError('Hay variables no reconocidas. Se requiere revisar antes de retirarlas.')
    if any(str(old.get(key, default)).lower() != default for key, default in CPU_DEFAULTS.items()):
        raise ValueError('Hay límites CPU personalizados; no se eliminaron silenciosamente.')
    cfg = Config.from_env(environ=old)
    values = dict(zip(FIELDS, (
        'production' if cfg.production else ('testing' if old.get('FLASK_ENV') == 'testing' else 'development'),
        cfg.secret_key, cfg.encryption_key, old.get('DATABASE_URL', ''), ','.join(cfg.public_origins),
        cfg.ollama_url, cfg.ollama_api_key, cfg.ollama_model,
        cfg.smtp_host, str(cfg.smtp_port), str(cfg.smtp_mode == 'starttls'),
        str(cfg.smtp_mode == 'ssl'), cfg.smtp_username, cfg.smtp_password, cfg.smtp_from,
    )))
    newline = '\r\n' if '\r\n' in text else '\n'
    lines = ['# Configuracion de Gianna Invest. No subir este archivo a Git.']
    for title, section_keys in SECTIONS:
        lines.extend(['', '# ' + title, *(key + '=' + quote(values[key]) for key in section_keys)])
    content = (newline.join(lines) + newline).encode('utf-8')
    actual = dict(dotenv_values(stream=StringIO(content.decode('utf-8'))))
    if actual != values:
        raise ValueError('La serialización alteraría una variable. No se modificó .env.')
    updated = Config.from_env(environ=actual)
    before, after = asdict(cfg), asdict(updated)
    # Order of the allowlist has no effect on host validation.
    before['trusted_hosts'] = set(before['trusted_hosts'])
    after['trusted_hosts'] = set(after['trusted_hosts'])
    differences = [key for key in before if before[key] != after[key]]
    if differences:
        raise ValueError('Se conservaron opciones personalizadas: revisión necesaria en ' + ', '.join(differences))
    return content, len(original_values), len(values)


def migrate(path, apply=False, replacements=None):
    path = Path(path).resolve()
    original = path.read_bytes()
    content, old_count, new_count = prepare(original, replacements)
    report = {'variables_before': old_count, 'variables_after': new_count,
              'effective_config_unchanged': True, 'applied': False}
    if not apply:
        return report
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = path.with_name('.env.before-simplify-' + stamp)
    fd, temp_name = tempfile.mkstemp(prefix='.env.simplifying-', dir=path.parent)
    temporary = Path(temp_name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        shutil.copystat(path, temporary)
        if path.read_bytes() != original:
            raise ValueError('.env cambió durante la revisión. No se sobrescribió.')
        with os.fdopen(os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    report.update(applied=True, backup=backup.name)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Aplicar con respaldo; sin esta opción solo verifica.')
    parser.add_argument('--set-database-url', action='store_true',
                        help='Usar DATABASE_URL del entorno y guardarla con respaldo.')
    args = parser.parse_args()
    replacements = None
    if args.set_database_url:
        replacements = {'DATABASE_URL': os.environ.get('DATABASE_URL', '').strip()}
        if any(not value.startswith('mariadb+mariadbconnector://') for value in replacements.values()):
            raise SystemExit('Se requiere DATABASE_URL MariaDB en el entorno; no se imprimió su valor.')
    try:
        report = migrate(BACKEND_ROOT / '.env', apply=args.apply, replacements=replacements)
    except (ValueError, OSError, UnicodeError):
        raise SystemExit('No se pudo simplificar .env de forma equivalente. No se imprimieron credenciales; conservá el archivo y revisá sus opciones personalizadas.') from None
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
