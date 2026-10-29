"""Agente RAG con herramientas: recuperación inicial garantizada + bucle acotado de búsquedas.

Flujo de cada consulta:
  1. Compuerta de seguridad determinista (insultos, delitos, acusaciones).
  2. Búsqueda híbrida inicial sobre la pregunta (con contexto si es un seguimiento corto).
  3. El modelo ve la evidencia numerada y puede buscar más (`buscar_en_la_guia`) o leer
     una ficha (`ver_ficha`) hasta MAX_STEPS veces.
  4. Se validan las citas [n] contra la evidencia realmente recuperada y se arma la respuesta.
"""
import json
import re
import time
from dataclasses import dataclass, field

from ..domain import ZONES, evidence_label, zone_names
from ..errors import DomainError
from .conversation import fold, is_social
from .prompts import CITATION_NUDGE, FINAL_NUDGE, TOOLS, system_prompt
from .safety import MESSAGES, hard_gate

MAX_STEPS = 4
DEADLINE_SECONDS = 100
MAX_EVIDENCE_CHARS = 36000
CITE = re.compile(r'\[(\d+(?:\s*[,;]\s*\d+)*)\]')
FOLLOWUP_WORDS = 9


@dataclass
class Evidence:
    """Fichas numeradas de una sola respuesta; el mismo registro conserva su número."""
    numbers: dict = field(default_factory=dict)
    cards: dict = field(default_factory=dict)
    conditions: set = field(default_factory=set)
    chars: int = 0

    def number(self, card):
        known = self.numbers.get(card['record_id'])
        if known:
            return known, False
        n = len(self.numbers) + 1
        self.numbers[card['record_id']] = n
        self.cards[n] = card
        return n, True

    def render(self, cards, force=False):
        parts = []
        for card in cards:
            n, new = self.number(card)
            if not new and not force:
                parts.append(f'[{n}] {card["title"]} (ya mostrada arriba)')
                continue
            meta = [f'Tema: {card["topic"]}']
            zones = zone_names(card['zones'])
            if zones and len(zones) < 7:
                meta.append('Zonas: ' + '; '.join(zones))
            elif len(zones) == 7:
                meta.append('Zonas: todo el departamento')
            meta.append('Evidencia: ' + evidence_label(card['evidence_type']))
            if card.get('cutoff_date'):
                meta.append('Corte: ' + str(card['cutoff_date']))
            if card.get('period'):
                meta.append('Período: ' + card['period'])
            block = [f'[{n}] {card["title"]}', ' | '.join(meta), card['text']]
            fresh = [c for c in card['conditions'] if c not in self.conditions]
            self.conditions.update(fresh)
            if fresh:
                block.append('Condiciones y alcance: ' + ' '.join(fresh))
            text = '\n'.join(block)
            self.chars += len(text)
            parts.append(text)
            if self.chars > MAX_EVIDENCE_CHARS:
                break
        return '\n\n'.join(parts) if parts else 'No se encontraron fichas relevantes para esa consulta.'


@dataclass
class Result:
    answer: str
    status: str
    cards: list
    trace: dict
    usage: dict
    requests: int = 0
    retrieved: list = field(default_factory=list)


def _args(call):
    raw = (call.get('function') or {}).get('arguments') or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = {}
    return raw if isinstance(raw, dict) else {}


def humanize(text, titles=None):
    """Red de seguridad: ningún código interno llega a la persona."""
    text = re.sub(r'\s*\((?:Z[1-7]|O(?:0[1-9]|1[0-6])|(?:TS|EN|AG|TR)-\d{3}|s\d{2}-\d{2}(?:-\d{2})?)\)', '', text)
    text = re.sub(r'\b(?:TS|EN|AG|TR)-\d{3}\b', 'la guía', text)
    text = re.sub(r'\bZ([1-7])\b', lambda m: ZONES.get(f'Z{m.group(1)}', m.group(0)), text)
    for code, title in (titles or {}).items():
        text = re.sub(rf'\b{code}\b', title, text)
    return re.sub(r'[ \t]+\n', '\n', text).strip()


class Agent:
    def __init__(self, retriever, ollama):
        self.retriever = retriever
        self.ollama = ollama

    def contextual_query(self, question, history):
        """Un seguimiento corto ("¿y en Varela?") se busca junto con la pregunta anterior."""
        words = len(question.split())
        previous = next((m['content'] for m in reversed(history) if m['role'] == 'user'), '')
        if previous and words <= FOLLOWUP_WORDS:
            return f'{previous[:300]} {question}'
        return question

    def prompt(self, settings, version_id):
        _, outline = self.retriever.outline(version_id)
        return system_prompt(settings, ZONES, outline)

    def run(self, question, settings, history, version_id=None):
        started = time.monotonic()
        gate = hard_gate(question)
        if gate:
            return Result(MESSAGES[gate], gate, [], {'gate': gate}, {})
        social = is_social(question)
        evidence = Evidence()
        trace = {'searches': [], 'steps': 0}
        usage = {'prompt_tokens': 0, 'output_tokens': 0}
        requests = 0
        messages = [{'role': 'system', 'content': self.prompt(settings, version_id)},
                    *({'role': m['role'], 'content': m['content']} for m in history),
                    {'role': 'user', 'content': question}]
        if not social:
            query = self.contextual_query(question, history)
            cards, search_trace = self.retriever.search(query, settings, version_id, limit=settings.retrieval_limit)
            trace['searches'].append(search_trace)
            messages += [
                {'role': 'assistant', 'content': '', 'tool_calls': [
                    {'function': {'name': 'buscar_en_la_guia', 'arguments': {'consulta': query}}}]},
                {'role': 'tool', 'tool_name': 'buscar_en_la_guia', 'content': evidence.render(cards)}]

        answer = ''
        try:
            for step in range(MAX_STEPS):
                remaining = DEADLINE_SECONDS - (time.monotonic() - started)
                final = step == MAX_STEPS - 1 or remaining < 25 or evidence.chars > MAX_EVIDENCE_CHARS
                message, part, model = self.ollama.chat(
                    messages, settings, tools=None if final or social else TOOLS, timeout=max(10, min(75, remaining)))
                requests += 1
                for key in usage:
                    usage[key] += part.get(key) or 0
                trace['steps'] = step + 1
                trace['model'] = model
                calls = message['tool_calls']
                if calls and not final:
                    messages.append({'role': 'assistant', 'content': message['content'], 'tool_calls': calls})
                    for call in calls[:6]:
                        messages.append({'role': 'tool', 'tool_name': call['function']['name'],
                                         'content': self.execute(call, evidence, settings, version_id, trace)})
                    continue
                answer = message['content'].strip()
                if answer:
                    break
                messages.append({'role': 'user', 'content': FINAL_NUDGE})
            if not answer:
                raise DomainError('El proveedor de respuestas no devolvió una respuesta. Volvé a intentar.', 503, 'ollama_unavailable')

            if evidence.cards and len(answer) > 350 and not CITE.search(answer):
                messages += [{'role': 'assistant', 'content': answer}, {'role': 'user', 'content': CITATION_NUDGE}]
                remaining = DEADLINE_SECONDS - (time.monotonic() - started)
                if remaining > 20:
                    message, part, _ = self.ollama.chat(messages, settings, timeout=min(60, remaining))
                    requests += 1
                    for key in usage:
                        usage[key] += part.get(key) or 0
                    repaired = message['content'].strip()
                    # Solo se acepta la reescritura si de verdad quedó respaldada con citas.
                    if CITE.search(repaired):
                        answer = repaired
                    trace['citation_repair'] = True
        except DomainError as exc:
            if exc.code != 'ollama_unavailable' or not evidence.cards:
                raise
            trace['degraded'] = True
            return self.degraded(evidence, trace, usage, requests)

        titles = {card['opportunity_id']: card['title'].split('·', 1)[-1].strip()
                  for card in evidence.cards.values() if card.get('opportunity_id')}
        answer, used = self.finalize(answer, evidence, titles)
        cards = [evidence.cards[n] | {'n': order} for order, n in enumerate(used, 1)]
        trace['retrieved'] = [card['record_id'] for card in evidence.cards.values()]
        trace['cited'] = [card['record_id'] for card in cards]
        if cards:
            status = 'answered'
        elif social or not trace['searches']:
            status = 'conversation'
        else:
            status = 'insufficient_evidence' if re.search(r'no (?:documenta|tiene|hay|cuenta|encontr)', fold(answer)) else 'conversation'
        return Result(answer, status, cards, trace, usage, requests, list(evidence.cards.values()))

    @staticmethod
    def degraded(evidence, trace, usage, requests):
        """Sin modelo disponible, la persona igual recibe las fichas más relacionadas, sin redacción propia."""
        top = list(evidence.cards.values())[:3]
        lines = ['En este momento no puedo redactar una respuesta completa, pero estas son las secciones de la guía más relacionadas con tu consulta:']
        for n, card in enumerate(top, 1):
            lines.append(f'- {card["title"]} [{n}]')
        lines.append('Podés abrir las fuentes para leerlas o volver a preguntar en unos segundos.')
        cards = [card | {'n': n} for n, card in enumerate(top, 1)]
        trace['retrieved'] = [c['record_id'] for c in evidence.cards.values()]
        trace['cited'] = [c['record_id'] for c in cards]
        return Result('\n'.join(lines), 'degraded', cards, trace, usage, requests)

    def execute(self, call, evidence, settings, version_id, trace):
        name = call['function']['name']
        args = _args(call)
        try:
            if name == 'buscar_en_la_guia':
                query = str(args.get('consulta') or '').strip()[:400]
                if not query:
                    return 'Falta el parámetro `consulta`.'
                zones = args.get('zonas') if isinstance(args.get('zonas'), list) else []
                kind = args.get('tipo') if args.get('tipo') in {'oportunidad', 'zona', 'ejemplo', 'ficha'} else None
                cards, search_trace = self.retriever.search(query, settings, version_id, zones=zones,
                                                            kinds=[kind] if kind else None, limit=settings.retrieval_limit)
                trace['searches'].append(search_trace)
                return evidence.render(cards)
            if name == 'ver_ficha':
                refs = args.get('fichas') if isinstance(args.get('fichas'), list) else [args.get('ficha')]
                cards, missing = [], []
                for ref in [str(r).strip().strip('[]') for r in refs if r][:6]:
                    record_id = next((rid for rid, n in evidence.numbers.items() if str(n) == ref), ref)
                    card = self.retriever.get(record_id, version_id)
                    (cards if card else missing).append(card or ref)
                trace['searches'].append({'ver_fichas': [c['record_id'] for c in cards], 'sin_ficha': missing})
                text = evidence.render(cards, force=True) if cards else ''
                if missing:
                    text += '\n\nNo existe una ficha con estos identificadores: ' + ', '.join(missing)
                return text.strip() or 'Indicá al menos un identificador.'
        except DomainError:
            raise
        return f'Herramienta desconocida: {name}.'

    @staticmethod
    def finalize(answer, evidence, titles):
        """Valida las citas contra la evidencia y las renumera 1..n por orden de aparición."""
        order = {}

        def keep(match):
            numbers = [int(x) for x in re.split(r'\s*[,;]\s*', match.group(1))]
            valid = [n for n in numbers if n in evidence.cards]
            for n in valid:
                order.setdefault(n, len(order) + 1)
            return ''.join(f'[{order[n]}]' for n in dict.fromkeys(valid))

        text = CITE.sub(keep, answer)
        return humanize(text, titles), sorted(order, key=order.get)
