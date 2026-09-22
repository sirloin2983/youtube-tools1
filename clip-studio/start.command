#!/bin/bash
# macOS / Linux launcher.
cd "$(dirname "$0")" || exit 1
python3 serve.py
code=$?
echo
echo "サーバーが終了しました(終了コード $code)。ログ: studio.log(このフォルダ内)"
echo "自分で止めていない場合は、上のメッセージと studio.log を教えてください。"
read -r -p "Enter で閉じる"
