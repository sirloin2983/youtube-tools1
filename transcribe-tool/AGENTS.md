# transcribe-tool(文字起こしツール)— AI 向けメモ(Claude・GPT 共通)

現在 **v0.21.0**(2026-09-28、動画全体の再認識と声の検出が捨てすぎる対策(下の「再認識(範囲・全体)と声の検出のやり直し」。`../docs/whole-retranscribe-design.md`)・映像の上の字幕に話者の色)。
それより前の版の中身は `README.txt` の「■ v0.xx の変更」と `../docs/WORKLOG.md`(0.16.0 = 「編集」の統合・0.11.0 = 認識のワーカー分離・0.12.0 = Resolve パックの一本化 など)。
画面の共通のルール(用語集・ヘッダー・ボタンと札・一覧・段階的に見せる・狭い画面)は `../docs/ui-guidelines.md`。画面を直すときは必ず合わせる。いま何が途中かは `../docs/WORKLOG.md` の最後の数件で確かめる。
現行の仕様は、このファイルとユーザー向けの `README.txt`。v0.9.8 までの経緯・決定の理由は `../docs/project/HANDOVER-transcribe-tool.md`、版ごとの記録は `../docs/project/history/transcribe-tool-v*.md`、
最初の仕様は `../docs/project/transcribe-tool-spec.md`(v0.7.0 当時。**どれも古い**ので、今の動きの根拠にはしない。理由を調べるときに読む)。
使い方の説明はユーザー向けの `README.txt`(変更したら README も直す)。
**精度改善の今の計画は `../docs/transcription-overhaul-plan.md`**(段0〜5。段0 の AI 側は済み・次は段1。段ごとにユーザーの承認のあとで実装)。
GPT の `TRANSCRIPTION_V2_DESIGN.md`(09-23)と `../docs/project/accuracy-plan.md`(09-24)はこの計画にまとめた旧計画(原則は引き継いだ・食い違う所は新しい方が正。経緯として読む)。
全体の状態(進行中・待ち・保留)は `../docs/ROADMAP.md`。

## 精度の測定の土台(計画の段0。v0.20.1)
- 機械の出力 `original` の各行に `avg_logprob`・`no_speech_prob`・`compression_ratio`(分かるものだけ。`machine_conf`・`CONF_KEYS`)。
  文字起こしのジョブ(`run_job`)と、範囲の再認識・疑わしい所の認識し直し(`finish_range_lines` の `conf` → `replace_original_multi`)が書く。
  選んだ行の再認識(`replace_original`)はまだ書かない。画面の保存(`sanitize_transcript`)は `original` を保存済みのものから引き継ぐので消えない
- 文書の `recognition = {"runs": [{engine, engineVersion, model, device, language, settings, audioSec, wallSec, at}]}`(`recognition_run`。文字起こしのジョブだけ)。
  版は `pkg_version`(dist-info を読むだけ。サーバー側で faster_whisper を import しない)
- 単語ごとの確率はまだ残していない(単語は `(開始, 終了, 文字)` の3つ組で多くの所が分解しているため。要るときに words.json の形ごと考える)
- モデルは手元のファイルだけで先に読む(`_new_whisper` の `local_files_only=True`。無ければネットワーク)
- 測る道具 `../tools/eval_asr.py`(`stored` = 保存してある出力 / `run` = 認識し直す / `compare` / `list`)。作業データは読むだけ、結果は作業データの `evals/asr/`。
  採点は serve.py の `_groups`・`norm_cer`・`lev_counts` を使い、`doc_metrics`(画面の測定)と同じ数になることを `stored` のたびに照らし合わせる(ずれたら注意を出す)。
  `run` は文字起こしのジョブと同じ整え方(`expand_segments`・`make_flags`)。元の動画が無ければ保管データの `full.flac`。テスト: リポジトリ直下で `python -m unittest tools/test_eval_asr.py`

## 構成
- `serve.py` … Python 標準ライブラリの HTTP サーバー(127.0.0.1:8775)。文字起こしは faster-whisper、話者判別は sherpa-onnx(任意)。
  ジョブは優先度付きの待機列(話者判別は、待っている文字起こしより先に処理。実行中のジョブは中断しない)。
  保存は `transcripts/<id>.json`(`segments` = 人が直した行、`original` = 機械の出力。精度測定・修正からの学習は、この2つを時刻の重なりで対応づける)
- `index.html` … 画面(CSS・HTML)。将来の統合(入口の `/transcribe/` に取り込む)に備えて CSP(`script-src 'self'`)に対応させたため、
  JS はインラインではなく `app.js`(このツールの画面ロジック)・`ui-kit.js`(共通の見た目。下記)を `<script src=...>` で読む。CSS は引き続き `<style>` に埋め込み(CSP はインラインの style を許可)
- `tx_worker.py` … 認識ワーカー(別プロセス。統合計画の段階3-3)。faster-whisper・sherpa-onnx(ネイティブコード)は**このプロセスの中だけ**で読み込む。
  serve.py の `WorkerClient`(`WORKER`)が起動し、標準入力/出力の1行1件の JSON でやり取りする。serve.py 側の `load_model()` は代理の `RemoteModel`
  (`transcribe()` が faster-whisper と同じ形 (行の生成器, 情報) を返す)を、`diarize_real()` はワーカーの結果を返すので、ジョブの処理(行の整形・保存)は変えずに済む。
  本体は serve.py の `_load_model_local()`・`_diarize_local()`(ワーカーが serve.py を読み込んで `IN_WORKER = True` にして呼ぶ)。
  音声の範囲はパスとサンプル番号で渡す(`read_wav_f32()` はサーバー側では `WavRef` を返し、numpy を読み込まない)。
  **サーバー側のプロセスで numpy・faster_whisper・ctranslate2・sherpa_onnx を import しない**(入口に取り込むと、落ちたときスタジオ・cut2resolve まで止まる。`test_worker.py` が検査)。
  やり取り用の標準入力は fd 0 から離して読む(`_protocol_input`。Windows で標準入力のパイプを読んで待つ間に DLL を読み込むと止まるため。2026-09-26)。
  ワーカーが落ちたらそのジョブだけ失敗、次の要求で起動し直す。取り消しは `job["proc"]`(`_CancelHandle`)経由で伝え、15秒で止まらなければ強制終了。
  `TRANSCRIBE_MODEL_IDLE_SEC`(既定900秒)使わなければワーカーごと終わらせる。GPU の有無も別プロセス(`tx_worker.py --probe`)で1回だけ調べる
- `app.js` … 画面の JS(旧 index.html の即時関数の中身をそのまま移した)。状態 `S`(文書・今の行など)と `V`(表示の好み。localStorage)はこのファイルのトップレベル変数で、グローバルではない。
  主なまとまり(v0.15.0): 履歴の一覧(「保存済み一覧」の節。`L` = 絞り込み・並び替え・まとめ方(localStorage `tx.list.v1`)、`txGroups`・`txOpen`・`txLimit`。
  開いているまとまりの分だけ描き、まとまりごとに「もっと見る」)、「編集」のタブ(`EDT`・`setEditTab()`・題名の行 `renderDocBar()`)、
  cut2resolve の呼び出し(`c2rBase()`/`c2rUrl()`/`c2rApi()`・`cpExport()`・`confirmOverwrite()`。パックのタブが使う)、キー操作の手がかり(`tx.keyhint`)
- 一覧の API `/api/transcripts`(serve.py の `list_transcripts`・`transcript_summary`): 行数(`rows` = 文字のある行)・`proofed`・`cut`・`flagged`・`durationSec`・
  元の配信(文書の `clip`(youtube-tools-clip/v1)の `videoId`・`clipTitle`・`clipStart`/`clipEnd`・`markLabel`)・配信者 `channel` と `streamTitle`
  (スタジオの data.json を**読むだけ**。置き場所は `studio_data_path()`、更新日時と大きさでキャッシュ `studio_videos()`)・元の動画の有無 `mediaOk`・
  パック `pack`(動画の隣の `<名前>_pack`。cut2resolve の作業データの「パックを作った記録」か、以前のパックならフォルダの中の cut-plan.json。
  規則は `ytt_core/txindex.pack_info` の1か所 = 入口の案件の画面 `app/cases.py` の `find_pack` と同じ判定。2026-09-26 ④)。
  動画・パックの有無はフォルダごとに1回・全体で `PACK_CHECK_BUDGET` 秒まで調べ、ネットワーク上のパス(`\\サーバー\…`)は調べない(資格情報を送らない。`mediaOk = None`)
- 3 パック のタブ(「編集」E4。`pack-tab.js`。v0.15.0 の校正画面の「カットとパック」を置き換えた): パック作りは **cut2resolve の API を呼ぶ**(文字起こし側に Resolve 用の計算を書かない)。
  区間は 2 カット のタブのとおり: cut2resolve の `api/build` の spec = `{video, transcript?, keeps: 残す区間の秒, advanced}`(`pack.EDIT_KEEPS`)・output = `{textplus, copyVideo, render, textplusFps, textplusSize, dir?, force}`。
  作る前にカットを保存し(`CUT.commit()`)、字幕の元として保存済みの文字起こしを動画のフォルダの `作業用\` に `.transcript.json`(`cpExport`。2026-09-27 から途中のファイルは `作業用`。規則は `ytt_core/schemas.py`)。文字起こしが無ければ Text+ なし(EDL と元の動画のコピー)。
  409 exists は上書きの確認(`#dlgOverwrite`)→ force。作り終えたら `POST /api/edit/pack`(packRev)。「これから作るパック」の字幕の数・注意は `POST /api/edit/preview`(ファイルを作らない)。
  cut2resolve の URL は `c2rUrl()` だけで作る(`UIKit.tools.base('cut2resolve')`。入口の中の同じポートのときだけ。合言葉は同じ入口のもの)。
  単体で開いたとき・cut2resolve が起動していないとき・動画が無い/音声だけ/ネットワーク上のときは理由を出して作れなくする(見積もりと zip は使える)。
  前回のパックの「フォルダを開く」は cut2resolve の `api/open-folder`(パックを作った記録か、以前の cut2resolve の cut-plan.json があるフォルダなら、入口を起動し直したあとでも開ける。
  `txindex.is_pack_dir`)。パックは最小限(④): 「予備も入れる」(`output.backup`)で EDL・予備の手順書・SRT。Text+ の .json は出さない(区間・字幕は Lua に埋め込み。テストは `resolve_textplus.read_script_plan` で読む)。
  zip(`/api/resolve-package`)と「残す区間(.cut-plan.json)を保存」も、カットがあればそのとおり
- `resolve_export.py` … 「Resolveパッケージ(zip)」(`/api/resolve-package`)。中身は隣の `../cut2resolve/pack.py` で作る
  (文書 → transcript/v1 → `pack.plan_cut(**pack.TRANSCRIPT_ROWS)` → `pack.build_pack(textplus=True)` → zip)。**Resolve 用の計算をここに書き足さない**
  (二重実装に戻さない。`../docs/resolve-pack-unification.md`)。cut2resolve の部品は呼ばれたときに読み込み、見つける場所は
  環境変数 `YTT_CUT2RESOLVE_DIR` → `../cut2resolve`。ここに残っているのは「残す行」の規則(`is_kept`・`kept_spans`)と SRT の書式(pipeline_io が使う)
- 「編集」(文字起こし + cut2resolve の統合。`../docs/edit-tool-design.md`。2026-09-26 に E1〜E6 を実装)のサーバー側(serve.py の「編集の内容」「音の波形」の節):
  編集の内容 `transcripts/<id>.edit.json`(残す区間 = カットの正。`GET/PUT /api/edit`・rev と 409)、`POST /api/edit/pack`(パックを作った記録・`packStale`)、
  `POST /api/open-video`(文字起こしせずに開く)、`GET /api/peaks`(音の波形。作っている間は 202)、`POST /api/transcribe` の `intoDoc`。
  **単語の時刻** `transcripts/<id>.words.json`(文書全体の単語の並び。認識と範囲の再認識が書く・削除で消す)と `POST /api/resplit`(今の文書を分け直す)。
  1つの字幕の最大文字数は設定の `subtitle`(`subtitle_settings`・`split_chars_for`)。行を分ける規則は `split_segment`(+2 文字まで許す)。細かい決まりは設計書の 12 ②。
  **再認識(範囲・全体)と声の検出のやり直し**(v0.21.0。`../docs/whole-retranscribe-design.md`): `POST /api/retranscribe` の `mode` = each(行ごと)/ range / **whole**(文書の範囲全体。`ids` はサーバーが「校正済みでない行」を入れる・上限は新規と同じ `MAX_SPAN_SEC`・声の検出は明示の off 以外「弱め」・評価用は断る)。
  range と whole の認識は `RangeRecognizer`(本物 / 疑似。疑似は `TRANSCRIBE_FAKE_GAP`・`TRANSCRIBE_FAKE_LOOSE` で 0 文字の所と緩い条件の結果を作れる)。反映は `apply_range(spec, lines, loose)` → `plan_range`(差し替えない行 = 守る区間を `fit_lines` で避ける・新しい行の重なりが `EMPTY_COVER` 未満の元の行は残して `EMPTY_FLAG`)。
  ほぼ空だった所は `RangeRecognizer.loose`(声の検出なし・`no_speech_threshold=None`・よくある誤認識の文は捨てる・`LOOSE_FLAG`)。守る区間と残した行の `original`・単語の時刻は古いまま(`replace_original_multi`・`replace_words` の keep)。
  **声の検出が捨てすぎたら緩める**: `transcribe_vad_fallback`(新規 `transcribe_real`・range・whole が共通で使う。`VAD_LADDER` 標準→弱め→なし、残りが `VAD_MIN_KEEP` 未満か文字 0 で次へ)。ワーカーは認識を始めた直後に `info`(duration・duration_after_vad)を送り、`RemoteModel.transcribe` は行より先にそれを読む(`_Segs.close()` で行を読まずにやめられる)。新規の文字起こしは、やり直しに備えて行を最後まで読んでから流す(処理状況の行数は読みながら `job["segments"]` に入れる)。記録は `recognition.runs` の `vadUsed`・`vadRemovedSec`・`vadRetries`、`params.vadUsed`、知らせは `job["vadNote"]`(`public_job`)。疑似のワーカーは `TRANSCRIBE_FAKE_VAD`(drop-normal / drop-vad)
  `public_job` は `job["warnings"]` も画面に出す(以前は `spec["warnings"]` だけで、ジョブの中で足した注意が届いていなかった)
  **疑わしい所だけ認識し直す**: ジョブ `redo`(`POST /api/redo`・`run_redo`・`redo_targets`・`redo_better`・`apply_redo`。話者判別・再認識と同じく編集を止める)。設定 `autoRedo`(既定オフ)・`redoLarge`。設計書の 12 ③-2
  **行の cutState は、編集の内容があれば文書のどの書き込みでも `apply_edit_cuts` で編集の内容から付け直す**(新しく文書を書き込む処理を足すときも通す)。
  細かい決まりは設計書の「11. 実装で決めたこと」
- `pack-tab.js` … 「編集」3 パック のタブ(置き先・入れるもの・出力先・これから作るパック・字幕の見本・作る・前回のパック・zip)。app.js より先に読み、`EditPack.create(host)` で起動する
- `cut.js` … 「編集」2 カット のタブ(タイムライン・プレビュー・字幕の一覧・たたき台・保存)。app.js より先に読み、app.js が `EditCut.create(host)` で起動する。
  区間はフレームの整数で持つ。行の「カット済」の規則 `rowCutFlags` は serve.py の `edit_cut_flags` と同じ(変えるときは両方)。細かい決まりは設計書の「11」の E3
- `test_metrics.py` … サーバー側の単体テスト。`test_edit.py` … 「編集」のサーバー側(test_metrics から読み込まれる)。`e2e_*.py` … 画面の通し確認(Playwright + 疑似モード)

## テストの実行
```
python -m unittest test_metrics test_resolve_export -q   # サーバー側(test_backend.py・test_worker.py・test_edit.py も test_metrics から読み込まれる。一覧の項目は test_backend の test_list_fields_for_history)
node --test test_document_save.cjs            # 保存・切り替えの競合(9件)
python e2e_ui_v07.py / e2e_ui_v08.py / e2e_ui_v09.py / e2e_eval_v093.py / e2e_ui_v098.py / e2e_ui_handoff.py
python e2e_edit_tabs.py                       # 「編集」E2: 3つのタブ・Alt+1/2/3・URL の #・メニューの帯・題名の行・文字起こしせずに開く(共通部分は e2e_edit_common.py)
python e2e_edit_cut.py                        # 「編集」E3: カットのタブ(入口に取り込んだ形。ドラッグ・吸着・分割・削る/戻す・I/O/X・元に戻す・保存・409・カット後の再生・無音のたたき台)
python e2e_edit_voices.py                     # 話者の声を覚える(A-3。名前を付ける → 覚える → 判別し直すと名前が付く → 忘れる)
python e2e_edit_pack.py                       # 「編集」E4: パックのタブ(入口に取り込んだ形。カットのとおりのパック・短い区間と 60fps の注意・前回のパック・中止・Text+ なし)
python e2e_ui_mounted.py                      # 入口(app/launch.py --only transcribe,cut2resolve)に取り込んだ形。CSP・合言葉・認識ワーカー(強制終了からの立ち直り)・
                                              # 履歴の一覧(配信ごと・配信者)・パックのタブ(cut2resolve の API・上書きの確認・zip)
python -m unittest tools/test_ui_kit_sync.py  # (リポジトリ直下で)ui-kit.js・index.html に埋め込んだ ui-kit の CSS が正本とずれていないか
```
- e2e は serve.py を疑似モード(環境変数 `TRANSCRIBE_BACKEND=fake`)で起動して試す。ffmpeg と Playwright の chromium が必要。
  Windows のコンソールでは `PYTHONIOENCODING=utf-8` を付けて流す(付けないと ▶ などを表示できずに途中で止まる)。`e2e_ui_mounted.py` は Windows でも動く(ワーカーは PowerShell で数え、入口は Ctrl+Break で止める)
- 「編集」の e2e(`e2e_edit_*.py`)は `e2e_edit_common.py` の `Server` で起動する(ツールのファイルを拡張子でまとめて写すので、新しい .js の写し忘れが起きない。`mounted=True` で入口に取り込んだ形)
- `TRANSCRIBE_BACKEND=worker-fake` は、サーバーは本物の経路(認識ワーカーとのやり取り)を通り、ワーカーの中だけ偽のモデルを使うテスト用のモード
  (`test_worker.py`・`e2e_ui_mounted.py`・`app/test_mount.py`)。`TRANSCRIBE_WORKER_CRASH=<n>` で n 行目のあとにワーカーを落とせる。
  `test_worker.py` は `test_metrics` から読み込まれる(上の1行のコマンドで一緒に走る)
- Playwright 同梱の chromium は H.264 を再生できない。画面で動画の再生まで確かめるテストでは、テスト用の動画を webm(VP9 + Opus)で作る
- e2e は一時フォルダに `serve.py`・`index.html`・`app.js`・**`cut.js`・`pack-tab.js`**・`ui-kit.js`・`hololive-roster.json`・**`pipeline_io.py`・`resolve_export.py`** を写して動かす
  (`pipeline_io.py`・`resolve_export.py` を写さないと、受け渡しの API・Resolve 書き出しが 500 になる。`app.js`・`ui-kit.js` を写さないと画面が真っ白になる)。
  共通部品 `../ytt_core/` は写さず、環境変数 `YTT_CORE_DIR`(リポジトリ直下)で見つける(Resolve パッケージを作るテストでは cut2resolve も `YTT_CUT2RESOLVE_DIR` で)
  (各スクリプトの先頭で設定している。新しいテストで serve.py を写すときも同じ1行を入れる)。`.runtime/` も `YTT_RUNTIME_DIR` で一時フォルダの中に置く
  (他のテストが同時に動いていても、「他のツール」の問い合わせ(/api/siblings)が混ざらないように)
- `e2e_ui_handoff.py` … 受け渡し(?media= / ?clip=・元の配信・動画の隣に保存・409)、テーマの保存の1本化、
  他のツールのメニュー、2026-09-24 の見直しで直した画面の不具合、v0.15.0 の見直し(単体でのカットとパックの案内・選んだ行のカット・動画なし・キー操作の手がかり・? ・390px の引き出し)
- `e2e_ui_v07.py` と `e2e_ui_v09.py` の「版 v0.9.4」の判定だけは、版を上げたことによる**想定内の失敗**(古い版の記録を残してあるため)。それ以外は全部通ること
- `e2e_ui_v08.py` の「4000行での Alt+Enter → 次の行 0.5 秒」は、マシンの負荷で時々超える(タイミング依存)
- e2e の各スクリプトは、メニューのタブで隠れるカードも操作できるように、テスト用のスタイルで全部のタブを表示している(タブ自体の確認は e2e_ui_v098.py の最後)
- 見た目は共通の ui-kit(`../ui-kit/`)。`ui-kit.js` は clip-studio と同じく `python tools/sync_ui_kit.py` で写したファイル(**手で直さない**)。
  CSS だけは画面が1ファイルの名残で index.html に埋め込み(`/* ui-kit:css:begin */…end */` の中。同じく sync_ui_kit.py で写す・手で直さない)。
  このツール固有の CSS はその後ろ(色は必ず ui-kit の変数。新しいクラスは `tt-` を付ける)
- 画面の色(テーマ)の保存は ui-kit の `ytt:theme` だけ(「表示」の「画面の色」とヘッダーのボタンは同じ設定)。`V`(tx.view.v1)には保存しない
- API・動画(`/media?...`)の URL は必ず `apiUrl()`(と `api()`・`apiBlob()`)を通して作る。`apiUrl()` は `app.js` 先頭の
  `const BASE = location.pathname.replace(/\/[^/]*$/, '')` を前に付ける(単体では `""`、入口の `/transcribe/` に取り込まれたときは `"/transcribe"`)。
  絶対パス `/api/...` を直接書かない。書き込み系(GET/HEAD 以外)には、入口が `<meta name="ytt-token">` で画面に入れる合言葉を
  `X-YTT-Token` ヘッダーで付ける(`TOKEN` が空、つまり単体起動のときは付けない)。他のツールへのリンクは `UIKit.tools.url()` を使う(BASE を使わない)

## 画面の設計で決めたこと(v0.9.9 の内容 + v0.18.0 で足したもの。変えるときはユーザーに確認)
- 編集画面は2列: 左 = 映像と道具(`aside.tx-stage`。画面に固定され、列の中だけスクロール)、右 = セリフの一覧(`#segs`)。狭いと1列(コンテナクエリ)
- 左のメニュー(`aside#menuPanel`)は ☰ / G で開閉し、状態を保存。**映像の欄(tx-stage)を畳むのではない**(過去に誤解して作り直した)。
  中は GPT 版のタブ(新規・履歴・精度・学習。`V.sideTab`)。編集欄が 1000px 未満なら文字起こしを開いた時点で自動で閉じる。
  v0.15.0: 画面が 720px 未満では本文の上に重ねる引き出し(`.tt-scrim` を押す・Esc で閉じる)
- v0.15.0: 映像の列は 映像と道具(`.pbox`: 題名・映像と再生の道具 `.tt-player`・編集の道具 `.tt-edit`)→ 道具のカード(v0.16.0 で「カットとパック」`#cutPack` は外した)
  (話者 `#spDetails` / 文字をまとめて直す `#fixDetails` / 書き出し `#exDetails` / 以前の版に戻す `#hiDetails`。「…」`#jumpMenu`(v0.18.0 から `details.ui-pop` のアイコンだけの丸ボタン。以前は「道具 ▾」)から移動)。
  行の検索・絞り込み・次の未校正・キーの手がかりは行の一覧の上(`#listHead`。2列では固定)。
  1列(編集欄 780px 以下)では `.tx-stage`・`.pbox` を display:contents にして、`.tt-player` だけ固定・道具のカードは一覧の後ろ
- 保存は GPT 版の仕組み(`saveDoc` を直列化、`openDoc` は保存できないときは切り替えずに false)。行ごとの「残す/カット済」(`cutState`)は「校正済み」の隣。
  まとめて変えるのは「まとめて ▾」の「選んだ行をカット/残す」だけ(同じ印を変える入口はこの2つ。「編集」E2 で「カットとパック」のカードから移した)
- 「編集」(E2〜): ヘッダーに3つのタブ(`#edTabs`・`setEditTab()`・`EDT`。URL の #tx/#cut/#pack・Alt+1/2/3。行の文字の入力中の Alt+数字 は話者のまま)。
  校正のキー(1 文字起こし 固有のもの。下)は 1 文字起こし のタブだけ(`wideTab()` で止める)。カット・パックのタブでは左のメニューを細い帯(`#menuStrip`)に畳み、
  帯から開くと本文の上に重ねる(`EDT.overlay`。`V.menu` とは別)。題名の行 `#docBar`(`renderDocBar()`)はどのタブにも出す。保存の状態 `#saveState` はヘッダー。
  題名の行の「まとめて実行 ▾」`#docAuto`(入口から開いたときだけ。今の文書を入口の `start-docs` で1本・`startDocAuto`・進み具合の札 `#pillAuto` = `renderDocAuto`。
  履歴の「選んで、まとめて実行」と同じ `pollRuns` で読み直す。2026-09-27 `../docs/followup-2026-09-27.md` の 3)
- **話者の声(A-3。2026-09-27)**: 名前を付けた話者の行(1秒以上・「声が混ざっている」を除く・長い行から 40 行 / 240 秒まで。`voice_groups`)の声の特徴を
  sherpa-onnx の SpeakerEmbeddingExtractor で取り(`_embed_local`。**ワーカーの中だけ**。サーバーは `embed_groups` → `WORKER.call("embed")`)、長さ 1 にして
  作業データの `voices/<判別モデル>.json` に名前ごとに保存(`load_voices`/`save_voices`。同じ名前は使った秒で重みを付けて混ぜる)。
  話者判別のジョブの最後(`recognize_voices`。`spec.recognize` 既定オン)で、見つかった話者の特徴を覚えている声と比べ、
  コサイン類似度 `VOICE_MATCH`(0.60)以上・2番目との差 `VOICE_MARGIN`(0.08)以上・1つの名前は1人だけ(`match_voices`)のときに、
  **仮の名前(`話者n`)のままの話者だけ**名前を付ける。失敗しても判別の結果は残す(警告)。ジョブ `voice-learn`(`/api/voices/learn`)、一覧 `GET /api/voices`(特徴そのものは返さない)・`/api/voices/delete`。
  疑似モードの特徴 `embed_fake` は偽の話者判別と同じ 10 秒の入れ替わり(テストで「覚える → 名前が付く」を確かめるため)。声の特徴は個人を見分けられる情報なので、作業データの外に出さない(.gitignore の `**/voices/`)
- 映像の上の字幕(`#playerCaption`)は、行の話者の名前がメンバーと合えばその色(`capSpeakerColor`。入口の `api/ytt/streamer-colors` を名前ごとに1回引いて覚える・パックのタブの `tx.pk.speakerColors` が '0' なら出さない・合わなければ pack-tab.js が body に入れた配信者の色 `--tt-cap-color` のまま)
- 行の ▶ は**その行だけ**再生して止まる(`playSeg(s, true)`)。通しの再生は映像そのものの再生ボタン / Space だけ
- キー操作は**単体キー**(Shift 不要)。例外は Shift+Space(校正済みにして次へ)と Shift+↓/↑(未校正への移動)だけ。Z は2回押しで削除。
  **左手のキー(ユーザー決定 2026-09-27「左手での操作が使いやすかった」。やめない)**: W/S 行・A/D 未校正・Q/E 3秒・B 自動で再生の切り替え・Tab 入力欄に入る/抜ける・入力中の Ctrl+Enter 聞き直す。
  v0.18.0 で ↓/↑・Shift+↓/↑ に置き換えたが 0.18.2 で左手のキーを戻し、↓/↑・Shift+↓/↑ は別の手段として残した。S の分割は 2 カット のタブだけ(校正のキーは 1 文字起こし のタブだけなので重ならない)。
  Space の再生・停止は `editPlaybackKeys` だけ(以前は app.js の末尾にも Space の処理が残っていて、1回押すと「再生 → すぐ停止」になった。0.18.2 で削除)。
  共通の再生キーは押しっぱなしの繰り返し(`e.repeat`)で Space・K・L・I・O を繰り返さない(J・矢印・, . は繰り返す)。
  **キー配置(v0.19.0。ユーザー決定 2026-09-27「設定で自由に割り当て」「共通の再生キーも変更可」)**: 操作の一覧は app.js の `TX_ACTIONS`(校正)+ `UIKit.keys.PLAYBACK_ACTIONS`(共通の再生)= `KEY_DEFS`。
  割り当ては `S.settings.keymap`(id → `UIKit.keys.comboOf` の表記。'' = 未設定)で、読むときは必ず `keymap()`(`sanitizeKeymap`: 重なり・使えないキーは外す)。
  使えないキーは `keyRefusal()`(`KEY_FIXED` = ↓↑・Shift+↓↑・Tab・Esc・Enter・?、数字 = 話者、再生のキーには `CUT_KEYS` = cut.js のキー S・X・Delete など)。
  再生のキーは `UIKit.keys.playback({ keymap })` に渡す(1 文字起こし = `editPlaybackKeys`、2 カット = cut.js の `commonKeys` が host の `keymap()` を使う)。
  下の帯・一覧の上の手がかり(`#keyHintItems`)・キー操作の一覧(`#keysCommon`・`#keysTx`)・⚙ の `#kmGrid` は `renderKeyUI()` がまとめて描く(割り当てを変えたら必ず呼ぶ)。
  新しい校正の操作をキーに足すときは `TX_ACTIONS` と `KEY_FN` に足す(直に e.code で判定しない)。cut.js に新しいキーを足すときは `CUT_KEYS` にも足す
  共通の再生キー(Space・J/K/L・← →(Shift で5秒)・, .・I/O)は `UIKit.keys.playback()` の1か所(`ui-kit.js`)。1 文字起こし は `editPlaybackKeys`(`media: player()`)、
  2 カット は `commonKeys`(`media: mediaProxy`。生の `<video>` だと togglePlay の頭出し・フレームの丸めを通らないので、`cut.js` の関数へ委ねる薄い代理オブジェクトを渡す)。
  各画面は自分のキー処理より**先に**共通キーを呼び、処理済み(true)なら自分では何もしない(1つのキーは全体で1つの意味。I/O は 1 文字起こし では何もしない = 別の意味を持たせない)
- 行の操作ボタン(時刻の微調整・再生位置・＋前に行・＋後に行・分割・結合・削除)は選んだ行(`.seg.nav`)の下にだけ出す
- 「今の行」(`S.navIdx`、青い太枠)と一括選択のチェック(`S.sel`)は別物。チェックで今の行を動かさない
- 行の並びが変わる操作(削除・結合・分割・追加・元に戻す・読み直し)の前後では `navSnapshot()` / `navRestore()` で行の id を基準に今の行を追い直す
- 行のボタンは mousedown でフォーカスを移さない(移すと前の行の操作ボタンが消えて一覧がずれ、押し損じる)。今の行は click で切り替える
- 行の追加は前後のすき間に置く。すき間が無いときは仮の 1.5 秒で置き、重なりは時刻の欄を赤く(`.times.ovl`)して知らせる。`sortSegs()` は開始時刻だけの安定ソート
- 評価用(evalSet)の文字起こしは、学習・辞書・提案に使わない(精度を測るためだけ)

### v0.18.0(画面の全面見直し 段1〜3。正本は `../.design/ui-overhaul/DESIGN_BRIEF.md`・`IMPLEMENTATION.md`)
- ヘッダー: `ui-appnav`(`<nav data-ui-appnav="transcribe">`。中身は `ui-kit.js` の `UIKit.appnav` が描く「ホーム/スタジオ/編集」)が、以前のブランドの印・「他のツール」メニュー・
  「入口」リンクを置き換えた。版表示 `#ver` は appnav のすぐ右に残す(版の食い違いの赤い帯・テストが読む)。開いている動画の引き継ぎは `UIKit.appnav.setLink('studio', '?url=…')`
  (`renderDocExtras` が元の配信の URL があるときだけ呼ぶ)。⚙(`[data-ui-settings]`)は `UIKit.settings.mount({tool:$('#edSettings')})` で
  `ui-drawer` を開く(ツールの節 = 旧「表示」ポップオーバーの中身 `#vFs`/`#vVid`/`#vDense`/`#vBrk`/`autoNext` + 全体の節 = テーマ・文字の大きさ・キーの帯)。
  画面の色(`#vTheme`)は全体の節に一本化したので、1 文字起こし 側には無くなった(`syncThemeSelect()` も削除)
- 映像の上の字幕(1 文字起こし。段2): `#playerCaption`(`.tt-caption`。`aria-hidden`。装飾扱いで、同じ情報は行の一覧から読める)。
  止まっているときは選んだ行(`S.navIdx`)・再生中は再生位置の行(`S.curIdx`)を `updateCaption()` で反映する(`setNav`・`renderDoc`・`timeupdate`・`pause`・`playing` から呼ぶ)
- 画面の下の帯(`UIKit.keybar`。段2〜3): 1 文字起こし は `txKeybarScene()`(行を選んでいる/文字を直している の2場面)、2 カット は `cutKeybarScene()`
  (通常/端を選んでいる の2場面。`renderSel()` から毎回呼ぶので選択の変化にすぐ追従)、3 パック は場面を持たない(`PACK.shown()` で `clear()` するだけ)。
  `app.js` の `onEditTab()` は **`to` が cut/pack のときは何もしない**(`CUT.onShown()`/`PACK.shown()` が呼ばれた時点で、それぞれ自分の場面をもう出しているため)。
  以前は「`to !== 'tx'` かつ `from === 'tx'` なら無条件で `clear()`」にしていて、tx → cut / tx → pack で直後に出した場面を消してしまう不具合があった
  (2026-09-27、画面の見直しの e2e を書いていて見つけて直した。`to === 'tx'` のときだけ `txKeybarScene()` を呼べばよい)
- 2 カット のタイムライン(段3): 4段 → **3段**(目盛り・区間(中に波形。`#tlVideo`/`#tlAudio` を同じ帯に重ねる)・字幕)。上にミニマップ `#tlMini`
  (`renderMini()`/`drawMiniWave()`/`bindMini()`。全体を縮めた波形+見ている範囲の枠 `#tlMiniView`。枠のドラッグ = 見る範囲を移動、
  左右の端 `.tt-tl-mini-h` のドラッグ = その端だけ動かして拡大縮小、枠の外を押すとそこを中心に寄る)。
  ホイールは Ctrl 不要でマウスの位置を中心に拡大縮小(`zoom(k, anchorX)`)、Shift+ホイールで横に移動。区間の端のつまみ `.tt-h` は見た目より
  左右 6px 外側まで当たり判定がある(CSS `.tt-h.in{left:-6px}`/`.tt-h.out{right:-6px}`。幅12px の帯の中を `e.target.closest('.tt-h')` で拾う)。
  `confirmReplace()`(たたき台での置き換えの確認)は `UIKit.dialog.confirm` を呼ぶ(無ければ旧 `h.confirm` にフォールバック)
- 3 パック(段3): 主画面には「前回の設定」の要約カード(`#pkSummaryText`。fps・大きさ・予備の有無・粗編集の動画つきか・出力先 + 配信者の色の丸 `#pkSummarySw`。
  `renderSummaryText()`)と「これから作るパック」カード(字幕の見本・配信者の欄 `#pkWho`・大きな「パックを作る」)だけを出す。手順1〜3(置き先・入れるもの・出力先)の
  細かい設定は「設定を変える」`#pkSettingsBtn` で開く `ui-drawer`(`#pkSettingsDrawer`。`UIKit.drawer.open(el,{modal:true,opener})`)へ移した。
  要素の id は変えていないので、値の読み書き・イベントの配線(`setOpt` 等)は以前のまま動く。前回のパック(`#pkLast`。「前回のパック」/「作り直しが要る」の札)は
  2カラムのグリッドで要約の隣の列に出す(常に見える。開かなくても分かる)

## 未解決・注意
- 過去の事例(その後の報告なし): v0.9.6 配布時(zip で配っていた頃)、ユーザーの PC で `serve.py` 起動時に `SyntaxError: unknown parsing error`(line 0)が出たという報告があった。原因は未特定(ファイルの破損・文字コード・BOM・zip 展開の失敗などを疑う)。再発したら、まずファイルの先頭のバイト列・サイズ・文字コードを確認する
- 本物の faster-whisper での通しの確認は 2026-09-26(Windows)、声の検出のやり直し・範囲/全体の再認識は 2026-09-28 に PC で確かめた。
  フォルダ一括・評価用・句読点の除去・話者判別の優先割り込みなど、ほかの個々の機能は実機で確かめた記録がない(疑似モードのテストだけ)
- 以前ここにあった「後で実装したい」は整理済み: スタジオへ返す(統合計画の段階4)・声の登録(v0.20.0 の「話者の声」)は実装済み、
  名簿への愛称は精度改善の段1、ボーカル分離は入れない(09-27 ユーザー決定。精度改善の段3・段5 の評価で効けば再検討)
