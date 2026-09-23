# transcribe-tool(文字起こしツール)— AI 向けメモ(Claude・GPT 共通)

現在 **v0.9.8(Claude 版)**。GPT 版の v0.9.8(別の変更)は上書きで消えたため `_recovered/2026-09-23-gpt/` に復元してあり、**2つの版の統合はユーザーの確認待ち**(`../docs/WORKLOG.md`)。
GPT の設計書 `TRANSCRIPTION_V2_DESIGN.md`(精度改善 v2。実装は保留)も必ず読む。
最新の経緯・決定事項・次にやることは `../docs/project/HANDOVER-transcribe-tool.md`(版ごとの記録は `transcribe-tool-v*.md`、全体仕様は `transcribe-tool-spec.md`)。
使い方の説明はユーザー向けの `README.txt`(変更したら README も直す)。
精度向上の計画(段階0〜5。クラウドは初期比較と点検だけ・最終的に外部課金0円)は `../docs/project/accuracy-plan.md`。**ユーザーの指示があるまで実装しない**(2026-09-24 時点)。

## 構成
- `serve.py` … Python 標準ライブラリの HTTP サーバー(127.0.0.1:8775)。文字起こしは faster-whisper、話者判別は sherpa-onnx(任意)。
  ジョブは優先度付きの待機列(話者判別は、待っている文字起こしより先に処理。実行中のジョブは中断しない)。
  保存は `transcripts/<id>.json`(`segments` = 人が直した行、`original` = 機械の出力。精度測定・修正からの学習は、この2つを時刻の重なりで対応づける)
- `index.html` … 画面(CSS・HTML・JS が1ファイル)。JS は即時関数の中なので、状態 `S`(文書・今の行など)と `V`(表示の好み。localStorage)はグローバルではない
- `test_metrics.py` … サーバー側の単体テスト。`e2e_*.py` … 画面の通し確認(Playwright + 疑似モード)

## テストの実行
```
python -m unittest test_metrics -q          # 31件
python e2e_ui_v07.py / e2e_ui_v08.py / e2e_ui_v09.py / e2e_eval_v093.py / e2e_ui_v098.py
```
- e2e は serve.py を疑似モード(環境変数 `TRANSCRIBE_BACKEND=fake`)で起動して試す。ffmpeg と Playwright の chromium が必要
- `e2e_ui_v07.py` と `e2e_ui_v09.py` の「版 v0.9.4」の判定だけは、版を上げたことによる**想定内の失敗**(古い版の記録を残してあるため)。それ以外は全部通ること
- `e2e_ui_v08.py` の「4000行での Alt+Enter → 次の行 0.5 秒」は、マシンの負荷で時々超える(タイミング依存)
- GPT が追加したテスト: `node --test test_document_save.cjs`(保存・切り替えの競合)、`python -m unittest test_resolve_export`(Resolve 書き出し)。
  **test_document_save.cjs は、GPT 版の変更が統合されるまで今の index.html では 9件中8件が失敗する**(想定内。統合後は全部通ること)

## 画面の設計で決めたこと(Claude 版 v0.9.8 時点。GPT 版との統合で変わりうる。変えるときはユーザーに確認)
- 編集画面は2列: 左 = 映像と道具(`aside.tx-stage`。画面に固定され、列の中だけスクロール)、右 = セリフの一覧(`#segs`)。狭いと1列(コンテナクエリ)
- 左のメニュー(`aside#menuPanel`)は ☰ / G で開閉し、状態を保存。**映像の欄(tx-stage)を畳むのではない**(過去に誤解して作り直した)
- 行の ▶ は**その行だけ**再生して止まる(`playSeg(s, true)`)。通しの再生は映像そのものの再生ボタン / Space だけ
- キー操作は**単体キー**(Shift 不要)。例外は Shift+Space(校正済みにして次へ)だけ(Space 単体は再生・停止)。Z は2回押しで削除
- 行の操作ボタン(時刻の微調整・再生位置・＋前に行・＋後に行・分割・結合・削除)は選んだ行(`.seg.nav`)の下にだけ出す
- 「今の行」(`S.navIdx`、青い太枠)と一括選択のチェック(`S.sel`)は別物。チェックで今の行を動かさない
- 行の並びが変わる操作(削除・結合・分割・追加・元に戻す・読み直し)の前後では `navSnapshot()` / `navRestore()` で行の id を基準に今の行を追い直す
- 行のボタンは mousedown でフォーカスを移さない(移すと前の行の操作ボタンが消えて一覧がずれ、押し損じる)。今の行は click で切り替える
- 行の追加は前後のすき間に置く。すき間が無いときは仮の 1.5 秒で置き、重なりは時刻の欄を赤く(`.times.ovl`)して知らせる。`sortSegs()` は開始時刻だけの安定ソート
- 評価用(evalSet)の文字起こしは、学習・辞書・提案に使わない(精度を測るためだけ)

## 未解決・注意
- **未解決**: v0.9.6 配布時、ユーザーの PC で `serve.py` 起動時に `SyntaxError: unknown parsing error`(line 0)が出たという報告があった。原因は未特定(ファイルの破損・文字コード・BOM・zip 展開の失敗などを疑う)。再発したら、まずファイルの先頭のバイト列・サイズ・文字コードを確認する
- v0.9.0 以降の機能(フォルダ一括・範囲の再認識・評価用・句読点の除去・話者判別の優先割り込みなど)は、疑似モードでしか確かめていない。実際の faster-whisper・実際の動画での確認がまだ
- 後で実装したい: 文字起こしの結果を切り抜きスタジオへ返す機能、声紋登録、ボーカル分離の比較、名簿への愛称の追加
