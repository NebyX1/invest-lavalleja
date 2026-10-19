"""Deterministic public-domain catalogue used to bridge natural language and corpus IDs.

This module never turns aliases into documentary evidence.  It only resolves a
user expression to the zone IDs already carried by approved records.  Answers
must still cite the immutable version records selected by the RAG pipeline.
"""
from dataclasses import dataclass
from difflib import get_close_matches
import re
from .conversation import fold


@dataclass(frozen=True)
class Zone:
    id: str
    name: str
    aliases: tuple[str, ...]
    themes: tuple[str, ...] = ()


# Names come from the seven public zone records in the canonical 2026 corpus.
# ``norte`` is an explicit retrieval alias for Z5/Z6.  The territorial wording
# was checked against the Intendencia's public note about the railway serving
# José Batlle y Ordóñez, José Pedro Varela and Zapicán.  This alias is routing
# metadata only: it is never inserted into source text or exposed as evidence.
ZONES = (
    Zone('Z1', 'Minas y entorno', ('minas',), ('industria', 'tecnologia', 'servicios')),
    Zone('Z2', 'Solís de Mataojo–Aguas Blancas', ('solis de mataojo', 'aguas blancas'), ('alimentos', 'industria')),
    Zone('Z3', 'Villa Serrana–Marco de los Reyes–Penitente', ('villa serrana', 'marco de los reyes', 'penitente'), ('turismo', 'hospitalidad')),
    Zone('Z4', 'Mariscala–Pirarajá', ('mariscala', 'piraraja'), ('madera', 'rural')),
    Zone('Z5', 'José Pedro Varela y entorno', ('jose pedro varela', 'varela', 'norte'), ('arroz', 'granos', 'poscosecha', 'calidad', 'eficiencia')),
    Zone('Z6', 'José Batlle y Ordóñez–Zapicán', ('jose batlle y ordonez', 'batlle y ordonez', 'batlle', 'zapican', 'norte'), ('servicios', 'ganaderos', 'reparacion', 'mantenimiento', 'rural', 'oficios')),
    Zone('Z7', 'Arequita–Polanco–Barriga Negra', ('arequita', 'polanco', 'barriga negra'), ('turismo', 'rural', 'alimentos')),
)
ZONE_BY_ID = {zone.id: zone for zone in ZONES}
VALID_OPPORTUNITY = re.compile(r'^O(?:0[1-9]|1[0-6])$')
DOMAIN_WORDS = re.compile(
    r'\b(?:invert\w*|inversion\w*|oportunidad\w*|negocio\w*|proyecto\w*|empresa\w*|'
    r'actividad\w*|instalar\w*|emprend\w*|permiso\w*|habilit\w*|requisit\w*|'
    r'rentab\w*|terreno\w*|galpon\w*|sector\w*|zona\w*|localidad\w*|comerci\w*|local\w*|'
    r'hotel\w*|hostel\w*|hostal\w*|hospedaj\w*|posada\w*|caban\w*|alojamient\w*|camping\w*|glamping\w*|estancia\w*|chacra\w*|'
    r'restaur\w*|parador\w*|bar|bares|cafe|cafeteria\w*|panader\w*|cervecer\w*|gastronom\w*|turism\w*|'
    r'planta\w*|fabric\w*|taller\w*|bodega\w*|vined\w*|agro\w*|ganad\w*|forest\w*|mader\w*|logisti\w*|frigorific\w*)\b'
)
EXPLORE_WORDS = re.compile(
    r'\b(?:oportunidad\w*|idea\w*|opcion\w*|alternativa\w*|explor\w*|que (?:puedo|podria)|'
    r'donde\b|en que (?:lugar|zona|localidad|parte)|que (?:lugar|zona|localidad)\b|recomiend\w*|recomend\w*|conviene\w*|negocio\w*)\b'
)
LOCATION_SEEKING_WORDS = re.compile(
    r'\b(?:donde\b|en que (?:lugar|zona|localidad|parte)|que (?:lugar|zona|localidad)\b|recomiend\w*|recomend\w*|conviene\w*|ubic\w*)\b'
)
REQUIREMENT_WORDS = re.compile(r'\b(?:permiso\w*|habilit\w*|requisit\w*|condicion\w*|verificar|revisar|antes de|abrir|instalar|poner|montar)\b')
FOLLOWUP_WORDS = re.compile(r'^(?:y\b|que tal\b|como seria\b|cuales son\b|donde queda\b|en esa zona\b|para eso\b|en ese caso\b|sobre eso\b)')
SECTOR_OPPORTUNITIES = (
    (
        re.compile(r'\b(?:gastronom\w*|parador\w*|restaur\w*|bar|bares|cafe|cafeteria\w*|panader\w*|cervecer\w*|bodega\w*|vined\w*|comida\w*|bebida\w*|alimento\w*|alimentari\w*|frio|conservac\w*)\b'),
        ('O07', 'O02', 'O05'),
        ('s11-01-01', 's12-01-01', 's16-02-01', 's09-01-02', 's26-01-01'),
    ),
    (
        re.compile(r'\b(?:turism\w*|turistic\w*|hospitalidad|hotel\w*|hostel\w*|hostal\w*|hospedaj\w*|posada\w*|caban\w*|alojamient\w*|camping\w*|glamping\w*|estancia\w*|chacra\w*|visitant\w*|experiencia\w*|geoturism\w*|serran\w*)\b'),
        ('O05', 'O06', 'O15'),
        ('s12-01-01', 's12-04-01', 's16-02-01', 's10-01-01'),
    ),
    (
        re.compile(r'\b(?:mader\w*|forest\w*|aserrad\w*|carpinter\w*|mueble\w*)\b'),
        ('O04',),
        ('s13-01-01', 's13-02-01', 's09-01-02'),
    ),
    (
        re.compile(r'\b(?:arroz\w*|grano\w*|poscosecha|silo\w*|acopio)\b'),
        ('O03',),
        ('s14-01-01', 's14-02-01'),
    ),
    (
        re.compile(r'\b(?:ganad\w*|agro\w*|rural\w*|campo|maquinaria)\b'),
        ('O12', 'O03', 'O07'),
        ('s15-01-01', 's13-01-01', 's16-01-01'),
    ),
    (
        re.compile(r'\b(?:industri\w*|automatiz\w*|mantenimient\w*|planta\w*|fabrica\w*)\b'),
        ('O01', 'O09', 'O13'),
        ('s10-01-01', 's11-01-01', 's14-01-01'),
    ),
    (
        re.compile(r'\b(?:software|digital\w*|tecnolog\w*|datos|sistema\w*|informatic\w*)\b'),
        ('O08',),
        ('s10-01-01', 's10-02-01'),
    ),
    (
        re.compile(r'\b(?:energi\w*|electric\w*|eficiencia|solar|termic\w*)\b'),
        ('O09',),
        ('s09-01-02', 's09-01-03', 's09-01-06'),
    ),
    (
        re.compile(r'\b(?:agua\w*|efluent\w*|saneamient\w*|residuo\w*|recicl\w*|circular\w*|subproduct\w*)\b'),
        ('O10', 'O11'),
        ('s09-01-02', 's09-01-03', 's09-01-04', 's09-01-06'),
    ),
    (
        re.compile(r'\b(?:educac\w*|capacitac\w*|formativ\w*)\b'),
        ('O14',),
        ('s10-01-01', 's12-01-01', 's16-02-01'),
    ),
    (
        re.compile(r'\b(?:taller\w*|galpon\w*|modular\w*|parque industrial)\b'),
        ('O13',),
        ('s10-01-01', 's10-05-01'),
    ),
)
STOPWORDS = {
    'para','como','cual','cuales','donde','desde','hasta','sobre','entre','quiero','puedo','podria',
    'deberia','lavalleja','invertir','inversion','inversiones','oportunidad','oportunidades','proyecto',
    'negocio','negocios','con','del','las','los','una','uno','que','por','sus','esta','este','hay',
    'abrir','poner','instalar','montar','crear','hacer','tener',
}


TYPO_GENERIC_TOKENS = {'pedro', 'jose', 'aguas', 'blancas', 'marco', 'reyes', 'negra', 'barriga', 'villa', 'batlle'}
TYPO_VOCABULARY = tuple(sorted({
    *(token for zone in ZONES for alias in zone.aliases for token in fold(alias).split()
      if len(token) >= 5 and token not in TYPO_GENERIC_TOKENS),
    'norte', 'lavalleja', 'invertir', 'inversion', 'inversiones', 'oportunidades', 'recomendame', 'recomiendas',
    'hostel', 'hospedaje', 'alojamiento', 'parador', 'restaurante', 'turismo', 'gastronomia', 'localidad',
    'cabanas', 'posada', 'emprendimiento', 'rubro', 'madera', 'forestal', 'ganaderia', 'industria', 'tecnologia',
}))


def correct_typos(text: str) -> str:
    """Fix small typos in zone/sector words so a slip like "norprte" cannot drop the territorial scope."""
    def fix(match: re.Match) -> str:
        word = match.group()
        folded = fold(word)
        if len(folded) < 5 or folded in TYPO_VOCABULARY or DOMAIN_WORDS.fullmatch(folded):
            return word
        close = [v for v in get_close_matches(folded, TYPO_VOCABULARY, n=1, cutoff=0.82)
                 if v[0] == folded[0] and abs(len(v) - len(folded)) <= 2]
        return close[0] if close else word
    return re.sub(r'[^\W\d_]+', fix, text)


def resolve_zones(text: str) -> tuple[str, ...]:
    normalized = fold(correct_typos(text))
    found = []
    for zone in ZONES:
        if re.search(rf'\b{zone.id.casefold()}\b', normalized) or any(
            re.search(rf'\b{re.escape(fold(alias))}\b', normalized) for alias in zone.aliases
        ):
            found.append(zone.id)
    return tuple(found)


def resolve_opportunities(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(match.upper() for match in re.findall(r'\bO(?:0[1-9]|1[0-6])\b', text, re.I)))


def zone_names(ids) -> list[str]:
    return [ZONE_BY_ID[zone_id].name for zone_id in ids if zone_id in ZONE_BY_ID]


def is_domain_query(text: str) -> bool:
    normalized = fold(correct_typos(text))
    return bool(DOMAIN_WORDS.search(normalized) or resolve_zones(normalized) or resolve_opportunities(text))


def record_type(record: dict) -> str:
    if record.get('opportunity_id'):
        return 'opportunity'
    title = fold(record.get('title', ''))
    if title.startswith('siete zonas siete preguntas de inversion z'):
        return 'zone_profile'
    if re.search(r'\b(?:permiso|habilitacion|requisito|condicion|antes de invertir)\b', fold(record.get('text', ''))):
        return 'requirement'
    return 'fact'


def retrieval_context(record: dict) -> str:
    zones = record.get('zones') or []
    clean_title = re.sub(r'^(?:O(?:0[1-9]|1[0-6])\s*·\s*|Siete zonas\.\s*Siete preguntas de inversión\.\s*·\s*Z[1-7]\s*·\s*)', '', record.get('title', '')).strip()
    parts = [f"Título: {clean_title or record.get('title', '')}"]
    if record.get('section') and record['section'] != record.get('title') and not re.fullmatch(r'O\d{2}[–-]O\d{2}', record['section']):
        parts.append(f"Sección: {record['section']}")
    parts.append(f"Tema: {record.get('topic', 'General')}")
    if zones:
        labels = '; '.join(ZONE_BY_ID[zone_id].name for zone_id in zones if zone_id in ZONE_BY_ID)
        parts.append(f'Zonas de referencia: {labels}')
    parts.append(f'Tipo de registro: {record_type(record)}')
    return '\n'.join(parts)


def significant_terms(text: str) -> set[str]:
    return {term for term in fold(text).split() if len(term) > 3 and term not in STOPWORDS}


def rank_catalog_records(records: list[dict], zones: tuple[str, ...], opportunity_ids: tuple[str, ...],
                         question: str, explore: bool, limit: int = 5) -> list[str]:
    """Return exact snapshot record IDs, keeping opportunity/zone diversity."""
    by_id = {record['id']: record for record in records}
    if opportunity_ids:
        exact = [record_id for record_id in opportunity_ids if record_id in by_id]
    else:
        exact = []
    profiles = []
    for zone_id in zones:
        candidates = [r for r in records if record_type(r) == 'zone_profile' and zone_id in (r.get('zones') or [])]
        if candidates:
            profiles.append(sorted(candidates, key=lambda r: r['id'])[0]['id'])
    normalized_question = fold(question)
    query_terms = significant_terms(question)
    wants_location = bool(LOCATION_SEEKING_WORDS.search(normalized_question))
    sector_matches = []
    territorial_matches = []
    for pattern, oids, tids in SECTOR_OPPORTUNITIES:
        if pattern.search(normalized_question):
            for oid in oids:
                if oid in by_id and oid not in sector_matches:
                    sector_matches.append(oid)
            for tid in tids:
                if tid in by_id and tid not in territorial_matches:
                    territorial_matches.append(tid)
    opportunities = [r for r in records if record_type(r) == 'opportunity'
                     and (not zones or set(zones) & set(r.get('zones') or []))]

    def opportunity_score(record: dict, zone_id: str | None = None):
        terms = significant_terms(record.get('title', '') + ' ' + record.get('text', ''))
        theme_terms = set()
        for rid in (record.get('zones') or []):
            if rid in ZONE_BY_ID and (not zone_id or rid == zone_id):
                theme_terms.update(ZONE_BY_ID[rid].themes)
        sector_bonus = 20 if record['id'] in sector_matches else 0
        return (sector_bonus + len(query_terms & terms) * 4 + len(theme_terms & terms) * 2,
                -len(record.get('zones') or []), record['id'])

    picked = list(exact)
    if zones or opportunity_ids:
        # First preserve territorial diversity: one best opportunity for every
        # resolved zone, then fill remaining slots by relevance.
        for zone_id in zones:
            candidates = [r for r in opportunities if zone_id in (r.get('zones') or []) and r['id'] not in picked]
            if candidates:
                picked.append(max(candidates, key=lambda r: opportunity_score(r, zone_id))['id'])
        for record in sorted(opportunities, key=opportunity_score, reverse=True):
            if record['id'] not in picked:
                picked.append(record['id'])
            if len(picked) >= max(1, limit - len(profiles)):
                break
    elif sector_matches:
        # Sector-specific query without explicit zone: include matching sector
        # opportunities plus territorial/zone records for the relevant localities
        # so the assistant can compare concrete places and their advantages.
        for oid in sector_matches[:2]:
            if oid not in picked:
                picked.append(oid)
        max_territorial = 3 if (wants_location or explore) else 2
        for tid in territorial_matches[:max_territorial]:
            if tid not in picked:
                picked.append(tid)
    elif explore or wants_location:
        # Open-ended exploration without zone or sector: give the model the
        # profile of every zone so it can compare concrete places and theses.
        all_profiles = sorted((r['id'] for r in records if record_type(r) == 'zone_profile'))
        for zp_id in all_profiles:
            if zp_id not in picked:
                picked.append(zp_id)
    ordered = picked + [record_id for record_id in profiles if record_id not in picked]
    return ordered[:limit]


def expanded_query(question: str, zones: tuple[str, ...], opportunity_ids: tuple[str, ...]) -> str:
    additions = []
    normalized = fold(question)
    if re.search(r'\b(?:gastronom\w*|parador\w*|restaur\w*|bar|bares|cafe|cafeteria\w*|panader\w*|cervecer\w*|bodega\w*|vined\w*|comida\w*|alimento\w*)\b', normalized):
        additions.append('Temas relacionados: alimentos, hospitalidad, turismo, Solís de Mataojo, Villa Serrana, Penitente, Arequita, Minas, habilitación bromatológica RUNAEV, uso de suelo y padrón.')
    elif re.search(r'\b(?:hotel\w*|hostel\w*|hostal\w*|hospedaj\w*|posada\w*|caban\w*|alojamient\w*|camping\w*|glamping\w*|estancia\w*|chacra\w*|turism\w*)\b', normalized):
        additions.append('Temas relacionados: hospitalidad serrana, Villa Serrana, Marco de los Reyes, Penitente, Arequita, Polanco, Barriga Negra, Minas, turismo, operadores, uso de suelo por padrón, agua, saneamiento y bomberos.')
    if zones:
        additions.append('Zonas: ' + '; '.join(ZONE_BY_ID[z].name for z in zones if z in ZONE_BY_ID))
    if opportunity_ids:
        additions.append('Fichas: ' + ', '.join(opportunity_ids))
    return question if not additions else question + '\n' + '\n'.join(additions)


def humanize_answer_codes(text: str) -> str:
    """Replace internal catalogue codes (Z1..Z7, O01..O16) in user-facing prose."""
    result = text
    for zone in ZONES:
        # "Zona Z3 (Villa Serrana...)" or "Z1 · Minas y entorno" -> "Villa Serrana..." / "Minas y entorno"
        result = re.sub(
            rf'\b(?:[Zz]ona\s+)?{zone.id}\s*(?:[·—–:-]\s*|\(\s*){re.escape(zone.name)}\)?',
            zone.name,
            result,
        )
        # Standalone "Zona Z1" or "Z1" -> "la zona de Minas y entorno" / "Minas y entorno"
        result = re.sub(rf'\b[Zz]ona\s+{zone.id}\b', f'la zona de {zone.name}', result)
        result = re.sub(rf'\b{zone.id}\b', zone.name, result)
    # "ficha O05 · Hospitalidad..." or "O07 · Alimentos..." -> "Hospitalidad..." / "Alimentos..."
    result = re.sub(r'\b(?:la\s+)?ficha\s+O(?:0[1-9]|1[0-6])\s*[·—–:-]\s*', 'la línea de ', result, flags=re.I)
    result = re.sub(r'\bO(?:0[1-9]|1[0-6])\s*[·—–:-]\s*', '', result)
    # Parenthetical "(O05)" or "(ficha O05)" -> removed
    result = re.sub(r'\s*\((?:ficha\s+)?O(?:0[1-9]|1[0-6])\)', '', result, flags=re.I)
    # Standalone "la ficha O05" or "O05" -> "esa línea de oportunidad"
    result = re.sub(r'\b(?:la\s+)?ficha\s+O(?:0[1-9]|1[0-6])\b', 'esa línea de oportunidad', result, flags=re.I)
    result = re.sub(r'\bO(?:0[1-9]|1[0-6])\b', 'esa oportunidad', result)
    return re.sub(r' {2,}', ' ', result)
