# Bandwidth Test Manager – Project Context

## Overview

- **Linux-based speedtest utility** for automated and logged bandwidth testing.
- **Outgoing only:** This service runs tests **from** this server **to** external Ookla and iperf3 servers. It does **not** host a speedtest or iperf3 server for others to connect to. The web UI and cron only initiate outbound tests and display results.
- **Core tools:** Ookla Speedtest CLI (command line) and **iperf3** (client only).
- Optional: **mtr**, **jq** (required for reporter).
- **Configurable sites:** Ookla servers and iperf3 servers/tests are defined in `/etc/netperf/config.json` and can be edited in the web UI. Cron schedule is also in config.
- **Web interface:** Optional web app (FastAPI + Uvicorn on port 8080) with **Setup** (**Site branding** in the browser: title, tagline, logo, primary color — saved with **Save branding** or before **Install / fix dependencies**; install/fix dependencies, **Users** for configurable auth, **Recent SLA alerts**, timezone/NTP, purge), **Dashboard** (graphs with **date + Range** filter: Full day, Last 12h, Last 6h; when viewing today, x-axis extends to current time and the line holds the last speed to now with no new dot; **pan/zoom** on day charts to scroll back through time, **Reset zoom** to restore; CSV/summary export), **Scheduler** (start/stop cron; shows schedule and frequency), **Settings** (config, probe identity, SLA thresholds & webhook, retention, **Appearance** light/dark/system), and **Remote nodes** (add probes that report back; download agent script per node; per-node dashboard). UI is responsive. HTTPS via nginx. Public read-only landing; admin login for full access.
- **Data:** Results stored in **SQLite** (`/var/log/netperf/netperf.db`); log files under `/var/log/netperf/YYYYMMDD/` are imported on read. Optional **probe_id** for multi-site; **retention_days** and purge from Setup. **Remote nodes** table stores node_id, name, location, token; ingest API accepts POST with **X-Node-Token** and writes results with that node’s probe_id.

---

## Install

**One-line install (no clone; downloads source if needed):** as root, pipe the raw `install.sh` from the repo into bash. Example for the public GitHub `main` branch:

```bash
curl -fsSL https://raw.githubusercontent.com/theorem6/Bandwidth-Test-Manager/main/install.sh | sudo bash
```

- Without a complete tree beside `install.sh`, the script fetches sources: **`BWM_SOURCE=archive`** (default) downloads a **GitHub-style tarball** (`BWM_REPO` = HTTPS web root, `BWM_REF` = **branch name** only); **`BWM_SOURCE=git`** runs **`git clone`** (`BWM_REPO` = clone URL, `BWM_REF` = branch, tag, or commit). Git is installed via the OS package manager if missing. Set `BWM_DEBUG=1` for verbose errors.
- **Private GitLab:** use `pack-release.sh` to produce `dist/*.tar.gz`, and `private-download-install.sh` on the server with `GITLAB_TOKEN` (or `BWM_TARBALL_URL`). See README **Private GitLab / offline bundle**.
- **Web UI asset paths:** Vite `base` is `/static/`; FastAPI serves `StaticFiles` at `/static/`. Behind nginx with a `/netperf/` location, also proxy `/static/` (see `web/nginx-netperf-path.conf`).
- After install, open the web UI and use **Setup → Site branding** (admin) to white-label the app without editing JSON by hand.

**On the server (as root), from a full clone:**

```bash
sudo ./install.sh
```

- Installs OS packages via `scripts/linux-deps.sh` (Debian/Ubuntu, Fedora/RHEL family, SUSE, Alpine, Arch), Ookla Speedtest CLI, iperf3, mtr, jq; optional trickle on Debian; copies scripts to `/bin`, creates `/etc/netperf/config.json` from `etc/netperf-config.json`. For the web UI it installs **Node.js 18+** and runs **`npm ci` / `npm run build`** in `web/frontend` (unless `SKIP_NPM_BUILD=1`), then installs Python venv under `/opt/netperf-web` (enables **systemd** when present).
- Use `sudo ./install.sh --no-web` to skip the web interface.
- Web port is configurable: set `PORT=8081` (or other) before running to use a different port (e.g. if 8080 is in use).

**Deploy to existing GCE instance (from local machine):**

```bash
./deploy-gce.sh INSTANCE_NAME [ZONE] [PROJECT]
```

- Copies project to the instance and runs `install.sh`. If port 8080 is in use on the server, the web UI is installed on 8081. Does not overwrite existing `/etc/netperf/config.json`.

**HTTPS (server already has a certificate):** On the server run `sudo ./web/setup-https.sh [domain]` (e.g. `hyperionsolutionsgroup.com` or a hostname that matches your certificate). The script detects Let's Encrypt or system certs, installs nginx if needed, and configures a reverse proxy to the web app. If nginx reports a conflicting server name, add inside your existing server block: `include /etc/nginx/snippets/netperf-proxy.conf;` then `sudo nginx -t && sudo systemctl reload nginx`. Ensure firewall allows tcp/443.

---

## Core Setup (manual)

```bash
curl -s https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | sudo bash
sudo apt install -y speedtest iperf3 mtr jq
sudo speedtest --accept-license
```

---

## Config (Ookla & iperf sites)

- Path: `/etc/netperf/config.json`.
- **site_url:** full HTTPS URL where the app is served (e.g. `https://hyperionsolutionsgroup.com/netperf/`). Used by the HTTPS setup script for redirects and domain detection.
- **ssl_cert_path** / **ssl_key_path:** server paths to the TLS certificate and private key. The `setup-https.sh` script reads these from config so the server uses the cert you configure.
- **speedtest_limit_mbps:** optional number (e.g. `100`) or `null`. When set, speedtest runs are throttled using `trickle`. Omit or leave empty for no limit.
- **cron_schedule:** cron expression for when tests run (e.g. `5 * * * *` = 5 min past every hour). Used by `netperf-scheduler start`. Editable in Settings.
- **ookla_servers:** list of `{ "id": <number> or "auto" or "local", "label": "Label" }`. Use `"id": "auto"` for Ookla’s default server selection (no `-s`). Use `"id": "local"` for automated ISP/near-POP selection via **`netperf-resolve-ookla-local`**: runs `speedtest -L -f json`, then (see below) picks one server id and `netperf-tester` runs `speedtest -s <id> -f json`. If resolution fails, behaves like `auto`.
- **ookla_local_patterns:** optional list of strings. If **non-empty**, only these substrings are used to filter the server list (name, location, host, sponsor; case-insensitive); **ookla_local_auto_isp** is ignored for filtering. If **empty**, behavior depends on **ookla_local_auto_isp**.
- **ookla_local_auto_isp:** boolean (default **true**). When **true** and patterns are empty: read ISP from **`$NETPERF_STORAGE/.ookla_isp_cache.json`** (or `/var/log/netperf/.ookla_isp_cache.json`); if missing or older than **7 days**, run one `speedtest -f json` (Ookla auto), parse `isp` / `client.isp`, update cache, then prefer servers whose listing matches significant tokens from that ISP name; if no match, use all servers. Always then choose the smallest **distance** (km) among candidates. When **false** and patterns are empty, all listed servers are candidates (distance only).
- **iperf_servers:** list of `{ "host": "hostname", "label": "label" }`.
- **iperf_tests:** list of `{ "name": "single", "args": "-P 1" }` (args are iperf3 client flags).
- **iperf_duration_seconds:** duration in seconds for each iperf3 test (default 10). Editable in Settings.
- **probe_id**, **location_name**, **region**, **tier:** optional identity for this probe (ISP/multi-site). Stored with results.
- **sla_thresholds:** `min_download_mbps`, `min_upload_mbps`, `max_latency_ms`. When violated, webhook is called (with cooldown).
- **webhook_url**, **webhook_secret:** URL and optional secret header for SLA violation POSTs.
- **retention_days:** optional; purge (Setup) deletes data older than this (default 30 when omitted).
- **auth_users:** optional list of `{ "username", "password_hash", "role" }`. When set, replaces built-in users; use **Setup → Users** to add/update (passwords stored hashed).
- **branding:** optional object for white-label UI: `app_title`, `tagline`, `logo_url` (path or `https://`), `logo_alt`, hex colors (`primary_color`, `primary_hover_color`, `navbar_gradient_start` / `end` for the navbar title text, `navbar_bg_start` / `end` for dark-theme navbar gradient), and `custom_css` (injected into the page; no `script` / `javascript:`). **Setup → Site branding** (admin) sets the main fields from the browser (saved with **Save branding** or before **Install / fix dependencies**). **Settings → Appearance** has the full theme editor. **POST /api/branding/logo** (admin) uploads a logo into `static/uploads/`. **GET /api/branding** is public (no auth) so the login page matches your brand.
- All of the above (except auth_users) are editable via **Settings**; auth is managed in **Setup → Users**. After changing site URL or cert paths, run `sudo ./web/setup-https.sh` on the server to apply.

---

## Scripts

| Script | Path | Purpose |
|--------|------|---------|
| **netperf-scheduler** | `/bin/netperf-scheduler` | Enable/disable automated speed test logging via cron (schedule from config) |
| **netperf-cron-run** | `/bin/netperf-cron-run` | Wrapper for cron: runs netperf-tester with today’s log dir |
| **netperf-tester** | `/bin/netperf-tester` | Run tests (Ookla + iperf3) using **config**; append to daily log dir |
| **netperf-resolve-ookla-local** | `/bin/netperf-resolve-ookla-local` | Resolve numeric Ookla server id for `"local"` mode (Python 3); called by netperf-tester |
| **netperf-reporter** | `/bin/netperf-reporter` | Parse and combine output (speedtest CSV; locations from filenames) |

All must be run as root. Tester reads `/etc/netperf/config.json` (or `NETPERF_CONFIG`).

---

## netperf-scheduler

- **Usage:** `netperf-scheduler [start | stop | h]`
- **start:** Adds cron job using **cron_schedule** from config (default `5 * * * *`), restarts cron. The cron job runs `/bin/netperf-cron-run`, which invokes netperf-tester with `/var/log/netperf/YYYYMMDD` for the current date.
- **stop:** Removes netperf cron job, restarts cron.
- **Install from web UI:** The **Setup** page includes **Site branding** and shows backend status (speedtest, iperf3, jq, config, cron). **Install / fix dependencies** saves branding first, then runs `/opt/netperf-web/install-deps.sh` (Ookla repo, apt install speedtest iperf3 jq mtr, accept license, copy scripts to `/bin`). The web service must run as root for this to succeed.

---

## netperf-tester

- **Usage:** `netperf-tester STORAGE_LOCATION` (or `-h` for help).
- **Storage:** Single argument = directory for the day, e.g. `/var/log/netperf/20250313`.

**Tests run (in order, with ~10s sleep between):**

1. **Ookla Speedtest (JSON):** one run per entry in **ookla_servers** (filename prefix `0_`, `1_`, … and label from config, lowercased). Each entry uses `speedtest -f json`, or `speedtest -s <id> -f json` for a fixed id, or for `"local"` runs `netperf-resolve-ookla-local` then `-s` that id (fallback: same as auto).

2. **iperf3** (to `9000.mtu.he.net`):
   - Single stream → `iperf-single-stream.txt`
   - 8 parallel streams → `iperf-multi-stream.txt`
   - UDP 1G → `iperf-udp.txt`

---

## netperf-reporter

- **Usage:** `netperf-reporter [speedtest | iperf] STORAGE_LOCATION` (or `-h`).
- **speedtest:** Reads `[0-9]_speedtest-*` in `STORAGE_LOCATION`, uses **jq** to parse JSON, outputs CSV report: `netperf-report-YYYYMMDD_NN.csv`. Locations: LOCAL, FL, IL, NC, WA.
- **iperf:** Not implemented yet.

---

## Crontab / Aliases (one-time setup)

```bash
echo -e "alias crontab='EDITOR=nano crontab'" >> .bash_aliases && . .bash_aliases
# Root crontab template is in the original spec (SHELL, PATH, comments).
```

---

## Remote nodes (multi-probe reporting)

- **Purpose:** Deploy a small agent on remote machines (POPs, customer sites) so they run speedtest/iperf and report results back to this main server. Each remote is a **node** with its own dashboard.
- **Flow:** In the UI, **Remote nodes** → Add node (name, location). The server creates the node and shows a **token** (once) and a **Download script** button. The script is a bash file with `MAIN_URL` and `NODE_TOKEN` already set. On the remote machine: install `speedtest` (Ookla CLI) and optionally `iperf3`, make the script executable, run it (e.g. via cron). The script POSTs JSON to `MAIN_URL/api/remote/ingest` with header `X-Node-Token: NODE_TOKEN`; the server stores results with `probe_id` = that node’s ID and updates `last_seen_at`.
- **API:** `POST /api/remote/ingest` (no user auth; uses `X-Node-Token`). Body: `{ "log_date": "YYYYMMDD", "speedtest": [ { "site", "timestamp", "download_bps", "upload_bps", "latency_ms" } ], "iperf": [ { "site", "timestamp", "bits_per_sec" } ] }`. Admin-only: `GET/POST /api/remote/nodes`, `GET/DELETE /api/remote/nodes/{node_id}`, `GET /api/remote/script/{node_id}` (download script with URL and token injected).
- **DB:** Table `remote_nodes` (node_id, name, location, token, created_at, last_seen_at). Results tables already have `probe_id`; remote ingest sets it to the node’s `node_id`.

---

## Quick reference

- **Start testing session:** `sudo netperf-scheduler start`
- **Stop testing session:** `sudo netperf-scheduler stop`
- **Report speedtest for a day:** `sudo netperf-reporter -s /var/log/netperf/YYYYMMDD`

---

## Web interface

- **URL:** Use the **Site URL (HTTPS)** configured in Settings (e.g. `https://hyperionsolutionsgroup.com/netperf/`). No port in the URL; nginx serves over HTTPS on 443. After `install.sh`, run `sudo ./web/setup-https.sh` so the server uses the cert; then open that URL.
- **Auth:** Built-in users `bwadmin` (admin) and `user` (readonly) until **Setup → Users** is used to set a password; then config `auth_users` (hashed) is used. Landing page is read-only with scheduler toggle; **Login** gives admin menu.
- **Features:** **Dashboard** — date selector, separate graphs (download/upload/latency, iperf), trend over time, Run test now, CSV and summary export. **Remote nodes** — add nodes (name, location); each gets a unique token and a **downloadable bash script** to run on the remote machine; script runs speedtest (and optional iperf3), POSTs results to this server; each node has its own dashboard page (data filtered by probe_id). **Setup** — backend status, install deps, **Users** (configurable auth), **Recent SLA alerts**, timezone/NTP, purge old data. **Scheduler** — start/stop cron. **Settings** — site URL, SSL, speed limit, cron, Ookla/iperf, probe identity, SLA thresholds & webhook, retention, **Appearance** (light/dark/system) (writes `/etc/netperf/config.json`).
- **Service:** `systemctl start|stop|status netperf-web` (Uvicorn on 127.0.0.1:8080 or 8081; nginx proxies to it).

---

## Outgoing-only (client) behavior

- **netperf-tester** and the web "Run test now" only run **outbound** tests: Speedtest CLI talks to Ookla’s servers; iperf3 runs as **client** to the hosts in config. This host does not act as a speedtest or iperf3 server.
- If **iperf3 server** is running on this host (e.g. listening on port 5201 from another role or package), you can disable it so the host is client-only: stop/disable the iperf3 service (e.g. `systemctl stop iperf3` / `systemctl disable iperf3` if present, or stop the process using port 5201).

---

*This file is the single source of truth for what this project is and how the three scripts and web UI work.*
