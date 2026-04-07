#!/bin/bash
# Install Ookla Speedtest CLI, iperf3, jq, mtr, netperf scripts. No web UI.
# Supports major Linux distros (see scripts/linux-deps.sh). Requires root.
set -eu
export DEBIAN_FRONTEND=noninteractive
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_SRC="$SCRIPT_DIR/scripts"
[ ! -d "$SCRIPTS_SRC" ] && SCRIPTS_SRC=""
PARENT="$(dirname "$SCRIPT_DIR")"

LINUX_DEPS="$SCRIPT_DIR/scripts/linux-deps.sh"
if [ ! -f "$LINUX_DEPS" ]; then
	echo "Missing $LINUX_DEPS — redeploy web app from a full install (includes scripts/linux-deps.sh)." >&2
	exit 1
fi
# shellcheck disable=SC1091
. "$LINUX_DEPS"

echo "=== Installing OS packages ==="
bwm_install_all_cli_dependencies

echo "=== Accepting Ookla license ==="
speedtest --accept-license --accept-gdpr 2>/dev/null || true

echo "=== Installing netperf scripts to /bin ==="
if [ -n "$SCRIPTS_SRC" ]; then
	for f in netperf-scheduler netperf-tester netperf-reporter netperf-cron-run netperf-resolve-ookla-local; do
		[ -f "$SCRIPTS_SRC/$f" ] && cp -f "$SCRIPTS_SRC/$f" /bin/ && chmod 755 "/bin/$f"
	done
fi

echo "=== Creating config and log dirs ==="
mkdir -p /etc/netperf /var/log/netperf
if [ ! -f /etc/netperf/config.json ]; then
	if [ -f "$PARENT/etc/netperf-config.json" ]; then
		cp -f "$PARENT/etc/netperf-config.json" /etc/netperf/config.json
	else
		echo '{"site_url":"","ssl_cert_path":"","ssl_key_path":"","speedtest_limit_mbps":null,"ookla_local_patterns":[],"ookla_local_auto_isp":true,"ookla_servers":[{"id":"local","label":"ISP / nearest (auto)"},{"id":"auto","label":"Public reference"}],"iperf_servers":[],"iperf_tests":[{"name":"single","args":"-P 1"}]}' > /etc/netperf/config.json
	fi
fi
echo "Done."
