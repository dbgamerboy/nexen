$ErrorActionPreference = 'Stop'
$nexenRoot = $PSScriptRoot
$expectedRoot = 'F:\NEXEN_GAME\NEXEN_Autonomy_v0.1'
if ([System.IO.Path]::GetFullPath($nexenRoot) -ne $expectedRoot) { throw 'Unexpected NEXEN runtime folder' }
$env:TEMP = 'F:\NEXEN_CACHE\temp\n8n'
$env:TMP = $env:TEMP
$env:PYTHONDONTWRITEBYTECODE = '1'
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
$python = 'F:\yum\NEXEN_Autonomy_v0.1\.venv\Scripts\pythonw.exe'
$entry = Join-Path $nexenRoot 'harnesses\n8n_runtime.py'
Start-Process -FilePath $python -ArgumentList @('-B', ('"' + $entry + '"'), 'run') -WorkingDirectory $nexenRoot -WindowStyle Hidden
Write-Host 'n8n local startup requested. Open http://localhost:5678 after its health check succeeds.'
