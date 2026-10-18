# コードの地図: src/friendapp(友人の玄関)

自動で作った物(`python dev/code_map.py`)。手で直さない。目次は [index.md](index.md)。`file:line` の行の番号は作った時点の物。

## src/friendapp/

- **__init__.py** (2 行) — 友人の玄関(F2。友人の PC の 2 つ目の玄関。notes:plan/f1-friend-requirements.md の A-1)。ytt と ② flow だけを読む(③ human は読まない)
- **api.py** (937 行) — 友人の玄関の口の中身(F2-2・F3-3。HTTP の形は server.py。ここは欄の検査・② への受付・送った物の進み具合と取り消し・失敗のやり直し・前回の値)。
  - 名前: `class FormError` :67・`oembed` :75・`probe_live` :86・`guess_streamer` :92・`file_title` :101・`clean_ranges` :107・`class Api` :123・`fsio_inside` :899・`rowtitle` :906
- **diag.py** (271 行) — 友人のアプリの診断の記録(10-18 ユーザー決定。notes:docs/spec/friend.md の 13-11)。友人の PC でしか出ない不具合を、伝聞でなく記録で追うため。
  - 名前: `mask` :56・`windows_text` :79・`stage_rows` :90・`transcribe_rows` :104・`prune_names` :116・`class Diag` :126
- **dropbox.py** (437 行) — 友人の玄関の Dropbox の部品(F2-3。notes:plan/f1-friend-requirements.md の 8b 章・docs/spec/friend.md の 2-17・4 章)。
  - 名前: `class DropboxError` :35・`class Cancelled` :51・`class Config` :55・`config_path` :71・`load_config` :76・`missing_scope` :90・`is_not_found` :95・`error_text` :99・`arg_header` :125・`commit_arg` :130・`content_hash` :136・`urlopen_transport` :165・ほか 1
- **engine.py** (358 行) — 友人の玄関の ② の組み立て(F2-1・F2-2。Fable と相談した案 3 = CLI(app/cli.py の run_local)と同じ部品を糸つきで持つ)。
  - 名前: `stage_lines` :37・`transcribe_line` :53・`transcribe_lines` :73・`transcribe_records` :79・`class FriendQueue` :101・`class Engine` :129
- **inbox.py** (1085 行) — 友人の受信箱の正(F2-2。notes:plan/f1-friend-requirements.md の A-1・A-12・5 章・6 章)。
  - 名前: `pack_name` :72・`pack_title` :78・`verdict_doc` :82・`unique_dest` :89・`case_of` :97・`class Inbox` :108
- **live.py** (165 行) — 友人の玄関のライブの依頼の欄と結びつき(F2-6。notes:plan/f1-friend-requirements.md の A-5・A-5b、docs/spec/friend.md の 2-15)。軽い部品だけ(画面を先に出すため)。
  - 名前: `check_settings` :34・`clean_settings` :56・`settings_label` :75・`request_item` :88・`class RequestBook` :110
- **live_session.py** (223 行) — 友人の玄関のライブ係(F2-6。notes:plan/f1-friend-requirements.md の A-5・A-13・A-14、docs/spec/friend.md の 2-15)。
  - 名前: `recorders` :34・`class FriendLive` :43
  - 受ける口: `/api/queue/add` :88・`/api/queue` :91
- **oldcopy.py** (467 行) — 友人の PC の古い作業データ(old_root)から、初回の取得の表(fetch.json)に載った物を新しい作業データ(new_root)へ写す。
  - 名前: `load_items` :74・`plan` :112・`notice` :168・`pending` :176・`clean` :194・`skip` :204・`mark_notice_shown` :213・`home_pending` :398・`clean_home` :407・`mark_asked` :430・`migrate` :437
- **places.py** (245 行) — 友人の玄関の置き場所(F2-1。notes:plan/f1-friend-requirements.md の 7 章・A-15・A-16)。
  - 名前: `home` :36・`data_root` :48・`friend_dir` :56・`cookies_path` :60・`outbox_dir` :65・`old_data_root` :69・`is_maker_data` :81・`tool_env` :110・`lay_tools_shallow` :131・`lay_whisper` :159・`api_key_env` :184・`members_env` :203・ほか 1
- **progress.py** (250 行) — 友人のアプリの「送った物」の行に出す、失敗の言葉と進み具合を作る部品(F3-3。notes:plan/f1-friend-requirements.md の C-2-15・C-2-16)。純粋な関数だけ(ファイルもネットも触らない。時計は引数で受ける)。
  - 名前: `classify` :73・`stage` :141・`eta` :187・`record` :206・`slow` :213・`text` :231
- **server.py** (1021 行) — 友人の玄関(F2-1・F2-2。notes:plan/f1-friend-requirements.md の A-1・B)。友人の PC の 2 つ目の玄関(ユーザーの PC は src/app/server.py)。
  - 名前: `save_dir` :119・`open_folder` :128・`pick_file_dialog` :144・`pick_folder_dialog` :184・`page_token` :221・`inject_meta` :228・`class Handler` :237・`streamer_colors` :562・`class Server` :574・`class FriendApp` :592・`make_logger` :915・`say` :944・ほか 2
  - 受ける口: `/api/ping` :289・`/api/friend/inbox` :291・`/api/friend/tidy` :296・`/api/friend/update` :298・`/api/friend/setup` :300・`/api/friend/state` :302・`/api/friend/peek` :306・`/api/friend/peek-live` :311・`/api/friend/player` :316・`/api/friend/receive` :318・`/api/friend/media` :321・`/api/friend/settings` :339・`/api/friend/streams` :341・`/api/flow/status` :343・`/api/friend/upload` :358・`/api/friend/send` :404・`/api/friend/pick-file` :407・`/api/friend/decide` :415・`/api/friend/undo` :417・`/api/friend/palette` :421・`/api/friend/files` :423・`/api/friend/report` :425・`/api/friend/prefs` :427・`/api/friend/retry` :430・`/api/friend/cancel` :432・`/api/friend/live-settings` :434・`/api/friend/local` :436・`/api/friend/open` :438・`/api/friend/update/apply` :451・`/api/friend/streams/refresh` :459・`/api/friend/settings/key` :467・`/api/friend/pick-folder` :472・`/api/friend/notice-seen` :484・`/api/shutdown` :492・`/api/flow/submit` :496・`/api/flow/cancel` :505・`/api/ytt/streamer-colors` :509・`/api/ytt/client-log` :511
- **settings.py** (411 行) — 友人の玄関の ⚙(F2-5。notes:plan/f1-friend-requirements.md の 7 章・9-2・A-8。今の送るアプリの Settings.cs と同じ規則を Python で)。
  - 名前: `class SettingsError` :50・`clean_key` :55・`looks_like_key` :59・`judge` :64・`probe_key` :92・`check_key` :106・`keys_path` :114・`load_key` :118・`save_key` :123・`check_folder` :132・`class Settings` :157
- **setup.py** (1014 行) — 友人の玄関の初回の取得(F2-5。notes:plan/f1-friend-requirements.md の 9-1・7-5・A-15・A-16。今の送るアプリの Setup.cs と同じ規則を Python で)。
  - 名前: `class FetchError` :58・`class Cancelled` :62・`safe_relative` :71・`problem` :87・`parse_item` :114・`load` :124・`archive_name` :148・`expect` :156・`folder` :161・`marker` :165・`label` :169・`is_done` :178・ほか 12
- **streams.py** (559 行) — 友人のアプリの「送る」画面の左に並べる、ホロライブ JP(と DEV_IS)の配信の一覧(F3-2)。API キー無し。
  - 名前: `parse_rss` :159・`classify` :191・`class Streams` :261
- **sync.py** (868 行) — 友人の玄関の Dropbox の同期(F2-3。notes:plan/f1-friend-requirements.md の A-2・5 章・8b 章、docs/spec/friend.md の 2-14〜2-17・5-1)。
  - 名前: `class SyncError` :81・`name_ok` :86・`out_kind` :92・`clean_text` :104・`clean_origin` :109・`parse_group` :132・`parse_meta` :161・`parse_meta_info` :167・`failure_text` :186・`server_time` :193・`safe_rel` :201・`safe_join` :208・ほか 9
- **tidy.py** (595 行) — アプリのフォルダの整理(10-18。形は Fable と相談 = 共有のメモ f3a-tidy-design.md。決定 3-86)。新しい版に入れ替えて起動できたあとと ⚙ から。
  - 名前: `class Tidy` :134
- **toolcheck.py** (111 行) — 友人の PC の初回の準備の最後の「道具を動かして確かめる」(F3-5。notes:plan/f1-friend-requirements.md の C-5-2・C-0)。
  - 名前: `run_cmd` :26・`check_tool` :37・`check_tools` :53・`make_wav` :58・`whisper_run` :68・`check_whisper` :76・`signature` :97・`failed` :109

## src/friendapp/ui/

- **friend.js** (133 行) — 友人のアプリの共通の部分(F3)。口は friendapp/server.py の説明。外から来た文字(題・名前・理由)は textContent でだけ入れる。
- **host.js** (92 行) — 窓と画面の境目(F3-1。notes:plan/f1-friend-requirements.md の C-1・説明は friend-apps/launcher/README.txt)。
- **palette.js** (71 行) — 友人のアプリの配色(前の送るアプリの「配色」= A ネオンシアン・B シンセウェーブ・C ターミナルグリーン・D アイスライト)。
- **receive.js** (348 行) — 受け取る画面(F3-4。notes:plan/f1-friend-requirements.md の C-3)。口 = GET api/friend/receive(friendapp/inbox.py の receive_view)・
- **send-form.js** (506 行) — 送る欄(F3-3。notes:plan/f1-friend-requirements.md の C-2-6〜C-2-13・C-2-17〜C-2-19)。口 = POST api/friend/send(friendapp/api.py の説明)。
- **send-list.js** (168 行) — 送る画面の配信の一覧(F3-2。notes:plan/f1-friend-requirements.md の C-2-2〜C-2-5)。
- **sent.js** (142 行) — 送った物(F3-3。notes:plan/f1-friend-requirements.md の C-2-14〜C-2-16)。行 = GET api/friend/inbox の rows のうち、まだ届け終えていない物と失敗。
- **settings.js** (442 行) — ⚙ 設定の引き出し(F3-5。notes:plan/f1-friend-requirements.md の C-5-2・C-2-19・C-1-2)。
- **setup.js** (108 行) — 初回の準備だけの画面(F3-5。notes:plan/f1-friend-requirements.md の C-5-1・C-1-2)。
- **update.js** (134 行) — 新しい版の帯の 1 行(更新。notes:plan/f1-friend-requirements.md の 8 章・A-15。形は friend-apps/launcher/README.txt)。

## テスト

- src/friendapp/tests/e2e_friend_receive.py — 友人のアプリの「受け取る」画面の通し確認(Playwright の chromium・headless・音なし)。玄関を一時フォルダに起こし(friend_e2e_kit.py)、
- src/friendapp/tests/e2e_friend_send.py — 友人のアプリの「送る」画面の通し確認(Playwright の chromium・headless・音なし)。玄関を一時フォルダに起こし(friend_e2e_kit.py)、
- src/friendapp/tests/friend_e2e_kit.py — 友人のアプリの e2e(e2e_friend_send.py・e2e_friend_receive.py)の共通部品。玄関(friendapp.server の FriendApp + Server)を
- src/friendapp/tests/test_diag.py — src/friendapp/diag.py(診断の記録)と、同期が /診断/ へ上げて 3 日で消す所・道具の記録 ytt/tools.remember のテスト。
- src/friendapp/tests/test_dropbox.py — src/friendapp/dropbox.py のテスト(本物の Dropbox につながない = 偽の通信 transport)。リポジトリ直下で: py -3.10 -m unittest src/friendapp/tests/test_dropbox.py
- src/friendapp/tests/test_engine.py — src/friendapp/engine.py(玄関の ② の組み立て)と oldcopy の写すだけの形のテスト。リポジトリ直下で: py -3.10 -m unittest src/friendapp/tests/test_engine.py
- src/friendapp/tests/test_file_preview.py — 動画ファイルの依頼(映像 2 本の mkv・長い題)の確認用の動画が、URL の依頼と同じ道で作られ、受け取るの media が読む所に置かれること。
- src/friendapp/tests/test_inbox.py — src/friendapp/inbox.py のテスト(受信箱の記録・決める・3 日の片付け・画面へ出す形)。リポジトリ直下で: py -3.10 -m unittest src/friendapp/tests/test_inbox.py
- src/friendapp/tests/test_live.py — F2-6 送る欄を広げる(動画ファイル・ライブ)のテスト。リポジトリ直下で: py -3.10 -m unittest src/friendapp/tests/test_live.py
- src/friendapp/tests/test_longpath.py — 260 文字を超える深いフォルダでも、zip の展開と受信箱の動かす所(保存先へ・ごみ箱へ・戻す)が通ること(Windows だけ)。
- src/friendapp/tests/test_oldcopy.py — src/friendapp/oldcopy.py のテスト。リポジトリ直下で: py -3.10 -m unittest src/friendapp/tests/test_oldcopy.py
- src/friendapp/tests/test_places.py — src/friendapp/places.py のテスト。リポジトリ直下で: py -3.10 -m unittest src/friendapp/tests/test_places.py
- src/friendapp/tests/test_progress.py — friendapp/progress.py の確かめ(F3-3)。ファイルもネットも使わない。
- src/friendapp/tests/test_server.py — src/friendapp/server.py と api.py の HTTP の口のテスト(本物のソケットで 127.0.0.1 のポート 0 に起こす。② は偽の engine)。リポジトリ直下で: py -3.10 -m unittest src/friendapp/tests/test_s…
- src/friendapp/tests/test_settings.py — 友人の玄関の ⚙ と初回の準備の口のテスト(F2-5。src/friendapp/settings.py・setup.py・server.py)。本物のソケットで 127.0.0.1 のポート 0 に起こす。
- src/friendapp/tests/test_setup.py — src/friendapp/setup.py(初回の取得。F2-5)のテスト。本物のネットには出ない(偽の取り方)。リポジトリ直下で: py -3.10 -m unittest src/friendapp/tests/test_setup.py
- src/friendapp/tests/test_streams.py — F3-2 友人のアプリの配信の一覧(friendapp/streams.py)のテスト。リポジトリ直下で: py -3.10 -m unittest src/friendapp/tests/test_streams.py
- src/friendapp/tests/test_sync.py — src/friendapp/sync.py のテスト(本物の Dropbox につながない = 偽の io。受信箱は本物の一時フォルダ)。
- src/friendapp/tests/test_tidy.py — フォルダの整理(friendapp/tidy.py)のテスト。一時フォルダに見本のアプリのフォルダを作る(本物の友人のフォルダ・作業データには触らない)。
- src/friendapp/tests/test_toolcheck.py — src/friendapp/toolcheck.py と places の道具の置き方(F3-5)のテスト。本物の道具・文字起こし・ネットは動かさない(偽の run・偽の transcribe)。
