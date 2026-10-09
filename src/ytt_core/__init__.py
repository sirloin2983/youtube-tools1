"""ytt_core — 入口(home/)・切り抜きスタジオ・「編集」・cut2resolve・録画の部品が共通に使う部品(統合計画の段階2。docs/design/integration-plan.md)。

Python 標準ライブラリだけで動く。各ツールは、自分のフォルダの1つ上(src/)にあるこのフォルダを読み込む
(一時フォルダにツールを写して動かすテストなどでは、環境変数 YTT_CORE_DIR に「ytt_core を含むフォルダ」を入れる)。

- fsio      … 原子的な書き込み(Windows の一時的なロックはやり直す)・大きさの上限つきの JSON の読み込み(読めなければ既定値 read_json_or も)・
              ネットワークパスの判定・静かに消す・更新日時のキャッシュ StampCache・ログの回し rotate・フォルダの中か is_inside・フォルダの大きさ dir_size
- runtime   … 実行中のポートの共有(.runtime/<ツールID>.json)・/api/ping の問い合わせ・/api/siblings の中身
- schemas   … 受け渡しの形式(docs/spec/pipeline.md)の名前・youtube-tools-clip/v1 の組み立てと検証・途中のファイルの置き場所(作業用/)
- httpsec   … ローカルサーバーの安全検査(Host・Origin・Sec-Fetch-*・合言葉 token_ok)と画面の応答ヘッダー・JSON の本文 read_json_body・
              動画の Range 応答 send_file・使用中のポートに bind しないサーバー ExclusiveServer
- datadir   … 作業データの置き場所(リポジトリの外)と、以前の場所からのコピー
- layout    … リポジトリの中のフォルダ名(フォルダ名を知る場所はここだけ)
- txindex   … 文字起こしの文書を他のツールから読む・切り抜きとの紐づけ・パックの有無(規則はここだけ)
- jobs      … 重い処理の同時実行の上限(SLOTS)
- colors    … 配信者の名前 → メンバーカラー(ホロカラーの一覧を読むだけ)
- loudness  … 聞こえ方の音量(LUFS)をそろえる決まり
- normalize … 素材を 30fps にそろえる(ffprobe で調べる・ffmpeg で作り直す)
- excite    … 盛り上がりの式(アーカイブの解析と配信中の検出が同じ式を読む。線 D の L1)・配信中の 1 秒ずつの計算 Online・候補の帳簿 PeakBook
- pick      … PC の「ファイルを選ぶ」「フォルダを選ぶ」の窓
- tools     … ffmpeg などの外部プログラムの場所と版、子プロセスの小道具(窓を出さない・優先度・動かして止める run / run_progress・
              孫ごと止める kill_tree・親が落ちても子を残さない KillJob・python_exe・メモリ・例外の短い理由 why)
- names     … 書き出しの名前の規則(置き場所のフォルダ・持ち主の印 .studio-id・1 本の名前・書きかけ .partial。スタジオの書き出しと入口のライブの書き出しが読む)
- recproto  … 録画元との約束(録画元・録画・セグメントの id の形・UTC の時刻の書き方・YouTube の動画の id。録画の部品・入口・配信中の検出のワーカーが読む)
- settings  … 設定ファイル(JSON の辞書)の読み書きの決まり SettingsFile(壊れていれば既定で動き、書く前に .broken-<日時> へ退避・原子的に書く・大きさの上限・
              節を置き換える / 節の鍵を直す / 最上位の鍵を直す)。ホームの prefs.json・スタジオの settings-ui.json・編集の settings.json が読む(設定を 1 つに S4)
- evaldata  … 友人用 文字起こし簡易版の評価データ(送る用 zip)の形式・記号の規則・届いた zip の検証(git の履歴(679ff01 以前)の docs/plan/friend-lite-plan.md。
              簡易版は 2026-10-04 に消した。形式と取り込み dev/eval_import.py は残す)

cut2resolve の単独のコマンドは ytt_core が無くても動く(WORK_DIR を自分でも持つ。音量の計算だけ読みに来る)。serve.py は読む。
ここを変えるときは `python -m unittest src/ytt_core/tests/test_ytt_core.py src/ytt_core/tests/test_evaldata.py src/ytt_core/tests/test_normalize.py src/ytt_core/tests/test_excite.py src/ytt_core/tests/test_settings.py` と、
使っている各ツールのテスト(AGENTS.md の表)を通すこと。
"""
VERSION = "1.6.0"   # 1.6.0(2026-10-09): 設定ファイルの読み書きの共通部品 settings(SettingsFile・SettingsError・SettingsTooLarge)を足した(設定を 1 つに S4。home/prefs.py・studio/store.py・editor/ed_learn.py が使う)
# 1.5.0(2026-10-09): 使われていない公開の関数・定数を消した(コードの見直しの F。evaldata の書き出し側 RULES・scrub_paths・zip_name・safe_url・overlap・raw_links、colors.rgb01、loudness.db_to_pct、normalize.TARGET、excite.PEAK_STATES)
# 1.4.0(2026-10-09): ツールをまたいだ規則 names・recproto を足した(T8)。fsio の StampCache.peek/set・read_json_or(allow_nan)・write_json(mode)、httpsec.send_head(cache)、tools.OUT_TIME を公開
# 1.3.0(2026-10-09): 各ツールの写しを吸い上げる小道具を足した(fsio・tools・httpsec・schemas・datadir.studio_out_dir・excite の定数)
