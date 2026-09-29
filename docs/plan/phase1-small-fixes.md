# 段1: 小さな直しと安全
> 状態(2026-09-29): 未着手。ホームからスタジオへの直行・引き出しの閉じ忘れ・声を覚えるの安全策・行のメニュー・Windows 以外のテストの飛ばし。
> 全体の計画は `docs/ROADMAP.md`。行番号は 2026-09-29 時点(始める前に今のコードで確かめ直す)。版の番号は、前の段で上がっていればそこから上げる。

## 目的
- 操作が止まる不具合(監査 01)と、評価用データの用途の矛盾(監査 02)を先に直す
- 「声を覚える」に混ざる声を減らす(監査 17・18。覚える対象を校正済みの行に絞り、覚える前に中身を見せ、一般名と既存名への追加を確かめる)
- 小さな導線の追加(B-8 ホームの案件からスタジオ、B-9 文字の欄で Shift+右クリック)
- クラウド(Linux)で単体テストが全部通る状態にする(Windows 前提の 5 件を飛ばす)

## 含む作業と順番
| # | 作業 | 大きさ | 依存 |
|---|---|---|---|
| 1 | B-8 ホームの案件の行に「スタジオで開く」(`?video=`) | S | なし |
| 2 | 監査01 引き出しを開いたままの Alt+数字 | S | なし |
| 3 | 監査02+17+18 声を覚える(評価用を断る・校正済みの行だけ・覚える前の確認・一般名・既存名の確認) | L | なし(編集の版上げは 3・4 でまとめて1回) |
| 4 | B-9 文字の欄の上の Shift+右クリックで行のメニュー | S | なし |
| 5 | Windows 以外でのテストの飛ばし(home 3件・編集 2件) | S | なし(最初にやってもよい。以後の確認が Linux で緑になる) |

## 各作業の細かい計画

### 1. B-8 ホームの案件の行からスタジオをその配信で開く
- 今の動き: 案件の行(`home/portal.html:185-222` の `tplCase`)にスタジオへのリンクは無い。切り抜きの行に「編集で開く」だけ(`home/portal.js:353-354`)。
  スタジオは `?video=<id>` を受け取り、保存済みの配信なら ③ 確認で開く(`studio/core.js:171-176`・`206-216`。id は `^[\w-]{1,64}$`)。案件の id = スタジオの動画の id(`home/cases.py:121,133`)
- 変えること: 行を開いた中の「状態」の行(`portal.html:198-200`)に `スタジオで開く` を置く。`caseCard`(`portal.js:436-`)で `link('スタジオで開く', '/studio/?video=' + encodeURIComponent(c.id))`(`portal.js:89` の `link()` = 新しいタブ・noopener)。
  `c.gone`(スタジオから消えた配信)のときは出さない(開いても ③ に行けず ① に落ちるため)。
  - 場所の作り方の案: (a) `/studio/` を直書き(`docHref` が `/transcribe/` を直書きしているのと同じ。簡単) / (b) `/api/status` の studio の `path`・`port` から作る(取り込めず子プロセスで動いたときも正しい)。
    子プロセスで動くのは取り込みに失敗したときだけなので (a) を採る。(b) は B-7 でまとめて見直すときの候補として WORKLOG に残す
- 変えるファイル: `home/portal.html`(ボタンの置き場所)・`home/portal.js`・`home/README.txt`・`home/launch.py`(版)
- テスト: `home/tests/e2e_portal.py` の [A](`:255-260` の行を開いたあと)に「`スタジオで開く` の href が `/studio/?video=e2eCase0001`」を足す。
  できれば新しいタブで開き `Studio.params.video === 'e2eCase0001'` を確かめる(YouTube の埋め込みの読み込みまでは見ない)。流す: ★`python home/tests/e2e_portal.py`、★`python -m unittest home/tests/test_launch.py home/tests/test_mount.py home/tests/test_cases.py home/tests/test_autorun.py home/tests/test_window.py`
- リスク・エッジケース: id は `encodeURIComponent` で入れる(スタジオ側も正規表現で弾く)。スタジオの画面がすでに別のタブで開いていても新しいタブになる(「編集で開く」と同じ動き)
- 終わりの条件: 案件の行を開くと「スタジオで開く」があり、押すとスタジオの ③ 確認でその配信が開く。消えた配信には出ない

### 2. 監査01 パックの設定を開いたまま Alt+1 で移ると、見えない引き出しが操作を塞ぐ
- 今の動き: タブの Alt+1/2/3 は `dialog[open]` だけを見ている(`editor/app.js:1928-1933`)。パックの設定 `#pkSettingsDrawer` は 3 パック の中(`index.html:1517`)にあり、
  modal で開く(`pack-tab.js:277`)と裏が `inert` になる(`ui-kit/ui-kit.js:475-488,505-513`)。タブを移ると親ごと隠れるが、`inert` は close まで残る(`ui-kit.js:521-531`)。
  ほかの文書のキーはすでに `.ui-drawer:not([hidden])` で止めている(`app.js:1938,1943,1972,2448`)。`hashchange`(`app.js:198`)・`setEditTab('cut')`(`:396`)からも同じことが起こり得る
- 変えること(2つとも行う):
  1. Alt+数字の処理(`app.js:1929`)に `document.querySelector('.ui-drawer:not([hidden])')` を足し、引き出しが開いている間はタブを変えない(ダイアログと同じ扱い。ほかのキーと規則をそろえる)
  2. `setEditTab`(`app.js:104-115`)で、隠れるタブ(`[data-edpanel]`)の中の開いている `.ui-drawer` を `UIKit.drawer.close()` で閉じてから隠す(戻る・# のリンク・プログラムからの切り替えでも `inert` を残さない)
  - 案の比較: Alt+数字で「閉じてから移る」も考えたが、Esc で閉じる動きがすでにあり、キーの意味をダイアログとそろえる方が覚えやすい。2 は保険(どの経路でも操作不能にしない)
- 変えるファイル: `editor/app.js`
- テスト: `editor/tests/e2e_edit_pack.py` の設定の引き出しの所(`:59-68`)に「開いたまま Alt+1 → タブは 3 パック のまま・引き出しは開いたまま」と
  「開いたまま `location.hash = '#tx'` → 引き出しが閉じ、`document.querySelector('[inert]')` が無く、1 文字起こしのボタンが押せる」を足す。
  ⚙ 設定(共通。body の直下)も開いて Alt+1 でタブが変わらないことを `editor/tests/e2e_edit_tabs.py`(`:108-` の ⚙ 設定の確認)に足す。流す: `editor/tests/e2e_edit_pack.py`・`editor/tests/e2e_edit_tabs.py`・`editor/tests/e2e_ui_mounted.py`
- リスク・エッジケース: 引き出しを閉じると `opener`(隠れたタブの `#pkSettingsBtn`)へフォーカスを戻そうとする(`ui-kit.js:529`)。隠れた要素へのフォーカスは効かないだけで害はないが、移った先のタブのボタンへフォーカスを置き直す(`opt.focus` と同じ)。
  ui-kit は触らない(写しの同期が要らない)
- 終わりの条件: パックの設定・⚙ 設定を開いた状態から、Alt+数字・戻る・# の変更のどれでも操作不能にならない(マウスとキーの両方で確かめる)

### 3. 監査02+17+18 声を覚える(評価用を断る・校正済みの行だけ・覚える前に見せる・一般名・既存名)
- 今の動き:
  - 画面: ボタンは「名前付きの話者がいる・部品がある・処理中でない」だけで有効(`app.js:817-821`)。押すとすぐジョブを追加(`app.js:841-849`)。評価用 `S.doc.evalSet` を見ていない
  - API: `validate_voice_learn`(`serve.py:3132-3145`)・`run_voice_learn`(`serve.py:3148-`)は evalSet を見ない。行は `voice_groups`(`serve.py:2985-3006`)= 1 秒以上・`MIXED_FLAG` でない行。
    校正済み(`proofed`)・行のメモ `TAGS = ("unclear","overlap","bgm")`(`serve.py:123`)を見ない。名前は `DEFAULT_SPK_NAME = ^話者\d+$`(`serve.py:2949`)以外は受ける
  - 同じ名前があれば、使った長さの重みで黙って混ぜる(`serve.py:3175-3181`)。取り消しは名前ごとの「忘れる」だけ
- 変えること:
  1. **評価用を断る(02)**: `validate_voice_learn` の先頭で `doc.get("evalSet") is True` なら `ApiError("eval_set", "評価用の文字起こしでは声を覚えません(評価用のデータを、ほかの文書の話者の名前付けに使わないため)。評価用を外してから行ってください", 400)`
    (再認識の断り方 `serve.py:4338-4339` と同じ形)。`run_voice_learn` でも読み直した文書で同じく断る(待機中に評価用へ変えた場合)。
    画面は `renderVoiceLearn` で評価用ならボタンを無効にし、ヒントに理由を出す(隠さない)。評価用の切り替え(`app.js:2227-`)でも `renderVoiceLearn()` を呼ぶ
  2. **覚える行を絞る(17)**: `voice_learn_groups(doc)` を新しく作り、覚えるときだけ使う: `voice_groups` の条件 + `proofed is True` + タグ `overlap`・`bgm`・`unclear` が無い行。
    **話者判別のときの照らし合わせ(`recognize_voices`・`serve.py:3107`)は `voice_groups` のまま変えない**(決定どおり)。除いた行の数を理由ごと(未校正・音のメモ・声が混ざる・1秒未満)に数えて返す
  3. **一般名を断る(18)**: `GENERIC_SPK_NAMES`(例: 本人・ゲスト・配信者・私・自分・相手・司会・MC・男性・女性・不明・その他・視聴者・ナレーション)と、仮名の形(`話者A`・`Speaker 1`・英字1文字 など)を
    `is_generic_speaker_name(name)` の1か所で判定(NFKC・大文字小文字・空白を寄せてから比べる)。一般名の話者は覚えない(理由「一般的な名前」として返す)。規則は serve.py だけに置き、画面は下の preview の結果を表示するだけ(二重に持たない)
  4. **覚える前に見せる(17)**: `GET /api/voices/preview?tid=&embedding=` を足す(読むだけ・ジョブを作らない)。返すもの:
    `people: [{name, speaker, rows, sec, exists, old: {rows, sec, updatedAt}|null}]`・`refused: [{name, reason: "generic"|"no_rows"}]`・`skipped: {unproofed, tagged, mixed, short}`・`evalSet`。
    画面は「声を覚える」を押すと preview を読み、確認ダイアログ(`confirmDlg`・`app.js:2707`)に「兎田ぺこら 12行・48秒 / 覚えない: 本人(一般的な名前。配信者の名前に変えてください)/ 使わなかった行: 未校正 20・音のメモ 3」を出す。
    - 別の案: 追加の API を作らず `POST /api/voices/learn {dryRun: true}` にする(入口が1つで済む)。フラグを落とした古い画面が本当に覚えてしまう危険があるので、読むだけの GET を分ける方を採る
  5. **既存名への追加を確かめる(18)**: preview で `exists` の人ごとに「『兎田ぺこら』の声はもう覚えています(30行・4分・9/27)。同じ人ですか」を確認し、「同じ人」のときだけ送る。
    API は `POST /api/voices/learn {tid, embedding, names:[覚える人], confirmSame:[既存の名前]}` にし、`names` に既存名があって `confirmSame` に無ければ `ApiError("confirm_same", …, 409, extra={"names": [...]})`。
    `names` が無い古い形の要求は 400(画面と API の版はそろえて上げるので互換は持たない)。`run_voice_learn` は `spec["names"]` との積だけを覚える(確認のあとで名前を付けた人を黙って覚えない)
- 変えるファイル: `editor/serve.py`(上の関数・GET の経路 `:5766` 付近・POST `:5888-5889`・先頭の API 一覧 `:15-17`)・`editor/app.js`(`:813-849`・評価用の切り替え)・`editor/index.html`(ヒントの文だけ。必要なら)・
  `editor/README.txt`(`:250-253` の説明)・`editor/AGENTS.md`(`:165-166` の「今は断っていない」を消し、覚える行の条件を書く)・`docs/plan/ui-audit-2026-09-28.md`・`docs/ROADMAP.md`
- テスト:
  - `editor/tests/test_voices.py`: `doc_with_speakers` に proofed・tags を渡せるようにし、既存の `test_learn_named_speakers_only_and_mix` は校正済みの行で作り直す。足す: 未校正・overlap/bgm/unclear・混ざりの行を覚えない / `recognize_voices` は未校正の行でも照らし合わせる(変えていない)/
    評価用は validate と run の両方で `eval_set` / 一般名(`本人`・全角の `ＭＣ`・`話者A`)は覚えない・全員一般名なら 400 / preview の人・行・秒・除いた数・exists / 既存名で `confirmSame` 無し → 409・有り → 混ぜる / 確認のあとで名前を付けた人は覚えない
  - `editor/tests/e2e_edit_voices.py`: 名前を付けた後、覚える前に行を校正済みにする(`Shift+Space` か行のボタン)。確認のダイアログに人・行・秒が出る / 2回目は「同じ人ですか」が出る / 評価用にするとボタンが無効でヒントに理由 / 名前を「本人」にすると覚えない案内 /
    API へ直接 `evalSet` の文書で POST すると 400(画面だけで止めていないことの確認)
  - 流す: `python -m unittest editor/tests/test_metrics.py editor/tests/test_resolve_export.py -q`・`editor/tests/e2e_edit_voices.py`・`editor/tests/e2e_eval_set.py`・`editor/tests/e2e_ui_mounted.py`
- リスク・エッジケース: 校正済みに絞ると覚えられる秒が大きく減る(校正前には押せなくなる)。0 行の人は「校正済みの行がありません」と出す(しきい値は足さない)。
  すでに一般名で覚えている声(例: 本人)は消さず、照らし合わせにも使われ続ける(判別側は変えない決定のため)。名前の表記ゆれ(`兎田 ぺこら`)は別人扱いのまま。
  preview と learn の間に文書が変わっても、learn の検査が正(409/400 をトーストで出す)。preview の GET は話者の名前を返すので、ほかの GET と同じ Host/Origin 検査の下に置く
- 終わりの条件: 評価用では画面・API の両方で覚えられない。覚える前に人・行・秒・除いた理由が見え、一般名は断られ、既存名への追加は確認してからだけ。判別時の名前付けの結果は変わらない

### 4. B-9 文字の欄の上で Shift+右クリックすると行のメニュー
- 今の動き: 行の右クリックのメニュー(`app.js:1678-1698`)は、文字・時刻の欄(`isTextEntry`・`app.js:1842`)の上では何もしない(`:1680`。ブラウザのコピー・貼り付けのメニュー)
- 変えること: `:1680` を `if (isTextEntry(e.target) && !e.shiftKey) return;` にする(普通の右クリックはブラウザのメニューのまま)。
  キーボードからの contextmenu(Shift+F10・アプリケーションキー)は `clientX/Y` が 0 になるので、そのときは行の位置(`row.getBoundingClientRect()`)の下に出す。
  「分割(カーソル位置)」は textarea の `selectionStart` を使う(`doSplit`・`app.js:2087-2090`)ので、右クリックした所ではなく入力中のカーソル位置で分かれることをメニューの文言のまま保つ
- 変えるファイル: `editor/app.js`・`editor/README.txt`(`:257` の右クリックの説明に1行)・キー一覧の案内(`#keys`)に「文字の欄では Shift+右クリック」
- テスト: `editor/tests/e2e_edit_tabs.py` の右クリックの確認(`:80-106`)に「textarea の上の右クリックはメニューを出さない(既定のまま)」「Shift+右クリックで出る・校正済みが効く」
  (`click(button="right", modifiers=["Shift"])`)。流す: `editor/tests/e2e_edit_tabs.py`・`editor/tests/e2e_proofread_accuracy.py`(行の操作)
- リスク・エッジケース: Firefox は Shift+右クリックでページの処理を無視して既定のメニューを出す(対象は Edge なので問題にしない。README に Edge/Chrome 向けと書く)。
  メニューを開くとフォーカスがメニューへ移り、textarea の IME の変換中の文字が確定することがある → `e.isComposing` 中は出さない
- 終わりの条件: 文字の欄で普通の右クリックはコピー・貼り付け、Shift+右クリックは行のメニュー。キーボードからも画面の中に出る

### 5. Windows 以外でのテストの飛ばし
- 今の動き(Linux で流して確かめた):
  - `home/tests/test_window.py` の `TestFocusWindow` のうち `test_finds_by_title_and_brings_to_front`・`test_not_found_or_refused`・`test_already_in_front` の3件が `ctypes.WINFUNCTYPE` が無くて落ちる(`home/appwindow.py:180`)。同じクラスの残り2件は通る
  - `editor/tests/test_edit.py` の `test_record_pack_and_stale`(`:155`。`..\\..\\x.txt` を名前だけにする処理が `\` を区切りと見ない)と `test_fill_doc_into_empty_document`(`:206`。`C:\\x\\clip.mp4` の normcase/abspath)が落ちる
- 変えること: その5件のテストだけに `@unittest.skipUnless(sys.platform == "win32" / os.name == "nt", "Windows の窓の API(WINFUNCTYPE)を使う" / "Windows のパス(\\ 区切り・C:\\)が前提")` を付ける。クラス全体には付けない(通る2件を残す)。
  - 案の比較: コード側(`appwindow.py`・serve.py のパスの扱い)を Linux でも動くように直す案もあるが、どちらも Windows だけで動く処理で、本番の動きを変える危険に見合わない → 飛ばすだけにする
- 変えるファイル: `home/tests/test_window.py`・`editor/tests/test_edit.py`・`editor/AGENTS.md`(`:84` の「Windows 以外では落ちる」→「飛ばす」)・`docs/ROADMAP.md` の 5
- テスト: Linux で ★`python -m unittest home/tests/test_launch.py home/tests/test_mount.py home/tests/test_cases.py home/tests/test_autorun.py home/tests/test_window.py` と `python -m unittest editor/tests/test_metrics.py editor/tests/test_resolve_export.py -q` が skip 5 で通る。PC(Windows)では skip 0 で通ること
- リスク・エッジケース: 飛ばしたテストは PC でしか確かめられない → WORKLOG に「PC で流す」を残す
- 終わりの条件: クラウドで単体テストが緑(飛ばしは 5 件だけ)

## 版の上げ方
- 入口: 0.12.0 → **0.12.1**(`home/launch.py:63` の VERSION・`home/README.txt` の見出しと変更の記録)。B-8 のため
- 編集: 0.21.0 → **0.22.0**(`editor/serve.py:100` の SERVER_VERSION・`app.js:3` の APP_VERSION・`README.txt` の見出し)。01・02/17/18・B-9 をまとめて1回。
  声を覚える API の形が変わる(`names`・`confirmSame`・preview)ので minor を上げる
- スタジオ・cut2resolve・ui-kit は変えない(版はそのまま)。テストだけの変更(5)は版を上げない
- 始める前に WORKLOG と実際のファイルで版がまだ 0.12.0 / 0.21.0 であることを確かめる(ほかの AI と番号を重ねない)

## 実機で確かめること
- ホームの案件を開き「スタジオで開く」→ Edge の専用の窓・普通のタブの両方で、その配信の ③ 確認が開く
- 3 パック の「設定を変える」を開いたまま Alt+1、ブラウザの戻る → 操作不能にならない。⚙ 設定も同じ
- 本物の sherpa-onnx で: 校正済みの行だけで声を覚え、確認のダイアログの行・秒が合う。2回目の「同じ人ですか」。次の話者判別で名前が付く(校正前の文書でも付く = 判別側は変えていない)
- 評価用の文書で「声を覚える」が押せず、理由が読める
- 文字の欄で右クリック(コピー・貼り付け)と Shift+右クリック(行のメニュー)。IME の変換中に押したとき
- PC で `home/tests/test_window.py`・`test_edit` が飛ばされずに通る

## 決まったこと(2026-09-29 ユーザー。計画を書いたあとに聞いた分)
- 一般の名前の一覧は上の案のとおり(本人・ゲスト・配信者・私・自分・相手・司会・MC・男性・女性・不明・その他・視聴者・ナレーション、と `話者A`・`Speaker 1`・英字1文字の形)
- すでに一般の名前で覚えている声は消さず、覚えた声の一覧に「一般的な名前です(忘れることをおすすめします)」と出す(1-3 に含める)
