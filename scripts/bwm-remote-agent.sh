#!/bin/bash
# Bandwidth Test Manager - Remote node agent (CLI / standalone)
# Copy this script to a remote machine and run with BWM_MAIN_URL and BWM_NODE_TOKEN set.
# Requires: curl, speedtest (Ookla CLI), optional iperf3.
# Install: apt install curl; see https://www.speedtest.net/apps/cli for Ookla.
#
# Usage:
#   export BWM_MAIN_URL="https://your-main-server.example.com"
#   export BWM_NODE_TOKEN="your-node-token-from-web-ui"
#   ./bwm-remote-agent.sh
#
# Run every hour (recommended): add to crontab -e:
#   5 * * * * BWM_MAIN_URL="https://..." BWM_NODE_TOKEN="..." /path/to/bwm-remote-agent.sh
#
# Optional: set IPERF_HOST to run one iperf3 test (e.g. export IPERF_HOST=iperf.he.net)

set -e

MAIN_URL="${BWM_MAIN_URL:-}"
NODE_TOKEN="${BWM_NODE_TOKEN:-}"

if [ -z "$MAIN_URL" ] || [ -z "$NODE_TOKEN" ]; then
  echo "Usage: set BWM_MAIN_URL and BWM_NODE_TOKEN (from Remote nodes in the web UI)." >&2
  echo "  export BWM_MAIN_URL=\"https://your-server.example.com\"" >&2
  echo "  export BWM_NODE_TOKEN=\"<token>\"" >&2
  echo "  $0" >&2
  exit 1
fi

LOG_DATE=$(date -u +%Y%m%d)
IPERF_HOST="${IPERF_HOST:-}"

payload_speedtest() {
  local out
  out=$(speedtest -f json 2>/dev/null) || return 0
  local down_b=$(echo "$out" | grep -o '"download":{[^}]*"bandwidth":[0-9]*' | grep -o '[0-9]*$' | head -1)
  local up_b=$(echo "$out" | grep -o '"upload":{[^}]*"bandwidth":[0-9]*' | grep -o '[0-9]*$' | head -1)
  local lat=$(echo "$out" | grep -o '"latency":[0-9.]*' | head -1 | grep -o '[0-9.]*$')
  local ts=$(echo "$out" | grep -o '"timestamp":"[^"]*"' | head -1 | sed 's/"timestamp":"//;s/"$//')
  [ -z "$down_b" ] && down_b=0
  [ -z "$up_b" ] && up_b=0
  local down=$((down_b * 8))
  local up=$((up_b * 8))
  [ -z "$lat" ] && lat=0
  [ -z "$ts" ] && ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  echo "{\"site\":\"Remote\",\"timestamp\":\"$ts\",\"download_bps\":$down,\"upload_bps\":$up,\"latency_ms\":$lat}"
}

payload_iperf() {
  local host="$1"
  [ -z "$host" ] && return 0
  local out
  out=$(iperf3 -c "$host" -t 10 -f m -J 2>/dev/null) || return 0
  local bps=$(echo "$out" | grep -o '"bits_per_second":[0-9.]*' | head -1 | grep -o '[0-9.]*$')
  [ -z "$bps" ] && return 0
  local ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  echo "{\"site\":\"$host\",\"timestamp\":\"$ts\",\"bits_per_sec\":$bps}"
}

SPEEDTEST_JSON=$(payload_speedtest)
IPERF_JSON=""
[ -n "$IPERF_HOST" ] && IPERF_JSON=$(payload_iperf "$IPERF_HOST") || true

if [ -n "$IPERF_JSON" ]; then
  BODY=$(printf '{"log_date":"%s","speedtest":[%s],"iperf":[%s]}' "$LOG_DATE" "$SPEEDTEST_JSON" "$IPERF_JSON")
else
  BODY=$(printf '{"log_date":"%s","speedtest":[%s],"iperf":[]}' "$LOG_DATE" "$SPEEDTEST_JSON")
fi

curl -s -X POST "${MAIN_URL}/api/remote/ingest" \
  -H "Content-Type: application/json" \
  -H "X-Node-Token: $NODE_TOKEN" \
  -d "$BODY" \
  --max-time 60
echo ""
