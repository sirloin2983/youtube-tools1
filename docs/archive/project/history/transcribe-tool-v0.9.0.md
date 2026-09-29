# 文字起こしツール v0.9.0(serve.py / index.html とも 0.9.0)

v0.8.3 からの追加。ユーザー要望の一括対応(質問→実装)。

## 実装
- **フォルダ一括**: POST /api/scan-folder {path, recursive}(直下のみ。recursive は3階層・最大500本)、POST /api/transcribe-batch {paths, skipDone, ...jobOpts}。動画ごとに別の文字起こし。済み(sourcePath 一致 かつ whole)と待機中は既定でスキップ。MAX_QUEUE 50→200。UI は新規カードの「フォルダ内すべて」タブ。
- **スタジオ連携(読むだけ)**: read_marker が STUDIO_DATA(環境変数 TRANSCRIBE_STUDIO_DATA、既定 <親>/clip-studio/data.json)→ 旧 MARKER_DATA の順に読み、videos は dict/list、マークは clips/marks/points のどれでも可(label→title、file も保持)。settings.json の outDir を返し、フォルダタブに「スタジオの書き出し先」ボタン。**実物の data.json では未確認**(スタジオ spec に data.json の形の記載なし)。
- **Tab 切り替え**: 入力欄内 Tab→抜ける、外(選択行あり)→入力欄に入る。IME 変換中(isComposing/keyCode 229)・Shift+Tab・ダイアログ中は素通し。
- **時刻の微調整**: 選択行に 開始/終了 −/＋ ボタン(幅 0.05〜1 秒、V.adjStep)。最小幅 0.1 秒、Undo 可、並びが変わるときだけ sortSegs、押した端をすぐ再生。キー割り当てなし(要望どおり)。
- **部分再認識(範囲)**: /api/retranscribe に mode:"range"。選択行の最初〜最後(間も含む・最大 MAX_RANGE_SEC=900)を1チャンクで認識→ wordSplit で行分割→ apply_range で差し替え。話者は最大重なり行から継承、proofed/tags は継承しない、original は replace_original_multi、.bak と履歴に退避。範囲外にはみ出す時刻は範囲内に収める。
- **青枠**: `.seg.nav` = 3px 太枠(自分で選んだ行だけ)。`.seg.cur`(再生中)は薄い背景+左端線で枠なし。既定では枠は再生に追従しない(V.frameFollow、既定オフ)。直前の行が 1.4 秒かけて消える(.was)。ensureVisible: 見える範囲なら動かさず、外れたら上から35%になめらかに寄せる(reduced-motion 対応)。
- テスト: test_metrics.py 26 件、e2e_ui_v09.py(フォルダ/スタジオ/範囲/Tab/微調整/枠)。変異チェックで主要ロジック全検出。

## 未確認・注意
- スタジオ data.json の実物の形と書き出しフォルダの構成(要サンプル)。
- 「青枠が見にくい」の解釈: 太枠=選択行/再生行=薄色に分離。意図と違えば要調整。
- 実エンジン(faster-whisper)での範囲再認識は疑似モードのみ検証。長い範囲の所要時間・GPU失敗時の CPU 再試行は実機未確認。

## 保留(記憶済み)
- 文字起こしをスタジオへ返す機能(後で実装)。
