#!/bin/bash
# Bandwidth Test Manager - Linux install script (includes Web UI)
# Run as root: sudo ./install.sh [--no-web]

set -eu
export DEBIAN_FRONTEND=noninteractive

INSTALL_WEB=true
[[ "${1:-}" == "--no-web" ]] && INSTALL_WEB=false

if [ "$(id -u)" -ne 0 ]; then
	echo "Run as root: sudo $0"
	exit 1
fi

# Project root (directory containing install.sh)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Installing dependencies ==="
if command -v apt-get &>/dev/null; then
	curl -s https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | bash
	# Ubuntu 24.04 (noble): Ookla repo may not have Release file; use jammy
	if [ -f /etc/apt/sources.list.d/ookla_speedtest-cli.list ] && grep -q 'noble' /etc/apt/sources.list.d/ookla_speedtest-cli.list 2>/dev/null; then
		sed -i 's/noble/jammy/g' /etc/apt/sources.list.d/ookla_speedtest-cli.list
	fi
	apt-get update -qq
	apt-get install -y speedtest iperf3 mtr jq
	apt-get install -y trickle 2>/dev/null || true

	# If package speedtest crashes with -f json (e.g. "basic_string::_M_construct null" on some builds),
	# install the official binary from https://www.speedtest.net/apps/cli so server list and tests work.
	if command -v speedtest &>/dev/null; then
		if ! (timeout 15 speedtest -L -f json &>/dev/null); then
			echo "=== Installing official Speedtest CLI binary (package build may be broken on this system) ==="
			ARCH=$(uname -m)
			case "$ARCH" in
				x86_64)   TARG="linux-x86_64" ;;
				aarch64|arm64) TARG="linux-aarch64" ;;
				armv7l|armhf)  TARG="linux-armhf" ;;
				armv6l)   TARG="linux-armel" ;;
				i386|i686) TARG="linux-i386" ;;
				*) echo "Unsupported arch $ARCH for fallback binary; keeping package." ; TARG="" ;;
			esac
			if [ -n "$TARG" ]; then
				VER="1.2.0"
				URL="https://install.speedtest.net/app/cli/ookla-speedtest-${VER}-${TARG}.tgz"
				TMP=$(mktemp -d)
				if curl -sSfL "$URL" -o "$TMP/speedtest.tgz" && tar -xzf "$TMP/speedtest.tgz" -C "$TMP" && [ -f "$TMP/speedtest" ]; then
					mkdir -p /usr/local/bin
					mv -f "$TMP/speedtest" /usr/local/bin/speedtest
					chmod 755 /usr/local/bin/speedtest
					echo "Installed official Speedtest CLI to /usr/local/bin/speedtest"
				else
					echo "Fallback download failed; keeping package. Server list may use text fallback in web UI."
				fi
				rm -rf "$TMP"
			fi
		fi
	fi
	else
		echo "Unsupported: only Debian/Ubuntu (apt) is supported."
		exit 1
	fi

echo "=== Accepting Ookla license ==="
speedtest --accept-license --accept-gdpr || true

echo "=== Installing scripts to /bin ==="
cp -f scripts/netperf-scheduler scripts/netperf-tester scripts/netperf-reporter scripts/netperf-cron-run /bin/
chmod 755 /bin/netperf-scheduler /bin/netperf-tester /bin/netperf-reporter /bin/netperf-cron-run

echo "=== Config and log directories ==="
mkdir -p /etc/netperf /var/log/netperf
# Web app stores results in SQLite at $NETPERF_STORAGE/netperf.db; tester scripts still write logs under $NETPERF_STORAGE/YYYYMMDD/
if [ ! -f /etc/netperf/config.json ]; then
	cp -f etc/netperf-config.json /etc/netperf/config.json
	echo "Created /etc/netperf/config.json (edit to change Ookla/iperf sites)"
else
	echo "Keeping existing /etc/netperf/config.json"
fi

if [ "$INSTALL_WEB" = true ]; then
	echo "=== Installing web interface ==="
	apt-get install -y python3 python3-pip 2>/dev/null || true
	# Ubuntu 24 (noble) needs python3.12-venv for ensurepip; others use python3-venv
	if python3 -c "import ensurepip" 2>/dev/null; then
		true
	elif [ -f /etc/os-release ] && grep -q "noble\|24.04" /etc/os-release 2>/dev/null; then
		apt-get install -y python3.12-venv
	else
		apt-get install -y python3-venv
	fi
	WEB_DIR="/opt/netperf-web"
	mkdir -p "$WEB_DIR" "$WEB_DIR/scripts"
	# Copy full web app (main.py, db.py, static/, requirements.txt, etc.)
	cp -r web/* "$WEB_DIR"
	cp -f scripts/netperf-scheduler scripts/netperf-tester scripts/netperf-reporter scripts/netperf-cron-run "$WEB_DIR/scripts/" 2>/dev/null || true
	rm -rf "$WEB_DIR/venv"
	python3 -m venv "$WEB_DIR/venv"
	if [ -f "$WEB_DIR/requirements.txt" ]; then
		"$WEB_DIR/venv/bin/pip" install -q -r "$WEB_DIR/requirements.txt"
	else
		"$WEB_DIR/venv/bin/pip" install -q "fastapi>=0.109" "uvicorn[standard]>=0.27"
	fi
	chmod 755 "$WEB_DIR/main.py"
	# Port: use PORT env if set (e.g. when 8080 is in use on GCE)
	WEB_PORT="${PORT:-8080}"
	# systemd service (FastAPI + Uvicorn)
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
	systemctl daemon-reload
	systemctl enable netperf-web.service 2>/dev/null || true
	systemctl start netperf-web.service 2>/dev/null || true
	echo "Web UI installed at $WEB_DIR, listening on http://0.0.0.0:$WEB_PORT"
	echo "  systemctl start|stop|status netperf-web"
else
	echo "Skipping web install (use --no-web to skip when re-running)"
fi

echo ""
echo "Done. Next steps:"
echo "  sudo netperf-scheduler start   # schedule hourly tests"
echo "  sudo netperf-scheduler stop    # stop schedule"
echo "  Edit /etc/netperf/config.json  to choose Ookla and iperf sites"
if [ "$INSTALL_WEB" = true ]; then
	echo "  Open http://<this-host>:${WEB_PORT:-8080}  for the web interface"
fi
