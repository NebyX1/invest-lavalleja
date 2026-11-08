"""Legacy settings stay readable, while the visible limit matches serving."""
import json
import pytest
from pydantic import ValidationError
from gianna.services.settings import Settings,get_settings


def test_legacy_unused_candidate_limit_is_normalized_without_sql_writes(db,cfg):
    raw=json.dumps({'model':'existing-model','rerank_candidates':24,'temperature':0.35})
    db.execute('INSERT INTO settings(`key`,value) VALUES(?,?)',('runtime',raw))
    settings=get_settings(db,cfg)
    assert settings.rerank_candidates==6 and settings.rerank_mode=='bounded'
    assert settings.rerank_budget_ms==1500 and settings.temperature==0.35
    assert db.one('SELECT value FROM settings WHERE `key`=?',('runtime',))['value']==raw


@pytest.mark.parametrize('values',[{'rerank_mode':'unbounded'},{'rerank_budget_ms':1501},
                                  {'rerank_budget_ms':0},{'rerank_candidates':1}])
def test_serving_limits_cannot_be_removed_in_settings(values):
    with pytest.raises(ValidationError):Settings(**values)


@pytest.mark.parametrize(('saved','expected'),[(400,1500),(350,350)])
def test_former_budget_default_upgrades_without_overwriting_custom_budget_or_sql(db,cfg,saved,expected):
    raw=json.dumps({'model':'kept-model','rerank_budget_ms':saved})
    db.execute('INSERT INTO settings(`key`,value) VALUES(?,?)',('runtime',raw))
    settings=get_settings(db,cfg)
    assert settings.model=='kept-model' and settings.rerank_budget_ms==expected
    assert db.one('SELECT value FROM settings WHERE `key`=?',('runtime',))['value']==raw
