#!/bin/bash
# macOS / Linux: installs the speaker-identification parts. First time only: chmod +x install-diarize.command
cd "$(dirname "$0")" || exit 1
if [ -x ../editor/.venv/bin/python ]; then PY=../editor/.venv/bin/python; else PY=python3; fi
"$PY" -m pip install -U sherpa-onnx numpy
echo
echo "Done. Restart the tools (start.command in the parent folder)."
