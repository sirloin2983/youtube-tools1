# HANDOVER — 次のセッションへの引き継ぎ(2026-09-27・「編集」の追加機能 ①〜⑦ が終わった)

セッションを切り替えるたびに上書きする。詳しい経緯は `docs/WORKLOG.md`、ルールは `AGENTS.md`、画面の共通のルールは `docs/ui-guidelines.md`、ユーザー向けの使い方はリポジトリ直下の `README.txt`。

## 今の状態
- **「編集」(文字起こし + cut2resolve の統合)**: E1〜E6 は 2026-09-26 に実装済み(`docs/edit-tool-design.md`。細かい決まりは「11」)
- **追加機能 ①〜⑦**(ユーザー 2026-09-26。`docs/edit-tool-design.md` の「12. 追加機能」。ユーザーの回答・実装で決めたことも各項目の下)を**全部実装した**(Claude Code・2026-09-26〜27):
  - ⑥ 「行から」のカットの端を声の止まる所まで広げる(`pack.ROW_EDGE`・「行から ▾」の設定)
  - ④ パックを最小限に(動画・.lua・.drb・.ps1・.bat・友人へ.txt。「予備も入れる」で EDL・予備の手順書・SRT)。cut-plan.json はパックに置かず cut2resolve の作業データ `packs/` に記録(`ytt_core/txindex` が読む)
  - ① Text+ 字幕の見た目 = けいふぉんと・黒い文字・白いふち・黒いふち(スクリプトが値を入れて読み直す。フォントは同梱しない = 規約に再配布の許可が無い)
  - ③-1 「長い区間に文字が少ない(抜けの可能性)」の印・集計 `tools/count_sparse_rows.py`(結果: 評価用 0 行・最近 18 本で 6 行 = 長さの 9.2%。**28 本とも VAD は普通だった**)
  - ② 1つの字幕の最大文字数(縦 16・横 28)・単語の時刻 `transcripts/<id>.words.json`・「今の文書を分け直す」・パックの Text+ 字幕を2段(縦 8・横 14)
  - ⑦ まとめて実行を、スタジオの配信の画面と「編集」の履歴(選んだ文書)からも
  - ③-2 疑わしい所だけ認識し直す(良くなったときだけ置き換える。自動は設定で既定オフ)
  - ⑤(b) 横の素材を縦にする作業は**やらない**(ユーザー決定)。③-3 声の分離は保留(ユーザーが判断)
- 版: 入口 0.10.1・切り抜きスタジオ 0.8.2・編集(文字起こし)0.17.0・cut2resolve 0.12.0・ytt_core 1.2.0・ui-kit v4(**まだ配っていない = push.bat の前**)
- コミット(このセッション): 設計書 de51d2a → ⑥ 5da3609 → ④ 480a0dc → ① 145ed65 → ③-1 82d9c1e → ② 7ef5896 → ⑦ 9b26cc3 → ③-2(この HANDOVER と同じコミット)。**push はまだ**(ユーザーの push.bat)
- 同じ時間に別の Claude Code のセッションが「ホロカラー」(`holo-colors/`。C# の常駐アプリ)を作った(ef083e8)。担当は AGENTS.md の表
- PC に conda-forge の lua(5.5)を入れた(テスト専用。ユーザー承認 09-27)→ Lua のテストも PC で流せる。conda が openssl・VC++ ランタイムも更新した(Python・Playwright は動作確認済み)
- **PC が不安定な可能性**(下の「注意」): テスト中にいろいろなプログラムがランダムに異常終了した。ユーザーに BIOS の更新などを案内した
- ユーザーの指示: **応答は日本語**・**作業中は 10〜20 分ごとに中間報告**・AI のモデルは作業に合わせて使い分ける

## 残りの作業(上から順に)
1. **実機確認(ユーザー)**: push.bat →「すべて終了」→ start-all.bat のあと。各項目の「実機で確かめてほしいこと」は WORKLOG のこのセッションの記録に(⑥ 語頭・語尾の聞き比べ・④ パックの中身と Resolve での取り込み・
   ① Text+ の見た目とマーカー(「反映できなかった」が出たら入力の名前を直す)・② 字幕の文字数と2段・③-2 の6か所・⑦ まとめて実行)と、「11」の E6 の分(60fps → 30fps など)
2. 実機確認の結果の直し(「編集」は Claude Code が担当)
3. ⑥ の決まった余白(後 0.2 秒)は、測った語尾(p50 0.3 秒)より短い → 聞き比べで語尾がまだ切れるなら 0.3 秒に上げる候補(ユーザーの判断)
4. ③-3 声の分離・`transcribe-tool/TRANSCRIPTION_V2_DESIGN.md`(GPT 作)の判断(ユーザー)
5. 「編集」の残り(設計の「10. 未決」。ユーザーが言い出したら): 複数の切り抜きをつなげる画面・字幕のトラックで行の時刻をドラッグで直す
6. 前からの候補: HANDOVER の以前の版の「見直しの残り」「改善の候補」(git の履歴の docs/HANDOVER.md)、精度の基準の記入待ち `docs/accuracy/USER_INPUT.md`

## 保留(ユーザー決定。言い出されたら進める)
- 新着配信の監視(段階5)・7-4 pywebview(窓の試用のあとで判断)
- まとめて実行で最初の文字起こしが遅い(09-26)。E1 の認識ワーカーの直しで治った可能性がある

## 注意: PC が不安定な可能性(2026-09-27 に調べた)
- テスト中に、関係の無いプログラムがランダムに異常終了した: ffmpeg(VP9。1スレッドでも 0xC0000005)・Python 本体の Segmentation fault・Playwright の node・chromium のタブ。流し直すと通る
- Windows のイベントログ(読むだけ): 直近3日で **dwm.exe が 256 回**、Defender・入力サービスなど常駐プログラムも 0xC0000005 で異常終了。WHEA(ハードウェアのエラー)の記録は無し
- CPU は i9-13900KF・**マイクロコード 0x10B**・BIOS 1.10(2022-09)。13/14世代の不安定さ(古いマイクロコードで電圧が高く、劣化が進む。Intel が 0x129 以降で対策)と症状が合う(断定はできない)
- → **テストが1回だけ異常終了で落ちたら、まず流し直す**(コードの不具合と決めつけない)。ユーザーには BIOS の更新(マザーボードのメーカーのサイト)・直らなければ Intel の保証を案内した
- テスト用の webm は `-threads 1`(ffmpeg 9.0.1 の VP9 は複数スレッドで落ちやすい)

## Claude Code(PC)で作業するときの注意
- PC は Windows(`C:\Users\you11\Desktop\youtube-test`)。**git はそのまま使える**: 始める前に `git status`・`git log -5 --oneline`、段ごとに `git add <変えたファイル> docs/WORKLOG.md` → `git commit -m "[Claude] 要約"`。
  **push はユーザーの push.bat**(AI は push しない)。**自分が変えていない未コミットの変更(別のセッション・別の AI)は add しない**(`git add -A` を使わない)
- **テストの流し方(Windows)**: 単体テスト(unittest)には `PYTHONIOENCODING=utf-8` を**付けない**(子プロセスの出力を cp932 で読むテストが落ちる)。画面テスト(e2e)には**付ける**。
  契約テスト `tools/test_resolve_pack_contract.py` は**単独のコマンドで**
- テスト用のサーバーは `CREATE_NEW_PROCESS_GROUP` で起動して Ctrl+Break で止める。Python は miniconda(`C:\Users\you11\miniconda3`。Playwright・lua もここ)
- Playwright 同梱の chromium は H.264 を再生できない(webm VP9 + yuv420p)。CSP のある画面では `page.wait_for_function` が動かない(`evaluate` で待つ `wait_js`)
- **サーバーを動かすテストは先頭で `os.environ.setdefault("YTT_DATA_DIR", "inplace")`**(忘れると本物の作業データを読み書きする)。cut2resolve のパックの記録は inplace だと `cut2resolve/packs/`(.gitignore 済み)
- 起動中の入口・ツールは古いコードのまま。ユーザーに確かめてもらう前に「すべて終了」→ start-all.bat
- `.bat` は CRLF。書き換えるときは改行を合わせ、ASCII だけにする

## 「編集」を直すときの要点(詳しくは `docs/edit-tool-design.md` の「11」と「12」)
- 行の「カット済」の規則は serve.py の `edit_cut_flags` と cut.js の `rowCutFlags` の2か所。文書を書き込む処理を足したら `apply_edit_cuts` を通す
- パックは `cut2resolve/pack.py` だけが作る(Resolve 用の計算・字幕の改行 `resolve_textplus.wrap_caption`・Text+ の見た目 `TEXT_STYLE` も cut2resolve)。変えたら契約テスト(単独)
- パックの有無・パックのフォルダの判定は `ytt_core/txindex`(`pack_info`・`is_pack_dir`・パックを作った記録 `packs/`)の1か所
- 単語の時刻は `transcripts/<id>.words.json`(文書全体。認識と範囲の再認識が書く)。1つの字幕の最大文字数は設定の `subtitle`
- 新しい .js を足したら e2e の写す一覧にも足す(`e2e_edit_*.py` は `e2e_edit_common.py` がまとめて写す)。Text+ の区間・字幕をテストで見るときは `resolve_textplus.read_script_plan`(Lua から読む)

## 次のセッションに貼る指示文(Claude Code 用)
```
リポジトリは今いるフォルダ(C:\Users\you11\Desktop\youtube-test。GitHub: https://github.com/sirloin2983/youtube-tools1)。
docs/HANDOVER.md、AGENTS.md、docs/WORKLOG.md の最後の数件、docs/ui-guidelines.md、docs/edit-tool-design.md(特に「11」と「12. 追加機能」)を必ず先に読んでから始めて。
応答は日本語で、10〜20 分ごとに中間報告して。AI のモデルは作業に合わせて使い分けて(サブエージェントの model を指定)。

■ 現在地(2026-09-27)
- 「編集」の E1〜E6 と、追加機能 ①〜⑦(③-3 は保留・⑤(b) はやらない)は実装・コミット済み(push は私が push.bat で)。
  版: 入口 0.10.1 / スタジオ 0.8.2 / 編集(文字起こし)0.17.0 / cut2resolve 0.12.0 / ytt_core 1.2.0 / ui-kit v4
- PC が不安定な可能性あり(HANDOVER の「注意」)。テストが1回だけ異常終了で落ちたら、まず流し直して

■ やること
- まず私に実機確認の結果を聞いて(HANDOVER の「残りの作業」1)。不具合があれば直す(段ごとにテスト・WORKLOG・git commit "[Claude] 要約"。push はしない)
- 設計の変更・依存の追加・既存機能の削除は、始める前に私に聞いて

■ 保留(こちらから言い出したら進める)
③-3 声の分離、新着配信の監視、pywebview、まとめて実行の最初の文字起こしが遅い件(直った可能性あり)
```
