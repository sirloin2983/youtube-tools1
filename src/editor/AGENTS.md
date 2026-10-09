# editor(「編集」= 文字起こし・カット・パック。2026-09-30 まで transcribe-tool)— AI 向けメモ(Claude・GPT 共通)

現在 **v0.61.0**(2026-10-09、LLM の後処理 E = `ed_llm.py`(名前は `llm_`・`LLM_`。規則の部分 `llm_fold`〜`llm_run` は編集のほかの部品を読まない = `dev/eval_llm.py` が単独で読む)。`run_job` で後処理 D のあと `llm_after_doc`: 出る人(題名・動画のパス・`stream_context` のチャンネル名とコラボ相手)の名簿の呼び名に 1 字違いの所と misrecognitions だけを `llm_pick` で選び(カタカナの呼び名はカタカナを含む所だけ・fill の行は選ばない・30 箇所まで)、選んだ所があるときだけ文字の LLM `tx_engines.LlamaText`(Qwen3-8B Q4_K_M・`LLAMA_TEXT_MODELS`・作業データの `models/llm-gguf/`・llama-server を mmproj なしで・`light`)を認識ワーカーに読み込み、ワーカーの op `complete` で行ごとに差分を聞く → `llm_guard`(行にある・候補か音が近い・字数・自信 0.5・新しい名前を持ち込まない)→ `llm_cap`(行の 15%)→ `llm_apply`(行の `fill = {from, by: "llm"}`・印 `LLM_FLAG` = 頭が FILL_NAME_FLAG と同じ「名簿の呼び名に直した」= 画面の unfill がそのまま外す)。`original` は変えない。記録 `recognition.runs[].llm`・`params.autoLlm`・生の提案 `<id>.llm.json`(`LLM_SCHEMA`。削除で一緒に消す)。設定 `autoLlm`(既定オン = decisions 3-17。評価用には当てない。画面のチェックはまだ = S3 のあと)。失敗しても文字起こしは成功(警告)。疑似は `TRANSCRIBE_FAKE_LLM`(fake = サーバーで・worker-fake = `LlamaText.FAKE_REPLY`)。`ed_learn.learn_events` は fill の行を含むまとまりを材料にしない。`LlamaQwen3` は `MODELS`・`MODEL_SUBDIR` を子クラスで差し替える形に(`_chat`・`_retry` を音声と文字で共有)。テスト `tests/test_llm.py`(test_metrics から読む)。10-09 に 22 本で CER 13.5 → 13.4%・名前 28 → 34/53 = `../../plan/llm-postfix.md` の 8)。v0.60.1 は(2026-10-09、内部の整理。動きは同じ = README の ■ v0.60.1)。v0.60.0 は(2026-10-08 夕、認識のあとの後処理 A・C・D = `ed_fill.py`(文字の少ない行の窓を SenseVoice(`tx_engines.SenseVoice`。sherpa-onnx・CPU・`light` = 主のモデルを手放さない)で読んで字数 3 倍なら置き換え・末尾の重複を捨てる・判別のあと定型の幻覚で声の無い行を捨てる `fill_clean_turns`・別のエンジンも同じ名簿の呼び名なら 1 字違いを直す)。設定 `autoFill`(既定オン。評価用には当てない)・行の `fill = {from, by}` と印 `FILL_FLAG`・画面の「別の読み」の札(`data-act="unfill"`)・記録 `recognition.runs[].fill`。10-08 の実験ループ(22 本で 13.0 → 11.1%)。ユーザー「全部入れて様子見」。テスト `test_fill.py`。下の「認識のあとの後処理」)。v0.59.8 は(2026-10-08 夕、「認識の設定」の用語集に GPU(whisper.cpp)のときの注意書き `#glossDev`(`app-core.js` の `renderOptSummary`)。whisper.cpp は `-mc 0` だと `--prompt` を使わない(10-08 の実験ループ)が、ヒントで精度は上がらなかったので渡し方は変えず案内だけ)。v0.59.7 は(2026-10-08 午後、名簿の呼び名の表記ゆれを直す = `roster.variant_pairs`(母音の長音 ↔ ー・`KANJI_VARIANTS`。`common` と 3 字未満は除く)を `ed_jobs.dict_pairs`(置換辞書 + 名簿の表。autoDict のときだけ = 評価用には当たらない)で run_job・範囲の再認識・再認識に当てる。`dict_version` の replacements のハッシュに名簿の表も入る。確かめ済み 22 本で名前 28 → 40/53・普段の文書 1045 行で変わる行 0 = `../../plan/line-b-transcription.md` の「10-08 の実験ループ」B)。v0.59.6 は(2026-10-08 昼、行を分ける文字数の既定 `SPLIT_CHARS` を 40 → 24 に(友人「字幕が長すぎる」→ ユーザー「3 段以上はやめてほしい・とりあえず 24 で」。確かめ済み 22 本で 24 は境目の的中 74%・①末 20% と 40 のまま。20 で −3 pt・16 で −8 pt = `../../plan/line-b-transcription.md` の「長い行だけ分けると」。`dev/eval_timing.py --apply` に split24)。v0.59.5 は(2026-10-08、文字起こしの行を字幕の最大文字数(縦 16)で分けるのをやめた = `split_chars_for` は設定 `subtitle.splitChars`(既定 40 = `SPLIT_CHARS`。環境変数 `TRANSCRIBE_SPLIT_CHARS`)を返し、字幕の向きでは変えない。画面の `subtitleReq` は `splitChars` を送らない。「長い行を分け直す」(`resplit_doc`)は `subtitle_max_chars`(字幕の最大文字数・向きごと = 0.59.4 までの決め方)のまま。区切りを意識した校正(確かめ済み 22 本)で 16 文字の内側の切れ目は 73% が戻された(`../../plan/line-b-row-split.md` の 8)。`dev/eval_timing.py` に行の境目の一致率(的中・再現)と `--apply` の「0.59.5」)。v0.59.4 は(2026-10-07 夜、1 秒丸めの配り直し `quant_retime` を**既定オフ**に(`TRANSCRIBE_RETIME=1` でオン)。測り直しで ①末 を悪くしたため(`../../plan/line-b-row-timing.md` の 6)。部品・記録・テストはそのまま)。v0.59.3 は(2026-10-07、UI の見直し 1 周目(基準 `docs/spec/ui-review-criteria.md`)= 文字の記号のアイコンを ui-kit v23 の `UIKit.icon`(app-core.js の `uiIcon`)と `.ui-caret` に・押せないボタンの理由(title)・要確認の札 `.seg .fl` の当たり判定 28px(`::after`)と色・処理中の札 `.tt-hjob` の点滅をやめる・`#stripBox`・`#tlMini` は A-25 の例外(`data-ui-audit-allow`)。見直し役(B)の直し: 行の「残す / カット」は 2 択(app-rows.js の `keepCutHTML`・2 カット も同じ。data-act keep/cut・keeprow/cutrow)・2 カット の I〜O を削るキーは H・確認は `UIKit.dialog.confirm`/`choose`(`#dlgConfirm`・`#dlgOverwrite` は消した)・`#cutForce` は二度押し・想定外の失敗は `ed_jobs.set_internal_error`(決まった文 + `errorDetail`)と `POST /api/jobs/retry`(文字起こしだけ)・ヘッダーの保存の状態は `paintSaveState`(2 と 3 はカットも)・`#pfStat` はやめた(数は `#pillProof`))。同じ v0.59.3 に PC 側の段9 の直しも入っている(2026-10-07、気が利く画面へ 段9 の直し = 2 カット の字幕の一覧のカット済の行の文字を 1 文字起こし と同じ `--ink-3` + 赤い取り消し線に(`index.html` の `.tt-csub.cut .tx`)・ui-kit v23 の写し(Esc のフォーカスの不具合・fps の欄の名前)。v0.59.2 は(2026-10-07、気が利く画面へ 段9 見た目の確認 = 赤い面の上の文字を ui-kit v22 の `--danger-on` に(行の札「カット済」・赤い帯の ×)・ui-kit v22 の写し。`docs/design/briefs/ux-consistency/DESIGN_REVIEW.md`)。v0.59.1 は(2026-10-07、気が利く画面へ 段7 の用語の統一 = 画面の「入口」→「ホーム」・2 カット の字幕の一覧の行の札を 1 文字起こし と同じ「残す / カット済」(`cut.js` の `.tt-csub-cut[aria-pressed]`)・ui-kit v21 の `.ui-next-btn`(履歴の `.tt-txi-next`)と `UIKit.menuOff`(`applyNeedHome` の `#docAuto`。app.js の summary の click は消した))。v0.59.0 は(2026-10-07、気が利く画面へ 段7〜8 の「編集」の分 = 下の「覚える値・次の一手(v0.59.0)」)。v0.58.3 は(2026-10-07、応答の見出しを書く処理を `ytt_core.httpsec.send` に 1 つ・版の帯の「起動し直す」に入口の notice)。v0.58.2 は(2026-10-07、「認識の設定」の `#optAutoContext` だけ変えても保存されなかった不具合を直した = 設定のチェックの change の配線を `app-core.js` の表 `SET_CHECKS` から作る(`app.js`)。長い e2e 5 本を場面ごとの関数に分けた = 下の「テストの実行」)。v0.58.1 は(2026-10-07、画面側(app*.js・cut.js・pack-tab.js・index.html の CSS)の内部の整理。見た目・操作・API の呼び方は同じ = 下の「構成」の「画面の共通の小道具」)。v0.58.0 は(2026-10-07、話者判別のしきい値の既定 0.5 → 0.6。ed_speakers の DIAR_CLUSTER_THRESHOLD)。
v0.57.2 は(2026-10-07、サーバー側(serve.py・ed_*.py・resolve_export.py など)の内部の整理。API・文書の形・設定・文字起こしの結果は同じ = 下の「構成」の「共通の小道具」)。v0.57.1 は(2026-10-07、行の時刻の原則 `../../docs/spec/row-timing-policy.md`(① 言葉が区間に収まる > ② 前後の言葉を入れない > ③ 無音を除く)に沿った後処理 = 下の「行の時刻の原則に沿った後処理」。
END_TRIM の既定を 0・続いている行をつなぐ `join_rows`・配り直しの重なりで言葉を切らない・`recognition.runs[].post`。`../../plan/line-b-row-timing.md` の 7)。
v0.57.0 は(2026-10-07、whisper.cpp の 1 秒単位に丸まった行の時刻を faster-whisper(CPU)の単語の時刻で配り直す = 下の「1 秒丸めの行の時刻の配り直し」。`../../plan/line-b-row-timing.md`)。v0.56.1 は(2026-10-06、行の BGM のメモのボタンの title に付ける基準 = app.js の `TAG_RULE`。基準の正本は `../../docs/spec/sound-tags.md`。
2列のときは行の一覧 `.tx-list` も映像の列と同じく画面に固定して列の中だけでスクロールし、再生の追いかけ・行の移動(`app-rows.js` の `ensureVisible`・`listScroller`)はその列だけを動かす = 窓は動かさない。1列は今までどおり窓。テスト `tests/e2e_follow_scroll.py`)。v0.56.0 は(2026-10-05、精度改善の追加案の 1〜5: 抜けの下書き・YouTube の字幕の候補 `ed_ytcap.py`・読む速さの印と時刻の候補 `ed_retime.py`・話者の細切れのならし(下の「追加案 1〜5」)。v0.55.0 は(2026-10-05、重なる字幕・組み込みの話者「ゲーム音声など」・行の印 `noSub`・話者の `sub`(字幕の色)・重なりの所の空の行の下書き・精度の重なりと noSub の別集計(下の「重なり・ゲーム音声など・字幕の見た目」)。v0.54.0 は(2026-10-05、評価用の動画を 1 本ずつ作り直す `POST api/eval-batch/redo-one`(`eval_batch_redo_one`・ドリルの帯の `#drRedo`・評価用の欄の `#evrRedo`。手を入れた文書は 409 touched → 確認 → force。確かめ済みは断る)。v0.53.1 は(2026-10-05、行の終わり: 音の谷へ寄せる `pull_ends` を既定でやめ(`PULL_ENDS_ON` = `TRANSCRIBE_PULL_ENDS=1` のときだけ。早めすぎて言葉の終わりが切れた = 人の直しは行き過ぎる再生の上で決めた値だった)、whisper.cpp の続いている行(すき間 `PULL_GAP` 以下)の終わりを `END_TRIM`(0.1 秒。`TRANSCRIBE_END_TRIM`)だけ早める `trim_ends`(ユーザーの目安)。v0.53.0 は(2026-10-04 夜、友人用 文字起こし簡易版を消した(ユーザー決定「いったん使わない」。画面 `lite.html`・`lite.js`・`lite-colors.json`・`ed_lite.py`(`/api/lite/…`)・`lite/` の起動・テスト `test_lite.py`・`e2e_lite.py`。git の cf617a8 までの履歴から戻せる)。残したもの: 送る用 zip の形式 `ytt_core/evaldata.py`・取り込み `dev/eval_import.py`・cut2resolve の字幕の型 lite と `video_tracks`・生出力 `<id>.asr.json`(下の「記録の土台」)・`TRANSCRIBE_CUDA_COMPUTE`。以前の簡易版の文書の印 `doc["lite"]` は読まない(`sanitize_transcript` は base の写しなので残るが、どこも見ない)・話者の `outline` は保存しなくなった。v0.52.1 は(2026-10-04 夜、2つ目のエンジンの候補 `ed_alt.run_alt` と精度を測る道具 `dev/eval_asr.py` にも本番と同じ行の後処理(長さより後ろを捨てる・whisper.cpp は行の終わりを音の谷へ。下の「行の後処理と whisper.cpp のフラッシュアテンション」)。v0.52.0 は(2026-10-04 夜、「この行だけ再生」を正確に止める `app-core.js` の `stopAtEnd`・`armPlayEnd`(timeupdate では平均 0.12 秒過ぎて次の行の頭が聞こえた)・未確認で手つかずの評価用を作り直す `POST api/eval-batch/redo`(⚙ のボタン・同じ文書 id・履歴に残す・話者判別をやり直す)。v0.51.0 は(2026-10-04 夜、whisper.cpp に既定で `-nfa`(フラッシュアテンションで large-v3 の時刻が 1 秒単位に丸まり繰り返しが増えていた)・行の後処理 `clip_rows`(長さより後ろを捨てる)・`merge_repeats`(1 文字の繰り返しをまとめる)・`pull_ends`(whisper.cpp の行の終わりを音の谷へ早める)(下の「行の後処理と whisper.cpp のフラッシュアテンション」)。v0.50.1 は(2026-10-04 夜、時刻の欄の重なりの赤い表示の直し: `app-rows.js` の `ovl` が最後/先頭の行で undefined を返し `classList.toggle` が反転していた → 真偽値で返す・表示と同じ 0.1 秒で比べる `t10`・隣と表示が同じなら値をそろえる `snapEdge`。精度の数え方で 〜・～・~ を ー と同じに(`ed_learn.norm_cer`)。v0.50.0 は(2026-10-04 夜、評価用の動画は文字起こしのあと自動で話者を判別して名前まで付ける: `ed_speakers` の `autodiar_*`(下の「話者の自動判別」)・`ed_jobs.run_job` の終わりのフック・まとめての文字起こしの後追い(`ed_evalbatch._eb_diar_pass`)・設定 `autoDiarize`(評価用でない文字起こし。既定オフ)・ドリルの帯の `#drAutoSpk`。ユーザーの要望「どうせ必要なんだから最初に全部話者認識してほしい」。v0.49.1 は(2026-10-04 夜、評価ドリルの帯に「話者を付ける…」`#drSpk`(app.js が「…」の中の「話者」= `#jumpMenu [data-jump=spDetails]` を押す)と話者の無い行の数 `#drSpkHint`(`app-learn.js` の `renderDrillSpk`。`renderDrillBar` と `renderSpAll` から呼ぶ)。ユーザーの指摘「ドリルに話者認識が見当たらない」= カードが「…」の中で見つけにくかった。v0.49.0 は(2026-10-04、2つ目のエンジンとの食い違いに候補を出す(精度改善の計画 第2版 D1-b): `ed_alt.py`・`POST api/alt`・`transcripts/<id>.alt.json`・提案の tier `alt`(札「別」)・設定 `altEngine`・`autoAlt`(下の「2つ目のエンジンの候補」)。v0.48.0 は(2026-10-04 夜、評価ドリルを動画 1 本単位・いつもの校正の画面に作り直した: `?doc=&drill=1` の帯・`api/drill/next|reviewed|unreviewed|status`・文書の印 `evalReviewed`・定点は確かめ済みの動画の長さで数える・drill.html は消した。v0.47.0 は(2026-10-04、評価用の動画のまとめての文字起こし `ed_evalbatch.py`(⚙ のボタン・少しずつ・`api/eval-batch`)・評価ドリル `drill.html`・`drill.js`・`ed_drill.py`(`api/drill/*`)と定点の「あと何分」・「全行をこの人に」(下の Q4 の2つの節)。v0.46.0 は(2026-10-04、記録の土台(マスタープラン Q2): 行の proofedAt・再認識の前の機械の結果を recognition.runs に・辞書の版・edit.json の draft・校正の手間 effort(`POST /api/effort`)・話者判別の `<id>.diar.json`(下の「記録の土台」と話者の所)。v0.45.0 は(2026-10-04、素材を 30fps にそろえる: 文字起こしのあと隣に `<名前>_30fps.mp4` を作って付け替え・選び直しは裏で・簡易版は lite-media に写し・3 パック は素材がちょうど 30fps なら 30 固定(下の「素材を 30fps にそろえる」)。v0.44.0 は(2026-10-04、評価用のフォルダの設定が空なのに「評価用」の名前のフォルダの動画を文字起こし・付け替えしようとしたら止める `ed_relink.eval_name_guard`(`eval_dir_unset`)・評価用の音声の flac を作業データの `eval-audio/` に作る `ed_evalaudio.py`(裏のスレッド・SLOTS・`GET api/eval-audio`・`TRANSCRIBE_EVAL_AUDIO=off`)・認識のワーカーのアイドル終了 60 分と「通常より下」の優先度(`git の履歴(679ff01 以前)の docs/plan/stability-review-2026-10.md`)。v0.43.0 は(2026-10-04、評価用にした文書の動画を外から評価用のフォルダへ取り込む: `ed_relink._eval_intake_pass`・`_eval_intake_one`(そろっていればメンバーのフォルダの「_NN_済」・それ以外は仮置き)・別のドライブは `_move`(コピー → 大きさ → 元を消す。消せなければコピーを消して元のまま)。いつ = `eval_settle`(裏のスレッド・応答 `intake: true`)・`eval_organize`(結果の `intaken`)。テストは test_edit の TestEvalFolder。`../../docs/spec/eval-folder.md` の「外からの取り込み」。キー配置は ? の一覧だけ・ヘッダーの明暗のボタンをやめた(ui-kit v14))。v0.42.0 は(2026-10-04、3 パック の「前回のパック」に「友人へ届ける」`#pkDeliver`: `pack-tab.js` が入口の `api/ytt/deliver`(home/deliver.py)を呼び、パックを zip にして依頼の受付の Dropbox の 出力 に置く。確認は `UIKit.dialog.confirm`・状態は `#pkDeliverMsg`。入口から開いたときだけ。テストは `e2e_edit_pack.py`)。v0.41.0 は(2026-10-04、履歴の項目を非表示に: `app-list.js` の `txFiltered`・`txRowHTML`・`renderList` が ui-kit の `UIKit.hide`(一覧の名前 `'transcripts'`。入口から開いたときだけ `available()`)を使う。「⋮」の `data-act=hide/unhide`(app.js の `#txList` のクリック)・`#txHiddenToggle`(非表示 n件を表示)・今開いている文書は隠しても除かない。覚える場所はホームの設定。テストは `e2e_ui_mounted.py`)。v0.40.1 は(2026-10-03、2 カット の保存の表示の直し: `cut.js` の `save` は `M.saving` を入れたあとで `renderSaveState` を呼ぶ。それまでは PUT を送っている間も「カットを保存しました」と出ていた。入れ直した PC で PUT が少し遅くなり `e2e_edit_cut.py` が落ちて分かった)。v0.40.0 は(2026-10-02、1 文字起こし の行の開始・終了を ui-kit の時刻の欄 `UIKit.timebox`(分:秒.0.1秒 = `data-ui-time-short`)に: `app-rows.js` の `segHTML`(`<span class="t" data-f data-ui-time>`)・`renderDoc` で `UIKit.timebox.attachAll`・確定は `#segs` の `ui-time-commit`(`app.js`。並びが変わらなければ描き直さず `markOvl` だけ)・`isTextEntry` は `.ui-time` を入力欄と同じ扱いに。テストは欄の文字を `text_content()` で読み、直すのは本物のキー入力(`e2e_row_editing.py` の `type_time`)。v0.39.0 は簡易版(v0.53.0 で消した)の書き出しで映像トラックの数 1〜5 を選ぶ: 画面 `#ltTracks`・設定 `videoTracks`(`ed_lite.load_settings`/`save_settings`・書き出しの要求でも渡して覚える)→ `pack.build_pack(video_tracks=)`。字幕は V(数+1)。v0.38.0 は精度改善の計画 段2-3: Qwen3-ASR のエンジン `tx_engines.Qwen3Asr`(0.6B・sherpa-onnx・CPU)と `LlamaQwen3`(1.7B・llama.cpp の llama-server・Vulkan)。精度を測る道具からだけ使う(画面には出さない)・測る道具に「時刻によらない CER」`doc_text`。下の「Qwen3-ASR」)。v0.37.0 は AMD などの GPU(whisper.cpp)を画面から選べる: 処理方式の `optDevice` に `vulkan`(`/api/tools` の `wcpp.ready` のときだけ app.js が足す)→ サーバーの `req_engine` が whisper.cpp にする・機器の表示は `devLabel`)。v0.36.1 は評価用の仮置きのコピー: 文書の無い仮置きの動画は、同じ名前・同じ大きさの動画を指す文書が1つだけならそれを付け替えてから移す(`ed_relink._eval_adopt_copy`・`_eval_copy_index`。`../../docs/spec/eval-folder.md`)。v0.36.0 は 精度改善の計画 段2-2: whisper.cpp(Vulkan)のエンジン `tx_engines.WhisperCpp`。下の「認識エンジンの口と全体の再認識の続きから」)。v0.35.0 は段2 の 2回目: 認識エンジンの口 `tx_engines.py` と、全体の再認識の区間ごとの保存・続きから(下の「認識エンジンの口と全体の再認識の続きから」))。v0.34.0 は友人用 文字起こし簡易版(v0.53.0 で消した): 画面 `lite.html`・`lite.js`(一本道。`git の履歴(679ff01 以前)の docs/plan/friend-lite-plan.md`)・サーバーの部品 `ed_lite.py`(`/api/lite/…`。状態・ドロップの受け取り・開始(doc["lite"] と既定の話者 = `on_new_doc`)・作業の記録 `<id>.lite-edits.jsonl`・書き出し = cut2resolve の pack(字幕の型 lite・カットなし・記号を除いた字幕)と送る用 zip(形式と規則は `ytt_core/evaldata.py`))・生出力 `<id>.asr.json`(`capture_raw`・`write_asr`・`read_asr`。単語の確信度は `seg_to_dict` の `wordProbs` = 3つ組は変えない)・`TRANSCRIBE_CUDA_COMPUTE`(`cuda_compute`)・話者の `outline`。v0.33.1 は 版の帯に「起動し直す」= `UIKit.restart.check($('#errBar'), …)`(段9 9-3。入口の api/ytt/restart-self)。v0.33.0 は評価用の仮置き: 評価用のフォルダの直下の `EVAL_STAGING`(評価用_仮置き)は名前を変えず(`_eval_videos(skip_staging)`)、`_eval_ready`(全行が校正済み・全行に話者)を満たせば、話した秒が最も長く名前がメンバーのフォルダ(`_eval_members`。「…数字_名前」)と同じ人のフォルダへ `_eval_next_name`(「_NN_済」)で `_eval_rename(…, "evalSettle")`。整理の最初の段 `_eval_staging_pass` と、画面がほかの文書へ移ったときの `POST /api/eval-folders/settle`(`eval_settle`・app.js の `evalSettle`)。v0.32.0 は評価用のフォルダ: 設定 `evalDirs`(`SETTINGS_PATCH_KEYS`。⚙ の `#evDirs`)の中の動画は `in_eval_dir` で評価用 = `validate_job`・`sanitize_transcript`・`restore_history`・`_relink_write` が evalSet を付け、`GET /api/transcript` の `evalLocked` で画面のチェックを固定。`POST /api/eval-folders/organize`(`eval_organize`。起動時は `prepare` の5秒後に1回)が「動画のフォルダ名_番号_済|未|未文字起こし」にそろえて途中のファイルの名前も変え、`_relink_write` で付け替える(失敗したら名前を戻す)。`../../docs/spec/eval-folder.md`。v0.31.0 は動画の再リンクを簡単に: 「動画を選び直す」の「参照…」= `POST /api/pick`(`ytt_core/pick.py` が別プロセスの tkinter で PC の窓を開く・一度に1つ)・履歴の上の「まとめて付け替える」`#relinkAllDlg`(`POST /api/relink/missing`・`/api/relink/find` = 選んだフォルダの中の同じファイル名。付け替えは1件ずつ既存の `/api/relink`)。v0.30.0 は段6「編集の機能を足す」: 3 パック の詳しい設定「行の後の余白」(設定 `rowEdge.padAfter`。`cut.js` の `redraftPristine`)・字幕の段の行の選択とドラッグ(`M.sel.kind === 'row'`・`applyRowEdge`。外へ広げたら `addRange` で区間も。文書とカットの元に戻すに同じ番号 = `pushUndo(seq)`/`undoDocIf`)・「再生位置でこの行を分ける」(`splitRowAt` を 1 文字起こし の分割と共用)・文書の競合の案内 `#cutDocConflict`。v0.29.0 は段5「見せ方をそろえる」: `?list=` で履歴を種類で開く・⚙ の select の幅・一覧の上の道具の折り返し。v0.28.0 は依頼の「話す人」(話者判別の 1人・names)。v0.27.0 は段4「パックの表示と出力を一致」: 設定を変えたら見積もりを出し直す(状態 P.pv)・粗編集の動画つきを覚える・出力先は覚えない・作ったときの出力の設定の記録 `pack.output` と今の設定との違い(`outputNow`/`outputDiff`)・zip に渡らない設定の説明(`ZIP_SKIPS`)・見本の話者の色は見積もりの `sampleSpeakers`。`../../docs/plan/phase4-pack-consistency.md`)。v0.26.1 はパックの音量の既定(30%)。v0.26.0 は段3「操作の一貫性」(メニューがキーを持つ間は文書のキーを止める・派生キー・キーの表示を配置から・1コマを素材の fps で・元に戻すで新しい方を戻す。`../../docs/plan/phase3-keys-undo.md`)。v0.25.0 は段2(動画を選び直す・カットの読み込み失敗の区別・URL の ?doc=・設定の保存の失敗と差のキーだけの保存)。v0.24.0 は段1(声を覚えるの安全・引き出しと Alt+数字・Shift+右クリックの行のメニュー)。v0.22.0 は精度改善の計画 段1(名簿の呼び名・配信ごとの文脈・評価用として文字起こし)と S-3(幻覚の印。下の「名簿の呼び名と配信ごとの文脈」)。
v0.21.0 = 2026-09-28、動画全体の再認識と声の検出が捨てすぎる対策(下の「再認識(範囲・全体)と声の検出のやり直し」。`../../docs/design/whole-retranscribe-design.md`)・映像の上の字幕に話者の色。
それより前の版の中身は `README.txt` の「■ v0.xx の変更」と `../../docs/WORKLOG.md`(0.16.0 = 「編集」の統合・0.11.0 = 認識のワーカー分離・0.12.0 = Resolve パックの一本化 など)。
画面の共通のルール(用語集・ヘッダー・ボタンと札・一覧・段階的に見せる・狭い画面)は `../../docs/spec/ui-guidelines.md`。画面を直すときは必ず合わせる。いま何が途中かは `../../docs/WORKLOG.md` の最後の数件で確かめる。
現行の仕様は、このファイルとユーザー向けの `README.txt`。v0.9.8 までの経緯・決定の理由は `git の履歴の docs/archive/project/HANDOVER-transcribe-tool.md`、版ごとの記録は `git の履歴の docs/archive/project/history/transcribe-tool-v*.md`、
最初の仕様は `git の履歴の docs/archive/project/transcribe-tool-spec.md`(v0.7.0 当時。**どれも古い**ので、今の動きの根拠にはしない。理由を調べるときに読む)。
使い方の説明はユーザー向けの `README.txt`(変更したら README も直す)。
**精度改善のこれからの計画は `../../plan/line-b-transcription.md`**(第2版。2026-10-04。D0・D1・E1〜E4・FT。段ごとにユーザーの承認のあとで実装)。済んだ段の記録と測った結果は `../../plan/line-b-transcription.md(付録)`(第1版。段0〜5。段ごとにユーザーの承認のあとで実装。どこまで済んだかは `../../docs/ROADMAP.md` の 線 B で確かめる。2026-10-03 時点で、段0・段1・段2 の 2-1〜2-3 は済み、次の 2-4 比較と決定は評価用の校正待ち)。
GPT の `TRANSCRIPTION_V2_DESIGN.md`(09-23)と `git の履歴の docs/archive/project/accuracy-plan.md`(09-24)はこの計画にまとめた旧計画(原則は引き継いだ・食い違う所は新しい方が正。経緯として読む)。
全体の状態(進行中・待ち・保留)は `../../docs/ROADMAP.md`。

## 精度の測定の土台(計画の段0。v0.20.1)
- 機械の出力 `original` の各行に `avg_logprob`・`no_speech_prob`・`compression_ratio`(分かるものだけ。`machine_conf`・`CONF_KEYS`)。
  文字起こしのジョブ(`run_job`)と、範囲の再認識・疑わしい所の認識し直し(`finish_range_lines` の `conf` → `replace_original_multi`)が書く。
  選んだ行の再認識(`replace_original`)はまだ書かない。画面の保存(`sanitize_transcript`)は `original` を保存済みのものから引き継ぐので消えない
- 文書の `recognition = {"runs": [{engine, engineVersion, model, device, language, settings, audioSec, wallSec, at}]}`(`recognition_run`。文字起こしのジョブだけ)。
  版は `pkg_version`(dist-info を読むだけ。サーバー側で faster_whisper を import しない)
- 単語ごとの確率はまだ残していない(単語は `(開始, 終了, 文字)` の3つ組で多くの所が分解しているため。要るときに words.json の形ごと考える)
- モデルは手元のファイルだけで先に読む(`tx_engines.FasterWhisper.create` の `local_files_only=True`。無ければネットワーク)
- 測る道具 `../../dev/eval_asr.py`(`stored` = 保存してある出力 / `run` = 認識し直す / `compare` / `list`)。作業データは読むだけ、結果は作業データの `evals/asr/`。
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
  ワーカーが落ちても server が残らないよう Windows のジョブオブジェクト(`ytt_core.tools.KillJob`。llama-server ごとに作り、`close()` で閉じたら中を終わらせる)・答えは `/v1/chat/completions` に音声(wav の base64)と assistant の先書き「language Japanese<asr_text>」→ `q3_parse`。
  server が落ちていたら起動し直して区切りを1回だけやり直す(`_decode` → `_ask` の `server_down`)。テスト: `tests/test_qwen3.py`(偽の server `tests/fake_llama_server.py`)
  **この PC(当時の 13900KF。10-04 に 12900KF に替えた)ではネイティブの部品の読み込み・起動がまれに落ちた**(sherpa-onnx の読み込み・llama-server の起動・Python 自体)ので、読み込み・起動は1回だけやり直す(10-04 の見直しでも残した: 一時的な失敗への備え・本物の失敗は2回目でそのまま出る。`git の履歴(679ff01 以前)の docs/plan/stability-review-2026-10.md`)。測った結果は計画の「4回目の結果」

## 行の後処理と whisper.cpp のフラッシュアテンション(v0.51.0。2026-10-04)
- `tx_engines.WhisperCpp.args` は既定で `-nfa`(`flash_attn()`。環境変数 `TRANSCRIBE_WCPP_FA=1` で戻す)。v1.9.4 の既定のフラッシュアテンションでは RX 7800 XT の Vulkan で行の時刻が整数秒に丸まり(`[_TT_250]` = 5.00 …)、
  繰り返しの行・音声の長さを越える行が出た。測った数字(評価用の配信 5 本 + ショート 2 本・40 秒前後): 整数秒の境目 29.2% → 11.7%・ショート 2 本の CER 9.3% → 4.9%・
  40 秒の f5d60a04a467 は 53 行(長さの外 21 行)→ 22 行。速さは 1 本 5.4 秒 → 6.6 秒。DTW(`--dtw large.v3`。`-nfa` が要る)の言葉の時刻は境目が良くならなかった(使わない)・`-sow`・`-sns`・`-et` は効かなかった
- `ed_jobs.expand_segments(gen, spec, dur=None, levels=None)`: 分けたあとに `clip_rows`(dur より後ろの行を捨て、終わりを切る。単語は捨てずに時刻を収める)→ `merge_repeats`(同じ 1 文字だけの行が `REP_ROWS` 行以上・すき間 `REP_ROW_GAP` 以下で続いたら 1 行に・
  同じ文字の続きは `REP_CHAR_KEEP` 文字まで。印は行の `_rep` → `make_flags` の「繰り返しの可能性」)→ `pull_ends`(levels があるときだけ)。
  `pull_end`: 次の行とのすき間が `PULL_GAP` 以下の行の終わりを、前 `PULL_BACK` 秒の中の音の谷(最小 + `PULL_TOL` dB 以内のいちばん後ろ)の左の端(+ `PULL_RISE` dB まで)+ `PULL_PAD` へ早める。遅くしない・次の行の始まり・文字は変えない
- 音の大きさは `WavLevels`(wave + array。numpy を使わないのでサーバー側で読める。要る所だけ読む)。`row_levels(spec, wav, base)` が **whisper.cpp のときだけ**作る
  (faster-whisper small の行の終わりは人より 0.08〜0.15 秒早く、寄せると悪くなった)。新規 = `run_job`(dur = 音声の長さ)・範囲と全体の再認識 = `RangeRecognizer.main`/`loose`・疑わしい所 = `range_lines_real`(base = チャンクの先頭が wav の何秒目か)
- 人が直したショート 2 本(d8d3b28b1bfa・b877798c24cd。35 の境目)で、機械の終わり − 人の終わり: 平均 +0.100 秒 → −0.008 秒(±0.05 秒以内 20% → 37%)。境目の音量 − 前後の谷(中央値)12.0 → 5.7 dB
- `dev/eval_asr.py` の `recognize_doc` と `ed_alt.run_alt` も `expand_segments(gen, spec, 音声の長さ, row_levels(spec, wav))` で本番と同じ後処理を通す(v0.52.1。wav の 0 秒 = 行の 0 秒なので base は 0)。
  結果に後処理の印 `post = {"clip", "mergeRepeats", "pullEnds"}`(eval_asr の run の `meta.post`・`<id>.alt.json` の `post`。pullEnds = levels を使ったか = whisper.cpp のとき)。
  `eval_asr compare` は、片方に post が無い(0.51.0 より前の測定)か中身が違う結果どうしだと、注意(`POST_NOTE`・結果の `warnings` と `postNote`)を出す = 古い測定とは比べない

## 行の時刻の原則に沿った後処理(v0.57.1。2026-10-07。`../../plan/line-b-row-timing.md` の 7・原則は `../../docs/spec/row-timing-policy.md`)
- 原則: ① 文字起こしした発言が行の区間に収まる(頭・末が切れない)> ② 前後の発言が区間に入らない > ③ 喋っていない時間を除く。迷ったら上を優先(無音を含める方が言葉を切るよりまし)
- `END_TRIM` の既定 0.1 → **0**(7-1。`trim_ends` は続いている行の終わりを早める = ① に反する)。`TRANSCRIBE_END_TRIM=0.1` で戻せる(関数・環境変数は残した)。
  `quant_is_int` は trim を足した値も見る形のまま(0 なら整数かだけ)
- **`join_rows(rows, gap=JOIN_GAP)`**(7-2。全エンジン): 0 < 次の始まり − 前の終わり ≤ `JOIN_GAP`(0.5 秒。`TRANSCRIBE_JOIN_GAP`、0 でやめる)なら前の行の終わり = 次の行の始まり。
  縮めない・重なりは触らない・最後の行はそのまま・文字と単語は変えない(延ばした所は単語の無いすき間)。かける所: `expand_segments` の最後(trim/pull のあと・句読点の除去の前。`join=True` が既定)と、
  配り直し `quant_retime` の窓の行と窓の外の前後 1 行(配り直しでできたすき間)。範囲・全体の再認識は `finish_range_lines` → `expand_segments` で通る。
  **通さない**(`join=False`): 疑わしい所の認識し直し(`range_lines_real`・疑似の redo)と 2 つ目のエンジンの候補(`ed_alt.run_alt`)= 文字を比べるだけで時刻を使わない。
  つなぐのは早めた・寄せたあとなので、`TRANSCRIBE_END_TRIM=0.1`・`TRANSCRIBE_PULL_ENDS=1` で 0.57.0 より前の形に戻すときは `TRANSCRIBE_JOIN_GAP=0` も一緒に
- 配り直しの重なり(7-3。`_quant_settle`): 候補の端が窓の中の隣の行と重なったら、その端だけ採らない(今の時刻のまま。境目は join に任せる = 聞き直した単語で言葉を「切る」向きに動かさない)。
  文字が当たらない行(候補なし)も切らない。窓の外の行とは、候補の始まり・終わりを外の行の終わり・始まりまでにとどめる(今の時刻より内側にはしない)。長さ `RETIME_MIN_LEN` 未満・今と同じ行は候補から外す
- 記録: `recognition.runs[].post = post_record() = {"version", "endTrim", "joinGap", "pullEnds", "retime"}`(`recognition_run`・`record_rerun`。生出力 asr.json の run にも入る)。
  無い記録は 0.57.0 まで。`dev/eval_timing.py` が確かめ済みの文書で ①頭・①末・②前・②次・③ を、最初の認識の engine・model と post ごとに出す(`--apply` で保存してある生出力に後処理を当て直した数字も)
- 画面: 「この行だけ再生」は、つないだ分だけ次の行の頭が少し聞こえることがある(① を優先した結果。README の ■ v0.57.1)
- 数字(10-07。確かめ済み 22 本の生出力 asr.json に後処理を当て直した = `dev/eval_timing.py --apply`。配り直しはかけない):
  0.57.0 の後処理 ①頭 18%・①末 33%・②前 13%・②次 5% → 0.57.1 ①頭 16%・①末 22%・②前 13%・②次 8%(③ 平均 0.46 → 0.52 秒)。テスト `tests/test_whispercpp.py` の `JoinRowsTest`・`QuantRetimeTest`

## 1 秒丸めの行の時刻の配り直し(v0.57.0。2026-10-07。`../../plan/line-b-row-timing.md` の案 A)
- **0.59.4 から既定オフ**(ユーザー決定 2026-10-07 夜): `QUANT_ON` は `TRANSCRIBE_RETIME=1` のときだけ True。測り直し(計画の 6 の「測り直し」)で聞き直した単語の終わりが言葉の末より早く、
  ①末 を 4 回とも悪くした(丸まった 4 本で 11% → 46%)。下の部品・記録(`retimed`・`post.retime` = False)・テスト(`QuantRetimeTest` は setUp でオンにして流す)はそのまま。次の対策は計画の 8
- 何が起きるか: whisper.cpp(large-v3・Vulkan)は**音声の中身によって** 30 秒の窓の中の行の時刻をまるごと 1 秒単位に丸める(6.00–8.00 / 12.00–14.00 …)。評価用 122 本の 27% の行・
  半分以上が丸まった文書 17 本。`-nfa` のあとも残る。同じ中身の wav でも 0.1% の違いで丸まるモードに入る。`-bs`・`-mc`・`-nth`・`-tp 0`・`-sow`・音量 ±6 dB・先頭の無音の追加では直らない
  (格子がずれるだけ)。DTW のトークンの時刻・Silero の声の区間へ寄せるのは人から遠くなった(10-06 に測った。計画の 2)。faster-whisper(CTranslate2・CPU)は丸まらず、単語の時刻は人の境目に近い
- 作り(`ed_jobs.py` の「1 秒丸めの行の時刻の配り直し」の節): `quant_windows(rows)` = 30 秒の窓(`QUANT_WINDOW`)ごとに行の境目(始まり・終わり。終わりは `END_TRIM` を足した値も = 0.57.1 から既定 0)が
  ±`QUANT_TOL`(0.011 秒)で整数の割合を数え、`QUANT_SHARE`(4 割)以上かつ行が `QUANT_MIN_ROWS`(3)以上の窓を「丸まった窓」に。隣の窓はすき間 2 秒以下ならつなぐ(上限 `QUANT_MAX_SEC`)。
  `quant_retime(rows, spec, get_words, dur, text_key, words_key)` = 窓の前後 `QUANT_MARGIN`(1 秒)を足した区間を `get_words(a, b)` で聞き直し、行ごとに `ed_retime.retime_raw`(行の文字 ↔ 単語の fitting alignment)で
  頭の字が当たれば始まり・末の字が当たれば終わりを置き換える(当たり `RETIME_MIN_MATCH` 未満・長さ `RETIME_MIN_LEN` 未満は今のまま)。重なりは 0.57.0 では「あとの行の始まりを信じて前の行の終わりを詰める」だったが、
  **0.57.1 から重なった端は採らない**(`_quant_settle`。上の節)・最後に窓の行へ `join_rows`。
  変えた行の単語は聞き直した単語に置き換える(words.json・分け直しが良い時刻を使う)。**文字は変えない**。whisper.cpp 以外・`QUANT_ON`(`TRANSCRIBE_RETIME=0` でやめる)でなければ何もしない。
  `quant_words_provider(job, spec, wav, offset)` = faster-whisper(`QUANT_MODEL`。既定 large-v3。`TRANSCRIBE_RETIME_MODEL=small` で速く)を `load_model(..., "auto", engine=faster-whisper)` で読み
  (ワーカーの中で whisper.cpp の分と入れ替わる = 次の文字起こしで whisper.cpp を読み直すが軽い)、`WavSlice` でその区間だけ `word_timestamps=True`・`vad_filter=False` で聞く。疑似のバックエンドでは何もしない(`TRANSCRIBE_FAKE_RETIME=1` で偽の単語)
- 通る所: 新規の文字起こし `run_job`(評価用の作り直しも同じ道)・範囲と全体の再認識 `RangeRecognizer.main`(行は元の動画の秒・`text_key="raw"`・`words_key="words"`)・測る道具 `dev/eval_asr.py` の `recognize_doc`。
  疑わしい所の認識し直し(`range_lines_real`・`loose`)と 2 つ目のエンジンの候補(`ed_alt`)は通さない(時刻を使わない・短い)
- 記録と知らせ: `recognition.runs[].retimed = {"windows", "rows", "spans", "model", "error"?}`(新規は `recognition_run`・再認識は `record_rerun` が `spec["_quant"]` から)。結果の注意に `QUANT_NOTE`(「… n か所(m 行)を聞き直して …」)。
  `eval_asr` の `post_meta` に `quantRetime`(モデル名 | False)= これが無い結果は 0.57.0 より前の測定(compare が違いを知らせる)
- 失敗したとき(モデルを読めない・取得できない): その窓は今の時刻のまま・`retimed.error` に理由・文字起こしは失敗にしない
- 数字: 「前」= 確かめ済み 22 本・校正済み 319 行で 始まり |差|>0.3 秒 35%・終わり 32%(10-07)。「後」は計画の 2-2 の表(実装のあとに測った)。テスト `tests/test_whispercpp.py` の `QuantRetimeTest`

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
- テスト: `test_roster.py`(test_metrics から読む)。測る道具 `../../dev/eval_asr.py run --context none|auto --temp0`

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
- 以前の簡易版の文書(印 `lite`)も普通の文書と同じく隣に作る(簡易版の `lite-media/` への写しは v0.53.0 で消した。`test_old_lite_mark_is_ignored`)
- テスト: `tests/test_normalize30.py`(test_metrics から読む)・`e2e_edit_tabs.py` の最後(別のサーバー `Server(normalize=True)`)。
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
  単独実行 `py -3.10 src/editor/ed_evalaudio.py`(serve.py を読み込んで作業データの場所を入口と同じに決める)。テストは `tests/test_evalaudio.py`(test_metrics から読む)

## 評価用の動画のまとめての文字起こし(マスタープラン Q4(b)。2026-10-04。v0.47.0)
- `ed_evalbatch.py`(`git の履歴の docs/plan/q3-q4-design.md` の (b))。評価用のフォルダ(`ed_relink.eval_dirs()`)の「評価用_仮置き」と、名前が `…_NN_未文字起こし` の動画(`eb_scan`)のうち、
  文字のある文書が無い・待っている/動いていない・済でない・あきらめていない(失敗 `EB_MAX_FAILS`=2・入れた回数 `EB_MAX_TRIES`=3)ものを `eb_candidates` で決め、
  **自分のジョブ(`spec["evalBatch"]` の印)が待ち・処理中 `EB_MAX_WAIT`(2)件になるまで**だけ `validate_job` → `add_job` する(`eb_tick`)。要求は `eb_request` = 編集の設定(`settings.json`)そのまま + `evalSet: True` + 動画全体。ヒントなしは `validate_job` の評価用の規則(`ev`)で保証(テストで固定)
- 文字の無い文書(文字起こしせずに開いた動画)だけがあるときは `intoDoc` でその文書へ入れる。ユーザーのジョブ(印の無い待ち・処理中)がある間・`ed_relink._evalorg_lock` の間・評価用のフォルダが見えない間は増やさない(見えないのは終わりにも止めにもしない)。
  残りが 0 で自分のジョブも無ければ `enabled` を外して `finishedAt`(止めるまで続く = 残りがある間)。取り消された(ユーザー)ものは入れ直さない
- 状態は作業データの `eval-batch.json`(`enabled`・`startedAt`・`enqueued`・`remaining`・`deferred`・`lastError`・`items[パス] = {tries, fails, done, error}`)。起動し直しても `enabled` なら続く(ジョブの表は空に戻るので、文書の無い動画を入れ直す)。
  別のプロセスとは `eval-batch.lock`(`ed_evalaudio._file_lock`)で重ならない。裏のスレッド `eb_start_background`(30 秒ごと・`TRANSCRIBE_EVAL_BATCH=off` で始めない)・`eval_batch_start` が起こすとすぐ見回る
- API の関数は `eval_batch_start`・`eval_batch_stop`(待っている自分のジョブだけ取り消す。動いている 1 本は最後まで)・`eval_batch_status`(`POST api/eval-batch/start|stop`・`GET api/eval-batch`)。
  **名前は serve.py が部品から集める = ほかの部品と重ならない名前(`eb_`・`EB_`・`eval_batch_`)にする**。画面は ⚙ の「評価用のフォルダ」の下(`index.html` の `#evbRow`・`app-tools.js` の `evbInit` ほか。15 秒ごとに状態を読む・404 なら出さない)。
  評価用の音声(`ed_evalaudio`)はジョブが動いている間は始めないので、まとめての文字起こしが続く間は flac が後回しになる。テストは `tests/test_evalbatch.py`(test_metrics から読む。偽のワーカー = 待機列のジョブをテストが疑似の認識で動かす)
- **話者の判別(v0.50.0)**: 自分の文字起こしの続きの判別のジョブ(`autodiar_after_transcribe`)は `spec["evalBatch"]` の印つき = 自分の待ちの数(`EB_MAX_WAIT`)に入り、「ほかのジョブ」として止まらない。
  **後追い** `_eb_diar_pass`(見回りのたびに、文字起こしの候補より先に `EB_DIAR_PER_TICK`(1)本まで): `eb_diar_candidates(tried, busy)` = 評価用・文字のある行がある・確かめ済みでない・
  **文字のある行に話者が 1 つも無い**(`ed_drill` の要約の `spkRows`)・判別したことが無い(diar.json が無い)・試していない・ジョブの最中でない・動画がある。直近 `DRILL_RECENT_SEC` に直した文書は後回し(数には入れる = 終わりにしない)。
  試した文書は `eval-batch.json` の `diar[id] = {at, via: backlog|transcribe, job?, name?, state?, error?, skipped?}`(**文書ごとに 1 回だけ**。自分の判別のジョブの結果は `_eb_absorb` が写す。待機列がいっぱい(busy)は試したことにしない)。
  終わり(enabled を外す)は、文字起こしの残り・判別の残り(`diarRemaining`)・自分の待ちが全部 0 のとき。状態の API に `diarWaiting`(自動の判別の待ち・処理中 + 後追いの残り)・`diarActive`・`diarTried`、⚙ の 1 行に「話者の判別 待ち n 本」。
  テストの `TestEvalBatch` は `TRANSCRIBE_AUTO_DIARIZE=off`(判別は `tests/test_autodiar.py`)
- **未確認の評価用の作り直し(v0.52.0。2026-10-04 ユーザー承認: v0.51.0 の直しより前に文字起こしした評価用のうち、確かめ済みでなく人が手を入れていないものは作り直してよい)**:
  - 判定 `eb_redo_why(tid, doc, busy, now, media)` → None(手つかず)か理由(`EB_REDO_LABELS`。`EB_REDO_TOUCHED` = 人が手を入れた)。手つかず = evalSet・evalReviewed なし・model あり(無ければ notTranscribed)・
    校正済みの行と音のメモ(tags)が無い・original が list で segments と行の数・各行の start/end(`EB_REDO_TIME_TOL` 0.005 秒以内)・文字が同じ・
    話者(`_eb_speaker_why`): 全部空なら手つかず(ただし今の最初の認識より後の判別が今の行に話者を付けていた = 人が外した → speaker)、話者があるなら diar.json の latest が `auto`・engine が single でない・
    行ごとの speaker が latest.rows のまま・使っている話者の名前が仮の名前(話者n)か voices.speakers[id].decided と同じで by が `EB_REDO_MACHINE_BY`(threshold・elimination・context。request = 依頼の名前は人の入力)・
    直近 `DRILL_RECENT_SEC` に updatedAt / effort.lastAt が無い・busy(ジョブの spec の tid)でない・動画がある。**迷うものは手を入れた側**(作り直さない)
  - `POST api/eval-batch/redo {dryRun}`(`eval_batch_redo`。dryRun は既定 = 数えるだけ): `{targets, touched, reasons, labels, touchedKeys, queued, added, status?}`。dryRun でなければ評価用のフォルダ・ffmpeg を確かめ、
    止まっていれば start と同じく始め(状態を数え直す)、対象(短い順)を `eval-batch.json` の `redo.queue` へ。`redo.items[id] = {at, job?, state?, skipped?, error?}`
  - 見回り `_eb_redo_pass`(話者の後追いのあと・新しい動画の文字起こしより先。待ちの数 `EB_MAX_WAIT` の中で): 入れる直前に `eb_redo_why` → 手が入っていれば skipped で外す。
    spec は `eb_redo_spec` = `eb_request`(編集の設定・evalSet)→ `validate_job`(intoDoc は渡さない = 行のある文書を断る決まりは画面からの道のまま)→ `intoDoc`・`tid`・`evalBatch`・`evalRedo` を足す
    (spec の tid で `ed_drill._busy_tids`・付け替えの `_doc_busy` が処理中と見る)。文書の範囲が全体でなければ start/end も同じ
  - `ed_jobs.run_job`: 最初に `eb_redo_skip_at_start`(もう一度判定。自分のジョブは busy から除く。手つかずなら `evalRedo.base` = 今の updatedAt)、書くときは `fill_doc` の代わりに `eb_redo_fill`
    (保存のロックの中で 動画が同じ・updatedAt が base のまま・手つかず を確かめ、違えば書かずに `job["redoSkipped"]`・「作り直しませんでした」で done。新しい文書も作らない)。
    書くもの: `hist_snapshot(force)` → `record_rerun(kind "evalRedo", replaced = 前の original)` + `replacedRun` = 前の最初の認識の記録 → fields で置き換え →
    `recognition.runs` = [新しい最初の認識(kind なし)] + 前の kind つきの記録(evalRedo を含む)・diarization・evalReviewed・resplit を消す・evalSet は True のまま。
    そのあとは普通の文字起こしと同じ(words.json・asr.json を書き直す・評価用の自動の話者判別 autodiar をもう一度。diar.json は消さない = 新しい回が latest になる)。
    **評価用の再認識を断る決まり(`validate_retranscribe`・`redo_spec`・画面)は変えていない**。この道だけが例外
  - 止める(`eval_batch_stop`)で `redo.queue` を空に(items に skipped "stopped")・待っている作り直しのジョブも取り消す。終わり(enabled を外す)は作り直しの待ちも 0 のとき。
    状態の API に `redoWaiting`(待ち + 処理中)・`redoActive`・`redoDone`・`redoSkipped`・`redoFailed`。`public_job` に `redo`・`redoSkipped`
  - 画面: ⚙ の `#evbRow` の `#evbRedo`(`app-tools.js` の `evbRedo`: dryRun → `confirmDlg` に「n 本を作り直します(手を入れた m 本は残します)…」と残す理由 → dryRun: false)・状態の 1 行に「作り直し 待ち n 本」「作り直し 済 n 本」。
    テストは `tests/test_evalbatch.py` の `test_redo_*`・`tests/e2e_eval_set.py` の最後
- **1 本ずつの作り直し(v0.54.0。2026-10-05 ユーザー要望「評価用まとめてじゃなくてひとつずつ再認識もしたい」= ドリルで校正しながら後処理の調整の効き目を 1 本ずつ確かめる)**:
  - `POST api/eval-batch/redo-one {id, baseUpdatedAt, force?}`(`eval_batch_redo_one`。`_eb_one_lock` の中で確かめてから `add_job`): 評価用でない 400 `not_eval`・確かめ済み 400 `reviewed`(force でも)・
    model なし 400 `not_transcribed`・baseUpdatedAt なし 400 / 違う 409 `conflict`・`_busy_tids` 409 `busy`・動画なし 400 `no_file`。判定は `eb_redo_why(…, media=False, recent=False)`
    (**直近に開いた・直した `recent` は見ない** = 開いている人が押す)。`EB_REDO_TOUCHED` の理由なら force のときだけ(無ければ 409 `touched` と extra `{why, label, rows, total}`。
    rows = `_eb_touched_rows` = 校正済み・音のメモ・original に同じ文字と時刻の行が無い・(話者が理由なら)話者のある行)。それ以外の理由は 400(コードは理由)。
  - spec は `eb_redo_spec` から **`evalBatch` を外す**(ユーザーのジョブ = まとめての文字起こしの待ちの数・止める・`_eb_absorb` に入らない。まとめてが enabled でなくても動く)+
    `evalRedo = {queuedAt, one: True, force, base(押したときの updatedAt), why}`。優先度は普通の文字起こしと同じ(`add_job` の transcribe)
  - 確かめ直し `_eb_one_why`(`eb_redo_skip_at_start`・`eb_redo_fill` が evalRedo.one のとき): updatedAt が base でなければ `pressedChanged`(「押したあとに直されたため」)= 書かない。
    force ならそれだけ、force でなければ今の決まり(recent は見ない)。one では skip_at_start で base を上書きしない。書く中身・履歴・runs(kind evalRedo)・話者を消して自動の判別、は同じ
  - `public_job` に `redoOne`。画面: `#drillBar` の `#drRedo`・`#evrBox` の `#evrRedo`(`app-learn.js` の `redoOneState`・`renderRedoOne`・`redoOneHere`。状態は app.js の `REDO1`。
    確かめ済み・文字起こし前・処理中は disabled と title の理由)。押す → `saveDoc()` → API → 409 touched なら `UIKit.dialog.confirm`「直した n 行は…置き換わります(以前の版に戻すで戻せます)」→ force で再送 →
    `pollJobs`。`lockJob` は `redoOne && into === S.docId` も見る(transcribe のジョブの tid は終わるまで空)= 編集を止めて `#diarBanner` に「この動画を今の設定で作り直しています」。
    終わったら `pollJobs` が `redo && tid === S.docId` で `openDoc(id, true)`(redoSkipped なら phase を知らせる)。キーは割り当てない
  - テストは `tests/test_evalbatch.py` の `test_redo_one_*`・`tests/e2e_drill.py` の最後(帯のボタン → 確認 → 作り直り → 読み直し・作り直しの間のロック)

## 評価ドリルと定点の「あと何分」・全行をこの人に(マスタープラン Q4(c)。2026-10-04。v0.47.0・**10-04 夜に動画 1 本単位・編集の画面に作り直し(v0.48.0)**)
- 仕様は `git の履歴の docs/plan/q3-q4-design.md` の (c)。サーバーは `ed_drill.py`(名前は `drill_`・`DRILL_` で始める = serve.py の `_ED_MODULES` の最後。中だけの名前も `_drill_…`)、
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
- **話者の自動判別(v0.50.0)との関係**: 判別のジョブが待ち・処理中の文書は `drill_next` の「処理中」(`_busy_tids` = ジョブの spec の tid)で出さない。文字起こしのフックは「完了」にする前に判別のジョブを足すので、間に開かれない。
  帯の `#drAutoSpk`(`renderDrillSpk`): 文書の `diarization.auto` が真なら「話者は自動で付けてあります(「名前」は動画の入ったフォルダ・配信から推測)。違っていたら直してください」(人が判別し直す・全行をこの人に で diarization が置き換わると消える)
- テストは `tests/test_drill.py`(test_metrics から読む)と `tests/e2e_drill.py`(入口に取り込んだ形。進行度のカードから始める → 1 行直してすぐ済み → 次の文書・定点の残り → 飛ばす(キー)→
  直してすぐ Shift+D → 再読み込みで続く → 話者の無い行の確認 → 次が無い → 終える・ドリルの外の確かめ済みと取り消し・全行をこの人に・? の一覧)

## 記録の土台: 文字起こし・カット・校正の手間(マスタープラン Q2。2026-10-04。v0.46.0)
機械の最初の結果を書き換えず、人の最終と並べて残す。どれも任意の項目を足すだけ(以前の文書・以前の画面で読める)・書き込みは `_save_lock` の中・**記録のために文書の updatedAt を動かさない**。テストは `tests/test_records.py`(test_metrics から読む)
- **行の `proofedAt`**(初めて校正済みにした時刻。ミリ秒): `ed_store.sanitize_transcript` が保存済み(base)の同じ id の行から引き継ぐ(画面が送った値は使わない)・
  保存済みで校正済みでなかった行は今の時刻・外した行は捨てる。この項目より前から校正済みの行には作らない(時刻なし = 以前から)。
  機械が書き換えて校正済みを外す所(`_apply_retranscribe`)は proofedAt も外す
- **再認識の前の機械の出力**: `_apply_retranscribe`(each)・`_apply_range`(range / whole)・`apply_redo`(redo)が `original` を差し替える**前**に、
  `ed_jobs.record_rerun` が `recognition.runs` に1件足す: `{"kind", "engine", "engineVersion", "model", "device", "language", "settings": {beam, vadMode, boost, wordSplit, autoDict, dict}, "range": [a, b], "spans"?(2つ以上), "replaced": [差し替えられた original の行], "replacedOmitted"?, "at"}`。
  差し替える行は `replaced_rows`(`replace_original(_multi)` と同じ「真ん中」の決まり・守った行は入れない)。上限は再認識の記録 `MAX_RERUNS`(30)件・replaced の行の合計 `MAX_REPLACED_ROWS`(20000)(古い記録から捨てる。最初の認識の記録 = kind の無いものは捨てない)。
  **runs を読むときは kind の有無で分ける**(kind が無い = 最初の認識。`runs[-1]` は再認識のあとは再認識の記録になる)
- **辞書の版** `ed_jobs.dict_version(spec)`: `{"glossary", "replacements"(autoDict), "learned"(autoLearned。規則と採用・却下の記録), "roster"(名簿のファイル)}` = 中身の SHA-256 の先頭 10 文字。
  `recognition_run` の `settings.dict`・最初の文字起こしの `params.dict`・再認識の記録の `settings.dict`
- **カットの `draft`**(初めてのたたき台): 画面(`cut.js` の `noteDraft`)がまだ1回も保存していない間に作ったたたき台(開いたときの「行から」・作り直し・行から/カットしない/無音/時刻リスト/スタジオ)の最後のものを覚え、
  初めての保存(`body(0)`)に `draft: {"origin", "settings", "keepsSec", "at"}` を添える。サーバーの `save_edit` は保存済みの edit.json が無い(壊れていた)ときだけ書き(`sanitize_draft`。正しくなければ黙って捨ててカットは保存)、以後は引き継ぐ。
  `read_edit` も draft を通す(`pack` と同じ扱い)。以前の版で作った edit.json には後から足さない。人の最終は保存したカットとパックの `cutPlan`。
  (b) `edit_draft`(GET)で書く案は採らなかった: GET で書くと edit.json ができて「たたき台のまま(pristine)」の扱い・行が変わったときの作り直しが変わるため
- **校正の手間** 文書の `effort = {"activeSec", "cutSec", "sessions", "proofedRows", "unproofedRows", "lastAt"}`: 時間は画面(app-learn.js の `effortTick`・`effortStart`・`effortFlush`。`S.eff`)が
  `S.sess.activeMs` と同じ 30 秒刻みで、1 文字起こし = activeSec・2 カット / 3 パック = cutSec にため、5 分たまったとき・`UIKit.life.onLeave`(keepalive)・別の文書を開くとき(`openDoc`)に `POST /api/effort`(`ed_store.add_effort`。1回 3600 秒まで)。
  行(proofedRows・unproofedRows)は `save_transcript` で `effort_rows` が数える。`restore_history` は effort を戻さない
- **生出力** `transcripts/<id>.asr.json`(v0.34.0 から。`ed_jobs.capture_raw`・`write_asr`・`read_asr`): 文字起こしのジョブの、分ける前・置換の前の認識の結果と単語ごとの確信度(`seg_to_dict` の `wordProbs`。words の3つ組は変えない)。
  簡易版の送る用 zip の元だったが、v0.53.0 で簡易版を消したあとも機械の最初の結果の記録として書き続ける(単語の確信度はここにしか無い)。今は読む所が無い(`read_asr` はテストだけ)。文書の削除で一緒に消す

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
  `run_job` の終わりに `alt_after_transcribe` が alt のジョブを足す(始められなくても文字起こしは成功のまま・`job["warnings"]` に理由)
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
- 測る道具 `../../dev/eval_alt.py`(2026-10-04 夜。読むだけ): 機械の最初の出力 `original` に対して `alt_diffs` で候補を出し直し、人の最終と比べて 当たり / 外れ(人はそのまま)/ 別の直し / 分からない(校正済みでない)に分ける・
  人の直しのうち候補が同じ所に出ていた割合(拾えた率。12 字以下の短い直しだけの数も)・採否の記録 `fb["alt"]`・出さなかった数の内訳。判定できた候補が 100 未満は「まだ少ない」。
  校正の手間(1 分の動画に何分・直しの量・エンジンや候補の有無ごと)は `../../dev/eval_effort.py`(文書の `effort` を読む)
- これから(計画 D1-b): 印の当たり率(`fb["alt"]` と、普段の校正で人が直した所に印があった割合)を測って既定を決める。名簿の呼び名と一致するときだけ自動で採るのは当たり率を見てから(E3)

## 重なり・ゲーム音声など・字幕の見た目(v0.55.0。2026-10-05。計画 `../../plan/line-b-overlap.md` の 6・7 と `../../docs/spec/friend-intake.md`)
- **組み込みの話者「ゲーム音声など」**: `ed_state.OTHER_SPK_ID = "other"`・`OTHER_SPK_NAME`・`OTHER_SPK_BUILTIN`・`OTHER_SPK_COLOR`・判定 `other_speaker(sp)`(id で)。JS は app.js の `OTHER_SP`・`isOtherSp`。
  文書の中の形 `{"id": "other", "name": "ゲーム音声など", "color": …, "builtin": "other"}`(話者の並びの最後。Alt+数字・数字キーの番号と 20 人の数に入れない)。話者の選択に常に出す(話者なし → ゲーム音声など → 文書の話者)。
  **自動では付けない**(手動だけ。自動の条件は、付けた記録がたまってから測る = 計画 6-2 の 3)。声を覚えない(`GENERIC_SPK_NAMES`・`voice_learn_plan`)・`recognize_voices`・`autodiar_*` は名前を付けない・話した秒に数えない
- **行の印 `noSub: true`(字幕に出さない)**: 話者とは別の項目(真のときだけ持つ。判定 `ed_state.no_sub_row`)。ゲーム音声などを選ぶとオン・そこから別の話者へ変えるとオフ・行のボタン(`data-act=nosub`)と右クリックでどの行でも切り替え。
  出さない: 映像の上の字幕・SRT・VTT・パック(transcript/v1 に `noSub` を載せ、cut2resolve の `pack.row_has_caption` が字幕を作らない)。**カットの「残す」には数える**(`kept_spans`・`rowCutFlags`・`edit_cut_flags` は変えない)。
  テキスト・JSON の書き出しには残す。件数は `#exNoSub`・3 パック の `#pkNoSub`。`original` は変えない。学習・辞書・提案・保管(`role: "nosub"`)・精度の本体から外す(`ed_learn.split_nosub`・`_prep_main`。精度は `noSub = {rows, sec, machineChars}` を別に)。
  評価用の作り直しの判定 `eb_redo_why` は noSub があれば人が手を入れた側
- **話者の `sub`(字幕の見た目。今は色だけ)**: `speakers[].sub = {"color": "#RRGGBB"}`(画面の行の色 `color` とは別)。検査は `ed_store.sanitize_sub_style` の許可の一覧 `SUB_STYLE_KEYS`(フォントなどを足すときはここに鍵を足す。知らない鍵は捨てる)。
  `POST /api/speakers/sub {"id", "styles": {名前: {"color"}}}` → `{"ok", "applied"}`(`ed_speakers.speakers_sub_apply`。名前は NFKC・空白を寄せて同じときだけ・404/400/409 busy。入口のまとめて実行が友人の依頼の色を入れる)。
  色の優先: `sub.color` → メンバーカラー → 配信者の色(`speakerColor`・`speakerColorByName`。スイッチを切っていても効く)。3 パック は `output.speakerStyles = {名前: {"color"}}`(色のある話者がいなければ鍵ごと送らない。記録 `pack.output`・`outputDiff`)・zip は `resolve_export.speaker_sub_colors`
- **重なる行**: 時刻の欄の赤 `ovl`(app-rows.js)は、同じ話者どうし・話者の無い行との重なりだけ(違う話者・noSub・空の下書きは赤くしない)。映像の上の字幕は `capStack`・`paintCaps`(`CAP_OVERLAP_MIN` 0.3 秒・`CAP_MAX_STACK` 3。1 文字起こし と 2 カット で同じ関数。再生中の行 `S.curIdx` は 1 つのまま)。
  パックの段分けは cut2resolve の `resolve_textplus.stack_captions`(見積もりの `captionLanes`・`captionsStacked`・`captionsTrimmed`・`noSubRows` を `edit_preview` がそのまま返す)
- **判別のやり直しで守る行** `ed_speakers.diar_keep_row`: noSub の行・ゲーム音声などの行・音のメモ `overlap` 付きで話者のある行・空の下書き。話者を変えない(id が新しい判別とぶつかれば `S2p` のように付け替え。1 人指定は同じ名前をまとめる)
- **重なりの所の空の行の下書き**: `GET /api/overlap-drafts?id=`(読むだけ。`ed_speakers.ovdraft_for_doc`・`ovdraft_candidates(doc, latest)`)= 判別の声の区間のうち、主の話者(合計がいちばん長いラベル)でなく、
  (a) `labelMap` に無いラベル(行が付かなかった声。話者は空・why unassigned)か (b) `overlaps` に入っていてその話者の行が半分以上を覆っていない区間(why overlap)。`OVDRAFT_JOIN` 0.3・`OVDRAFT_MIN` 0.5・`OVDRAFT_MAX` 40・`OVDRAFT_COVER` 0.5。
  画面は話者のカードの `#ovdBox`(`app-jobs.js` の `ovd*`・`ovdPlace` = 保存 → 数え直す → 確認 → **画面で行を足す**(元に戻す 1 回)。サーバーに行を作る API は無い)。足す行 = `{text: "", tags: ["overlap"], draft: "overlap"}`。
  行の印 `draft`(`ed_state.ROW_DRAFT_KINDS`・`blank_draft_row`): 文字を打ったら画面が外す(`clearDraftMark`)・空のままは字幕・カット・パック・精度(`ed_learn._prep`)に出ない・絞り込み `draft`・
  確かめ済みの文書では置けない・「済みにする」の前に空のままを消す確認。打った行は、あとで声の分離を測るときの正解(計画 6-3 の 5)
- **精度の重なりの別集計**(`ed_learn.is_overlap_group`・`overlap_best_counts`。違う話者で `OVERLAP_SEC` 0.3 秒以上・印 overlap は条件にしない・並べ方を入れ替えた小さい方): `dev/eval_asr.py` の `summary.overlap`・`nonOverlap`・`noSub`。**主な数字は変えていない**。エンジンを比べるとき(G1)は nonOverlap も見る
- テスト: `tests/test_voices.py` の `TestOtherVoice`・`tests/test_nosub_metrics.py`・`tests/test_ovdraft.py`(どれも test_metrics から)・`e2e_row_editing.py` の 17c・17-2・`e2e_edit_pack.py`

## 追加案 1〜5(v0.56.0。2026-10-05。優先度と本物のデータの数字は `../../plan/line-b-extra-ideas.md`)
- **抜けの下書き**: `ed_speakers.ovdraft_candidates(doc, latest, kinds=None)` の why `missing` = ラベルごとの声の区間(主の話者も含む)から「書いてある所」(文字のある行・空の下書き・noSub・ゲーム音声など・先に決まった重なり/unassigned の候補)を引いた切れ端で、
  `OVDRAFT_MISS_MIN`(0.8 秒)以上のもの。優先は 重なり → unassigned → 抜け(同じ所を二重に出さない)。印 `draft: "missing"`(`ed_state.ROW_DRAFT_KINDS = ("overlap", "missing")`・JS は app.js の `DRAFT_KINDS`。音のメモは付けない)。
  `GET /api/overlap-drafts?id=&kinds=overlap,missing`(応答に `counts`)。画面は `#ovdBox` のチェック `#ovdKOvl`・`#ovdKMiss`。空の下書きの決まりは種類によらず同じ
- **話者の細切れをならす**(既定オフ): `ed_speakers.smooth_labels(rows, overlaps)`(純粋)・`smooth_speakers`。条件 = `DIAR_SMOOTH_SHORT` 1.2 秒未満・すき間 `DIAR_SMOOTH_GAP` 0.6 秒以下・前後が同じラベルでその行だけ違う・
  `ratio < DIAR_SMOOTH_RATIO`(0.6。`weak` は使わない = 0.8 秒未満を全部含み、本物の相づちまでならすため)・overlaps との重なり `DIAR_SMOOTH_OVL` 0.1 秒未満。守る行(`diar_keep_row`)・2 行続く所はならさない。
  **生の結果(turns・overlaps)は変えない**(下書きが読む)。記録: diar.json の `rows[id].smoothed`(label は元のまま)・`latest.smooth`・文書の `diarization.smoothed`。設定 `diarSmooth`・要求の `smooth`・`#diarSmooth`。
  測る: `../../dev/eval_speakers.py --smooth off,on`(stored は判別し直さずに計算)。テスト `tests/test_smooth.py`
- **認識のあとの後処理 A・C・D**(`ed_fill.py`。名前は `fill_`・`FILL_`。`ed_retime` の次に読む。設定 `autoFill` 既定オン・評価用には当てない。0.60.0。10-08 の実験ループ = `../../plan/line-b-transcription.md`): `run_job` で `expand_segments` のあと `fill_after_rows`(C 末尾の重複 `fill_clean_tail` → A 文字の少ない行 `fill_sparse_row`(2 秒以上・縮めた字数 1.5 字/秒未満・同じ字の繰り返しで縮む)の窓 ±0.5 秒を SenseVoice で読み `fill_apply`(字数 3 倍以上なら置き換え。行に `fill = {from, by}`))→ `_rows_to_doc`(印 `FILL_FLAG`)→ D `fill_agree_doc`(全体を読み(30 分まで)、名簿の呼び名 `fill_aliases`(3 字以上・common は除く)がそのまま出ていれば同じ時間の行の同じ長さ 1 字違いを直す。`FILL_NAME_FLAG`)。記録 `recognition.runs[].fill = {engine, windows, rows, added, dup, agree}`・`params.autoFill`。定型の幻覚(`FILL_STOCK`)で声の区間と 3 割も重ならない行は `ed_speakers._apply_diarization` の先頭で `fill_clean_turns`(autoFill の文書・機械の出力のままの行だけ。`diarization.fillDropped`)。SenseVoice が使えなければ `job["warnings"]` に出して whisper のまま(文字起こしは失敗にしない)。2 つ目のエンジンは `tx_engines.SenseVoice`(`SENSE_VOICE_MODELS` = URL・大きさ・SHA-256 固定の tar.bz2 を `models/sensevoice/` に初回だけ取る・`light = True` で `_load_model_local` が主のモデルを手放さない・トークンの時刻で行 `sv_rows`)。疑似は環境変数 `TRANSCRIBE_FAKE_FILL`(窓いっぱいの 1 行。空 = 行なし。worker-fake は `install_fakes` が `SenseVoice.FAKE_TEXT` に入れる)。画面: 行の「別の読み」の札(`app-rows.js` の `segHTML`。`data-act="unfill"` = whisper の文字に戻す。`app.js`)・`ed_store.sanitize_transcript` が `fill` を残す。whisper の生の結果 `<id>.asr.json` は後処理の前のまま(後から後処理あり/なしを測り直す)
- **YouTube の字幕の候補**(`ed_ytcap.py`。名前は `ytcap_`・`YTCAP_`。`ed_alt` の次に読む。既定オフ): `POST /api/ytcap {id}`(ジョブ kind `ytcap`・優先度 2・同じ文書で 1 つ)。断る: 評価用 400 `eval_set`・元の配信が分からない 400 `no_clip`・文字なし 400 `empty`・409 `busy`。
  取得は yt-dlp で**字幕だけ**(`--skip-download --write-subs --write-auto-subs`・json3・`--ignore-config --no-cookies` = 公開の配信だけ。非公開・限定・メンバー限定・年齢制限・配信中は断る)。配信の ID は `^[\w-]{11}$` だけ・URL は ID から自分で作る。
  配信者の字幕(ja・ja-JP)→ 自動字幕の `ja-orig`(`ja` の自動は翻訳のことがある)。配信ごとに作業データの `ytcaps/<videoId>.json`(30 日。字幕なしは 1 日)・文書ごとに `transcripts/<id>.ytcap.json`(文書は書き換えない・削除で一緒に消す)。
  時刻 = `ytt_core.schemas.clip_offset(clip)` + 文書の秒。比べ方は **`ed_alt.alt_diffs` をそのまま**(+ `clipEdge` = 切り抜きの頭と終わり・`filler` = 言いよどみを足しただけ、は出さない)。
  `GET /api/suggest` の tier `yt`(札「YT」)・応答の `yt`。優先は 学習 → alt → yt。alt と同じ直しは alt の項目に `also: ["yt"]`(札「別・YT」)。採否は `fb["yt"]`(学習の統計・`dict_version` に入れない)。設定 `autoYtcap`。
  **候補にだけ使う(正解・学習・辞書にしない)**。測る: `../../dev/eval_alt.py --source alt|yt|both`(保存した `ytcaps/` だけ・通信しない)。テスト `tests/test_ytcap.py`・偽の yt-dlp `tests/fake_ytdlp.py`(環境変数 `TRANSCRIBE_YTDLP`)・`e2e_alt.py`
- **読む速さの印**(`ed_retime.py` の `subread_*`。画面は app-rows.js の `readMark` ほか。**同じ規則** = 例は `tests/subread_cases.json` を Python と node の両方が読む): `SUBREAD_FAST_CPS` 10 字/秒を超える・`SUBREAD_SHORT_SEC` 0.5 秒未満・`SUBREAD_MIN_CHARS` 2 文字以上。
  数える字 = NFKC のあと Unicode の L・N(ー は数える)。noSub・空の下書き・カット済は対象外。設定の任意の鍵 `subtitle.read = {fastCps, shortSec}`(欄は無い)。画面: 札 `.pill.warn`・`#readCount`・絞り込み `read`・3 パック の `#pkRead`。行を書き換えない
- **時刻を言葉に合わせる**(`ed_retime.retime_candidates`・`POST /api/retime {id, rows}` = 読むだけ・words.json が無ければ `reasonCode: "no_words"`): 行の今の時刻 ±`RETIME_PAD` 1.5 秒の単語を `ed_alt.alt_fold` で寄せ、行の文字を当てる。
  出す条件 = 当たった割合 `MIN_MATCH` 0.6 以上・端の字が単語に当たった端だけ・差 0.1 秒以上・長さ 0.3 秒以上・同じ話者の行と重ならない所まで詰める。**END_TRIM はかけない**(かけると人の時刻から離れた)。エンジンで端を外す `RETIME_END_SKIP`(今は空。faster-whisper は未測定)。
  画面: 選んだ行の「時刻を言葉に合わせる」(`rt*`。候補を見せて 1 押し・元に戻す 1 回)・「まとめて ▾」の `#rtSelected`(校正済みは外す)。**自動では動かさない**。テスト `tests/test_retime.py`・`e2e_row_editing.py` の 17-3

## 覚える値・次の一手(v0.59.0。2026-10-07。気が利く画面へ 段7〜8。`../../plan/ux-stage7-9.md`・`../../docs/design/briefs/ux-consistency/`)
- **設定の鍵(編集の設定 config.json)**: `cutSilence` = `{noise, min, pad}`(2 カット の「無音 ▾」。`SETTINGS_PATCH_KEYS` = `/api/settings/patch` だけで直す・3 つそろい、範囲は cut2resolve と同じ `ed_learn.CUT_SILENCE_RANGE`。
  画面は `cut.js` の `SIL_FIELDS`・`silSetting`・`fillSil`(「無音 ▾」を開いたとき)・`saveSil`(欄を変えたとき・たたき台を作るとき。範囲の外は知らせて戻す)。入口の `home/autorun.py` の `_pack_settings` が「無音で削る」に同じ鍵を読む)。
  `diarNum`(全体)= 話者のいない文書を開いたときの話者判別の人数の初めの値(最後に選んだ人数)。書くのは `diarNumChanged` だけ(`readOpts` は書かない = 開いている文書の人数を全体に写さない)
- **文書の鍵** `diarNum`(0〜8。0 = 自動)= 文書ごとの話者判別の人数。`POST /api/doc-diarnum`(`ed_store.set_diar_num`。**updatedAt を変えない** = 人数を選んだだけで保存の競合 409・パックの「作り直しが要る」を起こさない。画面の保存 PUT は送らない = 前の値が残る)。
  画面は `app-jobs.js` の `diarNumFor(d)`(文書の値 → その文書の話者の数(組み込みの「ゲーム音声など」を除く)→ 全体の既定)・`fillDiarNum`(openDoc・applySettings。理由は `#diarNumWhy`)
- **このブラウザの鍵** `tx.last.v1` = `{id, tab}`(前回の文書とタブ。`app-list.js` の `rememberLast` = 文書を開いた・タブを移った、`renderResume` = 空の状態 `#noDocResume` の「前回の続き: ○○ の 2 カット」(loadList・closeDoc)。自動では開かない。
  サーバーの設定にしないのは、窓ごとの道すじの便利(表示の好み V と同じ)で、タブを移るたびに config.json を書かないため。再読み込みは今までどおり URL の ?doc= と #タブ)
- **次の一手**: 文字起こし完了(別の文書を開いている間)の知らせに [開く](1 本)/[履歴を見る](`pollJobs`)・校正で未校正が 0 になったら [2 カットへ](`app-rows.js` の `proofNext(before)` = 行の「校正済み」・`proofOk`・「選んだ行を校正済みに」)・
  最後の行で未校正が残れば「まだ未校正の行が N 行あります」[最初の未校正へ](`unproofedCount`・`gotoFirstUnproofed`)・パック完了の知らせに [フォルダを開く] と `#pkOpen` へのフォーカス(`pack-tab.js` の `P.focusOpen`・`openFolder`)。
  パック完了の知らせには cut2resolve の `warningLevels` が `info` の案内を積まず、`P.notes` →「前回のパック」の `#pkLastNotes`(warn は今までどおり知らせに 2 件まで)
- **押せる次の一手**: 履歴の行の「パックを作る」「作り直す」は `button.tt-txi-next[data-act=gotab][data-tab=pack]`(`#txList` のクリックで開いてそのタブへ)。行 0 の文書は `#btnTxAgain`(`data-act=txagain`)・
  2 カット の字幕の無い文書は `#cutSubs .tt-csub-totx`(`h.toTx` = `app-tools.js` の `goTxInto`: 1 文字起こし の `#btnTxInto` / `#btnTxAgain` へフォーカス)。文書へ入れる文字起こしは `app-jobs.js` の `transcribeInto(btn)` の 1 か所
- **二度目の文字起こし**(`app-jobs.js` の `askTxAgain`): 動画全体(範囲なし)で `/api/doc-for` が行のある文書を返したら `UIKit.dialog.confirm` [開く](主・Enter)[作り直す]。
  confirm は Esc もキャンセルと同じ false を返すので、開いた `dialog.ui-dialog` の `cancel` イベント(Esc)を見て「やめる」にする(ui-kit に 3 択の確認ができたら置き換える)
- **パックの作り直し**(`pack-tab.js`): 409 exists の `dir` が前回のパック `P.pack.dir` と同じ(`sameDir`。大文字小文字・区切りをそろえる)なら確認なしで force。ボタンは前回のパックがあり出力先が空欄なら「パックを作り直す(上書き)」。
  作り直しの理由は `staleWhy()`(カットが変わった = rev・保存前の変更 / 字幕が変わった = docUpdatedAt)+ 設定の違い(`outputDiff`)→ `#pkLastWhen`
- **ホームから開いていないとき**(TOKEN なし): `#txBatchBox`・`#docAuto` は隠さず `applyNeedHome`(`#txPick` を disabled・`#txBatchOff` の理由・`#docAuto > summary` に aria-disabled と title・押すと理由を知らせて開かない)
- **画面の赤い帯** `showErr(msg, {plain})`(`app-core.js`): 決まった文 + 原文は「詳しく」・[読み込み直す]・[ホームへ](合言葉のあるときだけ。`../` の data-ui-portal)・×。版の違いの帯(`UIKit.restart` の `.ui-restart-msg`)が出ている間は上書きしない。
  まだ文書の無い動画の「文字起こしをする / 文字起こしせずに開く」は `#mcTx` にフォーカス(`showMediaChoice`)
- テスト: `e2e_edit_tabs` の `_scene_next_steps`・`_scene_remember`、`e2e_edit_cut`(無音の値)、`e2e_edit_pack`(フォーカス・[フォルダを開く]・info の案内・確認なしの作り直し)、`e2e_ui_mounted`(前回の続き・確認なしの作り直しと別の場所の確認・理由・履歴のボタン・二度目の文字起こし・`#mcTx`)、
  `test_edit.py` の `test_settings_patch_cut_silence`・`test_doc_diar_num`

## 構成
- **段10(2026-10-01)で serve.py を役割ごとの部品に分けた**(`git の履歴の docs/plan/phase10-code-split.md`。動きは同じ): `ed_state.py`(置き場所・設定の値・共通の小道具・記録・作業データの切り替え)・
  `ed_store.py`(保存・履歴・編集の内容)・`ed_relink.py`(付け替え・評価用のフォルダ)・`ed_media.py`(波形)・`ed_jobs.py`(ジョブ・認識ワーカー・声の検出のやり直し・単語の時刻・再認識・疑わしい所)・
  `ed_speakers.py`(話者判別・声を覚える)・`ed_learn.py`(辞書・学習・提案・精度・基準・書き出し・保管)・`ed_misc.py`(設定の比較・clip-marker・進行度・フォルダの一括・受け渡し)・`ed_evalaudio.py`(評価用の音声 flac。上の節)・`ed_alt.py`(2つ目のエンジンの候補。上の節)・`ed_fill.py`(認識のあとの後処理 A・C・D。上の節)・`serve.py`(版・起動・HTTP の振り分け)。
  部品どうしは `ed_xxx.名前` で呼ぶたびに読む(`from … import` しない = 差し替えが効く)。**serve.py が名前の受付**: `serve.名前` は持ち主の部品から読み、`serve.名前 = …`(テストの差し替え・mock.patch.object・入口の ALLOWED_HOSTS・ワーカーの IN_WORKER)は持ち主の部品へ転送する。
  版の正は serve.py の `SERVER_VERSION`(入口が読む。部品は `ed_state.SERVER_VERSION`)。新しい名前は、役割に合う部品に書く(serve.py の名前を部品から使わない)。import のときに使ってよいのは `ed_state` の名前だけ(ほかの部品は呼ぶときに)。
  テストで serve.py を一時フォルダに写すときは `ed_*.py` も写す(各 e2e の一覧は `ed_` で始まる .py を足す形)。まとめて流す: `python dev/run_editor_suite.py`
- **共通の小道具(v0.57.2 の整理。動きは同じ)**: 新しく書くときはまずこれを使う(同じ処理を部品ごとに書き直さない)。
  `ed_state`: `unlink_quiet`(消せなくても止めない)・`file_stamp`(更新日時と大きさ = キャッシュの鍵)・`read_schema_json`(付き物の JSON = words・asr・diar・alt・ytcap の読み方)・
  `union_spans`(区間をつなぐ)・`plain_int`・`fake_sleep`(疑似のバックエンドの待ち)・`ffmpeg_info`/`duration_in`(ffmpeg -i の長さ・ストリーム)・
  `now_ms`(ミリ秒の時刻)・`env_off`(環境変数の off/0/no/false)・`norm_path`(同じ動画かを比べる鍵 = normcase(abspath))・`add_warning`(ジョブの注意を付け直す)。
  0.60.1 から `unlink_quiet`・`file_stamp`・`plain_int`・`rss_mb` は ytt_core(fsio・schemas・tools)の別名(名前は残した)。JSON の読みは `ytt_core.fsio.read_json_or`、子プロセスの窓と優先度は `tools.no_window_flags(priority="low")`、孫ごと止めるのは `tools.kill_tree`。
  `ed_store`: `write_doc`(文書の書き込みはここを通す)・`snapshot`(履歴へ。残せなくても続ける)・`backup_doc`(機械が行を書き換える前の `.bak/<id>.pre-<kind>.json` と履歴)・`summaries()`(全文書の要約と動画のパス)。
  文書の要約のキャッシュは `_summary_cache` の 1 つ(0.60.1。鍵 = パス・更新日時・大きさ)。要約に進行度 `_prog`(`ed_misc.progress_stats` が足すだけ)と評価ドリル `_drill`(`ed_drill.drill_doc_summary`。呼び名の行の数だけ `drill_docs` が今の名簿で数える)も入る =
  一覧・進行度・ドリルで文書の JSON を読むのは 1 回。文書の JSON の読み方は `_load_doc`(read_transcript・履歴も同じ)。
  `ed_jobs`: `job_errors`(ジョブの本体を with で囲む = 取り消し・ApiError・想定外を job の状態に・一時の wav を消す)・`job_done`・`tid_busy`(同じ文書の処理中)・
  `JOB_RUNNERS`(ジョブの種類 → 本体)・`ChunkModel`(行ごとの認識と、GPU が実行時に失敗したら CPU でやり直す。再認識の each と設定の比較)・`split_terms`/`glossary_of`(用語集の欄)・`engine_version`・`_fresh_id`(新しい行の id)。
  文字起こしのジョブは `run_job` → `_rows_to_doc`(行・original・単語)→ `_doc_fields`(文書の中身・recognition.runs)。範囲・全体の再認識は `run_retranscribe` → `_retranscribe_range` / `_retranscribe_each`。
  `ed_jobs`(0.60.1): `check_cancel`・`set_cancelled`・`job_temp_wav`・`job_title`・`cpu_fallback`(GPU → CPU の決まりを 1 か所に。ChunkModel は取り消しまで捕まえる今の動きを `passthrough=()` で保つ)。同時に入れない組は `EXCLUSIVE` の 1 か所(入口の検査 `validate_*` も同じ表を使う・登録は `_busy_locked`)。設定は要求の頭で 1 回読んで渡す(`glossary_of`・`auto_glossary`・`learn_rules` の `settings` 引数・`dict_pairs` の組を渡す)。`tx_engines`: `env_num`(環境変数の数)・`is_16k_mono`・`half_cpu`・SenseVoice は `_Qwen3Chunked` の子クラス(`_chunk_rows` だけ上書き)。
  `ed_alt`: `alt_cached`・`alt_spans_of`・`alt_skip`(候補の計算を覚える・出さない候補。ed_ytcap も使う)。`resolve_export`: `_source_and_pack`・`_write_transcript`(たたき台・見積もり・zip で同じ)。
  serve.py の HTTP の振り分けは表 `GET_API`・`POST_API`(パス → 関数。部品の関数は lambda の中で `ed_xxx.名前` と呼ぶたびに読む = テストの差し替えが効く)。
  新しい API はこの表に 1 行足す(zip を返す 2 つ = `_export_corrections`・`_resolve_package` と /api/settings・/api/peaks・/media だけ Handler の中)
- **画面の共通の小道具(v0.58.1 の整理。動きは同じ)**: ボタンの処理の決まった形は `app-core.js` の 1 か所を使う(同じ書き方を画面ごとに書き直さない)。
  `kickJobs`(ジョブを入れたあと = startPolling + pollJobs)・`saveFirst`(保存中なら「保存中です…」)・`saveDone`(保存できなければ「保存が終わっていません…」)・`savedFor(id)`(保存の途中・競合・別の文書なら false)・
  `savedAll`(文書とカットの両方。まとめて実行・付け替え・zip)・`showConflict`(409 の案内)・`copyPath`・`setUrlParam`(?doc= ・?drill=)・`modalOpen`(ダイアログ・引き出しが開いている = 文書のキーを止める。cut.js には h で渡す)・
  `segIndexAt`(開始が t 以前の最後の行。二分探索)・`approxLen`・`httpError`(api・apiBlob・portalApi のエラーの形)。設定のチェックは表 `OPT_CHECKS`(認識の設定 = jobOpts にも)・`SET_CHECKS`(readOpts・applySettings)。
  行の一覧の描き直し(`renderDoc`)は行のボタンの title と読む速さの基準を `rowTitles()` で 1 回だけ作って全部の行に渡す(`segHTML(s, i, T)`。DOM は前と同じ)。確認のダイアログは `askDialog`(confirmDlg・confirmOverwrite)
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
  (二重実装に戻さない。`../../docs/design/resolve-pack-unification.md`)。cut2resolve の部品は呼ばれたときに読み込み、見つける場所は
  環境変数 `YTT_CUT2RESOLVE_DIR` → `../cut2resolve`。ここに残っているのは「残す行」の規則(`is_kept`・`kept_spans`)と SRT の書式(pipeline_io が使う)
- 「編集」(文字起こし + cut2resolve の統合。`../../docs/design/edit-tool-design.md`。2026-09-26 に E1〜E6 を実装)のサーバー側(serve.py の「編集の内容」「音の波形」の節):
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
  1つの字幕の最大文字数は設定の `subtitle`(`subtitle_settings`)= パックの折り返しと「長い行を分け直す」が使う。**文字起こしの行を分ける文字数は `subtitle.splitChars`(既定 40。`split_chars_for`。0.59.5 から字幕の最大文字数とは別)**。行を分ける規則は `split_segment`(+2 文字まで許す)。細かい決まりは設計書の 12 ②。
  **再認識(範囲・全体)と声の検出のやり直し**(v0.21.0。`../../docs/design/whole-retranscribe-design.md`): `POST /api/retranscribe` の `mode` = each(行ごと)/ range / **whole**(文書の範囲全体。`ids` はサーバーが「校正済みでない行」を入れる・上限は新規と同じ `MAX_SPAN_SEC`・声の検出は明示の off 以外「弱め」・評価用は断る)。
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
すべてリポジトリ直下から流す(テストは `src/editor/tests/`。2026-09-30 に `editor/tests/` へ、2026-10-07 にコードを `src/` の下へ移した)。
```
python -m unittest src/editor/tests/test_metrics.py src/editor/tests/test_resolve_export.py src/editor/tests/test_roster.py   # サーバー側(test_backend.py・test_worker.py・test_edit.py・test_voices.py も test_metrics から読み込まれる。`test_edit` の2件は Windows のパス前提で、Windows 以外では飛ばす(段1。`home/tests/test_window.py` の窓の API の3件も同じ)。一覧の項目は test_backend の test_list_fields_for_history)
node --test src/editor/tests/test_document_save.cjs   # 保存・切り替えの競合(9件)
python src/editor/tests/e2e_proofread_accuracy.py    # 校正済み・精度・用語集・設定の比較・辞書(旧 e2e_ui_v07)
python src/editor/tests/e2e_proofread_keys.py        # 認識の設定のチェックの保存・左手のキー・表示の設定・保管・保存の競合・4000行(旧 e2e_ui_v08)
python src/editor/tests/e2e_folder_marker_range.py   # フォルダ一括・スタジオのマーク・範囲の再認識・進み具合(旧 e2e_ui_v09)
python src/editor/tests/e2e_eval_set.py              # 評価用(旧 e2e_eval_v093)
python src/editor/tests/e2e_row_editing.py           # メニュー・行の追加・重なり・Z・画面幅(旧 e2e_ui_v098)
python src/editor/tests/e2e_ui_handoff.py
python src/editor/tests/e2e_edit_tabs.py            # 「編集」E2: 3つのタブ・Alt+1/2/3・URL の #・メニューの帯・題名の行・文字起こしせずに開く(共通部分は e2e_edit_common.py)
python src/editor/tests/e2e_edit_cut.py             # 「編集」E3: カットのタブ(入口に取り込んだ形。ドラッグ・吸着・分割・削る/戻す・I/O/X・元に戻す・保存・409・カット後の再生・無音のたたき台)
python src/editor/tests/e2e_edit_voices.py          # 話者の声を覚える(A-3。名前を付ける → 覚える → 判別し直すと名前が付く → 忘れる)
python src/editor/tests/e2e_edit_pack.py            # 「編集」E4: パックのタブ(入口に取り込んだ形。カットのとおりのパック・短い区間と 60fps の注意・前回のパック・中止・Text+ なし)
python src/editor/tests/e2e_ui_mounted.py           # 入口(home/launch.py --only transcribe,cut2resolve)に取り込んだ形。CSP・合言葉・認識ワーカー(強制終了からの立ち直り)・
                                              # 履歴の一覧(配信ごと・配信者)・パックのタブ(cut2resolve の API・上書きの確認・zip)
python src/editor/tests/e2e_drill.py               # 評価ドリル(編集の画面の ?drill=1 の帯・確かめ済みの印)と「全行をこの人に」・話者の自動判別(入口に取り込んだ形。サーバー側は test_drill.py・test_autodiar.py = test_metrics から読む)
python src/editor/tests/e2e_alt.py                 # 2つ目のエンジンの候補(D1-b。聞く → 行に「別」の候補 → 採用・却下 → autoAlt → 削除で alt.json も。入口に取り込んだ形。サーバー側は test_alt.py = test_metrics から読む)
python src/editor/tests/e2e_fill.py                # 認識のあとの後処理(0.60.0。文字の少ない行が別の読みに置き換わる → 「別の読み」の札で戻す → 保存 → 元に戻す → autoFill の設定。入口に取り込んだ形。サーバー側は test_fill.py = test_metrics から読む)
python src/editor/tests/e2e_follow_scroll.py      # 再生の追いかけ・行の移動で窓が動かず、2列では行の一覧の列だけが動く(v0.56.1)
python -m unittest dev/tests/test_ui_kit_sync.py  # ui-kit.js・index.html に埋め込んだ ui-kit の CSS が正本とずれていないか
```
- e2e は serve.py を疑似モード(環境変数 `TRANSCRIBE_BACKEND=fake`)で起動して試す。ffmpeg と Playwright の chromium が必要(Playwright の入れ方: `py -3.10 -m pip install -r setup\requirements-dev.txt` → `py -3.10 -m playwright install chromium`)。この PC では `python` を `py -3.10` と読み替える(`python` は Microsoft Store の別名に当たることがある)。
  Windows のコンソールでは `PYTHONIOENCODING=utf-8` を付けて流す(付けないと ▶ などを表示できずに途中で止まる)。`e2e_ui_mounted.py` は Windows でも動く(ワーカーは PowerShell で数え、入口は Ctrl+Break で止める)
- 「編集」の e2e(`e2e_edit_*.py`)は `e2e_edit_common.py` の `Server` で起動する(ツールのファイルを拡張子でまとめて写すので、新しい .js の写し忘れが起きない。`mounted=True` で入口に取り込んだ形)
- `TRANSCRIBE_BACKEND=worker-fake` は、サーバーは本物の経路(認識ワーカーとのやり取り)を通り、ワーカーの中だけ偽のモデルを使うテスト用のモード
  (`test_worker.py`・`e2e_ui_mounted.py`・`src/home/tests/test_mount.py`)。`TRANSCRIBE_WORKER_CRASH=<n>` で n 行目のあとにワーカーを落とせる。
  `test_worker.py` は `test_metrics` から読み込まれる(上の1行のコマンドで一緒に走る)
- Playwright 同梱の chromium は H.264 を再生できない。画面で動画の再生まで確かめるテストでは、テスト用の動画を webm(VP9 + Opus)で作る
- e2e は一時フォルダに `serve.py`・`index.html`・`app.js`・**`cut.js`・`pack-tab.js`**・`ui-kit.js`・`hololive-roster.json`・**`pipeline_io.py`・`resolve_export.py`** を写して動かす
  (`pipeline_io.py`・`resolve_export.py` を写さないと、受け渡しの API・Resolve 書き出しが 500 になる。`app.js`・`ui-kit.js` を写さないと画面が真っ白になる)。
  共通部品 `../ytt_core/` は写さず、環境変数 `YTT_CORE_DIR`(ツールの親のフォルダ = `src/`。`ytt_core/layout.py` の src_root)で見つける(Resolve パッケージを作るテストでは cut2resolve も `YTT_CUT2RESOLVE_DIR` で)
  (各スクリプトの先頭で設定している。新しいテストで serve.py を写すときも同じ1行を入れる)。`.runtime/` も `YTT_RUNTIME_DIR` で一時フォルダの中に置く
  (他のテストが同時に動いていても、「他のツール」の問い合わせ(/api/siblings)が混ざらないように)
- `e2e_ui_handoff.py` … 受け渡し(?media= / ?clip=・元の配信・動画の隣に保存・409)、テーマの保存の1本化、
  他のツールのメニュー、2026-09-24 の見直しで直した画面の不具合、v0.15.0 の見直し(単体でのカットとパックの案内・選んだ行のカット・動画なし・キー操作の手がかり・? ・390px の引き出し)
- e2e は全部通ること(以前あった「版 v0.9.4 の判定は想定内の失敗」は 2026-09-26 に app.js の版を読む形に直り、もう無い)
- `e2e_proofread_keys.py` の「4000行での Alt+Enter → 次の行 0.5 秒」は、マシンの負荷で時々超える(タイミング依存)
- 長い e2e(`e2e_proofread_keys`・`e2e_row_editing`・`e2e_edit_tabs`・`e2e_edit_cut`・`e2e_edit_pack`)は場面ごとの関数 `_scene_*(cx)` に分けてある(0.58.2。`docs/spec/code-quality.md` の基準 3 = テストの関数は 400 行以下)。
  `main` はサーバーと画面の準備・場面を呼ぶ順・後片付けだけ。場面へは `cx = types.SimpleNamespace(**locals())` で main の値を渡し、場面で作ってあとの場面で使う値は場面の最後で `cx` に戻す。
  確かめを足すときは合う場面に足すか、新しい場面を作って main から呼ぶ(場面の頭で使う値を `cx` から取り出す)
- 設定のチェックは `app-core.js` の表に足すだけで、読み込み・保存・変えたら保存する配線(`app.js`)まで効く(「認識の設定」は `OPT_CHECKS` = 文字起こしの要求にも付く。保管・書き出しのチェックは `SET_CHECKS` の残り)。`e2e_proofread_keys` の `_scene_opt_checks` が、表のどのチェックも変えたらすぐ設定に入ることを確かめる
- e2e の各スクリプトは、メニューのタブで隠れるカードも操作できるように、テスト用のスタイルで全部のタブを表示している(タブ自体の確認は e2e_row_editing.py の最後)
- 見た目は共通の ui-kit(`../ui-kit/`)。`ui-kit.js` は studio と同じく `python dev/sync_ui_kit.py` で写したファイル(**手で直さない**)。
  CSS だけは画面が1ファイルの名残で index.html に埋め込み(`/* ui-kit:css:begin */…end */` の中。同じく sync_ui_kit.py で写す・手で直さない)。
  このツール固有の CSS はその後ろ(色は必ず ui-kit の変数。新しいクラスは `tt-` を付ける)
- 画面の色(テーマ)の保存は ui-kit の `ytt:theme` だけ(⚙ 設定の「テーマ」で変える。ヘッダーの明暗ボタンは ui-kit v14 でやめた)。`V`(tx.view.v1)には保存しない
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
  履歴の「選んで、まとめて実行」と同じ `pollRuns` で読み直す。2026-09-27 `git の履歴の docs/archive/followup-2026-09-27.md` の 3)
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
- **話者を測る道具 `../../dev/eval_speakers.py`(I-2a。2026-10-04 夜)**: `stored`(既定。保存してある判別の記録を人の最終と比べる)と `run`(設定を変えて判別し直して比べる)。
  - `--reviewed only|prefer|ignore`(既定 only・`--docs` のときは prefer・確かめ済みが 0 本なら ignore に戻して注意)。**数えるのは人が確かめた行だけ** = 確かめ済みの文書の行・校正済みの行・人が話者を付け替えた行(行の speaker が diar.json の rows と違う)。
    機械の下書きのまま(仮の名前か、voices の decided と同じ名前で by が threshold・elimination・context の話者で、人が確かめた行が 1 つも無い)と、確かめられない行は数えず、数だけ別に出す(`--include-draft` で以前の数え方)。
    以前は自動の判別と名前付けがそのまま正解に数えられ、100% と出ていた(評価用 106 本のうち確かめ済みは 2 本だった)
  - 重なり: 機械の mixed・overlaps(行との重なり 0.1 秒以上)を、人の行の tags の `overlap` と比べた適合率・再現率
  - `run --threshold 0.5,0.7 --num auto --emb voxceleb [--min-on] [--min-off] [--docs]`: 全部の組み合わせを、本番と同じ道(`extract_audio` → `diarize_real` → `assign_speakers`)で**道具のプロセスの中で**判別する(`ed_jobs.IN_WORKER = True`。ワーカーは起動しない)。
    行の正しさ・話者の数(機械 − 人)・60 秒未満/以上の別・かかった秒。文書・diar.json は書かない(`--json` のときだけ `evals/speakers/<日時>-run.json`)。モデルが作業データの `models\diar` に無ければ取得せずに止まる
  - そのための任意の引数: `diarize_real`・`_diarize_local` の `threshold`・`min_on`・`min_off`(検査 `diar_tune`・ワーカーの要求の鍵 `threshold`・`minOn`・`minOff` = `DIAR_TUNE`)。**渡さなければワーカーへの要求は `{wav, num, emb}` のまま・既定の値も同じ**。
    `diarize_fake` と worker-fake の偽の判別は、しきい値 1.0 以上・人数 自動で 1 人にまとめる(テスト用)。既定の値(しきい値 0.5・VOICE_MATCH・VOICE_MARGIN)は、確かめ済みの文書がたまってから決める(今は変えていない)
  - まだ入れていない案: 似た声の話者をまとめる後処理(`run_diarize` の `diarize_real` のあと・`apply_diarization` の前に、話者ごとの特徴 `embed_groups` のコサイン類似度で)。短い動画で 1 人を 2 人に分ける対策の候補。`run --merge` で測ってから
- **話者の自動判別(v0.50.0。ユーザーの要望 2026-10-04)**: 本体は `ed_speakers` の `autodiar_*`(名前は `autodiar_`・`AUTODIAR_` で始める)。新しい認識の道は作らず、今の `diarize` のジョブ(`validate_diarize` → `add_job` → `run_diarize`)を使う。
  - いつ: `ed_jobs.run_job` の終わり(文書を書いて 30fps の作り直しのあと・**「完了」にする前**)に `autodiar_after_transcribe(job, spec, tid)`。評価用(spec の evalSet)は**設定によらず常に**、
    それ以外は `spec["autoDiarize"]`(`validate_job` = 要求の真偽値か、無ければ保存した設定 `autoDiarize`。既定オフ。画面は新規の「認識の設定」の `#optAutoDiar`。`optAutoAlt` と同じ配線 = `readOpts`・`applySettings`・`jobOpts`・丸ごとの設定の保存)。
    始められなくても文字起こしは成功のまま(`job["warnings"]`)。まとめての文字起こしの後追いは上の節
  - `autodiar_enqueue(tid, batch)`: `autodiar_why_not(doc)` = empty(文字のある行が無い)・reviewed(評価用で確かめ済み)・**has_speakers(文字のある行に 1 つでも話者 = 人が付けたものを置き換えない)** なら `{"skipped"}`。
    評価用なら名前の候補 `contextName` = `ed_drill.drill_candidates(tid)["suggest"]`(覚えた声 → 動画の入ったメンバーのフォルダ → 配信の文脈。一般的な名前・仮の名前は使わない。**ジョブを足すときに決める** = 判別のあとの diar.json の近い声を候補にしない)。
    要求 = 人数 自動(0)・`recognize: True`・判別モデルは設定 `diarEmb`。spec に `auto: True`・`autoEval`・`contextName`(・`evalBatch`)。部品が無い(`autodiar_ready` = 疑似は常に・**worker-fake では使わない**(本物の経路でモデルを取りに行くため)・それ以外は `has_sherpa()`)なら
    `{"skipped": "no_sherpa"}`(ログだけ。評価用は黙って・設定でオンにした評価用でない文字起こしは警告)。環境変数 `TRANSCRIBE_AUTO_DIARIZE=off` で止まる(テスト・困ったとき用)
  - `run_diarize` の最初に `autodiar_skip_at_start`(待っている間に人が話者を付けた・確かめ済みにした → 「完了(判別しませんでした)」・`job["autoSkipped"]`)。判別は今までどおり(`apply_diarization(…, auto)` が文書の `diarization.auto` と diar.json の `latest.auto = {eval, contextName}` を書く)→
    覚えた声(`recognize_voices`。仮の名前の話者だけ)→ `autodiar_name_by_context(tid, name)`: **まだ仮の名前(話者n)の話者のうち、話した秒(文字のある行)がいちばん長い人**に名前(1 人ならその人)。
    名前がもうほかの話者に使われていれば付けない(覚えた声を優先)。保存のロックの中で読み直して書く(`recognize_voices` と同じ)・文書の `diarization.contextName`・updatedAt。
    経過は `_autodiar_record` が diar.json の `latest.voices.speakers[id]` に `decided`・`by: "context"`、`latest.voices.context = {name, speaker, reason(name_in_use・all_named・no_speakers)}`。
    判別のあとも話者の無い行(声が見つからない)は無理に埋めない。ジョブの `named` に `by`(threshold・elimination・context)を足した(画面の知らせで覚えた声と動画の手がかりを分ける `namedBy`)
  - `public_job` に `auto`・`autoSkipped`。テストは `tests/test_autodiar.py`(test_metrics から読む)・画面は `tests/e2e_drill.py` の最後(評価用として文字起こし → 自動で話者 → ドリルで開くと話者付き)
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

### v0.18.0(画面の全面見直し 段1〜3。正本は `../../docs/design/briefs/ui-overhaul/DESIGN_BRIEF.md`・`IMPLEMENTATION.md`)
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
