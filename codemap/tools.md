# コードの地図: その他の画面(editor・studio・ui-kit・cut2resolve)

自動で作った物(`python dev/code_map.py`)。手で直さない。目次は [index.md](index.md)。`file:line` の行の番号は作った時点の物。

## src/cut2resolve/

- **serve.py** (615 行) — cut2resolve の API のサーバー(Python 標準ライブラリのみ。外部ツール: ffmpeg / ffprobe)。画面は「編集」(editor)に統合した(2026-09-26)。
  - 名前: `log` :113・`runtime_dir` :130・`write_runtime` :134・`remove_runtime` :144・`siblings` :149・`class AppState` :163・`board_jobs` :190・`board_cancel` :195・`attach_board` :202・`is_pack_dir` :207・`open_folder` :212・`file_info` :229・ほか 14
  - 受ける口: `/api/ping` :363・`/api/siblings` :364・`/api/job` :365・`/api/plan` :380・`/api/build` :380・`/api/job/cancel` :380・`/api/open-folder` :380

## src/editor/

- **ed_media.py** (156 行) — 「編集」のサーバーの部品: 音の波形(カットのタイムライン)(段10 で editor/serve.py から分けた。git の履歴(679ff01 以前)の docs/plan/phase10-code-split.md)。
  - 名前: `peaks_rate` :33・`compute_peaks` :54・`get_peaks` :123
- **ed_state.py** (186 行) — 「編集」のサーバーの部品: 置き場所・設定の値・共通の小道具・記録(落ちたときの手がかり)・作業データの切り替え(段10 で editor/serve.py から分けた。git の履歴(679ff01 以前)の docs/plan/phase10-code-split.md)。
  - 名前: `replace_retry` :64・`atomic_write` :70・`runtime_path_dir` :115・`setup_logging` :120・`write_mark` :146・`check_previous_run` :155・`clear_mark` :166・`backend_name` :178
- **ed_thumb.py** (90 行) — 「編集」のサムネの案(提案 P5 の S。notes:plan/thumb-ideas.md の 7・8)。作る本体は thumb_ideas.py(コマンドとしても使える独立の部品)。
  - 名前: `thumb_paths` :25・`thumb_spec` :37・`run_thumb` :52・`thumb_info` :70・`thumb_image_path` :83
- **serve.py** (820 行) — 文字起こしツール用のローカルサーバー(標準ライブラリ + faster-whisper)。
  - 名前: `class Handler` :369・`probe` :614・`make_server` :620・`startup_checks` :642・`set_data_dir` :671・`studio_data_path` :682・`choose_data_dir` :690・`prepare` :702・`busy` :744・`finish` :749・`mounted_elsewhere` :763・`main` :772・ほか 1
  - 受ける口: `/api/ping` :238・`/api/siblings` :239・`/api/clip-info` :240・`/api/roster` :241・`/api/tools` :242・`/api/voices` :243・`/api/voices/preview` :244・`/api/jobs` :245・`/api/transcripts` :246・`/api/learned` :247・`/api/suggest` :248・`/api/metrics` :249・`/api/drill/status` :250・`/api/drill/next` :251・`/api/drill/candidates` :252・`/api/history` :253・`/api/transcript` :254・`/api/eval-folders` :255・`/api/eval-batch` :256・`/api/edit` :257・`/api/edit/draft` :258・`/api/thumb-ideas` :259・`/api/edit/pack-readme` :260・`/api/doc-for` :261・`/api/mach-changes` :262・`/api/transcribe` :286・`/api/diarize` :287・`/api/voices/learn` :288・`/api/speakers/sub` :289・`/api/voices/delete` :290・`/api/rerun` :291・`/api/settings/patch` :293・`/api/restore` :294・`/api/suggest/feedback` :295・`/api/export-file` :296・`/api/relink/check` :297・`/api/relink` :298・`/api/relink/missing` :299・`/api/relink/find` :300・`/api/eval-folders/organize` :301・`/api/eval-folders/settle` :302・`/api/eval-batch/start` :303・`/api/eval-batch/stop` :304・`/api/eval-batch/redo` :305・`/api/eval-batch/redo-one` :306・`/api/pick` :307・`/api/retime` :308・`/api/edit/pack` :309・`/api/edit/preview` :310・`/api/effort` :311・`/api/doc-diarnum` :312・`/api/mach-changes/pick` :313・`/api/drill/reviewed` :314・`/api/drill/unreviewed` :315・`/api/transcribe/cancel` :316・`/api/jobs/retry` :317・`/api/settings` :492・`/api/peaks` :494・`/api/thumb-ideas/image` :498・`/api/resolve-package` :531
- **thumb_ideas.py** (246 行) — サムネの案を 6 つ並べた 1 枚を作る試作(提案 P5 の S = LLM なし。notes:plan/thumb-ideas.md)。完成品ではなく、サムネを作るときの参照。
  - 名前: `excite_score` :41・`clean` :49・`lines_of` :56・`one_word` :74・`row_at` :80・`select_times` :90・`card_texts` :110・`find_doc` :126・`doc_rows` :151・`member_color` :160・`mmss` :174・`crops_for` :178・ほか 2

## src/studio/

- **handoff.py** (40 行) — ツール間の受け渡し(notes:docs/spec/pipeline.md の 4)。
  - 名前: `runtime_dir` :16・`write_runtime` :21・`remove_runtime` :32・`siblings` :37
- **serve.py** (708 行) — 切り抜きスタジオ(ローカルサーバー・標準ライブラリのみ。外部ツール: ffmpeg、YouTube には yt-dlp)。
  - 名前: `init` :65・`attach_board` :77・`flow_host` :84・`busy` :92・`fetch_title` :96・`api_state` :108・`class Handler` :120・`probe` :460・`make_server` :474・`prepare` :584・`shutdown_jobs` :625・`finish` :647・ほか 2
  - 受ける口: `/api/ping` :200・`/api/siblings` :201・`/api/state` :202・`/api/settings` :203・`/api/rank/registry` :204・`/api/rank/search` :205・`/api/rank/live` :206・`/api/queue` :207・`/api/videos` :208・`/api/video` :209・`/api/transcripts` :210・`/api/title` :211・`/api/export` :212・`/api/collab/groups` :213・`/api/collab/group` :214・`/api/rank/resolve` :425・`/api/rank/import-official` :426・`/api/rank/search/cancel` :428・`/api/queue/add` :429・`/api/queue/cancel` :430・`/api/queue/skipchat` :431・`/api/queue/retry` :432・`/api/queue/clear` :433・`/api/videos/open` :434・`/api/live/adopt` :435・`/api/live/exported` :436・`/api/video/delete` :437・`/api/video/request-marks` :438・`/api/export/cancel` :440・`/api/collab/group/add` :442・`/api/collab/group/remove` :443・`/api/collab/group/delete` :444・`/api/collab/anchor` :445・`/api/config` :448・`/api/outdir` :449
- **startup.py** (111 行) — 切り抜きスタジオの起動の小物(役割で組み直す RS5-B。2026-10-10。旧 common.py の殻を消して、残った起動の物だけここへ)。
  - 名前: `migrate_old_logs` :37・`check_tools` :63・`start_env_check` :80・`env_state` :85

## src/ui-kit/

- **styleguide.js** (130 行) — ui-kit/styleguide.html の見本を動かす部品(CSP の script-src 'self' に合わせてインラインの <script> を使わず、この外部ファイルにした)。
- **ui-kit.js** (2781 行) — ui-kit v33 —テーマ切り替えと、ツール間のリンク。<head> の中で CSS より先に同期読み込みする(画面のちらつき防止)。

## テスト

- src/cut2resolve/tests/test_serve.py — 画面のサーバー(serve.py)の API のテスト。実サーバーを空きポートで別スレッドに起動する。
- src/editor/tests/e2e_edit_common.py — 「編集」の部品(校正・カット・パック)を使う画面のテストの共通部分。RS8 C4 で古い編集の画面と旧 e2e(e2e_edit_*.py など 15 本)は消え、
- src/editor/tests/fake_llama_server.py — テスト用の偽の llama-server(tx_engines.LlamaQwen3.COMMAND に [python, このファイル] を入れて使う)。
- src/editor/tests/fake_whisper_cli.py — テスト用の偽の whisper-cli(tx_engines.WhisperCpp.COMMAND に [python, このファイル] を入れて使う)。
- src/editor/tests/test_alt.py — 2つ目のエンジンとの食い違いに候補を出す(精度改善の計画 第2版 D1-b。editor/ed_alt.py)のテスト。
- src/editor/tests/test_autodiar.py — 評価用の文書の文字起こしのあとの話者の自動判別(human/proof/speakers の autodiar_*・eval/drill/evalbatch の後追い)のテスト。
- src/editor/tests/test_backend.py — サーバー側の見直し(2026-09-24)で直したバグ・足した機能のテスト。
- src/editor/tests/test_drill.py — 評価ドリルと定点の「あと何分」(マスタープラン Q4。git の履歴(679ff01 以前)の docs/plan/q3-q4-design.md の (c)。eval/drill/drill.py。RS4-2 まで editor/ed_drill.py)のテスト。
- src/editor/tests/test_edit.py — 「編集」ツールのサーバー側(notes:docs/design/edit-tool-design.md の 4・5・9)のテスト。
- src/editor/tests/test_evalbatch.py — 評価用の動画の「手が空いたとき少しずつまとめて文字起こし」(eval/drill/evalbatch.py。RS4-2 まで editor/ed_evalbatch.py。マスタープラン Q4(b))のテスト。
- src/editor/tests/test_fill.py — 認識のあとの後処理 A・B・C・D(pipeline/transcribe/fill.py。旧 src/editor/ed_fill.py。10-08 の実験ループ。編集 0.60.0。B = 行の頭の話者名は 0.67.0)のテスト。test_metrics から読み込まれる。
- src/editor/tests/test_llm.py — LLM の後処理 E(pipeline/transcribe/llm.py。旧 src/editor/ed_llm.py。提案 P18。編集 0.61.0)のテスト。test_metrics から読み込まれる。
- src/editor/tests/test_metrics.py — v0.7.0 の追加分(校正済み・CER測定・英字フラグ・A/B比較・校正済みの書き出し)のテスト。
- src/editor/tests/test_names.py — serve の名前の受付(役割で組み直す RS2。2026-10-10)のテスト。旧い名前の転送だけの殻 ed_*(ed_jobs ほか 9 本)は RS5-A で消した。
- src/editor/tests/test_normalize30.py — 素材を 30fps にそろえる(マスタープラン Q1)のテスト: ② flow/normalize の段・動画を選び直す(④ の付け替え)。
- src/editor/tests/test_nosub_metrics.py — 「字幕に出さない」行(noSub)と、同時にしゃべっている所(重なり)の数え方・学習のテスト(数え方は eval/drill/metrics.py・noSub の外し方と学習は human/proof/learn.py。RS3-E5c まで editor/ed_learn.py。保管は 0.68.…
- src/editor/tests/test_proof_api.py — 校正まわりの API の確かめ(旧 e2e = RS8 C4 で消した編集の画面の e2e が、画面の裏で API だけで確かめていた物を unittest に移した)。
- src/editor/tests/test_qwen3.py — Qwen3-ASR のエンジン(tx_engines.LlamaQwen3 = llama.cpp の 1.7B。sherpa-onnx の 0.6B Qwen3Asr は 0.58.0 で消した。精度改善の計画 段2-3)のテスト。test_metrics から読み込まれる。
- src/editor/tests/test_records.py — 記録の土台(マスタープラン Q2。notes:plan/line-bc-master-plan.md)のテスト。
- src/editor/tests/test_resolve_export.py — resolve_export(Resolve パッケージ = cut2resolve の Text+ パックを zip にしたもの)と「残す行」の規則のテスト。
- src/editor/tests/test_retime.py — 字幕の読む速さの印(T2)と、行の時刻を単語の時刻に合わせる候補(T1 の簡易版)のテスト(計算は pipeline/transcribe/retime.py・文書を読む包みは editor/ed_retime.py。RS2-9)。
- src/editor/tests/test_roster.py — 名簿の呼び名と配信ごとの文脈(文字起こしの改善の計画 段1-1・1-2。roster.py・serve.py の stream_context)のテスト。
- src/editor/tests/test_settings_schema.py — 設定の画面のスキーマ(src/app/ui/settings/schema.json。S5)の編集の分(store editor)が、ytt/settings の検査(SETTINGS_PATCH_KEYS・CUT_SILENCE_RANGE。RS3-1 まで ed_learn)と
- src/editor/tests/test_smooth.py — 話者の細切れをならす(S2。ed_speakers の smooth_labels・smooth_speakers・apply_diarization(smooth)・設定 diarSmooth)のテスト。2026-10-05。
- src/editor/tests/test_thumb_ideas.py — src/editor/thumb_ideas.py(サムネの案。提案 P5 の S。10-09 に dev/ から移した)のテスト。リポジトリ直下で:
- src/editor/tests/test_thumb_job.py — サムネの案のジョブ(提案 P5。editor/ed_thumb.py → thumb_ideas.py)のテスト。
- src/editor/tests/test_voices.py — 話者の声を覚える(A-3。git の履歴(679ff01 以前)の docs/archive/backlog-ui-2026-09-27.md)のサーバー側のテスト。
- src/editor/tests/test_whispercpp.py — whisper.cpp のエンジン(tx_engines.WhisperCpp。精度改善の計画 段2-2)のテスト。test_metrics から読み込まれる。
- src/editor/tests/test_worker.py — 認識ワーカー(src/pipeline/transcribe/worker.py。別プロセス。統合計画の段階3-3。RS2-9 に編集の tx_worker.py から移した)のテスト。  python -m unittest test_worker -v
- src/studio/tests/e2e_analyze.py — analyze.run の通し試験(疑似モード: 合成音声 + 合成チャット)。 実行: python3 e2e_analyze.py
- src/studio/tests/test_api.py — serve.py の HTTP 層のテスト(疑似モード・実サーバーを別スレッドで起動)。 実行: python3 test_api.py
- src/studio/tests/test_board_s2.py — RS8 の ② の口 S2: スタジオの解析(an)・書き出し(ex)・配信の検索(se)が掲示板(flow/board.py)に載る。  py -3.12 -m unittest src/studio/tests/test_board_s2.py
- src/studio/tests/test_file_recovery.py — 保存・書き出しの障害回復。実データやネットワークは使用しない。
- src/studio/tests/test_handoff.py — 受け渡し(notes:docs/spec/pipeline.md の 2.1・4・6)のテスト: .clip.json・.runtime/studio.json・/api/siblings。
- src/studio/tests/test_rank_live.py — ① 探す の「配信中」のタブ: 配信中・これからの予定の取得(rank.live_list)と GET /api/rank/live のテスト。外へは繋がない。
- src/studio/tests/test_robustness.py — データを失わない・壊れたファイルで止まらない、のテスト(feedback.jsonl・registry.json・キャッシュ・ログ・ポートの確保)。
- src/studio/tests/test_settings_schema.py — 設定の画面のスキーマ(src/app/ui/settings/schema.json。S5)のスタジオの分(store studio の節 analyze)が、analyze.validate_settings の
- src/ui-kit/tests/e2e_styleguide.py — ui-kit v6(画面の全面見直し notes:docs/design/briefs/ui-overhaul/ の段階1)の見本(styleguide.html)の動作確認(Playwright・chromium・headless)。
