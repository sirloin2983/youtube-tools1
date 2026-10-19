# コードの地図: ⑤ eval(検証)

自動で作った物(`python dev/code_map.py`)。手で直さない。目次は [index.md](index.md)。`file:line` の行の番号は作った時点の物。

## src/eval/

- **__init__.py** (2 行) — ⑤ テストと検証。どの層も import してよい(逆は不可)

## src/eval/check/

- **__init__.py** (2 行) — ⑤ 確かめるの待ち行列(V1。カードの出どころ sources・並び lineup・目標との対応 goals・組み立て deck。notes:docs/design/v1-check-build.md)
- **goals.py** (72 行) — 「確かめる」のカードの種類 → 入口の条件(src/eval/drill/accuracy.py の GOALS)の対応と、答えの数え方(V1 の V0。notes:docs/design/v1-check-build.md の 2-3)。
  - 名前: `register` :22・`goal_of` :30・`extra_counter` :35・`extra_from` :52・`by_kind` :60・`view` :66

## src/eval/drill/

- **__init__.py** (2 行) — ⑤ 評価ドリル・評価用フォルダ・精度のカード・A/B・精度の自動測定
- **accuracy.py** (633 行) — 精度の自動測定(マスタープラン Q3)。
  - 名前: `class ToolError` :87・`summarize_asr` :106・`summarize_marks` :121・`summarize_speakers` :140・`summarize_cut` :164・`summarize_alt` :177・`summarize_fill` :192・`summarize_timing` :207・`summarize_generic` :229・`count_daily` :252・`goals_of` :286・`in_window` :318・ほか 2
- **drill.py** (451 行) — 「編集」のサーバーの部品: 評価ドリルと定点の「あと何分」(マスタープラン Q4)。
  - 名前: `drill_reviewed_sec` :50・`drill_stream_key` :57・`drill_doc_summary` :76・`drill_docs` :129・`drill_status` :162・`drill_next` :205・`drill_reviewed` :271・`drill_unreviewed` :302・`drill_candidates_for` :387・`drill_candidates` :426
- **evalbatch.py** (806 行) — 「編集」のサーバーの部品: 評価用の動画を、手が空いたとき少しずつまとめて文字起こしする(マスタープラン Q4(b))。
  - 名前: `eb_path` :112・`eb_lock_path` :117・`eb_key` :121・`eb_read` :133・`eval_batch_status` :181・`eb_require_ready` :208・`eval_batch_start` :216・`eval_batch_stop` :231・`eb_scan` :258・`eb_candidates` :276・`eb_diar_candidates` :299・`eb_request` :357・ほか 8
- **metrics.py** (290 行) — ⑤ テストと検証の層 eval/drill: 認識精度の測定(文字誤り率 CER。人が校正済みにした行を正解に、機械の出力 original と比べる)・
  - 名前: `nosub_stats` :28・`is_overlap_group` :38・`overlap_orders` :55・`overlap_best_counts` :74・`norm_cer` :99・`lev_counts` :105・`metric_terms` :148・`new_acc` :161・`acc_line` :166・`acc_merge` :190・`acc_finish` :201・`doc_metrics` :210・ほか 2

## src/eval/fake/

- **__init__.py** (3 行) — ④ 疑似モード(偽のエンジン・偽の YouTube API・偽の録画元)。各段の登録の口から差し込む。本体に if fake を置かない
- **fake_asr.py** (187 行) — 疑似の文字起こし(環境変数 TRANSCRIBE_BACKEND=fake のテスト・画面の通し確認用)。
  - 名前: `fake_wait` :19・`transcribe_fake` :24・`fake_range_lines` :66・`diarize_fake` :87・`embed_fake` :101・`class FakeBackend` :118
- **fake_worker.py** (127 行) — 認識ワーカーの中の疑似(環境変数 TRANSCRIBE_BACKEND=worker-fake のテスト用。認識ワーカーは pipeline/transcribe/worker.py)。
  - 名前: `install` :24・`fake_sense_voice` :92・`fake_llama_text` :111

## src/eval/tools/

- **__init__.py** (2 行) — ⑤ 物差し(今の src/eval/tools/eval_*・_evalcommon・demo_env)
- **_evalcommon.py** (291 行) — dev/ の測る道具(eval_asr.py・eval_speakers.py・eval_timing.py・eval_cut.py・eval_alt.py・eval_marks.py)の共通の部品。
  - 名前: `add_period_args` :36・`split_ids` :45・`label_name` :50・`data_env` :55・`locate` :60・`day_ms` :67・`period` :78・`in_period` :83・`period_label` :92・`rate` :101・`pct` :105・`dist` :110・ほか 10
- **clipfit.py** (357 行) — 自動の区間が友人の区間にどれだけ合うかの物差し(LD-2a。notes:plan/done/ld2-clip-length.md の L-2)。⑤ eval_marks が表示に使い、単独でも動く。
  - 名前: `load_material` :42・`rebuild` :66・`picks` :87・`fit` :96・`summarize` :108・`default_variants` :118・`friend_material` :126・`evaluate` :138・`edge_speech` :199・`scene_only` :257・`grid` :272・`print_fit` :304・ほか 1
- **eval_alt.py** (564 行) — 「2つ目のエンジンとの食い違いの候補」(行に出る札「別」)が、校正を本当に速くしているかを数字で見る道具(候補の当たり率)。
  - 名前: `locate` :75・`name_checker` :80・`read_alt` :87・`read_feedback` :95・`read_answers` :106・`pct` :135・`num` :140・`clean_rows` :146・`fold_text` :153・`class Group` :163・`map_span` :188・`judge_candidate` :206・ほか 9
- **eval_asr.py** (1076 行) — 文字起こしの精度を、校正済みの文字起こし(評価用)で測る道具(文字起こしの改善の計画 段0-2。notes:plan/line-b-transcription.md(付録))。
  - 名前: `real_data_dir` :105・`load_docs` :110・`has_proofed` :128・`whole_video` :132・`reviewed_sec` :138・`resolve_source` :159・`doc_time` :163・`select_docs` :177・`resolve_reviewed` :200・`pick_reviewed` :208・`runs_of` :226・`draft_run` :231・ほか 43
- **eval_cloud.py** (514 行) — クラウドの文字起こし(OpenAI・ElevenLabs)に評価用の音声を送り、手元のエンジンと同じ物差し(src/eval/tools/eval_asr.py の採点)で測る道具
  - 名前: `request_fields` :82・`timing_kind` :96・`multipart` :103・`http_json` :115・`auth_headers` :134・`scrub` :138・`send_audio` :146・`delete_remote` :159・`rows_from_words` :183・`rows_from` :215・`cache_dir` :230・`audio_span` :234・ほか 17
- **eval_cut.py** (416 行) — カットのたたき台(機械の最初の結果)と、人の最終の差を測る道具(マスタープラン Q3・I-3a: 無音のしきい値・行の後の余白の既定を見直す材料)。
  - 名前: `num` :59・`ms_of` :63・`read_edit` :68・`read_draft` :98・`pack_final` :114・`find_pack` :139・`pct` :163・`clean` :174・`compare` :185・`class Agg` :227・`fmt_val` :267・`sig_of` :271・ほか 5
- **eval_fill.py** (416 行) — 認識のあとの後処理(src/pipeline/transcribe/fill.py・llm.py。A 文字の少ない行を別の読みで埋める・D 名簿の呼び名の 1 字違いを直す・
  - 名前: `fold` :70・`edit_distance` :75・`rows_of` :82・`overlap` :94・`first_run` :98・`read_answers` :107・`answer_of` :123・`answer_before` :127・`answer_time` :133・`checked_around` :138・`raw_text` :147・`match_seg` :153・ほか 15
- **eval_marks.py** (1246 行) — 盛り上がりの検出(スタジオの自動マーク)の当たり具合を、人の判定の記録で測る道具(線 C の土台。notes:plan/line-bc-master-plan.md の Q3・I-4a)。
  - 名前: `read_jsonl` :94・`locate` :113・`studio_videos` :119・`load_feedback` :124・`archive_reader` :137・`load_archive` :148・`run_records` :164・`load_runs` :169・`ts_ms` :191・`num` :198・`dist` :202・`same` :207・ほか 33
- **eval_speakers.py** (1138 行) — 話者の判別(と覚えた声の照合)の当たり具合を、人が直した最終で測る道具(線 B の話者の評価。notes:plan/line-bc-master-plan.md の Q3・I-2a)。
  - 名前: `read_diar` :101・`num` :110・`norm_name` :114・`hungarian_max` :118・`best_mapping` :169・`time_edited_flags` :183・`is_other_row` :204・`in_period` :209・`confirm_map` :213・`human_rows` :244・`overlap_rows` :285・`class Overlap` :310・ほか 34
- **eval_timing.py** (510 行) — 行の時刻(字幕の区間)を、行の時刻の原則(notes:docs/spec/subtitles.md)の数字で測る道具(notes:plan/done/line-b-row-timing.md の 7-4)。
  - 名前: `current_variant` :79・`letters` :87・`text_rows` :92・`text_match` :107・`best_overlap` :113・`measure_rows` :123・`boundary_agreement` :165・`boundary_sum` :189・`summarize` :197・`post_label` :207・`engine_label` :227・`doc_record` :233・ほか 14

## テスト

- src/eval/drill/tests/test_accuracy.py — 精度の自動測定(src/eval/drill/accuracy.py)の単体テスト。一時フォルダと、src/eval/tools/eval_*.py の代わりの偽の道具(小さな Python スクリプト)だけを使う。
- src/eval/tools/tests/test_clipfit.py — src/eval/tools/clipfit.py(自動の区間が友人の区間にどれだけ合うかの物差し)のテスト。リポジトリ直下で:
- src/eval/tools/tests/test_eval_alt.py — src/eval/tools/eval_alt.py(2つ目のエンジンとの食い違いの候補の当たり率を測る道具)のテスト。リポジトリ直下で:
- src/eval/tools/tests/test_eval_asr.py — src/eval/tools/eval_asr.py(文字起こしの精度を測る道具)のテスト。リポジトリ直下で:
- src/eval/tools/tests/test_eval_cloud.py — src/eval/tools/eval_cloud.py(クラウドの文字起こしとの比較)のテスト。リポジトリ直下で:
- src/eval/tools/tests/test_eval_cut.py — src/eval/tools/eval_cut.py(カットのたたき台と人の最終の差を測る道具)のテスト。リポジトリ直下で:
- src/eval/tools/tests/test_eval_fill.py — src/eval/tools/eval_fill.py(認識のあとの後処理の様子見の物差し)のテスト。リポジトリ直下で:
- src/eval/tools/tests/test_eval_marks.py — src/eval/tools/eval_marks.py(盛り上がりの検出を、人の判定の記録で測る道具。線 C の土台)のテスト。リポジトリ直下で:
- src/eval/tools/tests/test_eval_speakers.py — src/eval/tools/eval_speakers.py(話者の判別・声の照合を、人が直した最終で測る道具)のテスト。リポジトリ直下で:
- src/eval/tools/tests/test_eval_timing.py — src/eval/tools/eval_timing.py(行の時刻を原則の数字で測る道具)のテスト。リポジトリ直下で:
- src/eval/tools/tests/test_evalcommon.py — src/eval/tools/_evalcommon.py(測る道具の共通の部品)の、引数・保存・音声の出どころ・JSON の読み込みのテスト。リポジトリ直下で:
