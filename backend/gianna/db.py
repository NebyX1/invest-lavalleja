"""Database access for MariaDB, with SQLite retained only for tests/imports."""
from contextlib import closing
from pathlib import Path
import hashlib
import json
import sqlite3
import time
import uuid


class IntegrityError(Exception):
    """A database uniqueness or foreign-key constraint was violated."""


class Row(dict):
    """Mapping row that also preserves the positional access used by old queries."""
    def __init__(self, columns, values):
        super().__init__(zip(columns, values))
        self._values = tuple(values)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


def uid():
    return uuid.uuid4().hex


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


class _MariaResult:
    def __init__(self, cursor):
        self.cursor = cursor
        self.columns = tuple(item[0] for item in (cursor.description or ()))
        self.rowcount = cursor.rowcount
        if not self.columns:
            cursor.close()
            self.cursor = None

    def fetchone(self):
        if self.cursor is None:
            return None
        try:
            values = self.cursor.fetchone()
        finally:
            self.cursor.close()
            self.cursor = None
        return Row(self.columns, values) if values is not None else None

    def fetchall(self):
        if self.cursor is None:
            return []
        try:
            return [Row(self.columns, values) for values in self.cursor.fetchall()]
        finally:
            self.cursor.close()
            self.cursor = None


class _MariaConnection:
    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, args=()):
        sql = sql.replace('INSERT OR IGNORE INTO', 'INSERT IGNORE INTO')
        sql = sql.replace(
            'ON CONFLICT(`key`,bucket) DO UPDATE SET count=count+1',
            'ON DUPLICATE KEY UPDATE count=count+1',
        )
        sql = sql.replace(
            'ON CONFLICT(base_id,source_key) DO UPDATE SET content_json=excluded.content_json',
            'ON DUPLICATE KEY UPDATE content_json=VALUES(content_json)',
        )
        sql = sql.replace(
            'ON CONFLICT(`key`) DO UPDATE SET value=excluded.value',
            'ON DUPLICATE KEY UPDATE value=VALUES(value)',
        )
        cursor = self.raw.cursor()
        try:
            cursor.execute(sql, tuple(args))
        except Exception as exc:
            cursor.close()
            try:
                import mariadb
                if isinstance(exc, mariadb.IntegrityError):
                    raise IntegrityError(str(exc)) from exc
            except ImportError:
                pass
            raise
        return _MariaResult(cursor)

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()


class _SQLiteConnection:
    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, args=()):
        try:
            return self.raw.execute(sql, args)
        except sqlite3.IntegrityError as exc:
            raise IntegrityError(str(exc)) from exc

    def executescript(self, sql):
        try:
            return self.raw.executescript(sql)
        except sqlite3.IntegrityError as exc:
            raise IntegrityError(str(exc)) from exc

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()


class Database:
    def __init__(self, target):
        self.target = str(target)
        self.is_mariadb = self.target.startswith('mariadb+')
        self.path = None if self.is_mariadb else Path(self.target.removeprefix('sqlite:///'))
        self._engine = None
        if self.is_mariadb:
            from sqlalchemy import create_engine
            self._engine = create_engine(
                self.target,
                pool_pre_ping=True,
                pool_recycle=1800,
                pool_size=10,
                max_overflow=10,
                pool_timeout=30,
                connect_args={'connect_timeout': 10},
            )
            db_name = self.target.rsplit('/', 1)[-1].split('?', 1)[0]
            self._lock_name = 'gianna:' + hashlib.sha256(db_name.encode()).hexdigest()[:32]
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self):
        if self.is_mariadb:
            return _MariaConnection(self._engine.raw_connection())
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA busy_timeout=15000')
        return _SQLiteConnection(db)

    @staticmethod
    def _execute_statements(db, source):
        for statement in source.split(';'):
            if statement.strip():
                db.execute(statement)

    def migrate(self):
        migrations = Path(__file__).parent / ('migrations_mariadb' if self.is_mariadb else 'migrations')
        with closing(self.connect()) as db:
            if self.is_mariadb:
                db.execute('CREATE TABLE IF NOT EXISTS schema_versions(version INTEGER PRIMARY KEY,applied_at DOUBLE NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci')
                db.commit()
            else:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('CREATE TABLE IF NOT EXISTS schema_versions(version INTEGER PRIMARY KEY,applied_at REAL NOT NULL)')
            current = db.execute('SELECT COALESCE(MAX(version),0) FROM schema_versions').fetchone()[0]
            for path in sorted(migrations.glob('*.sql')):
                version = int(path.stem)
                if version <= current:
                    continue
                source = path.read_text(encoding='utf-8')
                if self.is_mariadb:
                    self._execute_statements(db, source)
                    db.execute('INSERT INTO schema_versions(version,applied_at) VALUES(?,?)', (version, time.time()))
                    db.commit()
                else:
                    db.executescript(f'BEGIN IMMEDIATE;\n{source}\nINSERT INTO schema_versions VALUES({version},{time.time()});\nCOMMIT;')
        if self.path:
            try:
                self.path.chmod(0o600)
            except OSError:
                pass

    def one(self, sql, args=()):
        with self.tx() as db:
            row = db.execute(sql, args).fetchone()
            return dict(row) if row is not None else None

    def all(self, sql, args=()):
        with self.tx() as db:
            return [dict(row) for row in db.execute(sql, args).fetchall()]

    def execute(self, sql, args=()):
        with self.tx(immediate=True) as db:
            return db.execute(sql, args).rowcount

    def setting(self, key, default=None):
        row = self.one('SELECT value FROM settings WHERE `key`=?', (key,))
        return json.loads(row['value']) if row else default

    def audit(self, actor, action, target=None, details=None):
        self.execute('INSERT INTO audit(at,user_id,action,target,details_json) VALUES(?,?,?,?,?)',
                     (time.time(), actor, action, target, dumps(details or {})))

    def size_mib(self):
        if not self.is_mariadb:
            return round(self.path.stat().st_size / 1024**2, 2) if self.path.exists() else 0.0
        row = self.one('SELECT COALESCE(SUM(data_length+index_length),0) AS bytes FROM information_schema.tables WHERE table_schema=DATABASE()')
        return round(row['bytes'] / 1024**2, 2)

    from contextlib import contextmanager

    @contextmanager
    def tx(self, immediate=False):
        db = self.connect()
        acquired = False
        try:
            if self.is_mariadb:
                if immediate:
                    acquired = db.execute('SELECT GET_LOCK(?,15)', (self._lock_name,)).fetchone()[0] == 1
                    if not acquired:
                        raise TimeoutError('No se pudo obtener el bloqueo de escritura de Gianna.')
                    db.commit()
                db.execute('START TRANSACTION')
            else:
                db.execute('BEGIN IMMEDIATE' if immediate else 'BEGIN')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            if acquired:
                try:
                    db.execute('SELECT RELEASE_LOCK(?)', (self._lock_name,)).fetchone()
                    db.commit()
                except Exception:
                    db.rollback()
            db.close()
