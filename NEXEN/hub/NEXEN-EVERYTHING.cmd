@echo off
setlocal
chcp 65001 >nul
"H:\NEXEN_RUNTIME\python-recovery\Scripts\python.exe" -B "%~dp0nexen_everything.py" %*
