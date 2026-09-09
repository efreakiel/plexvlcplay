#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$HelperDir = Split-Path $PSScriptRoot -Parent
Set-Location $HelperDir
Write-Host "Starting plexvlc helper from $HelperDir"
python -m plexvlc
if ($LASTEXITCODE -eq 2) {
  Write-Host "Helper already running, or port is in use. See %APPDATA%\plexvlc\plexvlc.log"
  exit 2
}
exit $LASTEXITCODE
