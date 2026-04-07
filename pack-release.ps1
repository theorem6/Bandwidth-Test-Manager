# Build a self-contained tarball for private mirrors (Windows / PowerShell).
# Run from the repository root. Requires tar (Windows 10+ or Git Bash).
#
# Usage:
#   .\pack-release.ps1
#   $env:SKIP_BUILD = "1"; .\pack-release.ps1

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$OutDir = if ($env:OUT_DIR) { $env:OUT_DIR } else { "dist" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$Stamp = Get-Date -Format "yyyyMMdd"
try {
    $Sha = (git -C $ScriptDir rev-parse --short HEAD 2>$null).Trim()
} catch { $Sha = "unknown" }
if (-not $Sha) { $Sha = "unknown" }
$Name = "bandwidth-test-manager-${Stamp}-${Sha}"
$TarPath = Join-Path $OutDir "${Name}.tar.gz"

if ($env:SKIP_BUILD -ne "1") {
    if (-not (Test-Path "$ScriptDir\web\frontend\node_modules")) {
        Write-Host "=== No web\frontend\node_modules — run: cd web\frontend; npm ci  (or set SKIP_BUILD=1) ==="
    } else {
        Write-Host "=== Building web UI (Vite) ==="
        Push-Location "$ScriptDir\web\frontend"
        npm run build
        Pop-Location
    }
} else {
    Write-Host "=== SKIP_BUILD=1 — using existing web\static ==="
}

Write-Host "=== Creating $TarPath ==="
if (Test-Path $TarPath) { Remove-Item $TarPath -Force }

if (Test-Path "$ScriptDir\web\frontend\node_modules") {
    Write-Warning "web/frontend/node_modules is present — tarball will be large. For a smaller bundle use WSL: ./pack-release.sh (excludes node_modules) or remove node_modules first."
}

& tar -c -z -f $TarPath -C $ScriptDir scripts etc web install.sh finish-web-install.sh bootstrap-web-on-server.sh

if (-not (Test-Path $TarPath)) { throw "tar failed" }

Write-Host ""
Write-Host "OK: $TarPath"
Get-FileHash -Algorithm SHA256 $TarPath
Write-Host ""
Write-Host "Install on a Linux server:"
Write-Host "  tar xzf $Name.tar.gz && sudo ./install.sh"
