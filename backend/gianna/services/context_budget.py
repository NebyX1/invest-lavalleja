"""Historial conversacional acotado por tamaño. Sin tokenizador: el español rinde ~3,5 caracteres por token."""
import re

HISTORY_CHARS = 14000
MESSAGE_CHARS = 3500
CITATION_MARK = re.compile(r'\s*\[\d+(?:\s*[,;–-]\s*\d+)*\]')


def clean_message(message):
    """Un turno guardable: sin marcas [n] (su numeración solo vale dentro de esa respuesta)."""
    text = CITATION_MARK.sub('', message['content']).strip()
    return {**message, 'content': text[:MESSAGE_CHARS]}


def retain_history(messages, model='', model_dir=None, max_chars=HISTORY_CHARS):
    kept = []
    used = 0
    for message in reversed(messages[-256:]):
        if message.get('role') not in {'user', 'assistant'} or not isinstance(message.get('content'), str):
            continue
        item = clean_message(message)
        if used + len(item['content']) > max_chars:
            break
        kept.append({key: item[key] for key in ('role', 'content', 'mode') if key in item})
        used += len(item['content'])
    kept.reverse()
    while kept and kept[0]['role'] != 'user':
        kept.pop(0)
    return kept
