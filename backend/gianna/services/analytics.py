from collections import Counter
import datetime,json,time


def percentile(values,p):
    if not values:return None
    s=sorted(values);k=(len(s)-1)*p;lo=int(k);hi=min(lo+1,len(s)-1)
    return round(s[lo]+(s[hi]-s[lo])*(k-lo),2)


def summary(db,days=30):
    days=max(1,min(180,int(days)));start=time.time()-days*86400
    rows=db.all("SELECT * FROM queries WHERE at>=? AND mode='public' ORDER BY at",(start,))
    daily=Counter();topics=Counter();statuses=Counter();sources=Counter()
    for r in rows:
        daily[datetime.datetime.fromtimestamp(r['at'],datetime.timezone.utc).date().isoformat()]+=1
        topics[r['topic'] or 'Sin tema recuperado']+=1;statuses[r['status']]+=1
        sources.update(json.loads(r['source_ids_json']))
    lat=[r['total_ms'] for r in rows]
    return {'days':days,'total':len(rows),'sessions':len({r['session_hash'] for r in rows if r['session_hash']}),
        'p50_ms':percentile(lat,.5),'p95_ms':percentile(lat,.95),'answered':statuses['answered'],
        'unanswered':sum(n for k,n in statuses.items() if k!='answered'),
        'positive_feedback':sum(r['feedback']==1 for r in rows),'negative_feedback':sum(r['feedback']==-1 for r in rows),
        'prompt_tokens':sum(r['prompt_tokens'] or 0 for r in rows),'output_tokens':sum(r['output_tokens'] or 0 for r in rows),
        'token_reporting_queries':sum(r['output_tokens'] is not None for r in rows),
        'daily':dict(daily),'topics':dict(topics.most_common(12)),'statuses':dict(statuses),'sources':dict(sources.most_common(15))}
