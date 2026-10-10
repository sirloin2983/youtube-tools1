# HANDOVER — 次のセッションへの引き継ぎ(2026-10-10 午後。役割で組み直す計画 = RS0〜RS4 済み・向きの違反 0。次は RS5)

セッションを切り替えるたびに上書きする。全体の計画と進捗は `plan/index.html`(データ `plan/data.js`)、文書の索引は `docs/ROADMAP.md`、経緯は `docs/WORKLOG.md`

## いまの状態
- 作業フォルダは `C:\dev\youtube-tools`(GitHub: https://github.com/sirloin2983/youtube-tools1)。**push はユーザーが `push.bat`**(RS2〜RS4 のコミットはまだ push されていない)
- **版**: 入口 **0.55.0**(あとから解析を消した)・スタジオ 0.26.0・編集 **0.69.0**(D2 = 進行度と校正の目標を消した)・cut2resolve 0.23.0・録画 0.3.3・ui-kit v25
- **役割で組み直す計画 `plan/role-restructure.md`**: 層 `src/ytt` ← `pipeline` ← `human` ← `manage` ← `eval`(`app` は全部を使ってよい)。向きは `dev/tests/test_layering.py`。**違反 0・`KNOWN_MAX = 0`**(`dev/layer_map.py`)= 新しい違反は 1 件でも落ちる
- **RS3・RS4 済み(10-10 午後)**: 段の結果は計画 8 節と WORKLOG の最後。ファイルの今の場所は `dev/layer_map.py`(FILES・DIRS)と AGENTS.md の表
  - 転送だけの殻(RS5 で消す): `src/editor/` の ed_jobs・ed_speakers・ed_store・ed_learn・ed_alt・ed_ytcap・ed_retime・ed_relink・ed_misc、`src/studio/common.py`(持つ名前は `_MOVED`・`_moved_owner`・`_add_moved` と common の起動の小物 11 個)
  - 旧パスの起動用の転送(runpy。RS5 で消す): `src/editor/tx_worker.py`・`src/home/live_excite_worker.py`・`live_align_worker.py`・`live_tx_worker.py`・`dev/eval_*.py` 13 本
  - app に残る物: editor の serve・ed_state・ed_media・ed_thumb・画面、home の launch・live・autorun・portal・prefs・mount・appwindow・settings、studio の serve・common(殻)・handoff・画面
- serve が登録する口: `jobs.register/configure`・`backend.set_selector`・`records.set_dict_inputs`・`recognize.set_head_stripper`・`doc_jobs.set_hooks`(redo_skip・redo_fill・norm_after)+ `check_hooks`・`ytt.settings.register_patch_key`・`speakers.set_context_namer` + `check_context_namer`・`worker_client.FAKES_MODULE`・殻への `_add_moved`(ed_store ← doclist・ed_learn ← metrics・ed_alt ← fake_asr・ed_relink ← folders)
- 測る道具は `src/eval/tools/`(`py -3.10 src/eval/tools/eval_asr.py stored` など。旧 `dev/eval_*.py` も動く)。eval_marks に `--analyze-missing [--wait] [--limit N]` = 未解析の友人の配信の解析を動いているスタジオに頼む(「あとから解析」の代わり)
- 決定: `plan/decisions.md` 3-23〜3-25 は確認済み。**3-26(eval_marks が画面の HTML の meta から合言葉を読む)は仮で決めた = ユーザーの確認待ち**。一時的な案(後の段で直る形)は確認に出さず AI が決めてよい(ユーザー指示)
- **進め方(ユーザー決定 10-10)**: 段ごとには unittest・lint・層の検査だけ・e2e は画面を変えた所の近い 1〜2 本・e2e の一式は RS の終わりに 1 回・文書(AGENTS・計画・data.js)は RS ごとに 1 回・コミットは少し大きめ
- テスト(RS3・RS4 の終わり): 単体一式・契約・test_mount・lint 0・e2e の一式 31 本 OK(前から落ちている e2e_window・e2e_ui_handoff の 2 本を除く)

## 次
1. **RS5**(計画 7・8 節と data.js の RS5): app を薄く(配線だけ)・殻 10 本と旧パスの転送を消す(テストの `import ed_*`・`common.X` の差し替えを持ち主へ付け替えてから)・版 1 つ・設定 1 ファイル・旧い URL の転送・「確認してから届ける」L1・L2(友人のアプリの更新と一緒に ① へ読み替え = 決定 3-25 の h)・疑似の `if` を登録の口に(studio_env.fake・backend_name など)・ytt_core の旧名の転送を消す。先に下調べ(読むだけ 2〜3 体)→ Fable と段の並び → 実装(別の作業フォルダ・同時 4 本まで)
2. ユーザーの確認(急がない): 3-26 / 入口を「すべて終了 → start.bat」で起動し直して(配信の無い時に)校正の画面・話者判別(覚えた声で名前が付くか)・まとめて実行で本物の 1 本 / `py -3.10 src/eval/tools/eval_marks.py --analyze-missing --wait` を 1 回
- 別件(タスクの札にした): `worker_client._probe_gpu` の判定が常に偽(画面の GPU 表示だけ。AMD の PC では実害なし)

## 注意(引き継ぐこと)
- **移した名前を別の部品に `from x import y` で別名として残さない**(S.X の差し替えが別名に当たって本体に効かない)。例外は差し替えない定数・純粋な関数(`# lint: keep 別名`)。移した先のモジュールは serve の `_ED_MODULES` に旧い持ち主の位置(殻は並べない)。`modfwd.duplicates` 0 件
- 読む側は `モジュール.名前` で呼ぶたびに読む。口に関数を値で登録しない(lambda の中で呼ぶたびに読む)。口は登録されていなければ RuntimeError + serve が登録の直後に check
- 殻に新しい名前を書かない。`src/pipeline/transcribe/tests` に `__init__.py` は無い = discover ではなくファイルを並べて流す。test_names を単独で流すときは `PYTHONPATH=src/editor/tests`
- **サブエージェントの実装と e2e を同時に流すと待ちのあるテストが揺れる**。最後の一式はサブエージェントが止まってから
- **前から落ちている**: `e2e_window`([7-1] = スタジオの ② から解析の設定の欄が無くなった)・`e2e_ui_handoff`(無くなった「3 パック」のタブ)。全体を続けて流したときだけ揺れる: `e2e_live_studio` の 1〜2 件・`test_live_archive` の 1 件(単独で OK)
- **unittest に `PYTHONIOENCODING=utf-8` を付けない**。e2e には付けて 1 本ずつ。`test_mount`・契約テストは単独で
- worktree のサブエージェント: 最初に `git merge --ff-only main`・「git mv だけ → 付け替え → 共有ファイル」の 3 コミット・まとめ役が cherry-pick(serve.py・layer_map・test_names の衝突はまとめ役が両方を合わせて解く)。main が進んだら SendMessage で知らせて rebase を頼む(先に終わって渡してくる体もいる)
- **同じ作業フォルダを別のセッションも使う**。コミットの前に `git status`・`git diff --cached --stat` を見て、自分の変えたファイルだけを add する
- ファイルは差分で直す(多くは CRLF。`sed -i` 禁止)。plan/data.js を直したら公開ページ(Artifact)も出し直す
- 入口が起動中の間はコードを変えても古いまま動く。ユーザーに「すべて終了 → start.bat」を頼む。**ライブの部品を移したので配信中に入口を落とさない**(起動中の古い入口が子を起こしても旧パスの転送で動く)

## 次のセッションに貼る指示文
「AGENTS.md → plan/data.js → docs/HANDOVER.md → docs/WORKLOG.md の末尾 3 件 → git status・git log -15 を見て。役割で組み直す計画(plan/role-restructure.md)は RS4 まで済み・向きの違反 0。HANDOVER の『次』のとおり RS5 を、まず下調べ(読むだけのサブエージェント)→ Fable と段の並び → 実装(別の作業フォルダ)の順で進めて。決めることが出たら decisions に並べて、一時的な案は聞かずに決めてよい。進め方は AGENTS.md の e2e と文書の決まり(段ごとは unittest・lint・層だけ・e2e 一式と文書は RS の終わりに 1 回)。重要な判断は Fable と相談。」
