# コードの地図: その他の画面(editor・studio・ui-kit・cut2resolve)

自動で作った物(`python dev/code_map.py`)。手で直さない。目次は [index.md](index.md)。`file:line` の行の番号は作った時点の物。

## src/cut2resolve/

- **serve.py** (615 行) — cut2resolve の API のサーバー(Python 標準ライブラリのみ。外部ツール: ffmpeg / ffprobe)。画面は「編集」(editor)にある。
  - 名前: `log` :113・`runtime_dir` :130・`write_runtime` :134・`remove_runtime` :144・`siblings` :149・`class AppState` :163・`board_jobs` :190・`board_cancel` :195・`attach_board` :202・`is_pack_dir` :207・`open_folder` :212・`file_info` :229・ほか 14
  - 受ける口: `/api/ping` :363・`/api/siblings` :364・`/api/job` :365・`/api/plan` :380・`/api/build` :380・`/api/job/cancel` :380・`/api/open-folder` :380

## src/editor/

- **ed_media.py** (155 行) — 「編集」のサーバーの部品: 音の波形(カットのタイムライン)。
  - 名前: `peaks_rate` :32・`compute_peaks` :53・`get_peaks` :122
- **ed_state.py** (184 行) — 「編集」のサーバーの部品: 置き場所・設定の値・共通の小道具・記録(落ちたときの手がかり)・作業データの切り替え。
  - 名前: `replace_retry` :64・`atomic_write` :70・`runtime_path_dir` :113・`setup_logging` :118・`write_mark` :144・`check_previous_run` :153・`clear_mark` :164・`backend_name` :176
- **ed_thumb.py** (90 行) — 「編集」のサムネの案(提案 P5 の S。notes:plan/thumb-ideas.md の 7・8)。作る本体は thumb_ideas.py(コマンドとしても使える独立の部品)。
  - 名前: `thumb_paths` :25・`thumb_spec` :37・`run_thumb` :52・`thumb_info` :70・`thumb_image_path` :83
- **serve.py** (812 行) — 文字起こしツール用のローカルサーバー(標準ライブラリ + faster-whisper)。
  - 名前: `class Handler` :361・`probe` :606・`make_server` :612・`startup_checks` :634・`set_data_dir` :663・`studio_data_path` :674・`choose_data_dir` :682・`prepare` :694・`busy` :736・`finish` :741・`mounted_elsewhere` :755・`main` :764・ほか 1
  - 受ける口: `/api/ping` :235・`/api/siblings` :236・`/api/roster` :237・`/api/tools` :238・`/api/voices` :239・`/api/voices/preview` :240・`/api/jobs` :241・`/api/transcripts` :242・`/api/learned` :243・`/api/suggest` :244・`/api/metrics` :245・`/api/drill/status` :246・`/api/drill/candidates` :247・`/api/history` :248・`/api/transcript` :249・`/api/eval-folders` :250・`/api/eval-batch` :251・`/api/edit` :252・`/api/edit/draft` :253・`/api/thumb-ideas` :254・`/api/edit/pack-readme` :255・`/api/doc-for` :256・`/api/mach-changes` :257・`/api/transcribe` :281・`/api/diarize` :282・`/api/voices/learn` :283・`/api/speakers/sub` :284・`/api/voices/delete` :285・`/api/rerun` :286・`/api/settings/patch` :288・`/api/restore` :289・`/api/suggest/feedback` :290・`/api/export-file` :291・`/api/relink/check` :292・`/api/relink` :293・`/api/eval-folders/organize` :294・`/api/eval-folders/settle` :295・`/api/eval-batch/start` :296・`/api/eval-batch/stop` :297・`/api/eval-batch/redo-one` :298・`/api/pick` :299・`/api/retime` :300・`/api/edit/pack` :301・`/api/edit/preview` :302・`/api/effort` :303・`/api/doc-diarnum` :304・`/api/mach-changes/pick` :305・`/api/drill/reviewed` :306・`/api/drill/unreviewed` :307・`/api/transcribe/cancel` :308・`/api/jobs/retry` :309・`/api/settings` :484・`/api/peaks` :486・`/api/thumb-ideas/image` :490・`/api/resolve-package` :523
- **thumb_ideas.py** (246 行) — サムネの案を 6 つ並べた 1 枚を作る試作(提案 P5 の S = LLM なし。notes:plan/thumb-ideas.md)。完成品ではなく、サムネを作るときの参照。
  - 名前: `excite_score` :42・`clean` :50・`lines_of` :57・`one_word` :75・`row_at` :81・`select_times` :91・`card_texts` :111・`find_doc` :127・`doc_rows` :152・`member_color` :161・`mmss` :175・`crops_for` :179・ほか 2

## src/studio/

- **handoff.py** (40 行) — ツール間の受け渡し(notes:docs/spec/pipeline.md の 4)。
  - 名前: `runtime_dir` :16・`write_runtime` :21・`remove_runtime` :32・`siblings` :37
- **serve.py** (708 行) — 切り抜きスタジオ(ローカルサーバー・標準ライブラリのみ。外部ツール: ffmpeg、YouTube には yt-dlp)。
  - 名前: `init` :65・`attach_board` :77・`flow_host` :84・`busy` :92・`fetch_title` :96・`api_state` :108・`class Handler` :120・`probe` :460・`make_server` :474・`prepare` :584・`shutdown_jobs` :625・`finish` :647・ほか 2
  - 受ける口: `/api/ping` :200・`/api/siblings` :201・`/api/state` :202・`/api/settings` :203・`/api/rank/registry` :204・`/api/rank/search` :205・`/api/rank/live` :206・`/api/queue` :207・`/api/videos` :208・`/api/video` :209・`/api/transcripts` :210・`/api/title` :211・`/api/export` :212・`/api/collab/groups` :213・`/api/collab/group` :214・`/api/rank/resolve` :425・`/api/rank/import-official` :426・`/api/rank/search/cancel` :428・`/api/queue/add` :429・`/api/queue/cancel` :430・`/api/queue/skipchat` :431・`/api/queue/retry` :432・`/api/queue/clear` :433・`/api/videos/open` :434・`/api/live/adopt` :435・`/api/live/exported` :436・`/api/video/delete` :437・`/api/video/request-marks` :438・`/api/export/cancel` :440・`/api/collab/group/add` :442・`/api/collab/group/remove` :443・`/api/collab/group/delete` :444・`/api/collab/anchor` :445・`/api/config` :448・`/api/outdir` :449
- **startup.py** (111 行) — 切り抜きスタジオの起動の小物(役割で組み直す RS5-B)。
  - 名前: `migrate_old_logs` :37・`check_tools` :63・`start_env_check` :80・`env_state` :85

## src/ui-kit/

- **ui-kit.js** (2749 行) — ui-kit v37 —テーマ切り替えと、ツール間のリンク。<head> の中で CSS より先に同期読み込みする(画面のちらつき防止)。

## テスト

- src/cut2resolve/tests/test_serve.py — 画面のサーバー(serve.py)の API のテスト。実サーバーを空きポートで別スレッドに起動する。
- src/editor/tests/e2e_edit_common.py — 「編集」の部品(校正・カット・パック)を使う画面のテストの共通部分。
- src/editor/tests/fake_llama_server.py — テスト用の偽の llama-server(tx_engines.LlamaQwen3.COMMAND に [python, このファイル] を入れて使う)。
- src/editor/tests/fake_whisper_cli.py — テスト用の偽の whisper-cli(tx_engines.WhisperCpp.COMMAND に [python, このファイル] を入れて使う)。
- src/editor/tests/test_alt.py — 2つ目のエンジンとの食い違いに候補を出す機能のテスト。
- src/editor/tests/test_autodiar.py — 評価用の文書の文字起こしのあとの話者の自動判別(human/proof/speakers の autodiar_*・eval/drill/evalbatch の後追い)のテスト。
- src/editor/tests/test_backend.py — サーバー側のバグ直し・機能のテスト。
- src/editor/tests/test_drill.py — 評価ドリルと定点の「あと何分」(eval/drill/drill.py。動画 1 本ずつ・編集の画面で全部聞いて直す・文書の印 evalReviewed)のテスト。
- src/editor/tests/test_edit.py — 「編集」ツールのサーバー側(notes:docs/design/edit-tool-design.md の 4・5・9)のテスト。
- src/editor/tests/test_evalbatch.py — 評価用の動画の「手が空いたとき少しずつまとめて文字起こし」(eval/drill/evalbatch.py)のテスト。
- src/editor/tests/test_fill.py — 文字起こしのジョブの後処理(A 別の読み・B 頭の名前・E LLM・配信ごとの文脈)を ③ の run_job で 1 回通し、文書と記録に残る形を確かめるテスト。test_metrics から読み込まれる。
- src/editor/tests/test_llm.py — LLM の後処理 E(pipeline/transcribe/llm.py)の、通しで起こせない所のテスト。test_metrics から読み込まれる。
- src/editor/tests/test_metrics.py — 校正済み・CER測定・英字フラグ・A/B比較・校正済みの書き出し)のテスト。
- src/editor/tests/test_names.py — serve の名前の受付のテスト。
- src/editor/tests/test_normalize30.py — 素材を 30fps にそろえるテスト: ② flow/normalize の段・動画を選び直す(④ の付け替え)。
- src/editor/tests/test_nosub_metrics.py — 「字幕に出さない」行(noSub)と、同時にしゃべっている所(重なり)の数え方・学習のテスト(数え方は eval/drill/metrics.py・noSub の外し方と学習は human/proof/learn.py)。
- src/editor/tests/test_proof_api.py — 校正まわりの API の確かめ(編集の画面の裏の API だけで確かめる)。
- src/editor/tests/test_qwen3.py — Qwen3-ASR のエンジン(tx_engines.LlamaQwen3 = llama.cpp の 1.7B)のテスト。test_metrics から読み込まれる。
- src/editor/tests/test_records.py — 記録の土台のテスト。
- src/editor/tests/test_resolve_export.py — resolve_export(Resolve パッケージ = cut2resolve の Text+ パックを zip にしたもの)の通し(本物の ffmpeg)と HTTP の口。
- src/editor/tests/test_retime.py — 字幕の読む速さの印(T2)と、行の時刻を単語の時刻に合わせる候補(T1 の簡易版)のテスト(計算は pipeline/transcribe/retime.py・文書を読む包みは human/proof/retime.py)。
- src/editor/tests/test_roster.py — 名簿の呼び名(pipeline/transcribe/roster.py)と同梱の名簿のテスト。
- src/editor/tests/test_settings_schema.py — 設定の画面のスキーマ(src/app/ui/settings/schema.json)の編集の分(store editor)が、ytt/settings の検査(SETTINGS_PATCH_KEYS・CUT_SILENCE_RANGE)と
- src/editor/tests/test_smooth.py — 話者の細切れをならす(smooth_labels・smooth_speakers・apply_diarization(smooth)・設定 diarSmooth)のテスト。
- src/editor/tests/test_thumb_job.py — サムネの案(ジョブ ed_thumb.py → thumb_ideas.py → ① thumb_cards)のテスト。
- src/editor/tests/test_voices.py — 話者の声を覚える(A-3)のサーバー側のテスト。
- src/editor/tests/test_whispercpp.py — whisper.cpp のエンジン(tx_engines.WhisperCpp)のテスト。test_metrics から読み込まれる。
- src/editor/tests/test_worker.py — 認識ワーカー(src/pipeline/transcribe/worker.py。別プロセス)のテスト。  python -m unittest test_worker -v
- src/studio/tests/test_api.py — serve.py の HTTP 層のテスト(疑似モード・実サーバーを別スレッドで起動)。 実行: python3 test_api.py
- src/studio/tests/test_board_s2.py — RS8 の ② の口 S2: スタジオの解析(an)・書き出し(ex)・配信の検索(se)が掲示板(flow/board.py)に載る。  py -3.12 -m unittest src/studio/tests/test_board_s2.py
- src/studio/tests/test_file_recovery.py — 書き出しの途中の失敗(マークへの記録・名前を決める・使用中のファイル)。通しでは起こせないので ① を差し替えて起こす。実データやネットワークは使用しない。
- src/studio/tests/test_handoff.py — /api/siblings(他のツールの .runtime を読んで返す口)のテスト。
- src/studio/tests/test_rank_live.py — ① 探す の「配信中」のタブ: 配信中・これからの予定の取得(rank.live_list)と GET /api/rank/live のテスト。外へは繋がない。
- src/studio/tests/test_robustness.py — データを失わない・壊れたファイルで止まらない、のテスト(feedback.jsonl・registry.json・キャッシュ・ログ・ポートの確保)。
- src/studio/tests/test_settings_schema.py — 設定の画面のスキーマ(src/app/ui/settings/schema.json。S5)のスタジオの分(store studio の節 analyze)が、analyze.validate_settings の
