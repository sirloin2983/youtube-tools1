# 作業データの置き場所(統合計画の段階4・2026-09-26)

作業データ(個人データ・設定・キャッシュ・記録)を**リポジトリの外**に置く。リポジトリには、コードと資料だけを残す。

## 決まったこと(ユーザー 2026-09-26)
- 置き場所: **`%LOCALAPPDATA%\youtube-tools\`**(例 `C:\Users\you11\AppData\Local\youtube-tools\`)。
  Windows のアプリのデータの定番の場所で、OneDrive で同期されない(個人データと 2GB を超えるキャッシュがクラウドに上がらない)
- 範囲: **全部**(3ツールの作業データ・設定・キャッシュ・ログ、話者判別のモデル、入口の記録)
- 移し方: **コピー**。以前の場所(各ツールのフォルダの中)のデータは消さない。消すのはユーザーが新しい場所で確かめてから

## フォルダの中身
| フォルダ | 中身 | 以前の場所から写すもの |
| --- | --- | --- |
| `studio\` | data.json(.bak)・feedback.jsonl(.old)・registry.json・config.json(YouTube の API キー)・settings(-ui).json・cache\(チャット 約2.2GB など)・archive\・studio.log・work\(解析の一時ファイル)・exports\(既定の書き出し先) | 左のうち、ログと work 以外 |
| `transcribe\` | transcripts\(.bak・.hist の控えを含む)・dataset\・evals\・models\diar\(話者判別のモデル)・settings.json・learn-feedback.json・eval-baselines.json・serve.log・worker.log・.running.json | 左のうち、ログと .running.json 以外 |
| `cut2resolve\` | work\uploads\(画面にドロップしたファイルの一時置き場。起動のたびに消える)・work\serve.log | なし(一時的なものだけ) |
| `app\` | logs\(入口の launcher.log と各ツールの出力・画面のエラーの記録 client-errors.jsonl(段階7-0))・cases.json(案件の状態・メモ。下の「案件ファイル」)・settings.json(`"window"`: 窓で開くか。段階7-3)・browser-profile\(窓(Edge のアプリモード)の専用のプロファイル。閲覧の記録・Cookie・キャッシュが入り、数十〜数百 MB になる。消すと窓の設定・ログインが初期に戻るだけ) | なし |
| 各フォルダの `.migrated.json` | いつ・どこから・何を写したか | — |

- 切り抜きスタジオの書き出し先: 設定で決めていればそのまま。以前の既定(`clip-studio\exports`)を使っていた場合は、そこを使い続ける(動画が2か所に分かれないように)
- パックの出力(cut2resolve の `<動画名>_pack`)・スタジオの書き出した動画は、これまでどおり動画の隣・指定したフォルダ(作業データではない)

## 仕組み(`ytt_core/datadir.py`)
- `data_root()`: 環境変数 `YTT_DATA_DIR` → Windows は `%LOCALAPPDATA%\youtube-tools`(macOS `~/Library/Application Support/youtube-tools`、それ以外 `$XDG_DATA_HOME/youtube-tools`)。
  `YTT_DATA_DIR=inplace` は以前と同じ「各ツールのフォルダの中」(テスト・元に戻したいとき用)
- `prepare(ツールID, 以前の場所, 写す名前)`: 各ツールが起動時に1回呼ぶ
  - 項目ごとに「一時的な名前(`.part-<pid>`)へコピー → 大きさとファイル数が元と同じか確かめる → 本来の名前へ改名」。途中で止まっても半端なものを本物として使わない(残った `.part-` は次の起動で消す)
  - 新しい場所にすでにある項目は上書きしない
  - 空き容量が足りない(写す量 + 256MB)・コピーに失敗したときは移さず、そのツールは**以前の場所のまま**動く(黒い画面に警告)。今回写した分は消し、次の起動で写し直す(以前の場所のまま動く間に古くなるため)
  - 全部終わったら `.migrated.json`。次からは写さない(新しい場所が正)
  - シンボリックリンクはたどらない
- 各ツール: スタジオ `serve._data_home()`(環境変数 `STUDIO_HOME` があればそれ)、文字起こし `serve.choose_data_dir()` / `set_data_dir()`(ワーカーには `TRANSCRIBE_DATA_DIR`)、
  cut2resolve `serve._choose_work_dir()`、入口 `launch.logs_dir_for()`。どれも「テスト・入口が先に場所を決めていれば、それを使う」
- 入口の画面(`/api/status` の `dataDir`)に置き場所を出す(隠しフォルダなので、パスをコピーしてエクスプローラーで開く)

## テストの決まり(重要)
- サーバー(serve.py・入口)を動かすテストは、必ず `os.environ.setdefault("YTT_DATA_DIR", "inplace")` を先頭に置く。
  忘れると、移し済みの PC で、テストのサーバーが**本物の作業データ**を読み書きする。`ytt_core/test_ytt_core.py` の `test_every_server_test_isolates_data_dir` が検査する
- 置き場所の通し確認: `python tools/e2e_datadir.py`(本物の入口を、以前の場所にデータがある状態で起動。一時フォルダだけを使う)

## 元に戻すとき
- 環境変数 `YTT_DATA_DIR=inplace` で起動すると、以前の場所(各ツールのフォルダの中)を使う。ただし、移した後に新しい場所で増えた・直した分は以前の場所には無い

## 以前の場所のデータの片付け(`tools/cleanup_legacy_data.py`・`tools\cleanup_legacy_data.bat`)
- 新しい場所で使えることを確かめてから、ユーザーが実行する(Cowork は PC のファイルを消せない)。消すものの一覧と大きさを見せ、y で**ごみ箱へ**移す(戻せる)
- 消すのは、確かめられたものだけ: 新しい場所に `.migrated.json` があり、写した元がこのリポジトリのフォルダで、写した一覧にあり、新しい場所にも同じ名前があるもの。
  ログ・work などの一時的なものは、新しい場所が使われていれば消す。ツールが動いていれば何もしない。`--dry-run` で一覧だけ
- 片付ける一覧は各 serve.py の `DATA_ITEMS` と同じ(`tools/test_cleanup_legacy_data.py` が検査)。コード・cut2resolve の exports(パックの出力)は触らない

## 案件ファイル(`app\cases.json`。2026-09-26 v0.6.0)
- 案件 = 切り抜きスタジオの動画1本(配信・ファイル)。入口の「案件」の画面(`/cases.html`・`app/cases.py`)が、配信ごとに
  書き出した切り抜き・文字起こし(校正の進み具合)・パック(`<名前>_pack\cut-plan.json`)を並べる
- 紐づけは**開くたびに各ツールのデータから組み立て直す**(ユーザー決定。各ツールの記録と食い違わないため)。規則は `ytt_core/txindex.py`(スタジオのセリフの表示と共通):
  切り抜き = スタジオの書き出し済みのマーク(mp4 の絶対パス)/ 文字起こし = 文書の sourcePath が同じ、無ければ文書の clip(.clip.json)の配信・マークが同じ(新しいものを優先)
- `cases.json` に持つのは人が付ける状態(未設定・作業中・投稿済み・見送り)・メモ(2000 文字まで)と、状態かメモを付けた案件の「最後に見えた紐づけ」だけ
  (`{"schema": "youtube-tools-cases/v1", "cases": {<動画ID>: {status, memo, statusUpdatedAt, last}}}`)。どちらも外すと案件ファイルからも消える
- 各ツールのデータ(data.json・transcripts)は**読むだけ**。書き込みの API(`POST /api/cases/update`)は合言葉・Host/Origin の検査つき

## 残っていること
- 0old・.whisper_models はユーザーが 2026-09-26 に削除済み
- 段階4 はこれで一通り(置き場所の移動・案件ファイル・セリフの表示・重い処理の同時実行の上限)
