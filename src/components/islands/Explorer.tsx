import { useEffect, useMemo, useState } from 'react';
import { useStore } from '@nanostores/react';
import { $savedZones, initializeClientState, toggleZone } from '../../stores/state';
import type { Sector, Zone } from '../../types';

interface Props { zones: Zone[]; sectors: Sector[] }

export default function Explorer({ zones, sectors }: Props) {
  const savedZones = useStore($savedZones);
  const [activity, setActivity] = useState('all');
  const [selectedId, setSelectedId] = useState(zones[0]?.id ?? '');
  useEffect(() => {
    const timer = window.setTimeout(() => initializeClientState(), 0);
    return () => window.clearTimeout(timer);
  }, []);

  const filteredZones = useMemo(() => activity === 'all' ? zones : zones.filter((zone) => zone.sectors.includes(activity)), [activity, zones]);
  const selected = filteredZones.find((zone) => zone.id === selectedId) ?? filteredZones[0];
  const selectedIsSaved = selected ? savedZones.includes(selected.id) : false;

  return (
    <section className="explorer" aria-label="Explorador territorial">
      <div className="explorer-toolbar">
        <label htmlFor="explorer-activity">Filtrar por actividad <select className="select" id="explorer-activity" value={activity} onChange={(event) => { setActivity(event.target.value); setSelectedId(''); }}>
          <option value="all">Todas las actividades</option>{sectors.map((sector) => <option key={sector.id} value={sector.id}>{sector.short}</option>)}
        </select></label>
        <span className="explorer-count" aria-live="polite">{filteredZones.length} {filteredZones.length === 1 ? 'perfil' : 'perfiles'}</span>
      </div>
      <div className="explorer-main">
        <div className="territory-schematic" aria-label="Esquema territorial sin coordenadas geográficas">
          <div className="contour-scene" aria-hidden="true">{Array.from({ length: 9 }, (_, index) => <i key={index} style={{ '--i': index } as React.CSSProperties} />)}</div>
          {filteredZones.map((zone) => <button type="button" key={zone.id} className={`territory-point ${selected?.id === zone.id ? 'selected' : ''}`} style={{ left: `${zone.position[0]}%`, top: `${zone.position[1]}%` }} onClick={() => setSelectedId(zone.id)} aria-pressed={selected?.id === zone.id}><span>{zone.short}</span></button>)}
          <p className="schematic-note">Esquema de perfiles comerciales. No representa límites administrativos ni ubicaciones exactas.</p>
        </div>
        <div className="explorer-detail" aria-live="polite">
          {selected ? <>
            <p className="eyebrow"><span className="tag mint">PERFIL TERRITORIAL</span> {selected.eyebrow}</p>
            <h3>{selected.name}</h3>
            <p>{selected.summary}</p>
            <div className="tag-list">{selected.sectors.map((id) => <span className="tag" key={id}>{sectors.find((sector) => sector.id === id)?.short ?? id}</span>)}</div>
            <div className="explorer-actions"><a className="btn primary small" href={`/zonas/${selected.id}/`}>Conocer esta zona <svg className="icon" viewBox="0 0 24 24" aria-hidden="true"><use href="#icon-up" /></svg></a><button className="btn small" type="button" onClick={() => toggleZone(selected.id)}>{selectedIsSaved ? 'Quitar' : 'Guardar'} <svg className="icon" viewBox="0 0 24 24" aria-hidden="true"><use href="#icon-bookmark" /></svg></button></div>
            <p className="explorer-limit">{selectedIsSaved ? 'Está en tu dossier.' : savedZones.length >= 3 ? 'Tu dossier ya tiene tres zonas.' : 'Podés guardar hasta tres zonas para compararlas.'}</p>
          </> : <p className="search-empty">No hay perfiles para esa actividad. Probá con otra entrada del catálogo.</p>}
        </div>
      </div>
      <div className="explorer-list" aria-label="Lista alternativa de zonas">{filteredZones.map((zone) => <a href={`/zonas/${zone.id}/`} key={zone.id}><span>{zone.short}</span><small>{zone.summary}</small><svg className="icon" viewBox="0 0 24 24" aria-hidden="true"><use href="#icon-up" /></svg></a>)}</div>
    </section>
  );
}
