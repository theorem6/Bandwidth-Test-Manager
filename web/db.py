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

            CREATE TABLE IF NOT EXISTS remote_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                location TEXT DEFAULT '',
                address TEXT DEFAULT '',
                token TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                last_seen_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_remote_nodes_node_id ON remote_nodes(node_id);
            CREATE INDEX IF NOT EXISTS idx_remote_nodes_token ON remote_nodes(token);

            CREATE TABLE IF NOT EXISTS voice_webhook_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                raw_payload TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_voice_webhook_idem
                ON voice_webhook_events(provider, idempotency_key);
        """)
        conn.commit()
        # Migrate existing DBs: add probe_id if missing
        for table in ("speedtest_results", "iperf_results"):
            if not _has_column(conn, table, "probe_id"):
                conn.execute("ALTER TABLE %s ADD COLUMN probe_id TEXT DEFAULT ''" % table)
                conn.commit()
        # Migrate remote_nodes: add address if missing
        if not _has_column(conn, "remote_nodes", "address"):
            conn.execute("ALTER TABLE remote_nodes ADD COLUMN address TEXT DEFAULT ''")
            conn.commit()
        # One-time (user_version < 2): empty timestamp breaks UNIQUE(log_date,site,timestamp).
        uv_row = conn.execute("PRAGMA user_version").fetchone()
        uv = int(uv_row[0]) if uv_row and uv_row[0] is not None else 0
        if uv < 2:
            conn.execute(
                "UPDATE speedtest_results SET timestamp = 'legacy-st-' || CAST(id AS TEXT) "
                "WHERE timestamp IS NULL OR TRIM(COALESCE(timestamp, '')) = ''"
            )
            conn.execute(
                "UPDATE iperf_results SET timestamp = 'legacy-ip-' || CAST(id AS TEXT) "
                "WHERE timestamp IS NULL OR TRIM(COALESCE(timestamp, '')) = ''"
            )
            conn.execute("PRAGMA user_version = 2")
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
            "log_date": log_date,
            "download_bps": down,
            "upload_bps": up,
            "latency_ms": lat,
        })
    return out


def get_speedtest_for_range(
    storage: Path, from_ymd: str, to_ymd: str, probe_id: Optional[str] = None
) -> dict[str, list[dict[str, Any]]]:
    """Return { site: [ points ] } for log_date in [from_ymd, to_ymd] inclusive. Each point includes log_date."""
    conn = _get_conn(storage)
    try:
        if probe_id:
            rows = conn.execute(
                """
                SELECT site, timestamp, download_bps, upload_bps, latency_ms, log_date
                FROM speedtest_results
                WHERE log_date >= ? AND log_date <= ? AND (probe_id = ? OR probe_id = '' OR probe_id IS NULL)
                ORDER BY log_date, timestamp, site
                """,
                (from_ymd, to_ymd, probe_id or ""),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT site, timestamp, download_bps, upload_bps, latency_ms, log_date
                FROM speedtest_results
                WHERE log_date >= ? AND log_date <= ?
                ORDER BY log_date, timestamp, site
                """,
                (from_ymd, to_ymd),
            ).fetchall()
    finally:
        conn.close()
    out: dict[str, list[dict[str, Any]]] = {}
    for site, ts, down, up, lat, ld in rows:
        if site not in out:
            out[site] = []
        out[site].append({
            "timestamp": ts or "",
            "log_date": ld,
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
        out[site].append({"timestamp": ts or "", "log_date": log_date, "bits_per_sec": bps})
    return out


def get_iperf_for_range(
    storage: Path, from_ymd: str, to_ymd: str, probe_id: Optional[str] = None
) -> dict[str, list[dict[str, Any]]]:
    """Return { site: [ points ] } for log_date in [from_ymd, to_ymd] inclusive."""
    conn = _get_conn(storage)
    try:
        if probe_id:
            rows = conn.execute(
                """
                SELECT site, timestamp, bits_per_sec, log_date
                FROM iperf_results
                WHERE log_date >= ? AND log_date <= ? AND (probe_id = ? OR probe_id = '' OR probe_id IS NULL)
                ORDER BY log_date, timestamp, site
                """,
                (from_ymd, to_ymd, probe_id or ""),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT site, timestamp, bits_per_sec, log_date
                FROM iperf_results
                WHERE log_date >= ? AND log_date <= ?
                ORDER BY log_date, timestamp, site
                """,
                (from_ymd, to_ymd),
            ).fetchall()
    finally:
        conn.close()
    out: dict[str, list[dict[str, Any]]] = {}
    for site, ts, bps, ld in rows:
        if site not in out:
            out[site] = []
        out[site].append({"timestamp": ts or "", "log_date": ld, "bits_per_sec": bps})
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


def get_speedtest_export_rows(storage: Path, log_date: str) -> list[tuple[Any, ...]]:
    """All speedtest rows for one day (CSV export). Tuples: site, timestamp, download_bps, upload_bps, latency_ms, probe_id."""
    conn = _get_conn(storage)
    try:
        rows = conn.execute(
            """
            SELECT site, timestamp, download_bps, upload_bps, latency_ms, IFNULL(probe_id, '')
            FROM speedtest_results WHERE log_date = ? ORDER BY timestamp, site
            """,
            (log_date,),
        ).fetchall()
    finally:
        conn.close()
    return list(rows)


def get_iperf_export_rows(storage: Path, log_date: str) -> list[tuple[Any, ...]]:
    """All iperf rows for one day (CSV export). Tuples: site, timestamp, bits_per_sec, probe_id."""
    conn = _get_conn(storage)
    try:
        rows = conn.execute(
            """
            SELECT site, timestamp, bits_per_sec, IFNULL(probe_id, '')
            FROM iperf_results WHERE log_date = ? ORDER BY timestamp, site
            """,
            (log_date,),
        ).fetchall()
    finally:
        conn.close()
    return list(rows)


def get_history_speedtest(
    storage: Path, cutoff_ymd: str, probe_id: Optional[str] = None
) -> list[dict[str, Any]]:
    """Return all speedtest points with log_date >= cutoff_ymd (YYYYMMDD) for trend charts. Optional probe_id filter."""
    conn = _get_conn(storage)
    try:
        if probe_id and probe_id.strip():
            rows = conn.execute(
                """
                SELECT log_date, site, timestamp, download_bps, upload_bps, latency_ms
                FROM speedtest_results
                WHERE log_date >= ? AND (probe_id = ? OR probe_id = '' OR probe_id IS NULL)
                ORDER BY log_date, timestamp
                """,
                (cutoff_ymd, probe_id.strip()),
            ).fetchall()
        else:
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


def get_history_iperf(
    storage: Path, cutoff_ymd: str, probe_id: Optional[str] = None
) -> list[dict[str, Any]]:
    """Return all iperf points with log_date >= cutoff_ymd (YYYYMMDD) for trend charts. Optional probe_id filter."""
    conn = _get_conn(storage)
    try:
        if probe_id and probe_id.strip():
            rows = conn.execute(
                """
                SELECT log_date, site, timestamp, bits_per_sec
                FROM iperf_results
                WHERE log_date >= ? AND (probe_id = ? OR probe_id = '' OR probe_id IS NULL)
                ORDER BY log_date, timestamp
                """,
                (cutoff_ymd, probe_id.strip()),
            ).fetchall()
        else:
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


# --- Remote nodes (probes that report back to this main node) ---

def list_remote_nodes(storage: Path) -> list[dict[str, Any]]:
    """Return all remote nodes (node_id, name, location, address, created_at, last_seen_at). Token not returned."""
    conn = _get_conn(storage)
    try:
        if _has_column(conn, "remote_nodes", "address"):
            rows = conn.execute(
                "SELECT node_id, name, location, COALESCE(address,''), created_at, last_seen_at FROM remote_nodes ORDER BY name"
            ).fetchall()
            return [
                {"node_id": r[0], "name": r[1], "location": r[2] or "", "address": r[3] or "", "created_at": r[4] or "", "last_seen_at": r[5] or ""}
                for r in rows
            ]
        rows = conn.execute(
            "SELECT node_id, name, location, created_at, last_seen_at FROM remote_nodes ORDER BY name"
        ).fetchall()
        return [
            {"node_id": r[0], "name": r[1], "location": r[2] or "", "address": "", "created_at": r[3] or "", "last_seen_at": r[4] or ""}
            for r in rows
        ]
    finally:
        conn.close()


def create_remote_node(
    storage: Path, node_id: str, name: str, location: str, token: str, address: str = ""
) -> None:
    """Insert a new remote node. node_id must be unique slug. address is optional IP or hostname."""
    conn = _get_conn(storage)
    try:
        if _has_column(conn, "remote_nodes", "address"):
            conn.execute(
                """
                INSERT INTO remote_nodes (node_id, name, location, token, address)
                VALUES (?, ?, ?, ?, ?)
                """,
                (node_id.strip(), (name or "").strip() or node_id, (location or "").strip(), token, (address or "").strip()),
            )
        else:
            conn.execute(
                """
                INSERT INTO remote_nodes (node_id, name, location, token)
                VALUES (?, ?, ?, ?)
                """,
                (node_id.strip(), (name or "").strip() or node_id, (location or "").strip(), token),
            )
        conn.commit()
    finally:
        conn.close()


def get_remote_node_token(storage: Path, node_id: str) -> Optional[str]:
    """Return token for node_id (for script download only)."""
    conn = _get_conn(storage)
    try:
        row = conn.execute("SELECT token FROM remote_nodes WHERE node_id = ?", (node_id.strip(),)).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def get_remote_node(storage: Path, node_id: str) -> Optional[dict[str, Any]]:
    """Return one node by node_id (without token)."""
    conn = _get_conn(storage)
    try:
        if _has_column(conn, "remote_nodes", "address"):
            row = conn.execute(
                "SELECT node_id, name, location, COALESCE(address,''), created_at, last_seen_at FROM remote_nodes WHERE node_id = ?",
                (node_id.strip(),),
            ).fetchone()
            if not row:
                return None
            return {"node_id": row[0], "name": row[1], "location": row[2] or "", "address": row[3] or "", "created_at": row[4] or "", "last_seen_at": row[5] or ""}
        row = conn.execute(
            "SELECT node_id, name, location, created_at, last_seen_at FROM remote_nodes WHERE node_id = ?",
            (node_id.strip(),),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {"node_id": row[0], "name": row[1], "location": row[2] or "", "address": "", "created_at": row[3] or "", "last_seen_at": row[4] or ""}


def get_remote_node_by_token(storage: Path, token: str) -> Optional[dict[str, Any]]:
    """Return node (node_id, name, ...) for ingest API auth. Token must match."""
    conn = _get_conn(storage)
    try:
        row = conn.execute(
            "SELECT node_id, name, location FROM remote_nodes WHERE token = ?",
            (token.strip(),),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {"node_id": row[0], "name": row[1], "location": row[2] or ""}


def update_remote_node_last_seen(storage: Path, node_id: str) -> None:
    """Set last_seen_at to now for the node."""
    conn = _get_conn(storage)
    try:
        conn.execute(
            "UPDATE remote_nodes SET last_seen_at = datetime('now') WHERE node_id = ?",
            (node_id.strip(),),
        )
        conn.commit()
    finally:
        conn.close()


def update_remote_node(
    storage: Path,
    node_id: str,
    name: Optional[str] = None,
    location: Optional[str] = None,
    address: Optional[str] = None,
) -> None:
    """Update a remote node's name, location, and/or address. None means leave unchanged."""
    conn = _get_conn(storage)
    try:
        updates = []
        params: list[Any] = []
        if name is not None:
            updates.append("name = ?")
            params.append(name.strip())
        if location is not None:
            updates.append("location = ?")
            params.append(location.strip())
        if address is not None and _has_column(conn, "remote_nodes", "address"):
            updates.append("address = ?")
            params.append(address.strip())
        if not updates:
            return
        params.append(node_id.strip())
        conn.execute(
            "UPDATE remote_nodes SET " + ", ".join(updates) + " WHERE node_id = ?",
            tuple(params),
        )
        conn.commit()
    finally:
        conn.close()


def delete_remote_node(storage: Path, node_id: str) -> None:
    """Remove a remote node. Does not delete its result data (probe_id remains in results)."""
    conn = _get_conn(storage)
    try:
        conn.execute("DELETE FROM remote_nodes WHERE node_id = ?", (node_id.strip(),))
        conn.commit()
    finally:
        conn.close()


# --- Voice / SIP webhook idempotency (append-only) ---


def voice_webhook_try_insert(storage: Path, provider: str, idempotency_key: str, raw_payload: str) -> bool:
    """
    Insert one webhook event. Returns True if this is the first time for (provider, idempotency_key),
    False if duplicate (INSERT OR IGNORE had no effect).
    """
    init_db(storage)
    conn = _get_conn(storage)
    try:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO voice_webhook_events (provider, idempotency_key, raw_payload)
            VALUES (?, ?, ?)
            """,
            (provider.strip()[:64], idempotency_key[:512], raw_payload),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def voice_webhook_list_recent(storage: Path, limit: int = 50) -> list[dict[str, Any]]:
    """Recent voice webhook rows (newest first), for admin/debug."""
    init_db(storage)
    conn = _get_conn(storage)
    try:
        rows = conn.execute(
            """
            SELECT id, provider, idempotency_key, length(raw_payload), created_at
            FROM voice_webhook_events ORDER BY id DESC LIMIT ?
            """,
            (max(1, min(limit, 200)),),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "id": r[0],
            "provider": r[1] or "",
            "idempotency_key": r[2] or "",
            "payload_bytes": r[3],
            "created_at": r[4] or "",
        }
        for r in rows
    ]
