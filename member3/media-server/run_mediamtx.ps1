# Starts MediaMTX natively on Windows with the AGHAT SETHU camera config.
#
#   .\run_mediamtx.ps1                                  # mediamtx.exe next to this script
#   .\run_mediamtx.ps1 -Exe C:\tools\mediamtx\mediamtx.exe
#
# Secrets come from .env in this folder (copy .env.example -> .env):
#   MTX_AUTHINTERNALUSERS_0_PASS  (publisher = CARLA)   MTX_AUTHINTERNALUSERS_1_PASS  (reader = backend)
param([string]$Exe = (Join-Path $PSScriptRoot "mediamtx.exe"))

Set-Location $PSScriptRoot

if (-not (Test-Path $Exe)) {
    Write-Error "mediamtx.exe not found at $Exe. Download mediamtx_v1.21.1_windows_amd64.zip from https://github.com/bluenviron/mediamtx/releases and extract mediamtx.exe here (or pass -Exe)."
    exit 1
}
$envFile = Join-Path $PSScriptRoot ".env"
if (-not (Test-Path $envFile)) {
    Write-Error "Missing $envFile - copy .env.example to .env and set the two passwords."
    exit 1
}
foreach ($line in Get-Content $envFile) {
    if ($line -match '^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$') {
        [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], "Process")
    }
}
foreach ($required in "MTX_AUTHINTERNALUSERS_0_PASS", "MTX_AUTHINTERNALUSERS_1_PASS") {
    if (-not [Environment]::GetEnvironmentVariable($required, "Process")) {
        Write-Error "$required is not set in .env"
        exit 1
    }
}

Write-Host "MediaMTX: RTSP ingest :8554/tcp | WHEP 127.0.0.1:8889 | WebRTC media :8189/udp"
& $Exe (Join-Path $PSScriptRoot "mediamtx.yml")
