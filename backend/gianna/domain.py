"""Vocabulario mínimo del corpus: zonas comerciales Z1-Z7, oportunidades O01-O16 y etiquetas de evidencia.

No contiene reglas de decisión. Solo traduce los códigos que ya trae cada registro
(``zones``, ``opportunity_id``, ``evidence_type``) a nombres legibles para el
índice y para el prompt del agente.
"""
import re

ZONES = {
    'Z1': 'Minas y entorno',
    'Z2': 'Solís de Mataojo–Aguas Blancas',
    'Z3': 'Villa Serrana–Marco de los Reyes–Penitente',
    'Z4': 'Mariscala–Pirarajá',
    'Z5': 'José Pedro Varela y entorno',
    'Z6': 'José Batlle y Ordóñez–Zapicán',
    'Z7': 'Arequita–Polanco–Barriga Negra',
}
ZONE_ID = re.compile(r'^Z[1-7]$')
OPPORTUNITY_ID = re.compile(r'^O(?:0[1-9]|1[0-6])$')

EVIDENCE_LABELS = {
    'documented_in_source': 'dato o requisito documentado en la fuente',
    'hypothesis': 'hipótesis a validar (no es un hecho comprobado)',
    'mixed': 'mezcla de dato documentado y propuesta de la guía',
    'didactic_example': 'ejemplo didáctico con supuestos (no son datos observados)',
    'institutional_proposal': 'propuesta institucional',
    'reference': 'referencia',
}


def zone_names(ids):
    return [ZONES[zone] for zone in ids if zone in ZONES]


def zone_label(zone_id):
    return f'{zone_id} · {ZONES[zone_id]}' if zone_id in ZONES else zone_id


def evidence_label(value):
    return EVIDENCE_LABELS.get(value, value or '')


def record_kind(record):
    """Tipo grueso, solo para filtros y etiquetas. Deriva de los campos del propio registro."""
    if record.get('opportunity_id') and OPPORTUNITY_ID.match(record['opportunity_id']):
        return 'oportunidad'
    record_id = record.get('id', '')
    if record_id.startswith('territorio-') or record.get('topic') in {'TERRITORIO'}:
        return 'zona'
    if record.get('evidence_type') == 'didactic_example':
        return 'ejemplo'
    return 'ficha'
