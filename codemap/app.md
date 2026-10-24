# コードの地図: src/app(入口と画面)

自動で作った物(`python dev/code_map.py`)。手で直さない。目次は [index.md](index.md)。`file:line` の行の番号は作った時点の物。

## src/app/

- **__init__.py** (2 行) — 入口と画面。起動・1 つのポート・API の配線・設定の画面の API。全部の層を使ってよい
- **autorun.py** (471 行) — まとめて実行(統合計画の段階5)。入口の「案件」の画面から、配信1本ぶんの作業を順に自動で流す。
  - 名前: `class ToolClient` :102・`spec_from_settings` :175・`live_auto_origin` :193・`class AutoRunner` :204
- **homereq.py** (114 行) — ホームの「友人の依頼」(10-24。ホームの見直しの 1・5): 受付の記録(human/friend/intake の snapshot の requests)に、
  - 名前: `rows` :87
- **live.py** (496 行) — リアルタイム切り抜き(線 D。notes:plan/line-d-live-clipping.md の 0)の入口の側。**既定はオフ**(ホームの設定の節 live.enabled)。
  - 名前: `studio_review` :98・`studio_audio` :105・`studio_lag` :123・`class Live` :132
  - 受ける口: `/api/peaks` :251・`/api/exports` :258・`/api/info` :270・`/api/begin` :306・`/api/export` :309・`/api/export/cancel` :318・`/api/archive/cancel` :320・`/api/archive` :323
- **mount.py** (208 行) — 統合サーバーへのツールの取り込み(統合計画の段階3。notes:docs/design/integration-plan.md)。
  - 名前: `class MountError` :52・`tool_modules` :56・`check_no_collision` :66・`load_serve` :76・`send_redirect` :103・`make_handler` :113・`class Mount` :160
  - 受ける口: `/api/ytt` :45
- **prefs.py** (488 行) — ホームの設定(画面の直し「気が利く画面へ」の土台。notes:docs/design/briefs/ux-consistency/DESIGN_BRIEF.md)。
  - 名前: `class PrefsError` :95・`guess_streamer` :382・`class Prefs` :394
- **server.py** (1828 行) — 入口(ランチャー)— 3つのツールのサーバーをまとめて起動・終了し、入口の画面を出す。
  - 名前: `runtime_dir` :186・`ping` :196・`tail` :204・`expected_version` :225・`tool_python` :231・`rel_or_abs` :241・`signal_stop` :249・`class Tool` :262・`app_data_dir` :312・`logs_dir_for` :318・`class Supervisor` :324・`query_int` :643・ほか 16
  - 受ける口: `/api/drill/status` :154・`/api/eval-batch` :154・`/api/intake` :629・`/api/backup` :630・`/api/accuracy` :631・`/api/flow/runs` :632・`/api/cases/auto` :634・`/api/flow/submit` :635・`/api/flow/estimate` :635・`/api/flow/cancel` :636・`/api/intake/scan` :637・`/api/backup/run` :637・`/api/accuracy/run` :638・`/api/check/answer` :639・`/api/check/unknown` :639・`/api/check/skip` :639・`/api/check/flush` :639・`/api/shutdown` :640・`/api/ping` :729・`/api/status` :731・`/api/health` :741・`/api/log` :743・`/api/flow/status` :758・`/api/flow/history` :762・`/api/check/next` :765・`/api/check/voiceclip` :771・`/api/home/requests` :777・`/api/cases` :789
- **ytlogin.py** (95 行) — ユーザーの PC の YouTube のログイン(10-23 ユーザー「ログインできる形にしといて」)。友人のアプリと同じ作り(notes:docs/spec/friend.md の 13-13)。
  - 名前: `cookies_path` :23・`apply_env` :27・`class YtLogin` :35

## src/app/check/

- **__init__.py** (2 行) — 入口の「確かめる」(⑤ の待ち行列 deck・lineup・sources・read_sources を入口から組む。goals は eval/check。notes:docs/design/v1-check-build.md)
- **cut_sources.py** (165 行) — 「確かめる」の自動カットのカードの出どころ(CUT-CARD。決定: plan/opt-eval.md の Q4 自動カットのカード)。
  - 名前: `cut_edge` :150・`cut_gap` :154・`cut_whole` :158
- **deck.py** (152 行) — 「確かめる」の待ち行列を組み立てる(V1 の V0。GET /api/check/next の中身と、答える前にカードをサーバーの側で引き直す find)。
  - 名前: `invalidate` :30・`check_args` :64・`next_cards` :85・`find` :128
- **eval_sources.py** (114 行) — 「確かめる」の評価のレーンの区間カードの出どころ section:eval(C-EVAL (2)。決定 3-47・3-49 Q2。反映は ③ src/human/check/section.py)。
  - 名前: `cut_after` :41・`section_eval` :62
- **lineup.py** (102 行) — 「確かめる」の待ち行列の並び(lineup)と数え方(V1 の V0。名前は標準の queue と重ねない。notes:docs/design/v1-check-build.md の 2-3)。純粋な関数だけ(ファイルを読まない)。
  - 名前: `card_id` :26・`parse_id` :30・`kind_rank` :40・`order` :67・`first` :72・`per_kind` :77・`public` :86・`check_n` :91
- **read_sources.py** (89 行) — 「確かめる」の読みのカードの出どころ read:alt(V1 の V2b。notes:docs/design/v1-check-build.md の 2-2)。読むだけ(作業データに書かない)。
  - 名前: `read_alt` :84
- **refresh.py** (102 行) — 「確かめる」のカードの元の文書を、今の版の文字起こしで作り直す(夜の見回り)。
  - 名前: `night_of` :32・`targets` :40・`read_state` :55・`tick` :62
- **sources.py** (415 行) — 「確かめる」のカードの出どころ(V1 の V0。notes:docs/design/v1-check-build.md の 2-2)。読むだけ(作業データに書かない)。
  - 名前: `register` :49・`registered` :63・`has_media` :82・`class View` :92・`value_auto` :263・`value_cand` :289・`read_fill` :318・`voice_diar` :335・`time_row` :373・`collect` :398
- **speech_sources.py** (66 行) — 「確かめる」の普段のレーンの「この行は声ですか?」カードの出どころ speech:diar(C-EVAL (3))。
  - 名前: `speech_diar` :41
- **voice_solo.py** (214 行) — 「確かめる」の誰の声のカードの出どころ voice:solo(10-23。ユーザーが自分の声の答えで声を覚えさせるため)。
  - 名前: `stream_counts` :164・`people` :177・`clip_targets` :189・`voice_solo` :198
- **voicefetch.py** (364 行) — 誰の声の材料の配信の音を YouTube から少しだけ取る(10-25。ユーザー「全メンバー揃えてほしい」「ショートだけでは足りない。配信からの材料も要る」。
  - 名前: `extra_channels` :57・`members` :64・`slot_free` :76・`parse_rss` :99・`choose` :113・`wants` :201・`tick` :210・`intake` :310
- **voicefill.py** (107 行) — 誰の声の材料を全メンバーぶんそろえる(10-25。ユーザー「誰の声を全部やったが本当に数人しかいなかった。全メンバー揃えてほしい」)。
  - 名前: `learn_dirs` :25・`eval_like` :38・`in_learn_dir` :44・`targets` :49・`pick` :74・`tick` :86
- **ytqueue.py** (448 行) — YouTube の取得の列(10-25。ユーザー「取り方 1 と 2 を統一しよう」「取得する配信を選ぶ段階で効率化できるはず」)。
  - 名前: `qdir` :47・`requests` :60・`candidates` :93・`score` :99・`fill_candidates` :128・`due` :162・`tidy` :291・`wants` :332・`tick` :341

## src/app/ui/

- **__init__.py** (2 行) — 画面(ホーム home・案件 cases・確かめる check・編集 editor・設定 settings・スタジオ studio)。共通の部品は src/ui-kit

## src/app/ui/cases/

- **caselink.js** (31 行) — 案件の画面へのリンクと切り抜きの校正の進み(ホームの案件の一覧 portal.js と案件の画面 cases.js の両方が読む。/cases-caselink.js)。
- **cases.js** (597 行) — 案件の画面(/cases = 入口の直下の 1 枚。部品は src/app/ui/cases/。RS8 C1 = 殻。作り方 notes:docs/design/rs8-cases-build.md・何を作るか notes:docs/design/briefs/rs8-cases/)。
- **edhost.js** (127 行) — 案件の画面に「編集」の校正(1 文字起こし)をそのまま載せる台(RS8 C2b。作り方 notes:docs/design/rs8-cases-build.md の C2b)。

## src/app/ui/cases/panels/

- **cand.js** (199 行) — 案件の画面の「候補」のパネル(#cand。配信全体の候補の採用・不採用・書き出し・LIVE の帯)。口の形は cases.js の先頭の説明。
- **cut.js** (549 行) — 案件の画面の「カット・パック」のパネル(#cut。残す区間を決めて、末尾で DaVinci Resolve へ渡すパックを作る)。口の形は cases.js の先頭の説明。RS8 C2c。
- **machpick.js** (159 行) — 校正のパネルの 3 択(RS8 C2b。作り方 notes:docs/design/rs8-cases-build.md の 4 節・決定 3-37 の案 A)。
- **new.js** (257 行) — 新しい案件のパネル(ホームの引き出し #newDrawer で開く。配信を探す・URL から入れる・解析の順番待ち。RS8 C3)。
- **proof.js** (188 行) — 案件の画面の「校正」のパネル(#proof。切り抜き 1 本の文字起こしの行を直す)。口の形は cases.js の先頭の説明。RS8 C2b。
- **studio-shim.js** (50 行) — スタジオの部品(review.js・rank.js・queue.js・collab.js)が使う window.Studio の代わりのうち、2 つのパネル(panels/cand.js・panels/new.js)で同じ部分。

## src/app/ui/check/

- **check.js** (588 行) — 確かめる(/check = 入口の直下の 1 枚。部品は src/app/ui/check/。RS8 V1 = 殻。作り方 notes:docs/design/v1-check-build.md・何を作るか …
- **player.js** (248 行) — 確かめるのカード用の軽い再生部品(/check-player.js。RS8 V1。作り方 notes:docs/design/v1-check-build.md の 4・5 節)。

## src/app/ui/check/cards/

- **cut.js** (69 行) — 確かめるの自動カットのカード(/check-cards/cut.js。CUT-CARD。口は check.js の先頭・出どころは src/app/check/cut_sources.py・反映は src/human/check/cutcard.py)。
- **read.js** (98 行) — 確かめるのカード「どちらの読みが正しいか」(/check-cards/read.js。V2b)。比べる欄は ui-kit の .ui-pair(3 択と共用)・口は check.js の先頭。
- **section.js** (134 行) — 確かめるのカード「区間を聞いて直す(評価用)」(/check-cards/section.js。C-EVAL (2)。口は check.js の先頭・出どころは src/app/check/eval_sources.py・
- **speech.js** (20 行) — 確かめるのカード「この行は声ですか?」(/check-cards/speech.js。C-EVAL (3)。口は check.js の先頭・反映は src/human/check/speech.py)。
- **time.js** (107 行) — 確かめるのカード「行の時刻が合っているか」(/check-cards/time.js。RS8 V1 の V2d。作り方 notes:docs/design/v1-check-build.md の 3-2・5 節・決定 3-41)。
- **value.js** (63 行) — 確かめるのカード「価値」(/check-cards/value.js)。口は check.js の先頭。
- **voice.js** (157 行) — 確かめるのカード「これは誰の声?」(/check-cards/voice.js。V2c。口は check.js の先頭・反映は src/human/check/voice.py)。

## src/app/ui/editor/

- **app-core.js** (303 行) — app-core.js — 「編集」の画面: 共通の小道具・表示の好み・⚙・取り込まれたツールの場所・設定。
  - 名前: `uiIcon` :12・`toast` :15・`showErr` :22・`undoToast` :36・`stopAtEnd` :48・`armPlayEnd` :69・`httpFailText` :74・`api` :75・`busy` :81・`kickJobs` :85・`saveFirst` :86・`saveDone` :91・ほか 32
- **app-jobs.js** (339 行) — app-jobs.js — 「編集」の画面: 文字起こしの要求・ジョブの進捗・話者の自動判別・声を覚える・再認識。
  - 名前: `recogOpts` :10・`jobOpts` :16・`startPolling` :22・`pollJobs` :24・`namedBy` :73・`transcribeInto` :77・`renderIntoState` :88・`jobProg` :99・`jobPhase` :100・`jobFailText` :101・`retryJob` :106・`renderDiarSetup` :113・ほか 26
- **app-learn.js** (259 行) — app-learn.js — 「編集」の画面: 修正の提案・校正済み・進み具合の帯・認識精度の測定・名簿・保存データへの保管・評価用の確かめ済み。
  - 名前: `scheduleSuggest` :8・`sugList` :12・`sugHTML` :14・`renderChips` :23・`loadSuggest` :33・`sugFeedback` :40・`altJob` :47・`renderAlt` :50・`applySug` :69・`acceptSug` :74・`rejectSug` :83・`setProof` :87・ほか 17
- **app-list.js** (81 行) — app-list.js — 「編集」の画面: 保存済み一覧の読み込み・題名の行の「まとめて実行」。
  - 名前: `loadList` :10・`portalApi` :18・`applyNeedHome` :24・`runCls` :29・`runStepsText` :30・`pollRuns` :32・`startDocAuto` :46・`renderDocAuto` :63・`syncListItem` :75
- **app-rows.js** (967 行) — app-rows.js — 「編集」の画面: 編集画面(保存・開く・行の描画と操作)・字幕の文字数・行の移動・話者の色・キー配置・用語の挿入・履歴・行の追加。
  - 名前: `spById` :8・`markDirty` :10・`setSaveState` :17・`paintSaveState` :20・`saveDoc` :26・`subNum` :62・`readSubtitle` :64・`fillSubtitle` :77・`subtitleReq` :87・`openDoc` :89・`docInfoText` :134・`opts` :145・ほか 100
- **app-tools.js** (294 行) — app-tools.js — 「編集」の画面: 動画を選び直す・検索と置換・受け渡し・確認のダイアログ・カット・パックのタブとのつなぎ。
  - 名前: `rlSync` :8・`rlReset` :10・`openRelink` :16・`renderRlResult` :23・`rlCheck` :42・`pickPath` :58・`updateDocTitle` :64・`docLength` :70・`renderDocBar` :77・`renderDocBarNow` :79・`syncEval` :95・`evNote` :103・ほか 19
- **app-tpl.js** (226 行) — app-tpl.js — 「編集」の画面の HTML(window.EditProofTpl)。「校正」の欄(tx)・ダイアログ(dialogs)・題名の行(docbar)・⚙ の編集の節(settings)。
- **app.js** (947 行) — 案件の画面(/cases)の校正のパネルの口。src/app/ui/cases/edhost.js が app.js より先に window.EditHost を置く = {base(API の頭), keybar(帯), tab(タブ), open(別の文書), opening}。
  - 名前: `$` :6・`apiUrl` :19・`spColor` :25・`norm` :26・`setSnap` :57・`setStatus` :58・`onLeave` :61・`pctOf` :75・`ago` :78・`runLabelOf` :82・`stepLabelOf` :83・`voiceSec` :93・ほか 31
- **cut.js** (1201 行) — 「編集」2 カット のタブ(notes:docs/design/edit-tool-design.md の 3・4・8)。app.js より先に読み込み、app.js が EditCut.create(host) で起動する。
  - 名前: `create` :24
- **doc-kit.js** (91 行) — doc-kit.js — 文書(文字起こしの行・話者)の小さな部品(window.EditDoc)。状態は持たない。
- **pack-tab.js** (465 行) — 「編集」のパック(2 カット の末尾 #packArea。notes:docs/design/edit-tool-design.md の 3・5)。app.js より先に読み、app.js が EditPack.create(host) で起動する。
  - 名前: `create` :11

## src/app/ui/home/

- **portal-edit.js** (67 行) — ホームの運用の中の「編集の精度」(src/app/ui/home/portal.html の #editOpsBox。RS8 C3)。
- **portal.js** (1806 行) — ホーム(src/app/ui/home/portal.html。段階5で入口 + 案件を1つにした)。

## src/app/ui/settings/

- **settings.js** (207 行) — 設定の画面(/settings = 入口の直下の 1 枚。部品は src/app/ui/settings/。設定を 1 つに S5。notes:docs/spec/data.md の 4)。

## src/app/ui/studio/

- **collab.js** (352 行) — 切り抜きスタジオ: ④ コラボ(動画のグループ化・時刻のズレの指定)。
  - 名前: `$` :8・`durText` :10・`paneHtml` :19・`emptyGroupsHtml` :49・`vlabel` :57・`who` :58・`vById` :59・`vmeta` :60・`videoRowHtml` :68・`matchV` :77・`groupsOf` :84・`isOpenG` :85・ほか 21
- **queue.js** (350 行) — 切り抜きスタジオ: 解析(① の先頭の「URL から入れる」と順番待ち)。Studio.enqueue(items) もここで定義する。
  - 名前: `$` :7・`mmss` :9・`entryHtml` :12・`settings` :49・`loadOpts` :53・`unquote` :58・`looksYt` :59・`entries` :60・`paintKinds` :70・`syncAdd` :75・`refocusForm` :85・`setMsg` :92・ほか 20
- **rank.js** (777 行) — 切り抜きスタジオ: ① 探す(配信ランキング)。検索 → 結果(全部まとめて再生数の順 / 事務所ごと)→ チェックして「解析に追加」か「まとめて実行」(入口から開いたときだけ)
  - 名前: `$` :5・`lsGet` :8・`lsSet` :9・`fmtN` :10・`fmtDur` :11・`ymd` :12・`okThumb` :13・`atMs` :16・`saveReg` :27・`agKey` :32・`captureReg` :35・`restoreReg` :52・ほか 69
- **review.js** (3485 行) — 切り抜きスタジオ ② 確認・書き出し(切り抜きマーカー由来)。
  - 名前: `create` :10・`round1` :15・`uid` :16・`toast` :17・`parseTime` :21・`isAutoLike` :35・`marksPayload` :36・`sec1` :48・`sanitizeKeymap` :49・`spanLabel` :61・`momentSpan` :63・`momentSpanOf` :65・ほか 288

## テスト

- tests/app/_pagetest.py — 入口(src/app/server.py)を一時のデータで立てて GET で画面の配り方を確かめるテストの共通の土台(test_cases_page・test_check_page)。
- tests/app/e2e_autorun.py — まとめて実行(src/app/autorun.py)の通し確認。本物の3ツールを疑似モードで一時フォルダに写し、入口に取り込んだ形で動かす(空きポートだけを使う)。
- tests/app/e2e_cases_cand.py — 案件の画面(/cases)の「候補」のパネル(src/app/ui/cases/panels/cand.js)の通し確認(Playwright)。リポジトリ直下で:
- tests/app/e2e_cases_cut.py — 案件の画面(/cases)の「カット・パック」パネル(src/app/ui/cases/panels/cut.js)の通し確認(Playwright)。リポジトリ直下で:
- tests/app/e2e_cases_proof.py — 案件の画面(/cases)の「校正」のパネル(panels/proof.js・edhost.js・machpick.js)の通し確認(Playwright)。リポジトリ直下で:
- tests/app/e2e_check.py — 確かめる(/check。部品は src/app/ui/check/)の通し確認(Playwright)。リポジトリ直下で:
- tests/app/e2e_live_archive.py — リアルタイム切り抜きのアーカイブ(録画に無い区間だけをアーカイブから書き出す・アーカイブ化を確かめて録画をごみ箱へ移す)の通しの確認。
- tests/app/e2e_live_studio.py — リアルタイム切り抜きの通しの確認: 入口にスタジオを取り込み、録画の部品を別のプロセスで立て、
- tests/app/e2e_portal.py — ホーム(src/app/ui/home/portal.html)の通し確認(Playwright。本物の3ツールを疑似モードで一時フォルダに写し、空きポートだけを使う)。
- tests/app/fake_excite_worker.py — 偽の検出ワーカー(e2e 用)。本物の src/pipeline/analyze/live_excite_worker.py の代わりに入口(live_detect.Detector)が起動し、
- tests/app/test_accuracy_api.py — 入口の API(GET api/accuracy・POST api/accuracy/run・設定の節)と、手が空いた判定のつなぎ。精度の自動測定の本体のテストは tests/eval/drill/test_accuracy.py。
- tests/app/test_autorun.py — まとめて実行(src/app/autorun.py)の段取りのテスト。ツールの API は偽物(FakeTools)で、本物の通し確認は tests/app/e2e_autorun.py。
- tests/app/test_backup_prefs.py — 設定 prefs の backup の節(src/app/prefs.py。入口の側に残した検査)。バックアップの本体のテストは tests/manage/keep/test_backup.py。
- tests/app/test_cases_page.py — 案件の画面(/cases。src/app/ui/cases/)とホーム(/)の配り方の安全の境目のテスト。  python -m unittest tests/app/test_cases_page.py -v
- tests/app/test_check_api.py — 入口の「確かめる」の口(GET api/check/next・POST api/check/answer(undo も)・skip・flush。V1 の V0)のつなぎ。
- tests/app/test_check_page.py — 確かめる(/check。src/app/ui/check/)の配り方の安全の境目のテスト。  python -m unittest tests/app/test_check_page.py -v
- tests/app/test_clean_keep.py — 自動の片付けが残す動画(src/app/server.py の clean_inputs・pending_check_docs。10-24 の直し):
- tests/app/test_deliver_api.py — 入口の ytt_api("deliver") の受け渡し(src/app/server.py の PortalServer.ytt_api)のテスト。deliver の本体のテストは tests/flow/test_deliver.py。
- tests/app/test_homereq.py — ホームの「友人の依頼」の行(src/app/homereq.py): 受付の記録と実行の記録を結んで、札・済んだ・案件の画面への道を決める。
- tests/app/test_intake_prefs.py — 入口の設定 prefs の intake の節(src/app/prefs.py。入口の側に残した検査)。intake の本体のテストは tests/human/friend/test_intake.py。
- tests/app/test_launch.py — 入口(src/app/server.py)のテスト。  python -m unittest tests/app/test_launch.py -v
- tests/app/test_live.py — リアルタイム切り抜き(線 D の P1)の入口の側(src/app/live.py・prefs の節 live・server.py の /live/…・「調子」の行)のテスト。
- tests/app/test_live_archive_api.py — 録画に無い区間をアーカイブから書き出す(線 D の P4)の入口 home を通す分: POST /live/api/archive・…/cancel・GET /live/api/exports の archiveInfo(server.py を通して)。
- tests/app/test_live_detect_api.py — 配信中の盛り上がりの検出の入口 home の側(app の殻 Live の GET|POST /live/api/peaks の振り分け・ホームの設定 prefs の検査)のテスト。
- tests/app/test_mount.py — 入口への取り込み(src/app/mount.py)のテスト。  python -m unittest tests/app/test_mount.py -v
- tests/app/test_settings_schema.py — 設定の画面のスキーマ(src/app/ui/settings/schema.json。S5)と、ホームの設定の検査(prefs.py)が食い違っていないか。リポジトリ直下で:
- tests/app/test_window.py — 窓で開く(src/ytt/appwindow.py)・画面のエラーの記録(本体は tests/manage/ops/test_clientlog.py)・入口の共通の API(api/ytt/…)。
- tests/app/test_ytlogin.py — ユーザーの PC の YouTube のログイン(src/app/ytlogin.py)。本物の YouTube・本物の cookie・本物の窓は使わない(偽の cookie と偽の起動)。リポジトリ直下で:
- tests/app/check/_checkkit.py — tests/app/check の共通の下ごしらえ。test_ で始めない(流す対象ではない)。
- tests/app/check/test_cut_sources.py — 「確かめる」の自動カットのカードの出どころ(src/app/check/cut_sources.py)の単体テスト: スイッチが切れていれば空・評価用の文書は出ない・
- tests/app/check/test_eval_sources.py — 評価のレーンの区間カードの出どころ(src/app/check/eval_sources.py。C-EVAL)の単体テスト: 区切り方・行の持ち主・スイッチ・
- tests/app/check/test_lineup.py — 「確かめる」の待ち行列の順と数え方(src/app/check/lineup.py・goals.py)の単体テスト。純粋な関数だけ。
- tests/app/check/test_read_sources.py — 「確かめる」の読みのカードの出どころ read:alt(src/app/check/read_sources.py。V2b)の単体テスト。一時フォルダの文書・alt.json だけを使う。
- tests/app/check/test_refresh.py — 確かめるのカードの元の古い版の文書の作り直し(src/app/check/refresh.py)の単体テスト: 対象の選び方(古い版・動画がある・評価用は外す・
- tests/app/check/test_sources.py — 「確かめる」のカードの出どころ(src/app/check/sources.py)と組み立て(deck.py)の単体テスト。一時フォルダの文書・.diar.json・スタジオの data.json だけを使う。
- tests/app/check/test_speech_sources.py — 「確かめる」の「この行は声ですか?」の出どころ(src/app/check/speech_sources.py)の単体テスト: 声の区間との重なりの割合・除外(校正済み・noSub・短い・空)・
- tests/app/check/test_voice_solo.py — 「確かめる」の誰の声のカードの出どころ voice:solo(src/app/check/voice_solo.py)の単体テスト: ソロの見分け(コラボの題名・2 人の題名・
- tests/app/check/test_voicefetch.py — 誰の声の材料が無いメンバーの音を YouTube から(src/app/check/voicefetch.py。10-25)。RSS と yt-dlp は偽物(ネットに出ない)。
- tests/app/check/test_voicefill.py — 誰の声の材料を学習用データのショートから(src/app/check/voicefill.py。10-25)。
- tests/app/check/test_ytqueue.py — YouTube の取得の列(src/app/check/ytqueue.py。10-25)。yt-dlp と API は偽物(ネットに出ない)。
