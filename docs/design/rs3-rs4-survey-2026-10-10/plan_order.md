> 状態(2026-10-10 朝): 3 つの下調べ(survey_rs3_editor.md・survey_rs3_home_studio.md・survey_rs4.md)を Fable が突き合わせた段の並びと、ユーザーに決めてもらうことの一覧。**まだ確認していない**(要約は `plan/role-restructure.md` の 8 節「RS3・RS4 の手順の案」と `plan/decisions.md` の 3-25)。HEAD 1b27688 の時点。

# RS3・RS4 の段の並びと、ユーザーに決めてもらうこと

前提: 違反 49 = 編集 18 + home/studio 31(3 報告で一致)。両方の段を全部入れると **49 → 0**(計画の RS5「違反 0」は RS4 の終わりで届く)。

## 1. 推奨の段の並び

| 段 | 中身(1 行) | 担当 | 並列 | KNOWN |
| --- | --- | --- | --- | --- |
| **0A 下ごしらえ(編集)** | E0 旧い名前を控える → E1 `ytt/workdata.py`(パス群・ROOT・SERVER_VERSION の持ち主。ed_state から消す)→ E2 動きのある物(check_source・media_duration・find_ffmpeg・probe_media → ytt/tools、GPU → worker_client、worker_fake・valid_model → txbase、studio_* → ytt/studiodata、ROSTER → roster、pio 廃止)→ E3 txenv・test_txenv・serve の register を消す(テスト 9 本の set-up を `workdata.X =` に) | Opus 1 体・直列 | 0B と並列(ファイルが重ならない。layer_map は触らない) | 49 |
| **0B 下ごしらえ(home/studio)** | 表の 3 行(autorun・live → app、live_failures → pipeline)+ 継ぎ目 8 つ(defaults= ×3・friend_feedback の discard=・live_archive の pack_info=・fsio.append_line・pipeline/runlog.py・now_ms → ytt)+ 死んだフック 2 つ | Sonnet 1 体 | 0A と並列 | 49 → 26 |
| **1 設定の口と評価用の判定** | E4 = ed_learn 28-128(load/patch/merge/replace・SETTINGS_PATCH_KEYS・register_patch_key)と ed_relink 506-566(eval_dirs・in_eval_dir・eval_name_guard・_eval_dirs_ok)を **ytt/settings** へ(値は workdata を直に読む = `ytt/evaldirs.py` と登録の口は作らない)。_remote_drive/_move/_same_drive → ytt/fsio。ed_store:280 の `_read_json_file` → fsio。doc_jobs の口 5 → 3 | Opus(0A と同じ体が続けて) | 直列(0A の後) | 26 → 21 |
| **2 波 1(ファイルが重ならない)** | 編集: **E5a** ed_store → human/proof/store + manage/cases/doclist(`_drill` を外し drill_docs が自前で要約・殻)/ **E5b** pipeline_io の組み立て 85 行 → resolve_export → pipeline/pack、pipeline_io → manage/cases、写す一覧 9 か所/ **E5c** ed_learn の残り 4 分割(replace → pipeline/transcribe、学習 → human/proof/learn、精度・基準 → eval/drill/metrics、書き出し・保管 → eval/tools)。home: **RS3-1** live の葉 7 つ + 旧パスの転送 3 つ + **RS4-5 live_report → pipeline**(同じ体)/ **RS3-2** keep・ops / **RS3-3** cases・friend(AutoRunner の友人の届けを mixin へ)。studio: **RS3-4** common の 7 分解 + 殻 | E5a Opus・E5b Sonnet・E5c Opus・RS3-1 Opus・RS3-2 Sonnet・RS3-3 Sonnet・RS3-4 Opus | 同時は 4 本まで(e2e の揺れ)。先に E5a・E5c・RS3-1・RS3-4、空いたら E5b・RS3-2・RS3-3 | 21 → 16 |
| **3 波 2** | **E6** alt・ytcap・retime → human/proof(`backend.select().name`・`Backend.alt_rows`)/ **E7** ed_relink(付け替え+30fps → manage/cases、評価用の整理 → eval/drill/folders)と ed_misc(A/B → eval/drill/abtest、マーカー・受け渡し → manage/cases、フォルダ一括 → human/proof/batch)/ **RS3-5** studio の移動(analyze・batch・store・rank・handoff を割る・txlink・exporter の import)/ **RS4-4a+4b** dev/eval_* 13 本 + _evalcommon → eval/tools(runpy の転送・テスト 14 本を eval/tools/tests へ)+ accuracy → eval/drill | E6 Sonnet・E7 Opus・RS3-5 Sonnet(3 体まで)・RS4-4 Sonnet | E5a の後。RS4-4 は 0A の後ならいつでも | 16 → 4 |
| **4 RS4 の移動と削除** | **RS4-2** ed_drill・ed_evalbatch → eval/drill(殻なし)、ed_evalaudio を消す(`_file_lock` は evalbatch の私的に・テスト・`/api/eval-audio`・start_background)、serve.prepare の評価用の裏スレッドを登録の口に | Opus | E7 と E5c の後(drill が folders・metrics を読む) | 4 → 0 |
| **5 まとめ** | layer_map(FILES・KNOWN_MAX 0)・AGENTS.md・editor/home/studio の README・docs/spec/pipeline.md に「記録の持ち主の表」(RS4 の 4-1)・plan・data.js・decisions・WORKLOG・HANDOVER。全テスト(サブエージェントが止まってから)・e2e 1 本ずつ | まとめ役 + Sonnet(文書) | 直列 | 0 |

- 共有ファイルは担当を作らず**まとめ役が最後に 1 回で直す**: serve.py の `_ED_MODULES`・routes・口の登録行、launch.py/live.py/autorun.py の import 行、`dev/layer_map.py`(FILES・KNOWN)、AGENTS.md、plan/data.js。各担当は「serve.py に足す行」を報告に書く。取り込みは RS2 と同じ(`git merge --ff-only main` → cherry-pick → 移動だけ/付け替えのコミットを分ける → 後から入る側が rebase)。
- 見積もり: 0A+1 ≈ 8.5h(直列)・0B ≈ 1.5h / 波 1 ≈ 壁時計 3.5h / 波 2 ≈ 4h / RS4-2 ≈ 3.5h / まとめ ≈ 3h → **壁時計 2.5〜3 日**(AI の作業 約 45〜50h)。

## 2. 下調べどうしの食い違いへの答え

**(1) 3 分割(ed_learn・ed_relink・ed_misc)の持ち主 → 案 A(RS3 が eval/ まで運ぶ。RS4 は移動と削除だけ)**
- 3 ファイルとも人の部分と eval の部分が相互に呼び合う(metrics → learn の `_groups`、abtest → metrics、folders → relink の `_relink_write`)。境目を確かめた 1 体が 1 回で割れば、同じファイルを 2 人が時間差で触らず衝突も手戻りも無い。
- RS4 先行案は切り出した eval 部品が ed_state を読めないため txenv へ鍵 4 つを足し、A/B は fake_sleep・has_faster_whisper・valid_model まで要る = E3 で消す二重の口が増える。違反の最終値は順番で変わらない(どちらも 0)。

**(2) txenv → E1〜E3 で `ytt/workdata.py` の変数に置き換えて消す(鍵は足さない)**
- txenv の鍵は「ed_state の今の値を返す lambda」なので持ち主が ed_state のまま = 読む側を移しても「→ed_state」の違反は消えず、鍵を足すほど RS5 の片付けが増える。
- 変数の持ち主を ytt に置けば、移す側は `workdata.X` を呼ぶたびに読むだけで、テストの `S.X = …`・`patch.object(S, …)` も modfwd で届く。ed_state に同じ名前を残さない(RS2 の決まり)。

## 3. ユーザーに決めてもらうこと(仮 = 仮で進めてよい / 確 = 確かめてから)

| # | 区分 | 問い | 選択肢 | 推奨 | 理由 |
| --- | --- | --- | --- | --- | --- |
| 1 | 仮 | 段の順: 下ごしらえ → RS3 が 3 分割を eval まで → RS4 は移動・削除 | 案 A / RS4 先行 / 完全並列 | 案 A | 2 節(1) |
| 2 | 仮 | txenv の置き換え先: RS0-a の文言は「ytt/settings」だが新設 `ytt/workdata.py` に分けてよいか | workdata 新設 / settings に同居 | workdata 新設 | settings.py はホーム・スタジオも読む共有部品。書き換わる大域の値を混ぜると modfwd の持ち主が曖昧 |
| 3 | 仮 | 評価用の判定の置き場所 | ytt/settings(RS0-f)/ ytt/evaldirs.py + 登録の口 | ytt/settings | workdata の値を直に読めるので口が要らない |
| 4 | 仮 | 計画 7 節の表の直し: live.py・autorun.py は **app に残す**(友人の届け 275 行だけ human/friend の mixin) | A: app / B: Live を 5 つ・AutoRunner の待機列を pipeline に | A | 違反が 15 件減る・本物の配信が動く玄関を割らない・run への 1 本化は RS6 で同じ所を触る(B は +1〜1.5 日) |
| 5 | 仮 | live_failures → pipeline(計画は manage/ops)、live_report → pipeline(計画は eval/tools)、demo_env → dev に残す(計画は eval/tools) | 表どおり / 直す | 直す | 失敗の文は ① のモジュールが作る・live_report の書き手は ① の見回り・demo_env は app の launch を読む |
| 6 | 仮 | cases.py 丸ごと manage/cases、store.py 丸ごと human/review(RS0-d)、handoff.py は割る、common.py は 7 分解 + 殻 | 計画の表 / 報告の案 | 報告の案 | cases の相手は全部引数・store は同じ辞書と `_save`・exporter が handoff を読む・common は 13 ファイル 360 参照 |
| 7 | 仮 | 殻の方針 | 全部に殻 / drill・evalbatch は殻なし | ed_* と studio/common は殻(RS5 で消す)。drill・evalbatch は殻なし | 読み手が数行だけ |
| 8 | 仮 | ドリルの要約 `_drill`(ed_store → ed_drill) | 登録の口 / drill が自前で読む | 自前 | 口を増やさない |
| 9 | 仮 | 小さな動きの変化: pio() の missing_module エラーと startup_checks の「pipeline_io.py が見つかりません」の廃止 / `_probe_gpu` は直さない(別の札)/ ワーカーの cwd・valid_model はそのまま | — | そのとおり | 移動と動きの修正を混ぜない |
| 10 | 仮 | 旧パスの転送(runpy): live_excite_worker・live_align_worker・live_tx_worker・dev/eval_*.py 13 本。RS5 で消す | 置く / 置かない | 置く | 起動中の古い入口が検出ワーカーと夜の測定を旧パスで起こす |
| 11 | 仮 | 1 対 1 のテストは部品と一緒に層の tests/ へ(dev/tests/test_eval_* 14 本 → src/eval/tools/tests) | 移す / 残す | 移す | RS1・RS2 の流儀。test_accuracy の `const()` が黙って skip する罠は skipped 0 を確かめる |
| 12 | 仮 | ed_store の edit.json は割らない / 名簿 JSON は動かさない / 友人の届けは mixin / 疑似の分岐は RS5 まで / 版は上げない | — | そのまま | 純粋な移動で済む |
| 13 | 仮 | 死んだフック STUDIO_FAKE_CHAT_DELAY・YTT_RECORDER_SOURCE を 0B で消す | — | 消す | 計画 9 節で決定済み。使うテスト 0 |
| 14 | **確** | ed_evalaudio を消す(決定済みの念押し) | 消す | 消す。実データ eval-audio/ とバックアップの写す指定は残す | 動画が外付けに無いときの測定の保険は「保管」の dataset/docs/<id>/full.flac だけになる |
| 15 | **確** | 設定の比較 A/B・修正データの書き出し・データの保管(dataset/)を使っているか | 消す / 移すだけ | RS3・RS4 は移すだけ | 画面に出ている(保存のたびに /api/archive)・保管は測る道具が読む |
| 16 | **確** | 「確認してから届ける」の範囲: L1 友人アプリの ②③ / L2 ライブの after / L3 手で届ける。アプリが ②③ を送ってきたときの扱い | L1 だけ / L1+L2 / 全部 / RS3 では消さない | RS3 では消さず移すだけ。L1・L2 は RS5(アプリ更新と一緒・① に読み替え)、L3 は RS6 の後 | L3 を今消すと直したパックを届ける手段が無くなる |
| 17 | **確** | 「あとから解析(測るため)」を消す時機 | RS3 / RS4 で代わりの道具を作ってから / 消さない | RS4 で eval_marks に「未解析の友人の配信を解析する」口を足してから | 消すと friendRanges の材料が貯まらない |
| 18 | **確** | 「進行度を消す」(RS0-m)の時機 | RS3 / RS4 / 別の段 | RS3・RS4 の外の別の段 | 画面・API・e2e 3 本の変更を伴い、移動と混ぜると落ちた原因が分からない |
| 19 | **確** | 道具のパス: `py -3.10 src/eval/tools/eval_asr.py stored` など(旧 dev/eval_*.py は転送で動く)。README の手打ち 2 か所を直す | — | 新パスに。旧は RS5 まで | ユーザーの手癖に関わる |
| 20 | **確** | 見積もりの直し: RS3 = 1 日・RS4 = 半日 → RS3 = 2〜2.5 日・RS4 = 1 日(合計 壁時計 2.5〜3 日) | — | 直す | 編集だけで直列 24〜27h・home/studio 13〜17h |
| 21 | **確** | 入口を起動し直す時機(RS1・RS2 の本物の 1 本もまだ)。RS3-1 の後は転送 3 つが要る = 配信中は入口を落とさない | — | 配信の無い時に「すべて終了 → start.bat」+ 本物の 1 本 | AI はユーザーの入口を止めない |

## 4. 今夜(ユーザーが寝ている間)に安全に先に進めてよい段
**0A(E0〜E3)と 0B を並列で**: ファイルを動かさない・動きが変わらない(例外は #9 の警告 1 つが出なくなるだけ)・案 A でも RS4 先行でも必ず最初に要る = 手戻りにならない・戻すのは git revert 数コミット。#2(workdata の名前)は仮のまま進める。波 1 以降(ファイルの移動)は取り込みの順番と e2e をまとめ役が見る必要があるので、ユーザーの確認のあと。
