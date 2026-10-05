# recorder/ — 録画の部品(線 D: リアルタイム切り抜き)

AI 向けの決まり。計画は `docs/plan/live-clipping-plan.md`(**0. 10-04 の見直しが正**)。使い方は `README.txt`。

## 形
- 入口とは**別のプロセス**(`recorder.py`)。入口(`home/live.py`)が、設定 `live.enabled` がオンの間だけ切り離して起動し、30 秒ごとに見回る。
  入口の「すべて終了」では止めない(録画を続ける)。版(`recorder.py` の `VERSION`)が上がると、録画中でなければ入口が終わってもらって起動し直す
- 1台で始めて2台(P5)に広げられる作り(計画の 0-2): 同じプログラム・同じ HTTP API。1台は `127.0.0.1` だけで待ち受け、2台は `--host`・`--allow-host`。
  合言葉(`Authorization: Bearer`。`<作業データ>/recorder/token.txt`)と Host の検査は1台でも同じコードを通る
- ブラウザは録画の部品へ直接つながない(Origin・Sec-Fetch-Site がある要求は 403)。画面は入口の `/live/r/<録画元>/…` の中継を通す
  (同じオリジン・CSP `script-src 'self'`・入口の合言葉のまま。CORS は要らない)。入口とスタジオは「録画元の一覧」(設定 `live.recorders`)を通して読む
- `rec_core.py` が録画の中身(セッション・再生リスト・繋ぎ直し・起動時の復旧)、`recorder.py` が HTTP と起動
- P2(マークと書き出し)は入口の側(`home/live_export.py`。マークの正本・書き出しのジョブ)。この部品は「区間の取得」
  `GET /live/<id>/segments?start=&end=`(UTC の時刻。区間にかかるセグメント `{uri, session, pdt, dur}`・欠け `gaps`・`lastPdt`・`active`)と
  セグメント本体を返すだけ(書き出し・作り直しはしない = 2台のときもノート PC は録るだけ)。欠けの規則は `rec_core.pick_segments`(GAP_TOL 秒より空いたら欠け)

## 決めたこと(2026-10-04)
- 録画は `-c copy` の HLS(`-hls_playlist_type event`・`temp_file+program_date_time`)。時刻は受信時刻(PDT)を UTC にそろえて返す
- **SLOTS(`ytt_core/jobs.py`)を通さない**: 作り直さない写しで軽く、配信中は順番待ちで止められないため。代わりに録画の部品と子(ffmpeg・streamlink)は「通常より上」の優先度
- 子は Windows のジョブ(閉じると子も消える)に入れる: 部品が落ちたときに子が残って書き続けない
- 配信の終わりの見分け: streamlink は切断でも終了コード 0 で終わる。記録に `No new segments`・`Reloading failed` が無い 0 だけを「終わり」とする(8.6.1 で確かめた)。
  `--stream-types hls` で、終わった配信(アーカイブ)を取りに行かない。それでも実際の時間の 3 倍より速く取れたらアーカイブとみなして止める
- 置き場所のドライブが無いときは作業データの中へ逃がさない(画面で案内)。空きが 1GB を切ったら録画を止める。自動では消さない
- 名前なしで始めた録画には、配信の題を付ける(`rec_core.fetch_title` = YouTube の oEmbed。録画とは別のスレッド・取れなくても録画は続く・付けた名前は上書きしない・direct(テスト)では聞かない。2026-10-05)
- 画面はスタジオの中(P3。2026-10-05。`home/live.html` は消した)。スタジオの画面が入口の `../live/…` を呼ぶ(`docs/plan/live-clipping-plan.md` の 0-8)
- API を足したら版を上げる(入口の見回りが、録画中でなければ新しい版で起動し直す。古い版のままだと新しい API が 404 になる)

## テストの実行(リポジトリ直下から)
- `py -3.10 -m unittest recorder/tests/test_recorder.py`(ffmpeg の lavfi で作った HLS を手元の HTTP サーバーで配信中のように出し、
  `--source direct` と streamlink の `hls://` で録る。本物の YouTube には繋がない。streamlink が無ければその分は skip)
- 入口の側を変えたら `py -3.10 -m unittest home/tests/test_live.py` と `PYTHONIOENCODING=utf-8 py -3.10 home/tests/e2e_live.py`
  (Edge があれば H.264 の再生・シークまで確かめる。Playwright 同梱の chromium は読み込みまで)
- テストの先頭で `os.environ.setdefault("YTT_DATA_DIR", "inplace")`。inplace の作業データは `recorder/data/`(`.gitignore` 済み)

## 注意
- ツール間で同じ名前の .py を作らない(`rec_core`・`recorder` は他と重ならない)。`/api/ytt/` で始まる API を作らない
- 入口の「調子」の録画の行・中継は `home/live.py`、設定の節は `home/prefs.py` の `live`
