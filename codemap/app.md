# コードの地図: src/app(入口と画面)

自動で作った物(`python dev/code_map.py`)。手で直さない。目次は [index.md](index.md)。`file:line` の行の番号は作った時点の物。

## src/app/

- **__init__.py** (3 行) — 入口と画面。起動・1 つのポート・API の配線・設定の画面の API。全部の層を使ってよい
- **autorun.py** (500 行) — まとめて実行(統合計画の段階5)。入口の「案件」の画面から、配信1本ぶんの作業を順に自動で流す。
  - 名前: `class ToolClient` :104・`spec_from_settings` :185・`live_auto_origin` :203・`class AutoRunner` :214
- **cli.py** (548 行) — ② 管理 + ① 道具で動くコマンド(RS6 b-S1。決定 3-29)。
  - 名前: `class UsageError` :55・`class PortalError` :59・`parse_args` :70・`load_spec` :97・`classify_input` :122・`check_from` :137・`use_data_dir` :146・`use_studio_data` :161・`class Learning` :182・`find_doc` :198・`class Progress` :213・`class Portal` :239・ほか 10
- **live.py** (517 行) — リアルタイム切り抜き(線 D。notes:plan/line-d-live-clipping.md の 0)の入口の側。**既定はオフ**(ホームの設定の節 live.enabled)。
  - 名前: `studio_review` :105・`studio_audio` :112・`studio_lag` :130・`class Live` :139
  - 受ける口: `/api/peaks` :271・`/api/exports` :278・`/api/info` :290・`/api/begin` :326・`/api/export` :329・`/api/adopt` :336・`/api/export/cancel` :340・`/api/archive/cancel` :342・`/api/archive` :345
- **mount.py** (220 行) — 統合サーバーへのツールの取り込み(統合計画の段階3。notes:docs/design/integration-plan.md)。
  - 名前: `class MountError` :53・`tool_modules` :57・`check_no_collision` :67・`load_serve` :77・`inject_token` :104・`send_redirect` :115・`make_handler` :125・`class Mount` :172
  - 受ける口: `/api/ytt` :46
- **prefs.py** (493 行) — ホームの設定(画面の直し「気が利く画面へ」の土台。notes:docs/design/briefs/ux-consistency/DESIGN_BRIEF.md)。
  - 名前: `class PrefsError` :96・`guess_streamer` :387・`class Prefs` :399
- **server.py** (1889 行) — 入口(ランチャー)— 3つのツールのサーバーをまとめて起動・終了し、入口の画面を出す。
  - 名前: `runtime_dir` :208・`ping` :218・`port_open` :223・`tail` :229・`expected_version` :250・`tool_python` :256・`rel_or_abs` :266・`signal_stop` :274・`class Tool` :287・`app_data_dir` :337・`logs_dir_for` :343・`class Supervisor` :349・ほか 20
  - 受ける口: `/api/intake` :651・`/api/backup` :652・`/api/accuracy` :653・`/api/flow/runs` :654・`/api/cases/auto` :656・`/api/flow/submit` :657・`/api/flow/estimate` :657・`/api/flow/cancel` :658・`/api/flow/retry` :658・`/api/flow/outbox/done` :659・`/api/intake/scan` :660・`/api/backup/run` :660・`/api/accuracy/run` :661・`/api/window` :661・`/api/check/answer` :662・`/api/check/skip` :662・`/api/check/flush` :662・`/api/cleanup` :663・`/api/shutdown` :663・`/api/ping` :764・`/api/status` :766・`/api/health` :770・`/api/log` :774・`/api/flow/machine` :789・`/api/flow/outbox` :794・`/api/flow/status` :796・`/api/flow/history` :800・`/api/check/next` :803・`/api/cases` :809

## src/app/check/

- **__init__.py** (2 行) — 入口の「確かめる」(⑤ の待ち行列 deck・lineup・sources・read_sources を入口から組む。goals は eval/check。notes:docs/design/v1-check-build.md)
- **cut_sources.py** (165 行) — 「確かめる」の自動カットのカードの出どころ(CUT-CARD。決定: plan/opt-eval.md の Q4 自動カットのカード)。
  - 名前: `cut_edge` :150・`cut_gap` :154・`cut_whole` :158
- **deck.py** (140 行) — 「確かめる」の待ち行列を組み立てる(V1 の V0。GET /api/check/next の中身と、答える前にカードをサーバーの側で引き直す find)。
  - 名前: `invalidate` :26・`check_args` :52・`next_cards` :73・`find` :116
- **eval_sources.py** (114 行) — 「確かめる」の評価のレーンの区間カードの出どころ section:eval(C-EVAL (2)。決定 3-47・3-49 Q2。反映は ③ src/human/check/section.py)。
  - 名前: `cut_after` :41・`section_eval` :62
- **lineup.py** (102 行) — 「確かめる」の待ち行列の並び(lineup)と数え方(V1 の V0。名前は標準の queue と重ねない。notes:docs/design/v1-check-build.md の 2-3)。純粋な関数だけ(ファイルを読まない)。
  - 名前: `card_id` :26・`parse_id` :30・`kind_rank` :40・`order` :67・`first` :72・`per_kind` :77・`public` :86・`check_n` :91
- **read_sources.py** (89 行) — 「確かめる」の読みのカードの出どころ read:alt(V1 の V2b。notes:docs/design/v1-check-build.md の 2-2)。読むだけ(作業データに書かない)。
  - 名前: `read_alt` :84
- **sources.py** (365 行) — 「確かめる」のカードの出どころ(V1 の V0。notes:docs/design/v1-check-build.md の 2-2)。読むだけ(作業データに書かない)。
  - 名前: `register` :45・`unregister` :53・`registered` :58・`class View` :81・`value_auto` :219・`value_cand` :245・`read_fill` :274・`voice_diar` :291・`time_row` :323・`collect` :348
- **speech_sources.py** (66 行) — 「確かめる」の普段のレーンの「この行は声ですか?」カードの出どころ speech:diar(C-EVAL (3))。
  - 名前: `speech_diar` :41

## src/app/ui/

- **__init__.py** (3 行) — 画面(ホーム home・案件 cases・確かめる check・編集 editor・設定 settings・スタジオ studio)。共通の部品は src/ui-kit

## src/app/ui/cases/

- **caselink.js** (31 行) — 案件の画面へのリンクと切り抜きの校正の進み(ホームの案件の一覧 portal.js と案件の画面 cases.js の両方が読む。/cases-caselink.js)。
- **cases.js** (587 行) — 案件の画面(/cases = 入口の直下の 1 枚。部品は src/app/ui/cases/。RS8 C1 = 殻。作り方 notes:docs/design/rs8-cases-build.md・何を作るか notes:docs/design/briefs/rs8-cases/)。
- **edhost.js** (140 行) — 案件の画面に「編集」の校正(1 文字起こし)をそのまま載せる台(RS8 C2b。作り方 notes:docs/design/rs8-cases-build.md の C2b)。

## src/app/ui/cases/panels/

- **cand.js** (224 行) — 案件の画面の「候補」のパネル(#cand。配信全体の候補の採用・不採用・書き出し・LIVE の帯)。口の形は cases.js の先頭の説明。
- **cut.js** (634 行) — 案件の画面の「カット・パック」のパネル(#cut。残す区間を決めて、末尾で DaVinci Resolve へ渡すパックを作る)。口の形は cases.js の先頭の説明。RS8 C2c。
- **machpick.js** (159 行) — 校正のパネルの 3 択(RS8 C2b。作り方 notes:docs/design/rs8-cases-build.md の 4 節・決定 3-37 の案 A)。
- **new.js** (294 行) — 新しい案件のパネル(ホームの引き出し #newDrawer で開く。配信を探す・URL から入れる・解析の順番待ち。RS8 C3)。
- **proof.js** (188 行) — 案件の画面の「校正」のパネル(#proof。切り抜き 1 本の文字起こしの行を直す)。口の形は cases.js の先頭の説明。RS8 C2b。

## src/app/ui/check/

- **check.js** (517 行) — 確かめる(/check = 入口の直下の 1 枚。部品は src/app/ui/check/。RS8 V1 = 殻。作り方 notes:docs/design/v1-check-build.md・何を作るか …
- **player.js** (172 行) — 確かめるのカード用の軽い再生部品(/check-player.js。RS8 V1。作り方 notes:docs/design/v1-check-build.md の 4・5 節)。

## src/app/ui/check/cards/

- **cut.js** (90 行) — 確かめるの自動カットのカード(/check-cards/cut.js。CUT-CARD。口は check.js の先頭・出どころは src/app/check/cut_sources.py・反映は src/human/check/cutcard.py)。
- **read.js** (93 行) — 確かめるのカード「どちらの読みが正しいか」(/check-cards/read.js。V2b)。比べる欄は ui-kit の .ui-pair(3 択と共用)・口は check.js の先頭。
- **section.js** (134 行) — 確かめるのカード「区間を聞いて直す(評価用)」(/check-cards/section.js。C-EVAL (2)。口は check.js の先頭・出どころは src/app/check/eval_sources.py・
- **speech.js** (20 行) — 確かめるのカード「この行は声ですか?」(/check-cards/speech.js。C-EVAL (3)。口は check.js の先頭・反映は src/human/check/speech.py)。
- **time.js** (107 行) — 確かめるのカード「行の時刻が合っているか」(/check-cards/time.js。RS8 V1 の V2d。作り方 notes:docs/design/v1-check-build.md の 3-2・5 節・決定 3-41)。
- **value.js** (90 行) — 確かめるのカード「価値」(/check-cards/value.js)。口は check.js の先頭。
- **voice.js** (80 行) — 確かめるのカード「これは誰の声?」(/check-cards/voice.js。V2c。口は check.js の先頭・反映は src/human/check/voice.py)。

## src/app/ui/editor/

- **app-core.js** (466 行) — app-core.js — 「編集」の画面: 共通の小道具・表示の好み・⚙・他のツール・設定・準備状況・評価ドリルの数の読み直し。
  - 名前: `fmtT` :8・`parseT` :15・`uiIcon` :24・`toast` :27・`showErr` :34・`undoToast` :48・`stopAtEnd` :60・`armPlayEnd` :81・`httpFailText` :86・`api` :87・`apiBlob` :92・`busy` :98・ほか 49
- **app-jobs.js** (397 行) — app-jobs.js — 「編集」の画面: 新規ジョブ・スタジオ/マーカー連携・ジョブの進捗・話者の自動判別・声を覚える・再認識。
  - 名前: `jobOpts` :8・`startFile` :13・`askTxAgain` :27・`onStart` :40・`startPolling` :52・`pollJobs` :54・`namedBy` :103・`renderJobBadge` :105・`transcribeInto` :112・`renderIntoState` :124・`jobProg` :135・`jobPhase` :136・ほか 31
- **app-learn.js** (286 行) — app-learn.js — 「編集」の画面: 修正から学習した候補・修正の提案・校正済み・進み具合の帯・認識精度の測定・名簿と用語集・保存データへの保管・評価用の確かめ済み。
  - 名前: `scheduleSuggest` :8・`putSettingsNow` :10・`sugList` :18・`sugHTML` :20・`renderChips` :29・`loadSuggest` :39・`sugFeedback` :46・`altJob` :53・`renderAlt` :56・`applySug` :75・`acceptSug` :80・`rejectSug` :89・ほか 21
- **app-list.js** (249 行) — app-list.js — 「編集」の画面: 保存済み一覧(履歴)・選んだ文書をまとめて実行。
  - 名前: `loadList` :11・`lastOpened` :22・`rememberLast` :26・`renderResume` :27・`emptyPrimary` :37・`resumeLast` :42・`txGroupKey` :44・`txGroupHead` :50・`txSortFn` :58・`txFiltered` :67・`txShortTitle` :77・`txRowHTML` :86・ほか 14
- **app-rows.js** (1073 行) — app-rows.js — 「編集」の画面: 編集画面(保存・開く・行の描画と操作)・字幕の文字数・行の移動・話者の色・キー配置・用語の挿入・履歴・行の追加。
  - 名前: `spById` :8・`markDirty` :10・`setSaveState` :18・`paintSaveState` :22・`saveDoc` :30・`subNum` :66・`readSubtitle` :68・`fillSubtitle` :81・`subtitleReq` :91・`openDoc` :93・`docInfoText` :152・`setUrlDoc` :164・ほか 110
- **app-tools.js** (516 行) — app-tools.js — 「編集」の画面: 動画を選び直す・まとめて付け替える・検索と置換・書き出し・左パネル・受け渡し・cut2resolve の API・確認のダイアログ・カットとパックのタブとのつなぎ。
  - 名前: `rlSync` :8・`rlReset` :10・`openRelink` :16・`renderRlResult` :23・`rlCheck` :42・`pickPath` :58・`updateDocTitle` :64・`docLength` :70・`renderDocBar` :77・`renderDocBarNow` :79・`syncEval` :96・`evNote` :104・ほか 37
- **app-tpl.js** (329 行) — app-tpl.js — 「編集」の画面の HTML(window.EditProofTpl)。「1 文字起こし」の欄(tx)・ダイアログ(dialogs)・左のメニュー(menu)・空の状態(nodoc)・題名の行(docbar)・⚙ の編集の節(settings)。
- **app.js** (1132 行) — 案件の画面(/cases)の校正のパネルに載せたときの口。src/app/ui/cases/edhost.js が app.js より先に window.EditHost を置く = {base(API の頭), keybar(帯), tab(タブ), open(別の文書), opening}。
  - 名前: `$` :6・`isOtherSp` :17・`apiUrl` :28・`safeName` :32・`spColor` :35・`uid` :36・`norm` :37・`wideTab` :48・`menuOpen` :49・`isDrawer` :54・`setSnap` :97・`setStatus` :98・ほか 44
- **cut.js** (1215 行) — 「編集」2 カット のタブ(notes:docs/design/edit-tool-design.md の 3・4・8)。app.js より先に読み込み、app.js が EditCut.create(host) で起動する。
  - 名前: `create` :24
- **pack-tab.js** (612 行) — 「編集」のパック(2 カット の末尾 #packArea。notes:docs/design/edit-tool-design.md の 3・5)。app.js より先に読み、app.js が EditPack.create(host) で起動する。
  - 名前: `create` :11

## src/app/ui/home/

- **portal-edit.js** (162 行) — ホームの運用の中の「編集の精度と学習」(src/app/ui/home/portal.html の #editOpsBox。RS8 C3)。
- **portal.js** (2094 行) — ホーム(src/app/ui/home/portal.html。段階5で入口 + 案件を1つにした)。

## src/app/ui/settings/

- **settings.js** (172 行) — 設定の画面(/settings = 入口の直下の 1 枚。部品は src/app/ui/settings/。設定を 1 つに S5。notes:docs/spec/data.md の 4)。

## src/app/ui/studio/

- **collab.js** (355 行) — 切り抜きスタジオ: ④ コラボ(動画のグループ化・時刻のズレの指定)。
  - 名前: `$` :8・`durText` :10・`armDelete` :12・`paneHtml` :20・`emptyGroupsHtml` :50・`vlabel` :58・`who` :59・`vById` :60・`vmeta` :61・`videoRowHtml` :69・`matchV` :78・`groupsOf` :85・ほか 22
- **queue.js** (353 行) — 切り抜きスタジオ: 解析(① の先頭の「URL から入れる」と順番待ち)。Studio.enqueue(items) もここで定義する。
  - 名前: `$` :7・`mmss` :11・`entryHtml` :14・`settings` :51・`loadOpts` :55・`unquote` :60・`looksYt` :61・`entries` :62・`paintKinds` :72・`syncAdd` :77・`refocusForm` :87・`setMsg` :94・ほか 20
- **rank.js** (785 行) — 切り抜きスタジオ: ① 探す(配信ランキング)。検索 → 結果(全部まとめて再生数の順 / 事務所ごと)→ チェックして「解析に追加」か「まとめて実行」(入口から開いたときだけ)
  - 名前: `$` :5・`lsGet` :8・`lsSet` :9・`fmtN` :10・`fmtDur` :11・`ymd` :12・`okThumb` :13・`atMs` :16・`saveReg` :27・`agKey` :32・`captureReg` :35・`restoreReg` :51・ほか 69
- **review.js** (3476 行) — 切り抜きスタジオ ② 確認・書き出し(切り抜きマーカー由来)。
  - 名前: `create` :9・`round1` :14・`uid` :15・`toast` :16・`parseTime` :20・`isAutoLike` :34・`marksPayload` :35・`sec1` :48・`sanitizeKeymap` :49・`spanLabel` :60・`sanitizeSettings` :64・`marks` :100・ほか 285

## テスト

- src/app/check/tests/_checkkit.py — src/app/check/tests の共通の下ごしらえ。test_ で始めない(流す対象ではない)。
- src/app/check/tests/test_cut_sources.py — 「確かめる」の自動カットのカードの出どころ(src/app/check/cut_sources.py)の単体テスト: スイッチが切れていれば空・評価用の文書は出ない・
- src/app/check/tests/test_eval_sources.py — 評価のレーンの区間カードの出どころ(src/app/check/eval_sources.py。C-EVAL)の単体テスト: 区切り方・行の持ち主・スイッチ・
- src/app/check/tests/test_lineup.py — 「確かめる」の待ち行列の順と数え方(src/app/check/lineup.py・goals.py)の単体テスト。純粋な関数だけ。
- src/app/check/tests/test_read_sources.py — 「確かめる」の読みのカードの出どころ read:alt(src/app/check/read_sources.py。V2b)の単体テスト。一時フォルダの文書・alt.json だけを使う。
- src/app/check/tests/test_sources.py — 「確かめる」のカードの出どころ(src/app/check/sources.py)と組み立て(deck.py)の単体テスト。一時フォルダの文書・.diar.json・スタジオの data.json だけを使う。
- src/app/check/tests/test_speech_sources.py — 「確かめる」の「この行は声ですか?」の出どころ(src/app/check/speech_sources.py)の単体テスト: 声の区間との重なりの割合・除外(校正済み・noSub・短い・空)・
- src/app/tests/_pagetest.py — 入口(src/app/server.py)を一時のデータで立てて GET で画面の配り方を確かめるテストの共通の土台(test_cases_page・test_check_page)。
- src/app/tests/e2e_autorun.py — まとめて実行(src/app/autorun.py)の通し確認。本物の3ツールを疑似モードで一時フォルダに写し、入口に取り込んだ形で動かす(空きポートだけを使う)。
- src/app/tests/e2e_cases_cand.py — 案件の画面(/cases)の「候補」のパネル(src/app/ui/cases/panels/cand.js)の通し確認(Playwright)。リポジトリ直下で:
- src/app/tests/e2e_cases_cut.py — 案件の画面(/cases)の「カット・パック」パネル(src/app/ui/cases/panels/cut.js)の通し確認(Playwright)。リポジトリ直下で:
- src/app/tests/e2e_cases_proof.py — 案件の画面(/cases)の「校正」のパネル(panels/proof.js・edhost.js・machpick.js)の通し確認(Playwright)。リポジトリ直下で:
- src/app/tests/e2e_check.py — 確かめる(/check。部品は src/app/ui/check/)の通し確認(Playwright)。リポジトリ直下で:
- src/app/tests/e2e_live_archive.py — リアルタイム切り抜きのアーカイブ(録画に無い区間だけをアーカイブから書き出す・アーカイブ化を確かめて録画をごみ箱へ移す)の通しの確認。
- src/app/tests/e2e_live_studio.py — リアルタイム切り抜きの通しの確認: 入口にスタジオを取り込み、録画の部品を別のプロセスで立て、
- src/app/tests/e2e_portal.py — ホーム(src/app/ui/home/portal.html)の通し確認(Playwright。本物の3ツールを疑似モードで一時フォルダに写し、空きポートだけを使う)。
- src/app/tests/fake_excite_worker.py — 偽の検出ワーカー(e2e 用)。本物の src/pipeline/analyze/live_excite_worker.py の代わりに入口(live_detect.Detector)が起動し、
- src/app/tests/test_accuracy_api.py — 入口の API(GET api/accuracy・POST api/accuracy/run・設定の節)と、手が空いた判定のつなぎ。精度の自動測定の本体のテストは src/eval/drill/tests/test_accuracy.py。
- src/app/tests/test_adopt_defaults.py — 採用の数・余白・待ちの既定が束(flow/spec.py の DEFAULTS adopt)の 1 か所から来て、今までの値のままであることを固定する(RS6 b-R1)
- src/app/tests/test_autorun.py — まとめて実行(src/app/autorun.py)の段取りのテスト。ツールの API は偽物(FakeTools)で、本物の通し確認は src/app/tests/e2e_autorun.py。
- src/app/tests/test_backup_prefs.py — 設定 prefs の backup の節(src/app/prefs.py。入口の側に残した検査)。バックアップの本体のテストは src/manage/keep/tests/test_backup.py。
- src/app/tests/test_cases_page.py — 案件の画面(/cases。src/app/ui/cases/)とホーム(/)の配り方の安全の境目のテスト。  python -m unittest src/app/tests/test_cases_page.py -v
- src/app/tests/test_check_api.py — 入口の「確かめる」の口(GET api/check/next・POST api/check/answer(undo も)・skip・flush。V1 の V0)のつなぎ。
- src/app/tests/test_check_page.py — 確かめる(/check。src/app/ui/check/)の配り方の安全の境目のテスト。  python -m unittest src/app/tests/test_check_page.py -v
- src/app/tests/test_cli.py — app/cli(② + ① で動くコマンド)のテスト。  py -3.12 -m unittest src/app/tests/test_cli.py -v
- src/app/tests/test_deliver_api.py — 入口の ytt_api("deliver") の受け渡し(src/app/server.py の PortalServer.ytt_api)のテスト。deliver の本体のテストは src/flow/tests/test_deliver.py。
- src/app/tests/test_intake_prefs.py — 入口の設定 prefs の intake の節(src/app/prefs.py。入口の側に残した検査)。intake の本体のテストは src/human/friend/tests/test_intake.py。
- src/app/tests/test_launch.py — 入口(src/app/server.py)のテスト。  python -m unittest src/app/tests/test_launch.py -v
- src/app/tests/test_live.py — リアルタイム切り抜き(線 D の P1)の入口の側(src/app/live.py・prefs の節 live・server.py の /live/…・「調子」の行)のテスト。
- src/app/tests/test_live_archive_api.py — 録画に無い区間をアーカイブから書き出す(線 D の P4)の入口 home を通す分: POST /live/api/archive・…/cancel・GET /live/api/exports の archiveInfo(server.py を通して)。
- src/app/tests/test_live_detect_api.py — 配信中の盛り上がりの検出の入口 home の側(app の殻 Live の GET|POST /live/api/peaks の振り分け・ホームの設定 prefs の検査)のテスト。
- src/app/tests/test_mount.py — 入口への取り込み(src/app/mount.py)のテスト。  python -m unittest src/app/tests/test_mount.py -v
- src/app/tests/test_settings_schema.py — 設定の画面のスキーマ(src/app/ui/settings/schema.json。S5)と、ホームの設定の検査(prefs.py)が食い違っていないか。リポジトリ直下で:
- src/app/tests/test_window.py — 窓で開く(src/ytt/appwindow.py)・画面のエラーの記録(本体は src/manage/ops/tests/test_clientlog.py)・入口の共通の API(api/ytt/…)。
