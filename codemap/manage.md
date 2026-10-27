# コードの地図: ④ manage(データ)

自動で作った物(`python dev/code_map.py`)。手で直さない。目次は [index.md](index.md)。`file:line` の行の番号は作った時点の物。

## src/manage/

- **__init__.py** (2 行) — ④ データの管理。ytt・flow・human を import してよい(① pipeline は直に読まない = ② を通す)

## src/manage/cases/

- **__init__.py** (2 行) — ④ 案件(配信 1 本の束ね)・紐づけ(切り抜き ↔ 文字起こし ↔ パック)・成果物の鍵の読み取り
- **cases.py** (848 行) — 案件(配信1本)ごとの紐づけ(統合計画の段階4)。入口の「案件」画面(src/app/ui/home/portal.html)の中身を作る。
  - 名前: `locations` :84・`read_studio` :98・`clip_state` :139・`clip_live` :160・`auto_info` :174・`live_failures_by_mark` :193・`delivered_of` :227・`virtual_cases` :286・`build` :333・`load_saved` :382・`revision` :475・`snapshot` :496・ほか 6
- **doclist.py** (101 行) — ④ 文字起こしの一覧と、元の動画・パックの有無・前回のパックの手順(役割で組み直す RS3-E5a)。
  - 名前: `list_transcripts` :52・`pack_readme` :81
- **handoff_io.py** (125 行) — ④ 受け渡し: 元の配信の情報(clip/v1)・受け渡しの JSON と SRT を動画の隣に保存
  - 名前: `class PipelineError` :32・`written_by_us` :44・`save_beside` :58・`export_file` :96
- **outdirs.py** (168 行) — ④ 書き出し先を変えたあとの案件の繋ぎ直し(決定 3-37 の (r8o))と、入口の「調子」の「置き場所」の数。
  - 名前: `read_data` :33・`state_path` :39・`read_state` :43・`relink_problem` :55・`relink` :69・`relink_out_dir` :85・`status` :136・`main` :148
- **relink.py** (242 行) — ④ 文書と動画の紐づけ: 動画を選び直す(付け替え)・「参照…」・素材を 30fps にそろえる
  - 名前: `relink_path` :27・`relink_check` :68・`relink_doc` :124・`norm_swap` :191・`norm_start` :209・`pick_path` :230
- **txindex.py** (237 行) — 文字起こしの文書(文字起こしツールの transcripts/*.json)を、他のツールから**読むだけ**の部品(統合計画の段階4)。
  - 名前: `folder` :29・`norm` :35・`doc_paths` :92・`load` :103・`class Docs` :116・`summary` :146・`matches` :161・`pick` :165・`offset` :189・`lines` :209・`pack_dir` :214・`pack_info` :219・ほか 1
- **txlink.py** (37 行) — 書き出し済みのマークの「セリフ」(文字起こしツールで作った文字起こし)を、元の配信の時刻にして返す(統合計画の段階4)。
  - 名前: `tx_folder` :15・`for_video` :19

## src/manage/keep/

- **__init__.py** (2 行) — ④ 置き場所・バックアップ・ごみ箱・録画の片付け
- **backup.py** (648 行) — 作業データのバックアップ(notes:docs/spec/data.md の「バックアップ」)。
  - 名前: `skip` :71・`plan` :138・`plan_cases` :174・`default_media_dirs` :201・`media_rel` :215・`plan_media` :232・`same` :239・`copy_one` :247・`run_once` :279・`class Backup` :329・`restore_once` :548・`main` :596
- **cleanup.py** (457 行) — 作業データの片付け(全体の計画 段9 9-2。ユーザー決定: ごみ箱フォルダ経由・日数を決めて消す。10-24: 手で選ぶ画面をやめて自動だけ)。
  - 名前: `class Cleanup` :101
- **evalfolders.py** (514 行) — ④ 評価用のフォルダの整理: 動画の名前を「フォルダ名_番号_状態」にそろえる・仮置きからメンバーのフォルダへ移す・評価用にした文書の動画を外から取り込む
  - 名前: `eval_videos` :68・`norm_member` :99・`member_name` :104・`organizing` :111・`eval_members` :116・`eval_organize` :330・`eval_settle` :406・`eval_folders_info` :502
- **learnpack.py** (144 行) — ④ データ: 学習の束を作る側(F1。資料の git:before-1028-cleanup:docs/design/f1-build.md の 2 の F1・3 の (f1c))。
  - 名前: `roster_names` :41・`filter_voices` :51・`collect` :58・`content_sha8` :87・`versions` :95・`build` :104
- **live_cleanup.py** (246 行) — 録画を自動で消す(線 D。資料の git:before-1028-cleanup:plan/line-d-live-clipping.md の 0-9 の最後。ユーザー決定。決定 3-73)の入口の側。
  - 名前: `class Cleaner` :53
- **trash.py** (19 行) — ④ データの keep: 動画と一緒にごみ箱フォルダへ動かす途中のファイル(何を一緒に動かすか)。
  - 名前: `existing_sidecars` :16

## src/manage/ops/

- **__init__.py** (2 行) — ④ データの運用: 調子・起動し直し・エラーの記録・分析と日報(analytics/)。失敗の集約は ② にある
- **clientlog.py** (78 行) — 画面(ブラウザ・窓)で起きたエラーの記録(統合計画の段階7-0)。
  - 名前: `clean` :27・`class ClientLog` :39
- **health.py** (422 行) — 「調子」(全体の計画 段9 9-1)。
  - 名前: `top_items` :36・`data_sizes` :56・`disk_free` :87・`tool_version` :107・`tool_versions` :118・`count_jsonl` :141・`count_client_errors` :172・`crash_counts` :206・`count_worker_incidents` :251・`class Health` :280
- **restart.py** (206 行) — 入口を起動し直す(段9 9-3)。
  - 名前: `live_warning` :43・`launcher_script` :53・`restart_args` :58・`launcher_env` :72・`popen_kwargs` :77・`spawn_new_launcher` :92・`port_free` :118・`wait_port_free` :134・`wait_pid_gone` :145・`wait_old_launcher` :158・`can_restart` :181
- **watch.py** (166 行) — 元の配信とガイドラインの見張り(10-23。提案 P7・人の作業なしの候補の 13 番。表は保管庫 plan/人の作業なしの候補-1023.md)。
  - 名前: `enabled` :35・`delivered_sources` :40・`check_sources` :53・`terms_mark` :79・`class Watch` :86

## src/manage/ops/analytics/

- **__init__.py** (15 行) — analytics — チャンネルの分析と日報・週報・月報(設計 notes:plan/done/analytics-daily-report.md)。
- **bridge.py** (108 行) — Apps Script の連携(gas/Code.gs のウェブアプリ)との通信。標準ライブラリだけ。
  - 名前: `class BridgeError` :20・`check_url` :26・`check_secret` :33・`class Bridge` :50
- **calc.py** (1130 行) — 計算(notes:plan/done/analytics-daily-report.md の 4 節と 12-4 の方針)。入力は data.Dataset、出力は JSON にできる dict。
  - 名前: `confirmed` :40・`points` :50・`cum_at` :65・`covered` :75・`shorts_with_days` :80・`class Curve` :84・`quality` :148・`count_posts` :162・`posts_summary` :167・`ypp_now` :179・`class Model` :189・`ypp_checks` :259・ほか 35
- **data.py** (206 行) — raw(ブックマークが Studio の内部 API から取った JSON)→ 形をそろえたデータ。
  - 名前: `class DataError` :31・`class Video` :35・`class Dataset` :73・`member_matcher` :109・`parse` :129
- **render.py** (574 行) — 日報・週報・月報の LINE の文面と HTML(calc の結果 → 文字列)。
  - 名前: `esc` :15・`man` :19・`pct` :30・`usd` :37・`d_md` :41・`d_mdw` :45・`page` :76・`provenance` :84・`scenario` :92・`pool_keys` :97・`probs` :101・`prob_range` :105・ほか 22
- **service.py** (415 行) — 入口の中で動く「分析と日報」: 見張り(新しい raw を受け取って分析し LINE へ)・画面と API(/analytics/)。
  - 名前: `data_dir` :47・`class Service` :55
- **timeutil.py** (94 行) — 日付と時刻の定義(1 か所。監査の E2・E3・E4。notes:plan/done/analytics-daily-report.md の 12-4 の 2)。
  - 名前: `pt_offset` :21・`to_pt` :29・`pt_day_start_utc` :34・`parse_utc` :41・`day_from_int` :58・`jst_date` :67・`md` :71・`md_w` :76・`day_end_utc` :81・`elapsed_hours_at_day_end` :86・`add_months` :91

## src/manage/ops/analytics/web/

- **app.js** (153 行) — 分析と日報の画面。API は相対パス(api/…)。書き込みは合言葉(X-YTT-Token)付き(入口が <meta name="ytt-token"> で渡す)

## テスト

- tests/manage/cases/test_cases.py — 案件(配信1本)ごとの紐づけ(src/manage/cases/cases.py)と、入口の /api/cases のテスト。本物の作業データは使わない。
- tests/manage/cases/test_docloc_listing.py — 文書の一覧が、案件の 作業用 に置いた文書(索引 .loc.json があるもの)も拾うことの確かめ(RS8 B-2-1b)。
- tests/manage/cases/test_outdirs.py — 書き出し先を変えたあとの案件の繋ぎ直し(src/manage/cases/outdirs.py)の確かめ。
- tests/manage/cases/test_perf_listing.py — 案件の一覧の速さの工夫が、ふつうの経路と同じ結果を返すことの突き合わせ。
- tests/manage/keep/test_backup.py — 作業データのバックアップ(src/manage/keep/backup.py。設定は入口の Prefs を借りる。prefs の節の検査は tests/app/test_backup_prefs.py)の単体テスト。一時フォルダだけを使う。
- tests/manage/keep/test_cleanup.py — src/manage/keep/cleanup.py(作業データの片付け。段9 9-2。10-24 から自動だけ)の単体テスト。
- tests/manage/keep/test_learnpack.py — manage/keep/learnpack(学習の束を作る側)のテスト。  py -3.12 -m unittest tests/manage/keep/test_learnpack.py -v
- tests/manage/keep/test_live_cleanup.py — 録画を自動で消す(src/manage/keep/live_cleanup.py。「書き出し済み + アーカイブ化を確かめたら ごみ箱へ」)のテスト。
- tests/manage/keep/test_trash.py — src/ytt/trashbin.py のごみ箱へ移す・戻す(④ の片付けと「要らない」が使う 1 か所)の単体テスト。戻せなかった物の元の場所を必ず記録する。
- tests/manage/ops/test_clientlog.py — 画面のエラーの記録(src/manage/ops/clientlog.py の ClientLog・clean)の単体テスト。一時フォルダだけを使う。
- tests/manage/ops/test_health.py — src/manage/ops/health.py(「調子」)の単体テスト。
- tests/manage/ops/test_restart.py — 入口を起動し直す部品(src/manage/ops/restart.py)のテスト。  python -m unittest tests/manage/ops/test_restart.py -v
- tests/manage/ops/test_watch.py — 元の配信とガイドラインの見張り(src/manage/ops/watch.py。10-23 提案 P7)。本物の YouTube・ページには繋がない(偽の API と偽の取得)。リポジトリ直下で:
- tests/manage/ops/analytics/test_analytics.py — 分析と日報(src/manage/ops/analytics)のテスト。本物のチャンネルの数字は使わない(リポジトリは Public)。make_raw が規則どおりに伸びる架空のチャンネルを作る。
