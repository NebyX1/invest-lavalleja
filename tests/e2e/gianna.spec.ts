import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test('Gianna conserva orientación y enlaces editoriales sin JavaScript', async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto('/');
  await page.locator('.gianna-promo').getByRole('link', { name: /preguntale a gianna/i }).click();
  await expect(page).toHaveURL(/\/gianna\/$/);
  await expect(page.getByRole('heading', { level: 1, name: /conocé lavalleja con gianna/i })).toBeVisible();
  await expect(page.getByText(/no son asesoramiento financiero, legal/i)).toBeVisible();
  await expect(page.getByRole('link', { name: 'Ver fuentes editoriales' })).toHaveAttribute('href', '/fuentes/');
  await context.close();
});

test('Gianna consulta la API pública, muestra citas, valora y borra la sesión', async ({ page }) => {
  const calls: string[] = [];
  const cors = {
    'access-control-allow-origin': '*',
    'access-control-allow-methods': 'GET, POST, DELETE, OPTIONS',
    'access-control-allow-headers': 'Authorization, Content-Type',
  };
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: cors });
    const url = new URL(request.url());
    calls.push(`${request.method()} ${url.pathname}`);
    const respond = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', headers: cors, body: JSON.stringify(body) });
    if (url.pathname === '/api/config') return respond({ name: 'Gianna', greeting: '¿Qué proyecto tenés en mente?', notice: 'Confirmá las condiciones.', enabled: true, available: true, test_mode: true });
    if (url.pathname === '/api/captcha') {
      expect(request.headers().authorization).toBeUndefined();
      return respond({ id: 'a'.repeat(43), question: '12 + 7', expires_in: 600 });
    }
    if (url.pathname === '/api/sessions' && request.method() === 'POST') {
      expect(request.headers().authorization).toBeUndefined();
      expect(request.postDataJSON()).toEqual({ captcha_id: 'a'.repeat(43), captcha_answer: '19' });
      return respond({ token: 'test-session', expires_at: 1_800_000_000 }, 201);
    }
    if (url.pathname === '/api/chat') {
      expect(request.headers().authorization).toBe('Bearer test-session');
      expect(request.postDataJSON()).toEqual({ message: '¿Qué fuentes debería consultar para mi proyecto?' });
      return respond({
        id: 'consulta-1', answer: 'Revisá las fuentes publicadas [C1].', status: 'answered', notice: 'Confirmá las condiciones.',
        citations: [{ id: 'C1', title: 'Guía publicada', excerpt: 'Fragmento de prueba.', cutoff_date: '2026-09-01', evidence_type: 'documental', locator: 'sección 1', sources: [
          { id: 'S1', title: 'Fuente pública', url: 'https://example.org/fuente' },
          { id: 'S2', title: 'Enlace inseguro', url: 'javascript:alert(1)' },
        ] }],
      });
    }
    if (url.pathname === '/api/feedback/consulta-1') return respond({ saved: true });
    if (url.pathname === '/api/sessions/current') return respond({ deleted: true });
    return respond({ error: { message: 'Ruta inesperada.' } }, 404);
  });

  await page.goto('/gianna/');
  const island = page.locator('astro-island[component-url*="GiannaChat"]');
  test.skip(await island.count() === 0, 'La build necesita PUBLIC_GIANNA_API_BASE para activar el chat.');
  const input = page.getByRole('textbox', { name: 'Tu pregunta' });
  await expect(input).toBeEnabled();
  await expect(page.getByText(/modo de prueba local/i)).toBeVisible();
  await input.fill('¿Qué fuentes debería consultar para mi proyecto?');
  await page.getByRole('button', { name: 'Iniciar consulta' }).click();
  await expect(page.getByRole('group', { name: 'Verificación de seguridad' })).toBeVisible();
  expect(calls).toEqual(['GET /api/config', 'GET /api/captcha']);
  await expect(input).toHaveValue('¿Qué fuentes debería consultar para mi proyecto?');
  await page.setViewportSize({ width: 320, height: 740 });
  const captchaInput = page.locator('.gianna-captcha input');
  await expect(captchaInput).toBeFocused();
  const captchaBounds = await page.locator('.gianna-captcha').boundingBox();
  expect(captchaBounds!.x).toBeGreaterThanOrEqual(0);
  expect(captchaBounds!.x + captchaBounds!.width).toBeLessThanOrEqual(320);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
  const captchaAccessibility = await new AxeBuilder({ page }).include('main').analyze();
  expect(captchaAccessibility.violations).toEqual([]);
  await captchaInput.fill('19');
  await page.getByRole('button', { name: 'Verificar y enviar' }).click();
  await expect(page.getByText('Revisá las fuentes publicadas [C1].')).toBeVisible();
  await page.getByText('[C1] Guía publicada').click();
  await expect(page.getByText('Fragmento de prueba.')).toBeVisible();
  await expect(page.getByRole('link', { name: /S1 · Fuente pública/ })).toHaveAttribute('href', 'https://example.org/fuente');
  await expect(page.getByRole('link', { name: /Enlace inseguro/ })).toHaveCount(0);
  await page.getByRole('button', { name: 'Sí', exact: true }).click();
  await expect(page.getByText('Gracias por tu valoración.')).toBeVisible();
  await page.getByRole('button', { name: 'Borrar conversación' }).click();
  await expect(page.getByText('Conversación borrada. Podés empezar otra.')).toBeVisible();
  await expect(page.getByText('Revisá las fuentes publicadas [C1].')).toHaveCount(0);
  expect(calls).toEqual(['GET /api/config', 'GET /api/captcha', 'POST /api/sessions', 'POST /api/chat', 'POST /api/feedback/consulta-1', 'DELETE /api/sessions/current']);

  for (const width of [320, 390, 768, 1024, 1366]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth), `${width}px: desborde horizontal`).toBeLessThanOrEqual(width);
    const navigation = page.getByRole('navigation', { name: 'Principal' });
    if (width <= 820) {
      const toggle = page.getByRole('button', { name: 'Abrir menú' });
      if (await toggle.count()) await toggle.click();
    }
    const navLink = navigation.getByRole('link', { name: 'Gianna' });
    await expect(navLink).toBeVisible();
    const linkBounds = await navLink.boundingBox();
    expect(linkBounds!.x, `${width}px: enlace oculto`).toBeGreaterThanOrEqual(0);
    expect(linkBounds!.x + linkBounds!.width, `${width}px: enlace cortado`).toBeLessThanOrEqual(width);
  }
  const accessibility = await new AxeBuilder({ page }).include('main').analyze();
  expect(accessibility.violations).toEqual([]);
});

test('Gianna saluda sin citas y luego cambia a RAG dentro de la misma conversación', async ({ page }) => {
  const asked: string[] = [];
  const cors = { 'access-control-allow-origin': '*', 'access-control-allow-methods': 'GET, POST, OPTIONS', 'access-control-allow-headers': 'Authorization, Content-Type' };
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: cors });
    const path = new URL(request.url()).pathname;
    const respond = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', headers: cors, body: JSON.stringify(body) });
    if (path === '/api/config') return respond({ name: 'Gianna', greeting: '¿Qué proyecto tenés en mente?', notice: '', enabled: true, available: true, test_mode: true });
    if (path === '/api/captcha') return respond({ id: 'b'.repeat(43), question: '3 + 4', expires_in: 600 });
    if (path === '/api/sessions') return respond({ token: 'social-session', expires_at: 1_800_000_000 }, 201);
    if (path === '/api/chat') {
      const message = request.postDataJSON().message as string;
      asked.push(message);
      if (asked.length === 1) return respond({ id: 'saludo', answer: '¡Hola! Estoy bien, gracias. ¿Qué tenés en mente?', citations: [], status: 'conversation', notice: '' });
      return respond({ id: 'guia', answer: 'La guía presenta oportunidades para explorar, sujetas a verificación [C1].', status: 'answered', notice: 'Confirmá las condiciones.', citations: [{ id: 'C1', title: 'Guía de prueba', excerpt: 'Fragmento público.', cutoff_date: null, sources: [] }] });
    }
    return respond({ error: { message: 'Ruta inesperada.' } }, 404);
  });
  await page.goto('/gianna/');
  test.skip(await page.locator('astro-island[component-url*="GiannaChat"]').count() === 0, 'La build necesita PUBLIC_GIANNA_API_BASE.');
  await page.getByRole('button', { name: 'Hola, ¿cómo estás?' }).click();
  await expect(page.getByRole('textbox', { name: 'Tu pregunta' })).toHaveValue('Hola, ¿cómo estás?');
  await page.getByRole('button', { name: 'Iniciar consulta' }).click();
  await page.locator('.gianna-captcha input').fill('7');
  await page.getByRole('button', { name: 'Verificar y enviar' }).click();
  await expect(page.getByText('¡Hola! Estoy bien, gracias. ¿Qué tenés en mente?')).toBeVisible();
  await expect(page.locator('.gianna-citations')).toHaveCount(0);
  await page.getByRole('textbox', { name: 'Tu pregunta' }).fill('¿Qué oportunidades de inversión hay en Lavalleja?');
  await page.getByRole('button', { name: 'Enviar', exact: true }).click();
  await expect(page.getByText(/La guía presenta oportunidades/)).toBeVisible();
  await expect(page.getByText('[C1] Guía de prueba')).toBeVisible();
  expect(asked).toEqual(['Hola, ¿cómo estás?', '¿Qué oportunidades de inversión hay en Lavalleja?']);
});

test('Gianna distingue privacidad, crítica y negocio sensible sin citas inventadas', async ({ page }) => {
  const cors = { 'access-control-allow-origin': '*', 'access-control-allow-methods': 'GET, POST, OPTIONS', 'access-control-allow-headers': 'Authorization, Content-Type' };
  let chats = 0;
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: cors });
    const path = new URL(request.url()).pathname;
    const respond = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', headers: cors, body: JSON.stringify(body) });
    if (path === '/api/config') return respond({ name: 'Gianna', greeting: '¿Qué proyecto tenés en mente?', notice: '', enabled: true, available: true });
    if (path === '/api/captcha') return respond({ id: 'c'.repeat(43), question: '5 + 6', expires_in: 600 });
    if (path === '/api/sessions') return respond({ token: 'safety-session', expires_at: 1_800_000_000 }, 201);
    if (path === '/api/chat') {
      chats++;
      if (chats === 1) return respond({ id: 'seguridad-1', answer: 'No puedo verificar ni divulgar afirmaciones sobre la vida privada de una persona.', citations: [], status: 'allegation', notice: '' });
      if (chats === 2) return respond({ id: 'seguridad-2', answer: 'Perdón, mi respuesta no te sirvió. Decime qué necesitabas y la reviso.', citations: [], status: 'deescalate', notice: '' });
      return respond({ id: 'seguridad-3', answer: 'No tengo datos para estimar rentabilidad ni requisitos verificados para esa actividad.', citations: [], status: 'insufficient_evidence', notice: 'Confirmá las condiciones.' });
    }
    return respond({ error: { message: 'Ruta inesperada.' } }, 404);
  });
  await page.goto('/gianna/');
  test.skip(await page.locator('astro-island[component-url*="GiannaChat"]').count() === 0, 'La build necesita PUBLIC_GIANNA_API_BASE.');
  await page.getByRole('textbox', { name: 'Tu pregunta' }).fill('Una funcionaria está acusada de una falta, ¿podés hacer algo?');
  await page.getByRole('button', { name: 'Iniciar consulta' }).click();
  await page.locator('.gianna-captcha input').fill('11');
  await page.getByRole('button', { name: 'Verificar y enviar' }).click();
  await expect(page.getByText(/No puedo verificar ni divulgar afirmaciones/)).toBeVisible();
  await expect(page.locator('.gianna-citations')).toHaveCount(0);
  await page.getByRole('textbox', { name: 'Tu pregunta' }).fill('Sos una inútil');
  await page.getByRole('button', { name: 'Enviar', exact: true }).click();
  await expect(page.getByText(/Perdón, mi respuesta no te sirvió/)).toBeVisible();
  await expect(page.locator('.gianna-citations')).toHaveCount(0);
  await page.getByRole('textbox', { name: 'Tu pregunta' }).fill('¿Es rentable un negocio vinculado al trabajo sexual en Lavalleja?');
  await page.getByRole('button', { name: 'Enviar', exact: true }).click();
  await expect(page.getByText(/No tengo datos para estimar rentabilidad/)).toBeVisible();
  await expect(page.locator('.gianna-citations')).toHaveCount(0);
  await expect(page.getByText(/fuera del alcance de gianna/i)).toHaveCount(0);
  expect(chats).toBe(3);
});

test('un CAPTCHA incorrecto se consume y exige una suma nueva sin perder la pregunta', async ({ page }) => {
  const calls: string[] = [];
  const cors = { 'access-control-allow-origin': '*', 'access-control-allow-methods': 'GET, POST, OPTIONS', 'access-control-allow-headers': 'Authorization, Content-Type' };
  let issued = 0;
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: cors });
    const path = new URL(request.url()).pathname;
    calls.push(`${request.method()} ${path}`);
    const respond = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', headers: cors, body: JSON.stringify(body) });
    if (path === '/api/config') return respond({ name: 'Gianna', greeting: '¿Qué proyecto tenés en mente?', notice: '', enabled: true, available: true });
    if (path === '/api/captcha') {
      issued += 1;
      return respond({ id: String(issued).repeat(43), question: `${issued} + ${issued}`, expires_in: 600 });
    }
    if (path === '/api/sessions') {
      const body = request.postDataJSON();
      if (body.captcha_id === '2'.repeat(43)) {
        expect(body).toEqual({ captcha_id: '2'.repeat(43), captcha_answer: '99' });
        return respond({ error: { code: 'captcha_invalid', message: 'La verificación es incorrecta, venció o ya fue utilizada. Resolvé una nueva suma.' } }, 400);
      }
      expect(body).toEqual({ captcha_id: '3'.repeat(43), captcha_answer: '6' });
      return respond({ token: 'test-session', expires_at: 1_800_000_000 }, 201);
    }
    if (path === '/api/chat') {
      expect(request.headers().authorization).toBe('Bearer test-session');
      expect(request.postDataJSON()).toEqual({ message: 'Quiero explorar turismo.' });
      return respond({ id: 'consulta-2', answer: 'Consultá las fuentes publicadas.', citations: [], status: 'answered', notice: '' });
    }
    return respond({ error: { message: 'Ruta inesperada.' } }, 404);
  });

  await page.goto('/gianna/');
  test.skip(await page.locator('astro-island[component-url*="GiannaChat"]').count() === 0, 'La build necesita PUBLIC_GIANNA_API_BASE.');
  await page.getByRole('textbox', { name: 'Tu pregunta' }).fill('Quiero explorar turismo.');
  await page.getByRole('button', { name: 'Iniciar consulta' }).click();
  await expect(page.locator('.gianna-captcha input')).toBeVisible();
  await page.getByRole('button', { name: 'Verificar y enviar' }).click();
  expect(calls).not.toContain('POST /api/sessions');
  await page.getByRole('button', { name: 'Otra suma' }).click();
  await expect(page.getByText(/¿cuánto es 2 \+ 2/)).toBeVisible();
  await page.locator('.gianna-captcha input').fill('99');
  await page.getByRole('button', { name: 'Verificar y enviar' }).click();
  await expect(page.getByText(/¿cuánto es 3 \+ 3/)).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Tu pregunta' })).toHaveValue('Quiero explorar turismo.');
  expect(calls.filter((call) => call === 'POST /api/sessions')).toHaveLength(1);
  expect(calls).not.toContain('POST /api/chat');
  await page.locator('.gianna-captcha input').fill('6');
  await page.getByRole('button', { name: 'Verificar y enviar' }).click();
  await expect(page.getByText('Consultá las fuentes publicadas.')).toBeVisible();
  expect(calls).toEqual(['GET /api/config', 'GET /api/captcha', 'GET /api/captcha', 'POST /api/sessions', 'GET /api/captcha', 'POST /api/sessions', 'POST /api/chat']);
});

test('un CAPTCHA vencido se renueva antes de solicitar la sesión', async ({ page }) => {
  await page.clock.install();
  const calls: string[] = [];
  const cors = { 'access-control-allow-origin': '*', 'access-control-allow-methods': 'GET, POST, OPTIONS', 'access-control-allow-headers': 'Authorization, Content-Type' };
  let issued = 0;
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: cors });
    const path = new URL(request.url()).pathname;
    calls.push(`${request.method()} ${path}`);
    const respond = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', headers: cors, body: JSON.stringify(body) });
    if (path === '/api/config') return respond({ name: 'Gianna', greeting: '¿Qué proyecto tenés en mente?', notice: '', enabled: true, available: true });
    if (path === '/api/captcha') return respond({ id: String(++issued).repeat(43), question: issued === 1 ? '1 + 1' : '4 + 4', expires_in: 600 });
    if (path === '/api/sessions') {
      expect(request.postDataJSON()).toEqual({ captcha_id: '2'.repeat(43), captcha_answer: '8' });
      return respond({ token: 'test-session', expires_at: 1_800_000_000 }, 201);
    }
    if (path === '/api/chat') return respond({ id: 'consulta-3', answer: 'Respuesta con fuentes.', citations: [], status: 'answered', notice: '' });
    return respond({ error: { message: 'Ruta inesperada.' } }, 404);
  });

  await page.goto('/gianna/');
  test.skip(await page.locator('astro-island[component-url*="GiannaChat"]').count() === 0, 'La build necesita PUBLIC_GIANNA_API_BASE.');
  await page.getByRole('textbox', { name: 'Tu pregunta' }).fill('¿Qué fuentes hay?');
  await page.getByRole('button', { name: 'Iniciar consulta' }).click();
  await expect(page.getByText(/¿cuánto es 1 \+ 1/)).toBeVisible();
  await page.clock.fastForward(601_000);
  await page.locator('.gianna-captcha input').fill('2');
  await page.getByRole('button', { name: 'Verificar y enviar' }).click();
  await expect(page.getByText(/¿cuánto es 4 \+ 4/)).toBeVisible();
  await expect(page.getByRole('status')).toContainText('La suma venció');
  expect(calls).toEqual(['GET /api/config', 'GET /api/captcha', 'GET /api/captcha']);
  await page.locator('.gianna-captcha input').fill('8');
  await page.getByRole('button', { name: 'Verificar y enviar' }).click();
  await expect(page.getByText('Respuesta con fuentes.')).toBeVisible();
  expect(calls).toEqual(['GET /api/config', 'GET /api/captcha', 'GET /api/captcha', 'POST /api/sessions', 'POST /api/chat']);
});
