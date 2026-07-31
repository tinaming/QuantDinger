#Requires -Version 5.1
<#
.SYNOPSIS
  Idempotent QMT Bridge starter for Windows host.

.DESCRIPTION
  Order: miniQMT must already be logged in, then this script ensures
  qmt_bridge.py is listening on :5002 with connected=true.

  Usage:
    .\start_qmt_bridge.ps1              # start if needed
    .\start_qmt_bridge.ps1 -StatusOnly  # health check only
    .\start_qmt_bridge.ps1 -Force       # kill existing bridge then restart
#>
[CmdletBinding()]
param(
    [switch]$StatusOnly,
    [switch]$Force,
    [int]$Port = 5002,
    [int]$WaitMiniQmtSec = 0
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BridgePy = Join-Path $ScriptDir "qmt_bridge.py"
$WorkDir = Split-Path -Parent $ScriptDir
$LogDir = Join-Path $ScriptDir "logs"
$OutLog = Join-Path $LogDir "qmt_bridge.log"
$ErrLog = Join-Path $LogDir "qmt_bridge.err.log"
$StatusUrl = "http://127.0.0.1:$Port/qmt/status"
$MiniQmtName = "XtMiniQmt"

function Get-BridgeHealth {
    try {
        $resp = Invoke-WebRequest -Uri $StatusUrl -UseBasicParsing -TimeoutSec 3
        $json = $resp.Content | ConvertFrom-Json
        return [pscustomobject]@{
            Ok        = ($resp.StatusCode -eq 200 -and $json.code -eq 0)
            Connected = [bool]$json.data.connected
            Raw       = $resp.Content
        }
    } catch {
        return [pscustomobject]@{ Ok = $false; Connected = $false; Raw = $_.Exception.Message }
    }
}

function Test-MiniQmtRunning {
    return [bool](Get-Process -Name $MiniQmtName -ErrorAction SilentlyContinue)
}

function Stop-BridgeListeners {
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        if ($c.OwningProcess) {
            Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep -Seconds 1
}

function Find-Python {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $fallback = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
    if (Test-Path $fallback) { return $fallback }
    throw "python.exe not found in PATH or $fallback"
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

if ($WaitMiniQmtSec -gt 0) {
    $deadline = (Get-Date).AddSeconds($WaitMiniQmtSec)
    while (-not (Test-MiniQmtRunning) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
    }
}

$health = Get-BridgeHealth
if ($StatusOnly) {
    Write-Host ("miniQMT={0} bridge_ok={1} connected={2}" -f (Test-MiniQmtRunning), $health.Ok, $health.Connected)
    Write-Host $health.Raw
    if ($health.Ok -and $health.Connected) { exit 0 } else { exit 1 }
}

if (-not (Test-MiniQmtRunning)) {
    Write-Warning "XtMiniQmt is not running. Start miniQMT and log in first, then re-run this script."
    Write-Host "Suggested: Start-Process `"D:\迅投极速策略交易系统交易终端 华鑫证券QMT模拟\bin.x64\XtMiniQmt.exe`""
    exit 2
}

if ($Force) {
    Stop-BridgeListeners
    $health = Get-BridgeHealth
}

if ($health.Ok -and $health.Connected) {
    Write-Host "QMT Bridge already healthy on :$Port (connected=true)"
    Write-Host $health.Raw
    exit 0
}

if ($health.Ok -and -not $health.Connected) {
    Write-Warning "Bridge up but connected=false — restarting after miniQMT login check"
    Stop-BridgeListeners
}

if (-not (Test-Path $BridgePy)) {
    throw "Missing bridge script: $BridgePy"
}

$python = Find-Python
Write-Host "Starting QMT Bridge: $python $BridgePy"
# Rotate oversized logs (~2MB)
foreach ($f in @($OutLog, $ErrLog)) {
    if ((Test-Path $f) -and ((Get-Item $f).Length -gt 2MB)) {
        Move-Item -Force $f "$f.bak"
    }
}

$proc = Start-Process -FilePath $python `
    -ArgumentList "`"$BridgePy`"" `
    -WorkingDirectory $WorkDir `
    -RedirectStandardOutput $OutLog `
    -RedirectStandardError $ErrLog `
    -WindowStyle Hidden `
    -PassThru

Write-Host "Started PID=$($proc.Id); logs: $LogDir"

$ready = $false
for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 1
    $health = Get-BridgeHealth
    if ($health.Ok -and $health.Connected) {
        $ready = $true
        break
    }
}

if ($ready) {
    Write-Host "OK: Bridge connected on :$Port"
    Write-Host $health.Raw
    exit 0
}

Write-Warning "Bridge started but not connected yet. Check miniQMT login and logs:"
Write-Host "  $OutLog"
Write-Host "  $ErrLog"
Write-Host $health.Raw
exit 3
