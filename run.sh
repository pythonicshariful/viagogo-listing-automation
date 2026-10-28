#!/usr/bin/env bash
# Viagogo Listing Automation — Linux / macOS launcher.
# Creates a venv if missing, installs deps, then starts the Flask UI.
# Usage: ./run.sh            (dry-run, safe default)
#        ./run.sh --install-browser   (also install Playwright Chromium)
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d venv ]; then
  echo "Creating virtualenv..."
  python3 -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt

if [ "${1:-}" = "--install-browser" ]; then
  python -m playwright install chromium
fi

# v1.3.0: NO .env file is needed — every setting lives in the dashboard
# (open http://127.0.0.1:5002 -> Settings). .env is only an optional
# override for advanced users; see .env.example.
echo "Starting Viagogo Listing Automation (dry-run is the safe default)..."
exec python app.py
