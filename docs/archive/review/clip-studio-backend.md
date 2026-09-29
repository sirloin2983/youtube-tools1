# 切り抜きスタジオ(clip-studio)サーバー側 見直し報告 — 2026-09-24

担当: Claude Code(サブエージェント「cs-backend」)/ ブランチ `wt/cs-backend`(worktree `/home/claude/wt-cs-backend`)
対象: `clip-studio/` の Python(serve.py・store.py・analyze.py・batch.py・exporter.py・rank.py・common.py)、テスト、README.txt。新規 `handoff.py`。
画面側(index.html・*.js・*.css)は触っていない。版(SERVER_VERSION 0.1.8)は上げていない。README は「次の版(未リリース)」の節に変更点を書いた。

---

## 1. 要約

- **受け渡しの約束(docs/pipeline.md の 2.1・4・6)を実装した**: 書き出した mp4 ごとの `.clip.json`、`GET /api/export` の `path` / `manifest`、`.runtime/studio.json`、`GET /api/siblings`
- **直した不具合(重要度「高」2件)**: 元の動画の末尾をまたぐマークの書き出しが音量調整で必ず失敗する / `feedback.jsonl` が大きくなると古い判定記録が消える
- その他、データ保護(壊れた registry.json が初期状態で上書きされる)、Windows(使用中ポートに bind できてしまう・予約名・長いパス・yt-dlp テンプレートの `%`)、公開リポジトリへの個人データ混入の危険(`studio.log.old`)、テストが固定ポートで他のテストとぶつかる、などを修正
- テスト: 既存 5本 + 新規 2本(`test_handoff.py` 20件・`test_robustness.py` 21件)。Python 211件・e2e_analyze・node 10件・ui-kit 同期、すべて通過。主要な修正 23 か所でミューテーション確認済み

---

## 2. 見つけた問題と対応

重要度: 高 = データが消える・機能が使えない / 中 = 条件次第で失敗・安全性 / 低 = まれ・見た目

### 高

| # | 問題 | 場所・再現条件 | 対応 |
|---|---|---|---|
| H1 | **元の動画の末尾をまたぐマークの書き出しが「空か短すぎます」で失敗する** | `exporter.apply_volume`。`run_ffmpeg` は終了を元の末尾で切り詰めて(例: 25〜40秒のマークを30秒の動画から → 5秒)正しく書き出すのに、音量調整(既定75%なので毎回通る)がマークの長さ(15秒)と比べて 50% 未満 → 失敗。配信の最後のマーク、前後10秒の編集用素材(終了+10秒)で起きうる。新しいテストを書いて初めて見つかった | 音量調整は「切り出した動画そのものの長さ」と比べる。YouTube の取得(`_ytdlp_sections` / `_ytdlp_stream`)も、分かっている配信の長さで切り詰めた長さと比べる(`expected_len`)。テスト `test_end_is_clamped_to_source_length` |
| H2 | **`feedback.jsonl` の古い判定記録が消える** | `analyze.feedback_for_mark`。5MB を超えると `os.replace(path, path + ".old")` で **.old を上書き**していたため、2回目の切り替えで最初の記録が消える。精度改善のための大事なデータ(HANDOVER の方針) | 上限を 32MB(約5万件)にし、超えたら `.old` の**末尾へ移す**(消さない)。移し終えてから元を空にする(途中で止まっても消えない。重複は ts で分かる)。書きかけの行(電源断)があっても次の行と繋がらないよう改行を補う。README の「データを送るとき」に `.old` も追記 |

### 中

| # | 問題 | 場所・再現条件 | 対応 |
|---|---|---|---|
| M1 | 壊れた `registry.json` が黙って seed.json に戻り、**次の保存で登録が初期状態に上書きされる**。中身が配列だと `AttributeError` で 500 | `rank.load_registry` | 壊れていたら `registry.json.corrupt-<日時>.bak` に退避してから seed で始める(`.bak` にしたのは .gitignore の `*.bak` に掛けるため)。一時的に開けない(ウイルス対策のロック等)ときは seed に切り替えず 500 を返す(seed のまま「解決」「取り込み」を押すと上書きになるため)。BOM 付きも読む |
| M2 | Windows で、**他のアプリが使用中のポートにも bind できてしまう** | `ThreadingHTTPServer` は `allow_reuse_address=1`(SO_REUSEADDR)。Windows ではこれで使用中のポートに bind でき、どちらに繋がるか不定。スタジオは 8800〜8819 を探すので、8810 の cut2resolve と重なる可能性がある | `StudioServer`: Windows では SO_REUSEADDR を使わず SO_EXCLUSIVEADDRUSE。**他のツールのサーバーにも同じ問題がある**(8章) |
| M3 | ログの控え `studio.log.old` / `studio-errors.log.old` が .gitignore(`*.log`)に掛からず、push.bat の `git add -A` で**公開リポジトリに載るおそれ**(ユーザー名入りのパス・動画タイトルを含む) | `serve._log`・`common.log_failure` | 控えの名前を `studio.old.log` / `studio-errors.old.log` に。起動時に以前の名前のファイルを自動で改名。`studio.crash.log` も起動時に 1MB で回す。.gitignore への追加は 8章 |
| M4 | テストが**固定ポート 18800** から探すので、同じ版のテストサーバーが他で動いていると `make_server` がそちらを「起動済み」と判断して失敗する(同時に走る他のエージェントのテストと衝突) | `test_api.py` | `make_server(0)` で OS に空きポートを選ばせる。新しいテストも全部空きポート |
| M5 | yt-dlp の `-o` は % 書式なので、**フォルダに `%` があると取得に失敗**する。出力先の設定では `%` を断っているが、既定の `exports/`・`work/` はツールのフォルダの場所しだい | analyze(音声・チャット)・exporter(書き出し) | `common.ytdlp_out` でフォルダ側を `%%` に。3か所とも通すことをテストで固定 |
| M6 | 前回の編集用素材 `<名前>_edit.mp4` だけが残っていると、ffmpeg の `-y` で上書き・yt-dlp は「取得済み」として古いものを使う | `exporter.unique_base` は `<名前>.*` しか見ていなかった | `<名前>_edit.*` も空いていることを確かめる |
| M7 | 出力先のパスが長いと Windows の MAX_PATH(260)を超えて書き出しに失敗しうる | `pick_folder`(フォルダ名60文字)+ ラベル30文字 + 接尾辞 | UTF-16 の単位で 240 に収まるよう、フォルダ名とラベルを削る(接尾辞 `_edit.clip.json`・yt-dlp の `.part` の分を残す)。出力先が短ければ従来どおり |
| M8 | Origin の検査が `o.replace("http://", "") in ALLOWED_HOSTS` で、`http://http://localhost:8800` のような値も通る | `serve._origin_ok` | `"http://" + 許可した Host` との完全一致に(実害は低いが意図どおりに) |
| M9 | 127.0.0.1 への問い合わせ(起動時の probe)が urllib 経由で、環境変数・Windows のプロキシ設定があるとプロキシに回る | `serve.probe` | `http.client` で直接つなぐ(`/api/siblings` も同じ) |

### 低

| # | 問題 | 対応 |
|---|---|---|
| L1 | Windows の予約名の判定が `COM¹`〜`³`・`LPT¹`〜`³`・`CONIN$`・`CONOUT$`・後ろの空白(`con .txt`)を見ていない | `exporter.is_reserved` |
| L2 | `export-log.txt` が 200KB を超えると**消していた**(失敗の直後に大きくなって消えることがある) | `export-log.old.txt` に1世代残す |
| L3 | `cache/meta` の形が違う(tags が数値など)と `classify_stream` が落ち、**記録用の情報のせいで解析全体が失敗**しうる | 読み込み時に形を確認し、違えば取り直し |
| L4 | `archive` の `runs` が壊れていると、その動画の archive 保存が毎回失敗し続ける | 壊れた履歴は読み飛ばす |
| L5 | 音量キャッシュが固定名の一時ファイル + `os.replace`(Windows の一時ロックで失敗)。チャットキャッシュの置き換えも同様。編集用素材の `.edit.json` も同様 | `atomic_write` / `replace_file`(再試行つき)に |
| L6 | 登録済みの YouTube 動画IDを検査せずに yt-dlp の URL にしていた(data.json を手で直された場合) | `build_spec` で `VID_RE` を確認(`--` の後ろなので元々オプション注入はできない。多層防御) |
| L7 | エラーが抽象的: API の OSError は一律「保存に失敗しました」、書き出しの想定外は「内部エラー: 型名」、12時間超は長さが出ない | OSError は権限・空き容量など具体的に(詳細は studio-errors.log にも記録)、内部エラーは「詳細は studio-errors.log」、12時間超は実際の長さを表示 |
| L8 | `serve.py` の未使用 `import mimetypes` | 削除 |

### 見て問題なしとしたもの(セキュリティ)
- Host / Sec-Fetch-Site(GET・書き込み)と Origin(書き込み)の検査、`application/json` 必須(CSRF のプリフライト)、本文 4MB 上限、読み取りのタイムアウト
- 静的ファイルは固定の対応表だけ(パストラバーサル不可)。`/media` はクライアントからパスを受け取らず、store の file 動画だけを realpath + 拡張子の確認のうえ Range 配信(シンボリックリンク経由の非メディアも拒否、既存テストあり)
- 外部コマンドはすべて引数リスト(`shell=True` なし)、YouTube の URL は検査済みID + `--` の後ろ、ffmpeg は `-protocol_whitelist file,pipe`(ストリーム直接指定時のみ http/https)
- 署名つき URL はログで `<URL>` に置き換え。`.clip.json` に API キーは入らない(テストで確認)

### 直さなかったもの(理由)
| 内容 | 理由 |
|---|---|
| data.json が壊れたとき `.bak` から自動で戻す | 仕様書の「設計判断」に「壊れたら退避して空で起動」とあるため変えない。**提案**(9章) |
| file 動画のID(パスの sha1)が Windows で大文字小文字を区別する(`C:\A.mp4` と `c:\a.mp4` が別の動画になる) | IDの作り方を変えると既存の data.json の動画と繋がらなくなる(移行が必要)。まれなので記録のみ |
| `data.json.bak` のコピーが原子的でない | `data.json` 本体は原子的。`.bak` が壊れるのは本体も同時に壊れたときだけで、毎回 fsync を増やすほどではない |
| yt-dlp が `b`(単一形式)で webm を返したとき、音量調整後の中身が mp4 なのに拡張子が .webm のまま | `--merge-output-format mp4` + `bv*+ba/b` ではほぼ起きない。直すと `file` の名前が変わり画面・記録に波及する |
| 解析中も出力先を変えられない(`busy()` に解析を含む) | 既存の決定の範囲。解析は出力先を使わないので緩めてもよい(提案) |

---

## 3. 追加した機能と使い方

### 3.1 書き出しごとの `.clip.json`(`youtube-tools-clip/v1`、pipeline.md の 2.1)
- 書き出した mp4 の隣に `<拡張子を .clip.json に置き換えた名前>` を、一時ファイル → 置き換えで書く(UTF-8・BOM なし)。**前後10秒の編集用素材 `*_edit.mp4` にも**付ける
- 書く順番: 切り出し → 音量調整 → 編集用素材 → マークを「書き出し済み」に記録 → `.clip.json` → item を `done`(画面が done を見た時点でファイルがある)
- 書けなくても書き出しは成功(`done`)。`warning` に「切り抜きの情報ファイル(.clip.json)を保存できませんでした(動画はそのまま使えます): <どのファイルか>」、`manifest` は `null`、詳細は studio-errors.log
- 中身の決め方
  - `range`: 元の配信の秒。**元の長さが分かれば終了をそこで切り詰める**(中身と一致させるため)
  - `export.mode`: 実際に使った方法。`"precise"`(再エンコード。開始はフレーム精度で `range.start`)/ `"fast"`(コピー。開始はキーフレーム単位で前にずれる)。速度優先を選んでもコピーに失敗して再エンコードに切り替わった場合は `"precise"`
  - `export.actualStart`: `fast` で、元が手元のファイル(file 動画・疑似モード)かつ **ffprobe があるときだけ**。ffprobe で「開始以前で最後のキーフレーム」を探し、出力側の映像の開始時刻(B フレームの遅延ぶん。合成動画で 0.2 秒)を引いた値 = 切り抜きの 0 秒が元の何秒か。YouTube の速度優先は取得元を調べられないので入れない(推定値は入れない)
  - `export.volume`(%)。編集用素材は `export.purpose: "edit-handles"` と `export.selection: {start, end}`(切り抜き本体の範囲)も
  - `mark.status`: 記録できれば `"exported"`。書き出し中にマークを動かして記録されなかったときは、書き出しを始めた時点の判定
  - `source`: youtube は `{kind, videoId, url, title, path: null}`、file は `{kind: "file", videoId: 内部ID, url: null, title, path: 元のファイル}`
  - `tool.version` は serve.py の SERVER_VERSION(`handoff.TOOL` に起動時に入れる。版の正は serve.py のまま)

### 3.2 `GET /api/export?id=` の各 item(画面の担当へ)
```json
{
  "id": "m1", "start": 1.0, "end": 3.0, "title": "テスト", "status": "done", "progress": 1.0,
  "file": "<動画名フォルダ>/01_00h00m01s-00h00m03s_テスト.mp4",          // 既存: 出力先からの相対(区切りは /)
  "error": null, "warning": "",                                             // 既存(複数の注意は " / " で連結)
  "path": "C:\\...\\exports\\<動画名フォルダ>\\01_00h00m01s-00h00m03s_テスト.mp4",   // 新規: mp4 の絶対パス
  "manifest": "C:\\...\\01_00h00m01s-00h00m03s_テスト.clip.json",           // 新規: .clip.json の絶対パス(書けなければ null)
  "editPath": "C:\\...\\01_..._テスト_edit.mp4", "editManifest": "C:\\...\\01_..._テスト_edit.clip.json"   // 新規: 編集用素材(無ければ null)
}
```
- `path` / `manifest` / `editPath` / `editManifest` は **`status === "done"` の item だけ**に値が入る(それ以外は null)
- 「文字起こしで開く」リンクは `?media=` + `encodeURIComponent(item.path)`。`file` は従来どおり相対のまま(既存の画面・テストが使っている)

### 3.3 実行中のポートの共有(pipeline.md の 4)
- 起動時に `<clip-studio の1つ上>/.runtime/studio.json`(環境変数 `YTT_RUNTIME_DIR` 優先)へ `{"tool":"studio","port":8800,"version":"0.1.8","startedAt":"2026-09-24T10:23:15+09:00","pid":1234}` を原子的に書く。書けなくても起動は続ける
- 正常終了(Ctrl+C・SIGTERM/SIGBREAK・serve_forever の終了)で消す。**`port` と `pid` が自分のものと一致するときだけ**消す(別のプロセスが書き直したファイルを消さないため。pid は生存確認には使っていない)
- `GET /api/siblings` → `{"tools": {"studio": 8800, "transcribe": 8775}}`
  - 自分自身は問い合わせずに含める。他は `.runtime/transcribe.json` / `cut2resolve.json` の**固定の2ファイルだけ**を読む(ファイル名に外の文字列を使わない)
  - ファイルは信用しない: 4KB 超は読まない、`tool` がファイル名と一致、`port` は `type(p) is int` で 1024〜65535(真偽値・小数・文字列は不可)
  - 問い合わせ先は 127.0.0.1 固定、`GET /api/ping` を 0.3 秒の時間制限で**並行して**行い、`app` が一致したもの(transcribe-tool / cut2resolve)だけ。全体で最大 0.5 秒程度で返る(応答しないサーバーがあっても)
  - http.client で直接つなぐ(プロキシ設定の影響を受けない)

### 3.4 `/api/state` の `env`(起動時の環境チェック)
```json
"env": {"checked": true, "python": "3.11.15",
        "tools": {"ffmpeg": {"found": true, "version": "6.1.1"}, "ffprobe": {"found": true, "version": ""},
                  "ytdlp": {"found": true, "version": "2026.07.01", "ageDays": 85}},
        "outDirFree": 32172457984,
        "warnings": ["yt-dlp が古い可能性があります(2026.07.01。85日前の版)。取得に失敗するときは「yt-dlp -U」で更新してください"]}
```
- 道具の版は起動時に裏のスレッドで1回調べる(`yt-dlp --version` は数秒かかることがあるため)。調べ終わるまで `checked: false`
- `warnings` は画面にそのまま出せる文: ffmpeg / yt-dlp が無い、yt-dlp が 60日より古い、書き出し先の空きが 2GB 未満。既存の項目(`ffmpeg`・`ytdlp` など)はそのまま

### 3.5 その他
- `make_server(0)`: 空きポートで起動(テスト用)
- `common.rotate_log` / `migrate_old_logs` / `ytdlp_out`、`exporter.expected_len` / `is_reserved` / `path_units` / `trim_units` / `copy_actual_start`

---

## 4. テスト

| テスト | 件数 | 結果 | 追加・変更 |
|---|---|---|---|
| test_studio.py | 66 | OK | 変更なし |
| test_api.py | 51(+4) | OK | 空きポートに変更。Origin の完全一致、`/api/state` の env、OSError の具体的な文、**HTTP 越しに書き出して path・manifest・.clip.json の中身を確認** |
| test_analyze.py | 27 | OK | 変更なし |
| test_exporter.py | 18(+13) | OK | **実際に ffmpeg で書き出して** .clip.json(本体・編集用素材)、速度優先の actualStart(キーフレーム5秒ごとの合成動画で 7秒 → 約4.8秒)、ffprobe が無いと actualStart なし、末尾の切り詰め(H1)、.clip.json が書けなくても成功、完了した item だけ path を公開、名前の衝突・予約名・長いパス、export-log、不正な動画ID |
| test_file_recovery.py | 8 | OK | 変更なし |
| test_handoff.py(新規) | 20 | OK | .clip.json の形・BOM なし・API キーを含まない、.runtime の書き込み・自分のものだけ消す・書けなくても続行・信用しないファイルの読み方、siblings(一致しない app・死んだポート・500・壊れた応答・**応答しないツールがあっても 1 秒未満**・プロキシの環境変数を無視・Host 検査)、スタジオ自身が他ツールからの ping に応答 |
| test_robustness.py(新規) | 21 | OK | feedback.jsonl が何度切り替わっても消えない・書きかけの行、registry.json の退避・一時的な失敗・BOM・形の違う入力、meta/archive/音量キャッシュ、ログの名前・旧名の移行、使用中ポートの回避・空きポート、yt-dlp テンプレートの % |
| e2e_analyze.py(ffmpeg) | — | OK | 変更なし |
| `node --test test_review.cjs` | 10 | 10 pass | 変更なし(`/api/export` の既存の項目は変えていないので影響なし) |
| `python -m unittest tools/test_ui_kit_sync.py` | — | OK | 触っていない |

実機に近い確認: `serve.py` を別プロセスで起動 → `.runtime/studio.json` ができる・`/api/siblings` が自分を返す・`/api/state` の env → SIGTERM と SIGINT それぞれで終了し、`studio.json` が消えることを確認。

### ミューテーション確認(23か所。修正を1つずつ壊し、対応するテストが落ちることを確認 → 元に戻した)
音量調整の長さ(H1)/ feedback の移し方(H2)/ 書きかけ行の改行 / siblings の app 一致 / ポートの型 / runtime の所有者確認 / プロキシを使わない / Origin の完全一致 / `_edit` の衝突 / .clip.json の失敗を警告にする / path を完了時だけ公開 / actualStart から映像の開始を引く / コピー方式の記録 / registry の退避 / 一時的な読み込み失敗 / meta の形の確認 / archive の runs / ログの名前 / 予約名の上付き数字 / 長いパスのラベル / OSError の文 / 不正な動画ID / 古い yt-dlp の注意 → **すべて落ちた**(スクリプトはセッションの一時フォルダ。リポジトリには入れていない)

---

## 5. 未確認のこと(実機・Windows でしか確かめられない)
- Windows の SO_EXCLUSIVEADDRUSE で、使用中のポートが本当に飛ばされるか(Linux では使用中ポートの回避をテスト済み)
- 黒い画面の×で閉じたとき(SIGBREAK)に `.runtime/studio.json` が消えるか(Linux の SIGTERM では確認。Windows は数秒の猶予があるので消せる見込み。消えなくても他ツールの ping が失敗して一覧から外れるだけ)
- `copy_actual_start` の精度: 合成動画(libx264)でのみ確認。OBS の録画・.ts など他の形式・YouTube から取った mp4 は未確認(読めない形式では入れないだけ)
- 実際の yt-dlp: `%%` のエスケープ、`yt-dlp --version` の形(winget 版・pip 版)、Windows での出力の文字コード(cp932 の可能性。`-J` は ASCII で出るので影響は小さいと判断)
- 長いパスの切り詰め(Windows の長いパスが無効な環境での実際の上限)
- 「文字起こしで開く」リンク・他ツールの `/api/siblings` との相互確認(他ツールの実装が揃ってから)

---

## 6. ユーザーに判断してほしいこと(安全な既定で進めた)
1. **feedback.jsonl の切り替え**: 上限を 5MB → 32MB に上げ、超えたら `.old` の末尾へ移す(消さない)方式にした。1ファイルのままがよければ上限を無くすこともできる
2. **data.json が壊れたときに `.bak` から自動で戻すか**(9章の提案1)。いまは仕様どおり「退避して空で起動」
3. `.clip.json` を**編集用素材 `*_edit.mp4` にも付けた**(pipeline.md の「書き出した mp4 ごとに」に従った)。不要なら本体だけにできる
4. yt-dlp が「古い」とみなす日数(60日)と、空き容量の注意(2GB)

---

## 7. docs/pipeline.md について(曖昧だった所・追記の提案)
- `export.mode` の値: `"precise"` / `"fast"` とした(スタジオ内部の `accurate` / `fast` を対応づけ)。**実際に使った方法**を書く(速度優先から再エンコードに切り替わったら `precise`)ことを明記したい
- `fast` で `actualStart` が無い場合(YouTube の速度優先・ffprobe なし)、読む側は「切り抜きの 0 秒は `range.start` より最大で数秒前(キーフレームの間隔)」と扱う、と明記したい
- `range.end` は元の長さが分かれば切り詰める(中身と一致)
- 追加の項目(知らない項目は無視、の範囲): `export.volume`、`export.purpose: "edit-handles"` + `export.selection`(編集用素材)、`.runtime/*.json` の `pid`(自分のファイルかを消すときの確認用。生存確認には使わない)
- `mark.status`: 記録できれば `exported`、できなければ書き出し開始時の判定
- 4 の「`.runtime/*.json` を読み」は、既知の3ツールのファイル名だけを読む実装にした(未知のツールは app 名が決まっていないため)

---

## 8. 他の担当・オーケストレーターへ
- **画面(clip-studio UI)の担当へ**: 3.2 の `path` / `manifest`(`status === "done"` のときだけ値あり)で「文字起こしで開く」リンク(`?media=encodeURIComponent(path)`、ポートは `/api/siblings` の `transcribe`、無ければ 8775)。`/api/state` の `env.warnings` は画面に出せる文。`/api/siblings` は `{"tools": {...}}`。item の `warning` は複数あると " / " で連結される
- **文字起こしツールの担当へ**: `.clip.json` の `export.mode` が `fast` で `actualStart` が無いことがある(7章)。編集用素材の `.clip.json` には `export.purpose: "edit-handles"` が付く
- **全ツールのサーバー担当へ(重要)**: `ThreadingHTTPServer` の既定(SO_REUSEADDR)だと、**Windows では使用中のポートにも bind できてしまう**。スタジオの `serve.StudioServer` と同じく、Windows では `allow_reuse_address = False` + `SO_EXCLUSIVEADDRUSE` を勧める。また 127.0.0.1 への問い合わせは urllib ではなく http.client で(プロキシ設定の影響を避ける)。`/api/ping` は Host `127.0.0.1:<port>` の要求に答えること(スタジオはそれで問い合わせる)
- **オーケストレーターへ**:
  - `.gitignore`(リポジトリ直下。担当外なので未変更)に `*.log.old`・`*.old.log`・`**/feedback.jsonl.old`(既存)・`**/registry.json.corrupt-*` の追加を勧める。スタジオ側は名前を変えて対処済み(起動時に旧名を改名)だが、他のツールも `*.log.old` を作っていないか確認を
  - `docs/project/clip-studio-spec.md`(担当外)に 3章の内容(.clip.json・.runtime・env・feedback の切り替え方式)の反映を
  - `docs/WORKLOG.md` は他のエージェントと衝突しないよう**書いていない**。統合時に以下の要約で1件追記してほしい:
    「2026-09-24 Claude Code(cs-backend)— スタジオのサーバー見直し: .clip.json・/api/siblings・.runtime/studio.json、書き出しの末尾またぎ失敗と feedback.jsonl の消失を修正、Windows のポート・予約名・長いパス、ログ名(公開リポジトリ対策)。詳細 docs/review/clip-studio-backend.md。版は未変更」
- ui-kit への要望: なし(画面は触っていない)

---

## 9. 提案(実装していない)
1. **data.json が壊れたとき、`.bak` が読めればそちらから戻す**(壊れたファイルは従来どおり `.corrupt-日時` に残し、画面に「1つ前の控えから戻しました」と出す)。いまは空で起動し、手で戻す必要がある
2. 出力先の `%` の禁止は、yt-dlp のテンプレートをエスケープしたので外せる(外すなら README・画面の文言も)
3. 解析中も出力先を変えられるようにする(解析は出力先を使わない)
4. file 動画のIDを Windows では大文字小文字を無視して作る(移行: 旧IDの動画を見つけたら付け替える処理が必要)

---

## 10. コミット(ブランチ wt/cs-backend、push していない)
```
72d6471 受け渡し用モジュール handoff.py を追加
ea29c72 .clip.json・/api/siblings・.runtime/studio.json、ポート確保とログの扱い
4875c28 feedback.jsonl の消失、壊れたキャッシュ・registry.json
e0d4a18 末尾をまたぐマークの書き出し失敗、受け渡しのテスト
7b46e65 API テストを空きポートに、Origin・env・エラー文・書き出しの受け渡し・データ保護のテスト
83fbacb README の次の版の変更点
111cac1 yt-dlp の出力テンプレートの % をエスケープ
```
変更ファイル: `clip-studio/` の serve.py・store.py(変更なし)・analyze.py・batch.py(変更なし)・exporter.py・rank.py・common.py・README.txt、新規 handoff.py・test_handoff.py・test_robustness.py、test_api.py・test_exporter.py。
