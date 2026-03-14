#!/usr/bin/env python3
"""Bandwidth Test Manager - Web API and UI."""
import json
import os
import re
import subprocess
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder="static", static_url_path="/static")

STORAGE = Path(os.environ.get("NETPERF_STORAGE", "/var/log/netperf"))
CONFIG_PATH = Path(os.environ.get("NETPERF_CONFIG", "/etc/netperf/config.json"))


def get_config():
    defaults = {
        "site_url": "",
        "ssl_cert_path": "",
        "ssl_key_path": "",
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


def save_config(data):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)


def parse_speedtest_file(path):
    results = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("type") != "result":
                    continue
                ts = obj.get("timestamp", "")
                download_bps = (obj.get("download", {}).get("bandwidth") or 0) * 8
                upload_bps = (obj.get("upload", {}).get("bandwidth") or 0) * 8
                latency_ms = obj.get("ping", {}).get("latency")
                server = obj.get("server", {})
                server_id = server.get("id", "ND")
                server_name = server.get("name", "ND")
                server_loc = server.get("location", "ND")
                results.append({
                    "timestamp": ts,
                    "download_bps": download_bps,
                    "upload_bps": upload_bps,
                    "latency_ms": latency_ms,
                    "server_id": server_id,
                    "server_name": server_name,
                    "server_location": server_loc,
                })
            except (json.JSONDecodeError, KeyError):
                continue
    return results


def site_label_from_speedtest_filename(name):
    # 0_speedtest-local -> Local
    m = re.match(r"^\d+_speedtest-(.+)$", name)
    if m:
        return m.group(1).replace("-", " ").title()
    return name


def parse_iperf_file(path):
    # iperf3 client output: [  5]   0.00-10.00  sec  1.10 GBytes   941 Mbits/sec    0             sender
    results = []
    bitrate_re = re.compile(
        r"\[\s*\d+\]\s+[\d.]+-[\d.]+\s+sec\s+[\d.]+\s+\w+\s+([\d.]+)\s+(G|M)?bits/sec"
    )
    with open(path, "r") as f:
        for line in f:
            m = bitrate_re.search(line)
            if m:
                val = float(m.group(1))
                unit = (m.group(2) or "M").upper()
                bps = val * 1e9 if unit == "G" else val * 1e6
                results.append({"bits_per_sec": bps})
    return results


def site_label_from_iperf_filename(name):
    # iperf-he-net-single.txt -> he-net single
    base = name.replace(".txt", "").replace("iperf-", "")
    return base.replace("-", " ").title()


@app.route("/")
@app.route("/netperf")
@app.route("/netperf/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/config", methods=["GET"])
def api_config_get():
    return jsonify(get_config())


@app.route("/api/config", methods=["PUT", "POST"])
def api_config_set():
    data = request.get_json(force=True, silent=True) or {}
    cur = get_config()
    if "speedtest_limit_mbps" in data:
        v = data["speedtest_limit_mbps"]
        cur["speedtest_limit_mbps"] = int(v) if v is not None and str(v).strip() != "" else None
    for key in ("site_url", "ssl_cert_path", "ssl_key_path"):
        if key in data:
            cur[key] = (data.get(key) or "").strip()
    cur["ookla_servers"] = data.get("ookla_servers", cur.get("ookla_servers", []))
    cur["iperf_servers"] = data.get("iperf_servers", cur.get("iperf_servers", []))
    cur["iperf_tests"] = data.get("iperf_tests", cur.get("iperf_tests", []))
    try:
        save_config(cur)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/dates")
def api_dates():
    try:
        if not STORAGE.exists():
            return jsonify({"dates": []})
        dates = sorted(
            [d.name for d in STORAGE.iterdir() if d.is_dir() and d.name.isdigit()],
            reverse=True,
        )
        return jsonify({"dates": dates})
    except Exception:
        return jsonify({"dates": []})


@app.route("/api/data")
def api_data():
    try:
        date = request.args.get("date")
        if not date or not date.isdigit():
            return jsonify({"error": "missing or invalid date"}), 400
        day_dir = STORAGE / date
        if not day_dir.exists() or not day_dir.is_dir():
            return jsonify({"speedtest": {}, "iperf": {}})

        speedtest = {}
        for f in sorted(day_dir.glob("[0-9]_speedtest-*")):
            label = site_label_from_speedtest_filename(f.name)
            speedtest[label] = parse_speedtest_file(f)

        iperf = {}
        for f in sorted(day_dir.glob("iperf-*.txt")):
            label = site_label_from_iperf_filename(f.name)
            iperf[label] = parse_iperf_file(f)

        return jsonify({"speedtest": speedtest, "iperf": iperf})
    except Exception:
        return jsonify({"speedtest": {}, "iperf": {}})


@app.route("/api/status")
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
    return jsonify({"scheduled": scheduled})


@app.route("/api/scheduler/start", methods=["POST"])
def api_scheduler_start():
    try:
        subprocess.run(
            ["/bin/netperf-scheduler", "start"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return jsonify({"ok": True})
    except subprocess.CalledProcessError as e:
        return jsonify({"ok": False, "error": (e.stderr or str(e))}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/scheduler/stop", methods=["POST"])
def api_scheduler_stop():
    try:
        subprocess.run(
            ["/bin/netperf-scheduler", "stop"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)
