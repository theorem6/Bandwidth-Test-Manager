#!/bin/bash
# Install only Ookla Speedtest CLI, iperf3, jq, mtr, and netperf scripts. No web UI.
# Called by the web API (runs as root). Safe to run multiple times.
set -eu
export DEBIAN_FRONTEND=noninteractive
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Scripts may be in SCRIPT_DIR/scripts (when deployed with scripts next to web) or in /bin already
SCRIPTS_SRC="$SCRIPT_DIR/scripts"
[ ! -d "$SCRIPTS_SRC" ] && SCRIPTS_SRC=""
PARENT="$(dirname "$SCRIPT_DIR")"

echo "=== Adding Ookla repository ==="
curl -s https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | bash
if [ -f /etc/apt/sources.list.d/ookla_speedtest-cli.list ] && grep -q 'noble' /etc/apt/sources.list.d/ookla_speedtest-cli.list 2>/dev/null; then
	sed -i 's/noble/jammy/g' /etc/apt/sources.list.d/ookla_speedtest-cli.list
fi
echo "=== Installing packages ==="
apt-get update -qq
apt-get install -y speedtest iperf3 mtr jq
apt-get install -y trickle 2>/dev/null || true
echo "=== Accepting Ookla license ==="
speedtest --accept-license --accept-gdpr 2>/dev/null || true
# If package speedtest crashes with -f json, install official binary from https://www.speedtest.net/apps/cli
if command -v speedtest &>/dev/null; then
	if ! (timeout 15 speedtest -L -f json &>/dev/null); then
		echo "=== Installing official Speedtest CLI binary (package build may be broken) ==="
		ARCH=$(uname -m)
		case "$ARCH" in
			x86_64)   TARG="linux-x86_64" ;;
			aarch64|arm64) TARG="linux-aarch64" ;;
			armv7l|armhf)  TARG="linux-armhf" ;;
			armv6l)   TARG="linux-armel" ;;
			i386|i686) TARG="linux-i386" ;;
			*) TARG="" ;;
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
			fi
			rm -rf "$TMP"
		fi
	fi
fi
echo "=== Installing netperf scripts to /bin ==="
if [ -n "$SCRIPTS_SRC" ]; then
	for f in netperf-scheduler netperf-tester netperf-reporter netperf-cron-run; do
		[ -f "$SCRIPTS_SRC/$f" ] && cp -f "$SCRIPTS_SRC/$f" /bin/ && chmod 755 "/bin/$f"
	done
fi
echo "=== Creating config and log dirs ==="
mkdir -p /etc/netperf /var/log/netperf
if [ ! -f /etc/netperf/config.json ]; then
	if [ -f "$PARENT/etc/netperf-config.json" ]; then
		cp -f "$PARENT/etc/netperf-config.json" /etc/netperf/config.json
	else
		echo '{"site_url":"","ssl_cert_path":"","ssl_key_path":"","speedtest_limit_mbps":null,"ookla_servers":[{"id":"auto","label":"Local"}],"iperf_servers":[],"iperf_tests":[{"name":"single","args":"-P 1"}]}' > /etc/netperf/config.json
	fi
fi
echo "Done."
