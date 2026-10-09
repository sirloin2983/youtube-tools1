# HANDOVER — 次のセッションへの引き継ぎ(2026-10-09 夜。役割で組み直す計画 = RS0 済み・次は RS1)

セッションを切り替えるたびに上書きする。全体の計画と進捗は `plan/index.html`(データ `plan/data.js`)、文書の索引は `docs/ROADMAP.md`、経緯は `docs/WORKLOG.md`

## いまの状態
- 作業フォルダは `C:\dev\youtube-tools`(GitHub: https://github.com/sirloin2983/youtube-tools1)。**push はユーザーが `push.bat`**
- **版(コミット済みの最新。10-09 夜は変えていない)**: 入口 0.54.0・スタジオ 0.26.0・編集 0.67.0・cut2resolve 0.23.0・録画 0.3.3・ui-kit v25・分析と日報 0.1.1・送るアプリ 2.9.0・ホロカラー 1.4.3
- **10-09 夜に決めたこと = ツール全体のコードを役割で組み直す(`plan/role-restructure.md`。ユーザー決定)**
  - 今の工程ごとのツール分け(スタジオ・編集・cut2resolve・入口)をやめ、役割の層で切る: `src/ytt`(基盤)← `pipeline`(① 自動の流れ: ingest/analyze/export/transcribe/pack + spec.py + run.py)← `human`(② 人の操作: review/proof/cut/find/friend)← `manage`(③ cases/keep/ops)← `eval`(④ fake/drill/tools)。`app`(入口と画面)は全部を使ってよい。UI の作りは後で再考(今の画面はそのまま置く)
  - 決まり(計画 4 節): import の向きをテストで守る / ① は画面と案件を知らない / 人の直しは ① の出力とは別の「上書き」でその段からやり直し(止めて待たない)/ 成果物に鍵を付けて切り抜き単位で使い回す / ① の記録と ② の記録は別 / 実験は束の違いで(① に if を増やさない)/ データの場所と URL は当面そのまま / 版 1 つ・設定 1 ファイル(RS5)
  - ① に渡す物(計画 5-4): 入力(URL か動画ファイル)+ 指定の束 spec(hints: ranges・people[{name,color?}] / analyze / analyze.adopt / export / transcribe / transcribe.post(学習データの場所と版)/ pack / run: from・force)。固定 = 常にパックまで・失敗しても続ける・30fps・精密・画質最大・API キーは束の外。既定値と検査は `pipeline/spec.py` の 1 か所。① は設定ファイルを読まない
  - データの流れの精査(計画 5-5。F-1〜F-9): 切り抜きの鍵に元の媒体の識別(録画 / アーカイブ / 動画ファイルのハッシュ)を入れる・入れ替えのとき ③ が上書きを付け替える・上書きは行の単位(proofed)で時刻の重なりで対応づける・出る人の推定は run が ingest の直後に 1 回・採用の集合 = 自動採用 ∪ hints.ranges ∪ 上書きの採用 − 不採用・話者判別は認識と別の鍵・ライブは 1 本の実行で段は切り抜き単位・学習データは実行の始めの版・① の記録を ③ が書き直さない
  - 横断する仮決め RS0-a〜m(`docs/design/role-restructure-map-2026-10-09.md` 1 節・`plan/decisions.md` 3-22)は**全部ユーザー確認済み**(h・l・m は見直し済み = decisions 1-5)。友人向けは優先度低め(本ツール側の事情を優先)
- **RS0 済み(コミット 9c2d0c9・0bb3d58・4218d0e)**: 層のフォルダ `src/{ytt,pipeline,human,manage,eval,app}`(空。`__init__.py` の docstring だけ)・ファイルの行き先の表 `dev/layer_map.py`(src の .py 97 本)・向きの検査 `dev/tests/test_layering.py`(今ある違反 69 件を KNOWN に。減らすだけ・新しい違反と表に無いファイルで落ちる。`--list` で一覧)・関数ごとの行き先 `docs/design/role-restructure-map-2026-10-09.md`(分割が要る 33 ファイル・約 31,000 行)
- 10-09 夜のそのほか: 最初に誤って始めた「中だけ分ける」案(`plan/code-separation.md`)の途中の変更は stash ごと消した(ユーザー決定)。`plan/code-separation.md` は「置き換え済み」

## 次 = RS1(計画 8 節。目安 1 日。操作は変わらない。**段ごとにユーザーに相談**(10-09 ユーザー指示「毎回きりのいいところで相談して」))
1. `src/ytt_core` → `src/ytt`(`git mv` 1 コミット。`excite.py` は `pipeline/analyze/` へ。`evaldata.py` は `eval/tools/`・`txindex.py` は `manage/cases/`)。旧い `ytt_core` の名前は転送(`src/ytt_core/__init__.py` が `ytt` を再公開)で残し、全テストを通す。`layout.py` の表と、各ツールの `_load_core()`(ytt_core を読む前の 4 か所の写し)・テストが一時フォルダに写すファイルの一覧も直す
2. `src/cut2resolve/{pack,resolve_textplus,cut2resolve_core,cut2resolve}.py` → `pipeline/pack/`、`src/recorder/*` → `pipeline/ingest/`、`src/studio/exporter.py` → `pipeline/export/`。転送で旧い名前を残す
3. `pipeline/spec.py`(5-4 の束の形・既定値・検査。今の設定の画面の値から束を組み立てる関数は app 側)と `pipeline/run.py`(まとめて実行 `autorun` の ① の経路を移して 1 本に。段を関数で呼ぶ = RS0-b。HTTP の `ToolClient` は app に残して消すのは流れが置き換わってから)
4. 鍵の JSON の形(成果物の横の小さな JSON。元の媒体の識別・区間・設定のハッシュ・学習データの版・作った版)を `ytt/schemas` に。今の `.clip.json` を壊さない(足すだけ)
5. 通すもの: 全 unittest(各ツール + `dev/tests/test_layering.py`。違反が減ったら KNOWN から消す)・`test_resolve_pack_contract`(単独)・`e2e_pipeline`・`e2e_live*`・lint 0。各段の終わりに「すべて終了 → start.bat」で本物の 1 本
6. 文書: `dev/layer_map.py`(移した物を DIRS で読む形に)・AGENTS.md の表(ytt_core → ytt、cut2resolve・recorder の行)・`plan/role-restructure.md` の状態の行・`plan/data.js` の RS1・WORKLOG
- RS2(`ed_jobs` の分割)は別のセッションで慎重に(校正の画面が壊れやすい)。RS3 と RS4 は並列にできる

## 次のセッションに貼る指示文
「AGENTS.md → plan/data.js → docs/HANDOVER.md → docs/WORKLOG.md の末尾 3 件 → git status・git log -10 を見て。10-09 夜に決めた役割で組み直す計画(plan/role-restructure.md。全部ユーザー決定済み。RS0 は済み)の RS1 を進めて。計画の 3・4・5-4・5-5・7・8 節と docs/design/role-restructure-map-2026-10-09.md、dev/layer_map.py、dev/tests/test_layering.py を読んでから。ytt_core → ytt(excite は pipeline/analyze)・cut2resolve のパック → pipeline/pack・recorder → pipeline/ingest・exporter → pipeline/export を git mv で移して旧い名前は転送で残し、pipeline/spec.py と run.py を作る。鍵の JSON の形は ytt/schemas に。段ごとにきりのいい所で相談して(RS1 の中でも、移す前に手順を見せてから)。違反は dev/tests/test_layering.py の KNOWN を減らす方向だけ。RS2 はやらない。」

## 注意(引き継ぐこと)
- **unittest に `PYTHONIOENCODING=utf-8` を付けない**(`test_mount` の子プロセスの読みが cp932 で落ちる)。e2e には付ける。e2e は 1 本ずつ
- ファイルは Edit で差分(多くは CRLF。`sed -i`・丸ごと書き直しはしない)。新しいファイルは Write でよい(LF でも git が index で LF にそろえる)
- `git mv` は 1 コミットにまとめ、前後で WORKLOG に告知(AGENTS.md)。移したら `dev/layer_map.py` の FILES から消して DIRS で読む形に(表に無いファイルがあるとテストが落ちる)
- ツール間で同じ名前の .py を作らない(`test_mount.py` が検査)。新しい層のフォルダは `layout.TOOL_DIRS` に無いので今は対象外だが、`pipeline/pack/pack.py` のような名前は転送の `src/cut2resolve/pack.py` と同じ名前になる = `sys.path` の順に注意(ツールのフォルダを先に足す `mount.py` の作り)
- 一時フォルダにツールを写すテスト(`test_launch._copy_tool` など)は tests/ を除いて写す。新しい層のフォルダも写す必要がある(写すファイルの一覧を直す)
- 計画の `plan/data.js` を直したら公開ページ(Artifact)も出し直す(`dev/plan_artifact.py` → Artifact ツール。手順はメモリ reference-plan-artifact)
