"""Bound recommendations to a few public options and their commercial probes.

Catalogue affinity orders documentary starting points, not expected returns.
Offered options are conversation navigation, never generated factual evidence.
"""
from .catalog import rank_catalog_records,record_type
from .conversation import fold
from .territory import TERRITORIAL_RECORDS


def recommendation_context(records,plan):
    public=[r for r in records if r.get('audience')=='public']
    by_id={r['id']:r for r in public}
    explicit=plan.opportunity_ids or plan.focus_opportunities
    primary=[oid for oid in explicit if oid in by_id and by_id[oid].get('opportunity_id')
             and (not plan.zones or set(plan.zones)&set(by_id[oid].get('zones',[])))]
    if not explicit:
        ranked=rank_catalog_records(public,plan.zones,(),plan.standalone_query,True,8)
        if plan.zones:
            for zone in plan.zones:
                match=next((rid for rid in ranked if by_id[rid].get('opportunity_id')
                    and zone in by_id[rid].get('zones',[])),None)
                if match and match not in primary:primary.append(match)
        else:
            primary=[rid for rid in ranked if by_id[rid].get('opportunity_id')][:2]
            if not primary:
                primary=[r['id'] for r in public if r.get('opportunity_id')][:2]
    if plan.intent=='develop':primary=primary[:1]
    else:primary=primary[:max(2,len(plan.zones))]
    zones=plan.zones or tuple(dict.fromkeys(z for rid in primary for z in by_id[rid].get('zones',[])))
    support=[]
    for zone in zones:
        # A territorial commercial probe describes that chapter's core route,
        # not every opportunity carrying the same zone (e.g. grain campaign
        # data cannot become the entry test for an energy service in Varela).
        core=next((rid for rid in rank_catalog_records(public,(zone,),(),'',True,len(public))
                   if by_id[rid].get('opportunity_id')),None)
        if core not in primary:continue
        main=next((rid for rid in TERRITORIAL_RECORDS.get(zone,()) if rid in by_id),None)
        if main:support.append(main)
        probe=next((r['id'] for r in public if r.get('zones')==[zone]
            and fold(r.get('title','')).startswith('prueba comercial')),None)
        if probe:support.append(probe)
        if not main:
            profile=next((r['id'] for r in public if zone in r.get('zones',[]) and record_type(r)=='zone_profile'),None)
            if profile:support.append(profile)
    return primary,list(dict.fromkeys(primary+support))
