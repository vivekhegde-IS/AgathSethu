# Puts the Gmail App Password for the welcome emails on the AWS server.
# It is typed here (hidden), sent over SSH, and written only into the
# server's backend .env - never into the repository or a command line.
#
#   .\member3\deploy\aws\set_smtp_password.ps1
#   .\member3\deploy\aws\set_smtp_password.ps1 -Server ubuntu@15.134.181.203 -Key $env:USERPROFILE\.ssh\aghat-key.pem
param(
    [string]$Server = "ubuntu@15.134.181.203",
    [string]$Key = "$env:USERPROFILE\.ssh\aghat-key.pem"
)
$ErrorActionPreference = "Stop"

$secure = Read-Host "Gmail App Password (16 letters, input hidden)" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    if (-not $plain.Trim()) { throw "No password entered." }
    $plain | ssh -i $Key -o BatchMode=yes $Server "sudo /usr/local/sbin/aghat-set-smtp-password"
    if ($LASTEXITCODE -ne 0) { throw "The server did not accept the password (exit $LASTEXITCODE)." }
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}
