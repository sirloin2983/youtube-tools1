# コードの地図: その他の画面(editor・studio・ui-kit・cut2resolve)

自動で作った物(`python dev/code_map.py`)。手で直さない。目次は [index.md](index.md)。`file:line` の行の番号は作った時点の物。

## src/cut2resolve/

- **serve.py** (589 行) — cut2resolve の API のサーバー(Python 標準ライブラリのみ。外部ツール: ffmpeg / ffprobe)。画面は「編集」(editor)にある。
  - 名前: `log` :111・`runtime_dir` :127・`class AppState` :139・`board_jobs` :166・`board_cancel` :171・`attach_board` :178・`is_pack_dir` :183・`open_folder` :188・`file_info` :205・`classify_warnings` :226・`with_warning_levels` :230・`class Handler` :238・ほか 11
  - 受ける口: `/api/ping` :334・`/api/siblings` :335・`/api/job` :336・`/api/plan` :351・`/api/build` :351・`/api/job/cancel` :351・`/api/open-folder` :351

## src/editor/

- **ed_media.py** (154 行) — 「編集」のサーバーの部品: 音の波形(カットのタイムライン)。
  - 名前: `peaks_rate` :31・`compute_peaks` :52・`get_peaks` :121
- **ed_state.py** (143 行) — 「編集」のサーバーの部品: 置き場所・設定の値・共通の小道具・記録(落ちたときの手がかり)・作業データの切り替え。
  - 名前: `atomic_write` :52・`runtime_path_dir` :76・`setup_logging` :81・`write_mark` :107・`check_previous_run` :116・`clear_mark` :127・`backend_name` :135
- **serve.py** (709 行) — 文字起こしツール用のローカルサーバー(標準ライブラリ + faster-whisper)。
  - 名前: `class Handler` :310・`probe` :500・`make_server` :506・`startup_checks` :529・`set_data_dir` :558・`studio_data_path` :569・`choose_data_dir` :577・`prepare` :589・`busy` :633・`finish` :638・`mounted_elsewhere` :652・`main` :661・ほか 1
  - 受ける口: `/api/ping` :191・`/api/siblings` :192・`/api/roster` :193・`/api/tools` :194・`/api/voices` :195・`/api/voices/preview` :196・`/api/jobs` :197・`/api/transcripts` :198・`/api/suggest` :199・`/api/metrics` :200・`/api/drill/status` :201・`/api/drill/candidates` :202・`/api/history` :203・`/api/transcript` :204・`/api/eval-folders` :205・`/api/eval-batch` :206・`/api/edit` :207・`/api/edit/draft` :208・`/api/edit/pack-readme` :209・`/api/doc-for` :210・`/api/mach-changes` :211・`/api/transcribe` :231・`/api/diarize` :232・`/api/voices/learn` :233・`/api/speakers/sub` :234・`/api/voices/delete` :235・`/api/rerun` :236・`/api/settings/patch` :237・`/api/restore` :238・`/api/suggest/feedback` :239・`/api/export-file` :240・`/api/relink/check` :241・`/api/relink` :242・`/api/eval-folders/organize` :243・`/api/eval-folders/settle` :244・`/api/eval-batch/start` :245・`/api/eval-batch/stop` :246・`/api/eval-batch/redo-one` :247・`/api/pick` :248・`/api/retime` :249・`/api/edit/pack` :250・`/api/edit/preview` :251・`/api/effort` :252・`/api/doc-diarnum` :253・`/api/mach-changes/pick` :254・`/api/drill/reviewed` :255・`/api/drill/unreviewed` :256・`/api/transcribe/cancel` :257・`/api/jobs/retry` :258・`/api/settings` :413・`/api/peaks` :415

## src/studio/

- **serve.py** (699 行) — 切り抜きスタジオ(ローカルサーバー・標準ライブラリのみ。外部ツール: ffmpeg、YouTube には yt-dlp)。
  - 名前: `init` :60・`attach_board` :72・`flow_host` :79・`busy` :87・`fetch_title` :91・`api_state` :98・`class Handler` :115・`probe` :448・`make_server` :463・`prepare` :573・`shutdown_jobs` :616・`finish` :638・ほか 2
  - 受ける口: `/api/ping` :183・`/api/siblings` :184・`/api/state` :185・`/api/settings` :186・`/api/rank/registry` :187・`/api/rank/search` :188・`/api/rank/live` :189・`/api/queue` :190・`/api/videos` :191・`/api/video` :192・`/api/transcripts` :193・`/api/title` :194・`/api/export` :195・`/api/collab/groups` :196・`/api/collab/group` :197・`/api/rank/resolve` :413・`/api/rank/import-official` :414・`/api/rank/search/cancel` :416・`/api/queue/add` :417・`/api/queue/cancel` :418・`/api/queue/skipchat` :419・`/api/queue/retry` :420・`/api/queue/clear` :421・`/api/videos/open` :422・`/api/live/adopt` :423・`/api/live/exported` :424・`/api/video/delete` :425・`/api/video/request-marks` :426・`/api/export/cancel` :428・`/api/collab/group/add` :430・`/api/collab/group/remove` :431・`/api/collab/group/delete` :432・`/api/collab/anchor` :433・`/api/config` :436・`/api/outdir` :437
- **startup.py** (111 行) — 切り抜きスタジオの起動の小物(役割で組み直す RS5-B)。
  - 名前: `migrate_old_logs` :37・`check_tools` :63・`start_env_check` :80・`env_state` :85

## src/ui-kit/

- **ui-kit.js** (2735 行) — ui-kit v37 —テーマ切り替えと、ツール間のリンク。<head> の中で CSS より先に同期読み込みする(画面のちらつき防止)。

## テスト

- tests/cut2resolve/test_serve.py — 画面のサーバー(serve.py)の API のテスト。実サーバーを空きポートで別スレッドに起動する。
- tests/editor/e2e_edit_common.py — 「編集」の部品(校正・カット・パック)を使う画面のテストの共通部分。
- tests/editor/test_backend.py — サーバー側のバグ直し・機能のテスト。
- tests/editor/test_edit.py — 「編集」ツールのサーバー側(資料の git:before-1028-cleanup:docs/design/edit-tool-design.md の 4・5・9)のテスト。
- tests/editor/test_settings_schema.py — 設定の画面のスキーマ(src/app/ui/settings/schema.json)の編集の分(store editor)が、ytt/settings の検査(SETTINGS_PATCH_KEYS・CUT_SILENCE_RANGE)と
- tests/studio/test_api.py — serve.py の HTTP 層のテスト(疑似モード・実サーバーを別スレッドで起動)。 実行: python3 test_api.py
- tests/studio/test_board_s2.py — RS8 の ② の口 S2: スタジオの解析(an)・書き出し(ex)・配信の検索(se)が掲示板(flow/board.py)に載る。  py -3.12 -m unittest tests/studio/test_board_s2.py
- tests/studio/test_file_recovery.py — 書き出しの途中の失敗(マークへの記録・名前を決める・使用中のファイル)。通しでは起こせないので ① を差し替えて起こす。実データやネットワークは使用しない。
- tests/studio/test_handoff.py — /api/siblings(他のツールの .runtime を読んで返す口)のテスト。
- tests/studio/test_rank_live.py — ① 探す の「配信中」のタブ: 配信中・これからの予定の取得(rank.live_list)と GET /api/rank/live のテスト。外へは繋がない。
- tests/studio/test_robustness.py — データを失わない・壊れたファイルで止まらない、のテスト(feedback.jsonl・registry.json・キャッシュ・ログ・ポートの確保)。
- tests/studio/test_settings_schema.py — 設定の画面のスキーマ(src/app/ui/settings/schema.json。S5)のスタジオの分(store studio の節 analyze)が、analyze.validate_settings の
