# HANDOVER — 次のセッションへの引き継ぎ(2026-09-26 夜)

セッションを切り替えるたびに上書きする。詳しい経緯は `docs/WORKLOG.md`、ルールは `AGENTS.md`、ユーザー向けの使い方はリポジトリ直下の `README.txt`。

## 今の状態
- GitHub の main = eef5e17(09-26 14:22)以降。この後の未コミット(段階7-0〜7-3)は WORKLOG の最後の記録を参照(push.bat で送る)
- 版: 入口 0.8.0・切り抜きスタジオ 0.7.0・文字起こし 0.14.2・cut2resolve 0.9.1・ui-kit v2・ytt_core(datadir・jobs・txindex)
- 統合計画: 段階1〜6 は実装済み・実機確認済み(09-26。段階5・6 の残りもユーザーが「全部問題なし」)。
  段階7(画面の形)の 7-0〜7-3 を実装済み・実機確認待ち。統合計画の正本 = Claude Docs「動画編集ツール 統合計画」にも段階7 を追加済み
  - 7-0 画面のエラーの記録(`%LOCALAPPDATA%\youtube-tools\app\logs\client-errors.jsonl`。入口の `/api/log?tool=client`)
  - 7-1 解析の設定をスタジオのサーバーへ(まとめて実行も同じ設定)
  - 7-2 離れた・戻ったを ui-kit の `UIKit.life` に共通化(隣の窓へ移ったときも保存)
  - 7-3 入口の「窓で開く(試用)」: Edge のアプリモード + 専用のプロファイル。既定はオフ(ブラウザ)
- ユーザーの指示: **作業中は 10〜20 分ごとに中間報告する**

## 残りの作業(上から順に)
1. 実機確認(ユーザー): push.bat →「すべて終了」→ start-all.bat のあと
   - 入口の下の「窓で開く(試用)」をオン →「いま窓で開く」で Edge の窓(アドレス欄・タブなし)が開くか
   - 窓の中で、入口の「開く」・スタジオの「他のツール」・書き出しの「文字起こしで開く」が**窓で**開くか(タブのある普通の窓になったら、display-mode の判定が外れている)
   - 窓の中のスタジオの ③ で YouTube の埋め込みが再生できるか。ランキングの題名(YouTube へのリンク)が**いつものブラウザ**で開くか
   - スタジオの ② の「解析の設定」が窓の中でも前と同じ値か(以前のブラウザの保存を引き継いだか)。値を変えて、窓とブラウザの両方で同じになるか
   - 文字起こしで直してすぐ隣の窓をクリック → 保存されるか(「保存しました」の表示)
   - `%LOCALAPPDATA%\youtube-tools\app\logs\client-errors.jsonl` ができているか(エラーが無ければ無くてよい)
2. 数日使ってから、ユーザーが決める: 窓で十分(既定を窓に)/ 7-4 pywebview(依存の追加なので、始める前に確認)/ ブラウザに戻す
3. 改善の候補(着手前にユーザーと相談): 校正したあとに案件の画面からパックを作り直す / まとめて実行の記録を入口の終了後も残す
4. ユーザーの確認待ち: 文字起こしの精度改善の設計 `transcribe-tool/TRANSCRIPTION_V2_DESIGN.md`(GPT 作。着手前に確認)、精度の基準の記入待ち `docs/accuracy/USER_INPUT.md`

## 保留(ユーザー決定。言い出されたら進める)
- 新着配信の監視(段階5)
- 書き出し中にブラウザのタブが STATUS_ACCESS_VIOLATION で落ちた(09-26 13:32。サーバー側は正常。再現したら、ブラウザ・画面・YouTube 再生中かを聞き、ハードウェアアクセラレーション → 拡張機能の順に切り分け。
  窓(専用のプロファイル・拡張機能なし)でも落ちるかが切り分けの材料になる。client-errors.jsonl も見る)
- まとめて実行で最初の文字起こしが遅い(09-26 14:32。43秒の切り抜きが 502 秒で終わらずユーザーが中止 → 直後の再実行は 15 秒。
  同時に認識ワーカーが起動し直していたので large-v3 の最初の読み込みを疑うが、原因は未確定。再現したら「文字起こし」の段の表示と transcribe の serve.log を見る)

## 注意
- Cowork(クラウド)は PC で git・移動・削除ができない。**消すファイルは tools/removals.txt に書く**(push.bat が git rm)。書き込んだら読み直して一致を確かめる。push はユーザーの push.bat
- push.bat はコミットの前に tools/push_helper.py check で個人データ・秘密情報を調べて止める。誤検出で止まったら検査(push_helper.py)を直す
- PC の .bat は CRLF(push.bat・install.bat・install-gpu.bat)。書き込むときは元の改行に合わせる
- **サーバーを動かすテストは先頭で `os.environ.setdefault("YTT_DATA_DIR", "inplace")`**(忘れると本物の作業データを読み書きする。ytt_core のテストが検査)
- 画面で visibilitychange を直接使わず `UIKit.life` を使う。ツールに `/api/ytt/` で始まる API を作らない(入口が受け持つ)。画面の不具合はまず client-errors.jsonl
- 窓の中かどうかは `display-mode: standalone` で見ている(`UIKit.win.isApp()`)。窓の専用のプロファイルは YouTube に未ログイン(会員限定などは再生できないことがある)
- 重い処理は `ytt_core.jobs.SLOTS` を通す。文字起こしと切り抜きの紐づけは `ytt_core/txindex.py` だけ。他のツールのデータは読むだけ。まとめて実行はツールの API を呼ぶ(関数を直接呼ばない)
- 契約テスト `tools/test_resolve_pack_contract.py` は単独のコマンドで(app/test_mount.py と一緒に渡すと部品の名前が重なる)
- GPT(Codex)がこのフォルダで作業すると `.git\refs\codex\` に壊れた参照が残ることがある → push.bat が `bad object refs/codex/…` で止まったら `rmdir /s /q .git\refs\codex`
- 起動中の入口・ツールは古いコードのまま。コードを直したら「すべて終了」→ start-all.bat

## 次のセッションに貼る指示文
```
リポジトリ: https://github.com/sirloin2983/youtube-tools1(PC 上は Desktop\youtube-test)。
docs/HANDOVER.md、AGENTS.md、docs/WORKLOG.md の最後の数件を必ず先に読んでから始めて。応答は日本語で、10〜20 分ごとに中間報告して。

■ 現在地(2026-09-26 夜)
- 統合計画の段階1〜6 は実装済み・実機確認済み。段階7(画面の形)の 7-0〜7-3 を実装済み・実機確認待ち
  (エラーの記録・解析の設定をサーバーへ・離れた/戻ったの共通化・入口の「窓で開く(試用)」= Edge のアプリモード)
- 版: 入口 0.8.0 / スタジオ 0.7.0 / 文字起こし 0.14.2 / cut2resolve 0.9.1 / ui-kit v2。GitHub の main は eef5e17 以降(段階7 は push.bat で送る)
- 起動は start-all.bat だけ。PC のファイルを消すときは tools/removals.txt に書く(push.bat が git rm)

■ 次の作業(HANDOVER の「残りの作業」)
1. 段階7 の実機確認の結果を聞く(窓の中のリンクの行き先・YouTube の埋め込み・解析の設定の引き継ぎ・隣の窓へ移ったときの保存)
2. 試用の結果で「窓で十分 / 7-4 pywebview / ブラウザに戻す」をユーザーが決める(pywebview は依存の追加なので、始める前に確認)
3. 改善の候補(校正後にパックを作り直す / まとめて実行の記録を残す)をどれからやるか相談

■ 保留(こちらから言い出したら進める)
新着配信の監視、書き出し中のタブの STATUS_ACCESS_VIOLATION、まとめて実行の最初の文字起こしが遅い件
```
