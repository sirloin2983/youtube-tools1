# コードの地図: ① pipeline(道具 = データを加工する)

自動で作った物(`python dev/code_map.py`)。手で直さない。目次は [index.md](index.md)。`file:line` の行の番号は作った時点の物。

## src/pipeline/

- **__init__.py** (2 行) — ① 道具(解析 analyze・書き出し export・文字起こし transcribe・パック pack・録画の取り込み ingest。1 つ 1 つが「入力 → 出力」の変換)。画面・案件・順番を知らない。ytt だけを import する。いつ・どの順で・どこに置いて・飛ばすかは ② の s…

## src/pipeline/analyze/

- **__init__.py** (2 行) — ① 解析: 材料の取得(fetch。動画・チャット・コメント)・音量(levels)・盛り上がりの式(excite)・候補・話の切れ目(breaks)・自動採用・配信中の検出
- **adopt.py** (73 行) — 採用の規則 F-5(notes:plan/done/role-restructure.md 5-5・決定 3-29 Q3。純粋な関数)。
  - 名前: `check_args` :18・`adopt` :35
- **analyze.py** (413 行) — 解析(自動切り抜き ac/serve.py 由来。書き出し・手動の○×は持たない)。
  - 名前: `sig_cache_dir` :37・`validate_live` :44・`validate_source` :50・`validate_settings` :65・`make_spec` :80・`chat_public` :89・`sig_path` :96・`load_sig` :100・`save_sig` :117・`archive_path` :130・`load_archive` :134・`save_archive` :144・ほか 3
- **breaks.py** (123 行) — 話の切れ目(breaks)。切り抜きの区間の両端を、文字起こしの話の切れ目へ寄せて言葉の途中で切らないための関数(線 LD-2c。notes:plan/done/ld2-clip-length.md)。
  - 名前: `cuts` :61・`snap` :106・`inside_row` :120
- **excite.py** (997 行) — 盛り上がり(excitement)の式。スタジオのアーカイブの解析(src/pipeline/analyze/analyze.py)と、配信中の検出(src/pipeline/analyze/live_excite_worker.py。線 D の L2)が同じ式を読む(線 D の L1。notes…
  - 名前: `smooth` :64・`median` :75・`local_baseline` :81・`robust_scale` :100・`audio_score` :106・`chat_z` :118・`shift_chat` :127・`chat_score` :133・`estimate_lag` :137・`ramp` :161・`head_ramp` :166・`comment_score` :173・ほか 14
- **fetch.py** (494 行) — 解析の材料を取ってくる仕事(音声のダウンロード・チャットのリプレイの取得と先読み・コメント欄・動画の付加情報)と、そのキャッシュの置き場と掃除。
  - 名前: `work_dir` :30・`chat_cache_dir` :34・`download_audio` :49・`chat_cache_path` :69・`drop_chat_cache` :73・`chat_cache_limit` :90・`use_chat_cache` :105・`prune_chat_cache` :115・`download_chat` :163・`prefetch_chat` :245・`cancel_prefetch` :288・`cancel_all_prefetch` :295・ほか 8
- **levels.py** (64 行) — 1 秒ごとの音量(RMS, dB)を、ffmpeg 1 回のデコードで全帯域と高音域(2kHz 超)の 2 系列に測る決まり(OPT1)。
  - 名前: `args` :23・`clear` :30・`level` :36・`read` :47・`collect` :56
- **live_excite_worker.py** (1494 行) — 配信中の盛り上がりの検出のワーカー(線 D の L2。notes:plan/line-d-detect.md・notes:plan/line-d-live-clipping.md の 0-10)。入口(src/flow/live_detect.py)が起動する子プロセス。
  - 名前: `class MeasureError` :115・`class NoTool` :119・`class RecorderDown` :123・`clean_requests` :131・`request_spec` :146・`clean_spec_doc` :159・`clean_bundles` :173・`clean_detect` :184・`measure_levels` :191・`parse_chat_line` :211・`clean_hint` :239・`spec_with_hint` :254・ほか 8

## src/pipeline/export/

- **__init__.py** (2 行) — ① 書き出し: 区間 → 動画(exporter)・サムネの案の絵(thumb_cards)
- **exporter.py** (993 行) — ③ 書き出し(クリップマーカー cm/serve.py 由来): store の動画・マークから ffmpeg / yt-dlp でクリップを mp4 にする。
  - 名前: `class ExportError` :51・`log_export` :55・`reason` :71・`verify_output` :78・`pick_folder` :87・`promote` :96・`drop_partial` :113・`clean_partials` :119・`check_section_path` :215・`build_section_spec` :236・`spec_from_video` :262・`new_result` :314・ほか 13
- **thumb_cards.py** (175 行) — サムネの案の描く部分(提案 P5 の S。notes:plan/thumb-ideas.md の 7・8)。ffmpeg で動画から 1 枚ずつ切り取って文字を載せ、6 案を 1 枚の PNG にまとめる。
  - 名前: `class ThumbError` :21・`ffmpeg_path` :28・`probe` :35・`loud_times` :45・`scene_times` :60・`font_path` :69・`fpath` :76・`text_filter` :81・`card_filters` :90・`crop_box` :120・`render_card` :138・`tile` :153・ほか 1

## src/pipeline/ingest/

- **__init__.py** (2 行) — ① 取り込み: 配信中の録画(recorder・rec_core)と、録画とアーカイブの音の照合(live_align_worker)。YouTube からの取得は export/exporter と analyze/fetch
- **live_align_worker.py** (133 行) — 音の照合(線 D の P4。notes:plan/line-d-live-clipping.md の 0-9)の子プロセス。**入口のプロセスから import しない
  - 名前: `fail` :34・`read_wav` :39・`next_pow2` :54・`xcorr_valid` :59・`align` :79・`main` :103
- **rec_core.py** (910 行) — 録画の中身(線 D の P1。notes:plan/line-d-live-clipping.md の 0・2〜4)。HTTP は recorder.py。
  - 名前: `class RecError` :79・`to_utc` :90・`pick_segments` :101・`validate_url` :121・`fetch_title` :143・`folder_state` :162・`parse_playlist` :186・`keep_order` :209・`build_playlist` :230・`read_text` :252・`clean_tmp` :281・`new_rec_id` :296・ほか 2
- **recorder.py** (371 行) — 録画の部品(線 D: リアルタイム切り抜きの P1。notes:plan/line-d-live-clipping.md の 0)。入口とは別のプロセスで動く。
  - 名前: `data_dir` :57・`load_token` :64・`read_settings` :79・`save_folder` :83・`clean_folder` :90・`make_logger` :104・`raise_priority` :128・`class Handler` :140・`class Server` :283・`parse_args` :294・`main` :314
  - 受ける口: `/api/ping` :180

## src/pipeline/pack/

- **__init__.py** (2 行) — ① パック: DaVinci Resolve に読ませるパック(pack・cut2resolve_core・srt2resolve)・Text+(resolve_textplus)・zip の受け渡し(resolve_export)・指定の読み(request)・自動のカット(auto_cut)・…
- **auto_cut.py** (141 行) — カットの計画の部品(read_cut_plan・build_plan・plan_from_keeps・finalize_plan。pack.py が使う)。
  - 名前: `read_cut_plan` :16・`default_handles` :71・`build_plan` :77・`removed_between` :98・`plan_from_keeps` :109・`finalize_plan` :117
- **cut2resolve_core.py** (889 行) — cut2resolve 共通部
  - 名前: `class Cancelled` :48・`class OutputExists` :55・`class Task` :64・`parse_time` :79・`parse_cut_list` :117・`sec_to_frames` :148・`cue_frames` :152・`frames_to_sec` :158・`fps_label` :163・`cut_list_to_keeps` :168・`normalize` :183・`subtract` :201・ほか 36
- **pack.py** (948 行) — カットの計算(試算)とパックの作成。② の CLI(src/app/cli.py)と画面(serve.py)の両方から呼ぶ共通部(処理を二重に持たない)。
  - 名前: `class RowEdge` :41・`class Request` :76・`class Plan` :113・`class Cache` :137・`default_out_dir` :201・`row_edge_from` :205・`widen_row_edges` :229・`row_edge_pending` :272・`silence_pending` :281・`detect_pending` :289・`without_detect` :298・`plan_cut` :317・ほか 15
- **preview.py** (124 行) — ① 確認用の動画(友人が受け取るかを決める前に見る、1 本の切り抜きの 480p の動画)とパックの中の切り抜きの動画の引き方(ds1 = 要件 1-5。② flow/deliver から分けた)。
  - 名前: `pack_title` :24・`scratch_path` :30・`remove_quiet` :35・`pack_video` :41・`make_preview` :80・`clip_preview` :105・`pack_seconds` :118
- **request.py** (336 行) — パックの指定(JSON の spec・output)-> pack.Request と build_pack の引数。指定の読み方の 1 か所
  - 名前: `clean_path` :33・`input_path` :58・`request_from_spec` :103・`clip_range_from_spec` :174・`row_edge_from_spec` :184・`advanced_from_spec` :193・`keeps_from_spec` :204・`speaker_color_map` :225・`speaker_styles_from` :244・`apply_speaker_styles` :267・`output_from_spec` :288・`speaker_colors_for` :327
- **resolve_export.py** (379 行) — DaVinci Resolve への受け渡し(文字起こしツールの「Resolveパッケージ(zip)をダウンロード」)と、「残す行」の規則。
  - 名前: `srt_time` :38・`srt_text` :44・`is_kept` :50・`kept_spans` :56・`tool_info` :83・`sorted_segments` :87・`build_transcript_v1` :106・`build_cut_plan_v1` :134・`wrap_text` :147・`build_srt` :154・`pack_instructions` :174・`edit_draft` :237・ほか 3
- **resolve_textplus.py** (1019 行) — Resolve Free向け Text+ 試験パック。Luaスクリプトを同梱する。
  - 名前: `hex_rgba` :70・`text_style` :81・`style_inputs` :97・`video_tracks_value` :119・`parse_target` :126・`caption_segments` :149・`stack_captions` :180・`default_wrap` :252・`wrap_caption` :257・`build_import_plan` :295・`importer_script` :363・`installer_script` :781・ほか 6
- **srt2resolve.py** (358 行) — パックの部品(動画の情報の読み取り・字幕の読み込み・フレームの計算・SRT の組み立ての小道具)。
  - 名前: `class ToolError` :28・`same_path` :32・`staged` :45・`write_text_atomic` :57・`tool` :66・`arg_path` :71・`clean_text` :95・`parse_subs` :102・`read_sub_file` :126・`snap_fps` :150・`codec_warnings` :162・`probe` :199・ほか 9

## src/pipeline/transcribe/

- **__init__.py** (2 行) — ① 文字起こし: 認識(エンジン・ワーカー)・話者・後処理(埋める・LLM・時刻)・名簿と辞書を読む。認識(重い)と後処理(軽い)で鍵を分ける
- **backend.py** (114 行) — サーバー側の認識の本物と疑似の差し込み口。
  - 名前: `mode` :18・`is_fake` :23・`class Backend` :28・`set_selector` :106・`select` :111
- **clipjob.py** (62 行) — ① 文字起こしのジョブの機械の文書の行を作る(make_doc_rows)。
  - 名前: `make_doc_rows` :15
- **diarize.py** (542 行) — ① 自動の流れの層 pipeline/transcribe: 話者判別の計算(sherpa-onnx)と判別の記録・声の特徴と覚えた声との照らし合わせ。
  - 名前: `diar_threads` :54・`has_sherpa` :60・`diar_models_dir` :66・`diar_info` :79・`ensure_diar_models` :109・`diar_tune` :140・`diarize_real` :156・`assign_speakers` :195・`label_ratio` :246・`smooth_labels` :254・`smooth_speakers` :276・`diar_path` :296・ほか 8
- **fill.py** (378 行) — 「編集」のサーバーの部品: 認識のあとの後処理(A・C・D。notes:plan/line-b-transcription.md の「10-08 の実験ループ」)。
  - 名前: `fill_norm` :62・`fill_chars` :67・`fill_sparse_row` :72・`fill_apply` :91・`fill_clean_tail` :121・`fill_stock` :134・`fill_voice_frac` :140・`fill_clean_turns` :148・`fill_spk_key` :173・`fill_spk_names` :178・`fill_spk_split` :194・`fill_strip_names` :223・ほか 7
- **live_tx_worker.py** (71 行) — 配信中の候補の文字起こし(線 D の D-11 案 b。notes:plan/line-d-live-clipping.md の 0-11)の子プロセス。**入口のプロセスから import しない
  - 名前: `recognize` :28・`main` :53
- **llm.py** (340 行) — 「編集」のサーバーの部品: LLM の後処理(提案 P18。notes:plan/done/llm-postfix.md)。
  - 名前: `llm_fold` :53・`llm_dist` :64・`llm_members` :75・`llm_targets` :86・`llm_near` :99・`llm_pick` :116・`llm_messages` :137・`llm_parse` :149・`llm_names` :167・`llm_guard` :177・`llm_cap` :198・`llm_apply` :211・ほか 7
- **models.py** (163 行) — ① 認識ワーカーの中で動く物: 読み込んだモデルの使い回し(_models)と読み込み(_load_model_local)・しばらく使わなければ手放す(release_idle_local)・
  - 名前: `models_touched` :31・`release_idle_local` :36・`setup_cuda_paths` :105・`cuda_count` :130・`cuda_libs_ok` :138・`cuda_compute` :159
- **postproc.py** (314 行) — ① 文字起こしの行の後処理: 要確認の印(make_flags)・認識の出力を整える流れ(expand_segments = 行を単語の時刻で分ける split_segment・
  - 名前: `latin_suspect` :31・`sparse_row` :59・`stock_phrase` :74・`repeats_in_line` :91・`make_flags` :102・`expand_segments` :135・`post_values` :174・`clip_rows` :201・`merge_repeats` :218・`trim_ends` :267・`join_rows` :280・`machine_conf` :291・ほか 2
- **recognize.py** (362 行) — ① 音声の認識: 動画から音声を取り出す(extract_audio)・声の検出が捨てすぎたら緩めてやり直す(transcribe_vad_fallback)・文字起こしの行(transcribe_real)・
  - 名前: `wav_args` :28・`extract_audio` :59・`seg_to_dict` :88・`vad_kept` :106・`vad_note` :114・`transcribe_vad_fallback` :128・`transcribe_real` :171・`transcribe_rows` :199・`audio_span` :218・`recognize_chunk` :228・`class ChunkModel` :250・`finish_range_lines` :270・ほか 1
- **records.py** (178 行) — ① 文字起こしの記録: recognition.runs の 1 件(エンジンと版・設定・辞書の版・後処理)・配信ごとの文脈と声の検出の記録・
  - 名前: `set_dict_inputs` :24・`pkg_version` :37・`engine_version` :46・`run_engine` :60・`recognition_run` :77・`short_hash` :91・`roster_hash` :104・`dict_version` :112・`context_record` :136・`vad_record` :144・`asr_path` :155・`capture_raw` :160・ほか 1
- **replace.py** (59 行) — ① 自動の流れの層 pipeline/transcribe: 確度「高」の学習済み置換を機械の出力に当てる(`auto_learned_replace`)。純粋な関数だけ(ファイル・設定を読まない)。
  - 名前: `fixed_finder` :15・`pick_glossary` :37・`auto_learned_replace` :52
- **retime.py** (268 行) — ① 字幕の読む速さの印(T2)と、直した行の時刻を単語の時刻から配り直す候補(T1 の簡易版)の計算。
  - 名前: `subread_chars` :44・`subread_limits` :49・`subread_mark` :62・`retime_raw` :154・`retime_candidates` :201
- **roster.py** (305 行) — 名簿(hololive-roster.json)と、配信ごとの文脈(文字起こしの改善の計画 段1。notes:plan/line-b-transcription.md(付録))。
  - 名前: `fold` :39・`load` :50・`channel_regions` :89・`find_in_text` :119・`match_name` :132・`build_context` :143・`member_terms` :167・`fit` :178・`prompt_terms` :193・`stream_context` :203・`leak_only` :228・`alias_variants` :262・ほか 1
- **tx_engines.py** (1239 行) — 文字起こしの認識エンジンの口(精度改善の計画 段2。notes:plan/line-b-transcription.md(付録))。
  - 名前: `engine_home` :52・`engine_of` :61・`env_num` :66・`is_16k_mono` :75・`half_cpu` :80・`class EngineError` :85・`class Engine` :93・`class FasterWhisper` :146・`wcpp_env` :214・`wcpp_bin_dir` :223・`wcpp_model_dir` :228・`wcpp_binary_ok` :232・ほか 19
- **worker.py** (322 行) — ① 文字起こしの認識ワーカー(統合計画の段階3-3)。編集のサーバーが別プロセスとして起動する(worker_client.WorkerClient)。人が直接起動するものではない。
  - 名前: `class Out` :84・`class JobProxy` :94・`handle` :253・`main` :277
- **worker_client.py** (748 行) — ① 認識ワーカー(別プロセス)とのやり取りとモデル: ワーカーの起動・要求・取り消し・強制終了(WorkerClient・WORKER)・モデルの代理(RemoteModel)・
  - 名前: `release_idle_models` :40・`worker_script` :69・`worker_log` :74・`worker_env` :91・`class WorkerError` :109・`class WorkerClient` :130・`class RemoteModel` :430・`req_engine` :480・`engines_info` :494・`check_engine` :501・`load_model` :514・`nvidia_gpu` :533・ほか 12

## テスト

- src/pipeline/analyze/tests/fake_ytdlp_chat.py — テスト用の偽の yt-dlp(配信中の live_chat)。src/pipeline/analyze/tests/test_live_excite_worker.py が、盛り上がりの検出のワーカー(src/pipeline/analyze/live_excite_worker.py の
- src/pipeline/analyze/tests/test_adopt.py — pipeline/analyze/adopt.py(採用の規則 F-5 の純粋な関数)と ② の口 flow/adopt のテスト。
- src/pipeline/analyze/tests/test_analyze.py — pipeline/analyze/analyze.py のテスト。 実行(リポジトリ直下): py -3.12 -m unittest src/pipeline/analyze/tests/test_analyze.py
- src/pipeline/analyze/tests/test_breaks.py — pipeline/analyze/breaks.py(話の切れ目)のテスト。  py -3.12 -m unittest src/pipeline/analyze/tests/test_breaks.py -v
- src/pipeline/analyze/tests/test_excite.py — pipeline/analyze/excite.py(盛り上がりの式)のテスト。  py -3.12 -m unittest src/pipeline/analyze/tests/test_excite.py -v
- src/pipeline/analyze/tests/test_live_excite_worker.py — 配信中の盛り上がりの検出(線 D の L2)のワーカー src/pipeline/analyze/live_excite_worker.py のテスト(子プロセスの中身を直に)。
- src/pipeline/export/tests/test_exporter.py — 書き出し(① pipeline/export/exporter)のテスト。
- src/pipeline/ingest/tests/hls_fixture.py — テスト用の「配信中のような HLS」(本物の YouTube には繋がない)。
- src/pipeline/ingest/tests/test_recorder.py — 録画の部品(recorder/)のテスト。本物の YouTube には繋がない: ffmpeg の lavfi で作った HLS を、手元の HTTP サーバーで
- src/pipeline/pack/tests/test_contracts.py — 別のプログラムが読む形の見本(src/ytt/tests/fixtures/contracts/ の clip/v1.json・transcript/v1.json)。書く側が書いた形は見本と同じ鍵・
- src/pipeline/pack/tests/test_cut2resolve.py — パックのテストの道具(見本の動画・EDL の読み方・採用区間からのパック)と、通しでは起こせない物の単体
- src/pipeline/pack/tests/test_pack.py — パック(pipeline.pack)のテスト。正しく動く道・端の場合・時刻の計算・入力の誤りは、本物の ffmpeg の通し(TestPackRun)で見本に混ぜてまとめて確かめる。
- src/pipeline/transcribe/tests/test_clipjob.py — pipeline/transcribe/clipjob(文字起こしのジョブの機械の文書の行)を、編集の serve を読まずに疑似のエンジンで使うテスト。
- src/pipeline/transcribe/tests/test_diarize.py — pipeline/transcribe/diarize(話者判別の計算・判別の記録・声の特徴)を、編集の serve を読まずに使うテスト。
- src/pipeline/transcribe/tests/test_fill_llm.py — pipeline/transcribe の fill(認識のあとの後処理 A・B・C・D)と llm(LLM の後処理 E)のテスト。編集の serve・ed_state は読まない。
- src/pipeline/transcribe/tests/test_live_tx_worker.py — 配信中の候補の文字起こしの子プロセス src/pipeline/transcribe/live_tx_worker.py のテスト(D-11 案 b)。本物の認識はしない。
- src/pipeline/transcribe/tests/test_postproc.py — ① 文字起こしの行の後処理(clipjob.make_doc_rows = 整える postproc → 名前を外す B → 末尾の重複 C と別の読み A → 印・置換辞書 → 名簿の呼び名 D → LLM E)を、
- src/pipeline/transcribe/tests/test_recognize.py — pipeline/transcribe/recognize(音声の取り出し・認識・範囲の行・)を、編集の serve を読まずに使うテスト。
- src/pipeline/transcribe/tests/test_txbackend.py — pipeline/transcribe の本物と疑似の差し込み口 backend のテスト(役割で組み直す RS2-2)。
- src/pipeline/transcribe/tests/test_txrecords.py — pipeline/transcribe/records(認識の記録・辞書の版・生出力・単語の時刻)を、編集の serve を読まずに使うテスト。
- src/pipeline/transcribe/tests/test_txroster.py — pipeline/transcribe/roster の配信ごとの文脈 stream_context と用語の区切り split_terms(ytt/txtext)を、編集の serve を読まずに使うテスト。
- src/pipeline/transcribe/tests/test_worker_client.py — pipeline/transcribe/worker_client(認識ワーカーとのやり取り・モデル・wav を読まずに渡す形。役割で組み直す RS2-6)を、編集の serve を読まずに使うテスト。
- src/pipeline/transcribe/tests/voice_fixture.py — 文字起こしの本物の通しの下ごしらえ(テストではない)。
