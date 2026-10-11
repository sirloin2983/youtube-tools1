状態(2026-10-11): 作り方の計画(AI が決めた。仮)

# V1「確かめる」(確認作業を 1 か所にまとめる画面)の作り方

関連: 何を作るか `docs/design/briefs/rs8-cases/DESIGN_BRIEF.md` 2-3・3(1・2・11)・見本 `briefs/rs8-cases/mock/index.html` の「3. 確かめる」・進め方 `plan/rs8-cases-ui.md`「V1 の前に決めたこと」・`plan/improvements.md` 13・`plan/decisions.md` 3-27 (fe)・案件の画面の作り方 `docs/design/rs8-cases-build.md`(殻 `src/app/ui/cases/cases.js` の `Panel` の口)・② の口 `docs/spec/pipeline.md` 2.9・目標の値 `src/eval/drill/accuracy.py` の `GOALS`。
この文書は「どう作るか」だけ。コードは書いていない。測る道具の記録の形を直に確かめられなかった所は「確かめる」と書いた(実装の V0 で読んで直す)。

## 0. 要約(推奨)
| 問い | 推奨 |
| --- | --- |
| 1 置き場所・URL | 入口の直下の 1 枚 **`/check`**(`src/app/ui/check/`。`/cases` と同じ配り方・同じ CSP)。ホームの [始める] → `/check`・案件の頭の「確かめると効く物 n 件」→ `/check?c=<案件 id>`(その案件に絞る。終わったら戻る) |
| 2 待ち行列の層 | 候補を集めて並べる・「あと何本」を数えるのは **⑤ `src/eval/check/`**(目標の値と「評価用」の判定がある層。① ③ ④ を読んでよい)。口は入口 `GET /api/check/next`・`POST /api/check/answer`。② は通らない(進み具合でなくデータの読み = rs8-flow-api 3 節と同じ理由) |
| 3 答えの記録と反映 | 新しい記録 1 本 **`app\check\answers.jsonl`**(カード 1 枚 1 行。Z は `undo` の行)+ **実物への反映は今の ③ の口をサーバー側 `human/check/apply.py` が呼ぶ**(届ける・採用・文書の commit)。測る道具が今読んでいる記録(feedback・文書の行・.alt・voices)は反映の副産物として今の形のまま増える = 道具はそのまま読める。新しく読むのは行の時刻のカードだけ(`eval_timing --check`) |
| 4 部品の共用 | **共用するのは「口・見た目・キー」**(媒体の URL・比較欄 `alt-pair`・`UIKit.keys.playback`・話者の色)。DOM の部品はカード用の**軽い再生部品 1 つ** `check/player.js`(video + 範囲 + 字幕 1 行 + 波形)を新しく作り、案件のパネル(編集の全画面・review.js)を丸ごと mount しない(重い・遅い・id が衝突) |
| 5 声・波形 | 声の覚え直しは answer の反映の中で「その人の確かめた行が 30 秒を超えたら」`flow/diar.merge_voice`(今の「前の声と長さで重みを付けて混ぜる」。`learnedFrom` の記録も既にある)を呼ぶ。波形は**今ある `GET /transcribe/api/peaks?id=`**(編集の 2 カットが使う 0〜255 の並び)を使う = 新しい API は作らない |
| 6 段 | V0 ⑤ の待ち行列 + API ∥ V1 画面の殻 → V2a 価値 ∥ V2b 読み ∥ V2c 声 ∥ V2d 時刻(worktree 4 本)→ V3 ホーム・案件のつなぎ・道具 → V4 締め。e2e は **`e2e_check.py` 1 本** + `e2e_portal` の直し。1.5〜2.5 日 |
| 7 ユーザーに聞く物 | 4 つ(8 節): 部品の共用の意味・[送る] は 1 枚遅れで確定・「続けて確認」を消す・時刻のカードの答えが実際に時刻を動かすか |

## 1. 置き場所・URL・入り方
| 項目 | 決めたこと | 捨てた案 |
| --- | --- | --- |
| フォルダ | `src/app/ui/check/`(`index.html`・`check.css`・`check.js`(殻)・`player.js`・`cards/value.js`・`cards/read.js`・`cards/voice.js`・`cards/time.js`) | `src/eval/drill/` の下(improvements 13 の「置き場所は ④」は RS6 より前の話。画面は app の層・数えるのは ⑤) |
| URL | **`/check`**。入口の `STATIC` に `/check`・`/check.js`・`/check.css`・`/check-cards/<名前>.js`・`/check-player.js`(`/check/` で始めない = `/cases` と同じ理由)。`NAV_PAGES`・`PAGE_CSP`(`/cases` と同じ。候補のままのカードが YouTube の埋め込みを使う)・`appwindow.PORTAL_PAGES` に足す | `/cases#check`(殻が案件 1 つに縛られる。案件をまたぐ待ち行列と合わない)/ ホームの引き出し(今の「続けて確認」の形。4 種類のカードと帯・10 件のまとめが引き出しには収まらない) |
| 引数 | `?c=<案件 id>`(その案件の物だけ)・`?kind=value|read|voice|time`(この種類だけ。ホームの「今いちばん効く確認」から)・`?back=cases`(終わったら案件へ戻るボタンを出す)。根のパスは出さない | — |
| ホームの [始める] | `#checkStart` を `href="check"` の `<a class="btn primary">` に(今の disabled と `CHECK_WHY` を消す)。`#checkNow` の「今いちばん効く確認」は `/api/check/next?n=0`(数だけ)から出す = `/api/accuracy` の goals と同じ順の規則で ⑤ が選ぶ(画面の `pickCheck` を消してサーバーへ) | — |
| 案件の画面 | `cases.js` の頭(`#csHint` の横)に「確かめると効く物 n 件」= `GET /api/check/next?c=<id>&n=0` の `total`。押すと `/check?c=<id>&back=cases`。15 秒の問い合わせに合わせて読む(2 秒ではない) | 案件の画面の中にカードを出す(殻の右の欄はパネル 1 つ・タブの体系と合わない) |
| 今の「続けて確認」(`#rvDrawer`・A5) | V1 の「切り抜く価値があるか(自動で採った)」のカードがそのもの。**V3 で引き出しとボタンを消し**、`#autoReview` の場所に「確かめる n 本」→ `/check?kind=value` を置く(`e2e_portal` の A5 の場面を `e2e_check` へ) | 残す(同じ物が 2 か所) |
| appnav | 「ホーム / 案件 / 確かめる / 設定」(`UIKit.appnav` の表と A-28 の検査) | — |

## 2. 待ち行列(どの層・出どころ・API・数え方)
### 2-1 層
- **数える・並べる = ⑤ `src/eval/check/`**(新。`queue.py` = 純粋(候補の一覧 → 順と「あと何本」。ファイルを読まない・テストしやすい)/ `sources.py` = 出どころごとに候補を集める(読むだけ)/ `goals.py` = `accuracy.GOALS` に足す 2 つ(後処理の札 30 行・行の時刻 N 行)と「種類 → 目標」の対応)。理由: 「目標まであと少し」は ⑤ の `GOALS` と測る道具の数え方そのもの・「評価用からは出さない」は ⑤ の `settings.in_eval_dir`/文書の `evalSet` の判定・⑤ は ① ③ ④ を読んでよい(`dev/layer_map.py` の ALLOWED)。
- **反映 = ③ `src/human/check/apply.py`**(新。カードの答え → 今の ③ の関数を呼ぶ + 記録 1 行)。③ は ① を直に読まないので、波形・声の特徴は ② `flow/tx`・`flow/diar` を通す。
- **② には何も足さない**(進み具合でなくデータの読みと人の操作。rs8-flow-api 3 節「② を通さない」と同じ)。例外は ① の道具を呼ぶ動詞 2 つ(波形・声の特徴は既に `flow/diar` にある見込み = 確かめる)。
- **入口 `src/app/server.py`** は口 2 つを配線するだけ(`GET_ROUTES`・`POST_ROUTES`)。
- 捨てた案: ③ `human/proof` に待ち行列(文書の側しか見えない・案件の候補とパック・採用の記録は ④)/ ④ `manage/cases` に(案件の一覧は持つが目標・評価用の判定は ⑤ の物。cases.py がさらに太る)/ 画面の JS で数える(4 つの API を画面が叩く = 画面が ③④ の形を全部知る)。

### 2-2 カードの種類ごとの出どころ(読むだけ)
| 種類 | 出どころ(sources.py) | 候補にする条件 | 自信・順の鍵 |
| --- | --- | --- | --- |
| value 自動で採った | ④ `cases` の `clips[].auto` で `review.deliveredAt` 無し・`review.pending` 無し(今の `rvItems()` と同じ) | 文書がある(再生できる)・非表示でない | 新しい配信から・配信の中は時刻の順 |
| value 候補のまま | スタジオの `data.json` の候補(`status` が `""` = 未決。自動が採らなかった物も)で書き出していない物(読みは `ytt/studiodata`) | 配信が YouTube(埋め込める)・評価用でない・`kind live` でない(feedback に残らない) | 点数の高い順(自動の採用の線の近くから = 取りこぼしを数える)。**「70 点」はコードに無い**(`eval_marks` の良い / 悪いは人の event と `status` だけ)= カードの答えそのものが 70 点の判定 |
| read 後処理 | 文書の行の `fill = {from, by}`(後処理が直した行。`by` = sense-voice / name / llm)で `proofed` でない物。2 択 = 今の `text` と `fill.from`(認識のまま) | 評価用でない・`fold` して違う | 新しい文書から |
| read 別のエンジン / YouTube の字幕 | `GET /api/suggest?id=` と同じ `alt_diffs` / `ytcap_diffs` の候補 `{seg, i, wrong, right, tier}`(`learn-feedback.json` の `dismissed` に無い物) | 同上(校正済みの行には出ない = 今の規則) | 違いが小さい物から(1〜3 文字 = 迷う物) |
| voice | `.diar.json` の `latest.rows[行id]`(`speaker`・`ratio`・`weak`・`mixed`)と `latest.voices.speakers[話者]`(`score`・`secondScore`・`reason`)。**自信は話者ごと**(行ごとの点は無い)= 行の `weak`・`ratio` と話者の `score − secondScore` を合わせて並べる。1 秒以上・`mixed` 無し | 評価用でない・answers.jsonl で未判定・`noSub` でない | 自信の低い順(`reason` = below_match / margin の話者 → `weak` の行 → 声の無い人) |
| time | 文字が決まった行(`proofed` か read のカードで決めた行)で answers.jsonl に判定が無い物 | 評価用でない | 新しい文書から。単語の印は `POST /api/retime`(読むだけ)の `edges` を使う(`.words` の GET は無い = 作らない) |

- 下調べで分かった事実(10-11。Sonnet 2 体の読み): `eval_fill`・`eval_timing` は `accuracy.AREAS` に無い(手で流す道具 = 入口の「調子」に出ない)→ V0 で AREAS に足す。評価用の見分けは文書の `evalSet is True`(ドリルの済みは `evalReviewed`。別のファイルは無い)。`learn-feedback.json` の `alt`/`yt` は `{acc, rej}` だけで時刻が無い。「人が確かめた話者」は `eval_speakers` が行の `speaker` と diar の差から推測する作り = 「合っている」と答えた事実は今の形に残らない → answers.jsonl が持つ。

### 2-3 API
```
GET  /api/check/next?c=<案件 id>&kind=<種類>&n=<枚数。既定 10。0 = 数だけ>&skip=<id,…>
 → {rev, cards: [{id, kind, source, case: {id, title}, target: {videoId, markId, docId, row}, media: {url, start, end, pad},
                 text, guess, options, score, note}],
    counts: {today, perKind: {value: n, …}}, goal: {kind, label, left, target, unit, opens}, total}
POST /api/check/answer {card: <id>, kind, source, target, answer: {…}, ms}   → {ok, applied: {…}, next: <省いた次の 1 枚か null>}
POST /api/check/answer {undo: <answer id>}                                     → {ok, reverted: {…}}
POST /api/check/skip   {card: <id>}                                             → {ok}(その日の間だけ後ろへ。app\check\skip.json に日付つき)
```
- `id` = `<kind>:<出どころ>:<対象の鍵>`(例 `voice:diar:<docId>#<row>`)。同じ対象を 2 回出さない鍵。
- **順の規則(`queue.order`)**: (1) 種類ごとに「あと / 目標」を計算(`goals.py`。届いた種類は後ろ)→ 小さい種類から (2) 種類の中は 2-2 の鍵 (3) 「軽い物」が同率なら value → read → voice → time(押す数が少ない順)。`?c=` のときは案件で絞ってから同じ規則。
- **「あと何本で何が決まるか」の数え方**: 種類 → `GOALS` の対応 = value → `marks`(判定のある配信 10 本。配信の単位で数える = 1 枚で減らない所は「この配信の判定 n 本目」と出す)/ read 後処理 → 新 `fill`(判定した行 30 = `eval_fill` の FEW_ROWS)/ read 別 → `alt`(100 件)/ voice → `speakers`(200 行)/ time → 新 `timing`(行 100。仮)。数字は answers.jsonl と今の記録の両方から(今の記録 = 画面の外で付いた判定も数える。`accuracy.py` の `goals_of` に `check` の集計を混ぜる)。
- 合言葉・Host / Origin は今の書き込み系の口と同じ。`n` は 1〜50。知らない `kind` は 400。

## 3. 答えの記録と反映(Z で戻す)
### 3-1 記録 = 新しく 1 本 + 今の記録はそのまま増える
- **`%LOCALAPPDATA%\youtube-tools\app\check\answers.jsonl`**(入口の持ち物。`accuracy-state.json` と同じ場所。バックアップの「作り直せない物」に足す)。1 行 = `{id, at, kind, source, case, target, guess, answer, ms, undo(戻した answer の id か無し), applied: {何を変えたか = 文書の版・採用・届けるのジョブ id}}`。追記だけ(`fsio.append_line`)。
- なぜ新しく: 4 種類を 1 つの時系列で見たい(「今日 n 件」・答える前の予想と答え = 当たりの推移)・測る道具の記録は出どころごとに形が違う。**今の記録に書くのは反映の副産物として**(下の表)。= 「出どころで分けて残す」(brief 2-3)と「道具はそのまま読める」(3-1)の両方。
- 捨てた案: 今の記録だけに書く(時刻のカードに置き場所が無い・「今日 n 件」が数えられない)/ 文書の中に書く(文書は ① の機械 + 人の層。確認の履歴を混ぜない)。

### 3-2 反映(`human/check/apply.py`。カード 1 枚 = 関数 1 つ)
| 種類 | 答え | 反映(今の口・サーバー側で呼ぶ) | 今の記録に増える物(道具) | Z |
| --- | --- | --- | --- | --- |
| value 自動で採った | 送る / 要らない | `cases.auto_review` の `deliver` / `discard`(= `/api/cases/auto` の中身。届けるは ③ `deliveries`・feedback 1 行) | `feedback.jsonl`(`eval_marks`) | **1 枚遅れで確定**(3-3)。確定前なら記録の取り消しだけ |
| value 候補のまま | 採用 / 不採用 | `Store.put_video`(マークの `status` を adopted / rejected に。feedback の good / bad はここが書く)。**書き出しは別の呼び出し**(`POST /studio/api/export {id, markIds}`。exporter は 1 度に 1 本 = 409 busy)→ apply は採用のあと ② の封筒で書き出しを頼む(`flow/run` の export の段 = 待ち行列に入る。確かめる: 封筒の kind)。できなければ V2a は「採用だけ」にして書き出しは案件の画面で | `feedback.jsonl`・`data.json`(`eval_marks`) | `put_video` で `""` に戻す(event unadopt = retract)。書き出しが待ちなら ② cancel |
| read 後処理 | 1 / 2 / 打つ | `store.commit(why='check:read')` で行の `text` を `fill.from` と入れ替え(2 = 認識のまま なら `fill` を消し `flag` の「別の読みで埋めた…」を外す = 今の `unfill` と同じ)。`proofed` は付けない・時刻は触らない | 文書の行の `fill`・`flag`(`eval_fill` の 戻した / 残した) | 逆の commit(前の `text`・`fill`・`flag`) |
| read 別 / YT | 1 / 2 / 打つ | 行の `text` の `wrong` → `right` の置換 + `store.commit(why='check:read')`・`learn.record_feedback({tid, action, items:[{seg, wrong, right, tier}]})`(= `POST /api/suggest/feedback` の中身。`alt`/`yt` の acc / rej と `dismissed`) | `learn-feedback.json`(`eval_alt` の採用率)・文書の行(`eval_alt` の当たり) | 逆の commit + `dismissed` から外す(record_feedback に取り消しの枝を 1 つ) |
| voice | 名前 / その他 / 混ざり | `store.commit(why='check:voice')` で行の `speaker`(名前は `speakers[]` に無ければ足す。その他 = 組み込み `other`・混ざり = 行の印 `MIXED_FLAG` + タグ overlap)。名前のときだけ覚える材料に(1 秒以上・`mixed` 無し・評価用でない)。**`voice_learn_plan` は `proofed` の行が前提**なので、カードの行は `proofed` にせず `rows=` で明示して渡す(引数 1 つ足す) | 文書の行(`eval_speakers` は評価用のみ = 変わらない)・`voices/<emb>.json`(`learnedFrom`) | 逆の commit。覚え直しは 30 秒の山から外して次に覚え直す |
| time | ちょうどいい / 頭 / 末 / 両方(+ ← → の量) | 動かした量があれば `store.commit(why='check:time')` で `start`/`end`。量が 0(印だけ)なら文書は触らず記録だけ | — (新 `eval_timing --check` が answers.jsonl を読む) | 逆の commit |
- `why` の語彙に `check:read`・`check:voice`・`check:time` を足す(`store.HUMAN_WHYS`。知らない why は ValueError)。`commit` は文書の唯一の書き込み口 = apply は `store._save_lock` の中で `read_transcript` → 行を直す → `updatedAt` を進める → `snapshot` → `commit`(`save_transcript` と同じ並び。HTTP の PUT を自分に投げない)。層が shadow(今の既定)でも primary でも同じ呼び方(`hum` は渡さない)。
- 届けるの進み具合は画面が持たない(② の掲示板 `dl:` に載る。確かめるの画面は見ない = 答えたら即次へ)。失敗は次に開いたとき `counts.failed` で 1 行。

### 3-3 Z で 1 つ前に戻す
- 画面は答えの履歴(`[{answerId, card}]`)を持ち、Z = 最後の 1 件に `POST /api/check/answer {undo}` → 成功したらそのカードを先頭に戻す(飛ばした物は戻さない)。
- **[送る](友人へ届ける)だけは 1 枚遅れで確定**: 答えた時点では記録と「送る予定」だけ・次のカードに答えた(か 10 件のまとめ・画面を離れた・`skip`)時点でサーバーが `deliver` を始める。理由: Dropbox へ出た物は戻せない。確定の口は `POST /api/check/answer` の中(前の保留を先に確定)+ `UIKit.life.onLeave` で `POST /api/check/flush`。離れたのに届かなかった保留は次に開いたとき先頭に「前回の 1 件(送る予定)を届けますか」。
- 捨てた案: 全部 1 枚遅れ(文書・採否は逆の操作で足りる。遅らせると案件の画面で同時に開いたときの版がずれる)/ 送るも即(戻せない)。

## 4. 部品の共用(決めたこと 1 の当て方)
- RS8 の実装で分かったこと: 校正のパネルは編集の全画面(`app-*.js` 7 本 + テンプレート)を `edhost` で載せる形・候補のパネルは `review.js` 3,600 行を載せる形。カード 1 枚のために丸ごと mount すると、読み込みに数秒・`#segs` などの id・`window` の keydown が衝突・「答えたら即次へ」の速さが出ない。
- **共用する物**: 媒体の口(`transcribe/media?id=`(Range)= 今の続けて確認と同じ・候補のままは `youtube-nocookie.com/embed?start=&end=` = 校正の小さい配信プレーヤーと同じ形)/ 行の文字の見せ方(`UIKit` の `esc`・話者の色 `colors`)/ 比較欄の見た目 **`alt-pair` = 3 択 `machpick.js` の `.cs-mc-pair` を ui-kit の `.ui-pair` に昇格**(読みのカードと 3 択で同じ)/ 再生のキー `UIKit.keys.playback`(Space・← →)/ 下の帯 `UIKit.keybar`/ 入力中の判定 `UIKit.keys.isTyping`。
- **新しく作る物 1 つ**: `check/player.js` = `{mount(el, media, opt), play(), onEnded(fn), stop()}`。video(切り抜き)か iframe(配信の区間)+ 字幕 1 行(行の `text`)+ 波形の帯(時刻のカードだけ。`opt.wave`)+ 頭・末の印。「再生が終わるまで Enter は効かない」(voice)は `onEnded` から。
- カードは 4 ファイル(`cards/*.js`)が同じ口 `{render(card, el), keys(e, card) -> answer|null, keybar()}` で、殻 `check.js` が 1 本の keydown・帯・Z・10 件のまとめ・[飛ばす]・次の先読み(`next` の 10 枚を持ち 3 枚を残して補充)を持つ。重いカード(定点の校正 G2)は `cases?c=eval#proof` へのリンクのカード 1 種(`cards/heavy.js`。V1 では評価用の案件へ飛ぶだけ)。
- 捨てた案: `CasesPanels.create('proof', {rows: [i]})`(brief の見込み。校正の行 1 本だけを出す `opt.rows` は編集の全画面に手を入れる = 凍結した古いコードを直すことになる)/ ui-kit に動画の部品を足す(1 画面しか使わない間は app の中。2 つ目の使い手が出たら上げる)。

## 5. 声を自動で覚え直す・行の時刻の波形
- **覚え直し**(仮 1 人 30 秒分): `apply.py` の voice の反映のあと、その人の「確かめた行の合計秒(評価用でない・混ざり無し・1 秒以上)」が前回の覚え直しから 30 秒を超えたら、`speakers.run_voice_learn` と同じ道(`voice_learn_plan(doc, rows=…)` → ② `flow/diar.voices_edit` + `merge_voice(old, vec, rows, sec, doc)` = 前の声と長さで重みを付けて混ぜる。w0 = min(old.sec, 3600))をジョブ `voice-learn` で回す(重い = `SLOTS`)。記録は登録簿 `voices/<emb>.json` の `learnedFrom: [{doc, at}]`(**既にある**)に `rows`・`sec`・`by: 'check'` を足す。既存の名前に足すときの `confirmSame` は「カードで名前を選んだ = 同じ人」として省く。失敗しても答えは済んだまま(次の答えでまた試す)。しきい値は `machine.json` でなく編集の settings `check.voiceRelearnSec`(この PC の設定でなく使い方の設定)。
- **波形**: **今ある `GET /transcribe/api/peaks?id=<docId>`**(`editor/ed_media.py`。0〜255 の 1 バイトの並び + `X-Peaks-Rate`・`X-Peaks-Duration`。作成中は 202 → カードは「波形を用意しています」で再生は始める)。`player.js` が行の範囲 ± 2.5 秒だけ切り出して描く(2 カットの `cut.js` と同じ読み方)。頭・末の印は行の `start`/`end`、単語の印は `POST /api/retime {id, rows:[行]}` の `edges`(単語の時刻が無ければ無印)。← → は 1 コマ(1/30 秒)・Shift で 5 コマ(`cut.js` と同じ刻み)。
- 捨てた案: 新しい波形の API(① ffmpeg → ② → ③ の 3 層に動詞を足す。`peaks` が同じ物を既に出している)/ ブラウザの WebAudio で解読(mp4 を丸ごと読む = 数十 MB)/ `.words` の GET を足す(`retime` の応答で足りる)。

## 6. 作る段(1 段 = コミット + テスト)
| 段 | 中身 | 触る所 | テスト | モデル | 並列 |
| --- | --- | --- | --- | --- | --- |
| V0 ⑤ の待ち行列と口 | `src/eval/check/`(queue・sources・goals)・`accuracy.AREAS` に `fill`・`timing`(`--json` で流す。`summarize_generic`)・`GOALS` に `fill`(30 行)・`timing`(100 行)・`goals_of` に check の集計・入口の `GET /api/check/next`・`POST /api/check/skip`・`app\check\` の置き場所(`data-location.md`・バックアップの一覧) | `src/eval/check/*`・`src/eval/drill/accuracy.py`・`src/app/server.py`・`docs/spec/data-location.md` | 新 `src/eval/check/tests/test_queue.py`(純粋)・`test_sources.py`(一時フォルダの文書と data.json)・`src/home/tests/test_accuracy_api.py`・`test_launch`・層の検査 | Opus(記録の形が 5 通り・評価用の判定 = 影響が広い) | V1 と同時 |
| V1 画面の殻 | `src/app/ui/check/`: 配り(STATIC・NAV_PAGES・CSP・PORTAL_PAGES・appnav)・帯(今日 n 件・この確認で決まる物・あと m)・カードの枠・keydown 1 本・Z・[飛ばす]・10 件のまとめ・先読み・`player.js`・カードの口と空のカード 4 つ・空の状態(「今日の分は終わり」)・失敗(何が / 次に)。見本の CSS(`.chk-*`)を `check.css` に(`onclick=` は使わない) | `src/app/ui/check/*`・`src/app/server.py`・`src/home/appwindow.py`・`src/ui-kit/`(`.ui-pair` を足して `sync_ui_kit`) | 新 `src/app/tests/test_check_page.py`(配り・CSP)・**e2e 1 本 `src/app/tests/e2e_check.py`**(殻: 開く・帯・キー・Z・飛ばす・10 件のまとめ。疑似の `next`)・`dev/tests/test_ui_kit_sync` | Opus(入口・CSP・キー) | V0 と同時。終わったらカードの口を 4 本へ |
| V2a 価値のカード | `cards/value.js`・`human/check/apply.py` の value(自動 = `auto_review`・候補のまま = 採否 + 書き出し)・1 枚遅れの確定と `flush`・`POST /api/check/answer` の配線(apply の口は V2a が作り、b〜d は関数を足す) | `cards/value.js`・`src/human/check/apply.py`・`src/app/server.py` の POST 1 つ | 新 `src/human/check/tests/test_apply.py`(value)・`src/manage/cases/tests/test_cases.py`(auto_review の呼び方が変わらないこと) | Sonnet(今の口の呼び替え) | worktree |
| V2b 読みのカード | `cards/read.js`(1 / 2 / 打つ。`.ui-pair`)・apply の read(`store.commit why='check:read:*'`・fill の印・alt の判定)・`layers.py` の why の語彙 | `cards/read.js`・`apply.py`・`src/human/proof/layers.py` | `test_apply`(read)・`src/human/proof/tests/`(layers の why)・`src/eval/tools/tests/test_eval_fill.py`・`test_eval_alt.py`(読める形のまま) | Sonnet | worktree |
| V2c 誰の声のカード | `cards/voice.js`(予想・再生が終わるまで Enter 無効・名前 / その他 / 混ざり)・apply の voice(行 + `voices`)・覚え直し(30 秒・`learnedFrom`)・設定 `check.voiceRelearnSec` | `cards/voice.js`・`apply.py`・`src/human/proof/speakers.py`(覚える口の引数だけ)・`src/flow/diar.py` | `test_apply`(voice)・`src/flow/tests/test_diar.py`・`src/pipeline/transcribe/tests/test_diarize.py` | Opus(声の登録簿を書く・原因が追いにくい) | worktree |
| V2d 時刻のカード | `cards/time.js`(`peaks` の波形・`retime` の単語の印・← →・ちょうどいい / 頭 / 末 / 両方)・apply の time・`eval_timing --check`(answers.jsonl を正解として読む。今の正解 = 評価用の `proofed` の行に、確かめるの判定を並べる) | `cards/time.js`・`apply.py`・`src/eval/tools/eval_timing.py` | `test_apply`(time)・`src/eval/tools/tests/test_eval_timing.py` | Sonnet(API は今の物。描く所と道具の 1 枝) | worktree |
| V3 ホーム・案件のつなぎ | `#checkStart` を `/check` へ・`#checkNow` を `next?n=0` から・「続けて確認」(`rv*`・`#rvDrawer`・`#autoReview`)を消して「確かめる n 本」に・案件の頭の「確かめると効く物 n 件」・appnav の 4 項目・`/api/accuracy` の goals に新 2 つが出る文言 | `src/home/portal.*`・`src/app/ui/cases/cases.js`・`index.html`・`src/ui-kit/ui-kit.js`(appnav) | `e2e_portal`(直す。A5 の場面を外す)・`e2e_cases`(頭の n 件 1 件)・`test_launch` | Sonnet(DOM の組み替え) | V2 のあと |
| V4 締め(1 コミット) | `run_e2e.py` の SUITE(`e2e_check` を足す。所要秒)・`ui_audit.py` の `SCREENS["home"]` に check の 4 ファイル・`default_scenes` に確かめるの場面・`demo_env.py` に各種類 1 枚ずつ出る見本のデータ・`AGENTS.md` の表(`src/app/`・`src/eval/`・`src/human/` の行)・`README.txt`・`docs/spec/pipeline.md`(`check:*` の why・`/api/check`)・`plan/data.js` V1 を済みに・版を上げる | 上の全部 | `py -3.10 dev/run_e2e.py --only check,portal,cases`(一式は RS の区切りでないので流さない)・`py -3.10 dev/ui_audit.py all --demo` Must 0・`lint` 0・層の検査・`test_run_e2e` | Opus | 単独(サブエージェントが止まってから) |
- 見積もり(AI の実績に合わせて短く): V0 + V1 半日・V2 並列 半日〜1 日・V3 2〜3 時間・V4 2〜3 時間 = **1.5〜2.5 日**。
- **e2e は少なめ**: 足すのは `e2e_check.py` 1 本(殻 + 4 種類のカードを疑似の `next` で 1 枚ずつ答える場面)。消えるのは `e2e_portal` の A5 の場面。各段では自分の unittest と `e2e_check` だけ。
- **並列の約束**: V2 の 4 本は `cards/<名前>.js` と `apply.py` の自分の関数・自分のテストだけ。`check.js`・`player.js`・`check.css`・`server.py` を直したくなったら殻の持ち主へ `SendMessage`。`apply.py` は V2a が骨(口・記録・undo の枝)を先に入れて他の 3 本が関数を足す(worktree は古いコミットから始まるので最初に ff・取り込みは cherry-pick)。
- **ui_audit の Must 0**: V1 で `SCREENS["home"]` に `check` のファイルを足し、V1〜V3 の各段で `py -3.10 dev/ui_audit.py static` を 0 に。`all --demo` は V4 で場面を足してから。押せない理由(`data-ui-why`)・空の状態 2 文 + ボタン・失敗は何が / 次に、の決まりは今のまま。

## 7. 守りと決まり(変えない物)
- CSP は `/cases` と同じ(インラインの `<script>`・`onclick=` なし。見本の `onclick=` は写さない)。合言葉は入口の meta → `UIKit.http`。Host / Origin は `httpsec` の 1 か所。URL は相対(`check-cards/…`・`api/check/…`・`transcribe/media`)。
- **URL だけで実物を変えない**: `/check?…` を開いても答えるまで何も書かない(pipeline.md 3 節の決まり)。
- 評価用(`evalSet`・`in_eval_dir`)の文書・候補は `sources.py` の 1 か所で外す(テストで固定 = 評価用の文書が 1 枚でも出たら落ちる)。
- 重い処理(書き出し・届ける・覚え直し・波形)は今の `SLOTS`・② の器を通す。確かめるの画面は進み具合を持たない。
- 同じ名前の .py を作らない: `src/eval/check/queue.py` は `flow/runqueue.py` と別名・`apply.py` は他に無い(`test_mount` が検査)。`src/human/check/` と `src/eval/check/` の同名(`__init__.py` 以外)は作らない。
- 画面を離れた / 戻った = `UIKit.life`(`'hidden'` で再生を止める・`'blur'` は保留の `flush` だけ)。

## 8. ユーザーに確かめる物(一時の形でない物だけ)
1. **部品の共用の意味** = 案件のパネル(校正・候補)を丸ごとは載せず、カード用の軽い再生部品 1 つを新しく作り、口・見た目(比較欄)・キーを共用する(4 節)。brief 決めたこと 1 の読み替え。
2. **[送る](友人へ届ける)は 1 枚遅れで確定**(次のカードに答えた時点。Z で戻せるため)。友人に届くのが 1 枚ぶん遅れる・最後の 1 枚は画面を離れたときに確定。代案 = 今の「二度押し」(即・戻せない)。
3. **ホームの「続けて確認」(引き出し)を消す**(同じ物が V1 の価値のカード。V3)。残す案 = 2 か所に同じ機能。
4. **時刻のカードで「頭 / 末がずれている」と答えたとき**: ← → で動かした量だけ実際に行の時刻を変える(動かさずに H / E だけなら印の記録だけ・時刻は変えない)。代案 = ずれの向きだけ記録して時刻は変えない(答えが実物に効かない)。
- AI が仮で決めて進める物(確認は要らない): URL の引数名(`c`・`kind`・`back`)・記録の置き場所と 1 行の形・`why` の語彙 `check:*`・目標の数(fill 30・timing 100)・覚え直しの 30 秒(設定)・波形の点の数と刻み・各段のモデル・e2e の本数。実装の段で `plan/decisions.md` の「仮で決めたこと」と `plan/data.js` の `userTasks.provisional` に 1 行ずつ。
