"""Rescore immutable retrieved lists against reviewed relevance IDs, without inference."""
import argparse
import hashlib
import json
from pathlib import Path

from scripts.benchmark_invest_rebuild import rank, summarize


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--benchmark',type=Path,required=True);p.add_argument('--cases',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():p.error('Use a new result path')
    source=json.loads(a.benchmark.read_bytes());cases=json.loads(a.cases.read_bytes());by_id={c['id']:c for c in cases}
    result={'retrieved_lists_sha256':hashlib.sha256(a.benchmark.read_bytes()).hexdigest(),
            'reviewed_gold_sha256':hashlib.sha256(a.cases.read_bytes()).hexdigest(),
            'scope':'Post-hoc relevance correction; not a blind benchmark or new timing measurement',
            'provider_calls':0,'original_missing_coverage':[c['id'] for c in cases if not c['old_any']], 'phases':{}}
    for phase,data in source['phases'].items():
        key='old_any' if phase=='original_400' else 'new_any'
        rows=[{**r,'rank':rank(r['ids'],by_id[r['id']][key])} for r in data['rows']]
        comparable=[r for r in rows if by_id[r['id']]['old_any']]
        result['phases'][phase]={'all_cases':summarize(rows),'shared_coverage_cases':summarize(comparable),'rows':rows}
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:{n:v[n] for n in ('all_cases','shared_coverage_cases')} for k,v in result['phases'].items()}))


if __name__=='__main__':main()
