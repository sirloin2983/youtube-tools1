# 友人用 文字起こし簡易版(lite)の実装計画

> 状態: **取り下げ(2026-10-04。ユーザー決定『いったん使わない』。コードは消した = git の cf617a8 までの履歴から戻せる)**。以前の状態(2026-10-02): L1〜L6 実装済み・実機の確認待ち(Claude Code。編集 0.34.0・ホーム 0.21.0・cut2resolve 0.17.0)。見直しの記録は `.design/friend-transcribe-lite/DESIGN_REVIEW.md`。設計の正本は `.design/friend-transcribe-lite/DESIGN_BRIEF.md`(grill-me・design-brief・10原則の確認は済み)。
> 段0(フォルダ整理)はコードの部分は済み。残りの「旧フォルダの改名・AI の作業フォルダの向け直し」は実装に関係しないので並行(ユーザー 2026-10-02「実装して」)。

## 1. 形(決めたこと)
- **サーバーは「編集」(`editor/`)をそのまま使う**。友人版は `editor/lite.html` + `lite.js` の**別の画面**で、同じ API(文字起こしのジョブ・文書の保存・競合・履歴)を呼ぶ。
  理由: 段10 で editor が部品に分かれ、文字起こし・字幕分割・保存はすでに共通の中身になっている。別のサーバーを作ると二重実装になり、精度改善(線 B)が友人版に届かない
- 友人版のための新しいサーバーの部品は `editor/ed_lite.py`(`/api/lite/…`)だけ。書き出し(パック + 送る用ファイル)・作業の記録(edits.jsonl)・状態(配信者の候補・色・再開)
- **共通コア**(ブリーフの「文字起こし・字幕分割・Text+ パック・評価データ形式」)の置き場所:
  | 中身 | 置き場所 | 友人版 / 編集 / 取り込みチェック |
  | --- | --- | --- |
  | 文字起こし(faster-whisper・ワーカー) | `editor/ed_jobs.py`・`tx_worker.py`(今のまま。GPU の精度の型を環境変数で選べるように) | 共通 |
  | 生出力(単語ごとの時刻・確信度) | `editor/ed_jobs.py` に `<id>.asr.json` を足す(分ける前・置換の前の認識結果) | 共通(編集の精度測定にも使える) |
  | 字幕分割(行) | `ed_jobs.split_segment`(今のまま) | 共通 |
  | Text+ パック | `cut2resolve/pack.py`・`resolve_textplus.py`(見た目の型 `lite` と字幕ごとのふちの色を足す) | 共通(Resolve 用の計算は cut2resolve だけ = 一本化の決まりを守る) |
  | 評価データの形式・記号の規則・パスの除去・zip の検証 | **新しい `ytt_core/evaldata.py`**(標準ライブラリだけ・純粋な関数) | 友人版の書き出しと、あなた側の取り込みチェックが同じ規則を使う |
- 入口(`home/launch.py`)に `--open-path`(最初に開く画面)を足し、友人版は `--only transcribe --open-path /transcribe/lite.html` で起動する(CSP・合言葉・Host 検査・ワーカーの分離・Edge の窓はそのまま使える)
- 起動は `lite/start.bat`(uv で Python 3.10 と部品を用意 → 更新の確認 → 入口)。部品の版は `setup/requirements-lite.txt`(英数字だけ)

## 2. 小さな決定(ブリーフに無く、実装で決めたこと。変えたければ言ってください)
- 文字起こしのモデルは `large-v3-turbo`(3060 の 8GB に int8_float16 で収まり、large-v3 に近い精度で速い)。GPU で失敗したら CPU で続ける(今の「自動」と同じ)
- GPU の精度の型: 環境変数 `TRANSCRIBE_CUDA_COMPUTE`(既定 float16 = 編集は今のまま)。友人版の起動が `int8_float16` を入れる
- 動画の受け取り: **ドロップ = アップロード**(ブラウザはドロップしたファイルの場所を教えないため。作業データの `lite-media/` に写す)、
  **「ファイルを選ぶ…」= PC の窓で選ぶ**(既存の `/api/pick`。写さない)。どちらも同じ画面に置く
- 出力先: `ドキュメント\文字起こし簡易版\<日付_配信者_作業ID>\` に `Resolve用ファイル\`(パック)と `送る用ファイル\<日付_配信者_作業ID>.zip`
- 作業ID = 文書の id(12 桁の英数字)。二重送付は作業ID で見分ける
- 話者の色: 内蔵の一覧 `editor/lite-colors.json`(差し替え可能な1ファイル)。最初の話者は 黄 + 黒ふち
- 字幕の見た目(友人版の型 `lite`): MS ゴシック・大きさ・位置は固定。文字の塗りとふちの色だけ話者ごと

## 3. 段と順番(各段でテストを足してコミット)
| 段 | 中身 | テスト |
| --- | --- | --- |
| L1 共通コア | `ytt_core/evaldata.py`(形式の版・ルールの版・記号の規則・字幕用の記号の除去・形式違いの検出・フィラーの数え・パスの除去・zip の検証)・cut2resolve の型 `lite` と字幕ごとのふち・ed_jobs の生出力 `<id>.asr.json` と GPU の型・話者のふちの色の保存 | `ytt_core/tests/test_evaldata.py`・`cut2resolve/tests/test_pack.py`・editor の単体 |
| L2 評価データの書き出し | `editor/ed_lite.py`: 送る用 zip(audio.flac・asr_raw.json・final.json・edits.jsonl・meta.json)とパック(カットなし = 動画全体)を1回で。作業の記録の追記 API | `editor/tests/test_lite.py`(zip の中身・絶対パスが無い・記号・空の行・確認済みだけ) |
| L3 画面 | `editor/lite.html`・`lite.js`(読み込み → 文字起こし中 → 校正 → 書き出し完了) | `editor/tests/e2e_lite.py` |
| L4 起動 | `lite/start.bat`(uv)・`lite/lite.py`(準備の確認・更新・入口)・`lite/update.py`(取得元は main に固定)・入口の `--open-path` | `lite/tests/test_lite_launcher.py`・`home/tests/test_launch.py` |
| L5 取り込みチェック | `dev/eval_import.py`: 届いた zip の検証(`../`・絶対パス・想定外のファイル・大きさ)→ 作業データの外の置き場所へ展開 → 弾く判定(形式違いの行・整えた疑い)を印と理由で記録(消さない) | `dev/tests/test_eval_import.py` |
| L6 見た目 | /frontend-design → /baseline-ui → /design-review | e2e の写真 |

## 4. 実機で確かめてもらうこと(ユーザーに依頼)
- **60fps の横動画を 30fps の Resolve プロジェクトで使ったときの字幕のずれ**(手順は `docs/plan/friend-lite-realcheck.md`。L2 のあとに作る)
- 友人の PC(RTX 3060)での start.bat の初回(uv・CUDA の部品のダウンロード・int8_float16)

## 5. 保留(ブリーフのとおり)
ホロカラー連携・整えた疑いの基準(最初のデータで調整。今は仮の値)・聞かずに確定を弾くか・波形表示
