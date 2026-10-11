状態(2026-10-11): 調べは済み(①②③④)・実装は OPT1 から始めた(RS8 と並べて worktree で)。直す候補は機能ごとの見直しメモに足していく

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
- ffmpeg を進み具合・取り消しつきで動かす部品 6 つ(`tools.run_progress`・`exporter._pump`・`cut2resolve_core._ffmpeg_stream`/`_ffmpeg_run`・`procs.run_capture`・`recognize.extract_audio`・`live_excite_worker.measure_levels`)→ `run_progress` に時間の上限・標準エラーを全部持つ選択・spawn の一覧に載せる選択を足して 1 つに。窓を出さない・優先度「低」を全部に。約 120 行 → **済み(da6cdda。tools.run_progress 1 つ)**
- ② に残る ① の仕事を ① へ: 音量とラウドネスの ffmpeg(`flow/live_export` と `exporter` → `pipeline/export/audio.py`)・ライブの切り出しのエンコード(`normalize` に区間・concat 版)・wav の取り出しの引数(`flow/live_tx`・`flow/live_archive._wav`。精密な切り方は残す)・パックの指定の組み立て(`flow/tools.py` の _pack_request など = cut2resolve の serve の写し → `pipeline/pack` に 1 つ。エラーの厳しさをどちらに合わせるか決める) → **パックの指定は済み(53f78bb。pipeline/pack/request.py。CLI の build_request は形が違うので別のまま)**
- ライブの見回りの糸の骨組み 3 つ(書き出し・取り込み・配信中の文字起こし)を小さな基底に・`Cancelled` / `Halted` を 1 組に → **済み(79b8393。flow/live_patrol.Patrol・行は横ばい)**
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
- `analyze.py`(881 行)の約半分(およそ 450 行)は「材料を取ってくる」仕事 = 音声のダウンロード・チャットのリプレイの取得と先読み・コメント欄(YouTube API)・付加情報(yt-dlp -J)・それぞれのキャッシュと掃除(prune_chat_cache など)。点数の計算と分けて `pipeline/analyze/fetch.py`(か `pipeline/ingest/`)へ → 解析の本体が読みやすくなる・取得だけ使い回せる → OPT2 → **済み(cbc33c1。pipeline/analyze/fetch.py。877 → 428 行)**
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
- `worker_client.py`(881 行)に**ワーカーの中で動く物**(モデルの読み込み `_load_model_local`・使い回し `_models`・`release_idle_models`)と**サーバー側の物**(`WorkerClient` = 起動・要求・取り消し・強制終了、`RemoteModel` = 代理)が同居。名前が「client」なのに中身の半分はワーカー側 → ワーカー側を `worker.py` か `models.py` へ分ける(numpy などを読まない決まり = サーバー側に重い import を持ち込まない守りも分かりやすくなる)→ OPT2 → **済み(982c701。pipeline/transcribe/models.py。879 → 744 行)**
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

- **決定 3-35(10-11 ユーザー「音量だけでいい」)**: ラウドネス(LUFS)をやめて音量(%)だけに。書き出し・ライブの書き出し・パックの測る側と `ytt/loudness.py`・束の `loudness`・画面の欄(約 270 行)。既定がラウドネス −14 から音量 75% に変わる(切り抜きごとの大きさがそろわなくなる)= 実装のとき既定の % を 1 回確かめる。OPT2 の音量の段と一緒に

### ① 全体を見て(10-11)
- 5 つの工程の本体(録画の中心・盛り上がりの式・切り出し・認識・pack)はどれも 1 か所にまとまっている。散らばっているのは**周り**: ffmpeg の扱い・ジョブの器(状態・取り消し・進み具合が解析・書き出し・パックで 3 通り)・画面の依頼の検査(書き出し・パックの組み立て)・画面のための計算(resolve_export)
- 大きく効く順: (1) ジョブの器と画面の依頼を ① から出す = ① は「指定 → 結果」の関数だけに(OPT2・RS8 と相談)(2) ffmpeg の扱いを 1 つに(OPT1・OPT2)(3) 使っていない出力(FCPXML・単独のコマンド)を消すか(RV)

## ② 管理の見直しメモ(10-11。① と同じく機能ごとにユーザーと見る)

### ②-1 流れの中心 `flow/run.py`・`runqueue.py`・`spec.py`・`envelope.py`・`runlog.py`(2,521 行)
- **② が ① を「各ツールの HTTP の API を呼んで、終わるまで待つ」形で動かしている**(`Runner._poll`・`_call_when_free`・`_wait_job` と `flow/tools.py` の HttpTools)。入口の外の CLI だけは LocalTools で ① を直に呼ぶ = **道が 2 本**。① のジョブの器(状態・取り消し・SLOTS 待ち)が各ツールのサーバーの中にあるため HTTP 越しになっている。① を「指定 → 結果」の関数にしたら(① の OPT2)、② はいつも直に呼べる = HttpTools・待ちの骨組み・束 → API の本文(`spec.export_body`・`tx_opts`・`pack_output`)が要らなくなる。画面の進み具合は ② の status から出す → **② でいちばん効く候補**(OPT2 の後半・RS8 と相談。画面が今の API で進み具合を見ている所を作り直すとき)
- **段の中身が入力の種類ごとに 3 組**: 配信 `_step_*`・文書 `_doc_*`・動画ファイル `_file_*`(文字起こし 3 つ・パック 3 つ・話者 2 つ)。中身は「どの文書を対象にするか」が違うだけの所が多い → 「対象の文書の一覧 → 段」の 1 組に寄せられるか調べる → OPT2
- **流れの種類 `MODE_STEPS` が 8 つ**(full・adopted・transcribe・doc・request・file・request_auto・file_auto)。中身は段の並びの違いだけ。束の `run`(どこまで進めるか・届けるか)で表せれば種類は要らない = 封筒の `legacy.mode` を消すのと同じ話 → RV(上の RV の観点「一時の欄を正式な欄に」)
- **実行の状態が 2 つの形**: Run の欄(画面の受付から来た mode・onFail・streamer・pins など)と束。`_asked_spec`・`_with_asked`・`_pins` で欄 → 束へ写している = 受付を submit(封筒 + 束)1 つにすれば写しが消える → RV(「受付を submit 1 つに」)
- **見積もり `Queue.estimate`(47 行 + 文書 19 行)は実行と同じ規則を別に書いている**(説明に「ずれることがある」)。段の「飛ばすか」の判定を 1 つの関数にして実行と見積もりの両方から呼ぶ → OPT2 → **済み(b1df619。判定 4 つを flow/run.py に・見積もりがパックの鍵の違いも数える)**
- **継ぎ方が 3 段**: Runner ← Queue ← 入口の AutoRunner(hook を上書き。Runner の hook は 12 個)。hook の多くは「③④ の物を ② に渡す」ための口 = 層の決まりで要る。ただ継ぐより、hook をまとめた 1 つの物(ホストの口)を渡す形の方が追いやすい → RV
- `spec.py`・`envelope.py`・`runlog.py` は純粋で小さく形は良い。動かさない(envelope の legacy は RV に記録済み)

### ②-2 成果物と置き場所 `flow/keys.py`・`placement.py`・`machine.py`(1,008 行)
- **鍵を書くのが ② の段ではなく各ツールのサーバー**: 説明は「② の段が終わったところで書く」だが、実際に `write_*` を呼ぶのはスタジオの serve(`write_studio_export`)・cut2resolve の serve と LocalTools(`write_pack`)・③ の `human/proof/doc_jobs`(`write_after_transcribe`)・ライブの書き出し。① をツールのサーバーの中で動かしているため(②-1 の 1 と同じ根)。② が ① を直に呼ぶ形になれば、鍵は ② の段の終わりの 1 か所で書ける → OPT2 の後半(②-1 の 1 と一緒に)
- **鍵の材料を作るために各ツールの API の読み方を写している**: `studio_media`・`studio_export_settings`(スタジオの書き出しの spec)・`_pack_settings`・`pack_body_inputs`(「cut2resolve の API の受付と同じ読み方」)・`transcribe_req_inputs`(「編集の受付 validate_job と同じ読み方」)。API の本文から材料を読み直すのをやめ、束から材料を作れば写しが消える(約 80 行)→ ②-1 の 1 と一緒に
- **`machine.py` の engine・device は選択肢が 1 つずつになった**(0.58.0 = whisper.cpp・vulkan だけ)。今は「旧い値を読み替える」「編集の settings.json の device から既定を決める `_editor_device`」が残っているだけ。友人の PC(RTX 3060)も whisper.cpp の Vulkan で始める(F1 の決めたこと 8)= 2 つ目の選択肢ができるまで、engine・device の欄と読み替えを畳める(読むときは固定の値)。旧い値の読み替えは古い machine.json・設定が無くなったら消す → OPT1 のあと(F1 で CUDA を足すなら残す = F1 の形が決まってから)
- `diskMinGB` は「読むのは後の段」(ヘッドレスの録画は使う)。`learningDir` は既定 = 今の場所で、まだ読み手が 1 つ。使い道が増えるまでこのまま
- `placement.py` の案件の根・`studio_data` は RS8 の B-2・B-3(案件フォルダへ移す)で形が変わる = そのときに見直す。`.flow.lock` の取り方・結果の束・`case.json` は形が良い → RS8

### ②-3 段ごとの口 `flow/tools.py`・`tx.py`・`diar.py`・`batch.py`・`jobs.py`・`pack.py`・`ingest.py`・`wire.py`(1,672 行)
- **待ち行列・ジョブの仕組みが 5 つある**: ② の `runqueue.Queue`(まとめて実行)・`jobs`(編集の文字起こし・話者などのジョブの表と待機列)・`batch.Batch`(スタジオの解析の待ち行列 最大 10 本)と、① の中の書き出しのジョブ(`exporter.start_job`)・パックの `Task`。どれも「積む・1 本ずつ動かす・状態・取り消し・やり直し・履歴」を自前で持つ。① の OPT2(ジョブの器を ② へ)と合わせて、② に 1 つのジョブの仕組み(種類を登録して動かす = 今の `jobs` の形が近い)にまとめる → OPT2 の後半〜RV(画面の進み具合の出し方が変わるので RS8 と相談)
- `tools.py`(HttpTools・LocalTools)は ②-1 の 1(直に呼ぶ形)で HttpTools ごと要らなくなる。LocalTools のパックの組み立て(`_pack_request`・`_pack_args`・`_speaker_map`)は ① の OPT2「パックの指定を 1 つに」へ
- `flow/pack.py`(65 行)は ① の `resolve_export` の編集の画面用の計算(たたき台・試算・受け渡し・付け替え)を ③④ に渡す口。① の 5 の「resolve_export の画面用の計算を ① の外へ」をやると、計算の置き場所と一緒に見直す(② に置くなら口は要らない)→ OPT2(RS8)
- `tx.py`(25 の動詞)・`diar.py` は「③ は ① を直に読まない」ための口で、各動詞に「② が足すこと」が書いてあり形は良い。ほぼ素通しの数本(`check_model`・`each_lines`・`end_whole`・diar の定数の読み出し 3 本)は記録済み(OPT1 の小物)
- `diar.py` の覚えた声の置き場所(`load_voices`・`save_voices`・`voices_edit`・`merge_voice`。約 50 行)は ② の段取りではなくデータの持ち主 = ④ `manage` の仕事に近い → RV(RS8 で案件・データの置き場所を見直すときに一緒に)
- `batch.py` は説明文が古い形(「解析キュー(バッチ)」だけで層・RS の説明が無い)。中身は上の「5 つの仕組み」に含む
- `ingest.py`(22 行・関数 1 つ)は小さいが ③ が ① を読まないための口 = 残す
- `wire.py` は ③⑤ を引数で受ける登録の口で形は良い(テストの直呼び化 = 編集の serve の登録を install 1 つに、はここを使う)

### ②-4 ライブ `flow/live*.py`(5,718 行。② の半分以上)
- 大きい 4 つのクラスに役目が詰まっている: `Archiver`(1,142 行・メソッド 61。アーカイブでの作り直し P4 と配信後の全自動 M7 の `_after_*` 約 400 行が同居)・`Exporter`(828 行・44。書き出しのジョブと ffmpeg の組み立て)・`LiveSession`(704 行・59。録画元のクライアント・録画を始める・見回り・子プロセス・調子・採用の口)・`Detector`(614 行・46)。説明文が約 545 行(経緯が厚い)。重複を消しても 3〜4% = 大きく減らすには機能を見直す(下の最後)
- **ライブ側にもジョブの仕組みが 3 つ**: 書き出しのジョブ(`Exporter`。`live/exports.json`・状態 5 つ以上)・作り直し(`Archiver`。同じ exports.json の archive・状態 7 つ)・候補の文字起こし(`LiveTx` の待ち)。上の「5 つの仕組み」と合わせて 8 通り → 1 つのジョブの仕組みにまとめる話に含める(OPT2 後半〜RV)
- **マークの置き場が 2 つ**: スタジオの動画とマークの台帳(`human/review/store`)と、ライブのマークの正本 `live_export.MarkStore`(175 行)。採用は `StudioMarks`(スタジオへ)と `LocalMarks`(MarkStore へ)で両方に対応している = 友人の PC(スタジオなし)のため。RS8 でマークと候補を案件フォルダへ移す(B-3)ときに 1 つにする → RS8
- **録画元から細切れを取ってつなぐ所が 2 つ**: ② の `Exporter._fetch`(配信中の文字起こし `LiveTx` も Exporter の内側の `_fetch` を借りて使う = 名前が `_` なのに外から使う)と、① の検出のワーカーの `measure_batch`。① の書き出しに「取り元 = 録画の細切れ」を足す(① の 3)と一緒に ① の 1 か所へ → OPT2
- **yt-dlp で配信を調べる所が 2 つ**: `livesession.probe_live`(配信中か・チャンネル・題)と `live_archive._probe_once`(アーカイブがあるか・時刻・長さ)。聞く項目が違うだけで、動かし方(窓を出さない・シェルを通さない・時間の上限)は同じ → ① か ytt の 1 つの「yt-dlp で 1 回調べる」に(約 20 行)→ OPT1 の小物
- ② の調べ(10-11 朝)で記録済み: 空き容量の確かめ 2 つ・JSON の保存の手書き・古い ffmpeg への逃げ道と出力の確かめの自前・糸の骨組み 3 つ・`Cancelled`/`Halted`・音量とラウドネス(決定 3-35 でラウドネスは消える)・切り出しのエンコード・wav の引数(上の OPT1・OPT2)
- **`Archiver` を割る**: 作り直し(P4)と配信後の全自動(M7)を別のクラス・ファイル(`live_after.py`)に。`Exporter` からマークの正本 `MarkStore` と入力の検査 `check_*` を `live_marks.py` に。行は減らないが 1 つのファイルで追う量が半分になる → RV(差分が大きいので RS8 のあと)
- **機能の見直し(行を大きく減らすならここ)**: 配信後の全自動(M7。約 400 行)・アーカイブでの作り直し(P4。約 700 行)・配信中の候補の文字起こし(D-11。約 360 行 + ワーカー)・配信ごとの結果の記録(D-12。約 240 行)・失敗の集約(M3。約 170 行)を、今どれだけ使っているか(友人も含めて)を見て、要らない物を消す → RV の「使っていない機能を消すか」(ライブは友人も使う = F1 の形と合わせて)

### 説明文の中の記号(10-11 ユーザー「たまに出てくる説明って何」)
- 説明文(docstring・コメント)に計画の記号が多い: ② の flow だけで M○(線 D の自動の段取り)139・0-○-○(線 D の計画の節)77・D-○ 40・RS7-2 G○ 39・RS6 b-○/a-○ 45・決定 3-○ 24・F-○/B-○ 12 など。どれも `plan/` と `docs/design/` の文書の項目を指す「なぜこうなっているか」の出どころ。ライブ系は説明文が約 545 行
- 困る所: 済んだ計画の段の名前(RS7-2 G2b・RS6 b-K1 など)はコードの今の形の説明にならない・記号の一覧が無い(どの文書かを知らないと引けない)・経緯(「以前は〜」「RS3 で〜から移した」)がコードの中に積もる
- 候補: (1) 記号の早見表を 1 枚(`docs/ROADMAP.md` の近くに「記号 → 文書」)(2) コードの説明は「今どう動くか・なぜか」だけにし、どこから移したか・いつの段かは git と WORKLOG に任せる(3) 今も効く決まり(決定 3-○・仮決め (○○))の参照は残す → RV(資料の見直しと一緒に。消すと行数は数百行減るが、動きは変わらない)

## ③ 人の操作の見直しメモ(10-11。RS8 の始め。読むだけ・Sonnet)

### ③-1 校正の文書 `human/proof/store.py`・`doc_jobs.py`・`overrides.py`(約 1,740 行)
- `store.py`(910 行)は「文書の置き場」(保存・履歴・整形・要約キャッシュ。〜440 行)と「カット/パックの編集の置き場」(`sanitize_edit`・`edit_draft`・`edit_preview`・`save_edit`・`record_pack`・`pack_stale`・`sanitize_pack_output`。約 450〜830 行)が同居。後半は空のまま残る `human/cut/`(`__init__.py` だけ)の仕事 → `human/cut/` へ割る(`edit_draft`/`edit_preview` は ① の `resolve_export` から来た画面用の計算で `flow/pack` 経由 = ②-3 の `flow/pack` と一緒に)→ RS8(新しいカット/パックの画面)
- 文書の置き場そのもの(`tx_path`・`write_doc`・`snapshot`・履歴・`_open_lock`)は ④ のデータの持ち主の仕事で `workdata.TX_DIR` を直に読む。置き場所の解決を 1 か所に寄せ、store は「渡された場所に読み書き」だけに → RS8 の B-2(`ytt/docloc` の案)
- `doc_jobs.py`(534 行)・`overrides.py`(293 行): O2 で `doc_jobs.run_job` の「文書づくり + `write_after_transcribe` + 上書きの引き継ぎ」を組み立て関数 1 つに寄せられる。上書きを正にして文書は派生に → O2
- `doc_jobs`・`rerun` のジョブは ② の `flow/jobs` に登録して使う(自前の表は無い)= 決まりに合う。ただし画面は編集の `/api/jobs` を読む → 新しい画面は ② の status から(RS8 の新しい画面)
- 説明文: 1 行目が「② 人の操作の層」「② 文書の置き場」など層の数がずれたまま(`proof/` 全ファイル。`overrides.py` だけ ③)・「転送だけの殻。RS5 で消す」(殻は消えた)→ RV の文書

### ③-2 話者 `speakers.py`(869 行)・再認識 `rerun.py`(416 行)
- `speakers.py` に 5 つの仕事: 判別の結果の反映・判別ジョブの受付・空の行の下書き(`ovdraft_*`)・自動の判別の判断(`autodiar_*`)・声の登録簿(`voice_*`・`recognize_voices`)。声の登録簿は ④ 寄り → 「声」だけ `human/proof/voices.py` へ(②-3 の `flow/diar` の声の置き場所と一緒に見る)→ OPT2
- `diar_smooth_setting`・`autodiar_why_not`・`autodiar_name_by_context`・`recognize_voices`・`voice_learn_plan` は外から使うのは画面の API 経由だけ・`rerun.replace_original`・`replace_words` はファイルの中からだけ → 公開名を絞る → OPT1 の小物

### ③-3 校正の補助 `alt.py`(378)・`ytcap.py`(532)・`learn.py`(419)・`retime.py`(39)・`batch.py`(107)
- **yt-dlp を呼ぶ所が 4 つ**(`ytcap.ytcap_command`・`friend/intake.youtube_info`・`flow/livesession.probe_live`・`flow/live_archive`)→ ① に yt-dlp を呼ぶ口を 1 つ → OPT1(ffmpeg の探し方と同じ話)
- 字幕の取得(yt-dlp)とキャッシュ(`_ytcap_cache_lock`・`ytcap_dir`)は ① の「材料を取ってくる」仕事 → 候補を作る処理だけ ③、取得は `pipeline/ingest` へ → OPT2
- `alt.py` の `alt_engine_key`・`alt_notation_only` は文字の寄せ方(OPT3 の 7 つ)と重なる可能性 → OPT3
- `retime.py`(39 行・呼ぶのは serve だけ)→ store か serve に寄せてファイルを減らす → OPT1 の小物
- `learn._fb_lock` と `review/feedback._fb_lock` は「jsonl を足す + 大きくなったら .old へ」の写し → `ytt/fsio` に 1 つ → OPT1
- `batch.transcribed_ranges` は ④ `handoff_io` が呼ぶ(④ が ③ を読む)。判定は文書の一覧だけで足りる → ④ の一覧に寄せる → RS8 の B-2・B-3

### ③-4 友人 `human/friend/`(`intake.py` 883・`deliver.py` 387・`delivery.py` 347・`friend_feedback.py` 134・`live_requests.py` 125)
- `intake.parse_ranges`・`parse_weights`・`parse_video_tracks` は `flow/spec.clean_ranges`・`clean_weights` と同じ規則を別の形で持つ(RANGE_MAX も別定義)→ 受付は「封筒 + 束に組む」だけ、検査は `flow/spec` に → OPT2
- `intake.Intake`(Dropbox の見張り)の受付の状態 `_load_state/_save_state`・`_record` は ② の status と別の表 → 新しい画面で受付の様子を出すとき ② の status に載せる → RS8
- `youtube_info`(yt-dlp)・`probe_video`(ffprobe)は ① の取り込みの仕事 → ① へ → OPT2
- **`deliver.Deliveries` は自前のジョブ表**(`self.jobs`・糸・同時 1 本)。画面は `/api/ytt/deliver` の自前の状態を見る → 届ける段を ② の段にして status から読む → RS8 の新しい画面
- `deliver.make_preview`(ffmpeg でまとめ動画)・`_preview_args`・`_atempo`・`_font_file` は ① の書き出しの仕事・`_run_ffmpeg` は ffmpeg の起動の写し → ① の `export` へ → OPT2
- `delivery.py`(Runner の mixin)は ② の hook に ③ を渡す継ぎ → ②-1 の「ホストの口」でまとまれば消える → RV
- `friend_feedback`・`live_requests` は小さく形が良い。動かさない

### ③-5 採用・マーク `human/review/store.py`(1,130 行)・`feedback.py`(150)
- `Store`(data.json)に 3 つ: マークの検査と整形(`_build_mark`・`validate_marks`)・動画の置き場(`ensure`・`put_video`・`delete`)・グループとアンカー(コラボ。約 200 行)→ コラボは別ファイル・マークの検査は純粋なので `review/marks.py` に → OPT2
- 動画の置き場 `data.json` は ④ の「案件の動画の一覧」と二重 → Store は「案件の中のマーク」を扱う形に → RS8 の B-3
- `feedback.feedback_path` はテストからだけ → OPT1 の小物

### ③-6 検索 `human/find/rank.py`(830 行)
- 説明文が「① 配信ランキング」のまま → RV
- 4 つの仕事: 登録簿・YouTube Data API の呼び出し・疑似 API(`fake_*` 5 つ。約 110 行)・検索ジョブと配信中の一覧。疑似 API は `eval/fake/` へ → OPT2
- **`rank._jobs` は自前のジョブの器**(最大 5 件・同時 1 本・取り消し・phase・progress)= ②-3 の「仕組みを 1 つに」に含める → OPT2・RS8(新しい画面は status から)
- API の叩き方(`yt_get`・`parse_iso_dur`・`parse_dt`)は `analyze.py` のコメント欄・動画情報と同じ → ① の基盤に 1 か所 → OPT3

### ③ 全体を見て(10-11)
- 呼び手 0 の関数は無い。重なりは「外から使わない公開名」と他の層と同じ処理の写し
- 直す順: (1) ジョブの器 `Deliveries`・`rank._jobs` を ② の status へ(新しい画面の前提。RS8)(2) 層の違う処理を出す(`intake` の検査 → `flow/spec`、yt-dlp・ffmpeg・ffprobe を呼ぶ所 → ① の口。OPT1・OPT2)(3) `proof/store.py`・`review/store.py` を割る(OPT2)(4) 置き場所の解決 4 か所(`proof/store`・`review/store`・`batch.transcribed_ranges`・`deliver`)は RS8 の中で
- 大きなファイル: `review/store.py` 1,130・`proof/store.py` 910・`intake.py` 883・`speakers.py` 869・`rank.py` 830。`human/cut/` は空のフォルダ

## ④ データの見直しメモ(10-11。RS8 の始め。読むだけ・Sonnet)

### ④-1 案件 `manage/cases/cases.py`(681 行)
- 仕事が 3 つ混ざっている: (a) 一覧の組み立て(`build`・`snapshot`・`_case_extras`・TODO_ORDER)、(b) 自動の切り抜きの確認(`auto_review`・`_deliver`・`_discard`・`expire_unseen`・`_remember`。約 250 行)、(c) ごみ箱への移動(`discard_clip`・`_to_trash`・`_put_back`・`_write_manifest`)。(b) は「見た・届けた・要らない」の操作で ③ の仕事(スタジオのマーク・feedback・Dropbox 配信を引数で受けて動かしている)。(c) は `keep/cleanup` のごみ箱(manifest・日付のフォルダ)と同じ規則を持つ → (b)(c) を `human/review` か `keep` へ、cases.py は一覧だけに → RS8 の新しい画面と一緒に
- 説明文(先頭 50 行)が仕様書になっている。画面の項目の説明は docs/spec へ、コードは短く → RV
- `live_failures_by_mark` は ② の `live_export.JOBS_SCHEMA` と exports.json を直に読み、結果の束も読む。ジョブの記録の読みは ② の口(`live_failures`)に 1 本あれば足りる → OPT2
- 案件の根は今 cases.json(app/ の 1 ファイル)+ スタジオの data.json から読むたびに組み直し + `placement.read_case` で case.json を足している(`_case_file`)。**B-2・B-3 で変わる所**: `locations`(cases.json・studio・transcripts・liveJobs・runs の 5 つの置き場所)、`load_saved`/`_write`(状態・メモ・auto の置き場所 → 案件ごとの case.json へ)、`snapshot` の last(元ファイルを消しても履歴を残す写し → 案件フォルダがそのまま履歴になれば要らない)、`find_pack`(`txindex.pack_info` を呼ぶだけ・呼び手 15)
- `remember_delivered`(呼び手は ③ の delivery 側 6 か所)は案件ファイルに書く → B-3 で案件の中へ

### ④-2 紐づけ・パックの規則 `cases/txindex.py`(239 行)・`txlink.py`(36 行)
- 紐づけ(`load`・`pick`・`offset`・`lines`)とパックの有無(`pack_dir`・`pack_key`・`read_pack_record`・`pack_info`・`is_pack_dir`)と鍵の状態(`key_state`)が 1 ファイル。パックは別ファイルにすると読みやすい(`pack_info` の呼び手は ③ ② ⑤ に広がっている)
- **パックを作った記録を cut2resolve の作業データ `packs/<フォルダのハッシュ>.json` に持つ**(`packs_dir`・`pack_key`)。B-2 でパックが案件の中に入るなら記録は案件の作業用へ移り、`packs_dir` の `datadir.resolve("cut2resolve")`・`c2r_dir`・env の引数、`_old_cut_plan`(2026-09-26 までの cut-plan.json)も要らなくなる → B-2。**紐づけの規則(sourcePath → clip の videoId/markId、normalize30 の relinks)も、文書が案件の中にあれば「同じ案件フォルダの文書」で済む** → B-3
- 呼び手がテストだけ: `matches`(本体 0・テスト 3)、`read_pack_record`(外から 0)、`txlink.tx_folder`(0)。`txlink.py` は `for_video` 1 つだけ(呼び手 1)→ スタジオの側か txindex に入れてファイルを減らす → OPT1
- `NORM_WHY` を relink と txindex で二重に持つ → 1 つに → OPT1

### ④-3 文書の一覧・付け替え `doclist.py`(108 行)・`relink.py`(488 行)
- `doclist.pack_info` は txindex のラッパー(外からの呼び手 0)。`list_transcripts` は編集の serve だけが呼ぶ画面の一覧 = ③ の仕事 → RS8 で画面を作り直すときに ③ へ
- **`relink.py` の 30fps まわり(`norm_*` 約 230 行)は ④ の仕事ではない**: 動画を 30fps に作り直す(ffmpeg・進み具合・取り消し・空き容量)は ① の変換 + ② の段取り。続き(`norm_after_transcribe`)は serve の登録の口経由。友人の受付(`human/friend/intake`)は `ytt.normalize` を別に呼ぶ = 30fps が 2 本の道 → `pipeline/` か `flow/` に 1 つ。付け替え(`relink_*`)だけが ④ → OPT2(RS8 の B-3 と同時に)
- 先頭の説明文が「③ 文書と動画の紐づけ」「ed_relink は転送だけの殻 = RS5 で消す」(消えている)など古い。`doclist`・`handoff_io` の先頭も同じ → RV
- **B-3 で文書が案件の中に入れば、動画を動かしても相対で追えるので `relink_*` の多くが要らなくなる可能性**(絶対パスの保持を決めるとき)

### ④-4 受け渡し `handoff_io.py`(222 行)・`pipeline_io.py`(163 行)
- `handoff_io.read_marker`・`marker_videos`・`clip_info` はスタジオの data.json の読み(`ytt/studiodata` と二重)。`OTHER_JSON_MAX`(64MB)は `studiodata.STUDIO_JSON_MAX` と別に持つ → 1 つに → OPT1
- `pipeline_io.siblings`/`ping`(.runtime の他ツールの問い合わせ)は入口の仕事。呼び手 1 → `ytt/runtime` か app へ → OPT1。`save_beside`・`written_by_us`(動画の隣への保存)は B-3 の「横のファイル」(動画の隣 → 案件の作業用)で置き場所の規則が変わる中心
- `handoff_io` が `human.proof.batch`・`store` を読むのは `transcribed_ranges` のためだけ

### ④-5 バックアップ `keep/backup.py`(435 行)
- 形は素直。B-0 で `plan_cases`(案件の根の作業用の *.json と .studio-id だけ)が入っている = **B-2・B-3 の規則はここが先に持っている**。変わる所: `CASE_WORK`(= `schemas.WORK_DIR` の二重定義)、`_cases_enter`(題名/作業用/runs の 3 段の決め打ち)、SKIP_DIRS(`work`・`cache`)と案件側の規則が 2 本。案件フォルダに文書・パックの記録が入るなら 1 本の「何を写すか」に → B-3
- `_norm` は `fsio.norm_path` と同じ → OPT1

### ④-6 片付け `keep/cleanup.py`(352 行)・`live_cleanup.py`(305 行)
- 途中のファイルの名前を 3 か所が別々に持つ: `cleanup.SIDECARS`(7 種)・`_media_stem` の suffix(6 種。同じ一覧ではない)・`backup` の .json 限定。**横のファイルの種類を 1 つの表**(ytt/schemas か placement)に → OPT1。B-3 で「動画の隣 + 作業用」が「案件の作業用」に変わると `_sidecars`・`_work_orphans` は案件ごとの片付けに → B-3
- `_exports` は案件の一覧を受けて「投稿済み/見送り + パック」で候補を出す。案件単位の片付け(案件フォルダごとごみ箱へ)になると規則が簡単になる → B-3・O2
- `live_cleanup.Cleaner` は ② の `live_archive`・`live_export` の内部を読み、録画を消す = ② 寄り → RS8 では動かさず RV(録画の置き場所が決まってから)

### ④-7 調子・記録・再起動 `ops/`
- `health.count_worker_incidents` は ① のワーカーの log の文言を写して数える。文言を変えると黙って 0 になる → ワーカー側の定数を読むか記録を構造化 → OPT1。`tool_versions` は呼び手 0 → 消すか使うか
- `clientlog.py`・`restart.py` は形が良い。動かさない
- `health.data_sizes` の DATA_TOOLS は B-2 で「案件の中の分」が加わる → B-2

### ④ 全体を見て(10-11)
- **置き場所の規則が 5 か所**に散っている(cases.locations・txindex.packs_dir・schemas.WORK_DIR 系・backup.plan_cases・cleanup)。B-2・B-3 は、これを `flow/placement` の 1 か所から引く形にする機会 → RS8 の最初に表を作る
- ④ に入っている ① ② の仕事: 30fps の作り直し(relink)・ライブの失敗のジョブ読み(cases)。逆に ④ に寄せる候補: `flow/diar.py` の覚えた声の置き場所(②-3)・`human/review/store` のスタジオの data.json(案件の中へ移す候補 → B-3)
- 効く順: (1) 置き場所の規則を 1 か所に(B-2)(2) 30fps と cases の ③ 的な操作(auto_review・ごみ箱)を出して ④ を「読む・紐づける・片付ける」に絞る(OPT2)(3) 二重定義の掃除(OPT1)(4) 古い説明文(RV)
- 動かさない: `clientlog`・`restart`・`backup` の本体・`txindex` の紐づけの中心

## ③④ をまとめて(10-11)
- **ジョブの器は合わせて 10 通り**: ② の見直しの 8 通り + ③ の `deliver.Deliveries`・`rank._jobs`。新しい画面は ② の status だけを見る(RS8 の条件 1)= ② の口の形を決める段でこの 10 通りの載せ方を決める
- **置き場所の規則が散っている**: ④ の 5 か所(cases.locations・txindex.packs_dir・schemas.WORK_DIR 系・backup.plan_cases・cleanup)+ ③ の 4 か所 → B-2 で `ytt/docloc`(文書)と `flow/placement`(案件)から引く形に
- **yt-dlp・ffmpeg・ffprobe を呼ぶ所が ③④ にもある**(ytcap・intake・deliver・relink の 30fps)→ OPT1・OPT2 の「① の口を 1 つ」に足す
