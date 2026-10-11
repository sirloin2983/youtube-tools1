状態(2026-10-11): 作り方の計画(AI が決めた。仮)

# RS8: 新しい画面(案件の画面)の作り方

関連: 何を作るか `docs/design/briefs/rs8-cases/DESIGN_BRIEF.md`(見本 `mock/index.html`)・問答 `grill.md`・下調べ `inventory.md`・進め方 `plan/rs8-cases-ui.md`(決めたこと 4 = データが落ち着いてから新しい画面に替えて古い画面を消す)・画面が見る ② の口 `docs/design/rs8-flow-api.md`・`docs/spec/pipeline.md` 2.9・画面の決まり `docs/spec/ui-guidelines.md`・`usability-heuristics.md`・`ui-review-criteria.md`。
この文書は「どう作るか」だけ(何を作るかは brief)。コードは書いていない。

## 0. 要約(推奨)
| 問い | 推奨 |
| --- | --- |
| 1 組み込み方 | **(b) 部品化を 1 回でやる(iframe の段は置かない)**: 新しい 1 枚 `/cases` に、スタジオ ② と編集 1〜2 の JS を「パネル」(`mount(el, ctx)` / `update(ctx)` / `unmount()` の同じ口)に切り出して載せる。古い画面は切り替えまで触らず(凍結)、切り替えで消す |
| 2 置き場所と URL | `src/app/ui/cases/`(入口の直下の 1 枚 `/cases`。`/settings` と同じ配り方)。URL は `/cases?c=<案件 id>&d=<文書 id>#cand|proof|cut`。案件 id は ④ `/api/cases` の `id`(配信 id・動画ファイルは `file:<根の sha1 の先頭 12 字>`・仮の案件は `eval`・`orphan`)= 根のパスは URL に出ない。今の URL は入口が 302 で転送 |
| 3 ホーム | `portal.*` を作り直さず**組み替える**: やること(種類ごとの件数)・確かめる(V1 の枠 = 「あと何本」の表だけ先に・[始める] は押せない + 理由)・案件の一覧(行き先を `/cases` へ)・運用は `details` に畳む・新しい案件 = スタジオ ① `rank.js` をパネルにして引き出しで |
| 4 3 択 | 校正パネルの**行の中(インラインの比較欄)**。行の札「機械の結果が変わりました」→ 開くと 前の機械 / 今の機械 / あなたの直し の 3 本 + [自分の直しのまま] [今の機械にする]。案件の頭に「機械が変わった行 n」の飛び先。独立の画面・ダイアログは作らない |
| 5 段 | C0 ④ の下ごしらえ ∥ C1 殻 → C2a 候補 ∥ C2b-0 編集の下ごしらえ → C2b 校正(3 択も)∥ C2c カット・パック(worktree 3 本)→ C3 ホーム → C4 切り替え(転送・古い画面を消す・テストの整理・ui_audit・e2e 一式)。e2e は C1 で 1 本・C2 は近い旧 e2e を各 1 本移植・一式は C4 だけ。2.5〜3.5 日 |
| 6 ユーザーに聞く物 | 3 つ(7 節): 古い画面を消す時期(C4 で即 = 推奨)・編集の左メニュー「精度」「学習」の行き先・3 択の見た目(インライン) |

## 1. 組み込み方 = (b) パネル化(iframe は置かない)
### 1-1 今のコードの形(判断の材料)
| 事実 | 出典 |
| --- | --- |
| iframe の埋め込みは**設計として断っている**: `X-Frame-Options: DENY`・`frame-ancestors 'none'`・`Sec-Fetch-Dest` の検査。テスト 5 本が固定(`test_mount`:161・`test_launch`:580・`test_backend`:894・`test_serve`:128・`test_mount`:310) | `src/ytt/httpsec.py:8,27`・`src/home/mount.py:38,42` |
| CSP が画面ごとに違う(スタジオだけ YouTube の埋め込みを許す) | `mount.py:37-42` |
| JS は全部素の `<script>`(`type=module` なし)。**スタジオ**は 6 本が即時関数で包まれ、外に出るのは `window.Studio` だけ・② は `review.js` 3,634 行 = 状態 `S` 1 つ + 関数群・DOM は `#paneReview` に JS が描く・外の口は `Studio.review.open(id)`(:3502)= **部品化に近い**。**編集**は `app-*.js` 7 本が**包みなしのトップレベル**(`$`・`S`・`api`・`esc`・`EDT`・`CUT`・`PACK` を共有)・`index.html` 1,976 行 = インラインの CSS 約 1,290 行 + 直書きの HTML 約 660 行(メニュー・2 タブ・ダイアログ・ドリルの帯)= **部品化から遠い**。ただし `cut.js`・`pack-tab.js` は `EditCut.create(host)`・`EditPack.create(host)` の **host を渡す形が既にある**(パネルの口の原型) | `src/studio/index.html:42-47`・`core.js:7`・`review.js:104-389,3502`・`src/editor/index.html:9-1299,1300-1960,1966-1974`・`app.js:1258,1262` |
| keydown: スタジオは `document` 1 本(`review.js:3456`。`Studio.step`・`isTyping`・IME・overlay で除外)/ 編集は `window` 8 本 + `document` 1 本(`app.js:631`(capture で `stopImmediatePropagation`)・`:762-836`・`cut.js:1078`)。どちらも「今の欄」をグローバル(`Studio.step`・`EDT.tab`)で判定 = 同じページに 2 つ置くと Space を両方が受ける | 同左 |
| 切り替えの口はもうある: スタジオ `loadVideo(id)`(`review.js:615`)・編集 `openDoc(id, keep)`(`app-rows.js:116`)・`setTab(t)`(`app-jobs.js:8`)。URL は `replaceState` だけ(`app-core.js:122-128,176,197`・`core.js:280-285`) | 同左 |
| 文書の保存は `baseUpdatedAt` で 409 → `showConflict`(`app-core.js:118`)。2 つの窓で同じ文書を開いても壊れない仕組みは**既にある** | 同左 |
| API の URL は 1 か所(`Studio.api`・`apiUrl()`・`c2rUrl()`・`UIKit.http` が合言葉を付ける) | AGENTS「取り込みの決まり」・ui-kit v24 |
| V1「確かめる」は**行の編集・候補の再生・カットを案件の画面と共用する**と決めた | brief 2-3・`plan/rs8-cases-ui.md` 決めたこと 1 |

### 1-2 3 案の比べ
| | (a) iframe + postMessage | (b) パネル化(推奨) | (c) 段階 (a) → (b) |
| --- | --- | --- | --- |
| 守り | `frame-ancestors`・`X-Frame-Options`・`Sec-Fetch-Dest` を**緩める**(同一オリジンだけに)。テスト 5 本を書き換え | 変えない | 一度緩めて戻す |
| CSP・合言葉 | 親と子で 2 つの CSP。合言葉は子の meta に入口が入れる = 今のまま | 1 枚 1 CSP(YouTube を許す行をスタジオから持ってくる) | 両方 |
| キー操作 | フォーカスのある frame にしか届かない。「次の切り抜き」「Alt+1/2」は親 → 子へ postMessage で転送。`UIKit.keymap` が 2 つ | 1 つの keydown の入口(`cases.js`)が今のパネルに配る。`keymap` 1 つ | (a) の分が捨てになる |
| UIKit.life・toast・keybar・ヘッダー | 子にもヘッダー・帯・知らせが出る → 子の画面を**変える**(隠す)= 古い画面に手を入れる。A-28(3 画面のヘッダー同形)に引っかかる | 1 つ | — |
| URL の `#`・保存 | 親の URL と子の URL が二重。保存の 409 は今のまま | 1 つ。409 の案内もそのまま移植 | — |
| V1 の部品の共用 | **できない**(行の編集・再生が frame の中) | できる(パネルを確かめるのカードからも `mount`) | (b) まで待つ |
| 「古い画面を消す」(決めたこと 4) | 消せない(iframe の中身が古い画面) | 消せる | (b) で消す |
| 速さ | 最速(1 日)だが行き止まり | 殻 1 日 + パネル 3 本並列 1〜2 日 + 切り替え 1 日 | (a) 1 日が丸ごと捨て |
- **捨てた案 (d) 折衷(スタジオ ② はパネル・編集だけ iframe)**: 今のコードにはいちばん近い(編集の整理を後回しにできる)が、V1 の共用の相手は**まさに編集の行の編集**なので、いちばん要る部品が frame の中に残る。守りの緩め・キーの転送・ヘッダーの隠しも編集の分は全部要る = (a) の欠点がほぼそのまま。
- **なぜ (b)**: V1 の共用と「古い画面を消す」の 2 つの決定が (a)(d) と両立しない。守りを緩める変更は、1 人で使うローカルのツールでも AGENTS の【高】(同一オリジン化による XSS の影響拡大)の線上にある。(c) の (a) は 1 日分の捨て仕事になる。
- **(b) のやり方(移植であって書き直しではない)**: `review.js` の ② の部分・`app-rows.js` + `app-core.js` の行の編集・`cut.js` + `pack-tab.js` を、関数の中身はそのまま **1 つのオブジェクト(パネル)に包み、`window`/`document` 直の keydown と `$('#id')` の決め打ちを `ctx.root` の中に閉じる**だけ。ロジックの書き換えは「切り抜きを切り替える」(`openDoc`・`loadVideo` を `update(ctx)` から呼ぶ)に絞る。見た目・文言・キーは今のまま(brief 3-7・3-8)。
  - **編集だけは機械的な下ごしらえが先に要る**(C2b-0): (1) `index.html` のインライン CSS 約 1,290 行を `panels/proof.css` に外出し(`/* ui-kit:css */` の埋め込みはやめて `/ui-kit.css` を読む)・(2) 直書きの HTML 約 660 行のうち 1 文字起こしの欄とダイアログを JS のテンプレート(文字列)に・(3) `app-*.js` 7 本のトップレベルを 1 つの即時関数に包み `window.EditProof` だけ出す。この 3 つは**動きを変えない書き換え**なので Sonnet で先に 1 コミット。スタジオは済んでいる形。
  - **id の衝突**: 2 つの画面が `#toast`・`#keys`・`#player` のような同じ id を持つ見込み。パネルの中の `$` は `ctx.root.querySelector` に閉じ、`document.getElementById` を使わない(C1 の口で決める。lint に 1 行足す = `panels/` の中で `document.getElementById(` と `document.querySelector(` を禁止)。
- **凍結**: C1〜C4 の間、古い画面(`src/studio/*.js`・`src/editor/*.js`・`index.html`)に機能の直しを入れない(入れると 2 か所になる)。不具合は `plan/improvements.md` に積み、新しい画面で直す。

### 1-3 パネルの口(仮。C1 で決めて 3 本が同じ形で作る)
```
Panel = { id: 'cand'|'proof'|'cut',
          mount(el, ctx),      // el = 右の欄。ctx = {caseId, docId|null, videoId|null, item, status(② の jobs を案件で絞った物), api(UIKit.http の包み), onDone(次へ)}
          update(ctx),         // 左の一覧で別の物を選んだ・status が変わった(rev)
          unmount(),           // タブを離れる(再生を止め・保存を flush・keydown を外す)
          keys(e) -> bool,     // 殻の keydown から今のパネルに 1 回だけ渡す(入力中は殻が先に除く = UIKit.keys.isTyping)
          keybar() -> [{k,l}] }// 下の帯(UIKit.keybar)の中身
```
- 殻(`cases.js`)が持つ物: URL の読み書き(`replaceState`)・左の一覧(④ `/api/cases` の 1 件 + ② `status?case=` の突き合わせ)・タブ・「次の切り抜き」・`UIKit.life`(離れたら今のパネルの `unmount` でなく `pause` 相当 = 再生だけ止める。`'blur'` は保存だけ)・2 秒 / 15 秒の問い合わせ・keydown の 1 本。
- パネルが持たない物: ヘッダー・appnav・設定の ⚙・知らせの入れ物(殻が 1 つ)。
- 確かめる(V1)はこの同じ `Panel` を `mount` してカードに使う(行の編集 = `proof` の行 1 本だけを出す `opt.rows`、候補の再生 = `cand` の `opt.single`)。V1 の設計で足す引数はこの 2 つの見込み。

## 2. 置き場所・URL・識別子・転送
| 項目 | 決めたこと | 捨てた案 |
| --- | --- | --- |
| フォルダ | `src/app/ui/cases/`(`index.html`・`cases.css`・`cases.js`・`panels/cand.js`・`panels/proof.js`・`panels/cut.js`・`panels/machpick.js`)。`src/app/ui/` は RS6 で「入口と画面の層」として用意済み(今は空) | `src/home/`(入口の app の残りと混ざる。RS6 で入口の本体は `src/app/server.py` へ移った)/ 新しいツール `src/cases/`(取り込み・`.runtime`・`/api/ping` の約束が要るのに、持つ API は無い) |
| URL | `/cases`(入口の直下の 1 枚。`/settings` と同じ理由 = 相対パス `api/ytt/…` が入口の API を指す)。入口の静的ファイルは `server.py:559-563` の `STATIC`(URL の完全一致の表。`.html/.css/.js/.json` だけ)なので、`/cases`・`/cases.js`・`/cases.css`・`/cases-panels/<名前>.js`(`/cases/` で始めない)を表に足す。**変える場所 6 つ**: `STATIC`・`NAV_PAGES`(:564。無いと他画面からの移動が 403)・`/cases.html` の 302 先(:663)・`home/appwindow.py:36` の `PORTAL_PAGES`・`ui-kit.js:242` の `/cases.html` のリンク・`portal.js:2178` の `#cases`。入口の静的ページには `ytt-version` の meta が入らない(`server.py:676`)ので、版は `/settings` と同じく `api/status` から | `/cases/`(フォルダ)= `api/…` が `/cases/api/` を指す/ `/#case-<id>`(ホームの 1 枚に全部)= portal.js がさらに太る |
| 引数 | `?c=<案件 id>`・`?d=<文書 id>`(切り抜き 1 本 = 文書 1 本。B-2 で文書 id は変えないと決めた)・`#cand` / `#proof` / `#cut`(タブ。`#tx` `#cut` `#pack` は今の編集と同じ読み替え = `pack` は `cut` の末尾へ)。`d` だけでも開ける(殻が ④ に `?doc=` で案件を聞く) | `?root=<パス>`(根のパスを URL に出す = 個人の名前を含むパスが知らせ・履歴に残る・`encodeURIComponent` の長さ) |
| 案件 id | ④ `/api/cases` の `id`(今 = スタジオの配信 id。`cases.py:275`。`_check_case_id` = 英数字・`-`・`_` の 1〜64 字)。動画ファイルの案件は `case.json` の id をそのまま(`flow/placement._case_id` = `f-<パスの sha1 の先頭 16 桁>`。既にある形を使う)・仮の案件は `eval`・`orphan`(brief 3-3・3-4)。C0 で行に **`root`**(今は無い。掲示板の `case` との突き合わせの鍵。`roots[配信 id]` を出すだけ)と `kind` を足す | 根のパスそのまま / 題名(重なる・変わる)/ 新しい id の体系(`case.json` と二重になる) |
| 今の URL の転送(brief 3-6。入口の 302) | `/studio/?video=X` → `/cases?c=X#cand` / `/studio/?step=rank`・`/studio/?url=…` → `/#new`(ホームの新しい案件。`url` は引数のまま渡す)/ `/studio/`(引数なし)→ `/` / `/transcribe/?doc=T[#tab]` → `/cases?d=T#tab` / `/transcribe/?media=P`・`?clip=P` → 入口が `/transcribe/api/doc-for` で文書を引いて `/cases?d=T#proof`(無ければ `/#new?media=P` = 新しい案件の動画ファイルの欄)/ `/transcribe/?drill=1` → `/cases?c=eval#proof` / `/transcribe/?list=…` → `/` / `/cases.html`・`/#cases` → `/`(今の 302 の先を直す。`server.py:663-664`) | 画面側(JS)での転送(古い JS を残すことになる) |
| 旧いパスの残し方 | `mount.py` の取り込みは**API だけ**残す(`/studio/api/*`・`/transcribe/api/*`・`/cut2resolve/api/*`。識別子・URL は変えない = AGENTS の互換)。ページ(`/studio/`・`/transcribe/` の HTML・JS・CSS)は配らず 302。`live/` の `/live/` → `/studio/` の 302 は `/cases` へ | — |

## 3. ホーム(入口)の作り替えの範囲と V1 の枠
`portal.js` 2,272 行は「案件」と「運用」が混ざっている。作り直さず、**節を組み替えて行き先を変える**(見た目の部品は今のまま = 見直し §11 の home の残りは一緒に片付ける)。
| 節(brief 2-1) | やること | 読む口 |
| --- | --- | --- |
| LIVE の帯 | `UIKit.liveBadge.get()` から録画中の案件の行を 1 本(「この案件を開く」= `/cases?c=<録画 id>#cand`) | 今のまま |
| やること | 今の「次にやること」(最大 5 件・行き先が 2 ツール)を**種類ごとの件数**(採用待ち・校正待ち・パック待ち・失敗)に。押すといちばん古い 1 件の `/cases?…#tab`。件数の計算は ④ `/api/cases` の集計(`cases.py` に `todo: {adopt, proof, pack, failed}` を足す = 画面で数えない)。失敗は ② `status` の `jobs` の `error` | ④ + ② |
| 確かめる(V1 の枠) | カード 1 枚: 今の `goalsRow`(`/api/accuracy`。`portal.js:1654-1680`)を「今いちばん効く確認 + あと何本」の形に置き直す。**[始める] は `disabled` + 理由「確かめるの画面は V1 で入ります」**(押せない理由を出す決まり)。V1 で `/check` を足すとき、このカードの中身だけ替える。今の「続けて確認」(`#rvDrawer`)は V1 の 1 枚目のカードになるので**RS8 では残す**(行き先のボタンだけ `/cases` へ) | 今のまま |
| 案件の一覧 | 今の一覧 + 列「切り抜き / 校正 / パック」(④ の集計)・末尾に仮の案件 2 行・行の行き先を `/cases?c=`。`[+ 新しい案件(URL・探す)]` = スタジオ ① の `rank.js` + `queue.js` を `panels/new.js` にして `UIKit.drawer`(modal)で開く(解析の待ちは ② の `an:` を掲示板から)。`UIKit.hide` の一覧名は今の `cases` | ④ + ② |
| 運用 | 受付・バックアップ・まとめて実行の記録・調子・まとめて実行の設定を `details.card.ops` に畳む(DOM はそのまま動かすだけ) | 今のまま |
- ホームのヘッダーの appnav(ホーム / スタジオ / 編集)は**「ホーム / 案件 / 設定」の形に変える**(スタジオ・編集の入口が無くなるため。`UIKit.appnav` の表と A-28 の検査を同時に直す = C4)。
- 作り直さない理由: 運用の節(受付・バックアップ・履歴・調子)は 1 行も変わらない。作り直すと e2e 4 本(`e2e_intake_ui`・`e2e_backup_ui`・`e2e_portal`・`e2e_window`)の足場(DOM の id)を全部直すことになる。

## 4. 3 択の画面(O2-4 の口)の置き場
- **校正パネルの行の中**: 行の印 `MACH_CHANGED` のある行に札「機械の結果が変わりました」(brief 見本の `warn` の札)。札を押す(キー: 行を選んで `Shift+?` は V1 と重なるので C2b で `keymap` に 1 つ登録)と、行の下に比較欄が開く: 前の機械 / 今の機械 / あなたの直し の 3 本(`GET /transcribe/api/mach-changes?id=&row=` の `before`・`now`・`human`)+ [自分の直しのまま](既定・primary)[今の機械にする](`POST …/pick {id,row,pick,baseUpdatedAt}`)。409(別の所で変わった・層が正でない)は欄の中に「何が・次にどうする」。
- 案件の頭(brief の「確かめると効く物 n 件」の横)に「機械が変わった行 n」= 押すと最初の印の行へ(`rows` の一覧は同じ口の `row` なし)。
- **層が primary でなければ札も頭の数字も出さない**(`layers` の値で判定。今は shadow = 画面は何も変わらない。primary への切り替えは別の決定 3-39)。
- 捨てた案: 独立の画面 `/mach`(行の文脈 = 前後の行と音が無いと選べない)/ `UIKit.dialog.choose`(ボタンの文字だけで 3 本の本文を比べられない。`choose` は 3 択以上の**確認**の部品)。
- 置き場所のコード: `panels/machpick.js`(校正パネルから呼ぶ小さな部品。V1 のカード「どちらの読みが正しいか」と同じ見た目 `alt-pair` を使う = 共用の 1 つ目)。

## 5. 作る段(1 段 = 1 コミットのまとまり + テスト)
| 段 | 中身 | 触る所 | テスト | モデル | 並列 |
| --- | --- | --- | --- | --- | --- |
| C0 ④ の下ごしらえ | `/api/cases` に `root`・`kind`・仮の案件 2 行(`eval`・`orphan`)・動画ファイルの案件 `file:`・切り抜きごとの状態(未・校正中・校正済み・パック済み = 文書の `proofed` の割合と `pack_info`)・`todo` の件数。`GET /api/cases?doc=<tid>` で 1 件を引く。転送の表(2 節)を `server.py` に(先に入れても今の画面には無害 = 旧 URL は今のページを返したまま、C4 でスイッチ) | `src/manage/cases/cases.py`・`src/app/server.py`・`txindex` は読むだけ | `test_cases`・`test_launch`(転送は C4 まで `off`) | Sonnet | C1 と同時 |
| C1 殻 | `src/app/ui/cases/`: 配り(`server.py` の表・CSP = 編集の物 + YouTube の 2 行・`NAV_PAGES`)・ヘッダー(appnav・版・⚙)・URL の読み書き・左の一覧(④ + ② の突き合わせ・進み具合の札・`rev` で描き直さない)・タブ・「次の未校正の切り抜き」(ボタン + キー)・空の状態(2 文 + ボタン)・失敗(何が / 次に)・`Panel` の口と**空のパネル 3 つ**(文字だけ)・`UIKit.life`・keydown 1 本。見本の CSS(`mock/index.html` の `.rail`・`.pane`)を `cases.css` に(見本の `onclick=` は使わない = A-02) | `src/app/ui/cases/*`・`src/app/server.py`・`src/ui-kit/`(新しい部品 `.ui-rail`・`.ui-rail-item` を足して `sync_ui_kit`) | 新規 `src/app/tests/test_cases_page.py`(配り・CSP・302 なし)・**e2e 1 本 `src/app/tests/e2e_cases.py`**(殻だけ: 開く・一覧・タブ・URL・キー)・`dev/tests/test_layering`・`test_mount`(同じ名前の .py = `cases.py` は manage にある → 画面側のテストの名前は `test_cases_page`) | Opus(入口・CSP・URL = 影響が広い) | C0 と同時。終わったら C2 の 3 本へ `Panel` の口を渡す |
| C2a 候補パネル | `review.js` の ② + LIVE の帯 → `panels/cand.js`(プレーヤー YouTube / video・タイムライン・マークの一覧・採用 / 不採用・候補をすべて採用・書き出しの引き出し・LivePlayer)。`Studio.api` → `ctx.api`(`/studio/api/…`)。書き出しの進み具合は ② `ex:` | `panels/cand.js`・`cases.css` | `e2e_cases_cand.py`(旧 `e2e_ui.py` の ② の場面から移植。1 本)・`test_review.cjs` は旧のまま(C4 で移す) | Opus(3,634 行・LIVE の状態が多い) | worktree |
| C2b-0 編集の下ごしらえ | 動きを変えない書き換え 3 つ(1-2): CSS の外出し・1 文字起こしの HTML をテンプレートに・`app-*.js` を 1 つの即時関数に。**旧い画面のまま動くことを旧 e2e で確かめる**(`e2e_edit_tabs`・`e2e_proofread_keys` の 2 本。凍結の唯一の例外) | `src/editor/index.html`・`app-*.js` | 旧 e2e 2 本・`test_document_save.cjs` | Sonnet | C2a と同時(C2b の前) |
| C2b 校正パネル + 3 択 | 編集 1 の行の編集(`app-rows`・`app-core` の保存と 409・`app-tools` の行の道具・話者・札・`?drill=1` の帯 = 仮の案件 `eval` の頭に)→ `panels/proof.js`。小さい配信プレーヤー(brief 2-2。`cand` のプレーヤーを `opt.mini` で再利用。今の編集に配信のプレーヤーは無い = 新しく載せる物はこれだけ)。3 択 `panels/machpick.js`(4 節) | `panels/proof.js`・`panels/machpick.js` | `e2e_cases_proof.py`(旧 `e2e_proofread_keys` + `e2e_row_editing` の要点を 1 本に)・`test_machpick` は旧のまま | Opus(保存・競合・キーの衝突) | worktree(C2b-0 のあと) |
| C2c カット・パック | `cut.js` + `pack-tab.js` → `panels/cut.js`(すでに分かれている。`c2rUrl()` → `ctx.api`。決定 3-34 パックの「予備」を消す・「3 パック」の古い文言を直す) | `panels/cut.js` | `e2e_cases_cut.py`(旧 `e2e_edit_cut` + `e2e_edit_pack` の要点を 1 本に)・`test_resolve_pack_contract` 単独 | Sonnet(規則の移植) | worktree |
| C3 ホーム | 3 節の組み替え(やること・確かめるの枠・一覧の列と行き先・運用を畳む・新しい案件 `panels/new.js` = `rank.js` + `queue.js` の移植) | `src/home/portal.*`・`panels/new.js` | `e2e_portal`(直す)・`e2e_autorun`(行き先)・`test_launch` | Sonnet(DOM の組み替え)。`new.js` の移植は C2 と同じ人が続けてよい | C2 のあと(殻の `Panel` を使う) |
| C4 切り替え(1 コミットに) | 転送を on・`mount.py` でページを配らず API だけ・`src/studio/` の画面ファイル(`index.html`・`*.js`・`*.css`)と `src/editor/` の画面ファイル(`index.html`・`app*.js`・`cut.js`・`pack-tab.js`・`ui-kit.js`)を `git rm`・`UIKit.appnav` を「ホーム / 案件 / 設定」に・`sync_ui_kit.py` の写し先(スタジオ・編集)を消す(入口の画面は正本 `/ui-kit.js`・`/ui-kit.css` を直に読む = 写しは要らない。`test_ui_kit_sync` も)・`ui_audit.py` の `SCREENS`(`studio`・`editor` を消し `home` に `cases` の 4 ファイル)・`MOUNTED`(A-01 の対象。`/studio/` `/transcribe/` を直に書かない検査は新しい画面にも当てる = `cases` を足す)・`default_scenes` を新しい画面に・`run_e2e.py` の SUITE(消す e2e・足す e2e)・`test_review.cjs` → `test_cand_panel.cjs`(読む先を `panels/cand.js`)・`test_document_save.cjs` の読む先・旧 e2e 20 本の整理(下の表)・`AGENTS.md` の表・`README.txt`・版を上げる | 上の全部 | **e2e 一式 `py -3.10 dev/run_e2e.py`**(大きな区切り)・`py -3.10 dev/ui_audit.py all --demo` Must 0・`lint` 0・層の検査 | Opus(入口・取り込み・テストの地形 = 影響が広い) | 単独(サブエージェントが止まってから = e2e が揺れないため) |
- 見積もり(AI の実績に合わせて短く): C0 + C1 半日・C2(C2b-0 を含む)並列 1〜1.5 日・C3 半日・C4 半日〜1 日 = **2.5〜3.5 日**。
- 3 択の口は入口でなく**編集のサーバー**(`/transcribe/api/mach-changes`・`…/pick`。`editor/serve.py:283,342`)。印は行の `flag` 欄に「、」区切りで入る(`layers.py:31`)。今の編集の画面はこの印の専用の見せ方を持たない = 新しい画面で初めてつなぐ。
- **e2e は少なめの決まり**との合わせ方: 足すのは殻 1 本 + パネル 3 本 + 新しい案件(C3 で `e2e_portal` に足す)= 4 本。代わりに旧い編集の e2e 15 本・スタジオの `e2e_ui` 2 回・`e2e_ui_mounted` が消える(一式は 31 → 約 20 本・ライブ 2 本は残る)。各段では自分の 1 本だけ流す。一式は C4 だけ。
- **古い画面を消すのは C4**(1 コミット)。理由: C2 の間は古い画面で普段の作業ができる(決めたこと 4)・消すのを別の段に分けると「新しい画面はできたのに古い e2e が残って一式 18 分」の期間ができる。消す前に `test_run_e2e`(e2e の入れ忘れの検査)・`ui_audit` の `SCREENS`・cjs の読む先を同じコミットで直す。
- **並列の約束**: C2 の 3 本は `panels/<名前>.js` と自分の e2e だけを触る。`cases.css`・`cases.js` を直したくなったら殻の持ち主(まとめ役)へ `SendMessage`(worktree は古いコミットから始まるので最初に ff)。ui-kit の正本を触るのは殻だけ。
- **ui_audit の Must 0**: C1 で `SCREENS["home"]` に `cases` のファイルを**足し**(旧 3 画面は C4 まで残す)、C1〜C3 の各段で `py -3.10 dev/ui_audit.py static` を 0 に。`all --demo`(Playwright の場面)は C4 で場面の表を新しい画面に書き換えてから。見本のデータ `demo_env.py` に仮の案件・動画ファイルの案件を 1 件ずつ足す(C0)。

### 旧 e2e の行き先(C4 で整理。`dev/run_e2e.py` の SUITE と `test_run_e2e` を同時に直す)
| 旧 | 行き先 |
| --- | --- |
| editor: `e2e_ui_mounted`・`edit_tabs`・`edit_cut`・`edit_pack`・`row_editing`・`proofread_keys`・`follow_scroll`・`edit_voices` | `e2e_cases_proof` / `e2e_cases_cut` に要点を移して消す |
| editor: `proofread_accuracy`・`folder_marker_range`・`eval_set`・`drill`・`alt`・`fill`・`ui_handoff` | 中身が API 寄りの物は unittest に落とす(`human/proof/tests`)。画面の分は `e2e_cases_proof` の場面に。`drill` は仮の案件 `eval` の場面 |
| studio: `e2e_ui`(2 回)・`e2e_review`(NOT_IN_SUITE) | `e2e_cases_cand` と C3 の新しい案件(`e2e_portal`)へ。`e2e_analyze` は API なのでそのまま |
| home: `e2e_portal`・`e2e_autorun`・`e2e_window`・`e2e_keymap`・`e2e_live_studio`・`e2e_live_archive` | 直す(行き先の URL・`/studio/` → `/cases`)。ライブ 2 本は `#cand` のライブの見た目 |
| home: `e2e_settings`・`e2e_intake_ui`・`e2e_backup_ui`・`e2e_live`・dev 2 本・ui-kit 1 本 | そのまま |

## 6. 守りと決まりの当て方(新しい画面で変えない物)
- CSP `script-src 'self' https://www.youtube.com https://s.ytimg.com; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`(スタジオの物をそのまま。インラインの `<script>`・`onclick=` なし)。合言葉は入口が meta に入れ `UIKit.http` が付ける(画面に書かない)。Host / Origin 検査は `httpsec` の 1 か所のまま。
- 画面は**相対パス**で読み(`cases.js`・`panels/…`)、API は `ctx.api(tool, path)` の 1 か所で `studio/api/…`・`transcribe/api/…`・`cut2resolve/api/…`・`api/…`(入口)を組む(A-01)。
- 同じ名前の .py を作らない: 画面のテストは `test_cases_page.py`(`manage/cases/cases.py`・`test_cases.py` と重ねない)。
- 進み具合は ② `GET /api/flow/status?case=<root>` だけ(2.9)。案件の中身は ④・人の操作は ③ の今の口。画面側で `cases` と `status` を `root` で突き合わせる。
- `UIKit.life`: `'hidden'` で再生を止め・`'blur'` は保存だけ。`UIKit.keys.isTyping` を殻で 1 回。キーは今の割り当て(`UIKit.keymap` は編集の `actions` + スタジオの `actions` を 1 つの表に。重なり(S・W・Q の例外)は `ui-guidelines` 2-3 のまま = タブが違えば別の意味でよい既存の 3 つだけ)。足すキー: 「次の切り抜き」1 つ(AI が決める。既定は `Shift+N` の見込み = `PB_BLOCKED` に足す)。
- 新しい部品(左の一覧 `.ui-rail`・比較欄 `.ui-pair`)は ui-kit の正本に足して `sync_ui_kit`。見本の `mock/index.html` の CSS は参考にして写すだけ(見本は残す = 設計の記録)。

## 7. ユーザーに確かめる物(一時の形でない物だけ)
1. **古い画面を消す時期 = C4 で即**(推奨。URL は転送・データは変わらない・`git` に残る)。代案 = 数日並走(旧ページも配る)。並走は 2 か所に不具合が出る期間を作るので推奨しない。
2. **編集の左メニューの行き先**: 新規 → ホームの「新しい案件」・履歴 → 案件の一覧、で消える。**「精度」(評価の一括・精度の表)と「学習」(置換の提案の管理)** は (a) ホームの運用に畳む(推奨。毎日は見ない)/ (b) 案件 `eval` の頭に置く / (c) V1 の確かめるの中、のどれか。
3. **3 択の見た目 = 校正の行の中のインライン比較欄**(4 節。ダイアログでなく、前後の行と音を見ながら選ぶ形)。
- AI が仮で決めて進める物(確認は要らない): `Panel` の口の形・URL の引数名(`c`・`d`)・案件 id の形(`file:`・`eval`・`orphan`)・ホームの appnav の 3 項目・「次の切り抜き」のキー・e2e の本数と行き先・各段のモデル・ui-kit の部品名。`plan/decisions.md` の「仮で決めたこと」と `plan/data.js` の `userTasks.provisional` に 1 行ずつ(実装の段で)。
