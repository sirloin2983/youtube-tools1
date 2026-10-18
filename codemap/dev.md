# コードの地図: dev・setup(開発の道具)

自動で作った物(`python dev/code_map.py`)。手で直さない。目次は [index.md](index.md)。`file:line` の行の番号は作った時点の物。

## dev/

- **build_friend_zip.py** (658 行) — 友人の PC に配る zip(新しいアプリ FriendApp + ② + ① の Python のコード + 埋め込み用 Python + 部品)を作る道具(F1 の F4a。設計 notes:docs/design/f1-build.md の 2・3 節)。
  - 名前: `class BuildError` :97・`say` :101・`sha256_file` :105・`download` :118・`cached` :130・`wheel_pins` :165・`pip_download` :183・`wheels` :193・`unzip_into` :231・`lay_python` :256・`src_files` :277・`lay_src` :292・ほか 20
- **code_map.py** (467 行) — コードの地図と言葉の索引を作る道具(AI のセッションがコードの場所を早く見つけるため。2026-10-18)。
  - 名前: `git_files` :52・`skipped` :57・`is_test` :61・`read` :65・`one_line` :73・`comment_head` :85・`py_info` :112・`js_info` :143・`cs_info` :164・`info` :186・`layer_of` :199・`norm_route` :206・ほか 12
  - 受ける口: 
- **demo_env.py** (300 行) — 見本のデータで入口と3ツールを動かす(画面の見直し・画面の写真・手での確認用)。本物の作業データには触らない。
  - 名前: `run` :47・`make_media` :51・`seed` :65・`seed_check` :177・`main` :245
- **doc_state.py** (241 行) — 計画の資料の頭の `状態`・`線` を計画の正(保管庫の plan/data/)から決めて書く・食い違いを止める(2026-10-18)。
  - 名前: `plan_data` :27・`task_lines` :33・`decide` :42・`derived` :50・`front` :74・`read_props` :85・`write_props` :109・`read` :142・`write` :147・`plan_docs` :156・`check` :166・`sync` :203・ほか 1
- **drift_report.py** (176 行) — 資料どうし・資料とコードの食い違いをまとめて流し、1 枚の一覧(保管庫の plan/食い違いの一覧.md。自動)に出す(2026-10-18)。
  - 名前: `read` :31・`md_files` :36・`is_index` :45・`caps` :49・`entry_docs` :65・`sentences` :71・`duplicates` :91・`collect` :103・`render` :112・`cell` :133・`write_report` :138・`main` :155
- **dropbox_auth.py** (165 行) — 友人のアプリの Dropbox の鍵を作る(ユーザーの PC で1回だけ。標準ライブラリと ytt の fsio だけ)。
  - 名前: `make_verifier` :40・`challenge_for` :47・`authorize_url` :53・`token_request_body` :65・`exchange` :74・`extra_scopes` :95・`missing_scopes` :101・`write_config` :109・`main` :114
- **fetch_webview2.py** (75 行) — 友人のアプリ FriendApp.exe が使う WebView2 の部品(DLL 3 つ)を NuGet の公式パッケージから取る(F3-1。notes:plan/f1-friend-requirements.md の C-1-1)。
  - 名前: `have` :29・`extract` :38・`main` :54
- **friend_demo.py** (309 行) — 友人の受信箱(src/friendapp)を見本のデータで動かす(画面の見直し・ui_audit・手での確認用)。本物の作業データ・② には触らない。
  - 名前: `demo_fetch` :31・`demo_probe` :36・`class StubQueue` :41・`class StubEngine` :66・`demo_thumb` :93・`class DemoStreams` :102・`seed` :141・`write_demo_fetch` :211・`class DemoDownloader` :225・`demo_file` :238・`main` :248
- **friend_diag.py** (186 行) — 友人のアプリから届いた診断の記録を読む(ユーザーの PC。notes:docs/spec/friend.md の 13-11)。AI が原因を調べるときに流す。
  - 名前: `default_dir` :34・`prune` :45・`load` :59・`is_error` :82・`lines_of` :102・`main` :146
- **friend_preflight.py** (853 行) — 友人に配る zip を、配る前にこの PC で「友人の PC と同じ状態」にして通しで試す(配る前の検査。notes:docs/spec/friend.md の 13-11)。
  - 名前: `class Preflight` :65・`class Report` :69・`free_port` :95・`link_or_copy` :101・`unpack` :110・`break_fetch` :129・`place_models` :139・`mirror_map` :163・`lay_shim` :179・`friend_env` :189・`make_work` :215・`class Window` :238・ほか 24
- **friend_preflight_shim.py** (270 行) — 配る前の検査(dev/friend_preflight.py)の通信の差し替え。検査が、展開した写しの python/Lib/site-packages/sitecustomize.py として置く
  - 名前: `install` :246
- **guard_hook.py** (434 行) — Claude Code の PreToolUse のフック: 事故のもとになる操作を機械が断る(2026-10-18)。標準ライブラリだけ・速く。
  - 名前: `class Tok` :51・`tok` :56・`tokenize` :62・`pipelines` :137・`word_of` :155・`norm_path` :171・`is_main_checkout` :184・`generated_kind` :198・`check_kill` :216・`check_sed` :242・`git_sub` :255・`check_git` :271・ほか 9
- **land.py** (305 行) — 作業のブランチを main に入れ、版(src/ytt/version.py の VERSION と README.txt の見出し)を道具が 1 つ上げる(2026-10-18)。
  - 名前: `class Stop` :38・`git` :42・`main_worktree` :51・`bump` :62・`read_version` :67・`set_version` :74・`set_readme` :78・`needs_bump` :88・`read_file` :93・`write_file` :98・`pid_alive` :103・`class Lock` :121・ほか 5
- **land_gate.py** (318 行) — main に入れる前の関所(dev/land.py が版を上げる前に流す。2026-10-18)。単独でも流せる:
  - 名前: `layer_of_dir` :58・`dependents` :65・`select` :70・`pick_units` :89・`run_units` :96・`count_of` :107・`run_check` :113・`run_tool` :127・`table_folders` :139・`table_drift` :153・`git` :177・`worktree_of` :182・ほか 8
- **layer_map.py** (139 行) — 役割の層と、今のファイルの行き先(役割で組み直す計画 `notes:plan/done/role-restructure.md` の 7 節を機械で読める形にしたもの。RS0。RS6 a-0 で 5 つの層に)。
  - 名前: `layer_of` :119・`allowed` :129
- **lint.py** (400 行) — コードの見直しの合格の基準を測る道具(読むだけ。基準は `notes:docs/spec/code.md`)。
  - 名前: `walk` :61・`read` :69・`rel` :77・`is_test` :81・`class Corpus` :85・`py_files` :106・`has_mark` :113・`unused_imports` :118・`dead_names` :142・`long_functions` :155・`dup_helpers` :166・`js_dead` :182・ほか 7
- **members_channels.py** (151 行) — 名簿 friend-apps/holo-colors/members.json の JP・DEV_IS の各メンバーに YouTube のチャンネル ID(channel)を入れる・確かめる道具。
  - 名前: `read_text` :29・`targets` :34・`norm` :43・`fetch_rss` :48・`verdict` :69・`cmd_check` :81・`cmd_set` :106・`main` :140
- **notes_tool.py** (470 行) — 資料のフォルダ(Obsidian の保管庫の中。layout.notes_root())のパスの検査と、資料を動かす道具(2026-10-13)。
  - 名前: `vault` :44・`plan_data` :48・`data_files` :54・`rebuild_data` :71・`read` :79・`write` :84・`md_files` :89・`code_files` :97・`local_target` :105・`pseudo_link` :117・`unlink_prose` :132・`tag_spans` :149・ほか 9
- **plan_artifact.py** (543 行) — 資料の保管庫(layout.notes_root())の plan/ の HTML(index.html・user-tasks.html)を、claude.ai の Artifact(リンクで開けるページ。スマホでも見る)用に 1 枚ずつまとめる。
  - 名前: `read` :46・`inline_assets` :51・`main_fragment` :64・`parse_plan_js` :73・`link_paths` :103・`task_line` :118・`class Linker` :123・`line_page_name` :153・`line_groups` :157・`build_line_page` :172・`build_line_pages` :192・`build_index` :199・ほか 14
- **plan_data.py** (466 行) — 計画のデータ(保管庫の plan/data/。計画の正)を 1 件 1 ファイルで持ち、表示用の plan/data.js を集めて作る(2026-10-18)。
  - 名前: `plan_dir_default` :49・`data_dir` :53・`has_split` :57・`read_text` :63・`write_atomic` :68・`ordered_keys` :77・`dumps` :82・`slug` :86・`file_name` :105・`items` :113・`sort_key` :129・`main_version` :135・ほか 11
- **push_helper.py** (263 行) — push.bat の補助(2026-09-26)。標準ライブラリだけ。リポジトリ直下で git が使えることが前提。
  - 名前: `git` :61・`read_removals` :70・`tracked` :90・`apply_removals` :95・`staged_files` :115・`staged_blob` :121・`problems_for` :125・`check` :160・`notes_root` :179・`push_notes` :186・`main` :232
- **run_e2e.py** (140 行) — 画面テスト(e2e)の一式を 1 本ずつ流して、1 本 1 行(所要秒・OK/FAIL の数)で出す。一式の正はこのファイルの SUITE。
  - 名前: `label` :65・`summary` :70・`selected` :77・`run_one` :90・`main` :104
- **run_editor_suite.py** (100 行) — 「編集」まわりのテストをまとめて流し、結果の1行ずつを出す(段10 のコードの整理で、分ける前と後の結果を比べるため)。
  - 名前: `find_node` :26・`summary` :49・`main` :62
- **run_unit.py** (175 行) — unittest を層ごと・フォルダごとに流す道具(1 本ずつ別のプロセス)。リポジトリ直下で:
  - 名前: `find_files` :45・`matches` :60・`build_units` :77・`run_one` :95・`report` :110・`run_all` :118・`print_summary` :135・`main` :145
- **session_start.py** (442 行) — セッションの入口の要約(2026-10-18)。新しい AI のセッションが最初に流し、今の状態を 1 画面(150 行以内)で見る。
  - 名前: `cut` :50・`run` :55・`git` :65・`read` :69・`git_block` :79・`versions` :99・`worklog_block` :108・`boundary_dirs` :124・`boundary_notes` :132・`boundary_block` :147・`load_items` :161・`plan_block` :171・ほか 15
- **spec_check.py** (187 行) — 仕様(保管庫の docs/spec/)とコードの食い違いを探す(2026-10-18)。
  - 名前: `git_files` :38・`read` :44・`class Code` :52・`spec_files` :70・`live_lines` :79・`norm_api` :96・`clean_path` :104・`setting_keys` :109・`check` :125・`main` :171
  - 受ける口: 
- **ui_audit.py** (842 行) — 画面(UI)の見直しの合格の基準のうち、機械で測れるものを測る道具(読むだけ。基準は `notes:docs/spec/ui.md` の A)。
  - 名前: `class Findings` :101・`read` :117・`rel` :125・`screen_files` :129・`allowed` :138・`each_line` :143・`regex_starts` :151・`scan_string` :161・`scan_code` :175・`strip_js_comments` :225・`html_texts` :232・`py_strings` :247・ほか 19
  - 受ける口: `/api/info` :94
- **worklog.py** (280 行) — 作業の記録(保管庫の docs/worklog/)をセッションごとのファイルに分けて書き、週のまとめを集めて作る(2026-10-18)。
  - 名前: `worklog_dir` :56・`monday` :60・`week_name` :64・`read` :68・`write` :73・`front_matter` :78・`session_entry` :91・`sessions` :101・`auto_block` :108・`merge_week` :121・`update_index` :135・`build` :150・ほか 7
- **worklog.py** (280 行) — 作業の記録(保管庫の docs/worklog/)をセッションごとのファイルに分けて書き、週のまとめを集めて作る(2026-10-18)。
  - 名前: `worklog_dir` :56・`monday` :60・`week_name` :64・`read` :68・`write` :73・`front_matter` :78・`session_entry` :91・`sessions` :101・`auto_block` :108・`merge_week` :121・`update_index` :135・`build` :150・ほか 7
- **worklog.py** (280 行) — 作業の記録(保管庫の docs/worklog/)をセッションごとのファイルに分けて書き、週のまとめを集めて作る(2026-10-18)。
  - 名前: `worklog_dir` :56・`monday` :60・`week_name` :64・`read` :68・`write` :73・`front_matter` :78・`session_entry` :91・`sessions` :101・`auto_block` :108・`merge_week` :121・`update_index` :135・`build` :150・ほか 7

## dev/obsidian/graph-history-toggle/

- **main.js** (103 行) — Obsidian のプラグイン: グラフを「いつもの見え方」と「すべてのファイル」でボタン 1 つで切り替える(2026-10-13)。
  - 名前: `migrate` :16

## setup/

- **build_whisper_vulkan.py** (167 行) — whisper.cpp を AMD などの GPU(Vulkan)用に、この PC で作る(精度改善の計画 段2-2。build-whisper-vulkan.bat から呼ぶ)。
  - 名前: `say` :33・`fail` :37・`run` :43・`find_cmake` :50・`find_vulkan_sdk` :67・`rmtree_all` :77・`sha256` :90・`main` :98
- **cleanup_legacy_data.py** (167 行) — 以前の場所(各ツールのフォルダの中)に残った作業データを片付ける(段階4。notes:docs/spec/data.md)。
  - 名前: `plan` :52・`running_tools` :86・`to_recycle_bin` :97・`remove` :114・`main` :129

## テスト

- dev/tests/e2e_datadir.py — 作業データの置き場所(統合計画の段階4)の通し確認。本物の入口(src/app/server.py)を、以前の場所にデータがある状態で起動する。
- dev/tests/e2e_pipeline.py — 3つのツールをつないだ通し確認(疑似モード・一時フォルダ・空きポート)。
- dev/tests/test_build_friend_zip.py — dev/build_friend_zip.py(友人の PC に配る zip を作る。F1 の F4a)のテスト。ネットは使わない(偽のキャッシュ・取る関数は差し替えて呼ばれたら落とす)。
- dev/tests/test_cleanup_legacy_data.py — setup/cleanup_legacy_data.py(以前の場所に残った作業データの片付け)のテスト。本物の AppData・ごみ箱は使わない。
- dev/tests/test_code_map.py — dev/code_map.py(コードの地図と言葉の索引を作る道具)の部品のテスト。リポジトリ直下で:
- dev/tests/test_doc_state.py — 資料の食い違いの検査(dev/doc_state.py・dev/spec_check.py・dev/drift_report.py)のテスト。一時フォルダの偽の保管庫だけを使う
- dev/tests/test_dropbox_auth.py — dev/dropbox_auth.py(切り抜き依頼の鍵を作る)のテスト。通信はしない(urlopen を差し替える)。
- dev/tests/test_friend_diag.py — dev/friend_diag.py(届いた診断を読む道具)のテスト。一時フォルダだけ(本物の Dropbox は読まない)。
- dev/tests/test_friend_preflight.py — 配る前の検査(dev/friend_preflight.py・dev/friend_preflight_shim.py)と、build_friend_zip.py --publish の関所のテスト。
- dev/tests/test_guard_hook.py — dev/guard_hook.py(PreToolUse のフックの守り)のテスト。よくある命令を並べて、通す / 断るを確かめる。一時フォルダだけを使う
- dev/tests/test_land.py — dev/land.py(main に入れる・版を道具が上げる)のテスト。一時フォルダの git リポジトリと worktree だけを使う
- dev/tests/test_land_gate.py — dev/land_gate.py(main に入れる前の関所)と dev/worklog.py check(報告の型)のテスト。一時フォルダだけを使う(テストは流さない)
- dev/tests/test_layering.py — 役割の層の import の向きを守るテスト(役割で組み直す計画 `notes:plan/done/role-restructure.md` の 4 節 1。RS0)。
- dev/tests/test_lint.py — dev/lint.py(コードの基準を測る道具)の部品のテスト。リポジトリ直下で:
- dev/tests/test_no_src_workdata.py — YTT_DATA_DIR=inplace のとき、作業データ(ログ・起動中の印・書き出し先)が src の中にできないことを見張る。リポジトリ直下で:
- dev/tests/test_notes_tool.py — dev/notes_tool.py(資料のフォルダのパスの検査と、資料を動かす道具)のテスト。一時フォルダの資料のフォルダと git で確かめる
- dev/tests/test_plan_artifact.py — dev/plan_artifact.py(計画のページ plan/ を 1 枚の公開用 HTML に組む道具)のテスト。目次と Artifact 用の 1 枚・ホームの自動の部分・版と参照・図を見る。
- dev/tests/test_plan_data.py — dev/plan_data.py(計画のデータ plan/data/ の 1 件 1 ファイルと data.js の生成・仮決めの自動の確定)のテスト。一時フォルダだけを使う
- dev/tests/test_push_helper.py — dev/push_helper.py(push.bat の補助: ファイルの削除・コミット前の検査)のテスト。一時フォルダの git リポジトリだけを使う。
- dev/tests/test_resolve_pack_contract.py — Resolve パックの契約テスト(文字起こしの「Resolveパッケージ(zip)」と cut2resolve の Text+ パック)。
- dev/tests/test_run_e2e.py — dev/run_e2e.py(e2e の一式)の一覧が、リポジトリの e2e_*.py と食い違っていないかを確かめる。
- dev/tests/test_run_unit.py — dev/run_unit.py(層ごとに unittest を流す道具)の一覧の作り方と、1 本だけの実行。リポジトリ直下で:
- dev/tests/test_session_start.py — dev/session_start.py(セッションの入口の要約・子への指示文の下書き)のテスト。一時フォルダの git と偽の保管庫だけを使う
- dev/tests/test_setup_ascii.py — Windows の cmd・pip がシステムの文字コード(日本語の Windows では cp932)で読むファイルが ASCII だけか・.bat が CRLF かのテスト。
- dev/tests/test_worklog.py — dev/worklog.py(作業の記録のセッションごとのファイルと週のまとめ)のテスト。一時フォルダだけを使う
