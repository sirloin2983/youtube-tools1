# コードの地図: ③ human(人の操作)

自動で作った物(`python dev/code_map.py`)。手で直さない。目次は [index.md](index.md)。`file:line` の行の番号は作った時点の物。

## src/human/

- **__init__.py** (2 行) — ③ 人の操作。① ② の成果物とは別に人の直し(人の層・上書き)を書き、その段からやり直しを頼む。人の直しから学習データを作る。ytt と ② flow を import してよい(① pipeline は ② を通す)
- **judgments.py** (194 行) — 人の判断の記録(judgments.jsonl。MARKS-3 の S1a)。人か友人が切り抜きを判断したときだけ 1 行足す。評価と学習が読む人の判断はここだけ。
  - 名前: `friend_value` :38・`path` :47・`record` :114・`rows` :145・`keys` :160・`fold` :171
- **judgments_migrate.py** (395 行) — 今の記録から人の判断だけを人の判断の記録(judgments.jsonl)へ 1 回写す道具(MARKS-3 の S2)。元の記録は読むだけで、消さない・直さない。
  - 名前: `dirs` :104・`build` :314・`apply` :350・`report` :362・`main` :376

## src/human/check/

- **__init__.py** (3 行) — ③ 確かめる(V1。カードの答えの記録 answerlog・答えを実物へ反映する土台 apply・文書の行を直す口 _doc と、種類ごとの反映 read・timerow・value・voice。
- **_doc.py** (60 行) — 「確かめる」の文書の行を直す 1 つの口(読み・時刻・声のカードの反映と Z が使う。opt-human 6-1)。
  - 名前: `busy` :21・`edit_row` :29・`flag_parts` :53・`join_flags` :58
- **answerlog.py** (182 行) — 「確かめる」の答えの記録(notes:docs/design/v1-check-build.md の 3-1)。
  - 名前: `answers_path` :43・`new_id` :51・`day_of` :56・`append` :61・`class State` :92・`state` :159・`read_skips` :165・`add_skip` :173
- **apply.py** (287 行) — 「確かめる」の答えを実物へ反映する土台(notes:docs/design/v1-check-build.md の 3-2・3-3)。
  - 名前: `class Refused` :42・`class Context` :50・`register` :73・`flush` :211・`answer` :218・`undo` :259・`skip` :280
- **cutcard.py** (68 行) — 「確かめる」の自動カットのカードの答えの記録(CUT-CARD。決定: plan/opt-eval.md の Q4 自動カットのカード)。
  - 名前: `enabled` :27
- **read.py** (149 行) — 「確かめる」の読みのカード(どちらの読みが正しいか)の反映(notes:docs/design/v1-check-build.md の 2-2・3-2。import で apply に登録する)。
  - 名前: `_check` :23・`_tid` :37・`_unflag` :44・`_row_state` :48・`_feedback` :53・`_cand_of` :65・`_apply` :72・`_same` :113・`_revert` :119
- **section.py** (261 行) — 「確かめる」の評価のレーンの区間カードの反映(C-EVAL (2)。決定 3-47「確かめると評価をまとめる」・3-49 Q2。設計の相談は Fable)。
  - 名前: `enabled` :245
- **speech.py** (88 行) — 「確かめる」の「この行は声ですか?」の反映(notes:docs/design/v1-check-build.md・C-EVAL (3))。
  - 名前: `_check` :17・`_row_of` :24・`_tags` :32・`_state` :36・`_apply_speech` :41・`_revert_speech` :57
- **timerow.py** (91 行) — 「確かめる」の時刻のカード「行の時刻が合っているか」の反映(notes:docs/design/v1-check-build.md の 3-2・5 節・決定 3-41)。
  - 名前: `_move` :19・`_check` :27・`_row_of` :39・`_apply_time` :47・`_revert_time` :66
- **value.py** (180 行) — 「確かめる」の価値のカード(切り抜く価値があるか = 70 点以上か)の反映(notes:docs/design/v1-check-build.md・決定 3-41)。
  - 名前: `_check` :32・`_code` :41・`_msg` :45・`_need` :49・`_auto_check` :59・`_auto_apply` :73・`_auto_revert` :84・`_studio` :100・`_set_status` :107・`_cand_apply` :136・`_cancel_export` :151・`_cand_revert` :166
- **voice.py** (366 行) — 「確かめる」の誰の声のカード(voice:diar)の答えの形・選択肢・反映・声の覚え直し(notes:docs/design/v1-check-build.md の 3-2・5 節、
  - 名前: `doc_embedding` :48・`registry` :52・`options_for` :67・`guess_for` :88

## src/human/cut/

- **__init__.py** (2 行) — ③ カット(残す区間・たたき台)。今は空 = カットとパックの口は human/proof/store の後半(割るのは OPT2。notes:plan/done/opt-human.md の 2e-1)

## src/human/find/

- **__init__.py** (3 行) — ③ 配信の検索(YouTube Data API・事務所の登録)
- **fake_yt.py** (119 行) — ① 配信の検索 rank.py の疑似 YouTube Data API(STUDIO_FAKE=1 のときだけ使う。ネットワークなし。e2e と画面の確かめが使う)。
  - 名前: `fake_channel_id` :20・`fake_video` :24・`fake_get` :34・`fake_live` :97
- **rank.py** (655 行) — ③ 配信の検索: 事務所・所属チャンネルの登録と、YouTube Data API による検索ジョブ。
  - 名前: `yt_get` :64・`parse_ref` :74・`sanitize_registry` :100・`load_registry` :133・`parse_regions` :275・`validate_search` :324・`run_search` :450・`parse_live_agencies` :543・`live_list` :556・`get_registry` :579・`put_registry` :583・`resolve` :590・ほか 8

## src/human/friend/

- **__init__.py** (2 行) — ③ 友人: 受付(Dropbox)→ まとめて実行(②)に流す → 届ける。友人の返事・送り返し・ライブの依頼の結びつき
- **friend_feedback.py** (142 行) — 友人の「要らない」を PC 側で片付ける(notes:docs/spec/friend.md の 2-14。2026-10-08 ユーザー「不採用の場合こちらにフィードバック」)。
  - 名前: `record_delivery` :26・`find_delivery` :37・`apply` :99
- **intake.py** (906 行) — 友人からの依頼の受付(notes:docs/spec/friend.md。2026-09-30)。
  - 名前: `configured_folder` :74・`out_dir_of` :85・`submit_urls` :95・`submit_file` :122・`youtube_id` :132・`parse_lines` :138・`parse_url_file` :164・`decode_text` :172・`probe_video` :186・`youtube_info` :198・`parse_speakers` :265・`parse_ranges` :300・ほか 4
- **live_requests.py** (102 行) — 友人のライブ配信の依頼と録画の結びつき(notes:docs/spec/friend.md の 2-15。ホーム 0.47.0)。
  - 名前: `settings_label` :26・`key_of` :31・`class Store` :35
- **returns.py** (494 行) — ③ 人の層: 友人からの送り返しを受け取って並べる(F1 の F2。notes:docs/design/f1-build.md の (f1d))。
  - 名前: `class Refused` :54・`returns_dir` :58・`extract` :96・`parse_verdict` :130・`parse_notice` :177・`scan` :212・`recent_notices` :404・`iter_requests` :443・`requested_videos` :479

## src/human/proof/

- **__init__.py** (2 行) — ③ 字幕の校正(文書の置き場と機械の層・人の層・カットの「カット済」・文字起こしと再認識のジョブ・別の読み・話者と声・辞書と名簿の学習・校正の記録)
- **alt.py** (403 行) — ③ 人の操作の層 human/proof: 2つ目のエンジンとの食い違いに候補を出す(精度改善の計画 第2版 D1-b。notes:plan/line-b-transcription.md)。
  - 名前: `alt_engine_key` :61・`alt_info` :70・`alt_first_run` :79・`alt_spec` :88・`alt_path` :121・`read_alt` :126・`run_alt` :136・`alt_after_transcribe` :160・`alt_notation_only` :193・`alt_diffs` :220・`alt_cached` :331・`alt_spans_of` :343・ほか 3
- **doc_jobs.py** (405 行) — ③ 人の操作の層 human/proof: 文字起こしのジョブの本体(run_job)と書く先の決め方・受付(validate_job・
  - 名前: `set_learning` :40・`glossary_of` :45・`validate_job` :62・`public_job` :131・`subtitle_settings` :169・`split_chars_for` :183・`learned_finder` :201・`dict_learned` :212・`carry_overrides` :230・`run_job` :269・`validate_retranscribe` :331・`redo_targets` :383
- **layers.py** (1061 行) — ③ 文書を「機械の層 + 人の層」から組み立てる純粋な関数(O2-1。RS8・2026-10-11。決定 3-37 の (r8r)〜(r8u)・notes:plan/done/rs8-cases-ui.md の決めたこと 3)。
  - 名前: `match` :65・`join_flags` :126・`compose_rows` :328・`compose` :424・`split_meta` :445・`diff` :551・`mach_changes` :636・`pick` :656・`assign_speakers` :692・`carry` :747・`mach_from_doc` :829・`advance_mach` :870・ほか 5
- **learn.py** (470 行) — ③ 人の操作の層 human/proof: 人が直した内容からの学習(機械の出力と人の行の対応づけ・「誤=>正」の統計・確度)と、行への修正の提案・
  - 名前: `align_groups` :29・`prep_rows` :48・`is_nosub` :63・`split_nosub` :67・`row_text` :92・`learn_events` :103・`learn_groups` :145・`learned_candidates` :198・`load_feedback` :228・`unrecord_feedback` :258・`record_feedback` :280・`forget_doc` :302・ほか 7
- **machpick.py** (46 行) — ③ 3 択の口(RS8 O2-4。決定 3-37・notes:plan/done/rs8-cases-ui.md の決めたこと 3 の案 A): 機械の結果が変わって人の直しと食い違う行(印 layers.MACH_CHANGED)を
  - 名前: `changes` :15・`pick` :24
- **rerun.py** (357 行) — ③ 人の操作の層 human/proof: 再認識(選んだ行 each・範囲 range・全体 whole)のジョブの本体と、文書への反映・
  - 名前: `record_rerun` :47・`apply_retranscribe` :83・`replace_original_multi` :152・`thin_rows` :171・`apply_range` :184・`run_retranscribe` :229・`rebuild_whole` :275・`validate_rerun` :330
- **retime.py** (32 行) — ③ 人の操作の層 human/proof: 行の時刻の候補の API の包み POST /api/retime {id, rows: [行の id…]}
  - 名前: `retime_engine` :12・`retime_doc` :18
- **speakers.py** (671 行) — ③ 人の操作の層 human/proof: 話者判別の結果を文書へ(apply_diarization・1 人指定 single_speaker・守る行 diar_keep_row)・判別のジョブの受付と文書への書き込み(validate_diarize・
  - 名前: `set_context_namer` :29・`check_context_namer` :38・`apply_diarization` :60・`diar_keep_row` :77・`validate_diarize` :168・`single_speaker` :191・`run_diarize` :219・`autodiar_enabled` :267・`autodiar_ready` :272・`autodiar_enqueue` :292・`autodiar_after_transcribe` :324・`is_generic_speaker_name` :405・ほか 7
- **store.py** (1190 行) — ③ 文書の置き場: 文書を書く唯一の口 commit と機械の層・人の層(層が正 = 文書は組み立て済みの写し・古い写しの読み直し fresh_copy)・保存の錠 saving・
  - 名前: `tx_path` :38・`write_doc` :42・`read_layers` :82・`commit` :123・`layers_for` :180・`fresh_copy` :210・`snapshot` :260・`backup_doc` :268・`sanitize_sub_style` :287・`sanitize_transcript` :300・`doc_length` :382・`good_row` :403・ほか 38

## src/human/review/

- **__init__.py** (3 行) — ③ 候補の確認(手動マーク・採用と不採用・端の調整・その記録)
- **feedback.py** (115 行) — 判定の記録(feedback.jsonl)。確認画面での人の結果(採用・不採用・削除・書き出し)と、人の最終の操作(手で足した・消した・採用の取り消し)を
  - 名前: `feedback_path` :17・`feedback_for_mark` :66・`nearest_auto` :83・`feedback_event` :106
- **store.py** (1044 行) — ③ 動画とマークの保存(data.json)。スレッドセーフ・原子的に書き込む。スタジオの `Store` が書き手(スタジオなしの書き手は ② flow/studiobook の StudioBook)。
  - 名前: `offset_from_anchors` :104・`class SeriesCache` :203・`class Store` :242

## テスト

- src/human/check/tests/test_apply.py — 「確かめる」の答えの記録(src/human/check/answerlog.py)と反映の土台(apply.py)の単体テスト。一時フォルダと偽の反映の部品だけを使う。
- src/human/check/tests/test_cutcard.py — 「確かめる」の自動カットのカードの答えの記録(src/human/check/cutcard.py)の単体テスト: 答えの形(出どころごとの選び)・
- src/human/check/tests/test_read.py — 「確かめる」の読みのカードの反映(src/human/check/read.py。V2b)の単体テスト。一時フォルダの文書と learn-feedback.json だけを使う。
- src/human/check/tests/test_section.py — 評価のレーンの区間カードの反映(src/human/check/section.py。C-EVAL)の単体テスト。一時の作業データに評価用の文書を作って、答える・戻すを確かめる。
- src/human/check/tests/test_speech.py — 「この行は声ですか?」の反映(src/human/check/speech.py)の単体テスト: 答えの形・keep は文書を触らない・drop は noSub と novoice を付ける(行は消さない・
- src/human/check/tests/test_timerow.py — 時刻のカードの反映(src/human/check/timerow.py)の単体テスト。一時の作業データに文書を作って、答える・戻すを確かめる。
- src/human/check/tests/test_value.py — 価値のカードの反映(src/human/check/value.py)の単体テスト。入口が渡す口(studio)は偽物。value:auto は記録だけ(案件の口を呼ばない)。
- src/human/check/tests/test_voice.py — 「確かめる」の誰の声のカード(src/human/check/voice.py。V1 V2c)の単体テスト: 答えの形・選択肢と予想・文書の行への反映(commit why check:voice)と Z・
- src/human/friend/tests/test_friend_feedback.py — 友人の「要らない」を PC 側で片付ける(src/human/friend/friend_feedback.py)の単体テスト。ごみ箱は本物の cleanup.Cleanup(一時フォルダ)。
- src/human/friend/tests/test_intake.py — 友人からの依頼の受付(src/human/friend/intake.py)の単体テスト。まとめて実行・ffprobe・yt-dlp は偽物。
- src/human/friend/tests/test_live_requests.py — 友人のライブ配信の依頼と録画の結びつきの Store(src/human/friend/live_requests.py。入口の作業データの live/requests.json。2-15)のテスト。
- src/human/friend/tests/test_returns.py — src/human/friend/returns.py(友人の送り返しの受け取り。F1 の F2)のテスト。リポジトリ直下で:
- src/human/proof/tests/test_commit.py — 文書を書く唯一の口 human/proof/store.commit のテスト(RS8 O2-0。動きは write_doc と同じ・why をログに残す)。
- src/human/proof/tests/test_doc_jobs.py — human/proof/doc_jobs のテスト(差し込みの口 set_hooks は X-RERUN で消した・serve なしで読める・人の行の引き継ぎ)。
- src/human/proof/tests/test_doc_placement.py — 文書の置き場所(ytt/docloc の索引)を人の側の部品が使うことのテスト(RS8 B-2-1b)。
- src/human/proof/tests/test_layers.py — 文書を「機械の層 + 人の層」から組み立てる関数(human/proof/layers。RS8 O2-1)のテスト。
- src/human/proof/tests/test_machpick.py — 3 択の口(human/proof/machpick と layers.mach_changes・pick。RS8 O2-4)のテスト。
- src/human/proof/tests/test_opt_h1_fixes.py — ③ 校正の小物の直し(OPT-H1。notes:plan/done/opt-human.md の役割 4・5)のテスト。serve なしで読める。
- src/human/proof/tests/test_primary_ops.py — 層が正(機械の層 + 人の層)のときの機械の操作(RS8 O2-5)のテスト。
- src/human/review/tests/test_studio.py — human/review/store.py の単体テスト(ネットワーク・ffmpeg 不要)。 実行(リポジトリ直下): py -3.12 -m unittest src/human/review/tests/test_studio.py
- src/human/tests/_workdata.py — 人の操作のテストが共有する、一時の作業データの準備(S4)。
- src/human/tests/test_judgments.py — 人の判断の記録(human/judgments)のテスト: 書いて読む・壊れた行・key の重複・fold の 3 レーンと retract と時刻順・.old・知らない what
- src/human/tests/test_judgments_migrate.py — 今の記録から人の判断の記録への写し(human/judgments_migrate)のテスト: 下見の数・スイッチが既定でオフ・書く行・二度流しても増えない・
