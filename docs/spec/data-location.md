# 作業データの置き場所(統合計画の段階4・2026-09-26)

作業データ(個人データ・設定・キャッシュ・記録)を**リポジトリの外**に置く。リポジトリには、コードと資料だけを残す。

## 決まったこと(ユーザー 2026-09-26)
- 置き場所: **`%LOCALAPPDATA%\youtube-tools\`**(例 `C:\Users\<ユーザー名>\AppData\Local\youtube-tools\`)。
  Windows のアプリのデータの定番の場所で、OneDrive で同期されない(個人データと 2GB を超えるキャッシュがクラウドに上がらない)
- 範囲: **全部**(3ツールの作業データ・設定・キャッシュ・ログ、話者判別のモデル、入口の記録)
- 移し方: **コピー**。以前の場所(各ツールのフォルダの中)のデータは消さない。消すのはユーザーが新しい場所で確かめてから

## フォルダの中身
| フォルダ | 中身 | 以前の場所から写すもの |
| --- | --- | --- |
| `studio\` | data.json(.bak)・feedback.jsonl(.old)・registry.json・config.json(YouTube の API キー)・settings(-ui).json・cache\(チャット 約2.2GB など)・archive\・studio.log・work\(解析の一時ファイル)・exports\(既定の書き出し先) | 左のうち、ログと work 以外 |
| `transcribe\` | transcripts\(.bak・.hist の控え・.resume = 全体の再認識の続きの記録(7 日で消す)を含む)・dataset\・evals\・models\diar\(話者判別のモデル)・settings.json・learn-feedback.json・eval-baselines.json・serve.log・worker.log・.running.json | 左のうち、ログと .running.json 以外 |
| `cut2resolve\` | work\uploads\(画面にドロップしたファイルの一時置き場。起動のたびに消える)・work\serve.log | なし(一時的なものだけ) |
| `app\` | logs\(入口の launcher.log と各ツールの出力・画面のエラーの記録 client-errors.jsonl(段階7-0))・cases.json(案件の状態・メモ。下の「案件ファイル」)・settings.json(`"window"`: 窓で開くか。段階7-3)・browser-profile\(窓(Edge のアプリモード)の専用のプロファイル。閲覧の記録・Cookie・キャッシュが入り、数十〜数百 MB になる。消すと窓の設定・ログインが初期に戻るだけ) | なし |
| 各フォルダの `.migrated.json` | いつ・どこから・何を写したか | — |

- 切り抜きスタジオの書き出し先: 設定で決めていればそのまま。以前の既定(`clip-studio\exports`)を使っていた場合は、そこを使い続ける(動画が2か所に分かれないように)
- パックの出力(cut2resolve の `<動画名>_pack`)・スタジオの書き出した動画は、これまでどおり動画の隣・指定したフォルダ(作業データではない)。
  受け渡しの途中のファイル(`.clip.json`・`.transcript.json`・`_edit.mp4` など)は、動画のフォルダの下の `作業用` フォルダ(2026-09-27。`docs/spec/pipeline.md` の 1)

## 仕組み(`ytt_core/datadir.py`)
- `data_root()`: 環境変数 `YTT_DATA_DIR` → Windows は `%LOCALAPPDATA%\youtube-tools`(macOS `~/Library/Application Support/youtube-tools`、それ以外 `$XDG_DATA_HOME/youtube-tools`)。
  `YTT_DATA_DIR=inplace` は以前と同じ「各ツールのフォルダの中」(テスト・元に戻したいとき用)
- `prepare(ツールID, 以前の場所, 写す名前)`: 各ツールが起動時に1回呼ぶ
  - 項目ごとに「一時的な名前(`.part-<pid>`)へコピー → 大きさとファイル数が元と同じか確かめる → 本来の名前へ改名」。途中で止まっても半端なものを本物として使わない(残った `.part-` は次の起動で消す)
  - 新しい場所にすでにある項目は上書きしない
  - 空き容量が足りない(写す量 + 256MB)・コピーに失敗したときは移さず、そのツールは**以前の場所のまま**動く(黒い画面に警告)。今回写した分は消し、次の起動で写し直す(以前の場所のまま動く間に古くなるため)
  - 全部終わったら `.migrated.json`。次からは写さない(新しい場所が正)
  - シンボリックリンクはたどらない
- 各ツール: スタジオ `serve._data_home()`(環境変数 `STUDIO_HOME` があればそれ。下の「置き場所の求め方」)、文字起こし `serve.choose_data_dir()` / `set_data_dir()`(ワーカーには `TRANSCRIBE_DATA_DIR`)、
  cut2resolve `serve._choose_work_dir()`、入口 `launch.logs_dir_for()`。どれも「テスト・入口が先に場所を決めていれば、それを使う」
- 入口の画面(`/api/status` の `dataDir`)に置き場所を出す(隠しフォルダなので、パスをコピーしてエクスプローラーで開く)

## 置き場所の求め方は ytt_core/datadir の1か所(2026-10-01 ユーザー決定)
以前は「`STUDIO_HOME` があればそれ、無ければ `datadir.tool_dir(...)`」のような式が、入口の案件(`home/cases.py`)・`ytt_core/txindex.py`・
各ツールの serve.py に別々に書かれていた。今は `ytt_core/datadir.py` だけが決め、他はそれを呼ぶ。
- `datadir.resolve(ツールID, repo_root, env)`(他のツールのデータを読む側)の順番:
  1. **登録された場所**(`datadir.register`)… 起動したツールが実際に決めたフォルダ。入口の中では同じプロセスの他のツールがそれを読む
     (移せずに以前の場所のまま動いた・テストがツールを一時フォルダに写して動かした、でも読む場所がずれない)。
     **`env` を渡したとき(テスト・明示の指定)は見ない**(`txindex.packs_dir` と同じ決まり)
  2. **ツールごとの環境変数** `datadir.ENV_OVERRIDE`(`studio` → `STUDIO_HOME`、`transcribe` → `TRANSCRIBE_DATA_DIR`。テスト用・以前からの指定)
  3. `tool_dir`(`YTT_DATA_DIR` → `%LOCALAPPDATA%\youtube-tools\<ツールID>` など。`inplace` なら各ツールのフォルダの中。フォルダ名は `ytt_core/layout.py`)
- `datadir.locate(...)` は 2 → 3 だけ(登録を見ない。自分で決める側 = 入口の `launch.app_data_dir` が使う)
- `datadir.prepare(...)`(ツールの起動時): 2 の環境変数があれば、写さずにそこを使う(`state: "override"`)。無ければ 3 の場所へ移行する。
  **`env` を渡さない(本物の起動の)ときは、決めたフォルダを登録する**(テストが `env` を渡して呼んでも、プロセス全体の登録は変わらない)
- 登録するところ: スタジオ `serve.prepare()`(テスト・入口が先に決めていたときも、実際に使う `common.home()` を登録)、
  「編集」は `serve.set_data_dir()`(`TRANSCRIBE_DATA_DIR` のときも `datadir.prepare` のときも通る)、cut2resolve は `datadir.prepare` の中で、入口は `launch.main()`(`app`)。cut2resolve の `txindex.use_packs_dir(<作業データ>/packs)` も
  `cut2resolve` の登録になる
- 読むところ: 入口の案件 `cases.locations()`(スタジオの data.json・案件ファイル)、`txindex.folder()`(文字起こし)・`txindex.packs_dir()`(パックを作った記録)、
  スタジオのセリフの表示(`studio/txlink.py` → `txindex.folder`)

## テストの決まり(重要)
- サーバー(serve.py・入口)を動かすテストは、必ず `os.environ.setdefault("YTT_DATA_DIR", "inplace")` を先頭に置く。
  忘れると、移し済みの PC で、テストのサーバーが**本物の作業データ**を読み書きする。`ytt_core/tests/test_ytt_core.py` の `test_every_server_test_isolates_data_dir` が検査する
- 置き場所の通し確認: `python dev/tests/e2e_datadir.py`(本物の入口を、以前の場所にデータがある状態で起動。一時フォルダだけを使う)

## 元に戻すとき
- 環境変数 `YTT_DATA_DIR=inplace` で起動すると、以前の場所(各ツールのフォルダの中)を使う。ただし、移した後に新しい場所で増えた・直した分は以前の場所には無い

## 以前の場所のデータの片付け(`setup/cleanup_legacy_data.py`・`setup\cleanup_legacy_data.bat`)
- 新しい場所で使えることを確かめてから、ユーザーが実行する(Cowork は PC のファイルを消せない)。消すものの一覧と大きさを見せ、y で**ごみ箱へ**移す(戻せる)
- 消すのは、確かめられたものだけ: 新しい場所に `.migrated.json` があり、写した元がこのリポジトリのフォルダで、写した一覧にあり、新しい場所にも同じ名前があるもの。
  ログ・work などの一時的なものは、新しい場所が使われていれば消す。ツールが動いていれば何もしない。`--dry-run` で一覧だけ
- 片付ける一覧は各 serve.py の `DATA_ITEMS` と同じ(`dev/tests/test_cleanup_legacy_data.py` が検査)。コード・cut2resolve の exports(パックの出力)は触らない

## 案件ファイル(`app\cases.json`。2026-09-26 v0.6.0)
- 案件 = 切り抜きスタジオの動画1本(配信・ファイル)。入口の「案件」の画面(`/cases.html`・`home/cases.py`)が、配信ごとに
  書き出した切り抜き・文字起こし(校正の進み具合)・パック(`<名前>_pack\cut-plan.json`)を並べる
- 紐づけは**開くたびに各ツールのデータから組み立て直す**(ユーザー決定。各ツールの記録と食い違わないため)。規則は `ytt_core/txindex.py`(スタジオのセリフの表示と共通):
  切り抜き = スタジオの書き出し済みのマーク(mp4 の絶対パス)/ 文字起こし = 文書の sourcePath が同じ、無ければ文書の clip(.clip.json)の配信・マークが同じ(新しいものを優先)
- `cases.json` に持つのは人が付ける状態(未設定・作業中・投稿済み・見送り)・メモ(2000 文字まで)と、状態かメモを付けた案件の「最後に見えた紐づけ」だけ
  (`{"schema": "youtube-tools-cases/v1", "cases": {<動画ID>: {status, memo, statusUpdatedAt, last}}}`)。どちらも外すと案件ファイルからも消える
- 各ツールのデータ(data.json・transcripts)は**読むだけ**。書き込みの API(`POST /api/cases/update`)は合言葉・Host/Origin の検査つき

## ごみ箱フォルダ(段9 9-2。入口 0.20.0。2026-10-01 ユーザー決定)
- ホームの「詳しく」の「片付け」で選んだ物は、すぐには消さず「ごみ箱フォルダ」の `<日付>\<種類>\` へ移す。14 日たった日付のフォルダは入口の起動時に消える(`home/cleanup.py` の `purge`)
- 置き場所は**動画と同じドライブ**(別のドライブへ数 GB を写さない・C: を圧迫しない): 作業データと同じドライブ → `%LOCALAPPDATA%\youtube-tools\app\ごみ箱\`、
  スタジオの書き出し先と同じドライブ → `<書き出し先>\ごみ箱\`、それ以外 → `<ドライブ>\youtube-tools ごみ箱\`。作業データの外に作った場所は `app\trash-roots.json` に残し、起動時の purge がそこも見る
- 元の場所は日付のフォルダの `manifest.jsonl`(1行 = {from, to, kind, bytes, at})。戻すときはエクスプローラーで移す

## 残っていること
- 0old・.whisper_models はユーザーが 2026-09-26 に削除済み
- 段階4 はこれで一通り(置き場所の移動・案件ファイル・セリフの表示・重い処理の同時実行の上限)

## バックアップ(2026-10-03。ホーム 0.24.0 で自動に)
- 作業データは**リポジトリの外**にあるので、git にも GitHub にも入らない(push.bat でも守られない)
- **2026-10-03 に Windows を入れ直したとき、作業データ(文字起こしと校正・スタジオの解析とマーク・設定)を失った**。バックアップが無かったため戻せなかった
- **自動のバックアップ**(ユーザー決定 2026-10-03。`home/backup.py`): ホームの「作業データのバックアップ」で写す先のフォルダを決めてオンにすると、
  入口が動いている間、決めた間隔(既定 1 時間。2026-10-04 に 24 → 1。すでに保存した設定は変わらない)で `<写す先>\youtube-tools-data\<ツールID>\…` へ写す。この PC の設定は `D:\backup`(設定はホームの `prefs.json` の節 `backup`)
  - 写すもの: 作り直せないもの(transcripts(.hist・.bak を含む)・dataset・evals・voices・settings・スタジオの data.json・feedback.jsonl・archive・registry・config.json・
    cut2resolve の packs・入口の cases.json・prefs.json など)
  - **変わったらすぐ写す**(2026-10-04): 間隔のほかに、3 分ごと(`CHECK_EVERY`)に、写す対象のファイルが前回の写し始めより新しく更新されていないかを見て、
    最後の変更から 120 秒(`QUIET`。校正の保存が続いている間は待つ)たっていれば、間隔を待たずに写す。間隔が来たときは、変わっていなくても写し(検証)にいく。
    `backup-state.json`・`.running.json` は「変わった」の判定に使わない(写すたび・ジョブのたびに書き換わるため)。写せなかったファイルがあれば、次の回でもう一度写す
  - 写さないもの(`backup.SKIP_DIRS`・`SKIP_SUFFIX`): `cache`・`work`・`logs`・`models`・`bin`・`browser-profile`・`exports`・`*.log`・途中のファイル(`.part-`)。
    取り直せる・作り直せるもの(チャットのキャッシュ・モデル・llama.cpp などの実行ファイル)と大きいもの。
    **例外: `transcribe\bin\whisper.cpp-*` は写す**(作り直すのに Visual Studio が要る。56MB ほど)。`models` は写さない。
    `transcribe\eval-audio\`(評価用の音声の flac)は写す(SKIP に入れない。テストで固定)。**新しく作業データに「作り直せないフォルダ」を足すときは、この名前と重ならないようにする**
  - 写し方: 大きさか更新時刻が違うファイルだけ・一時的な名前へ写してから改名・**写す先のファイルは消さない**(作業データで消えたもの・壊れたものに合わせて消さない)・
    上書きするときは、その日の最初の1回だけ1つ前を `.prev` で残す・シンボリックリンクはたどらない・写す先が作業データの中のときは断る
  - `YTT_DATA_DIR=inplace`(テスト・以前の形)では写さない。写す処理は入口のプロセスの中のスレッド(起動の 90 秒後に、時間が来ていれば)
  - 鍵(スタジオの `config.json` の YouTube の API キー)も写る。写す先は自分の PC のドライブにする(共有・クラウドのフォルダに置かない)
- 写し戻し: `home/backup.py` の `restore_once`(下の「写し戻しの手順」)。**2026-10-04 に一時フォルダで「写す → 消す → 写し戻す → 中身が同じ」をテストで確かめた**(`home/tests/test_backup.py`)。本物の作業データへの写し戻しは、まだ実際には試していない
- 残るリスク: 入口を動かしていない間は写らない・同じ PC の別のドライブなので、PC ごと失うと一緒に失う(外付けやクラウドへの写しは別に考える)・
  履歴は「1つ前」だけ(文字起こしは transcripts の `.hist` が別に履歴を持つ)
- テスト: `python -m unittest home/tests/test_backup.py`・`python home/tests/e2e_backup_ui.py`

## 写し戻しの手順(2026-10-04)
バックアップ(`<写す先>\youtube-tools-data\`)から作業データ(`%LOCALAPPDATA%\youtube-tools\`)へ、無い・違うファイルを写す。
`.prev`(1つ前の控え)は写さない・作業データのほうが新しいファイルは上書きしない(件数を出す)・作業データのファイルは消さない・シンボリックリンクはたどらない。

1. **入口を止める**(ホームの「すべて終了」。動いたままだと、写し戻したファイルをツールが古い内容で上書きする)
2. **Claude のアプリの中のシェルからは動かさない**。アプリは MSIX のパッケージなので、AI のシェルが `%LOCALAPPDATA%` へ書くと本物の場所ではなくパッケージの写しに入り、
   start.bat で動かす入口から見えない(AGENTS.md の動作環境)。**ユーザーの PowerShell(通常の窓)**で動かす。AI に頼むときは WMI(`Invoke-CimMethod Win32_Process Create`)で、パッケージの外のプロセスとして動かす
3. コマンド(リポジトリ直下から。`python` ではなく `py -3.10`):

   ```
   py -3.10 home\backup.py --restore D:\backup
   ```

   写す個数・大きさ・「作業データのほうが新しいので上書きしない」個数を出して、`y/N` を聞く。`--yes` で聞かない。写し戻す先の既定は本物の作業データ(`ytt_core/datadir` の場所)。`--target <フォルダ>` で別の場所へ(確かめ用)
4. 入口を start.bat(またはデスクトップのショートカット)で起動する。画面で文字起こしの一覧・案件・スタジオのマークが戻っていることを確かめる
5. 写し戻したあとの最初の自動バックアップは、写す先と作業データが同じ内容なので、ほとんど何も写さない
