"""Bounded server-owned project memory, encrypted with the session transcript.

User scope/activity and source-backed offered option IDs are kept separately.
Generated prose, facts and citation labels never become retrieval evidence.
The envelope is backward compatible with old encrypted transcript lists.
"""
from pydantic import ValidationError

from .agents import InvestorMemory
from .catalog import VALID_OPPORTUNITY, ZONE_BY_ID
from .planning import FACETS


def clean_memory(value):
    try:
        return InvestorMemory.model_validate(value if isinstance(value,dict) else {}).model_dump()
    except ValidationError:
        return InvestorMemory().model_dump()


def clean_state(value):
    if not isinstance(value,dict) or not value:return {}
    def values(key):
        items=value.get(key,[])
        return items if isinstance(items,(list,tuple)) else []
    offered=[]
    for option in values('offered_options')[:6]:
        if not isinstance(option,dict) or not isinstance(option.get('id'),str) or not VALID_OPPORTUNITY.fullmatch(option['id']):continue
        zones=option.get('zones',[])
        if not isinstance(zones,(list,tuple)):continue
        offered.append({'id':option['id'],'zones':[z for z in zones if isinstance(z,str) and z in ZONE_BY_ID]})
    return {
        'intent':value.get('intent') if value.get('intent') in {'explore','recommend','develop','locations','requirements','fact'} else 'fact',
        'zones':[z for z in values('zones') if isinstance(z,str) and z in ZONE_BY_ID][:7],
        'opportunity_ids':[o for o in values('opportunity_ids') if isinstance(o,str) and VALID_OPPORTUNITY.fullmatch(o)][:16],
        'activity':str(value.get('activity',''))[:160],
        'facets':[f for f in values('facets') if isinstance(f,str) and f in FACETS],
        'clarification':str(value.get('clarification',''))[:200],
        'brief':str(value.get('brief',''))[:1000],
        'focus_opportunities':[o for o in values('focus_opportunities') if isinstance(o,str) and VALID_OPPORTUNITY.fullmatch(o)][:3],
        'offered_options':offered,
        'memory':clean_memory(value.get('memory')),
    }


def latest_state(history):
    for message in reversed(history):
        if message.get('role')=='assistant' and isinstance(message.get('state'),dict):
            return clean_state(message['state'])
    return {}


def unpack_session(value):
    if isinstance(value,list):return value[-12:],latest_state(value)
    if isinstance(value,dict) and isinstance(value.get('messages'),list):
        return value['messages'][-12:],clean_state(value.get('project'))
    return [],{}


def state_for(plan,cited_records=None):
    offered=list(plan.offered_options)
    if cited_records is not None:
        offered=[{'id':r['opportunity_id'],'zones':r.get('zones',[])} for r in cited_records
                 if r.get('audience')=='public' and r.get('opportunity_id')]
    return clean_state({'intent':plan.intent,'zones':list(plan.zones),
        'opportunity_ids':list(plan.opportunity_ids),'activity':plan.activity,
        'facets':list(plan.facets),'clarification':plan.clarification,'brief':plan.project_brief,
        'focus_opportunities':list(plan.focus_opportunities),'offered_options':offered,'memory':plan.memory})
