import pytest
from gianna.chunking import chunks_for_record,pack_record
from gianna.errors import DomainError
# Deterministic synthetic tokenizer ONLY for algorithm tests; not an E5 performance/quality test.
def count(text):return len(text)+2


def test_budget_and_complete_character_coverage(corpus):
    record=corpus.records[0].model_dump();record['text']=' '.join('palabra'+str(i) for i in range(160))
    chunks=pack_record(record,count,420,40)
    assert len(chunks)>1 and all(c['token_count']<=420 for c in chunks)
    coverage=set()
    for c in chunks:coverage.update(range(c['char_start'],c['char_end']))
    assert coverage==set(range(len(record['text'])))
    assert all(c['embedding_text'].startswith('passage: ') for c in chunks)


def test_ids_idempotent_per_version(corpus):
    record=corpus.records[0].model_dump()
    a=chunks_for_record('v1',record,count,420,40);b=chunks_for_record('v1',record,count,420,40)
    assert a==b
    c=chunks_for_record('v2',record,count,420,40);assert a[0]['id']!=c[0]['id']
    assert a[0]['embedding_hash']==c[0]['embedding_hash']


def test_invalid_limit(corpus):
    with pytest.raises(DomainError):pack_record(corpus.records[0].model_dump(),count,900,40)


def test_small_record_no_extra_chunks(corpus):
    r=corpus.records[0].model_dump();r['text']='Texto corto.'
    assert len(pack_record(r,count,420,40))==1
