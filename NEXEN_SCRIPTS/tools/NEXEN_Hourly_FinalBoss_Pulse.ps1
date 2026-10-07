$ErrorActionPreference="SilentlyContinue"
$B="H:\NEXEN\tools\worker-bridge\nexen-bridge.ps1"
$C="H:\NEXEN\tools\NEXEN_Context_Slappa_CLI_Check.ps1"
if(Test-Path $C){& $C|Out-Null}
if(Test-Path $B){& $B hourly-pulse --master "H:\NEXEN\state\NEXEN_CONTEXT_SLAPPA_MASTER.txt"|Out-Null}
