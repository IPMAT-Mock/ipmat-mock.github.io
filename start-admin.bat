@echo off
REM IPMAT Admin - starts the local server and opens it in your browser.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv not found. Run once:  py -m venv .venv ^&^& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
  pause
  exit /b 1
)
echo Starting IPMAT Admin on http://127.0.0.1:5057 ...
start "" "http://127.0.0.1:5057"
".venv\Scripts\python.exe" app\server.py
pause
