#!/bin/bash
# One-shot: create systemd unit and start netperf-web. Run on server as root.
# Usage: sudo bash bootstrap-web-on-server.sh
# (Or: copy/paste this into an SSH session, or run via: gcloud compute ssh INSTANCE --command='curl -s URL | sudo bash')
set -e
export DEBIAN_FRONTEND=noninteractive

WEB_DIR="/opt/netperf-web"
WEB_PORT="${PORT:-8080}"

if [ ! -f "$WEB_DIR/main.py" ]; then
  echo "Missing $WEB_DIR/main.py. Copy web app to /opt/netperf-web first."
  exit 1
fi

# Install venv if needed
if ! python3 -c "import ensurepip" 2>/dev/null; then
  apt-get update -qq
  [ -f /etc/os-release ] && grep -q "noble\|24.04" /etc/os-release && apt-get install -y python3.12-venv || apt-get install -y python3-venv
fi

rm -rf "$WEB_DIR/venv"
python3 -m venv "$WEB_DIR/venv"
"$WEB_DIR/venv/bin/pip" install -q -r "$WEB_DIR/requirements.txt"
chmod 755 "$WEB_DIR/main.py"

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
systemctl enable netperf-web.service
systemctl restart netperf-web.service
sleep 1
systemctl status netperf-web.service --no-pager
echo ""
echo "Web UI: http://$(hostname -I | awk '{print $1}'):$WEB_PORT"
