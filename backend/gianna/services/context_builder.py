"""Build the bounded, attributed context handed to the response model."""
from .catalog import humanize_answer_codes, retrieval_context


def build_context(hits: list[dict], settings) -> list[dict]:
    selected=[];seen=set();used=0
    for hit in hits:
        if hit['record_id'] in seen:continue
        record=hit['record'];raw_text=record['text'] if len(record['text'])<=6500 else hit['text']
        text=humanize_answer_codes(raw_text)
        conditions='\n'.join(humanize_answer_codes(c) for c in record.get('conditions',[])) or 'Sin condiciones editoriales separadas.'
        entry=(retrieval_context(record)+
            f"\nTipo de evidencia: {record['evidence_type']}"
            f"\nCorte: {record.get('cutoff_date') or 'no especificado'}"
            f"\nLocalizador: {record.get('source_locator','')}"
            f"\nTEXTO DE LA FUENTE:\n{text}"
            f"\nCONDICIONES Y LÍMITES:\n{conditions}")
        if len(entry)+used>settings.max_context_chars:continue
        seen.add(hit['record_id']);used+=len(entry)
        selected.append({**hit,'citation':f'C{len(selected)+1}','context':entry})
        if len(selected)>=settings.max_context_records:break
    return selected


def render_evidence(selected: list[dict]) -> str:
    return '\n\n'.join('['+hit['citation']+']\n'+hit['context'] for hit in selected)
