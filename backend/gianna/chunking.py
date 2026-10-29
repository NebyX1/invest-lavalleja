"""Fichas de conocimiento: cabecera contextual determinista + empaquetado por tokens exactos.

Cada ficha se indexa con una cabecera (título, tema, sección, zonas) que se antepone
tanto al texto del embedding como al de BM25, de modo que "hospedaje en Villa
Serrana" encuentre la ficha aunque el cuerpo no repita esas palabras (patrón de
Contextual Retrieval). No reescribe el contenido ni usa un modelo generativo.
"""
import hashlib
import re
import uuid
from .domain import record_kind, zone_names
from .errors import DomainError

CONTEXTUALIZER_VERSION = 'cards-context-v5'


def input_prefix(record):
    title = record['title']
    lines = [title]
    context = [value for value in (record.get('topic'), record.get('section')) if value and value != title]
    if context:
        lines.append('Tema: ' + ' | '.join(dict.fromkeys(context)))
    zones = zone_names(record.get('zones', []))
    if zones and len(zones) < 7:
        lines.append('Zonas: ' + '; '.join(zones))
    return '\n'.join(lines) + '\n'


def pack_record(record, counter, limit=420, overlap=40):
    if not 180 <= limit <= 480 or not 0 <= overlap <= 80:
        raise DomainError('Perfil de fragmentación inválido.')
    prefix = input_prefix(record)
    if counter(prefix) > limit - 30:
        raise DomainError('El encabezado no deja espacio suficiente para el texto.')
    text = record['text']
    spans = []
    start = 0
    while start < len(text):
        rest = text[start:]
        if counter(prefix + rest) <= limit:
            end = len(text)
        else:
            lo, hi = start + 1, len(text)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if counter(prefix + text[start:mid]) <= limit:
                    lo = mid
                else:
                    hi = mid - 1
            end = lo
            partial = text[start:end]
            breaks = [m.end() for m in re.finditer(r'\n\n|(?<=[.!?])\s+', partial)]
            viable = [p for p in breaks if p > len(partial) * 0.55]
            if viable:
                end = start + viable[-1]
            else:
                ws = text.rfind(' ', start, end)
                if ws > start + len(partial) * 0.65:
                    end = ws + 1
        body = text[start:end].strip()
        if body:
            embedded = prefix + body
            if counter(embedded) > limit:
                raise DomainError('Fragmento fuera del presupuesto de tokens.')
            spans.append({'text': body, 'embedding_text': embedded, 'sparse_text': embedded,
                          'char_start': start, 'char_end': end, 'token_count': counter(embedded)})
        if end >= len(text):
            break
        new_start = end
        if overlap:
            lo, hi = start + 1, end
            while lo < hi:
                mid = (lo + hi) // 2
                if counter(text[mid:end]) <= overlap:
                    hi = mid
                else:
                    lo = mid + 1
            new_start = lo
            ws = text.find(' ', new_start, end)
            if ws >= 0:
                new_start = ws + 1
        start = max(start + 1, new_start)
    return spans


def chunks_for_record(version_id, record, counter, limit, overlap):
    result = []
    for i, item in enumerate(pack_record(record, counter, limit, overlap)):
        digest = hashlib.sha256((CONTEXTUALIZER_VERSION + '\0' + item['embedding_text'] + '\0' + item['sparse_text']).encode()).hexdigest()
        chunk_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f'gianna:{version_id}:{record["id"]}:{i}:{digest}'))
        result.append({
            'id': chunk_id, 'record_id': record['id'], 'position': i, 'title': record['title'], 'topic': record['topic'],
            'audience': 'public', 'evidence_type': record['evidence_type'], 'cutoff_date': record.get('cutoff_date'),
            'section': record.get('section', ''), 'opportunity_id': record.get('opportunity_id'),
            'record_type': record_kind(record), 'source_refs': record.get('source_refs', []),
            'zones': record.get('zones', []), 'contextualizer_version': CONTEXTUALIZER_VERSION,
            'embedding_hash': digest, **item})
    return result
