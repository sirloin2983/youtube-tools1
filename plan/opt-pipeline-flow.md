状態(2026-10-11): 調べは済み・実装はまだ(下の「いつやるか」の合図で始める)。① の機能を 1 つずつユーザーと見ていく途中で、見つけた物はここへ足す

# OPT ① 道具・② 管理の最適化(工程をまたいだ同じ作業をまとめる)

前提: 2026-10-11 ユーザー「① や ② はどんどん最適化していきたい」「実装はいい感じのタイミングで」。RV(全体の見直し)を待たず、普段の作業の合間に段ごとに入れる(`plan/data.js` の RV の行)。調べは読むだけのサブエージェント 2 体(① Opus・② Sonnet。10-11 朝)。行数は調べた時点の目安。

## わかったこと
- 字面のコピーはほとんど無い。重複は「同じ作業を工程ごとに書き方を変えて書いている」形で、① は **ffmpeg の扱い**(探す・動かす・調べる)に集中している
- ② は **① の仕事が ② に残っている**(決まり「② に変換のコードを書かない」に反する)のと、**基盤にある部品を使っていない**所が多い。ライブ系が大きいのは重複より説明文(約 545 行)と 1 クラスに役目が詰まっているため
- 減る行は全体で 700 行前後。効くのは不具合・速さ・直しやすさ

## OPT1 すぐやる(安全・不具合つき。約 250 行減)
| 項目 | 場所 | 効き目 |
| --- | --- | --- |
| ffmpeg・ffprobe・yt-dlp の探し方を `ytt/tools` の 1 つに(ツール固有の環境変数 → YTT_ → PATH → winget) | `ytt/tools.find_ffmpeg`・`ytt/studio_env.find_tool`・`pipeline/ingest/rec_core.py`・`flow/live_archive.py`・`ytt/normalize.probe`・`tools.media_tool`、yt-dlp は STUDIO_・YTT_・TRANSCRIBE_ と無し | **不具合**: winget だけで入れた PC(友人の PC)で解析・書き出し・録画が ffmpeg を見つけられない。F1 の前に必ず |
| スタジオの書き出しに古い ffmpeg(5.1 未満)への逃げ道 = `normalize.run_with_legacy` | `pipeline/export/exporter.run_ffmpeg`、ライブの書き出しの自前の逃げ道も寄せる(`flow/live_export.py` の _encode) | **不具合**: 古い ffmpeg でスタジオの書き出しだけ落ちる |
| 解析の音量を 1 回のデコードに(asplit。配信中の検出 `measure_levels` と同じ形) | `pipeline/analyze/analyze.py` の audio_levels | 長いアーカイブの音量の段がおよそ半分の時間。上限 20dB の扱いをそろえて `test_analyze` で確かめる |
| パックの自前の書き込み・JSON 読みを `fsio` へ | `pipeline/pack/srt2resolve.py` の _replace_retry・staged・write_bytes_atomic、`cut2resolve_core.read_json_file`・_unlink_quiet | 約 50 行。もう ytt を読んでいるので写しは要らない。契約テスト |
| ② の基盤の使い忘れ | 空き容量(`fsio.existing_parent`・`_disk_usage` が 2 つ)・JSON の保存(`fsio.write_json` に fsync を足す。6 か所)・出力の確かめ(`normalize.verify`)・`start_logged` を `ytt/tools` へ・`live_tx` を `tools.run` に(取り消しが効く) | 約 60 行 |
| 小物 | ffprobe を 1 回呼ぶ所を 1 つに・SRT の時刻 2 つ・`_sec` 2 つ・区間をつなぐ 3 つ・16kHz の wav の読み 3 つ・「NFKC → 文字と数字」の寄せ方 4 つ・`diar` の定数の読み出しを ytt へ | 約 120 行。契約テスト・text_chars の NFKC の差だけ注意 |

## OPT2 形を決めて進める(約 400 行減・② が決まりどおりになる)
- ffmpeg を進み具合・取り消しつきで動かす部品 6 つ(`tools.run_progress`・`exporter._pump`・`cut2resolve_core._ffmpeg_stream`/`_ffmpeg_run`・`procs.run_capture`・`recognize.extract_audio`・`live_excite_worker.measure_levels`)→ `run_progress` に時間の上限・標準エラーを全部持つ選択・spawn の一覧に載せる選択を足して 1 つに。窓を出さない・優先度「低」を全部に。約 120 行
- ② に残る ① の仕事を ① へ: 音量とラウドネスの ffmpeg(`flow/live_export` と `exporter` → `pipeline/export/audio.py`)・ライブの切り出しのエンコード(`normalize` に区間・concat 版)・wav の取り出しの引数(`flow/live_tx`・`flow/live_archive._wav`。精密な切り方は残す)・パックの指定の組み立て(`flow/tools.py` の _pack_request など = cut2resolve の serve の写し → `pipeline/pack` に 1 つ。エラーの厳しさをどちらに合わせるか決める)
- ライブの見回りの糸の骨組み 3 つ(書き出し・取り込み・配信中の文字起こし)を小さな基底に・`Cancelled` / `Halted` を 1 組に
- `ffmpeg -i` の読み 2 つ(カバー画像の扱い)・音量の ffmpeg の引数を `ytt/loudness` へ(パックの写しが 1 回作り直し)
- 字幕の時刻が数 ms 動く所(wav の切り方をそろえる)は `src/eval/tools/eval_timing.py` で確かめてから

## OPT3 データを見てから
- かなへの寄せ方 3 つ(`llm.llm_fold`・`roster.fold`・`txbase.alt_fold`。伸ばし「ー」の扱いが違う)・Text+ の改行の文字の種類(`resolve_textplus._char_kind` と `txbase.char_class`。ヽヾ のときだけ見た目が変わる)・出力の確かめ方の厳しさ 3 つ・録画元から取ってつなぐ所 2 つ(プロセスの境目)
- ライブの大きなクラスを割る(配信後の全自動を `live_after`・マークの置き場を `live_marks` に)は行数が減らず差分が大きい = RV で

## まとめない(別物)
子プロセスの常駐と見張り(worker・各 live_*_worker・recorder)・HLS の読み方 2 つ・チャットの読み方・行の分け方と Text+ の改行と SRT の折り返し・`live_archive._wav`(8kHz・精密)と `recognize.extract_audio`(16kHz)の中身・cv 待ちと Event の見回り・③ のための素通しの動詞(層の決まり)

## いつやるか(合図)
- **OPT1**: RS7-2 のセッションの「使わないモデル・エンジンの選択肢を消す」が main に入ったら(`tx_engines`・ワーカーとぶつかるため)。RS8 と並べてよい(触るファイルが重ならない)。**F1 より前に必ず**(ffmpeg の探し方の不具合)
- **OPT2**: OPT1 のあと、F1 の前(友人の PC で動く ② を決まりどおりにしてから渡す)。RS8 がライブの書き出し・パックの口を触るならその前後で調整
- **OPT3**: V1・G2 などで採点と字幕のデータがそろってから
- 各段の終わりに層ごとの行数を WORKLOG に 1 行(数え方は 10-11 の WORKLOG)
