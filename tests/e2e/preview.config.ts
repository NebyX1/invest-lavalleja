import { defineConfig, devices } from '@playwright/test';

// Run against an already started Astro preview when Windows cannot supervise its child process.
export default defineConfig({
  testDir: '.',
  timeout: 30_000,
  use: { baseURL: process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:4321' },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['Pixel 5'] } },
  ],
});
