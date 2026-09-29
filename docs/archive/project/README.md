# docs/project/ — 経緯の資料(古い。今の動きの根拠にしない)

2026-09-20〜24 に claude.ai の Project「動画編集ツール開発」に置いていた仕様書・引き継ぎ資料を、Claude Code・GPT(Codex)から読めるように写したものです。
**資料の正本はこのリポジトリ**(2026-09-26 ユーザー決定)。claude.ai の Project の `claude/*.md` は 2026-09-26 に片付けた(Project にしか無かった3本はここへ写し、残りは削除。
Project に残したのは、リポジトリの場所と今の状態を書いた `claude/README.md` と、統合計画の要約 `claude/integration-plan.md` だけ)。

ここの資料は**書いた時点のまま**で、多くは数版前の内容です(例: clip-studio-spec.md は v0.1.7、cut2resolve-spec.md は v0.1.3、transcribe-tool-spec.md は v0.7.0 当時)。
今の動き・仕様は、各ツールの `README.txt`(ユーザー向け)と `AGENTS.md`(AI 向け)、コード、`docs/pipeline.md`・`docs/integration-plan.md` を見てください。
ここは「なぜそう決めたか」「何を試して捨てたか」を調べるときに読みます。

| ファイル | 中身 | 書いた時点 |
| --- | --- | --- |
| HANDOVER.md | 切り抜きスタジオの引き継ぎ(決定事項・捨てた選択肢・ハマりどころ) | スタジオ v0.1.5 |
| HANDOVER-transcribe-tool.md | 文字起こしツールの引き継ぎ | 文字起こし v0.9.8 |
| clip-studio-spec.md / collab-mark-spec.md | スタジオの仕様・コラボのマーク転写の設計 | スタジオ v0.1.7 |
| cut2resolve-spec.md / srt2resolve-spec.md / auto-cut-design.md / resolve-textplus-test.md | Resolve への受け渡し(EDL・Text+)の経緯 | cut2resolve v0.1.3 ほか |
| transcribe-tool-spec.md / history/transcribe-tool-v*.md | 文字起こしの最初の仕様と、版ごとの記録(v0.7.1〜v0.9.4) | v0.7.0〜v0.9.4 |
| accuracy-plan.md / eval-set-procedure.md | 文字起こしの精度向上の計画・評価用データの運用 | 2026-09-24 |
| improvement-roadmap.md / output-dir-setting.md | 改善提案の実施状況・出力先の設定 | 2026-09-20 |
| auto-clip-spec.md / stream-rank-spec.md / clip-marker-v1.0.0.md | スタジオに統合する前の旧ツール(0old/) | 旧ツール |
| summary-2026-09-24.md / summary-2026-09-25.md | その日の作業の要点(全ツールの見直し / cut2resolve の Text+) | 2026-09-24・25 |
| new-tool-plan.md | 新ツールの作成予定(新着配信の監視・ラウドネス・一括実行)と不採用にした案 | 2026-09-24 |

新しい設計・決定は、ここではなく `docs/` の直下(例: `docs/integration-plan.md`)に書き、`docs/WORKLOG.md` からリンクします。
