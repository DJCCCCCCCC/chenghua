@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Missing project environment. See README.md.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "chenghua_app.py"
