import { useEffect, useMemo, useState } from 'react';
import type { FAQ, Source } from '../../types';

interface Props { sources: Source[]; faqs: FAQ[] }

function normalize(value: string) { return value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase(); }

export default function ResourceSearch({ sources, faqs }: Props) {
  const [query, setQuery] = useState('');
  const [type, setType] = useState('all');
  useEffect(() => {
    if (window.location.hash === '#buscar') document.getElementById('resource-search-input')?.focus();
  }, []);
  const filteredSources = useMemo(() => sources.filter((source) => {
    const haystack = normalize(`${source.title} ${source.scope} ${source.type}`);
    return (!query || haystack.includes(normalize(query))) && (type === 'all' || source.type === type);
  }), [query, sources, type]);
  const filteredFaqs = useMemo(() => faqs.filter((faq) => !query || normalize(`${faq.q} ${faq.a}`).includes(normalize(query))), [faqs, query]);
  const sourceTypes = [...new Set(sources.map((source) => source.type))];

  return <section className="inline-search" id="buscar" aria-label="Buscar recursos y preguntas frecuentes">
    <div className="inline-search-controls"><label htmlFor="resource-search-input">Buscar recursos <input id="resource-search-input" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Fuente, tema o palabra clave…" /></label><label htmlFor="resource-type">Tipo <select id="resource-type" value={type} onChange={(event) => setType(event.target.value)}><option value="all">Todos</option>{sourceTypes.map((item) => <option key={item} value={item}>{item}</option>)}</select></label></div>
    <div className="search-results resource-results" aria-live="polite"><h2 className="sr-only">Fuentes del centro del inversor</h2><p className="result-count">{filteredSources.length} fuentes · {filteredFaqs.length} preguntas</p>{filteredSources.map((source) => <article className="resource-result" id={`resource-result-${source.id}`} key={source.id}><span className="tag">{source.type}</span><div><h3>{source.title}</h3><p>{source.scope}</p><small>Consultada: {source.consulted}</small></div><a href={source.url} target={source.url.startsWith('http') ? '_blank' : undefined} rel={source.url.startsWith('http') ? 'noreferrer' : undefined}>Abrir <svg className="icon" viewBox="0 0 24 24" aria-hidden="true"><use href="#icon-up" /></svg></a></article>)}{filteredSources.length === 0 && <p className="search-empty">No encontramos fuentes con ese filtro.</p>}</div>
    <div className="faq-list"><h2>Preguntas frecuentes</h2>{filteredFaqs.map((faq) => <details key={faq.q}><summary>{faq.q}</summary><p>{faq.a}</p>{faq.sources.length > 0 && <div className="source-note">Fuentes: {faq.sources.map((id) => <a href={`/fuentes/#${id}`} key={id}>{id}</a>)}</div>}</details>)}</div>
  </section>;
}
