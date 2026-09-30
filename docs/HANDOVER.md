# HANDOVER — 次のセッションへの引き継ぎ(2026-10-01・段0〜4・段7・友人からの依頼の受付・ホロカラー 1.4.1・夜間の見直しの「高」3件・段5・段6 のあと。次は段9)

セッションを切り替えるたびに上書きする。全体のまとめと文書の索引は `docs/ROADMAP.md`、詳しい経緯は `docs/WORKLOG.md`、ルールは `AGENTS.md`、画面の共通のルールは `docs/spec/ui-guidelines.md` と
`docs/spec/usability-heuristics.md`(Nielsen の 10 の原則)、ユーザー向けの使い方はリポジトリ直下の `README.txt`。

## いまの場所と状態
- 作業フォルダは **`C:\dev\youtube-tools`**(段0 で clone し直した。GitHub: https://github.com/sirloin2983/youtube-tools1)。`Desktop\youtube-test` は古い写し(分かれたまま)。**そこで push.bat を実行しない・そこのファイルを直さない**
  (改名案: `youtube-test_old`。Codex・Claude Code・Cowork の作業フォルダの向け直しが済んだかは未確認)
- **すべてコミット済み・push 済みで origin/main と一致**(2026-10-01。HEAD a60dacc。`git status` はきれい)。**push はユーザーが `C:\dev\youtube-tools\push.bat` で行う**(AI は push しない)
- 版(2026-10-01。実物のファイルで確かめた): 入口 0.19.0・スタジオ 0.13.0・編集 0.30.0・cut2resolve 0.16.0・ui-kit v9・ホロカラー 1.4.1・送るアプリ(`request-sender/`)1.2.0(正は各ツールのファイル。`ROADMAP.md` の先頭の行にも同じ)
- 統合計画(`docs/design/integration-plan.md`)は段階0〜7 まで完了。ポートは 8700 で確定。Edge のアプリの窓を既定・新着配信の監視はやらない(09-27 ユーザー決定)
- これからの作業は `docs/ROADMAP.md` の 2(線 A = 段1〜8・線 B = 文字起こしの精度改善)。各段の細かい計画は `docs/plan/`

## 終わったこと(2026-09-30〜10-01)
- 段0 コミット2: docs を `spec/`・`plan/`・`design/`・`archive/` に並べ替え、パスとテストのコマンドを新しい配置に。`C:\dev\youtube-tools` に clone し直して、ユーザーが start.bat の起動を確認
  (残り: 古いフォルダの改名・AI の作業フォルダの向け直し。`docs/plan/phase0-restructure.md`)
- 夜間の見直し(131 件: 高 20・中 61・低 50): 結果は**ユーザーのデスクトップの HTML `夜間の見直しのまとめ_2026-09-30.html` だけ**(リポジトリには無い)。直したものと残りは下の「次にやること」の 3
- 段1(小さな直しと安全)・段2(データを失わない。ホーム 0.14.0・編集 0.25.0・ui-kit v9)・段3(操作の一貫性。編集 0.26.0)・段7(ホロカラーの色の調べ直し)。中身は `ROADMAP.md` の 2 の表
- スタジオの見直しの直し(0.12.0): 終了のとき ffmpeg・yt-dlp を孫ごと止める・書き出しは `.partial.mp4` に書いて仕上がったら置き換える・チャットのキャッシュに合計 1GB の上限
- キーの件の決定: 校正の S/W/Q と 2 カットの S/Q/W が同じキーで別の意味 → **現状維持**(ガイドライン 2-3 に例外として記載)
- **友人からの依頼の受付**(`docs/design/friend-intake.md`): ホーム 0.15.0 → 0.15.1(desktop.ini を断らない)→ 0.16.0(友人が ①全自動 / ②文字起こしまで / ③解析まで を選ぶ。送るアプリ 1.1.0)→
  0.17.0(既定はカットしない・音量 30%・① はパックを1本ずつ Dropbox の 出力\ へ・受け取ったら Dropbox から消す・送るアプリ 1.2.0・`start-background.bat` と `home/start_hidden.vbs` で裏から自動起動)。
  **実機(ユーザーの PC)で、友人のアプリから送った動画が受け付けられて通しで動いた**。ユーザーの PC のスタートアップに「youtube-tools (裏で起動)」を置いた(やめるときは shell:startup で消す)
- ホロカラー: 1.3.0 → 1.3.1(衣装の色・ペンライトの色を外した(ユーザー決定)・色の四角を大きく)→ **1.4.0**(札 = 名前 + 色の帯・マイワード・お気に入り・最近使ったもの・並べ替え(ドラッグ / Alt+矢印)・メンバーに色を追加。
  e2e 24 件 OK)。主な色は誰も変えていない。早見表の3色(ホロジュール・公式サイトの濃い色と縁)は全員そろえた。データは作業データの my-words.json・settings.json の favorites・recent が増えた
- ホロカラーの e2e(本物のキー入力)を単独で流して 24 件すべて通過

## 次にやること(順に)
1. **線 A 段9**(運用の安定化。`docs/plan/line-a-after-phase8.md` の 5 から細かい計画 `docs/plan/phase9-*.md` を先に作る。「決めてもらうこと」= 片付けの対象・依頼の受付の上限)→ 段10 → 線 B 段1・2 → 線 C → 12 → 8 → 15。段4〜6 は 10-01 に済み(編集 0.30.0・ホーム 0.19.0・スタジオ 0.13.0・cut2resolve 0.16.0)。
   計画の行番号は 09-29 時点なので、始める前に今のコードで読み直す。版は実物から上げる(段ごとに serve.py・画面・README の3か所)
2. **線 B**(精度改善)は**ユーザーの評価用の校正と `docs/plan/accuracy/USER_INPUT.md` の記入待ち**。AI が先にやれるのは段1 呼び名(効果の判定は評価セットのあと)。線 A と `editor/serve.py`・`app.js` が重なるので同時に進めない
3. 夜間の見直しの「高」の残り 3 件は **2026-10-01 に決めて直した**(WORKLOG の同じ日): ① 認識ワーカーの待ちに時限(20 分。`WORKER_SILENCE_TIMEOUT`)/ ② 作業データの置き場所の求め方を `ytt_core/datadir.resolve`・`register` の1か所に / ③ 「動画のファイル名に日本語」の注意は EDL を書くときだけ(cut2resolve 0.15.1)。 残りの確認: `AGENTS.md` の「いま進行中」の行は ROADMAP の 2 への参照に直した(10-01)。見直しの「中」「低」はユーザーのデスクトップのまとめの HTML(リポジトリには無い)。段5(見せ方)と重なるものはその段で一緒に直す
4. **実際の Dropbox での依頼の受付の確認**(URL の依頼・150MB 超の動画・受け取り後の削除(files/delete_v2。日本語名も)・ダウンロードの続き(Range)・権限不足のエラー・content_hash)。
   **1.0.0 の鍵では受け取れない**(権限 3 つの鍵で作り直した zip を渡す)
5. ホロカラー 1.4.1 の実機の確認(友人の PC・DPI 125%/150%・古い exe に新しい members.json を差し替えて読めるか)

## ユーザーが実機で確かめること
**`docs/ROADMAP.md` の 3 に一本化**(段1・段2・段3・スタジオ 0.12.0・依頼の受付・ホロカラー 1.4.1 の分がある。ここに写さない)。
起動中の入口は古いコードのままなので、「すべて終了」→ start.bat で起動し直してもらう(0.17.0 は裏で動いている。`start-background.bat` の裏の起動も、終了は入口の「すべて終了」)。

## 決めてもらったこと(2026-09-30)
- キー: 校正と 2 カットで同じキーの意味が違う件(S・W・Q)は**現状維持**。今後、両方にあるキーは同じ意味にする(例外は既存の S・W・Q だけ)
- ホロカラーの色: **迷った候補は全部入れる**(主な色は今のまま・2つ目以降に足す)。**ペンライトの色・衣装の色は外した**(ユーザー決定 09-30)。食い違いの4人の主な色・FUWAMOCO の2つ目の色の扱いは `docs/design/holo-colors-research.md` の「ユーザーに聞くこと」
- 友人からの依頼: 友人が送るたびに ①全自動 / ②文字起こしまで / ③解析まで を選ぶ(2026-10-01)。全部のパックの既定はカットしない・音量 30%。友人が受け取ったら Dropbox から消す
- 段2: 動画の付け替え(選び直し)で**断る場所は編集の作業データだけ**(スタジオの書き出しの記録など他の場所はそのまま)
- 2026-09-29 の決定(一覧): `docs/ROADMAP.md` の 5

## 注意: PC が不安定な可能性(2026-09-27 に調べた)
- テスト中に、関係の無いプログラムがランダムに異常終了する(ffmpeg・Python・Playwright の node・chromium)。dwm.exe が 3 日で 256 回異常終了。
  i9-13900KF・マイクロコード 0x10B・BIOS 1.10(2022-09)。13/14世代の不安定さと症状が合う(断定はできない)。BIOS の更新を案内済み(やったかは未確認)
- → **テストが1回だけ異常終了・ありえないエラーで落ちたら、まず流し直す**。今日もこの形で落ちた: chromium の `Target crashed`・ffmpeg の 0xC0000005・`ConnectionAbortedError`(10053)・Playwright の `Connection closed while reading from the driver`
- **Claude Code のアプリがときどき落ちる(セッションが途中で切れる)**: 項目ごとにコミットする。再開は「続行」で止まった所から。WORKLOG の「未コミット」と `git status` を突き合わせる
- 過去の事故: 2026-09-23、Claude が配った zip で GPT の変更が上書きされて消えた(`docs/WORKLOG.md`)。**古い控えからのファイル丸ごとの上書き・zip 配布はしない**。
  段0 のコミット2 では、Claude Code が検査とコミットを `;` でつないだため、検査が止めた表示のまま push まで進んだ(`docs/archive/` の誤検出。以後、検査は `&&` でつなぐ)

## Claude Code(PC)で作業するときの注意
- git はそのまま使える: 始める前に `git status`・`git log -5 --oneline`、項目ごとに `git add <変えたファイル> docs/WORKLOG.md` → `git commit -m "[Claude] 要約"`。
  **push はユーザーの push.bat**。自分が変えていない未コミットの変更は add しない(`git add -A` を使わない)
- **同じファイルを触る段は並列にしない**(段3〜6 は `editor/` が重なる。段4 は `editor/pack-tab.js`・`cut2resolve/`、段5 は `home/`・`studio/`・`editor/`、段6 は `editor/app.js`・`cut.js`)。
  並列にするときは担当のファイルを分ける。**WORKLOG は追記の直前に `git diff docs/WORKLOG.md` で他の未コミットの差分を確かめる**(ほかの AI の追記を巻き込まない・上書きしない)
- テストの流し方: 単体テスト(unittest)には `PYTHONIOENCODING=utf-8` を付けない・**画面テスト(e2e)には付ける**(付けないと `e2e_portal`・`e2e_window` は cp932 の UnicodeEncodeError)。e2e は **1 本ずつ**流す。
  契約テスト `dev/tests/test_resolve_pack_contract.py` は単独で。**`holo-colors/tests/e2e_holo_colors.py` は本物のキー入力を送るので、ほかのテスト・エージェントと同時に流さない**(前面の窓を取り合って落ちる。段7 のときに2回落ちた)
- **node は bash から見えない → Playwright 同梱の `C:\Users\you11\miniconda3\Lib\site-packages\playwright\driver\node.exe` で `--test studio/tests/test_review.cjs`(と `editor/tests/test_document_save.cjs`)**
- `holo-colors\build.bat` は Git Bash からだと「認識されない」→ PowerShell から `cmd /c ".\build.bat < NUL"`
- **説明文(docstring)にバックスラッシュを書かない**(`作業用\ ` は Python の不正なエスケープの警告 → 将来エラー)。パスの例は `/` で書く
- パッチを当てるときは、書き換える前の文字列がファイルにちょうど1回あることを確かめる(スクラッチの Python スクリプトでこの形にした)
- テスト用のサーバーは `CREATE_NEW_PROCESS_GROUP` で起動して Ctrl+Break で止める。Python は miniconda(`C:\Users\you11\miniconda3`。Playwright・lua もここ)
- Playwright 同梱の chromium は H.264 を再生できない(webm VP9)。CSP のある画面では `page.wait_for_function` が動かない(`evaluate` で待つ `wait_js`)
- サーバーを動かすテストは先頭で `os.environ.setdefault("YTT_DATA_DIR", "inplace")`。画面テストで配信者の色の一覧を使うときは `YTT_HOLO_MEMBERS`(ytt_core を写しても
  リポジトリの `holo-colors/members.json` を読む)
- `.bat` は CRLF・ASCII だけ。ui-kit を直したら `python dev/sync_ui_kit.py`(写しは手で直さない)
- サブエージェントで並列に進めるときは、モデルを難しさで選ぶ(`AGENTS.md`。探す・数える = Haiku、決まった規則の直しとテスト = Sonnet、設計の判断・原因不明・影響が広い部品 = Opus)。選んだモデルと理由は報告に1行

## 要点(詳しくは設計書・`docs/archive/followup-2026-09-27.md`)
- 途中のファイルの置き場所の規則は `ytt_core/schemas.py`(`WORK_DIR`・`sidecar_path`・`find_sidecar`)の1か所。cut2resolve は `cut2resolve_core.WORK_DIR`(同じ名前か test_serve が確かめる)
- 名前 → メンバーカラーは `ytt_core/colors.py` の1か所(画面は名前のまま送る。members.json の `colors` と作業データの `member-colors.json` を読み、使う側は `hex` = 主な色だけ)。Text+ の色は `resolve_textplus.text_style`
- 入口へ戻るリンクは `a[data-ui-portal]`(ui-kit の `UIKit.portal`)。窓を前に出すのは `home/appwindow.focus_window`
- パックは `cut2resolve/pack.py` だけが作る(変えたら契約テスト)。画面・API のパックは `readme_file=False`・`plan_file=False`・`backup` は選択
- 行の「カット済」の規則は serve.py の `edit_cut_flags` と cut.js の `rowCutFlags` の2か所
- キー配置は ui-kit の `UIKit.keymap`・`UIKit.keys.derived`(派生キー)の1か所。行の title・キー帯は配置から出す(`renderKeyUI`)

## 次のセッションに貼る指示文(Claude Code 用)
```
リポジトリは今いるフォルダ(C:\dev\youtube-tools。Desktop\youtube-test は古い写しなので触らない・そこで push.bat を実行しない。GitHub: https://github.com/sirloin2983/youtube-tools1)。
応答は日本語で、10〜20 分ごとに中間報告して(残り時間の目安も)。

■ 最初に読む(この順)
1. AGENTS.md → docs/ROADMAP.md(全体・段の状態・「3. 実機で確かめること」・5 の決定)→ docs/HANDOVER.md → docs/WORKLOG.md の末尾の数件
2. git status と git log -5 --oneline(自分が変えていない未コミットの変更は他の AI の作業途中 = 上書き・add しない)
3. 版を実物のファイルで確かめる(入口 0.19.0 / スタジオ 0.13.0 / 編集 0.30.0 / cut2resolve 0.16.0 / ui-kit v9 / ホロカラー 1.4.1 / 送るアプリ 1.2.0 のはず)

■ 現在地(2026-10-01)
- 段0(フォルダの整理)・段1〜段6・段7 が済み(段6 = 編集 0.30.0・cut2resolve 0.16.0。行の後の余白・字幕の段で行の時刻を直す/分ける)、ホーム 0.19.0・スタジオ 0.13.0。友人からの依頼の受付(ホーム 0.17.0・送るアプリ 1.2.0)とホロカラー 1.4.1 も入った。すべてコミット・push 済みで origin/main と一致(HEAD a60dacc)。push は私が push.bat でやる(AI は push しない)
- 依頼の受付は友人のアプリから送った動画 1 本で通しを確認済み。実際の Dropbox で未確認の項目は ROADMAP の 3(URL の依頼・150MB 超・受け取り後の削除・Range・権限不足・content_hash)
- キーの意味がタブで違う件は現状維持(ガイドラインに例外)。ホロカラーの色は迷った候補を全部入れた(ペンライト・衣装の色は外した)
- 線 B(精度改善)は私の評価用の校正待ち。PC が不安定な可能性あり(HANDOVER の「注意」)。テストが1回だけ異常終了で落ちたら、まず流し直して

■ やること
- 線 A の段9(運用の安定化)から。まず docs/plan/line-a-after-phase8.md の 5 を読んで細かい計画 docs/plan/phase9-*.md を作り、「決めてもらうこと」を私に聞いてから実装。段4〜6 と夜間の見直しの「高」3件は 10-01 に済み(WORKLOG)。
  私が実機で依頼の受付を確かめる話を先にしたら、ROADMAP の 3 の「依頼の受付」の項目から進める(不具合が出たら段4 より先に直す)
- 夜間の見直しの「中」「低」はまとめ(私のデスクトップの HTML)を見て、段9・段15 と重なるものは一緒に直す
- 分けられる作業(担当するファイルが重ならない調べもの・直し)はサブエージェントで並列に。モデルは難しさで選ぶ(探す・数える = Haiku、決まった規則の直しとテスト = Sonnet、設計の判断・原因不明・影響が広い部品 = Opus)。
  選んだモデルと理由は報告に1行。まとめ役が最後に全体のテストと境目の漏れを確かめる。WORKLOG は追記の直前に git diff で他の未コミットの差分を確かめる
- 項目ごとにコミット(`[Claude] 要約`)。段の終わりに版を上げ、ROADMAP の段の状態と「3. 実機で確かめること」を直す
- e2e は PYTHONIOENCODING=utf-8 を付けて1本ずつ。ホロカラーの e2e はほかのテストと同時に流さない

■ 私がいないとき(質問できないとき)の決まり
- 計画(docs/plan/)に書いてある範囲は質問せずに進める
- 計画に無い判断(設計の変更・依存の追加・費用・既存機能の削除)は実装せずに保留にして、WORKLOG に「保留: 内容・選択肢・おすすめ」を書いて次の項目へ進む
- 実機でしか確かめられないものは ROADMAP の 3 に足す。勝手に終わったことにしない
```
