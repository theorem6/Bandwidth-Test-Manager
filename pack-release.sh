#!/bin/bash
# Build a self-contained tarball for private mirrors, airgap, or internal hosting.
# Run from the repository root (after: cd web/frontend && npm ci && npm run build).
#
# Usage:
#   ./pack-release.sh
#   SKIP_BUILD=1 ./pack-release.sh          # skip npm run build
#   OUT_DIR=/tmp/out ./pack-release.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

OUT_DIR="${OUT_DIR:-dist}"
mkdir -p "$OUT_DIR"

STAMP="$(date +%Y%m%d)"
SHA="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
NAME="bandwidth-test-manager-${STAMP}-${SHA}"
TAR_PATH="${OUT_DIR}/${NAME}.tar.gz"

if [ "${SKIP_BUILD:-}" != "1" ]; then
	if [ ! -d "$ROOT/web/frontend/node_modules" ]; then
		echo "=== No web/frontend/node_modules — run: cd web/frontend && npm ci  (or SKIP_BUILD=1 to pack as-is) ==="
	else
		echo "=== Building web UI (Vite) ==="
		(cd "$ROOT/web/frontend" && npm run build)
	fi
else
	echo "=== SKIP_BUILD=1 — using existing web/static (ensure it is built) ==="
fi

echo "=== Creating ${TAR_PATH} ==="
tar -czf "$TAR_PATH" \
	--exclude='web/frontend/node_modules' \
	--exclude='web/frontend/.vite' \
	--exclude='web/**/__pycache__' \
	--exclude='web/**/.pytest_cache' \
	--exclude='web/venv' \
	--exclude='.git' \
	-C "$ROOT" \
	scripts etc web install.sh finish-web-install.sh bootstrap-web-on-server.sh

echo ""
echo "OK: ${TAR_PATH}"
if command -v sha256sum &>/dev/null; then
	sha256sum "$TAR_PATH"
elif command -v shasum &>/dev/null; then
	shasum -a 256 "$TAR_PATH"
fi
echo ""
echo "Install on a server:"
echo "  tar xzf ${NAME}.tar.gz && cd <extracted-dir-with-install.sh> && sudo ./install.sh"
