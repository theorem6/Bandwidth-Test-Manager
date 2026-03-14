#!/usr/bin/env python3
"""SQLite storage for netperf results. Best-practice schema for time-series test data."""
import sqlite3
from pathlib import Path
from typing import Any, Optional

# DB path: alongside log dirs (e.g. /var/log/netperf/netperf.db)
def _db_path(storage: Path) -> Path:
    return storage / "netperf.db"


def init_db(storage: Path) -> None:
    """Create tables if they don't exist."""
    path = _db_path(storage)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS speedtest_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                log_date TEXT NOT NULL,
                site TEXT NOT NULL,
                timestamp TEXT,
                download_bps INTEGER,
                upload_bps INTEGER,
                latency_ms REAL,
                server_id TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_speedtest_date ON speedtest_results(log_date);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_speedtest_dedup ON speedtest_results(log_date, site, timestamp);

            CREATE TABLE IF NOT EXISTS iperf_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                log_date TEXT NOT NULL,
                site TEXT NOT NULL,
                timestamp TEXT,
                bits_per_sec REAL NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_iperf_date ON iperf_results(log_date);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_iperf_dedup ON iperf_results(log_date, site, timestamp);
        """)
        conn.commit()
    finally:
        conn.close()


def _get_conn(storage: Path) -> sqlite3.Connection:
    path = _db_path(storage)
    if not path.exists():
        init_db(storage)
    return sqlite3.connect(str(path))


def insert_speedtest(
    storage: Path,
    log_date: str,
    site: str,
    timestamp: Optional[str],
    download_bps: Optional[int],
    upload_bps: Optional[int],
    latency_ms: Optional[float],
    server_id: Optional[str] = None,
) -> None:
    """Insert one speedtest result (IGNORE if duplicate)."""
    conn = _get_conn(storage)
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO speedtest_results
            (log_date, site, timestamp, download_bps, upload_bps, latency_ms, server_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (log_date, site, timestamp or "", download_bps, upload_bps, latency_ms, server_id or ""),
        )
        conn.commit()
    finally:
        conn.close()


def insert_iperf(
    storage: Path,
    log_date: str,
    site: str,
    timestamp: Optional[str],
    bits_per_sec: float,
) -> None:
    """Insert one iperf result (IGNORE if duplicate)."""
    conn = _get_conn(storage)
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO iperf_results (log_date, site, timestamp, bits_per_sec)
            VALUES (?, ?, ?, ?)
            """,
            (log_date, site, timestamp or "", bits_per_sec),
        )
        conn.commit()
    finally:
        conn.close()


def get_speedtest_for_date(storage: Path, log_date: str) -> dict[str, list[dict[str, Any]]]:
    """Return { site: [ {timestamp, download_bps, upload_bps, latency_ms}, ... ] } for charts."""
    conn = _get_conn(storage)
    try:
        rows = conn.execute(
            """
            SELECT site, timestamp, download_bps, upload_bps, latency_ms
            FROM speedtest_results WHERE log_date = ? ORDER BY timestamp
            """,
            (log_date,),
        ).fetchall()
    finally:
        conn.close()
    out: dict[str, list[dict[str, Any]]] = {}
    for site, ts, down, up, lat in rows:
        if site not in out:
            out[site] = []
        out[site].append({
            "timestamp": ts or "",
            "download_bps": down,
            "upload_bps": up,
            "latency_ms": lat,
        })
    return out


def get_iperf_for_date(storage: Path, log_date: str) -> dict[str, list[dict[str, Any]]]:
    """Return { site: [ {timestamp, bits_per_sec}, ... ] } for charts."""
    conn = _get_conn(storage)
    try:
        rows = conn.execute(
            """
            SELECT site, timestamp, bits_per_sec
            FROM iperf_results WHERE log_date = ? ORDER BY timestamp
            """,
            (log_date,),
        ).fetchall()
    finally:
        conn.close()
    out: dict[str, list[dict[str, Any]]] = {}
    for site, ts, bps in rows:
        if site not in out:
            out[site] = []
        out[site].append({"timestamp": ts or "", "bits_per_sec": bps})
    return out


def get_dates(storage: Path) -> list[str]:
    """Return sorted list of log_date (YYYYMMDD) that have any data."""
    conn = _get_conn(storage)
    try:
        dates = set()
        for row in conn.execute("SELECT DISTINCT log_date FROM speedtest_results").fetchall():
            dates.add(row[0])
        for row in conn.execute("SELECT DISTINCT log_date FROM iperf_results").fetchall():
            dates.add(row[0])
    finally:
        conn.close()
    return sorted(dates, reverse=True)


def get_history_speedtest(storage: Path, cutoff_ymd: str) -> list[dict[str, Any]]:
    """Return all speedtest points with log_date >= cutoff_ymd (YYYYMMDD) for trend charts."""
    conn = _get_conn(storage)
    try:
        rows = conn.execute(
            """
            SELECT log_date, site, timestamp, download_bps, upload_bps, latency_ms
            FROM speedtest_results
            WHERE log_date >= ?
            ORDER BY log_date, timestamp
            """,
            (cutoff_ymd,),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "date": r[0],
            "site": r[1],
            "timestamp": r[2] or "",
            "download_bps": r[3],
            "upload_bps": r[4],
            "latency_ms": r[5],
        }
        for r in rows
    ]


def get_history_iperf(storage: Path, cutoff_ymd: str) -> list[dict[str, Any]]:
    """Return all iperf points with log_date >= cutoff_ymd (YYYYMMDD) for trend charts."""
    conn = _get_conn(storage)
    try:
        rows = conn.execute(
            """
            SELECT log_date, site, timestamp, bits_per_sec
            FROM iperf_results
            WHERE log_date >= ?
            ORDER BY log_date, timestamp
            """,
            (cutoff_ymd,),
        ).fetchall()
    finally:
        conn.close()
    return [
        {"date": r[0], "site": r[1], "timestamp": r[2] or "", "bits_per_sec": r[3]}
        for r in rows
    ]


def import_speedtest_file_into_db(
    storage: Path,
    log_date: str,
    label: str,
    points: list[dict[str, Any]],
) -> None:
    """Insert parsed speedtest points from a file into the DB."""
    for pt in points:
        insert_speedtest(
            storage,
            log_date=log_date,
            site=label,
            timestamp=pt.get("timestamp"),
            download_bps=pt.get("download_bps"),
            upload_bps=pt.get("upload_bps"),
            latency_ms=pt.get("latency_ms"),
            server_id=pt.get("server_id"),
        )


def import_iperf_file_into_db(
    storage: Path,
    log_date: str,
    label: str,
    points: list[dict[str, Any]],
) -> None:
    """Insert parsed iperf points from a file into the DB."""
    for pt in points:
        bps = pt.get("bits_per_sec")
        if bps is not None:
            insert_iperf(
                storage,
                log_date=log_date,
                site=label,
                timestamp=pt.get("timestamp"),
                bits_per_sec=float(bps),
            )
