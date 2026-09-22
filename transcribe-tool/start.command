#!/bin/bash
# macOS / Linux launcher. First time only: chmod +x start.command
cd "$(dirname "$0")" || exit 1
if [ -x .venv/bin/python ]; then exec .venv/bin/python serve.py; fi
exec python3 serve.py
