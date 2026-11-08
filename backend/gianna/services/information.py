"""Bounded information flow; unverified prose is never a knowledge answer.

Intent is fixed before evidence. Read-only research remains available, followed
by source-bound composition and per-statement review. Failed plans are rewritten
as a whole, never trimmed by sentence or routed by business/place keywords.
"""
import json
import time

from ..errors import DomainError
from .answer_contract import (
    Intent, AnswerPlan, Review, InvalidContract, INTENT_TOOL, ANSWER_TOOL, REVIEW_TOOL,
    INTENT_POLICY, ANSWER_POLICY, REVIEW_POLICY, parse, validate_plan,
    review_payload, accepted, render,
)
from .conversation import is_social
from .prompts import TOOLS, SAFETY_RULES, INFORMATION_STYLE, guide_map

MAX_RESEARCH_STEPS = 1
MAX_PLANS = 3
DEADLINE_SECONDS = 100
READ_TOOLS = [t for t in TOOLS if t['function']['name'] in {'buscar_en_la_guia', 'ver_ficha'}]


def respond(agent, question, settings, history, version_id, evidence, trace, usage, started, budget):
    requests = trace['model_requests'] = trace['safety'].get('requests', 0)

    def chat(policy, payload, tools=None, *, max_tokens=None):
        nonlocal requests
        remaining = DEADLINE_SECONDS - (time.monotonic() - started)
        if remaining < 5:
            raise DomainError('Se agotó el tiempo para procesar la consulta.', 503, 'ollama_unavailable')
        messages = [{'role': 'system', 'content': policy},
                    {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False, allow_nan=False)}]
        message, part, model = agent.ollama.chat(messages, settings, tools=tools,
                                                max_tokens=max_tokens, timeout=min(60, remaining))
        requests += 1
        trace['model_requests'] = requests
        trace['model'] = model
        for key in usage:
            usage[key] += part.get(key) or 0
        return message

    if is_social(question):
        message = chat(SAFETY_RULES + '\n' + INFORMATION_STYLE +
                       '\nSos Gianna de Invest Lavalleja. Respondé brevemente al saludo o agradecimiento.',
                       {'question': question, 'history': history})
        if not (message.get('content') or '').strip():
            raise DomainError('No se obtuvo una respuesta.', 503, 'ollama_unavailable')
        return message['content'].strip(), requests

    # Neither the outline nor source text is available to this stage.
    intent = None
    for _ in range(2):
        message = chat(INTENT_POLICY, {'question': question, 'history': history}, [INTENT_TOOL], max_tokens=1200)
        try:
            intent = parse(message, 'interpretar_pedido', Intent)
            break
        except InvalidContract as exc:
            trace.setdefault('writing_rejections', []).append({'phase': 'intent', 'code': exc.code})
    if intent is None:
        raise DomainError('No se pudo procesar el pedido. Volvé a intentar.', 503, 'answer_not_verified')
    # Only controlled labels enter analytics; no questions, plans or quotes.
    trace['intent_kinds'] = [ask.kind for ask in intent.asks]
    precise = any(a.kind in {'fact', 'procedure', 'methodology'} for a in intent.asks)
    methodology = any(a.kind == 'methodology' for a in intent.asks)
    cards, search_trace = agent.retriever.search(intent.query, settings, version_id,
                                               limit=settings.retrieval_limit, rerank_budget=budget)
    trace['searches'].append(search_trace)
    evidence.render(cards)
    if precise:
        evidence.render(cards, force=True, documentary=True, methodology=methodology)

    _, outline = agent.retriever.outline(version_id)
    # Discovery gets the public title map as data; writing/review do not.
    research = 0
    plans = 0
    feedback = None
    previous = None
    tool_results = []
    while plans < MAX_PLANS:
        remaining = DEADLINE_SECONDS - (time.monotonic() - started)
        discovery = research < MAX_RESEARCH_STEPS and evidence.chars < 36000 and remaining > 30 and feedback is None
        payload = {'question': question, 'history': history, 'intent': intent.model_dump(),
                   'evidence_text': evidence.for_writing()}
        policy = SAFETY_RULES + '\n' + ANSWER_POLICY
        if settings.persona:
            policy = 'TONO ADICIONAL (solo estilo):\n' + settings.persona + '\n\n' + policy
        if discovery:
            payload['source_index'] = guide_map(outline)
            payload['read_results'] = tool_results
            policy += ('\nAntes de redactar, si falta evidencia pertinente, podés usar buscar_en_la_guia o ver_ficha. '
                       'source_index solo contiene títulos para descubrir documentos, no es evidencia. '
                       'No hagas búsquedas de asesoría que nadie pidió. Si ya hay información suficiente, '
                       'usá redactar_informacion. Nunca entregues una respuesta en prosa fuera del contrato.')
        if feedback:
            payload.update(previous_attempt=previous, correction=feedback)
            policy += '\nEl intento anterior fue RECHAZADO: corregí todos los criterios fallidos y entregá un plan nuevo.'
        message = chat(policy, payload, [ANSWER_TOOL, *READ_TOOLS] if discovery else [ANSWER_TOOL])
        calls = message.get('tool_calls') or []
        if discovery and calls and all(c.get('function', {}).get('name') in
                                       {'buscar_en_la_guia', 'ver_ficha'} for c in calls):
            tool_results = []
            for i, call in enumerate(calls):
                if i >= 6:
                    tool_results.append('No ejecutada: límite de seis herramientas por paso.')
                    continue
                tool_results.append(agent.execute(call, evidence, settings, version_id, trace,
                                                   rerank_budget=budget, documentary_allowed=precise,
                                                   methodology_allowed=methodology))
            research += 1
            trace['steps'] = research
            continue
        plans += 1
        previous = message
        try:
            plan = validate_plan(parse(message, 'redactar_informacion', AnswerPlan), intent, evidence.presented)
            review_message = chat(SAFETY_RULES + '\n' + REVIEW_POLICY,
                                  review_payload(plan, intent, evidence.presented, question, history), [REVIEW_TOOL], max_tokens=2400)
            review = parse(review_message, 'comprobar_afirmaciones', Review)
            if accepted(review, plan, intent):
                trace['writing_verified'] = True
                trace['writing_plans'] = plans
                trace['writing_statements'] = len(plan.statements)
                return render(plan), requests
            feedback = {'review': review.model_dump()}
            trace.setdefault('writing_rejections', []).append({'phase': 'review', 'code': 'semantic_rejection'})
        except InvalidContract as exc:
            feedback = {'structural_error': exc.code, **exc.location}
            trace.setdefault('writing_rejections', []).append({'phase': 'contract', 'code': exc.code})
    raise DomainError('No se pudo verificar una respuesta. Volvé a intentar.', 503, 'answer_not_verified')
