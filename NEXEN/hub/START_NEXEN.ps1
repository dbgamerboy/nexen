$ErrorActionPreference = 'Stop'
$nexenRoot = $PSScriptRoot
$listener = Get-NetTCPConnection -LocalPort 8788 -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    Write-Host 'Port 8788 is already in use. Open http://127.0.0.1:8788 to inspect the running service.'
    exit 0
}
$pythonExe = 'F:\yum\NEXEN_Autonomy_v0.1\.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Install the local Python environment first.' }
$nexenEntry = Join-Path $nexenRoot 'start_on_f.pyw'
$env:TEMP = 'F:\NEXEN_CACHE\temp'
$env:TMP = $env:TEMP
$running = Start-Process -FilePath $pythonExe -ArgumentList @(('"' + $nexenEntry + '"')) -WorkingDirectory $nexenRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $nexenRoot 'logs\server.out.log') -RedirectStandardError (Join-Path $nexenRoot 'logs\server.err.log')
Write-Host "NEXEN starting (process $($running.Id)). Dashboard: http://127.0.0.1:8788"
