# 文字起こしツール サーバー側の見直し(2026-09-24)

担当: 文字起こしツールのサーバー側(`transcribe-tool/` の serve.py・resolve_export.py・新規 pipeline_io.py・テスト・README.txt)。ブランチ `wt/tt-backend`。
版(SERVER_VERSION 0.9.9)は上げていない。README は「次の版の変更(サーバー側)」の節に追記した。
精度改善 v2(TRANSCRIPTION_V2_DESIGN.md)には手を付けていない。

## 1. 要約
- **直したバグ・弱点 17 件**(高 3・中 8・低 6)。どれもテストを足し、ミューテーション確認(直した所を元に戻す/壊すとテストが落ちる)をした
- **受け渡しの約束(docs/pipeline.md 2.1〜2.3・4・6)を実装**: `.clip.json` の読み込み、`GET /api/clip-info`、`GET /api/transcript-v1`、`POST /api/export-file`、`.runtime/transcribe.json`、`GET /api/siblings`
- **細かい改善**: 起動時の環境チェック、エラーを理由つき JSON で返す、モデルを使わない間は手放す、再認識で必要な所だけ音声を取り出す、一覧のキャッシュ など
- テスト: 単体 80 件すべて通過(元 37 件 + 追加 43 件)。e2e 5 本は刷新前の画面で想定どおり(v07・v09 の「版 v0.9.4」だけ失敗)。test_document_save.cjs 9/9

## 2. 見つけた問題と対応

| # | 重要度 | 場所 | 問題と再現条件 | 対応 |
|---|---|---|---|---|
| 1 | 高 | serve.py `Handler._fetch_site_ok` / `_guard` | 他のツールの画面のリンク(http://localhost:8800 → http://localhost:8775/?media=…)で開くと **403 forbidden**。ポートが違うだけでもブラウザは `Sec-Fetch-Site: same-site`(127.0.0.1 と localhost なら cross-site)を送るため。Playwright で旧版 403・新版 200 を確認した | 画面(`/`・`/index.html`)への**トップレベルの遷移**(`Sec-Fetch-Mode: navigate` かつ `Sec-Fetch-Dest: document`)だけ許可。API は従来どおり同じ画面からだけ。iframe 埋め込みは `X-Frame-Options: DENY`・`frame-ancestors 'none'` で拒否、`Referrer-Policy: same-origin` |
| 2 | 高 | serve.py `apply_diarization` / `apply_retranscribe` / `apply_range` | 話者判別・再認識の結果の書き込みが、保存のロック(`_save_lock`)を取らずに「読み直し → 書き込み」していた。その間に画面の自動保存が入ると、**その保存が黙って上書きされて消える** | 保存と同じロックの中で読み直し〜書き込み(`_apply_*` に分けた)。文書の削除も同じロックの中で(削除の直前に読んだ書き込みが、消した文書を生き返らせていた) |
| 3 | 高 | pipeline(新規)/ `?media=` | 画面は `?media=` を受けて clip-info を自動で呼ぶ想定。値は他のサイトのリンクからも来るので、Windows で `\\サーバー\共有\…` の存在を確かめると、**そのサーバーへ資格情報(NTLM ハッシュ)を送ってしまう** | clip-info と、`.clip.json` の中の media.path では、ネットワークのパス(`\\…`・`//…`)を調べない(`warning` を返す)。文字起こしの開始ボタン(利用者の操作)では従来どおり使える |
| 4 | 中 | resolve_export.py `build_plan` | **範囲指定の文書**(例: 1時間の動画の 100〜160 秒)で、素材の長さに「ファイル全体の長さ」を足していた → SOURCE_WITH_HANDLES の終わりが 3710 秒(動画は 3600 秒)、FCPXML の素材の長さも過大 | 範囲の長さ(end − start)を使い、後ろの余白はファイルの終わりで止める |
| 5 | 中 | serve.py `atomic_write` | fsync せずに置き換えていたので、停電・強制終了のあとに**中身が空の文字起こし**が残りうる。Windows ではウイルス対策・検索インデックスが一瞬ファイルを開いていて `os.replace` が PermissionError になることがある | fsync してから置き換え、Windows の PermissionError は最大 6 回(計約1秒)やり直す。失敗時は一時ファイルを必ず消す |
| 6 | 中 | serve.py `validate_diarize` / `validate_retranscribe` → `add_job` | 同じ文字起こしへの話者判別・再認識の重複を確かめてから、別のロックで待機列に入れていた(同時に2回押すと両方入る) | `add_job` の中(待機列と同じロック)でも確かめる(`EXCLUSIVE`) |
| 7 | 中 | serve.py `run_retranscribe` / `run_abtest` | 1行の再認識・比較でも、**文書の範囲全体(最大6時間)** の音声を取り出して float32 に展開していた(6時間で約 2GB・取り出しに数十秒) | 対象の行の最初〜最後 ±3.3 秒だけ取り出す(`audio_span`)。範囲の再認識は最大 15 分なので常に小さい |
| 8 | 中 | serve.py `load_model` | 読み込んだモデル(large-v3 で数GB)を、使わなくなってもずっと保持 | ジョブが 15 分無ければワーカーが手放す(`TRANSCRIBE_MODEL_IDLE_SEC`、0 で無効)。手放すのはジョブの合間だけ(使用中は消さない) |
| 9 | 中 | serve.py Handler | ApiError 以外の例外(RecursionError・想定外の OSError など)で、**応答なしに接続が切れる**(画面は「サーバーに接続できません」)。403/413/415 は素の文字列で、画面は「エラー 403」としか出せない | 全メソッドを `_safe` で包み、500 + 理由の JSON と serve.log への記録。403/413/415/404 も `{"error","message"}` の JSON。読み書きの時間切れ 120 秒(送ると言った長さより短い本文でスレッドが止まり続けない) |
| 10 | 中 | serve.py `load_settings` / `load_roster` 他 | README が「直せます」と案内している hololive-roster.json・settings.json を、メモ帳の「UTF-8 (BOM 付き)」で保存すると、**名簿が読めない・置換辞書が文字起こしで黙って使われない** | 手で直すファイルと他のツールの data.json は `utf-8-sig` で読む。`GET /api/settings` も BOM を外して返す |
| 11 | 中 | serve.py `list_transcripts` / `transcribed_ranges` / `scan_common` | 一覧・マーカー・フォルダの表示のたびに、全文書を JSON として2回ずつ読んでいた。フォルダ一括の判定はフォルダの数だけ全文書を読み直し、500 件を超えるフォルダでは判定が漏れた | 要約を(更新日時, 大きさ)でキャッシュ、判定は1回、パスを直接照合。同じファイルが2回あれば1回だけ待機列へ |
| 12 | 低 | serve.py `valid_model` | faster-whisper は、モデル名と同じフォルダが手元にあればそれを読む。`transcripts` などの名前も通っていた(攻撃には Origin の突破が要るので低) | 手元に実在するパスになる名前は断る |
| 13 | 低 | serve.py `_origin_ok` | `"http://"` を消してから比べていたので、`http://localhost:8775http://` のような崩れた値も通った(ブラウザは送らない) | `"http://" + 許可したホスト` と完全一致 |
| 14 | 低 | serve.py `_read_json` | `NaN` / `Infinity` を含む JSON を受け付け、settings.json に書くと画面の `JSON.parse` が壊れる | 400 で断る |
| 15 | 低 | serve.py `export_corrections` | 途中で失敗(評価用の指定など)すると、作りかけの zip が `transcripts/.tmp` に残る | 失敗時に消す |
| 16 | 低 | serve.py `archive_doc` | ffmpeg が無いのに前回の full.flac が残っていると `_flac_cut(None, …)` で TypeError → 保管が失敗 | ffmpeg があるときだけ切り出す |
| 17 | 低 | serve.py `probe` | 起動済みの確認(127.0.0.1)が環境変数のプロキシを通るので、HTTP_PROXY がある環境では「起動済み」と分からず二重に起動しうる | プロキシを使わない opener |

### 直さなかった・見送ったこと
- **文字起こしの削除で `.hist/<id>/` と `.bak/<id>.*`・dataset/ が残る**: 消えた文書を手で戻せる利点もあるので、既存の動作のまま。個人データを残したくない場合は「削除で履歴も消す」か「ゴミ箱に移す」をユーザーに決めてほしい
- **修正データの書き出し(export-corrections)が HTTP の処理の中で同期的に動く**(音声つき 400 行で数分): 画面の待ち方が変わるので、ジョブ化は画面側と相談が要る
- **Resolve パッケージは元の動画を丸ごと zip に入れ、一時フォルダ(%TEMP%、ふつう C:)に作る**: 長い配信だと C: の空きを使い切りうる。設計(GPT)どおりなので残した
- 同じフォルダで旧版と新版のサーバーが同時に動く場合、保存のロックはプロセスごと。保存の競合検出(updatedAt)で守られるので、そのまま

## 3. 受け渡しの API(画面の担当向けの形)

すべて従来の Host / Sec-Fetch-Site 検査の対象(同じ画面からだけ)。エラーは `{"error": コード, "message": 日本語の理由}`。

### 文字起こしの開始時の `.clip.json`(2.1)
- `POST /api/transcribe` と `POST /api/transcribe-batch` で、動画の隣の「拡張子を `.clip.json` に置き換えた名前」を探す。`youtube-tools-clip/v1` として検証できたら文書に `clip`(中身そのもの。知らない項目も残す)を保存
- 検証: `schema` が完全一致、`range.start/end` が有限の数で `0 ≤ start < end`、`source`・`media`・`mark`・`export`・`tool` はあればオブジェクト、`export.actualStart` はあれば 0 以上の数。256KB まで・BOM 可
- 不正・別の版 → 使わずに**ジョブの `warnings`(文字列の配列)** に理由。ジョブには `hasClip`(真偽)も足した。`/api/transcripts` の各項目にも `hasClip`
- 動画の長さと `media.durationSec` が 3 秒を超えて違えば、clip は使うが `warnings` に注意
- **範囲指定の文字起こしのときの扱い(決定)**: clip は変えずにそのまま保存。文書の行の時刻は従来どおり「動画ファイルの先頭 = 0 秒」(範囲の開始を足した値)なので、**元の配信の時刻 = `export.actualStart`(無ければ `range.start`)+ 行の時刻** が範囲指定でもそのまま成り立つ。範囲の開始で補正すると二重に足すことになるので、しない。transcript/v1 には範囲を `transcribedRange: {start, end}` で示す(約束に無い追加項目。読む側は無視してよい)

### `GET /api/clip-info?path=<動画 または .clip.json のパス>`
```json
{"clip": {…clip/v1…} | null, "clipPath": "…/動画_0012.clip.json" | null, "mediaPath": "…/動画_0012.mp4" | null, "warning": "理由" | null}
```
- 約束の `{"clip": …}` に `clipPath`・`mediaPath`・`warning` を足した(形の追加)
- `.clip.json` のパスを渡すと(画面の `?clip=` 用)、動画を ①`media.path` ②同じフォルダの `media.name`(名前だけ使う)③同じ名前 + 動画の拡張子 の順に探して `mediaPath` に入れる
- 見つからない・壊れている・ネットワークのパス → **200** で `clip: null` と `warning`(画面が `?media=` で開いたときに例外にしないため)。400 は `path` が空、または動画でも `.clip.json` でもないときだけ
- ffmpeg を呼ばないのですぐ返る。**画面の読み込み時に自動で呼んでよい**(ネットワークのパスは調べない)

### `GET /api/transcript-v1?id=<文字起こしID>`
約束 2.2 の形。`segments` は開始時刻の順(画面の sortSegs と同じ安定ソート)、**文字が空の行は入れない**(画面の書き出しと同じ)、`speaker` は `speakers` の並び順の番号(話者なしは `null`)、`cut` は `cutState == "cut"`、`proofed` は真偽。`original`・params・flag・tags などは入れない。追加項目: `language`、範囲指定なら `transcribedRange`

### `POST /api/export-file`
```json
要求: {"id": "…", "format": "transcript-v1" | "srt" | "cut-plan-v1", "baseUpdatedAt": 保存済みの updatedAt(任意), "wrap": 0(SRT の折り返し文字数・任意), "speakerNames": false(SRT に「[名前] 」・任意)}
応答: {"path": "C:\\…\\動画_0012.transcript.json", "name": "動画_0012.transcript.json", "overwritten": false, "format": "transcript-v1", "count": 行数(cut-plan は区間数)}
```
- 名前: 動画の名前から拡張子を除いたもの + `.transcript.json` / `.srt` / `.cut-plan.json`(`.clip.json` と同じ「拡張子を置き換える」規則。SRT はプレーヤーが自動で読む名前)
- **保存済みの内容**を書き出す。画面は先に保存してから呼ぶこと。`baseUpdatedAt` を付けると、保存済みの版と違うとき **409**(`conflict`)
- 同名があるとき: **このツールが前に書いた同じ schema(schema 一致かつ `tool.name == "transcribe-tool"`)なら上書き**(`overwritten: true`)。それ以外は `名前 (2).transcript.json`、`(3)`… の順に、空いている名前か、前にこのツールが書いた同じ schema のものを使う(書き出すたびに増えないように)。**SRT は常に別名**(中身で自分が書いたか判断できず、手で直した字幕を消さないため)
- cut-plan/v1 は他のツールも書ける形式なので、schema が同じでも `tool.name` が違う(無い)ファイルは上書きしない
- 書き込みは一時ファイル(fsync)→ ハードリンクで置く(既存のファイルを決して上書きしない。使えないドライブでは存在を確かめてから置き換え)。BOM なし・改行は LF
- 400: `no_media`(文書に動画のパスが無い・動画が見つからない)、`no_dir`、`no_write`(読み取り専用・他のアプリで開いている)、`write_failed`(長いパスのときはヒント付き)、`empty`(書き出す行・残す区間が無い)、`bad_format`。404: 文字起こしが無い
- SRT の規則(画面の exportRows / buildExport と同じ): 文字が空の行は出さない、開始は 0 未満にしない、終わりが 0 以下の行は出さない、ミリ秒は四捨五入。**時刻の基準は動画の先頭**(範囲指定の文書でも動画の時刻のまま。その動画の隣に置く字幕なので)。**カット済の行も出す**(字幕は動画全体に対するもの。カットは cut-plan と一緒に cut2resolve が適用する)。SRT の書式は `resolve_export.srt_text` に1か所化(Resolve パッケージの SRT と共用)
- cut-plan/v1 の規則: `resolve_export.kept_spans`(Resolve パッケージのカットと同じ関数。**どの行を残すかの判定 `is_kept` は1か所だけ**)。「カット済」でない・文字のある行の時間を、重なる・接するものどうしでまとめる。**行と行の間のすき間(無音)は残さない**(Resolve パッケージの従来の動作と同じ)。各区間: `id`(segment-001…)、`start`/`end`(秒・動画の先頭基準)、`status: "adopted"`、`label`(区間の文章の先頭 40 文字)、`lines`(まとめた行の id。追加項目)。`media`・`tool`・`createdAt`・`title` も入れる

### `.runtime/transcribe.json` と `GET /api/siblings`(4)
- 起動時に `<transcribe-tool の1つ上>/.runtime/transcribe.json`(`YTT_RUNTIME_DIR` 優先)へ `{"tool": "transcribe", "port", "version", "startedAt", "pid"}` を原子的に書く。書けなくても起動は続ける(serve.log に警告)。`pid` は参考のためだけで、生存確認には使わない
- 正常終了で消す: Ctrl+C に加え、SIGTERM と Windows の SIGBREAK(黒い画面を×で閉じた・Ctrl+Break)も同じ後始末に回す。**自分が書いた記録(同じポート・同じ pid)のときだけ**消す(別のポートで後から起動した同じツールの記録を消さない)
- `GET /api/siblings` → `{"tools": {"transcribe": 8775, "studio": 8800, …}}`。`.runtime/{studio,transcribe,cut2resolve}.json` だけを読み、`tool` がファイル名と一致・`port` が 1〜65535 の整数(bool は不可)のものを、**127.0.0.1 固定**・プロキシ無し・0.3 秒の時間制限で**並列に** `/api/ping` し、`app` が一致したものだけ返す。自分自身は常に含める。答えないサーバーがあっても約 0.3〜0.5 秒で返る

## 4. 細かい改善(サーバーだけで完結)
- 起動時の環境チェック: Python の版・ffmpeg・保存先への書き込み・ディスクの空き(2GB 未満)・index.html との版の違い・部品(pipeline_io.py / resolve_export.py)の欠け・OneDrive の同期フォルダ内。黒い画面と serve.log に出し、`/api/tools` の `envWarnings`(文字列の配列)でも返す(画面で出すかは画面の担当が判断)
- エラーメッセージを具体的に: 保存の失敗(ディスクの空き・権限・他のアプリ)、削除の失敗、元の動画が無い、Host が違う、別のサイトからの操作、など
- ログ: 画面が頻繁に呼ぶ・パスを含む API(jobs・media・siblings・progress・clip-info)は黒い画面に出さない。想定外の例外と「動画の隣に保存」は serve.log に残す
- **pipeline_io は必要になったときに読み込む**: README で長く「index.html と serve.py の2つを上書き」と案内してきたので、serve.py だけ差し替えられても起動はするように(受け渡しの API は理由つきの 500、起動時に警告)。README の更新手順は「.py と index.html をまとめて」に直した

## 5. テスト
- `python -m unittest test_metrics test_resolve_export -q` → **80 件 OK**(test_metrics 34 + 追加の test_backend 40 + test_resolve_export 6)。test_backend は test_metrics の末尾で読み込むので、従来のコマンドのまま走る(`python -m unittest test_backend` 単体でも可)
- 追加したテスト(test_backend.py): 保存ロックの待ち(3種)、原子的な書き込みの失敗時、add_job の排他、書き出し失敗時の zip、ffmpeg なしの保管、BOM、起動チェック、モデル名、clip/v1 の検証・ファイル・動画探し・ネットワークのパス、transcript/v1・cut-plan/v1・SRT の中身、動画の隣への保存(上書きの規則・SRT・作ってから置くまでの競合・権限エラー)、.runtime の読み書き・検証、疑似モードのサーバーでの通し(clip の保存・範囲指定・不正な clip・一括・clip-info・export-file 3形式・409・動画なし・siblings(答えない/app 違い/誰もいない)・画面の遷移の許可と API の拒否・Origin・NaN・415・想定外の例外で 500・SIGTERM で .runtime を消す)、audio_span と再認識・比較の取り出し範囲、モデルを手放す時間、要約のキャッシュ、フォルダ一括の判定の回数
- test_resolve_export.py に 3 件: 範囲指定の文書の素材の長さ、kept_spans の規則、SRT の書式
- **ミューテーション確認**(`/tmp/claude-0/tt-backend/mutate.py` でコードを1か所ずつ壊して実行): 37 か所を試し、36 か所でテストが落ちることを確認。最初に見逃した2か所(ハードリンクで置く競合・siblings の app 照合)はテストを強めて検出するようにした。残る1か所(siblings の join の締め切り)は、ping 自体の 0.3 秒の時間制限と同じ働きなので等価(検出不能)
- e2e(刷新前の index.html、Playwright): e2e_ui_v07 37/38・e2e_ui_v09 56/57(どちらも「版 v0.9.4」だけ=想定内)、e2e_ui_v08 59/59、e2e_eval_v093 22/22、e2e_ui_v098 135/135。e2e_ui_v098 は pipeline_io・resolve_export も置いた状態でも 135/135
- `node --test test_document_save.cjs` 9/9、`tools/test_ui_kit_sync.py` OK
- Playwright で「別のポートの画面からのリンク」を実際に開き、旧 serve.py は 403(`Sec-Fetch-Site: same-site`)、新 serve.py は 200 を確認

## 6. 未確認のこと・リスク・ユーザーに判断してほしいこと
- **実機(Windows)で未確認**: ×で閉じたときの SIGBREAK での後始末(×のあと約5秒で強制終了されるので、後始末は間に合う想定)、ハードリンクでの保存(NTFS は可、exFAT などは存在確認→置き換えに切り替わる)、`os.replace` のやり直し、OneDrive 配下での動作、実際の faster-whisper でのモデルの解放とメモリの戻り、長いパス(260 文字超)
- **cut-plan/v1 で行の間のすき間を残さない**のは、Resolve パッケージの従来の規則(GPT の設計)に合わせたため(「規則を二重に持たない」指示)。ショート動画ではすき間を詰める(ジェットカット)のが一般的だが、「カット済の行だけを消して、すき間は残す」方が良ければ、`kept_spans` にすき間を埋める幅(例: 1 秒以下のすき間はつなぐ)を足せば両方に効く。**ユーザーに決めてほしい**
- **モデルを 15 分で手放す**のは既定の推測値。次の文字起こしで 10〜30 秒の読み込み直しが入る。メモリより待ち時間を優先するなら `TRANSCRIBE_MODEL_IDLE_SEC=0`(start.bat で設定)
- 他のサイトのリンクからも画面を開けるようになった(許可は画面の表示だけ。API は従来どおり同じ画面から)。画面が URL の値で**重い処理を自動で始めない**ことが前提(docs/pipeline.md の 3)。画面の担当に守ってもらう
- 文字起こしの削除で履歴・控え・保管が残る件(2 の「見送った」)

## 7. 他の担当へ
- **画面(index.html)の担当へ**
  - 上の 3 の API の形で作ってください。約束からの追加: clip-info の `clipPath`・`mediaPath`・`warning`、export-file の `name`・`format`・`count` と任意の `baseUpdatedAt`・`wrap`・`speakerNames`、ジョブの `warnings`・`hasClip`、一覧の `hasClip`、`/api/tools` の `envWarnings`
  - 「動画の隣に保存」は、**保存が終わってから** `baseUpdatedAt: S.doc.updatedAt` を付けて呼ぶと、画面と違う内容を書き出さない(409 なら保存し直してから)
  - `clip` の中の文字列(`source.title`・`mark.label`・`source.url` など)は外から来るので、必ずエスケープ。URL をリンクにするなら `https://www.youtube.com/` で始まるものだけに
  - ジョブの `warnings`(例: .clip.json が別の版)を処理状況に出してほしい
  - e2e スクリプトで serve.py を一時フォルダへ写すときは、**`pipeline_io.py` と `resolve_export.py` も写す**(写さないと受け渡しの API が 500)
  - エラー応答はすべて `{"error","message"}` になったので、`api()` の `j.message` がそのまま使える
- **切り抜きスタジオ・cut2resolve の担当へ(重要)**: 各 serve.py の `_fetch_site_ok` が `Sec-Fetch-Site in (None, "same-origin", "none")` だけを許しているので、**他のツールの画面のリンクから開くと 403** になる(文字起こしツールで実際に確認した同じ問題)。画面への遷移(`Sec-Fetch-Mode: navigate`・`Sec-Fetch-Dest: document`)だけ許可し、`X-Frame-Options: DENY` を付ける修正を勧める(transcribe-tool/serve.py の `Handler._navigation_ok` を参照)
- **cut2resolve の担当へ**: 文字起こしの cut-plan/v1 は**行単位**(短い区間がたくさん)。auto_cut の既定の編集余白 10 秒で使うと、区間どうしが余白で全部つながり、**カット済の行が消えない**。`tool.name == "transcribe-tool"` の cut-plan は余白 0 を既定にするか、画面で選ばせてほしい。区間の `lines`(行の id)は字幕との対応づけに使える
- **オーケストレーターへ**: transcribe-tool/AGENTS.md(担当外なので未変更)のテストの説明に「test_backend.py(test_metrics から読み込む)」と「e2e で写すファイルに pipeline_io.py・resolve_export.py」を足してほしい。docs/WORKLOG.md も担当外なので未記入

## 8. ui-kit への要望
サーバー側の担当なので特になし。

## 9. 変更したファイル
- `transcribe-tool/serve.py`(修正・受け渡しの API の配線・起動チェック)
- `transcribe-tool/pipeline_io.py`(新規。clip/v1・transcript/v1・cut-plan/v1・SRT・動画の隣への保存・.runtime・siblings)
- `transcribe-tool/resolve_export.py`(`is_kept`・`kept_spans`・`srt_text`・`srt_time` を公開、範囲指定の文書の長さの修正)
- `transcribe-tool/test_backend.py`(新規)、`test_metrics.py`(新しい部品を写す・test_backend の読み込み・.runtime をテスト用フォルダに)、`test_resolve_export.py`(3 件追加)
- `transcribe-tool/README.txt`(次の版の変更・更新するファイル・困ったとき)
