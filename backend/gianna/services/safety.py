"""Deterministic safety gates.  The model never decides these routes.

These checks are intentionally narrow: they stop explicit allegations, insults
and requests to facilitate serious crimes before retrieval.  They do not
classify legitimate but sensitive economic activities as illegal.
"""
import re

from .conversation import fold

Action = str

DIRECT_ALLEGATION = re.compile(r'\b(?:funcionari[ao]s?|emplead[ao]s?|intendente|intendenta|alcalde|alcaldesa|director[ao]?|edil(?:es)?|persona|vecin[ao]s?|senor[ao]s?|mujer|hombre)\s+(?:(?:que|de|la|el|un|una)\s+){0,2}(?:(?:es|era|esta|fue)\s+(?:(?:un|una)\s+)?(?:prostitut\w*|corrup\w*|acusad\w*|violador\w*|delincu\w*|narcotrafic\w*)|(?:rob\w*|estaf\w*|abus\w*))\b')
ALLEGATION_REQUEST = re.compile(
    r'\b(?:rumor|rumores|dicen que|se dice que|corre la voz|difundir|difundir un rumor|'
    r'acusar|denunciar a|sospecha sobre)\b.{0,90}\b(?:alguien|persona|funcionario|intendente|'
    r'vecino|empresario|conocido|familiar|candidato)\b'
)
INSULT = re.compile(
    r'\b(?:estupid\w*|idiota\w*|imbecil\w*|inutil\w*|basura|mierda|pelotud\w*|bolud\w*|tarad\w*|mogolic\w*|'
    r'put[oa]s?|hdp|hijo de puta|hija de puta|la concha|forr[oa]s?|gil\w*|cornud\w*|pajer\w*|chupala|andate a cagar|no serv\w*)\b'
)
ILLICIT = re.compile(r'\b(?:evadir|falsificar|sobornar|coimear|hackear|robar|estafar|amenazar|agredir|matar|asesinar|secuestrar|extorsionar|acosar|atacar|golpear|lastimar)\b')
SEXUAL_EXPLOIT = re.compile(r'\b(?:explotar|traficar|coaccionar|trata)\b.{0,35}\b(?:sexual\w*|persona\w*|mujer\w*|menor\w*|nin\w*|infantil\w*|adolescent\w*)\b')
MINOR_EXPLOIT = re.compile(
    r'(?:\b(?:prostitu\w*|prostibul\w*|burdel\w*|escort\w*|acompanant\w*|trabaj\w* sexual\w*|'
    r'servicio\w* sexual\w*|explotac\w* sexual\w*|sexo|sexual\w*|pornograf\w*|erotic\w*|chicas?|chicos?|pibas?|pibes?|jovenes)\b.{0,80}'
    r'\b(?:infantil\w*|menor\w*|nin[oa]s?|adolescent\w*|liceal\w*|escolar\w*|chiquilin\w*|gurises|guris\w*|'
    r'menos de 1[0-8]|(?:1[0-7]|[1-9])\s*anos)\b)|'
    r'(?:\b(?:infantil\w*|menor\w*|nin[oa]s?|adolescent\w*|menos de 1[0-8]|(?:1[0-7]|[1-9])\s*anos)\b.{0,80}'
    r'\b(?:prostitu\w*|prostibul\w*|burdel\w*|escort\w*|trabaj\w* sexual\w*|servicio\w* sexual\w*|explotac\w* sexual\w*|pornograf\w*|negocio\w*|emprendimient\w*)\b)|'
    r'\b(?:pedofil\w*|pederast\w*|abuso infantil|trabajo infantil)\b'
)
SEVERE_ILLICIT_TRADE = re.compile(
    r'\b(?:narcotrafic\w*|narco\w*|trafic\w* de (?:drogas?|armas?|personas?|organos?|menores|estupefacientes)|'
    r'trata de (?:personas?|blancas|mujeres|menores)|lavado de (?:activos|dinero)|blanqueo de capitales|testaferr\w*|'
    r'contraband\w*|sicari\w*|clandestin\w* de (?:drogas?|armas?|juegos?|apuestas?))\b|'
    r'\b(?:vender|venta|comercializar|producir|fabricar|distribuir|traficar|invertir|negocio|emprendimiento|instalar|poner|abrir|montar)\b'
    r'.{0,60}\b(?:cocaina|pasta base|marihuana ilegal|heroina|metanfetamina\w*|fentanilo|extasis|lsd|drogas?(?:\s+ilegales?|s?\s+ilicitas?)?|'
    r'estupefacientes|narco\w*|armas?(?:\s+ilegales?|\s+de\s+fuego\s+sin|\s+clandestin\w*|\s+de\s+guerra)?|municion\w*\s+ilegal\w*|explosivos?)\b|'
    r'\b(?:cocaina|pasta base|heroina|metanfetamina\w*|fentanilo|drogas?\s+ilegales?|armas?\s+ilegales?|armas?\s+clandestin\w*)\b'
)
WANT_ACTION = re.compile(r'\b(?:como|quiero|necesito|ayudame|ensen\w*|explica\w*|pasos|puedo|voy a|estoy por|invertir|poner|abrir|montar|crear|instalar|emprend\w*|negocio|proyecto)\b')

MESSAGES = {
    'allegation': ('No puedo verificar ni divulgar afirmaciones sobre la vida privada o la conducta de una persona identificable. '
                   'Si te preocupa un posible delito, recurrí a los canales oficiales o a las autoridades competentes; evitá compartir datos personales aquí. '
                   'Puedo ayudarte con consultas sobre inversiones en Lavalleja.'),
    'refuse': ('Esa actividad es ilegal y constituye un delito grave. No asisto, asesoro ni brindo orientación bajo ningún concepto sobre explotación de menores, '
               'narcotráfico, tráfico de armas, trata de personas, lavado de activos ni ninguna otra actividad ilícita. '
               'Este canal está destinado exclusivamente a proyectos de inversión legítimos en Lavalleja.'),
    'deescalate': ('Estoy para ayudarte con información sobre inversiones en Lavalleja, pero no voy a responder a insultos. '
                   'Si querés, reformulá la consulta y seguimos.'),
}


def hard_gate(question: str) -> Action | None:
    text = fold(question)
    if DIRECT_ALLEGATION.search(text) or ALLEGATION_REQUEST.search(text):
        return 'allegation'
    if not re.search(r'\bdenunci\w*\b', text):
        if MINOR_EXPLOIT.search(text) or SEVERE_ILLICIT_TRADE.search(text):
            return 'refuse'
        if (ILLICIT.search(text) or SEXUAL_EXPLOIT.search(text)) and WANT_ACTION.search(text):
            return 'refuse'
    if INSULT.search(text) and (
        re.search(r'\b(?:sos|eres|vos|tu|gianna|chatbot|bot|asistente|no serv\w*)\b', text)
        or len(text.split()) <= 5
    ):
        return 'deescalate'
    return None
