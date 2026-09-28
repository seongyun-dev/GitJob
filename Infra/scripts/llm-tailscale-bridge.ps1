<#
.SYNOPSIS
Publish the WSL technology-summary server on this machine's Tailscale address.

.DESCRIPTION
The GPU is on this notebook, so inference cannot move to the EC2 host -- that
host has no GPU. The EC2 side therefore has to call in, and it cannot reach a
laptop behind NAT directly. Tailscale already joins the two, and the tailnet ACL
allows the whole range, so the only missing piece is something listening on the
Tailscale address: the server itself runs inside WSL, whose NAT the Windows
Tailscale interface does not forward into.

A `netsh interface portproxy` rule for the same address exists and is the
tidier mechanism, but it only binds if the Tailscale adapter already holds its
address when `iphlpsvc` starts -- which after a reboot it usually does not, so
the rule silently keeps a loopback listener and nothing else. Re-binding it
needs an elevated shell every time. This script needs none: binding a high port
to a specific address is not a privileged operation, and the inbound firewall
rule for it already exists ("GitJob LLM test FastAPI (Tailscale)").

Run it from Windows PowerShell; leave the window open while the link is needed.

    powershell -ExecutionPolicy Bypass -File `
      \\wsl.localhost\Ubuntu-24.04\home\ssafy\workspace\S15P21E102\Infra\scripts\llm-tailscale-bridge.ps1

.PARAMETER ListenPort
Tailnet-facing port. 18080 is the one the firewall rule opens.

.PARAMETER TargetPort
Port the summary server listens on inside WSL (`APP_PORT`).

.PARAMETER WaitForTargetSeconds
How long to wait for WSL and the summary server at startup. Generous because
this is normally launched by a logon task, before WSL has booted.
#>
[CmdletBinding()]
param(
    [int]$ListenPort = 18080,
    [int]$TargetPort = 18080,
    [string]$Distro = 'Ubuntu-24.04',
    [int]$WaitForTargetSeconds = 300,
    [int]$RetryDelaySeconds = 3,
    [string]$LogPath = (Join-Path $env:LOCALAPPDATA 'GitJob\logs\llm-tailscale-bridge.log')
)

$ErrorActionPreference = 'Stop'

function Write-BridgeLog {
    param([string]$Level, [string]$Message)
    $line = '{0} [{1}] {2}' -f (Get-Date -Format 'yyyy-MM-ddTHH:mm:ss.fffK'), $Level, $Message
    Write-Host $line
    try {
        $logDirectory = Split-Path -Parent $LogPath
        if ($logDirectory) {
            New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
        }
        Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
    } catch {
        # Logging must never take down the network bridge.
    }
}

$createdNew = $false
$instanceMutex = [System.Threading.Mutex]::new(
    $true,
    'Local\GitJobLlmTailscaleBridge',
    [ref]$createdNew
)
if (-not $createdNew) {
    Write-BridgeLog 'INFO' 'another bridge instance is already running; exiting'
    $instanceMutex.Dispose()
    exit 0
}

function Get-TailscaleIPv4 {
    $exe = 'C:\Program Files\Tailscale\tailscale.exe'
    if (-not (Test-Path $exe)) { throw "Tailscale not found at $exe" }
    $ip = (& $exe ip -4 | Select-Object -First 1).Trim()
    if (-not $ip) { throw 'Tailscale reported no IPv4 address; is it logged in?' }
    return $ip
}

function Get-WslIPv4 {
    # WSL takes a new address on most restarts, so this is resolved per run
    # rather than written into a config that quietly goes stale.
    param([string]$Distro)
    $out = (& wsl.exe -d $Distro -- hostname -I) -replace "`0", ''
    $ip = ($out -split '\s+' | Where-Object { $_ -match '^\d+\.\d+\.\d+\.\d+$' } | Select-Object -First 1)
    if (-not $ip) { throw "Could not read an IPv4 address from WSL distro '$Distro'" }
    return $ip
}

function Test-Target {
    param([string]$Ip, [int]$Port)
    try {
        $probe = [System.Net.Sockets.TcpClient]::new()
        $probe.Connect($Ip, $Port)
        $probe.Close()
        return $true
    } catch { return $false }
}

function Wait-BridgeTarget {
    # At logon both Tailscale and WSL may still be unavailable. Resolve both in
    # this loop: resolving Tailscale once before it made the task exit during
    # the exact startup race it was meant to handle.
    $deadline = (Get-Date).AddSeconds($WaitForTargetSeconds)
    $lastError = 'dependencies are not ready'
    while ($true) {
        try {
            $tailscaleIp = Get-TailscaleIPv4
            & wsl.exe -d $Distro -- true 2>$null | Out-Null
            $wslIp = Get-WslIPv4 -Distro $Distro
            if (Test-Target -Ip $wslIp -Port $TargetPort) {
                return [pscustomobject]@{ TailscaleIp = $tailscaleIp; WslIp = $wslIp }
            }
            $lastError = "nothing answered on ${wslIp}:${TargetPort}"
        } catch {
            $lastError = $_.Exception.Message
        }
        if ((Get-Date) -ge $deadline) {
            throw "Bridge dependencies did not become ready within $WaitForTargetSeconds s: $lastError"
        }
        Start-Sleep -Seconds $RetryDelaySeconds
    }
}

function Start-BridgeSession {
    param([string]$TailscaleIp, [string]$WslIp)

    $listener = [System.Net.Sockets.TcpListener]::new(
        [System.Net.IPAddress]::Parse($TailscaleIp),
        $ListenPort
    )
    $listener.Start()
    Write-BridgeLog 'INFO' "bridging tailnet ${TailscaleIp}:${ListenPort} -> wsl ${WslIp}:${TargetPort}"

    $jobs = [System.Collections.ArrayList]::new()
    $nextAddressCheck = (Get-Date).AddSeconds(5)
    try {
        while ($true) {
            # Reap completed pumps even while no new connection is arriving.
            foreach ($done in @($jobs | Where-Object { $_.Tasks[0].IsCompleted -or $_.Tasks[1].IsCompleted })) {
                $done.In.Close(); $done.Out.Close()
                [void]$jobs.Remove($done)
            }

            if ((Get-Date) -ge $nextAddressCheck) {
                $currentTailscaleIp = Get-TailscaleIPv4
                if ($currentTailscaleIp -ne $TailscaleIp) {
                    throw "Tailscale address changed: $TailscaleIp -> $currentTailscaleIp"
                }
                $nextAddressCheck = (Get-Date).AddSeconds(5)
            }

            if (-not $listener.Pending()) { Start-Sleep -Milliseconds 50; continue }

            $inbound = $listener.AcceptTcpClient()
            $outbound = [System.Net.Sockets.TcpClient]::new()
            try {
                $outbound.Connect($WslIp, $TargetPort)
            } catch {
                # WSL takes a new address whenever it restarts. Refresh the target
                # and let the caller retry instead of killing the bridge process.
                Write-BridgeLog 'WARN' "target refused connection: $($_.Exception.Message)"
                try {
                    $refreshed = Get-WslIPv4 -Distro $Distro
                    if ($refreshed -ne $WslIp) {
                        Write-BridgeLog 'INFO' "wsl address moved: $WslIp -> $refreshed"
                        $WslIp = $refreshed
                    }
                } catch {
                    Write-BridgeLog 'WARN' "could not refresh WSL address: $($_.Exception.Message)"
                }
                $inbound.Close()
                $outbound.Close()
                continue
            }

            # Both directions are copied concurrently. A summary request is small
            # but the reply can take seconds, so a half-duplex pump would stall.
            $a = $inbound.GetStream().CopyToAsync($outbound.GetStream())
            $b = $outbound.GetStream().CopyToAsync($inbound.GetStream())
            [void]$jobs.Add([pscustomobject]@{ Tasks = @($a, $b); In = $inbound; Out = $outbound })
        }
    } finally {
        foreach ($job in $jobs) { $job.In.Close(); $job.Out.Close() }
        $listener.Stop()
        Write-BridgeLog 'INFO' 'bridge session stopped'
    }
}

try {
    Write-BridgeLog 'INFO' "bridge supervisor started for ${Distro}"
    while ($true) {
        try {
            $target = Wait-BridgeTarget
            Start-BridgeSession -TailscaleIp $target.TailscaleIp -WslIp $target.WslIp
        } catch {
            Write-BridgeLog 'ERROR' $_.Exception.Message
        }
        Start-Sleep -Seconds $RetryDelaySeconds
    }
} finally {
    $instanceMutex.ReleaseMutex()
    $instanceMutex.Dispose()
}
