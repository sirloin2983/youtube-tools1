# ui-kit(共通の見た目)v3

3つのツール(切り抜きスタジオ・文字起こしツール・cut2resolve)で共通の、色・文字・部品・ダーク/ライト切り替え。
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
  - 入口の API は相対パス `api/ytt/…` で呼ぶ(入口の画面 → `/api/ytt/…`、取り込んだツール → `/studio/api/ytt/…`。どちらも入口が受け持つ)
- `styleguide.html` … 見本。ブラウザで直接開いて、ダーク/ライトの両方で確認する

## 使い方
1. 正本(このフォルダ)を直す
2. `python tools/sync_ui_kit.py` で各ツールへ写す(`--check` でずれの確認だけ)
3. 各ツールのテストに加えて `python -m unittest tools/test_ui_kit_sync.py` が通ること

各ツールでの読み込み:
- スタジオ・cut2resolve: `<head>` で `<script src="/ui-kit.js"></script>`(CSS より先・同期)→ `<link rel="stylesheet" href="/ui-kit.css">` → ツール固有の CSS
- 文字起こしツール: `index.html` の中の `/* ui-kit:css:begin */ … end */`(`<style>` の先頭)と `/* ui-kit:js:begin */ … end */`(`<head>` の `<script>`)に埋め込み

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

