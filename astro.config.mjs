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
  // 2026-10-06 合併：/map 已併入 /restaurants（同一頁地圖＋清單＋分區數字）。
  // 舊連結、書籤、search engine 一律 301 過去。
  redirects: {
    '/map': '/restaurants',
    '/en/map': '/en/restaurants',
    // 帶尾斜線嘅 /map/（舊連結都會開到）唔可以變 404 —— 由
    // public/map/index.html、public/en/map/index.html 兩張 meta-refresh 頁接住。
  },
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
