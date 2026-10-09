> 状態(2026-10-10 朝): 下調べ(読むだけ。Sonnet)の報告そのまま。行番号は 2026-10-10 の main(1b27688)のもの。順番と決めることのまとめは `plan/role-restructure.md` の 8 節「RS3・RS4 の手順の案」と `plan/decisions.md` の 3-25。

# RS4(④ テストと検証)の下調べ(2026-10-10。読むだけ。リポジトリのファイルと git は変えていない)

調べ方: HEAD 1b27688 の追跡ファイルを AST と grep で数えた(数えた小さな .py は scratchpad の scan.py・scan2.py・scan3.py・scan4.py・rs4_*.py)。
`S.名前`(serve の名前の受付経由)の読み手は別名 S・S_・SV・serve・mod・J だけを数えた(`E.load_serve().名前` のような形は漏れうる)。行数は `wc -l`。
調査は 1 人で行った(読むだけで規模が小さいため。サブエージェントは使っていない)。

## 0. 先に結論

- **RS4 は「移す」だけでは違反が 49 → 44 程度しか減らない。評価用の判定(`eval_dirs`・`in_eval_dir`・`eval_name_guard`)を ytt に出す下ごしらえ(RS0-f)を先にやると、人の層から manage への違反 4 組が消える**。最後まで入れて **49 → 37(−12)** の見込み(2 節の表)。
- `ed_evalaudio.py` は読む側が本当に無い(読むのは `GET /api/eval-audio` の状態と、バックアップが作業データのフォルダを写すだけ。画面も測る道具も読まない)。消すと止まるのは「起動 5 分後と 6 時間ごとの flac 作り」と 1 本の API だけ。テスト 12 件 + 1 件が消える。`_file_lock`(32 行)だけ評価用のまとめての文字起こし(ed_evalbatch)が使うので持ち主を移す。
- **計画 7 節の `live_report` → `eval/tools` は誤り**: 書き手は ① の見回り(live.py)で、これが pipeline → eval の違反の原因。移すなら ① の記録の書き手として pipeline 側に置き、`failure_of` を口で渡す(−1)。
- **`demo_env.py` は eval/tools に移せない**(app の launch・mount を import する見本サーバー。ui_audit が子プロセスで起動)。dev に残す案。
- `dev/eval_*.py` 13 本 + `_evalcommon.py` は import が裸の名前(`import _evalcommon as C`)。層のパッケージに入れると test_layering の「裸の名前の禁止」に当たるので `from eval.tools import …` に直す。パスで起動する形は保てる。旧い場所に runpy の転送を残すと、起動中の古い入口の夜の自動測定(`accuracy.py` が `dev/eval_*.py` を子プロセスで呼ぶ)もそのまま動く。
- **罠**: `src/home/tests/test_accuracy.py:473-493` の `const()` は道具のソースが無いと `skipTest` する。道具を動かすと**黙って飛ばされる**(落ちない)。パスを直すのを忘れない。
- ① の記録と ② の記録の「分ける」は、RS4 では**コードの持ち主を分ける所まで**(データの形は変えない = RS0-d)。文書・diar.json・data.json・live の記録の形の分割は RS6。

---

## 1. 移す物の一覧

### 1-1 ファイル別(行数・依存・読み手・テスト)

凡例: 依存 = そのファイルが読む他の部品(`ed_xxx.名前 (回数)`)。「殻」= RS2 で転送だけにした `ed_jobs`・`ed_speakers`。

| ファイル | 行 | 行き先(案) | 依存 | 読み手(src・dev) | テスト・差し替え |
| --- | ---: | --- | --- | --- | --- |
| `src/editor/ed_drill.py` | 426 | `eval/drill/drill.py` | ed_jobs殻(ACTIVE_STATES・_jobs・_jobs_lock・stream_context)、ed_relink(EVAL_STAGING・EVAL_WALK_DEPTH・_EVAL_MEMBER_RE・_eval_members・_norm_member・eval_dirs・in_eval_dir)、ed_speakers殻(_spk_name_key・is_generic_speaker_name・read_diar・voices_summary)、ed_state(ApiError 7・ROSTER・TID_RE・check_source・file_stamp・log・norm_path・now_ms・num・plain_int)、ed_store(13 名: _save_lock・_tids・apply_edit_cuts・doc_length・effort_rows・good_row・prune_cache・read_transcript・row_dur・sanitize_transcript・snapshot・transcript_summary・write_doc)、`pipeline.transcribe.roster`、`ytt.fsio` | **ed_store.py:17,246**(`drill_doc_summary` を文書の要約に入れる = KNOWN の ed_store→ed_drill)、ed_evalbatch.py(DRILL_RECENT_SEC・_busy_tids・_media_ok・drill_docs)、serve.py:102,131,192,268-270,342-343、human/proof/speakers.py:10,33,506,556(コメントと口 `set_context_namer`)、rerun.py:50(コメント)。dev/_evalcommon.py の `is_reviewed` が `drill_is_reviewed` の写し(測る道具がサーバーを読まずに選ぶため) | test_drill.py(12 件・`import ed_drill as DR`)、test_autodiar.py(`ed_drill._drill_cache.clear()` 2 か所・S.drill_next 2・S.drill_candidates 1)、test_names.py(S.drill_candidates を set)、test_evalbatch.py(S._busy_tids 2)、e2e_drill.py |
| `src/editor/ed_evalbatch.py` | 881 | `eval/drill/evalbatch.py` | ed_drill(DRILL_RECENT_SEC・_busy_tids・_media_ok・drill_docs)、ed_evalaudio(`_file_lock`)、ed_jobs殻(ACTIVE_STATES 7・_jobs・_jobs_lock・add_job 3・cancel_job・job_done・public_job・record_rerun・validate_job 2)、ed_learn(load_settings)、ed_relink(EVAL_STAGING・_eval_videos・_evalorg_lock・eval_dirs 3)、ed_speakers殻(autodiar_enabled・autodiar_enqueue・autodiar_ready・diar_path・read_diar・DEFAULT_SPK_NAME)、ed_state(ApiError 22・SETTINGS 2・TID_RE・atomic_write・env_off・find_ffmpeg 2・log 10・norm_path 3・now_ms 16・num 9・plain_int)、ed_store(_save_lock・apply_edit_cuts・read_transcript 5・snapshot・summaries 2・write_doc) | serve.py:103,131,188,331-334,791、human/proof/doc_jobs.py(口 `redo_skip`・`redo_fill` の説明のコメントだけ。呼ぶのは serve の lambda) | test_evalbatch.py(28 件・`EB.` 直・`mock.patch.object(EB, "eb_redo_skip_at_start")` 2 か所 :560,:681・`ed_evalaudio._file_lock` :337)、test_autodiar.py(eb_* 6 名)、test_ovdraft.py・test_voices.py(S.EB_REDO_TOUCHED・eb_redo_why・_eb_touched_rows)、test_names.py(S.eb_redo_skip_at_start を set)、human/proof/tests/test_doc_jobs.py:67-68(`ed_evalbatch` をモジュールとして持たない検査) |
| `src/editor/ed_evalaudio.py` | 351 | **消す** | ed_relink(_eval_videos・_evalorg_lock・eval_dirs 4)、ed_state、ytt(fsio・jobs・tools)。:17-20 に単独実行(serve を import) | serve.py:101,131,275(`/api/eval-audio`)、:792(`start_background`)、ed_evalbatch.py:34,380(`_file_lock`)。**画面(js・html)・dev・home は読まない**(git grep で 0)。home/backup.py:10 は `transcribe\eval-audio\` を写す指定だけ | test_evalaudio.py(12 件・230 行)、test_edit.py:1149 `test_eval_audio_status_api`、test_metrics.py:902(`from test_evalaudio import *`)、test_evalbatch.py:26,337、AGENTS.md(editor):134-141・README.txt(editor):707-712 |
| `src/editor/ed_learn.py`(精度・基準・書き出し・保管) | 1,301 のうち約 700 | 下の 1-3 | 精度は ed_learn 自身の人の層の名(`_groups`・`_prep`・`_norm`・`split_nosub`)を読む(eval → human は許される向き)。`ed_jobs.split_terms`(metric_terms)・`extract_audio`(archive_doc) | serve.py(`all_metrics`・`read_baselines`・`record_baseline`・`export_corrections`:543・`start_archive`・`dataset_stats`)、ed_misc(A/B が acc_*・norm_cer・metric_terms)、dev/eval_asr・eval_alt(S 経由) | 1-6 |
| `src/editor/ed_relink.py`(評価用フォルダの整理) | 1,058 のうち約 475 + 判定 約 55 + `_move` 29 | 下の 1-4 | ed_store(_save_lock・read_transcript・summaries・snapshot・write_doc・transcript_summary)、ed_state(ApiError・log・now_ms・norm_path・num・DATA_DIR・MEDIA_TYPES)、同じファイルの `_doc_busy`・`_relink_write`(manage 側) | serve.py(`eval_organize`・`eval_settle`・`eval_folders_info`・`_evalorg_startup`)、ed_drill・ed_evalbatch・ed_evalaudio、判定は ed_alt:97・ed_ytcap:111・ed_store:144,488・ed_learn(`_eval_dirs_ok`)・doc_jobs の口 | test_edit.py の `TestEvalFolder`(:1176-1507 = 332 行・S.eval_organize 17 ほか)、test_edit.py:1476,1488(`mock.patch.object(ed_relink, "_same_drive", …)`)、test_evalbatch・test_autodiar・test_drill(EVAL_STAGING)、e2e_eval_set.py |
| `src/editor/ed_misc.py`(設定の比較 A/B) | 484 のうち 141(L17-157) | `eval/drill/abtest.py` | ed_jobs殻(Cancelled・ChunkModel・audio_span・extract_audio・glossary_of・job_errors・split_terms・tid_busy)、ed_learn(acc_finish・acc_line・apply_replacements・load_settings・metric_terms・new_acc・norm_cer・parse_replacements)、ed_state(EVAL_DIR・TMP_DIR・LANGS・atomic_write・backend_name・check_source・fake_sleep・has_faster_whisper・valid_model ほか)、worker_client(read_wav_f32) | serve.py:152(`_heavy_jobs.register("abtest", …)`)・:265-266,319 | test_backend.py(`S.run_abtest`:259・`S.scan_common`)、test_worker.py(S.validate_abtest)、test_metrics.py:655-699(`/api/abtest` の通し)、e2e_proofread_accuracy.py:161 |
| `src/home/accuracy.py` | 544 | `eval/drill/accuracy.py` | manage.cases.txindex、ytt(datadir・fsio・layout・schemas・tools)、**:288 の `import prefs`(app)** = KNOWN の (accuracy, prefs) | home/launch.py:84,866,1127,1320。health.py は `accuracy_probe` を受け取るだけ | test_accuracy.py(28 件・`import accuracy`・:300-312 と :473-493 が `dev/` を見る)、dev/tests/test_eval_asr.py:785-789(`import accuracy`)、e2e_portal |
| `src/home/live_report.py` | 240 | **pipeline 側(書き手)**。計画の eval/tools は誤り | `live_export`(pipeline)、`live_failures`(manage)、ytt.fsio。中身は `live.detector`・`livetx`・`exporter`・`requests` をダックタイプで読む | live.py:83,295,1127(`Reporter(self)`・`tick`)。読むのは dev/eval_marks.py `--live`(JSON を直に読む。import なし) | test_live_detect.py:1163-1210(Reporter・EVERY・END_WINDOW) |
| `dev/eval_*.py` 13 本 | 合計 7,539 | `src/eval/tools/` | 3-2 の表 | accuracy.py(子プロセス)、autorun.py:1099・live_detect.py:221・live_excite_worker.py:298(**④ の出力ファイル `evals/marks/*.json` を ① が読む**)、AGENTS・README・plan(3-1) | dev/tests/test_eval_*.py 13 本 + test_evalcommon(合計 5,914 行) |
| `dev/_evalcommon.py` | 272 | `src/eval/tools/_evalcommon.py` | `TOP`・`REPO`・`EDITOR` を `HERE`(dev/)から割り出している(:21-26)。`load_serve` が `src/editor/serve.py` をパスで読む(:174-216) | eval_alt・asr・cloud・cut・effort・fill・llm・marks・speakers・timing | test_evalcommon.py(9 件) |
| `dev/demo_env.py` | 223 | **dev に残す案** | `import launch`・`import mount`(:180-181)と `src/home/tests` の `test_launch`(:30-32) = app の層 | dev/ui_audit.py:710 が子プロセスで起動 | — |

移る行数の合計の目安: eval/drill 約 2,770(drill 426・evalbatch 881・folders 約 475・metrics 約 295・abtest 141・accuracy 544)、eval/tools 約 8,220(corrections・archive 約 408 + 道具 7,539 + _evalcommon 272)。消す: evalaudio 351 + テスト約 250。

### 1-2 `ed_evalaudio.py` を消すと何が止まるか(「読む側が無い」の確認)

- 読む側(git grep `eval-audio|ed_evalaudio|TRANSCRIBE_EVAL_AUDIO`、docs の履歴を除く): serve.py の 4 行(import・`_ED_MODULES`・`/api/eval-audio`・`start_background`)、ed_evalbatch の `_file_lock` だけ。js・html・dev の道具・home は 0。
- 止まる物: ①起動 5 分後と 6 時間ごとの flac 作り(`start_background`。環境変数 `TRANSCRIBE_EVAL_AUDIO=off` も不要に)、② `GET /api/eval-audio`(画面は無い = README.txt:711「画面はまだありません」)、③ 単独実行 `py -3.10 src/editor/ed_evalaudio.py`。
- 変わらない物: バックアップ(`home/backup.py:10`・`test_backup.py:52,75,262`・`docs/spec/data-location.md:119` は「`eval-audio\` を写す」。**消さない**。実データに残っている flac のため)。実データの `eval-audio/` は消さない(削除はユーザー確認後)。
- 注意: 動画が外付けにしか無いときの測定の保険という作った目的(ed_evalaudio.py:4-5)は、今は読み手がいないので果たしていない。測る道具が使う保険の音声は `dataset/docs/<id>/full.flac`(`_evalcommon.audio_span` :218-224。「保管」ボタン = `archive_doc` が作る)の側。
- 付け替え: `_file_lock`(L285-316。msvcrt/fcntl)は ed_evalbatch だけが使う → evalbatch の私的な関数にする(test_evalbatch:337 を `EB._file_lock` に)。`_eval_videos`・`_evalorg_lock` を読む `_busy_reason` は消える。

### 1-3 `ed_learn.py` の分け方(関数の範囲。HEAD の行番号)

| 範囲 | 中身 | 行き先 | 備考 |
| --- | --- | --- | --- |
| 27-128 | 設定(SETTINGS_PATCH_KEYS・load_settings・patch/merge/replace) | RS3(human・ytt/settings) | 触らない。`evalDirs` の検査 :56(`ed_relink._eval_dirs_ok`)は判定を ytt に出す下ごしらえで直す |
| 130-178 | 置換辞書(parse_replacements・apply_replacements) | human/proof | 触らない |
| 181-247, 305-653 | 対応づけ `_groups`・`_prep`・`_norm`・noSub・学習・提案・フィードバック・名簿・用語集 | human/proof | 触らない。**eval の測定がこの 4 名(`_groups`・`_prep`・`_norm`・`split_nosub`)を読む**(eval → human)。dev/eval_asr・eval_alt は `S._groups` などで読む(eval_effort は `_groups` の写しを持つ) |
| 215-217, 249-302 | `OVERLAP_SEC`・`OVERLAP_PERM`・nosub_stats・_ov_sec・is_overlap_group・overlap_orders・overlap_best_counts(約 56 行) | eval/drill/metrics.py | norm_cer・lev_counts を呼ぶ = 精度の別集計 |
| 655-865 | norm_cer・lev_counts・metric_terms・new_acc・acc_line/merge/finish・doc_metrics・config_key・all_metrics(約 211 行) | eval/drill/metrics.py | **人の層の学習側は norm_cer などを呼ばない**(grep: 249-302 と archive_entries :1062 だけ) |
| 866-893 | EVAL_BASE・read_baselines・record_baseline(約 28 行) | eval/drill/metrics.py | **serve.py:727 `ed_learn.EVAL_BASE = …`(set_data_dir)があるので、RS2-9a の声の置き場所と同じく呼ぶたびに txenv の DATA_DIR から作る形に** |
| 894-984 | export_corrections・`_export_corrections_zip`(約 91 行) | eval/tools/corrections.py | 画面の「学習」の書き出し(app.js:318 `#lnExAudio`)から使われる。serve.py:543 |
| 985-1301 | ARCH_*・archive_entries・archive_doc・archive_rebuild_index・start_archive・dataset_stats(約 317 行) | eval/tools/archive.py | 画面の「保管」(app-learn.js:570,593・app.js:516)から。**読み手が測る道具にある**: `_evalcommon.audio_span` が `dataset/docs/<id>/full.flac` を使う。「使っていなければ消す」には当たらない |

### 1-4 `ed_relink.py` の分け方

| 範囲 | 中身 | 行き先 | 備考 |
| --- | --- | --- | --- |
| 24-209 | 付け替え(relink_*・`_relink_write`・`_doc_busy`) | manage/cases(RS3) | 触らない。ただし eval の整理が `_relink_write`・`_doc_busy` を読む(eval → manage は許される向き) |
| 210-388 | 30fps(norm_*) | RS3(ingest・cases) | 触らない。`in_eval_dir` を呼ぶ :349,:373 は ytt の判定に付け替え |
| 394-499 | 見つからない動画の探索・pick_path | RS3 | 触らない |
| **30-41, 506, 519-562** | `_remote_drive`・`EVAL_DIRS_MAX`・`_eval_dirs_ok`・`eval_dirs`・`in_eval_dir`・`EVAL_NAME_WORD`・`eval_name_guard`(約 55 行) | **ytt/evaldirs.py**(RS0-f の「判定だけ ytt」。設定の値と DATA_DIR は serve が登録する口で渡す。RS3/RS5 で ytt/settings に畳む) | ed_alt:97・ed_ytcap:111・ed_store:144,488・ed_learn の `_eval_dirs_ok`・doc_jobs の口(`eval_guard`・`in_eval_dir`)が読む。`_remote_drive` は relink_path・norm_plan・relink_folder も使うので `ytt.fsio` の共通の関数にする |
| 607-635 | `_same_drive`・`_move` | ytt/fsio | 別ドライブでも安全な移動。home/intake.py(自前の `_move` を持つ)・dev/eval_split(自前の `_move`)は別物。test_edit:1476,1488 の patch を新しい持ち主へ |
| 503-518, 565-604, 638-1058 | 整理の定数・走査・仮置き・取り込み・eval_organize・eval_settle・eval_folders_info・`_evalorg_startup`(約 475 行) | eval/drill/folders.py | `_EVAL_MEMBER_RE`・`_eval_members`・`_norm_member`・`EVAL_STAGING`・`EVAL_WALK_DEPTH` は drill.py も読む(同じ eval/drill の中) |

### 1-5 A/B(ed_misc L17-157)

`MAX_AB_LINES`・`MAX_AB_VARIANTS`・`KEEP_EVALS`・`ab_label`・`validate_abtest`・`_fake_hyp`・`run_abtest`・`read_eval`・`_BROKEN`・`list_evals` の 141 行。画面は app.js:502(設定の比較の「比較を実行」)・app-learn.js:555(結果の一覧)・index.html:1480。ジョブ kind `abtest` は serve.py:152 で `ytt.jobs.register`。結果は `EVAL_DIR/<job id>.json`(直下の JSON。dev の道具の `evals/<領域>/` とは別の深さ)。`ed_state.fake_sleep` は `eval.fake.fake_asr.fake_wait` の別名なので、移した先では直に読める。

### 1-6 テストの差し替え(`S.名前`・patch の数。serve 経由は `_ED_MODULES` に新しい持ち主を並べれば届く)

| 対象 | S 経由の読み(get)・差し替え(set/patch) | 直の別名・patch |
| --- | --- | --- |
| 精度(metrics)の名前 | 5 ファイル 94 回(dev/eval_asr 12・test_metrics 40・test_nosub_metrics 34・test_ovdraft 5・test_eval_asr 3)・差し替え 2(test_metrics の `S.MAX_LEV_CELLS`) | — |
| 書き出し・保管 | 2 ファイル 8 回(test_backend 2・test_nosub_metrics 6) | — |
| 評価用の判定 | test_edit 7 回・test_names の `S.in_eval_dir` を set | — |
| 評価用の整理 | test_edit 25 回・test_drill 1 回 | test_edit:1476,1488 `patch.object(ed_relink, "_same_drive")` |
| A/B | test_backend・test_worker・test_metrics・e2e | — |
| drill | test_autodiar 3・test_names 1(set)・test_evalbatch 2 | test_drill は `DR.` 直(12 件)・test_autodiar は `ed_drill._drill_cache` |
| evalbatch | test_ovdraft・test_voices・test_names(set)・test_autodiar | test_evalbatch は `EB.` 直・`patch.object(EB, "eb_redo_skip_at_start")` 2 |
| accuracy | — | test_accuracy は `accuracy.` 直(`mock.patch.object(accuracy, "summarize_asr")`・`"AREAS"`)・`import accuracy` |

直の別名を持つテストは import の 1 行を `from eval.drill import … as DR` などに直す。**旧い名前の殻は作らない**(ed_drill・ed_evalbatch は殻なしで消す。残すと S.名前 の差し替えが別名に当たる = RS2 の注意)。

---

## 2. 層の向き

### 2-1 移したあとの eval が読む物(eval は全部の層を読める)

| 新しいファイル | 読む相手(層) | 注意 |
| --- | --- | --- |
| eval/drill/drill.py | ytt(errors・fsio・schemas・jobs・evaldirs)、pipeline.transcribe(roster・txenv)、human(ed_store → RS3 で human/proof、speakers)、eval/drill/folders | `ed_state` を読まない: ApiError=`ytt.errors`、TID_RE・num・plain_int=`ytt.schemas`、file_stamp=`ytt.fsio.stamp`、log・env_off=`txbase`、ROSTER・check_source・find_ffmpeg・DATA_DIR=txenv。**足りない物**: `norm_path`・`now_ms`(ed_state に 1 行ずつ。差し替えるテストは無い = ytt へ移して別名)、`MEDIA_TYPES`(辞書。差し替えは無い)、`SETTINGS`・`DATASET_DIR`・`EVAL_DIR`・`FEEDBACK`(txenv に鍵 4 つ足す)。`atomic_write`・`replace_retry` は `ytt.fsio` の薄い包み |
| eval/drill/evalbatch.py | ytt(jobs: add_job・cancel_job・job_done・ACTIVE_STATES・_jobs・_jobs_lock)、human(doc_jobs: validate_job・public_job、rerun: record_rerun、speakers: autodiar_*・read_diar、ed_store、ed_learn.load_settings)、eval/drill(drill・folders) | 殻 `ed_jobs`・`ed_speakers` を読まず、本当の持ち主を読む(殻の読み手が 2 つ減る = RS5 が楽になる)。`_file_lock` は私的に持つ |
| eval/drill/folders.py | manage(ed_relink: `_doc_busy`・`_relink_write`)、human(ed_store)、ytt(evaldirs・fsio) | eval → manage は許される |
| eval/drill/metrics.py | human(ed_learn の `_groups`・`_prep`・`_norm`・`split_nosub`・`load_settings`・`parse_replacements`・`apply_replacements`)、human(ed_store)、pipeline.transcribe.roster(split_terms)、txenv | 学習側から metrics への向きは無い(向きは eval → human の一方向) |
| eval/drill/abtest.py | ytt.jobs(job_errors・Cancelled・tid_busy)、pipeline.transcribe(recognize: ChunkModel・extract_audio・audio_span、roster、worker_client、txenv)、human(doc_jobs.glossary_of、ed_store)、eval.fake.fake_asr、eval/drill/metrics | |
| eval/tools/corrections.py・archive.py | human(ed_store・ed_learn の `_groups` ほか)、pipeline.transcribe.recognize.extract_audio、eval/drill/metrics.norm_cer、txenv、ytt | `ed_state.TAGS`(3 つの文字列)は `ytt.schemas` に足す |
| eval/drill/accuracy.py | manage.cases.txindex、ytt | **prefs は読まない**: Accuracy は `prefs` を受け取っている。:288 の `prefs_mod.DEFAULTS["accuracy"]` の予備だけ、定数 `DEFAULT_CFG = {"enabled": True, "nightFrom": 1, "nightTo": 6}` で持つ(prefs.py:71 の `DEFAULTS["accuracy"]` との一致を見る 1 件を test_accuracy に足して固定する。test_settings_schema は accuracy の検査関数を見るだけで既定値の一致は見ていない) |
| eval/tools/eval_*.py・_evalcommon.py | manage.cases.txindex、pipeline.analyze.excite、pipeline.transcribe.(roster・llm・worker)、ytt、eval.tools.evaldata | `eval_alt.py:108` の `import ed_state`(関数の中。AST は関数の中の import も数える = test_layering:89)を `S.ed_state` に。`load_serve` はパスで serve.py を読むだけ(import ではない = 検査に出ない) |

### 2-2 下の層が eval を読んでいる所(KNOWN)と口にする方法

1. **(ed_store.py → ed_drill.py)** human → eval。ed_store.py:246 が `ed_drill.drill_doc_summary` を文書の要約 `_drill` に入れている。RS0-m(見直し版: ドリルの要約は ④ が自分で)のとおり、**drill 側が自前で作る**: `drill_docs()` が `ed_store.transcript_summary(tid)` の `evalSet` と `_key` だけ見て、評価用の文書だけ `_load_doc` で読み直し、`(_key, 名簿の版)` で覚える。登録の口は足さない(RS0 の見直しで口は e だけ)。評価用の文書だけ 1 回余計に読むが少数。`_drill` のキーを読むテストは無い(git grep)。
2. **(live.py → live_report.py)** pipeline → eval。上の 0 節のとおり live_report を ① の記録の書き手(pipeline)にして、`Reporter(self, failure_of=live_failures.failure_of)` と渡す(live.py は live_failures を既に読んでいる = KNOWN の (live, live_failures))。ファイル名は `live_report.py` のまま pipeline 側へ(RS3 のライブの移動と一緒でもよい)。`layer_map.FILES` の行を `("pipeline", "pipeline/run", …)` に訂正。
3. **口で ④ を差し込んでいる所(違反ではない)**: `doc_jobs.set_hooks(redo_skip・redo_fill)`(serve.py:187-189)、`speakers.set_context_namer`(serve.py:192)。移し先の名前に直すだけ。
4. **ファイルの境目で ④ → ① が読まれている所**(import ではないので検査に出ない): `home/autorun.py:104,111,1099`(`evals/marks/*.json` の `clipLength` = 友人の区間の長さ)・`live_detect.py:221`・`live_excite_worker.py:97-102,298`。計画の 9 節「友人の区間の長さ・配信中の長さの目安を dev の測定結果から決めている作り」。**RS6 で ③ の学習データに置く形へ**。RS4 では触らない(測る道具を動かしても書く場所と名前の形 `<日時>.json` を変えない)。

### 2-3 評価用の判定を ytt に出すと消える違反

(ed_alt, ed_relink)・(ed_ytcap, ed_relink)・(ed_store, ed_relink)・(ed_learn, ed_relink) = **4 組**(どれも `in_eval_dir` か `_eval_dirs_ok` だけを読む。scan3 で確認)。`ed_store → ed_misc` は `_read_json_file` だけ(ed_store.py:280)なので `_fsio.read_json_or(path, None, 64MiB)` に直すと消える(+1)。doc_jobs の口は 5 本 → 3 本(`eval_guard`・`in_eval_dir` が不要)。**RS3(txenv → ytt/settings)と重なる**ので RS3 に「`ytt/evaldirs.py` は settings に畳む対象」と伝える。

### 2-4 違反の減り方の見込み(KNOWN 49)

| 段 | 消える組 | 件数 |
| --- | --- | --- |
| RS4-1 判定を ytt へ | ed_alt・ed_ytcap・ed_store・ed_learn → ed_relink(4)、ed_store → ed_misc(1) | 49 → 44 |
| RS4-2 drill・evalbatch・folders・evalaudio | ed_drill→ed_state、ed_evalbatch→ed_state、ed_evalaudio→ed_state・serve(2)、ed_store→ed_drill | 44 → 39 |
| RS4-3 metrics・abtest・corrections・archive の切り出し | 変わらない(新しい違反を作らない。ed_learn→ed_state・ed_misc→ed_state・ed_relink→ed_state は RS3) | 39 |
| RS4-4 accuracy・dev の道具 | accuracy→prefs | 38 |
| RS4-5 live_report | live→live_report(`failure_of` を口で渡すので pipeline→manage を増やさない) | 37 |

---

## 3. dev/eval_* を src/eval/tools へ移すときの困りごと

### 3-1 説明の数(`git grep`、`dev/eval_*`・`_evalcommon`・`demo_env` のパスの出る行。合計 445 行)

| 区分 | 行数 | 直す? |
| --- | ---: | --- |
| 過去の記録(docs/WORKLOG.md・docs/design/*) | 227 | 直さない(AGENTS.md の決まり) |
| plan/*.md・plan/data.js(data.js は 9 行) | 75(うち data.js 9) | 現役の plan だけ(role-restructure・data.js・decisions の新しい節)。他は履歴扱い |
| docs/spec・HANDOVER | 7 | 直す(spec 6 ファイル 7 行) |
| AGENTS.md・README.txt(AGENTS.md 3・src/editor/AGENTS.md 19・src/editor/README.txt 10・src/home/README.txt 6)のツール名の行 | 38 | 直す。**ユーザーが手で打つ形の指示は 2 か所**: src/editor/README.txt:926(`python dev/eval_asr.py stored`)・src/home/README.txt:213(`py -3.10 dev/eval_marks.py --live`)。ほかは道具の名前の言及 |
| src の .py(コメント・docstring・文字列) | 41 + テスト 11 | コメントが主。コードで効くのは accuracy.py(AREAS :171-175・:296)・test_accuracy・test_eval_asr:785 |
| dev の .py・dev/tests | 37 + 14 | 道具自身の使い方の docstring(`python dev/eval_x.py …`)約 35 行は、移すファイルの中でパスを直す |
| 画面 | 1 | src/editor/app.js:289 のコメント |

`.bat`・`setup/`・`.gitignore`・`push_helper` に道具のパスは無い。`dev/run_editor_suite.py:23-24` が `dev/tests/test_eval_asr.py`・`test_eval_alt.py` を流す(テストを移すなら 2 行)。AGENTS.md の表の `dev/` の行(「道具を変えたら対応する `dev/tests/test_<名前>.py`」)も直す。

### 3-2 道具どうしの依存と import の形

eval_cloud・eval_effort・eval_timing・eval_llm・eval_alt → `eval_asr`(`import eval_asr as E`・`eval_asr.load_serve`)。eval_fetch → eval_split。eval_asr → eval_import(:164 の関数の中)。ほかは `_evalcommon` だけ。全部 `import _evalcommon as C` の裸の名前で、`sys.path.insert(0, HERE)` で dev/ を通している(各ファイルの冒頭)。**層のパッケージに入ると `dev/tests/test_layering.py:130-131` の「裸の名前で層のパッケージを読まない」に当たる** → `from eval.tools import _evalcommon as C`(先に `sys.path` に src を入れる。eval_asr.py:79 は既に `from eval.tools import evaldata` を使っているので前例あり)。パスで起動する形(`__main__`)では相対 import が使えないため絶対 import + 冒頭の sys.path の補正(tx_worker の worker.py の前例)。

### 3-3 `dev/tests/test_eval_*.py` の読み方

13 本 + test_evalcommon = 14 ファイル・5,914 行。冒頭で `HERE = dev/`(`dirname(dirname(__file__))`)を `sys.path` の先頭に入れ、`import eval_asr as E`(裸の名前)。7 本(cut・effort・fetch・marks・speakers・split・timing)は `REPO = src` も入れる(eval_import は `src/` を足す)。実行は `py -3.10 -m unittest dev/tests/test_eval_x.py`(冒頭の docstring に書いてある)。`test_eval_asr`・`test_eval_effort`・`test_eval_timing`・`test_eval_speakers` は `E.load_serve("fake")` で editor の serve をこのプロセスの中に読む。test_eval_asr:785-789 は `src/home` を sys.path に入れて `import accuracy`。→ 道具と一緒に `src/eval/tools/tests/` へ移す案(既に `src/eval/tools/tests/test_evaldata.py` が前例。層のパッケージの tests/ に置く決まり)。冒頭の 3-4 行(HERE・sys.path・import)を直すだけ。

### 3-4 旧い場所に転送を残すべきか → **残す案(RS5 で消す)**

- 理由 1(入口が起動中の古いコード): `accuracy.py` は夜の窓に `[python, <repo>/dev/<script>, args]` を子プロセスで起動する(:296)。転送が無いと古いまま動いている入口の夜の自動測定が「道具が無い(飛ばす)」になる(`_default_commands` は無ければ None)。壊れはしないが数が貯まらない。
- 理由 2: 過去の WORKLOG・計画書のコマンドが動く。ユーザーが手で打つ癖があれば同じ。
- 形は `src/recorder/recorder.py`・`src/editor/tx_worker.py` と同じ runpy の転送(約 15 行 × 13 本。`_evalcommon` と `demo_env` には要らない)。新しい入口のパス: `py -3.10 src/eval/tools/eval_asr.py stored`。
- 道具の中の使い方の docstring(`python dev/eval_x.py …`)は新しいパスに直す。

### 3-5 そのほかの困りごと

- **`_evalcommon` の場所の割り出し**: `TOP = dirname(HERE)`・`REPO = TOP/src`・`EDITOR = REPO/editor`(:21-26)・`git_rev` が TOP を使う(:131-139)。移すと `HERE` が `src/eval/tools` になるので `layout.src_root()`・`layout.repo_root()` で割り出す。`eval_split.py:38`・`eval_fetch.py:385` も `REPO/editor/hololive-roster.json` のパスを持つ。
- **`demo_env.py`**: eval の層は app を読めない(`launch`・`mount`・`test_launch`)。eval/tools に入れると (eval, app) が 2 組増える。`layer_map.FILES` で app の層に上書きする手もあるが、置き場所の意味が合わない → **dev に残す**(計画 7 節の最後の行から demo_env を外す)。
- **`accuracy.py` の既定のコマンド**(:295-297): `os.path.join(layout.repo_root(self.repo_root), "dev", area["script"])` を `os.path.join(self.repo_root, "eval", "tools", area["script"])` に。AREAS の説明コメント(:169)・docstring(:4-7,56-57)も。
- **黙って飛ぶテスト**: test_accuracy.py:473-493 の `const()` は道具が無いと `skipTest`。:300-312 は `os.path.isfile(dev/eval_cut.py)` の有無で期待が変わる。道具を動かしたら両方を新しい場所へ。`test_goal_thresholds_match_the_tools` が実際に走っていることを実行の出力(skipped 0)で確かめる。
- **同じ名前の .py**: 転送 `dev/eval_asr.py` と本体 `src/eval/tools/eval_asr.py` は dev が test_layering・test_mount の対象外なので衝突しない。
- **`sys.modules` の名前**: `load_serve` は `tx_serve_for_eval` の名前で serve.py を登録して読む(:172-203)。モジュール名が変わっても影響しない。
- **e2e の写す一覧**: `layout.SHARED_CODE_DIRS` に `eval` が入っているので `src/eval/` は自動で写る。

---

## 4. ① の記録と ② の記録を分ける

### 4-1 今混ざっている具体例

| 場所 | ① の物 | ② の物 | ④ の物 | 書く・触る関数(例) |
| --- | --- | --- | --- | --- |
| 文書 `transcripts/<id>.json` | `original`・`model`・`params`・`recognition.runs`(最初の認識 + 再認識の `replaced`)・`diarization.auto` | `segments`(`text`・`proofed`・`proofedAt`・`tags`・`cutState`・`noSub`)・`speakers[].name/color/sub`・`effort`・`relinks`・`diarNum` | `evalSet`・`evalReviewed`・`spec.evalRedo` による runs | `doc_jobs._rows_to_doc`(:408)・`_doc_fields`(:438)が ① の結果と ② の文書を 1 関数で作る(RS0-i)。`rerun.record_rerun`(:42)は ② の直しの前に ① の runs を書き足し、`evalReviewed` を外す(:52)。`ed_store.sanitize_transcript`(:139-149)・`fill_doc`(:1025)も ④ の印の面倒を見る |
| 行の `fill = {from, by}` | 認識のあとの後処理(① の出力)の印 | 人の行 `segments[]` の中に埋まる | | `ed_store.sanitize_transcript` が残す(:133)。画面の「別の読み」で戻す |
| `transcripts/<id>.diar.json` | `latest`(turns・overlaps・rows・labelMap) | `voices`(decided・by・context)を人の層が書き足す | | `diarize.update_diar_voices`(:330)・`speakers._autodiar_record`(:634)。RS2-9 で「RS0-h と食い違う」と記録済み |
| スタジオ `data.json` | 候補の点数・series | `status`(adopted/rejected)・`adoptedBy`・`file` | | `store.py:148-183`。RS0-d で RS6 |
| `live/reports/*.json`(live_report) | `samples`(遅れ・メモリ・再起動)・`detect`(候補数)・`tx`・`exports`・`disk` | `detect.adoptedAuto/Manual`(`_decisions` の origin)・`request {rid, streamer}`(友人) | 読むのは eval_marks `--live` | live_report.py:158-202。**live_detect は既に ① の `peaks.json` + ② の `decisions.json` の重ね合わせ(:344-356)で、望む形の見本** |
| `learn-feedback.json` | | 提案の採用・却下 | | 作るのは ed_learn.record_feedback、① の `doc_jobs` が autoLearned で読む(計画 6(B)のとおり。直さない) |
| `evals/<領域>/<日時>.json` | | | 測る道具の結果 | ① の 3 か所(autorun・live_detect・live_excite_worker)が読む(2-2 の 4) |

### 4-2 線引きの案

**RS4 でやる(データの形を変えない = RS0-d)**
1. ④ が ② の文書に書く入口を 3 つに限り、全部 `ed_store.write_doc` + `_save_lock` を通す: `drill_reviewed/unreviewed`(印)・`eb_redo_fill`(作り直し)・`eval_organize` 系の `_eval_mark_docs`(評価用の印)。移す先は eval/drill の 1 か所ずつ(今も通している。docs に「④ が文書に書く 3 つの入口」として 1 節足す)。
2. ② の側が ④ の内部を知る所を減らす: ed_store → ed_drill(要約)を外す(2-2 の 1)・`ed_relink` の評価用の判定を ytt へ(2-3)・doc_jobs の口を 5 → 3 本。`evalReviewed` の鍵を知る人の層のコード(`ed_store.py:149,1025`・`rerun.py:52`・`speakers.py:532`)は、鍵の名前を `ytt.schemas` の定数にしてコメントで ④ の印と明記する程度(動きは変えない)。
3. live_report を ① の記録の書き手にして pipeline に置く(2-2 の 2)。`adoptedAuto/Manual` と `request` は ② 由来の項目だが、JSON の形はそのまま(読み手 eval_marks が壊れない)。
4. 「記録の持ち主の表」(4-1 の表)を `docs/spec/pipeline.md` か `docs/spec/data-location.md` に足し、RS6 の入力にする。

**RS6 に送る(データの形を変える)**
- 文書の ① 部分(`original`・`recognition`・`diarization.auto`・`fill`)と ② 部分(`segments` の人の直し)を別の入れ物にする(5-3 の上書き。F-2・F-3)。
- diar.json の `voices`/`context` を人の層の別ファイルに。
- スタジオ data.json の `status`/`adoptedBy` と `live_feedback.jsonl`(RS0-d)。
- live_report の ① 部分と ② 部分を 2 つの JSON に(eval_marks の読み方を変える)。
- 友人の区間の長さ・配信中の長さの目安(evals/marks → ③ の学習データ)。

---

## 5. 段の案

### 5-1 段とコミット

| 段 | 内容 | 触るファイル | 担当(モデルと理由) | 通すテスト | 目安 |
| --- | --- | --- | --- | --- | --- |
| **RS4-1** 下ごしらえ(1〜2 コミット) | `ytt/evaldirs.py`(判定。設定と DATA_DIR は serve が登録する口 + `check`)・`ytt.fsio` に `is_remote_drive`・`move_safe`(`_move`/`_same_drive`)・`ytt.schemas` に `MEDIA_TYPES`・`TAGS`・`norm_path`・`now_ms`(ed_state に別名 `# lint: keep`)・txenv に鍵 `SETTINGS`・`DATASET_DIR`・`EVAL_DIR`・`FEEDBACK`・`ed_store:280` の `_read_json_file` を fsio へ・doc_jobs の口 5 → 3・新テスト `src/ytt/tests/test_evaldirs.py` | ytt/、pipeline/transcribe/txenv.py、ed_relink(55 行を切り出す)、ed_alt・ed_ytcap・ed_store・ed_learn(import 1 行ずつ)、doc_jobs.py、serve.py、ed_state | **Opus**(評価用の安全止め = 学習用に混ざるのを防ぐ判定を動かすため。影響が広い置き場所の口) | `src/ytt/tests/*`・`src/human/proof/tests/test_doc_jobs.py`・editor 一式(`test_metrics.py` + `test_resolve_export.py` + `test_roster.py`。TestEvalFolder と test_names が入る)・`dev/tests/test_layering.py`・lint | 2 時間 |
| **RS4-2** drill・evalbatch・folders・evalaudio(3〜4 コミット。移動だけ → 付け替え の 2 段) | `git mv ed_drill.py → eval/drill/drill.py`・`ed_evalbatch.py → evalbatch.py`(移動だけのコミット)→ import の付け替え(ed_state/殻を本当の持ち主へ)・ed_store の `_drill` を外し drill が自前で要約・ed_relink の整理を `eval/drill/folders.py` に切り出し・`ed_evalaudio.py` と関連のテストを消す(`_file_lock` は evalbatch の私的な関数に)・serve.py の `_ED_MODULES`・routes・口の名前・`/api/eval-audio`・`start_background`・layer_map・KNOWN | eval/drill/*、ed_relink、ed_store(2 か所)、serve.py、test_drill・test_evalbatch・test_autodiar・test_names・test_edit・test_metrics(1 行)・e2e_drill・e2e_eval_set | **Opus**(要約の切り離し・排他・口・評価用の作り直しの書き込みのため) | editor 一式 + `e2e_drill.py`・`e2e_eval_set.py`・`e2e_ui_mounted.py`(1 本ずつ・`PYTHONIOENCODING=utf-8`)・test_layering・lint | 3〜4 時間 |
| **RS4-3** metrics・abtest・corrections・archive | ed_learn の 249-302・655-893 → `eval/drill/metrics.py`、894-1301 → `eval/tools/corrections.py`・`archive.py`、ed_misc の A/B → `eval/drill/abtest.py`。`EVAL_BASE` は呼ぶたびに作る形に。serve.py の routes と `set_data_dir`:727・`_ED_MODULES` | ed_learn・ed_misc・serve.py、test_metrics・test_nosub_metrics・test_ovdraft・test_backend の `S.` はそのまま(持ち主が `_ED_MODULES` にあれば届く) | **Sonnet**(関数の範囲が決まっている規則の切り出し。この資料の 1-3・1-5 をそのまま渡す) | editor 一式(test_metrics が test_nosub_metrics・test_backend・test_edit を読む)・`e2e_proofread_accuracy.py`・`dev/tests/test_eval_asr.py`・test_layering・lint | 2 時間 |
| **RS4-4a** 道具の移動 | `dev/eval_*.py` 13 本 + `_evalcommon.py` を `git mv`(移動だけ)→ import・パスの割り出し・使い方の docstring の付け替え → `dev/eval_*.py` に runpy の転送 13 本・テスト 14 本を `src/eval/tools/tests/` へ・`run_editor_suite.py:23-24`・AGENTS の表 | dev/、eval/tools/ | **Sonnet**(機械的) | `src/eval/tools/tests/` 14 本(1 本ずつ。`py -3.10 -m unittest <ファイル>`)・`dev/run_editor_suite.py` が指す先・lint・test_layering | 2 時間 |
| **RS4-4b** accuracy | `home/accuracy.py → eval/drill/accuracy.py`・AREAS と `_default_commands` のパス・`prefs` の予備を定数に・launch.py:84 の import・test_accuracy(:300-312,:473-493 のパス = 黙って飛ばない確認)・test_eval_asr:785 | home/launch.py、home/tests/test_accuracy.py、dev/tests/test_eval_asr.py(= RS4-4a と同じ人が続けて) | **Sonnet** | `src/home/tests/test_accuracy.py`・`test_launch.py`・`test_health.py`・`e2e_portal.py` | 1 時間 |
| **RS4-5** live_report | pipeline 側へ・`failure_of` を口で渡す・layer_map の行の訂正・計画 7 節の表の訂正 | live.py(RS3 が動かす)、live_report.py | **Sonnet**。**RS3 のライブの移動と一緒にやるのが安全**(live.py を RS3 も触るため)。先に RS4 でやるなら RS3 の開始前に 1 コミットで | `src/home/tests/test_live_detect.py`・`test_live.py`・`e2e_live.py` | 0.5 時間 |
| **RS4-6** 文書とまとめ | AGENTS.md(フォルダの並び・層の行・`dev/` の行・テストの表)・src/editor/AGENTS.md(各節の持ち主・評価用の音声の節を消す)・README.txt の道具のパス 2 か所・docs/spec/pipeline.md に「記録の持ち主の表」・layer_map(FILES から移した行を消す・KNOWN_MAX 37)・plan(RS4 を済みに・data.js・公開ページ)・decisions に RS4 の仮決め・HANDOVER・WORKLOG | | Sonnet(文書)+ 私 | 全部(下) | 1 時間 |

最後の一式(サブエージェントが止まってから): editor・transcribe・human・ytt・pipeline の unittest、`src/home/tests` の関連、test_mount(単独)、契約(単独)、dev/tests、lint 0、`py -3.10 dev/ui_audit.py all --demo`(demo_env を dev に残すので影響は無いが、`ui_audit` が子プロセスで起動するため 1 回確認)、e2e は 1 本ずつ(e2e_drill・e2e_eval_set・e2e_proofread_accuracy・e2e_ui_mounted・e2e_live)。

### 5-2 並列にできる所(触るファイルが重ならない組)

RS4-1 が終わってから次の 3 本は並列にできる:
- **A: RS4-2**(ed_drill・ed_evalbatch・ed_relink の整理・ed_evalaudio・ed_store の 2 か所)
- **B: RS4-3**(ed_learn・ed_misc。A と重ならない。どちらも serve.py の登録行を触るので、**serve.py・layer_map.py・AGENTS.md は担当を作らず、まとめ役が最後に 1 回で直す**(各担当は「serve.py に足す行」をコミットメッセージか報告に書く))
- **C: RS4-4a + 4b**(dev/・eval/tools/・home/accuracy・launch の import 1 行)

RS4-5 は RS3 のライブの移動と同じ担当。RS4-6 は最後。

**RS3 との衝突**: ed_learn・ed_relink・ed_misc・ed_store・ed_alt・ed_ytcap・serve.py・doc_jobs.py・live.py・layer_map.py・AGENTS.md を両方が触る。切り出し(RS4-1〜3)を先にして**小さなコミットで main に入れ、RS3 は切り出しの終わった残りを `git mv`** する順にすれば、同じファイルを同時に書き換えない。RS4-1 の `ytt/evaldirs.py` は RS3 の ytt/settings の下ごしらえと同じ領域なので、先に RS3 の担当へ連絡。サブエージェントの作業フォルダは古いコミットから始まる(HANDOVER の注意)ので最初に `git merge --ff-only main`、取り込みは cherry-pick、移動は「移動だけ」と「付け替え」のコミットを分ける。

### 5-3 所要の目安

AI の作業で半日〜1 日(計画の「半日」より増える理由: 評価用の判定の下ごしらえと、テスト 14 本を含む道具の移動が加わった)。並列 3 本なら実時間で 4〜5 時間 + 最後の一式 1〜1.5 時間(サブエージェントが止まってから)。

---

## 6. 要判断

| 事 | 仮で決めるなら | 理由 |
| --- | --- | --- |
| ① `ed_evalaudio` を消す | 消す(計画 9 節で決定済み)。実データの `eval-audio/` とバックアップの写す指定は残す | 読む側が無い。ただし保険の音声は「保管」ボタンで作る `dataset/docs/<id>/full.flac` だけになる(外付けの動画が無いときの測定用)ことは 1 行伝える |
| ② 設定の比較(A/B)・修正データの書き出し・データの保管を消すか | **消さずに移す**(A/B → eval/drill、書き出し・保管 → eval/tools) | 画面に出ている(app.js:318,502,516)。保管は測る道具が読む(`audio_span`)。使っているかはユーザーにしか分からない |
| ③ 道具の新しいパスとコマンド | `py -3.10 src/eval/tools/eval_asr.py …`。`dev/eval_*.py` は runpy の転送で残す(RS5 で消す) | 起動中の古い入口の夜の自動測定が動き続ける・過去のコマンドが動く |
| ④ `demo_env.py` | dev に残す(計画 7 節の最後の行を直す) | app の launch・mount を読む。eval の層から app は読めない |
| ⑤ 道具のテストの置き場所 | `src/eval/tools/tests/` へ(前例 test_evaldata.py) | 層のパッケージの tests/ の決まり |
| ⑥ `live_report` の行き先 | pipeline 側(① の記録の書き手)。計画 7 節の「eval/tools」を訂正 | 書き手が ① の見回りで、eval に置くと違反が残る |
| ⑦ ドリルの要約を ed_store から外して drill が自前で作る | そうする(登録の口は足さない) | RS0-m 見直し版のとおり。評価用の文書だけ読み直すので負荷は小さい |
| ⑧ 評価用の判定の置き場所 | `ytt/evaldirs.py`(登録の口つき)。RS3/RS5 で ytt/settings に畳む | RS0-f(判定だけ ytt)。いま ytt/settings は無い |
| ⑨ 「進行度を消す」(3-22 の m) | **RS4 の外**。RS3 か RS5 でまとめて確認 | 画面(`#goalCard`・`/api/progress`)と test_metrics の変更を伴う。RS4 の移動と混ぜると落ちた原因が分からない |
| ⑩ 「あとから解析(測るため)」(autorun の約 290 行)の削除と ④ の代わりの道具 | **RS4 の外**(RS3 の autorun の分割と一緒) | 消すと友人の区間の見逃しの測定(eval_marks の friendRanges)に使うデータが貯まらなくなる。代わりの道具が要る |
| ⑪ 記録を分ける範囲 | 4-2 の「RS4 でやる」4 点まで。形の分割は RS6 | RS0-d |
| ⑫ ユーザーに見せる変化 | 画面の動きは変わらない。変わるのは `/api/eval-audio` が無くなること(画面は読まない)と、道具のパスだけ | |
| ⑬ 版を上げるか | 上げない(RS2 と同じ。動きが変わらない) | 3 ツールの版の同期の手間を避ける |

ユーザーに聞くのは ①(念押し 1 行)・②(使っているか)・⑥⑨⑩(計画の訂正)。残りは仮のまま `plan/decisions.md` の「仮で決めたこと」に並べ、最後にまとめて確認。

## 付録: 根拠の数字の出し方と限界

- 参照の数: `git grep -nE "dev[/\\](eval_|_evalcommon|demo_env)"`(445 行)を区分で数えた。
- 読み手: ファイル単位は `import X`・`import X as Y`・`from X import …` と `X.名前` を AST + 正規表現で。serve 経由は `S.名前`・`S_`・`SV`・`serve`・`mod`・`J` の別名だけ。`E.load_serve().名前` のような式は拾っていない。
- テスト件数は `def test_` の数(概数)。TestEvalFolder は test_edit.py:1176-1507。
- 行番号は HEAD 1b27688。RS3 が先に進むと ed_learn・ed_relink・ed_misc の行番号は動くので、着手前に関数名で引き直す。
