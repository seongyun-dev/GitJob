<#
.SYNOPSIS
Register the Tailscale bridge to start at logon.

.DESCRIPTION
Without this the bridge is a PowerShell window someone has to remember to open,
and the EC2 backend's calls start timing out after any reboot with nothing on
the server side to explain it.

Registered for the current user only, so no elevation is needed and nothing
runs as SYSTEM. Re-running replaces the existing registration.

    powershell -ExecutionPolicy Bypass -File `
      \\wsl.localhost\Ubuntu-24.04\home\ssafy\workspace\S15P21E102\Infra\scripts\llm-bridge-install-task.ps1

Remove it with:  Unregister-ScheduledTask -TaskName 'GitJob LLM Tailscale Bridge'
#>
[CmdletBinding()]
param(
    [string]$TaskName = 'GitJob LLM Tailscale Bridge',
    [string]$BridgeScript
)

$ErrorActionPreference = 'Stop'

if (-not $BridgeScript) {
    # $PSScriptRoot comes back empty when this file is invoked over a
    # \\wsl.localhost UNC path, which is the normal way to run it here.
    $here = $PSScriptRoot
    if (-not $here) { $here = Split-Path -Parent $MyInvocation.MyCommand.Path }
    $BridgeScript = Join-Path $here 'llm-tailscale-bridge.ps1'
}

if (-not (Test-Path $BridgeScript)) { throw "Bridge script not found: $BridgeScript" }

$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$BridgeScript`""

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

# The bridge waits for WSL itself, so a delay here is belt and braces; what
# matters is that the task is allowed to run indefinitely and to come back if it
# dies. ExecutionTimeLimit 0 means no limit -- the default would kill it after
# three days.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 99 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description 'Publishes the WSL technology-summary server on this machine Tailscale address so the EC2 backend can call it.' `
    -Force | Out-Null

Write-Host "registered logon task: $TaskName"
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State | Format-List
