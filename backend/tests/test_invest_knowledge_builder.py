"""Knowledge compilation: originals, private audience and exact source bindings."""
import json

import pytest

from gianna.corpus import Corpus, DocumentInfo, InformationView, Record, Source, information_source_hash
from scripts.build_invest_knowledge import compile_corpus


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    return path


@pytest.fixture
def inputs(tmp_path):
    original = Corpus(document=DocumentInfo(id='fixture', title='Original'),
        sources=[Source(id='source', title='Original source')], records=[
        Record(id='fact', title='Locality', text='A fact. An author task.', audience='public',
               evidence_type='mixed', source_refs=['source'], conditions=['An author checklist.']),
        Record(id='procedure', title='Procedure', text='Exact requirement with exception.',
               audience='public', conditions=['Material exception.'], source_refs=['source']),
        Record(id='method', title='Method', text='Original commercial coaching.', audience='public'),
        Record(id='private', title='Private', text='PRIVATE CONTENT', audience='internal')])
    reviewed = original.model_copy(deep=True)
    for record, text, kind in zip(reviewed.records[:3], ['A fact.', 'Requirement summary.', ''],
                                  ['descriptive', 'procedure', 'methodology']):
        record.information_view = InformationView(text=text, kind=kind,
                                                  source_sha256=information_source_hash(record))
    supplement = {'edition_date': '2026-11-08', 'scope_note': 'Reviewed edition.',
        'sources': [{'id': 'web', 'title': 'Primary source', 'url': 'https://example.test/source'}],
        'records': [{'id': 'new', 'title': 'New fact', 'text': 'A sourced fact.', 'kind': 'descriptive',
                     'evidence_type': 'documented_in_source', 'source_refs': ['web']}]}
    return (write(tmp_path/'original.json', original.model_dump(mode='json')),
            write(tmp_path/'reviewed.json', reviewed.model_dump(mode='json')),
            write(tmp_path/'supplement.json', supplement), original)


def test_compilation_retains_all_originals_and_existing_internal_records(inputs):
    a, b, c, original = inputs
    before = [p.read_bytes() for p in (a,b,c)]
    compiled = compile_corpus(a,b,c)
    records = {r.id:r for r in compiled.records}
    assert records['private'].model_dump() == original.records[3].model_dump()
    for record in original.records[:3]:
        archive = records['original.'+record.id].model_dump()
        archive.update(id=record.id, audience='public')
        assert archive == record.model_dump()
    assert records['fact'].text == 'A fact.' and records['fact'].conditions == []
    assert records['fact'].documentary.text == 'A fact. An author task.'
    assert records['fact'].documentary.conditions == ['An author checklist.']
    assert records['procedure'].text == 'Exact requirement with exception.'
    assert records['procedure'].conditions == ['Material exception.']
    assert 'method' not in records and records['original.method'].audience == 'internal'
    assert all(r.information_view is not None for r in compiled.records if r.audience=='public')
    roundtrip = Corpus.model_validate_json(compiled.model_dump_json())
    assert roundtrip == compiled
    assert before == [p.read_bytes() for p in (a,b,c)]


def test_stale_view_cannot_silently_create_an_unbound_summary(inputs):
    a,b,c,_ = inputs
    changed = json.loads(a.read_text(encoding='utf-8'))
    changed['records'][0]['text'] += ' Source revision changed.'
    write(a,changed)
    with pytest.raises(ValueError, match='stale'):
        compile_corpus(a,b,c)


def test_supplement_cannot_override_a_known_source_or_duplicate_a_record(inputs):
    a,b,c,_ = inputs
    supplement = json.loads(c.read_text(encoding='utf-8'))
    supplement['sources'][0]['id'] = 'source'
    write(c,supplement)
    with pytest.raises(ValueError, match='new'):
        compile_corpus(a,b,c)


def test_no_internal_source_text_enters_the_public_compiled_records(inputs):
    a,b,c,_ = inputs
    result = compile_corpus(a,b,c)
    public = '\n'.join(r.text for r in result.records if r.audience=='public')
    assert 'PRIVATE CONTENT' not in public
    assert 'An author task.' not in public
    assert 'Original commercial coaching.' not in public


def test_source_backed_amendment_keeps_archive_and_fails_if_stale(inputs):
    a,b,c,_ = inputs
    compiled = compile_corpus(a,b,c)
    public = next(r for r in compiled.records if r.id=='fact')
    original_archive = next(r for r in compiled.records if r.id=='original.fact').model_dump()
    supplement = json.loads(c.read_text(encoding='utf8'))
    supplement['amendments'] = [{'id':'fact','expected_sha256':information_source_hash(public),
        'changes':{'text':'An explicitly identified fact.', 'source_refs':['source','web']}}]
    write(c,supplement)
    changed = compile_corpus(a,b,c)
    assert next(r for r in changed.records if r.id=='original.fact').model_dump() == original_archive
    assert next(r for r in changed.records if r.id=='fact').text == 'An explicitly identified fact.'
    supplement['amendments'][0]['expected_sha256'] = '0'*64
    write(c,supplement)
    with pytest.raises(ValueError,match='stale'): compile_corpus(a,b,c)
