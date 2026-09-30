# 段3: 操作の一貫性(キー・フォーカス・取り消し)
> 状態(2026-09-30): **済み**(編集 0.26.0。3-1〜3-5 すべて。03・04・16 の多くは「気が利く画面へ 段6」(ui-kit v8)で入っていたので、今のコードとの差だけを直した。細部は WORKLOG の「段3」)。
> 決定(2026-09-30): 校正の S=次の行・W=前の行・Q=3秒戻る と 2 カット の S=分割・Q/W=端(同じキーでタブごとに別の意味)は **(1) 現状維持**。`docs/spec/ui-guidelines.md` の 2-3 に例外として記載。保留なし。
> 以前の状態(2026-09-29): 未着手。UI 追加監査の 03・04・05・15・16 を直す(「編集」のキー・フォーカス・元に戻す)。
> 全体の計画は `docs/ROADMAP.md`。行番号は 2026-09-29 時点(始める前に今のコードで確かめ直す)。版の番号は、前の段で上がっていればそこから上げる。

## 目的
- 登録できたキーは、必ずその操作として働く(別の操作に奪われない)。受け付けないキーは、登録のときに理由を出して断る
- 左のメニューを重ねて開いている間・メニューの中にフォーカスがある間は、後ろの文書のキー操作が動かない(1 文字起こし と 2 カット の両方)
- 1 文字起こし の「元に戻す」(ボタン・Ctrl+Z)は、文字起こしの編集とカットのどちらでも、いちばん新しい操作を1つ戻す(ユーザー決定 09-29: 2つの履歴を持ち、新しい方を戻す)
- 「1コマ」は素材の fps で動く(1 文字起こし と 2 カット で同じ感触)
- ツールチップ・通知・キー帯・キーの説明は、キー配置(⚙ 設定の「キー配置」)のとおりに出す。未設定のキーは書かない

## 含む作業と順番
| # | 作業 | 大きさ | 依存 |
|---|---|---|---|
| 3-1 | 04 左メニューを重ねて開いている間、後ろの文書のキーを止める(文字起こし・カット) | S | なし |
| 3-2 | 03 シークの割当キー + Shift(派生キー)を含めた衝突の検査 | M | なし(ui-kit を触る) |
| 3-3 | 16 キーの表示(title・通知・キー帯・説明)をキー配置から出す | M | 3-2(同じキー配置の関数を使う) |
| 3-4 | 15 1 文字起こし の「1コマ」を素材の fps で | S | なし |
| 3-5 | 05 1 文字起こし の「元に戻す」で、新しい方(文字起こし/カット)を戻す | M | なし(3-1 と同じ keydown を触るので、3-1 の後が楽) |

順番の理由: 3-1 は小さく独立で、3-5 と同じ keydown の条件を触るので先に片付ける。3-3 は 3-2 で作る「キーの名前を出す関数」を使う。

## 各作業の細かい計画

### 3-1 左メニューを重ねて開いている間、後ろの文書のキーを止める(監査 04)
- 今の動き: 文書のキー処理の除外は dialog・ui-drawer・文字入力だけ(`editor/app.js:1943`、Ctrl+Z は `app.js:2448`、Tab は `app.js:1965` 付近、共通の再生キーの enabled は `app.js:1938`)。
  重ねて開いたメニュー(`isDrawer() && menuOpen()`、`app.js:170`・`app.js:102`)は条件に無い。カットも同じ(`cut.js:848` の enabled、`cut.js:856` の onKey)。
  1440px では文書を開いているとメニューが重なる(`OVERLAY_MID`、`app.js:169`)ので、履歴のボタンにフォーカスして ↓ で後ろの行が動く
- 変えること: app.js に1つの判定 `menuHoldsKeys(e)` を作る = 「重ねて開いている(isDrawer() && menuOpen())」または「キーの行き先が `#menuPanel` の中」。
  文書のキー(校正のキー・共通の再生キー・Ctrl+Z・Tab・カットの onKey と共通キー)はこのとき何もしない。
  残すもの: G(メニューの開閉。`app.js:1948` の act === 'menu')・Esc(閉じる。`app.js:203`)・Alt+1/2/3(タブ。メニューを閉じずに切り替わるのは今と同じ)・? (一覧)。
  カットへは host に `menuHoldsKeys` を渡す(`app.js:2739` の EditCut.create の引数)
  - 案: (a) 重ねている間は全部止める / (b) フォーカスがメニューの中のときだけ止める。(a) だけだと 1600px 以上の並べて出すメニューで同じ漏れが残る、(b) だけだと幕の上で押したキーが漏れる → 両方の OR にする
- 変えるファイル: `editor/app.js`・`editor/cut.js`
- テスト: `editor/tests/e2e_edit_tabs.py` の「B-7: 1440px で…重ねて開く」の節に足す: 履歴のボタンにフォーカス → ↓ で `S.navIdx`(今の行)が変わらない・Space で再生しない・G と Esc では閉じる。
  2 カット のタブで G で重ねて開き、S で分割されない・Space で再生しない。流す: `editor/tests/e2e_edit_tabs.py`・`editor/tests/e2e_edit_cut.py`・`editor/tests/e2e_row_editing.py`・`editor/tests/e2e_ui_handoff.py`(390px の引き出し)
- リスク・エッジケース: メニューの中の検索欄(文字入力)は今どおり isTextEntry で除外される。Esc は「検索欄に文字があればまず空に」(`app.js:207`)を壊さない。
  右クリックのメニュー(`app.js:1701`、捕捉の段階)は先に受けるので影響なし
- 終わりの条件: 重ねたメニューにフォーカスがある間、↓↑・Space・S・Ctrl+Z などで文書・カットが変わらない。G・Esc・Alt+数字は今どおり

### 3-2 シークの割当キー + Shift(派生キー)を含めた衝突の検査(監査 03)
- 今の動き: 共通の再生キーは「seekBack/seekFwd に割り当てたキー + Shift」を5秒のシークとして先に取る(`ui-kit/ui-kit.js:878`〜`882`)。
  登録の検査 `keyRefusal`(`app.js:1894`)と `sanitizeKeymap`(`app.js:1900`)・`setKey`(`app.js:2015`)はこの派生キーを知らない → 「次の行」に Shift+← を登録でき、押すと5秒戻る
- 変えること:
  1. ui-kit に `UIKit.keys.derived(km)` を足す(`{ 'Shift+ArrowLeft': 'seekBack', … }` を返す。ルールは keysPlayback の中の派生と同じ所に置き、keysPlayback もこれを使う)。
     案: app.js だけで `'Shift+' + km.seekBack` を作る方が ui-kit の同期が要らないが、ルールが2か所になり、派生を増やしたときにずれる → ui-kit に置く
  2. `keyRefusal(d, combo, km)`: 校正のキーが派生キーと同じなら「Shift+← は『1秒戻る』のキー + Shift(5秒戻る)に使っています」と断る。
     seekBack/seekFwd に登録するときは、派生キーが固定のキー(KEY_FIXED)なら断り、他の操作が持っていれば今の「重なったら前の方を外す」(`app.js:2021`)と同じく外して通知
  3. カットの Shift+, / Shift+.(10コマ。`cut.js:866` は e.code で見る)が出す `<` `>` を CUT_KEYS(`app.js:1892`)に足し、再生のキーに登録できないようにする
  4. `sanitizeKeymap`: 読み込んだ配置で、派生キーと重なった校正のキーは外す(実際には共通キーが先に取って働かないので、「未設定」と見せる方が正しい)
- 変えるファイル: `ui-kit/ui-kit.js`(正本)→ `python dev/sync_ui_kit.py` で `studio/ui-kit.js`・`editor/ui-kit.js` へ写す、`editor/app.js`、`ui-kit/README.md`(v6 の節に1行)
- テスト: `editor/tests/e2e_proofread_keys.py` のキー配置の節(`editor/tests/e2e_proofread_keys.py:154` 付近)に足す: 「次の行」に Shift+← → 断られて未設定のまま / 「1秒戻る」を A にすると、Shift+A を持つ操作があれば外れる。
  流す: `python -m unittest dev/tests/test_ui_kit_sync.py`(直下)、`editor/tests/e2e_proofread_keys.py`・`editor/tests/e2e_edit_cut.py`、スタジオは ui-kit の写しが変わるので `node --test studio/tests/test_review.cjs` と `python studio/tests/e2e_ui.py`
- リスク・エッジケース: 既に config.json に派生キーと重なる配置を保存している人は、読み込みで校正のキーが「未設定」になる(実際に働いていなかったキーなので実害は無いが、通知が無い)。
  → 設定を開いたときに「使えないキーを外しました」を1回出すかは 3-3 の中で決める(小さく済む方)。記号キーは Shift で文字が変わる(`ui-kit.js:817` の comboOf)ので、`,` に割り当てたシークの派生は作らない(今と同じ)
- 終わりの条件: 派生キーと重なる登録はできない(理由が出る)。共通キーを変えたあとも、重なった登録が残らない

### 3-3 キーの表示(title・通知・キー帯・説明)をキー配置から出す(監査 16)
- 今の動き: 固定の文字列が残っている
  - 音の状態のボタンの title の X/C/V(`app.js:1479` の TAG_KEY)・行の ▶ の「(R)」・「＋後に行(N)」・削除の「Z でも」(`app.js:1488`・`1495`)
  - 削除の通知「もう一度 Z で」(`app.js:1859`)・メニューのボタンの「(G)」(`index.html:1034`・`1064`・`1069`)
  - カットのキー帯の `,` `.` `Space` `I` `O`(`cut.js:389`〜`392`)・カットの再生ボタンの「(Space)」(`index.html:1405`)・カットの下のキーの説明(`index.html:1465`)
  - キー操作の一覧のカットの段落(`index.html:1568`)と「基本の流れ」(`index.html:1570`。S・R・T・B・X/C/V)
  すでに配置どおりなのは、1 文字起こし のキー帯(`app.js:135`)・一覧の上の手がかり・キー操作の一覧の表(`app.js:1984` の renderKeyUI)
- 変えること: app.js に `keyName(id)`(割り当てがあれば表記、無ければ '')を1つ作り、上の全部をここから出す。未設定なら「(X)」ごと出さない。
  静的な HTML の説明は renderKeyUI で描き直す(キーの部分に `<span data-key="replay">` を置いて埋める。CSP 上インラインの script は使わない)。
  カットには host に `keyName` を渡し、`cutKeybarScene` と `#cutPlay` の title を配置から作る(分割 S・[ ]・Q/W・Del・X は固定のキーなので今のまま)。
  行の title は行を描くときに入るので、キー配置を変えたら `renderDoc()` をやり直す(配置の変更はまれなので、行が多くても許容)
- 変えるファイル: `editor/app.js`・`editor/cut.js`・`editor/index.html`
- テスト: `editor/tests/e2e_proofread_keys.py` のキー配置の節に足す: 「聞き取れない」を H にすると行の title が「(H)」、未設定にすると「(」が消える / 「1コマ進む」を変えるとカットのキー帯とカットの説明が変わる / 削除を未設定にしても嘘のキーの通知が出ない。
  流す: `editor/tests/e2e_proofread_keys.py`・`editor/tests/e2e_edit_cut.py`・`editor/tests/e2e_ui_handoff.py`(キー操作の手がかり・?)・`editor/tests/e2e_ui_mounted.py`
- リスク・エッジケース: 4000 行の文書で renderDoc をやり直す時間(`editor/tests/e2e_proofread_keys.py` の 4000 行の確認で測る)。行の title を「押したときに作る」方式にすれば再描画は要らないが、ホバーの title がずれるので採らない。
  スタジオの一覧(keymap を渡さない helpHtml)は変わらない
- 終わりの条件: キー配置を変えると、帯・title・通知・説明の全部が同じキーを出す。未設定のキーはどこにも出ない

### 3-4 1 文字起こし の「1コマ」を素材の fps で(監査 15)
- 今の動き: 共通の再生キーに `fps: 30` 固定(`app.js:1937`)。カットは素材の fps(`cut.js:847`、`M.fps` は `/api/edit/draft` か保存済みのカットから。`cut.js:134`〜`135`)で、フレームの境目にそろえて動く(stepFrames)
- 変えること: `fps: () => { const f = CUT && CUT.fps(); return f ? f[0] / f[1] : 30; }` にする(CUT.fps() は文書を開くとタブによらず読み込まれる。`app.js:1468`・`cut.js:914`)。
  あわせて `onFrame` で「今の位置をフレームの境目にそろえてから ±1」にする(カットの stepFrames と同じ丸め)。
  案: fps を渡すだけ(小さい)/ 境目にそろえる(押し続けても浮動小数のずれが溜まらず、カットと同じ位置に止まる)→ 後者。丸めの式は cut.js から `CUT.frameStep(t, dir)` として出して1か所にする。
  fps が分からない文書(動画が無い・ネットワーク上・音声だけ。`cut.js:133` の unavailable)は 30 のまま、キー操作の一覧の共通キーの下に「動画の fps が分からないので、1コマは約 1/30 秒」と1行出す
- 変えるファイル: `editor/app.js`・`editor/cut.js`
- テスト: `editor/tests/e2e_edit_pack.py` は 60fps の見本を作っている(`editor/tests/e2e_edit_pack.py:95` 付近)ので、同じ見本で 1 文字起こし のタブで止めて `.` → currentTime が 1/60 秒進む・`,` で戻る を足す(置き場所は editor/tests/e2e_edit_cut.py でもよい。見本の作り方が近い方)。
  流す: `editor/tests/e2e_edit_cut.py`・`editor/tests/e2e_edit_pack.py`・`editor/tests/e2e_proofread_keys.py`
- リスク・エッジケース: 可変 fps の動画は ffprobe の r_frame_rate が代表値なので、厳密な1コマにならない(監査の指摘どおり。表記は「1コマ」のまま、キー一覧の注で触れるかは実機で見て決める)。
  文書を開いた直後(CUT.load の途中)は 30 で動く
- 終わりの条件: 60fps の素材で `.` 1回 = 1/60 秒。1 文字起こし と 2 カット で同じ位置に止まる

### 3-5 1 文字起こし の「元に戻す」で、新しい方(文字起こし/カット)を戻す(監査 05)
- 今の動き: 1 文字起こし の行の「残す」(`app.js:1627`)と「選んだ行をカット」(`app.js:2684`)は、カットが使えるときは `CUT.rowsCut` に任せ、カットの履歴(`cut.js:99` の M.undo)に積む。
  1 文字起こし の「元に戻す」と Ctrl+Z(`app.js:1561` doUndo・`app.js:2449`)は文字起こしの履歴 `S.undo` だけを見る → カットを戻せず、ボタンも無効のまま。カットの undo は cut.js の中だけ(`cut.js:111`。外に出していない)
- 変えること: 2つの履歴はそのまま、操作の通し番号で新しい方を戻す
  1. app.js に `nextOp()`(通し番号)を作り、`pushUndo`(`app.js:1557`)と `withUndoReplace`(`app.js:2307`)の積む物を `{ seq, snap }` にする
  2. cut.js の `change()` で積むとき `seq: h.nextOp()` を付ける。やり直し(redo)から戻すときも新しい番号。`CUT.undoTop()`(一番上の seq。準備ができていなければ 0)・`CUT.undo()`・`CUT.undoCount()` を出す
  3. doUndo: 文字起こしの一番上とカットの一番上を比べて新しい方を戻す。カットを戻したら「カットを1つ戻しました」と通知(見えていない操作を黙って戻さない)
  4. ボタンの数「元に戻す(n)」(`app.js:1560`)は2つの合計。カットが変わったとき(`onCutMarks`・`onCutState`)にも updateUndo を呼ぶ
  5. 通知の文(`app.js:2687`「カットのタブの『元に戻す』」)を「元に戻す(Ctrl+Z)」に直す
  2 カット のタブの Ctrl+Z はカットだけのまま(決定は 1 文字起こし の動き。カットのタブには文字の変化が見えないため)
- 変えるファイル: `editor/app.js`・`editor/cut.js`
- テスト: `editor/tests/e2e_edit_cut.py` に足す: 1 文字起こし で行の「残す」→ カット後の長さが減る → Ctrl+Z で元の長さ / 文字を直す → 行をカット → 文字を直す の順で Ctrl+Z を3回 → 新しい順に戻る / ボタンの数が合計になる。
  流す: `editor/tests/e2e_edit_cut.py`・`editor/tests/e2e_edit_tabs.py`・`editor/tests/e2e_proofread_accuracy.py`〜`editor/tests/e2e_row_editing.py`(元に戻すを使う所)・`node --test editor/tests/test_document_save.cjs`
- リスク・エッジケース:
  - 文字起こしの控え(snap)は行の cutState も含む。カットのあとで古い控えに戻すと、行の「カット済」がカットの中身とずれる → 戻したあと `CUT.docChanged()` 経由(`app.js:1347`)で付け直されることを e2e で確かめる
  - 処理中(lockJob)はどちらも戻さない。文書を切り替えるとどちらの履歴も空になる(`app.js:1448`・`cut.js:117`)ので番号の比べ方は壊れない
  - カットの保存の競合(409)の最中に戻した場合は、カットの今の保存の流れ(scheduleSave)に任せる
- 終わりの条件: 1 文字起こし で、文字の編集とカットを混ぜても、Ctrl+Z・ボタンで操作した逆の順に1つずつ戻る

## 版の上げ方
- 編集: `editor/serve.py` の SERVER_VERSION・`app.js` の APP_VERSION・`README.txt` の見出しを同時に minor を1つ上げる(今は 0.21.0。前の段で上がっていれば、その次。始める前に WORKLOG と実ファイルで確かめる)。README に「変更」の節を足す
- ui-kit: `UIKit.keys.derived` を足すだけ(足すだけで今の動きは変えない)なので v6 のまま、`ui-kit/README.md` の v6 の節に1行。`dev/sync_ui_kit.py` で写す
- スタジオ: ui-kit の写しが変わるだけで画面の動きは変わらないので版は上げない(前に同期だけしたときの扱いを WORKLOG で確かめ、違えばそれに合わせる)

## 実機で確かめること
- 1440px で履歴のメニューを重ねて開き、メニューの中で ↓・Space・S を押しても文書・カットが動かない。G・Esc で閉じられる
- キー配置で「次の行」に Shift+← を登録しようとすると断られる。「1秒戻る」を別のキーにしたあと、その Shift つきで5秒戻る
- 60fps の配信の切り抜きで、1 文字起こし の `.` と 2 カット の `.` が同じ1コマ
- 1 文字起こし で行を「残す」→ 文字を直す → Ctrl+Z 2回で、文字 → カットの順に戻る
- キー配置を変えたあと、行の title・キー帯・? の一覧・カットのキーの説明が同じキーを出す

## 決まったこと(2026-09-29 ユーザー。計画を書いたあとに聞いた分)
- なし(05 の動きは 09-29 に決定済み。2 カット のタブの Ctrl+Z はカットだけのまま)
