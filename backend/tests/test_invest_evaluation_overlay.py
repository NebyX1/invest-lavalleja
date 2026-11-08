"""Reusing an evaluation index must not silently change its retrieval inputs."""
import json
from types import SimpleNamespace

import pytest

from gianna.corpus import DocumentaryContent, InformationView, Record, information_source_hash
from scripts.evaluate_invest_prompts import ReadOnlyDatabase


def pair():
    old=Record(id='fact',title='Fact',text='Indexed descriptive statement.',audience='public')
    old.information_view=InformationView(text=old.text,kind='descriptive',source_sha256=information_source_hash(old))
    updated=old.model_copy(deep=True)
    updated.documentary=DocumentaryContent(text='Unabridged detail from the same source.',conditions=['A material condition.'])
    updated.information_view=InformationView(text=old.text,kind='descriptive',source_sha256=information_source_hash(updated))
    return old,updated


def adapter(old,new):
    row={'record_key':old.id,'content_json':old.model_dump_json()}
    db=ReadOnlyDatabase(SimpleNamespace(one=lambda *a:dict(row),all=lambda *a:[dict(row)]),{new.id:new})
    return db,row


def test_documentary_overlay_keeps_the_indexed_content_and_original_row_unchanged():
    old,new=pair();db,row=adapter(old,new)
    result=db.one('SELECT record_key,content_json FROM version_records')
    assert json.loads(result['content_json'])['documentary']['text']==new.documentary.text
    assert 'documentary' not in json.loads(row['content_json'])
    assert db.applied=={'fact'}
    assert Record.model_validate_json(result['content_json']).information_view is not None


def test_changed_indexed_text_is_rejected_before_a_provider_call():
    old,new=pair();new.text='Different indexed content.'
    db,_=adapter(old,new)
    with pytest.raises(ValueError,match='indexed'):
        db.all('SELECT record_key,content_json FROM version_records')


def test_internal_records_and_writes_are_rejected():
    old,new=pair();old.audience='internal'
    db,_=adapter(old,new)
    with pytest.raises(ValueError,match='public'):
        db.one('SELECT record_key,content_json FROM version_records')
    with pytest.raises(ValueError,match='Read-only'):
        db.one('UPDATE records SET content_json=?',('{}',))
