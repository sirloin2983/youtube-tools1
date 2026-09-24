# youtube-tools1 — YouTube ショート動画の編集支援ツール群

このリポジトリで作業する AI(Claude・GPT/Codex のどちらも)の共通の前提です。Codex はこのファイルを、Claude Code は CLAUDE.md 経由で読みます。
**最初に下の「複数の AI で作業するときのルール」と `docs/WORKLOG.md` の最後の数件を読んでください。**
詳しい経緯・仕様は `docs/project/` にあります(Project の資料の写し。コードと各ツールの README.txt の方が新しければ、そちらが正)。

## ツール(フォルダ)
- `clip-studio/` … 切り抜きスタジオ(配信から切り抜く区間を選ぶ・マーク・書き出し)。仕様: `docs/project/clip-studio-spec.md`
- `transcribe-tool/` … 文字起こしツール(faster-whisper・話者判別・校正画面・精度測定)。**いま一番活発に開発中**。`transcribe-tool/AGENTS.md` を必ず読む
- `cut2resolve/` … DaVinci Resolve 連携(カット・字幕の受け渡し。v0.2.0 から専用の画面 serve.py あり)。仕様: `docs/project/cut2resolve-spec.md`, `srt2resolve-spec.md`
- 全体の引き継ぎ: `docs/project/HANDOVER.md`、今後の改善案: `docs/project/improvement-roadmap.md`
- 共通の見た目: `ui-kit/`(正本。`python tools/sync_ui_kit.py` で各ツールへ写す。写しは手で直さない)。ツール間の受け渡し: `docs/pipeline.md`
- 2026-09-24 の全ツール見直しのまとめ: `docs/review/README.md`。3ツールの通し確認: `python tools/e2e_pipeline.py`
- `app/` … 入口(ランチャー)。リポジトリ直下の `start-all.bat` で3ツールをまとめて起動・終了し、入口の画面(http://localhost:8700/)を出す。`app/README.txt`
- `ytt_core/` … スタジオ・文字起こし・入口の共通部品(書き込み・`.runtime`・受け渡しの形式・安全検査)。変えたら `python -m unittest ytt_core/test_ytt_core.py` と各ツールのテスト
- 1つのアプリへの統合計画: `docs/integration-plan.md`(段階1 = 入口、段階2 = ytt_core は実装済み。**当面 cut2resolve は統合しない**)

どのツールも「Python 標準ライブラリ中心のローカルサーバー(serve.py)+ 1ファイルの画面(index.html)」構成で、ユーザーの PC 上だけで動く。
外部サービスへ動画・音声を送らない方針。

## ユーザーについて(応答の仕方)
- **応答は日本語**で。Web/バックエンド開発のエンジニア。動画編集は初心者。基礎的な文法・ライブラリの説明は不要、**実装判断の理由**が知りたい
- コードを示すときは、なぜその実装にしたかを1〜2文添える。複数案があれば、保守性・性能などのトレードオフを簡潔に比較する
- セキュリティ・エッジケースのリスクは省略せず指摘する
- 動画編集の専門用語は、初めて使うときに軽く説明する(一度説明した語は以後そのまま使ってよい)
- 長い作業で文脈が圧縮されそうなときは、HANDOVER(引き継ぎ)資料と「次のセッションにそのまま貼れる再開用の指示文」を作る

## 動作環境(ユーザーの PC)
- Windows。このリポジトリは PC 上の `Desktop\youtube-test` にある
- CPU は Intel Core i9-13900KF、メモリ 32GB。GPU は **AMD Radeon RX 7800 XT**(16GB)(NVIDIA ではないので CUDA は使えない → faster-whisper は CPU で動く。GPU 前提の提案をしない)
- Python 3・ffmpeg はインストール済み(各ツールの install.bat / start.bat を使う)

## 開発のルール
- 実行時データ・個人データ・秘密情報はコミットしない(`.gitignore` 参照: transcripts/ dataset/ models/ exports/ clips/ config.json など)。リポジトリは Public にする方針なので特に注意
- 各ツールで版を上げるときは、**serve.py の SERVER_VERSION・index.html の APP_VERSION・README.txt の見出し**を必ず同時に上げる(食い違うと画面に赤い帯が出る)
- テストは各ツールのフォルダで実行(文字起こしツールは `transcribe-tool/AGENTS.md` 参照)。画面のテストは Playwright(chromium)+ ffmpeg が必要
- 各ツールの起動の約束(`serve.py [ポート] --no-open`・`.runtime/<ID>.json`・`/api/ping`・SIGTERM/SIGBREAK で後始末して終わる)は入口が使っている。
  変えるときは `app/launch.py` と `python -m unittest app/test_launch.py` も確認する(`docs/integration-plan.md` の「段階1の約束」)
- コミットメッセージは日本語で、何をなぜ変えたかを書く(既存の履歴に合わせる)

## 複数の AI で作業するときのルール(Claude・GPT/Codex 共通)
このリポジトリは Claude(Cowork / Claude Code)と GPT(Codex)の両方が編集する。**正は PC の作業フォルダ(C:\Users\you11\Desktop\youtube-test)とその git**。
ユーザーは git の手作業を面倒に感じているので、情報の共有は AI 側でこのルールに沿って自動で行う。

作業を始める前:
1. `docs/WORKLOG.md` の最後の数件を読む(誰が・いつ・何を変えたか、未完了、注意)
2. `git status` と `git log -5 --oneline` を見る。**自分が変えていない未コミットの変更は、他の AI の作業途中**。上書き・破棄しない。
   触る必要があるなら、先に「WIP: 他のAIの作業途中」としてコミットしてから始めるか、ユーザーに確認する
3. 版番号(各ツールの SERVER_VERSION / APP_VERSION)を実際のファイルと WORKLOG で確認する(別々の AI が同じ番号を付けないため)

作業中:
- ファイルは差分で直す。**古い控えからのファイル丸ごとの上書き・zip での上書き配布はしない**
  (2026-09-23、Claude が配った zip で GPT の変更が上書きされて消えた事故があった。`docs/WORKLOG.md` 参照)
- 設計の変更・依存の追加・費用がかかること・既存機能の削除は、実装の前にユーザーに確認する

作業を終えるとき:
1. `docs/WORKLOG.md` の**末尾**に記録を追記する(書式は WORKLOG の先頭)
2. 変更したファイルと WORKLOG をコミットする(`git add <変えたファイル> docs/WORKLOG.md` → `git commit -m "[Claude] 要約"` / `"[GPT] 要約"`)。
   push はユーザーが push.bat で行う(AI は push しなくてよい)
3. 長く使う設計・決定は `docs/` に文書で残し、WORKLOG からリンクする
- Claude(Cowork。クラウドから PC のフォルダに書き込む)は PC で git を実行できない。WORKLOG への追記までを行い、コミットは次に git を使う AI か push.bat に任せる
