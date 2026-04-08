"""Application logging, in-memory log buffer for the UI, and periodic health checks."""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading
from collections import deque
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable

# App log file format: 2025-04-07T12:00:00Z INFO message
_APP_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s+(\w+)\s+(.*)$")
_GENERIC_TS = re.compile(r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})\s+(.*)$")

LOG_STREAM_IDS = ("app_buffer", "app_events", "run_now", "speedtest_stderr")

_lock = threading.Lock()
_buffer: deque[dict[str, Any]] = deque(maxlen=2500)
_logger: logging.Logger | None = None
_health_stop: threading.Event | None = None
_health_thread: threading.Thread | None = None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _BufferHandler(logging.Handler):
    """Keep recent records for GET /api/admin/diagnostics."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            with _lock:
                _buffer.append(
                    {
                        "ts": _utc_now_iso(),
                        "level": record.levelname,
                        "message": record.getMessage(),
                    }
                )
        except Exception:
            pass


def init_diagnostics(storage: Path, config_path: Path) -> Path | None:
    """Attach rotating file log under storage and ring buffer. Returns log file path or None."""
    global _logger
    _logger = logging.getLogger("bwm")
    _logger.setLevel(logging.DEBUG)
    _logger.handlers.clear()
    _logger.propagate = False

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%SZ")
    buf = _BufferHandler()
    buf.setFormatter(fmt)
    _logger.addHandler(buf)

    log_path: Path | None = None
    try:
        storage.mkdir(parents=True, exist_ok=True)
        log_path = storage / "app-events.log"
        fh = RotatingFileHandler(
            str(log_path),
            maxBytes=2_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        fh.setFormatter(fmt)
        _logger.addHandler(fh)
    except OSError as e:
        _logger.warning("Could not create file log under %s: %s", storage, e)

    _logger.info(
        "Diagnostics initialized (storage=%s, config=%s, log_file=%s)",
        storage,
        config_path,
        log_path or "(buffer only)",
    )
    return log_path


def bwm_log() -> logging.Logger:
    """Root app logger; safe before init (no-op handlers)."""
    return logging.getLogger("bwm")


def get_recent_log_entries(limit: int = 300) -> list[dict[str, Any]]:
    with _lock:
        if limit <= 0:
            return []
        return list(_buffer)[-limit:]


def parse_log_line(line: str, default_level: str = "LOG") -> dict[str, Any] | None:
    """Parse one log line into ts / level / message; skip empty lines."""
    s = line.rstrip("\n\r")
    if not s.strip():
        return None
    m = _APP_LINE.match(s)
    if m:
        return {"ts": m.group(1), "level": m.group(2), "message": m.group(3).strip(), "raw": s}
    m2 = _GENERIC_TS.match(s)
    if m2:
        raw_ts = m2.group(1).replace(" ", "T")
        if not raw_ts.endswith("Z"):
            raw_ts = raw_ts + "Z"
        return {"ts": raw_ts, "level": default_level, "message": m2.group(2).strip(), "raw": s}
    return {"ts": "", "level": default_level, "message": s, "raw": s}


def _dedupe_repeated_lines(lines: list[str], repeat_cap: int = 8) -> list[str]:
    """Collapse long runs of identical lines (e.g. Ookla abort spam) with a single summary line."""
    if not lines:
        return []
    out: list[str] = []
    prev: str | None = None
    run = 0
    for line in lines:
        if line == prev:
            run += 1
            if run <= repeat_cap:
                out.append(line)
            elif run == repeat_cap + 1:
                out.append(
                    f"... ({run - repeat_cap} identical lines omitted; "
                    "replace Ookla CLI or set NETPERF_SKIP_TRICKLE=1 if using trickle) ..."
                )
            continue
        prev = line
        run = 1
        out.append(line)
    return out


def tail_file_parsed(
    path: Path,
    *,
    max_lines: int = 500,
    max_bytes: int = 400_000,
    default_level: str = "LOG",
    dedupe_runs: bool = False,
) -> list[dict[str, Any]]:
    """Read last chunk of a text file and return parsed non-empty lines."""
    if not path.is_file():
        return []
    try:
        raw = path.read_bytes()
        if len(raw) > max_bytes:
            raw = raw[-max_bytes:]
        text = raw.decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    if dedupe_runs:
        lines = _dedupe_repeated_lines(lines)
    chunk = lines[-max_lines:] if len(lines) > max_lines else lines
    out: list[dict[str, Any]] = []
    for ln in chunk:
        p = parse_log_line(ln, default_level=default_level)
        if p:
            out.append(p)
    return out


def latest_yyyymmdd_subdir(storage: Path) -> Path | None:
    """Newest YYYYMMDD child directory under storage, if any."""
    best: tuple[str, Path] | None = None
    try:
        for p in storage.iterdir():
            if p.is_dir() and len(p.name) == 8 and p.name.isdigit():
                if best is None or p.name > best[0]:
                    best = (p.name, p)
    except OSError:
        return None
    return best[1] if best else None


def speedtest_stderr_path(storage: Path) -> Path | None:
    """Prefer today's run folder speedtest.stderr.log; else newest date folder; else root file."""
    sub = latest_yyyymmdd_subdir(storage)
    if sub:
        f = sub / "speedtest.stderr.log"
        if f.is_file():
            return f
    root = storage / "speedtest.stderr.log"
    if root.is_file():
        return root
    return None


def parse_sources_param(s: str | None) -> set[str]:
    """Comma-separated source ids; empty or None means all streams."""
    all_ids = set(LOG_STREAM_IDS)
    if not s or not s.strip():
        return all_ids
    got = {x.strip().lower() for x in s.split(",") if x.strip()}
    picked = got & all_ids
    return picked if picked else all_ids


def read_root_crontab() -> str:
    """Same logic as main._crontab_l (avoid import order with FastAPI lifespan)."""
    cmd = ["crontab", "-l"]
    if os.geteuid() != 0:
        cmd = ["sudo", "-n", "crontab", "-l"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return (r.stdout or "") if r.returncode == 0 else ""
    except Exception:
        return ""


def run_health_checks(
    storage: Path,
    config_path: Path,
    crontab_fn: Callable[[], str] | None = None,
) -> list[dict[str, Any]]:
    """Return checklist; log WARNING for each failed check."""
    log = bwm_log()
    checks: list[dict[str, Any]] = []
    issues = 0

    def add(name: str, ok: bool, detail: str = "") -> None:
        nonlocal issues
        checks.append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            issues += 1
            log.warning("Health: FAIL %s — %s", name, detail or "(no detail)")

    add("config_file_exists", config_path.is_file(), str(config_path))
    add("storage_dir_exists", storage.exists() and storage.is_dir(), str(storage))

    writable = False
    wdetail = ""
    if storage.exists() and storage.is_dir():
        try:
            probe = storage / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            writable = True
        except OSError as e:
            wdetail = str(e)
    else:
        wdetail = "storage directory missing" if not storage.exists() else "not a directory"
    add("storage_writable", writable, wdetail)

    add("script_netperf_tester", Path("/bin/netperf-tester").is_file(), "/bin/netperf-tester")
    add("script_netperf_cron_run", Path("/bin/netperf-cron-run").is_file(), "/bin/netperf-cron-run")

    st_bin = Path("/usr/local/bin/speedtest")
    st_which = shutil.which("speedtest")
    ookla_ok = st_bin.is_file() or bool(st_which)
    add(
        "ookla_speedtest_cli",
        ookla_ok,
        f"/usr/local/bin/speedtest={'yes' if st_bin.is_file() else 'no'}, PATH speedtest={st_which or 'none'}",
    )

    db_path = storage / "netperf.db"
    add("database_file", db_path.is_file(), str(db_path))

    cron_txt = ""
    fn = crontab_fn or read_root_crontab
    try:
        cron_txt = fn()
    except Exception as e:
        add("cron_netperf_job", False, f"could not read crontab: {e}")
    else:
        has_netperf = "netperf" in cron_txt
        add(
            "cron_netperf_job",
            has_netperf,
            "found netperf line" if has_netperf else "no netperf entry in root crontab (scheduler may be stopped)",
        )

    if issues:
        log.info("Health check finished: %s issue(s)", issues)
    else:
        log.debug("Health check finished: all OK")
    return checks


def start_background_health_monitor(
    storage: Path,
    config_path: Path,
    crontab_fn: Callable[[], str] | None = None,
    interval_sec: int = 300,
    first_delay_sec: int = 45,
) -> Callable[[], None]:
    """Start daemon thread; return shutdown callback."""
    global _health_stop, _health_thread
    _health_stop = threading.Event()

    def loop() -> None:
        if _health_stop is None:
            return
        if _health_stop.wait(first_delay_sec):
            return
        while True:
            try:
                run_health_checks(storage, config_path, crontab_fn or read_root_crontab)
            except Exception as e:
                bwm_log().exception("Health monitor loop error: %s", e)
            if _health_stop.wait(interval_sec):
                break

    _health_thread = threading.Thread(target=loop, name="bwm-health", daemon=True)
    _health_thread.start()

    def shutdown() -> None:
        if _health_stop:
            _health_stop.set()
        if _health_thread and _health_thread.is_alive():
            _health_thread.join(timeout=5.0)

    return shutdown
