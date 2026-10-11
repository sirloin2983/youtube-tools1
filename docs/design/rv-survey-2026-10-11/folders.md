# RV 下調べ 4: フォルダの形

状態(2026-10-11): 読むだけの下調べ(Haiku の報告を Opus が確かめた)。直すのは RV の本番で。

## 1. `src/home/` に残る物(どれも層の表 `dev/layer_map.py` では app)

| ファイル | 行 | 役割 | 候補 |
| --- | --- | --- | --- |
| `launch.py` | 11 | 旧パスの runpy 転送(本体は `src/app/server.py`) | 消す(`test_launch.py` の import を見てから) |
| `mount.py` | 231 | 取り込みの表(MOUNTS・CSP・合言葉) | `src/app/` へ移す |
| `appwindow.py` | 296 | Edge のアプリの窓 | `src/app/` へ |
| `prefs.py` | 494 | ホームの設定の既定と検査 | `src/app/`(か `ytt/settings` へ寄せる) |
| `autorun.py` | 648 | AutoRunner(受付と hook の合成) | `src/app/`。受付を submit 1 つにすると縮む(→ code.md) |
| `live.py` | 527 | ライブの玄関 | `src/app/`。中身の大半は RS7-2 で `flow/livesession.py` へ出た |
| `portal.html`・`portal.js`(2,165)・`portal-edit.js`・`portal.css` | 約 3,050 | ホーム `/` | `src/app/ui/home/` へ(案件の画面 `src/app/ui/cases/` と並べる) |
| `settings/`(index.html・schema.json・settings.js・css) | — | `/settings` | `src/app/ui/settings/` へ |
| `start_hidden.vbs` | 23 | 窓を出さずに起動(`start-background.bat`・`manage/ops/restart.py`・`live.py` が使う) | 残す(置き場所だけ app と一緒に) |
| `vendor/hls.min.js` | 619KB | HLS.js(ライセンス付き) | 残す(置き場所だけ) |
| `README.txt` | 859 | ホームの使い方と変更の記録 | 直下 README と統合を検討(資料 docs.md) |
| `tests/` | unittest 26・e2e 9 | 中身のテストの多くは層へ移った物の HTTP の口 | → tests.md |

- 移すと影響する物: e2e の写す一覧・`test_mount.py` の同名検査・`portal.html` の相対パス(`studio/…`・`transcribe/…`)・`start.bat`・`restart.py`・AGENTS の表。**1 コミットの `git mv` + import の書き換え**で済む規模(半日)。
- `src/home` を空にしたら URL の `/`・作業データの ID `app` は変えない(AGENTS の「フォルダ名と識別子は別」)。

## 2. 名前だけ残った道具のフォルダ

| フォルダ | 中身 | 候補 |
| --- | --- | --- |
| `src/recorder/` | `.gitignore`・`AGENTS.md`・`README.txt`(**.py は 0 本**。AGENTS.md の表の「旧いパスの転送 `recorder.py`」は無い) | 文書を `pipeline/ingest/` の README に寄せてフォルダごと消す。inplace の作業データ `data/` の置き場所を datadir 側で決め直す |
| `src/cut2resolve/` | `serve.py`(740。API の配線)・`cut2resolve.bat`・README(331)・`selection.example.json` | `serve.py` は app。`src/app/` の下に「パックの API」として移すか、`/cut2resolve/` の URL のまま残すかを相談 |
| `src/studio/` | 画面の部品 `review.js`(3,647)・`rank.js`・`collab.js`・`queue.js`・API の配線 `serve.py`(709)・`startup.py`・`handoff.py`(39) | 画面の部品は `src/app/ui/` の下へ、`serve.py` は app へ。**相対パス `studio/…` は URL なので変えずに、入口の取り込みの表で場所だけ差し替えられる** |
| `src/editor/` | `app-*.js`・`app.js`・`app-tpl.js`・`cut.js`・`pack-tab.js`・`proof.css`・`serve.py`(877)・`ed_state.py`・`ed_media.py`・`ed_thumb.py`・`thumb_ideas.py`(402。`ed_thumb` が使う)・`hololive-roster.json` | studio と同じ。`thumb_ideas.py` は ① の道具(画像を作る)なので `pipeline/` へ |
| `src/analytics/` | 分析の本体(calc 1,145・render 573・service 438・bridge・gas/Code.gs) | 残す。**層の検査の外**(`layer_map` の DIRS に無い)= 入れるかを相談 |

## 3. `src/` の中の作業データ(inplace のとき)

| 場所 | 中身 | 状態 |
| --- | --- | --- |
| `src/.runtime/` | 起動中のポート | `.gitignore`。読む側 `ytt/runtime`・`app/server.py`・`cut2resolve/serve.py`・`editor/ed_state.py`・`eval/tools/_studioapi.py` |
| `src/home/prefs.json`・`src/home/live/`・`src/home/logs/` | inplace の入口の設定・ライブ・記録 | `.gitignore` |
| `src/recorder/data/` | inplace の録画 | `src/recorder/.gitignore` |
| `src/analytics/data/` | inplace の分析 | `.gitignore` |
| `src/cut2resolve/packs/` | パックの出力 | `.gitignore` |

- 候補: inplace(テストと開発用)の置き場所を `src/` の外の 1 か所(例: リポジトリ直下の `.data/<ツールID>/`)にまとめる。`.runtime` も `%LOCALAPPDATA%` の側か `.data/` へ。`.gitignore` の `src` 向けの行が減り、「src = コードだけ」になる。影響: `ytt/datadir.py`・`ytt/runtime`・テストの `YTT_DATA_DIR=inplace` の意味(`test_ytt_core.py` が検査)。
- 注意: MSIX の写し(AGENTS の動作環境)を避けるため、`%LOCALAPPDATA%` へ寄せるときはテストが AI のシェルで動くことを確かめる。

## 4. `friend-apps/`・`chrome-ext/`

| 場所 | 最終更新 | 候補 |
| --- | --- | --- |
| `friend-apps/common/`(Json.cs・Log.cs) | 10-07 | 残す(holo-colors と request-sender の両方の build.bat が `..\common\*.cs` を読む) |
| `friend-apps/holo-colors/`(約 3,400 行 + テスト) | 10-08 | 残す |
| `friend-apps/request-sender/`(約 6,800 行 + テスト 1,580) | 10-10 | 残す。友人の依頼の受付が submit 1 つになったら送る形を見直すか(code.md) |
| `chrome-ext/yt-studio-time/` | 10-09 | 残す(本体と独立) |

## 5. `dev/`・`setup/`・直下

| 物 | 候補 |
| --- | --- |
| `dev/sync_ui_kit.py`(104)・`dev/tests/test_ui_kit_sync.py` | 写し先が空(RS8 C4)= **消す**。ui-kit の版の検査だけ残すなら test を縮める |
| `dev/removals.txt` | 09-26 の古い行だけ = 中身を空に(仕組みは Cowork 用に残す) |
| `dev/run_editor_suite.py` | 編集の画面が消えた今、何を流すかを見直す(`setup/requirements*.txt` のコメントも指している) |
| ほかの dev の道具(lint・ui_audit・run_e2e・layer_map・demo_env・plan_artifact・push_helper・dropbox_auth) | 残す |
| `setup/`(bat・command・requirements・cleanup_legacy_data・build_whisper_vulkan) | 残す。`cleanup_legacy_data` は 09-30 の改名の片付け = 友人の PC で済んだら消す候補 |
| 直下 `start-background.bat`・`start.command` | AGENTS の起動の説明に無い = 文書に足す(消さない) |
