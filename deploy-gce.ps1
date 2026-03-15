# Deploy Bandwidth Test Manager to an existing GCE instance (PowerShell).
# Run after: gcloud auth login (if needed)
# Usage: .\deploy-gce.ps1 INSTANCE_NAME [ZONE] [PROJECT]
# Example: .\deploy-gce.ps1 acs-hss-server us-central1-a

param(
    [Parameter(Mandatory = $true)][string]$Instance,
    [string]$Zone = "us-central1-a",
    [string]$Project = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$GcloudArgs = @()
if ($Zone)    { $GcloudArgs += "--zone=$Zone" }
if ($Project) { $GcloudArgs += "--project=$Project" }
$GcloudCmd = "gcloud compute"
$GcloudSuffix = ($GcloudArgs | ForEach-Object { " $_" }) -join ""

Write-Host "=== Deploying to GCE instance: $Instance ==="
$describeOut = & gcloud compute instances describe $Instance $GcloudArgs 2>&1
if ($LASTEXITCODE -ne 0) {
    if ($describeOut -match "Reauthentication|auth login") {
        Write-Host "Run in a terminal (then retry):  gcloud auth login" -ForegroundColor Yellow
    }
    throw "Instance '$Instance' not found or gcloud not configured."
}

Write-Host "=== Building frontend (Svelte) ==="
Push-Location "$ScriptDir\web\frontend"
$ErrorActionPreference = "Continue"
npm run build 2>&1 | Out-Null
$ErrorActionPreference = "Stop"
Pop-Location

Write-Host "=== Creating tarball ==="
Remove-Item -Path "$ScriptDir\deploy.tar.gz" -ErrorAction SilentlyContinue
tar -c -z -f deploy.tar.gz scripts etc web install.sh finish-web-install.sh bootstrap-web-on-server.sh
if (-not (Test-Path deploy.tar.gz)) { Write-Error "tar failed" }

Write-Host "=== Copying project to instance ==="
& gcloud compute scp deploy.tar.gz "${Instance}:/tmp/deploy.tar.gz" $GcloudArgs
if ($LASTEXITCODE -ne 0) { Write-Error "scp failed" }

$RemoteScript = @'
set -e
REMOTE_DIR="/tmp/bwm-deploy"
mkdir -p "$REMOTE_DIR"
tar xzf /tmp/deploy.tar.gz -C "$REMOTE_DIR"
export PORT=8080
if command -v ss &>/dev/null; then
  if ss -tlnp 2>/dev/null | grep -q ':8080\b'; then export PORT=8081; echo "Port 8080 in use, using 8081"; fi
elif command -v netstat &>/dev/null; then
  if netstat -tlnp 2>/dev/null | grep -q ':8080 '; then export PORT=8081; echo "Port 8080 in use, using 8081"; fi
fi
sudo mkdir -p /opt/netperf-web
sudo cp -r "$REMOTE_DIR/web/"* /opt/netperf-web/ 2>/dev/null || true
cd "$REMOTE_DIR" && sudo DEBIAN_FRONTEND=noninteractive PORT="$PORT" bash install.sh
if [ -f "$REMOTE_DIR/finish-web-install.sh" ] && [ -f /opt/netperf-web/main.py ]; then
  sudo PORT="$PORT" bash "$REMOTE_DIR/finish-web-install.sh"
fi
if [ "$PORT" = "8081" ] && command -v nginx &>/dev/null; then
  for f in /etc/nginx/sites-enabled/netperf-web /etc/nginx/sites-available/netperf-web /etc/nginx/snippets/netperf-proxy.conf /etc/nginx/snippets/netperf-path.conf; do
    [ -f "$f" ] && sudo sed -i "s/127.0.0.1:8080/127.0.0.1:8081/g" "$f"
  done
  sudo nginx -t 2>/dev/null && sudo systemctl reload nginx 2>/dev/null && echo "Nginx updated to proxy to port 8081."
fi
rm -rf "$REMOTE_DIR" /tmp/deploy.tar.gz
echo ""
echo "=== Deploy complete ==="
'@

Write-Host "=== Running install on server ==="
$RemoteScriptFile = [System.IO.Path]::GetTempFileName()
Set-Content -Path $RemoteScriptFile -Value $RemoteScript -NoNewline
& gcloud compute scp $RemoteScriptFile "${Instance}:/tmp/deploy-remote.sh" $GcloudArgs
if ($LASTEXITCODE -ne 0) { Remove-Item $RemoteScriptFile -ErrorAction SilentlyContinue; Write-Error "scp script failed" }
Remove-Item $RemoteScriptFile -ErrorAction SilentlyContinue
& gcloud compute ssh $Instance $GcloudArgs --command "sudo bash /tmp/deploy-remote.sh; rm -f /tmp/deploy-remote.sh"
if ($LASTEXITCODE -ne 0) { Write-Error "Remote install failed" }

Remove-Item -Path "$ScriptDir\deploy.tar.gz" -ErrorAction SilentlyContinue
Write-Host ""
Write-Host "Web UI: open Site URL from Settings (e.g. https://your-host/netperf/)"
Write-Host "Optional: gcloud compute ssh $Instance $GcloudSuffix -- 'sudo netperf-scheduler start'"
