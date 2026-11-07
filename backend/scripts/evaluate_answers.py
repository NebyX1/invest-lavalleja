#!/usr/bin/env python3
"""Batería de conversaciones contra el agente real (llama a Ollama: consume cuota).

Uso: python scripts/evaluate_answers.py [--version ID] [--only nombre ...] [--report RUTA.md]

Controles automáticos por turno (no sustituyen la lectura humana del informe):
  - recuperó / citó alguna de las fichas esperadas
  - sin códigos internos (Z1, O05, TS-011...) ni jerga de implementación
  - cada cifra de la respuesta aparece en la evidencia recuperada (anti-alucinación numérica)
  - longitud, estado esperado, frases obligatorias/prohibidas
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

import local_env

BACKEND = local_env.prepare()

from gianna.config import Config
from gianna.db import Database
from gianna.security import Security
from gianna.services.conversation import fold
from gianna.services.context_budget import retain_history
from gianna.services.knowledge import Knowledge
from gianna.services.rag import RAG
from gianna.services.runtime import Embeddings, LanceStore, Ollama
from gianna.services.settings import get_settings

CODES = re.compile(r'\b(?:Z[1-7]|O(?:0[1-9]|1[0-6])|(?:TS|EN|AG|TR)-\d{3}|s\d{2}-\d{2})\b')
JARGON = re.compile(r'\b(?:base de datos|herramienta|RAG|embedding|endpoint)\b', re.I)
NUMBER = re.compile(r'\d[\d.,]*')


def matches(record_id, expected):
    return record_id == expected or expected.startswith(record_id + '-')


def numbers(text):
    found = set()
    for raw in NUMBER.findall(text):
        digits = re.sub(r'[.,]', '', raw.rstrip('.,'))
        if digits and len(digits) >= 2:
            found.add(digits)
    return found


def check(case, result, answer_text, evidence_text):
    problems = []
    retrieved = [c['record_id'] for c in result['retrieved']]
    cited = [c['record_id'] for c in result['citations']]
    if case.get('retrieved_any') and not any(matches(r, e) for r in retrieved for e in case['retrieved_any']):
        problems.append(f'no recuperó {case["retrieved_any"]}: {retrieved[:8]}')
    if case.get('cites_any') and not any(matches(r, e) for r in cited for e in case['cites_any']):
        problems.append(f'no citó {case["cites_any"]}: {cited}')
    if CODES.search(answer_text):
        problems.append('código interno visible: ' + CODES.search(answer_text).group(0))
    if JARGON.search(answer_text):
        problems.append('jerga: ' + JARGON.search(answer_text).group(0))
    known = numbers(evidence_text)
    stripped = re.sub(r'\d{1,2}/\d{1,2}/\d{2,4}', '', re.sub(r'\[\d+\]', '', answer_text))
    ungrounded = sorted(n for n in numbers(stripped)
                        if not any(k.startswith(n.rstrip('0') or n) for k in known) and n not in {'2026', '2025'})
    if ungrounded and result['status'] not in {'conversation', 'refuse', 'deescalate', 'allegation'}:
        problems.append('cifras sin respaldo en la evidencia: ' + ', '.join(ungrounded[:6]))
    if case.get('forbid_numbers') and re.search(r'\bretorno (?:anual )?de\s+\d|\brentabilidad (?:anual )?de\s+\d|\bROI\b', answer_text, re.I):
        problems.append('cifra de rentabilidad inventada')
    if case.get('status_any') and result['status'] not in case['status_any']:
        problems.append(f'estado {result["status"]} no está en {case["status_any"]}')
    if case.get('must_say_any') and not any(fold(p) in fold(answer_text) for p in case['must_say_any']):
        problems.append(f'falta alguna de {case["must_say_any"]}')
    for phrase in case.get('forbid_text', []):
        if phrase.lower() in answer_text.lower():
            problems.append('texto prohibido: ' + phrase)
    words = len(answer_text.split())
    if words > case.get('max_words', 330):
        problems.append(f'demasiado larga: {words} palabras')
    return problems


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version')
    parser.add_argument('--only', nargs='*')
    parser.add_argument('--cases', type=Path, default=BACKEND / 'evals' / 'dialogues.json')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    cfg = Config.from_env()
    db = Database(cfg.database_target)
    knowledge = Knowledge(db, cfg)
    embeddings = Embeddings(cfg)
    rag = RAG(db, cfg, knowledge, embeddings, LanceStore(cfg), Ollama(cfg), Security(db, cfg))
    settings = get_settings(db, cfg)
    version = rag.retriever.version(args.version)
    embeddings.for_profile(json.loads(version['profile_json'])).load()
    cases = [c for c in json.loads(args.cases.read_text(encoding='utf-8')) if not args.only or c['name'] in args.only]
    report, failures, total_s = [], 0, 0.0
    for case in cases:
        history = []
        for turn_index, question in enumerate(case['turns']):
            started = time.time()
            agent_result = rag.agent.run(question, settings, history, version['id'])
            elapsed = time.time() - started
            total_s += elapsed
            result = {'status': agent_result.status, 'retrieved': agent_result.retrieved,
                      'citations': agent_result.cards}
            evidence = question + ' ' + ' '.join(m['content'] for m in history) + '\n' + '\n'.join(
                c['text'] + ' ' + ' '.join(c['conditions']) + ' ' + c['title'] for c in agent_result.retrieved)
            last = turn_index == len(case['turns']) - 1
            problems = check(case, result, agent_result.answer, evidence) if last else []
            failures += bool(problems)
            flag = 'FALLA' if problems else 'ok'
            print(f'[{flag}] {case["name"]}#{turn_index + 1} {elapsed:.1f}s {agent_result.status} llamadas={agent_result.requests} '
                  f'citas={len(agent_result.cards)} palabras={len(agent_result.answer.split())}', flush=True)
            for problem in problems:
                print('      -', problem, flush=True)
            report.append(f'### {case["name"]} · turno {turn_index + 1} · {flag}\n\n**Pregunta:** {question}\n\n{agent_result.answer}\n\n'
                          f'_Fuentes: {" | ".join(c["title"] for c in agent_result.cards) or "ninguna"}_ · {elapsed:.1f}s · {agent_result.status}\n'
                          + ''.join(f'\n- ⚠ {p}' for p in problems) + '\n')
            history = retain_history(history + [{'role': 'user', 'content': question},
                                                {'role': 'assistant', 'content': agent_result.answer}])
    print(f'\n{len(cases) - failures if failures <= len(cases) else 0}/{len(cases)} casos sin observaciones automáticas · {total_s / max(1, len(cases)):.1f}s promedio por caso')
    if args.report:
        args.report.write_text('# Informe de conversaciones\n\n' + '\n'.join(report), encoding='utf-8')


if __name__ == '__main__':
    main()
