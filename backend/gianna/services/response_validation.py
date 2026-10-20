"""Structural helpers for source references and retrieval coverage; never a truth estimator."""
import re
from .planning import matches_facet


CITATION_GROUP=re.compile(r'\[(C\d+(?:\s*,\s*C\d+)*)\]')


def used_citation_ids(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(citation for group in CITATION_GROUP.findall(text)
                               for citation in re.findall(r'C\d+',group)))


def evidence_coverage(plan,selected: list[dict]) -> dict:
    # Retrieval diagnostics, not a semantic judgement of whether a source
    # answers the question. Missing catalogue profiles cannot pre-empt reading
    # useful evidence or force a blanket lack-of-information response.
    ids={hit['record']['id'] for hit in selected}
    missing=['reference:'+oid for oid in plan.opportunity_ids if oid not in ids]
    for facet in plan.facets:
        if not any(matches_facet(hit['record'],facet) for hit in selected):missing.append('facet:'+facet)
    return {'ok':bool(selected),'complete':not missing,'missing':missing}
