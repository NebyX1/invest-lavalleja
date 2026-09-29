import { useEffect, useId, useRef, useState, type KeyboardEvent, type SyntheticEvent } from 'react';

type Source = { id: string; title: string; url: string };
type Citation = { id: string; title: string; excerpt: string; cutoff_date: string | null; evidence_type?: string; locator?: string; sources: Source[] };
type Reply = { id: string; answer: string; citations: Citation[]; status: string; notice: string };
type Exchange = { question: string; reply: Reply };
type Config = { name: string; greeting: string; notice: string; enabled: boolean; available: boolean; test_mode?: boolean };
type CaptchaResponse = { id: string; question: string; expires_in: number };
type Captcha = { id: string; question: string; expiresAt: number };

class ApiRequestError extends Error {
  constructor(message: string, readonly code?: string) { super(message); }
}

function publicLink(value: string): string | undefined {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : undefined;
  } catch {
    return undefined;
  }
}

export default function GiannaChat({ apiBase }: { apiBase: string }) {
  const base = apiBase.replace(/\/$/, '');
  // This anonymous session capability is short lived. No conversation or token is persisted in the browser.
  const token = useRef<string | null>(null);
  const form = useRef<HTMLFormElement>(null);
  const field = useRef<HTMLTextAreaElement>(null);
  const captchaField = useRef<HTMLInputElement>(null);
  const mounted = useRef(true);
  const inputId = useId();
  const hintId = useId();
  const captchaId = useId();
  const [config, setConfig] = useState<Config | null>(null);
  const [question, setQuestion] = useState('');
  const [challenge, setChallenge] = useState<Captcha | null>(null);
  const [captchaAnswer, setCaptchaAnswer] = useState('');
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  const [rated, setRated] = useState<Set<string>>(new Set());

  async function call<T>(path: string, options: RequestInit = {}): Promise<T> {
    const headers = new Headers(options.headers);
    if (options.body !== undefined) headers.set('Content-Type', 'application/json');
    if (token.current) headers.set('Authorization', `Bearer ${token.current}`);
    const response = await fetch(base + path, { ...options, headers, credentials: 'omit' });
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      if (response.status === 401) token.current = null;
      const message = body?.error?.message;
      throw new ApiRequestError(typeof message === 'string' ? message : 'No se pudo completar la solicitud. Intentá nuevamente.', body?.error?.code);
    }
    if (body === null) throw new Error('La respuesta del asistente no se pudo leer.');
    return body as T;
  }

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    fetch(base + '/api/config', { credentials: 'omit', signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error('Gianna no está disponible en este momento.');
        return response.json() as Promise<Config>;
      })
      .then((data) => { if (mounted.current) setConfig(data); })
      .catch((error: unknown) => {
        if (mounted.current && !(error instanceof DOMException && error.name === 'AbortError')) {
          setStatus('No pudimos conectar con Gianna. Recargá la página para intentarlo de nuevo.');
        }
      });
    return () => { mounted.current = false; controller.abort(); };
  }, [base]);

  useEffect(() => {
    if (challenge && !busy) captchaField.current?.focus();
  }, [challenge, busy]);

  async function loadChallenge() {
    const response = await call<CaptchaResponse>('/api/captcha');
    if (typeof response.id !== 'string' || typeof response.question !== 'string' || !Number.isFinite(response.expires_in) || response.expires_in <= 0) {
      throw new Error('No se pudo leer la verificación de seguridad.');
    }
    setChallenge({ id: response.id, question: response.question, expiresAt: Date.now() + response.expires_in * 1000 });
    setCaptchaAnswer('');
  }

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = question.trim();
    if (!message || busy || !config?.enabled || !config.available) return;
    setBusy(true);
    try {
      if (!token.current) {
        if (!challenge || challenge.expiresAt <= Date.now()) {
          await loadChallenge();
          setStatus(challenge ? 'La suma venció. Resolvé la nueva para continuar.' : 'Resolvé la suma para iniciar la conversación.');
          return;
        }
        // A challenge is single-use, including when the answer is wrong or the request fails.
        setChallenge(null);
        try {
          token.current = (await call<{ token: string }>('/api/sessions', {
            method: 'POST', body: JSON.stringify({ captcha_id: challenge.id, captcha_answer: captchaAnswer.trim() }),
          })).token;
          setCaptchaAnswer('');
        } catch (error) {
          if (error instanceof ApiRequestError && error.code === 'captcha_invalid') {
            await loadChallenge();
            setStatus(`${error.message} Intentá con la nueva suma.`);
            return;
          }
          throw error;
        }
      }
      setStatus('Buscando información publicada y preparando una respuesta con fuentes…');
      setQuestion('');
      const reply = await call<Reply>('/api/chat', { method: 'POST', body: JSON.stringify({ message }) });
      if (mounted.current) {
        setExchanges((old) => [...old, { question: message, reply }]);
        setStatus('');
      }
    } catch (error) {
      if (mounted.current) {
        setQuestion(message);
        setStatus(error instanceof Error ? error.message : 'No se pudo conectar con Gianna.');
      }
    } finally {
      if (mounted.current) { setBusy(false); if (token.current) field.current?.focus(); }
    }
  }

  function onQuestionKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      form.current?.requestSubmit();
    }
  }

  async function clear() {
    if (busy) return;
    setBusy(true);
    try {
      if (token.current) await call('/api/sessions/current', { method: 'DELETE' });
      token.current = null;
      setChallenge(null);
      setCaptchaAnswer('');
      setExchanges([]);
      setRated(new Set());
      setStatus('Conversación borrada. Podés empezar otra.');
    } catch (error) {
      if (mounted.current) setStatus(error instanceof Error ? error.message : 'No se pudo borrar la conversación.');
    } finally {
      if (mounted.current) { setBusy(false); field.current?.focus(); }
    }
  }

  async function refreshChallenge() {
    if (busy || token.current) return;
    setBusy(true);
    try {
      await loadChallenge();
      setStatus('Nueva suma lista. Resolvela para continuar.');
    } catch (error) {
      if (mounted.current) setStatus(error instanceof Error ? error.message : 'No se pudo cargar otra suma.');
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  async function rate(id: string, value: 1 | -1) {
    try {
      await call('/api/feedback/' + encodeURIComponent(id), { method: 'POST', body: JSON.stringify({ value }) });
      if (mounted.current) setRated((old) => new Set([...old, id]));
    } catch (error) {
      if (mounted.current) setStatus(error instanceof Error ? error.message : 'No se pudo guardar la valoración.');
    }
  }

  const available = Boolean(config?.enabled && config.available);

  return <section className="gianna-chat" aria-label="Conversación con Gianna">
    <header className="gianna-chat-header">
      <div><span className="gianna-chat-avatar" aria-hidden="true">G</span><div><strong>{config?.name ?? 'Gianna'}</strong><p>Asistente de inversiones de Lavalleja</p></div></div>
      <button type="button" className="gianna-clear" onClick={clear} disabled={busy}>Borrar conversación</button>
    </header>
    {config?.test_mode && <p className="gianna-test-notice" role="note"><strong>Modo de prueba local.</strong> La guía todavía no tiene revisión editorial final. Contrastá cada respuesta con sus fuentes; no la uses para tomar decisiones de inversión.</p>}

    <div className="gianna-conversation" role="log" aria-label="Mensajes de la conversación" aria-live="polite" aria-relevant="additions text">
      {exchanges.length === 0 && <div className="gianna-welcome"><span aria-hidden="true">✦</span><h2>{config?.greeting ?? '¿Qué proyecto tenés en mente?'}</h2><p>Podés saludarme o contarme tu idea. Cuando consultemos datos de la guía, te mostraré las fuentes que respaldan la respuesta.</p><div className="gianna-starters" aria-label="Ideas para empezar">
        {['Hola, ¿cómo estás?', '¿Qué podés hacer?', '¿Qué debería revisar antes de invertir en Lavalleja?'].map((prompt) => <button key={prompt} type="button" onClick={() => { setQuestion(prompt); field.current?.focus(); }} disabled={!available || busy}>{prompt}</button>)}
      </div></div>}
      {exchanges.map(({ question: asked, reply }, index) => <div className="gianna-exchange" key={`${reply.id}-${index}`}>
        <article className="gianna-bubble gianna-bubble-user"><span className="gianna-speaker">Tu pregunta</span><p>{asked}</p></article>
        <article className="gianna-bubble gianna-bubble-answer"><span className="gianna-speaker">Gianna</span><p>{reply.answer}</p>
          {reply.citations?.length > 0 && <div className="gianna-citations"><h3>Fuentes de esta respuesta</h3>
            {reply.citations.map((citation) => <details key={citation.id}><summary>[{citation.id}] {citation.title}</summary>
              <p>{citation.excerpt}</p>
              <small>{[citation.evidence_type, citation.cutoff_date && `Corte: ${citation.cutoff_date}`, citation.locator].filter(Boolean).join(' · ')}</small>
              {citation.sources?.map((source) => {
                const href = publicLink(source.url);
                return href ? <a key={source.id} href={href} target="_blank" rel="noopener noreferrer">{source.id} · {source.title} ↗</a> : null;
              })}
            </details>)}
          </div>}
          {reply.notice && <p className="gianna-reply-notice">{reply.notice}</p>}
          {reply.id && <div className="gianna-feedback">{rated.has(reply.id) ? <small>Gracias por tu valoración.</small> : <><span>¿Te resultó útil?</span><button type="button" onClick={() => rate(reply.id, 1)}>Sí</button><button type="button" onClick={() => rate(reply.id, -1)}>Necesita mejorar</button></>}</div>}
        </article>
      </div>)}
    </div>

    <p className="gianna-status" role="status">{status || (config && !available ? (config.enabled ? 'La base de conocimiento aún no está disponible.' : 'El chat está pausado temporalmente.') : '')}</p>
    <form className="gianna-composer" ref={form} onSubmit={submit}>
      {!token.current && challenge && <div className="gianna-captcha" role="group" aria-label="Verificación de seguridad">
        <div><label htmlFor={captchaId}>Verificación de seguridad: ¿cuánto es {challenge.question}?</label><p>Resolvé la suma para enviar tu pregunta. Cada suma se usa una sola vez.</p></div>
        <div className="gianna-captcha-controls"><input id={captchaId} ref={captchaField} type="text" inputMode="numeric" pattern="[0-9]{1,2}" maxLength={2} autoComplete="off" value={captchaAnswer} onChange={(event) => setCaptchaAnswer(event.target.value)} required disabled={busy} /><button type="button" onClick={refreshChallenge} disabled={busy}>Otra suma</button></div>
      </div>}
      <label htmlFor={inputId}>Tu pregunta</label>
      <div className="gianna-composer-row"><textarea id={inputId} ref={field} aria-describedby={hintId} value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={onQuestionKeyDown} placeholder="¿Qué debería revisar para invertir en Lavalleja?" maxLength={2500} rows={2} required disabled={!available || busy} /><button type="submit" disabled={!available || busy || !question.trim()}>{busy ? 'Consultando…' : token.current ? 'Enviar' : challenge ? 'Verificar y enviar' : 'Iniciar consulta'}</button></div>
      <small id={hintId}>Enter para enviar · Shift+Enter para otra línea. Evitá compartir datos confidenciales.</small>
    </form>
    <p className="gianna-data-note">Tu pregunta y los fragmentos documentales necesarios se envían a Ollama Cloud para generar la respuesta. La conversación visible se conserva solo mientras esta página está abierta.</p>
  </section>;
}
