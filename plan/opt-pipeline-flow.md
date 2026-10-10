状態(2026-10-11): 調べは済み・実装はまだ(下の「いつやるか」の合図で始める)。① の機能を 1 つずつユーザーと見ていく途中で、見つけた物はここへ足す

# OPT ① 道具・② 管理の最適化(工程をまたいだ同じ作業をまとめる)

前提: 2026-10-11 ユーザー「① や ② はどんどん最適化していきたい」「実装はいい感じのタイミングで」。RV(全体の見直し)を待たず、普段の作業の合間に段ごとに入れる(`plan/data.js` の RV の行)。調べは読むだけのサブエージェント 2 体(① Opus・② Sonnet。10-11 朝)。行数は調べた時点の目安。

## わかったこと
- 字面のコピーはほとんど無い。重複は「同じ作業を工程ごとに書き方を変えて書いている」形で、① は **ffmpeg の扱い**(探す・動かす・調べる)に集中している
- ② は **① の仕事が ② に残っている**(決まり「② に変換のコードを書かない」に反する)のと、**基盤にある部品を使っていない**所が多い。ライブ系が大きいのは重複より説明文(約 545 行)と 1 クラスに役目が詰まっているため
- 減る行は全体で 700 行前後。効くのは不具合・速さ・直しやすさ

## OPT1 すぐやる(安全・不具合つき。約 250 行減)
| 項目 | 場所 | 効き目 |
| --- | --- | --- |
| ffmpeg・ffprobe・yt-dlp の探し方を `ytt/tools` の 1 つに(ツール固有の環境変数 → YTT_ → PATH → winget) | `ytt/tools.find_ffmpeg`・`ytt/studio_env.find_tool`・`pipeline/ingest/rec_core.py`・`flow/live_archive.py`・`ytt/normalize.probe`・`tools.media_tool`、yt-dlp は STUDIO_・YTT_・TRANSCRIBE_ と無し | **不具合**: winget だけで入れた PC(友人の PC)で解析・書き出し・録画が ffmpeg を見つけられない。F1 の前に必ず |
| スタジオの書き出しに古い ffmpeg(5.1 未満)への逃げ道 = `normalize.run_with_legacy` | `pipeline/export/exporter.run_ffmpeg`、ライブの書き出しの自前の逃げ道も寄せる(`flow/live_export.py` の _encode) | **不具合**: 古い ffmpeg でスタジオの書き出しだけ落ちる |
| 解析の音量を 1 回のデコードに(asplit。配信中の検出 `measure_levels` と同じ形) | `pipeline/analyze/analyze.py` の audio_levels | 長いアーカイブの音量の段がおよそ半分の時間。上限 20dB の扱いをそろえて `test_analyze` で確かめる |
| パックの自前の書き込み・JSON 読みを `fsio` へ | `pipeline/pack/srt2resolve.py` の _replace_retry・staged・write_bytes_atomic、`cut2resolve_core.read_json_file`・_unlink_quiet | 約 50 行。もう ytt を読んでいるので写しは要らない。契約テスト |
| ② の基盤の使い忘れ | 空き容量(`fsio.existing_parent`・`_disk_usage` が 2 つ)・JSON の保存(`fsio.write_json` に fsync を足す。6 か所)・出力の確かめ(`normalize.verify`)・`start_logged` を `ytt/tools` へ・`live_tx` を `tools.run` に(取り消しが効く) | 約 60 行 |
| 小物 | ffprobe を 1 回呼ぶ所を 1 つに・SRT の時刻 2 つ・`_sec` 2 つ・区間をつなぐ 3 つ・16kHz の wav の読み 3 つ・「NFKC → 文字と数字」の寄せ方 4 つ・`diar` の定数の読み出しを ytt へ | 約 120 行。契約テスト・text_chars の NFKC の差だけ注意 |

## OPT2 形を決めて進める(約 400 行減・② が決まりどおりになる)
- ffmpeg を進み具合・取り消しつきで動かす部品 6 つ(`tools.run_progress`・`exporter._pump`・`cut2resolve_core._ffmpeg_stream`/`_ffmpeg_run`・`procs.run_capture`・`recognize.extract_audio`・`live_excite_worker.measure_levels`)→ `run_progress` に時間の上限・標準エラーを全部持つ選択・spawn の一覧に載せる選択を足して 1 つに。窓を出さない・優先度「低」を全部に。約 120 行
- ② に残る ① の仕事を ① へ: 音量とラウドネスの ffmpeg(`flow/live_export` と `exporter` → `pipeline/export/audio.py`)・ライブの切り出しのエンコード(`normalize` に区間・concat 版)・wav の取り出しの引数(`flow/live_tx`・`flow/live_archive._wav`。精密な切り方は残す)・パックの指定の組み立て(`flow/tools.py` の _pack_request など = cut2resolve の serve の写し → `pipeline/pack` に 1 つ。エラーの厳しさをどちらに合わせるか決める)
- ライブの見回りの糸の骨組み 3 つ(書き出し・取り込み・配信中の文字起こし)を小さな基底に・`Cancelled` / `Halted` を 1 組に
- `ffmpeg -i` の読み 2 つ(カバー画像の扱い)・音量の ffmpeg の引数を `ytt/loudness` へ(パックの写しが 1 回作り直し)
- 字幕の時刻が数 ms 動く所(wav の切り方をそろえる)は `src/eval/tools/eval_timing.py` で確かめてから

## OPT3 データを見てから
- かなへの寄せ方 3 つ(`llm.llm_fold`・`roster.fold`・`txbase.alt_fold`。伸ばし「ー」の扱いが違う)・Text+ の改行の文字の種類(`resolve_textplus._char_kind` と `txbase.char_class`。ヽヾ のときだけ見た目が変わる)・出力の確かめ方の厳しさ 3 つ・録画元から取ってつなぐ所 2 つ(プロセスの境目)
- ライブの大きなクラスを割る(配信後の全自動を `live_after`・マークの置き場を `live_marks` に)は行数が減らず差分が大きい = RV で

## まとめない(別物)
子プロセスの常駐と見張り(worker・各 live_*_worker・recorder)・HLS の読み方 2 つ・チャットの読み方・行の分け方と Text+ の改行と SRT の折り返し・`live_archive._wav`(8kHz・精密)と `recognize.extract_audio`(16kHz)の中身・cv 待ちと Event の見回り・③ のための素通しの動詞(層の決まり)

## いつやるか(合図)
- **OPT1**: RS7-2 のセッションの「使わないモデル・エンジンの選択肢を消す」が main に入ったら(`tx_engines`・ワーカーとぶつかるため)。RS8 と並べてよい(触るファイルが重ならない)。**F1 より前に必ず**(ffmpeg の探し方の不具合)
- **OPT2**: OPT1 のあと、F1 の前(友人の PC で動く ② を決まりどおりにしてから渡す)。RS8 がライブの書き出し・パックの口を触るならその前後で調整
- **OPT3**: V1・G2 などで採点と字幕のデータがそろってから
- 各段の終わりに層ごとの行数を WORKLOG に 1 行(数え方は 10-11 の WORKLOG)

## 機能ごとの見直しメモ(① をユーザーと 1 つずつ見て見つけた候補。直すときはここから拾う)
書き方: 候補・場所・何が良くなるか・いつ(OPT1〜3 / RV / RS8 など)。直したら行末に「済み(コミット)」

### 1. 取り込み `pipeline/ingest/`(10-11)
- ffmpeg の探し方が独自(`rec_core.py` の YTT_FFMPEG → PATH)。winget だけの PC で録画が始まらない → OPT1 の「探し方を 1 つに」に含む
- `recorder.py`(370 行)は HTTP サーバー・合言葉・設定ファイル・起動の引数を持つ独立のアプリ = ① の道具ではなく入口。`rec_core` の中身だけ ① に残し、`recorder.py` は `src/app/` の側へ → RV(フォルダの形)
- `RecError` が基盤の `ApiError` と同じこと(400・404・409 と画面に出す理由)を別に持つ(別プロセスで動くための写し)→ `ytt/errors` にそろえる。数行 → OPT1 の小物
- `sources.py`(32 行・関数 3 つ)は中身の大半が `ytt/yturl.py` へ移った残り → `yturl` か使う側へ寄せてファイルを 1 つ減らす → OPT1 の小物
- `live_align_worker.py`(音の照合)は「受け取る」工程ではなく配信後の作り直しの道具(使うのは `flow/live_archive.py` だけ)。置き場所の見直し → RV
- 録画の中心 `rec_core.py` は重複も少なく形も素直 = 動かさない

### 2. 解析(盛り上がり)`pipeline/analyze/`(10-11)
- 盛り上がりの式 `excite.py`(852 行)は配信後と配信中の 1 か所・golden で縛る・標準ライブラリだけ = 形は良い。動かさない
- `analyze.py`(881 行)の約半分(およそ 450 行)は「材料を取ってくる」仕事 = 音声のダウンロード・チャットのリプレイの取得と先読み・コメント欄(YouTube API)・付加情報(yt-dlp -J)・それぞれのキャッシュと掃除(prune_chat_cache など)。点数の計算と分けて `pipeline/analyze/fetch.py`(か `pipeline/ingest/`)へ → 解析の本体が読みやすくなる・取得だけ使い回せる → OPT2
- `analyze.py` の解析ジョブが辞書で state・phase・progress・cancel・proc を持つ = ② の仕事(ジョブの状態・取り消し)が ① に入っている。① は「入力 → 結果」の関数にして、ジョブの器は `flow/batch.py` 側へ → OPT2(RS8 と相談)
- 音量を 2 回デコード(`audio_levels` を全帯域と高音域で 2 回)→ 配信中と同じ asplit の 1 回に → OPT1(上の表にある)
- `live_excite_worker.py`(1,589 行)の小物の写し: `pid_alive`(`ytt/procs.pid_alive` と同じ)・`write_json`(`fsio.write_json` に NaN を断る選択を足せば同じ)・`append_jsonl`。もう ytt を読んでいるので写しは要らない → OPT1 の小物(約 20 行)
- `live_excite_worker.length_hint`(約 40 行)は docstring に「入口の側が呼ぶ」= 呼ぶのは `flow/live_detect.py` だけ(人の採用の記録から長さの目安を作る)。② か ⑤ の仕事が ① のワーカーのファイルにある → `flow/live_detect.py` へ → OPT2
- `live_excite_worker` の `Worker`(549 行)は「同時に 2 本まで・順番待ち・飛ばした区間の測り直し」の段取り = ② 寄りの仕事。子プロセスなので ② のファイルにはできないが、段取り(どれをいつ測るか)と計算(RecState)を分けると読みやすい → RV
- `RecorderClient`(録画元の API を読む)は入口の `Live.request` と同じ形の写し(別プロセスのため)→ 録画元の小さな口を ytt に置けば 2 か所が 1 つに → OPT3(上の表の「録画元から取ってつなぐ所 2 つ」)
- config.json の検査 `clean_*` 5 つ(約 50 行)は入口が書く設定の写しを検査し直している。入口の束(spec)の検査と同じ規則なら `flow/spec` の検査を読む形に → 調べてから(OPT2)

### 3. 書き出し `pipeline/export/`(10-11)
- `exporter.py`(997 行)に 3 つの層の仕事が混ざっている: (a) 画面の依頼の検査と組み立て(`build_spec` は store を引いてマークから組む・`build_section_spec`・`check_section_path`・`_parse_opts`・`job_public` = API の応答の形)= app / ③ の仕事、(b) ジョブの器(`start_job`・`get_job`・`cancel`・`cancel_all`・`is_busy`・糸・`run_job` の SLOTS 待ち・`_settle`)= ② の仕事、(c) 切り出し・音量・ラウドネス・つなぐ・編集用素材・.clip.json = ① の本体。① には (c) だけを「spec → 出来たファイル」の関数で残し、(a) はスタジオの serve か `human/review`、(b) は `flow` へ → OPT2(RS8 と相談。スタジオの書き出しの API の形は変えない)
- **書き出しが 2 つある**: ① の `exporter`(手元のファイル・YouTube)と ② の `flow/live_export`(録画の HLS の細切れをつなぐ)。② 側は ffmpeg の組み立てまで自前(上の OPT2「② に残る ① の仕事」)。① の書き出しに「取り元 = 録画の細切れ」を足して、切り出し → 30fps → 音量 → ラウドネス → .clip.json の流れを 1 本にする → OPT2
- **② が ① をスタジオの HTTP 越しに呼んでいる**: 配信後の作り直し(`flow/live_archive.py` の fetch)は `POST /studio/api/live/section` を呼んで待つ(409 busy・切断の待ちのループつき)。書き出しが ① に移った今は ② から直に呼べる(スタジオが動いていない headless でも作り直せる・待ちのループが消える)→ OPT2
- `manifest.py`(26 行)は ytt/schemas を「スタジオ用の名前で呼ぶ」だけの薄い入口 → 呼ぶ側(exporter と ②)が `ytt/schemas` を直に読む → OPT1 の小物
- `_pump`(進み具合つきの ffmpeg・OPT2 の 6 つの 1 つ)・`verify_output`(確かめ方 3 通り・OPT3)・古い ffmpeg への逃げ道が無い(OPT1)・音量とラウドネスの ffmpeg の引数(OPT2)は上の表に記録済み
- YouTube の区間の取り方が 2 段(yt-dlp の --download-sections → だめなら直接 URL を ffmpeg に)= 仕様どおりの予備。動かさない

### 4. 文字起こし `pipeline/transcribe/`(10-11)
- **エンジンが 6 つ**(faster-whisper・whisper.cpp・Qwen3-ASR 0.6B・SenseVoice・Qwen3-ASR 1.7B の llama.cpp・文字の LLM)。使わない物は RS7-2 のセッションが「使わないモデル・エンジンの選択肢を消す」で今消している(10-11)= ここでは扱わない。入ったあとで `tx_engines.py`(1,200 行)の残りを見直す(Qwen3 の区切りの共通部分 `_Qwen3Chunked` が 1 つのエンジンだけになるなら畳む)→ OPT1 のあと
- `worker_client.py`(881 行)に**ワーカーの中で動く物**(モデルの読み込み `_load_model_local`・使い回し `_models`・`release_idle_models`)と**サーバー側の物**(`WorkerClient` = 起動・要求・取り消し・強制終了、`RemoteModel` = 代理)が同居。名前が「client」なのに中身の半分はワーカー側 → ワーカー側を `worker.py` か `models.py` へ分ける(numpy などを読まない決まり = サーバー側に重い import を持ち込まない守りも分かりやすくなる)→ OPT2
- **認識の入口が 4 つ**: 文書全体 `transcribe_real`/`transcribe_rows`(声の検出を緩めてやり直す `transcribe_vad_fallback` つき)・範囲の再認識 `RangeRecognizer`/`range_lines_real`/`finish_range_lines`・全体の再認識 `whole_lines`(区間に分けて続きから)・選んだ行の 1 行ずつ `recognize_chunk`。どれも「wav の区間 → 整えた行」で、時刻のずらし方・行の整え方が少しずつ違う → 「区間の一覧 → 整えた行」の 1 つの関数に寄せられるか調べる(結果の行が変わると校正済みの文書と合わなくなるので eval_asr・eval_timing で確かめる)→ OPT3
- **配信中の候補の文字起こし `live_tx_worker.py`(71 行)は別の認識プロセス**(1 本ごとに起動して whisper-cli を 1 回)。編集の認識ワーカー(常駐)とは別の道。配信中は入口のプロセスから動かすため・候補は 1 時間に数本で足りるため(説明あり)。エンジンを whisper.cpp に絞ったあとなら、どちらも「whisper-cli を動かす」だけになる = 起動の仕方(引数・モデルの場所)を `tx_engines.WhisperCpp` の 1 か所から作っているか確かめる → OPT1 のあと
- 後処理 4 つ(`fill` 378・`llm` 338・`postproc` 300・`retime` 267 = 1,283 行)は役目が別(行の整え・2 つ目のエンジンとの突き合わせ・LLM・時刻)で重なりは小さい。文字の寄せ方 7 つ(上の OPT1・OPT3)だけ
- 説明文の古い呼び名: `fill.py`・`llm.py` の先頭が「「編集」のサーバーの部品」のまま(① に移った)→ 文書の小物(RV)
- `backend.py`(本物と疑似の差し込み口・本物は素通し 13 個)は疑似のテストの土台 = 残す(10-11 の調べ)

### 5. パック `pipeline/pack/`(10-11)
- 中心は `pack.py`(plan_cut = 残す区間を決める・build_pack = 書く)で、「パックを作るのは pack.py だけ」の決まりどおり。`dev/tests/test_resolve_pack_contract.py` が縛る = 形は良い
- **`pack.Request` を組む所が 3 つ**: コマンド `cut2resolve.build_request`(引数から)・cut2resolve の serve の `request_from_spec`/`output_from_spec`(画面・API から)・`flow/tools.py` の `_pack_request`(serve の写し)。上の OPT2「パックの指定の組み立て」に CLI の分も入れて `pipeline/pack` に 1 つ → OPT2
- **FCPXML は単独のコマンドからしか作られない**: 画面・② はいつも fcpxml=False(`normalize_outputs`)。FCPXML(`srt2resolve.fcpxml_skeleton`・`build_fcpxml`・`auto_cut.build_cut_fcpxml`)と単独のコマンド 2 つ(`srt2resolve.py` の run/main・`auto_cut.py` の run)は README で「残す」と決めた物(cut2resolve の README 156 行)。Resolve Free では Text+ の Lua が本流 = 今も要るかを RV の「使っていない機能を消すか」で聞く(消せば数百行)→ RV
- **`srt2resolve.py`(613 行)は「単独のコマンド」と「パック全体の土台」(probe・ms_to_frames・parse_subs・時刻の書式)が同居**。pack・core・textplus・auto_cut がみな `srt2resolve as S` を読む = 名前から役目が分からない。土台を `pipeline/pack/media.py`(調べる)・`timecode.py`(時刻)などに分け、コマンドは薄く → OPT2(FCPXML を消すかが決まってから)
- **`resolve_export.py`(378 行)に編集の画面用の物**: `edit_draft`(カットのたたき台)・`edit_preview`(これから作るパックの試算)・`build_transcript_v1`(文書 → 受け渡しの形)・`kept_spans`/「残す行」の規則。パックを作るのではなく編集の画面のための計算 = ③ か ② の仕事。`create_package`(zip にする)だけが ① → OPT2(RS8 で編集の画面を作り直すときに一緒に)
- `cut2resolve_core.Task`(進み具合・取り消し)はジョブの器の一種(書き出しの job 辞書・解析の job 辞書と同じ役目が 3 通り)→ OPT2 の「ジョブの器を ② へ」と一緒に。`pack.Cache`(試算と作成で ffprobe・無音の検出を使い回す)は画面のための物だが ① にあっても困らない = 動かさない
- 小物: 説明文の版(`cut2resolve v0.4.0`・`共通部 v0.2.0`・`srt2resolve v0.1.4`・`auto_cut v0.2.0`)は版を全体で 1 つにした今は意味がない(RV の文書)/ 手順書の文章 `resolve_textplus.instructions`(116 行)・`cut2resolve_core.build_readme`(57 行)は文章がコードの中 = 雛形のファイルに出すかは RV(行は減らない)
- 自前の書き込み・JSON 読み(OPT1)・`_ffmpeg_stream`(OPT2)・ffprobe 3 つ(OPT1)・SRT の時刻・`_sec`・区間をつなぐ 3 つ(OPT1)・文字の種類の判定(OPT3)・音量の引数(OPT2)は上の表に記録済み

- **決定 3-34(10-11 ユーザー「予備を消す」)**: パックの「予備」(EDL・カット後の SRT・予備の手順書。欄 `#pkBackup`・API と束の `backup`・`build_pack(backup=)`)を消す。RS8 で編集のパックのタブを作り直すときに欄ごと。束の `pack.backup` は読み捨ててから外す。単独のコマンドの EDL・FCPXML は RV で聞く

### ① 全体を見て(10-11)
- 5 つの工程の本体(録画の中心・盛り上がりの式・切り出し・認識・pack)はどれも 1 か所にまとまっている。散らばっているのは**周り**: ffmpeg の扱い・ジョブの器(状態・取り消し・進み具合が解析・書き出し・パックで 3 通り)・画面の依頼の検査(書き出し・パックの組み立て)・画面のための計算(resolve_export)
- 大きく効く順: (1) ジョブの器と画面の依頼を ① から出す = ① は「指定 → 結果」の関数だけに(OPT2・RS8 と相談)(2) ffmpeg の扱いを 1 つに(OPT1・OPT2)(3) 使っていない出力(FCPXML・単独のコマンド)を消すか(RV)
