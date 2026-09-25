# 文字起こしツール v0.9.4(serve.py / index.html とも 0.9.4)

## 背景
質問「スタジオのマーカから読み取る機能は、すでに読んだやつをはじいてくれる?」→ v0.9.3時点では未対応(フォルダタブの「済みはスキップ」はあったが、マーカーのポイントタブには無かった)。追加実装。

## 実装
- serve.py: `transcribed_ranges()`(全文字起こしの sourcePath・start・end・whole・tid の一覧)、`_covered(ranges, path, start, end)`(全体処理済みなら常に「済み」、部分は対象範囲の9割以上重なれば「済み」)。scan_folder の done 判定もこれで統一。
- `read_marker()`: 各ポイントに `doneTid` を付与。書き出し済みの mp4(fileAbs)がある場合はその mp4 が一度でも文字起こしされていれば「済み」。無い場合は動画の sourcePath + 区間の重なりで判定。
- 新エンドポイント `GET /api/transcribed-ranges`(生の一覧。data.json を直接選ぶ場合にクライアント側で判定するため)。
- index.html: マーカータブに「文字起こし済みはスキップ」チェック(既定オン)。済みのポイントは最初からチェックが外れ、「文字起こし済み」pill が付く。data.json を直接選ぶフロー(`#markerFile`)でも、`/api/transcribed-ranges` を取得し `coveredBy()`(JS版、path は簡易正規化)で同様に判定(fileAbs 相当は分からないので sourcePath+区間のみ)。
- テスト: test_metrics.py に `_covered` の単体4件、e2e_ui_v09.py にサーバー側 doneTid・/api/transcribed-ranges・画面(pill・スキップ既定オフ・トグル)を追加。変異4種で検出確認。

## 制約
- data.json を直接選ぶフロー(スタジオ/旧マーカーが自動で見つからない場合)は、書き出し済み mp4 の実在確認をしないため、mp4 経由の「済み」判定はできない(sourcePath+区間のみ)。
- 重なり判定は9割のしきい値(前後のパディング分の誤差は吸収する想定、未実測)。
