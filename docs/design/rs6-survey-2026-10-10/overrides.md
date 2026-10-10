状態(2026-10-10): RS6 の下調べ(Haiku)の報告

# RS6 下調べ: 校正の上書きと切り抜きの鍵

読むだけの調査。コードは変えていない。推測は「推測」と書いた。

## 1. 文書と生の認識の形

| 物 | 場所 | 中身 |
| --- | --- | --- |
| 文書 `transcripts/<id>.json` | `store.tx_path`(`human/proof/store.py:28`) | `segments`(行)・`speakers`・`original`(機械の出力)・`words`・`recognition`・`retranscribed`・`relinks`・`sourcePath`・`updatedAt`・`evalSet` |
| 行 | `sanitize_transcript`(`store.py:79-`) | `id`・`start`・`end`・`text`・`speaker`・`flag`・`tags`・`proofed`・`proofedAt`・`cutState`・`noSub`・`fill`(別の読みで埋めた印) |
| 話者 | 同 | `id`・`name`・`color`・`sub`(字幕の見た目)。`OTHER_SPK_ID` は組み込み |
| 生の認識 `transcripts/<id>.asr.json` | `records.asr_path`(`pipeline/transcribe/records.py:147`)・`write_asr` は `ASR_SCHEMA = youtube-tools-asr-raw/v1`(`:143`) | 分ける前・置換の前の認識の結果。単語の時刻と確信度。書くのは `doc_jobs.py:387` だけ |
| 単語 `words.json` | `records.words_path`(`:180`) | 行の単語の時刻 |
| 原文 `original` | `doc_jobs._rows_to_doc`(`doc_jobs.py:407-`) | 行と同じ時刻の機械の出力(`text` は置換・学習の前) |

推測: `asr.json` と `original` は重複している。`original` は再認識の差し替えで `replace_original` により部分更新される(`rerun.py:83`)。`asr.json` は再認識で更新されない(書くのは初回の run だけと読める)。

## 2. 文書の作られ方と再認識

流れ: 認識(`recognize`)→ `_rows_to_doc`(`doc_jobs.py:407`)で行 id を `s1..` と振り、`postproc.make_flags` で印・`original` に機械の値 → `_doc_fields` → 文書を保存。id は毎回振り直すので、**行 id は文書を作り直すと変わる**。

| 操作 | 関数 | 人の直し(proofed・proofedAt・cutState)の扱い |
| --- | --- | --- |
| 選んだ行の再認識 | `rerun._apply_retranscribe`(`rerun.py:93-123`) | 差し替えた行は `proofed`・`proofedAt` を pop(`:108-109`)。話者の印だけ残す。`original` は範囲を差し替え。`record_rerun` で前の機械の値を残す(`:42`) |
| 疑わしい行の再認識(redo) | `apply_redo`(`rerun.py:293`)・`redo_targets`(`doc_jobs.py:519`) | `proofed` が真の行は対象外(`:307`・`:529`)。人が直した行も置き換えない。1 回の保存で履歴に残す |
| 文書の作り直し(文字起こし全体) | `run_job`(`doc_jobs.py:331`) | 新しい id・新しい行。既存の人の直しは引き継がない(推測: 同じ動画でも行は新規) |
| 行の範囲の再認識 | `_apply_range`(`rerun.py:215`) | 範囲の行を入れ替える。範囲に重なる校正済みの行の扱いは `plan_range`(`:185`)を読む必要あり(未確認) |

結論: 全部消えるのではなく、**差し替えた範囲だけ**消える。ただし「文書を作り直す」(run_job)は行 id が変わるので、人の直しは全部失われる。これが F-3 の「ID で対応づけできない」の根拠。

## 3. 人の直しの種類と文書での残り方

| 種類 | 残るもの | 根拠 |
| --- | --- | --- |
| 文字 | `text` を上書き。`original` は変えない(機械の値は残る) | `_rows_to_doc`・`save_transcript` は画面の値を受けて `sanitize_transcript` を通す |
| 校正済み | `proofed: true` と `proofedAt`(初回の時刻。保存済みの同じ id から引き継ぎ・画面の値は使わない) | `store.py:104-132` |
| 時刻 | `start`・`end` を画面の値で上書き(小数 2 桁) | `store.py:110-` |
| 話者 | `speaker`(文書の `speakers` にある id だけ) | `store.py:110`。話者の判別の反映は `speakers.py` の apply_diarization |
| 行の分割・結合 | 新しい id(`sid` を画面から受けるが、重複は `x` を付けて直す = `store.py:100-`)。`resplit_doc`(`doc_jobs.py:272`)は分割で `proofed` の行を尊重 | 推測: 分割は行 id を新規にする |
| 削除 | 行が送られなければ消える(`store.py` は送られた行だけ保存) | 推測 |
| 空の行の下書き | `text` が空の行。`sanitize` は通す。`draft` の概念は `edit_draft`(`store.py:608`)とは別 | `doc_jobs.py:412` は空の行を捨てる(機械側) |
| 要確認の印 | `flag` を画面の値で保存(100 字まで) | `store.py:112` |
| 音のメモ | `tags`(ROW_TAGS の中だけ) | `store.py:113-115` |
| カット | 行に `cutState: "cut"`。`apply_edit_cuts`(`store.py:581`)が `edit.json` の区間から印を付け直す | `store.py:124-131`・`store.py:556-581` |
| 字幕を出さない | `noSub: true` | `store.py:131` |

## 4. カット `transcripts/<id>.edit.json`

- `store.edit_path`(`store.py:446`)。`sanitize_edit`(`store.py:462`)の形: `{"sources": [{"fps": [n, d], "duration"}], "clips": [{"src": 0, "in", "out"}], "origin"}`。区間は元の動画の秒。`rev`・`packRev` はサーバーが付ける。
- 結びつき: 文書の行の `cutState` は `apply_edit_cuts` で区間から導く(行の時刻と区間の重なり = `edit_cut_flags` `store.py:556`)。つまり**カットは文書の行に従属し、行の時刻が変わるとカットの印も変わる**。
- 文書とは別ファイル。`relink` は `edit.json` を `.bak/<id>.edit.pre-relink.json` にバックアップする(`relink.py:171`)。

## 5. 切り抜きの付け替え `relink.py`

- `relink_doc`(`relink.py:131`): `sourcePath`・`sourceName`・`updatedAt`・`relinks`(履歴)だけを書く。**行・校正・話者・original・時刻・カットは変えない**(docstring)。
- `_relink_write`(`:166`): 控え `.bak/<id>.pre-relink.json` と履歴を残す。`bump=False` で 30fps の写しへの自動付け替えは `updatedAt` を変えない。
- 30fps の作り直し(`norm_*`・`:204-`)は同じ時刻の動画を作るので、行の時刻はそのまま使える(docstring の「時刻は秒なので同じ」)。
- F-2(速報版 → 本番版の入れ替え)への使える点: 付け替えは「文書の中身を変えず、動画だけ変える」の既存の型。上書きを入れ替え先の鍵へ付け替える処理の口として使える。ただし `norm_swap`(`:276`)は版の入れ替えの処理(未読・推測)。

## 6. 「上書き」を ① の出力と別に持つ形にするときの影響範囲

### 画面と API が読む・書く所

| 場所 | 読む・書く | 内容 |
| --- | --- | --- |
| `src/editor/app-rows.js:43`・`:129` | 書く・読む | `PUT/GET /api/transcript?id=`(文書全体) |
| `src/editor/app.js:1205` | 削除 | `DELETE /api/transcript` |
| `src/editor/serve.py` `:272`(GET `/api/transcript`)・`:36` | 読む・書く | 文書の入出力 |
| `serve.py:275-279` | 読む | `/api/edit`・`/api/edit/draft`・`/api/doc-for` |
| `serve.py:303-320` | 書く(ジョブ) | `/api/transcribe`・`/api/diarize`・`/api/retranscribe`・`/api/redo`・`/api/alt`・`/api/ytcap` |
| `serve.py:250-` | 読む | `/api/transcript-v1`(受け渡し形式。`_handoff_io.transcript_v1`) |
| `src/editor/app-tools.js:378` | 書く(画面) | 聞かずに書き換えた行は `proofed` を消す |
| `src/editor/app-rows.js:1006` | 書く(画面) | 結合のとき両方校正済みでないと外す |
| `src/editor/app-jobs.js:604`・`app-tools.js:216`・`app-list.js:259` | 読む | 件数・絞り込みの表示 |
| `src/studio/review.js:3002` | 読む | スタジオの一覧の校正数 |
| `src/pipeline/pack/resolve_export.py:125` | 読む | パックの `proofed`・`cut` |
| `src/pipeline/transcribe/fill.py:159・273` | 読む | 後処理(fill)は `proofed` の行を避ける |
| `src/manage/cases/txindex.py` 系 | 読む | 一覧の `proofed`・`cut`・`summary` |
| `src/eval/tools/eval_asr.py`・`eval_alt.py`・`eval_speakers.py` | 読む | 精度の正解(`proofed` の行)と `proofedAt` |

### リスク

1. **行 id の不安定さ**: `_rows_to_doc` は `s1..` を振り直す。文書の作り直し(`run_job`)で id が変わると、上書きを id で結びつけられない。F-3 の時刻の重なりでの対応づけが必要。
2. **時刻のずれ**: 行の `start`・`end` は画面で直せる(小数 2 桁に丸める)。辞書の後処理(`fill.py`)が時刻を変えると、重なりの判定が閾値に依存する(`FILL_AGREE_SLACK` `fill.py:273`)。閾値の値は未確認。
3. **分割・結合で id が増える・消える**: `sid` の `x` 付けと新しい id。上書きの「人が直した行」の数え方が合わない恐れ。
4. **`proofed` の二重の意味**: 画面の「校正済み」と「機械が書き換えたので確認し直し」が同じ項目。`_apply_retranscribe` は pop する(`rerun.py:108`)ので、上書きに移すなら pop の意味を変える必要がある。
5. **`original` と `asr.json` の二重**: 上書きを持つと、どれを ① の正とするかが 3 つに増える(`asr.json`・`original`・上書き)。
6. **カットの従属**: `cutState` は行から導くので、上書きに移すと `edit.json` との同期が増える(`apply_edit_cuts` を通す)。
7. **評価用(`evalSet`)**: 評価用の文書は再認識できない(`redo_spec`・`doc_jobs.py:547`)。上書きを移すときも `evalSet` の扱いを守る。
8. **書き込みの同時性**: 保存は `store._save_lock`(`rerun.py:89`・`relink.py:154`)。新しい上書きの書き込みも同じロックに入れる必要がある。
9. **履歴**: `hist_snapshot`(`store.py:295`)は文書全体の版。上書きを別ファイルにすると「以前の版に戻す」の範囲が変わる。

## 注意

- 行の作り方・`records.py` の書き手・`relink` の細部(`norm_swap`・`plan_range`)は推測を含む。実装の前に該当の行を読み直すこと。
- コードは変えていない。git の操作もしていない。
