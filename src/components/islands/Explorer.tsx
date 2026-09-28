import { useEffect, useMemo, useState } from 'react';
import { useStore } from '@nanostores/react';
import { $savedZones, initializeClientState, toggleZone } from '../../stores/state';
import { mapLocations, mapViewBox } from '../../data/map-locations';
import type { Sector, Zone } from '../../types';

interface Props { zones: Zone[]; sectors: Sector[] }

export default function Explorer({ zones, sectors }: Props) {
  const savedZones = useStore($savedZones);
  const [activity, setActivity] = useState('all');
  const [selectedId, setSelectedId] = useState(zones[0]?.id ?? '');
  const [selectedLocationId, setSelectedLocationId] = useState('minas');
  useEffect(() => {
    const timer = window.setTimeout(() => initializeClientState(), 0);
    return () => window.clearTimeout(timer);
  }, []);

  const filteredZones = useMemo(() => activity === 'all' ? zones : zones.filter((zone) => zone.sectors.includes(activity)), [activity, zones]);
  const filteredLocations = useMemo(() => mapLocations.filter((location) => filteredZones.some((zone) => zone.id === location.zoneId)), [filteredZones]);
  const selected = filteredZones.find((zone) => zone.id === selectedId) ?? filteredZones[0];
  const selectedIsSaved = selected ? savedZones.includes(selected.id) : false;

  function selectActivity(nextActivity: string): void {
    const nextZones = nextActivity === 'all' ? zones : zones.filter((zone) => zone.sectors.includes(nextActivity));
    const firstMappedLocation = mapLocations.find((location) => nextZones.some((zone) => zone.id === location.zoneId));
    setActivity(nextActivity);
    setSelectedId(firstMappedLocation?.zoneId ?? nextZones[0]?.id ?? '');
    setSelectedLocationId(firstMappedLocation?.id ?? '');
  }

  function selectZone(zoneId: string): void {
    setSelectedId(zoneId);
    setSelectedLocationId('');
  }

  return (
    <section className="explorer" aria-label="Explorador territorial">
      <h2 className="sr-only">Localidades y perfiles de Lavalleja</h2>
      <div className="explorer-toolbar">
        <label htmlFor="explorer-activity">Filtrar por actividad <select className="select" id="explorer-activity" value={activity} onChange={(event) => selectActivity(event.target.value)}>
          <option value="all">Todas las actividades</option>{sectors.map((sector) => <option key={sector.id} value={sector.id}>{sector.short}</option>)}
        </select></label>
        <span className="explorer-count" aria-live="polite">{filteredZones.length} {filteredZones.length === 1 ? 'perfil' : 'perfiles'}</span>
      </div>
      <div className="explorer-main">
        <div className="territory-map-wrap">
          <div className="territory-map-stage" role="group" aria-label="Localidades seleccionables en el mapa de Lavalleja" data-testid="lavalleja-map">
            <img className="territory-map-image" src="/media/Lavalleja-Map.svg" alt="Mapa del departamento de Lavalleja con seis localidades identificadas." width={mapViewBox.width} height={mapViewBox.height} loading="lazy" draggable="false" />
            {filteredLocations.map((location) => {
              const zone = zones.find((item) => item.id === location.zoneId);
              if (!zone) return null;
              const isSelected = selected?.id === zone.id && selectedLocationId === location.id;
              return <button
                type="button"
                key={location.id}
                className={`territory-location-point ${isSelected ? 'selected' : ''}`}
                style={{ left: `${location.x / mapViewBox.width * 100}%`, top: `${location.y / mapViewBox.height * 100}%` }}
                onClick={() => { setSelectedId(zone.id); setSelectedLocationId(location.id); }}
                aria-label={`Seleccionar ${location.name}. Perfil: ${zone.name}.`}
                aria-pressed={isSelected}
                title={`${location.name} · ${zone.name}`}
              ><span aria-hidden="true" /></button>;
            })}
          </div>
          <p className="territory-map-note">Los puntos corresponden a las localidades indicadas en el mapa. Los perfiles son orientativos y no indican padrones ni disponibilidad de predios.</p>
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
      <div className="explorer-list" role="group" aria-label="Seleccionar un perfil territorial">{filteredZones.map((zone) => <article className={`explorer-list-item ${selected?.id === zone.id ? 'selected' : ''}`} key={zone.id}>
        <button className="explorer-list-select" type="button" onClick={() => selectZone(zone.id)} aria-pressed={selected?.id === zone.id}><span>{zone.short}</span><small>{zone.summary}</small></button>
        <a className="explorer-list-link" href={`/zonas/${zone.id}/`} aria-label={`Abrir ficha de ${zone.name}`}><svg className="icon" viewBox="0 0 24 24" aria-hidden="true"><use href="#icon-up" /></svg></a>
      </article>)}</div>
    </section>
  );
}
