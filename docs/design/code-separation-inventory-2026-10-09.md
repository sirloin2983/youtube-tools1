# 棚卸し: ツール本体に混ざっている、AI のテスト・測定のための物(2026-10-09)

> 状態(2026-10-09): **資料**(読むだけのサブエージェント 5 体の報告をそのまま。行番号は HEAD 8c7ad56 の時点)。計画は `plan/code-separation.md`。種類: T = テストの都合 / M = 測定・記録の都合(M-記録 = 画面が読まない・M-画面 = 画面のある測定の機能)/ D = 開発者向けの見本・検査。「要確認」は推測を含む。

## 1. src/home(本体 19,030 行: py 16,166・js 2,431・html 433)
- 結論: M(確定)約 1,360 行(7%)・M(要確認)約 170・T 約 40・D 0。差し込み口(コンストラクタ引数・属性)約 110〜150 行は普通の依存の差し込みで残す。
- テスト用の環境変数は本体にほぼ無い(`intake.py:152-153` の `STUDIO_FAKE` だけ)。偽の録画元・偽ワーカーは `tests/fake_excite_worker.py`・`tests/fake_ytdlp_chat.py` にあり本体は差し込み口だけ。

### M(測定・記録)
| 種類 | ファイル:行 | 何か | 使う側 | 行数 | 分け方の案 |
|---|---|---|---|---|---|
| M(画面あり) | accuracy.py:1-543 全体 | dev/eval_asr・marks・speakers・cut・alt を夜に子プロセスで流し、結果の要約と「始める条件」goals を `app/accuracy-state.json` に書く | 画面: 調子の精度行・始める条件・「精度を今すぐ測る」(portal.js:1636-1695、portal.html:176)。test_accuracy.py、dev/tests/test_eval_asr.py:789 | 543 | 「測る道具の自動運転」なので dev 側が筋。画面ごと消すか残すかをユーザーが決める |
| M | accuracy.py:262, 524-527, 513-514, 18 | `heavy_enabled=False` 固定の `_heavy()` 空関数。到達しない | なし | 約 8 | 消す |
| M(画面あり) | accuracy.py:58-67 `GOALS`、212-230 `goals_of`、178-209 `count_daily` | 各工程の「あと何本・何分」。しきい値を dev/eval_* と二重に持つ | 画面(goalsRow)、test_accuracy | 約 70 | accuracy と一緒 |
| M | launch.py:25-26, 83, 544, 552, 758-762, 862-864, 871, 878-910, 1056, 1124, 1317 | `/api/accuracy`・`/api/accuracy/run`、`_accuracy_busy`・`_accuracy_last_edit`、起動・終了の配線 | 画面、test_launch | 約 52 | accuracy を分けるなら 1 か所に |
| M | health.py:266-271, 352-356 / 152-155 | `accuracy_probe` を調子に載せる。`count_autorun_failed` から post_analyze を除外 | 画面、test_health | 約 12 | accuracy・post_analyze と一緒 |
| M | prefs.py:10, 45-46, 71, 152-166, 355 / settings/schema.json:28-31 / settings/settings.js:26 | 設定の節 `accuracy` | 設定画面、test_settings_schema | 約 25 | accuracy と一緒 |
| M(画面あり) | portal.js:1636-1695、1521 の info 札。post_analyze の札 portal.js:32-35, 908-918, 1790, 1861-1878 | 精度の表示・あとから解析の札 | 画面 | 約 85 | 画面ごと消すか残すか |
| M | live_report.py:1-240 全体 + live.py:83, 295, 1127 | 配信ごとの結果を `live/reports/<録画元>__<録画>.json` に 60 秒ごとに書く | dev/eval_marks.py --live だけ。home に読み手無し。test_live_detect.py:1163-1203 | 243 | `samples` は録画中にしか取れないので移しにくい。`Reporter.all()`(227-240)はテスト専用 = 消せる |
| M | autorun.py 「あとから解析(測るため)」: 36-40, 68, 115-128, 378, 404, 460, 469-474, 534-557, 574, 582-585, 596, 896-921, 980, 999-1000, 1031, 1040-1249, 1251-1304 の分岐, 1430-1431 | 友人の依頼が区間だけで終わった配信を手が空いたら解析し直し、見逃しを測る。`autorun-deferred.json` | 画面は札だけ(portal.js:908-918)。launch.py:934-938。health.py。dev/eval_marks。test_autorun.py(1977, 2095-2096) | 約 290 | 「依頼が区間だけで終わった配信の videoId を残す」記録だけ本体に残し、解析し直す実行は dev の道具へ。`YTT_DEFER_ANALYZE=off` は止めるスイッチ |
| M | live_export.py:82-83, 477-485(`feedback()`)、live.py:889-890, 912-914、live_archive.py:971-975 と `compare` 引数、live_detect.py:623-662(`compare`)、cases.py:36, 362-381, 416-470, 499-528, 537-564(`_feedback_row`・`feedback` の引き回し) | `live_feedback.jsonl`(採用・届けた・要らない・期限切れ・detect_compare) | dev/eval_marks.py(838, 872, 951, 975)だけ。e2e_live_*、e2e_portal.py:1065-1084 | 約 100(compare 約 45) | `compare` は M そのもの。`feedback()` の口ごと「測定用の記録」へ |
| M | friend_feedback.py:21, 111-118 | `friend_feedback.jsonl` | dev/eval_marks.py:839, 866-880 だけ | 約 10 | 記録だけ分離。ごみ箱へ移す処理は本体 |
| M | live_tx.py:140-144 `items()` | live_report が成否を数えるためだけ | live_report、test_live_tx | 5 | live_report と一緒 |

### 要確認(利用者向けだが入力が測る道具の出力)
| 種類 | ファイル:行 | 何か | 使う側 | 行数 | 分け方の案 |
|---|---|---|---|---|---|
| 要確認 | autorun.py:129-138, 1434-1477(`_friend_length`)、1486-1489, 1499-1500 | 友人の依頼の自動の候補の長さを dev/eval_marks の最新の結果(`evals/marks/<日時>.json` の clipLength)から決める。設定 `autorun.friendLength`・`YTT_FRIEND_LENGTH` | schema.json:12。test_autorun.py:2306, 2413 | 約 65 | 本体で人の区間の長さを直接数える形にすれば dev から切り離せる |
| 要確認 | live_excite_worker.py:96-105, 290-362(`length_hint`・`clean_hint`・`spec_with_hint`)、live_detect.py:216, 219-225、`YTT_LIVE_LENGTH` | 配信中の候補の長さの目安(M10)。30 日より古い・見本が少ないときは使わない | test_live_detect.py:1540 | 約 100 | 同上。autorun と worker で同じ読み方が二重(`EVAL_MARKS_NAME_RE` も autorun.py:137 と worker 104) |
| 要確認 | autorun.py:81、prefs.py:17, 83, 288、settings/schema.json:46 | エンジンの選択肢に `qwen3-asr`・`llama.cpp` | 利用者の設定(live.auto.engine)。schema.json:121 の altEngine に Qwen3-ASR 1.7B | 約 5 | editor 側の公開状況と合わせて判断 |
| 要確認 | health.py:28 `CRASH_APPS` に `llama-server.exe` | 異常終了の数え対象 | 画面 | 1 | — |

### T(テストの都合)
| 種類 | ファイル:行 | 何か | 使う側 | 行数 | 分け方の案 |
|---|---|---|---|---|---|
| T | intake.py:152-153 | `STUDIO_FAKE=1` なら yt-dlp を呼ばず「疑似タイトル」 | 通る e2e は未特定 | 2 | `Intake(info=...)` の差し込み口があるので、通らないなら消す |
| T | live_report.py:227-240 `Reporter.all()` | 全記録を読む | test_live_detect.py:1202 だけ | 14 | 消す |
| T | autorun.py:1152-1156 `deferred()` | 「テストと、あとで画面に出すとき用」。画面は呼ばない | テストのみ | 5 | 消す |
| T | live.py:122-124, 136-137, 286 | `validate_url(allow_local)`・`allow_local_urls` | e2e_live.py:158 | 約 5 | 残す(属性で差し込む形) |
| T | launch.py:1157-1160 `make_server(start_port=0)`、271-279 `Supervisor(ports=)` | 空きポート・既定ポートの上書き | test_launch、e2e_* | 約 8 | 残す |
| T | launch.py:94-97 | analytics が無くても import を通す | 一時フォルダのテスト | 4 | 残す(正規の fallback) |
| T | settings/settings.js:171 `window.YttSettings` | e2e_settings.py が読む | e2e_settings.py | 1 | tests から取れる形に直せれば消す |
| T | mount.py:57-63 | `test_`・`e2e_`・`_` の部品名を除外 | 構造上必要 | 1 | 残す |
- 差し込み口(残す): live.py:255-282・285・279・1163-1164 / live_detect.py:133-141・246 / live_excite_worker.py:985-1000・412-417・399-402・1413-1414 / live_archive.py:368-398 / live_export.py:372-392 / live_cleanup.py:54-75 / live_tx.py:47-65 / accuracy.py:245-262 / autorun.py:534-557 / backup.py:207-213 / health.py:265-279 / intake.py:326-345 / appwindow.py:215 / restart.py:75-89 / cleanup.py:98 / clientlog.py:57 / live_requests.py:59 / deliver.py:317
- 分けると動きが変わる: accuracy を外すと夜の自動測定が止まり `evals/marks/*.json` が増えず、`_friend_length`・`length_hint` が 30 日で効かなくなる(**長さの機能を直接計算に直してから外す**)。post_analyze を外すと夜の解析し直しが無くなる(launch.py:934-938 の分岐・札・health の除外・`autorun-deferred.json` の読み込みも不要に)。live_report・feedback を外しても画面は変わらない(dev/eval_marks の `--live`・detect_compare・friend_feedback の入力が空になる)
- 分けられない理由: live_report は入口の非公開の物(`detector.view`・`heartbeat`・`_decisions`・`_load_fails`・`livetx.items`・`exporter.snapshot`・`requests.get`)を読む。accuracy は入口の SLOTS を見て「手が空いたとき」だけ流す(子プロセス)。cases.py の `feedback` 引数は `None` で動く形のままにすれば記録だけ外せる

## 2. src/studio(本体 11,365 行: py 5,707・js/html 5,658。ui-kit の写し除く)
- 結論: T 約 185・M 約 390・D 3 = 約 580(5%)。serve.py に偽の yt-dlp/ffmpeg や demo は無い(偽 yt-dlp の口は `exporter.py:513-515` だけ。demo は dev/demo_env.py)。`_pump` はテストが spy しているだけ。

| 種類 | ファイル:行 | 何か | 使う側 | 行数 | 分け方の案 |
|---|---|---|---|---|---|
| T | common.py:74-84, 621, 656 | `fake()`(`STUDIO_FAKE=1`)と `fake_media()`(`STUDIO_FAKE_MEDIA`)。`check_tools`・`env_state` の疑似分岐 | 下の「使い手」 | 13 | 判定は 1 か所のまま。中身を `studio/` 直下の別ファイルへ(`tests/` には置けない) |
| T | common.py:25-29 | `YTT_CORE_DIR` | dev/tests/e2e_pipeline.py:23、dev/_evalcommon.py:185、editor/ed_jobs.py:178 | 2 | 残す |
| T | serve.py:71-72 | `fetch_title` の疑似タイトル | test_api, e2e_ui | 2 | 疑似の別ファイルへ |
| T | serve.py:83-84 | `api_state` の `"fake"` キー(`hasKey`・`ytdlp` の `or fk`) | `settings.js:120` が「疑似モード(キー不要)」を表示。e2e_ui | 3 | fake キーと表示 1 行を同時に |
| T | serve.py:347 | `_config` の `or common.fake()` | test_api | 1 | 疑似の別ファイルへ |
| T | serve.py:440-444 | `make_server(0)` | test_api:30, test_handoff:164, test_robustness:307, test_rank_live:217 | 5 | tests 側で `StudioServer(("127.0.0.1",0),Handler)` と `serve._bound` に |
| 要確認 | serve.py:46 | `STUDIO_SOCKET_TIMEOUT` | 誰も設定しない。README にも無い | 1 | 決める |
| T | analyze.py:267-268, 411-421, 494, 579-585, 694-699 | 疑似の音声・チャット・コメント・付加情報(`STUDIO_FAKE_CHAT`・`_CHAT_DELAY`・`_COMMENTS`・`_META`)。`prefetch_chat` の疑似スキップ | e2e_analyze.py:31-77、home/tests/e2e_live_archive.py:736 | 27 | 疑似の別ファイルへ。`STUDIO_FAKE_CHAT_DELAY`(413-420)は使い手なし = 消す |
| T | analyze.py:24-25 | `excite` からの再公開(別名)。`CAP`・`SENS`・`LAG_MAX`・`LAG_MIN_CORR`・`LAG_MIN_CONTRAST`・`smooth`・`median`・`local_baseline`・`robust_scale`・`snap_quiet` は dead。`chat_score` は test_analyze.py:71 だけ | — | 2 | 消す(テストは `ytt_core.excite` を直接) |
| T | batch.py:88, 99 | `not common.fake()` | test_api, e2e | 2 | 疑似の別ファイルへ |
| T | exporter.py:204-205, 301 | `_youtube_source`・`build_spec` の疑似分岐 | test_exporter:819-826, test_api:887-899, e2e_live_archive, dev/demo_env | 3 | 疑似の別ファイルへ |
| T | exporter.py:513-515 | `_ytdlp_cmd()` | test_exporter:647, 734 | 3 | 残す(`find_tool` が単一パス) |
| T | exporter.py:32-33, 37-39 | 別名 `BASE_ROOM`・`safe_name`・`MAX_GAIN_DB` は使い手なし。`trim_units`・`_write_owner`・`TRUE_PEAK_CEIL` はテストだけ | test_exporter:322, 435-436, 537, 559 | 5 | 消す(テストは `ytt_core.names`・`loudness` を import) |
| T | exporter.py:949-950 | `unique=unique_base` | test_exporter | 2 | 残す |
| T | handoff.py:8 | `import http.client`(未使用) | — | 1 | 消す |
| T | rank.py:60-61, 102-208 | 疑似 YouTube Data API(`fake_get`・`fake_video`・`fake_live`・`fake_channel_id`・`_FAKE_INDEX`) | STUDIO_FAKE=1 の全テスト、dev/demo_env.py、dev/ui_audit.py | 109 | 疑似の別ファイル(studio/ 直下)へ。rank.py は `yt_get` の 2 行だけ |
| T | review.js:96, 3514 / queue.js:97 / settings.js:120 | `ytReadyMs`・`setYtReadyMs`(e2e_ui.py:778)。`STUDIO_FAKE_MEDIA` の失敗説明。疑似モードの表示 | 同左 | 4 | setYtReadyMs は残す |
| M | analyze.py:136-262, 31, 41, 57-58 | `feedback.jsonl` の書き込み(adopt/reject/delete/export + manual_add/manual_remove/unadopt/delete_judged。`nearest_auto`。32MB で `.old`) | dev/eval_marks.py だけ。書く側は store.py。test_robustness, test_api:595/919, test_analyze | 131 | 測定の記録へ |
| M | store.py:714-742, 749-754, 905-908 | `put_video`・`mark_exported` の判定記録の集計と呼び出し | 同上 | 約 41 | 一緒に |
| M | store.py:164, 183-184, 203-204, 776, 814, 818, 827 | `adoptedBy` | dev/eval_marks.py:261, 348, 366, 514, 685 | 約 12 | 一緒に |
| M | store.py:161, 200-202, 847-854 | `auto0Orig`(`auto0`・`_auto0` 129-134 は `_touched` が使うので本体) | dev/eval_marks.py:258 | 約 8 | 一緒に |
| M | analyze.py:744-779, 945-958, 37, 1012 | `archive/<動画ID>.json.gz` | dev/eval_marks.py:144。README:525。test_analyze:194-217 | 52 | 入り切りに |
| M | analyze.py:637-741, 38-40, 994-996, 932-942, 962-966, 1016-1017 | 動画の付加情報 `yt-dlp -J`(ヒートマップ・チャプター・タグ。「記録用」) | archive の `meta` と `result.counts.meta/heatmap` だけ | 約 126 | 消すか入り切りに(解析ごとの通信が 1 回減る) |
| M | analyze.py:806-808, 810, 834-846, 632-633, 917-918, 1002 | `parse_chat` の `extra`・コメント本文 `ctexts` | `_save_record` だけ | 約 18 | archive と一緒 |
| M | batch.py:281, analyze.py:149 | `analysis["type"]` は常に None の残骸 | なし | 2 | 消す |
| 要確認 | exporter.py:89 | `verify_output` が `export-log.txt` へ映像情報を 1 行 | 不明 | 1 | 決める |
| D | review.js:191, 195, 196 | `data-ui-audit-allow` | dev/ui_audit.py:362、test_review.cjs:1196 | 3 | 残す |
- STUDIO_FAKE の使い手: studio/tests(test_api, test_handoff, test_rank_live, test_robustness, e2e_ui, e2e_review, e2e_analyze)・home/tests(e2e_autorun, e2e_keymap, e2e_live_archive, e2e_live_studio, e2e_window, e2e_portal, test_mount, test_launch)・dev(e2e_pipeline, e2e_datadir, demo_env.py:177-183)・src/home/intake.py:152。環境変数名は変えない
- 疑似の中身を `tests/` に置けない理由: `home/tests/test_launch.py:940-943` の `_copy_tool` は tests を除いて写す。dev/demo_env.py と home の e2e はその写しを `STUDIO_FAKE=1` で動かす。置き場は `studio/` 直下(`mount.py` が sys.path にツールのフォルダを足す)
- `tests/test_review.cjs` は review.js を文字列の境目で切り出す(`between()` 56・`load([...])` 21・`sliceOf()` 11。queue.js・rank.js・core.js・settings.js も)。review.js:107・624・653・2737 はそのための防御。分けるなら review.js のファイル分割 + export(CSP と IIFE の大工事)

## 3. src/editor の Python(本体 16,191 行。ed_jobs 2,800・ed_speakers 1,510・ed_learn 1,312・tx_engines 1,185・ed_store 1,091・ed_relink 1,058・ed_evalbatch 881・serve 847)
- 結論: T 約 350・M(画面が読まない)約 780・M(画面あり)約 2,650・Qwen3 約 70・D 0。

### T
| 種類 | ファイル:行 | 何か | 使う側 | 行数 | 分け方の案 |
|---|---|---|---|---|---|
| T | tx_worker.py:135-202, 313-314 | `install_fakes`(偽の faster_whisper `FakeWhisper`・`TRANSCRIBE_FAKE_DELAY`・`TRANSCRIBE_WORKER_CRASH`・`TRANSCRIBE_FAKE_VAD`・偽の判別・偽の whisper-cli・SenseVoice/LlamaText への `FAKE_TEXT`/`FAKE_REPLY`)と `if S.worker_fake()` | test_worker, e2e_ui_mounted, test_fill, test_llm | 約 70 | `worker-fake` のときだけ差し込みファイルを import |
| T | ed_state.py:194-196, 475-482, 380-381, 455 | `fake_sleep`・`backend_name()`・`worker_fake()`、`has_faster_whisper`・`gpu_ready` の fake 分岐 | 全 e2e/単体 | 約 15 | 環境変数の読みをここ 1 か所に(今は ed_jobs・ed_speakers・ed_alt・ed_misc・ed_llm・ed_fill・serve が各自判定) |
| T | ed_jobs.py:1775-1787, 1816-1817 | `transcribe_fake`・`run_job` の fake 分岐 | 疑似の全テスト | 約 16 | 登録の口(`BACKENDS`)を 1 つ作り分岐を消す |
| T | ed_jobs.py:2466-2467, 2485-2488 | `run_redo` の fake 分岐(`TRANSCRIBE_FAKE_REDO` = 使うテスト 0) | — | 約 7 | 消す |
| T | ed_jobs.py:2502-2511, 2521, 2526, 2542-2543, 2565-2568, 2586-2610 | `_fake_spans`・`RangeRecognizer` の `fake`/`_fake`(`TRANSCRIBE_FAKE_GAP`/`LOOSE`) | test_worker | 約 45 | サブクラスで差し替え |
| T | ed_jobs.py:2777-2785, 1466-1471, 904 | `_retranscribe_each` の fake・`_run_base` の engine="fake"・`check_engine` の worker_fake | 同上 | 約 15 | 同上 |
| T | ed_speakers.py:63-64, 104-105, 229-241, 397-398, 614-616, 899-903, 1122-1123, 1130-1143, 1398-1402 | `diarize_fake`・`embed_fake` と fake 分岐 | test_voices, test_autodiar, test_worker | 約 46 | tx_worker の偽物と一緒に移す |
| T | ed_alt.py:66-70, 115-116, 132-145, 148-150, 167-168, 187-188 | `_alt_fake`(`TRANSCRIBE_FAKE_ALT`)・`body["fake"]=True` | test_alt, e2e_alt | 約 27 | 同上 |
| T | ed_llm.py:250-252 / ed_fill.py:296-298 / ed_misc.py:61-65, 83, 85, 97, 104-106 | `TRANSCRIBE_FAKE_LLM`・`TRANSCRIBE_FAKE_FILL`・abtest の `_fake_hyp` | test_llm, test_fill, e2e_fill, abtest | 約 22 | 同上 |
| T | tx_engines.py:286, 949, 824-831, 846-847, 870-871, 892-900, 1140-1166 | `WhisperCpp.COMMAND`・`LlamaQwen3.COMMAND`・`SenseVoice.FAKE_TEXT/_fake`・`LlamaText.FAKE_REPLY` | test_whispercpp, test_qwen3, test_fill, test_llm | 約 30 | 偽エンジンのクラスを移し `ENGINES` に tests が登録 |
| T | ed_evalbatch.py:874-881 `eb_shutdown` | 裏スレッドを止める(「テスト用」) | test_evalbatch, test_autodiar | 8 | tests のヘルパーへ |
| T | ed_jobs.py:1658-1660 `read_asr`・ed_llm.py:319-322 `read_llm`・pipeline_io.py:276-283 `read_runtime_entries`・ed_retime.py:61-76 `subread_mark` | テストだけが使う読み関数。`subread_mark` は JS との規則の一致の契約 | test_records, test_llm, test_backend, test_retime | 約 30 | tests へ(`subread_mark` は契約テストとして) |
| T | serve.py:157-163 `_ServeModule.__delattr__` | `mock.patch.object` が戻すための転送 | tests | 7 | tests 側へ |
| T | serve.py:88-90, 705-706・pipeline_io.py:19-28・resolve_export.py:84・ed_ytcap.py:137-143・ed_state.py:40-41 | `YTT_CORE_DIR`/`TRANSCRIBE_STUDIO_DATA`/`TRANSCRIBE_MARKER_DATA`/`YTT_CUT2RESOLVE_DIR`/`TRANSCRIBE_YTDLP` | e2e、test_ytcap | 約 20 | フックを 1 か所に(未設定なら今と同じ) |
| T/逃げ道 | ed_relink.py:216-218 `norm_enabled`・ed_speakers.py:893-895 `autodiar_enabled` | `TRANSCRIBE_NORMALIZE=off`・`TRANSCRIBE_AUTO_DIARIZE=off` | test_normalize30, test_autodiar, e2e | 約 7 | 利用者が使うなら残す |

### M-記録(画面が読まない。読むのは dev かテストだけ)
| 種類 | ファイル:行 | 何か | 使う側 | 行数 | 分け方の案 |
|---|---|---|---|---|---|
| M | ed_evalaudio.py 全体(1-352)、serve.py:244, 762 | 評価用のフォルダの動画から 16kHz の flac を `eval-audio/` に作る裏スレッド・`GET /api/eval-audio`。**読む所が無い**(dev は元の動画か `dataset/docs/<id>/full.flac`。backup.py の「写す」指定だけ) | test_evalaudio、backup のテスト | 352+6 | 消す(S1) |
| M | ed_jobs.py:1433-1445 `CONF_KEYS`/`machine_conf`、1636-1661 `capture_raw`/`write_asr`、1823・1865-1868・1908・2153・2318 | `original` の avg_logprob 等・`<id>.asr.json` | dev/eval_asr(byConfidence), eval_timing --apply, eval_fill, eval_llm | 約 60 | 書く側を 1 か所へ。止めると過去分の測り直しが新しい文書でできなくなる |
| M | ed_jobs.py:1447-1556(`pkg_version`・`engine_version`・`_run_base`・`recognition_run`・`post_record`・`short_hash`・`roster_hash`・`dict_version`)、1610-1622(`context_record`・`vad_record`)、1917-1930, 1836-1846 | `recognition.runs` の詳細。本体が読むのは **最初の記録の engine と model だけ**(ed_alt.py:91 `alt_first_run`、ed_retime.py:270) | dev/eval_*, test_records | 約 140 | engine/model だけ残して他は記録の 1 か所へ |
| M | ed_jobs.py:1558-1607 `replaced_rows`・`record_rerun`、2120, 2265, 2431-2436、ed_evalbatch.py:830-833 | `runs[].replaced`(**読む所が無い**)。`record_rerun` は `doc.pop("evalReviewed")`(1587)も担当 = 本体 | test_records, test_drill | 約 50 | 印を外す 1 行だけ残して蓄積は消す(S1) |
| M | ed_jobs.py:1320-1329 `END_TRIM`/`TRIM_GAP`/`TRIM_MIN`、1307-1308, 1412-1422 `trim_ends` | 既定で無効(END_TRIM=0)の行末を早める処理。dev/eval_timing の VARIANTS だけ | dev/eval_timing, test_whispercpp | 約 20 | dev へ移し本体は削除(S1) |
| M | ed_jobs.py:870-875 `ENGINE_DIR`・`engine_home` | `TRANSCRIBE_ENGINE_DIR`。`ENGINE_DIR` 変数は誰も設定しない | dev/eval_asr.py:880 | 約 6 | `ENGINE_DIR` は消す。環境変数は `load_serve` 側へ |
| M | ed_speakers.py:171-187, 190-211, 229-232、tx_worker の `_op_diarize` の tune | 話者判別の設定(`threshold`・`min_on`・`min_off`)を変えて測る引数 | dev/eval_speakers | 約 35 | dev 側で包む |
| M | ed_learn.py:227-228, 266-315(`is_overlap_group`・`overlap_orders`・`overlap_best_counts`) | 重なりのまとまりの精度の数え方。本体は使わない | dev/eval_asr, test_nosub_metrics | 約 52 | dev か ytt_core の測定部品へ(S1) |
| M | ed_store.py:497-545(`add_effort`・`effort_rows`)、463-465, 483-487、ed_drill.py:241、serve.py:309, 44、app-learn.js:179-201 | 校正の手間。画面は送るだけ。`effort.lastAt` は ed_evalbatch.py:558・ed_drill.py:92 が使う = 本体 | dev/eval_effort | 約 60 | 秒・行数は記録へ。`lastAt` は残す |
| M | ed_store.py:96-128(`proofedAt`)、ed_jobs.py:2130 | 初めて校正済みにした時刻。ed_drill.py:280-294 `drill_unreviewed` が使う | dev/eval_*, ed_drill | 約 15 | ドリルを残すなら残す |
| M | ed_store.py:630-660(`sanitize_draft`)、679-681, 848-876、cut.js:188 | カットのたたき台の記録 | dev/eval_cut | 約 45 | 記録へ(画面の `noteDraft` も) |
| M | ed_llm.py:304-316 `llm_write`・`llm_path`、ed_jobs.py:1869-1871、serve.py:595 | `<id>.llm.json` | dev/eval_fill | 約 15 | 記録へ |
| M | ed_llm.py:256-257 | `if ed_jobs.IN_WORKER:` | dev/eval_llm, eval_asr, _evalcommon.load_serve | 2 | `load_serve` 側で差し替え |

### M-画面(画面があり、目的は測定)
| 種類 | ファイル:行 | 何か | 使う側 | 行数 | 分け方の案 |
|---|---|---|---|---|---|
| M(画面) | ed_evalbatch.py 全体(881)、serve.py:245, 300-303, 761 | 評価用の動画のまとめての文字起こし・作り直し・話者判別の後追い | app-tools.js:254-320, app-learn.js:426 | 881 | 測定のツール(src/eval/)へ |
| M(画面) | ed_drill.py 全体(426)、serve.py:237-239, 311-312 | 評価ドリル・定点・確かめ済み・話者の候補 | app-learn.js:265-500 | 426 | 同上 |
| M(画面) | ed_relink.py:502-1058 | 評価用のフォルダの整理・仮置き・取り込み・`eval_name_guard`・`in_eval_dir`(ed_store・ed_jobs・ed_alt・ed_ytcap からも) | app.js:1077, app-tools.js:254-260 | 約 557 | `in_eval_dir` は ytt_core へ、整理は src/eval/ へ |
| M(画面) | ed_learn.py:667-906(CER・`doc_metrics`・`all_metrics`・`record_baseline`)、serve.py:233, 287 | 認識精度の測定・基準の記録 | app-learn.js:233-243, app.js:456。dev/eval_asr が `norm_cer`・`lev_counts`・`_groups` を共用 | 240 | 採点の関数は ytt_core か専用ファイルへ |
| M(画面) | ed_misc.py:17-158(`validate_abtest`・`run_abtest`・`read_eval`・`list_evals`) | 設定の比較(A/B) | app.js:502, app-tools.js, app-learn.js:555 | 142 | 要確認 |
| M(画面) | ed_learn.py:907-997 `export_corrections` | 修正データの zip(追加学習用) | app.js:318 | 91 | 要確認(消す候補) |
| M(画面) | ed_learn.py:998-1312(`archive_*`・`dataset_stats`)、serve.py:240, 289 | データの保管(校正の成果と音声を `dataset/` へ。離れたとき自動) | app.js:505-516、dev(`_evalcommon.audio_span`) | 315 | 要確認(自動を止める案が最小) |
| M(要確認) | tx_engines.py:503-516, 703-760(`Qwen3Asr`・`QWEN3_MODELS`)、home/prefs.py:83・autorun.py:81・settings/schema.json:46 | sherpa の Qwen3-ASR 0.6B。入口の `live.auto.engine` の選択肢に出ている。dev/eval_asr の `--engine` | 入口の設定・dev | 約 70 | 使わないなら消す。**`LlamaQwen3` は消せない**(ed_alt.py:39 の既定・`LlamaText` の親) |
- `evalSet` の分岐(本体に残す。`is_eval()` 1 か所に): ed_jobs.py:592-606, 636, 713-714, 1809, 1845-1860, 2003, 2304, 2357 / ed_store.py:139-149, 200, 237, 488-489, 1023-1025 / ed_speakers.py:913, 933-958, 1356, 1362, 1390 / ed_alt.py:93-98, 200, 408 / ed_ytcap.py:108-111, 124, 500 / ed_fill.py:151 / ed_learn.py:409, 857, 955, 1131, 1202, 1290(約 60 行)
- 分けられない: serve.py:119-167 の名前の受付(`_ED_MODULES`・`__getattr__`・`_ServeModule.__setattr__`)= tx_worker.py が `S.IN_WORKER = True` 等で使い、home/mount.py:207 も使う。`IN_WORKER` は本物のワーカーの旗。`LlamaQwen3`。`ed_learn` の採点関数は dev と画面と学習が共用

## 4. src/editor の JS・HTML(本体 約 9,046 行。ui-kit.js の写し除く)
| 種類 | ファイル:行 | 何か | 使う側 | 行数 | 分け方の案 |
|---|---|---|---|---|---|
| M | app-learn.js:179-205 / app.js:8,402,533 / app-rows.js:136 | 校正の手間(effortTick・effortStart・effortFlush → POST /api/effort)。画面は読まない | dev/eval_effort.py | 約 31 | 記録へ(サーバーの add_effort・/api/effort と一緒) |
| M(画面) | app-learn.js:263-504、app.js:190-194,272-277,773-776,815、app-core.js:242,509、app-tools.js:241,490-493、app-rows.js:47,918、app-jobs.js:338,505、index.html CSS 856-863・HTML 1430-1436・1542-1558・1595-1599 | 評価ドリル(?drill=1)。帯・「済みにして次へ」・Shift+D/N・定点・evalReviewed・redoOneHere・sessionStorage tx.drill | e2e_drill.py、e2e_eval_set.py | 約 306 | src/eval/ へ |
| M(画面) | app-jobs.js:492-546、app.js:188-189,200、index.html:1637-1642 | 「全行をこの人に(評価用)」(spAllGo、GET /api/drill/candidates) | e2e_drill.py | 約 64 | 同上 |
| M(画面) | app-tools.js:244-332、app.js:1066-1086、app-rows.js:126、app-core.js:491-495、index.html:1430,1982-2002 | 評価用フォルダの設定と整理・まとめての文字起こし・作り直し(evbStart・evbRedo・evalSettle・evalStat) | e2e_eval_set.py | 約 138 | 同上 |
| M(画面・要確認) | app-learn.js:230-261,535-566、app.js:453-461,476-506,1232、app-jobs.js:203-210,306、index.html:1471-1484 | 「認識精度の測定」カード(CER 約 40・基準 約 15・A/B 約 70) | e2e_proofread_accuracy.py | 約 125 | 同上 |
| 本体 | app.js:1057-1065,1088、app-tools.js:236-243、app-list.js:78,105,259、app-jobs.js:19、index.html:1420,1446,1592-1594 | 文書の「評価用」の印(学習・辞書から外す) | 画面・サーバー | 約 30 | 残す |
| T | app-core.js:453,457,464 | `t.backend === 'fake'` の「テスト用モード」の帯 | e2e_* | 3 | 共通の疑似の表示に |
| T | app.js:540 | `?nofs=1` | e2e_proofread_keys.py --nofs、e2e_ui_handoff.py | 1 | 残す |
| T | cut.js:1195 `_debug` / pack-tab.js:617 `state` | 使う側なし | — | 2 | 消す |
| D/要確認 | app-jobs.js:141 | `v.demo` の動画を飛ばす(書く側が無い) | — | 1 | 消してよいか |
| D | index.html:671,682,828,955,1069,1137,1151,1152,1201,1202 のコメント、app-tools.js:195、index.html:1631,1783 の `data-ui-audit-allow` | ui_audit の例外の印 | dev/ui_audit.py | 約 13 | 残す |
- test_document_save.cjs は名前で関数を取り出す(hhmm・docSaveP・setSaveState・saveDoc・showConflict・openDoc・docInfoText・setUrlDoc・setUrlParam・isBlankDraft・readChars・readLimits・readMark)。`subread_cases.json` はサーバーと画面の契約

## 5. src/ui-kit(3,617 行)
| 種類 | ファイル:行 | 何か | 使う側 | 行数 | 分け方の案 |
|---|---|---|---|---|---|
| D | styleguide.html(231)・styleguide.js(122) | 見本のページ(home/launch.py:533 は ui-kit.css/js しか配信しない = ユーザーは開けない) | dev/ui_audit.py:69,517,544、e2e_styleguide.py、README.md | 353 | dev/ へ(ui_audit の 3 か所と e2e のパスを直す。sync は写さない) |
| D | styleguide.js:73-75,86-88 の `window.__restartDemoOpts` 等 | テストが読む印 | e2e_styleguide.py | 約 5 | 一緒に |
| T | ui-kit.js:2179-2186,2203,2227 | restartRun/restartBand の interval・timeout・reload の引数(本番は渡さない) | e2e_styleguide.py:97-128 | 約 6 | 残す(明記) |
| D | ui-kit.js:1883-1885 `icon.names` | 見本とテストだけ | styleguide.js:18、e2e_styleguide.py:796 | 3 | 見本を移すなら見本側で参照 |
| D/要確認 | ui-kit.js:1462-1475,1534 `keys.helpHtml` | 見本だけが使う | styleguide.js:104 | 約 14 | 消す候補 |
- `tests/uikit_stub.cjs` は ui-kit.js を文字列の印(`  function esc(`・`  function pad2(`・`  /* ---- 入口の共通の API`・`window.UIKit = {`)で切り出す

## 6. src/cut2resolve(4,903 行)・src/recorder(1,259 行)
| 種類 | ファイル:行 | 何か | 使う側 | 行数 | 分け方の案 |
|---|---|---|---|---|---|
| T | cut2resolve/serve.py:62-64 | `YTT_CORE_DIR` | 各 e2e | 約 3 | 残す |
| T | cut2resolve/serve.py:245,251,828,844,848,852,856,868,875,878,906,910 | opener の差し込み | test_serve.py:72 | 約 11 | 本体は open_folder 固定、テストは mock.patch.object |
| T | cut2resolve/serve.py:854-856 | start_port=0 | test_serve.py:72 | 3 | 残す |
| T | cut2resolve/serve.py:881-886 | `_choose_work_dir` の「テストが差し替えていれば何もしない」 | test_serve.py:252 | 3 | テストの差し替え方を変えれば消せる |
| 要確認 | cut2resolve/auto_cut.py:195-242(run・main) | 採用区間 JSON からパックを作る CLI。画面・home・bat は使わない | test_cut2resolve.py:280、test_pack.py:671,839,1129 | 48 | 使わないなら消す(部品は pack.py が使う) |
| T | recorder.py:5,303-308,316-318 | `--source`・`--hls-time`・`--backoff`・`--idle-end`・`--stall-sec`・`YTT_RECORDER_SOURCE`(環境変数の口は使うテスト 0) | test_recorder.py:629-631、FAST(36) | 約 12 | テストの起動の道具へ |
| T | rec_core.py:10-12,119-120,132-135,745 | `direct`(偽の録画元。127.0.0.1 だけ許す) | test_recorder.py、hls_fixture.py | 約 8 | tests 側のサブクラスへ |
| T | rec_core.py:512-531,534-536,567,604-607,617-627,667-668 | direct の分岐(ENDLIST の終わりの判定・ffmpeg に q・stdin を閉じる・streamlink_ok) | 同上 | 約 35 | 本番の streamlink と同じコードを通るので動きの確認が要る |
| T | rec_core.py:649-658 | 時間を縮める引数 | FAST | 約 5 | 定数のまま属性で上書き |
| T | rec_core.py:653,773 | title_lookup を direct で None | test_recorder.py:558-605 | 約 2 | direct と一緒 |
| T | rec_core.py:279,281 | `new_rec_id(clock=)` | 使わない | 1 | 消す |

## 7. src/ytt_core(4,144 行)・dev(9,736 行)・テストの置き場所
| 種類 | ファイル:行 | 何か | 使う側 | 行数 | 分け方の案 |
|---|---|---|---|---|---|
| M | evaldata.py:1-339 | 評価用 zip の形式・検査・`judge`・`strip_marks` | dev/eval_import.py:37、dev/eval_asr.py:79,182-221。src からは 0 件 | 339 | dev/ へ(`test_evaldata.py` も。`__init__.py:27,31`・`AGENTS.md:47` を直す) |
| M | excite.py:278-307 `windowed_scores` | 一括の答え合わせ。本体は 0 件 | test_excite.py:134,160-162 | 約 30 | tests へ |
| T | excite.py:118-119 `chat_score` | 別名 | studio/analyze.py:25 → test_analyze.py:71 だけ | 2 | 消す |
| T | txindex.py:156-163 `use_packs_dir` | 非推奨 | test_ytt_core.py:1506-1515 | 8 | 消す |
| T | txindex.py:32,167-168 | `_cache` の注記・`YTT_CUT2RESOLVE_DIR` | editor/tests 5 本 | 約 3 | フックを 1 か所に |
| T | fsio.py:205-213 | `StampCache.__len__/__contains__/__iter__`(「テスト用」) | 要確認 | 9 | 本体で使っていなければテストが `_d` を見る形に |
| T | runtime.py:33-36 `runtime_dir`(`YTT_RUNTIME_DIR`) | 本体の読み手 15 か所。テスト 46 か所 | — | 4 | 1 か所のまま(editor/ed_misc.py:483・studio/handoff.py:39・launch.py:134 の写しは各ツール) |
| T | datadir.py:34,39-40,46-53,63-66 | `YTT_DATA_DIR=inplace`・`STUDIO_HOME`・`TRANSCRIBE_DATA_DIR` | 全サーバー系テスト 101 ファイル。docs/spec/data-location.md:26,61 は「元に戻したいとき用」とも | 約 10 | 残す(要確認) |
| T | datadir.py:69-75,94-97,202-204 `override` | — | 本体 6 か所 | 約 15 | そのまま |
| T | datadir.py:183,196,226 `prepare(free_bytes=)` | 空き容量の差し替え | test_ytt_core | 3 | 残す |
| T | jobs.py:32-38,42-46,66,108 | `limit_from_env(env)`・`HeavySlots(limit, reserved)`・`poll` | テスト | 約 8 | 残す |
| T | colors.py:22,31-35 `YTT_HOLO_MEMBERS` | — | cut2resolve/test_serve.py:696,905、home e2e_keymap/e2e_autorun/test_autorun、editor e2e_edit_common | 約 5 | フックを 1 か所に |
| T | colors.py:36-50 `_holo_file` | inplace のときホロカラーの作業データを読まない | 本体 | 約 6 | **消すとテストが本物の色を拾う** |
| T | tools.py:85-87 `kill_tree` の偽物の分岐、tools.py:193・normalize.py:243 の `popen=`、names.py:119 `clip_base(unique=)` | — | — | 6 | 残す |
- dev: M = eval_* 13 本 + _evalcommon 7,808(うち `accuracy.py:295` が子プロセスで呼ぶ eval_asr/marks/speakers/cut/alt + _evalcommon = 4,694 = **本体が dev に依存する唯一の線**)。D = demo_env 221 + ui_audit 775。本体寄り = push_helper 190(push.bat が呼ぶ)・dropbox_auth 164(ユーザーが 1 回実行)。AI 側 = lint 305・run_editor_suite 99・plan_artifact 66。sync_ui_kit 108(出力の写しは本体が読む)
- dev/tests に本体のテスト: test_resolve_pack_contract 774・e2e_pipeline 224・e2e_datadir 160・test_cleanup_legacy_data 133・test_setup_ascii 51
- テストの大きさ: ytt_core 3,010 / editor unittest 11,283 + cjs 217 + e2e 6,551 + 偽 274 / home 14,254 + e2e 5,013 + 偽 212 / studio 4,278 + cjs 1,208 + e2e 1,437 / cut2resolve 3,514 + lua 138 + fixtures / recorder 798 + 105 / analytics 423 / ui-kit cjs 60 + e2e 1,034 + stub 145 / dev 7,307 + e2e 384 / holo-colors C# 1,213 + e2e 528 / request-sender C# 1,584 / chrome-ext 79 + 174 = 約 65,500
- 環境変数のフック(本体が読む T。詳しくは各ツールの表): `YTT_DATA_DIR`・`YTT_RUNTIME_DIR`・`YTT_CORE_DIR`(studio/common.py:27-33・cut2resolve/serve.py:61-67・editor/serve.py:86-93・editor/pipeline_io.py:20-26・ed_jobs.py:178 = ytt_core を読む前なので集約不可)・`YTT_CUT2RESOLVE_DIR`・`YTT_HOLO_MEMBERS`・`STUDIO_HOME`・`TRANSCRIBE_DATA_DIR`・`TRANSCRIBE_STUDIO_DATA`・`TRANSCRIBE_MARKER_DATA`(e2e_folder_marker_range だけ)・`TRANSCRIBE_BACKEND`・`TRANSCRIBE_FAKE_DELAY/VAD/GAP/LOOSE/REDO(死)/ALT/FILL/LLM`・`TRANSCRIBE_WORKER_CRASH`・`TRANSCRIBE_YTDLP`・`TRANSCRIBE_NORMALIZE/AUTO_DIARIZE/EVAL_BATCH/EVAL_AUDIO`・`TRANSCRIBE_ENGINE_DIR`(eval_asr だけ)・`STUDIO_FAKE/_MEDIA/_CHAT/_COMMENTS/_META/_CHAT_DELAY(死)`・`YTT_RECORDER_SOURCE`(死)・`YTT_APP_BROWSER`・`YTT_DEFER_ANALYZE`。テスト内で閉じている物(`YTT_TEST_RESTART_*`・`YTT_E2E_NOGUARD`・`YTT_PREFS`・`FAKE_*`)は本体が読まない
- 名前の差し替え(本番でも使う本物の関数): `exporter._pump`(studio/exporter.py:372)・`live_archive.run_proc`(home/live_archive.py:135)・`A._pause`・`tools.find_tool`・`http.client.HTTPConnection`
