#!/bin/bash
# Bandwidth Test Manager — full install (CLI + optional web UI)
# Supports: Debian/Ubuntu, Fedora/RHEL/Rocky/Alma/Amazon Linux, openSUSE/SLES, Alpine, Arch.
# Run: sudo ./install.sh [--no-web]
# Remote fetch: BWM_REPO, BWM_REF. Debug: BWM_DEBUG=1

set -eu
export DEBIAN_FRONTEND=noninteractive

INSTALL_WEB=true
[[ "${1:-}" == "--no-web" ]] && INSTALL_WEB=false

if [ "$(id -u)" -ne 0 ]; then
	echo "Run as root: sudo $0"
	exit 1
fi

BWM_REPO="${BWM_REPO:-https://github.com/theorem6/Bandwidth-Test-Manager}"
BWM_REF="${BWM_REF:-main}"

BWM_TMPDIR=""
cleanup_bwm_tmp() {
	[ -n "${BWM_TMPDIR:-}" ] && [ -d "$BWM_TMPDIR" ] && rm -rf "$BWM_TMPDIR"
}
trap cleanup_bwm_tmp EXIT

_resolve_script_root() {
	local s="${BASH_SOURCE[0]-}"
	if [ -n "$s" ] && [ "$s" != "-" ] && [ -e "$s" ]; then
		cd "$(dirname "$s")" && pwd
		return
	fi
	pwd
}

bwm_download() {
	local url="$1" out="$2"
	if command -v curl &>/dev/null; then
		curl -fsSL "$url" -o "$out" || return 1
	elif command -v wget &>/dev/null; then
		wget -q -O "$out" "$url" || return 1
	elif command -v apt-get &>/dev/null; then
		DEBIAN_FRONTEND=noninteractive apt-get update -qq || return 1
		DEBIAN_FRONTEND=noninteractive apt-get install -y -qq curl || return 1
		curl -fsSL "$url" -o "$out" || return 1
	else
		echo "Need curl or wget to fetch sources (or use a full local tree)." >&2
		return 1
	fi
}

bwm_tree_complete() {
	local f
	for f in scripts/netperf-scheduler scripts/netperf-tester scripts/netperf-reporter scripts/netperf-cron-run scripts/netperf-resolve-ookla-local scripts/linux-deps.sh; do
		[ ! -f "$f" ] && return 1
	done
	[ ! -f etc/netperf-config.json ] && return 1
	if [ "$INSTALL_WEB" = true ] && [ ! -f web/main.py ]; then
		return 1
	fi
	return 0
}

SCRIPT_DIR="$(_resolve_script_root)"
cd "$SCRIPT_DIR"

if ! bwm_tree_complete; then
	echo "=== Downloading install source ==="
	BWM_TMPDIR="$(mktemp -d)"
	TGZ="$BWM_TMPDIR/src.tar.gz"
	ARCHIVE_URL="${BWM_REPO}/archive/refs/heads/${BWM_REF}.tar.gz"
	if ! bwm_download "$ARCHIVE_URL" "$TGZ"; then
		echo "Download failed." >&2
		[ -n "${BWM_DEBUG:-}" ] && echo "  URL: $ARCHIVE_URL" >&2
		exit 1
	fi
	tar -xzf "$TGZ" -C "$BWM_TMPDIR"
	FOUND="$(find "$BWM_TMPDIR" -mindepth 1 -maxdepth 1 -type d | head -1)"
	if [ -z "$FOUND" ] || [ ! -d "$FOUND" ]; then
		echo "Could not unpack install source." >&2
		[ -n "${BWM_DEBUG:-}" ] && echo "  Check BWM_REPO / BWM_REF. Temp: $BWM_TMPDIR" >&2
		exit 1
	fi
	SCRIPT_DIR="$FOUND"
	cd "$SCRIPT_DIR"
	if ! bwm_tree_complete; then
		echo "Archive missing expected files." >&2
		[ -n "${BWM_DEBUG:-}" ] && echo "  URL: $ARCHIVE_URL" >&2
		exit 1
	fi
	echo "=== Install source ready ==="
fi

# shellcheck disable=SC1091
. "$SCRIPT_DIR/scripts/linux-deps.sh"

echo "=== Installing OS packages (Ookla, iperf3, jq, mtr, …) ==="
bwm_install_all_cli_dependencies

echo "=== Accepting Ookla license ==="
speedtest --accept-license --accept-gdpr || true

echo "=== Installing scripts to /bin ==="
cp -f scripts/netperf-scheduler scripts/netperf-tester scripts/netperf-reporter scripts/netperf-cron-run scripts/netperf-resolve-ookla-local /bin/
chmod 755 /bin/netperf-scheduler /bin/netperf-tester /bin/netperf-reporter /bin/netperf-cron-run /bin/netperf-resolve-ookla-local

echo "=== Config and log directories ==="
mkdir -p /etc/netperf /var/log/netperf
if [ ! -f /etc/netperf/config.json ]; then
	cp -f etc/netperf-config.json /etc/netperf/config.json
	echo "Created /etc/netperf/config.json"
else
	echo "Keeping existing /etc/netperf/config.json"
fi

if [ "$INSTALL_WEB" = true ]; then
	echo "=== Installing web interface ==="
	bwm_install_python_web_packages || {
		echo "Python packages failed; install python3 and pip, then re-run." >&2
		exit 1
	}
	WEB_DIR="/opt/netperf-web"
	mkdir -p "$WEB_DIR" "$WEB_DIR/scripts"
	cp -r web/* "$WEB_DIR"
	cp -f scripts/netperf-scheduler scripts/netperf-tester scripts/netperf-reporter scripts/netperf-cron-run scripts/netperf-resolve-ookla-local scripts/linux-deps.sh "$WEB_DIR/scripts/" 2>/dev/null || true
	rm -rf "$WEB_DIR/venv"
	python3 -m venv "$WEB_DIR/venv"
	if [ -f "$WEB_DIR/requirements.txt" ]; then
		"$WEB_DIR/venv/bin/pip" install -q -r "$WEB_DIR/requirements.txt"
	else
		"$WEB_DIR/venv/bin/pip" install -q "fastapi>=0.109" "uvicorn[standard]>=0.27"
	fi
	chmod 755 "$WEB_DIR/main.py"
	WEB_PORT="${PORT:-8080}"
	cat > /etc/systemd/system/netperf-web.service << EOF
[Unit]
Description=Netperf Web UI
After=network.target

[Service]
Type=simple
WorkingDirectory=$WEB_DIR
ExecStart=$WEB_DIR/venv/bin/uvicorn main:app --host 0.0.0.0 --port $WEB_PORT
Restart=on-failure
Environment=NETPERF_STORAGE=/var/log/netperf
Environment=NETPERF_CONFIG=/etc/netperf/config.json
Environment=PORT=$WEB_PORT

[Install]
WantedBy=multi-user.target
EOF
	if bwm_systemd_available; then
		systemctl daemon-reload
		systemctl enable netperf-web.service 2>/dev/null || true
		systemctl start netperf-web.service 2>/dev/null || true
		echo "Web UI at $WEB_DIR, http://0.0.0.0:$WEB_PORT"
		echo "  systemctl start|stop|status netperf-web"
	else
		echo "systemd not detected. Start manually:"
		echo "  cd $WEB_DIR && NETPERF_STORAGE=/var/log/netperf NETPERF_CONFIG=/etc/netperf/config.json PORT=$WEB_PORT ./venv/bin/uvicorn main:app --host 0.0.0.0 --port $WEB_PORT"
	fi
else
	echo "Skipping web install (--no-web)"
fi

echo ""
echo "Done."
echo "  sudo netperf-scheduler start"
echo "  Edit /etc/netperf/config.json"
if [ "$INSTALL_WEB" = true ]; then
	echo "  Web: http://<this-host>:${PORT:-8080}/"
fi
