> 状態(2026-10-10 朝): 下調べ(読むだけ。Sonnet)の報告そのまま。行番号は 2026-10-10 の main(1b27688)のもの。順番と決めることのまとめは `plan/role-restructure.md` の 8 節「RS3・RS4 の手順の案」と `plan/decisions.md` の 3-25。

# RS3(編集の分)の下調べ — 2026-10-10(読むだけ。リポジトリは書き換えていない・テストも流していない)

調べ方: `ast` で各ファイルのトップレベルの名前・import・`ed_xxx.名前` の読みを数える小さな .py(scratchpad の `analyze_files.py`・`readers.py`・`callgraph.py`・`state_names.py`・`txenv_use.py`・`patches.py`)と grep。
「参照数」は文字の一致で数えたので、コメント・docstring の中の言及を少し含む(桁の目安)。違反の数は `dev/layer_map.py` の KNOWN(49 件)を直接読んだ(`test_layering.py --list` は流していない)。
前提: 1b27688 の時点(RS2-9 まで済み・作業フォルダはきれい)。

---

## 1. ファイルごとの現状と行き先

総括表(行数 / トップレベルの def+class 数 / 変数数 / 行き先):

| ファイル | 行 | def | var | 行き先 |
| --- | --- | --- | --- | --- |
| `ed_store.py` | 1091 | 61 | 26 | **分割**: human/proof(文書+編集の内容)・manage/cases(一覧・パックの手順)・ytt(スタジオ data.json の読み口・probe_media) |
| `ed_alt.py` | 418 | 20 | 11 | **丸ごと** human/proof/alt.py |
| `ed_ytcap.py` | 530 | 25 | 26 | **丸ごと** human/proof/ytcap.py |
| `ed_retime.py` | 41 | 2 | 0 | **丸ごと** human/proof/retime.py(包み) |
| `ed_learn.py` | 1301 | 61 | 34 | **分割**(5 つ): ytt/settings・pipeline/transcribe・human/proof・eval/drill・eval/tools |
| `ed_relink.py` | 1058 | 54 | 23 | **分割**(5 つ): manage/cases(付け替え+30fps)・ytt(評価用の判定・_move)・eval/drill(評価用フォルダ) |
| `ed_misc.py` | 484 | 21 | 7 | **分割**(5 つ): eval/drill(A/B)・manage/cases(マーカー・受け渡し)・human/proof(フォルダ一括)・app(runtime_path_dir) |
| `pipeline_io.py` | 294 | 18 | 25 | manage/cases(読み・保存・.runtime)。**transcript/v1 などの組み立て 85 行だけ pipeline/pack へ** |
| `resolve_export.py` | 294 | 19 | 2 | **丸ごと** pipeline/pack/resolve_export.py(+ 上の組み立てを受ける) |
| `ed_media.py` | 154 | 6 | 6 | **動かさない**(app。波形の配信) |
| `ed_thumb.py` | 87 | 6 | 3 | **動かさない**(app。ジョブの接着) |
| `thumb_ideas.py` | 395 | 26 | 12 | human/cut/thumb_ideas.py(丸ごと。違反は無いので急がない) |
| `ed_state.py` | 370 | 23 | 76 | **痩せさせる**: 状態を持つ名前を ytt へ・残りは app の物だけ(約 120〜150 行) |

### 1-1 ed_store.py(1091 行)
- 境目(行 = 今のファイル。`callgraph.py` で節ごとの呼び合いを見た):
  - 文書の読み書き・履歴・整形・手間・「文字起こしせずに開く」: 24-170(tx_path・write_doc・snapshot・backup_doc・sanitize_*・doc_length)、395-565(read_transcript・HIST_*・_save_lock・save_transcript・restore_history・effort・set_diar_num)、1003-1030(doc_has_rows・fill_doc)、1047-1091(find_doc_for_media・open_video)→ **human/proof/store.py**
  - 要約のキャッシュ 172-272(good_row・row_dur・_load_doc・_prog_of・transcript_summary・summaries・prune_cache)→ store に残す(進行度 `_prog_of` は ed_store:196 の中だけで計算 = 上向きの読みは無い。ドリル `_part("ドリル", ed_drill.drill_doc_summary, d)` が ed_store:246 で **human→eval**)
  - 編集の内容(edit.json)と「パックを作った」記録: 566-809(sanitize_edit・read_edit・edit_cut_flags・apply_edit_cuts・edit_draft・edit_preview・wrap_arg)、837-1002(get_edit・save_edit・sanitize_pack_output・record_pack・edit_summary・pack_stale)→ 計画は human/cut だが、**今は store に同居を勧める**(下の注)
  - スタジオの data.json の読み口 275-325(_studio_parse・_studio_load・studio_videos・studio_stream)→ **ytt/studiodata.py**(pipeline の roster.stream_context が使うため。map の要相談 #4 の案)
  - 一覧と「元の動画・パックの有無」326-394(pack_info・_files_state・list_transcripts)と前回のパックの手順 810-836(pack_readme)→ **manage/cases/doclist.py**(txindex = manage を読むのはここだけ: ed_store:332・817)
  - probe_media 1031-1046 → ytt/tools(ed_media・ed_relink・ed_state も使う)
- 注(edit.json を割らない理由): `callgraph` で **doc→cut が 3 本**(save_transcript・restore_history・fill_doc が apply_edit_cuts を呼ぶ)・**cut→doc が 9 本**(read_transcript・_save_lock・write_doc)と相互に呼ぶ。文書を書くたびに行の cutState を付け直す決まり(src/editor/AGENTS.md「行の cutState は…apply_edit_cuts」)があるので、割ると循環の import になる。human どうしなので違反ではない。割るのは UI を再考するとき(human/cut を作るとき)でよい。
- 依存: `ed_state` 110 refs / 28 名(ytt の別名 17 種・パス `TX_DIR`×7・`STUDIO_DATA`・関数 5(check_source・ffmpeg_info・duration_in・find_ffmpeg・pio)・定数 4(MAX_SEGMENTS・TAGS・SERVER_VERSION×2・TOOL_ID))。他の部品: `ed_relink.in_eval_dir`(144・488)・`ed_drill.drill_doc_summary`(246)・`ed_misc._read_json_file`(280)・`ed_learn.load_settings`(758)・`ed_jobs.subtitle_settings`(806 = 今の持ち主は doc_jobs)・`resolve_export`(内側の import 744・790・824)・`txindex`(内側 332・817)。KNOWN の組: (store→state)(store→drill)(store→misc)(store→relink)(store→txindex)= 5 本。
- 読み手(参照数): src = serve 27・human/proof/speakers 30・rerun 17・doc_jobs 11・ed_relink 30・ed_drill 22・ed_evalbatch 11・ed_learn 13・ed_misc 8・ed_ytcap 5・ed_alt 4・ed_media 2・ed_thumb 2・ed_retime 1。dev = eval_effort 5・eval_asr 2・eval_cut 1(コメントが多い)。tests(`import ed_store` する物)= test_evalbatch(40)・test_fill 6・test_llm 5・test_normalize30 4・test_alt 3・test_ytcap 2・test_autodiar 1・test_txroster 1・dev/tests/test_eval_effort 1。
- テストの差し替え: `S.read_transcript`(test_backend・test_ovdraft 計 3)・`S.HIST_INTERVAL`(test_metrics 2)・`S.PACK_CHECK_BUDGET`(test_backend)・`S.EDIT_SCHEMA`(test_edit)・`S.STUDIO_DATA = …`(test_backend:327・test_roster:147)。どれも `S.` 経由 = `_ED_MODULES` に持ち主を並べれば届く。

### 1-2 ed_alt.py(418 行)/ ed_ytcap.py(530 行)/ ed_retime.py(41 行)
- どれも**ファイル単位で human/proof へ**。純粋な計算(alt: alt_diffs 257-360・alt_notation_only・_alt_windows、ytcap: ytcap_parse_json3・ytcap_diffs)とジョブ(run_alt・run_ytcap)が同居するが、境目を割る利点が無い(どちらも human)。
- ed_alt の依存: `ed_state` 33 refs / 17 名(ApiError×7・num×6・backend_name×5・TMP_DIR×2 ほか)・`ed_store`(_save_lock・doc_has_rows・read_transcript・tx_path)・`ed_relink.in_eval_dir`(97)・`ed_jobs`(殻)13 名(add_job・tid_busy・job_errors・job_done・Cancelled・check_engine・engine_home・engine_version・expand_segments・extract_audio・split_chars_for・transcribe_fake・transcribe_real)・`ed_learn.load_settings`(58)。pipeline/transcribe の `tx_engines`・`txbase` は直に読んでいる。
  - **上向きの読みが 1 つ残る**: `ed_jobs.transcribe_fake`(139)= eval/fake。`ed_state.backend_name() == "fake"` が 5 か所(65・114・147・166・186)。口の案: `backend.select().name == "fake"`(fill・llm と同じ)と、`Backend` に `alt_rows(job, spec, wav, total, real)` を足して `_alt_fake`(131-143。環境変数 `TRANSCRIBE_FAKE_ALT`)の本体を `eval/fake/fake_asr.py` へ。
  - 書く側の設定の検査 `altEngine`(ed_learn:58 が `ed_alt.ALT_ENGINES` を読む)は、ytt/settings の鍵の登録(下の 1-4)に変えると ed_learn→ed_alt の向きが消える。
- ed_ytcap の依存: `ed_state` 55 refs / 13 名(ApiError×32・num×9)・`ed_alt`(alt_cached・alt_diffs・alt_fold・alt_skip・alt_spans_of)・`ed_store`・`ed_relink.in_eval_dir`(111)・`ed_jobs`(add_job・tid_busy・job_errors・job_done・Cancelled)。yt-dlp は `ytt.tools` で動かす(ed_ytcap:36)。上向きの読みは `in_eval_dir` だけ。
- ed_retime の依存: `ed_alt.alt_first_run`・`ed_store.read_transcript`・`pipeline.transcribe.records/retime`・`ytt.errors`(層は human なので違反なし)。
- 読み手: ed_alt = ed_ytcap 8・serve 5・ed_learn 4・doc_jobs 1・ed_retime 1・tests(test_alt・test_ytcap・e2e_alt・test_metrics)。ed_ytcap = serve 5・ed_learn 2・doc_jobs 1・dev/eval_alt 1・tests(test_ytcap・e2e_alt・fake_ytdlp)。ed_retime = serve 2・tests(test_retime・test_names・test_metrics)。
- テストの差し替え: `patch.object(ed_alt, "alt_spec")`(test_alt)・`ed_ytcap` の `YTCAP_DIR`・`YTCAP_TIMEOUT_SEC`・`ytcap_spec`(test_ytcap)・`mock.patch.object(ed_state, "FEEDBACK", …)`(test_alt:109・test_ytcap:160 の set-up。dev/eval_alt:109-114 は直に代入)。**ed_state に直に当てる書き方は持ち主を変えると届かなくなる**(test_llm:134・177 の `ed_state.ROSTER`、test_smooth:151-175 の `S.ed_state` 経由の `check_source`/`media_duration`/`backend_name`、dev/tests/test_eval_asr:168・210-211 の `S.ed_state.STUDIO_DATA`/`gpu_ready`/`backend_name` も同じ)→ `S` に当てる形へ直す。

### 1-3 ed_learn.py(1301 行)— 5 つに割れる
`callgraph.py` の節ごとの呼び合い(下の「→」は「呼ぶ」。逆向きの呼びは無い):
| 節(行) | 中身 | 行き先 | 備考 |
| --- | --- | --- | --- |
| 設定 28-128 | SETTINGS_MAX・_settings_file・load_settings・SETTINGS_PATCH_KEYS(45-64)・_cut_silence_ok・_keymap_ok・patch_settings・merge_settings・replace_settings(約 100 行) | **ytt/settings** | 検査の鍵: `evalDirs`(ed_relink._eval_dirs_ok)・`altEngine`(ed_alt.ALT_ENGINES)・`thumbCrop`(固定の 3 値)・`keymap`・`cutSilence`・`pack*` は純粋。上向きは evalDirs と altEngine だけ → ytt に検査の関数を持つ(evalDirs)か、持ち主が登録する(altEngine) |
| 置換辞書 130-178 | parse_replacements・_bounded・wb_split・apply_replacements(約 50 行・純関数) | **pipeline/transcribe/replace.py** | 読み手: doc_jobs・rerun・ed_misc(A/B)・record_baseline・learn_rules・metric_terms。「学習」からも使う → learn→replace(下向き) |
| 行の対応づけ 181-246+305 | PUNCT_ONLY・_groups・_prep・NOSUB_IN・is_nosub・split_nosub・_prep_main・_norm(約 70 行) | **human/proof/learn.py**(学習も精度も保管も使う核) | `_groups` は dev/eval_alt×4・eval_asr×2・eval_effort×3 が `S._groups` で読む |
| 精度の別集計 249-302 | nosub_stats・is_overlap_group・overlap_orders・overlap_best_counts(約 55 行) | eval/drill/metrics.py | norm_cer・lev_counts を呼ぶ(eval 内) |
| 学習・提案 309-666 | learn_events・learn_groups・_doc_info・learned_candidates・load_feedback・record_feedback・_spans・learn_rules・find_suggestions・suggest_for_doc・auto_learned_replace・load_roster・auto_glossary(約 350 行) | **human/proof/learn.py** | `load_roster` は roster.py へ寄せてよい(serve /api/roster・dev/eval_split)。suggest_for_doc は alt.alt_suggest・ytcap.ytcap_suggest を呼ぶ(human どうし) |
| 精度 659-865 + 基準 869-893 | norm_cer・lev_counts・metric_terms・acc_*・doc_metrics・config_key・all_metrics(約 210 行)・EVAL_BASE・read/record_baseline | **eval/drill/metrics.py** | 読み手: ed_misc(A/B)・dev/eval_asr×9・serve(/api/metrics・/api/eval-baselines)。EVAL_BASE は serve.set_data_dir が差し替える |
| 修正データの書き出し 897-984 + 保管 986-1301 | export_corrections・start_archive・archive_*・dataset_stats(約 400 行) | **eval/tools/dataset.py** | serve から 4 本(/api/export-corrections・/api/archive・/api/dataset)。**画面が保存のたびに /api/archive を自動で呼ぶ**(app.js:516・app-learn.js:593)ので、消すなら画面と e2e も(要確認の物) |
- 依存(`ed_state` 63 refs / 15 名: ApiError×21・atomic_write×9・DATASET_DIR×8・TMP_DIR×5・num×6・FEEDBACK×2 ほか)・`ed_store`(_tids×4・read_transcript×7・tx_path×2)・`ed_alt`(ALT_ENGINES・alt_suggest)・`ed_ytcap`(ytcap_suggest)・`ed_relink._eval_dirs_ok`・`ed_jobs`(extract_audio・split_terms)・`ed_thumb.THUMB_CROPS`(コメントのみ)。KNOWN の組: (learn→state)(learn→relink)。
- 読み手: serve 15・ed_misc 14・doc_jobs 12・ed_relink 3・ed_alt 2・rerun 2・speakers 2・ed_store/ed_thumb/ed_ytcap/ed_evalbatch 各 1・pipeline/spec.py(コメント)・dev(eval_effort 3・eval_asr 2・eval_alt)・tests(test_settings_schema 3・test_thumb_job 3・test_alt・test_llm・test_metrics・test_nosub_metrics・test_roster)。
- テストの差し替え: `S.DATASET_DIR = …`(test_backend:175・test_nosub_metrics:236)・`S.EVAL_DIR`(test_backend:256)・`S.FEEDBACK`/`ed_state.FEEDBACK`(test_alt・test_ytcap・dev/eval_alt)・`S.MAX_LEV_CELLS`(test_metrics 2)。`SETTINGS_PATCH_KEYS` は test_settings_schema が `ed_learn.` で直に読む。

### 1-4 ed_relink.py(1058 行)— 5 つに割れる
`callgraph.py` の節の呼び合い: relink→(evaldir・norm)・norm→(relink・evaldir)・evalorg→(evaldir・relink)・find→relink。**評価用の整理は付け替えを呼ぶが、付け替えは評価用の整理を呼ばない**(判定 `in_eval_dir`/`eval_name_guard` だけ)。
| 節(行) | 中身 | 行き先 |
| --- | --- | --- |
| 付け替え 24-209 | RELINK_*・_remote_drive(30-41)・relink_path・relink_check・_doc_busy・relink_doc・_relink_write | **manage/cases/relink.py**(`_remote_drive` は ytt/fsio へ) |
| 30fps 210-393 | norm_enabled・norm_name・norm_usable・norm_plan・_norm_room(判断 約 80 行)/ norm_swap・norm_run・norm_after_transcribe・norm_start・run_normalize(約 100 行) | RS0-g の決定どおりなら 判断=pipeline/ingest・付け替え=manage/cases。**まず 1 つのまま manage/cases/normalize.py**(違反は同じ 0 件。判断だけ割るのは後でもよい) |
| 探す・窓 394-505 | FIND_*・relink_missing・relink_folder・relink_find・pick_path(12 行) | manage/cases/relink.py(pick_path は app の薄い包み) |
| 評価用の判定 506-566 | EVAL_DIRS_MAX・_eval_dirs_ok・eval_dirs・in_eval_dir・EVAL_NAME_WORD・eval_name_guard(約 60 行) | **ytt/settings**(RS0-f)。`_eval_dirs_ok` は `_remote_drive` を使う |
| 評価用の整理 567-1058 | _eval_walk〜eval_organize・eval_settle・_eval_rename・eval_folders_info・_evalorg_startup(約 490 行)+ `_move`/`_same_drive`(607-635 = ytt/fsio へ。home/intake×2・dev/eval_split×2 も使う) | **eval/drill/folders.py**(RS4 の物。RS3 で割るときに最終の置き場へ) |
- 依存(`ed_state` 93 refs / 14 名: ApiError×34・log×17・norm_path×10・DATA_DIR×6・MEDIA_TYPES×6 ほか)・`ed_store`(30 refs / 10 名)・`ed_jobs`(殻。ACTIVE_STATES・_jobs・_jobs_lock・add_job・set_internal_error・run_job・work_one → 本体は ytt/jobs と doc_jobs)・`ed_learn.load_settings`×3(evalDirs)・`resolve_export.edit_draft`(100)。KNOWN の組: (relink→state)。
- 読み手: serve 14(+ set_hooks の 3 本 = ed_relink.eval_name_guard・in_eval_dir・norm_after_transcribe・serve:788 `_evalorg_startup` の裏スレッド・register("normalize"))・ed_drill 9・ed_evalbatch 7・ed_evalaudio 6・doc_jobs 4(コメント主体)・ed_store 2・ed_alt/ed_learn/ed_ytcap 各 1・manage/cases/txindex(コメント)・dev/eval_split。tests = test_normalize30(13)・test_edit(3)・test_evalbatch(2)・test_autodiar(1)。
- テストの差し替え(test_edit): `ed_relink._same_drive`(2)・`relink_check`(2)・`FIND_MAX_DEPTH`(2)・`_relink_write`(2)・`ed_relink.os.rename/remove`・`ed_relink.tempfile.mkstemp`・`ed_relink.shutil.disk_usage`・`ed_relink._vnorm.normalize`(test_normalize30 7)・test_names の `in_eval_dir`。**`_same_drive` を ytt/fsio へ動かすとこの 2 か所は書き換えが要る**(`ed_relink.os` などの「モジュールを通した差し替え」は、モジュールが別になると当たる先が変わるので、割るとき一番気を付ける所)。

### 1-5 ed_misc.py(484 行)— 5 つに割れる
| 節(行) | 中身 | 行き先 |
| --- | --- | --- |
| A/B 18-157 | MAX_AB_*・validate_abtest・run_abtest・read_eval・list_evals(約 140 行) | eval/drill/abtest.py(JOB_RUNNERS の "abtest"・EVAL_DIR。ChunkModel・norm_cer を使う) |
| JSON 161-165 | `_read_json_file`(= fsio.read_json_or の部分適用)| ytt/fsio を直に使う(ed_store:280・ed_media:133 も読む) |
| マーカー 166-272 | studio_out_dir・transcribed_ranges・_covered・read_marker・marker_videos(約 107 行) | manage/cases/marker.py。`transcribed_ranges` は ed_store.summaries しか使わない → human/proof/batch.py へ置いて marker が読む形が下向き |
| 進行度 276-300 | progress_stats(25 行)| manage/cases(要約の `_prog` を足し合わせるだけ。**RS0-m の「進行度を消す」は別の段**) |
| フォルダ一括 304-381 | MAX_SCAN_FILES・scan_folder・_done_and_active・add_batch・scan_common | **human/proof/batch.py**(validate_job + add_job を呼ぶ画面の一括投入。`_done_and_active` は transcribed_ranges を呼ぶ → 同じ human に置く) |
| 受け渡し 385-479 | _pipeline_error・clip_info・transcript_v1・export_file(約 95 行。pio 経由)| manage/cases/handoff.py |
| runtime_path_dir 482-484 | 3 行 | app(serve が 5 回使う) |
- 依存: `ed_state` 73 refs / 22 名(ApiError×23・EVAL_DIR×8・num×8・norm_path×7・pio×3・SERVER_VERSION×3・MEDIA_TYPES×3 ほか)・`ed_store`(summaries×2・read_transcript×4・edit_keeps_sec・read_edit)・`ed_jobs`(殻)14 名・`ed_learn`(A/B で acc_*・norm_cer・parse/apply_replacements・metric_terms ほか 14)・`pipeline_io`・`worker_client`。KNOWN の組: (misc→state)。(ed_store→ed_misc は `_read_json_file` の 1 本)
- 読み手: serve 17 (`/api/siblings`・clip-info・transcript-v1・marker・transcribed-ranges・evals・eval・progress・scan-folder・transcribe-batch・abtest・export-file)・ed_store 3・ed_media 1・home/accuracy 1(コメント)・pipeline/transcribe/recognize 1(コメント)。tests = test_metrics・test_backend(`S.transcribed_ranges` を 3 回差し替え)・e2e_folder_marker_range。

### 1-6 pipeline_io.py(294 行)/ resolve_export.py(294 行)
- 向きの問題は 1 本だけ: **resolve_export:133 `import pipeline_io`(中で `build_transcript_v1` を呼ぶ)= pipeline→manage**(KNOWN の (resolve_export→pipeline_io))。逆の pipeline_io:30 `import resolve_export`(is_kept・kept_spans・srt_text)は manage→pipeline で正しい。
- 直し方: pipeline_io の**組み立て 5 つ**(`sorted_segments` 123-133・`build_transcript_v1` 136-161・`_media_of` 164-167・`build_cut_plan_v1` 171-181・`wrap_text` 185-189・`build_srt` 192-207 = 約 85 行。依存は ytt の schemas/runtime と resolve_export の is_kept/kept_spans/srt_text だけ)を resolve_export(→ pipeline/pack)へ移し、pipeline_io(→ manage/cases)は `from pipeline.pack import resolve_export` して同じ名前で読めるようにする(`pipeline_io.build_transcript_v1` を ed_misc・テストが呼ぶ)。残りの pipeline_io(clip/v1 の探し方 `find_clip`・`load_clip_file`・`resolve_clip_media`・`save_beside`・.runtime の薄い包み)は ytt/schemas の薄い包みなので manage/cases へそのまま。
- `ed_state.pio()`(150-163)は「pipeline_io が読めなければ None」の遅延ロード(serve の分割で一部だけ差し替えたときの備え)。パッケージの import にすると**不要**になり、doc_jobs の `pio(required=False).find_clip` は `schemas.find_clip_path`+`load_clip_file`(既に ytt)を直に呼べば足りる。`serve.startup_checks` の「pipeline_io.py / resolve_export.py が見つかりません」(serve:702)も意味を失う(**動きが変わる小さな所**)。
- 読み手: pipeline_io = serve 3(startup_checks・prepare の write_runtime)・ed_misc 1・ed_state(pio)・resolve_export・ytt/runtime,schemas(コメント)・tests 12 ファイル(test_backend・test_edit・test_metrics・test_resolve_export・e2e の 6 本の「写す一覧」・e2e_pipeline・test_resolve_pack_contract)。resolve_export = ed_store 7(edit_draft・edit_preview・pack_instructions・ResolveExportError。内側の import)・ed_relink 3・serve 4(create_package)・pipeline_io 4・tests(test_resolve_export 17・test_resolve_pack_contract 16・test_edit 4・test_ovdraft)。
- 差し替え: `resolve_export._load_pack`(test_resolve_export)・`pipeline_io.remove_runtime`・`iso_now`・`load_clip_file`(home/studio 側のテスト)。`dev/tests/test_resolve_pack_contract.py:48-58` は `ROOT/"editor"` を sys.path に足して `import pipeline_io`・`import resolve_export` を裸で読む → 付け替えが要る(単独で流す決まり)。

### 1-7 ed_media.py(154 行)/ ed_thumb.py(87 行)/ thumb_ideas.py(395 行)
- ed_media・ed_thumb は FILES で app。**動かさない**(ed_state の読みを ytt に付け替えるだけ。ed_media は ed_misc._read_json_file と ed_store.probe_media を読む)。ed_thumb は `ed_learn.SETTINGS_PATCH_KEYS`(コメント)と `thumb_ideas`(内側の import)。
- thumb_ideas は ytt(datadir・tools・colors)だけを読む単独の部品で、違反なし。human/cut へ動かすなら `REPO = dirname(HERE)`(src の見つけ方 395 行の先頭)が 1 段深くなる・CLI の使い方(`python src/editor/thumb_ideas.py`)の文書(AGENTS・README・plan/thumb-ideas.md)を直す、が要る。**急がない**。

### 1-8 ed_state.py(370 行)— 痩せさせる対象
- 状態を持つ名前(RS3 で ytt へ): パス(DATA_DIR・TX_DIR・TMP_DIR・DATASET_DIR・EVAL_DIR・SETTINGS・FEEDBACK・MARKER_DATA・STUDIO_DATA 34-43)・ROOT・SERVER_VERSION・外の道具(find_ffmpeg 222・ffmpeg_info 227・media_duration 246・check_source 255)・GPU と部品の有無(nvidia_gpu 269・has_faster_whisper 286・worker_python 295・worker_has 305・gpu_ready 330・_probe_gpu 347)・valid_model 66・pio 150・worker_fake 362。
- app に残す: APP_ID・INDEX・APP_JS・UI_KIT_JS・PAGE_JS・PORT・ALLOWED_HOSTS・BASE_PATH・MAX_BODY・MAX_QUEUE・LOG_FILE/CRASH_FILE/RUN_MARK・setup_logging・write_mark・check_previous_run・backend_name(358。serve の selector と画面の表示用)。
- ytt の別名(ApiError・atomic_write・num・now_ms・plain_int・file_stamp・unlink_quiet・log・norm_path・union_spans・read_schema_json・add_warning・fmt_hms・env_off・TID_RE・MAX_TEXT・OTHER_SPK_*・blank_draft_row・ROW_DRAFT_KINDS・rss_mb・_mem)は**状態を持たない**。ファイルを動かすたびに、その部品が `from ytt import errors, fsio, schemas` と直に読む形へ(別名は最後に消す)。
- 参照: ed_state を読む非 app のファイル(KNOWN の「→ed_state」)= ed_alt 33・ed_learn 63・ed_store 108・ed_ytcap 55・ed_misc 73・ed_relink 93・ed_drill 22・ed_evalaudio 18・ed_evalbatch 70 refs(合計 約 535)。serve 149・ed_media 13・ed_thumb 6 は app。ほかは dev/eval_alt(`ed_state.FEEDBACK = …` を直に代入 = 持ち主を動かすと届かなくなる)・dev/tests/test_eval_effort・テスト 8 本(test_alt・test_edit・test_fill・test_llm・test_retime・test_thumb_job・test_ytcap)。

### 1-9 付録: RS4 のファイルとの接点
ed_drill(426 行)・ed_evalbatch(881)・ed_evalaudio(351)は FILES で eval。RS3 に関係するのは (a) 3 つとも `ed_state` を読む(ed_drill 22・ed_evalbatch 70・ed_evalaudio 18 refs。名前はほぼ ytt の別名と パス)= RS3 の「ytt へ付け替え」で一緒に消える (b) ed_drill が ed_relink の評価用の物(EVAL_STAGING・_EVAL_MEMBER_RE・_eval_members・_norm_member・eval_dirs・in_eval_dir)を 9 回読む (c) ed_evalaudio:19・345 の `import serve`(単独実行の入口)= KNOWN の (evalaudio→serve)。ed_evalaudio は計画 9 節で「消す(決定済み)」。

---

## 2. 移したあとの向き(上向きの読みと口の案)・KNOWN の見込み

### 2-1 移した先ごとの「上の層を読む所」と口
| 移し先 | 上向きの読み(今) | 口の案(RS2 と同じ作法) |
| --- | --- | --- |
| human/proof/store.py | ① `ed_drill.drill_doc_summary`(246)→ eval ② `ed_relink.in_eval_dir`(144・488)→ manage ③ `ed_misc._read_json_file`(280)→ manage ④ `txindex`(332・817)→ manage | ① **登録の口**: `store.set_summary_part(name, fn)`(serve が `lambda d: ed_drill.drill_doc_summary(d)` を登録。要約の `_part` に足す。RS0-m「進行度・ドリル・付き物は登録の口で各層が足す」)② **ytt/settings に判定を降ろす**(RS0-f)③ fsio.read_json_or を直に ④ **ファイルを境目に**一覧を manage/cases/doclist.py へ(store は txindex を知らなくなる) |
| manage/cases/doclist.py | なし(store・txindex・ytt/studiodata を読む = 下向き) | — |
| human/proof/alt.py | ① `ed_jobs.transcribe_fake`(eval)・`backend_name()` 5 か所 ② in_eval_dir ③ `learn.load_settings` | ① `backend.select().name`+ `Backend.alt_rows` の口(本体は eval/fake/fake_asr)② ytt/settings ③ ytt/settings |
| human/proof/ytcap.py | in_eval_dir のみ | ytt/settings |
| human/proof/learn.py(学習・提案) | `_eval_dirs_ok`(設定の検査)・`ed_alt.ALT_ENGINES` | 検査は ytt/settings の**鍵の登録**(alt が自分の `altEngine` の検査を登録。evalDirs の検査は ytt にある) |
| ytt/settings(+ytt/fsio) | evalDirs の検査が `_remote_drive`(ctypes)を使う | fsio に `_remote_drive`・`_move`・`_same_drive` を降ろす |
| manage/cases/relink.py・normalize.py | なし(store=human・ytt/jobs・resolve_export=pipeline を下向きに読む) | doc_jobs が読む 3 本(eval_guard・in_eval_dir・norm_after)は今の set_hooks のまま(human→manage は禁止) |
| eval/drill/folders.py・metrics.py・abtest.py・eval/tools/dataset.py | なし(eval は全部読める) | ed_drill・ed_evalbatch・ed_evalaudio の読みを `from . import folders` に |
| pipeline/pack/resolve_export.py | なし(組み立てを受けて pipeline_io への逆向きが消える) | — |
| pipeline/transcribe/replace.py | なし(純関数) | — |

### 2-2 KNOWN の 49 件のうち編集の分は 18 件(残り 31 = home 22・studio 9)
| # | 組 | 消える段 |
| --- | --- | --- |
| 1 | ed_store → ed_relink | E4(判定を ytt/settings へ) |
| 2 | ed_alt → ed_relink | E4 |
| 3 | ed_ytcap → ed_relink | E4 |
| 4 | ed_learn → ed_relink | E4 |
| 5 | resolve_export → pipeline_io | E5b(組み立てを pipeline/pack へ) |
| 6 | ed_store → ed_drill | E5a(要約の口) |
| 7 | ed_store → ed_misc | E5a(fsio) |
| 8 | ed_store → txindex | E5a(一覧を manage へ) |
| 9 | ed_store → ed_state | E5a |
| 10 | ed_learn → ed_state | E5c |
| 11 | ed_alt → ed_state | E6 |
| 12 | ed_ytcap → ed_state | E6 |
| 13 | ed_misc → ed_state | E7 |
| 14 | ed_relink → ed_state | E7 |
| 15 | ed_drill → ed_state | E7(の終わり。RS4 と重なる) |
| 16 | ed_evalbatch → ed_state | E7(同上) |
| 17 | ed_evalaudio → ed_state | E7(同上) |
| 18 | ed_evalaudio → serve | RS4(ed_evalaudio を消す。決定済み) |
- 見込み: **49 → 31**(18 件)。移した先に**新しい違反は出ない**はず(上の表の口を作る前提)。残る 31 は home(autorun・live*・intake・prefs…)と studio(common・handoff・store)= RS3 の home・studio の分。
- 注意: 「→ed_state」の組は、そのファイルが ed_state の名前を**1 つも読まなくなって**初めて消える。ytt の別名もすべて直に読む形に付け替える必要がある(ファイルごとに 1 回の機械的な付け替え)。

---

## 3. txenv を ytt に置き換える

### 3-1 いまの txenv の鍵(17 個。`txenv.py:17-19`)・返している物・読み手・置き換え先
| 鍵 | ed_state の中身 | 読み手(非テスト) | 置き換え先(案) | テストの差し替え |
| --- | --- | --- | --- | --- |
| DATA_DIR | `ed_state.py:34`(env `TRANSCRIBE_DATA_DIR` か ROOT)+ serve.set_data_dir(716) | speakers・diarize・tx_engines・worker_client×2 | **ytt/workdata.py の変数** | `S.DATA_DIR =`(test_edit 5・test_whispercpp・test_names) |
| TX_DIR | `ed_state.py:35` | diarize・llm・recognize・records×2 | 同 | `S.TX_DIR =`(14 か所。多くは TX_DIR・TMP_DIR・SETTINGS を同時に代入) |
| TMP_DIR | `ed_state.py:39` | txenv 経由では読まれない(ed_* が 13 回読む) | 同 | `S.TMP_DIR =` |
| ROOT | `ed_state.py:27`(serve.py のフォルダ) | worker_client(ワーカーの cwd) | workdata.ROOT(app が入れる。**既定を layout にしない** = e2e は serve.py を一時フォルダに写すので ROOT が実際のフォルダと違う) | 無し(`S.ROOT` を test_backend の valid_model が読む) |
| ROSTER | `ed_state.py:36`(editor/hololive-roster.json) | doc_jobs・fill×2・llm・records・roster×2 | **roster.py の変数 `ROSTER`**(roster は `_ED_MODULES` にある。JSON は動かさない) | `S.ROSTER =`(test_backend・test_llm・test_roster 6) |
| SERVER_VERSION | serve が代入 | postproc.post_record | workdata.SERVER_VERSION(serve が入れる) | 無し |
| find_ffmpeg | `_tools.find_tool("ffmpeg","TRANSCRIBE_FFMPEG")` | recognize | **ytt/tools** | `patch(S,"find_ffmpeg")` 3(test_backend) |
| worker_python | sys.executable(Mac/Linux は .venv) | worker_client | **worker_client** | 無し |
| worker_fake | env == "worker-fake" | speakers・diarize×2・worker_client×2 | **txbase.worker_fake()**(env_off の隣) | 無し(worker.py は自分の `_fake_mode` を登録している → 同じ env 読みに) |
| gpu_ready | 別プロセスで 1 回調べる(`ed_state.py:330`)。ワーカーの中では `_gpu_ready_local` | worker_client | **worker_client.gpu_ready()**(IN_WORKER で分ける今の形をそのまま) | `patch.object(S.ed_state, "gpu_ready")`(dev/tests/test_eval_asr:210。持ち主を動かすと `S` へ直す) |
| has_faster_whisper | worker_has("faster_whisper") | worker_client | worker_client | 無し |
| media_duration | ffmpeg_info→duration_in | doc_jobs×2・speakers×2・recognize | **ytt/tools** | `patch(S,"media_duration")` 4 |
| check_source | `MEDIA_TYPES` で拡張子を見る(255) | doc_jobs×3・rerun×2・speakers×4 | **ytt/tools**(MEDIA_TYPES は ytt/schemas) | `patch(S,"check_source")` 13 |
| studio_stream | ed_store.studio_stream(スタジオ data.json) | roster×2 | **ytt/studiodata.py** | `S.STUDIO_DATA =`(test_backend:327・test_roster:147) |
| valid_model | MODEL_RE+ROOT 相対の実在検査(66) | doc_jobs×3 | **pipeline/transcribe/txbase**(ROOT は workdata) | `patch(S,"valid_model")` 1(test_names) |
| pio | pipeline_io の遅延ロード | doc_jobs×1 | **廃止**: `schemas.find_clip_path`+`load_clip_file` を直に(1-6) | `S.pio` 1(test_names) |
| worker_has | ワーカーの Python のモジュールの有無 | diarize | worker_client | 無し |
→ 読み手は**非テスト 約 50 か所・13 ファイル**(worker_client 16 refs・doc_jobs 12・speakers 9・diarize 8・llm 6・roster 5・records 5・recognize 5・fill 5・rerun 4・postproc 4・tx_engines 3・txbase 1)。テストで txenv を直に触る物: test_txenv(28)・test_diarize(12)・test_fill_llm(11)・test_recognize(9)・test_worker_client(8)・test_txroster(8)・test_postproc(8)・test_txrecords(6)・test_names(6)。

### 3-2 ytt/settings.py にあるもの・足りないもの
- あるのは `SettingsFile`(設定ファイルの読み書き・節・鍵・原子的な書き込み・壊れたファイルの退避)と `SettingsError`/`SettingsTooLarge`/`section_name_ok`/`retire_broken` だけ(`src/ytt/settings.py:1-166`)。**パスも「今の値」も無い**。ホームの prefs・スタジオの store・編集の ed_learn が同じ部品を使う共有物。
- ytt/datadir.py には `register(tool, path)`・`registered(tool)`・`resolve`(他のツールが編集の作業データの場所を引く)がある。serve.set_data_dir が既に `register("transcribe", DATA_DIR)` している(serve:729)。
- 足りないのは (a) 編集のパス群の「今の値」と切り替え (b) 設定ファイルの編集用の読み書き(load/patch/merge/replace)と鍵の検査の表(ed_learn:28-128)(c) 評価用の判定。

### 3-3 置き換えた形の案
1. **新しい `ytt/workdata.py`** に「編集の作業データの今の値」を**モジュールの変数**として持つ(ed_state:34-44 をそのまま移す): `ROOT・DATA_DIR・TX_DIR・TMP_DIR・DATASET_DIR・EVAL_DIR・EVAL_BASE・SETTINGS・FEEDBACK・MARKER_DATA・STUDIO_DATA・SERVER_VERSION` と `configure(root)`(app が import のときに既定を入れる = 今の ed_state の読み込み時の既定と同じ)・`set_data_dir(d)`(serve.set_data_dir:716-722 の本体。ログのパスと worker.log は app の物なので serve に残す)。
   - **なぜ lambda でなく変数か**: `S.TX_DIR = …` は `modfwd` が「その名前を持つ部品」へ転送する。持ち主が workdata なら代入も `mock.patch.object(S, …)` もそのまま届き、読む側が `workdata.TX_DIR` と呼ぶたびに読めば十分(今の txenv の `__getattr__` と同じ効き方)。**ed_state に同じ名前を残してはいけない**(先に勝って差し替えが別名に当たる = RS2 の決まり)。
   - workdata を serve の `_ED_MODULES` に足す。重なりは `test_names.test_no_duplicate_names_across_parts` が見る。
2. **ytt/settings.py に足す**: `load_settings()`・`patch_settings`・`merge_settings`・`replace_settings`(ed_learn:28-128 の本体)・`SETTINGS_PATCH_KEYS`(鍵 → 検査の表)と **`register_patch_key(name, check)`**(持ち主が自分の鍵の検査を足す口。`altEngine` は alt が登録)・`eval_dirs()`・`in_eval_dir(path)`・`eval_name_guard(path, is_eval)`・`_eval_dirs_ok`(RS0-f)。同じ部品を使う ホーム(prefs)・スタジオ(store)の分は RS3 の home・studio の担当と**同じ口にそろえる**(先に口の形だけ決める)。
3. 動きのある鍵は持ち主へ(表のとおり): ytt/tools(find_ffmpeg・media_duration・check_source・probe_media・ffmpeg_info・duration_in)・worker_client(gpu_ready・has_faster_whisper・worker_python・worker_has・nvidia_gpu)・txbase(worker_fake・valid_model)・ytt/studiodata(studio_stream・studio_videos)・roster(ROSTER)。
4. `serve.py` の `_txenv.register(...)`(164-173)と `check()` を消す。ワーカー(`worker.py:166-167`)は workdata.DATA_DIR を env から入れ、`worker_fake` は txbase.worker_fake を読む。

### 3-4 テストの差し替えはどう届くか
- `S.名前 = …`・`patch.object(S, "名前")`: `_ED_MODULES` に持ち主(workdata・tools を載せる側・worker_client・txbase・roster・studiodata)が並んでいれば、modfwd が持ち主へ転送する(`ytt/modfwd.py`)。今テストが当てている名前(TX_DIR・TMP_DIR・SETTINGS・DATA_DIR・ROSTER・STUDIO_DATA・DATASET_DIR・EVAL_DIR・FEEDBACK・check_source・media_duration・find_ffmpeg・backend_name・valid_model・pio・gpu_ready)の**読み手が全員「持ち主.名前」を呼ぶたびに読む**ことが条件。
- 壊れる書き方(書き換えが要る。`ed_state` を直に当てる物): `patch.object(S.ed_state, "check_source"/"media_duration"/"backend_name")`(test_smooth:151-175)・`S.ed_state.gpu_ready`/`backend_name`/`STUDIO_DATA`(dev/tests/test_eval_asr:168・210-211)・`mock.patch.object(ed_state, "FEEDBACK"/"ROSTER")`(test_alt:109・test_ytcap:160・test_llm:134・177)・`ed_state.FEEDBACK = …`(dev/eval_alt:109-114)。計 約 10 行。`backend_name` は ed_state(app)に残すので test_smooth・test_eval_asr のその行は変わらない。
- txenv を直に触るテスト 9 本(上)は、`txenv.register(TX_DIR=lambda: tmp)` を `workdata.TX_DIR = tmp`(保存・戻し)に変える(約 100 行)。`test_txenv`(28 refs)と `test_names.TestTxenvRegistered` は「持ち主が S の差し替えに従う」テストに置き換える。
- 失敗の仕方が変わる点: txenv は登録が無いと RuntimeError だったが、変数だと未設定の既定のまま動いてしまう。既定は env か None(None なら os.path.join で型エラー = 気づける)にし、**ROOT の既定を repo の editor にしない**(一時フォルダに写した serve が本物のフォルダに書く事故を防ぐ)。

### 3-5 txenv を消すのは RS3 か RS5 か → **RS3 の最初(E3)**を勧める
- 移したファイルは `ed_state` を読めない。txenv を RS5 まで残すと、移す先が txenv の鍵を増やし(DATASET_DIR・EVAL_DIR・SETTINGS・FEEDBACK・MARKER_DATA…)、ed_state の値を lambda で返す二重の口が RS5 まで続く。最終の読み先(ytt/workdata など)を先に作れば、各ファイルを動かす 1 回で終わる。
- 安全策: ① 名前の群ごとに 1 コミット(パス → 動きのある関数 → txenv 本体の削除)で、毎回 編集の単体一式 + pipeline/transcribe のテスト + human/proof を流す ② この段では**ファイルを動かさない**(読み先の付け替えだけ)③ 1 つの名前の持ち主を 2 つにしない(ed_state から消す)。
- 残す物: 殻(`ed_*.py`)は RS5 で消す(RS2 と同じ)。

---

## 4. 画面・API(serve の GET_API・POST_API)から見た影響

- **URL・API の形は変えない**: serve の表は `ed_xxx.名前` を `lambda` の中で呼ぶ形。持ち主が変わるだけ(serve 自身の参照は本物の持ち主へ付け替える = RS2-8b の作法)。画面(`app*.js`・`index.html`)は触らない。
- ルートと持ち主の変わり方:
  - 文書: `/api/transcripts`(→ manage/cases/doclist)・`/api/transcript`(GET/PUT/DELETE)・`/api/history`・`/api/restore`・`/api/open-video`・`/api/doc-for`・`/api/effort`・`/api/doc-diarnum`・`/api/edit`・`/api/edit/draft`・`/api/edit/pack`・`/api/edit/preview` → human/proof/store(edit 部分も store)。`/api/edit/pack-readme` → doclist。
  - 校正の補助: `/api/suggest`・`/api/learned`・`/api/suggest/feedback`・`/api/roster` → human/proof/learn(roster は roster.py)・`/api/alt`・`/api/ytcap` → alt・ytcap・`/api/retime` → retime。
  - 設定: `PUT /api/settings`・`POST /api/settings/patch` → ytt/settings(serve は薄く呼ぶだけ)。
  - 精度と保管: `/api/metrics`・`/api/eval-baseline(s)` → eval/drill/metrics・`/api/dataset`・`/api/archive`・`/api/export-corrections` → eval/tools/dataset・`/api/abtest`・`/api/evals`・`/api/eval` → eval/drill/abtest。
  - 付け替え・評価用フォルダ: `/api/relink*`・`/api/pick` → manage/cases(pick は app)・`/api/eval-folders*` → eval/drill/folders。
  - マーカーと一括: `/api/marker`・`/api/transcribed-ranges`(→ human/proof/batch の transcribed_ranges)・`/api/scan-folder`・`/api/transcribe-batch` → human/proof/batch・`/api/clip-info`・`/api/transcript-v1`・`/api/export-file` → manage/cases/handoff・`/api/siblings` → manage/cases/pipeline_io。
  - `/api/progress` は残す(要約の `_prog` を足すだけ。消すのは別)。
  - Resolve のzip(`_resolve_package`)は resolve_export.create_package のまま(pipeline/pack の物)。
- 小さな動きの変化: ① `serve.startup_checks` の「pipeline_io.py / resolve_export.py が見つかりません」(serve:702)と `ed_state.pio` の `missing_module` エラーが意味を失う(パッケージの import になるため。画面に出る警告の文が 1 つ減る)② 文書の削除 `Handler._delete`(serve:613-638)は `ed_store._edit_cache.pop` など私有の状態に触れている → store に `delete_doc(tid)` を作る(RS0-m の「削除は名前の規則」)と配線が薄くなる(任意)。
- **e2e の「写す一覧」**: 9 か所の文字列の一覧に `"hololive-roster.json"・"pipeline_io.py"・"resolve_export.py"` が書いてある — `e2e_eval_set.py:44`・`e2e_folder_marker_range.py:44`・`e2e_proofread_accuracy.py:45`・`e2e_proofread_keys.py:50`・`e2e_row_editing.py:43`・`e2e_ui_handoff.py:67`・`test_backend.py:720`・`test_metrics.py:578`・`dev/tests/e2e_pipeline.py:92`。ファイルを動かすと `shutil.copy` が FileNotFoundError になるので**消す**(動かさない名簿の JSON は残す)。`ed_*.py` と `app-*.js` は glob で写す(殻もそのまま写る)。層のコードは `YTT_CORE_DIR`(= src)と `layout.copy_shared_code`(SHARED_CODE_DIRS に human・manage・eval・pipeline・ytt があり、新しい層のファイルは自動で写る)で見つかる。`e2e_edit_common.copy_tool` はフォルダの直下を拡張子を見ずに全部写す(コードの写し忘れは起きない)。
- そのほか: `dev/tests/test_resolve_pack_contract.py:48-58` は `ROOT/"editor"` を sys.path に足して `import pipeline_io`/`resolve_export` を裸で読む → `from pipeline.pack import resolve_export` と `manage.cases` に直す(単独で流す)。`dev/tests/e2e_datadir.py:51` は editor フォルダを丸ごと写すので変更不要。`dev/layer_map.py` の FILES は動かしたファイルの行を消し、殻の行(層 human・manage など「転送(RS5 で消す)」)を足す。`src/editor/tests/data_ed_*_names.txt`(RS2 の旧い名前の一覧)にならい、**動かす前に旧い名前を ed_store・ed_learn・ed_relink・ed_misc ごとに控えておく**(`test_names` に「旧い名前が S と殻で読める」検査を足すため)。
- 起動中の入口は古いコードのまま動く(各段のあと「すべて終了 → start.bat」)。home の `mount.py` は editor フォルダの `.py` 名が他のツールの名前と重ならないか見るので、editor のフォルダから名前が減る分には問題ない(殻は ed_ の名前で一意)。

---

## 5. 段の案(コミットの粒度・並列・テスト・違反の減り方・所要)

前提の整理:
- 全体に触る段(状態の持ち主を変える)は**直列で最初に**。ファイルを動かす段は殻(転送)を作れば互いの import を壊さず**並列にできる**(RS2 の手順: 別の作業フォルダ・取り込みは cherry-pick・「移動だけ」と「付け替え」を別コミット・並列の後から入る側が rebase)。
- 計画の「RS3 = 1 日」は home・スタジオ・編集を全部含んでいるが、**編集の分だけで AI の作業 約 1.5〜2 日**(下の合計)。RS3 の見積もりは延ばすべき。

| 段 | 中身 | 主に触る物 | 通すテスト(py -3.10・リポジトリ直下) | KNOWN | 目安 | 担当(モデル) |
| --- | --- | --- | --- | --- | --- | --- |
| **E0** 準備 | 旧い名前を控える(ed_store・ed_learn・ed_relink・ed_misc の `data_*_names.txt`)。ytt/settings の鍵の登録の口の形を home・studio の担当と合わせる | 新ファイルのみ | — | 49 | 0.5h | まとめ役 |
| **E1** 置き場所 | `ytt/workdata.py` を作り、パック群・ROOT・SERVER_VERSION の持ち主にする。ed_state からそれらを**消す**(別名は残さない)。serve.set_data_dir・prepare・`_ED_MODULES`・読み手の付け替え(src 約 120 refs(serve を除く非テスト)+ 直に `ed_state.X` を読むテスト 約 10) | ed_state・serve・全 ed_*(読むだけ)・doc_jobs/rerun/speakers・pipeline/transcribe/*・dev/eval_alt | 編集の単体一式(test_metrics ほか)・pipeline/transcribe/tests のファイル・human/proof/tests・test_names・`test_layering`・lint・e2e_ui_mounted・e2e_edit_tabs・e2e_drill | 49 | 2.5h | Opus |
| **E2** 動きのある物 | check_source・media_duration・find_ffmpeg・probe_media → ytt/tools / GPU・部品の有無 → worker_client / worker_fake・valid_model → txbase / studio_* → ytt/studiodata / pio 廃止(schemas を直に) / ROSTER → roster | ed_state・serve・ed_store(studio 部分)・ed_alt・ed_misc・doc_jobs・worker_client | 同上 + test_worker・e2e_edit_voices | 49 | 2h | Opus |
| **E3** txenv を消す | `txenv.X` → 持ち主の読み。worker.py の登録を消す。txenv.py・test_txenv・serve の register を削除。9 本のテストの set-up を `workdata.X = …` に | pipeline/transcribe/*・human/proof/*・serve・テスト 9 本 | 同上(pipeline/transcribe の全ファイル・test_worker・e2e_ui_mounted・e2e_edit_voices) | 49 | 1.5h | Opus か Sonnet(機械的) |
| **E4** 設定と評価用の判定 | ed_learn の設定(28-128)と ed_relink の評価用の判定(506-566)・`_remote_drive`/`_move`/`_same_drive` を ytt へ。鍵の登録の口(altEngine は alt が登録)。殻 ed_learn/ed_relink に旧い名前を転送 | ed_learn・ed_relink・ed_store・ed_alt・ed_ytcap・serve・ytt/settings・ytt/fsio・test_edit の差し替え 3 行 | 編集の単体一式・test_settings_schema・test_edit・`test_layering`・lint・e2e_eval_set・e2e_proofread_accuracy | **→ 45**(組 1〜4) | 2h | Opus |
| (並列の波 1: E5a・E5b・E5c は触るファイルが重ならない。E5b は小さいので先に渡して E5a の邪魔にならないよう殻で受ける) |
| **E5a** ed_store | human/proof/store.py(移動だけのコミット → 付け替え)・manage/cases/doclist.py・要約の口 `set_summary_part`・`_read_json_file` を fsio へ・殻 ed_store・serve の付け替え | ed_store・serve(27 refs)・ed_drill(口の登録だけ)・テスト import 8 本(殻で変更不要) | 編集の単体一式・e2e_edit_tabs/cut/pack・e2e_ui_mounted・e2e_proofread_accuracy・e2e_row_editing・e2e_drill | **→ 41**(組 6・7・8・9) | 3h | Opus |
| **E5b** pack の受け渡し | pipeline_io の組み立て 85 行 → resolve_export → pipeline/pack。pipeline_io → manage/cases。殻 2 つ・9 つの「写す一覧」・contract test・startup_checks | resolve_export・pipeline_io・serve(4)・e2e の 9 本 | test_resolve_export・`test_resolve_pack_contract`(**単独**)・src/pipeline/pack/tests・e2e_edit_pack・e2e_pipeline | **→ 40**(組 5) | 1.5h | Sonnet |
| **E5c** ed_learn の残り | 置換辞書 → pipeline/transcribe/replace.py・学習と提案 → human/proof/learn.py・精度/基準 → eval/drill/metrics.py・保管 → eval/tools/dataset.py。殻 ed_learn。EVAL_BASE の差し替え(set_data_dir) | ed_learn・serve(15)・ed_misc(A/B が読む)・dev/eval_*(`S.` 経由なので変更なし)・test_nosub_metrics・test_metrics | 編集の単体一式・test_nosub_metrics・test_settings_schema・dev/tests の test_eval_alt/asr/effort・e2e_proofread_accuracy・e2e_eval_set・e2e_alt・e2e_fill | **→ 39**(組 10) | 3h | Opus |
| (並列の波 2: E5a が入ってから。互いに重ならない) |
| **E6** 補助 | alt・ytcap・retime → human/proof(`from . import store`)。`backend.select().name` と `Backend.alt_rows`。殻 3 つ。test の `ed_state.FEEDBACK` 差し替えを持ち主へ | ed_alt・ed_ytcap・ed_retime・fake_asr・backend・test_alt・test_ytcap | test_alt・test_ytcap・test_retime・e2e_alt・e2e_fill・test_metrics | **→ 37**(組 11・12) | 2h | Sonnet |
| **E7** ed_relink と ed_misc | 付け替え+30fps → manage/cases・評価用の整理 → eval/drill/folders.py・A/B → eval/drill/abtest.py・マーカー/受け渡し → manage/cases・フォルダ一括 → human/proof/batch.py。殻 2 つ。ed_drill・ed_evalbatch・ed_evalaudio の `ed_state` 読みを外す | ed_relink・ed_misc・serve(14+17)・ed_drill/evalbatch/evalaudio(import だけ)・test_edit・test_normalize30 | test_edit・test_normalize30・test_evalbatch・test_evalaudio・test_autodiar・e2e_folder_marker_range・e2e_eval_set・e2e_edit_tabs(30fps)・e2e_drill | **→ 31 + 1** | 4h | Opus |
| **E8** まとめ | layer_map(FILES・KNOWN_MAX)・AGENTS.md の表・src/editor/AGENTS.md の構成・plan/role-restructure.md・data.js・decisions 3-25・WORKLOG・HANDOVER。全体のテスト(サブエージェントが止まってから)と e2e 一式(1 本ずつ) | 文書 | 単体全部・lint 0・test_mount(単独)・契約(単独)・e2e 全部(編集 14 本・pipeline・datadir・autorun・portal・keymap・live) | 31 | 2〜3h | まとめ役 + Sonnet(文書) |
- 合計: 直列で AI の作業 約 24〜27 時間 ≈ 3 日分。E5a/b/c の並列・E6/E7 の並列で**壁時計 約 1.5〜2 日**。
- 取り込み: RS2 の手順どおり(古い base から始まるので最初に `git merge --ff-only main`・取り込みは cherry-pick・「移動だけ」と「付け替え・転送」のコミットを分ける・e2e はまとめ役が 1 本ずつ・最後の一式はサブエージェントが止まってから)。殻は `ed_jobs.py` の形(`modfwd` の転送。持つ名前は `_MOVED`・`_add_moved` だけ)。

### RS3 と RS4 の順番と分担の案
共有するファイル: **ed_learn・ed_relink・ed_misc**(3 つとも人の部分と eval の部分が同居)と、ed_state を読む ed_drill・ed_evalbatch・ed_evalaudio。分割を 2 回に分けると同じファイルを 2 回割ることになる。
- **案 A(勧める)**: E0〜E4 は RS3 が先に済ませ(RS4 は待つ or dev/eval_* の移動など独立の物から)、**3 つの分割は RS3 が最終の置き場(eval/ を含む)まで運ぶ**。RS4 は (1) ed_drill・ed_evalbatch の丸ごとの移動(relative import に)(2) ed_evalaudio の削除(決定済み。裏スレッド・`/api/eval-audio`・test_evalaudio)(3) `home/accuracy.py`・`live_report.py`・`dev/eval_*.py`・`_evalcommon`・`demo_env` の eval/tools への移動 (4) serve.prepare の評価用の裏スレッド 3 本を登録の口に、を担当 = 約半日。(1) は E7 のあと(ed_drill が folders.py を読むため)。
- 案 B: 並列の別セッション。E1〜E4 は共有なので片方が先に済ませる必要がある。そのあと RS3 = store/alt/ytcap/pack、RS4 = ed_learn/ed_relink/ed_misc の 3 分割+eval 部品。ただし 3 分割は「人の部分を manage/human へ出す」ことでもあるので、片方だけでは完結しない(E4・E5c・E7 が RS4 側に寄る)。
- 担当表(AGENTS.md)の注意: 編集・home・studio・ytt は同じ担当(Claude)。`ytt/settings` の口は home・studio の RS3 と同じ設計にそろえる。

---

## 6. 要判断(ユーザーに確かめる事と、仮で決めるならどちらか)

| # | 事 | 仮 | 理由(1 行) |
| --- | --- | --- | --- |
| 1 | txenv の置き換え先の**入れ物の名前**: 計画の文言どおり `ytt/settings` に置くか、新しい `ytt/workdata.py` に置くか | `ytt/workdata.py` 新設(settings には設定ファイルの読み書き・鍵の検査・評価用の判定) | settings.py はホーム・スタジオも読む共有の部品で、書き換わる大域の値を持たせると modfwd の持ち主が曖昧になり、役割が混ざる |
| 2 | ed_learn・ed_relink・ed_misc の**分割を RS3 が eval/ まで運ぶ**か、人の部分だけ割って eval 部分は RS4 に残すか | RS3 が最終の置き場まで運ぶ(案 A) | 同じファイルを 2 回割らない・担当が重ならない |
| 3 | 計画 9 節で「要確認」の削除候補(修正データの書き出し・データの保管 `dataset/`・設定の比較 A/B)と、RS0-m の「進行度を消す」を RS3 でやるか | RS3 は**移すだけ**(消さない)。進行度の削除は RS3 のあとの別の段 | /api/archive は画面が保存のたびに自動で呼ぶ(app.js:516・app-learn.js:593)・進行度は画面の `#goalCard`・e2e 3 本が読む = 消すと画面と e2e の変更が要り、層の整理と混ぜると落ちた原因が分からなくなる |
| 4 | 殻(転送のモジュール)の方針: 動かしたファイルごとに RS2 と同じ殻を置き RS5 で消す | そうする | 並列の取り込みで他のファイルの import を壊さない・テスト約 20 本の import を一度に直さない |
| 5 | ed_store の edit.json 部分を human/cut に割るか | 今は割らず store に同居 | apply_edit_cuts が文書の書き込みのたびに呼ばれ、store↔edit の相互の呼びが 12 本ある。割るのは UI の再考のとき |
| 6 | 名簿の JSON(`src/editor/hololive-roster.json`)を pipeline/transcribe へ動かすか | 動かさない(RS5) | 参照が dev/eval_split・test_roster・test_backend の valid_model のテスト・e2e の一覧 9 本と文書に散り、違反の解消に効かない |
| 7 | 動きが変わる小さな所: ① `pio()` の「部品が見つからない」エラーと startup_checks の該当の警告を廃止 ② ワーカーの cwd(今は editor のフォルダ = `ROOT`)と `valid_model` の相対パス検査は変えない ③ `ed_state._probe_gpu` のバグ(常に偽)は移すときも直さない(別の札) | ①廃止 ②③そのまま | ①パッケージの import で起きなくなる ②モデル名の検査の前提を動かさない ③AMD の PC では実害なし・動きの変更を移動と混ぜない |
| 8 | 計画 8 節の RS3 の見積もり(1 日)を、編集の分だけで 1.5〜2 日に直す | 直す | 上の合計(直列 24〜27h)。home・スタジオの分は別に要る |

### 気づき(直していない)
- `.claude/worktrees/agent-*` に 4 つの古い git worktree が残っている(`git worktree list`)。grep に古い複製が混ざる・`git worktree` の整理(clean_up_worktrees)の候補。
- `dev/eval_alt.py:109-114` は `ed_state.FEEDBACK = …` を**直に代入**している(`S` 経由ではない)。FEEDBACK の持ち主を動かすと黙って効かなくなる → E1 で `S.FEEDBACK` か持ち主への代入に直す。
- `dev/tests/e2e_datadir.py:56` はまだ `from ytt_core import layout` を読んでいる(RS5 の転送の片付けの対象)。
- 殻を置いても、移した先の部品どうしの import は `from . import store` の相対にする(裸の `import ed_store` を新しい層の部品に書かない。`test_no_bare_import_into_layer_packages` は ed_store が層のフォルダに無い間は見逃すが、殻を消す RS5 で一斉に壊れる)。
