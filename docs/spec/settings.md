# 設定の決まり(置き場所・画面・1 つにまとめる手順)

状態: 段 0(棚卸しと決まり)済み 2026-10-09。段 1(スタジオ「2 解析」・編集「3 パック」のタブを無くして ⚙ へ)済み 2026-10-09(スタジオ 0.24.0・編集 0.62.0。ユーザー確認済み)。段 2(S4。読み書きの共通部品 `src/ytt_core/settings.py`。ytt_core 1.6.0)済み 2026-10-09 午後(仮決め `plan/decisions.md` 3-19 (gb)〜(ge))。段 3(S5)は案(計画 `plan/data.js`)。

2026-10-09 のユーザーの依頼: 「スタジオの解析・編集のパックのように、ただの設定だけの所を設定にまわしたい。そのあと設定はそれ単体で 1 つのものにして使いやすくしたい」→「解析と編集のパックはタブごと消して設定にまとめる」。

## 1. 分ける基準(何を ⚙ 設定に置くか)

- **毎回変える値は操作のボタンの隣に残す**: URL・範囲・題名・評価用にするか、など「この 1 回」の入力。
- **一度決めたら変えない値は ⚙ 設定**: 既定値・しきい値・重み・画質・音量・fps・大きさ・自動の後処理のオン/オフ。
- **配信ごとに触ることもある値(本数・長さ・感度・モデル・言語)も ⚙ に置く**。操作の側には「前回の設定」の 1 行の要約と「設定を変える」のリンク(押すと ⚙ の該当の節が開く)。編集のパックが 10-05 からこの形で、ユーザーが使えていた。
- **配信者(字幕の色)は入力欄を作らない**(10-09 ユーザー決定)。文書に覚えている値(ホームの prefs の streamer)か、友人の依頼の指定をそのまま使う。
- 設定の節の中では「使う順」に並べ、既定値で困らないものは `details.ui-disclosure`「詳しい設定」の中(`docs/spec/ui-guidelines.md` 2-2・`ui-review-criteria.md` B-08)。
- 変えたらすぐ保存(「保存」ボタンを作らない)。失敗は ⚙ の赤い印(`UIKit.settings.status`)。既定値は欄の横か placeholder で見せ、「標準に戻す」を置く(`usability-heuristics.md` H3)。

## 2. 今の置き場所(2026-10-09 の棚卸し)

| 置き場所 | 中身 | 書き方 |
| --- | --- | --- |
| ホーム `app/prefs.json`(`src/home/prefs.py`) | 節 autorun・streamer・keymap・intake・backup・hidden・live・accuracy。ツールをまたぐ値 | `POST api/ytt/prefs` に `op` = get / patch / remember / hide。節ごとに検査して差し替え(`PATCHABLE`)。壊れたファイルは `.broken-<日時>` に退避 |
| スタジオ `studio/settings-ui.json`(`store.py`) | 節 analyze(解析の設定 18 項目)・review(③ の約 30 項目) | `PUT /api/settings {section, value}` で節を丸ごと置き換え(32KB まで) |
| スタジオ `settings.json` / `config.json` / `registry.json` | 書き出し先 outDir / YouTube API キー / 事務所の登録 | `PUT /api/outdir` / `PUT /api/config` / `PUT /api/rank/registry` |
| 編集 `transcribe/settings.json`(`ed_state.py`) | 平らな 1 段。認識の設定約 20 項目・パック 7 項目(packFps・packSize・packLoudness・packVolume・packBackup・packRender・speakerColors)・rowEdge・cutSilence・用語集・置換辞書・keymap・evalDirs など | `PUT /api/settings {patch}`(差分。600ms 遅延)と `POST /api/settings/patch`(許可した 12 キー `SETTINGS_PATCH_KEYS` だけ・検査つき) |
| cut2resolve | **設定ファイル無し**。パックを作るリクエストで全部受け取る(`src/cut2resolve/README.txt` の spec / output)。無音の既定値 -35dB / 0.6s / 0.15s が 5 か所に重複(pack.py・cut2resolve_core.py・cut2resolve.py・serve.py)。Text+ の字幕の見た目(フォント・ふち)は `resolve_textplus.py` に直書き | — |
| 録画 `recorder/settings.json` | folder(prefs の `live.folder` と二重。入口が起動時に合わせる) | `POST /live/config` |
| 分析 `analytics/config.json` | url・secret・enabled・planPerWeek・boundary | `POST /analytics/api/config` |
| ブラウザ `localStorage` | 窓ごとの表示の好み: テーマ `ytt:theme`・文字 `ytt:fs`・キーの帯 `ytt:keybar`・スタジオ ① の検索条件 `clipstudio:rank:*`・編集の表示 `tx.view.v1`・一覧の並び | 窓ごと。バックアップに入らない(入れたい値は prefs へ) |

画面の側は 3 ツールともヘッダーの ⚙(`UIKit.settings.mount`。「このツール」節 + 「全体」節)がある。それと別に「ただの設定」が操作の隣に残っていた所:

- スタジオ ②「解析」: 「解析に追加」の直下の「解析の設定」カード(`queue.js` の `#qOpts`)。押した瞬間に DOM から値を読んで送る。「画質の上限」(maxHeight)は解析で読まれていない(死んだ設定)。
- スタジオ ③: 書き出しドロワーの「書き出しの設定」(対象・精密/高速・最大画質・音量・保存先)。
- 編集 タブ 1: 「文字起こしを開始」の真上の「認識の設定」(`#recogDetails`。モデル・言語・品質・処理方式・VAD・自動の後処理・用語集)。
- 編集 タブ 2: たたき台のボタンの隣の数値(行の端を広げる上限・無音の dB と秒)。
- 編集 タブ 3: 「パックの設定」の引き出し(`#pkSettingsDrawer`。タブの中だけ)。字幕の 1 段の文字数はタブ 1 の認識の設定の中(`#optWrapV/H`)。
- ホーム: 「依頼の受付」「バックアップ」が本文のパネルで「設定を保存」ボタン付き。ライブの設定はホームの ⚙ とスタジオの ⚙ の 2 か所から同じ prefs を書く。

## 3. 段 1: タブを無くして ⚙ へ(ユーザー決定 2026-10-09)

### スタジオ(「1 探す / 2 確認・書き出し」の 2 タブに)
- 「2 解析」のタブを無くす。`#steps` の data-step="queue" を消し、番号を 1・2 に。URL パラメータ・`clipstudio:step` に queue が残っていたら rank に読み替える。
- URL を入れて「解析に追加」→ 「1 探す」の中に「URL から入れる」の小さなカード(1 行目に URL 欄・「解析に追加」・「解析せずに確認画面を開く」)。ホーム・ライブから URL を受け取る口(`?url=` → `#qParam` の案内)もこのカードへ。
- 順番待ちの一覧(中止・やり直し・確認する・終わったものを消す)→ 同じカードの下に短い一覧(件数のバッジはヘッダーの「解析中」に残す)。
- 「解析の設定」18 項目 → ⚙「このツール」の「解析」節。「画質の上限」は消す(保存値は読み捨てる)。`S.enqueue` は DOM ではなく読み込んだ設定(analyze 節)から値を作る。要素の id(`useAudio`・`count`・`length`・`sens`…)は残して e2e を壊さない。
- 「書き出しの設定」は書き出しドロワーに残す(書き出す直前に見る値なので。段 1 では動かさない)。
- 版: スタジオ 0.23.3 → 0.24.0(`core.js` の APP_VERSION・`serve.py` の SERVER_VERSION・README)。テスト: `test_review.cjs`・`e2e_ui.py`(+`--mounted`)・`e2e_analyze.py`・`test_api.py`。

### 編集(「1 文字起こし / 2 カット」の 2 タブに)
- 「3 パック」のタブを無くす。タブの `#tabPack` と `pack-tab.js` の描き手は、タブではなく「2 カット」の末尾の「パックを作る」カードに描く(カットを決めた流れの続き)。
- 「パックを作る」カードに残すもの: 前回の設定の 1 行要約 + 「設定を変える」(⚙ のパックの節を開く)・地図・注意・「パックを作る」ボタン。「詳しく」の中に zip でダウンロード・残す区間(.cut-plan.json)の保存・出力先・開始タイムコード・リール名。
- 配信者(字幕の色)の欄 `#pkWho` と「話者の名前がメンバーと合えば色に」`#pkSpk` はカードから消す。配信者は文書に覚えている値(`UIKit.streamer` が prefs から出す値)か友人の依頼の指定をそのまま `output.streamer` に。`#pkSpk` の値(speakerColors)は ⚙ のパックの節へ。
- 「パックの設定」(fps・大きさ・音量のそろえ方・音量・予備・粗編集・行の後の余白・話者の色)→ ⚙「このツール」の「パック」節。字幕の 1 段の文字数(`#optWrapV/H`)もここへ移す(認識の設定から外す)。
- 「認識の設定」はタブ 1 に残す(段 1 では動かさない。文字起こしを始める直前に見る値が多いので、要約 + リンクに変えるかは使ってから決める)。
- 版: 編集 0.60.0 → 0.61.0(`app.js` の APP_VERSION・`serve.py`・README)。テスト: `src/editor/AGENTS.md` の一覧 + `e2e_edit_tabs.py`・`e2e_edit_pack.py`・`e2e_edit_cut.py`・`dev/tests/test_resolve_pack_contract.py`(単独)。
- まとめて実行(`src/home/autorun.py` の `_pack_settings`)は編集の settings.json の同じキーを読むので、保存先は変えない。

### 共通
- `docs/spec/ui-guidelines.md` 2-2 の「設定は ⚙ の 1 か所」に合う。画面を変えたら `py -3.10 dev/ui_audit.py all --demo` の Must 0 件。
- 旧い保存値(localStorage の `clipstudio:step` = queue・`tx.tab` = pack など)は読み替えて捨てる。設定ファイルの中身とキーは変えない(写し戻し・バックアップに影響させない)。

## 4. 段 2・3: 形をそろえる → 単体の「設定」(案)

- 段 2(S4。**済み 2026-10-09**): `src/ytt_core/settings.py` の `SettingsFile`(読む `load/read`・書く `save`・ロックの中で読み→直す→書く `update`・節を置き換える `set_section`・節の鍵を直す `patch_section(cleaner)`・最上位の鍵を検査つきで直す `update_keys(allow)`・最上位の鍵を合わせる `merge_top(skip)`)を、ホーム `prefs.py` の `Prefs`・スタジオ `store.py` の `get_ui/set_ui_section/set_ui`・編集 `ed_learn.py` の `load_settings/patch_settings/merge_settings/replace_settings` が使う。共通の決まり: 無い・読めない・辞書でない・上限より大きい = 既定 `{}` で動き、次に書くときに `.broken-<日時>` へ退避してから書く(消さない)・原子的な書き込み・大きさの上限(ホーム 1MB・スタジオ 32KB・編集 400KB。超えたら `SettingsTooLarge` → 413)・節の名前は `[A-Za-z][A-Za-z0-9_-]{0,31}`。**ファイルは分けたまま**(`data-location.md` とバックアップの形・ツール単独のテストを変えないため)。**API の形はそのまま**(各ツールの画面を書き換えずに済ませた。`{op, section, value}` に揃えるのは段 3 で設定ページが同じ API を使うときに)。既定値・検査の関数は各ツールに残した(ホーム `CLEANERS/DEFAULTS`・編集 `SETTINGS_PATCH_KEYS`。段 3 のスキーマで 1 か所にする)。cut2resolve の既定値は既に 1 本(`serve.py DEFAULTS` ← `pack.Request` ← `cut2resolve_core DEFAULT_*`)で、重複は編集 `ed_learn.CUT_SILENCE_RANGE`(範囲)だけ = 段 3 で。テスト `src/ytt_core/tests/test_settings.py`(10 件)。
- 段 3(S5): ホームに `/settings/` の 1 ページ。左に「全体 / ホーム / スタジオ / 編集 / パック(cut2resolve) / 録画 / 分析」。各節は**宣言的なスキーマ(キー・型・範囲・既定値・ラベル・1 行説明)から ui-kit が描く**(`UIKit.settingsForm`)ので、ラベル・既定値の表示・範囲の検査・「標準に戻す」・保存の印が自動で付く。各ツールの ⚙ は同じ描き手で自分の節だけを出す。検索・JSON の書き出し / 読み込みもここ。
- 段 2・3 で一緒に直すもの: ライブの設定を 1 か所(ホーム)に・録画フォルダの二重保存・ホームの受付とバックアップを自動保存に・編集の「config.json」の古い表記(`AGENTS.md`・コメント)・Text+ の字幕の見た目を設定にするか(友人の PC のフォントに依存するので要相談)。

## 5. 新しい設定を足すときの決まり

1. **どこに保存するか**: ツールをまたぐ(まとめて実行の既定・配信者・キー・ライブ)→ ホーム prefs の節。そのツールだけ → そのツールの設定ファイル。窓ごとの見た目だけ → localStorage。案件(文書・配信)ごとに違う値 → その文書・配信のデータ(設定ファイルに入れない)。
2. **画面は ⚙ の「このツール」節**。操作の隣に置くのは「毎回変える値」だけ。配信ごとに触る値は要約 1 行 + 「設定を変える」。
3. **既定値はサーバー側の 1 か所**(検査の関数と同じ所)。画面の HTML の value は見せるだけで、読み込み後は保存値で上書きされる。
4. **キーを消すとき**は読み捨てる(例外にしない)。名前を変えるときは 1 版だけ旧名も読む。
5. キー名と置き場所をこの文書の 2 の表に足す。
