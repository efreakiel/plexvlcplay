#Requires -Version 5.1
param(
    [switch]$Silent
)
$ErrorActionPreference = "Stop"

$HelperDir = Split-Path $PSScriptRoot -Parent
$RepoRoot = Split-Path $HelperDir -Parent
$AppDir = Join-Path $env:APPDATA "plexvlc"
$ExtIdPath = Join-Path $RepoRoot "extension\EXTENSION_ID.txt"
$Example = Join-Path $RepoRoot "config.example.json"
$RunHelper = Join-Path $PSScriptRoot "run-helper.ps1"
$TaskName = "plexvlc-helper"

New-Item -ItemType Directory -Force -Path $AppDir | Out-Null

$aclUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls $AppDir /inheritance:r /grant:r "${aclUser}:(OI)(CI)F" | Out-Null

$pythonw = $null
$python = $null
foreach ($name in @("pythonw", "python")) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) {
        if ($name -eq "pythonw") { $pythonw = $cmd.Source }
        if ($name -eq "python") { $python = $cmd.Source }
    }
}
if (-not $pythonw) { $pythonw = $python }
if (-not $pythonw) {
    Write-Error "Python was not found on PATH. Install Python 3.11+ and retry."
    exit 1
}

$configPath = Join-Path $AppDir "config.json"
if (-not (Test-Path $configPath)) {
    Copy-Item $Example $configPath
}

$extId = $null
if (Test-Path $ExtIdPath) {
    $extId = (Get-Content $ExtIdPath -Raw).Trim().ToLower()
}

if (Test-Path $configPath) {
    $cfg = Get-Content $configPath -Raw | ConvertFrom-Json
    $dirty = $false
    if (-not $cfg.helper_secret) {
        $bytes = New-Object byte[] 32
        [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $cfg.helper_secret = -join ($bytes | ForEach-Object { $_.ToString("x2") })
        $dirty = $true
    }
    if (-not $cfg.client_identifier) {
        $cfg.client_identifier = [guid]::NewGuid().ToString()
        $dirty = $true
    }
    if ($extId -and $extId -match '^[a-p]{32}$') {
        $ids = @($cfg.allowed_extension_ids)
        if (-not ($ids -contains $extId)) {
            $cfg.allowed_extension_ids = @($extId)
            $dirty = $true
        }
    }
    if ($dirty) {
        $cfg | ConvertTo-Json -Depth 8 | Set-Content $configPath -Encoding utf8
    }
}

function New-PlexvlcShortcut([string]$Path, [string]$Target, [string]$Arguments, [string]$WorkDir) {
    $ws = New-Object -ComObject WScript.Shell
    $sc = $ws.CreateShortcut($Path)
    $sc.TargetPath = $Target
    $sc.Arguments = $Arguments
    $sc.WorkingDirectory = $WorkDir
    $sc.WindowStyle = 7
    $sc.Description = "plexvlc helper"
    $sc.Save()
}

$programs = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
New-Item -ItemType Directory -Force -Path $programs | Out-Null
$startup = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"

New-PlexvlcShortcut (Join-Path $programs "plexvlc.lnk") $pythonw "-m plexvlc" $HelperDir
New-PlexvlcShortcut (Join-Path $startup "plexvlc.lnk") $pythonw "-m plexvlc" $HelperDir

$taskOk = $false
try {
    $arg = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$RunHelper`""
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    try { $trigger.Delay = "PT10S" } catch { }
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit ([TimeSpan]::Zero)
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    $taskOk = $true
} catch {
    Write-Host "Could not register scheduled task ($($_.Exception.Message)). Startup shortcut will still run the helper."
}

Write-Host "Installed plexvlc helper."
Write-Host "  Config: $configPath"
if ($taskOk) {
    Write-Host "  Logon task '$TaskName': waits for Plex Media Server, then starts the helper."
}
Write-Host "  Start Menu + Startup shortcuts also created."
Write-Host ""
Write-Host "The unpacked extension (frozen ID) talks to the helper with no pairing code."
Write-Host "Chrome/Edge -> chrome://extensions -> Developer mode -> Load unpacked ->"
Write-Host "  $RepoRoot\extension"

if (-not $Silent) {
    $ws = New-Object -ComObject WScript.Shell
    try {
        $ws.Popup("plexvlc will start after Plex at login. Load the unpacked extension if you have not already.", 12, "plexvlc", 64) | Out-Null
    } catch { }
}
