状態(2026-10-10): RS7 の下調べ(Haiku・low)の報告(サブエージェントが本文で返した報告を、まとめ役がそのまま置いた)

# RS7 下調べ: コード量を減らす候補

計算スクリプトは scratchpad(残していない)。テストは `tests/` と `test_`/`e2e_` の名前で除外。

## 1. 行数(src、テスト除く)
| 層 | py 件 | py 行 | js 件 | js 行 |
|---|---|---|---|---|
| pipeline | 37 | 15,454 | 0 | 0 |
| eval | 27 | 11,427 | 0 | 0 |
| editor | 5 | 1,667 | 10 | 9,527 |
| studio | 3 | 831 | 7 | 8,277 |
| human | 24 | 8,492 | 0 | 0 |
| flow | 20 | 7,992 | 0 | 0 |
| home | 6 | 4,484 | 3 | 2,418 |
| ytt | 31 | 4,505 | 0 | 0 |
| manage | 17 | 3,623 | 0 | 0 |
| ui-kit | 0 | 0 | 2 | 2,788 |
| analytics | 7 | 2,574 | 1 | 152 |
| cut2resolve | 1 | 980 | 0 | 0 |
| app | 3 | 535 | 0 | 0 |
| **合計** | **181** | **62,564** | **23** | **23,162** |

js には ui-kit の写し(`src/editor/ui-kit.js`・`src/studio/ui-kit.js` 各 2,667 行)を含む。写しを除くと js は約 17,800 行。

大きいファイル: `studio/review.js` 3,645・`ui-kit/ui-kit.js` 2,666・`home/portal.js` 2,242・`pipeline/analyze/live_excite_worker.py` 1,563・`flow/live_archive.py` 1,506・`eval/tools/eval_marks.py` 1,357・`home/launch.py` 1,338・`editor/app.js` 1,299・`home/live.py` 1,237・`pipeline/transcribe/tx_engines.py` 1,200・`editor/cut.js` 1,199・`flow/live_export.py` 1,193・`eval/tools/eval_asr.py` 1,176・`analytics/calc.py` 1,145・`human/review/store.py` 1,130・`editor/app-rows.js` 1,110・`eval/tools/eval_speakers.py` 1,103・`pipeline/pack/resolve_textplus.py` 1,020

## 2. 重複(6 行以上・名前と数値と文字列を正規化)
Python は 6〜9 行の短い重複だけで、大きな塊は無い。
| 行 | 場所 A | 場所 B | 内容 |
|---|---|---|---|
| 9 | eval/tools/eval_alt.py:43-53 | eval/tools/eval_fill.py:31-41 | argparse・読み込みの型 |
| 8 | eval/tools/eval_alt.py:43-51 | eval/tools/eval_effort.py:38-46 | 同上 |
| 8 | eval/tools/eval_asr.py:71-79 | eval/tools/eval_cut.py:29-37 | 同上 |
| 7 | eval/tools/eval_fill.py:71-77 | pipeline/transcribe/llm.py:66-72 | 編集距離の二重実装 |
| 6 | editor/ed_media.py:4-9 | editor/ed_state.py:4-9 | 先頭の説明 |
JS は `editor/cut.js` の startRowDrag と startDrag の 6 行だけ(ui-kit の写し同士の一致は除く)。

## 3. 一時の口・別名
- `# flow: alias ok` 1 件 = `src/flow/diar.py:135` `voice_rows`
- `_ED_MODULES` = `src/editor/serve.py:156-166`(`+=` が 10 行)・`modfwd` の本体は `src/ytt/modfwd.py`

## 4. 使われていない関数の候補
`_file_*`・`_step_*`・`_doc_*` は段の表から名前の連結で呼ばれる(誤検出)。テストからだけ呼ばれる物: `use_packs_dir`(manage/cases/txindex.py)・`same_key`(ytt/schemas.py)・`read_runtime_entries`(manage/cases/pipeline_io.py)・`read_asr`(pipeline/transcribe/records.py)・`eb_shutdown`(eval/drill/evalbatch.py)・`apply_edits`(eval/tools/eval_llm.py)。`finish_request`(home/launch.py:1107)は要確認。

## 5. dev/lint.py の物差し
`dup-helper`(ytt の小道具の写し)・`dup-block`(既定 12 行以上)・`js-dead` がある。

## まとめ
コード量の直しで減るのは数十〜数百行(eval/tools の引数の型を `_evalcommon` へ・編集距離を 1 つに・テストだけの関数)。大きいのは ui-kit の写し(約 5,300 行。計画では `app/ui/` に 1 つにして写しをやめる)。
