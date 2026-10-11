# RV 下調べ 3: 画面(UI)

状態(2026-10-11): 読むだけの下調べ(Sonnet が DOM の id を機械で突き合わせ、残りを grep で確かめた)。画面は開いていない。

## 1. 今の画面(配り方は `src/app/server.py:572-598` の `STATIC` 表・取り込んだ serve が `/studio/…`・`/transcribe/…` の部品を配る)

| URL | HTML | 読む物 |
| --- | --- | --- |
| `/` ホーム | `src/home/portal.html` | ui-kit・`portal.css`・`portal.js`・`portal-edit.js`。動的に `cases-panels/new.js`(→ `studio/rank.js`・`queue.js`・`collab.js`) |
| `/cases` 案件 | `src/app/ui/cases/index.html` | `cases.*`・`panels/{cand,proof,cut,machpick}`・`edhost.js`。動的に `studio/review.js`・`transcribe/app-*.js`・`app.js`・`cut.js`・`pack-tab.js`・`/live/hls.min.js` |
| `/check` 確かめる | `src/app/ui/check/index.html` | `check.*`・`check-player.js`・`check-cards/{value,read,voice,time}.js`(V1) |
| `/settings` 設定 | `src/home/settings/index.html` | `settings.*`・`/settings-schema.json` |
| `/analytics/` 分析 | `src/analytics/web/index.html` | ui-kit・`app.*` |
| 古い URL | — | `src/app/redirects.py` で 302(`?drill=1` → `/cases?c=eval#proof` も残る) |

- **どの画面からも読まれないファイルは 0 本**(57 本を確認)。`src/ui-kit/styleguide.*` は手で開く見本(残す)。
- ui-kit の写しは無い(`dev/sync_ui_kit.py` の写し先は空)。版の表記がずれる: `ui-kit.js:1`・README は v27・`ui-kit.css:437` は v28・`ui-kit.css:1` の見出しは「v6〜v23」・`ui-kit.js:3` に「sync_ui_kit で写す」・README の `data-ui-appnav` の値が古い。
- AGENTS の「画面は 3 枚」は `/check` を足す前の文。

## 2. いちばん大きい残り: 「見えないが生きている」コード
RS8 C4 で編集の `index.html` を消したので、`app.js` の `!EDIT_HOST` の枝は通らない。`edhost.js` は編集のテンプレートの `T.menu`・`T.nodoc` を組み立てるが、`panels/proof.css:11-13` が `#menuPanel`・`#noDoc` などを隠している。**画面に出ないのに DOM と JS は生きている**。

### 2-1. 編集(`src/editor/`)

| 機能 | テンプレート | JS | 状態 |
| --- | --- | --- | --- |
| 評価ドリルの帯とカード | `app-tpl.js:9-31,321-326` | `app-learn.js:263-505`・`app-core.js`・`app-jobs.js`・`app-rows.js`・`app-tools.js`・`app.js` に点在 | 届かない(消えた機能) |
| 新しく文字起こし(ファイル・フォルダ・マーク)・文字起こしせずに開く・フォルダの一括 | `app-tpl.js:~249-320` | `app-jobs.js:6-188`・`app-tools.js:483-540`・`app.js:1141,1253` | 隠れたメニューの中(消えた機能) |
| 履歴の検索・絞り込み・まとめて実行 | `app-tpl.js:~328-358` | `app-list.js` ほぼ全部(263 行) | 隠れている。ただし `loadList()` は案件の画面でも呼ばれる = `S.list` の読み手を確かめてから |
| まとめて付け替える | `app-tpl.js:218-233,358` | `app-tools.js:63-234`(約 170 行) | 届かない。1 本ずつの「動画を選び直す」は生きている |
| 名簿から用語集へ | `app-tpl.js:309-311` | `app-learn.js:506-530` | 隠れている。`S.roster` は名前の候補にも使う = 読み込みは残す |
| 精度・学習・基準のカード | `app-tpl.js:~359-376` | `app-learn.js:6-41,230-262`・`app.js:442-470` | ホームの `portal-edit.js` に同じ id の別の実装 = 二重 |
| 空の状態の案内文 `T.nodoc` | `app-tpl.js:377-390` | — | 隠れている・文が古い(「新規」「3 パック」= improvements 6 の (1) の今の場所) |
| 左メニューの開閉 | `app-tpl.js:234-248` | `app.js:49,59-71` ほか | 届かない |
| 評価用の動画をまとめて文字起こし(⚙) | `app-tpl.js:463-471` | `app-tools.js:273-310` | **届く**。eval の整理(評価の一括)と一緒に決める |

- 合わせて **テンプレート約 160 行 + JS 約 900〜1,000 行 + `proof.css` の対応する節**(`#menuPanel`・`.clist`・`.tt-batch`・`.tt-drill*`・`.tt-rl-*`)。キーの一覧の `drill` グループ・`TX_ACTIONS_ALL` の定義も。

### 2-2. 候補のパネル(`src/studio/review.js`。約 250 行)
- 配信の選択の一覧 `#rvPick`・「一覧に無い配信・動画ファイルを開く」`#rvOpenForm`(`review.js:115-143,524-580,668-700,3288-3339`)・空の案内 `#rvEmpty`(`182-190,2773-2780`)は `panels/cand.css:462` が隠す。
- ライブの録画を開く `openLiveRecording`(`:1766`)は `cand.js` の `Studio.live.register` がいつも断る・「① へ」(`Studio.go`)は review 以外を無視。

### 2-3. 小物
- `ui-kit.js:206-212,248-255` の「他のツール」メニュー(`TOOLS`・`UIKit.tools.render`)は見本しか使わない。`url`・`base`・`setPaths` は使う。
- `portal.html:125-126` の `#docRunSteps`・`#docRunMsg` はどの JS も読まない。
- `dev/ui_audit.py:66` が無いファイル(`intake.html`・`backup.html`・`live.html` など)を並べる・`:361` は `cut2resolve/serve.py` を測る。
- `T.dialogs` のキーの説明が「1 文字起こし」「2 カット のタブ」と書く(案件の画面のタブは「校正」「カット・パック」)= 要確認。

## 3. 文書の宿題(画面)
- `docs/spec/ui-guidelines.md` が RS8 前のまま: 「ホームと 2 つのツール」・`sync_ui_kit` で写す・3 タブ・appnav「ホーム / スタジオ / 編集」。`/cases`・`/check` の記述がほぼ無い → 書き直す(RV の資料の段)。
- `plan/improvements.md` 6: (1) 「3 パック」の文(今は `T.nodoc` の中 = 2-1 で消えれば片付く)・(2) `UIKit.settingsForm` が保存のたびに全部を描き直して打っている途中の欄が消える・起動し直したあとの「合言葉が違います」で直し方が分からない。
- `plan/improvements.md` 11 節(UI の見直しの残り)の studio・editor の行(B-01・B-06 など)は画面が組み直されて大半が古い → 棚卸しして閉じる。
- WORKLOG の残り: タブを閉じたときの ConnectionAbortedError が入口の黒い画面に出る・60fps の 1 コマは手で未確認。

## 4. おすすめ
1. 編集の隠れた UI を消す(2-1)。`S.list`・`S.roster` の読み手を確かめてから。`app.js` の `!EDIT_HOST` の枝も同時に。**校正の e2e(`e2e_cases_proof`)と `test_document_save.cjs` で確かめる**。
2. `review.js` の隠れた部分を消す(2-2)。`e2e_cases_cand` と `test_cand_panel.cjs`。
3. ui-kit の版の表記と README・`ui-guidelines.md` を今に合わせる。
4. 小物(`?drill=1` の転送・`ui_audit` の名前・`portal.html` の使われない id・「他のツール」メニュー)。
5. 続けて: 3 つの画面の部品(`review.js` 3,647 行・編集の `app-*.js` 約 7,400 行)を `src/app/ui/` の下へ移すか(folders.md)。URL の `studio/…`・`transcribe/…` は変えずに入口の配り方の表で差し替えられる。
