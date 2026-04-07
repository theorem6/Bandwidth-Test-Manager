#!/bin/bash
# Run on the server if the web UI was not fully installed (e.g. python3.12-venv was missing).
# Usage: sudo bash finish-web-install.sh [WEB_DIR]

set -e
export DEBIAN_FRONTEND=noninteractive

WEB_DIR="${1:-/opt/netperf-web}"
WEB_PORT="${PORT:-8080}"

if [ ! -d "$WEB_DIR" ] || [ ! -f "$WEB_DIR/main.py" ]; then
	echo "ERROR: Web app not found at $WEB_DIR (run full install.sh first)."
	exit 1
fi

# Ensure venv package for current Python
if ! python3 -c "import ensurepip" 2>/dev/null; then
	if [ -f /etc/os-release ] && grep -q "noble\|24.04" /etc/os-release 2>/dev/null; then
		apt-get install -y python3.12-venv
	else
		apt-get install -y python3-venv
	fi
fi

rm -rf "$WEB_DIR/venv"
python3 -m venv "$WEB_DIR/venv"
_VPY="$WEB_DIR/venv/bin/python3"
"$_VPY" -m pip install -q --upgrade pip setuptools wheel 2>/dev/null || true
if [ -f "$WEB_DIR/requirements.txt" ]; then
	"$_VPY" -m pip install -q -r "$WEB_DIR/requirements.txt"
else
	"$_VPY" -m pip install -q "fastapi>=0.109" "uvicorn[standard]>=0.27" "certifi>=2024.2.2" "python-multipart>=0.0.9"
fi
chmod 755 "$WEB_DIR/main.py"

# Create or update systemd service (FastAPI + Uvicorn)
cat > /etc/systemd/system/netperf-web.service << EOF
[Unit]
Description=Netperf Web UI
After=network.target

[Service]
Type=simple
WorkingDirectory=$WEB_DIR
ExecStart=$WEB_DIR/venv/bin/uvicorn main:app --host 0.0.0.0 --port $WEB_PORT
Restart=on-failure
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=NETPERF_STORAGE=/var/log/netperf
Environment=NETPERF_CONFIG=/etc/netperf/config.json
Environment=PORT=$WEB_PORT

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable netperf-web.service 2>/dev/null || true
systemctl restart netperf-web.service
systemctl status netperf-web.service --no-pager

echo ""
echo "Web UI: http://$(hostname -I | awk '{print $1}'):$WEB_PORT"
