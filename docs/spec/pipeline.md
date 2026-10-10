# ツール間の受け渡し(パイプラインの約束)v1

状態(2026-10-10 夜): **規則(今も有効)**。RS6 で成果物の鍵・校正の上書き・結果の束・`.flow.lock` を足した(2.4〜2.7)。役割で組み直す計画の RS3・RS4 が済み、ファイルの場所は役割の層(`src/ytt`・`pipeline`・`human`・`manage`・`eval`)に移った(7 に「記録の持ち主の表」)。2026-09-24 決定(ユーザー): **各ツールは独立して動かし、受け渡しの形式だけを統一する**。この約束のおかげで、2026-09-25〜27 に **1 つのアプリ(入口 `http://localhost:8700/` の 1 プロセス。`/studio/`・`/transcribe/`(編集)・`/cut2resolve/`(パックを作る API))に統合できた**(`docs/design/integration-plan.md`)。統合しやすい書き方の約束は 5 に残す。
受け渡しの一括実行(パイプライン)は、入口の「まとめて実行」(`src/home/autorun.py`。① の段の中身は `src/pipeline/run.py`)が行う。

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
  以前の置き方のファイルは動かさない。規則は `src/ytt/schemas.py`(`WORK_DIR`・`work_dir`・`sidecar_path`・`find_sidecar`)の1か所
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
GPT が `src/pipeline/pack/auto_cut.py` で決めた形。スタジオの採用マーク・文字起こしの「残す」行から作れる。
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
  (2026-09-26 ④。読むのは `src/manage/cases/txindex.py`。`docs/design/edit-tool-design.md` の 12 ④)

### 2.4 `youtube-tools-key/v1` — 成果物の鍵(形は RS1-5。**RS6 b-K1・K2 で書く・読むようにした**。コードは `src/flow/keys.py`)
成果物(切り抜き 1 本・認識・パックなど)の横に置く小さな JSON。「同じ鍵の成果物があれば作らない = 使い回し」の判定に使う(`plan/role-restructure.md` 4 の 4・5-2)。
形と関数は `src/ytt/schemas.py`(`make_key`・`validate_key`・`same_key`・`key_path`・`media_identity`・`file_digest`・`canon`・`sec_ms`)。
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

#### 2.4.1 鍵の置き場所と inputs(RS6 b-K1。`src/flow/keys.py`。書くのは ② の段が終わったところ。① は鍵を知らない)
| 段 | 鍵の場所 | `inputs` の中身 |
| --- | --- | --- |
| `export` | 切り抜き(動画)の横 `作業用/<名前>.export.key.json`(`key_path`) | `media`(`media_identity`)・`start`・`end`(ms の整数)・`settings`(出来上がりに効く設定) |
| `transcribe` | `transcripts/<id>.transcribe.key.json` | `export`(切り抜きの鍵の hash。無ければ `{media}`)・`engine`・`engineVersion`・`model`・`language`・`quality`(beam)・`vadMode`・`boost`・`span`(媒体の一部を認識したときだけ) |
| `post` | `transcripts/<id>.post.key.json` | `transcribe`(transcribe の hash)・`post`(後処理の設定)・`dict`(辞書の版) |
| `diar` | `transcripts/<id>.diar.key.json` | `transcribe`(同上)・`people`(出る人)・`voices`(覚えた声ファイルの内容のハッシュ) |
| `pack` | パックのフォルダの `pack.key.json` | `clips`(切り抜きの鍵の hash の並び)・`doc`(カットの指定と字幕のファイルの中身の版)・`settings`(パックの設定)・`form`(= 2。要求の本文から作った鍵) |
- **hash の作り方**: 2.4 の `make_key`(`sha256(canon({stage, v, inputs}))`)。パックは**作る前に分かる材料だけ**で組む(`pack_body_inputs` = cut2resolve の POST /api/build の本文 spec・output から)ので、段が「今の要求」と「書いてある鍵」を比べられる。`form` が 2 でない鍵(b-K1 の形)は鍵なしと同じに扱う(一度の作り直しをしない)
- 鍵が書けなくても段は失敗にしない(ログだけ)。文書を消すときは `transcribe`・`post`・`diar` の鍵も `over.json`(2.5)も一緒に消す
- **鍵が違うときの扱い**(`src/flow/run.py`。決定 `plan/decisions.md` 3-29 Q4): 今の材料から作った hash と書いてある鍵の hash を比べて `same`(同じ)・`differ`(違う)・`none`(鍵なし・壊れている・材料が分からない)に分ける
  - **文字起こし**: `same`・`none` は飛ばす(文書があれば。`none` = 今まで通り)。`differ` も**飛ばして印を付ける**(結果の文に「設定が違う(force で作り直し)」。人の校正を黙って捨てない)。作り直すのは force のときだけ
  - **パック**: `same` は飛ばす。`differ` は**作り直す**(パックは機械の物なので上書き)。`none` は今まで通り(同じ名前のパックがあれば飛ばし、無ければ作る)
  - **force**(`Run.force`・束の `run.force`・CLI の `--force`): **鍵が同じでも違っても作り直す**(鍵によらない)。文字起こしは新しい文書を作り、校正の上書き(2.5)で人の直しを引き継ぐ。パックは上書き
  - 鍵を読む段が無い成果物(export・post・diar)は今のまま。鍵は「何から作ったか」の記録として書くだけ

### 2.5 校正の上書き `transcripts/<id>.over.json`(RS6 b-O1。`src/human/proof/overrides.py`。③ の物。② は見ない)
文書を作り直しても人の直しを失わないための**派生の控え**(文書 `<id>.json` が正。控えは作り直しの引き継ぎのときに読む)。
```json
{"schema": "youtube-tools-over/v1", "clipKey": {…export の鍵 か null…},
 "rows": [{"start": 12.3, "end": 15.0, "text": "…", "proofed": true, "proofedAt": 1700000000000, "speaker": "…", "noSub": true, "tags": ["…"]}],
 "speakers": ["行が使う話者"], "at": 1700000000000}
```
- **人の行** = 校正済み(`proofed`)・文字が機械の出力 `original` の同じ時刻の行と違う・話者・`noSub`・`tags` のどれかを持つ行。`text` を持つのは「人の文字の行」(校正済みか文字が機械と違う)だけ。後処理が埋めた行(印 `fill`)は校正済みでなければ人の直しに数えない。空の下書き行は入れない
- **いつ書くか**: 文書を保存するたびに(`store.save_transcript` が保存のロックの中で `save_after`。書けなくても保存は成功のまま)。`at` = 元にした文書の `updatedAt`。控えが文書より古い(`at` < `updatedAt`)ときは文書から取り出し直す(`current`)
- **作り直しのとき引き継ぐ**: 同じ動画の文書を作り直す(force の再文字起こし・エンジンを変えた再実行)と、`doc_jobs.carry_overrides` が新しい機械の行へ人の行を**時刻の重なり**で重ねる(`match` = 片方の中心が相手の区間に入る、か、重なりが短い方の 1/2 以上)。人の行が長さの 1/2 以上を覆う、または機械の文字の 1/2 以上が人の行に現れる機械の行は人の行に置き換え、人が触っていない行だけ新しくなる
- **STALE の印**: 新しい文書のどの行とも対応づかない人の文字の行は、印 `STALE_FLAG`(「古い認識を元にした直し(作り直した文字起こしに対応する行がありません)」)を付けて行として残す
- **当てないもの**: 評価用(`evalSet`・`evalRedo`)の作り直し・再認識(each・range。校正済みの守りは従来のまま)
- **止めるスイッチ**: 環境変数 `TRANSCRIBE_CARRY_OVERRIDES=off`(前の文書はそのまま残るので直しは失われない)

### 2.6 ② の結果の束 `<案件>\作業用\runs\<実行id>.json`(RS6 b-B0。`src/flow/placement.py`・`src/flow/runlog.py`)
② の 1 回の実行が終わったところ(`flow/run.run` の最後)で原子的に書く。**書けなくても実行は失敗にしない**。形の名前は `runlog.RESULT_SCHEMA` = `youtube-tools-run/v1`。
- 中身: `id`・`input`(何を入れて始めたか = `kind`・`videoId`・`docId`・`sourcePath`・`title`・`mode`・`top`・`marks`・`ranges`・`cut`・`engine`・`model`・`overwrite`・`requestId`・`streamer`・`onFail`)・`spec`(その実行の束)・`state`(`done` / `error` / `cancelled` / `stopped` = 入口の終了で止まった = 次の起動で続く)・`message`・`error`・`nothing`・`steps`(段・状態・詳細)・`outputs`(段ごとの成果物のパスと鍵のパス。`export` / `transcribe`(`post` の鍵も)/ `pack` / `diarize`)・`packs`・`notes`(RS7-1 S4。友人の依頼のメモ)・`failures`・`created`・`at`・`madeBy`。`steps[]` の各段に `startedAt`・`finishedAt`(ミリ秒。RS7-1 S3。索引の 1 行の `steps` にも入る)
- 置き場所は案件の `作業用\runs\`(案件の根の求め方は `data-location.md`)。案件が分からない(まだ無い)ときは書かない
- 入口の `logs/autorun-runs.jsonl` の 1 行(1 実行 = 1 行)は**索引**: 1 行の `resultPath` が束の場所(書けなかった実行・RS6 より前の行には無い)。読む側は `runlog.read_result(rec)`(`resultPath` が絶対パスで名前が `<id>.json`・schema と id が一致するときだけ。案件のフォルダは人が動かす・消すので「あれば読める」だけ)。CLI(`src/app/cli.py`)は同じ形に段ごとの成果物と鍵を足して標準出力・`--out` へ返す

### 2.7 `.flow.lock` — 1 つの作業データに ② は 1 つ(RS6 b-B0・b-S1。`src/flow/placement.py`)
- 置き場所は**作業データの根**(`ytt.datadir.data_root`。`YTT_DATA_DIR=inplace` のテストでは `.runtime/`)の直下の `.flow.lock`。中身は `{pid, port, at, token}`(`port` = ② の HTTP のポート。CLI など無ければ null)
- 入口(start.bat)は起動で取り(`acquire`)、終わるとき返す(`release`)。CLI は動いている ② があればそのポートへ頼み、無ければ自分で取る。**同じ作業データで ② が 2 つ動かない**ので、別々のプロセスが同じ文書・パックを同時に書かない
- **取り残し**: 持ち主の pid が動いていなければ無いのと同じ(`lock_info` は None・`acquire` は消して取り直す)。ポートを書いた印は、そのポートが開いていることも見る(pid の使い回しを取り違えない)。返すのは自分の `token` の印だけ(別の ② が取り直した物は消さない)
- 入口を起動し直すとき、古い入口がポートを離さないうちに新しい入口が起動すると `.flow.lock` が残っていて起動を止める(RS7-1 1d: 新しい入口は古い入口の pid の終了を最大 90 秒待つ。期限が来ても `.flow.lock` の先客でも次の番号のポートには逃げず、読める文を出して非 0 で終わる)

### 2.8 封筒 + 束と ② の口(RS7-1。`src/flow/envelope.py`・`src/flow/spec.py`・`src/flow/runqueue.py`・`src/flow/machine.py`)
依頼 = **封筒**(処理の中身でない物)+ **束**(何を作るか)。② の段は束だけを読み、封筒は記録と届け方に使う。
- **封筒** `{id, kind: url|file|docs|live, input, requestId, deliver: {dir, batch, pool}, note, createdAt, specVersion}`(+ 一時の `legacy` = 段の並びの形 `mode`・1 本が失敗したとき `onFail`・字幕の色の配信者 `streamer`)。`input` は kind ごと(url = videoId か url・title・duration・fresh・marks / file = path・title / docs = docId・title / live = videoId か url・title・recorder(録画の部品の名前))。**kind live は Run にしない**: `Queue.submit` が `set_live_hook(fn)` で登録された `fn(封筒, 束)` → `{id, …}` へ回す(hook が無ければ ValueError。RS7-2 G2a)。ライブの設定は束の `adopt` の `top`・`pad`・`perHour`・`waitMin`・`sens`(high|normal|low)・`afterStream`(bool)。知らない項目・版・形の違う値は理由つきの ValueError(受け口では 400)
- **束** `post` に後処理 6 項目(`autoFill`・`stripNames`・`autoLlm`・`autoContext`・`splitChars`・`diarSmooth`)と `llmModel`。`post.learning` は `{version}` だけ(後処理の鍵に入る。学習データの場所は束でなく machine の `learningDir`)。`hints` は検査と読み口(`hint_ranges`・`hint_people`)つき。`run.repack`(パックの作り直し)・`run.pinned`。**`SCREEN`・`Run.screen` は消えた**: 切り出しは精密・画質の上限なし・パックの fps 30 を固定(`FIXED`。画面の欄 3 つも消した)。用語集は束に入れず、編集の受付が設定から(CLI は `flow/tools` の `Learning` が learningDir から)読む
- **束の文字起こしの既定(全体の版 0.58.0。2026-10-11)**: `transcribe` の `engine` は whisper.cpp・`model` は large-v3・`device` は vulkan(前は faster-whisper・small・auto)。選べる値は `spec.TX_ENGINES`・`TX_MODELS`・`TX_DEVICES`(それぞれ whisper.cpp / large-v3 / vulkan だけ)。`post.redoLarge`(kotoba のとき認識し直しだけ large-v3)は消えた。**旧い値の読み替え**: 束・`machine.json`・保存した設定の faster-whisper・qwen3-asr・llama.cpp(engine)、auto・cuda・cpu(device)、範囲外のモデル名は断らず `spec.read_legacy_tx` が既定(whisper.cpp / vulkan / large-v3)と読む(`spec.merge` と `machine.check` が使う)。`spec.RETIRED_KEYS`(今は `post.redoLarge`)は束を取り込むとき黙って捨てる。`spec.implied_engine(device)` は常に whisper.cpp。文字起こしの鍵は engine/model を含むので、旧い既定(small・auto)で動いた実行だけ鍵が変わる(= 「設定が違う」の印。force で作り直し)。whisper.cpp が作られていなければ文字起こしは理由つき(`engine_missing`)で断る(黙って CPU にしない)
- **束は受けたときに組む**: 入口の受付(`AutoRunner._accept`)が画面の設定 + この PC の設定で束を組み、友人の区間の長さ・配信者・届け方の n 本もそこで決める。待ちの間に設定を変えても、その実行の中身は変わらない
- **この PC の設定** `machine.json`(作業データの根。`data-location.md`。0.58.0 から `engine` は whisper.cpp・`device` は vulkan だけ = `machine.DEVICES` は `spec.TX_DEVICES`。旧い値は読み替え): `engine`・`device`・`llmModel`・`caseRoot`・`diskMinGB`・`learningDir`。強さは 引数 > 環境変数 `YTT_MACHINE_*`(旧い環境変数 `TRANSCRIBE_DEVICE` は machine では読まない = device は `YTT_MACHINE_DEVICE` だけ。認識ワーカーの `pipeline/transcribe/worker_client.py` は今も `TRANSCRIBE_DEVICE` を見る)> ファイル > 既定。`overlay(束)` は**引数・環境変数・ファイルで決めた値だけ**を束に重ねる(既定から来た値は重ねない = 何も決めていない PC では束・鍵が今と同じ)。編集の ⚙ のデバイスは `machine.json` に書く(GET/PUT `/api/settings` の中で振り分け。合わない値は 400)
- **口**: `POST /api/flow/submit`(合言葉。`{envelope, spec?}` → `{run}`)・`GET /api/flow/status`(`{queued, running, done, idle, closed, live: {recording, detecting, exporting}, runs}`。`idle` は待ち・実行中・live の数がどれも 0 のときだけ真。`Queue.set_status_hook` で入口が live を足す)。CLI は入口に頼むとき submit 1 回。submit の無い古い入口(404)には「入口を起動し直して」と出して終了コード 1(2 段で頼む道は消した)
- **ヘッドレスの入口**(RS7-2 G5a): `py -3.10 src/home/launch.py --headless`。ブラウザ・窓・③ の見張りを起こさない。起動できたら標準出力に 1 行 `{"event":"ready","port","token","pid"}`(呼び手はこれを待って port と合言葉を得る)。既に入口が動いていれば終了コード 3。`--headless --app-window` は引数のエラー。`restart-self` は 409(error `headless`)
- **kind live の受け渡し**(RS7-2 G2b): hook が `livesession.submit(封筒, 束)` で録画を始め、録画ごとに束を `live/bundles.json`(`data-location.md`)に控える。検出・採用の待ち・配信後の解析の設定・書き出しの音量はその録画の束から読む(束が無い録画は今までの読み方)。書き出したあとの受け渡しは `Queue.submit(kind file)` の封筒 + 束(`start_file` は残るが呼ぶ所は無い)。自分の配信(スタジオの URL の欄 `POST /live/api/begin`)は束を組まず今の読み方のまま
- **待ちの記録** `app\logs\autorun-active.json` は**版 2** = 各実行が封筒 + 束 + 状態(`Run.saved()`)。版 2 でない記録(版 1 など。欄だけ・束なし)は読まずに捨てる(ログに 1 行。変換はしない)。古すぎる実行は戻さず記録に「中止」。待ち行列・糸・記録は `Queue`(`runqueue.py`)が持ち、入口の AutoRunner は受付と hook だけ
- `Run.public` に `packs`・`newDocs`(文書単位の実行でも `docs`)

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
- ツールに依らない処理(clip/v1 の組み立て・検証、原子的な書き込み、`.runtime` と `/api/ping`・`/api/siblings`、Host/Origin の検査)は共通部品 `src/ytt/`(旧 `src/ytt_core/`。2026-10-09 に改名)に1つだけ置く(2026-09-24、統合計画の段階2。cut2resolve も 2026-09-26 から `.runtime`・`/api/siblings`・Host/Origin の検査は ytt を使う)

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

## 7. 記録の持ち主の表(役割で組み直す計画の RS4-1。2026-10-10。**今の持ち主の整理で、データの形は変えていない**。RS6 の入力)
作業データの記録ファイルを「① 自動の流れ」「② 人の操作」「④ 検証」のどれが書き、誰が読むかを、今のモジュールで並べる。1 つのファイルに複数の層の物が混ざっている所は RS6 で入れ物を分ける(下の「RS6 に送る」)。置き場所は `docs/spec/data-location.md`。

| 記録 | ① 自動(書き手) | ② 人 | ④ 検証 | 書く・触るモジュール(例) |
| --- | --- | --- | --- | --- |
| 文書 `transcripts/<id>.json` | `original`・`model`・`params`・`recognition.runs`(最初の認識 + 再認識)・`diarization.auto` | `segments` の人の直し(`text`・`proofed`・`proofedAt`・`tags`・`cutState`・`noSub`)・`speakers[].name/color/sub`・`effort`・`relinks`・`diarNum` | `evalSet`・`evalReviewed`・`spec.evalRedo` による runs | `src/human/proof/doc_jobs.py` の `_rows_to_doc`・`_doc_fields` が ① の結果と ② の文書を 1 関数で作る。`rerun.record_rerun` は ② の直しの前に ① の runs を書き足し `evalReviewed` を外す。文書の読み書きの口は `human/proof/store.py`(`write_doc`・`sanitize_transcript`・`fill_doc`) |
| 行の `fill = {from, by}` | 認識のあとの後処理(`pipeline/transcribe/fill.py`)の印 | 人の行 `segments[]` の中に埋まる | | `store.sanitize_transcript` が残す。画面の「別の読み」で戻す |
| `transcripts/<id>.diar.json` | `latest`(turns・overlaps・rows・labelMap)= `pipeline/transcribe/diarize.py` | `voices`(decided・by・context)を人の層が書き足す | | `diarize.update_diar_voices`・`human/proof/speakers.py` の `_autodiar_record` |
| `transcripts/<id>.edit.json`(カット) | | カットの結果(残す区間) | | 書くのは `human/proof/store.py`(文書と相互に呼ぶので割らない。保存は `apply_edit_cuts` を通す)。読むのは `pipeline/pack/` のパックの入力を作る側 |
| 切り抜きの `.clip.json`(作業用/) | 書き出し時の素性(`pipeline/export/exporter.py` の `write_clip`。形は `ytt/schemas.build_clip`) | | | 読むのは `manage/cases/txlink.py`・`txindex.py`・編集の `GET /api/clip-info` |
| パックの記録 `cut2resolve/packs/` | パックを作ったときの `cutPlan`(`pipeline/pack/pack.py`) | | | 読むのは `manage/cases/txindex.py` の `pack_info`(パックの有無の判定はここだけ) |
| スタジオ `data.json` | 候補の点数・series(`pipeline/analyze/analyze.py`・`pipeline/batch.py`) | `status`(adopted/rejected)・`adoptedBy`・`file`・手動マーク | | `human/review/store.py`(スレッドセーフ・原子的に書く)。分けるのは RS6 |
| 友人の依頼の受付の記録 `intake-state.json` ほか | 取り込み・流す(`src/home/autorun.py` の AutoRunner) | 確認・届ける(`human/friend/intake.py`・`deliver.py`・`delivery.py`) | | `manage/cases/cases.py` が案件として束ねる |
| 実行の記録 `autorun-runs.jsonl` | 書くのは `src/home/autorun.py` の AutoRunner | | | 読むのは `pipeline/runlog.py`(`read_runs_log`)。履歴の画面・autorun・ライブの失敗の集約 `pipeline/live_failures.py` |
| `live/reports/*.json`(配信ごとの記録) | `samples`(遅れ・メモリ・再起動)・`detect`(候補数)・`tx`・`exports`・`disk`(`pipeline/live_report.py`) | `detect.adoptedAuto/Manual`(`_decisions` の origin)・`request {rid, streamer}`(友人) | 読むのは `src/eval/tools/eval_marks.py --live` | `live_detect`(`pipeline/analyze/live_detect.py`)は ① の `peaks.json` + ② の `decisions.json` の重ね合わせで、望む形の見本 |
| `learn-feedback.json` | | 提案の採用・却下 | | 書くのは `human/proof/learn.py` の `record_feedback`、① の `doc_jobs` が `autoLearned` のとき読む(計画 6(B) のとおり) |
| `evals/<領域>/<日時>.json` | | | 測る道具の結果(`src/eval/tools/_evalcommon.py` が書く) | ① の 3 か所が読む: `src/home/autorun.py`・`pipeline/analyze/live_detect.py`・`pipeline/analyze/live_excite_worker.py`(`evals/marks` の `clipLength.suggest`) |

**④ が ② の文書に書く入口は 3 つに限り、全部 `human/proof/store.py` の `write_doc` + `_save_lock` を通す**: `eval/drill/drill.py` の `drill_reviewed`・`drill_unreviewed`(「校正済み・見直し」の印)・`eval/drill/evalbatch.py` の `eb_redo_fill`(後処理の作り直し)・`eval/drill/folders.py` の `_eval_mark_docs`(評価用の印)。`evalReviewed` の鍵を知る ② のコード(`store.py`・`rerun.py`・`speakers.py`)は ④ の印と知って触る。

**RS6 に送る**(データの形を変える): 文書の ① 部分(`original`・`recognition`・`diarization.auto`・`fill`)と ② 部分(`segments` の人の直し)を別の入れ物にする(`plan/role-restructure.md` の 5-3 の上書き)。スタジオ `data.json` の ① の候補と ② の採用の分離。
