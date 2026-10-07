# HANDOVER — 次のセッションへの引き継ぎ(2026-10-07 夜。段 7〜9・測り直しまで済み)

セッションを切り替えるたびに上書きする。全体の計画と進捗は `plan/index.html`(データ `plan/data.js`)、文書の索引は `docs/ROADMAP.md`、経緯は `docs/WORKLOG.md`、規則は `AGENTS.md`。

## いまの状態
- 作業フォルダは `C:\dev\youtube-tools`(GitHub: https://github.com/sirloin2983/youtube-tools1)。**push はユーザーが `push.bat`**(AI は push しない)
- **2026-10-07 にフォルダを整理した**: `src/`(home・studio・editor・cut2resolve・recorder・ytt_core・ui-kit)・`friend-apps/`(holo-colors・request-sender)・`plan/`(ユーザーが読む計画)・`docs/`(AI 向け)。start.bat は `src\home\launch.py` を呼ぶ。フォルダ名の正は `src/ytt_core/layout.py`(`src_root()` = ツールの親、`repo_root()` = リポジトリ直下)
- 同じ日に済んだこと(`plan/data.js` の recent ①〜⑤): ① 資料とフォルダの整理 / ② 線 D M1〜M7・B1 0.57.1・A1・B2(手元)/ ③ コードの見直し 2 周目まで(基準 `docs/spec/code-quality.md`・`dev/lint.py` 0 件)/ ④ plan の文書 / ⑤ 「気が利く画面へ」段 7〜9(`plan/ux-stage7-9.md`。段 9 = `docs/design/briefs/ux-consistency/DESIGN_REVIEW.md`)。夜に行の時刻の測り直し(`plan/line-b-row-timing.md` の 6)。仮決め (a)〜(al) はユーザー承認済み、(am)〜(aq) は未確認(`plan/decisions.md` の 3-4・3-5)
- **ユーザーの判断待ち**: 1 秒丸めの配り直し(`quant_retime`)を既定でやめるか(AI の案はやめる。`TRANSCRIBE_RETIME=0` と同じ動き。決まったら `src/editor/ed_jobs.py` の既定を変え、README と `plan/line-b-row-timing.md` の状態の行を直す)/ クラウドのエンジン比較の送り先 / M7 の本物の配信での確認(土日)/ L0(今夜の配信で「今やって」)
- 版(コミット済み): 入口 0.42.2・スタジオ 0.22.3・編集 0.59.3・cut2resolve 0.22.2・録画 0.3.2・ui-kit v23・送るアプリ 2.2.0・ホロカラー 1.4.3(正は各ファイル。`plan/data.js` の版の表も同じ)。テスト一式(単体・node・e2e 29 本・lint)は 10-07 夜に全部 OK。ユーザーは今夜の配信の前に「すべて終了」→ start.bat で起動し直す

## 次のセッションに貼る指示文
「AGENTS.md → plan/data.js(計画と進捗の正本。表示は plan/index.html)→ docs/WORKLOG.md の末尾 3 件を読んで、git status と git log -5 を見てから、plan/improvements.md の 0(次に手を付けるなら)と data.js の tasks の state が next のものから続けて。配り直し(quant_retime)の既定はユーザーの答えが出ていれば先に反映して。仮で決めたことは plan/decisions.md の 3-6 以降に足して、終わりにまとめて確認して。plan/data.js を直したら dev/plan_artifact.py で公開ページも更新して。」

## 注意(引き継ぐこと)
- 入口が起動中にフォルダを動かすと、録画の部品(`recorder.py`)のプロセスがフォルダを掴んで移動できない。入口の「すべて終了」では録画の部品が止まらないことがある(10-07)。ユーザーにタスク マネージャーで止めてもらう
- Claude Code のアプリ(Code タブ)から動かす AI は MSIX の中なので、`%LOCALAPPDATA%` への書き込みは写しに入る(`AGENTS.md` の動作環境)。作業データは入口の API を通すか、パッケージの外のプロセスで書く
- Claude Code のアプリがときどき落ちる(セッションが途中で切れる)。項目ごとにコミットする。再開は「続行」で止まった所から。WORKLOG の「未コミット」と `git status` を突き合わせる
- 2026-09-23 に、Claude が配った zip で GPT の変更が上書きされて消えた。**古い控えからのファイル丸ごとの上書き・zip 配布はしない**
- PC の不安定(i9-13900KF)は 10-04 に CPU を i9-12900KF に替えて解決したとみなす。異常終了は本物の失敗として調べる(入口の「調子」の「異常終了(7 日)」)
