@echo off
set OLLAMA_MODELS=H:\NEXEN\models\ollama
taskkill /F /IM ollama.exe 2>nul
taskkill /F /IM "ollama app.exe" 2>nul
timeout /t 2 /nobreak >nul
start "" "%USERPROFILE%\AppData\Local\Programs\Ollama\ollama.exe" serve
timeout /t 5 /nobreak >nul
ollama list
