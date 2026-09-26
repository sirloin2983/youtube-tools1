# transcribe-tool(文字起こしツール)— AI 向けメモ(Claude・GPT 共通)

現在 **v0.17.0**(2026-09-26、追加機能 ⑥「行から」のカットの端を声の止まる所まで広げる・④ パックを最小限に。`../docs/edit-tool-design.md` の 12。
v0.16.0 = 2026-09-26、「編集」: 文字起こし + cut2resolve の統合。入口での名前は「編集」、画面は3つのタブ(1 文字起こし / 2 カット / 3 パック)。`../docs/edit-tool-design.md`。
v0.15.0 = 画面の全面見直し: 履歴の一覧の作り直し・校正画面の「カットとパック」(案A。v0.16.0 で 2 カット・3 パック のタブへ移した)・道具のカードの分割・狭い画面。
v0.14.x = 作業データの置き場所・重い処理の上限・窓で使う準備、v0.12.0 = 「Resolveパッケージ(zip)」を cut2resolve の Text+ パックに一本化。v0.11.0 = 2026-09-25、認識を別プロセス(tx_worker.py)に分け、入口の `/transcribe/` に取り込めるようにした。v0.10.0 = 2026-09-24、全ツールの見直し・UI 刷新。v0.9.9 で Claude 版と GPT 版の v0.9.8 を統合済み)。
画面の共通のルール(用語集・ヘッダー・ボタンと札・一覧・段階的に見せる・狭い画面)は `../docs/ui-guidelines.md`。画面を直すときは必ず合わせる。いま何が途中かは `../docs/WORKLOG.md` の最後の数件で確かめる。
GPT の設計書 `TRANSCRIPTION_V2_DESIGN.md`(精度改善 v2。実装は保留)も必ず読む。
現行の仕様は、このファイルとユーザー向けの `README.txt`。v0.9.8 までの経緯・決定の理由は `../docs/project/HANDOVER-transcribe-tool.md`、版ごとの記録は `../docs/project/history/transcribe-tool-v*.md`、
最初の仕様は `../docs/project/transcribe-tool-spec.md`(v0.7.0 当時。**どれも古い**ので、今の動きの根拠にはしない。理由を調べるときに読む)。
使い方の説明はユーザー向けの `README.txt`(変更したら README も直す)。
精度向上の計画(段階0〜5。クラウドは初期比較と点検だけ・最終的に外部課金0円)は `../docs/project/accuracy-plan.md`。**ユーザーの指示があるまで実装しない**(2026-09-24 時点)。

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
  作る前にカットを保存し(`CUT.commit()`)、字幕の元として保存済みの文字起こしを動画の隣に `.transcript.json`(`cpExport`)。文字起こしが無ければ Text+ なし(EDL と元の動画のコピー)。
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

## 画面の設計で決めたこと(v0.9.9。変えるときはユーザーに確認)
- 編集画面は2列: 左 = 映像と道具(`aside.tx-stage`。画面に固定され、列の中だけスクロール)、右 = セリフの一覧(`#segs`)。狭いと1列(コンテナクエリ)
- 左のメニュー(`aside#menuPanel`)は ☰ / G で開閉し、状態を保存。**映像の欄(tx-stage)を畳むのではない**(過去に誤解して作り直した)。
  中は GPT 版のタブ(新規・履歴・精度・学習。`V.sideTab`)。編集欄が 1000px 未満なら文字起こしを開いた時点で自動で閉じる。
  v0.15.0: 画面が 720px 未満では本文の上に重ねる引き出し(`.tt-scrim` を押す・Esc で閉じる)
- v0.15.0: 映像の列は 映像と道具(`.pbox`: 題名・映像と再生の道具 `.tt-player`・編集の道具 `.tt-edit`)→ 道具のカード(v0.16.0 で「カットとパック」`#cutPack` は外した)
  (話者 `#spDetails` / 文字をまとめて直す `#fixDetails` / 書き出し `#exDetails` / 以前の版に戻す `#hiDetails`。「道具 ▾」`#jumpMenu` から移動)。
  行の検索・絞り込み・次の未校正・キーの手がかりは行の一覧の上(`#listHead`。2列では固定)。
  1列(編集欄 780px 以下)では `.tx-stage`・`.pbox` を display:contents にして、`.tt-player` だけ固定・道具のカードは一覧の後ろ
- 保存は GPT 版の仕組み(`saveDoc` を直列化、`openDoc` は保存できないときは切り替えずに false)。行ごとの「残す/カット済」(`cutState`)は「校正済み」の隣。
  まとめて変えるのは「まとめて ▾」の「選んだ行をカット/残す」だけ(同じ印を変える入口はこの2つ。「編集」E2 で「カットとパック」のカードから移した)
- 「編集」(E2〜): ヘッダーに3つのタブ(`#edTabs`・`setEditTab()`・`EDT`。URL の #tx/#cut/#pack・Alt+1/2/3。行の文字の入力中の Alt+数字 は話者のまま)。
  校正のキー(S・W・D・Space など)は 1 文字起こし のタブだけ(`wideTab()` で止める)。カット・パックのタブでは左のメニューを細い帯(`#menuStrip`)に畳み、
  帯から開くと本文の上に重ねる(`EDT.overlay`。`V.menu` とは別)。題名の行 `#docBar`(`renderDocBar()`)はどのタブにも出す。保存の状態 `#saveState` はヘッダー
- 行の ▶ は**その行だけ**再生して止まる(`playSeg(s, true)`)。通しの再生は映像そのものの再生ボタン / Space だけ
- キー操作は**単体キー**(Shift 不要)。例外は Shift+Space(校正済みにして次へ)だけ(Space 単体は再生・停止)。Z は2回押しで削除
- 行の操作ボタン(時刻の微調整・再生位置・＋前に行・＋後に行・分割・結合・削除)は選んだ行(`.seg.nav`)の下にだけ出す
- 「今の行」(`S.navIdx`、青い太枠)と一括選択のチェック(`S.sel`)は別物。チェックで今の行を動かさない
- 行の並びが変わる操作(削除・結合・分割・追加・元に戻す・読み直し)の前後では `navSnapshot()` / `navRestore()` で行の id を基準に今の行を追い直す
- 行のボタンは mousedown でフォーカスを移さない(移すと前の行の操作ボタンが消えて一覧がずれ、押し損じる)。今の行は click で切り替える
- 行の追加は前後のすき間に置く。すき間が無いときは仮の 1.5 秒で置き、重なりは時刻の欄を赤く(`.times.ovl`)して知らせる。`sortSegs()` は開始時刻だけの安定ソート
- 評価用(evalSet)の文字起こしは、学習・辞書・提案に使わない(精度を測るためだけ)

## 未解決・注意
- 過去の事例(その後の報告なし): v0.9.6 配布時(zip で配っていた頃)、ユーザーの PC で `serve.py` 起動時に `SyntaxError: unknown parsing error`(line 0)が出たという報告があった。原因は未特定(ファイルの破損・文字コード・BOM・zip 展開の失敗などを疑う)。再発したら、まずファイルの先頭のバイト列・サイズ・文字コードを確認する
- v0.9.0 以降の機能(フォルダ一括・範囲の再認識・評価用・句読点の除去・話者判別の優先割り込みなど)は、疑似モードでしか確かめていない。実際の faster-whisper・実際の動画での確認がまだ
- 後で実装したい: 文字起こしの結果を切り抜きスタジオへ返す機能、声紋登録、ボーカル分離の比較、名簿への愛称の追加
