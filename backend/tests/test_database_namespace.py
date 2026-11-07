"""Never initialize a different application's MariaDB or guess missing history."""
import pytest

from gianna.db import Database,uid
from gianna.errors import DomainError
from test_mariadb_import import maria_server  # shared opt-in disposable server


@pytest.mark.parametrize('tables,code',[(('foreign_application',),'database_namespace_conflict'),
                                      (('bases','versions','active_knowledge'),'database_history_missing')])
def test_existing_namespace_without_history_is_inspected_before_writes(maria_server,tables,code):
    url,server=maria_server
    name='test_namespace_'+uid()
    server.execute(f'CREATE DATABASE `{name}` CHARACTER SET utf8mb4')
    db=Database(url.set(database=name).render_as_string(hide_password=False))
    try:
        for table in tables:db.execute('CREATE TABLE '+table+'(id INTEGER PRIMARY KEY)')
        with pytest.raises(DomainError) as failed:db.migrate()
        assert failed.value.code==code
        actual=db.all('SELECT TABLE_NAME AS name FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()')
        assert {row['name'] for row in actual}==set(tables)
    finally:
        db._engine.dispose()
        server.execute(f'DROP DATABASE `{name}`')
