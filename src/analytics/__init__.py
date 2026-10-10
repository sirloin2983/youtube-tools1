"""analytics — チャンネルの分析と日報・週報・月報(設計 plan/analytics-daily-report.md)。

入口(src/home/launch.py)が /analytics/ で受け持つ(取り込むツールではなく、録画の /live/ と同じ形)。
データは既存の「Youtube日次」のブックマーク(iPhone の Safari で Studio を開いてタップ)が Google Drive に置く raw を、
Apps Script の連携(gas/Code.gs)から合言葉付きで受け取る。分析した結果は同じ連携へ送り返し、LINE に届く。

部品:
- timeutil: 日付の定義(太平洋時間の日・日本時間・公開からの経過)を 1 か所に
- data: raw → 形をそろえたデータ(検査つき)
- calc: 計算(確定・YPP・見込みと答え合わせ・初動・異変・週と月の集計・効き目の表)
- render: LINE の文面と HTML
- bridge: Apps Script の連携との通信
- service: 入口の中で動く見張り・画面と API
"""
from ytt.version import VERSION  # noqa: E402,F401  全体の版(ytt/version.py)
