状態(2026-10-10 深夜): RS7 の段の並びの第 2 版(Fable・high・読むだけ)。F1 の決定(`plan/f1-friend-pc.md`)に合わせて作り直した。サブエージェントが本文で返した報告を、まとめ役が少し詰めて置いた。問いの答えは `plan/decisions.md` の 3-30

# RS7 段の並び(第 2 版)

根拠: `plan/f1-friend-pc.md`(4f6fd8a)・第 1 版 `plan_order.md`・下調べ 5 本・`flow/run.py`(Run の欄 :123-171・`screen` :165)・`flow/spec.py`(SECTIONS :104・FIXED :108・SCREEN :372・TX_POST_KEYS :377)・`worker_client.py:549`(`TRANSCRIBE_DEVICE`)・`intake.py:698/761`・`live.py:740〜916`。

## 0. 結論: RS7 を 2 つに割る
F1 で「② の口と束」が前提になったので、**玄関の分割(ライブ係)より先に「束と口」を作る**(ライブの依頼も束で受ける = 差 3 はライブ係の前提)。量が第 1 版の約 1.5 倍。
- **RS7-1 束と口**(封筒 + 束・この PC の設定・待ち行列の保存と復元・受付を変換に・小物)→ 起動し直し R1
- **RS7-2 玄関とヘッドレス**(親の口・スタジオなしの採用・ライブ係・`app/server.py --headless`・B-1)→ 起動し直し R2
各 RS の終わりに e2e 一式と文書を 1 回。アプリの側(C#)は RS7-2 のあと。

## 1. 範囲(第 1 版との差)
**足す物(F1 から)**: 封筒 + 束の口 `POST /api/flow/submit`・状態の口 `GET /api/flow/status` / Run の欄を封筒だけに・段は束だけを読む・hints を読む(差 1)/ 束は受けたときに組んで保存(差 2)/ ライブも束で(差 3 = RS7-2)/ 「この PC の設定」の層 `flow/machine.py`(エンジン・デバイス・LLM のモデル・案件の根・空き容量の下限・学習データの場所。`TRANSCRIBE_*` と `llm.py:37` の定数をここへ。差 4)/ `Run.screen` を消す(差 5)/ 編集の受付が settings.json を読み直す 6 項目を束から・LocalTools を HttpTools と同じに(差 6)/ CLI が入口に束を丸ごと渡す(差 7)/ `_friend_length`・`_auto_streamer`・deliverBatch の既定を受付へ(差 8)/ 学習データの版(差 9)/ ② が画面なし・③ なしで起動(`--headless`)/ 待ち行列の保存と復元を封筒 + 束で / 覚えた声に「どの文書から覚えたか」/ 下調べの 3 件(CLI の LLM の文脈が `src\studio\data.json`・パックの ffmpeg が PATH だけ・CLI が学習した置換と用語集を読まない)。
**第 1 版から残す物**: 玄関の分割 案 B(G0 → G1 → G2)・段の時刻の記録・起動し直しと `.flow.lock`・`voice_rows`・バックアップ・B-1・`app/server.py`。
**外す・送る物**: `start-file` の新設(submit の kind=file に吸収)/ serverkit(F1 に効かない → RS7-2 の余り・無ければ RS8)/ 設定 1 ファイル(問いは消す = 機械の都合は `machine.py`・画面の都合の 4 ファイルは UI の再考で)/ 友人へ届ける段は app の hook のまま / D-13 はユーザーの PC だけ = ライブ係の host の hook / G3 は RS7-2 の余り・1 日を超えたら RS8 / 旧い形の依頼(送るアプリ 2.10.0)の変換はユーザーの PC の `intake` に残す(移る間だけ)。

## 2. 段の並び
### RS7-1 束と口(壁時計 1〜1.5 日)
**波 1(並列。入口を止めない)**
| 段 | 中身 | 触るファイル | モデル | 目安 |
|---|---|---|---|---|
| S1 この PC の設定 | `flow/machine.py`: `{engine, device, llmModel, caseRoot, diskMinGB, learningDir}` を `machine.json` + 環境変数 + 引数から読み、受けた束に重ねる。`TRANSCRIBE_DEVICE` は ② が要求の本文で渡す・`llm.py:37` の定数は要求で受ける・`live_tx` の固定も machine から | 新 `flow/machine.py`・`flow/tools.py`・`flow/tx.py`・`worker_client.py`・`llm.py`・`flow/live_tx.py` | Opus・high | 4 h |
| S2 束を広げる | `hints` の検査と読み口・`TX_POST_KEYS` に 6 項目・`post.learning.version`・SCREEN の扱い・`doc_jobs.py` の settings.json の読み直しを束から・LocalTools の device を丸めない・autoLearned/autoRedo を束どおり | `flow/spec.py`・`flow/tools.py`・`flow/tx.py`・`human/proof/doc_jobs.py` | Sonnet・medium | 4 h |
| S3 封筒と Run | `flow/envelope.py`(仮)`{id, kind: url/file/docs/live, input, requestId, deliver, note, createdAt, specVersion}`。Run の欄を束に写す読み替え(段は `run.xxx` を読まない)・`saved/restore` に封筒 + 束・`public` に packs/newDocs・文書単位でも `run.docs`・`steps[].startedAt/finishedAt`・知らない項目は理由つきで拒否 | `flow/run.py`・`flow/envelope.py`・`flow/placement.py`・`flow/runlog.py` | Opus・high | 8 h |
| 1d 起動し直しと lock | `--wait-pid` 最大 90 秒・次の番号に逃げず読める文で非 0・`LockBusy` を読める文 | `launch.py` main・`manage/ops/restart.py` | Sonnet・medium | 2 h |
| 1e 声 | `voice_rows` の別名を消す + 覚えた声に `learnedFrom: [{doc, at}]` | `flow/diar.py`・`human/proof/speakers.py`・`eval/tools/eval_speakers.py` | Sonnet・medium | 3 h |
| 1f バックアップ | `plan_cases(out_dir)` = `作業用\*.json`・`.studio-id` だけ | `manage/keep/backup.py`・`launch.py:858`・spec/data-location | Sonnet・medium | 2 h |
衝突: S2 と S3 は `spec.py` の鍵の名前を先に決めて分ける。`tools.py` は S1 と S2 で region が別。

**波 2**: S5 待ち行列を ② へ = `flow/queue.py`(仮): 糸・待ち行列・記録・復元(封筒 + 束)・`estimate`・`status()`・`submit(envelope, spec)`。AutoRunner は受付と hook(届ける・D-13・配信者の推定)だけに(Opus・high・5 h)

**波 3(並列)**: S4 受付を変換に = `start*` と `intake`(受けたときに封筒 + 束)・`build_spec` を受付時に・差 8 の既定を受付へ・`POST /api/flow/submit`・`GET /api/flow/status`(旧 `/api/autorun/*` は別名で残す = 画面の JS は変えない)・CLI は封筒 + 束で submit(1 段)(Opus・high・6 h)∥ F-k 小物 = CLI の LLM の文脈・パックの ffmpeg を `find_ffmpeg`・CLI が学習データを `learningDir` から(Sonnet・medium・2 h)

**Z1**: lint 0・層 0・unittest 一式・契約(単独)・e2e 一式・文書・**R1**(配信の無い時間に起動し直し): 画面のまとめて実行 1 本・CLI の submit 1 本(入口あり / なし)・旧い形の友人の依頼 1 本・入口を落として起動し直すと続きから。

### RS7-2 玄関とヘッドレス(壁時計 1〜1.5 日)
- **波 4(並列)**: G0 親の口(`flow/livehost.py` の Protocol・偽 host のテスト・`Live.close` の順のテスト。Opus 4 h)∥ G1a F-5 の純粋な規則を `pipeline/analyze/adopt.py` へ(golden。Sonnet 2 h)∥ 1b B-1(Sonnet 3 h)∥ serverkit(余りがあれば)
- **波 5(並列)**: G1b スタジオなしの採用(`flow/live_adopt.py`。StudioMarks / LocalMarks。本数は束の `adopt.top`(依頼の欄・既定 10)。Opus 5 h)∥ G5 `app/server.py`(mv・Supervisor・旧 `home/launch.py` は runpy の転送・**`--headless`** = 画面と ③ を載せず ① の API 3 本 + ② だけ・合言葉とポートを標準出力の 1 行で。Opus 5 h)
- **波 6(直列)**: G2 ライブ係 `flow/livesession.py`(`tick(now)` 冪等・既存の状態ファイルから復元・検出・採用・切り抜きごとに `queue.submit`。ライブの依頼も封筒 + 束 = `live_detect:201`・`live_archive:867` の `GET /api/settings` をやめる。D-13・届ける・友人の依頼は host の hook(headless は hook なし = 守りは `diskMinGB` だけ)。Opus 8 h)→ G3(余りで)
- **Z2**: 一式 + 文書 + 版 0.57.0 + **R2**: ライブ 1 本・配信後の作り直し 1 本・`--headless` の ② に CLI から submit 1 本

## 3. ユーザーに聞く問い(答えは decisions 3-30)
- Q1「この PC の設定」の持ち方: A 新しい `machine.json` を ② が読む・編集の ⚙ のエンジン・デバイスの欄はそこへ書く(推奨)/ B 編集の `settings.json` をそのまま / C 環境変数と引数だけ
- Q2 `Run.screen` の 3 項目(切り出しの精密・画質の上限・パックの fps)の画面の欄を RS7-1 で消すか: A 消す(5-4 のとおり。推奨)/ B UI の再考まで残し既定値つきの束の項目に
- Q3 学習データの「場所」を束に入れるか: A 束には版だけ・場所は「この PC の設定」(推奨)/ B 5-4 のとおり場所も束に

## 4. AI が決める一時の形
- 封筒の形・kind 4 つ・`specVersion`(知らない項目は 400 と理由)/ 旧 `/api/autorun/*` と `start_file/start_request` は変換の別名として残す
- 「このマークだけ」= `run.from=export` + `hints.ranges`、文書単位 = `kind=docs` + `run.from=pack`、`overwrite` = `run.force`
- `machine.json` の既定 = 今の値(engine/device は編集の設定から 1 度だけコピー・llmModel = qwen3-8b・caseRoot = outDir・diskMinGB = 20・learningDir = 作業データの根)。優先は 引数 > 環境変数 > ファイル
- 束は受付で組み、`queue` が封筒 + 束で保存(`autorun-active.json` の形は版を上げ、古い形は 1 度だけ読んで変換)
- `GET /api/flow/status` = `{queued, running, done, runs:[...]}`。`--headless` の合言葉は `.runtime/app.json` と標準出力の 1 行
- ライブ係は新しい保存を作らない。Archiver の解析の依頼は G3 まで HTTP。ユーザーの PC のマークの正本はスタジオのまま(B-3 で)
- D-13 の hook = `LiveHost.may_adopt(rc, rec) -> (ok, reason)`。headless は常に ok・空き容量だけ ② が見る
- 声の `learnedFrom` は各人に足すだけ。退避した 5 人は戻さない
- case.json = `youtube-tools-case/v1`・`ensure_case` は無いときだけ・索引は resultPath
- バックアップは `作業用\*.json` と `.studio-id` だけ・戻すのは手で。段の時刻は足すだけ(`LOG_VERSION` 据え置き)
- 1d は 90 秒・次の番号に逃げない。G5 は識別子 "app"・URL・`.runtime` 不変・旧 `launch.py` は R2 のあとに消す
- 版は Z2 で 0.57.0

## 5. 危険と止め方
- 束に写す読み替えで動きが変わる(S3): 欄 → 束の対応を test_run の golden で縛る。差が出たら戻す
- 受付の時機が変わる(差 2): 待ちの間に設定を変えても中身が変わらない = 意図した変化。WORKLOG と spec に 1 行
- machine の上書きが鍵を変える: 既定が今の値なので鍵は同じ。R1 で同じ切り抜きの再実行が「飛ぶ」ことを確かめる
- 本物の配信中に玄関を割らない: 波 5・6 と R2 は配信の無い時間に
- 並列の衝突: `autorun.py`(S5 → S4 は直列)・`spec.py`(S2/S3)・`launch.py`(1d・1f・S4・G5 の mv は最後)
- ② が二重に起きない(入口 + headless + CLI): `.flow.lock`。R2 で同時に起こして止まることを確かめる
- 旧い形の依頼は `intake` の変換で受け続ける(消すのはアプリの新版を渡したあと)
- 時間の上限: S3 が 1.5 日・G2 が 1 日を超えたら、その RS の残りを次へ送って R1/R2 を迎える
