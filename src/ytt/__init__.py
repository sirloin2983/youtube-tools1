"""ytt — 基盤(役割で組み直す計画 notes:plan/done/role-restructure.md の 3 節。どの層からも読める)。

Python 標準ライブラリだけで動く。読む側は src/ を sys.path に入れて `from ytt import fsio` のように読む(層のパッケージの中は兄弟を相対で)。
この __init__ は説明と定数だけ(import しない。dev/tests/test_layering.py が検査)。

- fsio      … 原子的な書き込み(Windows の一時的なロックはやり直す)・大きさの上限つきの JSON の読み込み(読めなければ既定値 read_json_or も)・
              ネットワークパスの判定・静かに消す・更新日時のキャッシュ StampCache・ログの回し rotate・フォルダの中か is_inside・フォルダの大きさ dir_size
- runtime   … 実行中のポートの共有(.runtime/<ツールID>.json)・/api/ping の問い合わせ・/api/siblings の中身
- schemas   … 受け渡しの形式(notes:docs/spec/pipeline.md)の名前・youtube-tools-clip/v1 の組み立てと検証・途中のファイルの置き場所(作業用/)
- httpsec   … ローカルサーバーの安全検査(Host・Origin・Sec-Fetch-*・合言葉 token_ok)と画面の応答ヘッダー・JSON の本文 read_json_body・
              動画の Range 応答 send_file・使用中のポートに bind しないサーバー ExclusiveServer
- datadir   … 作業データの置き場所(リポジトリの外)
- layout    … リポジトリの中のフォルダ名(フォルダ名を知る場所はここだけ)・テストが写す共通のコードの一覧
- jobs      … 重い処理の同時実行の上限(SLOTS)
- colors    … 配信者の名前 → メンバーカラー(ホロカラーの一覧を読むだけ)
- loudness  … 聞こえ方の音量(LUFS)をそろえる決まり
- normalize … 素材を 30fps にそろえる(ffprobe で調べる・ffmpeg で作り直す)
- pick      … PC の「ファイルを選ぶ」「フォルダを選ぶ」の窓
- tools     … ffmpeg などの外部プログラムの場所と版、子プロセスの小道具(窓を出さない・優先度・動かして止める run / run_progress・
              孫ごと止める kill_tree・親が落ちても子を残さない KillJob・python_exe・メモリ・例外の短い理由 why)
- names     … 書き出しの名前の規則(置き場所のフォルダ・持ち主の印 .studio-id・1 本の名前・書きかけ .partial。スタジオの書き出しと入口のライブの書き出しが読む)
- recproto  … 録画元との約束(録画元・録画・セグメントの id の形・UTC の時刻の書き方・YouTube の動画の id。録画の部品・入口・配信中の検出のワーカーが読む)
- settings  … 設定ファイル(JSON の辞書)の読み書きの決まり SettingsFile(壊れていれば既定で動き、書く前に .broken-<日時> へ退避・原子的に書く・大きさの上限・
              節を置き換える / 節の鍵を直す / 最上位の鍵を直す)。ホームの prefs.json・スタジオの settings-ui.json・編集の settings.json が読む

ここを変えるときは `python -m unittest src/ytt/tests/test_ytt_core.py src/ytt/tests/test_normalize.py src/ytt/tests/test_settings.py` と、
使っている各ツールのテスト(notes:docs/spec/code.md の 6 の表)を通すこと。
"""
# 版は全体で 1 つ = ytt/version.py の VERSION(__init__ は import しない決まり)。
