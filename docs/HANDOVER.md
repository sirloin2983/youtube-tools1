# HANDOVER — 次のセッションへの引き継ぎ(2026-10-10 夜。役割で組み直す計画 = RS6 は済み(本物の確認も済み)。次は RS7)

セッションを切り替えるたびに上書きする。全体の計画と進捗は `plan/index.html`(データ `plan/data.js`)、文書の索引は `docs/ROADMAP.md`、経緯は `docs/WORKLOG.md`

## いまの状態
- 作業フォルダは `C:\dev\youtube-tools`(GitHub: https://github.com/sirloin2983/youtube-tools1)。**push はユーザーが `push.bat`**(RS2 以降のコミットはまだ push されていない)
- **版**: 全体で 1 つ = `src/ytt/version.py` の **0.56.0**(仮。正式な 1.0.0 はこの計画のあとのコードと UI の見直しのあと)・ui-kit v25・送るアプリ 2.10.0(友人にはまだ渡していない)
- **層は 5 つ(RS6 で決めて組み替えた。decisions 3-29)**: ① 道具 `src/pipeline/`(入力 → 出力の加工だけ)・② 管理 `src/flow/`(① をいつ・どの順で・どこに置いて・飛ばすか。鍵・置き場所・ジョブと SLOTS・ワーカー・結果の束)・③ 人 `src/human/`・④ データ `src/manage/`・⑤ 検証 `src/eval/`・app は全部を読める。**③④ は ① を直に読まず ② を通す・⑤ は ① を直に読んでよい(本物の作業データへ書くときだけ ②)・② に変換のコードを書かない**。向きは `dev/layer_map.py` の `ALLOWED` と `dev/tests/test_layering.py`(違反 0・`test_flow_is_not_alias` = flow に ① の別名だけの関数を作ると落ちる。例外は `# flow: alias ok`。今 1 か所 = `flow/diar.voice_rows`)
- **RS6 で入った物(10-10 夜)**: 段が束(spec)を読む(`flow/spec.py` の束 → 本文の関数・`AutoRunner.build_spec`・`Run.screen` は一時の口)/ Tools の継ぎ目 `flow/tools.py`(HttpTools = 入口の API・LocalTools = 文字起こしとパックを直に)/ 成果物の鍵 `flow/keys.py`(書くのは ② の段の終わり・切り抜きは `作業用\<名前>.export.key.json`・文書は `transcripts\<id>.{transcribe,post,diar}.key.json`・パックは `<pack>\pack.key.json`)と鍵で飛ばす判定(認識は違えば印・force で作り直す / パックは違えば作り直す / 鍵なしは今のまま)/ 校正の上書き O1 `human/proof/overrides.py`(`<id>.over.json`・作り直しで人の行を時刻の重なりで引き継ぐ・STALE の印・`TRANSCRIBE_CARRY_OVERRIDES=off` で止まる)/ 採用を F-5 の 1 つの規則に(`human/review/store.adopt_marks`)/ 置き場所の持ち主 `flow/placement.py`・結果の束 `<案件>\作業用\runs\<実行id>.json`(索引は autorun-runs.jsonl の resultPath)・`.flow.lock`(作業データの根)/ CLI `src/app/cli.py`(入口が動いていれば頼む・無ければ動画ファイルを ② + ① だけで)/ `flow/wire.py`(serve の登録をまとめた・③ なしで呼べる)。仕様は `docs/spec/pipeline.md` の 2.4〜2.7・`docs/spec/data-location.md`。段の表と計画と違えた所は `plan/role-restructure.md` 8 節
- テスト(10-10 夜・e37f238): unittest 約 2,700 件・契約・test_mount・cut2resolve の test_serve(単独)OK・lint 0・層 OK・node 3 本 OK・e2e 31 本 OK(10-10 深夜に前から落ちていた `e2e_window` の [7-1]・`e2e_ui_handoff` を直した = 消した機能を追いかけていた。一式は `py -3.10 dev/run_e2e.py`。`e2e_live_studio` の M2 が続けて流したときだけ落ちていたのは、エンジンの保存の応答で設定の欄が描き直されてモデル名の入力が消えるため = テストは保存の印を待つように直した。描き直しの側(ui-kit の settingsForm)はツールの一括の見直しで)。画面のテストのサーバーは既定で `TRANSCRIBE_CARRY_OVERRIDES=off`(同じ動画を何度も文字起こしするので)

## 次
1. ~~ユーザーの本物の確認(RS6)~~ **済み 10-10 21 時**: ユーザーがアーカイブ 1 本・AI が CLI で動画ファイル 1 本(入口に頼む / 入口なし・鍵で飛ばす・--from pack)。見つけた不具合 = 入口に頼んだときの CLI の結果の JSON の artifacts・packs が空(RS7 で直す)。テストの物 D:/ytt-test/ と文書 cc86ccbb768a(題名 test)はユーザーが消してよい
2. **RS7**(data.js の RS7): 速度を測る → 速度かコード量 + **ライブとまとめて実行の玄関(Live・AutoRunner・launch)を割って 録画 → 検出 → 採用 を ② の run に**(友人もライブを使う = 完成までに必ず)・app/server.py・serve 3 本の骨組み・設定 1 ファイル・案件フォルダ B-1・入口の起動し直しと `.flow.lock`(古い入口がポートを離さないと新しい入口が起動を止める)の見直し・CLI の動画ファイルを入口に頼む口(今は 文字起こし → start-docs の 2 段)
3. RS8(B-2・B-3・O2・URL も CLI だけで。UI の再考と一緒)・F1(友人の PC の RTX 3060 で CLI 1 本 = CUDA。この PC は AMD で確かめられない)
- 後へ回したもの: バックアップが案件フォルダの `作業用\runs\` を写さない(索引で戻せる。B-2 の前に直す)・O1 は人が消した行を覚えない(作り直すと機械の行が戻る = O2)・`flow/diar.voice_rows` の別名(RS7)

## 注意(引き継ぐこと)
- **友人の前提(どのセッションも)**: 配る友人は 1 人・RTX 3060。最終的には友人の PC で ② + ① を動かすのがメイン(decisions 3-29・メモリ project-friend-pc-main)
- **一時の形はユーザーに聞かない**(ユーザー「何度も言うように一時的な変更なら何でもよい。一通り完成したときに動けばよい」)。Fable や下調べが「確」に入れてきた物もまとめ役が選び直す。聞くのは機能・データを消す・使い方が変わる・最終の形を決める物だけ
- 移した名前を別の部品に別名で残さない(S.X の差し替えが別名に当たる)。serve の `_ED_MODULES` に新しい持ち主を足す(RS6 で txtext・clipjob・flow/tx・flow/diar・flow/pack・dictfmt・txwords・slots_jobs を足した)。`modfwd.duplicates` 0 件
- **サブエージェントの実装と e2e を同時に流すと待ちのあるテストが揺れる**。最後の一式はサブエージェントが止まってから
- worktree のサブエージェント: 最初に `git merge --ff-only main`・main が進んだら SendMessage で rebase を頼む・取り込みは ff か cherry-pick(serve.py・layer_map・run.py の衝突はまとめ役)
- unittest に `PYTHONIOENCODING=utf-8` を付けない。e2e には付けて 1 本ずつ。`test_mount`・契約テスト・cut2resolve の test_serve は単独で
- ファイルは差分で直す(多くは CRLF。`sed -i` 禁止)。plan/data.js を直したら公開ページも出し直す(読んでいない版だと断られる → 写しを全部読む → user-tasks も read → 3 回目で通る)
- 入口が起動中の間はコードを変えても古いまま動く。**配信中に入口を落とさない**

## 次のセッションに貼る指示文
「AGENTS.md → plan/data.js → docs/HANDOVER.md → docs/WORKLOG.md の末尾 3 件 → git status・git log -15 を見て。役割で組み直す計画(plan/role-restructure.md)は RS6 まで済み(層は 5 つ = ① 道具 pipeline・② 管理 flow・③ 人・④ データ・⑤ 検証。違反 0)。HANDOVER の『次』の 2 の RS7 を、下調べ → Fable と段の並び → ユーザーの確認(一時の形は聞かない)→ 実装の順で。サブエージェントは仕事に合わせてモデルとエフォートを選ぶ(単純作業は Haiku・low)。進め方は AGENTS.md の e2e と文書の決まり(段ごとは unittest・lint・層だけ・e2e 一式と文書は RS の終わりに 1 回)。重要な判断は Fable と相談。」
