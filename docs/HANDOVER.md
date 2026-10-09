# HANDOVER — 次のセッションへの引き継ぎ(2026-10-10 早朝。役割で組み直す計画 = RS0・RS1・RS2 済み・次は RS2-9 → RS3・RS4)

セッションを切り替えるたびに上書きする。全体の計画と進捗は `plan/index.html`(データ `plan/data.js`)、文書の索引は `docs/ROADMAP.md`、経緯は `docs/WORKLOG.md`

## いまの状態
- 作業フォルダは `C:\dev\youtube-tools`(GitHub: https://github.com/sirloin2983/youtube-tools1)。**push はユーザーが `push.bat`**(RS2 のコミットはまだ push されていない)
- **版**: 入口 0.54.1・スタジオ 0.26.0・編集 0.67.0・cut2resolve 0.23.0・録画 0.3.3・ui-kit v25(RS2 の移動では版を上げていない = 操作は変わらない)
- **役割で組み直す計画 `plan/role-restructure.md`**: 層 `src/ytt` ← `pipeline` ← `human` ← `manage` ← `eval`(`app` は全部を使ってよい)。向きは `dev/tests/test_layering.py`(違反は `dev/layer_map.py` の KNOWN。減らすだけ。**今 59 件**)
- **RS2 済み(10-10。RS2-0〜8)**:
  - `src/ytt/modfwd.py` = 名前の転送(serve の名前の受付と殻の ed_jobs)。`src/editor/tests/test_names.py` が名前の重なり 0・旧い ed_jobs の名前(`data_ed_jobs_names.txt`)が S と ed_jobs で読める・殻が持つ名前は 3 つだけ、を守る
  - `src/ytt/jobs.py` = ジョブの表・待機列・取り消し・`register`・`configure`。`src/ytt/errors.py` = ApiError
  - `src/pipeline/transcribe/`: tx_engines・roster(stream_context・split_terms も)・txbase(SPK_FLAGS も)・txenv(パスと外の道具の一時の口。鍵 16 個。RS3 で ytt/settings に)・backend(疑似の差し込み口)・postproc・records・worker_client・recognize(transcribe_rows も)
  - `src/human/proof/doc_jobs.py`(文字起こしのジョブ run_job と文書づくり・受付 validate_*・redo_spec・public_job・字幕の文字数・resplit_doc・dict_pairs・口 set_hooks)・`rerun.py`(再認識と疑わしい所の本体と反映・record_rerun)。向きは rerun → doc_jobs だけ
  - `src/editor/ed_jobs.py` = 転送だけの殻(35 行。RS5 で消す)。`src/eval/fake/fake_asr.py` = 疑似の認識
  - serve が登録する口: `jobs.register/configure`・`txenv.register`・`backend.set_selector`・`records.set_dict_inputs`・`recognize.set_head_stripper`・`worker_client.WORKER_SCRIPT/WORKER_LOG`・`doc_jobs.set_hooks` + `check_hooks`
  - 仮決め(**まだ確認していない**): `plan/decisions.md` の 3-23(RS2-8-a〜g)
- テスト(RS2-8 のあと・サブエージェントが止まってから): 単体一式・test_mount・契約・lint 0 OK。e2e は編集 14 本・pipeline・datadir・autorun・portal・keymap・live・live_studio OK(e2e_ui_handoff は前から落ちている)

## 次(RS2-9。10-10 早朝に下調べ済み。要点は下)
- **tx_worker を `src/pipeline/transcribe/worker.py` へ**(スクリプトのパスで起動・絶対 import・serve を読まない)。旧い場所に runpy の転送スクリプト(起動中の古い入口用。recorder と同じ)。判別のワーカー側の本体(`_diarize_local`・`_embed_local`・DIAR_*)を新しい `pipeline/transcribe/diarize.py` へ同時に。GPU の調べ(setup_cuda_paths・_gpu_ready_local など)は ed_state から worker_client へ。疑似 install_fakes は `src/eval/fake/fake_worker.py`(serve が `worker_client` にモジュール名を登録 → 環境変数でワーカーへ)
- **ed_fill・ed_llm・ed_retime を pipeline/transcribe へ**(ed_state の読みは txenv の鍵・ed_retime の文書を読む API の包みは human/proof・alt_fold を下ろすか)
- **ed_speakers を判別(pipeline)と声の登録・文書への反映(human/proof)に分ける**
- そのあと RS3(② と ③)・RS4(④)。RS3 と RS4 は触るファイルを分ければ並列にできる

## 注意(引き継ぐこと)
- **移した名前を別の部品に `from x import y` で別名として残さない**(S.X の差し替えが別名に当たって本体に効かない)。移した先のモジュールは serve の `_ED_MODULES` に ed_jobs より前・殻の `_MOVED` にも足す。新しいモジュールは名前を import せずモジュールを import する(`modfwd.duplicates` が 0 件)
- 読む側は `モジュール.名前` で呼ぶたびに読む(ローカル変数でモジュール名を隠さない)。口に関数を値で登録しない(lambda の中で呼ぶたびにモジュールの属性を読む = テストの patch.object が届く)
- 殻の ed_jobs を読んでいる ed_alt・ed_drill・ed_evalbatch・ed_learn・ed_misc・ed_relink・ed_store・ed_ytcap は RS5 まで転送のまま。殻に新しい名前を書かない
- **サブエージェントの実装と e2e を同時に流すと待ちのあるテストが揺れる**。最後の確かめの一式はサブエージェントが止まってから
- 全体を続けて流したときだけ揺れる: `e2e_live_studio` の 2 件・`test_live_archive` の 1 件(単独で OK)。**前から落ちている**: `e2e_window`([7-1] #count)・`e2e_ui_handoff`(無くなった「3 パック」のタブ)
- **unittest に `PYTHONIOENCODING=utf-8` を付けない**。e2e には付けて 1 本ずつ。`test_mount`・契約テストは単独で
- サブエージェントの作業フォルダは古いコミットから始まることがある → 最初に `git merge --ff-only main`。取り込みは cherry-pick。転送を残す移動は「移動だけ」と「転送」のコミットに分ける
- **同じ作業フォルダを別のセッションも使う**。コミットの前に `git status`・`git diff --cached --stat` を見て、自分の変えたファイルだけを add する
- ファイルは差分で直す(多くは CRLF。`sed -i` 禁止)。plan/data.js を直したら公開ページ(Artifact)も出し直す
- 入口が起動中の間はコードを変えても古いまま動く。ユーザーに「すべて終了 → start.bat」を頼む(RS1・RS2 の本物の 1 本の確認もまだ)

## 次のセッションに貼る指示文
「AGENTS.md → plan/data.js → docs/HANDOVER.md → docs/WORKLOG.md の末尾 3 件 → git status・git log -15 を見て。役割で組み直す計画(plan/role-restructure.md)は RS2 まで済み。HANDOVER の『次』のとおり RS2-9(tx_worker・ed_fill・ed_llm・ed_retime を pipeline/transcribe へ・ed_speakers の分割)から進めて。サブエージェントは適切に使う(実装は別の作業フォルダ・e2e はまとめ役が 1 本ずつ)。重要な判断は Fable と相談。」
