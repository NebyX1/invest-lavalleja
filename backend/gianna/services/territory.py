"""Territorial evidence routing, not a business recommendation or legal zoning.

IDs refer to public snapshot chapters. All claims still come from their text.
"""
from .conversation import fold
from .catalog import record_type


TERRITORIAL_RECORDS={
    'Z1':('s10-01-01','s09-01-02'),
    'Z2':('s11-02-01','s09-01-03'),
    'Z3':('s12-01-01','s12-04-01','s12-02-01'),
    'Z4':('s13-01-01','s09-01-05'),
    'Z5':('s14-01-01','s09-01-06'),
    'Z6':('s15-01-01','s09-01-07'),
    'Z7':('s16-02-01','s09-01-08'),
}
TERRITORIAL_IDS={rid for ids in TERRITORIAL_RECORDS.values() for rid in ids}


def is_territorial(record):
    return record.get('id') in TERRITORIAL_IDS or record_type(record)=='zone_profile'


def location_candidates(records,plan):
    by_id={r['id']:r for r in records if r.get('audience')=='public'}
    activity=fold(plan.activity)
    if plan.zones:zones=plan.zones
    elif any(term in activity for term in ('ocio','bar','gastronom')):zones=('Z1','Z2','Z3')
    elif 'alojamiento' in activity:zones=('Z3','Z7','Z2')
    else:zones=tuple(TERRITORIAL_RECORDS)
    # One source per zone first, then additional conditions. Never add entities
    # to the remembered user scope just because they were comparison candidates.
    groups=[[rid for rid in TERRITORIAL_RECORDS[z] if rid in by_id] for z in zones]
    primary=[group[0] for group in groups if group]
    secondary=[rid for group in groups for rid in group[1:] if record_type(by_id[rid])!='zone_profile']
    return (primary+secondary)[:8]


def is_location_condition(record):
    # The public territorial chapter with parcel-specific landscape/service
    # constraints must accompany its commercial hypothesis, not be crowded out.
    return record.get('id')=='s12-04-01'
