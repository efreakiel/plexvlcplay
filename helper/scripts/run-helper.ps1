#Requires -Version 5.1
# Silent starter used by the logon scheduled task.
# Waits for Plex Media Server, then launches the loopback helper if needed.

$ErrorActionPreference = "Continue"
$HelperDir = Split-Path $PSScriptRoot -Parent
$AppDir = Join-Path $env:APPDATA "plexvlc"
$pidFile = Join-Path $AppDir "helper.pid"
$port = 18765

function Test-HelperUp {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $iar = $client.BeginConnect("127.0.0.1", $port, $null, $null)
        $ok = $iar.AsyncWaitHandle.WaitOne(400)
        if ($ok -and $client.Connected) {
            $client.Close()
            return $true
        }
        $client.Close()
    } catch { }
    return $false
}

function Test-HelperPid {
    if (-not (Test-Path $pidFile)) { return $false }
    try {
        $procId = [int]((Get-Content $pidFile -TotalCount 1).Trim())
    } catch {
        return $false
    }
    if ($procId -le 0) { return $false }
    return [bool](Get-Process -Id $procId -ErrorAction SilentlyContinue)
}

if ((Test-HelperUp) -or (Test-HelperPid)) {
    exit 0
}

$deadline = (Get-Date).AddSeconds(120)
while ((Get-Date) -lt $deadline) {
    if (Get-Process -Name "Plex Media Server" -ErrorAction SilentlyContinue) {
        break
    }
    if ((Test-HelperUp) -or (Test-HelperPid)) {
        exit 0
    }
    Start-Sleep -Seconds 2
}

Start-Sleep -Seconds 2
if ((Test-HelperUp) -or (Test-HelperPid)) {
    exit 0
}

$pythonw = $null
foreach ($name in @("pythonw", "python")) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) {
        $pythonw = $cmd.Source
        if ($name -eq "pythonw") { break }
    }
}
if (-not $pythonw) { exit 1 }

Start-Process -FilePath $pythonw -ArgumentList "-m", "plexvlc" -WorkingDirectory $HelperDir -WindowStyle Hidden
exit 0
