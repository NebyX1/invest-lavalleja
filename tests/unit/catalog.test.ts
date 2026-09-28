import { describe, expect, it } from 'vitest';
import { catalog, normalizePath, pages, routeManifest } from '../../src/data/site';
import { mapLocations, mapViewBox } from '../../src/data/map-locations';

describe('catálogo Invest Lavalleja', () => {
  it('conserva las 30 rutas de la referencia sin duplicados', () => {
    expect(pages).toHaveLength(30);
    expect(new Set(routeManifest.map((route) => route.path)).size).toBe(30);
    expect(routeManifest[0].path).toBe('/');
    expect(routeManifest.some((route) => route.path === '/mi-dossier/')).toBe(true);
  });

  it('mantiene referencias de sectores, zonas, casos y fuentes válidas', () => {
    const sourceIds = new Set(catalog.sources.map((source) => source.id));
    const sectorIds = new Set(catalog.sectors.map((sector) => sector.id));
    for (const sector of catalog.sectors) {
      expect(sector.sources.every((id) => sourceIds.has(id))).toBe(true);
      expect(sector.checks.length).toBeGreaterThan(0);
    }
    for (const zone of catalog.zones) {
      expect(zone.sectors.every((id) => sectorIds.has(id))).toBe(true);
      expect(zone.sources.every((id) => sourceIds.has(id))).toBe(true);
      expect(zone.position).toHaveLength(2);
    }
    for (const item of catalog.cases) expect(sourceIds.has(item.source)).toBe(true);
  });

  it('normaliza rutas y búsquedas con tildes de forma determinista', () => {
    expect(normalizePath('/zonas/minas')).toBe('/zonas/minas/');
    expect(normalizePath('/')).toBe('/');
    expect('José Pedro Varela'.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()).toBe('jose pedro varela');
  });

  it('vincula las seis localidades del SVG a perfiles territoriales válidos', () => {
    const zoneIds = new Set(catalog.zones.map((zone) => zone.id));
    expect(mapLocations).toHaveLength(6);
    expect(new Set(mapLocations.map((location) => location.id)).size).toBe(mapLocations.length);
    for (const location of mapLocations) {
      expect(zoneIds.has(location.zoneId)).toBe(true);
      expect(location.x).toBeGreaterThanOrEqual(0);
      expect(location.x).toBeLessThanOrEqual(mapViewBox.width);
      expect(location.y).toBeGreaterThanOrEqual(0);
      expect(location.y).toBeLessThanOrEqual(mapViewBox.height);
    }
  });
});
