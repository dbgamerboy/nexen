@echo off
rem Starts the NEXEN app (HUD, approvals, module bridge) on http://127.0.0.1:8794/ . Add --no-loop to skip the learning loop.
set NEXEN_DATA=H:\NEXEN_DATA\nexen
set NEXEN_MODBRIDGE_DIR=H:\NEXEN_MODULES\_curated
"H:\NEXEN_RUNTIME\python-recovery\Scripts\python.exe" -B H:\NEXEN\run_nexen.py serve --port 8794 --no-loop

