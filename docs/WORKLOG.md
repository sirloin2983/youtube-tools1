# 作業記録(Claude・GPT 共通)

このリポジトリを編集した AI は、作業の終わりに**末尾へ**1件追記する。作業を始める AI は、最後の数件を読んでから始める(ルールは `AGENTS.md`)。

書式:
```
## YYYY-MM-DD 担当(Claude(Cowork) / Claude Code / GPT(Codex))— 見出し
- 変更: 何を変えたか(ファイル名)
- 版: 変更前 → 変更後(版を上げたとき)
- 決定・理由: ユーザーと決めたこと・判断の理由
- 未完了・次: 残っていること
- 注意: 次の AI が踏みそうな落とし穴
```

---

## 2026-09-21〜23 Claude(Cowork)— 文字起こしツール v0.9.5〜v0.9.8(過去分のまとめ)
- 変更: transcribe-tool の index.html・serve.py・README.txt・e2e テスト。詳細は `docs/project/HANDOVER-transcribe-tool.md`
  - v0.9.5 句読点の除去・話者判別の優先割り込み / v0.9.6 編集画面の2列化・キーボードの「今の行」のずれ修正 /
    v0.9.7 映像を左に・行の ▶ はその行だけ再生・キー操作を Shift 不要に / v0.9.8 左メニューの開閉(☰ / G)・行の追加・UI の整理
- 注意: Claude はクラウドから作業しており、GitHub への push はできない(403)。v0.9.8 までは zip で配っていた

## 2026-09-23 GPT(Codex)— v2 設計書・保存の安全性・Resolve 書き出し(Claude が記録を代筆)
- 変更(Claude が git の記録から確認した内容): v0.9.7 の上に GPT 独自の「v0.9.8」として
  - 設計書 `transcribe-tool/TRANSCRIPTION_V2_DESIGN.md`(精度改善 v2。whisper.cpp Vulkan、信頼度ルーター、評価セットの固定など。**実装は保留・着手前にユーザー確認**)
  - `transcribe-tool/resolve_export.py` と `test_resolve_export.py`(DaVinci Resolve 用パッケージ: 映像・カット計画・FCPXML・SRT・Resolve 21.1 用の取り込みスクリプト。行の `cutState: "cut"` を使う)
  - `transcribe-tool/test_document_save.cjs`(保存中の切り替え・競合・読み込み中の編集で内容を失わないことの確認)
  - index.html: 左パネルのタブ化(新規・履歴・精度・学習)・「管理」ボタン・一覧の検索、保存の安全性の強化、行ごとの「残す/カット済」、Resolve 書き出しの画面、候補の検索
  - serve.py: cutState の保存、/api/resolve-package、スタジオの書き出し先の既定を exports に
  - clip-studio の複数のファイル(analyze.py・common.py・exporter.py・review.js・store.py など)と、そのテスト(e2e_review.py・test_file_recovery.py・test_review.cjs)
- 注意: 上の変更はコミットされていなかった

## 2026-09-24 Claude(Cowork)— 上書き事故の発見と復元・AI 間の共有ルールの導入
- 事故: ユーザーが Claude の v0.9.8 の zip を展開したとき、GPT が直していた transcribe-tool の index.html・serve.py・README.txt が上書きされて消えた
  (GPT の変更は未コミットだった)。clip-studio と resolve_export.py などの新しいファイルは無事
- 復元: Codex が .git に残したチェックポイントから GPT 版を取り出し、`_recovered/2026-09-23-gpt/transcribe-tool/` に置いた
  (index.html・serve.py・README.txt。GPT のテスト test_document_save.cjs が 9件すべて通ることを確認)。.gitignore で管理外
- 変更: `AGENTS.md`(共通ルール。旧 CLAUDE.md の内容を移した)、`CLAUDE.md`(AGENTS.md を読み込むだけ)、`transcribe-tool/AGENTS.md` / `CLAUDE.md` も同様、
  この `docs/WORKLOG.md`、`.gitignore`(_recovered/・git-patches/・Claude outputs/ を除外)、`push.bat`(ダブルクリックで GitHub に保存)、
  `docs/project/accuracy-plan.md`(精度向上計画。GPT の v2 設計書と同じ方針。どちらも実装は保留)
- 未完了・次: **Claude 版 v0.9.8 と GPT 版の統合**(ユーザーの確認待ち)。ぶつかるのは主に左パネル(Claude: ☰ で開閉 / GPT: タブ化)と行の操作ボタン
  (Claude: 選んだ行の下に出す / GPT: 「残す/カット済」と「…」メニュー)。保存の安全性・Resolve 書き出し・serve.py の変更は、ぶつからずに取り込める見込み
- 注意: 統合までは test_document_save.cjs が 8件失敗する。版は統合後に 0.9.9 にする(0.9.8 は2つの版で重複しているため)

## 2026-09-24 Claude(Cowork)— 続きの作業を Claude Code に引き継ぎ
- 決定: ユーザーが統合の方針を了承(「続行」)。あわせて「精度改善に必要なデータを集める」「ユーザーに入力してほしい項目を追加する」の指示。
  Cowork 側のトークンが尽きたため、続きは Claude Code で行う(ユーザーの指示)
- 変更: `docs/NEXT_TASKS.md`(3つのタスクの詳しい手順)、`run-next.bat`(ダブルクリックで Claude Code が開き、NEXT_TASKS.md の続きから始まる)
- 未完了・次: NEXT_TASKS.md の 1〜3(統合 → 基準データ → 入力項目)。どれも未着手

## 2026-09-24 Claude(Cowork)— 朝4時の自動再開の仕組み
- 変更: `schedule-next.bat`(ダブルクリックで、次の朝4時に1回だけ実行する予約をタスクスケジューラに登録。スリープ中なら起こす)、
  `auto-next.bat`(実行前の状態を控えとしてコミット → `claude -p` で NEXT_TASKS.md の続きを無人実行。結果は auto-next.log)
- 注意: 無人なので編集は確認なしで許可(acceptEdits)、コマンドは python・node・git の add/commit/status/diff/log だけに限定。push はしない。
  判断が必要な所では止まって WORKLOG と NEXT_TASKS.md に書く指示。使用量の上限が戻っていないと失敗する(auto-next.log で確認)

## 2026-09-24 GPT(Codex)— クラウド作業への移行準備
- 変更: `.gitignore` に `.whisper_models/` を追加し、ローカルの Whisper モデルを GitHub / クラウドへ送らないようにした。
- 決定・理由: 未コミットの Claude / GPT の統合作業は保護コミットしてから GitHub に送る。音声・文字起こし・モデルなどの個人データや実行データは送らない。
- 未完了・次: GitHub へ反映後、Codex Cloud 側でこのリポジトリを指定して統合タスクを開始する。
- 注意: Cloud 環境ではローカルの動画・音声・`transcripts/` を利用できない。実データを必要とする精度測定は PC 側で行う。
