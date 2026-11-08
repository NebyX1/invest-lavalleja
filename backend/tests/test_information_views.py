"""Additive information views keep original records and legacy snapshot bytes intact."""
from copy import deepcopy
import hashlib
import json

import pytest
from pydantic import BaseModel, ValidationError

from gianna.corpus import Corpus, InformationView, Record, export_jsonl, information_source_hash, load_corpus


def original_record(populated=True):
    # Explicit pre-view schema/defaults: do not derive this compatibility oracle from Record.
    result={
        'id':'record-1', 'title':'Título de prueba', 'section':'', 'topic':'General',
        'audience':'internal', 'evidence_type':'mixed', 'text':'Texto original.\nInformación íntegra.',
        'conditions':[], 'source_refs':[], 'zones':[], 'opportunity_id':None,
        'cutoff_date':None, 'period':'', 'source_locator':'', 'original_block_ids':[],
        'original_sha256':'', 'enabled':True,
    }
    if populated:
        result.update(section='Sección original',topic='Turismo',evidence_type='hypothesis',
            conditions=['Condición original.'],source_refs=['S01'],zones=['Z1'],opportunity_id='O01',
            cutoff_date='2026-09-18',period='Corte de septiembre de 2026',source_locator='DOCX p0001',
            original_block_ids=['p0001'],original_sha256='f'*64,enabled=False)
    return result


def corpus_payload(record):
    return {
        'schema_version':'gianna.corpus.v1',
        'document':{'id':'example','title':'Guía de prueba','filename':'','sha256':'',
                    'cutoff_date':None,'conversion_note':''},
        'sources':[{'id':'S01','title':'Fuente de prueba','description':'','url':'','accessed_at':None,
                    'verification':'transcribed_from_document_not_reverified','locator':''}],
        'records':[record], 'conversion_report':{},
    }


def json_bytes(value,canonical=False):
    return json.dumps(value,ensure_ascii=False,sort_keys=canonical,separators=(',',':'),allow_nan=False).encode('utf-8')


def with_view(original,kind='descriptive',text='Descripción informativa, sin alterar la fuente.'):
    return {**deepcopy(original),'information_view':{
        'text':text,'kind':kind,'source_sha256':information_source_hash(Record.model_validate(original)),
    }}


class SnapshotEnvelope(BaseModel):
    corpus: Corpus
    records: dict[str,Record]


@pytest.mark.parametrize('populated',[False,True])
@pytest.mark.parametrize('explicit_null',[False,True])
def test_legacy_standalone_nested_and_canonical_bytes_unchanged(populated,explicit_null):
    expected=original_record(populated)
    payload=deepcopy(expected) if populated else {key:expected[key] for key in ('id','title','text')}
    if explicit_null: payload['information_view']=None
    record=Record.model_validate(payload)
    expected_corpus=corpus_payload(expected)
    corpus=Corpus(**{**expected_corpus,'records':[record]})
    envelope=SnapshotEnvelope(corpus=corpus,records={'original':record})
    expected_envelope={'corpus':expected_corpus,'records':{'original':expected}}

    for model,legacy in ((record,expected),(corpus,expected_corpus),(envelope,expected_envelope)):
        for options in ({},{'round_trip':True},{'by_alias':True}):
            assert model.model_dump(**options)==legacy
            assert model.model_dump(mode='json',**options)==legacy
            assert model.model_dump_json(**options).encode('utf-8')==json_bytes(legacy)
            assert json_bytes(model.model_dump(**options),canonical=True)==json_bytes(legacy,canonical=True)
    assert record.information_view is None
    assert record.model_dump()['cutoff_date']==expected['cutoff_date']


def test_legacy_exclusion_and_explicit_inclusion_keep_null_view_absent():
    original=original_record(False)
    minimal={key:original[key] for key in ('id','title','text')}
    record=Record(**minimal,information_view=None)
    assert record.model_dump(exclude_unset=True)==minimal
    assert record.model_dump(exclude_defaults=True)==minimal
    assert record.model_dump(include={'information_view'})=={}
    assert record.model_dump_json(include={'information_view'})=='{}'
    corpus=Corpus.model_validate(corpus_payload(record))
    selection={'records':{'__all__':{'id','cutoff_date','information_view'}}}
    expected={'records':[{'id':record.id,'cutoff_date':None}]}
    assert corpus.model_dump(include=selection)==expected
    assert corpus.model_dump_json(include=selection).encode('utf-8')==json_bytes(expected)


def test_source_hash_uses_normalized_whole_original_and_utf8_canonical_json():
    original=original_record(False)
    expected=hashlib.sha256(json_bytes(original,canonical=True)).hexdigest()
    minimal={key:original[key] for key in ('id','title','text')}
    assert information_source_hash(Record(**minimal))==expected
    assert information_source_hash(Record(**dict(reversed(list(original.items())))))==expected
    assert information_source_hash(Record(**{**original,'enabled':1,'conditions':()}))==expected
    record=Record.model_validate(with_view(original))
    assert information_source_hash(record)==expected
    record.information_view=InformationView(text='',kind='methodology',source_sha256=expected)
    assert information_source_hash(record)==expected
    assert record.model_dump(exclude={'information_view'})==original


@pytest.mark.parametrize('suffix',['.json','.jsonl'])
@pytest.mark.parametrize('kind',['descriptive','proposal','procedure','methodology'])
def test_valid_native_import_export_roundtrip_preserves_original_fields(tmp_path,suffix,kind):
    original=original_record()
    payload=with_view(original,kind=kind,text='' if kind=='methodology' else 'Información útil.\nSegunda línea.')
    untouched=deepcopy(payload)
    corpus=Corpus.model_validate(corpus_payload(payload))
    record=corpus.records[0]
    assert record.information_view==InformationView(**payload['information_view'])
    assert record.model_dump(exclude={'information_view'})==original
    assert record.audience=='internal' and record.enabled is False
    assert payload==untouched

    path=tmp_path/('corpus'+suffix)
    exported=corpus.model_dump_json() if suffix=='.json' else export_jsonl(corpus)
    path.write_text(exported,encoding='utf-8-sig')
    imported=load_corpus(path)
    assert imported.model_dump()==corpus.model_dump()
    assert imported.model_dump_json()==corpus.model_dump_json()
    assert imported.records[0].information_view.source_sha256==information_source_hash(record)
    # The same native record JSON is used by immutable snapshots; no storage/DDL needed.
    snapshot_record=Record.model_validate_json(record.model_dump_json())
    assert snapshot_record.model_dump()==payload


ORIGINAL_CHANGES=[
    ('id','record-2'),('title','Título actualizado'),('section','Otra sección'),('topic','Industria'),
    ('audience','public'),('evidence_type','reference'),('text','Texto original actualizado.'),
    ('conditions',['Nueva condición.']),('source_refs',['S02']),('zones',['Z2']),
    ('opportunity_id','O02'),('cutoff_date','2026-10-01'),('period','Otro período'),
    ('source_locator','DOCX p0002'),('original_block_ids',['p0002']),('original_sha256','e'*64),
    ('enabled',True),
]


@pytest.mark.parametrize(('field','value'),ORIGINAL_CHANGES)
def test_any_original_change_invalidates_view_without_rewriting_data(field,value):
    original=original_record()
    payload=with_view(original)
    payload[field]=value
    untouched=deepcopy(payload)
    expected={**original,field:value}
    for record in (Record.model_validate(payload),Record.model_validate_json(json.dumps(payload))):
        assert record.information_view is None
        assert record.model_dump()==expected
        assert information_source_hash(record)!=payload['information_view']['source_sha256']
    assert payload==untouched


@pytest.mark.parametrize(('field','value'),ORIGINAL_CHANGES)
def test_original_assignment_invalidates_view(field,value):
    record=Record.model_validate(with_view(original_record()))
    setattr(record,field,value)
    assert record.information_view is None
    assert record.model_dump()=={**original_record(),field:value}


@pytest.mark.parametrize('field',['conditions','source_refs','zones','original_block_ids'])
@pytest.mark.parametrize('nested',[False,True])
def test_in_place_list_edits_are_invalidated_before_serialization(field,nested):
    record=Record.model_validate(with_view(original_record()))
    corpus=Corpus.model_validate(corpus_payload(record))
    getattr(record,field).append('changed')
    expected=original_record()
    expected[field].append('changed')
    model=corpus if nested else record
    dumped=model.model_dump_json() if nested else model.model_dump()
    assert record.information_view is None
    assert record.model_dump()==expected
    assert 'information_view' not in (json.loads(dumped)['records'][0] if nested else dumped)


@pytest.mark.parametrize('suffix',['.json','.jsonl'])
@pytest.mark.parametrize(('field','value'),[
    ('text','Texto nuevo.'),('conditions',['Condición nueva.']),('cutoff_date','2026-10-01'),
])
def test_stale_views_are_removed_on_nested_native_import(tmp_path,suffix,field,value):
    payload=with_view(original_record())
    payload[field]=value
    data=corpus_payload(payload)
    path=tmp_path/('stale'+suffix)
    if suffix=='.json':
        serialized=json.dumps(data,ensure_ascii=False)
    else:
        rows=[{'_kind':'document',**data['document']},{'_kind':'source',**data['sources'][0]},
              {'_kind':'record',**payload}]
        serialized='\n'.join(json.dumps(row,ensure_ascii=False) for row in rows)+'\n'
    path.write_text(serialized,encoding='utf-8')
    corpus=load_corpus(path)
    assert corpus.records[0].information_view is None
    assert corpus.records[0].model_dump()=={**original_record(),field:value}
    assert 'information_view' not in json.loads(corpus.model_dump_json())['records'][0]


@pytest.mark.parametrize('kind',['descriptive','proposal','procedure'])
@pytest.mark.parametrize('text',['',' \t\r\n','\u2003'])
def test_only_methodology_accepts_blank_text(kind,text):
    view={'text':text,'kind':kind,'source_sha256':'a'*64}
    with pytest.raises(ValidationError): InformationView.model_validate(view)
    with pytest.raises(ValidationError): Record(**original_record(),information_view=view)


@pytest.mark.parametrize('text',['',' \t\n','Método original.','á'*8000,'🧭'*8000],
                         ids=['empty','whitespace','method','limit-unicode','limit-emoji'])
def test_view_text_limits_accept_boundary_and_preserve_text(text):
    view=InformationView(text=text,kind='methodology',source_sha256='a'*64)
    assert view.text==text
    if text.strip():
        assert InformationView(text=text,kind='descriptive',source_sha256='a'*64).text==text


@pytest.mark.parametrize('changes',[
    {'text':'á'*8001},{'text':None},{'text':42},{'kind':'unknown'},{'kind':'Descriptive'},
    {'kind':None},{'source_sha256':'A'*64},{'source_sha256':'g'*64},
    {'source_sha256':'a'*63},{'source_sha256':'a'*65},{'source_sha256':'a'*64+'\n'},
    {'source_sha256':None},{'extra':'forbidden'},{'approved':True},
])
def test_malformed_views_are_rejected_even_if_their_hash_is_stale(changes):
    view={'text':'Descripción.','kind':'descriptive','source_sha256':'a'*64,**changes}
    with pytest.raises(ValidationError): InformationView.model_validate(view)
    with pytest.raises(ValidationError): Record(**original_record(),information_view=view)


@pytest.mark.parametrize('missing',['text','kind','source_sha256'])
def test_view_requires_all_fields(missing):
    view={'text':'Descripción.','kind':'descriptive','source_sha256':'a'*64}
    view.pop(missing)
    with pytest.raises(ValidationError): InformationView.model_validate(view)


def test_information_view_does_not_add_or_accept_editorial_approval():
    record=Record.model_validate(with_view(original_record()))
    assert record.audience=='internal'
    assert record.enabled is False
    assert 'approved' not in record.model_dump()
    with pytest.raises(ValidationError): Record(**{**record.model_dump(),'approved':True})
