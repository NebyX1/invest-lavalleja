#!/usr/bin/env python3
"""Create a confidential, consistent logical MariaDB backup for Gianna."""
from pathlib import Path
import argparse
import os
import subprocess
import sys
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gianna.config import Config


def create_backup(cfg, output):
    url = urlsplit(cfg.database_url)
    if url.scheme != 'mariadb+mariadbconnector' or not url.hostname or not url.path.strip('/'):
        raise SystemExit('El respaldo requiere DATABASE_URL MariaDB.')
    try:
        port = url.port or 3306
    except ValueError as exc:
        raise SystemExit('DATABASE_URL tiene un puerto inválido.') from exc
    database = unquote(url.path.strip('/'))
    target = Path(output).resolve()
    if target.exists():
        raise FileExistsError('El destino ya existe; no se sobrescribió.')
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    env = os.environ.copy()
    if url.password is not None:
        env['MYSQL_PWD'] = unquote(url.password)
    command = [
        'mariadb-dump', '--single-transaction', '--quick', '--skip-lock-tables',
        '--hex-blob', '--default-character-set=utf8mb4',
        '--host', url.hostname, '--port', str(port),
        '--user', unquote(url.username or ''), '--databases', database,
    ]
    try:
        with os.fdopen(fd, 'wb') as stream:
            subprocess.run(command, env=env, stdout=stream, stderr=subprocess.PIPE, check=True)
            stream.flush()
            os.fsync(stream.fileno())
        if target.stat().st_size == 0:
            raise RuntimeError('MariaDB produjo un respaldo vacío.')
    except FileNotFoundError:
        target.unlink(missing_ok=True)
        raise SystemExit('No se encontró mariadb-dump en la imagen; instalá el cliente MariaDB.')
    except subprocess.CalledProcessError:
        target.unlink(missing_ok=True)
        raise SystemExit('MariaDB no pudo generar el respaldo; no se conservó un archivo parcial.')
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    target = create_backup(Config.from_env(), args.output)
    print(f'Respaldo MariaDB creado en {target}. Es confidencial y no incluye LanceDB, modelos ni .env.')


if __name__ == '__main__':
    main()
