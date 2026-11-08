"""Serving boundaries and cache isolation; synthetic scores are not quality evidence."""
from concurrent.futures import ThreadPoolExecutor
import json
import threading
from types import SimpleNamespace

import pytest

from gianna.corpus import Record
from gianna.errors import DomainError
from gianna.services.retrieval import Retriever
from gianna.services.reranking import BoundedReranker, RerankBudget, RerankCache
from gianna.services.settings import Settings


class Clock:
    def __init__(self): self.value = 0.0
    def __call__(self): return self.value


class Engine:
    def __init__(self):
        self.profile = {'fingerprint':'fixture-profile'}
        self.calls = []
        self.failure = None
    def query(self, query): return [0.0]*384, query
    def rerank_bounded(self, query, texts, **options):
        self.calls.append((query, texts, options))
        if self.failure: raise self.failure
        return getattr(self,'scores',list(range(len(texts))))


def fixture_retriever(count=8):
    records = {f'card-{i}':Record(id=f'card-{i}', title=f'Card {i}', topic='Fixture',
        text=f'Public fixture {i}. No production content.', audience='public',
        evidence_type='hypothesis').model_dump() for i in range(count)}
    chunks = [{'id':f'chunk-{i}', 'record_key':f'card-{i}', 'text':f'Card {i}\nTema: Fixture\nFixture passage {i}'}
              for i in range(count)]
    points = [{'id':row['id'], 'score':1.0/(i+1), 'channels':['dense','bm25']}
              for i,row in enumerate(chunks)]
    engine = Engine()
    retriever = Retriever(SimpleNamespace(all=lambda *args:chunks), None, None,
                          SimpleNamespace(search=lambda *args,**kwargs:points))
    retriever.version = lambda version_id=None:{'id':version_id or 'version-1','collection_name':'fixture'}
    retriever.engine = lambda version:engine
    retriever.records = lambda *args:records
    retriever._outline = lambda version_id:[]
    return retriever, engine, records, chunks


def search(retriever, budget=None, **options):
    return retriever.search('sentinel-private-question',Settings(),limit=8,rerank_budget=budget,**options)


def test_only_small_window_changes_and_chunk_header_is_not_duplicated():
    retriever, engine, _, _ = fixture_retriever()
    baseline, _ = search(retriever)
    cards, trace = search(retriever,RerankBudget())
    assert {card['record_id'] for card in cards[:6]}=={f'card-{i}' for i in range(6)}
    assert trace['rerank']['fusion']=='rrf_equal_hybrid_neural'
    assert cards[-2:]==baseline[-2:]
    assert len(engine.calls)==1 and len(engine.calls[0][1])==6
    assert engine.calls[0][1][0].count('Card 0')==1
    assert 0 < engine.calls[0][2]['timeout'] <= 1.5
    assert engine.calls[0][2]['max_tokens']==160
    assert trace['rerank']['applied'] and trace['rerank']['reordered']


def test_catalog_profile_enters_neural_window_but_is_not_a_forced_winner():
    retriever,engine,_,_=fixture_retriever()
    engine.scores=[0,1,6,5,4,3]
    retriever._outline=lambda version:[{'id':'card-7','catalog_entry':
        {'kind':'locality','names':['Puerto Azul']}}]
    cards,trace=retriever.search('Información de Puerto Azul',Settings(),rerank_budget=RerankBudget())
    assert 'card-7' in trace['rerank']['before_ids']
    assert trace['catalog_ids']==['card-7']
    # The deterministic double scores later candidates higher. A catalog hit
    # must compete, rather than bypassing the retained neural reranker.
    assert len(engine.calls)==1 and cards[0]['record_id']!='card-7'
    assert trace['rerank']['applied']


def test_cache_is_shared_but_neural_budget_is_per_answer_and_never_resets():
    retriever, engine, _, _ = fixture_retriever()
    budget=RerankBudget()
    first,_=search(retriever,budget)
    again,trace=search(retriever,budget)
    assert again==first and trace['rerank']['state']=='cache_hit'
    assert budget.attempts==1 and len(engine.calls)==1
    other,trace=retriever.search('different query',Settings(),rerank_budget=budget)
    baseline,_=retriever.search('different query',Settings())
    assert other==baseline and trace['rerank']['reason']=='budget_spent'
    # A different answer can use the cached result without spending its attempt.
    fresh=RerankBudget()
    _,trace=search(retriever,fresh)
    assert trace['rerank']['state']=='cache_hit' and fresh.attempts==0


@pytest.mark.parametrize('change',['version','fingerprint','chunk','title'])
def test_cache_invalidates_for_publication_profile_or_content_change(change):
    retriever, engine, records, chunks = fixture_retriever()
    search(retriever,RerankBudget())
    options={}
    if change=='version': options['version_id']='version-2'
    if change=='fingerprint': engine.profile['fingerprint']='new-profile'
    if change=='chunk': chunks[0]['text']+=' Changed.'
    if change=='title': records['card-0']['title']='Changed public title'
    _,trace=search(retriever,RerankBudget(),**options)
    assert trace['rerank']['state']=='applied' and len(engine.calls)==2


@pytest.mark.parametrize('failure,reason',[
    (DomainError('sentinel-provider-prose',503,'rerank_busy'),'busy'),
    (DomainError('sentinel-provider-prose',503,'rerank_timeout'),'timeout'),
    (DomainError('sentinel-provider-prose',503,'rerank_not_ready'),'unavailable'),
    (RuntimeError('sentinel-provider-prose'),'error'),
])
def test_every_serving_failure_preserves_exact_hybrid_cards(failure,reason,caplog):
    retriever, engine, _, _ = fixture_retriever()
    engine.failure=failure
    baseline,_=search(retriever)
    with caplog.at_level('INFO'):
        cards,trace=search(retriever,RerankBudget())
    assert cards==baseline
    assert trace['rerank']['state']=='fallback' and trace['rerank']['reason']==reason
    assert not trace['rerank']['applied']
    assert 'sentinel-provider-prose' not in caplog.text
    assert 'sentinel-private-question' not in caplog.text
    if reason=='error':
        failures=[r for r in caplog.records if getattr(r,'event_name',None)=='retrieval.rerank_failed']
        assert failures and failures[0].event_fields['exception']['type']=='RuntimeError'
        assert 'sentinel' not in str(failures[0].event_fields)


@pytest.mark.parametrize('scores',[[1.0],[float('nan')]*6,[True]*6,['1']*6,{'score':1}])
def test_invalid_or_partial_scores_never_replace_or_cache_hybrid(scores):
    retriever, engine, _, _ = fixture_retriever()
    engine.rerank_bounded=lambda *args,**kwargs:scores
    baseline,_=search(retriever)
    cards,trace=search(retriever,RerankBudget())
    assert cards==baseline and trace['rerank']['reason']=='invalid_scores'
    assert not retriever.reranker.cache._values


def test_late_complete_result_is_rejected_and_not_cached():
    clock=Clock()
    retriever, engine, _, _ = fixture_retriever()
    retriever.reranker=BoundedReranker(clock=clock)
    def slow(*args,**kwargs):
        clock.value+=.401
        return [1.0]*6
    engine.rerank_bounded=slow
    baseline,_=search(retriever)
    cards,trace=search(retriever,RerankBudget(400,clock=clock))
    assert cards==baseline and trace['rerank']['reason']=='timeout'
    assert not retriever.reranker.cache._values


def test_parallel_request_falls_back_immediately_without_duplicate_neural_work():
    retriever, engine, _, _ = fixture_retriever()
    baseline,_=search(retriever)
    entered=threading.Event();release=threading.Event()
    def held(*args,**kwargs):
        entered.set()
        assert release.wait(2)
        return list(range(6))
    engine.rerank_bounded=held
    with ThreadPoolExecutor(max_workers=2) as pool:
        owner=pool.submit(search,retriever,RerankBudget())
        assert entered.wait(1)
        fallback=pool.submit(search,retriever,RerankBudget())
        try:
            cards,trace=fallback.result(timeout=.3)
            assert cards==baseline and trace['rerank']['reason']=='busy'
        finally:release.set()
        assert owner.result(timeout=1)[1]['rerank']['state']=='applied'


def test_cache_ttl_lru_capacity_and_no_raw_content_retention():
    clock=Clock();cache=RerankCache(max_entries=2,ttl=3,clock=clock)
    cache.put(b'a',(1.,));cache.put(b'b',(2.,));assert cache.get(b'a')==(1.,)
    cache.put(b'c',(3.,));assert list(cache._values)==[b'a',b'c']
    clock.value=3
    assert cache.get(b'a')!=(1.,)
    retriever,_,_,_=fixture_retriever()
    search(retriever,RerankBudget())
    retained=repr(retriever.reranker.cache._values)
    assert 'sentinel-private-question' not in retained and 'Fixture passage' not in retained
    assert all(isinstance(key,bytes) and len(key)==32 for key in retriever.reranker.cache._values)
    retriever.clear_rerank_cache();assert not retriever.reranker.cache._values


def test_preferences_are_preserved_and_explicit_disabled_mode_uses_no_neural():
    retriever,engine,records,_=fixture_retriever()
    records['card-0']['zones']=['Z1']
    cards,trace=search(retriever,RerankBudget(),zones=['Z1'])
    assert cards[0]['record_id']=='card-0' and trace['rerank']['applied']
    engine.calls=[]
    baseline,_=search(retriever)
    disabled=Settings().model_copy(update={'rerank_mode':'hybrid'})
    cards,trace=retriever.search('sentinel-private-question',disabled,rerank_budget=RerankBudget())
    assert cards==baseline and not engine.calls and trace['rerank']['reason']=='disabled'


def test_budget_caps_config_and_allows_only_one_attempt_in_parallel():
    budget=RerankBudget(100000)
    assert budget.timeout_ms==1500
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims=list(pool.map(lambda _:budget.claim(),range(20)))
    assert sum(value is not None for value in claims)==1
    assert RerankBudget(0).claim() is None
    for invalid in (float('nan'),float('inf'),True,'400'):
        with pytest.raises(ValueError):RerankBudget(invalid)


def test_explicit_offline_modes_are_separate_and_report_failure_instead_of_hiding_it():
    retriever,engine,_,_=fixture_retriever()
    engine.rerank=lambda query,texts:list(range(len(texts)))
    cards,trace=search(retriever,mode='rerank')
    assert cards[0]['record_id']=='card-7' and trace['rerank']['mode']=='rerank'
    assert trace['rerank']['state']=='applied'
    def failure(*args):raise DomainError('private model details',503,'rerank_timeout')
    engine.rerank=failure
    fallback,trace=search(retriever,mode='fused')
    baseline,_=search(retriever)
    assert fallback==baseline and trace['rerank']['state']=='fallback'


def test_final_scores_are_monotonic_across_preferred_window_and_untouched_tail():
    retriever,engine,records,_=fixture_retriever(count=10)
    records['card-2']['zones']=['Z1']
    records['card-8']['zones']=['Z1']
    baseline,_=search(retriever,zones=['Z1'])
    cards,trace=search(retriever,RerankBudget(),zones=['Z1'])
    ids=[card['record_id'] for card in cards]
    assert set(ids[:2])=={'card-8','card-2'}
    assert ids[6:]==[card['record_id'] for card in baseline][6:]
    assert all(a['score']>b['score'] for a,b in zip(cards,cards[1:]))
    assert trace['rerank']['score_basis']=='final_rank_rrf'
    cached,cache_trace=search(retriever,RerankBudget(),zones=['Z1'])
    assert cached==cards and cache_trace['rerank']['score_basis']=='final_rank_rrf'


def test_encoder_contention_consumes_answer_budget_and_later_search_cannot_reset_it():
    clock=Clock()
    retriever,engine,_,_=fixture_retriever()
    def queued_encoder(query):
        clock.value+=.401
        return [0.0]*384,query
    engine.query=queued_encoder
    budget=RerankBudget(400,clock=clock)
    cards,trace=search(retriever,budget)
    baseline,_=search(retriever)
    assert cards==baseline and trace['rerank']['reason']=='budget_spent'
    assert not engine.calls and budget.attempts==0
    assert budget.remaining()==0 and budget.start() is False
    engine.query=lambda query:([0.0]*384,query)
    cards,trace=retriever.search('next tool lookup',Settings(),rerank_budget=budget)
    assert not engine.calls and trace['rerank']['reason']=='budget_spent'


def test_encoder_elapsed_time_is_subtracted_from_the_single_neural_timeout():
    clock=Clock()
    retriever,engine,_,_=fixture_retriever()
    def encoder(query):
        clock.value+=.15
        return [0.0]*384,query
    engine.query=encoder
    _,trace=search(retriever,RerankBudget(clock=clock))
    assert trace['rerank']['applied']
    assert engine.calls[0][2]['timeout']==pytest.approx(1.35)
