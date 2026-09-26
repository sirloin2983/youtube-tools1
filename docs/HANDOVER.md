# HANDOVER — 次のセッションへの引き継ぎ(2026-09-26 深夜・「編集」の実装 E1〜E6 が終わった)

セッションを切り替えるたびに上書きする。詳しい経緯は `docs/WORKLOG.md`、ルールは `AGENTS.md`、画面の共通のルールは `docs/ui-guidelines.md`、ユーザー向けの使い方はリポジトリ直下の `README.txt`。

## 今の状態
- **「編集」(文字起こし + cut2resolve の統合)を実装した**(Claude Code・2026-09-26。`docs/edit-tool-design.md` の E1〜E6。細かい決まりは同じ文書の「11」)。
  - 入口のカードは「切り抜きスタジオ」「編集」の2枚。「編集」= transcribe-tool の画面の3つのタブ 1 文字起こし / 2 カット(タイムラインで手で切る)/ 3 パック
  - カット(残す区間)は `transcripts/<id>.edit.json`(youtube-tools-edit/v1・rev と 409)。行の「残す/カット済」はここから決まる(`apply_edit_cuts`)
  - パックは今までどおり `cut2resolve/pack.py` だけが作る(cut2resolve の API の `spec.keeps`)。cut2resolve の画面のファイルは消した(ユーザー決定)。`/cut2resolve/` は「編集」へ転送
  - まとめて実行も、カットを決めてある文書はそのとおりにパックを作る(ユーザー決定)
- **追加機能 ①〜⑦**(ユーザー 2026-09-26。`docs/edit-tool-design.md` の「12. 追加機能」。順番・決定・確認が要る所もそこ)。⑥(行から の端を広げる)と ④(パックを最小限に・記録は cut2resolve の作業データ packs/)は実装済み。次は ③-1 → ② → ①⑤ → ⑦ → ③-2
- 版: 入口 0.10.1・切り抜きスタジオ 0.8.1・編集(文字起こし)0.17.0・cut2resolve 0.12.0・ytt_core 1.2.0・ui-kit v4
- コミット: E1 caf3078 → E2 4f010de → E3 bcda68a → E4 b5302bc → E5 b39c1f3 → E5 追記 ff0037c → E6(この HANDOVER と同じコミット)。**push はまだ**(ユーザーの push.bat)
- テスト: AGENTS.md の表のテストは PC(Windows)で全部通る(WORKLOG の E6)。Node.js が PC に無いので `clip-studio/test_review.cjs`・`transcribe-tool/test_document_save.cjs` は流していない
- PC に Playwright(chromium)を入れた(ユーザー承認 09-26。miniconda の Python)。画面のテストは PC で流せる
- 統合計画: 段階1〜6 は実装済み・実機確認済み。段階7-0〜7-3 と画面の全面見直しは実装済み・**実機確認待ち**。統合計画の正本 = Claude Docs「動画編集ツール 統合計画」
  (「編集」への統合はまだ Claude Docs に書いていない。Cowork で書き足す)
- ユーザーの指示: **作業中は 10〜20 分ごとに中間報告する**。**AI のモデルは作業に合わせて使い分ける**

## 残りの作業(上から順に)
1. **実機確認(ユーザー)**: push.bat →「すべて終了」→ start-all.bat のあと(`docs/edit-tool-design.md` の「11」の E6 の「実機で確かめること」)
   - 入口のカードが2枚・スタジオの書き出しの「編集で開く」で開ける
   - 文字起こし → 2 カット でドラッグ・分割・削る → 3 パック で作ったパックを Resolve に取り込み、区間の端と Text+ 字幕の位置が合う
   - 60fps の元の動画を 30fps のプロジェクトに入れたとき、区間の端が1フレームずれない
   - 初回の文字起こしが以前(502 秒)より速くなったか(認識ワーカーが Windows で標準入力を読んで止まっていた不具合を E1 で直した。遅さの原因だった可能性)
   - 前からのお願い: 段階7(窓で開く・窓の中のリンク・解析の設定の引き継ぎ・隣の窓へ移ったときの保存)、画面の見直し(履歴・案件の一覧・スタジオ)
2. 実機確認の結果の直し(「編集」は Claude Code が担当)
3. 試用の結果で「窓で十分 / 7-4 pywebview / ブラウザに戻す」をユーザーが決める(pywebview は依存の追加なので始める前に確認)
4. 「編集」の残り(設計の「10. 未決」。ユーザーが言い出したら): 複数の切り抜きをつなげる画面(sources を増やす)・字幕のトラックで行の時刻をドラッグで直す
5. 見直しの残り(候補。着手前に相談): ui-kit に引き出し・確認のダイアログ・小さな進み具合の棒を共通の部品として足す、スタジオに配信の日時を残す、
   案件の画面からスタジオの特定の配信を開く(?open=)、スタジオのサーバーのエラーの文言に残る「動画」、行の「要確認」の印(押せる札のまま)
6. 改善の候補: まとめて実行の記録を入口の終了後も残す。`transcribe-tool/index.html` に v0.15.0 の「カットとパック」のカードの CSS(`.tt-cutpack`・`.tt-cp-*` の一部)が残っている(害はない。消すなら使っていないものだけ)
7. ユーザーの確認待ち: 文字起こしの精度改善の設計 `transcribe-tool/TRANSCRIPTION_V2_DESIGN.md`(GPT 作)、精度の基準の記入待ち `docs/accuracy/USER_INPUT.md`

## 保留(ユーザー決定。言い出されたら進める)
- 新着配信の監視(段階5)
- 書き出し中にブラウザのタブが STATUS_ACCESS_VIOLATION で落ちた(09-26 13:32。再現したら、ブラウザ・画面・YouTube 再生中かを聞き、ハードウェアアクセラレーション → 拡張機能の順に切り分け。client-errors.jsonl も見る)
- まとめて実行で最初の文字起こしが遅い(09-26 14:32)。E1 の認識ワーカーの直しで治った可能性がある(上の 1 で確かめる)

## Claude Code(PC)で作業するときの注意
- PC は Windows(`C:\Users\you11\Desktop\youtube-test`)。**git はそのまま使える**: 始める前に `git status`・`git log -5 --oneline`、段ごとに `git add <変えたファイル> docs/WORKLOG.md` → `git commit -m "[Claude] 要約"`。
  **push はユーザーの push.bat**(AI は push しない)。ファイルの移動・改名・削除は `git mv` / `git rm` で、1コミットにまとめて WORKLOG に告知
- **テストの流し方(Windows)**: 単体テスト(unittest)には `PYTHONIOENCODING=utf-8` を**付けない**(子プロセスの出力を cp932 で読むテストが落ちる)。画面テスト(e2e)には**付ける**(▶ などを表示できずに止まる)。
  契約テスト `tools/test_resolve_pack_contract.py` は**単独のコマンドで**(app/test_mount と一緒だと部品の名前が重なって落ちる)
- テスト用のサーバーは `CREATE_NEW_PROCESS_GROUP` で起動して Ctrl+Break(`CTRL_BREAK_EVENT`)で止める(Windows には SIGTERM・SIGKILL が無い)。`/proc` は無い(PowerShell でプロセスを数える)
- Python は `py -3` か `python`(複数入っている可能性。`py -0p` で一覧)。faster-whisper は認識ワーカーの中だけで、編集のサーバーの実装・テストには要らない(疑似モード `TRANSCRIBE_BACKEND=fake` / `worker-fake`)
- Playwright 同梱の chromium は H.264 を再生できない(再生を確かめるテストの動画は webm VP9 + yuv420p)。CSP のある画面では `page.wait_for_function` が動かない(`evaluate` で待つ `wait_js`)
- **サーバーを動かすテストは先頭で `os.environ.setdefault("YTT_DATA_DIR", "inplace")`**(忘れると PC の本物の作業データ `%LOCALAPPDATA%\youtube-tools\` を読み書きする)
- 起動中の入口・ツールは古いコードのまま。ユーザーに確かめてもらう前に「すべて終了」→ start-all.bat。テストでは使用中のポート(入口 8700 など)を使わない
- `.bat` は CRLF(push.bat・install.bat・install-gpu.bat・start-all.bat)。書き換えるときは改行を合わせ、ASCII だけにする

## 「編集」を直すときの要点(詳しくは `docs/edit-tool-design.md` の「11」)
- 行の「カット済」の規則は serve.py の `edit_cut_flags` と cut.js の `rowCutFlags` の2か所(残す区間との重なりが 0.75 フレーム未満ならカット。変えるときは両方と `test_edit.py`)
- 文書を書き込む処理を足したら `apply_edit_cuts` を通す。`PUT /api/edit` は文書の updatedAt を変えない
- 開いたときの下書き・見積もり(`/api/edit/draft`・`/api/edit/preview`)は文字起こしのサーバーで pack.py を一時フォルダで呼ぶ(開いただけで動画の隣にファイルを作らない)
- 新しい .js を足したら既存の e2e の写す一覧にも足す(`e2e_edit_*.py` は `e2e_edit_common.py` がまとめて写す)
- 画面の JS は `cut.js`・`pack-tab.js` を app.js より先に読み、app.js が `EditCut.create(host)`・`EditPack.create(host)` で起動する。cut2resolve の URL は `c2rUrl()` だけで作る

## 注意(前から)
- 画面を直すときは `docs/ui-guidelines.md`(用語集・ヘッダー・ボタンと札・一覧・段階的に見せる・狭い画面)に合わせる。ui-kit は正本を直して `python tools/sync_ui_kit.py`(写し先は clip-studio と transcribe-tool だけ)
- 見本のデータで全画面を動かす: `python tools/demo_env.py --port 8750 --dir <作業フォルダ>`(本物の作業データには触らない。Windows で動くかは未確認)
- パックは `cut2resolve/pack.py` だけが作る。編集の画面・文字起こし側に Resolve 用の計算を書き足さない。変えたら `tools/test_resolve_pack_contract.py`(単独のコマンドで)
- パックの有無の判定は `ytt_core/txindex.pack_info` の1か所(入口の案件・文字起こしの一覧)
- push.bat はコミットの前に tools/push_helper.py check で個人データ・秘密情報を調べて止める。誤検出で止まったら検査(push_helper.py)を直す
- GPT(Codex)がこのフォルダで作業すると `.git\refs\codex\` に壊れた参照が残ることがある → push.bat が `bad object refs/codex/…` で止まったら `rmdir /s /q .git\refs\codex`

## 次のセッションに貼る指示文(Claude Code 用)
```
リポジトリは今いるフォルダ(C:\Users\you11\Desktop\youtube-test。GitHub: https://github.com/sirloin2983/youtube-tools1)。
docs/HANDOVER.md、AGENTS.md、docs/WORKLOG.md の最後の数件、docs/ui-guidelines.md、docs/edit-tool-design.md(特に「11. 実装で決めたこと」)を必ず先に読んでから始めて。
応答は日本語で、10〜20 分ごとに中間報告して。AI のモデルは作業に合わせて使い分けて(サブエージェントの model を指定)。

■ 現在地(2026-09-26 深夜)
- 「編集」(文字起こし + cut2resolve の統合)は E1〜E6 まで実装・コミット済み(push は私が push.bat で)。
  版: 入口 0.10.0 / スタジオ 0.8.1 / 編集(文字起こし)0.16.0 / cut2resolve 0.11.0 / ui-kit v4
- cut2resolve の画面のファイルは消した。まとめて実行もカットのとおりにパックを作る(どちらも私の決定)

■ やること
- まず私に実機確認の結果を聞いて(HANDOVER の「残りの作業」1)。不具合があれば直す(段ごとにテスト・WORKLOG・git commit "[Claude] 要約"。push はしない)
- 設計の変更・依存の追加・既存機能の削除は、始める前に私に聞いて

■ 保留(こちらから言い出したら進める)
新着配信の監視、書き出し中のタブの STATUS_ACCESS_VIOLATION、まとめて実行の最初の文字起こしが遅い件(直った可能性あり)
```
