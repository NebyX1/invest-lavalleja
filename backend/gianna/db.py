"""Short SQLite transactions; no shared connection and no network work inside a transaction."""
from contextlib import contextmanager, closing
from pathlib import Path
import json
import sqlite3
import time
import uuid


def uid():
    return uuid.uuid4().hex


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


class Database:
    def __init__(self, path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self):
        db=sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA busy_timeout=15000')
        return db

    @contextmanager
    def tx(self, immediate=False):
        db=self.connect()
        try:
            db.execute('BEGIN IMMEDIATE' if immediate else 'BEGIN')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def migrate(self):
        with closing(self.connect()) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS schema_versions(version INTEGER PRIMARY KEY,applied_at REAL NOT NULL)')
            current=db.execute('SELECT COALESCE(MAX(version),0) FROM schema_versions').fetchone()[0]
            for path in sorted((Path(__file__).parent/'migrations').glob('*.sql')):
                version=int(path.stem)
                if version > current:
                    sql=path.read_text(encoding='utf-8')
                    db.executescript(f'BEGIN IMMEDIATE;\n{sql}\nINSERT INTO schema_versions VALUES({version},{time.time()});\nCOMMIT;')
        try: self.path.chmod(0o600)
        except OSError: pass

    def one(self, sql, args=()):
        with self.tx() as db:
            r=db.execute(sql,args).fetchone()
            return dict(r) if r is not None else None

    def all(self, sql, args=()):
        with self.tx() as db:
            return [dict(r) for r in db.execute(sql,args).fetchall()]

    def execute(self, sql, args=()):
        with self.tx(immediate=True) as db:
            return db.execute(sql,args).rowcount

    def setting(self, key, default=None):
        row=self.one('SELECT value FROM settings WHERE key=?',(key,))
        return json.loads(row['value']) if row else default

    def audit(self, actor, action, target=None, details=None):
        self.execute('INSERT INTO audit(at,user_id,action,target,details_json) VALUES(?,?,?,?,?)',
                     (time.time(),actor,action,target,dumps(details or {})))

    def backup(self, path):
        source=self.connect()
        dest=sqlite3.connect(path)
        try: source.backup(dest)
        finally: dest.close(); source.close()
