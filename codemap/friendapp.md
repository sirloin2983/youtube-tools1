# コードの地図: src/friendapp(友人の玄関)

自動で作った物(`python dev/code_map.py`)。手で直さない。目次は [index.md](index.md)。`file:line` の行の番号は作った時点の物。

## src/friendapp/

- **__init__.py** (2 行) — 友人の玄関(FriendApp。友人の PC の 2 つ目の玄関。資料の git:before-1028-cleanup:docs/design/friend-history.md の 7 章)。ytt と ② flow だけを読む(③ human は読まない)
- **api.py** (994 行) — 友人の玄関の口の中身(F3-3。HTTP の形は server.py。ここは欄の検査・② への受付・送った物の進み具合と取り消し・失敗のやり直し・前回の値)。
  - 名前: `class FormError` :64・`live_auto` :73・`oembed` :81・`probe_live` :86・`guess_streamer` :92・`file_title` :101・`clean_ranges` :107・`fit_name` :126・`class Api` :135・`fsio_inside` :956・`rowtitle` :963
- **diag.py** (328 行) — 友人のアプリの診断の記録(ユーザー決定。notes:docs/spec/friend.md の 13-11)。友人の PC でしか出ない不具合を、伝聞でなく記録で追うため。
  - 名前: `add_secret` :58・`mask` :74・`windows_text` :97・`stage_rows` :108・`transcribe_rows` :123・`probe_only` :136・`prune_names` :142・`class Diag` :153
- **dropbox.py** (462 行) — 友人の玄関の Dropbox の部品(資料の git:before-1028-cleanup:docs/design/friend-history.md の 7 章・docs/spec/friend.md の 2-17・4 章)。
  - 名前: `class DropboxError` :42・`class Cancelled` :58・`class Config` :62・`config_path` :78・`load_config` :83・`missing_scope` :97・`is_not_found` :102・`error_text` :106・`arg_header` :132・`commit_arg` :137・`content_hash` :143・`urlopen_transport` :172・ほか 1
- **ed25519.py** (126 行) — Ed25519 の署名と確かめ(RFC 8032 の 6 章の参照の形・純 Python。安全面の直し 1・10-29)。
  - 名前: `public_key` :96・`sign` :103・`verify` :113
- **engine.py** (538 行) — 友人の玄関の ② の組み立て(flow の部品を糸つきで持つ)。
  - 名前: `stage_lines` :41・`transcribe_line` :57・`transcribe_lines` :77・`transcribe_records` :83・`export_records` :103・`class FriendQueue` :122・`class Engine` :147・`live_cause` :502
- **inbox.py** (1312 行) — 友人の受信箱の正(notes:plan/done/f1-friend-requirements.md の C-3、資料の git:before-1028-cleanup:docs/design/friend-history.md の 7 章)。
  - 名前: `pack_name` :87・`pack_title` :93・`unique_dest` :97・`case_of` :105・`class Inbox` :116
- **live.py** (54 行) — 友人の玄関のライブの依頼の欄と結びつき(資料の git:before-1028-cleanup:docs/design/friend-history.md の 7 章、docs/spec/friend.md の 2-15)。軽い部品だけ(画面を先に出すため)。
  - 名前: `fixed` :23・`check_settings` :28・`settings_label` :50
- **live_session.py** (346 行) — 友人の玄関のライブ係(資料の git:before-1028-cleanup:docs/design/friend-history.md の 7 章、docs/spec/friend.md の 2-15)。
  - 名前: `recorders` :37・`class FriendLive` :46
  - 受ける口: `/api/queue/add` :92・`/api/queue` :95
- **oplog.py** (137 行) — 友人のアプリの操作の記録(形の正は notes:plan/友人の不具合の自動対応-1025.md の「操作の記録」)。
  - 名前: `day_name` :32・`clean_ui` :47・`class OpLog` :91
- **places.py** (251 行) — 友人の玄関の置き場所(資料の git:before-1028-cleanup:docs/design/friend-history.md の 7 章)。
  - 名前: `home` :36・`data_root` :48・`friend_dir` :56・`cookies_path` :60・`outbox_dir` :65・`is_maker_data` :69・`tool_env` :98・`lay_tools_shallow` :119・`lay_whisper` :147・`api_key_env` :172・`members_env` :186・`first_roster` :197・ほか 1
- **progress.py** (285 行) — 友人のアプリの「送った物」の行に出す、失敗の言葉と進み具合を作る部品(F3-3。notes:plan/done/f1-friend-requirements.md の C-2-15・C-2-16)。純粋な関数だけ(ファイルもネットも触らない。時計は引数で受ける)。
  - 名前: `classify` :106・`waiting_message` :129・`retry_note` :139・`stage` :181・`eta` :229・`slow` :248・`text` :266
- **report.py** (751 行) — 友人のアプリの状態の書き出しと、そのきっかけ(形の正は notes:plan/友人の不具合の自動対応-1025.md。受け取り側はユーザーの PC の別の部品)。
  - 名前: `fit` :63・`judge` :91・`live_cands` :132・`dir_bytes` :155・`class Reporter` :169
- **server.py** (1137 行) — 友人の玄関(資料の git:before-1028-cleanup:docs/design/friend-history.md の 7 章)。友人の PC の 2 つ目の玄関(ユーザーの PC は src/app/server.py)。
  - 名前: `save_dir` :125・`open_folder` :134・`pick_file_dialog` :150・`pick_folder_dialog` :190・`page_token` :227・`inject_meta` :234・`class Handler` :241・`client_log_line` :558・`class Server` :564・`class FriendApp` :583・`make_logger` :1017・`say` :1057・ほか 2
  - 受ける口: `/api/friend/client-log` :114・`/api/friend/state` :281・`/api/friend` :281・`/api/ping` :283・`/api/friend/inbox` :285・`/api/friend/tidy` :290・`/api/friend/update` :292・`/api/friend/setup` :294・`/api/friend/peek` :300・`/api/friend/player` :305・`/api/friend/receive` :307・`/api/friend/media` :310・`/api/friend/settings` :321・`/api/friend/streams` :323・`/api/flow/status` :325・`/api/friend/upload` :340・`/api/friend/peek-live` :386・`/api/friend/ops` :392・`/api/friend/send` :398・`/api/friend/pick-file` :403・`/api/friend/decide` :411・`/api/friend/undo` :413・`/api/friend/hold` :415・`/api/friend/files` :419・`/api/friend/report` :421・`/api/friend/prefs` :423・`/api/friend/retry` :426・`/api/friend/cancel` :430・`/api/friend/local` :434・`/api/friend/open` :438・`/api/friend/update/apply` :451・`/api/friend/update/now` :457・`/api/friend/streams/refresh` :462・`/api/friend/settings/key` :470・`/api/friend/pick-folder` :475・`/api/friend/notice-seen` :487・`/api/shutdown` :493・`/api/flow/submit` :497・`/api/flow/cancel` :506・`/api/ytt/streamer-colors` :510・`/api/ytt/client-log` :512
- **settings.py** (321 行) — 友人の玄関の ⚙(資料の git:before-1028-cleanup:docs/design/friend-history.md の 7 章)。
  - 名前: `class SettingsError` :45・`clean_key` :50・`looks_like_key` :54・`judge` :59・`probe_key` :87・`check_key` :101・`keys_path` :109・`load_key` :113・`save_key` :118・`check_folder` :127・`class Settings` :152
- **setup.py** (967 行) — 友人の玄関の初回の取得(資料の git:before-1028-cleanup:docs/design/friend-history.md の 7 章)。
  - 名前: `class FetchError` :65・`class Cancelled` :69・`safe_relative` :78・`problem` :94・`parse_item` :123・`load` :133・`archive_name` :157・`expect` :165・`folder` :170・`marker` :174・`label` :178・`is_done` :187・ほか 11
- **signing.py** (72 行) — 更新の署名(安全面の直し 1・10-29 決めた事 1〜3。案 A = Ed25519・公開鍵を src に焼き込む)。
  - 名前: `canonical` :20・`load_keys` :26・`check` :44・`accept` :61・`sign` :67
- **streams.py** (559 行) — 友人のアプリの「送る」画面の左に並べる、ホロライブ JP(と DEV_IS)の配信の一覧(F3-2)。API キー無し。
  - 名前: `parse_rss` :159・`classify` :191・`class Streams` :261
- **sync.py** (1123 行) — 友人の玄関の Dropbox の同期(資料の git:before-1028-cleanup:docs/design/friend-history.md の 7 章、docs/spec/friend.md の 2-14〜2-17・5-1)。
  - 名前: `class SyncError` :100・`name_ok` :105・`out_kind` :111・`clean_text` :123・`clean_origin` :128・`parse_meta` :139・`parse_meta_info` :145・`failure_text` :165・`server_time` :172・`safe_rel` :180・`safe_join` :187・`local_name` :197・ほか 14
- **tidy.py** (622 行) — アプリのフォルダの整理(形は Fable と相談 = 共有のメモ f3a-tidy-design.md。決定 3-86)。新しい版に入れ替えて起動できたあとと ⚙ から。
  - 名前: `keep_floor` :76・`class Tidy` :161・`prune_old_files` :597・`prune_diag` :615
- **toolcheck.py** (111 行) — 友人の PC の初回の準備の最後の「道具を動かして確かめる」(F3-5。notes:plan/done/f1-friend-requirements.md の C-5-2・C-0)。
  - 名前: `run_cmd` :26・`check_tool` :37・`check_tools` :53・`make_wav` :58・`whisper_run` :68・`check_whisper` :76・`signature` :97・`failed` :109
- **upgrade.py** (525 行) — 友人のアプリの更新の決まり(いつ入れ替えるか・重要な直し・新しい版の確かめと戻し・心拍・固まり)。
  - 名前: `vt` :60・`wait_reason` :67・`verify_sec` :84・`typical` :92・`beat_doc` :98・`class Upgrade` :108
- **voicesend.py** (124 行) — 友人の PC から送る声の材料(10-24 夜。ユーザー「誰の声をメンバー全員分」。案 = 資料の git:before-1028-cleanup:plan/声の材料を友人のPCから-1024.md)。
  - 名前: `zip_name` :33・`build` :46
- **ytdlp_update.py** (186 行) — 友人の PC の yt-dlp をいつも新しく(YouTube の bot 判定・仕様の変更に古い yt-dlp は当たりやすい。notes:docs/spec/friend.md の 13-13)。
  - 名前: `record_path` :56・`latest` :63・`probe` :75・`version_of` :85・`mark_ok` :93・`update` :98・`enabled` :151・`maybe_start` :155・`facts` :179

## src/friendapp/ui/

- **friend.js** (133 行) — 友人のアプリの共通の部分(F3)。口は friendapp/server.py の説明。外から来た文字(題・名前・理由)は textContent でだけ入れる。
- **host.js** (92 行) — 窓と画面の境目(F3-1。notes:plan/done/f1-friend-requirements.md の C-1、資料の git:before-1028-cleanup:docs/design/friend-history.md の 7 章)。
- **oplog.js** (138 行) — 操作の記録と画面の要約を玄関へ送る(形の正は notes:plan/友人の不具合の自動対応-1025.md。玄関は friendapp/report.py・oplog.py)。
- **palette.js** (13 行) — 友人のアプリの配色: ピンク(ui-kit のシンセウェーブ = 暗い・data-palette=synth)に固定する(配色 4 つの切り替えは 10-24 に無くした)。
- **receive.js** (389 行) — 受け取る画面(F3-4。notes:plan/done/f1-friend-requirements.md の C-3)。口 = GET api/friend/receive(friendapp/inbox.py の receive_view)・
- **send-form.js** (495 行) — 送る欄(F3-3。notes:plan/done/f1-friend-requirements.md の C-2-6〜C-2-13・C-2-17〜C-2-19)。口 = POST api/friend/send(friendapp/api.py の説明)。
- **send-list.js** (168 行) — 送る画面の配信の一覧(F3-2。notes:plan/done/f1-friend-requirements.md の C-2-2〜C-2-5)。
- **sent.js** (159 行) — 送った物(F3-3。notes:plan/done/f1-friend-requirements.md の C-2-14〜C-2-16)。行 = GET api/friend/inbox の rows のうち、まだ届け終えていない物と失敗。
- **settings.js** (376 行) — ⚙ 設定の引き出し(notes:plan/done/f1-friend-requirements.md の C-5-2・C-2-19)。
- **setup.js** (103 行) — 初回の準備だけの画面(notes:plan/done/f1-friend-requirements.md の C-5-1)。
- **update.js** (170 行) — 新しい版の帯の 1 行(更新。資料の git:before-1028-cleanup:docs/design/friend-history.md の 7 章)。

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
- tests/friendapp/test_signing.py — src/friendapp/ed25519.py・signing.py と dev/signing_key.py のテスト(更新の署名・安全面の直し 1)。
- tests/friendapp/test_streams.py — F3-2 友人のアプリの配信の一覧(friendapp/streams.py)のテスト。リポジトリ直下で: py -3.12 -m unittest tests/friendapp/test_streams.py
- tests/friendapp/test_sync.py — src/friendapp/sync.py のテスト(本物の Dropbox につながない = 偽の io。受信箱は本物の一時フォルダ)。
- tests/friendapp/test_tidy.py — フォルダの整理(friendapp/tidy.py)のテスト。一時フォルダに見本のアプリのフォルダを作る(本物の友人のフォルダ・作業データには触らない)。
- tests/friendapp/test_toolcheck.py — src/friendapp/toolcheck.py と places の道具の置き方(F3-5)のテスト。本物の道具・文字起こし・ネットは動かさない(偽の run・偽の transcribe)。
- tests/friendapp/test_upgrade.py — src/friendapp/upgrade.py(更新の決まり: いつ入れ替える・重要な直し・確かめと戻し・戻す印・取り消し・心拍・直しの版のやり直し・固まり)の境目のテスト。
- tests/friendapp/test_voicesend.py — 友人の PC から送る声の材料の通し(src/friendapp/voicesend.py → src/human/friend/voicein.py。10-24 夜)。
- tests/friendapp/test_ytdlp_update.py — src/friendapp/ytdlp_update.py(yt-dlp をいつも新しく)のテスト。ネットと yt-dlp は偽物(偽の http・偽の run)。
