# コードの地図: ③ human(人の操作)

自動で作った物(`python dev/code_map.py`)。手で直さない。目次は [index.md](index.md)。`file:line` の行の番号は作った時点の物。

## src/human/

- **__init__.py** (2 行) — ③ 人の操作。① ② の成果物とは別に人の直し(人の層・上書き)を書き、その段からやり直しを頼む。人の直しから学習データを作る。ytt と ② flow を import してよい(① pipeline は ② を通す)
- **judgments.py** (204 行) — 人の判断の記録(judgments.jsonl。MARKS-3 の S1a)。人か友人が切り抜きを判断したときだけ 1 行足す。評価と学習が読む人の判断はここだけ。
  - 名前: `friend_value` :38・`path` :47・`record` :114・`retract` :124・`rows` :155・`keys` :170・`fold` :181

## src/human/check/

- **__init__.py** (3 行) — ③ 確かめる(V1。カードの答えの記録 answerlog・答えを実物へ反映する土台 apply・文書の行を直す口 _doc と、種類ごとの反映 read・timerow・value・voice・speech・section・cutcard。
- **_doc.py** (104 行) — 「確かめる」の文書の行を直す 1 つの口(読み・時刻・声のカードの反映と Z が使う。opt-human 6-1)。
  - 名前: `busy` :22・`edit_row` :30・`edit_fields` :54・`revert_fields` :64・`doc_id` :78・`row_target` :86・`choice` :96
- **answerlog.py** (182 行) — 「確かめる」の答えの記録(notes:docs/design/v1-check-build.md の 3-1)。
  - 名前: `answers_path` :43・`new_id` :51・`day_of` :56・`append` :61・`class State` :92・`state` :159・`read_skips` :165・`add_skip` :173
- **apply.py** (282 行) — 「確かめる」の答えを実物へ反映する土台(notes:docs/design/v1-check-build.md の 3-2・3-3)。
  - 名前: `class Context` :45・`register` :68・`flush` :206・`answer` :213・`undo` :254・`skip` :275
- **cutcard.py** (54 行) — 「確かめる」の自動カットのカードの答えの記録(CUT-CARD。決定: plan/opt-eval.md の Q4 自動カットのカード)。
  - 名前: `enabled` :27
- **read.py** (141 行) — 「確かめる」の読みのカード(どちらの読みが正しいか)の反映(notes:docs/design/v1-check-build.md の 2-2・3-2。import で apply に登録する)。
  - 名前: `_check` :23・`_tid` :37・`_unflag` :41・`_row_state` :45・`_feedback` :50・`_cand_of` :62・`_apply` :69・`_same` :111・`_revert` :116
- **section.py** (261 行) — 「確かめる」の評価のレーンの区間カードの反映(C-EVAL (2)。決定 3-47「確かめると評価をまとめる」・3-49 Q2。設計の相談は Fable)。
  - 名前: `enabled` :245
- **speech.py** (60 行) — 「確かめる」の「この行は声ですか?」の反映(notes:docs/design/v1-check-build.md・C-EVAL (3))。
  - 名前: `_state` :15・`_apply_speech` :21・`_revert_speech` :37
- **timerow.py** (83 行) — 「確かめる」の時刻のカード「行の時刻が合っているか」の反映(notes:docs/design/v1-check-build.md の 3-2・5 節・決定 3-41)。
  - 名前: `_move` :19・`_check` :27・`_times` :39・`_apply_time` :43・`_revert_time` :65
- **value.py** (167 行) — 「確かめる」の価値のカード(切り抜く価値があるか = 70 点以上か)の反映(notes:docs/design/v1-check-build.md・決定 3-41)。
  - 名前: `_code` :32・`_msg` :36・`_need` :40・`_auto_check` :50・`_auto_apply` :64・`_auto_revert` :75・`_studio` :87・`_set_status` :94・`_cand_apply` :123・`_cancel_export` :138・`_cand_revert` :153
- **voice.py** (356 行) — 「確かめる」の誰の声のカード(voice:diar)の答えの形・選択肢・反映・声の覚え直し(notes:docs/design/v1-check-build.md の 3-2・5 節、
  - 名前: `doc_embedding` :49・`registry` :54・`options_for` :69・`guess_for` :90

## src/human/cut/

- **__init__.py** (2 行) — ③ カット(残す区間・たたき台)。中身は無い = カットとパックの口は human/proof/store の後半(notes:plan/done/opt-human.md の 2e-1)

## src/human/find/

- **__init__.py** (2 行) — ③ 配信の検索(YouTube Data API・事務所の登録)
- **fake_yt.py** (119 行) — ① 配信の検索 rank.py の疑似 YouTube Data API(STUDIO_FAKE=1 のときだけ使う。ネットワークなし。e2e と画面の確かめが使う)。
  - 名前: `fake_channel_id` :20・`fake_video` :24・`fake_get` :34・`fake_live` :97
- **rank.py** (640 行) — ③ 配信の検索: 事務所・所属チャンネルの登録と、YouTube Data API による検索ジョブ。
  - 名前: `yt_get` :64・`parse_ref` :74・`sanitize_registry` :100・`load_registry` :133・`parse_regions` :274・`validate_search` :323・`run_search` :449・`parse_live_agencies` :542・`live_list` :555・`get_registry` :578・`put_registry` :582・`resolve` :589・ほか 7

## src/human/friend/

- **__init__.py** (2 行) — ③ 友人: 受付(Dropbox)→ まとめて実行(②)に流す → 届ける。友人の返事・送り返し・ライブの依頼の結びつき
- **friend_feedback.py** (118 行) — 友人の「要らない」を PC 側で片付ける(notes:docs/spec/friend.md の 2-14。ユーザー「不採用の場合こちらにフィードバック」)。
  - 名前: `record_delivery` :24・`find_delivery` :29・`apply` :82
- **intake.py** (814 行) — 友人からの依頼の受付(notes:docs/spec/friend.md)。
  - 名前: `configured_folder` :77・`out_dir_of` :88・`submit_urls` :93・`submit_file` :117・`youtube_id` :127・`parse_lines` :133・`decode_text` :159・`probe_video` :173・`youtube_info` :185・`parse_ranges` :233・`class Intake` :262
- **live_requests.py** (22 行) — 友人のライブ配信の依頼と録画の結びつき(notes:docs/spec/friend.md の 2-15)。
  - 名前: `settings_label` :19
- **returns.py** (479 行) — ③ 人の層: 友人からの送り返しを受け取って並べる(F1 の F2。notes:docs/design/f1-build.md の (f1d))。
  - 名前: `returns_dir` :57・`extract` :95・`parse_verdict` :129・`parse_notice` :179・`scan` :214・`recent_notices` :405・`iter_requests` :444

## src/human/proof/

- **__init__.py** (2 行) — ③ 字幕の校正(文書の置き場と機械の層・人の層・カットの「カット済」・文字起こしと再認識のジョブ・別の読み・話者と声・辞書と名簿の学習・校正の記録)
- **alt.py** (416 行) — ③ 人の操作の層 human/proof: 2つ目のエンジンとの食い違いに候補を出す(精度改善の計画 第2版 D1-b。notes:plan/line-b-transcription.md)。
  - 名前: `alt_engine_key` :61・`alt_info` :70・`alt_first_run` :79・`alt_spec` :88・`alt_path` :121・`read_alt` :126・`run_alt` :136・`alt_after_transcribe` :160・`alt_notation_only` :193・`alt_diffs` :220・`alt_cached` :344・`alt_spans_of` :356・ほか 3
- **doc_jobs.py** (358 行) — ③ 人の操作の層 human/proof: 文字起こしのジョブの本体(run_job)と書く先の決め方・受付(validate_job と
  - 名前: `set_learning` :39・`glossary_of` :44・`validate_job` :61・`public_job` :130・`subtitle_settings` :168・`split_chars_for` :182・`learned_finder` :200・`dict_learned` :211・`carry_overrides` :229・`run_job` :268・`run_transcribe_job` :278・`redo_targets` :336
- **layers.py** (1056 行) — ③ 文書を「機械の層 + 人の層」から組み立てる純粋な関数(O2-1。RS8。決定 3-37 の (r8r)〜(r8u)・notes:plan/done/rs8-cases-ui.md の決めたこと 3)。
  - 名前: `match` :65・`compose_rows` :323・`compose` :419・`split_meta` :440・`diff` :546・`mach_changes` :631・`pick` :651・`assign_speakers` :687・`carry` :742・`mach_from_doc` :824・`advance_mach` :865・`replace_mach_span` :913・ほか 4
- **learn.py** (450 行) — ③ 人の操作の層 human/proof: 人が直した内容からの学習(機械の出力と人の行の対応づけ・「誤=>正」の統計・確度)と、行への修正の提案・
  - 名前: `align_groups` :28・`prep_rows` :47・`is_nosub` :62・`split_nosub` :66・`row_text` :91・`learn_events` :102・`learn_groups` :144・`load_feedback` :208・`unrecord_feedback` :238・`record_feedback` :260・`forget_doc` :282・`learn_rules` :301・ほか 6
- **machpick.py** (46 行) — ③ 3 択の口(RS8 O2-4。決定 3-37・notes:plan/done/rs8-cases-ui.md の決めたこと 3 の案 A): 機械の結果が変わって人の直しと食い違う行(印 layers.MACH_CHANGED)を
  - 名前: `changes` :15・`pick` :24
- **rerun.py** (454 行) — ③ 人の操作の層 human/proof: 再認識(選んだ行 each・範囲 range)のジョブの本体と、文書への反映・
  - 名前: `record_rerun` :49・`apply_retranscribe` :85・`replace_original_multi` :154・`thin_rows` :173・`apply_range` :186・`run_retranscribe` :231・`rebuild_whole` :277・`validate_retranscribe` :361・`validate_whole` :397・`validate_rerun` :425
- **retime.py** (32 行) — ③ 人の操作の層 human/proof: 行の時刻の候補の API の包み POST /api/retime {id, rows: [行の id…]}
  - 名前: `retime_engine` :12・`retime_doc` :18
- **speakers.py** (684 行) — ③ 人の操作の層 human/proof: 話者判別の結果を文書へ(apply_diarization・1 人指定 single_speaker・守る行 diar_keep_row)・判別のジョブの受付と文書への書き込み(validate_diarize・
  - 名前: `set_context_namer` :29・`check_context_namer` :38・`apply_diarization` :60・`diar_keep_row` :77・`validate_diarize` :169・`single_speaker` :193・`run_diarize` :221・`autodiar_enabled` :273・`autodiar_ready` :278・`autodiar_enqueue` :298・`autodiar_after_transcribe` :330・`is_generic_speaker_name` :417・ほか 7
- **store.py** (1181 行) — ③ 文書の置き場: 文書を書く唯一の口 commit と機械の層・人の層(層が正 = 文書は組み立て済みの写し・古い写しの読み直し fresh_copy)・保存の錠 saving・
  - 名前: `tx_path` :37・`write_doc` :41・`read_layers` :73・`commit` :114・`layers_for` :171・`fresh_copy` :201・`snapshot` :251・`backup_doc` :259・`sanitize_sub_style` :278・`sanitize_transcript` :291・`doc_length` :373・`good_row` :394・ほか 38

## src/human/review/

- **__init__.py** (2 行) — ③ 候補の確認(手動マーク・採用と不採用・端の調整・その記録)
- **machinelog.py** (102 行) — スタジオのマークの機械の記録(machine_marks.jsonl。10-19 ③ の統合 Q2 で feedback.jsonl から名前を変えた)。
  - 名前: `path` :33・`record` :63・`nearest_auto` :81
- **store.py** (851 行) — ③ 動画とマークの保存(data.json)。スレッドセーフ・原子的に書き込む。スタジオの `Store` が書き手(スタジオなしの書き手は ② flow/studiobook の StudioBook)。
  - 名前: `offset_from_anchors` :97・`class SeriesCache` :197・`class Store` :236

## テスト

- tests/human/_workdata.py — 人の操作のテストが共有する、一時の作業データの準備(S4)。
- tests/human/test_judgments.py — 人の判断の記録(human/judgments)のテスト: 書いて読む・壊れた行・key の重複・fold の 3 レーンと retract と時刻順・.old・知らない what
- tests/human/check/test_apply.py — 「確かめる」の答えの記録(src/human/check/answerlog.py)と反映の土台(apply.py)の単体テスト。一時フォルダと偽の反映の部品だけを使う。
- tests/human/check/test_cutcard.py — 「確かめる」の自動カットのカードの答えの記録(src/human/check/cutcard.py)の単体テスト: 答えの形(出どころごとの選び)・
- tests/human/check/test_read.py — 「確かめる」の読みのカードの反映(src/human/check/read.py)の単体テスト。一時フォルダの文書と learn-feedback.json だけを使う。
- tests/human/check/test_section.py — 評価のレーンの区間カードの反映(src/human/check/section.py)の単体テスト。一時の作業データに評価用の文書を作って、答える・戻すを確かめる。
- tests/human/check/test_speech.py — 「この行は声ですか?」の反映(src/human/check/speech.py)の単体テスト: 答えの形・keep は文書を触らない・drop は noSub と novoice を付ける(行は消さない・
- tests/human/check/test_timerow.py — 時刻のカードの反映(src/human/check/timerow.py)の単体テスト。一時の作業データに文書を作って、答える・戻すを確かめる。
- tests/human/check/test_value.py — 価値のカードの反映(src/human/check/value.py)の単体テスト。入口が渡す口(studio)は偽物。value:auto は記録だけ(案件の口を呼ばない)。
- tests/human/check/test_voice.py — 「確かめる」の誰の声のカード(src/human/check/voice.py)の単体テスト: 答えの形・選択肢と予想・文書の行への反映(commit why check:voice)と Z・
- tests/human/friend/test_friend_feedback.py — 友人の「要らない」を PC 側で片付ける(src/human/friend/friend_feedback.py)の単体テスト。ごみ箱は本物の cleanup.Cleanup(一時フォルダ)。
- tests/human/friend/test_intake.py — 友人からの依頼の受付(src/human/friend/intake.py)の単体テスト。まとめて実行・ffprobe・yt-dlp は偽物。
- tests/human/friend/test_returns.py — src/human/friend/returns.py(友人の送り返しの受け取り。F1 の F2)のテスト。リポジトリ直下で:
- tests/human/proof/test_alt.py — 2つ目のエンジンとの食い違いに候補を出す機能のテスト。
- tests/human/proof/test_autodiar.py — 評価用の文書の文字起こしのあとの話者の自動判別(human/proof/speakers の autodiar_*・eval/drill/evalbatch の後追い)のテスト。
- tests/human/proof/test_commit.py — 文書を書く唯一の口 human/proof/store.commit のテスト(動きは write_doc と同じ・why をログに残す)。
- tests/human/proof/test_doc_jobs.py — human/proof/doc_jobs のテスト(serve なしで読める・人の行の引き継ぎ)。
- tests/human/proof/test_doc_placement.py — 文書の置き場所(ytt/docloc の索引)を人の側の部品が使うことのテスト。
- tests/human/proof/test_layers.py — 文書を「機械の層 + 人の層」から組み立てる関数(human/proof/layers)のテスト。
- tests/human/proof/test_machpick.py — 3 択の口(human/proof/machpick と layers.mach_changes・pick)のテスト。
- tests/human/proof/test_opt_h1_fixes.py — ③ 校正の小物(名前の比べ方・学習の統計・名簿・覚え直しの行・再認識の単語)のテスト。serve なしで読める。
- tests/human/proof/test_primary_ops.py — 層が正(機械の層 + 人の層)のときの機械の操作のテスト。
- tests/human/proof/test_proof_api.py — 校正まわりの API の確かめ(編集の画面の裏の API だけで確かめる)。
- tests/human/proof/test_retime.py — 行の時刻を単語の時刻に合わせる候補(T1 の簡易版)のテスト(計算は pipeline/transcribe/retime.py・文書を読む包みは human/proof/retime.py)。
- tests/human/proof/test_smooth.py — 話者の細切れをならす(smooth_labels・smooth_speakers・apply_diarization(smooth)・設定 diarSmooth)のテスト。
- tests/human/proof/test_voices.py — 話者の声を覚える(A-3)のサーバー側のテスト。
- tests/human/review/test_studio.py — human/review/store.py の単体テスト(ネットワーク・ffmpeg 不要)。 実行(リポジトリ直下): py -3.12 -m unittest tests/human/review/test_studio.py
