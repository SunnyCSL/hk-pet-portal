import { defineConfig } from 'astro/config';
import tailwindcss from '@tailwindcss/vite';
import mdx from '@astrojs/mdx';
import vercel from '@astrojs/vercel';
import sitemap from '@astrojs/sitemap';
import { noindexSlugs } from './scripts/noindex-area-slugs.mjs';

// Sitemap filter: drop any area page that's noindex on the source page.
// noindexSlugs is computed once from the same JSON data the Astro pages
// use, so the union (`radius + name/address hit`) logic stays in lockstep.
// If a future area drops below the < 3 threshold, it lands here automatically.
function isNoindexAreaPage(urlString) {
  // urlString is a fully-qualified URL like
  // https://hk-pet-portal.vercel.app/restaurants/area/clear-water-bay or
  // https://hk-pet-portal.vercel.app/en/restaurants/area/clear-water-bay
  const m = urlString.match(/\/(en\/)?restaurants\/area\/([a-z0-9-]+)/);
  if (!m) return false;
  return noindexSlugs.has(m[2]);
}

export default defineConfig({
  site: 'https://hk-pet-portal.vercel.app',
  output: 'static',
  adapter: vercel(),
  integrations: [
    mdx(),
    sitemap({
      // Exclude pages that emit `<meta name="robots" content="noindex,follow">`
      // — these are thin area pages (currently 清水灣) that we keep for
      // direct-link UX but don't want Google to crawl as indexable URLs.
      filter: (pageUrl) => !isNoindexAreaPage(pageUrl),
    }),
  ],
  vite: {
    plugins: [tailwindcss()],
  },
  i18n: {
    defaultLocale: 'zh',
    locales: ['zh', 'en'],
    routing: {
      prefixDefaultLocale: false,
      redirectToDefaultLocale: false,
    },
  },
});
