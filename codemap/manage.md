# コードの地図: ④ manage(データ)

自動で作った物(`python dev/code_map.py`)。手で直さない。目次は [index.md](index.md)。`file:line` の行の番号は作った時点の物。

## src/manage/

- **__init__.py** (3 行) — ④ データの管理。ytt・flow・human を import してよい(① pipeline は直に読まない = ② を通す)

## src/manage/cases/

- **__init__.py** (3 行) — ④ 案件(配信 1 本の束ね)・紐づけ(切り抜き ↔ 文字起こし ↔ パック)・成果物の鍵の読み取り
- **cases.py** (910 行) — 案件(配信1本)ごとの紐づけ(統合計画の段階4)。入口の「案件」画面(src/app/ui/home/portal.html)の中身を作る。
  - 名前: `locations` :93・`read_studio` :107・`read_transcripts` :111・`find_pack` :116・`clip_state` :181・`clip_live` :204・`auto_info` :218・`live_failures_by_mark` :237・`delivered_of` :271・`virtual_cases` :331・`build` :405・`load_saved` :457・ほか 7
- **doclist.py** (108 行) — ④ 文字起こしの一覧と、元の動画・パックの有無・前回のパックの手順(役割で組み直す RS3-E5a。2026-10-10 に編集の文書の保存の部品から切り出した。中身は同じ)。
  - 名前: `pack_info` :21・`list_transcripts` :59・`pack_readme` :88
- **handoff_io.py** (118 行) — ④ 受け渡し: 元の配信の情報(clip/v1)・受け渡しの JSON と SRT を動画の隣に保存
  - 名前: `clip_info` :33・`export_file` :69
- **outdirs.py** (168 行) — ④ 書き出し先を変えたあとの案件の繋ぎ直し(決定 3-37 の (r8o))と、入口の「調子」の「置き場所」の数。
  - 名前: `read_data` :33・`state_path` :39・`read_state` :43・`relink_problem` :55・`relink` :69・`relink_out_dir` :85・`status` :136・`main` :148
- **pipeline_io.py** (164 行) — ツール間の受け渡し(notes:docs/spec/pipeline.md の約束 v1)のうち、読み・保存・.runtime を扱う部品(層 manage)。serve.py から呼ぶ。Python 標準ライブラリだけで動く。
  - 名前: `class PipelineError` :35・`load_clip_file` :55・`resolve_clip_media` :63・`written_by_us` :97・`save_beside` :111・`ping` :155・`siblings` :160
- **relink.py** (341 行) — ④ 文書と動画の紐づけ: 動画を選び直す(付け替え)・まとめて付け替える・「参照…」・素材を 30fps にそろえる
  - 名前: `relink_path` :31・`relink_check` :72・`relink_doc` :128・`norm_swap` :195・`norm_start` :213・`relink_missing` :242・`relink_folder` :266・`relink_find` :294・`pick_path` :329
- **txindex.py** (274 行) — 文字起こしの文書(文字起こしツールの transcripts/*.json)を、他のツールから**読むだけ**の部品(統合計画の段階4)。
  - 名前: `folder` :31・`norm` :37・`doc_paths` :94・`load` :105・`class Docs` :118・`summary` :148・`matches` :163・`pick` :167・`offset` :191・`lines` :211・`pack_dir` :216・`packs_dir` :221・ほか 6
- **txlink.py** (37 行) — 書き出し済みのマークの「セリフ」(文字起こしツールで作った文字起こし)を、元の配信の時刻にして返す(統合計画の段階4)。
  - 名前: `tx_folder` :15・`for_video` :19

## src/manage/keep/

- **__init__.py** (3 行) — ④ 置き場所・バックアップ・ごみ箱・録画の片付け
- **backup.py** (670 行) — 作業データのバックアップ(2026-10-03。notes:docs/spec/data.md の「バックアップ」)。
  - 名前: `skip` :71・`plan` :138・`plan_cases` :174・`default_media_dirs` :201・`media_rel` :215・`plan_media` :232・`same` :239・`copy_one` :247・`run_once` :279・`class Backup` :329・`restore_once` :557・`main` :618
- **cleanup.py** (502 行) — 作業データの片付け(全体の計画 段9 9-2。git の履歴(679ff01 以前)の docs/plan/phase9-ops-stability.md。ユーザー決定 2026-10-01: 元動画も候補に・ごみ箱フォルダ経由・日数を決めて消す)。
  - 名前: `class Cleanup` :123
- **evalfolders.py** (503 行) — ④ 評価用のフォルダの整理: 動画の名前を「フォルダ名_番号_状態」にそろえる・仮置きからメンバーのフォルダへ移す・評価用にした文書の動画を外から取り込む
  - 名前: `eval_organize` :319・`eval_settle` :395・`eval_folders_info` :491
- **learnpack.py** (163 行) — ④ データ: 学習の束を作る側(F1。notes:docs/design/f1-build.md の 2 の F1・3 の (f1c))。
  - 名前: `roster_names` :41・`filter_voices` :51・`collect` :58・`content_sha8` :87・`versions` :95・`build` :104・`verify` :147
- **live_cleanup.py** (264 行) — 録画を自動で消す(線 D。notes:plan/line-d-live-clipping.md の 0-9 の最後。2026-10-05 ユーザー決定・2026-10-16 に条件を変えた = 決定 3-73)の入口の側。
  - 名前: `class Cleaner` :57
- **trash.py** (124 行) — ④ データの keep: ごみ箱フォルダへ移す・戻すの 1 か所(OPT-M2。notes:plan/done/opt-manage.md の 7c-1・2c-1)。
  - 名前: `to_trash` :30・`record` :80・`put_back` :95

## src/manage/ops/

- **__init__.py** (2 行) — ④ データの運用: 調子・起動し直し・エラーの記録・分析と日報(analytics/)。失敗の集約は ② にある
- **clientlog.py** (86 行) — 画面(ブラウザ・窓)で起きたエラーの記録(統合計画の段階7-0)。
  - 名前: `clean` :28・`class ClientLog` :47
- **health.py** (398 行) — 「調子」(全体の計画 段9 9-1。git の履歴(679ff01 以前)の docs/plan/phase9-ops-stability.md)。
  - 名前: `top_items` :36・`data_sizes` :56・`disk_free` :87・`tool_version` :107・`tool_versions` :115・`count_jsonl` :133・`count_client_errors` :166・`count_autorun_failed` :171・`crash_counts` :207・`count_worker_incidents` :252・`class Health` :281
- **restart.py** (197 行) — 入口を起動し直す(段9 9-3。git の履歴(679ff01 以前)の docs/plan/phase9-ops-stability.md の「9-3」)。
  - 名前: `launcher_script` :44・`restart_args` :49・`launcher_env` :63・`popen_kwargs` :68・`spawn_new_launcher` :83・`port_free` :109・`wait_port_free` :125・`wait_pid_gone` :136・`wait_old_launcher` :149・`can_restart` :172

## src/manage/ops/analytics/

- **__init__.py** (15 行) — analytics — チャンネルの分析と日報・週報・月報(設計 notes:plan/done/analytics-daily-report.md)。
- **bridge.py** (108 行) — Apps Script の連携(gas/Code.gs のウェブアプリ)との通信。標準ライブラリだけ。
  - 名前: `class BridgeError` :20・`check_url` :26・`check_secret` :33・`class Bridge` :50
- **calc.py** (1146 行) — 計算(notes:plan/done/analytics-daily-report.md の 4 節と 12-4 の方針)。入力は data.Dataset、出力は JSON にできる dict。
  - 名前: `confirmed` :40・`day_end_utc` :48・`points` :54・`cum_at` :69・`covered` :79・`shorts_with_days` :84・`class Curve` :88・`quality` :152・`count_posts` :166・`posts_summary` :171・`ypp_now` :183・`class Model` :193・ほか 35
- **data.py** (209 行) — raw(ブックマークが Studio の内部 API から取った JSON)→ 形をそろえたデータ。
  - 名前: `class DataError` :31・`class Video` :35・`class Dataset` :73・`member_matcher` :109・`parse` :132
- **render.py** (574 行) — 日報・週報・月報の LINE の文面と HTML(calc の結果 → 文字列)。
  - 名前: `esc` :15・`man` :19・`pct` :30・`usd` :37・`d_md` :41・`d_mdw` :45・`page` :76・`provenance` :84・`scenario` :92・`pool_keys` :97・`probs` :101・`prob_range` :105・ほか 22
- **service.py** (441 行) — 入口の中で動く「分析と日報」: 見張り(新しい raw を受け取って分析し LINE へ)・画面と API(/analytics/)。
  - 名前: `data_dir` :46・`class Service` :54
- **timeutil.py** (89 行) — 日付と時刻の定義(1 か所。監査の E2・E3・E4。notes:plan/done/analytics-daily-report.md の 12-4 の 2)。
  - 名前: `pt_offset` :21・`to_pt` :29・`pt_day_start_utc` :34・`parse_utc` :41・`day_from_int` :58・`jst_date` :67・`md` :71・`md_w` :76・`elapsed_hours_at_day_end` :81・`add_months` :86

## src/manage/ops/analytics/web/

- **app.js** (153 行) — 分析と日報の画面。API は相対パス(api/…)。書き込みは合言葉(X-YTT-Token)付き(入口が <meta name="ytt-token"> で渡す)

## テスト

- src/manage/cases/tests/test_cases.py — 案件(配信1本)ごとの紐づけ(src/manage/cases/cases.py)と、入口の /api/cases のテスト。本物の作業データは使わない。
- src/manage/cases/tests/test_docloc_listing.py — 文書の一覧が、案件の 作業用 に置いた文書(索引 .loc.json があるもの)も拾うことの確かめ(RS8 B-2-1b)。
- src/manage/cases/tests/test_outdirs.py — 書き出し先を変えたあとの案件の繋ぎ直し(src/manage/cases/outdirs.py。決定 3-37 の (r8o))の確かめ。移行の道具(docmove・markmove の移す所)は消した。
- src/manage/cases/tests/test_perf_listing.py — 案件の一覧の速さの直し(PERF O5・O15)が、前の実装と同じ結果を返すことの突き合わせ。
- src/manage/keep/tests/test_backup.py — 作業データのバックアップ(src/manage/keep/backup.py。設定は入口の Prefs を借りる。prefs の節の検査は src/app/tests/test_backup_prefs.py)の単体テスト。一時フォルダだけを使う。
- src/manage/keep/tests/test_cleanup.py — src/manage/keep/cleanup.py(作業データの片付け。段9 9-2)の単体テスト。
- src/manage/keep/tests/test_learnpack.py — manage/keep/learnpack(学習の束を作る側。F1)のテスト。  py -3.12 -m unittest src/manage/keep/tests/test_learnpack.py -v
- src/manage/keep/tests/test_live_cleanup.py — 録画を自動で消す(src/manage/keep/live_cleanup.py。線 D の 0-9 の最後。LD-1 で「書き出し済み + アーカイブ化を確かめたら ごみ箱へ」)のテスト。
- src/manage/keep/tests/test_trash.py — src/manage/keep/trash.py(ごみ箱へ移す・戻すの 1 か所。OPT-M2)の単体テスト。設計原則の指摘 1 = 戻せなかった物の元の場所を必ず記録する。
- src/manage/ops/analytics/tests/test_analytics.py — 分析と日報(src/manage/ops/analytics)のテスト。本物のチャンネルの数字は使わない(リポジトリは Public)。make_raw が規則どおりに伸びる架空のチャンネルを作る。
- src/manage/ops/tests/test_clientlog.py — 画面のエラーの記録(src/manage/ops/clientlog.py の ClientLog・clean)の単体テスト。一時フォルダだけを使う。
- src/manage/ops/tests/test_health.py — src/manage/ops/health.py(「調子」。段9 9-1)の単体テスト。
- src/manage/ops/tests/test_restart.py — 入口を起動し直す部品(src/manage/ops/restart.py。段9 9-3)のテスト。  python -m unittest src/manage/ops/tests/test_restart.py -v
