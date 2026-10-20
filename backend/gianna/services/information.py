"""Task-wording detection only: no topic allowlist or evidence veto."""
import re
from .conversation import fold


def requests_information(text):
    return bool(re.search(r'\b(?:informacion|informame|datos sobre|que (?:dice|menciona|indica|contiene|es)|'
                         r'(?:la|lo|los|las) menciona la guia)\b',fold(text)))
