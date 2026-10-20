"""Lossless, reproducible consolidation of the two supplied knowledge inputs.

Does not use an LLM, edit the inputs, read .env, or connect to a running service.
Run with the repository's Python dependencies (python-docx and pydantic).
"""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata
from urllib.parse import urlsplit, urlunsplit

from inspect_inputs import inspect_docx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from gianna.corpus import Corpus, load_corpus

CUTOFF = '2026-10-19'
JSON_NAME = 'Invest_Lavalleja_2026.gianna.json'
DOCX_NAME = 'Conocimiento_Sectorial_Lavalleja_2026_10_19.docx'
INPUT_HASHES = {
    JSON_NAME: 'cc59c1c01b21420c959ed5e48e22ca3486752a4ddd8f421b77c544fae73d58de',
    DOCX_NAME: '1350c64f1dc53921f026289f9401ab4b5cbd68fed55f9e45a66b822c6a30ede8',
}
OUTPUT_NAME = 'Invest_Lavalleja_2026_10_19_consolidado.gianna.json'
EVIDENCE = {
    'Hecho o requisito documentado': 'documented_in_source',
    'Hecho con aplicación o inferencia': 'mixed',
    'Hipótesis de inversión': 'hypothesis',
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def stable_bytes(data):
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def normalized(text):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', text)).strip().casefold()


def url_key(url):
    # Preserve query and fragment: different article/section links are not interchangeable.
    parts = urlsplit(url)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, parts.fragment))


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def parse_sources(blocks):
    entries = []
    for index, block in enumerate(blocks):
        match = re.match(r'^((?:EN|AG|TS|TR)\d{3})  (.+)$', block.get('text', ''))
        if not match:
            continue
        following = blocks[index + 1]
        assert following['text'].startswith('Localizador  '), block['id']
        assert len(block['links']) == 1, block['id']
        locator, date = following['text'][len('Localizador  '):].split('  ·  Consulta ')
        entries.append({
            'id': match[1], 'title': match[2], 'url': block['links'][0],
            'locator': locator, 'accessed_at': date,
            'block_ids': [block['id'], following['id']],
        })
    assert len(entries) == 127
    return entries


def parse_fiches(blocks):
    fiches = []
    for index, block in enumerate(blocks):
        match = re.match(r'^((?:EN|AG|TS|TR)-\d{3})  ·  (.+?)  ·  (.+)$', block.get('text', ''))
        if not match:
            continue
        title, body, condition, reference = blocks[index - 1], blocks[index + 1], blocks[index + 2], blocks[index + 3]
        assert title['style'] == 'Heading 2'
        assert condition['text'].startswith('Condiciones  ')
        assert reference['text'].startswith('Fuentes  ')
        fields = reference['text'][len('Fuentes  '):].split('  ·  ')
        assert len(fields) in (2, 3)
        refs = fields[0].split(', ')
        period = fields[2].removeprefix('Período: ') if len(fields) == 3 else ''
        section = {'EN': 'Energía y ordenamiento territorial', 'AG': 'Agroindustria, forestación y minerales',
                   'TS': 'Turismo, servicios y capacidades', 'TR': 'Agua, industria y nuevas actividades'}[match[1][:2]]
        fiches.append({
            'id': match[1], 'title': title['text'], 'section': section,
            'evidence_type': EVIDENCE[match[2]], 'evidence_label': match[2],
            'zones': re.findall(r'\bZ[1-7]\b', match[3]), 'scope': match[3], 'body': body['text'],
            'condition': condition['text'][len('Condiciones  '):], 'refs': refs,
            'period': period, 'citation_locator': fields[1],
            'blocks': [title['id'], block['id'], body['id'], condition['id'], reference['id']],
        })
    assert Counter(f['id'][:2] for f in fiches) == {'EN': 34, 'AG': 35, 'TS': 34, 'TR': 25}
    assert len({f['id'] for f in fiches}) == 128
    return fiches


def source_union(entries):
    groups = defaultdict(list)
    for source in entries:
        groups[url_key(source['url'])].append(source)
    sources, aliases = [], {}
    for group in groups.values():
        primary = group[0]['id']
        for entry in group:
            aliases[entry['id']] = primary
        locator = ' | '.join(dict.fromkeys(entry['locator'] for entry in group))
        # Full, unshortened locators are preserved in description and conversion report.
        short_locator = locator if len(locator) <= 500 else 'Localizadores completos en descripción; ' + ', '.join(e['id'] for e in group)
        sources.append({
            'id': primary, 'title': group[0]['title'], 'url': group[0]['url'], 'accessed_at': CUTOFF,
            'verification': 'transcribed_from_supplied_docx_not_independently_reverified',
            'locator': short_locator,
            'description': ('Referencia del complemento Word. Consulta declarada por su autor: 2026-10-19; '
                            'no equivale a una comprobación independiente de toda la fuente por el consolidador.\n' +
                            '\n'.join(f"{e['id']}: {e['title']} — {e['locator']}" for e in group)),
        })
    return sources, aliases


def remap_inline(text, aliases):
    # Only source citations in square brackets; never rewrite numbers or legal text.
    def replace(match):
        ids = [part.strip() for part in match[1].split(',')]
        return '[' + ', '.join(dict.fromkeys(aliases.get(part, part) for part in ids)) + ']'
    return re.sub(r'\[((?:(?:EN|AG|TS|TR)\d{3})(?:,\s*(?:EN|AG|TS|TR)\d{3})*)\]', replace, text)


def make_record(fiche, aliases, blocks_by_id):
    conditions = [fiche['condition']]
    scope = 'Ámbito y naturaleza: ' + fiche['scope'] + '; ' + fiche['evidence_label'] + '.'
    text = remap_inline(fiche['body'], aliases)
    # Conditions are also in the retrieval text: chunking embeds text, not conditions[].
    text += '\n\nCondiciones y alcance: ' + fiche['condition']
    text += '\n\n' + scope + '\nCorte documental del complemento: ' + CUTOFF + '.'
    if fiche['period']:
        text += '\nPeríodo de la información: ' + fiche['period'] + '.'
    refs = list(dict.fromkeys(aliases[r] for r in fiche['refs']))
    original = '\n\n'.join(blocks_by_id[b]['text'] for b in fiche['blocks'])
    return {
        'id': fiche['id'], 'title': fiche['title'], 'section': fiche['section'],
        'topic': fiche['section'], 'audience': 'public', 'evidence_type': fiche['evidence_type'],
        'text': text, 'conditions': conditions, 'source_refs': refs, 'zones': fiche['zones'],
        'opportunity_id': None, 'cutoff_date': CUTOFF, 'period': fiche['period'],
        'source_locator': DOCX_NAME + ': DOCX ' + ', '.join(fiche['blocks']) + '; ' + fiche['citation_locator'],
        'original_block_ids': list(fiche['blocks']), 'original_sha256': digest(original.encode('utf-8')), 'enabled': True,
    }


def comparison(old_records, new_records):
    """Transparent lexical comparison for editorial review, NOT evidence validation."""
    stop = set('para como sobre entre desde hasta estas estos esta este fueron pueden puede debe deben ser una unos unas los las del que con por sin sus todo toda todos todas lavalleja inversión inversiones proyecto proyectos'.split())
    def terms(text):
        plain = unicodedata.normalize('NFKD', text.lower()).encode('ascii', 'ignore').decode()
        return {t for t in re.findall(r'[a-z]{4,}', plain) if t not in stop}
    public = [r for r in old_records if r['audience'] == 'public']
    a = {r['id']: terms(r['title'] + ' ' + r['text']) for r in public}
    b = {r['id']: terms(r['title'] + ' ' + r['text']) for r in new_records}
    new_to_old = []
    for record in new_records:
        candidates = sorted(((len(b[record['id']] & a[r['id']]) / max(1, len(b[record['id']] | a[r['id']])), r['id']) for r in public), reverse=True)[:3]
        new_to_old.append({'new_record': record['id'], 'title': record['title'],
                           'closest_old': [{'id': rid, 'jaccard': round(score, 4)} for score, rid in candidates],
                           'decision': 'complementary_not_a_substitute; no automatic semantic deletion'})
    old_to_new = []
    for record in old_records:
        candidates = sorted(((len(a.get(record['id'], set()) & values) / max(1, len(a.get(record['id'], set()) | values)), rid) for rid, values in b.items()), reverse=True)[:3]
        old_to_new.append({'old_record': record['id'], 'audience': record['audience'],
                           'decision': 'preserved_exactly',
                           'closest_new': [{'id': rid, 'jaccard': round(score, 4)} for score, rid in candidates] if record['audience'] == 'public' else []})
    # Rank possible overlaps inside the supplement without removing merely similar topics.
    overlaps = []
    for i, left in enumerate(new_records):
        for right in new_records[i + 1:]:
            x, y = b[left['id']], b[right['id']]
            score = len(x & y) / max(1, len(x | y))
            if score >= 0.30:
                overlaps.append({'records': [left['id'], right['id']], 'jaccard': round(score, 4)})
    return {'method': 'token-set Jaccard; review aid only, not semantic equivalence or truth verification',
            'new_to_old': new_to_old, 'old_to_new': old_to_new,
            'supplement_overlap_candidates': sorted(overlaps, key=lambda item: -item['jaccard'])}


def consolidate(folder, output):
    inputs = {}
    for name, expected in INPUT_HASHES.items():
        path = folder / name
        actual = digest(path.read_bytes())
        if actual != expected:
            raise ValueError(f'Input changed: {name}. Review input hashes and conversion decisions first.')
        inputs[name] = {'sha256': actual, 'bytes': path.stat().st_size}
    old = json.loads((folder / JSON_NAME).read_text(encoding='utf-8-sig'))
    load_corpus(folder / JSON_NAME)
    extracted = inspect_docx(folder / DOCX_NAME)
    blocks = extracted['blocks']; by_id = {b['id']: b for b in blocks}
    entries = parse_sources(blocks); fiches = parse_fiches(blocks)
    new_sources, aliases = source_union(entries)
    assert not set(s['id'] for s in new_sources) & set(s['id'] for s in old['sources'])
    new_records = [make_record(fiche, aliases, by_id) for fiche in fiches]
    fiche_map = {f['id']: f for f in fiches}
    merged = []
    # Editorial consolidation of a demonstrable duplicate event, not a similarity threshold.
    # Both original five-paragraph fiches remain intact in the audit archive.
    first = next(r for r in new_records if r['id'] == 'AG-032')
    second = next(r for r in new_records if r['id'] == 'TS-022')
    first['title'] = 'Plan VALE en Minas: 15 ecopuntos instalados y 60 previstos; servicios y condiciones'
    first['text'] = (
        'El Ministerio de Ambiente informó el 23 de septiembre de 2026 la puesta en funcionamiento de los primeros '
        '15 ecopuntos del Plan VALE en Minas, dentro de un total previsto de 60. Los puntos iniciales incluyen '
        'plazas Libertad y Rivera, UTEC, UTU Central, centros educativos y sectores céntricos y de la rambla. '
        'La cooperación reúne al Ministerio de Ambiente, IDL y Plan VALE, con participación del financiamiento privado, '
        'para clasificación en origen y recuperación de materiales. Es una novedad posterior al corte original del 18/09/2026. '
        'La noticia no acredita que los 60 puntos ya estén operativos.\n\n'
        'Como hipótesis comercial pueden investigarse mantenimiento, medición, educación de usuarios, separación, '
        'trazabilidad, logística y clasificación con los responsables del sistema. La existencia del plan no demuestra '
        'una contratación abierta ni el derecho de cualquier empresa a retirar o comercializar materiales. '
        'Deben confirmarse responsables, acuerdos, titularidad, materiales aceptados, rutas, cantidades efectivamente '
        'recuperadas y destino autorizado. No se proyectan ingresos por reciclables ni se consideran libres corrientes '
        'que puedan estar comprometidas con gestores u organizaciones del programa.\n\n'
        'Condiciones y alcance: 15 confirmados y 60 previstos al 23/09/2026; no confundir etapas. '
        'La oportunidad de servicios es una hipótesis, sin contratos ni disponibilidad libre de materiales acreditados. '
        'Corte documental del complemento: 2026-10-19; no es una inspección del estado de los puntos en esa fecha.'
    )
    first['conditions'] = list(dict.fromkeys(first['conditions'] + second['conditions']))
    first['source_refs'] = list(dict.fromkeys(first['source_refs'] + second['source_refs']))
    first['original_block_ids'] += second['original_block_ids']
    first['source_locator'] = DOCX_NAME + ': DOCX ' + ', '.join(first['original_block_ids'])
    first['original_sha256'] = digest('\n\n'.join(by_id[b]['text'] for b in first['original_block_ids']).encode('utf-8'))
    first['period'] = 'Noticia oficial 23/09/2026; consulta declarada del complemento 19/10/2026; 15 instalados, 60 previstos'
    new_records = [r for r in new_records if r['id'] != 'TS-022']
    merged.append({'from': ['AG-032', 'TS-022'], 'to': 'AG-032',
                   'reason': 'Same official event and URL; one record preserves both sets of details and limitations.'})
    targets = {f['id']: ('AG-032' if f['id'] == 'TS-022' else f['id']) for f in fiches}
    coverage = {}
    def account(ids, category, record_ids=None):
        for bid in ids:
            assert bid not in coverage, bid
            coverage[bid] = {'category': category, 'record_ids': record_ids or []}
    for fiche in fiches:
        account(fiche['blocks'], 'knowledge_fiche', [targets[fiche['id']]])
    for source in entries:
        account(source['block_ids'], 'source_metadata', [aliases[source['id']]])

    # The territorial table has unique cross-sector context; preserve rows with headings.
    territory = by_id['t003']; header = territory['rows'][0]['cells']
    for row in territory['rows'][1:]:
        cells = row['cells']; zone = re.search(r'Z[1-7]', cells[0])[0]
        cited = re.findall(r'\b(?:EN|AG|TS|TR)-\d{3}\b', cells[-1])
        # Expand the only explicit fiche ranges in the table instead of losing intervening sources.
        for prefix, start, end in re.findall(r'\b(EN|AG|TS|TR)-(\d{3})\s+a\s+\1-(\d{3})', cells[-1]):
            cited += [f'{prefix}-{n:03}' for n in range(int(start), int(end) + 1)]
        refs = list(dict.fromkeys(aliases[s] for rid in cited for s in fiche_map[rid]['refs']))
        text = '\n'.join(f'{label}: {value}' for label, value in zip(header, cells))
        text += '\n\nZ1–Z7 son agrupaciones comerciales de la guía, no categorías de suelo ni polígonos legales. '
        text += 'Las líneas a evaluar son hipótesis; los antecedentes no acreditan suelo disponible, demanda ni conexión. '
        text += 'Corte documental del complemento: 2026-10-19.'
        record = {'id': 'territorio-20261019-' + zone.lower(), 'title': 'Antecedentes y actividades a evaluar: ' + cells[0].replace('\n', ' · '),
                  'section': 'Lectura territorial del complemento', 'topic': 'Territorio y actividades sectoriales',
                  'audience': 'public', 'evidence_type': 'mixed', 'text': text,
                  'conditions': [by_id['p0018']['text']], 'source_refs': refs, 'zones': [zone],
                  'cutoff_date': CUTOFF, 'period': 'Síntesis del complemento al 19/10/2026; antecedentes con sus fechas propias',
                  'source_locator': DOCX_NAME + ': tabla ' + row['id'] + ', encabezados t003.r00; contexto p0018',
                  'original_block_ids': ['t003.r00', row['id'], 'p0018'],
                  'original_sha256': digest(stable_bytes(row)), 'enabled': True}
        new_records.append(record)
    account(['t003', 'p0018'], 'territorial_table_and_scope', [r['id'] for r in new_records if r['id'].startswith('territorio-')])

    # Non-fiche geographic and parcel information is substantive, not disposable front matter.
    for rid, title, ids, refs, evidence in [
        ('ambitos-geograficos-20261019', 'Ubicaciones específicas, cuencas y límites de las zonas comerciales', ['p0020', 'p0021', 'p0022'], ['AG007', 'AG008', 'AG004', 'EN026', 'EN023'], 'mixed'),
        ('consulta-predial-20261019', 'Datos necesarios para consultar sobre un predio de Lavalleja', ['p0023', 'p0024'], ['EN001', 'EN002', 'EN003', 'EN006', 'EN008', 'EN009', 'AG002', 'AG023', 'TR001'], 'mixed'),
    ]:
        text = '\n\n'.join(by_id[bid]['text'] for bid in ids if by_id[bid].get('style') != 'Heading 2')
        text += '\n\nCorte documental: 2026-10-19. Zonas comerciales, cuencas y delimitaciones legales no son equivalentes.'
        new_records.append({'id': rid, 'title': title, 'section': 'Lectura territorial del complemento', 'topic': 'Localización y alcance territorial',
                            'audience': 'public', 'evidence_type': evidence, 'text': text,
                            'conditions': ['No acredita habilitación ni disponibilidad de un predio.'],
                            'source_refs': list(dict.fromkeys(aliases[r] for r in refs)), 'zones': [], 'cutoff_date': CUTOFF,
                            'source_locator': DOCX_NAME + ': DOCX ' + ', '.join(ids), 'original_block_ids': ids,
                            'original_sha256': digest('\n\n'.join(by_id[b]['text'] for b in ids).encode('utf-8')), 'enabled': True})
        account(ids, 'non_fiche_substantive_knowledge', [rid])
    for block in blocks:
        if block['id'] not in coverage:
            account([block['id']], 'admin_archive_only: document_summary_navigation_diagnosis_or_methodology')
    assert set(coverage) == set(by_id)
    assert all(r.get('audience') == 'public' for r in new_records)
    records = deepcopy(old['records']) + new_records
    compare = comparison(old['records'], new_records)
    report = {
        'profile': 'invest-lavalleja-union-2026-10-19-v1', 'inputs': inputs,
        'original_document': old['document'], 'original_conversion_report': old['conversion_report'],
        'policy': {'original_records': 'all 271 preserved byte-for-byte as JSON values, including dates, IDs, audience and text',
                   'new_records': 'public candidates, all require editorial approval; no live import/index/activation performed',
                   'truth_verification': 'targeted external checks recorded separately; not exhaustive factual or legal certification',
                   'source_dates': 'supplement accessed_at is its author-declared date, not blanket independent reverification',
                   'token_policy': 'backend performs exact Bekko tokenization; no estimates substituted for runtime token counts',
                   'privacy': '75 original internal records retained; never promote to public or include in public index',
                   'page_policy': 'DOCX paragraph/table locators, not invented page numbers',
                   'agent_behavior': 'knowledge data only; no routing changes, fixed replies, topic vetoes or model changes'},
        'counts': {'original_records': len(old['records']), 'original_public': 196, 'original_internal': 75,
                   'supplement_fiches': len(fiches), 'consolidated_supplement_fiches': len(fiches) - 1,
                   'supplement_context_records': 9, 'new_records': len(new_records), 'total_records': len(records),
                   'public_records': sum(r['audience'] == 'public' for r in records), 'internal_records': 75,
                   'original_sources': len(old['sources']), 'supplement_source_entries': len(entries),
                   'supplement_unique_sources': len(new_sources), 'total_sources': len(old['sources']) + len(new_sources)},
        'source_aliases': aliases, 'supplement_source_entries': entries, 'fiche_to_record': targets,
        'record_merges': merged, 'block_coverage': coverage, 'unaccounted_block_ids': [],
        # Admin-only conversion metadata; never embedded by the public indexing job.
        'supplement_archive': extracted,
        'comparison': compare,
        'reconciliation': [
            {'kind': 'complement', 'old': ['O09', 's17-01-04', 's32-04-01'], 'new': ['EN-001', 'EN-017', 'EN-020', 'EN-023', 'EN-024', 'EN-026'],
             'decision': 'Efficiency and general cautions do not cover all generation technologies. Added concrete sector records, not fixed answers.'},
            {'kind': 'legal_scope', 'old': ['s12-04-01', 's16-03-01', 's16-04-01'], 'new': ['EN-003', 'EN-004', 'TS-001', 'TR-024'],
             'decision': 'Complement, no established contradiction: commercial zones are not plan/SNAP boundaries; prohibitions have a specific footprint.'},
            {'kind': 'temporal', 'old': ['s29-01-04', 'O10'], 'new': ['TR-003', 'TR-004', 'TS-004', 'TS-034'],
             'decision': 'Keep national water transition and local sanitation conditions together, not as interchangeable permissions.'},
            {'kind': 'temporal', 'old': ['s30-01-01', 's31-04-01'], 'new': ['TR-022', 'TR-023'],
             'decision': 'Original already includes 329/025 and 152/026. New timing details complement it; expired transition is not reopened.'},
            {'kind': 'historical_vs_operational', 'old': ['s15-05-01'], 'new': ['TS-027', 'TS-028'],
             'decision': 'Inventory and 2025 restrictions do not certify commercial rail availability in October 2026.'},
            {'kind': 'review_required', 'new': ['EN-005', 'TS-025', 'EN-031', 'EN-032', 'TS-016', 'TS-018', 'AG-028'],
             'decision': 'Plan status, calls, admission windows and label deadlines need current checks before publication; preserve their cutoff.'},
        ],
    }
    payload = {'schema_version': 'gianna.corpus.v1',
               'document': {'id': 'invest-lavalleja-consolidado-2026-10-19',
                            'title': 'Invest Lavalleja · Base consolidada de conocimiento · 19 de octubre de 2026',
                            'filename': OUTPUT_NAME, 'sha256': digest(stable_bytes(inputs)), 'cutoff_date': CUTOFF,
                            'conversion_note': 'Unión de la guía con corte 18/09/2026 y complemento sectorial 19/10/2026. '
                            'Los registros anteriores mantienen sus fechas y no se recertifican. 128 fichas nuevas se consolidan en 127, '
                            'con 9 registros adicionales de contexto territorial. Fuentes, condiciones, bloques originales y audiencias '
                            'se conservan. Huella de documento: SHA-256 del manifiesto de las dos entradas; la huella del archivo final '
                            'se entrega en manifiesto externo para evitar autorreferencia. Borrador pendiente de aprobación editorial; '
                            'ninguna importación, indexación o activación en la base de servicio.'},
               'sources': deepcopy(old['sources']) + new_sources, 'records': records, 'conversion_report': report}
    validated = Corpus.model_validate(payload)
    output.mkdir(parents=True, exist_ok=True)
    path = output / OUTPUT_NAME
    write_json(path, payload)
    assert load_corpus(path).model_dump() == validated.model_dump()
    # Assert the existing objects are preserved, not reconstructed from summaries.
    assert payload['records'][:len(old['records'])] == old['records']
    assert payload['sources'][:len(old['sources'])] == old['sources']
    write_json(output / 'comparacion-y-trazabilidad.json', report)
    manifest = {'corpus': {'filename': path.name, 'sha256': digest(path.read_bytes()), 'bytes': path.stat().st_size},
                'inputs': inputs, 'counts': report['counts'], 'active_knowledge_changed': False,
                'status': 'validated_schema; pending isolated backend and tokenizer tests; editorial approval required'}
    write_json(output / 'manifest.json', manifest)
    print(json.dumps(manifest, ensure_ascii=True))
    return payload


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path, default=ROOT / 'better-rag')
    parser.add_argument('--output', type=Path, default=ROOT / 'better-rag' / 'consolidated')
    args = parser.parse_args()
    consolidate(args.folder.resolve(), args.output.resolve())
