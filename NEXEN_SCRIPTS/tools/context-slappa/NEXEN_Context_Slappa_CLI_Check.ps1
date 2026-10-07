$ErrorActionPreference="SilentlyContinue"
$out="H:\NEXEN\state\context-slappa-cli-status.txt"
$lines=New-Object System.Collections.Generic.List[string]
$lines.Add("NEXEN CLI CONNECTIVITY CHECK")
$lines.Add("TIME: "+(Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"))
$lines.Add("RULE: FOUND != AUTHENTICATED != VERIFIED ROUND-TRIP")

$commands=[ordered]@{
 "nexen"="nexen"; "codex"="codex"; "claude"="claude"; "gemini"="gemini";
 "hermes"="hermes"; "antigravity"="antigravity"; "ollama"="ollama"; "n8n"="n8n";
 "git"="git"; "node"="node"; "python"="python"
}
foreach($k in $commands.Keys){
 $c=Get-Command $commands[$k] -ErrorAction SilentlyContinue
 if($c){$lines.Add("$k : FOUND | $($c.Source) | auth/round-trip UNVERIFIED")}
 else {$lines.Add("$k : NOT FOUND")}
}
if(Test-Path "H:\NEXEN\nexen.cmd"){
 $lines.Add("H:\NEXEN\nexen.cmd : FOUND")
 try{
  $r=& "H:\NEXEN\nexen.cmd" everything 2>&1 | Select-Object -First 12
  $lines.Add("nexen everything probe: RAN (read-only output below; readiness still not implied)")
  $r|ForEach-Object{$lines.Add("  "+$_)}
 }catch{$lines.Add("nexen everything probe: FAIL | "+$_.Exception.Message)}
}
if(Test-Path "H:\NEXEN\tools\dc-guardian\nexen-dc.ps1"){
 try{$dc=& "H:\NEXEN\tools\dc-guardian\nexen-dc.ps1" status 2>&1;$lines.Add("Desktop Commander guardian: "+($dc -join " "))}
 catch{$lines.Add("Desktop Commander guardian: FAIL | "+$_.Exception.Message)}
}
$lines | Set-Content $out -Encoding UTF8
