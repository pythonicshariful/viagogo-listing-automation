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

if [ ! -f .env ]; then
  echo "No .env found — copying .env.example (edit it before a live run)."
  cp .env.example .env
fi

echo "Starting Viagogo Listing Automation (DRY_RUN is the safe default)..."
exec python app.py
