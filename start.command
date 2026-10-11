#!/bin/bash
# macOS / Linux: 3つのツールをまとめて起動し、入口の画面を開く(詳しくは src/home/README.txt)。初回だけ: chmod +x start.command
cd "$(dirname "$0")" || exit 1
exec python3 src/app/server.py "$@"
