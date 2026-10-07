@echo off
rem Starts the hub (original MARVIN HUD server, chat, money lanes) on http://127.0.0.1:8788/
cd /d H:\NEXEN\hub
"H:\NEXEN_RUNTIME\python-recovery\Scripts\python.exe" -B nexen.py serve
