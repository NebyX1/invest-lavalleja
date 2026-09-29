import json
import time
import pytest
from gianna.errors import DomainError
from gianna.services.settings import Settings


def ready(db,knowledge,corpus):
    bid=knowledge.import_corpus(corpus,'Base','actor');knowledge.approve_public(bid,'actor')
    jid,vid=knowledge.enqueue_build(bid,Settings(),'actor')
    db.execute("UPDATE versions SET status='ready',chunk_count=1 WHERE id=?",(vid,))
    db.execute("UPDATE jobs SET status='done' WHERE id=?",(jid,))
    return bid,jid,vid


def test_import_never_approves_or_publishes(knowledge,db,corpus):
    bid=knowledge.import_corpus(corpus,'Base','actor')
    assert db.one('SELECT SUM(approved) n FROM records WHERE base_id=?',(bid,))['n']==0
    assert knowledge.active() is None
    with pytest.raises(DomainError):knowledge.enqueue_build(bid,Settings(),'actor')


def test_public_only_snapshot(knowledge,db,corpus):
    bid=knowledge.import_corpus(corpus,'Base','actor');assert knowledge.approve_public(bid,'actor')==1
    _,vid=knowledge.enqueue_build(bid,Settings(),'actor')
    rows=db.all('SELECT content_json FROM version_records WHERE version_id=?',(vid,))
    assert len(rows)==1 and json.loads(rows[0]['content_json'])['audience']=='public'


def test_edit_does_not_mutate_snapshot_or_active(knowledge,db,corpus):
    bid,_,vid=ready(db,knowledge,corpus);knowledge.activate(vid,'actor')
    row=db.one("SELECT * FROM records WHERE base_id=? AND audience='public'",(bid,));data=json.loads(row['content_json']);data['text']='Nuevo contenido.'
    knowledge.save_record(bid,data,'actor',row['id'])
    assert knowledge.active()['id']==vid
    snapshot=json.loads(db.one('SELECT content_json FROM version_records WHERE version_id=?',(vid,))['content_json'])
    assert snapshot['text']!=data['text']
    with pytest.raises(DomainError):knowledge.activate(vid,'actor')
    knowledge.activate(vid,'actor',rollback=True)


def test_active_base_cannot_be_deleted(knowledge,db,corpus):
    bid,_,vid=ready(db,knowledge,corpus);knowledge.activate(vid,'actor')
    with pytest.raises(DomainError):knowledge.enqueue_delete(bid,'actor')
    knowledge.unpublish('actor');knowledge.enqueue_delete(bid,'actor')
    with pytest.raises(DomainError):knowledge.activate(vid,'actor',rollback=True)


def test_only_published_versions_can_rollback(knowledge,db,corpus):
    bid,_,vid=ready(db,knowledge,corpus)
    with pytest.raises(DomainError):knowledge.activate(vid,'actor',rollback=True)


def test_source_edits_require_review(knowledge,db,corpus):
    bid=knowledge.import_corpus(corpus,'Base','actor');knowledge.approve_public(bid,'actor')
    source=corpus.sources[0].model_dump();source['title']='Título nuevo'
    knowledge.save_source(bid,source,'actor')
    assert db.one('SELECT SUM(approved) n FROM records WHERE base_id=?',(bid,))['n']==0


def test_no_duplicate_pending_build(knowledge,db,corpus):
    bid=knowledge.import_corpus(corpus,'Base','actor');knowledge.approve_public(bid,'actor');knowledge.enqueue_build(bid,Settings(),'actor')
    with pytest.raises(DomainError):knowledge.enqueue_build(bid,Settings(),'actor')
