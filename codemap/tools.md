# コードの地図: その他の画面(editor・studio・ui-kit・cut2resolve)

自動で作った物(`python dev/code_map.py`)。手で直さない。目次は [index.md](index.md)。`file:line` の行の番号は作った時点の物。

## src/cut2resolve/

- **serve.py** (584 行) — cut2resolve の API のサーバー(Python 標準ライブラリのみ。外部ツール: ffmpeg / ffprobe)。画面は「編集」(editor)にある。
  - 名前: `log` :111・`runtime_dir` :127・`class AppState` :139・`board_jobs` :166・`board_cancel` :171・`attach_board` :178・`is_pack_dir` :183・`open_folder` :188・`file_info` :205・`classify_warnings` :226・`with_warning_levels` :230・`class Handler` :238・ほか 11
  - 受ける口: `/api/ping` :330・`/api/siblings` :331・`/api/job` :332・`/api/plan` :347・`/api/build` :347・`/api/job/cancel` :347・`/api/open-folder` :347

## src/editor/

- **ed_media.py** (154 行) — 「編集」のサーバーの部品: 音の波形(カットのタイムライン)。
  - 名前: `peaks_rate` :31・`compute_peaks` :52・`get_peaks` :121
- **ed_state.py** (183 行) — 「編集」のサーバーの部品: 置き場所・設定の値・共通の小道具・記録(落ちたときの手がかり)・作業データの切り替え。
  - 名前: `replace_retry` :63・`atomic_write` :69・`runtime_path_dir` :112・`setup_logging` :117・`write_mark` :143・`check_previous_run` :152・`clear_mark` :163・`backend_name` :175
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
- src/editor/tests/test_normalize30.py — 素材を 30fps にそろえるテスト: ② flow/normalize の段・動画を選び直す(④ の付け替え)。
- src/editor/tests/test_nosub_metrics.py — 「字幕に出さない」行(noSub)と、同時にしゃべっている所(重なり)の数え方・学習のテスト(数え方は eval/drill/metrics.py・noSub の外し方と学習は human/proof/learn.py)。
- src/editor/tests/test_proof_api.py — 校正まわりの API の確かめ(編集の画面の裏の API だけで確かめる)。
- src/editor/tests/test_qwen3.py — Qwen3-ASR のエンジン(tx_engines.LlamaQwen3 = llama.cpp の 1.7B)のテスト。test_metrics から読み込まれる。
- src/editor/tests/test_records.py — 記録の土台のテスト。
- src/editor/tests/test_resolve_export.py — resolve_export(Resolve パッケージ = cut2resolve の Text+ パックを zip にしたもの)の通し(本物の ffmpeg)と HTTP の口。
- src/editor/tests/test_retime.py — 行の時刻を単語の時刻に合わせる候補(T1 の簡易版)のテスト(計算は pipeline/transcribe/retime.py・文書を読む包みは human/proof/retime.py)。
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
