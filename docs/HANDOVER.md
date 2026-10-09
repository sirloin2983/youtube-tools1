# HANDOVER — 次のセッションへの引き継ぎ(2026-10-10 朝。役割で組み直す計画 = RS0・RS1・RS2 済み・RS3 は下ごしらえ 0A・0B まで。次はユーザーの確認 → RS3 の段 1)

セッションを切り替えるたびに上書きする。全体の計画と進捗は `plan/index.html`(データ `plan/data.js`)、文書の索引は `docs/ROADMAP.md`、経緯は `docs/WORKLOG.md`

## いまの状態
- 作業フォルダは `C:\dev\youtube-tools`(GitHub: https://github.com/sirloin2983/youtube-tools1)。**push はユーザーが `push.bat`**(RS2・RS3-0 のコミットはまだ push されていない)
- **版**: 入口 0.54.1・スタジオ 0.26.0・編集 0.67.0・cut2resolve 0.23.0・録画 0.3.3・ui-kit v25(移動では版を上げていない。動きが変わったのは覚えた声の置き場所の直し(RS2-9a)と、編集の起動の警告 1 つ(RS3-0A)だけ)
- **役割で組み直す計画 `plan/role-restructure.md`**: 層 `src/ytt` ← `pipeline` ← `human` ← `manage` ← `eval`(`app` は全部を使ってよい)。向きは `dev/tests/test_layering.py`(違反は `dev/layer_map.py` の KNOWN。減らすだけ。**今 25 件**)
- **RS2 済み(10-10。RS2-0〜9)**: 編集の認識の側は `src/pipeline/transcribe/`(tx_engines・roster・txbase・backend・postproc・records・worker_client・recognize・diarize・fill・llm・retime・worker.py)、文書の側は `src/human/proof/`(doc_jobs・rerun・speakers)。殻(転送だけ・RS5 で消す)= `src/editor/ed_jobs.py`・`ed_speakers.py`、起動用の転送 = `src/editor/tx_worker.py`
- **RS3 の下ごしらえ済み(10-10 朝。0A・0B)**: 
  - 0A: 一時の口 txenv は消えた。作業データの置き場所と版は `src/ytt/workdata.py` の変数(`S.TX_DIR = …` は modfwd で届く)・動画音声の小道具は `ytt/tools`・GPU と部品・worker_fake・valid_model は `worker_client`・スタジオの data.json の読み口は `ytt/studiodata.py`・名簿の場所は `roster.ROSTER`・pio は廃止
  - 0B: 層の表(autorun・live は app・live_failures は pipeline)・継ぎ目(`defaults=`・`discard=`・`pack_info=`・`fsio.append_line`・`pipeline/runlog.py`・`schemas.now_ms`)・死んだフック 2 つを消した
- **RS3・RS4 の下調べと段の案**: `docs/design/rs3-rs4-survey-2026-10-10/`(plan_order.md = 段の並びと決めること 21 項目・survey_*.md = 報告そのまま)。要約は計画の 8 節「RS3・RS4 の手順の案」と `plan/decisions.md` 3-25
- serve が登録する口: `jobs.register/configure`・`backend.set_selector`・`records.set_dict_inputs`・`recognize.set_head_stripper`・`doc_jobs.set_hooks` + `check_hooks`・`speakers.set_context_namer` + `check_context_namer`・`worker_client.FAKES_MODULE`。置き場所は `workdata` の変数(登録の口ではない)
- 仮決め(**まだ確認していない**): `plan/decisions.md` の 3-23(RS2-8)・3-24(RS2-9)・3-25(RS3・RS4。うち RS3-f〜m は確かめてから進める)
- テスト(RS3-0 のあと・サブエージェントが止まってから): WORKLOG の最後の記録

## 次
1. **ユーザーの確認**: decisions 3-25(とくに確かめてから進める RS3-f ed_evalaudio を消す・g A/B と保管・h 確認してから届ける・i あとから解析・j 進行度・k 道具のパス・l 見積もり・m 入口の起動し直し)と 3-23・3-24。入口を「すべて終了 → start.bat」で起動し直して、校正の画面・話者判別(覚えた声で名前が付くか)・まとめて実行で本物の 1 本(RS1・RS2・RS3-0 の分。配信の無い時に)
2. **RS3 の段 1**: 設定の口(ed_learn の 28-128)と評価用の判定(ed_relink の 506-566)を ytt/settings へ(26 → 21 の見込みだったが、0A で 1 つ先に減っている)
3. **波 1**(並列 4 本まで): ed_store の分割・pipeline_io と resolve_export・ed_learn の分割・ライブの葉と転送 3 つ・keep と ops・cases と friend・スタジオの common の分解 → **波 2** → **RS4**(ed_drill・ed_evalbatch・ed_evalaudio)→ まとめ。表は plan_order.md
- 別件(タスクの札にした): `worker_client._probe_gpu`(0A で ed_state から移った)の判定が常に偽(画面の GPU 表示だけ。AMD の PC では実害なし)

## 注意(引き継ぐこと)
- **移した名前を別の部品に `from x import y` で別名として残さない**(S.X の差し替えが別名に当たって本体に効かない)。例外は差し替えない定数・純粋な関数(`# lint: keep 別名`)。移した先のモジュールは serve の `_ED_MODULES` に旧い持ち主より前。新しいモジュールは名前を import せずモジュールを import する(`modfwd.duplicates` が 0 件)
- 読む側は `モジュール.名前` で呼ぶたびに読む(ローカル変数でモジュール名を隠さない)。口に関数を値で登録しない(lambda の中で呼ぶたびにモジュールの属性を読む)。口は登録されていなければ RuntimeError + serve が登録の直後に check
- 殻(ed_jobs・ed_speakers)に新しい名前を書かない。`src/pipeline/transcribe/tests` に `__init__.py` は無い = discover ではなくファイルを並べて流す。test_names を単独で流すときは `PYTHONPATH=src/editor/tests`
- **サブエージェントの実装と e2e を同時に流すと待ちのあるテストが揺れる**。最後の確かめの一式はサブエージェントが止まってから。パックの単体も一式の中で 1 回だけ 1 件落ちたことがある(続けて 3 回 OK)
- **前から落ちている**: `e2e_window`([7-1] #count = スタジオの ② から解析の設定の欄が無くなった)・`e2e_ui_handoff`(無くなった「3 パック」のタブ)。全体を続けて流したときだけ揺れる: `e2e_live_studio` の 1〜2 件・`test_live_archive` の 1 件(単独で OK)
- **unittest に `PYTHONIOENCODING=utf-8` を付けない**。e2e には付けて 1 本ずつ。`test_mount`・契約テストは単独で
- サブエージェントの作業フォルダは古いコミットから始まることがある → 最初に `git merge --ff-only main`。取り込みは cherry-pick。移動は「移動だけ」と「付け替え・転送」のコミットに分ける。並列の実装役は、後から入る側が `git rebase main` で当て直してから渡す。共有ファイル(serve の `_ED_MODULES`・layer_map・AGENTS・data.js)はまとめ役が最後に直す
- `.claude/worktrees/agent-*` に今夜のサブエージェントの作業フォルダが残っている(中身は全部 main に取り込み済み)。消すときはユーザーに確認
- **同じ作業フォルダを別のセッションも使う**。コミットの前に `git status`・`git diff --cached --stat` を見て、自分の変えたファイルだけを add する
- ファイルは差分で直す(多くは CRLF。`sed -i` 禁止)。plan/data.js を直したら公開ページ(Artifact)も出し直す
- 入口が起動中の間はコードを変えても古いまま動く。ユーザーに「すべて終了 → start.bat」を頼む。起動中の古い入口がワーカーを起動し直しても、旧い場所の転送で新しいワーカーが動く。ライブの部品を移す段(波 1 の RS3-1)のあとは、配信中に入口を落とさない

## 次のセッションに貼る指示文
「AGENTS.md → plan/data.js → docs/HANDOVER.md → docs/WORKLOG.md の末尾 3 件 → git status・git log -15 を見て。役割で組み直す計画(plan/role-restructure.md)は RS2 まで済み・RS3 は下ごしらえ 0A・0B まで。docs/design/rs3-rs4-survey-2026-10-10/plan_order.md と plan/decisions.md 3-25 の決めることをユーザーに確認してから、RS3 の段 1(設定の口と評価用の判定を ytt/settings へ)→ 波 1 へ進めて。サブエージェントは適切に使う(実装は別の作業フォルダ・e2e はまとめ役が 1 本ずつ)。重要な判断は Fable と相談。」
