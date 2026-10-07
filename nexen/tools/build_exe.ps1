$ErrorActionPreference = 'Stop'
$app = Split-Path -Parent $PSScriptRoot
$csc = 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$out = Join-Path $app 'NEXEN.exe'
$tmp = Join-Path $app 'NEXEN.exe.new'
& $csc /nologo /target:winexe /optimize+ "/out:$tmp" /r:System.Windows.Forms.dll /r:System.Drawing.dll (Join-Path $app 'launcher\NexenLauncher.cs')
if ($LASTEXITCODE -ne 0) { throw "csc failed ($LASTEXITCODE)" }
Move-Item -Force $tmp $out
$hash = (Get-FileHash $out -Algorithm SHA256).Hash
"built $out  sha256 $hash"
