# HANDOVER — 次のセッションへの引き継ぎ(2026-10-10。役割で組み直す計画 = RS0・RS1 済み・RS2 は RS2-0〜7 済み・次は RS2-8)

セッションを切り替えるたびに上書きする。全体の計画と進捗は `plan/index.html`(データ `plan/data.js`)、文書の索引は `docs/ROADMAP.md`、経緯は `docs/WORKLOG.md`

## いまの状態
- 作業フォルダは `C:\dev\youtube-tools`(GitHub: https://github.com/sirloin2983/youtube-tools1)。**push はユーザーが `push.bat`**(RS2 のコミットはまだ push されていない)
- **版**: 入口 0.54.1・スタジオ 0.26.0・編集 0.67.0・cut2resolve 0.23.0・録画 0.3.3・ui-kit v25(RS2 の移動では版を上げていない = 操作は変わらない)
- **役割で組み直す計画 `plan/role-restructure.md`**: 層 `src/ytt` ← `pipeline` ← `human` ← `manage` ← `eval`(`app` は全部を使ってよい)。向きは `dev/tests/test_layering.py`(違反は `dev/layer_map.py` の KNOWN。減らすだけ。**今 66 件**)
- **RS2 の決定(ユーザー確認済み。8 節「RS2 の手順と決定」)**: 範囲 = ed_jobs の分割 + tx_engines・roster / ジョブの表は ytt/jobs / パスは一時の口 txenv / 疑似は ed_jobs の中だけを口に
- **RS2-0〜7 済み(10-10)**:
  - `src/ytt/modfwd.py` = 名前の転送(serve の名前の受付と ed_jobs の転送。読む・書く・消すを本物の持ち主へ)。`src/editor/tests/test_names.py` が「部品どうしで名前が重ならない・RS2 の前の ed_jobs の名前 `data_ed_jobs_names.txt` が S と ed_jobs で読める・移した名前を ed_jobs に残さない」を守る
  - `src/ytt/jobs.py` = ジョブの表・待機列・ワーカーの繰り返し・取り消し・`register`・`configure`(編集の種類は serve が登録)。`src/ytt/errors.py` = ApiError
  - `src/pipeline/transcribe/`: `tx_engines`・`roster`(RS2-3)・`txbase`(認識の決まり)・`txenv`(パスの一時の口。RS3 で消す)・`backend`(疑似の差し込み口)・`postproc`(RS2-4)・`records`(RS2-5)・`worker_client`(RS2-6)・`recognize`(RS2-7)。テストは同じフォルダの `tests/`(serve なしで読める・numpy などを読まない)
  - `src/eval/fake/fake_asr.py` = 疑似の認識(serve の selector が `ed_state.backend_name()` で選ぶ)
  - serve が登録する口: `jobs.register/configure`・`txenv.register`・`backend.set_selector`・`records.set_dict_inputs`(辞書の版の入力)・`recognize.set_head_stripper`(範囲の行の名前外し = ed_fill)・`worker_client.WORKER_SCRIPT/WORKER_LOG`
  - **ed_jobs は 1,045 行 = 文書の側だけ**(run_job・run_redo・run_retranscribe と反映の関数・validate_*・record_rerun・resplit_doc・public_job・subtitle_settings 群・split_terms・glossary_of・stream_context・dict_pairs・dict_learned・head_stripper・_rows_to_doc・_doc_fields・転送の口)
- テスト(RS2-4 のあと): 編集の単体 602・層・lint 0・関連の単体 OK。e2e は編集 15 本・pipeline・autorun・portal・datadir・keymap OK。**RS2-5〜7 のあと(サブエージェントが動いていない状態)の一式**: 編集の単体 602・層・lint 0・transcribe のテスト・eval_* OK、e2e は編集 15 本(e2e_ui_handoff は前から)・pipeline・autorun・portal・datadir・live_studio 189/189・live OK

## 次(RS2-8。下調べ済み。相談の区切り = 手順をユーザーに見せてから)
- **8a**: pipeline の層の読み手を本物の持ち主へ(ed_speakers: ytt/jobs の名前・`ed_jobs.extract_audio` → recognize・SPK_FLAGS → txbase(dev/eval_asr が `S.SPK_FLAGS` を読むので ed_state に別名)/ ed_fill: Cancelled → ytt/jobs・load_model/filter_kwargs → worker_client / ed_llm: Cancelled・IN_WORKER・WORKER・load_model → worker_client・stream_context → roster へ移す(studio_stream は txenv の鍵)/ ed_retime: read_words → records)。`valid_model`・`pio` を txenv の鍵へ。split_terms も roster へ
- **8b**: `git mv src/editor/ed_jobs.py src/human/proof/doc_jobs.py`(丸ごと)+ 新しい空の `src/editor/ed_jobs.py`(_MOVED・_add_moved・modfwd.install だけ。**層は human** = 読んでいる ed_alt・ed_store・ed_misc・ed_relink・ed_drill・ed_evalbatch など 9 つは RS5 まで転送のまま)。KNOWN: (ed_jobs, ed_alt/ed_learn/ed_store/ed_ytcap) が消え、(ed_jobs, ed_state/ed_evalbatch/ed_relink) は (doc_jobs, …) へ付け替え → **62**。読むのは `from human.proof import doc_jobs`(裸の import は test_layering が落とす)。modfwd.install は最後
- **8c**: doc_jobs から `rerun.py` を割る(rerun → doc_jobs の一方向。rerun は ed_state を読まない = validate_*・redo_spec は doc_jobs)。行き先の一覧は WORKLOG の RS2-5〜7 の記録
- **8d**: ed_evalbatch・ed_relink・ed_state を serve が登録する口に → **59**。口には**モジュールを登録**(test_evalbatch が `patch.object(EB, "eb_redo_skip_at_start")` を使う)。呼ぶ順 norm → autodiar → job_done を保つ
- そのあと: RS2 の結果を plan(8 節)・data.js(RS2 done)・AGENTS(editor の構成)に書き、公開ページを出し直す。ユーザーの確認 = 校正の画面が壊れていないか 10 分(data.js の RS2 の user 欄)
- RS3・RS4 は RS2 と触るファイルを分ければ並列にできる

## 次のセッションに貼る指示文
「AGENTS.md → plan/data.js → docs/HANDOVER.md → docs/WORKLOG.md の末尾 3 件 → git status・git log -15 を見て。役割で組み直す計画(plan/role-restructure.md)の RS2 は RS2-0〜7 まで済み。HANDOVER の『次』のとおり RS2-8(ed_jobs の残り = 文書の側を human/proof/doc_jobs.py・rerun.py へ、ed_jobs を空の転送に)を、移す前に手順を見せて相談しながら進めて。サブエージェントは適切に使う(実装は別の作業フォルダ・e2e はまとめ役が 1 本ずつ)。重要な判断は Fable と相談。」

## 注意(引き継ぐこと)
- **移した名前を ed_jobs・ed_state に `from x import y` で別名として残さない**(S.X の差し替えが別名に当たって本体に効かない)。移した先のモジュールは serve の `_ED_MODULES` に ed_jobs より前・ed_jobs の `_MOVED` にも足す。新しいモジュールは名前を import せずモジュールを import する(`modfwd.duplicates` が 0 件であること)
- ed_jobs に残る関数は移した名前を `postproc.名前` のようにモジュール名つきで呼ぶ(ローカル変数で隠さない = RS2-7 で `recognize` という変数が新しいモジュールを隠した)
- **e2e_eval_set**: 一式の中で 2 回だけ「文字起こしを 20 秒待つ」所で落ちた。どちらもサブエージェントが別の作業フォルダで重いテストを流していた間で、動いていない時の一式・単独・続けての 6 回は OK = PC の負荷と見る。**サブエージェントの実装と e2e を同時に流すと待ちのあるテストが揺れる**ので、最後の確かめの一式はサブエージェントが止まってから
- 全体を続けて流したときだけ揺れる: `e2e_live_studio` の 2 件・`test_live_archive` の 1 件(単独で OK)。**前から落ちている**: `e2e_window`([7-1] #count)・`e2e_ui_handoff`(無くなった「3 パック」のタブ)
- **unittest に `PYTHONIOENCODING=utf-8` を付けない**。e2e には付けて 1 本ずつ。`test_mount`・契約テストは単独で
- サブエージェントの作業フォルダは古いコミットから始まることがある → 最初に `git merge --ff-only main`。取り込みは cherry-pick
- **同じ作業フォルダを別のセッションも使う**(10-10 に「今日の報告と資料更新」のセッションが main に直接コミットし、こちらの未コミットの文書の直しを一緒に入れた。WORKLOG に RS2-4 の記録が 2 つある)。コミットの前に `git status`・`git diff --cached --stat` を見て、自分の変えたファイルだけを add する
- ファイルは差分で直す(多くは CRLF。`sed -i` 禁止)。plan/data.js を直したら公開ページ(Artifact)も出し直す
- 入口が起動中の間はコードを変えても古いまま動く。ユーザーに「すべて終了 → start.bat」を頼む(RS1 の本物の 1 本の確認もまだ)
