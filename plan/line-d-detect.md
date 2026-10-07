# 線 D 前倒し: 配信中の検出(L1〜L3)と配信中の自動マーク(M11)の実装計画(2026-10-07)
> 状態(2026-10-07 夜): **L1〜L3・M11 は実装済み**(ユーザー「障害がないなら最優先で試験したい」→ 同じ夜に。入口 0.43.0・スタジオ 0.23.0。検出 `live.detect` と自動採用 `live.autoAdopt` は試験中の機能の中のスイッチで既定オフ)。M8・M10・ワーカーの残り(同時 2 本・変わり目・遅れの短縮)と M9 を続けて実装中。次は起動し直し → 10-18/19 に検出オンで配信 1 本(L4')。実装の記録と仮決め (cb)〜(cj) は WORKLOG と `plan/decisions.md` の 3-7。
> 計画の経緯: 2026-10-07 にユーザー「L1〜L3 と M11 を早めにやりたい」で作った。設計の中身は `plan/line-d-live-clipping.md` の 0-10(案 A・子プロセス・入れ替え方式。**変えない**)と `plan/line-d-auto-pack.md` の段階 3・6。この文書は「早めるための順番・分け方・境目の約束・仮決め・日程」だけを持つ。
> 順番と進捗は `plan/index.html`(データ `plan/data.js`)。仮決めは `plan/decisions.md` の 3-7 (bg)〜(br)。コードの事実(関数名・行)は 2026-10-07 の調査(WORKLOG)に基づく。

## 1. 何を早めるか(以前の計画との違い)
| 観点 | 以前(10-06 の計画) | 今回(10-07 ユーザー指示) |
|---|---|---|
| 順番 | M7 の確認 → L0 → L1 →(採用の記録 10 本)C1・C2 → L2 → L3 → L4 → L5 → ユーザー決定 → M11〜M13。配信中の自動マークまで 5〜8 週間 | 今夜の M7 の試しと並行して **10-08 から L1 → L2 ∥ L3 → M11(既定オフ)**。週末に検出オンで配信 1 本(L4 の前倒し)→ 候補を見てユーザーが M11 をオンにするか決める。**2〜3 週間** |
| M11 の入口 | L5 の数字(配信数本 = 数週間)が出てから実装 | **実装は数字を待たない**(既定オフ)。オンにする判断だけユーザー(候補を 1〜2 本の配信で見てから)。L5 の比べる処理(0-10-6)は配信ごとに自動で記録し、数字は後から出る |
| L0 | L2 の前提 | 止める条件にしない。今夜の配信で 1 時間読めれば読む(目的は行の形 = `videoOffsetTimeMsec` が配信中も入るか)。チャットの数(5 分・64MB・起動し直しの間隔)は定数にして L4' のあとに決め直す |
| 並列 | 1 本ずつ | **2 本の線**(線 1 = 式 + ワーカー + 入口の API / 線 2 = スタジオの画面)。触るファイルが重ならない。境目は 3 の「候補の API の約束」を 10-08 に先に決め、線 2 は偽の応答で作る |
| 後ろへ | — | C1・C2(I-4a/b)・M8・M10・C3 は M11 のあと。**M9(確認の一覧)は M11 をオンにする前に要る**(自動のパックを捨てる所)ので、M11 の次に |

変えないこと: 0-10 の設計(案 A・子プロセス・入れ替え方式・1 時間 6 本・遅れ 30〜45 秒)・0-10-8 の決定・M11 の 5 分待ち・届けるは人の確認のあとだけ(M12 は含めない)・0-11(配信中の文字起こし)は含めない(D-11 は L3 のあとに決める)。
**既定はすべてオフ**: 検出(`live.detect.enabled`)も自動採用(`live.autoAdopt.enabled`)も試験中の機能の中のスイッチ。検出をオンにしても、自動採用がオフなら候補を出すだけ。

## 2. 工程(大きさは AI の時間。完了条件 = テストで確かめること)
| ID | やること | 触る所 | 大きさ | 完了条件 |
|---|---|---|---|---|
| **L1** 式を 1 つに | `analyze.py` の純粋関数(`smooth`・`median`・`local_baseline`・`robust_scale`・`audio_score`・`chat_z`・`shift_chat`・`estimate_lag`・`head_ramp`・`comment_score`・`pick_clips`・`snap_quiet`・`downsample`・定数 `SENS`・`CAP`・`LAG_*`)を **`src/ytt_core/excite.py` へ移すだけ**(式・加算の順・銀行丸め・`local_baseline` の点の作り方をそのまま)。足すもの: `local_baseline(x, back, fwd, step)`(既定は今と同じ 150/150)・`robust_scale(dev, floor, window)`(窓 = 直近 30 分)・1 秒ずつ足す **`Online`**(確定した秒の点数を返す。中の状態は窓の分だけ)・候補の帳簿 **`PeakBook`**(確定の規則 0-10-3 の 5・1 時間の枠と入れ替え 0-10-3 の 6・採用と見送りの除外。純粋・JSON にできる)・`parse_chat` の 1 件の重み(`warm_re`・スパチャ +4)を `message_weight` に切り出す。`analyze.py` は excite を読んで同じ名前を再公開(テストと e2e の呼び出しを壊さない)。`dev/eval_marks.py` の写し(`PART_ON`・`DEFAULT_PRE`)も excite から読む | `src/ytt_core/excite.py`(新)・`src/ytt_core/__init__.py`(一覧に 1 行)・`src/studio/analyze.py`・`dev/eval_marks.py`・`src/ytt_core/tests/test_excite.py`(新)・`src/studio/tests/test_analyze.py` | 6〜8 時間 | ① **golden**: 移す前に、合成の入力(`e2e_analyze` の wav + チャット JSONL・seed 固定)で候補・series・lagUsed を JSON に残し(リポジトリに入れる)、移した後と**完全一致**。手元の本物のアーカイブ 9 本(`studio/archive/*.json.gz` の full・band・chat.act から再計算)でも移す前後を比べる(個人データなのでコミットしない)② `Online(back=270, fwd=30, window=1800)` と、同じ値を渡した一括の関数が合成の系列で完全一致 ③ `PeakBook` の規則のテスト(確定・枠・入れ替え・採用は数えない・見送りは外す・JSON の往復)④ test_analyze・e2e_analyze・test_ytt_core・`dev/lint.py` 0 件(dup-block に当たらないよう写しを残さない。`chat_score` はテストだけなので `# lint: keep`)⑤ 3 の API の約束をこの文書で確定 |
| **L2** ワーカーと入口 | ワーカー `src/home/live_excite_worker.py`(入口の子プロセス・常駐・録画中の全部を受け持つ。0-10-4)。中身: 録画元の `/live/list` を 10 秒ごと → 録画ごとに `status?since=N` で新しいセグメント → `/live/<id>/<uri>` で本体 → **ffmpeg 1 回で 3 本(約 12 秒)**(今の `audio_levels` と同じ `astats` の 1 秒 RMS。`asplit` で全帯域と 2kHz 超を同時に)→ PDT で 1 秒の箱 → `Online` → `PeakBook`。チャット: yt-dlp の `--skip-download --write-subs --sub-langs live_chat` を配信 1 本につき 1 つ、伸びるファイルを末尾から読む(0-10-5 の止まったら起動し直し・64MB で回す)。遅れの推定(0-10-3 の 4)。**1 分ごとに状態をディスクへ**(3 のファイル)。512MB で自分を終える。入口側(`src/home/live_detect.py`。新): 起動・心拍の見張り・起動し直し(30 秒の見回りの中)・設定 `live.detect`・候補の API(3)・人の採用と見送り(`decisions.json`)・「調子」(遅れ・起動し直しの数・チャットの状態)・失敗の文(`live_failures` に kind "detect")・ホームの試験中の機能のスイッチ。配信が終わったら飛ばした区間を測り直し、P4 のあとアーカイブの解析と比べて `live_feedback.jsonl` に記録(0-10-6 = L5 の材料。人の手は要らない) | `src/home/live_excite_worker.py`(新)・`src/home/live_detect.py`(新。`live.py` を 1,000 行超にしない)・`live.py`(起動の呼び出しと API の振り分けだけ)・`prefs.py`・`health.py`・`live_failures.py`・`portal.html`・`portal.js`・`src/home/tests/test_live_detect.py`(新)・`test_live.py`(FakeRecorder の口)・`src/home/tests/fake_ytdlp_chat.py`(新。偽の yt-dlp) | 2〜3 日 | ① 偽の録画元(`test_live.py` の `FakeRecorder` に合成の `/segments`・`.ts`・pdt を足す)+ **注入した時計**で 12 時間を早送り(音の値は作り置きで ffmpeg を飛ばす): メモリが増えない・途中で 3 回止めても同じ候補 ② 欠け・チャットなし・チャットが 5 分止まる → 起動し直し・64MB で回す・403/429 の間隔 ③ 本物の ffmpeg の道は `hls_fixture` の 1 秒セグメントで数分 ④ `GET /live/api/peaks` の since 差分と `POST adopt/dismiss/restore`(adopt は `Live.adopt` を通り、`existing` の二重が無害)⑤ 「調子」に遅れ・起動し直しの数・チャットの状態 ⑥ 入口のプロセスで numpy を import しない(ワーカーも numpy は使わない。純粋な Python で足りる = 0-10-2)⑦ 録画の部品の版は上げない(API を足さない。足すなら `VERSION` と入口の見回りの起動し直し) |
| **L3** スタジオの帯(線 2) | LIVE の帯(`liveBarHTML` の `#rvArch` と `#rvAfterStream` の間)に静的な行を足す: 「候補 n 件(この 1 時間 x/6)・遅れ・チャット」の 1 行 + 候補の一覧(`#rvPeakList`: 時刻・点数・理由・[再生][採用][見送り]・「控えも見る」)。**作り直さず差分で更新**(`liveSet` と同じ。`test_review.cjs` の「3 秒の見回りで作り直さない」に合わせる)。入れ替えで外れた行は薄くして数秒で消す。再生中・マウスが乗っている行は外さない(0-10-3 の 6)。[再生] = `seek(max(0, start − 5))` + 区間の終わりで止める(`previewClip` と同じ)。[採用] = `POST ../live/api/peaks {op: adopt}` → 応答後に **`syncFromServer()`**(③ を開いたままだとサーバー側のマークは自動では出ないため)。時間軸に候補の印(`.rv-seg cand`。採用したら今までの `auto` の印に)。グラフは peaks の `series`(600 点)があるときだけ描く。設定: ⚙「ライブの録画」とホームの試験中の機能に「配信中の候補」(オン/オフ・感度・1 時間の本数 = `UIKit.prefs.patch('live', {detect: …})`)。帯に M11 の状態(「自動採用 オン(5 分待ち)」)。キー: `p` 次の候補を再生・`z` いまの候補を採用(両プリセット・共通再生・禁止キーのどれにも無い字。A4 で見直す)。見回り: `pollLiveStatus`(3 秒)の中で `since` 差分だけ取る(検出がオンの録画のときだけ) | `src/studio/review.js`・`review.css`・`settings.js`・`index.html`・`core.js`(`APP_VERSION`)・`serve.py`(`SERVER_VERSION`)・`README.txt`・`src/studio/tests/test_review.cjs`・`src/home/tests/e2e_live_studio.py`(候補のシーン)| 8〜12 時間 | ① `test_review.cjs` に候補の整形(差分の当て方・1 時間の枠の表示)の純粋関数 ② `e2e_live_studio.py` に「候補」のシーン(入口の `live/excite/<rc>/<rec>/peaks.json` を**偽で置く** → 帯に出る → [再生] → [採用] → マークが一覧に出て書き出しが始まる → [見送り] → 控え)③ `py -3.10 dev/ui_audit.py all --demo` Must 0(28px・名前・フォーカス・固定の色なし・インラインなし)④ e2e_keymap(p・z が割り当て可能で衝突しない)⑤ スタジオの版を上げる(README に記録) |
| **M11** 自動で採用 | スイッチ `live.autoAdopt {enabled: false, waitMin: 5}`。入口の見回り(30 秒)で、**確定から waitMin たって枠に残っている候補**(state frame・見送りでない・録画が active)を `Live.adopt({origin: "auto", after: "auto"})`。採用した候補は**枠に数えたまま固定**(入れ替えで外れない → M13 の「書き出し済みが外れる」はこの作りでは起きない。「控え」の札だけ残す)。スタジオ不通(502)は次の見回りで再試行(1 候補 5 回まで。超えたら失敗の文)。`decisions.json` に自動採用の記録(ワーカーが読んで枠に反映)。帯に「自動採用 オン(5 分待ち)」とホームのスイッチ。1 時間の上限はそのまま枠が持つ | `src/home/live_detect.py`・`prefs.py`・`portal.html`・`portal.js`・`src/studio/review.js`(表示だけ)・`src/home/tests/test_live_detect.py`・`e2e_live_studio.py` | 4〜6 時間 | 偽の時計で: 確定 → 5 分後に 1 回だけ採用(origin auto・after auto・`live_feedback.jsonl` に human false)・見送った候補は採用しない・5 分以内に入れ替えで外れた候補は採用しない・採用済みは入れ替えで外れない・スタジオ不通 → 再試行 → 上限で失敗の文。e2e: スイッチ → 候補 → src auto のマークと書き出し → 「調子」に失敗なし |
| **L4'** 本物で 1 本 | 検出オン(自動採用オフ)で本物の配信 1 本(ユーザー。U4 の 3 時間と兼ねる)。見るもの: 候補の当たりの印象・遅れ(帯)・CPU・チャットの起動し直しの数(「調子」)・録画と書き出しと文字起こしを同時に | — | ユーザー 30 分 + 配信 1 本。AI 結果の読み 2 時間 | 0-10-5 の数(5 分・64MB・間隔)を決め直す。**ユーザーが M11 をオンにするか決める**。配信が終わったら 0-10-6 の比較が自動で記録される(L5 の 1 本目) |

L0(今夜): 配信の URL をもらったら、AI が yt-dlp の live_chat を 1 時間ほど読む(行の形・書き出しの遅れ・黙って止まるか・ファイルの増え方)。読めなくても L2 は止めない(行の形の違いは `message_weight` の入口 1 か所で吸収する)。

## 3. 候補の API の約束(線 1 と線 2 の境目。10-08 に確定。変えるときは WORKLOG で両方に告知)
設定(`prefs.py` の `live` 節。patch は `api/ytt/prefs`): `live.detect {enabled: false, sens: "normal"(high|normal|low), perHour: 6(1〜30)}` / `live.autoAdopt {enabled: false, waitMin: 5(1〜60)}`。候補の長さ・前の割合は当面スタジオの解析の設定(45 秒・0.65)を使う(仮決め (bn))。

```
GET  /live/api/peaks?recorder=&recording=&since=<seq>     since 省略 = 全部 + series
  → { ok, seq, enabled,
      worker: { running, behindSec, chat: "ok"|"none"|"restarting"|"off", restarts, memMB, message },
      hour: { perHour, counts: { "<h>": n } },                 h = 録画の頭からの 1 時間ずつ
      peaks: [peak…](since 省略のとき)  /  changes: [{ seq, id, state }](since あり = 変わった候補だけ。入れ替え・採用・見送りも「変更」)
      series?: { step, total, audio, chat }(600 点。since 省略のときだけ) }
peak = { id, start, end, peak, score, parts, reasons, confirmedAt, hour,
         state: "frame"(枠)|"bench"(控え)|"adopted"|"dismissed", endPending, origin?: "manual"|"auto", markId?, jobId? }
         start・end・peak は録画の頭からの秒(スタジオのマークと同じ基準)
POST /live/api/peaks { op: "adopt"|"dismiss"|"restore", recorder, recording, id }
  adopt   → Live.adopt(origin manual)の { job, video, mark, existing } + { peak }
  dismiss / restore → { ok, peak }
```
ファイル(入口の作業データ `live/excite/<録画元>/<録画>/`。録画を消すとき一緒に消す):
| ファイル | 書き手 | 中身 |
|---|---|---|
| `state.json` | ワーカー | 最後に測ったセグメント・遅れ・山の途中・チャットの読んだ位置・窓(fsync してから入れ替え。起き直したらここから続ける) |
| `series.jsonl` | ワーカー | 1 分 1 行(音 2・チャット 1 の 1 秒の値。画面の 600 点はここから) |
| `peaks.json` | ワーカー | 候補の正本(`PeakBook` の JSON) |
| `decisions.json` | 入口 | 人の採用・見送り・自動採用の記録(ワーカーが読んで枠に反映) |
| `worker.json` | ワーカー | 心拍(30 秒ごと: pid・at・behindSec・memMB)。入口は 2 分止まったら、またはプロセスが終わっていたら起動し直す |

ワーカーと入口の会話は**ファイルと 30 秒の見回りだけ**(stdin/stdout の常駐プロトコルは作らない)。書き手は 1 ファイルに 1 つ。

## 4. 仮決め(確認してほしい。`plan/decisions.md` の 3-7)
- (bg) **M11 を L5 の前に実装する**(既定オフ)。オンにするのは、検出オンの配信 1〜2 本で候補を見てからのユーザーの決定。L5 の数字は配信ごとに自動で貯まる
- (bh) L0 を止める条件にしない。今夜 1 時間読めれば読む。チャットの数(5 分・64MB・間隔)は定数にして L4' のあとに決め直す
- (bi) 2 本の線で並列(線 1 = excite + ワーカー + 入口 / 線 2 = スタジオの画面)。3 の API の約束を 10-08 に先に決め、線 2 は偽の `peaks.json` で作る。同じ PC の 1 つのセッションでサブエージェントに分ける(クラウドと PC に分けると合流で衝突する = 10-07 の経験)
- (bj) 候補の正本はワーカーの `peaks.json`、人の採用・見送り・自動採用は入口の `decisions.json`。入口が合わせて返す(1 つのファイルに 2 つの書き手を作らない)
- (bk) ワーカーと入口はファイル + 30 秒の見回りで話す。常駐の stdin/stdout プロトコルは作らない(起動し直しに強い・既存の `spawn` の流儀のまま)
- (bl) 自動で採用した候補は枠に数えたまま固定(入れ替えで外れない)。人が採用した分は数えない(10-06 決定のまま)。→ M13 の「書き出し済みが入れ替えで外れる」は起きないので、「控え」の札だけ
- (bm) 音の測り方はアーカイブの解析と同じ ffmpeg の `astats`(1 秒の RMS・2kHz 超は highpass)を `asplit` で 1 回に。録画(HLS の AAC)と YouTube のアーカイブ(`-f ba`)の音の作りの差は残る(L5 で見る)
- (bn) 候補の長さと前の割合は当面スタジオの解析の設定(45 秒・0.65・上限 120)。M10(人の記録から。6 個では少ない)は後ろ
- (bo) 検出・自動採用の既定はオフ(試験中の機能の中のスイッチ 2 つ)。検出をオンにしても自動採用がオフなら候補を出すだけ
- (bp) L4 は「検出オン(自動採用オフ)で本物の配信 1 本」に縮めて前倒し(U4 の 3 時間と兼ねる)。長時間の安定(12 時間)は偽の配信の早送りのテストと、普段の使用で見る
- (bq) 含めない: 0-11(配信中の文字起こし)・M12(届ける)・M9(確認の一覧)。ただし **M9 は M11 をオンにする前に要る**ので M11 の次に作る(自動のパックを捨てる・誤検出の記録)
- (br) 入口側の新しいコードは `src/home/live_detect.py` に置く(`live.py` が 1,057 行で、見回り・中継・adopt を持つ。これ以上は分ける)。キーは p(次の候補)・z(採用)。A4(段 15)で見直す

## 5. 日程(AI は 1 日 4〜6 時間分。並列で短くする)
| 日 | AI | ユーザー | 節目 |
|---|---|---|---|
| 10-07(火)夜 | 計画・調査(済み)・L0(URL をもらえたら) | **今夜の配信で M7**(autoAfterStream はオン済み) | — |
| 10-08(水) | L1(式を移す・golden・Online・帳簿)+ 3 の API の確定 | M7 の結果(パックの本数・失敗)を一言 | golden 完全一致 |
| 10-09〜10-11(木〜土) | 線 1: L2(ワーカー → 入口 → API → 調子)/ 線 2: L3(帯・一覧・採用・設定。偽の peaks.json) | — | 12 時間の早送りテスト |
| 10-12(日) | 合流: e2e_live_studio の候補のシーン・ui_audit・lint・全体のテスト | — | 候補 → 採用 → 書き出しが通る |
| 10-13(月) | M11(スイッチ・5 分待ち・固定・再試行)+ 帯とホームの表示 | — | 偽の時計で 1 回だけ採用 |
| 10-14〜10-15(火〜水) | 予備(L0 の反映・偽の配信の直し・README・HANDOVER)。余れば M9 に着手 | — | **M11 まで入った版で起動し直し** |
| 10-18/19(土日) | 結果の読み(遅れ・CPU・候補の当たり・0-10-6 の比較の記録) | **検出オン(自動採用オフ)で配信 1 本**(L4') | 0-10-5 の数を決め直す |
| 10-20 ごろ | M9(確認の一覧)→ そのあと M8・M10・C1〜C3 | **M11 をオンにするか決める** | 配信中の自動マーク(決定次第) |

遅れたときは 線 2(L3)を先に細く通し(一覧と採用だけ)、グラフ・キー・控えの表示は後回しにする。

## 6. リスク
| リスク | 備え |
|---|---|
| 式を移して結果が変わる(float の加算順・銀行丸め・`local_baseline` の点の重なり) | 移す**前**に golden を作る。式は 1 文字も変えずに移し、back/fwd・window は既定で今と同じ値 |
| yt-dlp の配信中の live_chat の形が違う(`videoOffsetTimeMsec` が無い・`timestampUsec` だけ)/ 黙って止まる | L0 で見る。時刻の変換は 1 か所(`message_weight` の手前)。止まったら音だけで続ける(0-10-5) |
| 録画の音(HLS)とアーカイブの音(`-f ba`)で dB の値が違い、候補がずれる | 相対の式(ふだんとの差・MAD)なので小さい見込み。L5 の比較で測る |
| ワーカーが重い処理と取り合って遅れる | 優先度「通常より下」・ffmpeg は短い 1 回ずつ・遅れたら 60 秒ずつまとめ、10 分超で古い所を飛ばす(0-10-5) |
| review.js(3,242 行)の帯の変更で退行 | 差分更新の流儀を守る・`test_review.cjs`・e2e_live_studio の既存シーン・ui_audit Must 0 |
| 入口・ワーカーの起動し直し | 1 分ごとの `state.json`・心拍・入口の見回りで起動し直す。テストで 3 回止めて同じ候補 |
| 自動採用の誤検出が書き出し・文字起こしに流れる | 既定オフ・5 分待ち・1 時間 6 本の枠・パックのあとに人が見る(M9)。届けるは人のあとだけ |
| 2 つの線の衝突 | 触るファイルを分ける(線 1 = ytt_core・home / 線 2 = studio)。入口の API は線 1。同じ PC の 1 セッション |

## 7. あなたにしてもらうこと
1. 今夜: 配信の URL を伝える(L0 用。M7 は設定済み)。配信のあと、パックができたか・「調子」に失敗が出たかを一言
2. 10-15 ごろ: 「すべて終了」→ start.bat で起動し直し(M11 まで入った版)
3. 10-18/19: 試験中の機能で「配信中の候補」をオンにして配信 1 本。候補の当たりの印象(多い・少ない・ずれ)を一言
4. そのあと: M11(自動採用)をオンにするか決める。4 の仮決めで違うものがあれば記号で
