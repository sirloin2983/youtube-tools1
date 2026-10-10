状態(2026-10-10): RS7 の下調べ(Sonnet・medium)の報告(サブエージェントが本文で返した報告を、まとめ役が少し詰めて置いた)

# RS7 小さめの 6 項目(読むだけ)

## 1. B-1(case.json と案件の一覧の走査)
今の形:
- 案件の一覧はフォルダの走査ではなく 3 つの組み合わせ。`cases.snapshot`(`src/manage/cases/cases.py:301`)= スタジオ `data.json` の `videos`(`read_studio` :93)が背骨 + `app\cases.json`(`load_saved` :289。人の状態・メモ・最後に見えた紐づけ)+ `transcripts\*.json` の全読み(`txindex.load` :87。更新時刻のキャッシュ)
- 紐づけは毎回パスの一致で組み直す(`txindex._match` :103・`pick` :118)。パックは `txindex.pack_info`
- 文書の一覧 `doclist.list_transcripts`(:59)は `store._tids()` から
- 案件の根は `placement.case_root`(placement.py:79)。持ち主の印は `作業用\.studio-id`(`ytt/names.py:22`。中身は videoId だけ)
- data.json に無い案件は一覧に出ない

最小の案:
- `<案件>\作業用\case.json` に素性だけ: `{schema:"youtube-tools-case/v1", id, media:{kind, videoId|path}, title, channel, createdAt, madeBy}`。`.studio-id` は残し、読む側は両方を見る
- 書き手は ② の `placement.ensure_case(...)`(新設)。`write_result`(:231)の直前に冪等で(無いときだけ原子的に)
- 状態・メモは ④ の `cases.json` のまま(書き手が分かれて競合しない)
- 既存の案件は遅延の後付け(`snapshot` が case.json の無い案件に `ensure_case`。フォルダがあり印が合うときだけ)
- 一覧の走査: outDir の直下を scandir して `作業用\case.json`(無ければ `.studio-id`)→ data.json の videos と videoId で突き合わせ → data.json に無い物は「スタジオに無い案件」として足す。一覧 API の形は変えない
- 注意: 動画ファイルの案件(友人の動画)の根は outDir の外。索引は autorun-runs.jsonl の resultPath か作り直せる `app\case-roots.json`(未決)

テスト: `test_cases.py`・`test_run.py`・`test_launch.py`・`test_layering`。新しく `src/flow/tests/test_placement.py`。

## 2. バックアップが `作業用\runs\` を写さない
- バックアップの対象は作業データの根だけ(`plan(source)` `src/manage/keep/backup.py:109`)。`<outDir>\<題名>\作業用\` は根の外なので、runs に限らず `.clip.json`・`.edit.json`・鍵も写していない。outDir 未設定で `studio\exports\` のときは `SKIP_DIRS` の "exports"(:38)で落ちる
- 直す案(約 30〜40 行): `plan_cases(out_dir)` = 各案件の `作業用\` から `*.json` と `.studio-id` だけ(動画・パックは写さない)。写し先 `youtube-tools-data\cases\<題名>\作業用\...`。`run_once`(:170)で連結・`Backup` に out_dir を渡す(`launch.py:858`)・`latest_change`(:136)にも・`restore_once`(:330)に `--cases-to <outDir>`(足さないなら文書に「手で戻す」)
- テスト: `test_backup.py`。文書 `docs/spec/data-location.md`

## 3. 不具合: 入口に頼むと `artifacts`・`packs` が空
原因: `delegate`(`src/app/cli.py:367`)は `pub["docs"]` から packs を組むが、入口の `Run.public()`(`src/flow/run.py:257`)は `packs`・`newDocs` を返さない。さらに文書単位の実行(DOC_MODE。CLI の `start-docs`)では `run.docs` に文書が入らない(足すのは run.py:669・:831・:976 の 3 か所だけ。`_doc_pack` :888・`_doc_transcribe` に無い)。入口なしの `run_local` は回避策(`run.docs.append(run.doc_id)`・`list(run.packs)`)を持つ。
- 案 A(約 5 行): `Run.public()` に `packs`・`newDocs`、文書単位の実行でも `run.doc_id` を `run.docs` に(cli の回避策を run へ)。結果の束 `placement.outputs`(:156)の transcribe も直る(推測)
- 案 B: cli だけで resultPath の束を読む
- テスト: `test_run.py`・`test_cli.py`・`test_autorun.py`

## 4. 動画ファイルを入口に頼む口
- `AutoRunner.start_file`(`src/home/autorun.py:507`)は友人の依頼(`human/friend/intake.py:761`)とライブの書き出しのあと(`flow/live_export.py:1125`)から呼ばれる。mode は `FLOW_MODES["file"][flow]`(`file` = 文字起こしだけ・`file_auto` = 文字起こし → パック → 届ける。run.py:44-53)
- HTTP の口が無い(`_post_autorun` launch.py:723 は estimate・start-new・start-docs・start・cancel だけ)ので CLI は 文字起こし → start-docs の 2 段。3 の不具合はこの文書単位の実行から来る
- 最小: `POST /api/autorun/start-file`(約 12 行。body `{path, title?, streamer?, flow?, force?, deliver?}`)・`start_file` に force の引数。届けるを外す指定が要る(CLI の run_local は外している)。CLI は 1 回の start-file にでき、`_portal_transcribe` と `find_doc` の分岐が消える
- テスト: `test_launch.py`・`test_autorun.py`・`test_cli.py`

## 5. 入口の起動し直しと `.flow.lock`
今の時系列:
1. 「起動し直す」で `restart_self`(launch.py:925-950)が新しい入口を `--port <同じ> --wait-port --no-open` で起動(`restart.py:44-53`)、0.3 秒後に古い入口が `request_shutdown`
2. 新しい入口の `main`(:1273)は `wait_port_free` で最大 30 秒待つ。古い入口の後始末は子 1 つにつき最大 8 秒
3. 古い入口の finally は teardown → shutdown → remove_runtime → `placement.release` → `server_close`
4. 30 秒を超えると新しい入口は「次の番号で起動します」(:1274)
5. `make_server`(:1147): 古い入口がまだ ping に答える → 「すでに起動しています」で `return 0`(画面は戻らない)/ 答えないがソケットが残る → 8701 に bind
6. 8701 のとき `placement.acquire(port)`(:1286)は古い pid が生きていてポートも開いていると `LockBusy`。try の外なので**トレースバックで落ちる**。新しい入口はどこにも立たない

直す案:
- 案 A(約 20 行・推奨): `--wait-pid <古い pid>` を足して、古い入口が終わるまで 60〜90 秒待つ。期限が来たら次の番号では起動せず、読める文で非 0 で終わる(次の番号に逃げると「1 つの作業データに ② は 1 つ」と矛盾)。`LockBusy` も読める文に
- 案 B(約 25 行): lock の引き継ぎ(handoff)。レースの検討が要る
- テスト: `test_restart.py`・`test_launch.py`

## 6. `flow/diar.py` の `voice_rows` の別名
- 定義 `src/flow/diar.py:135-138`(`_calc.voice_groups(segs, key)` を返すだけ)。呼び出しは `human/proof/speakers.py` の :634 `recognize_voices`・:718 `voice_learn_plan`。同類に `voice_row_min`(:140)
- 無くす案: `match_known_voices`(diar.py:160)の入口を `segs, key` にして中で `voice_groups` → `embed` → 照合(② のつなぎ)/ `diar.learn_groups(segs, who, accept)` を新設(約 20 行。短い行と混声を ② が数え、校正済みか・音のメモの判定は ③ の `accept`)・speakers.py:707-718 のループを移し `voice_row_min` も消す。`# flow: alias ok` を消す
- テスト: `test_layering`・`src/editor/tests/test_voices.py`・`test_diarize.py`・`src/human/proof/tests/`。新しく `src/flow/tests/test_diar.py`

## 所見(推測)
3 と 4 は組で直すと小さい(start-file を足し、文書単位の実行にも docs/packs を持たせる)。5 は友人の PC の起動し直しを安定させる。2 は B-2 の前に必ず。1 と 6 は独立。
