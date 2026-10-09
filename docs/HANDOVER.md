# HANDOVER — 次のセッションへの引き継ぎ(2026-10-10 朝。役割で組み直す計画 = RS0・RS1・RS2 済み・次は RS3・RS4)

セッションを切り替えるたびに上書きする。全体の計画と進捗は `plan/index.html`(データ `plan/data.js`)、文書の索引は `docs/ROADMAP.md`、経緯は `docs/WORKLOG.md`

## いまの状態
- 作業フォルダは `C:\dev\youtube-tools`(GitHub: https://github.com/sirloin2983/youtube-tools1)。**push はユーザーが `push.bat`**(RS2 のコミットはまだ push されていない)
- **版**: 入口 0.54.1・スタジオ 0.26.0・編集 0.67.0・cut2resolve 0.23.0・録画 0.3.3・ui-kit v25(RS2 の移動では版を上げていない。覚えた声の置き場所の直し(RS2-9a)だけ動きが変わる)
- **役割で組み直す計画 `plan/role-restructure.md`**: 層 `src/ytt` ← `pipeline` ← `human` ← `manage` ← `eval`(`app` は全部を使ってよい)。向きは `dev/tests/test_layering.py`(違反は `dev/layer_map.py` の KNOWN。減らすだけ。**今 49 件**)
- **RS2 済み(10-10。RS2-0〜9)**:
  - `src/ytt/`: modfwd(名前の転送)・jobs(ジョブの表・待機列・登録の口)・errors・schemas(文書の形の小道具 TID_RE・OTHER_SPK_*・no_sub_row・blank_draft_row も)
  - `src/pipeline/transcribe/`: tx_engines・roster(stream_context・split_terms)・txbase(SPK_FLAGS・alt_fold・env_off)・txenv(パスと外の道具の一時の口。RS3 で ytt/settings に)・backend(疑似の差し込み口 = transcribe・diarize・embed)・postproc・records・worker_client(GPU の調べも)・recognize(transcribe_rows)・diarize・fill・llm・retime・**worker.py(認識ワーカー。スクリプトで起動)**
  - `src/human/proof/`: doc_jobs(文字起こしのジョブと文書づくり・受付・口 set_hooks)・rerun(再認識の本体と反映)・speakers(話者の文書の側・声の登録簿・口 set_context_namer)
  - `src/eval/fake/`: fake_asr(疑似の認識・判別・声の特徴)・fake_worker(ワーカーの疑似)
  - 殻(転送だけ・RS5 で消す): `src/editor/ed_jobs.py`・`src/editor/ed_speakers.py`。起動用の転送: `src/editor/tx_worker.py`。`src/editor/ed_retime.py` は文書を読む包みだけ(層 human。RS3 で human/proof へ)
  - serve が登録する口: `jobs.register/configure`・`txenv.register`・`backend.set_selector`・`records.set_dict_inputs`・`recognize.set_head_stripper`・`doc_jobs.set_hooks` + `check_hooks`・`speakers.set_context_namer` + `check_context_namer`・`worker_client.FAKES_MODULE`
  - 仮決め(**まだ確認していない**): `plan/decisions.md` の 3-23(RS2-8-a〜g)・3-24(RS2-9-a〜g)
- **動きが変わった所(1 つ)**: 覚えた声の置き場所(RS2-9a)。10-01 から入口の起動では存在しない `src/editor/voices` を見ていて、覚えた声で名前が付いていなかった → 作業データの `voices/voxceleb.json`(09-30)を読むように。次に話者判別したとき、覚えている人の名前が付くはず
- テスト(RS2-9 のあと・サブエージェントが止まってから): 単体一式・test_mount・契約・lint 0 OK。e2e は WORKLOG の RS2-9 の記録

## 次(RS3・RS4。並列にできる)
- **RS3**(② と ③): home の友人・案件・片付け・調子・ライブを行き先へ・スタジオの検索と手動マークを human へ・編集の校正の補助と学習(ed_store・ed_alt・ed_ytcap・ed_learn・ed_retime の包み)を human/proof へ・上書きの置き場。txenv を ytt/settings に置き換える。下調べから(行き先は `docs/design/role-restructure-map-2026-10-09.md`)
- **RS4**(④): ドリル・評価用フォルダ・A/B・精度の自動測定を eval/drill・dev/eval_* を eval/tools
- 別件(タスクの札にした): `ed_state._probe_gpu` の判定が常に偽(画面の GPU 表示だけ。AMD の PC では実害なし)

## 注意(引き継ぐこと)
- **移した名前を別の部品に `from x import y` で別名として残さない**(S.X の差し替えが別名に当たって本体に効かない)。例外は差し替えない定数・純粋な関数(`# lint: keep 別名`)。移した先のモジュールは serve の `_ED_MODULES` に旧い持ち主より前。新しいモジュールは名前を import せずモジュールを import する(`modfwd.duplicates` が 0 件)
- 読む側は `モジュール.名前` で呼ぶたびに読む(ローカル変数でモジュール名を隠さない)。口に関数を値で登録しない(lambda の中で呼ぶたびにモジュールの属性を読む = テストの patch.object が届く)。口は登録されていなければ RuntimeError + serve が登録の直後に check
- 殻(ed_jobs・ed_speakers)に新しい名前を書かない。殻を読んでいる ed_alt・ed_drill・ed_evalbatch・ed_learn・ed_misc・ed_relink・ed_store・ed_ytcap は RS5 まで転送のまま
- `src/pipeline/transcribe/tests` に `__init__.py` は無い = discover ではなくファイルを並べて流す。test_names を単独で流すときは `PYTHONPATH=src/editor/tests`
- **サブエージェントの実装と e2e を同時に流すと待ちのあるテストが揺れる**。最後の確かめの一式はサブエージェントが止まってから
- 全体を続けて流したときだけ揺れる: `e2e_live_studio` の 1〜2 件・`test_live_archive` の 1 件(単独で OK)。**前から落ちている**: `e2e_window`([7-1] #count)・`e2e_ui_handoff`(無くなった「3 パック」のタブ)
- **unittest に `PYTHONIOENCODING=utf-8` を付けない**。e2e には付けて 1 本ずつ。`test_mount`・契約テストは単独で
- サブエージェントの作業フォルダは古いコミットから始まることがある → 最初に `git merge --ff-only main`。取り込みは cherry-pick。移動は「移動だけ」と「付け替え・転送」のコミットに分ける。並列の実装役は、後から入る側が `git rebase main` で当て直してから渡す(線形のほうが取り込みやすい)
- **同じ作業フォルダを別のセッションも使う**。コミットの前に `git status`・`git diff --cached --stat` を見て、自分の変えたファイルだけを add する
- ファイルは差分で直す(多くは CRLF。`sed -i` 禁止)。plan/data.js を直したら公開ページ(Artifact)も出し直す
- 入口が起動中の間はコードを変えても古いまま動く。ユーザーに「すべて終了 → start.bat」を頼む(RS1・RS2 の本物の確認もまだ)。起動中の古い入口がワーカーを起動し直しても、旧い場所の転送で新しいワーカーが動く

## 次のセッションに貼る指示文
「AGENTS.md → plan/data.js → docs/HANDOVER.md → docs/WORKLOG.md の末尾 3 件 → git status・git log -15 を見て。役割で組み直す計画(plan/role-restructure.md)は RS2 まで済み(RS2-0〜9)。次は RS3(② と ③)と RS4(④)。下調べ(行き先・読み手・テストの差し替え)から始めて、手順を決めてから進めて。サブエージェントは適切に使う(実装は別の作業フォルダ・e2e はまとめ役が 1 本ずつ)。重要な判断は Fable と相談。」
