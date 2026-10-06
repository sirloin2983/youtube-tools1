# HANDOVER — 次のセッションへの引き継ぎ(2026-10-07。フォルダ整理・②③④ の見直しが済んだあと)

セッションを切り替えるたびに上書きする。全体の計画と進捗は `plan/index.html`(データ `plan/data.js`)、文書の索引は `docs/ROADMAP.md`、経緯は `docs/WORKLOG.md`、規則は `AGENTS.md`。

## いまの状態
- 作業フォルダは `C:\dev\youtube-tools`(GitHub: https://github.com/sirloin2983/youtube-tools1)。**push はユーザーが `push.bat`**(AI は push しない)
- **2026-10-07 にフォルダを整理した**: `src/`(home・studio・editor・cut2resolve・recorder・ytt_core・ui-kit)・`friend-apps/`(holo-colors・request-sender)・`plan/`(ユーザーが読む計画)・`docs/`(AI 向け)。start.bat は `src\home\launch.py` を呼ぶ。フォルダ名の正は `src/ytt_core/layout.py`(`src_root()` = ツールの親、`repo_root()` = リポジトリ直下)
- 同じ日に、ユーザーの指示の 4 つの作業を終えた(`plan/data.js` の recent = `plan/index.html` の 1): ① 資料とフォルダの整理 / ② A2・録画の部品の終了・線 D M1〜M7(入口 0.40.0)・B1 0.57.1・A1 しきい値 0.6(編集 0.58.0)・B2 手元の 4 エンジンの比較 / ③ 全フォルダの見直し(動きは同じ。各ツールの版を 1 つ上げた)/ ④ `plan/improvements.md`(次に手を付けるなら)・`decisions.md`(仮決め (a)〜(r))。**残り**: L0(配信中に)・クラウドの比較(送り先待ち)・M7 の本物の確認(ユーザー)・`decisions.md` の 3 の確認
- 版(2026-10-07 の終わり): 入口 0.40.1・スタジオ 0.21.1・編集 0.58.1・cut2resolve 0.21.1・録画 0.3.1・ui-kit v18・送るアプリ 2.1.1・ホロカラー 1.4.2(正は各ファイル)。ユーザーは入口を起動し直す必要がある

## 次のセッションに貼る指示文
「AGENTS.md → plan/data.js(計画と進捗の正本。表示は plan/index.html)→ docs/WORKLOG.md の末尾 3 件を読んで、git status と git log -5 を見てから、plan/improvements.md の 0(次に手を付けるなら)と data.js の tasks の state が next のものから続けて。仮で決めたことは plan/decisions.md の 3 に足して、終わりにまとめて確認して。plan/data.js を直したら dev/plan_artifact.py で公開ページも更新して。」

## 注意(引き継ぐこと)
- 入口が起動中にフォルダを動かすと、録画の部品(`recorder.py`)のプロセスがフォルダを掴んで移動できない。入口の「すべて終了」では録画の部品が止まらないことがある(10-07)。ユーザーにタスク マネージャーで止めてもらう
- Claude Code のアプリ(Code タブ)から動かす AI は MSIX の中なので、`%LOCALAPPDATA%` への書き込みは写しに入る(`AGENTS.md` の動作環境)。作業データは入口の API を通すか、パッケージの外のプロセスで書く
- Claude Code のアプリがときどき落ちる(セッションが途中で切れる)。項目ごとにコミットする。再開は「続行」で止まった所から。WORKLOG の「未コミット」と `git status` を突き合わせる
- 2026-09-23 に、Claude が配った zip で GPT の変更が上書きされて消えた。**古い控えからのファイル丸ごとの上書き・zip 配布はしない**
- PC の不安定(i9-13900KF)は 10-04 に CPU を i9-12900KF に替えて解決したとみなす。異常終了は本物の失敗として調べる(入口の「調子」の「異常終了(7 日)」)
