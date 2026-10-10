# RS5 下調べ: 疑似の分岐と「確認してから届ける」(A・B)

状態(2026-10-10): 下調べ(Haiku)の報告

読むだけの調査。コードは変えていない。テスト(`tests/`)の中の分岐は数えていない。

## A. 疑似モードの分岐(本体 src/ の `if` など)

### A-1. 差し込み口を通らず環境変数・旗を直に見ている所(STUDIO_FAKE 系)

| ファイル:行 | 何を分けているか | 置き換えの見込み |
|---|---|---|
| src/ytt/studio_env.py:63・66 | 定義: `fake()`(STUDIO_FAKE=1)・`fake_media()`(STUDIO_FAKE_MEDIA) | 旗の持ち主。ここを口にすれば呼び側は変えずに済む |
| src/studio/serve.py:74・86・350 | 疑似なら認証・API キーの扱いを変える | 中。`_env.fake()` の代わりに登録の口 |
| src/studio/common.py:81・120 | 疑似なら動画の取得・yt-dlp の確認を飛ばす | 中 |
| src/pipeline/export/exporter.py:207-208・304 | 疑似は元動画を STUDIO_FAKE_MEDIA で切り出す・yt-dlp の検査を飛ばす | 中 |
| src/pipeline/batch.py:87・98 | 疑似は ffmpeg・yt-dlp の存在確認を飛ばす | 低(確認の飛ばしだけ) |
| src/pipeline/analyze/analyze.py:134-135 | 疑似は動画の代わりに `fake_media()` | 中 |
| src/pipeline/analyze/analyze.py:278-279・439・553-554 | 疑似はチャット・コメント・メタの取得を STUDIO_FAKE_CHAT / _COMMENTS / _META の JSON に | 中(取得元の口が 3 つ要る) |
| src/pipeline/analyze/analyze.py:353 | 疑似は動画 ID の検査を飛ばす | 低 |
| src/human/find/rank.py:60 | 疑似は YouTube Data API の代わりに `fake_get`(rank.py 内の疑似本体) | 中。疑似本体を eval/fake へ移すなら口が要る |
| src/human/friend/intake.py:152 | `os.environ.get("STUDIO_FAKE")` を直接読む(ytt の旗を通らない) | 低。`studio_env.fake()` に寄せるだけで直る |

小計: 旗の判定の直読み 1 件(intake.py)+ `_env.fake()` の呼び出し 18 件前後。

### A-2. 文字起こしの疑似(TRANSCRIBE_BACKEND=fake・`backend_name() == "fake"`・`.select().name == "fake"`)

差し込み口は既にある: `src/pipeline/transcribe/backend.py` の `Backend`(REAL)・`select()`・`set_selector()`。疑似の本体は `src/eval/fake/fake_asr.py`(FAKE)。serve.py:181 で `set_selector(lambda: fake_asr.FAKE if ed_state.backend_name() == "fake" else REAL)` が入っている。

| ファイル:行 | 何を分けているか | 置き換えの見込み |
|---|---|---|
| src/editor/ed_state.py:186-187 | `backend_name()` の定義(環境変数 TRANSCRIBE_BACKEND == "fake") | 旗の持ち主。selector の判定はここを読んでいる |
| src/editor/serve.py:181 | selector の判定(疑似か本物か) | 既に口を使っている。判定の元を名前から旗に替えれば足りる |
| src/editor/serve.py:232・768 | 画面に backend 名を返す・faster-whisper の無いときの判定 | 低 |
| src/human/proof/speakers.py:520・871 | 疑似なら判別の可否・疑似の表示を分ける | 低〜中。`select().name` を見ずに Backend のメソッドへ |
| src/human/proof/alt.py:70・144・178 | 疑似なら候補の認識・ログを分ける | 中。alt_rows は既に口にある |
| src/pipeline/transcribe/diarize.py:82・343 | 疑似なら判別の可否・判別の経路 | 低〜中(口の diarize / embed はある) |
| src/pipeline/transcribe/llm.py:256-257 | 疑似なら TRANSCRIBE_FAKE_LLM の文字を返す | 中。Backend に LLM の口を足す必要がある |
| src/pipeline/transcribe/fill.py:297-298 | 疑似なら TRANSCRIBE_FAKE_FILL の文字を返す | 中。Backend に読みの口を足す必要がある |
| src/pipeline/transcribe/tx_engines.py:839・1155 | エンジンの FAKE_TEXT / FAKE_REPLY が文字列なら音声を読まず文字を返す | 低(エンジン単体の疑似口。ワーカーの疑似が使う) |
| src/eval/tools/eval_asr.py:695・881 | 疑似なら transcribe_fake・採点の保存を飛ばす | 低(測る道具) |
| src/eval/tools/eval_speakers.py:780・818 | 疑似なら diarize_fake・実音声の有無 | 低(測る道具) |

小計: `.name == "fake"` / `backend_name() == "fake"` の判定 約 15 件(py)。実際の分岐は 10 前後。JS 側(src/editor/app-core.js:453・457・464)も `t.backend !== 'fake'` で表示を分けている(画面の 3 件)。

### A-3. 認識ワーカーの疑似(TRANSCRIBE_BACKEND=worker-fake・`worker_fake()`)

| ファイル:行 | 何を分けているか | 置き換えの見込み |
|---|---|---|
| src/pipeline/transcribe/worker_client.py:742-745 | 定義 `worker_fake()`(環境変数 == "worker-fake") | 旗の持ち主 |
| src/pipeline/transcribe/worker_client.py:120・519・671・722 | ワーカー起動の環境・whisper-cli の選び方・GPU 判定・部品の有無 | 中。ワーカーの名前の口(FAKES_MODULE)は既にある |
| src/pipeline/transcribe/diarize.py:63・109 | ワーカーの中の判別を偽に | 低(FAKES_MODULE で差し替え済み) |
| src/human/proof/speakers.py:522 | 判別の可否 | 低 |
| src/pipeline/transcribe/worker.py:168 | install() を呼ぶか | 低。既に FAKES_MODULE の名前で動く |
| src/editor/serve.py:191 | `_txworker.FAKES_MODULE = fake_worker.__name__` を入れる | 既に差し込み口 |

小計: 約 10 件。worker-fake は既に名前の口(`FAKES_MODULE`・`FAKES_ENV`)で差し替え済み。残るのは「旗の判定」の直書きだけ。

### A-4. 疑似の関数の呼び分け(`fake_` の関数名)

- `src/editor/ed_jobs.py`・`ed_alt.py`・`ed_speakers.py`: 転送の殻。serve.py:182-203 が `_add_moved(fake_asr)` 等で本体を足す(RS5 で殻ごと消す)。
- `src/eval/tools/eval_asr.py:695`・`eval_speakers.py:847`・`eval_cloud.py:264`・`_evalcommon.py:184-191`: 測る道具の疑似の呼び分け(`C.fake_job()`・`TRANSCRIBE_BACKEND` を書き換える)。

### A-5. 置き換えの要点

1. 既に口がある: 文字起こし系は `backend.set_selector` と `Backend` のメソッド(alt_rows・diarize・embed)。ワーカーは `FAKES_MODULE`。ここは「名前の判定」を「口のメソッド」に寄せれば済む。
2. 口が無い: studio 系(`studio_env.fake()` の分岐 18 件前後)と LLM・読み(fill.py・llm.py)の疑似。studio 側は「取得元の口」(動画・チャット・コメント・メタ・API)を作る必要がある。
3. 最小の一手の候補: `src/ytt/studio_env.py` と `src/pipeline/transcribe/backend.py` に旗の登録の口を作り、`backend_name() == "fake"` と `_env.fake()` の直書きを順に差し替える。

## B. 友人の依頼の「確認してから届ける」(L1・L2・L3)

確認の経緯: docs/spec/friend-intake.md の「flow」表(① auto / ② check / ③ manual)と plan/decisions.md の 3-25 の h(RS3-h 確)。h の決まり: L1・L2 は RS5 で友人のアプリの更新と一緒に ① へ読み替え、L3 は RS6 のあと。

### B-1. L1: 友人のアプリから来る ②③ の依頼(intake の kind・flow)

| 種類 | ファイル:行 | 内容 |
|---|---|---|
| 友人の送る側の値 | friend-apps/request-sender/src/Core.cs:26 | `Auto = "auto", Check = "check", Manual = "manual"` |
| 送る側の既定 | friend-apps/request-sender/src/MainForm.cs:679-694 | `SelectedFlow` の既定は `Flow.Auto`(①)。Manual のときカット・トラック・届け方を使わない |
| 送る側の送信 | friend-apps/request-sender/src/MainForm.cs:940 | `flow = SelectedFlow` を JSON の `flow` に入れる |
| 送る側の範囲 | friend-apps/request-sender/src/TimeCore.cs:240・257 | Manual のとき範囲の本数を 0 にする(② の上位 N の扱い) |
| 送る側のライブ | friend-apps/request-sender/src/MainForm.cs:711-712 | ライブ配信の依頼は flow を Auto に固定して戻す |
| PC の受付(表示名・既定) | src/human/friend/intake.py:41 | `FLOW_LABELS` の定義。無ければ ② |
| PC の受付(読み) | src/human/friend/intake.py:517 | `flow = d.get("flow") if ... in FLOW_LABELS else "check"` |
| PC の受付(手動の流し) | src/human/friend/intake.py:622・653 | 動画(file)は "check"・URL の手動取り込みは "manual" |
| PC の受付(実行へ) | src/human/friend/intake.py:726・816・823 | `_accept_video`・`_process_urls`・`_record` が flow を受けて記録に入れる |
| 実行の口 | src/home/autorun.py:70-71・416・424・447・458 | `FLOW_MODES`(url・file × auto/check/manual)と `start_request`・`start_file` |

L1 の作業量の目安: 友人のアプリの値を変えずに PC 側だけで ②③ を ① に読み替えるなら、intake.py:517 の読み替え 1 か所と autorun.py の `FLOW_MODES` の差し替え(check・manual を auto へ)で済む。送る側(Core.cs・MainForm.cs)は RS5 で友人のアプリの更新と一緒。

### B-2. L2: ライブの after(既定 check)

| 種類 | ファイル:行 | 内容 |
|---|---|---|
| 既定 | src/home/live.py:352 | `"after": ... else "check"`(書き出したあとの自動の流れの既定) |
| 設定の読み | src/home/live.py:348・352 | ホームの設定 `live.auto.after`(prefs が検査) |
| 受け口 | src/home/live.py:26・577・579 | `POST /live/api/adopt` の `after`。`live_export.check_after(body, auto["after"])` |
| 値の定義 | src/pipeline/export/live_export.py(`AFTERS`・`check_after`) | 値の一覧(ここは読んでいない。名前だけ確認) |
| 友人のライブ依頼 | src/home/live.py:746-763 | 録画が依頼に結びつくと `after=auto` に固定して `_auto_deliver_for` |
| 友人のライブ依頼の受付 | src/human/friend/live_requests.py:9・19・41-42 | 設定の既定 `afterStream`(配信後の追加の真偽・既定 True。flow ではない) |
| 送る側 | friend-apps/request-sender/src/StreamCard.cs:478・517-519・559 | 「配信が終わったあと、アーカイブからも追加する」(afterStream) |
| 送る側の JSON | friend-apps/request-sender/src/TimeCore.cs:316・354・381 | `"live":{...,"afterStream":true}` |

注意: 友人のライブ依頼は PC 側で `after` が auto に固定されている(decisions 3-25 の h でいう L2 の「既定 check」は、ホームの自動の流れ `live.auto.after` の既定)。

### B-3. L3: 手で届ける(編集の「友人へ届ける」・案件の「採用して届ける」)

| 種類 | ファイル:行 | 内容 |
|---|---|---|
| 案件の「採用」 | src/manage/cases/cases.py:363・365・380-382 | `auto_review` の op `deliver` = 友人へ届ける(パックがあるときだけ)。`_deliver` を呼ぶ |
| 案件の届け処理 | src/manage/cases/cases.py:512 | `_deliver(repo_root, c, cl, deliveries, feedback, env)` |
| 画面(案件) | src/home/portal.js:449-499 | 「採用」ボタン・`deliverWhy`(届け先が決まっていない等の理由)。文言: 全自動の流れでは届けない = 人が確かめてから |
| 画面(編集) | src/editor/pack-tab.js・src/editor/index.html・src/editor/ed_thumb.py | 「友人へ届ける」(入口から開いたときだけ) |
| 届けの本体 | src/human/friend/deliver.py・src/human/friend/delivery.py | zip 作り・届け先への置き場所 |
| 届けた記録 | src/human/friend/friend_feedback.py | `deliveries.jsonl`(zip の名前・依頼 id 等)。「要らない」が引く |
| 自動の届け(参考) | src/home/autorun.py(`_deliver_pending`・`_deliver_batch`) | ① の全自動が届ける側。L3 とは別経路 |

L3 の注意: cases.py:363 の docstring どおり、人の切り抜き(clip["manual"])はこの口では届けない。L3 は RS6 のあと(decisions 3-25 h)。

### B-4. テスト

| 対象 | テスト |
|---|---|
| L1(受付・flow・②③) | src/home/tests/test_intake.py・test_autorun.py・src/home/tests/test_deliver.py・src/human/friend/tests/(test_friend_feedback.py) |
| L2(ライブの after・afterStream) | src/home/tests/test_live.py・test_live_archive.py・test_live_detect.py。画面は e2e_live.py・e2e_live_archive.py・e2e_live_studio.py |
| L3(採用して届ける・友人へ届ける) | src/home/tests/test_deliver.py・src/editor/tests/e2e_edit_pack.py(編集の「友人へ届ける」)・src/editor/tests/test_edit.py |
| 送る側(C#) | friend-apps/request-sender の build.bat(テストは C# の build に含む) |

### B-5. 送る側の値の要点(friend-apps/request-sender)

- Version = 2.9.0(Core.cs:20)。flow の値は `auto` / `check` / `manual`。既定は ①(`auto`)。
- ライブ配信の依頼は flow を `auto` に固定(MainForm.cs:711-712)。
- `afterStream` の既定は True(StreamCard.cs:517・TimeCore.cs:381)。
- `deliverBatch` は依頼の JSON に入る(2-16)。

## まとめ

- A: 本体の疑似分岐は約 40 件(旗の判定 + 名前の判定 + 疑似の呼び分け)。差し込み口が既にあるのは文字起こし系(backend.py の select・set_selector・FAKES_MODULE)。studio 系(`studio_env.fake()` 18 件前後)とは口が無い。
- B: L1 = intake.py の読み替え 1 か所 + autorun.py の FLOW_MODES(送る側は RS5 のアプリ更新と一緒)。L2 = live.py:352 の既定と live.py:577 の受け口。L3 = cases.py の auto_review・_deliver と portal.js の「採用」・pack-tab.js の「友人へ届ける」(RS6 のあと)。
