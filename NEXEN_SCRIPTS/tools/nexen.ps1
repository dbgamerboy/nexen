param(
  [Parameter(Position=0)][string]$Command="status",
  [Parameter(ValueFromRemainingArguments=$true)][string[]]$Rest
)
$ErrorActionPreference="Stop"
$Bridge="H:\NEXEN\tools\worker-bridge\nexen_bridge.py"
$Dc="H:\NEXEN\tools\NEXEN_DesktopCommander_Guardian.ps1"
$CliCheck="H:\NEXEN\tools\NEXEN_Context_Slappa_CLI_Check.ps1"
$env:NEXEN_BRIDGE_ROOT="H:\NEXEN\runtime\worker-bridge"
function Invoke-Py([string[]]$BridgeArgs){
  $PyLauncher=Get-Command py -ErrorAction SilentlyContinue
  if($PyLauncher){ & $PyLauncher.Source -3 $Bridge @BridgeArgs; return }
  $Python=Get-Command python -ErrorAction SilentlyContinue
  if($Python -and $Python.Source -and $Python.Source -notmatch "\\WindowsApps\\"){ & $Python.Source $Bridge @BridgeArgs; return }
  $LocalPython=Get-ChildItem (Join-Path $env:LOCALAPPDATA "Programs\Python\Python*\python.exe") -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
  if($LocalPython){ & $LocalPython.FullName $Bridge @BridgeArgs; return }
  throw "Usable Python launcher not found."
}
switch($Command.ToLower()){
  "dc-status"   { & $Dc status; break }
  "dc-discover" { & $Dc discover; break }
  "dc-restart"  { & $Dc restart; break }
  "cli-check"   { & $CliCheck; Get-Content "H:\NEXEN\state\context-slappa-cli-status.txt" -ErrorAction SilentlyContinue; break }
  "slap-status" { Get-Content "H:\NEXEN\state\context-slappa-usage.ini" -ErrorAction SilentlyContinue; break }
  default         { Invoke-Py (@($Command)+$Rest) }
}
