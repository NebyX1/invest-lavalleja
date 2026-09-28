import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs';

const routeManifest = JSON.parse(fs.readFileSync(new URL('../../src/data/route-manifest.json', import.meta.url), 'utf8')) as { path: string; title: string }[];

async function waitForIsland(page: import('@playwright/test').Page, componentName: string): Promise<void> {
  const island = page.locator(`astro-island[component-url*="${componentName}"]`);
  await expect(island).toHaveCount(1);
  await expect.poll(() => island.getAttribute('ssr'), { timeout: 10_000 }).toBeNull();
}

test('todas las rutas del manifiesto responden con contenido propio', async ({ page }) => {
  test.setTimeout(60_000);
  for (const route of routeManifest) {
    const response = await page.goto(route.path, { waitUntil: 'domcontentloaded' });
    expect(response?.status(), route.path).toBe(200);
    await expect(page.locator('main h1').first(), route.path).toBeVisible();
    await expect(page).toHaveTitle(new RegExp(route.title.split('|')[0].trim().slice(0, 18)));
  }
});

test('navegación interna conserva el documento y actualiza el contenido', async ({ page }) => {
  await page.goto('/');
  await page.waitForTimeout(500);
  const marker = await page.evaluate(() => {
    window.__investTestMarker = `marker-${Date.now()}`;
    return { marker: window.__investTestMarker, timeOrigin: performance.timeOrigin };
  });
  await page.getByRole('link', { name: /explorar oportunidades/i }).first().click();
  await expect(page).toHaveURL(/\/oportunidades\/$/);
  expect(await page.evaluate(() => window.__investTestMarker)).toBe(marker.marker);
  expect(await page.evaluate(() => performance.timeOrigin)).toBe(marker.timeOrigin);
  await expect(page.locator('main h1')).toContainText('Encontrá una actividad');
  for (const path of ['/territorio/', '/zonas/minas/', '/sectores/turismo/', '/recursos/', '/']) {
    await page.goto(path);
    await expect(page.locator('main h1').first()).toBeVisible();
  }
});

test('dossier persiste entre navegación y recarga', async ({ page }) => {
  await page.goto('/zonas/minas/');
  await waitForIsland(page, 'SaveZone');
  await page.getByRole('button', { name: /guardar esta zona/i }).click();
  await expect(page.getByRole('button', { name: /guardada en mi dossier/i })).toBeVisible();
  await page.goto('/mi-dossier/');
  await expect(page.locator('.dossier-card')).toContainText('Minas');
  await page.reload();
  await expect(page.locator('.dossier-card')).toContainText('Minas');
});

test('buscador global responde a Ctrl+K y navega con resultado real', async ({ page }) => {
  await page.goto('/');
  await waitForIsland(page, 'GlobalSearch');
  await page.keyboard.press('Control+K');
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.locator('#global-search-input').fill('UNESCO');
  await page.getByRole('dialog').locator('[role="option"]').first().click();
  await expect(page).toHaveURL(/\/fuentes\//);
});

test('asistente de proyecto guarda respuestas de la sesión', async ({ page }) => {
  await page.goto('/tu-proyecto/');
  await waitForIsland(page, 'ProjectWizard');
  await page.getByRole('button', { name: /^Turismo\b/ }).click();
  await expect(page.locator('.wizard-nav button').filter({ hasText: 'Continuar' })).toBeEnabled();
  await page.locator('.wizard-nav button').filter({ hasText: 'Continuar' }).click();
  await page.getByRole('button', { name: /idea en exploración/i }).click();
  await page.getByRole('button', { name: /continuar/i }).click();
  await page.getByRole('checkbox', { name: /localización/i }).check();
  await page.goto('/tu-proyecto/');
  await expect(page.locator('.wizard')).toContainText('Turismo');
});

test('el asistente conserva un ancho legible en escritorio, tablet y móvil', async ({ page }) => {
  await page.goto('/tu-proyecto/');
  await waitForIsland(page, 'ProjectWizard');

  for (const [width, height, minimumWizardWidth] of [
    [1920, 1080, 700],
    [1366, 768, 600],
    [1024, 768, 500],
    [768, 1024, 650],
    [390, 844, 300],
  ]) {
    await page.setViewportSize({ width, height });
    const layout = await page.evaluate(() => {
      const wizard = document.querySelector('.wizard')!;
      const bounds = wizard.getBoundingClientRect();
      const progress = [...document.querySelectorAll<HTMLElement>('.wizard-progress span')].map((item) => {
        const rect = item.getBoundingClientRect();
        return { left: rect.left, right: rect.right, height: rect.height, background: getComputedStyle(item).backgroundColor };
      });
      return {
        wizardWidth: bounds.width,
        documentWidth: document.documentElement.scrollWidth,
        progress,
      };
    });

    expect(layout.wizardWidth, `wizard width at ${width}px`).toBeGreaterThanOrEqual(minimumWizardWidth);
    expect(layout.documentWidth, `horizontal overflow at ${width}px`).toBeLessThanOrEqual(width);
    for (const [index, item] of layout.progress.entries()) {
      expect(item.height, `progress step ${index + 1} is collapsed at ${width}px`).toBeGreaterThanOrEqual(36);
      expect(item.background, `progress step ${index + 1} has a stray fill at ${width}px`).toBe('rgba(0, 0, 0, 0)');
    }
    for (let index = 1; index < layout.progress.length; index += 1) {
      expect(layout.progress[index]!.left, `progress labels overlap at ${width}px`).toBeGreaterThanOrEqual(layout.progress[index - 1]!.right - 1);
    }
  }
});

test('menú móvil, PDF y accesibilidad básica', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByRole('button', { name: /abrir menú/i }).click();
  await expect(page.locator('[data-mobile-nav]')).toHaveClass(/is-open/);
  const pdf = await page.request.get('/documentos/folleto-invest-lavalleja.pdf');
  expect(pdf.ok()).toBe(true);
  expect(pdf.headers()['content-type']).toContain('application/pdf');
  expect(Number(pdf.headers()['content-length'])).toBeGreaterThan(0);
  await page.goto('/recursos/');
  await expect(page.getByRole('link', { name: 'Descargar folleto', exact: true })).toHaveAttribute('download', 'folleto-invest-lavalleja.pdf');
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});

test('la descarga del folleto se promociona en portada y funciona en distintos tamaños', async ({ page }) => {
  for (const [width, height] of [[1920, 1080], [1366, 768], [1024, 768], [768, 1024], [390, 844]]) {
    await page.setViewportSize({ width, height });
    await page.goto('/');

    const heroDownload = page.getByRole('link', { name: /descargar el folleto invest lavalleja 2026 en pdf/i });
    await expect(heroDownload).toBeVisible();
    await expect(heroDownload).toHaveAttribute('download', 'folleto-invest-lavalleja.pdf');
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    const bounds = await heroDownload.boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
  }

  const downloadStarted = page.waitForEvent('download');
  await page.getByRole('link', { name: /descargar el folleto invest lavalleja 2026 en pdf/i }).click();
  const download = await downloadStarted;
  expect(download.suggestedFilename()).toBe('folleto-invest-lavalleja.pdf');
});

test('el mapa selecciona localidades y perfiles en escritorio y móvil', async ({ page }, testInfo) => {
  const isMobile = testInfo.project.name === 'mobile';
  await page.setViewportSize(isMobile ? { width: 390, height: 844 } : { width: 1440, height: 900 });
  await page.goto('/');
  await expect(page.getByRole('heading', { name: /elegí por lo que tu proyecto necesita/i })).toBeVisible();
  const map = page.getByTestId('lavalleja-map');
  await map.scrollIntoViewIfNeeded();
  await waitForIsland(page, 'Explorer');

  const mapImage = map.locator('img');
  await expect.poll(() => mapImage.evaluate((image: HTMLImageElement) => image.complete && image.naturalWidth > 0)).toBe(true);
  const mapSize = await map.boundingBox();
  expect(mapSize).not.toBeNull();
  expect(Math.abs((mapSize!.width / mapSize!.height) - (713 / 779))).toBeLessThan(0.03);

  const minasButton = map.getByRole('button', { name: /seleccionar minas/i });
  await minasButton.click();
  await expect(minasButton).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('.explorer-detail h3')).toHaveText('Minas y su entorno');

  const varelaButton = map.getByRole('button', { name: /seleccionar josé pedro varela/i });
  await varelaButton.click();
  await expect(varelaButton).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('.explorer-detail h3')).toHaveText('José Pedro Varela');

  await page.getByRole('button', { name: /villa serrana \/ penitente/i }).click();
  await expect(page.locator('.explorer-detail h3')).toHaveText('Villa Serrana, Penitente y Marco de los Reyes');
  await expect(page.getByRole('link', { name: /abrir ficha de villa serrana/i })).toHaveAttribute('href', '/zonas/villa-serrana-penitente/');
  const columnCount = await page.locator('.explorer-main').evaluate((element) => getComputedStyle(element).gridTemplateColumns.trim().split(/\s+/).length);
  expect(columnCount).toBe(isMobile ? 1 : 2);
  if (isMobile) expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  const accessibility = await new AxeBuilder({ page }).include('.explorer').analyze();
  expect(accessibility.violations).toEqual([]);
});

test('genera capturas de referencia del portal', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium', 'Las capturas se generan una vez en escritorio');
  const captureDir = 'reports/captures';
  fs.mkdirSync(captureDir, { recursive: true });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');
  await page.screenshot({ path: `${captureDir}/home-1440.png`, fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByRole('button', { name: /abrir menú/i }).click();
  await page.screenshot({ path: `${captureDir}/menu-mobile-390.png`, fullPage: true });

  await page.setViewportSize({ width: 1440, height: 900 });
  for (const [path, filename] of [
    ['/sectores/turismo/', 'sector-turismo.png'],
    ['/zonas/minas/', 'zona-minas.png'],
    ['/territorio/', 'explorer.png'],
  ] as const) {
    await page.goto(path);
    await page.locator('main h1').first().waitFor();
    await page.screenshot({ path: `${captureDir}/${filename}`, fullPage: true });
  }

  await page.goto('/');
  await waitForIsland(page, 'GlobalSearch');
  await page.keyboard.press('Control+K');
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.locator('#global-search-input').fill('UNESCO');
  await page.screenshot({ path: `${captureDir}/search-dialog.png`, fullPage: true });

  await page.goto('/zonas/minas/');
  await waitForIsland(page, 'SaveZone');
  await page.getByRole('button', { name: /guardar esta zona/i }).click();
  await page.goto('/mi-dossier/');
  await waitForIsland(page, 'DossierIsland');
  await page.screenshot({ path: `${captureDir}/dossier.png`, fullPage: true });

  await page.goto('/tu-proyecto/');
  await waitForIsland(page, 'ProjectWizard');
  await page.getByRole('button', { name: /^Turismo\b/ }).click();
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.screenshot({ path: `${captureDir}/project-wizard.png`, fullPage: true });
});

declare global {
  interface Window { __investTestMarker?: string }
}
