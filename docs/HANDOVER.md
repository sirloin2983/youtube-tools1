# HANDOVER — 次のセッションへの引き継ぎ(2026-10-12 朝。版 0.61.0。RS8・V1・F1 の AI の分は済み。**友人の PC で試して問題が出た → 送るアプリの要件を見直し中(暫定・覆りうる)。実装はユーザーの次の見直しのあと**)

セッションを切り替えるたびに上書きする。全体の計画と進捗は `plan/index.html`(データ `plan/data.js`)、文書の索引は `docs/ROADMAP.md`、経緯は `docs/WORKLOG.md`

## いまの状態
- 作業フォルダは `C:\dev\youtube-tools`(GitHub: https://github.com/sirloin2983/youtube-tools1)。**push はユーザーが `push.bat`**
- **版**: 全体で 1 つ = `src/ytt/version.py` の **0.61.0**(仮。1.0.0 は RV のあと = decisions 3-33)。RS8(案件の画面 /cases・0.59.0)・V1(確かめる /check・0.60.0)・F1(友人の PC で ② + ①・0.61.0)の AI の分は済み
- **層は 5 つ**: ① 道具 `src/pipeline/`・② 管理 `src/flow/`・③ 人 `src/human/`・④ データ `src/manage/`・⑤ 検証 `src/eval/`・app は全部を読める。向きは `dev/layer_map.py` の `ALLOWED` と `dev/tests/test_layering.py`(違反 0)
- **友人の PC で試した結果(10-11 夜)**: 起動で落ちた(終了コード 1)= アプリが E:・作業データが C: で `os.path.relpath` が ValueError → 73bc2c21 で直した(友人に届けるのは次の zip)。送るアプリは ② が起動で終わったとき標準エラーの最後の行を文に添える(d69ef85d)。ほかに友人の指摘: 何本か選んで消せない・開いたら一覧から消える・文字と動きが合わない・フォルダの管理に疑問
- **送るアプリの要件の見直し(10-11 深夜〜10-12)**: ユーザーと 1 問ずつ決めた結果が `plan/f1-friend-requirements.md`。**状態は暫定**(ユーザー「このあと更なる見直しをするので、ここで決めたことも根本的に覆る可能性がある」)= この文書を前提に実装も段取りも始めない。主な決定: 一覧は未決の箱・受け取る = 保存先へ移す・[動画にした] はやめる・物には必ず終わり(日数は既存の 3 日)・動画 / URL / ライブを区別しない・一時保管だけ場所を選べる・アプリは版ごとのフォルダ・採否の道は 送り返し に 1 本化
- **見つけたが直していない不具合**: 設定の「案件の保存先」(machine の caseRoot)は空き容量を測る所が変わるだけで出来上がる場所は変わらない / アプリの更新(`robocopy /E`)が新しい版で消したファイルを消さない / 画面なしの ② はまとめ動画を作らない

## 次
0. **10-12 朝(このセッション)**: 送るアプリの要件の見直し 1 回目は済み(暫定)。**次はユーザーの「更なる見直し」を待つ**(基本の仕様から 1 問ずつ・AI の案を 1 つ添えて)。決まったら直す順の段取り → 実装 → 初回の zip を作り直して友人へ
0. **10-11 夜(F1)**: F1 の AI の分は済み = 版 0.61.0(`docs/design/f1-build.md`・WORKLOG の末尾)。残りは友人の PC での確かめ(`py -3.10 dev/build_friend_zip.py --first --with-key` で初回の zip → 友人へ・本物の Dropbox で学習・送り返し・更新を 1 回)。そのあと RV
0. **10-11 夜**: V1 確かめる(/check)も済み = 版 0.60.0。次は F1 → RV
0. **10-11 夕(WORKLOG の末尾)**: RS8 の新しい画面ができた = 案件の画面 `/cases`(`src/app/ui/cases/`。殻 cases.js + パネル cand・proof・cut・new・machpick・台 edhost.js)とホームの組み替え。古い画面のページは消した(部品の JS は `src/studio`・`src/editor` に残して案件の画面が相対パスで読む)。版 0.59.0。e2e は 18 本。文書の層は shadow のまま(primary はユーザーの合図で)。次は V1 → F1 → RV
- 以下は 10-11 昼の記録。**10-11 昼の続き**: O2-3〜5 = `TRANSCRIBE_LAYERS=primary` で層が正(**既定は shadow のまま = ユーザーに直接聞いた答え。新しい画面の 3 択ができてから primary に**)・3 択の口 `/api/mach-changes`(`human/proof/machpick.py`)・再認識と話者は primary のときだけ新しい動き。URL も入口なしで CLI から最後まで(`flow/studiobook.py`。終了コード 3 は欠番)。入口の本体は `src/app/server.py`(旧パス `src/home/launch.py` は runpy の転送)。② の口 = 掲示板 `flow/board.py`・`GET /api/flow/status` の jobs・cases・rev・`POST /api/flow/cancel`・`retry`・`GET /api/flow/history`(仕様 `docs/spec/pipeline.md` 2.9・設計 `docs/design/rs8-flow-api.md`)。器 10 通りは包んで載せた(器を本当に 1 つにする OPT2 の後半は新しい画面の直後)。**次は新しい画面**(`docs/design/briefs/rs8-cases/`。進み具合は掲示板を 2 秒 / 15 秒で問い合わせ・案件の中身と人の操作は ③④ の今の口)→ primary へ → V1
- 以下は 10-11 午前までの記録。**RS8 の今(10-11。WORKLOG の末尾 2 件)**: B-2(文書を案件の 作業用 へ。`ytt/docloc`・`manage/cases/docmove.py`)・B-3(スタジオの候補と採用を案件の `作業用/候補.json`・`採用.json` へ。`flow/casebook`・`ytt/casefiles`・`ytt/studiodata`・初めて書き出した配信から案件が正・依頼は `<outDir>\依頼\<日付>_<題>_<id6>\`・既存の移行 `manage/cases/markmove.py`)・O2-0〜2(文書を書く口 `store.commit`・組み立て `human/proof/layers.py`・**影のモード既定オン** = 保存のたびに `.hum.json`・`.mach.json` を書いて比べてログ)・OPT1・OPT2 の大半が main に入った。**既存のデータの自動の移行は 2 つともスイッチで止めてある**(`machine.json` の `docMove`・`markMove` 既定オフ)= ユーザーが `plan/decisions.md` 3-36・3-37 を見てからオン → 入口を起動し直すと移る(1 回の起動で 50 本まで)→ 画面で本数を確かめ → `docmove.py --purge-migrated`。次: O2-3(切り替え。影のログで食い違い 0 を数日見てから)→ O2-4(3 択の口)→ O2-5 → URL も CLI で → serverkit・`launch.py` → `app/server.py` → ② の口の形 → 新しい画面。案件が見えないときの画面の表示(caseUnseen)は新しい画面で
1. **RS8**(`plan/rs8-cases-ui.md`。**始めるときの条件 = 同じ文書の「RS8 を始めるときの条件」**(10-11 ユーザー了承): ③④ の見直し(読むだけ)∥ B-2 の下調べ ∥ OPT1 の実装(`plan/opt-pipeline-flow.md`。別の worktree。F1 より前に必ず)→ B-2 → B-3 → O2 → URL も CLI で →(② の口の形を決める)→ 新しい画面。新しい画面の進み具合は ② の status から読む)。設計の材料は `docs/design/briefs/rs8-cases/`(DESIGN_BRIEF・見本)。RS8 で一緒にやる RS7-2 の残り(自分の配信も束で・G1a は 10-11 に済み): G3 配信後の作り直しを run に寄せる・serverkit・`launch.py` → `app/server.py` の mv・headless の配信後の全自動が LocalMarks の採用の印を見ない(重なりうる)
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
「AGENTS.md → plan/data.js → docs/HANDOVER.md → docs/WORKLOG.md の末尾 3 件 → git status・git log -15 を見て。版 0.61.0。RS8・V1・F1 の AI の分は済み。F1 は友人の PC で試して問題が出て、送るアプリの要件を plan/f1-friend-requirements.md で見直し中(暫定・覆りうる)。ユーザーがさらに見直すので、その文書を前提に実装を始めない。見直しは基本の仕様から 1 問ずつ、AI の案を 1 つ添えて聞く。日数は既存の 3 日(cleanup.py)に合わせる。質問されたら検証より先に答える。優先の順は decisions 3-33(F1 → RV → 1.0.0)。別のセッションが並行しうるので git add -A を使わない。」
