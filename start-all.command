#!/bin/bash
# macOS / Linux: 3つのツールをまとめて起動し、入口の画面を開く(詳しくは app/README.txt)。初回だけ: chmod +x start-all.command
cd "$(dirname "$0")" || exit 1
exec python3 app/launch.py "$@"
