状態(2026-10-10): 案 b(実行ごとのフォルダ)の下調べ・スタジオ側の置き場所(Haiku)

# 作業データの置き場所ごとの読み書きの一覧(スタジオ側)

読むだけの調べ。コードは変えていない。行番号は grep 時点のもの。層は `dev/layer_map.py` の DIRS(`src/ytt`→ytt、`src/pipeline`→pipeline、`src/human`→human、`src/manage`→manage、`src/eval`→eval、`src/app`→app)と FILES(`src/studio/*.py` の残りは app)で読んだ。テストは数だけ。

## 0. 置き場所の決まり(全体)
- 置き場所の根: `datadir.resolve("studio", root, env)` / `datadir.tool_dir` / `datadir.studio_out_dir`(ytt/datadir.py:63,111)。スタジオの作業データの既定は `%LOCALAPPDATA%\youtube-tools\studio`(studio/README.txt:420)。
- 読む側の変数: `ytt/workdata.py`(STUDIO_DATA は 28・39 行目。TRANSCRIBE_STUDIO_DATA で上書き)。`ytt/studio_env.py` は `_home`(24 行)を呼ばれたときに決める(home())。
- 途中のファイルの「作業用/」: `ytt/schemas.py:131`(WORK_DIR = "作業用")、138〜156 行の work_dir / find_sidecar 系。`names.py:60〜71` が所有者の印(OWNER_FILE)を作業用/ に書く。

## 1. スタジオの data.json(動画・配信・候補・自動マーク・手動マーク・採用/不採用)
入口: `studio/serve.py:64` `STORE = store_mod.Store(_env.p("data.json"))`。実体は `human/review/store.py`。

| ファイル:行 | 読む/書く | 層 | 何のために |
| --- | --- | --- | --- |
| human/review/store.py(全体・158〜160・212・380・469〜506・558) | 読む・書く | human | 動画とマークの保存。原子的書き込み・壊れたら .corrupt-日時 へ退避・.bak の控え |
| human/review/store.py:833 `replace_auto` | 書く | human | 自動マークの差し替え(再解析)。auto0Orig を書く |
| studio/serve.py:64・91・518 | 読む・書く | app | STORE の生成・起動時の警告・DATA_ITEMS(data.json ほか)の一覧 |
| studio/startup.py:40〜43 | 書く(退避) | app | .old・ログの回し |
| ytt/studiodata.py:11・15・32〜35 | 読む | ytt | 配信のチャンネル名・題・コラボ(スタジオの data.json を読むだけ)。`workdata.STUDIO_DATA` を呼ぶたびに読む |
| ytt/workdata.py:28・35〜39 | 変数の持ち主 | ytt | STUDIO_DATA の場所 |
| manage/cases/handoff_io.py:66 | 読む | manage | 案件の受け渡しで studio を読む |
| manage/cases/cases.py:84 | 場所だけ | manage | `cases["studio"]` = data.json の場所(案件の一覧) |
| manage/cases/doclist.py:75 | 読む | manage | `studiodata.studio_videos()` 経由 |
| pipeline/transcribe/roster.py:194 | 読む | pipeline | `studiodata.studio_stream(videoId)`(配信ごとの文脈) |
| eval/tools/_evalcommon.py:207 | 読む(差し替え) | eval | `mod.STUDIO_DATA = mod.studio_data_path()` |
| eval/tools/eval_marks.py:125・129〜132 | 読む | eval | data.json の videos と feedback.jsonl(と .old) |
| eval/tools/eval_asr.py:55(文言)・eval_split・eval_fetch | 読む(推測) | eval | --context auto のチャンネル名 |
| home/autorun.py:761 | 場所だけ | app | `evals/marks` の隣に studio の場所を求める |
| home/live.py:224 | 読む | app | settings-ui.json(スタジオ側の設定・同じ置き場所) |
| home/launch.py:967 | 存在だけ | app | スタジオの settings.json の有無 |
| editor/serve.py:684・701 | 読む(場所を決める) | app | `set_data_dir`・`choose_data_dir`(編集が studio の data.json の場所を datadir の規則で決める) |
| ytt/studio_env.py(全体) | 場所の決め | ytt | `home()`・`p(name)`(data.json・feedback.jsonl・config.json などの場所)。`fake()`・`find_tool` も |
| ytt/apikey.py:21・33〜35 | 読む・書く | ytt | スタジオの config.json(APIキー。data.json ではないが同じ置き場所) |
| ytt/settings.py:76・92・191 | 読む・書く | ytt | settings の読み書き(スタジオの settings.json) |
| studio/core.js:118〜132・queue.js:280 | 表示 | app(画面) | dataWarning の表示(data.json の退避の知らせ) |

推測: `store.py` の書き込みは `_warn` とバックアップの .bak を経由する。書き先のパスは `Store(path)` で渡された 1 つだけなので、置き場所を変えるときはこの 1 行で済む。

## 2. 元の動画・ダウンロード・チャット・音声の一時ファイル
| ファイル:行 | 読む/書く | 層 | 何のために |
| --- | --- | --- | --- |
| pipeline/analyze/analyze.py:49・53 `chat_cache_dir` / `sig_cache_dir` | 場所を返す | pipeline | チャットと音量の cache(スタジオの cache/) |
| pipeline/analyze/analyze.py:154・171・186・196〜200 | 読む・書く・消す | pipeline | チャットの cache(`<vid>.live_chat.json`)・上限・使用中の印・古いものを消す |
| pipeline/analyze/analyze.py:245・269 | 書く・消す | pipeline | 音量の署名 cache(`<vid>.json`) |
| pipeline/analyze/analyze.py:147 | 読む | pipeline | 作業用の `audio.*` を探す(`os.path.join(wdir, "audio")`) |
| pipeline/analyze/analyze.py:332 | 書く | pipeline | チャット cache のフォルダを作る |
| pipeline/analyze/analyze.py:436・551 | 読む(yt-dlp 経由) | pipeline | コメント・メタの取得 |
| pipeline/ingest/sources.py(全体・推測) | 読む・書く | pipeline | 元の動画・音声の取り込み(yt-dlp の出力先) |
| pipeline/ingest/live_archive.py:228・247 `fetch_full_audio` | 書く・読む | pipeline | `full.*` の音声をフォルダへ |
| pipeline/ingest/live_archive.py:410 | 書く | pipeline | `<exporter.folder>/archive.json` |
| pipeline/ingest/live_archive.py:1093・1120・1451 | 書く | pipeline | `作業用/archive-<id>`・`作業用/build`・`作業用/speed` |
| pipeline/analyze/live_excite_worker.py:1167 | 書く | pipeline | 配信中のチャット `<dir>/chat`(子プロセス) |
| pipeline/transcribe/tx_engines.py:218 `fetch_file` | 書く | pipeline | 文字起こし用のファイル取得 |
| pipeline/transcribe/live_tx.py(推測) | 書く | pipeline | 配信中の候補の文字起こし |
| manage/keep/cleanup.py:68・131・214 | 読む・消す | manage | 片付け(作業用/ の一覧・ごみ箱) |
| eval/tools/eval_speakers.py:837 `tempfile.mkdtemp` | 書く | eval | 評価の一時 wav |
| eval/tools/_evalcommon.py:187 | 書く | eval | 評価の一時フォルダ |
| ytt/tools.py・ytt/procs.py | 実行のみ | ytt | yt-dlp・ffmpeg の子プロセス(場所は持たない) |
| ytt/fsio.py:41 | 書く | ytt | 一時ファイル `.tmp-*.part` の作り方(原子的書き込み) |
| ytt/jobs.py:153 | 場所の設定 | ytt | `tmp_dir: tempfile.gettempdir`(ジョブの一時。既定は OS の temp) |

## 3. 書き出し先と切り抜き(.clip.json・パック・作業用)
書き出し先: `ytt/studio_env.py:109〜178`(default_out_dir・get_out_dir・set_out_dir・load_out_dir。settings.json の outDir)。`ytt/datadir.py:111` `studio_out_dir`(既定は作業データの exports)。

| ファイル:行 | 読む/書く | 層 | 何のために |
| --- | --- | --- | --- |
| ytt/studio_env.py:120・125〜153 | 読む・確かめる | ytt | 書き出し先の取得と検査(realpath・書けるか試す) |
| studio/startup.py:94 | 読む | app | 書き出し先のフォルダ |
| studio/serve.py(書き出し API) | 読む・書く | app | 書き出しのジョブ |
| pipeline/export/exporter.py:142・524・711・791 | 書く | pipeline | 作業用/ へ途中のファイル。`spec["outDir"]` を使う |
| pipeline/export/exporter.py:546 | 読む | pipeline | yt-dlp の `.f399.mp4.part` の名前 |
| pipeline/export/manifest.py(.clip.json の組み立て) | 書く | pipeline | `.clip.json` |
| ytt/schemas.py:16・131・138〜175・229・401 | 場所の計算・読む・書く | ytt | `CLIP_SUFFIX`・`WORK_DIR`・`work_dir`・`find_clip_path`(作業用/ → 動画の隣)・`load_clip_file` |
| manage/cases/pipeline_io.py:55・111 | 読む・書く | manage | `load_clip_file`・`save_beside` |
| manage/cases/cases.py(clip_live・一覧) | 読む | manage | 案件の一覧 |
| manage/keep/cleanup.py:68・214 | 読む・消す | manage | 作業用/ の片付け |
| eval/tools/eval_fetch.py:319 | 書く | eval | 評価の作業用 |
| home/live.py:755・266 | 場所を返す | app | ライブの書き出し先(`OUT_DIR`) |
| human/friend/deliver.py:63・276〜346 | 書く | human | 友人への届ける先(`OUT_DIR`) |
| cut2resolve/serve.py:78・335 | 書く | pipeline | パックの作業用(WORK_DIR を作業データの中へ切り替え。`_choose_work_dir` 879) |

推測: exporter の `folder` は `spec["outDir"]` からの相対で、スタジオの settings.json の outDir が既定。

## 4. 録画(HLS・ライブのデータ)
| ファイル:行 | 読む/書く | 層 | 何のために |
| --- | --- | --- | --- |
| pipeline/ingest/recorder.py:61・64・83 | 読む・書く | pipeline | `datadir.locate("recorder", …)`(`src/recorder/data`)・token・録画フォルダの記録 |
| pipeline/ingest/rec_core.py:311・693 | 書く・読む | pipeline | 録画の状態の save/load(推測: 録画の作業フォルダ) |
| home/live.py:196〜198・266 | 場所を返す | app | `recorder_data_dir`・`store_dir = <logs の隣>/live` |
| home/live.py:749 `deliver_dir` | 場所を返す | app | 届ける先 |
| pipeline/export/live_export.py(推測) | 書く | pipeline | 配信の書き出し(live の書き出し先) |
| pipeline/ingest/live_archive.py(全体) | 書く | pipeline | アーカイブの取り込み・archive.json |
| pipeline/analyze/live_detect.py | 読む・書く | pipeline | 配信中の検出(推測: live の状態) |
| manage/keep/live_cleanup.py | 読む・消す | manage | ライブの片付け |
| human/friend/live_requests.py・friend_feedback.py | 読む・書く | human | 友人の依頼・返事(logs/friend_feedback.jsonl) |
| eval/tools/eval_marks.py:847〜850・947〜995 | 読む・書く | eval | `live/live_feedback.jsonl`・`live/reports/`・`friend_feedback.jsonl` |
| ytt/recproto.py・ytt/names.py | 読む(推測) | ytt | 録画の共通の形・名前 |
| src/recorder/data(README・AGENTS 記載) | 置き場所 | (旧パス) | inplace の作業データ `data/`(旧い置き場所) |

## 5. 採用の記録 feedback と スタジオの settings.json
| ファイル:行 | 読む/書く | 層 | 何のために |
| --- | --- | --- | --- |
| human/review/feedback.py:15・20 | 場所・上限 | human | `feedback.jsonl`(32MB 超は .old の末尾へ移す。消さない) |
| human/review/feedback.py:65・71・111・133 | 書く・移す | human | 採用・不採用・削除・書き出し・手で足した行 |
| human/proof/learn.py:222 `load_feedback` | 読む | human | 学習(盛り上がりの学習の記録。`feedback.jsonl`) |
| eval/tools/eval_marks.py:129〜132 | 読む | eval | feedback.jsonl.old → feedback.jsonl の順 |
| studio/serve.py:518 DATA_ITEMS | 一覧 | app | 退避・バックアップの対象 |
| manage/keep/backup.py(全体) | 読む・写す | manage | バックアップの写し(data.json・feedback・設定を写す) |
| ytt/settings.py:76・92・191・322 | 読む・書く | ytt | settings の読み書き・`in_eval_dir` |
| ytt/workdata.py(変数) | 持ち主 | ytt | 置き場所 |
| home/prefs.py・home/settings/schema.json | 読む(推測) | app | 入口の設定 |
| studio/settings.js・studio/rank.js(画面) | 表示・保存 | app(画面) | スタジオの設定の画面 |

## 6. 数(置き場所ごと・推測を含む)
- 1. data.json: 直接の読み書きは `human/review/store.py`(と `ytt/studiodata.py`・`manage/cases/handoff_io.py`・`doclist.py`・`roster.py`・eval の読み取り)。パスの持ち主は `ytt/workdata.STUDIO_DATA` と `studio_env.p("data.json")` と `manage/cases/cases.py:84` の 3 か所。**変えるときに直す所: 約 12 件**(読む側はパスを変数で受けているので、置き場所の持ち主 3 か所を直せば済む見込み。推測)。
- 2. 元の動画・一時の cache: `analyze.py`(cache 4 関数)・`live_archive.py`・`exporter.py`・`sources.py`・`tx_engines.py`・eval 2 件。**約 10〜15 件**(推測)。
- 3. 書き出し・切り抜き: `studio_env`・`datadir.studio_out_dir`・`exporter.py`(4 件)・`schemas.work_dir`・`manifest.py`・`pipeline_io.py`・`cleanup.py`・`cut2resolve/serve.py`。**約 15 件**(推測)。
- 4. 録画: `recorder.py`・`rec_core.py`・`live.py`(3 件)・`live_archive.py`・`live_export.py`。**約 8 件**(推測)。
- 5. feedback・settings: `feedback.py`(1 件の場所)・`settings.py`・`apikey.py`・`studio_env.p`。**約 6 件**(推測)。

## 7. パスを自分で組み立てている所(変数を通さない直書き)
- `ytt/schemas.py:141`・`names.py:60〜71`・`names.py:108`・`exporter.py:142・524・711・791`・`cleanup.py:68・214`・`eval_fetch.py:319`: `WORK_DIR`("作業用")を直接 `os.path.join` している。実行ごとのフォルダに変えるなら、これらは `work_dir()` 経由に寄せる必要がある。
- `live_archive.py:1093・1120・1451`: `"archive-"+id`・`BUILD_DIR`・`SPEED_DIR` を直接組み立て。
- `home/autorun.py:761`・`pipeline/analyze/live_excite_worker.py:304`: `"evals", "marks"` を直接組み立て。
- `home/live.py:266`: `os.path.dirname(logs_dir)` + `"live"`(直書き)。
- `eval_marks.py:847〜850`: `LIVE_DIR = "live"`・`LIVE_FEEDBACK` などのファイル名を定数で持つ。
- `cut2resolve/serve.py:78`・`cut2resolve`: `os.path.join(CODE_DIR, "work")`(既定の直書き、起動時に切り替え)。

## 8. 所見(要点)
- 置き場所の「持ち主」は `studio_env.p`・`workdata.STUDIO_DATA`・`cases.locations` の 3 系統で、読む側は大半がこの変数を経由する。実行ごとのフォルダに変えるなら、この 3 つを先に 1 本にまとめるのが効く。
- 「作業用/」は `schemas.WORK_DIR` の 1 定数だが、直書きの組み立てが 10 件前後ある(第 7 節)。
- feedback.jsonl と data.json は 1 ファイルずつ(全体のまとめ)なので、実行ごとのフォルダへ分けると「全体の判定の集計」(eval_marks・learn)が複数フォルダを読むことになる。推測として、集計側の変更が一番大きい。
- 未確認(推測のまま): sources.py・live_export.py・live_detect.py・live_tx.py・rec_core.py の中の正確な行。読んだのは grep の一致行だけ。
