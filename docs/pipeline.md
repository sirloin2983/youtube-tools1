# ツール間の受け渡し(パイプラインの約束)v1

2026-09-24 決定(ユーザー): **各ツールは独立して動かし、受け渡しの形式だけを統一する**。ただし**将来1つのアプリに統合する可能性が高い**ので、統合しやすい書き方も約束しておく。
「受け渡しの一括実行(パイプライン)」は、個別のツールが完成してから作る(`docs/project/` の新ツール計画を参照)。

```
① 切り抜きスタジオ ──(切り抜き mp4 + .clip.json)──▶ ② 文字起こしツール ──(.transcript.json / SRT)──▶ ③ cut2resolve ──▶ DaVinci Resolve
        │                                                   ▲                                          ▲
        └─────────────(採用区間 cut-plan/v1)──────────────────┴──────────────────────────────────────────┘
```

## 1. 共通の約束(全スキーマ)
- 文字コードは UTF-8。書くときは BOM なし、読むときは BOM があっても受け付ける(`utf-8-sig`)
- 先頭に `schema`(`"youtube-tools-<種類>/v<版>"`)。書いたツールを `tool: {name, version}`、書いた日時を `createdAt`(ISO 8601、時差付き)に入れる
- **時刻は秒(小数)**。基準は「そのファイルが指すメディアの先頭 = 0 秒」。フレームへの変換は受け取った側が fps を使って行う(丸めの責任を1か所にするため)
- パスは絶対パス(Windows の `C:\...` のままでよい)。受け取った側は、パスに無ければ **JSON と同じフォルダの同名ファイル** を探す(フォルダごと移動・友人に渡した場合への備え)
- 知らない項目は無視する(前方互換)。互換の無い変更をするときだけ版(`/v2`)を上げる。読む側は自分の知らない版を「未対応の版」として拒否する
- 書き込みは一時ファイルに書いてから置き換える(書きかけのファイルを他のツールに読ませない)
- 個人データ(動画・音声・文字起こし)を外部に送らない方針は従来どおり。ここで決める JSON もローカルのファイルとしてだけ扱う

## 2. スキーマ

### 2.1 `youtube-tools-clip/v1` — 切り抜き1本の素性(スタジオが書く)
スタジオで書き出した mp4 の隣に、**拡張子を `.clip.json` に置き換えた名前**(`動画_0012.mp4` → `動画_0012.clip.json`)で置く。
文字起こしツールは、動画を指定されたら隣の `.clip.json` を自動で探して読み、「元の配信のどこか」を知る(将来「文字起こしをスタジオへ返す」ときの対応づけに使う)。
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
- `range` は**元の配信**の秒。切り抜きの中の時刻 `t` は、元の配信では `range.start + t`(fast 書き出しでキーフレームにずれた場合は `export.actualStart` があればそれを優先)
- `source.kind` は `youtube` か `file`。`file` のときは `path` に元のファイル、`videoId` は内部のID
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
- 機械の出力(`original`)・学習用の情報は入れない(受け渡しに不要で、個人データを増やさないため)
- 文字起こしツールは、ブラウザへのダウンロードに加えて「動画の隣にファイルとして保存」できる(`<動画の名前>.transcript.json`)。cut2resolve へのリンクにはこのパスを渡す。
  同名のファイルがあるときは、それが `youtube-tools-transcript/v1` のとき(=このツールが前に書いたもの)だけ上書きし、それ以外は別名にする

### 2.3 `youtube-tools-cut-plan/v1` — 残す区間の指定(誰でも書ける・cut2resolve が読む)
GPT が `cut2resolve/auto_cut.py` で決めた形。スタジオの採用マーク・文字起こしの「残す」行から作れる。
```json
{
  "schema": "youtube-tools-cut-plan/v1",
  "media": {"path": "…", "name": "…"},
  "segments": [{"id": "segment-001", "start": 15.25, "end": 42.8, "status": "adopted", "label": "見どころ"}]
}
```
- `status` が `adopted`(省略時も adopted)の区間だけを使う。`media` は任意(無ければ画面・引数で動画を指定)
- 出力フォルダには cut2resolve が同じ schema の詳細版 `cut-plan.json`(保持・削除区間・fps など)を書く

## 3. 画面どうしのリンク(URL)
他のツールの画面を、入力欄を埋めた状態で開く。**URL だけで重い処理を自動で始めない**(ブラウザで開いた別サイトのリンクから処理を走らせられないようにするため。サーバー側の Host / Origin の検査も従来どおり)。

| 開く画面 | URL | 入る所 |
|---|---|---|
| 切り抜きスタジオ | `http://localhost:8800/?url=<YouTube URL>` | ② 解析の URL 欄(既存) |
| 文字起こしツール | `http://localhost:8775/?media=<動画のパス>` / `?clip=<.clip.json のパス>` | 新規文字起こしのファイル欄 |
| cut2resolve | `http://localhost:8810/?video=<動画>&srt=<SRT>&transcript=<.transcript.json>&plan=<cut-plan>` | 入力欄 |

パスは `encodeURIComponent` で包む。受け取った画面は、値を入力欄に入れるだけで、存在確認などはボタンを押してからサーバーで行う。

## 4. 実行中のポートの共有
各サーバーは既定のポートが使用中なら次の番号を使うので、リンク先のポートが変わることがある。
- 起動時に `<リポジトリ直下>/.runtime/<ツールID>.json` に `{"tool", "port", "version", "startedAt"}` を書き、正常終了時に消す(`.runtime/` は git の対象外)。
  「リポジトリ直下」= 各ツールのフォルダの1つ上。環境変数 `YTT_RUNTIME_DIR` があればそちらを使う(テスト用)。書けなくても起動は続ける
- `GET /api/siblings` は `.runtime/*.json` を読み、書かれたポートに `GET /api/ping` を短い時間(0.3 秒)で問い合わせて、**応答した(app が一致した)ものだけ** `{"tools": {"studio": 8800, "transcribe": 8775}}` の形で返す(自分自身も含める)。画面の「他のツール」メニューはこれを使い、失敗したら既定のポートを使う
- ツールID と `/api/ping` の `app`: `studio` = `clip-studio`(切り抜きスタジオ)/ `transcribe` = `transcribe-tool`(文字起こしツール)/ `cut2resolve` = `cut2resolve`
- 入口の統合サーバーに取り込まれたツール(2026-09-25 からスタジオ)は、記録に `"path": "/studio/"` が付き、`<path>api/ping` で問い合わせる。
  `/api/siblings` はそのとき `"paths": {"studio": "/studio/"}` も返す(無ければ付けない)。画面は `UIKit.tools.setPaths(j.paths)` を呼んでから `UIKit.tools.url()` でリンクを作る
- 注意: 生きているかを pid で確かめない(Windows の `os.kill(pid, 0)` はプロセスを終了させてしまうため)

## 5. 将来の統合に向けた書き方
- 画面からの API 呼び出しは、ツールごとに1つの関数(スタジオの `Studio.api`、文字起こしの `api()` など)を通す。統合時に `/<ツールID>/api/...` へ移せるよう、ベースのパスはその関数の中だけで決める
- 見た目は共通の ui-kit(`ui-kit/`。色・文字・部品・ダーク/ライト)を使う。正本は1つで、`tools/sync_ui_kit.py` で各ツールに写す。ずれは `tools/test_ui_kit_sync.py` で検出する
- 新しく作るツール固有の CSS クラスには接頭辞を付ける(スタジオ `cs-`・文字起こし `tt-`・cut2resolve `c2r-`)。既存のクラス名は、テストが依存しているため今回は変えない
- 設定・データの置き場所は各ツールのフォルダのまま。統合するときに移行する
- ツールに依らない処理(clip/v1 の組み立て・検証、原子的な書き込み、`.runtime` と `/api/ping`・`/api/siblings`、Host/Origin の検査)は共通部品 `ytt_core/` に1つだけ置く(2026-09-24、統合計画の段階2。cut2resolve は対象外で自分の写しを持つ)

## 6. 受け渡しに使う API(各ツール)
| ツール | API | 中身 |
|---|---|---|
| 全ツール | `GET /api/siblings` | `{"tools": {"studio": 8800, ...}}`(4 を参照) |
| スタジオ | `GET /api/export?id=` の各ファイル | 書き出した mp4 のパスと、隣の `.clip.json` のパス(`manifest`) |
| 文字起こし | `GET /api/clip-info?path=<動画のパス>` | `{"clip": <clip/v1 または null>}`(隣の .clip.json を読む。画面で「元の配信」を表示する用) |
| 文字起こし | `GET /api/transcript-v1?id=<文字起こしID>` | transcript/v1 の JSON(ダウンロード用) |
| 文字起こし | `POST /api/export-file` `{"id", "format": "transcript-v1" \| "srt" \| "cut-plan-v1"}` | 動画の隣に保存して `{"path", "overwritten"}`。動画のパスが無い・書けないときは 400 |
| cut2resolve | 画面(`?video=&srt=&transcript=&plan=`)と、その裏の API | cut2resolve の README を参照 |
