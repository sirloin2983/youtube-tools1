状態(2026-10-10 深夜): RS8 の画面の設計の下調べ(Sonnet 1 体・Haiku 1 体。読むだけ)。brief は別に書く

# RS8 下調べ: 今の画面の地図と「確かめる」の材料

## 1. 今の画面の地図
| 画面 | URL | 主な操作 | 次に行く画面 |
| --- | --- | --- | --- |
| ホーム | `/`(`src/home/portal.html`・`portal.js`) | 「次にやること」(最大 5 件の作業のリスト)・案件(配信ごと)の一覧・状態とメモ・まとめて実行・続けて確認 | 行のボタンは同じ窓で移動: 候補・書き出し・文字起こしの待ち → `/studio/?video=<id>` / 校正待ち → `/transcribe/?doc=<tid>&media=…#tx` / パック待ち → 同 `#pack` |
| 案件ページ | `/cases.html` | 独立の画面ではなく `/#cases` へ転送(`launch.py:630`) | ホーム |
| 続けて確認(ホームの右の引き出し `#rvDrawer`) | `/` の中 | 自動の切り抜きを 1 本ずつ再生。A 採用(友人へ届ける)/ X 要らない / N 次へ(A5) | 編集で開く |
| 設定 | `/settings` | 全ツールの設定を 1 画面に(検索・即保存) | 各ツールの ⚙ から |
| スタジオ ① 探す | `/studio/?step=rank` | 検索 → チェック → 解析に追加・URL から入れる・解析の待ち | ② |
| スタジオ ② 確認・書き出し | `/studio/?video=<id>`(`review.js`) | 配信の選択・プレーヤー・タイムライン・マークの一覧(採用 / 不採用 / 候補・候補をすべて採用)・書き出しの引き出し | 「編集で開く」(`/transcribe/?media=<mp4>`。別窓 = 決定 (ad))・「案件で見る」 |
| スタジオ LIVE | ② と同じ画面(kind live) | LIVE の帯(録画・書き出したあと・配信者・作り直す・配信中の候補) | ② と同じ |
| 編集 1 文字起こし | `/transcribe/#tx`(`?doc=` `?media=` `?clip=` `?list=` `?drill=1`) | 左のメニュー(新規・履歴・精度・学習)・行の編集・文書ごとのまとめて実行 | Alt+2 → 2 カット |
| 編集 2 カット(末尾にパック) | `#cut` | タイムライン・たたき台 3 種・字幕の一覧・パックを作る・フォルダ・zip・友人へ届ける・サムネの案 | Resolve |
| 評価ドリル | `/transcribe/?drill=1` | 評価用を 1 本ずつ全部聞いて直す・済みにして次へ(Shift+D)・飛ばす | 次の文書 |

- 典型の流れ(配信 1 本 → パック): ホーム → スタジオ ① → ② → (別窓の)編集 1 → 編集 2 = ツールをまたぐのが 3 回・画面の状態 5 つ。クリックは校正を除いて 配信の準備 8〜12・採否 N・書き出し 2・編集の入り口 1〜3・パックまで 3。複数の切り抜きは 1 本目だけ知らせから開き、残りはホームの案件の行か編集の履歴から 1 本ずつ
- 事実: 案件 id = スタジオの配信 id(`cases` ↔ `?video=`)。編集へは文書 id(`?doc=`)か動画のパス(`?media=`)。ホームは案件の集計(`manage/cases/cases.py`)と編集の `/transcribe/api/transcripts` を合わせて出す。URL の組み立ては `portal.js` の `docHref`・`studioHref`・`caseNextHref`(~920-960)。窓は `UIKit.win`
- **ホームの「次にやること」はもう作業の待ち行列の芽**(最大 5 件・行き先がスタジオと編集に分かれる)

## 2. 課題(出典つき)
1. 校正が律速: 動画 1 分に約 12.6〜16 分(improvements §1・`plan/line-a-proofread-effort.md`)。重いのは つなぐ・分ける(約 70 秒/件)と文字の直し(約 31 秒/件)。A6 でキー M / Shift+M / Y(編集 0.63.0)
2. 確認作業が画面ごとにばらばら(improvements §13)
3. ツール別の入口と窓の行き来(決定 (ad) の別窓・同じ配信の複数の切り抜きを渡る導線が弱い・「次にやること」の行き先が分かれる)
4. UI の見直しの残り(improvements §11): スタジオの強調色が 4 つ・解析の入口が 2 つ・保存の状態の置き場所が画面ごとに違う(B-07)・タブを替えると appnav が横に動く(B-06)・まとめて実行の失敗の表示が弱い(B-11)
5. 「3 パック」の古い文言(improvements §6)
6. ドリルと続けて確認の実装が別
7. ライブの画面の未対応(improvements §6: 録画済みの範囲と欠け・時間のずれ・「停止」の重なり)

## 3. 「確かめる」(V1)の 7 項目の今
| 確認 | 今の画面と操作 | 書く記録 | 読む道具と目標 |
| --- | --- | --- | --- |
| 1 定点 G2(評価ドリル) | 編集 `?drill=1` の帯・済みにして次へ(`/api/drill/reviewed`) | 文書の `evalReviewed`・行の `proofed` | `eval_asr`。目標 `accuracy.py:60-63`(G2 定点 30 分)。**ドリルの帯は 15 分(`drill.py:37`)= 食い違い** |
| 2 話者 | ドリルの中(独立の ○× は無い) | 行の speaker・`evalReviewed` | `eval_speakers`(確かめ済みの行 200) |
| 3 「別」の採否 | 校正の行の札「別」(`/api/suggest/feedback`) | `learn-feedback.json` の alt・`<id>.alt.json` | `eval_alt`(判定できた候補 100) |
| 4 後処理の札 | 行の札「別の読み」(unfill) | 行の text と `fill` | `eval_fill`(FEW_ROWS 30)。**「あと何本」の表に無い** |
| 5 候補の採否 | スタジオ ② / 録画の 届けた・要らない | `feedback.jsonl`・`live_feedback.jsonl`・`friend_feedback.jsonl` | `eval_marks`(配信 10 本) |
| 6 カットのたたき台 | 編集 2 カット | `<id>.edit.json`(draft)・packs | `eval_cut`(パック 20 本) |
| 7 自動の切り抜きが 70 点以上か | **無い**(候補の点数 `score` は .clip.json にある・見たかは `clip.review.seenAt` だけ) | なし | なし |
- 「あと何本」: 計算は `src/eval/drill/accuracy.py` の GOALS(:59-68)・`goals_of`(:213-231)・夜に測り直して `accuracy-state.json`。表示は `GET /api/accuracy` → `portal.js:1654-1680` の `goalsRow`。定点の残りは `drill.py:156-189` の `drill_status`
- 1 件の時間は未計測(`eval_effort.py` の activeSec・cutSec から測れる)
- `src/home/README.txt:515-523` の accuracy の場所が古い(`src/home/accuracy.py` → 実体は `src/eval/drill/accuracy.py`)
