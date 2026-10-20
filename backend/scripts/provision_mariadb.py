#!/usr/bin/env python3
"""Provision isolated local Gianna schemas from an authorized MariaDB bootstrap URL."""
from pathlib import Path
import argparse
import secrets
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import dotenv_values
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from scripts.simplify_env import migrate as update_backend_env, prepare as validate_backend_env


DATABASES = ('gianna_invest', 'gianna_invest_human_test')
APP_USER = 'gianna_invest_app'
PRIVILEGES = 'SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bootstrap-env', required=True, help='Env autorizado con la URL de MariaDB de referencia')
    parser.add_argument('--backend-env', default=str(Path(__file__).resolve().parents[1] / '.env'))
    parser.add_argument('--container-host', default='host.docker.internal')
    args = parser.parse_args()

    bootstrap_env = Path(args.bootstrap_env).resolve()
    backend_env = Path(args.backend_env).resolve()
    if not bootstrap_env.is_file() or not backend_env.is_file():
        raise SystemExit('No se encontraron ambos archivos de configuración; no se hicieron cambios.')
    raw_url = dotenv_values(bootstrap_env).get('DATABASE_URL')
    if not raw_url:
        raise SystemExit('El archivo de referencia no contiene DATABASE_URL.')
    try:
        bootstrap = make_url(raw_url)
    except Exception:
        raise SystemExit('La URL de referencia no tiene un formato válido; no se imprimió.') from None
    if bootstrap.drivername != 'mariadb+mariadbconnector' or not bootstrap.username or not bootstrap.password:
        raise SystemExit('La URL debe identificar una cuenta MariaDB con permisos de aprovisionamiento.')

    host = bootstrap.host or ''
    container_host = args.container_host if host.lower() in {'localhost', '127.0.0.1', '::1'} else host
    bootstrap_connection = bootstrap.set(host=container_host, database=None)
    password = secrets.token_hex(32)
    urls = {
        'DATABASE_URL': bootstrap_connection.set(username=APP_USER, password=password,
                                                   database=DATABASES[0]).render_as_string(hide_password=False),
        'DATABASE_URL_HUMAN_TEST': bootstrap_connection.set(username=APP_USER, password=password,
                                                             database=DATABASES[1]).render_as_string(hide_password=False),
    }
    try:
        validate_backend_env(backend_env.read_bytes(), urls)
    except Exception:
        raise SystemExit('El .env de Gianna necesita revisión antes de aprovisionar MariaDB; no se modificó.') from None
    engine = create_engine(bootstrap_connection, pool_pre_ping=True, connect_args={'connect_timeout': 10})
    try:
        with engine.begin() as connection:
            existing_databases = connection.exec_driver_sql(
                'SELECT schema_name FROM information_schema.schemata WHERE schema_name IN (?,?)', DATABASES
            ).fetchall()
            existing_users = connection.exec_driver_sql(
                'SELECT User FROM mysql.user WHERE User=?', (APP_USER,)
            ).fetchall()
            if existing_databases or existing_users:
                raise SystemExit('Ya existe un esquema o usuario Gianna; no se modificó nada.')
            for database in DATABASES:
                connection.exec_driver_sql(
                    f'CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci'
                )
            connection.exec_driver_sql(
                f"CREATE USER '{APP_USER}'@'%' IDENTIFIED BY '{password}'"
            )
            for database in DATABASES:
                connection.exec_driver_sql(
                    f'GRANT {PRIVILEGES} ON `{database}`.* TO \'{APP_USER}\'@\'%\''
                )
        update_backend_env(backend_env, apply=True, replacements=urls)
    except SystemExit:
        raise
    except Exception:
        raise SystemExit('No se pudo completar la preparación de MariaDB. No se imprimieron credenciales.') from None
    finally:
        engine.dispose()

    print('Esquemas exclusivos de Gianna creados y usuario restringido configurado.')
    print(f'URLs guardadas en {backend_env.name} con respaldo automático; credenciales omitidas.')
    print('El esquema buzon-ciudadano y sus tablas no fueron modificados.')


if __name__ == '__main__':
    main()
