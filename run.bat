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

if not exist .env (
  echo No .env found - copying .env.example (edit it before a live run).
  copy .env.example .env
)

echo Starting Viagogo Listing Automation (DRY_RUN is the safe default)...
python app.py
