import { useEffect, useMemo, useState } from 'react';
import { useStore } from '@nanostores/react';
import catalogJson from '../../data/catalog.json';
import { $savedZones, clearZones, initializeClientState, removeZone } from '../../stores/state';
import type { Catalog } from '../../types';

const catalog = catalogJson as Catalog;
type View = 'overview' | 'operations' | 'checks';

function downloadMarkdown(content: string, filename: string): void {
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export default function DossierIsland() {
  const savedIds = useStore($savedZones);
  const [view, setView] = useState<View>('overview');
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      initializeClientState();
      setMounted(true);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);
  const zones = useMemo(() => (mounted ? savedIds : []).map((id) => catalog.zones.find((zone) => zone.id === id)).filter(Boolean), [mounted, savedIds]);

  const exportDossier = () => {
    const lines = [
      '# Mi dossier de inversión — Invest Lavalleja',
      '',
      'Generado localmente en este navegador. No se envió a ningún organismo y no constituye una oferta de inversión.',
      '',
      `Zonas seleccionadas: ${zones.length}/3`,
      '',
    ];
    for (const zone of zones) {
      if (!zone) continue;
      lines.push(`## ${zone.name}`, '', zone.summary, '', `**Oportunidad a explorar:** ${zone.opportunity}`, '', '**Fortalezas**', ...zone.strengths.map((item) => `- ${item}`), '', '**Por verificar**', ...zone.checks.map((item) => `- ${item}`), '', `Fuentes: ${zone.sources.map((id) => catalog.sources.find((source) => source.id === id)?.title ?? id).join('; ')}`, '');
    }
    downloadMarkdown(lines.join('\n'), 'invest-lavalleja-dossier.md');
  };

  if (zones.length === 0) {
    return <section className="dossier-empty" aria-live="polite"><div className="empty-mark"><svg className="icon" viewBox="0 0 24 24" aria-hidden="true"><use href="#icon-bookmark" /></svg></div><h3>Tu dossier está esperando una primera zona.</h3><p>Guardá hasta tres perfiles desde el explorador o las fichas territoriales para compararlos acá.</p><a className="btn primary" href="/territorio/">Explorar el territorio <svg className="icon" viewBox="0 0 24 24" aria-hidden="true"><use href="#icon-arrow" /></svg></a></section>;
  }

  return (
    <section className="dossier-workspace" aria-label="Dossier de inversión">
      <div className="dossier-toolbar"><p><strong>{zones.length}</strong> {zones.length === 1 ? 'zona guardada' : 'zonas guardadas'} <span>· máximo 3</span></p><div className="actions"><button className="btn small" type="button" onClick={exportDossier}>Descargar Markdown <svg className="icon" viewBox="0 0 24 24" aria-hidden="true"><use href="#icon-download" /></svg></button><button className="btn small" type="button" onClick={() => window.print()}>Vista de impresión</button><button className="btn small quiet" type="button" onClick={() => clearZones()}>Vaciar</button></div></div>
      <div className="dossier-tabs" role="tablist" aria-label="Perspectiva de comparación">
        {([['overview', 'Visión general'], ['operations', 'Operaciones'], ['checks', 'Requisitos y fuentes']] as const).map(([key, label]) => <button key={key} type="button" role="tab" aria-selected={view === key} className={view === key ? 'active' : ''} onClick={() => setView(key)}>{label}</button>)}
      </div>
      <div className="dossier-list">
        {zones.map((zone) => zone && <article className="dossier-card" key={zone.id}>
          <div className="dossier-card-head"><div><p className="eyebrow"><span className="dot" />{zone.eyebrow}</p><h3>{zone.name}</h3></div><button className="icon-button" type="button" aria-label={`Quitar ${zone.name} del dossier`} onClick={() => removeZone(zone.id)}><svg className="icon" viewBox="0 0 24 24" aria-hidden="true"><use href="#icon-close" /></svg></button></div>
          {view === 'overview' && <><p>{zone.summary}</p><div className="dossier-highlight"><span>Idea a explorar</span><strong>{zone.opportunity}</strong></div><ul className="check-list">{zone.strengths.map((item) => <li key={item}><svg className="icon" viewBox="0 0 24 24" aria-hidden="true"><use href="#icon-check" /></svg>{item}</li>)}</ul></>}
          {view === 'operations' && <><h4>Qué podría organizarse alrededor de esta zona</h4><p>{zone.opportunity}</p><div className="tag-list">{zone.sectors.map((id) => <span className="tag" key={id}>{catalog.sectors.find((sector) => sector.id === id)?.short ?? id}</span>)}</div></>}
          {view === 'checks' && <><h4>Puntos que requieren comprobación</h4><ul className="check-list pending">{zone.checks.map((item) => <li key={item}><span className="pending-dot" />{item}</li>)}</ul><div className="source-note">{zone.sources.map((id) => { const source = catalog.sources.find((item) => item.id === id); return source ? <a href={source.url} key={id} target={source.url.startsWith('http') ? '_blank' : undefined} rel={source.url.startsWith('http') ? 'noreferrer' : undefined}>{source.title}</a> : null; })}</div></>}
        </article>)}
      </div>
      <p className="dossier-note">La comparación organiza preguntas para tu proyecto. No calcula rentabilidad ni disponibilidad de inmuebles.</p>
    </section>
  );
}
