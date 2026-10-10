"""全体の版の 1 か所(役割で組み直す RS5-E。2026-10-10。決定 plan/decisions.md の 3-28)。

ホーム・スタジオ・編集・cut2resolve・録画・分析・パックの部品・ytt のすべてが、この VERSION を読む。
正式な 1.0.0 は、組み直しのあとのコードと画面の見直しが済んでから。それまでは仮の 0.56.0(ホームの番号を継いだ)。

版を上げるとき: この 1 行(と README.txt の見出し)だけを直す。画面(JS)に版の文字は書かない。
入口が画面(HTML)を返すとき、ディスクのこのファイルを読み直した値を <meta name="ytt-version"> に入れる(mount.py)。
画面はそれを APP_VERSION として使い、動いているサーバーの /api/ping の version と比べる = 起動し直し忘れの検出(赤い帯 UIKit.restart)。

標準ライブラリだけ(単独のコマンドからも読める)。
"""
import os
import re

VERSION = "0.58.0"

_RE = re.compile(r'^VERSION\s*=\s*"([^"]+)"', re.M)


def on_disk(src_root=None):
    """ディスクにあるこのファイルの版(動いているプロセスが覚えている VERSION ではなく、今のコードの版)。読めなければ ""。
    起動し直し忘れ(コードの版と動いているサーバーの版が違う)を見分けるため。src_root 省略時はこのファイルの場所"""
    path = os.path.join(src_root, "ytt", "version.py") if src_root else os.path.abspath(__file__)
    try:
        with open(path, "r", encoding="utf-8") as f:
            m = _RE.search(f.read())
        return m.group(1) if m else ""
    except (OSError, UnicodeError):
        return ""
