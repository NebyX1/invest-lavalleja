"""Generation transport; local retrieval runtimes live in dedicated modules."""
import time
import httpx
from ..errors import DomainError
from .neural import Embeddings
from .vector_store import LanceStore


def thinking_mode(model):
    # Explicit 1017 comparison profile: this revision advertises low via
    # /api/show. Match Beam's effort; keep older DeepSeek profiles unchanged.
    if model in {'deepseek-v4.1-flash:1017','deepseek-v4.1-flash:1017-cloud'}:return 'low'
    # This Cloud model still emitted reasoning with think=False in real tests.
    # Use its default; budget reasoning explicitly instead of claiming it is off.
    if model.startswith('minimax-m3.1-flash'):return None
    # Verified against the Cloud catalogue: this model accepts false and
    # returns its user-facing answer without spending the cap on thought.
    return False if model.startswith('deepseek-v4.1-flash') else 'low'


def task_token_budget(settings,short_cap):
    # MiniMax may consume thousands of tokens before message.content. Never
    # silently increase the operator's cap, but don't shrink it to 400/500.
    if settings.model.startswith('minimax-m3.1-flash'):return settings.max_output_tokens
    return min(settings.max_output_tokens,short_cap)


class _RequestScopedStream(httpx.AsyncByteStream):
    """A response owns its pool and closes it on the loop that used it."""

    def __init__(self,stream,transport):
        self.stream=stream;self.transport=transport;self.closed=False

    async def __aiter__(self):
        try:
            async for chunk in self.stream:yield chunk
        finally:
            await self.aclose()

    async def aclose(self):
        if not self.closed:
            self.closed=True
            try:await self.stream.aclose()
            finally:await self.transport.aclose()


class RequestScopedTransport(httpx.AsyncBaseTransport):
    """Never share asyncio-bound connections between gunicorn threads.

    PydanticAI runs each synchronous call on its own event loop. A shared AsyncClient
    could reuse a connection created on another loop, so every request creates and
    closes its own pool.
    """

    async def handle_async_request(self,request):
        transport=httpx.AsyncHTTPTransport(retries=0)
        try:response=await transport.handle_async_request(request)
        except BaseException:
            await transport.aclose();raise
        response.stream=_RequestScopedStream(response.stream,transport)
        return response

    async def aclose(self):pass


class Ollama:
    def __init__(self,cfg,client=None):
        self.cfg=cfg
        self.client=client or httpx.Client(base_url=cfg.ollama_url,headers={'Authorization':'Bearer '+cfg.ollama_api_key},
              timeout=httpx.Timeout(80,connect=8),limits=httpx.Limits(max_connections=4,max_keepalive_connections=3),follow_redirects=False,trust_env=False)

    def agent_model(self,settings,timeout=80):
        """PydanticAI model over Ollama's OpenAI-compatible endpoint (supports structured output and tools)."""
        if not self.cfg.ollama_api_key or not settings.model:
            raise DomainError('Configurá OLLAMA_API_KEY y seleccioná un modelo en Ajustes.',503,'ollama_not_configured')
        from openai import AsyncOpenAI
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.profiles.openai import OpenAIModelProfile
        from pydantic_ai.providers.openai import OpenAIProvider
        client=AsyncOpenAI(base_url=self.cfg.ollama_url+'/v1',api_key=self.cfg.ollama_api_key,timeout=timeout,max_retries=1,
                           http_client=httpx.AsyncClient(transport=RequestScopedTransport(),trust_env=False))
        # Ollama accepts max_tokens, not the newer max_completion_tokens field.
        return OpenAIChatModel(settings.model,provider=OpenAIProvider(openai_client=client),
                               profile=OpenAIModelProfile(openai_chat_supports_max_completion_tokens=False))

    def models(self):
        if not self.cfg.ollama_api_key:raise DomainError('Falta OLLAMA_API_KEY en .env.',503,'ollama_not_configured')
        try:
            r=self.client.get('/api/tags');r.raise_for_status()
            return sorted({x.get('name',x.get('model','')) for x in r.json().get('models',[]) if x.get('name') or x.get('model')})
        except (httpx.HTTPError,ValueError) as exc:raise DomainError('No se pudo consultar el catálogo de Ollama Cloud.',503,'ollama_unavailable') from exc

    def chat(self,messages,settings,think=None):
        if not self.cfg.ollama_api_key or not settings.model:
            raise DomainError('Configurá OLLAMA_API_KEY y seleccioná un modelo en Ajustes.',503,'ollama_not_configured')
        payload={'model':settings.model,'messages':messages,'stream':False,
                 'options':{'temperature':settings.temperature,'num_predict':settings.max_output_tokens}}
        if think is not None:
            payload['think']=think
        for attempt in range(2):
            try:
                response=self.client.post('/api/chat',json=payload)
                response.raise_for_status(); data=response.json()
                text=data.get('message',{}).get('content','')
                if not isinstance(text,str) or not text.strip():
                    if attempt==0:continue
                    raise ValueError('empty response')
                return text[:18000],{'prompt_tokens':data.get('prompt_eval_count'),'output_tokens':data.get('eval_count')}
            except httpx.HTTPStatusError as exc:
                # Retry only explicit throttling/unavailable responses; do not
                # duplicate a possibly completed generation after a timeout.
                if attempt==0 and exc.response.status_code in {429,503}:
                    time.sleep(0.8)
                    continue
                raise DomainError('El proveedor de respuestas no está disponible. La base de conocimiento no se modificó.',503,'ollama_unavailable') from exc
            except httpx.ConnectError as exc:
                if attempt==0:
                    time.sleep(0.8)
                    continue
                raise DomainError('El proveedor de respuestas no está disponible. La base de conocimiento no se modificó.',503,'ollama_unavailable') from exc
            except (httpx.HTTPError,ValueError) as exc:
                raise DomainError('El proveedor de respuestas no está disponible. La base de conocimiento no se modificó.',503,'ollama_unavailable') from exc
