#!/bin/bash
# Bandwidth Test Manager — full install (CLI + optional web UI)
# Supports: Debian/Ubuntu, Fedora/RHEL/Rocky/Alma/Amazon Linux, openSUSE/SLES, Alpine, Arch.
# With web UI: installs Node.js 18+, runs npm ci && npm run build in web/frontend (Vite → web/static/).
# Run: sudo ./install.sh [--no-web]
# Env: BWM_SOURCE=archive|git (default archive), BWM_REPO, BWM_REF, BWM_DEBUG=1,
#      SKIP_NPM_BUILD=1 (use committed web/static only; no npm)

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

# Used when BWM_SOURCE=git and the tree must be fetched; runs before scripts/linux-deps.sh exists.
bwm_ensure_git() {
	command -v git &>/dev/null && return 0
	export DEBIAN_FRONTEND=noninteractive
	if command -v apt-get &>/dev/null; then
		apt-get update -qq && apt-get install -y -qq git ca-certificates
	elif command -v dnf &>/dev/null; then
		dnf install -y git ca-certificates
	elif command -v microdnf &>/dev/null; then
		microdnf install -y git ca-certificates
	elif command -v yum &>/dev/null; then
		yum install -y git ca-certificates
	elif command -v zypper &>/dev/null; then
		zypper --non-interactive install -y git ca-certificates
	elif command -v apk &>/dev/null; then
		apk add --no-cache git ca-certificates
	elif command -v pacman &>/dev/null; then
		pacman -Sy --needed --noconfirm git ca-certificates
	else
		echo "No supported package manager to install git. Install git manually or set BWM_SOURCE=archive." >&2
		return 1
	fi
	command -v git &>/dev/null
}

# Clone BWM_REPO, checkout BWM_REF (branch, tag, or commit). Uses shallow clone when possible.
bwm_fetch_source_git() {
	local clone_dir="$1"
	local repo="$2" ref="$3"
	if git clone --depth 1 --branch "$ref" "$repo" "$clone_dir" 2>/dev/null; then
		return 0
	fi
	echo "=== Shallow clone not possible for ref \"$ref\"; full clone + checkout ===" >&2
	git clone "$repo" "$clone_dir" || return 1
	( cd "$clone_dir" && git checkout "$ref" ) || return 1
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
	BWM_TMPDIR="$(mktemp -d)"
	BWM_SRC="${BWM_SOURCE:-archive}"
	case "$BWM_SRC" in
		git)
			echo "=== Cloning install source (BWM_SOURCE=git) ==="
			if ! bwm_ensure_git; then
				exit 1
			fi
			CLONE_ROOT="$BWM_TMPDIR/src"
			if ! bwm_fetch_source_git "$CLONE_ROOT" "$BWM_REPO" "$BWM_REF"; then
				echo "git clone failed." >&2
				[ -n "${BWM_DEBUG:-}" ] && echo "  BWM_REPO=$BWM_REPO BWM_REF=$BWM_REF" >&2
				exit 1
			fi
			SCRIPT_DIR="$CLONE_ROOT"
			cd "$SCRIPT_DIR"
			if ! bwm_tree_complete; then
				echo "Clone missing expected files." >&2
				[ -n "${BWM_DEBUG:-}" ] && echo "  BWM_REPO=$BWM_REPO BWM_REF=$BWM_REF" >&2
				exit 1
			fi
			echo "=== Install source ready ==="
			;;
		archive|*)
			if [ "$BWM_SRC" != "archive" ]; then
				echo "Unknown BWM_SOURCE=\"$BWM_SRC\" (use archive or git). Using archive." >&2
			fi
			echo "=== Downloading install source (BWM_SOURCE=archive) ==="
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
			;;
	esac
fi

# shellcheck disable=SC1091
. "$SCRIPT_DIR/scripts/linux-deps.sh"

echo "=== Installing OS packages (Ookla, iperf3, jq, mtr, …) ==="
bwm_install_all_cli_dependencies

echo "=== Installing scripts to /bin ==="
cp -f scripts/netperf-scheduler scripts/netperf-tester scripts/netperf-reporter scripts/netperf-cron-run scripts/netperf-resolve-ookla-local /bin/
chmod 755 /bin/netperf-scheduler /bin/netperf-tester /bin/netperf-reporter /bin/netperf-cron-run /bin/netperf-resolve-ookla-local
grep -q -- '--accept-license' /bin/netperf-tester 2>/dev/null || echo "WARNING: /bin/netperf-tester may be stale (missing Ookla --accept-license). Re-copy scripts/netperf-tester from this repo." >&2

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
	if [ "${SKIP_NPM_BUILD:-}" = "1" ] && [ -f "$SCRIPT_DIR/web/static/index.html" ]; then
		echo "SKIP_NPM_BUILD=1 — using existing web/static (no npm run build)."
	else
		echo "=== Node.js + npm (for Vite build) ==="
		bwm_install_nodejs_npm || {
			echo "Node.js 18+ required. Install nodejs + npm, then re-run." >&2
			exit 1
		}
		echo "=== npm ci && npm run build → web/static/ ==="
		bwm_build_web_frontend "$SCRIPT_DIR" || {
			echo "Frontend build failed. Fix errors above, or set SKIP_NPM_BUILD=1 if web/static is pre-built." >&2
			exit 1
		}
	fi
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
	# Always use the venv interpreter (PEP 668: never install into system Python on Debian/Ubuntu).
	_VPY="$WEB_DIR/venv/bin/python3"
	"$_VPY" -m pip install -q --upgrade pip setuptools wheel 2>/dev/null || true
	if [ -f "$WEB_DIR/requirements.txt" ]; then
		"$_VPY" -m pip install -q -r "$WEB_DIR/requirements.txt"
	else
		"$_VPY" -m pip install -q "fastapi>=0.109" "uvicorn[standard]>=0.27" "certifi>=2024.2.2" "python-multipart>=0.0.9"
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
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
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
		echo ""
		echo "If netperf-web.service uses User= (not root), configure passwordless sudo for /bin/netperf-cron-run and /bin/netperf-tester so Dashboard → Run test now works."
	else
		echo "systemd not detected. Start manually:"
		echo "  cd $WEB_DIR && NETPERF_STORAGE=/var/log/netperf NETPERF_CONFIG=/etc/netperf/config.json PORT=$WEB_PORT ./venv/bin/uvicorn main:app --host 0.0.0.0 --port $WEB_PORT"
	fi
	echo ""
	echo "Web UI Python packages live only in $WEB_DIR/venv (PEP 668 — do not use bare pip). To upgrade deps later:"
	echo "  sudo $WEB_DIR/venv/bin/python3 -m pip install -r $WEB_DIR/requirements.txt"
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
