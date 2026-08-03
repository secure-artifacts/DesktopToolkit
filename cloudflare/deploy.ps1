# One-click deploy P2P signaling Worker (Durable Object rooms)
# Usage: right-click → Run with PowerShell, or: powershell -ExecutionPolicy Bypass -File deploy.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host ""
Write-Host "=== Desktop Toolkit P2P deploy ===" -ForegroundColor Cyan

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "Node.js not found. Install from https://nodejs.org/"
}

Write-Host "[1/3] Cloudflare login check..."
$who = & npx --yes wrangler whoami 2>&1 | Out-String
if ($LASTEXITCODE -ne 0 -or $who -match "not authenticated|not logged") {
    Write-Host "Opening browser for wrangler login..."
    & npx --yes wrangler login
}

Write-Host "[2/3] wrangler deploy..."
& npx --yes wrangler deploy
if ($LASTEXITCODE -ne 0) { throw "deploy failed" }

$nameLine = Get-Content wrangler.toml | Where-Object { $_ -match '^\s*name\s*=' } | Select-Object -First 1
$name = if ($nameLine -match '"([^"]+)"') { $Matches[1] } else { "desktop-toolkit-p2p" }

# Discover workers.dev host from whoami account is hard; try common pattern from prior deploy
$candidates = @(
    "https://$name.christiancag-fr.workers.dev/health",
    "https://$name.workers.dev/health"
)

Write-Host "[3/3] Health check..."
$ok = $false
foreach ($u in $candidates) {
    try {
        $r = Invoke-RestMethod -Uri $u -TimeoutSec 15
        Write-Host ($r | ConvertTo-Json -Compress)
        if ($r.ok -and $r.durable_rooms) {
            Write-Host "OK durable_rooms=true  $u" -ForegroundColor Green
            $ok = $true
            $appUrl = $u -replace "/health$", "" -replace "^https://", "wss://"
            Write-Host ""
            Write-Host "App relay URL:" -ForegroundColor Green
            Write-Host "  $appUrl"
            break
        }
        if ($r.ok -and -not $r.durable_rooms) {
            Write-Host "WARN: health OK but durable_rooms=false — redeploy with new_sqlite_classes" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "skip $u : $($_.Exception.Message)" -ForegroundColor DarkGray
    }
}
if (-not $ok) {
    Write-Host "Could not auto-probe health; check Cloudflare dashboard Workers URL." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Done."
pause
