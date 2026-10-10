状態(2026-10-10): RS7 の下調べ(Sonnet・medium)の報告(サブエージェントが本文で返した報告を、まとめ役が少し詰めて置いた)

# RS7 下調べ A・B・C: app/server.py・serve 3 本の骨組み・設定 1 ファイル

行番号は 2026-10-10 時点。推測は「推測」と書いた。

## A. app/server.py(入口 launch.py と mount.py)

### 今の形
- start.bat は `py -3.10 src\home\launch.py %*`。`src/app/` は `cli.py`・`tests/`・`ui/` だけ。**`server.py` も `host.py` も無い**。
- CLI(`src/app/cli.py` 531 行)は入口を起こさない: 入口が動いていれば `portal_at`(261)・`runtime_portal`(273)で頼む / 動いていなければ動画ファイルだけ `run_local`(407)で LocalTools。host.py は今は要らない(推測: 友人の PC で URL を CLI だけで流すとき・B-3 で要る)。
- `launch.py`(1338 行):
  - 小物 114〜264: `_spec` 114・`runtime_dir` 132・`ping` 142・`port_open` 147・`tail` 153・`expected_version` 174・`tool_python` 180・`signal_stop` 190・`app_data_dir` 253・`logs_dir_for` 259。`Tool` 203〜252
  - `Supervisor` 265〜550(約 285 行): `start` 311・`_mount` 331・`_spawn` 361・`start_all` 385・`stop` 390・`restart` 419・`stop_all` 423・`_tick` 450・`_on_exit` 486・`_monitor` 506・`close` 518・外部起動の検出 `_find_external` 295・`_mark_external` 353
  - HTTP の部品 551〜595(`query_int`・`read_json_body`・`site_ok`・`guarded_body`)
  - `PortalHandler` 596〜788: `do_GET` 622(60 行近い if の連鎖)・`do_POST` 678・`_post_case` 707・`_post_case_auto` 716・`_post_autorun` 723・`_post_intake_scan` 743・`_post_backup_run` 748・`_post_accuracy_run` 753・`_post_window` 759・`_post_cleanup` 769・`_post_shutdown` 777
  - 色 789〜807(`_color_entry`・`streamer_colors`・`hide_tokens`)
  - `PortalServer` 831〜1146: `ytt_api` 982・`prefs_api` 1035・`ytt_request` 1064・`handler_for` 1100・`teardown` 1121・`request_shutdown` 1137。入口だけの業務(`cleanup_candidates` 909・`purge_trash` 947・`_accuracy_*` 875〜・`streamer_guess` 1018)
  - `make_server` 1147・`make_logger` 1168・シグナル 1214〜1240・`main` 1263
- `mount.py`(231 行)は完成した層。`MOUNTS` 37・`load_serve` 77・`make_handler` 125(prefix を外し・合言葉・`/api/ytt/` を入口へ・CSP と meta)・`Mount` 184。serve に求める約束は `Handler`・`prepare`・`finish`・`SERVER_VERSION` の 4 つ。

### 最小の案
- `launch.py`・`mount.py` を `src/app/` へ `git mv`。旧い `launch.py` は runpy の転送(起動中の古い入口・start.bat 用。RS5-G と同じく起動し直しのあとに消す)。効果は名前の整理だけ。
- 実質の最小は Supervisor・Tool・小物(114〜550・約 440 行)を `app/supervisor.py` に切り出すこと。Supervisor は mount と ytt だけを読む(推測)。

### 大きい案
- `do_GET`/`do_POST` の if の連鎖をルーティングの表に(studio の `POST_ROUTES` と同じ形。B と共用できる)。
- `PortalServer` の入口だけの業務を `manage/ops`・`manage/keep` へ。

### リスク
- 入口の起動し直しで `autorun-active.json` と録画の子プロセスが切れる。配信が止まっている時間に。
- Supervisor の後始末(SIGTERM/SIGBREAK)は変えない。
- `mount`/`launch` を名前で読む所が 27 ファイル(test_mount・e2e・`eval/tools/_evalcommon.py`・`dev/demo_env.py`・`eval_asr/alt/cloud/llm`)。

### 触るテスト
`test_launch.py`・`test_mount.py`・`test_window.py`・`test_live*.py`・`test_autorun.py`・`test_layering`・lint。e2e は `e2e_portal`・`e2e_window`。

## B. serve 3 本の骨組み

行数: studio 682・editor 833・cut2resolve 980。`httpsec`(Host/Origin/Fetch-Site の検査・send・read_json_body・token_ok・ExclusiveServer)と `runtime`(ping・write_runtime・install_stop_signals)は既に ytt に 1 か所。

3 本に残る同じ形のコード:
| 重なり | studio | editor | cut2resolve |
| --- | --- | --- | --- |
| Handler の安全検査の包み・`_guard` | 101〜115 | 370〜385・422〜429 | 659〜673 |
| `_send`・`_json`・`_fail`/`_err` | 117〜127 | 387〜408 | 674〜681 |
| `_read_json` | 130〜140 | 410〜420 | 701〜719 |
| 想定外の例外を 500 で | 142〜159 | 431〜445 | 683〜700 |
| `do_*` の振り分け | 161〜253 | 446〜460 | 721〜750 |
| `probe`・`make_server`(ポート探し・古い版の警告) | 438〜470 | 618〜640 | 838〜870 |
| `mounted_elsewhere` | 631〜638 | 777〜784 | 931〜939 |
| `main` | 640〜679 | 786〜832 | 941〜976 |
| `prepare`/`finish`/`busy` | 560〜628 | 714〜775 | 906〜928 |

違い: ルーティングの表の形(studio はモジュール変数・editor は `GET_API`/`POST_API` + if・c2r は毎回作る辞書)、状態の持ち方(studio はグローバル・editor は `ed_state`・c2r は `ctx`)。editor の `_ED_MODULES`(約 40 の名前の受付・`_modfwd.install` 198)は骨組みではなく互換の層 = 対象外。

単独起動: `main()` と `mounted_elsewhere` は取り込みに失敗したときの保険(`Supervisor._spawn` が `serve.py <port> --no-open` を子プロセスで)。`test_launch.py` が約束を検査。`make_server` + `Handler` はテストが実際に使う(studio の test_api ほか・c2r の test_serve・`_evalcommon`)。

- 最小の案: `ytt/serverkit.py` に `find_port`・`mounted_elsewhere`・`run_main`・例外応答と `_read_json` の mixin の最小形。**差し引き 約 100〜130 行減**。3 本の公開名は薄い包みで残す。
- 大きい案: Handler の mixin(安全検査・送り・読み・例外・振り分け)を継ぎ、ルーティングを `{(method, path): (fn, write)}` にそろえる。**約 250〜300 行減**(推測)。エラーの文言と JSON の形がそろう。
- リスク: エラーの状態コードと文言が変わると `test_serve.py`(100 参照)・`test_edit.py`(211 参照)が落ちる。状態の持ち方は無理に統一しない。mount の `Mounted(base)` が `mod.Handler` を継ぐ関係と `parse_request` の上書きに注意。`ALLOWED_HOSTS` は mount が書く。editor の modfwd に触らない。
- テスト: studio の test_api・test_robustness・test_handoff・test_rank_live・test_file_recovery / c2r の test_serve / 編集の一式 / test_mount・test_launch・test_ytt_core・契約テスト(単独)。e2e は e2e_ui・e2e_ui_mounted・e2e_edit_pack から 1〜2 本。

## C. 設定 1 ファイル

| ファイル | 持ち主・読み手 |
| --- | --- |
| `app/prefs.json`(autorun・streamer・keymap・intake・backup・hidden・live・accuracy) | `home/prefs.py`(`Prefs` 399)。読み手 autorun・live・`flow/live_*`・intake・backup |
| `studio/settings-ui.json`(analyze・review) | `human/review/store.py`(`SettingsFile` 449)・`flow/spec.py` の `STUDIO_UI_FILE`・`AutoRunner._tool_settings`(autorun.py 779〜) |
| `studio/settings.json`(outDir だけ) | `ytt/studio_env.py` 108〜192・`ytt/datadir.py` 115(置き場所の決定) |
| `studio/config.json`(API キー)・`registry.json` | 別物 |
| `transcribe/settings.json`(平ら。認識・パック・用語集・置換辞書) | `ytt/settings.py` の `load_settings`/`patch_settings`/`replace_settings`(185〜280)・`AutoRunner._tool_settings` |
| `recorder/settings.json`(folder だけ。prefs の `live.folder` と二重) | `pipeline/ingest/recorder.py` |
| `analytics/config.json` | `src/analytics/` |

- 読み書きの部品は `ytt/settings.py` の `SettingsFile`(62〜175)に既に 1 本。ファイルの数だけが 4 つ。画面は入口の `/settings`(`schema.json` が節 → 保存先)と 3 ツールの ⚙。
- ② の束との関係: `flow/spec.py` は設定ファイルを読まない。画面の設定 → 束は `AutoRunner.build_spec`(796)。束に入らない値は `Run.screen`。**CLI は設定ファイルを読まない**(`--spec` の束だけ)= 友人の PC では束のファイル 1 つで足りる。
- 最小の案: 新しいファイルを作らず、読み口を 1 つの関数(`ytt/settings.read_all` のような)に。書き手は変えない。行数はほぼ同じ。
- 大きい案: `app/settings.json` を新設し、起動時に 4 つをコピーで読み込む。影響は prefs・store・settings・studio_env・datadir・recorder・live・autorun・intake・backup と画面(schema・⚙・UIKit.settings・3 つの API)。行数はむしろ増え、速度には効かない。outDir は置き場所の決定に使うので別扱い(鶏と卵)。バックアップ・`DATA_ITEMS` も変わる。
- テスト: 3 つの test_settings_schema・test_settings・test_autorun・test_run・test_spec・test_backup・e2e_settings。

## まとめ(推測)
効果は B の大きい案(約 250〜300 行減)> A の Supervisor の切り出し(見通し)> C は小さい案で十分。A の server.py への移動は玄関(live・autorun)の分割と同じ段で入口を止めて。B は単独で入れられる(取り込みの口 `prepare`/`finish` は変えない)。host.py は今は作らない。
