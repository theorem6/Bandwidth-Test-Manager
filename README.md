# Bandwidth Test Manager

Linux-based speedtest utility using **Ookla Speedtest CLI** and **iperf3**, with configurable sites, optional scheduling, CSV reporting, and a **web UI** with per-site and master graphs.

See **[PROJECT-CONTEXT.md](PROJECT-CONTEXT.md)** for full behavior, options, and usage.

## Quick start (Linux)

1. **One-shot install** (deps + scripts + config + web UI)
   ```bash
   sudo ./install.sh
   ```
   Use `sudo ./install.sh --no-web` to skip the web interface.

2. **Configure sites** (optional)  
   Edit `/etc/netperf/config.json` to choose which Ookla servers and iperf3 hosts/tests to run, or use **Settings** in the web UI.

3. **Start/stop scheduled testing**
   ```bash
   sudo netperf-scheduler start   # run tests at :05 every hour, log under /var/log/netperf/YYYYMMDD
   sudo netperf-scheduler stop    # remove schedule
   ```

4. **Web interface** (if installed)
   - Open `http://<host>:8080`
   - Pick a date and metric (download/upload/latency)
   - **Master graph:** all sites; click legend to toggle a site on/off
   - **Per-site graphs:** one chart per site
   - **Settings:** edit Ookla and iperf sites and save config

5. **Generate speedtest report** (CLI, after some runs)
   ```bash
   sudo netperf-reporter -s /var/log/netperf/YYYYMMDD
   ```

## Deploy to Google Compute Engine (GCE)

From your **local machine** (where `gcloud` is installed), deploy to an existing Linux (Debian/Ubuntu) GCE instance without overwriting existing config:

```bash
./deploy-gce.sh INSTANCE_NAME [ZONE] [PROJECT]
```

Example:
```bash
./deploy-gce.sh my-server us-central1-a my-project
```

- Copies the project to the instance and runs `install.sh` as root.
- **Conflict checks:** if port 8080 is already in use, the web UI is installed on port **8081** instead.
- Existing `/etc/netperf/config.json` on the server is kept; new installs get the default config.
- Requires: `gcloud` CLI, SSH access to the instance (e.g. `gcloud compute ssh`), and a Debian/Ubuntu instance. On Windows, run `deploy-gce.sh` from Git Bash or WSL.
