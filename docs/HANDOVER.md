# HANDOVER — 次のセッションへの引き継ぎ(2026-10-10。役割で組み直す計画 = RS0・RS1 済み・次は RS2 / RS3 / RS4)

セッションを切り替えるたびに上書きする。全体の計画と進捗は `plan/index.html`(データ `plan/data.js`)、文書の索引は `docs/ROADMAP.md`、経緯は `docs/WORKLOG.md`

## いまの状態
- 作業フォルダは `C:\dev\youtube-tools`(GitHub: https://github.com/sirloin2983/youtube-tools1)。**push はユーザーが `push.bat`**
- **版(コミット済みの最新)**: 入口 0.54.1・スタジオ 0.26.0・編集 0.67.0・cut2resolve 0.23.0・録画 0.3.3・ui-kit v25・分析と日報 0.1.1・送るアプリ 2.9.0・ホロカラー 1.4.3(RS1 の移動では版を上げていない = 操作は変わらない。入口 0.54.1 は続けて確認の直し。版 1 つにするのは RS5)
- **役割で組み直す計画 `plan/role-restructure.md`(ユーザー決定)**: 層 `src/ytt`(基盤)← `pipeline`(① 自動の流れ)← `human`(② 人の操作)← `manage`(③)← `eval`(④)。`app` は全部を使ってよい。import の向きは `dev/tests/test_layering.py` が守る(違反は `dev/layer_map.py` の KNOWN。減らすだけ・上限 KNOWN_MAX)
- **RS1 済み(10-09 夜〜10-10。結果は計画 8 節の下・WORKLOG)**:
  - `src/ytt/`(旧 ytt_core。旧い名前は `src/ytt_core/__init__.py` の転送で動く = テストは旧い名前のまま)・`pipeline/analyze/excite.py`・`manage/cases/txindex.py`・`eval/tools/evaldata.py`
  - `pipeline/pack/`(pack・resolve_textplus・cut2resolve_core・cut2resolve(CLI)・srt2resolve・auto_cut・.drb)・`pipeline/ingest/`(rec_core・recorder)・`pipeline/export/exporter.py`。**旧い場所に転送のモジュールは無い**(入口の取り込みの名前の検査が止めるため)。`src/cut2resolve/cut2resolve.py`(.bat 用)と `src/recorder/recorder.py`(古い入口用)だけ転送のスクリプト
  - `pipeline/spec.py`(① に渡す束の形・既定値・検査)・`pipeline/run.py`(`Runner` = ① の段の中身・`run()`。`home/autorun.py` の `AutoRunner` が継いで 12 の口の中身を持つ)・`ytt/schemas.make_key` など(鍵の形だけ。書くのは RS6)
  - 違反 69 → 68。層のパッケージの中は兄弟を相対 import・外からは `from pipeline.pack import pack`。**裸の名前で層のパッケージを読まない**(テストが落とす)
- 10-10 ユーザー指示: **どのセッションもサブエージェントを適切に使う**(AGENTS.md の「最初にやること」5)。RS1 では RS1-2〜7 を別の作業フォルダ(`isolation: worktree`)で並列に作らせ、まとめ役が取り込んで e2e を 1 本ずつ流した

## 次(ユーザーと決める)
- **ユーザーの確認**: 入口を「すべて終了 → start.bat」で起動し直し、まとめて実行で本物の 1 本(パックまで)が今までどおりか(data.js の RS1 の user 欄)
- **RS2**(いちばん重い。別のセッションで慎重に): `editor/ed_jobs.py`(2,800 行)を認識(`pipeline/transcribe`)と文書(`human/proof`)に分割・認識と後処理の段を分ける・エンジンの登録の口・疑似モードを `eval/fake` から。関数ごとの行き先は `docs/design/role-restructure-map-2026-10-09.md` の 5 節
- **RS3 と RS4 は並列にできる**(RS2 と触るファイルを分ける): RS3 = home の友人・案件・片付け・調子・ライブ、スタジオの検索と手動マーク、編集の校正の補助と学習。autorun の友人の経路(`_file_deliver` など)と `Run` の友人の欄もここで `human/friend` へ。RS4 = ドリル・評価用フォルダ・A/B・精度の自動測定・`dev/eval_*`

## 次のセッションに貼る指示文
「AGENTS.md → plan/data.js → docs/HANDOVER.md → docs/WORKLOG.md の末尾 3 件 → git status・git log -10 を見て。役割で組み直す計画(plan/role-restructure.md)は RS1 まで済み。次は RS2(ed_jobs の分割。計画 8 節・docs/design/role-restructure-map-2026-10-09.md の 5 節)を、段ごとに相談しながら進めて。サブエージェントは適切に使う(並列にできる所は最初に決める)。重要な判断は Fable と相談。」

## 注意(引き継ぐこと)
- **unittest に `PYTHONIOENCODING=utf-8` を付けない**(`test_mount` の子プロセスの読みが cp932 で落ちる)。e2e には付ける。e2e は 1 本ずつ(サブエージェントには流させず、まとめ役が取り込んだあとに流す)
- 全体を続けて流したときだけ時間の揺れで落ちることがある: `test_live_archive` の `test_residual_retry_and_busy_studio`・`e2e_live_studio` の M2(エンジン・モデルの欄)。単独で流し直して確かめる
- **前から落ちている e2e(RS1 とは別)**: `src/home/tests/e2e_window.py`([7-1] スタジオの ② の設定 = #count が無い)・`src/editor/tests/e2e_ui_handoff.py`(無くなった「3 パック」のタブを待つ)。別の作業として提案済み
- `test_ytt_core` を `test_mount` と同じプロセスで流すと `TestDatadir.test_resolve_precedence` が落ちる(環境変数の漏れ。別々に流す)
- サブエージェントの作業フォルダ(`isolation: worktree`)は**古いコミットから始まることがある**。最初に `git merge --ff-only main` させる。取り込みは cherry-pick。旧い場所に転送を残す移動は「移動のコミット」と「転送のコミット」に分ける(`git log --follow` が効くように)
- ファイルは Edit で差分(多くは CRLF。`sed -i`・丸ごと書き直しはしない)。新しいファイルは Write でよい
- `git mv` は 1 コミットにまとめ、前後で WORKLOG に告知。移したら `dev/layer_map.py` の FILES から消す(DIRS で読む)・KNOWN はパスの付け替えだけ
- 計画の `plan/data.js` を直したら公開ページ(Artifact)も出し直す(`dev/plan_artifact.py` → Artifact ツール。手順はメモリ reference-plan-artifact)
