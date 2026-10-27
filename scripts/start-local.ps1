param([switch]$TunnelOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$keyPath = Join-Path $env:USERPROFILE '.ssh\nms_dashboard_tunnel'
$runtimePath = Join-Path $projectRoot '.runtime'
if (-not (Test-Path -LiteralPath $keyPath)) { throw 'Kunci tunnel belum tersedia. Lihat docs/PHASE-03-INTEGRATION.md.' }
New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null
$listener = Get-NetTCPConnection -State Listen -LocalPort 18765 -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $ownerProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
    if ($ownerProcess.Name -ne 'ssh.exe' -or $ownerProcess.CommandLine -notlike '*127.0.0.1:18765:127.0.0.1:8765*' -or $ownerProcess.CommandLine -notlike '*nms_dashboard_tunnel*') { throw 'Port 18765 dipakai proses lain; tidak ada proses yang dihentikan.' }
} else {
    $sshArgs = @('-NT','-L','127.0.0.1:18765:127.0.0.1:8765','-i',('"' + $keyPath + '"'),'-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ExitOnForwardFailure=yes','-o','ServerAliveInterval=30','-o','ServerAliveCountMax=3','azril@192.168.20.195')
    $tunnel = Start-Process -FilePath (Join-Path $env:WINDIR 'System32\OpenSSH\ssh.exe') -ArgumentList $sshArgs -WindowStyle Hidden -RedirectStandardError (Join-Path $runtimePath 'tunnel-error.log') -PassThru
    $tunnel.Id | Set-Content (Join-Path $runtimePath 'tunnel.pid')
    Write-Host "Tunnel privat dimulai (PID $($tunnel.Id))."
}
if (-not $TunnelOnly) {
    Set-Location -LiteralPath $projectRoot
    npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
}
