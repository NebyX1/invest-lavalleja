import { useEffect, useState } from 'react';
import { useStore } from '@nanostores/react';
import { $savedZones, initializeClientState } from '../../stores/state';

export default function DossierCount() {
  const zones = useStore($savedZones);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      initializeClientState();
      setMounted(true);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  const count = mounted ? zones.length : 0;
  return <span className="saved-count" aria-label={`${count} zonas guardadas`}>{count}</span>;
}
