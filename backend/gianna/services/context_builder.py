"""Build the bounded, attributed context handed to the response model."""
from .catalog import humanize_answer_codes, retrieval_context

# Spanish labels keep corpus jargon ("hypothesis") out of the model's vocabulary without changing its meaning.
EVIDENCE_LABELS={'hypothesis':'propuesta a investigar (no comprobada)','documented_in_source':'documentado en la fuente',
                 'mixed':'mixto: datos documentados y propuestas','reference':'referencia'}


def build_context(hits: list[dict], settings,plan=None,existing=(),limit=None) -> list[dict]:
    """Select evidence entries. ``existing`` lets a second reading continue numbering and budgets."""
    selected=[];seen={h['record_id'] for h in existing};used=sum(len(h['context']) for h in existing)
    limit=limit or settings.max_context_records
    for hit in hits:
        if hit['record_id'] in seen:continue
        record=hit['record'];source_text=record['text']
        raw_text=source_text if len(source_text)<=6500 else hit['text']
        text=humanize_answer_codes(raw_text)
        conditions='\n'.join(humanize_answer_codes(c) for c in record.get('conditions',[])) or 'Sin condiciones editoriales separadas.'
        entry=(retrieval_context(record)+
            f"\nTipo de evidencia: {EVIDENCE_LABELS.get(record['evidence_type'],record['evidence_type'])}"
            f"\nCorte: {record.get('cutoff_date') or 'no especificado'}"
            f"\nLocalizador: {record.get('source_locator','')}"
            f"\nTEXTO DE LA FUENTE:\n{text}"
            f"\nCONDICIONES Y LÍMITES:\n{conditions}")
        if len(entry)+used>settings.max_context_chars:continue
        seen.add(hit['record_id']);used+=len(entry)
        selected.append({**hit,'citation':f'C{len(existing)+len(selected)+1}','context':entry})
        if len(existing)+len(selected)>=limit:break
    return selected


def render_evidence(selected: list[dict]) -> str:
    return '\n\n'.join('['+hit['citation']+']\n'+hit['context'] for hit in selected)
