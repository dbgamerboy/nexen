param(
  [Parameter(Position=0)][string]$Command="status",
  [Parameter(ValueFromRemainingArguments=$true)][string[]]$Rest
)
$ErrorActionPreference="Stop"
$relay="H:\NEXEN\tools\relay\nexen_relay.py"
$env:NEXEN_BRIDGE_ROOT="H:\NEXEN\runtime\worker-bridge"

function PyExe {
  if(Get-Command py -ErrorAction SilentlyContinue){ return @("py","-3") }
  if(Get-Command python -ErrorAction SilentlyContinue){ return @("python") }
  throw "Python launcher not found."
}
$py=PyExe
if(-not(Test-Path $relay)){ throw "NEXEN relay missing: $relay" }

switch($Command.ToLower()){
  "dc-status" { & "H:\NEXEN\tools\dc-guardian\nexen-dc.ps1" status; break }
  "dc-restart" { & "H:\NEXEN\tools\dc-guardian\nexen-dc.ps1" restart; break }
  "dc-discover" { & "H:\NEXEN\tools\dc-guardian\nexen-dc.ps1" discover; break }
  "slap-refresh" { & "H:\NEXEN\tools\context-slappa\NEXEN_Context_Slappa_CLI_Check.ps1"; break }
  default {
    if($py.Count -eq 2){ & $py[0] $py[1] $relay $Command @Rest }
    else { & $py[0] $relay $Command @Rest }
  }
}
