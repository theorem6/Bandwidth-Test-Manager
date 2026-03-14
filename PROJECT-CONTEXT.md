# Bandwidth Test Manager – Project Context

## Overview

- **Linux-based speedtest utility** for automated and logged bandwidth testing.
- **Core tools:** Ookla Speedtest CLI (command line) and **iperf3**.
- Optional: **mtr**, **jq** (required for reporter).
- **Configurable sites:** Ookla servers and iperf3 servers/tests are defined in `/etc/netperf/config.json` and can be edited in the web UI.
- **Web interface:** Optional Flask app (port 8080) for viewing graphs, per-site and master chart with legend toggles, and editing config.

---

## Install

**On the server (as root):**

```bash
sudo ./install.sh
```

- Installs deps (Ookla repo, speedtest, iperf3, mtr, jq, trickle), copies scripts to `/bin`, creates `/etc/netperf/config.json` from `etc/netperf-config.json`, and installs the web UI under `/opt/netperf-web` with a systemd service.
- Use `sudo ./install.sh --no-web` to skip the web interface.
- Web port is configurable: set `PORT=8081` (or other) before running to use a different port (e.g. if 8080 is in use).

**Deploy to existing GCE instance (from local machine):**

```bash
./deploy-gce.sh INSTANCE_NAME [ZONE] [PROJECT]
```

- Copies project to the instance and runs `install.sh`. If port 8080 is in use on the server, the web UI is installed on 8081. Does not overwrite existing `/etc/netperf/config.json`.

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
- **speedtest_limit_mbps:** optional number (e.g. `100`) or `null`. When set, speedtest runs are throttled to this many Mbps using `trickle` (install script installs it). Omit or leave empty for no limit.
- **ookla_servers:** list of `{ "id": <number> or "auto", "label": "Label" }`. Use `"id": "auto"` for auto-selected server.
- **iperf_servers:** list of `{ "host": "hostname", "label": "label" }`.
- **iperf_tests:** list of `{ "name": "single", "args": "-P 1" }` (args are iperf3 client flags).
- Editable via **Settings** in the web UI.

---

## Scripts

| Script | Path | Purpose |
|--------|------|---------|
| **netperf-scheduler** | `/bin/netperf-scheduler` | Enable/disable automated speed test logging via cron |
| **netperf-tester** | `/bin/netperf-tester` | Run tests (Ookla + iperf3) using **config**; append to daily log dir |
| **netperf-reporter** | `/bin/netperf-reporter` | Parse and combine output (speedtest CSV; locations discovered from filenames) |

All three **must be run as root**. Tester reads `/etc/netperf/config.json` (or `NETPERF_CONFIG`).

---

## netperf-scheduler

- **Usage:** `netperf-scheduler [start | stop | h]`
- **start:** Creates `/var/log/netperf/YYYYMMDD`, adds cron job, restarts cron.
- **stop:** Removes netperf cron job, restarts cron.
- **Cron:** `5 * * * * /bin/netperf-tester /var/log/netperf/YYYYMMDD` (minute 5 of every hour).

---

## netperf-tester

- **Usage:** `netperf-tester STORAGE_LOCATION` (or `-h` for help).
- **Storage:** Single argument = directory for the day, e.g. `/var/log/netperf/20250313`.

**Tests run (in order, with ~10s sleep between):**

1. **Ookla Speedtest (JSON):**
   - Local (auto server) → `0_speedtest-local`
   - Server 10171 (FL) → `1_speedtest-fl`
   - Server 53398 (IL) → `2_speedtest-il`
   - Server 58326 (NC) → `3_speedtest-nc`
   - Server 8864 (WA) → `4_speedtest-wa`

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

## Quick reference

- **Start testing session:** `sudo netperf-scheduler start`
- **Stop testing session:** `sudo netperf-scheduler stop`
- **Report speedtest for a day:** `sudo netperf-reporter -s /var/log/netperf/YYYYMMDD`

---

## Web interface

- **URL:** `http://<host>:8080` (after `install.sh` and `systemctl start netperf-web`).
- **Features:** Date selector, metric (download/upload/latency), **master graph** (all sites; click legend to show/hide a site), **per-site graphs**, scheduler start/stop, **Settings** to edit Ookla and iperf servers/tests (writes `/etc/netperf/config.json`).
- **Service:** `systemctl start|stop|status netperf-web`.

---

*This file is the single source of truth for what this project is and how the three scripts and web UI work.*
