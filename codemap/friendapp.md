# コードの地図: src/friendapp(友人の玄関)

自動で作った物(`python dev/code_map.py`)。手で直さない。目次は [index.md](index.md)。`file:line` の行の番号は作った時点の物。

## src/friendapp/

- **__init__.py** (2 行) — 友人の玄関(FriendApp。友人の PC の 2 つ目の玄関。notes:docs/design/friend-history.md の 7 章)。ytt と ② flow だけを読む(③ human は読まない)
- **api.py** (964 行) — 友人の玄関の口の中身(F3-3。HTTP の形は server.py。ここは欄の検査・② への受付・送った物の進み具合と取り消し・失敗のやり直し・前回の値)。
  - 名前: `class FormError` :63・`live_auto` :72・`merge_live` :80・`oembed` :90・`probe_live` :95・`guess_streamer` :101・`file_title` :110・`clean_ranges` :116・`fit_name` :135・`class Api` :144・`fsio_inside` :926・`rowtitle` :933
- **diag.py** (315 行) — 友人のアプリの診断の記録(ユーザー決定。notes:docs/spec/friend.md の 13-11)。友人の PC でしか出ない不具合を、伝聞でなく記録で追うため。
  - 名前: `mask` :62・`windows_text` :85・`stage_rows` :96・`transcribe_rows` :111・`probe_only` :124・`prune_names` :130・`class Diag` :140
- **dropbox.py** (456 行) — 友人の玄関の Dropbox の部品(notes:docs/design/friend-history.md の 7 章・docs/spec/friend.md の 2-17・4 章)。
  - 名前: `class DropboxError` :38・`class Cancelled` :54・`class Config` :58・`config_path` :74・`load_config` :79・`missing_scope` :93・`is_not_found` :98・`error_text` :102・`arg_header` :128・`commit_arg` :133・`content_hash` :139・`urlopen_transport` :168・ほか 1
- **engine.py** (535 行) — 友人の玄関の ② の組み立て(flow の部品を糸つきで持つ)。
  - 名前: `stage_lines` :41・`transcribe_line` :57・`transcribe_lines` :77・`transcribe_records` :83・`export_records` :103・`class FriendQueue` :122・`class Engine` :147・`live_cause` :499
- **inbox.py** (1192 行) — 友人の受信箱の正(notes:plan/f1-friend-requirements.md の C-3、notes:docs/design/friend-history.md の 7 章)。
  - 名前: `pack_name` :79・`pack_title` :85・`unique_dest` :89・`case_of` :97・`class Inbox` :108
- **live.py** (45 行) — 友人の玄関のライブの依頼の欄と結びつき(notes:docs/design/friend-history.md の 7 章、docs/spec/friend.md の 2-15)。軽い部品だけ(画面を先に出すため)。
  - 名前: `check_settings` :20・`settings_label` :42
- **live_session.py** (335 行) — 友人の玄関のライブ係(notes:docs/design/friend-history.md の 7 章、docs/spec/friend.md の 2-15)。
  - 名前: `recorders` :37・`class FriendLive` :46
  - 受ける口: `/api/queue/add` :91・`/api/queue` :94
- **oplog.py** (137 行) — 友人のアプリの操作の記録(形の正は notes:plan/友人の不具合の自動対応-1025.md の「操作の記録」)。
  - 名前: `day_name` :32・`clean_ui` :47・`class OpLog` :91
- **places.py** (251 行) — 友人の玄関の置き場所(notes:docs/design/friend-history.md の 7 章)。
  - 名前: `home` :36・`data_root` :48・`friend_dir` :56・`cookies_path` :60・`outbox_dir` :65・`is_maker_data` :69・`tool_env` :98・`lay_tools_shallow` :119・`lay_whisper` :147・`api_key_env` :172・`members_env` :186・`first_roster` :197・ほか 1
- **progress.py** (284 行) — 友人のアプリの「送った物」の行に出す、失敗の言葉と進み具合を作る部品(F3-3。notes:plan/f1-friend-requirements.md の C-2-15・C-2-16)。純粋な関数だけ(ファイルもネットも触らない。時計は引数で受ける)。
  - 名前: `classify` :105・`waiting_message` :128・`retry_note` :138・`stage` :180・`eta` :228・`slow` :247・`text` :265
- **report.py** (723 行) — 友人のアプリの状態の書き出しと、そのきっかけ(形の正は notes:plan/友人の不具合の自動対応-1025.md。受け取り側はユーザーの PC の別の部品)。
  - 名前: `fit` :63・`judge` :91・`live_cands` :132・`dir_bytes` :142・`class Reporter` :156
- **server.py** (1072 行) — 友人の玄関(notes:docs/design/friend-history.md の 7 章)。友人の PC の 2 つ目の玄関(ユーザーの PC は src/app/server.py)。
  - 名前: `save_dir` :120・`open_folder` :129・`pick_file_dialog` :145・`pick_folder_dialog` :185・`page_token` :222・`inject_meta` :229・`class Handler` :236・`client_log_line` :544・`class Server` :550・`class FriendApp` :568・`make_logger` :952・`say` :992・ほか 2
  - 受ける口: `/api/ping` :276・`/api/friend/inbox` :278・`/api/friend/tidy` :283・`/api/friend/update` :285・`/api/friend/setup` :288・`/api/friend/state` :290・`/api/friend/peek` :294・`/api/friend/peek-live` :299・`/api/friend/player` :304・`/api/friend/receive` :306・`/api/friend/media` :309・`/api/friend/settings` :320・`/api/friend/streams` :322・`/api/flow/status` :324・`/api/friend/upload` :339・`/api/friend/ops` :385・`/api/friend/send` :387・`/api/friend/pick-file` :392・`/api/friend/decide` :400・`/api/friend/undo` :402・`/api/friend/files` :406・`/api/friend/report` :408・`/api/friend/prefs` :410・`/api/friend/retry` :413・`/api/friend/cancel` :417・`/api/friend/live-settings` :421・`/api/friend/local` :423・`/api/friend/open` :427・`/api/friend/update/apply` :440・`/api/friend/streams/refresh` :448・`/api/friend/settings/key` :456・`/api/friend/pick-folder` :461・`/api/friend/notice-seen` :473・`/api/shutdown` :479・`/api/flow/submit` :483・`/api/flow/cancel` :492・`/api/ytt/streamer-colors` :496・`/api/ytt/client-log` :498
- **settings.py** (333 行) — 友人の玄関の ⚙(notes:docs/design/friend-history.md の 7 章)。
  - 名前: `class SettingsError` :46・`clean_key` :51・`looks_like_key` :55・`judge` :60・`probe_key` :88・`check_key` :102・`keys_path` :110・`load_key` :114・`save_key` :119・`check_folder` :128・`class Settings` :153
- **setup.py** (961 行) — 友人の玄関の初回の取得(notes:docs/design/friend-history.md の 7 章)。
  - 名前: `class FetchError` :61・`class Cancelled` :65・`safe_relative` :74・`problem` :90・`parse_item` :117・`load` :127・`archive_name` :151・`expect` :159・`folder` :164・`marker` :168・`label` :172・`is_done` :181・ほか 11
- **streams.py** (559 行) — 友人のアプリの「送る」画面の左に並べる、ホロライブ JP(と DEV_IS)の配信の一覧(F3-2)。API キー無し。
  - 名前: `parse_rss` :159・`classify` :191・`class Streams` :261
- **sync.py** (1003 行) — 友人の玄関の Dropbox の同期(notes:docs/design/friend-history.md の 7 章、docs/spec/friend.md の 2-14〜2-17・5-1)。
  - 名前: `class SyncError` :97・`name_ok` :102・`out_kind` :108・`clean_text` :120・`clean_origin` :125・`parse_meta` :136・`parse_meta_info` :142・`failure_text` :162・`server_time` :169・`safe_rel` :177・`safe_join` :184・`local_name` :194・ほか 10
- **tidy.py** (622 行) — アプリのフォルダの整理(形は Fable と相談 = 共有のメモ f3a-tidy-design.md。決定 3-86)。新しい版に入れ替えて起動できたあとと ⚙ から。
  - 名前: `keep_floor` :76・`class Tidy` :161・`prune_old_files` :597・`prune_diag` :615
- **toolcheck.py** (111 行) — 友人の PC の初回の準備の最後の「道具を動かして確かめる」(F3-5。notes:plan/f1-friend-requirements.md の C-5-2・C-0)。
  - 名前: `run_cmd` :26・`check_tool` :37・`check_tools` :53・`make_wav` :58・`whisper_run` :68・`check_whisper` :76・`signature` :97・`failed` :109
- **voicesend.py** (124 行) — 友人の PC から送る声の材料(10-24 夜。ユーザー「誰の声をメンバー全員分」。案 = notes:plan/声の材料を友人のPCから-1024.md)。
  - 名前: `zip_name` :33・`build` :46
- **ytdlp_update.py** (186 行) — 友人の PC の yt-dlp をいつも新しく(YouTube の bot 判定・仕様の変更に古い yt-dlp は当たりやすい。notes:docs/spec/friend.md の 13-13)。
  - 名前: `record_path` :56・`latest` :63・`probe` :75・`version_of` :85・`mark_ok` :93・`update` :98・`enabled` :151・`maybe_start` :155・`facts` :179

## src/friendapp/ui/

- **friend.js** (133 行) — 友人のアプリの共通の部分(F3)。口は friendapp/server.py の説明。外から来た文字(題・名前・理由)は textContent でだけ入れる。
- **host.js** (92 行) — 窓と画面の境目(F3-1。notes:plan/f1-friend-requirements.md の C-1、notes:docs/design/friend-history.md の 7 章)。
- **oplog.js** (138 行) — 操作の記録と画面の要約を玄関へ送る(形の正は notes:plan/友人の不具合の自動対応-1025.md。玄関は friendapp/report.py・oplog.py)。
- **palette.js** (13 行) — 友人のアプリの配色: ピンク(ui-kit のシンセウェーブ = 暗い・data-palette=synth)に固定する(配色 4 つの切り替えは 10-24 に無くした)。
- **receive.js** (352 行) — 受け取る画面(F3-4。notes:plan/f1-friend-requirements.md の C-3)。口 = GET api/friend/receive(friendapp/inbox.py の receive_view)・
- **send-form.js** (506 行) — 送る欄(F3-3。notes:plan/f1-friend-requirements.md の C-2-6〜C-2-13・C-2-17〜C-2-19)。口 = POST api/friend/send(friendapp/api.py の説明)。
- **send-list.js** (168 行) — 送る画面の配信の一覧(F3-2。notes:plan/f1-friend-requirements.md の C-2-2〜C-2-5)。
- **sent.js** (156 行) — 送った物(F3-3。notes:plan/f1-friend-requirements.md の C-2-14〜C-2-16)。行 = GET api/friend/inbox の rows のうち、まだ届け終えていない物と失敗。
- **settings.js** (379 行) — ⚙ 設定の引き出し(notes:plan/f1-friend-requirements.md の C-5-2・C-2-19)。
- **setup.js** (103 行) — 初回の準備だけの画面(notes:plan/f1-friend-requirements.md の C-5-1)。
- **update.js** (137 行) — 新しい版の帯の 1 行(更新。notes:docs/design/friend-history.md の 7 章)。

## テスト

- tests/friendapp/e2e_friend_receive.py — 友人のアプリの「受け取る」画面の通し確認(Playwright の chromium・headless・音なし)。玄関を一時フォルダに起こし(friend_e2e_kit.py)、
- tests/friendapp/e2e_friend_send.py — 友人のアプリの「送る」画面の通し確認(Playwright の chromium・headless・音なし)。玄関を一時フォルダに起こし(friend_e2e_kit.py)、
- tests/friendapp/friend_e2e_kit.py — 友人のアプリの e2e(e2e_friend_send.py・e2e_friend_receive.py)の共通部品。玄関(friendapp.server の FriendApp + Server)を
- tests/friendapp/test_diag.py — src/friendapp/diag.py(診断の記録)と、同期が /診断/ へ上げて 3 日で消す所・道具の記録 ytt/tools.remember のテスト。
- tests/friendapp/test_dropbox.py — src/friendapp/dropbox.py のテスト(本物の Dropbox につながない = 偽の通信 transport)。リポジトリ直下で: py -3.12 -m unittest tests/friendapp/test_dropbox.py
- tests/friendapp/test_engine.py — src/friendapp/engine.py(玄関の ② の組み立て)のテスト。リポジトリ直下で: py -3.12 -m unittest tests/friendapp/test_engine.py
- tests/friendapp/test_file_preview.py — 動画ファイルの依頼(映像 2 本の mkv・長い題)の確認用の動画が、URL の依頼と同じ道で作られ、受け取るの media が読む所に置かれること。
- tests/friendapp/test_inbox.py — src/friendapp/inbox.py のテスト(受信箱の記録・決める・3 日の片付け・画面へ出す形)。リポジトリ直下で: py -3.12 -m unittest tests/friendapp/test_inbox.py
- tests/friendapp/test_live.py — 送る欄の動画ファイル・ライブのテスト。リポジトリ直下で: py -3.12 -m unittest tests/friendapp/test_live.py
- tests/friendapp/test_longpath.py — 260 文字を超える深いフォルダでも、zip の展開と受信箱の動かす所(保存先へ・ごみ箱へ・戻す)が通ること(Windows だけ)。
- tests/friendapp/test_places.py — src/friendapp/places.py のテスト。リポジトリ直下で: py -3.12 -m unittest tests/friendapp/test_places.py
- tests/friendapp/test_progress.py — friendapp/progress.py の確かめ(F3-3)。ファイルもネットも使わない。
- tests/friendapp/test_report.py — src/friendapp/report.py(状態の書き出しとそのきっかけ)・oplog.py(操作の記録)・tidy.prune_diag の境目のテスト。
- tests/friendapp/test_server.py — src/friendapp/server.py と api.py の HTTP の口のテスト(本物のソケットで 127.0.0.1 のポート 0 に起こす。② は偽の engine)。リポジトリ直下で: py -3.12 -m unittest tests/friendapp/test_serve…
- tests/friendapp/test_settings.py — 友人の玄関の ⚙ と初回の準備の口のテスト(src/friendapp/settings.py・setup.py・server.py)。本物のソケットで 127.0.0.1 のポート 0 に起こす。
- tests/friendapp/test_setup.py — src/friendapp/setup.py(初回の取得)のテスト。本物のネットには出ない(偽の取り方)。リポジトリ直下で: py -3.12 -m unittest tests/friendapp/test_setup.py
- tests/friendapp/test_streams.py — F3-2 友人のアプリの配信の一覧(friendapp/streams.py)のテスト。リポジトリ直下で: py -3.12 -m unittest tests/friendapp/test_streams.py
- tests/friendapp/test_sync.py — src/friendapp/sync.py のテスト(本物の Dropbox につながない = 偽の io。受信箱は本物の一時フォルダ)。
- tests/friendapp/test_tidy.py — フォルダの整理(friendapp/tidy.py)のテスト。一時フォルダに見本のアプリのフォルダを作る(本物の友人のフォルダ・作業データには触らない)。
- tests/friendapp/test_toolcheck.py — src/friendapp/toolcheck.py と places の道具の置き方(F3-5)のテスト。本物の道具・文字起こし・ネットは動かさない(偽の run・偽の transcribe)。
- tests/friendapp/test_voicesend.py — 友人の PC から送る声の材料の通し(src/friendapp/voicesend.py → src/human/friend/voicein.py。10-24 夜)。
- tests/friendapp/test_ytdlp_update.py — src/friendapp/ytdlp_update.py(yt-dlp をいつも新しく)のテスト。ネットと yt-dlp は偽物(偽の http・偽の run)。
