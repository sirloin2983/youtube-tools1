# 段10: コードの整理(editor の serve.py・app.js を役割で分ける)

> 状態(2026-10-01): **決定済み・着手**(ユーザー決定: 1 = 案A・2 = app.js も同じ段で serve.py のあと・3 = Python 3.10 に固定して版を requirements に書く)。大きな計画は `docs/plan/line-a-after-phase8.md` の段10。**動きは変えない・版は上げない**。終わりの条件は「分ける前と後で全部のテストが同じ結果」
> 線 B 段1(呼び名と文脈)は 2026-09-29 に済んでいた(編集 0.22.0。`docs/plan/transcription-overhaul-plan.md` の「1回目の結果」)。「段10 の前にやるか」の決定は不要になった

## 目的
- 線 B 段2〜5(認識の部分を大きく書き換える)の前に、`editor/serve.py`(7,436 行・31 の節)を役割ごとのファイルに分け、差分を小さく・テストを速く・AI 同士の衝突を減らす
- `editor/app.js`(3,357 行)も同じ考えで分ける
- テストの入口を分かりやすくする・Python と部品の版を固定する

## 含まない
- 動きの変更・画面の変更・API の形の変更・フレームワーク/ビルドの導入(`.design/ui-overhaul/DESIGN_BRIEF.md` の Out of Scope)
- studio・home・cut2resolve の分割(必要が出たら別の段)

## 今の形(2026-10-01 に調べた)
- serve.py の節: 記録・保存・履歴・編集の内容・付け替え・評価用のフォルダ・波形・ジョブ・認識ワーカー・声の検出のやり直し・単語の時刻・話者判別・声を覚える・
  置換辞書と学習・提案・精度の測定・基準・修正データの書き出し・保管・選んだ行の再認識・範囲/全体の再認識・疑わしい所の認識し直し・設定の比較・clip-marker・進行度・フォルダの一括・受け渡し・HTTP
- serve.py を読む所: 入口 `home/mount.py`(`ytt_tool_transcribe` という名前でファイルから読む)・認識ワーカー `editor/tx_worker.py`(`import serve as S`。`_load_model_local`・`_diarize_local`・`_embed_local` を使う)・
  `dev/eval_asr.py`(`_groups`・`norm_cer` など)・テスト(`editor/tests/test_*.py` が `S = serve` を読み、**約 30 種類の名前を差し替える**: `S.TX_DIR`・`S.SETTINGS`・`S.DATA_DIR`・`S.WORKER`・`S.run_job`・`S.find_ffmpeg`・`S.relink_check` など)
- 決まり: ツール間で同じ名前の .py を作らない(`home/tests/test_mount.py` が検査)・サーバー側で numpy などを import しない(`test_worker.py`)・e2e はツールのファイルを一時フォルダに写す(`e2e_edit_common.py` は拡張子でまとめて写す。古い e2e は名前の一覧)
- Python: 起動(start.bat の `py -3`)は **3.10.6**(faster-whisper 1.2.1・ctranslate2 4.8.2・sherpa-onnx 1.13.8・onnxruntime 1.23.2・numpy 2.2.6)。
  テストは miniconda の **3.12.3**(playwright 1.63.0・numpy 1.26.4・onnxruntime 1.30.0)。`setup/requirements.txt` は `faster-whisper` の1行(版なし)

## 分け方(決めてもらうことの 1)
**案A(おすすめ)状態を1か所に置いて、関数は役割ごとのファイルへ。serve.py は設定・起動・HTTP の振り分けと、名前の引き継ぎ(再輸出)だけ**
- 置き場所などの値(`TX_DIR`・`SETTINGS`・`DATA_DIR`・`WORKER` など書き換わるもの)は新しい `ed_state.py` に置き、各ファイルは `st.TX_DIR` の形で**呼ぶたびに**読む(`from … import TX_DIR` はしない = 差し替えが効く)
- テストの差し替えは「その名前を持っているファイル」を差し替える形に直す(`S.TX_DIR = …` → `st.TX_DIR = …`、`S.relink_check = …` → `ed_relink.relink_check = …`)。読むだけの所(`S.read_transcript(...)`)は serve.py の再輸出でそのまま動く
- 利点: ふつうの Python の書き方・どこに何があるか分かる・線 B の差分が `ed_jobs.py` などに閉じる。欠点: テストの差し替え(約 60 か所)を直す手間・1回目の差分が大きい
**案B 同じファイルのまま並べ替えと目次だけ**: 差分は小さいが、線 B の衝突・テストの速さは良くならない(段10 の目的を満たさない)
**案C serve.py のモジュールに中身を流し込む(exec など)**: テストを直さずに済むが、Python の普通の読み込みと違い、エラーの行番号・道具(grep・IDE)が分かりにくくなる。採らない

### 案A のファイル(名前は他のツールと重ならないよう `ed_` で始める)
| ファイル | 中身(今の節) | 目安の行数 |
| --- | --- | --- |
| `ed_state.py` | 置き場所・設定の値・ロック(`_save_lock`・`_jobs_lock`)・`ApiError`・ログ | 200 |
| `ed_store.py` | 文字起こしの保存・履歴・編集の内容・一覧の要約 | 900 |
| `ed_relink.py` | 付け替え・まとめて付け替え・評価用のフォルダ | 700 |
| `ed_media.py` | ffmpeg/ffprobe・波形・音声の取り出し | 400 |
| `ed_jobs.py` | ジョブの列・認識ワーカー・声の検出のやり直し・単語の時刻・選んだ行/範囲/全体の再認識・疑わしい所の認識し直し | 2,400 |
| `ed_speakers.py` | 話者判別・声を覚える | 800 |
| `ed_learn.py` | 置換辞書・学習・提案・精度の測定・基準・修正データの書き出し・保管 | 1,300 |
| `ed_misc.py` | 設定の比較・clip-marker・進行度・フォルダの一括・受け渡し | 600 |
| `serve.py` | 起動・HTTP の振り分け・再輸出 | 700 |
(行数は目安。分けながら決める。循環 import を避けるため、下のファイルは上のファイルだけを読む)

## app.js の分け方(決めてもらうことの 2)
- 画面は `<script>` を順に読む形のまま(ビルドなし)。トップレベルの `const`・`let` は、後から読むスクリプトからも見える(同じ画面の中で共有される)ので、**今の名前のまま**ファイルを分けられる
- 案: `app-core.js`(状態 S・V・api・保存・開く)・`app-list.js`(履歴の一覧)・`app-rows.js`(行の描画・操作・キー)・`app-tools.js`(話者・置換・書き出し・設定・評価用)・`app.js`(起動)。読む順番は index.html の1か所
- 決めてもらうこと: serve.py と同じ段でやる(おすすめ: serve.py のあと、同じ段で)か、あとに回すか

## テストの整理
- `editor/tests/test_metrics.py` が他のテストを読み込む形はそのまま(コマンドは変えない)。分けたファイルに合わせて差し替えを直す
- 古い e2e(名前の一覧で写すもの)に新しい .py・.js を足す。`e2e_edit_common.py` は拡張子でまとめて写すので変えなくてよい
- 分ける前に全部のテストを流して結果を記録 → 分けたあとにもう一度流して同じことを確かめる(WORKLOG に件数)

## Python と部品の版の固定(決めてもらうことの 3)
- おすすめ: 起動は今の **3.10**(faster-whisper など入っている方)に固定し、`setup/requirements.txt` に今入っている版を書く(`faster-whisper==1.2.1`・`ctranslate2==4.8.2`・`sherpa-onnx==1.13.8`・`onnxruntime==1.23.2`・`numpy==2.2.6`)。
  start.bat・install.bat は `py -3.10` を先に試す(無ければ今までどおり `py -3` → `python`)。テスト用(playwright)は `setup/requirements-dev.txt` に分けて書き、テストは 3.10 でも 3.12 でも通ることを確かめる
- 別案: 3.12 にそろえる(miniconda)。faster-whisper などを入れ直す必要があり、GPU なしの CPU 版は入るが手間がかかる

## 進め方
1. 分ける前の全テストの結果を記録(editor の単体・e2e 全部・入口の test_mount・dev の契約テスト・eval_asr)
2. `ed_state.py` を作り、値を移す(テストの差し替えを直す)→ テスト → コミット
3. 節ごとに1ファイルずつ移す(下の層から: store → media → relink → speakers → learn → jobs → misc)。1ファイルごとにテスト → コミット
4. app.js を分ける → 画面の e2e → コミット
5. Python と版の固定 → install の確認(実機)
6. 前後の結果を WORKLOG に。`editor/AGENTS.md` の「構成」を新しいファイルで書き直す

## リスク
- 分けている間に、ほかの AI が `editor/` を触ると衝突する → 始める前に WORKLOG に「担当: editor/ の分割(段10)」と書き、1〜2 セッションで一気に終える
- 差し替えの直し漏れ: テストが「差し替えたつもりで本物を使う」と、作業データ・本物の ffmpeg に触れることがある → `YTT_DATA_DIR=inplace` の検査はそのまま。差し替えの名前の一覧を grep で前後比較する
- 認識ワーカーは serve.py を読み込む: ワーカーの中で numpy などを読む関数(`_load_model_local` など)の置き場所が変わっても、`tx_worker.py` からは serve.py の再輸出で見えるようにする。`test_worker.py` の「サーバー側で import しない」の検査を通す

## 決めてもらうこと
1. 分け方: 案A(おすすめ)/ 案B / 案C
2. app.js も同じ段で分けるか
3. Python: 3.10 に固定して版を requirements.txt に書く(おすすめ)/ 3.12 にそろえる / 今のまま
