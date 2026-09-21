import { useEffect, useState } from 'react';
import { useStore } from '@nanostores/react';
import { $savedZones, initializeClientState, toggleZone } from '../../stores/state';

interface Props { zoneId: string; zoneName: string }

export default function SaveZone({ zoneId, zoneName }: Props) {
  const savedZones = useStore($savedZones);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      initializeClientState();
      setMounted(true);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  const saved = mounted && savedZones.includes(zoneId);
  const atLimit = mounted && savedZones.length >= 3 && !saved;
  return (
    <div className="save-zone-control">
      <button className={`btn ${saved ? 'primary' : ''}`} type="button" onClick={() => toggleZone(zoneId)} disabled={atLimit} aria-pressed={saved}>
        <svg className="icon" viewBox="0 0 24 24" aria-hidden="true"><use href="#icon-bookmark" /></svg>
        {saved ? 'Guardada en mi dossier' : 'Guardar esta zona'}
      </button>
      <span className="save-zone-status" aria-live="polite">{atLimit ? 'Podés guardar hasta tres zonas.' : saved ? `${zoneName} está en tu selección.` : 'La selección queda guardada sólo en este navegador.'}</span>
    </div>
  );
}
