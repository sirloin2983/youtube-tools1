# youtube-tools1 — YouTube ショート動画の編集支援ツール群

このリポジトリで作業する AI(Claude・GPT/Codex のどちらも)の共通の前提です。Codex はこのファイルを、Claude Code は CLAUDE.md 経由で読みます。

## 最初にやること
1. `plan/index.html`(データ `plan/data.js`) を読む(全体の計画・各線の進捗・これからの順番。**順番の正**)
2. `docs/WORKLOG.md` の最後の数件を読む(誰が・いつ・何を変えたか、**未コミットのファイル**、未完了、注意)
3. `git status` と `git log -5 --oneline` を見る(下の「複数の AI で作業するときのルール」)
4. 触るツールの `AGENTS.md`(`src/editor/AGENTS.md`・`src/recorder/AGENTS.md`)と `README.txt` を読む。文書の索引は `docs/ROADMAP.md`

## フォルダの並び(2026-10-07 に整理。正は `src/ytt_core/layout.py`)
```
youtube-tools/
├─ start.bat  push.bat  README.txt  AGENTS.md  CLAUDE.md   ユーザーが触る(AGENTS/CLAUDE は AI の入口)
├─ setup/        インストールと片付け(install.bat・install-gpu.bat・bootstrap.bat・requirements*.txt)
├─ plan/         ユーザーが読む計画(README = 全体と進捗・user-tasks・decisions・improvements・line-*)
├─ src/          動くコード: home(入口)・studio・editor・cut2resolve・recorder・ytt_core(共通部品)・ui-kit(共通の見た目)
├─ friend-apps/  友人用の Windows アプリ(holo-colors・request-sender。C# 5・WinForms。build.bat で zip)
├─ chrome-ext/   自分用の Chrome 拡張(yt-studio-time = YouTube Studio のコンテンツ一覧の日付に投稿時刻を足す。2026-10-08)
├─ dev/          開発用の道具(push の検査・ui-kit の同期・精度を測る道具 eval_*.py・通し確認)と dev/tests/
└─ docs/         AI 向け: WORKLOG(記録)・HANDOVER(引き継ぎ)・ROADMAP(索引)・spec/(今の決まり)・design/(済んだ設計・briefs)
```
- **「root」の意味**: 各ツールの「1 つ上」= `src/`(`layout.src_root()`。テストが一時フォルダにツールと ytt_core を平らに写したときはその一時フォルダ)。入口の `ROOT`・`datadir`・`txindex`・テストの `REPO` はこの意味。リポジトリ直下(dev/・setup/・friend-apps/)が要るときだけ `layout.repo_root()`・`layout.holo_colors_dir()`
- **フォルダ名と識別子は別**: `/api/ping` の `"clip-studio"`・`"transcribe-tool"`、JSON の tool.name・schema、作業データの ID(`app`・`studio`・`transcribe`)、URL の `/studio/` `/transcribe/` `/cut2resolve/` は互換のため変えない(grep で当たっても直さない)。09-30 の改名(app→home・clip-studio→studio・transcribe-tool→editor・tools→dev)の対応表は `docs/design/phase0-restructure.md`
- 作業データ(文字起こし・設定・案件など)はリポジトリの外 `%LOCALAPPDATA%\youtube-tools\<ツールID>\`(`docs/spec/data-location.md`)。`.runtime/`(起動中のポート)は `src/.runtime/`

## 全体の形
- 3 つのツール(切り抜きスタジオ `src/studio/`・編集 `src/editor/`・cut2resolve `src/cut2resolve/`)と入口(ホーム `src/home/`)。どれも Python 標準ライブラリ中心のローカルサーバー + ブラウザの画面で、ユーザーの PC 上だけで動く。外部サービスへ動画・音声を送らない方針
- 起動は `start.bat` だけ(各ツールの単独起動は 2026-09-26 にやめた)。入口(`src/home/launch.py`、http://localhost:8700/)が 1 つのプロセスの中で 3 ツールを取り込む: `/studio/`・`/transcribe/`(編集)・`/cut2resolve/`(パックを作る API)。文字起こしの認識(faster-whisper・sherpa-onnx・whisper.cpp)だけは別プロセスのワーカー(`src/editor/tx_worker.py`)。録画の部品(`src/recorder/`。線 D。既定はオフ)も別プロセス
- **「編集」**(`docs/design/edit-tool-design.md`): 文字起こしと cut2resolve の画面を 1 つにした 3 つのタブ(1 文字起こし / 2 カット / 3 パック)。カット(残す区間)は `transcripts/<id>.edit.json`。cut2resolve は画面を消して、パックを作る部品(pack.py)・API(serve.py)・CLI として残る
- 流れ: スタジオで配信から区間を選んで書き出す → 編集で字幕を作って直し(1)・カットを決め(2)・DaVinci Resolve 用のパック(カット + Text+ 字幕)を作る(3)。受け渡しの形式は `docs/spec/pipeline.md`
- 線 D(リアルタイム切り抜き → 配信後の全自動): 録画の部品が HLS で録画し、スタジオの画面(配信の kind `"live"`)でマーク → 書き出し → 文字起こし → パック。計画は `plan/line-d-*.md`
- 別件: 友人からの依頼の受付(`docs/spec/friend-intake.md`。友人は `friend-apps/request-sender/` のアプリで Dropbox へ送る・入口 `src/home/intake.py` が受け取って自動で流す)・ホロカラー(`friend-apps/holo-colors/`。メンバーカラーをコピーする常駐アプリ。`members.json` は `src/ytt_core/colors.py` が読んで字幕の色に使う。設計 `docs/design/holo-colors.md`)
- ユーザー向けの使い方の全体はリポジトリ直下の `README.txt`。各ツールの `README.txt` は細かい使い方と変更の記録
- 統合計画(`docs/design/integration-plan.md`。段階 0〜7 完了)の正本は claude.ai の Claude Docs「動画編集ツール 統合計画」

## フォルダと、変えたら通すテスト
**すべてリポジトリ直下から実行。この PC では `python` を `py -3.10` と読み替える**(下の動作環境)。e2e(画面テスト)は 1 本ずつ・`PYTHONIOENCODING=utf-8` を付ける。unittest には付けない。コードを変えたら `py -3.10 dev/lint.py` も 0 件にする(基準: `docs/spec/code-quality.md`)。
| フォルダ | 役割 | 変えたら通すテスト |
| --- | --- | --- |
| `src/home/` | 入口・ホーム(ランチャー `launch.py`・取り込み `mount.py`・案件 `cases.py`・まとめて実行 `autorun.py`・窓 `appwindow.py`・エラーの記録 `clientlog.py`・バックアップ `backup.py`・届ける `deliver.py`・依頼の受付 `intake.py`・精度の自動測定 `accuracy.py`・調子 `health.py`・片付け `cleanup.py`・ライブ `live*.py`・配信中の検出 `live_detect.py`(入口側)と `live_excite_worker.py`(子プロセス。線 D の L2)) | `python -m unittest src/home/tests/test_launch.py src/home/tests/test_mount.py src/home/tests/test_cases.py src/home/tests/test_autorun.py src/home/tests/test_window.py src/home/tests/test_intake.py src/home/tests/test_backup.py src/home/tests/test_deliver.py src/home/tests/test_health.py src/home/tests/test_accuracy.py src/home/tests/test_live.py src/home/tests/test_live_archive.py src/home/tests/test_live_detect.py src/home/tests/test_cleanup.py src/home/tests/test_restart.py`、`python src/home/tests/e2e_portal.py`、`e2e_autorun.py`、`e2e_window.py`。依頼の受付の画面を変えたら `e2e_intake_ui.py`、バックアップの画面 `e2e_backup_ui.py`、キー配置 `e2e_keymap.py`、ライブ `e2e_live.py`・`e2e_live_studio.py`・`e2e_live_archive.py` |
| `src/studio/` | 切り抜きスタジオ(配信の解析・マーク・書き出し。ライブの画面 `review.js` の LivePlayer) | `python -m unittest src/studio/tests/test_studio.py src/studio/tests/test_api.py src/studio/tests/test_analyze.py src/studio/tests/test_exporter.py src/studio/tests/test_handoff.py src/studio/tests/test_robustness.py src/studio/tests/test_file_recovery.py src/studio/tests/test_rank_live.py`、`node --test src/studio/tests/test_review.cjs`、`python src/studio/tests/e2e_analyze.py`、画面を変えたら `python src/studio/tests/e2e_ui.py` と `--mounted`(`e2e_review.py` は手で見る見本サーバー) |
| `src/editor/` | 「編集」(文字起こし・話者判別・校正画面・精度測定・評価ドリル・2 つ目のエンジン・カット `cut.js`・パック `pack-tab.js`) | `src/editor/AGENTS.md` の「テストの実行」(画面を変えたら `e2e_ui_mounted.py`・`e2e_edit_tabs.py`・`e2e_edit_cut.py`・`e2e_edit_pack.py`・`e2e_edit_voices.py` も)。まとめて流すなら `python dev/run_editor_suite.py` |
| `src/cut2resolve/` | Resolve への受け渡し(EDL・Text+ パック)の部品と CLI・API | `python -m unittest src/cut2resolve/tests/test_cut2resolve.py src/cut2resolve/tests/test_pack.py src/cut2resolve/tests/test_serve.py`(API を変えたら `python src/editor/tests/e2e_edit_pack.py` も) |
| `src/recorder/` | 録画の部品(streamlink + ffmpeg の HLS・API と合言葉。入口と別のプロセス。`src/recorder/AGENTS.md`) | `python -m unittest src/recorder/tests/test_recorder.py`。入口の側を変えたら home の `test_live*`・`e2e_live*` |
| `src/ytt_core/` | 共通部品(書き込み `fsio`・`.runtime`・受け渡しの形式 `schemas`・Host/Origin 検査 `httpsec`・作業データの置き場所 `datadir`・同時実行の上限 `jobs`・文字起こしの読み取りと紐づけ `txindex`・名前 → メンバーカラー `colors`・ffmpeg などの場所 `tools`・フォルダ名 `layout`・評価データの形式 `evaldata`・30fps にそろえる `normalize`・盛り上がりの式 `excite`) | `python -m unittest src/ytt_core/tests/test_ytt_core.py src/ytt_core/tests/test_evaldata.py src/ytt_core/tests/test_normalize.py src/ytt_core/tests/test_excite.py` と、使っている各ツールのテスト(`excite` を変えたら `src/studio/tests/test_analyze.py`・`e2e_analyze.py`・`dev/tests/test_eval_marks.py` も) |
| `src/ui-kit/` | 共通の見た目と画面の共通の動き(`src/ui-kit/README.md`)の正本。**画面を直すときは `docs/spec/ui-guidelines.md` と `docs/spec/usability-heuristics.md` に合わせ、`docs/spec/ui-review-criteria.md` の基準(A は `py -3.10 dev/ui_audit.py all --demo` で Must 0 件)を満たす**。`python dev/sync_ui_kit.py` で各ツールへ写す(写しは手で直さない) | `python -m unittest dev/tests/test_ui_kit_sync.py`・`python src/ui-kit/tests/e2e_styleguide.py` と各ツールの画面のテスト。画面を変えたら `py -3.10 dev/ui_audit.py all --demo` の Must 0 件 |
| `dev/` | 開発用の道具(`push_helper.py`・`removals.txt`・`sync_ui_kit.py`・`run_editor_suite.py`・`demo_env.py`・`plan_artifact.py`(計画の公開ページ)・`lint.py`(コードの基準 `docs/spec/code-quality.md` を測る。**コードを変えたら `py -3.10 dev/lint.py` が 0 件**)・`ui_audit.py`(画面の基準 `docs/spec/ui-review-criteria.md` の A を測る。**画面を変えたら `py -3.10 dev/ui_audit.py all --demo` の Must 0 件**。`static` はサーバー不要)・測る道具の共通部品 `_evalcommon.py`・精度を測る `eval_asr.py`・`eval_marks.py`・`eval_speakers.py`・`eval_cut.py`・`eval_alt.py`・`eval_effort.py`・`eval_timing.py`(行の時刻を原則 ①頭・①末・②前・②次・③ の数字で。`--apply` で後処理を当て直す)・`eval_cloud.py`(クラウドの文字起こしに評価用を送って同じ物差しで測る。送る前に見積もり・`--send` で送る・キーは環境変数か鍵のファイル)・`eval_split.py`・`eval_fetch.py`・`eval_import.py`・`dropbox_auth.py`) | 道具を変えたら対応する `dev/tests/test_<名前>.py`。`python dev/tests/e2e_pipeline.py`(3 ツールの通し)・`python dev/tests/e2e_datadir.py`。`python -m unittest dev/tests/test_resolve_pack_contract.py` は**単独で**(cut2resolve と編集の部品を読むので他と混ぜると名前が重なる)。`src/cut2resolve/` か編集の `resolve_export.py`・`pipeline_io.py` を変えたら必ず |
| `setup/` | インストールと片付け(`install.bat`・`install-gpu.bat`・`install-diarize.bat`・`bootstrap.bat`・Mac の `.command`・`requirements*.txt`・`cleanup_legacy_data.bat`・`build-whisper-vulkan.bat`) | `.bat` と `requirements*.txt` は ASCII だけ。片付けのテストは `dev/tests/test_cleanup_legacy_data.py` |
| `friend-apps/holo-colors/` | ホロカラー(C# 5・WinForms。`src/`・`members.json`・`tests/`) | `friend-apps\holo-colors\build.bat`(コンパイル → テスト 31 件 → `dist/HoloColors.zip`。PowerShell からは `.\build.bat`)。キー・窓の動きを変えたら `python friend-apps/holo-colors/tests/e2e_holo_colors.py`(**本物のキー入力を送る。流す間は触らない・他のテストと同時にしない**) |
| `friend-apps/request-sender/` | 友人が依頼を送るアプリ(C# 5・WinForms。Dropbox の API)。鍵 `config.json` はコミットしない | `friend-apps\request-sender\build.bat`。鍵を作る `dev/dropbox_auth.py` を変えたら `dev/tests/test_dropbox_auth.py` |
| `chrome-ext/yt-studio-time/` | 自分用の Chrome 拡張: YouTube Studio のコンテンツ一覧の「日付」に公開(投稿)の時刻を足す(manifest V3・`world: MAIN` で内部 API の応答を控える。権限なし・外部との通信なし。使い方 `README.txt`・作り `AGENTS.md`。友人に渡す zip は `build.bat` → `dist/YtStudioTime.zip`) | `node --test chrome-ext/yt-studio-time/tests/test_main.cjs`(純粋な部分)・`python chrome-ext/yt-studio-time/tests/e2e_fake_studio.py`(偽の Studio に拡張を入れて通し。Edge で流す)。本物の Studio の画面は手で(README の入れ方) |
| `docs/`・`plan/` | 記録・仕様・計画 | — |

- 画面のテストは Playwright(chromium)+ ffmpeg が必要(入れ方は `setup/requirements-dev.txt` の先頭)。Playwright 同梱の chromium は H.264 を再生できない(動画の再生まで確かめるテストは webm で作る)。CSP のある画面では `page.wait_for_function` が動かない(`evaluate` で待つ)
- ツールを一時フォルダに写して動かすテストが多い。新しいファイルを足したら、写すファイルの一覧(各 e2e の先頭)にも足す
- **サーバーを動かすテストは先頭で `os.environ.setdefault("YTT_DATA_DIR", "inplace")`**(忘れると本物の作業データを読み書きする。`src/ytt_core/tests/test_ytt_core.py` が検査)。配信者の色の一覧を使うときは `YTT_HOLO_MEMBERS` を `friend-apps/holo-colors/members.json` に
- node は PATH に無い。Playwright 同梱の node を使う(`dev/run_editor_suite.py` の `find_node` と同じ場所: `<playwright>/driver/node.exe`)
- 説明文(docstring)にバックスラッシュを書かない(パスの例は `/`)。`.bat` は CRLF・ASCII だけ。多くのファイルは CRLF・UTF-8(差分で直す。丸ごと書き直さない)

## 資料の場所(正本はこのリポジトリ)
- **文書の索引は `docs/ROADMAP.md`**。順番と進捗は `plan/index.html`(データ `plan/data.js`)。claude.ai の Project の `claude/*.md` は古い写しで根拠にしない(例外: 統合計画は Claude Docs が正本)
- 今の仕様 = 各ツールの `README.txt`(ユーザー向け)+ `AGENTS.md`(AI 向け)+ コード。ツール間の受け渡し: `docs/spec/pipeline.md`
- **`plan/data.js` を直したら公開ページも更新する**(Claude Code だけができる): `py -3.10 dev/plan_artifact.py --out <scratchpad の art>` で 1 枚にまとめ、Artifact ツールで `url` = data.js の `artifactUrl` に公開し直す(主のページ = art/index.html、files = {"user-tasks.html": art/user-tasks.html})。スマホで見るためのリンク
- 新しい文書は種類で置く: 今の決まり・仕様 → `docs/spec/`、これからの計画(ユーザーが読む)→ `plan/`、済んだ設計・決定の記録 → `docs/design/`。WORKLOG と `docs/ROADMAP.md` の索引からリンクする。計画・設計の文書の先頭には「状態(日付)」の 1 行を置き、状態が変わったらその行と `plan/index.html`(データ `plan/data.js`) を直す
- 古い経緯(`docs/archive/`)は 2026-10-07 に消した。必要なら git の履歴(679ff01 以前)で読む。過去の記録(WORKLOG・`docs/design/`)の中の旧いパスは書き換えない

## 開発のルール
- 実行時データ・個人データ・秘密情報はコミットしない(`.gitignore`: transcripts/ dataset/ models/ exports/ clips/ config.json など)。リポジトリは Public にする方針。push.bat はコミットの前に `dev/push_helper.py check` で調べ、キーの形・個人データの名前・動画・5MB 超があれば止める(誤検出なら検査を直す)
- 版を上げるときは、**serve.py の SERVER_VERSION・画面の APP_VERSION・README.txt の見出し**を同時に上げる(食い違うと画面に赤い帯が出る)。APP_VERSION の場所: スタジオ `core.js`、編集 `app.js`、cut2resolve は `cut2resolve_core.py` の VERSION、入口は `src/home/launch.py`
- 各ツールの起動の約束(`serve.py [ポート] --no-open`・`.runtime/<ID>.json`・`/api/ping`・SIGTERM/SIGBREAK で後始末)は入口が使う。変えるときは `src/home/launch.py` と `test_launch.py` も
- コミット: ユーザーの push.bat は `git add -A` でまとめてコミットし、メッセージは「update 日付 時刻」。**何をなぜ変えたかは WORKLOG に書く**。AI が自分でコミットするときは日本語で要約(`"[Claude] 要約"` / `"[GPT] 要約"`)
- 重い処理は `src/ytt_core/jobs.py` の `SLOTS` を通す(新しく重い処理を足すときも)。データ移行はコピーのみ・元は残す・削除はユーザー確認後(`datadir.py`)

## 複数の AI で作業するときのルール(Claude・GPT/Codex 共通)
このリポジトリは Claude(Cowork / Claude Code)と GPT(Codex)の両方が編集する。**正は PC の作業フォルダ(C:\dev\youtube-tools)とその git**。ユーザーは git の手作業を面倒に感じているので、情報の共有は AI 側でこのルールに沿って自動で行う。

作業を始める前:
1. `docs/WORKLOG.md` の最後の数件を読む
2. `git status` と `git log -5 --oneline` を見る。**自分が変えていない未コミットの変更は、他の AI の作業途中**。上書き・破棄しない(`git add -A` を使わない)。触る必要があるなら、先に「WIP: 他の AI の作業途中」としてコミットしてから始めるか、ユーザーに確認する
3. 版番号(各ツールの SERVER_VERSION / APP_VERSION)を実際のファイルと WORKLOG で確認する(別々の AI が同じ番号を付けないため)

作業中:
- ファイルは差分で直す。**古い控えからのファイル丸ごとの上書き・zip での上書き配布はしない**(2026-09-23 に GPT の変更が消えた事故)
- 設計の変更・依存の追加・費用がかかること・既存機能の削除は、実装の前にユーザーに確認する。ユーザーが「止めずに進めて」と指示した作業では仮で決めて進め、`plan/decisions.md` の「仮で決めたこと」に並べて最後にまとめて確認する
- ファイルの移動・改名は `git mv` を **1 コミットにまとめ**、前後で WORKLOG に告知する。長く分かれたブランチは使わない

サブエージェント(並列の AI)を使うとき(2026-09-30 ユーザー決定):
- 分けられる作業(担当するファイルが重ならない調べもの・直し)はサブエージェントに分けて並列で進める。担当するファイル・フォルダを重ならないように決め、まとめ役が最後に全体のテストと境目の漏れを確かめる。e2e は 1 本ずつ(まとめ役が流す)
- **仕事の難しさに合わせてモデルを選ぶ**: 探す・数える・一覧(読むだけ)= 小さく速いモデル(Haiku)/ 決まった規則での直し・テストの実行と直し = 中くらい(Sonnet)/ 設計の判断・原因の分からない不具合・影響が広い部品(入口・取り込み・データの置き場所・セキュリティ)= いちばん強いモデル(Opus)。選んだモデルと理由は報告に 1 行で書く
- **WORKLOG は追記の直前に `git diff docs/WORKLOG.md` で他の未コミットの差分を確かめる**(ほかの AI の追記を巻き込まない)

作業を終えるとき:
1. `docs/WORKLOG.md` の**末尾**に記録を追記する(書式は WORKLOG の先頭)。コミットしていないなら「未コミット: <ファイル一覧>」を必ず書く。進捗が変わったら `plan/index.html`(データ `plan/data.js`) の該当の行も直す
2. git を使える AI は、変更したファイルと WORKLOG をコミットする(`git add <変えたファイル> docs/WORKLOG.md` → `git commit`)。push はユーザーが push.bat で行う
3. 長く使う設計・決定は `docs/` か `plan/` に文書で残し、WORKLOG からリンクする
4. 長い作業で文脈が圧縮されそうなときは、`docs/HANDOVER.md` と「次のセッションにそのまま貼れる再開用の指示文」を更新する

Claude(Cowork。クラウドから PC のフォルダに読み書きする)の注意:
- PC で git・ファイルの移動・削除ができない。WORKLOG への追記までを行い、コミットは次に git を使う AI か push.bat に任せる。**ファイルを消すときは `dev/removals.txt` に 1 行ずつ書く**(push.bat が `git rm` する)。移動は WORKLOG に手順を書いて頼む
- 書き込んだら読み直して、手元の内容と一致することを確かめる(2 回目以降が前の内容のまま書かれることがあった)
- 起動中の入口は古いコードのまま動いている。コードを直したら、ユーザーに「すべて終了」→ start.bat で起動し直してもらう

## 担当表(担当中は、他の AI はそのツール・ファイルを触らない。変わったら WORKLOG に書く)
- 統合(`src/home/`・`src/ytt_core/`)・`src/cut2resolve/`・編集(`src/editor/`)・3 ツールと入口の画面(`src/studio/`・`src/ui-kit/`)・ホロカラー・依頼の受付・録画の部品: **Claude**(ユーザー決定 2026-09-25〜30。**GPT は調査と文書まで**)
- 上に無いものを触るときは、始める前に WORKLOG に「担当: 〇〇」と書く

## 取り込みの決まりとリスク(統合計画の段階 3 以降。必ず守る)
- 画面は**相対パス**で部品を読み、API・動画の URL は 1 か所の関数で作る(絶対パス `/xxx` を書かない)。スタジオは `Studio.api`、編集は `app.js` の `apiUrl()` / `api()`(cut2resolve の API は `c2rUrl()`)
- 取り込んだ画面には CSP(`script-src 'self'`。スタジオだけ YouTube の埋め込みのため `https://www.youtube.com`・`https://s.ytimg.com` も許す。`src/home/mount.py`)がかかる: インラインの `<script>`・`onclick=` は動かない。書き込み系の API は合言葉(`X-YTT-Token`)が要る(上の関数が付ける)
- ツール間で同じ名前の .py を作らない(`src/home/tests/test_mount.py` が検査)
- 画面の共通の API `api/ytt/…`(エラーの記録・窓で開く・届ける)は入口が受け持つ。ツールに `/api/ytt/` で始まる API を作らない
- 画面を離れた・戻ったで処理するときは ui-kit の `UIKit.life.onLeave / onReturn` を使う(visibilitychange を直接使わない)。`'blur'`(隣の窓へ)のときは保存だけにして、再生の停止・重い処理はしない
- 画面の不具合を調べるときは、まず画面のエラーの記録 `%LOCALAPPDATA%\youtube-tools\app\logs\client-errors.jsonl` を見る
- 文字起こしのサーバー側のプロセスで numpy・faster_whisper・ctranslate2・sherpa_onnx を import しない(認識はワーカーの中だけ。`src/editor/tests/test_worker.py` が検査)。`src/home/live_align_worker.py`(numpy)も子プロセスだけ
- 【高】同一オリジン化による XSS の影響拡大: 1 つのポートにまとめたので、1 つの画面の XSS で全ツールの API が使える。CSP `script-src 'self'` を維持する、書き込み系の POST に合言葉、Host / Origin 検査は ytt_core の 1 か所で全 API にかける、パスは許可したフォルダの中だけ
- 文字起こしと切り抜きの紐づけの規則と、パックの有無の判定(`pack_info`)は `src/ytt_core/txindex.py` だけ。他のツールのデータは読むだけで書き換えない
- Resolve パックは `src/cut2resolve/pack.py` だけが作る(編集の `resolve_export.create_package` は pack を呼んで zip にするだけ)。パックの作り方を変えたら `dev/tests/test_resolve_pack_contract.py` を通す。編集側に Resolve 用の計算を書き足さない(`docs/design/resolve-pack-unification.md`)
- 盛り上がりの式は `src/ytt_core/excite.py` の 1 か所(線 D の L1。2026-10-07)。スタジオの `analyze.py` は excite を読んで同じ名前を再公開するだけ。式を直すときは `src/ytt_core/tests/data/excite_golden.json`(移す前の値)が食い違うので、意図した変更なら golden を作り直して WORKLOG に書く。配信中の検出(`Online`・`PeakBook`)も同じ式を使う

## ユーザーについて(応答の仕方)
- **応答は日本語**で。Web/バックエンド開発のエンジニア。動画編集は初心者。基礎的な文法・ライブラリの説明は不要、**実装判断の理由**が知りたい
- コードを示すときは、なぜその実装にしたかを 1〜2 文添える。複数案があれば、保守性・性能などのトレードオフを簡潔に比較する
- セキュリティ・エッジケースのリスクは省略せず指摘する。動画編集の専門用語は、初めて使うときに軽く説明する
- **中間報告を徹底する**: 作業のきりのいいところで、10〜20 分ごとを目安に、何が終わって次に何をするかを短く報告する。確認が要る点は仮で進めて最後にまとめて確認する(2026-10-03・10-07 ユーザー指示)

## 動作環境(ユーザーの PC)
- Windows 11。リポジトリは `C:\dev\youtube-tools`。CPU i9-12900KF(10-04 に替えた)・メモリ 32GB・GPU **AMD Radeon RX 7800 XT**(CUDA は使えない → faster-whisper は CPU。GPU は whisper.cpp Vulkan・llama.cpp Vulkan)
- **動かすのもテストも Python 3.10**(`py -3.10`。faster-whisper 1.2.1・sherpa-onnx 1.13.8・Playwright 1.63.0 + chromium は 3.10 に入っている。版は `setup/requirements*.txt` に固定)。`python` と打つと Microsoft Store の別名に当たって動かないことがある。`setup/requirements*.txt` は英数字だけで書く
- ffmpeg・ffprobe は winget の Gyan.FFmpeg 9.0.2。yt-dlp 2026.08.19・Deno 2.9.7(yt-dlp が使う)。Lua は無い(Lua を実行するテストは skip)。Visual Studio Build Tools 2022(C++)と Vulkan SDK 1.4.363.0 はある。whisper.cpp v1.9.4 Vulkan は作業データの `transcribe\bin\whisper.cpp-v1.9.4-vulkan\`。llama.cpp b11326 Vulkan と Qwen3-ASR 1.7B は 10-06 に取得済み。Whisper のモデルは large-v3・small
- **【Claude のデスクトップアプリ(Code タブ)から動かす AI の注意】** アプリが MSIX のパッケージなので、AI のシェル(とそこから起動したプロセス)が `%LOCALAPPDATA%` に書いたファイルは、本物の場所ではなく `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Local\` の写しに入る。AI からは両方が重なって見えるので気づけないが、ユーザーが start.bat で動かす入口からは見えない。**作業データへ AI が直接書くときは、パッケージの外のプロセスで書く**(`Invoke-CimMethod Win32_Process Create` で cmd・robocopy を動かす)か、入口の API(画面)を通す。本物の中身を確かめるときも同じ形で dir する。AI が起動した入口もパッケージの中で動く。`C:\dev\`・`D:\`・`E:\`・`%USERPROFILE%` の直下は写しにならない。Playwright の chromium(`%LOCALAPPDATA%\ms-playwright`)は写しの中だけ(AI が流す画面のテストは動く)
- 2026-10-03 に Windows を入れ直した(作業データは消えて作り直されている。入口が `D:\backup\youtube-tools-data` へ自動でバックアップする)。Windows のユーザー名は以前と違う(資料の `C:\Users\you11\...` のような具体的な名前は `<ユーザー名>` と読む)
- 入口が起動中の AI の作業: 入口の子プロセス(録画の部品など)がフォルダを掴んでいることがある。AI はユーザーのプロセスを止めない(ユーザーに「すべて終了」やタスク マネージャーを頼む)
