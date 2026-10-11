状態(2026-10-11): 案(ユーザー未確認)

# RS8: 新しい画面(案件の画面)が見る ② 管理の口の形

関連: 進め方 `plan/rs8-cases-ui.md`(条件 1 = 進み具合は ② の status から・今のツールの API を画面が直に見る形で新しく作らない)・① ② の見直し `plan/opt-pipeline-flow.md`(ジョブの器 10 通り・OPT2 の後半)・画面の設計 `docs/design/briefs/rs8-cases/DESIGN_BRIEF.md`・`inventory.md`・受け渡し `docs/spec/pipeline.md` 2.6〜2.8・今の口 `src/flow/runqueue.py`(`status`)・`src/app/server.py`(`/api/flow/submit`・`/api/flow/status`)。
コードは書いていない。この文書は「形」と「段の分け方」だけ。確認のあと `docs/spec/pipeline.md` 2.9 に規則として写す。

## 0. 要約(推奨)
| 問い | 推奨 |
| --- | --- |
| 1 画面が見る口 | **② に「ジョブの掲示板」`flow/board.py` を 1 つ置き、口は 4 つ**: `GET /api/flow/status[?case=]`(今の形 + `jobs[]` + `cases{}` + `rev`)・`POST /api/flow/cancel {id}`・`POST /api/flow/retry {id}`・`GET /api/flow/history[?case=]`。知らせ方は **間隔での問い合わせ**(動いていれば 2 秒・止まっていれば 15 秒。SSE は作らない) |
| 2 器 10 通りの載せ方 | **この段は「包んで見せる」**(各器が状態を変えるたびに掲示板へ写す。器の本体と今の API は動かしたまま)。**器を本当に 1 つにする OPT2 の後半は新しい画面の直後**(掲示板の形がそのまま最終形 = 画面を作り直さずに差し込める) |
| 3 案件の読みと人の操作 | **② を通さない**。案件の中身(候補・採用・文書・状態)は ④ `manage/cases` の口、人の操作(採用・校正・3 択・届ける)は ③ の今の口。② は進み具合だけ。鍵は**案件の根**(`flow/placement` が ② の中で既に引く物)で突き合わせる |
| 4 友人の PC | **同じ口で足りる**。送るアプリが聞く `idle`・`live` は今のまま、足す物は項目の追加だけ(知らない項目は無視 = 前方互換)。③ の器(届ける・検索)は headless に無いので掲示板に載らないだけ |
| 5 段と割り振り | S1 掲示板(Sonnet)→ S2 包み 6 本を worktree で並列(② の Run・ライブ 3 つ = Opus / 編集・スタジオ・パック・③ の 2 つ = Sonnet)∥ S3 入口の口(Opus)→ S4 画面側の読み替え見本(Sonnet)。旧い進み具合の API はこの段では消さない |

## 1. 画面が見る口(推奨 = 掲示板 1 つ・口 4 つ・間隔での問い合わせ)

### 1-1 何を見せる口か
新しい画面(入口・案件の画面・確かめる)が「今・何が・どこまで動いているか」を知るための口。**データ(文書・候補・採用・パックの有無)ではない**(それは 3 節)。
今の画面は進み具合を 7 か所から読んでいる(`/api/autorun`・編集 `/api/jobs`・`/studio/api/export`・`/studio/api/analyze`・cut2resolve `/api/build` のジョブ・`/live/api/...` の exports・`api/ytt/deliver`・rank の検索)= 画面ごとの読み方が違い、1 つの案件に何が動いているかを 1 か所で答えられない。

### 1-2 ジョブ 1 つの形(`Job`。掲示板が整える = 器ごとの言葉の違いをここで吸収)
```json
{"id": "tx:ab12cd34ef56", "kind": "transcribe", "parent": "run:0f3a9c1d2e", "case": "D:/clips/配信の題",
 "target": {"videoId": "…", "docId": "…", "markId": "…", "path": "…"},
 "title": "文字起こし: 配信の題 01",
 "state": "running", "stateLabel": "実行中", "phase": "認識中 2/5", "progress": 0.42, "waiting": false,
 "createdAt": 1760000000000, "startedAt": 1760000001000, "finishedAt": null,
 "error": null, "canCancel": true, "canRetry": false,
 "steps": null}
```
| 項目 | 意味・決まり |
| --- | --- |
| `id` | `<器の名>:<器の中の id>`。器をまたいで衝突しない・取り消しの振り分けの鍵(`run:`・`tx:`(編集のジョブ)・`an:`(解析)・`ex:`(書き出し)・`pk:`(パック)・`lx:`・`la:`・`lt:`(ライブの書き出し・作り直し・候補の文字起こし)・`dl:`(届ける)・`se:`(検索)) |
| `kind` | 段の語彙(`flow/run.STEP_LABELS` の鍵をそのまま): `analyze`・`adopt`・`export`・`transcribe`・`diarize`・`pack`・`deliver` + `run`(② の 1 回の実行)・`rerun`(再認識・比較・後処理の作り直し)・`search`(配信の検索)・`live_export`・`live_archive`・`live_tx`。掲示板の `KINDS` にない物は ValueError(語彙を増やすときは表に足す) |
| `parent` | ② の実行が頼んで動いた器のジョブなら、その `run:` の id。画面は親の下に畳んで出せる(今の `_wait_job` が持つツールのジョブの id をここに写すだけ) |
| `case` | **案件の根**(絶対パス・`fsio.norm_path`)か null。② の `placement.case_root`・`casebook.case_of`・文書なら `ytt/docloc` が引く。案件が無い(評価用・案件の分からない文書)は null = 画面の仮の案件に入る(brief 3-3) |
| `target` | 何に対するジョブか。ある物だけ(`videoId`・`docId`・`markId`・`path`・`recording`)。画面が左の一覧の行(切り抜き 1 本)に進み具合を付けるのに使う |
| `state` | **6 つに統一**: `queued`・`running`・`done`・`error`・`cancelled`・`skipped`。器ごとの細かい状態(編集の loading/extracting・ライブの作り直しの probe/align/fetch/verify・書き出しの item ごと)は `running` + `phase` に畳む。`stateLabel` は `run.RUN_STATE_LABELS` の言葉 |
| `phase` | 人が読む短い文(「順番待ち」「他のツールの処理が終わるのを待っています」「認識中 2/5」)。`waiting` = SLOTS 待ち(`ytt/jobs.WAIT_MESSAGE` と同じ事を真偽で) |
| `progress` | 0〜1 か null(分からない器 = 解析の一部・届ける) |
| `error` | `{code, text, detail}` か null。`text` は画面に出す文・`detail` は「詳しく」の中だけ(M9・S12 の決まりのまま) |
| `canCancel`・`canRetry` | その器が今できるか(編集の `can_retry`・書き出しは running の間だけ など) |
| `steps` | `kind: run` だけ。今の `status()` の `steps[]`(key・label・state・detail・startedAt・finishedAt)そのまま |

### 1-3 口 4 つ
| 口 | 形 | 今の口との関係 |
| --- | --- | --- |
| `GET /api/flow/status[?case=<根>]` | 今の `{queued, running, done, idle, closed, live, runs}` に **`rev`(変わるたびに増える整数)・`jobs: [Job]`(待ち・実行中 + 終わった直近 30 件。入れた順)・`cases: {<根>: {active, lastState, lastFinished}}`** を足す。`?case=` を付けると `jobs` をその案件に絞る(`idle`・`live`・counts は絞らない = 送るアプリの意味を変えない) | 今の項目は残す(送るアプリ・CLI が読む)。`runs` は `jobs` の `kind: run` と同じ中身 = 新しい画面が `runs` を読まなくなったら RV で消す |
| `POST /api/flow/cancel {id}` | 合言葉。掲示板が `id` の頭で器へ振り分ける(`run:` → `Queue.cancel`・`tx:` → `flow/jobs.cancel_job`・`an:` → `Batch.cancel`・`ex:` → `exporter.cancel`・`pk:` → `Task` の cancel・`lx:` `la:` `lt:` → ライブの各 cancel・`dl:` `se:` → ③ の cancel)。できない物は 409 `cannot_cancel`・無い id は 404 | 今の `/api/autorun/cancel`・`/api/transcribe/cancel`・`/studio/api/export/cancel`・`/api/job/cancel` …は残す(古い画面が使う)。新しい画面はこれだけ |
| `POST /api/flow/retry {id}` | 同じ指定で入れ直す(`canRetry` が真の物だけ。編集の `retry_job`・解析の `RETRYABLE`・② の Run は「もう一度 submit」= 済んだ段は鍵で飛ぶ) → 新しい `Job` | 今の `/api/jobs/retry` と同じ事を 1 つの口で |
| `GET /api/flow/history[?case=&limit=&offset=]` | 終わった実行の記録(`runlog`)。`?case=` は結果の束の `resultPath` の案件で絞る | 今の `/api/autorun/history` を flow の名前にして広げる(中身は同じ) |

### 1-4 変化の知らせ方 = 間隔での問い合わせ(推奨)
- 画面は `status` を **動いている物があれば 2 秒・無ければ 15 秒**(今の `portal.js` の `pollAuto` と同じ値)。隠れている間は `UIKit.life` の決まりで止める。`rev` が前と同じなら描き直さない。
- **捨てた案 SSE(`text/event-stream`)**: 入口は標準ライブラリの `ThreadingHTTPServer` で、SSE は接続 1 本を糸 1 本で占有する(取り込んだ 3 ツールの画面がそれぞれつなぐと糸が増える)・取り込みの中継(`mount.py`)と Host/Origin 検査・CSP の形を変える・窓(Edge のアプリモード)で止まった接続のつなぎ直しの面倒が増える。得られるのは「2 秒 → 即時」だけで、律速は人の校正(brief 1)なので釣り合わない。今の画面も全部が間隔での問い合わせ。
- **捨てた案 long-poll(`?since=rev` で変わるまで待つ)**: 糸を塞ぐ点は SSE と同じ。`since` で差分だけ返す省き方は、ジョブが 100 件を超えて重くなったときに足す(形は `rev` で用意済み)。
- 仮決め(AI): 2 秒・15 秒・直近 30 件・`cases{}` の 3 項目は使ってみて直す値。

## 2. 器 10 通りの載せ方(推奨 = 包んで見せる。器を 1 つにするのは直後)

### 2-1 器と包み方
掲示板 `flow/board.py` = **プロセスに 1 つの表 `{id: Job}` と `upsert(job)`・`remove(id)`・`list(case=None)`・`cancel(id)`・`retry(id)`・`set_case_hook(fn)`**(標準ライブラリ・ytt・同じ flow だけ。③ の器は入口が登録する = 層の向き)。各器は**状態を変える所で `board.upsert(その器 → Job)` を 1 行呼ぶだけ**(器の本体・今の API・画面は変えない)。
| 器 | 層 | 今の状態の置き場 | 包み(`→ Job` の対応) | cancel の先 |
| --- | --- | --- | --- | --- |
| `runqueue.Queue` の Run | ② | `Queue.runs`・`autorun-active.json` | `run:` / `kind run` / `steps` = `_status_of` / `case` = `placement.case_root(run)`。段がツールのジョブを始めたら(`_wait_job` の id)そのジョブの `parent` を自分にする | `Queue.cancel` |
| `flow/jobs`(編集の文字起こし・話者・再認識・比較…) | ② | `_jobs`・`/api/jobs` | `tx:` / `kind` = 登録した種類 → `transcribe`・`diarize`・`rerun` / `phase` = `job["phase"]` / `case` = `docloc.doc_dir(tid)` の案件 | `cancel_job` |
| `flow/batch.Batch`(解析) | ② | `items`・`/studio/api/analyze` | `an:` / `kind analyze` / `target.videoId` | `Batch.cancel` |
| `pipeline/export/exporter` の job(書き出し) | ① にある ② の仕事 | `_jobs`・`/studio/api/export` | `ex:` / `kind export` / item ごとには割らず `phase` = 「2/5 本目」`progress` = 平均 / `target.videoId` | `exporter.cancel` |
| `pipeline/pack/cut2resolve_core.Task`(パック) | ① にある ② の仕事 | `/cut2resolve/api/build` のジョブ | `pk:` / `kind pack` / `target.path` | `Task.cancel` |
| `flow/live_export.Exporter`(ライブの書き出し) | ② | `live/exports.json` | `lx:` / `kind live_export` / `target.recording`・`markId` / 状態 5 つ以上 → `running` + `phase`(`STATE_LABELS`) | 今の cancel |
| `flow/live_archive.Archiver`(作り直し) | ② | 同じ exports.json の `archive` | `la:` / `kind live_archive` / wait〜verify → `running` + `phase` | 今の cancel |
| `flow/live_tx.LiveTx`(配信中の候補の文字起こし) | ② | メモリ | `lt:` / `kind live_tx` | 今の cancel |
| `human/friend/deliver.Deliveries` | ③ | `self.jobs`・`api/ytt/deliver` | `dl:` / `kind deliver` / `progress` null / 入口が `board` を渡して登録 | `Deliveries` の cancel(無ければ `canCancel false`) |
| `human/find/rank._jobs`(検索) | ③ | `_jobs` | `se:` / `kind search` / `case` null | 今の cancel |

- **なぜ包むだけにするか**: 条件 1 の目的は「新しい画面が 1 つの形だけ見る」こと。包みなら 10 本を並列に・各 1〜2 時間で入り、今のテスト(各器の unittest)がそのまま効く。器を本当に 1 つにする(OPT2 の後半 = ① を「指定 → 結果」の関数に・② が ① を直に呼ぶ・HttpTools を消す)は書き出し `exporter` 997 行・ライブ 5,700 行に触る大きな直しで、RS8 がさらに膨らむ(`plan/rs8-cases-ui.md` 決めたこと 2 の「大きいため」と同じ理由)。
- **なぜ直後にやるか**: 画面ができたあとなら、器を 1 つにしても画面は掲示板の形しか見ていないので作り直さない(= 条件 1 の「差し込める」が実際に確かめられる)。先にやると、画面の無い間に器を変えるので「進み具合がちゃんと出るか」を古い画面で確かめることになる。
- **捨てた案 全部移してから画面**: 新しい画面が 2〜3 日遅れ、その間ユーザーの普段の作業は古い画面のまま。器を 1 つにする直しは掲示板の有無に関係なくできる。
- **捨てた案 画面が各 API を直に見る(今の形の延長)**: 条件 1 違反。7 か所の読み方を新しい画面に写すことになり、OPT2 の後半で全部書き直す。
- 器を 1 つにしたあとの掲示板: 器が 1 つなら `upsert` を呼ぶのは ② の段の 1 か所になり、`id` の頭は `run:` と段の `kind` だけが残る(頭の表は縮むが形は同じ)。

### 2-2 段の順(RS8 の中)
```
今: O2-5 済み → (この文書 = ② の口の形) → S1〜S4(4 節) → URL も CLI で(残り)→ 新しい画面(入口・案件の画面)→ 古い画面を消す
                                                                                   → OPT2 の後半(器を 1 つに・HttpTools を消す・鍵を ② の段の 1 か所で)→ V1
```
掲示板は「URL も CLI で」と触るファイルが重ならない(CLI は `flow/studiobook`・`flow/tools`)= 並べて進めてよい。

## 3. 案件の読みと人の操作(推奨 = ② を通さない)

| 画面が要る物(inventory・brief) | どの層の口か | 今の口 | 新しい画面での読み方 |
| --- | --- | --- | --- |
| 案件の一覧・状態・メモ・切り抜きごとの「未・校正中・校正済み・パック済み」・やることの件数 | ④ `manage/cases` | `GET /api/cases`・`POST /api/cases/update` | そのまま。行に `root`(案件の根)が要る = 掲示板の `case` と突き合わせる鍵(cases の行に無ければ足す) |
| 候補と採用(マーク・採否・書き出し) | ③ `human/review`(スタジオ) | `/studio/api/video`・`/studio/api/live/adopt`・`/studio/api/export` | 読みは今の口・書き出しの**進み具合だけ**掲示板(`ex:`) |
| 文書・行の編集・校正・話者・カット | ③ `human/proof` | 編集の `/transcribe/api/*` | そのまま。文字起こし・再認識の**進み具合だけ**掲示板(`tx:`) |
| 3 択(機械の結果が変わった行) | ③ `human/proof/machpick` | `GET /api/mach-changes`・`POST /api/mach-changes/pick` | そのまま(層が正のときだけ = `TRANSCRIBE_LAYERS=primary`。画面は `layers` が primary でなければ札を出さない) |
| パックを作る・届ける | ① の口 cut2resolve・③ deliver | `/cut2resolve/api/build`・`api/ytt/deliver` | 始めるのは今の口・進み具合は掲示板(`pk:`・`dl:`) |
| 新しい案件(URL・探す・まとめて実行) | ② | `POST /api/flow/submit`(封筒 + 束)・`/api/autorun/estimate` → `/api/flow/estimate` に改名 | **新しい画面は submit だけ使う**(`/api/autorun/start*` は古い画面用に残し RV で消す) |

- **なぜ ② を通さないか**: 層の決まりは「③④ は ① を直に読まず ② を通す」= ① の道具(ffmpeg・認識・pack)を呼ぶときの話。案件のファイル(`作業用/候補.json`・`採用.json`・文書)は ③④ が持ち主で、② は「どこに置くか」(`placement`・`casebook` の書き)までしか知らない。② に「案件の一覧を返す口」を作ると「② は画面と案件を知らない」に反し、`manage/cases/cases.py` の仕事が二重になる。
- **② が持ってよい案件の知識は「根」まで**: Job の `case` は根のパス。案件の題・状態・一覧の順は ④ が決める。② の `set_case_hook` は、① の器(書き出し・パック)が自分の根を知らないときに `target` → 根を引くための口(既定 = `placement`・`casebook.case_of`・`docloc` で引けた物だけ・引けなければ null)。
- **捨てた案 ② に案件の口(`GET /api/flow/case/<id>` = 進み具合 + 候補 + 文書)**: 画面は 1 回の問い合わせで済むが、② が ③④ のファイルを読むことになる(向きが逆)。画面側で `cases` と `status` を突き合わせる方が層が守れ、問い合わせは 2 本(2 秒ごとの `status` と、開いたとき・書いたときの `cases`)で済む。
- **捨てた案 画面のための集約を入口(app)に書く**: `src/app/server.py` が ③④② を読んで 1 つの JSON を組む。層は守れるが入口が太る(今 1,200 行超)。画面側の突き合わせ(JS 数十行)で足りる。
- URL と識別子は変えない(AGENTS の互換の決まり。`/studio/api/`・`/transcribe/api/`・`videoId`・文書 id・`markId`)。新しい画面は入口の `/` に置き、取り込み(`mount.py`)経由で今の口を呼ぶ(CSP・合言葉は今のまま)。

## 4. 友人の PC(`--headless`)でも同じ口で足りるか = 足りる
- 送るアプリが聞くのは `GET /api/flow/status` の `idle`・`live`・counts(`plan/f1-friend-pc.md`)。足す `rev`・`jobs`・`cases` は項目の追加で、知らない項目は無視する決まり(`docs/spec/pipeline.md` 1)。`?case=` を付けない限り意味は今と同じ。
- headless では ③ の器(届ける・検索)が無い = 掲示板にその `id` が載らないだけ。② の器(Run・編集のジョブ・解析・書き出し・パック・ライブ)は headless にも載る(取り込み 3 本は起こす)ので、送るアプリが将来「今どの段か」を出したければ `jobs` の `kind run` の `steps` を読めばよい。
- `cancel`・`retry` は合言葉つき(`ready` の `token`)= 送るアプリも使える。
- 気を付ける点: `jobs` が常に全部入ると、送るアプリの 2 秒ごとの問い合わせが大きくなる。上限(待ち・実行中 + 直近 30 件 ≒ 数十 KB)で足りる見込み。足りなければ `?brief=1`(jobs を省く)を足す(形は決めない)。

## 5. 実装の段と割り振り
| 段 | 中身 | 触る所 | モデル | 並列 |
| --- | --- | --- | --- | --- |
| S1 掲示板 | `src/flow/board.py`(表・`Job` の整形と検査・`KINDS`・`upsert`/`remove`/`list`/`cancel`/`retry`・`set_case_hook`・`rev`)+ `src/flow/tests/test_board.py`。純粋(ファイル・ネットワークなし) | flow だけ | Sonnet・medium(形はこの文書に書いてあるので規則の直し) | 最初に 1 本(1〜2 時間)。終わったら S2・S3 を同時に |
| S2a 包み ② の Run | `runqueue.Queue`・`run.Runner._wait_job` の `parent` | `flow/runqueue.py`・`flow/run.py` | Opus(入口の実行の糸・影響が広い) | worktree |
| S2b 包み 編集のジョブ | `flow/jobs.add_job`・`work_one`・`job_errors`・`cancel_job` で `upsert` | `flow/jobs.py`・`human/proof/doc_jobs.py` の `case`(docloc) | Sonnet | worktree |
| S2c 包み スタジオ(解析・書き出し) | `flow/batch.py`・`pipeline/export/exporter.py`(① の中の器 = 1 行の `upsert` だけ。OPT2 後半で ② へ出る) | 同左 | Sonnet | worktree |
| S2d 包み パック | `pipeline/pack/cut2resolve_core.Task`・`cut2resolve/serve.py` | 同左 | Sonnet | worktree |
| S2e 包み ライブ 3 つ | `live_export.Exporter`・`live_archive.Archiver`・`live_tx.LiveTx` | `flow/live_*.py` | Opus(大きなクラス・状態が多い) | worktree |
| S2f 包み ③ の 2 つ | `deliver.Deliveries`・`rank._jobs`(入口が `board` を渡す) | `human/friend/deliver.py`・`human/find/rank.py`・入口の配線 | Sonnet | worktree |
| S3 入口の口 | `/api/flow/status` の拡張・`/api/flow/cancel`・`/api/flow/retry`・`/api/flow/history`・`/api/flow/estimate`(改名。旧い名前は残す)・`live_activity` は今のまま | `src/app/server.py`・`src/home/autorun.py`・`test_launch.py` | Opus(入口) | S1 のあと S2 と同時 |
| S4 画面側の見本 | `docs/design/briefs/rs8-cases/mock/` に `status` の JSON を読む部品の見本(左の一覧の行に進み具合の札・親の下に畳む)。本物の画面は「新しい画面」の段 | mock だけ | Sonnet | S3 のあと |
| 締め | まとめ役: 層の検査・lint・各組の unittest・e2e は入口の `e2e_portal` と編集の `e2e_edit_tabs` の 2 本(画面は変えないので少なめ)・`docs/spec/pipeline.md` 2.9・WORKLOG | — | まとめ役 | — |

- 見積もり(AI の実績に合わせて短く): S1 1〜2 時間・S2 並列で 2〜3 時間・S3 1〜2 時間・S4 1 時間 = **半日〜1 日**。
- テストの約束: 掲示板は器から `upsert` を受けるだけなので、各器の unittest に「状態が変わったら掲示板にその id がその state で載る」を 1 件ずつ足す(`test_board` は形の検査だけ)。`dev/tests/test_layering.py`(① の `exporter`・`Task` が `flow.board` を読むのは向きの違反 → **① は `upsert` を直に呼ばず、呼び手(スタジオの serve・cut2resolve の serve = app)が `on_change` の hook で写す**。exporter の `start_job(…, on_done)` と同じ形)。
- 旧い口(`/api/autorun`・編集 `/api/jobs`・各 cancel)は**この段では消さない**(古い画面が使う)。新しい画面に替えたあと RV で消す。

## 6. ユーザーに確認が要る物(一時の形でない物だけ)
1. **知らせ方 = 間隔での問い合わせ(2 秒 / 15 秒)で SSE は作らない**(1-4)。即時性は上がらない代わりに入口の作りを変えない。
2. **器は「包んで見せる」で先に進め、器を 1 つにする OPT2 の後半は新しい画面の直後**(2-1・2-2)。RS8 の中でやらない。
3. **案件の中身と人の操作は ② を通さず ③④ の今の口のまま・② が持つ案件の知識は「根」まで**(3 節)。画面側で `status` と `cases` を突き合わせる。
4. **取り消し・やり直しを `POST /api/flow/cancel`・`/retry` の 1 つにする**(③ の届ける・検索も同じ口で止められる)。旧い cancel の口は新しい画面に替えるまで残す。
- AI が仮で決めて進める物(確認は要らない): `id` の頭の表・`kind` と `state` の語彙・2 秒 / 15 秒・直近 30 件・`cases{}` の 3 項目・`rev` の持ち方・S1〜S4 の割り振り。
