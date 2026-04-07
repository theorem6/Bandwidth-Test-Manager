#!/bin/bash
#
# One-shot download + install for a PRIVATE GitLab-hosted repo (or any HTTPS tarball).
# Host this script on an internal portal, or curl it and pipe to bash (see README).
#
# --- GitLab (archive API) ---
#   export GITLAB_TOKEN="glpat-xxxxxxxx"   # Personal access token: read_repository (or read_api)
#   export GITLAB_URL="https://gitlab.example.com"
#   export GITLAB_PROJECT_PATH="engineering/bandwidth-test-manager"
#   export GITLAB_REF="main"
#   curl -fsSL ./private-download-install.sh | sudo bash
#   sudo bash private-download-install.sh
#
# --- Pre-built tarball URL (e.g. uploaded GitLab Release asset or internal mirror) ---
#   export BWM_TARBALL_URL="https://gitlab.example.com/.../bandwidth-test-manager.tar.gz"
#   optional: BWM_HTTP_HEADER="Authorization: Bearer ..."  or  BWM_CURL_TOKEN for ?private_token=
#
set -euo pipefail

if ! command -v curl &>/dev/null; then
	echo "This script requires curl. Install curl, then retry." >&2
	exit 1
fi

if [ "$(id -u)" -ne 0 ]; then
	echo "Run as root: sudo $0 $*"
	exit 1
fi

BWM_TMPDIR="$(mktemp -d)"
trap 'rm -rf "${BWM_TMPDIR}"' EXIT

download_to() {
	local url="$1"
	local out="$2"
	if [ -n "${BWM_HTTP_HEADER:-}" ]; then
		curl -fsSL -H "${BWM_HTTP_HEADER}" "$url" -o "$out"
	else
		curl -fsSL "$url" -o "$out"
	fi
}

if [ -n "${BWM_TARBALL_URL:-}" ]; then
	echo "=== Downloading bundle ==="
	download_to "${BWM_TARBALL_URL}" "${BWM_TMPDIR}/bundle.tar.gz"
	tar -xzf "${BWM_TMPDIR}/bundle.tar.gz" -C "${BWM_TMPDIR}"
elif [ -n "${GITLAB_TOKEN:-}" ]; then
	: "${GITLAB_URL:=https://gitlab.hyperionsolutionsgroup.net}"
	: "${GITLAB_PROJECT_PATH:=engineering/bandwidth-test-manager}"
	: "${GITLAB_REF:=main}"
	ENC_PATH="$(printf '%s' "${GITLAB_PROJECT_PATH}" | sed 's|/|%2F|g')"
	ARCHIVE_URL="${GITLAB_URL}/api/v4/projects/${ENC_PATH}/repository/archive.tar.gz?sha=${GITLAB_REF}"
	echo "=== Downloading archive from GitLab (${GITLAB_REF}) ==="
	curl -fsSL -H "PRIVATE-TOKEN: ${GITLAB_TOKEN}" "${ARCHIVE_URL}" -o "${BWM_TMPDIR}/archive.tar.gz"
	tar -xzf "${BWM_TMPDIR}/archive.tar.gz" -C "${BWM_TMPDIR}"
else
	echo "Set one of:" >&2
	echo "  GITLAB_TOKEN + optional GITLAB_URL / GITLAB_PROJECT_PATH / GITLAB_REF" >&2
	echo "  BWM_TARBALL_URL (direct HTTPS URL to pack-release tarball)" >&2
	exit 1
fi

# GitLab archive unpacks to a single top-level folder; pack-release tarball is flat at cwd.
FOUND=""
if [ -f "${BWM_TMPDIR}/install.sh" ]; then
	FOUND="${BWM_TMPDIR}"
else
	FOUND="$(find "${BWM_TMPDIR}" -mindepth 1 -maxdepth 1 -type d | head -1)"
fi
if [ -z "${FOUND}" ] || [ ! -f "${FOUND}/install.sh" ]; then
	echo "Could not find install.sh after extract." >&2
	exit 1
fi

cd "${FOUND}"
exec bash install.sh "$@"
