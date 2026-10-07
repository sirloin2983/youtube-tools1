# Design Review: 画面(UI)の見直し(全画面。基準 `docs/spec/ui-review-criteria.md`)

状態(2026-10-07): **1 周目の途中**(測る → 直す → 測り直す を Must 0 まで繰り返す。上限 3 周)。
対象: ホーム(`src/home/`)・切り抜きスタジオ(`src/studio/`)・編集(`src/editor/`)・共通部品(`src/ui-kit/`)。段 9(`plan/ux-stage7-9.md` の 3)の「直した画面の見た目の確認」もこの文書にまとめる(960・1440・1920 × 明・暗は基準の A の幅に含めた)。
照らし合わせた文書: `docs/design/briefs/ui-overhaul/DESIGN_BRIEF.md`(見た目の方針「落ち着いた仕事道具」)・`ux-consistency/DESIGN_BRIEF.md`(動きの方針)・`docs/spec/ui-guidelines.md`・`docs/spec/usability-heuristics.md`。
やり方: 基準を作る(まとめ役の案 + 相談役 Opus の案)→ 自動の検査 `dev/ui_audit.py`(A)+ 見直し役 3 人(ホーム / スタジオ / 編集。Opus)+ まとめ役の横断(B)→ 直し役 3 人(フォルダごと)→ 測り直し。

## 1. 写真(見本のデータ `dev/demo_env.py --seed 7`)
`py -3.10 dev/ui_audit.py all --demo --shots <フォルダ>` が、場面 23 × 幅 390 / 960 / 1440(+ 1920)× 明(アイスライト)/ 暗(ネオンシアン)を `<場面>-<幅>-<light|dark>.png` で保存する。見直しに使った写真はクラウドの作業用フォルダ(リポジトリには入れない。要るときは上のコマンドで撮り直す)。
場面: home / home-case-open / home-empty-filter / home-advanced / home-settings / studio-rank / studio-queue / studio-review-empty / studio-review / studio-review-export / studio-review-pick / studio-keys / studio-settings / editor-empty / editor-tx / editor-tx-more / editor-tx-jump / editor-cut / editor-pack / editor-pack-settings / editor-keys / editor-settings / styleguide。

## 2. 自動の検査(A)の推移
| 周 | Must(件) | Should(件) | 場面を除いて一意 | 主な内訳(一意) |
| --- | --- | --- | --- | --- |
| 1 周目の前 | 704 | 217 | 144 | A-10 文字記号 44・A-08 固定の色 21(Should)・A-22 コントラスト 15・A-21 28px 13・A-36 10(Should)・A-24 label 9・A-25 7・A-34 7(Should)・A-09 用語 5・A-29 4(Should)・A-31 3・A-07 2・A-32 2・A-20 1・A-35 1 |
| 1 周目の後 | (測り直しで書く) | | | |

## 3. 見直し役(B)の指摘
(各見直し役の表をここにまとめる。重さは Must / Should / Could。直した周と結果を右に足す)

### 3-1 ホーム
(待ち)

### 3-2 切り抜きスタジオ
(待ち)

### 3-3 編集
(待ち)

### 3-4 横断(まとめ役。3 画面を並べて)
- ヘッダー(B-06): 3 画面とも `ui-appnav` → 版 → タブ → 右寄せ [状態 / ツールの操作] → [キー操作] → [設定] の順で同じ。ホームの右は「接続中」の札 + 設定(キー操作は無い。キーの操作が無い画面なので可)。スタジオの設定のボタンは API キー未設定の印「!」つき(名前に理由が入っている)。編集は「校正 13分14秒 / 5時間00分」の状態 + キー操作 + 設定。右の操作は 3 画面とも 3 つ以内 — 合格
- primary の数(B-07・A-35): ホーム 0(行のリンクが次の一手)・スタジオ ① 1(検索する)・③ 1(再生 / 停止。書き出しはヘッダーの行のボタン)・編集 空 1(文字起こしを開始)・1 文字起こし 0・2 カット 0・3 パック 1(パックを作る)— 1 つの欄に 2 つ以上は無い
- 空の状態(B-02): スタジオ ①「まだ検索していません / 条件を決めて「検索する」を押すと、人気の配信がここに並びます」・③「まだマークはありません / 配信を再生し、面白い場面で IN → OUT → 追加(または「今をマーク」)を押すと、ここに出ます。」・編集「まだ何も開いていません / …」+ 前回の続きのボタン — 2 文の形はそろっている(ボタンの有無は各見直し役の判定)
- 用語(B-04): 3 画面で「配信」「切り抜き」「文字起こし」「校正」「カット」「パック」「まとめて実行」の使い方は一致。ホームの「入口の条件」だけ古い語(A-09 で直す)
- 文字記号(A-10): 3 画面とも ▾ ▸ × ⚙ ☰ ✂ が残っていた(ブリーフの Anti-references)。ui-kit v23 で `.ui-caret` と SVG に統一し、各ツールで置き換える

## 4. 直したもの(周ごと)
### 1 周目
- ui-kit v23: 文字記号 → SVG / `.ui-caret`・リンクの青 `--accent-ink2`・summary の高さ 28px・`.ui-live-panel:focus-visible`・知らせの × を 28px の SVG・設定の全体の節の label・styleguide の label と ▾
- ホーム 0.42.3 / スタジオ 0.22.3 / 編集 0.59.3: (直し役の報告から書く)

## 5. 残したもの(Should・Could → `plan/improvements.md` の「UI の見直しの残り」)
(1 周目の後に書く)

## 6. 良かった所(見直し役の報告から)
(待ち)
