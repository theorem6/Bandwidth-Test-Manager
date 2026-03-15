#!/usr/bin/env python3
"""SQLite storage for netperf results. Best-practice schema for time-series test data."""
import sqlite3
from pathlib import Path
from typing import Any, Optional

# DB path: alongside log dirs (e.g. /var/log/netperf/netperf.db)
def _db_path(storage: Path) -> Path:
    return storage / "netperf.db"


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute("PRAGMA table_info(%s)" % table)
    for row in cur.fetchall():
        if row[1] == column:
            return True
    return False


def init_db(storage: Path) -> None:
    """Create tables if they don't exist; migrate to add probe_id if missing."""
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
                probe_id TEXT DEFAULT '',
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
                probe_id TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_iperf_date ON iperf_results(log_date);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_iperf_dedup ON iperf_results(log_date, site, timestamp);

            CREATE TABLE IF NOT EXISTS alert_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                probe_id TEXT DEFAULT '',
                location_name TEXT DEFAULT '',
                violations_json TEXT NOT NULL,
                webhook_fired INTEGER NOT NULL DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_alert_created ON alert_history(created_at);
        """)
        conn.commit()
        # Migrate existing DBs: add probe_id if missing
        for table in ("speedtest_results", "iperf_results"):
            if not _has_column(conn, table, "probe_id"):
                conn.execute("ALTER TABLE %s ADD COLUMN probe_id TEXT DEFAULT ''" % table)
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
    probe_id: Optional[str] = None,
) -> None:
    """Insert one speedtest result (IGNORE if duplicate)."""
    conn = _get_conn(storage)
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO speedtest_results
            (log_date, site, timestamp, download_bps, upload_bps, latency_ms, server_id, probe_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (log_date, site, timestamp or "", download_bps, upload_bps, latency_ms, server_id or "", probe_id or ""),
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
    probe_id: Optional[str] = None,
) -> None:
    """Insert one iperf result (IGNORE if duplicate)."""
    conn = _get_conn(storage)
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO iperf_results (log_date, site, timestamp, bits_per_sec, probe_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (log_date, site, timestamp or "", bits_per_sec, probe_id or ""),
        )
        conn.commit()
    finally:
        conn.close()


def get_speedtest_for_date(storage: Path, log_date: str, probe_id: Optional[str] = None) -> dict[str, list[dict[str, Any]]]:
    """Return { site: [ {timestamp, download_bps, upload_bps, latency_ms}, ... ] } for charts. Optional probe_id filter."""
    conn = _get_conn(storage)
    try:
        if probe_id:
            rows = conn.execute(
                """
                SELECT site, timestamp, download_bps, upload_bps, latency_ms
                FROM speedtest_results WHERE log_date = ? AND (probe_id = ? OR (probe_id IS NULL OR probe_id = ''))
                ORDER BY timestamp
                """,
                (log_date, probe_id or ""),
            ).fetchall()
        else:
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


def get_iperf_for_date(storage: Path, log_date: str, probe_id: Optional[str] = None) -> dict[str, list[dict[str, Any]]]:
    """Return { site: [ {timestamp, bits_per_sec}, ... ] } for charts. Optional probe_id filter."""
    conn = _get_conn(storage)
    try:
        if probe_id:
            rows = conn.execute(
                """
                SELECT site, timestamp, bits_per_sec
                FROM iperf_results WHERE log_date = ? AND (probe_id = ? OR (probe_id IS NULL OR probe_id = ''))
                ORDER BY timestamp
                """,
                (log_date, probe_id or ""),
            ).fetchall()
        else:
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


def delete_results_before(storage: Path, cutoff_ymd: str) -> tuple[int, int]:
    """Delete speedtest and iperf results with log_date < cutoff_ymd. Returns (speedtest_deleted, iperf_deleted)."""
    conn = _get_conn(storage)
    try:
        cur = conn.execute("DELETE FROM speedtest_results WHERE log_date < ?", (cutoff_ymd,))
        speedtest_deleted = cur.rowcount
        cur = conn.execute("DELETE FROM iperf_results WHERE log_date < ?", (cutoff_ymd,))
        iperf_deleted = cur.rowcount
        conn.commit()
        return (speedtest_deleted, iperf_deleted)
    finally:
        conn.close()


def get_summary(
    storage: Path,
    from_ymd: str,
    to_ymd: str,
    probe_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Return per-site summary (min/max/avg download, upload, latency; count) for log_date in [from_ymd, to_ymd]."""
    conn = _get_conn(storage)
    try:
        if probe_id:
            rows = conn.execute(
                """
                SELECT site,
                    COUNT(*),
                    MIN(download_bps), MAX(download_bps), AVG(download_bps),
                    MIN(upload_bps), MAX(upload_bps), AVG(upload_bps),
                    MIN(latency_ms), MAX(latency_ms), AVG(latency_ms)
                FROM speedtest_results
                WHERE log_date >= ? AND log_date <= ? AND (probe_id = ? OR probe_id = '' OR probe_id IS NULL)
                GROUP BY site
                """,
                (from_ymd, to_ymd, probe_id or ""),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT site,
                    COUNT(*),
                    MIN(download_bps), MAX(download_bps), AVG(download_bps),
                    MIN(upload_bps), MAX(upload_bps), AVG(upload_bps),
                    MIN(latency_ms), MAX(latency_ms), AVG(latency_ms)
                FROM speedtest_results
                WHERE log_date >= ? AND log_date <= ?
                GROUP BY site
                """,
                (from_ymd, to_ymd),
            ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        site, cnt, min_d, max_d, avg_d, min_u, max_u, avg_u, min_l, max_l, avg_l = r
        out.append({
            "site": site or "",
            "count": cnt or 0,
            "download_bps_min": min_d,
            "download_bps_max": max_d,
            "download_bps_avg": round(avg_d, 2) if avg_d is not None else None,
            "upload_bps_min": min_u,
            "upload_bps_max": max_u,
            "upload_bps_avg": round(avg_u, 2) if avg_u is not None else None,
            "latency_ms_min": min_l,
            "latency_ms_max": max_l,
            "latency_ms_avg": round(avg_l, 2) if avg_l is not None else None,
        })
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


def get_latest_speedtest_results(storage: Path, log_date: str, probe_id: Optional[str] = None) -> list[dict[str, Any]]:
    """Return the most recent speedtest result per site for the given log_date (for SLA evaluation)."""
    conn = _get_conn(storage)
    try:
        if probe_id:
            rows = conn.execute(
                """
                SELECT site, timestamp, download_bps, upload_bps, latency_ms
                FROM speedtest_results
                WHERE log_date = ? AND (probe_id = ? OR probe_id = '' OR probe_id IS NULL)
                ORDER BY timestamp DESC
                """,
                (log_date, probe_id or ""),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT site, timestamp, download_bps, upload_bps, latency_ms
                FROM speedtest_results WHERE log_date = ?
                ORDER BY timestamp DESC
                """,
                (log_date,),
            ).fetchall()
    finally:
        conn.close()
    # One result per site (first seen = latest due to ORDER BY timestamp DESC)
    seen: set[str] = set()
    out = []
    for site, ts, down, up, lat in rows:
        if site not in seen:
            seen.add(site)
            out.append({
                "site": site,
                "timestamp": ts or "",
                "download_bps": down,
                "upload_bps": up,
                "latency_ms": lat,
            })
    return out


def insert_alert(
    storage: Path,
    probe_id: str,
    location_name: str,
    violations: list[dict[str, Any]],
    webhook_fired: bool = True,
) -> None:
    """Append one SLA alert to history."""
    import json
    conn = _get_conn(storage)
    try:
        conn.execute(
            """
            INSERT INTO alert_history (created_at, probe_id, location_name, violations_json, webhook_fired)
            VALUES (datetime('now'), ?, ?, ?, ?)
            """,
            (probe_id or "", location_name or "", json.dumps(violations), 1 if webhook_fired else 0),
        )
        conn.commit()
    finally:
        conn.close()


def get_alerts(storage: Path, limit: int = 50) -> list[dict[str, Any]]:
    """Return most recent SLA alerts (newest first)."""
    conn = _get_conn(storage)
    try:
        rows = conn.execute(
            """
            SELECT id, created_at, probe_id, location_name, violations_json, webhook_fired
            FROM alert_history ORDER BY id DESC LIMIT ?
            """,
            (max(1, min(limit, 200)),),
        ).fetchall()
    finally:
        conn.close()
    import json
    out = []
    for r in rows:
        try:
            violations = json.loads(r[4]) if r[4] else []
        except Exception:
            violations = []
        out.append({
            "id": r[0],
            "created_at": r[1] or "",
            "probe_id": r[2] or "",
            "location_name": r[3] or "",
            "violations": violations,
            "webhook_fired": bool(r[5]),
        })
    return out


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
    probe_id: Optional[str] = None,
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
            probe_id=probe_id,
        )


def import_iperf_file_into_db(
    storage: Path,
    log_date: str,
    label: str,
    points: list[dict[str, Any]],
    probe_id: Optional[str] = None,
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
                probe_id=probe_id,
            )
