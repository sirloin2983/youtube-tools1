"""ytt_core — 入口(home/)・切り抜きスタジオ・「編集」・cut2resolve・録画の部品が共通に使う部品(統合計画の段階2。docs/design/integration-plan.md)。

Python 標準ライブラリだけで動く。各ツールは、自分のフォルダの1つ上(src/)にあるこのフォルダを読み込む
(一時フォルダにツールを写して動かすテストなどでは、環境変数 YTT_CORE_DIR に「ytt_core を含むフォルダ」を入れる)。

- fsio      … 原子的な書き込み(Windows の一時的なロックはやり直す)・大きさの上限つきの JSON の読み込み・ネットワークパスの判定・静かに消す
- runtime   … 実行中のポートの共有(.runtime/<ツールID>.json)・/api/ping の問い合わせ・/api/siblings の中身
- schemas   … 受け渡しの形式(docs/spec/pipeline.md)の名前・youtube-tools-clip/v1 の組み立てと検証・途中のファイルの置き場所(作業用/)
- httpsec   … ローカルサーバーの安全検査(Host・Origin・Sec-Fetch-*)と画面の応答ヘッダー
- datadir   … 作業データの置き場所(リポジトリの外)と、以前の場所からのコピー
- layout    … リポジトリの中のフォルダ名(フォルダ名を知る場所はここだけ)
- txindex   … 文字起こしの文書を他のツールから読む・切り抜きとの紐づけ・パックの有無(規則はここだけ)
- jobs      … 重い処理の同時実行の上限(SLOTS)
- colors    … 配信者の名前 → メンバーカラー(ホロカラーの一覧を読むだけ)
- loudness  … 聞こえ方の音量(LUFS)をそろえる決まり
- normalize … 素材を 30fps にそろえる(ffprobe で調べる・ffmpeg で作り直す)
- excite    … 盛り上がりの式(アーカイブの解析と配信中の検出が同じ式を読む。線 D の L1)・配信中の 1 秒ずつの計算 Online・候補の帳簿 PeakBook
- pick      … PC の「ファイルを選ぶ」「フォルダを選ぶ」の窓
- tools     … ffmpeg などの外部プログラムの場所と、子プロセスの小道具(窓を出さない・止める・親が落ちても子を残さない KillJob)
- evaldata  … 友人用 文字起こし簡易版の評価データ(送る用 zip)の形式・記号の規則・届いた zip の検証(git の履歴(679ff01 以前)の docs/plan/friend-lite-plan.md。
              簡易版は 2026-10-04 に消した。形式と取り込み dev/eval_import.py は残す)

cut2resolve の単独のコマンドは ytt_core が無くても動く(WORK_DIR を自分でも持つ。音量の計算だけ読みに来る)。serve.py は読む。
ここを変えるときは `python -m unittest src/ytt_core/tests/test_ytt_core.py src/ytt_core/tests/test_evaldata.py src/ytt_core/tests/test_normalize.py src/ytt_core/tests/test_excite.py` と、
使っている各ツールのテスト(AGENTS.md の表)を通すこと。
"""
VERSION = "1.2.0"
