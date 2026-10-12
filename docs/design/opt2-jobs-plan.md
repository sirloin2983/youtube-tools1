状態(2026-10-11 夜): 計画(段の並びは Fable。仮決めは `plan/decisions.md` 3-42)。実装は J0 から

# OPT2 後半: ジョブの器を本当に ② の 1 つに — 段の並び

関連: `plan/opt-pipeline-flow.md`(OPT2 の 56・64・73・80・91・129・142 行)・`docs/design/rs8-flow-api.md`(掲示板)・`docs/spec/pipeline.md` 2.9・掲示板の包み(b5186b3・e7af9ac・9cec613・a935a83・81c78cc)・層の向き `dev/layer_map.py`。
範囲外: 音量/ラウドネス(決定 3-35。10-11 夜の答え = 消すのを待つ)・画面の JS(触らない。API の応答の形は変えない)。

## 0. 要約
| 問い | 決めたこと |
| --- | --- |
| ① をどう「指定 → 結果」にするか | ① の関数は `fn(spec, ctl, …) -> 結果` の 1 形。進み具合・取り消し・途中の覚え書きは `ytt/jobs.Ctl`(今の `cut2resolve_core.Task` を ytt へ上げた物)1 つで渡す。子プロセスは `ytt/tools.run_progress(cancelled=ctl.cancelled, spawn=True)` の見張りが止める = ① が `job["proc"]` を持たない。枠 `SLOTS` は ① では取らない(取るのは ② の器) |
| ② の「1 つの器」 | `flow/jobs.Table`(種類ごとに 1 インスタンス・コードは 1 か所)。積む・1 本ずつ動かす・枠・状態・取り消し・やり直し・履歴・掲示板への写しは Table。種類ごとの違い(同時 1 本 / 最大 10 本 / 同じ動画は 1 つ・kind・title)は引数 |
| 何を ② に出すか | ① に残る器は 解析 an(analyze の辞書)と 書き出し ex(exporter の表)の 2 つだけ。パックの `Task` は器ではなく手渡し(= Ctl の原型)。pk の器は app の `cut2resolve/serve.AppState` |
| 効き目 | ② が ① を直に呼べる = Runner の HttpTools の ① の動詞・`_call_when_free` の 409 待ち・`live_archive._section` のスタジオ HTTP 越しの待ちが消える・headless でも作り直しが動く・鍵を ② の段の終わりで書ける |
| やらない | ライブの 3 器(lx・la・lt)の Table 化・③ の 2 器(dl・se)・HttpTools の完全な削除(③ の読みは残る)・`build_spec` を ① から出す → RV |

## 1. 今の器 10 通り
| 頭 | 器 | 層 | 場所 | 呼び手 | 画面 |
| --- | --- | --- | --- | --- | --- |
| an | 解析の辞書 + `flow/batch.Batch` | ①(辞書)+ ②(列) | `pipeline/analyze/analyze.py`(new_job・cancel_job・skip_chat・run_analyze)・`fetch.py` が job を読む 10 か所・`flow/batch.py` | スタジオ `/api/queue*`・② Runner(HTTP)・`flow/studiobook`(直)・`live_archive._after_analyze`(HTTP) | `queue.js`(新しい案件) |
| ex | 書き出しの表 `exporter._jobs` | ①(② の仕事) | `pipeline/export/exporter.py`(器 ≈ 130 行・job の参照 ≈ 20 か所) | スタジオ `/api/export*`・`/api/live/section`・`is_busy`(削除・出力先・終了)・studiobook(直)・Runner(HTTP + 409 待ち)・`live_archive._section`(HTTP の待ちループ) | `review.js` |
| pk | `cut2resolve_core.Task` + `cut2resolve/serve.AppState` | ①(手渡し)+ app(表) | `cut2resolve_core.py` 65-90・`cut2resolve/serve.py` 161-306 | `/api/plan|build|job|job/cancel`・Runner(HTTP)・LocalTools(直) | `pack-tab.js`・`panels/cut.js`・`app-tools.js` |
| tx | `flow/jobs` の表(モジュール変数) | ② | `flow/jobs.py` | 編集 `/api/jobs` など・Runner(HTTP) | `app-jobs.js` など |
| run | `flow/runqueue.Queue` | ② | | 入口 `/api/flow/*` | `cases.js`・`portal.js` |
| lx・la・lt | ライブの Exporter・Archiver・LiveTx | ② | `flow/live_*.py` | `/live/api/*` | `review.js` |
| dl・se | `deliver.Deliveries`・`rank._jobs` | ③ | `human/friend/deliver.py`・`human/find/rank.py` | 入口 `api/ytt/deliver`・スタジオ `/api/rank/search*` | `portal.js`・`rank.js` |

## 2. 共通の形 `ytt/jobs.Ctl`
`cut2resolve_core.Task` を `ytt/jobs.py` へ上げて少し足す(`Task` は別名で残す)。

```python
class Ctl:
    """① の関数への手渡し: 進み具合の報告・取り消し・途中の覚え書き。器(②)が 1 ジョブに 1 つ作って渡す。CLI は None でもよい"""
    def cancelled(self) -> bool             # run_progress(cancelled=…)・SLOTS.slot(cancelled=…) にそのまま
    def cancel(self)
    def check(self)                         # 立っていれば Cancelled(exc= で例外の型を選べる = パックは core の Cancelled)
    def report(self, frac=None, message=None)
    def note(self, key, value)              # 器に見せる途中の値(解析の chat の状態など)
    def flag(self, name) / raise_flag(name) # 器 → ① への小さな合図(skipChat)
    def span(self, lo, hi) -> Ctl           # 子: report を lo〜hi に写す(cancel・note は親と共有)
    def timer(self, dur) -> callable        # run_progress の on_time 用
```
決まり: 子プロセスは Ctl に入れない(`run_progress` の見張りが 0.3 秒で止める)・枠は ② の器が取る・① は state を書かない(失敗は例外)・`check_cancel(job)` は tx のために残す(J8 で ctl も見る)。

## 3. ② の最終形 `flow/jobs.Table`
```python
class Table:
    def __init__(self, prefix, tool, *, kinds, admit=None, keep=30, lanes=1, log=None, board=None, slots=None)
    def add(self, spec, kind) -> job
    def get(self, jid) / list(self) / cancel(self, jid) / retry(self, jid) / cancel_all(self) / shutdown(self)
    def busy(self, pred=None) -> bool
    def board_jobs / board_cancel / board_retry / attach_board(board)
```
既存の `flow/jobs` のモジュール関数は既定の Table("tx") への転送で残す。掲示板の id の頭(an・ex・pk・tx)は今のまま。

## 4. 段(1 段 = 1 コミット)
| 段 | 中身 | 主なファイル | 形を保つ物 | テスト | 並列 |
| --- | --- | --- | --- | --- | --- |
| J0 | `ytt/jobs.Ctl`・`cut2resolve_core.Task = Ctl` の別名・`procs.run_capture` が ctl も受ける | `ytt/jobs.py`・`cut2resolve_core.py`・`ytt/procs.py` | pack.py・request.py・serve | ytt・パック・cut2resolve・契約(単独)・層 | 最初に 1 本 |
| J1 | 解析を関数に: `analyze.run(spec, ctl) -> result`・`fetch` の job → (ctl, 実行ごとの辞書)・`flow/batch` が Ctl を作る。`new_job` などは互換の包みで 1 段だけ残す | `analyze.py`・`fetch.py`・`flow/batch.py` | `/api/queue` の形・`queue.js` | 解析・スタジオ・test_board_s2・studiobook・run・`e2e_analyze` | J2・J3 と並列 |
| J2 | 書き出しを関数に + ② の器 `flow/export.py`(ExportJobs: 同時 1 本 409・履歴 20・枠・`_out_lock` の下で登録・public は今の `job_public` と同じ)。① の `_jobs`・`start_job`・`cancel*`・`is_busy*`・`board_*` を消す | `exporter.py`・`flow/export.py`(新)・`studio/serve.py`・`flow/studiobook.py`・`layer_map.py` | `/api/export*`・`/api/live/section` の応答・`review.js` | 書き出し・スタジオ・studiobook・新しい test_export_jobs・`e2e_cases_cand`・`e2e_pipeline` | いちばん重い(Opus) |
| J3 | パックの器(app の AppState)を ② の `flow/packjobs.py` へ | `cut2resolve/serve.py`・`flow/packjobs.py`(新) | `/api/plan|build|job*` の形 | test_serve・パック・契約・`e2e_cases_cut` | J1・J2 と並列 |
| J4 | J1・J2 の互換の包みを消す・opt-pipeline-flow.md に済み | | | J1・J2 の一式 | J1・J2 のあと |
| J5 | `live_archive._section` のスタジオ HTTP を `flow/export` の直呼びに・`_after_analyze` は `flow/batch` を直に読む(`/api/video` の ③ は HTTP のまま) | `live_archive.py`・`livesession.py` | `/live/api/archive*`・`archive.json` | live_archive・livesession・`e2e_live_archive`(単独) | J2 のあと |
| J6 | `flow/jobs.Table` を作り an・ex・pk を載せる | `flow/jobs.py`・`batch.py`・`export.py`・`packjobs.py` | 各 API の応答 | ② 一式・スタジオ・cut2resolve・層 | J1〜J3 のあと |
| J7 | Runner が ① を直に呼ぶ(HttpTools の ① の動詞を消す。③ の動詞は残す)・`_call_when_free` を Table の待ちに | `flow/tools.py`・`flow/run.py`・`home/autorun.py`・`app/cli.py` | `/api/flow/status` の runs・steps の文・`Run.owned` | run・runqueue・tools・autorun・launch・cli・`e2e_autorun`・`e2e_pipeline` | J6 のあと(Opus) |
| J8 | 編集の tx を Table の既定インスタンスに(state の値 loading・extracting は残す) | `flow/jobs.py`・`flow/wire.py` | 編集 `/api/jobs` | `dev/run_editor_suite.py`・② | J7 と並列可 |
| J9(任意) | 鍵を ② の段の終わりで書く(②-2) | `flow/keys.py`・`run.py`・両 serve | 鍵のファイルの形 | test_keys・run・e2e_pipeline | J7 のあと |

並べ方: J0 → {J1, J2, J3} → J4 → {J5, J6} → {J7, J8} → J9。

## 5. やらない(RV へ)
- ライブの 3 器を Table に: もう ② にあり、永続・録画待ち・受け渡し・配信後の全自動と密。差分が 1,000 行を超えて行数は減らない。RV の `Archiver` を割る話と一緒に
- ③ の dl・se: ① を含まない(zip と YouTube API)。掲示板には載っている
- HttpTools の完全な削除: ② は ③ を読めない。③ の口は RV の「ホストの口」と一緒に
- ② の Run(runqueue)を Table に: 段・封筒・束・履歴を持つ別物
- 取り消しの即時 terminate を Ctl に残す: 見張りは 0.3 秒・画面は 2 秒ごと

## 6. 危ない所と確かめ方
- 層: 新しい `flow/export.py`・`flow/packjobs.py` は ytt・pipeline・flow だけ。① から flow を読まない。FILES に足す
- API の形: 段ごとに応答の鍵と値の型を unittest で縛る。形が変われば止める
- 終了の流れ(`shutdown_jobs`・`studiobook.close`・`livesession.close`)の `cancel_all`・`is_busy` の意味を保つ
- 書き出しの `_env._out_lock` の排他を落とさない
- J2 は exporter の中で `job` が「器」と「結果」の 2 つの意味 → `res` と `ctl` に分けて `job[` を 0 にしてから通す
- e2e は少なめ: J2 のあと `e2e_cases_cand`、J5 のあと `e2e_live_archive`、J7 のあと `e2e_autorun`・`e2e_pipeline`、全部のあと一式
