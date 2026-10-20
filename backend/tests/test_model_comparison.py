from scripts.compare_generation_models import summarize


def test_comparison_does_not_turn_failed_requests_into_fast_answers():
    report={'passed':1,'results':[
        {'status':'answered','total_ms':12000,'timings':{'generation_ms':4000,'retrieval_ms':7000},
         'usage':{'output_tokens':100},'trace':{'repair_attempted':True}},
        {'status':'error','total_ms':80000},
        {'status':'answered','total_ms':14000,'timings':{'generation_ms':6000,'retrieval_ms':7000}},
    ]}
    summary=summarize(report)
    assert summary['answered']==2 and summary['total']==3 and summary['checks_passed']==1
    assert summary['mean_http_ms']==13000 and summary['mean_generation_ms']==5000
    assert summary['repairs']==1 and summary['output_tokens_total']==100


def test_no_answers_have_no_latency_score_not_zero_latency():
    summary=summarize({'passed':0,'results':[{'status':'error','total_ms':80000}]})
    assert summary['answered']==0 and summary['mean_http_ms'] is None
    assert summary['mean_generation_ms'] is None
