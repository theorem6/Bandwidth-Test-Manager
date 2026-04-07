# Bandwidth Test Manager

Linux-based speedtest utility using **Ookla Speedtest CLI** and **iperf3**, with configurable sites, optional scheduling, CSV reporting, and a **web UI** with per-site and master graphs. **Outgoing only:** the app runs tests from this server to external speedtest/iperf servers; it does not host a speedtest or iperf server for others.

See **[PROJECT-CONTEXT.md](PROJECT-CONTEXT.md)** for full behavior, options, and usage. For turning this into a vital **ISP tool** (SLAs, alerting, multi-probe, reports), see **[docs/ISP-ROADMAP.md](docs/ISP-ROADMAP.md)**.

## Quick start (Linux)

1. **One-shot install** (deps + scripts + config + web UI). If you run `install.sh` without a full project tree beside it, the script downloads a source archive automatically (no `git clone` required). Installer output is generic; set `BWM_DEBUG=1` to print fetch URLs if something fails.

   **Copy-paste install (this repository):**

   ```bash
   curl -fsSL https://raw.githubusercontent.com/theorem6/Bandwidth-Test-Manager/main/install.sh | sudo bash
   ```

   The default branch for this repo is **`main`**. The full install includes the web UI (FastAPI + built static assets under `/opt/netperf-web`).

   CLI + cron only (no web app):

   ```bash
   curl -fsSL https://raw.githubusercontent.com/theorem6/Bandwidth-Test-Manager/main/install.sh | sudo bash -s -- --no-web
   ```

   **Other sources:** pipe any hosted raw `install.sh` into bash (your fork, mirror, or release). **Source archive:** `install.sh` uses `BWM_REPO` (HTTPS git web root) and `BWM_REF` (branch). Override when not using the defaults inside the script:

   ```bash
   curl -fsSL 'https://raw.githubusercontent.com/OWNER/REPO/main/install.sh' | sudo env BWM_REPO='https://github.com/OWNER/REPO' BWM_REF='main' bash
   ```

   If you already have a full clone, run `sudo ./install.sh` from the project root instead (nothing is re-downloaded).

   **GitHub URLs (bookmark for tests and automation)**

   | What | URL |
   |------|-----|
   | **One-line install (pipe to bash)** | `https://raw.githubusercontent.com/theorem6/Bandwidth-Test-Manager/main/install.sh` |
   | **Repository (browser)** | [github.com/theorem6/Bandwidth-Test-Manager](https://github.com/theorem6/Bandwidth-Test-Manager) |

   **Smoke-test the web UI** after install (Uvicorn only, no nginx): open **`http://<server>:8080/`** (root). Use your HTTPS **Site URL** from Settings when behind nginx (`/netperf/` path). Assets are served at both `/static/…` and `/netperf/static/…` so the UI loads correctly with or without a reverse proxy.

2. **Branding (web UI)**  
   After install, open the web UI (see table above). Log in as admin, go to **Setup**, and use **Site branding (optional)** to set title, tagline, logo, and primary color. Click **Save branding** or run **Install / fix dependencies** (branding is saved first). Full theme options are under **Settings → Appearance**. For HTTPS and a public path like `/netperf/`, run `sudo ./web/setup-https.sh` on the server.

3. **Configure sites** (optional)  
   Edit `/etc/netperf/config.json` or use **Settings** in the web UI to choose Ookla servers, iperf3 hosts/tests, and cron schedule.

4. **Start/stop scheduled testing**
   ```bash
   sudo netperf-scheduler start   # run tests per cron_schedule in config (default :05 every hour), log under /var/log/netperf/YYYYMMDD
   sudo netperf-scheduler stop     # remove schedule
   ```
   Or use **Scheduler** in the web UI to start/stop. The cron schedule is configurable in **Settings** (e.g. `5 * * * *`).

5. **Web interface** (if installed)
   - Open the **Site URL** from Settings (e.g. `https://your-server.netperf/`). Use HTTPS with no port in the URL; run `sudo ./web/setup-https.sh` on the server once to enable it.
   - **Landing:** read-only dashboard and scheduler toggle; **Login** (admin) unlocks the full menu.
   - **Setup:** **Site branding** (title, tagline, logo, primary color), backend status, **Install / fix dependencies**, **Users** (configurable auth), **Recent SLA alerts**, timezone/NTP, purge old data (retention).
   - **Dashboard:** date picker, **Range** (Full day / Last 12 hours / Last 6 hours), per-site and trend graphs (download/upload/latency, iperf). When viewing **today**, graphs extend to current time (line holds last speed to now). **Drag to pan, scroll to zoom** on day charts; **Reset zoom** to restore. **Run test now** (admin), CSV export, **Download summary (30d)**.
   - **Scheduler:** start or stop the test cron.
   - **Settings:** site URL, SSL, speed limit, cron, Ookla/iperf servers, **probe identity**, **SLA thresholds & webhook**, **data retention**, **Appearance** (light/dark/system theme).
   - **Remote nodes:** Add remote probes (POPs, customer sites) that report back to this server. For each node: **Download script** (bash agent with URL + token), run on the remote machine (e.g. via cron); results appear under that node. Each node has its own **dashboard page** (graphs filtered by node).

6. **Generate speedtest report** (CLI, after some runs)
   ```bash
   sudo netperf-reporter -s /var/log/netperf/YYYYMMDD
   ```

## Web UI (Svelte + TypeScript)

The UI is built with **Svelte**, **TypeScript**, and **Vite**. Before deploying (or to refresh the UI), build the frontend:

```bash
cd web/frontend && npm install && npm run build
```

This writes the app into `web/static/`. The FastAPI backend serves it at `/` and `/static/`, and also at `/netperf/static/` so built assets match the Vite base path when hitting Uvicorn directly.

## Private GitLab / offline bundle

The public one-liner uses GitHub `raw.githubusercontent.com`. For a **private** GitLab project (for example [engineering/bandwidth-test-manager](https://gitlab.hyperionsolutionsgroup.net/engineering/bandwidth-test-manager)), ship a **tarball** plus a small **download-and-install** script.

### 1. Build the tarball (on a machine with the repo)

```bash
cd web/frontend && npm ci && npm run build && cd ../..
./pack-release.sh
```

Creates `dist/bandwidth-test-manager-YYYYMMDD-<gitsha>.tar.gz` (gitignored). Upload it to a GitLab **Release**, artifact bucket, or internal HTTPS host. On Windows: `.\pack-release.ps1` (same output under `dist\`).

### 2a. Install using a GitLab token (reads the archive API)

On the target server you need a [Personal Access Token](https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html) or Deploy Token with **`read_repository`**. Copy [`private-download-install.sh`](private-download-install.sh) to the server (for private repos you cannot anonymously `curl` raw files from GitLab).

```bash
sudo GITLAB_TOKEN="glpat_xxxxxxxx" \
  GITLAB_URL="https://gitlab.hyperionsolutionsgroup.net" \
  GITLAB_PROJECT_PATH="engineering/bandwidth-test-manager" \
  GITLAB_REF="main" \
  bash private-download-install.sh
```

CLI-only: add `--no-web` at the end. Optional: `BWM_TARBALL_URL` pointing at a hosted `pack-release` `.tar.gz` instead of GitLab API; optional `BWM_HTTP_HEADER` for authenticated download.

### 2b. Install from a hosted tarball only

```bash
sudo BWM_TARBALL_URL="https://your-host/releases/bandwidth-test-manager.tar.gz" bash private-download-install.sh
```

### 2c. Manual extract

```bash
tar xzf bandwidth-test-manager-*.tar.gz
sudo ./install.sh
```

See `etc/install-bundle-readme.txt` inside the archive.

## One-server deployment (GCE)

Deploy to a GCE instance: the script builds the frontend, copies the project to the instance, and runs `install.sh` (and web finish) on the server. The install script installs Ookla Speedtest CLI, iperf3, jq, mtr, netperf scripts, config dirs, and the web app (venv + systemd).

**Linux / macOS (bash):**
```bash
./deploy-gce.sh INSTANCE_NAME [ZONE] [PROJECT]
```
Example: `./deploy-gce.sh acs-hss-server us-central1-a`

**Deploy from Windows**

- **Option A (PowerShell):** From the project directory run: `.\deploy-gce.ps1 INSTANCE_NAME [ZONE] [PROJECT]` (e.g. `.\deploy-gce.ps1 acs-hss-server us-central1-a`). If you see a reauth error, run `gcloud auth login` in a terminal first.
- **Option B (bash):** Use WSL or Git Bash and run: `bash deploy-gce.sh INSTANCE_NAME [ZONE] [PROJECT]`.
- **Option C (from server):** SSH into the instance, then clone (or pull) and install:
  ```bash
  git clone https://github.com/theorem6/Bandwidth-Test-Manager.git
  cd Bandwidth-Test-Manager
  cd web/frontend && npm install && npm run build && cd ../..
  sudo ./install.sh
  ```
  Existing `/etc/netperf/config.json` is kept. Start the scheduler if needed: `sudo netperf-scheduler start`.

- **Update existing deployment (from server):** If the repo is already on the server, pull and reinstall the web app:
  ```bash
  cd /path/to/Bandwidth-Test-Manager
  git pull origin main
  cd web/frontend && npm run build && cd ../..
  sudo ./install.sh
  ```
  Existing config is kept; the web app and static files are updated and the service is restarted.

- Builds the Svelte frontend, streams the project to the instance, runs `install.sh` and finishes the web setup.
- If port 8080 is in use on the server, the web UI is installed on **8081**; the deploy script syncs nginx to the correct port automatically. To fix 502 after a port change, run on the server: `sudo bash scripts/sync-nginx-netperf-port.sh`.
- Existing `/etc/netperf/config.json` on the server is kept.
- Requires: `gcloud` CLI and a Debian/Ubuntu instance.

## Git and releases

- **Clone:** `git clone <repo-url> && cd Bandwidth-Test-Manager`
- **Push changes:** `git add . && git commit -m "..." && git push origin main`
- **Releases:** Tags and release assets are created from the repo. To create a release, tag and push, then create a release in GitHub (or use `gh release create`).
  ```bash
  git tag -a v1.0.0 -m "Release v1.0.0"
  git push origin v1.0.0
  ```
  Then open the repo on GitHub → Releases → Draft a new release, choose the tag, add notes, and publish.

## License

This project is released under the [MIT License](LICENSE).

**Third-party software:** See [docs/OPEN_SOURCE.md](docs/OPEN_SOURCE.md) for dependency and tooling attribution.
