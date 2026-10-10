# HANDOVER — 次のセッションへの引き継ぎ(2026-10-11。役割で組み直す計画 = RS7-2 玄関とヘッドレス は済み(AI の分の本物の確認 R2 も済み)・使わないモデルを消した(0.58.0)。**RS8 を始めた: ③④ の見直し・B-2 の 0〜3・OPT1 は済み(10-11 早朝)。次は B2-4(仮決め 3-36 の確認 → docMove をオン → 本物で移行)→ B-3**)

セッションを切り替えるたびに上書きする。全体の計画と進捗は `plan/index.html`(データ `plan/data.js`)、文書の索引は `docs/ROADMAP.md`、経緯は `docs/WORKLOG.md`

## いまの状態
- 作業フォルダは `C:\dev\youtube-tools`(GitHub: https://github.com/sirloin2983/youtube-tools1)。**push はユーザーが `push.bat`**
- **版**: 全体で 1 つ = `src/ytt/version.py` の **0.58.0**(仮。1.0.0 は RS8・V1・F1・RV 全体の見直しが全部済んでから = decisions 3-33)・ui-kit v25・送るアプリ 2.10.0。ユーザーの入口は 0.57.0 で動いている = 0.58.0 にするには「すべて終了」→ start.bat(画面に版の赤い帯が出る)
- **層は 5 つ**: ① 道具 `src/pipeline/`・② 管理 `src/flow/`・③ 人 `src/human/`・④ データ `src/manage/`・⑤ 検証 `src/eval/`・app は全部を読める。③④ は ① を直に読まず ② を通す。向きは `dev/layer_map.py` の `ALLOWED` と `dev/tests/test_layering.py`(違反 0)
- **RS7-1 束と口・RS7-2 玄関とヘッドレス は済み**。RS7-2 の段の並びは `docs/design/rs7-survey-2026-10-10/plan_order_v3.md`(Fable)、結果は `plan/role-restructure.md` 8 節「RS7-2 の結果」、仕様は `docs/spec/pipeline.md` 2.8・`docs/spec/data-location.md`
- **RS7-2 で入った物**: ライブの親の口 `flow/livehost.py`(10-11 の片付けで `LiveHost` 1 つ + `RequestBook`・`MarkBook` に)/ 採用 `flow/live_adopt.py`(StudioMarks = スタジオの HTTP / LocalMarks = スタジオなし)/ ライブ係 `flow/livesession.py`(Live から app でない部分を抜き出した。封筒 kind `live` + 束で録画を始め、録画ごとの束を `live/bundles.json`。検出・採用の待ち・配信後の解析・書き出しの音量はその束から。書き出したあとは `Queue.submit(kind file)`)/ 入口の `--headless`(ready の 1 行・既に動いていれば終了コード 3・restart-self は 409・status に `live` と `idle`)/ 案件の `作業用\case.json`(`flow/placement.ensure_case`)/ 鍵で飛ばしたパックも結果の `keptPacks` に / 書き込み系を断るとき本文を読み捨てる(3 ツール)/ パックの書き出しの取り消しの競合の直し
- **決定 3-31(10-11 朝にユーザー確認済み)**: b1 ライブの検出・採用の設定は録画を始めたときの束に固定 / b2 書き出しの音量も同じ / b3 ホームの `live.auto.engine/model` の欄は残す・選べるモデルは普段使う物だけ。**自分の配信(スタジオの URL の欄)は束を組まず今の読み方のまま**(= b1・b2 は友人の依頼と headless の録画にだけ効く。RS8 で自分の配信も束に)
- **使わないモデル・エンジンの選択肢を消した(0.58.0。b74e86d)**: 残したのは whisper.cpp(Vulkan)+ large-v3・faster-whisper は内部の CPU の逃げ道だけ・SenseVoice-small・Qwen3-8B・Qwen3-ASR 1.7B(2 つ目)・voxceleb。Qwen3-ASR 0.6B のエンジン・small/medium/turbo/kotoba・処理方式の auto/cuda/cpu・2 つ目の whisper.cpp/faster-whisper・campplus/standard は消した(欄は残す)。保存済みの古い値は `flow/spec.read_legacy_tx` で今の値に読み替え(断らない)。束の既定は whisper.cpp・large-v3・vulkan
- テスト(10-11・8e7f901): unittest 23 組・3,417 件 OK(フォルダごとにまとめて 1 プロセス = 16 分)・lint 0・層 0・契約 35 件・**e2e 一式 31 本 OK**(e2e_autorun は case.json の置き場所を直したあと単独で OK)。0.58.0 のあと: unittest 24 組・3,361 件 OK・画面に近い e2e 5 本 OK

## 次
0. **RS8 の今(10-11 早朝。WORKLOG の末尾)**: ③④ の見直しは `plan/opt-pipeline-flow.md` に足した。B-2 は 0〜3 が main に入った = バックアップの規則・文書の置き場所の口 `ytt/docloc.py`(索引 `transcripts/<id>.loc.json`)・付け替え・新しい文書を案件の 作業用 に置く・既存の文書を移す `src/manage/cases/docmove.py`。**既存の文書の自動の移行はスイッチ `machine.json` の `docMove`(既定オフ)で止めてある** = ユーザーが仮決め `plan/decisions.md` 3-36 を見てからオン → 入口を起動し直すと移る(1 回の起動で 50 本まで)→ 画面で本数を確かめ → `py -3.10 src/manage/cases/docmove.py --purge-migrated`(= B2-4)。OPT1 も済み(winget だけの PC の不具合を直した)。次は B-3(スタジオの data.json の候補と採用・cases.json の状態とメモ・友人の依頼の写しが 1 つの案件を共有する穴)
1. **RS8**(`plan/rs8-cases-ui.md`。**始めるときの条件 = 同じ文書の「RS8 を始めるときの条件」**(10-11 ユーザー了承): ③④ の見直し(読むだけ)∥ B-2 の下調べ ∥ OPT1 の実装(`plan/opt-pipeline-flow.md`。別の worktree。F1 より前に必ず)→ B-2 → B-3 → O2 → URL も CLI で →(② の口の形を決める)→ 新しい画面。新しい画面の進み具合は ② の status から読む)。設計の材料は `docs/design/briefs/rs8-cases/`(DESIGN_BRIEF・見本)。RS8 で一緒にやる RS7-2 の残り: 自分の配信も束で(e2e_live_studio の「配信中に waitMin を変える」を b1 に合わせて書き直す)・G1a F-5 の規則を ① へ・G3 配信後の作り直しを run に寄せる・serverkit・`launch.py` → `app/server.py` の mv・headless の配信後の全自動が LocalMarks の採用の印を見ない(重なりうる)
2. 優先の順(decisions 3-33): RS8 → V1 → F1(送るアプリの側。C#。`plan/f1-friend-pc.md`)→ RV 全体の見直し 1 周 → 1.0.0。本物の確認は AI の分で済みにして止めない(3-32)・ユーザーの分は data.js のやること R2(普段の配信のついでに後追い)
- 後へ回したもの: 入口が立ち上がった直後(編集の取り込みが終わる前)に CLI が submit すると「編集が動いていない」で失敗する / S3 の一時の形(封筒の `legacy{mode, onFail, streamer}`・`run.pinned`・待ちの記録の欄の鍵)を封筒 + 束だけに / 配信者を `hints.people` の先頭にする決まりは submit で封筒に配信者が無いときだけ / 依頼も束も無い録画の受け渡しは onFail が "next" 固定・build_spec の知らせが封筒に乗らない(1 本だけなので実害は小さい)/ O2 の行き先(機械の結果 + 人の層から組み立てる)に逆らわない(`plan/rs8-cases-ui.md`)

## 注意(引き継ぐこと)
- **友人の前提**: 配る友人は 1 人・RTX 3060。友人の PC では送るアプリ(C#)が ② を `--headless` の子プロセスとして起こす(常駐しない)。② の口は 1 つ(ユーザーの入口・友人のアプリ・CLI)。D-13 は友人の PC に持たせない・届ける段も持たない(`plan/f1-friend-pc.md`)
- **Windows のスマート アプリ コントロール**: この PC は 10-11 にオフ。友人もオフにする前提(F1)
- **一時の形はユーザーに聞かない**。聞くのは機能・データを消す・使い方が変わる・最終の形を決める物だけ
- 移した名前を別の部品に別名で残さない。serve の `_ED_MODULES` に新しい持ち主を足す。`modfwd.duplicates` 0 件
- **サブエージェントの実装と e2e を同時に流すと待ちのあるテストが揺れる**。最後の一式はサブエージェントが止まってから。e2e の間は src を書き換えない(e2e は始まるたびに src を写す)
- worktree のサブエージェント: 最初に `git merge --ff-only main`・取り込みは cherry-pick・終わった worktree は `git worktree remove` と `git branch -D`
- **unittest の一式はフォルダごとにまとめて**(ユーザー 10-11「テストの数が多いのでまとめて」): テストのフォルダごとに `py -3.10 -m unittest <モジュール…>` を 1 プロセス(そのフォルダに cd・標準入力を閉じる = analytics が止まらない)。単独が要るのは `test_resolve_pack_contract`・`test_mount`・cut2resolve の `test_serve`。unittest に `PYTHONIOENCODING=utf-8` を付けない。e2e は `PYTHONIOENCODING=utf-8 py -3.10 dev/run_e2e.py`
- ファイルは差分で直す(多くは CRLF。**`sed -i` 禁止**)。plan/data.js を直したら公開ページも出し直す
- 別のセッションが並行している(10-11): 「今日の作業と今後の計画」(OPT の見直しメモ・RS8 の条件も)(`plan/`・decisions・data.js の他の行・HANDOVER の「次」を触ることがある)・「並列実行可能なタスク」(片付け。`C:/dev/yt-cleanup` の worktree で `src/app/cli.py` の 2 段の道・`runqueue` の版 1・`machine` の `TRANSCRIBE_DEVICE`・`livehost` の Protocol をまとめる など)。`git add -A` を使わない・コミットの直前に `git diff --cached --stat`
- 入口が起動中の間はコードを変えても古いまま動く。**配信中に入口を落とさない**

## 次のセッションに貼る指示文
「AGENTS.md → plan/data.js → docs/HANDOVER.md → docs/WORKLOG.md の末尾 3 件 → git status・git log -15 を見て。役割で組み直す計画は RS7-2(玄関とヘッドレス)まで済み・使わないモデルの選択肢を消して版 0.58.0(決定 3-31 は確認済み)。RS8(plan/rs8-cases-ui.md)は ③④ の見直し・B-2 の 0〜3・OPT1 まで済み(HANDOVER の「次」の 0)。仮決め decisions 3-36 をユーザーに確認してから docMove をオンにして B2-4、そのあと B-3 → O2 → URL も CLI → 新しい画面。画面の材料は docs/design/briefs/rs8-cases/。RS7-2 から送った残り(自分の配信も束で・G1a・G3・serverkit・launch.py → app/server.py)も RS8 で。優先の順は decisions 3-33(RS8 → V1 → F1 → RV → 1.0.0)・本物の確認で止めない(3-32)。設計の判断は Fable と相談・一時の形でない物だけユーザーに確認。サブエージェントは仕事に合わせてモデルとエフォートを選ぶ(単純作業は Haiku・low)。段ごとは unittest・lint・層だけ(unittest はテストのフォルダごとにまとめて 1 プロセス)・e2e 一式と文書は RS の終わりに 1 回。別のセッション(片付け・計画)が並行しているので git add -A を使わない。」
