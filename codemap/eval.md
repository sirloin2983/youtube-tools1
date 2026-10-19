# コードの地図: ⑤ eval(検証)

自動で作った物(`python dev/code_map.py`)。手で直さない。目次は [index.md](index.md)。`file:line` の行の番号は作った時点の物。

## src/eval/

- **__init__.py** (2 行) — ⑤ テストと検証。どの層も import してよい(逆は不可)

## src/eval/check/

- **__init__.py** (2 行) — ⑤ 確かめるの待ち行列(V1。カードの出どころ sources・並び lineup・目標との対応 goals・組み立て deck。notes:docs/design/v1-check-build.md)
- **goals.py** (64 行) — 「確かめる」のカードの種類 → 入口の条件(src/eval/drill/accuracy.py の GOALS)の対応と、答えの数え方(V1 の V0。notes:docs/design/v1-check-build.md の 2-3)。
  - 名前: `goal_of` :22・`extra_counter` :27・`extra_from` :44・`by_kind` :52・`view` :58

## src/eval/drill/

- **__init__.py** (2 行) — ⑤ 評価ドリル・評価用フォルダ・精度のカード・A/B・精度の自動測定
- **accuracy.py** (622 行) — 精度の自動測定(マスタープラン Q3)。
  - 名前: `class ToolError` :87・`summarize_asr` :106・`summarize_marks` :121・`summarize_speakers` :140・`summarize_cut` :164・`summarize_alt` :177・`summarize_fill` :192・`summarize_timing` :207・`count_daily` :241・`goals_of` :275・`in_window` :307・`day_of` :314・ほか 1
- **drill.py** (440 行) — 「編集」のサーバーの部品: 評価ドリルと定点の「あと何分」(マスタープラン Q4)。
  - 名前: `drill_reviewed_sec` :47・`drill_stream_key` :54・`drill_doc_summary` :73・`drill_docs` :126・`drill_status` :159・`drill_next` :202・`drill_reviewed` :268・`drill_unreviewed` :299・`drill_candidates_for` :376・`drill_candidates` :415
- **evalbatch.py** (765 行) — 「編集」のサーバーの部品: 評価用の動画を、手が空いたとき少しずつまとめて文字起こしする(マスタープラン Q4(b))。
  - 名前: `eb_path` :78・`eb_lock_path` :83・`eb_key` :87・`eb_read` :99・`eval_batch_status` :147・`eb_require_ready` :174・`eval_batch_start` :182・`eval_batch_stop` :197・`eb_scan` :224・`eb_candidates` :242・`eb_diar_candidates` :265・`eb_request` :323・ほか 7
- **metrics.py** (301 行) — ⑤ テストと検証の層 eval/drill: 認識精度の測定(文字誤り率 CER。人が校正済みにした行を正解に、機械の出力 original と比べる)・
  - 名前: `nosub_stats` :28・`is_overlap_group` :38・`overlap_orders` :55・`overlap_best_counts` :74・`norm_cer` :99・`lev_counts` :105・`metric_terms` :148・`new_acc` :161・`acc_line` :166・`acc_merge` :190・`acc_finish` :201・`scored_groups` :210・ほか 3

## src/eval/fake/

- **__init__.py** (3 行) — ④ 疑似モード(偽の認識エンジン fake_asr・偽のワーカー fake_worker)。各段の登録の口から差し込む。本体に if fake を置かない
- **fake_asr.py** (187 行) — 疑似の文字起こし(環境変数 TRANSCRIBE_BACKEND=fake のテスト・画面の通し確認用)。
  - 名前: `fake_wait` :19・`transcribe_fake` :24・`fake_range_lines` :66・`diarize_fake` :87・`embed_fake` :101・`class FakeBackend` :118
- **fake_worker.py** (127 行) — 認識ワーカーの中の疑似(環境変数 TRANSCRIBE_BACKEND=worker-fake のテスト用。認識ワーカーは pipeline/transcribe/worker.py)。
  - 名前: `install` :24・`fake_sense_voice` :92・`fake_llama_text` :111

## src/eval/tools/

- **__init__.py** (2 行) — ⑤ 物差し(測る道具 eval_*・clipfit と共通の部品 _evalcommon)
- **_evalcommon.py** (343 行) — 測る道具(src/eval/tools の eval_*.py・clipfit.py)の共通の部品。道具は src の中で `py -3.12 -m eval.tools.<名前>` で動かす(入口の accuracy.py も同じ)。
  - 名前: `add_period_args` :36・`split_ids` :45・`label_name` :50・`data_env` :55・`locate` :60・`day_ms` :67・`period` :78・`in_period` :83・`period_label` :92・`iter_docs` :100・`read_answers` :109・`short_pct` :127・ほか 14
- **clipfit.py** (342 行) — 自動の区間が友人の区間にどれだけ合うかの物差し(LD-2a。notes:plan/done/ld2-clip-length.md の L-2)。⑤ eval_marks が表示に使い、単独でも動く。
  - 名前: `load_material` :35・`rebuild` :51・`picks` :72・`fit` :81・`summarize` :93・`default_variants` :103・`friend_material` :111・`evaluate` :123・`edge_speech` :184・`scene_only` :242・`grid` :257・`print_fit` :289・ほか 1
- **eval_alt.py** (534 行) — 「2つ目のエンジンとの食い違いの候補」(行に出る札「別」)が、校正を本当に速くしているかを数字で見る道具(候補の当たり率)。
  - 名前: `locate` :68・`name_checker` :73・`read_alt` :80・`read_feedback` :88・`read_answers` :99・`clean_rows` :122・`fold_text` :129・`class Group` :139・`map_span` :164・`judge_candidate` :182・`match_answer` :215・`judge_doc` :225・ほか 7
- **eval_asr.py** (989 行) — 文字起こしの精度を、校正済みの文字起こし(評価用)で測る道具(文字起こしの改善の計画 段0-2。notes:plan/line-b-transcription.md(付録))。
  - 名前: `real_data_dir` :100・`load_docs` :105・`has_proofed` :120・`whole_video` :124・`resolve_source` :135・`doc_time` :139・`select_docs` :153・`pick_reviewed` :176・`runs_of` :186・`draft_run` :191・`draft_of` :198・`run_label` :211・ほか 40
- **eval_cloud.py** (509 行) — クラウドの文字起こし(OpenAI・ElevenLabs)に評価用の音声を送り、手元のエンジンと同じ物差し(src/eval/tools/eval_asr.py の採点)で測る道具
  - 名前: `request_fields` :77・`timing_kind` :91・`multipart` :98・`http_json` :110・`auth_headers` :129・`scrub` :133・`send_audio` :141・`delete_remote` :154・`rows_from_words` :178・`rows_from` :210・`cache_dir` :225・`audio_span` :229・ほか 17
- **eval_cut.py** (405 行) — カットのたたき台(機械の最初の結果)と、人の最終の差を測る道具(マスタープラン Q3・I-3a: 無音のしきい値・行の後の余白の既定を見直す材料)。
  - 名前: `ms_of` :57・`read_edit` :62・`read_draft` :92・`pack_final` :108・`find_pack` :133・`clean` :163・`compare` :174・`class Agg` :216・`fmt_val` :256・`sig_of` :260・`evaluate` :266・`print_agg` :334・ほか 3
- **eval_fill.py** (393 行) — 認識のあとの後処理(src/pipeline/transcribe/fill.py・llm.py。A 文字の少ない行を別の読みで埋める・D 名簿の呼び名の 1 字違いを直す・
  - 名前: `fold` :65・`edit_distance` :70・`rows_of` :77・`overlap` :89・`first_run` :93・`answer_of` :102・`answer_before` :106・`answer_time` :112・`checked_around` :117・`raw_text` :126・`match_seg` :132・`closer_of` :146・ほか 14
- **eval_marks.py** (1212 行) — 盛り上がりの検出(スタジオの自動マーク)の当たり具合を、人の判定の記録で測る道具(線 C の土台。notes:plan/line-bc-master-plan.md の Q3・I-4a)。
  - 名前: `read_jsonl` :91・`locate` :110・`studio_videos` :116・`load_machine` :125・`human_marks` :138・`archive_reader` :149・`run_records` :160・`load_runs` :165・`ts_ms` :185・`dist` :192・`same` :197・`pair` :201・ほか 32
- **eval_speakers.py** (1104 行) — 話者の判別(と覚えた声の照合)の当たり具合を、人が直した最終で測る道具(線 B の話者の評価。notes:plan/line-bc-master-plan.md の Q3・I-2a)。
  - 名前: `read_diar` :97・`norm_name` :106・`hungarian_max` :110・`best_mapping` :161・`time_edited_flags` :175・`is_other_row` :196・`in_period` :201・`confirm_map` :205・`human_rows` :236・`overlap_rows` :277・`class Overlap` :302・`new_counts` :325・ほか 31
- **eval_timing.py** (445 行) — 行の時刻(字幕の区間)を、行の時刻の原則(notes:docs/spec/subtitles.md)の数字で測る道具(notes:plan/done/line-b-row-timing.md の 7-4)。
  - 名前: `current_variant` :69・`letters` :77・`text_rows` :82・`text_match` :97・`best_overlap` :103・`measure_rows` :113・`boundary_agreement` :155・`boundary_sum` :179・`summarize` :187・`post_label` :197・`engine_label` :217・`doc_record` :223・ほか 12

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
- src/eval/tools/tests/test_evalcommon.py — src/eval/tools/_evalcommon.py(測る道具の共通の部品)の、引数・保存・音声の出どころのテスト。リポジトリ直下で:
