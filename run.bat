@echo off
REM Viagogo Listing Automation — Windows launcher.
REM Creates a venv if missing, installs deps, then starts the Flask UI.
REM Usage: run.bat
REM        run.bat install-browser   (also install Playwright Chromium)
setlocal
cd /d %~dp0

if not exist venv (
  echo Creating virtualenv...
  python -m venv venv
)
call venv\Scripts\activate.bat
python -m pip install --upgrade pip -q
pip install -r requirements.txt

if "%1"=="install-browser" (
  python -m playwright install chromium
)

REM v1.3.0: NO .env file is needed - every setting lives in the dashboard
REM (open http://127.0.0.1:5002 -^> Settings). .env is only an optional
REM override for advanced users; see .env.example.
echo Starting Viagogo Listing Automation (dry-run is the safe default)...
python app.py
