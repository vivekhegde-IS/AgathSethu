# Prepares this PC for a NETRA session. Run by the VS Code "netra" task
# before MediaMTX, the backend and the frontend start; it must exit 0 or the
# session does not start.
#
#   1. Stops whatever the previous session left running (MediaMTX, the
#      backend on :8001, the frontend on :5173), so every run loads the
#      current code and nothing starts on a fallback port.
#   2. Makes sure PostgreSQL is running.
#   3. Brings the database schema up to date (alembic upgrade head).
#   4. Checks MediaMTX's .env and the frontend's node_modules (installs them
#      if missing).
#
# CARLA itself runs on the simulator PC; this script prints the command to
# start the sender there.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$mediaServer = Join-Path $root "media-server"

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "NETRA preflight FAILED: $text" -ForegroundColor Red; exit 1 }

# 1) Previous session -----------------------------------------------------------
Step "Stopping the previous session"
foreach ($port in 8001, 5173) {
    $pids = netstat -ano | Select-String "LISTENING" | Select-String ":$port\s" |
        ForEach-Object { ($_ -split '\s+')[-1] } | Sort-Object -Unique
    foreach ($procId in $pids) {
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "port $port held by $($proc.ProcessName) (PID $procId) - stopping it"
            Stop-Process -Id $procId -Force
        }
    }
}
$mtx = Get-Process -Name "mediamtx" -ErrorAction SilentlyContinue
if ($mtx) {
    Write-Host "stopping old MediaMTX (PID $($mtx.Id -join ', '))"
    $mtx | Stop-Process -Force
}
Start-Sleep -Seconds 1

# 2) PostgreSQL -----------------------------------------------------------------
Step "PostgreSQL"
$pg = Get-Service | Where-Object { $_.Name -like "postgresql*" } | Select-Object -First 1
if (-not $pg) { Fail "no PostgreSQL service is installed on this PC." }
if ($pg.Status -ne "Running") {
    Write-Host "$($pg.Name) is $($pg.Status) - starting it"
    try { Start-Service $pg.Name } catch {
        Fail "could not start $($pg.Name) (run VS Code as administrator once, or start it in services.msc)."
    }
}
Write-Host "$($pg.Name) running"

# 3) Database schema --------------------------------------------------------------
Step "Database schema (alembic upgrade head)"
$python = Join-Path $backend ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Fail "backend virtualenv missing at $python. Create it: py -3.11 -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt"
}
Push-Location $backend
& $python -m alembic upgrade head
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) { Fail "alembic upgrade head failed (is DATABASE_URL in backend\.env correct?)." }

# 4) MediaMTX and frontend -----------------------------------------------------------
Step "MediaMTX and frontend"
if (-not (Test-Path (Join-Path $mediaServer "mediamtx.exe"))) { Fail "media-server\mediamtx.exe is missing." }
if (-not (Test-Path (Join-Path $mediaServer ".env"))) { Fail "media-server\.env is missing (copy .env.example and set the two passwords)." }
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    Write-Host "frontend node_modules missing - running npm install"
    Push-Location $frontend
    npm install
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) { Fail "npm install failed." }
}
Write-Host "ok"

Write-Host "`nNETRA preflight done. Starting MediaMTX, backend :8001 (NETRA + record) and frontend :5173." -ForegroundColor Green
Write-Host "On the CARLA PC, start the simulator, then run:  python vivek_fb_rfid.py" -ForegroundColor Yellow
exit 0
