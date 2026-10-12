# RV 下調べ 2: ⑤ 検証 `src/eval/`

状態(2026-10-11): 読むだけの下調べ(Sonnet の報告を Opus が確かめた)。消すのは RV の本番でユーザーに聞いてから。

## 要点
- `src/eval/` はコード約 10,950 行 + テスト約 7,500 行(tools 8,750 / 6,544・drill 2,790 / 542・check 687 / 401・fake 274)。「約 11,400 行」は計画の数字と合う。
- **ホームの「精度の自動測定」(`eval/drill/accuracy.py` の `AREAS`)が eval_asr・marks・speakers・alt・fill・timing・cut を子プロセスで起こす** = この 7 本はホームの表示が生きている限り現役。
- 新しい V1 確かめる(`src/eval/check/*`・`src/human/check/`)は現役。`human/check` は eval のコードを import せず、記録の形をそろえているだけ。
- 消す候補ははっきり分かれる: 一度きりの道具 5 本(約 3,660 行)と、RS8 で画面を消した評価ドリル・評価の一括・評価用フォルダの整理の API と起動時の処理(約 1,700 行 + 編集側のテスト・JS)。

## ファイルごと(行 = コード / テスト。日付は最後のコミット)

| ファイル | 行 | 使われ方 | 分類 | おすすめ |
| --- | --- | --- | --- | --- |
| `drill/accuracy.py` | 597 / 542 | `/api/accuracy`(入口)・ホーム `portal.js` | 現役 | 残す |
| `drill/metrics.py` | 326 / 編集側 | `/api/metrics`・`/api/eval-baseline(s)`・ホームの「精度と学習」(`portal-edit.js`) | 現役 | 残す |
| `drill/drill.py` | 444 / 編集側 | `/api/drill/*`(評価ドリル)+ `drill_candidates`(話者の名前の候補。`speakers.set_context_namer`) | 半分死に | ドリル本体を消し、名前の候補は `human/proof/speakers` か `human/check` へ移す |
| `drill/evalbatch.py` | 918 / 編集側 | `/api/eval-batch/*`・`doc_jobs` の hook(`redo_skip`・`redo_fill`)・起動時の `eb_start_background` | 画面は消えた・hook は生きる | hook の中身(作り直し)を ③ へ寄せ、評価の一括は消すか相談 |
| `drill/folders.py` | 505 / 編集側 | `/api/eval-folders*`・起動時のタイマー(`_evalorg_startup`) | 画面は消えた | 評価用の動画の置き場所の整理が今も要るかを聞いて、要らなければ消す |
| `fake/fake_asr.py`・`fake_worker.py` | 274 | テストの疑似 | 現役 | 残す |
| `check/*` | 687 / 401 | V1 確かめる | 現役 | 残す |
| `tools/_evalcommon.py`・`evaldata.py` | 611 / 294 | 共通部品・評価データの形 | 現役 | 残す |
| `tools/eval_asr.py`・`eval_marks.py`・`eval_speakers.py`・`eval_alt.py`・`eval_fill.py`・`eval_timing.py` | 5,014 / 4,828 | `AREAS`・OPT3 の確かめる道具 | 現役 | 残す |
| `tools/eval_cut.py` | 407 / 330 | `AREAS`(cut)。WORKLOG の最後の言及 10-07 | 現役だが薄い | 残す(自動の測定が回しているか一度見る) |
| `tools/_studioapi.py` | 86 | eval_marks だけ | 付属 | 残す |
| `tools/eval_layers.py` | 128 / 91 | RS8 O2-1 の確かめ | 一度きり | O2 が済んだら消す |
| `tools/eval_casebook.py` | 171 / 126 | RS8 B3-3 の往復の確かめ | 一度きり | 消す |
| `tools/eval_llm.py` | 198 / 152 | LLM の後処理(`plan/llm-postfix.md`) | 計画しだい | LLM の後処理を続けるなら残す |
| `tools/eval_effort.py` | 458 / 415 | 校正の手間(A6。10-09 に 22 本で測った)。`AREAS` に無い | 済んだ調べ | 消す(進行度と目標は 0.69.0 で消えた) |
| `tools/eval_cloud.py` | 511 / 393 | クラウドの文字起こしとの比較(決定 3-10・E1) | 済んだ調べ? | E1 を続けるかを聞く。続けないなら消す |
| `tools/eval_fetch.py` | 405 / 165 | 外から参照なし(評価用の動画の取得) | 手で使う | 新しい評価用を足す予定が無ければ消す |
| `tools/eval_import.py` | 388 / 353 | 外から参照なし(評価データの取り込み) | 手で使う | 同上 |
| `tools/eval_split.py` | 373 / 197 | 外から参照なし(評価用の分割) | 手で使う | 同上 |

## 画面との食い違い
- `src/editor/app-tpl.js:321` に評価ドリルのカード `#drillCard`・`#drillGo` が、`app.js:274`・`app-learn.js:263-505` にその動きが残る。案件の画面の校正(`edhost.js`)はこのテンプレートを読むが、カードは `#menuPanel` の中で `src/app/ui/cases/panels/proof.css:11-13` が `display:none` にしている = **見えないがコードと DOM は生きている**(決定 10-11 夕の「消えたまま」とは合う)。消すときはテンプレートと JS を同時に(`$('#drillGo')` は要素が無いと落ちる)。詳しくは ui.md の 3-1。

## 消した場合の目安
- 一度きりの道具 5 本(effort・cloud・fetch・import・split): コード 2,135 + テスト 1,523 = **約 3,660 行**。eval_layers・eval_casebook を足すと約 4,180 行。
- 評価ドリル・評価の一括・フォルダの整理の画面向けの部分: **約 1,700 行 + 編集側のテストと JS**(`app-learn.js`・`app-tools.js`・`app-tpl.js`・`editor/serve.py` の route・起動時のタイマー 2 つ)。
- 合わせて ⑤ は約 11,400 → 約 5,500〜6,000 行。

## 確かめ方
1. 候補ごとに `grep -rn "<名前>" src dev docs/spec setup` で参照 0 を確かめる。`dev/layer_map.py` の FILES・`src/editor/README.txt`・AGENTS の表から名前を外す。
2. `py -3.10 -m unittest dev/tests/test_layering.py`・`py -3.10 dev/lint.py`・`src/eval/tools/tests/` 全部。
3. ドリルを消すなら `py -3.10 src/app/tests/e2e_cases_proof.py` と `test_proof_api.py`。
