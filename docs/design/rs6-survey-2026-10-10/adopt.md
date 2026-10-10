状態(2026-10-10): RS6 の下調べ(Haiku)の報告

# RS6 下調べ: 自動採用(アーカイブ・動画ファイル)

読むだけ。コードは変えていない。行番号は 2026-10-10 時点の作業フォルダ。

## 1. 今のライブの自動採用

| 何 | どこ | 中身 |
| --- | --- | --- |
| 候補の検出・枠 | `src/pipeline/analyze/live_detect.py` 128 行(`AUTO_MAX_PER_REC = 10`・D-13 仮の数)、63〜64 行(`DETECT_DEFAULT`・`ADOPT_DEFAULT`) | 候補は PeakBook(帳簿 peaks.json)に frame/bench/adopted/dismissed で載る |
| 自動採用の設定の読み | 同 172〜174 行 `adopt_cfg()`、185〜190 行 `adopt_for(req)` | 録画ごとに {enabled, waitMin}。友人の依頼の録画は常にオン・待ちは依頼の waitMin(2〜15) |
| 採用の本体 | 同 478〜494 行 `adopt(rc, rec, pk, origin, after, streamer)` | `Live.adopt`(`src/home/live.py` 880 行)に通し、決定を decisions.json に残す。origin は "auto" か "manual" |
| 自動の見回り | 同 565〜611 行(M11)| 入口が候補を最初に見た時刻(`_seen`)から waitMin 分たったものを origin auto・after "auto" で採用。1 録画の上限 AUTO_MAX_PER_REC に達したら止めて帯に残す |
| 採用の数え方 | 同 538〜540 行 `auto_count` | decisions.json の adopted かつ origin auto の数 |
| 配信中の書き出し | `src/home/live.py` 841 行 `_studio_adopt_mark` | スタジオに手動マーク(status adopted)を作る |
| 既定値 | `src/home/prefs.py` 68 行 `"detect": {"enabled": True, "sens": "normal", "perHour": 6}, "autoAdopt": {"enabled": True, "waitMin": 5}`。検査は 267 行(perHour 1〜30)・281 行(waitMin 1〜60) | 既定はオン |
| 採用の HTTP | `src/home/live.py` 574 行 `POST /live/api/adopt`、`live_detect.py` の `POST /live/api/peaks {op: adopt|dismiss|restore}`(24 行) | 画面の帯の採用は origin manual |
| スタジオ側の印 | `src/studio/serve.py` 328〜331 行 `_adopt_top`(route 407 行 `/api/video/adopt-top`) | ライブ由来の解析とは別経路 |

注: 自動採用の上限・待ちは `live_detect.py` 内の定数と prefs の 2 か所に分かれている(spec の `adopt` 節とは別物)。

## 2. まとめて実行(URL・動画ファイル)の採用

| 入力 | 段(`src/pipeline/run.py` 33〜37 行 `MODE_STEPS`) | 採用の段の動き |
| --- | --- | --- |
| URL・通常(`full`) | analyze → adopt → export → transcribe → pack | `_step_adopt`(512 行)→ `POST /api/video/adopt-top` `{id, top}`(515 行)。`serve.py` `_adopt_top` → `store.py` `adopt_top`(756〜777 行) |
| URL・依頼(`request`・`request_auto`) | analyze → adopt → … | `_step_adopt_request`(491〜510 行)。区間 `run.ranges` を `pad_range` で前後に余白(495 行)→ `POST /api/video/request-marks` `{id, ranges, auto}`(500 行)。`store.py` `request_marks`(779〜831 行): 区間を採用の手動マーク(adoptedBy request)、残りを自動マークの点数順から `auto` 個採用(adoptedBy auto) |
| 動画ファイル(`file`・`file_auto`) | `file` は transcribe のみ・`file_auto` は transcribe → pack → deliver | **解析も採用もしない**。`_file_*`(892〜908 行)。区間の指定(ranges)は file 系では使われない(`run.py` の ranges は `REQUEST_URL_MODES` 内のみ = 156 行 推測ではなく grep 結果) |

- 書き出し: `_step_export`(541 行)は `status == "adopted"` のマークだけを書き出す(542 行)。`_export_body`(529 行)は設定 `review.*` を読む。
- 上位 N の数: `Run.top`(`top_arg` の既定 DEFAULT_TOP = 3。`autorun.py` の `start` 359 行で top を受ける)。request では `auto = max(0, top − len(ranges))`(496 行)。
- 友人の区間(`ranges`): 最大 10 個・1 つ 3600 秒まで(`spec.py` 18〜19 行)。`top` 以上の区間があれば自動は 0(`run.py` 156 行)。
- HTTP の呼び先: `studio` の `POST /api/video/adopt-top`・`POST /api/video/request-marks`(`autorun.py` 99 行 `STEP_TOOLS`)。
- 自動採用は学習の記録に入れない(`store.py` 756〜758 行。`adopt_top` も `request_marks` も feedback を書かない)。

## 3. `src/pipeline/spec.py` の adopt / hints

| 項目 | 既定 | 検査 | 実際に使われているか |
| --- | --- | --- | --- |
| `hints.ranges` | `[]` | `_ranges_ok`(234 行) | `run.py` は `Run(ranges=…)` で受けるだけ。`spec.merge` の結果は**本番コードから読まれていない**(下の注) |
| `hints.people` | `[]` | `_people_ok`(244 行) | 同上 |
| `adopt.top` | `DEFAULT_TOP` = 3 | `_top_ok`(265 行)・1〜30 | 未使用(run.py は `run.top` を使う) |
| `adopt.pad` | 2.0 | 0〜3600 | 未使用(`pad_range` は `RANGE_PAD` = 2.0 を直接使う) |
| `adopt.perHour` | 6 | 1〜30 | 未使用(prefs の値を使う) |
| `adopt.waitMin` | 5 | 1〜60 | 未使用(prefs の値を使う) |

- `spec.py` 129〜134 行(`DEFAULTS["adopt"]`)。`spec.py` 9〜10 行の注「今のコードはまだこの表を読まない」と一致(`grep` で `spec.merge`/`spec.DEFAULTS` を読むのは `src/pipeline/tests/test_spec.py` だけ)。
- 足りないもの: 「動画ファイルの自動採用」の節(件数・区間の扱い)、採用の方式(自動 / 候補を出して止める)の項目、F-5 の「上書きの採用・不採用」の項目。`hints.ranges` を file 系で使う決まりも無い。`adopt.count`(採用の上限)と `adopt.enabled` は無い(今は `top` が同じ役)。
- `spec.py` の `RANGE_MAX = 10`・`RANGE_MAX_SEC = 3600` は `spec` と `studio` の `MAX_REQUEST_RANGES` の二重管理(注釈どおり)。

## 4. 配信後の全自動(`src/pipeline/ingest/live_archive.py`)

- 候補の選び方: `pick_candidates`(320〜340 行)。候補 = スタジオのアーカイブのマークで src auto かつ status 空。点数の高い順に、録画の範囲(first〜last)へ切り詰め、録画の範囲に半分以上入ったものだけ。もう採用・書き出し済みの区間(`taken`)と重なるものは飛ばす。
- 採用の本体: `_after_adopt`(967〜1000 行)。`n` 本(録画の時間 × perHour、`per_hour()` は設定 `live.afterStreamPerHour`・既定 6・`live_archive.py` 821 行)を `self.adopt(body, hold="archive")` で 1 本ずつ頼む(998 行)。body は origin "archive"・after "auto"(996 行 `AFTER_FLOW = "auto"` 112 行)。
- 安全: 録画がまだ用意中・配信中なら待つ(`Later`)。`_after_adopt` は配信中の候補との比較(`compare`)を失敗しても続ける(975〜979 行)。
- 上限: `AUTO_MAX_PER_REC`(D-13)はこの経路では数えない(`live_detect.py` 33 行の注は「配信後の解析 archive は数えない」)。配信後の本数は `per_hour` で決まる。
- 決定の記録: 採用の結果は `_after_set`(state・jobs・picked)に残る。decisions.json は `live_detect` 側の記録。

## 5. 手動マーク・採用・不採用の記録(F-5 の「上書き」として読めるか)

- マークの形(`src/human/review/store.py` 153〜163 行): `status`("" / adopted / rejected / exported)・`src`(auto / collab / manual)・`adoptedBy`(auto / request。人が状態を変えたら外れる 182 行)・`auto0` / `auto0Orig`(機械の最初の区間)。
- 人の判定の記録: `store.py` 717〜741 行。status が adopted → feedback の `good`・rejected → `bad`・採用から外した → `unadopt`(741 行)・手動の追加 → `manual_add`(739 行)。feedback.jsonl に 1 行ずつ(`src/human/review/feedback.py`)。自動の採用(`adopt_top`・`request_marks`)は feedback を書かない。
- decisions.json(ライブ側)の item: `{n, id, state: adopted|dismissed|restore, origin: auto|manual, markId, jobId, at}`(`live_detect.py` 13 行・115〜116 行)。
- 読める点: マークの `adoptedBy` で「機械が採用・人が採用・人が不採用(rejected)」は区別できる。F-5 の「上書きの採用 − 上書きの不採用」は、`status` が adopted/rejected で `adoptedBy` が無いマーク(人の判断)と、decisions.json の `state` を読めば組める。**推測**: 「上書きの不採用」は現状 `rejected` マークとして残るが、自動の候補(status 空)を単に見送ったのか、人が rejected にしたのかは `adoptedBy`・`feedback` の `bad` 行で区別する必要がある。
- ライブ側の「見送り」は decisions.json の `dismissed`(画面の帯)で、スタジオのマークとは別の帳簿。二つの帳簿を F-5 でどう結ぶかは未決。

## 6. RS6 で自動採用を足すときに触るファイル(推測を含む)

| ファイル | 変えること |
| --- | --- |
| `src/pipeline/spec.py` | `adopt` 節に動画ファイル用・採用の方式・件数を足す(`SCHEMA`・`DEFAULTS`・`FIXED` の見直し)。`test_spec.py` の鍵の一致の検査 |
| `src/pipeline/run.py` | `MODE_STEPS["file"]`・`file_auto` に analyze/adopt を足すか決める。`_step_adopt`・`_step_adopt_request` の共通化。`Run` が `spec` の値を受ける口 |
| `src/home/autorun.py` | 動画ファイルの入口(`start_file` 447 行)で top・ranges を受け、`STEP_TOOLS`・`_step_adopt` の経路を通す |
| `src/studio/serve.py` / `src/human/review/store.py` | 動画ファイルのマークを採用する API(`adopt_top` 相当)を、ファイルの解析結果に対して使えるか確認 |
| `src/pipeline/ingest/live_archive.py` | 配信後の採用(`pick_candidates`・`_after_adopt`)を、ファイル用の共通の関数へ寄せるか判断 |
| `src/pipeline/analyze/live_detect.py` / `src/home/prefs.py` | 自動採用の既定(perHour・waitMin・AUTO_MAX_PER_REC)を spec の値と一つにする |
| `src/human/review/feedback.py` / `store.py` 717〜741 | F-5 の「上書き」の記録の形 |
| テスト | `src/pipeline/tests/test_spec.py`・`src/pipeline/tests/test_run.py`・`src/home/tests/test_autorun.py`・`src/pipeline/ingest/tests/test_live_archive.py`・`src/human/review/tests/test_studio.py`・`src/studio/tests/test_api.py` |
| 層の検査 | `dev/tests/test_layering.py`(import を変えたら) |

### 気づいた食い違い・リスク

1. `spec.DEFAULTS["adopt"]`(top 3・pad 2.0・perHour 6・waitMin 5)は本番で読まれていない。値は prefs・run.py・store.py に散っていて、変えると 3 か所以上を直す必要がある。
2. 動画ファイル(`file`・`file_auto`)は解析も採用もしない。自動採用を足すなら解析の段を入れることになり、友人の「軽く確認」の時間が増える。
3. `AUTO_MAX_PER_REC`(10)は配信中の自動だけに効き、配信後の archive 採用と URL の `auto` には効かない。上限の考え方が経路ごとに違う。
4. 自動採用(`adopt_top`・`request_marks`)は feedback を書かないので、F-5 の「上書き」の学習に入らない。これは仕様(人の判定ではない)だが、F-5 で「機械の採用を人が外した」を数えるなら記録が要る(`unadopt` は status が adopted→空のときだけ)。
5. 二つの帳簿(ライブの decisions.json とスタジオのマーク)の対応は、`markId` で結ぶ部分だけ。見送り(dismissed)はスタジオに残らない。
6. `pick_candidates`(archive)と `request_marks`(URL)と `adopt_top`(通常)で、「重なり」「半分以上」「点数順」の決まりがそれぞれ違う。RS6 で一つに寄せるなら、テストの期待値を先に固定する。
7. 上の 1〜6 は読んだ範囲での所見。行番号は grep と部分読みによる。動かして確かめてはいない。
