import subprocess, json
procs = subprocess.run(['powershell', '-Command', 
    'Get-WmiObject -Class Win32_Process | Where-Object { $_.Name -eq "python.exe" } | Select-Object ProcessId, CommandLine'],
    capture_output=True, text=True, timeout=10)
print(procs.stdout)
