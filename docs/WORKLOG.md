# 作業記録(Claude・GPT 共通)

このリポジトリを編集した AI は、作業の終わりに**末尾へ**1件追記する。作業を始める AI は、最後の数件を読んでから始める(ルールは `AGENTS.md`)。

**2026-09-30 にフォルダ名を変えた**(app→home・clip-studio→studio・transcribe-tool→editor・tools→dev/setup・docs を spec/plan/design/archive に)。この記録の中の旧いパスは当時のまま。対応表は `docs/plan/phase0-restructure.md`。

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
- 続き: 既存のResolve UIテスト素材をコピーし、`%TEMP%\Resolve-TextPlus-Preflight-20260924\` に実機用パッケージを準備した。動画・EDL・カット後SRT・cut-plan JSONのみをコピー(FCPXMLは含めない)。素材は1080x1920 / 30fps / 926 frames、EDLは2区間、SRTは7字幕。ffmpeg/ffprobeはPATHから見つからず、動画メタデータは同梱cut-planの記載を使用。元ファイルは変更していない。
- 実機フィードバック: 動画ストリームの埋め込みTCは `01:00:00:00`、30fps、30.8667秒とローカルメタデータで再確認。EDLの元TCを1時間加算しただけでは解決せず、Resolveの照合はリール名とTC双方を使うため、デスクトップ側テストEDLのリール名も `AX` から `TEST35` へ修正。手順書に `Assist using reel names from → Source clip filename` の設定を追記した。既存タイムラインは変更せず、新規プロジェクトで再試行する案内が必要。

## 2026-09-24 GPT(Codex)— 安全に削除できる作業控え・キャッシュを整理
- 削除: `_recovered/`、`Claude outputs/`、`git-patches/`、3ツールの `__pycache__/`、clip-studio と transcribe-tool の通常・クラッシュログ。
- 残したもの: 未適用の新版 `_new/`、旧版の保険 `0old/`、Whisperモデル、文字起こし・編集データ、現行コード。
- 理由: 復元内容は現行版に統合済みで、パッチ・ログ・Pythonキャッシュは通常運用に不要なため。削除した復旧控えとログはこの作業フォルダからは元に戻せない。

## 2026-09-24 GPT(Codex)— 未適用の新版確認フォルダを削除
- 削除: `_new/`（約2.17GB）。初回は試用中のローカルサーバーがログを使用していたため一部が残ったが、ユーザーが終了した後に完全削除した。
- 影響: `_new` にあった未適用の新版、試用用の写し、入れ替え用バッチ、同フォルダ内のバックアップは復元できない。現行の3ツールとその実行データには変更なし。

## 2026-09-24 GPT(Codex)— cut2resolve v0.3.0 Text+パックを追加
- 変更: `cut2resolve/resolve_textplus.py` を追加し、パック生成処理・画面・CLI に任意の Text+ パック出力を接続。動画は `media/` にコピーし、EDL・カット後SRT・cut-plan JSON・Resolve用スクリプト・登録バッチ・手順書を同梱する。Text+選択時はFCPXMLを生成せず、字幕がない場合はエラーにする。新規プロジェクトは素材の幅・高さ・fpsを設定する。
- 安全: 登録は同梱バッチの明示実行時のみ。Resolve側は新規プロジェクトと `CUT_TextPlus` / `SOURCE_WITH_HANDLES` を作る。プロジェクト名確認に `LoadProject()` を使わず、既存プロジェクトを切り替えない。フォントは同梱しない。
- 版: `cut2resolve_core.py`・画面の埋め込み版・READMEを v0.3.0 に更新。
- 確認: Python構文コンパイル、生成するResolveスクリプト/登録スクリプトの構文、`node --check cut2resolve/app.js` は成功。自動テストは未実施。Free 21.1 実機のスクリプト実行、Text+配置と時刻、削除区間復旧、再リンクは未確認。
- 続き: テスト素材と新規Resolveプロジェクトで、登録・実行可否から確認する。失敗時は従来のEDL + SRTへ戻し、この方式を成功とは記録しない。

## 2026-09-24 GPT(Codex)— Free 21.1向けText+登録をLua実験方式へ変更
- 理由: ユーザー環境では「ResolveにText+スクリプトを登録.bat」を実行後もPythonスクリプトが一覧に出なかった。Resolve 21.1でPythonスクリプトがStudio版へ移ったという更新情報に合わせ、Python登録方式を続けない。
- 変更: Text+パックのResolveスクリプトをLuaへ置換。明示実行バッチはPowerShellを呼び出し、同梱動画の現在の絶対パスを埋め込んだLuaを `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Edit` に登録する。出力UI・手順書・仕様・ファイル名にもLua実験版と明記。EDL/SRT/cut-planと動画同梱、復旧タイムラインの方針は維持。
- 安全・制約: 既存のPythonファイルを削除せず、旧スクリプト登録ファイルも自動削除しない。ユーザーが明示的にバッチ実行するまでResolve側へ登録しない。パック移動後は登録し直す。Lua方式のFree 21.1 Windows動作、Text+の生成・タイミング・字幕数は未確認で、本番プロジェクトでの実行は禁止して新規テストプロジェクトに限定する。
- 確認: Python側の構文確認、`node --check cut2resolve/app.js`、`git diff --check` 成功。`python -m unittest -v test_pack test_serve test_cut2resolve` は161件中106件成功・55件スキップ(ffmpeg/ffprobeがないため)。実機操作・Resolveスクリプト実行は未実施。Lua APIとFree 21.1のスクリプト変更について公開情報を確認したが、Free WindowsでLuaが使える保証は得られていない。

## 2026-09-24 GPT(Codex)— Text+登録PowerShellの文字化け構文エラーを修正
- 原因: 登録用 `.ps1` をBOMなしUTF-8で出力していたため、Windows PowerShell 5.1がANSIとして解釈し、日本語を含む行を正しく構文解析できなかった。
- 修正: `.ps1` はUTF-8 BOM付き・CRLFで生成する。すでに出力済みのパックには反映されないため、再生成するか既存 `.ps1` をBOM付きで保存し直す必要がある。
- 確認: 生成したPowerShellソースをWindows PowerShell Parserで解析し、エラーなし。

## 2026-09-24 Claude(Cowork)— 統合の段階1: 入口(ランチャー)`app/` と `start-all.bat`
- 変更(新規ファイルのみ。既存のツールのコードは変更なし): `app/launch.py`(3ツールを子プロセスとして起動・監視・停止し、入口の画面と API を出す)、
  `app/portal.html`・`portal.js`・`portal.css`(入口の画面。見た目は `ui-kit/` の正本をそのまま配る)、`app/README.txt`、`app/test_launch.py`(29件)・`app/e2e_portal.py`(Playwright)、
  リポジトリ直下の `start-all.bat`・`start-all.command`、`docs/integration-plan.md`(統合計画の要約)。`AGENTS.md` に `app/` と「起動の約束」を追記
- 版: 入口 v0.1.0(新規。版の正は `app/launch.py` の `VERSION`)
- 決定・理由: ユーザーの判断 = 統合は、まず cut2resolve 以外(スタジオ・文字起こし)。今回は段階1だけ(ツールのコードは触らない)。
  入口は cut2resolve も一緒に起動するが、中身には触れない(GPT の Text+ 作業中のため)
- 設計: 子の出力は `app/logs/<ID>.log`(黒い画面は入口の1つだけ)。準備完了は「起動後に書かれた `.runtime/<ID>.json` のポート + `/api/ping`」で判定(古い記録・pid は信用しない)。
  別の黒い画面で起動済みのツールは「別の画面で起動済み」として起動も停止もしない(古い版なら表示で知らせる)。停止は Windows = Ctrl+Break(子を CREATE_NEW_PROCESS_GROUP で起動)、
  それ以外 = SIGTERM。8秒で終わらなければ強制終了し、残った `.runtime` を片付ける。動作中の確認は TCP 接続だけ(`/api/ping` を定期的に送ると文字起こしのログが埋まるため)。
  入口のポートは 8700〜8719。異常終了は自動で起動し直さない(同じ原因で落ち続けないように)
- 確認: `python -m unittest app/test_launch.py` 29件 OK(偽のツール + 本物の3ツールの疑似モード)、ミューテーション 14件をすべて検出、`python app/e2e_portal.py` すべて OK、
  PC の cut2resolve(v0.3.0・21:18 時点の未コミット版)でも入口からの起動・停止を確認
- 未完了・次: Windows 実機での確認 = start-all.bat の起動、黒い画面の × で3ツールも終わり `.runtime` が消えるか、Ctrl+C、入口からの停止(Ctrl+Break)、
  別の黒い画面で起動済みのツールがあるときの表示。段階2(共通コア `ytt_core`)は未着手
- 注意: 各ツールの起動の約束(`serve.py [ポート] --no-open`・`.runtime/<ID>.json`・`/api/ping`・SIGTERM/SIGBREAK で後始末)を変えると入口が壊れる。変えるときは `app/launch.py` と `app/test_launch.py` も直す。
  未コミット(Claude Cowork は PC で git を使えない)。コミットするときは `[Claude] 統合の段階1: 入口(ランチャー)` として app/・start-all.*・docs/integration-plan.md・AGENTS.md・この WORKLOG を。
  GPT の cut2resolve の未コミットの変更には触れていない

## 2026-09-24 Claude(Cowork)— 入口 v0.1.0 の Windows 実機確認(ユーザー)
- 確認: ユーザーが Windows 実機で確認済み(start-all.bat で3ツールが動作中になる、黒い画面の × で3ツールも終わり .runtime が消える、入口からの停止・再起動)
- 未完了・次: 段階2(共通コア ytt_core。スタジオと文字起こしだけ)。未コミットの状態は前の記録のとおり

## 2026-09-24 GPT(Codex)— Text+の1時間ずれと日本語フォントを修正
- 原因: Lua生成スクリプトは再生位置用の絶対フレーム(`GetStartFrame()` + 字幕フレーム)を、タイムライン開始からの相対フレームを受け取る`SetMarkInOut`にも渡していた。開始TCが01:00:00:00の場合、Text+が02:00:00:00付近に置かれる。ユーザーがCtrl+Zで元位置に戻した画面でも確認した。
- 修正: 範囲指定には字幕の相対フレームを渡す。再生位置用の絶対タイムコードは維持。Text+にこのPCのResolveで日本語表示を確認した「MS ゴシック」を明示指定する。フォントファイルの同梱はしない。
- 確認: `python -m unittest -v test_pack.TestResolveTextPlusScript` 1件成功、`python -m unittest -q test_pack test_serve test_cut2resolve` 163件中108件成功・55件スキップ。旧パックや既存Resolveプロジェクトには自動反映されない。修正版パックのResolve実機再検証は未実施。
- 音割れ: ユーザーによるとスクリプト実行前後で変化。コピー素材と元素材のハッシュは一致し、スクリプトに音声変換・増幅はない。原因未確定。CUT_TextPlusとSOURCE_WITH_HANDLESの同一箇所を比較し、Resolve内の配置・再生側を切り分ける。音声処理の推測によるコード変更は行っていない。

## 2026-09-24 GPT(Codex)— Text+のフォント名と太さをセットで指定
- 実機再確認: ユーザーの新規テストプロジェクトで `Font Not Found: MS ゴシック Semibold` と表示。前回の修正はフォント名だけ変え、既定のSemiboldを残していた。タイムライン上の字幕位置は映像冒頭に合っていた。
- 修正: このPCのResolveで表示実績がある `Noto Sans JP / Medium` を各Text+に指定する。フォントファイルは同梱しない。生成パックの説明も更新。
- 確認: 対応する生成スクリプトの回帰テスト1件成功。新しいパックでの表示は未確認。音割れは継続しており、画面上のCUT_TextPlusとSOURCE_WITH_HANDLESはともに同梱movの音声1クリップのみ。SOURCE_WITH_HANDLESの再生結果をユーザーに確認中。音声コードは未変更。

## 2026-09-24 GPT(Codex)— 音割れをResolve編集ページのタイムライン再生に切り分け
- 同一のコピー素材・冒頭をユーザーと実機比較: メディアプールの元クリップを直接再生すると正常、CUT_TextPlusとSOURCE_WITH_HANDLESの編集ページ再生は音割れ、Fairlightページでは同じSOURCE_WITH_HANDLESの冒頭が正常。
- SOURCE_WITH_HANDLESで映像トラックを一時オフにしても音割れ。映像トラックは元に戻した。A1とBus1のフェーダーは0 dB、追加エフェクト欄は空。元クリップからResolve標準UIで作ったAUDIO_DIAG_MANUALタイムラインも編集ページで音割れしたため、LuaのAppendToTimeline固有の問題ではない。
- AUDIO_DIAG_MANUALはコピー素材を使った新規テストプロジェクト内に作成。その他のプロジェクトや元ファイルは変更していない。今後、短い書き出しでも割れるかを確認し、再生のみの問題か最終成果物にも出る問題か分ける。音声コード変更なし。

## 2026-09-24 GPT(Codex)— 音割れは編集ページの再生時だけと確認
- `cut2resolve/exports/AUDIO_DIAG_MANUAL.mov` をテストプロジェクトの手動タイムラインからH.264/AACで書き出し、ユーザーがResolve外で再生して音割れなしと確認。診断用動画は実行時出力としてgitignore対象。
- 同一箇所でメディアビューアとFairlightは正常、編集ページのスクリプト生成/手動生成タイムラインだけで割れた。素材・Lua配置処理・書き出しデータの破損を示す結果ではない。Resolve編集ページのプレビュー再生問題として扱い、音声の再エンコードやゲイン変更はしない。
- 残り: 修正後の `Noto Sans JP / Medium` を新規生成パックで実機確認する。編集ページの再生音そのものを直したい場合は、ResolveのオーディオI/Oや環境側を別途診断する。グローバル設定は未変更。

## 2026-09-24 GPT(Codex)— フォント再確認用の新規パックを作成
- 新規生成: `cut2resolve/exports/test35_fontcheck_pack/`。コピー素材test35.movとSRTから、既存パックを上書きせずText+パックを生成。元素材と同梱movのSHA256一致。Luaに字幕範囲の相対フレーム指定、`Noto Sans JP / Medium` の両指定が含まれることを確認。
- 目的: ユーザーがResolveを閉じて新パックの登録バッチを実行し、新規テストプロジェクトで日本語表示と字幕位置を確認できるようにする。登録・実機確認は未実施。診断用の旧プロジェクトと旧パックは保持。

## 2026-09-24 Claude(Cowork)— 統合の段階2: 共通部品 `ytt_core/`(スタジオ・文字起こし・入口)
- 変更: 新規 `ytt_core/`(fsio = 原子的な書き込み・JSON の読み込み・ネットワークパスの判定 / runtime = `.runtime` と /api/ping・/api/siblings /
  schemas = clip/v1 の組み立て・検証 / httpsec = Host・Origin・Sec-Fetch の検査 / tools = ffmpeg などの場所。テスト `ytt_core/test_ytt_core.py` 27件)。
  スタジオ `common.py`(atomic_write・replace_file・find_tool)・`handoff.py`(全体)・`serve.py`(安全検査)、文字起こし `serve.py`(atomic_write・find_ffmpeg・安全検査・probe・runtime_path_dir)・
  `pipeline_io.py`(clip/v1・書き込み・.runtime)、入口 `app/launch.py` を ytt_core を呼ぶ形に。関数名はそのまま残した(呼び出し側・テストを変えないため)
- 版: 各ツールの版は上げていない(画面・API・保存の動きは変えていないため)。ytt_core 1.0.0
- 決定・理由: ユーザーの指示「段階2」。統合の対象はスタジオと文字起こし(cut2resolve は対象外なので触れていない。ツールID の対応のずれだけテストで検出)。
  ytt_core は「YTT_CORE_DIR → ツールのフォルダの1つ上」で探し、sys.path の末尾に足す。無ければ理由を出して起動しない
- 動きがそろったところ: ファイルの置き換えのやり直しは「winerror 5・32・33 のときだけ4回(待ち合計 0.7 秒)」に統一(文字起こしは以前 Windows の PermissionError で6回)。
  `.runtime` のポートは 1024〜65535 に統一。fsync は文字起こしだけ「失敗なら保存も失敗」のまま
- テスト: 一時フォルダに serve.py を写す文字起こしのテスト・e2e と tools/e2e_pipeline.py・baseline_analysis.py に `YTT_CORE_DIR` の1行を追加。
  入口のテストは一時フォルダに ytt_core も写す
- 確認: スタジオ 単体7本 OK・test_review.cjs 14/14・e2e_analyze OK・e2e_ui 70/70、文字起こし test_backend 40・test_metrics 74・test_resolve_export 6 OK・test_document_save.cjs 9/9・
  e2e_ui_handoff / v098 / v08 / eval_v093 OK(v07・v09 は想定内の「版 v0.9.4」だけ失敗)、tools/e2e_pipeline OK、test_ui_kit_sync OK、入口 test_launch 29 OK・e2e_portal OK、
  cut2resolve の単体(変更なし)OK、ytt_core 27 OK。ytt_core へのミューテーション 10件はすべてどれかのテストで検出
- 未完了・次: 段階3(1つのサーバーへの取り込み)は「個別ツールの完成」の後(基準は未決)。ffmpeg の呼び出しとジョブの型は段階3で(docs/integration-plan.md の「段階2で決めたこと」)
- 注意: 起動中のスタジオ・文字起こしは古いコードのまま動いている。入口の「再起動」か、黒い画面を閉じて起動し直す。ツールのフォルダだけを別の場所へ写すと ytt_core が見つからず起動しない
  (写すならリポジトリごと、またはテストのように YTT_CORE_DIR を設定)。未コミット。GPT の cut2resolve の作業には触れていない

## 2026-09-24 GPT(Codex)— Text+テストパックの字幕入力取り違えを訂正
- 原因: 30.87秒の動画全編を使う `test35_fontcheck_pack` に、9秒のカット後SRT（7字幕）を渡していた。元の `cut2resolve/resolve-ui-test/test35.srt` は29.69秒まで14字幕あり、先のパック生成時の入力選択ミス。Text+の時刻計算やフォント変更による圧縮ではない。
- 対応: 既存パックは上書きせず、全編SRTを使って `cut2resolve/exports/test35_fullsubs_pack/` を新規生成。コード変更なし。動画は926フレーム、Text+計画は14字幕・末尾891フレーム（29.7秒）。元動画と同梱動画のSHA256一致、FCPXMLなし。
- 注意: `ffprobe` が現環境のPATHで実行できないため、直前パックと実機で検証済みのメタデータ（30fps・926フレーム・1080x1920・開始TC 01:00:00:00）を使用した。Resolve実機の新パック読み込みと音声書き出しは未確認。編集ページのプレビュー音割れ問題は別件として継続。

## 2026-09-24 GPT(Codex)— Text+を上段トラックへ配置し既存プロジェクトを再利用
- 変更: Lua生成スクリプトは開いているプロジェクトを使い、fps・解像度が素材と一致するときだけ新しいCUT_TextPlus / SOURCE_WITH_HANDLESを追加する。合わないときは編集前に停止。プロジェクト未選択なら従来どおり新規作成。既存タイムライン名と衝突する場合は末尾に連番を付ける。
- 原因/配置: カット映像を置いた後に上段の映像トラックを追加し、そこへText+を置く。現行の文字起こしツールのResolve出力でも使うAddTrack→Text+挿入の順に合わせた。映像クリップを字幕で分割する問題を避ける。
- 版: cut2resolve v0.3.1。README・CLI表示・serve画面の版を更新。
- パック: `cut2resolve/exports/test35_fullsubs_pack/` の生成Luaと手順書だけを更新。既存ResolveプロジェクトやEDL/SRT/素材コピーは変更していない。Resolve Free 21.1実機で配置・再実行はまだ未確認。再試行時はResolveを閉じて登録バッチを再実行し、その後fps/解像度が合うテストプロジェクトを開いてLuaを実行する。

## 2026-09-24 GPT(Codex)— 最新Text+パックをデスクトップへ集約
- 新規作成: `C:\Users\you11\Desktop\Resolve_TextPlus_最新版\`。全編SRT14字幕、Text+の上段トラック配置、既存プロジェクト再利用を含む。タイムライン長926フレーム、最終字幕終了891フレーム(29.7秒)。元動画と同梱動画のSHA256一致。
- 削除: AI生成の旧パック `cut2resolve/exports/test35_fontcheck_pack/`、`cut2resolve/exports/test35_fullsubs_pack/`、`cut2resolve/exports/Resolve_TextPlus_LATEST/`、デスクトップのPreflight内 `test35_pack/`。デスクトップの最新パック、Preflight内の素材/SRT/EDL/cut-plan、音声診断動画 `AUDIO_DIAG_MANUAL.mov`、Resolveプロジェクトは保持。
- 注意: 登録済みのLuaはResolveを閉じて、新パック内の登録バッチを実行し直す必要がある。V2配置・同一プロジェクト再利用はResolve Free 21.1実機で未確認。

## 2026-09-24 GPT(Codex)— Text+が映像の間に入る問題を実機で修正
- 原因: `AddTrack("video")` の後でも `InsertFusionTitleIntoTimeline("Text+")` は配置先を指定できず、タイトルがV1の映像の間に入った。Resolve Free 21.1のテストプロジェクト `C2R_test35_Lua_814785` で確認。
- 対応: 中立のText+を収めた `cut2resolve/textplus-template.drb` を追加。パックへ同梱し、Luaでビンを読み込んで `AppendToTimeline` の `trackIndex=2` と `recordFrame=タイムライン開始フレーム+字幕開始フレーム` を明示。字幕長は各キューのフレーム差で指定。cut2resolve v0.3.2。既存のEDL・SRT・cut-planと映像・音声処理は変更なし。
- 実機確認: コピー素材の既存テストプロジェクト内に `CUT_TextPlus_2` と復旧用タイムラインを追加。V1映像1本、A1音声1本、V2のText+14個、スクリプト失敗0。タイムライン開始108000フレーム、最初の字幕開始108039/長さ78、最後の字幕開始108801/長さ90で、計画の最終終了891フレームと一致。元の `CUT_TextPlus` は上書きしていない。
- 配布物: デスクトップ `Resolve_TextPlus_最新版` の生成Lua・登録ps1・手順書を更新しDRBを追加。登録済みLuaも更新済み。試験用DRB 1個は最新版フォルダから削除(復旧不要の今回生成した一時ファイル)。動画・EDL・SRT・cut-planはそのまま。`test_pack` 42件、`test_cut2resolve` 104件が成功(依存不足によるスキップあり)。編集ページの音割れは書き出しでは再現しない別件のまま。
- 未完了: 友人側PCでのDRB受け渡し・再リンクと、新しいタイムラインでの音声プレビューは未確認。既存の他AI未コミット変更を混ぜないため、この変更はコミットしていない。

## 2026-09-25 GPT(Codex)— 横型Text+実機検証パックを別途準備
- 経緯: ユーザーの横型方針に対し、従来の `test35` パックは1080x1920の縦素材だった。新規の1920x1080・30fpsプロジェクトで既存の登録Luaを直接実行すると、解像度不一致で素材を読み込む前に停止した。既存プロジェクト対応コードの削除やText+生成失敗ではない。メニュー経由は出力が見えず、Luaコンソールからの `dofile` でエラーを確認した。
- 対応: 横型の `1本目.mkv` を変更せず、冒頭約30秒を1920x1080・30fpsのローカル試験用mp4に書き出した。配置確認用の仮日本語字幕5件とともに、コード変更なしで `C:\Users\you11\Desktop\Resolve_TextPlus_横型検証_20260925` に新規パックを作成。元動画や従来の縦型パック、Resolveプロジェクトは変更していない。仮字幕は発話内容・時刻と一致しないことを同梱注意書きに明記した。
- 確認: 動画コピーのSHA256一致、planは1920x1080/30fps・字幕5件・カット1区間、Text+雛形あり、FCPXMLなし。Resolve実機での新パック読み込みとV1/A1/V2配置・音声は未確認。Resolveを閉じて新パックの登録バッチを実行し、既存の横型テストプロジェクトで試す必要がある。
- 注意: 他AIの未コミット変更とWORKLOGの既存差分を混ぜないため、この記録はコミットしていない。

## 2026-09-25 GPT(Codex)— 横型Lua未登録による同じ解像度エラーを解消
- 原因: 横型テストプロジェクトで再実行後も不一致エラーが出たため、登録済みLuaを読み取ったところ、更新日時が2026-09-24 23:36のまま、埋め込みデータが縦型 `test35`（1080x1920）だった。横型パックの生成自体は正常で、ユーザー側のプロジェクト設定は30fps・1920x1080だった。
- 対応: 新規横型パックの `install_resolve_textplus_script.ps1` を実行し、登録済みLuaを横型 `landscape_test`（1920x1080・30fps）に更新した。登録ファイルの内容と更新時刻を確認済み。元動画・Resolveプロジェクト・リポジトリのコードは変更していない。
- 未完了: 横型プロジェクト上で更新後Luaを実行し、V1/A1/V2を実機確認する。既存の未コミット変更を巻き込まないためコミットはしていない。

## 2026-09-25 GPT(Codex)— 横型Text+パックの実機確認結果
- ユーザー報告: 更新済み横型Luaを使った検証で「問題ない」、今回は音声も正常。横型の短尺コピー素材と仮字幕を用いた結果であり、元の長尺素材や以前の縦型 `test35.mov` での音声結果には一般化しない。
- 次: ユーザーは「さっきまでの元動画」での再確認を希望。`test35.mov`（縦1080x1920）と横型パックの元にした `1本目.mkv`（横1920x1080・60fps）のどちらを指すか確認してから、元データを変更しないコピーで進める。

## 2026-09-25 GPT(Codex)— test35の元となる横動画の所在を調査
- ユーザーの指定は、`test35.mov` の元になった横動画。`test35.mov` はDropboxの完成品デモ `26-09-13_さくらみこ.mov` とサイズ・SHA256が一致する縦型のResolve書き出しで、横の元動画そのものではない。
- 先に横型検証で使った `1本目.mkv` のフレームはResolve画面の録画で、`test35.mov` の元動画とは別物と確認。したがってそのパックで音声が正常でも、`test35` の元横動画の音声問題の解消はまだ確認できない。
- Dropboxの「未検査」にあるさくらみこ関連の横動画候補8本は、ローカルではクラウドプレースホルダー。読み取りは「クラウド ファイル プロバイダーが実行されていません」で失敗し、内容照合やパック作成は未着手。ユーザーから元横動画の正確なファイル場所、またはローカル利用可能なコピーを受け取って続行する。元動画・候補ファイルは変更していない。

## 2026-09-25 GPT(Codex)— 別の横動画でText+音声検証パックを準備
- ユーザー提供の `E:\Video\切り抜き動画素材\...\05_00h34m14s-00h34m48s.mp4` は横1920x1080・60fps・34.4秒、H.264/AACの音声あり。元動画は一切変更せず、再エンコードせずにコピーしてText+パックを作った。
- デスクトップの新規フォルダ `C:\Users\you11\Desktop\Resolve_TextPlus_千速_横60fps_20260925` にEDL/SRT/cut-plan、動画コピー、Lua、登録スクリプト、Text+雛形、注意書きを格納。SRT3件は配置検証の仮文で発話内容とは一致しない。元動画と同梱コピーのSHA256一致、計画は1920x1080・60fps・2064フレーム・字幕3件・カット1区間、FCPXMLなし。
- 前回の登録漏れを防ぐため、登録済みResolve Luaを今回パックへ更新し、埋め込みデータが該当動画・60fps・1920x1080であることを読み取り確認した。既存の30fps横型プロジェクトは変更していない。60fpsの新規テストプロジェクトでV1/A1/V2と音声を確認する必要がある。
- リポジトリのコード変更なし。既存の他AI未コミット変更を巻き込まないためコミットしていない。

## 2026-09-25 Claude(Cowork)— 編集ページの音割れは未解決(「横型で音声正常」は判断材料にならない)
- 分析: 「横型Text+で音声も正常」とされた `landscape_test.mp4`(画面録画)は、平均 -46.1 LUFS・最大 -28.2 dBFS・左右同一で、ほぼ無音。音割れを聞き分けられない音量のため、解消の根拠にならない。60fps の `05_00h34m14s-00h34m48s.mp4` で再び割れたのは再発ではなく、最初から未解決と見るべき。
- 割れた素材の比較: `test35.mov`(PCM 24bit・30fps・縦・TC 01:00:00:00・最大 -9.7 dBFS)と `05_...mp4`(AAC・60fps・横・TCなし・最大 -2.8 dBFS)は共通点がなく、どちらもファイル上は頭打ちなし。素材の形式・fps では説明できず、Resolve 編集ページの再生か PC 環境が原因の可能性が高い。Claude が30fpsに変換した版も音声は元と同一データ(MD5一致)。
- ユーザー報告の症状: 「プツプツ・パチパチ」と「大きい声のところだけ歪む・ビリつく」。編集ページのタイムラインのみ、処理は重く見えない。
- 見立て(未確定): 再生の途切れ(バッファ不足)は、音が大きいほど途切れのクリック音も大きくなるので、2つの症状を1つの原因で説明できる。音量の上がりすぎ(メーターが赤)とは、診断テストで区別する。前回の「Fairlight で正常」は冒頭だけの確認だった点に注意。
- 用意: 診断用動画 `audio_diag_30fps.mov` / `audio_diag_60fps.mov`(音声は同一の PCM。-18/-6/-1 dBFS の 1kHz、左だけ/右だけ、1秒ごとのクリック、スイープ)と手順書。置き場所 `cut2resolve/exports/audio_diag_20260925/`(git の対象外)。
- 未完了・次: ユーザーの診断結果待ち。音声のコード・再エンコード・ゲインは変えない。結果が出るまで音割れを「解決済み」と扱わない。

## 2026-09-25 Claude(Cowork)— 音割れはスクリプト実行が引き金(編集ページ全般の問題ではない)
- ユーザーの結果: 診断用の一定の音(-18/-6/-1 dBFS・左右・クリック・スイープ)は、メディアプール・編集ページ・Fairlight・60fps素材を30fpsタイムラインに置く・「すべてのビデオフレームを表示」オフ のすべてで正常(メーターも正常)。**手で作った新規プロジェクトに元動画 `05_...mp4` を手で置くと割れない**。
- ユーザーの指摘(GPT にも繰り返し伝えていた): **スクリプトを実行すると音割れする**。09-24 の記録「手動タイムライン AUDIO_DIAG_MANUAL も割れたので Lua 固有ではない」は、スクリプトを実行した後の同じプロジェクトでの確認であり、スクリプトの影響を除外できていない。「Resolve 編集ページのプレビュー再生問題」という結論は撤回し、スクリプト実行がプロジェクト(または Resolve の起動中の状態)を変えている前提で調べる。
- 除外できたこと: 編集ページで音量が上がって頭打ちする線(-1 dBFS の一定の音もメーターも正常)、素材の形式・fps。
- 用意: `cut2resolve/exports/audio_bisect_20260925/`(git 対象外)に、本番の Lua の処理を4段階に分けた診断スクリプト S0(何もしない)/ S1(ImportMedia + CreateEmptyTimeline + AppendToTimeline)/ S2(+ drb 雛形の ImportFolderFromFile + AddTrack)/ S3(+ Text+ 3個と SetInput)、登録バッチ、手順書。どれもプロジェクトの設定は変えない。毎段階、新規プロジェクトで、スクリプトが作ったタイムラインと手で作ったタイムラインの両方を再生し、割れたら Resolve 再起動後も続くかを見る。
- 注意: Claude が同日に作った縦型の自動設定テスト(`vertical_scale_test_20260925`)も新規プロジェクトを作って SetSetting するスクリプトなので、音割れの切り分けが終わるまで音の確認には使わない。
- 未完了・次: 診断結果待ち。原因が分かるまで Text+ パックの Lua に機能を足さない。

## 2026-09-25 Claude(Cowork)— 音割れ: スクリプトが API で作ったプロジェクトだけ設定が違う
- ユーザーの手順: 手で新規プロジェクト → 60fps 元動画は割れない → スクリプト実行後は割れる → メディアプールを空にして入れ直しても割れる → 30fps のタイムラインなら割れない。
- Resolve のログ(`Support/logs/davinci_resolve.log`)より、このとき実行したのは Claude の縦型テスト(`cut2resolve Vertical Test`)で、これは `CreateProject` で別のプロジェクト `C2R_VerticalTest_…` を作って切り替える。割れたのはそのプロジェクト。
- プロジェクト DB(`Resolve Project Library/…/Projects/<名前>/Project.db` の `SM_Config.FieldsBlob`。zstd + protobuf)を比較: API で作ったプロジェクトは、画面から作ったものと既定値が違う(解像度プリセット名なし・2160x3840・キャッシュ/最適化メディアの形式なし・いくつかの項目が未設定)。fps を 60 にそろえた手作りプロジェクト(60fps 動画・60fps タイムライン)は割れなかった。
- ユーザーの指摘: B(API 製プロジェクトが原因)と断定するのは危険。API 製でも割れないことがある。原因は未特定。当面の決まり: スクリプトにプロジェクトを作らせない・設定を変えさせない。
- 注意: この PC の Resolve 無料版では、スクリプトの print がコンソールに出ず、io.open でのファイル書き出しもできなかった。設定の確認は DB を直接読む(読むだけ)。

## 2026-09-25 Claude(Cowork)— cut2resolve v0.4.0: Text+ は「手で作ったプロジェクト」に足すだけ・60fps 動画を 30fps タイムラインに
- 担当: ユーザーの指示で、数日間 cut2resolve の Text+ は Claude が担当(GPT は触らない)。
- 前提(ユーザー): ① 最終は 30fps で友人が編集 ② 字幕は Text+ 必須 ③ 縦にしても画面外を後で使える。切り抜きスタジオの出力は 60fps 横。30fps に作り直すと画質が落ちるのが懸念。友人がスクリプトを実行する(案A)。
- 方針: 動画は再圧縮せずに元の 60fps 横のまま渡し、30fps・縦はプロジェクト側で作る。ユーザー確認済み(実機): 手で作った 30fps・1080x1920・入力スケーリング「最短辺をマッチ: 他をクロップ」のプロジェクトに 60fps 横の元動画を置くと、音は割れず、位置 X で画面外も見える。
- 変更: `resolve_textplus.py`(Lua を作り直し)・`pack.py`・`cut2resolve.py`(`--textplus-fps` / `--textplus-size`)・`serve.py`(`textplusFps` / `textplusSize`、不正は 400 bad_textplus)・`index.html` / `app.js`(置き先の fps・向きの選択)・`README.txt`・テスト。新規 `resolve_lua_mock.lua`。
  - Lua: CreateProject / SetSetting / LoadProject を使わない。開いているプロジェクトの fps・解像度が置き先(既定 30fps・1080x1920)と違えば何もせず止まる。
  - 字幕の位置: 字幕は区間ごとに「何番目の残す区間の先頭から何コマ(動画のコマ)」で持ち、実際に置かれたクリップの GetStart() + オフセット x(タイムライン fps / 動画 fps)で置く(実機の丸め方に依存しない)。
  - 結果表示: print が見えない環境があるため、成功 = CUT_TextPlus の先頭に緑マーカー(メモに件数・fps・拡大設定)、一部失敗 = 黄、失敗 = 空のタイムライン「C2R_エラー_理由」。
  - 前の版で importer_script が呼び出し元の plan を書き換えていた(absolutePath)のを直した。
- 版: cut2resolve 0.3.2 → 0.4.0
- 確認: test_pack 54 件・test_cut2resolve 111 件・test_serve 23 件・e2e_ui すべて OK(クラウド)。生成した Lua を Lua 5.3 と Resolve API の偽物で実行し、60fps→30fps の位置・止まり方・禁止 API を確認。ミューテーション(換算を外す・位置の基準を変える・fps 確認を外す・エラー表示を外す)をすべて検出。
- 未確認(実機): AppendToTimeline の startFrame/endFrame が 60fps の動画でも動画のコマで解釈されるか、30fps タイムラインでの実際の丸め方、AddMarker・日本語のタイムライン名。
- 未完了・次: ユーザーが実際の動画でパックを作り(置き先 30fps・縦)、手で作ったプロジェクトで実行して確認。未コミット。

## 2026-09-25 Claude(Cowork)— cut2resolve v0.4.0 の実機確認(ユーザー)と追加の修正
- 実機結果(実際の切り抜き動画、60fps 横 → 30fps・1080x1920 のプロジェクト): マーカー緑「字幕 18/18・カット 8/8・長さのずれ 0・復旧用 あり」、音割れなし。字幕の位置も合っていた。60fps の奇数コマから始まる区間は、Resolve が半コマの位置(In=340|0.5)で正しく扱っていた。
- 1回目は位置 X で画面の外が見えなかった: マーカーの「拡大設定 scaleToFit」= 入力スケーリングが「最長辺をマッチ: 黒帯を挿入」のまま実行していた。設定を「最短辺をマッチ: 他をクロップ」にすると見えた。新しいプロジェクトで「設定を保存・再確認 → 実行」の順にやり直すと、すべて問題なし(緑)。
- 追加: 縦の置き先 + 横の動画で拡大設定が scaleToFit のときは、タイムラインは作ったうえで黄色マーカー「cut2resolve 拡大設定を確認」(メモに直し方)。判定には実機で確認できた値 scaleToFit だけを使う(クロップ側の API 上の名前は未確認)。テスト追加。
- 実行直後は、削除などはできるが、インスペクタの細かい数値を変えても反映されないことがある。少し待てば直る(Resolve の裏の準備と思われる。原因は未調査)。Text+の使い方.txt に「少し待ってから再生・編集」を追記。
- プロジェクト DB の読み方のメモ: SM_Config の設定の protobuf で、1=解像度プリセット名、248=タイムライン fps(float)、275=2 が「最短辺をマッチ: 他をクロップ」(黒帯のときは項目なし)と見られる。
- 未完了・次: 友人の PC での確認(登録 bat・フォント Noto Sans JP・プロジェクトの作り方)。コミット(未)。

## 2026-09-25 Claude(Cowork)— 注意: Cowork からの書き込みが古い内容になることがある
- Cowork(クラウド)から PC へ同じ名前のファイルを何度も書き込むと、2回目以降が前の内容のまま書かれることがあった(resolve_textplus.py・resolve_lua_mock.lua・この WORKLOG)。
  書き込み後に読み直して一致を確認する。今回、字幕の見た目(MS ゴシック・黄色 + 黒ふち)の版が PC に入っておらず、ユーザーの実機確認が古いスクリプトで行われた。修正して一致を確認済み。
- cut2resolve の画面(serve.py)は起動時にプログラムを読み込む。コードを直したら黒い画面を閉じて start.bat から起動し直してからパックを作る。
- 字幕の見た目: MS ゴシック(Regular)・黄色い文字(#FFE600 付近)+ 黒いふち。resolve_textplus.py の TEXT_STYLE。実機未確認。
- 拡大設定: 新規プロジェクト 12・13 は DB 上「最短辺をマッチ: 他をクロップ」(SM_Config の 275=2)なのに、スクリプトの GetSetting は scaleToFit と返した(実行時点の値かは不明)。GetSetting の値が画面の設定と一致しない可能性あり。確認中。

## 2026-09-25 Claude(Cowork)— Text+ 字幕のフォントを「一覧から選ぶ」に変更・拡大設定の警告を廃止(実機で成功)
- フォント: 名前の決め打ちは実機ですべて Font Not Found(「MS ゴシック」+ Semibold / Regular / 標準、「ＭＳ ゴシック」+ 標準)。
  Lua で `resolve:Fusion().FontManager:GetFontList()` を読み、候補(Yu Gothic / 游ゴシック / Meiryo / メイリオ / MS Gothic / ＭＳ ゴシック / BIZ UD… 等)のうち実際にある書体、
  太さは Bold / 太字 / Regular / 標準 の順(無ければその書体にある太さ)を選ぶ。一覧を読めなければ予備(MS Gothic Regular)。
  選んだ書体と選び方をマーカーのメモに出す(候補が無いときは日本語らしい書体名の例も出す)。候補・色は resolve_textplus.py の TEXT_STYLE。
- ユーザーの指示: 「初期から入っている日本語フォントなら何でもよい」。字幕の色 = 黄色い文字 + 黒いふち(実機で確認済み)。
- 実機結果: 新しい版で Font Not Found が出ずに完成(ユーザー「できた」)。どの書体が選ばれたかは未記録。
- 拡大設定: 画面は「最短辺をマッチ: 他をクロップ」で画面の外も見えるのに、GetSetting("timelineInputResMismatchBehavior") は scaleToFit を返した。
  この値は当てにならないので黄色の警告は廃止し、「拡大設定(参考)」としてメモに出すだけにした。友人向け手順書は「上下に黒い帯がないか」を目で確認する形。
- 注意(再掲): cut2resolve の画面はコード更新後に起動し直さないと古いコードでパックを作る(入口から起動している場合は入口で停止→起動)。
- 未完了・次: 友人の PC での確認。コミット(未。Claude の cut2resolve の変更: resolve_textplus.py・pack.py・cut2resolve.py・serve.py・cut2resolve_core.py・app.js・index.html・README.txt・test_pack.py・test_serve.py・resolve_lua_mock.lua(新規))。

## 2026-09-25 Claude(Cowork)— 統合計画を更新: 段階3 に cut2resolve を追加・未決5件を決定・AGENTS.md にリスク一覧
- 変更: `docs/integration-plan.md`・`AGENTS.md`(文書のみ。コードは触っていない)
- 決定・理由(ユーザー): 段階3 の対象にスタジオ・文字起こしに加えて cut2resolve を入れる(v0.4.0 の Text+ パックが実機で成功し、除外理由の「Resolve 実機未確認」が解消したため)。
  未決5件も決定: 担当 = Claude が主担当 / 完成の基準 = 主要機能が動けば統合しながら並行で仕上げる / 作業データ = リポジトリの外 / 旧起動方法 = 統合後も残す / ブラウザか pywebview か = 段階3 の実装後に検討(保留)
- ゲート: cut2resolve の未コミットの変更(0.3.2 → 0.4.0、11ファイル。うち resolve_lua_mock.lua は未追跡)にテストを足してコミットするまで、段階3 に入らない
- 確認(git の index と PC のファイルの照合): HEAD = bd1eba6「更新 2026/09/25 0:44」(push 済み)。cut2resolve は 0.3.2 までコミット済み、0.4.0 の11ファイルと docs/WORKLOG.md が未コミット。app/・ytt_core/・start-all.* はコミット済み
- 未完了・次: 上のゲート(cut2resolve のテスト・コミット)。cut2resolve を段階3 のどの順で取り込むか。このファイルと上の2ファイルのコミット(Claude(Cowork)は git を実行できない)

## 2026-09-25 Claude(Cowork)— 段階3 のゲート: cut2resolve 0.4.0 のテストを確認・Text+ の CLI テストを追加
- 変更: `cut2resolve/test_cut2resolve.py`(Text+ パックを CLI で作るテスト 2件: 60fps の動画を再圧縮せず media/ に入れる・置き先の既定 30fps・1080x1920・計画にローカルの絶対パスを入れない・Lua がプロジェクトを作らない / `--textplus-fps`・`--textplus-size` の指定と不正値で何も作らないこと)。`docs/integration-plan.md`
- 確認(クラウド。GitHub の bd1eba6 に PC の未コミットの変更を重ねた状態): test_pack 53・test_cut2resolve 119・test_serve 23・e2e_ui・ytt_core・app/test_launch・tools/e2e_pipeline すべて OK。Lua は texlua(Lua 5.3)で実行
- 決定(ユーザー): EDL は Text+ の予備のまま。EDL 取り込みの実機確認は当面しない。友人の PC での Text+ の実機確認は済んだ。本格的にツールの統合(段階3)を始めたい
- 未完了・次: **コミット**(cut2resolve の12ファイル・docs/integration-plan.md・AGENTS.md・docs/WORKLOG.md。push.bat で可)。これで段階3 のゲートが開く

## 2026-09-25 Claude(Cowork)— 段階3 の進め方を決定: ファイルを動かさずに取り込む・スタジオ → cut2resolve → 文字起こし
- 変更: `docs/integration-plan.md`(決まっていること)
- 決定(ユーザー): 取り込み方式 = ファイルを動かさない(統合サーバーが各ツールの serve.py を別名で読み込む。git mv によるパッケージ化はしない)。順番 = スタジオ → cut2resolve → 文字起こし
- 理由: Claude(Cowork)は PC でファイルの移動・git ができない。移動しなければ旧起動方法もそのまま動き、git mv の競合も起きない。cut2resolve は小さく1プロセスでも安全、文字起こしはワーカー分離が要る最大の作業
- 注意: ツール間で同じ名前の Python モジュールを作らないこと(今は serve.py と e2e_ui.py だけが重なる)。段階3 でこれを検査するテストを足す
- 未完了・次: コミット(push.bat)→ 段階3 の1つ目(スタジオの取り込み)に着手

## 2026-09-25 Claude(Cowork)— 段階3-1: 切り抜きスタジオを入口に取り込み(入口 v0.2.0・スタジオ v0.3.0・ytt_core 1.1.0)
- 担当: 統合作業(Claude)。ゲート(cut2resolve 0.4.0 のコミット)は 7fc379f で通過を確認。作業の土台は HEAD = 7fc379f(PC の該当ファイルは HEAD と一致を確認)
- 決定(ユーザー): 取り込んだスタジオの場所は入口と同じアドレスの `/studio/`(http://localhost:8700/studio/)。友人の PC で Text+ の動作確認済み、本格的に統合を進める
- 変更(新規): `app/mount.py`(serve.py を別名 ytt_tool_studio で読み込み、/studio の下で Handler を包む・CSP・合言葉)、`app/test_mount.py`(11件)
- 変更: `app/launch.py`(要求の最初の行を覗いて振り分け・取り込み・合言葉・`--no-mount`・待ち受けを別スレッドに)、`app/portal.js`(合言葉・取り込みの表示・/studio/ へのリンク)、`app/README.txt`、
  `app/test_launch.py`・`app/e2e_portal.py`(スタジオを取り込んだ形で確認)。
  スタジオ: `serve.py`(`prepare()` / `finish()` に分けた・`BASE_PATH`・入口の中で動いていれば start.bat で2つ目を立てない)、`handoff.py`(場所つきの .runtime・siblings)、
  `core.js`(`Studio.base` を画面の場所から・書き込みに合言葉・siblings の paths)、`index.html`(部品を相対パスに)、`README.txt`、`e2e_ui.py`(`--mounted`)。
  `ytt_core/runtime.py`(.runtime の `path`・`<path>api/ping`・siblings の `paths`)、`ui-kit/ui-kit.js`(`UIKit.tools.setPaths`・場所つきのリンク。sync で各ツールへ)、
  文字起こし `index.html` と cut2resolve `app.js`(siblings の paths を ui-kit に渡す)、cut2resolve `serve.py`(siblings が場所を扱う)
- 版: スタジオ 0.2.0 → 0.3.0、入口 0.1.0 → 0.2.0、ytt_core 1.0.0 → 1.1.0。文字起こし・cut2resolve は版を上げていない(リンクの場所の対応だけ。動きは同じ)
- 確認(クラウド): スタジオ 単体7本・test_review.cjs・e2e_analyze・e2e_ui 70/70・**e2e_ui --mounted 70/70**(CSP・合言葉の下で画面のエラーなし)、
  文字起こし 単体・test_document_save・e2e 6本(v07・v09 は想定内の「版 v0.9.4」だけ)、cut2resolve 単体・e2e_ui、tools/e2e_pipeline、test_ui_kit_sync、
  ytt_core 29・app/test_launch 30・app/test_mount 11・e2e_portal すべて OK。ミューテーション 9件中 7件を検出(残り2件は二重の守りの片方で、もう一方が同じことを守っている)
- 未確認(実機): Windows での取り込み(start-all.bat → /studio/ が開くか・スタジオの解析と書き出し・YouTube の埋め込みが CSP の下で動くか・「すべて終了」で .runtime が消えるか)、
  入口の中で動いている間の start.bat の二重起動防止
- 注意: 取り込んだ画面では、インラインのスクリプト・`onclick=` は CSP で動かない。スタジオの画面を変えたら `e2e_ui.py --mounted` も通す。
  起動中のスタジオ・入口は古いコードのまま動いているので、入口を「すべて終了」してから start-all.bat で起動し直す。未コミット
- 未完了・次: 段階3-2(cut2resolve の取り込み)

## 2026-09-25 Claude(Cowork)— 段階3-2: cut2resolve を入口に取り込み(入口 v0.3.0・cut2resolve v0.5.0)
- 担当: 統合作業・cut2resolve(Claude)。作業の土台は HEAD = de5cf80(段階3-1 を含む。PC の該当ファイルは HEAD と一致を確認)
- 変更: `app/mount.py`(MOUNTS に cut2resolve。csp=None はツール自身の CSP を使い、インラインを許す CSP なら取り込まない)、`app/launch.py`(版だけ)、
  `app/test_mount.py`(cut2resolve の取り込み 7件: 画面・CSP・合言葉・Host/Origin・/media の Range・.runtime と siblings・start.bat の二重起動防止・終了時のジョブ取り消し)、
  `app/e2e_portal.py`(スタジオと cut2resolve を取り込んだ形。停止・異常終了の確認は子プロセスで動く文字起こしで)、`app/README.txt`。
  cut2resolve: `serve.py`(`prepare()` / `finish()` / `busy()` / `mounted_elsewhere()`・`Handler.ctx`・`.runtime` の path・siblings の self_path)、
  `app.js`(`BASE` を画面の場所から・書き込みに合言葉)、`index.html`(部品を相対パスに)、`e2e_ui.py`(`--mounted`: 本物の入口を起動して通す)、`test_serve.py`、`cut2resolve_core.py`(版)、`README.txt`。
  `docs/integration-plan.md`(「段階3-2で決めたこと」)、`AGENTS.md`
- 版: cut2resolve 0.4.0 → 0.5.0、入口 0.2.0 → 0.3.0。スタジオ・文字起こし・ytt_core は変えていない
- 確認(クラウド): cut2resolve test_serve・test_cut2resolve・test_pack・e2e_ui・**e2e_ui --mounted**(CSP 違反を含む画面のエラーなし・終了で .runtime が消える)、
  app/test_launch・test_mount 18・e2e_portal、ytt_core、tools/e2e_pipeline・test_ui_kit_sync、スタジオ 単体・e2e_ui --mounted 70/70 すべて OK。
  ミューテーション 3件(合言葉を付けない・.runtime に path を書かない・終了で取り消さない)はすべて検出
- 未確認(実機): Windows で start-all.bat → /cut2resolve/ で 読み込み・試算・パック作成(Text+)・「フォルダを開く」・プレビューの動画、「すべて終了」、入口の中で動いている間の cut2resolve の start.bat
- 注意: 入口の中の cut2resolve は、入力欄の前回の値(ブラウザの保存)が単独のときと別になる。起動中の入口は古いコードのままなので「すべて終了」→ start-all.bat で起動し直す。未コミット
- 未完了・次: 段階3-3(文字起こしの取り込み。faster-whisper は別プロセスのワーカー)。Resolve パックの一本化(契約テストが先)

## 2026-09-25 Claude(Cowork)— 段階3-3: 文字起こしの認識を別プロセスに分け、入口に取り込み(文字起こし v0.11.0・入口 v0.4.0)
- 担当: 統合作業(Claude)。文字起こしツールも統合のために変更(GPT は WORKLOG を見てから触る)。作業の土台は HEAD = 21f7ff4(段階3-2 を含む)
- 決定(ユーザー): ワーカー分離と取り込みを一度に行う。作業は AI モデルを使い分け(設計・ワーカー = Opus、画面の JS 分離・画面のテスト = Sonnet)
- 変更(新規): `transcribe-tool/tx_worker.py`(認識ワーカー)、`transcribe-tool/app.js`・`ui-kit.js`(index.html のインラインの JS を外へ)、
  `transcribe-tool/test_worker.py`(17件。test_metrics から読み込む)、`transcribe-tool/e2e_ui_mounted.py`(本物の入口に取り込んだ形で画面を通す・ワーカーの強制終了からの立ち直り)
- 変更: 文字起こし `serve.py`(`WorkerClient`・`RemoteModel`・`WavRef`・`load_model`/`diarize_real`/`gpu_ready` をワーカー経由に・本体は `_load_model_local`/`_diarize_local`・
  `prepare()`/`finish()`/`busy()`/`mounted_elsewhere()`・`BASE_PATH`・`/app.js`・`/ui-kit.js` の配信・起動時の版の確認は app.js・extract_audio のパイプを閉じる)、
  `pipeline_io.py`(.runtime の path・siblings の self_path)、`index.html`、`test_backend.py`・`test_metrics.py`・`test_document_save.cjs`・e2e 6本(写すファイルに app.js・ui-kit.js・tx_worker.py)、
  `README.txt`・`AGENTS.md`。`app/mount.py`(MOUNTS に transcribe)、`app/launch.py`(版)、`app/test_mount.py`(文字起こしの取り込み 6件: ワーカーが落ちても入口・スタジオは止まらない など)、
  `app/e2e_portal.py`(A: 3つとも取り込んだ本番の形 / B: 文字起こしを子プロセスにした形で停止・再起動・異常終了)、`app/README.txt`。
  `tools/sync_ui_kit.py`(文字起こしも ui-kit.js をファイルで写す。CSS は埋め込みのまま)、`tools/e2e_pipeline.py`。`AGENTS.md`・`docs/integration-plan.md`(「段階3-3で決めたこと」)
- 版: 文字起こし 0.10.0 → 0.11.0(APP_VERSION は app.js へ移動)、入口 0.3.0 → 0.4.0。スタジオ・cut2resolve・ytt_core は変えていない
- 確認(クラウド): 文字起こし 単体97件(test_worker 17件を含む)・node 9件・e2e v07/v08/v09/eval_v093/v098/handoff/**mounted**(v07・v09 は想定内の「版 v0.9.4」だけ)、
  app/test_launch・test_mount 24件・e2e_portal(A・B)、ytt_core、tools/e2e_pipeline・test_ui_kit_sync、スタジオ 単体・e2e_ui 70/70・--mounted 70/70、cut2resolve 単体・e2e_ui・--mounted すべて OK。
  ミューテーション 5件(サーバー側で numpy を読み込む・強制終了を中止にしない・fd の付け替えをしない・取り消し済みでも要求を送る・途中経過の値を制限しない)はすべて検出
- 未確認(実機・重要): **本物の faster-whisper での文字起こし**(クラウドは PyPI に届かず、ワーカーの中は偽のモデルで確認)。Windows で start-all.bat → /transcribe/ で
  文字起こし・再認識・話者判別・取り消し・「すべて終了」、単独の start.bat でも同じ、worker.log の中身、タスクマネージャーで python が2つ(入口とワーカー)になり、15分後にワーカーが消えること
- 注意: 画面の JS は app.js に移った(index.html を直しても JS は変わらない)。サーバー側で numpy・faster_whisper・ctranslate2・sherpa_onnx を import しない(test_worker が検査)。
  起動中の入口・文字起こしは古いコードのままなので「すべて終了」→ start-all.bat で起動し直す。未コミット
- 未完了・次: 実機確認。Resolve パックの一本化(契約テストが先)。段階4(作業データをリポジトリの外へ)

## 2026-09-26 Claude(Cowork)— フォルダ構成と AGENTS.md の見直し(文書の直し・docs の整理・不要ファイルの整理)
- 見直し案: claude.ai の Claude Docs「フォルダ構成と AGENTS.md の見直し案」(2026-09-25)。この記録はその決定分の実施
- 決定(ユーザー 2026-09-26):
  - **資料の正本はこのリポジトリ**。claude.ai の Project の `claude/*.md` は古い写しとして扱う(統合計画だけは従来どおり Claude Docs が正本)
  - docs の移動: 版ごとの記録 → `docs/project/history/`、精度の資料 → `docs/accuracy/`。NEXT_TASKS.md は削除
  - 削除: 無人実行の bat 3本(auto-next / run-next / schedule-next)と auto-next.log、docs/NEXT_TASKS.md、cut2resolve の音割れ調査用の資料(exports/ の中)、cut2resolve のシンプル版(使っていない)
  - cut2resolve の Text+ の担当(「数日」)は統合作業の担当に含める(cut2resolve 全体を Claude が主担当)
  - 採用しなかった: WORKLOG の月ごとの分割、push.bat のコミットメッセージを WORKLOG の見出しにする案(→ AGENTS.md のコミットの決まりを実態に合わせた)
- 変更:
  - `AGENTS.md` を並べ替え・実態に合わせて直した(ルールは削っていない): 最初にやること / 全体の形(入口が3ツールを取り込む・認識ワーカー)/ フォルダと変えたら通すテストの表 /
    資料の場所(正本・`docs/project/` は古い経緯)/ コミットの決まりを push.bat の実態に / WORKLOG に「未コミット」を書く / Cowork の注意(書いたら読み直す)/
    ワーカー分離を【高】リスクから「取り込みの決まり」へ / 担当表 / Python が2つある可能性
  - `transcribe-tool/AGENTS.md`: NEXT_TASKS と `_recovered/` の記述を削除、仕様書の場所と「古い」ことを明記、SyntaxError を「過去の事例」に
  - `docs/project/README.md`: 「経緯の資料(古い)」として書き直し、一覧を付けた
  - `cut2resolve/test_cut2resolve.py`: シンプル版のテスト3件をフル版(`cut2resolve.py 動画 カットリスト [字幕]`)の同じ使い方に移した(CRLF・BOM なし・上書きの保護・字幕なし・範囲外・埋め込みタイムコード)。`cut2resolve/README.txt` の手順も差し替え
  - `tools/baseline_analysis.py`: 既定の出力先を `docs/accuracy/` に
  - 新しい場所に書いたファイル(中身は元と同じ。accuracy の2本はリンクだけ直した): `docs/project/history/transcribe-tool-v0.7.1〜v0.9.4.md`(8本)、`docs/accuracy/accuracy-baseline.json`・`accuracy-baseline.md`・`USER_INPUT.md`
- 版: 変えていない(cut2resolve は画面・サーバーの動きが変わらないため)
- 確認(クラウド。シンプル版を消した状態): cut2resolve test_cut2resolve 120・test_pack・test_serve(計197)OK、スタジオ 単体215 OK、ytt_core・test_ui_kit_sync OK、app/test_mount OK
- **ユーザーか git を使える AI にお願い(Cowork は削除できない)**: 次を消してから push.bat(push.bat の `git add -A` で移動・削除として記録される)
  - 移動の元(新しい場所に同じ内容あり): `docs/project/transcribe-tool-v0.7.1.md`・`v0.8.0`・`v0.8.1`・`v0.8.2`・`v0.8.3`・`v0.9.0`・`v0.9.2`・`v0.9.4`(8本)、`docs/accuracy-baseline.json`、`docs/accuracy-baseline.md`、`docs/USER_INPUT.md`
  - 削除: `docs/NEXT_TASKS.md`、`auto-next.bat`、`run-next.bat`、`schedule-next.bat`、`auto-next.log`、`cut2resolve/cut2resolve_simple.py`、`cut2resolve/cut2resolve_simple.bat`
  - 削除(git の対象外・約110MB): `cut2resolve/exports/` の中の `audio_bisect_20260925`・`audio_diag_20260925`・`audio_diag2_20260925`・`settings_dump_20260925`・`vertical_scale_test_20260925`(フォルダ)と `AUDIO_DIAG_MANUAL.mov`
  - Windows のタスクスケジューラに `youtube-tools-auto-next` が残っていれば削除(schedule-next.bat が登録したもの)
- 未コミット: 段階3-3 の29ファイル(上の記録)+ 今回の AGENTS.md・transcribe-tool/AGENTS.md・docs/WORKLOG.md・docs/project/README.md・cut2resolve/README.txt・cut2resolve/test_cut2resolve.py・tools/baseline_analysis.py と新しい場所の11ファイル。
  ユーザーの判断で 3-3 と同じコミットにまとめる
- 未完了・次: 上の削除 → 3-3 の実機確認 → push.bat。claude.ai の Project の `claude/*.md` の扱い(古い写しを消して「リポジトリを見て」の1枚にするか)はユーザーに確認中
- 注意: `docs/project/HANDOVER-transcribe-tool.md` などの古い資料には NEXT_TASKS.md への参照が残るが、経緯の資料なので直していない

## 2026-09-26 Claude(Cowork)— claude.ai の Project の古い写し(claude/*.md)を片付け
- 決定(ユーザーが Claude に一任): 資料の正本はリポジトリなので、Project の古い写しは消し、Project には「リポジトリを見て」の案内1枚と統合計画の要約だけを残す
- 変更: Project にしか無かった3本をリポジトリへ写した: `docs/project/summary-2026-09-24.md`・`summary-2026-09-25.md`・`new-tool-plan.md`。`docs/project/README.md` の一覧に追加
- Project 側: `claude/README.md`(新規。リポジトリの場所・読む順・今の状態)を書き、`claude/integration-plan.md` は残し、ほかの `claude/*.md` は削除。
  削除したものは、2026-09-24 にリポジトリの `docs/project/`・`docs/pipeline.md`・`docs/review/README.md` へ写した後で Project 側が更新されていないことを確かめた(作成日時と中身の抜き取り確認)
- 注意: `claude/integration-plan.md` も写し(正本は Claude Docs「動画編集ツール 統合計画」)。古くなったら `docs/integration-plan.md` から写し直す
- 未コミット: 上の3本と `docs/project/README.md`・`docs/WORKLOG.md`(前の記録の未コミット分と一緒に push.bat で)

## 2026-09-26 Claude(Cowork)— push.bat の「衝突しました」は接続の失敗だった・push.bat を直した
- 状況: 09-26 0:47 の push.bat で commit(3b5712e「更新 2026/09/26 0:47」)はできたが、`git pull --rebase` が失敗して「衝突しました」と表示。
  調べた結果: GitHub の main は 21f7ff4 のままで新しい変更は無く、`.git/FETCH_HEAD` が空・rebase の途中の状態も無い → GitHub への接続(ネットワークかログイン)に失敗しただけで、衝突ではない。
  コミットは PC に残っていて、GitHub より1件進んでいる
- 前の push.bat の問題: ① pull の失敗を全部「衝突」と表示していた ② 新しい変更が無いと「保存する変更はありません」で終わるので、送れずに残ったコミットを送れなかった
- 変更: `push.bat` — 取り込みを fetch と rebase に分け、接続できないとき・衝突のとき・push の失敗を別々に表示。新しい変更が無くても GitHub より進んでいれば送る。
  衝突したら `git rebase --abort` で取り込みを取り消す(途中の状態で止めない)。コミットメッセージは前と同じ「更新 日付 時刻」
- 確認: Windows の cmd で動かしてはいない(クラウドに cmd が無い)。次にユーザーが push.bat を実行したときに確かめる
- 注意: GPT(Codex)が 09-25 23:24〜23:56 にこのフォルダで作業した跡(.git/refs/codex/turn-diffs)があるが、その時間に変わったファイルは見当たらず、WORKLOG にも記録が無い
- 未コミット: push.bat・docs/WORKLOG.md(次の push.bat でまとめて保存される)。`run-next.bat` が消し残っている(消してよい)
- 追記(同日): 直した push.bat を実行すると、日本語の長い echo の行の途中が別のコマンドとして実行された(`'…、もう一度' is not recognized`)。
  `chcp 65001` の下で cmd が UTF-8 の行を読み違える既知の問題。push.bat を **ASCII だけ**(英語の表示)に書き直した(start-all.bat と同じ方針)。
  コミットメッセージも「update 日付 時刻」になる。`git fetch` は -q を外し、失敗したときに git 自身のエラーが見えるようにした。
  接続できない原因はまだ不明(GitHub は動いている。クラウドからは `git ls-remote` で 21f7ff4 が見える)
- 原因が分かった(同日): 接続の問題ではなく、GPT(Codex)がこのリポジトリに作った「turn の差分の控え」の参照
  `.git/refs/codex/turn-diffs/checkpoints/…`(09-25 23:24〜23:56 の3つ)が、存在しないコミットを指していた。
  `git fetch` は手元の参照をすべて確かめるので `fatal: bad object refs/codex/…` → `did not send all necessary objects` で止まる。
  対処: `.git\refs\codex` フォルダを消す(Codex の過去の turn を元に戻す機能の控えが消えるだけで、コード・履歴には影響しない)。Cowork は削除できないのでユーザーが実行。
  **GPT(Codex)へ**: このフォルダで作業すると、また壊れた参照が残る可能性がある。push.bat が `bad object refs/codex/…` で止まったら同じ対処

## 2026-09-26 Claude(Cowork)— GitHub へ送信完了・段階3-3 の実機確認済み・セッション切り替え
- push: `.git\refs\codex` を消した後の push.bat で送信できた(21f7ff4 → dac1b89。0:47〜0:57 のコミット5件・54ファイル。個人データ・設定ファイルは含まれていないことを確認)
- **段階3-3 の実機確認: 済(ユーザー報告 2026-09-26)**。Windows で入口から /transcribe/ を使い、本物の faster-whisper で確認
- 引き継ぎ: `docs/HANDOVER.md`(今の状態・次の作業・注意)。次の作業は Resolve パックの一本化(契約テストが先)
- 未コミット: docs/WORKLOG.md・docs/HANDOVER.md(次の push.bat で)
- 未反映: 統合計画の正本(Claude Docs「動画編集ツール 統合計画」)と写し `docs/integration-plan.md` の 3-3 の状態を「実機確認済み」にする(正本を先に直す)

## 2026-09-26 Claude(Cowork)— Resolve パックの一本化(契約テスト → pack.py に寄せる)・余白つき素材を cut2resolve でも(文字起こし v0.12.0・cut2resolve v0.6.0)
- 担当: 統合作業・cut2resolve(Claude)。文字起こしは resolve_export.py・serve.py の /api/resolve-package・app.js の Resolve の欄・README・AGENTS.md だけを変えた。
  作業の土台は GitHub の main = 928c3b1(PC の作業フォルダに 928c3b1 より新しい変更が無いことを、ファイルの更新日時で確認)
- 決定(ユーザー 2026-09-26): 一本化の形は「機能が壊れないことを前提に Claude に任せる」。スタジオの余白つき素材(.edit.json)は cut2resolve でも使えるようにする
- 進め方: ① 先に契約テスト `tools/test_resolve_pack_contract.py` を書いて緑に(旧 resolve_export.build_plan と pack.plan_cut を同じ文字起こしで比べた)。
  普通の入力では一致し、食い違いはすべて旧 resolve_export の不具合だった(下)。緑にするまでに cut2resolve 側で直したのは丸めだけ。
  ② 文字起こしの「Resolveパッケージ(zip)」を、pack.py の Text+ パックを zip にするだけの形に寄せた。旧の計算はテストの中に凍結(LEGACY。旧コードと 932 件で一致を確認)して、前後で同じ区間・字幕・SRT になることを守る
- 変更(cut2resolve): `srt2resolve.py`(`round_half_up`。ms_to_frames・frames_to_ms を四捨五入に。以前は Python の round = 偶数への丸めで、30fps の 0.15 秒が 4 フレーム・0.25 秒が 8 フレームと上下ばらばら)、
  `cut2resolve_core.py`(`find_edit_media`・`_sec_to_ms`・write_pack の `stem`・版)、`pack.py`(`TRANSCRIPT_ROWS`・`Request.join_frames`・`Request.edit_media`・`edit_media_path`・`media_for_pack`・
  build_pack が余白つき素材を同梱して区間をずらす・結果に `editMedia`・`mediaKeeps`)、`serve.py`(上書きの下見に余白つき素材の名前・結果に editMedia)、`cut2resolve.py`(`--no-edit-media`)、`test_pack.py`(+7件)、`README.txt`
- 変更(文字起こし): `resolve_export.py`(create_package は 文書 → transcript/v1 → pack.plan_cut(TRANSCRIPT_ROWS) → build_pack(textplus) → zip。旧の計算・Python の取り込みスクリプト・FCPXML は削除。
  is_kept・kept_spans・srt_text は残す)、`serve.py`(size・版を渡す・ヘッダー)、`app.js`(fps を 24/25/30/50/60・縦/横の選択・案内の文)、`test_resolve_export.py`(作り直し。HTTP も)、
  `e2e_ui_mounted.py`(画面から zip をダウンロードして中身を確認)、`README.txt`・`AGENTS.md`
- 変更(その他): `tools/test_resolve_pack_contract.py`(新規)、`docs/resolve-pack-unification.md`(新規。経緯・旧との違い・zip の中身の変化)、`app/e2e_portal.py`(文字起こしの版)、`AGENTS.md`(【高】リスクを「済み・以後は pack.py だけ」に・テストの表)、`docs/integration-plan.md`
- 版: 文字起こし 0.11.0 → 0.12.0、cut2resolve 0.5.0 → 0.6.0。入口・スタジオ・ytt_core は変えていない
- 旧 resolve_export の不具合で、今回直ったもの: ① 60fps の動画で FPS に 30 を選ぶと、カットが半分の時刻にずれた(選んだ fps でフレームを数えていた)
  ② 動画の終わりをまたぐ行の字幕を捨てた ③ 時刻順でない行で SRT の番号が時刻順にならない ④ 半フレームの時刻が float の誤差で1フレームずれる ⑤ 動画の終わりを1フレーム超えることがある
- zip の中身の変化: Resolve 側は Python(新しいプロジェクトを作る。実機確認の記録なし)→ Lua(開いているプロジェクトに足すだけ。友人の PC で確認済み)。
  FCPXML → EDL。はじめに.txt → 友人へ.txt。zip の直下 → `<題名>_pack/` フォルダ1つ。CUT_TextPlus・SOURCE_WITH_HANDLES・余白つき素材・SRT は同じ
- 確認(クラウド): 契約テスト 23件、cut2resolve 単体 211・e2e_ui・--mounted、文字起こし 単体 101(test_resolve_export 10 を含む)・node 9・e2e v098/handoff/mounted/v08/eval_v093
  (v07・v09 は想定内の「版 v0.9.4」だけ)、app/test_launch・test_mount 54・e2e_portal、ytt_core・test_ui_kit_sync、tools/e2e_pipeline すべて OK。
  入口に3つとも取り込んだ形で /transcribe/api/resolve-package が zip を返すこと(cut2resolve の部品を共有)も確認。
  ミューテーション: 丸めを偶数への丸めに戻す・最短 0.3 秒・隙間をつながない・余白の分をずらさない・文字起こし側が別の規則で呼ぶ、はすべて検出
- 未確認(実機): 文字起こし画面の「Resolveパッケージ(zip)」→ 展開 → 友人へ.txt の手順で Resolve に取り込めるか。余白つき素材ありでクリップの端を延ばせるか。cut2resolve の Text+ パックでも同じ
- 注意: zip を作る間、一時フォルダに動画のコピーと zip の2つ分を使う(旧は1つ分)。文字起こし側に Resolve 用の計算を書き足さない(二重実装に戻さない)。
  起動中の入口・ツールは古いコードのままなので「すべて終了」→ start-all.bat で起動し直す
- 未完了・次: cut2resolve の `.runtime`・siblings を ytt_core に切り替える(HANDOVER の1に一緒に書いてあったが今回はしていない)。段階4(作業データをリポジトリの外へ。場所は未決)
- 未コミット: 上の変更すべて(AGENTS.md・app/e2e_portal.py・cut2resolve/{README.txt,cut2resolve.py,cut2resolve_core.py,pack.py,serve.py,srt2resolve.py,test_pack.py}・
  docs/{integration-plan.md,resolve-pack-unification.md,WORKLOG.md,HANDOVER.md}・tools/test_resolve_pack_contract.py・
  transcribe-tool/{AGENTS.md,README.txt,app.js,e2e_ui_mounted.py,resolve_export.py,serve.py,test_resolve_export.py})。push.bat で

## 2026-09-26 Claude(Cowork)— cut2resolve を ytt_core に切り替え・段階4 の1つ目: 作業データをリポジトリの外へ(スタジオ v0.4.0・文字起こし v0.13.0・cut2resolve v0.7.0・入口 v0.5.0)
- 担当: 統合作業(Claude)。スタジオ・文字起こしも置き場所のために変更(serve.py の起動処理・README・テストの先頭1行)。作業の土台は GitHub の main = fd6686c(Resolve パックの一本化を含む)
- 確認(ユーザー 2026-09-26): 前回のお願い(push.bat・一本化の実機確認)は「できた」。**以後、10〜20 分ごとに中間報告する**(AGENTS.md の「ユーザーについて」に追記)
- 決定(ユーザー 2026-09-26): 作業データの置き場所 = `%LOCALAPPDATA%\youtube-tools\<ツールID>\`、範囲 = 全部(データ・設定・キャッシュ・ログ・話者判別のモデル・入口の記録)。移行はコピーで元は残す(統合計画の決まりどおり)
- 変更(cut2resolve を ytt_core に): `cut2resolve/serve.py` の .runtime・siblings・Host/Origin/Sec-Fetch の検査・probe を ytt_core(runtime・httpsec)を呼ぶ薄い包みに(約80行の重複を削除。関数名はそのまま)。
  画面(serve.py)は隣に ytt_core が要る(CLI の cut2resolve.py は単体で動く)。`test_serve.py` に ytt_core を使うことの確認、`ytt_core/test_ytt_core.py` の「写しを持つ」前提のテストを「写しを持たない」確認に
- 変更(段階4): `ytt_core/datadir.py`(新規。置き場所の決定・項目ごとに一時名へコピー → 大きさと数を確認 → 改名・既存は上書きしない・空き容量不足/失敗なら以前の場所のまま・.migrated.json)、
  スタジオ `serve.py`(`_data_home`・以前の既定の exports を使い続ける・/api/state に dataDir。テストや入口が先に決めた場所は上書きしない)、
  文字起こし `serve.py`(`DATA_DIR`・`set_data_dir`・`choose_data_dir`・ワーカーへ TRANSCRIBE_DATA_DIR・スタジオの data.json を新しい場所から読む `studio_data_path`)、
  cut2resolve `serve.py`(`_choose_work_dir`・ログの場所の表示)、入口 `launch.py`(`logs_dir_for`・/api/status に dataDir)・`portal.html`・`portal.js`(置き場所とパスのコピー)、
  テスト・e2e 28ファイルの先頭に `os.environ.setdefault("YTT_DATA_DIR", "inplace")`、`ytt_core/test_ytt_core.py`(TestDatadir 11件。忘れたテストを落とす検査を含む)、
  `clip-studio/test_robustness.py`(TestDataHome 3件)、`tools/e2e_datadir.py`(新規。本物の入口で移行を通し確認 15項目)、
  資料: `docs/data-location.md`(新規)・`docs/pipeline.md`・`docs/integration-plan.md`・`AGENTS.md`・各 README
- 版: スタジオ 0.3.0 → 0.4.0、文字起こし 0.12.0 → 0.13.0、cut2resolve 0.6.0 → 0.7.0、入口 0.4.0 → 0.5.0(`app/e2e_portal.py` の版も)
- 確認(クラウド): スタジオ 単体 218・test_review.cjs・e2e_analyze・e2e_ui 70/70・--mounted 70/70、文字起こし 単体 101・node 9・e2e v098/handoff/mounted/v08/eval_v093(v07・v09 は想定内の「版 v0.9.4」だけ)、
  cut2resolve 単体 213・e2e_ui・--mounted、入口 54・e2e_portal、ytt_core・契約テスト・test_ui_kit_sync、tools/e2e_pipeline・**e2e_datadir** すべて OK。
  全部のテストのあと、本物の置き場所(~/.local/share/youtube-tools)が作られていないことも確認
- テストで見つけて直した不具合: 入口の中のスタジオが、テスト・入口が先に決めた置き場所(STUDIO_HOME)を上書きしていた(既定のときだけ切り替えるように)
- 未確認(実機): Windows で「すべて終了」→ start-all.bat → 最初の起動でコピーされるか(スタジオの cache 約2.2GB。数十秒かかる見込み)、
  入口の画面の「作業データの置き場所」、3ツールで以前のデータ(マーク・文字起こし・設定・API キー)が見えるか、2回目の起動で写し直さないか
- 注意: **サーバーを動かすテストは先頭で YTT_DATA_DIR=inplace**(忘れると移し済みの PC で本物の作業データを読み書きする。検査あり)。
  契約テストは `app/test_mount.py` と同じ unittest に渡さない(部品の名前が重なって落ちる。単独で実行)。
  以前の場所のデータ(clip-studio の data.json・cache など、transcribe-tool の transcripts・dataset など、cut2resolve\work、app\logs)は、新しい場所で確かめてから消す(Cowork は消せない)
- 未完了・次: 実機確認 → 以前の場所のデータの削除の案内。段階4 の残り(案件ごとの紐づけ・同時実行の上限・文字起こしをスタジオへ返す)。`0old`・`.whisper_models` の扱いはユーザーが決める
- 未コミット: 上の変更すべて(新規 3: ytt_core/datadir.py・tools/e2e_datadir.py・docs/data-location.md、変更 46 ファイル + docs/WORKLOG.md・docs/HANDOVER.md)。push.bat で

## 2026-09-26 Claude(Cowork)— 移行の確認と、以前の場所の片付けスクリプト
- 確認(PC。AppData は読み取りで): push(af3487a)済み。`%LOCALAPPDATA%\youtube-tools\` に studio・transcribe・cut2resolve・app があり、studio・transcribe・cut2resolve に .migrated.json(09-26 2:15。コピーは約4秒)。
  文字起こしの transcripts 91・dataset 455・models 3 は以前の場所と大きさ・数が一致、スタジオの cache 107 件(約2.2GB)・archive 25 件・data.json・config.json もそろっている。移行後は以前の場所のログが更新されていない(新しい場所だけが使われている)
- 変更(新規): `tools/cleanup_legacy_data.py`(以前の場所の作業データを、確かめてからごみ箱へ。一覧と大きさを見せて y で実行・--dry-run・ツールが動いていれば何もしない)、
  `tools/cleanup_legacy_data.bat`(ダブルクリック用。ASCII)、`tools/test_cleanup_legacy_data.py`(9件。片付ける一覧が各 serve.py の DATA_ITEMS と同じことも検査)
- 変更: `docs/data-location.md`(片付けの節)、`AGENTS.md`(テストの表)、`start-all.bat`(エラー時の launcher.log の場所を新しい場所に)
- 消す条件: 写したデータは .migrated.json があり・写した元がこのリポジトリのフォルダ・写した一覧にある・新しい場所にも同じ名前がある。ログ・work は新しい場所が使われていれば。コードと cut2resolve の exports は触らない
- 未確認(実機): Windows のごみ箱へ移す処理(SHFileOperationW)は、クラウドでは動かせない(テストは一時フォルダへの移動で代用)。まず --dry-run で一覧を見てもらう
- 未コミット: tools/cleanup_legacy_data.py・tools/cleanup_legacy_data.bat・tools/test_cleanup_legacy_data.py・docs/data-location.md・AGENTS.md・start-all.bat・docs/WORKLOG.md・docs/HANDOVER.md(push.bat で)

## 2026-09-26 Claude(Cowork)— 段階4 の残り: 同時実行の上限・案件ファイル・文字起こしをスタジオへ返す(入口 v0.6.0・スタジオ v0.5.0・文字起こし v0.14.0・cut2resolve v0.8.0)
- 担当: 統合作業(Claude)。スタジオ・文字起こし・cut2resolve も変更(重い処理の順番待ち・セリフの表示)。作業の土台は GitHub の main = 6b8304d
- 確認(ユーザー 2026-09-26): `0old`・`.whisper_models` はユーザーが削除済み
- 決定(ユーザー 2026-09-26): 段階4 の残りとして「案件ファイルを持つ」「文字起こしをスタジオへ返す」「同時実行の上限」をこの順で(上限 → 案件 → セリフ)
- 変更(同時実行の上限): `ytt_core/jobs.py`(新規。`SLOTS` = 1つのプロセスの中で重い処理を順番どおりに2つまで。`YTT_MAX_HEAVY_JOBS` 1〜8。待っている間も中止できる)。
  スタジオ `batch.py`(解析)・`exporter.py`(書き出し。job に waiting)・`review.js`(順番待ちの表示)、文字起こし `serve.py`(work_one)、cut2resolve `serve.py`(パックの作成)、入口 `/api/status` に heavy
- 変更(案件ファイル): `app/cases.py`(新規。紐づけを開くたびに組み立て直す・`cases.json` に状態・メモ・最後に見えた紐づけ)、`app/cases.html`・`app/cases.js`(新規。CSP の下・textContent だけ)、
  `app/launch.py`(`GET /api/cases`・`POST /api/cases/update`。書き込みは合言葉つき)、`app/portal.html`(案件へのリンク)・`app/portal.css`
- 変更(セリフ): `ytt_core/txindex.py`(新規。文字起こしの文書の読み取り(更新日時・大きさでキャッシュ)・紐づけの規則・元の配信の時刻へのずれ。案件と共通)、
  `clip-studio/txlink.py`(新規)・`serve.py`(`GET /api/transcripts?id=`)・`review.js`(書き出し済みのマークに「セリフ」。行を押すとその行を再生・開閉を覚える・タブに戻ると読み直す)・`review.css`
- テスト: `ytt_core/test_ytt_core.py`(TestHeavySlots 5・TestTxIndex 5)、`app/test_cases.py`(新規 6)、`app/e2e_portal.py`(案件の画面: 表示・状態の保存・読み込み直し)、
  スタジオ `test_api.py`(TestTranscripts)・`test_exporter.py`・`test_review.cjs`(セリフ 1)・`e2e_ui.py`(セリフ 7 項目)、文字起こし `test_backend.py`、cut2resolve `test_serve.py`(各 TestHeavyJobLimit)
- 資料: `docs/data-location.md`(案件ファイル)・`docs/integration-plan.md`(段階4で決めたこと)・`AGENTS.md`・各 README。統合計画の正本(Claude Docs)も更新済み
- 版: 入口 0.5.0 → 0.6.0、スタジオ 0.4.0 → 0.5.0、文字起こし 0.13.0 → 0.14.0、cut2resolve 0.7.0 → 0.8.0(`app/e2e_portal.py` の版も)
- 判断・理由: 案件の紐づけを保存せず毎回組み立て直すのは、各ツールが持つ記録(マーク・文字起こし)と食い違わないため。紐づけの規則を ytt_core/txindex.py の1か所にしたのは、
  案件の画面とスタジオで別々に書くと片方だけ直して食い違うため。上限は種類ごとではなく全体で2(単純さ優先。困る場面が出たら種類ごとに)
- 注意: 新しく重い処理(ffmpeg・認識など)を足すときは `ytt_core.jobs.SLOTS.slot(...)` を通す。他のツールのデータは読むだけ(書き換えない)。
  セリフの時刻は .clip.json が無いとマークの開始に合わせる(高速書き出しは数秒ずれる。画面に注記)。ネットワーク上のパスの .clip.json は読まない
- 未確認(実機): 入口の「案件」の画面に今の配信・切り抜き・文字起こしが正しく並ぶか、状態・メモの保存、スタジオの ③ でセリフが出て時刻が合うか、
  2つより多く重い処理を始めたときの順番待ちの表示
- 未完了・次: 実機確認。段階5(一括実行・新着配信の監視・ラウドネス調整)は未着手
- 未コミット: 新規 7(ytt_core/jobs.py・ytt_core/txindex.py・app/cases.py・app/cases.html・app/cases.js・app/test_cases.py・clip-studio/txlink.py)、
  変更 30(AGENTS.md・app/{README.txt,e2e_portal.py,launch.py,portal.css,portal.html}・
  clip-studio/{README.txt,batch.py,core.js,e2e_ui.py,exporter.py,review.css,review.js,serve.py,test_api.py,test_exporter.py,test_review.cjs}・
  cut2resolve/{README.txt,cut2resolve_core.py,serve.py,test_serve.py}・docs/{HANDOVER.md,WORKLOG.md,data-location.md,integration-plan.md}・
  transcribe-tool/{README.txt,app.js,serve.py,test_backend.py}・ytt_core/test_ytt_core.py)。push.bat で

## 2026-09-26 Claude(Cowork)— 文字起こしの古い画面テスト2本の版の確認を直す
- 担当: 文字起こしのテストだけ(Claude。ツール本体は変えていない)
- 変更: `transcribe-tool/e2e_ui_v07.py`・`e2e_ui_v09.py` の「画面の版が v0.9.4」という固定の確認を、`app.js` の `APP_VERSION` を読んで比べる形に(`app_version()`)
- 理由: v0.9.4 より後は毎回この1項目だけ FAIL になり(「想定内」として扱っていた)、「SOME FAILED」が常に出ると本物の失敗を見落とすため。版を上げるたびにテストを書き換えなくて済む
- 確認(クラウド): 2本とも ALL PASSED(v0.14.0)
- 未コミット: transcribe-tool/e2e_ui_v07.py・transcribe-tool/e2e_ui_v09.py・docs/WORKLOG.md(直前の記録の未コミット分と一緒に push.bat で)

## 2026-09-26 Claude(Cowork)— 保留: 書き出し中にブラウザのタブが STATUS_ACCESS_VIOLATION で落ちた(ユーザー判断で一旦放置)
- 起きたこと(ユーザー報告・ログから): 入口 v0.6.0 で起動後、13:31:51 にスタジオで書き出し(配信 CEo1T9NzynY)。13:32:15〜13:32:44 に画面からのアクセスが途切れ、読み直されている(この間にタブが落ちたとみられる)
- サーバー側は正常: 入口・3ツールのログにエラーなし、書き出しは 13:32:57 に完了し data.json も保存済み
- 見立て(未確認): ブラウザ本体のクラッシュ。書き出し中(ffmpeg が CPU を使い切る)に YouTube の埋め込みを再生していた可能性。GPU(AMD)のドライバーとハードウェアアクセラレーション、拡張機能・セキュリティソフトの相性が典型。
  今回のセリフ表示(review.js)が引き金の可能性も1回では否定できない
- 未完了・次: 再現したら、どのブラウザ・どの画面・YouTube を再生中だったかを聞く → ハードウェアアクセラレーションをオフ → 拡張機能なしのシークレットウィンドウ、の順で切り分け
- 未コミット: docs/WORKLOG.md(前の記録の未コミット分と一緒に push.bat で)

## 2026-09-26 Claude(Cowork)— 段階5・6: まとめて実行・ラウドネス調整・コミット前の検査・単独起動の廃止・README の一本化(入口 v0.7.0・スタジオ v0.6.0・文字起こし v0.14.1・cut2resolve v0.9.0)
- 担当: 統合作業(Claude)。スタジオ・文字起こし・cut2resolve も変更(ラウドネス・採用の API・起動の案内・preset)。作業の土台は GitHub の main = 98073c1
- 決定(ユーザー 2026-09-26): 新着配信の監視は保留。ツールごとの単独起動はやめる(起動ファイルは削除。削除も「code などを使って」行う)。画面の形(pywebview)は保留・現状維持。
  まとめて実行の範囲は「選べるようにする」、ラウドネスは「スタジオの書き出し時」
- 変更(コミット前の検査・削除の仕組み): `tools/push_helper.py`(新規。removals: tools/removals.txt のファイルを git rm(git が管理しているものだけ・.. や絶対パス・ワイルドカードは拒否)/
  check: コミットするファイルにキーの形・個人データの名前・作業データのフォルダ・動画・5MB 超があれば止める)、`tools/removals.txt`(新規)、`push.bat`(削除 → git add → 検査 の順)、`tools/test_push_helper.py`(新規 6)
- 変更(単独起動の廃止): 3ツールの start.bat・start.command を tools/removals.txt に載せた(**次の push.bat で git rm される**)。画面(core.js・文字起こし app.js・cut2resolve app.js)と install*.bat/.command の案内を start-all.bat に。
  serve.py の単独で動く部分(取り込めないときの子プロセス・テスト)は残した
- 変更(ラウドネス): スタジオ `exporter.py`(build_spec の loudness(-11/-14/-16/-18)、measure_loudness(loudnorm で測るだけ)、apply_loudness(切り抜きと編集用素材に同じ量・ピーク -1 dBTP と +20dB で上げ止め・無音は触らない)、
  .clip.json の export.loudness)、`review.js`(設定「音量のそろえ方」既定 -14・書き出しの行に結果)・`review.css`、`test_exporter.py`(TestLoudness 5)
- 変更(まとめて実行): `app/autorun.py`(新規。3つの形・各ツールの API を HTTP で順に呼ぶ・まだ無いものだけ作る・中止・順番待ち)、`app/launch.py`(GET /api/autorun・POST /api/autorun/start・/cancel。合言葉つき)、
  `app/cases.html`・`cases.js`・`portal.css`(各配信に形の選択・採用する数・実行・中止・段ごとの進み具合)、スタジオ `store.py`・`serve.py`(POST /api/video/adopt-top。学習の記録は書かない)、
  cut2resolve `serve.py`(spec の preset "transcript-rows" = pack.TRANSCRIPT_ROWS)、テスト `app/test_autorun.py`(新規 10)・`app/e2e_autorun.py`(新規。本物の3ツールで画面から「採用後を全部」→ Text+ パック、API で「解析から全部」)・
  スタジオ `test_api.py`(TestAdoptTop)・cut2resolve `test_serve.py`(preset)
- 変更(README の一本化): リポジトリ直下の `README.txt`(新規。全体の使い方)、各ツールの README の起動の節と変更点、`AGENTS.md`、`docs/integration-plan.md`(段階5・6で決めたこと)。統合計画の正本(Claude Docs)も更新
- 版: 入口 0.6.0 → 0.7.0、スタジオ 0.5.0 → 0.6.0、文字起こし 0.14.0 → 0.14.1、cut2resolve 0.8.0 → 0.9.0(`app/e2e_portal.py` の版も)
- 判断・理由: まとめて実行はツールの関数を直接呼ばず API を呼ぶ(画面と同じ検査・ジョブ管理・重い処理の順番待ちを通すため)。自動で採用したマークを feedback に入れないのは、機械の選択を人の判断として学習すると自己強化になるため。
  ラウドネスを切り抜きと編集用素材で別々に測らず同じ量をかけるのは、Resolve で差し替えたときに音量が変わらないようにするため。削除を removals.txt + push.bat にしたのは、Cowork が PC のファイルを消せず、git rm なら履歴から戻せるため
- 注意: まとめて実行の解析は既定の設定(解析の設定はブラウザの localStorage にしか無い)。実行の記録は入口のメモリだけ(入口を終えると消える)。自動で作ったパックの字幕は校正前。
  ラウドネスの既定を -14 にしたので、以前の「音量 75%」とは書き出しの音量が変わる(「そろえない」で以前と同じ)
- 未確認(実機): 案件の画面の「まとめて実行」(3つの形)・書き出しのラウドネス(実際の配信で聞こえ方がそろうか)・push.bat の削除と検査(Windows の cmd で)
- 未完了・次: 実機確認。保留: 新着配信の監視・画面の形(pywebview)・書き出し中のタブの STATUS_ACCESS_VIOLATION
- 未コミット: 新規 7(README.txt・app/autorun.py・app/e2e_autorun.py・app/test_autorun.py・tools/push_helper.py・tools/removals.txt・tools/test_push_helper.py)、
  変更 34(AGENTS.md・push.bat・app/{README.txt,cases.html,cases.js,e2e_portal.py,launch.py,mount.py,portal.css,test_mount.py}・
  clip-studio/{README.txt,core.js,exporter.py,review.css,review.js,serve.py,store.py,test_api.py,test_exporter.py}・cut2resolve/{README.txt,app.js,cut2resolve_core.py,serve.py,test_serve.py}・
  transcribe-tool/{README.txt,app.js,install.bat,install.command,install-diarize.bat,install-diarize.command,install-gpu.bat,serve.py}・docs/{integration-plan.md,WORKLOG.md,HANDOVER.md})、
  削除 6(push.bat が tools/removals.txt から git rm: clip-studio・cut2resolve・transcribe-tool の start.bat・start.command)。push.bat で

## 2026-09-26 Claude(Cowork)— 段階5・6 の実機確認(一部)と保留の記録・引き継ぎ
- 確認(PC のログ・GitHub): push(eef5e17)で 42 ファイルと start.bat・start.command 6本の削除が届いた(push.bat の removals と検査が Windows で動いた)。
  入口 v0.7.0・スタジオ 0.6.0・文字起こし 0.14.1・cut2resolve 0.9.0 で起動。まとめて実行「解析から全部」を2回: 1回目は自動採用 → 書き出し(約1分)の後、文字起こしが終わらずユーザーが中止、
  2回目は書き出しを飛ばし、文字起こし 15 秒 → transcript/v1 保存 → Resolve パック作成まで進んだ
- 保留(ユーザー決定): 1回目の文字起こしが遅かった件(43秒の切り抜きで 502 秒。同時に認識ワーカーが起動し直していた。large-v3 の最初の読み込みを疑うが未確定)。再現したら「文字起こし」の段の表示と transcribe の serve.log を見る
- 変更: docs/HANDOVER.md(残りの作業・改善の候補・保留・次のセッションに貼る指示文)
- 未コミット: docs/HANDOVER.md・docs/WORKLOG.md(push.bat で)

## 2026-09-26 Claude(Cowork)— 段階7-0〜7-3: 画面のエラーの記録・解析の設定をサーバーへ・離れた/戻ったの共通化・窓で開く(試用)(入口 v0.8.0・スタジオ v0.7.0・文字起こし v0.14.2・cut2resolve v0.9.1)
- 担当: 統合作業(Claude)。スタジオ(queue.js・review.js)・文字起こし(app.js)も変更(離れた/戻った・解析の設定)。作業の土台は GitHub の main = eef5e17 + PC の未コミット(前の記録の HANDOVER・WORKLOG)
- 確認(ユーザー 2026-09-26): 段階5・6 の実機確認の残り(まとめて実行の「採用後を全部」「文字起こしまで」・ラウドネス・案件の状態とメモ・セリフ・順番待ち)は全部問題なし
- 決定(ユーザー 2026-09-26): 画面の形は「おすすめの流れ」で 7-3 まで進める(7-0 エラーの記録 → 7-1 解析の設定をサーバーへ → 7-2 タブ前提の作りを直す → 7-3 Edge のアプリモードの窓を試用)。
  窓を数日試してから「窓で十分 / pywebview(7-4。依存の追加なので改めて確認)/ ブラウザに戻す」を決める。統合計画の正本(Claude Docs)に段階7 を追加済み
- 変更(7-0): `app/clientlog.py`(新規。client-errors.jsonl に1行1件の JSON・1分に30件・512KB で回す)、`ui-kit/ui-kit.js`(UIKit.report・error / unhandledrejection を自動で送る・同じエラーは1回・20件まで)、
  `app/launch.py`(PortalServer.ytt_request / ytt_api: 画面の共通の API `api/ytt/…`・`/api/log?tool=client`・本文の読み取りを read_json_body に)、`app/mount.py`(取り込んだツールの `/…/api/ytt/…` をツールに渡さず入口へ)
- 変更(7-1): スタジオ `queue.js`(解析の設定を `/api/settings` の analyze に保存・localStorage はサーバーに無いときだけ1回引き継ぐ・読み込み中に変えた値を上書きしない・離れたら待たずに送る)、
  `app/autorun.py`(「解析から全部」が保存した解析の設定を使う)、`app/test_autorun.py`
- 変更(7-2): `ui-kit/ui-kit.js`(UIKit.life: onLeave('hidden'|'blur'|'pagehide')・onReturn('visible'|'focus'|'pageshow')。iframe にフォーカスがあれば離れたことにしない。'blur' のあと 'hidden' になればもう一度知らせる)、
  文字起こし `app.js`(設定・文書の保存を onLeave に。保管(音声の切り出し)は 'blur' では走らせない)、スタジオ `review.js`('blur' では保存だけ・再生は止めない。戻ったらセリフを読み直す)、`app/portal.js`(戻ったら状態を取り直す)
- 変更(7-3): `app/appwindow.py`(新規。Edge の場所(YTT_APP_BROWSER・Program Files・LOCALAPPDATA・レジストリ)、`--app=<URL> --user-data-dir=<app\browser-profile>`、設定 app\settings.json の window、
  開ける URL の検査・10 秒に 8 回まで)、`app/launch.py`(起動時に設定どおり窓かブラウザで開く・POST /api/window・/api/status の window)、`app/portal.html`・`portal.js`(「窓で開く(試用)」のスイッチと「いま窓で開く」)、
  `ui-kit/ui-kit.js`(UIKit.win: 窓(display-mode: standalone)の中の target=_blank リンクを入口に頼んで開く。このパソコンの画面 → 窓、外 → いつものブラウザ)
- 変更(その他): ui-kit の写し3つ(tools/sync_ui_kit.py)、`.gitignore`(**/logs/・**/browser-profile/)、`tools/push_helper.py`(browser-profile を送らない)・`tools/test_push_helper.py`、
  `clip-studio/e2e_ui.py`(戻っただけの合図 → 「離れた → 戻った」の組で送る tab_away_and_back。本物のタブの切り替えと同じ形)
- テスト: `app/test_window.py`(新規 21)・`app/e2e_window.py`(新規。窓の中の「開く」→ 偽の Edge がアプリモードで起動・外のサイト → いつものブラウザ・解析の設定の引き継ぎ・離れた/戻った・エラーの記録)、
  `app/test_mount.py`(取り込んだツールの api/ytt/…)。クラウドで全部通過: 単体(入口 93・スタジオ 226・文字起こし 102・cut2resolve 217・ytt_core/tools 69・node 24)、
  画面(e2e_portal・e2e_autorun・e2e_window・スタジオ e2e_ui / --mounted・e2e_analyze・cut2resolve e2e_ui / --mounted・文字起こし e2e 7本・tools/e2e_pipeline・e2e_datadir)
- 資料: `README.txt`(窓で開く・エラーの記録)・各ツールの README・`AGENTS.md`(取り込みの決まりに api/ytt・UIKit.life・エラーの記録)・`ui-kit/README.md`(v2)・`docs/data-location.md`・`docs/integration-plan.md`(段階7で決めたこと)
- 版: 入口 0.7.0 → 0.8.0、スタジオ 0.6.0 → 0.7.0、文字起こし 0.14.1 → 0.14.2、cut2resolve 0.9.0 → 0.9.1(ui-kit の更新だけ)、ui-kit v1 → v2
- 判断・理由: 画面の共通の API を入口1か所にしたのは、3ツールの serve.py に同じ検査つきの API を3回書かないため(取り込みの層で回す)。
  エラーの記録を JSON の1行にしたのは、エラーの文の改行で偽の行を作らせないため。窓の判定を display-mode にしたのは、サーバーからは同じ画面がタブか窓か分からないため
  (外れたら今までどおりタブで開くだけ)。窓を閉じても入口を終えないのは、閉じる直前の保存よりサーバーの停止が先になる危険を持ち込まないため
- 注意: 画面で visibilitychange を直接使わず UIKit.life を使う(AGENTS.md)。ツールに /api/ytt/ で始まる API を作らない。窓の専用のプロファイルは YouTube に未ログイン
  (会員限定・年齢制限の配信は窓の中の埋め込みで再生できないことがある)。窓の設定は次の起動から(「いま窓で開く」ですぐ試せる)
- 未確認(実機・クラウドの Linux では Edge の窓を再現できない): 窓の中で「開く」「文字起こしで開く」が窓で開くか(display-mode: standalone の判定)・YouTube の埋め込みが再生できるか・
  外のリンクがいつものブラウザで開くか・書き出し中に落ちないか・client-errors.jsonl に記録されるか
- 未完了・次: 実機確認 → 数日の試用 → 窓で十分 / 7-4 pywebview / ブラウザに戻す をユーザーが決める。改善の候補(校正後にパックを作り直す・まとめて実行の記録を残す)は未着手
- 未コミット: 新規 4(app/appwindow.py・app/clientlog.py・app/test_window.py・app/e2e_window.py)、
  変更 34(.gitignore・AGENTS.md・README.txt・app/{README.txt,autorun.py,e2e_portal.py,launch.py,mount.py,portal.html,portal.js,test_autorun.py,test_mount.py}・
  clip-studio/{README.txt,core.js,e2e_ui.py,queue.js,review.js,serve.py,ui-kit.js}・cut2resolve/{README.txt,cut2resolve_core.py,ui-kit.js}・
  docs/{HANDOVER.md,WORKLOG.md,data-location.md,integration-plan.md}・tools/{push_helper.py,test_push_helper.py}・transcribe-tool/{README.txt,app.js,serve.py,ui-kit.js}・ui-kit/{README.md,ui-kit.js})。push.bat で

## 2026-09-26 Claude(Cowork)— 担当の変更: 文字起こしツールも Claude(UI の全面見直しの開始)
- 決定(ユーザー 2026-09-26): 案A(文字起こしの校正画面に「カットとパック」の欄を足し、計算とパック作りは cut2resolve の API を呼ぶ)で進める。**文字起こしツールの担当も Claude**。
  UI は3ツールと入口すべてを全面的に見直し、使いづらい部分を徹底的になくす(進め方は Claude に任せる・実装まで)。文字起こしの履歴(たくさんの動画)を見やすくする
- 担当: 文字起こしツール(`transcribe-tool/`)・`clip-studio/` の画面・`ui-kit/` も、この作業が終わるまで Claude。GPT(Codex)はこの間これらを触らない
- 変更: `tools/demo_env.py`(新規。見本のデータ(架空の配信者・配信・切り抜き・たくさんの文字起こし)で入口と3ツールを疑似モードで動かす。画面の見直し・写真・手での確認用)
- 未コミット: tools/demo_env.py・AGENTS.md・docs/WORKLOG.md(このあとの見直しの変更と一緒に push.bat で)

## 2026-09-26 Claude(Cowork)— 3ツールと入口の画面の全面見直し・文字起こしの「カットとパック」(案A)・履歴と案件の一覧(入口 v0.9.0・スタジオ v0.8.0・文字起こし v0.15.0・cut2resolve v0.10.0・ui-kit v3)
- 担当: Claude(文字起こしツールも。直前の記録)。作業の土台は GitHub の main = 7ce0050(段階7 まで)+ 直前の記録の未コミット(tools/demo_env.py・AGENTS.md・WORKLOG)
- 決定(ユーザー 2026-09-26): 案A で進める・UI は3ツールと入口すべてを全面的に見直す・使いづらい部分を徹底的に排除・進め方は任せる(実装まで)・たくさんの動画の履歴を見やすく。
  今後の開発は AI モデルを作業に合わせて使い分ける(今回: 監査4本は Sonnet、文字起こし・スタジオの実装は Opus、cut2resolve・入口/案件の実装は Sonnet、統括・見直し・結合は Opus)
- 進め方: `tools/demo_env.py`(見本のデータ)で全画面を動かし、画面ごとに監査(写真つき)→ 共通のルール `docs/ui-guidelines.md`(新規。用語集・ヘッダー・ボタンと札・一覧・段階的に見せる・狭い画面)と ui-kit v3 → 4つの画面を並行で実装 → 統括が見直し・結合・全体のテスト
- 変更(共通・ui-kit v3): 状態の札の文字を濃く(`--ok-ink` など。明るいテーマで 3.66〜4.37 → 5.5 以上)・札は枠なしで押せない表示に、入口へ戻るリンク(ヘッダーの `data-ui-home`・「他のツール」の先頭に入口・案件の一覧。取り込まれているときだけ)、
  一覧の部品(`.ui-listbar` `.ui-count` `.ui-group` `.ui-next`)・言葉の説明(`.ui-term`)・`.lag.keep`・`UIKit.fmt.ago/date/dur`・`UIKit.esc`。ytt_core/txindex.py に `pack_info`(パックの有無の判定。入口の案件と文字起こしの一覧の二重の規則を1か所に)
- 変更(文字起こし v0.15.0): 履歴を作り直し(配信ごと・配信者ごと・まとめないのまとまり、検索・状態・種類・並び替え、1件1行に だれの・いつの・校正の進み具合・パック、操作は「⋮」)。/api/transcripts に項目を追加
  (rows・proofed・cut・flagged・durationSec・videoId・clipTitle・markLabel・channel・streamTitle(スタジオの data.json を読むだけ)・mediaOk・pack)。
  校正画面の映像の下に「カットとパック」(残す/カットの行数・カット後の長さ・カット後の見え方で再生・選んだ行をカット/残す・Text+ の fps と大きさ・パックを作る/作り直す・上書きの確認。
  計算とパック作りは cut2resolve の api/plan・api/build(preset transcript-rows)。zip と .cut-plan.json は「詳しい設定」へ)。「話者・置換・書き出し」を4枚(話者・文字をまとめて直す・書き出し・以前の版に戻す)に分割、
  720px 未満は左メニューを引き出しに、キー操作の手がかり、「キー操作」「パック」の言葉
  - 統括の判断: 文字起こしを開いただけで動画の隣に .transcript.json を書き出していた作りを、「カット後の見え方で再生」を入れたとき・パックを作るときだけに変更(ファイルを勝手に増やさない)。それまでのカット後の長さは残す行の時間を足した目安(「約」)
- 変更(スタジオ v0.8.0): 不具合2件(① 事務所を登録した直後にチェックが全部外れて検索できない・③ プレーヤーが使えないときキー操作のたびに通知が出る)、③ の配信の選択を探せる一覧に、書き出しはどの表示でも右の列の先頭、
  ① の検索結果は「全部まとめて上位30本」を既定に、② の失敗に「どうすればいいか」、④ コラボに検索・配信者ごとのまとまり・メンバーに配信者と日時、狭い画面の案内・28px 以上のボタン、「配信」「動画ファイル」の言葉。/api/videos に createdAt
- 変更(cut2resolve v0.10.0): 動画を読み込むまで書き出しを閉じる・無音の数値は「詳しい設定」へ、動画と同じ場所の同じ名前の字幕・文字起こし・残す区間を提案(/api/inspect の siblings)、切れる所が無いときの案内(pack.py)、
  パスの末尾(ファイル名)を見せる、注意の重さの色分け(warningLevels)、試算前の確認、今見ている段の強調、専門用語の説明。文字起こし関係の入力は閉じた欄へ移し「文字起こしツールのカットとパックがおすすめ」の案内(機能は消していない)。API は追加だけ
- 変更(入口 v0.9.0・案件): 案件を1件1行(開くと切り抜き・まとめて実行・メモ)、検索・状態・並び替え・まとめ方(なし・配信者・状態)・30件ずつ、「次にやること」、パスは title へ、まとめて実行が動いている行は閉じない。
  高さは 60本で 20,686px → 2,789px(1440px 幅)・35,225px → 3,690px(390px 幅)。/api/cases の各案件に streamedAt・tx・packs・next・remaining。「すべて終了」の残り秒数
- 変更(その他): `tools/demo_env.py`(パックの印を中に作る・② 解析も動く)、README(全体・各ツール)、AGENTS.md、ui-kit/README.md、docs/integration-plan.md
- テスト(クラウドで全部通過): 単体 スタジオ 226・文字起こし 103・cut2resolve 223・入口 97・ytt_core/tools 70・契約 23・node 27(スタジオ 18・文字起こし 9)、
  画面 入口 e2e_portal・e2e_autorun・e2e_window、スタジオ e2e_ui・--mounted・e2e_analyze、cut2resolve e2e_ui・--mounted、文字起こし e2e 7本、tools/e2e_pipeline・e2e_datadir
- 版: 入口 0.8.0 → 0.9.0、スタジオ 0.7.0 → 0.8.0、文字起こし 0.14.2 → 0.15.0、cut2resolve 0.9.1 → 0.10.0、ui-kit v2 → v3
- 注意: 画面を直すときは docs/ui-guidelines.md に合わせる。ツールの画面の中の「他のツール」のリンクを数えるテストは、先頭の「入口」「案件の一覧」を除いて数える(`.ui-brand-mark:not([data-tool=portal])`)。
  文字起こしの「カットとパック」は入口の中(同じポートの cut2resolve)だけで使える。文字起こし側に Resolve 用の計算を書き足さない。`pgrep/pkill -f demo_env.py` は同じコマンドの中の自分のシェルにも当たるので、`[t]ools/demo_env.py` と書く
- 未確認(実機): 全画面(特に文字起こしの履歴・カットとパックで実際の配信の切り抜きからパックを作り Resolve で読めるか・案件の一覧・スタジオの ③)。窓(段階7-3)の中での見え方
- 残した課題(候補): ui-kit に引き出し・確認のダイアログ・小さな進み具合の棒・キーの手がかりの帯を共通の部品として足す(今は各ツールにある)、スタジオに配信の日時(uploadDate)を残す(今は追加した時刻)、
  案件の画面からスタジオの特定の配信を開く(?open=)、スタジオのサーバーのエラーの文言に残る「動画」、行の「要確認」の印が押せる札のまま(ルールの3)
- 未コミット: 新規 2(docs/ui-guidelines.md・tools/demo_env.py(直前の記録))、変更 63(AGENTS.md・README.txt・app/{README.txt,cases.html,cases.js,cases.py,e2e_autorun.py,e2e_portal.py,launch.py,portal.css,portal.js,test_cases.py}・
  clip-studio/{README.txt,app.css,collab.js,core.js,e2e_ui.py,index.html,queue.js,rank.js,review.css,review.js,serve.py,settings.js,store.py,test_review.cjs,test_studio.py,ui-kit.css,ui-kit.js}・
  cut2resolve/{README.txt,app.css,app.js,cut2resolve_core.py,e2e_ui.py,index.html,pack.py,serve.py,test_pack.py,test_serve.py,ui-kit.css,ui-kit.js}・docs/{WORKLOG.md,integration-plan.md,HANDOVER.md}・
  transcribe-tool/{AGENTS.md,README.txt,app.js,e2e_eval_v093.py,e2e_ui_handoff.py,e2e_ui_mounted.py,e2e_ui_v07.py,e2e_ui_v08.py,e2e_ui_v09.py,e2e_ui_v098.py,index.html,serve.py,test_backend.py,test_document_save.cjs,ui-kit.js}・
  ui-kit/{README.md,ui-kit.css,ui-kit.js}・ytt_core/{test_ytt_core.py,txindex.py})。push.bat で

## 2026-09-26 Claude(Cowork)— 「編集」ツール(文字起こし + cut2resolve の統合)の設計と画面イメージ・Claude Code への引き継ぎ
- 決定(ユーザー 2026-09-26): 文字起こしツールと cut2resolve を**1つのツール「編集」**にする(入口・他のツールから cut2resolve のカードはなくなる。パックの部品は中で使う)。
  「普通のカットツールのように手動でのカット位置の調整も必要」「編集ソフトを作るイメージ」、校正は同じツールの別の画面、範囲はカットと字幕まで、
  切り抜きは基本1本(あとで複数をつなげられるように)、文字起こしの無い動画も使える。画面は3つのタブ 1 文字起こし / 2 カット / 3 パック → 画面イメージを承認(「このイメージでいい」)。
  **実装は Claude Code(PC)で行う**
- 変更: `docs/edit-tool-design.md`(新規。画面・データ(`transcripts/<id>.edit.json`)・API(edit の GET/PUT と rev・open-video・peaks・intoDoc・cut2resolve の keeps)・入口の変更・
  実装の段取り E1〜E6・実装の判断・リスク・未決)、`docs/mockups/`(新規。edit-1-transcribe.png・edit-2-cut.png・edit-3-pack.png と元の edit-mock.html(ui-kit.css を相対パスで読む・見本のデータは架空))、
  `docs/HANDOVER.md`(Claude Code 用に書き直し・貼る指示文)、`AGENTS.md`(担当表に「編集」の実装の担当、資料の場所に設計書)
- 判断・理由: 編集の内容(残す区間)を文書と別のファイルにしたのは、校正の保存(baseUpdatedAt)とタイムラインの細かい保存をぶつけないため。
  たたき台の計算とパック作りは cut2resolve の api/plan・api/build のまま(Resolve 用の計算を二重に持たない。resolve-pack-unification.md の方針)。
  編集の内容に動画のパスを保存しないのは、画面から送られたパスでパックを作らせないため
- 途中の経緯: 一度「実装を進める」と決めたが、ユーザーの「実装ストップ」で止め、画面イメージで合意してから引き継ぐ形にした。コードは何も変えていない
- 未完了・次: E1〜E6 の実装(Claude Code)。段階7と画面の見直しの実機確認(ユーザー)。Claude Docs「動画編集ツール 統合計画」に「編集」への統合を書き足す(Cowork)
- 注意: 新しい .js(cut.js・pack-tab.js の予定)を足したら、文字起こしの e2e が一時フォルダに写すファイルの一覧にも足す。cut2resolve は ui-kit の一覧から消さずに隠す
  (編集の画面が `UIKit.tools.base('cut2resolve')` でパックの API を呼ぶため)
- 未コミット: 新規 5(docs/edit-tool-design.md・docs/mockups/{edit-1-transcribe.png,edit-2-cut.png,edit-3-pack.png,edit-mock.html})、変更 3(docs/HANDOVER.md・docs/WORKLOG.md・AGENTS.md)。
  Claude Code が最初のコミットに含めるか、push.bat で

## 2026-09-26 Claude Code — 「編集」E1 サーバー(編集の内容・open-video・peaks・intoDoc・cut2resolve の keeps)と、認識ワーカーが Windows で止まる不具合
- 担当: 「編集」の実装(Claude Code。AGENTS.md の担当表)。土台は main = 0126478(設計書・画面イメージはユーザーが push 済み)
- 確認(ユーザー 2026-09-26): 段階7と画面の見直しの実機確認は**まだ**(待たずに E1 から始める)。PC に Playwright と Node.js が無い → E2 に入る前に入れるか聞き直す(依存の追加)
- 変更(文字起こし `transcribe-tool/serve.py`): 編集の内容 `transcripts/<id>.edit.json`(`sanitize_edit`・`read_edit`・`GET/PUT /api/edit`・rev と 409・壊れたファイル)、
  行の cutState を編集の内容から決める `edit_cut_flags`・`apply_edit_cuts`(校正の保存・範囲/選んだ行の再認識・履歴から戻す・intoDoc のどの書き込みでも)、
  `POST /api/edit/pack`(パックを作った記録。rev は増やさない)と `pack_stale`、一覧の `hasEdit`・`editRev`・`packRev`・`packAt`・`packStale`、
  `POST /api/open-video`(文字起こしせずに開く。拡張子・ffmpeg で映像か音声が読めるか・同じ動画の文書があればそれ)、`GET /api/peaks`(音の波形。202 で待たせる・cache/peaks・SLOTS)、
  `POST /api/transcribe` の `intoDoc`(`fill_doc`)、削除で `.edit.json` も消す、ApiError に extra(409 に今の rev を付ける)
- 変更(cut2resolve): `pack.EDIT_KEEPS`・`MAX_KEEPS`・`Request.warn_short`(0.5 秒より短い区間の注意)・`summary` の `keepsSec`、
  `serve.request_from_spec` の `spec.keeps`(`keeps_from_spec` の検査・`advanced_from_spec` に「詳しい設定」を分けた・keeps と preset の同時指定は 400)
- 変更(ワーカー `transcribe-tool/tx_worker.py`): やり取り用の標準入力を fd 0 から離して読む(`_protocol_input`)。**Windows で、標準入力のパイプを別のスレッドが読んで待っている間に
  numpy などの DLL を読み込むと、次の要求が届くまで止まる**(PC で最小の再現を確認。`test_worker` の範囲の再認識のテストが止まっていた = クラウドの Linux では出ない)。
  保留の「まとめて実行の最初の文字起こしが遅い(43 秒の切り抜きで 502 秒)」の原因の可能性が高い → 実機で次に文字起こしするときに速くなったかを見てほしい
- テスト: 新規 `transcribe-tool/test_edit.py`(12。test_metrics から読み込む)、`cut2resolve/test_serve.py` に keeps、`tools/test_resolve_pack_contract.py` に `EditKeepsContract`
  (keeps のパック = 時刻リストのパック・29.97/59.94fps でもフレームがずれない・以前の文書のたたき台「行から」のパック = preset transcript-rows のパック)。
  PC(Windows・Python 3.12 miniconda)で通過: 文字起こし 115(skip 1)・cut2resolve 225(skip 14 = Lua が無い)・契約 25・ytt_core/tools 61(skip 1)・入口 97
- 決定・理由: 設計書の「11. 実装で決めたこと」(`docs/edit-tool-design.md`)。主なもの: clips は 0 個も保存できる(パックは 1 個以上)、`PUT /api/edit` は文書の updatedAt を変えない
  (校正の保存の競合に巻き込まない。cutState は編集の内容から付け直すので古い画面の印で壊れない)、パックの記録の API を足した(設計の 5 に無かった)、重なる2行の一方だけカット済のときは字幕が増える(契約テストの説明に記録)
- 未完了・次: E2 画面の骨組み(3つのタブ・Alt+1/2/3・題名の行・メニューの帯・「カットとパック」のカードを外す・文字起こしせずに開く)。版は E6 でまとめて上げる(今は据え置き)
- 注意: 行の「カット済」の規則は `edit_cut_flags` と、E3 で作る画面の cut.js の2か所になる(同じ定数 0.75 フレーム)。文書を書き込む処理を足すときは `apply_edit_cuts` を通す

## 2026-09-26 Claude Code — 「編集」E2 画面の骨組み(3つのタブ・題名の行・メニューの帯・文字起こしせずに開く)
- 変更(文字起こし `transcribe-tool/`): `index.html`(ブランド「編集」・3つのタブ・保存の状態をヘッダーへ・題名の行 `#docBar`・タブの中身の入れ物 `#tabTx/#tabCut/#tabPack`・
  左のメニューの細い帯 `#menuStrip`・「文字起こしせずに開く」・`?media=` の選択 `#mediaChoice`・行の無い文書の案内 `#noRows`・「選んだ行をカット/残す」を「まとめて ▾」へ・
  「カットとパック」のカードを 3 パック のタブへ(E4 で作り直すまでの仮)・キー操作の一覧に Alt+1/2/3)、`app.js`(`EDT`・`setEditTab()`・URL の #tx/#cut/#pack・Alt+1/2/3・
  校正のキーは 1 文字起こし のタブだけ・帯から重ねて開くメニュー・`renderDocBar()`・`openVideoNoTx()`・`?media=` で文書があれば開く・intoDoc の「この動画を文字起こしする」)、
  `serve.py`(`GET /api/doc-for`・`find_doc_for_media`(open-video と共通)・ジョブの一覧に `into`)
- テスト: 新規 `e2e_edit_common.py`・`e2e_edit_tabs.py`、`test_edit.py` に doc-for、`e2e_ui_handoff.py`(?media= の新しい流れ・文字起こしせずに開く・intoDoc)、
  `e2e_ui_mounted.py`(カードの場所・**Windows でも動くように**: ワーカーを PowerShell で数える・入口を Ctrl+Break で止める・SIGKILL が無ければ SIGTERM)。
  PC で通過: 文字起こしの e2e 8本(既存7本 + e2e_edit_tabs)・単体 116(skip 1)・app/test_mount・tools/test_ui_kit_sync
- 決定・理由: 設計書の「11. 実装で決めたこと」の E2。行の文字の入力中の Alt+数字 は話者のまま(設計の Alt+1/2/3 と重なるため)。?media= は文書があれば開く(設計の 3)
- 注意: `<html>` の属性は `data-edtab-now`(`[data-edtab]` はタブのボタンだけ。同じ名前にすると querySelector が `<html>` に当たる)。Windows のコンソールで e2e を流すときは
  `PYTHONIOENCODING=utf-8`。Playwright(1.63)を miniconda の Python に入れた(ユーザー承認 2026-09-26)
- 未完了・次: E3 カット(タイムライン・プレビュー・字幕の一覧・たたき台・保存)

## 2026-09-26 Claude Code — 「編集」E3 カットのタブ(タイムライン・プレビュー・字幕の一覧・たたき台・保存)
- 変更(文字起こし `transcribe-tool/`): 新規 `cut.js`(タイムライン: 区間・削る区間・つまみのドラッグ(1フレーム単位・吸着・Alt)・分割・削る/戻す・I/O/X・, .・元に戻す/やり直す・ズーム・
  波形(canvas)・字幕の帯、プレビュー(元の動画/カット後・字幕を重ねる)、字幕の一覧(押すとその位置・行ごとの削る/戻す)、たたき台(行から・無音・時刻リスト・スタジオ)、
  0.8 秒まとめて保存・409 の読み直し/上書き・動画の長さの変化)、`index.html`(カットのタブの中身・確認のダイアログ・キー操作の一覧・CSS)、
  `app.js`(cut.js の起動と受け渡し・行の「残す/カット済」と「選んだ行をカット/残す」を編集の操作に・文書を切り替える前にカットを保存・題名の行の札をカットから・api() のエラーに data)、
  `serve.py`(`GET /api/edit/draft`・`/cut.js`・`/pack-tab.js` を配る)、`resolve_export.py`(`edit_draft`: pack.TRANSCRIPT_ROWS で「行から」と fps・長さ)
- テスト: 新規 `e2e_edit_cut.py`(入口に取り込んだ形)、`test_edit.py` に draft、既存の e2e 6本・test_backend・test_metrics の写す一覧に cut.js、`e2e_edit_common.py`(検索してから開く・YTT_CUT2RESOLVE_DIR)、
  `e2e_edit_tabs.py`(行の無い文書にもカットの札)。PC で通過: 文字起こしの e2e 9本(既存7本・e2e_edit_tabs・e2e_edit_cut)・単体 117(skip 1)・契約 25・app/test_mount・tools/test_ui_kit_sync
- 決定・理由(設計書の「11」の E3): **開いたときの下書き・「行から」は文字起こしのサーバーで pack.py を呼ぶ**(cut2resolve の api/plan だと動画の隣に .transcript.json を書き出すことになり、
  「開いただけでファイルを増やさない」に反するため。規則は pack.py の1か所のまま)。J は1秒戻る(ブラウザは逆再生できない)。区間はフレームの整数で持つ
- 途中で直した不具合: 選ぶたびにタイムラインの DOM を作り直してクリックが届かない・波形の canvas と目盛りのラベルが中身の幅を押し広げて「全体」が効かない・
  ページのスクロールバーの出入りで倍率がずれる(いずれもテストで見つけて直した)
- 未完了・次: E4 パック(keeps でパック・上書きの確認・中止・前回のパック・作り直しの知らせ)。3 パック のタブは今は仮のカード(行の印から作る)
- 注意: 行の「カット済」の規則は serve.py の `edit_cut_flags` と cut.js の `rowCutFlags` の2か所(変えるときは両方と test_edit)。新しい .js を足したら既存の e2e の写す一覧にも足す

## 2026-09-26 Claude Code — 「編集」E4 パックのタブ(カットのとおりのパック・見積もり・前回のパック・作り直しの知らせ)
- 変更(文字起こし `transcribe-tool/`): 新規 `pack-tab.js`(置き先の fps・大きさ・入れるもの・出力先・これから作るパック(長さ・区間・Text+ 字幕の数・略図)・字幕の見本・作る前の注意・
  パックを作る(cut2resolve の api/build に spec.keeps)・上書きの確認・進み具合と中止・前回のパック(中身・フォルダを開く・友人へ.txt・パスをコピー)・作り直しの知らせ・zip)、
  `index.html`(3 パック のタブを作り直し・「カットとパック」のカードと映像の「カット後の見え方」の印を外した)、`app.js`(`CP` を外して cut2resolve の呼び出し・書き出し・上書きの確認だけ残した・
  pack-tab.js の起動・一覧の「パック済み」を更新)、`cut.js`(`commit()`・`fps()`・`refresh()`)、`serve.py`(`POST /api/edit/preview`・`GET /api/edit/pack-readme`・zip と cut-plan をカットのとおりに)、
  `resolve_export.py`(`edit_preview`・`create_package(keeps=)`)
- 変更(cut2resolve): `serve.py`(`is_pack_dir`: cut2resolve の cut-plan.json のあるフォルダは「フォルダを開く」で開ける)、`test_serve.py`
- テスト: 新規 `e2e_edit_pack.py`、`e2e_ui_mounted.py`・`e2e_ui_handoff.py`・`e2e_edit_tabs.py` をパックのタブに合わせた、`test_edit.py` に見積もり・手順書・zip・cut-plan、`e2e_edit_common.py`(直下のファイルを全部写す)、
  既存の e2e の写す一覧に `pack-tab.js`。PC で通過: 文字起こしの e2e 10本・単体 118(skip 1)・cut2resolve 225(skip 14)・契約 25・app/test_mount・ui-kit の写し・ytt_core
- 決定・理由(設計書の「11」の E4): 見積もりは文字起こしのサーバーで pack.py を一時フォルダで呼ぶ(開いただけで動画の隣にファイルを作らないため。規則は pack.py の1か所)。
  文字起こしの無い動画は Text+ なしのパック。zip と「残す区間の保存」もカットのとおり。前回のパックのフォルダは入口を起動し直しても開ける
- **既存機能の変更(確認してほしい)**: v0.15.0 の校正画面の「カットとパック」のカードは無くなった(中身は 2 カット・3 パック のタブへ。設計の 3 のとおり)。
  「cut2resolve で開く」のリンク(カードの詳しい設定の中)は無くした(cut2resolve の画面は E5 で「編集」へ転送する予定のため)
- 実機で確かめてほしいこと: 60fps の元の動画を 30fps のプロジェクトに入れたとき、Resolve で区間の端が1フレームずれないか(パックのタブに注意を出している。設計の 9)
- 未完了・次: E5 入口・ほか(入口のカード・ui-kit の一覧・cut2resolve の画面の転送・「編集で開く」・まとめて実行の文言)

## 2026-09-26 Claude Code — 「編集」E5 入口・ほかのツール(入口のカード・ui-kit v4・cut2resolve の画面の転送・「編集で開く」)
- 変更: `app/launch.py`(文字起こし = 「編集」・cut2resolve は hidden・状態に hidden)、`app/portal.js`・`portal.html`(cut2resolve のカードは動いている間は出さない・流れは ① → ②)、
  `app/mount.py`(`page_to`: 取り込んだ cut2resolve の画面は「編集」へ転送。編集も取り込まれているときだけ・?classic=1 は前の画面)、`app/cases.js`(「編集で開く」の1つに)、
  `app/autorun.py`(文言)、`ui-kit/ui-kit.js`(v4: 表示名「編集」・cut2resolve は hidden でメニューに出さない)と写し3つ、`clip-studio/review.js`(書き出しの結果は「編集で開く」の1つ)、
  `transcribe-tool/app.js`(書き出しの欄の「cut2resolve で開く」→ パックのタブへの案内)、入口へ戻るリンクの説明(3つのツール → ツール)
- テスト: `app/test_mount.py`(転送)、`app/e2e_portal.py`・`app/e2e_window.py`・`clip-studio/e2e_ui.py`・`transcribe-tool/e2e_ui_handoff.py` を合わせた。
  **Windows でも流せるように直した**(以前から Linux 前提で PC では止まっていたもの): e2e_portal(SIGKILL)・e2e_window(偽の Edge を .bat で)・e2e_pipeline と cut2resolve の e2e_ui --mounted(Ctrl+Break で止める)・
  スタジオの e2e_ui(YouTube を止めたあと読み直す)。PC で通過: 入口 98・e2e_portal 94・e2e_autorun・e2e_window・e2e_pipeline・e2e_datadir・ytt_core/tools・スタジオ単体・e2e_ui 113(単体・入口の中とも)・
  e2e_analyze・cut2resolve e2e_ui(単体・入口の中)・文字起こしの e2e 10本
- 注意: テストを流すとき、単体テスト(unittest)には `PYTHONIOENCODING=utf-8` を付けない(子プロセスの出力を cp932 で読むテストが落ちる)。画面テスト(e2e)には付ける。
  Node.js が無いので `clip-studio/test_review.cjs`・`transcribe-tool/test_document_save.cjs` は PC で流していない
- 未決(ユーザーに確認): 単体の cut2resolve の画面のファイルを消すか(今は ?classic=1 で残している)、まとめて実行でカットのある文書をカットのとおりに作るか
- 未完了・次: E6 仕上げ(版・README・AGENTS.md・ui-guidelines の用語・HANDOVER)

## 2026-09-26 Claude Code — 「編集」E5 追記: まとめて実行もカットのとおり・cut2resolve の画面を削除(ユーザー決定)
- 未決への回答(ユーザー 2026-09-26): 単体の cut2resolve の画面のファイル → **消す**。まとめて実行でカットのある文書 → **カットのとおりに作る**
- 変更(まとめて実行 `app/autorun.py`): パックの段で、「編集」でカットを決めてある文書は `GET /api/edit` の区間を spec.keeps にして作る(接している区間は1つに・字幕の行が無ければ Text+ なし)。
  作ったら `POST /api/edit/pack` で記録(packRev)を残す(「編集」のパックのタブで作り直しの知らせが出る)。カットの無い文書は今までどおり preset transcript-rows。`app/test_autorun.py` に1件
- **削除(git rm。ファイルの削除の告知)**: `cut2resolve/index.html`・`app.js`・`app.css`・`e2e_ui.py`・`ui-kit.js`・`ui-kit.css`。
  `cut2resolve/serve.py` の `/`・`/index.html` は「画面は「編集」に統合しました」の案内だけ(スクリプトなし・CSP・X-Frame-Options DENY)。API・CLI(cut2resolve.py)・パック作り(pack.py)はそのまま
- 変更: `app/mount.py`(?classic=1 の逃げ道をやめた。編集が取り込まれていれば /cut2resolve/ はいつも「編集」へ転送)、`tools/sync_ui_kit.py`(写し先から cut2resolve を外した)、
  `cut2resolve/test_serve.py`・`app/test_mount.py`・`app/e2e_portal.py`(前の画面の確認を案内の確認に)、`AGENTS.md`(表の cut2resolve の行)
- テスト(PC で通過): cut2resolve 225(skip 14)・入口の単体 99・e2e_portal・e2e_autorun・tools/e2e_pipeline・契約 25・ui-kit の写し・文字起こしの e2e_ui_mounted
- 未完了・次: E6 仕上げ(版・README・AGENTS.md・ui-guidelines の用語・HANDOVER)

## 2026-09-26 Claude Code — 「編集」E6 仕上げ(版・README・AGENTS.md・用語集・HANDOVER)。「編集」の実装 E1〜E6 はこれで終わり
- 版: 編集(文字起こし)0.15.0 → **0.16.0**(serve.py・app.js・README)、cut2resolve 0.10.0 → **0.11.0**(cut2resolve_core.VERSION・README)、
  入口 0.9.0 → **0.10.0**(launch.py・README)、スタジオ 0.8.0 → **0.8.1**(serve.py・core.js・README)、ui-kit **v4**(README.md)
- 文書: `README.txt`(ツールの一覧・流れ・まとめて実行)、`transcribe-tool/README.txt`(「編集」の3つのタブ・Resolve 連携の節・v0.16.0)、
  `cut2resolve/README.txt`(画面は「編集」へ・前の画面との対応表・API の keeps・v0.11.0)、`app/README.txt`(v0.10.0)、`clip-studio/README.txt`(v0.8.1)、`ui-kit/README.md`(v4)、
  `AGENTS.md`(全体の形に「編集」・表)、`transcribe-tool/AGENTS.md`、`docs/ui-guidelines.md` の用語集(編集・カット・残す区間/削る区間・たたき台・作り直し)、
  `docs/pipeline.md`(画面どうしのリンク・受け渡しの API)、`docs/edit-tool-design.md`(E5 追記・E6・実機で確かめること・未決の回答)、`docs/HANDOVER.md`(書き直し・再開用の指示文)
- 画面の文言: 「カットとパック」のカードが無くなったのに残っていた言葉を直した(`transcribe-tool/app.js` の一覧の「パックを作る」の説明・`pack-tab.js`・`index.html` のたたき台「行から」の説明と行の操作の説明)。
  コメントだけ: `cut2resolve/serve.py`・`cut2resolve_core.py`・`clip-studio/exporter.py`
- テスト(PC・Windows で全部通過): 入口 単体 99・e2e_portal・e2e_autorun・e2e_window / スタジオ 単体 226(skip 1)・e2e_analyze・e2e_ui 113(単体・入口の中)/
  編集 単体 117(skip 1)・e2e 10本(v07・v08・v09・eval_v093・v098・handoff・edit_tabs・edit_cut・edit_pack・ui_mounted)/ cut2resolve 225(skip 14)/ ytt_core 51(skip 1)/
  tools: e2e_pipeline・e2e_datadir・test_ui_kit_sync・test_cleanup_legacy_data・test_push_helper・契約 25。Node.js が無いので test_review.cjs・test_document_save.cjs は流していない
- 実機で確かめてほしいこと(ユーザー): push.bat →「すべて終了」→ start-all.bat のあと、`docs/edit-tool-design.md` の「11」の E6 の5つ
  (入口のカード2枚と「編集で開く」・カット → パック → Resolve で区間と字幕が合うか・60fps → 30fps・初回の文字起こしの速さ・段階7と画面の見直し)
- 未完了・次: 実機確認の結果の直し。「編集」の残り(複数の切り抜きをつなげる・字幕のトラックでの時刻の直し)はユーザーが言い出したら。HANDOVER の「残りの作業」

## 2026-09-26 Claude Code — 追加機能 ①〜⑦ の受け付け(設計書の「12. 追加機能」)
- 担当: Claude Code(「編集」の実装と同じ担当。`transcribe-tool/`・`cut2resolve/`・`app/`・`ytt_core/txindex.py` に及ぶ)
- 変更: `docs/edit-tool-design.md` に「**12. 追加機能**」(ユーザーの指示・順番・決定・確認が要る所)。ユーザーの指示は「11」だったが、11 は「実装で決めたこと」で使っているので 12 にした
- 順番: E1〜E6 は実装済みなので ⑥(語頭・語尾が切れる)→ ④(パックの出力を最小限に)→ ③-1(疑わしい行を見つける・数える → 報告)→ ②(字幕の文字数。初期値を確認してから)→
  ①⑤・⑦(方式・作り方を確認してから)→ ③-2(③-1 の結果を見てユーザーが決めてから)
- 未完了・次: ⑥ から始める

## 2026-09-26 Claude Code — 追加機能 ⑥ 語頭・語尾が切れる(「行から」の区間の端を声の止まる所まで広げる)
- 変更(cut2resolve): `pack.py`(`RowEdge`・`ROW_EDGE`・`row_edge_from`・`widen_row_edges`・`row_edge_pending`・`without_detect`・`_cut_row_frames`、
  `TRANSCRIPT_ROWS` に row_edge、`plan_cut` の rows で端を広げる、CLI の表示)、`serve.py`(`spec.rowEdge`)、`cut2resolve.py`(`--no-row-edge`)、`README.txt`
- 変更(編集 `transcribe-tool/`): `resolve_export.py`(下書き・zip に設定の rowEdge、SLOTS の順番を待てないときは決まった余白)、`serve.py`(`/api/edit/draft` はカットが保存済みなら
  「行から」を計算しない・`rows=1`・`DRAFT_SLOT_WAIT`、zip に rowEdge)、`cut.js`(「行から ▾」の設定・`rows=1`・行を削るとき前後の切れ端も削る)、`index.html`、`app.js`(putSettings を渡す)、`README.txt`
- 変更(入口): `app/autorun.py`(カットの無い文書のパックに、文字起こしの設定の rowEdge を渡す)
- テスト: `cut2resolve/test_pack.py`(TestRowEdgeRule・TestRowEdgeWithAudio)・`test_serve.py`、`tools/test_resolve_pack_contract.py`(RowEdgeContract を新規。A は広げない設定で一本化の前と比べる)、
  `transcribe-tool/test_edit.py`(下書き・設定・SLOTS)・`test_resolve_export.py`・`e2e_edit_cut.py`、`app/test_autorun.py`。
  PC で通過: cut2resolve 255(skip 14)・契約 27・入口の autorun/mount・編集の単体 118(skip 1)・e2e(edit_cut・edit_pack・edit_tabs・ui_mounted・ui_handoff)
- **契約テストの期待値を変えた理由**: ⑥ で「行から」のカットの端が広がるのはユーザーの決定(意図した変更)。変えたのは区間の終わり・始まりだけで、
  行の時間を残す規則そのもの(広げない設定)は一本化の前(LEGACY)と同じことを A で確かめ続ける。詳細は `docs/edit-tool-design.md` の 12 ⑥「実装で決めたこと」
- 決定・理由: カット済の行は越えない(越えると向こう側に切れ端が残る)・決まった余白も上限の中・カットが保存済みの文書では開くたびに無音を調べない・
  行を削ると広げた切れ端も削る。−35dB・0.15 秒は本物の文字起こし 22 本で測って据え置き(設計書に数字)
- 版: 据え置き(④ のあとでまとめて上げる)
- 実機で確かめてほしいこと(ユーザー): 語頭・語尾が切れていた切り抜きで聞き比べ(手順は中間報告と設計書の 12 ⑥)
- 未完了・次: ④ パックの出力を最小限に

## 2026-09-26 Claude Code — 追加機能 ④ パックの出力を最小限に(cut-plan.json は作業データの記録へ)・版上げ
- 変更(cut2resolve): `pack.py`(`pack_paths`・`planned_outputs`・`build_pack` に `backup`・`plan_file`。Text+ の .json を出さない・cut-plan の中身は `plan` で返す)、
  `resolve_textplus.py`(.json を書かない・手順書の予備の案内を backup しだいに・`read_script_plan` = Lua に埋め込んだ計画を読み直す)、
  `serve.py`(`output.backup`・API は `plan_file=False`・**パックを作った記録 `packs/<ハッシュ>.json`**(`write_pack_record`)・`is_pack_dir` は txindex へ・起動時に `use_packs_dir`)、README
- 変更(ytt_core 1.2.0): `txindex.py`(`packs_dir`・`use_packs_dir`・`pack_key`・`read_pack_record`・`is_pack_dir`・`pack_info` は記録 → 以前の cut-plan.json)
- 変更(編集): `pack-tab.js`・`index.html`(パックに入れるもの・「予備も入れる」)、`serve.py`(手順書の表示は `txindex.is_pack_dir`・zip に backup)、`resolve_export.py`(zip も最小限)、README・AGENTS.md
- 変更(ほか): `.gitignore`(`cut2resolve/packs/`。YTT_DATA_DIR=inplace のとき)、`docs/pipeline.md`・`docs/edit-tool-design.md`(3 パック の「パックに入れるもの」・12 ④ の実装で決めたこと・① のユーザー指定の見た目)・`docs/HANDOVER.md`
- 版: 編集(文字起こし)0.16.0 → **0.17.0**・cut2resolve 0.11.0 → **0.12.0**・入口 0.10.0 → **0.10.1**・ytt_core 1.1.0 → **1.2.0**(⑥ と ④ の分。各ツールの3か所)
- テスト: cut2resolve(TestMinimalPack・test_serve の最小限/予備/記録/フォルダを開く)・ytt_core(test_pack_record)・契約テスト(B は最小限と予備ありの両方で zip = API のパック。
  区間・字幕は Lua から読む)・編集(test_resolve_export・test_edit・e2e_edit_pack・e2e_ui_mounted)・入口(e2e_autorun)。
  PC で通過: cut2resolve 265(skip 14)・ytt_core/tools 62・契約 27・入口の単体 100・編集の単体 118・e2e(edit_pack・ui_mounted・edit_cut・edit_tabs・ui_handoff・
  app/e2e_autorun・app/e2e_portal・tools/e2e_pipeline)
- **契約テストの期待値を変えた理由**: ④ でパックの中身から textplus-import.json・cut-plan.json・(既定で)EDL・SRT・予備の手順書を外すのはユーザーの決定。
  「zip = cut2resolve の API のパック」は同じ条件(最小限・予備あり)で比べ続け、区間・字幕は Lua に埋め込んだ計画で確かめる(中身は同じ)
- 決定・理由: 記録は cut2resolve の作業データ(パックを作るのは cut2resolve のため)。読むのは txindex だけ。記録したファイルがフォルダに無ければ記録を使わない。
  コマンド(cut2resolve.py)は今までどおりフォルダに cut-plan.json・EDL を書く(作業データの無い使い方)。以前のパックも「パック済み」「フォルダを開く」のまま
- ユーザーから字幕の見た目の指定(`C:\Users\you11\Desktop\素材` の画像4枚・けいふぉんと)→ 設計書の 12 ①⑤ に記録。**けいふぉんとの規約に再配布の許可が書かれていない**ので、
  パックに .ttf を入れるかはユーザーの確認待ち。反映のしかた(雛形 / スクリプトが値を入れる)はこのあと確認
- 注意: `cut2resolve/test_serve.py` の `TestPathsAndUploads.test_upload` が Windows でまれに WinError 10053(断った要求の接続の打ち切り)で落ちる。今回の変更とは関係なく、流し直すと通る
  `transcribe-tool/e2e_ui_mounted.py` の 3c(パックのタブ)も、続けて流したときに1回だけ「パックを作る」が押せるようになる前に確かめて落ちた → ボタンが押せるまで待つように直した
- 未完了・次: ① の反映のしかたを確認 → ③-1(疑わしい行を見つける・数える → 報告)→ ②(初期値の確認)→ ⑤・⑦ → ③-2
- 実機で確かめてほしいこと(ユーザー): 「パックを作る」で、フォルダの中身が6つ(media・.lua・.drb・.ps1・.bat・友人へ.txt)になり、Resolve でこれまでどおり取り込めること。
  「予備も入れる」で EDL・予備の手順書・SRT が増えること。以前に作ったパックが一覧で「パック済み」のままなこと

## 2026-09-26 Claude Code — 追加機能 ① Text+ 字幕の見た目をユーザーの指定に(けいふぉんと・黒い文字・白いふち・黒いふち)
- ユーザーの指定: `C:\Users\you11\Desktop\素材` の Resolve の Text+ のインスペクタの画像4枚(値は `docs/edit-tool-design.md` の 12 ①⑤)。
  回答(2026-09-26): スクリプトが値を入れる(雛形方式ではない)・けいふぉんと はパックに入れない(規約に再配布の許可が書かれていない)・縦・横とも同じ
- 変更(cut2resolve): `resolve_textplus.py`(`TEXT_STYLE` を指定の見た目に・`style_inputs()`・Lua: 指定のフォント → 無ければ自動選択で黄色・値を入れて最初の字幕で読み直し、
  入らなかった入力をマーカーのメモに・友人へ.txt に けいふぉんと の入れ方と黄色のマーカーの読み方)、`resolve_lua_mock.lua`(GetInput・無い入力のまね・出力に見た目)、`test_pack.py`、README
- 変更(編集): `index.html`(字幕の見本の CSS `.tt-cap-look`・パックのタブの見出し)、`pack-tab.js`(見本・注意の文)、README
- テスト: PC に **conda-forge の lua(5.5)を入れた**(テスト専用。ユーザー承認 2026-09-26)→ 偽の Resolve で Lua を動かすテスト 16 件も PC で流せるようになった。
  **conda がついでに openssl・vc・vs2015_runtime を conda-forge の新しい版に置き換えた**(miniconda の基本の環境。Python 3.12.3・ssl・Playwright は動くことを確認)。
  PC で通過: cut2resolve 271(飛ばし 0)・契約・編集の単体・e2e(edit_pack・edit_cut・ui_mounted)
- 版: 据え置き(編集 0.17.0・cut2resolve 0.12.0 はまだ配っていないので、同じ版の変更点に足した)
- 実機で確かめてほしいこと(ユーザー): けいふぉんと を入れた PC でパックを作り → bat → スクリプトを実行し、(1) 先頭のマーカーが緑で、メモに「見た目 けいふぉんと・黒い文字・白いふち・黒いふち」
  だけ(「反映できなかった」が無い)、(2) Text+ を選んだインスペクタの値が素材の画像と同じ(大きさ 0.14・アンカー・シェード 1/2/5)、(3) 字幕の位置が今までと比べておかしくないか
  (アンカーを下にしたので、字幕の下端が今までの位置の中心あたりに来る可能性がある)。「反映できなかった: …」が出たら、その名前を教えてほしい(入力の名前を直す)
- 未完了・次: ⑤(b) 横の素材を縦にする作業をやるかの確認。順番どおり ③-1(疑わしい行を見つける・数える → 報告)→ ②(初期値の確認)→ ⑦ → ③-2

## 2026-09-26 Claude Code — 追加機能 ③-1 長い区間に文字が少ない行を見つける・数える(結果の報告)・テストの不安定さ2つを直す
- 変更(編集): `transcribe-tool/serve.py`(`sparse_row`・`text_chars`・`SPARSE_MIN_SEC` 4.0 秒より長く・`SPARSE_MAX_CPS` 1.5 文字/秒未満・`make_flags` に
  「長い区間に文字が少ない(抜けの可能性)」)、`test_metrics.py`、README。以前の文書の印は変えない(新しく認識した行から)
- 新規: `tools/count_sparse_rows.py`(作業データを読むだけの集計。機械の出力と今の行・評価用と最近の文字起こし)
- **結果**(PC の作業データ 28 本): 評価用 10 本(129 行・460 秒)は **0 行**。最近の 18 本(263 行・754 秒)は **6 行(2.3%)・69.5 秒(長さの 9.2%)・5 本**。
  最長は 20.4 秒に 5 文字。large-v3 と large-v3-turbo の両方で出る。**28 本とも VAD は「普通」(normal)**で文字起こししていた(「弱い」は 0 本)→ 見立ての
  「VAD を甘くしているから」は今ある文書には当てはまらない。詳しくは `docs/edit-tool-design.md` の 12 ③-1
- 境目: ちょうど 4.0 秒は含めない(疑似の文字起こしの行 = 4.0 秒に「テスト文N」が全部当たり、`e2e_ui_v08` の「F で次の要確認へ」などが崩れたため。本物の行に 4.0 秒ちょうどは無かった)
- テストの不安定さを直した(どちらも今回の機能とは別):
  1. **ffmpeg 9.0.1(winget の Gyan 版)の VP9 を複数スレッドで符号化すると、PC で 1 割ほど 0xC0000005 で落ちる**(1 スレッド・H.264 は 0 回。miniconda の PATH とは無関係と確認)。
     テスト用の webm を作る所に `-threads 1`(`e2e_edit_common.py`・`e2e_ui_mounted.py`・`tools/demo_env.py`・`clip-studio/e2e_ui.py`)。ツール本体は VP9 で書き出さない
  2. `e2e_ui_mounted.py` が「編集」の ping だけ待って画面を開き、cut2resolve の取り込みが遅れると「cut2resolve が起動していない」になっていた → cut2resolve の ping も待つ。
     止まったときに `#pkOff` の理由を出すようにした
- 未完了・次(ユーザーの判断待ち): ③-2 をどうするか(③-1 の結果を見て)・② の初期値(縦 16・横 28 の案)・⑤(b) をやるか・⑦ の作り方

## 2026-09-27 Claude Code — 追加機能 ② 1つの字幕の文字数(縦 16・横 28)・単語の時刻の保存・今の文書を分け直す・パックの字幕の2段
- ユーザーの回答(2026-09-26): 縦 16・横 28、パックの字幕は2段(縦 8・横 14 前後で改行。改行の文字数は縦用・横用の設定)、行を分けるときの向きは設定「字幕の向き」(既定 縦)、
  ⑤(b) 横の素材を縦にする作業はやらない、③-2 は設計どおり作る(⑦ のあと)
- 変更(編集 `transcribe-tool/`): `serve.py`(`subtitle_settings`・`split_chars_for`・`SPLIT_SLACK`・`_cut_words` の同じ種類の文字の途中を避ける・
  `split_segment(max_chars)` が行の単語を `_words` に・**単語の時刻 `transcripts/<id>.words.json`**(`read_words`・`write_words`・`replace_words`・`row_words`)を
  認識のジョブと範囲の再認識で保存・削除で消す・**`POST /api/resplit`**(`resplit_doc`)・見積もりの見本 `samples`・zip の `wrap`)、`resolve_export.py`、
  `app.js`(新規の「字幕の文字数」・要求に `subtitleOrientation`/`splitChars`・「今の文書を分け直す」`resplitDoc`)、`index.html`、`pack-tab.js`(`textplusWrap`・見本を2段で)、README・AGENTS.md
- 変更(cut2resolve): `resolve_textplus.py`(**`wrap_caption`**・`WRAP_DEFAULT`・`default_wrap`・`build_import_plan(wrap)` が Text+ の字幕だけに改行・計画に `captionWrap`)、
  `pack.py`(`build_pack(textplus_wrap)`)、`serve.py`(`output.textplusWrap` 0〜40)、README
- 変更(入口): `app/autorun.py`(Text+ の改行の文字数 = 文字起こしの設定 `subtitle.wrapChars.vertical`)、README
- テスト: `test_metrics`・`test_worker`・`test_edit`・`e2e_edit_tabs`・`cut2resolve/test_pack`・`test_serve`・`app/test_autorun`。PC で通過(e2e 一式は下)
- 決定・理由: 単語の時刻は行ではなく文書に1つ(行の id・順番が画面で変わっても使える)。分け直すのは文字が単語と一致する行だけ(人の直しを壊さない)。短い行はつながない。
  改行の規則は cut2resolve に1か所(Text+ に入れるのは cut2resolve のため。画面の見本もその結果を出す)。**ひらがなだけの文は語の途中で改行されることがある**(辞書を使わないための限界)
- 版: 据え置き(編集 0.17.0・cut2resolve 0.12.0・入口 0.10.1 の変更点に足した。まだ配っていない)
- 実機で確かめてほしいこと(ユーザー): 新しく文字起こしした行が 16 文字(+2)以内に分かれるか・「今の文書を分け直す」・パックの Text+ 字幕が2段で画面に収まるか(大きさ 0.14 と合わせて)
- テスト(PC): 編集の単体 122・cut2resolve 275・契約 27・ytt_core/tools・入口の autorun・e2e(edit_pack・edit_cut・edit_tabs・ui_mounted・ui_handoff・v098・v07・v08・v09・eval_v093・app/e2e_autorun・tools/e2e_pipeline)。`e2e_ui_v08` の「保管の状況」は結果より少し遅れて「済」になるので待つように直した
- 注意: 同じ時間に**別の Claude Code のセッションが「ホロカラー」(`holo-colors/`)を作っていて**、`.gitignore`・`AGENTS.md`・`README.txt` にその変更(未コミット)がある。このコミットには含めていない(触っていない)
- ⑦ の作り方(ユーザー 2026-09-27): 案のとおり(設計書の 12 ⑦)・カットのある文書はカットのとおり
- 未完了・次: ⑦ → ③-2

## 2026-09-27 Claude Code — 新しいツール「ホロカラー」(holo-colors。メンバーカラーをキーで呼び出してコピーする Windows のアプリ)
- 担当: Claude Code(`holo-colors/`・`docs/holo-colors.md`。AGENTS.md の担当表に追記)。既存の3ツール・入口には触っていない
- ユーザーの依頼(2026-09-26): 既存のツールとは別に、キーボードショートカットで呼び出し、ホロライブのメンバーカラーをクリックでコピー・自分で色を足せる・コピーしたら閉じる(閉じない設定も)
- 決定(ユーザー): ブラウザではなく Windows のアプリ / **主に友人が使う** → Python + tkinter から **C#(WinForms)の exe** に変更(友人の PC に Python が要らない。
  Windows に入っている .NET Framework 4 の csc で作る。C# 5 まで)/ メンバーは JP・DEV_IS・EN・ID・卒業 + 新ユニット「アソビ★まわり隊！」/ サインイン時の起動は設定で選ぶ
- 追加: `holo-colors/`(`src/*.cs`・`app.manifest`・`app.ico`・`members.json`(86 人)・`tests/CoreTests.cs`・`build.bat`・`e2e_holo_colors.py`・`make_icon.py`・`README.txt`)、`docs/holo-colors.md`(設計・色の出典・リスク)
- 変更: `AGENTS.md`(全体の形・表・担当表)、`README.txt`(別のツールとして案内)、`.gitignore`(`holo-colors/build/`・`dist/`・`data/`)
- 版: ホロカラー **1.0.0**(`src/Core.cs` の AppInfo.Version と README の見出し)
- メンバーの色: 主な出典はホロジュール(カバーの配信予定サイトのアイコンの縁の色)。調べ物は下請けの調査(Wayback の保存版 約150件と wiki・公式サイトで照合)、
  Claude Code が今のホロジュールで一致・公式サイトの卒業生の一覧(天音かなた・火威青)・アソビ★まわり隊！の区分を取り直して確かめた。人見クリスは色の資料が無いので入れていない
- テスト(PC で通過): `build.bat`(単体 15 件)・`python holo-colors/e2e_holo_colors.py`(本物のキー入力で 15 件。ユーザーの許可を得て流した)。画面は `--screenshot <フォルダ>` の画像で確認
- 成果物: `holo-colors/dist/HoloColors.zip`(exe・members.json・README。git には入れない。build.bat で作り直せる)
- 未決(ユーザーに確認): 出典どうしで色合いが大きく違う4人(アキ・ローゼンタール・角巻わため・アイラニ・イオフィフティーン・九十九佐命。今はホロジュールの色)。`docs/holo-colors.md` の「メンバーの色」
- 注意: exe は未署名なので、友人の PC では初回に SmartScreen の確認が出る(README に手順)。既定のキー Ctrl+Alt+H は Resolve などより先に取る(設定で変えられる)。
  e2e は本物の入力を送るので、流す前にユーザーに確認する(キーを送る前に前面の窓を確かめて止まる安全装置はある)
- 同じ時間に別のセッションが「編集」の追加機能を進めていた(上の記録・未コミットの変更)。このコミットには入れていない

## 2026-09-27 Claude Code — 追加機能 ⑦ 案件の一覧以外から「まとめて実行」(スタジオの配信の画面・「編集」の履歴で選んだ文書)
- ユーザーの回答(2026-09-27): 作り方は案のとおり(設計書の 12 ⑦)・カットのある文書はカットのとおり
- 変更(入口 `app/`): `autorun.py`(**文書単位の実行** `start_docs`・`Run(doc_id, overwrite)`・`_execute_doc`・`_doc_transcribe`(intoDoc)・`_doc_pack`、
  パックを1本作る所を `_pack_one` に切り出して配信単位の実行と共通に・`_pack_settings`)、`launch.py`(`POST /api/autorun/start-docs`)、`test_autorun.py`(TestDocs 5件)、README
- 変更(編集): `app.js`・`index.html`(履歴の「選んで、まとめて実行」・進み具合と中止・入口の API は画面の場所からの相対)、`e2e_edit_pack.py`、README
- 変更(スタジオ): `review.js`・`review.css`(③ の上の帯に「まとめて実行 ▾」・進み具合の帯)、`e2e_ui.py`、版 0.8.1 → **0.8.2**(serve.py・core.js・README)
- 決定・理由: 文書ごとに1つの実行にした(配信単位の実行と同じ順番待ち・中止・状態の API をそのまま使え、二重の登録を文書ごとに断れる)。
  パックの作り方は配信単位と同じ関数(二重の実装にしない)。入口に取り込まれていないときは、どちらの画面にも出さない
- 版: 編集 0.17.0・入口 0.10.1 の変更点に足した(まだ配っていない)・スタジオ 0.8.2
- テスト(PC): 入口の単体・e2e_portal・e2e_autorun・e2e_window・スタジオの単体・e2e_ui(入口の中 117・単体 114)・e2e_analyze・編集の e2e(edit_pack・edit_tabs・ui_mounted)・e2e_pipeline
- **注意(PC が不安定)**: テスト中に、関係の無いプログラムがランダムに異常終了した(1スレッドの ffmpeg の 0xC0000005・Python 本体の Segmentation fault・Playwright の node・chromium のタブ)。流し直すと通る。Windows のイベントログ(読むだけ)では、直近3日で dwm.exe が 256 回・Defender など常駐プログラムも 0xC0000005 で落ちていた。CPU は i9-13900KF・マイクロコード 0x10B・BIOS 1.10(2022-09)。13/14世代の不安定さ(古いマイクロコードで劣化が進む。Intel が 0x129 以降で対策)と症状が合う → ユーザーに BIOS の更新などを案内した。**テストが1回だけ異常終了で落ちたときは、まず流し直す**(コードの不具合と決めつけない)
- 未完了・次: ③-2(疑わしい所だけ認識し直す。ユーザー承認済み = 設計どおり)

## 2026-09-27 Claude Code — ホロカラー 1.0.1: スクロールすると文字だけ動かない不具合・build.bat が壊れた zip でも「Done」
- ユーザーの報告: 「スクロールに表示が対応していない」
- 原因: `holo-colors/src/PaletteView.cs` の描画で `Graphics.TranslateTransform` を使っていたが、文字を描く TextRenderer は Transform を無視するので、
  色の札はスクロールで動くのに名前とカラーコードの文字だけ元の位置に描かれていた(スクロールしない画面の確認では見えなかった)
- 変更: `PaletteView.cs`(スクロールの分の座標を自分でずらす・見えない札は描かない・ホイールやスクロールバーで動かしたあともマウスの下の枠を合わせる・
  検索欄の上のホイールの量を整数の割り算の前に掛ける(タッチパッドの細かい回転で動かなかった))、`Program.cs`(`--screenshot` にスクロールした画面)、
  `tests/CoreTests.cs`(**スクロールした絵 = スクロールしていない絵をずらしたもの** を画素で比べる。直す前は 4635 点違って失敗することを確かめた)
- 変更: `build.bat`(zip は失敗したら 1 秒待って 5 回まで・中身が 3 つか確かめる・dist へのコピーの失敗も止める)。書いた直後の exe をウイルス対策ソフトが掴んで、
  exe の入っていない zip(10KB)ができたのに「Done」と出ていた
- 版: ホロカラー 1.0.0 → **1.0.1**(Core.cs・README)。`docs/holo-colors.md`・`AGENTS.md` のテストの件数(16)
- テスト(PC で通過): build.bat の単体 16 件。e2e は流していない(直したのは描画とホイールで、e2e が確かめるキー・フォーカスには触れていない)
- 注意: build.bat は最初に `--quit` で、普段の作業データで動いているホロカラーを終わらせる(exe を上書きするため)。PC で試しているときに build.bat を流すと閉じる

## 2026-09-27 Claude Code — 追加機能 ③-2 疑わしい所だけ認識し直す(良くなったときだけ置き換える・既定オフの自動)
- ユーザーの判断(2026-09-26): ③-1 の結果を見て「設計どおり作る」
- 変更(編集 `transcribe-tool/`): `serve.py`(ジョブ `redo`・`POST /api/redo`・`redo_targets`・`redo_spec`・`redo_kwargs`(VAD 普通・短く区切る)・`redo_better`・`apply_redo`・`run_redo`、
  時間の上限 `REDO_MAX_SEC` 600 秒・1回 30 行まで、`EXCLUSIVE` に redo、文字起こしのジョブが疑わしい行の avg_logprob を覚えて `autoRedo` なら redo のジョブを足す、
  範囲の行に `lp`)、`app.js`・`index.html`(新規の「疑わしい所を自動で認識し直す」(既定オフ)・「kotoba なら large-v3」・「文字をまとめて直す」の「疑わしい所を認識し直す」・
  編集を止める・終わったら読み直す)、`test_metrics`・`test_edit`・`test_worker`・`e2e_edit_tabs`、README・AGENTS.md
- 変更(入口): `app/autorun.py`(`TX_KEYS` に autoRedo・redoLarge)、README
- 決定・理由(詳しくは設計書の 12 ③-2): 範囲は前後 1 秒でも隣の行にはかからない(隣の行を消さない)。機械の出力のある文書では、機械の出力と同じ文字の行だけ(人の直しを壊さない)。
  置き換えは最後にまとめて1回(中止 = 何も変えない・前の版は履歴)。手で押したときは元の avg_logprob が分からないので、文字の数と疑わしい印だけで比べる
- 版: 編集 0.17.0・入口 0.10.1 の変更点に足した(まだ配っていない)
- 実機で確かめてほしいこと(ユーザー): ③-1 で見つかった6か所(例: 20.4 秒に「いや、なんだ!」)の文書を開いて「疑わしい所を認識し直す」→ 置き換わるか・内容が正しいか
- テスト(PC・全部): 入口の単体・ytt_core/tools 71・契約 27・cut2resolve 275・編集の単体 125・スタジオの単体 226・e2e(編集 10 本・入口 3 本・スタジオ 単体/入口の中・e2e_analyze・e2e_pipeline・e2e_datadir)
- 文書: `docs/HANDOVER.md` を書き直した(追加機能 ①〜⑦ が終わった状態・PC の不安定さの注意・次のセッションの指示文)
- 未完了・次: 追加機能 ①〜⑦ はこれで全部。実機の確認の結果の直し

## 2026-09-27 Claude Code — ホロカラー 1.1.0: 一番手前に残り続けないように・不具合探しと見た目
- ユーザーの指摘: 「キーを押したとき前面に出るのはいいけど、閉じない時にも残り続けてうざい」「全体的なバグ探しや見た目の分かりやすさを改善」
- 変更(動き): 一覧の窓を「常に手前」にしない(キーで呼んだときに前に出すだけ。設定の「一覧をいつも一番手前に表示する」で戻せる)、Esc はまず検索の文字を消す
- 不具合探し: 下請けの見直し(コードを読むだけ)の 19 件を Claude Code が確かめて直した。主なもの:
  作業データが一瞬開けないと設定・マイカラーを初めの状態で上書きしていた(読み直し → だめなら保存を止める)/ 保存の失敗を元に戻さなかった /
  Alt+F4・Ctrl+V・F キー単独も呼び出しのキーにできた(`Hotkey.Problem` で断る)/ 一覧を開いたまま別のアプリへ移ると戻る先が古いまま /
  設定のキーの欄から別のアプリへ移るとキーが外れたまま / ほかのプログラムから閉じられると以後エラー / 高い DPI で欄が小さい(`Ui.Px`)/
  フォント・アイコンの作りっぱなし(`Ui` で使い回す)/ .NET 4.7 より前で落ちる(DeviceDpi をやめた)/ zip の中から起動したときの案内・自動起動を使えなくする /
  自動起動が別の場所を指すときの「付け直す」/ キーの欄から Tab・Shift+Tab・Enter・Esc で出られない / 選択済みの札を押すと検索欄からフォーカスが外れる /
  通知領域のアイコンのクリックでダイアログの下の一覧だけ隠れる / build.bat が動いているホロカラーを黙って終わらせ、1 秒しか待たなかった
- 変更(見た目): 見出し(区分の札・太字・人数・線)、下の段を2段に(知らせは横いっぱい: ふだんはヒント、コピーしたら色の見本つき、初回は「× で閉じても通知領域で待っています」)、
  閉じない設定でコピーした札に「✓ コピーしました」、開いた直後は選択の枠を出さない(文字を打つか矢印を使ったら出す)
- 版: ホロカラー 1.0.1 → **1.1.0**(Core.cs・README)。`docs/holo-colors.md`(決めたことに追記)・`AGENTS.md`(テストの件数)
- テスト(PC で通過): build.bat の単体 17 件(開けなかったファイルと保存の失敗を足した)・e2e 20 件(Esc・開いたまま移った窓へ戻る・一番手前ではない を足した。ユーザーの許可を得て流した)

## 2026-09-27 Claude Code — 実機の確認の結果の直し(1): パックに media フォルダ・友人へ.txt を作らない・Text+ の重ね順
- ユーザーの実機の確認(Resolve): ④ パックの中身は OK だが「media フォルダは中が1つだから分けなくていい」「友人へ.txt もいらない」。
  ① 見た目は「ダメ」。マーカーのメモ「見た目 … (反映できなかった: Priority1, Priority2, Priority5)」= 重ね順(優先順位)が入らず、太い黒ふち(要素5)が白ふちの上に描かれた可能性が高い。
  ③ 語頭・語尾の聞き比べ・③-2 の6か所は保留
- 変更(cut2resolve): `pack.py`(動画はパックの直下・`readme_file`(画面・API は False = 友人へ.txt を書かない。コマンドは True)・以前の `media\<動画>` が残っていれば「前に作った…」で知らせる(消さない)・
  画面に出す手順は書かなくても `readme` で返す)、`cut2resolve_core.write_pack`(`readme_path=False` で書かない・中身は `readme_text`)、
  `resolve_textplus.py`(登録用 ps1・計画の動画の場所を直下に・手順書の文言・`readme_text`・`readme_from_script`(パックの Lua から手順を作り直す)・
  **重ね順の読み替え**: 名前で入らなければ Resolve の入力の一覧(`GetInputList`)から表示名「Priority」と要素の番号で探す → 候補の名前 `PriorityBack<n>` の順に試し、
  入った名前はメモに「入力の名前を読み替え: …」(緑のまま)。それでも入らなければ黄色・入力の一覧をパックのフォルダの `textplus-inputs.txt` に書く)、
  `serve.py`(API は readme_file=False)、`resolve_lua_mock.lua`(GetInputList)
- 変更(編集): `resolve_export.py`(zip も手順書なし・`pack_instructions`)、`serve.py`(`/api/edit/pack-readme` は Lua から作り直す。以前のパックは中の手順書)、
  `pack-tab.js`・`index.html`(「友人へ.txt を見る」→「Resolve での手順を見る」・入れるものの説明)
- 決定・理由: 優先順位の入力名は Web に無く、Resolve 本体の `Plugins\text.plugin` の文字列を調べた(読むだけ)。入力名は「名前 + 要素の番号」(`%s%d`)で作られ、
  位置の欄の近くに `PriorityBack` という名前があった(表示名は「Priority」)。決め打ちせず、実機の入力の一覧から表示名で探すのを先にした(PriorityBack が別の意味でも誤って入れないため)。
  次の実機の確認でメモの「読み替え」の名前を見て、次の版で決め打ちにする。コマンド(cut2resolve.py)は人に渡す使い方もあるので 友人へ.txt を書き続ける
- 契約テストの期待値の変更(理由: ユーザーの指示でパックの形が変わった): B の cut2resolve 側を API と同じ `readme_file=False` に・余白つき素材の動画の場所 `media/clip_edit.mp4` → `clip_edit.mp4`
- 版: cut2resolve 0.12.0 → **0.13.0**、編集 0.17.0 → **0.17.1**(serve.py・app.js・README)
- テスト(PC): 入口の単体・ytt_core/tools 56・契約 27・cut2resolve 279・編集の単体 125・e2e(編集 tabs/cut/pack/mounted/handoff・入口 autorun/portal・e2e_pipeline)
- 実機で確かめてほしいこと(ユーザー): パックを作り直して Resolve で実行 → 白いふちが黒いふちの上に見えるか・マーカーのメモ(「読み替え: …」または「反映できなかった … 入力の一覧: textplus-inputs.txt」)。
  まだおかしければ、Resolve の画面の写真と、パックにできた textplus-inputs.txt を送ってもらう

## 2026-09-27 Claude Code — 実機の確認のあとの要望(2): 入口が二つにならない・UI の 10 の原則の資料・要望の設計
- ユーザーの要望(2026-09-27): ①出力先の途中のファイルを下のフォルダへ ②bat と「他のツール」から入ると入口が二つになる ③UI は NN/g の 10 の原則を学んでほしい(原則に沿った変更は Cowork で)
  ④まとめて実行を各段階から ⑤配信者の名前で字幕の色(手で入れたときだけ・まとめて実行でも)。決めたことと設計は **`docs/followup-2026-09-27.md`**
- ユーザーの回答: ① パックと元動画以外を下へ ② 開いている入口を前に出す ④ ユーザーが作業する各段階に ⑤ 文字を色に
- 変更(②): `ui-kit/ui-kit.js`(v5。`UIKit.portal`: 入口へ戻るリンク `a[data-ui-portal]` は、BroadcastChannel で入口の画面に問い合わせ、あれば移らずに
  `api/ytt/focus-portal`・前に出せなければ知らせる・無ければ今までどおり移る)→ `tools/sync_ui_kit.py` で写した、`app/portal.js`(答える)、`app/cases.html`(← 入口へ)、
  `app/launch.py`(`focus-portal`・`PORTAL_TITLE`)、`app/appwindow.py`(`focus_window`: 題名で窓を探し、前面の窓のスレッドに入力をつないでから SetForegroundWindow・`Opener.focus`)
- 変更(③): `docs/usability-heuristics.md`(新規。10 の原則の要点・このツール群での当てはめ方・確かめ方・気づいたこと)、`docs/ui-guidelines.md`・`AGENTS.md` からリンク。画面は変えていない
- 版: 入口 0.10.1 → **0.10.2**(launch.py・README)、ui-kit v4 → **v5**
- テスト(PC): `app/test_window.py`(窓を前に出す・API・題名が portal.html と同じ)、`app/e2e_window.py`(入口が開いていれば移らずに頼む・前に出せなければ知らせる・
  「他のツール」の入口も・入口が無ければ移る。本物の窓は動かさないように focus を差し替え)、`e2e_portal`・スタジオ `e2e_ui --mounted`・編集 `e2e_ui_handoff`・`test_ui_kit_sync`
- 注意: `app/test_window.py` の `test_security_checks` が1回だけ ConnectionAbortedError で落ちた(403 を返してすぐ閉じる所の接続のタイミング。流し直すと通る。今回の変更とは関係ない)
- 実機で確かめてほしいこと(ユーザー): 窓で開く設定で、ツールの窓の「入口」→ 新しく開かずに bat で開いた入口の窓が前に出るか(本物の窓を前に出す所はテストで動かしていない)
- 未完了・次: ① 出力先の整理・⑤ 配信者の色・④ 各段階のまとめて実行(`docs/followup-2026-09-27.md` の順に)

## 2026-09-27 Claude Code — 実機のあとの要望(3): 配信者の名前で字幕の色(文字をメンバーカラーに)
- ユーザーの要望と決定: 配信者の名前を入れると、そのカラーコードで字幕を作る(手で入れたときだけ・まとめて実行でも)。**文字を色に**(白いふち・外側の黒いふちは同じ)。
  設計と実装で決めたことは `docs/followup-2026-09-27.md` の 4
- 変更(共通): `ytt_core/colors.py`(新規。名前 → メンバーカラーの照らし合わせの1か所。ホロカラーの `holo-colors/members.json` とマイカラー
  `%LOCALAPPDATA%\youtube-tools\holo-colors\my-colors.json` を読むだけ。かな・全角半角・大小・区切りを区別しない・名前の一部で1人に決まるときだけ・同じ名前はマイカラーが先)、
  `ui-kit`(`UIKit.streamer`: `<input data-ui-streamer>` に候補・色の見本・合う人。同じ名前ではもう一度照らし合わせない)→ 写した
- 変更(cut2resolve): `resolve_textplus.text_style(color)`(塗りの要素の色・見た目の名前)・`build_import_plan`/`write_files`/`readme_text`/`instructions` に色、
  `pack.build_pack(textplus_color=)`、`serve.py`(`output.streamer` → 400 bad_streamer・パックの記録に textColor・streamer)
- 変更(入口): `autorun.py`(`start`・`start_docs` の streamer。始める前に照らし合わせる・cut2resolve に照らし合わせた名前を渡す)、`launch.py`(`api/ytt/streamer-colors`・streamer を渡す)、
  `cases.html`・`cases.js`(配信者の欄)
- 変更(スタジオ): `review.js`(まとめて実行 ▾ に配信者の欄)。変更(編集): `index.html`・`pack-tab.js`(3 パック の「配信者(字幕の色)」・文書ごとに覚える・字幕の見本の色)、
  `app.js`・`index.html`(履歴の「選んで、まとめて実行」に配信者の欄)、`serve.py`・`resolve_export.py`(zip の streamer)
- 不具合(作る途中で見つけて直した): 名前を入れた直後に隣の「実行」を押すと、欄から離れたとき(change)にもう一度照らし合わせを始めて説明の文が縮み、
  ボタンが押している途中でずれてクリックが成立しなかった(画面のテストで見つけた。人も同じ目に遭う)→ 同じ名前では照らし合わせない・途中の「探しています…」を出さない
- ついでに直した: `clip-studio/test_review.cjs` の偽の環境に `pollAuto` が無く2件落ちていた(⑦ で `loadVideo` から呼ぶようにしたときの抜け。PC の bash から node が見えず流していなかった。
  **node は Playwright 同梱の `C:\Users\you11\miniconda3\Lib\site-packages\playwright\driver\node.exe` で流せる**)
- 版: まだ配っていない版の変更点に足した(cut2resolve 0.13.0・編集 0.17.1・入口 0.10.2・スタジオ 0.8.2・ui-kit v5)
- テスト(PC): 入口の単体 114・ytt_core/tools 60・契約 27・cut2resolve 281・編集の単体 125・スタジオの単体 226・node 18・
  e2e(編集 tabs/cut/pack/mounted/handoff・入口 autorun/portal/window・e2e_pipeline・e2e_datadir・スタジオ e2e_ui と --mounted)。
  入口の e2e 3本が「Page crashed」などの異常終了で1回落ちた(PC の不安定さ)→ 流し直して通過
- 実機で確かめてほしいこと(ユーザー): 3 パック で配信者の名前を入れてパック → Resolve の字幕の文字がその色か(重ね順の直しと一緒に)

## 2026-09-27 Claude Code — 実機のあとの要望(4): 出力先に途中のファイルを並べない(作業用フォルダ)
- ユーザーの要望と決定: 「出力先が汚くなるから途中出力のものをまとめて新たな下層のフォルダに入れる」→ **パックと元動画以外を下へ**。
  下のフォルダの名前・細かい決まりは、ユーザーが寝ていたので質問せずに決めた(`docs/followup-2026-09-27.md` の 1「実装で決めたこと」。違えば直す)
- 決まり: 動画のフォルダの直下は元動画(書き出した切り抜き)とパック(`_pack`)だけ。`.clip.json`・`.edit.json`・`_edit.mp4`・`_edit.clip.json`・`.transcript.json`・`.srt`・
  `.cut-plan.json`・`.studio-id` は下の **`作業用`** に書く。読む側は `作業用/` → 動画の隣(以前の置き方)の順に探す。以前のファイルは動かさない・消さない
- 変更(共通): `ytt_core/schemas.py`(`WORK_DIR`・`work_dir`・`media_folder`・`sidecar_path`・`sidecar_candidates`・`find_sidecar`・`find_clip_path`。
  `clip_path_for` は書く場所 = `作業用/`)、`txindex.offset`(両方を読む)
- 変更(スタジオ): `handoff.py`(.clip.json を 作業用/ に)、`exporter.py`(編集用素材と .edit.json を 作業用/ に書く spec・`.studio-id` は 作業用/(読むのは両方)・
  名前の重なりは直下と 作業用/ の両方・`SUFFIX_ROOM` 24 → 28)
- 変更(編集): `pipeline_io.py`(`save_beside` は 作業用/ に・`find_clip` は両方・`resolve_clip_media` は .clip.json が 作業用 の中なら動画は1つ上)、
  `serve.py`(たたき台「スタジオ」の .cut-plan.json は両方・フォルダ一括は 作業用 を拾わない)、画面の文言(「動画の隣に保存」→「作業用フォルダに保存」)
- 変更(cut2resolve): `cut2resolve_core.py`(`WORK_DIR`・余白つき素材の .edit.json は両方・文字起こしから動画を探す予備は 作業用 の1つ上も)、`serve.py`(隣の字幕・文字起こしの候補は両方)
- 文書: `docs/pipeline.md`(1 共通の約束に「途中のファイルの置き場所」・2.1・2.2・6)、`docs/data-location.md`、各 README・`transcribe-tool/AGENTS.md`
- 注意(直した): 説明文(docstring)に `作業用\ ` と書くと Python の「不正なエスケープ」の警告(将来はエラー)になる → `作業用/` と書く。
  変えた .py は `warnings.simplefilter("error")` で compile して確かめた
- 版: まだ配っていない版の変更点に足した(スタジオ 0.8.2・編集 0.17.1・cut2resolve 0.13.0・ytt_core)
- テスト(PC): 入口の単体・ytt_core/tools・契約 27・cut2resolve 283・編集の単体 125・スタジオの単体 227・node 18・e2e(編集 tabs/cut/pack/mounted/handoff・
  入口 autorun/portal/window・e2e_pipeline・e2e_datadir・スタジオ e2e_ui と --mounted)。
  `app/test_mount` の1件・入口の e2e_autorun・e2e_datadir・スタジオ e2e_ui が1回ずつ Playwright の node の異常終了(「module is not defined in ES module scope」・
  「Connection closed while reading from the driver」)などで落ちた → 流し直して通過(PC の不安定さ。テストの中身の前に落ちている)
- 実機で確かめてほしいこと(ユーザー): スタジオで書き出す → 出力先の配信のフォルダの直下が「切り抜きの mp4・_pack・作業用」だけか。以前の切り抜きも「編集」で開けるか

## 2026-09-27 Claude Code — 実機のあとの要望(5): まとめて実行を各段階から(「編集」の題名の行・スタジオのマークの行)・HANDOVER
- ユーザーの要望と決定: 「案件一覧からしかまとめて実行できなくて不便だから、各ツールからその後の作業をまとめてできる機能が欲しい」→ ⑦ の2か所を伝えたうえで
  **ユーザーが作業する各段階に欲しい**。足した入口と細かい決まりは、ユーザーが寝ていたので質問せずに決めた(`docs/followup-2026-09-27.md` の 3。違えば直す)
- 変更(入口): `autorun.py`(`start` の `marks` = そのマークだけ・`MAX_MARKS` 50・「解析から全部」とは組み合わせない・`_mine`/`_clips(v, run)` で書き出し・文字起こし・パックを絞る・
  `modeLabel` に「(n本)」)、`launch.py`(marks を渡す)
- 変更(スタジオ): `review.js`(採用・書き出し済みのマークの行に「この後を ▸」= そのマークだけ「採用後を全部」。入口から開いたときだけ。上の配信者の欄も使う)
- 変更(編集): `index.html`・`app.js`(題名の行に「まとめて実行 ▾」= 今の文書を `start-docs` で1本。先に文書とカットを保存・配信者の欄(パックのタブで入れた名前を入れる)・
  上書き・進み具合の札 `#pillAuto`・終わったら前回のパックを読み直す)
- 文書: `docs/followup-2026-09-27.md`(3 の実装で決めたこと)、`docs/usability-heuristics.md`(気づいたことを今の状態に・まとめて実行の入口が5か所になり見せ方が違う = 候補)、
  各 README・`transcribe-tool/AGENTS.md`、**`docs/HANDOVER.md` を書き直した**(今日の要望が終わった状態・次の実機の確認で重ね順の名前を決め打ちにする)
- 版: まだ配っていない版の変更点に足した(入口 0.10.2・スタジオ 0.8.2・編集 0.17.1)
- テスト(PC): 入口の単体 116・ytt_core/tools 60・契約 27・cut2resolve 283・編集の単体 125・スタジオの単体 227・node 18・
  e2e(編集 tabs/cut/pack(題名の行のまとめて実行・配信者の色)/mounted/handoff・入口 autorun/portal/window・e2e_pipeline・e2e_datadir・
  スタジオ e2e_ui(115 件)と --mounted(「この後を ▸」))。スタジオの e2e_ui が3回続けて Playwright の node の起動の異常終了で落ちた → 流し直して2回とも通過
- 実機で確かめてほしいこと(ユーザー): 「編集」の題名の行の「まとめて実行 ▾」・スタジオのマークの行の「この後を ▸」

## 2026-09-27 Claude Code — 2 回目の実機の確認は問題なし・次の要望(① 探す からのまとめて実行)を記録
- 決定・理由: ユーザー「実機で確かめてほしいことは問題ない」(重ね順・パックの形・配信者の色・入口を前に出す・作業用フォルダ・各段階のまとめて実行)。
  重ね順の入力の名前は決め打ちにしない(今の「`Priority<n>` → 表示名で探す → `PriorityBack<n>`」の方が Resolve の版の違いに強い)
- 次の要望(ユーザー): 「また後で、探すのところにもまとめて実行が欲しい」→ **まだ作らない**。案を `docs/followup-2026-09-27.md` の 5 に書いた
  (① 探す の配信はまだスタジオに無いので、`app/autorun.py` が配信 ID・題名・配信者を受けて解析のあとで読み直す形が要る。作る前に置き場所と中身をユーザーに見せる)
- 変更: 文書だけ(`docs/followup-2026-09-27.md` の 0・5、`docs/HANDOVER.md` の「今の状態」「残りの作業」「次のセッションに貼る指示文」)
- テスト(PC): コードは変えていない。前のコミットの確かめとして、スタジオの e2e_ui(115 件)と --mounted(120 件)を流し直して全部通過

## 2026-09-27 Claude Code — スタジオの ① 探す からもまとめて実行(選んだ配信を「解析から全部」)
- ユーザーの要望と決定: 「探すのところにもまとめて実行が欲しい」→ 記録したあと「素早く実行」。置き場所・中身は質問せずに決めた(`docs/followup-2026-09-27.md` の 5「実装で決めたこと」。違えば直す)
- 変更(入口): `autorun.py`(`start_new(items, top, streamer)` = まだスタジオに無い YouTube の配信を「解析から全部」で。配信ごとに1つの実行・10 本まで・
  すでに順番待ちの配信は skipped・`Run.fresh`(受け取った題名・配信者。`_video` が 404 のときだけ使い、解析のキューにも渡す)・`public()` に `fromSearch`)、
  `launch.py`(`POST /api/autorun/start-new`)
- 変更(スタジオ): `rank.js`(選んだときの段に「まとめて実行」= 採用する数・配信者(字幕の色)・「選んだ配信 n 本をまとめて実行」。チャンネルが違う配信を選んだら注意の文。
  行の印「まとめて実行の順番待ち / 中」・その間はチェックできない。入口から開いたときだけ)、`core.js`(入口の API を呼ぶ `Studio.portalApi` を1つに)、
  `review.js`(`portalApi` は `Studio.portalApi` を使う)、`app.css`
- テスト: `app/test_autorun.py` に TestNew(新しい配信の通し・解析済みなら解析を飛ばす・検査と skipped)、`clip-studio/e2e_ui.py --mounted` に ① 探す のまとめて実行
  (入口の API は偽物に差し替えて送る中身と行の印・本物の start-new が空を断る)、単体で開いたときは出ない
- 文書: `README.txt`・`clip-studio/README.txt`・`app/README.txt`、`docs/followup-2026-09-27.md` の 5、`docs/usability-heuristics.md`(入口が6か所)、`docs/HANDOVER.md`
- 版: まだ配っていない版の変更点に足した(入口 0.10.2・スタジオ 0.8.2)
- テスト(PC): 入口の単体 119・スタジオの単体 227・node 18・スタジオ e2e_ui(116 件)と --mounted(126 件。① 探す のまとめて実行を含む)・入口 e2e_autorun・e2e_portal。
  スタジオの e2e_ui が1回「設定を開いている間は ③ のショートカットが効かない」で落ちた(今回触っていない所・時間の揺れ)→ 流し直して通過

## 2026-09-27 Claude(Cowork)— 画面の全面見直しのデザインブリーフ(ui-dev-workflow の段階1〜2)
- 変更: `.design/ui-overhaul/DESIGN_BRIEF.md` を新しく作った(文書だけ。コードは変えていない)
- 決定・理由(ユーザーとの質問で決定・ブリーフはユーザー承認済み):
  - 対象は Web の4画面(入口・案件・スタジオ・編集)。ホロカラーは対象外。配置の構成から作り直す(素の JS・ui-kit は維持)。PC の全画面が主
  - 入口と案件を1つの「ホーム」に(上に「次にやること」、下に全案件の一覧)。動画の一覧は案件に一本化(編集の履歴は左メニューから外し「最近開いた5件」だけ)
  - ツール間の移動はヘッダー左の「ホーム / スタジオ / 編集」。設定は各ツールの⚙の右の欄1つ(全体の設定はどこで変えても全部に効く)
  - 見た目: 明るいテーマが既定・落ち着いた仕事道具風(灰色の面、強調色は主なボタン・選択中だけ)・作業画面は詰める
  - キー: 再生系(Space・J/K/L・← →・, .・I/O)を全ツールで統一。校正の行の移動を S/W → ↓/↑ に(S はカットの分割だけの意味に)、Q/E/B/Tab/Ctrl+Enter をやめる。ボタンの横にキーを書き、下に使えるキーの帯
  - 校正: 映像の上に今の行を字幕で重ねる・操作の入口を役割ごとに1つ(話者・まとめて直す・書き出し・以前の版は「…」へ)。上級機能(精度・学習)は今の場所で既定で閉じる
  - カット: タイムラインを3段(区間の中に波形)・ミニマップ・ホイールで拡大・端の当たり判定を広く。パック: 前回の設定の要約+「作る」だけ、詳しい設定は右の欄
  - スタジオ: ③ の書き出しを右の欄へ・今をマーク①〜⑤を主役に(IN/OUT は下げる)・盛り上がりのグラフを大きく+山に順位と理由(画面の側で計算)・④ コラボは設定へ・書き出しのあと自動で文字起こし
- 未完了・次: 実装は PC の Claude Code(順番: 共通(ui-kit)→ 編集の校正 → カット・パック → スタジオ → ホーム)。ほぼ完成したら段階3(/frontend-design → /baseline-ui → /design-review)。
  `transcribe-tool/AGENTS.md`「画面の設計で決めたこと」(キー・左メニュー)と `docs/ui-guidelines.md`(ヘッダー・用語「入口」→「ホーム」)は実装と同時に改訂する(ブリーフの「guidelines の改訂」)
- 注意: ブリーフは GitHub の 45e5ef8 時点のコードを読んで書いた。PC にはその後のコミット(① 探す のまとめて実行など)がある。実装の前に差分を確認する
- 未コミット: `.design/ui-overhaul/DESIGN_BRIEF.md`・`docs/WORKLOG.md`

## 2026-09-27 Claude Code — 画面の全面見直しの実装(ブリーフの段1〜5)
- ユーザーの指示: `.design/ui-overhaul/DESIGN_BRIEF.md`(承認済み)を「実装の順番」どおりに。45e5ef8 以降の変更との合わせ方はユーザー承認(`.design/ui-overhaul/IMPLEMENTATION.md` の 0)。
  途中から「全部一括で続行・質問しない・自己判断で決めてよい」。実装で決めた細部はすべて `.design/ui-overhaul/IMPLEMENTATION.md`
- 変更(段1 共通): ui-kit v6(`ui-kit/ui-kit.{css,js}`・`styleguide.html`・`styleguide.js`・`README.md`・新しい確かめ `ui-kit/e2e_styleguide.py` 41 件)。
  既定を明るいテーマに・トークン(`--stage-bg`・`--playhead` など)・飾り(影・グラデーション・無限の点滅)をやめる・
  `UIKit.appnav`(ホーム/スタジオ/編集)・`drawer`(modal / docked・`focus:false`)・`dialog.confirm/alert`・`.ui-pop`・`toast`(`#toast` の入れ物に重ねる)・`keybar`・`.ui-kbd`・`.ui-miniprogress`・
  `settings`(⚙ の欄。全体 = テーマ・文字の大きさ・キーの帯。`ytt:theme`・`ytt:fs`・`ytt:keybar`)・`keys`(共通の再生キー `playback`・`isTyping`・`helpHtml`)・`icon`(SVG の線のアイコン)
- 変更(4画面のヘッダー): 左に appnav + 版(`#ver`)、右に キー操作・⚙・テーマ。ブランド・「他のツール」・「入口」リンクはなくした
- 変更(段2・3 編集 0.18.0): 校正 = 映像の上に今の行の字幕・「…」に話者/まとめて直す/書き出し/以前の版・行の右クリックのメニュー・
  キー ↓/↑・Shift+↓/↑・共通の再生キー(Q/E/B/Tab/Ctrl+Enter をやめた。B は ⚙ の欄)・キーの帯・「表示」のポップオーバーを ⚙ の欄へ。
  カット = 3段のタイムライン・ミニマップ・ホイールで拡大(Shift で横)・端の当たり判定を外側 6px・端を選んでいるときの , . は1コマ(Shift で10)・置き換えの確認は UIKit.dialog。
  パック = 前回の設定の要約(配信者の色の丸)+「作る」+ 字幕の見本、詳しい設定は「設定を変える」の右の欄(zip もその中)
- 変更(段4 スタジオ 0.9.0): 書き出しは右の欄(1280px 以上は docked で並べる・狭いときは modal で重ねる)・今をマーク①〜⑤を主役に(IN/OUT/追加は「細かく決める」)・
  盛り上がりのグラフを高く + 上位5つの山に「順位 理由」(画面の側で S.series から)・④ コラボは ⚙ の欄へ・書き出しのあと自動で文字起こし(`api/autorun/start` mode:'transcribe' + marks。⚙ でオフ。`ytt:studio.autoTx`)・
  共通の再生キー(← → は ±1秒/Shift ±5秒・K は止める。共通のキーは割り当てを変えられない)・マークの行の「この後を」は「…」へ
- 変更(段5 ホーム = 入口 0.11.0): `app/portal.*` に「次にやること」(校正待ち・パック待ち・進行中。今の API から画面で組み立てる)・案件の一覧(`cases.html`・`cases.js` を取り込んで削除。`/cases.html` は `/#cases` へ 302)・
  「単体の文字起こし」(選んでまとめて実行 = `start-docs`)・起動の管理は「詳しく」に畳む。画面・README の「入口」→「ホーム」
- 文書: `docs/ui-guidelines.md`(用語「ホーム」・ヘッダー・新しい節「設定と右の欄」「キー」)、`transcribe-tool/AGENTS.md`(画面の設計で決めたこと)、各 README
- 見直し(Opus)の指摘を直した: スタジオ(書き出しの欄の開閉が採用のたびに動く・自動の文字起こしのあとで再読み込み・キーの割り当て・コラボの未表示のときの null)、
  ホーム(戻ったときに入力が消える・次にやることの重複)、編集(カットで K が再生になる・右クリックのメニューが切れる・⚙ の欄の裏でキーが効く・Shift+, . が効かない・字幕が再生位置とずれる ほか)
- テスト(PC): ui-kit e2e 41・スタジオ 単体 227 / node 18 / e2e_ui 126 / --mounted 139・編集 単体 125 / node 9 / e2e v07・v08・v09・eval_v093・v098・handoff・edit_tabs・edit_cut・edit_pack・ui_mounted すべて通過・
  入口 単体(test_launch・mount・cases・autorun・window)/ e2e_portal / e2e_window 通過・`tools/test_ui_kit_sync.py`・`tools/test_resolve_pack_contract.py` 通過
- 注意:
  - `transcribe-tool/test_document_save.cjs` は E3 以降ずっと落ちていた(`CUT` などの未定義。今回の変更の前から)→ テストの用意を足して 9 件通過
  - node は PATH に無い。`C:\Users\you11\miniconda3\Lib\site-packages\playwright\driver\node.exe --test …` で流す
  - `app/test_mount.py` は `PYTHONIOENCODING=utf-8` を付けて流すと子プロセスの出力の読み取りで落ちる(付けずに流す)
  - この日のセッションは 15〜30 分ごとに切れて、裏で動かしたエージェントが止まった。区切りごとにコミットした
- 未完了・次: 編集の左メニューはまだ履歴の一覧(検索・並べ替え・選んでまとめて実行)を持っている(ブリーフは「新規・最近開いた5件・ホームへのリンク」だけ)。
  ユーザーの実機の確認(4画面・明るい/暗い・1440/1280/1024 の幅)。ブリーフの段3(/frontend-design → /baseline-ui → /design-review)

## 2026-09-27 Claude Code — 画面の全面見直しの続き(編集の左メニュー・通しの確認)
- 変更: 編集の左メニューを1列に(新規 → 処理状況 → 開く = 何も打っていないときは最近の5件・打つと題名で最大 20 件・「すべての文字起こし → ホーム」→ 精度・学習は下に閉じて)。
  横のタブ・まとまり・並べ替え・「選んで、まとめて実行」をなくした(ホームの「単体の文字起こし」と案件の一覧へ)。題名の行の「まとめて実行」は残す。`setSideTab()` は該当する欄を開くだけ
- 決定・理由: ブリーフは「新規・最近開いた5件・ホームへのリンク」だけだが、編集を単体で開いたとき(ホームが無い)に古い文書を開けなくなるので、題名の検索を1つ残した(`.design/ui-overhaul/IMPLEMENTATION.md` の 6)
- 版: 編集 0.18.0 → 0.18.1
- テスト(PC): 編集の e2e 10 本・単体 125・node 9、入口の単体・e2e_portal・e2e_autorun・e2e_window、`tools/e2e_pipeline.py`、`tools/test_ui_kit_sync.py`・`test_push_helper.py`・`test_resolve_pack_contract.py`、ytt_core すべて通過
  (入口の単体は1回だけ1件落ちて、流し直して通過。前からある接続の揺れ)
- 未完了・次: ユーザーの実機の確認(4画面・明るい/暗い・幅 1440/1280/1024)。そのあとブリーフの段3(/frontend-design → /baseline-ui → /design-review)

## 2026-09-27 Claude Code — 狭かった所の直し(ユーザーの指摘「UIが狭い部分がある」「コラボ欄せまい」)
- 変更: スタジオ(`review.js`・`review.css`・`app.css`)、編集(`app.js`・`index.html`)、e2e の画面の幅。内容は `.design/ui-overhaul/IMPLEMENTATION.md` の 7
  - スタジオの書き出しの欄を並べるのは 1680px 以上だけ(1440px ではマークの一覧が細くなった)。コラボの節を開いたら ⚙ の欄を最大 1040px に(名前が縦に割れていた)
  - 編集: 本文の幅が 1300px 未満なら文書を開いたときに左メニューを自動で閉じる・映像の欄を最大 640px(閉じれば 760px)・パックの字幕の見本を右の列へ
- 確かめ方: `python tools/demo_env.py --port 8750` の見本のデータで 1920・1440 の写真を撮って見比べた
- テスト(PC): スタジオ e2e_ui 128・--mounted 141、編集の e2e 10 本すべて通過(1500px で「メニューが開いたまま」を前提にしていたテストは 1920px に)
- 版: まだ配っていない版に含めた(スタジオ 0.9.0・編集 0.18.1)

## 2026-09-27 Claude Code — ホロカラー 1.2.0: タスクバーにピン止めして起動中の印が付くように(閉じる = 最小化)
- ユーザーの運用(指示): 「タスクバーにピン止めする運用にした。起動中のマークつけて」
- 変更: `holo-colors/src/MainForm.cs`(ツールウィンドウ → タスクバーに出るふつうの窓)、`Program.cs`(閉じる = 最小化・`Shown`・`NearCursor`/`RestoreAt`(SetWindowPlacement で位置を決めてから戻す)・
  `--hidden` は最小化で起動・戻る先は `ForegroundTracker`・初回の案内とバルーンの文言)、`Win32.cs`(`ForegroundTracker`(SetWinEventHook)・WINDOWPLACEMENT など)、
  `e2e_holo_colors.py`(開いている = 最小化されていない・タスクバーのボタンの確認2件)、README(ピン留めの手順・版)、`docs/holo-colors.md`(決めたこと)
- 決定・理由: 起動中の印はタスクバーのボタンがある間だけ付くので、隠さずに最小化する。タスクバーから開いたとき戻る先がタスクバーにならないよう、前面の窓の変化を追う。
  通知領域のアイコンは終了・設定の入口として残した
- 版: ホロカラー 1.1.0 → **1.2.0**
- テスト(PC で通過): build.bat の単体 17 件・e2e 22 件(ユーザーの許可を得て流した)
- 注意: Git Bash から `cmd //c build.bat | grep` で流すと zip の段で止まる(PowerShell から流せば最後まで進む。build.bat の不具合ではない)。
  このセッションの最初に「# を付けない」を既定にする変更をしかけたが、ユーザーの判断(設定で外せるのでこのままでよい)で取り消した

## 2026-09-27 Claude Code — 画面の全面見直しの段階3(/frontend-design → /baseline-ui → /design-review)
- /frontend-design: 一覧を「1枚の紙」に(ホームの次にやること・案件、編集の行。ui-kit に `.ui-sheet`)・等幅は時刻と数字だけ・一覧の上のキーの手がかりは既定で出さない(`.design/ui-overhaul/IMPLEMENTATION.md` の 8)
- /baseline-ui: 100dvh・飾りのグラデーションと字間の変更をやめる・見出し/本文の折り返し・長い動きと幅のアニメーションをやめる・safe-area・重なりの順の決まり(同 9。技術の指定 Tailwind などは前提と合わないので当てはめない)
- /design-review: 結果は `.design/ui-overhaul/DESIGN_REVIEW.md`。写真は `.design/ui-overhaul/screenshots/`(git に入れない。`.gitignore` に足した)。
  直した: 映像の上の字幕が映像の外に出ていた(映像と字幕だけの箱 `.tt-vbox`)・「…」と映像の下の4枚のカードで入口が2つ(カードは「…」から開いたときだけ出す)・
  キー操作の一覧の並び(全部「キー → 説明」)・⚙ の欄の形・ホームの ⚙ を文字つきに・「メニューを閉じました」は1回だけ。映像の背景は `--stage-bg`
- テスト(PC): ui-kit e2e・スタジオ e2e_ui 128・編集の e2e(v07・v08・v09・v098・eval・handoff・edit_tabs/cut/pack)・入口 e2e_portal 通過
- 未完了・次: 盛り上がりのグラフと山の札は見本では出ない(解析の直後だけ)ので実機で確かめる。DESIGN_REVIEW.md の「Should Fix(残り)」「Could Improve」

## 2026-09-27 Claude Code — ホロカラー 1.2.1: 右上の × でアプリを終了する
- ユーザーの指摘: 「アプリの×押しても終了しない」(1.2.0 では × も最小化にしていた)
- 変更: `holo-colors/src/MainForm.cs`(× ・ Alt+F4 ・タスクバーの「ウィンドウを閉じる」= 終了。閉じている最中に Quit を呼ぶと入れ子になるので、Cancel して BeginInvoke で終わる。
  Esc とコピー後に閉じるのは最小化のまま。初回の案内の文言)、`Program.cs`(コメント)、`e2e_holo_colors.py`(最後に × と同じ SC_CLOSE を送って終わることを確かめる)、README・`docs/holo-colors.md`
- 決定・理由: タスクバーにピン止めする運用なので、× は終了がふつう。× で終わると次に起動するまで Ctrl+Alt+H は効かない(README に書いた)
- 版: ホロカラー 1.2.0 → **1.2.1**
- テスト(PC で通過): build.bat の単体 17 件。× と同じ知らせ(WM_SYSCOMMAND SC_CLOSE)を送り、最小化の状態・開いた状態のどちらでも正常に終わることを確かめた(入力は送らない確認)。
  e2e 全体は流していない(Esc・コピー後の最小化には触れていない。次に流すときは最後の × の確認が増えて 23 件)

## 2026-09-27 Claude Code — 編集 0.18.2: 使いにくくなった所を戻す(履歴の一覧・左手のキー・Space)
- ユーザーの指摘: 「文字起こしが使いにくくなった」「履歴が消えた」「キー変更が消えた」「スペースで再生がうまく機能していない(連続で押した判定になって気持ち悪い)」「左手での操作が使いやすかった」
- 変更:
  - 左メニューの履歴: 0eb65dc(左メニューを1列に・最近5件だけ)を `git revert` で戻した(app.js・index.html は自動で合わさった)。新規/履歴/精度/学習 のタブ・配信ごと/配信者のまとまり・並べ替え・選んでまとめて実行が戻る。
    その後の直し(1300px 未満でメニューを自動で閉じる・トーストは1回だけ など)は残っている
  - キー(`transcribe-tool/app.js`): W/S 行・A/D 未校正・Q/E 3秒・B 自動で再生・Tab 入力欄に入る/抜ける・入力中の Ctrl+Enter 聞き直す を戻した。↓/↑・Shift+↓/↑ も残す。キーの一覧(index.html)・下の帯も
  - Space: 共通の再生キー(`UIKit.keys.playback`)と app.js の末尾の古い Space の処理の**両方**が動き、1回押すと「再生 → すぐ停止」になっていた → 古い方を削除。
    ui-kit(`ui-kit/ui-kit.js` → sync): 押しっぱなしの繰り返しで Space・K・L・I・O を繰り返さない・`play()` の失敗(直後に止めたとき)を無視する
- 決定・理由: 画面の全面見直し(ブリーフ)でやめたものだが、ユーザーが実際に使って不便だったので戻す(ブリーフ・IMPLEMENTATION.md の 6 に取り消しを書いた)。
  左手のキーと ↓/↑ は重ならない(S の分割は 2 カット のタブだけ)ので両方残した
- 版: 編集 0.18.1 → **0.18.2**(revert で 0.18.0 に戻った版の番号を上げ直した)
- テスト(PC): 編集 単体 125・node 9・e2e v07・v08(左手のキー・Space 1回・押しっぱなしの確認を足した)・v09・v098・handoff・eval_v093・edit_tabs・edit_cut・edit_pack・ui_mounted すべて通過、
  スタジオ e2e_ui 128、ui-kit e2e_styleguide、`tools/test_ui_kit_sync.py` 通過。
  テストの直し: v098 の「☰ のトースト」の確認は段3-3(トーストは1回だけ)と合っていなかったので外した・edit_cut の帯の確認を「S / ↓」に・edit_pack の最後の不要な検索欄の操作を外した
- 未完了・次: ホームの「単体の文字起こし」の一覧と編集の履歴で入口が2つになっている(同じ操作)。ユーザーの実機の確認のあとで、どちらを主にするか決める
- 注意: 起動中の入口は古いコードのまま。「すべて終了」→ start-all.bat で起動し直す

## 2026-09-27 Claude Code — 画面の直しの候補を文書に(未実装)
- ユーザーの指示: 「…」の選択肢が画面の外に出る・話者名から字幕の色・話者の記憶(「まだ実装しなくていい」)と、UI レビューの結果 11 件(「これも追加」)を残す
- 変更: `docs/backlog-ui-2026-09-27.md` を新しく作った(文書だけ。コードは変えていない)。A = 要望 3 件(原因と案)、B = UI レビュー 11 件(優先度 高 3・中 7・見た目 1)
- 決定: 取りかかるのはユーザーの指示があってから。どの項目でも、編集の履歴の一覧と左手のキーは残す(ユーザー決定)

## 2026-09-27 Claude Code — 編集 0.19.0: キー配置を変えられるように
- ユーザーの指示: 「編集画面でキー設定変えたい」。質問で決定: 設定で自由に割り当て(スタジオの「キー配置」と同じ形)・共通の再生キーも変更可
- 変更:
  - `ui-kit/ui-kit.js`(→ sync): `UIKit.keys.playback` が `keymap` を受け取る(渡さなければ今までの既定 = スタジオは変わらない)。`comboOf`・`keyText`・`PLAYBACK_ACTIONS`・`playbackMap`・`helpHtml(keymap)` を足した。README も
  - `transcribe-tool/app.js`: 校正のキーを表(`TX_ACTIONS`・`KEY_FN`)にして、割り当ては `S.settings.keymap`(サーバーの config.json。どのブラウザ・窓でも同じ)。
    ⚙ 設定の「キー配置」(`#kmGrid`・「標準に戻す」)。使えないキー(↓↑・Shift+↓↑・数字・Tab・Esc・Enter・?、再生のキーにはカットの S・X・Delete など)は理由を出して断る。重なりは前の操作から外して知らせる。
    下の帯・一覧の上の手がかり・キー操作の一覧(?)は今の割り当てで描く(`renderKeyUI`)
  - `transcribe-tool/cut.js`: カットのタブの共通キーにも同じ割り当てを渡す。`index.html`(一覧・手がかり・設定の欄・CSS)
- 決定・理由: 保存はブラウザ(localStorage)ではなくサーバーの設定(Edge の窓とブラウザで同じ配置を使えるように)。スタジオの共通キーは変えない(スタジオには別の「キー配置」がある)
- 版: 編集 0.18.2 → **0.19.0**
- テスト(PC): e2e_ui_v08 に「キー配置」の確認(変える・効く・断る・重なりを外す・サーバーに保存・再生のキーも・標準に戻す)を足して通過。
  編集 単体 125・node 9・e2e v07・v09・v098・handoff・eval_v093・edit_tabs・edit_cut・edit_pack・ui_mounted、スタジオ e2e_ui 128・--mounted 141・node 18、ui-kit e2e_styleguide・`tools/test_ui_kit_sync.py` 通過
  (編集の単体は1回だけ1件落ちて、流し直して通過)。見本のデータで ⚙ の欄とキー操作の一覧の写真を撮って確かめた
- 注意: 起動中の入口は古いコードのまま。「すべて終了」→ start-all.bat で起動し直す

## 2026-09-27 Claude Code — バックログの実装(`docs/backlog-ui-2026-09-27.md`。進行中の記録)
- ユーザーの指示: 「新着配信の監視はやらない・窓の形は専用の窓・以外は実装」。質問で決定: 専用の窓 = Edge のアプリの窓を既定に(pywebview は使わない)・精度改善は保留のまま・声の分離は入れない
- B-1・B-4・B-5(ホーム `app/portal.js`・編集 `transcribe-tool/app.js`): 「編集で開く」・次にやることのリンクを文書 ID(`?doc=<id>&media=<パス>`)に。編集は `?doc=` を先に見て、
  一覧に無ければ動画のパスで探す(予備)。次にやることから「投稿済み」「見送り」の案件を外す。次にやることに配信者・配信日を添える。
  テスト: `app/e2e_portal.py`(doc= のリンク・投稿済みは出ない・戻すと出る・配信者)、`transcribe-tool/e2e_edit_tabs.py`(同じ動画の2つの文書で古い方が開く・見つからないときの予備) 通過
- B-2(スタジオ `clip-studio/review.js`): 書き出しの欄を重ねて開いている間(1680px 未満)と、欄の中にフォーカスがある間は、裏の配信のキーを止める(横に並べているときは欄の外では効く)。テスト: `e2e_ui.py` 129 件通過
- B-3(編集 `app.js`): 右クリックのメニューを開いている間は、キーをメニューだけが受け取る(↑↓・Home・End で移動・Enter/Space で選ぶ・Esc/Tab で閉じる・ほかのキーは裏の行に渡さない)。テスト: `e2e_edit_tabs.py` 通過
- A-1(ui-kit `ui-kit.js` → sync): `details.ui-pop`・`ui-menu` を開いたら置き場所を測り、画面の外にはみ出す側だけ反対にそろえる(下にはみ出せば上に開く)。どの画面の「…」にも効く。テスト: `e2e_edit_tabs.py`(1440・1280・1024px)・ui-kit e2e 通過
- B-8(編集 `index.html`): 行の操作ボタン(校正済み・残す/カット済・微調整・音の状態のメモ)の文字を `--ink-2`・枠を `--line-strong`・高さ 28px に(コントラスト 4.5:1 以上・28px)
- B-9(編集): 映像の下の「設定」(再生に追従・太枠・時刻の微調整の幅)を右上の ⚙ 設定の「再生・行の操作」へ移し、設定の入口を1か所に。案内の文言も合わせた。テスト: e2e v07・v08・v09・v098 通過

## 2026-09-27 Claude Code — 文字起こしの大幅改善の計画(計画のみ・コードは変えていない)
- ユーザーの指示: 「文字起こし機能の大幅改善の計画」。質問で決定: 目的は**聞き違い**と**抜け・重なり声**(速さ・校正の手間は主目的ではない)・新しいモデル・実行ファイルの取得は可・クラウドは初期比較だけ
- 変更: `docs/transcription-overhaul-plan.md` を新しく作った(v2 設計書と accuracy-plan を今のコードと決定に合わせて1本に。段0 測る土台 → 段1 呼び名と配信ごとの文脈 → 段2 エンジンの境界 + GPU(whisper.cpp / llama.cpp の Vulkan)・Qwen3-ASR などの比較 → 段3 抜け → 段4 2つのエンジンの食い違い → 段5 重なり声(別視点))。
  `transcribe-tool/AGENTS.md` からリンク
- 調べて分かったこと(PC): 用語集・置換辞書は空・名簿に呼び名なし・`original` に信頼度なし・認識は large-v3 の CPU(1分半に 30〜50 秒)・モデルを読むたびに HF へ版の確認の通信
- 未完了・次: ユーザーの承認と、評価用の校正(15〜30 分・4 人以上。計画の 8 の 1)。承認があれば段0 から
- B-7(編集 `index.html`・`app.js`): 文書を開いている間、720〜1600px では左のメニュー(履歴など)を本文の上に重ねて開く(列を取らない。字幕の行が2段に割れない)。履歴から選ぶと閉じる。履歴そのものは変えていない
- A-1 の直し: 置き場所の直しを toggle イベント(後から届く)ではなく MutationObserver(描く前)で行う(1コマだけ画面の外に見えることがあった)
- テスト: 編集の e2e 全部(v07・v08・v09・v098・handoff・eval・edit_tabs/cut/pack・mounted)・スタジオ e2e_ui・ui-kit e2e 通過(v08 は重ねたメニューを閉じてから本文を操作するよう直した)
- B-6(スタジオ `core.js`・編集 `app.js`): 編集のヘッダーの「スタジオ」は `?video=<元の配信の id>&url=<URL>` を渡す。スタジオは ?video= の配信が保存済みなら ③ の確認画面でその配信を開き(?url= は使わない)、無ければこれまでどおり ?url= を解析の欄へ。テスト: スタジオ e2e_ui 133・--mounted 146、編集 handoff 通過
- B-10(編集 2 カット `cut.js`): キーボードだけで区間・端を選ぶ `[` `]`(前/次の区間。選んでいなければ再生位置から)・`Q` `W`(選んだ区間 = 無ければ再生位置の区間の始まり/終わりの端)→ 今までどおり `,` `.` で動かす。下の帯・キー操作の一覧も。
  再生のキーの割り当てで使えないキー(`CUT_KEYS`)に `[` `]` `q` `w` を足した。テスト: `e2e_edit_cut.py` 通過
- B-11(スタジオ `review.js`・`review.css`): マークの一覧の微調整のボタン(±5/±1/±0.5・現在位置)は選んだマークにだけ出す。別のマークの欄に入ったら(Tab でも)そのマークを選ぶ。テスト: e2e_ui 135・--mounted・node 通過
- 専用の窓(入口 `app/appwindow.py`・`portal.*`・README): 設定が無ければ Edge のアプリの窓で開く(`DEFAULT_MODE = "app"`)。オフにすると browser が残る・Edge が無ければブラウザ。「(試用)」を外した。入口 0.11.0 → **0.12.0**。
  `docs/integration-plan.md` に決定を書いた。テスト: `app/test_window.py`・`e2e_window.py`・入口の単体 91 件 通過
- A-2 話者の名前から字幕の色(cut2resolve `cut2resolve_core.py`・`pack.py`・`resolve_textplus.py`・`serve.py`、`ytt_core/colors.py`、編集 `pack-tab.js`・`index.html`・`resolve_export.py`・`serve.py`):
  文字起こしの話者の名前を読み(`read_transcript` の speaker)、計画に話者の区間(`Plan.speaker_spans`)。字幕の真ん中を元の動画の時刻に戻して話者を決め(`pack.cue_speakers`)、
  メンバーと1人に合う話者の字幕だけ Lua の計画に `cap.fill`(Resolve の中で Text+ の塗りの色を入れる)。合わない話者は配信者の色(空なら黒)のまま。
  名前→色の規則は `ytt_core/colors.speaker_colors` の1か所(cut2resolve の API と文字起こしの zip が共通で使う)。API は output.speakerColors(既定オン)。
  余白つき素材に置き換える前の計画(元の動画の時刻 = 文字起こしの時刻)で決める。パックのタブに「話者の名前がメンバーと合えば…」のスイッチと、話者 → 色の一覧。
  テスト: cut2resolve 287・契約テスト・編集 単体 125・e2e_edit_pack(話者「みこ」の字幕だけ色)・ui_mounted 通過。**Resolve の実機で色が入るかは未確認**(Lua の SetInput。見た目の入力の読み替えと同じ名前を使う)
- A-3 話者の声を覚える(編集 `serve.py`・`tx_worker.py`・`app.js`・`index.html`、`.gitignore`): 名前を付けた話者の声の特徴(sherpa-onnx。ワーカーの中だけ)を作業データの `voices/<判別モデル>.json` に覚え、
  話者判別のあとで見つかった話者と比べて、仮の名前(話者n)のままの話者に名前を付ける(類似度 0.60 以上・2番目との差 0.08 以上・1つの名前は1人)。
  「…」→「話者」に「声を覚える」(スイッチ・ボタン・覚えている声の一覧と「忘れる」)。詳しくは `transcribe-tool/AGENTS.md` の「話者の声」。
  テスト: `test_voices.py`(7件。test_metrics から読む)・`test_worker.py`(ワーカー経由で覚える → 名前が付く)・新しい `e2e_edit_voices.py` 通過
- 版: 編集 0.19.0 → **0.20.0**・スタジオ 0.9.0 → **0.10.0**・cut2resolve 0.13.0 → **0.14.0**・入口 0.11.0 → **0.12.0**(README の見出しと変更の記録も)
- テスト(PC・最後にまとめて): 編集 単体 125+・node 9・e2e(v07・v08・v09・v098・handoff・eval・edit_tabs/cut/pack/voices・mounted)、スタジオ e2e_ui 135・--mounted 148・node 18、
  cut2resolve 287、契約テスト、入口 単体 91・e2e_portal・e2e_window、ytt_core、ui-kit e2e・sync 通過
- 未完了・実機で確かめること: A-2 の色が Resolve の Text+ に入るか(Lua の SetInput。クラウドでは確かめられない)・A-3 の声の照らし合わせの精度(しきい値は実際の配信で調整)・専用の窓で起動するか。
  統合計画の正本(claude.ai の Claude Docs「動画編集ツール 統合計画」)にも「窓 = Edge の窓を既定・pywebview は使わない・新着配信の監視はやらない」と 09-27 の進み具合を書いた(ユーザーの指示「更新」)
- 注意: 起動中の入口は古いコードのまま。「すべて終了」→ start-all.bat で起動し直す(次から Edge の専用の窓で開く)

## 2026-09-28 Claude Code — 文字起こしの改善の計画 段0(AI 側): 自信の度合いを残す・モデルを手元から読む・精度を測る道具
- ユーザーの指示: 計画の段0 のうち AI 側を作る(ユーザーは並行して評価用を校正する)。評価用で見つけた間違いは辞書に足さない・校正は耳で確かめる、と説明済み
- 変更:
  - `transcribe-tool/serve.py`: 機械の出力 `original` の各行に avg_logprob・no_speech_prob・compression_ratio(`machine_conf`・`CONF_KEYS`。文字起こしのジョブ・範囲の再認識・疑わしい所の認識し直し)。
    文書に `recognition.runs`(エンジン・版・モデル・機器・設定・音声の秒・かかった秒。`recognition_run`・`pkg_version` は dist-info を読むだけ)。
    モデルは手元のファイルだけで先に読む(`_new_whisper`。`local_files_only=True` → 無ければネットワーク。読むたびの HF への確認の通信をやめた)
  - `transcribe-tool/tx_worker.py`: 偽のモデルが local_files_only を受け取る
  - `tools/eval_asr.py`(新): `stored`(保存してある出力)/ `run`(認識し直す)/ `compare`(同じ文書どうしの差と 95% の範囲)/ `list`。作業データは読むだけ、結果は作業データの `evals/asr/`(文章を含むのでリポジトリに入れない)。
    採点は画面の「認識精度の測定」と同じ(`stored` のたびに `doc_metrics` と照らし合わせる)。条件(重なり・BGM)・要確認の印・自信の度合い・まとまりの種類(両方/人が消した/人が足した)・文書ごと・名簿の名前の再現率
  - テスト: `test_metrics`(手元から読む・machine_conf)・`test_worker`(original の自信の度合い・recognition)・`tools/test_eval_asr.py`(新・3件)。AGENTS.md(直下の表・transcribe-tool の「精度の測定の土台」)・README
- 版: 編集 0.20.0 → **0.20.1**(画面は変わらない)
- テスト(PC): 編集 単体 135・node 9・e2e_ui_mounted・e2e_edit_tabs・tools/test_eval_asr 通過
- 本物で流した結果(評価用 9 本・校正の途中のデータなので数字は動く): `run`(large-v3・CPU・今の設定)で音声 408 秒を 149 秒(実時間の 0.37 倍)・モデルの読み込み 7 秒・メモリ最大 3.3GB。
  CER 21.6%(8 本)/ 保存してある出力 16.8%(9 本)。誤りの多くは**抜け**(人が足した行 = 機械が何も出さなかった所を含む)。要確認の印ありの方が誤りが少なく(6.8% / 15.4%)、自信の度合いはどの行も「高」で見分けに使えていない(量が少なく結論は出せない)
- 未完了・次: ユーザーの評価用の校正(15〜30 分・4 人以上)。そろったら `python tools/eval_asr.py stored` と `run` で基準を取り直す → 段1(呼び名)。
  段0-3(書き方の決まり)はおすすめ(つなぎ言葉は残す・算用数字・笑いは書かない・伸ばしは「ー」)を伝えた段階で、ユーザーの確定はまだ
- 注意: 起動中の入口は古いコードのまま。「すべて終了」→ start-all.bat で起動し直すと、次の文字起こしから自信の度合いが残る

## 2026-09-28 Claude Code — 教師データ＿夏色まつり の文字起こしと動画の参照を直した(作業データだけ・コードは変えていない)
- ユーザーの指摘: 「教師データ＿夏色まつり の文字起こしと動画ファイルとの参照が切れた」
- 原因: 動画のファイル名が 2026-09-22 16:37 ごろに `01_00h06m03s-00h06m43s.mp4` → `教師データ＿夏色まつり01.mp4` などに変わっていた(フォルダは同じ E:\Video\切り抜き動画素材\教師データ用\教師用データ＿夏色まつり)。
  段0 の変更とは関係ない(その前から切れていた。eval_asr の run も保管の音声で測っていた)
- 直したこと: 作業データの文書5件(43e30ca2b432=01・df09bdcae630=02・050710117283=03・cc97b6acc84c=04・f695ec73f8b7=05。長さが区間と一致することを確かめた)の sourcePath・sourceName を新しい名前に。
  updatedAt は変えていない(開いたまま保存しても 409 にならない)。直す前は transcripts/.bak/<id>.pre-relink.json。起動中のツールで mediaOk = True を確かめた
- 直していないもの: 保管データ(dataset/docs/<id>/doc.json・manifest.json。写し)とスタジオの data.json の書き出しの記録(起動中のスタジオが上書きするため触らない)。
  26-06-11_夏色まつり(042eed22f3d8)の動画 Dropbox\切り抜き動画\完成品デモ\26-06-11_夏色まつり.mov はフォルダごと見つからない(別件・未対応)
- 次の候補(未実装・ユーザー判断): 動画が見つからない文書で「動画を選び直す」(ツールに付け替えの機能が無い)

## 2026-09-28 GPT(Codex) — UI追加監査（調査のみ・実装なし）
- ユーザーの指示: さらに修正点を徹底的に洗い出す。実装せず、コピペできる形で渡す。
- 変更: `docs/ui-audit-2026-09-28.md` に追加20項目と根拠・再現条件・修正方針・未確認範囲を記録。`.design/ui-overhaul/DESIGN_REVIEW.md` は既存レビューを残して追記。本WORKLOGと合わせ文書3ファイルのみ。
- 確認: 基準 `4bd71f7`、編集0.20.1・スタジオ0.10.0・入口0.12.0・cut2resolve0.14.0。使い捨てのdemo_envでキー・設定・再読み込み・パック作成と画面撮影（画像はgit管理外）。本物の作業データは変更していない。
- 主な問題: パック設定の裏でAlt+タブ切替→操作ロック、評価用でも声の登録が有効、派生ショートカットの衝突、左メニューへのキー漏れ、文字起こし側でのカットUndo、出力設定とパック表示の不整合。
- 注意: 20件すべてが実再現済みのバグではない。コード上の条件付き問題、声の登録条件の設計判断、既知の再リンク不足、YouTubeの準備待ちを分けた。左履歴と左手キーを維持する。実装の承認は得ていない。
- 未完了・次: ユーザーの優先順位・実装指示待ち。実ASR・Resolve・実配信、通信障害注入、全画面×全幅×明暗の完全な組合せ確認は未実施。アプリのコード・版番号は変えていない。

## 2026-09-28 Cowork(Claude) — 「動画全体を再認識」の設計メモ(設計のみ・コードは変えていない)
- ユーザーの要望: 文字起こしの再認識で動画全体を認識し直したい。あわせて「複数人(声が重なる所)だと 0 文字になることがある」
- ユーザーが決めたこと: 動画全体を「範囲をまとめて」と同じやり方で(行を作り直し抜けも拾う・15分の上限なし)・**校正済みの行は残す**・実装は Claude Code に任せる
- 変更: `docs/whole-retranscribe-design.md` を新しく作った(画面の選択肢・`/api/retranscribe` の `mode: "whole"`・反映の決まり・0 文字の安全装置(元の行を残す)と空いた所だけ緩い条件で認識し直す・テスト)
- 気づいたこと: 今の「範囲をまとめて」は、範囲内で 0 文字になった所の元の行を消してしまう(同じ文書の 3-4 の 2 で直す)
- 未完了・次: Claude Code が設計メモに沿って実装。ユーザーに 0 文字になった文書と時刻を1〜2か所もらう
- 未コミット: docs/whole-retranscribe-design.md, docs/WORKLOG.md

## 2026-09-28 Cowork(Claude) — 「複数人だと 0 文字」の原因を調べた(調査と設計メモの追記のみ・コードも作業データも変えていない)
- ユーザーの指摘: 教師データ＿白上フブキ02(`8e89d529ae24`、40 秒)が全体で 0 文字
- 分かったこと: worker.log に `VAD filter removed 00:40.000 of audio`(19:14:02)。認識の記録の `wallSec` も 0.08 秒 = **声の検出(Silero VAD・設定は「標準」)が40秒すべてを捨て、モデルに何も渡っていなかった**。
  同じ時の 03(`855b1f53aa87`)も 22.4/30 秒が捨てられ「ご視聴ありがとうございました」だけ。PC の pyannote の区切りのモデル(話者判別用)で見ると 02 は約 85% に声があり、16〜21 秒・39 秒は2人の重なりが多い。音量は普通
- 変更: `docs/whole-retranscribe-design.md` の 4 を書き直した(原因は「捨てる判定」ではなく声の検出。捨てすぎたら「弱め」→「なし」で自動でやり直す・捨てた秒数を `recognition.runs` に残す・全体の再認識は既定「弱め」・Silero を pyannote の区切りのモデルに替える案は後で検討)
- 未完了・次: Claude Code が設計メモに沿って実装。「弱め」で通るかは PC で未確認(`tools/eval_asr.py run` で vadMode を変えて確かめるとよい)
- 未コミット: docs/whole-retranscribe-design.md, docs/WORKLOG.md

## 2026-09-28 Claude Code — 編集 0.21.0: 動画全体の再認識・声の検出が捨てすぎたときの自動のやり直し・0 文字の所は元の行を残す・映像の上の字幕に話者の色
- ユーザーの指示: Cowork の依頼書 `docs/whole-retranscribe-design.md`(同じコミットに入れた)のとおり実装。あわせて「話者名を入れたら字幕の文字も変わるようにプレビューでも」(質問で決定: 1 文字起こし の映像の上の字幕)
- 変更(`transcribe-tool/`):
  - 声の検出のやり直し(設計 4-2): `transcribe_vad_fallback`(標準→弱め→なし。残りが 20% 未満・文字が 0・**よくある誤認識の文だけ**のとき次へ)を新規の文字起こし・範囲・全体で共通に使う。
    ワーカーは認識を始めた直後に `info`(duration・duration_after_vad)を送り、`RemoteModel.transcribe` が行より先に読む(`_Segs.close()` で行を読まずにやめる)。
    記録: `recognition.runs` の `vadUsed`・`vadRemovedSec`・`vadRetries`、`params.vadUsed`。知らせ: `job.vadNote`(処理状況・完了の知らせ・認識の設定の欄)。
    新規の文字起こしは、やり直しに備えて行を最後まで読んでから流す(処理状況の行数は読みながら数える)
  - 全体の再認識(設計 3): `/api/retranscribe` の `mode: "whole"`(校正済みでない行を差し替え・上限 6 時間・声の検出は既定「弱め」・評価用は断る)。認識は `RangeRecognizer`、反映は `apply_range` → `plan_range`・`fit_lines`
    (校正済みの行は文字・時刻・話者・original・単語の時刻そのまま。かかる新しい行は捨てる/切り詰める)。画面は「対象」に「動画全体(校正済みの行は残す)」・ヒント(残す行・差し替える行・目安は large-v3 の CPU だけ)・1回目の押し直しの案内・完了の知らせ
  - 0 文字の所(設計 3-4 の 2・4-2 の 3): 範囲・全体で、新しい行の重なりが 30% 未満の元の行は残して印「再認識で文字が出なかった(元の行のまま)」。その所だけ声の検出なし・no_speech_threshold なしで認識し直し、出た行は印「声が重なる所などを緩い条件で認識」(よくある誤認識の文は捨てる)。**以前の「範囲をまとめて」が 0 文字の所の行を消していたのも直った**
  - `public_job` が `job["warnings"]` も画面に出す(疑わしい所の認識し直しの注意などが届いていなかった)
  - 映像の上の字幕(`#playerCaption`): 話者の名前がメンバーと合えばその色(`capSpeakerColor`。入口の `api/ytt/streamer-colors`・パックのタブの「話者の名前がメンバーと合えば…」を切っていれば出さない)
  - テスト: `test_worker`(声の検出のやり直し・全体で校正済みを残す・0 文字の所を残す/緩い条件で埋める・範囲も同じ・6 時間・評価用・明示の「なし」)、`test_metrics`(fit_lines・やり直しの順番・よくある誤認識の文だけ)、
    `e2e_edit_tabs`(動画全体: ヒント・2度押し・校正済みが残る・知らせ)、`e2e_edit_pack`(映像の上の字幕の色: みこ = さくらみこの色・話者なし = 配信者の色・スイッチを切れば出さない)
- 版: 編集 0.20.1 → **0.21.0**(README の変更の記録・AGENTS.md の「再認識(範囲・全体)と声の検出のやり直し」)
- テスト(PC): 編集 単体 143・node 9・e2e v07・v08・v09・v098・eval_v093・handoff・edit_tabs・edit_cut・edit_pack・edit_voices・ui_mounted すべて通過
- PC で確かめた結果(白上フブキ02・03。作業データは読むだけ。large-v3・CPU・音量補正あり。やり直しを止めて設定ごとに):
  | 文書 | 標準 | 弱め | なし |
  | 02(8e89d529ae24・40 秒) | 40.0 秒捨てて 0 文字 | 35.0 秒捨てて 23 文字 | 0 秒・52 文字 |
  | 03(855b1f53aa87・30 秒) | 22.4 秒捨てて「ご視聴ありがとうございました」だけ | 12.8 秒捨てて 56 文字 | 0 秒・131 文字(「ござう」の繰り返しを含む) |
  自動のやり直し(標準から): 02 → 「なし」まで緩めて文字が出る。03 は最初の決まり(残り 20% 未満・文字 0)では**やり直さなかった**(残り 25%・誤認識の文が出ていた)ので、「よくある誤認識の文だけ」も文字 0 とみなすように足した → 「弱め」でやり直す。
  **注意: 同じ音声でも回ごとに結果がかなり違った**(02 の「なし」52 字 / 176 字、03 の「弱め」56 字 / 17 字)。雑音の多い音声では Whisper が温度を上げたやり直しで乱数を使うため。精度の比較は複数回か、評価用の量で見る
- 提案だけ(未実装・ユーザーの確認待ち): 設計 4-3 = 声の検出を Silero から pyannote の区切りのモデル(話者判別用に PC にある。重なった声を見つけられる)に替える/両方の「どちらかが声」を使う。計画の段3・段5 とまとめて評価用で比べてから決める
- 未完了・次: UI レビュー(`docs/ui-audit-2026-09-28.md` の 20 項目。ユーザー: 「自明な部分以外は確認してから」)
- 注意: 起動中の入口は古いコードのまま。「すべて終了」→ start-all.bat で起動し直す

## 2026-09-29 Claude Code(クラウド)— HANDOVER の書き直し・統合計画の段階表の古い記述を直した(文書のみ・コードは変えていない)
- ユーザーの指示: 計画の全体像の確認のあと、「AI だけで片付く2つ(HANDOVER・段階表)をやる」
- 変更:
  - `docs/HANDOVER.md`: 09-27 のままだったのを今の状態に書き直した(版 入口 0.12.0・スタジオ 0.10.0・編集 0.21.0・cut2resolve 0.14.0・ui-kit v6、
    改善計画の段0・0.21.0、UI 追加監査 20 項目は未実装、実機で確かめること・保留・作業データの別件の一覧、再開用の指示文)。PC での作業の注意と要点はそのまま残した
  - `docs/integration-plan.md`: 段階表の 5・7 の行と「未決」を 09-27 の決定(Edge の窓を既定・pywebview は使わない・新着配信の監視はやらない)にそろえた(本文と表が食い違っていた)
- 未完了・次: ユーザーに次の作業(改善計画の段1 / UI 監査のどの項目から)を聞く。正本の Claude Docs はすでに 09-27 に更新済み(今回は触っていない)

## 2026-09-29 Claude Code(クラウド)— 全体のまとめ `docs/ROADMAP.md` と、計画・指示の文書の整理(文書のみ・コードは変えていない)
- ユーザーの指示: 「これ全体をまとめて、各指示書を整理して」。質問で決定: 対象は計画・設計・依頼の文書と AI 向けのルール文書の両方・まとめの置き場所は任せる → リポジトリに置いた(資料の正本はリポジトリ・Codex も読めるため)
- 変更:
  - `docs/ROADMAP.md`(新): 全体像(柱 A〜E と状態)・進行中と次(精度改善・UI 追加監査)・実機で確かめること・保留/未決・作業データの別件・**文書の索引**(規則 / 記録 / 進行中 / 完了した設計 / 古い資料)
  - 計画・設計の文書の先頭に「状態(2026-09-29)」の1行: `integration-plan`(完了)・`edit-tool-design`(実装済み・未決2件)・`whole-retranscribe-design`(0.21.0 で実装済み・4-3 は提案)・
    `followup-2026-09-27`・`backlog-ui-2026-09-27`(実装済み。題の「未実装」を外した)・`transcription-overhaul-plan`(進行中)・`ui-audit-2026-09-28`(未実装)・`transcribe-tool/TRANSCRIPTION_V2_DESIGN.md`(新しい計画にまとめ済み)
  - `AGENTS.md`: 最初にやることに ROADMAP を足した・統合計画の長い1段落を短く・資料の場所を ROADMAP の索引へ寄せた・「計画の文書の先頭に状態の1行」「状態が変わったら ROADMAP も直す」を足した。**担当表・規則の中身は変えていない**
  - `transcribe-tool/AGENTS.md`: 版の経緯(0.9〜0.20 の14行)を README と WORKLOG への案内に・「v2 設計書も必ず読む」「accuracy-plan は指示まで実装しない」の古い指示を今の計画への案内に・
    末尾の「後で実装したい」(スタジオへ返す・声の登録は実装済み、愛称は段1、ボーカル分離は入れない)と実機確認の記述を今の状態に
  - `docs/HANDOVER.md`: 残り・実機・保留・別件の一覧を ROADMAP に一本化(二重に持たない)・再開用の指示文で ROADMAP を読むように
- 未完了・次: 担当表の「画面の全面見直し(見直しが終わるまで他の AI は触らない)」は見直しが済んだので、GPT が画面を触ってよいかをユーザーに確認する(今回は変えていない)

## 2026-09-28 Claude(Cowork か PC の Claude Code。09-29 に後追いで記録)— スタジオ 0.11.0: 「一瞬を切り取る」
- 09-29 の検証で、push.bat のコミット 129b4e7(「update 2026/09/28 21:28」)に WORKLOG の記録が無い変更が入っていたのを見つけた。作ったのは Claude(ユーザー回答 09-29)
- 変更: `clip-studio/review.js`・`review.css`・`e2e_ui.py`・`README.txt`。③ 確認に「一瞬を切り取る」(キー C): 今の位置の前2秒・後3秒から始め、±0.1/0.5/1 秒と「今の位置」で端を合わせ、
  「▶ 範囲を再生」で確かめて、その数秒だけを mp4 に書き出す。マーク「一瞬」(採用)として一覧に残り、自動の文字起こし・「この後を ▸」・案件にもそのまま乗る
- 版: README に「v0.11.0 の変更」があったが、見出し・`core.js`・`serve.py` は 0.10.0 のままだった → 09-29 に3か所を **0.11.0** にそろえた(下の記録)

## 2026-09-29 Claude Code(クラウド)— 文書をコード・git と照らし合わせて検証・保留をユーザーと1件ずつ決めた・スタジオの版を 0.11.0 に
- ユーザーの指示: 「この段階で全体の情報を正確に整理したい」「保留を一つずつ整理するから質問して」
- 検証(4つに分けて、読むだけで調べた): 版・ファイルの参照・テスト(クラウドの Linux で単体テストを流した)、AGENTS.md と統合計画の技術的な記述、`transcribe-tool/AGENTS.md` の識別子と定数、ROADMAP の状態と UI 追加監査の 20 項目
  - 見つかった食い違い: 記録の無いスタジオの変更(上)・`transcribe-tool/AGENTS.md` の「評価用は学習に使わない」が「声を覚える」では守られていない(監査の 02 と同じ)・
    統合計画の古い記述(start.bat・既定はブラウザ・/cases.html・実機確認待ち)・ytt_core の `colors`・`tools` が AGENTS.md に無い・ホロカラーは「つながっていない」が色の一覧は colors.py が読む・
    まとめて実行の入口は5か所ではなく7か所・「校正のあとでパックを作り直す」はほぼ実装済み・UI 監査の 12 は一部対応済み(ほか 19 件は残る)
  - テスト(Linux・ffmpeg なし): ytt_core 56・ui-kit sync 4・push_helper 6・eval_asr 3・cut2resolve 287・スタジオ 175 通過。
    `app/test_window.py` の TestFocusWindow 3件と `transcribe-tool` の test_edit 2件は Windows 前提で Linux では落ちる(PC では通る見込み。ROADMAP の 5)
- 保留の決定(ユーザー 09-29。詳しくは `docs/ROADMAP.md` の 4): やる = 行の後の余白を設定に・字幕のトラックで時刻を直す・複数の切り抜きをつなげる(優先度 低)・動画を選び直す・
  文字起こしの一覧は編集の履歴を主に・まとめて実行の記録をファイルに・まとめて実行の入口の見せ方をそろえる・案件の行からスタジオを ?video= で・文字の欄で Shift+右クリック・ホロカラーの色を全員調べ直す(複数の色・自分で直せる形)。
  閉じた = パックの作り直し(済み)・最初の文字起こしが遅い(感じない)・③-2 の6か所(段3 で測る)。担当表 = 画面は今までどおり Claude だけ。保留のまま = タブが落ちる件と BIOS・ポート番号
- 変更: `docs/ROADMAP.md`(1〜5 を書き直し)・`AGENTS.md`(ytt_core の行・ui-kit のテスト・ホロカラーと colors.py・担当表・CSP の細部)・`transcribe-tool/AGENTS.md`(評価用と声を覚える・test_voices・パックの output・apply_edit_cuts)・
  `docs/integration-plan.md`(古い記述に「→ その後」を書き足した)・`docs/ui-audit-2026-09-28.md`・`docs/edit-tool-design.md`・`docs/holo-colors.md`(状態)・`docs/HANDOVER.md`(版)
- 版: スタジオ 0.10.0 → **0.11.0**(`serve.py`・`core.js`・`README.txt` の見出し。中身は 09-28 の「一瞬を切り取る」)
- 未完了・次: ROADMAP の B-1〜B-10 と UI 監査の取りかかる順をユーザーに聞く。精度改善はユーザーの評価用の校正待ち
- 注意: 起動中の入口は古いコードのまま(版の表示だけ変わる)。「すべて終了」→ start-all.bat で起動し直す

## 2026-09-29 Claude Code(クラウド)— 全体を1つの大きな計画と段ごとの細かい計画に整理・残りの保留を全部決めた(文書のみ・コードは変えていない)
- ユーザーの指示: 「全体に散らばった情報をまとめて保留を解決して、一つの大きな計画とその各段階の細かい計画に整理する」(実装はしない)
- 決めたこと(ユーザー 09-29。質問 8 件 + 計画を書いて出た 13 件。記録は `docs/ROADMAP.md` の 5 と各段の計画の「決まったこと」):
  声を覚える = 校正済み・印なしの行だけ・一般の名前は断る・既にある一般の名前は一覧で知らせる / パックの出力先は覚えない・粗編集と予備は覚える / zip に渡らない設定は画面に書く /
  元に戻すは操作した順 / 「できれば直す」はマークの一覧と幅の崩れ2件 / 古い資料の判断はまとめて閉じる / ポート 8700 で確定 / 動画を選び直す場所 = この PC のドライブならどこでも /
  ホームの単体にもまとめて実行を残す / 行の後の余白は無音が無いときだけ・後ろだけ / 残す行を広げたら区間も広げる / マークの行に配信者の欄は出さない /
  ホロカラーは名簿も直す・友人の exe にも「色を直す」 / 複数の切り抜きは全部 30fps 前提・素材ごと・8本・粗編集なし
- 変更:
  - `docs/ROADMAP.md`: 「全体の計画」に組み直した(1 全体像 / 2 大きな計画 = 線 A 段1〜8 と線 B 精度改善 / 3 実機で確かめること / 4 様子を見るもの / 5 決めたことの記録 / 6 作業データの別件 / 7 段の進め方 / 8 文書の索引)
  - `docs/plan/phase1-small-fixes.md`〜`phase8-multi-clip.md`(新・8本): 段ごとの細かい計画(目的・作業と順番・各作業の今の動き(file:line)・変えること・ファイル・テスト・リスク・終わりの条件・版・実機の確認・決まったこと)。
    今のコードを読んで書いた(行番号は 09-29 時点)。計画を書く中で見つかったこと: 設定の読み込みに失敗すると次の保存で用語集・キー配置が空で上書きされうる(監査 11 より重い)・
    編集の `PUT /api/settings` は丸ごと置き換え(窓2つで消える)・カットの読み込み失敗でたたき台からパックを作れてしまう(監査 13)・まとめて実行の `_edit_keeps` は複数の素材を知らない(段8 で同じ版で直す)
  - `docs/ui-audit-2026-09-28.md`(20 項目を段1〜5 に割り振った)・`AGENTS.md`(索引の場所・計画の場所)・`docs/HANDOVER.md`(次は段1・再開用の指示文)・`docs/edit-tool-design.md`・`docs/holo-colors.md`(計画へのリンク)
- 未完了・次: 線 A の段1 から(ユーザーの「始めて」の指示を待つ)。線 B はユーザーの評価用の校正待ち。タブが落ちる件は様子見
## 2026-09-28 Claude Code — スタジオ: 「一瞬を切り取る」(キー C)と「マークにする」(版は未変更 0.10.0)
- ユーザーの指示: 「スタジオでその一瞬だけ(自分で調整)切り取る機能」→ 質問で決定: 数秒の短い動画・マーク「一瞬」(採用)として残す・前 2 秒/後 3 秒・0.1 秒刻み。
  使ってみて「ライブ中で書き出せなかった(マークも作られない)」→「今はマークのみでいい・テストもしなくていいからすぐ」
- 変更(`clip-studio/review.js`・`review.css`・`e2e_ui.py`・README): ③ の開く欄「一瞬を切り取る」`#rvMoment`(キー C = 操作 `moment`)。始まり/終わりを ±0.1/0.5/1 秒・「今の位置」、動かした端へ移る、「▶ 範囲を再生」、
  **「マークにする」**(ライブ中・書き出しの実行中でもできる。ライブ中はライブの印つき)と「書き出す」(そのマークだけ `startExport`。ライブ中・実行中は押せず理由を出す)。サーバーは変えていない
- テスト: 最初の版(書き出すだけ)で e2e_ui 141・--mounted 154・node 18・単体を通した(途中はユーザーの push.bat のコミット 129b4e7)。
  **「マークにする」を足したあとのテストは、ユーザーの指示で流していない**(構文の検査だけ)。次に e2e_ui に「マークにする」の確認を足して流す
- 版: 動いているサーバーを起動し直さずにページの再読み込み(F5)で使えるよう、**番号は 0.10.0 のまま**(上げると画面と食い違って赤い帯)。次に起動し直すときに 0.11.0 に上げる(serve.py・core.js・README の見出し。README の変更の記録は「次の版の変更」として書いた)

## 2026-09-28 Claude Code — スタジオ: 「一瞬をマーク」をボタン1つに(前・後の秒数はあらかじめ決める)
- ユーザーの指示: 「ボタン一つでマークまで」「前後の秒数は 0.1 秒単位で、押してから調整ではなく、あらかじめ秒数を決めて」「すぐ実装」
- 変更(`clip-studio/review.js`・`review.css`・`e2e_ui.py`・README): 押してから調整する欄(`#rvMoment`・範囲を再生・マークにする・書き出す)をやめ、「今をマーク」の欄の2行目に
  「一瞬をマーク」ボタン(キー C = 操作 `moment`)と 前/後 の秒数の欄(0.1 秒単位・0〜60・既定 2.0/3.0。設定 `review.momentBefore`/`momentAfter` に保存)。押すとすぐマーク「一瞬」(採用。ライブ中はライブの印)
- テスト: e2e_ui の確認を書き直した(既定の秒数・秒数を変えて C → 3.8 秒のマーク・設定に保存)。**流すのはこのコミットのあと**(ユーザーが急いでいるため先にコミット)
- 版: 0.10.0 のまま(ページの再読み込みで使えるように。次に起動し直すときに 0.11.0)

## 2026-09-28 Claude Code — スタジオ: 「つなげて1本に」(チェックしたマークを時刻の順に1本の mp4 に)
- ユーザーの指示: 「細かいマークから書き出したものを合成して一つにしたい」。質問で決定: mp4 を1本・同じ配信の中だけ・チェックして選ぶ・つなぎ目はそのまま
- 変更(`clip-studio/`): `exporter.py`(`/api/export` に `combine: true`。2 件以上・時刻の順・合計 60 分まで。`_run_combine` = 各マークを 作業用/ に切り出し(音量も)→ `concat_pieces`(concat フィルタで再エンコード・setsar・音声の無い部品があれば映像だけ)→
  出力先の直下に `つなぎ_<最初>-<最後>_<n>本.mp4` → ラウドネスはつないだ1本で → 部品は消す。**.clip.json は書かない・マークの「書き出し済み」は付けない**(.clip.json の時刻 = 元の配信の時刻 の約束を崩さないため)。
  `job_public` に `combined`)、`review.js`(マークの行の左にチェック `.rv-join`・書き出しの欄に「チェックした n 件をつなげて1本に」`#rvJoinRun`・書き出しの一覧の先頭に「つないだ1本」の行(「編集で開く」)・自動の文字起こしはしない・配信を切り替えたらチェックを外す)、`review.css`、`e2e_ui.py`、README
- 直した不具合(見つけた): マークの行の入力欄に入ると行を選ぶ(B-11)ため、下の行のチェックを押すと上の行の微調整が畳まれて一覧がずれ、押したつもりが外れた → つなぐのチェックでは行を選ばない
- テスト(PC): e2e_ui 144(つないだ長さ = 選んだマークの合計・部品が消える・.clip.json なし・マークの状態は変わらない・チェックが外れる)。1回目に1件だけ落ちた確認は、流し直して再現しなかった
- 版: 0.10.0 のまま(ページの再読み込みで使える。**サーバー側(exporter.py)を変えたので、つなぐのは入口を起動し直してから**)。次に起動し直すときに 0.11.0

## 2026-09-29 Cowork(Claude) — 「気が利く画面へ」の設計(話者の色・カットしない・まとめて実行の統一・? でキー設定・使いごこちの見直し。設計のみ・コードは変えていない)
- ユーザーの要望: 話者判別した話者のメンバーカラーを字幕に(色が出ない所がある・文字起こしの画面でも)/ カットしないことも選びたい / 複数の画面から呼べる機能(まとめて実行など)の挙動をそろえ、細かく設定したい / キーの確認の場所(?)で設定したい / 「全体的に UI の気が利かない」「毎回同じ入力をさせられる」
- ui-dev-workflow を全部(ユーザーの選択)。段階1(grill-me・design-brief)と段階2(10 原則の要約を読んでブリーフに Heuristics applied)まで
- 変更(新規・文書だけ): `.design/ux-consistency/DESIGN_BRIEF.md`(**ユーザー承認 2026-09-29**)・`AUDIT.md`(サブエージェント 3 本の調査: まとめて実行など複数の入口の比較・編集の監査 27 件・ホームとスタジオの監査 30 件とキーの実装メモ。基準は GitHub の 129b4e7)・`REQUEST.md`(Claude Code 向けの依頼書: 設定の置き場・段1〜9・テスト・リスク)
- ユーザーが決めたこと:
  - 話者の色: 映像の上の字幕・パックの字幕の見本・カットのプレビューで色が出なかった。文字起こしの画面では話者の色(左端の線・話者の欄)をメンバーカラーに(文字の色は変えない)
  - カットしない: カットのタブとまとめて実行の両方。カット済の行の**字幕も全部出す**
  - まとめて実行: どの入口にも全部の設定(方法は Claude に任せる → 1 つの部品 `UIKit.autorun`・値は 1 か所)。どこで変えても全入口の既定が変わる。細かく選ぶのはカットの方法と順番・上書き。失敗したときは設定で選ぶ
  - 配信者(字幕の色): **配信のチャンネルから自動 + 覚える**(2026-09-27 の「自動では入れない」を変更)
  - キー: ? の一覧でそのまま変える(スタジオもそろえる)
  - 見直しは全部まとめて今回。**実装は PC の Claude Code**(このセッションは GitHub に push できないため)
- 分かったこと: 話者の色は Text+ と映像の上の字幕(0.21.0)には入っているが、パックの見本・カットのプレビューは話者の色を見ていない(GPT 監査 12 と同じ)。映像の上の字幕に出なかったのは、起動し直す前の古いコード・ホームから開いていない・名前が名簿と合わない、のどれかの可能性(PC で要確認。REQUEST 段2)。
  まとめて実行はパックの fps・縦横・話者の色のスイッチを無視している(常に 30fps・縦・色あり)
- 未完了・次: Claude Code が `REQUEST.md` の段0〜9 を実装(段9 = ui-dev-workflow の段階3: frontend-design・baseline-ui・design-review)
- 未コミット: .design/ux-consistency/DESIGN_BRIEF.md, .design/ux-consistency/AUDIT.md, .design/ux-consistency/REQUEST.md, docs/WORKLOG.md

## 2026-09-29 Claude Code — 文字起こしの精度改善 1回目の手順0: 評価用の文書を配信者単位で入れ替えた(作業データだけ・コードは変えていない)
- 担当: Claude Code — 文字起こし・自動カットの精度改善(`transcribe-tool/`・`tools/eval_asr.py`・`hololive-roster.json`)。計画の正本は Claude Docs「文字起こし・自動カット 精度改善 実装計画」
  (既存の `docs/transcription-overhaul-plan.md` に差分として組み込む。全7回の1回目 = 呼び名と文脈 + S-3)
- ユーザーの指示: 1回目は 0(評価用に移す候補の確認)→ 1-1 → 1-2 → S-3 の順。**1〜3 の実装は「まだ」**(ユーザー 2026-09-29)。0 の候補を一覧にして確認した
- 決定(ユーザー): 案 A = スバル・ルイ・ロボ子の文書は全部評価用 / 教師データ＿白上フブキ02・03 は評価用の印を外す / フブキの残り(教師データ01・04・05 は評価用・完成品4本は学習用)はそのまま / 印の付け替えは Claude が作業データを直す
- 変更(作業データ `%LOCALAPPDATA%/youtube-tools/transcribe/transcripts/`。ツールが全部止まっているのを確かめてから):
  評価用に = d879b7c7789d・8d54b4cecac9・faca6d306113・7e731bf9ce62(完成品デモのスバル 4本)・ed29a5d858af(ルイ)・d722c335f5be(ロボ子)/
  評価用を外す = 8e89d529ae24・855b1f53aa87(フブキ02・03)。updatedAt を進めた(開いたままの古い画面が保存すると 409 になり、印を戻さない)。控えは `transcripts/.bak/<id>.pre-evalset.json`
- 結果: 評価用 21 本・校正済み 9.9 分・6 人 / 学習用 8 本・2.6 分。段1 で使える誤りのペア(`learn_pairs`)は 66 組のうち学習用に出る 22 組。記録: `docs/project/eval-set-procedure.md` の「評価用の構成の記録」
- 移した文書のまだ校正していない行(評価に入れるには校正が要る): 26-09-08_鷹嶺ルイ 0:21.1〜0:31.0(声が重なる)・26-09-17_大空スバル 0:32.6〜0:35.6(声が重なる)。
  ほかに「聞き取れない」の印で未校正の行が 5 つ(09-05・09-12 に各1・09-17 に3。測定に入らない)
- 注意: 保管データ(dataset/docs/<id>/)の manifest・lines.jsonl の split は、次に保管し直すまで古いまま(保管の一覧は今の印で数えるので表示は正しい)。追加学習を作るときは文書の今の evalSet も見ること。
  文字起こしを消して保管データにだけ残っている学習用(星街すいせい・さくらみこ BOMBANANA・綺々羅々ヴィヴィ 3本)は「修正から学習」に使われていない
- 未完了・次: 段1-1(名簿の呼び名・誤りやすい形・普通の言葉と重なる印。`USER_INPUT.md` は空なので下書き → ユーザー確認)→ 段1-2(出る人の呼び名だけをプロンプトへ・評価用は渡さない設定も)→ S-3。**ユーザーの「始めて」を待つ**

## 2026-09-29 Claude Code — 精度改善 1回目の段1-1・1-2: 名簿の呼び名(下書き)と配信ごとの文脈(版は最後にまとめて上げる)
- 変更:
  - `transcribe-tool/hololive-roster.json`: `members`(55 人 = JP 全員と JP の卒業生。aliases = 呼び名・common = 普通の言葉と重なる呼び名・misrecognitions = 誤りやすい形)と `aliasesNote`。
    **呼び名は AI の下書き(ユーザーの確認待ち)**。誤りやすい形は、学習用の文書の修正(`learn_pairs`)に出る名前の誤り 6 組だけ(すぅー→スバル・みく→みこ・トルカ→ポルカ・トーイ/トーア→トワ・ヘヨ→ミオ。評価用にしか出ない 44 組は入れない)
  - `transcribe-tool/roster.py`(新): 名簿の読み込み・題名/チャンネル名から出る人を探す(正式な名前か、普通の言葉と重ならない 3 文字以上の呼び名だけ)・話者の名前との照合・ヒントの語(1人 = 名前 + 呼び名 3)・`fit`(語の途中で切らない)・`leak_only`(S-3 で使う)
  - `transcribe-tool/serve.py`: `stream_context`(配信のチャンネル名・コラボ相手 = スタジオの data.json を読むだけ・話者の名前・題名と動画のフォルダ名から出る人を決める。**題名の文字列は渡さない**)・
    `prompt_terms`(用語集 → 文脈。先頭 150 字)・`whisper_kwargs` は語の途中で切らない・`studio_videos` を `_studio_load` にしてコラボのまとまりも読む(`studio_stream`)・
    評価用として文字起こし(`evalSet: true` = 用語集・文脈・置換辞書・学習した置換を使わず、文書に評価用の印)・文書の `params.context`・`recognition.runs[].settings.promptChars/context`・
    温度 0 固定(`temp0`。測る道具だけ)
  - 画面(`index.html`・`app.js`): 設定「配信に出る人の名前と呼び名を、認識のヒントに自動で足す」(`autoContext`。**既定オフ** = 評価用で効くか測ってから決める)・文字起こしの開始に「評価用として文字起こしする」
  - `tools/eval_asr.py`: `--context none|auto`(既定 none = 基準)・`--temp0`・名前の再現率に呼び名も数える
  - テスト: `transcribe-tool/test_roster.py`(新・12 件。test_metrics から読む)・`tools/test_eval_asr.py`(文脈あり)・写すファイルの一覧に roster.py(9 か所)
- テスト(PC): 編集 単体 154・tools/test_eval_asr 4・ytt_core 56・app/test_mount・e2e_ui_mounted・e2e_edit_tabs 通過
- 決定・理由: スタジオの data.json は serve.py がすでに読んでいたので、別の部品(ytt_core)を作らず同じキャッシュでコラボのまとまりも読む(同じファイルを二重に読まない)
- 未完了・次: S-3(よくある誤認識の文・反復・プロンプトの漏れ出し)→ 文脈あり/なしの測定 → 版・資料。呼び名の下書きの確認(ユーザー)

## 2026-09-29 Claude Code — 精度改善 1回目の S-3(幻覚の印)と版 0.22.0・資料
- 変更:
  - `transcribe-tool/serve.py`: `HALLUC_LINE`(動画の締めの決まり文句。**行のほとんどがその文のときだけ** = 残り 3 文字以下。配信者が本当に言うこともあるため)・音楽の表記だけの行(♪・(音楽))→ `stock_phrase`。
    以前からの `HALLUC` は文の一部でも(今までどおり)。`repeats_in_line`(2〜10 文字が 5 回以上続く。1 文字の繰り返し = 笑い・叫びは除く)→「繰り返しの可能性」。
    近くの行に同じ文(4 文字以上・前の 5 行に 2 回)→「同じ文の繰り返し」。`LEAK_FLAG`「ヒントの語だけ(プロンプトの漏れ出しの可能性)」(3 秒以内でヒントの語だけ、または「用語:」を含む)。
    声の検出のやり直しは決まり文句・ヒントの語だけの結果を「文字 0」とみなす・緩い条件の認識は LEAK_FLAG の行も入れない・`REDO_BAD_FLAGS` に LEAK_FLAG
  - 版: 編集 0.21.0 → **0.22.0**(serve.py・app.js・README の見出しと変更の記録)。**画面の直し(ux-consistency)の依頼書の「編集 0.22.0」は、このあと 0.23.0 にする**
  - 資料: `transcribe-tool/AGENTS.md`(「名簿の呼び名と配信ごとの文脈」)・`docs/transcription-overhaul-plan.md`(9. 論文調査で採用した項目の組み込み・1回目の結果・採用の決まり)・`docs/accuracy/USER_INPUT.md`(1・2 に下書きの場所)
  - テスト: `test_roster.py` に S-3(5 件)。既存の `test_make_flags_latin_only_for_ja` は、行が用語集の語だけなので漏れ出しの印が付くのが正しい → 期待値を直した(英字の除外の確かめは残した)
- 評価用を除いた 85 本(機械の出力 773 行)で新しい印が付くのは 5 行(「ぱん」×10・「歩こう」×7・「げん」×5 など)。決まりは評価用を見ずに決めた
- テスト(PC): 編集 単体 159 通過
- 未完了・次: 評価用で文脈あり/なしの測定(`tools/eval_asr.py run --context none|auto --temp0`)→ 画面のテストの流し直し → 呼び名の下書きの確認(ユーザー)

## 2026-09-29 Claude Code — 気が利く画面へ(ux-consistency)段1: 知らせ・二度押しの確認・ホームの設定の置き場
- 担当: Claude Code — ux-consistency(app/・ui-kit/・transcribe-tool/・clip-studio/・cut2resolve/・ytt_core/colors.py)。正本は `.design/ux-consistency/DESIGN_BRIEF.md`、段取りは `REQUEST.md`
- 始める前に: GPT の未コミットの作業は無い(09-28 の GPT の UI 監査は文書だけ)。版: 編集は精度改善で 0.22.0 を使ったので、**この見直しでは 編集 0.23.0**・ホーム 0.13.0・cut2resolve 0.15.0・スタジオ 0.11.0(09-28 の予約分と一緒)を最後にまとめて上げる
- 変更:
  - `ui-kit/ui-kit.js`(v7)・`ui-kit.css`: `UIKit.toast` の `ms: 0` = 消えない(以前は `opt.ms || 既定` で 0 が 2.5 秒に戻っていた。S-9)・`action: {label, fn}`・閉じる(×)・戻り値 `{close, el}`。
    `UIKit.confirmTwice(btn, run, text)`(二度押しの3つの実装を1つに)・`.btn.armed` を ui-kit へ。`UIKit.prefs`(get・patch(同じ節を 400ms まとめて)・flush・remember・available。失敗は知らせと [もう一度])
  - `app/prefs.py`(新)・`launch.py`: `POST api/ytt/prefs`(op get / patch / remember)。作業データの `app/prefs.json`。節ごと(autorun・keymap は送ったキーだけ直す・streamer は1件ずつ覚える。種類ごと 2000 件・古い順に捨てる)・
    許可した形だけ・知らないキーは捨てる・256KB まで・壊れたファイルは退避して既定で動く・合言葉と Host/Origin の検査は既存の1か所
  - 二度押しの置き換え: スタジオ `review.js`・`collab.js`、編集 `app.js`(声を忘れる・話者判別し直す は何が起きるかの文言に)。
    **戻せる操作は確認をやめて知らせの [元に戻す]**(E-22・S-23): スタジオ「候補をすべて採用」(変えたマークだけ候補に戻す)・編集「全行を校正済みに/全解除」(Ctrl+Z と同じ doUndo)
  - テスト: `app/test_window.py`(TestPrefs 4 件・api/ytt/prefs)・`ui-kit/e2e_styleguide.py`(ms:0・ボタン・×・二度押し)・`clip-studio/test_review.cjs`(ui-kit の confirmTwice を試す)・`transcribe-tool/e2e_ui_v07.py`(全行の校正は確認なし・知らせに「元に戻す」)
- テスト(PC): 入口 単体 98・スタジオ node 18・e2e_ui 144・編集 e2e_ui_v07・ui-kit e2e_styleguide・sync 通過
- 未完了・次: 段2(話者の色)。ブリーフにある「編集の PUT /api/settings を送ったキーだけ直す」は段7(保存の失敗)でまとめて行う

## 2026-09-29 Claude Code — 気が利く画面へ 段2(話者の色)の途中で中断(ユーザー「一度中断」)
- 途中までの変更(このコミットに入れた。画面のテスト e2e_edit_pack は通過):
  - 色を決めるのは `transcribe-tool/app.js` の `speakerColor(spId)` の1つ(`SPKC`・`lookupSpeakerNames` で名前をまとめて1回照らし合わせ・`rowSpColor`・`onSpeakerColors` で塗り直し)。
    行の左端の線・話者の欄(メンバーの色の見本と理由の1行・名前の候補 datalist `#spNames` = 覚えた声・配信者・名簿)・映像の上の字幕・カットのプレビュー(`cut.js` の `showCaption`・`refreshCaption`)・パックの見本(`pack-tab.js` の `#pkSamples`・`#pkPhoneCap`)
  - スイッチ「話者の名前がメンバーと合えば…」は編集の設定 `speakerColors` へ(初回だけこのブラウザの `tx.pk.speakerColors` から移す)。`app/autorun.py` の `_pack_settings` も同じ値をパックの `output.speakerColors` に渡す(以前は常にオン)
  - 入口 `api/ytt/streamer-colors` に `names`(まとめて照らし合わせ → `matches`)
  - 話者判別が終わったら知らせに [名前を付ける](名前の無い最初の欄へフォーカス)。`app.js` の `toast(msg, {…})` はオブジェクトなら UIKit.toast へ
  - `e2e_edit_pack.py`: 見本の電話の字幕は1行目の話者の色・行の線の色・スイッチを切ると全部消えて設定に残る
- **未完了(次にやること)**: `app/test_window.py` に names のまとめて照らし合わせ・`app/test_autorun.py` に speakerColors が渡るテスト / `e2e_ui_mounted`・`e2e_edit_cut`・`e2e_edit_tabs`・`e2e_edit_voices`・`app/e2e_autorun` の流し直し / 段2 の WORKLOG の本記録
- 精度改善 1回目の測定: 基準(文脈なし・温度0)は終わった(作業データの `evals/asr/20260929-211155_段1-基準-temp0.json`)。**文脈ありの回が裏で動いている**(終わると同じフォルダに `段1-文脈あり-temp0`)。
  判定は決めておいた採用の決まり(`docs/transcription-overhaul-plan.md` の 9)で、呼び名の下書きの確認のあとに行う。今回は前回より約3倍遅かった(原因は未確認)

## 2026-09-29 Claude Code — パックの音量(LUFS にそろえる)をパック作りとまとめて実行の欄に(ユーザー「まずこれだけすぐ」「テストは後に回して実装」)
- ユーザーの指示: 「まとめて出力や最後のパック生成のところで音量調整したい」。質問で決定: 場所 = パックを作るとき + まとめて実行の欄・決め方 = LUFS にそろえる(スタジオと同じ選択肢)
- 変更:
  - `ytt_core/loudness.py`(新): 選べる値(-11/-14/-16/-18)・ピークの上限 -1 dBTP・上げる量の上限 +20 dB・loudnorm の読み方・かける量・区間だけ測る aselect。**スタジオの書き出し(`clip-studio/exporter.py`)もこれを使うように**(動きは同じ。test_exporter 25 件通過)
  - `cut2resolve/cut2resolve_core.py`: `measure_loudness`(残す区間だけ)・`copy_video_gain`(映像はそのまま・音声だけ作り直す。webm は Opus)・`render_rough_cut(gain_db)`・`loudness_mod`(コマンドで動かすときも ytt_core を読めるように)
  - `cut2resolve/pack.py` `build_pack(loudness=)`: カットで残す区間(余白つき素材なら、それに合わせた区間)を測り、同梱の動画と粗編集の動画に同じ量。元の動画は書き換えない(パックの動画が元と同じ場所ならそろえずに注意)。結果 `loudness`
  - `cut2resolve/serve.py`: `output.loudness`(検査は ytt_core/loudness.check_target)・結果に `loudness`
  - 値の置き場: 編集の設定 `packLoudness`(既定 -14・0 = そろえない)。**`POST /api/settings/patch`(送ったキーだけ直す・許可した項目だけ)でしか変えない**。
    丸ごとの保存(PUT /api/settings)では、この項目はサーバーの値を残す(開いたままの古い画面が戻さないように)
  - 画面: 編集 3 パック の「設定を変える」→「2 パックに入れるもの」に「音量のそろえ方(LUFS)」・要約・作ったあとの知らせに結果。
    まとめて実行の欄(編集の題名の行・ホームの案件・スタジオ ③ のメニュー)に「パックの音量」= ui-kit の `UIKit.packLoud`(mount・get・set。編集の場所が分かってから欄を出す・どこで変えても同じ値)
  - `app/autorun.py`: まとめて実行のパックの段も `packLoudness` を `output.loudness` に
  - 版: 編集 0.22.0 → **0.23.0**・cut2resolve 0.14.0 → **0.15.0**・ホーム 0.12.0 → **0.13.0**・スタジオ 0.10.0 → **0.11.0**(09-28 の予約分と、気が利く画面へ 段1〜2 もこの版に含む)。
    **気が利く画面へ の最後の版上げは、この次の番号にする**
- 確かめたこと: 測る・音声だけ作り直して写す、を ffmpeg で手元で確認(-47.9 LUFS の音 → 上げる量の上限 +20 dB で -27.9)。**テストは書いていない(ユーザーの指示で後回し)**
- 未完了・次(テスト): ytt_core/loudness の単体・cut2resolve の test_pack(loudness あり/なし/音声なし/同じ場所)・test_serve(output.loudness の検査)・
  transcribe の api/settings/patch と PUT の保持・app/test_autorun(loudness が渡る)・e2e_edit_pack(欄・要約・知らせ)・ホーム/スタジオの欄の e2e・契約テスト `tools/test_resolve_pack_contract.py`(単独で)。
  zip(`/api/resolve-package`)には音量を入れていない
- 注意: 起動中の入口は古いコードのまま。「すべて終了」→ start-all.bat で起動し直す

## 2026-09-29 Claude Code — パックの音量を % でも決められるように(ユーザー「まだ大きい。原因は」→「単位が分からないから % でも」)
- 調べたこと(21:33 のパック。鈴鳴つづり 02_00h37m12s-00h37m32s): 目標は **-18 LUFS** が選ばれていて、残す区間は元 -18.8 → パック -18.0 LUFS(+0.8 dB = 約 110%)。処理は選んだ値どおり。
  「小さめ」を選んでも元がそれより小さかったので**少し上がった**。さらに冒頭 0.4 秒付近に一瞬 -9.7 LUFS(平均より約 8 dB 大きい)があり、LUFS でそろえるのは平均だけなのでこの差は残る。
  同じ名前で上書きしたので、Resolve が前の動画を読んだままの可能性もある(開き直すと確実)
- 変更: 選択肢に「音量を % で決める」(編集の設定 `packVolume`。1〜200・元 = 100。`packLoudness` = 0 のとき使う)。cut2resolve の `output.volume`(測らずにその量。`ytt_core/loudness.check_volume`・`pct_to_db`)。
  まとめて実行も packVolume を渡す。画面: パックのタブの「%」の欄・要約「音量 70%」・知らせに % も(「元の約 110%・+0.8 dB」)。まとめて実行の欄(UIKit.packLoud)も LUFS / % の両方(値は {loud, vol})。
  LUFS の選択肢に言葉を添えた(「YouTube と同じくらい」「小さめ」など)。版は上げていない(0.23.0 / 0.15.0 / 0.13.0 / 0.11.0 のまま。まだ配っていない同じ版)
- テストは後回し(ユーザーの指示)。大きい瞬間だけ抑える(リミッター・コンプレッサー)は提案したが、未決定

## 2026-09-29 Claude Code — 精度改善 1回目の測定の結果: 配信ごとの文脈は不採用(既定オフのまま)
- 評価用 21 本(音声 1,057 秒・large-v3・CPU・温度0): 文脈なし CER 22.8% / 文脈あり 59.5%(差 +36.7 pt、95% の範囲 +18.0〜+59.0)。余分 157 → 678 字。
  事前に決めた採用の決まり(`docs/transcription-overhaul-plan.md` の 9)の ①② を満たさない → 不採用
- 崩れ方: ヒントの語をカンマ区切りで繰り返す(hotwords の一覧の形をまねた・温度0でやり直しが働かない、とみられる)。S-3 の印はこれらの行に付いた
- 結果のファイル: 作業データの `evals/asr/20260929-211155_段1-基準-temp0.json`・`20260929-212751_段1-文脈あり-temp0.json`。今回は 09-28 より約2倍遅かった(実時間の 0.78 倍。原因は未調査)
- 次(2回目以降): 直し方の案は計画書の 9 に書いた(学習用の文書で先に試す)。呼び名の下書きの確認(ユーザー)は引き続き待ち

## 2026-09-29 Claude Code — 気が利く画面へ 段2 の残りと、パックの音量のテスト(後回しにしていた分)
- テストを足した: `ytt_core/test_ytt_core.py`(TestLoudness: 値の検査・% ⇔ dB・loudnorm の読み方・かける量の決まり・区間の選び方)、
  `cut2resolve/test_pack.py`(残す区間だけ測って同梱の動画をそろえる・% で決める・そろえない・元の動画は書き換えない・粗編集の動画にも同じ量)、
  `cut2resolve/test_serve.py`(output.loudness / volume の検査)、`app/test_window.py`(streamer-colors の names)、
  `app/test_autorun.py`(まとめて実行のパックが編集の設定の話者の色・音量(LUFS / %)に従う)、
  `transcribe-tool/test_edit.py`(api/settings/patch と、丸ごとの保存で音量が残る)、`transcribe-tool/e2e_edit_pack.py`(音量の欄・% の欄・要約・設定に残る・作ったあとの知らせ)
- テスト(PC): ytt_core 58・入口 単体 60・cut2resolve 291・編集 単体 160・契約 27・e2e_edit_pack・e2e_ui_mounted・e2e_edit_tabs・e2e_edit_cut・e2e_edit_voices・
  入口 e2e_portal・e2e_autorun・スタジオ e2e_ui --mounted 157 すべて通過
- 段2(話者の色)はこれで終わり。次: 段3(カットしない)

## 2026-09-29 Claude Code — 気が利く画面へ 段3: カットしない
- 変更:
  - カットのタブ: 「行から」の隣に「カットしない」(`#cutNone`・`draftWhole`)。残す区間 = 動画全体(origin `whole`。serve.py の `EDIT_ORIGINS` に足した)。Ctrl+Z で戻る。
    行の「カット済」は編集の内容から付け直す決まりなので、動画全体を残すとカット済の行が無くなり、**字幕も全部出る**(パックは EDIT_KEEPS = drop_cut_rows なし)。下の行に「(カットしない = 動画全体)」
  - まとめて実行: カットを決めていない文書のカットの方法を、ホームの設定 `autorun.cut` から(`AutoRunner(prefs=)`・`_cut_method`)。
    rows = 今までどおり(preset transcript-rows)/ none = 動画全体(時刻リストの「削る」を空で・`dropCutRows: false` = カット済の行の字幕も消さない)/
    silence = 無音で削る(値は編集の設定 `cutSilence` {noise, min, pad}。無ければ cut2resolve の既定)。保存済みのカットがある文書は、今までどおりそのカット
  - 方法を選ぶ欄は段4(まとめて実行の部品 `UIKit.autorun`)で作る
- テスト: `e2e_edit_cut.py`(カットしない・カット済が無くなる・Ctrl+Z)、`app/test_autorun.py`(none・silence・既定 rows)。入口 単体・編集 単体 160・e2e_edit_cut 通過

## 2026-09-29 Claude Code — 気が利く画面へ 段4a: まとめて実行のサーバー側
- 変更(`app/autorun.py`・`launch.py`):
  - パックの設定は編集の設定のとおり(`_pack_settings`): fps(packFps)・縦横(packSize)・予備(packBackup)・1段の文字数は縦横に合わせる(横なら wrapChars.horizontal)・話者の色・音量。
    「行から」の設定(rowEdge)の形が変なときは既定で作って知らせる(`_row_edge_ok`。以前は cut2resolve の 400 でパックの段が失敗)
  - 配信単位の実行でも「パックがあれば作り直す(上書き)」(`start(overwrite=)`・API の overwrite。S-12)
  - 失敗したとき(ホームの設定 `autorun.onFail`: next = 残りを続ける・既定 / stop = そこで止める): 書き出し・文字起こし・パックの1本ずつの失敗に効く。
    パックの1本の失敗は、next なら段を「一部失敗」にして残りを作る(以前はそこで実行ごと止まった)
  - 何もしなかったら「完了」と言わない(`_finish_message`。どの段も飛ばした = `nothing`・「やることがありませんでした」。S-4)
  - 状態の言葉を1か所に(`STEP_STATE_LABELS`・`RUN_STATE_LABELS`。各段と実行に `stateLabel`。S-2)
  - 見積もり `POST /api/autorun/estimate`(実行と同じ規則で段ごとの本数と飛ばす理由。書き込まない。前の段の結果しだいの本数は null)
- 後回し(報告): カットの無い文書で作ったパックの記録(`/api/edit/pack` は保存したカットが要る。まとめて実行がカットを保存することになるので、動きの変更として相談する)
- テスト: `app/test_autorun.py`(TestStage4 6 件)。入口 単体 99・e2e_autorun 通過
- 次: 4b(共通の部品 UIKit.autorun)

## 2026-09-29 Claude Code — 気が利く画面へ 段4b・4c: まとめて実行の部品(UIKit.autorun)と 8 つの入口
- 変更:
  - `ui-kit/ui-kit.js`(v7)・`ui-kit.css`: `UIKit.autorun` = panel(要約1行 +「設定を変える」のポップオーバー: 形・採用数・カットの方法・パックの置き先(fps)・大きさ・音量・話者の色・予備・上書き・1本が失敗したとき)・
    start(見積もり → やることが 0 なら始めない →「始めました(書き出し 2 本 → 文字起こし あとで決まる → …)」→ 終わったら知らせ [校正を始める] / 止まったら [やり直す])・watch・stepLabel / runLabel(状態の言葉)。
    値は1か所: 形・採用数・カット・上書き・失敗したとき = ホームの設定 autorun、パックの出力 = 編集の設定(送ったキーだけ直す)
  - 編集の設定の「送ったキーだけ直す」に packFps・packSize・speakerColors・packBackup を足した(丸ごとの保存ではサーバーの値が残る)。
    3 パック のタブもこれで保存(fps・大きさ・話者の色・予備。**予備は覚えるようにした** = E-4 の一部)。タブを開くたびに読み直す
  - 入口: ホームの案件(形の初期値は配信の状態から・採用数と形はホームの設定・見積もり)/ ホームの紐づかない文書(上書きの文言をそろえ、ホームの設定と同じ値)/
    スタジオ ① 探す(採用数を覚える・部品で始める)/ スタジオ ③ のメニュー・マークの行の「この後を ▸」(見積もり)/ 書き出しのあとの自動の文字起こし(終わったら知らせ)/
    編集の題名の行・履歴(見積もり・上書きはホームの設定と同じ値)。どの入口にも要約1行と「設定を変える」
  - 状態の言葉: ホーム・スタジオ・編集の別々の表をやめ、サーバーの stateLabel(待ち・実行中・済み・飛ばした・一部失敗・失敗・中止・やることがありませんでした)
- テストの期待を直した(意図した動きの変更): `app/e2e_autorun.py`(2回目は見積もりで「やることがありません」と出して始めない)・`e2e_edit_pack.py`(完了 → 済み。待つのは実行の札)・`clip-studio/e2e_ui.py`(帯の言葉)
- テスト(PC): e2e_autorun・e2e_portal・e2e_edit_pack・e2e_edit_tabs・e2e_ui_mounted・スタジオ e2e_ui --mounted 157・e2e_ui 144(1回目に1件「設定を開いている間のショートカット」が落ち、流し直すと通った)・ui-kit e2e_styleguide・node 18・sync 通過
- 次: 4d(全選択・パックが無いものだけ・20 本まで・失敗の札・「校正を始める」で開く文書)

## 2026-09-29 Claude Code — 気が利く画面へ 段4d: 全選択・パックが無いものだけ・20 本まで・失敗の札・「校正を始める」で開く文書
- 変更: ホームの紐づかない文書と編集の履歴に「表示中を全部選ぶ」「パックが無いものだけ選ぶ」と「20 本まで」(超えたら押せず理由を出す。S-11)。
  ホームの文書の行は、失敗した実行の札「失敗」を残す(理由は札のツールチップ。以前は終わると札が消えた。S-5)。
  まとめて実行の結果に扱った文書の id(`docs`)を残し、終わったときの知らせの [校正を始める] でその文書を開く(配信単位の実行でも)
- テスト: `app/test_autorun.py`(docs)・`e2e_edit_pack.py`(パックが無いものだけ選ぶ)。入口 単体・e2e_portal・e2e_edit_pack 通過
- 段4 の残り(後回し・報告): カットの無い文書で作ったパックの記録(4-4)。ホームの `#docRunSteps`・`#docRunMsg` は使っていない(進み具合は行の札と知らせで出す)
- 次: 段5(配信者の自動と記憶)

## 2026-09-29 Claude Code — 気が利く画面へ 段5: 配信者の自動と記憶
- 変更(ユーザーの答え「配信のチャンネルから自動 + 覚える」。`docs/followup-2026-09-27.md` の 4 を直した):
  - `ytt_core/colors.from_channel`: 配信のチャンネル名に正式な名前(2文字以上)か英語名(4文字以上)がそのまま含まれ、1人に決まるときだけその人(マイカラーは使わない)
  - `app/prefs.guess_streamer`: 決める順 = 文書に覚えた名前 → 配信に覚えた名前 → チャンネルに覚えた名前 → チャンネル名から。空を覚えていれば「色なし」(自動で入れ直さない)。
    入口の API `api/ytt/streamer-guess`({docId?, videoId?, channel?}。文書だけなら元の配信・チャンネルを調べる)
  - まとめて実行: 配信者を送らなかった実行(None)は、実行ごとに同じ順で決め、パックの段に「字幕の色: ○○(自動: チャンネル名から / 前回の名前)」と出す。空で送った = 色なし(`streamerFrom`)
  - `UIKit.streamer.autoFill(input, ctx)`: 欄に自動で入れて札「自動(チャンネル名から)」「前回」「前回: 色なし」。手で直したら(change)文書・配信・チャンネルに覚える。
    打ち始めたら、あとから届いた自動の名前で上書きしない(同じ相手の欄を直したあとは入れ直さない)。
    `UIKit.streamer.check(input)`: 始める前に照らし合わせ直し、メンバーに見つからなければ「色なしで進める」か聞く(S-20。以前は始めたあとでエラー)
  - 入口: 編集の題名の行のまとめて実行・3 パック のタブ(以前はこのブラウザの tx.streamer.v1 → ホームの設定へ移す)・ホームの案件・スタジオ ③ のまとめて実行。
    スタジオのマークの行の「この後を ▸」に、使う字幕の色を出す(S-10)。スタジオは欄が空でも送る(空 = 色なし)
- テストで見つけて直した: 自動の名前の問い合わせの途中に打つと打った名前が消えた・描き直した直後(照らし合わせの途中)に始めると「見つかりません」と聞いていた
- テスト: `ytt_core/test_ytt_core.py`(from_channel)・`app/test_window.py`(決める順・API)・`app/test_autorun.py`(TestStage5)・`e2e_edit_pack.py`(文書ごとに覚える)。
  ytt_core・入口 単体 104・e2e_edit_pack・e2e_autorun・e2e_portal・e2e_edit_tabs・e2e_ui_mounted・スタジオ e2e_ui --mounted 157・ui-kit e2e_styleguide・node 18 通過
- 次: 段6(? でキーを変える)

## 2026-09-29 Claude Code — 気が利く画面へ 段6(途中): ? でキーを変える(UIKit.keymap)
- **途中でセッションを切り替えた(ユーザーの指示)。コミットは WIP**。残りは下の「残り」
- 変更:
  - `ui-kit/ui-kit.js`(v8)・`ui-kit.css`: `UIKit.keymap.create(opt)` = キーの一覧がそのままキー配置の設定。? の一覧と ⚙ の「キー配置」は同じ部品(`mount(el)`)。
    キーのボタン → その場で次のキーを待つ(Esc = 取り消しだけ・一覧は閉じない / Delete = 外す / 変換中は受け取らない / 断ったら待つのを続けて理由を一覧の中に)。
    重なりは「「X」から外しました [戻す]」(一覧の中。モーダルの上なので知らせは使わない)・行ごとの「標準」・すべて標準に戻す・変えられないキーは錠と理由。
    重なりの検査は部品の1か所: 共通の再生キーにできないキー `PB_BLOCKED`(全ツールの固定キー・編集の 2 カット のキー・数字)・ツールの `refuse`・派生キー(← → のキー + Shift = 5秒。GPT-03)。
    共通の再生キーはホームの設定 `keymap.playback`(入口の外では `fallbackPlayback`)。初回は編集の settings.keymap にあった再生キーを移す。戻ったとき(`UIKit.life.onReturn`)に読み直す。
    `UIKit.keys.playback` は変換中を受け取らない・`onKey(name, action)` に操作を渡す。錠のアイコン `lock`
  - 編集(`app.js`・`cut.js`・`index.html`): KEY_DEFS・keyRefusal・sanitizeKeymap・kmCap・setKey・#kmReset をやめて部品へ。#keys の中身は `#keysList`(部品)+ `#keysFlow`(基本の流れを今の割り当てから)。
    ? をもう一度押すと閉じる(S-29)。行のボタンのツールチップ・「もう一度 Z」・2 カット のキーの帯とタイムラインの下の案内 `#cutKeysText` も今の割り当てから(GPT-16・S-30)。
    2 カット のキーは `CUT_KEY_ROWS` の1か所(一覧に出す)。1コマのキーを変えたら「そのキー + Shift」で10コマ。
    重ねて開いた左のメニューの中のキーは後ろの文書を動かさない(`menuHasKeys`。GPT-04)。校正のキーの保存は `api/settings/patch` の `keymap`(serve.py の SETTINGS_PATCH_KEYS。形は fullmatch で検査)
  - スタジオ(`review.js`・`core.js`・`review.css`): setKey・startCapture・SHARED_KEYS をやめて部品へ(③ のキー配置と ? の一覧 `#keyHelpBody`)。共通の再生キーもスタジオで変えられる(S-27)。
    組み合わせの名前は実際の割り当てから(S-28)。IN/OUT のボタンの横のキー・キーの帯も今の割り当てから。変換中は受け取らない。「標準に戻す」ボタンは部品の「すべて標準に戻す」へ
  - `app/prefs.py`: キーの形の検査を fullmatch に(`$` は末尾の改行の前にも合うので "s\n" が通っていた)
- テスト(通過): 編集 単体 151(`test_edit.py` に keymap の patch)・入口 test_window 35・ui-kit sync・`e2e_ui_v08.py`(キー配置の欄を新しい部品に合わせて直した)・**新しい `app/e2e_keymap.py`**(移す・Esc・変換中・派生キー・[戻す]・標準・スタジオと同じ再生キー・GPT-04)
- 残り(次のセッション):
  1. 流していないテスト: `e2e_edit_tabs.py`・`e2e_ui_handoff.py`(? で開く)・`e2e_edit_cut.py`(帯)・`e2e_edit_pack.py`・`e2e_ui_mounted.py`・スタジオ `e2e_ui.py` と `--mounted`(? の一覧の中身の確認 402 行付近)・
     `node --test clip-studio/test_review.cjs`(review.js の関数を切り出すテスト。KM が無い形で動くか)・ui-kit `e2e_styleguide.py`・入口 `e2e_portal.py`・`e2e_window.py`
  2. `app/test_window.py` に prefs の "s\n" を断るテストを足す(書きかけで入っていない)
  3. ui-kit の README.md に「v8」(UIKit.keymap の使い方)・transcribe-tool/AGENTS.md の「キー配置」の項を新しい形に書き直す・AGENTS.md の表に `app/e2e_keymap.py`
  4. 段6 を WIP でない形でコミット → 段7 → 段9 → 版を上げる
- 未コミット: なし(このコミットに全部入れた)

## 2026-09-30 Claude(Cowork)— 段0 リポジトリのフォルダの整理の計画
- 変更: `docs/plan/phase0-restructure.md` を新規作成(計画のみ。コードは触っていない)
- 決定・理由(ユーザー 2026-09-30): リポジトリの並べ替えとフォルダ名の変更をやる(app→home・clip-studio→studio・transcribe-tool→editor、テストは各ツールの tests/、tools→dev/setup、docs を spec/plan/design/archive に)。
  Python のパッケージ化は後回し。実施は Claude Code(PC)。置き場所は C:\dev\youtube-tools に clone し直して入れ替える。動画(E:\Video)の整理は保留
- 注意: 計画は GitHub の main(09-29)を読んで書いた。PC はその後に進んでいる(編集 0.22.0・test_roster.py など)ので、始める前に今のコードで対象を数え直す。
  線 B・画面の直し(ux-consistency)の作業と同時に進めない(段の切れ目で入れる)
- 未コミット: docs/plan/phase0-restructure.md, docs/WORKLOG.md

## 2026-09-30 Claude Code — 止まっていた push の rebase の片付け・気が利く画面へ 段6 の仕上げ(段0 の前)
- 変更(rebase): 09-30 00:27 の push.bat の `git pull --rebase origin main` が `transcribe-tool/AGENTS.md` の衝突で止まっていた(21 コミット中 9 まで)。
  衝突は GitHub 側(Cowork が版の歴史を短くした)に 0.22.0 の行を足して解決 → 残り 12 は衝突なし。コードは rebase 前の c4ff7aa と同じ(GitHub 側の 4 コミットは docs と AGENTS.md だけ)。
  Cowork が rebase の途中に書いた WORKLOG の追記は stash でどけて戻し、`docs/plan/phase0-restructure.md` と一緒にコミットした(356befe)
- 変更(段6 の残り): `app/test_window.py`(prefs の keymap で末尾の改行 "s
" を断るテスト)・`ui-kit/README.md`(v8 = `UIKit.keymap` の使い方)・
  `transcribe-tool/AGENTS.md`(キー配置の項を部品の形に書き直した)・`AGENTS.md`(表に `app/e2e_keymap.py`)
- 変更(改行): `tools/sync_ui_kit.py` の `read` を改行をそろえて読むように(+ `test_ui_kit_sync.py` にテスト)。rebase で作業フォルダが CRLF で書き直されると、
  写しの見出しの行(HEADER は LF)だけが食い違って `test_ui_kit_sync` が落ち、写し直すと index.html の埋め込みの末尾に空行が増えていた。段0 の clone し直しでも同じことが起きるため
- テスト(PC・通過): `e2e_edit_tabs`・`e2e_ui_handoff`・`e2e_edit_cut`・`e2e_edit_pack`・`e2e_ui_mounted`・スタジオ `e2e_ui.py`(144)と `--mounted`(157)・
  `node --test clip-studio/test_review.cjs`(18)・`ui-kit/e2e_styleguide.py`・`app/e2e_portal.py`・`app/e2e_window.py`・`app/e2e_keymap.py`・`app/test_window.py`(35)・`tools/test_ui_kit_sync.py`(5)
- 未完了・次: 段6 はこれで終わり(WIP を解いた)。気が利く画面への段7・段9・版を上げるのは、段0(フォルダの整理)のあと。次は段0
- 注意: ui-kit/README.md に v7(気が利く画面へ 段1〜5 の部品: 知らせ・二度押しの確認・UIKit.autorun など)の節がまだ無い
- 未コミット: なし

## 2026-09-30 Claude Code — 段0(リポジトリのフォルダの整理)開始
- **段0 開始。GPT(Codex)・Cowork はコードの作業を止めてください**(フォルダ名が変わる。終わったらここに書く)。計画は `docs/plan/phase0-restructure.md`
- 始める前のテスト(PC・09-30): unit 12 組・e2e 21 本すべて通過。落ちていたのは `transcribe-tool/test_document_save.cjs`(4/9。段5 で openDoc が呼ぶ `lookupSpeakerNames` をテストの置き換えに足していなかった)だけで、置き換えを足して 9/9
- 注意: `clip-studio/e2e_review.py` はテストではなく手で見るための見本サーバー(止まらない)。全部流すときに入れない
- 未コミット: なし

## 2026-09-30 Claude Code — 段0 コミット1: フォルダの移動とパスの直し(資料はまだ)
- **フォルダ名が変わった**(対応表は `docs/plan/phase0-restructure.md`): `app/`→`home/`・`clip-studio/`→`studio/`・`transcribe-tool/`→`editor/`・`tools/`→`dev/`(インストールと片付けは `setup/`)・
  `start-all.bat`/`.command`→`start.bat`/`.command`。各ツールのテストは `<ツール>/tests/`(cut2resolve の Resolve の確認用データは `cut2resolve/tests/fixtures/`)。
  古い e2e は機能の名前に: `e2e_ui_v07`→`e2e_proofread_accuracy`・`v08`→`e2e_proofread_keys`・`v09`→`e2e_folder_marker_range`・`e2e_eval_v093`→`e2e_eval_set`・`v098`→`e2e_row_editing`(消した・まとめたテストは無い)
- 新しい `ytt_core/layout.py`: ツールの ID → フォルダ名(`TOOL_DIRS`)・`repo_root()`・`tool_dir()`。フォルダ名を知る場所(launch・mount・cases・txindex・colors・編集の serve.py のスタジオの場所・sync_ui_kit・e2e)はここを読む
- 変えていない(互換): `/api/ping` の app の値・JSON の tool.name と schema・作業データの ID(`%LOCALAPPDATA%\youtube-tools\{app,studio,transcribe,cut2resolve}`)・.runtime の ID・URL・ポート
- テストはリポジトリ直下から流す形にそろえた(例 `python -m unittest home/tests/test_launch.py`・`python editor/tests/e2e_edit_tabs.py`)。
  `cut2resolve/tests` は、フォルダ名 `cut2resolve` が CLI の `cut2resolve.py` を隠すので、CLI を `importlib` で読む。一時フォルダに写すツールから `tests/` を除く
- 作業: git mv は Claude Code、パスの直しはサブエージェント4つ(home・ytt_core = Opus、studio・editor・cut2resolve/dev/setup = Sonnet。AGENTS.md の新しいルール)
- テスト(PC・新しい配置): unit 12 組・e2e 21 本すべて通過(`home/tests/test_window.py` の1件は接続の打ち切りで1回落ち、流し直し3回とも通過)。
  入口を起動して 3 ツールが動作中・画面 4 つが応答・案件 42 件・作業データは %LOCALAPPDATA% のまま
- スタジオの書き出し先は `E:\Video\…`(古いフォルダの外。手順6で古いフォルダを消しても動画は失わない)
- 未完了・次: **コミット2(docs の並べ替え・AGENTS.md の表とテストのコマンド・各 README・ROADMAP の索引)はまだ**。AGENTS.md・README の中のパスとテストのコマンドは古いまま。
  次は push → 手順6(`C:\dev\youtube-tools` に clone し直し)→ 新しい場所で全部のテスト → コミット2。GPT・Cowork は引き続き止める
- 未コミット: なし

## 2026-09-30 Claude Code — 段0 コミット2: 資料の並べ替えと索引・手順6(clone し直し)
- 手順6: push(3cec845..d44855c)→ `git clone -c core.autocrlf=true … C:\dev\youtube-tools` → ユーザーが新しい場所の start.bat で起動を確認。**これからの作業フォルダは `C:\dev\youtube-tools`**
- docs を種類で分けた: `docs/spec/`(pipeline・data-location・ui-guidelines・usability-heuristics)・`docs/plan/`(phase*・transcription-overhaul-plan・ui-audit・accuracy/)・
  `docs/design/`(integration-plan・edit-tool-design・mockups・whole-retranscribe-design・resolve-pack-unification・holo-colors)・`docs/archive/`(project・review・followup・backlog-ui・TRANSCRIPTION_V2_DESIGN.md)
- 旧 → 新のパスを機械で置き換え(コミット1 の改名の一覧 + docs の移動。89 ファイル・約 690 か所。コードの側はコメントだけ)。WORKLOG・`docs/design/`・`docs/archive/`・`.design/ui-overhaul/` は当時の記録なので変えない
- 文章の直し: AGENTS.md(フォルダの表・テストのコマンドをリポジトリ直下からに・`setup/` の行・識別子とフォルダ名は別・文書の置き場所の決まり・作業フォルダの場所)・`editor/AGENTS.md`(テストの一覧・古い「想定内の失敗」を消した)・
  ROADMAP(先頭に対応表へのリンク・段0 の行・版の一覧・索引)・HANDOVER・各 README・spec・plan・`.design/ux-consistency/`(README・spec・plan はサブエージェント Sonnet)。`dev/baseline_analysis.py` の既定の出力先を `docs/plan/accuracy` に
- テスト(新しい場所): ui-kit の写しの検査・dev 24・ytt_core 60・home unit 140・studio の api/handoff すべて通過(コードはコメントだけの変更)
- 未完了・次: 古いフォルダ `Desktop\youtube-test` を `youtube-test_old` に改名(このセッション・VS Code・ターミナルを閉じてから)。
  そこにだけあるもの: `Claude outputs\`(2.8MB)・Resolve の手の確認用の動画 `cut2resolve\tests\fixtures\resolve-ui-test\*.mov`(77MB×2)は、要るなら新しい場所へコピー。1 週間ほど問題が無ければ消す。
  Codex・Claude Code・Cowork の作業フォルダを `C:\dev\youtube-tools` に向け直す。新しい場所で全部のテストを流す(夜に流す予定だった分)
- **GPT・Cowork: 段0 は済んだ。作業を再開してよい(新しいフォルダ名と `C:\dev\youtube-tools` で)**
- 未コミット: なし

## 2026-09-30 Claude Code — push の検査が docs/archive/ を作業データと誤検出した件
- コミット2(c422f14)のとき、`dev/push_helper.py check` が `docs/archive/` の 37 個の文書を「作業データのフォルダ(archive/)の中」として止めた。
  **Claude Code がコマンドを `;` でつないでいたため、止まった表示のままコミットと push まで進んだ**(手順のミス。以後、検査は `&&` でつなぐ)。中身は前から公開していた古い資料(`docs/project/`・`docs/review/` などを移したもの)で、個人データは無い
- 直し: `push_helper.problems_for` のフォルダ名の規則から `docs/archive/` 直下だけを外した(その下の作業データの名前・ログ・秘密情報・大きさは今までどおり止める。テストに両方の例を足した)。
  `.gitignore` の `**/archive/` のあとに `!docs/archive/`(外さないと、今後 docs/archive に足した文書が git に入らない)
- テスト: `python -m unittest dev/tests/test_push_helper.py` 6 件通過・`docs/archive` の全ファイルが検査を通る・`studio/archive/` は引き続き無視される
- 未コミット: なし

## 2026-09-30 Claude Code — 新しい場所(C:\dev\youtube-tools)で全部のテスト
- 前提: `git status` は空(22d81e4)。すべてリポジトリ直下から、1本ずつ流した。node は Playwright 同梱の node.exe。e2e は `PYTHONIOENCODING=utf-8` 付き(unit は付けない)
- unit(すべて通過): `ytt_core` 60(skip 1)・`dev` の ui-kit 写し 5・cleanup_legacy_data 9・push_helper 6・eval_asr 4・resolve_pack_contract 27(単独)・
  home 5 ファイル 140・studio 7 ファイル 227(skip 1)・editor 3 ファイル 178(skip 1)・cut2resolve 3 ファイル 291
- node --test(通過): `editor/tests/test_document_save.cjs` 9/9・`studio/tests/test_review.cjs` 18/18
- e2e(すべて通過): home: portal(108 OK)・autorun・window(39)・keymap / studio: analyze・ui 144/144・ui --mounted 157/157 /
  ui-kit styleguide(47)/ editor: proofread_accuracy(38)・proofread_keys(90)・folder_marker_range(54)・eval_set(22)・row_editing(134)・ui_handoff(66)・edit_tabs(76)・
  edit_cut(64)・edit_voices(14)・edit_pack(50)・ui_mounted(41)/ dev: e2e_pipeline・e2e_datadir
- `holo-colors/build.bat`: テスト 17 件通過・dist\HoloColors.zip まで完了(`e2e_holo_colors.py` は本物のキー入力を送るので流していない。`studio/tests/e2e_review.py` は見本サーバーなので流していない)
- 1回目に落ちて流し直しで通ったもの(この PC の不定の落ち。コードの問題ではない): `home/tests/test_launch.py` の `test_post_guards`(ConnectionAbortedError 10053)・
  studio の unit(出力の途中でプロセスごと消えた)・`e2e_proofread_keys`(chromium の "Target crashed" + 4000 行の反応が 65 ms でタイミング FAIL)・`e2e_edit_cut`/`e2e_edit_voices`(Playwright の "Connection closed while reading from the driver")
- 落ちたが直したもの: なし。clone し直し・フォルダの改名(古いパス・無いファイル・CRLF)による失敗は無かった
- 注意(問題ではない): e2e を `PYTHONIOENCODING=utf-8` なしで流すと `e2e_portal`・`e2e_window` は cp932 の UnicodeEncodeError で止まる(editor/AGENTS.md に書いてある既知の条件)。
  `cmd /c build.bat` は Git Bash からだと「認識されない」になる(PowerShell から `cmd /c ".\build.bat < NUL"` なら動く)
- 残った問題: なし。テストが本物の作業データ(%LOCALAPPDATA%\youtube-tools)を書き換えていないことも確認(直近 2 時間の更新なし)
- 未コミット: なし

## 2026-09-30 Claude Code — 段1 開始・1. B-8 ホームの案件の行に「スタジオで開く」
- 段1(`docs/plan/phase1-small-fixes.md`)を始めた。版は実物で確かめて ホーム 0.13.0・編集 0.23.0・スタジオ 0.11.0(計画の 0.12.0/0.21.0 から進んでいる)。版は段の終わりにまとめて上げる
- 変更: `home/portal.html`(案件の行を開いた中の「状態」の行に `.pt-case-studio`)・`home/portal.js`(`caseCard` で `link('スタジオで開く', '/studio/?video=' + encodeURIComponent(c.id))`。`c.gone` のときは出さない)
- 決定・理由: 場所は `/studio/` の直書き(計画の案 (a)。`docHref` と同じ)。取り込みに失敗してスタジオが子プロセスで動いたときは合わない → **B-7(段5)でまとめて見直す候補**(`/api/status` の studio の path・port から作る案 (b))
- テスト: `home/tests/e2e_portal.py` の [A] に「href・新しいタブ・noopener」「開いたスタジオが `Studio.params.video === 'e2eCase0001'` で ③ 確認(`Studio.step === 'review'`)」を足して通過。
  home の unit 140 通過(1・2回目は `test_post_guards`/`test_security_checks` が ConnectionAbortedError で落ち、3回目に通過。この PC の既知の不定の落ち)
- 未コミット: なし

## 2026-09-30 Claude Code — 段1 2. 監査01 引き出しを開いたままの Alt+数字・タブの切り替え
- 変更: `editor/app.js` の2か所(計画どおり両方)
  1. タブの Alt+1/2/3 は `.ui-drawer:not([hidden])` のときも止める(ダイアログと同じ扱い。ほかの文書のキーと同じ規則)
  2. `setEditTab` で、隠れるタブ(`[data-edpanel]`)の中の開いている引き出しを `UIKit.drawer.close()` で閉じてから隠し、閉じたときは移った先のタブのボタンへフォーカスを置き直す(戻る・# のリンク・プログラムからの切り替えでも `inert` と幕を残さない)。ui-kit は触っていない
- テスト: `e2e_edit_pack.py` に「開いたまま Alt+1 → 3 パック のまま・引き出しも開いたまま」「開いたまま `location.hash='#tx'` → 引き出しが閉じ、`[inert]`・幕が無く、フォーカスは 1 文字起こし のボタン、ヘッダーのタブが押せる」、
  `e2e_edit_tabs.py` に「⚙ 設定を開いている間は Alt+2 でタブが変わらない」を足した。通過: e2e_edit_pack・e2e_edit_tabs(77)・e2e_ui_mounted(1回目は Playwright の "Connection closed while reading from the driver"、流し直しで通過)
- 未コミット: なし

## 2026-09-30 Claude Code — 段1 3. 監査02+17+18 「声を覚える」の安全
- 変更(`editor/serve.py`): `voice_learn_plan`(覚える行 = 1秒以上・声が混ざっていない・**校正済み**・音のメモ overlap/bgm/unclear が無い。除いた行を理由ごとに数える)・
  `is_generic_speaker_name`/`GENERIC_SPK_NAMES`(ユーザー決定の一覧 + `話者A`・`Speaker 1`・英字1文字・数字だけ。NFKC・小文字・空白を寄せる)・
  `GET /api/voices/preview`(読むだけ。人・行・秒・exists/old・refused(generic/no_rows)・skipped・evalSet)・
  `validate_voice_learn`(評価用 400 `eval_set`・`names` が無い古い形 400・既にある名前が `confirmSame` に無ければ 409 `confirm_same` + names)・
  `run_voice_learn`(読み直した文書で評価用を断り、`spec["names"]` との積だけ覚える。待っている間にほかで同じ名前を覚えたら足さずに注意)・`voices_summary` に `generic`。
  **判別のときの照らし合わせ(`recognize_voices`)は `voice_groups` のまま**(決定どおり。テストで確認)
- 変更(`editor/app.js`・`index.html`): 評価用ならボタンを無効にしてヒントに理由(`syncEval` からも描き直す)。押すと preview → `confirmDlg` に人・行・秒・覚えない名前・使わなかった行 →
  既にある名前は1人ずつ「同じ人ですか」→ 確かめた人だけ送る。覚えられる人がいなければ知らせだけ(ジョブを作らない)。覚えている声の一覧で一般的な名前に「一般的な名前です(忘れることをおすすめします)」の札。
  `#cfText` に `white-space:pre-line`(確認の本文を複数行に)
- 決定・理由: 確認は計画どおり今の `confirmDlg`(`#dlgConfirm`)を使った。ui-guidelines の「確認は `UIKit.dialog.confirm`」には、本文が1段落しか入らない(改行が出ない)ので今回は寄せていない
  (ui-kit に複数行の本文を足すのは段5 の見た目の統一か、夜間の見直しの 6 の「確認のダイアログを ui-kit に」でまとめて行う候補)
- テスト: `editor/tests/test_voices.py` を書き直し・足した(17 件: 一般名の判定・校正済みだけ・未校正だけなら 400・評価用は validate/run の両方・preview の数・既にある名前の 409 と confirmSame・確認のあとで名前を付けた人は覚えない・待っている間に覚えられた名前に足さない・一覧の generic・照らし合わせは未校正でも名前が付く)。
  `test_worker.py` の声の通しの確認を新しい形(校正済み・names)に。`e2e_edit_voices.py` に未校正のときの知らせ・確認のダイアログの人・行・秒と「本人」・2回目の「同じ人ですか」(やめる/足す)・API の 409/400・評価用でボタンが無効で理由・API へ直接でも 400 を足した
- 流したテスト(リポジトリ直下): `python -m unittest editor/tests/test_metrics.py editor/tests/test_resolve_export.py editor/tests/test_roster.py` 188 通過(skip 1)・e2e_edit_voices・e2e_eval_set・e2e_ui_mounted 通過
- 未コミット: なし

## 2026-09-30 Claude Code — 段1 4. B-9 文字の欄の上で Shift+右クリックすると行のメニュー
- 変更: `editor/app.js` の行の右クリック(`#segs` の contextmenu)。文字・時刻の欄の上は、普通の右クリックはブラウザ既定のまま・**Shift+右クリックで行のメニュー**。
  日本語の変換中は出さない(contextmenu に isComposing が無いので `compositionstart/end` で覚える)。キーボード(Shift+F10・アプリケーションキー)から開いて位置が 0,0 のときは、欄(か行)の下に出す。
  「分割(カーソル位置)」は今までどおり入力中のカーソル位置で分ける(文言も同じ)。? のキーの一覧の「入力中に使えるキー」に「Shift+右クリック」を足した
- テスト: `e2e_edit_tabs.py` に「文字の欄の普通の右クリックでは出ない」「Shift+右クリックで出て、校正済みが効く」「キーボードから開くと欄の下」「変換中は出ない・終われば出る」を足した。
  通過: e2e_edit_tabs(86。1回目は Playwright の "Connection closed while reading from the driver"、流し直しで通過)・e2e_proofread_accuracy
- 注意: Firefox は Shift+右クリックでページの処理を無視して既定のメニューを出す(対象は Edge/Chrome。README に書く)
- 未コミット: なし

## 2026-09-30 Claude Code — 段1 5. Windows 以外でのテストの飛ばし
- 変更: `home/tests/test_window.py` の `TestFocusWindow` の3件(`test_finds_by_title_and_brings_to_front`・`test_not_found_or_refused`・`test_already_in_front`。`ctypes.WINFUNCTYPE`)と、
  `editor/tests/test_edit.py` の2件(`test_record_pack_and_stale`・`test_fill_doc_into_empty_document`。Windows のパス)に `@unittest.skipUnless(sys.platform == "win32", 理由)`。クラス全体には付けない(通る2件を残す)。`editor/AGENTS.md` の「落ちる」→「飛ばす」
- テスト(PC): home の unit 140 通過(飛ばしなし)・`python -m unittest editor/tests/test_metrics.py editor/tests/test_resolve_export.py` 171 通過(skip は前からの1件だけ)。
  `sys.platform='linux'` にして読み込むと test_window.py は skip 3 で通ることも確かめた(本物の Linux では流していない → **クラウドで流したときに skip 5 で緑になるかを次に確かめる**)
- 未コミット: なし

## 2026-09-30 Claude Code — 段1 追加1: スタジオの知らせが消えない(夜間の見直しの 3-ui-consistency の 1)
- 原因: `studio/core.js` の `Studio.toast(msg, ms, kind)` が ms をそのまま `UIKit.toast` へ渡していた。スタジオの呼び出し(約 40 か所)は昔の「0 = 既定の秒数」で `toast(msg, 0, 'ok'|'err')` と書いているが、
  ui-kit v7 で `ms: 0` が「消えない」に変わったため、成功の知らせも × を押すまで残っていた
- 変更: `Studio.toast` は `ms || undefined` を渡す(0・省略 = ui-kit の既定。成功 2.5 秒・失敗 8 秒)。消えない知らせにしたいときは ms にオブジェクトを渡す(`Studio.toast(msg, { ms: 0, kind: 'err' })`。そのまま UIKit.toast へ。編集の `toast()` と同じ形)。
  スタジオの呼び出しに「意図して消えない」ものは無かった(ui-kit の中の `ms: 0` は ui-kit から直接 `toastFn` を呼んでいるので影響なし)
- テスト: `studio/tests/e2e_ui.py` に「0 → 既定・数字 → その秒数・オブジェクト → そのまま」「`toast(msg, 0, 'ok')` は既定の秒数で消える」「`{ ms: 0 }` は残る」を足した。
  同じファイルの「設定を開いている間は ③ のショートカットが効かない」が、止めた直後の表示の更新(0:22.0 → 0:22.1)で不定に落ちるようになった(時間の流れが変わったため。2回に1回ほど)
  → 表示の一致ではなく「1 秒の移動が無い(差 0.5 秒未満)」を見るように直した。通過: e2e_ui 147/147・e2e_ui --mounted 160/160
- 未コミット: なし

## 2026-09-30 Claude Code — 段1 追加2: カットのタイムラインのフォーカスの枠(夜間の見直しの 3-ui-consistency の 5)
- 原因: `editor/index.html` の `.tt-tl-scroll:focus-visible{box-shadow:inset 0 0 0 2px var(--ring)}`。`--ring` は影の指定そのもの(`0 0 0 3px color-mix(…)`)なので値が不正になり、
  `outline:none` も付いていたため、`tabindex="0"` のタイムライン(`#tlScroll`)にキーボードで来ても何も見えなかった(ui-guidelines 6「フォーカスの輪を消さない」)
- 変更: `.tt-tl-scroll:focus{outline:none}` + `.tt-tl-scroll:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}`(横スクロールの枠の内側に出す。マウスで押したときは出さない)
- テスト: `e2e_edit_cut.py` に「キーボードで来たとき `:focus-visible` で outline 2px solid」を足して通過(直す前の CSS では outline が none で落ちる)。`dev/tests/test_ui_kit_sync.py` 通過(ui-kit の写しの部分は触っていない)
- 未コミット: なし

## 2026-09-30 Claude Code — 段1 の終わり: 版上げ・README・ROADMAP・全体のテスト
- 版: ホーム 0.13.0 → **0.13.1**(B-8)・編集 0.23.0 → **0.24.0**(監査01・02/17/18・B-9・追加2。声を覚える API の形が変わったので minor)・スタジオ 0.11.0 → **0.11.1**(追加1)。cut2resolve・ui-kit は変えていない
  (計画は 0.12.0/0.21.0 からの版上げを書いていたが、実物は段0 までに 0.13.0/0.23.0 だったのでそこから上げた。**段2 の計画の「スタジオ 0.11.0 → 0.11.1」は 0.11.2 に読み替える**)
- 変更: `home/launch.py`・`editor/serve.py`・`editor/app.js`・`studio/serve.py`・`studio/core.js` の版、3つの README.txt の見出しと変更の記録、`editor/AGENTS.md` の先頭の版(0.22.0 のままだった)、
  `docs/ROADMAP.md`(版・段1 の状態 = 済み・「3. 実機で確かめること」に段1 の分・索引)・`docs/plan/phase1-small-fixes.md` の状態の1行。home/README.txt の B-8 は変更の記録に書いた
- 全体のテスト(リポジトリ直下・版上げのあと): unit = ytt_core・home 5 ファイル 140・studio 7 ファイル・editor(metrics/resolve_export/roster)・ui-kit の写し・Resolve パックの契約 すべて通過 /
  e2e = home: portal・window・keymap / studio: e2e_ui 147/147・--mounted 160/160(1回目は落ち、流し直しで通過。1回目のログは上書きで残っていない)/
  editor: edit_tabs・edit_cut・edit_pack・edit_voices・ui_mounted・eval_set・proofread_accuracy・proofread_keys・row_editing・ui_handoff / dev: e2e_pipeline すべて通過。
  本物の作業データ(%LOCALAPPDATA%\youtube-tools)は、直近 4 時間の更新なし(ログを除く)
- 保留: なし(計画の5項目と追加の2件をすべて実装)
- 未完了・次: 実機で確かめること(ROADMAP の 3 の「段1」)。クラウド(Linux)で単体テストが skip 5 で通るかは未確認。起動中の入口は古いコードのままなので「すべて終了」→ start.bat で起動し直す。
  B-7(段5)の候補: 「スタジオで開く」の場所を `/api/status` の studio の path・port から作る(取り込みに失敗して子プロセスで動いたとき用)。
  夜間の見直し(3-ui-consistency)の残り(コントラスト・赤い帯・保存の状態・確認のダイアログを ui-kit に など)は段1 に入れていない
- 未コミット: なし

## 2026-09-30 Claude Code — 段2 開始・1. B-4 動画を選び直す(監査 19)
- 段2(`docs/plan/phase2-data-safety.md`)を始めた。版は実物で確かめて ホーム 0.13.1・編集 0.24.0・スタジオ 0.11.1(段1 のあと)。版は段の終わりにまとめて上げる。
  入口の2項目(B-6・14)はサブエージェント(Opus。入口は影響が広い部品のため)に `home/` だけを任せて並行で進めている(WORKLOG はまとめ役が書く)
- 変更(`editor/serve.py`): `POST /api/relink/check`(書き込まない。名前・長さ・fps・元の長さとの差・`mismatch`・同じ動画を使う別の文書・動画の終わりより後ろの行・注意)・
  `POST /api/relink`(`_save_lock` の中で baseUpdatedAt の 409・その文書のジョブ中の 409・長さの差で `acceptDiff` が無ければ 409 `duration_mismatch`。
  控え = `.bak/<id>.pre-relink.json`・`.bak/<id>.edit.pre-relink.json`・`hist_snapshot(force)`。書き換えるのは sourcePath・sourceName・updatedAt・`relinks`(最新 10 件)だけ。edit.json は書き換えない)。
  パスの検査 `relink_path`: ネットワーク(UNC と、Windows のネットワークドライブ = `GetDriveTypeW`)はファイルに触る前に断る → realpath のあとでもう一度 ネットワーク・「:」(代替ストリーム)・拡張子・`DATA_DIR` の中。
  fps・長さは `resolve_export.edit_draft(rows=False)`(カットのタブと同じ測り方)。音声だけのファイルは ffmpeg の長さで、注意を出して付け替えは許す
- 変更(画面): `cut.js` の `state()` に `offCode`・`loaded`・`docId`、`#cutOff` を文 + ボタン(「動画を選び直す」= source_missing のとき・「もう一度読み込む」= 3 で使う)に。
  `app.js` の `renderPlayerMsg`(再生の失敗: 見つからない → 元のパス + ボタン / network_path → その理由 / それ以外 → 「この形式は再生できません(mkv など)」。カットの読み込みが終わるまでは短い文)・
  `#relinkDlg`(元のパスとコピー・新しいパス・確かめる → 結果・長さが違えばチェックするまで押せない・パスを変えたら確かめ直し・付け替える前に saveDoc と CUT.flush・後は openDoc で読み直し)・
  履歴の一覧の「動画なし」の行の ⋮ に「動画を選び直す」(開いてからダイアログ)
- 決定・理由: 断る作業データは**このツールの `DATA_DIR` だけ**(計画どおり)。全体の作業データ(`%LOCALAPPDATA%\youtube-tools`)まで断ると、スタジオの既定の書き出し先 `studio\exports` の切り抜きを選べなくなるため。
  同じパスへの付け替えは 400 `same_path`。`relinks` は文書の中だけ(`docs/spec/pipeline.md` の受け渡しの形には出ないので書き足していない)
- テスト: `editor/tests/test_edit.py` に `TestRelinkStore`(書き換える項目・控え3つ・履歴から戻す・記録の上限・409 の3種・same_path・長さの決まり・パスの検査。Windows の形は skipUnless nt)と
  `TestRelinkHttp`(本物の動画で確かめる → 付け替え → パック済みが「作り直し」・カットのタブが使える・/media が 200・古い updatedAt の 409・履歴から元のパス / 長さの違いは同意で通る / 作業データの中・拡張子・無い・ネットワーク・壊れた mp4 を断る・音声だけは注意)。
  `e2e_edit_tabs.py` に1節(別名で別のフォルダへ移す → 案内とボタン → 一覧の ⋮ → カットのタブのボタン → 短い動画で注意とチェック → 正しい動画で付け替え → カットのタブと再生が使える・行とカットはそのまま)。
  `test_document_save.cjs` の openDoc の置き換えに `renderPlayerMsg` を足した。
  通過: 編集の unit 197(skip 1)・node 9/9・e2e_edit_tabs・e2e_edit_cut(1回目は chromium の Target crashed、流し直しで通過)・e2e_edit_pack・e2e_ui_handoff・e2e_ui_mounted(1回目は ffmpeg が 0xC0000005 で落ち、流し直しで通過)・dev/tests/e2e_pipeline
- 未コミット: なし

## 2026-09-30 Claude Code(サブエージェント。まとめ役が代筆)— 段2 2. B-6 まとめて実行の記録をファイルに
- 変更: `home/autorun.py`(終わった実行を `app\logs\autorun-runs.jsonl` に1行ずつ。1行 = `Run.public()` + `v: 1`。書くのは `_loop` の finally・順番待ちの中止・入口の終了の3か所だけ。
  `Run.logged` で二重に書かない。書き込みは `cv` の外の別のロック `_log_lock`。1MB で `.1` に回す(1世代・clientlog.py と同じ形)。書けなくても実行は止めず `log_error` に。
  起動時に末尾 256KB を読む(足りなければ `.1` も)。壊れた行・版の違う行・終わっていない行は飛ばす。`snapshot()` に `past`(配信・文書ごとの最後の結果でメモリに無いもの、最大 50 件)。
  `history(limit, offset)`(新しい順・既定 50・最大 200)。`AutoRunner(log_dir=None)` なら今までどおりメモリだけ)・
  `home/launch.py`(`log_dir=self.sup.logs_dir` を渡す・`GET /api/autorun/history?limit=&offset=`・冒頭の API 一覧)・
  `home/portal.js`・`portal.html`・`portal.css`(案件の行: メモリに無ければ `past` から「前回 …: 失敗 ・ 理由(3日前)」と段の札。単体の文字起こしの行も同じ。
  案件の下に畳んだ `details.ui-disclosure#historyBox`「まとめて実行の記録」。開いたときだけ読む・「もっと見る」で 50 件ずつ)・`home/README.txt` の本文(置き場所・強制終了では残らない)
- 決定・理由: `past` は `_trim` で落ちた分も書いたときに覚える(最大 500 件)。「もっと見る」は offset(開いている間に記録が増えると1件重なることがあるが最小の形として許容。段5 の部品化で見直す)
- テスト: `home/tests/test_autorun.py` に TestRunLog(10 件)・`test_launch.py` に test_autorun_history・`e2e_autorun.py` に ④(入口を起動し直しても `past`・案件の行の前回・記録の3件)。
  単体一式 151 OK・e2e_portal・e2e_autorun 42 OK
- コミット: 274aaf9
- 未コミット: なし

## 2026-09-30 Claude Code(サブエージェント。まとめ役が代筆)— 段2 5. 監査 14 ホームのメモの保存の競合
- 変更: `home/portal.js`(案件ごとに `memoSave[id] = {busy, sent, again, msg}`・1つずつ順に送る・送っている間の押し直しは `again` にして応答のあとで今の下書きを1回だけ送る・
  送った値と今の下書きが同じときだけ下書きを消して「保存しました」、違えば「保存しました(そのあとの入力はまだ保存していません)」・書き込む先は ID で今の行と `casesData` から引く・保存中は「保存中…」と `aria-busy`)
- 決定・理由: 押し直しのときにボタンは押せなくしない(最後の値を保存したい意図を again で受ける)。
  テストは計画の `page.route` ではなく画面の fetch を包んで応答だけを止めた(同期版の page.route は止めている間 Playwright の操作も止まるため)
- テスト: `home/tests/e2e_portal.py` に 2d-3(保存中の書き足し・行の作り直しでも入力が残る・二度押しで最後の値)。e2e_portal 121 OK・e2e_autorun OK・単体一式 151 OK
  (1回目は test_launch の ConnectionAbortedError、2回目は Segmentation fault。3回目で通過。この PC の不定の落ち)
- 注意: サブエージェントのコミットの Co-Authored-By は「Claude Opus 5.5」になっている(システムの指定に従った)
- コミット: 1c97c7e
- 未コミット: なし

## 2026-09-30 Claude Code — 段2 3. 監査 13 カットの読み込み失敗を新規と区別
- 変更: `editor/cut.js` の `load`(`/api/edit` の GET の失敗を `edErr` に取り、404 以外は `setOff('保存済みのカットを読み込めませんでした(理由)', 'edit_load')` にして fps を持たない = 区間を作らない・たたき台にしない。
  動画が無いなど下書きの理由があるときはそちらを出す)・`#cutOff` の「もう一度読み込む」(`#cutRetry`。1 で作った置き場所)・タブを開き直したときも読み直す(`onShown`。load の中からの呼び出しでは読み直さない = 失敗し続けても繰り返さない)。
  off なのでパックのタブも `block()` で止まる。3つの状態 = 未作成(何も言わない)・壊れている(今の知らせ)・読めない(上)
- 注意: 前のコミット(0128127)で `docs/WORKLOG.md` の改行が CRLF 混じりから LF にそろった(autocrlf の正規化。中身は同じ。差分が全行になっている)
- テスト: `e2e_edit_cut.py` に `page.route` で `/api/edit` の GET を 500 → 理由と「もう一度読み込む」・区間が無い・保存済みは rev 1 のまま・パックのタブの `#pkOff` と作れない → タブを開き直すと読み直す → 「もう一度読み込む」で保存済みの2区間。
  通過: e2e_edit_cut・e2e_edit_pack・node test_document_save 9/9
- 未コミット: なし

## 2026-09-30 Claude Code — 段2 4. 監査 06 再読み込みで文書を見失わない
- 変更: `editor/app.js`(`setUrlDoc(id)` = `history.replaceState` で `?doc=<id>` を足す/消す。タブの `#` はそのまま。`openDoc` が成功したら入れる・`closeDoc`(削除)で消す・
  `takeUrlParams` は `?media=`・`?clip=` だけ消して `?doc=` は残す。`?doc=` の文書が一覧に無ければ知らせて URL から消す(開いている文書があればその id に戻す))
- 決定・理由: pushState ではなく replaceState(戻るボタンで文書を行き来させると、未保存の保存・カットの flush と戻る操作がぶつかるため。計画どおり)
- 同時に直したもの(3 の続き。`editor/cut.js`): ① 読み直す(同じ文書の load)の途中に、前の読み込みの音の波形が届くと `findSilence` が fps の無い状態で落ちていた
  ("Cannot read properties of null (reading '0')"。以前から「読み直す」で起こりえた競合で、3 の「タブを開き直すと読み直す」で出やすくなった)→ `loadPeaks` は読み込みの番号(`M.loading`)が変わったらやめる・`findSilence` は fps が無ければ何もしない。
  ② 使えない間(`!ready()`)のタイムラインに、前の文書・読み直す前の区間の `.tt-k` が残っていた → 描くときに空にする
- テスト: `e2e_edit_tabs.py` の B-1 の2件を新しい形に(開いたあとも `?doc=` を残し `?media=` は外す・動画から探して開いた文書の id になる)+ 1節(切り替えで URL が変わる・再読み込みで同じ文書と 2 カット のタブ・消した文書の `?doc=` は知らせて何も開かず URL から消える)。
  `e2e_ui_handoff.py` の ?media= の1件(`?nofs=1&doc=<id>` になる)。`e2e_edit_common.py` に `wait_url_doc`(再読み込みのあと URL の文書が開き終わるのを待つ。`open_doc` の先頭と `e2e_edit_pack.py` の再読み込みのあと。待たないとメニューが途中で閉じてクリックが外れる)。
  `e2e_row_editing.py` の再読み込みは `?doc=` を外してから(計画どおり)。`e2e_edit_cut.py` の 3 の節は「もう一度読み込む」を押すまで失敗させる形に(開いたあとにタブを開き直すと読み直すため、1回だけの失敗では不定になった)。
  通過: e2e_edit_tabs・e2e_edit_cut・e2e_edit_pack・e2e_edit_voices・e2e_ui_mounted・e2e_ui_handoff・e2e_row_editing・e2e_proofread_accuracy・e2e_proofread_keys・e2e_folder_marker_range・e2e_eval_set・node 9/9
  (流し直して通ったもの: proofread_keys の Target crashed・folder_marker_range と edit_cut の "Connection closed while reading from the driver"・ui_mounted の起動直後の落ち)
- 未コミット: `ui-kit/`・`studio/review.js`(6. 監査 11 の途中)

## 2026-09-30 Claude Code — 段2 6. 監査 11 設定の保存の失敗を出す
- 変更(ui-kit v9。`ui-kit/ui-kit.js`・`ui-kit.css`・`README.md` → `python dev/sync_ui_kit.py` で写した): `UIKit.settings.status(state, message, retry, label)`・`statusOf()`。
  `'err'` で ⚙ ボタン(`[data-ui-settings]`)に赤い印(`data-ui-status="err"`)・title と aria-label に理由、設定の引き出しの先頭に `.notice.err.ui-settings-status`「理由 [もう一度/label]」。`''` で消す。
  (計画は「v6 → v7」だったが、実物はすでに v8(keymap)だったので v9 にした。ui-kit.js の先頭の行の版も v6 のままだったので v9 に)
- 変更(編集): `editor/serve.py` に `merge_settings`(`PUT /api/settings {"patch": {キー: 値 | null}}`。最上位のキーだけロックの中で今のファイルに合わせる・null で消す・`SETTINGS_PATCH_KEYS` は変えない・形が違えば 400・大きすぎれば 413。丸ごとの PUT は従来どおり)。
  `editor/app.js`: 保存は「最後に保存した内容(`setSaved`)との差のキーだけ」を1つずつ順に送る(`sendSettings`)。失敗 → `status('err', …, 再送)`・成功で消す・離れるときの keepalive の送信が失敗していたら戻ったとき(`UIKit.life.onReturn`)に送り直す。
  読み込みに失敗 → `S.settingsLoadErr` を立てて「設定を読み込めませんでした… [読み直す]」、読み直すまで保存しない(`putSettingsNow` は投げる・`saveKeymap` も止める = 空の配置で上書きしない)。読み直したら画面の欄を設定から描き直す
- 変更(スタジオ): `studio/review.js` の ③ 確認の設定(節ごとの保存はそのまま)に同じ形(保存の失敗の印と再送・読み込みの失敗で既定値のまま保存しない・戻ったときに送り直す)。`queue.js` はすでに知らせているので変えていない
- 決定・理由: 競合はキー単位の合わせ(計画どおり。rev の 409 にすると設定の画面に「読み直す/上書き」の選択を作ることになるため。同じキーを2つの窓で同時に変えたときだけ後勝ち)
- テスト: `editor/tests/test_backend.py` に TestSettingsMerge(別のキーが残る・null で消す・パックの項目は変えない・形の検査 400・413・断ったら書かない)、`test_edit.py` に HTTP の `test_settings_put_patch`(2つの窓の別々のキーが両方残る)。
  `e2e_edit_tabs.py` に1節(`page.route` で PUT を 500 → ⚙ の印と理由・引き出しの「もう一度」→ 戻して押すと保存でき印が消える・2つの窓で別々の設定が両方残る・GET を 500 → 読み込みの失敗の印・変えても PUT しない・「読み直す」で保存済みの値)。
  `studio/tests/e2e_ui.py` に同じ確認(単独と --mounted)。`home/tests/e2e_keymap.py` の「編集を開き直す」は `goto` のあとに `reload`(06 で URL に `?doc=` が残るので、同じ URL への goto が # だけの移動になり読み直していなかった)
- 注意: 同期版の Playwright の `page.route` は、Python が Playwright を呼んでいる間しか動かない。route を付けたまま `time.sleep` で待つと、画面の要求がそこで止まる(`pg.wait_for_timeout` で待つ)
- 通過: 編集の unit 一式(skip 1)・dev/tests/test_ui_kit_sync・node(編集 9/9・スタジオ 18/18)・studio e2e_ui 154/154・e2e_ui --mounted 167/167・ui-kit e2e_styleguide・home e2e_keymap・e2e_portal・
  編集の e2e 一式(edit_tabs・proofread_accuracy・proofread_keys・folder_marker_range・eval_set・row_editing・ui_handoff・edit_cut・edit_voices・edit_pack・ui_mounted)
- 未コミット: なし(版上げ・README・ROADMAP は次の「段の終わり」のコミット)

## 2026-09-30 Claude Code — 段2 の終わり: 版上げ・README・ROADMAP・計画の状態
- 版: ホーム 0.13.1 → **0.14.0**(B-6 の新しい API・14)・編集 0.24.0 → **0.25.0**(B-4 の新しい API・13・06・11)・スタジオ 0.11.1 → **0.11.2**(11)・ui-kit v8 → **v9**(11 のコミットで済み)。cut2resolve は変えていない
  (計画は 09-29 の版からの例 = 0.13.0/0.22.0/0.11.1/v7 だったので、段1 のあとの実物から上げた)
- 変更: `home/launch.py`・`editor/serve.py`・`editor/app.js`・`studio/serve.py`・`studio/core.js` の版、3つの README.txt の見出しと変更の記録(編集は「■ 動画を選び直す」の使い方も)、
  `editor/AGENTS.md`(先頭の版・動画を選び直す/設定の保存/?doc=/edit_load の説明)、`docs/ROADMAP.md`(版・段2 の状態 = 済み・「3. 実機で確かめること」に段2 の分)、`docs/plan/phase2-data-safety.md` の状態の1行
- 保留: なし(計画の6項目をすべて実装)
- 未完了・次: 実機で確かめること(ROADMAP の 3 の「段2」)。起動中の入口は古いコードのままなので「すべて終了」→ start.bat で起動し直す。版上げのあとの e2e はこのあと1本ずつ流す(下に追記)
- 未コミット: なし

## 2026-09-30 Claude Code — 段2 の版上げのあとの全体のテスト
- unit(すべて通過): home 5 ファイル・studio 7 ファイル(skip 1)・editor 一式(skip 1)・ytt_core(skip 1)・Resolve パックの契約(単独)・cut2resolve 291・ui-kit の写し・push_helper
- e2e(1本ずつ順に。すべて通過・流し直しなし): home: portal・autorun・window・keymap / studio: e2e_ui・e2e_ui --mounted・e2e_analyze / ui-kit styleguide /
  editor: edit_tabs・edit_cut・edit_pack・edit_voices・ui_mounted・ui_handoff・row_editing・proofread_accuracy・proofread_keys・folder_marker_range・eval_set / dev: e2e_pipeline・e2e_datadir
- 注意(問題ではない): e2e_portal の出力に ConnectionAbortedError(10053)の Traceback が3つ出る(画面の移動で閉じた接続をサーバーが書き込み中に知るもの。テストは「すべて OK」・終了コード 0)
- 未コミット: なし

## 2026-09-30 Claude Code — 段7(ホロカラーの色の調べ直し)7-1〜7-7 のコード
- 担当: ホロカラー(`holo-colors/`)・`ytt_core/colors.py`(色の部分)・`docs/design/holo-colors*.md`。段2 の別のエージェントと並行(触るファイルは重ならない)
- 変更:
  - 7-1 `holo-colors/members.json` を version 2 に: 1人に `colors`(`hex`・`label`・`src`・`confidence`)。`hex` は主な色のまま(= `colors[0].hex`)。メンバーの `confidence` は `colors[0]` へ移した。`sources` に `retrieved`。
    形と案の比較は `docs/design/holo-colors.md` の「形(version 2)」。1.2.1 の exe(build 済みの控え)で version 2 の members.json が 86 人とも読めることを確かめた
  - 7-2 `docs/design/holo-colors-research.md`(新規): 出典の順位・確かさの基準・画像を入れない・取れない出典は推測で埋めない・1人の調べ方
  - 7-4 `Core.cs`: `ColorOption`(Hex・Label)・`ColorEntry.Colors`/`OriginalColors`/`MemberId`/`Customized`・`Palette.ReadColors`(hex を先頭へ・壊れた色は飛ばす・colors の無い古い形は1色)。検索は2つ目以降の色コードとラベルでも当たる
  - 7-5 `PaletteView.cs`: 2色以上の札の右下に小さな四角(最大3つ + 「+n」。左半分にはかぶせない)。四角を押すとその色をコピー(`HitTestColor`・`ColorActivated`。押した所と離した所が同じときだけ)。
    ツールチップに全部の色とラベル。`MainForm.cs`: 右クリックに色ごとの「コピー #xxxxxx(ラベル)」(色の見本つき)。`Program.cs`: `Copy(entry, 色の番号)`。キー操作(矢印・Enter)は主な色のまま
  - 7-6 作業データの `member-colors.json`(`{"version":1,"members":{"<メンバー id>":{"colors":[{"hex","label"}]}}}`)。`Store.SetMemberColors`/`ResetMemberColors`/`ApplyMemberColors`(書き込みは WriteAtomic・壊れていれば .corrupt-日時・開けなければ保存を止める・保存の失敗は元に戻す・members.json と同じ色にしたら「元に戻す」と同じ・知らない id は消さずに残す)。
    右クリック「色を直す…」→ `MemberColorsForm`(一覧・上へ(主にする)・下へ・削除(最低1色)・足す・選んだ色を変える・元の色に戻す)。直した札は右上の角に小さな三角の印。`--screenshot` に member-colors.png
  - 7-7 `ytt_core/colors.py`: `load()` が members.json の `colors` と `member-colors.json`(`member_colors_path`。inplace では読まない)を読み、`hex` = 主な色(直した色があればその先頭)。返す項目に `colors`・`custom`。使う側は今までどおり `hex` だけ
- テスト: `holo-colors\build.bat` 21 件(17 → 21: 複数の色・直した色 2 件・札の四角。BundledMembers に version 2 の形の検査)。`ytt_core/tests/test_ytt_core.py` 61 件(直した色・colors の形・同梱の members.json の形)。
  cut2resolve 291 件・`home/tests/test_launch.py` も通過。`e2e_holo_colors.py` に「札の中の小さな四角を押すとその色」を1件(段の最後に流す)
- 決定・理由: 直した色のキーはメンバーの id だけ(卒業でグループが変わっても残る)。四角は札の右下(一覧の人数と並びが変わらない。押しにくい分は右クリックのメニューでも同じことができる)
- 未完了・次: 7-3(全員を Web で調べる)・7-8(README・版 1.3.0・ROADMAP・e2e)
- 未コミット: なし

## 2026-09-30 Claude Code(サブエージェント)— 段3 開始・3-1 左メニューを重ねて開いている間、後ろの文書のキーを止める(監査 04)
- 段3(`docs/plan/phase3-keys-undo.md`)を始めた。版は実物で ホーム 0.14.0・編集 0.25.0・スタジオ 0.11.2・ui-kit v9。段7(ホロカラー)は別のエージェントが同時に進めている(`holo-colors/`・`ytt_core/colors.py` は触らない)。
  計画は 09-29 に GitHub の main から書かれたもので、その後の「気が利く画面へ 段6」(ui-kit v8 の `UIKit.keymap`。GPT-03/04/16)で 03・04・16 の多くは入っていた → 今のコードとの差だけを直す
- 変更(`editor/app.js`): `menuHasKeys` を「(a) 重ねて開いている(isDrawer() && menuOpen())**または** (b) フォーカスがメニューの中」に(以前は (a) かつ (b) = 幕の上や本文にフォーカスがあると漏れ、1600px 以上の並べて出すメニューでも漏れた)。
  Ctrl+Z(元に戻す)と Tab(行の入力欄へ)の keydown にも同じ条件。2 カット は host の `menuHasKeys` をそのまま使う(cut.js は変えていない)。
  並べて出すメニューの履歴から文書を開いたら、フォーカスをメニューの外へ(openDoc。(b) で ↓ が効かなくなるのを避ける)。G・Esc・Alt+1/2/3・? は今どおり
- テスト: `e2e_edit_tabs.py` に 3-1 の節(1440px: G で開いてメニューの中で ↓・S・Space・Ctrl+Z が効かない / フォーカスを外しても効かない / G・Esc で閉じる / 閉じたら ↓ が効く /
  1700px: 並べて出すメニューの中で ↓ が効かない・履歴から開いたらすぐ ↓ が効く / 2 カット: 重ねて開いている間 S・Space が効かない・閉じたら S で分割)。
  `test_document_save.cjs` の openDoc の置き換えに `menuOpen` を足した。
  通過: e2e_edit_tabs・e2e_edit_cut・e2e_row_editing・e2e_ui_handoff・home/tests/e2e_keymap・node 9/9
- 未コミット: なし

## 2026-09-30 Claude Code — 段7 7-3(全員を調べ直した)・7-8(段の終わり)
- 版: ホロカラー 1.2.1 → **1.3.0**(`holo-colors/src/Core.cs` の AppInfo.Version・README の見出しと変更の記録)。members.json は version 2・updated 2026-09-30。ytt_core の変更はツールの版を上げない
- 7-3: 86 人・20 グループすべてに `checked`(2026-09-30)と記録の表(`docs/design/holo-colors-research.md` の「記録」)。取得はサブエージェント(Sonnet。Web から HTML とテキストだけ・画像は取らない・リポジトリは触らない)、
  members.json への反映と記録の表はまとめ役。ホロジュールの枠の色は自分でも数人を取り直して確かめた(#4E7FFC・#F9AFB2・#FF45D5・#F9F1E4・#266AFF)
  - 今日のホロジュールで確かめた 62 人(1人の枠 50・共演の枠 10・FUWAMOCO の2人共用 2)は、**全員が今の主な色と同じ**。出ていない 24 人は保存版(s2)の記録のまま
  - 主な色は変えていない(既定)。2つ目の色: 食い違いの4人(アキ・ローゼンタール・角巻わため・アイラニ・イオフィフティーン・九十九佐命)に公式サイトの画像の色(medium)、FUWAMOCO の2人にホロジュールの2人共用 #F9F1E4(high)
  - 確かさの内訳(色 92 個): high 80・medium 10・low 2。公式の明示(①)は1件も取れなかった(ペンライトの色の案内は X の画像だけ)
  - 採らなかったもの: ペンライトの色(非公式 wiki が公式 X の画像を書き写した名前。④)・公式カードゲームのカードの色(ゲームの分類)・wiki の見出し色(`alt` に wiki の2つ目の色を足した)。出典 s13(ペンライトの表)を足した
  - 名簿: 新しいデビュー・卒業の差なし(公式の一覧 83 件はすべて入っている)。人見クリスは色の資料が見つからず、入れていない(確かめられなかった)
- 7-8: `holo-colors/README.txt`(札の小さな四角・【メンバーの色を直す】・直した色の場所・変更の記録 1.3.0)、`docs/design/holo-colors.md`(作業データ member-colors.json・画面・テスト 21 件・2026-09-29 の決定 = 実装済み)、
  `docs/ROADMAP.md`(先頭の版・段7 = 済み・索引に holo-colors-research.md)、`docs/plan/phase7-holo-colors.md`(状態の1行・ユーザーに聞くこと)。`dist/HoloColors.zip` を作り直した(build.bat)
- テスト: `holo-colors\build.bat` 21 件 OK・`ytt_core/tests/test_ytt_core.py` OK(skip 1)・cut2resolve 291 件 OK・`home/tests/test_launch.py` OK。1.2.1 の exe(控え)で最後の members.json も 86 人読めた。
  **`python holo-colors/tests/e2e_holo_colors.py` は2回とも途中で失敗**(1回目: 検索して Enter のあと「コピーしたら閉じる」が来ない、2回目: 11 件通ったあと「札のクリックで閉じる」が来ない。
  段2 の別のエージェントが同時に画面のテストを流していて前面の窓・入力を取り合った可能性。新しく足した「小さな四角」の確認までは進んでいない)→ ユーザーの PC で、ほかに何も動かしていないときに流し直す
- ユーザーに聞くこと(詳しくは `docs/design/holo-colors-research.md` の「ユーザーに聞くこと」):
  1. 食い違いの4人の主な色を公式サイトの画像の色(またはペンライトの色)に替えるか(今はホロジュールの色が主)
  2. FUWAMOCO の2つ目の色(2人共用 #F9F1E4)を残すか
  3. ペンライトの色を2つ目以降に足すか(公式の画像で確かめてから。色合いが今の主な色と違う人の一覧あり)
  4. 主な色を変えたほうがよい人は見つからなかった・名簿の差なし(確認だけ)
- 実機で確かめること: 1.2.1 の exe のまま新しい members.json に差し替えて起動できる / 1.3.0 で2色以上の人(例: アキ・ローゼンタール)の小さな四角を押して Resolve に Ctrl+V /
  右クリックの色ごとのコピー / 「色を直す…」で主な色を変える → 終了・起動しても残る → members.json を差し替えても残る / 同じ PC の「編集」のパックで配信者の欄にその人 → Text+ の文字が直した主な色(入口を起動し直さなくてよいか) /
  DPI 125%・150% で札の四角が名前やカラーコードに重ならない / e2e_holo_colors.py を流し直す
- 未コミット: なし

## 2026-09-30 Claude Code(サブエージェント)— 段3 3-2 シークの派生キー(+ Shift)を含めた衝突の検査(監査 03)
- 今のコードとの差: 派生キーの検査(登録で断る・読み込みで外す・1秒戻るを変えたら重なる操作を外す)は ui-kit v8 の `UIKit.keymap` で入っていた。残りを直した
- 変更(`ui-kit/ui-kit.js` → `python dev/sync_ui_kit.py` で `editor/`・`studio/` へ): `UIKit.keys.derived(km)`(`{ 'Shift+ArrowLeft': 'seekBack', … }`)を足し、
  `UIKit.keys.playback`(押したとき)と `UIKit.keymap` の重なりの検査が同じこれを使う(以前は2か所に別々の書き方)。
  `UIKit.keymap.BLOCKED` に `<` `>`(2 カット の Shift+, / Shift+. = 選んだ端を10コマ)を足した = 共通の再生キーにできない。
  「1秒戻る」を H にして Shift+H を持つ操作から外したときの文を「「次の行」から Shift+H(H + Shift = 5秒に使う)を外しました」に(以前は「(Shift+H)から H を外しました」と読めた)。
  `ui-kit/README.md` の v9 の節に1行(版は v9 のまま。計画どおり)
- テスト: `e2e_proofread_keys.py` のキー配置の節に「次の行」に Shift+← → 断る / 「次の行」= Shift+H のあと「1秒戻る」= H → 次の行は未設定・Shift+H で5秒戻る / 再生のキーに <(Shift+,)→ 断る。
  通過: e2e_proofread_keys・home/tests/e2e_keymap・e2e_edit_cut・dev/tests/test_ui_kit_sync・node studio 18/18・studio e2e_ui 154/154・--mounted 167/167・ui-kit e2e_styleguide
- 保留: 夜間の見直しの「校正では S = 次の行・Q = 3秒戻る、2 カット では S = 分割・Q/W = 端の選択」(同じキーがタブで別の意味。ガイドライン 2-3「1つのキーは全体で1つの意味」に反する)。
  計画の 03 は派生キーだけを扱っていて、これは含まない。**校正の左手キー(W/S/A/D/Q/E/B/Tab)はユーザー決定で残したもの**なので実装しない。ユーザーの判断が要る。
  選択肢: (1) 今のまま(タブごとに意味が違うことをガイドラインの例外として書く)/ (2) 2 カット のキーを別のキーに(例: 分割 = C・端 = [ ] の Shift など。カットの操作感が変わる)/
  (3) 校正の既定を変える(ユーザー決定に反するので、ユーザーの了承が要る)
- 未コミット: なし

## 2026-09-30 Claude Code(サブエージェント)— 段3 3-3 キーの表示(title・通知・説明)をキー配置から出す(監査 16)
- 今のコードとの差: 行の ▶・校正済み・音の状態の title、削除の「もう一度 Z」、1 文字起こし と 2 カット のキー帯、カットの下の説明 `#cutKeysText`、? の一覧と「基本の流れ」は段6(GPT-16)で配置どおりになっていた。残りを直した
- 変更: `editor/app.js`(行の「＋後に行」の「(N)」・削除の「Z でも消せます」を `titleAddAfter()`・`titleDel()` に = 配置から・未設定なら出さない。キー配置を変えたら行を描き直さず title だけ合わせる(renderKeyUI)。
  静的な HTML のキーは `data-key-title="操作の id"`(title の後ろに「(キー)」)と `data-key="id"` + `data-key-fmt`(中の文字)で renderKeyUI が埋める。
  「移動したら自動で再生」の説明の title・精度の説明の「校正済み」のキーも配置から。削除の通知は未設定のとき「削除のキー」)・
  `editor/index.html`(メニューのボタン3つの「(G)」・カットの再生ボタンの「(Space)」・精度の説明の Shift+Space を上の印に。「I〜O を削る」の文字を `#cutIOLabel` に)・
  `editor/cut.js`(`#cutIOLabel` = 始まり/終わりの印のキーから。外していれば「印の間を削る」)。2 カット の固定のキー(S・[ ]・Q/W・Del・X)は計画どおり今のまま
- 決定・理由: 行の title は計画の「renderDoc をやり直す」ではなく、今の形(title だけ書き換える)のまま足した(4000 行でも描き直しが要らない)。
  読み込みで外れたキーの知らせ(3-2 のリスク)は、キー配置の一覧のその行に「… なので外れています」が出る(v8)ので、別の知らせは足していない
- テスト: `e2e_proofread_keys.py` に 3-3 の節(標準の title / 聞き取れない = H で (H)・未設定で「(」ごと消える / 削除・行の追加を未設定 / メニュー = M でボタンの title / 1コマ進む = U でカットの説明 /
  再生 = P でカットの再生ボタン / 始まりの印を外すと「印の間を削る」/ 校正済みのキーを外すと精度・自動で再生の説明に Shift+Space が出ない)。
  通過: e2e_proofread_keys・e2e_edit_cut・e2e_ui_handoff・e2e_ui_mounted・e2e_row_editing・home/tests/e2e_keymap・node 9/9
- 未コミット: なし

## 2026-09-30 Claude Code(サブエージェント)— スタジオ: 終了のとき実行中の解析・書き出しの子プロセスを止める(夜間の設計レビュー studio の 1・2)
- 担当: `studio/`(段3 の別のエージェントが `editor/`・`ui-kit/` を同時に編集中。触るファイルは重ならない)。`home/` は変えていない(`Mount.stop()` がすでに `finish()` を呼ぶので、`finish()` の中で止めれば入口の「すべて終了」・Ctrl+C・×の流れに乗る)
- 問題: 終了の流れ(入口の「すべて終了」・単独起動の Ctrl+C / SIGTERM / SIGBREAK)が .runtime を消すだけで、実行中の ffmpeg / yt-dlp を止めなかった。
  Windows では子を `CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW` で起動しているので、親が終わっても見えないまま CPU・回線・ディスクを使い続ける
- 変更:
  - `studio/common.py`: `spawn` が起動した子を1か所(`_children`)で覚え、`forget`(見届けたら外す。run_capture・_pump の finally)・`children()`(終わったものは自動で外す)・
    `stop_children(wait)`(子が無ければすぐ戻る。POSIX は SIGTERM → wait 秒 → SIGKILL、Windows は `taskkill /T /F` で孫ごと)。
    `run_short`: すぐ終わる読み取りのコマンド(`media_info` の ffmpeg -i・`stream_urls` の yt-dlp -g・`_ffprobe_json`)も spawn を通す(以前は subprocess.run で、止める手段が無く、中止も効かなかった)
  - `studio/serve.py`: `shutdown_jobs()` = ① 解析の待ちを「中止」で取り除き、実行中の解析・書き出し・チャットの先読みに中止を伝える → ② `stop_children` → ③ ジョブのスレッドが後始末を終えるのを最大5秒待つ。
    中断したものを studio.log に1行(「終了のため中断しました: 解析 N 本(名前)・書き出し N 件・…」)。`finish()` の先頭で呼ぶ(単独起動で .runtime を書けなかったときも main の finally で呼ぶ)
  - `studio/batch.py`: `shutdown()`(closing の印。待ちを始めない・`add` は 503 closing)・`running_now()`。終了で中断した解析は status = cancelled・error「終了のため中断しました」・phase「中断しました(終了)」
  - `studio/exporter.py`: `cancel_all()`(job["interrupted"])。**ついでにレビューの 2**: `run_job` を try/finally で包み、想定外の例外でも「実行中」のまま残さない(`_settle`: 中止を伝えていれば cancelled、そうでなければ error。
    以前は is_busy が真のままになり、次の書き出し・出力先の変更・動画の削除が 409 のまま・まとめて実行が待ち続けた)
  - `studio/analyze.py`: `cancel_all_prefetch()`
- テスト(`studio/tests/test_robustness.py` に 9 件): 子が無いときはすぐ戻る / 孫を起動する python の子を孫ごと止める(印のファイルの書き換えが止まる)/ run_short の後始末・時間切れ /
  書き出しの実行中に shutdown_jobs → 子と孫が止まる・ジョブは cancelled・2本目を始めない・studio.log に記録 / 解析の待ち・実行中が「終了のため中断」/ closing のあとの add は断る / finish は jobs → runtime の順 /
  書き出しのジョブが想定外の例外でも error で終わる。通過: studio の unit 7 ファイル(236 件・skip 1)・home/tests/test_mount.py・studio/tests/e2e_analyze.py
- 決定・理由: Windows では窓なし・別グループの子に穏やかな合図(Ctrl+Break・WM_CLOSE)が届かないので、中止の印(ジョブが次の段階に進まない)を先に立ててから taskkill /T /F で止める
  (書き出しの途中のファイルは次の件で一時の名前にするので、強制終了でも完成品と同じ名前の壊れたファイルは残らない)。待ち行列・書き出しのジョブはメモリだけなので「中断」は studio.log に残す(画面に出すのはレビューの 13 = 保留)
- 保留: 入口が落ちた(強制終了・クラッシュ)ときにも子を消す Windows の Job Object(`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`。ctypes)は設計の判断が要るので入れていない。入口の「すべて終了」の前に `busy()` を見て確認を出す(home 側の画面の変更)も保留
- 未コミット: なし(このあとコミット)

## 2026-09-30 Claude Code(サブエージェント)— 段3 3-4 1 文字起こし の「1コマ」を素材の fps で(監査 15)
- 変更: `editor/cut.js` に `CUT.frameStep(t, n)`(t 秒から n コマ動いた時刻。フレームの境目 + 0.5ms = 2 カット の stepFrames と同じ丸め。fps が分からない・別の文書なら null)。
  `editor/app.js` の共通の再生キーに `fps: () => CUT の fps`(以前は 30 固定)と `onFrame`(frameStep で動かす。止めてから = 2 カット と同じ)。fps が分からない文書・カットの読み込み中は今までどおり 1/30 秒。
  キー操作の一覧に `#keysFpsNote`「動画の fps が分からないため、1コマは約 1/30 秒です」(カットの読み込みが終わって fps が無いとき。`renderFpsNote` = onCutState と一覧を開くとき)
- 決定・理由: 1コマの移動で再生を止めるようにした(以前の 1 文字起こし は再生したまま 1/30 秒ずらしていた。2 カット は止める。計画の「同じ感触」に合わせた)。丸めの式は cut.js の1か所(計画どおり)
- テスト: `e2e_edit_pack.py`(60fps の見本)に 3-4 の節(1 文字起こし で . = 121 コマ目の境目・. 3回と , 1回で 123 コマ目・止まっている・2 カット で続けて . = 124 コマ目)。
  通過: e2e_edit_pack・e2e_edit_cut・e2e_proofread_keys・e2e_edit_tabs・node 9/9
- 未コミット: なし

## 2026-09-30 Claude Code(サブエージェント)— スタジオ: 書き出しを書きかけの名前に書き、仕上がったら置き換える(夜間の設計レビュー studio の 4)
- 問題: 書き出しの mp4 を最終の名前へ直接書いていたので、途中で止まる(終了・PC の不安定・強制終了)と、壊れた・仕上がっていない `NN_…mp4` が完成品と同じ名前で残った(.clip.json も無く、編集側で紐づかない)
- 変更(`studio/exporter.py`):
  - 切り出し(ffmpeg・yt-dlp の区間取得・ストリームの直接指定)・前後10秒の編集用素材・つないだ1本は `<base>.partial.mp4`(同じフォルダ。拡張子は .mp4 のまま = ffmpeg が形式を決められる)に書く。
    音量・ラウドネスの調整も書きかけのまま行い、仕上がったら `promote`(`common.replace_file` = `ytt_core.fsio.replace_retry`)で `<base>.mp4` へ。切り抜き本体 → 編集用素材の順
    (編集用素材の置き換えだけ失敗したら、今までの「編集用素材を作れなかった」と同じ警告にする)。書き出し済みの記録(data.json の on_done)と .clip.json はそのあと = 本当の名前で書く(今までと同じ)
  - yt-dlp の `-o` も `<base>.partial.%(ext)s`(途中の .f399.mp4.part なども、この名前から始まる)。出来上がりは `.partial.mp4` を優先し、`.temp.` を含む名前は拾わない
  - `.edit.json` の media は本当の名前(`final_path`)を書く
  - 失敗・中止: 項目ごとの finally で書きかけ(`.vol.mp4` も)と、編集用素材の `.edit.json` を消す(`drop_partial`・`_drop_edit`)。仕上がったものは消さない。
    編集用素材の途中で中止されたら(終了の流れを含む)、本体も仕上げずに「中止」にする(以前は本体を書き出し済みにして続けていた)
  - 起動時に裏で `clean_partials()`: 出力先の `<動画>/` と `<動画>/作業用/` の `*.partial.*` を消す(スタジオの印 .studio-id のあるフォルダだけ。書き出しが始まっていたらやめる)。消した数は studio.log へ
  - `SUFFIX_ROOM` 28 → 36(`.partial` の8文字分。長い出力先ではラベルが少し短くなる)
  - API・画面の形は変えていない(GET /api/export の path・file は完了した項目だけで、本当の名前)
- テスト(`studio/tests/test_exporter.py` に 5 件): 成功したら書きかけが残らない・.edit.json が本当の名前 / ラウドネスの調整で失敗 → 完成品の名前のファイル・書きかけ・.edit.json が残らず記録もしない(仕上げの間は書きかけの名前)/
  編集用素材の途中で中止 → 何も残らない・cancelled / 名前の関数 / clean_partials はスタジオのフォルダだけ・書き出し中は消さない。
  通過: studio の unit 7 ファイル(241 件・skip 1)・`studio/tests/e2e_ui.py` 154/154(1回目は「読み直す」で設定が入る の1件が NG → 流し直しで全件 OK。書き出しとは関係の無い設定の節)
- 注意: 以前の版で途中まで書かれて最終の名前で残っているファイルは見分けられないので、片付けていない(新しい版から残らない)
- 未コミット: なし(このあとコミット)

## 2026-09-30 Claude Code(サブエージェント)— 段3 3-5 1 文字起こし の「元に戻す」で、新しい方(文字起こし/カット)を戻す(監査 05)
- 変更: `editor/app.js`(`nextOp()` = 操作の通し番号。`S.undo` の中身を `{seq, snap}` に(`pushUndo`・`withUndoReplace`)。`doUndo` は文字起こしの一番上とカットの一番上(`CUT.undoTop()`)を比べて新しい方を1つ戻す。
  カットを戻したら「カットを1つ戻しました(2 カット のタブの区間)」と知らせる。文字起こしを戻したら、すぐ `CUT.docChanged()` で行の「カット済」を今のカットから付け直す(控えの印は古いことがある)。
  処理中(lockJob)はどちらも戻さない。「元に戻す(n)」は2つの合計(カットが変わったとき = onCutMarks・onCutState でも数え直す)。
  「全行を校正済みにしました」の知らせの「元に戻す」は文字起こしの側だけ(`doUndo('tx')`。あとでカットを変えていても、カットは戻さない)。選んだ行をカットしたときの知らせを「「元に戻す」(Ctrl+Z)で戻せます」に)・
  `editor/cut.js`(積むとき(変更・ドラッグ・やり直し)に `seq: h.nextOp()`。`CUT.undoTop()`・`CUT.undo()`・`CUT.undoCount()` を出す)。2 カット のタブの Ctrl+Z はカットだけのまま(ユーザー決定 09-29)
- テスト: `e2e_edit_cut.py` に 3-5 の節(行の「残す」→ 数が1増える → Ctrl+Z でカットが戻る・区間も元どおり・知らせ / 行の終わりを早める → 行をカット → 別の行の終わり の3つを Ctrl+Z・Ctrl+Z・ボタンで新しい順に戻す・数は合計 /
  最後に文書の行の印がカットの中身と合っている)。同じファイルの後ろの `import re`(関数の中)を外した(先頭で読み込み済み。関数の中にあると、前の節の入れ子の関数から re が使えない)。
  通過: e2e_edit_cut・e2e_edit_tabs・e2e_proofread_accuracy・e2e_proofread_keys・e2e_folder_marker_range・e2e_eval_set・e2e_row_editing・node 9/9
- 未コミット: なし

## 2026-09-30 Claude Code(サブエージェント)— スタジオ: チャットのキャッシュに合計の大きさの上限(夜間の設計レビュー studio の 7)
- 問題: `cache/chat` は件数(30)だけで制限していて、実機で 30 件・2.0GB(上限は 30 × 400MB = 12GB)。作業データの置き場(C: の AppData)が気づかないうちに大きくなる
- 変更(`studio/analyze.py`): `prune_chat_cache(limit, keep)` が件数と**合計の大きさ**(既定 1GB。環境変数 `STUDIO_CHAT_CACHE_MB` で変えられる = `STUDIO_SOCKET_TIMEOUT` などと同じ仕組み)の両方に収まるまで、
  最後に使った時刻(mtime。使うたびに utime で新しくしている)が古いものから消す。途中で止まった写し(`*.live_chat.json.tmp`)も消す。
  **消さないもの**: 解析が使っている最中の動画(`use_chat_cache(vid, ±1)`。`run_analyze` の始めと finally)・チャットの先読みが取得中の動画(PREFETCH)・いちばん新しいもの(今入れたもの。1つで上限を超えていても)。
  「使っていないと確かめた直後に使い始めた」を消さないよう、消す処理と使い始めは同じロック。Windows で開いていて消せないものは飛ばして次の機会に。
  消すきっかけ: 今までどおりキャッシュに入れたとき + **起動時に裏で1回**(`serve._clean_leftovers`。減らした量を studio.log へ)。音量・付加情報のキャッシュ(件数だけ)は変えていない
- テスト(`studio/tests/test_robustness.py` に 5 件): 合計で古い順に消す / 件数の上限も効く / 使用中・先読み中・いちばん新しいもの・*.tmp / 環境変数 / 起動時の片付け。
  通過: studio の unit 7 ファイル(246 件・skip 1)・`studio/tests/e2e_analyze.py`。本物の作業データには触っていない(テストは一時フォルダ)
- 保留(設計の判断が要る): レビューの根本の直し = 生の live_chat.json ではなく parse_chat の結果(1秒ごとの配列)を gzip で残す。上限を画面の設定から変える(画面の変更)
- 未コミット: なし(このあとコミット)

## 2026-09-30 Claude Code(サブエージェント)— 段3 の終わり: 版上げ・README・ROADMAP・計画の状態
- 版: 編集 0.25.0 → **0.26.0**(`editor/serve.py`・`app.js`・`README.txt` の見出し)。ui-kit は v9 のまま(`UIKit.keys.derived` と `<` `>` の BLOCKED を足しただけ。計画どおり)。
  スタジオは ui-kit の写しが変わっただけなので上げていない(計画どおり。0.11.2 のまま。スタジオは別の作業(書き出し・終了の後始末)が同じ時間に進んでいた)。ホーム・cut2resolve は変えていない
- 変更: `editor/README.txt` に「■ v0.26.0 の変更」、`editor/AGENTS.md`(先頭の版・「キーと元に戻す」の段落)、`docs/ROADMAP.md`(版・段3 の状態 = 済み・「3. 実機で確かめること」に段3・索引の計画の状態)、
  `docs/plan/phase3-keys-undo.md` の状態の行
- 保留(ユーザーの判断が要る): 校正の S = 次の行・Q = 3秒戻る と、2 カット の S = 分割・Q/W = 端の選択(同じキーがタブで別の意味。ガイドライン 2-3)。校正の左手キーはユーザー決定で残したもの。
  選択肢は 3-2 の記録のとおり((1) 今のまま・ガイドラインに例外として書く / (2) 2 カット のキーを変える / (3) 校正の既定を変える)
- 未完了・次: 実機で確かめること(ROADMAP の 3 の「段3」)。起動中の入口は古いコードのままなので「すべて終了」→ start.bat で起動し直す。版上げのあとの e2e は下に追記
- 未コミット: なし

## 2026-09-30 Claude Code(サブエージェント)— スタジオ 0.12.0(夜間の設計レビュー studio の直し 1〜3 のまとめ)
- 版: スタジオ 0.11.2 → **0.12.0**(`studio/serve.py` の SERVER_VERSION・`studio/core.js` の APP_VERSION・`studio/README.txt` の見出しと変更の記録。README に STUDIO_CHAT_CACHE_MB の1行)
- 済み(上の3件の記録): 1 終了のとき子プロセスを孫ごと止める / 2 書き出しを書きかけの名前に / 3 チャットのキャッシュの合計の上限。ついでにレビューの「書き出しのジョブが想定外の例外で実行中のまま」も直した
- `docs/ROADMAP.md` の「3. 実機で確かめること」にスタジオ 0.12.0 の分を足した。**先頭の版の行(ROADMAP の8行目)と索引の段2 の行の「スタジオ 0.11.2」は、担当の範囲の外なので直していない**(まとめ役が直す)
- テスト(版を上げたあと): studio の unit 7 ファイル 246 件(skip 1)・home/tests/test_mount.py・e2e_analyze・e2e_ui 154/154・e2e_ui --mounted 167/167
  (e2e_ui は --mounted と合わせて3回、1件だけ NG が出て流し直しで全件 OK: 「読み直す」で設定が入る / 画面のエラー「Permissions policy violation: compute-pressure is not allowed」= ブラウザが出す警告で、今回の変更とは関係が無い。どちらも流し直しで出ない)
- 保留(設計の判断が要る。ユーザーかまとめ役が決める):
  - 解析がネットワークを待つ間(音声のダウンロード・チャット待ち 最大 120 分)も jobs.SLOTS を持ったまま(レビューの 3)。直すには run_analyze を「素材の取得 / 解析 / 組み立て」に分け、ffmpeg の区間だけ枠を取る(レビューの 8 と一緒に)。
    枠の持ち方が変わると、まとめて実行・文字起こしとの順番の見え方も変わるので今回は入れていない
  - 入口が強制終了・クラッシュしたときにも子を消す Windows の Job Object(KILL_ON_JOB_CLOSE。ctypes)
  - 入口の「すべて終了」の前に、スタジオが処理中なら確認を出す(home の画面)
  - 終了で中断した解析の待ち・書き出しを、次の起動で画面に出す(レビューの 13。待ち行列をファイルに残す)
  - チャットのキャッシュを生の live_chat.json ではなく集計結果(1秒ごとの配列)で残す(レビューの 7 の根本の直し)
- 未コミット: なし(このあとコミット)

## 2026-09-30 Claude Code(サブエージェント)— 段3 の版上げのあとの全体のテスト
- unit(通過): editor 一式 201(skip 1)・dev/tests/test_ui_kit_sync・node 編集 9/9(スタジオ 18/18 は 3-2 のあと)
- e2e(1本ずつ順に。すべて通過・流し直しなし): editor: edit_tabs・edit_cut・edit_pack・edit_voices・ui_mounted・ui_handoff・row_editing・proofread_accuracy・proofread_keys・folder_marker_range・eval_set /
  home: e2e_keymap / dev: e2e_pipeline。スタジオ e2e_ui 154/154・--mounted 167/167・ui-kit e2e_styleguide は 3-2(ui-kit の最後の変更)のあとに通過
- 注意: 作業中に別のエージェントがスタジオ(`studio/serve.py`・`core.js`・`README.txt` など)を直していた(この記録の時点で未コミットの差分があるのはそのファイルで、段3 の作業ではない)。
  本物の作業データ(%LOCALAPPDATA%\youtube-tools)の 18:36 ごろの更新(prefs の配信者・cut2resolve のパックの記録・dataset)は、起動中の入口からの操作で、テストのものではない(テストは YTT_DATA_DIR=inplace)
- 未コミット: なし(段3 の分)

## 2026-09-30 Claude Code — ホロカラーの e2e(本物のキー入力)を単独で流し直した: 24 件すべて通過
- 段7 のときに2回落ちた `python holo-colors/tests/e2e_holo_colors.py` を、ほかのテストが動いていない状態で流したら 24 件すべて通過(新しく足した「札の小さな四角を押すとその色がコピーされる」も含む)。落ちていたのは、同時に動いていた別のエージェントの画面のテストと前面の窓・入力を取り合ったため
- 未コミット: なし

## 2026-09-30 Claude Code — キーの意味がタブで違う件は現状維持(ユーザー決定)を文書に
- 決定(ユーザー 2026-09-30): 校正(1 文字起こし)の S=次の行・W=前の行・Q=3秒戻る と、2 カットの S=分割・Q/W=端(入り・出し)の選択が同じキーで別の意味になる件は**現状維持**(変えない)。コードは変えていない
- 実物の確認: `editor/app.js` のキー配置の既定(rowNext=s・rowPrev=w・back3=q)と `editor/cut.js`(s=分割・q=入り端・w=出し端)のとおり
- 変えたファイル:
  - `docs/spec/ui-guidelines.md` 2-3: 「例外(2026-09-30 ユーザー決定)」を追記。理由(校正の左手キーは 0.18.2 でユーザー決定で残したもの。タブが違えば見た目も違い混同しにくい)と、今後の注意(校正とカットの両方にあるキーは同じ意味にする。例外は既存の S・W・Q だけ)
  - `docs/plan/phase3-keys-undo.md`: 先頭の「保留」を「決定(2026-09-30): (1) 現状維持。ガイドラインに例外として記載」に
  - `docs/ROADMAP.md`: 段3 の行の「保留1件」を「保留なし(現状維持で決定)」に。5「決めたことの記録」の表に1行
- 未コミット: なし

## 2026-09-30 Claude Code — ホロカラー: 早見表と照らし合わせて候補の色を全員分に追加(ユーザー決定)
- 決定(ユーザー 2026-09-30): 「カラーは迷ったもの全部入れる。全員に複数色あるからしっかり確認」。迷った候補は全部入れる・FUWAMOCO の共用色は残す・ペンライトの色を足す・**主な色(`hex` = `colors[0]`)は変えない**
- 取得: ホロライブ非公式 wiki の早見表(https://seesaawiki.jp/hololivetv/d/%C1%E1%B8%AB%C9%BD#content_1_7 。EUC-JP を curl で HTML だけ)の「公式カラー」3つの表(ホロジュール 80 人・公式サイトの画像 85 人・ブライト衣装 51 人)と、
  別掲の「ペンライト」のページ(メンバー-イベント別 75 人・イベント別の公式画像の色コード)。断られなかった(Wayback は不要)。画像は取っていない
- `holo-colors/members.json`: `colors` に無い色を2つ目以降に全部足した = **85 人・339 色**(medium 125 = 公式サイト画像・濃 76 / 縁 49、low 214 = ペンライト(今)75・ペンライト旧 48・ブライト衣装 メイン 40 / サブ 46・ホロジュール(wiki)5)。
  同じ色 = RGB の各成分の差 8 以下は足さない。ペンライトは色の名前 → Link Your Wish(2022)の公式画像の色コードを名前ごとに当てた(`label` 「ペンライト: 水色」・以前のライブだけの色は「ペンライト旧: …」)。
  足した色が `alt` にあったものは `alt` から外した(140 件)。新しい出典 s14(ブライト衣装)を `sources` に、s13 の説明と取得日を更新。`updated` 2026-09-30(版は 1.3.0 のまま。データだけ)
- 見つからず: **魔乃アロエ**(どの表にも無い。足していない)。表ごとに無い人は research.md に
- 主な色と早見表のホロジュールの欄: 一致 69・不一致 11・欄なし 6。不一致 = FUWAMOCO(2人共用 #F9F1E4。もう入っている)・FLOW GLOW の5人(wiki の値が今日のホロジュールと違う → low で足した)・アソビ★まわり隊！の4人(wiki の欄が公式サイトの「濃い部分」と同じ値)
- 名前の対応: EN・ID はローマ字 → members.json の `en` と完全一致。「友人A」→ 友人A（えーちゃん）。対応が取れなかったのはメンバーではない4行(公式チャンネル・Blue Journey・DEV_IS・ReGLOSS のユニット)だけ
- 文書: `docs/design/holo-colors-research.md` に「早見表(2026-09-30 取得)と照らし合わせ」(取得・足し方の決まり・ペンライトの色の対応表・結果・**全員 86 人の確認の表**)、
  `docs/design/holo-colors.md`・`holo-colors/README.txt` の出典の説明、`docs/plan/phase7-holo-colors.md` の「ユーザーに聞くこと」→「決定(2026-09-30)」
- テスト: `python -m unittest ytt_core/tests/test_ytt_core.py` 61 件 OK(skip 1)・`holo-colors\build.bat` 21 件 OK・`dist\HoloColors.zip` を作り直した(README 込み)
- 注意: 1人の色は最多 9 色(アキ・ローゼンタール)。札の四角は最大3つ + 「+n」なので、4色目以降は右クリックのメニューから。ペンライトの色は名前の目安(ライブごとに実際の色は少し違う)。
  low の色(wiki だけ)は公式の画像で確かめていない。`docs/ROADMAP.md` は担当外のため直していない(段7 の行は「済み」のまま)
- 未コミット: なし(このあとコミット)

## 2026-09-30 Claude Code — 友人からの依頼の受付の設計(実装なし)
- 変更: `docs/design/friend-intake.md`(新規)、`docs/ROADMAP.md`(2 に「別件: 友人からの依頼の受付」・8 の索引に1行)。コードは変えていない
- 決定(ユーザー 2026-09-30): 友人から配信の URL と切り抜いた動画を受け取り、届いたらすぐ自動で文字起こしまで流す。経路はユーザーの Dropbox(有料 2TB)。
  友人の PC には送るだけの C# のプログラム(Dropbox の API・アプリ専用のフォルダだけの鍵)。URL は上位 N 個(依頼ごと 1〜10・既定 3)、動画は文字起こしだけ。
  友人への完了の知らせはしない。PC が止まっていた間の依頼は次の起動で流す。「全部これでよい。問題があれば追加する」
- 理由: ホームのポートを外に開けない(取りに行く形)・友人は費用もアカウントも不要(ファイルリクエスト・API の容量は受け取る側だけに数える)
- 未完了・次: 実装はユーザーの合図のあと(文書の 8 の順番)。仮の上限(1日 5 件・配信 8 時間・動画 20GB)は動かしてから直す
- 未コミット: なし(このあとコミット)

## 2026-09-30 Claude Code(まとめ役 Opus + サブエージェント Opus・Sonnet)— 友人からの依頼の受付を実装(ホーム 0.15.0・request-sender)
- 版: ホーム 0.14.0 → **0.15.0**(`home/launch.py` の VERSION・`home/README.txt` の見出し)。ほかのツールは変えていない
- 変更(まとめ役): `home/intake.py`(新規。見張り・検査・コピー・受付済み\ と 失敗\ への移動・intake-state.json)、`home/autorun.py`(形 request・file、start_request・start_file、記録の kind file)、
  `home/prefs.py`(節 intake)、`home/launch.py`(GET /api/intake・POST /api/intake/scan・起動と終了)、テスト `home/tests/test_intake.py`(新規 18 件)・`test_autorun.py`(+2)・`test_launch.py`(+1)
- 変更(Sonnet): `home/portal.html`・`portal.js`・`portal.css` に「依頼の受付」の節、`home/tests/e2e_intake_ui.py`(新規。API は page.route の偽物)。kind file の実行が「次にやること」・記録で #intake へ
- 変更(Opus): `request-sender/`(新規。友人の送るだけのプログラム。C# 5・WinForms・Dropbox の API。build.bat でテスト 14 件 → dist\RequestSender.zip)、
  `dev/dropbox_auth.py`(PKCE で鍵を作る)・`dev/tests/test_dropbox_auth.py`、`dev/push_helper.py`(request-sender/config.json と Dropbox の鍵の形を止める)・`test_push_helper.py`、`.gitignore`
- 文書: `docs/design/friend-intake.md` の状態 → 実装済み・実機の確認待ち、`AGENTS.md`(テストの表に test_intake・e2e_intake_ui・request-sender の行、担当表)、`docs/ROADMAP.md`(版・別件の状態・3 に実機で確かめること)
- テスト: home の unit 一式(launch 32・mount/cases/window 71・autorun 51・intake 18)、e2e_intake_ui・e2e_portal・e2e_autorun・e2e_window・e2e_keymap すべて OK。
  request-sender\build.bat OK(14 件)、dev の push_helper 7・dropbox_auth 10 OK
- 未完了・次: **本物の Dropbox では一度も試していない**(upload_session/finish の形・incorrect_offset の応答・token の取り直しは記憶の仕様)。実機の通しは ROADMAP の 3。
  送る側では動画の大きさの上限を見ていない(PC 側で断る)。起動中の入口は古いコードなので「すべて終了」→ start.bat
- 注意: 鍵(request-sender\config.json)はコミットしない(.gitignore と push_helper)。漏れたら Dropbox の設定でアプリの接続を切る
- 未コミット: なし(このあとコミット)

## 2026-09-30 Claude Code — ホーム 0.15.1: 依頼の受付が desktop.ini を毎回断っていた
- 実機(ユーザー): 友人のプログラムから送った動画は「受け付けた」(通しで動いた)。ただし見張るフォルダの desktop.ini を「受け付けない種類」として 失敗\ へ移し、
  Windows・Dropbox がすぐまた作るので「断った」が 30 秒ごとに増えた
- 直し: `home/intake.py` の is_os_file(desktop.ini・Thumbs.db・.DS_Store など + Windows の隠し・システム属性)を見ない。前の版で断った記録は読み直すときに消す。
  テスト `test_intake.py` +1(19 件 OK)・`test_launch.py -k intake` OK
- 版: ホーム 0.15.0 → 0.15.1(launch.py・README.txt)
- 未完了・次: ユーザーの Dropbox の 失敗\ に移った desktop.ini は消してよい(AI は消していない)。URL の依頼と 150MB 超の動画は未確認
- 未コミット: なし(このあとコミット)

## 2026-10-01 Claude Code(まとめ役 Opus + サブエージェント Opus)— 依頼の形を友人が選ぶ(ホーム 0.16.0・送るアプリ 1.1.0)
- 決定(ユーザー 2026-10-01): 友人が送るたびに ① 全自動(パックまで作って Dropbox の 出力\ へ)/ ② 軽く確認(文字起こしまで)/ ③ 全部人が行う(解析まで)を選ぶ。
  アプリの既定は ①。① のパックは友人のアプリの「受け取る」で受け取る(鍵に読みの権限を足す)。③ の動画はスタジオで解析まで。テストは簡易でよい
- 変更(まとめ役・コミット 2f16b1a): `home/autorun.py`(形 request_auto・request_manual・file_auto・file_manual、段「Dropbox へ届ける」= パックを zip にして 出力\ へ・止まったら 出力\ に .失敗.txt)、
  `home/intake.py`(JSON の flow。無い・知らない値は ②)、`home/portal.js`(一覧に形)、版 0.16.0、`docs/design/friend-intake.md` の 2-2、テスト +6(unit 75 件・e2e 3本 OK)
- 変更(サブエージェント): `request-sender/`(1.1.0。①②③ の選択・「受け取る」のタブ = /出力/ の一覧とダウンロード・失敗の理由)、`dev/dropbox_auth.py`(権限 3 つ: files.content.write・files.content.read・files.metadata.read)。build.bat 16 件・dev 19 件 OK
- 注意: **1.0.0 の鍵は受け取れない**。Dropbox の Permissions に3つ → dropbox_auth.py → build.bat → zip を渡し直す。実際の Dropbox で未確認: ダウンロードの続きから取る(Range)・権限不足のエラーの形・content_hash
- 注意: サブエージェントが古いフォルダに `C:\Users\you11\Desktop\youtube-test\Sending.cs`(0 バイト・git の外)を誤って作った。消す権限が無く残っている → ユーザーに消してもらう
- 未コミット: なし(このあとコミット)

## 2026-09-30 Claude Code — ホロカラー: 早見表の3色(ホロジュール・公式サイトの濃い/縁)を全員そろえて先頭へ
- ユーザーの指示: 「ホロカラーのカラーは全員三色ある。seesaawiki の早見表(公式カラー)のホロジュールと公式サイト欄のすべてを追加して」
- 調べ: ページ(EUC-JP)を取り直して2つの表(ホロジュール 83 行・公式サイト 85 行)を全部読み、members.json と1人ずつ突き合わせた(EN・ID は英語名で)。
  すでに 82 人は3色とも入っていた。足りなかったのは公式サイトの縁の色の3人(星街すいせい #50E5F9・AZKi #F4348B・癒月ちょこ #FF6E9B)。魔乃アロエは表に無い
- 変更: `holo-colors/members.json`(3色を足し、8人の色の並びを「主な色 → 残りのホロジュール → 公式サイト画像・濃 → 公式サイト画像・縁 → そのほか」に。
  ペンライト・衣装の色が早見表の色より前にあって、札の小さな四角(2つ目から3つ)に早見表の色が出ない人がいた。候補の alt のうち色の一覧に入ったものは消した)、
  `docs/design/holo-colors.md`(決めたことに1項目)
- 主な色(hex = 字幕の色)は誰も変えていない。exe は変わらないので版は据え置き(dist の zip の members.json は新しい)
- テスト: holo-colors\build.bat(21 件)・`python -m unittest ytt_core/tests/test_ytt_core.py`(61 件)OK。画面は --screenshot で確認
- 未コミット: なし(このあとコミット)。`docs/ROADMAP.md` の未コミットの変更は別の作業のもので、触っていない

## 2026-10-01 Claude Code(まとめ役 Opus + サブエージェント Sonnet)— 既定を「カットしない・音量 30%」・受け取ったら消す・裏で動かす(ホーム 0.17.0・編集 0.26.1・送るアプリ 1.2.0)
- 決定(ユーザー 2026-10-01): 全部のパックの既定をカットしない・音量 30% に / 友人が受け取ったら Dropbox から消し、パックは1本ずつ届ける / スタジオ(画面)を開いていなくても使えるよう、裏で起動する bat を自動起動に
- 変更(まとめ役): `home/prefs.py`(autorun.cut の既定 none)・`home/autorun.py`(カットの既定 none・音量の既定 0 LUFS = 30%・① はパックができるごとに _deliver_one)、
  `editor/pack-tab.js`・`ui-kit/ui-kit.js`(音量の既定 0 / 30。写しは sync_ui_kit)、版: 編集 0.26.1・ホーム 0.17.0、
  `start-background.bat`・`home/start_hidden.vbs`(新規。ASCII・CRLF でないと cmd が日本語の rem を読み違えた)、README・設計の文書 2-3・ROADMAP の版
- 変更(Sonnet): `request-sender/`(1.2.0。受け取って確かめたら files/delete_v2・失敗の知らせの「消す」・受け取り済みの表示をやめた)。build 17 件 OK
- ユーザーの PC に置いたもの: スタートアップに「youtube-tools (裏で起動).lnk」(wscript で start_hidden.vbs)。やめるときは shell:startup で消す。
  いまホーム 0.17.0 が裏で動いている(22:31 に起動を確かめた)
- テスト(簡易でよい = ユーザー): home の autorun・intake 75 件 OK(既定に依る4件を直した)・test_ui_kit_sync OK。e2e は流していない
- 注意: ユーザーの編集の設定には packLoudness 0・packVolume 30 がもう保存されていた。ホームの設定に autorun.cut は無かった = 今回から「カットしない」。
  delete_v2・日本語名の削除は実際の Dropbox で未確認
- 未コミット: なし(このあとコミット)

## 2026-09-30 Claude Code — ホロカラー: ペンライトの色を外した
- ユーザーの判断: 「ペンライトの色はいらない」
- 変更: `holo-colors/members.json`(「ペンライト: …」「ペンライト旧: …」の 123 色と出典 s13 を外した。主な色がペンライトの人はいない。86 人のまま)、
  `holo-colors/README.txt`(候補の色の説明・変更の記録)、`docs/design/holo-colors.md`(決めたことに1項目)
- exe は変わらないので版は据え置き(dist の zip の members.json は新しい)。`holo-colors/tests/CoreTests.cs` のペンライトはテストの中の見本のデータなのでそのまま
- テスト: holo-colors\build.bat(21 件)・`python -m unittest ytt_core/tests/test_ytt_core.py`(61 件)OK
- 未コミット: なし(このあとコミット)

## 2026-09-30 Claude Code — ホロカラー 1.3.1: 衣装の色を外した・色の四角を大きく
- ユーザー: 「衣装の色もいらない」「もうちょっと各色大きく」
- 変更: `holo-colors/members.json`(「ブライト衣装・…」の 86 色と出典 s14 を外した。公式サイトの縁の色と同じ値で出典に s14 が並んでいた6人は、色を残して s14 だけ外した。
  主な色は誰も変えていない。2つ目以降の色は 1〜2 つの人がほとんど、FLOW GLOW だけ 3 つ)、
  `holo-colors/src/PaletteView.cs`(札 46 → 56px・最小の幅 148 → 172px・四角 14 → 22px・角丸と「+n」の幅も合わせた。四角は札の右半分に入るだけ、の決まりはそのまま)、
  `holo-colors/tests/CoreTests.cs`(四角のテストの見本の窓を 640 → 760px。「+n」付きで3つ並ぶ幅)、`holo-colors/tests/e2e_holo_colors.py`(先頭の札をクリックする高さ)、
  `holo-colors/src/Core.cs`・README(版・説明・変更の記録)、`docs/design/holo-colors.md`
- 版: ホロカラー 1.3.0 → **1.3.1**
- テスト: holo-colors\build.bat(21 件)・`python -m unittest ytt_core/tests/test_ytt_core.py`(61 件)OK。画面は --screenshot で確認。
  e2e(本物の入力)は流していない(クリックする位置を札の高さに合わせて直しただけ。次に流すときに確かめる)
- 未コミット: なし(このあとコミット)

## 2026-09-30 Claude Code(まとめ役 Opus + サブエージェント Sonnet)— ホロカラー 1.4.0: 画面の見直し(札 = 名前 + 色の帯)・マイワード・お気に入り・最近・並べ替え・メンバーに色を追加
- ユーザー: 「UI の全面的見直し」「色の配置がきもい・1色しかないように見える」「マイカラーに並べ替え」「マイワードも登録したい」「追加した方がいい機能の提案」、
  途中で「お気に入りと最近は元の位置にもそのまま」「それぞれのメンバーにマイカラーを追加 → B に増やす」「+n じゃなくて二段」
- 決定(ユーザー): 案B(札の下段を色の帯に)・マイワードは複数行も・並べ替えはドラッグ + キー・追加機能はお気に入りと最近使ったもの(Resolve の形式・書き出し・字幕の見本は選ばれず)
- 変更(サブエージェント Sonnet。受け渡しの形を先に決めた決まった規則の実装): `holo-colors/src/Core.cs`(ColorEntry.Text/IsWord・Branches の WORD/FAV/RECENT・
  Store.Words と my-words.json・AddWord/UpdateWord/RemoveWord・Remove/Move を2つのグループに・MoveTo・Settings.Favorites/Recent・ToggleFavorite/NoteRecent/Forget/ResolveIds)、
  `holo-colors/tests/WordsTests.cs`(新規 10 件)
- 変更(まとめ役 Opus。見た目の判断・影響の広い画面): `PaletteView.cs`(書き直し: 上段 = 名前・✎・☆/★、下段 = 色の帯(等分・40px 未満なら折り返し・段の本数をそろえる・行の高さをそろえる)、
  ワードの札、ドラッグで並べ替え、★ のクリック)、`MainForm.cs`(お気に入り・最近のグループ・「＋ 追加」のメニュー・Alt + 矢印・右クリックのメニュー)、
  `Dialogs.cs`(EditWordForm)、`Program.cs`(ワードのコピー = CRLF・最近の記録・お気に入り・並べ替え・マイワード・「この人に色を追加…」・撮影に words.png)、
  `tests/CoreTests.cs`(小さな四角のテスト → 帯のテスト PaletteBands。WordsTests を呼ぶ)、`tests/e2e_holo_colors.py`(先頭の札 = 最近使ったもの・帯のクリック)、
  README・`docs/design/holo-colors.md`(v1.4.0 の節)・AGENTS.md(テストの件数)
- 版: ホロカラー 1.3.1 → **1.4.0**
- テスト: build.bat 31 件・`python -m unittest ytt_core/tests/test_ytt_core.py` OK・e2e 24 件(ユーザーの許可を得て流した)。画面は --screenshot に見本の作業データを入れて確認
- 注意: 作業データに my-words.json が増えた。settings.json に favorites・recent が増えた(古い版の exe はその欄を無視して読める)
- 未コミット: なし(このあとコミット)

## 2026-09-30 Claude Code(まとめ役 + サブエージェント Sonnet)— ホロカラー 1.4.1(検索中のドラッグの並べ替え)・文書を今の状態に(ROADMAP・HANDOVER・friend-intake)
- ユーザー: 「気になる点と文書の古い所もこの後の作業の流れで適当にやっといて」(1.4.0 の軽い確認で見つけた1件と、版の食い違い)
- 変更(ホロカラー 1.4.1。まとめ役): 検索で絞り込んだままマイカラー・マイワードをドラッグすると、画面に出ている札の番号を Store のグループ全体の番号として使っていたので、隠れている札の分だけ違う位置に入っていた。
  `PaletteView.ItemMoved` は番号ではなく「落とした先にあった項目」を渡し、`Store.MoveToEntry(e, target)`(新規)がグループの中の番号にしてから `MoveTo`。Alt+矢印(`Move`)は前後1つなので影響なし。
  `holo-colors/src/{Core,PaletteView,Program}.cs`・`tests/CoreTests.cs`(ドラッグの確認を項目名に)・`tests/WordsTests.cs`(MoveToEntry: 落とした先の位置・末尾・同じ項目・別のグループへは動かない)・README(版と変更の記録)・`docs/design/holo-colors.md`
- 変更(文書。サブエージェント Sonnet = 決まった事実で直す作業): `docs/ROADMAP.md`(版の行: 編集 0.26.1・ホロカラー 1.4.1・送るアプリ 1.2.0 / 段7 の行: ペンライト・衣装の色は外した(ユーザー決定)/ 別件「依頼の受付」を 0.17.0・実機で通し確認済みに / 3 に実際の Dropbox で未確認の項目とホロカラー 1.4.1 の確認 / 索引)、
  `docs/design/friend-intake.md`(状態の行を 10-01 に。2-2 の「Dropbox から消さない」は 2-3 と矛盾していたので「消すのは友人のアプリだけ」に)、
  `docs/HANDOVER.md`(10-01 の状態に書き直し: push 済み・版・依頼の受付とホロカラー 1.3.1〜1.4.1 を「終わったこと」に・次にやることの 4・5・決めてもらったこと・再開用の指示文の版と現在地)。
  まとめ役が読み直して、HANDOVER の「`Desktop\youtube-test\Sending.cs` を消してもらう」は実際にはもう無いので外した
- テスト: `holo-colors\build.bat` 31 件 OK(zip も作り直した)・`python -m unittest ytt_core/tests/test_ytt_core.py` 61 件 OK。e2e(本物のキー入力)は流していない(ドラッグは e2e に無く、キー・窓の動きは変えていない)
- 残っている古い所(触っていない): `docs/design/holo-colors-research.md` の「ユーザーに聞くこと」(食い違いの4人の主な色・FUWAMOCO の2つ目の色)は未決のまま。HANDOVER の「次にやること」3(夜間の見直しの「高」の残り)は 09-30 のまま
- 未完了・次: 線 A 段4(`docs/plan/phase4-pack-consistency.md`)。計画の行番号は 09-29 時点なので今のコードで確かめ直してから
- 未コミット: なし(このあと2つに分けてコミット: ホロカラー 1.4.1 / 文書)

## 2026-10-01 Claude Code(まとめ役 Opus + サブエージェント Sonnet 2つ)— 線 A 段4「パックの表示と出力を一致」(編集 0.27.0)
- 計画: `docs/plan/phase4-pack-consistency.md`(4-1〜4-5 すべて。状態の行を「済み」に)。行番号は 09-29 時点から少しずれていたが、対象の関数・要素は同じだった
- 変更(4-1 監査 07。まとめ役): `editor/pack-tab.js` の見積もりに状態 `P.pv`(idle / wait / run / save / err)と `pvErrKey`。鍵 `previewKeyNow()`(区間・行・字幕の1段の文字数)が変わっていて予約も計算も無ければ、
  **描画(renderNow)の1か所で** `schedulePreview()` する(設定を変える所ごとに書くと足し忘れで同じ不具合が戻るため。同じ鍵で失敗したら「もう一度」まで出し直さない)。
  計算中・保存待ち(競合なら案内)・失敗 + 「もう一度」を `#pkPvState`/`#pkPvRetry` に。前の見積もりの注意は薄く残す(`.tt-pk-warn.old`)。`app.js` の `readOpts` が `PACK.changed()` を呼ぶ(⚙ の字幕の文字数)
- 変更(4-2 監査 09): 「粗編集の動画(mp4)」を編集の設定 `packRender` に覚える(`serve.py` の SETTINGS_PATCH_KEYS に追加・`shown()` の読み直しの鍵にも)。要約は覚えている物だけ(出力先を外した)。
  出力先は要約の外の「作る場所」の行(`#pkPlace`)で、毎回動画の隣と分かるように。出力先の欄の説明に「覚えません」
- 変更(4-3 監査 08): 画面の `outputNow(hasRows)` が今の出力の設定を1つ作り、パックを作る API と記録 `POST /api/edit/pack` の `output` の両方に使う。`outputDiff(記録, 今)` で違いを「フレームレート: 30fps → 60fps」の形に。
  前回のパックの札は stale なら「作り直しが要る」、設定が違えば「設定が違う」(黄)。`#pkLastDiff` に違いと「できているファイルは作ったときのまま」。記録が無い(この版より前・まとめて実行)は「記録がありません」。
  サーバー(Sonnet): `serve.py` の `sanitize_pack_output`(決まった鍵・型・長さ。1つでも壊れていれば output なしで記録。古い画面・autorun は送らない)・`editor/tests/test_edit.py` の `test_record_pack_output`(約 35 の不正値)
- 変更(4-4 監査 10): `ZIP_SKIPS`(粗編集の動画・音量の調整・開始タイムコード・タイムラインの開始タイムコード・リール名)。zip の説明を書き換え、選んでいるときは zip のボタンの横に `#pkZipWarn`。
  字幕の無い文書は zip にできない(zip はいつも Text+ あり = `create_package` が例外)ので、ボタンを押せなくして理由を出す。契約テスト(Sonnet): `dev/tests/test_resolve_pack_contract.py` の `ZipSkipsContract` 6 件
  (zip と api/build のパックのファイルが粗編集を除いて同じ・zip に roughcut が無い・タイムコード/リール名を変えても zip の EDL/Lua は変わらない・字幕なしは zip が例外)
- 変更(4-5 監査 12): `resolve_export.edit_preview` の応答に `sampleSpeakers`(`pack.cue_speakers` = 実際のパックと同じ規則。名前か null)。画面は見積もりができたらそれで見本の色を決め、古い間は行の話者から。
  `app.js` に `speakerColorByName(name)`(照らし合わせの1か所。`speakerColor(spId)` もこれを使う)を足して PACK に渡した。2 カット の字幕はもう段2 で話者の色だったので変えていない
- 版: 編集 0.26.1 → **0.27.0**(serve.py・app.js・README の見出しと変更の記録・`editor/AGENTS.md` の先頭の版)。cut2resolve・入口は変えていない(pack.py は読むだけ)
- テスト: `python -m unittest editor/tests/test_metrics.py editor/tests/test_resolve_export.py -q`(185)・`python -m unittest dev/tests/test_resolve_pack_contract.py`(33。単独)・
  `editor/tests/e2e_edit_pack.py`(75 OK。4-1〜4-5 の確認を足した。0.26.1 で既定が 30% になった分の古い確認も直した)・`editor/tests/e2e_ui_mounted.py`(ALL PASSED)。`e2e_edit_cut.py` はこのあと
- 気づき: 4-2 の「予備も入れる」は前の段でもう覚えていた(`packBackup`)。zip には音量の調整も渡らない(計画の一覧に無かったので `ZIP_SKIPS` に足した。zip は元の動画のコピーをそのまま入れる)
- 決定(ユーザー 2026-10-01。夜間の見直しの「高」の残り 3 件): ① 認識ワーカーの待ちに**時限を入れる**(読み取りスレッド + queue.get(timeout))/ ② 作業データの置き場所の求め方を **ytt_core の1か所に**/
  ③ パックの「動画のファイル名に日本語」の注意は **(b) EDL を使わない(予備なし)ときは出さない**。次にこの順で行う(段5 の前)
- 文書: `docs/ROADMAP.md`(版・段4 の行「済み」・3 に段4 の実機の確認)
- 未コミット: なし(このあとコミット)

## 2026-10-01 Claude Code — 認識ワーカーの待ちに時限(夜間の見直し「高」の残り ①。ユーザー決定 10-01)
- 問題: `editor/serve.py` の `WorkerClient._read` が `proc.stdout.readline` で待つだけで、ワーカー(tx_worker.py)がネイティブの部品で黙ると待ちが全部止まり、`ytt_core.jobs.SLOTS` を持ったまま他のツールの重い処理(解析・書き出し)まで塞いだ
- 変更: 標準出力は読み取り専用のスレッド `_reader`(起動ごとに新しい `queue.Queue`。EOF・閉じたら b"" を入れて終わる)が列に入れ、`_read` は `queue.get(timeout=WORKER_SILENCE_TIMEOUT)`(既定 20 分)。
  超えたら強制終了 → `_reap` → そのジョブを `worker_hung` で失敗にし(取り消し中なら中止)、次の要求で起動し直す。落ちたとき(EOF)の扱いは今までどおり。`_drain` の読み捨てにも同じ時限が効く
- 理由(20 分): モデルの初回のダウンロード中は何も届かない時間が長い。誤って止めても失敗の文に「そのままもう一度実行」と書き、ダウンロードは続きから進む。短くするより安全側
- テスト: `editor/tests/test_worker.py` に `test_silent_worker_is_killed_after_timeout`(偽のワーカーを 1 行ごとに 60 秒黙らせ、時限 1.5 秒で失敗・ワーカーが残らない・_busy_rid が戻る・次のジョブで起動し直す)。
  `python -m unittest editor/tests/test_worker.py` 25 件 OK・editor の単体一式(test_metrics・test_resolve_export・test_roster)203 件 OK
- 文書: `editor/AGENTS.md`(ワーカーの項)・`editor/README.txt`(v0.27.0 の変更に1項目。版は 0.27.0 のまま = まだ push していない同じ版)
- 未コミット: なし(このあとコミット)

## 2026-10-01 Claude Code(サブエージェント Sonnet。まとめ役が版上げ)— cut2resolve 0.15.1: 「動画のファイル名に日本語」の注意は EDL を書くときだけ(残り ③。ユーザー決定 (b))
- 問題: 注意が試算(plan_cut の warnings → 「編集」の「これから作るパック」)にも毎回出て、従って動画の名前を変えると文字起こしと動画の紐づけが切れた。EDL がファイル名で元動画と結び付くための案内なので、EDL を書かない Text+ パックには関係ない
- 変更: `cut2resolve/pack.py` の `plan_cut` から `C.name_warnings` を外し、`build_pack` で `"edl" in paths` のときだけ結果の warnings に足す(予備あり・Text+ なしのパック・コマンド)。`cut2resolve/serve.py` の動画を調べる API(inspect)からも外した(画面はもう無い・情報だけ)。
  `name_warnings` 自体は残す(test_cut2resolve が使う)。コマンドの `--dry-run`(describe)には出なくなった(本番の実行では EDL を書いたあとに出る)
- 版: cut2resolve 0.15.0 → **0.15.1**(`cut2resolve_core.py` の VERSION・README の見出しと変更点)
- テスト: `cut2resolve/tests/test_pack.py` に `TestNameWarningOnlyWithEdl` 5 件(日本語名の動画で 試算に無い・Text+ 予備なしに無い・予備ありに1回・EDL が本体のパックに1回・ASCII 名は出ない)。
  `python -m unittest cut2resolve/tests/test_cut2resolve.py cut2resolve/tests/test_pack.py cut2resolve/tests/test_serve.py` 301 件 OK・`python -m unittest dev/tests/test_resolve_pack_contract.py` 33 件 OK(単独)
- 未コミット: なし(このあとコミット)

## 2026-10-01 Claude Code — ② 作業データの置き場所の求め方を ytt_core の1か所に(途中で中断。ユーザー「ここで中断」)
- 状態: **途中(WIP)**。Opus のサブエージェントが `ytt_core/datadir.py` に `ENV_OVERRIDE`(studio = STUDIO_HOME・transcribe = TRANSCRIBE_DATA_DIR)・`register(tool, path)`・`resolve(tool, repo_root, env)`
  (登録済み(env を渡さないとき)→ 環境変数 → tool_dir の順)を足し、`home/cases.py`・`home/launch.py`・`studio/serve.py`・`studio/common.py`・`ytt_core/txindex.py`・`docs/spec/data-location.md`・テストを直したところで止めた。
  `python -m unittest ytt_core/tests/test_ytt_core.py` は 64 件 OK。**home・studio の単体テストと `dev/tests/e2e_datadir.py` は未確認**。`editor/serve.py`(prepare / set_data_dir で `datadir.register("transcribe", …)` を呼ぶ)は**まだ接続していない**
- 再開するとき: 上の未コミットの差分を `git diff` で読み、home(`test_launch`・`test_mount`・`test_cases`・`test_autorun`・`test_window`)と studio の単体テスト → `editor/serve.py` の接続 → `python dev/tests/e2e_datadir.py`・`editor/tests/e2e_ui_mounted.py` → WORKLOG → コミット
- 文書(この中断の前に直した分。コミット済み): `AGENTS.md`(「いま進行中」の行を ROADMAP の 2 への参照に)・`docs/HANDOVER.md`(次は段5・夜間の見直しの「高」3 件の状態・版)
- 未コミット: home/cases.py, home/launch.py, studio/common.py, studio/serve.py, studio/tests/test_robustness.py, ytt_core/datadir.py, ytt_core/tests/test_ytt_core.py, ytt_core/txindex.py, docs/spec/data-location.md(すべて ② の途中)

## 2026-10-01 Claude Code(まとめ役 Opus + サブエージェント Sonnet)— 話す人で話者分離も自動に(編集 0.27.0・送るアプリ 1.3.0)
- 決定(ユーザー 2026-10-01): 友人が人数と名前を入れ、文字起こしのあとの話者分離と名前付けも自動に。「編集」の話者判別の人数に「1人」を足して対処。テストは簡易でよい
- 変更: `editor/serve.py`(/api/diarize の numSpeakers 1 = single_speaker・names = 照らし合わせをその名前だけ + 消去法)・`editor/index.html`(人数に 1人)・版 0.27.0、
  `home/autorun.py`(段「話者分離」。話す人があるときだけ、この実行で文字起こしした文書に)・`home/intake.py`(parse_speakers・一覧に「話す人」)・`home/portal.js`、
  テスト: editor test_voices +2(19 OK)・home autorun/intake +2(77 OK)、`docs/design/friend-intake.md` 2-4
- 版: 編集 0.27.0 は別の作業が先に使っていたので **0.28.0**、ホーム 0.17.0 → **0.18.0**(launch.py の別の作業は push.bat でコミット済みになっていた)
- 送るアプリ 1.3.0(Sonnet): 「話す人」の人数と名前・JSON の speakers。build 18 件 OK
- 未コミット: なし

## 2026-10-01 Claude Code — ② 作業データの置き場所の求め方を ytt_core の1か所に(仕上げ。中断の続き)
- 経緯: 中断したときの未コミットの 9 ファイル(Opus のサブエージェントの分)は、ユーザーの push.bat の「update 2026/10/01 0:12」(9115e19)にそのまま入っていた。今回はその続き
- 変更: `editor/serve.py` の `set_data_dir()` が `datadir.register("transcribe", DATA_DIR)` を呼ぶ(TRANSCRIBE_DATA_DIR のときも prepare のときも通る)。
  `studio_data_path()` は `datadir.resolve("studio", …)`(登録 → STUDIO_HOME → 新しい置き場)で決め、そこに無く登録も環境変数も無いときだけ以前の場所(スタジオのフォルダ)。
  `docs/spec/data-location.md` に「編集」の登録の場所を1行
- 規則(`ytt_core/datadir.py`。9115e19 に入っていた分): `resolve(tool, repo_root, env)` = ① 登録(`register`。env を渡したときは見ない)→ ② ツールごとの環境変数 `ENV_OVERRIDE`(STUDIO_HOME・TRANSCRIBE_DATA_DIR)→ ③ `tool_dir`。
  `locate` は ②③ だけ(自分で決める側 = 入口)。`prepare` は env を渡さないとき決めた場所を登録する。読む側: `home/cases.locations`・`txindex.folder`・`txindex.packs_dir`(`use_packs_dir` は cut2resolve の登録に)
- テスト(すべて通過): `ytt_core/tests/test_ytt_core.py`(64)・home の単体 5 組(159)・studio の単体 7 組(246)・editor の単体一式(205)・`dev/tests/e2e_datadir.py`・`editor/tests/e2e_ui_mounted.py`・`home/tests/e2e_portal.py`
- これで夜間の見直しの「高」の残り 3 件(①②③)はすべて済み。次は線 A 段5(`docs/plan/phase5-consistent-ui.md`)
- 未コミット: なし(このあとコミット)

## 2026-10-01 Claude Code — 線 A の段8 のあとの大きな計画(案)を書いた(`docs/plan/line-a-after-phase8.md`)
- 依頼: ユーザー「A の段8 以降の大きな計画を立てたい」。段5〜6・8 で 09-29 の計画が尽きるので、その先の候補を集めて章と段に並べた(**案。採否・順番はユーザーの決定待ち**)
- 集め方: Haiku のサブエージェント 3 つ(読むだけなので小さいモデル)で並列に、① 設計書の保留・未決・提案のまま、② 計画書(段5・6・8・線 B・USER_INPUT・HANDOVER)の残り、③ コードの「仮・将来」と README の「できないこと」を一覧にし、まとめ役(Opus)が分類した
- 中身: 4 つの章(Ⅰ 運用と土台 / Ⅱ 切り抜きの質 / Ⅲ パックの先 / Ⅳ 画面と周辺)と段9〜15 の案。おすすめ順は 段5 → 6 → 9(運用の安定化)→ 10(コードの整理。線 B 段2 の前)→ 線 B 段1・2 → 13(投稿の準備)→ 11(見どころ検出の精度 = 線 C の土台)→ 12(コラボの別視点)→ 8 → 15。段14(Resolve なしの仕上げ)は要決定。
  「やらない」と決めたもの(9:16・新着の監視など)は蒸し返さず 6 に材料だけ
- 文書: `docs/ROADMAP.md`(2 の表に「9〜15 段8 のあと(案)」の行・8 の索引に1行)
- 触っていない: 段5 の作業途中の未コミット(editor/README.txt・index.html・app.js・e2e_edit_tabs.py、home/README.txt・portal.*・e2e_portal.py、studio/review.css。別のセッションの分。WORKLOG にまだ記録が無い)
- 未コミット: なし(このあと docs の 3 ファイルだけコミット)

## 2026-10-01 Claude Code — 段8 のあとの計画をユーザーが決定(順番・段13/14 はやらない・線 C・9:16 はやらないのまま)
- 決定(ユーザー 2026-10-01): 順番はおすすめどおり(5 → 6 → 9 → 10 → 線 B 段1・2 → 線 C の土台 → 12 → 8 → 15)/ **段13 投稿の準備・段14 Resolve なしの仕上げはやらない** / 見どころ検出の精度は**線 C**として独立 / 9:16 はやらないのまま
- 文書: `docs/plan/line-a-after-phase8.md`(状態を「決定済み」に・表と 8 を決定に)・`docs/ROADMAP.md`(2 の表に段9・10・12・15 と「やらない」の行・順番の1行・線 C の節・5 の決定の記録 2 行・8 の索引)
- 注意: ROADMAP は段5 のセッションが同時に直していた(版・段5 済み・実機の項目)。**私の変更だけを index に入れてコミット**した(HEAD の版に同じ置き換えを当てて `git update-index`。作業ツリーには両方の変更が残っている)。段5 のセッションの差分はそのまま未コミット
- 未コミット: なし(私の分。段5 のセッションの分は別)

## 2026-10-01 Claude Code(まとめ役 Opus + サブエージェント Sonnet 2つ)— 線 A 段5「見せ方をそろえる」(ホーム 0.19.0・スタジオ 0.13.0・編集 0.29.0)
- 計画: `docs/plan/phase5-consistent-ui.md`(状態を「済み」に)。始める前に今のコードで確かめたら、**5-2・5-3(B-7 まとめて実行の部品と 8 つの入口)は「気が利く画面へ 段4b・4c」(09-29)の `UIKit.autorun` で済んでいた**ので、この段では触っていない
- 5-1(B-5。まとめ役): ホームの「単体の文字起こし」を、件数 +「編集の履歴で見る」(`/transcribe/?list=other#tx`)の1行 `#unlinkedHead` と、その下の `details`「選んで、まとめて実行」(検索・選択・実行はそのまま。09-29 決定: 入口は減らさない)に。
  編集の `takeUrlParams` に `?list=other|clip|all|eval`(履歴の種類 `L.kind` を変えて左のメニューの履歴を開く。URL からは消す。doc・media と同時なら文書も開く)。
  次にやることの実行中の文書のリンク(`#doc-<id>`)は、まとまりが残るのでそのまま。`home/portal.{html,js,css}`・`editor/app.js`・`home/tests/e2e_portal.py`(2f)・`editor/tests/e2e_edit_tabs.py`(?list=)・`home/README.txt`
- 5-4(Sonnet): スタジオ ③ のマークの一覧 `#rvList` を「1枚の紙」(`.ui-sheet` と同じ見え方。外枠1つ・行の間は線・左の状態の色は inset の影・選んだ行は outline・開いた行と選んだ行は `--panel-2`)。畳んだ行は 460px 以上で1行。`studio/review.css`
- 5-7(Sonnet): YouTube プレーヤーの準備待ちに時限 `S.ytReadyMs`(20 秒。テストは `Studio.review.setYtReadyMs`)。時限・`new YT.Player` の例外で案内 +「もう一度試す」(`data-act=ytretry`)+「YouTube で開く」+ 手入力の案内。
  遅れて onReady が来たら案内を消して使う(playerToken で古いのは捨てる)。`loadYTApi` は時限を resolve で止め、再試行で前の script を消す。自動の再試行はしない。iframe_api の読み込み失敗の案内にも「もう一度試す」。`studio/review.js`・`studio/tests/e2e_ui.py`(偽の iframe_api で確認)
- 5-5・5-6(Sonnet): 編集 ⚙「動画の大きさ」の選択肢を「音声だけ」に(値は同じ。説明は欄の下と title)。一覧の上の道具は「次の未校正・…・件数」を `.tt-rb-end`(nowrap)に、1100px 以下で kbd を隠す。`editor/index.html`。写真 1440/1024/390 で確認
- 5-8: 版 ホーム 0.18.0 → **0.19.0**・スタジオ 0.12.0 → **0.13.0**・編集 0.28.0 → **0.29.0**(各 serve.py・画面・README・`editor/AGENTS.md`)。ui-kit は v9 のまま(変えていない)。
  `docs/spec/ui-guidelines.md` 4(一覧は1枚の紙)・`.design/ui-overhaul/IMPLEMENTATION.md` 10・`docs/ROADMAP.md`(版・段5 の行・B-5/B-7 の表・3 に段5 の実機の確認)・`docs/HANDOVER.md`(次は段6)
- テスト(すべて通過): home の単体 5 組(159)・editor の単体一式(205)・studio の単体 7 組(246。`test_api.TestBody.test_content_type` が1回だけ落ち、単独で流し直して OK = この PC の不安定さ)・`node --test studio/tests/test_review.cjs`(18)・
  e2e: `studio/tests/e2e_ui.py`(163)と `--mounted`(176)・`home/tests/e2e_portal.py`・`home/tests/e2e_autorun.py`・`editor/tests/e2e_edit_tabs.py`・`editor/tests/e2e_ui_mounted.py`・`dev/tests/e2e_pipeline.py`。
  e2e_portal のログにある `ConnectionAbortedError` の Traceback は、再読み込みで途中で切れた POST に入口が応答しようとしたもの(テストは全部 OK。以前からの雑音)
- 注意: 途中で別のセッション(段8 のあとの計画)が ROADMAP・WORKLOG をコミットしていたが、このセッションの編集は作業ツリーに残っていて食い違いは無い
- 未コミット: なし(このあとコミット)

## 2026-10-01 Claude Code — 線 D(リアルタイム切り抜き)を ROADMAP に追加(ユーザー指示「線 D も追加」)
- 文書: `docs/plan/live-clipping-plan.md`(ユーザーが貼った 09-28 の仮計画をそのまま写し、先頭に状態の行と、14 に今のリポジトリに当てはめる注意(SLOTS・案件の形・段9 に載せる・新着の監視はやらないのまま)を足した)
- `docs/ROADMAP.md`: 2 の先頭を「4つの線」に・線 C の下に線 D の節(形・律速 = P0・線 A との重なり = P3 は studio/ の段と同時にしない・決定済みと未確定)・8 の索引に1行。`docs/plan/line-a-after-phase8.md` の 1 に線 D との関係を1行
- ROADMAP は前と同じく私の変更だけを index に入れてコミット(段5 のセッションの未コミットの差分は作業ツリーに残したまま)
- 未コミット: なし(私の分)

## 2026-10-01 Claude Code(まとめ役 Opus + サブエージェント Sonnet)— 線 A 段6「編集の機能を足す」(編集 0.30.0・cut2resolve 0.16.0)
- 計画: `docs/plan/phase6-edit-features.md`(状態を「済み」に)。ユーザーの指示で始める前に計画を読み直した(順番は 段6 → 段9 → 段10 → 線 B 段1・2 → 線 C → 12 → 8 → 15)。実装で決めた細部は `docs/design/edit-tool-design.md` の 11「段6」
- 6-1(Sonnet。B-1a): `cut2resolve/pack.py` の `row_edge_from` に `padAfter`(0〜ROW_EDGE_MAX。bool・文字・範囲外は ToolError。`padAfter` > `after` なら `after` も上げる。`on:false` なら広げない。無ければ今までどおり 0.2)。
  cut2resolve 0.15.1 → **0.16.0**(設定の形が増えた)。テスト: `test_pack.py`(row_edge_from・決まった余白 0.4/1.0)・`test_serve.py`(spec.rowEdge.padAfter)・契約テスト `RowEdgeContract.test_widening_contract_pad_after`(乱数 75 文書。既定の件は変えない)。`docs/design/edit-tool-design.md` 12 ⑥ の設定の形
- 6-2(B-1b): 3 パック の「詳しい設定」に「行の後の余白(秒)」`#pkPadAfter`(`pack-tab.js` の `savePad`: change の 0.8 秒後に `putSettings`。失敗なら欄も元へ。値は change のときに読む = 待つ間に render が欄を書き戻すため)。
  たたき台のまま(pristine)なら `CUT.redraftPristine()` で「行から」を作り直し、手で直したカットには「効きません」の案内。要約は既定(0.2)と違うときだけ「行の後の余白 0.5秒」。
  2 カット の「行から ▾」は値を出すだけ(`#cutEdgePad`。変える入口は1か所 = guidelines 3)、`saveEdge` は `padAfter` を残す
- 6-3(B-2a): 字幕の段の行を押して選ぶ(`M.sel = {kind:'row'}`)→ 左右のつまみ `.tt-rh`(競合中・処理中は出さない)。ドラッグ・Q / W で端を選んで , .(Shift で 10 コマ)。前後の行を越えない・1フレーム以上。放したら 0.01 秒に丸めて文書に(`applyRowEdge` → `h.rowChanged` = renderDoc + markDirty)
- 6-4(B-2b): 残す行を外へ広げた分が削る区間に入るときだけ `addRange` で区間も足す(縮めても変えない・たたき台のままなら作り直しに任せる・知らせる)。
  1回の操作 = 文書の元に戻す(`pushUndo(seq)`)とカットの元に戻すに同じ番号。2 カット の Ctrl+Z・元に戻すボタンは app.js の `doUndo`(新しい方を戻す)に任せ、カットを戻すときは `undoDocIf(seq)` で同じ番号の文書の控えも戻す
- 6-5(B-2c): 行を選ぶと「再生位置でこの行を分ける」(端から 0.3 秒より内側のときだけ)。dialog `#cutSplitDlg`(読み取り専用の欄でカーソル = 分け目。初期値は時刻の比)→ `app.js` の `splitRowAt`(1 文字起こし の `doSplit` と共用)。
  **dialog の close イベントは遅れて来る**(Playwright で 5 回中 2 回ずれた)ので、Enter・「分ける」で `commitSplit` をその場で呼ぶ形に。キーは足していない
- 6-6(B-2d): 区間を足したときは編集の内容 `save()` を先に、文書は markDirty の 0.7 秒後。文書の競合(`S.conflict`)・処理中の鍵の間はつまみと「分ける」を出さず、カットのタブにも `#cutDocConflict`(1 文字起こし へのボタン)。app.js は競合の変化で `CUT.refresh()`。サーバーの API は変えていない
- 版: 編集 0.29.0 → **0.30.0**(serve.py・app.js・README・`editor/AGENTS.md`)。入口・スタジオ・ui-kit は変えていない
- テスト(すべて通過): cut2resolve 3 組(301)・契約テスト(34。単独)・editor の単体一式・`node --test editor/tests/test_document_save.cjs`・
  e2e `editor/tests/e2e_edit_cut.py`(108 OK。6-2〜6-6 の確認を足した: 行のドラッグ +0.20 秒・区間も広がる・, で縮めても区間は変えない・Ctrl+Z で両方戻る・次の行を越えない・分ける・競合の案内・パックの引き出しの余白 → 行から ▾ の表示と保存)・
  `e2e_edit_pack.py`(6-2: padAfter の保存・要約・手で直したカットの案内)・`e2e_edit_tabs.py`・`e2e_ui_mounted.py`
- 気づき: e2e の「保存を待つ」は `#saveState` の文字ではなく `data-state === 'ok'` で見る(直前の「保存しました」の文字が残る)。`S` は page.evaluate から見えない(app.js の const は別スコープ)
- 文書: `docs/ROADMAP.md`(版・段6 の行「済み」・B-1/B-2 の表・3 に段6 の実機の確認)・`docs/HANDOVER.md`(版)・`docs/design/edit-tool-design.md` 11・`cut2resolve/README.txt`
- 未完了・次: 段9(運用の安定化。`docs/plan/line-a-after-phase8.md` の 5 から細かい計画 `phase9-*.md` を先に作る)。段9 は「決めてもらうこと」(片付けの対象・依頼の受付の上限)がある
- 未コミット: なし(このあとコミット)

## 2026-10-01 Claude Code(まとめ役 Opus + サブエージェント Sonnet)— 動画の再リンクを簡単に(編集 0.31.0)
- 決定(ユーザー 2026-10-01): 「参照…」でファイルを選ぶ + 履歴からまとめて付け替える。対象は「編集」だけ(スタジオは別の段)。
  段2 B-4 の「候補の自動の推測はしない」を、**ユーザーが選んだフォルダの中の同じファイル名**に限って緩めた(付け替える前に1件ずつ長さを確かめ、長さが違うものは既定で選ばない)
- 変更: `ytt_core/pick.py`(新規。PC の標準の窓を別プロセスの tkinter で開いてパスを返す・一度に1つ・10 分で閉じる)、
  `editor/serve.py`(`POST /api/pick`・`/api/relink/missing`・`/api/relink/find`。付け替え自体は既存の `/api/relink` を1件ずつ = 控え・競合・長さの確認は同じ)、
  `editor/app.js`・`index.html`(1件のダイアログに「参照…」・履歴の上の `#txMissing`・`#relinkAllDlg`)・README・AGENTS.md
- テスト: 単体 +21(Sonnet。`test_edit.py` の TestRelinkFind・`test_ytt_core.py` の TestPick)、`e2e_edit_tabs.py` に「まとめて付け替える」の節(/api/pick は応答を差し替え)。
  通した: editor 単体 216 OK・ytt_core 74 OK・home test_mount 26 OK・e2e_edit_tabs・e2e_ui_mounted ALL PASSED。node が PATH に無いので test_document_save.cjs は流していない(保存の処理は触っていない)
- 注意: 本物の「参照…」の窓は自動のテストでは開けない(実機で確かめる)。start.bat が使う Python(py -3 = Python310・miniconda)はどちらも tkinter あり。
  e2e_edit_tabs の前の節(動画を選び直す)が最後に動画を消すので、その文書の波形の 404 が後ろの節に届くことがある(この節の n_err で吸収)
- 未コミット: なし

## 2026-10-01 Claude Code — 評価用のフォルダ(編集 0.32.0)と、評価用データのフォルダの用意
- 依頼: ユーザー「E:\Video\切り抜き動画素材 に評価用のデータを入れるフォルダを作る」→「このフォルダ内のデータは評価用として扱いたい」→「名前を適切にして再リンクする作業を定期的に。全ての行が済みかどうかで名前を変える」
- フォルダ(リポジトリの外。PC の上だけ): `E:\Video\切り抜き動画素材\評価用データ\{1_JP|2_EN|3_ID}\<NN_グループ(デビュー順)>\評価用データNN_<メンバー>\`(70 人。`holo-colors/members.json` の卒業以外。DEV_IS は JP の中・holoAN は 2025-10〜12 デビューなので FLOW GLOW の後)
- 決定(ユーザー 2026-10-01): フォルダの中は**自動で評価用**・**印は外せない**・名前は「**動画のフォルダ名_番号_済|未|未文字起こし**」・済 = **全行が校正済み**・整理は**入口の起動時 + ボタン**(Windows のタスクはやめた: 入口が止まっていると付け替えられない)
- 変更: `editor/serve.py`(評価用のフォルダの節: 設定 `evalDirs`(`SETTINGS_PATCH_KEYS`)・`in_eval_dir`・`eval_organize`(`POST /api/eval-folders/organize`・`GET /api/eval-folders`・起動の5秒後に1回)。
  印を付ける所 = `validate_job`・`sanitize_transcript`・`restore_history`・`_relink_write`(relink_doc の書き込みを関数に分けた。整理と共用)・`GET /api/transcript` の `evalLocked`・保存の応答に `evalSet`)、
  `editor/app.js`・`index.html`(⚙ の「評価用のフォルダ」`#evDirs`・保存・今すぐ整理・`syncEval` でチェックを固定)・README・AGENTS.md。設計と限界: `docs/design/eval-folder.md`
- 作業データの設定: ユーザーの `%LOCALAPPDATA%\youtube-tools\transcribe\settings.json` に `evalDirs` を入れた(入口は止まっていた。控え `settings.json.pre-evaldirs.bak`)
- テスト: `test_edit.py` に TestEvalFolder(6)・`e2e_eval_set.py` に評価用のフォルダの節(⚙ から保存・自動で評価用・整理で改名と付け替え・チェックを外せない)。
  通した: editor 単体 222 OK・e2e_eval_set・e2e_edit_tabs・e2e_ui_mounted・e2e_folder_marker_range ALL PASSED・home test_mount 26 OK・ytt_core 74 OK(別々に。同じ unittest で流すと環境変数が混ざって落ちる = 以前から)。node が無いので test_document_save.cjs は流していない
- 注意: 「元動画の再リンク簡素化」のセッションのコミット(b5c1871)を待ってから editor/ を触った。起動中の入口は古いコードなので、「すべて終了」→ start.bat で起動し直すと効く
- 未コミット: なし(このあとコミット。`.design/friend-transcribe-lite/` は別のセッションのもの)

## 2026-10-01 Claude Code — 評価用の仮置き(編集 0.33.0)
- 依頼: ユーザー「評価用データ\評価用_仮置き に仮置きして作業する。話者を設定し全行校正済みになったら自動で対象フォルダに移動」
- 決定(ユーザー 2026-10-01): 移す先 = **話した時間が最も長いメンバー**(話者の名前とメンバーのフォルダ名が同じ人。いなければ仮置きに残す)・話者の条件 = **全行に話者が付いていればよい**(仮の名前でも)・
  いつ = **整理のとき + ほかの文書へ移ったとき**・仮置きの中の名前は**元のまま**
- 変更: `editor/serve.py`(`EVAL_STAGING`・`_eval_members`・`_eval_ready`・`_eval_next_name`・`_eval_settle_one`・`_eval_staging_pass`(整理の最初の段。移したあと数え直す)・`POST /api/eval-folders/settle`(`eval_settle`)・
  `_rename_sidecars` を別のフォルダへの移動にも対応・`_eval_rename` に記録の理由 `why`)、`editor/app.js`(`openDoc` で前の文書を 1.5 秒後に `evalSettle`・整理の結果に「仮置きから移した / 残した」)、`index.html`(⚙ の説明)、README・AGENTS.md・`docs/design/eval-folder.md` の「仮置き」・ROADMAP の版
- フォルダ: `E:\Video\切り抜き動画素材\評価用データ\評価用_仮置き` を作った(PC の上だけ)
- テスト: `test_edit.py` TestEvalFolder に 3 件(移す・条件を満たすまで残す 3 通り・1件の settle)、`e2e_eval_set.py` に仮置きの節(ほかの文書へ移ると「_02_済」で移る)。
  通した: editor 単体 225 OK・e2e_eval_set・e2e_edit_tabs・e2e_ui_mounted ALL PASSED
- 未コミット: なし(このあとコミット。`.design/friend-transcribe-lite/` は別のセッションのもの)

## 2026-10-01 Claude Code — 段9 9-2 片付けを画面まで(入口 0.20.0)
- 依頼: ユーザー「元動画がどんどんたまっていくから何とかしたい」→ 段9 の 9-2(片付け)を画面まで仕上げる(ユーザー決定)
- 状態を確かめたこと: 9-1「調子」(`home/health.py`・`/api/health`・ホームの節)・9-3 の部品 `home/restart.py`・9-2 の部品 `home/cleanup.py` は、
  別のセッションが作って a5068a3(push.bat)でコミット済みだった(WORKLOG の記録は無かった)。9-2 は部品とテストだけで、入口の API・画面につながっていなかった
- 追加の決定(ユーザー 2026-10-01): ごみ箱フォルダは**動画と同じドライブ**。元動画の条件は「おすすめで」→ 案件が投稿済み/見送り(計画どおり)に加えて **Text+ のパック(動画のコピー入り)を作って 14 日**
  (Text+ でないパックは元動画を参照するので日数では出さない = Resolve で作業中の素材を消さない)
- 変更: `home/cleanup.py`(`PACK_AGE_DAYS`・元動画と一緒に `_edit.mp4`・作業用の途中のファイル = `extra`・`trash_for`(作業データ / 書き出し先\ごみ箱 / <ドライブ>\youtube-tools ごみ箱)・
  `trash-roots.json`・purge はどのごみ箱も・同じ名前は (1))、`home/launch.py`(`GET/POST /api/cleanup`・起動時の purge を裏で・版 0.19.0 → **0.20.0** = 9-1 と 9-2)、
  `home/portal.{html,js,css}`(「詳しく」の「調子」の下に「片付け」: 候補を探す・種類ごとに選ぶ・確認の dialog・移す)、
  `home/README.txt`・`docs/plan/phase9-ops-stability.md` の状態・`docs/ROADMAP.md`(版・段9 の行)・`docs/spec/data-location.md`(ごみ箱フォルダ)
- テスト: `test_cleanup.py` +2(Text+ のパックから 14 日・途中のファイルも一緒に・同じドライブのごみ箱と purge)・`test_launch.py` +1(/api/cleanup)・`e2e_portal.py` に片付けの節。
  通した: home の単体 8 組 199(test_mount の3件は PYTHONIOENCODING=utf-8 のときだけ落ちる以前からの文字コードの件。付けずに 26 OK)・e2e_portal すべて OK(129)。
  途中で CSP(`style-src 'self'`)に HTML の style 属性が引っかかったので CSS のクラスにした
- 実機で確かめること: 入口を起動し直して「詳しく」→「片付け」→「候補を探す」。E: の元動画を移すと `E:\Video\切り抜き動画素材\ごみ箱\<日付>\export\` に入る。14 日後の起動で消える
- 残り: 段9 の 9-3(版の帯から起動し直す。部品 `home/restart.py` はある)・9-4(依頼の受付の運用)・9-5(小さな注意。一部は a5068a3 で入っている)
- 未コミット: なし(このあとコミット。`.design/friend-transcribe-lite/` は別のセッションのもの)

## 2026-10-01 Claude Code — 段9 9-3 版の帯から「起動し直す」(入口 0.20.0・スタジオ 0.13.1・編集 0.33.1)
- 状態を確かめたこと: 部品 `home/restart.py`(+ test_restart)と ui-kit v10 の `UIKit.restart`(帯のボタン・ping で戻りを待つ)は a5068a3 で入っていた。入口の API・`--wait-port`・各ツールの帯が未接続だった
- 変更: `home/launch.py`(画面の共通の API `api/ytt/restart-self` → `restart_self`: `can_restart`(重い処理・まとめて実行・取り込んだツールの busy)で 409 → `spawn_new_launcher(restart_args(同じポート, --only, --no-mount))` → 0.3 秒後に「すべて終了」と同じ後始末。
  起動の引数 `--wait-port`(`wait_port_free` で古い入口がポートを離すまで最大 30 秒)、`editor/app.js`・`studio/core.js`(版が違えば `UIKit.restart.check($('#errBar'), …)`。ui-kit が無い・単体で開いたときは今までの文)。
  版: スタジオ 0.13.0 → **0.13.1**・編集 0.33.0 → **0.33.1**(各 serve.py・画面・README・editor/AGENTS.md)。入口は 0.20.0 のまま(9-1〜9-3)
- テスト: `test_launch.py` に test_restart_self(忙しいと 409・空いていれば --wait-port で起こして後始末)。通した: test_launch + test_restart 49 OK・studio test_api OK・
  studio e2e_ui 154/154・`--mounted` 176/176・editor e2e_ui_mounted ALL PASSED。
  本物の入口でも確かめた(テスト用ポート 18791・一時フォルダの作業データ・--only cut2resolve): restart-self → 古い入口は 0.4 秒で終わり、新しい入口が 2.0 秒で同じポートに戻り、合言葉が新しくなる → 止めた
- 文書: `home/README.txt`・`docs/ROADMAP.md`(版・段9 の行)・`docs/plan/phase9-ops-stability.md` の状態(残り 9-4・9-5)
- 未コミット: なし(このあとコミット。`.design/friend-transcribe-lite/` は別のセッションのもの)

## 2026-10-01 Claude Code — 段9 9-4 依頼の受付の運用・9-5 の確認(段9 は済み。入口 0.20.0)
- 状態を確かめたこと: 9-4 の「上限を画面から」(`home/prefs.py` の `INTAKE_RANGES`・ホームの欄)・②③ の失敗の知らせ(`autorun._deliver_failure` は deliver_dir があれば①②③とも)・
  受け取った動画の片付け(9-2 の intake の候補)は入っていた。9-5 も a5068a3 で入っていた(VFR・AV1/H.265/10bit は cut2resolve の probe → `plan.warnings` → 見積もりの注意・ドロップフレームは欄の下 `#pkSrcTcHint`)
- 足したもの: (1) 見る間隔を設定から(prefs の intake に `interval` 10〜600 秒・既定 30・整数。`Intake._loop` は設定の値で待つ。テストで interval を渡したときはそれ)。ホームの欄 `#intakeInterval`、
  (2) 受付で断った依頼も友人に知らせる(`Intake._notify_rejected`: 友人のアプリの依頼 = 依頼 id が `REQ_ID_RE` に合うものだけ、`出力\<依頼 id>__<題>.失敗.txt`(①の止まったときと同じ形 = アプリの「受け取る」が読む)。一部だけ断ったときも)
- テスト: `test_intake.py` +1(断った依頼の .失敗.txt・手で置いたファイルは置かない)と TestPrefs に interval、`e2e_intake_ui.py` の patch の本文に interval。
  通した: test_intake 22・test_launch / test_autorun / test_cleanup OK・e2e_intake_ui すべて OK・e2e_portal すべて OK
- 文書: `docs/design/friend-intake.md` の 9・`docs/plan/phase9-ops-stability.md`(状態 = 済み)・`docs/ROADMAP.md`(段9 の行 = 済み)・`home/README.txt`
- 次: ROADMAP の順番どおりなら段10(コードの整理。線 B 段2 の前)
- 未コミット: なし(このあとコミット。`.design/friend-transcribe-lite/` は別のセッションのもの)

## 2026-10-01 Claude Code — 段10 コードの整理を始める(担当: editor/ の分割。終わるまでほかの AI は editor/ を触らない)
- 計画: `docs/plan/phase10-code-split.md`(新規)。決定(ユーザー 2026-10-01): 案A(`ed_state.py` に置き場所などの値・役割ごとの `ed_*.py`・serve.py は起動と HTTP の振り分けと再輸出)・app.js も同じ段で serve.py のあと・Python 3.10 に固定して版を requirements に書く
- 線 B 段1 は 09-29 に済んでいた(ROADMAP の「次は段1」が古かったので直した)
- **担当: Claude Code(このセッション)が editor/ の serve.py・app.js・tests を分割中**。動きは変えない・版は上げない。項目ごとにコミットする
- 未コミット: なし(このあと計画書・ROADMAP・WORKLOG をコミット)

## 2026-10-01 Claude Code — 段10-1 editor/serve.py を役割ごとの部品に分けた(動きは同じ・版は上げない)
- 計画: `docs/plan/phase10-code-split.md`(案A)。7,436 行の serve.py → `ed_state` 441・`ed_store` 877・`ed_relink` 706・`ed_media` 171・`ed_jobs` 2,151・`ed_speakers` 801・`ed_learn` 1,199・`ed_misc` 571・`serve` 879 行
- 作り方: 手で移さず、節の見出しで行き先を決め、AST と symtable で各関数が使う大域の名前を調べて、ほかの部品の名前を `ed_xxx.名前` に書き換える道具で分けた(979 か所。`global` 文の中のほかの部品の名前は外して代入を `ed_xxx.名前 = …` に)。
  import のときにほかの部品の名前を使っていた MIXED_FLAG・WEAK_FLAG・NONE_FLAG は ed_state へ。ed_state はほかの部品の読み込みを最後に置く(循環 import で値ができる前に読まれないように)
- serve.py は名前の受付: PEP 562 の `__getattr__`(読む。sys.modules に登録しない読み込み = 契約テストでも働く)+ モジュールのクラスの `__setattr__`・`__delattr__`(書く・消すを持ち主の部品へ。
  mock.patch.object は戻すときに消してから入れ直すので、持ち主は読み込んだ時点の表 `_ED_OWNER` で覚える)。**テストの差し替えは1行も直さずに済んだ**
- 版の正は serve.py の `SERVER_VERSION` のまま(入口 home/launch.py がこの行を読むため)。部品は `ed_state.SERVER_VERSION`(serve.py が読み込みのときに入れる)
- テストの写す一覧: e2e 7 本・test_backend・test_metrics・dev/tests/e2e_pipeline.py に `ed_*.py` を足した(`e2e_edit_common.py` はフォルダごと写すので不要)
- 前後の結果(`python dev/run_editor_suite.py`。同じ): 編集の単体 225 OK・test_mount 26・契約 34・eval_asr 4・ui-kit 5・e2e 12 本(proofread_accuracy 38・proofread_keys 121・folder_marker_range 54・eval_set 27・row_editing 134・ui_handoff 66・edit_tabs 129・edit_cut 108・edit_voices 29・edit_pack 88・ui_mounted 41・e2e_pipeline 24)すべて OK。版の行を戻したあと単体・取り込み・ui_mounted・test_launch・契約をもう一度 OK
- 次: 段10-2 app.js を分ける → 10-3 Python 3.10 の固定と部品の版
- 未コミット: なし(このあとコミット。担当の宣言は段10 が終わるまで続く)

## 2026-10-01 Claude Code — 段10-2 editor/app.js を役割ごとのファイルに分けた(動きは同じ・版は上げない)
- app.js(3,357 行)の関数の定義(トップレベルの function 203 個)を、区切りの見出しごとに `app-core.js`(343)・`app-jobs.js`(370)・`app-list.js`(222)・`app-learn.js`(260)・`app-rows.js`(639)・`app-tools.js`(660)へ。
  状態(S・V など)・定数・ボタンの配線・起動は app.js(1,247 行)に**元の順番のまま**残した(関数は app.js より先に読むので、1ファイルのときと同じくどこからでも呼べる。読む順番は index.html の1か所)
- app.js の包み `(() => { … })();` を外した(関数・状態をほかのファイルから見えるように = トップレベルの const/let は同じ画面のスクリプトで共有される)。
  トップレベルの名前 402 個をブラウザの window の名前と比べてぶつからないことを確かめた。cut.js・pack-tab.js・ui-kit.js は包みのまま(外に出すのは EditCut・EditPack・UIKit だけ)
- サーバーの静的配信 `ed_state.PAGE_JS` に app-*.js、テストの写す一覧に `app-*.js`(ed_*.py と同じ形)
- `editor/tests/test_document_save.cjs`: index.html の読む順番でファイルをつなげ、関数を名前で取り出す形に(目印での切り出しは分けると壊れるため)。各ファイルを別々に構文の確認。
  node は PC に無かったが **Playwright に入っている node(v24)で流せる**ことが分かった → `dev/run_editor_suite.py` が使う。
  流してみたら1件落ちていた(編集 0.33.0 で openDoc に入れた「仮置きの確認」の予約が残るのを、テストが「予約なし」で見ていた)→ 期待を「その予約だけが1つ残る」に直した
- 前後の結果(同じ): 編集の単体 225・test_mount 26・契約 34・eval_asr 4・ui-kit 5・node 9・e2e 12 本(項目数も 10-1 と同じ)・home の e2e_portal・e2e_keymap すべて OK
- 次: 段10-3 Python 3.10 の固定と部品の版
- 未コミット: なし(このあとコミット)

## 2026-10-01 Claude Code — 段10-3 Python 3.10 の固定と部品の版 → 段10 は済み(担当の宣言を終える)
- `setup/requirements.txt` に今この PC の Python 3.10 で動いている版(faster-whisper 1.2.1・ctranslate2 4.8.2・onnxruntime 1.23.2・numpy 2.2.6)、話者判別は新しい `requirements-diarize.txt`(sherpa-onnx 1.13.8・numpy 2.2.6。install-diarize.bat が読む)、
  テスト用は新しい `requirements-dev.txt`(playwright 1.63.0)。`pip install --dry-run` で、今入っている版とまったく同じ(入れ直しが起きない)ことを確かめた
- **requirements は英数字だけ**: この PC の pip 22.2 は requirements を Windows の文字コード(cp932)で読むので、日本語のコメントがあると UnicodeDecodeError で落ちる(最初に日本語で書いて気づいた)
- start.bat・setup/install.bat・install-diarize.bat・install-gpu.bat・home/start_hidden.vbs: `py -3.10` → `py -3` → `python` の順に選ぶ(.bat・.vbs は ASCII のまま)
- 3.10 で単体テストを流した: 編集の単体 225・test_mount 26・test_launch / test_restart / test_cleanup / test_intake・eval_asr・契約 すべて OK(e2e は playwright が 3.12 にしか無いので 3.12 のまま)
- 文書: README.txt(準備の 1 を Python 3.10 に)・AGENTS.md(動作環境の Python の段落)・editor/AGENTS.md(app-*.js の決まり)・`docs/plan/phase10-code-split.md`(状態 = 済み)・ROADMAP(段10 = 済み)
- **段10 は済み。担当の宣言(editor/ の分割)はここで終わり**。次は ROADMAP の順番どおり線 B 段2(エンジンの差し替え)。分けたので、認識の変更は主に `editor/ed_jobs.py` に閉じる
- 未コミット: なし(このあとコミット。`.design/friend-transcribe-lite/` は別のセッションのもの)

## 2026-10-02 Claude Code — 友人用 文字起こし簡易版(lite)を始める(担当の宣言)
- 担当: 友人用 文字起こし簡易版(`editor/lite*`・`editor/ed_lite.py`・`lite/`・`ytt_core/evaldata.py`・`dev/eval_import.py`、cut2resolve の Text+ の型 `lite`)は Claude Code(PC)
- 設計の正本: `.design/friend-transcribe-lite/DESIGN_BRIEF.md`(ユーザーの Downloads から写した)。計画: `docs/plan/friend-lite-plan.md`(段 L1〜L6)
- 段0 の残り(旧フォルダの改名・AI の作業フォルダの向け直し)は実装に関係しないので並行(ユーザー「実装して」)
- 未コミット: なし(このあとコミット)

## 2026-10-02 Claude Code(まとめ役 Opus + サブエージェント Sonnet・Opus)— 友人用 文字起こし簡易版 L1〜L6(編集 0.34.0・ホーム 0.21.0・cut2resolve 0.17.0)
- 計画 `docs/plan/friend-lite-plan.md`(状態 = 実装済み・実機の確認待ち)・設計 `.design/friend-transcribe-lite/DESIGN_BRIEF.md`・見直し `.design/friend-transcribe-lite/DESIGN_REVIEW.md`
- 形: サーバーは「編集」をそのまま使い、友人用は別の画面(`editor/lite.html`・`lite.js`)。共通コア = ed_jobs(文字起こし・字幕分割)・cut2resolve の pack(Text+)・新しい `ytt_core/evaldata.py`(評価データの形式・記号・パスの除去・zip の検証)
- L1 共通コア: `ytt_core/evaldata.py`(+ `ytt_core/tests/test_evaldata.py`)・cut2resolve 0.17.0 の字幕の型 `lite`(MS ゴシック・大きさ 0.08 は仮・要素5 を無効)と字幕ごとのふちの色(`build_pack(textplus_style, speaker_outlines)`。Sonnet)・
  editor の生出力 `<id>.asr.json`(`capture_raw`。単語の確信度はワーカーの `probability` → `seg_to_dict` の `wordProbs`。words の3つ組は変えない)・`TRANSCRIBE_CUDA_COMPUTE`・話者の `outline`
- L2 書き出し: `editor/ed_lite.py`(`/api/lite/state|settings|upload|probe|start|ops|export|open`)・`lite-colors.json`。書き出し = カットなしのパック(記号を除いた字幕・空の行は入れない)+ 送る用 zip(audio.flac 16kHz モノラル・asr_raw・final・edits.jsonl・meta。絶対パスを除いて find_abs_paths で確かめ、作ったあと check_zip で自分でも確かめる)。重い処理は SLOTS を通す
- L3 画面: 一本道(読み込み → 文字起こし → 校正 → 書き出し)・続きから・Enter で確認して次へ・数字で話者・I/O・Z/X/C/V・時刻は前後の行と重ならない・取り消し/やり直し・作業の記録(確定の前に再生したか)。`editor/tests/e2e_lite.py`(35 項目)
- L4 起動: `lite/start.bat`(ASCII・uv・Python 3.10。**python の行は `& exit /b`** = 更新でこのファイルが書き換わっても続きを読まない)・`lite/lite_start.py`(更新 → 部品(GPU があれば cuBLAS/cuDNN)→ ffmpeg(無ければ winget を聞く)→ 入口)・
  `lite/lite_update.py`(取得元は `sirloin2983/youtube-tools1` の main に固定。git は origin が同じで変更が無いときだけ ff。zip は API で調べたコミットの zip だけを取り、名前を検証・PROTECTED は上書きしない。消えたファイルは消さない)・
  入口の `--open-path` と `--app-window`(appwindow の `force_mode` = 設定に保存しない)・`.gitattributes`(*.bat を CRLF で取り出す)・`.gitignore`(lite/.venv・送る用ファイル・eval-intake)・`setup/requirements-lite*.txt`
- L5 取り込みチェック(Opus): `dev/eval_import.py`(届いた zip を置き場所へ写して sha256 → check_zip → 展開 → 形式・作業ID・絶対パスの検証 → judge → check.json・index.jsonl。置き場所は `%LOCALAPPDATA%\youtube-tools\eval-intake`・リポジトリと git の作業フォルダの中は断る・routing.json の noTrain)。指摘を受けて evaldata の judge を形の違う中身に強くした
- L6: /frontend-design(1枚の面・映像の上の字幕の見本・主のボタンは次の一手だけ)→ /baseline-ui(100dvh・transform・tabular-nums・トークン・z-index・確認・空のとき)→ /design-review(375px のはみ出し・行の並び・コントラスト・ブリーフの軽い知らせ・ルールを畳む)
- テスト: editor の単体 238・test_lite 13・evaldata 14・eval_import 25・lite の起動 14・cut2resolve 310・契約 34・home の launch/window 70・test_mount 26・ui-kit の写し・e2e 一式(`dev/run_editor_suite.py` に e2e_lite を足した。e2e_eval_set だけ一式の中で時間切れ → 単独で通る = 以前からの不安定さ)
- 気づき: `PYTHONIOENCODING=utf-8` を付けて home/tests/test_mount.py を流すと子プロセスの出力が読めず落ちる(以前からの件。付けない)。Python のヒアドキュメントで `\x00` などを書くと JS に本物の NUL が入る(raw 文字列で書く)
- 実機で確かめてもらうこと: `docs/plan/friend-lite-realcheck.md`(60fps→30fps の字幕のずれ・字幕の大きさ 0.08・ふちの色)・友人の PC での lite\start.bat の初回(uv・CUDA の部品・int8_float16)・ドロップの受け取り(大きな動画)
- 決めたこと(変えたければ言ってもらう): モデル large-v3-turbo・出力は ドキュメント\文字起こし簡易版\・Resolve のプロジェクトは 30fps 固定・同時に話す2人の行も時刻は重ねない(ブリーフの「重ならないよう制限」に合わせた)
- 未コミット: なし(このあとコミット)

## 2026-10-02 Claude Code — 線 B 段2 の 2回目: 2-1 認識エンジンの口(担当の宣言: editor/ の認識の部分)
- 担当: 線 B 段2(`editor/tx_engines.py`・`tx_worker.py`・`ed_jobs.py` の認識の部分)は Claude Code(PC)。ROADMAP の順番どおり(段10 → 線 B 段1・2)
- 新しい `editor/tx_engines.py`: エンジンの形(`create(name, device, compute_type)`・`transcribe(audio, **kw)` = faster-whisper と同じ (行, 情報)・`params()`)と一覧 `ENGINES`。今は `FasterWhisper` だけ(引数と結果をそのまま通す)。
  ネイティブの部品は `create` の中で読む(サーバー側も名前と版のために読むので、先頭で import しない)。知らない名前は ValueError(要求の文字列からクラスを探さない)
- `ed_jobs`: `load_model(…, engine)`・`_load_model_local(…, engine)`(モデルの使い回しのキーを `(名前, 機器, エンジン)` に)・`_new_whisper` は `FasterWhisper.create` へ移した・`RemoteModel.engine`・`recognition_run` の engine/版はエンジンから。
  既定のエンジンのときはワーカーへの要求に engine を足さない(今までと同じやり取り)
- `tx_worker`: 要求の `engine`(無ければ faster-whisper。一覧に無ければ `bad_engine` で断り、ワーカーは落ちない)・受け付ける引数はエンジンの `params()`
- テスト: test_worker に `test_engine_by_name_through_worker`・`EngineTest`(そのまま通す・知らない名前・先頭でネイティブを読まない)。写す一覧(`("tx_worker.py", …)` の9か所)に `tx_engines.py`。編集の単体 238 → そのまま通る
- 未コミット: なし(このあとコミット)

## 2026-10-02 Claude Code — 線 B 段2 の 2回目: S-1 全体の再認識の区間ごとの保存・続きから → 編集 0.35.0(2回目は済み)
- `ed_jobs.whole_lines`: 全体の再認識は、長さが `WHOLE_PART_SEC`(600 秒)の 1.5 倍を超えたら `whole_parts` で区間に分ける(区切り = 目安の前後 90 秒の中で、今の文書の行の無いいちばん長いすき間の真ん中。無ければ目安の所)。
  区間ごとに `RangeRecognizer.main(p0, p1, share)`(行は区間の内側に切る・進み具合は区間の割合)。終わった区間の行を `transcripts/.resume/<id>.whole.json` に書き、
  目印 `whole_key`(文書・範囲・行を作る設定・ヒントの語・エンジンとモデル・元の動画の大きさと更新日時)が同じならもう一度始めたときに使う(`job["resumed"]`・知らせ「前回の途中から続けました」)。
  反映したら・文字が出なかったら消す。使われなかった記録は 7 日で消す。**短い動画は1区間 = 以前と同じ結果・記録を書かない**
- 置き場所を TX_DIR の下にしたのは、テストが TX_DIR を一時フォルダに向けるため(DATA_DIR の直下だと inplace のテストでリポジトリに書く)。`docs/spec/data-location.md` に1行
- 新しい文字起こし(`run_job`)はまだ1回で認識する(計画の S-1 は全体の再認識だけ)
- テスト: test_worker に `test_whole_resumes_from_saved_parts`(2区間目で落ちる → 続きから → 通しと同じ行)・`test_whole_resume_needs_same_settings`・`EngineTest.test_whole_parts_cut_in_gaps`。
  編集の単体 245(238 + 7)・test_mount 26・契約 34・eval_asr 4・ui-kit 5・node 9・e2e 12 本すべて OK(`dev/run_editor_suite.py`。e2e_eval_set も一式の中で通った)
- 版: 編集 0.35.0(serve.py・app.js・README)。文書: editor/AGENTS.md(新しい節)・README の変更の記録・計画の「2回目の結果」と状態・ROADMAP(線 B と版の行)
- 次(3回目): 段2-2 whisper.cpp Vulkan。**始める前にユーザーに聞く**: 実行ファイルをツールが取得するか(推奨 = URL・SHA-256 固定)・手で置くか(計画の 8 の 4)
- 実機で確かめること(急がない): 15 分を超える文書の「全体を再認識」で処理状況に「(n / m 区間)」が出る・途中で中止してもう一度押すと「前回の途中から続けました」
- 未コミット: なし(このあとコミット)

## 2026-10-02 Claude Code — 線 B 段2-2 whisper.cpp Vulkan(コードとテスト。実機の作成と確認はこのあと)
- 決定(ユーザー 2026-10-02): whisper.cpp は公式の配布に Windows の Vulkan 版が無い(CPU・BLAS・NVIDIA だけ。v1.9.4 = b5130 のリリースを API で確かめた)→ **公式のソースを決まったコミットで取り、この PC で作る**。
  Vulkan SDK はユーザーが winget で入れる。llama.cpp(段2-3)は公式の win-vulkan-x64 の zip があるので、ツールが URL・SHA-256 固定で取得してよい
- `setup/build-whisper-vulkan.bat`(ASCII)→ `setup/build_whisper_vulkan.py`: v1.9.4 を shallow clone → HEAD が `927cfce3…` と一致しなければ作らない → VS 2022 の CMake(Visual Studio 17 2022 の生成器 = 開発者用の画面が要らない)・`-DGGML_VULKAN=ON` → whisper-cli だけ作る → `--help` で動くか確かめる →
  作業データの `bin\whisper.cpp-v1.9.4-vulkan\`(whisper-cli.exe・DLL・build.json = 版・コミット・各ファイルの SHA-256)。ソースは `build\`
- `tx_engines.WhisperCpp`: whisper-cli を子プロセスで(引数のリスト・shell なし・窓なし)。**引数は応答ファイル `@args.txt`(UTF-8)で渡す**(コマンド行は Windows の文字コードで読まれ、日本語のヒントが化けるため。そのかわりパスは ASCII でないと開けないので、短い名前(8.3)にするか理由を出して止める)。
  faster-whisper の引数を写す(language・beam・-mc 0・temperature 0 → -tp 0 -nf・no_speech → -nth・initial_prompt → --prompt・声の検出 → --vad + Silero v6.2 の ggml + 閾値・無音・余白。hotwords は無い)。
  結果は -ojf の JSON → faster-whisper と同じ属性の行(単語 = 文字のトークン・確率。avg_logprob = トークンの確率の対数の平均、compression_ratio = 同じ式、no_speech_prob = なし、duration_after_vad = なし)。
  **GPU を頼んだのに `whisper_backend_init_gpu: using Vulkan… backend` が無ければ止める**(黙って CPU にしない)。機器の順は auto/cuda → vulkan だけ・cpu → -ng。取り消し・進み具合はワーカーが `hooks` で渡す
- モデル: ggml の large-v3(3.1GB)・large-v3-turbo(1.6GB)・Silero v6.2(885KB)を大きさと SHA-256 固定で `models\whispercpp\` に取る(`fetch_file`。https だけ・.part に書いて合ったときだけ名前を付ける・合わなければ消す)。anime-whisper は変換が要るので後回し
- サーバー: 要求の `engine`(`req_engine`。一覧に無い名前・そのエンジンで使えないモデルは断る)・`check_engine`(faster-whisper は今までどおり、whisper.cpp は実行ファイルと build.json のコミット)・`load_model(…, engine=engine_of(spec))` を文字起こし・再認識・範囲/全体に。画面からはまだ選べない(比べて決めてから)
- 精度を測る道具: `dev/eval_asr.py run --engine whisper.cpp`(実行ファイルとモデルは本物の作業データ = `S.ENGINE_DIR`)
- テスト: `editor/tests/test_whispercpp.py`(test_metrics から読む。偽の whisper-cli `tests/fake_whisper_cli.py` で引数・UTF-8 のヒント・結果の読み取り・GPU が無いとき止める・失敗・取り消し・取得の大きさと SHA-256・サーバーの受付と準備)・
  test_worker の `test_whispercpp_through_worker`(worker-fake のワーカーは偽の whisper-cli を使う)。編集の単体 254・test_mount 26・eval_asr 4 OK
- 未コミット: なし(このあとコミット)。次: ユーザーが Vulkan SDK を入れたら、build-whisper-vulkan.bat で作り、本物の GPU で動くか・速さを確かめる → 版を上げる

## 2026-10-02 Claude Code — 線 B 段2-2 whisper.cpp Vulkan の実機の確認 → 編集 0.36.0(3回目は済み)
- ユーザーが Vulkan SDK 1.4.363.0 を入れた → `setup/build-whisper-vulkan.bat` で作った(作業データの `bin\whisper.cpp-v1.9.4-vulkan\`。build.json にコミットと各ファイルの SHA-256)
- 実機で分かって直したこと:
  ① MSBuild は 260 文字を超えるパスで失敗する(FTK1011。シェーダーを作る入れ子のプロジェクトで約 190 文字)→ 作る場所を `C:\ytt-build\` に・できたら消す(git の読み取り専用のファイルも消す `rmtree_all`)
  ② RX 7800 XT + AMD のドライバでは、最初の GPU の計算で何も出さずに 0xC0000409 で落ちる → 行列コアの経路を切る `GGML_VK_DISABLE_COOPMAT=1`(`wcpp_env`。指定があればそれに従う)。40 秒の音声が 6.8 秒(CPU 52.5 秒)
  ③ 声の検出(--vad)のモデルは CPU で動き「no GPU found」の行を出す → GPU の確かめを、認識のモデルの `using … backend` の行で判断するように(偽の whisper-cli も同じ行を出す)
  ④ whisper.cpp の声の検出は声の所をつないで認識するため、文字が大きく抜けた(turbo で CER 36% → 80%)→ 既定で受け付けない(`params()`。測るときだけ `TRANSCRIBE_WCPP_VAD=1`)
  ⑤ 精度を測る道具は serve を登録せずに読み、認識はワーカーで動く → 実行ファイルとモデルの置き場所を環境変数 `TRANSCRIBE_ENGINE_DIR` で渡す(`engine_home()`)
- 測った結果(評価用 18 本・1,229 秒・温度 0・文脈なし。結果は作業データの `evals/asr/20261002-*`): faster-whisper large-v3 CPU **21.7%**(141/468/102)900 秒 /
  whisper.cpp large-v3 GPU 27.0%(223/243/415)180 秒 / turbo GPU 36.4% 86 秒。**GPU は 5 倍速く抜けは半分・余分が 4 倍 → 採用はまだ**。以前の基準 22.8% は評価用 21 本(フォルダの整理の前)なので、今後はこの 21.7% と比べる
- 次の候補(計画の「3回目の結果」): whisper.cpp に faster-whisper の Silero の区間を渡す / 2-3 Qwen3-ASR / 段3 の2つ目のエンジン
- テスト: 編集の単体 254・test_mount 26・契約 34・eval_asr 4・ui-kit 5・node 9・e2e 一式・通し確認 すべて OK(e2e_row_editing は一式の中で1回だけクリックの時間切れ → 単独で ALL PASSED)
- 版: 編集 0.36.0。文書: editor/AGENTS.md・README・計画の「3回目の結果」・ROADMAP
- 別のセッション(評価用データフォルダ構成)が `editor/ed_relink.py`・`editor/tests/test_edit.py` を直している(未コミット。このコミットには入れない。版は向こうが 0.36.1 で上げる)
- 未コミット(こちらの分): なし

## 2026-10-02 Claude Code — 評価用の仮置き: 文書の無いコピーを元の文書に付け替える(版はあとで 0.36.1)
- 依頼: ユーザー「2本評価用に追加したけど移らない」→ 原因は、仮置きに入れたのがコピーで、文書は元の書き出し先の動画を指したままだったこと(仕組みは仮置きの動画を使う文書しか見ない)。
  その2本は中身が同じことを確かめて、動いている入口の API で文書を仮置きのコピーへ付け替え → 整理で `評価用データ44_宙科そぴあ_01_済.mp4`・`_02_済.mp4` へ移った
- 決定(ユーザー 2026-10-02「つかう」): 整理のときに自動で付け替える。`editor/ed_relink.py` の `_eval_copy_index`・`_eval_adopt_copy`(同じファイル名・同じ大きさの動画を指す文書がちょうど1つ。
  元の動画が無い・評価用のフォルダの中を指す・行が無い・候補が2つ以上・処理中は付け替えない。記録の理由 `evalStagingCopy`)。設計: `docs/design/eval-folder.md` の「仮置きのコピーの付け替え」
- テスト: test_edit の TestEvalFolder +2(付け替えて移る・大きさが違えば付け替えない・元の動画は残る/候補が2つなら理由を残す)。編集の単体 256 OK(別のセッションの未コミットの変更も入った作業ツリーで)
- 別件: 10-01 23:26 の `/api/metrics` の TypeError('range_iterator')と直後の入口の異常終了は、同じ処理が 3.10・3.12 で正しく動き・今の入口でも正常なので、PC の不安定さ(CPU の件)による一時的なものとみた
- 注意: 「計画の次」のセッションが editor/ を作業中(線 B 段2-2・0.36.0 が未コミット)だったので、私は ed_relink.py・test_edit.py・eval-folder.md だけを直してコミットした。
  **版(serve.py・app.js・README)は、そちらが 0.36.0 をコミットしたあとに 0.36.1 で上げる**(README の変更の記録もそのとき)
- 追記: 「計画の次」が 0.36.0 をコミットした(ff9a0ce)あと、編集を **0.36.1** に上げた(serve.py・app.js・README の変更の記録・editor/AGENTS.md・ROADMAP の版)。編集の単体・e2e_ui_mounted・e2e_eval_set OK
- 未コミット: なし

## 2026-10-02 Claude Code — 線 B 段2-2 の続き: whisper.cpp の余分な文字を減らす(ユーザー決定「1」= Silero の区間)を試した
- `tx_engines`: whisper.cpp の vad_filter を「全体を認識 → Silero(faster-whisper の、ワーカーの中)で声のある所 → その外の行を捨てる」にした(`speech_spans`・`drop_outside_speech`。時刻はつながない)
- **測ったら悪くなった**(評価用 18 本・温度 0): 27.0% → **33.8%**(抜け 243 → 588・余分 415 → 334)。BGM・ゲームの音で Silero が声を取りこぼす(今の faster-whisper の抜けが多いのも同じ理由とみられる)。no_speech の閾値を外しても同じ数
  → 既定では使わない(測るときだけ `TRANSCRIBE_WCPP_SPEECH_FILTER=1`)。whisper.cpp 自身の声の検出も既定で使わない(`native_vad()`・`TRANSCRIBE_WCPP_VAD=1`)
- 余分な文字を調べると、多くは声の無い所の幻覚ではなく**同じ文字の繰り返し**(「うううう…」76・25・16・13 字。その下の本当の行も消える)。原因は測る道具の `--temp0`(whisper.cpp では `-nf` = 温度のやり直しを止める)
- **温度のやり直しあり(アプリで普段使う形)で測ると whisper.cpp large-v3 GPU = CER 21.6%**(置換 187 / 抜け 248 / 余分 272)・130 秒。faster-whisper(温度 0)21.7%・900 秒とほぼ同じで約 7 倍速い。
  公平のため faster-whisper も「やり直しあり」で測っている(このあと)
- テスト: test_whispercpp 10 件(Silero の区間で捨てる・捨てる規則)・編集の単体 OK
- 未コミット: なし(このあとコミット)
- 追記(同じ日): faster-whisper large-v3 CPU も「やり直しあり」で同じ 18 本を測った = **21.1%**(150/439/104)・561 秒。whisper.cpp large-v3 GPU 21.6%・130 秒と誤差の範囲で同じ・約 4 倍速い。
  計画の「3回目の結果」と ROADMAP に表を書いた。主のエンジンにするかはユーザーに聞く。測るときは whisper.cpp を温度 0 で測らない(繰り返しで悪く出る)

## 2026-10-02 Claude Code — AMD の GPU(whisper.cpp)を画面から選べる → 編集 0.37.0
- 「続行」= 次の候補 ①(whisper.cpp を画面で選べるように)。既定は今までどおり「自動」(faster-whisper)。主のエンジンを替えるかは使ってみてから
- 画面: 「認識の設定」の処理方式に「GPU(AMD など・whisper.cpp)」(`vulkan`)。`/api/tools` の `wcpp.ready`(作ってあるとき)だけ app.js が足す。保存した設定の device = vulkan は読み込み直しても残る
  (`applySettings` は選択肢にある値だけ)。whisper.cpp で使えないモデルなら、その場で案内(`#optDevHint`)と「始める」の上の要約にも出す(「認識の設定」は閉じていることが多いため)。
  ジョブ・設定の比較・文書の認識の設定の表示は `devLabel`(vulkan = 「GPU(whisper.cpp)」。以前は cuda 以外を CPU と出していた)。AMD の案内の文も直した
- サーバー: `req_engine` が `device: "vulkan"` を whisper.cpp にする(spec の device は auto = Vulkan だけ・黙って CPU にしない)・使えないモデルは使えるモデルを案内する `bad_model`・`engines_info()` を `/api/tools` に
- 設定の比較(A/B。`ed_misc`)は今までどおり faster-whisper(vulkan は auto 扱い)
- 確かめた: 一時の作業データに作った印だけを置いた疑似のサーバーで、選択肢が出る・保存と読み込み直し・案内の出し入れ(内蔵のブラウザ)。テスト一式すべて OK(編集の単体 259・e2e 12 本・通し確認)
- 実機で確かめてもらうこと: 入口を「すべて終了」→ start.bat → 「認識の設定」で GPU(AMD など・whisper.cpp)・large-v3 を選んで文字起こし → 処理状況に「GPU(whisper.cpp)」・速さ
- 未コミット: なし

## 2026-10-02 Claude Code — 線 B 段2-3 Qwen3-ASR を試した → 編集 0.38.0
- 依頼: ユーザー「とりあえず 2-3 までやって」
- 変更: `editor/tx_engines.py`(Qwen3-ASR の共通の元 `_Qwen3Chunked`・`Qwen3Asr` = 0.6B sherpa-onnx CPU・`LlamaQwen3` = 1.7B llama-server Vulkan・区切り `q3_chunks`・行 `q3_rows`・繰り返し `q3_squash`・答え `q3_parse`・安全な展開 `_safe_extract`/`_safe_unzip`・ジョブオブジェクト `_kill_on_close_job`)、
  `dev/eval_asr.py`(`--engine qwen3-asr|llama.cpp`・エンジンの既定のモデル・**時刻によらない CER** `doc_text`)、テスト `editor/tests/test_qwen3.py`・`fake_llama_server.py`(test_metrics から読む)・`dev/tests/test_eval_asr.py` +1、
  版 0.37.0 → 0.38.0(serve.py・app.js・README の変更の記録)、editor/AGENTS.md、計画の「4回目の結果」、ROADMAP。README の以前の版の記録で `setup\build-…` の `\b` が制御文字になっていたのも直した
- 新しい依存は無し(sherpa-onnx は入っている版)。取得するもの(作業データの中・どれも URL・大きさ・SHA-256 固定): sherpa の 0.6B(879MB)・llama.cpp b11326 の win-vulkan-x64(33MB。10-02 に取得の許可済み)・ggml-org の 1.7B Q8_0 GGUF と mmproj(2.5GB)
- 結果(評価用 18 本・時刻によらない CER): faster-whisper 20.2%・561 秒 / whisper.cpp 18.7%・130 秒 / **Qwen3 1.7B GPU 27.2%・32 秒** / Qwen3 0.6B CPU 32.9%・169 秒。文脈のヒントは悪化。主のエンジンにはしない(画面にも出さない)。
  結果のファイルは作業データの `evals/asr/20261002-055502_段2-3-qwen3-0.6b-ja.json`・`20261002-060650_段2-3-qwen3-1.7b-gpu.json`
- 注意: **この PC は今とても不安定**(CPU の件)。sherpa-onnx の読み込み・llama-server の起動・Python 自体(正規表現の解析の中など)がまれに落ちる。読み込みと起動は1回だけやり直すようにした。
  測定は途中で文書が「とばしました」になったら数に入らないので、全部そろった回だけ比べる。単体テストも同じ理由でまれに落ちる(流し直すと通る)
- テスト: 編集の単体 275(skip 1)・test_qwen3 16・eval_asr 5 OK
- 未完了・次: 段2-4 比較と決定(評価用の校正待ち)。Qwen3 1.7B は段3/4 の2つ目のエンジンの候補
- 未コミット: なし(このあとコミット)

## 2026-10-02 Claude Code — 簡易版: Resolve の映像トラックの数を選ぶ → 編集 0.39.0・cut2resolve 0.18.0
- 依頼: ユーザー「友人側で映像トラック数(1〜5)を選択して、映像トラックをその数分追加する。その一番上に字幕」
- 解釈(報告で確認を頼んだ): 数 N = 映像トラックの本数。V1 = 動画・V2〜VN = 空(素材を重ねる用)・字幕は V(N+1)。N = 1 は今までどおり(V1 動画・V2 字幕)
- cut2resolve: `pack.build_pack(video_tracks=1)` → `resolve_textplus.write_files`/`build_import_plan`(計画の `videoTracks`。1 のときは書かない = 今までと同じ中身・契約テストも同じ)。
  Lua は AddTrack を N 回 → `trackIndex=captionTrack`(N+1)。マーカーのメモに字幕のトラック(V3 以上のとき)。手順書(`instructions`・`readme_from_script`)のトラックの書き方も数に合わせる。範囲の外は ToolError(`video_tracks_value`)
- 編集(簡易版): 書き出しの段に「映像トラックの数」の select `#ltTracks` と案内 `#ltTracksHint`。設定 `videoTracks`(`ed_lite.load_settings`/`save_settings`。1〜5 の整数だけ・既定 1)を覚えて次から使う。
  書き出しの要求 `/api/lite/export {id, videoTracks}` でも渡して覚える(選択の保存と書き出しが前後しても選んだ数で作る)。lite/README.txt に1行
- テスト: test_pack +1(偽の Resolve で V4 に字幕・tracks=4・既定は V2)・lite の build_pack の確かめ +・test_lite +1(設定)と書き出しで 3 を選んだときの Lua と手順書・e2e_lite に選択と案内と保存。
  cut2resolve 312・編集の単体 290・契約 34・test_mount 26・e2e_lite・e2e_ui_mounted・e2e_edit_pack・通し確認 OK
- 実機で確かめてもらうこと: 本物の Resolve で N = 3 などの Lua を流し、AddTrack で V2〜V4 ができ、字幕が V4 に入るか(偽物では確認済み)
- 未コミット: なし(このあとコミット)

## 2026-10-02 Claude Code — 友人の依頼に映像トラックの数 → 送るアプリ 1.4.0・ホーム 0.22.0・cut2resolve 0.19.0
- 依頼: ユーザー「友人のアプリから送る依頼につける」(直前の簡易版の映像トラックの数と同じものを、送るアプリの ① 全自動のパックにも)
- 送るアプリ: 「PC でどこまでやるか」の下に「Resolve の映像トラックの数」(1〜5)と案内。① 全自動のときだけ有効(②③ はパックを PC で作らないため)。送るたびに選ぶ・覚えない。
  JSON は 2 以上・① のときだけ `"videoTracks":N`(`VideoTracks.JsonPart`。1.3.0 までの呼び出しはそのまま)。build.bat のテスト 19 件 OK・画面は DrawToBitmap で確認(②で灰色)
- ホーム: `intake.parse_video_tracks`(2〜5 の整数・flow が auto のときだけ)→ `start_request`/`start_file(video_tracks=)` → `Run.video_tracks` → `_pack_one` が `output.videoTracks`。
  依頼の一覧に「映像トラック: N本」(`tracksLabel`・portal.js)
- cut2resolve: `/api/build` の `output.videoTracks`(省略 = 1・範囲の外は 400 bad_tracks)→ `pack.build_pack(video_tracks=)`
- 文書: friend-intake.md の 2-5・各 README・ROADMAP の版
- テスト: home 186・cut2resolve 314・契約 34・push_helper・e2e_portal・e2e_intake_ui・e2e_autorun・通し確認 OK(test_launch の test_autorun_history が1回だけ落ち、単独・流し直しで OK = 時間の揺れ)
- 回答(ユーザーの質問): 依頼のカットの既定は「カットしない」(home/prefs.py の DEFAULTS autorun.cut = "none"。この PC の prefs.json も未設定 = none)
- 友人へ: dist\RequestSender.zip(1.4.0)を渡し直す。ユーザーは入口を「すべて終了」→ start.bat
- 未コミット: なし(このあとコミット)

## 2026-10-02 Claude Code — 依頼の映像トラックの数: 受付は 1〜5・既定 1(ユーザー指示)
- ユーザー「ホームの依頼の受付では 1〜5 で指定する。初期値は 1 でいい」→ `intake.parse_video_tracks` を 1〜5 の整数(無い・形が違えば 1)に。① の依頼は必ず数が決まり、一覧に「映像トラック: N本」(1 でも)
- 送るアプリも ① のときは 1 を含めて毎回 `videoTracks`(1〜5。範囲の外は 1)を書く。②③ は今までどおり書かない。版は据え置き(ホーム 0.22.0・アプリ 1.4.0 はまだ配っていない)
- テスト: test_intake・test_autorun 80・home の残り・e2e_intake_ui・build.bat 19 件 OK
- 未コミット: なし(このあとコミット)

## 2026-10-02 Claude Code — 映像トラックの数の意味を直した: 空のトラック → 同じ動画を V1〜VN に重ねる
- ユーザー: 案内の「V2 は空」を見て「何これ? やりたいことの意味わかってる?」→ 確かめたら「1」= **同じ動画を N 本のトラック全部に置く**(重ねて加工する用)。私の解釈(V2〜VN を空に)が違っていた
- Lua: AddTrack を N 回(字幕は今までどおり V(N+1))→ V2〜VN に V1 の各区間と同じ位置(`recordFrame = edits[i]:GetStart()`)・同じ範囲で **映像だけ**(`mediaType=1`。音声まで重ねると音が二重になるため、音は A1 の1本)。
  置けなかった・位置か長さが合わない区間は数えてマーカーのメモ(「同じ映像 V1〜VN(置けなかった n)」)と黄色/一部失敗に
- 偽の Resolve(resolve_lua_mock.lua): 動画を trackIndex で置いたら長さをタイムラインのコマに換算し、mediaType を出す。test_pack の 3 本で V1〜V3 に 2 区間ずつ・mediaType=1 が 4 つ
- 案内の文(簡易版・送るアプリ)と手順書・各 README・friend-intake.md を「V1〜VN に同じ動画、V(N+1)(いちばん上)に字幕」に。版は据え置き(まだ配っていない)
- **実機で確かめること**: 本物の Resolve 21.1 で `mediaType=1` と `recordFrame` を指定した AppendToTimeline が V2 以上に映像だけを置くか(API の文書にはあるが、この PC ではまだ試していない)
- テスト: cut2resolve 314・test_lite 14・契約 34・e2e_lite・test_intake/test_autorun 80・build.bat 19 件 OK
- 未コミット: なし(このあとコミット)

## 2026-10-02 Claude Code — 依頼の受付で同じ動画を断らない
- ユーザー「同じ動画を断らないようにする」→ `home/intake.py` の `_accept_video` の重複の検査(大きさ + 先頭と末尾 4MB のハッシュ `file_key` と `st["files"]`)を外した。`file_key`・`HASH_PART`・hashlib も消した。
  送り直すたびに作業データへ別のコピー(同じ名前なら末尾に乱数)として入り、別の実行になる。状態の `files` は読み込みだけ残す(以前の記録。増えない)
- 配信の URL は今までどおり「前に受け付けた配信です」で断る(今回の対象外。必要なら同じように外せる)
- テスト: test_intake の test_manual_video_with_name を「2回目も受け付ける」に・+1(同じ中身を映像トラックの数 1 と 2 で送り直し → 2 本とも受け付け・別のコピー)。home 142・e2e_intake_ui・通し確認 OK
- 文書: friend-intake.md の重複・home/README.txt(0.22.0 の項に追記。版は据え置き)
- 未コミット: なし(このあとコミット)

## 2026-10-02 Claude Code — 切り抜き依頼の機能追加と画面の全面見直し → 送るアプリ 2.0.0・ホーム 0.23.0・スタジオ 0.14.0
- 依頼: ユーザー「配信の URL で時間を指定してその部分を切り取る / カットなしを初期値にして選べるように / UI の全面見直し(特に時間の入力)/ 便利な機能を提案 / AI モデルやサブエージェントを適切に」。
  UI の作業の決まり(ui-dev-workflow)どおり、聞き取り → 設計書 → 確認 → 実装 → 見直しの順。設計書と決まったこと: `.design/request-sender-overhaul/DESIGN_BRIEF.md`、
  見直し: 同 `DESIGN_REVIEW.md`、進め方の記録: 同 `IMPLEMENTATION.md`。PC 側の決まりは `docs/design/friend-intake.md` の 2-6
- 決定(ユーザー 2026-10-02): ① 区間が「切り抜く数」に足りない分だけ自動で埋める ② カットは「しない(初期値)/ 無音を削る」の2つ ③ 時刻は1つの欄・「:」は打たない・
  時 → 分 → 秒 の順に左から打つ(右から押し出す形は不採用)・← → で場所を選ぶ・「+30秒」などのボタンは要る ④ 前後の余白 2 秒は PC が自動で付ける(選ばせない)
  ⑤ 仕上げ方は毎回 ①・ほかは覚える ⑥ URL の題名を出す ⑦ 届いた知らせは「窓を出すなどで絶対に操作の邪魔をしない」 ⑧ 同じ配信も受け付けて解析などは使い回す
  ⑨ ③ + 時間指定はやらない ⑩ 配色はサイバー風の 4 つから選べる(右上)⑪ 解析の重みは 音声・チャット・コメント の数字を直接いじる。
  提案して選ばれなかったもの: 時刻のメモをまとめて貼る・区間に題名・送った依頼の進み具合
- 送るアプリ(`request-sender/`。C# 5): 画面を作り直した。`TimeCore.cs`(時刻の読み書き・時刻の欄の状態 `TimeEdit`・区間・カット・重み・題名・覚える設定)・`Theme.cs`(配色 A〜D・フォント・DPI)・
  `Controls.cs`(自前で描く部品: ボタン・チェック・ラジオ・数の − / +・入力の枠・一覧・右クリックのメニュー)・`TimeBox.cs`(時刻の欄。自前の描画)・`StreamCard.cs`(配信のカード・区間の行・題名の問い合わせ)・
  `MainForm.cs`(横2列・下の帯の要約・届いた知らせ)・`MainForm.Receive.cs`(配色・自前の一覧)・`Program.cs`(`--screenshot`)。
  依頼の JSON に `items[].ranges`・`cut`・`weights`(`top` は配信ごと)。settings.json は保存先を消さずに足す(`LocalState.UpdateSettings`)。通信は Dropbox と YouTube の oEmbed(ID だけ渡す)
- スタジオ: `POST /api/video/request-marks`(`store.request_marks`。区間を採用済みの手動マークに・足りない分を自動の上位(区間と重ならない)で採用・使い回す・学習の記録は書かない)
- ホーム: `intake.parse_ranges`・`parse_cut`・`parse_weights`、配信の URL の重複を断らない、`autorun` の `Run.ranges`・`cut`・`weights`・`pad_range`(前後 2 秒)・`_step_adopt_request`・
  `_weights_differ`(重みが違えば解析し直す)・① の送り直しはパックを作り直す(`overwrite`)。区間が切り抜く数に足りていれば段「解析」を外す。依頼の一覧に区間・カット・重みの札(portal.js)
- 版: 送るアプリ 1.4.0 → 2.0.0・ホーム 0.22.0 → 0.23.0・スタジオ 0.13.1 → 0.14.0(serve.py・core.js・README)
- テスト: build.bat 28 件(時刻・区間・JSON・設定・題名・時刻の欄のキー・配信のカード・要約)・スタジオの単体 249(+3)・ホームの単体(test_intake 28・test_autorun 62 ほか)・
  e2e_intake_ui・e2e_autorun・e2e_portal・e2e_analyze・e2e_ui(163)・e2e_ui --mounted(176)・通し確認 e2e_pipeline すべて OK。push_helper check OK。
  画面は `build\RequestSender.exe --screenshot`(窓ごと。配色 4 つ・最小/大きめ・③・誤り・送信中・送り終えた・受け取る)で確かめた
- サブエージェント: 最初の調査(スタジオの API。Haiku・読むだけ)は使えた。**実装と見直しを頼んだサブエージェント(Opus / 既定のモデル)は、起動するたびにセッションごと落ちた(4 回)** ので、
  画面も PC 側も見直しもまとめ役が直接行い、きりのいい所ごとにコミットした(WIP のコミットが 15 個ほどある)
- 注意: **この PC は今も不安定**。python の単体テストが Segmentation fault・SystemError で落ちることがある(変更前のコードでも同じ。流し直すと通る)。
  標準の出力をファイルへ向けて e2e を流すときは `PYTHONUTF8=1`(無いと cp932 で落ちる)。git bash の長いヒアドキュメントは失敗することがある(スクリプトをファイルに書いて流す)
- 実機で確かめてもらうこと(ROADMAP の 3 にも): 友人の PC で時刻の欄の打ちやすさ・配色・DPI 125%/150%・題名・届いた知らせ。本物の YouTube で、区間だけの依頼(解析なし)・区間 + 自動・重みを指定・同じ配信の送り直し
- ユーザーがやること: 入口を「すべて終了」→ start.bat(ホーム 0.23.0・スタジオ 0.14.0)。`request-sender\dist\RequestSender.zip`(2.0.0)を友人に渡し直す(鍵は同じ)
- 未完了・次: 設計レビューの「余裕があれば」(− / + の押しっぱなし・開始のあと自動で終了へ・カードを畳む・Ctrl+Enter)はユーザーの判断待ち
- 未コミット: なし

## 2026-10-02 Claude Code — 時刻の欄を使い回せる部品に → ui-kit v11(`UIKit.timebox`)・送るアプリは YouTube の URL を要る欄だけ
- 依頼: ユーザー「今回使った時間入力の UI を使いまわしたい(YouTube の時間機能は必要な時だけでいい)」
- ui-kit v11: `UIKit.timebox`(`<span data-ui-time>`・`attach` / `create` / `get` / `set` / `parse` / `format`)。送るアプリの TimeBox と同じ動き(「:」を打たない・時 → 分 → 秒・← →・↑ ↓・
  BackSpace・Delete・貼り付け)。選べること: 0.1 秒まで(`data-ui-time-tenths`)・**YouTube の URL も読む(`data-ui-time-youtube`。既定はオフ)**・上限(`data-ui-time-max`)・使えない(`aria-disabled`)。
  入力欄ではなくフォーカスできる要素に自分で描く(日本語入力に数字を取られない・選んだ所をアクセントで反転)。イベント `ui-time`・`ui-time-reject`・`ui-time-paste`。
  `UIKit.keys.isTyping` は時刻の欄を入力中と数える。CSS は `.ui-time`(空のときのクラスは `ui-time-empty`。`.empty` は「空の状態の箱」の部品と衝突するので使わない)
- 送るアプリ: `TimeBox.AcceptYouTubeUrl`(既定オフ。配信の区間の欄だけ true)・`TimeText.TryParse(text, allowUrl, out sec)`。動きは今までどおり(版は 2.0.0 のまま。まだ配っていない)
- 文書: `ui-kit/README.md` の v11・`docs/spec/ui-guidelines.md` の 3-2(時刻を手で入れる欄を新しく作るときは UIKit.timebox を使う・YouTube の URL は配信の位置の欄だけ)・request-sender/README.txt の開発の節
- **まだしていないこと(ユーザーに聞いた)**: 今ある時刻の欄の置き換え(スタジオの現在位置 `#rvNow`・マークの開始/終了・コラボの合わせる時刻。どれも 0.1 秒の欄)。
  置き換えるときは `data-ui-time-tenths` にして、スタジオの `Studio.isTyping`(core.js)に `.ui-time` を足す
- テスト: ui-kit の見本 e2e_styleguide(時刻の欄は本物のキー入力・Ctrl+V / Ctrl+C を含む)・test_ui_kit_sync・スタジオ e2e_ui --mounted 176・編集 e2e_ui_mounted・e2e_lite・ホーム e2e_portal・e2e_keymap・送るアプリ build.bat 28 件 すべて OK
- 注意: Web の時刻の欄は右クリックの貼り付けが無い(ブラウザの決まりで、入力欄でない要素には出ない)。Ctrl+V だけ。送るアプリ(C#)は右クリックでも貼れる
- 未コミット: なし

## 2026-10-02 Claude Code — 時刻の欄を3か所に置き換え → 編集 0.40.0・スタジオ 0.15.0(ui-kit v11 のまま)
- 依頼: ユーザー「スタジオのマークの開始・終了 / コラボの『合わせる時刻』/ 文字起こしの行」を `UIKit.timebox` に。文字起こしの行は「分の代わりに 0.1 秒単位」→ 確かめて **分:秒.0.1秒 の3つ**(ユーザー決定)
- ui-kit(v11 のまま足した): 形 `short`(`data-ui-time-short`。分:秒.0.1秒。1時間を超えたら分が 60 以上)・確定の知らせ `ui-time-commit`(Enter か欄を離れたとき・値が変わっていれば。
  `detail: {value, via: 'enter'|'blur', to}`)・`attachAll(入れ物)`・`get` / `set` は付いていなければ付ける・`format(秒, 形)`
- 編集(0.40.0): `app-rows.js` の `segHTML`(`<span class="t" data-f data-ui-time data-ui-time-short>`)・`renderDoc` で `attachAll`・微調整(`nudge`)は `UIKit.timebox.set`。
  確定は `app.js` の `#segs` の `ui-time-commit`: **並びが変わらなければ描き直さず `markOvl` だけ**(開始を打って Tab → 終了 と続けて打てる。以前は毎回描き直して文字の欄へフォーカスが移っていた)。
  `isTextEntry` と再生の追従の「入力中か」に `.ui-time`。CSS は `index.html` の `.seg .t`(`min-width:0`・フォーカスの枠)
- スタジオ(0.15.0): `review.js` の `tfieldHTML`(時:分:秒.0.1秒 = `data-ui-time-tenths`)・`renderList` で `attachAll`・確定は `ui-time-commit`(`S.rendering` の間は無視。
  Enter ならその欄のまま・欄を離れて確定したら移った先へフォーカス = **開始 → Tab で次へ進める**。以前は開始の欄に戻っていた)・行を選ぶ focusin に `.ui-time`。
  `core.js` の `Studio.isTyping` に `.ui-time`。`collab.js` の合わせる時刻 4 つ(`UIKit.timebox.get`。空なら理由を出してその欄へ)・使わなくなった `parseTime` を消した・Enter で保存は捕捉の段階で。
  「現在位置」(`#rvNow`)は今までの入力欄のまま(秒の数字でジャンプできるため。ユーザーの選択に入っていない)
- テスト: 欄の文字は `textContent`(`innerText` は区切りごとに改行が入る)・直すのは本物のキー入力。直したテスト: e2e_row_editing(`type_time`)・e2e_folder_marker_range・e2e_ui_handoff・e2e_edit_cut・
  スタジオ e2e_ui(+8: 数字だけ → Enter・↑ で 0.1 秒 → Tab で次へ・空にしても元に戻る・欄の ← → は再生位置を動かさない・コラボ 001235 → 0:01:23.5・空の欄へ移る)・ui-kit の見本(short・確定・attachAll)。
  結果: 編集の一式(単体 276・node 9・e2e 12 本・通し確認)・スタジオ e2e_ui 171 / --mounted 184・e2e_analyze・node 18・ui-kit の見本・ホーム e2e_portal / e2e_keymap・test_mount 26・契約 34 すべて OK
  (スタジオ e2e_ui は1回だけ「『読み直す』で保存済みの設定が入り、印が消える」が NG → 流し直しで 171 件 OK。時刻の欄とは別の所・この PC の時間の揺れとみた)
- 注意: 式の途中の行に `//` のコメントを足して後ろを消してしまい、編集の画面が動かなくなった(すぐ直した)。長い1行の式を直すときは、コメントは上の行に書く
- 実機で確かめてもらうこと: 入口を「すべて終了」→ start.bat。編集の行・スタジオのマークで、数字だけで時刻が入るか・日本語入力がオンでも数字が入るか・Tab で続けて打てるか
- 未コミット: なし

## 2026-10-02 Claude Code — 画面の見た目をサイバー風に → ui-kit v12(計器盤の形・配色4つ)
- 依頼の流れ: ユーザー「サイバー風を全体に。色違いを除いていろんなパターンを」→ 見本 `.design/cyber-theme/board.html`(本物の ui-kit の部品に
  A 計器盤・B ターミナル・C ネオン管・D 装甲パネル・E 設計図 を当てたもの)→ **A に決定** → A で配色9つ → **ネオンシアン・アイスライト・鋼の白・ターミナルグリーン** を選び、
  それぞれ直してと依頼(問題: 薄い文字のコントラスト・「済み」とアクセントが同じ色・注意と失敗の取り違え・スイッチのつまみが消える・情報と済みが近い)→ 直して「続けて」= 本番へ
- ui-kit v12(`ui-kit.css` の末尾「v12」・`ui-kit.js` の `UIKit.theme`): 形 = 角 2px・カードの左上と右下に角の括弧(`.card::before/::after`)・タブと切り替えは下線・
  札は枠だけで等幅・進み具合は目盛り・知らせは左の線・表の見出しは等幅。色 = 明るい `:root` がアイスライト・暗い `:root[data-theme=dark]` がネオンシアン・
  `data-palette=steel|green` で鋼の白・ターミナルグリーン。暗いときの配色は `localStorage['ytt:palette']`(`UIKit.theme.palette()`)= 明るい/暗いの保存(`ytt:theme`)とは別なので、
  切り替えボタン・OSに合わせる・以前の保存がそのまま動く。⚙ の「テーマ」: アイスライト / ネオンシアン(値は以前の dark のまま)/ 鋼の白 / ターミナルグリーン / OSに合わせる。
  スイッチのつまみは `--knob`。各ツールへ写した(`dev/sync_ui_kit.py`)。ツールの版は上げていない(ui-kit だけの変更)
- 決めた数値と理由: `.design/cyber-theme/patterns.css` の「調整した4つ」(コントラストはどれも文字/地 4.5:1 以上・本文 7:1 以上・状態の色どうしが近すぎない)
- テスト: ui-kit の見本 e2e_styleguide(+配色: 明るい = ice・暗い既定 = cyan・palette('steel') と保存・明るい ↔ 暗いで最後の暗い配色に戻る)・test_ui_kit_sync・
  編集の一式(e2e_ui_handoff と e2e_proofread_keys は ⚙ のテーマの値 dark を選ぶので、値を互換にして通した)・スタジオ e2e_ui 171 / --mounted 184・ホーム e2e_portal・e2e_keymap・
  e2e_intake_ui・e2e_window すべて OK。画面は見本の環境(`dev/demo_env.py`)で ホーム・スタジオ・編集 × 配色4つを撮って確かめた
- 送るアプリ(`request-sender/`)の配色は別のまま(A ネオンシアン・B シンセウェーブ・C ターミナルグリーン・D アイスライト)。そろえるかは未定
- ユーザーがやること: 入口を「すべて終了」→ start.bat(ui-kit の写しが変わった)。⚙ の「テーマ」で4つを試す
- 未コミット: なし

## 2026-10-03 Claude Code — Windows の入れ直しのあとの復元・.gitignore に秘密情報の名前を足した
- 経緯: ユーザーが PC の Windows を入れ直し、C:\dev\youtube-tools を GitHub から clone し直した(最新 19e0316 = 10-02 19:22)。
  10-02 19:22 以降の未 push の作業と、作業データ `%LOCALAPPDATA%\youtube-tools\`(data.json・feedback.jsonl・config.json・settings・cache・transcripts・dataset・evals)は失われた
  (C:\Windows.old は空。デスクトップのバックアップ `D:\backup\Desktop\youtube-test` は 09-30 08:17 の段0 の途中で、作業データは 09-26 から外にあったので入っていない)
- 復元(バックアップから。上書きなし・diff/cmp で一致を確認): cut2resolve の packs 15件 → `%LOCALAPPDATA%\youtube-tools\cut2resolve\packs\`、
  editor の voices/voxceleb.json → `%LOCALAPPDATA%\youtube-tools\transcribe\voices\`、`Claude outputs/`、`cut2resolve/tests/fixtures/resolve-ui-test/` の test35.mov ×2。
  写していない(ユーザーの選択): .design の写真・holo-colors の build/dist・cut2resolve/exports・古いログ・.runtime
- 変更: `.gitignore` に `**/.env`・`**/cookies.txt`・`**/cases.json`・`**/.migrated.json`(push_helper の BAD_NAMES にあるが .gitignore に無かった。push.bat を通さない `git add .` で入るおそれ)。
  追跡中のファイルと全履歴をキー・トークンの形で調べ、本物は無かった(当たったのは test_push_helper.py のダミーだけ)
- 注意: バックアップの .git にある段0 コミット2(bd6cb40)・2e3c069 は origin に無い(origin は c422f14 で同じ内容を入れ直している)。拾わなくてよい
- ユーザーがやること: 起動後、スタジオ・編集の設定を入れ直す
- 未コミット: なし

## 2026-10-03 Claude Code — 入れ直しのあとの続き: 動かすソフトの入れ直し・API キー・動作確認・評価用データの整理(記録だけ)
- 変更: この記録だけ(コードの変更なし)。ユーザーが貼った作業の記録のうち、上の件に無かった分を残す
- 入れ直したソフト: Python 3.10.11(winget)・yt-dlp 2026.08.19(winget。Deno と yt-dlp 用の ffmpeg も一緒に入った)・
  `setup/requirements.txt`(faster-whisper 1.2.1・ctranslate2 4.8.2・onnxruntime 1.23.2・numpy 2.2.6)・`setup/requirements-diarize.txt`(sherpa-onnx 1.13.8)。
  Python 3.10 で部品を読み込めた。ytt_core のテスト 74件 OK
- YouTube Data API のキー: 消えていたので Google Cloud Console で作り直した(名前「youtube-tools スタジオ」・API の制限 = YouTube Data API v3 だけ・アプリケーションの制限なし)。
  スタジオの ⚙ で入れた → `%LOCALAPPDATA%\youtube-tools\studio\config.json`(リポジトリの外)
- 動作確認: start.bat → 文字起こし → パック化まで動いた。パックの記録は 16件(戻した 15 + 新しい 1)。画面のエラーの記録・入口のログにエラーなし
- 評価用データ: `E:\Video\切り抜き動画素材\評価用データ\1_JP` の動画 18本(682MB)を `評価用_仮置き` へ移した(上書きなし。1_JP には空のフォルダが残っている)。
  `評価用_仮置き` は 360本(mov 334・mp4 25・mkv 1)・合計 3時間42分01秒(平均 約37秒)
- 未完了・次: push.bat で push(ac231bd とこの記録)。以前の文字起こしと校正・スタジオの解析とマークは戻せない(元の動画があれば作り直せる)。
  「編集」の設定(パックの音量・fps・キー配置など)は初期値に戻っている
- 注意: **Playwright が入っていない**(10-03 に確認。Python 3.10・3.12 のどちらにも無く、`%LOCALAPPDATA%\ms-playwright` も無い。miniconda も無くなり、3.12 は普通の Python)。
  画面のテスト(e2e)と node を使うテスト(`dev/run_editor_suite.py` は Playwright の node を使う)は、`pip install playwright` → `playwright install chromium` をするまで流せない。
  AGENTS.md の「動作環境」の「miniconda の Python 3.12(playwright 入り)」は今の PC と合っていない(入れ直したら直す)。
  PATH の ffmpeg は winget の yt-dlp 用のもの(`...\WinGet\Links\ffmpeg.exe`)が先に見つかる
- 未コミット: なし
