# 段8: 複数の切り抜きをつなげる(B-3)
> 状態(2026-10-08): 未着手。**10-08 にユーザーが「全部」やると決定(今週。`plan/data.js` の A3)**。前提の U2(Resolve の実機)は 10-08 に済み。設計の段階の計画。細かい部分は 8-1 のあとで決め直す。始める前に同じ文書の中の食い違い(「fps 違いは断る・上限はユーザーに聞く」と「決まったこと」の「全部 30fps・8 本」)を「決まったこと」の側にそろえる
> **行番号・版の番号・ファイルの場所は 2026-09-29 時点(その後 `src/` へ移した)。始めるときに今のコードで読み直す**。素材は 10-04 から全部 30fps にそろえるので、下の「fps 違いは断る」は要らなくなった。全体の進捗は `plan/index.html`(データ `plan/data.js`)、線 A の残りは `plan/line-a-remaining.md`。

## 目的
- 1つの編集(`transcripts/<id>.edit.json`)に**素材(切り抜きの動画)を足し、並べ替え**、つないだ1本として Resolve のパック(EDL・Text+)を作れるようにする
- 今は素材1本だけ。サーバーは `sources` が1つでないと 400、`src ≠ 0` も 400(`src/editor/serve.py:824-826`・`838-840`)。設計のときから「データの形だけ備える。画面は作らない」(`docs/design/edit-tool-design.md` の 1・4)
- **素材1本の編集は、ファイルもパックも今とまったく同じ**にする(契約テストで守る)

## 含む作業と順番
| # | 作業 | 大きさ | 依存 |
| --- | --- | --- | --- |
| 8-1 | データの形(v2)を決め、`docs/design/edit-tool-design.md` に書く | S | なし |
| 8-2 | サーバー: 形の検査・読み書き・行のカット済・一覧・パックの「作り直し」 | M | 8-1 |
| 8-3 | cut2resolve: 複数の素材の計画(`pack.plan_multi`)と EDL・SRT | L | 8-1 |
| 8-4 | cut2resolve: Text+ の Lua と PowerShell を複数の素材に | M | 8-3 |
| 8-5 | 画面 2 カット: 素材の帯(足す・並べ替え・外す)と、つないだ時間軸での編集・再生 | L | 8-2 |
| 8-6 | 画面 3 パック と、ほかの入口(zip・残す区間の保存・まとめて実行) | M | 8-3, 8-4, 8-5 |
| 8-7 | テスト(契約テスト・e2e)・文書・版 | M | 全部 |

8-2 と 8-3 は並べて進められる。8-5 は大きいので、まず「素材の帯と並べ替え + 素材ごとの区間の表示」までを出し、時間軸の上での素材の境目のドラッグは後回しにしてよい。

## 各作業の細かい計画

### 8-1 データの形(v2)
- 今の動き: `{"schema":"youtube-tools-edit/v1","sources":[{"fps","duration"}],"clips":[{"src":0,"in","out"}],"origin","rev","packRev","pack"?}`。`sources[0]` のパスは保存しない(文書の動画を使う。画面から来たパスでパックを作らせないため)(`docs/design/edit-tool-design.md` の 4)
- 変えること:
  - `sources[i]` = `{"doc": "<文書の id>", "fps", "duration"}`。**`sources[0]` はこの文書(`doc` を書かない)**、足した素材は別の文書(文字起こし済みでも・行 0 の「文字起こしせずに開く」文書でもよい)を id で指す。**パスは今と同じく保存しない**(文書の `sourcePath` をサーバーが引く)
  - `clips` はタイムラインの順。**素材ごとにまとまって並ぶ**(`sources` の順)。同じ素材の中は今と同じく時刻の順・重ならない。並べ替え = `sources` の並べ替え
  - `schema` は**素材が2つ以上のときだけ** `youtube-tools-edit/v2`。1つなら今と同じ v1 のまま書く(今あるファイルの移し替えは要らない)
- 案の比較: (a) 素材ごとにまとまる(採用)… 検査・行のカット済・字幕の付け方が素材ごとの今の規則をそのまま使える。「A の一部 → B → A の続き」はできない(A を2回足せばできる形にはしない。B-3 の決定は「素材を足す・並べ替え」)。(b) clips を自由に並べる … 何でもできるが、同じ素材の区間の重なり・順番の検査と、画面の時間軸が「元の動画の秒」で描けなくなる
- 同じ素材を2回足すのは断る(素材の文書 id が重ならない)。fps の違う素材は断る(8-3 のリスク。ユーザーに聞く)
- 変えるファイル: `docs/design/edit-tool-design.md`(4・5 と 11 に「B-3」の節)、`docs/spec/pipeline.md`(編集の内容の形)
- 終わりの条件: 形・検査の決まり・v1 との関係を文書にした

### 8-2 サーバー(`src/editor/serve.py`)
- 今の動き: `sanitize_edit`(819〜853)が1素材だけ受ける。`edit_cut_flags`(879〜)は `sources[0].fps` と全部の clips で行のカット済を決める。`edit_keeps_sec`(962〜)は clips を全部つなぐ。`save_edit`(1046〜)は `apply_edit_cuts` でこの文書の行だけ書く。`pack_stale`(1123)はこの文書の `updatedAt` だけ見る
- 変えること:
  - `sanitize_edit`: sources 1〜8 個(上限は仮。ユーザーに聞く)、`doc` は `TID_RE`・存在する文書・重ならない・自分を指さない。clips の `src` は 0〜n-1 で素材の順にまとまる。素材ごとの長さの上限で区間を検査。1つなら今と同じ結果(同じ dict)
  - `read_edit`: v1 と v2 の両方を読む。v2 の読めない版は今と同じく壊れている扱い
  - 行のカット済(`edit_cut_flags`・`apply_edit_cuts`): **この文書(src 0)の区間だけ**で決める。足した素材の文書の行は**書き換えない**(ほかの文書は読むだけ)。字幕は 8-3 で素材ごとに「区間に入る行」を付けるので、足した素材の文書の cutState には頼らない
  - `edit_keeps_sec` は素材ごとの区間を返す関数を足す(1素材のときは今と同じ値)
  - `GET /api/edit` に各素材の文書の題名・動画があるか(`sourceOk`)を足す。素材の文書が消えていたら `missingSources` を返す(編集は開けるがパックは作れない)
  - `pack_stale`: 足した素材の文書の `updatedAt` もパックの記録(`pack.docUpdatedAt` を素材ごとの辞書に)と比べる
  - 文書を消すとき、ほかの編集の素材になっていれば知らせる(消すのは止めない。その編集は `missingSources`)
- 変えるファイル: `src/editor/serve.py`、`src/editor/tests/test_edit.py`
- テスト: `src/editor/tests/test_edit.py` に「v1 はそのまま・v2 を読み書き・doc の検査(無い・自分・重なり・形)・素材のまとまりの順・src 0 の行だけ cutState が変わる・足した素材の文書は書き換わらない・pack_stale が素材の文書の更新を見る」。流す: `python -m unittest src/editor/tests/test_metrics.py src/editor/tests/test_resolve_export.py -q`
- リスク: 素材の文書 id を画面から受けるので、パスの検査は文書の `sourcePath` に対して今の `check_source`・ネットワークのパスの扱い(`edit_draft` の 940〜949 と同じ)を素材ごとに通す。1MB の上限はそのまま
- 終わりの条件: 1素材の編集のファイル・応答が今と同じ(既存のテストがそのまま通る)で、v2 を保存・読み直しできる

### 8-3 cut2resolve: 複数の素材の計画と EDL・SRT
- 今の動き: `plan_cut(req)`(`src/cut2resolve/pack.py:286`)は動画1本の `Plan`(keeps はその動画のフレーム)。`build_edl`(`cut2resolve_core.py:433`)は全イベントが同じ `clip_name`・同じリール。`remap_cues`(458)は1本の keeps で字幕をつなぐ。`build_pack`(`pack.py:579`)は `media_for_pack` で動画を1本同梱する。`request_from_spec` の `spec.keeps`(`src/cut2resolve/serve.py:450-453`)は1本
- 変えること:
  - 新しい指定 `spec.parts = [{video, transcript?, keeps}, ...]`(2〜8 個。`keeps`・`preset` と一緒は 400)。各部分を今の `pack.Request(**EDIT_KEEPS)` にして `plan_cut` を**そのまま**素材ごとに呼び、`pack.plan_multi(plans)` でまとめる(区間の計算・字幕の切り詰めは今の関数を使い回す。規則を二重に書かない)
  - EDL: イベントごとに素材の `* FROM CLIP NAME` と、素材ごとのリール(`AX`・`BX`… か素材の名前から。8 文字まで)。録画側のタイムコードは全部つないで進める(`build_edl` に「イベントごとの素材」を渡せるようにし、1本のときは今と同じ行)
  - 字幕: 素材ごとの `cues_out` を、前の素材の長さの合計だけずらして1本にする。SRT も同じ
  - 同梱する動画は素材の数だけ。名前が重なるとき(別のフォルダの同じ名前)は `01_名前.mp4` のように番号を付ける。余白つき素材(`media_for_pack`)は素材ごとに今の規則
  - fps が違う素材は断る(`ToolError`。「fps のそろった切り抜きだけつなげます」)。大きさが違うのは注意だけ(Resolve が合わせる)
  - 粗編集の動画(`render`)と FCPXML は、素材が2つ以上のときは最初は作らない(画面で選べなくし、理由を出す)。作るなら ffmpeg の concat で別の作業
- 変えるファイル: `src/cut2resolve/pack.py`、`src/cut2resolve/cut2resolve_core.py`、`src/cut2resolve/serve.py`(`request_from_spec`・`api/plan`・`api/build`。`input_path` の検査を部分ごとに)、`src/cut2resolve/tests/test_pack.py`・`test_serve.py`・`test_cut2resolve.py`
- テスト: 「部分1つの parts = 今の keeps と同じパック」「2素材の EDL のイベント・クリップ名・録画側の連続」「字幕のずれ」「同じ名前の動画に番号」「fps 違いは断る」「parts と keeps の同時は 400」「パスの検査」。流す: `python -m unittest src/cut2resolve/tests/test_cut2resolve.py src/cut2resolve/tests/test_pack.py src/cut2resolve/tests/test_serve.py`、★`python -m unittest dev/tests/test_resolve_pack_contract.py`(単独で)
- リスク: EDL のイベント番号は 999 まで(`C.MAX_EDL_EVENTS`)→ 全素材の合計で注意を出す。重い処理(無音の検出は EDIT_KEEPS では使わないが、ffprobe・コピー)は今の api/build のジョブの中で行う
- 終わりの条件: 2素材のパックが作れ、1素材のパックは契約テストで今とバイト単位で同じ

### 8-4 Text+ の Lua と登録の PowerShell
- 今の動き: 計画 JSON は `media` 1つ(`resolve_textplus.py:222-223`)・`cuts` は同じ動画のコマ(224)。Lua は `ImportMedia` を1回して全区間を同じクリップで `AppendToTimeline`(`resolve_textplus.py:402-415`)。`sourceTimeline`(元動画全体の予備のタイムライン)も1本(228・562)。動画のパスは登録の PowerShell が `__C2R_MEDIA_PATH__` を置き換える(`resolve_textplus.py:596-623`)。字幕は「何番目の区間の先頭から何コマ目か」(`caption_segments` 117〜)なので、区間が並べば素材が変わってもそのまま使える
- 変えること:
  - 計画に `medias: [{file, name, width, height, fps}]` を足し、`cuts[i].media` に素材の番号。1素材のときは今の `media` だけを書く(Lua の文字が今と同じ)
  - Lua: `medias` があれば素材ごとに `ImportMedia` し、区間ごとにそのクリップで置く。予備のタイムラインは素材ごと
  - PowerShell: `__C2R_MEDIA_PATH_1__`… を素材の数だけ置き換え、全部あるか確かめる
- 変えるファイル: `src/cut2resolve/resolve_textplus.py`、`src/cut2resolve/tests/test_pack.py`(Lua を読み直す `read_script_plan` のテスト)
- テスト: 「1素材の Lua が今と同じ」「2素材の計画の medias・cuts.media・字幕の区間番号」「PowerShell の置き換えの印が残らない」。★`python -m unittest dev/tests/test_resolve_pack_contract.py`
- リスク: Resolve の実機でしか確かめられない(Lua の `ImportMedia` を複数回・別々のクリップの `AppendToTimeline`)。Resolve Free の制限は今と同じ。実機の確認までは「試験中」と画面に出す
- 終わりの条件: 実機の Resolve で2素材のパックから Text+ のタイムラインができ、字幕の位置がずれない

### 8-5 画面 2 カット(`src/editor/cut.js`・`app.js`・`index.html`)
- 今の動き: `M` が素材1本の `fps`・`dur`・`total`・`clips`(フレームの組)を持つ(`cut.js:18-23`)。読み込みは `sources[0]`(`cut.js:135`)、保存は `src: 0` 固定(`cut.js:167`)。動画は `/media?id=<文書>` 1本(`cut.js:604-606`)。波形は `/api/peaks?id=`(文書ごと)
- 変えること:
  - 時間軸の上に「素材の帯」: 素材ごとの札(題名・長さ・残す長さ)、「＋素材を足す」(履歴の文書から選ぶ、か「文字起こしせずに開く」と同じ `POST /api/open-video` で動画を選ぶ)、ドラッグか「← →」で並べ替え、外す(src 0 は外せない)
  - 時間軸は**つないだ後の順**に素材を並べ、素材ごとに今の描き方(元の動画のフレーム・波形・字幕の段)をそのまま使う。内部は `M.parts[i] = {doc, fps, dur, total, clips, peaks}`、今の `M.clips` などは「選んでいる素材」を指す形にして、今の操作(ドラッグ・分割・削る/戻す・I/O/X・元に戻す)の書き直しを小さくする
  - カット後の再生: 素材の終わりで `<video>` の `src` を次の素材に切り替える(切り替えの間は一瞬止まる。プレビューは目安 = 今の決まりと同じ)
  - 元に戻すの履歴に素材の足す・外す・並べ替えも入れる。保存は今の 0.8 秒まとめ・409 の扱いのまま
  - 足した素材の文書の字幕を直すときは「その文書を開く」へ案内(ここでは直さない)
- 変えるファイル: `src/editor/cut.js`、`src/editor/app.js`(素材を選ぶ窓・`apiUrl` 経由)、`src/editor/index.html`・`style.css`。部品の見た目は ui-kit にあればそれを使う(写しは直さない)
- テスト: 新しい `src/editor/tests/e2e_edit_multi.py`(素材を足す・並べ替え・外す・保存・読み直し・409・カット後の再生で素材が切り替わる。webm で作る)。流す: `src/editor/tests/e2e_edit_cut.py`・`src/editor/tests/e2e_edit_tabs.py`・`src/editor/tests/e2e_ui_mounted.py`(1素材で今と同じ)
- リスク: CSP(インラインの script を使わない)、`UIKit.life` で離れたときに保存。素材の動画が無い・ネットワーク上なら、その素材だけ使えない印(ほかの素材は編集できる)。素材が多いと波形の問い合わせが増える → 見えている素材だけ読む
- 終わりの条件: 1素材の文書で見た目・操作が今と同じ(既存の e2e が通る)、2素材の編集を画面だけで作って保存できる

### 8-6 3 パック と、ほかの入口
- 今の動き: 3 パック は `spec = {video: d.sourcePath, keeps, transcript?}`(`pack-tab.js:240`)。zip(`/api/resolve-package`。`serve.py:5945-5965`)・「残す区間(.cut-plan.json)を保存」(`serve.py:5573-5578`)・まとめて実行の `_edit_keeps`(`src/home/autorun.py:510-524`)は clips を1本として読む(src を見ない)
- 変えること:
  - 3 パック: 素材が2つ以上なら `spec.parts`(素材ごとの `video`・`keeps`・`transcript`。文字起こしの書き出し `cpExport` を素材ごとに)。「粗編集の動画つき」は選べなくし理由を出す。見積もり(`/api/edit/preview`)も素材ごと → 合計
  - zip と「残す区間の保存」: 素材が2つ以上なら 400 で「3 パック で作ってください」(zip の中は動画1本の前提のため)
  - まとめて実行: 素材が2つ以上の編集は**作らずに注意**(「複数の素材のカットは 編集 の 3 パック で作ってください」)。1素材は今と同じ
- 案の比較(まとめて実行): (a) 注意だけで飛ばす(採用)… まれな使い方なので入口の変更が小さい。(b) まとめて実行でも parts で作る … 入口が素材の文書のパスを引く処理を持つことになる
- 変えるファイル: `src/editor/pack-tab.js`、`src/editor/serve.py`、`src/editor/resolve_export.py`(見積もり)、`src/home/autorun.py`、`src/home/tests/test_autorun.py`
- テスト: `src/editor/tests/e2e_edit_pack.py` に2素材のパック、`src/editor/tests/test_edit.py` に zip・cut-plan の 400、★`python -m unittest src/home/tests/test_autorun.py` に「2素材は注意で飛ばす」。★`python src/home/tests/e2e_autorun.py`
- リスク: まとめて実行の `_edit_keeps` は src を見ずに全区間をつなぐので、**この変更を入れる前に v2 のファイルができると、違うパックが黙って作られる** → 8-2 と同じ版で入れる(8-2 だけを先に出さない)
- 終わりの条件: 2素材の編集から 3 パック でパックができ、zip・保存・まとめて実行は理由つきで断る

### 8-7 テスト・文書
- 契約テスト(`dev/tests/test_resolve_pack_contract.py`): `EditKeepsContract`(358〜)に「parts 1つ = keeps」「2素材のパック = 素材ごとのパックの区間・字幕をつないだもの(録画側のずれだけ違う)」を足す。★単独で流す
- `dev/tests/e2e_pipeline.py`(3ツールの通し)・`dev/demo_env.py`(見本のデータ)は1素材のまま通ること。新しい e2e のファイルは、写すファイルの一覧(各 e2e の先頭)に足す
- 文書: `docs/design/edit-tool-design.md`(4・5・10 の未決を「実装済み」に)、`docs/spec/pipeline.md`、`src/editor/AGENTS.md`(3 パック の spec)、`src/editor/README.txt`・`src/cut2resolve/README.txt`、`plan/index.html`(データ `plan/data.js`) の段 8 の行
- 終わりの条件: 上のテストと、root の `AGENTS.md` の表の各フォルダのテストが通る

## 版の上げ方
- 編集: `src/editor/serve.py` の SERVER_VERSION・`app.js` の APP_VERSION・`src/editor/README.txt` の見出しを同時に、作業を始める時点の版の次の minor(今は 0.21.0。先の段で上がっていればそこから)
- cut2resolve: `cut2resolve_core.py` の VERSION と `src/cut2resolve/README.txt` の見出し(今は 0.14.0 → 次の minor)
- 入口: `src/home/autorun.py` を変えるので `src/home/launch.py` の版と `src/home/README.txt`(今は 0.12.0 → 次の patch か minor)
- 8-2・8-3・8-6 は同じ版でまとめて入れる(8-6 のリスク)。版を決める前に WORKLOG と実際のファイルで番号を確かめる

## 実機で確かめること
- 2本の切り抜き(同じ fps)を1つの編集でつなぎ、3 パック → Resolve で Text+ のタイムラインができる。素材の境目で映像・字幕が1コマもずれない
- 60fps の素材を 30fps のタイムラインに置いたとき(今の Lua の換算 `ratio`)、2本目以降もずれない
- EDL(予備)を Resolve で読んだとき、素材ごとに正しいクリップにつながる(クリップ名で探す)
- 素材の動画を動かした・消したときの画面の案内
- カット後の再生で素材が切り替わるときの止まり方(目安として許せるか)

## 決まったこと(2026-09-29 ユーザー。計画を書いたあとに聞いた分)
- 素材は**全部 30fps の前提**(ユーザー: 「そもそも最初から全部 30fps でいい」)。違う fps の素材は断る(実際には起きない想定)
- 並べ方は**素材ごとにまとめる**(A の区間を全部 → B の区間を全部)
- 上限は **8 本**・複数の素材のときは**粗編集の動画を作らない**
