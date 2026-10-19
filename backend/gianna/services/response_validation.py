"""Structural citation and task-coverage checks; never a truth estimator."""
import re
from .catalog import record_type


CITATION_GROUP=re.compile(r'\[(C\d+(?:\s*,\s*C\d+)*)\]')


def used_citation_ids(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(citation for group in CITATION_GROUP.findall(text)
                               for citation in re.findall(r'C\d+',group)))


def _line_requires_citation(line: str,is_first: bool = False,is_final: bool = False) -> bool:
    if re.match(r'^#{1,6}\s+\S',line):return False
    if re.fullmatch(r'(?:\*\*[^*\n]{1,140}\*\*|__[^_\n]{1,140}__):?',line):return False
    plain=re.sub(r'^(?:#{1,6}\s*|[-*]\s+|\d+[.)]\s+)', '', line).strip()
    if not plain:return False
    # Only one possible escape hatch exists: a standalone closing question on
    # the final non-empty line. Earlier rhetorical questions still need cites.
    if is_first and len(plain)<=160 and (plain.endswith(':') or not re.search(r'[.!?]$',plain)):return False
    if is_final and '¿' in plain and plain.endswith('?'):return False
    if re.fullmatch(r'\*{0,2}(?:opciones|condiciones|próximo paso|para afinar|en síntesis)\*{0,2}:?',plain,re.I):return False
    return True


def validate_citation_syntax(text: str, allowed) -> bool:
    refs=set(used_citation_ids(text));allowed=set(allowed)
    if not refs or not refs<=allowed:return False
    if re.search(r'https?://|www\.',text,re.I):return False
    lines=[line.strip() for line in text.splitlines() if line.strip()]
    for index,line in enumerate(lines):
        if _line_requires_citation(line,index==0,index==len(lines)-1) and not CITATION_GROUP.search(line):return False
    return True


def remove_uncited_lines(text: str) -> tuple[str,list[int]]:
    """Drop unsupported prose while preserving layout and allowed presentation lines."""
    numbered=[(number,line) for number,line in enumerate(text.splitlines(),1)]
    nonempty=[number for number,line in numbered if line.strip()]
    first=nonempty[0] if nonempty else None;last=nonempty[-1] if nonempty else None
    kept=[];removed=[]
    for number,line in numbered:
        stripped=line.strip()
        if (not stripped or not _line_requires_citation(stripped,number==first,number==last)
                or CITATION_GROUP.search(stripped)):
            kept.append(line)
        else:
            removed.append(number)
    cleaned='\n'.join(kept).strip()
    return re.sub(r'\n{3,}','\n\n',cleaned),removed


def citation_diagnostics(text: str,allowed,plan,selected: list[dict]) -> dict:
    """Return content-free validation signals safe to persist in query traces."""
    used=used_citation_ids(text);allowed_set=set(allowed)
    uncited=[];lines=[(number,line.strip()) for number,line in enumerate(text.splitlines(),1) if line.strip()]
    for index,(number,stripped) in enumerate(lines):
        if _line_requires_citation(stripped,index==0,index==len(lines)-1) and not CITATION_GROUP.search(stripped):
            uncited.append(number)
    return {'used_citation_ids':list(used),'unknown_citation_ids':sorted(set(used)-allowed_set),
            'uncited_line_numbers':uncited,'contains_url':bool(re.search(r'https?://|www\.',text,re.I)),
            'citation_syntax_ok':validate_citation_syntax(text,allowed),
            'plan_coverage_ok':response_covers_plan(plan,selected,text)}


def evidence_coverage(plan,selected: list[dict]) -> dict:
    selected_records=[hit['record'] for hit in selected]
    selected_ids={record['id'] for record in selected_records}
    missing=[]
    if plan.opportunity_ids:
        missing.extend(f'opportunity:{oid}' for oid in plan.opportunity_ids if oid not in selected_ids)
    if plan.intent=='explore' and plan.zones:
        for zone_id in plan.zones:
            if not any(record_type(r)=='zone_profile' and zone_id in (r.get('zones') or []) for r in selected_records):
                missing.append(f'zone_profile:{zone_id}')
            if not any(record_type(r)=='opportunity' and zone_id in (r.get('zones') or []) for r in selected_records):
                missing.append(f'opportunity_for_zone:{zone_id}')
    return {'ok':not missing,'missing':missing}


def response_covers_plan(plan,selected: list[dict],text: str) -> bool:
    used=set(used_citation_ids(text))
    cited=[hit['record'] for hit in selected if hit['citation'] in used]
    if plan.intent=='explore' and plan.zones:
        return all(any(record_type(record)=='opportunity' and zone_id in (record.get('zones') or [])
                       for record in cited) for zone_id in plan.zones)
    if plan.opportunity_ids:
        return all(any(record.get('id')==opportunity_id for record in cited) for opportunity_id in plan.opportunity_ids)
    return True
