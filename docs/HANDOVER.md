# HANDOVER — 次のセッションへの引き継ぎ(2026-10-07 深夜。UI の見直し(基準 → 合格までループ)が済んだところ)

セッションを切り替えるたびに上書きする。全体の計画と進捗は `plan/index.html`(データ `plan/data.js`)、文書の索引は `docs/ROADMAP.md`、経緯は `docs/WORKLOG.md`、規則は `AGENTS.md`。

## いまの状態
- 作業フォルダは `C:\dev\youtube-tools`(GitHub: https://github.com/sirloin2983/youtube-tools1)。**push はユーザーが `push.bat`**
- **2026-10-07 の UI の見直しは、クラウドの Claude Code がブランチ `claude/ui-review-2026-10-07` に積んで push 済み**(クラウドの決まりで push した。main はその間に進んでいないので、PC では `git fetch origin claude/ui-review-2026-10-07` → `git merge origin/claude/ui-review-2026-10-07` で早送りで取り込める。取り込んだら「すべて終了」→ start.bat で起動し直す)
- 済んだこと(記録は `docs/WORKLOG.md` の末尾と `docs/design/briefs/ux-consistency/DESIGN_REVIEW.md`): 基準 `docs/spec/ui-review-criteria.md`(A = 機械で測る 31 項目・B = 人が見る 21 項目・合格の定義)・測る道具 `dev/ui_audit.py`(`py -3.10 dev/ui_audit.py all --demo` で見本サーバーごと測る。**画面を変えたら Must 0 件**)・3 周の直し(ui-kit v23・入口 0.42.3・スタジオ 0.22.3・編集 0.59.3)。A の Must 704 → 0、見直し役の Must 28 → 0 で合格
- **ユーザーに確認してほしいこと**: `plan/decisions.md` の 3-4 の仮決め (am)〜(ba)(合格の定義・コントラストの範囲・文字記号を全部 SVG・行の札を 2 択に・2 カット の X → H・ホームの ⚙ の節 など)。合格は Linux(クラウド)の chromium で判定したので、Windows でも e2e(`dev/run_editor_suite.py` と home・studio の e2e)を流し直すと確実
- 残り(直さなかった Should・Could)は `plan/improvements.md` の 11。段 9 以前の残りは同じ文書の 10 と `plan/ux-stage7-9.md`
- 版(コミット済みの最新): 入口 0.42.3・スタジオ 0.22.3・編集 0.59.3・cut2resolve 0.22.2・録画 0.3.2・ui-kit v23・送るアプリ 2.2.0・ホロカラー 1.4.3(正は各ファイル。`plan/data.js` の版の表も同じ)
- Linux で前から落ちるテスト(Windows では通る): home の `test_live` 2 件(`E:\` のパス前提)と `test_cleanup.test_move_only_known_and_purge`(一覧の順が OS で違う)、editor の `test_roster` 2 件 + 1 件(Windows のパス前提)。e2e は Linux でも全部 OK

## 次のセッションに貼る指示文
「AGENTS.md → docs/WORKLOG.md の末尾 1 件(UI の見直しの記録)→ git status を見て。plan/decisions.md の 3-4 の (am)〜(ba) をユーザーと確認し、変えるものがあれば直して、画面を変えたら py -3.10 dev/ui_audit.py all --demo で Must 0 件と、その画面の e2e を確かめて。」

## 注意(引き継ぐこと)
- 入口が起動中にフォルダを動かすと、録画の部品(`recorder.py`)のプロセスがフォルダを掴んで移動できない。入口の「すべて終了」では録画の部品が止まらないことがある(10-07)。ユーザーにタスク マネージャーで止めてもらう
- Claude Code のアプリ(Code タブ)から動かす AI は MSIX の中なので、`%LOCALAPPDATA%` への書き込みは写しに入る(`AGENTS.md` の動作環境)。作業データは入口の API を通すか、パッケージの外のプロセスで書く
- クラウドの Claude Code(claude.ai/code)は PC のフォルダを見ない。GitHub のブランチに push するので、PC 側で取り込む(上の手順)。`python` は `python3`・node は Playwright 同梱ではなく `/opt/node22/bin/node`・Segoe UI と Cascadia が無い(写真の字が少し違う)・YouTube の埋め込みは読めない
- Claude Code のアプリがときどき落ちる(セッションが途中で切れる)。項目ごとにコミットする。再開は「続行」で止まった所から。WORKLOG の「未コミット」と `git status` を突き合わせる
- 2026-09-23 に、Claude が配った zip で GPT の変更が上書きされて消えた。**古い控えからのファイル丸ごとの上書き・zip 配布はしない**
- PC の不安定(i9-13900KF)は 10-04 に CPU を i9-12900KF に替えて解決したとみなす。異常終了は本物の失敗として調べる(入口の「調子」の「異常終了(7 日)」)
