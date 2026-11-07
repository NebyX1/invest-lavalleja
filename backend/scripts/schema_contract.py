"""Generate/check column names from the authoritative test migrations, in memory.

This development check does not open an installation, read .env or connect to
MariaDB. Production reads the generated JSON, not a secondary SQLite database.
"""
import argparse
import json
from pathlib import Path
import sqlite3

ROOT=Path(__file__).resolve().parents[1]


def contract():
    with sqlite3.connect(':memory:') as connection:
        for migration in sorted((ROOT/'gianna/migrations').glob('*.sql')):
            connection.executescript(migration.read_text(encoding='utf-8'))
        tables=[row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {table:sorted(row[1] for row in connection.execute('PRAGMA table_info('+table+')'))
                for table in tables}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write',action='store_true')
    options=parser.parse_args(argv)
    path=ROOT/'gianna/schema_contract.json'
    result=contract()
    if options.write:
        path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    elif json.loads(path.read_text(encoding='utf-8'))!=result:
        parser.error('El contrato no coincide con las migraciones; regenerá con --write.')
    return 0


if __name__=='__main__':raise SystemExit(main())
