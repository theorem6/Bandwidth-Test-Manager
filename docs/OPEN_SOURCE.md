# Open source & third-party software (Bandwidth Test Manager)

**Project license:** [MIT License](../LICENSE).

This app combines a **Python** backend (FastAPI, Uvicorn) and a **Svelte** + **Vite** frontend. Third-party components are used under their respective licenses.

## Direct dependencies

### Python (`web/requirements.txt`)

| Package | License (typical) |
|---------|-------------------|
| **FastAPI** | MIT |
| **Uvicorn** | BSD-3-Clause |
| **Starlette** (FastAPI dependency) | BSD-3-Clause |
| **Pydantic** (FastAPI dependency) | MIT |

Verify installed versions: `pip show fastapi uvicorn`.

### Frontend (`web/frontend/package.json`)

| Package | SPDX |
|---------|------|
| **Svelte** | MIT |
| **Vite**, **@sveltejs/vite-plugin-svelte** | MIT |
| **TypeScript** | Apache-2.0 |
| **Bootstrap** | MIT |
| **bootstrap-icons** | MIT |
| **Chart.js** | MIT |
| **chartjs-plugin-zoom** | MIT |
| **Hammer.js** (transitive, zoom) | MIT |

Run `npx license-checker@25.0.1 --production --direct` in `web/frontend` for a machine-readable list including transitive packages.

## External tools (not bundled)

- **Ookla Speedtest CLI** — subject to Ookla’s license and accept-license terms when installed on the server.
- **iperf3** — BSD-3-Clause (typical system package).

## Hosted services

If you connect to external speedtest or iperf endpoints, their operators’ terms apply.

---

**Last updated:** March 2026.
