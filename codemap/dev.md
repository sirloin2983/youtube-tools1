# コードの地図: dev・setup(開発の道具)

自動で作った物(`python dev/code_map.py`)。手で直さない。目次は [index.md](index.md)。`file:line` の行の番号は作った時点の物。

## dev/

- **_common.py** (38 行) — dev/ の道具が共通で使う小物(標準ライブラリだけ)。guard_hook.py・push_helper.py は単独で動く条件なので、ここを読まない。
  - 名前: `find_node` :8・`read_utf8` :21・`write_utf8` :27・`tracked_files` :33
- **build_friend_zip.py** (641 行) — 友人の PC に配る zip(新しいアプリ FriendApp + ② + ① の Python のコード + 埋め込み用 Python + 部品)を作る道具(設計 notes:docs/design/f1-build.md の 2・3 節)。
  - 名前: `class BuildError` :94・`say` :98・`sha256_file` :102・`download` :115・`cached` :127・`wheel_pins` :162・`pip_download` :180・`wheels` :190・`unzip_into` :228・`lay_python` :253・`src_files` :274・`lay_src` :289・ほか 19
- **code_map.py** (466 行) — コードの地図と言葉の索引を作る道具(AI のセッションがコードの場所を早く見つけるため)。
  - 名前: `git_files` :53・`skipped` :57・`is_test` :61・`read` :65・`one_line` :73・`comment_head` :85・`py_info` :112・`js_info` :143・`cs_info` :164・`info` :186・`layer_of` :199・`norm_route` :206・ほか 12
  - 受ける口: 
- **demo_env.py** (303 行) — 見本のデータで入口と3ツールを動かす(画面の見直し・画面の写真・手での確認用)。本物の作業データには触らない。
  - 名前: `run` :47・`make_media` :51・`seed` :65・`seed_check` :180・`main` :248
- **doc_state.py** (237 行) — 計画の資料の頭の `状態`・`線` を計画の正(保管庫の plan/data/)から決めて書く・食い違いを止める。
  - 名前: `plan_data` :28・`task_lines` :34・`decide` :43・`derived` :51・`front` :75・`read_props` :86・`write_props` :110・`write` :143・`plan_docs` :152・`check` :162・`sync` :199・`main` :217
- **drift_report.py** (179 行) — 資料どうし・資料とコードの食い違いをまとめて流し、1 枚の一覧(保管庫の plan/食い違いの一覧.md。自動)に出す。
  - 名前: `read` :31・`md_files` :36・`is_index` :45・`caps` :54・`entry_docs` :70・`sentences` :76・`duplicates` :96・`collect` :108・`render` :117・`cell` :138・`write_report` :143・`main` :160
- **dropbox_auth.py** (165 行) — 友人のアプリの Dropbox の鍵を作る(ユーザーの PC で1回だけ。標準ライブラリと ytt の fsio だけ)。
  - 名前: `make_verifier` :40・`challenge_for` :47・`authorize_url` :53・`token_request_body` :65・`exchange` :74・`extra_scopes` :95・`missing_scopes` :101・`write_config` :109・`main` :114
- **fetch_webview2.py** (75 行) — 友人のアプリ FriendApp.exe が使う WebView2 の部品(DLL 3 つ)を NuGet の公式パッケージから取る(F3-1。notes:plan/f1-friend-requirements.md の C-1-1)。
  - 名前: `have` :29・`extract` :38・`main` :54
- **friend_demo.py** (327 行) — 友人の受信箱(src/friendapp)を見本のデータで動かす(画面の見直し・ui_audit・手での確認用)。本物の作業データ・② には触らない。
  - 名前: `demo_fetch` :33・`demo_probe` :38・`class StubQueue` :43・`class StubEngine` :68・`demo_thumb` :95・`class DemoStreams` :104・`seed` :143・`write_demo_fetch` :214・`class DemoDownloader` :228・`demo_file` :241・`write_demo_update` :251・`main` :263
- **friend_diag.py** (186 行) — 友人のアプリから届いた診断の記録を読む(ユーザーの PC。notes:docs/spec/friend.md の 13-11)。AI が原因を調べるときに流す。
  - 名前: `default_dir` :34・`prune` :45・`load` :59・`is_error` :82・`lines_of` :102・`main` :146
- **friend_preflight.py** (968 行) — 友人に配る zip を、配る前にこの PC で「友人の PC と同じ状態」にして通しで試す(配る前の検査。notes:docs/spec/friend.md の 13-11)。
  - 名前: `class Preflight` :70・`class Report` :74・`free_port` :100・`link_or_copy` :106・`unpack` :115・`break_fetch` :134・`place_models` :144・`mirror_map` :168・`lay_shim` :184・`friend_env` :194・`fake_media` :221・`make_work` :225・ほか 29
- **friend_preflight_shim.py** (270 行) — 配る前の検査(dev/friend_preflight.py)の通信の差し替え。検査が、展開した写しの python/Lib/site-packages/sitecustomize.py として置く
  - 名前: `install` :246
- **guard_hook.py** (434 行) — Claude Code の PreToolUse のフック: 事故のもとになる操作を機械が断る。標準ライブラリだけ・速く。
  - 名前: `class Tok` :51・`tok` :56・`tokenize` :62・`pipelines` :137・`word_of` :155・`norm_path` :171・`is_main_checkout` :184・`generated_kind` :198・`check_kill` :216・`check_sed` :242・`git_sub` :255・`check_git` :271・ほか 9
- **land.py** (297 行) — 作業のブランチを main に入れ、版(src/ytt/version.py の VERSION と README.txt の見出し)を道具が 1 つ上げる。
  - 名前: `class Stop` :40・`git` :44・`main_worktree` :53・`bump` :64・`read_version` :69・`set_version` :76・`set_readme` :80・`needs_bump` :90・`pid_alive` :95・`class Lock` :113・`pending_paths` :160・`commit` :168・ほか 3
- **land_gate.py** (318 行) — main に入れる前の関所(dev/land.py が版を上げる前に流す)。単独でも流せる:
  - 名前: `layer_of_dir` :58・`dependents` :65・`select` :70・`pick_units` :89・`run_units` :96・`count_of` :107・`run_check` :113・`run_tool` :127・`table_folders` :139・`table_drift` :153・`git` :177・`worktree_of` :182・ほか 8
- **layer_map.py** (131 行) — 役割の層と、今のファイルの行き先(役割で組み直す計画 `notes:plan/done/role-restructure.md` の 7 節を機械で読める形にしたもの)。
  - 名前: `layer_of` :111・`allowed` :121
- **lint.py** (394 行) — コードの見直しの合格の基準を測る道具(読むだけ。基準は `notes:docs/spec/code.md`)。
  - 名前: `walk` :63・`read` :71・`rel` :79・`is_test` :83・`class Corpus` :87・`py_files` :108・`has_mark` :115・`unused_imports` :120・`dead_names` :144・`long_functions` :159・`dup_helpers` :170・`js_dead` :186・ほか 7
- **loc.py** (342 行) — コードの行数を数える共通の道具(ユーザーと決めた数え方。セッションごとの数の食い違いを無くす)。
  - 名前: `classify` :39・`count_text` :64・`py_docstring_starts` :78・`py_code_lines` :89・`scan_code_lines` :104・`skip_to` :158・`skip_string` :163・`prefix_code_lines` :186・`git` :214・`files_at` :221・`tally` :244・`totals` :257・ほか 4
- **members_channels.py** (151 行) — 名簿 friend-apps/holo-colors/members.json の JP・DEV_IS の各メンバーに YouTube のチャンネル ID(channel)を入れる・確かめる道具。
  - 名前: `read_text` :29・`targets` :34・`norm` :43・`fetch_rss` :48・`verdict` :69・`cmd_check` :81・`cmd_set` :106・`main` :140
- **notes_tool.py** (461 行) — 資料のフォルダ(Obsidian の保管庫の中。layout.notes_root())のパスの検査と、資料を動かす道具。
  - 名前: `vault` :45・`plan_data` :49・`data_files` :55・`rebuild_data` :72・`md_files` :80・`code_files` :88・`local_target` :96・`pseudo_link` :108・`unlink_prose` :123・`tag_spans` :140・`vrel` :159・`link_to` :163・ほか 7
- **plan_artifact.py** (482 行) — 資料の保管庫(layout.notes_root())の plan/ の HTML(index.html・user-tasks.html)を、claude.ai の Artifact(リンクで開けるページ。スマホでも見る)用に 1 枚ずつまとめる。
  - 名前: `read` :44・`inline_assets` :49・`main_fragment` :62・`link_paths` :71・`task_line` :86・`class Linker` :91・`line_page_name` :121・`line_groups` :125・`build_line_page` :140・`build_line_pages` :160・`build_index` :167・`first_sentences` :205・ほか 12
- **plan_data.py** (420 行) — 計画のデータ(保管庫の plan/data/。計画の正)を 1 件 1 ファイルで持ち、表示用の plan/data.js を集めて作る。
  - 名前: `plan_dir_default` :49・`data_dir` :53・`has_split` :57・`read_text` :63・`write_atomic` :68・`ordered_keys` :77・`dumps` :82・`slug` :86・`file_name` :105・`items` :113・`sort_key` :129・`main_version` :135・ほか 10
- **push_helper.py** (263 行) — push.bat の補助。標準ライブラリだけ。リポジトリ直下で git が使えることが前提。
  - 名前: `git` :61・`read_removals` :70・`tracked` :90・`apply_removals` :95・`staged_files` :115・`staged_blob` :121・`problems_for` :125・`check` :160・`notes_root` :179・`push_notes` :186・`main` :232
- **rule_checks.py** (474 行) — 規則(書き方・置き場所・ファイルの形)の見張り。test-trim の規則の担当。
  - 名前: `rule` :27・`read_text` :34・`read_bytes` :39・`rel` :44・`repo_files` :48・`src_py_files` :57・`non_ascii_lines` :67・`bat_problems` :72・`requirements_problems` :83・`rule_bat_ascii_crlf` :97・`rule_requirements_ascii` :108・`push_bat_problems` :117・ほか 22
- **rule_imports.py** (719 行) — 規則の見張りのうち、ソースを import して突き合わせる物(`dev/rule_checks.py` の続き)。
  - 名前: `check` :37・`c_adopt_defaults` :86・`c_live_tx_constants` :99・`c_port_ranges` :127・`c_tool_module_names` :134・`schema_shape_problems` :153・`schema_items` :208・`c_settings_schema` :223・`c_studio_schema` :248・`c_portal_title` :263・`c_static_table` :270・`c_spec_consistency` :278・ほか 21
- **run_e2e.py** (132 行) — 画面テスト(e2e)の一式を 1 本ずつ流して、1 本 1 行(所要秒・OK/FAIL の数)で出す。一式の正はこのファイルの SUITE。
  - 名前: `label` :57・`summary` :62・`selected` :69・`run_one` :82・`main` :96
- **run_unit.py** (205 行) — unittest を層ごと・フォルダごとに流す道具(1 本ずつ別のプロセス)。リポジトリ直下で:
  - 名前: `find_files` :51・`matches` :66・`build_units` :83・`run_one` :105・`report` :129・`run_all` :144・`print_summary` :163・`main` :175
- **session_start.py** (454 行) — セッションの入口の要約。新しい AI のセッションが最初に流し、今の状態を 1 画面(150 行以内)で見る。
  - 名前: `cut` :49・`run` :54・`git` :64・`read` :68・`git_block` :78・`versions` :98・`worklog_block` :107・`boundary_dirs` :123・`boundary_notes` :131・`boundary_block` :146・`load_items` :160・`plan_block` :170・ほか 16
- **spec_check.py** (220 行) — 仕様(保管庫の docs/spec/)とコードの食い違いを探す。
  - 名前: `git_files` :45・`read` :49・`class Code` :57・`spec_files` :75・`live_lines` :84・`norm_api` :101・`clean_path` :109・`setting_keys` :114・`check` :130・`gone` :181・`main` :198
  - 受ける口: 
- **ui_audit.py** (1050 行) — 画面(UI)の見直しの合格の基準のうち、機械で測れるものを測る道具(読むだけ。基準は `notes:docs/spec/ui.md` の A)。
  - 名前: `class Findings` :106・`read` :122・`rel` :130・`screen_files` :134・`allowed` :143・`each_line` :148・`regex_starts` :156・`scan_string` :166・`scan_code` :180・`strip_js_comments` :230・`html_texts` :237・`py_strings` :252・ほか 31
  - 受ける口: `/api/info` :99
- **worklog.py** (280 行) — 作業の記録(保管庫の docs/worklog/)をセッションごとのファイルに分けて書き、週のまとめを集めて作る。
  - 名前: `worklog_dir` :56・`monday` :60・`week_name` :64・`read` :68・`write` :73・`front_matter` :78・`session_entry` :91・`sessions` :101・`auto_block` :108・`merge_week` :121・`update_index` :135・`build` :150・ほか 7

## dev/obsidian/graph-history-toggle/

- **main.js** (103 行) — Obsidian のプラグイン: グラフを「いつもの見え方」と「すべてのファイル」でボタン 1 つで切り替える。
  - 名前: `migrate` :16

## setup/

- **build_whisper_vulkan.py** (167 行) — whisper.cpp を AMD などの GPU(Vulkan)用に、この PC で作る(精度改善の計画 段2-2。build-whisper-vulkan.bat から呼ぶ)。
  - 名前: `say` :33・`fail` :37・`run` :43・`find_cmake` :50・`find_vulkan_sdk` :67・`rmtree_all` :77・`sha256` :90・`main` :98

## テスト

- dev/tests/plan_fixture.py — 計画のデータ plan/data/ をテストの一時フォルダに置く道具(dev/tests/test_plan_data.py・test_plan_artifact.py が使う)。
- dev/tests/test_build_friend_zip.py — dev/build_friend_zip.py(友人の PC に配る zip を作る。F1 の F4a)のテスト。ネットは使わない(偽のキャッシュ・取る関数は差し替えて呼ばれたら落とす)。
- dev/tests/test_code_map.py — dev/code_map.py(コードの地図と言葉の索引を作る道具)の古さの判定と書き出しのテスト。リポジトリ直下で:
- dev/tests/test_doc_state.py — 資料の食い違いの検査(dev/doc_state.py・dev/spec_check.py の --gone)のテスト。一時フォルダの偽の保管庫だけを使う
- dev/tests/test_drift_report.py — dev/drift_report.py の索引の判定。リポジトリ直下で:
- dev/tests/test_dropbox_auth.py — dev/dropbox_auth.py(切り抜き依頼の鍵を作る)のテスト。通信はしない(urlopen を差し替える)。
- dev/tests/test_friend_diag.py — dev/friend_diag.py(届いた診断を読む道具)のテスト。一時フォルダだけ(本物の Dropbox は読まない)。
- dev/tests/test_friend_preflight.py — 配る前の検査(dev/friend_preflight.py・dev/friend_preflight_shim.py)と、build_friend_zip.py --publish の関所のテスト。
- dev/tests/test_guard_hook.py — dev/guard_hook.py(PreToolUse のフックの守り)のテスト。よくある命令を並べて、通す / 断るを確かめる。一時フォルダだけを使う
- dev/tests/test_land.py — dev/land.py(main に入れる・版を道具が上げる)のテスト。一時フォルダの git リポジトリと worktree だけを使う
- dev/tests/test_land_gate.py — dev/land_gate.py(main に入れる前の関所)と dev/worklog.py check(報告の型)のテスト。一時フォルダだけを使う(テストは流さない)
- dev/tests/test_layering.py — 役割の層の import の向きを守るテスト(役割で組み直す計画 `notes:plan/done/role-restructure.md` の 4 節 1。RS0)。
- dev/tests/test_lint.py — dev/lint.py(コードの基準を測る道具)の部品のテスト。リポジトリ直下で:
- dev/tests/test_loc.py — dev/loc.py(コードの行数を数える道具)のテスト。小さな見本の文字列で、Python のコメント・空行・docstring の数え方と正味の差を確かめる
- dev/tests/test_no_src_workdata.py — YTT_DATA_DIR=inplace のとき、作業データ(ログ・起動中の印・書き出し先)が src の中にできないことを見張る。リポジトリ直下で:
- dev/tests/test_notes_tool.py — dev/notes_tool.py(資料のフォルダのパスの検査と、資料を動かす道具)のテスト。一時フォルダの資料のフォルダと git で確かめる
- dev/tests/test_plan_artifact.py — dev/plan_artifact.py(計画のページ plan/ を 1 枚の公開用 HTML に組む道具)のテスト。目次と Artifact 用の 1 枚・ホームの自動の部分・版と参照・図を見る。
- dev/tests/test_plan_data.py — dev/plan_data.py(計画のデータ plan/data/ の 1 件 1 ファイルと data.js の生成・仮決めの自動の確定)のテスト。一時フォルダだけを使う
- dev/tests/test_push_helper.py — dev/push_helper.py(push.bat の補助: ファイルの削除・コミット前の検査)のテスト。一時フォルダの git リポジトリだけを使う。
- dev/tests/test_resolve_pack_contract.py — Resolve パックの契約テスト(文字起こしの「Resolveパッケージ(zip)」と cut2resolve の Text+ パック)。zip とパックのタブは同じ部品(pack.py)で作る。
- dev/tests/test_rule_checks.py — 規則の見張り(dev/rule_checks.py・dev/rule_imports.py・dev/ui_audit.py の A-16〜A-19・A-37)が、破った見本で止まり、正しい見本で通ることを確かめる。
- dev/tests/test_run_e2e.py — dev/run_e2e.py(e2e の一式)の一覧が、リポジトリの e2e_*.py と食い違っていないかを確かめる。
- dev/tests/test_run_unit.py — dev/run_unit.py(層ごとに unittest を流す道具)の一覧の作り方と、1 本だけの実行。リポジトリ直下で:
- dev/tests/test_session_start.py — dev/session_start.py(セッションの入口の要約・子への指示文の下書き)のテスト。一時フォルダの git と偽の保管庫だけを使う
- dev/tests/test_worklog.py — dev/worklog.py(作業の記録のセッションごとのファイルと週のまとめ)のテスト。一時フォルダだけを使う
