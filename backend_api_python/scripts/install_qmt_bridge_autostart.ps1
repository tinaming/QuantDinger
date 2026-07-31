#Requires -Version 5.1
<#
.SYNOPSIS
  Register Windows Scheduled Tasks to keep QMT Bridge alive.

.DESCRIPTION
  Creates two tasks (combined AtLogOn+Repeat in one task is rejected by Task Scheduler):
    - ChanQuant-QMT-Bridge       : every 5 minutes (watchdog; no-op if healthy)
    - ChanQuant-QMT-Bridge-Logon : at user logon (+60s delay)

  Run once:
    powershell -ExecutionPolicy Bypass -File .\install_qmt_bridge_autostart.ps1

  Uninstall:
    .\install_qmt_bridge_autostart.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [switch]$Uninstall,
    [string]$TaskName = "ChanQuant-QMT-Bridge"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Starter = Join-Path $ScriptDir "start_qmt_bridge.ps1"
$LogonTaskName = "$TaskName-Logon"

if (-not (Test-Path $Starter)) {
    throw "Missing $Starter"
}

function Remove-BridgeTasks {
    foreach ($name in @($TaskName, $LogonTaskName)) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    }
}

if ($Uninstall) {
    Remove-BridgeTasks
    Write-Host "Removed scheduled tasks: $TaskName, $LogonTaskName"
    exit 0
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Starter`" -WaitMiniQmtSec 120"

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

# Watchdog: every 5 minutes (~10 years repetition window is "indefinite" enough)
$triggerRepeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $triggerRepeat `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

# Logon: separate task — combining with Repeat trigger fails on this Windows build
$triggerLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$triggerLogon.Delay = "PT1M"

Register-ScheduledTask `
    -TaskName $LogonTaskName `
    -Action $action `
    -Trigger $triggerLogon `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

Write-Host "Registered scheduled tasks:"
Write-Host "  $TaskName       (every 5 min watchdog)"
Write-Host "  $LogonTaskName (AtLogOn +60s)"
Write-Host "  Starter: $Starter"
Write-Host ""
Write-Host "Still required each day:"
Write-Host "  1) Start miniQMT (XtMiniQmt) and complete login if prompted"
Write-Host "  2) Tasks start/restart Bridge once XtMiniQmt is running"
Write-Host ""
Write-Host "Manual check:  powershell -File `"$Starter`" -StatusOnly"
Write-Host "Manual start:  powershell -File `"$Starter`""
