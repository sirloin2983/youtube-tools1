# 文字起こしツール v0.9.1〜v0.9.2(serve.py / index.html とも 0.9.2)

## v0.9.1
- スタジオの実 data.json(schema clip-studio/v1)で確認: videos は {ID: 動画}、マークは marks、動画の path、書き出し済みは file=書き出し先からの相対パス。15本・133マーク(exported 37 / rejected 11 / adopted 2 / 候補 83)。
- marker_videos: sourcePath は sourcePath または path、local は kind が local/file も。書き出し先(settings.json outDir)配下で実在する mp4 に fileAbs を付与(パス外へ出ないよう realpath+commonpath で検査)。
- マークタブ: 元の動画のパスが空でも、書き出し済み mp4 をそのまま /api/transcribe-batch に渡して文字起こし。

## v0.9.2
- **進行度**: GET /api/progress(校正済みかつ「聞き取れない」でない行の秒数・行数の合計。mtime+size でキャッシュ)。左の「進行度」カード(棒・今日の増分〈localStorage 基準〉・節目 30分/1時間/3時間/目標)と、上の帯(押すとカードへ)。目標は settings.goalHours(既定5時間、0.5〜200)。節目到達で1回だけ通知。節目は「目標=時間」ではなく判断の目安(LoRA は dev で勝つかで判断する、と合意)。
- **カードの折りたたみ**: 左の各カード(処理状況・保存済み・精度測定・学習候補・保存データ・進行度)を details 化。開閉は localStorage `tx.fold.<id>`。保存済みは件数を見出しに表示。
- **スタジオのマーク取得元**: 読み込み元(スタジオ/旧マーカー/選んだ data.json)とパス、書き出し先を表示。動画の選択肢に [スタジオ] 等、各ポイントに 自動(点数)/手動・状態・mp4あり。
- テスト: e2e_ui_v09.py に進行度・折りたたみの保持・取得元表示を追加。変異チェック4種(unclear 除外・折りたたみ復元・節目の絞り込み・取得元の一覧)で検出。

## 未確認
- 実機での校正ペース(進行度の「今日の増分」で測れる)。実エンジンでの範囲再認識・一括追加。
