状態(2026-10-10): RS6 の段の並びの案(Fable)

# RS6 の段の並びと、ユーザーに決めてもらうこと

下調べ 5 本(adopt・keys・overrides・standalone・app_split。Haiku)を突き合わせ、判断の要になる所はコードを開いて確かめた。HEAD f47bf4c。コードは変えていない。

## 1. 下調べの突き合わせ(食い違い・誤り・自分で確かめた所)

| # | 報告 | 確かめた結果 |
| --- | --- | --- |
| 1 | adopt: `spec.merge` の結果は本番から読まれていない | 正しい。`run()` は `r.spec = spec` に入れるだけ(run.py 931-939)。段は `GET /api/settings` を 4 か所で読む(441・530・637・812)= **RS6-0 で束に置き換える所** |
| 2 | adopt: 動画ファイルは解析も採用もしない | 正しい(MODE_STEPS の file = transcribe のみ)。ただし `human/friend/delivery.py:75 _file_analyze` が残っている(依頼 ③ の名残 = RS5-F でモードを消したので**届かない死にコード**。A3 で使うか消す)。スタジオの `queue/add` は file でも `videoId` を返す(batch.py 117)= 動画ファイルに解析 → 採用 → 書き出しを通す土台はある |
| 3 | adopt: `adopt_top` は「人が採用済みなら何もしない」 | 正しい(store.py 766)。計画 F-5 の「採用の集合 = 自動 ∪ ranges ∪ 人の採用 − 人の不採用」と食い違う。`request_marks`(779-831)は F-5 に近い(ranges → 人の採用を数に入れて点数順で埋める・rejected 除外・重なり除外)= **Q3** |
| 4 | keys: 鍵を書く所・読む所は 0 | 正しい。`make_key` を呼ぶのはテストだけ |
| 5 | keys: 名簿の版が mtime | 半分誤り。`roster_hash` は mtime と大きさを**キャッシュの鍵**にした内容のハッシュ(records.py 95-100・`_file_hash`)= そのまま鍵の材料にしてよい |
| 6 | overrides: 文書の作り直し(run_job)で人の直しが全部消える | 条件つき。同じ切り抜きに文書があれば `_pick_doc` が飛ばすので普段は作り直さない。消えるのは force の再文字起こし・画面の「作り直す」・エンジンを変えた再実行のとき。**本番版への入れ替え(F-1・F-2)は同じパスに置き換える**(live_archive.py `_swap` 1461・`_update_clip` 1471「時刻は変わらない」)ので文書は付いたまま。しかも配信後の全自動は入れ替わるまで文字起こしを待つ(`handoffWait archive`。1027-1031)= 今の流れでは F-2 の付け替えは**ほぼ起きない**。RS6 で要るのは「入れ替え後に鍵を書き直す」(K1)と「作り直しの時の引き継ぎ」(O1) |
| 7 | standalone: 登録の口を CLI が入れるには human・eval の import が要る | 「段を関数で直接呼ぶ」形(B)の話。CLI が serve 3 本を中で起こす形(A')ならこの問題は無い(serve が今どおり登録する)。A' の土台は `home/launch.py --only transcribe,cut2resolve`(`e2e_ui_mounted` が使う形)で、もう動いている |
| 8 | standalone: 素の Runner の `_pick_doc` の既定は None | 正しい = 単体の起動では文字起こしを**毎回**やり直す。素の Runner の `_docs`・`_pick_doc` を HTTP(`GET /api/transcripts` + パスの一致)にする(仮) |
| 9 | app_split: AutoRunner の hook が Runner・Delivery と「重複」 | 誤読。Runner と Delivery の同名は**既定**、AutoRunner の同名は**上書き**(案件・設定で埋める)= 設計どおり。整理する物は無い |
| 10 | app_split: ライブの流れは Runner を使っていない | 半分。書き出しのあとは `live_export._handoff` → `autorun.start_file` → `run()`(① の経路)を通る(live_export.py 1090-1111)。Runner の外なのは 録画 → 解析 → 採用 → 書き出し の前半だけ(live_detect・live_archive・Live.adopt) |

## 2. RS6 の範囲の案(やる・後へ回す)

**やる**: (0) 段が束(spec)を読む(今は 4 か所で画面の設定を HTTP で読む → 束。AutoRunner が設定から束を組む = 5-4「① は設定ファイルを読まない」)/ (1) 自動採用を F-5 の規則で 1 本に・動画ファイルにも解析 → 採用(束の `adopt.mode` で選ぶ)/ (2) 鍵を全段で書く・認識とパックの飛ばす判定に読む(鍵なし = 今のまま)/ (3) 上書きの第 1 版 = 人の行を時刻の重なりで新しい文書へ引き継ぐ + `<id>.over.json` を切り抜きの鍵つきで別に残す(画面は変えない)/ (4) ① 単体の CLI = **HTTP のまま、CLI が 3 つの serve を中で起こす(A')**。launch.py から「3 ツールを起こして止める」部分だけ切り出して CLI と共有 / (5) live_archive の配信後の採用の数と余白を束の `adopt` から読む(prefs の二重管理を 1 つに)。

**後へ回す(理由)**: 段を関数で直接呼ぶ(B)→ RS7 で HTTP の往復の時間を測ってから(認識 1 本 数十秒に対して HTTP は ms = 効果が小さい見込み。B は doc_jobs(②)の文書づくりを ① の成果物に割る大仕事 = 上書き O2 と同じ段で)/ 3 つの経路の一本化(5-1 の「録画 → 解析 → 採用」を Runner に入れる)→ 本物の配信が動く玄関。鍵と採用が入ってから(RS7 の測定のあと)/ app/server.py と live・autorun の分割 → RS7 の「serve 3 本の骨組み」と同じファイルを触るので一緒に(RS6 は CLI に要る切り出しだけ)/ 上書き O2(文書を ① の後処理ずみ + 上書きから組む)→ UI 再考と一緒 / L3(手で届ける)→ 変えない。RS6 のあと「`run.from=pack` → deliver」に読み替える小さな段 / ③ の案件の画面に鍵の状態(認識ずみ・設定が違う・パックが古い)を出す → 読む関数だけ RS6(K2)・画面は後。

見積もり: 計画の「1 日」→ **壁時計 2 日(AI の作業 約 35h。並列込み)**。理由 = 新機能 4 つ + 束の読み替え + CLI。RS3 と同じく実績は計画の 2 倍。

## 3. 段の並び

| 段 | 中身 | 触るファイル | テスト | 並列の組 | モデル | 見積 |
| --- | --- | --- | --- | --- | --- | --- |
| **RS6-0 束を段が読む** | `spec.py` に 束 → API の本文 の純粋関数(`analyze_settings(b)`・`export_body(b)`・`tx_opts(b)`・`pack_output(b)`)。run.py の `_analyze_item`・`_export_body`・`_tx_opts`・`_pack_settings`・`_cut_method` が `GET /api/settings` をやめて `run.spec` を読む。Run の欄(top・ranges・weights・cut・engine・model・video_tracks・speakers)は**そのまま**で、`Run.spec` = AutoRunner が組んだ束に欄を重ねた物(仮)。AutoRunner に `build_spec()`(スタジオ・編集の設定ファイル + prefs → `spec.merge` → `validate`。app が組む = 5-4)。intake の依頼の値は Run の欄のまま(RS6 では束に写さない) | run.py・spec.py・autorun.py・test_spec・test_run・test_autorun | unittest 3 本・lint・層 | 波 1(K1・O1 と並列。run.py は 0 だけが触る) | Opus・high | 5h |
| **RS6-K1 鍵を書く** | ① の持ち主の隣に `.key.json`: export = exporter.py の `write_clip_manifest`(843・851)の隣(inputs: `media_identity`(archive videoId / recording / file sha256)・range・export 設定)。live_archive `_update_clip` が入れ替え後に media = archive で**書き直す**(F-1)。transcribe = `records.write_asr` の隣 `<tid>.transcribe.key.json`(export の鍵の hash・engine・engineVersion・model・language・quality・vadMode・boost)。post = `<tid>.post.key.json`(transcribe の hash・post 設定・`dict_version`)。diar = `diarize.write_diar` の隣(transcribe の hash・出る人・声の版 = F-6)。pack = `pack.build_pack` がパックのフォルダに `pack.key.json`(切り抜きの鍵の一覧・文書の updatedAt/rev・pack 設定)。`records.write_key(tid, stage, inputs)`・`read_key` を records に(doc_jobs が write_asr と同じ場所で呼ぶ = ② が ① の関数を呼ぶ既存の形) | exporter.py・manifest.py・live_archive.py(1471-)・records.py・diarize.py・pack/pack.py・schemas.py(必要なら)・各 tests | test_exporter・test_live_archive・test_txrecords・test_diarize・test_pack・test_ytt_core・`test_resolve_pack_contract`(単独) | 波 1 | Sonnet・medium | 4h |
| **RS6-O1 上書きの第 1 版(F-3)** | 新 `human/proof/overrides.py`: `extract(doc)` = 人の行(proofed・text が original と違う・speaker・noSub・tags)/ `apply(rows, over)` = 時刻の重なり(中心が入る or 重なり 50% 以上)で対応づけて text・proofed・speaker を上書き。対応づかない人の行は新しい印 `STALE_FLAG`「古い認識を元にした直し」で**行として残す** / `write(tid, over)` = `<tid>.over.json`(切り抜きの鍵の hash・at)。呼ぶ所: (a) `store.save_transcript` の最後(派生。`_save_lock` 内)(b) `doc_jobs.run_job` で同じ動画の既存の文書があるとき(`store.find_doc_for_media`。human の中)に新しい行へ apply。再認識 each(`_apply_retranscribe` の proofed pop)と range(`plan_range` の守る区間)は**変えない**。画面・API は変えない | overrides.py(新)・store.py・doc_jobs.py・src/human/proof/tests/test_doc_jobs.py・editor/tests/test_records.py | test_doc_jobs・test_metrics(editor の行)・lint・層 | 波 1 | Opus・high | 6h |
| **RS6-A 採用(F-5)** | A1 `_step_adopt` を 1 本に: 束 `adopt.mode`(新)= `auto`(URL の既定)/ `whole`(動画ファイルの既定 = 今の友人の流れ)/ `ranges`(hints.ranges だけ)/ `candidates`(候補を出して止める)。auto は `request_marks` の規則(ranges → 人の採用を数に入れ → 点数順で `adopt.top` まで・rejected と重なりは除く)に統一(**Q3**)。`adopt_top` は request_marks(ranges=[], auto=top)に吸収。A2 動画ファイル: MODE_STEPS の file/file_auto を `adopt.mode` で組む(whole = 今どおり・それ以外 = analyze → adopt → export → …。videoId は queue/add の返り)。`_file_analyze` を活かす。A3 `candidates` の次回は `run.from=export` = 人の採用(mode adopted)を読む(今の仕組み) | run.py・spec.py(adopt 節)・store.py(request_marks の auto の数え方)・studio/serve.py・delivery.py・test_run・test_studio・test_api | unittest・lint・層 | 波 2(0 のあと。run.py は A と K2 が触る = 同じ体) | Opus・high | 5h |
| **RS6-K2 鍵を読む** | `_step_transcribe`: 文書があれば transcribe の鍵を比べ、一致 → 飛ばす / 鍵なし → 飛ばす(今のまま)/ 違う → 飛ばして「設定が違う(force で作り直し)」の印・`run.force` なら新しい文書へ(O1 が人の行を引き継ぐ)。`_step_pack`: pack の鍵が違う(字幕が新しい・設定が違う)→ 作り直す / 鍵なし → 今のまま(overwrite のときだけ)(**Q4**)。素の Runner の `_docs`・`_pick_doc` の既定を HTTP(`GET /api/transcripts`)に(単体の CLI が使い回せる)。manage/cases/txindex に `key_state(media)`(認識ずみ・設定が違う・パックが古い を返すだけ。画面は後) | run.py・txindex.py・test_run・test_ytt_core | unittest・lint・層 | 波 2(A と同じ体) | Opus・high | 3h |
| **RS6-S1 ① 単体の CLI** | `src/app/host.py`(仮名): launch.py の「3 ツールを取り込んで起こす・止める」(Supervisor・Mount・空きポート・合言葉・後始末)を関数に切り出し、launch.py はそれを呼ぶ(動きは同じ)。`src/app/cli.py`: `py -3.10 src/app/cli.py <URL か動画> --spec spec.json [--from 段] [--force] [--data-dir D] [--out result.json]` = `spec.merge`+`validate` → host で studio・transcribe・cut2resolve を起こす → `run(ToolClient, Run.from_input(...), spec=束)`(hooks なし = 素の Runner)→ 結果の束(`Run.public()` + 段ごとの鍵のパス)を JSON に → host を閉じる(ワーカー・子プロセスを残さない)。API キーは環境変数だけ。作業データは `--data-dir` → `YTT_DATA_DIR` | launch.py・app/host.py(新)・app/cli.py(新)・layer_map(FILES に host・cli を足す)・test_launch・新 test_cli | test_launch・test_mount・test_cli・lint・層 | 波 2(A/K2 と並列。run.py は触らない) | Opus・high | 6h |
| **RS6-R1 配信後の採用を束に** | live_archive の `_per_hour_for`・`Live.adopt` の pad を `spec.DEFAULTS["adopt"]` 経由に(prefs の `live.afterStreamPerHour`・`autoAdopt` は読むが、既定値と範囲は spec の 1 か所)。`pick_candidates`(録画の範囲に切り詰める規則)は**変えない** | live_archive.py・live.py(2 行)・prefs.py(既定の参照)・test_live_archive | unittest・lint・層 | 波 2 | Sonnet・medium | 2h |
| **RS6-Z まとめ** | 文書: `docs/spec/pipeline.md` に鍵と上書きの形(`.key.json`・`.over.json`)/ AGENTS.md(pipeline・human の行と CLI)/ plan 8 節に RS6 の結果と違えた所 / data.js(RS6 済み・見積もりの直し)/ decisions 3-29 / WORKLOG・HANDOVER。e2e の一式(サブエージェントが止まってから 1 本ずつ)。本物の確認(5 節) | 文書・layer_map | e2e 一式・ui_audit(画面は変えないので static だけ) | 直列 | まとめ役 + Sonnet(文書) | 4h |

- 共有ファイルの決まり(RS3 と同じ): run.py は 0 → (A・K2 の 1 体)の順で 1 体ずつ。`spec.py` は 0 が形を作り、A は `adopt` 節だけ足す。serve.py(editor)・layer_map・AGENTS・data.js はまとめ役が最後に 1 回。取り込みは `git merge --ff-only main` → cherry-pick → 後から入る側が rebase
- 波 1 = 0・K1・O1(3 体並列。ファイルが重ならない)→ 波 2 = A+K2(1 体)・S1・R1(3 体並列)→ Z。壁時計 2 日

## 4. ユーザーに確かめること(確)と、AI が決めること(仮)

| # | 区分 | 問い | 選択肢 | 推奨 | 理由 |
| --- | --- | --- | --- | --- | --- |
| Q1 | **確** | ① 単体の起動の形 | A' HTTP のまま CLI が serve 3 本を中で起こす / B 段を関数で直接呼ぶ / C 入口(launch)を別プロセスで起こして待つ | **A'** | B は doc_jobs(②)の文書づくりを ① の成果物に割る大仕事(上書き O2 と同じ段)で RS6 の 1 日に収まらない・HTTP の往復は認識の時間に比べて小さい(RS7 で測る)。C は A' より遅く子プロセスの後始末が二重。A' でも「配った友人の環境で JSON 1 つで動く」は満たす(serve は同じ Python・同じ依存) |
| Q2 | **確** | 動画ファイルの入力の既定(計画 5-4 は「ranges だけ or 候補を出して止める」、今の友人の流れは「全体を 1 本として文字起こし → パック」) | 計画どおり / 今のまま / 束の `adopt.mode` で選べて動画ファイルの既定は whole | **束で選べて既定は whole** | 友人の動画は切り抜き済み(送るアプリの説明も「切り抜いた動画」)= 解析して候補を出すと届かなくなる。計画 5-4 の「友人が自分で録画した物」は mode を ranges / candidates にした束で表せる。送るアプリは変えない |
| Q3 | **確** | 採用の集合の規則を F-5 のとおり 1 本に(ranges → 人の採用を数に入れ → 点数順で top まで・不採用と重なりは除く)。今の `adopt_top` の「人が採用済みなら自動は 0」をやめる | F-5 に統一 / 今のまま(人が採用済みなら足さない) | **F-5 に統一** | 1 つの規則で URL・動画ファイル・依頼が同じ。人が 1 本採用した配信を再実行すると top までの残りを自動で足す = 計画の「人の上書き + 自動」。二重の書き出しは鍵(K2)と status で防ぐ |
| Q4 | **確** | 鍵が違う・無いときの既定 | 認識: 飛ばして印(force で作り直し)/ 違えば作り直す。パック: 違えば作り直す / 今のまま。鍵なし: 今のまま(存在で飛ばす)/ 作り直す | **認識は飛ばして印・パックは作り直す・鍵なしは今のまま** | 認識は重く(10 分の動画で数分)、設定を変えただけで全部やり直すと夜の全自動が止まる。パックは数秒で「字幕を直したら作り直し」が計画の形。既存の成果物に鍵は無いので「鍵なし = 作り直す」は全部作り直しになる = 安全側で今のまま |
| Q5 | **確** | 上書きの第 1 版の範囲 | O1 = 時刻の重なりで新しい文書へ引き継ぐ + `.over.json` を別に残す(画面は変えない)/ O2 = 文書を ① の後処理ずみ + 上書きから組む(① と ② の完全な分離) | **O1** | 今の流れで人の直しが消えるのは force・作り直し・エンジン変更のときだけ(1 節 #6)。O1 でそこを塞ぎ、over.json が ④ と F-2 の材料になる。O2 は文書の形・画面・評価の道具まで変わる = UI 再考と一緒 |
| Q6 | **確** | 経路の一本化(5-1)と app の分割(3-28)の RS6 での範囲 | 最小(R1 + CLI に要る host の切り出しだけ。live/autorun/server.py の分割と録画 → 採用の Runner 入りは RS7 以降)/ 計画どおり全部 | **最小** | 本物の配信が動く玄関を新機能と同じ RS で割らない(落ちた原因が分からなくなる)。RS7 が serve 3 本の骨組みと設定 1 ファイルで同じファイルを触る |

仮(AI が決めて記録だけ): 鍵の置き場所(切り抜き = `作業用/<名前>.<段>.key.json`・文書 = `transcripts/<id>.<段>.key.json`・パック = `<pack>/pack.key.json`)と inputs の中身(5-2 の表。数値は `sec_ms` で ms に) / `.over.json` の形(`{schema: youtube-tools-over/v1, clipKey, rows: [{start, end, text, proofed, speaker, noSub, tags}], at}`)と印の名前 `STALE_FLAG` / `Run.spec` は Run の欄を束に重ねた派生(intake は RS6 では束を組まない)/ 素の Runner の `_docs`・`_pick_doc` を HTTP に / CLI の名前と場所(`src/app/cli.py`・`src/app/host.py`)/ 死にコード `_file_analyze` は A2 で使う / `file_digest`(sha256 全体)は RS6 では大きさ + 先頭と末尾 1MB のハッシュに**しない**(F-1 の識別が要る = 全体。時間は RS7 で測る)/ L3 は据え置き / ③ の画面に鍵の状態を出すのは後 / 見積もりの直し(1 日 → 2 日)。

## 5. リスクと、本物で確かめる手順

リスク: (a) Q3 で「人が採用済みの配信の再実行で自動採用が増える」= 意図した動き。上限 top・鍵・status で二重は無いが、ユーザーが驚く可能性 → 進み具合の文に「自動で n 本を足しました」/ (b) K1 の鍵の材料が ② の値(辞書の版は serve が登録する `set_dict_inputs`)= 引数で受ける形にして層の向きを守る / (c) O1 の時刻の重なりの閾値(fill の `FILL_AGREE_SLACK`・画面の 0.01 秒丸め)= 中心が入る or 50% で始め、評価用の確かめ済み 22 本で「人の行が何割引き継がれるか」を数えて決める(test に固定)/ (d) CLI(A')は入口と同じ MSIX の写しの問題 = AI が動かした結果は本物の作業データに入らない。ユーザーが外のシェルで / (e) `file_digest` は大きい動画で全部読む(2GB で数秒)。RS7 で測る / (f) live_archive の `_update_clip` が鍵を書き直せなかったとき = 鍵が速報版のまま → 認識の鍵が「一致」して本番版の文字起こしが飛ぶ(F-1 そのもの)。書けなければ鍵を**消す**(鍵なし = 今のまま = 作り直さないが、K2 の印が「鍵なし」と出る)/ (g) 波 2 の run.py は 1 体に限る(A と K2)。e2e の一式はサブエージェントが止まってから。

本物で確かめる(計画の「アーカイブ 1 本と動画ファイル 1 本」。配信の無い時に「すべて終了 → start.bat」のあと):
1. アーカイブ 1 本: ホームの「まとめて実行(解析から全部・top 3)」→ 採用 3 本・書き出し・`作業用/*.export.key.json`・文書に `.transcribe.key.json`・`.post.key.json`・パックに `pack.key.json` があること → 「編集」で 1 行直して保存 → `.over.json` が書かれ、同じ配信を再実行 → 解析・採用・書き出し・認識は「飛ばした(鍵が一致)」・パックだけ作り直る(鍵が違う) → 設定でエンジンを変えて再実行 → 認識は「飛ばした: 設定が違う(force で作り直し)」の印 → `force` で再実行 → 新しい文書に直した行が引き継がれ(`proofed` のまま)、対応づかない行があれば印
2. 動画ファイル 1 本(ユーザーの外のシェルで): `py -3.10 src/app/cli.py <mp4> --spec spec.json --data-dir <一時フォルダ> --out result.json`(spec は `{"transcribe": {"engine": "whisper.cpp", "model": "large-v3"}}` 程度)→ パックまでできて result.json に段ごとの成果物と鍵・失敗 0。同じ指定でもう一度 → 全段「飛ばした」。`--from pack` → パックだけ
3. 退行の確認: e2e の一式(特に `e2e_live*`・`e2e_autorun`・`e2e_intake_ui`・`e2e_pipeline`)。ライブの経路は変えないので、ホームのライブの画面で録画 → 採用 → 届ける が今までどおり(本物の配信は次の配信のときに 1 回)
