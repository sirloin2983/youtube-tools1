# 画面(UI)の見直しの合格の基準(2026-10-07)

> 状態(2026-10-07): **規則**。ユーザー指示「全ての UI 関係の見直し。基準を作成して、それに合格するまでループする。サブエージェントと相談して判断して」で作った。
> 作り方: まとめ役(Claude Code)の案 + 相談役(Opus)の案(A 25・B 17・誤検出 20 例・決まりを変える提案 8)+ 画面の地図(Explore)を突き合わせて決めた。基準を変えるときはこの文書と `dev/ui_audit.py` を同時に直す(`docs/spec/code-quality.md` と同じ形)。
> 土台: `docs/spec/ui-guidelines.md`(画面の決まり)・`docs/spec/usability-heuristics.md`(Nielsen の 10 原則)・`docs/design/briefs/ui-overhaul/DESIGN_BRIEF.md`(見た目の方針)・`docs/design/briefs/ux-consistency/DESIGN_BRIEF.md`(動きの方針)・`src/ui-kit/README.md`・Vercel の Web Interface Guidelines(一般の作法。このツール群に合うものだけ)。
> 対象: ホーム(`src/home/portal.html`)・切り抜きスタジオ(`src/studio/`)・編集(`src/editor/`)・共通部品(`src/ui-kit/`)。cut2resolve は画面が無い。対象外: 線 D の録画の画面(既定でオフ・試験中)・friend-apps(WinForms)。

使う人は Web の開発者だが動画編集は初心者。**「次に何をすればいいか」が画面だけで分かる**ことを一番に見る。

## 0. 合格の定義と繰り返し方
- **合格** = 次の 3 つ。
  1. ゲート: 各ツールの単体・e2e(`AGENTS.md` の表)と `dev/lint.py` 0 件が通る
  2. (A) `py -3.10 dev/ui_audit.py all --demo --shots <フォルダ>` の **Must が 0 件**(例外は理由つきの `allow` だけ。4 を参照)
  3. (B) 見直し役(ホーム / スタジオ / 編集 の 3 人 + まとめ役の横断)の **Must が 0 件**
- Should は直せるものは直し、残りは `plan/improvements.md` の「UI の見直しの残り」に 1 行 1 件(ID・場面・何が・大きさ)で残す。
- 繰り返し: 測る(A・B)→ 直す(担当のファイルを分ける。ui-kit は正本を直して `dev/sync_ui_kit.py`)→ ゲート → もう一度測る。**上限 3 周**。2 周目からの見直し役は前の周の一覧を受け取り、まず「直ったか」を判定する。2 周目以降に新しく Must にしてよいのは、直したことで起きた退行と、前の周に無かった画面だけ(それ以外の新しい指摘は Should)。3 周しても残った Must はユーザーに写真で見せて決めてもらう。
- 場面の表(1 の末尾)と見本のデータ(`dev/demo_env.py --seed 7`)は固定する。場面を足すのは基準の改訂として扱う。1 周目の前に今の件数を測って残す(`docs/WORKLOG.md`)。
- **重さの決め方**(見直し役が 1 件ずつ付ける。Must は、項目 ID・場面・判定の文のどこに当たるか・写真の名前かセレクタ、の 4 つがそろった指摘だけ。そろわなければまとめ役が Should に落とす):
  - **Must**: 操作ができない・次の一歩が分からない・`ui-guidelines` の決まりに反する・キーボードやコントラストなどアクセシビリティの失敗・設計書(ブリーフ)との大きな食い違い
  - **Should**: 不一致(言葉・形・場所)・足りない状態(空・失敗・処理中)・狭い幅での崩れ
  - **Could**: 磨き(間隔・文字・動き)
- **直しの線引き**: 属性(aria・title・label)・色の値・大きさ・文言の直しは確認なしで進める。並び・流れを変える直し、ボタンを減らす・移す直しは設計の変更なので仮で決めて `plan/decisions.md` の「仮で決めたこと」に並べ、終わりにまとめて確認する(ユーザー指示「合格するまでループする」= 止めずに進める)。
- 測る場所: 自動の検査はクラウド(Linux。Segoe UI・Cascadia Mono が無いので英数字の幅が少し違う)でも流せる。幅に関わる項目(A-20・A-30・A-36)の最終の判定は、できればユーザーの Windows でも流す(結果が違えば Windows を正とする)。

## 1. 機械で測る基準(A。`dev/ui_audit.py`。見本のデータの上で、場面 × 幅 390 / 960 / 1440(主な作業の場面は 1920 も)× 明(アイスライト)・暗(ネオンシアン)。文字「大きい」は 390 / 960 で はみ出し・縦割れ だけ)
`static` はコードを読むだけ(サーバー不要)。`live` は Playwright で場面を開いて測る。終了コードは Must が 1 件でもあれば 1。報告は場面ごとの件数と「場面を除いて一意の数」(直す量の目安)の両方を出す。

| ID | 基準 | 測り方 | 重さ | 根拠 |
| --- | --- | --- | --- | --- |
| A-01 | 取り込まれる画面(studio・editor)が絶対パスを直に書かず、要求は自分の場所の中(取り込みの場所 `/studio/` `/transcribe/` `/cut2resolve/`・ホームの API `/api/`・録画 `/live/`)だけ。API・動画の URL は 1 か所の関数(`Studio.api`・`apiUrl()`・`c2rUrl()`・`UIKit.tools.base()`)で作る | 静的: JS の `fetch(`・`href=`・`src=`・`location`・`window.open(`・`EventSource(` と HTML の `src/href/action` に `"/` で始まる文字列が無い(関数へ渡す `'/api/…'` と、ホームへの `a[data-ui-portal]` は可)。実行時: 取り込んだ状態で出た同じサーバーへの要求の path が上の場所の中 | Must | AGENTS.md「取り込みの決まり」 |
| A-02 | インラインの `<script>`・`on〇〇=` 属性が無い(CSP `script-src 'self'`) | HTML の grep。実行時の CSP 違反は A-27 で数える | Must | AGENTS.md |
| A-03 | ブラウザの `confirm`/`alert`/`prompt` を使わない(`UIKit.dialog`) | JS の grep(コメント・文字列を除く) | Must | ui-guidelines 2-2 |
| A-05 | `visibilitychange` を直接使わない(`UIKit.life`)。ui-kit が無いときの保険(直前の行で `UIKit.life` / `if (life)` を見ている)は可 | JS の grep | Must | AGENTS.md |
| A-06 | ツールの `serve.py` に `/api/ytt/` を作らない | grep | Must | AGENTS.md |
| A-07 | `outline:none` でフォーカスの輪を消さない(同じ規則に `box-shadow` か、同じセレクタの `:focus-visible` の規則があれば可。見えるかは A-26 で測る) | CSS の grep(ui-kit は正本だけ) | Must | ui-guidelines 6・WIG「Focus」 |
| A-08 | ツールの CSS/JS に固定の色(`#hex`・`rgb()`・`white`/`black`)を書かない(トークン `var(--…)`) | CSS の値と JS の `style.color =` などの grep(トークンの定義行 `--x: #…`・`url()` は除く) | Should(1 件ずつ判断。字幕の縁取り・幕の黒のように両テーマで同じでよい色は allow) | ui-overhaul ブリーフ「Colors」・ui-kit README |
| A-09 | 用語集の「使わない言葉」(ストリーム・トランスクリプト・セグメント・クリップ・パッケージ・プリセット・入口・ポータル・一括実行・ショートカット など)が画面の文言に無い | HTML の文と属性(title・placeholder・aria-label・alt・data-ui-why)・JS の文字列・ホームの画面に出る .py の文字列(docstring・コメント・launch.py の argparse・backup.py の CLI は除く)。「動画」「削除」「更新」「ショート」は別の意味で使うので人が見る(B-04) | Must | ui-guidelines 1 |
| A-10 | 絵文字・記号のアイコン(☰ ⚙ ✂ ✓ ▶ ▾ ▸ ⋮ × ↶ ↷ など)を文言・ボタンの名前に使わない(SVG の `UIKit.icon`)。可: 矢印 ← → ↑ ↓(kbd・「A → B」の文)・①〜⑤(今をマーク。ユーザー決定)・数字の横の ×(0.5×・1080×1920) | 同上 | Must | ui-overhaul ブリーフ「Anti-references」(決定 P-6: ▾ ▸ も SVG に) |
| A-11 | `ui-kit.css` に `prefers-reduced-motion` で全部の動きを止める節がある(各ツールはこれに乗る) | grep | Must | ui-overhaul ブリーフ「Accessibility」 |
| A-12 | `<html lang>`・`<title>`・`<meta viewport>` がある | HTML の grep | Must | WIG「Accessibility」 |
| A-13 | `transition: all` を書かない | CSS の grep | Must(決まりの文書に無い一般論だが、今 0 件なので壊れたときに気づく用) | WIG「Animation」 |
| A-14 | ui-kit の写しが正本と同じ | `dev/sync_ui_kit.py --check` | Must | ui-kit/README |
| A-15 | 専門用語(EDL・Text+・FCPXML・LUFS・CER)を出す画面に `abbr.ui-term` の説明がある | HTML の grep(1 画面に 1 つあれば可) | Should | ui-guidelines 1 |
| A-20 | 横にはみ出さない | `scrollWidth ≤ 窓の幅 + 1` を全場面・全幅・両テーマ・文字「大きい」で | Must | ui-guidelines 6 |
| A-21 | 押せる部品(button・input・select・textarea・summary・role=button・a.btn)は高さ 28px 以上(幅も。checkbox・radio は 16px) | 見える要素の高さ・幅(`::before/::after` で広げた当たり判定も数える。キーの帯は除く) | Must | ui-guidelines 6(決定 P-7 の書き方) |
| A-22 | 文字と背景のコントラスト 4.5:1 以上(24px 以上・太字 18.66px 以上は 3:1) | 見える文字ごとに、文字の中心の点に重なる要素(`elementsFromPoint`)を上から合成した背景と比べる。色は `rgb()` と `color(srgb …)`(color-mix の結果)を読む。opacity は文字の alpha に掛ける。除く: disabled・aria-disabled・placeholder・aria-hidden・option・背景画像や映像の上・字幕の見本(`.tt-cap-*`。仕上がりの見た目)・知らせ・画面の外 | Must(明・暗)。鋼の白・ターミナルグリーンは Should(`--variants` で任意) | ui-guidelines 6(決定 P-4: `--ink-4` は placeholder・空の欄・押せない物・飾りにだけ) |
| A-23 | 押せる部品(button・a[href]・summary・role=button)に名前がある。記号だけの名前(× … ▾)は不可 | 文字(aria-hidden の子は除く・sr-only は含む)・aria-label・aria-labelledby・title・img の alt | Must | WIG「Accessibility」 |
| A-24 | 入力欄(input・select・textarea)に label(for / 包む)か aria-label・aria-labelledby・title がある(placeholder だけは不可) | DOM | Must | WIG「Forms」 |
| A-25 | `cursor:pointer` の要素は Tab で届く(button・a[href]・input・summary・tabindex ≥ 0 か、その中。label の中も可) | DOM。マウスだけの便利(タイムラインのクリックで移動 など)は `data-ui-audit-allow="A-25"` に「キーでは何で代わるか」を添える | Must | ui-guidelines 6「キーボードだけで全部」 |
| A-26 | Tab で移った要素にフォーカスの輪が見える(outline か box-shadow か、枠の色の変化) | 1440 明で Tab を 60 回まで押して見る | Must | ui-guidelines 6 |
| A-27 | 画面の読み込み・場面を開く操作でエラーが出ない(pageerror・console.error・同じサーバーへの要求の 4xx/5xx・CSP 違反。録画の部品が無いときの `/live/api/info` の 404 と、外のサイト(YouTube の埋め込み)の失敗は除く) | Playwright | Must | AGENTS.md(画面のエラーの記録)・原則 9 |
| A-28 | 3 画面のヘッダーに同じ部品が同じ順にある: `nav[data-ui-appnav]` → `.ui-ver` → `.ui-header-actions`(その右端が `[data-ui-settings]`) | DOM | Must | ui-guidelines 2(決定 P-1: [テーマ] は v14 で消えた) |
| A-29 | 文の中以外のリンク(`a`)も 28px 以上 | A-21 と同じ | Should | ui-guidelines 6 |
| A-30 | 文字が 1 文字ずつ縦に割れない | 390・960 で、3 文字以上の文字のノードの行の数(`Range.getClientRects()` の top の種類)が文字の数以上なら不可 | Must | ui-guidelines 6(`.lag.keep`) |
| A-31 | 重ねる欄の約束: ⚙ 設定の引き出し・? のキー操作の一覧・パックの詳しい設定・スタジオの書き出し(1680 未満)は、開いたらフォーカスが中・Tab を 30 回押しても外へ出ない・`aria-modal=true`(dialog は showModal)・Esc で閉じる・閉じたら開いたボタンへ戻る。1680 以上の書き出し(docked)は閉じ込めない | Playwright で開いて押す | Must | ui-guidelines 2-2・ui-overhaul ブリーフ「Accessibility」・ui-kit v6 |
| A-32 | ずっと動き続ける表示は回転の輪・読み込み中(`.ui-spin`・`.pill.run`・`.ui-skel`・indet)だけ。`prefers-reduced-motion` で 1 ms より長い動きが走っていない | `document.getAnimations()`(通常と reduce の両方) | Must | ui-overhaul ブリーフ「Accessibility」 |
| A-33 | 状態の札(`.pill`)は押せない(button・a・role=button・tabindex・cursor:pointer でない) | DOM | Must | ui-guidelines 3 |
| A-34 | 押せない部品(disabled・aria-disabled)に理由(title・data-ui-why・aria-describedby)がある | DOM | Should | ux ブリーフ「理由のない無効をなくす」・ui-kit v21 |
| A-35 | 1 つの入れ物(card・section・dialog・drawer・pop・details・form)に `.btn.primary` は 1 つ | DOM | Should | ui-guidelines 3 |
| A-36 | 切れている文字(`text-overflow` / `overflow:hidden` で `scrollWidth > clientWidth`)に title か aria-label がある | DOM(`.sr-only` は除く) | Should | ui-guidelines 4 |

**場面**(`dev/ui_audit.py` の `default_scenes`。固定): ホーム(開いた直後・案件の行を開く・絞り込みで 0 件・詳しく・設定)/ スタジオ ①・②・③(配信なし・配信 `demo0000000`・書き出しの欄・配信を選ぶ・キー操作・設定)/ 編集(空・1 文字起こし・「まとめて」・「…」・2 カット・3 パック・詳しい設定・キー操作・設定)/ ui-kit の見本(styleguide)。1920 はホーム・スタジオ ③・編集 1 と 2。
副作用のあるボタン(すべて終了・片付け・実行・窓で開く)は押さない。見本の文字起こしは「行があって評価用でない 1 件目」。
処理中・失敗の場面(まとめて実行の進み具合・失敗の帯)は見本では作れないので、B-03・B-11 で見直し役がコードと疑似モードで見る。

## 2. 人(見直し役)が見る基準(B。A の `--shots` の写真と DOM・コードを見て、1 件ずつ Must / Should / Could を付ける)
見直し役が受け取るもの: 写真(場面 × 幅 × テーマ)・この文書・画面の地図(場面の開き方)・A の結果。返す形: 1 件 1 行で「項目 ID・場面・重さ・何が・どこ(ファイル:行 か 写真の名前・セレクタ)・判定の文のどこに当たるか・直し方の案」。良い所も 3 つまで。

| ID | 基準 | 見方・判定(合格の条件) | 根拠 |
| --- | --- | --- | --- |
| B-01 | **次の一歩が画面だけで分かる**: 各場面に主な操作(`primary`)が 1 つ、次にやること(`.ui-next`/`.ui-next-btn`)か完了の知らせのボタン([開く][2 カットへ][フォルダを開く][編集で開く])がある | 写真を見て「次に押すもの」を 1 つ言える。言えない・同じ強さの候補が 2 つ以上あって迷う なら Must | heuristics 1・6、ux ブリーフ「結果と理由を必ず見せる」 |
| B-02 | **空の状態**は 2 文(「まだ〇〇はありません」+「〇〇すると、ここに出ます」)と次のボタン 1 つ | 一覧・タブ・欄が空のときの表示を全部見る(見本の「絞り込みで 0 件」も)。文だけ・ボタン無しは Must | ui-guidelines 5、ux ブリーフ「空の状態」 |
| B-03 | **失敗の文**は「何が起きたか」+「どうすればいいか」。技術的な原文(例外の名前・HTTP の番号・JSON・スタックトレース・内部のパス)は畳んだ `details` か title にだけ。問題が起きた場所の近くに出る | 画面の `showErr`・`toast(kind:'err')`・`notice`・サーバーの `ApiError` の文を読む。次の一歩が無い失敗は Must | heuristics 9、ui-guidelines 5 |
| B-04 | **用語**は用語集どおり(A-09 で見ない「動画」(配信のことに使わない)「削除」(行を消す操作だけ)「更新」(作り直しに使わない)「ショート」の使い分けも)。内部の言葉(API・JSON・ID・拡張子・関数名・英語の状態名)が本文に無い。専門用語の初出に `abbr.ui-term`。新しい言葉は用語集に足す | 画面の文言を読む。意味が逆に読める語(「残す」が外す意味になる など)は Must、ゆれは Should | ui-guidelines 1、heuristics 2 |
| B-05 | **同じことは同じ言葉・同じ形・同じ場所**: 同じ操作のボタンを 2 か所に置かない(1 つの状態を変える入口は 1 か所)。わざと入口を複数にしているもの(まとめて実行の 8 入口・キー配置の ? と ⚙・ホームへ戻る)は名前・部品・既定値・結果が同じ。状態の言葉(待ち・実行中・済み・飛ばした・失敗・中止)。保存の状態はヘッダーの 1 か所 | 3 画面を横に並べて比べる(まとめ役の横断でも)。名前・形・動きが違えば Should、結果が違えば Must | heuristics 4、ux ブリーフ「入口は複数でも中身は 1 つ」 |
| B-06 | **ヘッダー**の並び: `ui-appnav` → 版 → 段のタブ → 右寄せで [ツールの操作(アイコン + 文字、多くて 3)] → [キー操作] → [⚙ 設定]。実行中の札は点滅しない | 3 画面のヘッダーを見比べる。並びの違い・4 つ以上の操作は Should | ui-guidelines 2 |
| B-07 | **ボタンと札**: 種類は `primary` / 普通・`ghost` / `danger`(確認つき)の 3 つ。`primary` は 1 つの欄に 1 つ(A-35)。札(`.pill`)は押せない表示だけ(A-33)、押せるものは必ず `.btn`。色の意味(ok = 済み・動作中 / wait = まだ / run = 実行中 / warn / err / info)と言葉(済み・まだ・実行中・注意・失敗) | 画面ごとに primary の数と、押せる札を探す。押せる札・確認の無い danger は Must | ui-guidelines 3 |
| B-08 | **段階的に見せる・主役が大きい**: 1440 で主役(ホーム = 次にやること・案件 / スタジオ ③ = プレーヤー・盛り上がり・マーク / 編集 = 映像と行・タイムライン・パックの要約と「作る」)が画面の大半。詳しい設定は `details.ui-disclosure`。まだ使えない欄は閉じるか「〜すると使えます」。同じ情報を 1 画面に二度出さない | 初期表示に設定の欄・使えない欄が並んでいないか。二重の情報は Should | ui-guidelines 5、heuristics 8、ui-overhaul ブリーフ principle 1 |
| B-09 | **一覧**: 上に `.ui-listbar`(検索・絞り込み・並び替え・件数)。1 件 1 行で高さをそろえ、詳しい中身は開いたときだけ。1 枚の紙(外枠 1 つ・行の間は細い線。1 件ごとの角丸・枠・影にしない)。同じ題名が並んでも だれの・いつの(配信者・`UIKit.fmt.ago`)で見分けられる。次にやることは 1 つ。フルパスを常に出さない(長い名前は末尾が見える)。200 件でも重くない | ホームの案件・次にやること・編集の履歴・スタジオ ① の結果・③ の配信を選ぶ・マークの一覧 | ui-guidelines 4 |
| B-10 | **取り消しと確認**: 取り消せる操作は確認しない(知らせの [元に戻す]・Ctrl+Z)。取り消せない操作(消す・上書き・止める・すべて終了)だけ `danger` の見た目で `UIKit.dialog.confirm`(最初のフォーカスはキャンセル)か二度押し。確認の連打・画面ごとに作った確認が無い | 消す・上書き・止める の全部の経路を押す。確認の無い取り消せない操作は Must | heuristics 3・5、ui-guidelines 2-2・3 |
| B-11 | **処理の状態**: 重い処理(解析・書き出し・文字起こし・パック・まとめて実行)に進み具合(数字か棒)と何をしているか。終わったら何ができたかと次の一歩。失敗したら理由と [やり直す]。何もしなかったときは「完了」と言わない | 疑似モードで処理を始めて見る(コードでも)。進み具合が無い・終わりが分からないは Must | heuristics 1、ux ブリーフ 3 |
| B-12 | **押せない理由**: 押せない操作は隠さず押せない形で見せ、近くか押したときに理由と「押せるようにする一手」が分かる(A-34 の文が日本語として理由になっているか) | disabled・hidden の要素を探し、理由が出るか押す | heuristics 5、ux ブリーフ「理由のない無効をなくす」 |
| B-13 | **キー**: 単体キーが基本。入力欄では効かない。よく使うボタンに `kbd.ui-kbd`。下の帯に場面に合ったキーが 5〜7 個。1 つのキーは全体で 1 つの意味(例外は S・W・Q)。? の一覧 = 設定。一覧・帯・ボタンの横は今の割り当てから作る | キー操作の一覧と帯とボタンの横を見比べる | ui-guidelines 2-3 |
| B-14 | **狭い幅**: 960 と 1440 で崩れない(重なって読めない・切れて意味が分からない・押せる部品が隠れる が無い)。390 で横にはみ出さず、文字が縦に割れない(A-20・A-30)。390 では主作業(一覧・プレーヤー)に早く届く順に並び、設定は閉じている | 写真(390・960・1440・1920)を見る。操作できないは Must、並びの順は Should | ui-guidelines 6、ux ブリーフ「Responsive」 |
| B-15 | **見た目の方針**(落ち着いた仕事道具): 灰色の段階で面を分け、強調色は意味(primary・選択中・今の行・フォーカス)にだけ。1 画面に強調色のボタンが並ばない。飾りの影・グラデーション・角丸のカードの並び・ネオンの光が無い。SVG の線のアイコン 1 種類。時刻は等幅 `tabular-nums`。間隔はトークン(`--sp-*`)の値 | 写真を見て、ブリーフの Anti-references(SaaS のダッシュボード・ネオン・文字記号のアイコン・強調色の並び)に当たる所を探す。当たれば Should(文字記号は A-10 で Must)。強調色は配色ごと(アイスライトの青・ネオンシアン。ブリーフの「紫」は v12 より前の値 = 決定 P-3) | ui-overhaul ブリーフ「Aesthetic Direction」 |
| B-16 | **暗いテーマ**: 両テーマで読める。映像の周りは `--stage-bg`。固定の色(A-08)が残るなら両テーマで意味があること。影は暗いテーマで濃く | 暗い写真を全部見る。読めない所は Must | ui-guidelines 6 |
| B-17 | **フォーカスの流れ**: ダイアログ・引き出しの約束(A-31)に加えて、完了のあとは次に打つ所へ。押したボタンが無効になるときは次の操作へ移す(フォーカスを失わない) | キーボードだけで 1 つの作業(文字起こし → 校正 → カット → パック)を通す。`document.activeElement` を見る | ui-overhaul ブリーフ「Accessibility」、ux ブリーフ |
| B-18 | **設定**: ⚙ の 1 か所(「このツール」+「全体」)。今の値が見える。保存の失敗が見える(知らせ + [もう一度]) | 設定を開いて値を変え、失敗を起こして見る | ui-guidelines 2-2、ux ブリーフ「保存の失敗」 |
| B-19 | **覚える・自動で入れる**: 覚えるものの表(ux ブリーフ 5)どおりに前回の値が入る。自動で入れた値には理由(「自動」「前回」)が見え、1 手で直せる。パックの前回の設定・まとめて実行の要約 1 行 | 画面を閉じて開き直す。値が戻れば Should | heuristics 6、ux ブリーフ「聞くのは一度だけ」 |
| B-20 | **文の作法**: 能動の文。数は数字。ボタンの名前は何をするかが分かる(「続ける」より「パックを作る」)。省略は `…`(`...` でない)。読み込み中は `…` で終える。hint は 2 文まで、長い説明は手順の形 | 文言を読む。ゆれは Could | WIG「Content & Copy」「Typography」、heuristics 10 |
| B-21 | **色だけで意味を伝えない**: 状態・話者・自動/前回・押せる/押せないが、色のほかに文字か形でも分かる(話者の色の丸の横に名前、札に文字) | 全場面 | ux ブリーフ「Accessibility」 |

見直し役の分け方: ホーム / スタジオ / 編集 の 3 人(写真と自分の画面のコードを見る)。横断(B-05・B-06・B-15 の画面の間の食い違い)はまとめ役が 3 画面の写真を並べて見る。

## 3. 今回決めたこと(相談役の質問への答え。仮決め。`plan/decisions.md` にも並べる)
1. コントラスト(A-22)は明(アイスライト)・暗(ネオンシアン)を Must、鋼の白・ターミナルグリーンは Should。`--ink-4`(面に対して 3.2〜3.8:1)は placeholder・空の欄・押せない物・飾りにだけ使い、情報の文字(行の時刻・カット済の行)には使わない(P-4 を採用。`ui-guidelines` 6 に書く)
2. 文字記号(▾ ▸ ⋮ ×)も SVG に替えて A-10 を Must にする(P-6 を採用。ブリーフの Anti-references が ▾ を名指ししているため)。用語集の「まとめて ▾」は「まとめて(メニュー)」に書き直す
3. 入力欄の枠とフォーカスの輪の 3:1(P-5)は今回は入れない(トークンの値が変わり、静かな見た目を変えるので要確認)。`plan/improvements.md` に Should で残す
4. 測る場所: このクラウド(Linux)で測って合格を判定する。幅に関わる項目は、できればユーザーの Windows で `py -3.10 dev/ui_audit.py all --demo` をもう一度流す(結果が違えば Windows を正)
5. 見直し役は 3 人 + まとめ役の横断。上限 3 周。2 周目以降の新しい Must は退行か新しい画面だけ
6. 例外は行の印(`ui-audit: allow A-xx <理由>`・`data-ui-audit-allow`)で書く(理由がコードの横に残る)。中央の一覧(`dev/ui_allow.json`)は作らない
7. ヘッダーの決まり(`ui-guidelines` 2)の [テーマ] は v14 で消えたので文書を直す(P-1)。幅は 390・960・1440(+1920)(P-2)。「タップする部品は 28px 以上」は「押せる部品は高さ 28px 以上(アイコンだけのものは幅も)。文中のリンクと label に包まれた checkbox は除く。当たり判定は見た目より広げてよい」に書き直す(P-7)

## 4. このツール群に合わないので採らない一般論(理由)
| 一般論 | 入れない理由 |
| --- | --- |
| モバイルファースト・スマホ向けの工夫・320px/400% の組み替え | PC の窓で使う前提(ui-overhaul ブリーフ「Responsive」「Out of Scope」)。390 は「はみ出さない・縦に割れない」だけ |
| タップの大きさ 44px・本文 16px | 28px・12.5〜14px と決めている(ui-guidelines 6・ui-overhaul「Typography」)。大きくしたい人は設定の「文字の大きさ」 |
| `autocomplete`・`inputmode`・`preconnect`・画像の `loading=lazy`・大きい一覧の仮想化 | ローカルのツールで、外の資源・ログイン・画像の一覧が無い。一覧は「絞り込んだ分だけ描く・もっと見る」(ui-guidelines 4) |
| 見出しの Title Case・curly quotes | 日本語の画面 |
| 送るボタンはいつも押せるままにして押したら失敗を出す型 | 「押せない理由がある操作は押せなくして理由を出す」(heuristics 5)の逆 |
| 危ない操作は全部確認する | 「取り消せる操作は確認しない(元に戻す)」(ux ブリーフ)と決めている |
| スクリーンリーダーの全部の流れ・ランドマークの完全な監査・スキップリンク | 使う人は画面を見てキーボードで使う 1 人。名前・ラベル・重ねる欄の約束(A-23・A-24・A-31)だけ |
| 暗いテーマを既定に・AAA(7:1)・Lighthouse の点数 | ユーザー決定(明るい既定)。目的が違う |

## 5. 今回の値(2026-10-07。1 周目の前)
`dev/ui_audit.py all`(クラウドの Linux・見本のデータ・場面 23 × 幅 3〜4 × 明・暗 + 文字大)の最初の測定: **Must 704 件・Should 217 件(場面を除いて一意 144)**。
内訳(一意): A-07 2・A-08 21(Should)・A-09 5・A-10 44・A-20 1・A-21 13・A-22 15・A-24 9・A-25 7・A-29 4(Should)・A-31 3・A-32 2・A-34 7(Should)・A-35 1(Should)・A-36 10(Should)。
(その前の測り方では閉じたメニューの中身まで数えて Must 3003 件だった。閉じた details の中身は `checkVisibility` で除くように直した)
見直し役の Must / Should の数と、周ごとの推移は `docs/WORKLOG.md` と `docs/design/briefs/ux-consistency/DESIGN_REVIEW.md` に書く。

**結果(2026-10-07。3 周で合格)**: A は Must 704 → 9(2 周目)→ **0**(3 周目。Should 38・一意 13 = 見本ページ 5 とスタジオの固定の色 8 だけ)。B は見直し役の Must ホーム 10・スタジオ 9・編集 9 → 0。ゲート OK。以後、画面を変えたら `py -3.10 dev/ui_audit.py all --demo` を Must 0 件にする(`AGENTS.md` の表)。
