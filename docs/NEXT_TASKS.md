# 次にやる作業(Claude Code 向け・2026-09-24 Claude(Cowork) が作成)

ユーザーの指示:「続行」「精度改善に必要なデータがあれば集める」「こちら側に入力してほしい項目があれば確認して追加」。
Cowork 側でトークンが尽きたため、Claude Code で続きを行う。**始める前に `AGENTS.md` のルールと `docs/WORKLOG.md` の最後の数件を読むこと。**
終わったタスクは、この表の「状態」を「済」にし、WORKLOG に記録してコミットする(push は不要。ユーザーが push.bat で行う)。

| # | タスク | 状態 |
|---|---|---|
| 1 | Claude 版と GPT 版の v0.9.8 を統合して v0.9.9 にする | 済(2026-09-24 Claude Cowork) |
| 2 | 精度改善用のデータを集めて基準を測る(段階0・無料・読み取りのみ) | 済(`docs/accuracy-baseline.md`) |
| 3 | ユーザーに入力してほしい項目の一覧を作る | 済(`docs/USER_INPUT.md`。ユーザーの記入待ち) |

---

## 1. 統合(transcribe-tool。ユーザー了承済みの方針)
- 今の `transcribe-tool/index.html`・`serve.py`・`README.txt` = Claude 版 v0.9.8。GPT 版 = `_recovered/2026-09-23-gpt/transcribe-tool/` の3ファイル。
  共通の元は Claude の v0.9.7(git の `4b1a2a5` 相当。PC の git には無いので、差分は「GPT 版 と Claude 版」を直接比べて判断する)
- GPT 版からそのまま取り込む:
  - 保存の安全性(`saveDoc` の直列化・`docSaveP`・`docOpenSeq`、`openDoc` が保存失敗・競合・読み込み中の編集で false を返して切り替えない)
  - 行ごとの「残す/カット済」(`cutState`)と、話者・置換・書き出しの中の「DaVinci Resolveへ渡す」(`installResolveExport`・`/api/resolve-package`・`resolve_export.py`)
  - 保存済み一覧の検索・絞り込み・「残りを表示」、修正候補の検索・「残りを表示」・回数の既定 2回以上
  - serve.py: `sanitize_transcript` で `cutState` を保存、`studio_out_dir` の既定を exports に、`/api/resolve-package`
  - 準備が必要な項目の表示(setup-banner)
- ぶつかる所の決め方:
  - 左のパネル: Claude 版の「☰ で開閉(`V.menu`・`#btnMenu`・G キー・`.app.menu-closed>aside`)」を土台に、その中に GPT 版のタブ(新規・履歴・精度・学習、`V.sideTab`)を入れる。
    GPT 版の「集中モード」「管理」ボタン(`#btnSide`・`side-open`・`has-doc` の 1280px 以下の切り替え)は、☰ と役割が重なるので入れない(☰ に一本化)
  - 行のボタン: 「残す/カット済」は「校正済み」の隣に常に出す。GPT 版の「…」メニュー(`.row-more`)は入れず、分割・結合・削除などは Claude 版の「選んだ行の下の操作の段」のまま
  - 行の mousedown でフォーカスを移さない処理・`navSnapshot/navRestore`・Z の2回押しなど、Claude 版のキーボード操作の修正は維持する
- 版: 0.9.9(SERVER_VERSION・APP_VERSION・README.txt の見出し)。README に v0.9.9 の変更点(統合の内容)を書く
- テスト(全部通すこと。通らない場合は理由を WORKLOG に書く):
  - `python -m unittest test_metrics -q`、`python -m unittest test_resolve_export -q`、`node --test test_document_save.cjs`(統合後は9件すべて通る)
  - Playwright が入っていれば `e2e_ui_v098.py`・`e2e_ui_v08.py`・`e2e_ui_v09.py`・`e2e_ui_v07.py`・`e2e_eval_v093.py`(v07/v09 の「版 v0.9.4」判定だけは想定内の失敗)。
    入っていなければ実行できなかったことを WORKLOG に書く
- 統合が終わったら `_recovered/` は消してよい(ユーザーに一言伝える)

## 2. 精度の基準データ(段階0。ツールは変更しない・PC のデータは読むだけ)
計画は `docs/project/accuracy-plan.md` と `transcribe-tool/TRANSCRIPTION_V2_DESIGN.md`。データは `transcribe-tool/transcripts/*.json`(segments=人が直した行、original=機械の出力)、
`transcribe-tool/dataset/`(index.jsonl・docs/<id>/lines.jsonl・audio/*.flac=校正済みの行ごとの音声)、`transcribe-tool/settings.json`(用語集・置換辞書)。
serve.py の関数(`doc_metrics`・`norm_cer`・`_groups`・`learn_events`)を import して使い、ツールの画面と同じ数字になるようにする(import 時の副作用を先に確認)。
測って `docs/accuracy-baseline.md`(日本語。CER は初出で説明)と `docs/accuracy-baseline.json` に残す。スクリプトは `tools/baseline_analysis.py` に置く(再実行できるように):
1. 全体の CER と内訳(置換・脱落・挿入)。文書別・モデル別・設定別(params の vadMode・beam・boost・用語集の有無など)。評価用(evalSet)は分けて
2. 人物名・固有名詞の誤り(用語集・`hololive-roster.json` の名前が何に聞き違えられたか)、よくある修正の組み合わせ(誤→正)と回数
3. 条件別: 行のメモ(overlap・bgm・unclear)、要確認の印(自信が低い・音声でない可能性・繰り返し・英字)あり/なし、音量の四分位(行ごとの音声の RMS。小声の代わり)ごとの CER
4. 信頼度と誤り: 連続値の信頼度は保存されていない。印の有無で分かる範囲だけ
5. モデルの比較(large-v3 と turbo など): データに両方あれば比べる。無ければ無いと書く
6. データの棚卸し: 校正済みの音声の合計時間・行数・文書数・話者/配信者・評価用の数。正式な評価セットの条件(合計15〜30分以上、元の配信3〜5本以上、話者4人以上、
   通常/BGM/重なり/小声/叫び/笑い/固有名詞/無音を含む)に対して、何が足りないか
7. 統計の注意: 標本が小さいので、差がどこまで意味があるか(行・文書のブートストラップでおおよその 95% 区間)
8. 結論: 誤りがどこに集中しているか、どの対策が有望か、ユーザーが用意すべきデータ(具体的に)
- 注意: クラウドには送らない。個人データ(音声・文字起こし)をリポジトリにコミットしない(レポートには集計値と短い例だけ)

## 3. ユーザーに入力してほしい項目(`docs/USER_INPUT.md` を作る)
2 の結果も踏まえて、ユーザーが書き込むだけでよい記入用のファイルを作る(AI が読み取って用語集・評価に使う)。最低限:
- 評価用の動画のリスト(URL またはファイルのパス・配信者・区間・種類(通常/BGM/重なり/小声/叫び/固有名詞)・評価用か学習用か)
- 人物の正式な表記と呼び名・愛称(例: 白上フブキ = フブキ・白上・フブちゃん)、よく一緒に出る人
- ゲーム・企画ごとの用語(ゲーム名・固有の言葉)
- チャンネル固有の言葉・口癖・定番の挨拶
- コラボの別視点(同じコラボの各配信者の配信 URL)
- 字幕の書き方の決まり(つなぎ言葉「えっと」を残すか・数字は漢数字か算用数字か・笑い「www」をどう書くか)— クラウドの結果と比べるときの正規化に必要
- 既存の `settings.json` の用語集・置換辞書と重複する分は、そちらを参照すると書く
