"""The evaluation overlay binds presentation only; it cannot publish or write SQL."""
import json
import sys

import pytest

from gianna.corpus import InformationView, Record, information_source_hash
from scripts.evaluate_information_style import ReadOnlyDatabase, main


class SourceDatabase:
    def __init__(self, row):
        self.row = row
        self.calls = []

    def one(self, sql, args=()):
        self.calls.append((sql, args))
        return self.row

    def all(self, sql, args=()):
        self.calls.append((sql, args))
        return [self.row]


def test_overlay_preserves_original_fields_and_does_not_mutate_database_row():
    source = Record(id='public', title='Fuente', text='Texto original.',
                    audience='public', conditions=['Alcance original.'])
    row = {'record_key': source.id, 'content_json': source.model_dump_json()}
    original_bytes = row['content_json']
    underlying = SourceDatabase(row)
    view = InformationView(text='Una descripción.', kind='descriptive',
                           source_sha256=information_source_hash(source))
    overlay = ReadOnlyDatabase(underlying, {source.id: view})
    result = json.loads(overlay.one('SELECT record_key,content_json FROM version_records')['content_json'])
    assert result.pop('information_view') == view.model_dump()
    assert result == source.model_dump(mode='json')
    assert row['content_json'] == original_bytes and result['conditions'] == ['Alcance original.']
    assert overlay.applied == {'public'}


def test_overlay_rejects_source_revision_mismatch_instead_of_testing_other_data():
    source = Record(id='public', title='Fuente', text='Texto original.', audience='public')
    view = InformationView(text='Una descripción.', kind='descriptive', source_sha256='0' * 64)
    db = ReadOnlyDatabase(SourceDatabase({'record_key': source.id, 'content_json': source.model_dump_json()}),
                          {source.id: view})
    with pytest.raises(ValueError, match='different source revision'):
        db.all('SELECT record_key,content_json FROM version_records')


def test_overlay_does_not_upgrade_an_internal_record():
    source = Record(id='internal', title='Interno', text='Datos privados.')
    row = {'record_key': source.id, 'content_json': source.model_dump_json()}
    view = InformationView(text='Una descripción.', kind='descriptive',
                           source_sha256=information_source_hash(source))
    db = ReadOnlyDatabase(SourceDatabase(row), {source.id: view})
    assert db.one('SELECT record_key,content_json FROM version_records') == row
    assert db.applied == set()


@pytest.mark.parametrize('sql', ['UPDATE records SET enabled=0', 'DELETE FROM records', 'INSERT INTO records VALUES(1)'])
def test_overlay_rejects_mutation_before_calling_database(sql):
    original = SourceDatabase(None)
    db = ReadOnlyDatabase(original)
    with pytest.raises(ValueError, match='SELECT only'):
        db.one(sql)
    assert original.calls == []


def test_paid_evaluation_is_opt_in_before_reading_configuration(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, 'argv', ['evaluate_information_style', '--output', str(tmp_path / 'results.json')])
    monkeypatch.setattr('scripts.evaluate_information_style.dotenv_values',
                        lambda *_: pytest.fail('No configuration read without opt-in'))
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
