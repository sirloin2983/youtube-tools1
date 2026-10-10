# RS6 の下調べ: 切り抜き単位の使い回し(鍵)

状態(2026-10-10): RS6 の下調べ(Haiku)の報告

読むだけの調査。コードは変えていない。行番号は 2026-10-10 時点の作業フォルダ。「推測」は読んで確かめていない所。

## 1. 鍵の関数(src/ytt/schemas.py)

| 項目 | 場所 | 中身 |
| --- | --- | --- |
| 定数 | schemas.py:260-265 | `KEY_SCHEMA = "youtube-tools-key/v1"`、`KEY_VERSION = 1`、`KEY_STAGES = (ingest, analyze, export, transcribe, diar, post, pack)`、`KEY_SUFFIX = ".key.json"`、`MEDIA_KINDS = (recording, archive, file)` |
| 媒体の識別 | schemas.py:286-303 `media_identity(kind, **kw)` | recording = {recorder, recording}、archive = {videoId}、file = {sha256}(64 桁の 16 進に検査)。余分・不足の項目は ValueError |
| 中身のハッシュ | schemas.py:306-315 `file_digest` | 動画ファイル全体の sha256(1MB ずつ読む。巨大な動画は全部読むので時間がかかる = 推測ではなく実装どおり) |
| 正規化 | schemas.py:318-338 `_norm` | float は小数 3 桁に丸め、整数と同じ値なら int。NaN・無限大は ValueError |
| 正規 JSON | schemas.py:341-343 `canon` | sort_keys・空白なし・ensure_ascii=False |
| ハッシュ | schemas.py:346-348 `_key_hash` | sha256(canon({stage, v, inputs}))。madeBy と at は入らない |
| 作る | schemas.py:351-363 `make_key(stage, inputs, made_by=None)` | 戻り値 `{schema, v, stage, inputs(正規化後), hash, madeBy?{name,version}, at}` |
| 検査 | schemas.py:366-391 `validate_key(obj)` | `(複製, None)` か `(None, 理由)`。inputs から hash を計算し直して一致を確かめる |
| 同じか | schemas.py:394-397 `same_key(a, b)` | 両方が正しく、stage と hash が同じなら True(作った日時・人は見ない) |
| 置き場所 | schemas.py:400-404 `key_path(path, stage)` | `sidecar_path(path, "." + stage + ".key.json")`。例: 動画_0012.mp4 + export → 作業用/動画_0012.export.key.json。IO はしない |

- テスト: src/ytt/tests/test_ytt_core.py:665-770 付近(`test_make_key`・`test_validate_key`・`test_key_path` など)。`make_key` と `same_key` を使うのはこのテストだけ(grep で確認)。
- **今は鍵を書くコードも読むコードも無い**。`.key.json` を作る所は 0 件。

## 2. 「済みの段を飛ばす」判定の今の形

判定は鍵ではなく「ファイルや記録が有るか」「記録に済みと書いてあるか」。

| 場所 | 判定 |
| --- | --- |
| src/pipeline/run.py:49-60 | `DONE_STEPS = ("done", "skip", "warn")`。戻した実行(保存された記録)で済みの段を飛ばす。段の state だけで判定(鍵なし) |
| run.py:384-402 `_run_steps` | `st["state"] in DONE_STEPS` なら段を飛ばす |
| run.py:423-425 `_step_analyze` | 解析済みの判定で skip。重みが違えば解析し直す(run.py:416 の比較。記録された重みと比べる) |
| run.py:541-546 `_step_export` | `status == "adopted"` の印だけ書き出す。`exported` は数えるだけ(鍵なし) |
| run.py:570-572 `_clips` | 書き出し済み(`status == exported`)かつ `os.path.isfile(m["path"])` |
| run.py:574-589 `_step_transcribe` | 各切り抜きが `self._pick_doc(...)` で文書に紐づくか(ファイル名・id の一致)。全部紐づけば skip |
| run.py:292-294 `_pick_doc` | 基底は None(文字起こし済みとみなさない)。AutoRunner は home/autorun.py:728-730 で `txindex.pick` を使う |
| run.py:816-826 `_doc_transcribe` | 文書の `count > 0` なら「文字起こし済み」で skip |
| run.py:749-789 `_step_pack` | パック有無で判定(`pack_info` 系・`exists` の 409 応答)。`overwrite` で作り直し |
| src/pipeline/ingest/live_archive.py:5-59 | 録画ごとの `archive.json` の state(マークごとの最新ジョブ・`done`・`error`・`aligned`)。鍵なし |
| src/home/autorun.py:425 付近 | 解析済みの skip 理由文 |

結論: 段の skip は「段の state の記録」か「ファイル・文書・パックの有無」。鍵の一致で判定している所は無い。

## 3. 成果物の今の置き場所と名前

| 成果物 | 置き場所 | 名前の決め方 |
| --- | --- | --- |
| 切り抜きの mp4 | `names.pick_folder(get_out_dir(), title, videoId, videoId)`(src/ytt/names.py:75)で `<書き出し先>/<題名>/` を決める。同じ題名で持ち主(owner = videoId)が違えば `_2` … | 書き出しは exporter.py:953 `_names.clip_base(outDir, idx, start, end, label, unique=unique_base)`。番号・開始終了・ラベル入り。作業中は `<base>.partial.mp4`(exporter.py:44, 472) → 仕上がりで `promote`(exporter.py:107) |
| yt-dlp の区間の取り出し | `作業用/<base>_dl.partial.mp4`(exporter.py:458, 546) | 切り出したら消す |
| `.clip.json`(切り抜きの素性 youtube-tools-clip/v1) | 作業用/`<base>.clip.json`(manifest.py:11-12 `manifest_path`) | mp4 と同じ名前の基底。`write_clip_manifest`(manifest.py:21)で書く。鍵はまだ入っていない |
| 切り抜きの書き出し「同じ区間を 2 回」 | — | 推測: `clip_base` が `unique` を取るので、2 回目は別の名前の mp4 ができ、`.clip.json` も別になる(連番の部分は読んで確かめていない)。鍵の一致で止める仕組みは無いので、同じ区間の二重の書き出しは今のまま起きる |
| アーカイブからの本番版 | `作業用/本番版の作りかけ/<ジョブ>/`(live_archive.py:118)、完成は `free_name(folder, name)`(live_archive.py:282)で別名 | 速報版(録画)と本番版(アーカイブ)は同じ owner なので同じフォルダに並ぶ |
| 文字起こし文書 | `TX_DIR/<tid>.json`(human/proof/store.py:29 `tx_path`)。tid は `uuid.uuid4().hex[:12]`(store.py:906) | **ランダム**。切り抜きとの紐づけは id ではなく下の txindex の規則 |
| 編集(カット・字幕の直し) | `TX_DIR/<tid>.edit.json`(store.py:447) | — |
| 履歴・バックアップ | `<tid>.pre-<kind>.json`(store.py:49)、版の履歴 `<ts>.json`(store.py:307) | — |
| 認識の生の結果 | `asr_path(tid)`(pipeline/transcribe/records.py:147、write_asr :164、read_asr :170) | tid の名前 |
| 単語の時刻 | `words_path(tid)`(records.py:180) | tid の名前 |
| 話者判別の記録 | `TX_DIR/<tid>.diar.json`(pipeline/transcribe/diarize.py:294 `diar_path`) | tid の名前。`rows[行id]` に smoothed |
| パック | `pack_dir(media_path)`(manage/cases/txindex.py:151)。パックの記録は `packs_dir` の `pack_key(dirpath)`(txindex.py:172-174 = dirpath の sha1 の先頭 20 字 + .json) | `<名前>_pack`(txindex の docstring) |

## 4. 紐づけの規則(影響する所)

- src/manage/cases/txindex.py:103-111 `_match(doc, video_id, mark_id, media)`: 文書の `source.videoId` と `mark.id` の一致、かつ `media`(切り抜きのパス)が文書の clip の path と一致(規則は `norm`、txindex.py:41)。
- txindex.py:118-123 `pick`: 一致した文書のうち最新。`(文書, 件数, id の一覧)` を返す。
- txindex.py:126-143 `offset`: 切り抜きの中の時刻 → 配信の時刻のずれ。`.clip.json` → 同じ名前の sidecar → マーク の順。
- txindex.py:208-220 `pack_info(media_path, env)`: パックの記録(`read_pack_record`)か古い cut-plan.json で判定。`textplus` を持つ。
- src/manage/cases/txlink.py:19-31 `for_video`: パックが無くても `pick` で文字起こしを紐づける(書き出し済みのマークだけ)。
- src/manage/cases/relink.py: 文書の path の付け替え(`relink_doc` :131、`_relink_write` :166)と音声の正規化 `norm_*`(:204-342)。**切り抜きの path が変わると `_match` が外れる**ので、鍵が path を持つなら relink と鍵の更新を揃える必要がある。
- src/manage/cases/doclist.py:21 `pack_info` は txindex と別の定義の重複(推測: 同じ規則の写し)。

鍵を入れると影響する所: `_match` と `pick`(鍵の hash で紐づけを増やすなら規則の変更)・`pack_info`(パックの鍵の一覧)・relink(path 変更)・doclist の重複。

## 5. 段ごとの鍵の材料と今の場所(計画 5-2)

| 段 | 計画の鍵の材料 | 今どこにあるか |
| --- | --- | --- |
| ingest(録画の取り込み・アーカイブ) | 媒体の識別(recording・archive・file) | 録画の id・recorder: rec_core / live_archive の job。アーカイブ: videoId(live_archive の probe)。ファイル: `file_digest` は**まだ誰も呼んでいない** |
| analyze | 重み・感度・学習データの版(長さの目安) | 重み: run.py:416-425 の記録(`weights`)。学習データの版: **無い**(推測: 新しく作る必要あり) |
| export | 切り抜きの範囲・精度(fast/precise)・高さ上限・音量・媒体の識別 | exporter.py:164 `_parse_opts`、:191 `_max_height`、:461 `_enc`、manifest に export の欄。媒体の識別は `.clip.json` の source.live.* の一部 |
| transcribe(認識) | エンジン・エンジンの版・モデル・言語・VAD・beam・boost | records.py:60-68 `_run_base`(engine、engineVersion、model、language、settings.beam/vadMode/boost/wordSplit)、records.py:51-57 `_engine_ids`、engine_version は records.py:46-48(パッケージは dist-info の版、whisper.cpp などは `eng.version(home)` = 決めた版の定数)。VAD: records.py:135 `vad_record`。device: records.py:73 |
| transcribe(後処理) | 後処理の設定・辞書の版・名簿の版 | records.py:103-125 `dict_version`(glossary・replacements・learned・roster の短いハッシュ)。辞書の中身は serve が `set_dict_inputs`(records.py:24)で登録(編集の ed_jobs.dict_pairs・dict_learned)。名簿の版は `roster_hash`(records.py:95-100、ファイルの更新日時と大きさのキャッシュ) |
| diar(話者判別) | 認識の鍵 + 出る人 + 声の版 | diarize.py:52 閾値・min_on・min_off(sherpa の設定)、:39-48 モデルの sha256(モデルの版)。声の版(voices)は diarize の `update_diar_voices` 付近(推測: 声の登録簿の版は diar.json に残るが鍵の材料としては未整備) |
| pack | 入っている切り抜きの鍵の一覧・字幕の版・カット・パックの設定 | run.py:684-745 `_pack_one`(pack_opts・カットの方法・packRev の記録)、cut-plan(旧)、txindex.pack_info。字幕の版(文書の rev / updatedAt)は run.py:745 の `rev`・`docUpdatedAt` |

## 6. RS6 で鍵を書く・読む所の候補と気づいたリスク

### 書く所(候補)
- exporter: `manifest.write_clip_manifest`(manifest.py:21)の隣に `key_path(mp4, "export")` を書く。または `.clip.json` の中に `key` を入れる(今の形を変える)。
- analyze: run.py の `_step_analyze`(423)で `analyze` の鍵。
- 認識: `records.recognition_run`(records.py:71)の周り(`write_asr` :164 の隣)に `transcribe` の鍵。
- 後処理: `postproc.post_record()` の周り(推測: 場所は postproc.py)。
- diar: `write_diar`(diarize.py の判別の記録)の隣に `diar` の鍵。
- pack: `_pack_one`(run.py:684)の後、`pack` の記録(`read_pack_record` の書き込み側 = packs_dir)に鍵の一覧。

### 読む所(候補)
- run.py `_step_export`(541)・`_step_transcribe`(574)・`_doc_transcribe`(816)・`_step_pack`(749)の skip 判定。
- home/autorun.py `_pick_doc`(728)の紐づけに鍵の一致を足すか。
- manage/cases/txindex.py `pick` / `pack_info`(鍵で状態を出す = ③ の案件)。

### リスク
1. **F-1(速報版と本番版の混同)**: 切り抜きの名前は owner = videoId で同じフォルダに並ぶ(names.py:75)。鍵に媒体の識別を入れないと、録画からの速報版とアーカイブからの本番版が同じ鍵になり、本番版が飛ばされる。媒体の識別は `make_key` の inputs に `media` として入れる(schemas.py:717 のテストの例がある)。
2. **F-2(上書きの引き継ぎ)**: 校正の上書きを切り抜きの鍵に付けるなら、速報版から本番版への入れ替えで鍵が変わる。③ の案件が付け替えると決めた通りに実装する必要がある。
3. **辞書の版の材料が serve 経由**: records.py の `set_dict_inputs` は編集の serve が登録する。① (pipeline)が同じ材料を読むと層の違反になるので、鍵を作る側は値を引数で受けるのが安全。
4. **名簿の版がファイルの更新時刻**: roster_hash(records.py:95-100)は mtime と大きさのキャッシュ。鍵の材料にするなら内容のハッシュに替える必要がある(同じ内容で時刻だけ変わると鍵が変わる)。
5. **エンジンの版が固定の定数**: whisper.cpp など `eng.version(home)` は決めた版の定数。バイナリを差し替えても版が変わらないと鍵が変わらない(推測: 版の決め方に注意)。
6. **file の媒体の識別**: `file_digest` は動画全体を読む。大きな動画で時間がかかる。RS7 の速度の測定に入れる。
7. **鍵の数値の丸め**: `_norm` は 3 桁に丸める。区間の秒は ms 単位で揃えるのが安全(sec_ms・schemas.py:268)。
8. **LLM の後処理・llama の版**: dict_version に入っていない(推測: 入れるなら後処理の鍵に別途)。
9. **鍵の無い既存の成果物**: 今ある切り抜き・文書には鍵が無い。RS6 の初回は「鍵が無い = 作り直す」か「ファイルがあれば使う(移行)」を決める必要がある(計画の決め事を確認)。
10. **パックの鍵の一覧**: パックが切り抜きの鍵を持つなら、`pack_info` の判定を鍵の一覧に合わせる。relink で path が変わると txindex の一致が外れる(上の 4)。
