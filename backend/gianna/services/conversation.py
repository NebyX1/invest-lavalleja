"""Normalización de texto y detección de cortesías breves."""
import re
import unicodedata

QUICK_SOCIAL = re.compile(
    r'^(?:hola(?: gianna)?(?: como estas| que tal)?|holi|buenas?|buenos dias|buenas tardes|buenas noches|hey|ey|que tal|como estas|'
    r'todo bien|gracias|muchas gracias|chau|adios|hasta luego|quien sos|como te llamas|que podes hacer|en que me podes ayudar|y vos|bien y vos)$')
SOCIAL_WORDS = {
    'hola', 'holi', 'buenas', 'buenos', 'buen', 'dia', 'dias', 'tardes', 'noches', 'hey', 'ey', 'gracias', 'muchas', 'muchisimas',
    'chau', 'adios', 'hasta', 'luego', 'gianna', 'genial', 'perfecto', 'ok', 'okey', 'dale', 'bueno', 'excelente', 'listo',
    'bien', 'todo', 'que', 'tal', 'como', 'estas', 'te', 'va', 'por', 'la', 'ayuda', 'info', 'informacion', 'saludos', 'y', 'vos'}


def fold(value: str) -> str:
    value = ''.join(c for c in unicodedata.normalize('NFKD', value.casefold()) if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', value)).strip()


def is_social(question: str) -> bool:
    """Cortesía pura ("hola, gracias"): no hay nada que buscar en la guía."""
    text = fold(question)
    words = text.split()
    return bool(QUICK_SOCIAL.match(text)) or (0 < len(words) <= 6 and all(w in SOCIAL_WORDS for w in words))
