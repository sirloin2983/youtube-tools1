#!/bin/bash
# macOS / Linux installer. First time only: chmod +x install.command
cd "$(dirname "$0")" || exit 1
python3 -m venv ../src/editor/.venv && ../src/editor/.venv/bin/python -m pip install -U -r requirements.txt
echo
echo "Done. Run start.command in the parent folder next."
