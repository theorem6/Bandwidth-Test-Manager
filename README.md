# Bandwidth Test Manager

Linux-based speedtest utility using **Ookla Speedtest CLI** and **iperf3**, with configurable sites, optional scheduling, CSV reporting, and a **web UI** with per-site and master graphs. **Outgoing only:** the app runs tests from this server to external speedtest/iperf servers; it does not host a speedtest or iperf server for others.

See **[PROJECT-CONTEXT.md](PROJECT-CONTEXT.md)** for full behavior, options, and usage. For turning this into a vital **ISP tool** (SLAs, alerting, multi-probe, reports), see **[docs/ISP-ROADMAP.md](docs/ISP-ROADMAP.md)**.

## Quick start (Linux)

1. **One-shot install** (deps + scripts + config + web UI)
   ```bash
   sudo ./install.sh
   ```
   Use `sudo ./install.sh --no-web` to skip the web interface.

2. **Configure sites** (optional)  
   Edit `/etc/netperf/config.json` or use **Settings** in the web UI to choose Ookla servers, iperf3 hosts/tests, and cron schedule.

3. **Start/stop scheduled testing**
   ```bash
   sudo netperf-scheduler start   # run tests per cron_schedule in config (default :05 every hour), log under /var/log/netperf/YYYYMMDD
   sudo netperf-scheduler stop     # remove schedule
   ```
   Or use **Scheduler** in the web UI to start/stop. The cron schedule is configurable in **Settings** (e.g. `5 * * * *`).

4. **Web interface** (if installed)
   - Open the **Site URL** from Settings (e.g. `https://your-server.netperf/`). Use HTTPS with no port in the URL; run `sudo ./web/setup-https.sh` on the server once to enable it.
   - **Landing:** read-only dashboard and scheduler toggle; **Login** (admin) unlocks the full menu.
   - **Setup:** backend status, **Install / fix dependencies**, **Users** (configurable auth: add/update users, passwords stored hashed), **Recent SLA alerts**, timezone/NTP, purge old data (retention).
   - **Dashboard:** date picker, per-site and trend graphs (download/upload/latency, iperf). **Run test now** (admin), CSV export, **Download summary (30d)**.
   - **Scheduler:** start or stop the test cron.
   - **Settings:** site URL, SSL, speed limit, cron, Ookla/iperf servers, **probe identity**, **SLA thresholds & webhook**, **data retention**, **Appearance** (light/dark/system theme).
   - **Remote nodes:** Add remote probes (POPs, customer sites) that report back to this server. For each node: **Download script** (bash agent with URL + token), run on the remote machine (e.g. via cron); results appear under that node. Each node has its own **dashboard page** (graphs filtered by node).

5. **Generate speedtest report** (CLI, after some runs)
   ```bash
   sudo netperf-reporter -s /var/log/netperf/YYYYMMDD
   ```

## Web UI (Svelte + TypeScript)

The UI is built with **Svelte**, **TypeScript**, and **Vite**. Before deploying (or to refresh the UI), build the frontend:

```bash
cd web/frontend && npm install && npm run build
```

This writes the app into `web/static/`. The FastAPI backend serves it at `/` and `/static/`.

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
  git pull origin master
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
- **Push changes:** `git add . && git commit -m "..." && git push origin master`
- **Releases:** Tags and release assets are created from the repo. To create a release, tag and push, then create a release in GitHub (or use `gh release create`).
  ```bash
  git tag -a v1.0.0 -m "Release v1.0.0"
  git push origin v1.0.0
  ```
  Then open the repo on GitHub → Releases → Draft a new release, choose the tag, add notes, and publish.
