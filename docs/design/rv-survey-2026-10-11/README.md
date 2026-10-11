# RV 全体の見直し — 下調べ(2026-10-11)

状態(2026-10-11): 下調べ済み(読むだけ。コード・テスト・画面・設定は変えていない)。RV の本番はユーザーと「相談の問い」を 1 問ずつ決めてから。並行の OPT2 の後半(ジョブの器を ② へ・音量を % だけに)・V1 の V4 が入ると行数と一部の候補は動く。

調べ方: 読むだけのサブエージェント 6 体を並列に(コード・⑤ eval・画面・テスト・資料 = Sonnet / フォルダ = Haiku)。まとめと突き合わせ・裏取りは Opus。Haiku の「未使用かも」の 4 件(`thumb_ideas.py`・`start_hidden.vbs`・`friend-apps/common`・`analytics/bridge.py`)は使われていると確かめて候補から外した。既存の見直しメモ(`plan/opt-pipeline-flow.md` の RV 行き 約 20 件・`plan/improvements.md` 6)も取り込んだ。

| 観点 | 詳しく |
| --- | --- |
| 1. コード(量・使っていない物・API・重複・名前) | [code.md](code.md) |
| 2. ⑤ 検証 `src/eval/` | [eval.md](eval.md) |
| 3. 画面 | [ui.md](ui.md) |
| 4. フォルダ | [folders.md](folders.md) |
| 5. 資料と R1 | [docs.md](docs.md) |
| 6. テスト | [tests.md](tests.md) |

## 要約(5 行)
1. **細かいデッドコードはほとんど無い**(本体の関数・クラス約 2,000 件のうちテスト以外から使われないのは 13 件)。行を減らせるのは「機能ごと」: ⑤ の一度きりの道具と評価ドリル系(約 5,400 行 + テスト)・**画面に出ないのに生きている編集の UI**(テンプレート約 160 + JS 約 1,000 行)と候補のパネルの隠れた部分(約 250 行)・ライブの使い方しだいの機能(M7・P4・D-11・D-12・M3 で約 1,900 行)。
2. **名前と入口の二重**: 受付が `AutoRunner.start*`(画面)と `POST /api/flow/submit`(CLI)の 2 つ・`/api/flow/{cancel,retry,estimate}` は誰も使わない・封筒の `legacy`(mode・onFail・streamer)は全経路で必須・`run.pinned` は名前から意味が分からない・`MODE_STEPS` 8 種。1 つにすれば `_asked_spec`・`_pins` などの写しと autorun の多くが消える。
3. **フォルダが役割と合わない**: `src/home` は app の .py 6 本 + ホームと設定の画面・`src/studio`・`src/editor` は画面の部品と API の配線だけ・`src/recorder` は文書だけ・`src/analytics` は層の検査の外。テストは `src/home/tests`(11,890 行)・`src/editor/tests`(12,398 行)に層の部品のテストが置き去り。
4. **資料が実装に遅れている**: AGENTS.md の 1 行 約 6,900 文字の経緯・版 0.58.0 のまま・`src/editor/AGENTS.md` に消えたファイル 84 件・`ui-guidelines.md` が RS8 前・索引に無い文書 20 本ほど・WORKLOG 923KB・decisions 196KB・`userTasks.provisional` が空(3-40・3-41 は仮のまま)。
5. **テストの仕組み**: 手書きのテストの列挙(AGENTS の表)から V1 の 10 本ほどが漏れている・e2e は 19 本(AGENTS は 18)・`free_port` などの小物が 7〜25 か所に写し。層ごとに流す `dev/run_unit.py` を作り、表の列挙をやめるのがいちばん効く。

## 候補の表(何を・なぜ・影響・おすすめ・確かめ方)
おすすめ: **消す** / **直す** / **移す** / **残す** / **聞く**(ユーザーに決めてもらう)。大きさ: 小 = 1 時間未満・中 = 半日まで・大 = 1 日以上。

### A. コードと入口
| # | 何を | なぜ | 影響・大きさ | おすすめ | 確かめ方 |
| --- | --- | --- | --- | --- | --- |
| A1 | 受付を `POST /api/flow/submit`(封筒 + 束)1 つに。画面(`portal.js:661-1245`)も封筒を送る。`AutoRunner.start*` 5 本・`/api/autorun/*`・使われない `/api/flow/{cancel,retry,estimate}` の二重を消す | 入口が 2 つ = 欄 → 束の写し(`_asked_spec`・`_with_asked`・`_pins`)が要る | autorun 648 行の大半・ホームの画面・e2e_autorun・e2e_portal。大 | 直す | `test_autorun`・`flow/tests`・`e2e_autorun`・`e2e_portal` |
| A2 | 封筒の `legacy` を束の正式な欄に・`MODE_STEPS` 8 種を束の `run` で表す・`run.pinned` を `locked` に改名・`prefs` の `autorun.mode` を消す | 「一時」の名前が全経路で必須 | `flow/envelope.py`・`run.py`・`livesession.py`・`live_export.py`・`app/cli.py`・`docs/spec/pipeline.md`。束の形の版を上げて古い形を読み替え。中 | 直す(A1 と同じ段) | `test_envelope`・`test_run`・`test_cli`・`test_livesession` |
| A3 | Runner の hook 12 個を「ホストの口」1 つに・`human/friend/delivery.py`(mixin)を消す | 継ぎ方が 3 段で追いにくい | flow・app・human/friend。中 | 直す(A1 のあと) | 同上 |
| A4 | 使われない API `GET /api/transcript-v1`・`POST /api/video/adopt-top`(+ `Store.adopt_top`)・関数 `step_ms`・`read_runtime_port`・`match_voices`・設定の検査 `packFps` | 呼び手が無い | 小 | 消す | `grep` で 0・各テスト |
| A5 | `txindex.key_state` は呼ばれていない(説明文は flow/keys から呼ぶと書く) | つなぎ忘れの疑い | 小 | 聞く(AI が先に調べる) | `flow/keys` と `test_keys` |
| A6 | 同じ中身の写し `now_ms`・`is_network_path`・`safe_stdio`・`_step_error`・3 つの serve の同じ構え(`make_server`・`install_stop_signals` など) | 直す所が 2〜4 か所 | 小〜中 | 直す | 各 serve の test・`test_launch`・`test_mount` |
| A7 | 説明文: 「転送だけの殻 RS5 で消す」14 本・層の番号のずれ・計画の記号(flow に M○ 139 など)・古い版の文字(`cut2resolve v0.4.0` など)・先頭 50 行の仕様書 | 今の形の説明にならない | 数百行減る・動きは変わらない。中 | 直す(記号の早見表を 1 枚) | `lint.py` |
| A8 | ジョブ・待ち行列の仕組み 8 通りを 1 つに | 同じ「積む・動かす・取り消す」が 8 回 | OPT2 の後半で進行中 | 残す(RV では結果を見るだけ) | — |
| A9 | ライブの大きなクラス(`Archiver` を割る・`live_excite_worker.Worker` の段取りと計算)・`recorder.py`・`live_align_worker.py`・`diar` の声の置き場所・`live_cleanup.Cleaner` | `plan/opt-pipeline-flow.md` の RV 行き | 中〜大 | 直す(A1〜A3 と F1 のあと) | flow の live 系・`e2e_live*` |
| A10 | パックの FCPXML・単独のコマンド 2 つ(`srt2resolve.py`・`auto_cut.py`)・単独のコマンドの EDL・手順書の文章がコードの中 | 画面と ② は使わない(README で「残す」と決めた物・決定 3-34 で RV で聞く) | 中 | 聞く | `test_pack`・契約テスト |

### B. 使っていない機能(行を大きく減らすならここ)
| # | 何を | 大きさ | おすすめ | 確かめ方 |
| --- | --- | --- | --- | --- |
| B1 | ⑤ の一度きりの道具 `eval_effort`・`eval_cloud`・`eval_fetch`・`eval_import`・`eval_split`(+ `eval_casebook`・`eval_layers`) | 約 3,660〜4,180 行(テスト込み) | 消す(cloud は聞く) | eval.md の確かめ方 |
| B2 | 評価ドリル・評価の一括・評価用フォルダの整理の API と起動時の処理(`drill.py` の本体・`evalbatch.py`・`folders.py`)。`drill_candidates`(話者の名前の候補)と `evalbatch` の作り直しの hook は ③ へ移して残す | 約 1,700 行 + 編集側のテストと JS | 聞く(⚙ の「評価用をまとめて文字起こし」はまだ届く) | `e2e_cases_proof`・`test_proof_api` |
| B3 | 編集の隠れた UI(ドリルの帯とカード・新規の文字起こし・フォルダの一括・履歴の検索・まとめて付け替え・名簿から用語集・精度のカードの二重・`T.nodoc`・左メニュー) | テンプレート約 160 + JS 約 1,000 行 + CSS | 消す(消えた機能 = 決定済み) | `e2e_cases_proof`・`test_document_save.cjs` |
| B4 | 候補のパネル `review.js` の隠れた部分(配信の選択の一覧・URL を開く・空の案内・ライブの録画を開く) | 約 250 行 | 消す(配信の選択の一覧は決定済み) | `e2e_cases_cand`・`test_cand_panel.cjs` |
| B5 | ライブの機能: 配信後の全自動 M7(約 400)・アーカイブでの作り直し P4(約 700)・配信中の候補の文字起こし D-11(約 360 + ワーカー)・配信ごとの記録 D-12(約 240)・失敗の集約 M3(約 170) | 約 1,900 行 + テスト | 聞く(友人の使い方と F1 の形しだい) | flow の live 系・`e2e_live*` |
| B6 | テスト `test_names.py`(51 件)と `data_ed_*_names.txt` 12 本・`ytt_core` の名前の確かめ 2 件 | 約 1,500 行 | 消す(modfwd の仕組みの検査だけ残す) | `test_modfwd` |

### C. フォルダ
| # | 何を | 影響・大きさ | おすすめ |
| --- | --- | --- | --- |
| C1 | `src/home` の app の .py 6 本を `src/app/`、ホームと設定の画面を `src/app/ui/home/`・`settings/` へ。`launch.py` は消す | e2e の写す一覧・`test_mount`・`start.bat`・`restart.py`・AGENTS。中(1 コミットの `git mv`) | 移す |
| C2 | `src/studio`・`src/editor` の画面の部品を `src/app/ui/` の下へ・3 つの `serve.py` を app へ・`thumb_ideas.py` を `pipeline/` へ。URL の `studio/…`・`transcribe/…`・作業データの ID は変えない | 大 | 聞く(C1 と同時か後か) |
| C3 | `src/recorder` を消す(文書は `pipeline/ingest/` へ)・`src/cut2resolve` の serve を app へ | 小〜中 | 消す・移す |
| C4 | `src/analytics` を層の検査に入れるか、層の外と決めて `layer_map.py:98-105` の行き先を直す | 小 | 聞く |
| C5 | inplace の作業データと `.runtime` を `src/` の外(例: 直下の `.data/`)へ | `ytt/datadir`・`ytt/runtime`・テストの `YTT_DATA_DIR=inplace`・`.gitignore`。中 | 聞く |
| C6 | `dev/sync_ui_kit.py` と `test_ui_kit_sync.py`・`dev/removals.txt` の古い行 | 小 | 消す |

### D. 資料(R1 を含む)
| # | 何を | おすすめ |
| --- | --- | --- |
| D1 | AGENTS.md を今の決まりだけに(経緯 約 6,900 文字の行・表の「〜へ移した」・CLI の詳細は spec へ・版の文字は「version.py を見る」に・画面は 4 枚) | 直す(7 割ほど削れる) |
| D2 | `src/editor/AGENTS.md`(613 行・消えたファイル 84 件)を残る物だけの短い文書に | 直す |
| D3 | `docs/spec/pipeline.md`・`settings.md`・`data-location.md`・`friend-intake.md`・`ui-guidelines.md`・`src/ui-kit/README.md`・各ツールの README の古いパスと画面 | 直す |
| D4 | ROADMAP の索引に無い文書 20 本ほどを足す・HANDOVER の版と「次」 | 直す(小) |
| D5 | WORKLOG(923KB): 日ごとのファイルに割る か 10-07 と同じ圧縮を 10-03〜10-09 に | 聞く(おすすめは圧縮 = 追記の決まりが変わらない) |
| D6 | decisions を未確認だけに(確定は `docs/design/decisions-archive.md` へ。番号は変えない)・`userTasks.provisional` を埋める | 直す |
| D7 | line-*.md を残りだけに・済んだ設計の大きな文書(code-review-simplify 2,747 行・role-restructure-map 1,758 行・rs3〜rs7 の下調べ 約 4,000 行・briefs の古い 2 組)を結論だけにして git の履歴へ | 聞く(どこまで消すか) |
| D8 | `plan/data.js` の整合(V1 を doing・U8 を wait か F1 へ・U5 の 2 か所・古いパス)・`plan/improvements.md` 11 節の古い画面の行を閉じる | 直す |

### E. テスト
| # | 何を | おすすめ |
| --- | --- | --- |
| E1 | `dev/run_unit.py`(層ごとに discover・所要秒・`--only`)を作り、AGENTS の表のテストの列挙をやめる | 直す(いちばん効く) |
| E2 | `src/editor/tests` の約 25 本・`src/home/tests`・`src/studio/tests` の層の部品のテストを層の側へ。偽物 3 本を `eval/fake/` へ・`e2e_edit_common` を `app/tests/` へ。`test_metrics` の `import *` の集めをやめる | 移す(C1・C2 と同じ時に) |
| E3 | 重複(adopt 3 か所・マークの検査・docmove と markmove・ページ共通・設定のスキーマ 3 か所・「重い部品を読まない」3 本)と小物の写し(`free_port` など)を testkit 1 つに・写す一覧 5 か所を「直下を全部」に | 直す |
| E4 | e2e の一式 19 本(約 18 分。ライブ 2 本で半分)はそのまま | 残す |

## 相談の問いの一覧(RV を始めるときに 1 問ずつ)
上から順に聞くと、後の問いの前提がそろう。各問いに AI のおすすめを添える。

1. **RV の進め方**: 段を「(1) 消す物 → (2) 入口と名前(A1〜A3)→ (3) フォルダとテストの移動(C・E)→ (4) 資料(D)」の順にするか。おすすめ: この順(消してから動かすと移す量が減り、資料は最後に 1 回で済む)。
2. **⑤ の一度きりの道具**(B1): `eval_effort`・`fetch`・`import`・`split`・`casebook`・`layers` を消してよいか。`eval_cloud`(決定 3-10 の E1。クラウドとの比較)は続けるか。おすすめ: 全部消す(要るときは git から戻せる)。
3. **評価ドリル・評価の一括・評価用フォルダの整理**(B2): ⚙ の「評価用の動画をまとめて文字起こし」と起動時の評価用フォルダの整理は今も要るか。おすすめ: 精度の自動測定(ホーム)が評価用の文書を作り直せるなら消す。
4. **ライブの機能**(B5): 配信後の全自動・アーカイブでの作り直し・配信中の候補の文字起こし・配信ごとの記録・失敗の集約のうち、あなたと友人が使っている物はどれか。おすすめ: F1(友人の PC)の形が決まってから決める = この問いは F1 のあと。
5. **パックの単独のコマンド**(A10): FCPXML・`srt2resolve.py`・`auto_cut.py`・単独のコマンドの EDL を消してよいか(画面と ② は使わない)。おすすめ: 消す。
6. **受付を submit 1 つに**(A1・A2): 画面も封筒 + 束を送る形にし、`/api/autorun/*` を消してよいか。`legacy` を正式な欄に・`pinned` を `locked` に改名・`mode` を束の `run` で表す、でよいか。おすすめ: はい(古い束は読むときに読み替え)。
7. **フォルダの形**(C1・C2): `src/home` を `src/app` へ(おすすめ: はい)。`src/studio`・`src/editor` の画面の部品と serve も `src/app` へ寄せ、ツール名のフォルダをなくすか(おすすめ: はい。ただし URL・作業データの ID は変えない)。
8. **作業データを `src` の外へ**(C5): inplace と `.runtime` をリポジトリ直下の `.data/` へ移すか。おすすめ: はい(src = コードだけになる)。
9. **`src/analytics`**(C4): 層の検査に入れるか、層の外の独立した道具とするか。おすすめ: 層の外と決めて表を直す(本体と独立して動く)。
10. **WORKLOG**(D5): 日ごとのファイルに割るか、古い日を 1 件 1 行に圧縮するか。おすすめ: 圧縮(追記の決まり・テストを変えずに 3,588 → 約 1,000 行)。
11. **済んだ設計の文書**(D7): rs3〜rs7 の下調べ・code-review-simplify・role-restructure-map・briefs の古い 2 組を「結論だけ + git の履歴」にしてよいか。おすすめ: はい(決定の根拠は decisions と role-restructure 8 節に残っているのを確かめてから)。
12. **AGENTS.md の形**(D1): 今の決まりだけにし、テストのコマンドは `dev/run_unit.py`(E1)に任せる形でよいか。おすすめ: はい。
13. **1.0.0 の条件**: RV のどこまでが済んだら 1.0.0 にするか。おすすめ: 1〜3 と 6・7・12 が済み、e2e 一式と unittest 全部が通ったら。
