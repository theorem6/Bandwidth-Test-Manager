#!/usr/bin/env python3
"""Bandwidth Test Manager - Web API and UI (FastAPI + Uvicorn)."""
import hashlib
import hmac
import json
import os
from collections import defaultdict
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

import db
import diagnostics
from voice_domain import get_domain_schema
from voice_provider_adapter import get_default_adapter

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from typing import Any, Optional


def _netperf_log_date_str() -> str:
    """Folder YYYYMMDD under storage; must match netperf-cron-run's date +%Y%m%d (local timezone)."""
    return datetime.now().strftime("%Y%m%d")


def _netperf_ookla_home() -> str:
    """Writable Ookla config dir ($HOME/.config/ookla). Empty NETPERF_OOKLA_HOME must not win over default."""
    raw = (os.environ.get("NETPERF_OOKLA_HOME") or "").strip()
    return raw if raw else "/var/lib/netperf-ookla"


# Built-in users (used when config auth_users is missing or empty). username -> (password, role)
AUTH_USERS_BUILTIN = {
    "bwadmin": ("unl0ck", "admin"),
    "user": ("user", "readonly"),
}
AUTH_SALT = "netperf-bwm-v1"
security_basic = HTTPBasic(auto_error=False)


def _hash_password(password: str) -> str:
    return "sha256:" + hashlib.sha256((AUTH_SALT + password).encode()).hexdigest()


def _verify_password(password: str, stored: str) -> bool:
    if not stored:
        return False
    if stored.startswith("sha256:"):
        return _hash_password(password) == stored
    if stored.startswith("plain:"):
        return password == stored[6:]
    return password == stored


def _get_auth_users() -> dict[str, tuple[str, str]]:
    """Return username -> (password_hash_or_plain, role). From config auth_users if set, else built-in."""
    cfg = get_config()
    raw = cfg.get("auth_users")
    if isinstance(raw, list) and len(raw) > 0:
        out = {}
        for u in raw:
            if not isinstance(u, dict):
                continue
            name = (u.get("username") or "").strip()
            if not name:
                continue
            stored = u.get("password_hash") or u.get("password") or ""
            role = (u.get("role") or "readonly").strip() or "readonly"
            if role not in ("admin", "readonly"):
                role = "readonly"
            out[name] = (stored, role)
        if out:
            return out
    return {k: ("plain:" + v[0], v[1]) for k, v in AUTH_USERS_BUILTIN.items()}


def get_current_user(credentials: Optional[HTTPBasicCredentials] = Depends(security_basic)) -> tuple[str, str]:
    """Validate Basic auth and return (username, role). No WWW-Authenticate so browser uses in-page login only."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Login required")
    username, password = credentials.username, credentials.password
    users = _get_auth_users()
    if username not in users:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    stored, role = users[username]
    if not _verify_password(password, stored):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return (username, role)


def require_admin(user: tuple[str, str] = Depends(get_current_user)) -> tuple[str, str]:
    """Require admin role. Raises 403 for readonly."""
    if user[1] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


APP_DIR = Path(__file__).resolve().parent
STORAGE = Path(os.environ.get("NETPERF_STORAGE", "/var/log/netperf"))
CONFIG_PATH = Path(os.environ.get("NETPERF_CONFIG", "/etc/netperf/config.json"))
# Package installs may put speedtest only under /usr/bin; install.sh symlinks /usr/local/bin/speedtest.
# Subprocesses and threads must see /usr/local/bin (systemd unit also sets PATH).
_p0 = os.environ.get("PATH", "")
if "/usr/local/bin" not in _p0.split(os.pathsep):
    os.environ["PATH"] = "/usr/local/bin" + os.pathsep + _p0

# UI allows only these (see web/frontend/src/lib/schedule.ts)
_ALLOWED_CRON_SCHEDULES = frozenset({"5 * * * *", "5 6 * * *", "5 */6 * * *"})


def _normalize_cron_schedule(v: str) -> str:
    """Map any legacy 5-field cron to one of the allowed presets."""
    s = re.sub(r"\s+", " ", (v or "").strip()) or "5 * * * *"
    if s in _ALLOWED_CRON_SCHEDULES:
        return s
    parts = s.split()
    if len(parts) >= 5:
        if parts[1] == "*/6":
            return "5 */6 * * *"
        if parts[1] == "*" and parts[2] == "*":
            return "5 * * * *"
    return "5 6 * * *"


@asynccontextmanager
async def _app_lifespan(_: FastAPI):
    diagnostics.init_diagnostics(STORAGE, CONFIG_PATH)
    diagnostics.bwm_log().info("Service started pid=%s euid=%s", os.getpid(), os.geteuid())
    try:
        diagnostics.run_health_checks(STORAGE, CONFIG_PATH)
    except Exception:
        diagnostics.bwm_log().exception("Initial health check failed")
    _shutdown_diag = diagnostics.start_background_health_monitor(STORAGE, CONFIG_PATH)
    yield
    _shutdown_diag()
    diagnostics.bwm_log().info("Service stopping")


app = FastAPI(title="Bandwidth Test Manager", docs_url=None, redoc_url=None, lifespan=_app_lifespan)


@app.middleware("http")
async def netperf_api_path_middleware(request: Request, call_next):
    """Rewrite /netperf/api/* → /api/* so routes match when the SPA is opened at /netperf/ on Uvicorn
    (e.g. http://host:8080/netperf/). Nginx configs that strip the /netperf/ prefix already send /api/*."""
    path = request.scope.get("path") or ""
    if path == "/netperf/api" or path.startswith("/netperf/api/"):
        request.scope["path"] = path[len("/netperf") :]
        request.scope["raw_path"] = request.scope["path"].encode("latin-1")
    return await call_next(request)


class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Any) -> Any:
        response = await super().get_response(path, scope)
        if hasattr(response, "headers"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response


static_dir = APP_DIR / "static"

if static_dir.exists():
    (static_dir / "uploads").mkdir(parents=True, exist_ok=True)
    app.mount("/static", NoCacheStaticFiles(directory=str(static_dir)), name="static")

_BRANDING_KEYS = (
    "app_title",
    "tagline",
    "logo_url",
    "logo_alt",
    "primary_color",
    "primary_hover_color",
    "navbar_gradient_start",
    "navbar_gradient_end",
    "navbar_bg_start",
    "navbar_bg_end",
    "custom_css",
)
_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{3,8}$")


def _sanitize_logo_url(u: str) -> str:
    u = (u or "").strip()[:2000]
    if not u:
        return ""
    if u.startswith(("https://", "http://", "/netperf/", "/static/")):
        return u
    if u.startswith("/") and not u.startswith("//"):
        return u
    return ""


def normalize_branding(raw: Any) -> dict[str, str]:
    """Return a full branding dict with safe string values (empty = use UI built-in defaults)."""
    out = {k: "" for k in _BRANDING_KEYS}
    if not isinstance(raw, dict):
        return out
    out["app_title"] = str(raw.get("app_title") or "").strip()[:200]
    out["tagline"] = str(raw.get("tagline") or "").strip()[:300]
    out["logo_url"] = _sanitize_logo_url(str(raw.get("logo_url") or ""))
    out["logo_alt"] = str(raw.get("logo_alt") or "").strip()[:200]
    for key in (
        "primary_color",
        "primary_hover_color",
        "navbar_gradient_start",
        "navbar_gradient_end",
        "navbar_bg_start",
        "navbar_bg_end",
    ):
        v = raw.get(key)
        s = str(v).strip() if v is not None else ""
        out[key] = s if _HEX_COLOR_RE.fullmatch(s) else ""
    css = str(raw.get("custom_css") or "")[:50000]
    if css:
        low = css.lower()
        if "<script" in low or "javascript:" in low:
            css = ""
    out["custom_css"] = css
    return out


def get_config() -> dict:
    defaults = {
        "site_url": "",
        "ssl_cert_path": "",
        "ssl_key_path": "",
        "speedtest_limit_mbps": None,
        "cron_schedule": "5 * * * *",
        "iperf_duration_seconds": 10,
        "ookla_servers": [],
        "ookla_local_patterns": [],
        "ookla_local_auto_isp": True,
        "iperf_servers": [],
        "iperf_tests": [],
        "probe_id": "",
        "location_name": "",
        "region": "",
        "tier": "",
        "sla_thresholds": {
            "min_download_mbps": None,
            "min_upload_mbps": None,
            "max_latency_ms": None,
        },
        "webhook_url": "",
        "webhook_secret": "",
        "last_sla_alert_at": None,
        "retention_days": None,
        "auth_users": [],
        "voice_webhook_secret": "",
    }
    if not CONFIG_PATH.exists():
        out = dict(defaults)
        out["branding"] = normalize_branding({})
        out["cron_schedule"] = _normalize_cron_schedule(str(out.get("cron_schedule", "5 * * * *")))
        return out
    with open(CONFIG_PATH, "r") as f:
        data = json.load(f)
    for k, v in defaults.items():
        if k not in data:
            data[k] = v
    if isinstance(data.get("sla_thresholds"), dict):
        for tk, tv in defaults["sla_thresholds"].items():
            if tk not in data["sla_thresholds"]:
                data["sla_thresholds"][tk] = tv
    data["branding"] = normalize_branding(data.get("branding"))
    data["cron_schedule"] = _normalize_cron_schedule(str(data.get("cron_schedule", "5 * * * *")))
    return data


def save_config(data: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)


def _ookla_timestamp_from_obj(obj: dict) -> str:
    """Best-effort ISO timestamp from Ookla result JSON (field names vary by CLI version)."""
    for key in ("timestamp", "date", "time"):
        v = obj.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    res = obj.get("result")
    if isinstance(res, dict):
        for key in ("timestamp", "date"):
            v = res.get(key)
            if v is not None and str(v).strip():
                return str(v).strip()
    return ""


def _ensure_unique_timestamps_in_points(points: list[dict], log_date: str, field: str = "timestamp") -> None:
    """Fill missing timestamps and break duplicates so INSERT OR IGNORE keeps every run (same site, same day)."""
    if not points or len(log_date) < 8:
        return
    try:
        y, mo, d = int(log_date[:4]), int(log_date[4:6]), int(log_date[6:8])
        base = datetime(y, mo, d, 12, 0, 0)
    except ValueError:
        return
    seen: set[str] = set()
    for i, pt in enumerate(points):
        raw = (pt.get(field) or "").strip() if isinstance(pt.get(field), str) else str(pt.get(field) or "").strip()
        if not raw or raw in seen:
            pt[field] = (base + timedelta(seconds=i)).strftime("%Y-%m-%dT%H:%M:%S") + ".000000Z"
        seen.add(pt[field])


def _speedtest_result_to_point(obj: dict, require_type: bool = True) -> dict | None:
    """Extract one result point from Ookla JSON. Bandwidth is bytes/sec; we convert to bps (*8).
    When require_type=False, accept any object with download/upload (e.g. partial or alternate CLI output)."""
    if require_type and obj.get("type") != "result":
        return None
    download = obj.get("download") or {}
    upload = obj.get("upload") or {}
    ping = obj.get("ping") or {}
    server = obj.get("server") or {}
    bandwidth_d = download.get("bandwidth")
    bandwidth_u = upload.get("bandwidth")
    download_bps = (int(bandwidth_d) * 8) if bandwidth_d is not None else 0
    upload_bps = (int(bandwidth_u) * 8) if bandwidth_u is not None else 0
    latency_ms = ping.get("latency")
    if latency_ms is not None:
        try:
            latency_ms = float(latency_ms)
        except (TypeError, ValueError):
            latency_ms = None
    return {
        "timestamp": _ookla_timestamp_from_obj(obj),
        "download_bps": download_bps,
        "upload_bps": upload_bps,
        "latency_ms": latency_ms,
        "server_id": server.get("id", "ND"),
        "server_name": server.get("name", "ND"),
        "server_location": server.get("location", "ND"),
    }


def _decode_json_stream(raw: str) -> list[dict]:
    """Decode one or more JSON values from one string (JSONL or concatenated objects)."""
    out: list[dict] = []
    if not raw:
        return out
    dec = json.JSONDecoder()
    n = len(raw)
    i = 0
    while i < n:
        while i < n and raw[i].isspace():
            i += 1
        if i >= n:
            break
        try:
            obj, end = dec.raw_decode(raw, i)
        except json.JSONDecodeError:
            i += 1
            continue
        i = end
        if isinstance(obj, dict):
            out.append(obj)
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, dict):
                    out.append(item)
    return out


def parse_speedtest_file(path: Path) -> list:
    """Parse Ookla speedtest -f json output and return parsed points.
    Supports JSONL, one large JSON value, and concatenated objects without separators."""
    results = []
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return results
    # 1) Line-by-line (common path when each run appends one JSON line)
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            pt = _speedtest_result_to_point(obj)
            if pt:
                results.append(pt)
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    # 2) Decode any JSON stream structure from the full file text.
    # This handles concatenated objects robustly (without regex splitting nested JSON).
    if not results and raw.strip():
        for obj in _decode_json_stream(raw):
            pt = _speedtest_result_to_point(obj)
            if not pt:
                pt = _speedtest_result_to_point(obj, require_type=False)
            if pt:
                results.append(pt)
    # 3) Lenient line-by-line fallback for malformed lines that still contain useful keys.
    if not results and raw.strip():
        for line in raw.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                pt = _speedtest_result_to_point(obj, require_type=False)
                if pt and (pt.get("download_bps") or pt.get("upload_bps")):
                    results.append(pt)
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
    return results


def site_label_from_speedtest_filename(name: str) -> str:
    m = re.match(r"^\d+_speedtest-(.+)$", name)
    if m:
        return m.group(1).replace("-", " ").title()
    return name


def _import_day_from_files(log_date: str) -> None:
    """Load that day's result files from STORAGE into the SQLite DB (idempotent). Uses probe_id from config."""
    day_dir = STORAGE / log_date
    if not day_dir.exists() or not day_dir.is_dir():
        return
    db.init_db(STORAGE)
    cfg = get_config()
    probe_id = (cfg.get("probe_id") or "").strip() or None
    for f in sorted(day_dir.glob("*_speedtest-*")):
        label = site_label_from_speedtest_filename(f.name)
        points = parse_speedtest_file(f)
        if points:
            _ensure_unique_timestamps_in_points(points, log_date)
            db.import_speedtest_file_into_db(STORAGE, log_date, label, points, probe_id=probe_id)
    for f in sorted(day_dir.glob("iperf-*.txt")):
        label = site_label_from_iperf_filename(f.name)
        points = parse_iperf_file(f, log_date=log_date, summary_only=True)
        if points:
            _ensure_unique_timestamps_in_points(points, log_date)
            db.import_iperf_file_into_db(STORAGE, log_date, label, points, probe_id=probe_id)


SLA_ALERT_COOLDOWN_SECONDS = 900  # 15 min

def _evaluate_sla_and_webhook() -> None:
    """Evaluate latest speedtest results against SLA thresholds; if violated, POST to webhook (with cooldown)."""
    cfg = get_config()
    webhook_url = (cfg.get("webhook_url") or "").strip() or os.environ.get("WEBHOOK_URL", "").strip()
    if not webhook_url:
        return
    thresholds = cfg.get("sla_thresholds") or {}
    min_download_mbps = thresholds.get("min_download_mbps")
    min_upload_mbps = thresholds.get("min_upload_mbps")
    max_latency_ms = thresholds.get("max_latency_ms")
    if min_download_mbps is None and min_upload_mbps is None and max_latency_ms is None:
        return
    today = _netperf_log_date_str()
    db.init_db(STORAGE)
    probe_id = (cfg.get("probe_id") or "").strip() or None
    results = db.get_latest_speedtest_results(STORAGE, today, probe_id=probe_id)
    if not results:
        return
    violations: list[dict] = []
    for r in results:
        site = r.get("site", "")
        down_bps = r.get("download_bps")
        up_bps = r.get("upload_bps")
        lat = r.get("latency_ms")
        down_mbps = (down_bps / 1e6) if down_bps is not None else None
        up_mbps = (up_bps / 1e6) if up_bps is not None else None
        v: list[str] = []
        if min_download_mbps is not None and down_mbps is not None and down_mbps < min_download_mbps:
            v.append("download %.2f Mbps < %s Mbps" % (down_mbps, min_download_mbps))
        if min_upload_mbps is not None and up_mbps is not None and up_mbps < min_upload_mbps:
            v.append("upload %.2f Mbps < %s Mbps" % (up_mbps, min_upload_mbps))
        if max_latency_ms is not None and lat is not None and lat > max_latency_ms:
            v.append("latency %.1f ms > %s ms" % (lat, max_latency_ms))
        if v:
            violations.append({"site": site, "violations": v, "download_mbps": down_mbps, "upload_mbps": up_mbps, "latency_ms": lat})
    if not violations:
        return
    last_at = cfg.get("last_sla_alert_at")
    if last_at:
        try:
            s = last_at.replace("Z", "").replace("+00:00", "").strip()
            dt = datetime.fromisoformat(s)
            if (datetime.utcnow() - dt).total_seconds() < SLA_ALERT_COOLDOWN_SECONDS:
                return
        except Exception:
            pass
    payload = {
        "event": "sla_violation",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "probe_id": cfg.get("probe_id") or "",
        "location_name": cfg.get("location_name") or "",
        "region": cfg.get("region") or "",
        "tier": cfg.get("tier") or "",
        "results": results,
        "violations": violations,
    }
    secret = (cfg.get("webhook_secret") or "").strip() or os.environ.get("WEBHOOK_SECRET", "").strip()
    try:
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "Bandwidth-Test-Manager/1.0"},
            method="POST",
        )
        if secret:
            req.add_header("X-Webhook-Secret", secret)
        with urllib.request.urlopen(req, timeout=15) as _:
            pass
        cfg["last_sla_alert_at"] = datetime.utcnow().isoformat() + "Z"
        save_config(cfg)
        db.init_db(STORAGE)
        db.insert_alert(
            STORAGE,
            probe_id=cfg.get("probe_id") or "",
            location_name=cfg.get("location_name") or "",
            violations=violations,
            webhook_fired=True,
        )
    except Exception:
        pass


def _local_timestamp_from_file(path: Path) -> Optional[str]:
    """Get an ISO timestamp from the file's modification time in UTC, with 'Z' suffix so the frontend
    parses it as UTC and displays in the user's local time (e.g. 19:46 UTC shows as 1:46 PM Central)."""
    try:
        mtime = path.stat().st_mtime
        utc_dt = datetime.utcfromtimestamp(mtime)
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%06d" % (utc_dt.microsecond,) + "Z"
    except Exception:
        return None


def parse_iperf_file(path: Path, log_date: Optional[str] = None, summary_only: bool = False) -> list:
    """Parse iperf3 output (with optional --timestamp). Returns list of { bits_per_sec, timestamp }.
    Timestamp is taken from the local clock: the file's modification time (when the test wrote the file).
    log_date is YYYYMMDD from the parent dir for fallback only.
    When summary_only=True, prefer the combined end-of-test line (interval 0.0-X sec); if none found, use last point.
    All points from the same test get the same timestamp (local file mtime)."""
    results = []
    all_points: list[dict] = []  # when summary_only, collect all then filter or take last
    time_prefix_re = re.compile(
        r"^(?:(?:\w{3}\s+\d{1,2}|\d{8})\s+)?(\d{1,2}:\d{2}:\d{2}(?:\.\d+)?)\s*(.*)$", re.MULTILINE
    )
    bitrate_re = re.compile(
        r"\[\s*\d+\]\s+([\d.]+-[\d.]+)\s+sec\s+[\d.]+\s+\w+\s+([\d.]+)\s+(G|M|K)?bits/sec"
    )
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return results
    # Use local clock: file mtime (when the test wrote the file on this machine)
    test_start_timestamp = _local_timestamp_from_file(path)
    for line in raw.splitlines():
        stripped = line.strip()
        rest = stripped
        m = time_prefix_re.match(stripped)
        if m:
            rest = (m.group(2) or "").strip()
        bit_m = bitrate_re.search(rest)
        if bit_m:
            interval_part = bit_m.group(1)  # e.g. "0.00-10.00" or "1.00-2.00" or "0.0-10.0"
            val = float(bit_m.group(2))
            unit = (bit_m.group(3) or "M").upper()
            bps = val * 1e9 if unit == "G" else (val * 1e6 if unit == "M" else val * 1e3)
            point = {"bits_per_sec": bps, "timestamp": test_start_timestamp}
            if summary_only:
                if interval_part.startswith("0.0") and "-" in interval_part:
                    results.append(point)
                all_points.append(point)
            else:
                results.append(point)
    if summary_only and not results and all_points:
        results = [all_points[-1]]
    # If any point still has no timestamp (e.g. stat failed), use log_date midnight UTC as last resort
    if any(r.get("timestamp") is None for r in results) and log_date and len(log_date) >= 8:
        y, mo, d = log_date[:4], log_date[4:6], log_date[6:8]
        fallback_ts = test_start_timestamp or f"{y}-{mo}-{d}T00:00:00.000000Z"
        for r in results:
            if r.get("timestamp") is None:
                r["timestamp"] = fallback_ts
    return results


def site_label_from_iperf_filename(name: str) -> str:
    base = name.replace(".txt", "").replace("iperf-", "")
    return base.replace("-", " ").title()


@app.get("/")
@app.get("/netperf")
@app.get("/netperf/")
def index():
    """Serve the single-page UI. No-cache so browser always gets latest."""
    index_path = static_dir / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=500, detail="index.html not found")
    return FileResponse(
        index_path,
        media_type="text/html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
    )


def _parse_speedtest_servers_json(out: str) -> list[dict]:
    """Parse JSON or JSONL output from speedtest -L -f json. Returns list of {id, name, location}."""
    servers = []
    try:
        single = json.loads(out)
        if isinstance(single, dict) and "servers" in single:
            for s in single.get("servers", []):
                sid = s.get("id")
                if sid is not None:
                    name = s.get("name") or s.get("host")
                    name = str(name) if name is not None else str(sid)
                    loc = s.get("location") or s.get("country") or ""
                    servers.append({"id": sid, "name": str(name), "location": str(loc) if loc else ""})
        elif isinstance(single, list):
            for s in single:
                if isinstance(s, dict) and s.get("id") is not None:
                    name = s.get("name") or s.get("host") or str(s["id"])
                    loc = s.get("location") or s.get("country") or ""
                    servers.append({"id": s["id"], "name": str(name), "location": str(loc) if loc else ""})
    except (json.JSONDecodeError, TypeError):
        pass
    if not servers:
        for line in out.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict) and "id" in obj:
                    name = obj.get("name") or obj.get("host") or str(obj["id"])
                    loc = obj.get("location") or obj.get("country") or ""
                    servers.append({"id": obj["id"], "name": str(name), "location": str(loc) if loc else ""})
                elif isinstance(obj, dict) and "servers" in obj:
                    for s in obj.get("servers", []):
                        if isinstance(s, dict) and s.get("id") is not None:
                            name = s.get("name") or s.get("host") or str(s["id"])
                            loc = s.get("location") or s.get("country") or ""
                            servers.append({"id": s["id"], "name": str(name), "location": str(loc) if loc else ""})
            except (json.JSONDecodeError, TypeError):
                continue
    return servers


def _parse_speedtest_servers_text(out: str) -> list[dict]:
    """Parse plain text from speedtest -L (no json). Lines like '  12345) Server Name (City, Country)'."""
    servers = []
    # Match "  12345) Server Name (City, Country)" or "  Server Name (id: 12345)"
    for line in out.split("\n"):
        line = line.strip()
        # Format: number) description
        m = re.match(r"^\s*(\d+)\)\s*(.+)$", line)
        if m:
            sid = int(m.group(1))
            desc = (m.group(2) or "").strip()
            servers.append({"id": sid, "name": desc, "location": ""})
            continue
        # Format: ... (id: 12345)
        m = re.search(r"\(id:\s*(\d+)\)\s*$", line)
        if m:
            sid = int(m.group(1))
            name = line[: m.start()].strip() or str(sid)
            servers.append({"id": sid, "name": name, "location": ""})
    return servers


def _speedtest_net_entry_to_dict(s: dict) -> Optional[dict]:
    """Map one Speedtest.net API server object to our catalog row."""
    try:
        sid = int(str(s.get("id", "")).strip())
    except (TypeError, ValueError):
        return None
    if sid <= 0:
        return None
    sponsor = str(s.get("sponsor") or "").strip()
    city = str(s.get("name") or "").strip()
    country = str(s.get("country") or "").strip()
    cc = str(s.get("cc") or "").strip()
    host = str(s.get("host") or "").strip()
    loc_parts = [x for x in (city, country) if x]
    loc = ", ".join(loc_parts)
    name = sponsor or city or str(sid)
    return {"id": sid, "name": name, "location": loc, "country": country, "host": host, "cc": cc}


def _ssl_context_for_https() -> ssl.SSLContext:
    """Prefer certifi’s CA bundle — Python may otherwise fail TLS on hosts with incomplete system CAs."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


_OOKLA_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# systemd services often have a minimal PATH — curl is not always found via which()
def _curl_executable() -> Optional[str]:
    w = shutil.which("curl")
    if w and Path(w).is_file():
        return w
    for candidate in ("/usr/bin/curl", "/bin/curl", "/usr/local/bin/curl"):
        if Path(candidate).is_file():
            return candidate
    return None


def _parse_speedtest_net_servers_payload(data: Any) -> list[dict]:
    """Normalize JSON from Speedtest.net (array or {servers: [...]})."""
    if isinstance(data, dict) and isinstance(data.get("servers"), list):
        data = data["servers"]
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for s in data:
        if not isinstance(s, dict):
            continue
        row = _speedtest_net_entry_to_dict(s)
        if row:
            out.append(row)
    return out


def _fetch_speedtest_net_json_urllib(url: str) -> Any:
    """GET JSON with browser-like headers and SSL context (some hosts block generic agents)."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _OOKLA_UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.speedtest.net/",
            "Origin": "https://www.speedtest.net",
        },
    )
    ctx = _ssl_context_for_https()
    try:
        with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        raw = raw.strip()
        if raw.startswith("<"):
            return None
        return json.loads(raw)
    except Exception:
        return None


def _curl_ookla_get(url: str, *, accept: str, ipv4: bool = False, max_time_sec: int = 120) -> Optional[str]:
    """GET body via curl (different TLS/IPv6 behavior than Python on some servers)."""
    curl_bin = _curl_executable()
    if not curl_bin:
        return None
    args = [
        curl_bin,
        "-fsSL",
        "--max-time",
        str(max_time_sec),
        "--retry",
        "2",
        "--retry-delay",
        "1",
    ]
    if ipv4:
        args.append("-4")
    args += [
        "-A",
        _OOKLA_UA,
        "-H",
        f"Accept: {accept}",
        "-H",
        "Referer: https://www.speedtest.net/",
        "-H",
        "Origin: https://www.speedtest.net",
        url,
    ]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=max_time_sec + 15)
        if r.returncode != 0 or not (r.stdout or "").strip():
            return None
        return r.stdout
    except Exception:
        return None


def _fetch_speedtest_net_json_curl(url: str) -> Any:
    """Try curl with default routing, then IPv4-only (broken IPv6 is common on servers)."""
    for ipv4 in (False, True):
        raw = _curl_ookla_get(url, accept="application/json, */*", ipv4=ipv4)
        if not raw:
            continue
        t = raw.strip()
        if t.startswith("<"):
            continue
        try:
            return json.loads(t)
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def _fetch_speedtest_net_text_urllib(url: str) -> Optional[str]:
    """GET raw body (XML). Used for speedtest-servers.php legacy list."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _OOKLA_UA,
            "Accept": "application/xml, text/xml, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.speedtest.net/",
            "Origin": "https://www.speedtest.net",
        },
    )
    ctx = _ssl_context_for_https()
    try:
        with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def _fetch_speedtest_net_text_curl(url: str) -> Optional[str]:
    for ipv4 in (False, True):
        raw = _curl_ookla_get(url, accept="application/xml, text/xml, */*", ipv4=ipv4)
        if raw and "<server" in raw:
            return raw
    return None


def _parse_speedtest_servers_xml(text: str) -> list[dict]:
    """Parse legacy Speedtest.net XML (settings/servers/server[@id]). Same geo list browsers get from .php."""
    if not text or "<server" not in text:
        return []
    try:
        root = ET.fromstring(text.strip())
    except ET.ParseError:
        return []
    out: list[dict] = []
    for el in root.iter("server"):
        a = el.attrib
        row = _speedtest_net_entry_to_dict(
            {
                "id": a.get("id", ""),
                "sponsor": a.get("sponsor", ""),
                "name": a.get("name", ""),
                "country": a.get("country", ""),
                "cc": a.get("cc", ""),
                "host": a.get("host", ""),
            }
        )
        if row:
            out.append(row)
    return out


def _fetch_speedtest_servers_by_search(query: str, limit: int) -> list[dict]:
    """Live search against Speedtest.net (same API as the website). Max 100 results per request."""
    qenc = urllib.parse.quote(query.strip(), safe="")
    lim = max(1, min(limit, 100))
    urls = [
        f"https://www.speedtest.net/api/js/servers?engine=js&https_functional=true&limit={lim}&search={qenc}",
        f"https://www.speedtest.net/api/js/servers?limit={lim}&search={qenc}",
    ]
    best: list[dict] = []
    for url in urls:
        data = _fetch_speedtest_net_json_urllib(url)
        if data is None:
            data = _fetch_speedtest_net_json_curl(url)
        if data is None:
            continue
        rows = _parse_speedtest_net_servers_payload(data)
        if len(rows) > len(best):
            best = rows
    return sorted(
        best,
        key=lambda x: (str(x.get("country") or "ZZZ"), str(x.get("name") or ""), int(x["id"])),
    )


def _fetch_speedtest_servers_public_api() -> list[dict]:
    """Large server list from Speedtest.net (geo-based). Supplements Ookla CLI -L (~10–20 nearest).

    Merges every successful JSON/XML response (union by server id) so a partial failure still leaves
    thousands of rows when any path works. Uses certifi for TLS, Referer headers, and curl -4 fallback.
    """
    merged: dict[int, dict] = {}
    urls = [
        "https://www.speedtest.net/api/js/servers?limit=10000",
        "https://www.speedtest.net/api/js/servers?engine=js&https_functional=true&limit=10000",
    ]
    for url in urls:
        # Prefer curl first: same behavior as a manual shell test (works when Python TLS/PATH is broken).
        for getter in (_fetch_speedtest_net_json_curl, _fetch_speedtest_net_json_urllib):
            data = getter(url)
            if data is None:
                continue
            for row in _parse_speedtest_net_servers_payload(data):
                merged.setdefault(int(row["id"]), row)
    xml_url = "https://www.speedtest.net/speedtest-servers.php"
    for getter in (_fetch_speedtest_net_text_curl, _fetch_speedtest_net_text_urllib):
        txt = getter(xml_url)
        if not txt:
            continue
        for row in _parse_speedtest_servers_xml(txt):
            merged.setdefault(int(row["id"]), row)
    return sorted(
        merged.values(),
        key=lambda x: (str(x.get("country") or "ZZZ"), str(x.get("name") or ""), int(x["id"])),
    )


@app.get("/api/me")
def api_me(user: tuple[str, str] = Depends(get_current_user)):
    """Return current user and role (for login flow and UI)."""
    return JSONResponse({"username": user[0], "role": user[1]})


@app.get("/api/users")
def api_users_list(_user: tuple[str, str] = Depends(require_admin)):
    """List usernames and roles (no passwords). For configurable auth."""
    users = _get_auth_users()
    return JSONResponse({
        "users": [{"username": u, "role": r} for u, (_, r) in users.items()],
    })


@app.post("/api/users/set-password")
async def api_users_set_password(request: Request, _user: tuple[str, str] = Depends(require_admin)):
    """Set or update a user (username, password, role). Stores hashed password in config auth_users."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    username = (body.get("username") or "").strip()
    password = body.get("password")
    role = (body.get("role") or "readonly").strip() or "readonly"
    if role not in ("admin", "readonly"):
        role = "readonly"
    if not username or not isinstance(password, str) or len(password) < 1:
        return JSONResponse({"ok": False, "error": "username and password required."}, status_code=400)
    if len(username) > 128:
        return JSONResponse({"ok": False, "error": "username too long."}, status_code=400)
    cfg = get_config()
    auth_users = list(cfg.get("auth_users") or [])
    if not isinstance(auth_users, list):
        auth_users = []
    existing = next((i for i, u in enumerate(auth_users) if isinstance(u, dict) and (u.get("username") or "").strip() == username), None)
    entry = {"username": username, "password_hash": _hash_password(password), "role": role}
    if existing is not None:
        auth_users[existing] = entry
    else:
        auth_users.append(entry)
    cfg["auth_users"] = auth_users
    try:
        save_config(cfg)
        return JSONResponse({"ok": True, "message": f"User {username} updated."})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


def _ookla_license_json_path(home: str) -> Path:
    return Path(home) / ".config" / "ookla" / "speedtest-cli.json"


def _ookla_cli_cmd(bin_exe: str, *args: str) -> list[str]:
    """Build speedtest argv; omit --accept-license once speedtest-cli.json exists (less EULA on stderr)."""
    home = _netperf_ookla_home()
    cmd: list[str] = [bin_exe]
    if os.environ.get("NETPERF_OOKLA_ALWAYS_LICENSE") == "1" or not _ookla_license_json_path(home).is_file():
        cmd.extend(["--accept-license", "--accept-gdpr"])
    cmd.extend(args)
    return cmd


def _ookla_speedtest_env() -> dict[str, str]:
    """Ookla writes under $HOME/.config/ookla; use a writable service path (not necessarily /root)."""
    home = _netperf_ookla_home()
    try:
        (Path(home) / ".config" / "ookla").mkdir(parents=True, mode=0o755, exist_ok=True)
    except OSError:
        pass
    e: dict[str, str] = {**os.environ, "HOME": home, "NETPERF_OOKLA_HOME": home, "DEBIAN_FRONTEND": "noninteractive"}
    if not (e.get("TERM") or "").strip():
        e["TERM"] = "xterm-256color"
    if not (e.get("TMPDIR") or "").strip():
        e["TMPDIR"] = "/tmp"
    return e


def _run_speedtest_list(cmd: list[str], env: dict) -> tuple[str, str, int]:
    """Run speedtest -L (with optional -f json). Returns (stdout, stderr, returncode)."""
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        return ((r.stdout or "").strip(), (r.stderr or "").strip(), r.returncode)
    except subprocess.TimeoutExpired:
        return ("", "Timeout", -1)
    except FileNotFoundError:
        raise


@app.get("/api/speedtest-servers")
def api_speedtest_servers(
    search: Optional[str] = None,
    limit: int = 100,
    _user: tuple[str, str] = Depends(get_current_user),
):
    """Return list of Ookla Speedtest servers.

    Without **search**: merges Speedtest.net geo catalog + CLI `speedtest -L` (nearest servers).

    With **search**: queries Speedtest.net live (`/api/js/servers?search=…`, up to 100 rows) — not a local filter.
    """
    q = (search or "").strip()
    if q:
        lim = max(1, min(limit, 100))
        rows = _fetch_speedtest_servers_by_search(q, lim)
        if not rows:
            return JSONResponse(
                {
                    "servers": [],
                    "error": f'No servers matched "{q}" on Speedtest.net. Try another word or a numeric server ID.',
                }
            )
        return JSONResponse({"servers": rows})

    env = _ookla_speedtest_env()
    error_note: Optional[str] = None
    servers: list[dict] = []

    # Prefer official binary if present (install-deps installs it when package version crashes)
    speedtest_bin = "/usr/local/bin/speedtest" if Path("/usr/local/bin/speedtest").exists() else "speedtest"

    try:
        # JSON list; --accept-license/--accept-gdpr required for non-TTY (cron/service).
        out, err, code = _run_speedtest_list(_ookla_cli_cmd(speedtest_bin, "-L", "-f", "json"), env)
        if out:
            servers = _parse_speedtest_servers_json(out)
        if not out or (code != 0 and not servers):
            error_note = err or "JSON list failed or empty"
    except FileNotFoundError:
        error_note = "speedtest CLI not installed — using Speedtest.net catalog only."

    # Fallback 1: plain text with same binary (no -f json)
    if not servers:
        try:
            out, err, _ = _run_speedtest_list(_ookla_cli_cmd(speedtest_bin, "-L"), env)
            if out:
                servers = _parse_speedtest_servers_text(out)
                if servers and error_note:
                    error_note = "Server list from text (JSON list failed on this Speedtest build)."
                elif not error_note:
                    error_note = "Server list from text (JSON unavailable)."
            elif not error_note:
                error_note = err or "No output from speedtest -L"
        except Exception as e:
            if not error_note:
                error_note = str(e)

    # Fallback 2: if we still have no servers and default was "speedtest", try official binary
    if not servers and speedtest_bin == "speedtest" and Path("/usr/local/bin/speedtest").exists():
        try:
            out, err, _ = _run_speedtest_list(_ookla_cli_cmd("/usr/local/bin/speedtest", "-L"), env)
            if out:
                servers = _parse_speedtest_servers_text(out)
                error_note = "Server list from text (JSON list failed on this Speedtest build)." if error_note else None
        except Exception:
            pass

    # Dedupe CLI list by id
    seen = set()
    unique: list[dict] = []
    for s in servers:
        sid = s["id"]
        if sid not in seen:
            seen.add(sid)
            unique.append(s)

    # Merge with Speedtest.net API (thousands near client geo); CLI alone is ~10 nearest
    http_servers = _fetch_speedtest_servers_public_api()
    merged: dict[int, dict] = {}
    for s in http_servers:
        merged[int(s["id"])] = dict(s)
    for s in unique:
        sid = int(s["id"])
        if sid not in merged:
            merged[sid] = dict(s)
        else:
            o = merged[sid]
            if not (o.get("name") or "").strip() and s.get("name"):
                o["name"] = s["name"]
            if not (o.get("location") or "").strip() and s.get("location"):
                o["location"] = s["location"]
    final_list = sorted(
        merged.values(),
        key=lambda x: (str(x.get("country") or "ZZZ"), str(x.get("name") or ""), int(x["id"])),
    )
    if not http_servers and unique and not error_note:
        error_note = (
            "Full server catalog unavailable (HTTPS to speedtest.net failed). "
            "Showing nearest servers from the Speedtest CLI only."
        )

    # Don't show raw C++ crash to user (e.g. "terminate called... basic_string::_M_construct null not valid")
    if error_note and (
        "terminate called" in error_note
        or "logic_error" in error_note
        or "basic_string" in error_note
    ):
        error_note = "Speedtest CLI list failed on this build (you can still enter a server ID below)."

    return JSONResponse({"servers": final_list, "error": error_note} if error_note else {"servers": final_list})


@app.get("/api/health")
def api_health():
    """Confirm API is up and report data status."""
    try:
        dates = []
        if STORAGE.exists():
            dates = sorted(
                [d.name for d in STORAGE.iterdir() if d.is_dir() and d.name.isdigit()],
                reverse=True,
            )
        return JSONResponse({
            "ok": True,
            "storage": str(STORAGE),
            "dates_count": len(dates),
            "latest_date": dates[0] if dates else None,
        })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


RUN_NOW_SENTINEL = STORAGE / ".run-now"
RUN_NOW_MAX_AGE_SEC = 20 * 60  # consider stale after 20 min


@app.get("/api/run-status")
def api_run_status():
    """Return whether a run-now test is currently in progress (script still running)."""
    try:
        if not RUN_NOW_SENTINEL.exists():
            return JSONResponse({"running": False})
        mtime = RUN_NOW_SENTINEL.stat().st_mtime
        import time
        if time.time() - mtime > RUN_NOW_MAX_AGE_SEC:
            RUN_NOW_SENTINEL.unlink(missing_ok=True)
            return JSONResponse({"running": False})
        return JSONResponse({"running": True, "started_at": mtime})
    except Exception:
        return JSONResponse({"running": False})


def _run_now_cmd() -> list:
    """Build command for run-now; use sudo if we're not root so netperf-tester/cron-run can run."""
    run_args = None
    if Path("/bin/netperf-cron-run").exists():
        run_args = ["/bin/netperf-cron-run"]
    else:
        today = _netperf_log_date_str()
        storage_today = STORAGE / today
        storage_today.mkdir(parents=True, exist_ok=True)
        if Path("/bin/netperf-tester").exists():
            run_args = ["/bin/netperf-tester", str(storage_today)]
    if not run_args:
        return []
    if os.geteuid() != 0:
        return ["sudo", "-n"] + run_args
    return run_args


def _sudo_noninteractive_works() -> bool:
    """True if sudo -n can run commands (required for Run test now when uvicorn is not root)."""
    if os.geteuid() == 0:
        return True
    try:
        r = subprocess.run(
            ["sudo", "-n", "true"],
            capture_output=True,
            timeout=10,
            env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


@app.post("/api/run-now")
def api_run_now(_user: tuple[str, str] = Depends(require_admin)):
    """Start speedtest + iperf in background. Returns immediately; client should poll GET /api/run-status. Uses sudo when app is not root so tests actually run."""
    cmd = _run_now_cmd()
    if not cmd:
        return JSONResponse({"ok": False, "error": "netperf scripts not found. Use Setup to install dependencies."})
    if os.geteuid() != 0 and cmd[0] == "sudo" and not _sudo_noninteractive_works():
        return JSONResponse(
            {
                "ok": False,
                "error": (
                    "Run test now needs passwordless sudo for the service user. "
                    "Add to /etc/sudoers.d/ (use visudo): "
                    "'<web_user> ALL=(root) NOPASSWD: /bin/netperf-cron-run, /bin/netperf-tester' "
                    "or run the web service as root. See /var/log/netperf/run-now-last.log after a failed attempt."
                ),
            },
            status_code=503,
        )
    STORAGE.mkdir(parents=True, exist_ok=True)
    run_now_log = STORAGE / "run-now-last.log"
    RUN_NOW_SENTINEL.touch()
    import threading
    def run():
        try:
            ookla_h = _netperf_ookla_home()
            r = subprocess.run(
                cmd,
                capture_output=True,
                timeout=600,
                cwd="/",
                env={
                    **os.environ,
                    "DEBIAN_FRONTEND": "noninteractive",
                    "HOME": ookla_h,
                    "NETPERF_OOKLA_HOME": ookla_h,
                },
            )
            try:
                run_now_log.write_text(
                    f"cmd={cmd!r}\nreturncode={r.returncode}\nstdout={r.stdout or ''}\nstderr={r.stderr or ''}\n",
                    encoding="utf-8",
                )
            except OSError:
                pass
            if r.returncode != 0:
                diagnostics.bwm_log().warning(
                    "run-now exit code=%s cmd=%s stderr_tail=%s",
                    r.returncode,
                    cmd,
                    (r.stderr or "")[-2000:],
                )
            else:
                diagnostics.bwm_log().info("run-now completed successfully")
            today = _netperf_log_date_str()
            _import_day_from_files(today)
            _evaluate_sla_and_webhook()
        except Exception as ex:
            diagnostics.bwm_log().exception("run-now failed: %s", ex)
            try:
                run_now_log.write_text(f"cmd={cmd!r}\nexception={ex!r}\n", encoding="utf-8")
            except OSError:
                pass
        finally:
            RUN_NOW_SENTINEL.unlink(missing_ok=True)
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return JSONResponse({"ok": True, "message": "Test started. Poll run-status for completion."})


@app.get("/api/config")
def api_config_get(_user: tuple[str, str] = Depends(get_current_user)):
    return JSONResponse(get_config())


@app.get("/api/branding")
def api_branding_public():
    """Public branding fields for navbar, colors, and custom CSS (no auth; safe subset)."""
    cfg = get_config()
    b = cfg.get("branding") or {}
    if not isinstance(b, dict):
        b = {}
    b = normalize_branding(b)
    return JSONResponse(b)


@app.post("/api/branding/logo")
async def api_branding_logo_upload(
    file: UploadFile = File(...),
    _user: tuple[str, str] = Depends(require_admin),
):
    """Upload a logo image into static/uploads and set branding.logo_url in config."""
    if not static_dir.exists():
        return JSONResponse({"ok": False, "error": "Static directory not available."}, status_code=500)
    raw_name = (file.filename or "").strip()
    ext = Path(raw_name).suffix.lower()
    allowed = {".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif", ".ico"}
    if ext not in allowed:
        return JSONResponse(
            {"ok": False, "error": f"Allowed types: {', '.join(sorted(allowed))}"},
            status_code=400,
        )
    try:
        body = await file.read()
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    if len(body) > 2_000_000:
        return JSONResponse({"ok": False, "error": "File too large (max 2 MB)."}, status_code=400)
    upload_dir = static_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    fname = f"brand-logo{ext}"
    dest = upload_dir / fname
    try:
        dest.write_bytes(body)
    except OSError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    logo_url = f"/static/uploads/{fname}"
    cur = get_config()
    cur.setdefault("branding", normalize_branding({}))
    cur["branding"] = normalize_branding({**cur["branding"], "logo_url": logo_url})
    try:
        save_config(cur)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    return JSONResponse({"ok": True, "logo_url": logo_url})


@app.put("/api/config")
@app.post("/api/config")
async def api_config_set(request: Request, _user: tuple[str, str] = Depends(require_admin)):
    try:
        data = await request.json()
    except Exception:
        data = {}
    cur = get_config()
    if "speedtest_limit_mbps" in data:
        v = data["speedtest_limit_mbps"]
        cur["speedtest_limit_mbps"] = int(v) if v is not None and str(v).strip() != "" else None
    for key in ("site_url", "ssl_cert_path", "ssl_key_path"):
        if key in data:
            cur[key] = (data.get(key) or "").strip()
    if "cron_schedule" in data:
        cur["cron_schedule"] = _normalize_cron_schedule(str(data.get("cron_schedule") or ""))
    if "iperf_duration_seconds" in data:
        v = data.get("iperf_duration_seconds")
        try:
            n = int(v) if v is not None and str(v).strip() != "" else 10
            cur["iperf_duration_seconds"] = max(1, min(300, n))  # clamp 1–300 seconds
        except (TypeError, ValueError):
            cur["iperf_duration_seconds"] = 10
    if "ookla_local_patterns" in data:
        raw_pats = data.get("ookla_local_patterns")
        if isinstance(raw_pats, list):
            cur["ookla_local_patterns"] = [str(x).strip() for x in raw_pats if str(x).strip()]
        elif isinstance(raw_pats, str):
            cur["ookla_local_patterns"] = [p.strip() for p in re.split(r"[\n,]+", raw_pats) if p.strip()]
        else:
            cur["ookla_local_patterns"] = []
    if "ookla_local_auto_isp" in data:
        cur["ookla_local_auto_isp"] = bool(data.get("ookla_local_auto_isp"))
    if "ookla_servers" in data:
        raw_ookla = data.get("ookla_servers")
        if isinstance(raw_ookla, list):
            cur["ookla_servers"] = []
            for s in raw_ookla:
                if not isinstance(s, dict):
                    continue
                sid = s.get("id")
                label = str(s.get("label") or "").strip() or "Server"
                sid_lower = (sid.strip().lower() if isinstance(sid, str) else None)
                if sid == "local" or sid_lower == "local":
                    cur["ookla_servers"].append({"id": "local", "label": label or "Local ISP"})
                elif sid == "auto" or sid is None or sid_lower in ("", "auto"):
                    cur["ookla_servers"].append({"id": "auto", "label": label or "Auto"})
                else:
                    try:
                        cur["ookla_servers"].append({"id": int(sid) if isinstance(sid, (int, float)) else int(sid), "label": label})
                    except (TypeError, ValueError):
                        cur["ookla_servers"].append({"id": "auto", "label": label})
    if "iperf_servers" in data:
        cur["iperf_servers"] = data.get("iperf_servers") if isinstance(data.get("iperf_servers"), list) else cur.get("iperf_servers", [])
    if "iperf_tests" in data:
        raw_tests = data.get("iperf_tests")
        if isinstance(raw_tests, list):
            cur["iperf_tests"] = [{"name": str(t.get("name", "test")).strip() or "test", "args": str(t.get("args", "")).strip()} for t in raw_tests if isinstance(t, dict)]
    for key in ("probe_id", "location_name", "region", "tier"):
        if key in data:
            cur[key] = (data.get(key) or "").strip()
    if "sla_thresholds" in data and isinstance(data["sla_thresholds"], dict):
        cur.setdefault("sla_thresholds", {})
        for k in ("min_download_mbps", "min_upload_mbps", "max_latency_ms"):
            if k in data["sla_thresholds"]:
                v = data["sla_thresholds"][k]
                cur["sla_thresholds"][k] = int(v) if v is not None and str(v).strip() != "" else None
    if "webhook_url" in data:
        cur["webhook_url"] = (data.get("webhook_url") or "").strip()
    if "webhook_secret" in data:
        cur["webhook_secret"] = (data.get("webhook_secret") or "").strip()
    if "retention_days" in data:
        v = data.get("retention_days")
        cur["retention_days"] = int(v) if v is not None and str(v).strip() != "" else None
    if "branding" in data and isinstance(data["branding"], dict):
        prev = cur.get("branding") if isinstance(cur.get("branding"), dict) else {}
        merged = {**prev, **data["branding"]}
        cur["branding"] = normalize_branding(merged)
    try:
        save_config(cur)
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# --- Remote nodes (probes that report back to this server) ---

def _slug(s: str) -> str:
    """Make a safe node_id from name."""
    s = re.sub(r"[^a-zA-Z0-9_-]", "-", (s or "").strip())
    return s.strip("-").lower() or "node"


def _verify_address(address: str) -> tuple[bool, str]:
    """Verify that the given IP or hostname is reachable (TCP connect to port 22 or 80). Returns (ok, error_message)."""
    host = (address or "").strip()
    if not host:
        return True, ""
    # Allow host:port; for verification we only need the host part (avoid splitting IPv6)
    if re.match(r"^[^\[\]]+:\d+$", host):
        host = host.rsplit(":", 1)[0].strip()
    if not host:
        return True, ""
    for port in (22, 80, 443):
        try:
            sock = socket.create_connection((host, port), timeout=3)
            sock.close()
            return True, ""
        except (socket.gaierror, socket.timeout, OSError):
            continue
    return False, f"Cannot reach {address} (tried TCP ports 22, 80, 443). Check IP/hostname and that the host is up and reachable from this server."


@app.get("/api/remote/nodes")
def api_remote_list(_user: tuple[str, str] = Depends(require_admin)):
    """List all remote nodes (no tokens)."""
    try:
        nodes = db.list_remote_nodes(STORAGE)
        return JSONResponse({"nodes": nodes})
    except Exception:
        return JSONResponse({"nodes": []})


@app.post("/api/remote/nodes")
async def api_remote_create(request: Request, _user: tuple[str, str] = Depends(require_admin)):
    """Create a remote node. Body: { name, location?, address? }. If address (IP/hostname) is provided, verifies reachability. Returns node_id and token (show once)."""
    try:
        data = await request.json()
    except Exception:
        data = {}
    name = (data.get("name") or "").strip()
    if not name:
        return JSONResponse({"ok": False, "error": "name required"}, status_code=400)
    location = (data.get("location") or "").strip()
    address = (data.get("address") or "").strip()
    if address:
        ok, err = _verify_address(address)
        if not ok:
            return JSONResponse({"ok": False, "error": err}, status_code=400)
    node_id = _slug(name)
    # Ensure unique node_id
    existing = db.get_remote_node(STORAGE, node_id)
    if existing:
        for i in range(1, 1000):
            candidate = f"{node_id}-{i}"
            if not db.get_remote_node(STORAGE, candidate):
                node_id = candidate
                break
    token = secrets.token_hex(24)
    db.create_remote_node(STORAGE, node_id, name, location, token, address=address)
    node = db.get_remote_node(STORAGE, node_id)
    return JSONResponse({
        "ok": True,
        "node": {**node, "token": token},
        "message": "Node created. Download the script and run it on the remote machine. Save the token; it is shown only once.",
    })


@app.get("/api/remote/nodes/{node_id}")
def api_remote_get(node_id: str, _user: tuple[str, str] = Depends(require_admin)):
    """Get one remote node (no token)."""
    node = db.get_remote_node(STORAGE, node_id)
    if not node:
        return JSONResponse({"error": "Node not found"}, status_code=404)
    return JSONResponse(node)


@app.put("/api/remote/nodes/{node_id}")
async def api_remote_update(node_id: str, request: Request, _user: tuple[str, str] = Depends(require_admin)):
    """Update a remote node. Body: { name?, location?, address? }. Only provided fields are updated. If address (non-empty) provided, verifies reachability."""
    node = db.get_remote_node(STORAGE, node_id)
    if not node:
        return JSONResponse({"error": "Node not found"}, status_code=404)
    try:
        data = await request.json()
    except Exception:
        data = {}
    name = data.get("name")
    name = (name.strip() if isinstance(name, str) else None) if name is not None else None
    location = data.get("location")
    location = (location.strip() if isinstance(location, str) else "") if location is not None else None
    address = data.get("address")
    address = (address.strip() if isinstance(address, str) else "") if address is not None else None
    if address is not None and address:
        ok, err = _verify_address(address)
        if not ok:
            return JSONResponse({"ok": False, "error": err}, status_code=400)
    if name is not None:
        db.update_remote_node(STORAGE, node_id, name=name)
    if location is not None:
        db.update_remote_node(STORAGE, node_id, location=location)
    if address is not None:
        db.update_remote_node(STORAGE, node_id, address=address)
    updated = db.get_remote_node(STORAGE, node_id)
    return JSONResponse({"ok": True, "node": updated})


@app.delete("/api/remote/nodes/{node_id}")
def api_remote_delete(node_id: str, _user: tuple[str, str] = Depends(require_admin)):
    """Delete a remote node. Result data for this probe_id is kept."""
    node = db.get_remote_node(STORAGE, node_id)
    if not node:
        return JSONResponse({"error": "Node not found"}, status_code=404)
    db.delete_remote_node(STORAGE, node_id)
    return JSONResponse({"ok": True})


REMOTE_AGENT_SCRIPT = r'''#!/bin/bash
# Bandwidth Test Manager - Remote node agent
# Run this script on a remote machine (e.g. via cron) to report speedtest/iperf results to the main node.
# Requires: curl, speedtest (Ookla CLI), optional iperf3. Install: apt install curl; see https://www.speedtest.net/apps/cli for Ookla.
#
# Run every hour (e.g. at :05): add to crontab -e:
#   5 * * * * /path/to/bwm-remote-agent-NODEID.sh
#
# Or with env in crontab: 5 * * * * BWM_MAIN_URL="..." BWM_NODE_TOKEN="..." /path/to/bwm-remote-agent-standalone.sh

set -e
MAIN_URL="{{MAIN_URL}}"
NODE_TOKEN="{{NODE_TOKEN}}"
LOG_DATE=$(date -u +%Y%m%d)

# Optional: one iperf3 server to test (hostname or IP). Leave empty to skip iperf.
IPERF_HOST="${IPERF_HOST:-}"

payload_speedtest() {
  local out
  out=$(speedtest -f json 2>/dev/null) || return 0
  local down_b=$(echo "$out" | grep -o '"download":{[^}]*"bandwidth":[0-9]*' | grep -o '[0-9]*$' | head -1)
  local up_b=$(echo "$out" | grep -o '"upload":{[^}]*"bandwidth":[0-9]*' | grep -o '[0-9]*$' | head -1)
  local lat=$(echo "$out" | grep -o '"latency":[0-9.]*' | head -1 | grep -o '[0-9.]*$')
  local ts=$(echo "$out" | grep -o '"timestamp":"[^"]*"' | head -1 | sed 's/"timestamp":"//;s/"$//')
  [ -z "$down_b" ] && down_b=0
  [ -z "$up_b" ] && up_b=0
  local down=$((down_b * 8))
  local up=$((up_b * 8))
  [ -z "$lat" ] && lat=0
  [ -z "$ts" ] && ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  echo "{\"site\":\"Remote\",\"timestamp\":\"$ts\",\"download_bps\":$down,\"upload_bps\":$up,\"latency_ms\":$lat}"
}

payload_iperf() {
  local host="$1"
  [ -z "$host" ] && return 0
  local out
  out=$(iperf3 -c "$host" -t 10 -f m -J 2>/dev/null) || return 0
  local bps=$(echo "$out" | grep -o '"bits_per_second":[0-9.]*' | head -1 | grep -o '[0-9.]*$')
  [ -z "$bps" ] && return 0
  local ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  echo "{\"site\":\"$host\",\"timestamp\":\"$ts\",\"bits_per_sec\":$bps}"
}

# Build JSON payload
SPEEDTEST_JSON=$(payload_speedtest)
IPERF_JSON=""
[ -n "$IPERF_HOST" ] && IPERF_JSON=$(payload_iperf "$IPERF_HOST") || true

# Build body: log_date, speedtest array, iperf array
if [ -n "$IPERF_JSON" ]; then
  BODY=$(printf '{"log_date":"%s","speedtest":[%s],"iperf":[%s]}' "$LOG_DATE" "$SPEEDTEST_JSON" "$IPERF_JSON")
else
  BODY=$(printf '{"log_date":"%s","speedtest":[%s],"iperf":[]}' "$LOG_DATE" "$SPEEDTEST_JSON")
fi

curl -s -X POST "${MAIN_URL}/api/remote/ingest" \
  -H "Content-Type: application/json" \
  -H "X-Node-Token: $NODE_TOKEN" \
  -d "$BODY" \
  --max-time 60
echo ""
'''


@app.get("/api/remote/script/{node_id}")
def api_remote_script(node_id: str, request: Request, _user: tuple[str, str] = Depends(require_admin)):
    """Download a bash script for the remote node. Injects MAIN_URL and token."""
    node = db.get_remote_node(STORAGE, node_id)
    if not node:
        return JSONResponse({"error": "Node not found"}, status_code=404)
    token = db.get_remote_node_token(STORAGE, node_id)
    if not token:
        return JSONResponse({"error": "Node not found"}, status_code=404)
    cfg = get_config()
    main_url = (cfg.get("site_url") or "").strip().rstrip("/")
    if not main_url and hasattr(request, "base_url"):
        main_url = str(request.base_url).rstrip("/")
    if not main_url:
        main_url = "https://your-main-node.example.com"
    script = REMOTE_AGENT_SCRIPT.replace("{{MAIN_URL}}", main_url).replace("{{NODE_TOKEN}}", token)
    return Response(
        content=script,
        media_type="application/x-sh",
        headers={"Content-Disposition": f'attachment; filename="bwm-remote-agent-{node_id}.sh"'},
    )


@app.post("/api/remote/ingest")
async def api_remote_ingest(request: Request):
    """Accept speedtest/iperf results from a remote agent. Auth: X-Node-Token header. No user auth."""
    token = request.headers.get("X-Node-Token") or ""
    node = db.get_remote_node_by_token(STORAGE, token) if token else None
    if not node:
        return JSONResponse({"ok": False, "error": "Invalid or missing X-Node-Token"}, status_code=401)
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)
    log_date = (data.get("log_date") or "").strip()
    if not log_date or not re.match(r"^\d{8}$", log_date):
        return JSONResponse({"ok": False, "error": "log_date required (YYYYMMDD)"}, status_code=400)
    probe_id = node["node_id"]
    st_rows = [x for x in (data.get("speedtest") or []) if isinstance(x, dict)]
    by_site: dict[str, list[dict]] = defaultdict(list)
    for st in st_rows:
        site = str(st.get("site") or "Remote").strip() or "Remote"
        by_site[site].append(st)
    for site, arr in by_site.items():
        _ensure_unique_timestamps_in_points(arr, log_date)
        for st in arr:
            try:
                db.insert_speedtest(
                    STORAGE,
                    log_date=log_date,
                    site=site,
                    timestamp=str(st.get("timestamp") or ""),
                    download_bps=int(st["download_bps"]) if st.get("download_bps") is not None else None,
                    upload_bps=int(st["upload_bps"]) if st.get("upload_bps") is not None else None,
                    latency_ms=float(st["latency_ms"]) if st.get("latency_ms") is not None else None,
                    probe_id=probe_id,
                )
            except (TypeError, ValueError, KeyError):
                pass
    ip_rows = [x for x in (data.get("iperf") or []) if isinstance(x, dict) and x.get("bits_per_sec") is not None]
    by_isite: dict[str, list[dict]] = defaultdict(list)
    for ip in ip_rows:
        site = str(ip.get("site") or "iperf").strip() or "iperf"
        by_isite[site].append(ip)
    for site, arr in by_isite.items():
        _ensure_unique_timestamps_in_points(arr, log_date)
        for ip in arr:
            try:
                db.insert_iperf(
                    STORAGE,
                    log_date=log_date,
                    site=site,
                    timestamp=str(ip.get("timestamp") or ""),
                    bits_per_sec=float(ip["bits_per_sec"]),
                    probe_id=probe_id,
                )
            except (TypeError, ValueError, KeyError):
                pass
    db.update_remote_node_last_seen(STORAGE, probe_id)
    return JSONResponse({"ok": True, "message": "Ingested"})


@app.get("/api/dates")
def api_dates():
    """Return list of dates that have data (DB + filesystem). Imports file data into DB for each date dir."""
    try:
        db.init_db(STORAGE)
        date_set: set[str] = set(db.get_dates(STORAGE))
        if STORAGE.exists():
            for d in STORAGE.iterdir():
                if d.is_dir() and d.name.isdigit():
                    date_set.add(d.name)
                    _import_day_from_files(d.name)
        dates = sorted(date_set, reverse=True)
        return JSONResponse({"dates": dates})
    except Exception:
        return JSONResponse({"dates": []})


@app.get("/api/data")
def api_data(date: Optional[str] = None, probe_id: Optional[str] = None):
    """Return speedtest and iperf data for a date. Optional probe_id filter. Imports from files first if needed."""
    try:
        if not date or not date.isdigit():
            return JSONResponse({"error": "missing or invalid date"}, status_code=400)
        _import_day_from_files(date)
        pid = (probe_id or "").strip() or None
        speedtest = db.get_speedtest_for_date(STORAGE, date, probe_id=pid)
        iperf = db.get_iperf_for_date(STORAGE, date, probe_id=pid)
        return JSONResponse({"speedtest": speedtest, "iperf": iperf})
    except Exception:
        return JSONResponse({"speedtest": {}, "iperf": {}})


def _range_from_end_ymd(end_ymd: str, span: str) -> tuple[str, str]:
    """Inclusive [from, to] YYYYMMDD for chart window ending at end_ymd."""
    end = datetime.strptime(end_ymd, "%Y%m%d").date()
    if span == "week":
        start = end - timedelta(days=6)
    elif span == "month":
        start = end - timedelta(days=29)
    elif span == "year":
        start = end - timedelta(days=364)
    else:
        start = end
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


@app.get("/api/data-range")
def api_data_range(end: Optional[str] = None, span: str = "day", probe_id: Optional[str] = None):
    """Speedtest + iperf for a window ending at **end** (YYYYMMDD): day=1, week=7, month=30, year=365 calendar days."""
    try:
        if not end or len(end) != 8 or not end.isdigit():
            return JSONResponse({"error": "missing or invalid end (YYYYMMDD)"}, status_code=400)
        sp = (span or "day").lower()
        if sp not in ("day", "week", "month", "year"):
            sp = "day"
        from_ymd, to_ymd = _range_from_end_ymd(end, sp)
        db.init_db(STORAGE)
        for ymd in _iter_ymd_range(from_ymd, to_ymd):
            day_dir = STORAGE / ymd
            if day_dir.is_dir():
                _import_day_from_files(ymd)
        pid = (probe_id or "").strip() or None
        speedtest = db.get_speedtest_for_range(STORAGE, from_ymd, to_ymd, probe_id=pid)
        iperf = db.get_iperf_for_range(STORAGE, from_ymd, to_ymd, probe_id=pid)
        return JSONResponse(
            {
                "speedtest": speedtest,
                "iperf": iperf,
                "range": {"from": from_ymd, "to": to_ymd, "span": sp, "end": end},
            }
        )
    except Exception:
        return JSONResponse({"speedtest": {}, "iperf": {}, "range": None})


def _iter_ymd_range(from_ymd: str, to_ymd: str):
    a = datetime.strptime(from_ymd, "%Y%m%d").date()
    b = datetime.strptime(to_ymd, "%Y%m%d").date()
    d = a
    while d <= b:
        yield d.strftime("%Y%m%d")
        d += timedelta(days=1)


def _escape_csv(val: Any) -> str:
    if val is None:
        return ""
    s = str(val)
    if "," in s or '"' in s or "\n" in s:
        return '"' + s.replace('"', '""') + '"'
    return s


@app.get("/api/export/csv")
def api_export_csv(date: Optional[str] = None, _user: tuple[str, str] = Depends(get_current_user)):
    """Export full speedtest and iperf data for a date as CSV.

    Source of truth is SQLite after syncing log files into the DB. Log files under STORAGE/YYYYMMDD/
    are imported first (same as dashboard); rows that exist only in the DB (e.g. remote node ingest)
    are included. Extra column probe_id identifies the source node when set.
    """
    if not date or not date.isdigit():
        return Response(status_code=400)
    db.init_db(STORAGE)
    day_dir = STORAGE / date
    if day_dir.exists() and day_dir.is_dir():
        _import_day_from_files(date)

    st = db.get_speedtest_export_rows(STORAGE, date)
    ip = db.get_iperf_export_rows(STORAGE, date)
    if not st and not ip:
        return Response(status_code=404)

    rows: list[list[str]] = []
    rows.append(
        [
            "type",
            "date",
            "site",
            "timestamp",
            "download_mbps",
            "upload_mbps",
            "latency_ms",
            "throughput_mbps",
            "probe_id",
        ]
    )
    for site, ts, d, u, lat, probe in st:
        rows.append(
            [
                "speedtest",
                date,
                site or "",
                ts or "",
                str(round((d or 0) / 1e6, 2)) if d is not None else "",
                str(round((u or 0) / 1e6, 2)) if u is not None else "",
                str(lat) if lat is not None else "",
                "",
                probe or "",
            ]
        )
    for site, ts, bps, probe in ip:
        rows.append(
            [
                "iperf",
                date,
                site or "",
                ts or "",
                "",
                "",
                "",
                str(round((bps or 0) / 1e6, 2)) if bps is not None else "",
                probe or "",
            ]
        )
    body = "\n".join(",".join(_escape_csv(str(c)) for c in row) for row in rows)
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="netperf-{date}.csv"'},
    )


@app.get("/api/history")
def api_history(days: int = 90, probe_id: Optional[str] = None):
    """Return time-series data for trend graphs. Optional probe_id filter for remote node view."""
    try:
        db.init_db(STORAGE)
        nd = max(1, min(int(days), 366))
        cutoff = (datetime.now() - timedelta(days=nd)).strftime("%Y%m%d")
        if STORAGE.exists():
            for d in STORAGE.iterdir():
                if d.is_dir() and d.name.isdigit() and d.name >= cutoff:
                    _import_day_from_files(d.name)
        pid = (probe_id or "").strip() or None
        speedtest_points = db.get_history_speedtest(STORAGE, cutoff, probe_id=pid)
        iperf_points = db.get_history_iperf(STORAGE, cutoff, probe_id=pid)
        return JSONResponse({"speedtest": speedtest_points, "iperf": iperf_points})
    except Exception:
        return JSONResponse({"speedtest": [], "iperf": []})


def _crontab_l() -> str:
    """Return root's crontab (where netperf-scheduler writes). Use sudo when app is not root."""
    cmd = ["crontab", "-l"]
    if os.geteuid() != 0:
        cmd = ["sudo", "-n", "crontab", "-l"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return (r.stdout or "") if r.returncode == 0 else ""
    except Exception:
        return ""


@app.get("/api/status")
def api_status():
    try:
        out = _crontab_l()
        scheduled = "netperf" in out
    except Exception:
        scheduled = False
    return JSONResponse({"scheduled": scheduled})


def _scheduler_cmd(*args: str) -> list[str]:
    """Run netperf-scheduler; use sudo if we're not root so crontab can be modified."""
    base = ["/bin/netperf-scheduler"]
    if os.geteuid() != 0:
        return ["sudo", "-n"] + base + list(args)
    return base + list(args)


def _root_cmd(cmd: list[str]) -> list[str]:
    """Run a command as root; prepend sudo -n if process is not root."""
    if os.geteuid() != 0:
        return ["sudo", "-n"] + cmd
    return cmd


@app.post("/api/scheduler/start")
def api_scheduler_start():
    """Start cron schedule. Returns 200 with ok/error so frontend can show message."""
    cmd = _scheduler_cmd("start")
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0:
            return JSONResponse({"ok": True})
        err = (r.stderr or r.stdout or "").strip()
        if "already scheduled" in err.lower():
            return JSONResponse({"ok": True, "message": "Schedule was already active."})
        return JSONResponse({"ok": False, "error": err or f"Exit code {r.returncode}"})
    except FileNotFoundError:
        return JSONResponse({"ok": False, "error": "netperf-scheduler not found. Run Setup → Install / fix dependencies."})
    except subprocess.TimeoutExpired:
        return JSONResponse({"ok": False, "error": "Start timed out."})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@app.post("/api/scheduler/stop")
def api_scheduler_stop():
    """Stop cron schedule. Returns 200 with ok/error so frontend can show message."""
    try:
        r = subprocess.run(
            _scheduler_cmd("stop"),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0:
            return JSONResponse({"ok": True})
        return JSONResponse({"ok": False, "error": (r.stderr or r.stdout or "").strip() or f"Exit code {r.returncode}"})
    except FileNotFoundError:
        return JSONResponse({"ok": False, "error": "netperf-scheduler not found. Run Setup → Install / fix dependencies."})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@app.get("/api/backend-status")
def api_backend_status(_user: tuple[str, str] = Depends(get_current_user)):
    """Report whether Ookla speedtest, iperf3, jq are installed and config/cron state."""
    def have(cmd: str) -> bool:
        try:
            r = subprocess.run(
                ["which", cmd],
                capture_output=True,
                text=True,
                timeout=2,
            )
            return r.returncode == 0 and bool(r.stdout and r.stdout.strip())
        except Exception:
            return False

    scheduled = False
    cron_line = ""
    try:
        out = _crontab_l()
        scheduled = "netperf" in out
        if scheduled:
            for line in out.splitlines():
                if "netperf" in line:
                    cron_line = line.strip()
                    break
    except Exception:
        pass

    cfg = get_config()
    ookla_list = cfg.get("ookla_servers") or []
    iperf_servers_list = cfg.get("iperf_servers") or []
    return JSONResponse({
        "speedtest_installed": have("speedtest"),
        "iperf3_installed": have("iperf3"),
        "jq_installed": have("jq"),
        "config_path": str(CONFIG_PATH),
        "config_exists": CONFIG_PATH.exists(),
        "scheduled": scheduled,
        "cron_schedule": cfg.get("cron_schedule", "5 * * * *"),
        "cron_line": cron_line,
        "ookla_servers_count": len(ookla_list),
        "iperf_servers_count": len(iperf_servers_list),
        "storage_path": str(STORAGE),
        "storage_exists": STORAGE.exists(),
    })


@app.get("/api/timezone")
def api_timezone_get(_user: tuple[str, str] = Depends(get_current_user)):
    """Return current timezone, local time, and NTP sync status."""
    out: dict = {"timezone": "", "local_time_iso": "", "ntp_active": False}
    try:
        r = subprocess.run(
            _root_cmd(["timedatectl", "show"]),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0:
            for line in (r.stdout or "").splitlines():
                if line.startswith("Timezone="):
                    out["timezone"] = line.split("=", 1)[1].strip()
                elif line.startswith("NTPSynchronized="):
                    out["ntp_active"] = line.split("=", 1)[1].strip().lower() == "yes"
        if not out["timezone"] and Path("/etc/timezone").exists():
            out["timezone"] = Path("/etc/timezone").read_text().strip()
        r2 = subprocess.run(
            ["date", "-Iseconds"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if r2.returncode == 0 and r2.stdout:
            out["local_time_iso"] = r2.stdout.strip()
    except Exception:
        pass
    return JSONResponse(out)


@app.get("/api/timezones")
def api_timezones_list(_user: tuple[str, str] = Depends(get_current_user)):
    """Return list of valid timezone identifiers (e.g. America/Chicago)."""
    try:
        r = subprocess.run(
            _root_cmd(["timedatectl", "list-timezones"]),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0 and r.stdout:
            zones = [z.strip() for z in r.stdout.splitlines() if z.strip()]
            return JSONResponse({"timezones": zones})
    except Exception:
        pass
    # Fallback: common zones
    fallback = [
        "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
        "America/Phoenix", "UTC", "Europe/London", "Europe/Paris", "Asia/Tokyo", "Australia/Sydney",
    ]
    return JSONResponse({"timezones": fallback})


@app.post("/api/timezone")
async def api_timezone_set(request: Request, _user: tuple[str, str] = Depends(require_admin)):
    """Set system timezone (e.g. America/Chicago). Requires root."""
    try:
        try:
            body = await request.json()
        except Exception:
            body = {}
        if isinstance(body, dict):
            tz = (body.get("timezone") or "").strip()
        else:
            tz = ""
        if not tz or "/" not in tz or ".." in tz:
            return JSONResponse({"ok": False, "error": "Invalid timezone."}, status_code=400)
        r = subprocess.run(
            _root_cmd(["timedatectl", "set-timezone", tz]),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0:
            return JSONResponse({"ok": True, "message": f"Timezone set to {tz}."})
        return JSONResponse(
            {"ok": False, "error": (r.stderr or r.stdout or "Failed").strip()},
            status_code=400,
        )
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/ntp-install")
def api_ntp_install(_user: tuple[str, str] = Depends(require_admin)):
    """Install NTP and enable time sync. Requires root. Uses apt install ntp or chrony."""
    try:
        # Enable systemd-timesyncd NTP client first (often already active)
        subprocess.run(
            _root_cmd(["timedatectl", "set-ntp", "true"]),
            capture_output=True,
            text=True,
            timeout=5,
        )
        # Install full NTP daemon for better sync (ntp or chrony)
        for pkg, svc in [("ntp", "ntp"), ("chrony", "chrony")]:
            r = subprocess.run(
                _root_cmd(["apt-get", "update"]),
                capture_output=True,
                text=True,
                timeout=60,
                env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
            )
            if r.returncode != 0:
                continue
            r = subprocess.run(
                _root_cmd(["apt-get", "install", "-y", pkg]),
                capture_output=True,
                text=True,
                timeout=120,
                env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
            )
            if r.returncode == 0:
                subprocess.run(
                    _root_cmd(["systemctl", "enable", svc]),
                    capture_output=True,
                    timeout=5,
                )
                subprocess.run(
                    _root_cmd(["systemctl", "start", svc]),
                    capture_output=True,
                    timeout=5,
                )
                return JSONResponse({
                    "ok": True,
                    "message": f"NTP installed ({pkg}). Time sync enabled. Wait a minute for sync.",
                })
        return JSONResponse({
            "ok": True,
            "message": "NTP client enabled (timedatectl set-ntp). Install ntp or chrony package manually if needed.",
        })
    except subprocess.TimeoutExpired:
        return JSONResponse({"ok": False, "error": "Install timed out."}, status_code=500)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/clear-iperf-data")
def api_clear_iperf_data(_user: tuple[str, str] = Depends(require_admin)):
    """Delete all iperf3 log files so the next cron run or Run test now produces fresh iperf data."""
    try:
        if not STORAGE.exists():
            return JSONResponse({"ok": True, "deleted": 0, "message": "No storage dir."})
        deleted = 0
        for day_dir in STORAGE.iterdir():
            if day_dir.is_dir() and day_dir.name.isdigit():
                for f in day_dir.glob("iperf-*.txt"):
                    try:
                        f.unlink()
                        deleted += 1
                    except OSError:
                        pass
        return JSONResponse({
            "ok": True,
            "deleted": deleted,
            "message": f"Removed {deleted} iperf log file(s). Next cron run or Run test now will create fresh iperf data.",
        })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/check-sla")
def api_check_sla(_user: tuple[str, str] = Depends(require_admin)):
    """Run SLA evaluation now (compare latest results to thresholds, fire webhook if violated). Called automatically after Run test now; use this for cron or manual trigger."""
    try:
        _evaluate_sla_and_webhook()
        return JSONResponse({"ok": True, "message": "SLA check completed."})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/api/summary")
def api_summary(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    probe_id: Optional[str] = None,
    _user: tuple[str, str] = Depends(get_current_user),
):
    """Summary report: per-site min/max/avg download, upload, latency for date range. from_date/to_date = YYYYMMDD; default last 30 days."""
    try:
        db.init_db(STORAGE)
        now = datetime.utcnow()
        if not from_date or not from_date.isdigit():
            from_date = (now - timedelta(days=30)).strftime("%Y%m%d")
        if not to_date or not to_date.isdigit():
            to_date = now.strftime("%Y%m%d")
        if from_date > to_date:
            from_date, to_date = to_date, from_date
        pid = (probe_id or "").strip() or None
        rows = db.get_summary(STORAGE, from_date, to_date, probe_id=pid)
        return JSONResponse({"from": from_date, "to": to_date, "probe_id": pid or "", "summary": rows})
    except Exception as e:
        return JSONResponse({"error": str(e), "summary": []}, status_code=500)


@app.get("/api/export/summary")
def api_export_summary(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    probe_id: Optional[str] = None,
    _user: tuple[str, str] = Depends(get_current_user),
):
    """Download summary report as CSV (per-site min/max/avg for date range)."""
    try:
        db.init_db(STORAGE)
        now = datetime.utcnow()
        if not from_date or not from_date.isdigit():
            from_date = (now - timedelta(days=30)).strftime("%Y%m%d")
        if not to_date or not to_date.isdigit():
            to_date = now.strftime("%Y%m%d")
        if from_date > to_date:
            from_date, to_date = to_date, from_date
        pid = (probe_id or "").strip() or None
        rows = db.get_summary(STORAGE, from_date, to_date, probe_id=pid)
        lines = [
            "site,count,download_mbps_min,download_mbps_max,download_mbps_avg,upload_mbps_min,upload_mbps_max,upload_mbps_avg,latency_ms_min,latency_ms_max,latency_ms_avg",
        ]
        for r in rows:
            def mbps(bps):
                return round((bps or 0) / 1e6, 2) if bps is not None else ""
            def ms(v):
                return round(v, 1) if v is not None else ""
            lines.append(",".join([
                _escape_csv(r.get("site")),
                str(r.get("count", 0)),
                str(mbps(r.get("download_bps_min"))),
                str(mbps(r.get("download_bps_max"))),
                str(mbps(r.get("download_bps_avg"))),
                str(mbps(r.get("upload_bps_min"))),
                str(mbps(r.get("upload_bps_max"))),
                str(mbps(r.get("upload_bps_avg"))),
                str(ms(r.get("latency_ms_min"))),
                str(ms(r.get("latency_ms_max"))),
                str(ms(r.get("latency_ms_avg"))),
            ]))
        body = "\n".join(lines)
        return Response(
            content=body,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="netperf-summary-{from_date}-{to_date}.csv"'},
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/alerts")
def api_alerts(limit: int = 50, _user: tuple[str, str] = Depends(get_current_user)):
    """Return recent SLA alert history (newest first). Default limit 50, max 200."""
    try:
        db.init_db(STORAGE)
        alerts = db.get_alerts(STORAGE, limit=min(max(1, limit), 200))
        return JSONResponse({"alerts": alerts})
    except Exception as e:
        return JSONResponse({"alerts": [], "error": str(e)})


@app.get("/api/sla-status")
def api_sla_status(_user: tuple[str, str] = Depends(get_current_user)):
    """Return SLA config and last alert time (no violation details)."""
    cfg = get_config()
    thresholds = cfg.get("sla_thresholds") or {}
    return JSONResponse({
        "probe_id": cfg.get("probe_id") or "",
        "location_name": cfg.get("location_name") or "",
        "sla_thresholds": {
            "min_download_mbps": thresholds.get("min_download_mbps"),
            "min_upload_mbps": thresholds.get("min_upload_mbps"),
            "max_latency_ms": thresholds.get("max_latency_ms"),
        },
        "webhook_configured": bool((cfg.get("webhook_url") or "").strip() or os.environ.get("WEBHOOK_URL")),
        "last_sla_alert_at": cfg.get("last_sla_alert_at"),
    })


@app.post("/api/clear-old-data")
def api_clear_old_data(days: Optional[int] = None, _user: tuple[str, str] = Depends(require_admin)):
    """Delete log dirs and DB rows older than `days` (keep last N days). If days omitted, uses config retention_days (null = 30)."""
    try:
        cfg = get_config()
        if days is None:
            days = cfg.get("retention_days")
            if days is None:
                days = 30
        days = min(max(int(days), 1), 365)
        cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y%m%d")
        db_deleted_speed, db_deleted_iperf = 0, 0
        if (STORAGE / "netperf.db").exists():
            db.init_db(STORAGE)
            db_deleted_speed, db_deleted_iperf = db.delete_results_before(STORAGE, cutoff)
        dir_deleted = 0
        if STORAGE.exists():
            for d in STORAGE.iterdir():
                if d.is_dir() and d.name.isdigit() and d.name < cutoff:
                    try:
                        shutil.rmtree(d)
                        dir_deleted += 1
                    except OSError:
                        pass
        return JSONResponse({
            "ok": True,
            "deleted_dirs": dir_deleted,
            "deleted_speedtest_rows": db_deleted_speed,
            "deleted_iperf_rows": db_deleted_iperf,
            "message": f"Purged data older than {days} days ({dir_deleted} dirs, {db_deleted_speed + db_deleted_iperf} DB rows).",
        })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


def _voice_webhook_secret() -> str:
    return (os.environ.get("VOICE_WEBHOOK_SECRET") or "").strip() or (get_config().get("voice_webhook_secret") or "").strip()


def _verify_voice_webhook_signature(body: bytes, sig_header: Optional[str]) -> bool:
    """HMAC-SHA256 hex of raw body; header X-Voice-Webhook-Signature or sha256=<hex>. Empty secret = skip verify (dev)."""
    secret = _voice_webhook_secret()
    if not secret:
        return True
    if not sig_header:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    s = (sig_header or "").strip()
    if s.lower().startswith("sha256="):
        s = s[7:]
    try:
        return hmac.compare_digest(expected.lower(), s.lower())
    except Exception:
        return False


@app.get("/api/voice/schema")
def api_voice_schema(_user: tuple[str, str] = Depends(get_current_user)):
    """Domain model reference: bounded contexts, entities, state machines, carrier notes (no secrets)."""
    return JSONResponse(get_domain_schema())


@app.get("/api/voice/webhooks/recent")
def api_voice_webhooks_recent(_user: tuple[str, str] = Depends(require_admin)):
    """Recent inbound voice webhook rows (idempotency log)."""
    try:
        db.init_db(STORAGE)
        return JSONResponse({"events": db.voice_webhook_list_recent(STORAGE)})
    except Exception as e:
        return JSONResponse({"error": str(e), "events": []}, status_code=500)


@app.post("/api/voice/webhooks/{provider}")
async def api_voice_webhook(provider: str, request: Request):
    """
    Carrier webhook ingress: optional HMAC-SHA256 signature (X-Voice-Webhook-Signature),
    idempotency via X-Idempotency-Key or body hash. No Basic auth — restrict by network in production.
    """
    body = await request.body()
    sig = request.headers.get("X-Voice-Webhook-Signature") or request.headers.get("X-Signature")
    if not _verify_voice_webhook_signature(body, sig):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    idem = (request.headers.get("X-Idempotency-Key") or request.headers.get("Idempotency-Key") or "").strip()
    if not idem:
        idem = hashlib.sha256(body).hexdigest()

    prov = (provider or "unknown").strip().lower()[:64]
    db.init_db(STORAGE)
    raw = body.decode("utf-8", errors="replace")
    is_new = db.voice_webhook_try_insert(STORAGE, prov, idem, raw)
    if not is_new:
        return JSONResponse({"ok": True, "duplicate": True, "idempotency_key": idem})

    hdrs = {k: v for k, v in request.headers.items() if k.lower().startswith("x-") or k.lower() in ("content-type",)}
    adapter = get_default_adapter()
    result = adapter.handle_webhook(prov, raw, hdrs)
    return JSONResponse({"ok": True, "duplicate": False, "idempotency_key": idem, "result": result})


@app.post("/api/install-deps")
def api_install_deps(_user: tuple[str, str] = Depends(require_admin)):
    """Run dependency install (Ookla repo, speedtest, iperf3, jq, netperf scripts). Requires root."""
    install_script = APP_DIR / "install-deps.sh"
    if not install_script.exists():
        return JSONResponse(
            {"ok": False, "error": "install-deps.sh not found. Deploy scripts to /opt/netperf-web/scripts."},
            status_code=500,
        )
    try:
        r = subprocess.run(
            ["/bin/bash", str(install_script)],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(APP_DIR),
            env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
        )
        if r.returncode != 0:
            err_tail = (r.stderr or r.stdout or "Install failed").strip()
            diagnostics.bwm_log().warning("install-deps failed rc=%s: %s", r.returncode, err_tail[:3000])
            return JSONResponse(
                {"ok": False, "error": err_tail[:500]},
                status_code=500,
            )
        diagnostics.bwm_log().info("install-deps completed successfully")
        return JSONResponse({"ok": True, "message": "Dependencies installed."})
    except subprocess.TimeoutExpired:
        diagnostics.bwm_log().warning("install-deps timed out (5 min limit)")
        return JSONResponse({"ok": False, "error": "Install timed out (5 min)."}, status_code=500)
    except Exception as e:
        diagnostics.bwm_log().exception("install-deps error: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/api/admin/diagnostics")
def api_admin_diagnostics(
    limit: int = 400,
    sources: str | None = Query(
        None,
        description="Comma-separated: app_buffer,app_events,run_now,speedtest_stderr (default: all)",
    ),
    _user: tuple[str, str] = Depends(require_admin),
):
    """Health checks + parsed log streams (buffer, app-events.log, run-now-last.log, speedtest stderr). Admin only."""
    lim = max(50, min(limit, 2000))
    checks = diagnostics.run_health_checks(STORAGE, CONFIG_PATH)
    want = diagnostics.parse_sources_param(sources)

    streams: dict[str, Any] = {}
    app_log_path = STORAGE / "app-events.log"
    run_now_path = STORAGE / "run-now-last.log"
    st_err = diagnostics.speedtest_stderr_path(STORAGE)

    if "app_buffer" in want:
        buf = diagnostics.get_recent_log_entries(lim)
        streams["app_buffer"] = {"path": None, "lines": buf}
    if "app_events" in want:
        streams["app_events"] = {
            "path": str(app_log_path) if app_log_path.is_file() else str(app_log_path),
            "lines": diagnostics.tail_file_parsed(app_log_path, max_lines=lim, default_level="LOG"),
        }
    if "run_now" in want:
        streams["run_now"] = {
            "path": str(run_now_path),
            "lines": diagnostics.tail_file_parsed(run_now_path, max_lines=lim, default_level="RUN"),
        }
    if "speedtest_stderr" in want:
        lines: list[dict[str, Any]] = []
        if st_err and st_err.is_file():
            lines = diagnostics.tail_file_parsed(
                st_err, max_lines=lim, default_level="STDERR", dedupe_runs=True
            )
        streams["speedtest_stderr"] = {"path": str(st_err) if st_err else None, "lines": lines}

    # Flatten in stable order for clients that want one scroll region
    order = diagnostics.LOG_STREAM_IDS
    merged: list[dict[str, Any]] = []
    for sid in order:
        if sid not in want:
            continue
        meta = streams.get(sid) or {}
        for row in meta.get("lines") or []:
            entry = {**row, "source": sid}
            merged.append(entry)

    legacy_logs = diagnostics.get_recent_log_entries(lim)
    return JSONResponse(
        {
            "checks": checks,
            "logs": legacy_logs,
            "streams": streams,
            "merged": merged,
            "stream_order": [s for s in order if s in want],
            "log_file": str(app_log_path),
            "health_interval_minutes": 5,
        }
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
