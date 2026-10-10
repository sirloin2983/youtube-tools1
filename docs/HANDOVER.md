# HANDOVER — 次のセッションへの引き継ぎ(2026-10-10 夕。役割で組み直す計画 = RS0〜RS5 済み・向きの違反 0・転送 0。次は RS6)

セッションを切り替えるたびに上書きする。全体の計画と進捗は `plan/index.html`(データ `plan/data.js`)、文書の索引は `docs/ROADMAP.md`、経緯は `docs/WORKLOG.md`

## いまの状態
- 作業フォルダは `C:\dev\youtube-tools`(GitHub: https://github.com/sirloin2983/youtube-tools1)。**push はユーザーが `push.bat`**(RS2〜RS4 のコミットはまだ push されていない)
- **版**: 全体で 1 つ = `src/ytt/version.py` の **0.56.0**(仮。RS5-E。正式な 1.0.0 はこの計画のあとのコードと UI の見直しのあと = ユーザー)・ui-kit v25・送るアプリ **2.10.0**(友人にはまだ渡していない)
- **役割で組み直す計画 `plan/role-restructure.md`**: 層 `src/ytt` ← `pipeline` ← `human` ← `manage` ← `eval`(`app` は全部を使ってよい)。向きは `dev/tests/test_layering.py`。**違反 0・`KNOWN_MAX = 0`**(`dev/layer_map.py`)= 新しい違反は 1 件でも落ちる
- **RS3・RS4 済み(10-10 午後)**: 段の結果は計画 8 節と WORKLOG の最後。ファイルの今の場所は `dev/layer_map.py`(FILES・DIRS)と AGENTS.md の表
  - **RS5 の前半(10-10 夕)で消した**: 編集の殻 9 本・studio/common.py・cut2resolve.py の転送・ytt_core の import(本体は残る)。起動の小物は `src/studio/startup.py`。疑似の旗は `pipeline/transcribe/backend.py` の `mode()`・`is_fake()` と Backend のメソッド。友人の依頼の L1(②③)は消した(L2 の check・L3 は残す)
  - **RS5 の終わり(10-10 夕。ユーザーが入口を起動し直したあと)**: 旧パスの起動用の転送 19 本(tx_worker・live_*_worker 3 つ・recorder.py・dev/eval_* 13 本・ytt_core)も消した = **転送は 0**。layer_map の FORWARDERS は空
  - app に残る物: editor の serve・ed_state・ed_media・ed_thumb・画面、home の launch・live・autorun・portal・prefs・mount・appwindow・settings、studio の serve・common(殻)・handoff・画面
- serve が登録する口: `jobs.register/configure`・`backend.set_selector`・`records.set_dict_inputs`・`recognize.set_head_stripper`・`doc_jobs.set_hooks`(redo_skip・redo_fill・norm_after)+ `check_hooks`・`ytt.settings.register_patch_key`・`speakers.set_context_namer` + `check_context_namer`・`worker_client.FAKES_MODULE`・殻への `_add_moved`(ed_store ← doclist・ed_learn ← metrics・ed_alt ← fake_asr・ed_relink ← folders)
- 測る道具は `src/eval/tools/`(`py -3.10 src/eval/tools/eval_asr.py stored` など。旧 `dev/eval_*.py` も動く)。eval_marks に `--analyze-missing [--wait] [--limit N]` = 未解析の友人の配信の解析を動いているスタジオに頼む(「あとから解析」の代わり)
- 決定: `plan/decisions.md` 3-23〜3-25 は確認済み。**3-26(eval_marks が画面の HTML の meta から合言葉を読む)は仮で決めた = ユーザーの確認待ち**。一時的な案(後の段で直る形)は確認に出さず AI が決めてよい(ユーザー指示)
- **進め方(ユーザー決定 10-10)**: 段ごとには unittest・lint・層の検査だけ・e2e は画面を変えた所の近い 1〜2 本・e2e の一式は RS の終わりに 1 回・文書(AGENTS・計画・data.js)は RS ごとに 1 回・コミットは少し大きめ
- テスト(RS3・RS4 の終わり): 単体一式・契約・test_mount・lint 0・e2e の一式 31 本 OK(前から落ちている e2e_window・e2e_ui_handoff の 2 本を除く)

## 次
1. **RS6**(計画 7・8 節と data.js の RS6): ① の新機能 = アーカイブと動画ファイルの自動採用・切り抜き単位の使い回し(鍵 `ytt/schemas.make_key`)・校正の上書きを切り抜きの鍵に付ける(再認識で消えない)・① 単体の起動(URL か動画 → パック)。app/server.py と live/autorun の分割(decisions 3-25 の c・3-28)・L3(手で届ける)の扱い(3-25 の h)もここ。**新機能 = 設計の変更なので、下調べ(Haiku・low)→ Fable と段の並び → ユーザーに確認してから実装**
2. ユーザーの確認(急がない): 起動し直した入口で校正の画面・話者判別(覚えた声)・まとめて実行で本物の 1 本 / `py -3.10 src/eval/tools/eval_marks.py --analyze-missing --wait` を 1 回 / 送るアプリ 2.10.0 を本物の作業フォルダの `friend-apps\request-sender\build.bat` で作り直して友人へ
- 後へ回したもの(decisions 3-28): 設定 1 ファイル・スタジオの疑似の分岐(studio_env.fake 18 件)・serve 3 本の共通の骨組み → RS7
- 別件(タスクの札にした): `worker_client._probe_gpu` の判定が常に偽(画面の GPU 表示だけ。AMD の PC では実害なし)
- **サブエージェントのモデルとエフォート(ユーザー 10-10)**: 探す・置き換え・文書・テストを流して集める = Haiku・low / 規則の移動 = Sonnet・medium / 差し込み口・入口・広い部品 = Opus・high / 段の並び = Fable。正解表のような機械的な物はスクリプトで作ってサブエージェントに渡す

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
「AGENTS.md → plan/data.js → docs/HANDOVER.md → docs/WORKLOG.md の末尾 3 件 → git status・git log -15 を見て。役割で組み直す計画(plan/role-restructure.md)は RS5 まで済み(向きの違反 0・転送 0)。HANDOVER の『次』のとおり RS6 を、下調べ → Fable と段の並び → ユーザーの確認 → 実装の順で。サブエージェントは仕事に合わせてモデルとエフォートを選ぶ(単純作業は Haiku・low)。決めることが出たら decisions に並べて、一時的な案は聞かずに決めてよい。進め方は AGENTS.md の e2e と文書の決まり(段ごとは unittest・lint・層だけ・e2e 一式と文書は RS の終わりに 1 回)。重要な判断は Fable と相談。」
