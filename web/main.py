#!/usr/bin/env python3
"""Bandwidth Test Manager - Web API and UI (FastAPI + Uvicorn)."""
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import db
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from typing import Any, Optional

# Users: username -> (password, role). role: "admin" | "readonly"
AUTH_USERS = {
    "bwadmin": ("unl0ck", "admin"),
    "user": ("user", "readonly"),
}
security_basic = HTTPBasic(auto_error=False)


def get_current_user(credentials: Optional[HTTPBasicCredentials] = Depends(security_basic)) -> tuple[str, str]:
    """Validate Basic auth and return (username, role). Raises 401 if invalid. No WWW-Authenticate so browser does not show native popup; use in-page login only."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Login required")
    username, password = credentials.username, credentials.password
    if username not in AUTH_USERS:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    passwd, role = AUTH_USERS[username]
    if password != passwd:
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

app = FastAPI(title="Bandwidth Test Manager", docs_url=None, redoc_url=None)


class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Any) -> Any:
        response = await super().get_response(path, scope)
        if hasattr(response, "headers"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response


static_dir = APP_DIR / "static"
if static_dir.exists():
    app.mount("/static", NoCacheStaticFiles(directory=str(static_dir)), name="static")


def get_config() -> dict:
    defaults = {
        "site_url": "",
        "ssl_cert_path": "",
        "ssl_key_path": "",
        "speedtest_limit_mbps": None,
        "cron_schedule": "5 * * * *",
        "iperf_duration_seconds": 10,
        "ookla_servers": [],
        "iperf_servers": [],
        "iperf_tests": [],
    }
    if not CONFIG_PATH.exists():
        return defaults
    with open(CONFIG_PATH, "r") as f:
        data = json.load(f)
    for k, v in defaults.items():
        if k not in data:
            data[k] = v
    return data


def save_config(data: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)


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
        "timestamp": str(obj.get("timestamp", "")),
        "download_bps": download_bps,
        "upload_bps": upload_bps,
        "latency_ms": latency_ms,
        "server_id": server.get("id", "ND"),
        "server_name": server.get("name", "ND"),
        "server_location": server.get("location", "ND"),
    }


def _split_json_objects(raw: str) -> list[dict]:
    """Split concatenated JSON objects (e.g. multiple runs appended to one file). Returns list of dicts."""
    out: list[dict] = []
    # Try splitting by "}\s*{" to get separate objects
    parts = re.split(r"\}\s*\{", raw.strip())
    for i, part in enumerate(parts):
        part = part.strip()
        if not part:
            continue
        if not part.startswith("{"):
            part = "{" + part
        if not part.endswith("}"):
            part = part + "}"
        try:
            obj = json.loads(part)
            if isinstance(obj, dict):
                out.append(obj)
        except (json.JSONDecodeError, TypeError):
            continue
    return out


def parse_speedtest_file(path: Path) -> list:
    """Parse Ookla speedtest -f json output (JSONL or concatenated JSON). Returns list of result points.
    Handles multiple runs per file so all speedtests are saved, not just the last."""
    results = []
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return results
    # 1) Line-by-line (JSONL: one result per line)
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
    # 2) If we got nothing, try splitting concatenated JSON objects (e.g. multiple runs in one file)
    if not results and raw.strip():
        for obj in _split_json_objects(raw):
            pt = _speedtest_result_to_point(obj)
            if not pt:
                pt = _speedtest_result_to_point(obj, require_type=False)
            if pt:
                results.append(pt)
    # 3) Whole file as single JSON (some CLI versions)
    if not results and raw.strip():
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                pt = _speedtest_result_to_point(obj)
                if pt:
                    results.append(pt)
                else:
                    pt = _speedtest_result_to_point(obj, require_type=False)
                    if pt:
                        results.append(pt)
            elif isinstance(obj, list):
                for item in obj:
                    if isinstance(item, dict):
                        pt = _speedtest_result_to_point(item)
                        if not pt:
                            pt = _speedtest_result_to_point(item, require_type=False)
                        if pt:
                            results.append(pt)
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
    # 4) Lenient line-by-line fallback
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
    """Load that day's result files from STORAGE into the SQLite DB (idempotent)."""
    day_dir = STORAGE / log_date
    if not day_dir.exists() or not day_dir.is_dir():
        return
    db.init_db(STORAGE)
    for f in sorted(day_dir.glob("[0-9]_speedtest-*")):
        label = site_label_from_speedtest_filename(f.name)
        points = parse_speedtest_file(f)
        if points:
            db.import_speedtest_file_into_db(STORAGE, log_date, label, points)
    for f in sorted(day_dir.glob("iperf-*.txt")):
        label = site_label_from_iperf_filename(f.name)
        points = parse_iperf_file(f, log_date=log_date, summary_only=True)
        if points:
            db.import_iperf_file_into_db(STORAGE, log_date, label, points)


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


@app.get("/api/me")
def api_me(user: tuple[str, str] = Depends(get_current_user)):
    """Return current user and role (for login flow and UI)."""
    return JSONResponse({"username": user[0], "role": user[1]})


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
def api_speedtest_servers(_user: tuple[str, str] = Depends(get_current_user)):
    """Return list of Ookla Speedtest servers. Tries JSON first; on crash/failure uses plain speedtest -L.
    If the default speedtest crashes, tries /usr/local/bin/speedtest (official binary from install-deps)."""
    env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
    error_note: Optional[str] = None
    servers: list[dict] = []

    # Prefer official binary if present (install-deps installs it when package version crashes)
    speedtest_bin = "/usr/local/bin/speedtest" if Path("/usr/local/bin/speedtest").exists() else "speedtest"

    try:
        # Try JSON first (some Ookla builds crash with -f json: "basic_string::_M_construct null not valid")
        out, err, code = _run_speedtest_list([speedtest_bin, "-L", "-f", "json"], env)
        if out:
            servers = _parse_speedtest_servers_json(out)
        if not out or (code != 0 and not servers):
            error_note = err or "JSON list failed or empty"
    except FileNotFoundError:
        return JSONResponse({"servers": [], "error": "speedtest CLI not installed. Use Setup to install."})

    # Fallback 1: plain text with same binary (no -f json)
    if not servers:
        try:
            out, err, _ = _run_speedtest_list([speedtest_bin, "-L"], env)
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
            out, err, _ = _run_speedtest_list(["/usr/local/bin/speedtest", "-L"], env)
            if out:
                servers = _parse_speedtest_servers_text(out)
                error_note = "Server list from text (JSON list failed on this Speedtest build)." if error_note else None
        except Exception:
            pass

    # Dedupe by id
    seen = set()
    unique = []
    for s in servers:
        sid = s["id"]
        if sid not in seen:
            seen.add(sid)
            unique.append(s)

    # Don't show raw C++ crash to user (e.g. "terminate called... basic_string::_M_construct null not valid")
    if error_note and (
        "terminate called" in error_note
        or "logic_error" in error_note
        or "basic_string" in error_note
    ):
        error_note = "Speedtest CLI list failed on this build (you can still enter a server ID below)."

    return JSONResponse({"servers": unique, "error": error_note} if error_note else {"servers": unique})


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
        from datetime import datetime
        today = datetime.utcnow().strftime("%Y%m%d")
        storage_today = STORAGE / today
        storage_today.mkdir(parents=True, exist_ok=True)
        if Path("/bin/netperf-tester").exists():
            run_args = ["/bin/netperf-tester", str(storage_today)]
    if not run_args:
        return []
    if os.geteuid() != 0:
        return ["sudo", "-n"] + run_args
    return run_args


@app.post("/api/run-now")
def api_run_now(_user: tuple[str, str] = Depends(require_admin)):
    """Start speedtest + iperf in background. Returns immediately; client should poll GET /api/run-status. Uses sudo when app is not root so tests actually run."""
    cmd = _run_now_cmd()
    if not cmd:
        return JSONResponse({"ok": False, "error": "netperf scripts not found. Use Setup to install dependencies."})
    STORAGE.mkdir(parents=True, exist_ok=True)
    RUN_NOW_SENTINEL.touch()
    import threading
    def run():
        try:
            subprocess.run(
                cmd,
                capture_output=True,
                timeout=600,
                cwd="/",
                env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
            )
        except Exception:
            pass
        finally:
            RUN_NOW_SENTINEL.unlink(missing_ok=True)
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return JSONResponse({"ok": True, "message": "Test started. Poll run-status for completion."})


@app.get("/api/config")
def api_config_get(_user: tuple[str, str] = Depends(get_current_user)):
    return JSONResponse(get_config())


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
        v = (data.get("cron_schedule") or "").strip() or "5 * * * *"
        # Basic sanity: 5 fields for cron
        if len(v.split()) >= 5:
            cur["cron_schedule"] = v
    if "iperf_duration_seconds" in data:
        v = data.get("iperf_duration_seconds")
        try:
            n = int(v) if v is not None and str(v).strip() != "" else 10
            cur["iperf_duration_seconds"] = max(1, min(300, n))  # clamp 1–300 seconds
        except (TypeError, ValueError):
            cur["iperf_duration_seconds"] = 10
    if "ookla_servers" in data:
        raw_ookla = data.get("ookla_servers")
        if isinstance(raw_ookla, list):
            cur["ookla_servers"] = []
            for s in raw_ookla:
                if not isinstance(s, dict):
                    continue
                sid = s.get("id")
                label = str(s.get("label") or "").strip() or "Server"
                if sid == "auto" or sid is None or (isinstance(sid, str) and sid.strip().lower() in ("", "auto")):
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
        # else leave cur unchanged
    try:
        save_config(cur)
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


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
def api_data(date: Optional[str] = None):
    """Return speedtest and iperf data for a date. Reads from SQLite; imports from files first if needed."""
    try:
        if not date or not date.isdigit():
            return JSONResponse({"error": "missing or invalid date"}, status_code=400)
        _import_day_from_files(date)
        speedtest = db.get_speedtest_for_date(STORAGE, date)
        iperf = db.get_iperf_for_date(STORAGE, date)
        return JSONResponse({"speedtest": speedtest, "iperf": iperf})
    except Exception:
        return JSONResponse({"speedtest": {}, "iperf": {}})


def _escape_csv(val: Any) -> str:
    if val is None:
        return ""
    s = str(val)
    if "," in s or '"' in s or "\n" in s:
        return '"' + s.replace('"', '""') + '"'
    return s


@app.get("/api/export/csv")
def api_export_csv(date: Optional[str] = None, _user: tuple[str, str] = Depends(get_current_user)):
    """Export full speedtest and iperf data for a date as CSV (all interval points; chart shows summary only)."""
    if not date or not date.isdigit():
        return Response(status_code=400)
    day_dir = STORAGE / date
    if not day_dir.exists() or not day_dir.is_dir():
        return Response(status_code=404)
    rows: list[list[str]] = []
    # Header: type, date, site, timestamp, download_mbps, upload_mbps, latency_ms, throughput_mbps
    rows.append(["type", "date", "site", "timestamp", "download_mbps", "upload_mbps", "latency_ms", "throughput_mbps"])
    for f in sorted(day_dir.glob("[0-9]_speedtest-*")):
        label = site_label_from_speedtest_filename(f.name)
        for pt in parse_speedtest_file(f):
            d = pt.get("download_bps")
            u = pt.get("upload_bps")
            rows.append([
                "speedtest",
                date,
                _escape_csv(label),
                _escape_csv(pt.get("timestamp")),
                str(round((d or 0) / 1e6, 2)) if d is not None else "",
                str(round((u or 0) / 1e6, 2)) if u is not None else "",
                str(pt.get("latency_ms")) if pt.get("latency_ms") is not None else "",
                "",
            ])
    for f in sorted(day_dir.glob("iperf-*.txt")):
        label = site_label_from_iperf_filename(f.name)
        for pt in parse_iperf_file(f, log_date=date, summary_only=False):
            b = pt.get("bits_per_sec")
            rows.append([
                "iperf",
                date,
                _escape_csv(label),
                _escape_csv(pt.get("timestamp")),
                "",
                "",
                "",
                str(round((b or 0) / 1e6, 2)) if b is not None else "",
            ])
    body = "\n".join(",".join(_escape_csv(str(c)) for c in row) for row in rows)
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="netperf-{date}.csv"'},
    )


@app.get("/api/history")
def api_history(days: int = 90):
    """Return time-series data for trend graphs. Reads from SQLite; imports file data for dates in range first."""
    try:
        db.init_db(STORAGE)
        cutoff = (datetime.utcnow() - timedelta(days=min(days, 365))).strftime("%Y%m%d")
        if STORAGE.exists():
            for d in STORAGE.iterdir():
                if d.is_dir() and d.name.isdigit() and d.name >= cutoff:
                    _import_day_from_files(d.name)
        speedtest_points = db.get_history_speedtest(STORAGE, cutoff)
        iperf_points = db.get_history_iperf(STORAGE, cutoff)
        return JSONResponse({"speedtest": speedtest_points, "iperf": iperf_points})
    except Exception:
        return JSONResponse({"speedtest": [], "iperf": []})


@app.get("/api/status")
def api_status():
    try:
        out = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        scheduled = "netperf" in (out.stdout or "")
    except (subprocess.TimeoutExpired, Exception):
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
    try:
        out = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        scheduled = "netperf" in (out.stdout or "")
    except Exception:
        pass

    cfg = get_config()
    ookla_list = cfg.get("ookla_servers") or []
    iperf_servers_list = cfg.get("iperf_servers") or []
    cron_line = ""
    if scheduled:
        try:
            out = subprocess.run(
                ["crontab", "-l"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            for line in (out.stdout or "").splitlines():
                if "netperf" in line:
                    cron_line = line.strip()
                    break
        except Exception:
            pass
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


@app.post("/api/clear-old-data")
def api_clear_old_data(days: int = 30, _user: tuple[str, str] = Depends(require_admin)):
    """Delete log directories older than `days` (keep last N days). Default 30."""
    try:
        if not STORAGE.exists():
            return JSONResponse({"ok": True, "deleted": 0, "message": "No storage dir."})
        cutoff = (datetime.utcnow() - timedelta(days=min(max(days, 1), 365))).strftime("%Y%m%d")
        deleted = 0
        for d in STORAGE.iterdir():
            if d.is_dir() and d.name.isdigit() and d.name < cutoff:
                try:
                    shutil.rmtree(d)
                    deleted += 1
                except OSError:
                    pass
        return JSONResponse({"ok": True, "deleted": deleted, "message": f"Removed {deleted} day(s) older than {days} days."})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


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
            return JSONResponse(
                {"ok": False, "error": (r.stderr or r.stdout or "Install failed").strip()[:500]},
                status_code=500,
            )
        return JSONResponse({"ok": True, "message": "Dependencies installed."})
    except subprocess.TimeoutExpired:
        return JSONResponse({"ok": False, "error": "Install timed out (5 min)."}, status_code=500)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
