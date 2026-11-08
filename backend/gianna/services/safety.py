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
    r'servicio\w* sexual\w*|explotac\w* sexual\w*|sexo|sexual\w*|pornograf\w*|erotic\w*)\b.{0,80}'
    r'\b(?:infantil\w*|menor\w*|nin[oa]s?|adolescent\w*|liceal\w*|escolar\w*|chiquilin\w*|gurises|guris\w*|'
    r'menos de 1[0-8]|(?:1[0-7]|[1-9])\s*anos)\b)|'
    r'(?:\b(?:infantil\w*|menor\w*|nin[oa]s?|adolescent\w*|menos de 1[0-8]|(?:1[0-7]|[1-9])\s*anos)\b.{0,80}'
    r'\b(?:prostitu\w*|prostibul\w*|burdel\w*|escort\w*|trabaj\w* sexual\w*|servicio\w* sexual\w*|explotac\w* sexual\w*|pornograf\w*)\b)|'
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
MINORS = re.compile(r'\b(?:menor\w*|adolescent\w*|juvenil\w*|chiquilin\w*|guris\w*|nin[oa]s?|(?:1[0-7]|[1-9])\s*anos|menos de 18|(?:chic[oa]s?|pib[ea]s?|joven\w*|hombres|mujeres|personas|gente)\s+(?:de|desde|hasta)\s+(?:1[0-7]|[1-9])\b)')
SEXUAL_SERVICES = re.compile(r'\b(?:prostitu\w*|prostibul\w*|burdel\w*|escort\w*|servicio\w* sexual\w*|trabaj\w* sexual\w*|explotac\w* sexual\w*|pornograf\w*|encuentros? intim\w*)\b')
NIGHTLIFE = re.compile(r'\b(?:boliche\w*|discoteca\w*|disco|local(?:es)?\s+(?:bailable\w*|nocturn\w*)|fiesta\w*|evento\w*|baile\w*|matine\w*)\b')
FOLLOWUP = re.compile(r'^(?:y\b|e\b|tambien\b|entonces\b|en ese caso\b|en que\b|para (?:eso|ese|esa|menor\w*|adolescent\w*|chic\w*)\b|dame\b|decime\b|busca\w*\b|recom\w*\b|me recom\w*\b|(?:y\s+)?(?:donde|como|cual|que lugar|que condiciones|cuanto)\b)')
NEW_PROJECT = re.compile(r'\b(?:otro proyecto|otra actividad|cambi(?:o|emos) de tema|en cambio|nada que ver|por separado)\b')
ADULTS_ONLY = re.compile(r'\b(?:solo|exclusivamente|todos|unicamente)\s+(?:para\s+)?(?:adultos|mayores de edad|mayores de 18)\b')
FACILITATE = re.compile(r'\b(?:ofrecer|montar|poner|abrir|crear|instalar|vender|invertir|ocultar|evadir|falsificar|conseguir|cometer|explotar|traficar|coaccionar|asesinar|matar|secuestrar|abusar|violar|agredir)\b|\borganiz\w*\s+(?:ese|este|un|el)\s+(?:negocio|proyecto|servicio)\b|\b(?:quiero|necesito)\s+(?:(?:un|el|ese|este)\s+)?(?:negocio|emprendimiento|servicio)\b')
PROTECTIVE = re.compile(r'\b(?:como|donde|quiero|necesito|puedo|para)\s+(?:puedo\s+)?(?:denunciar|prevenir|evitar|impedir|proteger)\b|\b(?:taller|curso|programa|campana|charla)\s+(?:de|sobre)\s+educacion sexual\b|\b(?:informacion|guia|campana)\s+(?:sobre|de)\s+(?:la\s+)?prevencion\b')
PROTECTIVE_SETUP = re.compile(r'\b(?:crear|abrir|montar|organizar)\s+(?:(?:un|una|el|la)\s+)?(?:taller|curso|programa|campana|charla)\b')
COURTESY = re.compile(r'^(?:gracias|muchas gracias|entiendo|ok|de acuerdo|bien)$')


def explicit_minor_exploitation(text):
    minor_age = MINORS.search(text) or re.search(r'\b(?:de|desde|hasta)\s+(?:1[0-7]|[1-9])\b', text)
    return bool(MINOR_EXPLOIT.search(text) or (minor_age and SEXUAL_SERVICES.search(text)))


def protective_request(text):
    return bool(PROTECTIVE.search(text) and not FACILITATE.search(PROTECTIVE_SETUP.sub('', text)))

MESSAGES = {
    'allegation': ('No puedo verificar ni divulgar afirmaciones sobre la vida privada o la conducta de una persona identificable. '
                   'Si te preocupa un posible delito, recurrí a los canales oficiales o a las autoridades competentes; evitá compartir datos personales aquí. '
                   'Puedo ayudarte con consultas sobre inversiones en Lavalleja.'),
    'refuse': ('No puedo ayudar a planificar ni facilitar la explotación o el abuso de menores ni otras actividades que causen daño. '
               'Si se trata de un proyecto diferente y legítimo, describilo y puedo orientar la consulta.'),
    'deescalate': ('Estoy para ayudarte con información sobre inversiones en Lavalleja, pero no voy a responder a insultos. '
                   'Si querés, reformulá la consulta y seguimos.'),
}


def hard_gate(question: str, history=None) -> Action | None:
    text = fold(question)
    if FOLLOWUP.search(text) and not NEW_PROJECT.search(text) and not ADULTS_ONLY.search(text) and not protective_request(text):
        prior_users = [fold(m.get('content', '')) for m in (history or []) if m.get('role') == 'user'][-3:]
        for previous in reversed(prior_users):
            if NEW_PROJECT.search(previous) or ADULTS_ONLY.search(previous) or protective_request(previous):
                break
            if explicit_minor_exploitation(previous) or explicit_minor_exploitation(previous + ' ' + text):
                return 'refuse'
            if not (FOLLOWUP.search(previous) or COURTESY.search(previous)):
                break
    if DIRECT_ALLEGATION.search(text) or ALLEGATION_REQUEST.search(text):
        return 'allegation'
    if not protective_request(text):
        if explicit_minor_exploitation(text) or SEVERE_ILLICIT_TRADE.search(text):
            return 'refuse'
        if (ILLICIT.search(text) or SEXUAL_EXPLOIT.search(text)) and WANT_ACTION.search(text):
            return 'refuse'
    if INSULT.search(text) and (
        re.search(r'\b(?:sos|eres|vos|tu|gianna|chatbot|bot|asistente|no serv\w*)\b', text)
        or len(text.split()) <= 5
    ):
        return 'deescalate'
    return None
