import { defineConfig } from 'astro/config';
import tailwindcss from '@tailwindcss/vite';
import mdx from '@astrojs/mdx';
import vercel from '@astrojs/vercel';

export default defineConfig({
  site: 'https://hk-pet-portal.vercel.app',
  output: 'static',
  adapter: vercel(),
  integrations: [mdx()],
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
