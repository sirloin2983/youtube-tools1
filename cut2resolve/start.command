#!/bin/bash
# macOS / Linux 用の起動
cd "$(dirname "$0")" || exit 1
python3 serve.py
code=$?
echo
echo "サーバーが終了しました(終了コード $code)"
read -r -p "Enter で閉じる"
