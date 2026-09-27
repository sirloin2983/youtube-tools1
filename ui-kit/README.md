# ui-kit(共通の見た目)v6

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
    名前の候補(datalist)・色の見本・合う人の表示を付ける。照らし合わせは入口(`api/ytt/streamer-colors` → `ytt_core/colors.py`)。値は名前のまま送る。
    値を画面から入れたら `UIKit.streamer.set(input, 名前)`。合う人が決まるたびに input に `ui-streamer` イベント(detail: 人 | null)。
    同じ名前ではもう一度照らし合わせない(欄から離れたときに説明の文が変わって、隣のボタンのクリックが外れたため)
  - `UIKit.portal`(v5・2026-09-27)… 入口へ戻るリンク(`a[data-ui-portal]`。「他のツール」の入口・`[data-ui-home]`・案件の画面の「← 入口へ」)は、
    入口がほかの窓・タブで開いていれば移らずに入口の窓を前に出す(`api/ytt/focus-portal`)。入口の画面は `UIKit.portal.listen()` で答える(BroadcastChannel `ytt-portal`)
  - 入口の API は相対パス `api/ytt/…` で呼ぶ(入口の画面 → `/api/ytt/…`、取り込んだツール → `/studio/api/ytt/…`。どちらも入口が受け持つ)
- `styleguide.html` … 見本。ブラウザで直接開いて、ダーク/ライトの両方で確認する

## 使い方
1. 正本(このフォルダ)を直す
2. `python tools/sync_ui_kit.py` で各ツールへ写す(`--check` でずれの確認だけ)
3. 各ツールのテストに加えて `python -m unittest tools/test_ui_kit_sync.py` が通ること

各ツールでの読み込み:
- スタジオ: `<head>` で `<script src="/ui-kit.js"></script>`(CSS より先・同期)→ `<link rel="stylesheet" href="/ui-kit.css">` → ツール固有の CSS
- 編集(文字起こしツール): CSS は `index.html` の中の `/* ui-kit:css:begin */ … end */`(`<style>` の先頭)に埋め込み、JS は `ui-kit.js` の写し
- cut2resolve: 画面を「編集」に統合して消したので、写さない(2026-09-26)

## テーマ
- `<html data-theme="light|dark">` を `ui-kit.js` が付ける。初回は OS の設定に合わせ、切り替えボタン(`[data-theme-toggle]`)を押すと保存する
- 保存場所は localStorage の `ytt:theme`(`light` / `dark`。無ければ OS に合わせる)。ツールごとにポートが違うので保存は別々
- 色は必ず変数(`var(--panel)` など)で書く。固定の色を書くと片方のテーマで読めなくなる
- 主な変数: `--bg` `--panel` `--panel-2` `--panel-3` `--field` `--line` `--line-2` `--ink` `--ink-2` `--ink-3` `--accent` `--accent-ink` `--accent-soft` `--ok` `--warn` `--danger` `--info`(+ `-soft`)、グラフ用 `--c-audio` `--c-chat` `--c-com`

## ヘッダーの書き方
`styleguide.html` の `<header class="ui-header">` をそのまま使う(ブランドのアイコン・ツール名・版・タブ・他のツール・テーマ切り替え)。
ブランドの色は `.ui-brand-mark[data-tool=studio|transcribe|cut2resolve]`。

## v3(2026-09-26・画面の全面見直し)
共通のルールは `docs/ui-guidelines.md`(用語集・ヘッダー・ボタンと札・一覧・段階的に見せる・狭い画面)。
- 状態の札(`.pill`)の文字は `--ok-ink` `--warn-ink` `--danger-ink` `--info-ink` `--accent-ink2`(明るいテーマで 5.5:1 以上)。札は枠なし・押せない表示だけ
- 入口へ戻る: ヘッダーに `<a class="ui-home" data-ui-home hidden>`(と `data-ui-cases`)。入口に取り込まれているとき(画面に `ytt-token` がある)だけ ui-kit が `/`・`/cases.html` を入れて出す。
  「他のツール」のメニュー(`UIKit.tools.render`)も、取り込まれているときは先頭に「入口」「案件の一覧」を出す。`UIKit.tools.mounted()`
- 一覧: `.ui-listbar`(検索は残りの幅いっぱい)・`.ui-count`・`details.ui-group`(+ `.ui-group-n`・`.ui-group-side`)・`.ui-next`(次にやること)
- 言葉の説明: `<abbr class="ui-term" title="1文の説明">EDL</abbr>`
- `.lag.keep`: 短いラベル + select の組を折り返さない(狭い画面で1文字ずつ縦に割れないように)
- `UIKit.fmt.ago(ms)`(「3日前」「今日 14:32」)・`UIKit.fmt.date(ms)`・`UIKit.fmt.dur(秒)`・`UIKit.esc(s)`

## v4(2026-09-26・「編集」: 文字起こし + cut2resolve の統合。`docs/edit-tool-design.md`)
- ツールの一覧(`UIKit.tools`)の transcribe の表示名を「編集」(カット・字幕・Resolve へのパック)に
- cut2resolve は `hidden: true`: 一覧には残す(編集が `UIKit.tools.base('cut2resolve')` でパックの API を呼ぶ)が、「他のツール」のメニューには出さない
- 写し先は clip-studio(css・js)と transcribe-tool(js と index.html の CSS)だけ(`tools/sync_ui_kit.py`)

## v6(2026-09-27・画面の全面見直し 段階1。`.design/ui-overhaul/`)
土台(トークン・部品)を広げる回。作り替えはしていない。詳しい経緯・決めたことは `.design/ui-overhaul/DESIGN_BRIEF.md` と `IMPLEMENTATION.md` の「1」。

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
- **`UIKit.icon(name, {size})`**: 24x24・線1本(`stroke=currentColor` `stroke-width=2`・角丸)の SVG を文字列で返す。`<span class="ui-icon" data-icon="play">` は DOMContentLoaded で自動的に中身が入る(`UIKit.icon.fill(root)` で好きな範囲だけ埋め直せる)。
  種類の一覧は `ui-kit.js` の `ICONS`(`styleguide.html` の「アイコン」に一覧表示)

`styleguide.html` はこれらすべての見本を表示する(動きは `styleguide.js`。CSP に合わせてインラインの `<script>` は使わない)。
