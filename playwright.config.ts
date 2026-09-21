import { defineConfig, devices } from '@playwright/test';

const previewMode = process.env.PLAYWRIGHT_PREVIEW === 'true';

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  fullyParallel: true,
  reporter: [['list'], ['html', { outputFolder: 'reports/playwright', open: 'never' }]],
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:4321',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  webServer: {
    command: previewMode ? 'node scripts/serve-preview-for-tests.mjs' : 'node scripts/serve-for-tests.mjs',
    url: 'http://127.0.0.1:4321',
    reuseExistingServer: true,
    timeout: 120_000,
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['Pixel 5'] } },
  ],
});
