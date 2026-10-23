# コードの地図: ① pipeline(道具 = データを加工する)

自動で作った物(`python dev/code_map.py`)。手で直さない。目次は [index.md](index.md)。`file:line` の行の番号は作った時点の物。

## src/pipeline/

- **__init__.py** (2 行) — ① 道具(解析 analyze・書き出し export・文字起こし transcribe・パック pack・録画の取り込み ingest。1 つ 1 つが「入力 → 出力」の変換)。画面・案件・順番を知らない。ytt だけを import する。いつ・どの順で・どこに置いて・飛ばすかは ② の s…

## src/pipeline/analyze/

- **__init__.py** (2 行) — ① 解析: 材料の取得(fetch。動画・チャット・コメント)・音量(levels)・盛り上がりの式(excite)・候補・話の切れ目(breaks)・自動採用・配信中の検出
- **adopt.py** (73 行) — 採用の規則 F-5(notes:plan/done/role-restructure.md 5-5・決定 3-29 Q3。純粋な関数)。
  - 名前: `check_args` :18・`adopt` :35
- **analyze.py** (409 行) — 解析(自動切り抜き ac/serve.py 由来。書き出し・手動の○×は持たない)。
  - 名前: `sig_cache_dir` :35・`validate_live` :42・`validate_source` :48・`validate_settings` :63・`make_spec` :78・`chat_public` :87・`sig_path` :94・`load_sig` :98・`save_sig` :115・`archive_path` :128・`load_archive` :132・`save_archive` :142・ほか 3
- **breaks.py** (119 行) — 話の切れ目(breaks)。切り抜きの区間の両端を、文字起こしの話の切れ目へ寄せて言葉の途中で切らないための関数(線 LD-2c。notes:plan/done/ld2-clip-length.md)。
  - 名前: `cuts` :61・`snap` :106
- **excite.py** (1016 行) — 盛り上がり(excitement)の式。スタジオのアーカイブの解析(src/pipeline/analyze/analyze.py)と、配信中の検出(src/pipeline/analyze/live_excite_worker.py。線 D の L2)が同じ式を読む(線 D の L1。notes…
  - 名前: `smooth` :85・`median` :96・`local_baseline` :102・`robust_scale` :121・`audio_score` :127・`chat_z` :139・`shift_chat` :148・`estimate_lag` :154・`ramp` :178・`head_ramp` :183・`comment_score` :190・`peak_total` :205・ほか 14
- **fetch.py** (554 行) — 解析の材料を取ってくる仕事(音声のダウンロード・チャットのリプレイの取得と先読み・コメント欄・動画の付加情報)と、そのキャッシュの置き場と掃除。
  - 名前: `work_dir` :32・`chat_cache_dir` :36・`download_audio` :51・`chat_cache_path` :83・`drop_chat_cache` :87・`chat_cache_limit` :104・`use_chat_cache` :119・`prune_chat_cache` :129・`download_chat` :177・`prefetch_chat` :259・`cancel_prefetch` :302・`cancel_all_prefetch` :309・ほか 9
- **levels.py** (64 行) — 1 秒ごとの音量(RMS, dB)を、ffmpeg 1 回のデコードで全帯域と高音域(2kHz 超)の 2 系列に測る決まり(OPT1)。
  - 名前: `args` :23・`clear` :30・`level` :36・`read` :47・`collect` :56
- **live_excite_worker.py** (1658 行) — 配信中の盛り上がりの検出のワーカー(線 D の L2。notes:plan/line-d-detect.md・notes:plan/line-d-live-clipping.md の 0-10)。入口(src/flow/live_detect.py)が起動する子プロセス。
  - 名前: `chat_trouble` :139・`class MeasureError` :157・`class NoTool` :161・`class RecorderDown` :165・`clean_requests` :173・`request_spec` :188・`clean_spec_doc` :209・`clean_bundles` :223・`clean_detect` :234・`measure_levels` :241・`parse_chat_line` :261・`clean_hint` :280・ほか 10

## src/pipeline/export/

- **__init__.py** (2 行) — ① 書き出し: 区間 → 動画(exporter)・サムネの案の絵(thumb_cards)
- **exporter.py** (1097 行) — ③ 書き出し(クリップマーカー cm/serve.py 由来): store の動画・マークから ffmpeg / yt-dlp でクリップを mp4 にする。
  - 名前: `class ExportError` :53・`log_export` :57・`reason` :73・`verify_output` :80・`pick_folder` :89・`promote` :98・`drop_partial` :115・`clean_partials` :121・`check_section_path` :217・`build_section_spec` :238・`spec_from_video` :264・`new_result` :316・ほか 14
- **outcheck.py** (110 行) — ① 書き出しのあとの自動の点検(10-23。notes:plan/人の作業なしの候補-1023.md の 1)。書き出した切り抜き 1 本を測り、気になる所を返すだけ(出力は止めない・消さない)。
  - 名前: `black_spans` :37・`edge_ratio` :42・`judge` :55・`check` :77
- **thumb_cards.py** (174 行) — サムネの案の描く部分(提案 P5 の S。notes:plan/thumb-ideas.md の 7・8)。ffmpeg で動画から 1 枚ずつ切り取って文字を載せ、6 案を 1 枚の PNG にまとめる。
  - 名前: `class ThumbError` :21・`ffmpeg_path` :28・`probe` :35・`loud_times` :44・`scene_times` :59・`font_path` :68・`fpath` :75・`text_filter` :80・`card_filters` :89・`crop_box` :119・`render_card` :137・`tile` :152・ほか 1

## src/pipeline/ingest/

- **__init__.py** (2 行) — ① 取り込み: 配信中の録画(recorder・rec_core)と、録画とアーカイブの音の照合(live_align_worker)。YouTube からの取得は export/exporter と analyze/fetch
- **live_align_worker.py** (133 行) — 音の照合(線 D の P4。notes:plan/line-d-live-clipping.md の 0-9)の子プロセス。**入口のプロセスから import しない
  - 名前: `fail` :34・`read_wav` :39・`next_pow2` :54・`xcorr_valid` :59・`align` :79・`main` :103
- **rec_core.py** (1016 行) — 録画の中身(線 D の P1。notes:plan/line-d-live-clipping.md の 0・2〜4)。HTTP は recorder.py。
  - 名前: `class RecError` :93・`to_utc` :104・`pick_segments` :115・`validate_url` :135・`fetch_title` :157・`folder_state` :176・`parse_playlist` :200・`keep_order` :223・`build_playlist` :244・`read_text` :266・`clean_tmp` :295・`new_rec_id` :310・ほか 2
- **recorder.py** (383 行) — 録画の部品(線 D: リアルタイム切り抜きの P1。notes:plan/line-d-live-clipping.md の 0)。入口とは別のプロセスで動く。
  - 名前: `data_dir` :58・`load_token` :65・`read_settings` :80・`save_folder` :84・`clean_folder` :91・`make_logger` :105・`raise_priority` :129・`class Handler` :141・`class Server` :285・`parse_args` :296・`main` :324
  - 受ける口: `/api/ping` :181

## src/pipeline/pack/

- **__init__.py** (2 行) — ① パック: DaVinci Resolve に読ませるパック(pack・cut2resolve_core・srt2resolve)・Text+(resolve_textplus)・zip の受け渡し(resolve_export)・指定の読み(request)・自動のカット(auto_cut)・…
- **auto_cut.py** (141 行) — カットの計画の部品(read_cut_plan・build_plan・plan_from_keeps・finalize_plan。pack.py が使う)。
  - 名前: `read_cut_plan` :16・`default_handles` :71・`build_plan` :77・`removed_between` :98・`plan_from_keeps` :109・`finalize_plan` :117
- **cut2resolve_core.py** (875 行) — cut2resolve 共通部
  - 名前: `class Cancelled` :47・`class OutputExists` :54・`class Task` :63・`parse_time` :78・`parse_cut_list` :116・`sec_to_frames` :147・`cue_frames` :151・`frames_to_sec` :157・`fps_label` :162・`cut_list_to_keeps` :167・`normalize` :182・`subtract` :200・ほか 35
- **edge_pause.py** (104 行) — 切り抜きの両端を「話の間」へ寄せる(10-23。決定 3-153。notes:plan/heatmap-study.md の「切り抜きの端を話の間へ」)。
  - 名前: `levels` :26・`voice_level` :46・`pauses` :52・`snap_end` :66・`snap_start` :76・`snap` :86
- **pack.py** (964 行) — カットの計算(試算)とパックの作成。画面(serve.py)と ② の自動の流れが呼ぶ共通部(処理を二重に持たない)。
  - 名前: `class RowEdge` :42・`class Request` :77・`class Plan` :114・`class Cache` :138・`default_out_dir` :202・`row_edge_from` :206・`widen_row_edges` :230・`row_edge_pending` :273・`silence_pending` :282・`detect_pending` :290・`without_detect` :299・`plan_cut` :318・ほか 16
- **preview.py** (124 行) — ① 確認用の動画(友人が受け取るかを決める前に見る、1 本の切り抜きの 480p の動画)とパックの中の切り抜きの動画の引き方(ds1 = 要件 1-5。② flow/deliver から分けた)。
  - 名前: `pack_title` :24・`scratch_path` :30・`remove_quiet` :35・`pack_video` :41・`make_preview` :80・`clip_preview` :105・`pack_seconds` :118
- **request.py** (336 行) — パックの指定(JSON の spec・output)-> pack.Request と build_pack の引数。指定の読み方の 1 か所
  - 名前: `clean_path` :33・`input_path` :58・`request_from_spec` :103・`clip_range_from_spec` :174・`row_edge_from_spec` :184・`advanced_from_spec` :193・`keeps_from_spec` :204・`speaker_color_map` :225・`speaker_styles_from` :244・`apply_speaker_styles` :267・`output_from_spec` :288・`speaker_colors_for` :327
- **resolve_export.py** (375 行) — DaVinci Resolve への受け渡し(文字起こしツールの「Resolveパッケージ(zip)をダウンロード」)と、「残す行」の規則。
  - 名前: `srt_time` :37・`srt_text` :43・`is_kept` :49・`kept_spans` :55・`tool_info` :82・`sorted_segments` :86・`build_transcript_v1` :105・`build_cut_plan_v1` :133・`wrap_text` :146・`build_srt` :153・`pack_instructions` :173・`edit_draft` :233・ほか 3
- **resolve_textplus.py** (1031 行) — Resolve Free向け Text+ 試験パック。Luaスクリプトを同梱する。
  - 名前: `hex_rgba` :70・`text_style` :81・`style_inputs` :97・`video_tracks_value` :119・`parse_target` :126・`caption_segments` :149・`stack_captions` :180・`default_wrap` :252・`wrap_caption` :257・`build_import_plan` :295・`importer_script` :363・`installer_script` :792・ほか 6
- **srt2resolve.py** (353 行) — パックの部品(動画の情報の読み取り・字幕の読み込み・フレームの計算・SRT の組み立ての小道具)。
  - 名前: `class ToolError` :27・`same_path` :31・`staged` :44・`write_text_atomic` :56・`tool` :65・`arg_path` :70・`clean_text` :94・`parse_subs` :101・`read_sub_file` :125・`snap_fps` :149・`codec_warnings` :161・`probe` :198・ほか 9

## src/pipeline/transcribe/

- **__init__.py** (2 行) — ① 文字起こし: 認識(エンジン・ワーカー)・話者・後処理(埋める・LLM・時刻)・名簿と辞書を読む。認識(重い)と後処理(軽い)で鍵を分ける
- **backend.py** (119 行) — サーバー側の認識の本物と疑似の差し込み口。
  - 名前: `mode` :18・`is_fake` :23・`class Backend` :28・`set_selector` :111・`select` :116
- **clipjob.py** (71 行) — ① 文字起こしのジョブの機械の文書の行を作る(make_doc_rows)。
  - 名前: `make_doc_rows` :17
- **diarize.py** (550 行) — ① 自動の流れの層 pipeline/transcribe: 話者判別の計算(sherpa-onnx)と判別の記録・声の特徴と覚えた声との照らし合わせ。
  - 名前: `diar_threads` :59・`has_sherpa` :65・`diar_models_dir` :71・`diar_info` :84・`ensure_diar_models` :114・`diar_tune` :145・`diarize_real` :161・`assign_speakers` :203・`label_ratio` :254・`smooth_labels` :262・`smooth_speakers` :284・`diar_path` :304・ほか 8
- **fill.py** (439 行) — 「編集」のサーバーの部品: 認識のあとの後処理(A・C・D。notes:plan/line-b-transcription.md の「10-08 の実験ループ」)。
  - 名前: `fill_norm` :67・`fill_chars` :72・`fill_sparse_row` :77・`fill_apply` :96・`fill_clean_tail` :126・`fill_stock` :139・`fill_voice_frac` :145・`fill_clean_turns` :153・`fill_spk_key` :178・`fill_spk_names` :183・`fill_spk_split` :199・`fill_strip_names` :228・ほか 9
- **live_tx_worker.py** (71 行) — 配信中の候補の文字起こし(線 D の D-11 案 b。notes:plan/line-d-live-clipping.md の 0-11)の子プロセス。**入口のプロセスから import しない
  - 名前: `recognize` :28・`main` :53
- **llm.py** (372 行) — 「編集」のサーバーの部品: LLM の後処理(提案 P18。notes:plan/done/llm-postfix.md)。
  - 名前: `llm_fold` :57・`llm_dist` :68・`llm_members` :79・`llm_targets` :92・`llm_near` :105・`llm_gloss` :130・`llm_pick` :142・`llm_messages` :166・`llm_parse` :178・`llm_names` :196・`llm_guard` :206・`llm_cap` :227・ほか 8
- **models.py** (163 行) — ① 認識ワーカーの中で動く物: 読み込んだモデルの使い回し(_models)と読み込み(_load_model_local)・しばらく使わなければ手放す(release_idle_local)・
  - 名前: `models_touched` :31・`release_idle_local` :36・`setup_cuda_paths` :105・`cuda_count` :130・`cuda_libs_ok` :138・`cuda_compute` :159
- **postproc.py** (333 行) — ① 文字起こしの行の後処理: 要確認の印(make_flags)・認識の出力を整える流れ(expand_segments = 行を単語の時刻で分ける split_segment・
  - 名前: `latin_suspect` :31・`sparse_row` :59・`stock_phrase` :74・`repeats_in_line` :91・`make_flags` :102・`note_only` :139・`note_nosub` :144・`expand_segments` :151・`post_values` :193・`clip_rows` :220・`merge_repeats` :237・`trim_ends` :286・ほか 4
- **recognize.py** (364 行) — ① 音声の認識: 動画から音声を取り出す(extract_audio)・声の検出が捨てすぎたら緩めてやり直す(transcribe_vad_fallback)・文字起こしの行(transcribe_real)・
  - 名前: `wav_args` :28・`extract_audio` :59・`seg_to_dict` :88・`vad_kept` :106・`vad_note` :114・`transcribe_vad_fallback` :128・`transcribe_real` :173・`transcribe_rows` :201・`audio_span` :220・`recognize_chunk` :230・`class ChunkModel` :252・`finish_range_lines` :272・ほか 1
- **records.py** (210 行) — ① 文字起こしの記録: recognition.runs の 1 件(エンジンと版・設定・辞書の版・後処理)・配信ごとの文脈と声の検出の記録・
  - 名前: `set_dict_inputs` :24・`pkg_version` :37・`engine_version` :46・`run_engine` :60・`recognition_run` :77・`dtw_record` :97・`engine_timing` :107・`short_hash` :123・`roster_hash` :136・`dict_version` :144・`context_record` :168・`vad_record` :176・ほか 3
- **replace.py** (59 行) — ① 自動の流れの層 pipeline/transcribe: 確度「高」の学習済み置換を機械の出力に当てる(`auto_learned_replace`)。純粋な関数だけ(ファイル・設定を読まない)。
  - 名前: `fixed_finder` :15・`pick_glossary` :37・`auto_learned_replace` :52
- **retime.py** (208 行) — ① 直した行の時刻を単語の時刻から配り直す候補(T1 の簡易版)の計算。
  - 名前: `retime_raw` :94・`retime_candidates` :141
- **roster.py** (306 行) — 名簿(hololive-roster.json)と、配信ごとの文脈(文字起こしの改善の計画 段1。notes:plan/line-b-transcription.md(付録))。
  - 名前: `fold` :40・`load` :51・`channel_regions` :90・`find_in_text` :120・`match_name` :133・`build_context` :144・`member_terms` :168・`fit` :179・`prompt_terms` :194・`stream_context` :204・`leak_only` :229・`alias_variants` :263・ほか 1
- **separate.py** (98 行) — 「編集」のサーバーの部品: 声を伴奏から分けて(Spleeter 2stems・sherpa-onnx・CPU)、分けた声の音量から声のある区間を作る(notes:plan/voice-separation-1022.md)。
  - 名前: `sep_model_dir` :31・`spans_from_db` :35・`voice_spans` :61
- **tx_engines.py** (1376 行) — 文字起こしの認識エンジンの口(精度改善の計画 段2。notes:plan/line-b-transcription.md(付録))。
  - 名前: `engine_home` :52・`engine_of` :61・`env_num` :66・`is_16k_mono` :75・`half_cpu` :80・`class EngineError` :85・`class Engine` :93・`class FasterWhisper` :146・`scan_timings` :225・`gpu_peek` :249・`wcpp_env` :264・`wcpp_bin_dir` :273・ほか 21
- **worker.py** (334 行) — ① 文字起こしの認識ワーカー(統合計画の段階3-3)。編集のサーバーが別プロセスとして起動する(worker_client.WorkerClient)。人が直接起動するものではない。
  - 名前: `class Out` :84・`class JobProxy` :94・`handle` :265・`main` :289
- **worker_client.py** (735 行) — ① 認識ワーカー(別プロセス)とのやり取りとモデル: ワーカーの起動・要求・取り消し・強制終了(WorkerClient・WORKER)・モデルの代理(RemoteModel)・
  - 名前: `release_idle_models` :39・`worker_script` :68・`worker_log` :73・`worker_env` :90・`class WorkerError` :108・`class WorkerClient` :129・`class RemoteModel` :429・`req_engine` :481・`engines_info` :495・`check_engine` :502・`load_model` :515・`nvidia_gpu` :531・ほか 12

## テスト

- tests/pipeline/analyze/fake_ytdlp_chat.py — テスト用の偽の yt-dlp(配信中の live_chat)。tests/pipeline/analyze/test_live_excite_worker.py が、盛り上がりの検出のワーカー(src/pipeline/analyze/live_excite_worker.py の
- tests/pipeline/analyze/test_adopt.py — pipeline/analyze/adopt.py(採用の規則 F-5 の純粋な関数)と ② の口 flow/adopt のテスト。
- tests/pipeline/analyze/test_analyze.py — pipeline/analyze/analyze.py のテスト。 実行(リポジトリ直下): py -3.12 -m unittest tests/pipeline/analyze/test_analyze.py
- tests/pipeline/analyze/test_breaks.py — pipeline/analyze/breaks.py(話の切れ目)のテスト。  py -3.12 -m unittest tests/pipeline/analyze/test_breaks.py -v
- tests/pipeline/analyze/test_excite.py — pipeline/analyze/excite.py(盛り上がりの式)のテスト。  py -3.12 -m unittest tests/pipeline/analyze/test_excite.py -v
- tests/pipeline/analyze/test_live_excite_worker.py — 配信中の盛り上がりの検出(線 D の L2)のワーカー src/pipeline/analyze/live_excite_worker.py のテスト(子プロセスの中身を直に)。
- tests/pipeline/export/test_exporter.py — 書き出し(① pipeline/export/exporter)のテスト。
- tests/pipeline/export/test_outcheck.py — 書き出しのあとの自動の点検(① pipeline/export/outcheck)のテスト。本物の ffmpeg で合成した壊れた動画(黒いコマ・無音・割れ・声の途中で切れる・長さ違い)を点検する。
- tests/pipeline/ingest/hls_fixture.py — テスト用の「配信中のような HLS」(本物の YouTube には繋がない)。
- tests/pipeline/ingest/test_recorder.py — 録画の部品(recorder/)のテスト。本物の YouTube には繋がない: ffmpeg の lavfi で作った HLS を、手元の HTTP サーバーで
- tests/pipeline/pack/test_contracts.py — 別のプログラムが読む形の見本(tests/ytt/fixtures/contracts/ の clip/v1.json・transcript/v1.json)。書く側が書いた形は見本と同じ鍵・
- tests/pipeline/pack/test_cut2resolve.py — パックのテストの道具(見本の動画・EDL の読み方・採用区間からのパック)と、通しでは起こせない物の単体
- tests/pipeline/pack/test_edge_pause.py — 切り抜きの両端を話の間へ寄せる(pipeline/pack/edge_pause)の純粋な部分
- tests/pipeline/pack/test_pack.py — パック(pipeline.pack)のテスト。正しく動く道・端の場合・時刻の計算・入力の誤りは、本物の ffmpeg の通し(TestPackRun)で見本に混ぜてまとめて確かめる。
- tests/pipeline/pack/test_resolve_export.py — resolve_export(Resolve パッケージ = cut2resolve の Text+ パックを zip にしたもの)の通し(本物の ffmpeg)と HTTP の口。
- tests/pipeline/transcribe/fake_llama_server.py — テスト用の偽の llama-server(tx_engines.LlamaQwen3.COMMAND に [python, このファイル] を入れて使う)。
- tests/pipeline/transcribe/fake_whisper_cli.py — テスト用の偽の whisper-cli(tx_engines.WhisperCpp.COMMAND に [python, このファイル] を入れて使う)。
- tests/pipeline/transcribe/test_clipjob.py — pipeline/transcribe/clipjob(文字起こしのジョブの機械の文書の行)を、編集の serve を読まずに疑似のエンジンで使うテスト。
- tests/pipeline/transcribe/test_diarize.py — pipeline/transcribe/diarize(話者判別の計算・判別の記録・声の特徴)を、編集の serve を読まずに使うテスト。
- tests/pipeline/transcribe/test_fill.py — 文字起こしのジョブの後処理(A 別の読み・B 頭の名前・E LLM・配信ごとの文脈)を ③ の run_job で 1 回通し、文書と記録に残る形を確かめるテスト。test_metrics から読み込まれる。
- tests/pipeline/transcribe/test_fill_llm.py — pipeline/transcribe の fill(認識のあとの後処理 A・B・C・D)と llm(LLM の後処理 E)のテスト。編集の serve・ed_state は読まない。
- tests/pipeline/transcribe/test_live_tx_worker.py — 配信中の候補の文字起こしの子プロセス src/pipeline/transcribe/live_tx_worker.py のテスト(D-11 案 b)。本物の認識はしない。
- tests/pipeline/transcribe/test_llm.py — LLM の後処理 E(pipeline/transcribe/llm.py)の、通しで起こせない所のテスト。test_metrics から読み込まれる。
- tests/pipeline/transcribe/test_postproc.py — ① 文字起こしの行の後処理(clipjob.make_doc_rows = 整える postproc → 名前を外す B → 末尾の重複 C と別の読み A → 印・置換辞書 → 名簿の呼び名 D → LLM E)を、
- tests/pipeline/transcribe/test_qwen3.py — Qwen3-ASR のエンジン(tx_engines.LlamaQwen3 = llama.cpp の 1.7B)のテスト。test_metrics から読み込まれる。
- tests/pipeline/transcribe/test_recognize.py — pipeline/transcribe/recognize(音声の取り出し・認識・範囲の行・)を、編集の serve を読まずに使うテスト。
- tests/pipeline/transcribe/test_records.py — 記録の土台のテスト。
- tests/pipeline/transcribe/test_roster.py — 名簿の呼び名(pipeline/transcribe/roster.py)と同梱の名簿のテスト。
- tests/pipeline/transcribe/test_txbackend.py — pipeline/transcribe の本物と疑似の差し込み口 backend のテスト(役割で組み直す RS2-2)。
- tests/pipeline/transcribe/test_txrecords.py — pipeline/transcribe/records(認識の記録・辞書の版・生出力・単語の時刻)を、編集の serve を読まずに使うテスト。
- tests/pipeline/transcribe/test_txroster.py — pipeline/transcribe/roster の配信ごとの文脈 stream_context と用語の区切り split_terms(ytt/txtext)を、編集の serve を読まずに使うテスト。
- tests/pipeline/transcribe/test_whispercpp.py — whisper.cpp のエンジン(tx_engines.WhisperCpp)のテスト。test_metrics から読み込まれる。
- tests/pipeline/transcribe/test_worker.py — 認識ワーカー(src/pipeline/transcribe/worker.py。別プロセス)のテスト。  python -m unittest test_worker -v
- tests/pipeline/transcribe/test_worker_client.py — pipeline/transcribe/worker_client(認識ワーカーとのやり取り・モデル・wav を読まずに渡す形。役割で組み直す RS2-6)を、編集の serve を読まずに使うテスト。
- tests/pipeline/transcribe/voice_fixture.py — 文字起こしの本物の通しの下ごしらえ(テストではない)。
