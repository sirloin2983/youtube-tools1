# RS5 下調べ: 版と設定ファイル(2026-10-10)

状態(2026-10-10): 下調べ(Haiku)の報告

読むだけの調べ。コードは変えていない。行番号は 2026-10-10 時点。

## A. 版の持ち場所

### A-1. 版の正(コード内の定数)

| ツール | 版の正 | 値 | 読む側 |
| --- | --- | --- | --- |
| ホーム(入口) | `src/home/launch.py:101` `VERSION` | 0.55.0 | `/api/ping`・`/api/status`(:299, :656) |
| スタジオ サーバー | `src/studio/serve.py:39` `SERVER_VERSION` | 0.26.0 | `/api/ping`(:183)・`.clip.json`(:41) |
| スタジオ 画面 | `src/studio/core.js:5` `APP_VERSION` | 0.26.0 | 赤い帯(:311) |
| 編集 サーバー | `src/editor/serve.py:135` `SERVER_VERSION` | 0.69.0 | `/api/ping`(:225)・入口が読む |
| 編集 画面 | `src/editor/app.js:2` `APP_VERSION` | 0.69.0 | 赤い帯(:1272)・`UIKit.settings.mount`(:82) |
| 編集 部品の持ち主 | `src/ytt/workdata.py:28` `SERVER_VERSION`(serve が :137 で入れる) | - | 部品(postproc :358 ほか) |
| cut2resolve | `src/pipeline/pack/cut2resolve_core.py:33` `VERSION` | 0.23.0 | `src/cut2resolve/serve.py:76` が `SERVER_VERSION = C.VERSION` で再利用 |
| 録画の部品 | `src/pipeline/ingest/recorder.py:48` `VERSION` | 0.3.3 | 入口の「調子」 |
| ytt(共通部品) | `src/ytt/__init__.py:30` `VERSION` | 1.8.0 | 参照は少ない |
| 分析 | `src/analytics/__init__.py:15` `VERSION` | 0.1.1 | - |
| srt2resolve | `src/pipeline/pack/srt2resolve.py:28` `VERSION` | 0.1.4 | - |
| auto_cut | `src/pipeline/pack/auto_cut.py:27` `VERSION` | 0.2.0 | - |
| live_export | `src/pipeline/export/live_export.py:63` `VERSION` | 0.1.0 | - |
| ホロカラー(C#) | `friend-apps/holo-colors/README.txt` 見出しのみ | 1.4.3 | 版の定数はコード側を確認していない |
| 依頼送信(C#) | 確認していない | - | - |
| 拡張 yt-studio-time | README 見出し `README.txt:1` | 0.1.0 | manifest 側は未確認 |

版の正の数: Python・JS の定数で **10 か所**(ホーム・スタジオ 2・編集 3(serve・app.js・workdata の写し)・cut2resolve・録画・ytt・分析・srt2resolve・auto_cut・live_export)。
ほかに寄せ先として重複している箇所: `src/home/launch.py:113` の `SERVE_VERSION_RE`(serve.py の行を正規表現で読む)と `launch.py:116-130` の `_spec(... version_path=...)`(cut2resolve 側は `layout.PACK_CORE` の `VERSION` 行を読む)。

### A-2. 版の見出し(README.txt)

| ファイル | 見出し行 |
| --- | --- |
| `src/home/README.txt:2` | v0.55.0 |
| `src/studio/README.txt:2` | v0.26.0 |
| `src/editor/README.txt:2` | v0.69.0 |
| `src/cut2resolve/README.txt:1` | v0.23.0 |
| `src/analytics/README.txt:2` | v0.1.1 |
| `src/pipeline/ingest/README.txt`・`src/pipeline/pack/README.txt`・`src/ytt/README.txt` | 見出しに版の数字なし(未確認) |

見出しの数字は手で合わせる(CLAUDE.md の決まり)。見出しを検査するテストは確認できなかった。

### A-3. 食い違いの検査(赤い帯)

- **ui-kit**: `src/ui-kit/ui-kit.js:2173-2248` `UIKit.restart`(check・band・run・available)。`check(el, 画面の版, サーバーの版)` は版が違えば帯を出す。`UIKit.version` は `ui-kit.js:2662` で 25。
- 各画面の呼び出し: スタジオ `core.js:311`、編集 `app.js:1272`。ツールの起動時の `/api/ping` のあと。
- 編集サーバー自身の検査: `src/editor/serve.py:680-682`(app.js の APP_VERSION を正規表現で読んで比べ、違えば文字列を返す)。
- 入口の版比べ: `src/home/launch.py:181`(version_path の行を読んで期待値とし、`/api/ping` の値と比べる。`expected` は :253)。

### A-4. テスト・検査

- `src/home/tests/test_launch.py:128`: 版の行を作って起動の検査に使う。
- `src/home/tests/e2e_portal.py:176-177`: 編集・スタジオの画面の版を正規表現で読んで照合。
- `src/editor/tests/e2e_proofread_accuracy.py:26`・`e2e_folder_marker_range.py:23`・`e2e_ui_mounted.py:167`: `const APP_VERSION` を読む。
- `src/editor/tests/test_names.py:145`・`test_whispercpp.py:365`・`test_backend.py:320-324`: serve と部品の版の一致。
- `src/studio/tests/test_api.py:72,551`・`src/cut2resolve/tests/test_serve.py:91,414`・`src/home/tests/test_mount.py:296,334`: `/api/ping` の版を定数と比べる。
- `src/ui-kit/tests/e2e_styleguide.py:53-114`: 版の帯の e2e。`src/ui-kit/tests/uikit_stub.cjs:62` と `test_uikit_stub.cjs:15` は ui-kit.js の `version` を読む。

### A-5. push の検査

- `dev/push_helper.py` には版の検査が無い(`version` の語が 0 件)。キー・個人データ・動画・5MB 超を見る(CLAUDE.md の記述どおり)。版の確認は push の検査の外。

## B. 設定ファイル

### B-1. 置き場所と読み書きの部品

| 設定 | 置き場所 | 読み書きの部品 | 形 |
| --- | --- | --- | --- |
| ホーム | `app/prefs.json` | `src/home/prefs.py:401` で `ytt.settings.SettingsFile` | 節 8 系統(autorun・streamer・keymap・intake・backup・hidden・live・accuracy)。`PATCHABLE` で節ごとに検査 |
| スタジオ 画面 | `studio/settings-ui.json` | `src/human/review/store.py:451` で `SettingsFile`(indent=None・32KB) | 節 analyze(約 18 項目)・review(約 30 項目) |
| スタジオ 出力先 | `studio/settings.json` | `src/studio/serve.py:542`・`src/ytt/studio_env.py:166-193` | `outDir` の 1 鍵 |
| 編集 | `transcribe/settings.json` | `src/ytt/settings.py:185-188` の `SettingsFile`(400KB)。`load_settings`・`patch_settings`・`merge_settings`・`replace_settings` | 平らな 1 段。約 35 鍵(認識 約 20・パック 7・rowEdge・cutSilence・用語集・置換・keymap・evalDirs など)。`SETTINGS_PATCH_KEYS` が 12 鍵 |
| cut2resolve | なし | - | リクエストで受け取る(既定 -35dB 等が 4〜5 か所に重複) |
| 録画 | `recorder/settings.json` | `src/pipeline/ingest/recorder.py:80`・`:87` | folder の 1 鍵(prefs の live.folder と二重) |
| 分析 | `analytics/config.json` | (未確認。`src/analytics/` の内部) | url・secret・enabled・planPerWeek・boundary |
| 入口の作業データ | `settings.json`(`src/home/appwindow.py:31` の SETTINGS_NAME) | 読み取りのみ確認 | - |

書き込み口の総数(呼び出し箇所の数。読み・書きを別数えにすると概数):
- `SettingsFile` を作る所: 3(prefs・review の settings-ui・ytt の編集用)。
- 直接 `json` で読む所(`read_json` 系): 約 12 か所(eval 道具 5・datadir・studio_env・recorder・live.py・live_detect・launch・handoff_io・eval_marks)。
- 直接書く所: 3(studio_env の outDir・recorder の settings・prefs 経由の atomic_write)。

### B-2. 入口の設定の画面

- `src/home/settings/schema.json`: 形式 version 1・sections 8(general・home・live・studio・editor・pack・analytics・keys)。
- 節ごとの鍵数は schema の列挙の形が違い、自動では数えられなかった(目視で確認が要る)。
- 設定の画面(`src/home/settings/settings.js`)が読むのは prefs(ホーム)側。スタジオ・編集の値は各 ⚙(`UIKit.settings.mount`)で別に出す。

### B-3. 「設定 1 ファイル」にするときの変更箇所(見積もり)

- `src/ytt/settings.py` の `SettingsFile` を使う 3 か所を、1 つのファイルの節として読み書きする形へ。ホーム(prefs.py:401)・スタジオ(store.py:451)・編集(settings.py:185-188)の 3 つの置き場所。
- 直接読み書きしている約 15 か所(上の B-1 の一覧)を 1 つの読み口に寄せる。特に `studio/settings.json`(outDir)・`recorder/settings.json`・`analytics/config.json` は別の形式なので節に移すと migration が要る。
- 編集の平らな 1 段(`SETTINGS_PATCH_KEYS` の検査)と節の形(ホーム・スタジオ)を同じ形にする場合、検査と `PATCHABLE` の表の作り直しが必要。
- `docs/spec/settings.md` の「2. 今の置き場所」と「5. 新しい設定を足すときの決まり」を更新。`src/ytt/__init__.py:24-25` の説明文も直す。
- `localStorage` 側(テーマ・文字・キーの帯など 6 項目)は今の方針どおり窓ごとのまま(prefs へ入れるかは別判断)。

## 注意
- 上の数は grep による概数。特に「読み書きの所の数」は呼び出しの書き方で増減する。
- 分析の config の読み書き部品と、C# 側の版の定数は未確認。
