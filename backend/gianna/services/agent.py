"""Safety, pre-evidence intent, hybrid retrieval and source-bound reviewed answers.

Read-only discovery and the shared neural reranker stay in the information flow.
Only a structurally valid and semantically reviewed plan becomes an answer.
"""
import json
import re
import time
from dataclasses import dataclass, field

from ..domain import ZONES, zone_names
from ..errors import DomainError
from .conversation import is_social
from .prompts import system_prompt
from .safety import MESSAGES, hard_gate
from .risk import assess as assess_risk
from .reranking import RerankBudget

DEADLINE_SECONDS = 100
MAX_EVIDENCE_CHARS = 36000
CITE = re.compile(r'\[(\d+(?:\s*[,;]\s*\d+)*)\]')
FOLLOWUP_WORDS = 9
SOURCE_NATURE = {
    'documented_in_source': 'Datos o requisitos de la fuente',
    'hypothesis': 'Propuestas de actividad',
    'mixed': 'Antecedentes y propuestas',
    'didactic_example': 'Ejemplo con supuestos explícitos',
    'institutional_proposal': 'Propuesta institucional',
    'reference': 'Referencia documental',
}


@dataclass
class Evidence:
    """Fichas numeradas de una sola respuesta; el mismo registro conserva su número."""
    numbers: dict = field(default_factory=dict)
    cards: dict = field(default_factory=dict)
    presented: dict = field(default_factory=dict)
    documentary_presented: set = field(default_factory=set)
    chars: int = 0

    def number(self, card):
        known = self.numbers.get(card['record_id'])
        if known:
            return known, False
        n = len(self.numbers) + 1
        self.numbers[card['record_id']] = n
        self.cards[n] = card
        return n, True

    def render(self, cards, force=False, *, documentary=False, methodology=False):
        parts = []
        for card in cards:
            n, new = self.number(card)
            if not new and not force:
                parts.append(f'[{n}] {card["title"]} (ya mostrada arriba)')
                continue
            meta = [f'Tema: {card["topic"]}']
            view = card.get('information_view')
            if documentary and (methodology or not view or view['kind'] != 'methodology'):
                view = None
            if not view:
                zones = zone_names(card['zones'])
                if zones and len(zones) < 7:
                    meta.append('Zonas: ' + '; '.join(zones))
                elif len(zones) == 7:
                    meta.append('Zonas: todo el departamento')
            meta.append('Naturaleza: ' + SOURCE_NATURE.get(card['evidence_type'], card['evidence_type']))
            if card.get('cutoff_date'):
                meta.append('Corte: ' + str(card['cutoff_date']))
            if card.get('period'):
                meta.append('Período: ' + card['period'])
            if view:
                body = view['text'] or ('Este registro contiene metodología del documento, sin enunciados descriptivos. '
                                        'Su texto íntegro se conserva para consultas sobre esa metodología.')
                block = [f'[{n}] {card["title"]}', ' | '.join(meta), body]
            else:
                original = card.get('documentary') if documentary else None
                body = original['text'] if original else card['text']
                conditions = original['conditions'] if original else card['conditions']
                block = [f'[{n}] {card["title"]}', ' | '.join(meta), body]
                # Scope belongs to each source, including a forced reread; a
                # condition shown under another card must not silently vanish.
                if conditions:
                    block.append('Condiciones y alcance de esta ficha: ' + ' '.join(conditions))
            text = '\n'.join(block)
            if self.chars + len(text) > MAX_EVIDENCE_CHARS:
                continue
            if not view and original:
                self.cards[n] = card | {'text':body,'conditions':conditions}
            # The final writer receives only source content actually exposed to
            # research, never hidden originals or tool-control instructions.
            if (not view or view['text'].strip()) and (n not in self.documentary_presented or not view):
                self.presented[n] = text
                if not view:
                    self.documentary_presented.add(n)
            if view:
                text += ('\nLectura: vista informativa. Para un dato o procedimiento que esta vista no detalle, '
                         'ver_ficha admite vista="documental" con el texto y las condiciones originales.')
            self.chars += len(text)
            parts.append(text)
            if self.chars > MAX_EVIDENCE_CHARS:
                break
        return '\n\n'.join(parts) if parts else 'No se encontraron fichas relevantes para esa consulta.'

    def for_writing(self):
        return '\n\n'.join(self.presented[n] for n in sorted(self.presented))


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

    def assess(self, question, settings, history):
        gate = hard_gate(question, history)
        if gate:
            return Result(MESSAGES[gate], gate, [], {'gate': gate, 'safety':{
                'policy':'semantic-safety-v1', 'source':'hard_block', 'decision':gate,
                'model_evaluated':False, 'requests':0}}, {})
        assessment = assess_risk(self.ollama, question, history, settings)
        if assessment.decision != 'allow':
            return Result(assessment.message(), assessment.decision, [],
                          {'gate':assessment.decision, 'safety':assessment.trace()},
                          assessment.usage, assessment.requests)
        return assessment

    def run(self, question, settings, history, version_id=None, *, assessment=None):
        assessment = assessment if assessment is not None else self.assess(question, settings, history)
        if isinstance(assessment, Result):
            return assessment
        started = assessment.started
        return self.inform(question, settings, history, version_id, assessment, started)

    def inform(self, question, settings, history, version_id, assessment, started):
        from .information import respond
        evidence = Evidence()
        trace = {'searches': [], 'steps': 0, 'safety': assessment.trace(),
                 'writing_policy': 'source-bound-information-v1'}
        usage = {key: assessment.usage.get(key) or 0 for key in ('prompt_tokens', 'output_tokens')}
        budget = (RerankBudget(timeout_ms=settings.rerank_budget_ms)
                  if settings.rerank_mode == 'bounded' else None)
        try:
            answer, requests = respond(self, question, settings, history, version_id,
                                      evidence, trace, usage, started, budget)
        except DomainError as exc:
            if exc.code not in {'ollama_unavailable', 'answer_not_verified'} or not evidence.presented:
                raise
            trace['degraded'] = True
            trace['writing_error'] = exc.code
            return self.degraded(evidence, trace, usage, trace.get('model_requests', assessment.requests))
        titles = {card['opportunity_id']: card['title'].split('·', 1)[-1].strip()
                  for card in evidence.cards.values() if card.get('opportunity_id')}
        answer, used = self.finalize(answer, evidence, titles)
        cards = [evidence.cards[n] | {'n': order} for order, n in enumerate(used, 1)]
        trace['retrieved'] = [card['record_id'] for card in evidence.cards.values()]
        trace['cited'] = [card['record_id'] for card in cards]
        status = 'answered' if cards else 'conversation' if is_social(question) else 'insufficient_evidence'
        return Result(answer, status, cards, trace, usage, requests, list(evidence.cards.values()))

    @staticmethod
    def degraded(evidence, trace, usage, requests):
        """Sin modelo disponible, la persona igual recibe las fichas más relacionadas, sin redacción propia."""
        top = [evidence.cards[n] for n in sorted(evidence.presented)][:3]
        lines = ['En este momento no puedo redactar una respuesta completa, pero estas son las secciones de la guía más relacionadas con tu consulta:']
        for n, card in enumerate(top, 1):
            lines.append(f'- {card["title"]} [{n}]')
        cards = [card | {'n': n} for n, card in enumerate(top, 1)]
        trace['retrieved'] = [c['record_id'] for c in evidence.cards.values()]
        trace['cited'] = [c['record_id'] for c in cards]
        return Result('\n'.join(lines), 'degraded', cards, trace, usage, requests)

    def execute(self, call, evidence, settings, version_id, trace, *, rerank_budget=None,
                documentary_allowed=False, methodology_allowed=False):
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
                                                            kinds=[kind] if kind else None, limit=settings.retrieval_limit,
                                                            rerank_budget=rerank_budget)
                trace['searches'].append(search_trace)
                return evidence.render(cards)
            if name == 'ver_ficha':
                refs = args.get('fichas') if isinstance(args.get('fichas'), list) else [args.get('ficha')]
                cards, missing = [], []
                for ref in [str(r).strip().strip('[]') for r in refs if r][:6]:
                    record_id = next((rid for rid, n in evidence.numbers.items() if str(n) == ref), ref)
                    card = self.retriever.get(record_id, version_id)
                    (cards if card else missing).append(card or ref)
                requested_detail = args.get('vista') == 'documental'
                documentary = requested_detail and documentary_allowed
                original_ids = [c['record_id'] for c in cards if documentary and (methodology_allowed or
                                (c.get('information_view') or {}).get('kind') != 'methodology')]
                trace['searches'].append({'ver_fichas': [c['record_id'] for c in cards], 'sin_ficha': missing,
                                         'vista': ('documental' if len(original_ids) == len(cards) and original_ids else
                                                   'mixta' if original_ids else 'informativa'),
                                         'detail_requested': requested_detail, 'documental_ids': original_ids})
                text = evidence.render(cards, force=True, documentary=documentary,
                                       methodology=methodology_allowed) if cards else ''
                if requested_detail and not documentary_allowed:
                    text = ('Se entrega la vista informativa correspondiente al alcance registrado. '
                            'La declaración de alcance es un control interno, no una aclaración que deba pedirse al usuario.\n\n' + text)
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
