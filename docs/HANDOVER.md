# HANDOVER — 次のセッションへの引き継ぎ(2026-09-26 深夜)

セッションを切り替えるたびに上書きする。詳しい経緯は `docs/WORKLOG.md`、ルールは `AGENTS.md`、画面の共通のルールは `docs/ui-guidelines.md`、ユーザー向けの使い方はリポジトリ直下の `README.txt`。

## 今の状態
- GitHub の main = 7ce0050(段階7-0〜7-3 まで)以降。この後の未コミット(画面の全面見直し)は WORKLOG の最後の記録を参照(push.bat で送る)
- 版: 入口 0.9.0・切り抜きスタジオ 0.8.0・文字起こし 0.15.0・cut2resolve 0.10.0・ui-kit v3・ytt_core(datadir・jobs・txindex(pack_info を追加))
- 担当: 統合作業・cut2resolve・**文字起こしツール**・3ツールと入口の画面の見直し(ui-kit を含む)は Claude(ユーザー決定 09-26)
- 統合計画: 段階1〜6 は実装済み・実機確認済み。段階7-0〜7-3(エラーの記録・解析の設定をサーバーへ・離れた/戻った・窓で開く(試用))は実装済み・実機確認待ち。
  続けて画面の全面見直し(09-26 夜)を実装済み・実機確認待ち。統合計画の正本 = Claude Docs「動画編集ツール 統合計画」にも記録済み
- ユーザーの指示: **作業中は 10〜20 分ごとに中間報告する**。**AI のモデルは作業に合わせて使い分ける**(監査・定型の実装は Sonnet、難しい実装・設計・結合は Opus など)

## 残りの作業(上から順に)
1. 実機確認(ユーザー): push.bat →「すべて終了」→ start-all.bat のあと
   - 文字起こし: 履歴(配信ごとのまとまり・だれの/いつの/校正の進み具合・絞り込みと並び替え)、校正画面の「カットとパック」
     (行を「カット済」→「カット後の見え方で再生」で飛ぶか →「パックを作る」→ 切り抜きの隣の `_pack` に Text+ パック → Resolve で読めるか。作り直すときの上書きの確認)
   - 案件の一覧(1件1行・開く・並び替え・まとめ方・次にやること・まとめて実行)、スタジオ(① の事務所のチェック・③ の配信の選択・書き出しの位置)、cut2resolve(動画を入れると隣の字幕を提案)
   - 段階7 の残り: 入口の「窓で開く(試用)」、窓の中のリンク、解析の設定の引き継ぎ、隣の窓へ移ったときの保存
2. 試用の結果で「窓で十分 / 7-4 pywebview / ブラウザに戻す」をユーザーが決める(pywebview は依存の追加なので始める前に確認)
3. 見直しの残り(候補。着手前に相談): ui-kit に引き出し・確認のダイアログ・小さな進み具合の棒・キーの手がかりの帯を共通の部品として足す(今は各ツールにある)、
   スタジオに配信の日時を残す、案件の画面からスタジオの特定の配信を開く(?open=)、スタジオのサーバーのエラーの文言に残る「動画」、行の「要確認」の印(押せる札のまま)
4. 改善の候補: まとめて実行の記録を入口の終了後も残す
5. ユーザーの確認待ち: 文字起こしの精度改善の設計 `transcribe-tool/TRANSCRIPTION_V2_DESIGN.md`(GPT 作)、精度の基準の記入待ち `docs/accuracy/USER_INPUT.md`

## 保留(ユーザー決定。言い出されたら進める)
- 新着配信の監視(段階5)
- 書き出し中にブラウザのタブが STATUS_ACCESS_VIOLATION で落ちた(09-26 13:32。再現したら、ブラウザ・画面・YouTube 再生中かを聞き、ハードウェアアクセラレーション → 拡張機能の順に切り分け。client-errors.jsonl も見る)
- まとめて実行で最初の文字起こしが遅い(09-26 14:32。large-v3 の最初の読み込みを疑うが未確定。再現したら「文字起こし」の段の表示と transcribe の serve.log を見る)

## 注意
- 画面を直すときは `docs/ui-guidelines.md`(用語集・ヘッダー・ボタンと札・一覧・段階的に見せる・狭い画面)に合わせる。ui-kit は正本を直して `python tools/sync_ui_kit.py`
- 見本のデータで全画面を動かす: `python tools/demo_env.py --port 8750 --dir <作業フォルダ>`(本物の作業データには触らない)。止めるときは `pgrep -f "[t]ools/demo_env.py" | xargs kill`
  (`pkill -f demo_env.py` を同じコマンドに書くと自分のシェルも止まる)
- 文字起こしの「カットとパック」は cut2resolve の API(api/plan・api/build・api/job・api/job/cancel・api/open-folder、preset transcript-rows、409 exists)に頼っている。変えるときは互換を保つ。文字起こし側に Resolve 用の計算を書き足さない
- パックの有無の判定は `ytt_core/txindex.pack_info` の1か所(入口の案件・文字起こしの一覧)
- Cowork(クラウド)は PC で git・移動・削除ができない。**消すファイルは tools/removals.txt に書く**(push.bat が git rm)。書き込んだら読み直して一致を確かめる。push はユーザーの push.bat
- push.bat はコミットの前に tools/push_helper.py check で個人データ・秘密情報を調べて止める。誤検出で止まったら検査(push_helper.py)を直す
- PC の .bat は CRLF(push.bat・install.bat・install-gpu.bat)。書き込むときは元の改行に合わせる
- **サーバーを動かすテストは先頭で `os.environ.setdefault("YTT_DATA_DIR", "inplace")`**
- 契約テスト `tools/test_resolve_pack_contract.py` は単独のコマンドで
- GPT(Codex)がこのフォルダで作業すると `.git\refs\codex\` に壊れた参照が残ることがある → push.bat が `bad object refs/codex/…` で止まったら `rmdir /s /q .git\refs\codex`
- 起動中の入口・ツールは古いコードのまま。コードを直したら「すべて終了」→ start-all.bat

## 次のセッションに貼る指示文
```
リポジトリ: https://github.com/sirloin2983/youtube-tools1(PC 上は Desktop\youtube-test)。
docs/HANDOVER.md、AGENTS.md、docs/WORKLOG.md の最後の数件、docs/ui-guidelines.md を必ず先に読んでから始めて。
応答は日本語で、10〜20 分ごとに中間報告して。AI のモデルは作業に合わせて使い分けて。

■ 現在地(2026-09-26 深夜)
- 統合計画の段階1〜6 は実装済み・実機確認済み。段階7-0〜7-3 と、3ツール・入口の画面の全面見直しを実装済み・実機確認待ち
  (文字起こしの履歴を配信ごとに・校正画面の「カットとパック」・案件を1件1行・スタジオの不具合2件・cut2resolve の段階的な表示)
- 版: 入口 0.9.0 / スタジオ 0.8.0 / 文字起こし 0.15.0 / cut2resolve 0.10.0 / ui-kit v3
- 文字起こしツールも Claude の担当。起動は start-all.bat だけ。PC のファイルを消すときは tools/removals.txt に書く

■ 次の作業(HANDOVER の「残りの作業」)
1. 実機確認の結果を聞く(文字起こしの履歴・カットとパック → Resolve、案件の一覧、スタジオ、cut2resolve、窓で開く)
2. 窓の試用の結果で「窓で十分 / pywebview / ブラウザに戻す」を決める
3. 見直しの残り(ui-kit の共通部品の追加など)をどれからやるか相談

■ 保留(こちらから言い出したら進める)
新着配信の監視、書き出し中のタブの STATUS_ACCESS_VIOLATION、まとめて実行の最初の文字起こしが遅い件
```
