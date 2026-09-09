#Requires -Version 5.1
$ErrorActionPreference = "Continue"

Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" | ForEach-Object {
  if ($_.CommandLine -and $_.CommandLine -match "plexvlc") {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }
}

Unregister-ScheduledTask -TaskName "plexvlc-helper" -Confirm:$false -ErrorAction SilentlyContinue

$programs = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\plexvlc.lnk"
$startup = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\plexvlc.lnk"
Remove-Item $programs, $startup -ErrorAction SilentlyContinue

$app = Join-Path $env:APPDATA "plexvlc"
if (Test-Path $app) {
  $q = Read-Host "Delete $app (config, logs, secret)? [y/N]"
  if ($q -match '^[yY]') {
    Remove-Item $app -Recurse -Force
  }
}

Write-Host "Removed shortcuts and the plexvlc-helper logon task. Disable or remove the unpacked extension in chrome://extensions."
