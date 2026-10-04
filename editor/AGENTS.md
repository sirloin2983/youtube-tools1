# editor(「編集」= 文字起こし・カット・パック。2026-09-30 まで transcribe-tool)— AI 向けメモ(Claude・GPT 共通)

現在 **v0.49.1**(2026-10-04 夜、評価ドリルの帯に「話者を付ける…」`#drSpk`(app.js が「…」の中の「話者」= `#jumpMenu [data-jump=spDetails]` を押す)と話者の無い行の数 `#drSpkHint`(`app-learn.js` の `renderDrillSpk`。`renderDrillBar` と `renderSpAll` から呼ぶ)。ユーザーの指摘「ドリルに話者認識が見当たらない」= カードが「…」の中で見つけにくかった。v0.49.0 は(2026-10-04、2つ目のエンジンとの食い違いに候補を出す(精度改善の計画 第2版 D1-b): `ed_alt.py`・`POST api/alt`・`transcripts/<id>.alt.json`・提案の tier `alt`(札「別」)・設定 `altEngine`・`autoAlt`(下の「2つ目のエンジンの候補」)。v0.48.0 は(2026-10-04 夜、評価ドリルを動画 1 本単位・いつもの校正の画面に作り直した: `?doc=&drill=1` の帯・`api/drill/next|reviewed|unreviewed|status`・文書の印 `evalReviewed`・定点は確かめ済みの動画の長さで数える・drill.html は消した。v0.47.0 は(2026-10-04、評価用の動画のまとめての文字起こし `ed_evalbatch.py`(⚙ のボタン・少しずつ・`api/eval-batch`)・評価ドリル `drill.html`・`drill.js`・`ed_drill.py`(`api/drill/*`)と定点の「あと何分」・「全行をこの人に」(下の Q4 の2つの節)。v0.46.0 は(2026-10-04、記録の土台(マスタープラン Q2): 行の proofedAt・再認識の前の機械の結果を recognition.runs に・辞書の版・edit.json の draft・校正の手間 effort(`POST /api/effort`)・話者判別の `<id>.diar.json`(下の「記録の土台」と話者の所)。v0.45.0 は(2026-10-04、素材を 30fps にそろえる: 文字起こしのあと隣に `<名前>_30fps.mp4` を作って付け替え・選び直しは裏で・簡易版は lite-media に写し・3 パック は素材がちょうど 30fps なら 30 固定(下の「素材を 30fps にそろえる」)。v0.44.0 は(2026-10-04、評価用のフォルダの設定が空なのに「評価用」の名前のフォルダの動画を文字起こし・付け替えしようとしたら止める `ed_relink.eval_name_guard`(`eval_dir_unset`)・評価用の音声の flac を作業データの `eval-audio/` に作る `ed_evalaudio.py`(裏のスレッド・SLOTS・`GET api/eval-audio`・`TRANSCRIBE_EVAL_AUDIO=off`)・認識のワーカーのアイドル終了 60 分と「通常より下」の優先度(`docs/plan/stability-review-2026-10.md`)。v0.43.0 は(2026-10-04、評価用にした文書の動画を外から評価用のフォルダへ取り込む: `ed_relink._eval_intake_pass`・`_eval_intake_one`(そろっていればメンバーのフォルダの「_NN_済」・それ以外は仮置き)・別のドライブは `_move`(コピー → 大きさ → 元を消す。消せなければコピーを消して元のまま)。いつ = `eval_settle`(裏のスレッド・応答 `intake: true`)・`eval_organize`(結果の `intaken`)。テストは test_edit の TestEvalFolder。`../docs/design/eval-folder.md` の「外からの取り込み」。キー配置は ? の一覧だけ・ヘッダーの明暗のボタンをやめた(ui-kit v14))。v0.42.0 は(2026-10-04、3 パック の「前回のパック」に「友人へ届ける」`#pkDeliver`: `pack-tab.js` が入口の `api/ytt/deliver`(home/deliver.py)を呼び、パックを zip にして依頼の受付の Dropbox の 出力 に置く。確認は `UIKit.dialog.confirm`・状態は `#pkDeliverMsg`。入口から開いたときだけ。テストは `e2e_edit_pack.py`)。v0.41.0 は(2026-10-04、履歴の項目を非表示に: `app-list.js` の `txFiltered`・`txRowHTML`・`renderList` が ui-kit の `UIKit.hide`(一覧の名前 `'transcripts'`。入口から開いたときだけ `available()`)を使う。「⋮」の `data-act=hide/unhide`(app.js の `#txList` のクリック)・`#txHiddenToggle`(非表示 n件を表示)・今開いている文書は隠しても除かない。覚える場所はホームの設定。テストは `e2e_ui_mounted.py`)。v0.40.1 は(2026-10-03、2 カット の保存の表示の直し: `cut.js` の `save` は `M.saving` を入れたあとで `renderSaveState` を呼ぶ。それまでは PUT を送っている間も「カットを保存しました」と出ていた。入れ直した PC で PUT が少し遅くなり `e2e_edit_cut.py` が落ちて分かった)。v0.40.0 は(2026-10-02、1 文字起こし の行の開始・終了を ui-kit の時刻の欄 `UIKit.timebox`(分:秒.0.1秒 = `data-ui-time-short`)に: `app-rows.js` の `segHTML`(`<span class="t" data-f data-ui-time>`)・`renderDoc` で `UIKit.timebox.attachAll`・確定は `#segs` の `ui-time-commit`(`app.js`。並びが変わらなければ描き直さず `markOvl` だけ)・`isTextEntry` は `.ui-time` を入力欄と同じ扱いに。テストは欄の文字を `text_content()` で読み、直すのは本物のキー入力(`e2e_row_editing.py` の `type_time`)。v0.39.0 は簡易版の書き出しで映像トラックの数 1〜5 を選ぶ: 画面 `#ltTracks`・設定 `videoTracks`(`ed_lite.load_settings`/`save_settings`・書き出しの要求でも渡して覚える)→ `pack.build_pack(video_tracks=)`。字幕は V(数+1)。v0.38.0 は精度改善の計画 段2-3: Qwen3-ASR のエンジン `tx_engines.Qwen3Asr`(0.6B・sherpa-onnx・CPU)と `LlamaQwen3`(1.7B・llama.cpp の llama-server・Vulkan)。精度を測る道具からだけ使う(画面には出さない)・測る道具に「時刻によらない CER」`doc_text`。下の「Qwen3-ASR」)。v0.37.0 は AMD などの GPU(whisper.cpp)を画面から選べる: 処理方式の `optDevice` に `vulkan`(`/api/tools` の `wcpp.ready` のときだけ app.js が足す)→ サーバーの `req_engine` が whisper.cpp にする・機器の表示は `devLabel`)。v0.36.1 は評価用の仮置きのコピー: 文書の無い仮置きの動画は、同じ名前・同じ大きさの動画を指す文書が1つだけならそれを付け替えてから移す(`ed_relink._eval_adopt_copy`・`_eval_copy_index`。`../docs/design/eval-folder.md`)。v0.36.0 は 精度改善の計画 段2-2: whisper.cpp(Vulkan)のエンジン `tx_engines.WhisperCpp`。下の「認識エンジンの口と全体の再認識の続きから」)。v0.35.0 は段2 の 2回目: 認識エンジンの口 `tx_engines.py` と、全体の再認識の区間ごとの保存・続きから(下の「認識エンジンの口と全体の再認識の続きから」))。v0.34.0 は友人用 文字起こし簡易版: 画面 `lite.html`・`lite.js`(一本道。`docs/plan/friend-lite-plan.md`)・サーバーの部品 `ed_lite.py`(`/api/lite/…`。状態・ドロップの受け取り・開始(doc["lite"] と既定の話者 = `on_new_doc`)・作業の記録 `<id>.lite-edits.jsonl`・書き出し = cut2resolve の pack(字幕の型 lite・カットなし・記号を除いた字幕)と送る用 zip(形式と規則は `ytt_core/evaldata.py`))・生出力 `<id>.asr.json`(`capture_raw`・`write_asr`・`read_asr`。単語の確信度は `seg_to_dict` の `wordProbs` = 3つ組は変えない)・`TRANSCRIBE_CUDA_COMPUTE`(`cuda_compute`)・話者の `outline`。v0.33.1 は 版の帯に「起動し直す」= `UIKit.restart.check($('#errBar'), …)`(段9 9-3。入口の api/ytt/restart-self)。v0.33.0 は評価用の仮置き: 評価用のフォルダの直下の `EVAL_STAGING`(評価用_仮置き)は名前を変えず(`_eval_videos(skip_staging)`)、`_eval_ready`(全行が校正済み・全行に話者)を満たせば、話した秒が最も長く名前がメンバーのフォルダ(`_eval_members`。「…数字_名前」)と同じ人のフォルダへ `_eval_next_name`(「_NN_済」)で `_eval_rename(…, "evalSettle")`。整理の最初の段 `_eval_staging_pass` と、画面がほかの文書へ移ったときの `POST /api/eval-folders/settle`(`eval_settle`・app.js の `evalSettle`)。v0.32.0 は評価用のフォルダ: 設定 `evalDirs`(`SETTINGS_PATCH_KEYS`。⚙ の `#evDirs`)の中の動画は `in_eval_dir` で評価用 = `validate_job`・`sanitize_transcript`・`restore_history`・`_relink_write` が evalSet を付け、`GET /api/transcript` の `evalLocked` で画面のチェックを固定。`POST /api/eval-folders/organize`(`eval_organize`。起動時は `prepare` の5秒後に1回)が「動画のフォルダ名_番号_済|未|未文字起こし」にそろえて途中のファイルの名前も変え、`_relink_write` で付け替える(失敗したら名前を戻す)。`../docs/design/eval-folder.md`。v0.31.0 は動画の再リンクを簡単に: 「動画を選び直す」の「参照…」= `POST /api/pick`(`ytt_core/pick.py` が別プロセスの tkinter で PC の窓を開く・一度に1つ)・履歴の上の「まとめて付け替える」`#relinkAllDlg`(`POST /api/relink/missing`・`/api/relink/find` = 選んだフォルダの中の同じファイル名。付け替えは1件ずつ既存の `/api/relink`)。v0.30.0 は段6「編集の機能を足す」: 3 パック の詳しい設定「行の後の余白」(設定 `rowEdge.padAfter`。`cut.js` の `redraftPristine`)・字幕の段の行の選択とドラッグ(`M.sel.kind === 'row'`・`applyRowEdge`。外へ広げたら `addRange` で区間も。文書とカットの元に戻すに同じ番号 = `pushUndo(seq)`/`undoDocIf`)・「再生位置でこの行を分ける」(`splitRowAt` を 1 文字起こし の分割と共用)・文書の競合の案内 `#cutDocConflict`。v0.29.0 は段5「見せ方をそろえる」: `?list=` で履歴を種類で開く・⚙ の select の幅・一覧の上の道具の折り返し。v0.28.0 は依頼の「話す人」(話者判別の 1人・names)。v0.27.0 は段4「パックの表示と出力を一致」: 設定を変えたら見積もりを出し直す(状態 P.pv)・粗編集の動画つきを覚える・出力先は覚えない・作ったときの出力の設定の記録 `pack.output` と今の設定との違い(`outputNow`/`outputDiff`)・zip に渡らない設定の説明(`ZIP_SKIPS`)・見本の話者の色は見積もりの `sampleSpeakers`。`../docs/plan/phase4-pack-consistency.md`)。v0.26.1 はパックの音量の既定(30%)。v0.26.0 は段3「操作の一貫性」(メニューがキーを持つ間は文書のキーを止める・派生キー・キーの表示を配置から・1コマを素材の fps で・元に戻すで新しい方を戻す。`../docs/plan/phase3-keys-undo.md`)。v0.25.0 は段2(動画を選び直す・カットの読み込み失敗の区別・URL の ?doc=・設定の保存の失敗と差のキーだけの保存)。v0.24.0 は段1(声を覚えるの安全・引き出しと Alt+数字・Shift+右クリックの行のメニュー)。v0.22.0 は精度改善の計画 段1(名簿の呼び名・配信ごとの文脈・評価用として文字起こし)と S-3(幻覚の印。下の「名簿の呼び名と配信ごとの文脈」)。
v0.21.0 = 2026-09-28、動画全体の再認識と声の検出が捨てすぎる対策(下の「再認識(範囲・全体)と声の検出のやり直し」。`../docs/design/whole-retranscribe-design.md`)・映像の上の字幕に話者の色。
それより前の版の中身は `README.txt` の「■ v0.xx の変更」と `../docs/WORKLOG.md`(0.16.0 = 「編集」の統合・0.11.0 = 認識のワーカー分離・0.12.0 = Resolve パックの一本化 など)。
画面の共通のルール(用語集・ヘッダー・ボタンと札・一覧・段階的に見せる・狭い画面)は `../docs/spec/ui-guidelines.md`。画面を直すときは必ず合わせる。いま何が途中かは `../docs/WORKLOG.md` の最後の数件で確かめる。
現行の仕様は、このファイルとユーザー向けの `README.txt`。v0.9.8 までの経緯・決定の理由は `../docs/archive/project/HANDOVER-transcribe-tool.md`、版ごとの記録は `../docs/archive/project/history/transcribe-tool-v*.md`、
最初の仕様は `../docs/archive/project/transcribe-tool-spec.md`(v0.7.0 当時。**どれも古い**ので、今の動きの根拠にはしない。理由を調べるときに読む)。
使い方の説明はユーザー向けの `README.txt`(変更したら README も直す)。
**精度改善のこれからの計画は `../docs/plan/transcription-plan-v2.md`**(第2版。2026-10-04。D0・D1・E1〜E4・FT。段ごとにユーザーの承認のあとで実装)。済んだ段の記録と測った結果は `../docs/plan/transcription-overhaul-plan.md`(第1版。段0〜5。段ごとにユーザーの承認のあとで実装。どこまで済んだかは `../docs/ROADMAP.md` の 線 B で確かめる。2026-10-03 時点で、段0・段1・段2 の 2-1〜2-3 は済み、次の 2-4 比較と決定は評価用の校正待ち)。
GPT の `TRANSCRIPTION_V2_DESIGN.md`(09-23)と `../docs/archive/project/accuracy-plan.md`(09-24)はこの計画にまとめた旧計画(原則は引き継いだ・食い違う所は新しい方が正。経緯として読む)。
全体の状態(進行中・待ち・保留)は `../docs/ROADMAP.md`。

## 精度の測定の土台(計画の段0。v0.20.1)
- 機械の出力 `original` の各行に `avg_logprob`・`no_speech_prob`・`compression_ratio`(分かるものだけ。`machine_conf`・`CONF_KEYS`)。
  文字起こしのジョブ(`run_job`)と、範囲の再認識・疑わしい所の認識し直し(`finish_range_lines` の `conf` → `replace_original_multi`)が書く。
  選んだ行の再認識(`replace_original`)はまだ書かない。画面の保存(`sanitize_transcript`)は `original` を保存済みのものから引き継ぐので消えない
- 文書の `recognition = {"runs": [{engine, engineVersion, model, device, language, settings, audioSec, wallSec, at}]}`(`recognition_run`。文字起こしのジョブだけ)。
  版は `pkg_version`(dist-info を読むだけ。サーバー側で faster_whisper を import しない)
- 単語ごとの確率はまだ残していない(単語は `(開始, 終了, 文字)` の3つ組で多くの所が分解しているため。要るときに words.json の形ごと考える)
- モデルは手元のファイルだけで先に読む(`tx_engines.FasterWhisper.create` の `local_files_only=True`。無ければネットワーク)
- 測る道具 `../dev/eval_asr.py`(`stored` = 保存してある出力 / `run` = 認識し直す / `compare` / `list`)。作業データは読むだけ、結果は作業データの `evals/asr/`。
  採点は serve.py の `_groups`・`norm_cer`・`lev_counts` を使い、`doc_metrics`(画面の測定)と同じ数になることを `stored` のたびに照らし合わせる(ずれたら注意を出す)。
  `run` は文字起こしのジョブと同じ整え方(`expand_segments`・`make_flags`)。元の動画が無ければ保管データの `full.flac`。テスト: リポジトリ直下で `python -m unittest dev/tests/test_eval_asr.py`
  2026-10-04(Q3): `--since/--until`(行の proofedAt の最大 → updatedAt)・`--source eval|daily|all|friend`(普段の文書・友人の zip `eval-intake`)・`--group-by engine|model`・下書きのエンジン(runs の最初の認識の記録)と同じときの注意・評価用以外はヒントなしで認識し直す・15 分未満は「まだ少ない」
  2026-10-04 夜: `--reviewed only|prefer|ignore`(評価用の既定は only。確かめ済みが 0 本なら従来の選び方に戻して注意)。確かめ済み(`drill_is_reviewed` と同条件)の文書は動画全体(0〜durationSec)が正解で、人の行の無い所の機械の文字は余分・機械の無い所の人の行は抜け。結果の `summary.reviewed`(docs・sec・missChars・extraChars・extraOutsideChars)

## 認識エンジンの口と全体の再認識の続きから(計画 段2-1・S-1。v0.35.0)
- `tx_engines.py`: 認識エンジンの形(`create(name, device, compute_type, log)` → エンジン・`transcribe(audio, **kw)` = faster-whisper の WhisperModel.transcribe と同じ (行, 情報)・`params()`)と一覧 `ENGINES`(今は `FasterWhisper` だけ。引数と結果をそのまま通す)。
  **新しいエンジン(whisper.cpp・Qwen3-ASR)はここにクラスを足して `ENGINES` に登録する**。行・情報は faster-whisper と同じ属性で返す(サーバー側の整え方は変えない)。
  このファイルはサーバー側も名前と版のために読むので、**ネイティブの部品は `create` の中で読む**(`test_worker.EngineTest` が検査)
- 選び方: `load_model(name, job, pref, force_cpu, engine)` → ワーカーの要求 `load`/`transcribe` の `engine`(既定のときは送らない = 以前と同じやり取り)。ワーカーは一覧に無い名前を `bad_engine` で断る。
  モデルの使い回しのキーは `(名前, 機器, エンジン)`。記録 `recognition.runs[].engine`・`engineVersion` はエンジンの `id`・`package` から(spec の `engine`。まだ画面からは選べない)
- 全体の再認識(`mode: whole`)は `whole_lines`: 長さが `WHOLE_PART_SEC`(600 秒)の 1.5 倍を超えたら `whole_parts` で区間に分け(区切りは目安の前後 `WHOLE_SPLIT_WINDOW` 秒の中で、行の無いいちばん長いすき間の真ん中。無ければ目安の所)、
  区間ごとに `RangeRecognizer.main(p0, p1, share)`(行は区間の内側に切る)。終わった区間の行を `transcripts/.resume/<id>.whole.json` に書き(`write_resume`。目印 `whole_key` = 文書・範囲・行を作る設定・ヒントの語・エンジンとモデル・元の動画の大きさと更新日時)、
  同じ目印でもう一度始めたら書いてある区間は認識しない(`job["resumed"]` と知らせ)。反映したら・文字が出なかったら消す(`drop_resume`)。使われなかった記録は 7 日で消す。
  短い動画は1区間 = 以前と同じ結果・記録を書かない。区間の境目で声の検出のやり直しは区間ごと(知らせはやり直した区間の1つ)
- **whisper.cpp(段2-2。v0.36.0)** `tx_engines.WhisperCpp`: 作業データの `bin/whisper.cpp-v1.9.4-vulkan/whisper-cli.exe`(`setup/build-whisper-vulkan.bat` が公式のソースを決まったコミット `WHISPER_CPP` で作る。`build.json` のコミットが違えば `ready()` が断る)を子プロセスで。
  **引数は応答ファイル `@args.txt`(UTF-8)**(コマンド行は Windows の文字コードで読まれて日本語のヒントが化ける)・パスは ASCII でなければ 8.3 の名前(`_ascii_path`)。結果は `-ojf` の JSON → `parse_json`(単語 = 文字のトークン)。
  **2026-10-03 の Windows の入れ直しで、作業データの中の実行ファイルとモデル(`bin/whisper.cpp-v1.9.4-vulkan/`・`models/whispercpp/`)は消えた**。`setup\build-whisper-vulkan.bat` で作り直すまで GPU は選べない(Visual Studio 2022 の C++ と Vulkan SDK が先に要る。今の PC には無い)。
  機器は auto/cuda → `vulkan` だけ(**黙って CPU にしない**。`_check_gpu` が認識のモデルの `using … backend` を見る。声の検出のモデルの「no GPU found」は無視)・cpu → `-ng`。
  環境変数 `GGML_VK_DISABLE_COOPMAT=1` を既定で付ける(`wcpp_env`。RX 7800 XT + AMD のドライバでは行列コアの経路で何も出さずに 0xC0000409 で落ちた)。
  **whisper.cpp の声の検出は既定で使わない**(`native_vad()`。声の所をつないで認識するため文字が大きく抜けた。測るときだけ `TRANSCRIBE_WCPP_VAD=1`)。
  Silero の区間の外の行を捨てる案(`speech_spans`・`drop_outside_speech`)も悪化したので既定オフ(`TRANSCRIBE_WCPP_SPEECH_FILTER=1`)。既定の vad_filter は whisper.cpp では何もしない。
  **whisper.cpp を温度 0(`--temp0` = `-nf`)で測らない**(同じ文字の繰り返しで大きく悪く出る)。
  画面(v0.37.0): 処理方式「GPU(AMD など・whisper.cpp)」= 要求の `device: "vulkan"` → `req_engine` が whisper.cpp(spec の device は auto)。whisper.cpp で使えないモデルは `bad_model` で使えるモデルを案内。`/api/tools` の `wcpp`(`engines_info`)
  モデルは `WCPP_MODELS`(large-v3・large-v3-turbo)と `WCPP_VAD` を `fetch_file`(https・大きさ・SHA-256。合わなければ消す)で `models/whispercpp/`。
  サーバー: 要求の `engine`(`req_engine`)・`check_engine`・`engine_home()`(精度を測る道具は `TRANSCRIBE_ENGINE_DIR` で本物の作業データ)。テストは `tests/test_whispercpp.py`(偽の whisper-cli `tests/fake_whisper_cli.py`)と test_worker の `test_whispercpp_through_worker`(worker-fake のワーカーは偽の whisper-cli)
- **Qwen3-ASR(段2-3。v0.38.0)**: 共通の元 `_Qwen3Chunked`(時刻を出さないモデルなので、音の大きさ(0.05 秒ごとの RMS)で `q3_chunks` = 12〜28 秒の区切りの、ならした音のいちばん小さい所で切る →
  区切りごとに `_decode` → `q3_rows`(。？！で分け・長い文は「、」でも・時刻は区切りの中の声のあるコマ(`q3_floor` より大きい)に字数で割り振る目安)。無音の区切り(`Q3_SILENT`)は送らない。
  言語は区切りごとに指定する(`Q3_LANG`。自動の判定では日本語の区切りが中国語になり繰り返しが止まらなかった)・出力の上限は区切りの秒 × `Q3_TOKENS_PER_SEC`・繰り返しは `q3_squash` で 4 回まで・`<|` から先は捨てる。
  `Qwen3Asr`(engine `qwen3-asr`・モデル `qwen3-asr-0.6b`): 入っている sherpa-onnx 1.13.8 の `from_qwen3_asr`。モデルは sherpa-onnx の公式の tar.bz2(`QWEN3_MODELS`。`_safe_extract` は top の下の普通のファイルだけ)。
  用語のヒントは認識器を作るときに渡す(区切りごとの `set_option("hotwords")` は `<|endoftext|>` のあとに関係ない英文が続いた)。
  `LlamaQwen3`(engine `llama.cpp`・モデル `qwen3-asr-1.7b`): 公式の win-vulkan-x64 の zip(`LLAMA_CPP`。`_safe_unzip`)と ggml-org の GGUF(`LLAMA_MODELS`)。llama-server を 127.0.0.1 のあいているポートで1つ起動し、
  **毎回作る合言葉 `--api-key`**(llama.cpp は CORS をすべて許すので、付けないと同じ PC のブラウザのページから呼べる)・`-t 8`(24 だと当時の 13900KF で起動中によく落ちた。環境変数 `TRANSCRIBE_LLAMA_THREADS` で変えられる。10-04)・`-lv 4`(GPU に載ったかの行 `offloaded n/m layers to GPU` を `_check_gpu` が見る。黙って CPU にしない)・
  ワーカーが落ちても server が残らないよう Windows のジョブオブジェクト(`_kill_on_close_job`。閉じたら中を終わらせる)・答えは `/v1/chat/completions` に音声(wav の base64)と assistant の先書き「language Japanese<asr_text>」→ `q3_parse`。
  server が落ちていたら起動し直して区切りを1回だけやり直す(`_decode` → `_ask` の `server_down`)。テスト: `tests/test_qwen3.py`(偽の server `tests/fake_llama_server.py`)
  **この PC(当時の 13900KF。10-04 に 12900KF に替えた)ではネイティブの部品の読み込み・起動がまれに落ちた**(sherpa-onnx の読み込み・llama-server の起動・Python 自体)ので、読み込み・起動は1回だけやり直す(10-04 の見直しでも残した: 一時的な失敗への備え・本物の失敗は2回目でそのまま出る。`docs/plan/stability-review-2026-10.md`)。測った結果は計画の「4回目の結果」

## 名簿の呼び名と配信ごとの文脈(計画 段1・S-3。v0.22.0)
- 名簿 `hololive-roster.json`: `groups`(画面の「名簿から追加」。`/api/roster` の形は変えていない)+ `members`(channel = YouTube のチャンネルの ID(2026-10-04。公式サイトから。使うのは `dev/eval_fetch.py` だけで、`roster.py` は読まない)・aliases = 呼び名・common = 普通の言葉と重なる呼び名・
  misrecognitions = 誤りやすい形。**学習用の文書の修正に出るものだけ**入れる。評価用にしか出ない誤りは入れない)。読むのは `roster.py`(`load` は更新日時でキャッシュ)
- 配信ごとの文脈 `stream_context(doc, enabled)`: チャンネル名(スタジオの data.json の videos。`_studio_load` = 履歴の一覧と同じキャッシュ)→ コラボ相手(data.json の groups。`studio_stream`)→
  話者の名前(`roster.match_name`。ちょうど同じときだけ)→ 題名・動画のファイル名・**動画の入ったフォルダの名前**(`roster.find_in_text`。正式な名前か、common でない 3 文字以上の呼び名)。
  6 人まで・1人 = 名前 + 呼び名 3 つ。**題名の文字列そのものはヒントに渡さない**。使った人は `params.context`・`recognition.runs[].settings.context`
- ヒントの語は `prompt_terms(spec)` の1か所(用語集 → 文脈。`roster.fit` で先頭 150 字・語の途中で切らない)。`whisper_kwargs`・`make_flags`(英字の除外・漏れ出し)が使う。
  設定 `autoContext`(既定オフ)。**評価用の文書・評価用として始めた文字起こし(`evalSet: true`)には用語集・文脈・置換辞書・学習した置換を渡さない**
- S-3 の印(`make_flags`): `stock_phrase`(以前からの HALLUC は文の一部でも・`HALLUC_LINE` は行のほとんどがその文のときだけ・♪/(音楽) だけの行)・`repeats_in_line`(2〜10 文字が 5 回以上。1 文字の繰り返しは除く)・
  近くの行の同じ文(前の5行に2回)・`LEAK_FLAG`(3 秒以内でヒントの語だけ、または「用語:」を含む)。声の検出のやり直し(`transcribe_vad_fallback`)は決まり文句・ヒントの語だけの結果を「文字 0」とみなし、
  緩い条件の認識は `LEAK_FLAG` の行も入れない。`REDO_BAD_FLAGS` にも入れた
- テスト: `test_roster.py`(test_metrics から読む)。測る道具 `../dev/eval_asr.py run --context none|auto --temp0`

## 素材を 30fps にそろえる(マスタープラン Q1。2026-10-04。v0.45.0)
- 部品は `ed_relink.py` の「素材を 30fps にそろえる」の節(作り直しは `ytt_core/normalize.py`。別名 `_vnorm` = **`_norm` は ed_learn の関数と重なるので使わない**。serve が部品の名前をまとめて見せるため)。
  判定は `normalize.needs_normalize(probe())`(H.264・8bit・yuv420p・30/1 の CFR・AAC 以外は作り直す)。音声だけの拡張子・映像の無いもの・`TRANSCRIBE_NORMALIZE=off` は何もしない
- **文字起こし**: `ed_jobs.run_job` が文書・単語・生出力を書いたあと `ed_relink.norm_after_transcribe(job, spec, tid)` → `norm_plan`(置き先 = 隣の `<名前>_30fps.mp4`。
  あって使える(30fps・長さが同じ)なら reuse、使えないなら上書きせず `_30fps_2.mp4`…)→ `norm_run`(`_norm_room` = 書けるか・空き(元の大きさ + 1GB)→ normalize → `norm_swap`)。
  ジョブは work_one で SLOTS を持っているので取り直さない。作り直しの間 `job["tid"]` を入れる(`_doc_busy` で選び直しを止める)。進み具合は state running・phase `NORM_PHASE`・progress 0〜1
  (画面は phase + n% を出すので変えていない)。結果は `job["normNote"]`・`normOk`(`public_job`)、付け替えなかったときは warnings にも。失敗・中止でも文書は元の動画のまま・ジョブは done
- **付け替え** `norm_swap`: `_save_lock` の中で文書の sourcePath がまだ元のときだけ `_relink_write(..., why="normalize30", bump=False)`(**updatedAt を変えない** = 開いている画面の次の保存を 409 にしない。
  保存は sourcePath を画面から受け取らないので消えない)。relinks の記録・控え・履歴は普通の付け替えと同じ
- **選び直し** `relink_doc`: 付け替えはすぐ済ませ、`norm_start` が裏のジョブ kind `normalize`(`run_normalize`)を足す(応答 `normalizing` = ジョブの id・`normNote` = 作れない理由)。
  `"normalize": false` なら作らない = 「まとめて付け替える」(app.js の raGo。以前の文書の動画はそのまま)。画面は app-jobs.js の `pollJobs` が `normDone` を知らせ、開いている文書なら `openDoc(id, true)`
- **評価用は作り直さない**(spec / 文書の evalSet・`in_eval_dir`)
- **簡易版**(spec / 文書の `lite`): 置き先は `ed_lite.norm_dst` = `lite-media/<新しい番号>/<元の名前>.mp4`(ドロップの写しの番号は外す。Resolve 用ファイル・zip の sourceName が元の名前のまま)。
  ドロップで受け取った写し(`ed_lite.in_media_dir` = lite-media の直下)は、付け替えたあとほかの文書が使っていなければ消す(`_drop_upload`)。30fps の「ファイルを選ぶ」は今までどおり写さずに使う。
  lite.js は `isNormPhase(j)` のとき「30fps にそろえています… n%」・残りの見積もりを数え直す・中止の確認の文を変える(結果は残る)
- テスト: `tests/test_normalize30.py`(test_metrics から読む)・`e2e_lite.py`・`e2e_edit_tabs.py` の最後(別のサーバー `Server(normalize=True)`)。
  **e2e の `Server` は既定で `TRANSCRIBE_NORMALIZE=off`**(テストの webm(VP9)を作り直した H.264 は Playwright の chromium で再生できないため)。`e2e_ui_mounted.py` も off(24fps のままパックの保険の道を確かめる)
- 未対応: `ed_store.find_doc_for_media`(?media= で文書を探す)・`ytt_core/txindex` は sourcePath だけを見るので、作り直した文書は元の動画のパスでは見つからない

## 評価用のフォルダの設定が消えたときの安全と、評価用の音声(マスタープラン Q0。2026-10-04)
- **安全の止め**: `ed_relink.eval_name_guard(path, is_eval, todo)`。設定 `evalDirs` が空・壊れているのに、動画のパスのフォルダ名のどこかに「評価用」が入っていたら `ApiError("eval_dir_unset", 400)` で止めて案内する
  (学習用に混ざらないように)。呼ぶのは `ed_jobs.validate_job`(`evalSet: true` で始める・`intoDoc` の文書が評価用のときは通す)と `ed_relink.relink_check`(`relink_doc` も通る。評価用の文書は通す)。
  `evalDirs` が設定されていれば何もしない(今までどおり)。パスの文字を調べるだけでファイルには触らない。テストは test_edit の `TestEvalFolder.test_unset_eval_dirs_stops_eval_named_folder`
- **評価用の音声** `ed_evalaudio.py`(動画が E:\ にしか無いため、評価用のフォルダ(`ed_relink.eval_dirs()`)の下の動画 = `_eval_videos(skip_staging=False)` から 16kHz・モノラルの flac を作業データの `eval-audio/` に作る。バックアップに入る):
  `index.json`(`items[sha1 の先頭 12 文字] = {src, size, mtime, flac, flacSize, durationSec, madeAt}`・`gone`(元が消えた。flac は消さない)・失敗は `error`/`fails`(同じ元で `MAX_FAILS` 回まで)・`scan`・`lastRun`・`lastError`)と
  `<sha1 12 文字>_<元の stem>.flac`。元のパスの sha1・大きさ・更新時刻(1 秒差まで)が同じなら作り直さない。評価用の整理で動画の名前が変わったものは、大きさと更新時刻が同じなら flac を引き継ぐ(`_reconcile` の adopted)。
  評価用のフォルダが見えない間(ドライブを外した・未設定)は何もしない = `gone` にもしない・`eval-audio/` も作らない。
  ffmpeg は `ed_state.find_ffmpeg()`・`-vn -ac 1 -ar 16000 -c:a flac -f flac <名前>.part` → 改名・Windows は `BELOW_NORMAL_PRIORITY_CLASS | CREATE_NO_WINDOW`。1本ごとに `SLOTS`(ラベル「評価用の音声」)を通し、
  ジョブが動いている・待っている間と評価用の整理の間は始めない(`_busy_reason`。途中でやめたら 10 分後にもう一度)。ほかのプロセス(単独実行と入口)とは `eval-audio/.lock`(`_file_lock`)で重ならない。
  裏のスレッド `start_background`(`serve.prepare` から1回。起動の 5 分後と 6 時間ごと。環境変数 `TRANSCRIBE_EVAL_AUDIO=off` で始めない)・状態の API `GET /api/eval-audio`(`status`。ファイルは探さず索引を読むだけ。画面は無い)・
  単独実行 `py -3.10 editor/ed_evalaudio.py`(serve.py を読み込んで作業データの場所を入口と同じに決める)。テストは `tests/test_evalaudio.py`(test_metrics から読む)

## 評価用の動画のまとめての文字起こし(マスタープラン Q4(b)。2026-10-04。v0.47.0)
- `ed_evalbatch.py`(`../docs/plan/q3-q4-design.md` の (b))。評価用のフォルダ(`ed_relink.eval_dirs()`)の「評価用_仮置き」と、名前が `…_NN_未文字起こし` の動画(`eb_scan`)のうち、
  文字のある文書が無い・待っている/動いていない・済でない・あきらめていない(失敗 `EB_MAX_FAILS`=2・入れた回数 `EB_MAX_TRIES`=3)ものを `eb_candidates` で決め、
  **自分のジョブ(`spec["evalBatch"]` の印)が待ち・処理中 `EB_MAX_WAIT`(2)件になるまで**だけ `validate_job` → `add_job` する(`eb_tick`)。要求は `eb_request` = 編集の設定(`settings.json`)そのまま + `evalSet: True` + 動画全体。ヒントなしは `validate_job` の評価用の規則(`ev`)で保証(テストで固定)
- 文字の無い文書(文字起こしせずに開いた動画)だけがあるときは `intoDoc` でその文書へ入れる。ユーザーのジョブ(印の無い待ち・処理中)がある間・`ed_relink._evalorg_lock` の間・評価用のフォルダが見えない間は増やさない(見えないのは終わりにも止めにもしない)。
  残りが 0 で自分のジョブも無ければ `enabled` を外して `finishedAt`(止めるまで続く = 残りがある間)。取り消された(ユーザー)ものは入れ直さない
- 状態は作業データの `eval-batch.json`(`enabled`・`startedAt`・`enqueued`・`remaining`・`deferred`・`lastError`・`items[パス] = {tries, fails, done, error}`)。起動し直しても `enabled` なら続く(ジョブの表は空に戻るので、文書の無い動画を入れ直す)。
  別のプロセスとは `eval-batch.lock`(`ed_evalaudio._file_lock`)で重ならない。裏のスレッド `eb_start_background`(30 秒ごと・`TRANSCRIBE_EVAL_BATCH=off` で始めない)・`eval_batch_start` が起こすとすぐ見回る
- API の関数は `eval_batch_start`・`eval_batch_stop`(待っている自分のジョブだけ取り消す。動いている 1 本は最後まで)・`eval_batch_status`(`POST api/eval-batch/start|stop`・`GET api/eval-batch`)。
  **名前は serve.py が部品から集める = ほかの部品と重ならない名前(`eb_`・`EB_`・`eval_batch_`)にする**。画面は ⚙ の「評価用のフォルダ」の下(`index.html` の `#evbRow`・`app-tools.js` の `evbInit` ほか。15 秒ごとに状態を読む・404 なら出さない)。
  評価用の音声(`ed_evalaudio`)はジョブが動いている間は始めないので、まとめての文字起こしが続く間は flac が後回しになる。テストは `tests/test_evalbatch.py`(test_metrics から読む。偽のワーカー = 待機列のジョブをテストが疑似の認識で動かす)

## 評価ドリルと定点の「あと何分」・全行をこの人に(マスタープラン Q4(c)。2026-10-04。v0.47.0・**10-04 夜に動画 1 本単位・編集の画面に作り直し(v0.48.0)**)
- 仕様は `../docs/plan/q3-q4-design.md` の (c)。サーバーは `ed_drill.py`(名前は `drill_`・`DRILL_` で始める = serve.py の `_ED_MODULES` の最後。中だけの名前も `_drill_…`)、
  画面は**編集の index.html そのもの**(別のページ drill.html・drill.js・`GET ui-kit.css` と行ごとの API `api/drill/pick`・`api/drill/row` は作り直しで消した)。
  作り直しの理由(ユーザーの指摘): 行を 1 行ずつ直すと、隣の行との結合・話していない所の行(幻覚)の削除・抜けの書き足しができず、行と行のすき間を誰も聞かないので定点が甘く出る
- **文書の印 `evalReviewed = {"at", "rows"(文字のある行の数), "durationSec"(動画の長さ = `ed_store.doc_length`), "via"?: "drill" | "editor"}`** = 動画を全部聞いて(すき間も)直した。判定は `ed_drill.drill_is_reviewed(doc)`(evalSet と印)
  - 付けるのは `POST api/drill/reviewed {id, baseUpdatedAt, via?}`(`drill_reviewed`)だけ: 保存のロックの中で読み、`baseUpdatedAt` が違えば 409 `conflict`・無ければ 400・評価用でなければ 400 `not_eval`・
    文字起こしせずに開いた文書(model なし・行なし)は 400 `not_transcribed`・ジョブの最中は 409 `busy`。**文字のある行のうち校正済みでない行を校正済みに**(`sanitize_transcript` を通すので proofedAt = 今 = `at`)・
    `effort_rows`・`apply_edit_cuts`・`hist_snapshot`・updatedAt は必ず前より大きく。行が 0 の文書(本当に無音)も付けられる。付いていれば付け直す
  - 外すのは `POST api/drill/unreviewed {id, baseUpdatedAt}`(`drill_unreviewed`): 印と、**印が校正済みにした行(proofedAt が `at` と同じ)の校正済み**を戻す(前から校正済みの行はそのまま)
  - 画面の保存(`sanitize_transcript`)は base から引き継ぐだけ(画面が送った値は使わない = 付けも消しもできない)。**評価用を外すと消える**(外している間は一括置換・再認識で機械が書き換えられるため)。
    行の文字・時刻・話者を人が後から直しても残す。**機械が行を書いたら外す**: `ed_jobs.record_rerun`(再認識 each・range・whole と疑わしい所の認識し直し redo が差し替える前に必ず通る)・
    `ed_store.fill_doc`(行の無い文書への文字起こし)。以前の版に戻す(`restore_history`)は、その版の印のまま。PUT /api/transcript の応答に `evalReviewed`(画面が評価用を外したときに表示を合わせる)
  - **測る道具(dev/eval_asr.py など)が「確かめ済みだけ」を選ぶときは `drill_is_reviewed(doc)` と同じ条件**(evalSet が True かつ evalReviewed が dict)。確かめ済みの文書は、
    行の範囲だけでなく**動画全体(0〜durationSec)**が正解(すき間 = 何も話していない、が正解)。行の無い確かめ済みの文書も「無音が正解」として使える
- `GET api/drill/next?skip=<id,…>`(`drill_next`): 評価用・文字のある行がある・確かめ済みでない・今回のドリルで飛ばしていない(skip。12 桁の id だけ・`DRILL_MAX_SKIP` 件まで)・
  直近 `DRILL_RECENT_SEC`(10 分)に更新していない(`updatedAt` と `effort.lastAt` の新しい方)・ジョブの最中でない・動画がある(ネットワーク上は調べずに除く)文書から、**動画の単位で乱数で 1 本**。
  無ければ `{"id": null, "reason", "counts"}`(理由 = 確かめ済み・文字起こし前・飛ばした・直近に直した・処理中・動画が無い の本数)。文書の要約は更新日時と大きさ(と名簿の版)で覚える(`drill_docs`)
- `GET api/drill/status`(`drill_status`): 定点 = **確かめ済みの評価用の動画の長さ**(`durationSec`。無ければ文書の長さ)の合計 → `DRILL_GOAL_SEC`(900)の残り。`docs`・`reviewedDocs`・`pendingDocs`(文字起こし済み・まだ)・`untranscribed`。
  条件 `DRILL_CONDS` は**確かめ済みの文書の中で**数える(行は「校正済み・聞き取れない印なし」): 話者(一般的な名前でない名前の種類 4)・配信(`drill_stream_key` = 配信の ID → メンバーのフォルダ → 動画のフォルダ。3)・
  声の重なり / BGM(印の秒 30)・呼び名(名簿 `roster.find_in_text` に当たる行 10)
- `GET api/drill/candidates?id=`(`drill_candidates`): 候補 = この文書の話者判別の記録(diar.json)の覚えた声 → 動画の入ったメンバーのフォルダ(評価用のフォルダの中だけ)→ 配信の文脈(`ed_jobs.stream_context`)を `near: true`、
  そのあとにほかの覚えた声(使った秒の長い順)・ほかのメンバーのフォルダ(中に別のメンバーのフォルダがある「1_JP」「01_0期生」の段は除く)。一般的な名前は除く・16 件まで。`suggest` = 最初の near
- 画面(`app-learn.js` の `drill*`・`markReviewed`・`renderEvalReview`。状態は app.js の `DR = {on, done, skip, none, status, busy}`。済ませた本数・飛ばした文書はタブの sessionStorage `tx.drill`):
  - URL `?drill=1`(`?doc=` と並べる。`app-tools.js` の `takeUrlParams`。文書が無ければ `drillStart(false)` で次の 1 本)で 1 文字起こし のタブの上に帯 `#drillBar`:
    この動画の状態・定点まであと n 分・済ませた本数・条件・「済みにして次へ」`#drDone`・「飛ばして次へ」`#drSkip`・「ドリルを終える」`#drEnd`(URL の drill を消す)。次が無ければ `#drNone` に理由
  - 「済みにして次へ」(`drillDone`)= `markReviewed('drill')`(話者の無い行があれば `UIKit.dialog.confirm` → **`saveDoc()` で保存し終えてから** api/drill/reviewed。409 は保存の 409 と同じ `#conflictBar`)→
    `drillNext()`(api/drill/next → 既存の `openDoc` で切り替え。画面は読み直さない)。次が無ければ今の文書を `openDoc(id, true)` で読み直す
  - キー(⚙ のキー配置・? の一覧のまとまり「評価ドリル」): `drillDone` = Shift+D・`drillSkip` = Shift+N(`TX_ACTIONS`。帯が出ていないときは知らせるだけ。押し間違いで「全部聞いた」にならないよう Shift つき)。下の帯(keybar)にもドリルの間だけ
  - ドリルの外: 評価用の文書を開くと、映像の上(評価用の帯の下)に `#evrBox`(確かめ済み/まだ・「全部聞いて直したので済みにする」`#evrMark` = `evalReviewHere`・「取り消す」`#evrUndo` = `unmarkReviewed`。確認つき)。ドリルの間は帯に出すので隠す
  - 進行度のカード(`#goalCard`)の `#drillStat`(`loadDrillStat`・`renderDrillStat`。`loadProgress` が一緒に呼ぶ)と「評価ドリルを始める →」`#drillGo`(`drillStart`)。
    評価用の目標は定点の 15 分に一本化した(`#evalStat` の「目安 20 分・全行を校正」はやめ、本数と校正済みの行だけ)
  - 話者のカードの `#spAllBox`(`app-jobs.js` の `renderSpAll`・`fillSpAll`・`spAllGo`。状態は app.js の `SPALL`。`renderSpeakers` の最後で呼ぶ): 評価用で話者の無い行があるときだけ出し、
    確認(`UIKit.dialog.confirm`)のあと既存の `POST api/diarize {numSpeakers: 1, names: [名前]}`(= `single_speaker`。diar.json も書く)。仮の名前(話者1)は断る
- 移したあとの流れ: ドリルで次の文書へ切り替えると、前の文書は既存の `evalSettle`(全行に話者 + 全行校正済みなら仮置きからメンバーのフォルダへ)に乗る
- テストは `tests/test_drill.py`(test_metrics から読む)と `tests/e2e_drill.py`(入口に取り込んだ形。進行度のカードから始める → 1 行直してすぐ済み → 次の文書・定点の残り → 飛ばす(キー)→
  直してすぐ Shift+D → 再読み込みで続く → 話者の無い行の確認 → 次が無い → 終える・ドリルの外の確かめ済みと取り消し・全行をこの人に・? の一覧)

## 記録の土台: 文字起こし・カット・校正の手間(マスタープラン Q2。2026-10-04。v0.46.0)
機械の最初の結果を書き換えず、人の最終と並べて残す。どれも任意の項目を足すだけ(以前の文書・以前の画面で読める)・書き込みは `_save_lock` の中・**記録のために文書の updatedAt を動かさない**。テストは `tests/test_records.py`(test_metrics から読む)
- **行の `proofedAt`**(初めて校正済みにした時刻。ミリ秒): `ed_store.sanitize_transcript` が保存済み(base)の同じ id の行から引き継ぐ(画面が送った値は使わない)・
  保存済みで校正済みでなかった行は今の時刻・外した行は捨てる。この項目より前から校正済みの行には作らない(時刻なし = 以前から)。
  機械が書き換えて校正済みを外す所(`_apply_retranscribe`)は proofedAt も外す。簡易版(lite)も同じ保存(PUT /api/transcript)なので同じ
- **再認識の前の機械の出力**: `_apply_retranscribe`(each)・`_apply_range`(range / whole)・`apply_redo`(redo)が `original` を差し替える**前**に、
  `ed_jobs.record_rerun` が `recognition.runs` に1件足す: `{"kind", "engine", "engineVersion", "model", "device", "language", "settings": {beam, vadMode, boost, wordSplit, autoDict, dict}, "range": [a, b], "spans"?(2つ以上), "replaced": [差し替えられた original の行], "replacedOmitted"?, "at"}`。
  差し替える行は `replaced_rows`(`replace_original(_multi)` と同じ「真ん中」の決まり・守った行は入れない)。上限は再認識の記録 `MAX_RERUNS`(30)件・replaced の行の合計 `MAX_REPLACED_ROWS`(20000)(古い記録から捨てる。最初の認識の記録 = kind の無いものは捨てない)。
  **runs を読むときは kind の有無で分ける**(kind が無い = 最初の認識。`ed_lite.bundle_parts` の生出力の無い文書の代わりは `runs[-1]` を読むので、再認識のあとは再認識の記録になる)
- **辞書の版** `ed_jobs.dict_version(spec)`: `{"glossary", "replacements"(autoDict), "learned"(autoLearned。規則と採用・却下の記録), "roster"(名簿のファイル)}` = 中身の SHA-256 の先頭 10 文字。
  `recognition_run` の `settings.dict`・最初の文字起こしの `params.dict`・再認識の記録の `settings.dict`
- **カットの `draft`**(初めてのたたき台): 画面(`cut.js` の `noteDraft`)がまだ1回も保存していない間に作ったたたき台(開いたときの「行から」・作り直し・行から/カットしない/無音/時刻リスト/スタジオ)の最後のものを覚え、
  初めての保存(`body(0)`)に `draft: {"origin", "settings", "keepsSec", "at"}` を添える。サーバーの `save_edit` は保存済みの edit.json が無い(壊れていた)ときだけ書き(`sanitize_draft`。正しくなければ黙って捨ててカットは保存)、以後は引き継ぐ。
  `read_edit` も draft を通す(`pack` と同じ扱い)。以前の版で作った edit.json には後から足さない。人の最終は保存したカットとパックの `cutPlan`。
  (b) `edit_draft`(GET)で書く案は採らなかった: GET で書くと edit.json ができて「たたき台のまま(pristine)」の扱い・行が変わったときの作り直しが変わるため
- **校正の手間** 文書の `effort = {"activeSec", "cutSec", "sessions", "proofedRows", "unproofedRows", "lastAt"}`: 時間は画面(app-learn.js の `effortTick`・`effortStart`・`effortFlush`。`S.eff`)が
  `S.sess.activeMs` と同じ 30 秒刻みで、1 文字起こし = activeSec・2 カット / 3 パック = cutSec にため、5 分たまったとき・`UIKit.life.onLeave`(keepalive)・別の文書を開くとき(`openDoc`)に `POST /api/effort`(`ed_store.add_effort`。1回 3600 秒まで)。
  行(proofedRows・unproofedRows)は `save_transcript` で `effort_rows` が数える。`restore_history` は effort を戻さない。簡易版は時間を送らない(行は数える)

## 2つ目のエンジンの候補(計画 第2版 D1-b。v0.49.0)
校正を速くするため、主のエンジンとは別のエンジンで同じ音声を認識し、食い違う所を行の候補(学習の提案と同じ形・tier `alt`)に出す。**自動では書き換えない**。本体は `ed_alt.py`(名前は `alt_`・`ALT_`・`_alt_` で始める。serve.py の `_ED_MODULES` の最後)。テストは `tests/test_alt.py`(test_metrics から読む)・画面は `tests/e2e_alt.py`(入口に取り込んだ形)
- **ジョブ** kind `alt`(`POST /api/alt {id, engine?}` → `alt_spec` → `run_alt`)。優先度 2(`JOB_PRIORITY`。普通の文字起こしより後)・同じ文書の alt は 1 つだけ(`EXCLUSIVE`)・待機列・SLOTS・取り消し・ワーカーは今の仕組みのまま。
  文書の範囲(start〜end)の音声を `extract_audio` → `transcribe_real`(疑似は `_alt_fake` = 主の疑似の行に環境変数 `TRANSCRIBE_FAKE_ALT="誤=>正,…"` をかける)→ `expand_segments`(句読点の除去・行の分け方は同じ。置換辞書・学習した置換はかけない)。
  **ヒント(用語集・文脈)は渡さない**(ヒントの語が候補に漏れないように)。声の検出は weak・beam 5・単語の時刻で分ける
- 結果 `transcripts/<id>.alt.json` = `{"schema": "youtube-tools-alt/v1", "id", "engine", "engineVersion", "model", "device", "at", "range": [start, end], "audioSec", "wallSec", "rows": [{start, end, text}], "fake"?}`(時刻は元の動画の秒)。
  書くのは `_save_lock` の中で文書があるときだけ(認識の間に消された文書の付き物を作らない)。**文書(<id>.json)は書き換えない・updatedAt を動かさない**ので、編集を止めるジョブ(`LOCK_KINDS`)にしない。文書の削除(serve.py の `_delete`)で一緒に消す
- 断る(`alt_spec`): 評価用の文書・評価用のフォルダの動画(400 `eval_set`。定点の正解が 2 つのエンジンに寄らないように)・文字の無い文書(`empty`)・動画が無い(`no_file`)・
  その文書の最初の認識(`recognition.runs` の kind の無い記録。`alt_first_run`)と同じエンジンかつ同じモデル(`same_engine`)・同じ文書で実行中(409 `busy`)。疑似でなければ `check_engine` も(実行ファイルが無いなど。GPU が無いのは読み込みのときにエンジンが理由を出して止める = 黙って CPU にしない)
- エンジン: `ALT_ENGINES`(設定 `altEngine` の値 → エンジン・モデル・機器。ここ 1 か所)= `llama.cpp`(Qwen3-ASR 1.7B・GPU。**既定** `ALT_DEFAULT`)/ `whisper.cpp`(large-v3・GPU)/ `faster-whisper`(large-v3・CPU)。
  選び方 `alt_engine_key`(要求の engine → 設定 → 既定)。`altEngine` は `SETTINGS_PATCH_KEYS`(画面は `api/settings/patch`)。`/api/tools` の `alt`(`alt_info` = 選べるエンジンと準備)
- 自動: 設定 `autoAlt`(既定オフ)。`validate_job` が `spec["autoAlt"]` = 要求の autoAlt(真偽値のとき)か、無ければ保存した設定(まとめて実行 `home/autorun.py` の TX_KEYS は autoAlt を送らないため)。評価用は常に偽。
  `run_job` の終わりに `alt_after_transcribe` が alt のジョブを足す(始められなくても文字起こしは成功のまま・`job["warnings"]` に理由)。友人用簡易版は `autoAlt: False` を送る
- **候補** `alt_diffs(rows, alt_rows)`(純粋な関数)→ `([{seg, i, wrong, right, tier: "alt", pos: 0, neg: 0}], {long, cross, mostly, notation, edge})`:
  比べるときだけ寄せる `alt_fold`(NFKC・小文字・カタカナ → ひらがな・伸ばし `ALT_DROP_CHARS`・文字でも数字でもないもの(記号・句読点・空白)を捨てる)。寄せた文字 → 元の行と位置の対応を持ち、
  行の時刻で `ALT_WINDOW_SEC`(90 秒。区切りは目安の前後 `ALT_WINDOW_SLACK` 秒で行のすき間がいちばん長い所 = `_alt_windows`)の窓ごとに `difflib.SequenceMatcher(autojunk=False)`。
  2つ目のエンジンの行は真ん中の時刻で 1 つの窓だけに入れる。窓の境目に触れる食い違いは出さない(`edge`)。片方だけにある文字は隣の 1 文字を足して置き換えの形に。
  出さない: どちらかが `ALT_MAX_CHARS`(12)文字を超える(`long`)・行をまたぐ(`cross`)・行の寄せた文字の半分以上が違う行(`mostly`)・置き換えで片方がひらがなだけ・もう片方が漢字まじり(`notation` = 表記だけの違いらしい。読みは分からないので出さない側)・校正済みの行・同じ行で重なる位置。
  候補は今の行の文字に対して毎回計算する(採用・人が直した所は自然に消える)。4 時間・5000 行で 0.2 秒ほど
- `GET /api/suggest`(`ed_learn.suggest_for_doc`)が `alt_suggest` で足す: 却下した候補(`fb["dismissed"]` の `seg|誤=>正`)と、同じ行・同じ位置の学習の提案と重なるものは出さない(学習を優先)・合わせて 1000 件まで。
  応答の `alt` = `{engine, model, label, at, count, skipped}` か null(alt.json が無い・評価用)。結果は `_alt_cache`(alt.json の更新日時・大きさ・文書の updatedAt・行数)
- 採用・却下 `POST /api/suggest/feedback`: 項目の `tier: "alt"` は学習の統計 `fb["stat"]` に入れず `fb["alt"] = {acc, rej}` に数える(却下は今までどおり `dismissed` へ)。`load_feedback` が `alt` も返す。辞書の版 `dict_version` の learned は `alt` を除いて作る
- 画面: 行の候補は `app-learn.js` の `sugHTML`(tier `alt` は札「別」・クラス `tt-sg-alt`(`--info` の点線)・title に「別のエンジン(名前)では、こう聞こえた候補」)・`sugFeedback` が `tier: "alt"` を付けて送る。
  「文字をまとめて直す」の「別のエンジンの候補(試験中)」(`#altEngine`・`#altGo`・`#altMsg`。`renderAlt`。評価用・動画のパスが無い・行が無いときは押せず理由)。
  新規の「認識の設定」のチェック `#optAutoAlt`(設定 `autoAlt`・`jobOpts`)。ジョブが終わったら開いている文書なら `loadSuggest`(`pollJobs` の `altDone`)。「確度高の提案を全部採用」は alt を含めない
- これから(計画 D1-b): 印の当たり率(`fb["alt"]` と、普段の校正で人が直した所に印があった割合)を測って既定を決める。名簿の呼び名と一致するときだけ自動で採るのは当たり率を見てから(E3)

## 構成
- **段10(2026-10-01)で serve.py を役割ごとの部品に分けた**(`../docs/plan/phase10-code-split.md`。動きは同じ): `ed_state.py`(置き場所・設定の値・共通の小道具・記録・作業データの切り替え)・
  `ed_store.py`(保存・履歴・編集の内容)・`ed_relink.py`(付け替え・評価用のフォルダ)・`ed_media.py`(波形)・`ed_jobs.py`(ジョブ・認識ワーカー・声の検出のやり直し・単語の時刻・再認識・疑わしい所)・
  `ed_speakers.py`(話者判別・声を覚える)・`ed_learn.py`(辞書・学習・提案・精度・基準・書き出し・保管)・`ed_misc.py`(設定の比較・clip-marker・進行度・フォルダの一括・受け渡し)・`ed_evalaudio.py`(評価用の音声 flac。上の節)・`ed_alt.py`(2つ目のエンジンの候補。上の節)・`serve.py`(版・起動・HTTP の振り分け)。
  部品どうしは `ed_xxx.名前` で呼ぶたびに読む(`from … import` しない = 差し替えが効く)。**serve.py が名前の受付**: `serve.名前` は持ち主の部品から読み、`serve.名前 = …`(テストの差し替え・mock.patch.object・入口の ALLOWED_HOSTS・ワーカーの IN_WORKER)は持ち主の部品へ転送する。
  版の正は serve.py の `SERVER_VERSION`(入口が読む。部品は `ed_state.SERVER_VERSION`)。新しい名前は、役割に合う部品に書く(serve.py の名前を部品から使わない)。import のときに使ってよいのは `ed_state` の名前だけ(ほかの部品は呼ぶときに)。
  テストで serve.py を一時フォルダに写すときは `ed_*.py` も写す(各 e2e の一覧は `ed_` で始まる .py を足す形)。まとめて流す: `python dev/run_editor_suite.py`
- **段10-2 で app.js も分けた**: 関数の定義は `app-core.js`(共通・表示の好み・⚙・設定・進行度)・`app-jobs.js`(新規ジョブ・フォルダ一括・連携・ジョブの進捗・話者判別・声を覚える・再認識)・`app-list.js`(履歴の一覧・選んでまとめて)・
  `app-learn.js`(学習の候補・提案・校正済み・進み具合・精度・名簿・保管)・`app-rows.js`(編集画面の保存と開く・行・字幕の文字数・行の移動・話者の色・キー配置・用語・履歴・行の追加)・`app-tools.js`(付け替え・検索と置換・書き出し・左パネル・受け渡し・cut2resolve・確認・カット/パックのつなぎ)。
  **状態(S・V など)・定数・ボタンの配線・起動は app.js に元の順番のまま**(包み `(() => {…})()` は外した = トップレベルの const/let と関数は同じ画面のスクリプトで共有)。読む順番は index.html(app-*.js → app.js)・静的配信は `ed_state.PAGE_JS`。
  新しい関数は役割に合う app-*.js に、新しい配線・状態は app.js に。トップレベルの名前はブラウザの window の名前(close・open・name など)と重ねない。版 `APP_VERSION` は app.js のまま
- `serve.py` … Python 標準ライブラリの HTTP サーバー(127.0.0.1:8775)。文字起こしは faster-whisper、話者判別は sherpa-onnx(任意)。
  ジョブは優先度付きの待機列(話者判別は、待っている文字起こしより先に処理。実行中のジョブは中断しない)。
  保存は `transcripts/<id>.json`(`segments` = 人が直した行、`original` = 機械の出力。精度測定・修正からの学習は、この2つを時刻の重なりで対応づける)
- `index.html` … 画面(CSS・HTML)。将来の統合(入口の `/transcribe/` に取り込む)に備えて CSP(`script-src 'self'`)に対応させたため、
  JS はインラインではなく `app.js`(このツールの画面ロジック)・`ui-kit.js`(共通の見た目。下記)を `<script src=...>` で読む。CSS は引き続き `<style>` に埋め込み(CSP はインラインの style を許可)
- `tx_worker.py` … 認識ワーカー(別プロセス。統合計画の段階3-3)。faster-whisper・sherpa-onnx(ネイティブコード)は**このプロセスの中だけ**で読み込む。
  serve.py の `WorkerClient`(`WORKER`)が起動し、標準入力/出力の1行1件の JSON でやり取りする。serve.py 側の `load_model()` は代理の `RemoteModel`
  (`transcribe()` が faster-whisper と同じ形 (行の生成器, 情報) を返す)を、`diarize_real()` はワーカーの結果を返すので、ジョブの処理(行の整形・保存)は変えずに済む。
  本体は serve.py の `_load_model_local()`・`_diarize_local()`(ワーカーが serve.py を読み込んで `IN_WORKER = True` にして呼ぶ)。
  音声の範囲はパスとサンプル番号で渡す(`read_wav_f32()` はサーバー側では `WavRef` を返し、numpy を読み込まない)。
  **サーバー側のプロセスで numpy・faster_whisper・ctranslate2・sherpa_onnx を import しない**(入口に取り込むと、落ちたときスタジオ・cut2resolve まで止まる。`test_worker.py` が検査)。
  やり取り用の標準入力は fd 0 から離して読む(`_protocol_input`。Windows で標準入力のパイプを読んで待つ間に DLL を読み込むと止まるため。2026-09-26)。
  ワーカーが落ちたらそのジョブだけ失敗、次の要求で起動し直す。取り消しは `job["proc"]`(`_CancelHandle`)経由で伝え、15秒で止まらなければ強制終了。
  **黙ったワーカー**(何も届かない)は `WORKER_SILENCE_TIMEOUT`(20 分)で強制終了してそのジョブを失敗にする(標準出力は読み取り専用のスレッド `_reader` が列に入れ、待つ側 `_read` は `queue.get(timeout)`。
  待ち続けると SLOTS を持ったまま他のツールの重い処理を塞ぐため。2026-10-01)。
  `TRANSCRIBE_MODEL_IDLE_SEC`(既定3600秒。10-04 に 900 から延ばした)使わなければワーカーごと終わらせる。GPU の有無も別プロセス(`tx_worker.py --probe`)で1回だけ調べる
  ワーカーは Windows で「通常より下」の優先度で起動する(`_worker_priority`。画面・書き出し・パックが先に CPU を取る。`TRANSCRIBE_WORKER_PRIORITY=normal` で今までどおり。10-04)
- `app.js` … 画面の JS(旧 index.html の即時関数の中身をそのまま移した)。状態 `S`(文書・今の行など)と `V`(表示の好み。localStorage)はこのファイルのトップレベル変数で、グローバルではない。
  主なまとまり(v0.15.0): 履歴の一覧(「保存済み一覧」の節。`L` = 絞り込み・並び替え・まとめ方(localStorage `tx.list.v1`)、`txGroups`・`txOpen`・`txLimit`。
  開いているまとまりの分だけ描き、まとまりごとに「もっと見る」)、「編集」のタブ(`EDT`・`setEditTab()`・題名の行 `renderDocBar()`)、
  cut2resolve の呼び出し(`c2rBase()`/`c2rUrl()`/`c2rApi()`・`cpExport()`・`confirmOverwrite()`。パックのタブが使う)、キー操作の手がかり(`tx.keyhint`)
- 一覧の API `/api/transcripts`(serve.py の `list_transcripts`・`transcript_summary`): 行数(`rows` = 文字のある行)・`proofed`・`cut`・`flagged`・`durationSec`・
  元の配信(文書の `clip`(youtube-tools-clip/v1)の `videoId`・`clipTitle`・`clipStart`/`clipEnd`・`markLabel`)・配信者 `channel` と `streamTitle`
  (スタジオの data.json を**読むだけ**。置き場所は `studio_data_path()`、更新日時と大きさでキャッシュ `studio_videos()`)・元の動画の有無 `mediaOk`・
  パック `pack`(動画の隣の `<名前>_pack`。cut2resolve の作業データの「パックを作った記録」か、以前のパックならフォルダの中の cut-plan.json。
  規則は `ytt_core/txindex.pack_info` の1か所 = 入口の案件の画面 `home/cases.py` の `find_pack` と同じ判定。2026-09-26 ④)。
  動画・パックの有無はフォルダごとに1回・全体で `PACK_CHECK_BUDGET` 秒まで調べ、ネットワーク上のパス(`\\サーバー\…`)は調べない(資格情報を送らない。`mediaOk = None`)
- 3 パック のタブ(「編集」E4。`pack-tab.js`。v0.15.0 の校正画面の「カットとパック」を置き換えた): パック作りは **cut2resolve の API を呼ぶ**(文字起こし側に Resolve 用の計算を書かない)。
  区間は 2 カット のタブのとおり: cut2resolve の `api/build` の spec = `{video, transcript?, keeps: 残す区間の秒, advanced}`(`pack.EDIT_KEEPS`)・output = `{textplus, copyVideo, render, textplusFps, textplusSize, textplusWrap, streamer, speakerColors, backup, dir?, force}`(`pack-tab.js` の作るところ)。
  作る前にカットを保存し(`CUT.commit()`)、字幕の元として保存済みの文字起こしを動画のフォルダの `作業用\` に `.transcript.json`(`cpExport`。2026-09-27 から途中のファイルは `作業用`。規則は `ytt_core/schemas.py`)。文字起こしが無ければ Text+ なし(EDL と元の動画のコピー)。
  409 exists は上書きの確認(`#dlgOverwrite`)→ force。作り終えたら `POST /api/edit/pack`(packRev。任意の `output` = 作ったときの出力の設定 {fps・size・wrap・textplus・backup・render・speakerColors・streamer?・loudness?・volume?・advanced?{srcStartTc・recStart・reel}}。`sanitize_pack_output` が決まった鍵・型・長さだけ確かめ、余計な鍵は捨て、1つでも正しくなければ `output` なしで記録する(古い画面・まとめて実行は送らない)。edit.json の `pack.output`。`packStale` は output を見ない)。「これから作るパック」の字幕の数・注意は `POST /api/edit/preview`(ファイルを作らない。応答の `sampleSpeakers` = `samples` と同じ順の話者の名前か null。`pack.cue_speakers` = 実際のパックと同じ規則)。
  cut2resolve の URL は `c2rUrl()` だけで作る(`UIKit.tools.base('cut2resolve')`。入口の中の同じポートのときだけ。合言葉は同じ入口のもの)。
  単体で開いたとき・cut2resolve が起動していないとき・動画が無い/音声だけ/ネットワーク上のときは理由を出して作れなくする(見積もりと zip は使える)。
  前回のパックの「フォルダを開く」は cut2resolve の `api/open-folder`(パックを作った記録か、以前の cut2resolve の cut-plan.json があるフォルダなら、入口を起動し直したあとでも開ける。
  `txindex.is_pack_dir`)。パックは最小限(④): 「予備も入れる」(`output.backup`)で EDL・予備の手順書・SRT。Text+ の .json は出さない(区間・字幕は Lua に埋め込み。テストは `resolve_textplus.read_script_plan` で読む)。
  zip(`/api/resolve-package`)と「残す区間(.cut-plan.json)を保存」も、カットがあればそのとおり
- `resolve_export.py` … 「Resolveパッケージ(zip)」(`/api/resolve-package`)。中身は隣の `../cut2resolve/pack.py` で作る
  (文書 → transcript/v1 → `pack.plan_cut(**pack.TRANSCRIPT_ROWS)` → `pack.build_pack(textplus=True)` → zip)。**Resolve 用の計算をここに書き足さない**
  (二重実装に戻さない。`../docs/design/resolve-pack-unification.md`)。cut2resolve の部品は呼ばれたときに読み込み、見つける場所は
  環境変数 `YTT_CUT2RESOLVE_DIR` → `../cut2resolve`。ここに残っているのは「残す行」の規則(`is_kept`・`kept_spans`)と SRT の書式(pipeline_io が使う)
- 「編集」(文字起こし + cut2resolve の統合。`../docs/design/edit-tool-design.md`。2026-09-26 に E1〜E6 を実装)のサーバー側(serve.py の「編集の内容」「音の波形」の節):
  編集の内容 `transcripts/<id>.edit.json`(残す区間 = カットの正。`GET/PUT /api/edit`・rev と 409)、`POST /api/edit/pack`(パックを作った記録・`packStale`)、
  `POST /api/open-video`(文字起こしせずに開く)、`GET /api/peaks`(音の波形。作っている間は 202)、`POST /api/transcribe` の `intoDoc`。
  **動画を選び直す**(段2 B-4。v0.25.0): `POST /api/relink/check`(書き込まない確認)・`POST /api/relink`(`baseUpdatedAt` 必須・409 = conflict / busy / duration_mismatch(`acceptDiff` で通す))。
  パスの検査は `relink_path`(ネットワークはファイルに触る前に断る → realpath のあとでもう一度・「:」・拡張子・`DATA_DIR` の中)。書き換えるのは sourcePath・sourceName・updatedAt・`relinks`(最新 10 件)だけ。
  控え = `.bak/<id>.pre-relink.json`・`.bak/<id>.edit.pre-relink.json`・履歴。長さの決まりは `_relink_ref`(動画全体 = duration と ±max(1秒, 0.5%)、範囲 = end − 0.5 秒以上)。
  **まとめて付け替える・参照…**(v0.31.0。ユーザー決定 2026-10-01: 参照の窓 + 履歴からまとめて。「候補を自動で推測しない」を、ユーザーが選んだフォルダの中の同じファイル名に限って緩めた):
  `POST /api/relink/missing`(パスの記録があって見つからない文書。ネットワーク上は調べず skipped)・`POST /api/relink/find {folder, ids}`(`relink_folder` で検査 → `os.walk` で同じファイル名。
  上限 `FIND_BUDGET_SEC`・`FIND_MAX_ENTRIES`・`FIND_MAX_DEPTH`・ごみ箱やシステムのフォルダと `.` で始まるフォルダと DATA_DIR は見ない。書き込まない)・`POST /api/pick {kind: file|dir, hint}`(`ytt_core/pick.py`。409 pick_busy・400 pick_unavailable)。
  画面は `#relinkAllDlg`(app.js の `RA`・`openRelinkAll`・`raFind`。確かめるのは1件ずつ直列・長さが違うものは最初は選ばない・選んだ = acceptDiff)。案内は履歴の上の `#txMissing`(`renderMissing`。一覧の `mediaOk === false`)
  画面は `#relinkDlg`(app.js の `openRelink`)。再生の失敗の案内 `renderPlayerMsg` はカットのタブの `CUT.state().offCode === 'source_missing'` のときだけボタンを出す
  **設定の保存**(段2 監査 11): 画面は最後に保存した内容との差のキーだけを `PUT /api/settings {"patch": {キー: 値 | null}}`(`merge_settings`。`SETTINGS_PATCH_KEYS` は変えない)。丸ごとの PUT も従来どおり受ける。
  失敗は ui-kit の `UIKit.settings.status`(⚙ の印と引き出しの先頭)。読み込みに失敗したら `S.settingsLoadErr` を立て、読み直すまで保存しない(`saveKeymap` も)。
  URL の `?doc=` は `setUrlDoc`(監査 06。replaceState)。カットの読み込みの失敗は `offCode = 'edit_load'`(監査 13。`#cutRetry`)
  **キーと元に戻す**(段3。v0.26.0): 文書・カットのキーは `menuHasKeys(t)` = 重ねて開いたメニュー **または** フォーカスがメニューの中 のとき働かない(新しい keydown を足すときも通す。G・Esc・Alt+数字・? は除く)。
  キーの表示は割り当てから: 行の title は `titlePlay`・`titleProof`・`titleTag`・`titleAddAfter`・`titleDel`、静的な HTML は `data-key-title="操作の id"`・`data-key="id"`(+`data-key-fmt`)を `renderKeyUI` が埋める(キーを書き込まない)。
  1 文字起こし の「1コマ」は `CUT.frameStep(t, n)`(cut.js の stepFrames と同じ丸め)。元に戻すは `S.undo = [{seq, snap}]` とカットの `M.undo[].seq`(`nextOp()` の通し番号)を比べて新しい方(`doUndo`。2 カット の Ctrl+Z はカットだけ)
  **単語の時刻** `transcripts/<id>.words.json`(文書全体の単語の並び。認識と範囲の再認識が書く・削除で消す)と `POST /api/resplit`(今の文書を分け直す)。
  1つの字幕の最大文字数は設定の `subtitle`(`subtitle_settings`・`split_chars_for`)。行を分ける規則は `split_segment`(+2 文字まで許す)。細かい決まりは設計書の 12 ②。
  **再認識(範囲・全体)と声の検出のやり直し**(v0.21.0。`../docs/design/whole-retranscribe-design.md`): `POST /api/retranscribe` の `mode` = each(行ごと)/ range / **whole**(文書の範囲全体。`ids` はサーバーが「校正済みでない行」を入れる・上限は新規と同じ `MAX_SPAN_SEC`・声の検出は明示の off 以外「弱め」・評価用は断る)。
  range と whole の認識は `RangeRecognizer`(本物 / 疑似。疑似は `TRANSCRIBE_FAKE_GAP`・`TRANSCRIBE_FAKE_LOOSE` で 0 文字の所と緩い条件の結果を作れる)。反映は `apply_range(spec, lines, loose)` → `plan_range`(差し替えない行 = 守る区間を `fit_lines` で避ける・新しい行の重なりが `EMPTY_COVER` 未満の元の行は残して `EMPTY_FLAG`)。
  ほぼ空だった所は `RangeRecognizer.loose`(声の検出なし・`no_speech_threshold=None`・よくある誤認識の文は捨てる・`LOOSE_FLAG`)。守る区間と残した行の `original`・単語の時刻は古いまま(`replace_original_multi`・`replace_words` の keep)。
  **声の検出が捨てすぎたら緩める**: `transcribe_vad_fallback`(新規 `transcribe_real`・range・whole が共通で使う。`VAD_LADDER` 標準→弱め→なし、残りが `VAD_MIN_KEEP` 未満か文字 0 で次へ)。ワーカーは認識を始めた直後に `info`(duration・duration_after_vad)を送り、`RemoteModel.transcribe` は行より先にそれを読む(`_Segs.close()` で行を読まずにやめられる)。新規の文字起こしは、やり直しに備えて行を最後まで読んでから流す(処理状況の行数は読みながら `job["segments"]` に入れる)。記録は `recognition.runs` の `vadUsed`・`vadRemovedSec`・`vadRetries`、`params.vadUsed`、知らせは `job["vadNote"]`(`public_job`)。疑似のワーカーは `TRANSCRIBE_FAKE_VAD`(drop-normal / drop-vad)
  `public_job` は `job["warnings"]` も画面に出す(以前は `spec["warnings"]` だけで、ジョブの中で足した注意が届いていなかった)
  **疑わしい所だけ認識し直す**: ジョブ `redo`(`POST /api/redo`・`run_redo`・`redo_targets`・`redo_better`・`apply_redo`。話者判別・再認識と同じく編集を止める)。設定 `autoRedo`(既定オフ)・`redoLarge`。設計書の 12 ③-2
  **行の cutState は、編集の内容があれば文書の書き込みで `apply_edit_cuts` で編集の内容から付け直す**(行を足す・分ける・時刻を変える処理を足すときは必ず通す)。
  通らないのは、新しい文書を作るとき(編集の内容がまだ無い)と、行の時刻を変えない書き込み(話者判別の結果・覚えた声で名前を付ける)だけ
  細かい決まりは設計書の「11. 実装で決めたこと」
- `pack-tab.js` … 「編集」3 パック のタブ(置き先・入れるもの・出力先・これから作るパック・字幕の見本・作る・前回のパック・zip)。app.js より先に読み、`EditPack.create(host)` で起動する
- `cut.js` … 「編集」2 カット のタブ(タイムライン・プレビュー・字幕の一覧・たたき台・保存)。app.js より先に読み、app.js が `EditCut.create(host)` で起動する。
  区間はフレームの整数で持つ。行の「カット済」の規則 `rowCutFlags` は serve.py の `edit_cut_flags` と同じ(変えるときは両方)。細かい決まりは設計書の「11」の E3
- `test_metrics.py` … サーバー側の単体テスト。`test_edit.py` … 「編集」のサーバー側(test_metrics から読み込まれる)。`e2e_*.py` … 画面の通し確認(Playwright + 疑似モード)

## テストの実行
すべてリポジトリ直下から流す(テストは `editor/tests/`。2026-09-30 に移した)。
```
python -m unittest editor/tests/test_metrics.py editor/tests/test_resolve_export.py editor/tests/test_roster.py   # サーバー側(test_backend.py・test_worker.py・test_edit.py・test_voices.py も test_metrics から読み込まれる。`test_edit` の2件は Windows のパス前提で、Windows 以外では飛ばす(段1。`home/tests/test_window.py` の窓の API の3件も同じ)。一覧の項目は test_backend の test_list_fields_for_history)
node --test editor/tests/test_document_save.cjs   # 保存・切り替えの競合(9件)
python editor/tests/e2e_proofread_accuracy.py    # 校正済み・精度・用語集・設定の比較・辞書(旧 e2e_ui_v07)
python editor/tests/e2e_proofread_keys.py        # 左手のキー・表示の設定・保管・保存の競合・4000行(旧 e2e_ui_v08)
python editor/tests/e2e_folder_marker_range.py   # フォルダ一括・スタジオのマーク・範囲の再認識・進み具合(旧 e2e_ui_v09)
python editor/tests/e2e_eval_set.py              # 評価用(旧 e2e_eval_v093)
python editor/tests/e2e_row_editing.py           # メニュー・行の追加・重なり・Z・画面幅(旧 e2e_ui_v098)
python editor/tests/e2e_ui_handoff.py
python editor/tests/e2e_edit_tabs.py            # 「編集」E2: 3つのタブ・Alt+1/2/3・URL の #・メニューの帯・題名の行・文字起こしせずに開く(共通部分は e2e_edit_common.py)
python editor/tests/e2e_edit_cut.py             # 「編集」E3: カットのタブ(入口に取り込んだ形。ドラッグ・吸着・分割・削る/戻す・I/O/X・元に戻す・保存・409・カット後の再生・無音のたたき台)
python editor/tests/e2e_edit_voices.py          # 話者の声を覚える(A-3。名前を付ける → 覚える → 判別し直すと名前が付く → 忘れる)
python editor/tests/e2e_edit_pack.py            # 「編集」E4: パックのタブ(入口に取り込んだ形。カットのとおりのパック・短い区間と 60fps の注意・前回のパック・中止・Text+ なし)
python editor/tests/e2e_ui_mounted.py           # 入口(home/launch.py --only transcribe,cut2resolve)に取り込んだ形。CSP・合言葉・認識ワーカー(強制終了からの立ち直り)・
                                              # 履歴の一覧(配信ごと・配信者)・パックのタブ(cut2resolve の API・上書きの確認・zip)
python editor/tests/e2e_lite.py                # 友人用 文字起こし簡易版(lite.html・lite.js。入口に取り込んだ形。サーバー側は test_lite.py = test_metrics から読む)
python editor/tests/e2e_drill.py               # 評価ドリル(編集の画面の ?drill=1 の帯・確かめ済みの印)と「全行をこの人に」(入口に取り込んだ形。サーバー側は test_drill.py = test_metrics から読む)
python editor/tests/e2e_alt.py                 # 2つ目のエンジンの候補(D1-b。聞く → 行に「別」の候補 → 採用・却下 → autoAlt → 削除で alt.json も。入口に取り込んだ形。サーバー側は test_alt.py = test_metrics から読む)
python -m unittest dev/tests/test_ui_kit_sync.py  # ui-kit.js・index.html・lite.html に埋め込んだ ui-kit の CSS が正本とずれていないか
```
- e2e は serve.py を疑似モード(環境変数 `TRANSCRIBE_BACKEND=fake`)で起動して試す。ffmpeg と Playwright の chromium が必要(Playwright の入れ方: `py -3.10 -m pip install -r setup\requirements-dev.txt` → `py -3.10 -m playwright install chromium`)。この PC では `python` を `py -3.10` と読み替える(`python` は Microsoft Store の別名に当たることがある)。
  Windows のコンソールでは `PYTHONIOENCODING=utf-8` を付けて流す(付けないと ▶ などを表示できずに途中で止まる)。`e2e_ui_mounted.py` は Windows でも動く(ワーカーは PowerShell で数え、入口は Ctrl+Break で止める)
- 「編集」の e2e(`e2e_edit_*.py`)は `e2e_edit_common.py` の `Server` で起動する(ツールのファイルを拡張子でまとめて写すので、新しい .js の写し忘れが起きない。`mounted=True` で入口に取り込んだ形)
- `TRANSCRIBE_BACKEND=worker-fake` は、サーバーは本物の経路(認識ワーカーとのやり取り)を通り、ワーカーの中だけ偽のモデルを使うテスト用のモード
  (`test_worker.py`・`e2e_ui_mounted.py`・`home/tests/test_mount.py`)。`TRANSCRIBE_WORKER_CRASH=<n>` で n 行目のあとにワーカーを落とせる。
  `test_worker.py` は `test_metrics` から読み込まれる(上の1行のコマンドで一緒に走る)
- Playwright 同梱の chromium は H.264 を再生できない。画面で動画の再生まで確かめるテストでは、テスト用の動画を webm(VP9 + Opus)で作る
- e2e は一時フォルダに `serve.py`・`index.html`・`app.js`・**`cut.js`・`pack-tab.js`**・`ui-kit.js`・`hololive-roster.json`・**`pipeline_io.py`・`resolve_export.py`** を写して動かす
  (`pipeline_io.py`・`resolve_export.py` を写さないと、受け渡しの API・Resolve 書き出しが 500 になる。`app.js`・`ui-kit.js` を写さないと画面が真っ白になる)。
  共通部品 `../ytt_core/` は写さず、環境変数 `YTT_CORE_DIR`(リポジトリ直下)で見つける(Resolve パッケージを作るテストでは cut2resolve も `YTT_CUT2RESOLVE_DIR` で)
  (各スクリプトの先頭で設定している。新しいテストで serve.py を写すときも同じ1行を入れる)。`.runtime/` も `YTT_RUNTIME_DIR` で一時フォルダの中に置く
  (他のテストが同時に動いていても、「他のツール」の問い合わせ(/api/siblings)が混ざらないように)
- `e2e_ui_handoff.py` … 受け渡し(?media= / ?clip=・元の配信・動画の隣に保存・409)、テーマの保存の1本化、
  他のツールのメニュー、2026-09-24 の見直しで直した画面の不具合、v0.15.0 の見直し(単体でのカットとパックの案内・選んだ行のカット・動画なし・キー操作の手がかり・? ・390px の引き出し)
- e2e は全部通ること(以前あった「版 v0.9.4 の判定は想定内の失敗」は 2026-09-26 に app.js の版を読む形に直り、もう無い)
- `e2e_proofread_keys.py` の「4000行での Alt+Enter → 次の行 0.5 秒」は、マシンの負荷で時々超える(タイミング依存)
- e2e の各スクリプトは、メニューのタブで隠れるカードも操作できるように、テスト用のスタイルで全部のタブを表示している(タブ自体の確認は e2e_row_editing.py の最後)
- 見た目は共通の ui-kit(`../ui-kit/`)。`ui-kit.js` は studio と同じく `python dev/sync_ui_kit.py` で写したファイル(**手で直さない**)。
  CSS だけは画面が1ファイルの名残で index.html に埋め込み(`/* ui-kit:css:begin */…end */` の中。同じく sync_ui_kit.py で写す・手で直さない)。
  このツール固有の CSS はその後ろ(色は必ず ui-kit の変数。新しいクラスは `tt-` を付ける)
- 画面の色(テーマ)の保存は ui-kit の `ytt:theme` だけ(⚙ 設定の「テーマ」で変える。ヘッダーの明暗ボタンは ui-kit v14 でやめた。editor/lite.html だけ設定が無いので `data-theme-toggle` のボタンが残る)。`V`(tx.view.v1)には保存しない
- API・動画(`/media?...`)の URL は必ず `apiUrl()`(と `api()`・`apiBlob()`)を通して作る。`apiUrl()` は `app.js` 先頭の
  `const BASE = location.pathname.replace(/\/[^/]*$/, '')` を前に付ける(単体では `""`、入口の `/transcribe/` に取り込まれたときは `"/transcribe"`)。
  絶対パス `/api/...` を直接書かない。書き込み系(GET/HEAD 以外)には、入口が `<meta name="ytt-token">` で画面に入れる合言葉を
  `X-YTT-Token` ヘッダーで付ける(`TOKEN` が空、つまり単体起動のときは付けない)。他のツールへのリンクは `UIKit.tools.url()` を使う(BASE を使わない)

## 画面の設計で決めたこと(v0.9.9 の内容 + v0.18.0 で足したもの。変えるときはユーザーに確認)
- 編集画面は2列: 左 = 映像と道具(`aside.tx-stage`。画面に固定され、列の中だけスクロール)、右 = セリフの一覧(`#segs`)。狭いと1列(コンテナクエリ)
- 左のメニュー(`aside#menuPanel`)は ☰ / G で開閉し、状態を保存。**映像の欄(tx-stage)を畳むのではない**(過去に誤解して作り直した)。
  中は GPT 版のタブ(新規・履歴・精度・学習。`V.sideTab`)。編集欄が 1000px 未満なら文字起こしを開いた時点で自動で閉じる。
  v0.15.0: 画面が 720px 未満では本文の上に重ねる引き出し(`.tt-scrim` を押す・Esc で閉じる)
- v0.15.0: 映像の列は 映像と道具(`.pbox`: 題名・映像と再生の道具 `.tt-player`・編集の道具 `.tt-edit`)→ 道具のカード(v0.16.0 で「カットとパック」`#cutPack` は外した)
  (話者 `#spDetails` / 文字をまとめて直す `#fixDetails` / 書き出し `#exDetails` / 以前の版に戻す `#hiDetails`。「…」`#jumpMenu`(v0.18.0 から `details.ui-pop` のアイコンだけの丸ボタン。以前は「道具 ▾」)から移動)。
  行の検索・絞り込み・次の未校正・キーの手がかりは行の一覧の上(`#listHead`。2列では固定)。
  1列(編集欄 780px 以下)では `.tx-stage`・`.pbox` を display:contents にして、`.tt-player` だけ固定・道具のカードは一覧の後ろ
- 保存は GPT 版の仕組み(`saveDoc` を直列化、`openDoc` は保存できないときは切り替えずに false)。行ごとの「残す/カット済」(`cutState`)は「校正済み」の隣。
  まとめて変えるのは「まとめて ▾」の「選んだ行をカット/残す」だけ(同じ印を変える入口はこの2つ。「編集」E2 で「カットとパック」のカードから移した)
- 「編集」(E2〜): ヘッダーに3つのタブ(`#edTabs`・`setEditTab()`・`EDT`。URL の #tx/#cut/#pack・Alt+1/2/3。行の文字の入力中の Alt+数字 は話者のまま)。
  校正のキー(1 文字起こし 固有のもの。下)は 1 文字起こし のタブだけ(`wideTab()` で止める)。カット・パックのタブでは左のメニューを細い帯(`#menuStrip`)に畳み、
  帯から開くと本文の上に重ねる(`EDT.overlay`。`V.menu` とは別)。題名の行 `#docBar`(`renderDocBar()`)はどのタブにも出す。保存の状態 `#saveState` はヘッダー。
  題名の行の「まとめて実行 ▾」`#docAuto`(入口から開いたときだけ。今の文書を入口の `start-docs` で1本・`startDocAuto`・進み具合の札 `#pillAuto` = `renderDocAuto`。
  履歴の「選んで、まとめて実行」と同じ `pollRuns` で読み直す。2026-09-27 `../docs/archive/followup-2026-09-27.md` の 3)
- **話者の声(A-3。2026-09-27)**: 名前を付けた話者の行(1秒以上・「声が混ざっている」を除く・長い行から 40 行 / 240 秒まで。`voice_groups`)の声の特徴を
  sherpa-onnx の SpeakerEmbeddingExtractor で取り(`_embed_local`。**ワーカーの中だけ**。サーバーは `embed_groups` → `WORKER.call("embed")`)、長さ 1 にして
  作業データの `voices/<判別モデル>.json` に名前ごとに保存(`load_voices`/`save_voices`。同じ名前は使った秒で重みを付けて混ぜる)。
  話者判別のジョブの最後(`recognize_voices`。`spec.recognize` 既定オン)で、見つかった話者の特徴を覚えている声と比べ、
  コサイン類似度 `VOICE_MATCH`(0.60)以上・2番目との差 `VOICE_MARGIN`(0.08)以上・1つの名前は1人だけ(`match_voices`)のときに、
  **仮の名前(`話者n`)のままの話者だけ**名前を付ける。失敗しても判別の結果は残す(警告)。ジョブ `voice-learn`(`/api/voices/learn`)、一覧 `GET /api/voices`(特徴そのものは返さない)・`/api/voices/delete`。
  疑似モードの特徴 `embed_fake` は偽の話者判別と同じ 10 秒の入れ替わり(テストで「覚える → 名前が付く」を確かめるため)。声の特徴は個人を見分けられる情報なので、作業データの外に出さない(.gitignore の `**/voices/`)
  **覚えるときの安全(段1・2026-09-30。監査02・17・18)**: 覚えるときに使う行は `voice_learn_plan`(`voice_groups` の条件 + **校正済み** + 音のメモ `overlap`・`bgm`・`unclear` が無い)。**判別のときの照らし合わせ(`recognize_voices`)は `voice_groups` のまま**(校正前の文書でも名前が付く。変えない決定)。一般的な名前(本人・ゲスト・配信者・MC など・`話者A`・`Speaker 1`・英字1文字。`GENERIC_SPK_NAMES`・`is_generic_speaker_name` の1か所。NFKC・小文字・空白を寄せて比べる)は覚えない。画面は押すと `GET /api/voices/preview`(読むだけ。人・行・秒・既にある名前・断った名前・使わなかった行の数)を `confirmDlg` に出し、既にある名前は1人ずつ「同じ人ですか」。`POST /api/voices/learn` は `{tid, embedding, names, confirmSame}`(`names` が無い古い形は 400・既にある名前が `confirmSame` に無ければ 409 `confirm_same`)。`run_voice_learn` は読み直した文書で決め直し、`spec["names"]` との積だけを覚える。一覧の `generic` が真の声は「一般的な名前です(忘れることをおすすめします)」(消さない)
- **話者判別の記録(v0.46.0。マスタープラン Q2)**: 判別のたびに `transcripts/<id>.diar.json`(schema `youtube-tools-diar/v1`)に機械の最初の結果を残す(`ed_speakers` の `build_diar_run`・`write_diar`・`read_diar`。
  `apply_diarization` と 1人指定の `single_speaker` が書く・書けなくても判別は失敗にしない)。中身は `latest` = {at・engine・turns・overlaps・labelMap・rows[行の id]={label・speaker・ratio・mixed・weak}・voices} と `history`(前の回。新しい順・最新を含め 5 回まで)。
  `voices` は `recognize_voices` が `update_diar_voices` で足す(話者ごとの top/second の名前と点数・decided・by = threshold/elimination/request・reason = 付けなかった理由。`match_voices_explain`)。ベクトルは書かない。
  人の最終は今までどおり行の `speaker`・`speakers[].name`(変えない)。文書の削除(serve.py の `_delete`)で一緒に消える。テストは test_voices の `TestDiarRecord`・`TestDiarDelete`
- 映像の上の字幕(`#playerCaption`)は、行の話者の名前がメンバーと合えばその色(`capSpeakerColor`。入口の `api/ytt/streamer-colors` を名前ごとに1回引いて覚える・パックのタブの `tx.pk.speakerColors` が '0' なら出さない・合わなければ pack-tab.js が body に入れた配信者の色 `--tt-cap-color` のまま)
- 行の ▶ は**その行だけ**再生して止まる(`playSeg(s, true)`)。通しの再生は映像そのものの再生ボタン / Space だけ
- キー操作は**単体キー**(Shift 不要)。例外は Shift+Space(校正済みにして次へ)と Shift+↓/↑(未校正への移動)だけ。Z は2回押しで削除。
  **左手のキー(ユーザー決定 2026-09-27「左手での操作が使いやすかった」。やめない)**: W/S 行・A/D 未校正・Q/E 3秒・B 自動で再生の切り替え・Tab 入力欄に入る/抜ける・入力中の Ctrl+Enter 聞き直す。
  v0.18.0 で ↓/↑・Shift+↓/↑ に置き換えたが 0.18.2 で左手のキーを戻し、↓/↑・Shift+↓/↑ は別の手段として残した。S の分割は 2 カット のタブだけ(校正のキーは 1 文字起こし のタブだけなので重ならない)。
  Space の再生・停止は `editPlaybackKeys` だけ(以前は app.js の末尾にも Space の処理が残っていて、1回押すと「再生 → すぐ停止」になった。0.18.2 で削除)。
  共通の再生キーは押しっぱなしの繰り返し(`e.repeat`)で Space・K・L・I・O を繰り返さない(J・矢印・, . は繰り返す)。
  **キー配置(v0.19.0。ユーザー決定 2026-09-27「設定で自由に割り当て」「共通の再生キーも変更可」。気が利く画面へ 段6(2026-09-29)で ui-kit の部品 `UIKit.keymap` へ。`../ui-kit/README.md` の「v8」)**:
  キーを変える場所は ? の一覧(`#keysList`)の 1 か所だけ(`KM = UIKit.keymap.create(...)`。app.js)。⚙ の「キー配置」には説明と「キー配置を変える(?)」のボタン(`#setKeysOpen`。引き出しを閉じて ? の一覧を開く)だけを置く(以前の `#kmGrid` はやめた。2026-10-04)。操作の一覧は `TX_ACTIONS`(校正)で、共通の再生キーは部品が足す。
  割り当ては必ず `keymap()`(= `KM.map()`。共通の再生キーを含む)で読む。校正のキーは編集の設定 `S.settings.keymap` に**送ったキーだけ**直す(`saveKeymap` → `api/settings/patch`。serve.py の `SETTINGS_PATCH_KEYS`・形は fullmatch で検査)。
  共通の再生キーはホームの設定 `keymap.playback`(スタジオと同じ。入口の外で開いたときだけ編集の settings.keymap = `fallbackPlayback`)。
  使えないキー: 校正のキーは `refuse`(`KEY_FIXED` = ↓↑・Shift+↓↑・Tab・Esc・Enter・?、数字 = 話者)、共通の再生キーは加えて部品の `PB_BLOCKED`(2 カット のキー S・X・Q・W・[ ]・Delete など)。重なりの検査は部品の1か所。
  変えられないキーの表(錠と理由)は `fixed`(2 カット のキーは `CUT_KEY_ROWS` の1か所。1コマのキーを変えたら「そのキー + Shift」で10コマ)。
  再生のキーは `UIKit.keys.playback({ keymap })` に渡す(1 文字起こし = `editPlaybackKeys`、2 カット = cut.js の `commonKeys` が host の `keymap()` を使う)。
  下の帯・一覧の上の手がかり(`#keyHintItems`)・基本の流れ(`#keysFlow`)・行のボタンのツールチップは `renderKeyUI()` がまとめて描く(部品の `onChange` から呼ばれる)。2 カット の帯・案内(`#cutKeysText`)は `ytt-keys-changed` で描き直す。
  ? をもう一度押すと一覧を閉じる(S-29)。重ねて開いた左のメニューの中のキーは後ろの文書を動かさない(`menuHasKeys`。GPT-04)。
  新しい校正の操作をキーに足すときは `TX_ACTIONS` と `KEY_FN` に足す(直に e.code で判定しない)。cut.js に新しいキーを足すときは `CUT_KEY_ROWS` と ui-kit の `PB_BLOCKED` にも足す。確かめるテストは `../home/tests/e2e_keymap.py`
  共通の再生キー(Space・J/K/L・← →(Shift で5秒)・, .・I/O)は `UIKit.keys.playback()` の1か所(`ui-kit.js`)。1 文字起こし は `editPlaybackKeys`(`media: player()`)、
  2 カット は `commonKeys`(`media: mediaProxy`。生の `<video>` だと togglePlay の頭出し・フレームの丸めを通らないので、`cut.js` の関数へ委ねる薄い代理オブジェクトを渡す)。
  各画面は自分のキー処理より**先に**共通キーを呼び、処理済み(true)なら自分では何もしない(1つのキーは全体で1つの意味。I/O は 1 文字起こし では何もしない = 別の意味を持たせない)
- 行の操作ボタン(時刻の微調整・再生位置・＋前に行・＋後に行・分割・結合・削除)は選んだ行(`.seg.nav`)の下にだけ出す
- 「今の行」(`S.navIdx`、青い太枠)と一括選択のチェック(`S.sel`)は別物。チェックで今の行を動かさない
- 行の並びが変わる操作(削除・結合・分割・追加・元に戻す・読み直し)の前後では `navSnapshot()` / `navRestore()` で行の id を基準に今の行を追い直す
- 行のボタンは mousedown でフォーカスを移さない(移すと前の行の操作ボタンが消えて一覧がずれ、押し損じる)。今の行は click で切り替える
- 行の追加は前後のすき間に置く。すき間が無いときは仮の 1.5 秒で置き、重なりは時刻の欄を赤く(`.times.ovl`)して知らせる。`sortSegs()` は開始時刻だけの安定ソート
- 評価用(evalSet)の文字起こしは、学習・辞書・提案に使わない(精度を測るためだけ)。
  評価用のフォルダ(`evalDirs`。v0.32.0)の中の動画の文書は、評価用の印を外せない(サーバーが書き込みのたびに付け直す)。評価用の印を外す経路を足すときは `in_eval_dir` を通す
  「声を覚える」も断る(段1・監査02。`validate_voice_learn`・`run_voice_learn`(待っている間に評価用へ変えた場合)の `eval_set` 400 と、画面のボタンを無効にしてヒントに理由)。再認識・疑わしい所の認識し直し・保管データの評価用の分け方も断っている

### v0.18.0(画面の全面見直し 段1〜3。正本は `../.design/ui-overhaul/DESIGN_BRIEF.md`・`IMPLEMENTATION.md`)
- ヘッダー: `ui-appnav`(`<nav data-ui-appnav="transcribe">`。中身は `ui-kit.js` の `UIKit.appnav` が描く「ホーム/スタジオ/編集」)が、以前のブランドの印・「他のツール」メニュー・
  「入口」リンクを置き換えた。版表示 `#ver` は appnav のすぐ右に残す(版の食い違いの赤い帯・テストが読む)。開いている動画の引き継ぎは `UIKit.appnav.setLink('studio', '?url=…')`
  (`renderDocExtras` が元の配信の URL があるときだけ呼ぶ)。⚙(`[data-ui-settings]`)は `UIKit.settings.mount({tool:$('#edSettings')})` で
  `ui-drawer` を開く(ツールの節 = 旧「表示」ポップオーバーの中身 `#vFs`/`#vVid`/`#vDense`/`#vBrk`/`autoNext` + 全体の節 = テーマ・文字の大きさ・キーの帯)。
  画面の色(`#vTheme`)は全体の節に一本化したので、1 文字起こし 側には無くなった(`syncThemeSelect()` も削除)
- 映像の上の字幕(1 文字起こし。段2): `#playerCaption`(`.tt-caption`。`aria-hidden`。装飾扱いで、同じ情報は行の一覧から読める)。
  止まっているときは選んだ行(`S.navIdx`)・再生中は再生位置の行(`S.curIdx`)を `updateCaption()` で反映する(`setNav`・`renderDoc`・`timeupdate`・`pause`・`playing` から呼ぶ)
- 画面の下の帯(`UIKit.keybar`。段2〜3): 1 文字起こし は `txKeybarScene()`(行を選んでいる/文字を直している の2場面)、2 カット は `cutKeybarScene()`
  (通常/端を選んでいる の2場面。`renderSel()` から毎回呼ぶので選択の変化にすぐ追従)、3 パック は場面を持たない(`PACK.shown()` で `clear()` するだけ)。
  `app.js` の `onEditTab()` は **`to` が cut/pack のときは何もしない**(`CUT.onShown()`/`PACK.shown()` が呼ばれた時点で、それぞれ自分の場面をもう出しているため)。
  以前は「`to !== 'tx'` かつ `from === 'tx'` なら無条件で `clear()`」にしていて、tx → cut / tx → pack で直後に出した場面を消してしまう不具合があった
  (2026-09-27、画面の見直しの e2e を書いていて見つけて直した。`to === 'tx'` のときだけ `txKeybarScene()` を呼べばよい)
- 2 カット のタイムライン(段3): 4段 → **3段**(目盛り・区間(中に波形。`#tlVideo`/`#tlAudio` を同じ帯に重ねる)・字幕)。上にミニマップ `#tlMini`
  (`renderMini()`/`drawMiniWave()`/`bindMini()`。全体を縮めた波形+見ている範囲の枠 `#tlMiniView`。枠のドラッグ = 見る範囲を移動、
  左右の端 `.tt-tl-mini-h` のドラッグ = その端だけ動かして拡大縮小、枠の外を押すとそこを中心に寄る)。
  ホイールは Ctrl 不要でマウスの位置を中心に拡大縮小(`zoom(k, anchorX)`)、Shift+ホイールで横に移動。区間の端のつまみ `.tt-h` は見た目より
  左右 6px 外側まで当たり判定がある(CSS `.tt-h.in{left:-6px}`/`.tt-h.out{right:-6px}`。幅12px の帯の中を `e.target.closest('.tt-h')` で拾う)。
  `confirmReplace()`(たたき台での置き換えの確認)は `UIKit.dialog.confirm` を呼ぶ(無ければ旧 `h.confirm` にフォールバック)
- 3 パック(段3): 主画面には「前回の設定」の要約カード(`#pkSummaryText`。fps・大きさ・予備の有無・粗編集の動画つきか・出力先 + 配信者の色の丸 `#pkSummarySw`。
  `renderSummaryText()`)と「これから作るパック」カード(字幕の見本・配信者の欄 `#pkWho`・大きな「パックを作る」)だけを出す。手順1〜3(置き先・入れるもの・出力先)の
  細かい設定は「設定を変える」`#pkSettingsBtn` で開く `ui-drawer`(`#pkSettingsDrawer`。`UIKit.drawer.open(el,{modal:true,opener})`)へ移した。
  要素の id は変えていないので、値の読み書き・イベントの配線(`setOpt` 等)は以前のまま動く。前回のパック(`#pkLast`。「前回のパック」/「作り直しが要る」の札)は
  2カラムのグリッドで要約の隣の列に出す(常に見える。開かなくても分かる)

## 未解決・注意
- 過去の事例(その後の報告なし): v0.9.6 配布時(zip で配っていた頃)、ユーザーの PC で `serve.py` 起動時に `SyntaxError: unknown parsing error`(line 0)が出たという報告があった。原因は未特定(ファイルの破損・文字コード・BOM・zip 展開の失敗などを疑う)。再発したら、まずファイルの先頭のバイト列・サイズ・文字コードを確認する
- 本物の faster-whisper での通しの確認は 2026-09-26(Windows)、声の検出のやり直し・範囲/全体の再認識は 2026-09-28 に PC で確かめた。
  フォルダ一括・評価用・句読点の除去・話者判別の優先割り込みなど、ほかの個々の機能は実機で確かめた記録がない(疑似モードのテストだけ)
- 以前ここにあった「後で実装したい」は整理済み: スタジオへ返す(統合計画の段階4)・声の登録(v0.20.0 の「話者の声」)は実装済み、
  名簿への愛称は精度改善の段1、ボーカル分離は入れない(09-27 ユーザー決定。精度改善の段3・段5 の評価で効けば再検討)
