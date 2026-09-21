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

test('menú móvil, PDF y accesibilidad básica', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByRole('button', { name: /abrir menú/i }).click();
  await expect(page.locator('[data-mobile-nav]')).toHaveClass(/is-open/);
  const pdf = await page.request.get('/documentos/folleto-invest-lavalleja.pdf');
  expect(pdf.ok()).toBe(true);
  await page.goto('/recursos/');
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
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
  await page.screenshot({ path: `${captureDir}/project-wizard.png`, fullPage: true });
});

declare global {
  interface Window { __investTestMarker?: string }
}
