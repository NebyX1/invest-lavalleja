import type { Citation } from './types';

function publicLink(value: string): string | undefined {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : undefined;
  } catch {
    return undefined;
  }
}

function cleanCitationTitle(title: string): string {
  return title
    .replace(/^O(?:0[1-9]|1[0-6])\s*·\s*/i, '')
    .replace(/^Siete zonas\.\s*Siete preguntas de inversión\.\s*·\s*Z[1-7]\s*·\s*/i, 'Zona: ')
    .trim();
}

export default function Sources({ citations }: { citations: Citation[]; opportunities?: string[] }) {
  if (!citations.length) return null;
  return <div className="gianna-citations">
    <h3>Fuentes citadas en esta respuesta</h3>
    {citations.map((citation) => <details key={citation.id}>
      <summary>[{citation.id}] {cleanCitationTitle(citation.title)}</summary>
      <p>{citation.excerpt}</p>
      <small>{[citation.evidence_type, citation.cutoff_date && `Corte: ${citation.cutoff_date}`, citation.locator].filter(Boolean).join(' · ')}</small>
      {citation.sources?.map((source) => {
        const href = publicLink(source.url);
        return href ? <a key={source.id} href={href} target="_blank" rel="noopener noreferrer">{source.id} · {source.title} ↗</a> : null;
      })}
    </details>)}
  </div>;
}
