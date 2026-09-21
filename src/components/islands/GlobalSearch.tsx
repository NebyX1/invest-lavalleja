import Fuse from 'fuse.js';
import { useEffect, useRef, useState } from 'react';
import { navigate } from 'astro:transitions/client';
import type { SearchEntry } from '../../types';

function normalize(value: string): string {
  return value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
}

interface Props {
  entries: SearchEntry[];
}

export default function GlobalSearch({ entries }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const triggerRef = useRef<HTMLElement | null>(null);

  const searchableEntries = entries.map((entry) => ({ ...entry, search: normalize(`${entry.title} ${entry.excerpt} ${entry.type}`) }));
  const fuse = new Fuse(searchableEntries, { keys: ['search'], threshold: 0.35, ignoreLocation: true });
  const results = query.trim() ? fuse.search(normalize(query)).slice(0, 8).map((result) => result.item) : entries.slice(0, 8);

  useEffect(() => {
    const searchWindow = window as Window & { __investSearchPending?: boolean };
    const openSearch = (event?: Event) => {
      if (event) {
        const trigger = (event.target as HTMLElement | null)?.closest('[data-open-search]');
        if (!trigger) return;
        event.preventDefault();
        triggerRef.current = trigger as HTMLElement;
      }
      setOpen(true);
    };
    const onExternalOpen = () => {
      searchWindow.__investSearchPending = false;
      setOpen(true);
    };
    const onClick = (event: Event) => openSearch(event);
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        openSearch();
      }
    };
    document.addEventListener('click', onClick);
    document.addEventListener('keydown', onKeyDown);
    window.addEventListener('invest:open-search', onExternalOpen);
    if (searchWindow.__investSearchPending) onExternalOpen();
    return () => {
      document.removeEventListener('click', onClick);
      document.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('invest:open-search', onExternalOpen);
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    setActiveIndex(0);
    window.setTimeout(() => inputRef.current?.focus(), 0);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false);
        window.setTimeout(() => triggerRef.current?.focus(), 0);
      }
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        setActiveIndex((index) => Math.min(index + 1, Math.max(results.length - 1, 0)));
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault();
        setActiveIndex((index) => Math.max(index - 1, 0));
      }
      if (event.key === 'Enter' && results[activeIndex]) {
        event.preventDefault();
        void goTo(results[activeIndex].path);
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open, activeIndex, results]);

  async function goTo(path: string) {
    setOpen(false);
    setQuery('');
    await navigate(path);
  }

  if (!open) return null;

  return (
    <div className="search-dialog" role="dialog" aria-modal="true" aria-labelledby="global-search-title" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
      <div className="search-dialog-panel glass">
        <div className="search-dialog-head">
          <div><p className="eyebrow"><span className="dot" />BUSCAR EN INVEST LAVALLEJA</p><h2 id="global-search-title">Encontrá información.</h2></div>
          <button className="btn square" type="button" aria-label="Cerrar búsqueda" onClick={() => setOpen(false)}><svg className="icon" viewBox="0 0 24 24" aria-hidden="true"><use href="#icon-close" /></svg></button>
        </div>
        <label className="search-input-wrap" htmlFor="global-search-input">
          <svg className="icon" viewBox="0 0 24 24" aria-hidden="true"><use href="#icon-search" /></svg>
          <input ref={inputRef} id="global-search-input" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Sectores, zonas, historias, fuentes…" autoComplete="off" />
          <kbd>Esc</kbd>
        </label>
        <div className="search-results" role="listbox" aria-label="Resultados de búsqueda" aria-live="polite">
          {results.length > 0 ? results.map((result, index) => (
            <button className={`search-result ${index === activeIndex ? 'is-active' : ''}`} type="button" role="option" aria-selected={index === activeIndex} key={result.id} onMouseEnter={() => setActiveIndex(index)} onClick={() => void goTo(result.path)}>
              <span className="search-result-type">{result.type}</span>
              <span><strong>{result.title}</strong><small>{result.excerpt}</small></span>
              <svg className="icon" viewBox="0 0 24 24" aria-hidden="true"><use href="#icon-up" /></svg>
            </button>
          )) : <p className="search-empty">No encontramos resultados. Probá con una actividad, una localidad o una fuente.</p>}
        </div>
        <p className="search-hint"><kbd>↑</kbd><kbd>↓</kbd> para recorrer · <kbd>Enter</kbd> para abrir · <kbd>Esc</kbd> para cerrar</p>
      </div>
    </div>
  );
}
