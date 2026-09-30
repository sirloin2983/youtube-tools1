# 段5: 見せ方をそろえる
> 状態(2026-10-01): **済み**(ホーム 0.19.0・スタジオ 0.13.0・編集 0.29.0。5-2・5-3 の B-7 は「気が利く画面へ 段4」の UIKit.autorun で先に済んでいたので、この段では変えていない)。以前の状態(2026-09-29): 未着手。まとめて実行の入口を ui-kit の1つの部品にそろえ、ホームの単体の文字起こしを軽くし、見直しの残り(Could Improve 2〜4)と YouTube プレーヤーの時間切れを直す
> 全体の計画は `docs/ROADMAP.md`。行番号は 2026-09-29 時点(始める前に今のコードで確かめ直す)。版の番号は、前の段で上がっていればそこから上げる。

## 目的
- まとめて実行の入口(ホームの案件・スタジオ ① 探す・スタジオの動画の帯とマークの行・編集の題名の行・編集の履歴・書き出しのあとの自動の文字起こし)が、場所ごとに違う名前・形・進み具合の出し方になっている。数は減らさずに(B-7)、**ui-kit の1つの部品**で「何を・どこまで・だれの色で」を同じ形で見せる
- 文字起こしの一覧は編集の履歴を主にする(B-5)。ホームの「単体の文字起こし」は件数と「編集で開く」だけ
- 2026-09-27 の見直しの Could Improve の (2)(3)(4) を片付ける((1) はやらない)
- 監査20: YouTube プレーヤー本体の準備待ちに時間切れ・再試行・逃げ道を付ける

## 含む作業と順番
| # | 作業 | 大きさ | 依存 |
| --- | --- | --- | --- |
| 5-1 | B-5 ホームの単体の文字起こしを「件数 + 編集で開く」に・編集の履歴を URL で開く | S | なし |
| 5-2 | B-7a ui-kit v7 の部品 `UIKit.autorun`(入口の形・進み具合の形・言葉) | M | なし |
| 5-3 | B-7b 各入口を部品に載せ替え(ホームの案件・スタジオ ①・動画の帯・マークの行・編集の題名の行・編集の履歴・自動の文字起こし) | M | 5-1, 5-2 |
| 5-4 | Could Improve (2) スタジオのマークの一覧を「1枚の紙」の畳んだ行に | M | なし |
| 5-5 | Could Improve (3) 編集 ⚙「動画の大きさ」の選択欄の幅 | S | なし |
| 5-6 | Could Improve (4) 1024px で一覧の上の「…」だけ次の行に落ちる | S | なし |
| 5-7 | 監査20 YouTube プレーヤーの準備待ちの時間切れ・再試行 | S | なし |
| 5-8 | 版・README・guidelines・ROADMAP・WORKLOG | S | 全部 |

5-1 を先にする(ホームの単体の入口が消えるので、5-3 で載せ替える入口が1つ減る)。5-4〜5-7 は互いに独立。

## 各作業の細かい計画

### 5-1 B-5 ホームの「単体の文字起こし」を件数と「編集で開く」だけに
- 今の動き: ホームの `#unlinkedGroup` に検索・行の一覧・もっと見る・チェックで選ぶ・配信者(字幕の色)・上書き・「選んだ文書をまとめて実行」がある(`home/portal.html:70-92`・`tplDoc` `:225-237`、`home/portal.js:612-707` の `loadTxList`〜`runDocsBatch`)。同じことが編集の履歴にもある(`editor/index.html:1170-1193`、`app.js:647-730`)。
  次にやることの「実行中」の文書は `#doc-<id>` へ飛ぶ(`portal.js:782`)。`focusHash` が `#doc-` で単体のまとまりを開く(`portal.js:874-878`)
- 変えること:
  - `#unlinkedGroup` は `details` をやめて1行: 「単体の文字起こし N 件(どの配信にも紐づかない文字起こし)」+ `a.btn`「編集で開く」(`/transcribe/?list=other#tx` のような、編集の履歴を「種類: それ以外」で開く URL)。件数は今の `casesData.unlinked.length`
  - 検索・選択の一覧は軽くする。**まとめて実行は残す**(09-29 決定。`runDocsBatch`・`renderDocRun` は 5-2 の B-7 の部品に置き換える)。`loadTxList` は「次にやること」が使うので残す
  - 次にやることの文書の実行中(`runsByDoc`)と `focusHash` の `#doc-` は、`docHref(id, path, 'tx')`(編集へ直接)に替える
  - 編集: `takeUrlParams`(`app.js:2492`)に `list=other|clip|all` を足す → 左メニューの履歴(`setSideTab('files')`)を開き `#txFilter` をその値に(`L.kind` を変えて `saveListPrefs`)。`doc`・`media` と同時なら文書を開く方を優先
- 変えるファイル: `home/portal.html`・`home/portal.js`・`home/portal.css`(`.pt-doc*` の消した分)・`editor/app.js`・`home/README.txt`・`README.txt`(ホームの説明)
- テスト: `home/tests/e2e_portal.py` の 2f(`:313-325`)を「件数が出る・リンクが `/transcribe/?list=other` で始まる・選んで実行の欄が無い」に書き換え。`editor/tests/e2e_edit_tabs.py` に `?list=other` で履歴が「それ以外」で開く確認を足す。流す: ★`python -m unittest home/tests/test_launch.py home/tests/test_mount.py home/tests/test_cases.py home/tests/test_autorun.py home/tests/test_window.py`・★`python home/tests/e2e_portal.py`・★`python home/tests/e2e_autorun.py`
- リスク・エッジケース: ホームの「単体」(txindex の unlinked = どの案件にも入らない文書)と編集の「それ以外」(`!hasClip`)は同じ集合ではない(スタジオから消した配信の切り抜きは unlinked だが hasClip)。件数が合わないことがある → リンクの文言を「編集の履歴で見る」にし、件数はホームの数として出す(編集側の件数と比べない)。編集が動いていないときもリンクは出す(開いた先で案内が出る)
- 終わりの条件: ホームの単体は1行だけ・ホームからの文書のまとめて実行の入口は無い(編集の履歴にある)・次にやることの実行中の文書は編集へ直接開く・e2e が通る

### 5-2 B-7a ui-kit の部品 `UIKit.autorun`(v7)
- 今の動き: 同じ API(ホームの `/api/autorun`・`start`・`start-new`・`start-docs`・`cancel`)なのに、入口ごとに部品と言葉が違う。
  入口の形: ホームの案件 = select の3つの形 +「実行」(`home/portal.html:202-216`)、① 探す = `ui-menu` + 「選んだ配信 N 本をまとめて実行」(`studio/rank.js:167-175`)、動画の帯 = `ui-menu` の中に形ごとのボタン3つ(`review.js:133-146`)、
  マークの行 = 「…」の中の「この後を ▸」(`review.js:1524`)、題名の行 = 「この文書を最後まで」(`editor/index.html:1249-1259`)、履歴 = チェック +「まとめて実行」(`index.html:1182-1193`)。
  進み具合の言葉も3通り: ホーム `STEP_STATE`「まだ・済み・一部失敗」(`portal.js:16-17`)/ スタジオ `AUTO_STEP`「待ち・済・一部」(`review.js:1984-1985`)/ 編集 `STEP_STATE`「待ち・済・一部」(`app.js:667-668`)
- 変えること(部品は DOM と言葉だけ。API を呼ぶのは今までどおり各画面):
  - `UIKit.autorun.menu(host, {target, count, modes, top, overwrite, streamer, onStart})`: `details.ui-pop.ui-autorun` を作る。summary は必ず「まとめて実行」(アイコン + `▾`)。中身は上から「対象: この配信 / 選んだ 3 本 / このマーク / この文書」→ 形(1つなら文字だけ、複数ならラジオ)→ 採用する数(`full` のときだけ)→ 配信者(字幕の色。`UIKit.streamer.attach`)→ 上書き(文書のときだけ)→ 手順の並び(「書き出し → 文字起こし → パック」)→ primary「始める」1つ。`onStart({mode, top, streamer, overwrite})` を返す
  - `UIKit.autorun.status(el, run, {onCancel, homeHref})`: 札(順番待ち / 実行中 / 完了 / 止まりました / 中止)+ 手順ごとの小さな札 + 中止(実行中のとき)+ 「ホームで見る」。1行でも複数行でも同じ形
  - `UIKit.autorun.MODES` / `STEP_LABEL` / `RUN_LABEL` / `stepsOf(mode)`: 言葉の正。home/autorun.py の `MODES`・`MODE_STEPS`(`home/autorun.py:31-33`)と同じ並び(ui-kit のテストで表を比べる)
  - 案: API の呼び出しまで部品に入れる(入口の URL を ui-kit が計算)と各画面のコードはさらに減るが、ホームは `/api/`、取り込んだ画面は `../api/` で道が違い、失敗時の言い分(「この配信はすでに実行中」の見分け `review.js:1998-2001`)も画面ごとに違う。**DOM と言葉だけにする**(壊れる範囲を小さく)
  - 文言は `textContent` で入れる(題名・配信者名が入る。XSS を作らない)。CSP の都合でインラインのハンドラは使わない
- 変えるファイル: `ui-kit/ui-kit.js`・`ui-kit/ui-kit.css`・`ui-kit/README.md`(v7 の節)・`ui-kit/styleguide.html`・`ui-kit/styleguide.js`・`ui-kit/tests/e2e_styleguide.py` → `python dev/sync_ui_kit.py`
- テスト: `e2e_styleguide.py` に「メニューの形(形が1つ/3つ・数・上書き)・`onStart` の値・状態の札・中止」を足す。home/autorun.py の `MODES`・`MODE_STEPS` と ui-kit の表が同じかを確かめる unittest(★`dev/tests/test_ui_kit_sync.py` か `home/tests/test_autorun.py` に1件)。★`python -m unittest dev/tests/test_ui_kit_sync.py`
- リスク・エッジケース: ui-kit を変えると全画面に効く(v6 のテストがすべて通ることを確かめる)。`ui-menu` と `ui-pop` の閉じ方の差(外のクリック・Esc)→ `ui-pop` にそろえる。375px では中身を左寄せ(`data-align=left`)にしてはみ出さない
- 終わりの条件: 部品が styleguide にあり、言葉の表が1か所・サーバーの表と一致・v7

### 5-3 B-7b 各入口を部品に載せ替える
- 今の動き: 5-2 のとおり。書き出しのあとの自動の文字起こしは設定(`studio/settings.js:44-49`)+ トーストだけ(`review.js:1991-2003`)
- 変えること(入口の数・場所は変えない。形と言葉だけ):
  - ホームの案件(`portal.html:202-216`・`portal.js:369-417`): select +「実行」→ `autorun.menu`(形3つ)。進み具合 `.pt-auto-steps` → `autorun.status`
  - ① 探す(`rank.js:167-175`・`:344-360`): `#rkAuto` の中身 → `autorun.menu(target:'選んだ N 本', modes:['full'])`。本数は `count()` で更新
  - 動画の帯(`review.js:133-146`・`:2004-2015`): ボタン3つ → `autorun.menu`(形3つ)。帯 `#rvAutoBar`(`:2017-2045`)→ `autorun.status`
  - マークの行(`review.js:1524`・`:1709`): 「…」の中の項目は残し、文言を「まとめて実行(このマーク): 書き出し → 文字起こし → パック」に。押すと同じ `autorun.menu` を小さく開く(配信者の欄を毎回出すかは下の「聞くこと」)
  - 編集の題名の行(`index.html:1249-1259`・`app.js:694-707`)と札 `#pillAuto`(`app.js:708-718`): `autorun.menu(target:'この文書')` + `autorun.status` の短い形
  - 編集の履歴(`index.html:1182-1193`・`app.js:720-730`・`renderRuns` `:666-678`): 「選んで、まとめて実行」のチェックは残し、選んだあとの欄を `autorun.menu(target:'選んだ N 本')`、`#txRuns` を `autorun.status` の並びに
  - 書き出しのあとの自動の文字起こし: 始めたときのトーストを「まとめて実行(文字起こしまで)を始めました」にそろえ、進み具合は動画の帯の `autorun.status` に出す(今と同じ所)
  - 「案件の一覧」「案件で見る」リンク(`rank.js:174`・`review.js:2031` の `../#cases`)は「ホームで見る」にそろえる
- 変えるファイル: `home/portal.html`・`home/portal.js`・`home/portal.css`・`studio/rank.js`・`studio/review.js`・`studio/review.css`・`studio/app.css`・`editor/index.html`・`editor/app.js`・各 `README.txt`
- テスト: 要素の id を変えたら e2e を直す。★`python home/tests/e2e_portal.py`・★`python home/tests/e2e_autorun.py`・`python studio/tests/e2e_ui.py` と `python studio/tests/e2e_ui.py --mounted`(`:440-503` の自動の文字起こし)・★`node --test studio/tests/test_review.cjs`(`pollAuto` を切り出し範囲の外に置いたままにする `:52`)・`transcribe-tool` の `editor/tests/e2e_ui_mounted.py`・`editor/tests/e2e_edit_tabs.py`・★`python dev/tests/e2e_pipeline.py`
- リスク・エッジケース: 入口から開いていない(`TOKEN` が無い)ときは今までどおり隠す(`review.js:2051`・`app.js:2760-2761`・`rank.js:387`)。二重押し(始めている間は「始める」を止める)。未保存のマーク・文書・カットを先に保存する処理(`review.js:2008`・`app.js:699`)は消さない
- 終わりの条件: 7か所(5-1 で消えるホームの単体を除く)で summary が「まとめて実行」・中身の並び・状態の言葉が同じ。e2e が通る

### 5-4 Could Improve (2) スタジオのマークの一覧を畳んだ行の「1枚の紙」に
- 今の動き: マークの行は1件ずつ角丸・枠・隙間 5px のカード(`studio/review.css:302-311`)。畳んだ行 `.folded` も同じカード(`review.js:1513-1533`)。ホームと編集は `.ui-sheet`(外枠1つ・行の間は細い線。`ui-kit/ui-kit.css:378-379`、IMPLEMENTATION.md の 8)
- 変えること: `#rvList` を1枚の紙に(外枠1つ・`gap:0`・行の間は `border-top`)。畳んだ行は角丸・影なしで1行の高さ(時刻・長さ・札・ラベル・判定)をそろえる。左の状態の色の線(採用・不採用・候補・書き出し済み)は残す。
  開いた行・選んだ行だけ背景を `--panel-2` にして少し余白を足す(紙の中で開いた所が分かる)。判定・再生・削除のボタンは今の位置のまま
- 変えるファイル: `studio/review.css`(`.rv-list`・`.rv-mark-row`)・必要なら `review.js` の `markHTML` にクラスだけ
- テスト: `python studio/tests/e2e_ui.py` と `python studio/tests/e2e_ui.py --mounted`(一覧の操作・判定のキー)。見本のデータ(`python dev/demo_env.py`)で 1440・1024・390 × 明るい/暗いの写真を撮って見比べる
- リスク・エッジケース: `.sel` の枠(`review.css:310`)が紙の中で隣の線と重なる → 選んだ行は `outline` にする。スクロールの中の `sticky` と `scrollbar-gutter`(`:302`)を壊さない。390px で1行が2段に割れるときもボタンの位置をそろえる
- 終わりの条件: 畳んだ行がホーム・編集と同じ「1枚の紙」に見え、写真で確かめた

### 5-5 Could Improve (3) 編集 ⚙「動画の大きさ」の選択欄の幅
- 今の動き: 設定の節の select は `width:auto`(`ui-kit/ui-kit.css:415-417`)。「音声だけ聞く(映像を隠す)」の長い選択肢(`editor/index.html:1595`)で、この欄だけ幅が広い
- 変えること: 選択肢の文言を「音声だけ」にし、説明は欄の `title` と下の小さい説明に移す(編集の中だけ・ui-kit を変えない)。
  案: ui-kit で設定の select の幅を一律(例 9em)にする方法もあるが、スタジオの設定の select まで変わり確かめる範囲が増える。**文言を短くする方**にする
- 変えるファイル: `editor/index.html`
- テスト: `editor/tests/e2e_ui_mounted.py`・`editor/tests/e2e_edit_tabs.py`(`#vVid` を使う所があれば文言を合わせる)。写真で 1440・390
- リスク・エッジケース: 値(`a`)は変えない(`app.js:149` の検査・保存した設定がそのまま使える)
- 終わりの条件: ⚙ の編集の節で select の幅がそろう

### 5-6 Could Improve (4) 1024px で一覧の上の「…」だけ次の行に落ちる
- 今の動き: 一覧の上の道具 `.tt-rowbar` は折り返しあり(`editor/index.html:335-338`・`:728-732`)。並びは 検索・絞り込み・「次の未校正 Shift ↓」・「…」・件数(`:1266-1276`)。1024px では最後の「…」だけが次の行に落ちる
- 変えること: 「次の未校正」・「…」・件数を1つの `nowrap` の箱に入れ、折り返すときは3つ一緒に落ちるようにする。列が狭いとき(`@container editor` の幅で)「次の未校正」のボタンの中の `<kbd>` を隠す(キーはキーの帯と title に出ている)
- 変えるファイル: `editor/index.html`(HTML と埋め込み CSS の、ui-kit の印の外の部分)
- テスト: `editor/tests/e2e_ui_mounted.py`・`editor/tests/e2e_edit_tabs.py`。1024・1440・390 の写真で「…」が単独で落ちないこと
- リスク・エッジケース: 一覧の上の固定(`:742` の sticky)の高さが変わると `--khh`(`app.js` の ResizeObserver)で行の位置の計算が変わる → 行へ移動したときに隠れないか確かめる
- 終わりの条件: 1024px で「…」が単独で次の行に落ちない

### 5-7 監査20 YouTube プレーヤーの準備待ちに時間切れと再試行
- 今の動き: IFrame API の読み込みには 12 秒の時間切れがある(`studio/review.js:587-599`)が、`new YT.Player`(`:688-692`)のあと onReady / onError のどちらも来ないと「プレーヤーを準備しています…」のまま(`:678` の `phMsg`)。
  また読み込みの時間切れの後で script が遅れて読めても `ytApiP = null` にしたまま・再試行で script を二重に足す
- 変えること:
  - `new YT.Player` のあとに準備待ちのタイマー(20 秒。`onReady`・`onError`・`unmountPlayer` で止める)。時間切れなら `showNotice`(`:602-608`)に「YouTube のプレーヤーの準備が終わりません(回線・埋め込みの制限のおそれ)」+ ボタン「もう一度試す」(`mountPlayer()`)+ 今ある「YouTube で開く」+「時刻の手入力でマークは続けられます」
  - `new YT.Player` が例外を投げたときも同じ案内
  - `loadYTApi`: 時間切れのタイマーを resolve で止める。再試行では前の script を消してから足す(二重に読まない)
  - 再試行のボタンは `data-act` で `#rvNotice` のクリック(`:1826`)に足す(CSP のためインラインにしない)
- 変えるファイル: `studio/review.js`
- テスト: `studio/tests/e2e_ui.py` に「YouTube の iframe_api を、onReady を呼ばない偽物で返す」(`page.route` で `https://www.youtube.com/iframe_api` に JS を返す。CSP はスタジオだけ youtube.com を許しているので読める)→ 時間切れの案内と「もう一度試す」が出る・押すともう一度準備する、を足す。時間切れの秒はテストで短くできるように `S` の値(`S.ytReadyMs`)にする。★`node --test studio/tests/test_review.cjs`(切り出し範囲の境目の文字列を変えない)
- リスク・エッジケース: 遅い回線で 20 秒後に onReady が来る → 案内を出したあとでも onReady が来たら案内を消して使えるようにする(トークン `playerToken` で古いプレーヤーの通知は捨てる)。自動の再試行はしない(YouTube に何度も繋ぎに行かない)
- 終わりの条件: 準備が終わらないとき、時間切れの案内・再試行・YouTube で開く・手入力の案内が出る

### 5-8 版・文書
- `docs/spec/ui-guidelines.md` の 1(用語: 「まとめて実行」の部品の言葉)と 4(一覧: マークの一覧も1枚の紙)、`.design/ui-overhaul/IMPLEMENTATION.md` に「段5(2026-09-29〜)で決めたこと」、`docs/ROADMAP.md` の B-5・B-7 と監査20、WORKLOG

## 版の上げ方
その時点の版から上げる(ほかの段で上がっていれば、その次)。今の版で書くと:
- ui-kit v6 → **v7**(5-2。`ui-kit.js` の先頭・README.md)→ `python dev/sync_ui_kit.py`
- 入口(ホーム)0.12.0 → **0.13.0**(`home/launch.py` の VERSION・`home/README.txt` の見出し)
- スタジオ 0.11.0 → **0.12.0**(`studio/serve.py` の SERVER_VERSION・`core.js` の APP_VERSION・README.txt の見出し)
- 編集 0.21.0 → **0.22.0**(`editor/serve.py`・`app.js`・README.txt)
- cut2resolve は変えない

## 実機で確かめること
- start.bat で起動し直してから: ホームの単体が1行・「編集で開く」で履歴が「それ以外」で開く
- 7か所のまとめて実行が同じ形(summary・対象・手順・配信者の色・始める)。実際に1本(案件の「採用後を全部」)流して、ホームと動画の帯と編集の題名の行に同じ札が出る
- スタジオのマークの一覧(本物の配信の 30 件ほど)で、畳んだ行が読みやすいか・判定のキーが今までどおり
- 編集 ⚙ の欄の幅、1024px の窓で一覧の上の道具
- 回線を切った状態でスタジオの YouTube の配信を開き、時間切れの案内と「もう一度試す」

## 決まったこと(2026-09-29 ユーザー。計画を書いたあとに聞いた分)
- **ホームの単体の文字起こしにも「まとめて実行」を残す**(B-7 の「入口を減らさない」を優先)。一覧は件数と「編集で開く」に軽くするが、選んでまとめて実行する入口は B-7 の部品で残す。
  → 5-1 の「`portal.js` の文書の検索・選択・まとめて実行を消す」は、**まとめて実行の部分を消さずに B-7 の部品に置き換える**と読み替える
- マークの行の「この後を ▸」では配信者の欄を**出さない**(動画の帯で決めた配信の設定を使う)
