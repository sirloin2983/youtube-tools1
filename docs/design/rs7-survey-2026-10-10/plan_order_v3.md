状態(2026-10-11): RS7-2 の段の並びの第 3 版(Fable・high・読むだけ)。RS7-1 が入った main を見て第 2 版の 2 節(RS7-2)を見直した。サブエージェントが本文で返した報告を、まとめ役がほぼそのまま置いた。(b) の問いはユーザーが寝ている間の仮決定 = `plan/decisions.md` の 3-31

# RS7-2 段の並び(第 3 版)

根拠: `plan_order_v2.md` 2 節・`live_split.md`・`plan/f1-friend-pc.md` 決めたこと 2〜9・`plan/rs8-cases-ui.md` 決めたこと 4・今のコード(行番号は 10-11 の main)。

## 0. 結論
- 第 2 版の骨(G0 → G1b → G2、`--headless`、B-1)は残す。**友人のライブは「友人のライブ配信の依頼」の経路(2-15)がもう ② の中にほぼある**(`live_requests.Store` + `Detector.requests_cfg` `src/flow/live_detect.py:176-186` + `adopt_for(req)` :181 + `Exporter._handoff` の request → `start_file` `src/flow/live_export.py:1104-1128`)。足りないのは **入口が封筒 + 束で受ける口・スタジオ無しのマーク・`GET /api/settings`/settings-ui.json の読み・`start_file` → `submit`・D-13 と届けるの hook 化** の 5 つ。G2 は「ライブ係を新しく書く」ではなく **`Live` から app でない部分を `flow/livesession.py` へ抜き出す**(案 B を抽出で実現)。
- **外す**: G1a(F-5 を ①)・G3(配信後の作り直し)・serverkit・`git mv launch.py → app/server.py`(G5b)は RS8 へ(理由は 1 節)。
- 目安: AI の作業 約 30 h → 壁時計 1〜1.5 日。G2 が 1 日を超えたら 6 節。

## 1. 第 2 版から変える所
| # | 変更 | 根拠 |
|---|---|---|
| 1 | **G1a(F-5 を `pipeline/analyze/adopt.py`)は G1b の前提ではない → RS8 の B-3 へ**。ライブの採用は F-5 を通らない: `Live.adopt` `src/home/live.py:881` → `_studio_adopt_mark` :842-879(kind live の配信を登録 + 区間 ±0.5 秒の使い回し + 採用の印 + 番号 n)。F-5 `store.adopt_marks` は kind live を断る(`src/human/review/store.py:783-784`)。F-5 の持ち主は B-3 で候補と採用が案件へ移るとき必ず変わる = 2 度割らない | `live.py:842-916`・`store.py:763-830`・`rs8-cases-ui.md` 決めたこと 4 |
| 2 | **G3 も RS8 へ**(G1a と一緒。`Archiver._after_adopt` `src/flow/live_archive.py:968` は独自の `pick_candidates`・`_after_begin` の解析の依頼 :870-882 は HTTP)。RS7-2 では「`GET /api/settings` を束に置き換える」だけ(:867) | `live_archive.py:825-1010` |
| 3 | **serverkit は RS8**(F1 に効かない・RS8 で Handler を組み直す)。決定 3-30 の「余り」の枠を使わない | `plan/decisions.md:541`・`plan_order.md:19` |
| 4 | **G5 を割る**: G5a `--headless` は `launch.py` に旗を足すだけ(1,367 行の `git mv` と 27 の読み手・`test_launch` 45 件・e2e の写しの一覧は F1 に効かない)。G5b の mv は RS8 の app/ui の組み直しと一緒。識別子 "app"・URL・`.runtime` は不変 | `src/home/launch.py:845-900, 1279-1362` |
| 5 | **G2 の中身を具体化**: (a) 封筒 kind live は Run を作らず `Queue.submit` が `live` の hook へ回す(今は `Run.from_envelope` が断る `src/flow/run.py:318-319`)。(b) 束に検出・採用の欄(`adopt.sens/waitMin/afterStream`。`top`・`pad`・`perHour` はある `src/flow/spec.py:121`)。(c) 録画ごとの封筒 + 束を `live/bundles.json` に残す(第 2 版の「新しい保存を作らない」を覆す = 「束は受けたとき」を守るには録画ごとに束を置く場所が要る。`requests.json` は友人の依頼の印のまま)。(d) `Detector.spec()` `live_detect.py:195-207`・`Archiver` :867・`studio_audio` `live.py:223-244`・`auto_cfg` :347-354 を束から。(e) `_handoff` → `queue.submit(kind file, 束 = 録画の束 + request の speakers/videoTracks/cut)`。(f) D-13(`unconfirmed` `live.py:298`・`stop_long_requests` :713)と届ける(`_auto_deliver_for` :758)は host の hook | 上の各行 |
| 6 | **G0 の範囲を縮める**: `Archiver`・`Cleaner` はもう関数で受けている(`live.py:371-380, 388-389`)= Protocol は `Detector`・`LiveTx`・`Reporter`・`Exporter` の 4 つだけ | `live_detect.py`・`live_tx.py`・`live_report.py`・`live_export.py` |
| 7 | **足りない物**: `status()` に録画・検出の動きを足す(送るアプリの「終わったら閉じる」= `idle` が録画中は偽。`src/flow/runqueue.py:369-380` は実行だけ)/ headless で入口が動いているなら非 0 で終える / `flow/keys` が `adopt` 節を鍵に入れていないことを先に確かめる | |
| 8 | 済んだ物は無い。`Run.public` の packs は入ったが「飛ばしたパック」が載らない → 3 節 | `run.py:1115-1117, 1017-1030` |

## 2. 段の表(worktree で並列 → まとめ役が cherry-pick。段ごとは unittest・lint・層の検査)
| 段 | 中身 | 触るファイル | モデル | 目安 | 並列 | 衝突 |
|---|---|---|---|---|---|---|
| P0 packs の直し(**済み 10-11 fd0e8d0**) | 3 節 | `flow/run.py`・`keys.py`・`placement.py`・`test_run` | Sonnet・medium | 1.5 h | | |
| **波 A** | | | | | | |
| G0 親の口 | `flow/livehost.py` に Protocol。4 つの子を `host` に依存させる(動きは変えない)。偽 host で `Detector/LiveTx/Reporter/Exporter` が `Live` なしに動く unittest・`Live.close` の順を縛る unittest | `flow/live_detect.py`・`live_tx.py`・`live_report.py`・`live_export.py`・`home/live.py`・新 `flow/tests/test_livehost.py` | Opus・high | 4 h | ○ | `live_export.py`(G1b と直列) |
| 1b B-1 | `placement.ensure_case(media)`(冪等・原子的・無いときだけ)= `case.json` `youtube-tools-case/v1 {id, media, title, channel, createdAt, madeBy}`、`cases.snapshot` が案件の根を走査して既存の案件に後付け、`.studio-id` は残す | `flow/placement.py`・`manage/cases/cases.py`・テスト・spec/data-location | Sonnet・medium | 3 h | ○ | なし |
| G5a `--headless` | `launch.py` に `--headless`: ブラウザを開かない・③ の見張りを起こさない・取り込みと ② は載せる・合言葉とポートを標準出力の 1 行 JSON・入口が動いていれば読める文で非 0・`status()` に `live: {recording, detecting}` を足し `idle` に効かせる | `launch.py`・`flow/runqueue.py`(status)・`test_launch.py`・`test_runqueue.py` | Opus・high | 4 h | ○ | `launch.py` |
| G2a 封筒・束・口 | `envelope` kind live の input・束に `adopt.sens/waitMin/afterStream`・`Queue.submit` が kind live を hook へ(無ければ今の ValueError) | `flow/envelope.py`・`spec.py`・`runqueue.py`(submit)・`run.py`(from_envelope)・テスト | Sonnet・medium | 3 h | ○ | `runqueue.py`(G5a と region が別) |
| **波 B** | | | | | | |
| G1b スタジオなしの採用 | `Live.adopt` と周りを `flow/live_adopt.py` へ。マークの置き場を差し込み口に: `StudioMarks`(今の動き)/ `LocalMarks`(`live_export.MarkStore` に採用の印と番号)。本数の上限は `adopt.top`(友人の PC)/ D-13(ユーザーの PC) | `home/live.py`・`flow/live_adopt.py`(新)・`flow/live_export.py`・`flow/live_detect.py`・テスト | Opus・high | 5 h | ○ | `live_export.py`(G0 のあと) |
| **波 C** | | | | | | |
| G2b ライブ係 | `flow/livesession.py` = `Live` から app でない部分を抜き出す。`host` = G0 の Protocol + `may_adopt`(D-13)・`deliver_for`・`marks`(G1b)。受付 = `submit(封筒, 束)`: 録画を始めて `live/bundles.json` に封筒 + 束。検出・解析・音量・auto_cfg は録画の束から。`_handoff` は `queue.submit(kind file)`。`home/live.py` は HTTP の受け口・中継・StudioMarks・届ける・D-13 の殻 | `home/live.py`・`flow/livesession.py`・`live_detect.py`・`live_archive.py`・`live_export.py`・`human/friend/intake.py`・`launch.py`・`test_live*` | Opus・high | 8〜10 h | × | 全部(1 体で) |
| Z2 まとめ | lint 0・層 0・unittest 一式・契約(単独)・e2e 一式・文書・版 **0.57.0** | | まとめ役 + Haiku | 半日 | | |
| RS8 へ送る | G5b `git mv launch.py → app/server.py`・G1a・G3・serverkit | | | | | |

## 3. 小さな直し「鍵で飛ばしたパックが packs に無い」(P0。済み)
`run.packs` は ① 全自動で Dropbox へ届ける物なので足さず、新しい欄 `run.kept_packs`。結果に出すのは `Run.all_packs()`(public・結果の束・CLI)。飛ばした文書も `run.docs` に。

## 4. 決めることの仕分け
**(a) AI が決める**: Protocol の名前と属性 / `live/bundles.json` の形 `{rc/rec: {envelope, spec, at}}` / 束の `adopt.sens/waitMin/afterStream` の名前と既定(今の `live_requests.SETTINGS_DEFAULT`)/ kind live は Run を作らず status の `live` 欄 / `start_file`・`/api/autorun/*`・`live_begin` は別名で残す / headless の標準出力の 1 行 `{"port", "token", "pid"}` / `LocalMarks` の採用の印の形 / 友人の PC の上限は `adopt.top`・ユーザーの PC は `AUTO_MAX_PER_REC` と D-13 のまま / 版 0.57.0 / G5b・G1a・G3・serverkit を RS8 へ。

**(b) ユーザーに確認(仮決定で進める = decisions 3-31)**:
| 物 | 何が変わるか | 仮決定 | 戻しやすさ |
|---|---|---|---|
| b1 ライブの検出・採用の設定を録画を始めたときに固定 | 今は 60 秒ごとにスタジオの解析の設定を読み直す = 配信中に設定を変えると効く。固定にすると効かなくなる | 固定にする(RS7-1 S4 と同じ理屈。配信中に変えるなら録画を止めて始め直す) | 易: 束を読み直す口を 1 つ足せば戻る |
| b2 書き出しの音量を settings-ui.json でなく束から | 画面の設定を変えても、始めた録画には効かない | 束から(b1 と同じ) | 易 |
| b3 ホームの設定 `live.auto.engine/model` の欄 | machine.json と二重 | 消さない(束の transcribe に写すだけ。消すのは UI の再考で) | 不要 |

## 5. 危険と止め方・R2
- 本物の配信中に触らない: 波 C の取り込み・Z2・R2 の前に録画中が無いことを見る。
- `Live.close` の順を G0 の unittest で縛る。
- 二重の ②: headless と start.bat は同じ作業データなら `.flow.lock` で 2 つ目が止まる。
- 束の欄の追加が鍵に波及しないことを G2a の最初に確かめる(adopt 節は鍵に入れない)。
- 動きが変わる兆し(採用の id・`.clip.json` の形・ジョブの状態の名前・`requests.json` の形)が出たら戻す。`bundles.json` は足すだけ・無ければ今までどおり。
- G2b は 1 体で。波 A・B のサブエージェントが止まってから。
- **R2**:
  - AI だけでできる: (1) `--headless` で起こし、標準出力の 1 行で CLI から submit → status の idle → 終了で `.flow.lock` が消える / (2) headless の間に start.bat の入口を起こす → 止まる / (3) `e2e_live*` 3 本 / (4) 封筒 kind live を submit → 偽の配信元で録画 → 検出 → 採用(LocalMarks)→ 書き出し → 文字起こし → パック(headless)/ (5) 文字起こしの最中に restart-self で続きから。
  - ユーザーの手が要る(配信の無い時間に 30 分): 起動し直し → 本物の配信 1 本をスタジオの URL の欄から(StudioMarks・自動採用・届ける)→ 配信後の作り直し 1 本 → 「すべて終了」で録画の部品が止まる。

## 6. 時間の上限
- G2b が 1 日を超えたら: `Live.begin`(ユーザーの PC の自分の配信)は束を組まず今の読み方のまま残し、封筒 kind live(友人の依頼・headless)だけ束で動く所で切って Z2 → R2 へ。残りは RS8 の B-3 と一緒。
- RS7-2 は割らない。G5b・G1a・G3・serverkit は最初から RS8。
