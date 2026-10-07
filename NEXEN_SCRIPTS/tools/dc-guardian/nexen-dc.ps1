param([ValidateSet("discover","status","restart")][string]$Command="status")
$ErrorActionPreference="Stop"
$StateDir="H:\NEXEN\state\desktop-commander"
$LogDir="H:\NEXEN\logs\desktop-commander"
$State=Join-Path $StateDir "launch.json"
$Log=Join-Path $LogDir "guardian.log"
New-Item -ItemType Directory -Force $StateDir,$LogDir | Out-Null

function Log($m){ Add-Content $Log ("{0} {1}" -f (Get-Date -Format o),$m) }

function Discover {
  $services=Get-CimInstance Win32_Service -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -match 'desktop.*commander|commander.*desktop' -or
    $_.DisplayName -match 'desktop.*commander|commander.*desktop' -or
    $_.PathName -match 'desktop.*commander|commander.*desktop'
  }
  if($services){
    $s=$services | Select-Object -First 1
    $o=[ordered]@{mode="service";name=$s.Name;display=$s.DisplayName;path=$s.PathName;discovered=(Get-Date).ToString("o")}
    $o | ConvertTo-Json | Set-Content $State -Encoding UTF8
    return $o
  }

  $procs=Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -match 'desktop.*commander|commander.*desktop' -or
    $_.CommandLine -match 'desktop.*commander|commander.*desktop'
  } | Where-Object { $_.ExecutablePath }
  if($procs){
    $p=$procs | Select-Object -First 1
    $o=[ordered]@{mode="process";name=$p.Name;path=$p.ExecutablePath;commandLine=$p.CommandLine;discovered=(Get-Date).ToString("o")}
    $o | ConvertTo-Json | Set-Content $State -Encoding UTF8
    return $o
  }

  $roots=@("$env:LOCALAPPDATA\Programs","$env:LOCALAPPDATA","$env:APPDATA","$env:ProgramFiles",${env:ProgramFiles(x86)}) | Where-Object {$_ -and (Test-Path $_)}
  foreach($r in $roots){
    $hit=Get-ChildItem $r -File -Filter *.exe -Recurse -Depth 3 -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -match 'desktop.*commander|commander.*desktop' } | Select-Object -First 1
    if($hit){
      $o=[ordered]@{mode="process";name=$hit.Name;path=$hit.FullName;commandLine=$hit.FullName;discovered=(Get-Date).ToString("o")}
      $o | ConvertTo-Json | Set-Content $State -Encoding UTF8
      return $o
    }
  }
  return $null
}

function ReadSpec {
  if(Test-Path $State){ try { return Get-Content $State -Raw | ConvertFrom-Json } catch {} }
  return Discover
}

if($Command -eq "discover"){
  $x=Discover
  if($x){$x|ConvertTo-Json -Depth 4}else{'{"status":"NOT_FOUND"}'}
  exit
}

$spec=ReadSpec
if(-not $spec){
  Log "NOT_FOUND no Desktop Commander service/process/executable discovered"
  '{"status":"NOT_FOUND"}'
  exit 2
}

if($Command -eq "status"){
  if($spec.mode -eq "service"){
    $s=Get-Service -Name $spec.name -ErrorAction SilentlyContinue
    [ordered]@{mode="service";name=$spec.name;status=if($s){$s.Status.ToString()}else{"MISSING"};path=$spec.path}|ConvertTo-Json
  } else {
    $p=Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {$_.ExecutablePath -eq $spec.path}
    [ordered]@{mode="process";name=$spec.name;running=[bool]$p;path=$spec.path}|ConvertTo-Json
  }
  exit
}

if($Command -eq "restart"){
  if($spec.mode -eq "service"){
    try {
      $s=Get-Service -Name $spec.name -ErrorAction Stop
      if($s.Status -eq "Running"){ Restart-Service -Name $spec.name -Force -ErrorAction Stop }
      else { Start-Service -Name $spec.name -ErrorAction Stop }
      Log "PASS service restart/start $($spec.name)"
      '{"status":"PASS","mode":"service"}'
    } catch {
      Log "FAIL service restart $($_.Exception.Message)"
      '{"status":"FAIL","mode":"service"}'
      exit 1
    }
  } else {
    try {
      Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {$_.ExecutablePath -eq $spec.path} |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
      Start-Sleep -Milliseconds 600
      Start-Process -FilePath $spec.path -WindowStyle Hidden
      Start-Sleep -Seconds 2
      $alive=Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {$_.ExecutablePath -eq $spec.path}
      if(-not $alive){ throw "Process did not appear after restart." }
      Log "PASS process restart $($spec.path)"
      '{"status":"PASS","mode":"process"}'
    } catch {
      Log "FAIL process restart $($_.Exception.Message)"
      '{"status":"FAIL","mode":"process"}'
      exit 1
    }
  }
}
