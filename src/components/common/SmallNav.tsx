import { useEffect, useState } from 'react';
import { $savedZones, initializeClientState } from '../../stores/state';
import { useStore } from '@nanostores/react';

interface Props {
  currentPath: string;
}

const navItems = [
  ['/por-que-lavalleja/', 'Por qué Lavalleja'],
  ['/oportunidades/', 'Oportunidades'],
  ['/territorio/', 'Territorio'],
  ['/como-invertir/', 'Cómo invertir'],
  ['/gianna/', 'Gianna'],
] as const;

function isActive(currentPath: string, path: string) {
  return currentPath === path || (path !== '/' && currentPath.startsWith(path));
}

function Brand() {
  return (
    <a className="wordmark" href="/" aria-label="Invest Lavalleja, inicio" data-astro-prefetch>
      <svg className="brand-mark" viewBox="0 0 48 48" fill="none" aria-hidden="true">
        <path d="M5 35 17 13l9 14 7-10 10 18H5Z" stroke="currentColor" strokeWidth="1.5" />
        <path d="m12 35 11-17 13 17M5 40h38" stroke="currentColor" strokeWidth="1.1" />
        <circle cx="36" cy="9" r="3" fill="currentColor" />
      </svg>
      <span className="brand-name"><b>INVEST</b><small>LAVALLEJA</small></span>
    </a>
  );
}

function DossierBadge() {
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

export default function SmallNav({ currentPath }: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const closeMenu = () => setMenuOpen(false);

  useEffect(() => {
    const onPageLoad = () => closeMenu();
    document.addEventListener('astro:page-load', onPageLoad);
    return () => document.removeEventListener('astro:page-load', onPageLoad);
  }, []);

  return (
    <header className="site-header small-nav" transition-name="site-header">
      <div className="nav-shell glass">
        <Brand />
        <div className="nav-tools">
          <a className="btn square nav-search" href="/recursos/#buscar" data-open-search aria-label="Buscar información">
            <svg className="icon" viewBox="0 0 24 24" aria-hidden="true"><use href="#icon-search" /></svg>
          </a>
          <a className="btn square dossier-link" href="/mi-dossier/" aria-label="Abrir mi dossier" data-astro-prefetch>
            <svg className="icon" viewBox="0 0 24 24" aria-hidden="true"><use href="#icon-bookmark" /></svg>
            <DossierBadge />
          </a>
          <button
            className="btn square mobile-toggle"
            type="button"
            data-menu-toggle
            aria-label={menuOpen ? 'Cerrar menú' : 'Abrir menú'}
            aria-expanded={menuOpen}
            aria-controls="primary-nav"
            onClick={() => setMenuOpen((open) => !open)}
          >
            <svg className="icon" viewBox="0 0 24 24" aria-hidden="true"><use href="#icon-menu" /></svg>
          </button>
        </div>
        <nav className={`nav-links${menuOpen ? ' is-open' : ''}`} id="primary-nav" aria-label="Principal" data-mobile-nav>
          {navItems.map(([href, label]) => (
            <a key={href} href={href} className={isActive(currentPath, href) ? 'active' : undefined} data-astro-prefetch onClick={closeMenu}>
              {label}
            </a>
          ))}
          <a className="nav-download" href="/documentos/folleto-invest-lavalleja.pdf" download="folleto-invest-lavalleja.pdf" onClick={closeMenu} aria-label="Descargar folleto Invest Lavalleja (PDF)">
            Folleto PDF <svg className="icon" viewBox="0 0 24 24" aria-hidden="true"><use href="#icon-download" /></svg>
          </a>
          <a className="btn primary small nav-project" href="/tu-proyecto/" data-astro-prefetch onClick={closeMenu}>
            Tu proyecto <svg className="icon" viewBox="0 0 24 24" aria-hidden="true"><use href="#icon-up" /></svg>
          </a>
        </nav>
      </div>
    </header>
  );
}
