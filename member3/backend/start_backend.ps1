# Starts the AGHAT SETHU backend reliably.
#
#   .\start_backend.ps1            # port 8000
#   .\start_backend.ps1 -Port 8001
#
# What it does, so the backend "loads up" every time:
#   1. Frees the port from any stale/hung uvicorn (fixes [WinError 10048]).
#   2. Uses the project's .venv Python (NOT the system Python, which lacks the
#      backend's dependencies).
#   3. Starts uvicorn against app.main:app.
param([int]$Port = 8000)

Set-Location $PSScriptRoot

# 1) Free the port -----------------------------------------------------------
$pids = netstat -ano | Select-String "LISTENING" | Select-String ":$Port\s" |
    ForEach-Object { ($_ -split '\s+')[-1] } | Sort-Object -Unique
foreach ($procId in $pids) {
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "Port $Port in use by $($proc.ProcessName) (PID $procId) - stopping it"
        Stop-Process -Id $procId -Force
    }
}
if ($pids) { Start-Sleep -Seconds 1 }

# 2) Pick the venv Python ----------------------------------------------------
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "Virtualenv not found at $python. Create it first: py -3.11 -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt"
    exit 1
}

# 3) Run ---------------------------------------------------------------------
Write-Host "Starting backend on http://127.0.0.1:$Port (python: $python)"
& $python -m uvicorn app.main:app --host 0.0.0.0 --port $Port
