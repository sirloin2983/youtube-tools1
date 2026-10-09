# 役割で組み直す: 関数ごとの行き先の表(2026-10-09。RS0)

> 状態(2026-10-09 夜): **資料**(読むだけのサブエージェント 3 体(Sonnet)の報告をそのまま。行番号は HEAD 2a8d81c の時点)。計画は `plan/role-restructure.md`、ファイル単位の表と向きの検査は `dev/layer_map.py`・`dev/tests/test_layering.py`。分割が要るファイル(入口 13・スタジオと cut2resolve と録画 11・編集 9 = 33 ファイル・約 31,000 行)を関数・クラス・定数ごとに「どの層のどこへ」と理由(呼び手の行番号)で並べた。RS1〜RS3 で移すときに各担当へ渡す。「要相談」は 3 体がそれぞれ付けた番号で、横断する物は 1 節に仮決めを置いた。

## 1. 横断する要相談と仮決め(RS0-a〜RS0-m。`plan/decisions.md` 3-22。**10-09 夜にユーザー確認済み。h・l・m は見直して決定の表 1-5 の形に = ① は自分の成果物と記録だけ書く(色は束で渡す)/ ① は空き容量と録画の管理を考えない・キャッシュは自分で片付ける / 進行度は消す・一覧は ③ の 1 関数・ドリルの要約は ④ が自分で・削除は名前の規則。登録の口は e だけ**)

3 体の報告に同じ形の問題が繰り返し出た。移す前に向きを 1 つに決めておく(違えば RS1 の前に直す)。

| 記号 | 何が困るか | 仮決め |
| --- | --- | --- |
| RS0-a | **「設定と状態の束」**(編集 `ed_state`・スタジオ `common`・入口 `prefs`)を全層が読む。app に置くと向きが逆(違反 69 件の大半) | 設定の読み書きと既定値・検査・置き場所の解決(`set_data_dir`・`set_out_dir` の現在値)は **`ytt/settings`** に寄せる(設定 1 ファイル・層ごとの節。検査の関数は鍵の持ち主の層が登録する)。文書の形の定数(`MAX_TEXT`・`OTHER_SPK_*`・`TID_RE`・印の名前)は **`ytt/schemas`**。`log`・`write_mark`(起動の印)・ジョブの共通の約束(`Cancelled`・`check_cancel`・`job_temp_wav`)・`_move`/`_same_drive`・共通の例外(`LiveError`)は **`ytt`**(`ytt/jobs`・`ytt/fsio`・`ytt/log`)。起動時の検査(`check_previous_run`)は app |
| RS0-b | **ツール間の HTTP 呼び出し**(入口 `ToolClient`・`live.studio_call`)を ① が使っている | 新しい形では ① は段を**関数で**呼ぶ(RS1 で `pipeline/run` が段を直接 import)。移す間は `ToolClient` を app に置き、`pipeline/run` から HTTP を消した時点で捨てる |
| RS0-c | **① が学習データを読む口**(覚えた声・置換の規則・採用の記録から作る長さの目安・配信者の記憶)が ② の関数を直接呼んでいる | 計画 6(B)のとおり**ファイルが境目**。書く側(作る)は `human/proof`・`human/review`、**読む側の小さな関数は `pipeline/transcribe`・`pipeline/analyze` が自分で持つ**(形式は `ytt/schemas` で共有)。`_friend_length`・`length_hint` も「採用の記録から作る学習データ」= ② が作り ③ に置き ① が読む |
| RS0-d | **候補(①)と人の判定(②)が同じ記録に同居**(スタジオ data.json の `status`・`adoptedBy`、`live_feedback.jsonl`、`live_detect` の `_decisions`、`MarkStore`、`adopt` の口が人と自動の両用) | 計画 4-3・5-3 のとおり分けるのは **RS6(上書きの置き場)**。RS1〜RS3 は**データの形を変えずコードだけ移す**: 入れ物(`Store` の SCHEMA・読み書き・退避)は `human/review`、配信の登録(id・kind・title・path)は `manage/cases`、候補を書く関数は `pipeline/analyze`、「候補 + 上書き」の合成は `manage/cases`(計画 5-3「案件側が持つ」)。`adopt` は人用(`human/review`)と自動用(`pipeline/analyze`)の 2 つの口にする |
| RS0-e | **ジョブ表と待機列**(編集 `_jobs`・`JOB_RUNNERS`・ワーカー循環)を全層が直接読む。① 単体が認識を動かす入口がこの表しかない | 汎用の待機列と SLOTS は **`ytt/jobs`**。① の段を回す runner は **`pipeline/run`**。ジョブの種別は各層が**登録の口**(`JOB_RUNNERS` の後継)で足す(② の alt・ytcap・relink、④ の drill・evalbatch)。`_jobs` を直接読む所は `ytt/jobs` の問い合わせに置き換える |
| RS0-f | **評価用フォルダの判定**(`in_eval_dir`・`evalSet`)を ① と ② が呼ぶ。eval に置くと向きが逆 | 判定だけ **`ytt/settings`**(`is_eval()` 1 か所。計画 3 の「編集に残すのは評価用の印」)。整理・仮置き・取り込み(`organize`・`settle`)は `eval/drill` |
| RS0-g | **30fps にそろえる**(編集 `ed_relink` の `norm_*`・入口 `intake._normalize_copy`)の行き先が計画に無い | 写しを作る判断と実行は **`pipeline/ingest`**(`ytt/normalize` を呼ぶ)、文書の付け替え(`norm_swap`)は `manage/cases`、ジョブの接着は呼び手の層 |
| RS0-h | **① が ② の上書き・記憶に書く**(`autorun._remember_styles` = 話者の字幕の色、`prefs.remember` = 配信者の記憶) | ① は**結果を返すだけ**。覚えるのは `manage/cases`(配信者の記憶・前回の結果)か `human/proof`(話者の色)が、① の結果を受けて書く |
| RS0-i | **`run_job`・`validate_job`・`apply_diarization`・`autodiar_*`**(認識の計算と、文書への書き込み・評価用の規則・次の段の自動投入が 1 関数) | RS2 の分割点。**計算は `pipeline/transcribe` の純関数**(入力ファイル → 結果)。文書の作成・`fill_doc`・人が付けた行を守る規則・後続の投入は `human/proof` の薄い包み。指定の既定値と検査は `pipeline/spec`、`intoDoc`・`find_clip` の検査は `human/proof` |
| RS0-j | **cut2resolve の `AppState`**(ジョブの実行・`pack.Cache`・フォルダを開く許可が 1 クラス)、`serve._resolve_package`(配線を超える処理) | `pipeline/run`(実行)・`pipeline/pack`(Cache・`_resolve_package` の中身は `resolve_export` に 1 関数)・app(許可リスト・配線) |
| RS0-k | **入口の二重**(`intake.youtube_id` と `ytt/recproto.video_id_of`、`parse_ranges` と `autorun.clean_ranges`、`_normalize_copy`) | `ytt/recproto`・`pipeline/spec`・`pipeline/ingest` の 1 つに寄せる(RS3) |
| RS0-l | **片付けと見張り**(`chat_cache` の上限と掃除、`live_export.disk`、`after_stream_hold`) | 掃除の実行は持ち主の層(`pipeline/analyze`・`pipeline/export`)に置き、**起動時の呼び出しと見張りだけ `manage/keep`・`manage/ops`** |
| RS0-m | **文書の一覧と要約**(`transcript_summary` がドリルの要約と進行度を作る)、`serve._delete`(付き物の持ち主が層をまたぐ) | 基本の要約と削除は `human/proof`。進行度は `manage/cases`、ドリルの要約は `eval/drill` が**登録の口**で足す。付き物(edit.json・asr・diar・alt・ytcap・llm)も各層が登録 |

共通の作法: 「下の層が上の層の関数を呼んでいる」所は、(1) 読むだけならファイルを境目にして下の層が自分の読み手を持つ (2) 上の層の処理を挟みたいなら**登録の口**(callback の表)を下の層に置き、上の層が起動時に登録する (3) どちらでもないなら、その処理ごと上の層に移す。

## 2. 行数の合計(3 体の報告から。概算)

| 対象 | 行数 | pipeline | human | manage | eval | app | ytt | 要相談・ヘッダ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 入口 13 ファイル | 12,765 | 6,748 | 1,552 | 1,174 | 321 | 2,062 | 223 | 685 |
| 編集 9 ファイル | 9,942 | 2,795 | 2,336 | 603 | 1,491 | 701 | 231 | 1,785 |
| スタジオ・cut2resolve の API・録画 11 ファイル | 7,059 | 3,016 | 1,336 | 31 | 119 | 917 | 551 | 944(+keep 76・ops 69) |



## 3. 入口 src/home(13 ファイル)(元の見出し: src/home/ の行き先の表(RS0。読むだけの調査))

- 根拠: `plan/role-restructure.md` の 3 節(目標の形)と 7 節(行き先の表)。層は pipeline(ingest・analyze・export・transcribe・pack・run/spec)/ human(review・proof・cut・find・friend)/ manage(cases・keep・ops)/ eval(fake・drill・tools)/ app / ytt。
- 調べた日: 2026-10-09 時点のコード。呼び手は grep で確かめた(行番号つき)。行番号は 2026-10-09 時点のそのファイルの行。
- 表の「行」は `開始-終了 (行数)`。終了は次の行の開始の手前まで(空行・コメントを含む)。docstring と import は「—(説明・import)」にまとめた。
- 理由の頭の【要相談】は、層の境目が割れていて決めきれない物。最後に一覧もある。
- 使ったモデル: Sonnet。

### autorun.py(2275 行)

3 つの経路が 1 つの `AutoRunner`(1 本のキュー・1 本のスレッド `_loop` 1251)と 1 つの `Run`(339)に同居している。

- **① の経路**: 人が押す `start`(718)/`start_new`(736)/`start_docs`(757)と、ライブ・動画ファイルの `start_file`(806。呼び手 intake.py:759・live_export.py:1112)。段は `_step_analyze` → `_step_adopt` → `_step_export` → `_step_transcribe` → `_step_diarize` → `_step_pack`。
- **友人の依頼の経路**: `start_request`(775。呼び手 intake.py:696)と、`Run` の友人用の項目(request_id・deliver_dir・deliver_batch・pool・pack_marks・speakers・video_tracks)、`deliver` の段と届ける部品一式(1964-2230)、組の溜め(2121-2219。呼び手 live.py:695)。
- **測るための経路**: `post_analyze`(あとから解析)= 1040-1249 と各所の `POST_MODE` 分岐(Run 404・public 460・_remember 999・snapshot 980・_loop 1256/1266/1297・_step_analyze 1430)。呼び手 launch.py:935-937(restart_self)・health.py:154(失敗の数から除外)。plan 9 で消す。

**混ざっている結び目(分けるときに切る所)**
(a) `Run.__init__` 382-387: mode から段を決める・区間が足りれば analyze を外す。
(b) `_pack_one` 1784-1785: パックの途中で `_deliver_pending` を呼ぶ = ① の中に友人の届けが入っている。
(c) `_loop` 1294-1297: 失敗時の届け残し・失敗の .txt(友人)とあとから解析の登録(測る用)が ① のループの終わりに入っている。
(d) `_step_adopt` 1554: mode が request なら友人の区間の採用へ分岐。
(e) `_record_delivery` 2062-2072: friend の記録が manage の `cases.remember_delivered` を呼ぶ(向きが逆)。
(f) 層違反の import: `cases`(55。find_pack 567・clip_live 294・read_studio/locations 1313/1441・remember_delivered 2070)・`ytt_core.txindex`(`_docs` 1309。plan では txindex は manage/cases)・`prefs`(59)・`friend_feedback`(58)・`deliver`(57)。

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| モジュール docstring・import | 1-60 (60) | —(説明・import) | docstring 4-47 に 3 つの経路が混在。import の cases(55)・prefs(59)・friend_feedback(58)・deliver(57)は pipeline から上の層を読む向き違反 |
| MODES | 61-61 (1) | pipeline/run | 画面の選択肢 full/adopted/transcribe = run(from=段)の入口名。参照 prefs.py:47・launch.py:742 |
| STEP_LABELS | 62-63 (2) | pipeline/run | 段の表示名。deliver(63)は友人の段 |
| MODE_STEPS(full/adopted/transcribe/doc) | 64-65 (2) | pipeline/run | ① の段の並び = run(from=)の元になる表 |
| MODE_STEPS(request*/file* の段表) | 66-67 (2) | human/friend | 友人の依頼の形ごとの段。request_auto/file_auto に deliver が入る |
| MODE_STEPS(file_manual / post_analyze) | 68-68 (1) | eval/drill | post_analyze = あとから解析(測るため)は plan 9 で消す。file_manual は友人 ③(下の _file_analyze と同じ扱い) |
| REQUEST_MODES・REQUEST_URL_MODES(説明つき) | 69-76 (8) | human/friend | 友人の依頼の形(依頼 ①②③)。使う所 Run 383・public 460・_step_adopt 1554・_defer_eligible 473 |
| RANGE_PAD | 77-77 (1) | pipeline/analyze | 友人が指定した区間の前後に足す 2 秒。pad_range(278)専用 |
| RANGE_MAX / RANGE_MAX_SEC | 78-79 (2) | pipeline/spec | 「この区間は必ず」の指定の個数・長さの上限(clean_ranges 用)。studio の MAX_REQUEST_RANGES/MAX_MARK_SEC と二重 |
| CUTS | 80-80 (1) | pipeline/spec | パックのカット方法 none/silence の選択肢。Run.cut の検査(349) |
| TX_ENGINES / TX_MODEL_RE | 81-82 (2) | pipeline/spec | 実行ごとのエンジン・モデル指定の検査(Run 345-346)。prefs.py:83-84 と二重 |
| WEIGHT_KEYS | 83-83 (1) | pipeline/spec | 解析の重みの鍵(clean_weights 271) |
| FLOW_MODES | 84-85 (2) | human/friend | 友人の flow(auto/check/manual)→ mode。start_request 783・start_file 817 が使う |
| STEP_STATE_LABELS・RUN_STATE_LABELS・NOTHING_MESSAGE・DOC_MODE | 86-92 (7) | pipeline/run | 状態語。DOC_MODE = 文書単位の実行(from=transcribe) |
| MAX_MARKS | 93-93 (1) | pipeline/spec | 「このマークだけ」の指定の上限(_marks_arg 676) |
| DOC_LABEL | 94-94 (1) | pipeline/run | 文書単位の実行の表示名 |
| DEFAULT_TOP | 95-95 (1) | pipeline/spec | 採用する数の既定 3(_top_arg 298) |
| MAX_NEW | 96-96 (1) | pipeline/run | start_new/start_request の 1 回に入れられる配信数の上限(736・781) |
| MAX_KEEP・RUNS_LOG・LOG_* | 97-101 (5) | pipeline/run | 実行の記録(autorun-runs.jsonl)= ① が自分の結果を残す記録。読み手は health.py:154・live_failures.py:147・cases.py:84(manage) |
| PAST_*・HISTORY_* | 102-106 (5) | pipeline/run | 案件ごとの前回の結果(past)・履歴 API(launch.py:675)の件数。【要相談】past は案件の行の「前回」= manage/cases が ① の結果 JSON を読む形が筋 |
| MAX_WAITING | 107-107 (1) | pipeline/run | 順番待ちの上限(_busy_reason 307) |
| POOL_FILE・POOL_* | 108-111 (4) | human/friend | ライブの切り抜きを n 本の組で届ける溜め(deliver-pool.json)の定数 |
| BUSY_WAIT | 112-112 (1) | pipeline/run | ツールが 409 busy のときの待ち間隔(_call_when_free 1324) |
| TX_KEYS | 113-114 (2) | pipeline/transcribe | 文字起こしの設定のうちジョブに渡す鍵(_tx_opts 1852) |
| POST_MODE・OTHER_MODES・DEFER_* | 115-128 (14) | eval/drill | あとから解析(測るため)の定数。plan 9 で消す(④ の道具で代える)。環境変数 YTT_DEFER_ANALYZE |
| FRIEND_LENGTH_*・EVAL_MARKS_NAME_RE・EVAL_READ_MAX・FRIEND_*_RANGE | 129-138 (10) | pipeline/analyze | 【要相談】友人の区間の長さの実績(dev/eval_marks の結果)で自動候補の長さを決める定数。plan 9「学習データとして ③ に置く形に直す」対象。live_excite_worker.py:96-105 と二重 |
| CANCEL_WAIT | 139-139 (1) | pipeline/run | 取り消した解析が止まるのを待つ秒(_cancel_analysis 1517) |
| ACTIVE_FILE・RESTORE_*・RESUME_WAIT・DONE_STEPS・STEP_TOOLS | 140-148 (9) | pipeline/run | 入口の起動し直しで待ち・実行中を戻す記録(M5)の定数。run の「済んだ段は飛ばす」に当たる |
| REDO_STEPS | 149-151 (3) | manage/ops | 【要相談】「起動し直す」で止めてよい段(restart_info 923 専用)。起動し直しの判断は ops が持ち、run は実行中の段と ID を聞かれて返す口だけ持つ形が筋 |
| TX_ACTIVE・QUEUE_ACTIVE | 152-153 (2) | manage/ops | _redo_work(942)が仕事の一覧を読むときの状態名(editor の ed_jobs・studio の batch と二重) |
| RUN_ID_RE | 154-157 (4) | pipeline/run | 実行 id の形(Run.restore 404) |
| _media_is_30fps | 158-168 (11) | pipeline/pack | 素材がちょうど 30fps か → パックの fps を 30 に(_pack_one 1729)。判定は ytt の normalize.probe の薄い皮 |
| _has_captions | 169-173 (5) | pipeline/pack | 文書に残す字幕の行があるか(_pack_one 1733・_doc_pack 1886) |
| TOOL_NAMES・ToolClient | 174-230 (57) | app | 【要相談】取り込んだツール(studio/transcribe/cut2resolve)の API を HTTP で呼ぶ皮。pipeline が段を関数で呼べるようになるまでの接着。呼び手 launch.py:887・967・1103・live.py:402。pipeline に置くと app を読む向き違反なので app に出す |
| JOB_STATE_JA・_job_why | 231-238 (8) | pipeline/run | ツールのジョブ失敗の理由を日本語に(1652・1777・1877) |
| _yt_id_ok | 239-243 (5) | pipeline/ingest | YouTube 動画 ID の検査(start_new 749・_defer 1078)= URL の判定 |
| _doc_id_ok | 244-247 (4) | pipeline/run | 文書 ID の検査(start_docs 766) |
| _num・_ms_ok | 248-256 (9) | ytt | 数値の検査。ytt の schemas.is_num と二重 |
| clean_ranges | 257-270 (14) | pipeline/spec | 区間指定 [(開始, 終了)] の検査 = 指定の束の「この区間は必ず」。呼び手 start_request 791・Run.restore 422 |
| clean_weights | 271-277 (7) | pipeline/spec | 解析の重みの検査。呼び手 start_request 784・Run.restore 423 |
| pad_range | 278-286 (9) | pipeline/analyze | 友人の区間に余白を足して採用に(_step_adopt_request 1536) |
| LIVE_AUTO_CUT | 287-289 (3) | pipeline/spec | 自動採用の切り抜きのカット既定 none(M8)。パック設定の既定値 |
| live_auto_origin | 290-297 (8) | pipeline/pack | 【要相談】.clip.json の source.live.origin が auto/archive か(manage/cases の clip_live を呼ぶ)。パックのカット方法の決定(1740)に使う。鍵 JSON を pipeline が直接読む形にして cases への依存を断つ |
| _top_arg | 298-306 (9) | pipeline/spec | 採用する数 1〜30 の検査 |
| _busy_reason | 307-315 (9) | pipeline/run | 同じ配信・文書を二重に入れない・待ち上限 |
| clean_pool・_PoolRun | 316-338 (23) | human/friend | ライブの切り抜きの組の溜めの指定の検査・溜めを届ける部品へ渡す代役。作り手 live_export.py:1109(deliver_pool) |
| Run.__init__ | 339-388 (50) | pipeline/run | 【要相談】① の状態に、友人の項目(request_id 362・deliver_dir 356・deliver_batch 347・pool 344・pack_marks 359)と測る用(preempted 378)が同居。382-387 で mode から段を決める。分割するなら ① の Run + 友人の付随情報 |
| Run.saved・Run.restore | 389-444 (56) | pipeline/run | 待ちの記録の書き出し・復元(M5) |
| Run.key・step・public | 445-468 (24) | pipeline/run | 前回の結果のキー・段の取得・画面用の形(public は UI 用の整形も含む) |
| _defer_eligible | 469-476 (8) | eval/drill | 区間だけで終わった依頼の判定 = あとから解析の登録条件。消す |
| _rec_key・_parse_rec | 477-502 (26) | pipeline/run | 実行の記録 1 行の読み取り(past・履歴用) |
| read_runs_log | 503-532 (30) | pipeline/run | 実行の記録の読み取り。読み手: 自分(562・992・1097)と live_failures.py:147(manage/ops) |
| AutoRunner.__init__ | 533-585 (53) | pipeline/run | キュー・記録・復元の初期化。defer(553-583)・pool(545-547)の初期化が同居(測る用・友人用)。作る所 launch.py:1103 |
| _save_active・_restore_active | 586-629 (44) | pipeline/run | 待ち・実行中の実行を autorun-active.json に残して戻す(M5) |
| _await_tools | 630-651 (22) | pipeline/run | 戻した実行がツールの準備を待つ |
| _streamer | 652-661 (10) | pipeline/spec | 画面で入れた配信者名の照合(colors.resolve)= 指定の束の「配信者」 |
| _auto_streamer | 662-675 (14) | pipeline/pack | 【要相談】配信者(字幕の色)を覚えた名前→チャンネル名から決める。覚えた名前は prefs の streamer(人の入力から作る学習データ)。呼び手 1754・1806 |
| _marks_arg | 676-685 (10) | pipeline/spec | 「このマークだけ」の指定の検査 |
| _pref | 686-693 (8) | app | ホームの設定 autorun 節を読む。run には spec で渡す形にして pipeline から設定を読ませない |
| _push・_enqueue | 694-717 (24) | pipeline/run | キューに入れる共通処理 |
| start | 718-735 (18) | pipeline/run | 人が押す full/adopted/transcribe の入口。呼び手 launch.py:742 |
| start_new | 736-756 (21) | pipeline/run | スタジオ「① 探す」で選んだ配信を解析から全部で。呼び手 launch.py:738(human/find からの入口) |
| start_docs | 757-774 (18) | pipeline/run | 「編集」の履歴で選んだ文書を文字起こし→パック(from=transcribe)。呼び手 launch.py:740 |
| start_request | 775-805 (31) | human/friend | 友人の URL 依頼を ① に流す薄い層(flow→mode・deliver_dir・pool 等の付与)。呼び手 intake.py:696。中の make(786-803)は ① の run を作るだけにできる |
| start_file | 806-823 (18) | pipeline/run | 動画ファイルを ① に入れる(文字起こし→パック)。呼び手 intake.py:759(友人)と live_export.py:1112(ライブの書き出しのあと)。ライブ側も ① の入口として使う |
| estimate | 824-893 (70) | pipeline/run | 【要相談】実行と同じ規則の見積もり(段ごとの本数)。ホーム画面の「実行」ボタン用。run の「計画だけ返す」口にするか app に置くか。呼び手 launch.py:735-736 |
| _active_runs・_wake | 894-907 (14) | pipeline/run | キューの見張り。_wake 902 が preempt(測る用)を呼ぶ |
| _preempt_deferred・stop_deferred | 908-922 (15) | eval/drill | あとから解析を止める。呼び手 launch.py:937。消す |
| restart_info・_redo_work | 923-957 (35) | manage/ops | 【要相談】「起動し直す」の可否の材料(実行中の段のジョブをツールの一覧で確かめる)。呼び手 launch.py:939。ops から run を覗く口が要る |
| cancel | 958-975 (18) | pipeline/run | 実行の中止。呼び手 launch.py:744 |
| snapshot・history | 976-995 (20) | pipeline/run | 実行の状態・記録の返し方。呼び手 launch.py:673・675・884・live_export.py:491 |
| _remember・_log・close・_trim | 996-1039 (44) | pipeline/run | 記録・終了・古い実行の整理 |
| あとから解析の説明・_defer_on | 1040-1046 (7) | eval/drill | 測るためだけの経路。消す |
| _env_off | 1047-1050 (4) | ytt | 環境変数が off か。あとから解析(1044)と友人の長さ(1437)が使う汎用の小物 |
| _now_ms〜_defer_post_done(あとから解析の一覧一式) | 1051-1250 (200) | eval/drill | 一覧 autorun-deferred.json・登録・取り込み・開始・終了処理。約 200 行。消す(inventory 20 行目) |
| _loop | 1251-1306 (56) | pipeline/run | 【要相談】1 本のワーカー。あとから解析の取り出し(1256・1266・1297)・失敗時の届け残し(1294-1296)が同居 |
| _docs・_studio_video | 1307-1314 (8) | pipeline/run | 【要相談】txindex.load・cases.read_studio を直接読む(plan では manage/cases)。段が使う「文書の一覧・配信の一覧」は run へ渡すか、manage を読まない形に |
| _check・_wait・_call_when_free・_poll | 1315-1353 (39) | pipeline/run | 中止検査・待ち・ツールの 409 待ち・ジョブ待ちの骨組み |
| _video・_execute・_run_steps・_finish_message | 1354-1408 (55) | pipeline/run | 配信の読み・mode ごとの段の呼び分け(_step_/_doc_/_file_)・段を順に進める |
| _weights_differ | 1409-1416 (8) | pipeline/analyze | 重みが違えば解析し直す(解析の鍵の判定) |
| _step_analyze | 1417-1433 (17) | pipeline/analyze | 解析の段。1430-1431 に POST_MODE 分岐(測る用) |
| _friend_length | 1434-1478 (45) | pipeline/analyze | 【要相談】友人の区間の長さの実績(dev/eval_marks の最新結果)を依頼の自動候補に重ねる。学習データ(B)として ③ に置く形へ。呼び手 1486 |
| _analyze_item・_cancel_analysis | 1479-1531 (53) | pipeline/analyze | 解析のキュー投入・待ち・取り消し(依頼 ③ の _file_analyze 1954 も使う) |
| _step_adopt_request・_step_adopt | 1532-1569 (38) | pipeline/analyze | 自動採用(区間+上位 N / adopt-top)。区間指定の友人用分岐(1554)を含む |
| _export_body | 1570-1577 (8) | pipeline/export | 書き出しの設定(画質・音量)をスタジオの設定から作る |
| _mine | 1578-1581 (4) | pipeline/run | この実行で扱うマーク(marks 指定) |
| _step_export | 1582-1610 (29) | pipeline/export | 書き出しの段。呼び手 _run_steps |
| _clips | 1611-1614 (4) | pipeline/run | 書き出し済みの切り抜き一覧 |
| _step_transcribe | 1615-1657 (43) | pipeline/transcribe | 文字起こしの段(ジョブ投入・待ち) |
| _edit_keeps | 1658-1673 (16) | pipeline/pack | 【要相談】「編集」のカット(edit.json の clips)を読む = human/cut の上書きを pack が読む口。今は HTTP /api/edit 経由 |
| _pack_settings・_cut_method | 1674-1712 (39) | pipeline/pack | パックの作り方(編集の設定 3 パックのタブと同値)を集める。_cut_method は _pref(app)を読む |
| _speaker_styles | 1713-1724 (12) | pipeline/pack | 友人が指定した話者の字幕の色を検査して pack へ渡す形に |
| _pack_one | 1725-1790 (66) | pipeline/pack | 1 本のパックを cut2resolve で作る。1784-1785 でパックの途中に届け(友人)を呼ぶ結び目 |
| _step_pack | 1791-1841 (51) | pipeline/pack | パックの段(切り抜きごとに _pack_one) |
| _doc | 1842-1851 (10) | pipeline/run | 文書の取得・元動画の確認 |
| _tx_opts・_wait_job・_doc_transcribe | 1852-1880 (29) | pipeline/transcribe | 文字起こしの設定取得・「編集」ジョブ待ち・文書単位の文字起こし |
| _doc_pack | 1881-1899 (19) | pipeline/pack | 文書単位のパック |
| _step_diarize | 1900-1934 (35) | pipeline/transcribe | 文字起こしした文書の話者分離(友人の人数指定) |
| _remember_styles | 1935-1945 (11) | human/proof | 【要相談】友人指定の字幕の色を文書の話者に覚える(POST /api/speakers/sub)= ② の上書きへの書き込み。① は書かず pack へ直接渡す形が筋 |
| _file_diarize | 1946-1949 (4) | pipeline/transcribe | 依頼の動画の話者分離(_step_diarize を呼ぶだけ) |
| _file_analyze | 1950-1957 (8) | human/friend | 【要相談】依頼 ③「全部人が行う」= 解析までで止める。plan 9 は ② の「確認してから届ける」を消すと書くが ③ の扱いは未記載 |
| _file_pack | 1958-1963 (6) | pipeline/pack | 依頼の動画のパック(_doc_pack を呼ぶ) |
| 届けの一式(_file_deliver〜_deliver_one) | 1964-2120 (157) | human/friend | deliver の段・Dropbox 出力への zip・n 本の組・まとめ動画・届けた記録(_record_delivery 2062 が cases.remember_delivered を呼ぶ)。deliver.py/friend_feedback.py と同じ領域 |
| 組の溜め一式(_pools_load〜flush_pools) | 2121-2219 (99) | human/friend | 実行をまたいで n 本ためて組で届ける。呼び手 live.py:685・695(見回り) |
| _deliver_failure | 2220-2230 (11) | human/friend | 止まったとき友人の「受け取る」に理由 .txt を置く(intake._notify_rejected と同じ形) |
| _file_transcribe | 2231-2263 (33) | pipeline/transcribe | 依頼の動画の文字起こし。2255-2260 で prefs.remember(配信者の記憶 = 要相談) |
| _row_edge_ok | 2264-2275 (12) | pipeline/pack | 「行から」の端の設定の検査。cut2resolve の pack.row_edge_from と二重 |

### launch.py(1344 行)

入口(`PortalServer`)= 全部の部品を作って配線する場所なので、ほとんどが `app`。`app` が全部を使ってよい層なので import の向きは問題ない。例外は、中身が別の層の仕事になっている数個(restart_self・片付けの候補・精度の自動測定の「手が空いたか」)。

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| docstring・import | 1-98 (98) | —(説明・import) | API 一覧の docstring(9-48)と、全部の部品の import(autorun・intake・backup・accuracy・deliver・cases・friend_feedback・cleanup・restart・prefs・live・analytics)= app だから許される向き |
| APP_ID・VERSION・TOOL_ID・DEFAULT_PORT・UI_KIT_DIR・LOG_MAX など | 99-111 (13) | app | VERSION 0.54.0 は plan 4-8「版は 1 つ」で入口の版が正になる |
| SERVE_VERSION_RE・_spec・TOOLS・TOOL_IDS | 112-132 (21) | app | 起動するツール(studio/transcribe/cut2resolve)の表 |
| runtime_dir・valid_port・read_runtime・ping・port_open | 133-153 (21) | app | ytt.runtime の薄い皮(消せる) |
| tail | 154-174 (21) | manage/ops | ログの末尾を返す(GET /api/log 670 専用)。ログ閲覧は調子の一部 |
| expected_version | 175-184 (10) | app | ツールの版の期待値を読む(Supervisor が使う)。plan で版が 1 つになると消える |
| tool_python・signal_stop | 185-207 (23) | app | 子プロセスの起動・停止の合図 |
| Tool | 208-257 (50) | app | ツール 1 つ(子プロセス/取り込み)の状態 |
| app_data_dir・logs_dir_for | 258-269 (12) | ytt | 入口の作業データ・ログの置き場所 = datadir.locate の薄い皮。置き場所の規則は ytt |
| Supervisor | 270-529 (260) | app | ツールの起動・停止・監視(start 316・_mount 336・stop 395・_monitor 511) |
| SETTINGS_DIR・STATIC・CSP・GET_SNAPSHOTS・POST_ROUTES | 530-555 (26) | app | 静的ファイルと API の配線表(POST_ROUTES 547-553 が autorun・cases・intake・backup・accuracy・cleanup を並べる) |
| query_int・BODY_ERRORS・read_json_body・site_ok・guarded_body | 556-600 (45) | app | HTTP の検査(httpsec の薄い皮) |
| PortalHandler の共通部(log_message〜_fail) | 601-626 (26) | app | Host/Origin 検査・応答の補助 |
| PortalHandler.do_GET | 627-682 (56) | app | GET の配線: /live→live 631・/analytics 633・/api/health 659・/api/cleanup 661・/api/log 662・/api/autorun/history 674・/api/cases 676 |
| PortalHandler.do_POST | 683-711 (29) | app | POST の配線: ytt_api 688・live 693・analytics 695・ツール start/stop 697・POST_ROUTES 705 |
| _post_case | 712-720 (9) | app | 配線 → manage/cases.update |
| _post_case_auto | 721-727 (7) | app | 配線 → cases.auto_review(human/review)に deliveries・studio_call・feedback・trash・hide を渡す |
| _post_autorun | 728-747 (20) | app | 配線 → pipeline/run の estimate/start_new/start_docs/start/cancel |
| _post_intake_scan・_post_backup_run・_post_accuracy_run・_post_window・_post_cleanup・_post_shutdown | 748-793 (46) | app | 配線(intake・backup・accuracy・appwindow・cleanup・終了) |
| _color_entry・streamer_colors・hide_tokens | 794-816 (23) | app | 配信者の色候補の API(規則は ytt.colors)・設定の合言葉を伏せる |
| peek_path | 817-835 (19) | app | 接続の最初の行を覗いてどのツールの Handler に渡すか決める |
| PortalServer.__init__ | 836-877 (42) | app | 全部の部品を作って配線する唯一の場所(intake 857・backup 861・accuracy 863・deliveries 865・live 868・health 870・cleanup 873・analytics 876) |
| _accuracy_busy・_accuracy_last_edit | 878-911 (34) | eval/drill | 精度の自動測定(accuracy.py)に渡す「手が空いたか」の判定。SLOTS・autorun・編集ジョブを見る。accuracy と一緒に eval へ |
| cleanup_candidates | 912-925 (14) | manage/keep | 片付けの候補を作る(案件+受付フォルダを cleanup に渡す)。呼び手 launch.py:661・_post_cleanup |
| restart_self | 926-954 (29) | manage/ops | 入口ごと起動し直す(restart.py を呼ぶ)。run の実行中判定は autorun.restart_info・stop_deferred(935-939)に頼る。呼び手 ytt_api 1000 |
| purge_trash | 955-963 (9) | manage/keep | 起動時に期限切れのごみ箱を消す。呼び手 main 1321 |
| _worker_probe | 964-972 (9) | manage/ops | 編集の /api/ping の worker(認識ワーカー)を調子に渡す。ToolClient を使う |
| _extra_dirs | 973-979 (7) | manage/keep | スタジオの書き出し先(空き容量とごみ箱の置き場所)。health 870・cleanup 873 に渡す |
| tool_ports | 980-989 (10) | app | 窓で開いてよいツールのポート |
| ytt_api | 990-1025 (36) | app | 画面の共通 API(client-log・open-window・restart-self・deliver・live・prefs・streamer-colors)の振り分け |
| streamer_guess | 1026-1042 (17) | app | 配信者を自動で決める API(prefs.guess_streamer を呼ぶ。guess_streamer の置き場は prefs.py 384 の要相談を参照) |
| prefs_api | 1043-1071 (29) | app | 設定の読み書き API(get/patch/remember/hide)。patch の後に intake/backup/accuracy/live を起こす 1056-1061 |
| ytt_request | 1072-1088 (17) | app | 画面の共通 API の検査(Host・Origin・合言葉・本文) |
| tool_endpoint・autorun(property) | 1089-1107 (19) | app | ツールの (ポート, 場所) を返す・AutoRunner を最初に使うとき作る(launch.py:1103) |
| handler_for・finish_request | 1108-1119 (12) | app | 取り込んだツールへ要求を渡す |
| close_watchers・teardown・request_shutdown | 1120-1154 (35) | app | 終了の後始末の順番(intake→backup→accuracy→live→analytics→autorun→監視→ツール) |
| make_server | 1155-1175 (21) | app | 空いているポートで待ち受ける |
| make_logger | 1176-1217 (42) | app | launcher.log への出力 |
| STOP_SIGNALS〜ignore_stop_signals | 1218-1249 (32) | app | 終了の合図の扱い |
| parse_args・main | 1250-1344 (95) | app | 起動の入口。見張りを start する順番(1315-1321) |

### live.py(1238 行)

`Live` は「ライブ全体の玄関」で、録画元の操作(ingest)・画面の API と中継(app)・マーク/書き出し/アーカイブ/検出/文字起こし/報告の組み立て・友人の依頼の結びつき・片付けまでを 1 つのクラス(254-1238)が持つ。分割すると ingest / run / app / friend / keep / ops に散る。ここでは Live の入口ごとに行き先を付けた。呼び手は主に launch.py(PortalServer 868・do_GET 631・do_POST 693・ytt_api 1010)。

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| docstring・import | 1-86 (86) | —(説明・import) | API 一覧の docstring(2-62)と import(live_export・live_archive・live_cleanup・live_failures・live_detect・live_requests・live_tx・live_report・deliver・intake.OUT_DIR) |
| CODE_DIR・VENDOR_DIR・DEFAULT_FOLDER・RECORDER_PORT・LOCAL | 87-91 (5) | pipeline/ingest | 録画元の既定(recorder.py と同じ値の二重) |
| PAGES・TYPES・TO_STUDIO | 92-94 (3) | app | /live/ の部品配信・スタジオへの転送 |
| STUDIO_PATH・RELAY_RE・RELAY_POST_RE・PASS_TYPES・RELAY_TIMEOUT | 95-99 (5) | app | 録画元への中継(HLS の再生)の経路表 |
| WATCH_SEC・SPAWN_GAP・VERSION_RE | 100-102 (3) | pipeline/ingest | 録画の部品の見回り・起動の間隔 |
| QUALITIES・DEFAULT_QUALITY・YT_HOSTS・URL_MAX | 103-106 (4) | pipeline/ingest | 録画の画質・URL の検査(rec_core と同じ値の二重) |
| POOL_EVERY | 107-107 (1) | human/friend | 組の溜めを見る間隔(flush_pools 677) |
| EXPIRE_EVERY | 108-108 (1) | manage/keep | 見ていない自動の切り抜きの片付けを見る間隔(expire_unseen 697) |
| LIVE_STATUSES・PROBE_TIMEOUT・CHANNEL_MAX | 109-111 (3) | pipeline/ingest | yt-dlp の live_status・調べる時間切れ |
| STATUS_TIMEOUT・STATUS_CACHE・RECENT_SEC | 112-114 (3) | app | 全ツールのヘッダーの録画の札(api/ytt/live の status) |
| STOP_TIMEOUT | 115-115 (1) | pipeline/ingest | 録画元の stop を待つ秒 |
| ADOPT_SAME | 116-116 (1) | pipeline/analyze | スタジオのマークを使い回す区間の差 0.5 秒(_studio_adopt_mark 854) |
| QUIT_TIMEOUT・QUIT_WAIT・KEPT_NOTE | 117-121 (5) | pipeline/ingest | 入口の終了で録画の部品を止める待ち・録画中は残す知らせ(launch.py:787) |
| validate_url | 122-143 (22) | pipeline/ingest | 録画を始める URL の検査(YouTube の https だけ)。呼び手 begin 611 |
| _clean | 144-149 (6) | pipeline/ingest | yt-dlp の出力の整形 |
| probe_live | 150-178 (29) | pipeline/ingest | yt-dlp で配信中か(live_status)・題・チャンネルを調べる = 配信中の判定。呼び手 begin 613(self.probe 285)。intake.youtube_info 147・live_archive._probe_once 181 と近い二重 |
| _rec_view・_same_stream | 179-194 (16) | pipeline/ingest | 録画の要約・同じ配信か |
| recorder_data_dir・_read_token・is_local_url | 195-214 (20) | pipeline/ingest | 手元の録画の部品の作業データ・合言葉・手元 URL か |
| STUDIO_EXPORT_*・studio_review・studio_audio | 215-244 (30) | pipeline/export | 書き出しの音量(スタジオの settings-ui.json の review を読む。review.js の既定と二重)。Exporter の audio 引数 267 |
| studio_lag | 245-253 (9) | human/review | スタジオの「反応の遅れ補正」を読む(録画の画面の I の最初の選び方)。手動マークの画面用(/live/api/info 528) |
| Live.__init__ | 254-303 (50) | pipeline/ingest | 【要相談】Live が detector・requests・livetx・reporter・exporter・archiver・cleaner を全部持つ玄関。分割後は ingest(録画元)+ run(見回り)+ 各部品への配線 |
| Live.cfg・_read_cfg・cfg_scope・enabled | 304-330 (27) | app | 設定の節 live を 1 回読む。run には spec で渡す形に(prefs を直接読むのは app の仕事) |
| Live.recorders・find | 331-344 (14) | pipeline/ingest | 録画元の一覧(合言葉つき)・id で引く |
| Live.auto_cfg | 345-353 (9) | pipeline/spec | 書き出したあとの自動の流れ(after/cut/engine/model/pad)= 指定の束 |
| Live.exporter(property) | 354-362 (9) | pipeline/export | Exporter を最初に使うとき作る |
| Live.archiver(property) | 363-378 (16) | pipeline/run | Archiver を組み立てる(配信後の全自動の依存を注入: adopt・request・compare・recordings) |
| Live.cleaner・auto_delete | 379-393 (15) | manage/keep | 録画を自動で消す Cleaner(live_cleanup.py)を組み立てる |
| Live.studio_call | 394-405 (12) | app | 【要相談】取り込んだスタジオの API を ToolClient(autorun)経由で呼ぶ。呼び手 live_detect 204・live_archive(studio=)・launch.py:725・live_export._studio_exported 1169・cases の expire。autorun.ToolClient と同じ位置づけ(app) |
| Live.list_recordings・recording_state | 406-426 (21) | pipeline/ingest | 録画元ごとの録画の一覧・状態。呼び手 live_detect 551・live_archive recordings=・live.py:687 |
| Live.local_token・expected_version | 427-439 (13) | pipeline/ingest | 手元の録画の部品の合言葉・期待する版 |
| Live.request・call・ping | 440-479 (40) | pipeline/ingest | 録画元への HTTP |
| Live.handle_get・_handle_get | 480-537 (58) | app | GET /live/… の配線(peaks 501・marks/exports 508・info 525・relay 531) |
| Live.handle_post・_handle_post・_api_post | 538-592 (55) | app | POST /live/… の配線(begin・marks・export・adopt・peaks・archive) |
| Live._ids・_down・_find_active | 593-608 (16) | pipeline/ingest | 録画元・録画 id の検査・同じ配信を録画中か |
| Live.begin | 609-650 (42) | pipeline/ingest | URL の配信状態を調べ、配信中なら録画を始める。呼び手 _api_post 561・begin_request 660 |
| Live.begin_request・active_requests | 651-676 (26) | human/friend | 友人のライブ配信の依頼 → 録画を始めて依頼に結びつける。呼び手 intake.py:596(live_begin)・launch.py:859 |
| Live.flush_pools | 677-696 (20) | human/friend | 組の溜めの残りを届ける見回り(autorun.flush_pools を呼ぶ)。呼び手 _tick 1128 |
| Live.expire_unseen | 697-713 (17) | manage/keep | 3 日見ない自動の切り抜きをごみ箱へ(cases.expire_unseen を呼ぶ)。呼び手 _tick 1129 |
| Live.stop_long_requests | 714-740 (27) | human/friend | 友人の依頼の録画を 6 時間で止める(録画元の stop)。呼び手 _tick 1126 |
| Live._request_for・deliver_dir・_auto_deliver_for | 741-769 (29) | human/friend | 録画が友人の依頼に結びついていれば依頼の設定で・自分の配信の自動の切り抜きを確認なしで届ける(live.autoDeliver) |
| Live._rec_status | 770-785 (16) | pipeline/ingest | 録画元の録画の状態(firstPdt 等) |
| Live.export_studio | 786-801 (16) | pipeline/export | スタジオのマークから書き出す(POST /live/api/export の studio 形)。_request_for(794)で友人の依頼を重ねる |
| Live._adopt_secs・_pad_secs | 802-833 (32) | pipeline/analyze | 採用の区間の秒を決める・自動の採用に余白を足す(M8) |
| Live._studio_ok | 834-842 (9) | app | studio_call の失敗を LiveError に |
| Live._studio_adopt_mark | 843-881 (39) | pipeline/analyze | 【要相談】スタジオの配信(kind live)を登録して採用のマークを足す。スタジオのマーク = 候補データ(analyze)であり、人の採用(上書き)の置き場(human/review)でもある。自動採用が人の上書きの置き場に直接書く |
| Live.adopt | 882-919 (38) | pipeline/analyze | 【要相談】マーク+書き出し依頼(M1)。人の採用(manual)も自動(auto・archive)も同じ口。呼び手 live_detect 489・live_archive adopt=。origin で ① と ② を区別するだけ |
| Live.ytt・_ytt・recent | 920-970 (51) | app | api/ytt/live(ヘッダーの録画の札の status/stop)。呼び手 launch.py:1011 |
| Live._relay | 971-1006 (36) | app | 録画元の HLS を同じオリジンで中継 |
| Live.on_patch | 1007-1010 (4) | app | 設定を変えたとき見回りを起こす。呼び手 launch.py:1060 |
| Live.note | 1011-1017 (7) | manage/ops | 同じ知らせを見回りのたびに記録しない(全 live_* が使う) |
| Live.start・close | 1018-1037 (20) | pipeline/ingest | 見回りの開始・終了(close が detector・livetx・archiver・exporter・録画の部品を止める) |
| Live._own_proc〜_stop_recorder | 1038-1098 (61) | pipeline/ingest | 入口の終了で録画の部品を止める(録画中なら残す)。呼び手 launch.py:786 |
| Live._watch・_guard | 1099-1115 (17) | pipeline/ingest | 見回りのスレッド・不具合でも続ける皮 |
| Live.tick・_tick の見回りの束ね(1123-1129) | 1116-1129 (14) | pipeline/run | 【要相談】検出・文字起こし・依頼の整理・6 時間止め・報告・組の溜め・片付けを 1 本で呼ぶ。run(配信中)の見回りに当たるが、友人(flush_pools・stop_long)・ops(reporter)・keep(expire)が同居 |
| Live._tick の録画の部品の起動・版の確認 | 1130-1168 (39) | pipeline/ingest | 手元の録画元が動いていなければ起動、古い版なら起動し直し、置き場所を伝える |
| Live.spawn | 1169-1194 (26) | pipeline/ingest | 録画の部品を入口と切り離して起動 |
| Live.health・_health | 1195-1238 (44) | manage/ops | 録画元ごとの状態・失敗の一覧・空き容量・検出の行を調子に渡す。作る所 launch.py:870(live_probe) |

### live_archive.py(1487 行)

2 つの別の仕事が `Archiver` に同居している。(1) P4「本番版への作り直し」= 速報版の録画から切った動画を、配信後のアーカイブから切り直した動画に入れ替える(取得し直し = ingest + 書き出し)。(2) M7「配信後の全自動」= アーカイブを解析して上位 N を自動採用 → 書き出し → 本番版 → 文字起こし → パック(run そのもの)。plan 7 では `pipeline/`(ingest・analyze・export・transcribe・run)へ。

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| docstring・import | 1-71 (71) | —(説明・import) | P4 と M7 の流れの説明(2-66) |
| CODE_DIR〜HEIGHTS(作り直しの定数) | 72-107 (36) | pipeline/ingest | 照合の窓・取得の時間切れ・再試行・入れ替えの間隔など(P4) |
| AFTER_MAX_AGE・AFTER_TOP_MAX・AFTER_MIN_SEC・AFTER_INSIDE・AFTER_FLOW | 108-112 (5) | pipeline/analyze | 配信後の自動採用の選び方の定数(上限・最小の長さ・録画の範囲に入る割合) |
| REF_SEC | 113-113 (1) | pipeline/ingest | 録画とアーカイブの時刻合わせに使う音の長さ |
| AFTER_LABELS・AFTER_END | 114-116 (3) | pipeline/run | 配信後の全自動の状態の表示名・終わりの状態 |
| SPEED_DIR・BUILD_DIR・UNAVAILABLE | 117-121 (5) | pipeline/ingest | 速報版の退避先・作りかけの置き場・取れない理由(メンバー限定など) |
| ArchiveError・Later | 122-134 (13) | pipeline/ingest | 作り直せない理由・今はできない(あとで) |
| run_proc | 135-149 (15) | ytt | 外のプログラムを 1 回動かす皮(ytt.tools.run)。テストが差し替える名前なので残してある |
| _num・_pause | 150-166 (17) | pipeline/ingest | 数の読み取り・やり直す前の待ち |
| probe_archive・_probe_once・readiness | 167-227 (61) | pipeline/ingest | yt-dlp でアーカイブの状態(was_live/post_live…)を調べる。live.probe_live・intake.youtube_info と近い二重 |
| fetch_full_audio | 228-257 (30) | pipeline/ingest | 配信の音を丸ごと yt-dlp で取る |
| worker_python・run_align | 258-276 (19) | pipeline/ingest | 速報版とアーカイブの音の照合(live_align_worker.py を子プロセスで) |
| inside・free_name | 277-292 (16) | ytt | パスの包含・空いている名前(fsio.is_inside・names の皮) |
| ended_at・_checked_within | 293-310 (18) | pipeline/ingest | 録画が終わった時刻・用意の確認が新しいか |
| after_count・pick_candidates | 311-342 (32) | pipeline/analyze | 自動採用の N の決め方・アーカイブの候補から録画の範囲に入る上位 N を選ぶ |
| after_progress・after_text | 343-368 (26) | pipeline/run | 配信後の全自動の進み具合・1 行の文(スタジオの LIVE の帯に出す) |
| Archiver.__init__ | 369-414 (46) | pipeline/ingest | 【要相談】P4(作り直し)と M7(配信後の全自動)の両方の依存(exporter・studio・adopt・compare・request)を持つ。分けるなら 2 クラス |
| Archiver.key・_load・_save_info・info_view | 415-451 (37) | pipeline/ingest | 録画ごとの記録 archive.json(用意の確認・afterStream の状態)を読み書きする。info_view は afterStream の進み具合も返す |
| Archiver._aset・_rec_jobs・targets・_queue・request・cancel | 452-518 (67) | pipeline/ingest | 作り直しの対象選び・順番待ち・画面のボタン(POST /live/api/archive)。呼び手 live.py:586・587 |
| Archiver.video_id・check・_info_put・_ready_info | 519-565 (47) | pipeline/ingest | アーカイブの用意の確認と結果の保存 |
| Archiver.start・close・_loop・_next・_vid_of・_audio_dir・_clean_audio・_full_audio・_next_of・busy | 566-659 (94) | pipeline/ingest | 作り直しのワーカー(1 本ずつ順に)・音の置き場・手が空いているか |
| Archiver._ended_at・auto_tick | 660-723 (64) | pipeline/ingest | 録画が終わった時刻・自動の作り直しの見回り(設定 live.autoArchive) |
| Archiver._after_get・_after_set・after_tick・_after_step | 724-801 (78) | pipeline/run | 配信後の全自動(M7)の状態機械: wait → analyze → export → done。呼び手 live.py(見回り) |
| Archiver._request_after・_after_on・_per_hour_for | 802-819 (18) | pipeline/run | この録画で配信後の全自動を動かすか・1 時間あたりの本数(友人の依頼の設定 > ホームの設定) |
| Archiver._after_begin | 820-879 (60) | pipeline/run | 用意の確認 → 時刻合わせ → アーカイブの解析を頼む(スタジオの queue に入れる 862-877 は analyze の仕事) |
| Archiver._known_offset・_after_offset | 880-932 (53) | pipeline/ingest | 録画の受信時刻とアーカイブの秒のずれ(照合) |
| Archiver._after_analyze・_studio_video | 933-962 (30) | pipeline/analyze | アーカイブの解析の進み具合を見て、済めば採用へ |
| Archiver._after_adopt | 963-1010 (48) | pipeline/analyze | 解析の候補から上位 N を選び Live.adopt(origin archive)を 1 本ずつ頼む。compare(973)を呼ぶ |
| Archiver._after_follow | 1011-1047 (37) | pipeline/run | 採用したジョブを見届ける(書き出し → 本番版 → 渡す)。全部済めば done、録画を消してよいと cleaner に伝える |
| Archiver.after_stream_hold | 1048-1064 (17) | manage/keep | 【要相談】録画を自動で消すのを待つ理由。呼び手 live.py:385(cleaner の hold)。配信後の全自動の状態を keep が聞く口 |
| Archiver.after_failures | 1065-1080 (16) | manage/ops | 配信後の全自動の失敗を調子の一覧に足す(文は live_failures.after_stream_failure)。呼び手 live.py:1226 |
| Archiver._stop | 1081-1086 (6) | pipeline/ingest | 取り消し・終了の検査 |
| Archiver._process | 1087-1195 (109) | pipeline/ingest | 1 本を本番版に作り直す(probe → align → fetch → verify → 入れ替え)。欠けのマークの新規書き出し(1176-1190)は export の _finish を呼ぶ |
| Archiver._speed_file・_rec_meta・_nearest_offset | 1196-1251 (56) | pipeline/ingest | 入れ替える相手の速報版・録画の記録・近いマークのずれ |
| Archiver._wav〜_audio・_check_media | 1252-1339 (88) | pipeline/ingest | 8kHz の wav に切る・照合・ffprobe の確認 |
| Archiver._build | 1340-1369 (30) | pipeline/export | スタジオ POST /api/live/section(YouTube 書き出しの中身)で本番版を作る |
| Archiver._residual | 1370-1382 (13) | pipeline/ingest | 本番版と速報版の音のずれを測る |
| Archiver._section | 1383-1441 (59) | pipeline/export | スタジオの section 書き出しを呼んで待つ |
| Archiver._swap・_update_clip | 1442-1487 (46) | pipeline/ingest | 速報版を作業用へ退避して本番版を元の名前に・.clip.json の source.live.archive を更新 |

### live_export.py(1180 行)

ライブの録画から区間を切り出して動画にする(`Exporter`)と、その元になるマークの正本(`MarkStore`)。Exporter の主体は `pipeline/export`。マーク(人が打つ)は `human/review`。書き出し後に `autorun.start_file` へ渡す所(`_handoff` 1091)が export → run の結び目。

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| docstring・import | 1-63 (63) | —(説明・import) | マーク・ジョブ・ディスク見張り・origin の説明(2-47) |
| VERSION・TOOL・MARKS_SCHEMA・JOBS_SCHEMA | 64-68 (5) | pipeline/export | 書き出しの道具名・記録の形 |
| ID_RE〜YT_ID_RE | 69-74 (6) | pipeline/ingest | 録画元・録画・セグメント・動画 ID の形(recproto の別名) |
| STUDIO_ID_RE・MAX_MARKS・MAX_MARK_SEC・LABEL_MAX | 75-78 (4) | human/review | マークの検査と上限(MarkStore 用) |
| AFTERS | 79-79 (1) | pipeline/spec | 書き出したあと none/check/auto の選択肢(prefs.py:81 と二重) |
| ORIGINS | 80-80 (1) | pipeline/analyze | 【要相談】採用の出どころ manual/auto/archive。自動の出力と人の上書きを同じ記録に混ぜて区別する鍵(plan 4-3) |
| AUTO_KEYS | 81-81 (1) | pipeline/spec | ジョブに覚える書き出したあとの設定(cut・engine・model) |
| FEEDBACK・FEEDBACK_MAX_BYTES | 82-83 (2) | human/review | 【要相談】採用の記録 live_feedback.jsonl。人の判定(良い/悪い)と自動の採用の両方が書く。書き手が ①(live.py:912 adopt 自動)と ②(cases._deliver/_discard)に割れる |
| TITLE_MAX・KEEP_JOBS | 84-85 (2) | pipeline/export | 書き出しの題の長さ・残すジョブ数 |
| LEN_TOL〜STATE_LABELS | 86-92 (7) | pipeline/export | 書き出しの長さの許容・見回り・状態の表示名 |
| GB・DISK_WARN・DISK_LOW・DISK_POLL | 93-96 (4) | manage/keep | 空き容量の注意・停止のしきい値(Exporter.disk 604 が使う) |
| HOLDS | 97-97 (1) | pipeline/run | 本番版を待ってから run へ渡す理由(holdFor archive) |
| ARCHIVE_RUN・ARCHIVE_ACTIVE | 98-101 (4) | pipeline/ingest | 本番版への作り直しの状態名(live_archive.RUN と同じ) |
| LiveError・Cancelled・Halted | 102-116 (15) | pipeline/export | 【要相談】live_* 全部が LX.LiveError を使う共通の例外。置き場は pipeline 共通か ytt |
| iso_epoch・epoch_iso・now_iso・video_id_of・compact_ts・safe_name・unique_base | 117-121 (5) | ytt | ytt の recproto・names の別名(テスト・live_archive・live_cleanup が LX. の名前で読む) |
| pick_folder | 122-130 (9) | pipeline/export | 書き出し先のフォルダを決める(ytt.names.pick_folder の皮) |
| rec_list | 131-139 (9) | pipeline/ingest | 録画元の録画の一覧(GET /live/list)。呼び手 live.py:411・421・606 |
| latest_per_mark | 140-150 (11) | pipeline/export | マークごとの最新のジョブ(live_archive・live_cleanup と共通) |
| _text | 151-154 (4) | ytt | 制御文字を落とす小物 |
| check_after | 155-166 (12) | pipeline/spec | 書き出したあと(none/check/auto)の検査。呼び手 live.py:573・790・887 |
| check_origin | 167-175 (9) | pipeline/analyze | 採用の出どころの検査 |
| clean_auto | 176-181 (6) | pipeline/spec | 設定 live.auto → ジョブに覚える {cut, engine, model} |
| check_streamer | 182-193 (12) | pipeline/spec | 配信者名の検査 |
| deliver_pool | 194-204 (11) | human/friend | ライブの切り抜きを n 本の組で届ける溜めの指定。autorun.clean_pool(316)が受ける |
| job_after | 205-210 (6) | pipeline/spec | ジョブの書き出したあと(古いジョブ互換) |
| studio_mark_id | 211-215 (5) | pipeline/export | スタジオのマーク id → マークの正本の id(lm-…) |
| check_studio | 216-238 (23) | pipeline/export | POST /live/api/export の studio の検査 |
| MarkStore | 239-371 (133) | human/review | 【要相談】録画 1 本のマークの正本(人が打つ add/update/delete)= 手動マークの上書きの置き場。ただし Exporter.add_studio 522 が自動採用のマークも upsert する |
| Exporter.__init__・_load・_save・_set・_trim | 372-443 (72) | pipeline/export | 書き出しのジョブの記録(exports.json)。起動し直しで途中のジョブを録画待ちに戻す |
| Exporter.snapshot | 444-466 (23) | pipeline/export | 画面用のジョブ一覧(失敗の文 failure と tx 状態を重ねる)。呼び手 live.py:514・521 |
| Exporter.failures | 467-476 (10) | manage/ops | 失敗の一覧(調子の live.failures)。呼び手 live.py:1224 |
| Exporter.feedback | 477-486 (10) | human/review | 【要相談】採用の記録を 1 行書く。呼び手 live.py:912・launch.py:725(cases の feedback=)・live_detect 661(compare)・live.py:706 |
| Exporter._tx_states | 487-498 (12) | pipeline/run | 文字起こしへ渡したジョブの run の状態(autorun.snapshot を読む) |
| Exporter.busy・_busy_error | 499-510 (12) | pipeline/export | 書き出し・作り直しの途中のマークは書き換えさせない |
| Exporter.add_studio・add | 511-571 (61) | pipeline/export | 書き出しジョブを足す。request(友人の依頼 {rid・deliverDir・deliverBatch・autoDeliver} 560-564)を job に残す |
| Exporter.cancel・pending | 572-591 (20) | pipeline/export | 取り消し・途中のジョブがあるか |
| Exporter.disk_paths・disk・_disk_low | 592-653 (62) | manage/keep | 【要相談】書き出し先・live\work の空き容量の見張りと「空き待ち」の判断。見張りは keep/ops、止める判断は export(_next_ready 688) |
| Exporter.start・close・_loop・_next_ready | 654-740 (87) | pipeline/export | 書き出しのワーカー・録画が区間まで届くのを待つ |
| Exporter._query・_sources・_backup_for | 741-780 (40) | pipeline/ingest | 録画元のセグメントを問い合わせ、主→予備の録画元を選ぶ |
| Exporter._cancelled・_process | 781-850 (70) | pipeline/export | 1 本の書き出し(取得 → 作り直し → 音量 → 検証 → 完了) |
| Exporter._fetch | 851-881 (31) | pipeline/ingest | 録画元からセグメントを取る |
| Exporter._encode・target・_audio_cfg・_adjust_audio・_run・_base・_title | 882-1027 (146) | pipeline/export | セグメントをつないで正確な区間に切り 30fps に・音量/ラウドネス・名前の規則 |
| Exporter._finish | 1028-1078 (51) | pipeline/export | 検証済みの動画を置き、.clip.json(鍵 JSON)を書き、書き出したあとの渡しへ |
| Exporter._after_note・_handoff | 1079-1116 (38) | pipeline/run | 【要相談】書き出したあと autorun.start_file へ渡す(動画ファイルの run)。request があれば友人の設定(1107-1111)を渡す。export→run の結び目で、呼び手 _finish 1068・_hand_over 1131 |
| Exporter._hand_over・release_hold・_retry_handoffs | 1117-1157 (41) | pipeline/run | 空き待ち・本番版待ちの渡しを今する。release_hold の呼び手 live_archive 1027・1162 |
| Exporter._studio_exported | 1158-1176 (19) | pipeline/export | スタジオのマークを「書き出し済み」にする(POST /studio/api/live/exported) |
| _disk_usage | 1177-1180 (4) | manage/keep | 空きの取得(shutil.disk_usage の皮) |

### live_detect.py(706 行)

配信中の盛り上がりの検出(`Detector`)の入口側。計算は子プロセス live_excite_worker.py。検出・候補・自動採用の中核なので主に `pipeline/analyze`。人の採用・見送り・戻す(decisions.json)は ②(human/review)の書き込み。呼び手は live.py(detector 292・api_get 504・api_post 579・tick 1123・health 1233・failures 1227)。

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| docstring・import | 1-51 (51) | —(説明・import) | ファイルの分担(config.json・decisions.json・peaks.json…)・API・自動採用 M11・安全弁 D-13/D-14 の説明 |
| CODE_DIR〜CHAT_ORDER | 52-66 (15) | pipeline/analyze | ワーカーの場所・心拍の止まり判定・自動採用の試し回数など |
| _dump | 67-71 (5) | ytt | JSON をバイト列に(汎用) |
| start_logged | 72-92 (21) | ytt | 常駐の子プロセスをログに足す形で起動する。呼び手 live.py:1186(録画の部品)・Detector._spawn 300。tools の皮 |
| _ids_ok | 93-97 (5) | pipeline/ingest | 録画元・録画 id の形(パスに使う前の検査)。呼び手 live.py:595 |
| clean_spec | 98-109 (12) | pipeline/analyze | スタジオの解析の設定 → ワーカーの spec |
| overlay | 110-124 (15) | pipeline/analyze | 候補に「まだワーカーが当てていない人の決定」を重ねる(自動の出力 + 上書きを読む形の先取り) |
| SEEN_KEEP_SEC〜UNCONFIRMED_EVERY | 125-131 (7) | pipeline/analyze | 自動採用の安全弁の数(1 録画 10 本・未確認 20 本で休む) |
| Detector.__init__ | 132-158 (27) | pipeline/analyze | 状態の初期化 |
| Detector.dir〜adopt_for | 159-190 (32) | pipeline/analyze | 設定(detect・autoAdopt)の読み・友人の依頼の録画の設定(requests_cfg・adopt_for) |
| Detector.wake | 191-197 (7) | pipeline/analyze | 友人の依頼で録画を始めた直後に見回りを起こす。呼び手 live.py:666 |
| Detector.spec・config・write_config | 198-218 (21) | pipeline/analyze | ワーカーに渡す config.json |
| Detector._length_hint | 219-237 (19) | pipeline/analyze | 【要相談】人が選んだ区間の長さの目安(dev/eval_marks の結果)を ワーカーの config に入れる。学習データ(B)として ③ に置く形へ。live_excite_worker.length_hint(294)を呼ぶ |
| Detector.tick・heartbeat・_hb_age・running・_ensure・_spawn・_kill・stop | 238-334 (97) | pipeline/analyze | ワーカー(検出の子プロセス)の見張り・起動・停止。tick は自動採用(auto_tick)も呼ぶ |
| Detector.folder・forget・view・series・_load_series・worker_view | 335-342 (8) | pipeline/analyze | 候補・系列の読み取り(peaks.json + 決定)。forget の呼び手 live_cleanup(録画を消したとき) |
| Detector._decisions | 343-395 (53) | pipeline/analyze | 【要相談】decisions.json の読み取り。人の採用・見送り(②)と自動の採用(①)が同じファイル。plan 4-3(自動の出力と人の上書きを混ぜない)の対象 |
| Detector.api_get | 396-441 (46) | app | GET /live/api/peaks の整形(候補+決定+文字+時間の枠)。呼び手 live.py:504 |
| Detector.decide・api_post | 442-476 (35) | human/review | 人の採用・見送り・戻すを decisions.json に残す(POST /live/api/peaks)。呼び手 live.py:579 |
| Detector.adopt | 477-497 (21) | pipeline/analyze | 【要相談】候補を Live.adopt(M1)に通して決定を残す。人(manual。api_post 469)と自動(auto。auto_tick 610)の両方の口 |
| Detector._load_fails・_give_up | 498-516 (19) | pipeline/analyze | 自動の採用を諦めた候補の記録(auto_failures.json) |
| Detector.unconfirmed・auto_count・paused_why | 517-547 (31) | pipeline/analyze | 【要相談】安全弁: 未確認の自動の切り抜きの数(manage/cases の数を live.unconfirmed で注入 = launch.py:869)で自動採用を休む。manage の数を pipeline が読む向き |
| Detector._target_recordings・auto_tick | 548-622 (75) | pipeline/analyze | 自動採用の中核(録画中+終わって 6 時間以内の録画で、枠の中の候補を waitMin 後に採用) |
| Detector.compare | 623-664 (42) | eval/drill | 配信中の候補とアーカイブの候補を比べて live_feedback.jsonl に detect_compare を書く(L5 の材料)。呼び手 live_archive.py:973。精度の測定 |
| Detector.health | 665-688 (24) | manage/ops | 調子の detect の行。呼び手 live.py:1233 |
| Detector.failures | 689-706 (18) | manage/ops | 調子の失敗(kind detect)。呼び手 live.py:1227 |

### live_excite_worker.py(1561 行)

配信中の盛り上がりの検出の子プロセス(標準ライブラリだけ・numpy 不使用)。録画元からセグメントを取って音量を測り、チャットを読み、`ytt_core.excite` の式で候補を出す。ほぼ全部 `pipeline/analyze`(plan 3: 「盛り上がりの式(excite)・チャットとコメント・候補・自動採用・配信中の検出」)。録画元からのセグメント取得だけ ingest。

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| docstring・import | 1-60 (60) | —(説明・import) | ワーカーの流れ(録画元 → ffmpeg → 1 秒の箱 → excite.Online → PeakBook)の説明 |
| WORKER_VERSION〜QUEUED_EVERY | 61-95 (35) | pipeline/analyze | 周期・保存・メモリ・チャットの上限など |
| LENGTH_HINT_ENV〜LENGTH_HINT_MIN_* | 96-101 (6) | pipeline/analyze | 【要相談】長さの目安(M10)の定数。dev/eval_marks の結果を読む。autorun.py:129-138 と二重。学習データ(B) |
| SPEC_RANGES | 102-103 (2) | pipeline/analyze | 解析の設定の範囲(studio/analyze.py の validate_settings と二重) |
| EVAL_MARKS_RE・EVAL_READ_MAX | 104-105 (2) | pipeline/analyze | 【要相談】測定結果ファイルの名前の形(autorun.py:137 と二重) |
| ID_RE・iso_epoch・PEAK_ID_RE・LEVEL_*・STATS・NOCHAT_HINTS・BLOCK_HINTS | 106-117 (12) | pipeline/analyze | 録画元との約束の別名・候補 id の形・音量測定とチャット取得の定数 |
| MeasureError・NoTool・RecorderDown | 118-130 (13) | pipeline/analyze | ワーカーの例外 |
| pid_alive・take_lock | 131-177 (47) | ytt | プロセスの生存確認・1 つだけ動かす鍵(汎用) |
| write_json・append_jsonl | 178-189 (12) | ytt | JSON の書き込み(汎用) |
| clean_requests・clean_detect | 190-209 (20) | pipeline/analyze | config.json の検査(requests は友人の依頼の録画の設定) |
| _level・_read_levels・measure_levels | 210-262 (53) | pipeline/analyze | ffmpeg で 1 秒ごとの RMS を測る |
| parse_chat_line | 263-290 (28) | pipeline/analyze | yt-dlp の live_chat 1 行 → (時刻, 重み) |
| _HINT_CACHE・length_hint・clean_hint・spec_with_hint | 291-365 (75) | pipeline/analyze | 【要相談】人が選んだ長さの目安を、測定結果(evals/marks/*.json の clipLength.suggest)から読み、新しく受け持つ録画の長さ・前の割合に使う。呼び手 live_detect.py:222。plan 9「dev の測定結果から決めている作りを学習データとして ③ に置く形に直す」対象 |
| RecorderClient | 366-398 (33) | pipeline/ingest | 録画元(recorder.py)の API を読む(GET /live/list・status・セグメント本体) |
| launch_process | 399-405 (7) | ytt | 子プロセスの起動(汎用) |
| ChatFeed | 406-649 (244) | pipeline/analyze | yt-dlp の live_chat を配信 1 本に 1 つ起動し、ファイルを読む(止まったら起動し直し・取れない配信は音だけ) |
| RecState | 650-963 (314) | pipeline/analyze | 録画 1 本の状態(1 秒の箱・欠け・遅れ・Online・PeakBook・保存) |
| parse_segments | 964-983 (20) | pipeline/ingest | HLS のセグメント一覧の解析 |
| Worker | 984-1535 (552) | pipeline/analyze | 全録画を回す本体(受け持つ録画の選び・順番待ち・測る・締める・飛ばした区間の測り直し)。1264-1275 は友人の依頼の録画ごとの設定(requests)を読む = 指定の束の一部として config.json 経由で渡される |
| main | 1536-1561 (26) | pipeline/analyze | ワーカーの起動(--config・--parent) |

### live_tx.py(346 行)

配信中の候補の文字起こし(D-11 案 b)。確定した候補の音を録画元から取り、whisper.cpp(GPU)の子プロセスで認識して tx.json に残す。plan 3 の `pipeline/transcribe`(「配信中の文字起こし」)。呼び手 live.py(livetx 294・tick 1124・close 1028)・live_detect.py(text_for 486・view 406・recent_ids 435)。

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| docstring・import | 1-24 (24) | —(説明・import) | 候補の文字起こしの説明(設定 liveTx・守り・SLOTS の枠) |
| WORKER・WCPP_*・DEFAULT_MODEL・TX_*・FAIL_PAUSE_AFTER・PAUSE_SEC・RECENT_SEC・TEXT_MAX・DOC_MAX | 25-40 (16) | pipeline/transcribe | whisper.cpp の置き場所・モデル名(editor の tx_engines.py と二重で、test_live_tx が同じことを確かめる 28-29 行目のコメント) |
| wav_args | 41-46 (6) | pipeline/transcribe | セグメントをつないだ .ts から 16kHz モノラルの wav を作る ffmpeg の引数 |
| LiveTx.__init__ | 47-76 (30) | pipeline/transcribe | 状態・SLOTS の初期化 |
| LiveTx.cfg・data_dir・paths・ready・_ffmpeg・status | 77-118 (42) | pipeline/transcribe | 設定 liveTx・whisper.cpp とモデルがあるか(ready) |
| LiveTx.folder・_load・_save・view・items・text_for・recent_ids・record・_record_error | 119-173 (55) | pipeline/transcribe | tx.json(候補 id → 文字)の読み書き |
| LiveTx.tick | 174-220 (47) | pipeline/transcribe | 確定した候補を見つけて列に入れる(detector の候補を読む) |
| LiveTx.start・close・_loop | 221-254 (34) | pipeline/transcribe | 1 本ずつ処理する裏のスレッド |
| LiveTx._after・_one | 255-316 (62) | pipeline/transcribe | 1 候補の処理(録画元からセグメントを取って wav → 認識)。取得は exporter の仕組みを使う(ingest の操作) |
| LiveTx._run_in_slot・_run_worker | 317-346 (30) | pipeline/transcribe | 重い処理の枠(SLOTS の live-tx)を取って live_tx_worker.py を子プロセスで動かす |

### health.py(366 行)

「調子」(GET /api/health)を集める部品。全部 `manage/ops`。作る所 launch.py:870(live_probe=Live.health・accuracy_probe=Accuracy.snapshot を注入)。

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| docstring・import | 1-18 (18) | —(説明・import) | 調子の説明 |
| CACHE_SEC〜DATA_TOOLS | 19-32 (14) | manage/ops | 数え直す間隔・異常終了の対象 exe・データ置き場の表 |
| top_items・data_sizes | 33-65 (33) | manage/ops | 作業データの大きさ(ツールごと上位 12 項目)。置き場所の規則は ytt.datadir |
| disk_free | 66-85 (20) | manage/ops | ドライブごとの空き容量。live_export.Exporter.disk(592)と近い二重 |
| tool_version・tool_versions | 86-99 (14) | manage/ops | ffmpeg・ffprobe・yt-dlp の版 |
| _stamp_to_epoch・count_jsonl・count_client_errors・count_autorun_failed | 100-157 (58) | manage/ops | エラーの件数。count_autorun_failed 151-155 が post_analyze を除く(測る用が消えれば不要)。読む記録 = autorun-runs.jsonl(pipeline/run が書く) |
| _wevtutil_events・_evt_field・crash_counts | 158-225 (68) | manage/ops | Windows イベントログから異常終了を数える(直近 7 日) |
| WORKER_CRASH_MARK・WORKER_HUNG_MARK・count_worker_incidents | 226-251 (26) | manage/ops | 「編集」の serve.log の文言を数える(editor の ed_jobs のログ文言と二重にそろえる) |
| _try・Health | 252-366 (115) | manage/ops | 調子 1 つにまとめる。snapshot 325 が versions・worker・disk・errors・live・accuracy・data・crashes を返す |

### prefs.py(489 行)

ホームの設定(prefs.json)。plan 4-8「設定は 1 ファイル(pipeline / human / manage / eval の節)」へ移すときの元。節ごとに持ち主の層が違う: autorun・live → pipeline、intake → human/friend、backup → manage/keep、accuracy → eval、streamer・hidden・keymap → 画面(app)。読み書き・既定値・検査は `app`(汎用の検査は ytt)。

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| docstring・import | 1-40 (40) | —(説明・import) | 節の説明(autorun・streamer・keymap・intake・backup・hidden・live・accuracy) |
| MAX_BYTES・SECTIONS・PATCHABLE・各 *_MODES・HIDE_*・COMBO_RE | 41-57 (17) | app | 設定の節と上限。AUTORUN_MODES(47)は autorun.MODES、CUT_METHODS(48)は autorun.CUTS と二重 |
| DEFAULTS | 58-71 (14) | app | 各節の既定値。plan では節ごとに各層(pipeline/spec・human・manage・eval)が既定値を持つ形へ。参照 accuracy.py:291・backup.py:238・intake.py:422・autorun.py:2004 |
| INTAKE_RANGES・INTAKE_INTS | 72-74 (3) | app | 節 intake(human/friend)の範囲。autorun.py:2005 が deliverBatch の範囲を読む |
| FOLDER_MAX・RECORDERS_MAX・RECORDER_* | 75-79 (5) | app | 節 live.recorders(pipeline/ingest)の検査 |
| LIVE_QUALITIES〜LIVE_WAIT_MIN | 80-91 (12) | app | 節 live(pipeline)の選択肢。recorder・live_export・excite・editor の名前と二重(コメントに「と同じ」が並ぶ) |
| PrefsError | 92-95 (4) | ytt | 設定の検査の例外(ytt.settings.SettingsError の皮) |
| _clean_autorun | 96-120 (25) | app | 節 autorun(pipeline の mode/top/cut/onFail/friendLength)の検査 |
| _clean_folder | 121-135 (15) | ytt | PC の中の絶対パスだけ許す汎用の検査(ネットワークは断る) |
| _clean_backup | 136-151 (16) | app | 節 backup(manage/keep)の検査 |
| _clean_accuracy | 152-166 (15) | app | 節 accuracy(eval)の検査 |
| _clean_live | 167-221 (55) | app | 節 live(pipeline: 録画元・画質・自動・検出・配信後)の検査 |
| _int_in・_has_ctrl・_put_bool・_drop_oldest | 222-245 (24) | ytt | 汎用の検査の小物 |
| _clean_keys | 246-261 (16) | ytt | 小さな節を鍵ごとに直す汎用の検査 |
| _clean_live_detect〜LIVE_PARTS | 262-300 (39) | app | live の中の小さな節(detect・liveTx・autoAdopt・auto)の検査 |
| _read_live | 301-320 (20) | app | 保存してある live 節を壊れた鍵だけ既定に戻して読む |
| _clean_intake | 321-337 (17) | app | 節 intake(human/friend)の検査 |
| _clean_keymap | 338-352 (15) | app | 共通の再生キー(編集・スタジオで同じ)の検査 = 画面の設定 |
| CLEANERS | 353-357 (5) | app | 節 → 検査関数の表 |
| _clean_name | 358-366 (9) | app | 配信者名・録画元名の検査 |
| _read_streamer | 367-374 (8) | app | 【要相談】配信者の記憶(文書/配信/チャンネル → 名前)の読み取り。人の入力から作る学習データ(plan 6 の (B))= 置き場は ③、読み手は ①(字幕の色)。今は prefs.json の 1 節 |
| _read_hidden | 375-383 (9) | app | 一覧の非表示の読み取り(画面の表示だけ。データは消さない) |
| guess_streamer | 384-395 (12) | pipeline/spec | 【要相談】配信者(字幕の色)を覚えた名前→チャンネル名から決める。呼び手 autorun.py:671(pipeline)と launch.py:1038(app)。入力は prefs の streamer。① が読む学習データ側に置く形が筋 |
| Prefs(__init__・_load・_section・get・_save・patch) | 396-445 (50) | app | 設定ファイルの読み書き(ytt.settings.SettingsFile の上)。get/patch の呼び手 launch.py:1048・1053 |
| Prefs.remember | 446-464 (19) | app | 【要相談】配信者の記憶を 1 件書く。呼び手 autorun.py:2257(pipeline が設定を書く向き違反)・launch.py:1064 |
| Prefs.hide | 465-489 (25) | app | 一覧の項目を非表示にする・戻す(UIKit.hide)。呼び手 launch.py:725・live.py:707 |

### mount.py(226 行)

ツール(studio/transcribe/cut2resolve)の serve.py を入口のサーバーに取り込む仕組み。全部 `app`(plan 7: 「home/launch.py・mount.py … → app/」)。

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| docstring・import | 1-27 (27) | —(説明・import) | 取り込みの決まりの説明 |
| _mount_spec・MOUNTS | 28-42 (15) | app | 取り込めるツールの表と CSP(studio は YouTube プレイヤー用に script-src を足す 36) |
| TOKEN_HEADER・SAFE_METHODS・YTT_API・TOKEN_FAIL | 43-51 (9) | app | 合言葉の見出し・画面の共通 API の場所。launch.py が使う(69・109) |
| MountError | 52-55 (4) | app | 取り込みの失敗 |
| tool_modules・check_no_collision・load_serve | 56-102 (47) | app | serve.py を別名で読み込み、部品名の衝突を調べる |
| inject_token・send_redirect | 103-119 (17) | app | 画面に合言葉を入れる・転送 |
| make_handler | 120-178 (59) | app | ツールの Handler を /prefix の下で動くように包む(合言葉検査・共通 API を入口へ回す・画面の転送) |
| Mount | 179-226 (48) | app | 取り込んだツール 1 つの起動・版・busy・停止 |

### cases.py(667 行)

案件(配信 1 本)の組み立て(スタジオ・文字起こし・パックの紐づけ)が本体で `manage/cases`。ほかに「自動でできた切り抜きの確認」(見た・採用して届ける・要らない)と、ごみ箱への片付けが同居している。呼び手 launch.py(snapshot 678・update 715・auto_review 724・locations 896)・autorun.py(find_pack 567・clip_live 294・read_studio 1313・locations 1313/1441・remember_delivered 2070)・live.py(expire_unseen 706)・friend_feedback.py・cleanup.py。

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| docstring・import | 1-51 (51) | —(説明・import) | 案件・紐づけ・自動でできた切り抜きの確認の説明 |
| SCHEMA・STATUSES・MAX_MEMO・MAX_JSON・_lock | 52-57 (6) | manage/cases | 案件ファイル cases.json の形・状態の選択肢 |
| TODO_ORDER・TODO_LABEL | 58-60 (3) | manage/cases | 「次にやること」の並び(ホームの「次にやること」と同じ表) |
| AUTO_ORIGINS | 61-61 (1) | manage/cases | 自動の出どころの名前(auto・archive)。autorun.py:295 も使う |
| AUTO_OPS・AUTO_KEEP | 62-63 (2) | human/review | 自動でできた切り抜きの確認の操作(seen/deliver/discard)・覚える数 |
| DISCARD_KIND | 64-64 (1) | manage/keep | ごみ箱/<日付>/ の下の種類の名前 |
| MARK_RE・STUDIO_TRIES・_busy・_busy_lock | 65-67 (3) | human/review | スタジオのマーク id の形・マークを不採用にするときの再試行・「要らない」の二重押し防止 |
| _readers | 68-70 (3) | manage/cases | 実行の記録を読む Reader の覚え |
| _read_json | 71-77 (7) | ytt | JSON を読む皮(fsio.read_json_file) |
| locations | 78-89 (12) | manage/cases | スタジオ data.json・文字起こしフォルダ・cases.json・live exports.json・実行の記録の場所。autorun.py:1313・1441・launch.py:896 が使う |
| read_studio・read_transcripts・find_pack | 90-106 (17) | manage/cases | 各ツールのデータを読む(読むだけ)。txindex の規則に従う |
| _upload_date_ms・_int_ms・_stream_time | 107-127 (21) | manage/cases | 配信日の目安 |
| _case_extras | 128-164 (37) | manage/cases | 案件 1 件ごとの合計と「次にやること」 |
| clip_live | 165-178 (14) | manage/cases | 切り抜きの .clip.json の source.live を読む = 成果物の鍵の読み取り(plan 7: 「成果物の鍵の読み取り」は manage/cases)。呼び手 autorun.py:294 |
| auto_info | 179-189 (11) | manage/cases | 自動でできた切り抜きの出どころ・点数・控え |
| live_failures_by_mark | 190-217 (28) | manage/cases | ライブの書き出しの失敗の文をマークごとに引く(文は live_failures だけが作る) |
| _auto_records・_apply_review | 218-238 (21) | manage/cases | 人の確認を重ねる(「自動の出力 + 人の上書き」のうち表示側) |
| build | 239-285 (47) | manage/cases | 案件の一覧を組み立てる |
| load_saved・_write・snapshot | 286-323 (38) | manage/cases | 案件ファイルの読み書き・画面用の一覧 |
| _check_case_id | 324-329 (6) | manage/cases | 案件 id の検査 |
| update | 330-353 (24) | manage/cases | 案件の状態・メモを付ける。呼び手 launch.py:715 |
| ReviewError | 354-361 (8) | human/review | 確認の操作の失敗 |
| auto_review | 362-389 (28) | human/review | 【要相談】POST /api/cases/auto(見た・採用して届ける・要らない)。呼び手 launch.py:724。人の判定を残す点は human/review、届ける点は human/friend、片付ける点は manage/keep。cases の中にあるが案件の仕事ではない |
| _find_auto | 390-401 (12) | human/review | 自動でできた切り抜きを一覧から引く |
| remember_delivered | 402-412 (11) | manage/cases | 【要相談】まとめて実行が届けた切り抜きに「届けた」を残す。呼び手 autorun.py:2070(届けは human/friend)。向きは friend → cases の依存で、human から manage を読むのは向き違反 |
| EXPIRE_SEC | 413-415 (3) | manage/keep | 見ない自動の切り抜きを片付けるまで 3 日 |
| expire_unseen・_expire_one | 416-471 (56) | manage/keep | 【要相談】3 日見ない自動の切り抜きをごみ箱へ(要らないと同じ片付け)。呼び手 live.py:706。案件の状態を読んで片付けるので cases と keep の境 |
| _remember | 472-500 (29) | manage/cases | 案件ファイルに確認(seenAt・deliveredAt・discardedAt)を残す |
| _feedback_row | 501-510 (10) | human/review | live_feedback.jsonl の 1 行を作る |
| _deliver | 511-536 (26) | human/friend | 採用 = パックを zip にして Dropbox の 出力 へ(deliver.Deliveries。届ける) |
| _discard | 537-570 (34) | human/review | 【要相談】要らない = ごみ箱へ+マークを不採用に+誤検出の記録+文字起こしを非表示に。人の判定が主なので human/review、移動は keep |
| discard_clip | 571-589 (19) | manage/keep | 切り抜き 1 本ぶんをごみ箱へ+マークを不採用に。友人の「要らない」(friend_feedback)も mark_id 空で呼ぶ |
| _to_trash・_put_back・_write_manifest | 590-639 (50) | manage/keep | ごみ箱/<日付>/discard/<名前>/ へ移す・戻す・manifest を残す(cleanup と同じ場所・形) |
| _studio_ok・_studio_reject | 640-667 (28) | human/review | スタジオのマークを不採用(rejected)に(画面と同じ PUT /api/video) |

### intake.py(880 行)

友人の依頼の受付(Dropbox の見張るフォルダ)。ほぼ全部 `human/friend`(plan 7: 「intake.py・deliver.py・live_requests.py・friend_feedback.py → human/friend/」)。例外は、URL・動画ファイルの判定と 30fps 化(ingest の仕事)。受付が ① を呼ぶ所は `_process_urls` 696(`start_request`)と `_accept_video` 759(`start_file`)。作る所 launch.py:857。

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| docstring・import | 1-36 (36) | —(説明・import) | 受付の決まりの説明 |
| VIDEO_EXT〜DELIVER_BATCH_RANGE・REQ_*・STATE_FILE など | 37-67 (31) | human/friend | 受付の定数。BAD_NAME_CHARS・OUT_DIR は deliver.py:25・live.py:85 も読む |
| youtube_id | 68-86 (19) | pipeline/ingest | 【要相談】YouTube の URL → 11 文字の ID。ytt の recproto.video_id_of と近い二重。URL の判定は ingest |
| parse_lines・parse_url_file・decode_text・_accepted | 87-134 (48) | human/friend | .txt/.url の行の読み取り・文字コード |
| probe_video | 135-146 (12) | pipeline/ingest | ffprobe で音声のある動画か・長さ(動画ファイルの判定)。normalize.probe の皮 |
| youtube_info | 147-177 (31) | pipeline/ingest | yt-dlp で配信の長さ・状態・題名・チャンネル。STUDIO_FAKE の分岐 152-153 は疑似モードの if(plan 4-6 で eval/fake の登録口へ)。live.probe_live・live_archive._probe_once と近い二重 |
| is_os_file | 178-189 (12) | human/friend | OS・同期アプリのファイルを依頼として扱わない |
| _speaker_name・STYLE_KEYS・parse_style・parse_speakers | 190-241 (52) | human/friend | 依頼 JSON の話す人・字幕の色の検査 |
| CUT_LABELS・hms | 242-249 (8) | human/friend | 表示用の文 |
| parse_ranges・parse_cut・parse_weights・parse_video_tracks | 250-295 (46) | human/friend | 【要相談】依頼 JSON の区間・カット・重み・映像トラックの検査。autorun.clean_ranges(257)・clean_weights(271)・CUTS(80)と二重。形の検査は spec が持ち、friend は変換だけに |
| _deliver_how・parse_deliver_batch | 296-306 (11) | human/friend | 届け方(n 本ごとの組)の検査 |
| _safe_name・_streamer | 307-324 (18) | human/friend | 依頼 JSON のファイル名の検査・配信者名の照合 |
| Intake.__init__ | 325-354 (30) | human/friend | 受付の初期化(runner=AutoRunner・feedback・live_begin を注入) |
| Intake._load_state・_save_state・_today | 355-382 (28) | human/friend | intake-state.json の読み書き |
| Intake.start・close・_loop | 383-403 (21) | human/friend | 見張りのスレッド |
| Intake.snapshot・_cfg | 404-424 (21) | human/friend | 画面用の状態。呼び手 launch.py の GET /api/intake |
| Intake.scan・_settled・_count・_read_text | 425-503 (79) | human/friend | フォルダを見る・同期が終わったか |
| Intake._handle_request_json | 504-555 (52) | human/friend | 友人のアプリの依頼 JSON の受付 |
| Intake._handle_live_request | 556-615 (60) | human/friend | ライブ配信の依頼(2-15): 録画を始めて依頼に結びつける(live_begin = Live.begin_request)。終わっていれば ① 全自動へ |
| Intake._handle_manual_video・_handle_feedback・_handle_text | 616-653 (38) | human/friend | 手で送った動画・友人の「要らない」・手で送った URL |
| Intake._process_urls | 654-724 (71) | human/friend | URL の依頼を検査して ① に流す(runner().start_request 696)。配信の長さ・状態の確認に youtube_info |
| Intake._accept_video | 725-770 (46) | human/friend | 動画を確かめて作業データへコピーし ① に流す(runner().start_file 759)。上限(maxGB・maxHours)は友人の方針 |
| Intake._normalize_copy | 771-814 (44) | pipeline/ingest | 【要相談】コピーが 30fps でなければ作り直す(ytt.normalize を SLOTS 内で)。「URL か動画ファイルの取り込み」は ingest の仕事で、friend は呼ぶだけが筋 |
| Intake._record・_notify_rejected・_move | 815-880 (66) | human/friend | 受付の記録・断った理由の 失敗.txt・元のファイルを 受付済み/失敗 へ |

### 行数の合計(行き先別)

各行は「行き先: 行数(うち要相談の行数)」。「—」は docstring・import。

- **autorun.py**(2275 行): pipeline/run 807(要相談 189) / pipeline/spec 61 / pipeline/ingest 5 / pipeline/analyze 181(要相談 55) / pipeline/export 37 / pipeline/transcribe 146 / pipeline/pack 259(要相談 38) / human/friend 345(要相談 8) / human/proof 11(要相談 11) / manage/ops 40(要相談 38) / eval/drill 245 / app 65(要相談 57) / ytt 13 / —(説明・import) 60
- **launch.py**(1344 行): manage/keep 30 / manage/ops 59 / eval/drill 34 / app 1111 / ytt 12 / —(説明・import) 98
- **live.py**(1238 行): pipeline/run 30(要相談 14) / pipeline/spec 9 / pipeline/ingest 489(要相談 50) / pipeline/analyze 110(要相談 77) / pipeline/export 55 / human/review 9 / human/friend 103 / manage/keep 33 / manage/ops 51 / app 263(要相談 12) / —(説明・import) 86
- **live_archive.py**(1487 行): pipeline/run 222 / pipeline/ingest 926(要相談 46) / pipeline/analyze 115 / pipeline/export 89 / manage/keep 17(要相談 17) / manage/ops 16 / ytt 31 / —(説明・import) 71
- **live_export.py**(1180 行): pipeline/run 92(要相談 38) / pipeline/spec 38 / pipeline/ingest 90 / pipeline/analyze 10(要相談 1) / pipeline/export 638(要相談 15) / human/review 149(要相談 145) / human/friend 11 / manage/keep 70(要相談 62) / manage/ops 10 / ytt 9 / —(説明・import) 63
- **live_detect.py**(706 行): pipeline/ingest 5 / pipeline/analyze 459(要相談 124) / human/review 35 / manage/ops 42 / eval/drill 42 / app 46 / ytt 26 / —(説明・import) 51
- **live_excite_worker.py**(1561 行): pipeline/ingest 53 / pipeline/analyze 1382(要相談 83) / ytt 66 / —(説明・import) 60
- **live_tx.py**(346 行): pipeline/transcribe 322 / —(説明・import) 24
- **health.py**(366 行): manage/ops 348 / —(説明・import) 18
- **prefs.py**(489 行): pipeline/spec 12(要相談 12) / app 378(要相談 27) / ytt 59 / —(説明・import) 40
- **mount.py**(226 行): app 199 / —(説明・import) 27
- **cases.py**(667 行): human/review 125(要相談 62) / human/friend 26 / manage/cases 329(要相談 11) / manage/keep 129(要相談 56) / ytt 7 / —(説明・import) 51
- **intake.py**(880 行): pipeline/ingest 106(要相談 63) / human/friend 738(要相談 46) / —(説明・import) 36

**13 ファイル全体**(12765 行): pipeline/run 1151(要相談 241) / pipeline/spec 120(要相談 12) / pipeline/ingest 1674(要相談 159) / pipeline/analyze 2257(要相談 340) / pipeline/export 819(要相談 15) / pipeline/transcribe 468 / pipeline/pack 259(要相談 38) / human/review 318(要相談 207) / human/friend 1223(要相談 54) / human/proof 11(要相談 11) / manage/cases 329(要相談 11) / manage/keep 279(要相談 135) / manage/ops 566(要相談 38) / eval/drill 321 / app 2062(要相談 96) / ytt 223 / —(説明・import) 685

### 要相談の一覧

| ファイル | 行 | 名前 | 仮の行き先 | 理由 |
| --- | --- | --- | --- | --- |
| autorun.py | 102-106 | PAST_*・HISTORY_* | pipeline/run | 案件ごとの前回の結果(past)・履歴 API(launch.py:675)の件数。past は案件の行の「前回」= manage/cases が ① の結果 JSON を読む形が筋 |
| autorun.py | 129-138 | FRIEND_LENGTH_*・EVAL_MARKS_NAME_RE・EVAL_READ_MAX・FRIEND_*_RANGE | pipeline/analyze | 友人の区間の長さの実績(dev/eval_marks の結果)で自動候補の長さを決める定数。plan 9「学習データとして ③ に置く形に直す」対象。live_excite_worker.py:96-105 と二重 |
| autorun.py | 149-151 | REDO_STEPS | manage/ops | 「起動し直す」で止めてよい段(restart_info 923 専用)。起動し直しの判断は ops が持ち、run は実行中の段と ID を聞かれて返す口だけ持つ形が筋 |
| autorun.py | 174-230 | TOOL_NAMES・ToolClient | app | 取り込んだツール(studio/transcribe/cut2resolve)の API を HTTP で呼ぶ皮。pipeline が段を関数で呼べるようになるまでの接着。呼び手 launch.py:887・967・1103・live.py:402。pipeline に置くと app を読む向き違反なので app に出す |
| autorun.py | 290-297 | live_auto_origin | pipeline/pack | .clip.json の source.live.origin が auto/archive か(manage/cases の clip_live を呼ぶ)。パックのカット方法の決定(1740)に使う。鍵 JSON を pipeline が直接読む形にして cases への依存を断つ |
| autorun.py | 339-388 | Run.__init__ | pipeline/run | ① の状態に、友人の項目(request_id 362・deliver_dir 356・deliver_batch 347・pool 344・pack_marks 359)と測る用(preempted 378)が同居。382-387 で mode から段を決める。分割するなら ① の Run + 友人の付随情報 |
| autorun.py | 662-675 | _auto_streamer | pipeline/pack | 配信者(字幕の色)を覚えた名前→チャンネル名から決める。覚えた名前は prefs の streamer(人の入力から作る学習データ)。呼び手 1754・1806 |
| autorun.py | 824-893 | estimate | pipeline/run | 実行と同じ規則の見積もり(段ごとの本数)。ホーム画面の「実行」ボタン用。run の「計画だけ返す」口にするか app に置くか。呼び手 launch.py:735-736 |
| autorun.py | 923-957 | restart_info・_redo_work | manage/ops | 「起動し直す」の可否の材料(実行中の段のジョブをツールの一覧で確かめる)。呼び手 launch.py:939。ops から run を覗く口が要る |
| autorun.py | 1251-1306 | _loop | pipeline/run | 1 本のワーカー。あとから解析の取り出し(1256・1266・1297)・失敗時の届け残し(1294-1296)が同居 |
| autorun.py | 1307-1314 | _docs・_studio_video | pipeline/run | txindex.load・cases.read_studio を直接読む(plan では manage/cases)。段が使う「文書の一覧・配信の一覧」は run へ渡すか、manage を読まない形に |
| autorun.py | 1434-1478 | _friend_length | pipeline/analyze | 友人の区間の長さの実績(dev/eval_marks の最新結果)を依頼の自動候補に重ねる。学習データ(B)として ③ に置く形へ。呼び手 1486 |
| autorun.py | 1658-1673 | _edit_keeps | pipeline/pack | 「編集」のカット(edit.json の clips)を読む = human/cut の上書きを pack が読む口。今は HTTP /api/edit 経由 |
| autorun.py | 1935-1945 | _remember_styles | human/proof | 友人指定の字幕の色を文書の話者に覚える(POST /api/speakers/sub)= ② の上書きへの書き込み。① は書かず pack へ直接渡す形が筋 |
| autorun.py | 1950-1957 | _file_analyze | human/friend | 依頼 ③「全部人が行う」= 解析までで止める。plan 9 は ② の「確認してから届ける」を消すと書くが ③ の扱いは未記載 |
| live.py | 254-303 | Live.__init__ | pipeline/ingest | Live が detector・requests・livetx・reporter・exporter・archiver・cleaner を全部持つ玄関。分割後は ingest(録画元)+ run(見回り)+ 各部品への配線 |
| live.py | 394-405 | Live.studio_call | app | 取り込んだスタジオの API を ToolClient(autorun)経由で呼ぶ。呼び手 live_detect 204・live_archive(studio=)・launch.py:725・live_export._studio_exported 1169・cases の expire。autorun.ToolClient と同じ位置づけ(app) |
| live.py | 843-881 | Live._studio_adopt_mark | pipeline/analyze | スタジオの配信(kind live)を登録して採用のマークを足す。スタジオのマーク = 候補データ(analyze)であり、人の採用(上書き)の置き場(human/review)でもある。自動採用が人の上書きの置き場に直接書く |
| live.py | 882-919 | Live.adopt | pipeline/analyze | マーク+書き出し依頼(M1)。人の採用(manual)も自動(auto・archive)も同じ口。呼び手 live_detect 489・live_archive adopt=。origin で ① と ② を区別するだけ |
| live.py | 1116-1129 | Live.tick・_tick の見回りの束ね(1123-1129) | pipeline/run | 検出・文字起こし・依頼の整理・6 時間止め・報告・組の溜め・片付けを 1 本で呼ぶ。run(配信中)の見回りに当たるが、友人(flush_pools・stop_long)・ops(reporter)・keep(expire)が同居 |
| live_archive.py | 369-414 | Archiver.__init__ | pipeline/ingest | P4(作り直し)と M7(配信後の全自動)の両方の依存(exporter・studio・adopt・compare・request)を持つ。分けるなら 2 クラス |
| live_archive.py | 1048-1064 | Archiver.after_stream_hold | manage/keep | 録画を自動で消すのを待つ理由。呼び手 live.py:385(cleaner の hold)。配信後の全自動の状態を keep が聞く口 |
| live_export.py | 80-80 | ORIGINS | pipeline/analyze | 採用の出どころ manual/auto/archive。自動の出力と人の上書きを同じ記録に混ぜて区別する鍵(plan 4-3) |
| live_export.py | 82-83 | FEEDBACK・FEEDBACK_MAX_BYTES | human/review | 採用の記録 live_feedback.jsonl。人の判定(良い/悪い)と自動の採用の両方が書く。書き手が ①(live.py:912 adopt 自動)と ②(cases._deliver/_discard)に割れる |
| live_export.py | 102-116 | LiveError・Cancelled・Halted | pipeline/export | live_* 全部が LX.LiveError を使う共通の例外。置き場は pipeline 共通か ytt |
| live_export.py | 239-371 | MarkStore | human/review | 録画 1 本のマークの正本(人が打つ add/update/delete)= 手動マークの上書きの置き場。ただし Exporter.add_studio 522 が自動採用のマークも upsert する |
| live_export.py | 477-486 | Exporter.feedback | human/review | 採用の記録を 1 行書く。呼び手 live.py:912・launch.py:725(cases の feedback=)・live_detect 661(compare)・live.py:706 |
| live_export.py | 592-653 | Exporter.disk_paths・disk・_disk_low | manage/keep | 書き出し先・live\work の空き容量の見張りと「空き待ち」の判断。見張りは keep/ops、止める判断は export(_next_ready 688) |
| live_export.py | 1079-1116 | Exporter._after_note・_handoff | pipeline/run | 書き出したあと autorun.start_file へ渡す(動画ファイルの run)。request があれば友人の設定(1107-1111)を渡す。export→run の結び目で、呼び手 _finish 1068・_hand_over 1131 |
| live_detect.py | 219-237 | Detector._length_hint | pipeline/analyze | 人が選んだ区間の長さの目安(dev/eval_marks の結果)を ワーカーの config に入れる。学習データ(B)として ③ に置く形へ。live_excite_worker.length_hint(294)を呼ぶ |
| live_detect.py | 343-395 | Detector._decisions | pipeline/analyze | decisions.json の読み取り。人の採用・見送り(②)と自動の採用(①)が同じファイル。plan 4-3(自動の出力と人の上書きを混ぜない)の対象 |
| live_detect.py | 477-497 | Detector.adopt | pipeline/analyze | 候補を Live.adopt(M1)に通して決定を残す。人(manual。api_post 469)と自動(auto。auto_tick 610)の両方の口 |
| live_detect.py | 517-547 | Detector.unconfirmed・auto_count・paused_why | pipeline/analyze | 安全弁: 未確認の自動の切り抜きの数(manage/cases の数を live.unconfirmed で注入 = launch.py:869)で自動採用を休む。manage の数を pipeline が読む向き |
| live_excite_worker.py | 96-101 | LENGTH_HINT_ENV〜LENGTH_HINT_MIN_* | pipeline/analyze | 長さの目安(M10)の定数。dev/eval_marks の結果を読む。autorun.py:129-138 と二重。学習データ(B) |
| live_excite_worker.py | 104-105 | EVAL_MARKS_RE・EVAL_READ_MAX | pipeline/analyze | 測定結果ファイルの名前の形(autorun.py:137 と二重) |
| live_excite_worker.py | 291-365 | _HINT_CACHE・length_hint・clean_hint・spec_with_hint | pipeline/analyze | 人が選んだ長さの目安を、測定結果(evals/marks/*.json の clipLength.suggest)から読み、新しく受け持つ録画の長さ・前の割合に使う。呼び手 live_detect.py:222。plan 9「dev の測定結果から決めている作りを学習データとして ③ に置く形に直す」対象 |
| prefs.py | 367-374 | _read_streamer | app | 配信者の記憶(文書/配信/チャンネル → 名前)の読み取り。人の入力から作る学習データ(plan 6 の (B))= 置き場は ③、読み手は ①(字幕の色)。今は prefs.json の 1 節 |
| prefs.py | 384-395 | guess_streamer | pipeline/spec | 配信者(字幕の色)を覚えた名前→チャンネル名から決める。呼び手 autorun.py:671(pipeline)と launch.py:1038(app)。入力は prefs の streamer。① が読む学習データ側に置く形が筋 |
| prefs.py | 446-464 | Prefs.remember | app | 配信者の記憶を 1 件書く。呼び手 autorun.py:2257(pipeline が設定を書く向き違反)・launch.py:1064 |
| cases.py | 362-389 | auto_review | human/review | POST /api/cases/auto(見た・採用して届ける・要らない)。呼び手 launch.py:724。人の判定を残す点は human/review、届ける点は human/friend、片付ける点は manage/keep。cases の中にあるが案件の仕事ではない |
| cases.py | 402-412 | remember_delivered | manage/cases | まとめて実行が届けた切り抜きに「届けた」を残す。呼び手 autorun.py:2070(届けは human/friend)。向きは friend → cases の依存で、human から manage を読むのは向き違反 |
| cases.py | 416-471 | expire_unseen・_expire_one | manage/keep | 3 日見ない自動の切り抜きをごみ箱へ(要らないと同じ片付け)。呼び手 live.py:706。案件の状態を読んで片付けるので cases と keep の境 |
| cases.py | 537-570 | _discard | human/review | 要らない = ごみ箱へ+マークを不採用に+誤検出の記録+文字起こしを非表示に。人の判定が主なので human/review、移動は keep |
| intake.py | 68-86 | youtube_id | pipeline/ingest | YouTube の URL → 11 文字の ID。ytt の recproto.video_id_of と近い二重。URL の判定は ingest |
| intake.py | 250-295 | parse_ranges・parse_cut・parse_weights・parse_video_tracks | human/friend | 依頼 JSON の区間・カット・重み・映像トラックの検査。autorun.clean_ranges(257)・clean_weights(271)・CUTS(80)と二重。形の検査は spec が持ち、friend は変換だけに |
| intake.py | 771-814 | Intake._normalize_copy | pipeline/ingest | コピーが 30fps でなければ作り直す(ytt.normalize を SLOTS 内で)。「URL か動画ファイルの取り込み」は ingest の仕事で、friend は呼ぶだけが筋 |

### 層の向きの違反(この 13 ファイルの中で見つけたもの)

- pipeline(autorun)→ manage: `cases`(autorun.py:55。find_pack 567・clip_live 294・read_studio/locations 1313/1441・remember_delivered 2070)、`ytt_core.txindex`(1309。plan 7 では manage/cases)。
- pipeline(autorun)→ human/app: `prefs`(59。guess_streamer 671・remember 2257・DEFAULTS/INTAKE_RANGES 2004-2005)、`friend_feedback`(58)、`deliver`(57)。
- 向きは正しいが中身が友人寄り: human(intake)が `runner().start_request/start_file`(696・759)を呼ぶのは正しい向き。ただし ① の入口 `start_file`(autorun.py:806)が request_id・deliver_dir・deliver_batch・pool という友人の引数を持ち、pipeline の書き出し(live_export._handoff 1107-1112)も友人の依頼の項目をそこへ渡している。
- human(live_detect.api_post の decide / MarkStore)と pipeline(auto_tick・Live.adopt・_studio_adopt_mark)が同じ記録(decisions.json・スタジオのマーク・live_feedback.jsonl)に書く = plan 4-3「人の直しは ① の出力を書き換えない」に反する箇所。
- pipeline(live_detect)→ manage: 未確認の数(`Live.unconfirmed` = launch.py:869 が cases の数を注入)。
- pipeline → app: `autorun.ToolClient`(HTTP でツールを呼ぶ)。live.py:402 の `studio_call` も同じ。


## 4. スタジオ・cut2resolve の API・録画(11 ファイル)(元の見出し: studio / cut2resolve / recorder の行き先の表(読むだけの調査。2026-10-09))

対象: `src/studio/{store,analyze,common,serve,exporter,batch,rank,handoff,txlink}.py`・`src/cut2resolve/serve.py`・`src/recorder/recorder.py`。基準は `plan/role-restructure.md` の 3 節(目標の形)・7 節(行き先の表)。使ったモデル: Sonnet。

- 行 = 行番号(その物の先頭から次の物の直前まで。直前のコメント・空行はその物に含めた)。行数の合計は各表の下。
- 行き先の書き方: `pipeline/ingest|analyze|export|spec|run|pack`・`human/review|find`・`manage/cases|keep|ops`・`eval/fake`・`app`・`ytt`。`ヘッダ` = 先頭の説明と import(行き先を持たない)。`要相談` = 迷う物(理由の先頭の [A]〜[G] は末尾の「要相談の一覧」の番号)。
- `pipeline/spec` は plan の `pipeline/spec.py`(指定の束の形と既定値)。`pipeline/run` は `pipeline/run.py`(流れ・順番待ち)。
- 理由の中の数字は「呼び手の行」(`grep` で確認。ファイル名なしは同じファイル)。疑似(STUDIO_FAKE)の `if` が関数の中にある物は、その関数の行き先のまま行数に含め、末尾の「疑似の分岐」の表に行番号を別に挙げた。

### src/studio/store.py(1142 行)

> `store.py` は「候補のデータ(①)」と「人の判定(②)」が `data.json` の 1 つの辞書(マーク)に混ざっている。フィールドごとの分けは、この表の下の「data.json のフィールド表」にまとめた。

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| (docstring・import) | 1-25 | ヘッダ | モジュールの説明と import。store が analyze を import(21)する向きは human/review → pipeline で許される向き。逆に batch が store を呼ぶ(pipeline/run → human)は逆向き |
| SCHEMA | 26 | 要相談 | [A] data.json の schema 名 clip-studio/v1。data.json の持ち主を誰にするか(要相談 A)が決まるまで保留。_save 560 が書く |
| ID_RE / MAX_MARKS / MAX_MARK_SEC | 27-29 | human/review | マーク id の形・件数 500・長さ 3600 秒の上限。手動マークの検査(validate_marks 241,258 / check_times 124 / load_marks 218,226 / _collab_from 141 / SeriesCache._path 410) |
| MAX_REQUEST_RANGES | 30 | 要相談 | [C] 友人の依頼の区間数の上限 10。request_marks(787)だけが使う。request_marks の行き先が決まるまで保留 |
| MAX_TIME | 31 | human/review | 秒の巨大値の上限。_num_strict 88 → check_times / offset_from_anchors(手動の入力検査) |
| PART_KEYS | 32 | pipeline/analyze | 材料ごとの点数の鍵 audio/chat/comments(_clean_parts 100)。解析の材料の名前なので ① |
| RESTORE_STEPS | 33-34 | 要相談 | [A] data.json 退避後の戻し方の文言。画面の帯に出す(_load 492,506)。入れ物の持ち主しだい |
| STATUS_CLIENT | 35 | human/review | クライアントが設定できる状態 ''/adopted/rejected(= 人の判定)。_build_mark 172,188 |
| SERIES_KEEP | 36 | pipeline/analyze | 盛り上がりグラフのキャッシュ保持数 60(SeriesCache.__setitem__ 421) |
| DUP_TOL / EDIT_TOL | 37-38 | human/review | 同じ区間の許容 ±0.5 秒(_same 271)・手で動かしたと見なす 0.05 秒(_build_mark 173 / _touched 283 / mark_exported 888 / _add_collab_candidate 1094)。人の直しの検出に使う |
| SAVE_ERR | 39 | 要相談 | [A] 保存失敗の文言。_save 570 と set_ui 1142 が使う |
| UI_MAX_BYTES | 40 | ytt | 画面の設定 settings-ui.json の大きさ上限(Store.__init__ 452)。設定は 1 ファイル化(plan 4-8)で ytt/settings へ |
| コラボ定数(MAX_GROUPS 他) | 41-49 | human/review | グループ数 50・メンバー 8・転写の前後 2.5 秒・アンカーの傾きの範囲・最小の間隔(offset_from_anchors 319,325 / create_group 973,979 / _add_collab_candidate 1080)。② コラボの転写 |
| now_ms | 50-53 | ytt | 現在のミリ秒。store 内 6 か所 + batch.py:12,56,281 が import(pipeline/run が store に依存する逆向きの原因なので、汎用部品へ出す) |
| _pos_int | 54-57 | ytt | 正の整数判定(190,527)。ytt.schemas.is_int の薄い包み |
| _BY_SCORE | 58 | pipeline/analyze | 点数の高い順(adopt_top 769 / request_marks 824 / replace_auto 868)。候補の並べ方 = 自動採用の順 |
| _BY_TIME | 59-61 | human/review | 時刻順(request_marks 830 / replace_auto 870 / _add_collab_candidate 1111)。有効なマークの一覧の並べ |
| _ms_or_now | 62-66 | human/review | 保存された createdAt/updatedAt の読み直し(159,528,549)。data.json 読み込みの小道具 |
| _warn | 67-70 | 要相談 | [A] stderr に 1 行。data.json 読み込み(222,388,470 他)専用。入れ物しだい |
| BadMark | 71-74 | human/review | 区間・マーク・アンカーの検査エラー(人の入力の検査)。replace_auto 859 が ① の候補の検査にも使う点に注意 |
| _f | 75-84 | ytt | 数値化(NaN・bool は None)。_clean_parts 101 / _auto0 131 / _clean_server 152 / replace_auto 862 / _load_pieces 295 から。ytt.schemas.num と同機能で重複 |
| _num_strict | 85-90 | human/review | JSON の数値だけ受ける(check_times 116 / offset_from_anchors 311) |
| _clean_reasons | 91-95 | pipeline/analyze | 候補の理由文(6 件・40 字)。_clean_server 153 / replace_auto 862。理由は ① が付ける(コラボ転写の注記 1101 は ②) |
| _clean_parts | 96-106 | pipeline/analyze | 候補の材料ごとの点数 {audio,chat,comments}。_clean_server 153 / replace_auto 863 |
| _clamp_end | 107-113 | human/review | 終わりを配信の長さで切る。request_marks 806 / _add_collab_candidate 1083(人の指定区間・転写区間) |
| check_times | 114-128 | human/review | 開始・終了の検査と丸め。_build_mark 169 / request_marks 796 / replace_auto 858(① の候補の検査にも使う)/ collab 1080,1091 |
| _auto0 | 129-136 | pipeline/analyze | 最初の自動区間 auto0 の検査(_clean_server 160,161)。auto0 は ① の元の答え |
| _collab_from | 137-145 | human/review | コラボ転写の由来 {videoId,markId} の検査(_clean_server 162 / _add_collab_candidate 1075) |
| _clean_server | 146-166 | 要相談 | [C] サーバー由来の項目の整形。1 関数に ① の項目(src/score/reasons/parts/peak/auto0/auto0Orig)・② の項目(status の adopted/rejected・collabFrom・createdAt)・書き出し結果(status=exported/file/path/archived)・機械の採用の印(adoptedBy)が同居。下の「data.json のフィールド表」参照 |
| _build_mark | 167-207 | 要相談 | [C] クライアントのマークとサーバーの値を合成して 1 件にする中心。start/end/label/status を人が書き換え、exported の取り外し(174-179)と adoptedBy の取り外し(182-183)で ② が ① の印を消す。分割の本丸 |
| _new_mark | 208-212 | human/review | サーバーが作る手動マーク(prefix r=依頼 / a=自動 / c=コラボ)。呼び手 813,861,1108。a の呼び手 861 は ① 寄りだが、作るのは手動マークの型 |
| load_marks | 213-230 | human/review | 保存済みマークを 1 件ずつ読み、壊れた 1 件を飛ばす(526)。_build_mark(trusted)の包みなので分割は _build_mark に従う |
| _drop_archived | 231-238 | 要相談 | [D] archived(ライブ → アーカイブ本番版への入れ替え印)を live 以外から外す(526)。archived は書き出し結果の側のフィールドなので mark_exported と一緒に決める |
| validate_marks | 239-269 | human/review | PUT /api/video のマーク全体の厳しい検査(711)。人の直し(上書き)の入口そのもの |
| _same | 270-273 | human/review | 区間が ±0.5 秒で同じか(809 request_marks / 864 replace_auto) |
| _overlaps | 274-279 | human/review | 区間が重なるか(824 / 1088) |
| _touched | 280-285 | human/review | 人が手を入れた自動マークか(状態・ラベル・端の移動)。呼び手は replace_auto 846 だけ。② の判定を ① の再解析が読む唯一の接点 |
| _load_pieces | 286-302 | human/review | コラボのオフセット区分の読み込み(547) |
| offset_from_anchors | 303-329 | human/review | アンカー 1〜2 点から a,b を求める(set_anchor 1038) |
| _in_piece | 330-335 | human/review | オフセット区分の範囲判定(340,366) |
| _piece_for | 336-344 | human/review | 区分の選択(_to_ref 349) |
| _to_ref | 345-352 | human/review | この動画の時刻 → 基準動画の時刻(_transfer_collab 1051) |
| _from_ref | 353-372 | human/review | 基準動画の時刻 → この動画の時刻(_transfer_collab 1058) |
| _new_group_id | 373-379 | human/review | グループ id の発行(create_group 982) |
| _load_each | 380-391 | 要相談 | [A] videos/groups を 1 件ずつ読んで壊れた件を飛ばす(495,497)。入れ物の持ち主しだい |
| _replaced | 392-401 | 要相談 | [A] 辞書の写しの差し替え(576,580)。保存成功までメモリを変えない規則の道具 |
| SeriesCache | 402-445 | pipeline/analyze | 動画 ID → 盛り上がりグラフ。cache/series/<vid>.json に保存(最新 60)。グラフは ① の成果物。Store.series(455)が持ち、読むのは serve.py _video 208-209。analyze.prune_cache を呼ぶ(421) |
| class Store / __init__ | 446-459 | 要相談 | [A] 入れ物の本体。ui_file(452)・videos・groups・series・warning を持つ。serve.py:60 が作る |
| _quarantine | 460-473 | 要相談 | [A] 壊れた data.json の退避(490,499) |
| _load | 474-508 | 要相談 | [A] data.json を読み、壊れたら退避して空で起動(serve.py api_state 87 が warning を 1 度だけ出す) |
| _load_video | 509-532 | 要相談 | [B] 配信 1 件の読み込み。登録情報(id/kind/title/channel/duration/fileName/path/live)+ ② marks + ① analysis + rev/createdAt/updatedAt を 1 つの辞書に作る(524-528) |
| _load_group | 533-550 | human/review | コラボグループの読み込み(497) |
| take_warning | 551-557 | 要相談 | [A] 起動時の問題を 1 度だけ返す。serve.py:87 |
| _save | 558-573 | 要相談 | [A] videos+groups をまとめて data.json に保存(.bak を 1 世代)。全メソッドの書き込みがここを通る |
| _commit | 574-577 | 要相談 | [A] 動画 1 本の保存(584,680,691) |
| _commit_group | 578-581 | 要相談 | [A] グループ 1 件の保存(986,1011,1020,1028) |
| _bump | 582-587 | 要相談 | [A] 版(rev)を上げて保存。put_video 747 / adopt_top 777 / request_marks 831 / replace_auto 874 / mark_exported 904 / collab 1104,1112。rev は画面の保存のぶつかり検出(baseRev)にも使う |
| _need | 588-594 | 要相談 | [B] 登録済みの配信を取る(404)。多くのメソッドの入口 |
| _pub | 595-603 | 要相談 | [C] 配信の公開用の写し。marks(混在)と analysis(①)を深くコピー(602)。GET /api/video と feedback の入力(snap)になる |
| _summary | 604-615 | 要相談 | [B] 配信一覧の 1 行(件数 autoMarks/adopted/exported/candidates・hasSeries・groupId)。GET /api/videos 用。画面向けの要約なので app 寄りの可能性もある |
| list | 616-621 | 要相談 | [B] 配信一覧(serve.py:188) |
| get | 622-627 | 要相談 | [B] 配信 + series(serve.py 190,208,288,297) |
| internal | 628-633 | 要相談 | [B] path を含む内部用の写し(exporter.build_spec 261 だけ) |
| media_path | 634-639 | 要相談 | [B] /media 用の実パス(serve.py:219) |
| has | 640-643 | 要相談 | [B] 登録の有無(serve.py 309,334 / batch.py:233) |
| ensure | 644-682 | 要相談 | [B] 配信の登録(なければ作る)。batch.py:112,163(pipeline/run が呼ぶ = 向きが逆)/ serve.py 259,268,270,336。ファイルの長さ確認(650 media_info)と live の登録(665)を含む |
| delete | 683-700 | 要相談 | [B] 配信の削除(+ series 削除 692 + コラボから外す 696)。serve.py:315。ifNoMarks(入口の録画の片付け)は 689 |
| put_video | 701-756 | human/review | 確認画面の保存(PUT /api/video)。マーク全体の置き換え + 判定の feedback 行(714-754)+ 採用時のコラボ転写(752)。人の上書きの書き手の中心。呼び手 serve.py:321(画面・home/cases.py:662・home/live.py も HTTP 経由) |
| adopt_top | 757-779 | pipeline/analyze | 自動採用(上位 N 件を adopted + adoptedBy='auto')。人の判定ではない・feedback を書かない(759-760)。serve.py:326 ← home/autorun.py:1556。status を data.json に直接書く点は要注意(新形では ① の候補側の印にする) |
| request_marks | 780-833 | 要相談 | [C] 友人の依頼。区間指定(→ 採用済みマーク)= ② の「前に指定する」(spec の必須区間)と、足りない分を自動の上位で埋める = ① の自動採用が 1 関数に同居。serve.py:338 ← home/autorun.py:1541 |
| replace_auto | 834-877 | 要相談 | [C] 解析結果の反映。候補(① の出力)を新しい自動マークにする部分と、人が触れたマークを手動として残す部分(_touched 846・auto0Orig 853)= ① と ② の突き合わせが 1 関数。batch._apply 283 だけが呼ぶ。新形では「候補を書く(①)」と「候補 + 上書きの有効な一覧(human/review か manage/cases)」に割る |
| mark_exported | 878-910 | 要相談 | [D] 書き出し完了を記録(status=exported・file・path・archived)+ 初回なら feedback 'good/export' を書く(905-908)。前半は ① の書き出し結果(新形では鍵つき .clip.json)、後半は ② の記録。exporter の on_done に渡される(serve.py 296,360) |
| _video_group | 911-918 | human/review | 配信が入っているコラボグループ(コラボ全般で使う) |
| _group_summary | 919-930 | human/review | グループの要約(画面向け) |
| list_groups | 931-934 | human/review | serve.py:193 |
| get_group | 935-938 | human/review | serve.py:194 |
| _need_group | 939-947 | human/review | グループ取得(404) |
| _check_free | 948-956 | human/review | 対象配信が他のグループに入っていないか |
| _clean_ids | 957-968 | human/review | 配信 id のリストの整形 |
| create_group | 969-988 | human/review | serve.py:369 |
| add_members | 989-1003 | human/review | serve.py:373 |
| remove_member | 1004-1016 | human/review | serve.py:377(delete 696 からも) |
| _save_group | 1017-1022 | human/review | グループの変更保存 |
| delete_group | 1023-1030 | human/review | serve.py:382 |
| set_anchor | 1031-1044 | human/review | serve.py:386 |
| _transfer_collab | 1045-1064 | human/review | 採用 → 同じグループの他動画へ候補として転写(put_video 752 だけが呼ぶ) |
| _add_collab_candidate | 1065-1113 | human/review | 転写先に src='collab' の候補を足す。既に重なるマークがあれば範囲を広げ、理由欄に由来を足す(1096-1104)= ② が ① の自動マークの reasons/start/end を書き換えうる(新形では上書きにする) |
| get_ui | 1114-1117 | ytt | 画面の設定 settings-ui.json の読み(serve.py:183)。ytt_core.settings.SettingsFile の包み |
| set_ui_section | 1118-1129 | ytt | 画面の設定の 1 節だけ置き換え(serve.py:352) |
| set_ui | 1130-1142 | ytt | 画面の設定の全体書き(serve.py:354) |

**行数の合計(src/studio/store.py)**

- pipeline/analyze: 94 行
- human/review: 506 行
- ytt: 48 行
- 要相談: 469 行
- ヘッダ: 25 行
- 合計: 1142 行

#### store.py: data.json のフィールド表(① と ② の混ざり方)

`data.json` = `{schema: "clip-studio/v1", videos: {<動画ID>: {...}}, groups: {<グループID>: {...}}}`(`_save` 560)。①=自動の成果(pipeline/analyze・pipeline/export)・②=人の判定(human/review)。「混在」はフィールド 1 つに両方の書き手がいる物。

**配信 1 件(`videos[<id>]`。読み込みは `_load_video` 510-531)**

| フィールド | 中身 | 書き手(行) | 所属 |
| --- | --- | --- | --- |
| `id` `kind`(youtube/file/live) | 配信の識別 | `ensure` 645-665 | 配信の登録(要相談 B。暫定 manage/cases) |
| `title` `channel` `fileName` `path`(file のみ)`live`{recorder,recording,url,videoId}(live のみ) | 配信の登録情報 | `ensure` 659-679(題・チャンネルは `batch.add` 110・`_open_video`・依頼が渡す) | 配信の登録(要相談 B) |
| `duration` | 配信の長さ | 登録時 `ensure` 653(ファイルのみ)・解析が `replace_auto` 872-873 で上書き | 混在(登録 / ① の測定値) |
| `rev` `updatedAt` `createdAt` | 版と時刻(画面の保存のぶつかり検出 `put_video` 709) | `_bump` 582-586 | 入れ物(要相談 A) |
| `analysis`{at,signals,counts,warnings,spec,type} | 解析 1 回分の記録 | `batch._apply` 281 → `replace_auto` 871。`_feedback_row` 144-148 が読んで feedback に写す | **①**(archive にも同じ物が残る) |
| `marks[]` | 下の表 | — | 混在 |

**マーク 1 件(`marks[]`。整形は `_clean_server` 146-164・`_build_mark` 167-205)**

| フィールド | 中身 | 書き手(行) | 所属 |
| --- | --- | --- | --- |
| `id` | `a…`自動 / `r…`依頼 / `c…`コラボ / `m…`手動(253) | `_new_mark` 208・`validate_marks` 253 | 共通 |
| `start` `end` | 現在の区間 | 初期値 = 候補(`replace_auto` 858-861 = ①)。画面で動かすと上書き(`put_video` → `_build_mark` 169 = ②)。動かしたかは `auto0` との差(`_touched` 283・`_feedback_row` 159) | **混在**(初期値 ① / 端の調整 ②) |
| `label` | 名前 | `_build_mark` 192 | **②** |
| `src` | `auto` / `manual` / `collab` | `replace_auto` 847(人が触れた auto は manual に変わる = ① → ② の持ち替え)・`_add_collab_candidate` 1109 | 混在(出自の印) |
| `score` `peak` `reasons` `parts` | 点数・ピーク・理由文・材料ごとの点数 | `replace_auto` 862-863。`reasons` にはコラボ転写の注記も足される(`_add_collab_candidate` 1101 = ②) | **①**(reasons だけ混在) |
| `auto0` | 最初の自動区間 [開始, 終わり] | `replace_auto` 863。コラボ候補も持つ(1109) | **①** |
| `auto0Orig` | 手動に変わったマークの最初の自動区間 | `replace_auto` 853 のみ | **①** |
| `live` | 配信中に打ったマークか | 画面 → `_build_mark` 194(home/live.py の PUT /api/video) | **②**(配信中の上書き) |
| `status` | `""`(候補) / `adopted` / `rejected` / `exported` | `adopted`・`rejected` は人(`put_video` 735-738)。機械の採用も同じ値(`adopt_top` 776・`request_marks` 818,827)。`exported` はサーバー(`mark_exported` 894) | **混在**(最も重い。人の判定 ②・自動採用 ①・書き出し済みの印が 1 つの値) |
| `adoptedBy` | `auto`(自動採用) / `request`(友人の区間指定) | `adopt_top` 776・`request_marks` 814,818,827。人が状態を変えると外れる(`_build_mark` 182-183) | ①(`auto`)/ human/friend→spec(`request`)。「機械の印」 |
| `file` `path` `archived` | 書き出した mp4(出力先からの相対 / 絶対)・ライブ → アーカイブ本番版への入れ替え済み | `mark_exported` 894-903。時刻や状態を変えると外れる(`_build_mark` 174-179,196-199) | **書き出し結果**(pipeline/export の出力の参照。要相談 D) |
| `createdAt` | 作成時刻 | `_new_mark` 210・`_ms_or_now` | 共通 |
| `collabFrom` | コラボ転写の元 {videoId, markId} | `_add_collab_candidate` 1109 | **②** |

**コラボグループ(`groups[<id>]`。`_load_group` 534-549)**: `id` `name` `base` `members` `offsets`{動画ID: [{a,b,tStart,tEnd}]} `createdAt` `updatedAt` = すべて **②**(human/review のコラボ)。

**data.json の外で store / analyze が持つ物**: `cache/series/<動画ID>.json`(盛り上がりグラフ = ①・`SeriesCache`)・`feedback.jsonl` と `.old`(人の判定の行 = ②・`analyze.py` 137-262)・`archive/<動画ID>.json.gz`(材料と直近 5 回の候補 = ① の自分の記録・`save_archive`)・`cache/chat` `cache/signals` `cache/meta`(① の取得キャッシュ)・`settings-ui.json`(画面の設定 = ytt)。

**data.json を読む外の読み手**(形を変えるときに影響する): `src/editor/ed_store.py:296-299`(配信のチャンネル名・題とコラボのまとまり)・`src/home/cases.py:79-83`(場所の表に載せている)・`dev/eval_marks.py:115`(マーク・feedback・archive を突き合わせる)・`ytt_core/txindex`(マークの `path` ↔ 文字起こし)。HTTP の書き手: `home/autorun.py`(queue/add 1490・request-marks 1541・adopt-top 1556・export 1588)・`home/cases.py:649-662`(PUT /api/video で不採用に)・`home/live.py:845`(PUT /api/video, baseRev つき)・`home/live_export.py`(POST /api/live/exported)。

**① と ② が混ざる 4 つの接点**(分けるならここ)
1. `status` / `adoptedBy` の 1 つの値に、人の判定・自動採用・書き出し済みが同居(`_clean_server` 148-164・`adopt_top` 776・`mark_exported` 894)。
2. `replace_auto` 834-876: ① の再解析が ② の手を入れたマークを読んで(`_touched` 280-283)手動として残す。**① が ② を読む**唯一の接点。plan 4-3 の「人の直しは ① の出力を書き換えない」を満たすには、① は候補だけ書き、有効な一覧(候補 + 上書き)は human/review か manage/cases が作る形になる。
3. `_build_mark` 174-183: 画面の保存が `exported` や `adoptedBy` を外す(② が ① の印を消す)。
4. `_add_collab_candidate` 1096-1104: コラボ転写(②)が自動マークの `reasons` と `start/end` を書き換える。

**分けた場合の素描**(参考。決めるのは要相談 A・B・C・D): ① が書く `candidates`(id・start・end・score・reasons・parts・peak・auto0・analysis・series・自動採用の id)/ ② が書く `overrides`(マーク id ごとの status・label・端の調整・手動マーク・コラボのマーク・collabFrom)/ 書き出し結果は `.clip.json`(鍵つき)/ 有効な一覧 = 候補 + 上書きを合成する読み取り(`replace_auto` と `_pub` の後半)。

### src/studio/analyze.py(1031 行)

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| (docstring・import) | 1-26 | ヘッダ | 解析の説明と import。23-25 行で ytt_core.excite を analyze.X の名前で再公開(batch・テスト・e2e が呼ぶ)= excite は plan 通り pipeline/analyze へ |
| API_BASE | 27 | pipeline/analyze | YouTube Data API の URL(fetch_comments 595) |
| チャットキャッシュの定数(CHAT_CACHE_KEEP / MAX_BYTES) | 28-30 | pipeline/analyze | チャット取得のキャッシュの件数・合計上限(prune_chat_cache 331 / chat_cache_limit 310) |
| MAX_FEEDBACK_BYTES | 31 | human/review | feedback.jsonl の上限 32MB(_feedback_write 174) |
| MAX_DURATION〜META_TIMEOUT | 32-40 | pipeline/analyze | 解析の上限・待ち時間・冒頭の減点・archive 保持数・付加情報の TTL(load_sig 388 / download_audio 279 / _levels 862 / run_analyze 他) |
| FB_SETTING_KEYS | 41 | human/review | feedback の行に写す解析設定の鍵(_feedback_row 148) |
| SPEC_KEYS | 42-44 | pipeline/analyze | 結果・archive に残す設定の鍵(_save_record 953 / run_analyze 1018)。spec.py と同じ鍵一覧になる |
| work_dir | 45-48 | pipeline/analyze | 解析の作業フォルダ(511,982 と serve.py:562 が起動時に消す)。common.p の包み |
| chat_cache_dir | 49-52 | pipeline/analyze | チャットのキャッシュの場所(287,333,473) |
| sig_cache_dir | 53-56 | pipeline/analyze | 音量の解析結果のキャッシュの場所(378,402) |
| feedback_path | 57-60 | human/review | feedback.jsonl の場所(_feedback_write 170) |
| LIVE_NO_ANALYZE | 61-64 | pipeline/analyze | 「ライブの録画は解析できません」の文言。validate_source 79 / store.adopt_top 766 / request_marks 802 |
| validate_live | 65-70 | pipeline/ingest | ライブの録画 1 本の記述の検査 → source 辞書。serve.py:261(common.check_live の包み) |
| validate_source | 71-85 | pipeline/ingest | URL か動画ファイルの判定 → source 辞書。batch.py:98 / serve.py 258,269,335。plan の「ingest: URL か動画ファイルの判定」そのもの |
| validate_settings | 86-98 | pipeline/spec | 解析の設定(件数・長さ・感度・重み・チャットの待ち)の既定値と丸め。batch.py:90。plan の spec.py(指定の束の形と既定値) |
| make_spec | 99-107 | pipeline/spec | source + settings → 解析 spec(ファイルならチャット・コメント無効)。batch.py:237 |
| new_job | 108-113 | pipeline/analyze | 解析ジョブの辞書(state/phase/progress/cancel/proc…)。batch.py:237 |
| chat_public | 114-119 | pipeline/analyze | チャット取得の進み具合の公開形。batch.py 67,272(画面向けの整形は app に寄せる余地あり) |
| cancel_job | 120-125 | pipeline/analyze | 解析の中止(proc/proc2/proc3 を止める)。batch.py 144,182 |
| skip_chat | 126-135 | pipeline/analyze | チャット待ちだけ打ち切る(人の操作だが、ジョブに対する操作)。batch.py:152 |
| _fb_lock | 136-139 | human/review | feedback.jsonl の追記ロック |
| _feedback_row | 140-164 | human/review | feedback の 1 行(区間・点数・材料・解析の設定・auto0 との差 dStart/dEnd・adoptedBy)。人の判定の記録だが ① の analysis(signals/spec/type)を読んで写す |
| _feedback_write | 165-182 | human/review | feedback.jsonl に追記(32MB で .old へ)。live 配信は書かない(166-169) |
| feedback_for_mark | 183-191 | human/review | 採用・不採用・書き出しの行。store.py 750,908 から |
| FB_EXTRA_EVENTS | 192-199 | human/review | 手で足した/消した/採用の取り消し/判定済みの削除の対応表 |
| nearest_auto | 200-222 | human/review | 手で足したマークに一番近い自動マーク(manual_add の nearAuto)。store.py:740 |
| feedback_event | 223-233 | human/review | manual_add 等の行。store.py:754 |
| _append_line | 234-244 | human/review | jsonl の 1 行追記(書きかけを繋がない)。汎用なので ytt.fsio に出せる |
| _move_feedback_to_old | 245-264 | human/review | 大きくなった feedback.jsonl を .old の末尾へ移す |
| download_audio | 265-285 | pipeline/ingest | yt-dlp で音声を取得(_levels 858 だけ)。267-268 に疑似の分岐(common.fake → fake_media) |
| chat_cache_path | 286-289 | pipeline/analyze | チャット 1 本のキャッシュのパス(422,501,515) |
| _usable_chat | 290-294 | pipeline/analyze | 取得済みのチャットが使えるか(423,440,501) |
| prune_cache | 295-303 | ytt | 古い順に消す汎用の整理(402 save_sig / 721 fetch_meta / store.py:421 SeriesCache)。中身は解析と無関係な汎用処理 |
| chat_cache_limit | 304-312 | 要相談 | [E] チャットキャッシュの合計上限(環境変数 STUDIO_CHAT_CACHE_MB)。呼び手 330,332 と serve.py:580(起動時の片付け) |
| _chat_use_lock / _chat_in_use | 313-318 | pipeline/analyze | 解析が使用中のチャットの印(消さないため) |
| use_chat_cache | 319-328 | pipeline/analyze | 使用中の印の増減(974,985) |
| prune_chat_cache | 329-376 | 要相談 | [E] チャットキャッシュを件数・合計の上限に収める。キャッシュの片付け(manage/keep)でもあるが、使用中の印と先読み(PREFETCH)を見るので pipeline/analyze の状態に依存。呼び手 477 と serve.py:578 |
| sig_path | 377-380 | pipeline/analyze | 音量の解析結果のパス |
| load_sig | 381-397 | pipeline/analyze | 音量の解析結果の読み(852)。感度などを変えた再解析で使い回す = 鍵つき成果物の使い回しの先取り |
| save_sig | 398-406 | pipeline/analyze | 音量の解析結果の保存(874) |
| download_chat | 407-482 | pipeline/analyze | チャットのリプレイ取得(yt-dlp)+ 先読み待ち + キャッシュ。411-421 に疑似の分岐(STUDIO_FAKE_CHAT / 死んだフック STUDIO_FAKE_CHAT_DELAY)。呼び手 514,561 |
| チャット先読みの定数・状態 | 483-491 | pipeline/analyze | PREFETCH_MAX / _pf_lock / _pf_done / PREFETCH |
| prefetch_chat | 492-534 | pipeline/analyze | 待ちの配信のチャットを先に取る。494 に fake 判定。batch.py:220 |
| cancel_prefetch | 535-544 | pipeline/analyze | 先読みの中止。435,550 と batch.py:58 |
| cancel_all_prefetch | 545-553 | pipeline/analyze | 終了の流れで先読みを全部中止(serve.py:596) |
| start_chat | 554-573 | pipeline/analyze | チャット取得を別スレッドで開始(993) |
| TS_RE | 574-576 | pipeline/analyze | コメントの時刻表記の正規表現 |
| fetch_comments | 577-615 | pipeline/analyze | 動画コメント欄の取得(YouTube Data API commentThreads)。579-585 に疑似の分岐(STUDIO_FAKE_COMMENTS)。呼び手 920。rank.yt_get と別に urlopen を持つ(API 呼び出しの重複) |
| LIST_MIN | 616-618 | pipeline/analyze | チャプター一覧とみなす個数 3 |
| stamps_from | 619-636 | pipeline/analyze | コメント → 時刻と重み(585,613) |
| meta_dir | 637-641 | pipeline/analyze | 動画の付加情報のキャッシュ場所 |
| slim_meta | 642-674 | pipeline/analyze | yt-dlp -J の動画情報から記録に使う項目だけ取り出す |
| _meta_ok | 675-681 | pipeline/analyze | キャッシュの形の確認 |
| load_meta | 682-691 | pipeline/analyze | 付加情報のキャッシュ読み(24 時間) |
| fetch_meta | 692-726 | pipeline/analyze | 付加情報の取得(記録用)。694-699 に疑似の分岐(STUDIO_FAKE_META)。呼び手 734 |
| start_meta | 727-743 | pipeline/analyze | 付加情報を別スレッドで取る(995) |
| ARCHIVE_ID_RE | 744-747 | pipeline/analyze | archive の id の形 |
| archive_path | 748-751 | pipeline/analyze | archive/<vid>.json.gz の場所 |
| load_archive | 752-761 | pipeline/analyze | archive の読み(767)。dev/eval_marks.py が読む |
| save_archive | 762-780 | pipeline/analyze | 1 秒ごとの材料と直近 5 回の候補を残す = ① の自分の記録(plan 4-5)。呼び手 956 |
| audio_levels | 781-805 | pipeline/analyze | ffmpeg で 1 秒ごとの音量(868,870) |
| parse_chat | 806-849 | pipeline/analyze | live_chat.json → 1 秒ごとの活気(898) |
| _levels | 850-879 | pipeline/analyze | 音量(全体・高音域)。キャッシュの再利用と音声取得(download_audio) |
| _chat_signal | 880-916 | pipeline/analyze | チャットの待ちと解析 |
| _comment_signal | 917-931 | pipeline/analyze | コメントの時刻 → 材料 |
| _weights | 932-944 | pipeline/analyze | 重みと付加情報の待ち |
| _save_record | 945-960 | pipeline/analyze | archive へ記録(956) |
| _stop_helpers | 961-976 | pipeline/analyze | 失敗・中止時の後始末 |
| run_analyze | 977-1031 | pipeline/analyze | 解析 1 ジョブの本体 → job['result']{source,candidates,series,signals,counts,warnings,spec}。batch.py:246。plan の analyze(盛り上がりの式・チャット・コメント・候補)の中心 |

**行数の合計(src/studio/analyze.py)**

- pipeline/ingest: 42 行
- pipeline/analyze: 740 行
- pipeline/spec: 22 行
- human/review: 135 行
- ytt: 9 行
- 要相談: 57 行
- ヘッダ: 26 行
- 合計: 1031 行

### src/studio/common.py(662 行)

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| (docstring・import) | 1-21 | ヘッダ | 共通部品の説明と import |
| CODE_DIR | 22-24 | ytt | コード・静的ファイル・seed.json の場所。handoff.runtime_dir 40 / txlink 15 / rank.SEED 37 / serve.py:39,168 が使う |
| _load_core | 25-37 | ytt | ytt_core を sys.path に足す(YTT_CORE_DIR)。src/ytt がパッケージになれば不要(消せる) |
| _load_core() 呼び出し・import・_home | 38-41 | ytt | ytt_core の import と、データ置き場 _home(datadir.override('studio')) |
| KEY_RE | 42 | ytt | API キーの形(set_api_key 198)。キー保管は ytt/settings(plan 7) |
| VID_RE | 43 | ytt | YouTube の 11 文字 ID。analyze 494 / exporter 21,239,301 / serve.py 32,213 / rank 層全体で共有 |
| YT_API_BASE | 44 | ytt | YouTube Data API の URL(analyze.py:27 / rank.py:27) |
| MEDIA_EXT | 45-47 | pipeline/ingest | 動画・音声の拡張子(check_media_path 266 / serve.py:222 の /media)。cut2resolve/serve.py:85 の MEDIA_EXTS は別の集合 |
| ApiError | 48-53 | ytt | 全モジュール共通の例外(Handler が捕まえる)。cut2resolve/serve.py:108 にも別の同名クラス |
| Cancelled | 54-57 | ytt | 中止の例外(analyze / common.run_capture / rank) |
| set_home | 58-64 | ytt | データ置き場を変える(serve.py:58) |
| home | 65-68 | ytt | データ置き場(serve.py 85,557,559,647) |
| p | 69-73 | ytt | データ置き場の中のパス(analyze 6 か所・rank・serve 他) |
| fake | 74-78 | ytt | 疑似の判定の 1 行(STUDIO_FAKE == '1')。呼び手 analyze 267,411,494,579,694 / batch 88,99 / exporter 204,301 / rank 60 / serve 71,83,347 / common 621,656。分岐が eval/fake の登録に置き換わると不要になる |
| fake_media | 79-86 | eval/fake | 疑似の動画の代わりのファイル(STUDIO_FAKE_MEDIA)。analyze 268 / exporter 205 |
| find_tool | 87-91 | ytt | 外部プログラムの確認(STUDIO_FFMPEG などの環境変数 → PATH)。analyze / batch / exporter / serve / store 651 |
| replace_file | 92-96 | ytt | 共有違反の再試行つき置き換え(fsio.replace_retry の包み) |
| atomic_write | 97-101 | ytt | 一時ファイル経由の書き込み(fsio.atomic_write の包み) |
| _URL_RE / redact | 102-110 | ytt | 署名つき URL を伏せる。analyze / exporter / serve / rank |
| _error_log_lock / old_log_name | 111-120 | ytt | ログ回しの道具 |
| rotate_log | 121-126 | ytt | ログを 1 世代回す(fsio.rotate と重複)。exporter 69 / serve 470,485 |
| migrate_old_logs | 127-137 | manage/keep | 旧い名前の studio.log.old を改名する起動時の移行。serve.py:560 |
| log_failure | 138-150 | ytt | 処理エラーを studio-errors.log に残す(analyze / exporter / rank / serve / store / handoff が呼ぶ)。書く道具は下の層に置き、集約・日報は manage/ops |
| permission_message | 151-157 | ytt | アクセス拒否の文言(analyze 1026 / exporter / serve 151) |
| tail_reason | 158-163 | ytt | 外部プログラムの stderr から理由を拾う(analyze 3 か所)。exporter.reason と近い別実装 |
| fmt_ts | 164-168 | ytt | HH:MM:SS.mmm |
| fmt_ms | 169-173 | ytt | M:SS |
| num | 174-183 | ytt | 範囲に丸めた数(analyze.validate_settings 多数 / store.py:525) |
| get_api_key | 184-195 | ytt | API キー(環境変数 → config.json)。analyze.fetch_comments 586 / rank.yt_get 62 / serve 82。plan: 保管は ytt/settings |
| set_api_key | 196-206 | ytt | API キーの保存(serve.py:347) |
| parse_video_id | 207-233 | pipeline/ingest | URL / ID → YouTube 動画 ID(analyze.validate_source 80 / check_live 260) |
| LIVE_ID_RE / LIVE_RECORDER_RE / YT_HOSTS | 234-239 | pipeline/ingest | ライブの録画 id・録画元・許す YouTube ホスト。recorder の録画 id の形と同じ |
| check_live | 240-262 | pipeline/ingest | 録画 1 本の記述の検査(analyze.validate_live 67 / store._load_video 518) |
| check_media_path | 263-270 | pipeline/ingest | 手元の動画・音声ファイルのパス検査(analyze 76) |
| file_video_id | 271-275 | pipeline/ingest | ファイル動画の id = 'f' + sha1(絶対パス)(analyze 77) |
| watch_url | 276-280 | ytt | https://www.youtube.com/watch?v=… の組み立て。analyze 3 か所 / rank 2 / serve 73 で共有 |
| ytdlp_out | 281-287 | pipeline/ingest | yt-dlp -o のテンプレート(% のエスケープ)。analyze 272,447 / exporter |
| メディア情報のキャッシュ(MEDIA_CACHE_MAX 他) | 288-297 | ytt | media_info の StampCache と ffmpeg の覚え |
| _probe_media | 298-306 | ytt | ffmpeg -i で長さ・映像・音声(run_short 経由) |
| media_info | 307-320 | ytt | 長さと音声の有無。analyze 859 / exporter 9 か所 / store.ensure 650 |
| media_info_known | 321-325 | ytt | 覚えた結果だけ見る(exporter.promote 109) |
| remember_media_info | 326-331 | ytt | 名前の付け替え後に結果を引き継ぐ(exporter 111) |
| 子プロセスの定数・集合(KILL_GRACE / STOP_WAIT / _children) | 332-340 | ytt | 外部プログラムの管理の状態 |
| spawn | 341-354 | ytt | 外部コマンドの起動(窓なし・別グループ・子を覚える) |
| forget | 355-360 | ytt | 終わった子を外す |
| children | 361-368 | ytt | 動いている子の一覧(serve.py:597) |
| stop_children | 369-397 | ytt | 子を孫ごと止める(serve.py 599,603) |
| run_short | 398-419 | ytt | すぐ終わる外部コマンド(_probe_media / exporter) |
| hard_kill | 420-425 | ytt | 孫ごと強制終了 |
| terminate | 426-450 | ytt | 止める依頼(猶予のあと強制)。analyze / exporter / run_capture |
| idle_message | 451-454 | ytt | 出力が止まったときの文言(exporter 430 / run_capture 511) |
| run_capture | 455-514 | ytt | 外部コマンドを実行し 1 行ずつ渡す(中止・時間切れ・無出力対応)。analyze 279,459,708 |
| _out_dir・default_out_dir・reset_out_dir・get_out_dir | 515-531 | ytt | 書き出し先の現在値。exporter が 6 か所で読む(本来は spec に載せて渡す値) |
| is_inside_out_dir | 532-541 | pipeline/export | パスが書き出し先の中か(realpath)。exporter.check_section_path 224 / serve.py:283 |
| check_out_dir | 542-565 | pipeline/export | 書き出し先の検査(% 禁止・書き込みテスト)。set_out_dir 588 / load_out_dir 572 |
| load_out_dir | 566-578 | ytt | settings.json の outDir を読む(serve.py:59) |
| _out_lock / BUSY_MSG / set_out_dir | 579-601 | 要相談 | [F] 書き出し先の変更。settings.json を書く + 実行中は変えられない(busy は batch と exporter の両方 = serve.py:65)+ exporter.start_job 334 が _out_lock を取る。設定(ytt)・書き出し(pipeline/export)・実行中の判定(app)にまたがる |
| 環境チェックの定数(YTDLP_OLD_DAYS 他) | 602-608 | ytt | yt-dlp の古さ・空きの下限・結果の覚え |
| _tool_version | 609-616 | ytt | 外部プログラムの版(ytt_core.tools.tool_version の包み) |
| check_tools | 617-632 | ytt | ffmpeg / ffprobe / yt-dlp の有無と版。621 に疑似の分岐 |
| start_env_check | 633-636 | ytt | 起動時に裏で 1 回(serve.py:564) |
| env_state | 637-662 | app | GET /api/state の env(画面に出せる文の組み立て)。serve.py:86。656 に疑似の分岐 |

**行数の合計(src/studio/common.py)**

- pipeline/ingest: 79 行
- pipeline/export: 34 行
- manage/keep: 11 行
- eval/fake: 8 行
- app: 26 行
- ytt: 460 行
- 要相談: 23 行
- ヘッダ: 21 行
- 合計: 662 行

### src/studio/serve.py(670 行)

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| (docstring・import) | 1-34 | ヘッダ | スタジオのサーバー。6 つの studio モジュールを全部 import する(= app の位置) |
| APP_ID / SERVER_VERSION / TOOL_ID / handoff.TOOL.update | 35-38 | app | ping の app 名・版 0.26.0(core.js と揃える)。版は 1 つに(plan 4-8)で消える。38 行で handoff.TOOL に版を注入 |
| CODE_DIR | 39 | app | 静的ファイルの場所(168) |
| STATIC | 40 | app | 静的ファイルの表(index.html / *.js / *.css)。plan: app/ui/studio へ |
| STATIC_TYPES | 41 | app | 拡張子 → Content-Type(173) |
| PORT / BASE_PATH / ALLOWED_HOSTS / MAX_BODY / SOCKET_TIMEOUT | 42-46 | app | 待ち受けの状態(BASE_PATH は home/mount.py が prepare で入れる) |
| MEDIA_TYPES | 47-49 | app | /media の Content-Type(224) |
| STORE / BATCH | 50-53 | app | モジュールの大域(init が作る)。全ルートがここから store・batch を呼ぶ |
| init | 54-64 | app | Store と Batch の組み立て(prepare 558 とテスト) |
| busy | 65-68 | app | 解析中か書き出し中か(set_out_dir に渡す。343)。batch と exporter の両方を見るので app |
| fetch_title | 69-80 | pipeline/ingest | oEmbed で配信のタイトルを取る(GET /api/title ← 画面の URL 欄)。URL → タイトルは取り込みの補助。71-72 に疑似の分岐 |
| api_state | 81-92 | app | GET /api/state の組み立て(鍵・道具・出力先・クォータ・env・dataWarning)。rank.quota 85 / env_state 86 / take_warning 87 |
| class Handler | 93-254 | app | HTTP の検査(Host・Origin・Sec-Fetch-Site)・GET の表(180-195)・/media・書き込みの共通の順番・エラー整形 |
| _open_video | 255-272 | app | POST /api/videos/open の配線(kind=file / live / youtube)。検査は analyze.validate_* / 登録は STORE.ensure。live のときのチャンネル名の制御文字除去 267 だけ小さな論理 |
| _live_exported | 273-299 | 要相談 | [D] POST /api/live/exported。入口のライブ書き出し(home/live_export.py)が済んだマークを書き出し済みにする。path 検査(書き出し先の中・.mp4)+ 相対パス計算(295)+ STORE.mark_exported。書き出し結果の記録の窓口で、配線以上の論理を持つ |
| _live_section | 300-306 | app | POST /api/live/section の配線(exporter.build_section_spec → start_job)。2 行 |
| _video_delete | 307-319 | app | POST /api/video/delete。書き出し中の拒否・解析の中止・削除を順に呼ぶ全層をまたぐ流れ(exporter 311・BATCH 313・STORE 315) |
| _put_video | 320-323 | app | PUT /api/video の配線(STORE.put_video) |
| _adopt_top | 324-329 | app | POST /api/video/adopt-top の配線(STORE.adopt_top) |
| _request_marks | 330-341 | app | POST /api/video/request-marks の配線 + 未登録なら ensure(334-337) |
| _outdir | 342-345 | app | PUT /api/outdir の配線(common.set_out_dir) |
| _config | 346-349 | app | PUT /api/config(API キー保存。common.set_api_key) |
| _settings | 350-357 | app | PUT /api/settings(画面の設定) |
| _export | 358-362 | app | POST /api/export(build_spec → start_job。on_done に STORE.mark_exported を渡す 360) |
| _export_cancel | 363-367 | app | POST /api/export/cancel |
| _collab_create / _add / _remove / _delete / _anchor | 368-388 | app | コラボのルートの配線(STORE.create_group など。実体は human/review) |
| POST_ROUTES | 389-412 | app | POST の表。rank・queue・videos・export・collab へ振り分け |
| PUT_ROUTES | 413-421 | app | PUT の表 |
| StudioServer | 422-425 | app | httpsec.ExclusiveServer の別名 |
| probe | 426-431 | app | 同じ版が動いているか |
| _bound | 432-439 | app | ポートの確定 |
| make_server | 440-459 | app | 空きポートで待ち受け |
| LOG_MAX / _log_lock / _log | 460-476 | manage/ops | studio.log に 1 行追記(終了の原因調べ。起動 561・中断 605・終了 654 で使う)。エラーの記録 |
| _setup_diagnostics | 477-512 | manage/ops | 未処理の例外・シグナル・クラッシュを studio.log / studio.crash.log に残す(main 643 だけ) |
| DATA_ITEMS / DATA_STATE | 513-518 | manage/keep | 旧い場所から新しい置き場へ写す名前の表(datadir.prepare に渡す)と結果 |
| _data_home | 519-534 | manage/keep | データの置き場所の決定と旧データのコピー(datadir.prepare)。prepare 558 から |
| _keep_legacy_exports | 535-547 | manage/keep | 移行時、旧い exports を書き出し先として使い続ける設定(settings.json)を書く |
| prepare | 548-568 | app | 起動の準備(置き場所・Store 初期化・ログ・work の掃除・.runtime・環境チェック・片付けスレッド)。home/mount.py と main の両方から |
| _clean_leftovers | 569-584 | manage/keep | 起動時の片付け: 書き出しの書きかけ(exporter.clean_partials)とチャットキャッシュ(analyze.prune_chat_cache)を整理 |
| SHUTDOWN_WAIT | 585-587 | app | 終了待ちの上限 5 秒 |
| shutdown_jobs | 588-609 | app | 終了の流れ(BATCH.shutdown・exporter.cancel_all・analyze.cancel_all_prefetch・common.stop_children)。全層を止めるので app |
| finish | 610-618 | app | 終了の後始末(home/mount.py の Mount.stop が呼ぶ) |
| mounted_elsewhere | 619-627 | app | 入口の中で動いていればその URL(単独起動の重複防止) |
| main | 628-670 | app | 単独起動の入口 |

**行数の合計(src/studio/serve.py)**

- pipeline/ingest: 12 行
- manage/keep: 51 行
- manage/ops: 53 行
- app: 493 行
- 要相談: 27 行
- ヘッダ: 34 行
- 合計: 670 行

### src/studio/exporter.py(993 行)

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| (docstring・import) | 1-23 | ヘッダ | 区間 → 動画の書き出し。import handoff / common。疑似は 3 行目と 204 行目に出てくる |
| MAX_EXPORT_CLIPS 他(クリップ数・秒・無出力・音量の既定) | 24-28 | pipeline/export | 書き出しの上限と既定の音量 75%(build_spec 269 / _parse_opts 166 / _pump 389) |
| LOUDNESS_CHOICES / TRUE_PEAK_CEIL / MAX_GAIN_DB / EDIT_HANDLE_SEC | 29-34 | pipeline/export | ytt_core.loudness の別名と編集用素材の前後 10 秒 |
| 名前の規則の別名(MAX_PATH_UNITS・safe_name 他) | 35-39 | pipeline/export | ytt_core.names の別名。テストと他の部品が読むため残してある(消せる) |
| LOG_MAX | 40 | pipeline/export | export-log.txt の上限(log_export 69) |
| PARTIAL / partial_path / is_partial / final_path | 41-44 | pipeline/export | 書きかけの印(.partial.mp4)の別名 |
| _jobs / _jobs_lock | 45-48 | pipeline/export | 書き出しジョブの表(メモリだけ) |
| ExportError | 49-52 | pipeline/export | 書き出しの失敗 |
| is_busy | 53-57 | pipeline/export | 実行中か。serve.py 66,601,604,658 / clean_partials 141 |
| is_busy_for | 58-62 | pipeline/export | その配信を書き出し中か(serve.py:311) |
| log_export | 63-75 | pipeline/export | 実行コマンドと出力を <出力先>/export-log.txt に残す。plan 9「要確認: スタジオの export-log.txt」 |
| _ERR_RE / reason | 76-85 | pipeline/export | 失敗理由の行を選ぶ(verify_output 91 / _pump 432)。common.tail_reason と近い別実装 |
| verify_output | 86-94 | pipeline/export | 出力が空・短すぎないか(ffmpeg は開始が範囲外でも成功する) |
| pick_folder | 95-103 | pipeline/export | <出力先>/<動画名>/ を決める(_run_job 920) |
| promote | 104-114 | pipeline/export | 書きかけ → 本当の名前へ置き換え |
| _rm | 115-120 | pipeline/export | 消せなくても続ける |
| drop_partial | 121-126 | pipeline/export | 失敗・中止時に書きかけを消す |
| clean_partials | 127-150 | pipeline/export | 起動時に前回の書きかけを消す。serve._clean_leftovers 572 から |
| _bad / _bad_opt | 151-160 | pipeline/export | 検査エラーの作り |
| _parse_opts | 161-187 | pipeline/export | precision・volume・loudness の検査(build_spec 271 / build_section_spec 248)。書き出しの設定 = spec |
| _max_height | 188-196 | pipeline/export | 画質の上限の検査 |
| _need_ffmpeg | 197-201 | pipeline/export | ffmpeg が無ければ 400 |
| _youtube_source | 202-211 | pipeline/export | YouTube の取り元を spec に入れる。204-205 に疑似の分岐(fake_media)→ eval/fake の登録の口へ |
| check_section_path | 212-232 | pipeline/export | POST /api/live/section の path の検査(書き出し先の中・.mp4・上書きしない) |
| build_section_spec | 233-258 | pipeline/export | 区間 1 本の spec(YouTube の videoId の start〜end → path)。serve.py:303 |
| build_spec | 259-306 | pipeline/export | 配信 + マーク → spec。引数 store を受けて store.internal を引く(261)ので、新形では辞書(配信 + マーク)を受ける形に直す。ライブ録画は断る(264)。301 に疑似の判定。serve.py:359 |
| PUBLIC_PATHS | 307-309 | pipeline/export | 公開するパスの鍵 |
| job_public | 310-322 | pipeline/export | GET /api/export の形(画面向けの整形を含む)。serve.py 192,304,360 |
| _combined_public | 323-331 | pipeline/export | つないだ 1 本の公開形 |
| start_job | 332-347 | pipeline/export | ジョブ登録 + スレッド開始。common._out_lock を取る(334)。serve.py 304,360 |
| get_job | 348-354 | pipeline/export | ジョブ取得(serve.py:192) |
| cancel | 355-360 | pipeline/export | 中止(serve.py:364) |
| cancel_all | 361-371 | pipeline/export | 終了の流れ用の一括中止(serve.py:595) |
| _pump | 372-435 | pipeline/export | ffmpeg/yt-dlp の実行と進み具合・無出力の監視 |
| _make | 436-449 | pipeline/export | 出力を作って検証、失敗なら export-log に残して削除 |
| PROGRESS / ENC / ENC_FAST / SECTION_PAD / DL_TAG | 450-457 | pipeline/export | 30fps の作り直しの引数(ytt_core.normalize)・区間取得の余白 |
| _enc | 458-461 | pipeline/export | 精密 / 高速の引数の選択 |
| _method | 462-466 | pipeline/export | .clip.json の export.mode |
| run_ffmpeg | 467-500 | pipeline/export | 手元のファイルから切り出す |
| expected_len | 501-507 | pipeline/export | 期待する長さ |
| _fsel | 508-512 | pipeline/export | yt-dlp の形式の選択 |
| _ytdlp_cmd | 513-517 | pipeline/export | yt-dlp のコマンド先頭 |
| _work_dir | 518-523 | pipeline/export | 作業用/ の場所 |
| _drop_glob | 524-527 | pipeline/export | 途中ファイルの削除 |
| _ytdlp_sections | 528-582 | pipeline/export | YouTube の区間取得(--download-sections) |
| stream_urls | 583-596 | pipeline/export | 直接の URL(yt-dlp -g) |
| _ytdlp_stream | 597-612 | pipeline/export | 直接の URL から切り出す |
| run_ytdlp | 613-628 | pipeline/export | YouTube 動画の書き出しの本体 |
| _reencode_audio | 629-642 | pipeline/export | 音声だけ作り直す |
| apply_volume | 643-651 | pipeline/export | 音量(%)をかける |
| measure_loudness | 652-660 | pipeline/export | ラウドネスを測る |
| apply_loudness | 661-683 | pipeline/export | ラウドネスをそろえる |
| MAX_COMBINE_SEC | 684-686 | pipeline/export | つないだ長さの上限 3600 秒 |
| _runner | 687-691 | pipeline/export | file / url の実行関数の選択 |
| _fail | 692-703 | pipeline/export | 失敗の記録 |
| _run_combine | 704-753 | pipeline/export | 選んだマークを時刻順につないで 1 本 |
| concat_pieces | 754-770 | pipeline/export | つなぎ合わせ |
| _drop_edit | 771-780 | pipeline/export | 編集用素材の取り消し |
| export_edit_media | 781-815 | pipeline/export | 前後 10 秒の編集用素材(Resolve 用) |
| _clip_export_info | 816-827 | pipeline/export | .clip.json の export 部分 |
| write_manifests | 828-851 | pipeline/export | 書き出した mp4 の隣に .clip.json(handoff.write_clip_manifest 840,848)。plan 5-2 の「鍵つき成果物」の先祖 |
| run_job | 852-873 | pipeline/export | 重い処理の順番(jobs.SLOTS)を待ってから書き出す |
| _settle | 874-887 | pipeline/export | 実行中のまま終わったジョブの後始末 |
| _run_section | 888-916 | pipeline/export | 区間 1 本を path ちょうどへ |
| _run_job | 917-945 | pipeline/export | マークごとのループ |
| _export_clip | 946-993 | pipeline/export | 1 本ぶん(切り出し → 音量 → 編集用素材 → ラウドネス → 本名 → on_done(= STORE.mark_exported 979)→ .clip.json)。on_done は引数で受けるので pipeline/export は store を import しない |

**行数の合計(src/studio/exporter.py)**

- pipeline/export: 970 行
- ヘッダ: 23 行
- 合計: 993 行

### src/studio/batch.py(283 行)

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| (docstring・import) | 1-14 | ヘッダ | 解析キュー。12 行で store.now_ms を import(pipeline → human の逆向き) |
| MAX_ACTIVE / MAX_HISTORY / FINISHED / RETRYABLE / メッセージ | 15-22 | pipeline/run | キューの上限(待ち + 実行中 10・履歴 30)と状態の名前 |
| class Batch / __init__ | 23-32 | pipeline/run | 解析の順番待ち(1 ワーカー・古い順)。plan: studio/batch.py → pipeline/run.py(順番待ち) |
| start | 33-40 | pipeline/run | ワーカースレッドを 1 つだけ起動 |
| _active | 41-43 | pipeline/run | 待ち + 実行中 |
| is_busy | 44-47 | pipeline/run | serve.py:66(busy) |
| _find | 48-53 | pipeline/run | qid から探す(404) |
| _finish | 54-64 | pipeline/run | 終了状態の設定・履歴の整理。58 で先読みを止める(analyze) |
| _public | 65-72 | pipeline/run | キュー 1 行の公開形(画面向け) |
| snapshot | 73-80 | pipeline/run | GET /api/queue(serve.py:187) |
| _new_item | 81-84 | pipeline/run | キューの 1 件の辞書 |
| add | 85-127 | pipeline/run | キューに入れる(検査 analyze.validate_* + store.ensure 112)。store.ensure(登録)を呼ぶのは逆向きなので、app 側で ensure してから入れる形に(要相談 B 参照)。serve.py:394 |
| _admit_error | 128-137 | pipeline/run | 満杯・重複の判定 |
| cancel | 138-146 | pipeline/run | serve.py:395 |
| skipchat | 147-154 | pipeline/run | チャットを待たない(serve.py:396) |
| retry | 155-170 | pipeline/run | やり直し。163 で store.ensure を呼ぶ(add と同じ逆向き) |
| cancel_video | 171-184 | pipeline/run | 配信の削除前にその配信の解析を止める(serve.py:313) |
| shutdown | 185-201 | pipeline/run | 終了の流れ(serve.py:594) |
| running_now | 202-205 | pipeline/run | serve.py 601,604 |
| clear | 206-211 | pipeline/run | 終わったものを消す(serve.py:398) |
| _kick_prefetch | 212-224 | pipeline/run | 次の配信のチャットを先読み(analyze.prefetch_chat 220) |
| _loop | 225-252 | pipeline/run | ワーカー本体。重い処理の順番(jobs.SLOTS 243)→ analyze.run_analyze 246 → _complete。233 で store.has |
| _complete | 253-278 | pipeline/run | 解析の終わりの処理(状態の決定・_apply) |
| _apply | 279-283 | 要相談 | [C] 解析結果(候補)を store.replace_auto に渡して data.json に反映(283)。plan では ① は「ファイルと JSON」を書くだけで ② の側が読む。この 1 行が ① → data.json(混在)の接点なので replace_auto と一緒に決める |

**行数の合計(src/studio/batch.py)**

- pipeline/run: 264 行
- 要相談: 5 行
- ヘッダ: 14 行
- 合計: 283 行

### src/studio/rank.py(830 行)

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| (docstring・import) | 1-26 | ヘッダ | 配信の検索と事務所の登録(YouTube Data API)。7 行目: 疑似は STUDIO_FAKE=1 |
| API_BASE | 27 | human/find | common.YT_API_BASE(65) |
| NET_MSG | 28 | human/find | 接続エラーの文言 |
| CHID_RE / HANDLE_RE / SLUG_RE / JST | 29-32 | human/find | チャンネル ID・ハンドル・事務所 id・日本時間 |
| MAX_AGENCIES〜FATAL | 33-39 | human/find | 上限・並列数・キャッシュ秒・seed.json の場所・全体を止める失敗の種類 |
| _quota / _quota_lock / _reg_lock / _cache / _cache_lock | 40-46 | human/find | API 呼び出し回数・キャッシュの状態 |
| registry_path | 47-50 | human/find | registry.json の場所(事務所の登録) |
| quota | 51-54 | human/find | 使った API ユニット数(serve.py:85) |
| yt_get | 55-101 | human/find | YouTube Data API を 1 回呼ぶ(エラーの種類分け・1 回だけ再試行)。60-61 に疑似の分岐。analyze.fetch_comments は別に urlopen を持つ |
| _FAKE_WORDS / _FAKE_INDEX | 102-106 | eval/fake | 疑似の API のデータ(fake_get が使う) |
| _h | 107-110 | eval/fake | 疑似のハッシュ |
| fake_channel_id | 111-114 | eval/fake | 疑似のチャンネル ID |
| fake_video | 115-124 | eval/fake | 疑似の動画 |
| fake_get | 125-180 | eval/fake | 疑似の API 本体(channels / channelSections / playlistItems / videos)。LIVE_PAGE(rank 本体の定数)を読む 149 に注意 |
| _fake_register | 181-186 | eval/fake | 疑似の動画の索引 |
| fake_live | 187-210 | eval/fake | 疑似の配信中・予定 |
| parse_ref | 211-232 | human/find | @ハンドル / チャンネル ID / URL → ref |
| _list | 233-236 | human/find | 形の違う入力で落ちない |
| sanitize_registry | 237-265 | human/find | 事務所の登録の整形 |
| load_registry | 266-287 | human/find | registry.json(無ければ seed.json)を読む |
| _quarantine_registry | 288-298 | human/find | 壊れた registry.json の退避 |
| save_registry | 299-302 | human/find | registry.json の保存 |
| _soft | 303-315 | human/find | 1 チャンネルの失敗と全体を止める失敗の仕分け |
| _pending | 316-320 | human/find | 未解決のチャンネル |
| _resolve_channels | 321-335 | human/find | チャンネルの解決(ID は 50 件ずつ・ハンドルは 1 件ずつ) |
| _apply_channel | 336-345 | human/find | 解決結果の反映 |
| resolve_registry | 346-354 | human/find | 登録の解決 |
| import_official | 355-385 | human/find | 公式チャンネルの「チャンネル」欄から所属チャンネルを取り込む |
| _jobs / _jobs_lock | 386-390 | human/find | 検索ジョブの表 |
| norm | 391-394 | human/find | 検索語の正規化 |
| parse_iso_dur | 395-402 | human/find | ISO8601 の長さ |
| parse_dt | 403-414 | human/find | 日時の解析 |
| validate_search | 415-444 | human/find | 検索条件の検査 |
| _MISS | 445-447 | human/find | キャッシュの未ヒット印 |
| _cache_get | 448-455 | human/find | TTL つきキャッシュ |
| _cached | 456-468 | human/find | キャッシュ越しの取得 |
| list_candidates | 469-499 | human/find | チャンネルのアップロード一覧から期間内の動画 ID(「候補」だが解析の候補ではなく検索結果) |
| fetch_videos | 500-521 | human/find | 動画の詳細 |
| video_row | 522-530 | human/find | 検索結果の 1 行 |
| matches | 531-538 | human/find | 条件に合うか |
| _ok_channels | 539-552 | human/find | 解決済みチャンネル |
| run_search | 553-615 | human/find | 検索ジョブ本体(WORKERS 並列) |
| _start_search | 616-628 | human/find | ジョブ開始 |
| job_public | 629-639 | human/find | ジョブの公開形 |
| LIVE_* 定数(LIVE_TTL / LIVE_SCAN_TTL / LIVE_PAGE / LIVE_AHEAD / LIVE_LATE / MEMBERS_RE / _live_none / _live_lock) | 640-652 | human/find | 「配信中」タブの設定と状態 |
| parse_live_agencies | 653-665 | human/find | ?agencies= の解析(serve.py:186) |
| _live_scan | 666-673 | human/find | 先頭数本の動画 ID |
| _ms | 674-677 | human/find | ミリ秒 |
| live_row | 678-713 | human/find | videos.list の 1 件 → 配信中・予定の 1 行 |
| _live_fetch | 714-736 | human/find | videos.list で状態を聞く |
| _live_build | 737-772 | human/find | 配信中・予定の一覧を作る |
| live_list | 773-793 | human/find | GET /api/rank/live(serve.py:186)。画面(rank.js:486)だけが読む |
| get_registry | 794-797 | human/find | serve.py:184 |
| put_registry | 798-804 | human/find | serve.py:417 |
| resolve | 805-809 | human/find | serve.py:390 |
| import_official_channels | 810-814 | human/find | serve.py:391 |
| start_search | 815-818 | human/find | serve.py:392 |
| get_search | 819-825 | human/find | serve.py:185 |
| cancel_search | 826-830 | human/find | serve.py:393 |

**行数の合計(src/studio/rank.py)**

- human/find: 695 行
- eval/fake: 109 行
- ヘッダ: 26 行
- 合計: 830 行

### src/studio/handoff.py(61 行)

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| (docstring・import) | 1-12 | ヘッダ | ツール間の受け渡し。import http.client は未使用(inventory T 67 行) |
| TOOL / TOOL_APPS / PING_TIMEOUT | 13-17 | ytt | ytt_core.runtime の別名と .clip.json の tool 名・版(版は serve.py:38 が注入)。版は 1 つに(plan 4-8) |
| manifest_path | 18-23 | pipeline/export | .clip.json の置き場所(作業用/) |
| clip_manifest | 24-28 | pipeline/export | youtube-tools-clip/v1 の組み立て(ytt_core.schemas.build_clip)。呼び手 write_clip_manifest 34 |
| write_clip_manifest | 29-36 | pipeline/export | 書き出した mp4 の隣に .clip.json を書く(exporter.py 840,848) |
| runtime_dir | 37-42 | ytt | .runtime の場所(ytt_core.runtime.runtime_dir の包み)。write_runtime 48 / serve.py:622 |
| write_runtime | 43-53 | app | 起動時に .runtime/studio.json を書く(serve.py:563) |
| remove_runtime | 54-58 | app | 終了時に消す(serve.py:616) |
| siblings | 59-61 | app | GET /api/siblings(serve.py:181)。cut2resolve/serve.py:155 にも同じ包みがある |

**行数の合計(src/studio/handoff.py)**

- pipeline/export: 19 行
- app: 19 行
- ytt: 11 行
- ヘッダ: 12 行
- 合計: 61 行

### src/studio/txlink.py(35 行)

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| (docstring・import) | 1-10 | ヘッダ | 書き出し済みマークのセリフ(文字起こしのデータは読むだけ) |
| MAX_LINES | 11-13 | manage/cases | 1 本の切り抜きで返す行の上限 3000(for_video 34) |
| tx_folder | 14-17 | manage/cases | 文字起こしの置き場(txindex.folder) |
| for_video | 18-35 | manage/cases | マーク(切り抜き)↔ 文字起こしの紐づけ。txindex.pick / offset / lines を呼ぶ。serve.py:190。plan: txindex は manage/cases |

**行数の合計(src/studio/txlink.py)**

- manage/cases: 25 行
- ヘッダ: 10 行
- 合計: 35 行

### src/cut2resolve/serve.py(980 行)

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| (docstring・import) | 1-60 | ヘッダ | cut2resolve の API サーバー。1-35 は API の説明、36-60 は import と sys.path |
| _load_core | 61-72 | ytt | ytt_core を sys.path に足す。src/ytt がパッケージになれば不要 |
| _load_core() 呼び出し・ytt_core の import | 73-75 | ytt | 共通部品の import |
| APP_ID / TOOL_ID / SERVER_VERSION / DEFAULT_PORT | 76-79 | app | ping の app 名・版(C.VERSION)・既定ポート 8810。版は 1 つに |
| WORK_DIR / LOG_PATH / LOG_MAX | 80-82 | app | serve.log の場所(起動時に作業データの中へ _choose_work_dir) |
| MAX_BODY / SOCKET_TIMEOUT | 83-84 | app | HTTP の上限 |
| MEDIA_EXTS | 85 | pipeline/ingest | 動画の拡張子(FIELD_EXTS 164)。studio/common.MEDIA_EXT と別の集合(.m4v .avi .mxf .mts .m2ts .wmv を含む / .m4a .mp3 などを含まない)。ingest で 1 つにするかは要確認 |
| PAGE_PATHS / MOVED_PAGE / CSP / QUIET_PATHS | 86-96 | app | 旧画面 / への案内ページ・CSP・ログを出さない経路。plan: 旧い URL の転送 |
| _REQ / DEFAULTS | 97-100 | pipeline/spec | pack.Request の既定値のコピー(noise・silenceMin 他)。指定を省いたときの値 = パックの指定の既定 |
| TOOL_APPS / PING_TIMEOUT / BASE_PATH / ALLOWED_HOSTS / MOUNT | 101-107 | app | 取り込まれたときの状態 |
| class ApiError | 108-115 | ytt | 同名の例外が studio/common.py:48 にもある(extra の既定が違う)。ytt に 1 つ |
| _log_lock / log | 116-131 | manage/ops | serve.log に 1 行追記(エラーの記録。パックの失敗の調べ用) |
| runtime_dir | 132-139 | app | .runtime の場所(ytt_core.runtime の包み) |
| write_runtime | 140-149 | app | 起動時に .runtime/cut2resolve.json |
| remove_runtime | 150-154 | app | 終了時に消す |
| siblings | 155-160 | app | GET /api/siblings。studio.handoff.siblings と同じ包み(重複) |
| LABELS / FIELD_EXTS | 161-166 | pipeline/spec | 入力の種類ごとの名前と許す拡張子(clean_path / input_path が使う) |
| clean_path | 167-191 | pipeline/spec | 画面から来たパスを整える(引用符・file:///・相対パスを断る)。request_from_spec 395-400 |
| input_path | 192-209 | pipeline/spec | 入力ファイルの存在・拡張子の検査 |
| class Job | 210-241 | pipeline/run | plan / build の 1 ジョブの辞書(進み具合・結果・エラー)。pack の C.Task を持つ |
| class AppState | 242-314 | 要相談 | [G] 1 つに ジョブ表と実行(start_job/_run: 重い処理の順番 _heavy.SLOTS 282・エラー整形 291-303 = pipeline/run 寄り)、pack.Cache(249 = pipeline/pack)、「フォルダを開く」の許可リストと opener(allow_out_dir・out_dir_allowed・open_folder = app)が同居 |
| is_pack_dir | 315-320 | manage/cases | パックのフォルダか(ytt_core.txindex.is_pack_dir の包み)。_open_folder 823 |
| MAX_PACK_RECORDS | 321-323 | pipeline/pack | パックの記録の保持数 1000 |
| write_pack_record | 324-349 | pipeline/pack | パックを作った記録(packs/<フォルダのハッシュ>.json)。パックが何をしたかの ① の記録。txindex(manage/cases)が読む。呼び手 803(_build の work) |
| open_folder | 350-359 | app | エクスプローラーでフォルダを開く(OS 呼び出し。opener として差し込み可 251) |
| _num | 360-378 | pipeline/spec | 数値の検査(request_from_spec 418-452 / advanced_from_spec / output_from_spec) |
| _str | 379-386 | pipeline/spec | 文字列の検査 |
| request_from_spec | 387-455 | pipeline/spec | 画面の指定 JSON → pack.Request(silence / keep / list / keeps / transcript-rows)。呼び手 Handler._plan 761・_build 776 |
| row_edge_from_spec | 456-464 | pipeline/spec | 行の端を声の止まる所まで広げる指定 |
| advanced_from_spec | 465-475 | pipeline/spec | 詳しい設定(fps・フレーム数・TC・リール名・EDL 名) |
| keeps_from_spec | 476-496 | pipeline/spec | 残す区間の検査。editor/ed_store.py:775 に「同じ決まり」の別実装がある(重複) |
| speaker_color_map | 497-502 | pipeline/pack | 話者名 → メンバーカラー(ytt_core.colors)。_build 791 |
| _style_color | 503-510 | pipeline/spec | speakerStyles の color の検査 |
| SPEAKER_STYLE_KEYS / SPEAKER_STYLES_MAX / SPEAKER_NAME_MAX | 511-515 | pipeline/spec | 話者ごとの見た目指定の許可の鍵・上限 |
| speaker_styles_from | 516-538 | pipeline/spec | output.speakerStyles の検査(友人の依頼の見た目の指定) |
| apply_speaker_styles | 539-559 | pipeline/pack | 指定の色をメンバーカラーより優先して重ねる(plan に重ねる)。_build 793 |
| output_from_spec | 560-598 | pipeline/spec | 出力の指定(Text+・音量・ラウドネス・配信者の色・トラック数・予備)→ build_pack の引数 |
| FILE_NOTES | 599-605 | app | 出力ファイルの種類ごとの注記(画面向け) |
| file_info | 606-613 | app | 出力ファイル 1 件の画面向けの形(_build 807) |
| _INFO_WARNING_MARKERS | 614-626 | app | 警告を info にする語句の表(画面の warn / info の分け) |
| classify_warnings | 627-630 | app | 警告の重さの付与 |
| with_warning_levels | 631-636 | app | summary / build_pack の戻りに warningLevels を足す |
| class Handler(共通部分・GET) | 637-759 | app | 検査(_guard)・応答・エラー整形・本文の読み・GET /api/ping, siblings, job |
| Handler._plan | 760-774 | pipeline/pack | POST /api/plan。work() の中身(plan_cut → planned_outputs → summary)が試算の流れ本体で、Handler の中に埋まっている。pack 側の関数に出し、Handler は配線だけにする |
| Handler._build | 775-814 | pipeline/pack | POST /api/build。上書きの確認 780-786 + work()(色の決め方 790-794 → build_pack → 記録 write_pack_record → 結果の整形)= パックを作る流れ本体が Handler の中。pack 側へ出す |
| Handler._cancel | 815-820 | app | POST /api/job/cancel |
| Handler._open_folder | 821-833 | app | POST /api/open-folder(許可されたフォルダだけ開く) |
| class C2RServer | 834-837 | app | 単独起動のサーバー |
| probe | 838-843 | app | 同じ版が動いているか |
| _bound | 844-851 | app | ポート確定 + AppState |
| make_server | 852-871 | app | 空きポートで待ち受け |
| class MountContext | 872-880 | app | 入口に取り込まれたときの状態 |
| _choose_work_dir | 881-894 | manage/keep | 作業用フォルダ(ログ)を作業データの置き場所の中にする(datadir.prepare)。studio._data_home と同種 |
| _startup | 895-905 | app | 待ち受け以外の起動の準備 |
| prepare | 906-913 | app | 入口に取り込まれるときの準備(home/mount.py) |
| busy | 914-919 | app | ジョブが動いているか(入口の「すべて終了」の確認) |
| finish | 920-930 | app | 取り込まれたときの後始末(ジョブの取り消し・.runtime の削除) |
| mounted_elsewhere | 931-940 | app | 入口の中で動いていればその URL |
| main | 941-980 | app | 単独起動の入口 |

**行数の合計(src/cut2resolve/serve.py)**

- pipeline/ingest: 1 行
- pipeline/spec: 265 行
- pipeline/run: 32 行
- pipeline/pack: 111 行
- manage/cases: 6 行
- manage/keep: 14 行
- manage/ops: 16 行
- app: 379 行
- ytt: 23 行
- 要相談: 73 行
- ヘッダ: 60 行
- 合計: 980 行

### src/recorder/recorder.py(372 行)

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| (docstring・import) | 1-39 | ヘッダ | 録画の部品(別プロセス)。API の説明と import |
| HERE / ROOT / sys.path | 40-48 | pipeline/ingest | ytt_core と rec_core を import できるようにする |
| APP_ID / VERSION / DEFAULT_PORT / TOKEN_HEADER / BODY_MAX / LOG_MAX / LIVE_RE / TOKEN_RE | 49-58 | pipeline/ingest | 録画の部品の版(0.3.3)・ポート 8730(home/live.py:90 と同じ値)・合言葉の形。版は 1 つに |
| data_dir | 59-65 | pipeline/ingest | 作業データの場所(token・設定・記録)。home/live.py:196 に同じ規則の写し |
| load_token | 66-80 | pipeline/ingest | 合言葉(無ければ作る)。入口が同じファイルを読む |
| read_settings | 81-84 | pipeline/ingest | settings.json(録画の置き場所) |
| save_folder | 85-91 | pipeline/ingest | 置き場所を覚える |
| clean_folder | 92-105 | pipeline/ingest | 置き場所の検査(PC の絶対パスのみ) |
| make_logger | 106-129 | pipeline/ingest | recorder.log |
| raise_priority | 130-141 | pipeline/ingest | プロセスの優先度を通常より上に(Windows) |
| class Handler | 142-284 | pipeline/ingest | 録画の API(/live/list・start・stop・delete・status・segments・index.m3u8・config・quit)。入口が /live/r/<録画元>/ で中継 |
| class Server | 285-295 | pipeline/ingest | 独占サーバー |
| parse_args | 296-302 | pipeline/ingest | コマンドライン引数 |
| --source(環境変数 YTT_RECORDER_SOURCE を含む) | 303-304 | eval/fake | 取得のしかた direct(HLS の URL を直接 ffmpeg に渡す偽の録画元)。環境変数の口は使うテスト 0 = plan 9 の死んだフック。登録の口に置き換える |
| parse_args(続き) | 305-315 | pipeline/ingest | hls-time・backoff・idle-end・stall-sec・quiet とポートの検査 |
| main | 316-372 | pipeline/ingest | 起動(rec_core.Recorder を作り待ち受け) |

**行数の合計(src/recorder/recorder.py)**

- pipeline/ingest: 331 行
- eval/fake: 2 行
- ヘッダ: 39 行
- 合計: 372 行

### 11 ファイルの合計(行き先別)

- pipeline/ingest: 465 行
- pipeline/analyze: 834 行
- pipeline/export: 1023 行
- pipeline/spec: 287 行
- pipeline/run: 296 行
- pipeline/pack: 111 行
- human/review: 641 行
- human/find: 695 行
- manage/cases: 31 行
- manage/keep: 76 行
- manage/ops: 69 行
- eval/fake: 119 行
- app: 917 行
- ytt: 551 行
- 要相談: 654 行
- ヘッダ: 290 行
- 合計: 7059 行

### 要相談の一覧

行き先を 1 つに決められなかった物。「暫定」は私の見立て。

| 番号 | 何 | 該当(ファイル:行) | 迷う理由 / 暫定 |
| --- | --- | --- | --- |
| A | `data.json` の入れ物(Store の読み書き・版・退避・警告) | store.py: SCHEMA 26・RESTORE_STEPS 33・SAVE_ERR 39・_warn 67・_load_each 380・_replaced 392・class Store 446・_quarantine 460・_load 474・take_warning 551・_save 558・_commit 574・_commit_group 578・_bump 582 | plan の表は store.py を「候補 → analyze / 手動マーク・採用・コラボ → review」の分割としか書いておらず、入れ物(保存・退避・版)の持ち主が無い。暫定: human/review(① は data.json に書かず候補を別 JSON に出す = plan 4-2・4-3 なので、残る data.json は ② の上書き + コラボ + 配信の登録)。ただし `rev` と全体 1 回の保存が配信の登録(B)と同居し、`data.json` の読み手が外に 4 つある(上の「外の読み手」)。plan 4-7 でファイルの場所は変えない |
| B | 配信の登録(id・kind・title・channel・duration・fileName・path・live)と一覧・取得・削除 | store.py: _load_video 509・_need 588・_summary 604・list 616・get 622・internal 628・media_path 634・has 640・ensure 644・delete 683。連動: batch.py:112,163(ensure)・233(has)、serve.py:307 `_video_delete` | plan の表に無い。暫定: manage/cases(「配信 1 本の束ね」)。ただし pipeline/run(batch)が `ensure` を呼ぶのは逆向きなので、app が登録してから enqueue する形に直す必要がある。`_summary` は画面向けの要約で app 寄りでもある |
| C | ① と ② が 1 関数に同居 | store.py: _clean_server 146・_build_mark 167・_pub 595・request_marks 780・replace_auto 834・MAX_REQUEST_RANGES 30、batch.py `_apply` 279 | 上の「4 つの接点」。`request_marks` は区間指定(② の「前に指定する」= spec の必須区間。human/friend)と自動採用の上位埋め(① analyze)の両方。`replace_auto` は候補の書き込み(①)と人が触れたマークの保持(②)。暫定: 候補を書く部分 = pipeline/analyze、有効な一覧の合成 = human/review(または manage/cases。plan 5-3 は「③ の案件が自動の結果と人の上書きのどちらが有効かを持つ」と書いている) |
| D | 書き出し結果の記録(status=exported・file・path・archived) | store.py: mark_exported 878・_drop_archived 231、serve.py: `_live_exported` 273 | 書き出しの出力の参照は ① の成果物(plan 5-2 の鍵つき `.clip.json`)で、同じ関数が feedback の「よかった/export」(② = human/review)も書く。暫定: 参照の記録 = pipeline/export の sidecar(`handoff.write_clip_manifest` が既にある)、feedback の行 = human/review に割る。`_live_exported` は検査 + 相対パス計算 + 記録で配線以上の論理を持つ(home/live_export.py の完了通知を受ける窓口) |
| E | チャットキャッシュの上限と掃除 | analyze.py: chat_cache_limit 304・prune_chat_cache 329(呼び手 477・serve.py:578,580) | 保管の片付け(manage/keep)だが、使用中の印(_chat_in_use)と先読み(PREFETCH)という pipeline/analyze の状態を見ないと安全に消せない。暫定: pipeline/analyze に置いたまま、起動時の呼び出しだけ manage/keep の片付けから呼ぶ |
| F | 書き出し先の変更 | common.py: _out_lock / BUSY_MSG / set_out_dir 579 | 設定(settings.json を書く = ytt)・書き出し(`exporter.start_job` 334 が同じロックを取る = pipeline/export)・実行中の判定(`serve.busy` 65 = batch と exporter の両方 = app)にまたがる。暫定: app に置き、書き出し先の現在値だけ ytt |
| G | cut2resolve の `AppState` | cut2resolve/serve.py:242 | ジョブ表と実行(重い処理の順番 `_heavy.SLOTS`・エラー整形)= pipeline/run 寄り、`pack.Cache` = pipeline/pack、「フォルダを開く」の許可リストと opener = app。暫定: 3 つに割る |

行き先は決めたが、確認してほしい点(要相談にはしていない):
- **疑似の判定 `common.fake()`(74)は ytt にした**(依頼文の「疑似の判定の 1 行 = app か ytt」に従った)。plan 4-6 は分岐を登録の口に置き換えるので、置き換えが済めば消える。
- `pipeline/spec` と `pipeline/pack` の境: `request_from_spec`・`output_from_spec` など「画面の指定 → pack.Request」の検査は spec に、`_plan`/`_build` の work() 本体(色の決め方・記録・警告の合成)は pack にした。依頼文の行き先の例に `pipeline/spec` が無かったので、plan の `spec.py` 表記を使った。
- `fetch_title`(serve.py:69)は URL → タイトル(oEmbed)なので pipeline/ingest にしたが、画面の URL 欄の補助でもあるので app の可能性がある。
- `analyze.validate_settings`・`make_spec`(解析の設定の既定値)は pipeline/spec にした。`SPEC_KEYS`・`FB_SETTING_KEYS` の鍵一覧と二重になる。

### 疑似(STUDIO_FAKE)の分岐の行番号(eval/fake の登録の口に置き換える対象)

関数の行き先の行数に含めてあるもの(rank.py の疑似 API の塊 102-208 と common.fake_media と recorder の `--source` は eval/fake として数えた)。

| 場所 | 中身 |
| --- | --- |
| common.py:74-76 | `fake()` 本体(環境変数 STUDIO_FAKE) |
| common.py:79-84 | `fake_media()`(STUDIO_FAKE_MEDIA) |
| common.py:621 / 656 | `check_tools`(yt-dlp を有りに)・`env_state`(警告を出さない) |
| analyze.py:267-268 | `download_audio`(fake_media を返す) |
| analyze.py:411-421 | `download_chat`(STUDIO_FAKE_CHAT と、死んだフック STUDIO_FAKE_CHAT_DELAY) |
| analyze.py:494 | `prefetch_chat`(先読みしない) |
| analyze.py:579-585 | `fetch_comments`(STUDIO_FAKE_COMMENTS) |
| analyze.py:694-699 | `fetch_meta`(STUDIO_FAKE_META) |
| batch.py:88 / 99 | `add`(ffmpeg・yt-dlp の確認を飛ばす) |
| exporter.py:204-205 / 301 | `_youtube_source`(fake_media を元にする)・`build_spec`(ID の形を確かめない) |
| rank.py:60-61 | `yt_get`(fake_get に回す)。本体は 102-208 の塊 |
| serve.py:71-72 / 83-84 / 347 | `fetch_title`(疑似のタイトル)・`api_state`(hasKey / ytdlp を真に)・`_config`(hasKey を真に) |
| recorder.py:303-304 | `--source direct` と環境変数 YTT_RECORDER_SOURCE(plan 9: 使うテスト 0 の死んだフック)。偽の録画元の実体は `rec_core.py`(対象外) |
| cut2resolve/serve.py | 疑似の分岐は無い |

### 気づいた点(層の向き・重複)

- **逆向きの依存(pipeline → human/manage)**: `batch.py:12` が `store.now_ms` を import、`batch.add` 112・`retry` 163 が `store.ensure`、`_loop` 233 が `store.has`、`_apply` 283 が `store.replace_auto`。`exporter.build_spec(store, req)` が `store.internal`(261)を引く。`exporter` の `on_done` は引数なので向きは合っている(store を import していない)。直し方は exporter の `on_done` と同じ形(コールバックを app が渡す)。
- **向きが合っている物**: `store.py` が `analyze` を import(21)して feedback を書くのは human/review → pipeline/analyze なので許される向き。ただし feedback の書き手を human/review へ移すと、`analyze.py` の feedback の書き手一式(136-262)は store 側に移る。
- **重複**: `ApiError`(studio/common.py:48 と cut2resolve/serve.py:108)・動画拡張子の集合(studio/common.py:45 と cut2resolve/serve.py:85 が別)・`siblings`/`write_runtime`/`runtime_dir` の包み(studio/handoff.py と cut2resolve/serve.py:132-158)・`keeps_from_spec`(cut2resolve/serve.py:476 と editor/ed_store.py:775)・失敗理由を拾う関数(common.tail_reason 158 と exporter.reason 79)・ログ回し(common.rotate_log 121 と fsio.rotate)・YouTube Data API の呼び出し(rank.yt_get 55 と analyze.fetch_comments 595 が別々に urlopen)・`recorder.data_dir` と `home/live.py:196` の規則の写し。
- **Handler の中に流れ本体**: cut2resolve/serve.py の `Handler._plan` 760・`_build` 775(work() が試算とパックを作る流れ)。plan 3 の「app は配線だけ」に合わせるなら pack 側へ出す。
- **batch.py は pipeline/run になるが画面向けの整形を含む**: `_public` 65・`snapshot` 73(GET /api/queue の形)。analyze.chat_public 114 も同じ。


## 5. 編集 src/editor(9 ファイル)(元の見出し: src/editor 分割の行き先の表(読むだけの調査。2026-10-09))

根拠: `plan/role-restructure.md` の 3 節(目標の形)・7 節(行き先の表)。呼び手は `src/` と `dev/` の .py の全文を識別子で数えた結果(テストは「tests N」)と、要所の本文の読みで確かめた。行は「その名前の開始行 〜 次の名前の開始行の手前」(間の空行・コメントを含む)。名前が並ぶ行は、同じ行き先で隣り合う小さな定数・関数をまとめた。
行き先の `要相談(案: X)#n` は末尾の「要相談の一覧」の番号。`ytt` は基盤、`ytt(settings)` は設定ファイルの読み書き。使ったモデル: Sonnet。

### ed_jobs.py(2800 行)

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| (ヘッダ)docstring・import | 1-39 | ヘッダ(分割後は各行き先が必要な分だけ持つ) | モジュールの説明と import。分割したら各ファイルが自分の分だけ持つ |
| ジョブ表 _jobs/_order/_jobs_lock/_queue/_seq_counter/JOB_PRIORITY | 40-45 | 要相談(案: human/proof)#1 | 画面の裏ジョブの登録簿と優先度つき待機列。_jobs/_jobs_lock を ed_drill・ed_evalbatch・ed_misc・ed_relink・ed_speakers・serve が直に読む。ジョブの進み具合なので human/proof が自然だが、① 単体(pipeline/run)から認識を動かす入口が現状これしか無い |
| _models/_model_lock/_model_used/MODEL_IDLE_SEC + release_idle_models | 46-71 | pipeline/transcribe | 読み込み済みモデルの保持表とアイドル解放(サーバー側ではワーカーごと終わらせる)。_models/_model_lock/_model_used は tx_worker が直に使う。呼ぶのはジョブ循環 worker()(1940) |
| Cancelled/check_cancel/set_cancelled/INTERNAL_MSG/set_internal_error/job_errors/job_temp_wav/job_done/job_title | 72-134 | 要相談(案: ytt)#2 | 取り消し・失敗・一時 wav・完了の約束(job は dict)。認識の途中(pipeline: transcribe_real・RangeRecognizer・diarize)と human 側(ed_alt・ed_ytcap・ed_thumb・ed_relink・ed_misc・ed_speakers)の両方が呼ぶ(check_cancel は ed_speakers から 6 回)。pipeline は human を import できないので共通の下(ytt/jobs。SLOTS は既に ytt_core.jobs)に置く案 |
| _busy_locked/tid_busy | 135-151 | 要相談(案: human/proof)#1 | 同じ文書で処理中のジョブがあるか(ジョブ表を見る)。呼び手 ed_alt・ed_misc・ed_speakers×2・ed_thumb・ed_ytcap。ジョブ表(#1)に従う |
| IN_WORKER/WORKER_SCRIPT/WORKER_LOG(+_MAX/_CANCEL_GRACE/_SILENCE_TIMEOUT/_LINE_MAX)/_worker_priority/worker_env | 152-181 | pipeline/transcribe | 認識ワーカー(別プロセス)の定数と起動環境。IN_WORKER は ed_llm・ed_speakers×3・serve・tx_worker・dev/eval_asr・eval_speakers が参照。WORKER_LOG は serve.set_data_dir(683)が差し替える |
| WorkerError/_CancelHandle/WorkerClient/WORKER | 182-478 | pipeline/transcribe | 認識ワーカーへの 1 行 1 JSON のやり取りの本体(273 行)。WORKER は serve(終了時 close)・ed_llm・ed_speakers×2 が参照。tx_worker.py が相手側 |
| _Obj/_Segs/RemoteModel | 479-550 | pipeline/transcribe | ワーカー越しのモデル代理(faster-whisper と同じ形で返す)。dev/_evalcommon が参照 |
| split_terms/glossary_of | 551-561 | pipeline/transcribe | 用語集の欄の分解と自動の用語の足し込み。呼び手 ed_learn・ed_misc。glossary_of は ed_learn.auto_glossary(学習データ)を読む(#3) |
| validate_job | 562-640 | 要相談(案: pipeline/spec と human/proof に分ける)#6 | HTTP の要求 → 文字起こしの指定(spec)。範囲・モデル・言語・後処理の既定値(= pipeline/spec)と、intoDoc の文書検査・評価用の規則・pio(find_clip)・設定の読み込みが 1 関数に同居。呼び手 ed_evalbatch×5・ed_fill×2・ed_llm・ed_misc・serve・tests 48 |
| ACTIVE_STATES/EXCLUSIVE/RETRY_KINDS/NO_RETRY/can_retry/retry_job/add_job/public_job | 641-725 | 要相談(案: human/proof)#1 | ジョブの登録・排他表・やり直し・画面向けの要約。add_job の呼び手 ed_alt・ed_evalbatch×4・ed_misc・ed_relink・ed_speakers・ed_ytcap・serve。public_job は serve×3。EXCLUSIVE は ed_speakers×2・ed_thumb が参照 |
| extract_audio | 726-756 | pipeline/transcribe | ffmpeg で 16k モノラル wav を取り出す。呼び手 ed_alt・ed_learn・ed_misc・ed_speakers×2・tx_engines・dev/eval_asr・eval_cloud |
| 要確認の印の規則 LATIN_*/SPARSE_*/latin_suspect/sparse_row/stock_phrase/repeats_in_line/make_flags | 757-869 | pipeline/transcribe | 認識の行に付ける要確認の印(英語の幻覚・文字の少ない行・決まり文句・繰り返し)。後処理。呼び手は _rows_to_doc(1887)と dev/eval_asr(make_flags)。SPARSE_FLAG は redo(2323)も使う |
| ENGINE_DIR/engine_home/engine_of/req_engine/engines_info/check_engine/load_model/_load_model_local | 870-978 | pipeline/transcribe | エンジン・モデルの選択と読み込み。engines_info は serve(/api/tools)、_load_model_local は tx_worker×5・tx_engines・dev/_evalcommon、check_engine は ed_alt×2 |
| CUDA_COMPUTE_TYPES/cuda_compute/whisper_kwargs/prompt_terms | 979-1018 | pipeline/transcribe | 認識の引数とヒントの語(用語集 → 文脈)。prompt_terms は dev/eval_asr も使う |
| stream_context | 1019-1041 | pipeline/transcribe | 配信ごとの文脈(チャンネル名・コラボ相手・題名から出る人)をヒントに。呼び手 ed_drill・ed_llm×2・dev/eval_asr。ed_store.studio_stream(スタジオ data.json)を読む(#4) |
| filter_kwargs | 1042-1060 | pipeline/transcribe | モデルが受けない引数を落とす。呼び手 ed_fill・tx_engines |
| VAD_*/seg_to_dict/_prob/vad_kept/vad_note/transcribe_vad_fallback | 1061-1133 | pipeline/transcribe | 声の検出の梯子(標準 → 弱め → なし)と行の辞書化。新規・範囲・全体の再認識が共通で使う |
| GPU_FAILED_*/CPU_FALLBACK_PHASE/cpu_fallback/transcribe_real | 1134-1184 | pipeline/transcribe | GPU が実行時に失敗したら CPU でやり直す決まりと、本物の認識の本体。呼び手 ed_alt・dev/eval_asr |
| SPLIT_SLACK/SUBTITLE_DEFAULT/ORIENTATIONS/subtitle_settings/subtitle_max_chars/split_chars_for/strip_punct/_cut_words/split_segment/expand_segments | 1185-1316 | pipeline/transcribe | 字幕設定の既定値と、行の分け方・句読点の除去・後処理の入口(expand_segments)。呼び手 ed_alt・ed_fill×3・dev/eval_asr・eval_timing×3、subtitle_settings は ed_store(wrap_arg 806) |
| REP_*/END_TRIM/JOIN_GAP/TRIM_*/clip_rows/merge_repeats/trim_ends/join_rows | 1317-1432 | pipeline/transcribe | 行の時刻の後処理(長さの外を捨てる・繰り返しをまとめる・すき間をつなぐ)。END_TRIM/JOIN_GAP は ed_retime・dev/eval_timing が参照 |
| CONF_KEYS/machine_conf/pkg_version/engine_version/_run_base/recognition_run/post_record/short_hash/roster_hash/dict_pairs/dict_version | 1433-1557 | pipeline/transcribe | ① が結果に残す「使った指定と版」の記録(recognition.runs)。dict_pairs/dict_version は ed_learn.load_settings・parse_replacements を読む。呼び手 ed_alt・dev/eval_asr×4 |
| MAX_RERUNS/MAX_REPLACED_ROWS/replaced_rows/record_rerun | 1558-1609 | human/proof | 再認識で行を差し替える前に、直前の original を文書の recognition.runs に控える(evalReviewed を外す)。文書の書き換えの一部。呼び手 ed_drill・ed_evalbatch。plan 9 で runs[].replaced は消す決定 |
| context_record/vad_record/row_words | 1610-1630 | pipeline/transcribe | 記録用の整形と、行の単語の時刻 |
| ASR_SCHEMA/MAX_ASR_BYTES/asr_path/capture_raw/write_asr/read_asr、WORDS_SCHEMA/words_path/read_words/write_words | 1631-1693 | pipeline/transcribe | 生の認識(asr.json)と単語の時刻(words.json)の書き出し・読み込み = ① の出力。asr_path/words_path は serve(文書削除 582)、read_words は ed_retime×2、ASR_SCHEMA/capture_raw は dev/eval_timing |
| replace_words | 1694-1701 | human/proof | 部分的な再認識のあと words.json の該当区間を差し替える(守る区間つき)。呼び手 _apply_range(2236) |
| _squash/_fresh_id/resplit_doc | 1702-1774 | human/proof | 「長い行を分け直す」= 文書の行の操作(単語の時刻で分ける)。resplit_doc は serve から。_fresh_id は新しい行の id |
| transcribe_fake | 1775-1789 | eval/fake | TRANSCRIBE_BACKEND=fake の疑似の認識(4 秒ごとの「テスト文N」)。呼び手 run_job(1816)・ed_alt・dev/eval_asr |
| JOB_RUNNERS | 1790-1802 | 要相談(案: human/proof)#1 | ジョブ種別 → 本体の分配表。diarize/voice-learn(ed_speakers)・retranscribe/redo(ed_jobs)・abtest(ed_misc = eval/drill)・normalize(ed_relink)・alt/ytcap/thumb(human)が 1 つの表に混ざる。層ごとに自分の種別を登録する口にしたい |
| run_job | 1803-1886 | 要相談(案: 認識の本筋を pipeline/transcribe、文書の作成と後始末を human/proof)#5 | 文字起こしジョブ 1 本(84 行)。音声の取り出し → 認識 → 後処理 → 文書を書く → 30fps・話者判別・redo・alt・ytcap の後続を足す。認識と後処理は pipeline、文書の作成(uuid・write_doc・fill_doc)・evalRedo・後続のジョブ投入は human/proof か eval/drill。run_job は ed_alt・ed_evalbatch×4・ed_fill×4・ed_llm×2・ed_relink・ed_speakers・ed_ytcap が名前で参照、tests 100 |
| _rows_to_doc/_doc_fields | 1887-1939 | pipeline/transcribe | 認識した行 → 文書の行・original・単語・recognition.runs の組み立て(① が結果に残す物)。_rows_to_doc は ed_learn.auto_learned_replace・apply_replacements を呼ぶ(#3)。呼び手は run_job のみ(_rows_to_doc は ed_llm も) |
| worker/work_one/cancel_job | 1940-1993 | 要相談(案: human/proof)#1 | ジョブ循環のスレッド(待機列 → SLOTS → run_job)と取り消し。worker は serve.prepare から起動、work_one は ed_relink×2、cancel_job は serve×2・ed_evalbatch・ed_ytcap。ed_state.write_mark を呼ぶ(#14) |
| SPK_FLAGS | 1994-1996 | 要相談(案: ytt)#7 | 話者の要確認の印 3 つの組(ed_state の MIXED/WEAK/NONE_FLAG)。ed_speakers×2・dev/eval_asr が使う。文書の形(#7) |
| MAX_RANGE_SEC/validate_retranscribe | 1997-2048 | human/proof | 再認識ジョブの要求検査(行ごと/範囲/全体・評価用は断る・排他)。serve から |
| AUDIO_MARGIN/audio_span/recognize_chunk/ChunkModel | 2049-2103 | pipeline/transcribe | 再認識する範囲の音声の切り出しと、行ごとの認識(GPU 失敗は CPU でやり直す)。audio_span は ed_misc・dev/eval_asr・eval_cloud×3・eval_speakers・_evalcommon、ChunkModel は ed_misc(A/B)が使う |
| replace_original/apply_retranscribe/_apply_retranscribe/_in_spans/replace_original_multi | 2104-2158 | human/proof | 選んだ行の再認識結果を文書の行・original・proofedAt に反映(校正済みの行は守る)。文書の書き換え |
| PROTECT_PAD から LOOSE_FLAG/_ov/fit_lines/plan_range/apply_range/_apply_range | 2159-2282 | human/proof | 範囲・全体の再認識の結果を、守る行を避けて文書に反映(ほぼ空の所は元の行を残す)。文書の書き換え |
| range_lines_real/finish_range_lines | 2283-2322 | pipeline/transcribe | 範囲の本物の認識と、行の整形(expand_segments に通す) |
| REDO_*/redo_targets/redo_spec/redo_kwargs/redo_better/apply_redo/run_redo | 2323-2501 | human/proof | 疑わしい所(文字の少ない行など)だけ認識し直す = 校正の補助。文書から対象を選び、結果を文書に反映。redo_spec は serve から。認識そのものは RangeRecognizer/ChunkModel を呼ぶ |
| _fake_spans | 2502-2513 | eval/fake | TRANSCRIBE_FAKE_GAP/LOOSE の疑似の区間を環境変数から読む(RangeRecognizer._fake だけが使う) |
| RangeRecognizer(main/loose/_load/_chunk) | 2514-2585 | pipeline/transcribe | 範囲・全体の再認識の認識部(声の検出の梯子・緩い条件)。本物の経路。self.fake の分岐(2521・2542・2565)は登録の口に置き換える |
| RangeRecognizer._fake | 2586-2607 | eval/fake | 疑似の範囲再認識(3 秒ごとに「範囲再認識N」)。クラスの中のメソッドなので切り出しが要る |
| WHOLE_*/RESUME_*/whole_parts/resume_path/whole_key/read_resume/write_resume/drop_resume/whole_lines | 2608-2724 | pipeline/transcribe | 全体の再認識を区間に分けて保存し、続きから再開する(認識の部分)。whole_parts は文書の行のすき間を見る |
| run_retranscribe/_retranscribe_range/_retranscribe_each | 2725-2800 | human/proof | 再認識ジョブの本体(文書を読む → 音声 → 認識 → 文書に反映)。_retranscribe_each の疑似分岐(2777-2784)は eval/fake の登録の口へ |


### ed_speakers.py(1510 行)

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| (ヘッダ)docstring・import | 1-33 | ヘッダ(分割後は各行き先が必要な分だけ持つ) | モジュールの説明と import。分割したら各ファイルが自分の分だけ持つ |
| DIAR_DIR/DIAR_SEG/DIAR_EMBS/DIAR_EMB_DEFAULT/MAX_DIAR_SEC/MAX_SPEAKERS/SPK_COLORS/diar_threads/has_sherpa/_diar_path/_have/diar_info | 34-80 | pipeline/transcribe | 話者判別モデルの置き場・一覧・有無。DIAR_DIR は serve.set_data_dir が差し替え、DIAR_EMB_DEFAULT は serve・tx_worker×2・dev/eval_speakers、diar_info は serve(/api/tools)、has_sherpa は ed_fill。SPK_COLORS は single_speaker(560)の話者の色 |
| _download_verified/ensure_diar_models | 81-130 | pipeline/transcribe | 判別モデルの取得(大きさ・SHA-256 を確かめる)。run_diarize(591)から |
| WavRef/WavSlice/read_wav_f32 | 131-170 | pipeline/transcribe | 音声の参照(ワーカーへはパスとサンプル番号で渡し、サーバー側で numpy を import しない)。ed_jobs×3・ed_fill・ed_misc・dev/_evalcommon が使う |
| DIAR_TUNE/diar_tune/diarize_real/_diarize_local | 171-228 | pipeline/transcribe | 話者判別の本体(ワーカーの中で sherpa-onnx)。_diarize_local は tx_worker×3、diar_tune は tx_worker・dev/eval_speakers |
| diarize_fake | 229-242 | eval/fake | 疑似の話者判別(10 秒ごとの入れ替わり)。tx_worker(worker-fake)・dev/eval_speakers も呼ぶ |
| assign_speakers/_assign/DIAR_SMOOTH_*/label_ratio/smooth_labels/smooth_speakers/diar_smooth_setting | 243-340 | pipeline/transcribe | 声の区間 → 行への話者の割り当てと、細切れのならし(純粋な計算)。assign_speakers・smooth_* は dev/eval_speakers×3 も使う |
| DIAR_SCHEMA/DIAR_KEEP/MAX_DIAR_*/_diar_lock/diar_path/read_diar/_diar_put/write_diar/_diar_edit/_label_of/update_diar_voices/_diar_engine/_turn_overlaps/build_diar_run/_record_diar | 341-444 | pipeline/transcribe | <id>.diar.json = ① が結果に残す「判別の生の結果」(声の区間・重なり・行ごとのラベル)。diar_path は serve(文書削除)、read_diar は ed_drill・ed_evalbatch・dev/eval_speakers×3 |
| apply_diarization/_spk_ids/diar_keep_row/_diar_kept_speakers/_apply_diarization | 445-536 | 要相談(案: 計算は pipeline/transcribe、文書への書き込みは human/proof)#8 | 判別結果を文書の話者・行に書く(人が付けた行・字幕に出さない行・ゲーム音声などの行は守る。ed_fill.fill_clean_turns で定型の幻覚も捨てる)。呼び手 ed_fill・ed_jobs×2・dev/eval_speakers(diar_keep_row)。人の上書きを守る部分は human/proof、純粋な割り当ては pipeline |
| validate_diarize | 537-559 | human/proof | 判別ジョブの要求検査(排他・人数・モデル)。serve から |
| single_speaker | 560-590 | human/proof | 「話す人が 1 人」= 判別せずに全行をその人に(手で決めた行は守る)。文書の書き換え。ed_drill も呼ぶ |
| run_diarize | 591-661 | 要相談(案: 認識・割り当てを pipeline/transcribe、文書への書き込みと名付けを human/proof)#8 | 判別ジョブの本体(71 行)。音声 → 判別 → 文書に反映 → 覚えた声で名前付け → 評価用の文脈の名前付け。JOB_RUNNERS(ed_jobs 1791)・dev/eval_speakers から |
| OVDRAFT_*/_ovdraft_*/ovdraft_candidates/_join_label_spans/ovdraft_for_doc | 662-889 | human/proof | 重なり・抜けの所の空の行の下書き候補(判別の記録を読んで数えるだけ。行を足すのは画面)= 校正の補助。ovdraft_for_doc は serve(/api/overlap-drafts) |
| AUTODIAR_BY/autodiar_enabled/autodiar_ready/autodiar_why_not/autodiar_enqueue/autodiar_after_transcribe/autodiar_skip_at_start/autodiar_name_by_context/_autodiar_record | 890-1040 | 要相談(案: 自動で動かす段は pipeline/transcribe、人が付けた話者を守る判定は human/proof)#9 | 文字起こしのあとの自動の話者判別(評価用は常に・他は設定)。「文字のある行に話者があれば置き換えない」の判定と、判別ジョブの投入と、評価用の名前付け(ed_drill.drill_candidates = eval を読む)が混在。ed_jobs×2(run_job 1876)・ed_evalbatch×3 が呼ぶ |
| VOICES_DIR/VOICE_*/_voices_lock/DEFAULT_SPK_NAME/GENERIC_SPK_*/_spk_name_key/is_generic_speaker_name/voices_path/load_voices/save_voices | 1041-1083 | 要相談(案: 読み口 load_voices は pipeline/transcribe、保存と一般名の判定は human/proof)#3 | 覚えた声(個人を見分けられる学習データ)の置き場と読み書き。recognize_voices(1233 = ① の判別)が読み、run_voice_learn(1386 = ② の学習)が書く。is_generic_speaker_name は ed_drill×2、DEFAULT_SPK_NAME は ed_evalbatch・dev/eval_speakers |
| _unit/_cos/voice_groups/embed_groups | 1084-1129 | pipeline/transcribe | 声の特徴ベクトルの計算の部品(行の選び方・ワーカーへの要求)。voice_groups は voice_learn_plan(1299)も使う |
| embed_fake | 1130-1146 | eval/fake | 疑似の声の特徴(偽の判別と同じ 10 秒の入れ替わり)。tx_worker から |
| _embed_local | 1147-1185 | pipeline/transcribe | 声の特徴の抽出(ワーカーの中だけ)。tx_worker×2 |
| _VOICE_EMPTY/match_voices/match_voices_explain | 1186-1232 | pipeline/transcribe | 特徴ベクトルと覚えた声のコサイン類似度の照合(しきい値 VOICE_MATCH/MARGIN)の計算 |
| recognize_voices | 1233-1294 | 要相談(案: 照合は pipeline/transcribe、名前を文書に書く部分は human/proof)#8 | 判別のあと覚えた声と照らし合わせ、仮の名前の話者に名前を付ける(62 行)。計算(特徴・照合)と、文書への書き込み(_save_lock の中で speakers[].name)と、diar.json の記録が混在。noSub 行・ゲーム音声を除く判定(ed_state.no_sub_row)は文書の形(#7) |
| VOICE_LEARN_TAGS/EVAL_SET_VOICE_MSG/voice_learn_plan/_voice_emb/voice_preview/validate_voice_learn/run_voice_learn/voices_summary/delete_voice | 1295-1464 | human/proof | 「声を覚える/忘れる」= 人の名付けから学習データ(覚えた声)を作る ②。serve から(preview・learn・delete・summary)。ed_drill も voices_summary を使う |
| SPKSUB_SKIP_KINDS/_spksub_key/_spksub_busy/speakers_sub_apply | 1465-1510 | human/proof | 話者の字幕の見た目(色)を名前で文書に当てる(友人の依頼の色)。serve(/api/speakers/sub)から。文書の書き換え |


### ed_learn.py(1312 行)

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| (ヘッダ)docstring・import | 1-26 | ヘッダ(分割後は各行き先が必要な分だけ持つ) | モジュールの説明と import。分割したら各ファイルが自分の分だけ持つ |
| SETTINGS_MAX/_settings_lock/_settings_file/load_settings | 27-43 | ytt(settings) | 設定ファイル(settings.json)を ytt_core.settings.SettingsFile で読む。load_settings は ed_alt・ed_evalbatch・ed_jobs×4・ed_misc・ed_relink×3・ed_speakers×2・ed_store から = 全層が使う |
| SETTINGS_PATCH_KEYS/CUT_SILENCE_RANGE/_KM_ID_RE/_KM_COMBO_RE/_cut_silence_ok/_keymap_ok | 44-80 | 要相談(案: 検査の表は ytt(settings)、鍵ごとの検査は持ち主の層が登録)#10 | api/settings/patch で直してよい鍵と値の検査表。検査が ed_relink._eval_dirs_ok(評価用)・ed_alt.ALT_ENGINES(human)・キー配置(app)・パック(pipeline/pack)の物を参照。plan 4-8 の「設定 1 ファイル・層ごとの節」と合わせて鍵の持ち主を決める。SETTINGS_PATCH_KEYS は ed_thumb も参照 |
| _settings_error/patch_settings/merge_settings/replace_settings | 81-129 | ytt(settings) | 設定の部分更新・差分マージ・丸ごと置換(SettingsFile を呼ぶだけ)。serve の PUT/POST から |
| parse_replacements/_cc/_bounded/wb_split/apply_replacements | 130-191 | pipeline/transcribe | 置換辞書(誤=>正)の解釈と適用の純関数 = 認識の後処理。ed_jobs×3・ed_misc(A/B)・roster が使う。_bounded/wb_split は学習の _spans/learn_rules も使う |
| PUNCT_ONLY/_groups/_prep/NOSUB_IN/OVERLAP_SEC/OVERLAP_PERM/is_nosub/split_nosub/_prep_main | 192-259 | human/proof | 機械の行(original)と人の行の対応づけと noSub の分離。学習(learn_events/learn_groups)と精度(doc_metrics)と保管が共有。_groups は dev/eval_alt×4・eval_asr×2・eval_effort×3 も使う。OVERLAP_SEC/OVERLAP_PERM(227-228)は eval/drill の重なり集計用だが 2 行なので同居 |
| nosub_stats/_ov_sec/is_overlap_group/overlap_orders/overlap_best_counts | 260-315 | eval/drill | 精度の別集計(noSub・声の重なり)。doc_metrics(791)と dev/eval_asr×4 が使う |
| _norm | 316-319 | human/proof | 行のまとまりの文字を連結(学習・精度・保管が共有) |
| learn_events/learn_groups/_info_cache/_doc_info/_all_infos/learned_candidates | 320-457 | human/proof | 人の直しから「誤り → 正しい」の材料を取り出す(修正からの学習。② が作る側)。learned_candidates は serve、learn_events は ed_llm |
| MAX_RULES/_rules_cache/_fb_lock/load_feedback/record_feedback | 458-504 | human/proof | 提案の採用・却下の記録(learn-feedback.json)。record_feedback は serve、load_feedback は ed_jobs×2(run_job の autoLearned)・dev/eval_alt×2・eval_marks×2 が読む(#3) |
| _spans/learn_rules | 505-553 | 要相談(案: 書く側(規則を作る)は human/proof、規則の取り出し口は pipeline/transcribe)#3 | 全文書の直しから規則 {誤,正} を作る(確度の元データ)。suggest_for_doc(提案 = ②)と、run_job の autoLearned・auto_glossary(① が学習データを読む)の両方が呼ぶ。plan 6(B) の「② が作り ① は読むだけ」の読み口が未整理 |
| _match/_tier/find_suggestions/suggest_for_doc | 554-628 | human/proof | 提案(確度 高/中)と alt/yt の候補の合成。校正の補助。suggest_for_doc は ed_alt・ed_ytcap・serve が呼ぶ |
| auto_learned_replace | 629-636 | 要相談(案: human/proof(読み口の整理 #3))#3 | 確度「高」の学習済み置換だけを当てる。_rows_to_doc(ed_jobs 1906)= ① の後処理が呼ぶ |
| load_roster | 637-650 | pipeline/transcribe | 同梱の名簿(hololive-roster.json)を画面向けに整えて読む。serve(/api/roster)・dev/eval_split が呼ぶ。名簿を読むのは roster.py と同じ pipeline/transcribe |
| auto_glossary | 651-666 | 要相談(案: human/proof(読み口の整理 #3))#3 | よく直される正しい語を認識のヒントに足す(learn_rules を読む)。glossary_of(ed_jobs 556)= ① が呼ぶ |
| MAX_LEV_CELLS/_LONG_MARKS/_SMALL_VOWELS/_RUNS/norm_cer/lev_counts/metric_terms/new_acc/acc_line/acc_merge/acc_finish/doc_metrics/config_key/all_metrics | 667-879 | eval/drill | 認識精度(CER)の測定。ed_misc(A/B)・dev/eval_asr×9・serve(/api/metrics)が使う。norm_cer は archive_entries(1040)も使う |
| EVAL_BASE/_base_lock/read_baselines/record_baseline | 880-907 | eval/drill | 評価用の精度の基準(eval-baselines.json)。serve から。EVAL_BASE は serve.set_data_dir が差し替え |
| MAX_EXPORT_CLIPS/MAX_CLIP_SEC/_export_lock/EXPORT_README/export_corrections/_export_corrections_zip | 908-1000 | eval/tools | 修正データ(誤り → 正しいの音声つき zip)の書き出し。serve(/api/export-corrections)のみ。plan 9: 使っていなければ消す(要確認の小さい物) |
| ARCH_*/_arch*/ARCH_README/_join_text/archive_entries/_flac_cut/archive_doc/archive_rebuild_index/_arch_run/start_archive/dataset_stats | 1001-1312 | eval/tools | 校正の成果と音声を dataset/ に保管。serve(start_archive・dataset_stats)のみ。plan 9: データの保管は使っていなければ消す(要確認の小さい物) |


### ed_relink.py(1058 行)

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| (ヘッダ)docstring・import | 1-23 | ヘッダ(分割後は各行き先が必要な分だけ持つ) | モジュールの説明と import。分割したら各ファイルが自分の分だけ持つ |
| RELINK_*/_remote_drive/relink_path/_relink_ref/relink_check/_doc_busy/relink_doc/_relink_write | 24-209 | manage/cases | 動画を選び直す = 文書の動画パスの付け替え(紐づけ)。長さの確認・競合・控え・履歴。serve(check・relink)から。_relink_write は norm_swap・eval の整理も使う |
| NORM_SUFFIX/NORM_PHASE/NORM_MIN_FREE/NORM_WHY/norm_enabled/norm_name/norm_usable/norm_plan/_norm_room | 210-287 | pipeline/ingest | 動画を 30fps にそろえる写しを作るかの判断(作るのは ytt_core.normalize)。取り込んだ動画の下準備なので ingest。NORM_WHY は ytt_core.txindex も読む |
| norm_swap | 288-305 | manage/cases | 作った 30fps の写しへ文書を付け替える(_relink_write 経由・updatedAt を変えない)= 紐づけ |
| norm_run/norm_after_transcribe/_norm_note/norm_start/run_normalize | 306-393 | 要相談(案: 30fps を作る所までは pipeline/ingest、付け替えは manage/cases)#11 | 作り直し → 付け替えをジョブの中で(進み具合・normNote)。ed_jobs.run_job(1874)・JOB_RUNNERS(1796)・ed_relink.relink_doc(norm_start)から。pipeline が付け替え(紐づけ)を知る形になっている |
| FIND_*/_FIND_SKIP/relink_missing/relink_folder/relink_find | 394-487 | manage/cases | 見つからない動画を、選んだフォルダの中の同じファイル名から探す候補(書き込まない)。serve(missing・find)から |
| pick_path | 488-505 | app | ファイル選択の窓(ytt_core.pick)を開く薄い包み。serve(/api/pick)のみ = HTTP の配線の補助 |
| EVAL_DIRS_MAX/EVAL_STATES/EVAL_WALK_*/EVAL_SIDECARS/EVAL_STAGING/_EVAL_MEMBER_RE/_evalorg_lock/_evalorg_last | 506-518 | eval/drill | 評価用フォルダの整理の定数とロック。ed_drill×3・ed_evalbatch・ed_evalaudio・dev/eval_split が参照 |
| _eval_dirs_ok/eval_dirs/in_eval_dir/EVAL_NAME_WORD/eval_name_guard | 519-564 | 要相談(案: 判定だけ ytt(settings)、整理は eval/drill)#12 | 設定 evalDirs から「この動画は評価用のフォルダの中か」を判定。in_eval_dir を ed_alt・ed_jobs(validate_job 606)・ed_store×2(sanitize_transcript・restore_history)・ed_ytcap・serve・_relink_write が呼ぶ = 下の層から使われるので eval に置くと向きが逆。eval_dirs は ed_drill・ed_evalaudio×4・ed_evalbatch×3 |
| _eval_name_re/_eval_state/_eval_walk/_eval_videos/_path_busy | 565-606 | eval/drill | 評価用フォルダの走査(動画の列挙・名前の状態)。_eval_videos は ed_evalaudio・ed_evalbatch が使う |
| _same_drive/_move | 607-637 | 要相談(案: ytt(書き込み))#13 | 別ドライブでも安全な移動(コピー → 大きさ確認 → 元を消す)。評価用の整理が使うが、home/intake×2・dev/eval_split×2 も呼ぶ汎用の部品 |
| _rename_sidecars/_norm_member/_eval_members/_eval_ready/_eval_next_name/_eval_best_member/_eval_settle_one/_eval_copy_index/_eval_adopt_copy/_eval_staging_pass/_eval_outside_docs/_eval_free_name/_eval_intake_one/_eval_intake_pass | 638-874 | eval/drill | 評価用の動画の仮置き・メンバーのフォルダへの整理の内部。_norm_member・_eval_members は ed_drill が使う |
| eval_organize/_eval_docs_by_path/eval_settle/_eval_mark_docs/_eval_rename/eval_folders_info/_evalorg_startup | 875-1058 | eval/drill | 評価用の整理の入口(ボタン・起動時・文書を移ったとき)。serve から(organize・settle・folders_info・startup) |


### ed_misc.py(484 行)

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| (ヘッダ)docstring・import | 1-17 | ヘッダ(分割後は各行き先が必要な分だけ持つ) | モジュールの説明と import。分割したら各ファイルが自分の分だけ持つ |
| MAX_AB_LINES/MAX_AB_VARIANTS/KEEP_EVALS/ab_label/validate_abtest | 18-60 | eval/drill | 設定の比較(A/B)の要求検査。serve から |
| _fake_hyp | 61-67 | eval/fake | A/B の疑似の認識結果(run_abtest 内の fake 分岐用) |
| run_abtest/read_eval/_BROKEN/list_evals | 68-160 | eval/drill | A/B ジョブの本体(同じ行を設定違いで認識して CER を比べる)と結果 evals/*.json の読み出し。run_abtest は JOB_RUNNERS(ed_jobs 1795)から、read_eval・list_evals は serve。ChunkModel・norm_cer を使う |
| OTHER_JSON_MAX/_read_json_file | 161-165 | ytt | 他のツールが書く JSON を大きさの上限つきで読む(ytt_core.fsio.read_json_or の写し)。ed_media・ed_store(スタジオ data.json)・dev/lint が使う |
| studio_out_dir/transcribed_ranges/_covered/read_marker/marker_videos | 166-275 | manage/cases | clip-marker/スタジオの出力フォルダ・マーカー JSON を読み、どの区間が文字起こし済みかを数える連携。read_marker・transcribed_ranges は serve から(studio_out_dir は ed_misc 内だけ。他の studio_out_dir は ytt_core.datadir の別物) |
| progress_stats | 276-303 | manage/cases | 進行度(校正済みの秒・行の数・目標)。ed_store×2・serve・home/accuracy(同名の可能性)が参照 |
| MAX_SCAN_FILES/scan_folder/_done_and_active/add_batch/scan_common | 304-384 | human/proof | フォルダ一括の文字起こしの取り込み(動画を列挙 → validate_job + add_job)。serve(scan・batch)から。画面の一括投入なので human/proof |
| _pipeline_error/clip_info/transcript_v1/export_file | 385-481 | manage/cases | 受け渡し(pipeline_io 経由): 隣の .clip.json を読む・transcript/v1 や SRT・cut-plan を動画の隣に保存。serve から。pipeline_io は plan 7 で manage/cases |
| runtime_path_dir | 482-484 | app | .runtime の置き場の解決(serve が 5 回使う) |


### ed_state.py(491 行)

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| (ヘッダ)docstring・import | 1-22 | ヘッダ(分割後は各行き先が必要な分だけ持つ) | モジュールの説明と import。分割したら各ファイルが自分の分だけ持つ |
| APP_ID/SERVER_VERSION | 23-24 | app | /api/ping の app 名と版(serve が代入)。launch・recorder・mount も読む |
| ROOT | 25-25 | ytt | このフォルダ(コードの置き場)。WORKER_SCRIPT・ROSTER・INDEX・DATA_DIR の既定が基にする。移したあとは各部が自分の場所を持つ |
| INDEX/APP_JS/UI_KIT_JS/PAGE_JS | 26-31 | app | 画面のファイルの場所(serve が配る・起動時検査) |
| DATA_DIR/TX_DIR | 32-33 | ytt | 作業データと文書(transcripts/)の置き場。全部の部品が使う(grep: ed_jobs×3・ed_relink・ed_store×7ほか)。置き場所の規則は ytt |
| ROSTER | 34-34 | pipeline/transcribe | 同梱の名簿ファイルのパス(ed_drill・ed_fill・ed_jobs×3・ed_learn・ed_llm・dev/eval_alt・eval_asr が読む) |
| DATASET_DIR | 35-35 | eval/tools | 校正の成果と音声の保管先 dataset/(ed_learn の archive だけが使う) |
| EVAL_DIR | 36-36 | eval/drill | A/B の結果の置き場 evals/(ed_misc だけが使う) |
| TMP_DIR | 37-37 | ytt | transcripts/.tmp(一時 wav)。ed_alt・ed_jobs×4・ed_learn×5・ed_misc×2・ed_ytcap が使う |
| SETTINGS | 38-38 | ytt(settings) | settings.json のパス。ed_learn の SettingsFile と serve(GET /api/settings)が使う |
| FEEDBACK | 39-39 | human/proof | learn-feedback.json(提案の採否)のパス。ed_learn・serve・home/live_export・dev/eval_alt が使う |
| MARKER_DATA | 40-40 | manage/cases | 旧 clip-marker の data.js(ed_misc.read_marker だけが使う) |
| STUDIO_DATA | 41-41 | ytt | 切り抜きスタジオの data.json のパス(読むだけ)。ed_misc・ed_store・serve・dev/eval_asr・_evalcommon が使う |
| PORT/ALLOWED_HOSTS/BASE_PATH/MAX_BODY | 42-45 | app | HTTP の待ち受けの設定(serve×30、launch・mount も代入) |
| MAX_SEGMENTS/TAGS | 46-47 | human/proof | 文書の行の上限と音のメモの種類(ed_store.sanitize_transcript・ed_learn) |
| MAX_TEXT/OTHER_SPK_*/other_speaker/no_sub_row/ROW_DRAFT_KINDS/blank_draft_row | 48-78 | 要相談(案: ytt/schemas)#7 | 文書の行・話者の形(ゲーム音声など・字幕に出さない・空の下書き)。human の文書(ed_store・ed_speakers・ed_learn・ed_retime)と pipeline(ed_jobs の MAX_TEXT×7・ed_speakers.recognize_voices の no_sub_row)の両方が使う。pipeline が human を import できないので共通の下に置く案 |
| MAX_SPAN_SEC | 79-79 | pipeline/transcribe | 1 回に文字起こしできる長さの上限(6 時間)= 指定の検査値。ed_jobs×2 だけ |
| MAX_QUEUE | 80-80 | human/proof | 待機できるジョブの最大件数。add_job(ed_jobs 678)だけ(ジョブ表 #1) |
| TID_RE | 81-81 | 要相談(案: ytt/schemas)#7 | 文書 id の形(12 桁の 16 進)。ed_alt・ed_drill・ed_evalbatch×3・ed_learn×2・ed_misc×2・ed_relink・ed_speakers ほか全層 |
| MODEL_RE/valid_model | 82-94 | pipeline/transcribe | モデル名の検査。ed_jobs×4・ed_misc・tx_engines×5・dev/eval_asr |
| MEDIA_TYPES | 95-100 | ytt | 拡張子 → MIME(動画・音声の受け入れ判定)。ed_misc×3・ed_relink×6・serve×3 が使う |
| MODELS/LANGS | 101-108 | pipeline/transcribe | 選べるモデルと言語の一覧。MODELS は serve(/api/tools)・tx_engines×6、LANGS は validate_job |
| HALLUC/HALLUC_LINE/HALLUC_LINE_REST/MUSIC_ONLY/LEAK_FLAG/LEAK_MAX_SEC/REP_MIN/REP_RE | 109-123 | pipeline/transcribe | 幻覚・ヒントの漏れ出し・繰り返しの規則(make_flags が使う)。LEAK_FLAG は ed_jobs×4 と tests 8 |
| ApiError | 124-130 | ytt | 全層が raise する共通の例外(code・message・status)。serve×77・ed_jobs×53・ed_learn×21・ed_evalbatch×23 ほか。HTTP 向けの形だが pipeline からも投げる |
| replace_retry/atomic_write/unlink_quiet/file_stamp/plain_int/rss_mb/read_schema_json/union_spans/add_warning/norm_path/now_ms/env_off | 131-193 | ytt | 書き込み・検査・時刻・環境変数の小道具(unlink_quiet・file_stamp・plain_int・rss_mb は既に ytt_core の別名)。atomic_write は ed_learn×9ほか多数、norm_path・now_ms は ed_relink・ed_store・ed_evalbatch が多数 |
| fake_sleep | 194-201 | eval/fake | 疑似のバックエンドの待ち(ed_jobs×4・ed_misc・ed_speakers が呼ぶ) |
| LOG_FILE/CRASH_FILE/RUN_MARK | 202-204 | 要相談(案: ytt(記録の口)と app(起動時の検査))#14 | serve.log・crash ログ・起動中の印のパス。serve.set_data_dir が差し替える。manage/ops 領域(起動し直し・エラーの記録)だが、write_mark を human/proof のジョブ循環(work_one)が呼ぶので ops には置けない |
| TOOL_ID | 205-205 | ytt | docs/spec/pipeline.md の 4 のツール ID "transcribe"(serve×20、SLOTS の枠名、datadir の登録) |
| _pio_mod/pio | 206-222 | 要相談(案: manage/cases(pipeline_io と同じ行き先)。ただし ed_jobs.validate_job が使う)#15 | pipeline_io.py(隣のファイル。clip.json の探し方・runtime の書き方)を遅延で読む。ed_jobs(validate_job の find_clip)・ed_misc×3・ed_store・serve×4。plan 7 では pipeline_io を manage/cases に置くが pipeline/transcribe から使われる |
| log/_run_state/_crash_fp/_mem/setup_logging/write_mark/check_previous_run/clear_mark | 223-282 | 要相談(案: ytt(記録の口)と app(起動時の検査))#14 | ログとクラッシュの記録・起動中の印(前回の異常終了の検出)。log は全層(grep: serve×43・tests 245)。setup_logging・check_previous_run・clear_mark は serve の起動と終了、write_mark は ed_jobs.work_one。_mem は ed_jobs×6 |
| find_ffmpeg/ffmpeg_info/duration_in/media_duration/num/fmt_hms/check_source | 283-333 | ytt | 外部プログラム(ffmpeg)と動画の検査の基盤。find_ffmpeg は ed_evalaudio・ed_evalbatch×2・ed_jobs・ed_learn×2・ed_media・ed_store・serve×2、media_duration は ed_alt・ed_jobs×3・ed_speakers×2・pipeline_io×5 |
| setup_cuda_paths/nvidia_gpu/has_faster_whisper/worker_python/worker_has/cuda_count/cuda_libs_ok/_gpu_ready_local/gpu_ready/_probe_gpu | 334-474 | pipeline/transcribe | GPU・認識部品の有無の検査(別プロセスで 1 回だけ調べる)。setup_cuda_paths は serve・tx_worker・dev/_evalcommon、worker_python は ed_jobs・home/live_archive×2、gpu_ready は ed_jobs・serve |
| backend_name/worker_fake | 475-484 | eval/fake | TRANSCRIBE_BACKEND の読み取り(fake / worker-fake)。backend_name は ed_alt×5・ed_fill・ed_jobs×6・ed_llm・ed_misc・ed_speakers×7・serve×2 から呼ばれる = plan 4-6 で登録の口に置き換える対象 |
| MIXED_FLAG/WEAK_FLAG/NONE_FLAG | 485-491 | 要相談(案: ytt/schemas)#7 | 話者の要確認の印の文言。ed_jobs(SPK_FLAGS)・ed_speakers×3 が使う |


### serve.py(847 行)

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| (ヘッダ)docstring・import | 1-85 | ヘッダ(分割後は各行き先が必要な分だけ持つ) | モジュールの説明と import。分割したら各ファイルが自分の分だけ持つ |
| _load_core | 86-111 | app | ytt_core を sys.path に足す起動の小細工。パッケージ化(ytt/)すれば不要になる見込み |
| APP_ID/SERVER_VERSION | 112-116 | app | /api/ping の app 名と版の正(入口 home/launch.py がこの行を読む)。plan 4-8 で版は 1 つに |
| _ED_MODULES/_ED_OWNER/_ed_owner/__getattr__/_ServeModule/_me | 117-169 | app | serve.名前 を分けた部品へ転送する仕掛け(テスト・ワーカー・dev の測る道具が S.名前 で使う)。plan 10: 最後まで残し RS5 で一括して消す |
| QUIET_PATHS/PAGE_HEADERS/_tid_arg/_ping/_tools_info/_jobs_list/_learned/_metrics/_transcript/GET_API/_job/_id_of/_delete_voice/_cancel/POST_API/_qid/_BODY_ERRORS | 170-331 | app | API の表(パス → 関数)と、1〜数行の接着。実体は ed_* の関数に転送するだけ。_cancel は home/live_archive×8 が別名で使う(名前だけの一致) |
| Handler(検査・応答・do_*) | 332-436 | app | HTTP の検査(Host/Origin/Sec-Fetch-Site)・応答・合言葉・例外の包み |
| Handler._get/_peaks/_media | 437-488 | app | GET の振り分けと、波形・動画の配信(Range は httpsec) |
| Handler._post/_export_corrections | 489-521 | app | POST の振り分けと、修正データ zip の応答(中身は ed_learn.export_corrections) |
| Handler._resolve_package | 522-553 | 要相談(案: app は呼ぶだけ、組み立ては pipeline/pack の resolve_export へ)#16 | Resolve パッケージ zip の要求を組み立てる(配信者の色・話者の色・keeps・row_edge・wrap を集めて resolve_export.create_package)。32 行で、配線を超える組み立てが入っている |
| Handler._put | 554-581 | app | PUT の振り分け(設定・文書・編集の内容)と書き込み失敗の応答 |
| Handler._delete | 582-609 | 要相談(案: human/proof に delete_doc を作り、各層の付き物は登録して消す)#17 | 文書の削除。保存のロックの中で文書本体と付き物(edit.json・words・asr・diar・alt・ytcap・llm)を消す。付き物の持ち主が pipeline(asr・words・diar)と human(alt・ytcap・llm・edit)にまたがり、配線ではなく業務ロジック |
| probe/make_server | 610-633 | app | 同じツールが動いているポートの確認と、空きポートでの待ち受け開始 |
| MIN_FREE_BYTES/_env_warnings/startup_checks | 634-674 | app | 起動時の環境検査(Python・ffmpeg・保存先・空き・index.html・app.js の版・pipeline_io)。画面向けに /api/tools の envWarnings に出す |
| _started | 675-677 | app | 起動の準備を 1 回だけにする印 |
| DATA_ITEMS/set_data_dir | 678-701 | 要相談(案: 置き場所の規則は ytt、各層の定数の書き換えは各層が自分で)#18 | 作業データの置き場を切り替え、ed_state の DATA_DIR・TX_DIR・SETTINGS・FEEDBACK・LOG_FILE ほかと ed_jobs.WORKER_LOG・ed_speakers.DIAR_DIR・ed_learn.EVAL_BASE を一斉に書き換える。ed_state の定数が各層に散らばる限り、ここで全層を知る必要がある |
| studio_data_path | 702-711 | ytt | スタジオの data.json の場所(ytt_core.datadir の規則)。ed_store・dev/_evalcommon×2 が使う |
| choose_data_dir | 712-723 | app | 起動時の作業データの決定(環境変数 → ytt_core.datadir.prepare でコピー) |
| prepare | 724-767 | app | 待ち受け以外の起動の準備(ログ・前回の異常終了・.runtime・環境検査・ジョブのスレッド・評価用の裏スレッド 3 つ)。home/mount・launch からも呼ばれる。評価用の裏スレッド(ed_relink._evalorg_startup・ed_evalbatch・ed_evalaudio)は eval の側が登録する形にする |
| busy/finish | 768-790 | app | 入口の「すべて終了」の確認と、終了の後始末(動かしているジョブの取り消し・ワーカー終了・.runtime 削除) |
| mounted_elsewhere | 791-799 | app | 入口の統合サーバーの中で動いていれば、そのURL(二重起動を避ける) |
| main/_open_running/install_stop_signals | 800-847 | app | 単体起動の入口とシグナルの受け取り |


### ed_store.py(1091 行)

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| (ヘッダ)docstring・import | 1-23 | ヘッダ(分割後は各行き先が必要な分だけ持つ) | モジュールの説明と import。分割したら各ファイルが自分の分だけ持つ |
| tx_path/write_doc/snapshot/backup_doc | 24-48 | human/proof | 文書(transcripts/<id>.json)の書き込みの共通の口と履歴への控え。ed_alt・ed_learn×2・ed_ytcap・serve・ed_jobs×5・ed_relink×2・ed_speakers×5 ほか |
| _sub_color/SUB_STYLE_KEYS/DIAR_NUM_MAX/sanitize_sub_style | 49-74 | human/proof | 話者の字幕の見た目の検査(許可の鍵だけ)。ed_speakers×2・pack の speakerStyles が使う |
| sanitize_transcript | 75-154 | human/proof | 画面から保存される文書の検査・整形(80 行。proofedAt・evalReviewed・評価用を base から引き継ぐ)。ed_drill×3・ed_state・resolve_export・dev/eval_asr が使う |
| doc_length | 155-171 | human/proof | 文書の長さ(秒)。ed_drill×2・dev/eval_asr・eval_effort×4 |
| _summary_cache/_summary_lock/good_row/row_dur/_load_doc/_prog_of/_part/transcript_summary/_tids/prune_cache/summaries | 172-274 | 要相談(案: 基本の要約は human/proof、進行度は manage/cases、ドリルは eval/drill が足す)#19 | 文書 1 件の要約(履歴の一覧・進行度・ドリルの元)。transcript_summary の中で eval/drill の drill_doc_summary(ed_drill)と進行度 _prog_of を作るので human/proof が eval を import している。prune_cache は analyze・store(スタジオ)も使う汎用。_load_doc は read_transcript と共通 |
| _studio_cache/_studio_parse/_studio_load/studio_videos/studio_stream | 275-325 | 要相談(案: 読み取り口を ytt に(pipeline/transcribe からも届くように))#4 | スタジオの data.json(配信者・題名・コラボのまとまり)を読むだけの口。履歴の一覧(list_transcripts)と stream_context(ed_jobs 1019 = pipeline)が使う。ytt_core.txindex は plan 7 で manage/cases なので pipeline からは届かない |
| PACK_CHECK_BUDGET/pack_info/_files_state | 326-367 | manage/cases | 一覧の各文書の「元の動画があるか」「動画の隣のパックがあるか」(txindex.pack_info = 紐づけの規則)。pack_info は home/cases・live_archive・ytt_core.txindex・dev/demo_env・eval_marks が同名で参照 |
| list_transcripts | 368-394 | 要相談(案: manage/cases(束ねる側を上に))#19 | 履歴の一覧: 要約 + 編集の状態 + パックの古さ + スタジオの配信者 + 動画/パックの有無を 1 つに束ねる。束ねる相手が human/cut・manage/cases・ytt にまたがる。serve・ed_misc から |
| read_transcript | 395-404 | human/proof | 文書を読む(id 検査・壊れの区別)。全層(grep: serve×5・ed_drill×4・ed_evalbatch×5・ed_jobs×9 ほか、tests 63) |
| HIST_*/_save_lock/_hist_dir/hist_stamps/hist_snapshot/list_history/save_transcript/restore_history | 405-500 | human/proof | 履歴(自動スナップショット)・保存の競合検出(baseUpdatedAt)・以前の版に戻す。_save_lock は文書を書く全部が使う(ed_jobs×5・ed_relink×7・ed_speakers×5 ほか) |
| MAX_EFFORT_SEC/EFFORT_KEYS/_effort_of/effort_rows/add_effort/set_diar_num | 501-565 | human/proof | 校正の手間(時間・行数)の記録と、文書ごとの話者判別の人数。② の記録。add_effort・set_diar_num は serve、effort_rows は ed_drill・dev/eval_effort |
| EDIT_SCHEMA から wrap_arg(sanitize_edit/sanitize_draft/read_edit/edit_cut_flags/apply_edit_cuts/edit_draft/edit_keeps_sec/keeps_arg/edit_preview) | 566-809 | human/cut | edit.json = カット(残す区間)の検査・読み込み・たたき台・行の cutState 付け直し・プレビュー。apply_edit_cuts は ed_jobs×4・ed_relink・ed_drill・ed_evalbatch が文書を書くたびに呼ぶ。edit_preview は resolve_export を呼ぶ(human → pipeline/pack は順方向) |
| PACK_README_NAMES/pack_readme | 810-836 | manage/cases | 前回のパックの Resolve での手順(パックのフォルダを txindex.is_pack_dir で確かめ、resolve_export.pack_instructions か旧い手順書を読む)= 成果物の紐づけの読み取り。serve から |
| get_edit/save_edit | 837-886 | human/cut | edit.json の取得と保存(rev・409・draft)。serve から。get_edit は pack_stale(下)を呼ぶ |
| PACK_OUTPUT_LOUDNESS/_pack_text/_PACK_REQUIRED/_PACK_OPTIONAL/sanitize_pack_output/record_pack | 887-979 | human/cut | パックを作ったあとの記録(edit.json の pack・output の設定)の検査と保存。② 側の記録。record_pack は serve |
| edit_summary/pack_stale | 980-1002 | human/cut | 一覧用の編集・パックの状態と「作り直しが要る」の規則(1 か所)。get_edit・list_transcripts が使う。manage/cases が読む相手 |
| doc_has_rows/fill_doc | 1003-1030 | human/proof | 文字起こしの無い文書(intoDoc)に結果を入れる。ed_jobs(run_job)・ed_drill・ed_evalbatch が使う |
| probe_media | 1031-1046 | ytt | ffmpeg -i で長さと映像・音声の有無を調べる。ed_media・ed_relink・ed_state が使う |
| _open_lock/find_doc_for_media/open_video | 1047-1091 | human/proof | 「文字起こしせずに開く」: 動画のパスから文書を探し、無ければ作る(clip.json があれば入れる)。serve から。find_doc_for_media は ?media= の紐づけにも使う |


### tx_worker.py(349 行)

| 名前 | 行 | 行き先 | 理由 |
| --- | --- | --- | --- |
| (ヘッダ)docstring・import | 1-35 | ヘッダ(分割後は各行き先が必要な分だけ持つ) | モジュールの説明と import。分割したら各ファイルが自分の分だけ持つ |
| HERE/PROGRESS_EVERY/_protocol_stream/_protocol_input/Out/JobProxy/_seg_dict/_audio | 36-136 | pipeline/transcribe | ワーカーの標準入出力のやり取り(fd 0 から離して読む)・進み具合の送り方・ジョブの代理(ワーカー内の job は dict の代理) |
| install_fakes | 137-206 | eval/fake | TRANSCRIBE_BACKEND=worker-fake のとき、ワーカーの中だけ偽のモデル・偽の判別・偽の特徴を差し込む(70 行)。tx_engines×2 の FAKE 属性を書き換える。test_worker・e2e_ui_mounted が使う |
| _engine/_op_load/_op_transcribe/_op_diarize/_op_embed/_op_complete/OPS/handle/main | 207-349 | pipeline/transcribe | 要求(load・transcribe・diarize・embed・complete)の処理と主ループ。ed_jobs.WORKER_SCRIPT がこのファイルのパスを起動する。S(= serve)の名前を使って ed_jobs._load_model_local・ed_speakers._diarize_local を呼ぶ |


### ファイルごとの行数の合計(行き先別)

- ed_jobs.py(2800 行): pipeline/transcribe 1689 / human/proof 619 / eval/fake 49 / 要相談 404 / ヘッダ(import・docstring) 39
- ed_speakers.py(1510 行): pipeline/transcribe 529 / human/proof 498 / eval/fake 31 / 要相談 419 / ヘッダ(import・docstring) 33
- ed_learn.py(1312 行): pipeline/transcribe 76 / human/proof 332 / eval/drill 297 / eval/tools 405 / ytt(settings) 66 / 要相談 110 / ヘッダ(import・docstring) 26
- ed_relink.py(1058 行): pipeline/ingest 78 / manage/cases 298 / eval/drill 476 / app 18 / 要相談 165 / ヘッダ(import・docstring) 23
- ed_misc.py(484 行): human/proof 81 / manage/cases 235 / eval/fake 7 / eval/drill 136 / app 3 / ytt 5 / ヘッダ(import・docstring) 17
- ed_state.py(491 行): pipeline/transcribe 179 / human/proof 4 / manage/cases 1 / eval/fake 18 / eval/drill 1 / eval/tools 1 / app 12 / ytt 133 / ytt(settings) 1 / 要相談 119 / ヘッダ(import・docstring) 22
- serve.py(847 行): app 668 / ytt 10 / 要相談 84 / ヘッダ(import・docstring) 85
- ed_store.py(1091 行): human/proof 392 / human/cut 410 / manage/cases 69 / ytt 16 / 要相談 181 / ヘッダ(import・docstring) 23
- tx_worker.py(349 行): pipeline/transcribe 244 / eval/fake 70 / ヘッダ(import・docstring) 35
- 9 ファイル合計(9942 行): pipeline/ingest 78 / pipeline/transcribe 2717 / human/proof 1926 / human/cut 410 / manage/cases 603 / eval/fake 175 / eval/drill 910 / eval/tools 406 / app 701 / ytt 164 / ytt(settings) 67 / 要相談 1482 / ヘッダ(import・docstring) 303

### 要相談の一覧

1. ジョブ表・待機列・ワーカー循環・JOB_RUNNERS・add_job/public_job/cancel_job(ed_jobs と ed_state.MAX_QUEUE)。人の目線では「ジョブの進み具合 = human/proof」だが、① 単体(pipeline/run)が認識を動かす入口がこの表以外に無く、_jobs/_jobs_lock は ed_drill・ed_evalbatch・ed_misc・ed_relink・ed_speakers・serve が直に読む。案: 表と循環は human/proof、認識の本体は pipeline の関数にして、JOB_RUNNERS は各層が自分の種別を登録する口に。
   - 該当: ed_jobs.py 40-45(ジョブ表 _jobs/_order/_jobs_lock/_queue/_seq)、ed_jobs.py 135-151(_busy_locked/tid_busy)、ed_jobs.py 641-725(ACTIVE_STATES/EXCLUSIVE/RETRY_KINDS/NO_R)、ed_jobs.py 1790-1802(JOB_RUNNERS)、ed_jobs.py 1940-1993(worker/work_one/cancel_job)
2. ジョブの共通の約束(Cancelled・check_cancel・set_cancelled・job_errors・job_temp_wav・job_done・job_title)。認識の途中(pipeline)と human の部品の両方が呼ぶため、どちらかに置くと向きが逆になる。案: ytt/jobs(SLOTS が既にある ytt_core.jobs の隣)。
   - 該当: ed_jobs.py 72-134(Cancelled/check_cancel/set_cancelled/INT)
3. ① が ② の学習データを読む口(plan 6(B))。今は ed_jobs が ed_learn.learn_rules・load_feedback・auto_learned_replace・auto_glossary と ed_speakers.load_voices を直接呼ぶ(pipeline → human の逆向き)。案: 作る側(learn_events・learn_rules・record_feedback・save_voices・run_voice_learn)は human/proof、読む側(規則の取り出し・覚えた声の読み)は学習データの置き場のファイルを読む関数として pipeline/transcribe に。
   - 該当: ed_speakers.py 1041-1083(VOICES_DIR/VOICE_*/_voices_lock/DEFAULT_)、ed_learn.py 505-553(_spans/learn_rules)、ed_learn.py 629-636(auto_learned_replace)、ed_learn.py 651-666(auto_glossary)
4. スタジオ data.json の読み取り(ed_store.studio_*)。履歴の一覧(human/manage)と stream_context(pipeline/transcribe)の両方が使う。ytt_core.txindex は plan 7 で manage/cases なので pipeline から届かない。案: ytt に読み取り口。
   - 該当: ed_store.py 275-325(_studio_cache/_studio_parse/_studio_load)
5. run_job(ed_jobs 1803-1886)の分け方。案: 音声取り出し → 認識 → 後処理 → 行・original・単語・記録の組み立てまでを pipeline/transcribe の関数(入力 spec・出力 rows と記録)に。文書の作成/fill_doc、evalRedo、30fps・話者判別・redo・alt・ytcap の後続投入は human/proof(または eval/drill)の薄い包みに。RS2 のいちばん重い分割点。
   - 該当: ed_jobs.py 1803-1886(run_job)
6. validate_job の分け方。案: 範囲・モデル・言語・後処理の既定値と検査は pipeline/spec、intoDoc の文書検査・評価用の規則(in_eval_dir)・pio の find_clip は human/proof。
   - 該当: ed_jobs.py 562-640(validate_job)
7. 文書の形の定数(ed_state の MAX_TEXT・OTHER_SPK_*・other_speaker・no_sub_row・ROW_DRAFT_KINDS・blank_draft_row・TID_RE・MIXED/WEAK/NONE_FLAG と ed_jobs.SPK_FLAGS)。human の文書と pipeline の両方が使う。案: ytt/schemas(plain_int などが既にある)。
   - 該当: ed_jobs.py 1994-1996(SPK_FLAGS)、ed_state.py 48-78(MAX_TEXT/OTHER_SPK_*/other_speaker/no_su)、ed_state.py 81-81(TID_RE)、ed_state.py 485-491(MIXED_FLAG/WEAK_FLAG/NONE_FLAG)
8. 話者判別の「計算」と「文書への書き込み」の境目(apply_diarization 系・run_diarize・recognize_voices)。人が付けた行を守る規則(diar_keep_row)は human/proof、声の区間 → 行の割り当て・照合は pipeline/transcribe。案: 計算は純関数にして pipeline、文書に書く包みは human/proof。
   - 該当: ed_speakers.py 445-536(apply_diarization/_spk_ids/diar_keep_row)、ed_speakers.py 591-661(run_diarize)、ed_speakers.py 1233-1294(recognize_voices)
9. autodiar_*(文字起こしのあとの自動の話者判別)。「自動で次の段を動かす」は pipeline/run の仕事、「人が付けた話者を置き換えない」は human/proof の判定、評価用の名前の手がかりは eval/drill(ed_drill.drill_candidates)を読む。3 層にまたがる。
   - 該当: ed_speakers.py 890-1040(AUTODIAR_BY/autodiar_enabled/autodiar_re)
10. SETTINGS_PATCH_KEYS(設定の鍵と検査の表)。検査関数が評価用フォルダ・2 つ目のエンジン・キー配置・パック・サムネの物を参照。plan 4-8(設定 1 ファイル・層ごとの節)に合わせ、鍵の持ち主の層が検査を持ち ytt(settings) の表に登録する形が自然だが、決めてから。
   - 該当: ed_learn.py 44-80(SETTINGS_PATCH_KEYS/CUT_SILENCE_RANGE/_K)
11. ed_relink の 30fps(norm_run・norm_after_transcribe・norm_start・run_normalize)。plan 7 に 30fps の行き先が書かれていない。案: 写しを作る判断(norm_plan など)は pipeline/ingest、付け替え(norm_swap)は manage/cases、ジョブ接着は呼び手の層。
   - 該当: ed_relink.py 306-393(norm_run/norm_after_transcribe/_norm_not)
12. in_eval_dir・eval_dirs・eval_name_guard・_eval_dirs_ok(評価用のフォルダの判定)。plan 7 は ed_relink の評価用フォルダを eval/drill とするが、判定を ed_jobs.validate_job(pipeline)・ed_store.sanitize_transcript/restore_history(human/proof)・_relink_write(manage)・ed_alt・ed_ytcap が呼ぶ。案: 判定だけ ytt(settings)(設定 evalDirs から決まる)に置き、整理(organize・settle)は eval/drill。
   - 該当: ed_relink.py 519-564(_eval_dirs_ok/eval_dirs/in_eval_dir/EVAL)
13. _move・_same_drive(別ドライブ安全な移動)。評価用の整理が主な使い手だが home/intake×2・dev/eval_split×2 も使う汎用部品。案: ytt。
   - 該当: ed_relink.py 607-637(_same_drive/_move)
14. ed_state の記録の口(LOG_FILE・CRASH_FILE・RUN_MARK・log・_run_state・setup_logging・write_mark・check_previous_run・clear_mark・_mem)。plan では manage/ops(エラーの記録・起動し直し)だが、log は全層、write_mark は human/proof のジョブ循環が呼ぶ。案: log と write_mark は ytt、起動時の検査(setup_logging・check_previous_run・clear_mark)は app。
   - 該当: ed_state.py 202-204(LOG_FILE/CRASH_FILE/RUN_MARK)、ed_state.py 223-282(log/_run_state/_crash_fp/_mem/setup_logg)
15. ed_state.pio(pipeline_io.py の遅延ロード)。plan 7 は pipeline_io を manage/cases に置くが、ed_jobs.validate_job(pipeline/spec)が find_clip を呼ぶ。案: find_clip の部分だけ ytt(schemas の clip 読み)に降ろすか、spec の検査を human 側に置く。
   - 該当: ed_state.py 206-222(_pio_mod/pio)
16. serve の _resolve_package(32 行)に配線を超える組み立て(配信者の色・話者の色・keeps・row_edge・wrap)が入っている。案: resolve_export(pipeline/pack)に 1 関数を作り、app は呼ぶだけ。
   - 該当: serve.py 522-553(Handler._resolve_package)
17. serve の _delete(文書の削除)。付き物(edit.json・words・asr・diar・alt・ytcap・llm)の持ち主が pipeline と human にまたがる。案: human/proof に delete_doc を作り、各層が付き物のパスを登録する。
   - 該当: serve.py 582-609(Handler._delete)
18. serve.set_data_dir が ed_state・ed_jobs・ed_speakers・ed_learn の定数を一括で書き換える。案: 置き場所の規則は ytt(datadir は既に ytt_core)に集め、各層は関数で毎回解決する形にして、この書き換えをやめる(plan 4-7 では置き場所は当面そのまま)。
   - 該当: serve.py 678-701(DATA_ITEMS/set_data_dir)
19. 文書の一覧・要約(ed_store.transcript_summary・list_transcripts)。要約の中で ed_drill.drill_doc_summary(eval/drill)と進行度(manage)を作るため human/proof が上の層を import している。案: 基本の要約は human/proof、進行度は manage/cases、ドリルは eval/drill が登録の口から足す。list_transcripts は束ねる側として manage/cases。
   - 該当: ed_store.py 172-274(_summary_cache/_summary_lock/good_row/ro)、ed_store.py 368-394(list_transcripts)

