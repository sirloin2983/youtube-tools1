# HANDOVER — 次のセッションへの引き継ぎ(2026-09-30・段0〜3・段7 のあと。次は段4)

セッションを切り替えるたびに上書きする。全体のまとめと文書の索引は `docs/ROADMAP.md`、詳しい経緯は `docs/WORKLOG.md`、ルールは `AGENTS.md`、画面の共通のルールは `docs/spec/ui-guidelines.md` と
`docs/spec/usability-heuristics.md`(Nielsen の 10 の原則)、ユーザー向けの使い方はリポジトリ直下の `README.txt`。

## いまの場所と状態
- 作業フォルダは **`C:\dev\youtube-tools`**(段0 で clone し直した。GitHub: https://github.com/sirloin2983/youtube-tools1)。`Desktop\youtube-test` は古い写し(分かれたまま)。**そこで push.bat を実行しない・そこのファイルを直さない**
  (改名案: `youtube-test_old`。Codex・Claude Code・Cowork の作業フォルダの向け直しが済んだかは未確認)
- GitHub(origin/main)より **2 コミット進んでいる**(`git rev-list --count origin/main..HEAD`。このファイルのコミットが入れば 3 以上)。**push はユーザーが `C:\dev\youtube-tools\push.bat` で行う**(AI は push しない)
- 版(2026-09-30。実物のファイルで確かめた): 入口 0.14.0・スタジオ 0.12.0・編集 0.26.0・cut2resolve 0.15.0・ui-kit v9・ホロカラー 1.3.0(正は各ツールのファイル。`ROADMAP.md` の先頭の行にも同じ)
- 統合計画(`docs/design/integration-plan.md`)は段階0〜7 まで完了。ポートは 8700 で確定。Edge のアプリの窓を既定・新着配信の監視はやらない(09-27 ユーザー決定)
- これからの作業は `docs/ROADMAP.md` の 2(線 A = 段1〜8・線 B = 文字起こしの精度改善)。各段の細かい計画は `docs/plan/`

## 今日(2026-09-30)終わったこと
- 段0 コミット2: docs を `spec/`・`plan/`・`design/`・`archive/` に並べ替え、パスとテストのコマンドを新しい配置に。`C:\dev\youtube-tools` に clone し直して、ユーザーが start.bat の起動を確認
  (残り: 古いフォルダの改名・AI の作業フォルダの向け直し。`docs/plan/phase0-restructure.md`)
- 夜間の見直し(131 件: 高 20・中 61・低 50): 結果は**ユーザーのデスクトップの HTML `夜間の見直しのまとめ_2026-09-30.html` だけ**(リポジトリには無い)。直したものと残りは下の「次にやること」の 3
- 新しい場所で全部のテストを通した(unit・node・e2e すべて。直したものなし。PC の不定の落ちだけ流し直した)
- 段1(小さな直しと安全): B-8 案件の行に「スタジオで開く」・監査 01 引き出しを開いたままの Alt+数字・02/17/18 「声を覚える」の安全・B-9 Shift+右クリック・Windows 以外のテストの skip ＋ 夜間の見直しの2件(スタジオの知らせが消えない・タイムラインのフォーカスの枠)
- 段2(データを失わない): B-4 動画を選び直す・B-6 まとめて実行の記録をファイルに・監査 06/11/13/14(ホーム 0.14.0・編集 0.25.0・ui-kit v9)
- 段3(操作の一貫性): 監査 03/04/05/15/16(編集 0.26.0。元に戻すは新しい方を戻す・1コマは素材の fps・キー表示は配置から)
- 段7(ホロカラーの色の調べ直し): members.json を version 2(1人に複数の色)・小さな四角でコピー・画面から色を直す・字幕の色は主な色(ホロカラー 1.3.0)。86 人を調べ直した
- スタジオの見直しの直し(0.12.0): 終了のとき ffmpeg・yt-dlp を孫ごと止める・書き出しは `.partial.mp4` に書いて仕上がったら置き換える・チャットのキャッシュに合計 1GB の上限
- ホロカラーの e2e(本物のキー入力)を単独で流して 24 件すべて通過
- キーの件の決定: 校正の S/W/Q と 2 カットの S/Q/W が同じキーで別の意味 → **現状維持**(ガイドライン 2-3 に例外として記載)
- ホロカラー: 非公式 wiki の早見表(公式サイトの画像・ブライト衣装・ペンライト)と照合し、85 人に 339 色を 2 つ目以降として追加(主な色は変えない。medium 125・low 214。魔乃アロエだけ見つからず)。コミット 71597ea。記録は `docs/design/holo-colors-research.md`

## 次にやること(順に)
1. **線 A 段4**(パックの表示と出力を一致。`docs/plan/phase4-pack-consistency.md`。監査 07・08・09・10・12 の残り)→ 段5(見せ方をそろえる)→ 段6(編集の機能を足す)→ 段8(複数の切り抜きをつなげる。優先度 低)。
   計画の行番号は 09-29 時点なので、始める前に今のコードで読み直す。版は実物から上げる(段ごとに serve.py・画面・README の3か所)
2. **線 B**(精度改善)は**ユーザーの評価用の校正と `docs/plan/accuracy/USER_INPUT.md` の記入待ち**。AI が先にやれるのは段1 呼び名(効果の判定は評価セットのあと)。線 A と `editor/serve.py`・`app.js` が重なるので同時に進めない
3. **夜間の見直しの「高」でまだ直していないもの**(設計の判断が要るので、始める前にユーザーに聞くか、保留にして WORKLOG に書く):
   - 編集のワーカー待ちに時限が無い(`editor/serve.py` の認識ワーカーの readline。ワーカーが黙ると待ちが全部止まり SLOTS を持ったまま他のツールを塞ぐ。案: 読み取り専用のスレッド + `queue.get(timeout)`)
   - 作業データの置き場所の求め方が 3 通り(`home/cases.py`・`editor/serve.py`・`studio/serve.py`。`ytt_core/txindex.py` にも別の書き方。案: 各ツールが起動時に決めた場所を ytt_core の1か所に登録して、そこから読む)
   - パックの「動画のファイル名に日本語」の注意が毎回出て、従うと紐づけが切れる(`cut2resolve/cut2resolve_core.py` の注意・`studio/exporter.py`。案 (a) パックの中の動画だけ ASCII 名に置き換える / (b) EDL を使わないときは出さない。(a)(b) を決めてもらう)
   - 確かめ済み: 子プロセスの後始末・知らせが消えない・フォルダの整理は直した。**AI 向け資料の版の食い違いは ROADMAP が「正は各ファイル」にして直った**。
     残りの確認: `AGENTS.md` の「いま進行中なのは文字起こしの精度改善」が線 A/B の書き分けを反映しているか(古ければ ROADMAP の 2 への参照に直す)・`editor/AGENTS.md` 先頭の版
   - 見直しの「中」「低」はまとめの HTML を見る。段5(見せ方)・段4 と重なるものはその段で一緒に直す
4. ホロカラー 1.3.0 の実機の確認(1.2.1 の exe で新しい members.json が読める・札の小さな四角・「色を直す…」・DPI 125%/150%)。WORKLOG の段7 の記録にある

## ユーザーが実機で確かめること
**`docs/ROADMAP.md` の 3 に一本化**(段1・段2・段3・スタジオ 0.12.0 の分がある。ここに写さない)。ホロカラー 1.3.0 の実機の確認は `docs/WORKLOG.md` の「段7 7-3(全員を調べ直した)・7-8」の記録にある
(1.2.1 の exe に新しい members.json を差し替えて起動できる・小さな四角・「色を直す…」・DPI 125%/150%)。起動中の入口は古いコードのままなので、「すべて終了」→ start.bat で起動し直してもらう。

## 決めてもらったこと(2026-09-30)
- キー: 校正と 2 カットで同じキーの意味が違う件(S・W・Q)は**現状維持**。今後、両方にあるキーは同じ意味にする(例外は既存の S・W・Q だけ)
- ホロカラーの色: **迷った候補は全部入れる**(主な色は今のまま・2つ目以降に足す)。食い違いの4人の主な色・ペンライトの色・FUWAMOCO の2つ目の色の扱いは `docs/design/holo-colors-research.md` の「ユーザーに聞くこと」
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
2. git status と git log -5 --oneline(自分が変えていない未コミットの変更は他の AI の作業途中 = 上書き・add しない。
   ホロカラーの候補の色を足す作業(holo-colors/members.json・docs/design/holo-colors-research.md)が途中の可能性あり。WORKLOG の末尾で終わったか確かめる)
3. 版を実物のファイルで確かめる(入口 0.14.0 / スタジオ 0.12.0 / 編集 0.26.0 / cut2resolve 0.15.0 / ui-kit v9 / ホロカラー 1.3.0 のはず)

■ 現在地(2026-09-30)
- 段0(フォルダの整理)・段1・段2・段3・段7 が済み、スタジオは 0.12.0(夜間の見直しの直し)。GitHub より 2 コミット以上進んでいる。push は私が push.bat でやる(AI は push しない)
- キーの意味がタブで違う件は現状維持(ガイドラインに例外)。ホロカラーの色は迷った候補を全部入れる
- 線 B(精度改善)は私の評価用の校正待ち。PC が不安定な可能性あり(HANDOVER の「注意」)。テストが1回だけ異常終了で落ちたら、まず流し直して

■ やること
- 線 A の段4 から始める(docs/plan/phase4-pack-consistency.md。4-1 → 4-2 → 4-3 → 4-4 → 4-5)。始める前に計画の行番号を今のコードで確かめ直す。段5・段6・段8 はそのあと(段3〜6 は editor/ が重なるので並列にしない)
- 夜間の見直しの「高」の残り(HANDOVER の「次にやること」の 3: ワーカー待ちの時限・作業データの置き場所の求め方・パックの日本語ファイル名の注意)は、段の切れ目で扱う。設計の判断が要るので、決められなければ保留にして WORKLOG に書く
- 分けられる作業(担当するファイルが重ならない調べもの・直し)はサブエージェントで並列に。モデルは難しさで選ぶ(探す・数える = Haiku、決まった規則の直しとテスト = Sonnet、設計の判断・原因不明・影響が広い部品 = Opus)。
  選んだモデルと理由は報告に1行。まとめ役が最後に全体のテストと境目の漏れを確かめる。WORKLOG は追記の直前に git diff で他の未コミットの差分を確かめる
- 項目ごとにコミット(`[Claude] 要約`)。段の終わりに版を上げ、ROADMAP の段の状態と「3. 実機で確かめること」を直す
- e2e は PYTHONIOENCODING=utf-8 を付けて1本ずつ。ホロカラーの e2e はほかのテストと同時に流さない

■ 私がいないとき(質問できないとき)の決まり
- 計画(docs/plan/)に書いてある範囲は質問せずに進める
- 計画に無い判断(設計の変更・依存の追加・費用・既存機能の削除)は実装せずに保留にして、WORKLOG に「保留: 内容・選択肢・おすすめ」を書いて次の項目へ進む
- 実機でしか確かめられないものは ROADMAP の 3 に足す。勝手に終わったことにしない
```
