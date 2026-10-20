"""Targeted source-attribution checks, complementing structural checks.

This is not an entailment model. It detects high-impact concepts attached to
sources that do not even discuss them. Paragraphs with inline IDs are checked
against those sources; paragraphs without IDs only against specific proper
names, which must appear somewhere in the retrieved evidence.
"""
import re
from .catalog import significant_terms
from .conversation import fold
from .response_validation import used_citation_ids

ANCHORS={
    'fire_safety':r'\b(?:bomberos|incendio\w*)\b',
    'food_registry':r'\b(?:runaev|bromatolog\w*)\b',
    'protected_land':r'\b(?:proteccion|protegida\w*|snap|unesco)\b',
    'property_inventory':r'\b(?:inventario|disponibilidad|disponibles)\b',
    'environment_agency':r'\b(?:dinacea|dinagua|aap)\b',
}
# Generic words such as "protegida" or "inventario" appear in honest negations
# ("no hay un inventario de predios"), so uncited text is held to proper names only.
SPECIFIC_ANCHORS={**{name:ANCHORS[name] for name in ('fire_safety','food_registry','environment_agency')},
                   'protected_land':r'\b(?:snap|unesco)\b'}


def attribution_issues(text,selected):
    by_id={hit['citation']:fold(hit['record'].get('title','')+' '+hit['record'].get('text','')+' '+
        ' '.join(hit['record'].get('conditions',[]))) for hit in selected}
    everything=' '.join(by_id.values())
    issues=[]
    for index,paragraph in enumerate(re.split(r'\n\s*\n',text)):
        cited=used_citation_ids(paragraph)
        evidence=' '.join(by_id.get(cid,'') for cid in cited) if cited else everything
        anchors=ANCHORS if cited else SPECIFIC_ANCHORS
        normalized=fold(paragraph)
        missing=[name for name,pattern in anchors.items()
                 if re.search(pattern,normalized) and not re.search(pattern,evidence)]
        if missing:issues.append({'paragraph':index,'citation_ids':list(cited),'missing_concepts':missing})
    return issues


def supported_sources(text,selected,declared,minimum=5):
    """Keep declared sources that visibly feed the answer; never leave the answer without one.

    A source stays when its title shares a significant term with the answer or its body overlaps substantially;
    the body threshold scales down for very short records so a brief but genuine source is not discarded.
    """
    answer_terms=significant_terms(text);kept=[]
    for hit in selected:
        if hit['citation'] not in declared:continue
        record=hit['record'];body_terms=significant_terms(record.get('title','')+' '+record.get('text',''))
        if (answer_terms & significant_terms(record.get('title',''))
                or len(answer_terms & body_terms)>=min(minimum,max(1,len(body_terms)//3))):kept.append(hit['citation'])
    return tuple(kept) or tuple(declared[:1])


def remove_misattributed_paragraphs(text,issues):
    rejected={issue['paragraph'] for issue in issues}
    return '\n\n'.join(paragraph for index,paragraph in enumerate(re.split(r'\n\s*\n',text))
                       if index not in rejected).strip()
