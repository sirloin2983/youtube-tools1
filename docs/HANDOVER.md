# HANDOVER — 次のセッションへの引き継ぎ(2026-10-07。フォルダ整理と見直しの作業中)

セッションを切り替えるたびに上書きする。全体の計画と進捗は `plan/index.html`(データ `plan/data.js`)、文書の索引は `docs/ROADMAP.md`、経緯は `docs/WORKLOG.md`、規則は `AGENTS.md`。

## いまの状態
- 作業フォルダは `C:\dev\youtube-tools`(GitHub: https://github.com/sirloin2983/youtube-tools1)。**push はユーザーが `push.bat`**(AI は push しない)
- **2026-10-07 にフォルダを整理した**: `src/`(home・studio・editor・cut2resolve・recorder・ytt_core・ui-kit)・`friend-apps/`(holo-colors・request-sender)・`plan/`(ユーザーが読む計画)・`docs/`(AI 向け)。start.bat は `src\home\launch.py` を呼ぶ。フォルダ名の正は `src/ytt_core/layout.py`(`src_root()` = ツールの親、`repo_root()` = リポジトリ直下)
- 同じ日に、ユーザーの指示で 4 つの作業を順に進めている(進み具合は `plan/data.js` の recent = `plan/index.html` の 1): ① 資料とフォルダの整理 → ② ユーザーの作業が要らない実装(A2・B1 0.57.1・A1・B2 の手元の分・線 D 1D)→ ③ コードの見直し(動きを変えない範囲。処理の方法は変えてよい)→ ④ 改善案を `plan/` に
- 版(2026-10-07): 入口 0.37.0・スタジオ 0.21.0・編集 0.57.0・cut2resolve 0.21.0・録画 0.3.0・ui-kit v17・送るアプリ 2.1.0・ホロカラー 1.4.1(正は各ファイル)

## 次のセッションに貼る指示文
「AGENTS.md → plan/data.js(計画と進捗の正本。表示は plan/index.html)→ docs/WORKLOG.md の末尾 3 件を読んで、git status と git log -5 を見てから、data.js の recent(直近の作業)で止まっている所から続けて。仮で決めたことは plan/decisions.md に並べて、終わりにまとめて確認して。」

## 注意(引き継ぐこと)
- 入口が起動中にフォルダを動かすと、録画の部品(`recorder.py`)のプロセスがフォルダを掴んで移動できない。入口の「すべて終了」では録画の部品が止まらないことがある(10-07)。ユーザーにタスク マネージャーで止めてもらう
- Claude Code のアプリ(Code タブ)から動かす AI は MSIX の中なので、`%LOCALAPPDATA%` への書き込みは写しに入る(`AGENTS.md` の動作環境)。作業データは入口の API を通すか、パッケージの外のプロセスで書く
- Claude Code のアプリがときどき落ちる(セッションが途中で切れる)。項目ごとにコミットする。再開は「続行」で止まった所から。WORKLOG の「未コミット」と `git status` を突き合わせる
- 2026-09-23 に、Claude が配った zip で GPT の変更が上書きされて消えた。**古い控えからのファイル丸ごとの上書き・zip 配布はしない**
- PC の不安定(i9-13900KF)は 10-04 に CPU を i9-12900KF に替えて解決したとみなす。異常終了は本物の失敗として調べる(入口の「調子」の「異常終了(7 日)」)
