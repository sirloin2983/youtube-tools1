# youtube-tools1 — YouTube ショート動画の編集支援ツール群

このリポジトリで作業する AI(Claude・GPT/Codex のどちらも)の共通の前提です。Codex はこのファイルを、Claude Code は CLAUDE.md 経由で読みます。

## 最初にやること
1. `docs/ROADMAP.md` を読む(全体のまとめ: 済んだこと・進行中・待ち・保留と、**どの文書を読めばよいかの索引**)
2. `docs/WORKLOG.md` の最後の数件を読む(誰が・いつ・何を変えたか、**未コミットのファイル**、未完了、注意)
3. `git status` と `git log -5 --oneline` を見る(下の「複数の AI で作業するときのルール」)
4. 触るツールの `AGENTS.md`(今は `editor/AGENTS.md` だけ)と `README.txt` を読む

## 全体の形
- 3つのツール(切り抜きスタジオ `studio/`・編集 `editor/`・cut2resolve `cut2resolve/`)と、それをまとめる入口(ホーム `home/`)がある。どれも Python 標準ライブラリ中心のローカルサーバー + ブラウザの画面で、ユーザーの PC 上だけで動く。外部サービスへ動画・音声を送らない方針
- **「編集」**(2026-09-26。`docs/design/edit-tool-design.md`): 文字起こしツールと cut2resolve の画面を1つにした。画面は `editor/` の3つのタブ(1 文字起こし / 2 カット / 3 パック)。
  カット(残す区間)は `transcripts/<id>.edit.json`。cut2resolve は画面を消して、パックを作る部品(pack.py)・API(serve.py)・CLI として残る(入口にカードを出さない。`/cut2resolve/` の画面は「編集」へ転送)
- 普段はリポジトリ直下の `start.bat` → 入口(`home/launch.py`、http://localhost:8700/)が1つのプロセスの中で3ツールを取り込んで動かす:
  `/studio/`(切り抜きスタジオ)・`/transcribe/`(編集)・`/cut2resolve/`(パックを作る API)。
  文字起こしの認識(faster-whisper・sherpa-onnx)だけは別プロセスのワーカー(`editor/tx_worker.py`)で動く(落ちても入口・他のツールは止まらない)
- 各ツールの `start.bat` での単独起動は 2026-09-26 にやめた(ユーザー決定)。起動は `start.bat` だけ。serve.py の単独で動く部分は、入口に取り込めなかったときの子プロセスとテストのために残す
- ユーザー向けの使い方の全体はリポジトリ直下の `README.txt`(09-26 に一本化)。各ツールの `README.txt` は細かい使い方と変更の記録
- **作業データはリポジトリの外** `%LOCALAPPDATA%\youtube-tools\<ツールID>\`(2026-09-26。`ytt_core/datadir.py`・`docs/spec/data-location.md`)。以前の各ツールのフォルダの中からは最初の起動でコピーする(元は消さない)
- 流れ: スタジオで配信から区間を選んで書き出す → 「編集」で字幕を作って直し(1)・カットを決め(2)・DaVinci Resolve 用のパック(カット + Text+ 字幕。中身は cut2resolve の pack.py)を作る(3)。受け渡しの形式は `docs/spec/pipeline.md`
- 1つのアプリへの統合計画(`docs/design/integration-plan.md`)は段階0〜7 まで完了(入口・ytt_core・3ツールの取り込み・作業データの外出し・案件・まとめて実行・Edge の専用の窓)。
  統合計画の正本は claude.ai の Claude Docs「動画編集ツール 統合計画」(`docs/design/integration-plan.md` は写し)。**これからの作業は `docs/ROADMAP.md` の 2**(線 A = 使い勝手と機能の段1〜8(AI だけで進められる)・線 B = 文字起こしの精度改善 `docs/plan/transcription-overhaul-plan.md`(ユーザーの評価用の校正が律速))。全体の状態も `docs/ROADMAP.md`
- **別のツール: ホロカラー(`holo-colors/`。2026-09-27)** … ホロライブのメンバーカラーをキー(Ctrl+Alt+H)で呼び出してコピーする Windows の常駐アプリ。
  **主に友人が使う**ので Python ではなく C#(WinForms)。Windows に入っている .NET Framework 4 の csc で作る(`build.bat`。C# 5 まで)。アプリ自体は入口・3ツールとつながっていないが、
  メンバーの色の一覧 `holo-colors/members.json`(と作業データの自分の色)は `ytt_core/colors.py` が読み、字幕の色に使う(形を変えるときは colors.py とそのテストも)。
  設計と決めたこと・メンバーの色の出典: `docs/design/holo-colors.md`、使い方: `holo-colors/README.txt`

## フォルダと、変えたら通すテスト
| フォルダ | 役割 | 変えたら通すテスト(**すべてリポジトリ直下から実行**。テストは各フォルダの `tests/`) |
| --- | --- | --- |
| `home/` | 入口・ホーム(ランチャー・取り込み `mount.py`・案件 `cases.py`・まとめて実行 `autorun.py`・窓で開く `appwindow.py`・画面のエラーの記録 `clientlog.py`・作業データのバックアップ `backup.py`・パックを友人へ届ける `deliver.py`)。`home/README.txt` | `python -m unittest home/tests/test_launch.py home/tests/test_mount.py home/tests/test_cases.py home/tests/test_autorun.py home/tests/test_window.py home/tests/test_intake.py home/tests/test_backup.py home/tests/test_deliver.py`、`python home/tests/e2e_portal.py`、`python home/tests/e2e_autorun.py`、`python home/tests/e2e_window.py`(窓・エラーの記録・解析の設定。段階7)、依頼の受付の画面を変えたら `python home/tests/e2e_intake_ui.py`、バックアップの画面を変えたら `python home/tests/e2e_backup_ui.py`、キー配置(ui-kit の `UIKit.keymap`・ホームの設定の keymap)を変えたら `python home/tests/e2e_keymap.py` |
| `studio/` | 切り抜きスタジオ(配信の解析・マーク・書き出し) | `python -m unittest studio/tests/test_studio.py studio/tests/test_api.py studio/tests/test_analyze.py studio/tests/test_exporter.py studio/tests/test_handoff.py studio/tests/test_robustness.py studio/tests/test_file_recovery.py`、`node --test studio/tests/test_review.cjs`、`python studio/tests/e2e_analyze.py`、画面を変えたら `python studio/tests/e2e_ui.py` と `python studio/tests/e2e_ui.py --mounted`(`studio/tests/e2e_review.py` はテストではなく手で見るための見本サーバー) |
| `editor/` | 「編集」(文字起こし(faster-whisper・話者判別・校正画面・精度測定)・カット `cut.js`・パック `pack-tab.js`) | `editor/AGENTS.md` の「テストの実行」(画面を変えたら `python editor/tests/e2e_ui_mounted.py` と `e2e_edit_tabs.py`・`e2e_edit_cut.py`・`e2e_edit_pack.py`・`e2e_edit_voices.py` も) |
| `cut2resolve/` | DaVinci Resolve への受け渡し(EDL・Text+ パック)の部品と CLI。API は serve.py(画面は 2026-09-26 に「編集」へ統合して消した。`/` は案内だけ) | `python -m unittest cut2resolve/tests/test_cut2resolve.py cut2resolve/tests/test_pack.py cut2resolve/tests/test_serve.py`(API を変えたら `python editor/tests/e2e_edit_pack.py` も。CLI の `cut2resolve.py` はフォルダと同じ名前なので、テストは importlib で読む) |
| `ytt_core/` | 共通部品(書き込み `fsio`・`.runtime`・受け渡しの形式と途中のファイルの置き場所 `schemas`・Host/Origin 検査 `httpsec`・作業データの置き場所 `datadir`・重い処理の同時実行の上限 `jobs`・文字起こしの読み取りと紐づけ `txindex`・名前 → メンバーカラー `colors`・ffmpeg などの場所 `tools`・リポジトリの中のフォルダ名 `layout`(フォルダ名を知る場所はここを読む。2026-09-30)・評価データ(送る用 zip)の形式と検証 `evaldata`(友人用簡易版。2026-10-02)・素材を 30fps にそろえる `normalize`(2026-10-04 Q1)) | `python -m unittest ytt_core/tests/test_ytt_core.py ytt_core/tests/test_evaldata.py ytt_core/tests/test_normalize.py` と、使っている各ツールのテスト |
| `ui-kit/` | 共通の見た目と画面の共通の動き(テーマ・他のツール・入口へ戻る・一覧の部品・離れた/戻った `UIKit.life`・エラーの記録 `UIKit.report`・窓のリンク `UIKit.win`・日時の書式 `UIKit.fmt`。`ui-kit/README.md`)の正本。**画面を直すときは `docs/spec/ui-guidelines.md`(用語集・ヘッダー・ボタンと札・一覧の見せ方)と `docs/spec/usability-heuristics.md`(Nielsen の 10 の原則。原則に沿った見直しは Cowork が行う)に合わせる**。`python dev/sync_ui_kit.py` で各ツールへ写す(写しは手で直さない) | `python -m unittest dev/tests/test_ui_kit_sync.py`・`python ui-kit/tests/e2e_styleguide.py` と各ツールの画面のテスト |
| `dev/` | 開発用の道具(push.bat の検査 `push_helper.py`・`removals.txt`・ui-kit の同期・3ツールの通し確認・精度の基準の計算・精度を測る道具 `eval_asr.py`・見本のデータで全画面を動かす `demo_env.py`)・Resolve パックの契約テスト | `python dev/tests/e2e_pipeline.py`(3ツールの通し確認)・`python dev/tests/e2e_datadir.py`(作業データの置き場所とコピー)・`python -m unittest dev/tests/test_cleanup_legacy_data.py`(以前の場所の片付け。本体は `setup/`)・`python -m unittest dev/tests/test_push_helper.py`(push.bat の削除とコミット前の検査)。友人用簡易版の届いた zip の取り込みチェック `eval_import.py` を変えたら `python -m unittest dev/tests/test_eval_import.py`。文字起こしの採点(serve.py の `_groups`・`norm_cer`・`lev_counts`・`doc_metrics`)か精度を測る道具 `eval_asr.py` を変えたら `python -m unittest dev/tests/test_eval_asr.py`。`cut2resolve/` か文字起こしの `resolve_export.py`・`pipeline_io.py` を変えたら `python -m unittest dev/tests/test_resolve_pack_contract.py`(**単独のコマンドで**。cut2resolve と文字起こしの部品を読み込むので、`home/tests/test_mount.py` と同じ unittest に渡すと部品の名前が重なって落ちる) |
| `setup/` | ユーザーが実行するインストールと片付け(`install.bat`・`install-gpu.bat`・`install-diarize.bat`・Mac の `.command`(`editor/.venv` を作る)・`requirements.txt`・`cleanup_legacy_data.bat`) | `.bat` は ASCII だけ。片付けのテストは `dev/tests/` |
| `request-sender/` | 友人が依頼を送るプログラム(C# 5・WinForms。Dropbox の API でアプリ専用のフォルダへ。`docs/design/friend-intake.md`)。受け取る側は `home/intake.py`。鍵(`config.json`)はコミットしない | `request-sender\build.bat`(コンパイル → テスト → `dist/RequestSender.zip`)。鍵を作る `dev/dropbox_auth.py` を変えたら `python -m unittest dev/tests/test_dropbox_auth.py`。盛り上がりの検出を人の判定の記録で測る道具 `dev/eval_marks.py`(読むだけ。Q3)を変えたら `python -m unittest dev/tests/test_eval_marks.py`。話者の判別・声の照合を人の最終で測る `dev/eval_speakers.py`(読むだけ。Q3)を変えたら `python -m unittest dev/tests/test_eval_speakers.py` |
| `holo-colors/` | ホロカラー(メンバーカラーをコピーする Windows の常駐アプリ。C# 5・WinForms。`src/`・`members.json`・`tests/`) | `holo-colors\build.bat`(コンパイル → テスト 31 件 → `dist/HoloColors.zip`)。キー・窓の動きを変えたら `python holo-colors/tests/e2e_holo_colors.py`(本物のキー入力を送る。流す間は触らない) |
| `recorder/` | 録画の部品(線 D のリアルタイム切り抜き。**既定はオフ**。入口と別のプロセス・streamlink + ffmpeg の HLS・API と合言葉。`recorder/AGENTS.md`) | `python -m unittest recorder/tests/test_recorder.py`、入口の側(`home/live.py`・`live.*`)を変えたら `python -m unittest home/tests/test_live.py` と `python home/tests/e2e_live.py` |
| `docs/` | 作業記録(ROADMAP・WORKLOG・HANDOVER)と資料(`spec/` 今の決まり・`plan/` これからの計画・`design/` 済んだ設計・`archive/` 古い経緯。下の「資料の場所」) | — |

- フォルダ名は 2026-09-30 に変えた(段0。`app/`→`home/`・`clip-studio/`→`studio/`・`transcribe-tool/`→`editor/`・`tools/`→`dev/`・`setup/`、`start-all.bat`→`start.bat`。対応表は `docs/plan/phase0-restructure.md`)。
  **フォルダ名と識別子は別**: `/api/ping` の `"clip-studio"`・`"transcribe-tool"`、JSON の tool.name・schema、作業データの ID(`app`・`studio`・`transcribe`)は互換のため変えていない(grep で当たっても直さない)

- 画面のテストは Playwright(chromium)+ ffmpeg が必要(入れ方は `setup/requirements-dev.txt` の先頭のコメント)。Playwright 同梱の chromium は H.264 を再生できない(動画の再生まで確かめるテストは webm で作る)
- ツールを一時フォルダに写して動かすテストが多い。新しいファイルを足したら、写すファイルの一覧(各 e2e の先頭)にも足す
- **サーバーを動かすテストは先頭で `os.environ.setdefault("YTT_DATA_DIR", "inplace")`**(忘れると移し済みの PC で本物の作業データを読み書きする。`ytt_core/tests/test_ytt_core.py` が検査)

## 資料の場所(正本はこのリポジトリ)
- **資料の正本はこのリポジトリ**(2026-09-26 ユーザー決定)。claude.ai の Project の `claude/*.md` は古い写しで、根拠にしない(例外: 統合計画は Claude Docs が正本)
- **文書の索引と、それぞれの状態(規則 / 進行中 / 完了した設計 / 古い資料)は `docs/ROADMAP.md` の 8**。迷ったらそこから探す。**これからの作業の順番は ROADMAP の 2(線 A = 段1〜8・線 B = 精度改善)、各段の細かい計画は `docs/plan/`**
- 今の仕様 = 各ツールの `README.txt`(ユーザー向け)+ `AGENTS.md`(AI 向け)+ コード。ツール間の受け渡し: `docs/spec/pipeline.md`
- `docs/archive/project/`・`docs/archive/review/`・`docs/archive/TRANSCRIPTION_V2_DESIGN.md` は古い経緯(**多くは数版前のまま**)。「なぜそう決めたか」を調べるときだけ読む
- 計画・設計の文書の先頭には「状態(日付)」の1行を置く(済んだ・進行中・未実装)。状態が変わったら、その1行と `docs/ROADMAP.md` を直す
- 新しい文書は種類で置く: 今の決まり・仕様 → `docs/spec/`、これからの計画 → `docs/plan/`、済んだ設計・決定の記録 → `docs/design/`、使わなくなった古い資料 → `docs/archive/`。WORKLOG と `docs/ROADMAP.md` からリンクする
- 過去の記録(WORKLOG・`docs/design/`・`docs/archive/`)の中の旧いパスは書き換えない(当時の記録のため)

## 開発のルール
- 実行時データ・個人データ・秘密情報はコミットしない(`.gitignore` 参照: transcripts/ dataset/ models/ exports/ clips/ config.json など)。リポジトリは Public にする方針なので特に注意。
  push.bat はコミットの前に `dev/push_helper.py check` で調べ、キーの形・個人データの名前・動画・5MB 超があれば止める(誤検出なら検査を直す)
- 各ツールで版を上げるときは、**serve.py の SERVER_VERSION・画面の APP_VERSION・README.txt の見出し**を必ず同時に上げる(食い違うと画面に赤い帯が出る)。
  APP_VERSION の場所: スタジオ `core.js`、文字起こし `app.js`、cut2resolve は `cut2resolve_core.py` の VERSION 1か所。入口は `home/launch.py`
- 各ツールの起動の約束(`serve.py [ポート] --no-open`・`.runtime/<ID>.json`・`/api/ping`・SIGTERM/SIGBREAK で後始末して終わる)は入口が使っている。
  変えるときは `home/launch.py` と `python -m unittest home/tests/test_launch.py` も確認する(`docs/design/integration-plan.md` の「段階1の約束」)
- コミット: ユーザーの push.bat は `git add -A` でまとめてコミットし、メッセージは「更新 日付 時刻」になる。**何をなぜ変えたかは WORKLOG に書く**(履歴の説明は WORKLOG が担う)。
  git を使える AI が自分でコミットするときは、日本語で要約を書く(`"[Claude] 要約"` / `"[GPT] 要約"`)

## 複数の AI で作業するときのルール(Claude・GPT/Codex 共通)
このリポジトリは Claude(Cowork / Claude Code)と GPT(Codex)の両方が編集する。**正は PC の作業フォルダ(C:\dev\youtube-tools。2026-09-30 に Desktop\youtube-test から移した)とその git**。
ユーザーは git の手作業を面倒に感じているので、情報の共有は AI 側でこのルールに沿って自動で行う。

作業を始める前:
1. `docs/WORKLOG.md` の最後の数件を読む
2. `git status` と `git log -5 --oneline` を見る。未コミットの変更は、WORKLOG の「未コミット」に書かれたファイルと照らし合わせる。
   **自分が変えていない未コミットの変更は、他の AI の作業途中**。上書き・破棄しない。触る必要があるなら、先に「WIP: 他のAIの作業途中」としてコミットしてから始めるか、ユーザーに確認する
3. 版番号(各ツールの SERVER_VERSION / APP_VERSION)を実際のファイルと WORKLOG で確認する(別々の AI が同じ番号を付けないため)

作業中:
- ファイルは差分で直す。**古い控えからのファイル丸ごとの上書き・zip での上書き配布はしない**
  (2026-09-23、Claude が配った zip で GPT の変更が上書きされて消えた事故があった。`docs/WORKLOG.md` 参照)
- 設計の変更・依存の追加・費用がかかること・既存機能の削除は、実装の前にユーザーに確認する
- ファイルの移動・改名は `git mv` を**1コミットにまとめ**、前後で WORKLOG に告知する。長く分かれたブランチは使わない(同じフォルダを2つの AI が使うため、切り替えると相手のファイルが入れ替わる)

サブエージェント(並列の AI)を使うとき(2026-09-30 ユーザー決定。どのセッションでも行う):
- 分けられる作業(担当するファイルが重ならない調べもの・直し)は、サブエージェントに分けて並列で進め、速くする。担当するファイル・フォルダを重ならないように決め、まとめ役が最後に全体のテストと境目の漏れを確かめる
- **仕事の難しさに合わせてモデルを選ぶ**(速さ・費用・質の釣り合い):
  - 探す・数える・一覧を作るだけ(読むだけ)… 小さく速いモデル(Claude なら Haiku)
  - 決まった規則での直し・テストの実行と直し(指示がはっきりしている)… 中くらいのモデル(Claude なら Sonnet)
  - 設計の判断・原因の分からない不具合・影響が広い部品(入口・取り込み・データの置き場所・セキュリティ)… いちばん強いモデル(Claude なら Opus)
- 選んだモデルと理由は、ユーザーへの報告に1行で書く

作業を終えるとき:
1. `docs/WORKLOG.md` の**末尾**に記録を追記する(書式は WORKLOG の先頭)。コミットしていないなら「未コミット: <ファイル一覧>」を必ず書く。
   進行中・待ち・保留が変わったら `docs/ROADMAP.md` の該当の1行も直す
2. git を使える AI は、変更したファイルと WORKLOG をコミットする(`git add <変えたファイル> docs/WORKLOG.md` → `git commit`)。push はユーザーが push.bat で行う(AI は push しなくてよい)
3. 長く使う設計・決定は `docs/` に文書で残し、WORKLOG からリンクする

Claude(Cowork。クラウドから PC のフォルダに読み書きする)の注意:
- PC で git・ファイルの移動・削除ができない。WORKLOG への追記までを行い、コミットは次に git を使う AI か push.bat に任せる。
  **ファイルを消すときは `dev/removals.txt` に1行ずつ書く**(ユーザーの push.bat が `git rm` する。git が管理しているファイルだけ。`dev/push_helper.py`)。移動は WORKLOG に手順を書いて頼む
- 同じファイルを何度も書き込むと、2回目以降が前の内容のまま書かれることがあった(2026-09-25)。**書き込んだら読み直して、手元の内容と一致することを確かめる**
- 起動中の入口・ツールは古いコードのまま動いている。コードを直したら、ユーザーに「すべて終了」→ start.bat で起動し直してもらう

## 統合作業の決まりとリスク(段階3 以降。作業する AI は必ず守る)
詳しい理由は `docs/design/integration-plan.md` の「主なリスクと対策」と「段階3-1〜3-3で決めたこと」。【高】は特に優先。

担当表(担当中は、他の AI はそのツール・ファイルを触らない。変わったら WORKLOG に書く):
- 統合作業(`home/`・`ytt_core/`・3ツールの取り込み)と `cut2resolve/` 全体(Text+ を含む): Claude が主担当(ユーザー決定 2026-09-25・26)
- 文字起こしツール(`editor/`)と3ツール・入口の画面(`studio/` の画面・`ui-kit/` を含む): Claude が担当(ユーザー決定 2026-09-26。**2026-09-29 ユーザー決定: 見直しが終わったあとも Claude だけ。GPT は調査と文書まで**)
- 「編集」ツール(文字起こし + cut2resolve の統合。`docs/design/edit-tool-design.md`)の実装: Claude Code(PC)が担当(ユーザー決定 2026-09-26。`editor/`・`cut2resolve/`・`home/`・`ui-kit/`・`studio/review.js` に及ぶ)。
  E1〜E6 は 2026-09-26 に実装済み。実機確認の結果の直しも同じ担当
- ホロカラー(`holo-colors/`・`docs/design/holo-colors.md`): Claude Code(PC)が担当(2026-09-27 作成)
- 友人からの依頼の受付(`home/intake.py`・`request-sender/`・`docs/design/friend-intake.md`): Claude Code(PC)が担当(2026-09-30 作成)
- 画面の全面見直し(`.design/ui-overhaul/DESIGN_BRIEF.md`。ユーザー承認 2026-09-27)の実装: Claude Code(PC)が担当(段1〜5 実装済み 2026-09-27。実装で決めた細部は `.design/ui-overhaul/IMPLEMENTATION.md`)
- 上に無いツールを触るときは、始める前に WORKLOG に「担当: 〇〇」と書く

取り込みの決まり:
- 画面は**相対パス**で部品を読み、API・動画の URL は1か所の関数で作る(絶対パス `/xxx` を書かない)。スタジオは `Studio.api`、編集は `app.js` の `apiUrl()` / `api()`(cut2resolve の API は `c2rUrl()`)
- 取り込んだ画面には CSP(`script-src 'self'`。スタジオだけ YouTube の埋め込みのため `https://www.youtube.com`・`https://s.ytimg.com` も許す。`home/mount.py`)がかかる: インラインの `<script>`・`onclick=` などは動かない。書き込み系の API は合言葉(`X-YTT-Token`)が要る(上の関数が付ける)
- ツール間で同じ名前の .py を作らない(`home/tests/test_mount.py` が検査)
- 画面の共通の API `api/ytt/…`(エラーの記録・窓で開く)は入口が受け持つ(`home/mount.py` がツールに渡さない)。ツールに `/api/ytt/` で始まる API を作らない
- 画面を離れた・戻ったで処理するときは ui-kit の `UIKit.life.onLeave / onReturn` を使う(visibilitychange を直接使わない。窓を並べると隣の窓のクリックでタブの切り替えは来ない)。
  `'blur'`(隣の窓へ)のときは保存だけにして、再生の停止・重い処理はしない
- 画面の不具合を調べるときは、まず画面のエラーの記録 `%LOCALAPPDATA%\youtube-tools\app\logs\client-errors.jsonl`(入口の `/api/log?tool=client`)を見る
- 文字起こしのサーバー側のプロセスで numpy・faster_whisper・ctranslate2・sherpa_onnx を import しない(認識はワーカーの中だけ。`editor/tests/test_worker.py` が検査)

リスク:
- 【高】AI 間の同時編集の競合: 上の担当表と「複数の AI で作業するときのルール」を徹底する
- 【高】同一オリジン化による XSS の影響拡大: 1つのポートにまとめたので、1つの画面の XSS で全ツールの API(ファイルの書き込み・Resolve へのスクリプト登録)が使える。
  CSP `script-src 'self'` を維持する、書き込み系の POST に合言葉(CSRF トークン)、Host / Origin 検査は ytt_core の1か所で全 API にかける、パスは許可したフォルダの中だけ
- 文字起こしと切り抜きの紐づけの規則と、パックの有無の判定(`pack_info`)は `ytt_core/txindex.py` だけ(入口の案件・スタジオのセリフ・文字起こしの履歴が共通で使う)。他のツールのデータは読むだけで書き換えない
- Resolve パックは `cut2resolve/pack.py` だけが作る(2026-09-26 一本化。文字起こしの `resolve_export.create_package` は pack を呼んで zip にするだけ)。
  パックの作り方を変えたら `dev/tests/test_resolve_pack_contract.py` を通す(文字起こしの zip と cut2resolve のパックが同じ中身・一本化の前と同じ区間と字幕)。
  経緯と旧との違いは `docs/design/resolve-pack-unification.md`。文字起こし側に Resolve 用の計算を書き足さない(二重実装に戻さない)
- 【高】古い写しを根拠にした判断: `claude/*.md` と `docs/archive/project/` は古い。食い違いを見つけたら、今のコード・README・AGENTS.md を正とする(統合計画だけは Claude Docs が正本)
- CPU の取り合い(重い処理は `ytt_core/jobs.py` の `SLOTS` を通す。新しく重い処理を足すときも必ず通す。09-26)、データ移行(コピーのみ・元は残す・削除はユーザー確認後。`ytt_core/datadir.py`)、Public リポジトリへの個人データ混入(作業データはリポジトリの外。09-26 実装)

## ユーザーについて(応答の仕方)
- **応答は日本語**で。Web/バックエンド開発のエンジニア。動画編集は初心者。基礎的な文法・ライブラリの説明は不要、**実装判断の理由**が知りたい
- コードを示すときは、なぜその実装にしたかを1〜2文添える。複数案があれば、保守性・性能などのトレードオフを簡潔に比較する
- セキュリティ・エッジケースのリスクは省略せず指摘する
- 動画編集の専門用語は、初めて使うときに軽く説明する(一度説明した語は以後そのまま使ってよい)
- 長い作業で文脈が圧縮されそうなときは、HANDOVER(引き継ぎ)資料と「次のセッションにそのまま貼れる再開用の指示文」を作る
- **中間報告を徹底する**(2026-09-26 ユーザー指示): 作業のきりのいいところで、10〜20 分ごとを目安に、何が終わって次に何をするかを短く報告する

## 動作環境(ユーザーの PC)
- Windows。このリポジトリは PC 上の `C:\dev\youtube-tools` にある(2026-09-30 まで `Desktop\youtube-test`)
- CPU は Intel Core i9-12900KF(2026-10-04 に確認。以前の i9-13900KF はよく落ちたので替えた)、メモリ 32GB。GPU は **AMD Radeon RX 7800 XT**(16GB)(NVIDIA ではないので CUDA は使えない → faster-whisper は CPU で動く。GPU 前提の提案をしない)
- Python・ffmpeg はインストール済み(`setup\install.bat`・リポジトリ直下の start.bat を使う)。**動かすのは Python 3.10**(`py -3.10`。faster-whisper 1.2.1・sherpa-onnx 1.13.8 などは 3.10 に入っている。
  版は `setup/requirements*.txt` に固定。段10-3 = 2026-10-01)。start.bat・install*.bat・home/start_hidden.vbs は `py -3.10` → `py -3` → `python` の順に選ぶ。
  **2026-10-03 に Windows を入れ直した**(作業データ `%LOCALAPPDATA%\youtube-tools\` は消えて、新しく作り直されている。10-03 から入口が `D:\backup\youtube-tools-data` へ自動でバックアップする = `docs/spec/data-location.md`)。入れ直しのあとは、miniconda は無い。Python は py ランチャーの 3.10.11(winget で入れた)と 3.12(普通の Python。`py` の既定。追加の部品は入れていない)。動かすのも、テストを流す(e2e を含む)のも 3.10。
  Playwright 1.63.0 と chromium は 3.10 に入れた(`py -3.10 -m pip install -r setup\requirements-dev.txt` → `py -3.10 -m playwright install chromium`)。単体テストは 3.10 でも通る(段10-3 で確かめた)。
  `setup/requirements*.txt` は **英数字だけ**で書く(以前の PC の pip 22 は Windows の文字コードで読み、日本語のコメントで落ちた。今の pip は 23.0.1 だが、決まりはそのまま残す)。node は PATH に無い(Playwright に入っている node を `dev/run_editor_suite.py` の find_node が自動で見つけて使う)。
  **`python` と打つと Microsoft Store の別名(WindowsApps\python.exe)に当たって動かないことがある**。資料のテストのコマンドは `python ...` と書いてあるが、この PC では `py -3.10 ...` と読み替える。
  ffmpeg・ffprobe は winget の Gyan.FFmpeg 9.0.2(full_build。PATH で先に見つかる)。yt-dlp 2026.08.19(winget の yt-dlp.yt-dlp)と Deno 2.9.7(winget の DenoLand.Deno)も入っている(今の yt-dlp は YouTube の取得に JavaScript の実行環境 Deno を使う)。
  Lua は無い(`cut2resolve/tests/test_pack.py` の Lua を実行するテストは skip になる)。Visual Studio Build Tools 2022(C++。17.14)と Vulkan SDK 1.4.363.0 は 10-04 に入った。
  whisper.cpp v1.9.4 の Vulkan 版は 10-04 に作り直した(作業データの `transcribe\bin\whisper.cpp-v1.9.4-vulkan\`。RX 7800 XT を認識)。Whisper の ggml のモデル・Qwen3-ASR のモデルは次に使うときに取得し直す。
- **【Claude のデスクトップアプリ(Code タブ)から動かす AI の注意】(2026-10-04 に分かった)** アプリが MSIX のパッケージなので、AI のシェル(とそこから起動したプロセス)が `%LOCALAPPDATA%` に書いたファイルは、
  本物の場所ではなく `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Local\` の写しに入る。AI からは両方が重なって見えるので気づけないが、ユーザーが start.bat で動かす入口からは見えない
  (10-03〜04 に AI が戻したパック 15件・声の登録・編集の設定、作った whisper.cpp がこれで本物の場所に無かった → 10-04 に写した)。
  **作業データ(`%LOCALAPPDATA%\youtube-tools\`)へ AI が直接書くときは、パッケージの外のプロセスで書く**(例: `Invoke-CimMethod Win32_Process Create` で cmd・robocopy を動かす。WMI から作ったプロセスはパッケージの外になる)。
  本物の中身を確かめるときも同じ形で dir する。できれば入口の API(画面)を通して書く。AI が入口・start_hidden.vbs を起動すると、その入口もパッケージの中で動く(ユーザーに start.bat・デスクトップのショートカットで起動し直してもらう)。
  `C:\dev\`・`D:\`・`E:\`・`%USERPROFILE%` の直下は写しにならない。Python 3.10 の部品(faster-whisper・sherpa-onnx・Playwright)は本物の場所に入っている(10-04 にパッケージの外から確かめた)が、
  Playwright の chromium(`%LOCALAPPDATA%\ms-playwright`)は写しの中だけ(AI が流す画面のテストは動く。パッケージの外で流すなら `py -3.10 -m playwright install chromium` をし直す)
- Whisper のモデルは small だけ取得済み(ほかは次に使うときに取得し直す)。Windows のユーザー名は以前と違う(資料の `C:\Users\you11\...` のような具体的な名前は `<ユーザー名>` と読む)
