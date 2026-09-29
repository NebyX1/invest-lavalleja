import { useEffect, useRef, useState, type FormEvent } from 'react';
import './gianna-chat.css';

type Source = { id: string; title: string; url: string };
type Citation = { id: string; title: string; excerpt: string; cutoff_date: string | null; sources: Source[] };
type Reply = { id: string; answer: string; citations: Citation[]; status: string; notice: string };
type Message = { role: 'user' | 'assistant'; text: string; reply?: Reply };
type Config = { name: string; greeting: string; notice: string; enabled: boolean; available: boolean };
type Props = { apiBase: string };

function publicLink(value: string): string | undefined {
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : undefined; }
  catch { return undefined; }
}

/** apiBase is a public backend URL, never an API key. Mount as an Astro React island. */
export default function GiannaChat({ apiBase }: Props) {
  const base = apiBase.replace(/\/$/, '');
  const token = useRef<string | null>(null);
  const mounted = useRef(true);
  const [config, setConfig] = useState<Config | null>(null);
  const [question, setQuestion] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  const [rated, setRated] = useState<Set<string>>(new Set());

  async function call<T>(path: string, options: RequestInit = {}): Promise<T> {
    const headers = new Headers(options.headers);
    headers.set('Content-Type', 'application/json');
    if (token.current) headers.set('Authorization', `Bearer ${token.current}`);
    const response = await fetch(base + path, { ...options, headers, credentials: 'omit' });
    const body = await response.json();
    if (!response.ok) {
      if (response.status === 401) token.current = null;
      throw new Error(body.error?.message ?? 'No se pudo completar la solicitud.');
    }
    return body as T;
  }

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    fetch(base + '/api/config', { credentials: 'omit', signal: controller.signal })
      .then(async r => { if (!r.ok) throw new Error('Gianna no está disponible.'); return r.json() as Promise<Config>; })
      .then(data => { if (mounted.current) setConfig(data); })
      .catch(error => { if (mounted.current && error.name !== 'AbortError') setStatus(error.message); });
    return () => { mounted.current = false; controller.abort(); };
  }, [base]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = question.trim();
    if (!message || busy) return;
    setBusy(true); setStatus('Buscando en la guía y preparando una respuesta con fuentes…');
    setMessages(old => [...old, { role: 'user', text: message }]); setQuestion('');
    try {
      if (!token.current) token.current = (await call<{token: string}>('/api/sessions', { method: 'POST', body: '{}' })).token;
      const reply = await call<Reply>('/api/chat', { method: 'POST', body: JSON.stringify({ message }) });
      if (mounted.current) { setMessages(old => [...old, { role: 'assistant', text: reply.answer, reply }]); setStatus(''); }
    } catch (error) { if (mounted.current) { setStatus(error instanceof Error ? error.message : 'Error de conexión.'); setQuestion(message); } }
    finally { if (mounted.current) setBusy(false); }
  }

  async function clear() {
    if (busy) return;
    setBusy(true);
    try {
      if (token.current) await call('/api/sessions/current', { method: 'DELETE' });
      token.current = null; setMessages([]); setRated(new Set()); setStatus('Conversación borrada.');
    } catch (error) { setStatus(error instanceof Error ? error.message : 'No se pudo borrar.'); }
    finally { setBusy(false); }
  }

  async function rate(id: string, value: 1 | -1) {
    try {
      await call('/api/feedback/' + encodeURIComponent(id), { method: 'POST', body: JSON.stringify({ value }) });
      setRated(old => new Set([...old, id]));
    } catch (error) { setStatus(error instanceof Error ? error.message : 'No se pudo guardar la valoración.'); }
  }

  return <section className="gianna-chat" aria-label="Asistente de inversiones">
    <header><div><strong>{config?.name ?? 'Gianna · Invest Lavalleja'}</strong><p>{config?.greeting ?? '¿Qué proyecto tenés en mente?'}</p></div>
      <button type="button" onClick={clear} disabled={busy}>Borrar conversación</button></header>
    <p className="gianna-privacy">La pregunta y los fragmentos necesarios se envían a Ollama Cloud. No compartas información confidencial.</p>
    <div className="gianna-messages" aria-live="polite">
      {messages.map((message, index) => <article className={'gianna-message gianna-' + message.role} key={index}>
        <p>{message.text}</p>
        {message.reply?.citations.map(cite => <details key={cite.id}>
          <summary>[{cite.id}] {cite.title}</summary><p>{cite.excerpt}</p><small>Corte documental: {cite.cutoff_date ?? 'No especificado'}</small>
          {cite.sources.map(source => publicLink(source.url) ? <p key={source.id}><a href={publicLink(source.url)} target="_blank" rel="noopener noreferrer">{source.id} · {source.title} ↗</a></p> : null)}
        </details>)}
        {message.reply && <div className="gianna-feedback">{rated.has(message.reply.id) ? <small>Gracias por tu valoración.</small> : <>
          <button type="button" onClick={() => rate(message.reply!.id, 1)}>Me resultó útil</button>
          <button type="button" onClick={() => rate(message.reply!.id, -1)}>Necesita mejorar</button></>}</div>}
      </article>)}
    </div>
    <p className="gianna-status" role="status">{status}</p>
    <form onSubmit={submit}><label htmlFor="gianna-question">Tu pregunta</label><textarea id="gianna-question" value={question} onChange={e => setQuestion(e.target.value)} maxLength={2500} rows={3} required />
      <button type="submit" disabled={busy || config?.enabled === false}>{busy ? 'Preparando respuesta…' : 'Preguntar a Gianna →'}</button></form>
    <p className="gianna-privacy">{config?.notice ?? 'Orientación documental. Las condiciones de cada proyecto requieren confirmación.'}</p>
  </section>;
}
