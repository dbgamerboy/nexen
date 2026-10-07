@echo off
rem Double-click: fixes access to 05_AI folder(s). Optional: FIX-05_AI-ACCESS.cmd "F:\exact\path\05_AI"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0FIX-05_AI-ACCESS.ps1" %*
