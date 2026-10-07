$ErrorActionPreference="SilentlyContinue"
$Out="H:\NEXEN\state\context-slappa-cli-status.txt"
$L=New-Object System.Collections.Generic.List[string]
$L.Add("NEXEN CONTEXT SLAPPA - CLI CONNECTIVITY / DISCOVERY STATUS")
$L.Add("TIME: "+(Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"))
$L.Add("RULE: FOUND != AUTHENTICATED != CONNECTED != TESTED")
$Targets=@("codex","claude","gemini","hermes","antigravity","ollama","n8n","git","node","npx","py","python")
foreach($n in $Targets){$g=Get-Command $n -ErrorAction SilentlyContinue;if($g){$L.Add($n.ToUpper()+": RESOLVED | "+$g.Source+" | auth/round-trip UNVERIFIED")}else{$L.Add($n.ToUpper()+": NOT FOUND")}}
if(Test-Path "$env:USERPROFILE\bin\nexen-bridge.cmd"){$L.Add("NEXEN-BRIDGE: RESOLVED | $env:USERPROFILE\bin\nexen-bridge.cmd")}else{$L.Add("NEXEN-BRIDGE: NOT FOUND")}
if(Test-Path "H:\NEXEN\nexen.cmd"){$L.Add("ROOT NEXEN CLI: FOUND | H:\NEXEN\nexen.cmd")}else{$L.Add("ROOT NEXEN CLI: NOT FOUND")}
$L|Set-Content $Out -Encoding UTF8
$L
