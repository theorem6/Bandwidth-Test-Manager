"""Application logging, in-memory log buffer for the UI, and periodic health checks."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from collections import deque
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable

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
            msg = self.format(record)
            with _lock:
                _buffer.append(
                    {
                        "ts": _utc_now_iso(),
                        "level": record.levelname,
                        "message": msg,
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
