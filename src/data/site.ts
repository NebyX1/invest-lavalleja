import catalogJson from './catalog.json';
import pagesJson from './pages.json';
import type { Catalog, EditorialPage, SearchEntry } from '../types';

export const catalog = catalogJson as Catalog;
export const pages = pagesJson as EditorialPage[];

export const sectorsById = new Map(catalog.sectors.map((sector) => [sector.id, sector]));
export const zonesById = new Map(catalog.zones.map((zone) => [zone.id, zone]));
export const sourcesById = new Map(catalog.sources.map((source) => [source.id, source]));

export function normalizePath(path: string): string {
  const value = path.split('?')[0].split('#')[0];
  if (value === '/') return value;
  return `/${value.replace(/^\/+|\/+$/g, '')}/`;
}

export function getPage(path: string): EditorialPage | undefined {
  return pages.find((page) => page.path === normalizePath(path));
}

function stripHtml(value: string): string {
  return value
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

const pageEntries: SearchEntry[] = pages.map((page) => ({
  id: `page:${page.path}`,
  title: page.title,
  type: 'Página',
  excerpt: page.description || stripHtml(page.parts.find((part) => part.type === 'html')?.content ?? '').slice(0, 180),
  path: page.path,
}));

const sectorEntries: SearchEntry[] = catalog.sectors.map((sector) => ({
  id: `sector:${sector.id}`,
  title: sector.name,
  type: 'Sector',
  excerpt: sector.description,
  path: `/sectores/${sector.id}/`,
}));

const zoneEntries: SearchEntry[] = catalog.zones.map((zone) => ({
  id: `zone:${zone.id}`,
  title: zone.name,
  type: 'Zona',
  excerpt: zone.summary,
  path: `/zonas/${zone.id}/`,
}));

const caseEntries: SearchEntry[] = catalog.cases.map((item) => ({
  id: `case:${item.id}`,
  title: item.name,
  type: 'Historia',
  excerpt: item.text,
  path: `/historias/${item.id}/`,
}));

const sourceEntries: SearchEntry[] = catalog.sources.map((source) => ({
  id: `source:${source.id}`,
  title: source.title,
  type: 'Fuente',
  excerpt: source.scope,
  path: `/fuentes/#${source.id}`,
}));

export const searchIndex: SearchEntry[] = [
  ...pageEntries,
  ...sectorEntries,
  ...zoneEntries,
  ...caseEntries,
  ...sourceEntries,
];

export const routeManifest = pages.map(({ path, title }) => ({ path, title }));
