import { useEffect, useMemo, useState } from 'react';
import { useStore } from '@nanostores/react';
import catalogJson from '../../data/catalog.json';
import { $projectDraft, initializeClientState, resetProjectDraft, updateProjectDraft } from '../../stores/state';
import { emptyProjectDraft, type Catalog } from '../../types';

const catalog = catalogJson as Catalog;
const stages = [
  ['idea', 'Idea en exploración'],
  ['prefactibilidad', 'Prefactibilidad'],
  ['instalación', 'Instalación o expansión'],
] as const;
const needs = [
  ['localizacion', 'Localización y padrón'],
  ['servicios', 'Servicios e infraestructura'],
  ['equipo', 'Equipo y proveedores'],
  ['permisos', 'Permisos y normativa'],
  ['mercado', 'Mercado y clientes'],
  ['financiamiento', 'Estructura de financiamiento'],
] as const;

function downloadSummary(text: string): void {
  const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'invest-lavalleja-resumen-proyecto.md';
  link.click();
  URL.revokeObjectURL(url);
}

export default function ProjectWizard() {
  const storedDraft = useStore($projectDraft);
  const [step, setStep] = useState(0);
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      initializeClientState();
      setMounted(true);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);
  const draft = mounted ? storedDraft : emptyProjectDraft;
  const currentDraft = draft;
  const activeSector = catalog.sectors.find((sector) => sector.id === currentDraft.activity);
  const relatedZones = useMemo(() => currentDraft.activity ? catalog.zones.filter((zone) => zone.sectors.includes(currentDraft.activity)) : [], [currentDraft.activity]);
  const canContinue = step === 0 ? Boolean(currentDraft.activity) : step === 1 ? Boolean(currentDraft.stage) : step === 2 ? currentDraft.needs.length > 0 : true;

  const summary = `# Resumen local de proyecto\n\nGenerado localmente en este navegador. No se envió a una oficina ni crea una solicitud.\n\n- Actividad: ${activeSector?.name ?? 'Sin definir'}\n- Etapa: ${stages.find(([id]) => id === currentDraft.stage)?.[1] ?? 'Sin definir'}\n- Necesidades declaradas: ${currentDraft.needs.length ? currentDraft.needs.map((id) => needs.find(([needId]) => needId === id)?.[1]).join(', ') : 'Sin definir'}\n\n## Próximas preguntas\n\nConfirmá qué información, permisos, proveedores y condiciones debe comprobar tu proyecto. Las necesidades declaradas no son recursos disponibles.\n`;

  return (
    <section className="wizard" aria-label="Preparar mi proyecto">
      <div className="wizard-progress" aria-label={`Paso ${step + 1} de 4`}>{['Actividad', 'Etapa', 'Necesidades', 'Resumen'].map((label, index) => <span key={label} className={index === step ? 'current' : index < step ? 'done' : ''}><b>{index + 1}</b>{label}</span>)}</div>
      {step === 0 && <div className="wizard-step"><p className="eyebrow"><span className="dot" />PASO 1 · ACTIVIDAD</p><h3>¿Qué querés desarrollar?</h3><p>Elegí una entrada del catálogo para relacionar tu proyecto con información editorial explícita.</p><div className="wizard-options">{catalog.sectors.map((sector) => <button className={currentDraft.activity === sector.id ? 'selected' : ''} type="button" key={sector.id} onClick={() => updateProjectDraft({ activity: sector.id })}><span>{sector.short}</span><small>{sector.description}</small></button>)}</div></div>}
      {step === 1 && <div className="wizard-step"><p className="eyebrow"><span className="dot" />PASO 2 · ETAPA</p><h3>¿En qué momento está?</h3><p>Esta respuesta organiza el resumen; no es una evaluación del proyecto.</p><div className="wizard-options compact">{stages.map(([id, label]) => <button className={currentDraft.stage === id ? 'selected' : ''} type="button" key={id} onClick={() => updateProjectDraft({ stage: id })}><span>{label}</span><small>{id === 'idea' ? 'Primera exploración y preguntas.' : id === 'prefactibilidad' ? 'Comparación de condiciones antes de comprometer.' : 'Operación, expansión o nueva instalación.'}</small></button>)}</div></div>}
      {step === 2 && <div className="wizard-step"><p className="eyebrow"><span className="dot" />PASO 3 · NECESIDADES</p><h3>¿Qué necesitás comprobar?</h3><p>Podés elegir más de una. Estas necesidades quedan como preguntas abiertas.</p><div className="wizard-checks">{needs.map(([id, label]) => <label key={id} className={currentDraft.needs.includes(id) ? 'selected' : ''}><input type="checkbox" checked={currentDraft.needs.includes(id)} onChange={(event) => updateProjectDraft({ needs: event.target.checked ? [...currentDraft.needs, id] : currentDraft.needs.filter((item) => item !== id) })} />{label}</label>)}</div></div>}
      {step === 3 && <div className="wizard-step wizard-result"><p className="eyebrow"><span className="dot" />PASO 4 · RESUMEN</p><h3>Una decisión con más contexto.</h3><p>Este resumen local relaciona tus respuestas con etiquetas del catálogo sin prometer disponibilidad ni compatibilidad.</p><article><span className="tag mint">ACTIVIDAD</span><h4>{activeSector?.name ?? 'Sin definir'}</h4><p>{activeSector?.tagline ?? 'Elegí una actividad para empezar.'}</p></article><article><span className="tag violet">ZONAS RELACIONADAS</span>{relatedZones.length ? <ul>{relatedZones.map((zone) => <li key={zone.id}><a href={`/zonas/${zone.id}/`}>{zone.name}</a><small>{zone.summary}</small></li>)}</ul> : <p>Elegí una actividad para ver perfiles relacionados.</p>}</article><article><span className="tag gold">PREGUNTAS ABIERTAS</span><p>{draft.needs.length ? draft.needs.map((id) => needs.find(([needId]) => needId === id)?.[1]).join(' · ') : 'No declaraste necesidades todavía.'}</p></article><div className="actions"><button className="btn primary" type="button" onClick={() => downloadSummary(summary)}>Descargar resumen <svg className="icon" viewBox="0 0 24 24" aria-hidden="true"><use href="#icon-download" /></svg></button><button className="btn" type="button" onClick={() => resetProjectDraft()}>Restablecer</button></div></div>}
      <div className="wizard-nav"><button className="btn" type="button" onClick={() => setStep((value) => Math.max(0, value - 1))} disabled={step === 0}>Atrás</button>{step < 3 ? <button className="btn primary" type="button" onClick={() => setStep((value) => Math.min(3, value + 1))} disabled={!canContinue}>Continuar <svg className="icon" viewBox="0 0 24 24" aria-hidden="true"><use href="#icon-arrow" /></svg></button> : <a className="btn" href="/contacto/">Ver canales de contacto</a>}</div>
      <p className="wizard-persistence" aria-live="polite">Tus respuestas se conservan en esta sesión del navegador.</p>
    </section>
  );
}
