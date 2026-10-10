状態(2026-10-10): RS7 の下調べ(Sonnet・high)の報告(サブエージェントが本文で返した報告を、まとめ役が少し詰めて置いた)

# RS7 下調べ: ライブとまとめて実行の玄関を割る(読むだけ。行番号は 10-10 時点)

## 要点
- 食い違い 1: ライブは Runner を「最後の 1 歩」だけ使う。Exporter が書き出したあと `runner.start_file(...)`(`flow/live_export.py:1104-1128`)で AutoRunner の file モード(`flow/run.py:953` `_file_transcribe`・`:947` `_file_pack`)に渡す。**解析・採用・書き出しは run の `_step_*` と別系統の二重実装**。
- 食い違い 2: `flow/live_*` は `Live`(app の `home/live.py`)を親にして呼び返す。`Detector(self…)`(`live.py:294`)・`LiveTx`(:296)・`Reporter`(:297)・`Exporter`(:361)。Detector は `self.live.cfg/recorders/studio_call/adopt/requests/livetx/exporter/list_recordings/note/log/_ids/_halt/root` を呼ぶ。**移す前にこの親の口を型(Protocol)にするのが先**。
- 食い違い 3: ライブの採用は Studio の HTTP API に依存する。`_studio_adopt_mark`(`live.py:842-879`)は `POST /api/videos/open`・`GET/PUT /api/video`・`POST /api/live/exported`(`live_export.py:1182`)。**Studio が無い友人の PC で動かす最大の壁**。
- `AutoRunner.start_file`(`autorun.py:507`)はあるが HTTP の口が無い。

## 1. 今の経路の地図
**A. 配信のライブ(app の Live が玄関)**
| 段 | 関数(行) | 備考 |
|---|---|---|
| 録画の子プロセス | `pipeline/ingest/recorder.py`(HTTP :8730)。起こすのは `Live.spawn` `live.py:1168`・見回り `_tick` :1121(30 秒) | breakaway。録画中は入口が終わっても残す :1067-1096 |
| 録画の開始 | `Live.begin` :608(`probe_live` :152 → `/live/start`)・友人は `begin_request` :650 | |
| 検出(配信中ずっと) | `Detector.tick` `flow/live_detect.py:235`(子 `pipeline/analyze/live_excite_worker.py`・心拍 :258-289) | 計算は子プロセス・② は監督だけ |
| 採用(自動) | `Detector.auto_tick` :560-618 → `Detector.adopt` :474 → `Live.adopt` `live.py:881-916` | 規則が run の F-5(`run.py:555`)と別 |
| 書き出し | `Exporter.add_studio` `live_export.py:511` → `_loop` :668・`_process` :788(録画のセグメントを ffmpeg)→ `_finish` :1040(`.clip.json`・export の鍵 :1029) | run の `_step_export`(:593)は Studio の `/api/export`(yt-dlp)で別物 |
| 候補の文字 | `LiveTx` `live_tx.py:174/269` | 字幕の正本ではない |
| 本番の文字起こし → パック | `Exporter._handoff` :1104 → `AutoRunner.start_file` → `run._file_transcribe`・`_file_diarize`・`_file_pack` | ここで B と合流 |
| 配信後の作り直し | `Archiver`(`live_archive.py:370`)`auto_tick` :686・`after_tick` :749・`_after_begin` :825(解析を `/api/queue/add` で :872)・`_after_adopt` :968・`Exporter.release_hold` :1153 | 解析・採用を run を通さず再実装 |
| 後始末・記録 | `Cleaner`(`manage/keep/live_cleanup.py`)・`Reporter.tick`・`live_failures` | |

**B. まとめて実行**: `POST /api/autorun/start|start-new|start-docs|estimate|cancel`(`launch.py:723-741`)→ `AutoRunner.start*` → 糸 `_loop` :727 → `_execute` :779(`build_spec` :796 → `flow.run.run(client, run, spec, hooks=self)` `run.py:984`)→ `Runner.execute` :434 → 結果の束。

**C. CLI**: 入口がいれば `delegate` :349(動画 = 編集の `/api/transcribe` → `start-docs` の 2 段)。いなければ動画だけ `run_local` :407。URL は入口が要る。

重なり・食い違い: 解析(`Archiver._after_begin` と `run._analyze_item` が両方 `/api/queue/add`・設定の読み方が違う)/ 採用(`Live.adopt` と `run._step_adopt`。既定の数値だけ `spec.DEFAULTS["adopt"]` を共有)/ 鍵(export は live も書く。transcribe/pack は run だけ。録画の検出に鍵は無い)/ 状態ファイルが 10 近く(`exports.json`・`marks/`・`archive.json`・`excite/*.json`・`requests.json`・`reports/`・`autorun-active.json`・`deliver-pool.json`)。結果の束は run だけ。

## 2. 分類(RS6 のあと)
| 物 | app に残す | ② flow へ | ① | ③ 友人 |
|---|---|---|---|---|
| live.py の HTTP の受け口・中継・札 | ○ | | | |
| 設定の読み `cfg/auto_cfg/recorders`・Studio の設定の読み・`local_token` | ○(束の `live` 節に写して ② に渡す) | | | |
| 子プロセスの監督 `spawn/_tick/_watch/stop_recorder/close`・`health` | ○(recorder の起動は ② からも要る) | 見張りの判断 | | |
| 録画元のクライアント `request/call/ping`・`list_recordings` など | | ○(`live_export.rec_list` と重複) | ○(ingest の client) | |
| `validate_url/probe_live/_same_stream` | | | ○ | |
| `begin`・`adopt`・`_pad_secs` など | | ○(adopt は F-5 と統合) | | `stop_long_requests` |
| Studio 経由のマーク `_studio_adopt_mark`・`export_studio`・`studio_call` | ○(Studio を使う画面用のアダプタ) | MarkStore を直に使う採用が要る | | |
| 友人 `begin_request/…/deliver_dir`・`flush_pools` | | | | ○ |
| autorun の `ToolClient`・`restart_info/_redo_work` | ○ | | | |
| 受付 `start*`・糸 `_loop`・待ち行列・記録・`_save_active/_restore_active` | 受付は app | 糸・待ち・記録は ② 向き | | |
| `build_spec/_tool_settings/spec_from_settings`・hook | ○(画面の設定 → 束) | | | `_friend_length` は ③ |
| `estimate` | | ○ | | |
| launch の Supervisor・PortalHandler・PortalServer・main | ○ | `.flow.lock` と終了の順は ② 向き | | |

## 3. 「録画 → 検出 → 採用」を run の段にするとき
制約: `Run` は 1 本の入力で段が 1 回ずつ進み終わる。`FROM_MODE`・`Run.from_input`・`spec.RUN_FROM` に録画の入力と段が無い。束に `live` 節が無い。

- **案 A: 長い 1 本の Run**(段 record → detect → adopt を Run に)。配信中ずっと止まらない段・途中の復元を Run が抱える・糸が 1 本なので次の切り抜きが進めない。重い(推測)
- **案 B(推奨): ② に常駐の「ライブ係」(`flow/livesession.py` 仮)を足し、Run は 1 切り抜き 1 本の一回きりのまま**。`tick(now)` を冪等にして状態は既存のファイルから復元。録画の監督 → 検出 → 採用(F-5 の同じ関数)→ 切り抜きごとに `Run`(file_auto)を積む。配信後の作り直しは別の実行(アーカイブの URL)。`from_` は adopt・export だけ意味がある。Run 本体を触らず、守っているテストが広いまま。新しく要るのは親の口(Protocol)と Studio なしの採用
- **案 C: tick 型の汎用スケジューラ**(Run を段ごとに再入)。いちばん大きい変更・RS8 以降(推測)

起動し直し: 案 B なら新しい保存は要らない(既存の `exports.json`・`excite/decisions.json`・`archive.json` から)。録画の子プロセスの監督: 判断は ②・起こし方(breakaway・優先度・ログ)は ①(`pipeline/ingest` に spawn)。`live_detect.start_logged` :74 が共通の起動関数(推測)。

## 4. 友人の PC で ② + ① だけにするとき、今 app・③ にしかない物
1. 採用のマーク = Studio の HTTP
2. 設定 = prefs の `live` 節(束に `live` 節が要る)。録画元の合言葉 `recorder/token.txt`
3. 解析の設定 = Studio の `GET /api/settings` → 束の `analyze`
4. 書き出しの音量 = settings-ui.json → 束の `export`
5. 画面からの操作 = app のまま
6. 友人へ届ける = ③。友人の PC 自身が友人なので要らない可能性(推測)
7. 安全弁 D-13 の「未確認の数」= ④ cases。人が見ない前提なら上限の本数だけ
8. `expire_unseen`・Cleaner・Health = ④。録画の自動削除は友人の PC にも要る
9. 子プロセスの起動の順と後始末・`.flow.lock`。CLI がライブを持つなら CLI にも同じ後始末

## 5. CLI と `start_file`
- `start_file`(`autorun.py:507-522`): 動画 1 本を `file`/`file_auto` の Run にして順番待ちへ。呼び手は live_export と友人の受付
- 足す所: `launch.py:543-545` の表と `_post_autorun` に start-file
- 本当の穴: (1) `start_file` に force・束の引数が無い → CLI の `--spec`/`--force` が入口経由だと効かない。`Run.saved()` に束が入らないので起動し直すと CLI の束が消える → Run に束の上書きを持たせ saved に入れる必要 (2) 任意のパスを HTTP で受けるので拡張子(`ytt/tools.MEDIA_TYPES`)で絞る

## 6. 危険とテスト
危険: 本物の配信中に割ると、録画の子・検出の子・Exporter の途中のジョブ・Archiver の作り直しの途中・`autorun-active.json`・保留の handoff が同時に残る。`Live.close` の順(detector → livetx → archiver → exporter → recorder)と `teardown` の順を変えると、保留の受け渡し先が先に閉じうる(推測)。`self._server = h.server` を要求ごとに入れる癖。入口と CLI が両方 recorder と検出ワーカーを起こす二重の ②。束の `live` 節の追加は鍵の定義に波及。

守られている所: `test_live.py`(58)・`test_live_archive.py`(34)・`test_live_detect.py`(50)・`test_live_tx.py`(19)・`test_autorun.py`(107)・`flow/tests/test_run.py`・`test_launch.py`・e2e の live 3 本と autorun。

守られていない所: `flow/live_*` を Live なしで動かすテストが無い / 入口の起動し直しの全体(autorun の復元 + exports の復元 + 保留 + kept の録画へ再接続)のテストが無い / `Live.close()` の順を縛るテストが無い / 本物の YouTube・streamlink・Windows の CTRL_BREAK は人手だけ / CLI + ライブは未定義。

進め方の提案(推測): 親の口(Protocol)を `flow/` に定義して `Detector/Exporter/LiveTx/Reporter/Archiver` をそれだけに依存させる(動きは変えない)→ Studio なしの採用(MarkStore + `Exporter.add`)を足して F-5 に寄せる → 案 B のライブ係を `flow/` に置き Live は薄い app の殻に。
