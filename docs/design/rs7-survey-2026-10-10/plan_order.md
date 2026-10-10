状態(2026-10-10): RS7 の段の並びの案(Fable・high・読むだけ)。サブエージェントが本文で返した報告を、まとめ役が少し詰めて置いた。問いの答えは `plan/decisions.md` の 3-30

# RS7 段の並び(案)

根拠: `plan/role-restructure.md` 3〜5・8・10 節、`decisions.md` 3-29、この フォルダの下調べ 5 本、`src/home/live.py`・`autorun.py`・`src/flow/run.py`・`live_export.py`・`live_detect.py`・`placement.py`。

## 1. 範囲
**入れる物**
| 物 | どこまで | 理由 |
|---|---|---|
| 速度の直し | 段ごとの開始・終了の時刻を Run・結果の束・索引に記録するだけ | 0 秒で入り、URL 経路の不明な約 200 秒の正体が次の測定で分かる。他の速度案は頻度 0〜2% で効かない |
| 玄関の分割 | 案 B(② に常駐のライブ係・Run は 1 切り抜き 1 本のまま)を完成まで: 親の口 → スタジオなしの採用 → ライブ係 → AutoRunner の糸と記録を ② へ → launch を app/server.py に | ユーザー決定(友人もライブ)。案 A は配信中ずっと止まらない段と糸 1 本を抱える・案 C は変更が最大 |
| app/server.py | `git mv`(launch・mount → `src/app/`)+ Supervisor の切り出し。do_GET/do_POST の表化はしない | 玄関の分割と同じ起動し直しで入る。表化は UI の再考で API が変わるので後 |
| serve 3 本の骨組み | 最小(`ytt/serverkit.py`。約 100〜130 行減) | 単独で入り、取り込みの口を変えない。Handler の全面の mixin とルーティングの統一は RS8 |
| B-1 | case.json(素性だけ)+ 一覧の走査 + 既存の遅延の後付け | 決定 3-29 |
| 小さい項目 | start-file の口・`Run.public` の packs・CLI を 1 段に / 起動し直しと `.flow.lock` / `voice_rows` の別名 / バックアップが `作業用\` を写さない | RS6 で見つけた不具合・友人の PC の起動し直し・alias の最後の 1 件・B-2 の前に必ず |
| 設定 | 読み口 1 つ(`ytt/settings.read_all` の形)だけ。1 ファイル化は問い Q3 | 行数は増え速度に効かない・outDir は置き場所の決定に使う |

**RS8 以降**: B-2・B-3・O2・URL も CLI だけ / serve のルーティングの統一と Handler の全面の mixin / ui-kit の写しを `app/ui/` に 1 つ(約 5,300 行・UI の再考と一緒)/ `app/host.py` / 後処理だけ当て直す道(頻度 0)/ 評価の生出力のキャッシュ(⑤ の道具。improvements に 1 行)/ ポーリングの間隔 / 配信後の作り直しを run の別の実行にする G3 は 1 日を超えたら B-3 と一緒に。

## 2. 段の並び
**波 1(全部並列。入口を止めずに入れられる)**
| 段 | 中身 | 触るファイル | モデル | 目安 |
|---|---|---|---|---|
| 1a 時刻と start-file | `steps[].startedAt/finishedAt` を `_run_steps`・`Run.saved/public`・`write_result`・索引に / `Run.public` に packs・newDocs・文書単位でも `run.docs` に / `start_file(force, spec)` + `POST /api/autorun/start-file`(拡張子は `MEDIA_TYPES`・届けるは既定オフ)/ CLI の delegate を 1 段に・`Run.saved` に束の上書き | `flow/run.py`・`runlog.py`・`placement.write_result`・`home/autorun.py`・`launch.py` の `_post_autorun`・`app/cli.py` | Sonnet・medium | 3 h |
| 1b B-1 | `placement.ensure_case`(冪等・原子的)・`cases.snapshot` の走査と後付け・`.studio-id` は残す | `flow/placement.py`・`manage/cases/cases.py`・`ytt/names.py`・新 `flow/tests/test_placement.py` | Sonnet・medium | 3 h |
| 1c serverkit | `ytt/serverkit.py` + 3 本の serve を薄い包みに。状態コード・文言・表・modfwd は触らない | `ytt/serverkit.py`・3 本の `serve.py` | Sonnet・medium | 4 h |
| 1d 起動し直しと lock | `--wait-pid` で古い入口の終了を最大 90 秒待つ・次の番号に逃げず読める文で非 0・`LockBusy` を読める文に | `launch.py` の main・`manage/ops/restart.py` | Sonnet・medium | 2 h |
| 1e voice_rows | `match_known_voices(segs, key)`・`diar.learn_groups`・alias ok を消す | `flow/diar.py`・`human/proof/speakers.py`・新 `flow/tests/test_diar.py` | Sonnet・low | 2 h |
| 1f バックアップ | `plan_cases(out_dir)` = `作業用\*.json` と `.studio-id` だけを `cases\<題名>\作業用\` へ。戻すのは手で(文書) | `manage/keep/backup.py`・`launch.py:858`・`docs/spec/data-location.md` | Sonnet・medium | 2 h |
| G0 親の口 | `flow/livehost.py`(仮)に Protocol。`Detector/Exporter/LiveTx/Reporter/Archiver` をそれだけに依存させ、偽の host で Live なしに動くテストと `Live.close` の順を縛るテスト。動きは変えない | `flow/live_*.py`・新 livehost・`flow/tests/test_livehost.py` | Opus・high | 5 h |

**波 2(波 1 のあと。並列)**
| 段 | 中身 | 触るファイル | モデル | 目安 |
|---|---|---|---|---|
| G1a 採用の規則を ① へ | F-5 の純粋な選び方を `pipeline/analyze/adopt.py` に移す。`store.adopt_marks` は呼ぶだけ(golden で同値) | `pipeline/analyze/adopt.py`・`human/review/store.py` | Sonnet・medium | 3 h |
| G1b スタジオなしの採用 | `Live.adopt/_adopt_secs/_pad_secs/_studio_adopt_mark` を `flow/live_adopt.py`(仮)へ。マークの置き場を差し込み口に: StudioMarks(今の形。app が渡す)/ LocalMarks(既存 `MarkStore`) | `home/live.py`・`flow/live_adopt.py`・`flow/live_export.py`・`flow/live_detect.py` | Opus・high | 6 h |
| G4 AutoRunner を割る | 待ち行列・糸・記録・復元・`estimate` を `flow/queue.py`(仮)へ。受付・`build_spec`・ToolClient・友人の mixin は app に残す | `home/autorun.py`・`flow/queue.py`・`flow/run.py` | Opus・high | 6 h |

**波 3(直列)**
| 段 | 中身 | 触るファイル | モデル | 目安 |
|---|---|---|---|---|
| G2 ライブ係 | `flow/livesession.py`: `tick(now)` 冪等。録画の監督の判断・検出・採用・切り抜きごとに `queue.start_file`。状態は既存のファイルから復元。`Live` は HTTP の受け口・設定の読み・子プロセスの起こし方・スタジオのアダプタだけの殻。recorder の spawn は `pipeline/ingest` へ | `home/live.py`・`flow/livesession.py`・`flow/live_detect.py`・`pipeline/ingest/` | Opus・high | 1 日 |
| G3 配信後の作り直し | `Archiver._after_begin/_after_adopt` を `flow.run`(入力 = アーカイブ URL)に寄せる。1 日を超えるか動きが変わるなら RS8 へ | `flow/live_archive.py`・`flow/run.py` | Opus・high | 0.5〜1 日 |
| G5 app/server.py | `git mv launch.py → src/app/server.py`・`mount.py → src/app/`・Supervisor + Tool → `src/app/supervisor.py`・start.bat・読み手 27 ファイル。旧 `src/home/launch.py` は runpy の転送(起動し直しのあとに消す) | 上記 + `dev/layer_map.py` | Sonnet・medium | 4 h |
| Z まとめ | lint 0・層 0・unittest 一式・契約(単独)・e2e 一式(サブエージェントが止まってから)・文書・版 0.57.0 | | Opus | 半日 |

本物を確かめる区切り(配信の無い時間に): R1 = 波 1 のあと(任意)/ **R2 = G5 のあと(必ず)**: start.bat → ライブ 1 本 + 配信後の作り直し 1 本 + CLI の動画 1 本。

見積もり: AI の作業 約 45 h → 壁時計 2.5〜3 日。

## 3. ユーザーに聞く問い(答えは decisions 3-30)
- Q1 友人の PC のライブでスタジオの画面を使うか: A 使わない / B 画面も配る / C 当面 A で作り、画面を配るかは UI の再考で(推奨)
- Q2 友人へ届ける段を友人の PC の ② に持つか: A 持たない(推奨)/ B 持つ
- Q3 設定 1 ファイルを RS7 で最終の形としてやるか: A 読み口 1 つだけ・1 ファイル化は UI の再考と一緒(推奨)/ B RS7 で新設 / C 1 ファイル化をやめる
- Q4 友人の PC での自動採用の安全弁: A 上限の本数だけ(推奨)/ B 未確認の数も数える / C 自動採用を使わない

## 4. AI が決める一時の形
- 親の口は `flow/livehost.py` の Protocol。名前は今のまま
- マークの置き場: `studio_call` を host が渡せば StudioMarks、無ければ LocalMarks
- F-5 の純粋な規則は `pipeline/analyze/adopt.py`
- ライブ係は既存の状態ファイルから復元・新しい保存を作らない。配信後の作り直しは別の実行
- Archiver の解析の依頼は G3 まで HTTP のまま
- AutoRunner の受付は app、糸・待ち・記録・復元・estimate は `flow/queue.py`。`Run.saved` に `specOverride`
- `POST /api/autorun/start-file` の本文 `{path, title?, streamer?, flow?, force?, deliver?, spec?}`。path は実在する `MEDIA_TYPES` だけ
- 起動し直し: `--wait-pid` 最大 90 秒・次の番号に逃げない
- 段の時刻は `steps[].startedAt/finishedAt`(ms)を足すだけ(`LOG_VERSION` 据え置き)
- case.json = `youtube-tools-case/v1 {id, media, title, channel, createdAt, madeBy}`。動画ファイルの案件の索引は autorun-runs.jsonl の resultPath
- バックアップは `作業用\*.json` と `.studio-id` だけ。戻すのは手で
- serverkit は最小。状態の持ち方は統一しない
- app/server.py: mv + Supervisor の切り出しだけ。識別子 "app"・`/api/ytt/`・`.runtime` は不変
- 版は Z で 0.57.0

## 5. 危険と止め方
- 本物の配信中に玄関を割らない: 波 3 と R2 は配信の無い時間に。G0 で `Live.close` の順をテストで縛り、G2 で「録画の途中で入口を起動し直す」の復元を unittest に
- 動きが変わる兆し(採用の id・`.clip.json` の形・エラーの文言・ジョブの状態の名前)が出たら戻す
- ② が二重に録画と検出を起こさない(RS7 の CLI はライブを持たない・`.flow.lock`)
- 並列の衝突: `launch.py`(1a・1d・1f)と `placement.py`(1a・1b)は region が別 = cherry-pick。G5 の `git mv` は最後
- データ: `ensure_case` は無いときだけ・バックアップはコピーだけ・設定ファイルは触らない
- 時間の上限: G3 が 1 日・G2 が 1.5 日を超えるなら RS8 へ(Live の殻は厚いまま動く = 一時の形として可)
- 友人の PC(CUDA)はこの PC で確かめられない = F1。`worker_client` は不変
