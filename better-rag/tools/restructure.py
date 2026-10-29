"""Reestructura el corpus consolidado en fichas de conocimiento autosuficientes.

El corpus original conserva fragmentos de tabla de 60-200 caracteres ("Ocupación
supuesta", "2 · Contrastar mercado") que, recuperados solos, no significan nada.
Este paso determinista (sin LLM) fusiona los registros contiguos que comparten
prefijo ``sNN-MM-`` en una sola ficha con su título padre, y conserva
trazabilidad: fuentes, zonas, bloques originales y fechas se unen sin perder nada.

Uso: python restructure.py ENTRADA.gianna.json SALIDA.gianna.json
"""
import hashlib
import json
import re
import sys
from collections import OrderedDict
from pathlib import Path

GROUP = re.compile(r'^(s\d{2}-\d{2})-(\d{2})$')


def strip_prefix(title, parent):
    for sep in (' · ', ' - '):
        if title.startswith(parent + sep):
            return title[len(parent) + len(sep):]
    return title


def merge(group):
    ordered = sorted(group, key=lambda r: r['id'])
    # El padre es el registro sin sufijo " · x" (resumen de la sección), o el título común más corto.
    parent_title = min((r['title'] for r in ordered), key=len)
    parent_title = parent_title.split(' · ')[0]
    parts = []
    for record in ordered:
        label = strip_prefix(record['title'], parent_title)
        body = record['text'].strip()
        if label != record['title'] and label and not body.casefold().startswith(label.casefold()[:30]):
            parts.append(f'{label}: {body}')
        else:
            parts.append(body)
    text = '\n\n'.join(parts)
    conditions = list(OrderedDict.fromkeys(c for r in ordered for c in r.get('conditions', [])))
    refs = list(OrderedDict.fromkeys(s for r in ordered for s in r.get('source_refs', [])))
    zones = list(OrderedDict.fromkeys(z for r in ordered for z in r.get('zones', [])))
    blocks = list(OrderedDict.fromkeys(b for r in ordered for b in r.get('original_block_ids', [])))
    evidence = {r['evidence_type'] for r in ordered}
    locator = '; '.join(OrderedDict.fromkeys(r.get('source_locator', '') for r in ordered if r.get('source_locator')))
    merged = dict(ordered[0])
    merged.update(
        id=GROUP.match(ordered[0]['id']).group(1),
        title=parent_title,
        text=text,
        conditions=conditions,
        source_refs=refs,
        zones=zones,
        original_block_ids=blocks,
        evidence_type=evidence.pop() if len(evidence) == 1 else 'mixed',
        cutoff_date=max(r.get('cutoff_date') or '' for r in ordered) or None,
        source_locator=locator[:1500],
        original_sha256=hashlib.sha256('\n'.join(r['original_sha256'] for r in ordered).encode()).hexdigest(),
    )
    return merged


def restructure(corpus):
    groups = OrderedDict()
    standalone = []
    for record in corpus['records']:
        match = GROUP.match(record['id'])
        if record['audience'] == 'public' and match:
            groups.setdefault(match.group(1), []).append(record)
        else:
            standalone.append(record)
    merged = []
    for key, members in groups.items():
        merged.append(members[0] if len(members) == 1 else merge(members))
    records = sorted(merged + standalone, key=lambda r: (r['audience'] != 'public', r['id']))
    result = dict(corpus)
    result['records'] = records
    note = corpus['document'].get('conversion_note', '')
    digest = hashlib.sha256(json.dumps(records, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    result['document'] = dict(
        corpus['document'], id=corpus['document']['id'].replace('consolidado', 'fichas'),
        title=corpus['document']['title'] + ' (fichas)', filename='Invest_Lavalleja_2026_10_19_fichas.gianna.json', sha256=digest,
        conversion_note=(note + ' Reestructurado en fichas: fragmentos contiguos fusionados por sección.').strip()[:4000])
    return result


if __name__ == '__main__':
    source, target = Path(sys.argv[1]), Path(sys.argv[2])
    data = json.loads(source.read_text(encoding='utf-8'))
    out = restructure(data)
    target.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    pub = [r for r in out['records'] if r['audience'] == 'public']
    print(f"{len(data['records'])} -> {len(out['records'])} registros; públicos {len(pub)}; "
          f"mediana {sorted(len(r['text']) for r in pub)[len(pub) // 2]} caracteres")
