param([ValidateSet("discover","status","restart")][string]$Command="status")
$ErrorActionPreference="Stop"
$StateDir="H:\NEXEN\state\desktop-commander"
$LogDir="H:\NEXEN\logs\desktop-commander"
$State=Join-Path $StateDir "launch.json"
$Log=Join-Path $LogDir "guardian.log"
New-Item -ItemType Directory -Force $StateDir,$LogDir | Out-Null
function Log($m){ Add-Content $Log ("{0} {1}" -f (Get-Date -Format o),$m) }
function Save($o){ $o|ConvertTo-Json -Depth 6|Set-Content $State -Encoding UTF8; return $o }
function Discover {
  $services=Get-CimInstance Win32_Service -ErrorAction SilentlyContinue|Where-Object{
    $_.Name -match 'desktop.*commander|commander.*desktop' -or $_.DisplayName -match 'desktop.*commander|commander.*desktop' -or $_.PathName -match 'desktop.*commander|commander.*desktop'
  }
  if($services){$s=$services|Select-Object -First 1;return Save ([ordered]@{mode='service';name=$s.Name;path=$s.PathName;discovered=(Get-Date).ToString('o')})}
  $p=Get-CimInstance Win32_Process -ErrorAction SilentlyContinue|Where-Object{
    ($_.Name -match 'desktop.*commander|commander.*desktop' -or $_.CommandLine -match 'desktop.*commander|commander.*desktop') -and $_.ExecutablePath
  }|Select-Object -First 1
  if($p){return Save ([ordered]@{mode='process';name=$p.Name;path=$p.ExecutablePath;commandLine=$p.CommandLine;discovered=(Get-Date).ToString('o')})}
  $roots=@("$env:LOCALAPPDATA\Programs","$env:LOCALAPPDATA","$env:APPDATA","$env:ProgramFiles",${env:ProgramFiles(x86)})|Where-Object{$_ -and (Test-Path $_)}
  foreach($r in $roots){
    $hit=Get-ChildItem $r -File -Filter *.exe -Recurse -Depth 4 -ErrorAction SilentlyContinue|Where-Object{$_.Name -match 'desktop.*commander|commander.*desktop'}|Select-Object -First 1
    if($hit){return Save ([ordered]@{mode='process';name=$hit.Name;path=$hit.FullName;commandLine=$hit.FullName;discovered=(Get-Date).ToString('o')})}
  }
  return $null
}
function Spec {if(Test-Path $State){try{$x=Get-Content $State -Raw|ConvertFrom-Json;if($x){return $x}}catch{}};return Discover}
if($Command -eq 'discover'){$x=Discover;if($x){$x|ConvertTo-Json -Depth 6}else{'{"status":"NOT_FOUND"}'};exit}
$x=Spec
if(-not$x){Log 'NOT_FOUND';'{"status":"NOT_FOUND"}';exit 2}
if($Command -eq 'status'){
  if($x.mode -eq 'service'){$s=Get-Service $x.name -ErrorAction SilentlyContinue;[ordered]@{mode='service';name=$x.name;status=if($s){$s.Status.ToString()}else{'MISSING'};path=$x.path}|ConvertTo-Json}
  else{$p=Get-CimInstance Win32_Process -ErrorAction SilentlyContinue|Where-Object{$_.ExecutablePath -eq $x.path};[ordered]@{mode='process';name=$x.name;running=[bool]$p;path=$x.path}|ConvertTo-Json};exit
}
if($Command -eq 'restart'){
  if($x.mode -eq 'service'){
    try{$s=Get-Service $x.name -ErrorAction Stop;if($s.Status -eq 'Running'){Restart-Service $x.name -Force -ErrorAction Stop}else{Start-Service $x.name -ErrorAction Stop};Log "PASS service $($x.name)";'{"status":"PASS","mode":"service"}'}catch{Log("FAIL service "+$_.Exception.Message);'{"status":"FAIL","mode":"service"}';exit 1}
  } else {
    try{
      Get-CimInstance Win32_Process -ErrorAction SilentlyContinue|Where-Object{$_.ExecutablePath -eq $x.path}|ForEach-Object{Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue}
      Start-Sleep -Milliseconds 700
      Start-Process -FilePath $x.path -WindowStyle Hidden
      Start-Sleep -Seconds 2
      $alive=Get-CimInstance Win32_Process -ErrorAction SilentlyContinue|Where-Object{$_.ExecutablePath -eq $x.path}
      if(-not$alive){throw 'Process did not appear after restart'}
      Log "PASS process $($x.path)";'{"status":"PASS","mode":"process"}'
    }catch{Log("FAIL process "+$_.Exception.Message);'{"status":"FAIL","mode":"process"}';exit 1}
  }
}
