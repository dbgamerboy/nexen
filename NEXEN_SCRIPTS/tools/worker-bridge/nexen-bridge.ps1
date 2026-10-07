param([Parameter(Position=0)][string]$Command="status",[Parameter(ValueFromRemainingArguments=$true)][string[]]$Rest)
$ErrorActionPreference="Stop"
$Root="H:\NEXEN\runtime\worker-bridge"
$Dirs=@("workers","inbox","claimed","outbox","failed","receipts","heartbeats","events","updates","context","logs")
foreach($d in $Dirs){New-Item -ItemType Directory -Force (Join-Path $Root $d)|Out-Null}
function W($p,$o){$o|ConvertTo-Json -Depth 12|Set-Content $p -Encoding UTF8}
function R($p){Get-Content $p -Raw -Encoding UTF8|ConvertFrom-Json}
function V($n,$def=""){$i=[Array]::IndexOf($Rest,$n);if($i -ge 0 -and $i+1 -lt $Rest.Count){$Rest[$i+1]}else{$def}}
function E($k,$o){$p=Join-Path $Root ("events\"+[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()+"-$k.json");W $p ([ordered]@{event=$k;at=(Get-Date).ToString("o");data=$o})}
function Q($ticket,$to,$prompt,$source,$context){
 $id="$ticket-"+([guid]::NewGuid().ToString("N").Substring(0,10))
 $z=[ordered]@{job_id=$id;ticket_id=$ticket;to=$to;prompt=$prompt;source=$source;context=$context;state="QUEUED";attempts=1;created_at=(Get-Date).ToString("o");canonical_completion=$false}
 W (Join-Path $Root "outbox\$id.json") $z;W (Join-Path $Root "inbox\$id.json") $z;E "queued" $z;$id
}
switch($Command.ToLower()){
"init"{$m=[ordered]@{name="NEXEN Universal Worker Bridge";version="3.1-powershell";root=$Root;authority="NEXEN canonical state";canonical_completion=$false};W (Join-Path $Root "bridge.json") $m;$m|ConvertTo-Json}
"discover"{if(Test-Path (Join-Path $Root "bridge.json")){Get-Content (Join-Path $Root "bridge.json") -Raw}else{& $PSCommandPath init}}
"status"{$o=[ordered]@{};foreach($d in $Dirs){$o[$d]=(Get-ChildItem (Join-Path $Root $d) -File -ErrorAction SilentlyContinue).Count};$o|ConvertTo-Json}
"register"{$name=$Rest[0];$z=[ordered]@{worker=$name;registered_at=(Get-Date).ToString("o");canonical_authority=$false};W (Join-Path $Root "workers\$name.json") $z;E "registered" $z;$z|ConvertTo-Json}
"workers"{@(Get-ChildItem (Join-Path $Root "workers") -Filter *.json -File -ErrorAction SilentlyContinue|ForEach-Object{R $_.FullName})|ConvertTo-Json -Depth 8}
"send"{$ticket=V "--ticket";$to=V "--to";$prompt=V "--prompt";if(!$ticket -or !$to -or !$prompt){throw "send requires --ticket --to --prompt"};Q $ticket $to $prompt (V "--source" "unknown") (V "--context")}
"fail"{$id=$Rest[0];$reason=V "--reason" "unknown";$z=[ordered]@{job_id=$id;state="FAILED_DISPATCH";error=$reason;failed_at=(Get-Date).ToString("o");canonical_completion=$false};W (Join-Path $Root "failed\$id.json") $z;E "failed_dispatch" $z;$z|ConvertTo-Json}
"pending-prompts"{@(Get-ChildItem (Join-Path $Root "failed") -Filter *.json -File -ErrorAction SilentlyContinue|ForEach-Object{R $_.FullName})|ConvertTo-Json -Depth 8}
"hourly-pulse"{$master=V "--master" "H:\NEXEN\state\NEXEN_CONTEXT_SLAPPA_MASTER.txt";$key=Get-Date -Format "yyyyMMddHH";$dedupe=Join-Path $Root "events\dedupe-hourly-$key.json";if(Test-Path $dedupe){(R $dedupe).job_id;break};$p="HOURLY CONTINUITY / MONEY PULSE. Owner financial and housing situation is PRIORITY ZERO. Next 14 days are critical. Owner-stated stretch target: `$100,000 in 14 days. Do not restart or undo valid work. REMEMBER does not mean STOP. Check canonical state, CLI connectivity, failed prompts, revenue lane, and continue from last verified checkpoint. REAL CASH > MORE ARCHITECTURE. FINISH > UNBLOCK > MONETIZE > STABILIZE > ENHANCE.";$id=Q "CONTINUITY" "*" $p "nexen-hourly" $master;W $dedupe ([ordered]@{job_id=$id});$id}
default{throw "Unknown command: $Command"}
}
