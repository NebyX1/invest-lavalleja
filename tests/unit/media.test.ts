import fs from 'node:fs';
import path from 'node:path';
import { tmpdir } from 'node:os';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { pages } from '../../src/data/site';

const bannerNames = ['agro-conceptual.webp', 'hospitalidad-conceptual.webp', 'serrano-conceptual.webp'];

describe('organización de los recursos visuales', () => {
  it('mantiene los tres banners dentro de block-banners y no deja copias antiguas públicas', () => {
    for (const name of bannerNames) {
      expect(fs.existsSync(new URL(`../../public/media/block-banners/${name}`, import.meta.url))).toBe(true);
      expect(fs.existsSync(new URL(`../../public/media/${name}`, import.meta.url))).toBe(false);
    }
  });

  it('las páginas declaran las dimensiones 16:9 y usan las rutas nuevas', () => {
    const html = pages.flatMap((page) => page.parts.map((part) => part.type === 'html' ? part.content : '')).join('\n');
    const images = [...html.matchAll(/<img\b[^>]*>/g)].map((match) => match[0]);
    expect(images.length).toBeGreaterThan(0);
    for (const image of images) {
      expect(image).toMatch(/src="\/media\/block-banners\//);
      expect(image).toContain('width="1600"');
      expect(image).toContain('height="900"');
      expect(image).toMatch(/\balt="/);
    }
    expect(html).not.toMatch(/\/media\/(?:agro|hospitalidad|serrano)-conceptual\.webp/);
  });

  it('conserva la geometría original del mapa en su carpeta específica', () => {
    const map = fs.readFileSync(new URL('../../public/media/map/Lavalleja-Map.svg', import.meta.url), 'utf8');
    expect(map).toContain('viewBox="0 0 713 779"');
    expect(fs.existsSync(new URL('../../public/media/Lavalleja-Map.svg', import.meta.url))).toBe(false);
  });

  it('el extractor migra las rutas sin sobrescribir los banners editados', () => {
    const fixtureRoot = fs.mkdtempSync(path.join(tmpdir(), 'invest-media-'));
    try {
      const html = bannerNames.map((name) => `<img src="/media/${name}" width="1942" height="267" alt=""/>`).join('');
      const fixturePages = [{ path: '/', title: 'Prueba', parts: [{ type: 'html', content: html }] }];
      const fixtureAssets = Object.fromEntries(bannerNames.map((name) => [`/media/${name}`, 'data:image/webp;base64,b3JpZ2luYWw=']));
      const reference = `<style>.fixture{}</style><script id="catalog-data">{"sectors":[]}</script>`
        + `<script id="pages-data">${JSON.stringify(fixturePages)}</script><script id="asset-data">${JSON.stringify(fixtureAssets)}</script>`;
      fs.writeFileSync(path.join(fixtureRoot, 'Invest_Lavalleja_Vista_Previa.html'), reference);
      const script = fileURLToPath(new URL('../../scripts/extract-reference.mjs', import.meta.url));
      const missing = spawnSync(process.execPath, [script], { cwd: fixtureRoot, encoding: 'utf8' });
      expect(missing.status).not.toBe(0);
      expect(missing.stderr).toContain('Falta el banner 16:9');
      expect(fs.existsSync(path.join(fixtureRoot, 'src/data/pages.json'))).toBe(false);

      fs.mkdirSync(path.join(fixtureRoot, 'public/media/block-banners'), { recursive: true });
      for (const name of bannerNames) fs.writeFileSync(path.join(fixtureRoot, 'public/media/block-banners', name), 'edited-banner');
      const extracted = spawnSync(process.execPath, [script], { cwd: fixtureRoot, encoding: 'utf8' });
      expect(extracted.status, extracted.stderr).toBe(0);
      const result = fs.readFileSync(path.join(fixtureRoot, 'src/data/pages.json'), 'utf8');
      expect(result).not.toContain('/media/agro-conceptual.webp');
      const normalized = JSON.parse(result)[0].parts[0].content as string;
      expect([...normalized.matchAll(/width="1600" height="900"/g)]).toHaveLength(3);
      for (const name of bannerNames) {
        expect(normalized).toContain(`/media/block-banners/${name}`);
        expect(fs.readFileSync(path.join(fixtureRoot, 'public/media/block-banners', name), 'utf8')).toBe('edited-banner');
      }
    } finally {
      fs.rmSync(fixtureRoot, { recursive: true, force: true });
    }
  }, 15_000);
});
