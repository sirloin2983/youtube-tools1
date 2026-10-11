# RV 下調べ 1: コード

状態(2026-10-11): 読むだけの下調べ(Sonnet が AST と grep で数え、上位を手で裏取り)。並行の OPT2(ジョブの器を ② へ・音量を % だけに)と RS8 の直し残しが入ると数字は少し動く。

## 1. 量(ファイル数 / 行。本体とテストを分けた)

| フォルダ | .py 本体 | .py テスト | .js | .css / .html |
| --- | --- | --- | --- | --- |
| `ytt` | 34 / 5,721 | 7 / 3,453 | — | — |
| `pipeline` ① | 40 / 15,741 | 21 / 7,667 | — | — |
| `flow` ② | 31 / 12,786 | 27 / 8,938 | — | — |
| `human` ③ | 33 / 10,947 | 17 / 5,567 | — | — |
| `manage` ④ | 19 / 5,136 | 10 / 3,324 | — | — |
| `eval` ⑤ | 35 / 12,506 | 21 / 7,487 | — | — |
| `app` | 5 / 2,362 | 9 / 3,330 | 13 / 3,100 | 5 / 1,083・2 / 119 |
| `home` | 6 / 2,207 | **26 / 11,890** | 4 / 2,520 | 2 / 300・2 / 471 |
| `studio` | 3 / 858 | 8 / 2,241 | 4 / 5,097 | — |
| `editor` | 5 / 1,715 | **31 / 12,398** | 10 / 7,409 | 1 / 689 |
| `cut2resolve` | 1 / 740 | 1 / 879 | — | — |
| `recorder` | 0 | 0 | — | (文書だけ) |
| `analytics` | 7 / 2,574 | 1 / 423 | 1 / 152 | — |
| `ui-kit` | 0 | 1 / 1,033 | 2 / 2,790 | 1 / 620・1 / 231 |

- 本体の .py 約 105,000 行・テストの .py 約 79,000 行。`home`・`editor` はテストが本体の 5〜7 倍 = 層へ移した部品のテストが置き去り(tests.md)。

## 2. 使っていないコード
本体のトップレベルの関数・クラス約 2,000 件のうち、テスト以外から参照 0 は 13 件だけ = **大きなデッドコードは無い**(消すなら「機能ごと」= eval.md・下の 7)。

| 場所 | 名前 | おすすめ |
| --- | --- | --- |
| `flow/runlog.py:78` | `step_ms` | 消す |
| `ytt/runtime.py:91` | `read_runtime_port` | 消す |
| `pipeline/transcribe/diarize.py:489` | `match_voices` | 呼び元なし → 消す寄り |
| `manage/cases/txindex.py:239` | `key_state` | 説明文は flow/keys から呼ぶと書くが呼ばれていない = **つなぎ忘れか確かめる** |
| `pipeline/transcribe/llm.py:337` `read_llm`・`eval/drill/evalbatch.py:911` `eb_shutdown` | modfwd(`S.名前`)で届くかも | 確かめてから |
| `pipeline/transcribe/retime.py:49,62` | `subread_limits`・`subread_mark` | JS(`app-rows.js:311`)の写しと突き合わせる参照の実装 = 残すと明記するか JS を正に |
| `excite.windowed_scores`・`modfwd.duplicates`・各 `unregister`・`PeakBook.changes_since`・`SettingsFile.set_section` | テスト用 | 残す(テスト用と説明文に) |

- 動的な呼び出し(見かけだけ未使用): modfwd の名前の転送・`getattr(self, "_post_…")`・`Runner._step_*`・パスで起こす子プロセスと CLI。

## 3. API(約 141 本。画面からも Python のクライアントからも使われない物)

| API | 定義 | おすすめ |
| --- | --- | --- |
| `GET /api/transcript-v1` | `editor/serve.py:258` | 消す(画面は `/api/export-file` の format) |
| `POST /api/video/adopt-top` | `studio/serve.py:442` | 消す(`Store.adopt_top` も。採用は F-5 の 1 つの規則 `_step_adopt`) |
| `POST /api/flow/cancel`・`retry`・`estimate` | `app/server.py:616-620` | 画面は `/api/autorun/*` を使う = 二重。**受付を submit 1 つに**するとき画面を flow 側へ切り替えて autorun 側を消す |
| `POST /api/video/request-marks` | `studio/serve.py:443` | 残す(`flow/tools.py:54` が HTTP で呼ぶ。直に呼ぶ形へ移す予定) |

## 4. 転送の殻
- `dev/layer_map.py` の `FORWARDERS` は空(RS5-G)。残る殻は `src/home/launch.py`(11 行)だけ → 消す(AGENTS の手打ちの例を直してから)。
- 「転送だけの殻 … RS5 で消す」と書いたままの説明文が 14 本(`eval/drill/metrics.py:9`・`human/proof/{alt,doc_jobs,learn,retime,store,ytcap}.py`・`manage/cases/{handoff_io,relink}.py`・`pipeline/transcribe/diarize.py:6`・`ytt/{apikey,modfwd,procs,studio_env}.py`)→ 直す。
- `ytt/modfwd`(serve の `_ED_MODULES` が名前を転送)は生きている。編集のテストが `import serve as S` で層の部品を読むのをやめれば(tests.md)、modfwd ごと消せる見込み。

## 5. 重複
| 名前 | 場所 | おすすめ |
| --- | --- | --- |
| `now_ms` | `ytt/schemas.py:26`・`human/check/answerlog.py:44`・`editor/ed_state.py:96`(同じ中身) | `ytt.schemas` に寄せる |
| `is_network_path` | `ytt/fsio.py:136`・`pipeline/pack/cut2resolve_core.py:847`(同じ) | fsio へ |
| `safe_stdio` | `ytt/runtime.py:186`・`pipeline/pack/srt2resolve.py:552`・`eval/tools/eval_marks.py:212` | runtime へ |
| `_step_error` | `flow/studiobook.py:278`・`flow/tools.py:119` | 1 か所に |
| `make_server`・`install_stop_signals`・`_load_core`・`mounted_elsewhere`・`attach_board`・`board_job(s)`・`board_cancel` | `app/server.py`・`editor/serve.py`・`studio/serve.py`・`cut2resolve/serve.py` | 3 つの serve の同じ構えを ytt か app の共通へ(単独起動は 09-26 にやめた = 取り込みの形だけでよい) |
| `runtime_dir` などの包み | `studio/handoff.py`・`cut2resolve/serve.py`・`ytt/runtime.py` | 包みを減らす |
| `pct`・`num` | eval_*.py・analytics | `_evalcommon` へ |
| ジョブ・待ち行列の仕組み **8 通り**(`runqueue.Queue`・`jobs`・`batch.Batch`・書き出し・パックの Task・ライブの Exporter・Archiver・LiveTx) | ① ② | `plan/opt-pipeline-flow.md`。OPT2 の後半で進行中 = RV では結果を見るだけ |

## 6. 名前が実態と合わない物

| 物 | 場所 | 今の意味 | おすすめ |
| --- | --- | --- | --- |
| 封筒の `legacy`(mode・onFail・streamer) | `flow/envelope.py:15,30,133,166`・`flow/run.py:129,338,345-350`・`app/cli.py:52,383-391`・`flow/livesession.py:185,277`・`docs/spec/pipeline.md:151` | 「一時」のはずが全経路で必須 | 束の正式な欄へ。`mode` は `MODE_STEPS` 8 種と一緒に「束の `run`(どこまで・届けるか)」で表して消す |
| 束の `run.pinned` | `flow/run.py:153-168,306`・`flow/livesession.py:200-275`・`flow/live_export.py:489` | 依頼が固定した項目の名前の並び | `locked`(か `fixed`)に改名。束の形の版を上げて読み替え |
| AutoRunner の `start`・`start_new`・`start_docs`・`start_request`・`start_file` と `/api/flow/submit` | `home/autorun.py:306-406`・`flow/runqueue.py:273` | 入口が 2 つ。画面は autorun だけ・submit は CLI だけ | 受付を submit 1 つに(画面も封筒 + 束を送る)。`_asked_spec`・`_with_asked`・`_pins` の写しが消える。hook 12 個を「ホストの口」1 つに(memo ②-1) |
| `src/home` | 入口の app のコード + ホームと設定の画面 | — | `src/app/` へ(folders.md) |
| `src/studio`・`src/editor`・`src/cut2resolve` | 画面の部品と API の配線だけ | ツール名のまま | folders.md |
| `src/recorder` | 文書だけ(`recorder.py` は無い。AGENTS は「ある」と書く) | — | 消す・文書は `pipeline/ingest/` へ |
| `src/analytics` | `layer_map.py:98-105` は `manage/ops/analytics` へ移す前提なのに動いていない・層の検査の外 | — | 移すか、層の外と決めて表を直す |
| 説明文の層の番号・計画の記号 | `human/proof/` の先頭「② 人の操作の層」など・flow に M○ 139 など | — | docs.md の 3 |

## 7. 設定の欄
- `src/home/settings/schema.json` の 110 項目に**読まれない物は 0**。
- `packFps`(`ytt/settings.py:14,202`): fps は 30 に固定 = 検査と移行の登録だけ残る → 消す。
- `packRender`(schema.json:136): 画面が保存して画面だけが読む = パックを作る引数で効いているか確かめる。
- `prefs.DEFAULTS["autorun"]["mode"]`(`src/home/prefs.py:61,103-106`): 読み手が見つからない → 消す寄り(受付を submit 1 つにするときに一緒に)。

## 8. 既存の見直しメモから RV に回っている物(`plan/opt-pipeline-flow.md`)
- 構造: `recorder.py`(録画の HTTP サーバー)を app へ・`live_align_worker.py` の置き場所・`live_excite_worker.Worker` の段取りと計算を分ける・`Archiver` を割る(`live_after.py`・`live_marks.py`)・`diar.py` の覚えた声の置き場所を ④ へ・`live_cleanup.Cleaner` を ② 寄りに・`delivery.py`(mixin)はホストの口でまとめて消す。
- 機能の見直し(行を大きく減らすならここ): 配信後の全自動 M7(約 400)・アーカイブでの作り直し P4(約 700)・配信中の候補の文字起こし D-11(約 360 + ワーカー)・配信ごとの記録 D-12(約 240)・失敗の集約 M3(約 170)を、友人も含めて今どれだけ使っているかで残すか決める(F1 の形と合わせて)。
- パック: FCPXML と単独のコマンド 2 つ(`srt2resolve.py`・`auto_cut.py`)・単独のコマンドの EDL(決定 3-34 で RV で聞く)・説明文の古い版(`cut2resolve v0.4.0` など)・手順書の文章がコードの中(`resolve_textplus.instructions` 116 行・`build_readme` 57 行)。
- 説明文: `fill.py`・`llm.py` の先頭「「編集」のサーバーの部品」・`find/` の「① 配信ランキング」・`doclist`・`handoff_io` の古い先頭・先頭 50 行が仕様書になっている物。
