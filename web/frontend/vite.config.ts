import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

export default defineConfig({
  plugins: [svelte()],
  // Must match FastAPI StaticFiles mount at /static/ (works on direct :8080; nginx: proxy /static/ too).
  base: '/static/',
  build: {
    outDir: '../static',
    emptyOutDir: true,
    rollupOptions: {
      input: 'index.html',
    },
  },
});
