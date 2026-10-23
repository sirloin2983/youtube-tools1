# コードの地図: その他の画面(editor・studio・ui-kit・cut2resolve)

自動で作った物(`python dev/code_map.py`)。手で直さない。目次は [index.md](index.md)。`file:line` の行の番号は作った時点の物。

## src/cut2resolve/

- **serve.py** (584 行) — cut2resolve の API のサーバー(Python 標準ライブラリのみ。外部ツール: ffmpeg / ffprobe)。画面は「編集」(editor)にある。
  - 名前: `log` :111・`runtime_dir` :127・`class AppState` :139・`board_jobs` :166・`board_cancel` :171・`attach_board` :178・`is_pack_dir` :183・`open_folder` :188・`file_info` :205・`classify_warnings` :226・`with_warning_levels` :230・`class Handler` :238・ほか 11
  - 受ける口: `/api/ping` :330・`/api/siblings` :331・`/api/job` :332・`/api/plan` :347・`/api/build` :347・`/api/job/cancel` :347・`/api/open-folder` :347

## src/editor/

- **ed_media.py** (154 行) — 「編集」のサーバーの部品: 音の波形(カットのタイムライン)。
  - 名前: `peaks_rate` :31・`compute_peaks` :52・`get_peaks` :121
- **ed_state.py** (143 行) — 「編集」のサーバーの部品: 置き場所・設定の値・共通の小道具・記録(落ちたときの手がかり)・作業データの切り替え。
  - 名前: `atomic_write` :52・`runtime_path_dir` :76・`setup_logging` :81・`write_mark` :107・`check_previous_run` :116・`clear_mark` :127・`backend_name` :135
- **ed_thumb.py** (90 行) — 「編集」のサムネの案(提案 P5 の S。notes:plan/thumb-ideas.md の 7・8)。作る本体は thumb_ideas.py(コマンドとしても使える独立の部品)。
  - 名前: `thumb_paths` :25・`thumb_spec` :37・`run_thumb` :52・`thumb_info` :70・`thumb_image_path` :83
- **serve.py** (759 行) — 文字起こしツール用のローカルサーバー(標準ライブラリ + faster-whisper)。
  - 名前: `class Handler` :323・`probe` :551・`make_server` :557・`startup_checks` :579・`set_data_dir` :608・`studio_data_path` :619・`choose_data_dir` :627・`prepare` :639・`busy` :683・`finish` :688・`mounted_elsewhere` :702・`main` :711・ほか 1
  - 受ける口: `/api/ping` :197・`/api/siblings` :198・`/api/roster` :199・`/api/tools` :200・`/api/voices` :201・`/api/voices/preview` :202・`/api/jobs` :203・`/api/transcripts` :204・`/api/learned` :205・`/api/suggest` :206・`/api/metrics` :207・`/api/drill/status` :208・`/api/drill/candidates` :209・`/api/history` :210・`/api/transcript` :211・`/api/eval-folders` :212・`/api/eval-batch` :213・`/api/edit` :214・`/api/edit/draft` :215・`/api/thumb-ideas` :216・`/api/edit/pack-readme` :217・`/api/doc-for` :218・`/api/mach-changes` :219・`/api/transcribe` :243・`/api/diarize` :244・`/api/voices/learn` :245・`/api/speakers/sub` :246・`/api/voices/delete` :247・`/api/rerun` :248・`/api/settings/patch` :250・`/api/restore` :251・`/api/suggest/feedback` :252・`/api/export-file` :253・`/api/relink/check` :254・`/api/relink` :255・`/api/eval-folders/organize` :256・`/api/eval-folders/settle` :257・`/api/eval-batch/start` :258・`/api/eval-batch/stop` :259・`/api/eval-batch/redo-one` :260・`/api/pick` :261・`/api/retime` :262・`/api/edit/pack` :263・`/api/edit/preview` :264・`/api/effort` :265・`/api/doc-diarnum` :266・`/api/mach-changes/pick` :267・`/api/drill/reviewed` :268・`/api/drill/unreviewed` :269・`/api/transcribe/cancel` :270・`/api/jobs/retry` :271・`/api/settings` :429・`/api/peaks` :431・`/api/thumb-ideas/image` :435・`/api/resolve-package` :468
- **thumb_ideas.py** (246 行) — サムネの案を 6 つ並べた 1 枚を作る試作(提案 P5 の S = LLM なし。notes:plan/thumb-ideas.md)。完成品ではなく、サムネを作るときの参照。
  - 名前: `excite_score` :42・`clean` :50・`lines_of` :57・`one_word` :75・`row_at` :81・`select_times` :91・`card_texts` :111・`find_doc` :127・`doc_rows` :152・`member_color` :161・`mmss` :175・`crops_for` :179・ほか 2

## src/studio/

- **serve.py** (693 行) — 切り抜きスタジオ(ローカルサーバー・標準ライブラリのみ。外部ツール: ffmpeg、YouTube には yt-dlp)。
  - 名前: `init` :60・`attach_board` :72・`flow_host` :79・`busy` :87・`fetch_title` :91・`api_state` :98・`class Handler` :115・`probe` :443・`make_server` :457・`prepare` :567・`shutdown_jobs` :610・`finish` :632・ほか 2
  - 受ける口: `/api/ping` :183・`/api/siblings` :184・`/api/state` :185・`/api/settings` :186・`/api/rank/registry` :187・`/api/rank/search` :188・`/api/rank/live` :189・`/api/queue` :190・`/api/videos` :191・`/api/video` :192・`/api/transcripts` :193・`/api/title` :194・`/api/export` :195・`/api/collab/groups` :196・`/api/collab/group` :197・`/api/rank/resolve` :408・`/api/rank/import-official` :409・`/api/rank/search/cancel` :411・`/api/queue/add` :412・`/api/queue/cancel` :413・`/api/queue/skipchat` :414・`/api/queue/retry` :415・`/api/queue/clear` :416・`/api/videos/open` :417・`/api/live/adopt` :418・`/api/live/exported` :419・`/api/video/delete` :420・`/api/video/request-marks` :421・`/api/export/cancel` :423・`/api/collab/group/add` :425・`/api/collab/group/remove` :426・`/api/collab/group/delete` :427・`/api/collab/anchor` :428・`/api/config` :431・`/api/outdir` :432
- **startup.py** (111 行) — 切り抜きスタジオの起動の小物(役割で組み直す RS5-B)。
  - 名前: `migrate_old_logs` :37・`check_tools` :63・`start_env_check` :80・`env_state` :85

## src/ui-kit/

- **ui-kit.js** (2749 行) — ui-kit v37 —テーマ切り替えと、ツール間のリンク。<head> の中で CSS より先に同期読み込みする(画面のちらつき防止)。

## テスト

- tests/cut2resolve/test_serve.py — 画面のサーバー(serve.py)の API のテスト。実サーバーを空きポートで別スレッドに起動する。
- tests/editor/e2e_edit_common.py — 「編集」の部品(校正・カット・パック)を使う画面のテストの共通部分。
- tests/editor/test_backend.py — サーバー側のバグ直し・機能のテスト。
- tests/editor/test_edit.py — 「編集」ツールのサーバー側(notes:docs/design/edit-tool-design.md の 4・5・9)のテスト。
- tests/editor/test_settings_schema.py — 設定の画面のスキーマ(src/app/ui/settings/schema.json)の編集の分(store editor)が、ytt/settings の検査(SETTINGS_PATCH_KEYS・CUT_SILENCE_RANGE)と
- tests/editor/test_thumb_job.py — サムネの案(ジョブ ed_thumb.py → thumb_ideas.py → ① thumb_cards)のテスト。
- tests/studio/test_api.py — serve.py の HTTP 層のテスト(疑似モード・実サーバーを別スレッドで起動)。 実行: python3 test_api.py
- tests/studio/test_board_s2.py — RS8 の ② の口 S2: スタジオの解析(an)・書き出し(ex)・配信の検索(se)が掲示板(flow/board.py)に載る。  py -3.12 -m unittest tests/studio/test_board_s2.py
- tests/studio/test_file_recovery.py — 書き出しの途中の失敗(マークへの記録・名前を決める・使用中のファイル)。通しでは起こせないので ① を差し替えて起こす。実データやネットワークは使用しない。
- tests/studio/test_handoff.py — /api/siblings(他のツールの .runtime を読んで返す口)のテスト。
- tests/studio/test_rank_live.py — ① 探す の「配信中」のタブ: 配信中・これからの予定の取得(rank.live_list)と GET /api/rank/live のテスト。外へは繋がない。
- tests/studio/test_robustness.py — データを失わない・壊れたファイルで止まらない、のテスト(feedback.jsonl・registry.json・キャッシュ・ログ・ポートの確保)。
- tests/studio/test_settings_schema.py — 設定の画面のスキーマ(src/app/ui/settings/schema.json。S5)のスタジオの分(store studio の節 analyze)が、analyze.validate_settings の
