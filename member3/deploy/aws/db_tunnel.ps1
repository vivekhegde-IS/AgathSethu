# Opens the SSH tunnel that lets the LOCAL backend use the AWS database.
#   localhost:5433  ->  AWS server's PostgreSQL (127.0.0.1:5432 on the server)
# Keep this window open while the local backend runs. Ctrl+C closes the tunnel.
# The AWS database is never opened to the internet; only this SSH key reaches it.
#
# Usage (PowerShell):  .\member3\deploy\aws\db_tunnel.ps1
# If it times out: your internet IP changed -> EC2 security group -> SSH (22) -> My IP.

$Server = "ubuntu@15.134.181.203"
$Key = Join-Path $HOME ".ssh\aghat-key.pem"

Write-Host "Tunnel: localhost:5433 -> AWS PostgreSQL. Keep this window open (Ctrl+C to stop)."
while ($true) {
    ssh -i $Key -N -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes `
        -L 5433:127.0.0.1:5432 $Server
    Write-Host "Tunnel dropped; reconnecting in 5 s (Ctrl+C to stop)..."
    Start-Sleep -Seconds 5
}
