# ui-kit(共通の見た目)v1

3つのツール(切り抜きスタジオ・文字起こしツール・cut2resolve)で共通の、色・文字・部品・ダーク/ライト切り替え。
将来1つのアプリに統合するときに見た目がそろっているよう、正本はここ1か所にして、各ツールへ写す。

- `ui-kit.css` … 色の変数(トークン)と部品(ボタン・入力・カード・タブ・表・通知など)
- `ui-kit.js` … テーマ切り替え(`window.UIKit.theme`)と「他のツール」メニュー(`window.UIKit.tools`)
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
