// Visual QA for the synthetic email rendered by scripts.preview_access_email.
// Browser rendering is not a substitute for testing actual email clients.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { chromium, webkit } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const backend = fileURLToPath(new URL('../', import.meta.url));
const output = path.join(backend, 'reports/email/preview');
const html = await fs.readFile(path.join(output, 'access-code.html'), 'utf8');
const scenarios = [];

async function screenshot(page, filename) {
  const height = await page.locator('.email-outer').evaluate(element => Math.ceil(element.getBoundingClientRect().height));
  await page.setViewportSize({width:page.viewportSize().width, height});
  await page.screenshot({path:path.join(output, filename), fullPage:true});
}

for (const [engine, launcher] of Object.entries({chromium, webkit})) {
  const browser = await launcher.launch({headless:true});
  try {
    for (const theme of ['light', 'dark']) {
      for (const width of [320, 390, 768, 1280]) {
        const context = await browser.newContext({viewport:{width, height:900}, colorScheme:theme});
        try {
          const page = await context.newPage();
          let externalRequests = 0;
          await page.route('**/*', route => { externalRequests++; return route.abort(); });
          await page.setContent(html);
          const layout = await page.evaluate(() => ({
            width:document.documentElement.scrollWidth,
            code:document.querySelector('.email-code').textContent,
          }));
          assert.ok(layout.width <= width, `${engine}/${theme}/${width}: horizontal overflow`);
          assert.equal(layout.code, '012345');
          const axe = await new AxeBuilder({page}).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
          assert.deepEqual(axe.violations.map(item => ({id:item.id, targets:item.nodes.map(node => node.target)})),
                           [], `${engine}/${theme}/${width}: accessibility`);
          assert.equal(externalRequests, 0);
          if ([390, 768].includes(width)) await screenshot(page, `${engine}-${theme}-${width}.png`);
          scenarios.push({engine, theme, width, overflow:false, accessibility_violations:0,
                          code_preserved:true, external_requests:0});
        } finally { await context.close(); }
      }
    }
    const context = await browser.newContext({viewport:{width:320, height:900}, colorScheme:'light'});
    try {
      const page = await context.newPage();
      await page.setContent(html.replace(/<style>[\s\S]*?<\/style>/i, ''));
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth) <= 320,
                `${engine}: inline-only styles overflow`);
      assert.equal(await page.locator('.email-code').textContent(), '012345');
      await screenshot(page, `${engine}-inline-only-320.png`);
      scenarios.push({engine, theme:'light', width:320, mode:'inline_only', overflow:false, code_preserved:true});
    } finally { await context.close(); }
  } finally { await browser.close(); }
}

const report = {synthetic_code:true, real_emails_sent:0, email_clients_tested:false,
                html_sha256:createHash('sha256').update(html).digest('hex'), scenarios};
await fs.writeFile(path.join(output, 'visual-validation.json'), JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify({scenarios:scenarios.length, engines:['chromium', 'webkit'],
                            horizontal_overflow:0, accessibility_violations:0, real_emails_sent:0}));
