# コードの地図: dev・setup(開発の道具)

自動で作った物(`python dev/code_map.py`)。手で直さない。目次は [index.md](index.md)。`file:line` の行の番号は作った時点の物。

## dev/

- **build_friend_zip.py** (616 行) — 友人の PC に配る zip(新しいアプリ FriendApp + ② + ① の Python のコード + 埋め込み用 Python + 部品)を作る道具(F1 の F4a。設計 notes:docs/design/f1-build.md の 2・3 節)。
  - 名前: `class BuildError` :96・`say` :100・`sha256_file` :104・`download` :117・`cached` :129・`wheel_pins` :164・`pip_download` :182・`wheels` :192・`unzip_into` :230・`lay_python` :255・`src_files` :276・`lay_src` :291・ほか 17
- **code_map.py** (462 行) — コードの地図と言葉の索引を作る道具(AI のセッションがコードの場所を早く見つけるため。2026-10-18)。
  - 名前: `git_files` :52・`skipped` :57・`is_test` :61・`read` :65・`one_line` :73・`comment_head` :85・`py_info` :112・`js_info` :143・`cs_info` :164・`info` :186・`layer_of` :199・`norm_route` :206・ほか 11
  - 受ける口: 
- **demo_env.py** (300 行) — 見本のデータで入口と3ツールを動かす(画面の見直し・画面の写真・手での確認用)。本物の作業データには触らない。
  - 名前: `run` :47・`make_media` :51・`seed` :65・`seed_check` :177・`main` :245
- **dropbox_auth.py** (165 行) — 友人のアプリの Dropbox の鍵を作る(ユーザーの PC で1回だけ。標準ライブラリと ytt の fsio だけ)。
  - 名前: `make_verifier` :40・`challenge_for` :47・`authorize_url` :53・`token_request_body` :65・`exchange` :74・`extra_scopes` :95・`missing_scopes` :101・`write_config` :109・`main` :114
- **fetch_webview2.py** (75 行) — 友人のアプリ FriendApp.exe が使う WebView2 の部品(DLL 3 つ)を NuGet の公式パッケージから取る(F3-1。notes:plan/f1-friend-requirements.md の C-1-1)。
  - 名前: `have` :29・`extract` :38・`main` :54
- **friend_demo.py** (309 行) — 友人の受信箱(src/friendapp)を見本のデータで動かす(画面の見直し・ui_audit・手での確認用)。本物の作業データ・② には触らない。
  - 名前: `demo_fetch` :31・`demo_probe` :36・`class StubQueue` :41・`class StubEngine` :66・`demo_thumb` :93・`class DemoStreams` :102・`seed` :141・`write_demo_fetch` :211・`class DemoDownloader` :225・`demo_file` :238・`main` :248
- **layer_map.py** (139 行) — 役割の層と、今のファイルの行き先(役割で組み直す計画 `notes:plan/role-restructure.md` の 7 節を機械で読める形にしたもの。RS0。RS6 a-0 で 5 つの層に)。
  - 名前: `layer_of` :119・`allowed` :129
- **lint.py** (400 行) — コードの見直しの合格の基準を測る道具(読むだけ。基準は `notes:docs/spec/code.md`)。
  - 名前: `walk` :61・`read` :69・`rel` :77・`is_test` :81・`class Corpus` :85・`py_files` :106・`has_mark` :113・`unused_imports` :118・`dead_names` :142・`long_functions` :155・`dup_helpers` :166・`js_dead` :182・ほか 7
- **members_channels.py** (151 行) — 名簿 friend-apps/holo-colors/members.json の JP・DEV_IS の各メンバーに YouTube のチャンネル ID(channel)を入れる・確かめる道具。
  - 名前: `read_text` :29・`targets` :34・`norm` :43・`fetch_rss` :48・`verdict` :69・`cmd_check` :81・`cmd_set` :106・`main` :140
- **notes_tool.py** (429 行) — 資料のフォルダ(Obsidian の保管庫の中。layout.notes_root())のパスの検査と、資料を動かす道具(2026-10-13)。
  - 名前: `vault` :42・`read` :46・`write` :51・`md_files` :56・`code_files` :64・`local_target` :72・`pseudo_link` :84・`unlink_prose` :99・`tag_spans` :116・`vrel` :135・`link_to` :139・`data_js_problems` :159・ほか 6
- **plan_artifact.py** (473 行) — 資料の保管庫(layout.notes_root())の plan/ の HTML(index.html・user-tasks.html)を、claude.ai の Artifact(リンクで開けるページ。スマホでも見る)用に 1 枚ずつまとめる。
  - 名前: `read` :43・`inline_assets` :48・`main_fragment` :61・`parse_plan_js` :70・`link_paths` :100・`task_line` :115・`class Linker` :120・`line_page_name` :150・`line_groups` :154・`build_line_page` :169・`build_line_pages` :189・`build_index` :196・ほか 11
- **push_helper.py** (248 行) — push.bat の補助(2026-09-26)。標準ライブラリだけ。リポジトリ直下で git が使えることが前提。
  - 名前: `git` :60・`read_removals` :69・`tracked` :89・`apply_removals` :94・`staged_files` :114・`staged_blob` :120・`problems_for` :124・`check` :154・`notes_root` :173・`push_notes` :180・`main` :217
- **run_e2e.py** (140 行) — 画面テスト(e2e)の一式を 1 本ずつ流して、1 本 1 行(所要秒・OK/FAIL の数)で出す。一式の正はこのファイルの SUITE。
  - 名前: `label` :65・`summary` :70・`selected` :77・`run_one` :90・`main` :104
- **run_editor_suite.py** (100 行) — 「編集」まわりのテストをまとめて流し、結果の1行ずつを出す(段10 のコードの整理で、分ける前と後の結果を比べるため)。
  - 名前: `find_node` :26・`summary` :49・`main` :62
- **run_unit.py** (175 行) — unittest を層ごと・フォルダごとに流す道具(1 本ずつ別のプロセス)。リポジトリ直下で:
  - 名前: `find_files` :45・`matches` :60・`build_units` :77・`run_one` :95・`report` :110・`run_all` :118・`print_summary` :135・`main` :145
- **ui_audit.py** (842 行) — 画面(UI)の見直しの合格の基準のうち、機械で測れるものを測る道具(読むだけ。基準は `notes:docs/spec/ui.md` の A)。
  - 名前: `class Findings` :101・`read` :117・`rel` :125・`screen_files` :129・`allowed` :138・`each_line` :143・`regex_starts` :151・`scan_string` :161・`scan_code` :175・`strip_js_comments` :225・`html_texts` :232・`py_strings` :247・ほか 19
  - 受ける口: `/api/info` :94

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
- dev/tests/test_dropbox_auth.py — dev/dropbox_auth.py(切り抜き依頼の鍵を作る)のテスト。通信はしない(urlopen を差し替える)。
- dev/tests/test_layering.py — 役割の層の import の向きを守るテスト(役割で組み直す計画 `notes:plan/role-restructure.md` の 4 節 1。RS0)。
- dev/tests/test_lint.py — dev/lint.py(コードの基準を測る道具)の部品のテスト。リポジトリ直下で:
- dev/tests/test_no_src_workdata.py — YTT_DATA_DIR=inplace のとき、作業データ(ログ・起動中の印・書き出し先)が src の中にできないことを見張る。リポジトリ直下で:
- dev/tests/test_notes_tool.py — dev/notes_tool.py(資料のフォルダのパスの検査と、資料を動かす道具)のテスト。一時フォルダの資料のフォルダと git で確かめる
- dev/tests/test_plan_artifact.py — dev/plan_artifact.py(計画のページ plan/ を 1 枚の公開用 HTML に組む道具)のテスト。目次と Artifact 用の 1 枚・ホームの自動の部分・版と参照・図を見る。
- dev/tests/test_push_helper.py — dev/push_helper.py(push.bat の補助: ファイルの削除・コミット前の検査)のテスト。一時フォルダの git リポジトリだけを使う。
- dev/tests/test_resolve_pack_contract.py — Resolve パックの契約テスト(文字起こしの「Resolveパッケージ(zip)」と cut2resolve の Text+ パック)。
- dev/tests/test_run_e2e.py — dev/run_e2e.py(e2e の一式)の一覧が、リポジトリの e2e_*.py と食い違っていないかを確かめる。
- dev/tests/test_run_unit.py — dev/run_unit.py(層ごとに unittest を流す道具)の一覧の作り方と、1 本だけの実行。リポジトリ直下で:
- dev/tests/test_setup_ascii.py — Windows の cmd・pip がシステムの文字コード(日本語の Windows では cp932)で読むファイルが ASCII だけか・.bat が CRLF かのテスト。
