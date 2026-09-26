# youtube-tools1 — YouTube ショート動画の編集支援ツール群

このリポジトリで作業する AI(Claude・GPT/Codex のどちらも)の共通の前提です。Codex はこのファイルを、Claude Code は CLAUDE.md 経由で読みます。

## 最初にやること
1. `docs/WORKLOG.md` の最後の数件を読む(誰が・いつ・何を変えたか、**未コミットのファイル**、未完了、注意)
2. `git status` と `git log -5 --oneline` を見る(下の「複数の AI で作業するときのルール」)
3. 触るツールの `AGENTS.md`(今は `transcribe-tool/AGENTS.md` だけ)と `README.txt` を読む

## 全体の形
- 3つのツールと、それをまとめる入口がある。どれも Python 標準ライブラリ中心のローカルサーバー + ブラウザの画面で、ユーザーの PC 上だけで動く。外部サービスへ動画・音声を送らない方針
- 普段はリポジトリ直下の `start-all.bat` → 入口(`app/launch.py`、http://localhost:8700/)が1つのプロセスの中で3ツールを取り込んで動かす:
  `/studio/`(切り抜きスタジオ)・`/transcribe/`(文字起こし)・`/cut2resolve/`(Resolve への受け渡し)。
  文字起こしの認識(faster-whisper・sherpa-onnx)だけは別プロセスのワーカー(`transcribe-tool/tx_worker.py`)で動く(落ちても入口・他のツールは止まらない)
- 各ツールの `start.bat` での単独起動は 2026-09-26 にやめた(ユーザー決定)。起動は `start-all.bat` だけ。serve.py の単独で動く部分は、入口に取り込めなかったときの子プロセスとテストのために残す
- ユーザー向けの使い方の全体はリポジトリ直下の `README.txt`(09-26 に一本化)。各ツールの `README.txt` は細かい使い方と変更の記録
- **作業データはリポジトリの外** `%LOCALAPPDATA%\youtube-tools\<ツールID>\`(2026-09-26。`ytt_core/datadir.py`・`docs/data-location.md`)。以前の各ツールのフォルダの中からは最初の起動でコピーする(元は消さない)
- 流れ: スタジオで配信から区間を選んで書き出す → 文字起こしで字幕を作って直す → cut2resolve で DaVinci Resolve 用のパック(カット + Text+ 字幕)にする。受け渡しの形式は `docs/pipeline.md`
- 1つのアプリへの統合計画: `docs/integration-plan.md`(段階1 = 入口、段階2 = ytt_core、段階3 = 3ツールの取り込み(3-1 スタジオ・3-2 cut2resolve・3-3 文字起こし)まで実装済み。段階4 = 作業データをリポジトリの外へ・案件ファイル(入口の `/cases.html`)・重い処理の同時実行の上限・文字起こしをスタジオへ返す(セリフの表示)、段階5 = まとめて実行(`app/autorun.py`)・ラウドネス調整、段階6 = README の一本化・単独起動の廃止 も実装済み。段階7 = 画面の形: 7-0 画面のエラーの記録・7-1 解析の設定をサーバーへ・7-2 離れた/戻ったの共通化・7-3 Edge のアプリモードの窓(試用)を実装済み。7-4 pywebview は試用のあとで判断・新着配信の監視は保留)。
  統合計画の正本は claude.ai の Claude Docs「動画編集ツール 統合計画」(`docs/integration-plan.md` は写し)

## フォルダと、変えたら通すテスト
| フォルダ | 役割 | 変えたら通すテスト(そのフォルダで実行。★はリポジトリ直下から) |
| --- | --- | --- |
| `app/` | 入口(ランチャー・取り込み `mount.py`・案件 `cases.py`・まとめて実行 `autorun.py`・窓で開く `appwindow.py`・画面のエラーの記録 `clientlog.py`)。`app/README.txt` | ★`python -m unittest app/test_launch.py app/test_mount.py app/test_cases.py app/test_autorun.py app/test_window.py`、★`python app/e2e_portal.py`、★`python app/e2e_autorun.py`、★`python app/e2e_window.py`(窓・エラーの記録・解析の設定。段階7) |
| `clip-studio/` | 切り抜きスタジオ(配信の解析・マーク・書き出し) | `python -m unittest test_studio test_api test_analyze test_exporter test_handoff test_robustness test_file_recovery`、★`node --test clip-studio/test_review.cjs`、`python e2e_analyze.py`、画面を変えたら `python e2e_ui.py` と `python e2e_ui.py --mounted` |
| `transcribe-tool/` | 文字起こし(faster-whisper・話者判別・校正画面・精度測定) | `transcribe-tool/AGENTS.md` の「テストの実行」(画面を変えたら `python e2e_ui_mounted.py` も) |
| `cut2resolve/` | DaVinci Resolve への受け渡し(EDL・Text+ パック)。画面は serve.py | `python -m unittest test_cut2resolve test_pack test_serve`、画面を変えたら `python e2e_ui.py` と `python e2e_ui.py --mounted` |
| `ytt_core/` | 共通部品(書き込み・`.runtime`・受け渡しの形式・Host/Origin 検査・作業データの置き場所 `datadir`・重い処理の同時実行の上限 `jobs`・文字起こしの読み取りと紐づけ `txindex`) | ★`python -m unittest ytt_core/test_ytt_core.py` と、使っている各ツールのテスト |
| `ui-kit/` | 共通の見た目と画面の共通の動き(テーマ・他のツール・入口へ戻る・一覧の部品・離れた/戻った `UIKit.life`・エラーの記録 `UIKit.report`・窓のリンク `UIKit.win`・日時の書式 `UIKit.fmt`。`ui-kit/README.md`)の正本。**画面を直すときは `docs/ui-guidelines.md`(用語集・ヘッダー・ボタンと札・一覧の見せ方)に合わせる**。`python tools/sync_ui_kit.py` で各ツールへ写す(写しは手で直さない) | ★`python -m unittest tools/test_ui_kit_sync.py` と各ツールの画面のテスト |
| `tools/` | 補助スクリプト(ui-kit の同期・3ツールの通し確認・精度の基準の計算・見本のデータで全画面を動かす `demo_env.py`)・Resolve パックの契約テスト | ★`python tools/e2e_pipeline.py`(3ツールの通し確認)・★`python tools/e2e_datadir.py`(作業データの置き場所とコピー)・★`python -m unittest tools/test_cleanup_legacy_data.py`(以前の場所の片付け)・★`python -m unittest tools/test_push_helper.py`(push.bat の削除とコミット前の検査)。`cut2resolve/` か文字起こしの `resolve_export.py`・`pipeline_io.py` を変えたら ★`python -m unittest tools/test_resolve_pack_contract.py`(**単独のコマンドで**。cut2resolve と文字起こしの部品を読み込むので、`app/test_mount.py` と同じ unittest に渡すと部品の名前が重なって落ちる) |
| `docs/` | 作業記録・設計・資料(下の「資料の場所」) | — |

- 画面のテストは Playwright(chromium)+ ffmpeg が必要。Playwright 同梱の chromium は H.264 を再生できない(動画の再生まで確かめるテストは webm で作る)
- ツールを一時フォルダに写して動かすテストが多い。新しいファイルを足したら、写すファイルの一覧(各 e2e の先頭)にも足す
- **サーバーを動かすテストは先頭で `os.environ.setdefault("YTT_DATA_DIR", "inplace")`**(忘れると移し済みの PC で本物の作業データを読み書きする。`ytt_core/test_ytt_core.py` が検査)

## 資料の場所(正本はこのリポジトリ)
- **資料の正本はこのリポジトリ**(2026-09-26 ユーザー決定)。claude.ai の Project の `claude/*.md` は古い写しで、根拠にしない(例外: 統合計画は Claude Docs が正本)
- 今の仕様 = 各ツールの `README.txt`(ユーザー向け)+ `AGENTS.md`(AI 向け)+ コード。ツール間の受け渡し: `docs/pipeline.md`
- `docs/project/` は 2026-09-24 までの経緯(仕様書・引き継ぎ)。**多くは数版前のまま**(例: cut2resolve-spec.md は v0.1.3、実物は v0.5.0)。
  「なぜそう決めたか」を調べるときに読む。一覧は `docs/project/README.md`
- `docs/review/README.md` … 2026-09-24 の全ツールの見直し。`docs/accuracy/` … 文字起こしの精度の基準(`accuracy-baseline.md`)とユーザーの記入待ちの項目(`USER_INPUT.md`)
- 新しい設計・決定は `docs/` の直下に文書で残し、WORKLOG からリンクする

## 開発のルール
- 実行時データ・個人データ・秘密情報はコミットしない(`.gitignore` 参照: transcripts/ dataset/ models/ exports/ clips/ config.json など)。リポジトリは Public にする方針なので特に注意。
  push.bat はコミットの前に `tools/push_helper.py check` で調べ、キーの形・個人データの名前・動画・5MB 超があれば止める(誤検出なら検査を直す)
- 各ツールで版を上げるときは、**serve.py の SERVER_VERSION・画面の APP_VERSION・README.txt の見出し**を必ず同時に上げる(食い違うと画面に赤い帯が出る)。
  APP_VERSION の場所: スタジオ `core.js`、文字起こし `app.js`、cut2resolve は `cut2resolve_core.py` の VERSION 1か所。入口は `app/launch.py`
- 各ツールの起動の約束(`serve.py [ポート] --no-open`・`.runtime/<ID>.json`・`/api/ping`・SIGTERM/SIGBREAK で後始末して終わる)は入口が使っている。
  変えるときは `app/launch.py` と `python -m unittest app/test_launch.py` も確認する(`docs/integration-plan.md` の「段階1の約束」)
- コミット: ユーザーの push.bat は `git add -A` でまとめてコミットし、メッセージは「更新 日付 時刻」になる。**何をなぜ変えたかは WORKLOG に書く**(履歴の説明は WORKLOG が担う)。
  git を使える AI が自分でコミットするときは、日本語で要約を書く(`"[Claude] 要約"` / `"[GPT] 要約"`)

## 複数の AI で作業するときのルール(Claude・GPT/Codex 共通)
このリポジトリは Claude(Cowork / Claude Code)と GPT(Codex)の両方が編集する。**正は PC の作業フォルダ(C:\Users\you11\Desktop\youtube-test)とその git**。
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

作業を終えるとき:
1. `docs/WORKLOG.md` の**末尾**に記録を追記する(書式は WORKLOG の先頭)。コミットしていないなら「未コミット: <ファイル一覧>」を必ず書く
2. git を使える AI は、変更したファイルと WORKLOG をコミットする(`git add <変えたファイル> docs/WORKLOG.md` → `git commit`)。push はユーザーが push.bat で行う(AI は push しなくてよい)
3. 長く使う設計・決定は `docs/` に文書で残し、WORKLOG からリンクする

Claude(Cowork。クラウドから PC のフォルダに読み書きする)の注意:
- PC で git・ファイルの移動・削除ができない。WORKLOG への追記までを行い、コミットは次に git を使う AI か push.bat に任せる。
  **ファイルを消すときは `tools/removals.txt` に1行ずつ書く**(ユーザーの push.bat が `git rm` する。git が管理しているファイルだけ。`tools/push_helper.py`)。移動は WORKLOG に手順を書いて頼む
- 同じファイルを何度も書き込むと、2回目以降が前の内容のまま書かれることがあった(2026-09-25)。**書き込んだら読み直して、手元の内容と一致することを確かめる**
- 起動中の入口・ツールは古いコードのまま動いている。コードを直したら、ユーザーに「すべて終了」→ start-all.bat で起動し直してもらう

## 統合作業の決まりとリスク(段階3 以降。作業する AI は必ず守る)
詳しい理由は `docs/integration-plan.md` の「主なリスクと対策」と「段階3-1〜3-3で決めたこと」。【高】は特に優先。

担当表(担当中は、他の AI はそのツール・ファイルを触らない。変わったら WORKLOG に書く):
- 統合作業(`app/`・`ytt_core/`・3ツールの取り込み)と `cut2resolve/` 全体(Text+ を含む): Claude が主担当(ユーザー決定 2026-09-25・26)
- 文字起こしツール(`transcribe-tool/`)と3ツール・入口の画面の全面見直し(`clip-studio/` の画面・`ui-kit/` を含む): Claude が担当(ユーザー決定 2026-09-26。見直しが終わるまで他の AI は触らない)
- 上に無いツールを触るときは、始める前に WORKLOG に「担当: 〇〇」と書く

取り込みの決まり:
- 画面は**相対パス**で部品を読み、API・動画の URL は1か所の関数で作る(絶対パス `/xxx` を書かない)。スタジオは `Studio.api`、文字起こし・cut2resolve は `app.js` の `apiUrl()` / `api()`
- 取り込んだ画面には CSP(`script-src 'self'`)がかかる: インラインの `<script>`・`onclick=` などは動かない。書き込み系の API は合言葉(`X-YTT-Token`)が要る(上の関数が付ける)
- ツール間で同じ名前の .py を作らない(`app/test_mount.py` が検査)
- 画面の共通の API `api/ytt/…`(エラーの記録・窓で開く)は入口が受け持つ(`app/mount.py` がツールに渡さない)。ツールに `/api/ytt/` で始まる API を作らない
- 画面を離れた・戻ったで処理するときは ui-kit の `UIKit.life.onLeave / onReturn` を使う(visibilitychange を直接使わない。窓を並べると隣の窓のクリックでタブの切り替えは来ない)。
  `'blur'`(隣の窓へ)のときは保存だけにして、再生の停止・重い処理はしない
- 画面の不具合を調べるときは、まず画面のエラーの記録 `%LOCALAPPDATA%\youtube-tools\app\logs\client-errors.jsonl`(入口の `/api/log?tool=client`)を見る
- 文字起こしのサーバー側のプロセスで numpy・faster_whisper・ctranslate2・sherpa_onnx を import しない(認識はワーカーの中だけ。`transcribe-tool/test_worker.py` が検査)

リスク:
- 【高】AI 間の同時編集の競合: 上の担当表と「複数の AI で作業するときのルール」を徹底する
- 【高】同一オリジン化による XSS の影響拡大: 1つのポートにまとめたので、1つの画面の XSS で全ツールの API(ファイルの書き込み・Resolve へのスクリプト登録)が使える。
  CSP `script-src 'self'` を維持する、書き込み系の POST に合言葉(CSRF トークン)、Host / Origin 検査は ytt_core の1か所で全 API にかける、パスは許可したフォルダの中だけ
- 文字起こしと切り抜きの紐づけの規則と、パックの有無の判定(`pack_info`)は `ytt_core/txindex.py` だけ(入口の案件・スタジオのセリフ・文字起こしの履歴が共通で使う)。他のツールのデータは読むだけで書き換えない
- Resolve パックは `cut2resolve/pack.py` だけが作る(2026-09-26 一本化。文字起こしの `resolve_export.create_package` は pack を呼んで zip にするだけ)。
  パックの作り方を変えたら `tools/test_resolve_pack_contract.py` を通す(文字起こしの zip と cut2resolve のパックが同じ中身・一本化の前と同じ区間と字幕)。
  経緯と旧との違いは `docs/resolve-pack-unification.md`。文字起こし側に Resolve 用の計算を書き足さない(二重実装に戻さない)
- 【高】古い写しを根拠にした判断: `claude/*.md` と `docs/project/` は古い。食い違いを見つけたら、今のコード・README・AGENTS.md を正とする(統合計画だけは Claude Docs が正本)
- CPU の取り合い(重い処理は `ytt_core/jobs.py` の `SLOTS` を通す。新しく重い処理を足すときも必ず通す。09-26)、データ移行(コピーのみ・元は残す・削除はユーザー確認後。`ytt_core/datadir.py`)、Public リポジトリへの個人データ混入(作業データはリポジトリの外。09-26 実装)

## ユーザーについて(応答の仕方)
- **応答は日本語**で。Web/バックエンド開発のエンジニア。動画編集は初心者。基礎的な文法・ライブラリの説明は不要、**実装判断の理由**が知りたい
- コードを示すときは、なぜその実装にしたかを1〜2文添える。複数案があれば、保守性・性能などのトレードオフを簡潔に比較する
- セキュリティ・エッジケースのリスクは省略せず指摘する
- 動画編集の専門用語は、初めて使うときに軽く説明する(一度説明した語は以後そのまま使ってよい)
- 長い作業で文脈が圧縮されそうなときは、HANDOVER(引き継ぎ)資料と「次のセッションにそのまま貼れる再開用の指示文」を作る
- **中間報告を徹底する**(2026-09-26 ユーザー指示): 作業のきりのいいところで、10〜20 分ごとを目安に、何が終わって次に何をするかを短く報告する

## 動作環境(ユーザーの PC)
- Windows。このリポジトリは PC 上の `Desktop\youtube-test` にある
- CPU は Intel Core i9-13900KF、メモリ 32GB。GPU は **AMD Radeon RX 7800 XT**(16GB)(NVIDIA ではないので CUDA は使えない → faster-whisper は CPU で動く。GPU 前提の提案をしない)
- Python 3・ffmpeg はインストール済み(文字起こしの install.bat・リポジトリ直下の start-all.bat を使う)。Python が複数入っている可能性がある(`__pycache__` に 3.10 と 3.12 の両方)。
  faster-whisper を入れた Python と `py -3` が同じかは未確認(`py -0p` で一覧が出る)
