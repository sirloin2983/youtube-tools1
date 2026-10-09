> 状態(2026-10-10 朝): 下調べ(読むだけ。Sonnet)の報告そのまま。行番号は 2026-10-10 の main(1b27688)のもの。順番と決めることのまとめは `plan/role-restructure.md` の 8 節「RS3・RS4 の手順の案」と `plan/decisions.md` の 3-25。

# RS3(入口 src/home・スタジオ src/studio の分)下調べ(読むだけ。2026-10-10)

> 調べた範囲: HEAD 1b27688 の作業フォルダ(未コミット変更なし)。計画 `plan/role-restructure.md`(3・4・5-3・5-5・7・8・9 節)・`plan/decisions.md` 3-22〜3-24・`dev/layer_map.py`・`dev/tests/test_layering.py`・
> `docs/design/role-restructure-map-2026-10-09.md`(関数ごとの行き先。**行番号は古い**ので使った所は今のコードで確かめ直した)・`docs/HANDOVER.md`。
> 数えるための小さな .py は scratchpad の `deps.py`・`readers.py`・`viol.py`・`viol2.py`(リポジトリは書き換えていない・テストは流していない。`viol*.py` は test_layering の `violations()` を呼ぶだけで、層の表を差し替えた what-if も出せる)。
> 先に結論: **向きの違反 49 件のうち 31 件が home/studio の分。残り 18 件は編集(ed_*)。層の表の 3 行を変えるだけで 31 → 16(全体 49 → 34)。残る 16 件は小さな継ぎ目(下の 2 節)で 0 にできる = RS3(home/studio)のあと全体 18。**
> そのために 1 つ計画と違う置き方を提案する(`live.py` と `autorun.py` を app に残す・`live_failures` を pipeline に置く)。5 節の要判断 1・2。

---

## 1. ファイルごとの表(行数は今の HEAD)

凡例: 行き先 = 提案(★ = 計画 7 節・layer_map と違う)/ 依存 = そのファイルが import する home・studio の兄弟と層の部品 / 読み手 = src 内で import する側(テストと dev は別欄)/
「別名」= lint の `# lint: keep 別名` を付けてよい差し替えない定数・純粋な関数。移すときの作法は RS2 のまま(`git mv` だけのコミット → 付け替えのコミット。層の中は兄弟を相対 import・外からは `from pipeline.export import live_export` の形。裸の名前で読まない)。

### 1-A 入口 src/home(27 ファイル + 画面)

| ファイル(行) | 行き先 | 分割 | 依存 | 読み手(src) | テスト(unittest / e2e) | 差し替え・転送の要点 |
| --- | --- | --- | --- | --- | --- | --- |
| `accuracy.py`(544) | RS4 で `eval/drill`(RS3 では prefs の継ぎ目だけ) | しない | prefs(:288 の lazy)・txindex・ytt | launch | test_accuracy(583)・`dev/tests/test_eval_asr.py:789` が `import accuracy`(パスで読む) | `_cfg` の失敗時の既定 `prefs_mod.DEFAULTS["accuracy"]`(:288-292)を、コンストラクタに渡す形に。RS4 で本体を移すとき test_eval_asr の読み方も直す |
| `appwindow.py`(295) | app(残す) | — | なし | launch | test_window・e2e_window | 触らない |
| `autorun.py`(1428) | **★ app(残す)**。出す物: 友人の届け(`_PoolRun` :214-225・`_file_analyze`〜`_deliver_failure` :1155-1428 約 275 行・POOL_* :88-91)→ `human/friend/`(mixin)/ 実行の記録の読み(`read_runs_log`・`_parse_rec`・RUNS_LOG・LOG_VERSION :236-289 ほか)→ `pipeline/runlog.py` | 3 つに | cases・clientlog・deliver・friend_feedback・prefs(:57-70)・txindex(:57)・pipeline.run/spec | launch・live(lazy :400)・live_failures(lazy :146) | test_autorun(2450。`A.RUNS_LOG`・`A.read_runs_log` を使う = 別名で残す)・e2e_autorun・e2e_portal | あとから解析(約 250 行)は残す(3-B)。`AutoRunner` は Runner を継いで hook を埋める役 = 案件・設定・友人の届けを知ってよい app の仕事(`pipeline/run.py:11-14` の docstring が「層の向きの上で ① に置けないため RS3 で分ける」と書いていた所)。友人の届けは `human/friend/delivery.py` の mixin にして `class AutoRunner(Delivery, run_mod.Runner)`(`self.cv`・`self.runs`・`self.log` を使うため。RS6 で外のクラスに)。`cases.remember_delivered`(:1269)は口(`remember=`)で受ける = human が manage を読まない |
| `backup.py`(399) | `manage/keep/backup.py` | しない | prefs(lazy :234)・ytt | launch | test_backup(342)・e2e_backup_ui(153) | DEFAULTS の失敗時の既定を注入。`py -3.10 src/home/backup.py --restore` の説明(docstring :17・README・docs/spec/data-location.md)のパスを直す |
| `cases.py`(668) | `manage/cases/cases.py`(**丸ごと**。中の ごみ箱系 `discard_clip`・`_to_trash`・`_put_back`・`_write_manifest`・`expire_unseen` 約 180 行は同じ manage 層なので今は割らない) | しない(★ 計画の「auto_review は human/review」は採らない: 全部の相手が引数で渡される `deliveries`・`studio`・`feedback`・`trash`・`hide` で、書くのは案件の記録だけ) | cleanup・live_failures・txindex・ytt(:48-51)。lazy `live_export`(:194) | autorun・friend_feedback・launch・live(lazy :704) | test_cases(516)・test_accuracy が一部 | `friend_feedback` が `cases.discard_clip`・`cases.ReviewError` を読む(:17,:105-106)→ 口で渡す(2 節 #9)。launch が cases を呼ぶ所は `launch.py:681,:727,:872,:899,:918,:1035-1039` |
| `cleanup.py`(352) | `manage/keep/cleanup.py` | しない | ytt のみ | cases・launch | test_cleanup(190)・test_cases・test_friend_feedback | 軽い |
| `clientlog.py`(94) | `manage/ops/clientlog.py` | `append_line`(:28-34)だけ `ytt/fsio` へ | ytt.fsio | autorun(:67)・launch・live_export(:61) | test_window(画面のエラーの記録) | `append_line` を使う 3 か所(autorun:771・live_export:483・clientlog:92)を `fsio.append_line` に。`analyze._append_line`(studio :235)と近い二重だが別件 |
| `deliver.py`(387) | `human/friend/deliver.py` | しない | intake(:25 の `BAD_NAME_CHARS`・`OUT_DIR`)・ytt | autorun・launch・live | test_deliver(450)・test_cases | 同じ human/friend の中の相対 import になる。`Deliveries`(:315〜)は launch が作る(`launch.py:868`) |
| `friend_feedback.py`(131) | `human/friend/friend_feedback.py` | しない | cases(:17)・ytt | autorun・intake・launch | test_friend_feedback(119)・test_autorun | `apply(logs_dir, fb, trash=…, log=…)` に `discard=` を足す(launch が `cases.discard_clip` を渡す)。`ReviewError` は ValueError の子なので `except ValueError` に |
| `health.py`(366) | `manage/ops/health.py` | しない | ytt のみ | launch | test_health(281) | 軽い。`live_probe`・`accuracy_probe`・`worker_probe` は launch が渡す口のまま |
| `intake.py`(880) | `human/friend/intake.py` | しない(RS0-k の二重 `youtube_id`・`parse_ranges`・`_normalize_copy` の寄せは任意) | friend_feedback・live_requests・prefs(lazy :421)・ytt | deliver・launch・live(`OUT_DIR`) | test_intake(967)・e2e_intake_ui(233) | `_cfg` の既定を注入(:420-422)。`STUDIO_FAKE` の分岐(:152)はそのまま(RS5)。`live.py` が `OUT_DIR` を読む(:85)→ app なので可 |
| `launch.py`(1347) | app(残す。RS5 で `app/server.py`) | — | 全部 | — | test_launch(999)・test_accuracy・e2e 全部・`dev/demo_env.py:180` | import 行(:79-95)と作る所(:858-878)を直すだけ。**`start.bat:21` が `src\home\launch.py` を起動**・`restart.py` が同じパスで新しい入口を起こす = 動かさない |
| `live.py`(1238) | **★ app(残す)**(計画 7 節では pipeline。5 節の要判断 1) | しない | live_export・live_archive・live_cleanup・live_failures・live_detect・live_requests・live_tx・live_report・deliver・intake(:78-85)。lazy autorun(:400)・cases(:704) | launch | test_live(2027)・test_live_detect・test_live_tx・e2e_live* | 録画元の操作・画面の中継・友人の依頼・片付け・見回り `_tick`(:1122-1129)・調子 `health` を 1 つのクラスで束ねる玄関 = 合成の役(map 3 節の内訳: ingest 489・app 263・analyze 110・friend 103・ops 51・export 55・keep 33)。リーフ(下)を移すので import だけ直す |
| `live_align_worker.py`(132) | `pipeline/ingest/live_align_worker.py` | しない | なし(numpy。**入口のプロセスでは import しない**) | なし(`live_archive.py:74` がパスで子プロセス) | test_live_archive・e2e_live_archive(本物を起動) | **旧い場所に runpy の転送スクリプト**(起動中の古い入口が `live_archive.WORKER` でパス起動するため。`src/editor/tx_worker.py` と同じ作り) |
| `live_archive.py`(1488) | `pipeline/ingest/live_archive.py`(P4 の作り直し 926 行 + M7 の配信後の全自動 222 行などが 1 つ。**割らない**。run との統合は RS6) | しない | live_export・live_failures・txindex(:68,:1145) | live・live_cleanup | test_live_archive(1267)・e2e_live_archive(846) | `txindex.pack_info(speed)`(:1145)を `pack_info=` の口で受ける(Live が渡す)。WORKER(:74) は新しい場所のスクリプトへ |
| `live_cleanup.py`(306) | `manage/keep/live_cleanup.py` | しない | live_archive・live_detect・live_export・live_failures(:33-36) | live(`Live.cleaner` :380-387) | (直接のテストなし。test_live 経由) | manage → pipeline で向きは合う。`Cleaner(live, hold=…)` は duck typing |
| `live_detect.py`(707) | `pipeline/analyze/live_detect.py` | しない(人の採用 `decide`・`api_post` は RS6) | live_excite_worker(:49 `EW`)・live_export・live_failures・excite | live・live_cleanup | test_live_detect(1798)・e2e_live_studio | `WORKER`(:54)は新しいスクリプトへ。**旧パスに転送**。`import live_excite_worker as EW`(同じプロセスに読む)は相対 import に |
| `live_excite_worker.py`(1562) | `pipeline/analyze/live_excite_worker.py` | しない | excite・ytt(:55-60)。標準ライブラリだけ(numpy 不使用) | live_detect | test_live_detect(`import live_excite_worker as W`)・fixtures `tests/fake_excite_worker.py`(131)・`fake_ytdlp_chat.py`(81) | `ROOT = dirname(HERE)`(:56)は src が 2 つ上になるので直す(スクリプトとして動いたときだけ sys.path に足す = RS2-9d の worker.py の形)。**旧パスに runpy の転送**(落ちて起動し直すとき・メモリ超過の終了コード 3 のとき入口が旧パスで再起動する)。fake_excite_worker は e2e_live_studio が `TESTS` から読む(:888) |
| `live_export.py`(1180) | `pipeline/export/live_export.py`(MarkStore 133 行・採用の記録 `feedback` 10 行などの人の側は今は割らない = RS0-d) | しない | clientlog(:61)・live_failures(:62)・ytt | cases(lazy)・live・live_archive・live_cleanup・live_detect・live_failures(lazy)・live_report・live_tx | test_live(`LX`)・test_live_archive・test_live_detect・test_live_tx・e2e_live*(`LX.xxx = …` の差し替えが多い) | `clientlog.append_line`(:483)→ `fsio.append_line`。`live_failures` は pipeline に移る(下)ので向きは合う |
| `live_failures.py`(171) | **★ `pipeline/live_failures.py`**(計画は manage/ops) | しない(任意で `Reader`・`collect` を別) | autorun(lazy :146)・live_export(lazy :156) | cases・live・live_archive・live_cleanup・live_detect・live_export・live_report | test_live(`FailuresTest`)・test_live_detect | 失敗の文を作るのは pipeline の 4 モジュール(export・detect・archive・cleanup)で、ops は読むだけ。manage/ops に置くと pipeline → manage が 4 組できる。`read_runs_log` を `pipeline/runlog.py` に出せば autorun を読まなくなる |
| `live_report.py`(240) | `eval/tools/live_report.py`(計画どおり) | しない | live_export・live_failures・ytt | live(`Reporter(self)` :295) | test_live_detect | eval → pipeline で向きは合う。読み手の `dev/eval_marks.py --live` はファイルを読むだけ(モジュールは読まない) |
| `live_requests.py`(124) | `human/friend/live_requests.py` | しない | ytt のみ | intake・live | test_intake・test_live(`LiveRequestsStoreTest`) | 軽い |
| `live_tx.py`(346) | `pipeline/transcribe/live_tx.py` | しない | live_export(`LX`)・ytt | live | test_live_tx(695)・test_live_detect | `WORKER`(:25)を新しい場所へ。pipeline どうしの import は絶対 import |
| `live_tx_worker.py`(63) | `pipeline/transcribe/live_tx_worker.py` | しない | `pipeline.transcribe.tx_engines`(関数の中) | なし(live_tx が子プロセスで) | test_live_tx(`import live_tx_worker as TW`) | `_paths()`(:15-19)の `src = dirname(here)` は 2 段上に。**旧パスに転送**。テストの「入口で tx_engines・numpy を import しない」(test_live_tx:687) |
| `mount.py`(226) | app(残す) | — | ytt | launch | test_mount(612。単独で流す) | studio の部品が減ると `tool_modules(studio)`(:56-63)が小さくなる(1-B) |
| `prefs.py`(489) | app(残す。`ytt/settings` への統合は RS5「設定 1 ファイル」) | しない | ytt.settings | accuracy・autorun・backup・intake・launch | test_settings_schema・多数 | 他から読まれるのは `DEFAULTS[節]`・`INTAKE_RANGES`・`guess_streamer`・`Prefs.remember` だけ(2 節 #1・#8・#10・autorun)。各持ち主が既定を引数で受ければ prefs を読む必要が無くなる |
| `restart.py`(164) | `manage/ops/restart.py` | しない | ytt | launch | test_restart(243)・test_launch | 新しい入口を起こす先 `src/home/launch.py` は動かさない |
| `portal.*`・`settings/`・`vendor/`・`start_hidden.vbs` | app(残す。RS5 で app/ui) | — | — | — | e2e_portal・e2e_settings | `vendor/hls.min.js` は `live.py:88` の `CODE_DIR/vendor` で配る = live.py を home に残すので動かさない |

### 1-B スタジオ src/studio(8 ファイル + 画面)

| ファイル(行) | 行き先 | 分割 | 依存 | 読み手(src) | テスト | 差し替え・転送の要点 |
| --- | --- | --- | --- | --- | --- | --- |
| `common.py`(662) | **分解**: ① `ytt/procs.py`(spawn・forget・children・stop_children・run_short・hard_kill・terminate・idle_message・run_capture :332-514 約 185 行)② `ytt/` のメディア情報(`media_info*`・キャッシュ :288-331 約 45 行)③ `ytt/` の置き場所・書き出し先・疑似の旗(`set_home`・`home`・`p`・`fake`・`*_out_dir`・`_out_lock`・`set_out_dir` :58-78,:515-601 約 150 行)④ API キー(`KEY_RE`・`get_api_key`・`set_api_key` :184-206)⑤ 小物(`redact`・`log_failure`・`permission_message`・`tail_reason`・`fmt_ts`・`fmt_ms`・`num`・`watch_url`・`rotate_log`・`replace_file`・`atomic_write`・`find_tool` ほか 約 110 行)⑥ `pipeline/ingest/`(URL・動画ファイルの判定 `parse_video_id`・`check_live`・`check_media_path`・`file_video_id`・`ytdlp_out`・`MEDIA_EXT`・`LIVE_ID_RE` :207-286 約 80 行)⑦ 残す: 環境チェック `check_tools`・`env_state`(:602-662 約 60 行 = app)・`migrate_old_logs`(:127-137 = studio の起動時だけ)・`_load_core` | 7 つに | datadir・fsio・tools | analyze・batch・handoff・rank・serve・store・txlink・**exporter**(pipeline/export。`import common`) | 12 ファイル 約 360 参照(test_robustness 91・test_analyze 51・test_rank_live 42・test_studio 40・test_exporter 36・test_api 30 …) | 殻 `common.py` を `ytt/modfwd.install` で残す案(RS2 の ed_jobs と同じ。テストの `C.xxx = …` が本物の持ち主へ届く。RS5 で消す)。`ApiError`・`Cancelled` は `ytt.errors` に 1 つ(`serve.py:121` は `e.extra or {}` で読むので ytt.errors.ApiError で互換)。**`CODE_DIR` から決めている物が 4 つ**: ① data の既定の置き場所 `_home = override or CODE_DIR`(:40) ② `rank.SEED`(:37) ③ `handoff.runtime_dir`(:40) ④ `txlink.tx_folder`(:15)。serve が渡す形に |
| `analyze.py`(1032) | `pipeline/analyze/analyze.py`(precedent: `pipeline/pack/pack.py`)。feedback の書き手(約 135 行 :136-262)は `human/review/feedback.py` へ(任意。store が読むので向きは合う) | 任意 | common(:21-22 多数)・excite | batch・serve・store | test_analyze(251)・e2e_analyze・test_api・test_robustness・test_settings_schema・home の test_live_detect | 疑似の分岐 5 か所(:268・:412・:495・:580・:695)は `common.fake()` のまま(= ytt の旗。RS5 で `eval/fake` の口)。**`STUDIO_FAKE_CHAT_DELAY`(:414-421)は 3-C で消してよい** |
| `batch.py`(283) | `pipeline/batch.py`(`run.py` の兄弟。`run.py:16` の「兄弟モジュールにする」) | しない | analyze・common・store(**`now_ms` の 1 行 :12**) | serve | 直接のテストなし(test_api・test_robustness 経由) | `now_ms` を ytt へ(`ed_state.now_ms` とも二重)。`Batch(store)` は既に store を引数で受ける(`ensure`・`has`・`replace_auto` だけ使う)ので import は要らなくなる |
| `store.py`(1142) | `human/review/store.py`(**丸ごと**。★ 計画の「候補 → analyze・手動 → review に割る」は RS6 の上書きの置き場と一緒。RS0-d で確認済み)。`SeriesCache`(:402-445)と `_clean_reasons`・`_clean_parts`・`PART_KEYS`・`SERIES_KEEP`(約 94 行)は `pipeline/analyze` へ出してよい | 任意(94 行) | analyze(feedback・`LIVE_NO_ANALYZE`・`prune_cache`。human → pipeline で向きは合う)・common(:22-23)・ytt | batch・serve | test_studio(848) | 配信の登録(`ensure`・`delete`・`list`…約 170 行)と data.json の入れ物は同じ辞書・同じ `_save` を通るので割らない |
| `rank.py`(830) | `human/find/rank.py` + `seed.json` も移す(`SEED = CODE_DIR/seed.json` :37) | しない(疑似 API の塊 :102-208 約 109 行は rank に残す = RS5 で eval/fake) | common(`log_failure`・`watch_url`・`p`・`fake`・`YT_API_BASE`・`VID_RE`・`CODE_DIR`・`get_api_key`・`atomic_write`・`ApiError`・`Cancelled`) | serve | test_rank_live(251)・test_api・test_robustness・e2e_ui | `test_api.py:179` は `/seed.json` が配られないことを確かめる(パスの検査。動かしても結果は同じ) |
| `serve.py`(670) | app(残す) | — | 7 つの兄弟 + exporter + ytt | mount | test_api・test_robustness・e2e_ui・home の e2e | import 先を新しい場所に(`from pipeline.analyze import analyze` など)。`init`(:54-64)・`prepare`(:548-568)・`shutdown_jobs` は配線のまま |
| `handoff.py`(61) | **割る**: 切り抜きの記録 `manifest_path`・`clip_manifest`・`write_clip_manifest`(約 19 行)→ `pipeline/export/`、`runtime_dir`・`write_runtime`・`remove_runtime`・`siblings`(約 30 行)は studio に残す(app)。★ 計画の「manage/cases」は採らない | 2 つに | common | exporter(`handoff.write_clip_manifest` ×2)・serve | test_handoff(258)・test_exporter | `handoff.TOOL.update(...)`(`serve.py:38` が版を入れる)は残す側。`import http.client` の差し替えは siblings 側(残す) |
| `txlink.py`(35) | `manage/cases/txlink.py` | しない | common(`CODE_DIR` だけ :15)・txindex | serve | (test_api 経由) | `txindex.folder(dirname(CODE_DIR))` の根は serve が渡す |
| `*.js`・`*.css`・`index.html`・`seed.json` | studio に残す(RS5 で app/ui)。seed.json だけ rank と一緒に | — | — | — | test_review.cjs・e2e_ui | 触らない |
| (すでに移ってある)`pipeline/export/exporter.py` | — | — | **`import common`・`import handoff`**(裸の名前。studio/ が sys.path に居る前提 = RS1-4 の仮) | serve | test_exporter(36) | 上の common の分解のあと `from ytt import procs …`・`from . import manifest` に。`common._out_lock` と `set_out_dir`(:334)は書き出し先の状態と一緒に ytt へ |

### 1-C 入口の取り込み・起動がファイルをどう読むか(今と移したあと)

- **ホームの部品は裸の名前**: `launch.py:79-95` が `import autorun`・`import intake`…(`src/home` が `sys.path[0]` = スクリプトのフォルダ。`ROOT`=src は **append**・`launch.py:76-77`)。移した物は `from manage.keep import backup as backup_mod` の形に。層の決まりで、層のフォルダの部品を**裸の名前で読むと `test_no_bare_import_into_layer_packages` が落ちる**。
- **スタジオ・編集・cut2resolve は `mount.load_serve`**(`mount.py:76-100`): `<root>/<フォルダ>/serve.py` を別名 `ytt_tool_<ID>` で読み、そのフォルダを `sys.path[0]` に足す。ツールの中の部品(`common`・`store`…)は**裸の名前で同じフォルダから**読まれる。部品の名前が別のツールとぶつからないか(`check_no_collision` :66-73 は `tool_modules(フォルダ)` = serve・test_・e2e_・_ 以外の .py の名前)を読み込み前に見る。
  → **studio から部品が出ると `tool_modules(studio)` が空に近づき、衝突の検査が実質働かなくなる**。`test_mount.py:61-69,:597-612` は「studio の `common` と同名の偽モジュールを sys.modules に置くと取り込みに失敗して子プロセスに落ちる」ことを確かめている = `common.py` を殻で残す(提案)なら今のまま通る。残さないなら偽の名前を別の仕組み(`load_serve` を失敗させる)に替える。
  `test_no_duplicates`(`test_mount.py:49-56`)は home・studio・editor・cut2resolve・ytt_core の直下の名前だけを見る = 移した先(層のフォルダ)の名前は対象外(名前の重なりは層のテストの裸の名前の禁止が見る)。
- **studio の部品が出たあとの serve.py**: `common._load_core()`(:25-37)が `YTT_CORE_DIR` か 1 つ上の src を `sys.path` に足す = `pipeline`・`human`… が見つかる元。**殻の `common.py` を残すなら serve が最初に読む名前としてこの役を続ける**(単独起動・一時フォルダに写すテストのため)。
- **子プロセスで動くスクリプト(パスで起動)**: ① `live_excite_worker.py`(`live_detect.py:54` の `WORKER`。落ちる・心拍が 120 秒止まる・メモリ 512MB 超で終了コード 3 のたびに入口が起動し直す)② `live_align_worker.py`(`live_archive.py:74`。本番版への作り直しのたびに 1 回)③ `live_tx_worker.py`(`live_tx.py:25`。候補 1 本ごとに 1 回)。録画の部品 `src/recorder/recorder.py` は RS1-3 で転送済み、`restart.py` が起こす `launch.py` は動かさない、`accuracy.py` が起こす `dev/eval_*.py` は RS4。
  **古い入口(メモリに旧コードを持ったまま)が旧パスのスクリプトを起こすのは上の 3 つだけ**。旧パスに `src/editor/tx_worker.py`(runpy で新しい場所を `__main__` として動かす 18 行)と同じ転送を 3 つ置く(`layer_map.FILES` に「転送(RS5 で消す)」で)。lazy import(`live.py:400,:704`・`live_failures.py:146,:156`・`cases.py:194`)は、入口が起動中なら既に sys.modules にあるので古い入口でも壊れない(起動し直すまで古いコードが動くだけ)。
- **直接の読み手が home の外にあるもの**: `dev/demo_env.py:180`(`import launch`)・`dev/tests/test_eval_asr.py:789`(`import accuracy`)・`dev/lint.py:51`(`src/home/launch.py` の版)・`start.bat:21`。launch は動かさないので影響なし。accuracy は RS4。
- **テストが一時フォルダに写す形**: `layout.SHARED_CODE_DIRS`(`layout.py:29`)は `pipeline`・`human`・`manage`・`eval`・`app` を丸ごと写すので、新しいファイルを足しても各 e2e の「写す一覧」に足す必要は無い。studio のテストは `sys.path.insert(0, studio フォルダ)` + `import common`/`store`(`test_studio.py:11-14`)で読む = ここは書き換えが要る。

### 1-D テストの動かし方(RS1・RS2 の流儀に合わせる)

- **1 対 1 のテストは移した部品と一緒に**: test_backup・test_cleanup → `manage/keep/tests/`、test_health・test_restart → `manage/ops/tests/`、test_cases → `manage/cases/tests/`、test_intake・test_deliver・test_friend_feedback → `human/friend/tests/`、test_live_tx → `pipeline/transcribe/tests/`、test_live_archive → `pipeline/ingest/tests/`、test_studio → `human/review/tests/`、test_analyze → `pipeline/analyze/tests/`、test_rank_live → `human/find/tests/`、fixtures(`fake_excite_worker.py`・`fake_ytdlp_chat.py`)→ `pipeline/analyze/tests/`。
  動かすなら冒頭の `sys.path.insert(HERE…)`・`import xxx` を `from manage.keep import backup` に直す(`from ytt_core import fsio` は転送で動くが、直す機会に `from ytt import fsio`)。
- **残す(Live・AutoRunner・launch を通すもの)**: test_launch・test_mount・test_window・test_live・test_live_detect(`import live as LV`・`prefs as P`)・test_autorun・e2e 全部。import だけ直す。`test_live_detect.py` は `WorkerSimTest`・`ChatFeedTest`・`FfmpegTest`・`WorkerRestTest`(worker 単体)と `DetectApiTest`(Live を通す)が 1 ファイルに混ざっている。割るなら別の段(今は import だけ)。
- **差し替えの落とし穴**: `LX.xxx = …`・`mock.patch.object(L, …)` は「読む側が呼ぶたびにモジュールの属性を読む」形でなければ効かない(HANDOVER の注意)。名前を**別のモジュールに移す**物(例 `read_runs_log` → runlog、`append_line` → fsio)は、テストの差し替えの宛先を新しい持ち主に直す。移した名前を旧モジュールに `from x import y` で別名として残すと差し替えが本体に届かない(別名にしてよいのは差し替えない定数・純粋な関数)。
  差し替えの数(`assign` = モジュール属性への代入の行数): test_autorun 63・test_live 74・test_live_archive 69・test_live_detect 59・test_live_tx 31・test_mount 37・test_launch 22・test_deliver 20・test_accuracy 19・test_intake 23。`test_robustness.py:271` は `analyze.py` と `exporter.py` のソースを**パスで読んで**検査する(移したらパスを直す)。

---

## 2. 移したあとの向き

層の表(`dev/layer_map.py`)はもう計画どおりの行き先を持っているので、**ファイルを動かしただけでは違反は 1 件も減らない**。減るのは (a) 表の 3 行を替える (b) 継ぎ目を作る のどちらか。

### 2-A KNOWN の 49 件のうち home/studio の 31 件(`viol.py` の出力)と、直し方

| # | 組 | 何が原因か(根拠) | 直し方(口の案) | 段 |
| --- | --- | --- | --- | --- |
| 1 | eval accuracy → app prefs | 失敗時の既定 `prefs_mod.DEFAULTS["accuracy"]`(`accuracy.py:288-292`) | `defaults=` を引数で受ける(launch が渡す) | 0 |
| 2〜7 | pipeline autorun → cases・clientlog・deliver・friend_feedback・prefs・txindex | AutoRunner が案件(`find_pack` :302・`clip_live`/`AUTO_ORIGINS` :198-199・`read_studio`/`locations` :1065,:1105・`remember_delivered` :1269)・設定・友人の届け・txindex(:1061,:1078)を読む | **表を `app` に替える**(AutoRunner は hook を埋める役 = 合成)。友人の届けだけは human/friend の mixin に出す | 0 |
| 8 | manage backup → app prefs | `DEFAULTS["backup"]`(`backup.py:234-238`) | #1 と同じ | 0 |
| 9 | human friend_feedback → manage cases | `cases.discard_clip`・`cases.ReviewError`(`friend_feedback.py:17,:105-106`) | `apply(…, discard=…)` で渡す | 0 |
| 10 | human intake → app prefs | `DEFAULTS["intake"]`(`intake.py:421-422`) | #1 と同じ | 0 |
| 11〜17 | pipeline live → cases・deliver・intake・live_cleanup・live_failures・live_report・live_requests | `Live` が玄関(`live.py:78-85`・`cleaner` :380-387・`_tick` :1122-1129・`expire_unseen` :704・`_auto_deliver_for` :759) | **表を `app` に替える**(live.py は home に残す) | 0 |
| 18・20・22 | pipeline live_archive・live_detect・live_export → manage live_failures | 失敗の文を pipeline の 4 モジュールが作る(`live_export.py:387,:457,:475`・`live_detect.py:698-705`・`live_archive.py:1037,:1073`) | **`live_failures` を pipeline に置く**(表の 1 行)。`read_runs_log` を `pipeline/runlog.py` に出して autorun の lazy import(`live_failures.py:146`)をなくす | 0 |
| 19 | pipeline live_archive → manage txindex | `txindex.pack_info(speed)`(`live_archive.py:1145`)。パックの有無の規則は txindex だけ(AGENTS の決まり) | `pack_info=` の口(Live が `txindex.pack_info` を渡す)。または pack の記録の読み(`txindex.py:151-224`)を `pipeline/pack` に出して txindex が読む | 0 |
| 21 | pipeline live_export → manage clientlog | `clientlog.append_line`(`live_export.py:483`)。autorun も同じ(:771) | `fsio.append_line`(`clientlog.py:28-34` をそのまま) | 0 |
| 23 | pipeline exporter → app studio/common | `import common`(9 種の名前) | common の分解(1-B の ①〜⑤) | 1 |
| 24 | pipeline exporter → manage studio/handoff | `handoff.write_clip_manifest` ×2 | 切り抜きの記録を `pipeline/export` へ | 1 |
| 25 | pipeline analyze → app common | `common.p`・`terminate`・`fake`…(19 種) | common の分解 | 1 |
| 26・27 | pipeline batch → app common・human store | `common.find_tool`・`fake`・`stop_children`。`from store import now_ms`(`batch.py:12`) | common の分解。`now_ms` を ytt へ | 1(+0) |
| 28 | manage handoff → app common | `common.log_failure`・`CODE_DIR`(`handoff.py:40`) | 割ったあとの studio 側は app なので読んでよい | 1 |
| 29 | human rank → app common | 7 種 | common の分解 | 1 |
| 30 | human store → app common | `num`・`media_info`・`log_failure`・`find_tool`・`check_live`・`ApiError`・`atomic_write` | common の分解 | 1 |
| 31 | manage txlink → app common | `CODE_DIR` だけ | 根を引数に | 1 |

### 2-B 「設定と状態の束」を `ytt/settings` に寄せる必要があるか(RS0-a)

- **入口 `prefs.py`: RS3 では要らない。** 他の層が読んでいるのは `DEFAULTS[節]`(accuracy・backup・intake の 3 か所。`autorun.py:1203-1204` の `DEFAULTS["intake"]["deliverBatch"]`・`INTAKE_RANGES` は友人の届けに移る)と `guess_streamer`(`autorun.py:428`)・`Prefs.remember`(`autorun.py:1093` は渡された `self.prefs` のメソッド = import ではない)だけ。持ち主が既定を引数で受ければ prefs への依存は 0 になる。`Prefs`・`CLEANERS`・`DEFAULTS` の表は app に残る。「設定 1 ファイル」(旧 4 ファイルの読み込み)と検査の関数の持ち主への登録は RS5 のまま。
- **スタジオ `common.py` は寄せる必要がある**(ただし「設定」ではなく**ユーティリティと状態の束**。設定らしいのは置き場所 `home/p`・書き出し先・API キーの 3 つだけで約 180 行)。編集の `txenv`(「置き場所のパスと外の道具の一時の口」)とは別の形で足りる: studio の `set_home`/`set_out_dir` は `serve.prepare` が呼ぶ 1 つのモジュールの状態なので、`ytt` に同じ形の状態モジュールを 1 つ置けば移せる(名前は仮: `ytt/studio_env.py`)。`ytt/settings`(`SettingsFile`)に混ぜない。
- `fake()` の旗(`STUDIO_FAKE`)は pipeline が読むので ytt に置く(map の「common.fake は ytt」)。`eval/fake` に置くと pipeline → eval。登録の口への置き換えは RS5(疑似の分岐は analyze 5・batch 2・exporter 2・rank 1・serve 3・intake 1)。

### 2-C 見込み(KNOWN の件数。全体の 49 のうち)

| 時点 | 件数 | 減る理由 |
| --- | --- | --- |
| 今 | 49(home/studio 31 + 編集 18) | — |
| 表の 3 行だけ替える(autorun・live → app、live_failures → pipeline) | **34** | #2〜7・#11〜17・#18・#20・#22 の 15 件。コードは 1 行も動かない |
| 段 0 の継ぎ目(defaults ×3・discard・pack_info・append_line・runlog・now_ms) | **26** | #1・#8・#9・#10・#19・#21・live_failures → autorun・#27 の 8 件 |
| 段 4・5(studio の common 分解・manifest) | **18** | #23〜#26・#28〜#31 の 8 件 |
| 編集 RS3(別の調査) | 0 を目指す | 残りは `ed_*` → `ed_state`・`ed_relink`・`ed_drill`・`ed_misc`・`txindex`・`pipeline_io` 18 件 |

(`KNOWN_MAX` は段ごとに下げる。`dev/tests/test_layering.py` の `KNOWN` は件数が合っていないと「直った違反は消す」で落ちる。)

---

## 3. 消す物の今の状態(消すと何が変わるか)

### 3-A 「確認してから届ける」の経路(計画 9 節の決定。RS5 の項目)

「止めて待つ」形が 3 層に分かれている。**どこまでを指すかは決めが要る**(5 節の要判断 3)。

| 層 | 中身(根拠) | 消すと変わること |
| --- | --- | --- |
| L1 友人の依頼の ②「軽く確認」・③「全部人が行う」 | `intake.py:41`(`FLOW_LABELS`)・`:516`(**既定が `check`**)・`:518-553,:654-724,:759,:815-822` に flow が通っている / `autorun.py:74-75`(`FLOW_MODES`)・`start_request`/`start_file` の `flow=`(:527-571)・`_file_analyze`(:1155)/ `pipeline/run.py:35-37,:41-45`(`request`・`file`・`request_manual`・`file_manual` の段の表)/ 友人のアプリ `Core.cs:24-27,:328,:354,:385,:403,:445-447`・`MainForm.cs:60-65,:242〜`(「02 仕上げ方」の 3 択) | 友人が ②③ を選べなくなる(アプリの更新が要る)。**アプリが ②③ を送ってきたとき**の扱いを決める(サーバーが ① に読み替える / 断る / 残す)。文書 `docs/spec/friend-intake.md` の 2-2。コード約 80 行・テストは test_intake(flow の言及 34 行)・test_autorun の `TestRequests`(790 行のうち ②③ の分)・e2e_intake_ui・C# のテスト |
| L2 自分のライブの `after`(none/check/auto) | `live_export.py:24,:79,:155-166,:205-210,:1079-1116`(`AFTERS`・`check_after`・`job_after`・`_handoff`)・`prefs.py:67,:286`(**既定が `"check"` = 文字起こしまで**)・`settings/schema.json:44`・`live.py:345-353`(`auto_cfg`)・`autorun.py` の `start_file(flow=after)` | 配信中・配信後の自動の切り抜きが、既定で「文字起こしまで」から「パックまで」に変わる(計画 5-4 の「`after` 無し・常にパックまで」)。設定の画面の項目が 1 つ消える。保存済みの設定の `live.auto.after` は読み捨て |
| L3 手で届ける操作 | 編集の「友人へ届ける」`pack-tab.js` の `#pkDeliver` + `launch.py:1008-1012`(`api/ytt/deliver`)+ `deliver.Deliveries`(:315〜)/ 案件の「採用して届ける」`cases.auto_review` の `deliver`(:363-389)+ `portal.js:512,:545,:619,:764` | **計画の 5-3「終わってから直して、その段からやり直す」の受け皿(パックの作り直し → 自動で届く)がまだ無い**ので、今消すと直したパックを友人に渡す手段が無くなる。RS6 のあとが筋 |

→ 提案: RS3 は**移すだけ**(L1〜L3 とも)。L1 はアプリの更新と合わせて RS5。L3 は RS6 の「直したらその段からやり直す」ができてから。

### 3-B 「あとから解析(測るため)」

- コード: `autorun.py` に約 250 行(定数 :92-102・`_defer_eligible` :228-233・init :308-318,:339-341・`_preempt_deferred`/`stop_deferred` :660-675・`_defer_*` と `deferred`・`_start_deferred` :795-1002)。`pipeline/run.py`(`POST_MODE`・`OTHER_MODES` :58-59・`restore` が弾く :179・`_weights_differ` の分岐 :438)。`launch.py:938-941`(restart_self が止める)。`health.py:152-154`(失敗の数から除く)。`portal.js:32-35,:1864`(案件の行の札)。環境変数 `YTT_DEFER_ANALYZE`。データ `logs/autorun-deferred.json`(残る)。
- テスト: test_autorun の `TestDeferred`(:1965-2295 約 330 行)・test_launch 3・test_health 1・e2e_portal 2。
- 変わること: 画面は案件の行の「あとから解析」の札が消える・restart_self の分岐が 1 つ減る。**測定の側**: 友人が区間だけで送った配信は、今は idle のときに自動で解析されて `dev/eval_marks.py` の `friendRanges`(友人の区間 ↔ 自動の候補)の材料になる。消すと新しい材料が溜まらない(既にあるものは残る・`eval_marks` は未解析の配信を別に数える)。計画の「④ の道具で代える」道具はまだ無い → **代わりの道具(`dev/eval_marks.py` に未解析の友人の配信だけ解析するコマンド)を RS4 で作ってから消す**のが筋。idle のときの CPU・ネットワーク(音声・チャットの取得)の負荷はなくなる。
- RS3 への効き方: 動かし先は app の autorun.py の中(移さない)ので、**RS3 では消さなくてもコストは増えない**。

### 3-C 死んだフック

| フック | 今 | 消すと |
| --- | --- | --- |
| `STUDIO_FAKE_CHAT_DELAY` | `studio/analyze.py:414-421`(疑似モードでチャットの取得を遅らせ、中の `skip`/`cancel` を待つ 8 行)。使うテスト 0(リポジトリ全体の grep で analyze.py と文書だけ) | 画面・設定・テストに変化なし。`STUDIO_FAKE=1` のときだけ効く部分。analyze を移す前に消すと移す行が減る(段 0 に入れてよい) |
| `YTT_RECORDER_SOURCE` | `pipeline/ingest/recorder.py:301`(`--source` の既定を環境変数から取る 1 行)と `rec_core.py:12` の説明。**`--source direct` そのものは生きている**(test_recorder:37,:631・e2e_live:127・e2e_live_archive:215・e2e_live_studio:12 が引数で渡す) | 環境変数を読む既定だけ消す(`default="streamlink"`)。変化なし。`--source direct` の偽の録画元を `eval/fake` の口に移すのは RS4/RS5 の別件 |
| `TRANSCRIBE_FAKE_REDO` | RS2 で消し済み | — |

---

## 4. 段の案

### 4-A 段とコミット(AGENTS の流儀: 移動と付け替えを別コミット・`git mv` は 1 コミットにまとめて WORKLOG で告知)

| 段 | 中身 | 並列 | 通すもの(まとめ役が流す) | 違反 | 目安(AI の作業の長さ) |
| --- | --- | --- | --- | --- | --- |
| **RS3-0 下ごしらえ** | ① 表を替える(autorun・live → app、live_failures → pipeline)② `pipeline/runlog.py`(`read_runs_log` ほか)③ `fsio.append_line` ④ `now_ms` を ytt へ ⑤ defaults ×3・`friend_feedback` の `discard=`・`live_archive` の `pack_info=` の口 ⑥ 死んだフック 2 つ | 1 人(Sonnet)。ファイルは home の 10 前後・小さい | home の unittest 一式・`test_layering`・lint 0 | 49 → 26 | 1〜1.5 時間 |
| **RS3-1 live の葉** | `live_export`→export、`live_detect`+`live_excite_worker`→analyze、`live_archive`+`live_align_worker`→ingest、`live_tx`+`live_tx_worker`→transcribe、`live_failures`→pipeline、`live_report`→eval/tools、`live_cleanup`→keep。旧パスの転送 3 つ(excite・align・tx)。テストと fixtures の付け替え | Wave A の 1 人(**Opus**。本番の配信が動く所・子プロセスの転送・numpy を入口で読まない約束) | test_live・test_live_detect・test_live_archive・test_live_tx・test_live_* の e2e 3 本(1 本ずつ) | 26(動かすだけ) | 2.5〜3.5 時間 |
| **RS3-2 keep・ops** | `backup`・`cleanup`→keep、`health`・`clientlog`・`restart`→ops | Wave A の 1 人(Sonnet) | test_backup・test_cleanup・test_health・test_restart・test_window・test_launch・e2e_backup_ui | 26 | 1.5〜2 時間 |
| **RS3-3 cases・friend** | `cases`→cases、`intake`・`deliver`・`live_requests`・`friend_feedback`→friend、AutoRunner の友人の届けを `human/friend/delivery.py` の mixin に | Wave A の 1 人(Sonnet〜Opus。`autorun.py` を触るのでここだけ) | test_cases・test_intake・test_deliver・test_friend_feedback・test_autorun・test_accuracy・e2e_intake_ui・e2e_autorun | 26 | 2〜3 時間 |
| **RS3-4 studio の common の分解** | 1-B の ①〜⑦。`ytt` に `procs`・メディア情報・`studio_env`・API キー・小物、`pipeline/ingest` に URL・動画の判定。`common.py` は殻 + `modfwd`。`ApiError` を ytt.errors に統一 | Wave B(別の作業フォルダ。**Opus**。影響が広い・12 のテスト・CODE_DIR 由来の 4 点) | studio の unittest 一式・node test_review・e2e_analyze・e2e_ui(+ `--mounted`)・test_mount(単独)・test_exporter | 26 → 18 になる前の準備 | 2〜3 時間 |
| **RS3-5 studio の移動** | `analyze`→analyze(+feedback を review に)、`batch`→`pipeline/batch.py`、`store`→review、`rank`+`seed.json`→find、`handoff` を割る、`txlink`→cases、exporter の import | RS3-4 のあと 3 人まで(rank・store+analyze+batch・handoff+txlink+exporter はファイルが重ならない) | 同上 | 26 → **18** | 2 時間 |
| **RS3-6 まとめ** | `layer_map`(FILES・KNOWN・KNOWN_MAX)・AGENTS.md の表・home/studio の README・計画 `plan/data.js`(+ 公開ページ)・WORKLOG・HANDOVER。全部のテスト | まとめ役 | 全 unittest・lint 0・`test_layering`・e2e 1 本ずつ・`dev/tests/e2e_pipeline.py`・`e2e_datadir.py` | 18 | 1.5〜2 時間 |

- **並列の組**: 〔RS3-1 ∥ RS3-2 ∥ RS3-3〕(ファイルが重ならない。ただし `launch.py`・`live.py`・`autorun.py` の import 行は 3 者が触る = **この 3 つの import の直しはまとめ役がまとめて**。`git mv` だけのコミットを先に cherry-pick し、付け替えは各自の作業フォルダで)と、〔RS3-4 → RS3-5〕は別の作業フォルダで同時に進められる(studio と home はファイルが重ならない。共有は `dev/layer_map.py` と `exporter.py` と文書だけ)。RS3-0 は先に 1 人で。
- 編集側の RS3(`ed_store` ほか → human/proof)は別の調査。**`dev/layer_map.py`(FILES・KNOWN)・`AGENTS.md`・WORKLOG・`plan/data.js` は共有**なので、取り込みは順番に(KNOWN の集合の差分が衝突しやすい)。
- 並列の実装の最中は待ちのあるテスト(e2e)が揺れる(e2e-flaky-under-subagent-load)。**全体の一式はサブエージェントが止まってから**。e2e は 1 本ずつ・`PYTHONIOENCODING=utf-8`(unittest には付けない)。
- 合計の目安: 実作業 約 13〜17 時間分 → 並列で **壁時計 7〜9 時間**(計画 8 節の「RS3 は 1 日」の範囲)。RS2-9 の実績(11 コミット・約 5.5 時間)と同じ運び。
- 前から落ちている物: `e2e_window`([7-1] #count)・`e2e_ui_handoff`。全体を続けて流したときだけ揺れる物: `e2e_live_studio` の 1〜2 件・`test_live_archive` の 1 件(単独で OK)。

### 4-B ライブ(線 D)は本物の配信で動いている — 壊すと困る所

1. **コードを移しても、起動中の入口は古いコードのまま動く**(Python は読み終えたファイルを掴まないので `git mv` は安全)。新しい入口に替えるには「すべて終了 → start.bat」= **配信中は入口を落とさない**。録画の部品(別プロセス)は入口が落ちても録り続けるが、`live_excite_worker`(検出)・`live_tx_worker` は入口と一緒に止まる(state.json から続きは再開)。**AI はユーザーの入口を止めない**(AGENTS)。起動し直す時機はユーザーに頼む。
2. **旧パスの転送は 3 つ必須**(1-C)。置かないと、古い入口が検出のワーカーを起動し直そうとして `can't open file` で失敗し、検出が止まる(自動の採用が止まる)。
3. **numpy を入口のプロセスで import しない約束**(`live_align_worker.py` の docstring・`test_live_detect.py:1789` の `NoNumpyTest`・`test_live_tx.py:687`)。移した先の層の `__init__.py` は import 禁止(`test_package_inits_do_not_import`)なので問題は出ないが、`live_excite_worker` を `live_detect` が同じプロセスで読む(`:49`)ので、ワーカーの `sys.path` の足し方は「スクリプトとして動いたときだけ」にしてモジュールとして読んだときは触らない(`pipeline/transcribe/worker.py` の形)。
4. **ディスク上の形式は変えない**(`peaks.json`・`decisions.json`・`exports.json`・`requests.json`・`archive.json`・`deliver-pool.json`・`autorun-active.json`・`live/reports/*.json`・`live_feedback.jsonl`)。コードを移すだけ。`live_requests.Store`(`live.py:293`)の置き場所も同じ。
5. **人の採用と自動の採用が同じ口・同じファイル**(`Live.adopt`・`Detector.adopt`・`decisions.json`・`MarkStore`・`live_feedback.jsonl`)は RS0-d で「RS6 まで形を変えない」と確認済み。RS3 では割らない(割ると配信中の採用が壊れる)。
6. `Live._tick`(`live.py:1122-1129`)は 7 つの見回りを `_guard` で包んで順に呼ぶ。移すときも順番・`_guard` は変えない。
7. 直したあとの確かめ: `e2e_live`(本物の録画の部品を `--source direct` で)・`e2e_live_archive`(本物の align)・`e2e_live_studio`(偽の検出ワーカー)を 1 本ずつ。それでも**本物の配信 1 本**は RS1・RS2 の確認と一緒にユーザーに頼むことになる(まだ未確認)。

---

## 5. 要判断(ユーザーに確かめる事と、仮ならどちらか)

| # | 問い | 選択肢 | 仮にするなら(理由) |
| --- | --- | --- | --- |
| 1 | **`live.py` と `AutoRunner`(autorun.py)を RS3 で分解せず app に置く**でよいか(計画 7 節は live.py → pipeline、autorun の友人の経路 → human/friend) | A: app に置く(友人の届けだけ human/friend へ出す)/ B: `Live` を ingest・friend・keep・ops・app に 5 つ、AutoRunner の順番待ちを `pipeline/` に出す | **A**。理由: ① 違反が一気に 15 件減る ② `live.py`(1238 行)は録画元の操作・中継・友人・片付け・調子を `_tick` で束ねる玄関で、本番の配信が動いている ③ RS5「app を薄く」・RS6「run に 1 本化」が同じ所を触るので B は二度手間。B は +1〜1.5 日 |
| 2 | `live_failures` を manage/ops でなく **pipeline に置く**でよいか | A: pipeline / B: ops のまま(pipeline の 4 モジュールから口で受ける) | **A**。失敗の文は ① のモジュールが作り、ops(health)は集まった一覧を `live_probe` で受けるだけ。B は #18・#20・#22 が口に変わって複雑 |
| 3 | 「確認してから届ける」の範囲と、友人のアプリが ②③ を送ってきたときの扱い(3-A の L1〜L3) | L1 だけ消す / L1+L2 / 全部 / RS3 では消さない | **RS3 では消さず移すだけ**。消すのは RS5(L1 は ①に読み替えてアプリは後で更新、L2 はライブの既定を「パックまで」に)。L3 は RS6 のあと |
| 4 | 「あとから解析」を消す時機 | RS3 で消す / RS4 で代わりの道具を作ってから / 消さない | **RS4 のあと**(`eval_marks` に未解析の友人の配信を解析する口を足してから)。RS3 では app の autorun.py に残すだけでコスト増なし |
| 5 | `store.py` を割らず `human/review` に丸ごと置く(配信の登録・data.json の入れ物も一緒) | A: 丸ごと / B: 登録を manage/cases・候補を pipeline に割る | **A**(RS0-d の確認済みの方針。分けるのは RS6)。`SeriesCache` 等 94 行だけ analyze へ出すのは任意 |
| 6 | studio の `common.py` を**殻(modfwd の転送)で残す**か、読み手(13 ファイル・約 360 参照)を一気に書き換えるか。`ApiError` を `ytt.errors` に統一してよいか | 殻あり / 殻なし | **殻あり**(RS2 の ed_jobs と同じ流儀。テストの差し替えが本体に届く。RS5 で消す)。`ApiError` は統一(`serve.py:121` が `extra or {}` で読むので互換)。ytt に足す新モジュールの名前(`procs`・`studio_env`…)は仮 |
| 7 | 友人の届けを AutoRunner から出す形 | mixin(機械的・`self.cv` などを共有)/ 外のクラス(口で渡す) | **mixin**(RS6 で外のクラスに)。理由: 移すのが 275 行の純粋な移動で済む |
| 8 | テストの動かし方 | 1 対 1 のテストは部品と一緒に移す(RS1・RS2 の流儀)/ 全部 home・studio に残して import だけ直す | **移す**(Live・AutoRunner・launch を通すテストは残す)。`test_live_detect.py`(1798 行)を割るのは別の段 |
| 9 | `rank.py` の疑似 API(約 109 行)と `intake.py:152`・`analyze.py` の疑似の分岐 | RS3 で eval/fake の口に / RS5 まで置く | **RS5 まで**(`common.fake()` を ytt の旗として一時的に使う)。pipeline から `eval/fake` を読むと向きが逆になる |
| 10 | `studio/analyze.py` の feedback の書き手(約 135 行)を `human/review/feedback.py` に出す | 出す / 出さない | **出す(任意・段 5 の最後)**。RS0-h「① は自分の記録だけ書く」に合う。向きの違反は減らない |

## 付記

- 使ったモデル: Sonnet 5.5(読むだけの下調べ。自分で全部。サブエージェントは使っていない = 1 本の追跡で足りたため)。
- 触れなかったもの: 編集の `ed_*`(別の調査)・`cut2resolve/serve.py`・`src/analytics/`・画面(JS/CSS)・`accuracy.py` の移動(RS4)。
- 数えた根拠のスクリプト: scratchpad の `deps.py`(兄弟 import)・`readers.py`/`readers.txt`(読み手)・`viol.py`(今の違反 49 件)・`viol2.py`(表の 3 行を替えた what-if = 34 件)。
