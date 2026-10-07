$ws = New-Object -ComObject WScript.Shell
$sd = $env:APPDATA + "\Microsoft\Windows\Start Menu\Programs\Startup"
$s = $ws.CreateShortcut($sd + "\NEXEN-Bots.lnk")
$s.TargetPath = "cmd.exe"
$s.Arguments = "/c start /B "" H:\NEXEN\v1\app\startup-bots.bat"
$s.WorkingDirectory = "H:\NEXEN\v1\app"
$s.Save()
Write-Host "Startup shortcut created"