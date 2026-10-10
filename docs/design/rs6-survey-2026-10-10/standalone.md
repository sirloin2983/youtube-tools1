状態(2026-10-10): RS6 の下調べ(Haiku)の報告

# RS6 下調べ: ① 単体の起動(URL か動画 → パック)

読むだけの調べ。コードは変えていない。行番号は 2026-10-10 時点の作業フォルダ。「推測」と書いたものは読んでいない。

## 1. Runner の段 → HTTP API → 今の実体

Runner は `src/pipeline/run.py`(939 行)。段の関数は `_step_*` と `_pack_one`。HTTP の呼び先は `self.client`(ToolClient)。

| 段 (run.py) | 呼ぶ API | 今の実体(serve の行 → 関数) |
| --- | --- | --- |
| 解析 `_step_analyze` 423・`_analyze_item` 438 | スタジオ `GET /api/settings`(441)・`POST /api/queue/add`(449)・`GET /api/queue`(461)・`POST /api/queue/cancel`(480) | studio/serve.py:398 `BATCH.add`・420 `_settings`・187 `/api/settings` 読み。解析本体は `pipeline/analyze/analyze.py`(推測: BATCH は `pipeline/batch.py`) |
| 採用 `_step_adopt` 512・`_step_adopt_request` 491 | `POST /api/video/adopt-top`(515)・`/api/video/request-marks`(500) | studio/serve.py:407-408 `_adopt_top`・`_request_marks`(本体は human/review 側。推測) |
| 書き出し `_step_export` 541 | `GET /api/settings`(530)・`POST /api/export`(547)・`GET /api/export?id=`(553)・`POST /api/export/cancel`(559) | studio/serve.py:409-410 → `pipeline/export/exporter.py` |
| 認識 `_step_transcribe` 574 | editor `GET /api/settings`(637・812)・`POST /api/transcribe`(590・832)・`GET /api/jobs`(594)・`POST /api/transcribe/cancel`(603) | editor/serve.py:303 `validate_job` → `human/proof/doc_jobs.py` → `pipeline/transcribe/recognize.py`・worker |
| 話者 `_step_diarize` 857 | editor `POST /api/diarize`(871) | editor/serve.py:304 → `human/proof/speakers.py` → `pipeline/transcribe/diarize.py` |
| 字幕の取り出し `_pack_one` 684 | editor `POST /api/export-file`(693・697) | editor/serve.py:319 → `manage/cases/handoff_io.py` |
| 文書の読み `_edit_keeps` 617 | editor `GET /api/edit`(619) | editor/serve.py:275 → `human/proof/store.py` |
| パックの記録 | editor `POST /api/edit/pack`(745) | editor/serve.py:334 → `human/proof/store.py` の record_pack |
| パック `_pack_one` 719・733 | cut2resolve `POST /api/build`(719)・`GET /api/job?id=`(727)・`POST /api/job/cancel`(733) | cut2resolve/serve.py:751・736・773 `_build` → `pipeline/pack/pack.py`(推測: `_build` 本体は cut2resolve_core) |

- 設定の読み: 解析・書き出し・認識・パックの設定は、どれも API 越しに「ツールの画面の設定」を読んでいる(run.py 441・530・637・812)。① 単体では設定ファイルを読まないので、この読みを束(spec)の値に置き換える必要がある(§2・§5)。
- `run.py` 冒頭 docstring と `run()` の 920 行付近の注: RS1-7 では spec を読まない。段が spec を読むのは RS6 から。現状 `run(client, input, spec=None, …)` の spec は `r.spec` に入るだけ。
- 段の関数は `Runner` の中のメソッド。`_pref`・`_checkpoint`・`_await_tools`・`_studio_video`・`_docs`・`_pick_doc`・`_after_pack` など 12 個の hook は既定で何もしない(run.py 273-323)。単体の CLI では既定の Runner を使えばよい。

## 2. 段を直接呼ぶために要るもの(入口なしで ① を動かすときの不足)

| 要るもの | 今の場所 | 単体で足りないこと |
| --- | --- | --- |
| 作業データの置き場所 | `src/ytt/workdata.py` 32 `set_root`・42 `set_data_dir`(変数の持ち主)。`src/ytt/datadir.py` 46 `data_root`・93 `locate`・102 `resolve` | serve の起動時に `set_data_dir` が呼ばれる(editor/serve.py:686・714)。単体では呼ばれず既定値(推測: %LOCALAPPDATA%)。テストは `workdata.TX_DIR` を直接差し替える |
| ジョブの表と同時実行 | `src/ytt/jobs.py` 133 `SLOTS`(プロセスに 1 つ)・173 `register`・278 `add_job`・304 `worker` | 登録は editor/serve.py:161-169 が行う。`SLOTS` は ① では直接取る(`tool_slot` 167)。登録のない kind(transcribe など)は動かない |
| 認識ワーカー | `src/pipeline/transcribe/worker_client.py` 148 `WorkerClient`・422 `WORKER`・87 `worker_script`・109 `worker_env`。ワーカー本体 `worker.py` | 別プロセス。単体 CLI でも `WORKER` を使えば起動できる(推測)。GPU・部品の有無は `nvidia_gpu` 653・`has_faster_whisper` 670・`worker_has` 689 |
| 認識の差し込み | editor/serve.py:180 `_txbackend.set_selector`・182 `_txrecords.set_dict_inputs`・188 `_txrecognize.set_head_stripper`・192 `_docjobs.set_hooks`・196 `_speakers.set_context_namer` | serve が起動時に入れる。単体では未設定 → 疑似か本物かの選択・辞書・冒頭の削り方が既定値。① で使うなら CLI 側でこの 5 行相当を入れる必要あり |
| 設定の読み | studio `STORE.get_ui()`(studio/serve.py:187)・editor の `ed_state` 設定 | ① は設定ファイルを読まない(計画 5-4)。束から値を渡す形に直す必要 |
| API キー | `src/ytt/apikey.py` 16 `get_api_key`(環境変数 YOUTUBE_API_KEY が優先、無ければデータ置き場所の config.json) | 束の外(計画 5-4)。CLI は環境変数だけにするのが安全 |
| ffmpeg・動画の小道具 | `src/ytt/tools.py` 32 `find_tool`・54 `find_ffmpeg`・59 `ffmpeg_info` | 問題なし(入口に依存しない) |
| 案件・txindex・届ける | `manage/cases/txindex.py`・`human/friend/deliver.py` | ① が読んではいけない(層の決まり)。Runner の hook で空の既定を使う |
| 録画 | `pipeline/ingest/` | URL が配信中の録画は ingest の子プロセス。単体 CLI では後回しでよい |

入口なしで ① を動かすと足りないものは、主に (a) 設定を束から渡す読み直し、(b) serve が入れる登録の口(selector・hooks・namer など)、(c) 作業データの場所の指定、(d) 認識ワーカーの起動。ジョブの表(`SLOTS`)は ① 自身で取れば足りる。

## 3. 束(spec)の形と呼ぶ側

- `src/pipeline/spec.py`: 節 8 つ = hints・analyze・adopt・export・transcribe・post・pack・run(`SECTIONS` 99 行)。既定値 `DEFAULTS` 112-171、`merge(spec)` 174(既定に重ねる。知らない節・鍵は ValueError)、`validate(bundle)` 330(型と範囲。合わなければ理由つき ValueError)。`FIXED` 103 は束に入れない固定値。純粋関数だけ(ファイル・ネットワークを読まない)。
- 呼ぶ側の組み立て: `src/home/autorun.py` の `AutoRunner`(195)。`start`(359)・`start_new`(377)・`start_docs`(398)・`start_request`(416)・`start_file`(447)が引数を受けて `Run` を作り、`run_mod.run(self.client, run, hooks=self)`(721)を呼ぶ。束そのものはまだ autorun が組み立てていない(spec を渡す行は見当たらない = 推測)。`spec.py` は autorun の検査を読み直す形(`src/home/autorun.py` 56-57 行)。
- `src/human/friend/intake.py` と `src/home/live.py`: 束を組む箇所は確認できなかった(grep で `merge`・`validate` のヒットなし)。友人の依頼は `start_request` の引数(区間・出る人・カットなど)で渡る = 推測。
- テストは `src/pipeline/tests/test_spec.py`・`test_run.py`(FakeClient が API を模写: 18 行 `class FakeClient`)。

## 4. 今ある CLI の作り方の例

- `src/pipeline/pack/cut2resolve.py`: `main(argv=None)`(106)。`argparse`(108)で `inputs` と多数の引数を受け、`build_request(args)`(44)→ `run(args)`(85)。末尾 `if __name__ == "__main__":`(156)。引数の既定は `pack.Request` の既定を読む(serve と CLI で同じ既定)。
- `src/eval/tools/eval_marks.py`: `argparse` の `p.add_argument(...)`(1329-1334)。`--live` `--analyze-missing` などのフラグ。作業データは読むだけ。
- 注意: どの CLI も `src/` 直下の import 形(`from ytt import …`)を使い、起動は `py -3.10 src/…/x.py`。`sys.path` の調整は各ファイル先頭(推測)。

## 5. ① 単体 CLI の候補と段の分け方

入口案(例):
```
py -3.10 src/pipeline/run.py <URL または 動画ファイル> --spec spec.json --out <フォルダ> [--from 段] [--force]
```
- `--spec` は `pipeline.spec.merge` に通す(変えたい所だけの JSON)。API キーは環境変数 `YOUTUBE_API_KEY` だけ(束の外)。
- `--out` は結果の束(実行 id・有効な束・段ごとの成果物のパス・パックのフォルダ・失敗と理由。計画 5-4)を書く場所。作業データは `--out` の下に作るか、`workdata` へ `set_root` で向ける(要確認)。
- 段の分け方の案: `ingest`(URL → 動画。`pipeline/ingest/sources.py`)→ `analyze`(`pipeline/analyze/analyze.py`)→ `adopt`(自動採用)→ `export`(`pipeline/export/exporter.py`)→ `transcribe`(`pipeline/transcribe/recognize.py` + `worker_client.WORKER`)→ `post`(後処理 `postproc`・`fill`・`llm`・`retime`)→ `pack`(`pipeline/pack/pack.py`)。各段の成果物と鍵(計画 5-2)を JSON で書く。
- 段は関数で直接呼ぶ形に寄せる(HTTP を挟まない)。今は ToolClient 経由なので、まず段ごとに「API の本体関数」を引数で呼べる形に切り出す必要がある。RS1-7 の注に沿うなら、段ごとに serve と同じ関数を呼ぶ薄い層を作る。

リスクと注意:
- 向きの決まり(`dev/tests/test_layering.py`・`dev/layer_map.py`): `pipeline` は `ytt` と `pipeline` だけを import できる(run.py の docstring 2 行目以降)。① が `human`・`manage` を読むと違反になる。案件・届ける・txindex は hook で外から差し込む。CLI の入口は `pipeline` の外(例: `src/app/` か `src/pipeline/cli.py` を `ytt`・`pipeline` だけで書く)に置くのが安全(推測・要確認)。
- 登録の口(selector・set_hooks・set_dict_inputs など)は serve が入れている。CLI で同じ口を入れるには `human`・`eval` を import する必要がある恐れ(editor/serve.py の import 元)。層の向きに反するので、口の登録は app 層の CLI で行う形を検討。
- 設定の読みを消すと、画面の既定値と CLI の既定値が二重になる。束の `DEFAULTS` と serve の既定の一致を検査するテストが要る(推測・既存の `test_spec.py` で足りるか要確認)。
- 認識ワーカーは別プロセス。単体 CLI の終了時に子プロセスを残さないこと(`WORKER_CANCEL_GRACE`・`WORKER_SILENCE_TIMEOUT`、worker_client.py 81-83)。
- Windows の作業データはパッケージ写し(MSIX)の影響を受ける(AI が書くと本物の場所と違う。CLAUDE.md の注意)。本番の実行は入口を通すか、外のプロセスで確かめる。
- 文字起こしのサーバー側に numpy・faster_whisper を import しない決まり(CLAUDE.md)。CLI も同じ。

## 6. 次に決めること(要確認)

1. 段の関数化: 段ごとに HTTP ではなく関数で呼ぶ薄い層をどこに置くか(`pipeline/run.py` 内か兄弟モジュールか。run.py の docstring は「兄弟モジュール」を推奨)。
2. 登録の口をどの層で入れるか(CLI 側の app 層に置く案)。
3. `--out` と作業データの場所の関係。
4. 束を組む人: AutoRunner が束を作る版(RS6 で追加)と、CLI が JSON を読む版の二つを、同じ `spec.merge` に通す。
