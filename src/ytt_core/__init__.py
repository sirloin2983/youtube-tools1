"""ytt_core — 切り抜きスタジオ・文字起こしツール・入口(home/)で共通に使う部品(統合計画の段階2。docs/design/integration-plan.md)。

Python 標準ライブラリだけで動く。各ツールは、自分のフォルダの1つ上(リポジトリ直下)にあるこのフォルダを読み込む
(一時フォルダにツールを写して動かすテストなどでは、環境変数 YTT_CORE_DIR に「ytt_core を含むフォルダ」を入れる)。

- fsio     … 原子的な書き込み(Windows の一時的なロックはやり直す)・大きさの上限つきの JSON の読み込み・ネットワークパスの判定
- runtime  … 実行中のポートの共有(.runtime/<ツールID>.json)・/api/ping の問い合わせ・/api/siblings の中身
- schemas  … 受け渡しの形式(docs/spec/pipeline.md)の名前と、youtube-tools-clip/v1 の組み立て・検証
- httpsec  … ローカルサーバーの安全検査(Host・Origin・Sec-Fetch-*)と画面の応答ヘッダー
- tools    … ffmpeg などの外部プログラムの場所(環境変数での上書きつき)
- evaldata … 友人用 文字起こし簡易版の評価データ(送る用 zip)の形式・記号の規則・パスの除去・届いた zip の検証(git の履歴(679ff01 以前)の docs/plan/friend-lite-plan.md。
             簡易版は 2026-10-04 に消した。形式と取り込み dev/eval_import.py は残す)

cut2resolve は統合の対象外(docs/design/integration-plan.md)なので、ここを使わない。
ここを変えるときは `python -m unittest ytt_core/tests/test_ytt_core.py` と、スタジオ・文字起こし・入口のテストをすべて通すこと。
"""
VERSION = "1.2.0"
