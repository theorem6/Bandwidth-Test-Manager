# Making Bandwidth Test Manager a Vital ISP Tool

This document summarizes what the project provides today and gives concrete advice to turn it into a tool ISPs rely on for monitoring, SLAs, and operations.

---

## What You Have Today (Strengths)

| Area | Current state |
|------|----------------|
| **Testing** | Ookla Speedtest CLI + iperf3; configurable servers and tests; single cron schedule; optional speed limit (trickle). |
| **Storage** | SQLite for results; file-based logs under `/var/log/netperf/YYYYMMDD`; import-on-read from files into DB. |
| **UI** | FastAPI + Svelte; dashboard with per-site and trend graphs (download/upload/latency, iperf throughput); date picker; CSV export; public landing + admin login. |
| **Operations** | Scheduler on/off from UI; timezone/NTP in Setup; dependency install from UI; clear data; deploy via bash or from server. |
| **Security** | HTTP Basic auth (bwadmin/user); read-only vs admin; public read for dashboard/scheduler. |

**Implemented for ISP use:** **Probe identity** (probe_id, location_name, region, tier in config and DB); **SLA thresholds + webhook** (min download/upload, max latency; POST to URL on violation with 15 min cooldown; run after "Run test now" or via POST /api/check-sla); **SLA status** (GET /api/sla-status). **Also implemented:** **Data retention** – config `retention_days` (Settings); purge (Setup) deletes log dirs and DB rows older than retention (default 30). **Summary report** – `GET /api/summary?from_date=&to_date=&probe_id=` (per-site min/max/avg); `GET /api/export/summary` (CSV); Dashboard **Download summary (30d)** button. **Alert history** – SLA violations that trigger the webhook are stored in SQLite `alert_history`; GET /api/alerts returns recent entries; Setup page shows "Recent SLA alerts". **Configurable auth** – config `auth_users` (list of username, password_hash, role); when set, replaces built-in users; GET /api/users (admin) and POST /api/users/set-password (admin) to list and add/update users; passwords stored hashed (sha256). **Remaining gaps:** scheduled email report, central multi-probe dashboard.

---

## High-Impact Additions for ISPs

### 1. **SLA thresholds and alerting**

- **Why:** ISPs need to know when a location or tier fails its committed rate (e.g. 100 Mbps down, 20 ms latency).
- **What to add:**
  - Configurable **thresholds** in Settings (or config): e.g. `min_download_mbps`, `max_latency_ms`, `min_upload_mbps` per “tier” or globally.
  - After each test run (or on a schedule), **evaluate** the latest result(s) against thresholds; if violated, emit an **event** (see below).
  - **Alerting:** At least one outbound action: **webhook** (POST JSON to a URL), and optionally **email** or **SMTP**. Store last-alert time to avoid flapping (e.g. re-alert only after 15–30 min or when back in compliance then out again).
- **UI:** “Alerts” or “SLA” page: recent violations, last fired time, link to dashboard for that date/site. Optional: simple on/off and threshold edit in Settings.

### 2. **Probe/site identity (multi-probe ready)**

- **Why:** One server can run multiple “logical” probes (e.g. different configs or VLANs), or you may later run one instance per POP; you need a stable **probe_id** / **location_id** so a central system can aggregate.
- **What to add:**
  - In config (and UI): **probe_id** (e.g. `pop-chicago-1`) and optional **location_name**, **region**, **tier** (e.g. “1G”, “100M”). Store these with every result (new columns or a small `probes` table keyed by `probe_id`).
  - **DB:** Add `probe_id` (and optionally `location_name`, `tier`) to `speedtest_results` and `iperf_results`; backfill existing rows with a default probe_id if needed.
  - **API:** Keep existing per-date/history APIs; add optional `?probe_id=` filter so a central dashboard or NOC can query by probe. This sets you up for multi-probe without changing the single-server design yet.

### 3. **Webhook and simple integrations**

- **Why:** NOC dashboards, ticketing (e.g. create ticket when SLA fails), and automation (e.g. “run test” from another system) require machine-to-machine integration.
- **What to add:**
  - **Outbound webhook:** On threshold violation (and optionally on “test completed”), POST a JSON payload to a configurable URL (with optional secret header). Payload: probe_id, timestamp, test type, metrics, threshold violated.
  - **Inbound API:** Optional **token-auth API** (e.g. `POST /api/run-now` with `Authorization: Bearer <token>` or `X-API-Key`) so NOC or scripts can trigger a test without browser login. Restrict to a single “runner” token and document it in Setup/README.
  - **Health/read-only API:** You already have public `/api/health`, `/api/dates`, `/api/data`, `/api/history`. Document them as a “read API” for Grafana, custom dashboards, or status pages.

### 4. **Scheduled reports and export**

- **Why:** Management and compliance often want a periodic summary (e.g. “last 24 h by site”, “weekly SLA summary”) without opening the UI.
- **What to add:**
  - **Scheduled report:** Cron (or a small scheduler in the app) that, once per day/week, computes: by probe/site, min/max/avg download and upload, % of tests above threshold, and optionally latency p95. Output: **JSON** and **CSV** (and optionally PDF via a simple template). Send via **email** (SMTP) or write to a path (e.g. `/var/reports/netperf/daily-YYYYMMDD.csv`).
  - Reuse the same “summary” logic for an **API endpoint** (e.g. `GET /api/summary?from=...&to=...&probe_id=...`) so external tools can pull the same numbers.

### 5. **Configurable auth and roles**

- **Why:** ISPs need to align with internal identity (LDAP/AD) or at least avoid hardcoded passwords.
- **What to add:**
  - **Configurable users:** Store users (and hashed passwords) in config or SQLite (e.g. `users` table: username, password_hash, role). On first run, create default admin if no users exist; allow adding/editing users from Setup (admin only). Optionally support **LDAP/AD** bind for “login only” and keep roles in local config.
  - **Roles:** You already have admin vs readonly; optional: “operator” (can run tests and see alerts, cannot edit config or users). Document who can do what in README/CONTRIBUTING.

### 6. **Data retention and purging**

- **Why:** ISPs may have to retain data for a fixed period (e.g. 90 days) and then purge for compliance or disk.
- **What to add:**
  - **Retention policy** in config: e.g. `retention_days: 90`. A cron job or scheduled task (e.g. daily): delete from SQLite and remove log dirs older than `retention_days`; optionally only delete files and keep aggregated summary rows if you add them later.
  - **UI:** In Setup, “Data retention” section: set retention days, “Purge now” (with confirmation) for testing. Document in PROJECT-CONTEXT.

---

## Architecture Evolution: Multi-Probe and Central View

Today: **one server = one probe**. To scale to many locations (towers, POPs, CPE):

- **Option A – Many independent instances:** Deploy one Bandwidth Test Manager per location; each has its own config, DB, and UI. Use a **central dashboard** (separate app or Grafana) that calls each instance’s read API (`/api/data`, `/api/history`) and aggregates by `probe_id` (once you add it). Alerts can be per-instance (webhook from each) or aggregated in the central system.
- **Option B – Lightweight agents + central collector:** Thin “probe” agents on each site only run tests and **push** results to a central API (e.g. `POST /api/ingest` with probe_id, timestamp, metrics). The central server runs the current web UI, DB, and alerting. This requires: (1) a small agent (script or container) that runs netperf-tester and POSTs JSON, and (2) central API + DB schema that accept multi-probe data and retain `probe_id`.

Recommendation: **Add probe_id and optional filters first** (section 2); then use **Option A** with a simple central dashboard (or Grafana) that polls each instance. Move to Option B only if you need to manage hundreds of probes or want a single DB for reporting.

---

## Operational and Security Hardening

- **HTTPS:** You already support nginx + certs; document that ISPs should never use the app over plain HTTP in production.
- **Secrets:** Move webhook URL and API token out of config into env vars or a secrets store (e.g. `WEBHOOK_URL`, `API_TOKEN`); document in README.
- **Audit:** Optional audit log (who changed config, who ran “clear data”, when scheduler was toggled) in a table or file; useful for compliance.
- **Backup:** Document backing up `/var/log/netperf/` and `netperf.db` (and config) for disaster recovery; optional script to dump DB and tar logs to object storage.

---

## Priority Order (Suggested)

1. **Probe/site identity** (probe_id + optional location/tier in DB and config) – unblocks multi-site and reporting.
2. **SLA thresholds + webhook** – immediate value for NOC and ticketing.
3. **Scheduled summary report** (CSV/JSON + email or path) – management and compliance.
4. **Configurable auth** (and optional LDAP) – security and ops.
5. **Retention policy + purge** – compliance and disk.
6. **Optional central dashboard** (Grafana or small aggregator) once you have multiple probes.

---

## Summary

You already have a solid single-probe monitoring app with a clear UI, SQLite storage, and flexible test configuration. To make it **vital for an ISP**, focus on: **probe identity**, **SLA thresholds and webhooks**, **scheduled reports**, **configurable auth**, and **retention**. That combination supports NOC workflows, management reports, and future multi-site aggregation without a full rewrite.
