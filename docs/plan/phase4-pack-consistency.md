# 段4: パックの表示と実際の出力を一致させる
> 状態(2026-10-01): **済み**(編集 0.27.0。4-1〜4-5 すべて。cut2resolve・入口は変えていない)。以前の状態(2026-09-29): 未着手。UI 追加監査の 07・08・09・10・12(残り)を直す(3 パック のタブの見積もり・前回の設定・前回のパック・zip・字幕の見本の色)。
> 全体の計画は `docs/ROADMAP.md`。行番号は 2026-09-29 時点(始める前に今のコードで確かめ直す)。版の番号は、前の段で上がっていればそこから上げる。

## 目的
- パックのタブに出ている数字・見本・注意・「前回の設定」が、実際に作るパック(と zip)と同じになる
- 設定を変えたら見積もりを出し直す。計算中・失敗・未計算を見分けられる
- 前回のパックを作ったときの出力の設定を記録し、今の設定との違いを出す(できたファイルは変わっていないことも書く)
- 「前回の設定」には覚えている物だけを出す(ユーザー決定 09-29: 出力先は覚えない・毎回動画の隣が既定、「粗編集の動画つき」は覚える)
- zip は今のまま。zip に渡らない設定を画面に書く(ユーザー決定 09-29)
- パックの字幕の見本と 2 カット の字幕も、映像の上の字幕(#playerCaption)と同じく話者ごとの色で出す

## 含む作業と順番
| # | 作業 | 大きさ | 依存 |
|---|---|---|---|
| 4-1 | 07 見積もりに効く設定を変えたら出し直す・計算中/失敗/未計算を分ける | S | なし |
| 4-2 | 09 「粗編集の動画つき」を覚える・「前回の設定」は覚えている物だけ | S | なし |
| 4-3 | 08 パックを作ったときの出力の設定を記録し、今の設定との違いを出す | M | 4-2(どの設定を「出力の設定」として並べるかを共有する) |
| 4-4 | 10 zip に渡らない設定を画面に書く・契約テストに差分を足す | S | 4-3(設定の一覧の関数を使う) |
| 4-5 | 12 残り: パックの字幕の見本と 2 カット の字幕を話者の色で | M | なし(4-1 の見積もりの応答を少し変える) |

順番の理由: 4-1・4-2 は pack-tab.js の中で閉じて小さい。4-3・4-4 は「今の出力の設定」を1つの関数(`outputNow()`)にまとめてから使う。4-5 はサーバーの見積もりの形を変えるので最後に契約テストと一緒に流す。

## 各作業の細かい計画

### 4-1 見積もりに効く設定を変えたら出し直す(監査 07)
- 今の動き: 縦横の変更は `setOpt`(`editor/pack-tab.js:279`)で保存と render だけ。見積もりの鍵に `wrapOf()`(縦横で変わる。`pack-tab.js:14`)が入る(`pack-tab.js:118`・`146`)ので、
  変えた瞬間に見積もりが古い扱いになり、字幕数が「…」(`pack-tab.js:151`)・注意が消える(`pack-tab.js:162`〜`166` は fresh のときだけ注意を足す)。出し直しの予約はタブの出入り(`pack-tab.js:323`)とカット・文字の変更(`pack-tab.js:324`)だけ。
  ⚙ 設定の字幕の文字数(wrapChars。`app.js:2404` → readOpts `app.js:247`)の変更も PACK に知らせない。
  さらに `runPreview` は文書の保存に失敗すると何も記録せずに戻る(`pack-tab.js:122`)ので「…」のまま止まる
- 変えること:
  1. 見積もりの状態を `P.pv = 'idle' | 'wait' | 'run' | 'err'` で持つ。render で「鍵が変わった・予約も計算も無い」なら `schedulePreview()` する(どの経路で設定が変わっても自分で直る)。
     案: 設定を変える所ごとに schedulePreview を呼ぶ(はっきりしているが、足し忘れで同じ不具合が戻る)/ render で鍵を見て予約(1か所で済む)→ 後者。二重に予約しないよう pvT と pvSeq で守る
  2. 表示: 計算中は「計算しています…」、失敗は理由 +「もう一度」ボタン、保存待ちで計算できないときは「文字起こしの保存を待っています」。
     前の見積もりの注意は、計算中は「(前の設定での見積もり)」と添えて薄く残し、黙って消さない
  3. readOpts で字幕の文字数が変わったら `PACK.changed()` を呼ぶ
- 変えるファイル: `editor/pack-tab.js`・`editor/app.js`(readOpts の1行)・`editor/index.html`(「もう一度」ボタンと薄くする見た目)
- テスト: `editor/tests/e2e_edit_pack.py` の設定を変える所(`editor/tests/e2e_edit_pack.py:69` 付近)に足す: 縦 → 横で字幕数が「…」のままにならず数字に戻る・注意が再び出る / 見積もりの API を止めた状態(ルートを横取りして 500)で失敗と「もう一度」が出る。
  流す: `editor/tests/e2e_edit_pack.py`・`editor/tests/e2e_ui_mounted.py`(パックのタブ)
- リスク・エッジケース: render は requestAnimationFrame でまとめて呼ばれる(`pack-tab.js:132`)ので、render から予約しても連打にはならない。ただしパックのタブを見ていないときは予約しない(今の `changed()` と同じ。見えないタブで保存と計算を走らせない)。
  見積もりの前に文書を保存する(`pack-tab.js:122`)ので、保存の競合(409)中は「保存の競合を先に解いてください」と出す
- 終わりの条件: 縦横・fps・字幕の文字数を変えると、タブを移らずに見積もりが新しくなる。計算中・失敗・未計算が見て分かる

### 4-2 「粗編集の動画つき」を覚える・「前回の設定」は覚えている物だけ(監査 09)
- 今の動き: 覚えているのは fps・大きさ(`S.settings.packFps`・`packSize`、`pack-tab.js:12`・`13`・`279`)と、このブラウザの「話者の色」(`pack-tab.js:71`〜`73`)・文書ごとの配信者の名前(`pack-tab.js:48`)。
  「予備」「粗編集の動画」は変えても render だけ(`pack-tab.js:284`・`285`)、出力先は文書を開くたびに空欄(`pack-tab.js:100`)。
  なのに「前回の設定」の要約(`pack-tab.js:183`〜`188`、見出しは `index.html:1475`)は予備・粗編集・出力先も並べる → 再読み込みで要約の中身が変わる
- 変えること:
  1. 粗編集: `S.settings.packRender` に覚える(change で setOpt。文書を開いたとき `load()` でチェックに戻す。設定はサーバーの config.json なので、別の窓・ブラウザでも同じ)
  2. 要約は覚えている物だけ: fps・大きさ・粗編集の動画つき(オンのとき)・予備(オンのとき。09-29 決定で覚える)・配信者の色の丸(今どおり)。出力先は要約から外す
  3. 出力先は要約の外に「作る場所: 動画の隣の『<動画名>_pack』(毎回ここ。変えるときは設定の 3)」の1行で出す(覚えない物だと分かるように)。欄の説明(`index.html:1552`)にも「覚えません(毎回空欄から)」を足す
  - 出力先を覚えないのは決定どおり(別の案件へ間違って出さないため)。同じ文書を開いている間は欄に入れた値が残る(今どおり。文書を切り替えると空欄)
- 変えるファイル: `editor/pack-tab.js`・`editor/index.html`
- テスト: `editor/tests/e2e_edit_pack.py`: 粗編集をオン → 再読み込み → オンのまま・要約に「粗編集の動画つき」/ 出力先を入れて再読み込み → 空欄・要約に出力先が無い・「作る場所」の行は動画の隣 / 予備をオンにして再読み込み → オンのまま・要約に「予備」。
  既存の確認(`editor/tests/e2e_edit_pack.py:58`・`69` の要約の文字)は中身が変わるので直す。流す: `editor/tests/e2e_edit_pack.py`・`editor/tests/e2e_ui_mounted.py`
- リスク・エッジケース: 粗編集の動画は時間と容量がかかる。覚えたままにすると、次の文書でも気づかずに作る → 要約に「粗編集の動画つき」と出ることで気づける(ボタンの近くに出す)。
  字幕の無い文書は予備がいつもオン(`pack-tab.js:172`)。覚えた値と食い違わないよう、要約はそのときの実際の値(字幕が無ければオン)を出す
- 終わりの条件: 「前回の設定」の要約は再読み込みの前後で同じ。出力先は要約に出ず、作る場所の行で毎回動画の隣と分かる

### 4-3 パックを作ったときの出力の設定を記録し、違いを出す(監査 08)
- 今の動き: 作り終えた記録 `/api/edit/pack` は rev・文書の更新日時・フォルダ・ファイル名だけ(`pack-tab.js:262`・`264`、サーバーの `record_pack` `serve.py:1079`〜`1100`)。
  「作り直しが要る」の判定 `isStale`(`pack-tab.js:201`)はカットの rev・文書の更新日時・未保存だけを見る → 60fps・粗編集ありに変えても緑の「前回のパック」のまま
- 変えること:
  1. 画面に `outputNow()` を作る: `{ fps, size, wrap, textplus, backup, render, streamer(名前), speakerColors, advanced: { srcStartTc, recStart, reel } }`。build の out(`pack-tab.js:241`)もこれから作る
  2. `/api/edit/pack` に `output` を足す。サーバーは決まった鍵だけ・型と長さを確かめて保存(文字列は 40〜200 字まで、fps は数字の文字列、size は2つのどちらか)。無い・壊れていれば保存しない(古い画面・まとめて実行からの記録と同じ扱い)
  3. 前回のパックの欄に「作ったときと違う設定」を並べる(例: 「fps: 30 → 60」「粗編集の動画: なし → あり」)。札は「設定が違う」(黄)とし、「できているファイルは作ったときのまま(変わっていません)。作り直すと今の設定になります」と書く。
     カット・字幕の変更(今の isStale)と設定の違いは別の文で出す(直す場所が違うため)
  4. 記録に output が無いパック(この版より前・まとめて実行 `home/autorun.py:581`〜`584`)は「作ったときの設定の記録がありません」と出し、違いは出さない
  - 案: 記録を edit.json の pack に入れる(今の場所。文書と一緒に消える・入口の txindex は読まない)/ パックのフォルダの中に書く(パックに入れない方針に反する)→ 前者
- 変えるファイル: `editor/pack-tab.js`・`editor/serve.py`(record_pack・先頭の API 一覧 `serve.py:35`)・`editor/index.html`(違いの欄)・`editor/AGENTS.md`(パックの記録の形)
- テスト: `editor/tests/test_edit.py` の `test_record_pack_and_stale`(`editor/tests/test_edit.py:155`)に足す: output の鍵の許可・型の違い・長すぎる文字・余計な鍵を捨てる・無くても記録できる。
  `editor/tests/e2e_edit_pack.py`: 30fps で作る → 60fps に変える → 「設定が違う」と「fps: 30 → 60」→ 30 に戻すと消える / 粗編集をオンにすると違いが出る。
  流す: `python -m unittest editor/tests/test_metrics.py editor/tests/test_resolve_export.py -q`(test_edit を含む)・`editor/tests/e2e_edit_pack.py`・`editor/tests/e2e_ui_mounted.py`
- リスク・エッジケース: 記録の値は edit.json から読んで画面に出すので、必ず esc() する(`read_edit` は pack を中身を確かめずに返す。`serve.py:874`〜`875`)。
  配信者の名前は個人データではないが、作業データの外(リポジトリ)には出ない(edit.json は作業データ)。一覧の「作り直し」(packStale。`serve.py` の edit_summary)は今どおりカット・字幕だけで決める(設定の違いまで一覧に出すと、fps を変えただけで全部が作り直しに見える)
- 終わりの条件: パックを作ったあとで設定を変えると、前回のパックの欄に違いが出て、ファイルは変わっていないと書かれる

### 4-4 zip に渡らない設定を画面に書く(監査 10)
- 今の動き: zip の説明は「中身は上の『パックを作る』と同じ」(`pack-tab.js:179`)。zip の要求(`pack-tab.js:312`)は fps・大きさ・予備・字幕の文字数・配信者・話者の色だけで、
  粗編集の動画・開始タイムコード・タイムラインの開始タイムコード・リール名(`pack-tab.js:239`〜`241`)は渡さず、`resolve_export.create_package`(`resolve_export.py:237`)にも引数が無い
- 変えること(zip の中身は変えない。決定どおり):
  1. pack-tab.js に `ZIP_SKIPS = ['render', 'srcStartTc', 'recStart', 'reel']` と名前を1か所に書き、zip の説明を
     「残す区間・字幕・予備・fps・大きさは上の『パックを作る』と同じ。粗編集の動画・開始タイムコード・リール名は zip には入りません(使うのは入口から『パックを作る』)」にする
  2. 今それらを選んでいる(粗編集オン・タイムコード/リール名が空でない)ときだけ、zip のボタンの横に「今の設定のうち ○○ は zip に入りません」と黄色で出す
- 変えるファイル: `editor/pack-tab.js`・`editor/index.html`(`index.html:1543` の説明)・`dev/tests/test_resolve_pack_contract.py`
- テスト: `dev/tests/test_resolve_pack_contract.py`(単独で流す)に足す: 同じ文書で zip と pack.py のパックを、予備あり/なしで比べて同じファイル(粗編集の動画と手順書を除く)・
  zip には `_roughcut.mp4` が無い・詳しいタイムコードを変えても zip の EDL は変わらない(= 渡らないことを固定し、将来渡すようにしたら画面の説明も直す合図にする)。
  `editor/tests/e2e_edit_pack.py`: 粗編集オンで zip の横に注意が出る。流す: `python -m unittest dev/tests/test_resolve_pack_contract.py`・`editor/tests/e2e_edit_pack.py`
- リスク・エッジケース: 字幕の無い文書では「パックを作る」は Text+ を作らない(`pack-tab.js:241` の textplus: hasRows)が、zip は常に textplus=True(`resolve_export.py:265`)。
  契約テストで字幕なしの文書の zip の中身も確かめ、違えば説明に足す(中身は変えない)
- 終わりの条件: zip の説明と注意が、zip に入らない設定を正しく言う。契約テストがその差を固定している

### 4-5 パックの字幕の見本と 2 カット の字幕を話者の色で(監査 12 の残り)
- 今の動き: 映像の上の字幕は話者の色にしている(`app.js:1777` updateCaption → `app.js:1788` capSpeakerColor。「話者の色」のスイッチ `tx.pk.speakerColors` を見る)。
  パックの見本(`pack-tab.js:155`〜`157`)と 2 カット の字幕(`cut.js:553`〜`558` showCaption)は文字だけで、body の `--tt-cap-color`(配信者の色。`pack-tab.js:64`、`index.html:893`)のまま。
  見積もりの見本 `samples` は文字だけで話者が無い(`resolve_export.py:230`)。照らし合わせの控えは app.js の capSpk と pack-tab.js の spkCache(`pack-tab.js:74`〜`81`)で二重
- 変えること:
  1. 見積もりの応答に `sampleSpeakers`(見本と同じ順の話者の名前。pack.py の `cue_speakers`(`cut2resolve/pack.py:444`)= 実際のパックと同じ規則)を足す。規則は pack.py だけに置き、ここで書かない
  2. app.js の capSpeakerColor を「名前 → 色」の1つの関数 `speakerHex(name, onReady)` にまとめ、PACK と CUT に host で渡す(spkCache をやめて1つの控えに)
  3. パックの見本・縦長の見本(`#pkPhoneCap`)・2 カット の字幕に、話者の色があれば `--tt-cap-color` を要素に付ける(無ければ配信者の色のまま)。見積もりが古い間の見本(文書の行から作る方)は行の speaker から色を出す
  4. 「話者の色」のスイッチ(`pack-tab.js:73`)を変えたら、映像の上・カット・見本の全部を描き直す(今は映像の上の字幕を描き直さない)
- 変えるファイル: `editor/resolve_export.py`(edit_preview の応答)・`editor/app.js`・`editor/pack-tab.js`・`editor/cut.js`
- テスト: `editor/tests/test_edit.py` の見本の確認(`editor/tests/test_edit.py:442` 付近)に sampleSpeakers を足す。`editor/tests/e2e_edit_pack.py` の話者の色の節(`editor/tests/e2e_edit_pack.py:110` 付近)に: パックの見本の1つ目が「みこ」の行ならさくらみこの色 /
  2 カット で「みこ」の行を再生中の字幕が同じ色 / スイッチを切ると全部が配信者の色。
  流す: `python -m unittest editor/tests/test_metrics.py editor/tests/test_resolve_export.py -q`・`python -m unittest dev/tests/test_resolve_pack_contract.py`(単独)・`editor/tests/e2e_edit_pack.py`・`editor/tests/e2e_edit_cut.py`
- リスク・エッジケース: 色は style に入れるので `#rrggbb` の形を確かめてから入れる(今の capSpeakerColor と同じ。`app.js:1797`)。入口の外(単体。TOKEN が無い)では API が無いので色は出さない(今どおり)。
  見積もりが古い間の見本は行の話者、新しくなったら pack.py の話者、と切り替わるが、規則は同じなので通常は同じ色
- 終わりの条件: 3か所の字幕(映像の上・カット・パックの見本)が同じ話者で同じ色。実際のパックの Text+ の色(`editor/tests/e2e_edit_pack.py:99` の fills)とも合う

## 版の上げ方
- 編集: `editor/serve.py` の SERVER_VERSION・`app.js` の APP_VERSION・`README.txt` の見出しを同時に minor を1つ上げる(今は 0.21.0。前の段で上がっていればその次。始める前に WORKLOG と実ファイルで確かめる)。README の「変更」に4-1〜4-5
- cut2resolve: pack.py は読むだけ(cue_speakers を使う)で変えないので上げない。変える必要が出たら `cut2resolve_core.py` の VERSION と README を上げ、`python -m unittest cut2resolve/tests/test_cut2resolve.py cut2resolve/tests/test_pack.py cut2resolve/tests/test_serve.py` も流す
- 入口: `home/autorun.py` は変えない(記録に output が無いパックとして扱う)ので上げない

## 実機で確かめること
- パックのタブで縦 ↔ 横を切り替えると、字幕数と注意がすぐ新しくなる
- 粗編集の動画をオンにして start.bat を開き直しても、オンのまま・要約に出る。出力先は空欄で、作る場所が動画の隣
- 30fps で作ったあと 60fps に変えると、前回のパックに「fps: 30 → 60」と「ファイルは作ったときのまま」が出る
- 粗編集オンのまま zip を押すと、「粗編集の動画は zip に入りません」が出る。zip の中身は前と同じ
- 話者に名前(メンバー)を付けた文書で、映像の上・2 カット・パックの見本の字幕が同じ色。Resolve に入れた Text+ も同じ色

## 決まったこと(2026-09-29 ユーザー。計画を書いたあとに聞いた分)
- 「予備も入れる」も**覚える**(粗編集の動画つきと同じ扱い。「前回の設定」の要約にも出す)
