# HANDOVER — 次のセッションへの引き継ぎ(2026-09-26 夜・「編集」の実装を Claude Code へ)

セッションを切り替えるたびに上書きする。詳しい経緯は `docs/WORKLOG.md`、ルールは `AGENTS.md`、画面の共通のルールは `docs/ui-guidelines.md`、ユーザー向けの使い方はリポジトリ直下の `README.txt`。

## 今の状態
- GitHub の main = 62ab367(段階7-0〜7-3 と、3ツール・入口の画面の全面見直しまで)。
  この後の未コミット = 「編集」の設計書と画面イメージ(`docs/edit-tool-design.md`・`docs/mockups/`)と、この HANDOVER・WORKLOG・AGENTS.md(担当表に1行)
- 版: 入口 0.9.0・切り抜きスタジオ 0.8.0・文字起こし 0.15.0・cut2resolve 0.10.0・ui-kit v3・ytt_core(datadir・jobs・txindex(pack_info))
- **新しい方針(ユーザー決定 09-26)**: 文字起こしツールと cut2resolve を1つのツール「**編集**」にする。3つのタブ 1 文字起こし / 2 カット(ふつうの編集ソフトのようなタイムラインで手で切る)/ 3 パック。
  範囲はカットと字幕まで。切り抜きは基本1本(あとで複数をつなげられる形に)。文字起こしの無い動画も使える。
  設計・画面イメージはユーザー承認済み(「このイメージでいい」)→ `docs/edit-tool-design.md`・`docs/mockups/edit-*.png`
- **実装は Claude Code(PC)で行う**(ユーザー決定 09-26)。Cowork は設計と画面イメージまでで、実装には手を付けていない
- 担当: 統合作業・cut2resolve・文字起こしツール(= 編集)・3ツールと入口の画面(ui-kit を含む)は Claude(Claude Code も Claude。他の AI は触らない)
- 統合計画: 段階1〜6 は実装済み・実機確認済み。段階7-0〜7-3 と画面の全面見直しは実装済み・**実機確認待ち**。統合計画の正本 = Claude Docs「動画編集ツール 統合計画」
  (「編集」への統合はまだ Claude Docs に書いていない。Cowork で書き足す)
- ユーザーの指示: **作業中は 10〜20 分ごとに中間報告する**。**AI のモデルは作業に合わせて使い分ける**(監査・定型の実装・テストの実行は Sonnet、難しい実装・設計・結合は Opus など)

## 残りの作業(上から順に)
1. **「編集」の実装**(Claude Code): `docs/edit-tool-design.md` の「7. 実装の段取り」E1 サーバー → E2 画面の骨組み → E3 カット → E4 パック → E5 入口・ほか → E6 仕上げ。
   段ごとにテストを通し、WORKLOG に書き、コミット(`[Claude] 要約`)し、ユーザーに中間報告。「9. リスク・エッジケース」は全部扱う。「10. 未決」は途中でユーザーに聞く
   - 始める前に、下の 2 の実機確認の結果をユーザーに聞く(文字起こしの「カットとパック」まわりの不具合は、編集で置き換える部分なら E3・E4 の中で直す。それ以外は先に直す)
2. 実機確認(ユーザー): push.bat →「すべて終了」→ start-all.bat のあと
   - 文字起こし: 履歴(配信ごとのまとまり・だれの/いつの/校正の進み具合・絞り込みと並び替え)、校正画面の「カットとパック」(パック → Resolve で読めるか・上書きの確認)
   - 案件の一覧(1件1行・開く・並び替え・まとめ方・次にやること・まとめて実行)、スタジオ(① の事務所のチェック・③ の配信の選択・書き出しの位置)、cut2resolve(隣の字幕の提案)
   - 段階7 の残り: 入口の「窓で開く(試用)」、窓の中のリンク、解析の設定の引き継ぎ、隣の窓へ移ったときの保存
3. 試用の結果で「窓で十分 / 7-4 pywebview / ブラウザに戻す」をユーザーが決める(pywebview は依存の追加なので始める前に確認)
4. 見直しの残り(候補。着手前に相談): ui-kit に引き出し・確認のダイアログ・小さな進み具合の棒・キーの手がかりの帯を共通の部品として足す(今は各ツールにある。編集のタブで使うなら E2 で一緒に)、
   スタジオに配信の日時を残す、案件の画面からスタジオの特定の配信を開く(?open=)、スタジオのサーバーのエラーの文言に残る「動画」、行の「要確認」の印(押せる札のまま)
5. 改善の候補: まとめて実行の記録を入口の終了後も残す
6. ユーザーの確認待ち: 文字起こしの精度改善の設計 `transcribe-tool/TRANSCRIPTION_V2_DESIGN.md`(GPT 作)、精度の基準の記入待ち `docs/accuracy/USER_INPUT.md`

## 保留(ユーザー決定。言い出されたら進める)
- 新着配信の監視(段階5)
- 書き出し中にブラウザのタブが STATUS_ACCESS_VIOLATION で落ちた(09-26 13:32。再現したら、ブラウザ・画面・YouTube 再生中かを聞き、ハードウェアアクセラレーション → 拡張機能の順に切り分け。client-errors.jsonl も見る)
- まとめて実行で最初の文字起こしが遅い(09-26 14:32。large-v3 の最初の読み込みを疑うが未確定。再現したら「文字起こし」の段の表示と transcribe の serve.log を見る)

## Claude Code(PC)で作業するときの注意
- PC は Windows(`C:\Users\you11\Desktop\youtube-test`)。**git はそのまま使える**: 始める前に `git status`・`git log -5 --oneline`、段ごとに `git add <変えたファイル> docs/WORKLOG.md` → `git commit -m "[Claude] 要約"`。
  **push はユーザーの push.bat**(AI は push しない。push.bat はコミット済みで未送信のものも送る)
- Cowork 向けの回り道(`tools/removals.txt` に消すファイルを書く・書き込んだら読み直す)は要らない。ファイルの移動・改名・削除は `git mv` / `git rm` で、1コミットにまとめて WORKLOG に告知(AGENTS.md)
- Python は `py -3` か `python`(複数入っている可能性。`py -0p` で一覧)。faster-whisper は認識ワーカーの中だけで、編集のサーバーの実装・テストには要らない(疑似モード `TRANSCRIBE_BACKEND=fake` / `worker-fake`)
- 画面のテストは Playwright(chromium)と ffmpeg が要る。**PC に Playwright が無ければ、入れる前にユーザーに確認**(依存の追加)。Playwright 同梱の chromium は H.264 を再生できない(再生を確かめるテストの動画は webm)
- **サーバーを動かすテストは先頭で `os.environ.setdefault("YTT_DATA_DIR", "inplace")`**(忘れると PC の本物の作業データ `%LOCALAPPDATA%\youtube-tools\` を読み書きする)
- 起動中の入口・ツールは古いコードのまま。ユーザーに確かめてもらう前に「すべて終了」→ start-all.bat。テストでは使用中のポート(入口 8700 など)を使わない
- `.bat` は CRLF(push.bat・install.bat・install-gpu.bat・start-all.bat)。書き換えるときは改行を合わせ、ASCII だけにする(push.bat の先頭の注意)
- モデルの使い分け(ユーザーの指示): サブエージェントに任せるときは、テストの実行・定型の書き換え・調べ物は Sonnet(または Haiku)、タイムラインの実装・設計の判断・結合と見直しは Opus

## 注意(前から)
- 画面を直すときは `docs/ui-guidelines.md`(用語集・ヘッダー・ボタンと札・一覧・段階的に見せる・狭い画面)に合わせる。ui-kit は正本を直して `python tools/sync_ui_kit.py`
- 見本のデータで全画面を動かす: `python tools/demo_env.py --port 8750 --dir <作業フォルダ>`(本物の作業データには触らない。Windows で動くかは未確認)
- パックは `cut2resolve/pack.py` だけが作る。編集の画面・文字起こし側に Resolve 用の計算を書き足さない。変えたら `tools/test_resolve_pack_contract.py`(**単独のコマンドで**)
- パックの有無の判定は `ytt_core/txindex.pack_info` の1か所(入口の案件・文字起こしの一覧)
- push.bat はコミットの前に tools/push_helper.py check で個人データ・秘密情報を調べて止める。誤検出で止まったら検査(push_helper.py)を直す
- GPT(Codex)がこのフォルダで作業すると `.git\refs\codex\` に壊れた参照が残ることがある → push.bat が `bad object refs/codex/…` で止まったら `rmdir /s /q .git\refs\codex`

## 次のセッションに貼る指示文(Claude Code 用)
```
リポジトリは今いるフォルダ(C:\Users\you11\Desktop\youtube-test。GitHub: https://github.com/sirloin2983/youtube-tools1)。
docs/HANDOVER.md、AGENTS.md、docs/WORKLOG.md の最後の数件、docs/ui-guidelines.md、docs/edit-tool-design.md を必ず先に読んでから始めて。
画面イメージは docs/mockups/edit-1-transcribe.png・edit-2-cut.png・edit-3-pack.png(承認済み)。
応答は日本語で、10〜20 分ごとに中間報告して。AI のモデルは作業に合わせて使い分けて(サブエージェントの model を指定)。

■ やること: 文字起こしツールと cut2resolve を統合した「編集」ツールの実装
- docs/edit-tool-design.md の「7. 実装の段取り」E1〜E6 を順に。段ごとにテストを通し、WORKLOG に書き、git commit("[Claude] 要約")。push はしない(私が push.bat で)
- 「9. リスク・エッジケース」は全部扱う。「10. 未決」と、設計の変更・依存の追加(Playwright を入れるなど)・既存機能の削除は、始める前に私に聞いて
- 始める前に、段階7と画面の見直しの実機確認の結果を私に聞いて(HANDOVER の「残りの作業」2)

■ 現在地(2026-09-26 夜)
- GitHub main = 62ab367 + 未コミット(docs/edit-tool-design.md・docs/mockups/・HANDOVER・WORKLOG・AGENTS.md)
- 版: 入口 0.9.0 / スタジオ 0.8.0 / 文字起こし 0.15.0 / cut2resolve 0.10.0 / ui-kit v3
- 起動は start-all.bat だけ。作業データはリポジトリの外(%LOCALAPPDATA%\youtube-tools\)

■ 保留(こちらから言い出したら進める)
新着配信の監視、書き出し中のタブの STATUS_ACCESS_VIOLATION、まとめて実行の最初の文字起こしが遅い件
```
