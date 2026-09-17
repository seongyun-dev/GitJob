<#
.SYNOPSIS
Register the Tailscale bridge to start at logon.

.DESCRIPTION
Without this the bridge is a PowerShell window someone has to remember to open,
and the EC2 backend's calls start timing out after any reboot with nothing on
the server side to explain it.

Registered for the current user only, so no elevation is needed and nothing
runs as SYSTEM. The bridge script is copied to LocalAppData before registration:
the task must not depend on a `\\wsl.localhost` path before WSL has started.
Re-running replaces the installed copy and existing registration.

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

$installDirectory = Join-Path $env:LOCALAPPDATA 'GitJob'
$logDirectory = Join-Path $installDirectory 'logs'
$installedBridge = Join-Path $installDirectory 'llm-tailscale-bridge.ps1'
$logPath = Join-Path $logDirectory 'llm-tailscale-bridge.log'
$bootstrapLogPath = Join-Path $logDirectory 'llm-tailscale-bridge-bootstrap.log'
$launcherPath = Join-Path $installDirectory 'llm-tailscale-bridge.cmd'
$startupDirectory = [Environment]::GetFolderPath('Startup')
$startupLauncher = Join-Path $startupDirectory 'GitJob LLM Tailscale Bridge.vbs'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
Copy-Item -LiteralPath $BridgeScript -Destination $installedBridge -Force

$powershellExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
if (-not (Test-Path $powershellExe)) { throw "Windows PowerShell not found: $powershellExe" }
$launcher = @"
@echo off
"$powershellExe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$installedBridge" -LogPath "$logPath" >> "$bootstrapLogPath" 2>&1
exit /b %ERRORLEVEL%
"@
Set-Content -LiteralPath $launcherPath -Value $launcher -Encoding ASCII
$escapedLauncherPath = $launcherPath.Replace('"', '""')
$startupScript = @"
Set shell = CreateObject("WScript.Shell")
shell.Run Chr(34) & "$escapedLauncherPath" & Chr(34), 0, False
"@
Set-Content -LiteralPath $startupLauncher -Value $startupScript -Encoding ASCII

$action = New-ScheduledTaskAction `
    -Execute $env:ComSpec `
    -Argument "/D /C call `"$launcherPath`""

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
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description 'Publishes the WSL technology-summary server on this machine Tailscale address so the EC2 backend can call it.' `
    -Force | Out-Null

Write-Host "registered logon task: $TaskName"
Write-Host "installed bridge: $installedBridge"
Write-Host "bridge log: $logPath"
Write-Host "bootstrap log: $bootstrapLogPath"
Write-Host "startup fallback: $startupLauncher"
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 3
$registered = Get-ScheduledTask -TaskName $TaskName
$registered | Select-Object TaskName, State | Format-List

# Some Windows builds reject a valid long-running PowerShell action before the
# script starts (LastTaskResult 0xFFFD0000). The per-user Startup launcher is an
# independent bootstrap path. A named mutex in the bridge makes the two safe to
# run together.
$tailscaleExe = 'C:\Program Files\Tailscale\tailscale.exe'
if (-not (Test-Path $tailscaleExe)) { throw "Tailscale not found: $tailscaleExe" }
$tailscaleIp = (& $tailscaleExe ip -4 | Select-Object -First 1).Trim()
if (-not $tailscaleIp) { throw 'Tailscale reported no IPv4 address' }
$listener = Get-NetTCPConnection -State Listen -LocalAddress $tailscaleIp -LocalPort 18080 -ErrorAction SilentlyContinue
if (-not $listener) {
    Start-Process -FilePath (Join-Path $env:SystemRoot 'System32\wscript.exe') `
        -ArgumentList "`"$startupLauncher`"" `
        -WindowStyle Hidden
    $deadline = (Get-Date).AddSeconds(15)
    do {
        Start-Sleep -Milliseconds 500
        $listener = Get-NetTCPConnection -State Listen -LocalAddress $tailscaleIp -LocalPort 18080 -ErrorAction SilentlyContinue
    } while (-not $listener -and (Get-Date) -lt $deadline)
}
if (-not $listener) {
    throw "Bridge did not listen on the Tailscale address. Inspect: $logPath and $bootstrapLogPath"
}
