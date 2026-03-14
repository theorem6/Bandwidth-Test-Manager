#!/bin/bash
# Run on the server after extracting the deploy tarball. Everything is done via install.sh.
# Usage: bash deploy-remote.sh
set -e
REMOTE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PORT=8080

# Stop netperf-web so 8080 is free if it was the only listener (avoids switching to 8081 and 502 behind nginx)
sudo systemctl stop netperf-web.service 2>/dev/null || true
sleep 1

if command -v ss &>/dev/null; then
  if ss -tlnp 2>/dev/null | grep -q ':8080\b'; then
    echo "Port 8080 in use. Using 8081 and updating Nginx."
    export PORT=8081
  fi
elif command -v netstat &>/dev/null; then
  if netstat -tlnp 2>/dev/null | grep -q ':8080 '; then
    echo "Port 8080 in use. Using 8081 and updating Nginx."
    export PORT=8081
  fi
fi

# install.sh: deps (Ookla, iperf3, jq, mtr), scripts to /bin, config dirs, web app to /opt/netperf-web, venv, systemd
cd "$REMOTE_DIR" && sudo DEBIAN_FRONTEND=noninteractive PORT="$PORT" bash install.sh
if [ -f "$REMOTE_DIR/finish-web-install.sh" ] && [ -f /opt/netperf-web/main.py ]; then
  sudo PORT="$PORT" bash "$REMOTE_DIR/finish-web-install.sh" || sudo PORT="$PORT" bash "$REMOTE_DIR/bootstrap-web-on-server.sh"
fi

# If we're on 8081, point Nginx at 8081 so /netperf/ doesn't 502
if [ "$PORT" = "8081" ] && command -v nginx &>/dev/null; then
  for f in /etc/nginx/sites-available/netperf-web /etc/nginx/sites-enabled/netperf-web /etc/nginx/snippets/netperf-path.conf /etc/nginx/snippets/netperf-proxy.conf; do
    [ -f "$f" ] && sudo sed -i "s/127.0.0.1:8080/127.0.0.1:8081/g" "$f"
  done
  sudo nginx -t 2>/dev/null && sudo systemctl reload nginx 2>/dev/null && echo "Nginx updated to proxy to port 8081."
fi

echo "Deploy done. Web UI on port $PORT"
