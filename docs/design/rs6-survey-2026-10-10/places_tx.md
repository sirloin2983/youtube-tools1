状態(2026-10-10): 案 b(実行ごとのフォルダ)の下調べ・文字起こし・パック・入口の置き場所(Haiku)

# 作業データの置き場所と読み書きするコード(読むだけの調べ)

調べ方: `src/` の .py と .js を grep。テストは数だけ数えた。層は `dev/layer_map.py` の DIRS(`src/pipeline`=pipeline・`src/human`=human・`src/manage`=manage・`src/eval`=eval・`src/ytt`=ytt)と FILES(`src/editor` 等の殻)で判定。`src/editor/` と `src/studio/` と `src/home/` は app 層のまま残るものが多い。
「推測」と書いたものは行を読んでいない。

## 1. 文字起こしの文書と横のファイル(`workdata.TX_DIR` = 作業データ/transcripts)

置き場所の値: `src/ytt/workdata.py:26-51`(`TX_DIR` は `<DATA_DIR>/transcribe/transcripts` 系。読む側は `workdata.TX_DIR` と呼ぶたびに読む)。

| ファイル:行 | 読む/書く | 層 | 何のために |
|---|---|---|---|
| src/human/proof/store.py:29 | 書く/読む | human/proof | `<id>.json`(文書本体)の path |
| src/human/proof/store.py:47 | 書く | human/proof | `.bak/` の退避 |
| src/human/proof/store.py:240 | 読む | human/proof | 文書 id の一覧(`TX_DIR` を listdir、`TID_RE` で絞る) |
| src/human/proof/store.py:282 | 書く | human/proof | `.hist/<id>` の履歴 |
| src/human/proof/store.py:447 | 書く/読む | human/proof | `<id>.edit.json`(カットの時刻の細かい保存。文書と別 rev) |
| src/human/proof/store.py:707 | 書く | human/proof | `<id>.edit.broken.json` の退避 |
| src/pipeline/transcribe/records.py:148 | 書く/読む | pipeline/transcribe | `<id>.asr.json`(生出力) |
| src/pipeline/transcribe/records.py:181 | 書く/読む | pipeline/transcribe | `<id>.words.json`(単語の時刻) |
| src/pipeline/transcribe/recognize.py:393 | 書く/読む | pipeline/transcribe | `.resume/<id>.whole.json`(途中再開) |
| src/pipeline/transcribe/diarize.py:295 | 書く/読む | pipeline/transcribe | `<id>.diar.json`(判別の記録。`update_diar_voices` 330 行) |
| src/pipeline/transcribe/llm.py:310,323 | 書く/読む | pipeline/transcribe | `<id>.llm.json` |
| src/human/proof/alt.py:127 | 書く/読む | human/proof | `<id>.alt.json`(2 つ目のエンジン) |
| src/human/proof/ytcap.py:456 | 書く/読む | human/proof | `<id>.ytcap.json`(推測: YouTube 字幕の取り込み) |
| src/human/proof/doc_jobs.py:346,391 | 読む/書く(経由) | human/proof | 生出力と LLM 記録を records・llm に渡す |
| src/human/proof/speakers.py:151,709 | 書く(経由) | human/proof | `<id>.diar.json` へ判別の記録 |
| src/human/proof/retime.py(入口) | 読む | human/proof | `<id>.words.json` を読んで時刻を計算 |
| src/pipeline/transcribe/fill.py:225 | 読む(コメント) | pipeline/transcribe | 後処理は `.asr.json` を残す |
| src/manage/cases/relink.py:173 | 書く | manage/cases | `.bak/<id>.edit.pre-relink.json` |
| src/manage/cases/txindex.py(全体) | 読む | manage/cases | 文書の一覧・文書と動画の紐づけ(`folder()`・`load()`・`pick()`・`pack_info()`) |
| src/manage/cases/doclist.py | 読む | manage/cases | 文書一覧と要約キャッシュ(`store` 経由) |
| src/manage/cases/txlink.py:16-35 | 読む | manage/cases | 文書の根 = `txindex.folder(...)`(読むだけ) |
| src/manage/cases/cases.py:84,98 | 読む | manage/cases | 文書フォルダの場所と一覧 |
| src/eval/tools/eval_asr.py・eval_alt.py・eval_fill.py・eval_timing.py・eval_speakers.py・_evalcommon.py | 読む | eval/tools | 測る道具が文書・横のファイルを読む |
| src/eval/drill/folders.py・metrics.py・accuracy.py | 読む | eval/drill | 評価用のフォルダ整理 |

ファイル数: 直接の書き手 = human/proof(store・alt・ytcap・speakers・doc_jobs)、pipeline/transcribe(records・diarize・llm・recognize)。読むだけ = manage/cases と eval。入口の画面 src/editor/app*.js は API 経由で読む(推測)。

## 2. 文書の一覧と紐づけ(動画・マーク・.clip.json との対応)

| ファイル:行 | 読む/書く | 層 | 何のために |
|---|---|---|---|
| src/manage/cases/txindex.py:151 | 読む | manage/cases | `pack_dir(media)`(動画の隣の `<名前>_pack`) |
| src/manage/cases/txindex.py:195-196 | 読む | manage/cases | 以前のパックの `cut-plan.json` |
| src/manage/cases/txindex.py:208 | 読む | manage/cases | `pack_info(media_path)` = パックの有無の判定(1 か所) |
| src/manage/cases/txindex.py:6-14 | — | manage/cases | 紐づけの規則(動画の path → 元の配信の id → `.clip.json`)の文書 |
| src/manage/cases/doclist.py:21-24 | 読む | manage/cases | 動画の隣のパック判定を txindex へ委譲 |
| src/manage/cases/cases.py:6-7,27-28,84,167-169,253,279,445,552 | 読む | manage/cases | 案件の画面の一覧・文書の紐づけ・`.clip.json` の source.live |
| src/manage/cases/handoff_io.py:135-161 | 読む | manage/cases | `/api/clip-info`(動画または `.clip.json` の path) |
| src/manage/cases/pipeline_io.py:49-80 | 読む | manage/cases | `.clip.json` の探す・読む・検証(動画は作業用/ の 1 つ上 or 同じフォルダ) |
| src/ytt/schemas.py(`clip_path_for`・`find_clip`・`WORK_DIR`) | 読む | ytt | `.clip.json` の場所の規則(作業用/ の下) |
| src/pipeline/export/manifest.py:12,22 | 書く | pipeline/export | `作業用/<名前>.clip.json` |
| src/pipeline/export/exporter.py:805,810,832 | 書く | pipeline/export | `.edit.json`(編集用素材の隣)・`.clip.json` |
| src/pipeline/export/live_export.py:22,31 | 書く | pipeline/export | 配信の書き出しの `作業用/<名前>.clip.json` と `live/live_feedback.jsonl` |
| src/pipeline/ingest/live_archive.py:29,1472 | 書く | pipeline/ingest | `.clip.json` の `source.live.archive` を直す |

## 3. パック(Resolve 用フォルダ・zip)

| ファイル:行 | 読む/書く | 層 | 何のために |
|---|---|---|---|
| src/pipeline/pack/pack.py:196-197 | 書く | pipeline/pack | `default_out_dir(video)` = 動画の隣の `<動画名>_pack/`(パックの本体の出力先) |
| src/pipeline/pack/pack.py:647,683 | 書く | pipeline/pack | `out_dir or default_out_dir(...)` で書く |
| src/pipeline/pack/pack.py:668 | 読む | pipeline/pack | `prev_copy`(前のパックの記録の videoCopy)を serve が渡す |
| src/cut2resolve/serve.py:322-335 | 書く | app(cut2resolve 殻) | `write_pack_record` = 作業データの `packs/<フォルダのハッシュ>.json`(`_txi.packs_dir`) |
| src/pipeline/pack/cut2resolve_core.py:805 | 書く | pipeline/pack | 記録の videoCopy の中身 |
| src/pipeline/pack/cut2resolve_core.py:922-940 | 読む | pipeline/pack | 余白つき素材 `<動画名>.edit.json`(作業用/ → 動画の隣の順) |
| src/pipeline/pack/cut2resolve.py:136 | 読む | pipeline/pack | CLI の `.edit.json` 指定 |
| src/manage/cases/txindex.py:151-151,195-208 | 読む | manage/cases | パックの有無は記録(`packs/`)と `cut-plan.json` の両方で見る |
| src/manage/cases/cases.py:104,445,552,578 | 読む | manage/cases | `pack_dir` / `pack_info` を案件の画面・捨てる・届ける判定で |
| src/human/friend/deliver.py:1-9 | 読む/書く | human/friend | Dropbox の `出力\` へ zip(`<依頼 id>__<題>`。同名は 4 文字足す)。パックのフォルダを zip |
| src/pipeline/run.py:130,169,206,739-740 | 書く | pipeline | 実行で作ったパックのフォルダを `self.packs` に記録(`autorun-active.json` に残す) |
| src/ytt/studio_env.py:109-112 | 読む | ytt | スタジオの書き出し先の既定 = `<置き場所>/exports` |
| src/manage/keep/cleanup.py:30 | 読む(片付け) | manage/keep | 途中のファイルの SIDECARS に `.cut-plan.json`・`_edit.mp4` などを含む(パック側の残り) |

推測: 「パック」の実体は (a) 動画の隣の `<名前>_pack/` フォルダ、(b) 作業データの `packs/<ハッシュ>.json` の記録、(c) 旧い `cut-plan.json` の 3 つが並んで、どれを正とするかは `txindex.pack_info` 1 か所で決まる。

## 4. 入口の記録(実行・案件・配信の報告)

| ファイル:行 | 読む/書く | 層 | 何のために |
|---|---|---|---|
| src/pipeline/runlog.py:14 | 書く/読む | pipeline | `RUNS_LOG = "autorun-runs.jsonl"`(入口の作業データの logs の中。`read_runs_log`) |
| src/pipeline/run.py:12,163-169 | 書く/読む | pipeline | `autorun-active.json`(待ちの記録。`restore` で同じ実行に戻す) |
| src/home/live.py:296,361 | 書く/読む | app(home) | `live_report.Reporter` と失敗の集約が `runs_log` を読む |
| src/pipeline/live_report.py:5,18 | 書く | pipeline | `live/reports/<録画元>__<録画の id>.json`(書き手はここだけ) |
| src/pipeline/export/live_export.py:81 | 書く | pipeline/export | `live/live_feedback.jsonl`(採用の記録。feedback.jsonl とは別) |
| src/pipeline/analyze/live_detect.py:627,662 | 書く | pipeline/analyze | `live_feedback.jsonl` に `detect_compare` を 1 行 |
| src/pipeline/ingest/live_archive.py:55,975 | 書く | pipeline/ingest | `live_feedback.jsonl` に採用・比較 |
| src/manage/cases/cases.py:6-7,27-35,421,539 | 読む/書く | manage/cases | 案件の画面(`.clip.json`・ごみ箱フォルダへ移す) |
| src/manage/keep/backup.py:72,330,367 | 読む/コピー | manage/keep | バックアップの走査(`DirEntry`)と写し戻し(`--restore`) |
| src/home/live.py:30 | 読む | app(home) | ライブの採用の記録の説明 |

## 5. 学習データと評価用

| ファイル:行 | 読む/書く | 層 | 何のために |
|---|---|---|---|
| src/ytt/workdata.py:26,51 | 変数 | ytt | `FEEDBACK = <DATA_DIR>/learn-feedback.json`(提案の採用・却下の記録) |
| src/ytt/settings.py:3,19,175 | 読む/書く | ytt | 編集の設定 settings.json(学習の設定の入れ物) |
| src/pipeline/transcribe/roster.py:18,186-190 | 読む | pipeline/transcribe | 名簿 `roster.ROSTER`(編集の ed_state が入れる。推測: `hololive-roster.json` を編集のフォルダに置く) |
| src/pipeline/transcribe/fill.py:181,246 | 読む | pipeline/transcribe | 名簿(後処理) |
| src/pipeline/transcribe/llm.py:277 | 読む | pipeline/transcribe | 名簿の member 一覧 |
| src/pipeline/transcribe/replace.py(全体) | 読む | pipeline/transcribe | 置換辞書(`set_dict_inputs` で登録した口から読む) |
| src/pipeline/transcribe/records.py:24-118 | 読む | pipeline/transcribe | 辞書の版(`dict_version`)・学習の記録(`learned`)・名簿のハッシュ |
| src/human/proof/learn.py(全体) | 読む/書く | human/proof | 学習(覚えた置換・採用/却下の記録)。推測: `learn-feedback.json` を読み書き |
| src/human/proof/speakers.py:709 | 書く(経由) | human/proof | 覚えた声(voices)の照合経過を `diar.json` へ |
| src/pipeline/transcribe/diarize.py:330-338 | 書く | pipeline/transcribe | `voices` を `<id>.diar.json` の latest に |
| src/eval/drill/folders.py・drill.py・evalbatch.py | 読む/書く | eval/drill | 評価用のフォルダ整理・ドリル(推測: `dataset/`・`eval-audio/` を読む) |
| src/eval/tools/_evalcommon.py・eval_*.py(13 本) | 読む | eval/tools | 評価用の文書と音声 |

`dataset/` と `eval-audio/` の文字列は src/ の .py では「評価データ」の説明に出るだけで、置き場所の定数は見つけられなかった(推測: `src/eval/drill/folders.py` か `workdata.EVAL_BASE` の下)。

## 6. 保管と片付けの対象

| ファイル:行 | 対象 | 層 | 何を |
|---|---|---|---|
| src/manage/keep/backup.py:41,100 | 作業データ一式(`transcribe\bin\whisper.cpp-*` は写す) | manage/keep | 写す・`--restore` で戻す |
| src/manage/keep/cleanup.py:30 | 元動画と一緒の途中のファイル: `.clip.json`・`.edit.json`・`.transcript.json`・`.cut-plan.json`・`.studio-id`・`_edit.mp4`・`.srt` | manage/keep | 片付けで移す |
| src/manage/keep/cleanup.py:218,234-254 | 文字起こしの作業用(`workdir`)・`cache/peaks`・`datadir.resolve(tool)` の一覧 | manage/keep | `os.listdir` で列挙 |
| src/manage/keep/cleanup.py:349 | 削除対象の拡張子(`.transcript.json`・`.clip.json`・`.edit.json`・`.cut-plan.json`・`.srt`) | manage/keep | 片付けの一覧 |
| src/manage/keep/live_cleanup.py(推測: 存在を確認していない) | 配信の録画・`live/` | manage/keep | 推測 |

## 7. 数の集計(推測を含む)

置き場所ごと、実行ごとのフォルダに変えたとき直す所(概数):

| 置き場所 | 直す所の数(概数) | 根拠 |
|---|---|---|
| 1 文字起こしの文書と横のファイル(`TX_DIR`) | 約 25(human/proof 6・pipeline/transcribe 8・manage/cases 4・eval 6 ほか) | 上の表の行数 |
| 2 文書の一覧と紐づけ(txindex 系) | 約 12(txindex・doclist・txlink・cases・handoff_io・pipeline_io) | 表 2 |
| 3 パック(pack・記録・deliver・run) | 約 10(pack.py 2・serve 1・cut2resolve_core 2・txindex 2・cases 3・deliver 1・run 2) | 表 3 |
| 4 入口の記録(RUNS_LOG・autorun-active・live/reports・live_feedback) | 約 9(runlog・run・live_report・live_export・live_detect・live_archive・home/live・cases・backup) | 表 4 |
| 5 学習と評価(roster・replace・learn・settings・eval) | 約 12(roster・fill・llm・replace・records・learn・speakers・diarize・eval 系) | 表 5 |
| 6 保管と片付け(backup・cleanup) | 約 4(backup 3・cleanup 3) | 表 6 |

テストの数は未集計(各 test_*.py が `TX_DIR` を差し替えているので、実数は数百の行になる推測)。

## 文書の id(ランダム)を前提にしている所

- src/human/proof/store.py:240 `TID_RE` で `<id>.json` を絞る(id の形を前提)
- src/ytt/schemas.py の `TID_RE`・`make_key`(成果物の鍵の形)
- src/pipeline/transcribe/records.py:148 `tid + ".asr.json"` などすべての `<id>.<拡張子>` 系
- src/manage/cases/txindex.py: 動画の path → 文書 id の対応(`pick`)が id の形を前提にしている(推測)

実行ごとのフォルダにすると、横のファイルの名前(`<id>.*`)を `<実行 id>/` の下へ移すだけで済むが、`TID_RE` と `list` の列挙(store.py:240)、`txindex.pick` の対応は作り直しになる(推測)。

## パスを直書きしている所(確認できたもの)

- src/cut2resolve/serve.py:322-335 `packs/` の記録(`_txi.packs_dir` の中)
- src/pipeline/pack/pack.py:197 `f"{Path(video).stem}_pack"`
- src/pipeline/export/manifest.py:12 `作業用/<名前>.clip.json`(日本語のフォルダ名)
- src/pipeline/export/live_export.py:81 `live_feedback.jsonl`
- src/pipeline/export/exporter.py:790 `作業用/`(出力先の直下はパックと元動画だけ)
- src/manage/cases/pipeline_io.py:66 動画のフォルダ = `.clip.json` が `作業用/` なら 1 つ上
- src/pipeline/run.py / runlog.py の `autorun-runs.jsonl`・`autorun-active.json`
- src/pipeline/live_report.py:5 `live/reports/`
- src/manage/keep/cleanup.py:30 の拡張子の一覧

## 要点

1. 文字起こしの横のファイル(`<id>.*`)は human/proof と pipeline/transcribe の両方が書くので、実行フォルダ化の影響が一番大きい(約 25 箇所)。
2. パックは「動画の隣」「作業データの packs/」「旧い cut-plan.json」の 3 つの置き場所に分かれ、`txindex.pack_info` 1 か所で判定している。ここを変えれば 3 の大半が済む。
3. 入口の記録(runs・live_feedback・live/reports)は pipeline に集まっていて、実行フォルダへ移すなら runlog と run.py の 2 箇所が起点になる。
4. 学習データ(roster・辞書・learn)は workdata/ROSTER の変数で差し替えているので、実行フォルダ化の対象外にしやすい(推測)。
5. 片付け・バックアップは拡張子の一覧(cleanup.py:30・349)と `datadir.resolve` の名前に依存しており、新しいフォルダ構成では一覧の更新が要る。
