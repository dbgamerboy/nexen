$ErrorActionPreference="SilentlyContinue"
$env:NEXEN_BRIDGE_ROOT="H:\NEXEN\runtime\worker-bridge"
$relay="H:\NEXEN\tools\relay\nexen_relay.py"
if(-not(Test-Path $relay)){exit 2}
if(Get-Command py -ErrorAction SilentlyContinue){ py -3 $relay cli-check | Out-Null; py -3 $relay pulse --ticket CONTINUITY --to "*" | Out-Null }
elseif(Get-Command python -ErrorAction SilentlyContinue){ python $relay cli-check | Out-Null; python $relay pulse --ticket CONTINUITY --to "*" | Out-Null }
