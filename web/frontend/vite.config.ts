import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

export default defineConfig({
  plugins: [svelte()],
  base: '/netperf/static/',
  build: {
    outDir: '../static',
    emptyOutDir: true,
    rollupOptions: {
      input: 'index.html',
    },
  },
});
