# HANDOVER — 次のセッションへの引き継ぎ(2026-10-11。役割で組み直す計画 = RS7-1 束と口 は済み(本物の確認も済み)。次は RS7-2)

セッションを切り替えるたびに上書きする。全体の計画と進捗は `plan/index.html`(データ `plan/data.js`)、文書の索引は `docs/ROADMAP.md`、経緯は `docs/WORKLOG.md`

## いまの状態
- 作業フォルダは `C:\dev\youtube-tools`(GitHub: https://github.com/sirloin2983/youtube-tools1)。**push はユーザーが `push.bat`**
- **版**: 全体で 1 つ = `src/ytt/version.py` の **0.56.0**(仮。1.0.0 は RS8・V1・見直し 1 周・F1 が全部済んでから = `plan/rs8-cases-ui.md`)・ui-kit v25・送るアプリ 2.10.0
- **層は 5 つ**: ① 道具 `src/pipeline/`・② 管理 `src/flow/`・③ 人 `src/human/`・④ データ `src/manage/`・⑤ 検証 `src/eval/`・app は全部を読める。③④ は ① を直に読まず ② を通す。向きは `dev/layer_map.py` の `ALLOWED` と `dev/tests/test_layering.py`(違反 0・flow の別名 0 = `# flow: alias ok` は無くなった)
- **RS7 は 2 つに割った**(decisions 3-30・`docs/design/rs7-survey-2026-10-10/plan_order_v2.md`): RS7-1 束と口(**実装済み 10-11**)/ RS7-2 玄関とヘッドレス(次)。先に測った結果、鍵で飛ばせる時間は実績で小さい = 形の整理に寄せた
- **RS7-1 で入った物**: この PC の設定 `flow/machine.py`(作業データの根の `machine.json`・`YTT_MACHINE_*`・`TRANSCRIBE_DEVICE` は旧い名前・overlay は明示した値だけ)/ 封筒 `flow/envelope.py`(`{id, kind, input, requestId, deliver, note, createdAt, specVersion}` + 一時の `legacy`)/ 待ち行列 `flow/runqueue.py` の Queue(糸・待ちの記録 版 2 = 封筒 + 束・`submit`・`status`。AutoRunner は受付と hook だけで Queue を継ぐ)/ 束は受けたときに組む / `POST /api/flow/submit`・`GET /api/flow/status` / CLI は入口に submit 1 回(古い入口は 2 段)/ `Run.screen` と `spec.SCREEN` を消した = 精密・画質の上限なし・fps 30 を固定(画面の欄 3 つも消した)/ 束に後処理 6 項目・`post.llmModel`・`post.learning.version`(場所は machine の learningDir)・`run.repack`・`run.pinned` / 段ごとの時刻 `steps[].startedAt/finishedAt` / 起動し直しは古い入口の pid を最大 90 秒待ち、次の番号に逃げない / バックアップが案件の `作業用` の json を `cases\` へ / 覚えた声に `learnedFrom`。仕様は `docs/spec/pipeline.md` 2.8・計画と違えた所は `plan/role-restructure.md` 8 節「RS7-1 の結果」
- テスト(10-11・a83c51b 以降): unittest 約 2,808 件・node 64・lint 0・ui_audit Must 0・**e2e 一式 31 本 OK**

## 次
1. ~~R1(RS7-1 の本物の確認)~~ **済み 10-11 1 時台**: ユーザーのまとめて実行 1 本(スマート アプリ コントロールが whisper-cli.exe を止めた → ユーザーがオフにして通った)・AI の CLI の submit と、文字起こしの最中の restart-self で新しい入口が続きから流した。WORKLOG の末尾
2. **RS7-2 玄関とヘッドレス**(plan_order_v2.md の 2 節): 波 4 = G0 親の口(`flow/livehost.py` の Protocol)∥ G1a F-5 の規則を ① へ ∥ 1b B-1(case.json)∥ serverkit(余り)→ 波 5 = G1b スタジオなしの採用(StudioMarks / LocalMarks)∥ G5 `app/server.py --headless` → 波 6 = G2 ライブ係 `flow/livesession.py`(ライブの依頼も封筒 + 束・`GET /api/settings` をやめる)→ G3(余り)→ Z2(e2e 一式・文書・版 0.57.0・R2 = ライブ 1 本・配信後の作り直し 1 本・headless に CLI から submit 1 本)
3. そのあと RS8(`plan/rs8-cases-ui.md`: 画面の形を紙で → B-2 → B-3 → O2 → URL も CLI → 新しい画面)・F1 の送るアプリの側(`plan/f1-friend-pc.md`。C#。RS7-2 のあと)
- 後へ回したもの: CLI の結果でパックを鍵で飛ばすと packs が空(前のパックは残っている)/ S3 の一時の形(封筒の `legacy{mode, onFail, streamer}`・`run.pinned`・待ちの記録に欄の鍵も残す)は RS7-2 以降で封筒 + 束だけに / 配信者を `hints.people` の先頭にする決まりは submit で封筒に配信者が無いときだけ / スタジオの test_api の test_origin_on_writes は組の中だけで時々落ちる / AGENTS.md の analytics のテストの書き方(ImportError)/ O2 の行き先(機械の結果 + 人の層から組み立てる)に逆らわない(`plan/rs8-cases-ui.md`)

## 注意(引き継ぐこと)
- **友人の前提**: 配る友人は 1 人・RTX 3060。友人の PC では送るアプリ(C#)が ② を画面なし・③ なしの子プロセスとして起こす(常駐しない)。② の口は 1 つ(ユーザーの入口・友人のアプリ・CLI)。D-13 は友人の PC に持たせない・届ける段も持たない(`plan/f1-friend-pc.md`)
- **Windows のスマート アプリ コントロール**: この PC は 10-11 にオフにした(自分でビルドした署名の無い whisper.cpp・llama.cpp が止まるため。WinError 4551)。友人の PC でオンなら同じく止まる = F1 で確かめる
- **一時の形はユーザーに聞かない**。聞くのは機能・データを消す・使い方が変わる・最終の形を決める物だけ
- 移した名前を別の部品に別名で残さない。serve の `_ED_MODULES` に新しい持ち主を足す。`modfwd.duplicates` 0 件
- **サブエージェントの実装と e2e を同時に流すと待ちのあるテストが揺れる**。最後の一式はサブエージェントが止まってから
- worktree のサブエージェント: 最初に `git merge --ff-only main`・main が進んだら SendMessage で rebase を頼む・取り込みは cherry-pick。`launch.py`・`autorun.py`・`spec.py`・`run.py` の衝突はまとめ役
- unittest に `PYTHONIOENCODING=utf-8` を付けない。e2e には付けて 1 本ずつ(`py -3.10 dev/run_e2e.py`)。`test_mount`・契約テスト・cut2resolve の test_serve は単独で。編集のテストは `src/editor/tests` に cd して `py -3.10 -m unittest test_metrics test_settings_schema`
- ファイルは差分で直す(多くは CRLF。**`sed -i` 禁止** = 10-11 にも data.js を LF にしかけた)。plan/data.js を直したら公開ページも出し直す(断られたら写しを全部 Read → user-tasks を read → 同じ物を 2 回送ると通る)
- 別のセッション(「完了内容と今後の計画」)が `plan/`・`docs/design/briefs/rs8-cases/` を触っている。`git add -A` を使わない
- 入口が起動中の間はコードを変えても古いまま動く。**配信中に入口を落とさない**

## 次のセッションに貼る指示文
「AGENTS.md → plan/data.js → docs/HANDOVER.md → docs/WORKLOG.md の末尾 3 件 → git status・git log -15 を見て。役割で組み直す計画は RS7-1(束と口)まで済み(本物の確認 R1 も済み。decisions 3-30・docs/design/rs7-survey-2026-10-10/plan_order_v2.md)。HANDOVER の『次』の 2 の RS7-2(玄関とヘッドレス)を、Fable と段の並びの見直し → 一時の形でない物だけユーザーに確認 → 実装の順で。小さな直しとして、CLI の結果の JSON でパックを鍵で飛ばしたときに packs が空になる所も RS7-2 で。友人の PC の形は plan/f1-friend-pc.md・RS8 は plan/rs8-cases-ui.md。サブエージェントは仕事に合わせてモデルとエフォートを選ぶ(単純作業は Haiku・low)。段ごとは unittest・lint・層だけ・e2e 一式と文書は RS の終わりに 1 回。重要な判断は Fable と相談。」
