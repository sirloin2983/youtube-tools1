# ui-kit(共通の見た目)v18

ツール(入口・切り抜きスタジオ・編集)で共通の、色・文字・部品・ダーク/ライト切り替え。
将来1つのアプリに統合するときに見た目がそろっているよう、正本はここ1か所にして、各ツールへ写す。

- `ui-kit.css` … 色の変数(トークン)と部品(ボタン・入力・カード・タブ・表・通知など)
- `ui-kit.js` … テーマ切り替え(`window.UIKit.theme`)と「他のツール」メニュー(`window.UIKit.tools`)。v2(2026-09-26・段階7)で次を追加:
  - `UIKit.life` … 画面を離れた・戻った。`onLeave(fn(reason))`(`'hidden'` タブの切り替え・`'blur'` 別の窓へ・`'pagehide'` 閉じる直前)、
    `onReturn(fn(reason))`(`'visible'`・`'focus'`・`'pageshow'`)、`isAway()`。**画面で visibilitychange を直接使わずにこれを使う**
    (窓を並べると隣の窓をクリックしてもタブの切り替えは来ない)。埋め込み(iframe)にフォーカスがあるときは離れたことにしない。
    離れた・戻ったは組で1回ずつ知らせる(例外: `'blur'` のあとに `'hidden'` になったとき・閉じる直前は、もう一度知らせる)。`'blur'` のときは重い処理・再生の停止をしないのが決まり
  - `UIKit.report(message, info)` … 画面のエラーを入口の記録(`app\logs\client-errors.jsonl`)へ。捕まえられなかったエラー(error・unhandledrejection)は自動で送る。
    同じエラーは1回・1回の表示で20件まで。入口の外(合言葉 `ytt-token` が無い画面)では送らない
  - `UIKit.win` … `isApp()` 窓(Edge のアプリモード。`display-mode: standalone`)で開いているか、`open(url)` 入口に頼んで開く。
    窓の中の `target="_blank"`(と Ctrl・Shift・中クリック)のリンクは自動で: このパソコンの画面 → 窓、外のサイト → いつものブラウザ
  - `UIKit.streamer`(v5・2026-09-27)… 配信者の名前(字幕の色)の欄。`<input data-ui-streamer>` を置く(画面を後から作るときは `UIKit.streamer.attach(input)`)と、
    名前の候補(datalist)・色の見本・合う人の表示を付ける。照らし合わせは入口(`api/ytt/streamer-colors` → `src/ytt_core/colors.py`)。値は名前のまま送る。
    値を画面から入れたら `UIKit.streamer.set(input, 名前)`。合う人が決まるたびに input に `ui-streamer` イベント(detail: 人 | null)。
    同じ名前ではもう一度照らし合わせない(欄から離れたときに説明の文が変わって、隣のボタンのクリックが外れたため)
  - `UIKit.portal`(v5・2026-09-27)… 入口へ戻るリンク(`a[data-ui-portal]`。「他のツール」の入口・`[data-ui-home]`・案件の画面の「← 入口へ」)は、
    入口がほかの窓・タブで開いていれば移らずに入口の窓を前に出す(`api/ytt/focus-portal`)。入口の画面は `UIKit.portal.listen()` で答える(BroadcastChannel `ytt-portal`)
  - 入口の API は相対パス `api/ytt/…` で呼ぶ(入口の画面 → `/api/ytt/…`、取り込んだツール → `/studio/api/ytt/…`。どちらも入口が受け持つ)
- `styleguide.html` … 見本。ブラウザで直接開いて、ダーク/ライトの両方で確認する

## 使い方
1. 正本(このフォルダ)を直す
2. `python dev/sync_ui_kit.py` で各ツールへ写す(`--check` でずれの確認だけ)
3. 各ツールのテストに加えて `python -m unittest dev/tests/test_ui_kit_sync.py` が通ること

各ツールでの読み込み:
- スタジオ: `<head>` で `<script src="/ui-kit.js"></script>`(CSS より先・同期)→ `<link rel="stylesheet" href="/ui-kit.css">` → ツール固有の CSS
- 編集(文字起こしツール): CSS は `index.html` の中の `/* ui-kit:css:begin */ … end */`(`<style>` の先頭)に埋め込み、JS は `ui-kit.js` の写し
- cut2resolve: 画面を「編集」に統合して消したので、写さない(2026-09-26)

## テーマ
- `<html data-theme="light|dark">` を `ui-kit.js` が付ける。初回は OS の設定に合わせ、⚙ 設定の「テーマ」で選ぶと保存する(v14 でヘッダーの切り替えボタンはやめた。`[data-theme-toggle]` を付けたボタンがあれば今までどおり動く)
- 保存場所は localStorage の `ytt:theme`(`light` / `dark`。無ければ OS に合わせる)。ツールごとにポートが違うので保存は別々
- 色は必ず変数(`var(--panel)` など)で書く。固定の色を書くと片方のテーマで読めなくなる
- 主な変数: `--bg` `--panel` `--panel-2` `--panel-3` `--field` `--line` `--line-2` `--ink` `--ink-2` `--ink-3` `--accent` `--accent-ink` `--accent-soft` `--ok` `--warn` `--danger` `--info`(+ `-soft`)、グラフ用 `--c-audio` `--c-chat` `--c-com`

## ヘッダーの書き方
`styleguide.html` の `<header class="ui-header">` をそのまま使う(ブランドのアイコン・ツール名・版・タブ・他のツール・設定)。
ブランドの色は `.ui-brand-mark[data-tool=studio|transcribe|cut2resolve]`。

## v3(2026-09-26・画面の全面見直し)
共通のルールは `docs/spec/ui-guidelines.md`(用語集・ヘッダー・ボタンと札・一覧・段階的に見せる・狭い画面)。
- 状態の札(`.pill`)の文字は `--ok-ink` `--warn-ink` `--danger-ink` `--info-ink` `--accent-ink2`(明るいテーマで 5.5:1 以上)。札は枠なし・押せない表示だけ
- 入口へ戻る(v18 で消した): ヘッダーに `<a class="ui-home" data-ui-home hidden>`(と `data-ui-cases`)。入口に取り込まれているとき(画面に `ytt-token` がある)だけ ui-kit が `/`・`/cases.html` を入れて出す。
  「他のツール」のメニュー(`UIKit.tools.render`)も、取り込まれているときは先頭に「入口」「案件の一覧」を出す。`UIKit.tools.mounted()`
- 一覧: `.ui-listbar`(検索は残りの幅いっぱい)・`.ui-count`・`details.ui-group`(+ `.ui-group-n`・`.ui-group-side`)・`.ui-next`(次にやること)
- 言葉の説明: `<abbr class="ui-term" title="1文の説明">EDL</abbr>`
- `.lag.keep`: 短いラベル + select の組を折り返さない(狭い画面で1文字ずつ縦に割れないように)
- `UIKit.fmt.ago(ms)`(「3日前」「今日 14:32」)・`UIKit.fmt.date(ms)`・`UIKit.fmt.dur(秒)`・`UIKit.esc(s)`

## v4(2026-09-26・「編集」: 文字起こし + cut2resolve の統合。`docs/design/edit-tool-design.md`)
- ツールの一覧(`UIKit.tools`)の transcribe の表示名を「編集」(カット・字幕・Resolve へのパック)に
- cut2resolve は `hidden: true`: 一覧には残す(編集が `UIKit.tools.base('cut2resolve')` でパックの API を呼ぶ)が、「他のツール」のメニューには出さない
- 写し先は studio(css・js)と editor(js と index.html の CSS)だけ(`dev/sync_ui_kit.py`)

## v6(2026-09-27・画面の全面見直し 段階1。`docs/design/briefs/ui-overhaul/`)
土台(トークン・部品)を広げる回。作り替えはしていない。詳しい経緯・決めたことは `docs/design/briefs/ui-overhaul/DESIGN_BRIEF.md` と `IMPLEMENTATION.md` の「1」。

### トークン
- **既定のテーマが明るいに変わった**: 保存が無いときは `light`(以前は OS の設定に従う `system`)。「OSに合わせる」は選んだときだけ `localStorage['ytt:theme']` に `'system'` と明示的に保存する
- `--bg`(明るいテーマ)を `#eceef2` に(面 `--panel` との差を広げる)
- 新しいトークン: `--stage-bg` / `--stage-ink`(映像の周り。両テーマで暗い灰色)・`--playhead`(再生位置の赤)・`--toast-bg` / `--toast-ink`(通知。両テーマで暗い面)・`--keybar-h`(下の帯の高さ)・`--drawer-w`(引き出しの幅)
- 飾りを除いた: `.btn` と `.card` の影(`.card.raised` だけ残す)、ヘッダーのブランドの印のグラデーション→単色(ツールごとに1色)、`.bar` のグラデーション→単色、`.pill.run` / `.dot.run` の無限の点滅(`.pill.run` は静かな回転の輪に。`prefers-reduced-motion` で止まるのは今までどおり)
- 文字の大きさ「大きい」: `html[data-fs=lg]` で `--fs-*` を少し(1〜1.5px)大きく(設定の「文字の大きさ」から)

### 部品(JS は `window.UIKit`。CSS クラスは ui-kit.css)
- **`UIKit.appnav`**: `<nav data-ui-appnav="studio|transcribe|portal">` に、ホーム/スタジオ/編集の3つを DOMContentLoaded で描く(ホームは入口に取り込まれているときだけ)。
  今の場所は `aria-current="page"`。`setLink(id, suffix)`(`'?media=…'` のように `?`/`#` で始まる文字列だけ受け付け、そのツールへ今の動画を引き継ぐ)・`setVersion(text)`(今の場所の項目の `title` に版を出す)
- **`UIKit.drawer`**: 右から出る引き出し(設定・書き出し・パックの詳しい設定などで共通)。`<aside class="ui-drawer" hidden>` + `.ui-drawer-head` / `.ui-drawer-body`。
  `open(el, {modal, opener})` / `close(el)` / `isOpen(el)`。`modal:true`(既定)は幕つき・裏(body 直下。引き出し自身・幕・トースト・下の帯は除く)を `inert` にしてフォーカスを閉じ込め、Esc で閉じる。
  `modal:false`(docked)は幕なし・裏も操作できる(開いたまま他の作業を続けられる。書き出し中など)。閉じたら `opener`(渡さなければ開いた時の `document.activeElement`)へフォーカスを戻す。`focus:false` で開いたときにフォーカスを中へ動かさない(画面が自動で開く docked の欄)
- **`UIKit.dialog`**: `confirm({title, body, ok, cancel, danger}) → Promise<boolean>`・`alert({title, body}) → Promise<void>`。`<dialog class="ui-dialog">` + `showModal()`(フォーカスの閉じ込め・Esc はブラウザに任せる)。
  本文は `textContent` で入れる(呼び出し側の文字列を innerHTML に入れない)。Esc は `confirm` では `false` になる
- **`details.ui-pop`**(ポップオーバー): `<details class="ui-pop"><summary>…</summary><div class="ui-pop-body">…</div></details>`。既存の `details.ui-menu` と同じ仕組みで外側のクリック・Esc で閉じる(Esc は `summary` へフォーカスを戻す)。`data-align="left"` で左寄せ
- **`UIKit.toast(message, {kind, ms, detail})`**: 通知を重ねて最大3つ(`kind`: `'ok'|'err'|'info'|''`)。入れ物は `<div class="ui-toasts" id="toast" aria-live="polite">`(ページに既存の `#toast` があれば作り直して使う。無ければ body の末尾に作る)。
  既定の表示時間は 2.5 秒、`err` は 8 秒 + `role="alert"`(クリックでいつでも閉じられる)。`detail`(原文)は畳んだ `<details>` に入る
- **`UIKit.keybar`**: 画面下の細い帯(いま使えるキーを 5〜7 個)。`set([{k, l}, …])`(場面が変わったら置き換える)・`flash(k)`(押されたキーを一瞬光らせる)・`clear()`。
  設定「キーの帯を出す」(既定オン。`localStorage['ytt:keybar'] === '0'` で消える)。表示中は `html[data-keybar]`(画面側で下の余白に使える)
- **`.ui-kbd`**: ボタンの中の小さなキーの手がかり(`<kbd class="ui-kbd">I</kbd>`)
- **`.ui-miniprogress`**: 幅 64px・高さ 4px の小さな進み具合の棒(`style="--p:42%"`)。`.indet` で進み具合が分からないとき
- **`UIKit.settings.mount({tool, title, version})`**: ヘッダーの `[data-ui-settings]` ボタンから開く設定の引き出し。渡した `tool`(そのツール固有の設定の要素。無くてもよい)+ 共通の「全体」の節(テーマ・文字の大きさ・キーの帯を出す)を1つの `ui-drawer` にする。
  全体の設定は `localStorage` の `ytt:theme` / `ytt:fs`(`'md'|'lg'`)/ `ytt:keybar`(`'0'` で消す)を使うので、どのツールで変えても他のタブ・他のツールに効く(`storage` イベント)
- **`UIKit.keys`**: `isTyping(el)`(入力欄・select・contenteditable か)・`helpHtml()`(共通の再生キーの表。`?` のキー操作の一覧の先頭に置く)・
  `playback({media, enabled, onIn, onOut, onFrame, fps, onKey})` → keydown ハンドラ関数(**自動では組み込まれない**。画面が自分のキー処理より先に呼び、`true`(処理した)なら自分の処理をしない)。
  Space 再生・停止 / J 1秒戻る / K 止める(速さを1倍に戻す)/ L 再生(もう一度で 1.5→2倍)/ ← → 1秒(Shift で5秒)/ , . 1コマ(`fps` 既定30。`onFrame(dir)` が `true` を返せば代わりにそちらを使う。カットで区間の端を選んでいるときなど)/ I O `onIn`/`onOut`。
  入力欄にフォーカスがある・Ctrl/Alt/Meta が押されている・Shift は矢印以外では無視。処理したキーは `opts.onKey(name)` と `UIKit.keybar.flash(name)` を呼ぶ
  `keymap`(オブジェクトか関数。操作 id → キーの表記)を渡すと割り当てを変えられる(編集の ⚙「キー配置」。渡さなければ上の既定 = スタジオ)。操作 id と既定は `PLAYBACK_ACTIONS`
  (playPause・back1・stop・play・seekBack・seekFwd・frameBack・frameFwd・markIn・markOut)。seekBack/seekFwd は割り当てたキー + Shift で5秒。
  押しっぱなしの繰り返しでは、再生・停止・K・L・I・O を繰り返さない。`comboOf(e)`(キーの表記。'j'・'Shift+j'・'Space'・'ArrowLeft'。英字・Space・名前のあるキーだけ Shift を付ける)・`keyText(combo)`(表示用。'Shift+←')・
  `helpHtml(keymap)`(渡せば今の割り当ての表)
- **`UIKit.icon(name, {size})`**: 24x24・線1本(`stroke=currentColor` `stroke-width=2`・角丸)の SVG を文字列で返す。`<span class="ui-icon" data-icon="play">` は DOMContentLoaded で自動的に中身が入る(`UIKit.icon.fill(root)` で好きな範囲だけ埋め直せる)。
  種類の一覧は `ui-kit.js` の `ICONS`(`styleguide.html` の「アイコン」に一覧表示)

`styleguide.html` はこれらすべての見本を表示する(動きは `styleguide.js`。CSP に合わせてインラインの `<script>` は使わない)。

## v8(2026-09-29・気が利く画面へ 段6。`UIKit.keymap`)
キーの一覧がそのままキー配置の設定。`?` の一覧と ⚙ の「キー配置」は同じ部品(`mount(el)` を2か所に置く。中身は1つ)。編集とスタジオが使う。
- **`UIKit.keymap.create(opt)`** → api。`opt`:
  - `actions: [{id, def, label, group, alt}]`(ツールのキー。`def` は `UIKit.keys.comboOf` の表記)・`groups`・`fixed: [{group|title, why, note, rows: [[キー, 説明, 理由?]]}]`(変えられないキー。錠のアイコンと理由を出す)
  - `refuse(combo)` → そのツールで固定の意味があれば理由の文字列(ツールのキーにも共通の再生キーにもできない)
  - `load()` / `save(part)`: ツールのキーの読み書き(`save` には**変えたキーだけ**が来る。ツール側は送ったキーだけ直す = 窓を並べても戻らない)
  - `fallbackPlayback: {load, save}`: 入口の外で開いたときの共通の再生キーの置き場(編集は自分の settings.keymap)
  - `intro`・`playbackNote`・`footNote`・`extra`: 一覧の中の文。`onChange()`: 割り当てが変わるたび(画面の帯・手がかりを描き直す)
- api: `map()`(今効く割り当て `{id: キー}`。共通の再生キーを含む。`UIKit.keys.playback({keymap})` にそのまま渡せる)・`key(id)`・`text(id)`(表示用)・`actionOf(combo)`(キー → このツールの操作の id)・
  `mount(el)`・`reload()`・`refusal(id, combo)`・`set(id, combo)`・`setMany(map, msg)`(スタジオのプリセット。[戻す] つき)・`clearNote()`・`capturing()`
- **共通の再生キー**(`UIKit.keys.PLAYBACK_ACTIONS`)はホームの設定 `keymap.playback`(`src/home/prefs.py`・`api/ytt/prefs`)に1つ。どのツールで変えても同じ。
  初回は `fallbackPlayback.load()` の値(編集の settings.keymap にあった再生キー)をホームの設定へ移す。戻ったとき(`UIKit.life.onReturn`)に読み直す
- 変え方: キーのボタン → その場で次のキーを待つ(捕捉の段階で受け、ほかのキー処理に渡さない)。Esc = 取り消しだけ(一覧は閉じない)・Delete / Backspace = 外す・
  Ctrl / Alt / Meta つきと日本語の変換中は受け取らない・断ったら理由を一覧の中に出して待ち続ける
- 重なり: 別の操作に使っているキーを選ぶと、そちらを外して「「X」から外しました [戻す]」(一覧はモーダルの上なので、知らせ(トースト)ではなく一覧の中に出す)。行ごとの「標準」・すべて標準に戻す
- **重なりの検査は部品の1か所**: 共通の再生キーにできないキー `UIKit.keymap.BLOCKED`(全ツールの固定キー・編集の 2 カット のキー・数字)・ツールの `refuse`・
  派生キー(← → に当たるキー + Shift = 5 秒。1文字の記号は派生しない。GPT-03)。キーの形は `src/home/prefs.py` の `COMBO_RE` と同じ(サーバーは fullmatch で検査)
- 新しいキーを足すとき: ツールのキーは `actions` に、共通の再生キーにできなくなるキー(どこかのツールで固定の意味を持つもの)は `PB_BLOCKED`(ui-kit.js)に足す。確かめるテストは `src/home/tests/e2e_keymap.py`

## v9(2026-09-30・全体の計画 段2 監査 11。`UIKit.settings.status`)
設定の保存・読み込みの失敗を、文書の保存の表示とは別の場所に出す(黙って捨てない)。
- **`UIKit.settings.status(state, message, retry, label)`**: `state = 'err'` で ⚙ ボタン(`[data-ui-settings]`)に赤い印(`data-ui-status="err"`)・title と aria-label に理由、
  設定の引き出しの先頭に `.notice.err.ui-settings-status`「message [label]」(`retry` を押すと呼ぶ。Promise を返せば終わるまでボタンを止める。label の既定は「もう一度」)。
  `''`・`null` で消す。**成功したら必ず消す**(印が出っぱなしにならないように)。`statusOf()` → `{state, message}`
- 使い方の約束(編集・スタジオ): 保存の失敗 → `status('err', '設定を保存できていません: 理由', 再送)`。読み込みの失敗 → `status('err', '設定を読み込めませんでした…', 読み直す, '読み直す')` にして、
  **読み直すまで保存しない**(空・既定値で保存済みの設定を上書きしないため)
- (段3 3-2・監査 03。版は v9 のまま)**`UIKit.keys.derived(km)`** → `{ 'Shift+ArrowLeft': 'seekBack', … }`(← → に当たるキー + Shift = 5 秒の派生キー)。
  `UIKit.keys.playback`(押したとき)と `UIKit.keymap`(登録のときの重なりの検査)が同じこの関数を使う(派生の決まりを1か所に)。
  `UIKit.keymap.BLOCKED` に `<` `>`(編集 2 カット の Shift+, / Shift+. = 選んだ端を10コマ)を足した = 共通の再生キーにできない

## v10(2026-10-01・段9 9-3。`UIKit.restart`。`git の履歴(679ff01 以前)の git の履歴(679ff01 以前)の docs/plan/phase9-ops-stability.md` の 9-3)
版の赤い帯(画面の APP_VERSION と `/api/ping` の版が違う)から、入口ごと起動し直す。取り込んだツールは入口と同じプロセスなので、ツールだけの再起動では版が入れ替わらない。
- **`UIKit.restart.check(el, 画面の版, サーバーの版, opts)`**: 版が違えば `el`(ツールの `.errbar`)に「画面(vX)とサーバー(vY)の版が違います。」を出して `true`、同じなら何もしないで `false`。
  **ホームから開いた画面(合言葉 `ytt-token` がある)だけ**「起動し直す」のボタン(`.ui-restart-btn`)を付ける。単体で開いたときは今までどおり「黒い画面を閉じて、起動し直してください」の文だけ
- ボタン → 入口の `POST api/ytt/restart-self`(相対パス。合言葉付き。入口が新しい入口を起動して自分は「すべて終了」と同じ後始末で終わる。`src/home/restart.py`)→
  「起動し直しています…」→ `api/ping` を 2 秒ごとに読み、**一度答えなくなってから答えた・版が変わった**ら `location.reload()`(新しい入口は合言葉が変わるので読み込み直しが要る)。
  断られた(409。実行中の処理がある・終了の途中)ら理由を帯に出してもう一度押せる。90 秒で戻らなければ「start.bat をダブルクリックして起動してください」にしてボタンを隠す
- 帯の状態は `el` の `data-ui-restart`(`ready` / `sending` / `waiting` / `done` / `refused` / `timeout`)。部品: `band(el, …)`(比べずに出す)・`run(opts)`(頼んで待つだけ。`from`・`onState(state, text)`・`reload`)・`available()`
- ツールでの使い方: 起動時の `/api/ping` のあとで `UIKit.restart.check($('#errBar'), APP_VERSION, ping.version)`(以前の `showErr('…版が違います…')` の代わり)。
  `UIKit.version` は 10(v9 では 8 のままだった)

## v18(2026-10-07・内部の整理。動きは同じ)
- 確認・お知らせのダイアログ(`UIKit.dialog`)・編集の設定の保存(`UIKit.packLoud`・`UIKit.autorun`)・捕まえたエラーの記録を、中で 1 つの関数にまとめた。`UIKit` の形と動きは変えていない
- 使っている画面が無くなっていた `<a data-ui-home>` / `data-ui-cases`(v3 の入口・案件へ戻るリンク)の処理と `.ui-home` の見た目を消した(ヘッダーは `ui-appnav` に一本化済み = `docs/spec/ui-guidelines.md` の 2)

## v17(2026-10-05・ほかの窓で音が鳴っているかを知らせ合う `UIKit.sound`)
- 「編集」を別の窓で開いて再生すると、スタジオの配信の音と二重になる(ユーザー)。この画面の `<video>`・`<audio>` が鳴っている間(再生中・消音でない・音量 0 でない)、同じオリジンの窓へ BroadcastChannel `ytt-sound` で知らせる(`{id, tool, playing}`。外へは送らない)
- 鳴っている間は 2 秒ごとに送り直し、受ける側は 6 秒来なければ止まったとみなす(窓を閉じた・落ちたとき)
- `UIKit.sound.other(tool?)` = ほかの窓(tool を渡せばそのツール以外)で鳴っているか・`UIKit.sound.onChange(fn)`。各画面で足すものは無い(ui-kit が自動で見る)。使うのはスタジオのライブの録画(`src/studio/review.js` の `duckMode`)

## v16(2026-10-05・線 D「リアルタイム切り抜き」P3。`UIKit.liveBadge`。`plan/line-d-live-clipping.md` の 0-8)
全ツールのヘッダーの「録画中」の札。**録画があるときだけ**、appnav のあるヘッダー(`.ui-header` の中の `.ui-header-actions` の先頭)に出る。**ヘッダーの HTML に足すものは無い**(JS が作る)。
録画が無い・機能がオフ・合言葉(`ytt-token`)が無いページ(入口を通さない単独起動)では、要素も作らない(場所も取らない)。
- データ: 入口の `POST api/ytt/live {op: "status"}`(相対パス。合言葉 `X-YTT-Token` は他の `api/ytt/…` と同じ)→ `{enabled, recordings: [{recorder, id, title, state, active, seconds, endedAt, url}]}`。
  `state` = waiting | recording | reconnecting | stopped | ended | error。オンのときは 10 秒ごと・オフ(`enabled: false`・404 などの 4xx)のときは 60 秒ごとに問い合わせる。
  ネットワーク・5xx の一時的な失敗は、2回までは今の表示のまま 10 秒後に取り直し、3回続いたら札を消す。**隠れているタブは問い合わせない**(戻ったらすぐ取り直す。`UIKit.life.onReturn`)
- 札(押せるボタン): 「● 録画中 1」(本数。赤い点は飾りで、文字も出す)・「つなぎ直し中」・「配信待ち 1」。複数あれば「録画中 1・配信待ち 1」。
  動いているものが無く、終わって間もない録画だけが残っているときは「録画終了 n」(「開く」で行ける)、エラーがあれば「録画エラー」。状態は `data-state` と `aria-label` にも出る
- 一覧(札を押すと開く。`role="dialog"`・Esc / 外側のクリック / Tab で外へ出ると閉じる。開いたらフォーカスは一覧へ・Esc で札へ戻る): 録画ごとに 題(無ければ URL)・状態・録画済みの時間(m:ss / h:mm:ss。録画中は1秒ごとに進む)・
  「開く」(= `<a href="<スタジオ>?video=<録画の id>">`。スタジオの場所は appnav が使う `UIKit.tools` のもの)・動いている録画に「停止」(`UIKit.confirmTwice` の二度押し → `POST api/ytt/live {op: "stop", recorder, recording}`)。
  **差分で直す**: 行・ボタンは作り直さない(10 秒ごとの更新で、押そうとしたボタンや二度押しの途中が消えない)。題などは `textContent`(外から来る文字)
- 知らせ(`UIKit.toast`。**ページを開いた最初の1回では出さない**): 動いていた録画が動かなくなった →「「題」の録画が終わりました(合計 h:mm:ss)」/ recording → reconnecting →「「題」の録画が切れました。つなぎ直しています」(失敗の色)/
  動いていた録画が error になった →「「題」の録画でエラーが起きました」
- `UIKit.liveBadge`: `get()`(最後の応答 `{enabled, recordings}`。まだ無ければ `null`。失敗で札を消したときは `{enabled: false, recordings: []}`)・`refresh()`(すぐ問い合わせ直す → Promise(最後の応答))・
  `onChange(fn(応答))`(答えのたびに。差があったかは fn が比べる)・`onOpen(fn(録画))`(スタジオの画面が登録する。あれば「開く」はページを移らず、一覧を閉じて `fn` を呼ぶ。無ければスタジオへ移る)
- 見本とテスト: `styleguide.html` の「v16: 録画中の札」(見た目だけの静的な見本)・`python src/ui-kit/tests/e2e_styleguide.py`(`api/ytt/live` を `page.route` で偽装。札・一覧・差分・二度押し・知らせ・間隔・隠れたタブ)。`UIKit.version` は 16

## v15(2026-10-04・引き出しの中から開くダイアログが固まる不具合)
- 引き出し(`UIKit.drawer.open(el, {modal: true})`。⚙ 設定など)は裏の要素を `inert` にする。そのとき、ページに最初からある `<dialog>`(編集の `#dlgConfirm` など)まで `inert` にしていたので、
  引き出しの中から `showModal` で開いた確認が、表示はされるのにクリックもキーも受け付けず固まっていた(ユーザーの報告: ⚙ の「仮置きをまとめて文字起こし」の確認)。
  → `drawerInert` は `<dialog>` を `inert` にしない(閉じた dialog は表示されず、開いた modal の dialog は showModal が裏を止める)。`UIKit.version` は 15(v14 の間は 13 のままだった)。
  テスト: `src/editor/tests/e2e_eval_set.py` の「⚙ の中から開いた確認のダイアログを押せて閉じられる」(直す前の ui-kit では FAIL になることを確かめた)

## v14(2026-10-04・ヘッダーの明暗ボタンをやめる・キーを変える場所を1つに)
- ヘッダーの明るい/暗いの切り替えボタン(`.ui-theme-toggle`)と、その CSS を消した。配色は ⚙ 設定の「テーマ」(4つ + OSに合わせる)から選ぶ。`UIKit.theme.toggle()` と `[data-theme-toggle]` のクリックの動きは残す(ボタンの無い軽い画面 `editor/lite.html` が使う)。
- キーを変える場所は ? の一覧の 1 か所(`UIKit.keymap` の `mount` は ? の一覧だけ)。⚙ 設定の「キー配置」の一覧はやめ、「キー配置を変える(?)」のボタンで同じ一覧を開く。

## v13(2026-10-04・一覧の項目を任意に非表示に `UIKit.hide`)
増えていく一覧(ホームの案件・次にやること・単体の文字起こし・届いた依頼・まとめて実行の記録、スタジオ ③ の配信、「編集」の履歴)の項目を隠す部品。
**新しく増えていく一覧を作るときは、これで隠せるようにする**。データは消さない(表示だけ)。
- 覚える場所: ホームの設定の節 `hidden`(`src/home/prefs.py`。一覧の名前 → `{id: 隠した時刻}`。一覧の名前は `HIDE_LISTS` = `cases`・`todo`・`transcripts`・`videos`・`intake`・`runs`。
  新しい一覧はそこに足す)。足す・外すは `api/ytt/prefs` の op `hide`(`{list, ids, hidden}`)で1件ずつ = 窓を2つ並べても相手の分を消さない
- `available()`: ホームから開いた(合言葉がある)ときだけ true。false のときは隠す操作・切り替えを出さない
- `load(force)` → Promise(最初の1回と、画面に戻ったとき(`UIKit.life.onReturn`)に読み直す)・`has(list, id)`・`count(list, ids)`
- `set(list, ids, on, {label, undo, quiet})`: 先に覚えている内容を変えて `onChange` を呼び、送る。知らせ「「…」を非表示にしました [元に戻す]」は部品が出す。失敗したら戻して知らせる
- `showing(list)` / `setShowing(list, on)`: 隠したものも出すか(その画面の間だけ。覚えない)
- `toggle(btn, list, n)`: 「非表示 n件を表示」/「非表示のものを隠す」の切り替えボタンを描く(一覧を描くたびに呼ぶ。n = 今の絞り込みで隠れている数。0 で出していないときは隠す)
- `onChange(fn(list))`: 変わったら(list = その一覧、null = 全部を読み直した)
- 見た目: 隠したものを出しているときの行に `.ui-hidden-item`(薄く)、札 `<span class="ui-hidden-tag">非表示</span>`
- 決まり: 今開いている・実行中の項目は、隠していても一覧から消さない(迷わないため)

## v12(2026-10-02・サイバー風: 計器盤の形と配色4つ)
ユーザーが見本(`docs/design/briefs/cyber-theme/board.html`)から **A 計器盤** と、配色 **アイスライト・ネオンシアン・鋼の白・ターミナルグリーン** を選んだ(2026-10-02)。
- 形(`ui-kit.css` の末尾の「v12」): 角はほぼ直角(`--r` = 2px)・細い 1px の線・`.card` の左上と右下に角の括弧(`::before` / `::after`。**ツールで `.card` の疑似要素を使わない**)・
  タブと `.ui-seg` は下線・`.pill` は枠だけで等幅・`.bar` は目盛り・`.notice` は左の線・`th` と `.card-sub` は等幅。光らせない
- 色: 明るい = **アイスライト**(`:root`)/ 暗い = **ネオンシアン**(`:root[data-theme=dark]`)。暗いときだけ `data-palette` で **鋼の白**(`steel`)・**ターミナルグリーン**(`green`)に替えられる
  (どれも文字/地 4.5:1 以上・状態の色どうしが紛れない。決めた数値と直した理由は `docs/design/briefs/cyber-theme/patterns.css` の「調整した4つ」)
- JS: `<html data-palette="ice|cyan|steel|green">` を `UIKit.theme` が付ける。暗いときの配色は `UIKit.theme.palette()`(読む)・`palette('steel')`(変えて `localStorage['ytt:palette']` に保存)。
  明るい/暗い(`ytt:theme`)とは別に持つので、「OSに合わせる」・以前の保存はそのまま使える(暗くしたときに、最後に選んだ暗い配色になる)
- ⚙ 設定の「テーマ」: アイスライト(明るい)/ ネオンシアン / 鋼の白 / ターミナルグリーン(暗い)/ OSに合わせる
- 色は必ず変数で書く決まりは今までどおり(固定の色は、配色を替えたときに浮く)。スイッチのつまみは `--knob`(鋼の白・ターミナルグリーンは明るいアクセントの上で見えるように地の色)
- 送るアプリ(`friend-apps/request-sender/`)の配色は別(A ネオンシアン・B シンセウェーブ・C ターミナルグリーン・D アイスライト)

## v11(2026-10-02・時刻の欄 `UIKit.timebox`)
時刻(1:23:45)を「:」を打たずに入れる欄。送るアプリ(`friend-apps/request-sender/` の TimeBox)で決めた動き(`docs/spec/friend-intake.md の 2-10` の「時刻の欄」)を、Web の画面でも使い回すための部品。
**時刻を手で入れる欄を新しく作るときは、これを使う**(`docs/spec/ui-guidelines.md` の 3-2)。スタジオの「現在位置」の欄だけは今までの入力欄のまま(5025 のような秒の数字でジャンプする使い方があるため)。
- 置き方: `<span data-ui-time aria-label="開始の時刻"></span>`(DOMContentLoaded で自動)。画面をあとから作るときは `UIKit.timebox.attach(el, opt)` か `UIKit.timebox.create(opt)`(要素を返す)
- 形は3つ: **時:分:秒**(既定。`1:23:45`)/ **時:分:秒.0.1秒**(`data-ui-time-tenths` / `tenths`。`0:01:23.5`。スタジオのマーク・コラボ)/
  **分:秒.0.1秒**(`data-ui-time-short` / `short`。`1:23.5`。1時間を超えたら分が 60 以上 = `83:45.6`。編集の字幕の行。ユーザー決定 2026-10-02)。
  どの形も、左の端(時か分)は1桁打ったら次へ進む
- 選べること(属性 / opt): はじめの値 `data-ui-time="83.5"` / `value`(秒)・
  **YouTube の URL も読む** `data-ui-time-youtube` / `youtube`(…?t=5025・t=1h2m3s。**要る欄だけ**。既定はオフ)・上限 `data-ui-time-max="600"` / `max`(秒)・
  使えない `aria-disabled="true"`・誤り `aria-invalid="true"`(赤い枠。**誤りかどうかと理由の文は、使う画面が決めて出す**)
- 値: `UIKit.timebox.get(el)` → 秒(入っていなければ `null`)・`UIKit.timebox.set(el, 秒 | null)`(画面から入れたときは `ui-time`・`ui-time-commit` を出さない)。
  変わるたびに要素へ `ui-time`(`detail.value`。bubbles。打っている途中も出る)、
  **Enter か欄を離れたときに、値が変わっていれば `ui-time-commit`**(入力欄の change に当たる。`detail: {value, via: 'enter'|'blur', to: 移った先の要素 | null}`)。
  値を保存する・画面を描き直すのは `ui-time-commit` で行う(打つたびに描き直すと欄が作り直されて打てなくなる)。描き直したあとは、`via === 'blur'` なら `to`(移った先)へ
  フォーカスを戻し、欄に奪い返さない(開始 → Tab → 終了 と続けて打てるように)。おかしな値は理由を出して `set(el, 元の値)` で戻す。
  読めない貼り付けは `ui-time-reject`(`detail.reason`)、貼り付けた文字は `ui-time-paste`(`detail.text`。YouTube の URL から配信の ID を取りたいときに)
- 画面を `innerHTML` で描き直したあとは `UIKit.timebox.attachAll(入れ物)`(中の `[data-ui-time]` を全部)。欄の文字をテストで読むときは `textContent`(`innerText` は区切りごとに改行が入る)
- 動き: 欄に入ると「時」が選ばれる(反転)→ 数字で 時(1桁)→ 分(2桁)→ 秒(2桁)→(0.1 秒)と進む(`12345` → 1:23:45。分・秒の最初が 6〜9 なら1桁で次へ)。
  ← → で場所を選ぶ(クリックでも)・↑ ↓ で選んだ単位を ±1(Shift で ±10。繰り上がりあり)・BackSpace = 選んだ所を 0(もう 0 なら左へ)・Delete = 空に・
  Ctrl+V = `1:23:45` / `83:45`(分:秒)/ `1h23m45s`。数字だけ(`5025`)は読まない(秒か 時分秒 か決められない)。入っていない欄は `-:--:--`
- 入力欄(input)ではなく、フォーカスできる要素(`role="spinbutton"`)に自分で描いている: 文字を打ち込めない・日本語入力に数字のキーを取られない・選んだ所をアクセントで見せられる。
  欄が使ったキーは画面のキー操作に渡さない(`stopPropagation`)。`UIKit.keys.isTyping(el)` は時刻の欄を「入力中」と数える。
  **ツールが自分の「入力中か」の判定を持っているとき(スタジオの `Studio.isTyping` など)は、使う前に `.ui-time` を足す**
- そのほか: `UIKit.timebox.parse(文字, {youtube, tenths})` → 秒 | null・`UIKit.timebox.format(秒, 形)` → `1:23:45`(形: 省略 / `true`・`'tenths'` / `'short'`)
- 使っている所(2026-10-02): 編集の 1 文字起こし の行(short)・スタジオの ③ 確認のマークの開始/終了(tenths)・コラボの合わせる時刻(tenths)
- 見本とテスト: `styleguide.html` の「v11: 時刻の欄」・`python src/ui-kit/tests/e2e_styleguide.py`(本物のキー入力)。`UIKit.version` は 11

## 重なりの順(z-index)の決まり(v6・段3-2)
新しい値を作らず、この段のどれかにそろえる。
- 1〜6: 部品の中の重なり(タイムラインのつまみ・映像の上の字幕など)
- 30〜45: 画面の中で貼り付く物(sticky の見出し・ヘッダー 40)
- 50: 画面の下のキーの帯 / 60〜65: ポップオーバー・「…」・右クリックのメニュー
- 70・75: 右の欄の幕・右の欄 / 80: ツールチップ / 90: トースト
