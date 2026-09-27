# HANDOVER — 次のセッションへの引き継ぎ(2026-09-27・実機の確認のあとの要望が終わった)

セッションを切り替えるたびに上書きする。詳しい経緯は `docs/WORKLOG.md`、ルールは `AGENTS.md`、画面の共通のルールは `docs/ui-guidelines.md` と
`docs/usability-heuristics.md`(Nielsen の 10 の原則)、ユーザー向けの使い方はリポジトリ直下の `README.txt`。

## 今の状態
- 「編集」の E1〜E6(2026-09-26)と追加機能 ①〜⑦(2026-09-26〜27。`docs/edit-tool-design.md` の 12)は実装済み
- **実機の確認のあとの要望**(ユーザー 2026-09-27。`docs/followup-2026-09-27.md`)を全部実装した(Claude Code・2026-09-27):
  1. パックに media フォルダ・友人へ.txt を作らない(手順は「編集」の「Resolve での手順を見る」)・Text+ の重ね順の入力名を Resolve の中で探す(実機で Priority1/2/5 が入らなかった)
  2. 入口が二つにならない(ツールの窓の「入口」は、開いている入口の窓を前に出す)・UI の 10 の原則の資料(画面の変更はしない = Cowork が行う)
  3. 配信者の名前で字幕の文字をメンバーカラーに(パックのタブ・まとめて実行の各入口。`ytt_core/colors.py`)
  4. 出力先に途中のファイルを並べない(`.clip.json`・編集用素材・`.transcript.json` などは「作業用」フォルダへ。`ytt_core/schemas.py` の `WORK_DIR`)
  5. まとめて実行を各段階から(「編集」の題名の行の「まとめて実行 ▾」= 今の文書・スタジオのマークの行の「この後を ▸」= そのマークだけ)
  6. スタジオの ① 探す からもまとめて実行(選んだ配信を「解析から全部」。`POST /api/autorun/start-new`。設計書の 5)
  - 4・5 の細かい決まりは、ユーザーが寝ていたので**質問せずに決めた**(設計書の「実装で決めたこと」。違えば直す)
  - **実機の確認: 問題なし**(ユーザー 2026-09-27)
- ユーザーが保留にしたもの: ⑥ 語頭・語尾の聞き比べ・③-2 の6か所の確認
- 版: 入口 0.10.2・スタジオ 0.8.2・編集 0.17.1・cut2resolve 0.13.0・ytt_core・ui-kit v5(**まだ配っていない = push.bat の前**。今日の変更は全部この版に含めた)
- コミット(今日): 7a1643f(パック・重ね順)→ f4d2d87(入口・原則の資料・設計)→ f503584(配信者の色)→ 8293b27(作業用フォルダ)→ 各段階のまとめて実行(この HANDOVER と同じコミット)。**push はまだ**
- PC が不安定な可能性(下の「注意」)。今日もテストが Playwright の node の異常終了などで何度か落ち、流し直すと通った

## 残りの作業(上から順に)
1. ~~実機の確認(ユーザー)~~ → **2026-09-27 ユーザー「問題ない」**(重ね順・パックの形・配信者の色・入口を前に出す・作業用フォルダ・各段階のまとめて実行)。
   重ね順の入力の名前は決め打ちにしない(今の「`Priority<n>` → 表示名で探す → `PriorityBack<n>`」の方が Resolve の版の違いに強い)
2. **実機の確認(ユーザー)**: スタジオの ① 探す で配信をチェック →「まとめて実行」→「選んだ配信 n 本をまとめて実行」(2026-09-27 に作った。
   「素早く実行」なので置き場所・中身は質問せずに決めた = 設計書の 5「実装で決めたこと」。違えば直す)
3. 保留: ⑥ の聞き比べ(語尾がまだ切れるなら後の余白を 0.3 秒に)・③-2 の6か所・③-3 声の分離・`transcribe-tool/TRANSCRIPTION_V2_DESIGN.md` の判断
4. UI の 10 の原則に沿った画面の見直しは **Cowork**(`docs/usability-heuristics.md` の「気づいたこと」に候補)
5. 前からの候補: 複数の切り抜きをつなげる画面・字幕のトラックで行の時刻をドラッグで直す(設計の「10. 未決」)、精度の基準の記入待ち `docs/accuracy/USER_INPUT.md`

## 保留(ユーザー決定。言い出されたら進める)
- 新着配信の監視(段階5)・7-4 pywebview(窓の試用のあとで判断)

## 注意: PC が不安定な可能性(2026-09-27 に調べた)
- テスト中に、関係の無いプログラムがランダムに異常終了する: ffmpeg・Python 本体・Playwright の node(「module is not defined in ES module scope」・
  「Connection closed while reading from the driver」・「Page crashed」)・chromium。Python の単体テストで「'float' object is not callable」のような、ありえないエラーも1回出た
- dwm.exe が直近3日で 256 回異常終了。CPU は i9-13900KF・マイクロコード 0x10B・BIOS 1.10(2022-09)。13/14世代の不安定さと症状が合う(断定はできない)
- → **テストが1回だけ異常終了・ありえないエラーで落ちたら、まず流し直す**。ユーザーには BIOS の更新・直らなければ Intel の保証を案内した

## Claude Code(PC)で作業するときの注意
- git はそのまま使える: 始める前に `git status`・`git log -5 --oneline`、段ごとに `git add <変えたファイル> docs/WORKLOG.md` → `git commit -m "[Claude] 要約"`。
  **push はユーザーの push.bat**。自分が変えていない未コミットの変更は add しない(`git add -A` を使わない)
- テストの流し方: 単体テスト(unittest)には `PYTHONIOENCODING=utf-8` を付けない・画面テスト(e2e)には付ける。契約テスト `tools/test_resolve_pack_contract.py` は単独で。
  **node は bash から見えない → Playwright 同梱の `C:\Users\you11\miniconda3\Lib\site-packages\playwright\driver\node.exe` で `--test clip-studio/test_review.cjs`**
- **説明文(docstring)にバックスラッシュを書かない**(`作業用\ ` は Python の不正なエスケープの警告 → 将来エラー)。パスの例は `/` で書く
- パッチを当てるときは、書き換える前の文字列がファイルにちょうど1回あることを確かめる(今日の作業はスクラッチの Python スクリプトでこの形にした)
- テスト用のサーバーは `CREATE_NEW_PROCESS_GROUP` で起動して Ctrl+Break で止める。Python は miniconda(`C:\Users\you11\miniconda3`。Playwright・lua もここ)
- Playwright 同梱の chromium は H.264 を再生できない(webm VP9)。CSP のある画面では `page.wait_for_function` が動かない(`evaluate` で待つ `wait_js`)
- サーバーを動かすテストは先頭で `os.environ.setdefault("YTT_DATA_DIR", "inplace")`。画面テストで配信者の色の一覧を使うときは `YTT_HOLO_MEMBERS`(ytt_core を写しても
  リポジトリの `holo-colors/members.json` を読む)
- `.bat` は CRLF・ASCII だけ

## 要点(詳しくは設計書・`docs/followup-2026-09-27.md`)
- 途中のファイルの置き場所の規則は `ytt_core/schemas.py`(`WORK_DIR`・`sidecar_path`・`find_sidecar`)の1か所。cut2resolve は `cut2resolve_core.WORK_DIR`(同じ名前か test_serve が確かめる)
- 名前 → メンバーカラーは `ytt_core/colors.py` の1か所(画面は名前のまま送る)。Text+ の色は `resolve_textplus.text_style`
- 入口へ戻るリンクは `a[data-ui-portal]`(ui-kit v5 の `UIKit.portal`)。窓を前に出すのは `app/appwindow.focus_window`
- パックは `cut2resolve/pack.py` だけが作る(変えたら契約テスト)。画面・API のパックは `readme_file=False`・`plan_file=False`・`backup` は選択
- 行の「カット済」の規則は serve.py の `edit_cut_flags` と cut.js の `rowCutFlags` の2か所

## 次のセッションに貼る指示文(Claude Code 用)
```
リポジトリは今いるフォルダ(C:\Users\you11\Desktop\youtube-test。GitHub: https://github.com/sirloin2983/youtube-tools1)。
docs/HANDOVER.md、AGENTS.md、docs/WORKLOG.md の最後の数件、docs/followup-2026-09-27.md、docs/ui-guidelines.md、docs/usability-heuristics.md を先に読んでから始めて。
応答は日本語で、10〜20 分ごとに中間報告して。

■ 現在地(2026-09-27)
- 実機の確認のあとの要望(パックの形・重ね順・入口が二つ・配信者の色・作業用フォルダ・各段階のまとめて実行)は実装・コミット済み(push は私が push.bat で)。
  版: 入口 0.10.2 / スタジオ 0.8.2 / 編集 0.17.1 / cut2resolve 0.13.0 / ui-kit v5
- PC が不安定な可能性あり(HANDOVER の「注意」)。テストが1回だけ異常終了で落ちたら、まず流し直して

■ やること
- 実機の確認は済み(問題なし)。そのあと作ったスタジオの ① 探す からのまとめて実行(docs/followup-2026-09-27.md の 5)の実機の確認の結果を私に聞いて
- 設計の変更・依存の追加・既存機能の削除は、始める前に私に聞いて
```
