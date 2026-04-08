#!/bin/bash
# Shared dependency installation for Debian/Ubuntu, Fedora/RHEL/Rocky/Alma/Amazon,
# openSUSE/SLES, Alpine, and Arch. Sourced by install.sh and web/install-deps.sh.
# Requires root. Idempotent where possible.

# --- Ookla Speedtest official binary (fallback when package is missing or broken) ---
bwm_speedtest_install_official_binary() {
	local ARCH TARG VER URL TMP
	ARCH=$(uname -m)
	case "$ARCH" in
		x86_64) TARG="linux-x86_64" ;;
		aarch64|arm64) TARG="linux-aarch64" ;;
		armv7l|armhf) TARG="linux-armhf" ;;
		armv6l) TARG="linux-armel" ;;
		i386|i686) TARG="linux-i386" ;;
		*) echo "No official Ookla tarball for arch $ARCH" >&2; return 1 ;;
	esac
	VER="1.2.0"
	URL="https://install.speedtest.net/app/cli/ookla-speedtest-${VER}-${TARG}.tgz"
	TMP=$(mktemp -d)
	if curl -fsSL "$URL" -o "$TMP/speedtest.tgz" && tar -xzf "$TMP/speedtest.tgz" -C "$TMP" && [ -f "$TMP/speedtest" ]; then
		mkdir -p /usr/local/bin
		mv -f "$TMP/speedtest" /usr/local/bin/speedtest
		chmod 755 /usr/local/bin/speedtest
		echo "Installed official Ookla Speedtest CLI -> /usr/local/bin/speedtest"
		if ! env HOME="${HOME:-/root}" TERM="${TERM:-xterm-256color}" TMPDIR="${TMPDIR:-/tmp}" \
			/usr/local/bin/speedtest --accept-license --accept-gdpr --version >/dev/null 2>&1; then
			echo "WARNING: /usr/local/bin/speedtest --version failed — wrong arch, bad libc, or corrupt download. Replace tarball or use distro packages." >&2
		fi
		rm -rf "$TMP"
		return 0
	fi
	rm -rf "$TMP"
	return 1
}

bwm_speedtest_needs_official_binary() {
	command -v speedtest &>/dev/null || return 0
	timeout 15 speedtest --accept-license --accept-gdpr -L -f json &>/dev/null && return 1
	return 0
}

bwm_pkg_mgr() {
	if command -v apt-get &>/dev/null; then echo apt; return
	elif command -v dnf &>/dev/null; then echo dnf; return
	elif command -v microdnf &>/dev/null; then echo microdnf; return
	elif command -v yum &>/dev/null; then echo yum; return
	elif command -v zypper &>/dev/null; then echo zypper; return
	elif command -v apk &>/dev/null; then echo apk; return
	elif command -v pacman &>/dev/null; then echo pacman; return
	fi
	echo unknown
}

# --- Debian / Ubuntu ---
bwm_install_deps_apt() {
	export DEBIAN_FRONTEND=noninteractive
	if ! command -v curl &>/dev/null; then
		apt-get update -qq && apt-get install -y -qq curl ca-certificates
	fi
	curl -fsSL https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | bash
	if [ -f /etc/apt/sources.list.d/ookla_speedtest-cli.list ] && grep -q 'noble' /etc/apt/sources.list.d/ookla_speedtest-cli.list 2>/dev/null; then
		sed -i 's/noble/jammy/g' /etc/apt/sources.list.d/ookla_speedtest-cli.list
	fi
	apt-get update -qq
	apt-get install -y speedtest iperf3 mtr jq tar gzip ca-certificates
	apt-get install -y trickle 2>/dev/null || true
	if ! command -v speedtest &>/dev/null; then
		bwm_speedtest_install_official_binary || true
	fi
	if bwm_speedtest_needs_official_binary; then
		echo "=== Replacing broken speedtest package with official Ookla binary ==="
		bwm_speedtest_install_official_binary || true
	fi
}

# --- Fedora / RHEL / Rocky / Alma / Amazon Linux ---
bwm_install_deps_rpm() {
	local mgr=""
	command -v dnf &>/dev/null && mgr=dnf
	[ -z "$mgr" ] && command -v microdnf &>/dev/null && mgr=microdnf
	[ -z "$mgr" ] && command -v yum &>/dev/null && mgr=yum
	[ -n "$mgr" ] || { echo "No dnf/yum/microdnf found." >&2; return 1; }
	command -v curl &>/dev/null || $mgr install -y curl ca-certificates
	curl -fsSL https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.rpm.sh | bash
	case "$mgr" in
		dnf|microdnf) $mgr install -y speedtest iperf3 mtr jq tar gzip ca-certificates python3 ;;
		yum) yum install -y speedtest iperf3 mtr jq tar gzip ca-certificates python3 ;;
	esac
	if ! command -v speedtest &>/dev/null; then
		bwm_speedtest_install_official_binary || true
	fi
	if bwm_speedtest_needs_official_binary; then
		echo "=== Replacing broken speedtest with official Ookla binary ==="
		bwm_speedtest_install_official_binary || true
	fi
}

# --- SUSE ---
bwm_install_deps_zypper() {
	zypper --non-interactive refresh
	zypper --non-interactive install -y iperf3 mtr jq curl tar gzip ca-certificates python3 python3-pip || true
	if ! command -v speedtest &>/dev/null; then
		bwm_speedtest_install_official_binary || {
			echo "Install speedtest from https://www.speedtest.net/apps/cli if needed." >&2
		}
	fi
	if command -v speedtest &>/dev/null && bwm_speedtest_needs_official_binary; then
		bwm_speedtest_install_official_binary || true
	fi
}

# --- Alpine ---
bwm_install_deps_apk() {
	apk add --no-cache curl tar gzip ca-certificates iperf3 mtr jq python3 py3-pip
	if ! command -v speedtest &>/dev/null; then
		bwm_speedtest_install_official_binary || true
	fi
	if command -v speedtest &>/dev/null && bwm_speedtest_needs_official_binary; then
		bwm_speedtest_install_official_binary || true
	fi
}

# --- Arch Linux ---
bwm_install_deps_pacman() {
	pacman -Sy --needed --noconfirm curl tar gzip iperf3 mtr jq python python-pip ca-certificates
	if ! command -v speedtest &>/dev/null; then
		bwm_speedtest_install_official_binary || {
			echo "Optional: install ookla-speedtest-tool from AUR for packaged speedtest." >&2
		}
	fi
	if command -v speedtest &>/dev/null && bwm_speedtest_needs_official_binary; then
		bwm_speedtest_install_official_binary || true
	fi
}

# Detect family from /etc/os-release
bwm_detect_family() {
	local id like
	[ -f /etc/os-release ] || { echo unknown; return; }
	# shellcheck disable=SC1091
	. /etc/os-release
	id="${ID:-}"
	like="${ID_LIKE:-}"
	case "$id" in
		debian|ubuntu|linuxmint|pop) echo debian; return ;;
		fedora) echo rhel; return ;;
		rhel|centos|rocky|almalinux|ol|virtuozzo) echo rhel; return ;;
		amzn) echo rhel; return ;;
		alpine) echo alpine; return ;;
		arch|manjaro) echo arch; return ;;
		opensuse*|sles|sle*) echo suse; return ;;
	esac
	case " $like " in
		*" debian "*) echo debian; return ;;
		*" rhel "*) echo rhel; return ;;
		*" fedora "*) echo rhel; return ;;
	esac
	echo unknown
}

# Cron and non-login shells often have PATH=/usr/bin:/bin. Package installs may put Ookla only in
# /usr/bin while our scripts prefer /usr/local/bin/speedtest (official tarball). Ensure a stable path.
bwm_ensure_ookla_speedtest_symlink() {
	mkdir -p /usr/local/bin
	if [ -x /usr/local/bin/speedtest ]; then
		return 0
	fi
	local found
	found=$(command -v speedtest 2>/dev/null) || return 0
	if [ -z "$found" ] || [ "$found" = "/usr/local/bin/speedtest" ]; then
		return 0
	fi
	local real
	real=$(readlink -f "$found" 2>/dev/null) || real="$found"
	if [ -x "$real" ]; then
		ln -sf "$real" /usr/local/bin/speedtest
		echo "=== Linked /usr/local/bin/speedtest -> $real (stable path for cron and the web app) ==="
	fi
}

# If we only have a symlink to the distro binary, replace it with the official tarball file (same Ookla
# build, but a real path under /usr/local; set SKIP_OOKLA_TARBALL=1 to skip the extra download).
bwm_replace_ookla_symlink_with_tarball() {
	[ "${SKIP_OOKLA_TARBALL:-0}" = "1" ] && return 0
	[ -L /usr/local/bin/speedtest ] || return 0
	echo "=== Replacing /usr/local/bin/speedtest symlink with official tarball (stable file under /usr/local) ==="
	bwm_speedtest_install_official_binary || true
}

# Main entry: CLI tools (speedtest, iperf3, jq, mtr, curl, tar)
bwm_install_all_cli_dependencies() {
	local fam mgr
	fam=$(bwm_detect_family)
	mgr=$(bwm_pkg_mgr)
	echo "=== Detected OS family: $fam (package tool: $mgr) ==="

	case "$fam" in
		debian)
			bwm_install_deps_apt
			;;
		rhel)
			if [ "$mgr" = unknown ]; then
				echo "No supported package manager (dnf/yum/microdnf)." >&2
				exit 1
			fi
			bwm_install_deps_rpm
			;;
		suse)
			bwm_install_deps_zypper
			;;
		alpine)
			bwm_install_deps_apk
			;;
		arch)
			bwm_install_deps_pacman
			;;
		*)
			# Fallback: try by package manager only
			case "$mgr" in
				apt) bwm_install_deps_apt ;;
				dnf|yum|microdnf) bwm_install_deps_rpm ;;
				zypper) bwm_install_deps_zypper ;;
				apk) bwm_install_deps_apk ;;
				pacman) bwm_install_deps_pacman ;;
				*)
					echo "Unsupported or unknown distribution. Install manually: curl, tar, gzip, jq, iperf3, mtr, Ookla speedtest CLI." >&2
					echo "See https://www.speedtest.net/apps/cli" >&2
					exit 1
					;;
			esac
			;;
	esac

	bwm_ensure_ookla_speedtest_symlink
	bwm_replace_ookla_symlink_with_tarball

	command -v speedtest &>/dev/null || {
		echo "speedtest CLI not available after install." >&2
		exit 1
	}
	command -v iperf3 &>/dev/null || echo "Warning: iperf3 not found; install it for iperf tests." >&2
	command -v jq &>/dev/null || {
		echo "jq is required." >&2
		exit 1
	}
}

# Python + venv support for web UI (install.sh). Prefer venv over system pip (PEP 668 on Debian 12+).
bwm_install_python_web_packages() {
	if command -v apt-get &>/dev/null; then
		export DEBIAN_FRONTEND=noninteractive
		apt-get install -y ca-certificates python3 python3-venv 2>/dev/null || apt-get install -y python3 python3-full
		if python3 -c "import ensurepip" 2>/dev/null; then
			:
		elif [ -f /etc/os-release ] && grep -q "noble\|24.04" /etc/os-release 2>/dev/null; then
			apt-get install -y python3.12-venv
		else
			apt-get install -y python3-venv 2>/dev/null || apt-get install -y python3-full
		fi
	elif command -v dnf &>/dev/null; then
		dnf install -y python3 python3-pip 2>/dev/null || dnf install -y python3
	elif command -v microdnf &>/dev/null; then
		microdnf install -y python3 python3-pip 2>/dev/null || microdnf install -y python3
	elif command -v yum &>/dev/null; then
		yum install -y python3 python3-pip 2>/dev/null || yum install -y python3
	elif command -v zypper &>/dev/null; then
		zypper --non-interactive install -y python3 python3-pip 2>/dev/null || zypper --non-interactive install -y python3
	elif command -v apk &>/dev/null; then
		apk add --no-cache python3 py3-pip py3-virtualenv 2>/dev/null || apk add --no-cache python3 py3-pip
	elif command -v pacman &>/dev/null; then
		pacman -Sy --needed --noconfirm python python-pip python-virtualenv 2>/dev/null || pacman -Sy --needed --noconfirm python python-pip
	else
		echo "Could not install Python automatically. Install python3 and pip, then re-run." >&2
		return 1
	fi
	return 0
}

bwm_systemd_available() {
	[ -d /run/systemd/system ] && command -v systemctl &>/dev/null
}

# Node.js major version (0 if missing)
bwm_node_major() {
	if ! command -v node &>/dev/null; then
		echo 0
		return
	fi
	node -p "parseInt(process.versions.node, 10)" 2>/dev/null || echo 0
}

# Install Node.js + npm for building the Svelte/Vite frontend (Vite 5 needs Node 18+).
bwm_install_nodejs_npm() {
	export DEBIAN_FRONTEND=noninteractive
	local mj
	if command -v apt-get &>/dev/null; then
		apt-get update -qq
		apt-get install -y ca-certificates curl gnupg
		apt-get install -y nodejs npm 2>/dev/null || apt-get install -y nodejs
		mj="$(bwm_node_major)"
		if [ "${mj:-0}" -lt 18 ] 2>/dev/null; then
			echo "=== Installing Node.js 20.x from NodeSource (Vite needs Node 18+) ==="
			curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
			apt-get install -y nodejs
		fi
	elif command -v dnf &>/dev/null; then
		dnf install -y nodejs npm 2>/dev/null || dnf install -y nodejs
	elif command -v microdnf &>/dev/null; then
		microdnf install -y nodejs npm 2>/dev/null || microdnf install -y nodejs
	elif command -v yum &>/dev/null; then
		yum install -y nodejs npm 2>/dev/null || yum install -y nodejs
	elif command -v zypper &>/dev/null; then
		zypper --non-interactive install -y nodejs npm
	elif command -v apk &>/dev/null; then
		apk add --no-cache nodejs npm
	elif command -v pacman &>/dev/null; then
		pacman -Sy --needed --noconfirm nodejs npm
	else
		echo "Could not install Node.js automatically." >&2
		return 1
	fi
	command -v npm &>/dev/null || {
		echo "npm not found after Node install." >&2
		return 1
	}
	mj="$(bwm_node_major)"
	if [ "${mj:-0}" -lt 18 ] 2>/dev/null; then
		echo "Node.js $(node -v 2>/dev/null) is too old; Vite 5 needs Node 18+. Install Node 20+ manually, then re-run." >&2
		return 1
	fi
	echo "Using Node $(node -v), npm $(npm -v)"
	return 0
}

# Run npm ci && npm run build in web/frontend (cwd = repo root).
bwm_build_web_frontend() {
	local root="${1:?repo root}"
	local fe="$root/web/frontend"
	if [ ! -f "$fe/package.json" ]; then
		echo "Missing $fe/package.json" >&2
		return 1
	fi
	(
		cd "$fe" || exit 1
		if [ -f package-lock.json ]; then
			npm ci
		else
			npm install
		fi
		npm run build
	)
}
