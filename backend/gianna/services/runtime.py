"""Transporte hacia Ollama Cloud (API nativa con herramientas) y re-exportación de los motores locales."""
import logging
import time

import httpx

from ..errors import DomainError
from .neural import Embeddings
from .vector_store import LanceStore

LOG = logging.getLogger(__name__)
UNAVAILABLE = 'El proveedor de respuestas no está disponible en este momento. Volvé a intentar en unos segundos.'
RETRYABLE = {408, 409, 425, 429, 500, 502, 503, 504}


def thinking_mode(model):
    """Valor de ``think`` verificado contra el catálogo de Ollama Cloud para cada familia."""
    if model.startswith('deepseek-v4.1-flash:1017'):
        return 'low'
    if model.startswith('deepseek-v4.1-flash'):
        return False
    if model.startswith('minimax-m3.1-flash'):
        return None
    return 'low'


class Ollama:
    def __init__(self, cfg, client=None):
        self.cfg = cfg
        self.client = client or httpx.Client(
            base_url=cfg.ollama_url, headers={'Authorization': 'Bearer ' + cfg.ollama_api_key},
            timeout=httpx.Timeout(75, connect=8), limits=httpx.Limits(max_connections=6, max_keepalive_connections=4),
            follow_redirects=False, trust_env=False)

    def models(self):
        if not self.cfg.ollama_api_key:
            raise DomainError('Falta OLLAMA_API_KEY en .env.', 503, 'ollama_not_configured')
        try:
            response = self.client.get('/api/tags')
            response.raise_for_status()
            return sorted({x.get('name', x.get('model', '')) for x in response.json().get('models', []) if x.get('name') or x.get('model')})
        except (httpx.HTTPError, ValueError) as exc:
            raise DomainError('No se pudo consultar el catálogo de Ollama Cloud.', 503, 'ollama_unavailable') from exc

    def candidates(self, settings):
        """Modelo elegido y, si falla, alternativas verificadas del mismo proveedor (sin repetir)."""
        order = [settings.model, *self.cfg.ollama_fallback_models]
        return [m for i, m in enumerate(order) if m and m not in order[:i]]

    def chat(self, messages, settings, *, tools=None, max_tokens=None, model=None, think='auto', timeout=75):
        """Una respuesta del modelo. Devuelve (message, usage, model_usado).

        Reintenta con espera creciente ante límites, caídas de red o respuestas vacías y,
        si el modelo elegido sigue fallando, prueba el siguiente de la lista de alternativas.
        """
        if not self.cfg.ollama_api_key or not settings.model:
            raise DomainError('Configurá OLLAMA_API_KEY y seleccioná un modelo en Ajustes.', 503, 'ollama_not_configured')
        last_error = None
        deadline = time.monotonic() + timeout
        for name in ([model] if model else self.candidates(settings)):
            for attempt in range(3):
                remaining = deadline - time.monotonic()
                if remaining < 5:
                    raise DomainError(UNAVAILABLE, 503, 'ollama_unavailable') from last_error
                try:
                    return self._once(name, messages, settings, tools, max_tokens, think, remaining) + (name,)
                except _Retry as exc:
                    last_error = exc
                    LOG.warning('Ollama %s intento %s: %s', name, attempt + 1, exc)
                    time.sleep((0.7, 1.8)[attempt] if attempt < 2 else 0)
                except _Fatal as exc:
                    last_error = exc
                    LOG.warning('Ollama %s rechazó la solicitud: %s', name, exc)
                    break
        raise DomainError(UNAVAILABLE, 503, 'ollama_unavailable') from last_error

    def _once(self, model, messages, settings, tools, max_tokens, think, timeout):
        payload = {'model': model, 'messages': messages, 'stream': False,
                   'options': {'temperature': settings.temperature, 'num_predict': max_tokens or settings.max_output_tokens}}
        if tools:
            payload['tools'] = tools
        mode = thinking_mode(model) if think == 'auto' else think
        if mode is not None:
            payload['think'] = mode
        limit = httpx.Timeout(timeout, connect=8)
        try:
            response = self.client.post('/api/chat', json=payload, timeout=limit)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise _Retry(type(exc).__name__) from exc
        if response.status_code == 400 and 'think' in payload and 'think' in response.text.lower():
            payload.pop('think')
            try:
                response = self.client.post('/api/chat', json=payload, timeout=limit)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                raise _Retry(type(exc).__name__) from exc
        if response.status_code in RETRYABLE:
            raise _Retry(f'HTTP {response.status_code}')
        if response.status_code >= 400:
            raise _Fatal(f'HTTP {response.status_code}: {response.text[:200]}')
        try:
            data = response.json()
        except ValueError as exc:
            raise _Retry('respuesta no JSON') from exc
        message = data.get('message') or {}
        content = message.get('content') or ''
        calls = message.get('tool_calls') or []
        if not content.strip() and not calls:
            raise _Retry('respuesta vacía')
        usage = {'prompt_tokens': data.get('prompt_eval_count'), 'output_tokens': data.get('eval_count')}
        return {'content': content, 'tool_calls': calls}, usage


class _Retry(Exception):
    pass


class _Fatal(Exception):
    pass
