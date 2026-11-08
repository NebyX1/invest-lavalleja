"""Corpus-owned catalog candidates participate in real retrieval orchestration."""
from gianna.corpus import CatalogEntry, Record, information_source_hash
from gianna.services.retrieval import Retriever
from types import SimpleNamespace
import pytest


def catalog():
    r=Retriever(None,None,None,None)
    r._outline=lambda version:[
        {'id':'profile-a','catalog_entry':{'kind':'locality','names':['Puerto Azul','Azul']}},
        {'id':'profile-b','catalog_entry':{'kind':'sector','names':['energía solar']}},
        {'id':'unrelated','catalog_entry':None}]
    return r


def test_catalog_uses_declared_names_accents_and_word_boundaries_without_topic_rules():
    r=catalog()
    assert r.catalog_matches('Energía solar en Puerto Azul','v')==['profile-b','profile-a']
    assert r.catalog_matches('energia solar en AZUL','v')==['profile-b','profile-a']
    assert r.catalog_matches('azulejos y energía','v')==[]
    r._outline=lambda version:[{'id':'new-place','catalog_entry':{'kind':'locality','names':['Localidad Nueva']}}]
    assert r.catalog_matches('Información de Localidad Nueva','v')==['new-place']


def test_empty_catalog_preserves_legacy_behavior():
    r=catalog();r._outline=lambda version:[{'id':'old-record'}]
    assert r.catalog_matches('Azul','v')==[]


def test_catalog_metadata_is_bound_to_the_reviewed_source_and_omitted_for_legacy():
    record=Record(id='old',title='Old',text='An original statement.')
    assert 'catalog_entry' not in record.model_dump()
    before=information_source_hash(record)
    record.catalog_entry=CatalogEntry(kind='locality',names=['Puerto Azul'])
    assert information_source_hash(record)!=before
    assert record.model_dump()['catalog_entry']=={'kind':'locality','names':['Puerto Azul']}


@pytest.mark.parametrize('names',[[],['  '],['ab'],['x'*141]])
def test_invalid_or_empty_entity_vocabulary_is_rejected(names):
    with pytest.raises(ValueError):CatalogEntry(kind='locality',names=names)
