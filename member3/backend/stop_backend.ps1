# Stops the AGHAT SETHU backend (e.g. when it hangs and Ctrl+C does nothing).
#
#   .\stop_backend.ps1             # port 8000
#   .\stop_backend.ps1 -Port 8001
#
# Only the process LISTENING on that port is stopped - never every python.exe.
param([int]$Port = 8000)

$listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $listeners) {
    Write-Host "Nothing is listening on port $Port."
    exit 0
}

foreach ($procId in ($listeners.OwningProcess | Sort-Object -Unique)) {
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "Stopping $($proc.ProcessName) (PID $procId) on port $Port"
        Stop-Process -Id $procId -Force
    }
}

Start-Sleep -Seconds 1
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    Write-Warning "Port $Port is still in use."
    exit 1
}
Write-Host "Port $Port is free."
