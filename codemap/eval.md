# コードの地図: ⑤ eval(検証)

自動で作った物(`python dev/code_map.py`)。手で直さない。目次は [index.md](index.md)。`file:line` の行の番号は作った時点の物。

## src/eval/

- **__init__.py** (2 行) — ⑤ テストと検証。どの層も import してよい(逆は不可)

## src/eval/check/

- **__init__.py** (2 行) — ⑤ 確かめるの待ち行列(V1。カードの出どころ sources・並び lineup・目標との対応 goals・組み立て deck。notes:docs/design/v1-check-build.md)
- **goals.py** (69 行) — 「確かめる」のカードの種類 → 入口の条件(src/eval/drill/accuracy.py の GOALS)の対応と、答えの数え方(V1 の V0。notes:docs/design/v1-check-build.md の 2-3)。
  - 名前: `goal_of` :22・`extra_counter` :27・`extra_from` :49・`by_kind` :57・`view` :63

## src/eval/drill/

- **__init__.py** (2 行) — ⑤ 評価ドリル・評価用フォルダ・精度のカード・A/B・精度の自動測定
- **accuracy.py** (637 行) — 精度の自動測定(マスタープラン Q3)。
  - 名前: `class ToolError` :88・`summarize_asr` :107・`summarize_marks` :122・`summarize_speakers` :141・`summarize_cut` :165・`summarize_alt` :178・`summarize_fill` :193・`summarize_timing` :208・`count_daily` :242・`goals_of` :276・`in_window` :308・`day_of` :315・ほか 1
- **drill.py** (383 行) — 「編集」のサーバーの部品: 評価ドリルと定点の「あと何分」(マスタープラン Q4)。
  - 名前: `drill_reviewed_sec` :43・`drill_stream_key` :50・`drill_doc_summary` :69・`drill_docs` :122・`drill_status` :155・`drill_reviewed` :211・`drill_unreviewed` :242・`drill_candidates_for` :319・`drill_candidates` :358
- **evalbatch.py** (767 行) — 「編集」のサーバーの部品: 評価用の動画を、手が空いたとき少しずつまとめて文字起こしする(マスタープラン Q4(b))。
  - 名前: `eb_path` :80・`eb_lock_path` :85・`eb_key` :89・`eb_read` :101・`eval_batch_status` :149・`eb_require_ready` :176・`eval_batch_start` :184・`eval_batch_stop` :199・`eb_scan` :226・`eb_candidates` :244・`eb_diar_candidates` :267・`eb_request` :325・ほか 7
- **metrics.py** (300 行) — ⑤ テストと検証の層 eval/drill: 認識精度の測定(文字誤り率 CER。人が校正済みにした行を正解に、機械の出力 original と比べる)・
  - 名前: `nosub_stats` :27・`is_overlap_group` :37・`overlap_orders` :54・`overlap_best_counts` :73・`norm_cer` :98・`lev_counts` :104・`metric_terms` :147・`new_acc` :160・`acc_line` :165・`acc_merge` :189・`acc_finish` :200・`scored_groups` :209・ほか 3

## src/eval/fake/

- **__init__.py** (2 行) — ④ 疑似モード(偽の認識エンジン fake_asr・偽のワーカー fake_worker)。各段の登録の口から差し込む。本体に if fake を置かない
- **fake_asr.py** (191 行) — 疑似の文字起こし(環境変数 TRANSCRIBE_BACKEND=fake のテスト・画面の通し確認用)。
  - 名前: `fake_wait` :19・`transcribe_fake` :24・`fake_range_lines` :66・`diarize_fake` :87・`embed_fake` :101・`class FakeBackend` :118
- **fake_worker.py** (127 行) — 認識ワーカーの中の疑似(環境変数 TRANSCRIBE_BACKEND=worker-fake のテスト用。認識ワーカーは pipeline/transcribe/worker.py)。
  - 名前: `install` :24・`fake_sense_voice` :92・`fake_llama_text` :111

## src/eval/tools/

- **__init__.py** (2 行) — ⑤ 物差し(測る道具 eval_*・clipfit と共通の部品 _evalcommon)
- **_evalcommon.py** (342 行) — 測る道具(src/eval/tools の eval_*.py・clipfit.py)の共通の部品。道具は src の中で `py -3.12 -m eval.tools.<名前>` で動かす(入口の accuracy.py も同じ)。
  - 名前: `add_period_args` :36・`split_ids` :45・`label_name` :50・`data_env` :55・`locate` :60・`day_ms` :67・`period` :78・`in_period` :83・`period_label` :92・`iter_docs` :100・`read_answers` :109・`short_pct` :127・ほか 14
- **clipfit.py** (347 行) — 自動の区間が友人の区間にどれだけ合うかの物差し(LD-2a。notes:plan/done/ld2-clip-length.md の L-2)。⑤ eval_marks が表示に使い、単独でも動く。
  - 名前: `load_material` :35・`rebuild` :51・`picks` :75・`fit` :86・`summarize` :98・`default_variants` :108・`friend_material` :116・`evaluate` :128・`edge_speech` :189・`scene_only` :247・`grid` :262・`print_fit` :294・ほか 1
- **eval_alt.py** (533 行) — 「2つ目のエンジンとの食い違いの候補」(行に出る札「別」)が、校正を本当に速くしているかを数字で見る道具(候補の当たり率)。
  - 名前: `locate` :67・`name_checker` :72・`read_alt` :79・`read_feedback` :87・`read_answers` :98・`clean_rows` :121・`fold_text` :128・`class Group` :138・`map_span` :163・`judge_candidate` :181・`match_answer` :214・`judge_doc` :224・ほか 7
- **eval_asr.py** (1003 行) — 文字起こしの精度を、校正済みの文字起こし(評価用)で測る道具(文字起こしの改善の計画 段0-2。notes:plan/line-b-transcription.md(付録))。
  - 名前: `real_data_dir` :102・`load_docs` :107・`has_proofed` :122・`whole_video` :126・`resolve_source` :137・`doc_time` :141・`select_docs` :155・`pick_reviewed` :178・`runs_of` :188・`draft_run` :193・`draft_of` :200・`run_label` :213・ほか 40
- **eval_cloud.py** (509 行) — クラウドの文字起こし(OpenAI・ElevenLabs)に評価用の音声を送り、手元のエンジンと同じ物差し(src/eval/tools/eval_asr.py の採点)で測る道具
  - 名前: `request_fields` :77・`timing_kind` :91・`multipart` :98・`http_json` :110・`auth_headers` :129・`scrub` :133・`send_audio` :141・`delete_remote` :154・`rows_from_words` :178・`rows_from` :210・`cache_dir` :225・`audio_span` :229・ほか 17
- **eval_cut.py** (404 行) — カットのたたき台(機械の最初の結果)と、人の最終の差を測る道具(マスタープラン Q3・I-3a: 無音のしきい値・行の後の余白の既定を見直す材料)。
  - 名前: `ms_of` :56・`read_edit` :61・`read_draft` :91・`pack_final` :107・`find_pack` :132・`clean` :162・`compare` :173・`class Agg` :215・`fmt_val` :255・`sig_of` :259・`evaluate` :265・`print_agg` :333・ほか 3
- **eval_fill.py** (393 行) — 認識のあとの後処理(src/pipeline/transcribe/fill.py・llm.py。A 文字の少ない行を別の読みで埋める・D 名簿の呼び名の 1 字違いを直す・
  - 名前: `fold` :65・`edit_distance` :70・`rows_of` :77・`overlap` :89・`first_run` :93・`answer_of` :102・`answer_before` :106・`answer_time` :112・`checked_around` :117・`raw_text` :126・`match_seg` :132・`closer_of` :146・ほか 14
- **eval_marks.py** (1211 行) — 盛り上がりの検出(スタジオの自動マーク)の当たり具合を、人の判定の記録で測る道具(線 C の土台。notes:plan/line-bc-master-plan.md の Q3・I-4a)。
  - 名前: `read_jsonl` :90・`locate` :109・`studio_videos` :115・`load_machine` :124・`human_marks` :137・`archive_reader` :148・`run_records` :159・`load_runs` :164・`ts_ms` :184・`dist` :191・`same` :196・`pair` :200・ほか 32
- **eval_speakers.py** (1103 行) — 話者の判別(と覚えた声の照合)の当たり具合を、人が直した最終で測る道具(線 B の話者の評価。notes:plan/line-bc-master-plan.md の Q3・I-2a)。
  - 名前: `read_diar` :96・`norm_name` :105・`hungarian_max` :109・`best_mapping` :160・`time_edited_flags` :174・`is_other_row` :195・`in_period` :200・`confirm_map` :204・`human_rows` :235・`overlap_rows` :276・`class Overlap` :301・`new_counts` :324・ほか 31
- **eval_timing.py** (446 行) — 行の時刻(字幕の区間)を、行の時刻の原則(notes:docs/spec/subtitles.md)の数字で測る道具(notes:plan/done/line-b-row-timing.md の 7-4)。
  - 名前: `current_variant` :68・`letters` :76・`text_rows` :81・`text_match` :96・`best_overlap` :102・`measure_rows` :112・`boundary_agreement` :154・`boundary_sum` :178・`summarize` :186・`post_label` :196・`engine_label` :216・`doc_record` :224・ほか 12

## テスト

- tests/eval/drill/test_accuracy.py — 精度の自動測定(src/eval/drill/accuracy.py)の単体テスト。一時フォルダと、src/eval/tools/eval_*.py の代わりの偽の道具(小さな Python スクリプト)だけを使う。
- tests/eval/drill/test_drill.py — 評価ドリルと定点の「あと何分」(eval/drill/drill.py。動画 1 本ずつ・編集の画面で全部聞いて直す・文書の印 evalReviewed)のテスト。
- tests/eval/drill/test_evalbatch.py — 評価用の動画の「手が空いたとき少しずつまとめて文字起こし」(eval/drill/evalbatch.py)のテスト。
- tests/eval/drill/test_metrics.py — 校正済み・CER測定・英字フラグ・A/B比較・校正済みの書き出し)のテスト。
- tests/eval/drill/test_nosub_metrics.py — 「字幕に出さない」行(noSub)と、同時にしゃべっている所(重なり)の数え方・学習のテスト(数え方は eval/drill/metrics.py・noSub の外し方と学習は human/proof/learn.py)。
- tests/eval/tools/test_clipfit.py — src/eval/tools/clipfit.py(自動の区間が友人の区間にどれだけ合うかの物差し)のテスト。リポジトリ直下で:
- tests/eval/tools/test_eval_alt.py — src/eval/tools/eval_alt.py(2つ目のエンジンとの食い違いの候補の当たり率を測る道具)のテスト。リポジトリ直下で:
- tests/eval/tools/test_eval_asr.py — src/eval/tools/eval_asr.py(文字起こしの精度を測る道具)のテスト。リポジトリ直下で:
- tests/eval/tools/test_eval_cloud.py — src/eval/tools/eval_cloud.py(クラウドの文字起こしとの比較)のテスト。リポジトリ直下で:
- tests/eval/tools/test_eval_cut.py — src/eval/tools/eval_cut.py(カットのたたき台と人の最終の差を測る道具)のテスト。リポジトリ直下で:
- tests/eval/tools/test_eval_fill.py — src/eval/tools/eval_fill.py(認識のあとの後処理の様子見の物差し)のテスト。リポジトリ直下で:
- tests/eval/tools/test_eval_marks.py — src/eval/tools/eval_marks.py(盛り上がりの検出を、人の判定の記録で測る道具。線 C の土台)のテスト。リポジトリ直下で:
- tests/eval/tools/test_eval_speakers.py — src/eval/tools/eval_speakers.py(話者の判別・声の照合を、人が直した最終で測る道具)のテスト。リポジトリ直下で:
- tests/eval/tools/test_eval_timing.py — src/eval/tools/eval_timing.py(行の時刻を原則の数字で測る道具)のテスト。リポジトリ直下で:
- tests/eval/tools/test_evalcommon.py — src/eval/tools/_evalcommon.py(測る道具の共通の部品)の、引数・保存・音声の出どころのテスト。リポジトリ直下で:
