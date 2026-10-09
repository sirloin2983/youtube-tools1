# ツール間の受け渡し(パイプラインの約束)v1

状態(2026-10-07): **規則(今も有効)**。2026-09-24 決定(ユーザー): **各ツールは独立して動かし、受け渡しの形式だけを統一する**。この約束のおかげで、2026-09-25〜27 に **1 つのアプリ(入口 `http://localhost:8700/` の 1 プロセス。`/studio/`・`/transcribe/`(編集)・`/cut2resolve/`(パックを作る API))に統合できた**(`docs/design/integration-plan.md`)。統合しやすい書き方の約束は 5 に残す。
受け渡しの一括実行(パイプライン)は、入口の「まとめて実行」(`src/home/autorun.py`)が行う。

```
入口(ホーム)http://localhost:8700/ が、1 つのプロセスの中に 3 つのツールを取り込んで動かす
① 切り抜きスタジオ /studio/ ──(切り抜き mp4 + .clip.json)──▶ ② 編集 /transcribe/ ──(パックを作る部品・API = /cut2resolve/)──▶ DaVinci Resolve
        │                       (1 文字起こし → 2 カット → 3 パック。            ▲                                      ▲
        │                        .transcript.json / SRT / .edit.json)             │                                      │
        └─────────────(採用区間 cut-plan/v1)──────────────────────────────────────┴──────────────────────────────────────┘
```

## 1. 共通の約束(全スキーマ)
- 文字コードは UTF-8。書くときは BOM なし、読むときは BOM があっても受け付ける(`utf-8-sig`)
- 先頭に `schema`(`"youtube-tools-<種類>/v<版>"`)。書いたツールを `tool: {name, version}`、書いた日時を `createdAt`(ISO 8601、時差付き)に入れる
- **時刻は秒(小数)**。基準は「そのファイルが指すメディアの先頭 = 0 秒」。フレームへの変換は受け取った側が fps を使って行う(丸めの責任を1か所にするため)
- パスは絶対パス(Windows の `C:\...` のままでよい)。受け取った側は、パスに無ければ **JSON と同じフォルダの同名ファイル** を探す(フォルダごと移動・友人に渡した場合への備え)。
  JSON が `作業用` フォルダの中なら、動画は1つ上のフォルダ(下の「途中のファイルの置き場所」)を先に探す
- **途中のファイルの置き場所(2026-09-27)**: 動画のフォルダの直下に並べるのはパック(`<名前>_pack`)と元動画(書き出した切り抜きの mp4)だけ。
  それ以外の受け渡しのファイル(`.clip.json`・`.edit.json`・`_edit.mp4`・`.transcript.json`・`.srt`・`.cut-plan.json`・スタジオの `.studio-id`)は
  **動画のフォルダの下の `作業用` フォルダ**に書く(動画がもう `作業用` の中なら、そのフォルダ)。読む側は `作業用\` → 動画の隣(以前の置き方)の順に探す。
  以前の置き方のファイルは動かさない。規則は `src/ytt_core/schemas.py`(`WORK_DIR`・`work_dir`・`sidecar_path`・`find_sidecar`)の1か所
  (cut2resolve は `cut2resolve_core.WORK_DIR` に同じ名前を持つ)
- 知らない項目は無視する(前方互換)。互換の無い変更をするときだけ版(`/v2`)を上げる。読む側は自分の知らない版を「未対応の版」として拒否する
- 書き込みは一時ファイルに書いてから置き換える(書きかけのファイルを他のツールに読ませない)
- 個人データ(動画・音声・文字起こし)を外部に送らない方針は従来どおり。ここで決める JSON もローカルのファイルとしてだけ扱う

## 2. スキーマ

### 2.1 `youtube-tools-clip/v1` — 切り抜き1本の素性(スタジオが書く)
スタジオで書き出した mp4 の `作業用` フォルダに、**拡張子を `.clip.json` に置き換えた名前**(`動画_0012.mp4` → `作業用\動画_0012.clip.json`)で置く
(2026-09-27 まではmp4 の隣。読む側は両方を探す)。
文字起こしツールは、動画を指定されたら `.clip.json` を自動で探して読み、「元の配信のどこか」を知る(将来「文字起こしをスタジオへ返す」ときの対応づけに使う)。
そのため画面どうしのリンクは動画のパスだけ渡せばよい(`?media=`)。
```json
{
  "schema": "youtube-tools-clip/v1",
  "tool": {"name": "clip-studio", "version": "0.2.0"},
  "createdAt": "2026-09-24T12:00:00+09:00",
  "media": {"path": "C:\\Users\\...\\exports\\動画_0012.mp4", "name": "動画_0012.mp4", "durationSec": 45.2},
  "source": {"kind": "youtube", "videoId": "abcdefghijk", "url": "https://www.youtube.com/watch?v=abcdefghijk",
             "title": "配信タイトル", "path": null},
  "range": {"start": 1234.5, "end": 1279.7},
  "mark": {"id": "m12", "label": "見どころ", "status": "exported", "src": "manual"},
  "export": {"mode": "precise"}
}
```
- `range` は**元の配信**の秒。切り抜きの中の時刻 `t` は、元の配信では `range.start + t`(fast 書き出しでキーフレームにずれた場合は `export.actualStart` があればそれを優先。**2026-10-04(Q1)から書き出しはいつも 30fps に作り直すので位置ちょうど・actualStart は付かない**。以前の切り抜きのために読む側は残す)
- `source.kind` は `youtube` か `file`(2026-10-04 から、リアルタイム切り抜き(線 D・既定オフ)の書き出しは `live`: range は録画の最初のセグメントの受信時刻からの秒・絶対時刻と録画の素性は `source.live`・`url` は null(アーカイブの秒とずれるため)。`src/home/live_export.py`)。`file` のときは `path` に元のファイル、`videoId` は内部のID
- 秘密情報(API キーなど)や、元動画以外の個人のパスは入れない

### 2.2 `youtube-tools-transcript/v1` — 文字起こしの結果(文字起こしツールが書く)
```json
{
  "schema": "youtube-tools-transcript/v1",
  "tool": {"name": "transcribe-tool", "version": "0.10.0"},
  "createdAt": "…",
  "media": {"path": "C:\\...\\動画_0012.mp4", "name": "動画_0012.mp4", "durationSec": 45.2},
  "clip": { …2.1 の中身そのもの(入力にあった場合だけ)… },
  "title": "…",
  "speakers": [{"id": 0, "name": "配信者A"}],
  "segments": [
    {"id": "s1", "start": 0.52, "end": 2.10, "text": "こんばんは", "speaker": 0, "proofed": true, "cut": false}
  ]
}
```
- `segments` は時刻順。`cut: true` は画面の「カット済」(Resolve へ渡すときに削る行)
- 行の任意の項目 `noSub: true`(2026-10-05。「字幕に出さない」= ゲームのキャラなどの声)。**その行の時間は残す区間に数え、字幕は作らない**(cut2resolve の `pack.row_has_caption`。項目が無ければ今までと同じ)。
  `segments` は時刻が重なってもよい(違う話者の同時発話)。パックは重なる字幕を別の段に分ける(`plan/line-b-overlap.md`)
- 機械の出力(`original`)・学習用の情報は入れない(受け渡しに不要で、個人データを増やさないため)
- 文字起こしツールは、ブラウザへのダウンロードに加えて「作業用フォルダにファイルとして保存」できる(`作業用\<動画の名前>.transcript.json`。2026-09-27 までは動画の隣)。cut2resolve へのリンクにはこのパスを渡す。
  同名のファイルがあるときは、それが `youtube-tools-transcript/v1` のとき(=このツールが前に書いたもの)だけ上書きし、それ以外は別名にする

### 2.3 `youtube-tools-cut-plan/v1` — 残す区間の指定(誰でも書ける・cut2resolve が読む)
GPT が `src/cut2resolve/auto_cut.py` で決めた形。スタジオの採用マーク・文字起こしの「残す」行から作れる。
```json
{
  "schema": "youtube-tools-cut-plan/v1",
  "media": {"path": "…", "name": "…"},
  "segments": [{"id": "segment-001", "start": 15.25, "end": 42.8, "status": "adopted", "label": "見どころ"}]
}
```
- `status` が `adopted`(省略時も adopted)の区間だけを使う。`media` は任意(無ければ画面・引数で動画を指定)
- cut2resolve の詳細版(同じ schema。保持・削除区間・fps など)は、コマンド(cut2resolve.py)では出力フォルダの `cut-plan.json`。
  画面・API(「編集」・まとめて実行)のパックでは出力フォルダに置かず、cut2resolve の作業データ `packs/` の「パックを作った記録」の `cutPlan` に入れる
  (2026-09-26 ④。読むのは `src/ytt_core/txindex`。`docs/design/edit-tool-design.md` の 12 ④)

### 2.4 `youtube-tools-key/v1` — 成果物の鍵(役割で組み直す計画の RS1-5。**RS1 では形と純粋な関数だけ。書くのは RS6**)
成果物(切り抜き 1 本・認識・パックなど)の横に置く小さな JSON。「同じ鍵の成果物があれば作らない = 使い回し」の判定に使う(`plan/role-restructure.md` 4 の 4・5-2)。
今はどこにも書いていない。形と関数は `src/ytt/schemas.py`(`make_key`・`validate_key`・`same_key`・`key_path`・`media_identity`・`file_digest`・`canon`・`sec_ms`)。
```json
{
  "schema": "youtube-tools-key/v1", "v": 1, "stage": "export",
  "inputs": {"media": {"kind": "archive", "videoId": "…"}, "range": [12.345, 40], "fps": 30},
  "hash": "<sha256 の 16 進 64 桁>",
  "madeBy": {"name": "studio", "version": "…"}, "at": "2026-10-09T12:00:00+09:00"
}
```
- `stage` は `ingest`・`analyze`・`export`・`transcribe`・`diar`(話者判別。認識とは別の成果物 = F-6)・`post`(後処理)・`pack` のどれか
- **`hash` = sha256(`canon({"stage","v","inputs"})`)**。`canon` はキーを並べ替え・空白なし・日本語はそのままの JSON。`madeBy` と `at` はハッシュに入れない(いつ・誰が作ったかで鍵が変わらないように)
- **ミリ秒に丸める**: `inputs` の中の小数は(深さによらず)小数 3 桁に丸め、整数と同じ値なら整数にする(`12.0` と `12` は同じ)。秒の値は計算の経路で `12.3456789` と `12.3460001` のように揺れ、丸めないと同じ区間なのに鍵が食い違って使い回しの当たり率が下がるため。`inputs` に入れてよい型は int・float・str・bool・None・list・dict(キーは文字列)だけ(NaN・無限大は ValueError、ほかの型は TypeError)
- **元の媒体の識別(F-1)**: `media_identity` が `{"kind":"recording","recorder","recording"}`・`{"kind":"archive","videoId"}`・`{"kind":"file","sha256"}`(中身のハッシュ。`file_digest` が 1MB ずつ読んで出す。名前や更新日時は入れない)を作る。配信中の録画からの速報版とアーカイブからの本番版が同じ鍵にならない
- `validate_key` は schema・段・`hash` の形を調べ、`inputs` からハッシュを計算し直して一致を確かめる(書き換えられた鍵は使わない)。`same_key` は両方が正しく、段と `hash` が同じときだけ True
- 置き場所は `key_path(path, stage)` = 作業用/ の中の `<名前>.<段>.key.json`(パスの計算だけ)

## 3. 画面どうしのリンク(URL)
他のツールの画面を、入力欄を埋めた状態で開く(今はどれも入口のポート 8700 の `/studio/`・`/transcribe/` 配下)。**URL だけで重い処理を自動で始めない**(ブラウザで開いた別サイトのリンクから処理を走らせられないようにするため。サーバー側の Host / Origin の検査も従来どおり)。

| 開く画面 | URL | 入る所 |
|---|---|---|
| 切り抜きスタジオ | `http://localhost:8700/studio/?url=<YouTube URL>` | ② 解析の URL 欄(既存) |
| 編集(文字起こしツール) | `http://localhost:8700/transcribe/?media=<動画のパス>` / `?clip=<.clip.json のパス>` | その動画の文字起こしがあれば開く(`GET /api/doc-for`)。無ければ新規文字起こしのファイル欄 |
| ~~cut2resolve~~ | 画面は「編集」に統合して消した(2026-09-26)。入口の中の `/cut2resolve/?video=<動画>` は `/transcribe/?media=<動画>` へ転送 | — |

パスは `encodeURIComponent` で包む。受け取った画面は、値を入力欄に入れるだけで、存在確認などはボタンを押してからサーバーで行う。

## 4. 実行中のポートの共有
入口の中で動いているときは全ツールが入口のポート(8700。使用中なら次の番号)の `/studio/`・`/transcribe/`・`/cut2resolve/` 配下になる。ツールを単独のサーバーで起動したとき(入口に取り込めなかったときの子プロセス・テスト)は、既定のポートが使用中なら次の番号を使うので、リンク先のポートが変わることがある。
- 起動時に `src/.runtime/<ツールID>.json`(`<リポジトリ直下>/src/` の `.runtime/`)に `{"tool", "port", "version", "startedAt"}` を書き、正常終了時に消す(`.runtime/` は git の対象外)。
  `.runtime/` の場所 = 各ツールのフォルダの1つ上(`src/`)。環境変数 `YTT_RUNTIME_DIR` があればそちらを使う(テスト用)。書けなくても起動は続ける
- `GET /api/siblings` は `.runtime/*.json` を読み、書かれたポートに `GET /api/ping` を短い時間(0.3 秒)で問い合わせて、**応答した(app が一致した)ものだけ** `{"tools": {"studio": 8700, "transcribe": 8700}}`(単独で起動したときは `{"studio": 8800, "transcribe": 8775}` のようにツールごとのポート)の形で返す(自分自身も含める)。画面の「他のツール」メニューはこれを使い、失敗したら既定のポートを使う
- ツールID と `/api/ping` の `app`: `studio` = `clip-studio`(切り抜きスタジオ)/ `transcribe` = `transcribe-tool`(文字起こしツール)/ `cut2resolve` = `cut2resolve`
- 入口の統合サーバーに取り込まれたツール(2026-09-25 からスタジオ)は、記録に `"path": "/studio/"` が付き、`<path>api/ping` で問い合わせる。
  `/api/siblings` はそのとき `"paths": {"studio": "/studio/"}` も返す(無ければ付けない)。画面は `UIKit.tools.setPaths(j.paths)` を呼んでから `UIKit.tools.url()` でリンクを作る
- 注意: 生きているかを pid で確かめない(Windows の `os.kill(pid, 0)` はプロセスを終了させてしまうため)

## 5. 統合しやすい書き方(統合済み。今も守る)
- 画面からの API 呼び出しは、ツールごとに1つの関数(スタジオの `Studio.api`、文字起こしの `api()` など)を通す。統合時に `/<ツールID>/api/...` へ移せるよう、ベースのパスはその関数の中だけで決める
- 見た目は共通の ui-kit(`src/ui-kit/`。色・文字・部品・ダーク/ライト)を使う。正本は1つで、`dev/sync_ui_kit.py` で各ツールに写す。ずれは `dev/tests/test_ui_kit_sync.py` で検出する
- 新しく作るツール固有の CSS クラスには接頭辞を付ける(スタジオ `cs-`・文字起こし `tt-`・cut2resolve `c2r-`)。既存のクラス名は、テストが依存しているため今回は変えない
- 設定・データの置き場所は `%LOCALAPPDATA%\youtube-tools\<ツールID>\`(2026-09-26 から。段階4。`docs/spec/data-location.md`)。以前の各ツールのフォルダの中からは、最初の起動でコピーする
- ツールに依らない処理(clip/v1 の組み立て・検証、原子的な書き込み、`.runtime` と `/api/ping`・`/api/siblings`、Host/Origin の検査)は共通部品 `src/ytt_core/` に1つだけ置く(2026-09-24、統合計画の段階2。cut2resolve も 2026-09-26 から `.runtime`・`/api/siblings`・Host/Origin の検査は ytt_core を使う)

## 6. 受け渡しに使う API(各ツール)
| ツール | API | 中身 |
|---|---|---|
| 全ツール | `GET /api/siblings` | `{"tools": {"studio": 8700, ...}}`(4 を参照) |
| スタジオ | `GET /api/export?id=` の各ファイル | 書き出した mp4 のパスと、`作業用` の `.clip.json` のパス(`manifest`) |
| 文字起こし | `GET /api/clip-info?path=<動画のパス>` | `{"clip": <clip/v1 または null>}`(`作業用` か隣の .clip.json を読む。画面で「元の配信」を表示する用) |
| 文字起こし | `GET /api/transcript-v1?id=<文字起こしID>` | transcript/v1 の JSON(ダウンロード用) |
| 文字起こし | `POST /api/export-file` `{"id", "format": "transcript-v1" \| "srt" \| "cut-plan-v1"}` | 動画のフォルダの `作業用` に保存して `{"path", "overwritten"}`。動画のパスが無い・書けないときは 400 |
| 文字起こし | `GET/PUT /api/edit?id=`・`POST /api/edit/pack` など | 「編集」のカット(`transcripts/<id>.edit.json`。youtube-tools-edit/v1)。`docs/design/edit-tool-design.md` の 4・5 |
| cut2resolve | `POST /api/plan`・`/api/build`(spec の `keeps` = 「編集」のカット・`preset` = transcript-rows)など | cut2resolve の README を参照(画面は無い) |
