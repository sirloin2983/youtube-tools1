状態(2026-10-10 夜): RS6 の段の並び 第 2 版(層を 5 つに・案件ごとのフォルダ B-0 を反映。Fable)

# RS6 の段の並び 第 2 版

前提 = `plan/decisions.md` 3-29(層 ①道具 `pipeline/` / ②管理 新 `flow/` / ③人 `human/` / ④データ `manage/` / ⑤検証 `eval/`・③ → ① は直に呼ばず全部 ② を通す・採用は F-5・鍵が違えば認識は印/パックは作り直し・置き場所は案件ごと(RS6 は B-0 だけ)・CLI は ② + ①・友人 1 人 RTX 3060 の PC がメイン)。第 1 版 `plan_order.md`・`layer5_review.md`・`option_b.md` の上に書く。コードは変えていない。HEAD f47bf4c。「推測」は読んで確かめていない所。

## 1. RS6 の範囲(第 1 版からの差)と、2 つに分ける案

| | 第 1 版(10-10 夕) | 第 2 版 |
| --- | --- | --- |
| 層 | 4 層 + app のまま | **5 層 + app**。`flow/`(②)を新設し、段取り(run・spec・batch・runlog・live_* の段取り・ジョブの待機列・ワーカーの起動・認識の記録 records)を移す。番号は ①〜⑤ に付け替え |
| ③ → ① | 直呼びのまま | **全部 ② 経由**(約 30 行・名前で約 120)。④ も ② 経由(残り 3 行)。⑤ は ① を直に読んでよい(2 節) |
| 字幕 | — | ① に `clipjob`(機械の文書を作る部分)を切り出す。文書は同じ `transcripts/<id>.json` で項目ごとに持ち主 |
| 採用 | A1 F-5・A2 動画ファイルにも解析 → 採用・A3 candidates | **A1 だけ**(A2・A3 は外す = Q2 の答え「今のまま」) |
| CLI | A'(serve 3 本を中で起こす) | **② + ① で動く CLI**。第 1 版は動画ファイル(丸ごと / `hints.ranges`)。URL は動いている ② に頼む(`.flow.lock`) |
| 置き場所 | 無し | **B-0**: ② の結果の束 → `<案件>\作業用\runs\<実行id>.json`・鍵は切り抜きの横・置き場所の持ち主 `flow/placement.py`・`.flow.lock` |
| 鍵 | ① の持ち主の隣で ① が書く | **② の段が計算して横に書く**(① は鍵を知らない = layer5_review 2 節)。材料の records は ② に移るので層の向きの工夫が要らない |
| Q6(live・autorun・server.py) | 最小 | 同じく最小: Live・AutoRunner・launch は app に残し、**中の段取り(live_archive・live_export・live_tx・live_failures・live_report・runlog)だけ `flow/` へ**。玄関の分割と server.py は RS7 |

RS7 以降へ回す物(第 1 版 2 節のまま + 追加): B-1(case.json・案件の走査)= RS7 / B-2・B-3(文書と data.json を案件へ)= UI 再考と一緒 / URL 入力を ② 単体で(候補を ② が持つ = B-3 のあと)/ 段を全部関数で呼ぶ(analyze・export・adopt の Local 実装)= RS7 で測ってから / O2 / L3 / live・autorun の玄関の分割と `app/server.py` / 友人へ渡す α(install.bat・モデル取得)/ CUDA の確認(友人の PC)。

**RS6 は 2 つに分ける(推奨)**: **RS6a 層の組み替え**(flow/ を作って移す・語彙を ytt へ・clipjob・③ → ② の付け替え・④ の 3 行・wire。**動きは変えない**)→ 入口を起動し直して本物の 1 本 → **RS6b 新機能**(束・鍵・採用・上書き・CLI・B-0)。理由: 移動と新機能を同じ RS で混ぜると落ちた原因が分からない(計画 10 節と同じ決まり)/ a の終わりで「違反 0・別名 0」を固定してから b に入ると、b のサブエージェントが層の違反で止まらない / 見積もりが a 1 日 + b 1.5 日で、1 つの RS としては RS3+RS4 より大きい。

## 2. 「③ は全部 ② を通す」の実装の形

### 2-1 今の 30 行の中身(使っている名前で分類。grep で数えた)
| 種類 | 例 | 行き先 |
| --- | --- | --- |
| (a) 語彙 = 定数・ロガー・純粋な文字の関数・例外・URL の形(約 40 名) | `txbase.log/MAX_TEXT/LANGS/SPK_FLAGS/add_warning/char_class/alt_fold`・`postproc.strip_punct/text_chars`・`replace.parse_replacements/wb_split`・`sources.VID_RE/watch_url/YT_API_BASE/MEDIA_EXT`・`resolve_export.ResolveExportError`・`live_detect._ids_ok`・`roster.ROSTER`(パス) | **ytt へ下ろす**(`ytt/txbase.py`(丸ごと 59 行。ロガー名 "tx" のまま)・`ytt/yturl.py`・`ytt/errors`・`ytt/schemas`・辞書の読み方 `ytt/dictfmt.py`)。再公開しない = ③④⑤ が直に読む |
| (b) 段取り = もう ② の物(約 15 名) | `run_mod.Runner/StepError/MODE_STEPS`(delivery)・`records.*`(write_asr・write_words・read_words・recognition_run・dict_version・engine_version)・`live_failures/live_export/live_archive`(cases・live_cleanup) | ② に移るので import 先を `flow.` に変えるだけ |
| (c) 動く物 = ワーカー・ffmpeg・SLOTS・ファイル書き(約 50 名) | `recognize.transcribe_rows/extract_audio/transcribe_real/RangeRecognizer/whole_lines`・`worker_client.load_model/check_engine/read_wav_f/valid_model/req_engine/has_faster_whisper`・`diarize.diarize_real/embed_groups/ensure_diar_models/match_voices_explain/…`(speakers 25 名)・`fill.*`・`llm.*`・`postproc.make_flags/row_words/split_segment`・`analyze.validate_source/prune_cache`・`_src.check_live`・`resolve_export.edit_draft/edit_preview/build_*` | **② の動詞**(下)経由。③ の中に残っている「① の半身」(speakers の判別の計算の glue・rerun の RangeRecognizer 使い・alt の transcribe_real)は ② へ移す |

### 2-2 ② が出す口(動詞 = 別名ではない。それぞれ「① を呼ぶ + ② の責任(SLOTS・ワーカーの起動と後始末・一時 wav・記録・鍵・置き場所)」を足す)
| 口 | 中身 | 使う ③④ |
| --- | --- | --- |
| **ジョブ(重い)** `flow/jobs.py` | `ytt/jobs` の待機列・register・add_job・worker・cancel を移す(`HeavySlots`/`SLOTS` は ytt に残す = 資源の原始)。③ は自分の種類(diarize・retranscribe・alt…)を `flow.jobs.register` で登録してよい(③ → ② の向き) | serve(wire 経由)・doc_jobs・rerun・speakers・alt・ytcap |
| `flow/tx.py` `transcribe_clip(job, spec, wav) → {segs, original, words, raw, fields(recognition…), fill_rec, llm_rec, llm_items}` | 一時 wav の取り出し → ① `clipjob.make_doc_rows` → `records` を書く(asr・words・llm.json)→ 認識と後処理の鍵(RS6b-K1 でここに足す)。文書の機械の分(`original`・`recognition`・`params`)はここが組む(今の `_doc_fields`) | doc_jobs.run_job(③ は fields に `speakers`・`clip`・`evalSet` を足して書く) |
| `flow/tx.py` `recognize_range(job, spec, wav, a, b)`・`recognize_whole(...)`・`extract_audio(job, spec, wav)`・`alt_rows(job, spec, wav)`・`engine_ready(spec) → (engine, version)`(check_engine + has_faster_whisper + valid_model + req_engine を 1 つに) | ワーカーの model の読み込みと手放し・SLOTS はもうジョブが持つので、ここは ① の RangeRecognizer/transcribe_real を回して行を返すだけ + 記録 | rerun(受付と反映は ③ に残す)・alt・ytcap は不要(txbase だけ) |
| `flow/diar.py` `diarize(job, spec, wav, hints) → diar の記録`・`embed(job, spec, wav, groups)`・`match_voices(groups, voices) → 説明つき`・`models_ready()` | ① `diarize.*` の計算と `ensure_diar_models`・声の登録簿の読み(置き場所は ②)。speakers.py の判別ジョブの計算の glue(`_record_diar`・`_assign`・`_label_of`・`_unit` など私有名を 8 つ読んでいる = 半身が ③ に残っている印)をここへ | speakers(反映・字幕の見た目・空の行・自動の判別の判断は ③ に残す) |
| `flow/ingest.py` `probe(url_or_path) → {kind, live?, id, title}`・`prune_cache()` | ① `sources.check_live`・`analyze.validate_source/prune_cache` | review/store・rank |
| `flow/pack.py` `cut_draft(doc, opts)`・`cut_preview(...)`・`handoff_files(doc, …)`・`plan(media)` | ① `resolve_export.edit_draft/edit_preview/build_*`(たたき台は無音の検出 = ffmpeg)。`tool_slot` もここ | proof/store・handoff_io・doclist・relink |
| `flow/wire.py` `install(backend=…, dict_inputs=…, head_stripper=…, hooks=…, fakes_module=…)` | 今の serve.py 161-196(register 9 本・configure・set_selector・set_dict_inputs・set_head_stripper・set_hooks・set_context_namer)。app は `wire.install(...)` を 1 回呼ぶだけ。CLI は同じ wire を「③ なし」で呼ぶ(hooks は既定の何もしない値) | editor/serve・CLI |

別名の山にしない工夫(機械で守る): (1) 語彙は ytt へ下ろす = ② に「定数を返す関数」を作らない / (2) `dev/tests/test_layering.py` に **`test_flow_is_not_alias`**: `src/flow/*.py` の関数で、本体が `return <pipeline のモジュール>.<名前>(同じ引数)` の 1 行だけの物は落とす(AST。`# flow: alias ok` で例外。目安 0 件)/ (3) 動詞は上の表の **約 12 本**に抑える(増やすときは表に足す = Z で文書)/ (4) ② の動詞の docstring に「① を呼ぶ前後で ② が足すこと」を 1 行書く(lint の docstring の検査に乗る)。

### 2-3 層の表(`dev/layer_map.py`)と検査
- `LAYERS = ["ytt", "pipeline", "flow", "human", "manage", "eval", "app"]`。順位の比較をやめ **`ALLOWED` の表**にする: `pipeline → {ytt}` / `flow → {ytt, pipeline}` / `human → {ytt, flow}`(**pipeline 不可**)/ `manage → {ytt, flow, human}`(pipeline 不可)/ `eval → {ytt, pipeline, flow, human, manage}` / `app → 全部`。`test_layer_order` の期待値を表に合わせる
- 移す途中は RS0 と同じ: a-0 で今の ③ → ① 30 行 + ④ → ① 14 行を `KNOWN` に入れ(`KNOWN_MAX = 44`)、段ごとに減らして a-Z で 0
- ④⑤ の答え(推奨): **④ は ② を通す**(移したあと残るのは `resolve_export` 3 行だけ = `flow/pack` の動詞で済む。規則が「①を直に読むのは ⑤ だけ」の 1 つになる)/ **⑤ は ① を直に読んでよい**。理由: `eval/fake` は ① の差し込み口(`backend.select`・`worker_client.FAKES_MODULE`)に差す物で ② を挟むと口が 2 重になる / 測る道具(`eval_*`・drill・metrics)は ① の段を評価用の材料で純粋に回す = 精度の輪 (A) そのもの。② を通すと SLOTS・置き場所・鍵が測定に混ざる。決まりは 1 行: **「⑤ が本物の作業データへ書くときだけ ②(jobs・placement)を通す」**(evalbatch・drill の作り直しは今も doc_jobs の hook = ② のジョブ経由なので満たす)

### 2-4 clipjob と文書の持ち主
`pipeline/transcribe/clipjob.py` `make_doc_rows(job, spec, wav, pairs, lrules, lfb) → {rows, raw, total, t_rec, segs, original, words, dictApplied, learnApplied, sparseLp, fill_rec, fill_read, llm_rec, llm_items, names_n}` = 今の `run_job` 345〜356 行(`transcribe_rows → fill_strip_names → fill_after_rows → _rows_to_doc → fill_agree_doc → llm_after_doc`)。`_rows_to_doc` が呼ぶ ③ `learn.auto_learned_replace`(規則は引数で受け取る純粋な文字の関数)は ① `replace.py` へ移す(学習の規則を**作る**のは ③ のまま)。`_doc_fields`(records を使う)は ② `flow/tx` へ。
同じ `transcripts/<id>.json` の中の持ち主(仮): ①/② = `original`・`recognition`・`params`・`model`・`language`・`start/end/whole/duration`・横の `.asr.json`・`.words.json`・`.llm.json`・`.diar.json` / ③ = `segments[]` の `text`(置換後)・`proofed/proofedAt`・`speaker`・`flag`・`tags`・`noSub`・`cutState`・`speakers`・`title`・`clip`・`evalSet`・`.edit.json`・`.over.json`(RS6b)。機械の分を書く最小の `write_machine_doc(tid, fields)` は ②(CLI が ③ なしで文書を作るため。`ytt/fsio` の原子的書き込み)。③ `store.write_doc` は人の分を足して書く。

## 3. 段の並び
| 段 | 中身 | 触るファイル | テスト | 並列の組 | モデル | 見積(AI) |
| --- | --- | --- | --- | --- | --- | --- |
| **a-0 層の表** | `layer_map` に flow・`ALLOWED` 表・`src/flow/__init__.py`・`test_flow_is_not_alias`・今の ③④ → ① 44 件を KNOWN に(減らすだけ)。`test_layer_order` 直し | layer_map・test_layering・src/flow | 層の検査 | 直列(最初。1h) | Opus・high | 2h |
| **a-1 語彙を ytt へ** | `txbase` → `ytt/txbase.py`(git mv。ロガー名 "tx" のまま。`_ED_MODULES` と test_names の位置)・`sources` の URL の形 → `ytt/yturl.py`・`ResolveExportError` → `ytt/errors`・`_ids_ok` → `ytt/schemas`・`replace` の読み方(parse・wb_split・_bounded)→ `ytt/dictfmt.py`(当て方 apply は ① に残す)。読み手 約 25 ファイルの import 行 | ytt/*・pipeline/transcribe/{txbase,replace}・ingest/sources・human 11・manage 4・eval 4・editor/serve・テスト | unittest(編集・層・ytt)・lint・層 | 波 a1(a-2 と並列。import 行の衝突はまとめ役) | Sonnet・medium | 3h |
| **a-2 段取りを flow へ** | git mv: `pipeline/{run,spec,batch,runlog,live_failures,live_report}.py`・`export/live_export.py`・`ingest/live_archive.py`・`transcribe/live_tx.py`・`transcribe/records.py` → `src/flow/`(`live_tx_worker`・`live_align_worker`・`live_excite_worker` は子プロセスの道具 = ① に残す)。`ytt/jobs.py` の 136 行目以降(表・待機列・register・worker・cancel)→ `flow/jobs.py`(`HeavySlots`・`SLOTS`・`tool_slot` は ytt)。読み手(autorun・live・launch・serve 3 本・delivery・cases・live_cleanup・テスト)の付け替え | 上記 + app の import 行 | unittest(home・pipeline・human/friend・manage)・lint・層 | 波 a1 | Sonnet・medium | 4h |
| **a-3 clipjob と flow/tx** | `clipjob.py`(2-4)・`flow/tx.py` の動詞 6 本・`write_machine_doc`・doc_jobs(`run_job` は ② を呼んで ③ の分を足す)・rerun(RangeRecognizer/whole_lines/load_model の使いを `recognize_range/whole` へ)・alt(`alt_rows`)・retime(records → flow)の付け替え。`auto_learned_replace` → ① replace | clipjob(新)・flow/tx(新)・doc_jobs・rerun・alt・retime・learn・human/proof/tests・editor/tests(S.名前) | test_doc_jobs・test_recognize・編集の行の unittest・lint・層 | 波 a2(a-4 と並列。ファイルは重ならない) | Opus・high | 6h |
| **a-4 判別の半身を flow/diar へ** | speakers.py(984 行)から判別ジョブの計算の glue・声を覚える embed・照合を `flow/diar.py` へ。③ に残す = 反映 `apply_diarization`・空の行の下書き・自動の判別の判断・字幕の見た目・声の登録簿の編集の受付。fake の `Backend.diarize/embed` は ① の口のまま | speakers・diarize・flow/diar(新)・test_voices・test_speakers | test_diarize・test_voices・test_speakers・lint・層 | 波 a2 | Opus・high | 5h |
| **a-5 残りと wire** | review/store と rank → `flow/ingest`、proof/store・handoff_io・doclist・relink → `flow/pack`(`tool_slot` も)、`flow/wire.py`(serve 161-196 を移し serve は `wire.install`)、learn の replace を dictfmt に、delivery の `run_mod` → `flow.run`。KNOWN を 0 に | human/review/store・find/rank・proof/store・manage/cases 4・flow/{ingest,pack,wire}(新)・editor/serve・layer_map | test_studio・test_api・test_cases・編集の unittest・lint・層(KNOWN 0) | 波 a3(a-3・a-4 のあと。1 体) | Sonnet・medium | 4h |
| **a-Z** | 全 unittest・`test_resolve_pack_contract`(単独)・`test_mount`(単独)・lint 0・層 0・e2e 近い 2 本(`e2e_ui_mounted`・`e2e_edit_voices`)。AGENTS.md の層の行と layer_map の docstring だけ短く直す(番号の付け替えの本番は b-Z)。**入口を起動し直して本物の 1 本**(校正・判別・まとめて実行) | 文書 2 か所 | 上記 | まとめ役 | Opus(まとめ役) | 2h |
| **b-0 束を段が読む** | 第 1 版 RS6-0 のまま(`flow/spec.py` に 束 → 本文 の純粋関数・`flow/run.py` の 4 か所の `GET /api/settings` → `run.spec`・AutoRunner の `build_spec()`)。**`Tools` の継ぎ目**: `flow/tools.py` に `HttpTools(client)`(今の形)と `LocalTools()`(transcribe = `flow.tx.transcribe_clip`・pack = `pipeline.pack.build_pack` を直に。analyze/adopt/export は RS7)。Runner の段は `self.tools.<段>()` を呼ぶ | flow/run・spec・tools(新)・autorun・test_run・test_spec・test_autorun | unittest 3 本・lint・層 | 波 b1(K1・O1・B0 と並列。run.py は b-0 だけ) | Opus・high | 6h |
| **b-K1 鍵を書く** | `flow/keys.py`: `write(stage, path, inputs)`・`read`・`stale(path, stage, inputs)`。**書くのは ② の段の完了時**(`_step_export` の後 = `作業用/<名前>.export.key.json`、`flow/tx.transcribe_clip` の後 = `<tid>.transcribe.key.json`・`.post.key.json`、`flow/diar` の後 = `.diar.key.json`、`_pack_one` の後 = `<pack>/pack.key.json`)。`live_archive._update_clip`(② に移った)が本番版に入れ替えたとき export の鍵を書き直す(F-1。書けなければ消す)。材料は束(b-0)+ records の版 + `media_identity` | flow/keys(新)・flow/run・flow/tx・flow/diar・flow/live_archive・test_* | 新 test_keys・test_run・test_live_archive・`test_resolve_pack_contract` | 波 b1 | Sonnet・medium | 4h |
| **b-O1 上書き O1** | 第 1 版のまま(`human/proof/overrides.py` = `extract/apply/write`・`STALE_FLAG`・`<tid>.over.json`)。呼ぶ所: `store.save_transcript` の最後と、`doc_jobs.run_job` で同じ動画の既存の文書があるとき ② の行に apply(③ の側で重ねる = ② は上書きを見ない)。閾値は評価用 22 本で数えて固定 | overrides(新)・proof/store・doc_jobs・tests | test_doc_jobs・test_metrics | 波 b1 | Opus・high | 6h |
| **b-B0 置き場所** | `flow/placement.py`: `case_root(media) → <outDir>\<題名>\`(動画ファイル入力は動画のフォルダ。推測: 今のパックが隣に出るのと同じ)・`work_dir(media)`・`runs_dir(media)`・`.flow.lock`(pid・ポート。`flow.run` の入口で取る。CLI は lock があれば `/api/…` に頼む)。置き場所の持ち主 3 系統(`studio_env.p`・`workdata.STUDIO_DATA`・`cases.locations`)が placement を呼ぶ(**値は今と同じ**)。② の結果の束(`Run.public()` + 段ごとの鍵のパス)を `作業用\runs\<実行id>.json` に書き、`autorun-runs.jsonl` は索引(1 行にパスを足す) | flow/placement(新)・flow/run(結果の束の書き)・ytt/studio_env・workdata・manage/cases/cases・runlog・test_* | 新 test_placement・test_run・test_runlog・test_cases・e2e_datadir(a-Z の後 1 本) | 波 b1 | Opus・high | 5h |
| **b-A 採用 F-5** | `_step_adopt` を 1 本に: `request_marks` の規則(ranges → 人の採用を数に入れ → 点数順で top まで・rejected と重なりは除く)に統一・`adopt_top` を吸収。進み具合の文に「自動で n 本を足しました」。束の `adopt.mode` は作らない(A2 外し) | flow/run・flow/spec(adopt 節の top/pad)・human/review/store・studio/serve・test_run・test_studio・test_api | unittest・lint・層 | 波 b2(b-0 のあと。run.py は A と K2 の 1 体) | Opus・high | 4h |
| **b-K2 鍵を読む** | `_step_transcribe`: 文書があれば `keys.stale` → 一致 = 飛ばす / 無し = 飛ばす / 違う = 飛ばして印「設定が違う(force で作り直し)」・`run.force` なら新しい文書へ(O1 が引き継ぐ)。`_step_pack`: 違う → 作り直す / 無し = 今のまま。素の Runner の `_docs`・`_pick_doc` の既定を HTTP に。`manage/cases/txindex.key_state(media)`(読むだけ。画面は後) | flow/run・txindex・test_run・test_ytt_core | unittest | 波 b2(A と同じ体) | Opus・high | 3h |
| **b-S1 CLI** | `src/app/cli.py`: `py -3.10 src/app/cli.py <動画 \| URL> --spec spec.json [--from 段] [--force] [--data-dir D] [--out result.json]`。`spec.merge + validate` → `wire.install`(③ なし・hooks 既定)→ `flow.placement` の lock → 動画ファイルは `LocalTools` で transcribe → pack(ワーカーは ② が起こして閉じる)/ URL は動いている ② へ HTTP(`HttpTools`)。lock が無く URL なら「入口を起動してください」。API キーは環境変数だけ。結果 = runs の JSON と同じ物を `--out` にも | app/cli(新)・flow/wire・layer_map・新 test_cli | test_cli・test_mount(単独)・lint・層 | 波 b2(A/K2 と並列。run.py は触らない) | Opus・high | 5h |
| **b-R1 配信後の採用を束に** | 第 1 版のまま(`_per_hour_for`・`Live.adopt` の pad を `spec.DEFAULTS["adopt"]` 経由に) | flow/live_archive・live・prefs・test_live_archive | unittest | 波 b2 | Sonnet・medium | 2h |
| **b-Z まとめ** | 文書 1 回: 番号 ①〜⑤ の付け替え(AGENTS.md・`plan/role-restructure.md` 3〜8 節・`plan/data.js` の RS6a/b・layer_map・`docs/spec/pipeline.md` に `.key.json`・`.over.json`・`runs/` の形・`docs/spec/data-location.md` に placement・HANDOVER・decisions 3-29)。e2e の一式(サブエージェントが止まってから 1 本ずつ)。本物の確認(5 節)。公開ページ | 文書 | e2e 一式・ui_audit static | 直列 | まとめ役 + Sonnet(文書) | 5h |

- 見積: **RS6a 26h・RS6b 40h = AI 約 66h**。並列込みの壁時計は実績(RS3+RS4 = 見積 45〜50h を 1 日)に合わせて **a 1 日・b 1.5 日**。第 1 版の 2 日 + 層 1 日 + B-0 と ③ → ② で 0.5 日
- 共有ファイルの決まり(RS3 と同じ): import 行の衝突はまとめ役が解く・`run.py`(flow)は b-0 → (A+K2 の 1 体)の順で 1 体ずつ・`serve.py`(editor)・`layer_map`・`_ED_MODULES`・data.js はまとめ役が最後に 1 回・取り込みは `git merge --ff-only` → cherry-pick → 後から入る側が rebase。e2e はまとめ役が 1 本ずつ・一式はサブエージェントが止まってから

## 4. ユーザーに確かめること(確)と AI が決めること(仮)
| # | 問い | 選択肢 | 推奨 | 理由 |
| --- | --- | --- | --- | --- |
| 確 1 | ④⑤ も ② を通すか | (i) ④ は ② 経由・⑤ は ① を直に読んでよい(本物の作業データへ書くときだけ ②)/ (ii) ④⑤ とも ② 経由 / (iii) ④⑤ とも直でよい | **(i)** | ④ は残り 3 行で済み規則が 1 つに / ⑤ の fake は ① の口に差す物・測る道具は ① を純粋に回す = 精度の輪 (A)。② を挟むと測定に SLOTS・置き場所・鍵が混ざる |
| 確 2 | RS6 を a(組み替え・動きは同じ)と b(新機能)に分けるか | 分ける / 1 つで | **分ける** | 落ちた原因を分ける・a の終わりに入口を起動し直して 1 本・b の並列が層の違反で止まらない |
| 確 3 | CLI 第 1 版の範囲 | (i) 動画ファイル(丸ごと / ranges)は ② + ① で直に・URL は動いている ② へ頼む(lock)/ (ii) URL も直に(候補を ② が持つ = B-3 を RS6 に前倒し) | **(i)** | 友人の主用途は動画ファイル 1 本 → パック。URL の解析 → 採用は data.json(③ store)が要るので B-3(UI 再考と一緒)の決定を守る |
| 確 4 | Q6: live・autorun の扱い | 最小(中の段取り live_archive・live_export・live_tx・live_failures・live_report を flow へ移すだけ。Live・AutoRunner・launch の分割と server.py は RS7)/ 計画どおり RS6 で全部 | **最小** | 本物の配信が動く玄関を新機能と同じ RS で割らない。移す物はもう葉として分かれているので git mv + import 行だけ |

仮(AI が決めて記録だけ): `txbase` を丸ごと ytt へ(ロガー名 "tx" のまま)/ `records` と `ytt/jobs` の待機列を ② へ(`HeavySlots` は ytt)/ ② の動詞 約 12 本の一覧(2-2)と `test_flow_is_not_alias` の形 / `ALLOWED` 表(2-3)/ `auto_learned_replace` を ① `replace` へ / 文書の中の持ち主の項目(2-4)と `write_machine_doc` は ② / `Tools` の 2 実装(Http・Local。Local は transcribe・pack だけ)/ 鍵は ② の段の完了時に書く・置き場所は第 1 版の仮のまま / `.flow.lock` の形 `{pid, port, at}` と CLI の「頼む」先は `/api/ping` の入口 / 動画ファイル入力の案件の根 = 動画のフォルダ / `Run.spec` は Run の欄を束に重ねた派生 / `.over.json` の形と `STALE_FLAG` は第 1 版のまま / 第 1 版の仮(鍵の置き場所・inputs・file_digest 全体・L3 据え置き)はそのまま。

## 5. リスクと本物の確かめ方
リスク: (a) **a-4 speakers.py の割り直し**がいちばん重い(984 行・私有名 8 つを ③ が読む・test_voices/test_speakers が `S.名前` を差し替える)。割れなければ a-4 だけ「speakers が読む diarize の名前を flow/diar の同名で包む」に落とし `# flow: alias ok` で印を付け、RS7 で割る(KNOWN と同じく減らすだけ)/ (b) `txbase`・`records` の移動で `_ED_MODULES` の位置と test_names が変わる(RS3 と同じ手順。`modfwd.duplicates` 0 件を保つ)/ (c) ② が何でも屋になる → 別名の検査 + 動詞の一覧 + 「② に変換のコードを書かない」を layer_map の docstring と `docs/spec/code-quality.md` に 1 行(機械で守れるのは別名まで = 推測: 変換の混入は review で見る)/ (d) `LocalTools` と `HttpTools` で transcribe の結果の形が違うと K2 の判定がずれる → `test_run` に両方で同じ `Run.public()` が出る検査 / (e) `.flow.lock` の取り残し(入口が落ちたとき)→ pid が生きていなければ上書き / (f) B-0 で `runs/` を案件の `作業用\` に書く = バックアップが `exports` を飛ばす(option_b 4 節)。RS6 では `autorun-runs.jsonl` の索引が残るので失っても戻せる(B-2 の前にバックアップの規則を直す)/ (g) 第 1 版の (a)〜(g)(人の採用済みの配信で自動が増える・鍵の材料・O1 の閾値・MSIX・file_digest・鍵の書き直し失敗・run.py は 1 体)はそのまま / (h) CUDA はこの PC で確かめられない = `transcribe.device` の束の値が鍵に入ることだけ test で固定し、本物は友人の PC で。

本物で確かめる(配信の無い時に「すべて終了 → start.bat」のあと):
1. **a-Z(RS6a の終わり)**: 校正の画面で 1 本開く・話者判別(覚えた声で名前が付く)・まとめて実行(採用後を全部)が今までどおり動く。動きは変えていないので差が出たら a の退行
2. **アーカイブ 1 本(RS6b)**: ホームの「まとめて実行(解析から全部・top 3)」→ `作業用\*.export.key.json`・文書の `.transcribe.key.json`・`.post.key.json`・`.diar.key.json`・`<pack>\pack.key.json`・**`作業用\runs\<実行id>.json`** があり `autorun-runs.jsonl` の行がそれを指す → 「編集」で 1 行直して保存 → `.over.json` → 同じ配信を再実行 → 解析・採用・書き出し・認識は「飛ばした(鍵が一致)」・パックだけ作り直る → 設定でエンジンを変えて再実行 → 認識は印「設定が違う」→ `force` → 新しい文書に直した行が引き継がれ(`proofed` のまま)・対応づかない行は `STALE_FLAG`
3. **動画ファイル 1 本(CLI。ユーザーの外のシェルで。AI が流すときは `--data-dir C:\dev\tmp\…` = MSIX の写しを避ける)**: `py -3.10 src/app/cli.py <mp4> --spec spec.json --data-dir <一時> --out result.json`(spec は `{"transcribe": {"engine": "whisper.cpp", "model": "large-v3"}}` 程度)→ パックまで・result.json に段ごとの成果物と鍵・失敗 0・ワーカーの子プロセスが残らない → 同じ指定でもう一度 → 全段「飛ばした」→ `--from pack` → パックだけ。入口が動いている間に URL を渡す → lock を見て入口へ頼み、ホームの一覧に実行が出る
4. **退行**: e2e の一式(特に `e2e_live*`・`e2e_autorun`・`e2e_intake_ui`・`e2e_pipeline`・`e2e_datadir`)。ライブの経路の玄関は変えないので、本物の配信は次の配信のとき 1 回(録画 → 採用 → 届ける)
5. **CUDA(別の項目。友人の PC)**: 同じ CLI を RTX 3060 で 1 本(`transcribe.device = cuda`)→ 鍵の `device`・`engineVersion` が CPU の結果と別になり両方が案件に残る。data.js には「友人の PC で CLI 1 本(CUDA)を確かめる」として入れる(操作だけの項目ではなく確かめる中身がある)
