# Netperf UI (Svelte + TypeScript + Vite)

Build the frontend before deploying. Output goes to `web/static/` (overwrites that folder).

```bash
cd web/frontend
npm install
npm run build
```

Then deploy the project as usual; FastAPI serves `web/static/index.html` at `/` and `/static/` for assets.

- **Dev:** `npm run dev` (Vite dev server; set API proxy to backend or use full URL)
- **Preview:** `npm run preview` (serve production build locally)
