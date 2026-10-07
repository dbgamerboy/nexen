@echo off
setlocal
set PY=H:\NEXEN_RUNTIME\python-recovery\Scripts\python.exe
set T=%~dp0marvin_train.py
cd /d "%~dp0"
:menu
cls
echo ==============================================
echo   MARVIN HEAVY TRAINING   (120 questions)
echo ==============================================
"%PY%" H:\NEXEN-ENTERPRISE\Apps\NEXEN\companion\nexen-next\blocker.py
echo ----------------------------------------------
echo   1  Self-test (checks the module, no password)
echo   2  Ask live MARVIN all 120 questions
echo   3  Ask live MARVIN only the brutal ones (difficulty 5)
echo   4  Ask live MARVIN only the ones he failed last time
echo   5  Show the latest report
echo   6  Make fine-tune files (chat set and right/wrong pairs)
echo   7  Open the question list and answer key
echo   8  Open NEXEN NEXT (the full app)
echo   0  Exit
echo.
echo   Options 2 to 4 ask for your MARVIN password. It is typed hidden and never saved.
echo   MARVIN must be running first. STOP and PAUSE stay on, this only asks questions.
echo.
set C=
set /p C=Pick a number:
if not defined C exit /b 0
if "%C%"=="1" "%PY%" "%T%" selftest & pause & goto menu
if "%C%"=="2" "%PY%" "%T%" run --target marvin & "%PY%" "%T%" report & pause & goto menu
if "%C%"=="3" "%PY%" "%T%" run --target marvin --min-diff 5 & "%PY%" "%T%" report & pause & goto menu
if "%C%"=="4" "%PY%" "%T%" run --target marvin --ids-file results\drill-ids.txt & "%PY%" "%T%" report & pause & goto menu
if "%C%"=="5" "%PY%" "%T%" report & pause & goto menu
if "%C%"=="6" "%PY%" "%T%" sft & "%PY%" "%T%" dpo & pause & goto menu
if "%C%"=="7" "%PY%" "%T%" md & start "" notepad "%~dp0questions\QUESTIONS.md" & start "" notepad "%~dp0questions\ANSWER-KEY.md" & goto menu
if "%C%"=="8" start "" "H:\NEXEN_RUNTIME\python-recovery\Scripts\pythonw.exe" "H:\NEXEN-ENTERPRISE\Apps\NEXEN\companion\nexen-next\nexen_next.py" & goto menu
if "%C%"=="0" exit /b 0
goto menu
