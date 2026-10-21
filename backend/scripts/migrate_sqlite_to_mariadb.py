#!/usr/bin/env python3
"""One-time, guarded import of a stopped Gianna SQLite database into MariaDB."""
from pathlib import Path
import argparse
import os
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gianna.db import Database


TABLES = (
    'users', 'auth_challenges', 'admin_sessions', 'recovery_codes', 'rate_limits', 'settings',
    'bases', 'records', 'sources', 'versions', 'version_records', 'version_sources', 'chunks',
    'active_knowledge', 'jobs', 'audit', 'chat_sessions', 'queries', 'embedding_cache',
    'captcha_challenges',
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', help='Archivo SQLite existente de Gianna')
    parser.add_argument('--confirm-api-stopped', action='store_true')
    parser.add_argument('--confirm', action='store_true')
    args = parser.parse_args()
    if not args.confirm or not args.confirm_api_stopped:
        raise SystemExit('Detené la API y volvé a ejecutar con --confirm-api-stopped --confirm.')

    source = Path(args.source).resolve()
    if not source.is_file():
        raise SystemExit('No se encontró el archivo SQLite indicado.')
    target = os.environ.get('DATABASE_URL', '').strip()
    if not target.startswith('mariadb+mariadbconnector://'):
        raise SystemExit('DATABASE_URL debe apuntar a MariaDB. No se imprimió su valor.')

    with sqlite3.connect(f'file:{source.as_posix()}?mode=ro', uri=True) as sqlite_db:
        if sqlite_db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise SystemExit('La base SQLite no supera integrity_check.')
        names = {row[0] for row in sqlite_db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if set(TABLES) - names:
            raise SystemExit('La base fuente no contiene todas las tablas esperadas de Gianna.')
        counts = {table: sqlite_db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in TABLES}

        destination = Database(target)
        destination.migrate()
        with destination.tx(immediate=True) as maria:
            for table in TABLES:
                rows = maria.execute(f'SELECT COUNT(*) FROM `{table}`').fetchone()[0]
                allowed_seed = table == 'active_knowledge' and rows == 1 and maria.execute(
                    'SELECT version_id FROM active_knowledge WHERE singleton=1').fetchone()[0] is None
                if rows and not allowed_seed:
                    raise SystemExit('El destino MariaDB ya contiene datos; no se modificó.')

            # The MariaDB schema seeds its singleton row; replace that empty seed with the source row.
            maria.execute('DELETE FROM active_knowledge')
            for table in TABLES:
                source_rows = sqlite_db.execute(f'SELECT * FROM "{table}"')
                columns = tuple(item[0] for item in source_rows.description)
                if not counts[table]:
                    continue
                quoted = ','.join(f'`{column}`' for column in columns)
                placeholders = ','.join('?' for _ in columns)
                statement = f'INSERT INTO `{table}` ({quoted}) VALUES ({placeholders})'
                for row in source_rows:
                    maria.execute(statement, row)

        for table, expected in counts.items():
            actual = destination.one(f'SELECT COUNT(*) AS n FROM `{table}`')['n']
            if actual != expected:
                raise SystemExit(f'La verificación de importación falló en la tabla {table}.')
        print(f'Migración verificada: {sum(counts.values())} filas en {len(TABLES)} tablas.')
        print('No se borró ni se modificó el SQLite de origen; conserválo como respaldo hasta validar la aplicación.')


if __name__ == '__main__':
    main()
