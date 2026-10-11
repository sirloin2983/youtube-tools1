# RV 下調べ 6: テスト

状態(2026-10-11): 読むだけの下調べ(Sonnet が静的に数えた。テストは流していない。層の判定は import からの推定 = 移す前に 1 本ずつ目で見る)。

## 1. 量
- 約 198 ファイル・`def test_` 約 3,300・約 73,500 行。unittest は全体で約 3,400 件・フォルダごとに 1 プロセスで約 16 分(WORKLOG 10-11)。
- 大きいフォルダ: `src/editor/tests` 654 件・12,649 行 / `src/home/tests` 273 件・11,916 行 / `src/flow/tests` 390 件・8,965 行 / `src/eval/tools/tests` 336 件・6,561 行。

## 2. 層とずれたテスト(いちばん大きい塊は `src/editor/tests`)
`src/editor/` に残るコードは serve・ed_state・ed_media・ed_thumb・thumb_ideas だけなのに、テストは `import serve as S` で層の部品を読む形のまま置き去り。

| テスト | 実際の相手 | 移し先 |
| --- | --- | --- |
| test_fill・test_llm・test_roster・test_records・test_retime・test_whispercpp・test_qwen3・test_worker | `pipeline/transcribe` | `src/pipeline/transcribe/tests/`(`test_fill_llm.py`・`test_diarize.py` と統合) |
| test_resolve_export | `pipeline/pack` | `src/pipeline/pack/tests/` |
| test_alt・test_ytcap・test_ovdraft・test_smooth・test_voices・test_proof_api・test_normalize30 | `human/proof` | `src/human/proof/tests/` |
| test_drill・test_evalbatch・test_autodiar・test_metrics・test_nosub_metrics | `eval/drill` | `src/eval/drill/tests/`(eval の整理しだいで消す) |
| test_edit(65)・test_backend(44。1,071 行の共通の下ごしらえも兼ねる) | 混ざり | 割ってから各層へ |
| fake_ytdlp・fake_whisper_cli・fake_llama_server | 複数の層が使う偽物 | `src/eval/fake/` |
| e2e_edit_common | 案件の画面の e2e が読む補助 | `src/app/tests/` |
| home の test_live_archive_api・test_live_detect_api・test_live_tx_prefs・test_adopt_defaults・fake_excite_worker | flow・pipeline | 中身の重なりを見て flow へ寄せる / 口の確かめだけ残す |
| home の test_check_api | app | `src/app/tests/`(test_check_page と同居) |
| studio の test_api(61)・test_robustness(44)ほか | human/review・human/find・pipeline/export | 各層へ |

## 3. 重複
- 同じ関数を何か所でも: 採用 adopt(flow/test_run・human/review/test_studio・pipeline/analyze/test_adopt の 3 か所)・マークの検査(ytt/test_marks と test_studio)・`test_first_export_makes_case`(test_studiobook と test_studio)・docmove と markmove の同じ 7 件・cases_page と check_page のページ共通 6 件・`defaults=` の 3 か所・設定のスキーマ 3 か所(home・studio・editor → ytt へ)・「重い部品を読まない」検査が pipeline/transcribe に 3 本(→ 層の検査へ)。
- 口(HTTP)と中身の重なりの疑い: home の test_autorun(2,201 行・103 件)と flow の test_run・test_runqueue、home の test_live(826 行)と flow の test_livesession・test_live_*。
- 小物の写し: `free_port` 7 か所・`make_video` 6・HTTP の小さなクライアント 20+・`wait_for` 10+・`sys.path.insert` 174 ファイル・`YTT_DATA_DIR` の設定 169 ファイル → 共通の testkit(例 `src/ytt/testkit.py`)1 つに。
- 一時フォルダへ写す一覧: 共通のコードは `layout.copy_shared_code` に 1 本化済み(良い)。ただしツールごとの手書きの一覧が 5 か所(test_backend の start_server・test_proof_api・dev/tests/e2e_pipeline・test_launch・e2e_edit_common)→ 「直下を全部写す」形にそろえれば写し忘れが起きない。
- `src/editor/tests/test_metrics.py` の末尾が 10 本以上を `import *` で集める(流すと編集の全部が走る・個別に流すと二重)→ 層へ移したら要らない。

## 4. e2e の一式(`dev/run_e2e.py` の SUITE)
- **19 本**(AGENTS の「18 本」は e2e_check を足す前の数)・約 1,065 秒(約 18 分)。ライブ 2 本(e2e_live_studio 約 180・e2e_live_archive 約 360)で半分。
- NOT_IN_SUITE: chrome-ext の e2e_fake_studio(Edge)・holo-colors の e2e_holo_colors(本物のキー)。

## 5. 文書に名前が無い = 誰も流さないテスト
- `src/human/check/tests/`(5 本)・`src/eval/check/tests/`(3 本)・`src/home/tests/test_check_api.py`・`src/app/tests/test_check_page.py`(V1。AGENTS の表に行が無い)
- `src/home/tests/test_adopt_defaults.py`・`src/pipeline/transcribe/tests/test_clipjob.py`・`dev/tests/test_lint.py`・`test_push_helper.py`
- AGENTS の cut2resolve の行の `src/editor/tests/e2e_edit_pack.py` は消えている(→ e2e_cases_cut)
- **おすすめ**: 表のファイルの手書きの列挙をやめ、`dev/run_unit.py`(層ごと = フォルダごとに discover を 1 プロセスで・所要秒つき・`--only flow` で絞る)を作って AGENTS からはそれだけを指す。WORKLOG 10-11 の「フォルダごとにまとめて流す」をそのまま道具にする形。

## 6. 消せるテスト
- `src/editor/tests/test_names.py`(51 件)と `data_ed_*_names.txt` 12 本(約 830 行): ed_* の殻は RS5 で消えた = 仕組み(modfwd)の検査だけ `ytt/tests/test_modfwd.py` に残して消す
- `test_cut2resolve` の `test_work_dir_matches_ytt_core`・`test_uses_ytt_core`(旧い名前の確かめ)
- eval の整理(eval.md)で消す道具のテスト 約 1,500 行

## 7. 遅い・揺れるもの(WORKLOG の記録)
- 単独で流す: test_mount・test_resolve_pack_contract・cut2resolve の test_serve
- `time.sleep` が多い: test_autorun 26・test_ytt_core 13・test_launch 10。子プロセスを起こす: test_ytt_core・test_mount・test_live_excite_worker・test_worker
- 1 本ごとの秒は記録が無い → `dev/run_unit.py` を作るなら所要秒を出す
