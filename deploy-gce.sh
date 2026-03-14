#!/bin/bash
# Deploy Bandwidth Test Manager to an existing GCE instance.
# Run locally (where gcloud is installed). Copies project and runs install.sh on the server.
# Usage: ./deploy-gce.sh INSTANCE_NAME [ZONE] [PROJECT]
# Example: ./deploy-gce.sh my-server us-central1-a my-project

set -e

INSTANCE="${1:?Usage: $0 INSTANCE_NAME [ZONE] [PROJECT]}"
ZONE="${2:-}"
PROJECT="${3:-}"

# Optional gcloud args
GCLOUD_EXTRA=()
[[ -n "$ZONE" ]]    && GCLOUD_EXTRA+=(--zone "$ZONE")
[[ -n "$PROJECT" ]] && GCLOUD_EXTRA+=(--project "$PROJECT")

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOTE_DIR="/tmp/bandwidth-test-manager-$$"

echo "=== Deploying to GCE instance: $INSTANCE ==="
if ! gcloud compute instances describe "$INSTANCE" "${GCLOUD_EXTRA[@]}" &>/dev/null; then
  echo "Instance '$INSTANCE' not found or gcloud not configured. Check name, zone, and project."
  exit 1
fi

echo "=== Building frontend (Svelte) ==="
(cd "$SCRIPT_DIR/web/frontend" && npm run build 2>/dev/null) || echo "Skip frontend build (run: cd web/frontend && npm run build)"

echo "=== Copying project to instance ==="
tar czf - -C "$SCRIPT_DIR" scripts etc web install.sh finish-web-install.sh bootstrap-web-on-server.sh | \
  gcloud compute ssh "$INSTANCE" "${GCLOUD_EXTRA[@]}" -- "mkdir -p $REMOTE_DIR && tar xzf - -C $REMOTE_DIR"

echo "=== Checking for conflicts on server ==="
# Run conflict check and install on the server
gcloud compute ssh "$INSTANCE" "${GCLOUD_EXTRA[@]}" -- bash -s -- "$REMOTE_DIR" << 'REMOTE'
set -e
REMOTE_DIR="$1"
export PORT=8080

# Port 8080 in use?
if command -v ss &>/dev/null; then
  if ss -tlnp 2>/dev/null | grep -q ':8080\b'; then
    echo "Port 8080 is already in use. Using 8081 for Netperf Web UI."
    export PORT=8081
  fi
elif command -v netstat &>/dev/null; then
  if netstat -tlnp 2>/dev/null | grep -q ':8080 '; then
    echo "Port 8080 is already in use. Using 8081 for Netperf Web UI."
    export PORT=8081
  fi
fi

# Copy web app to /opt if present (so finish-web can use it)
sudo mkdir -p /opt/netperf-web
sudo cp -r "$REMOTE_DIR/web/"* /opt/netperf-web/ 2>/dev/null || true

# Require root for install (installs deps, scripts, config; may install web)
if [ "$(id -u)" -ne 0 ]; then
  echo "Running install with sudo..."
  cd "$REMOTE_DIR" && sudo DEBIAN_FRONTEND=noninteractive PORT="$PORT" bash install.sh
else
  cd "$REMOTE_DIR" && DEBIAN_FRONTEND=noninteractive PORT="$PORT" bash install.sh
fi

# Ensure web UI is up (idempotent: creates venv + systemd unit if missing)
if [ -f "$REMOTE_DIR/finish-web-install.sh" ] && [ -f /opt/netperf-web/main.py ]; then
  sudo PORT="$PORT" bash "$REMOTE_DIR/finish-web-install.sh" || sudo PORT="$PORT" bash "$REMOTE_DIR/bootstrap-web-on-server.sh"
fi

echo "Cleaning up $REMOTE_DIR..."
rm -rf "$REMOTE_DIR"
REMOTE

echo ""
echo "=== Deploy complete ==="
echo "On the server: sudo netperf-scheduler start   # optional: schedule hourly tests"
echo "Web UI: open the Site URL (no port), e.g. https://<host>/netperf/"
echo "        Set Site URL and cert paths in Settings; run: sudo ./web/setup-https.sh"
echo "To get external IP: gcloud compute instances describe $INSTANCE ${GCLOUD_EXTRA[*]} --format='get(networkInterfaces[0].accessConfigs[0].natIP)'"
exit 0
