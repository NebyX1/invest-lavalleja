import { defineConfig } from 'astro/config';
import react from '@astrojs/react';
import sitemap from '@astrojs/sitemap';
import tailwindcss from '@tailwindcss/vite';

const siteUrl = process.env.PUBLIC_SITE_URL?.trim();

export default defineConfig({
  site: siteUrl || undefined,
  integrations: [react(), ...(siteUrl ? [sitemap()] : [])],
  prefetch: {
    defaultStrategy: 'hover',
  },
  vite: {
    plugins: [tailwindcss()],
  },
  markdown: {
    shikiConfig: {
      themes: {
        light: 'github-dark',
        dark: 'github-dark',
      },
    },
  },
});
