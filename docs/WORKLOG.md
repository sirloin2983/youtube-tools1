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

## 2026-09-24 GPT(Codex)— 無人実行の安全性と古い引き継ぎ記述を修正
- 変更: `auto-next.bat` から `git add -A` / 自動コミットを除去し、開始時に未コミット変更があれば中止するようにした。無人実行 Claude にも変更をコミットせず残すよう指示し、git add/commit の許可を外した。
- 変更: `schedule-next.bat` に予約時の dirty worktree チェックを追加。未コミット作業がある場合はタスクを登録しない。
- 変更: `transcribe-tool/AGENTS.md` と `docs/project/HANDOVER-transcribe-tool.md` の「統合は確認待ち」「GitHub clone/pull・zipで作業」という古い案内を、ユーザー了承済み・PCフォルダ正本・`docs/NEXT_TASKS.md` 参照に更新。
- 理由: 複数AIが共有する作業フォルダを無人実行が一括ステージ・コミットしたり、古い引き継ぎ指示で別コピーを正本と誤認したりするリスクを防ぐ。
- 確認: タスクスケジューラに `youtube-tools-auto-next` は登録されていない。コード差分の目視確認のみで、テストは未実行。

## 2026-09-24 GPT(Codex)— cut2resolve の出力上書き事故を防止
- 変更: cut2resolve フル版・シンプル版と srt2resolve は、既存の出力ファイルがある場合に既定で停止し、`--force` 指定時のみ上書きするようにした。入力ファイルとの衝突は `--force` でも拒否する。
- 変更: CLI のバージョンを cut2resolve / srt2resolve とも 0.1.3 に更新し、仕様メモに上書き動作と更新内容を追記した。
- 理由: 同じ出力先で再実行したとき、前の EDL・SRT・FCPXML・粗編集動画を確認なしに壊さないため。明示フラグで繰り返し生成する運用は維持する。
- 確認: `python -m unittest -v test_cut2resolve.py` は 37件中24件成功、13件スキップ(ffmpeg/ffprobe がこの環境の PATH に無く、該当テストは従来どおりスキップ)。Resolve 実機 / PC操作テストはユーザー指示により未実施。

## 2026-09-24 GPT(Codex)— 文字起こし統合前提の自動カット計画を作成
- 変更: `cut2resolve/auto_cut.py` を新設。採用区間JSON(v1)を入力に、既定で前後10秒の編集ハンドルをフレーム精度で保持し、残す/削除範囲を記録する。EDL・FCPXML・カット後SRT・`cut-plan.json`・友人向け説明をパッケージ化する。
- 変更: `cut2resolve/selection.example.json` と `docs/project/auto-cut-design.md` を追加。文字起こし画面は将来公開JSON契約から `build_plan()` / `write_package()` を呼べるよう境界を設けた。既存出力保護と `--force` も適用。
- 制約: 文字起こしツール本体には今回は触れていない。FCPXMLタイトルがResolve Free 21.1でText+になるか、パッケージ移動後の再リンク、映像音声同期は実機未確認。EDL/SRTとJSONは復旧経路として同梱する。Resolve PC操作テストはユーザー指示により省略。
- 確認: `python -m unittest -v test_cut2resolve.py` は 41件中28件成功、13件スキップ(ffmpeg/ffprobe が実行環境のPATHにないため)。`py_compile` とCLIヘルプも確認。

## 2026-09-24 Claude(Cowork)— v0.9.9(2つの v0.9.8 の統合)・精度の基準・入力項目
- 変更(transcribe-tool): Claude 版 v0.9.8 と GPT 版 v0.9.8(`_recovered/`)を v0.9.7 を共通の元にした3方向の統合で1つにした。index.html・serve.py・README.txt・AGENTS.md
  - GPT 版から: 保存の安全性(saveDoc の直列化・openDoc の中断)、行の「残す/カット済」(cutState)、Resolve パッケージの書き出し、一覧・候補の検索、候補の回数の既定2回以上、
    準備の案内の表示、serve.py の cutState・/api/resolve-package・スタジオの書き出し先の既定
  - ぶつかった所: 左パネルは Claude の ☰ 開閉の中に GPT のタブ(新規・履歴・精度・学習)。GPT の「集中モード」「管理」ボタン・1280px 以下の切り替え・行の「…」メニューは入れなかった。
    メニューの自動で閉じる幅を編集欄 1000px 未満に(GPT 版でメニューが細くなったため)
  - e2e: タブで隠れるカードも操作できるようテスト用スタイルを追加、e2e_ui_v098.py にタブ・残す/カット済の確認を追加、e2e_ui_v07.py は候補の回数を1回に
- 版: 0.9.8(2つ)→ **0.9.9**
- 確認: test_metrics・test_resolve_export・test_document_save.cjs(9/9)・e2e 5本すべて通過(v07/v09 の「版 v0.9.4」だけ想定内の失敗)。実機(Windows・実エンジン)は未確認
- 追加: `docs/accuracy-baseline.md` / `.json`(段階0の基準。校正済み 8.5 分で CER 8.4%。重なり 24%・要確認の印あり 18%。誤りの多くは呼び名・愛称)、
  `tools/baseline_analysis.py`(再計算用。PC で `python tools/baseline_analysis.py transcribe-tool docs`)、`docs/USER_INPUT.md`(ユーザーの記入用)
- 未完了・次: USER_INPUT.md の記入(特に呼び名)→ 用語集・置換辞書に反映。評価用を 15 分・4 人以上に。`_recovered/` は統合済みなので消してよい
- 注意: 未コミット。PC で git を使う AI がいれば、`[Claude] v0.9.9 統合・基準・入力項目` としてコミットしてほしい(または push.bat)。
  GPT の cut2resolve の未コミットの変更には触れていない

## 2026-09-24 Claude(Cowork)— 全ツールの見直し・UI 刷新・受け渡しの統一(スタジオ 0.2.0 / 文字起こし 0.10.0 / cut2resolve 0.2.0)
- 変更: まとめは `docs/review/README.md`、各ツールの詳細は `docs/review/*.md`。共通の見た目 `ui-kit/`(+ `tools/sync_ui_kit.py`)、受け渡しの約束 `docs/pipeline.md`、
  cut2resolve の専用画面(serve.py・index.html・app.js・app.css・pack.py)、3ツールの通し確認 `tools/e2e_pipeline.py`
- 版: スタジオ 0.1.8 → 0.2.0、文字起こし 0.9.9 → 0.10.0、cut2resolve 0.1.3 → 0.2.0(srt2resolve 0.1.4)
- 決定・理由: ユーザーの選択 = ダーク/ライト切り替え、受け渡しの形式だけ統一(将来アプリ統合の可能性が高い → 見た目は ui-kit で共通、API 呼び出しは各ツール1か所の関数)、
  cut2resolve に専用画面、納品は PC の `_new` フォルダに置いてユーザーが確認してから入れ替え
- 作業の土台: 2026-09-24 08:40 時点の PC の作業フォルダ(他の AI の未コミットの作業 = v0.9.9 統合・auto_cut など を含む)。`_new/入れ替え.bat` は、その時点から PC 側で変わったファイルがあれば止まる
- 未完了・次: 実機(Windows)での確認(`docs/review/README.md` の最後)、ユーザーの判断待ち6件(同じファイル)。受け渡しの一括実行(パイプライン)は個別のツールの完成後
- 注意: ui-kit の写し(clip-studio/ui-kit.*・cut2resolve/ui-kit.*・transcribe-tool/index.html の印の間)は手で直さない。正本 `ui-kit/` を直して `python tools/sync_ui_kit.py`。
  CSP で unsafe-eval を禁止しているため、Playwright の `wait_for_function`(文字列)は使えない(evaluate で待つ)

## 2026-09-24 GPT(Codex)— Resolve Free 21.1 の Text+ 実機確認手順
- 変更: `docs/project/resolve-textplus-test.md` を追加。コピー素材・新規プロジェクトで、EDLカット編集、SRT時刻、Text+変換方式、フォント/スタイル、DRT/DRP、別フォルダ再リンクを順に確認する手順と結果記録欄を作成。
- 理由: Text+自動生成とFree 21.1のスクリプト可否、別PCでの再リンクが未検証のため、実装判断前の安全な合否基準を揃える。
- 注意: 実機操作・第三者スクリプト実行・フォント配布はまだ行っていない。Git状態確認は実行環境の所有者不一致による `dubious ownership` で失敗したため、グローバルGit設定は変更せず、既存ファイルを変更せずに新規手順書とWORKLOGのみ追加した。
