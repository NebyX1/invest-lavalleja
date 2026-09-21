import type { APIRoute } from 'astro';

export const prerender = true;

export const GET: APIRoute = () => {
  const indexing = import.meta.env.PUBLIC_INDEXING === 'true' && Boolean(import.meta.env.PUBLIC_SITE_URL);
  const body = indexing ? `User-agent: *\nAllow: /\n${import.meta.env.PUBLIC_SITE_URL ? `Sitemap: ${import.meta.env.PUBLIC_SITE_URL.replace(/\/$/, '')}/sitemap-index.xml\n` : ''}` : 'User-agent: *\nDisallow: /\n';
  return new Response(body, { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
};
