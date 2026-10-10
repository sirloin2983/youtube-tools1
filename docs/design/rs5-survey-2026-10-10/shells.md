# RS5 下調べ: 転送(殻)の読み手の数

状態(2026-10-10): 下調べ(Haiku)の報告

読むだけの調べ。コードは書き換えていない。数字は `grep` の行数(本体とテストを分けた、`__pycache__` は除外)。
**注意**: 「件数」は名前が出てくる行の数で、コメント・docstring の言及を含む。実際に読む行(import・属性の参照・patch)だけの数は下の表の「うち実コード」の列に近似で書いた。正確な付け替え表は、消す前に各殻ごとに grep をやり直す必要がある。

## 1. editor の転送の殻(src/editor/ed_*.py・RS5 で消す)

「本体」= src/ の本体(コメント含む)、「テスト」= tests/ 配下。「patch・代入」= `mock.patch(.object)` や `X.名前 = …` で殻へ差し替えている行。

| 殻 | 中身(持ち主) | 本体の件数 | テストの件数 | patch・代入(殻へ) | 主な読み手 |
| --- | --- | --- | --- | --- | --- |
| ed_jobs.py | ytt/jobs・pipeline/transcribe の roster・tx_engines・postproc・records・worker_client・recognize・txbase、human/proof の doc_jobs・rerun。`_add_moved` で eval/fake/fake_asr | 22(12 ファイル) | 196(17 ファイル) | テスト 1 ファイル(test_eval_asr)だけで `patch.object(ed_jobs, …)` 数件、`S.ed_jobs.IN_WORKER` 等の代入 | test_names 25・test_alt 24・test_evalbatch 32・test_normalize30 19・test_fill 20・test_autodiar 17・test_ytcap 13・test_records 13・test_llm 10・test_thumb_job 10・eval_speakers / eval_timing(`getattr(S,"ed_jobs")`)・serve.py(`_ED_MODULES` 登録) |
| ed_speakers.py | diarize・human/proof/speakers。`_add_moved` で eval/fake | 8(5) | 18(6) | `tools/eval_speakers.py:766` `S.ed_speakers.DIAR_DIR = d`・`:557`・`:799` の参照、テスト 2 本で `S.ed_speakers` 参照 | test_names 8・test_autodiar 4・test_metrics 3 |
| ed_store.py | human/proof/store・manage/cases/doclist(`_add_moved`) | 7(4) | 82(14) | 参照のみ(patch は確認できず) | test_evalbatch 40・test_names 12・test_fill 7・test_llm 6・test_alt 4・test_normalize30 5。コード: ed_media 2・ed_thumb 3・serve.py 1。`eval/tools/tests/test_eval_effort.py:100` が `import ed_store` |
| ed_learn.py | pipeline/transcribe/replace・human/proof/learn・eval/drill/metrics(`_add_moved`) | 11(10 コード・docstring 含む) | 18(7) | 参照のみ | test_names 11・test_llm 2 ほか。コード: eval/tools/eval_asr.py 1・eval/drill/metrics.py 1・ytt/settings.py 2(コメントの言及が多い) |
| ed_alt.py | human/proof/alt。`_add_moved` で eval/fake(`_alt_fake`) | 4(3) | 18(6) | 参照のみ | test_names 6・test_alt 5・test_ytcap 4・test_metrics 1・e2e_alt 1 |
| ed_ytcap.py | human/proof/ytcap | 2(1) | 8(5) | 参照のみ | test_names 3・test_ytcap 2・e2e_alt 1・fake_ytdlp 1・test_metrics 1 |
| ed_retime.py | human/proof/retime(計算は pipeline/transcribe/retime) | 5(3) | 8(4。json・cjs 含む) | 参照のみ | test_names 3・test_retime 2・subread_cases.json 1・test_document_save.cjs 1・test_metrics 1 |
| ed_relink.py | manage/cases/relink・eval/drill/folders(`_add_moved`) | 5(3) | 11(2) | 参照のみ | test_names 10・test_doc_jobs 1。コード: ytt/fsio.py 2・ytt/settings.py 1(コメント) |
| ed_misc.py | manage/cases/handoff_io・human/proof/batch | 2(1。`layer_map` のみ) | 5(1。test_names) | なし | test_names 5 |

editor の殻の合計: 件数で約 430(本体約 60・テスト約 370)。ただし test_names.py と 9 本の `data_ed_*_names.txt`(src/editor/tests/)が名前の一覧を持つ。殻を消すと、一覧の名前が引けなくなる(テストが落ちる)。

### serve.py の受け付け(S.名前 で読めるか)
- `src/editor/serve.py:100` で `import ed_state, ed_store, ed_relink, ed_media, ed_jobs, ed_speakers, ed_learn, ed_misc` と**殻をすべて import している**(殻の _MOVED の持ち主を登録するため)。
- `_ED_MODULES`(serve.py:143-144)に並んでいるのは **ed_jobs の殻だけ**。他の殻(ed_store・ed_speakers・ed_learn・ed_relink・ed_misc・ed_alt・ed_ytcap・ed_retime)は、コメントで「殻は名前を持たない・並べない」と書いてある(名前の重なり防止)。
- つまり `S.名前` は持ち主の部品(human/proof・pipeline/transcribe 等)を直接並べて読む。殻を消しても `S.名前` の解決は変わらない見込み。
- **見込み(4)**: 殻を消しても serve の受け付けは壊れない見込みだが、次の箇所は殻の名前(`ed_jobs.transcribe_fake` 等)を直接参照しているので要対応:
  - `src/editor/serve.py:180` のコメント(`ed_jobs.transcribe_fake などの旧い名前は fake_asr へ転送`)
  - テスト群の `import ed_store`・`S.ed_jobs`・`S.ed_speakers` 等(上の表)
  - `src/eval/tools/eval_speakers.py:557,584,766,799`・`eval_timing.py:281` の `S.ed_jobs` / `S.ed_speakers`(実コード)
  - `_evalcommon.py:257` の `J = S.ed_jobs`(実コード)

## 2. studio の殻(src/studio/common.py・RS5 で消す)

- `common.py` は殻 + 起動の小物 11 個(`_load_core`・`CODE_DIR`・`migrate_old_logs`・`check_tools`・`start_env_check`・`env_state` 等)。殻の本体は `_MOVED` の 7 モジュール(ytt/studio_env・apikey・procs・mediainfo・textutil・errors・pipeline/ingest/sources)へ回す。
- **読み手(import・patch の件数。`common` という語は ytt 内の別の意味でも使われるので、実コードの件数は下の数字より少ない)**:
  - 本体: `src/studio/serve.py` 4-5 件(`import common` / `common.名前`)・`src/home/mount.py` 2・`src/home/autorun.py` 1・`src/pipeline/ingest/sources.py` 1(コメント)・`src/human/proof/ytcap.py` 1(パス文字列)。`dev/layer_map.py` 2。
  - テスト: `src/pipeline/export/tests/test_exporter.py` 38・`src/studio/tests/test_robustness.py` 46・`src/studio/tests/test_api.py` 16・`src/home/tests/test_mount.py` 7・`src/studio/tests/test_rank_live.py` 3・`test_handoff.py` 2・`test_file_recovery.py` 1・`e2e_ui.py` 5・`e2e_analyze.py` 2・`e2e_review.py` 2・`src/home/tests/e2e_live_archive.py` 2・`e2e_live_studio.py` 2。
  - テストの `patch` 差し替えは `test_robustness.py` と `test_api.py` に多い(`mock.patch.object(common, …)` の形。件数は未数え上げ)。
- 合計の目安: 本体 約 10・テスト 約 130 件。

## 3. ytt_core の転送(src/ytt_core/__init__.py・RS5 で消す)

- 中身: `sys.modules` に `ytt_core.<名前>` を登録する転送。持ち主は ytt(colors・datadir・fsio・httpsec・jobs・layout・loudness・names・normalize・pick・recproto・runtime・schemas・settings・tools)・eval/tools/evaldata・manage/cases/txindex・pipeline/analyze/excite。
- **import 文の読み手(py)**: 約 45 ファイル・約 80 行。内訳はほぼテスト(`src/home/tests/` 約 25 ファイル・`src/ytt/tests/test_ytt_core.py` 7・`src/editor/tests/` 約 8・`src/cut2resolve/tests/test_serve.py` 4・`src/eval/tools/tests/` 約 5・`dev/tests/` 2)。本体は `src/ytt/__init__.py` 4・`src/ytt/layout.py` 2 のコメント程度。
- **文書・パス文字列**: `src/cut2resolve/README.txt` 14・`src/home/README.txt` 13・`src/studio/README.txt` 6・`src/editor/README.txt` 5・`src/editor/AGENTS.md` 3・`src/recorder/README.txt` 4・`src/ui-kit/README.md` 1。
- **サブプロセス・設定ファイルのパス**: `.bat`・`setup/` には無し。`friend-apps/*/members.json` の 5 件は `ytt_core` のコメント言及(ファイル名ではない・要確認)。
- `dev/lint.py`・`dev/tests/test_layering.py`(2)・`dev/tests/test_cleanup_legacy_data.py`・`e2e_datadir.py` は名前を参照する(層の検査と片付けの検査)。
- 合計の目安: py の import 約 80・文書 約 45・検査 約 8。

## 4. dev/eval_*.py の転送(13 本・runpy・RS5 で消す)

- 中身: 14 行。`runpy.run_path` で `src/eval/tools/eval_X.py` を `__main__` として動かすだけ。対象は alt・asr・cloud・cut・effort・fetch・fill・import・llm・marks・speakers・split・timing の 13 本。
- **読み手(パスの文字列・子プロセス)**:
  - `src/eval/drill/accuracy.py` 11 件(夜の自動測定が `dev/eval_*.py` を子プロセスで起こす。**実コードの付け替えが要る**)
  - `src/home/tests/test_accuracy.py` 9 件(同上・テスト)
  - `dev/run_editor_suite.py` 2 件(写す一覧・実行)
  - `dev/layer_map.py` 2 件(各殻の行き先の表)
  - `src/eval/tools/_evalcommon.py` 3 件・`src/eval/tools/evaldata.py` 1 件・`src/editor/ed_state.py` 1 件・`src/editor/serve.py` 1 件(コメント・パスの言及)
  - `src/editor/README.txt` 11 件・`src/editor/AGENTS.md` 19 件・`src/home/README.txt` 8 件・`src/ui-kit/README.md` 1 件(**手打ちのコマンドの文書**。旧いコマンド `py -3.10 dev/eval_…py` を書いている)
  - 各 `src/eval/tools/eval_X.py` の docstring(本体の中の旧いコマンドの言及・eval_alt 6・eval_asr 9・eval_cloud 9・eval_effort 10・eval_speakers 8 など)
- 付け替えの要点: 旧い入口(夜の自動測定の子プロセス・手打ちのコマンド)が `dev/eval_*.py` の旧いパスを使い続けるので、転送を消すと `accuracy.py` の子プロセス起動と文書 2 つの書き換えが要る。
- **テストの参照**: `src/eval/tools/tests/test_eval_*.py` 13 本が各 eval の**新しい**パス(src/eval/tools)で読んでいる(旧い転送を使うテストは確認できず・要確認)。

## 5. 旧いパスの起動用の転送(runpy・src/editor と src/home)

| 転送 | 新しい本体 | 読み手(旧いパスを使うもの) |
| --- | --- | --- |
| src/editor/tx_worker.py | src/pipeline/transcribe/worker.py | `src/editor/tests/test_worker.py:550` が旧いパスで `--probe` を起動(テスト 1 件)・`src/editor/tests/e2e_ui_mounted.py` は新しいパス(`WORKER_TAIL`)・`src/editor/AGENTS.md` 3 件・`README.txt` 2 件(文書)・`dev/layer_map.py` 5 件。本体の起動はすべて新しいパス(`worker_client.py` の `WORKER_SCRIPT`・`test_worker_client.py`) |
| src/home/live_excite_worker.py | src/pipeline/analyze/live_excite_worker.py | 本体の起動は `src/pipeline/analyze/live_detect.py:54` の `WORKER = os.path.join(CODE_DIR, "live_excite_worker.py")` が**新しい場所**(同じフォルダ)。旧いパスを使うのは `src/home/tests/fake_excite_worker.py`(偽)・`test_live_detect.py`・`src/home/README.txt` 5 件(文書)・`dev/layer_map.py` 5 件 |
| src/home/live_align_worker.py | src/pipeline/ingest/live_align_worker.py | 本体の起動は `src/pipeline/ingest/live_archive.py:73` が新しいパス。旧いパスの読み手は `src/home/tests/test_live_archive.py`(コメント)・`e2e_live_archive.py`(コメント)・`dev/layer_map.py` |
| src/home/live_tx_worker.py | src/pipeline/transcribe/live_tx_worker.py | 本体の起動は `src/pipeline/transcribe/live_tx.py:25` が新しいパス。旧いパスの言及は `src/pipeline/transcribe/tx_engines.py:194` のコメント(**「入口の home/live_tx_worker.py が名前を参照しているので残す」** = 定数を残す理由がコメントに書いてある・要確認)・`src/home/tests/test_live_tx.py` 7 件(テスト・コメント多い)・`src/home/prefs.py` 1 件 |

- 4 本とも、**現在のコードは新しいパスで起動している**。旧いパスを使うのは「古いコードのまま動いている入口が起動し直すとき」だけ(各転送の docstring の説明どおり)。よって殻を消す前に、起動中の旧い入口を止める必要がある(RS5 の前提)。
- 上の表の件数の大半は docstring・README の言及で、実コードの読み手は `test_worker.py:550` の 1 件だけ。

## 6. まとめ(件数の合計と、いちばん多い所)

- **editor の転送 9 本**: 件数の合計は約 430(本体 約 60・テスト 約 370。コメント込み)。いちばん多いのは `ed_jobs`(約 218・テスト 196)、次いで `ed_store`(約 89)。実コードの付け替えは `S.ed_jobs`・`S.ed_speakers` の参照(eval_speakers・eval_timing・_evalcommon)と `patch.object(ed_jobs, …)`(test_eval_asr)。
- **studio の殻 common.py**: 件数の合計は約 140(本体 約 10・テスト 約 130)。いちばん多いのは `test_robustness.py`(46)・`test_exporter.py`(38)・`test_api.py`(16)。
- **ytt_core**: import 約 80・文書 約 45(README 4 本が中心)。いちばん多いのは `src/ytt/tests/test_ytt_core.py`(7・import)と `src/home/tests/` 約 25 ファイル。
- **dev/eval_*.py**(13 本): 読み手の合計 約 60(accuracy.py 11・test_accuracy.py 9・AGENTS.md 19・README.txt 11・home/README.txt 8)。実コードの付け替えは **accuracy.py の子プロセス起動**(夜の自動測定)。
- **旧い起動用の転送 4 本**(tx_worker・live_excite・live_align・live_tx_worker): 実コードの旧いパス参照は**ほぼ無い**(test_worker.py:550 の 1 件・tx_engines.py:194 のコメント)。本体は新しい場所から起動される。

## 付け替えの順番の提案(この下調べからの見込み・未検証)
1. テストの差し替え先を持ち主へ(`patch.object(ed_jobs, …)` → `doc_jobs`/`rerun`/`recognize` など)。`S.名前` の受け付けは変えない
2. `accuracy.py` の子プロセス起動を `src/eval/tools/eval_X.py` へ。文書 2 つ(editor の AGENTS・README、home の README)の旧いコマンドを書き換え
3. `test_worker.py:550`(旧い tx_worker のパスで起動するテスト)を消すか、転送を残す判断
4. `dev/layer_map.py` の FORWARDERS と KNOWN から殻の行を消す・`test_names.py` と `data_ed_*_names.txt` を新しい持ち主の名前に直す
5. 殻を消す前に、起動中の旧い入口(live_detect・live_archive・live_tx・worker_client)が使う旧いパスが無いことを確かめる(転送を消す = 古い入口が起動し直せなくなる)

## 残った不確かさ
- 件数は grep の行数。コメント・docstring を含む。実コードの読み手の数は表より少ない。
- `common` の grep は語が他の意味でも使われるため、studio の件数は上限。
- `test_eval_*.py` が旧い `dev/eval_*.py` を使うかは未確認(新しいパスで読んでいるように見えた)。
- `friend-apps/*/members.json` の `ytt_core` は、ファイル名の言及か参照かを未確認。
