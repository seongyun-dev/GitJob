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
    [int]$WaitForTargetSeconds = 300
)

$ErrorActionPreference = 'Stop'

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

$tailscaleIp = Get-TailscaleIPv4

# At logon this runs before WSL is up, so booting it and waiting is the normal
# path, not an error case. `wsl.exe -- true` is what starts the distro, and
# systemd then brings up gitjob-ollama and gitjob-llm-summary.
$wslIp = $null
$deadline = (Get-Date).AddSeconds($WaitForTargetSeconds)
while ($true) {
    try {
        & wsl.exe -d $Distro -- true 2>$null | Out-Null
        $wslIp = Get-WslIPv4 -Distro $Distro
        if (Test-Target -Ip $wslIp -Port $TargetPort) { break }
    } catch { }
    if ((Get-Date) -ge $deadline) {
        throw "Nothing answered on ${Distro}:${TargetPort} within $WaitForTargetSeconds s. In WSL, run: bash Infra/scripts/llm-summary-serve-wsl.sh"
    }
    Start-Sleep -Seconds 3
}

$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse($tailscaleIp), $ListenPort)
$listener.Start()
Write-Host "bridging tailnet ${tailscaleIp}:${ListenPort}  ->  wsl ${wslIp}:${TargetPort}"
Write-Host 'Ctrl+C to stop.'

$jobs = [System.Collections.ArrayList]::new()
try {
    while ($true) {
        # A peer can close while no new connection is arriving. Reap completed
        # pumps before checking Pending so a dead pooled connection is closed
        # promptly instead of waiting for the next caller.
        foreach ($done in @($jobs | Where-Object { $_.Tasks[0].IsCompleted -or $_.Tasks[1].IsCompleted })) {
            $done.In.Close(); $done.Out.Close()
            [void]$jobs.Remove($done)
        }

        if (-not $listener.Pending()) { Start-Sleep -Milliseconds 50; continue }

        $inbound = $listener.AcceptTcpClient()
        $outbound = [System.Net.Sockets.TcpClient]::new()
        try {
            $outbound.Connect($wslIp, $TargetPort)
        } catch {
            # WSL takes a new address whenever it restarts, so a refusal is more
            # often a moved target than a dead one. Re-resolve before giving up
            # on this connection; the next one then goes to the right place.
            Write-Warning "target refused the connection: $($_.Exception.Message)"
            $refreshed = $null
            try { $refreshed = Get-WslIPv4 -Distro $Distro } catch { }
            if ($refreshed -and $refreshed -ne $wslIp) {
                Write-Host "wsl address moved: $wslIp -> $refreshed"
                $wslIp = $refreshed
            }
            $inbound.Close()
            continue
        }

        # Both directions are copied concurrently. A summary request is small but
        # the reply can take seconds on a 4B model, so a half-duplex pump would
        # stall every call.
        $a = $inbound.GetStream().CopyToAsync($outbound.GetStream())
        $b = $outbound.GetStream().CopyToAsync($inbound.GetStream())
        [void]$jobs.Add([pscustomobject]@{ Tasks = @($a, $b); In = $inbound; Out = $outbound })
    }
} finally {
    foreach ($job in $jobs) { $job.In.Close(); $job.Out.Close() }
    $listener.Stop()
    Write-Host 'bridge stopped.'
}
