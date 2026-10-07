# Fix "Access denied" on the 05_AI folder(s): take ownership + give YOUR account Full Control (SYSTEM keeps access).
# Nothing is deleted or moved. Current permissions are backed up first so it can be undone:
#   icacls "<parent folder>" /restore "<backup file>"
# Run: double-click FIX-05_AI-ACCESS.cmd (asks for admin once).  Exact path instead of search:  FIX-05_AI-ACCESS.cmd "F:\some\05_AI"
param([string]$Path)
$ErrorActionPreference = 'Continue'
$me = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if(-not $isAdmin){
  $args2 = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
  if($Path){ $args2 += " -Path `"$Path`"" }
  Start-Process powershell.exe -Verb RunAs -ArgumentList $args2
  exit
}
$logDir = if(Test-Path H:\NEXEN){ 'H:\NEXEN\logs' } else { "$env:USERPROFILE\NEXEN-logs" }
New-Item -ItemType Directory -Force $logDir | Out-Null
$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$receipt = Join-Path $logDir '05_AI-ACCESS-FIX.txt'
function R($m){ $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m"; Write-Host $line; Add-Content $receipt $line }

if($Path){ $targets = @($Path) } else {
  Write-Host "Searching for folders named 05_AI (F:, H:, E:, C:\Users)... this can take a minute."
  $roots = @('F:\','H:\','E:\',"$env:SystemDrive\Users") | Where-Object { Test-Path $_ }
  $targets = foreach($r in $roots){
    Get-ChildItem $r -Directory -Recurse -Depth 4 -Force -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -ieq '05_AI' } | ForEach-Object FullName
  }
  $targets = @($targets | Sort-Object -Unique)
}
if(-not $targets){
  Write-Host "No 05_AI folder found. Run again with the exact path:  FIX-05_AI-ACCESS.cmd `"X:\path\to\05_AI`""
  Read-Host 'Press Enter to close'; exit 1
}
Write-Host "`nWill fix access for $me on:"; $targets | ForEach-Object { Write-Host "  $_" }
if(-not $Path -and (Read-Host "`nFix these? (Y/N)") -notmatch '^[Yy]'){ exit }   # exact path given = already confirmed

R "=== run $ts as $me ==="
foreach($t in $targets){
  if(-not (Test-Path -LiteralPath $t)){ R "SKIP not found: $t"; continue }
  $backup = Join-Path $logDir ("05_AI-acl-backup-$ts-" + ($t -replace '[:\\ ]','_') + '.txt')
  icacls "$t" /save "$backup" /T /C /Q | Out-Null
  R "backup acl -> $backup (exit $LASTEXITCODE)"
  takeown /F "$t" /R /D Y | Out-Null
  R "takeown $t (exit $LASTEXITCODE)"
  icacls "$t" /grant "${me}:(OI)(CI)F" /T /C /Q | Out-Null
  R "icacls grant $me Full $t (exit $LASTEXITCODE)"
  icacls "$t" /grant "*S-1-5-18:(OI)(CI)F" /T /C /Q | Out-Null
  R "icacls grant SYSTEM Full $t (exit $LASTEXITCODE)"
  try { $n = @(Get-ChildItem -LiteralPath $t -Force -ErrorAction Stop).Count; R "CHECK OK: $t lists $n items" }
  catch { R "CHECK FAILED: $t - $($_.Exception.Message)" }
}
R "=== done. receipt: $receipt ==="
Read-Host 'DONE. Press Enter to close'
