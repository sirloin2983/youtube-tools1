# HANDOVER — 次のセッションへの引き継ぎ(2026-10-07 夜。線 D の前倒し(L1〜L3・M11)の計画まで。段 7〜9・測り直し・UI の見直し・合流は済み)

セッションを切り替えるたびに上書きする。全体の計画と進捗は `plan/index.html`(データ `plan/data.js`)、文書の索引は `docs/ROADMAP.md`、経緯は `docs/WORKLOG.md`、規則は `AGENTS.md`。

## いまの状態
- 作業フォルダは `C:\dev\youtube-tools`(GitHub: https://github.com/sirloin2983/youtube-tools1)。**push はユーザーが `push.bat`**
- **線 D の前倒し(10-07 夜。ユーザー「障害がないなら最優先で試験したい」)= L1〜L3・M11・M9 + M12・M8・M10・ワーカーの残り・見直しの直しまで全部 main に入った**(入口 **0.43.1**・スタジオ **0.23.0**。検出 `live.detect`・自動採用 `live.autoAdopt` は試験中の機能のスイッチで既定オフ)。コミット: L1 32fc540/be5db44 → L3 052f420 → L2 bc39458 → 合流 eaddde8 → 見直しの直し 5fec5aa → M9 の merge 3f38b16 → 点数の経路 09dce8c → M8/M10/ワーカーの merge c0ec368 → lengthHint e2d10b6。worktree とブランチは消した。テスト(10-07 夜、全部 main で): 単体 home 363+102・test_live 43・test_live_detect 38・studio 282・ytt_core/excite 101・node 51・lint 0・e2e 1 本ずつ(live_studio 164・live・live_archive 100・portal・keymap・studio e2e_ui 218 / --mounted 243)すべて OK・`ui_audit all --demo`(Windows で初めて最後まで。dev/ui_audit.py の cp932・file:// を直した)Must 0。仮決めは `plan/decisions.md` 3-7 の (bg)〜(br)・(cb)〜(cw)(3-8 の (bs)〜(bw) は別セッションの I-5。次は (cx) から)。残りの小物は `plan/improvements.md` の 12。**次**: ユーザーが「すべて終了」→ start.bat(10-07 夜の 2 本目の M7 が終わってから)→ 10-18/19 に検出オンで配信 1 本(L4')→ 候補を見て M11 をオンにするか決める
- **線 D の前倒し(10-07 夜。ユーザー「L1〜L3 と M11 を早めにやりたい」)**: 計画は `plan/line-d-detect.md`(順番 L1 → L2 ∥ L3 → M11(既定オフ)→ 10-18/19 に検出オンで配信 1 本 → ユーザーが M11 をオンにするか決める / 線 1 = excite + ワーカー + 入口、線 2 = スタジオの帯 / 候補の API の約束(3)/ 仮決め (bg)〜(br) = `plan/decisions.md` の 3-7 / 日程(5))。**次のセッションは L1 から**(`src/ytt_core/excite.py` へ式を移す。移す前に golden を作る)。同じ夜に入口の設定 `live.autoAfterStream` を API でオンにした(今夜の配信で M7 を試す。結果は WORKLOG と `plan/data.js` の U4・M7 に)
- **合流済み**: PC 側の夜の 2 コミット(段 9 の直し・夜の締め = origin/main)と、クラウドの UI の見直し(ブランチ `claude/ui-review-2026-10-07`)を、クラウドで merge して衝突を直した。PC では `git fetch origin claude/ui-review-2026-10-07` → `git merge origin/claude/ui-review-2026-10-07` で入る(main がその後に進んでいなければ早送り)。取り込んだら「すべて終了」→ start.bat で起動し直す
- 済んだこと(10-07): ① 資料とフォルダの整理 / ② 線 D M1〜M7・B1・A1・B2(手元)/ ③ コードの見直し 2 周目(`dev/lint.py` 0 件)/ ④ plan の文書 / ⑤ 気が利く画面へ 段 7〜9(`plan/ux-stage7-9.md`・段 9 の記録は `DESIGN_REVIEW.md` の付録)/ 行の時刻の測り直し(`plan/line-b-row-timing.md` の 6)/ ⑥ UI の見直し: 基準 `docs/spec/ui-review-criteria.md`(A = 機械で測る 31 項目・B = 人が見る 21 項目)・測る道具 `dev/ui_audit.py`(`py -3.10 dev/ui_audit.py all --demo`。**画面を変えたら Must 0 件**)・3 周の直しで A の Must 704 → 0、見直し役の Must 28 → 0(記録は `docs/design/briefs/ux-consistency/DESIGN_REVIEW.md`)
- **ユーザーに確認してほしいこと**: `plan/decisions.md` の 3-4(段 9 (am)〜(ao))・3-5(測り直し (ap)(aq))・3-6(UI の見直し (ar)〜(bf): 合格の定義・コントラストの範囲・文字記号を全部 SVG・行の札を 2 択に・2 カット の X → H・ホームの ⚙ の節 など)。**済み(10-07 夜)**: 1 秒丸めの配り直しは既定オフ(編集 0.59.4。残るずれの対策は規則も聞き直しの行の時刻も効かず = `plan/line-b-row-timing.md` の 8)/ **判断待ち**: クラウドのエンジン比較の送り先 / M7 の本物の配信での確認(土日)/ L0(配信中に「今やって」)
- UI の見直しの合格は Linux(クラウド)の chromium で判定した。Windows でも e2e(`dev/run_editor_suite.py` と home・studio の e2e)と `py -3.10 dev/ui_audit.py all --demo` を流し直すと確実
- 残り(直さなかった Should・Could)は `plan/improvements.md` の 10(段 9)と 11(UI の見直し)
- 版(コミット済みの最新): 入口 0.42.3・スタジオ 0.22.3・編集 0.59.4・cut2resolve 0.22.2・録画 0.3.2・ui-kit v23・送るアプリ 2.2.0・ホロカラー 1.4.3(正は各ファイル。`plan/data.js` の版の表も同じ)。**v23 / 0.22.3 / 0.59.3 はクラウドと PC が別々に付けた番号を合流で 1 つにした**(README の同じ版の見出しの中に両方の変更)。次に版を付けるときは WORKLOG と origin/main の両方を見る
- Linux で前から落ちるテスト(Windows では通る): home の `test_live` 2 件(`E:\` のパス前提)と `test_cleanup.test_move_only_known_and_purge`(一覧の順が OS で違う)、editor の `test_roster` 2 件 + `test_evalaudio` 1 件(Windows のパス前提)。e2e は Linux でも全部 OK

## 次のセッションに貼る指示文
「AGENTS.md → plan/data.js → plan/line-d-detect.md → docs/WORKLOG.md の末尾 3 件 → git status・git log -10 を見て。線 D の前倒し(L1〜L3・M11・M8〜M10・M12)は全部 main に入っている(入口 0.43.1・スタジオ 0.23.0)。まず今夜の配信 2 本の M7 の結果(GET /live/api/exports?recorder=local&recording=20261007-185959-9OrfCLv9QKY と 20261007-193336-kLsldZDUa70 の archiveInfo.afterStream)と、ユーザーが起動し直したかを確かめて WORKLOG と plan/data.js の U4・M7 に記録。次に plan/improvements.md の 12(M8 の余白 2 秒・仮の候補の札・prefs の説明文)を小さく直し、単体と e2e_live_studio・e2e_portal・ui_audit all --demo で確かめてコミット。ユーザーが検出オンで配信を 1 本試したら、調子・LIVE の帯・live/excite/<rc>/<rec>/peaks.json・excite.log を読んで結果(候補の数・遅れ・チャットの起動し直し・CPU)を WORKLOG に書き、0-10-5 の数を決め直す。迷う点は仮決めして decisions 3-7 に (cx) 以降で。」

## 注意(引き継ぐこと)
- 入口が起動中にフォルダを動かすと、録画の部品(`recorder.py`)のプロセスがフォルダを掴んで移動できない。入口の「すべて終了」では録画の部品が止まらないことがある(10-07)。ユーザーにタスク マネージャーで止めてもらう
- Claude Code のアプリ(Code タブ)から動かす AI は MSIX の中なので、`%LOCALAPPDATA%` への書き込みは写しに入る(`AGENTS.md` の動作環境)。作業データは入口の API を通すか、パッケージの外のプロセスで書く
- クラウドの Claude Code(claude.ai/code)は PC のフォルダを見ない。GitHub のブランチに push するので、PC 側で取り込む(上の手順)。**PC 側でコミットしたら早めに push する**(push していないと、クラウドと同じ版番号・同じ仮決めの記号を付けてしまい、合流で衝突する = 10-07 の合流)。`python` は `python3`・node は `/opt/node22/bin/node`・Segoe UI と Cascadia が無い・YouTube の埋め込みは読めない
- Claude Code のアプリがときどき落ちる(セッションが途中で切れる)。項目ごとにコミットする。再開は「続行」で止まった所から。WORKLOG の「未コミット」と `git status` を突き合わせる
- 2026-09-23 に、Claude が配った zip で GPT の変更が上書きされて消えた。**古い控えからのファイル丸ごとの上書き・zip 配布はしない**
- PC の不安定(i9-13900KF)は 10-04 に CPU を i9-12900KF に替えて解決したとみなす。異常終了は本物の失敗として調べる(入口の「調子」の「異常終了(7 日)」)
