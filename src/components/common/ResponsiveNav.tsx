import { useEffect, useState } from 'react';
import BigNab from './BigNab';
import SmallNav from './SmallNav';

interface Props {
  currentPath: string;
}

type NavigationMode = 'desktop' | 'mobile';

export default function ResponsiveNav({ currentPath }: Props) {
  const [mode, setMode] = useState<NavigationMode>('desktop');
  const [activePath, setActivePath] = useState(currentPath);

  useEffect(() => {
    const mediaQuery = window.matchMedia('(max-width: 820px)');
    const updateMode = () => setMode(mediaQuery.matches ? 'mobile' : 'desktop');
    updateMode();
    mediaQuery.addEventListener('change', updateMode);
    return () => mediaQuery.removeEventListener('change', updateMode);
  }, []);

  useEffect(() => {
    const updatePath = () => setActivePath(window.location.pathname);
    document.addEventListener('astro:page-load', updatePath);
    return () => document.removeEventListener('astro:page-load', updatePath);
  }, []);

  return mode === 'mobile' ? <SmallNav currentPath={activePath} /> : <BigNab currentPath={activePath} />;
}
