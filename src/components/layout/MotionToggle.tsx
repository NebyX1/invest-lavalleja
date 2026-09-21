import { useEffect, useState } from 'react';
import { useStore } from '@nanostores/react';
import { $movementPaused, initializeClientState, setMovementPaused } from '../../stores/state';

export default function MotionToggle() {
  const paused = useStore($movementPaused);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      initializeClientState();
      setMounted(true);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  const isPaused = mounted && paused;
  useEffect(() => {
    document.documentElement.dataset.motionPaused = isPaused ? 'true' : 'false';
  }, [isPaused]);

  return (
    <button className="motion-toggle" type="button" onClick={() => setMovementPaused(!isPaused)} aria-pressed={isPaused}>
      <svg className="icon" viewBox="0 0 24 24" aria-hidden="true"><use href="#icon-sun" /></svg>
      {isPaused ? 'Activar movimiento' : 'Pausar movimiento'}
    </button>
  );
}
