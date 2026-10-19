import { useEffect, useId, useRef, useState, type KeyboardEvent, type SyntheticEvent } from 'react';
import AnswerContent from './gianna/AnswerContent';
import Sources from './gianna/Sources';
import type { Config, Exchange, Reply } from './gianna/types';

type CaptchaResponse = { id: string; question: string; expires_in: number };
type Captcha = { id: string; question: string; expiresAt: number };

const PROGRESS_STEPS = [
  'Analizando tu consulta y el contexto del proyecto…',
  'Buscando fichas, zonas y requisitos en la guía publicada…',
  'Verificando citas y elaborando la orientación con fuentes…',
];

class ApiRequestError extends Error {
  constructor(message: string, readonly code?: string) { super(message); }
}

export default function GiannaChat({ apiBase }: { apiBase: string }) {
  const base = apiBase.replace(/\/$/, '');
  // This anonymous session capability is short lived. No conversation or token is persisted in the browser.
  const token = useRef<string | null>(null);
  const form = useRef<HTMLFormElement>(null);
  const field = useRef<HTMLTextAreaElement>(null);
  const captchaField = useRef<HTMLInputElement>(null);
  const conversation = useRef<HTMLDivElement>(null);
  const mounted = useRef(true);
  const inputId = useId();
  const hintId = useId();
  const captchaId = useId();
  const [config, setConfig] = useState<Config | null>(null);
  const [question, setQuestion] = useState('');
  const [challenge, setChallenge] = useState<Captcha | null>(null);
  const [captchaAnswer, setCaptchaAnswer] = useState('');
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [pendingQuestion, setPendingQuestion] = useState('');
  const [progressStep, setProgressStep] = useState(0);
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

  useEffect(() => {
    // Scroll only the message list so the newest question is visible; never the whole page.
    const list = conversation.current;
    const latest = list?.lastElementChild as HTMLElement | null | undefined;
    if (!list || !latest || (!exchanges.length && !pendingQuestion)) return;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    window.requestAnimationFrame(() => list.scrollTo({ top: Math.max(0, latest.offsetTop - 12), behavior: reduced ? 'auto' : 'smooth' }));
  }, [exchanges, pendingQuestion]);

  useEffect(() => {
    if (!pendingQuestion) {
      setProgressStep(0);
      return;
    }
    const first = window.setTimeout(() => setProgressStep(1), 1100);
    const second = window.setTimeout(() => setProgressStep(2), 2800);
    return () => {
      window.clearTimeout(first);
      window.clearTimeout(second);
    };
  }, [pendingQuestion]);

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
      setPendingQuestion(message);
      setStatus(PROGRESS_STEPS[0]);
      setQuestion('');
      const reply = await call<Reply>('/api/chat', { method: 'POST', body: JSON.stringify({ message }) });
      if (mounted.current) {
        setPendingQuestion('');
        setExchanges((old) => [...old, { question: message, reply }]);
        setStatus('');
      }
    } catch (error) {
      if (mounted.current) {
        setPendingQuestion('');
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
      setPendingQuestion('');
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

    <div ref={conversation} className="gianna-conversation" role="log" aria-label="Mensajes de la conversación" aria-live="polite" aria-relevant="additions text">
      {exchanges.length === 0 && !pendingQuestion && <div className="gianna-welcome"><span aria-hidden="true">✦</span><h2>{config?.greeting ?? '¿Qué proyecto tenés en mente?'}</h2><p>Podés saludarme o contarme tu idea. Cuando consultemos datos de la guía, te mostraré las fuentes que respaldan la respuesta.</p><div className="gianna-starters" aria-label="Ideas para empezar">
        {['Hola, ¿cómo estás?', '¿Qué podés hacer?', '¿Qué debería revisar antes de invertir en Lavalleja?'].map((prompt) => <button key={prompt} type="button" onClick={() => { setQuestion(prompt); field.current?.focus(); }} disabled={!available || busy}>{prompt}</button>)}
      </div></div>}
      {exchanges.map(({ question: asked, reply }, index) => <div className="gianna-exchange" key={`${reply.id}-${index}`}>
        <article className="gianna-bubble gianna-bubble-user"><span className="gianna-speaker">Tu pregunta</span><p>{asked}</p></article>
        <article className="gianna-bubble gianna-bubble-answer"><span className="gianna-speaker">Gianna</span><AnswerContent text={reply.answer} />
          <Sources citations={reply.citations ?? []} opportunities={reply.opportunity_ids} />
          {reply.notice && <p className="gianna-reply-notice">{reply.notice}</p>}
          {reply.id && <div className="gianna-feedback">{rated.has(reply.id) ? <small>Gracias por tu valoración.</small> : <><span>¿Te resultó útil?</span><button type="button" onClick={() => rate(reply.id, 1)}>Sí</button><button type="button" onClick={() => rate(reply.id, -1)}>Necesita mejorar</button></>}</div>}
        </article>
      </div>)}
      {pendingQuestion && <div className="gianna-exchange gianna-exchange-pending" aria-busy="true">
        <article className="gianna-bubble gianna-bubble-user"><span className="gianna-speaker">Tu pregunta</span><p>{pendingQuestion}</p></article>
        <article className="gianna-bubble gianna-bubble-answer gianna-bubble-pending" aria-label="Gianna está preparando una respuesta">
          <span className="gianna-speaker">Gianna</span>
          <div className="gianna-thinking">
            <span className="gianna-thinking-dots" aria-hidden="true"><span /><span /><span /></span>
            <p className="gianna-thinking-step">{PROGRESS_STEPS[progressStep]}</p>
          </div>
          <ol className="gianna-thinking-stages" aria-hidden="true">
            {PROGRESS_STEPS.map((label, idx) => <li key={label} className={idx < progressStep ? 'is-done' : idx === progressStep ? 'is-active' : ''}>{label}</li>)}
          </ol>
        </article>
      </div>}
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
    <p className="gianna-data-note">Tu pregunta se envía a nuestro modelo de IA para generar la respuesta. La conversación visible se conserva solo mientras esta página está abierta.</p>
  </section>;
}
