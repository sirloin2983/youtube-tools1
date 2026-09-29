# 段7: ホロカラーの色を全員調べ直す(B-10)
> 状態(2026-09-29): 未着手。全員の公式の色を調べ直し、1人に複数の色を持てる形にして、あとからユーザーが自分で直せるようにする
> 全体の計画は `docs/ROADMAP.md`。行番号は 2026-09-29 時点(始める前に今のコードで確かめ直す)。版の番号は、前の段で上がっていればそこから上げる。

## 目的
- 今の `holo-colors/members.json` は 86 人・1人1色(`hex`)。多くのメンバーは公式の色が2色以上あるのに1色しか持てず、出典どうしで色合いが大きく違う4人(アキ・ローゼンタール・角巻わため・アイラニ・イオフィフティーン・九十九佐命)は片方を捨てている(`docs/holo-colors.md` の「メンバーの色」)
- 全員を決まった手順で調べ直し、**出どころ・確かさを色ごとに記録**する
- 1人に複数の色を持てるようにする。ただし**字幕の色(`ytt_core/colors.py`)と以前の exe(1.2.1)は今までどおり動く**(主な色 = `hex` を残す)
- ユーザー(と友人)が**アプリの画面からメンバーの色を直せる**ようにする。直した色は作業データに置き、members.json を差し替えても消えない

## 含む作業と順番
| # | 作業 | 大きさ | 依存 |
| --- | --- | --- | --- |
| 7-1 | members.json の形を決める(複数の色・出どころ・主な色)と、両方の読み手の互換 | S | なし |
| 7-2 | 調べ方の手順書と記録の置き場所(`docs/holo-colors-research.md`) | S | 7-1 |
| 7-3 | 全員を調べる(グループごと。Web で調べるのはこの作業の中) | L | 7-2 |
| 7-4 | C# の読み込みと検索(`Core.cs`)を複数の色に対応 | M | 7-1 |
| 7-5 | 一覧の札で2つ目以降の色を見せてコピーできるようにする(`PaletteView.cs`・`MainForm.cs`) | M | 7-4 |
| 7-6 | ユーザーが色を直す(`member-colors.json`。画面の「色を直す…」) | M | 7-4 |
| 7-7 | `ytt_core/colors.py` を新しい形と直した色に対応(字幕の色 = 主な色) | S | 7-1, 7-6 の形 |
| 7-8 | テスト・README・設計の文書・版 | S | 7-3〜7-7 |

7-4〜7-7 は形(7-1)が決まれば 7-3 と並べて進められる。7-3 の結果は最後に members.json へまとめて入れる(途中の半端な一覧を友人に配らない)。

## 各作業の細かい計画

### 7-1 members.json の形
- 今の動き: 1人 = `{"id","name","en","hex","src":[出典id],"alt":["#xxxxxx 説明 (s4)"],"note"?,"confidence"?}`(`holo-colors/members.json`)。C# は `hex` が読めないと FormatException で全体を読まない(`holo-colors/src/Core.cs:443-446`)。`colors.py` は `hex` だけ読む(`ytt_core/colors.py:78-98`)。`alt` はどちらも読まない
- 変えること: 1人に `colors` を足す。`hex` は**主な色**として残す(`colors[0].hex` と同じ値にする。テストで一致を確かめる)
  ```json
  {"id": "tsunomaki-watame", "name": "角巻わため", "en": "...", "hex": "#F9AFB2",
   "colors": [{"hex": "#F9AFB2", "label": "ホロジュール", "src": ["s1","s2"], "confidence": "high"},
              {"hex": "#DBDA89", "label": "公式サイトの画像", "src": ["s4"], "confidence": "medium"}],
   "alt": ["#... 採らなかった候補と理由 (s7)"], "checked": "2026-10-xx"}
  ```
  - `label` は画面に出す短い名前(12 文字まで)。`confidence` は high / medium / low(7-2 の基準)。`checked` = 調べ直した日
  - `alt` は「照らし合わせたが採らなかった候補」の意味のまま残す(色を直すときの材料)
  - 最上位の `version` を 2 に。`sources` の各項目に `retrieved`(取得日)と、あれば `archive`(Wayback の URL)を足す
- 案の比較: (a) `hex` を残して `colors` を足す(採用)… 1.2.1 の exe と今の colors.py が新しい members.json をそのまま読める。友人が members.json だけ差し替えても落ちない。値が2か所に出る代わりにテストで一致を守る。(b) `hex` を消して `colors` だけ … きれいだが古い exe が全員読めなくなる(`Core.cs:445` で throw)
- 変えるファイル: `holo-colors/members.json`(形だけ先に。中身は 7-3)、`docs/holo-colors.md`
- テスト: 7-8 にまとめる
- リスク: `colors` の最初と `hex` の食い違い → C# と Python の両方のテストで検査。id は今 `グループid/メンバーid` でしか重なりを見ていない(`Core.cs:458`)→ 直した色のキー(7-6)に使うので**メンバー id を全体で一意**にする検査を足す
- 終わりの条件: 形を `docs/holo-colors.md` に書き、1.2.1 の exe(build 済み)で新しい形の見本が読めることを確かめた

### 7-2 調べ方の手順書と記録
- 今の動き: 出典は `sources`(s1〜s12・g1〜)で、主はホロジュールのアイコン枠の色(s1・s2)。公式サイトの画像の色(s4)や wiki(s3・s7)は照らし合わせ(`docs/holo-colors.md` の「メンバーの色」)
- 変えること: `docs/holo-colors-research.md` に手順と、1人1行の記録の表(候補の色 / 出典 / 採った・採らない / 理由)を作る
  - **出典の順位**: ① 公式の明示(本人・カバーの公式アカウントの「メンバーカラー」の発言、公式グッズ・公式ライブのペンライトの色の案内、公式サイトのプロフィール)② ホロジュール(カバー運営)の枠の色 ③ 公式サイトの画像から取った色 ④ 非公式の wiki・まとめ(照らし合わせだけ。これだけでは採らない)
  - **確かさ**: high = ①か②で色コードが直接取れた・②が複数の保存版で同じ、medium = 画像から取った色・①が色の名前だけ(例「水色」)で色コードを当てた、low = ④だけ・出典どうしで食い違う
  - 画像から取るときの決まり: 縁や JPEG のにじみを避け、平らな部分の中央値を取る。取った場所を記録に書く。**画像そのものはリポジトリに入れない**(Public のため・著作物のため。URL と取得日だけ)
  - ペンライトの色は名前で示されることが多い → `label` に名前(「ペンライト: 水色」)を書き、色コードは近いものを当てて medium
  - 残すもの: 各出典の URL・取得日・Wayback の保存版(あれば)。ページが消えても確かめ直せるように
- 変えるファイル: `docs/holo-colors-research.md`(新規)、`docs/holo-colors.md`(手順へのリンク)、`docs/ROADMAP.md` の索引(6)
- テスト: なし(文書)
- リスク: 非公式の表が互いに写し合っている(s5 と s6 は独立でない、と既に記録あり)→ 独立でない出典を2つと数えない決まりを書く
- 終わりの条件: 手順書ができ、1グループ(0期生)で試しに記録を取って手順が回ることを確かめた

### 7-3 全員を調べる
- 今の動き: 86 人・20 グループ(`members.json`)。confidence medium 6 人・low 2 人。人見クリスは色が見つからず入れていない(`docs/holo-colors.md`)
- 変えること: 7-2 の手順でグループごとに調べ、`docs/holo-colors-research.md` に記録 → members.json の `colors`・`hex`・`alt`・`checked` を直す
  - 主な色(`hex`)は**今の色を変えない**のが既定(字幕の色が急に変わらないように)。変えたほうがよい人は一覧にしてユーザーに聞く(下の「聞くこと」)
  - 食い違いの4人は、両方の色を `colors` に入れる(どちらが主かはユーザーに聞く)
  - 人見クリスも改めて探す。卒業生の区分・日付は今の記録のまま(調べるのは色)
  - 調べている間に名簿の差(新しいデビュー・卒業)に気づいたら記録し、足すかはユーザーに聞く(この段の目的は色)
  - グループごとに区切って WORKLOG と中間報告(20 グループ。1回に数グループ)
- 変えるファイル: `holo-colors/members.json`、`docs/holo-colors-research.md`
- テスト: 7-8 の形の検査(C# の BundledMembers・`ytt_core/test_ytt_core.py`)をグループごとに流す
- リスク: Web の取得が拒まれる・保存版が無い → 「確かめられなかった」と記録し、確かさを下げる(推測で埋めない)。ホロジュールは最近配信した人しか出ない(既知)。作業量が大きいので、途中で止めても一覧が壊れない順(1グループ書いたら検査を通す)にする
- 終わりの条件: 全員に `checked` と1色以上の `colors` があり、どの色にも出典と確かさがある。記録の表が全員分ある

### 7-4 C# の読み込みと検索
- 今の動き: `ColorEntry` は `Hex` 1つ(`Core.cs:24-34`)。`Palette.Load` が `hex` を読む(`Core.cs:425-463`)。検索のキーは名前・ローマ字・グループ・メモ・`Hex`(`Core.cs:142-146`)
- 変えること: `ColorEntry` に `List<ColorOption> Colors`(`Hex`・`Label`)を足す(C# 5 で書ける形。`Hex` は主な色のまま)。`Load` は `colors` があれば読み、壊れた項目は飛ばす(`hex` が読めない人は今までどおりエラー)。`colors` が無い古い members.json は `Hex` 1つの `Colors` を作る。検索のキーに全部の色コードと `Label` を入れる
- 変えるファイル: `holo-colors/src/Core.cs`
- テスト: `CoreTests.cs` に「colors を読む・無い形も読む・壊れた色は飛ばす・2つ目の色コードで検索が当たる・メンバー id が全体で一意」を足す。BundledMembers に「`colors[0]` = `hex`」
- リスク: C# 5 の制限(`?.`・`$""`・`=>` のメンバー・自動プロパティの初期化子は使えない。`docs/holo-colors.md` の「ファイル」)。マイカラーは今までどおり1色(`Store.MakeEntry` は `Colors` に1つ入れる)
- 終わりの条件: build.bat が通り、今の members.json と新しい形の両方を読める

### 7-5 札で2つ目以降の色を見せる・コピーする
- 今の動き: 札は1色で、名前と色コードを描く(`PaletteView.cs:219-247`)。札の大きさは `tileH = S(46)`(`PaletteView.cs:119`)。右クリックのメニューは「コピー」「この色をもとにマイカラーへ追加…」(`MainForm.cs:300-319`)
- 変えること:
  - 色が2つ以上ある札は、右下に小さな色の四角(ほかの色)を並べる。四角を押すとその色をコピー(札の本体は今までどおり主な色)。当たり判定は `HitTest` を札と四角の2段にする
  - 右クリックのメニューに色ごとの「コピー #xxxxxx(ラベル)」を並べる。ツールチップにも全部の色とラベル
  - キーの操作(↑↓←→・Enter)は主な色のまま(覚え直しを増やさない)
- 案の比較: (a) 札の中の小さな四角(採用)… 一覧の人数・並びが変わらない。小さいので押しにくい → 右クリックのメニューでも同じことができるようにする。(b) 色ごとに札を分ける … 押しやすいが一覧が倍近くに伸び、検索の結果も同じ人が並ぶ
- 変えるファイル: `holo-colors/src/PaletteView.cs`、`holo-colors/src/MainForm.cs`、`holo-colors/src/Program.cs`(コピーを色の指定つきにする)
- テスト: `CoreTests.cs` の PaletteLayout に「四角の位置が札の中・四角の当たりはその色・スクロールしても一緒に動く」を足す(PaletteScrollDrawing の画素の比較も四角ありの札で)。`python holo-colors/e2e_holo_colors.py` に「四角を押すとその色がコピーされる」を1件足す
- リスク: 札が狭い(DPI 100%・細い窓)と四角が名前に重なる → 名前を先に省略(`EndEllipsis`)し、四角は最大 3 つ + 「+n」。白に近い色の四角は縁を付ける(札と同じ)
- 終わりの条件: 2色以上の人の四角でその色がコピーされ、1色の人の見た目は今と同じ(`--screenshot` で見比べる)

### 7-6 ユーザーが色を直す
- 今の動き: 作業データ(`%LOCALAPPDATA%\youtube-tools\holo-colors\`)に `settings.json` と `my-colors.json`(マイカラー)がある(`Core.cs:530-531`)。メンバーの色を直す方法は members.json を手で直すだけ(README.txt の 67 行目)で、差し替えると消える
- 変えること: 作業データに `member-colors.json` を置く(`{"version":1,"members":{"<メンバー id>":{"colors":[{"hex","label"}]}}}`。`colors[0]` が主な色)。メンバーの札の右クリックに「色を直す…」: 色の一覧(追加・削除・上へ = 主にする・ラベル)と「元の色に戻す」。直した人の札に小さな印、ツールチップに「直した色」
  - 書き込みは今の `Files.WriteAtomic`、読めないときは `.corrupt-日時` に残す、開けないときは保存を止める(`Store` と同じ決まり)
  - キーはメンバー id だけ(グループの id を入れない。卒業でグループが変わっても直した色が残る)。members.json に無い id の項目は残しておくが使わない
- 案の比較: (a) 作業データに上書きの差分(採用)… members.json を新しくしても直した色が残り、`colors.py` も同じ場所を読める。(b) members.json を画面から書き換える … 友人が新しい zip に差し替えると消える。exe の横(Program Files など)に書けないこともある。(c) マイカラーに同じ名前で足す(今でもできる)… 一覧に同じ人が2回出る
- 変えるファイル: `holo-colors/src/Core.cs`(`Store` に読み書き)、`holo-colors/src/Dialogs.cs`(直す窓)、`holo-colors/src/MainForm.cs`・`Program.cs`(メニューと反映)
- テスト: `CoreTests.cs` に「直した色が一覧に反映される・元に戻す・壊れたファイル・開けないときは上書きしない・知らない id」を StoreColors / StoreCorrupt / StoreLocked と同じ作りで
- リスク: 直した色をすべて消す操作 → 最低1色は残す(空なら「元に戻す」と同じ)。主な色を変えると字幕の色も変わる(7-7)→ 窓にそう書く
- 終わりの条件: 画面から直した色がアプリを起動し直しても残り、members.json を差し替えても消えない

### 7-7 字幕の色(`ytt_core/colors.py`)
- 今の動き: `load()` がマイカラー → members.json の順に `hex` を読む(`ytt_core/colors.py:78-98`)。マイカラーは inplace(テスト)では読まない(`colors.py:32-35`)。使う所は入口の配信者の欄(`app/launch.py:747-752`)・パック(`cut2resolve/serve.py:541-556`)・zip(`transcribe-tool/serve.py:5952-5958`)・まとめて実行(`app/autorun.py:154`)
- 変えること: 字幕の色 = **主な色**(直した色があればその `colors[0]`、無ければ members.json の `hex`)。`load()` で `member-colors.json` を重ねる(置き場所は `mine_path` と同じ決まり。inplace では読まない)。返す項目に `colors`(全部の色)を足すが、使う側(`speaker_colors`・`resolve`・入口の `pick`)は今までどおり `hex` だけを使う
- 変えるファイル: `ytt_core/colors.py`
- テスト: `ytt_core/test_ytt_core.py` の色のテスト(`TestColors`。750 行目〜)に「直した色の主な色が字幕の色になる・直した色のファイルが壊れていても落ちない・colors の形の検査(形の違う色は捨てる)」、`test_repo_members_json_is_readable`(807 行目)に「全員 `colors[0].hex == hex`」。使っている所のテスト(`cut2resolve` の `test_serve`・`app/test_launch.py`)も流す
- リスク: 使う側で「直した色」が効くのは入口を起動し直した後ではなく、ファイルの更新日時で読み直す(今の `_read_json` のキャッシュの仕組みで足りる)。テストで本物の作業データを読まないこと(`YTT_DATA_DIR=inplace`)
- 終わりの条件: 直した主な色がパックの Text+ の文字の色に出る(テストと実機)

### 7-8 テスト・README・文書
- 今の動き: `build.bat` がテスト 17 件を流す(`docs/holo-colors.md` の「テスト」)。README に「メンバーの色について」の節がある
- 変えること: README.txt に「札の小さな四角」「色を直す…」「直した色はどこに残るか」を書く。`docs/holo-colors.md` の「メンバーの色」「作業データ」「ファイル」を新しい形に直し、2026-09-29 の決定の行を「実装済み」に。`docs/ROADMAP.md` の段7 の行と「1. 全体像」のホロカラーの行を直す
- 変えるファイル: `holo-colors/README.txt`、`docs/holo-colors.md`、`docs/ROADMAP.md`、`docs/WORKLOG.md`
- テスト(流すもの): `holo-colors/build.bat`(PC)、`python holo-colors/e2e_holo_colors.py`(PC・触らない)、★`python -m unittest ytt_core/test_ytt_core.py`、`cut2resolve` の `python -m unittest test_cut2resolve test_pack test_serve`、★`python -m unittest app/test_launch.py`
- リスク: build.bat と e2e は Windows でしか流せない(クラウドの環境では C# をコンパイルできない)→ Linux では Python のテストと JSON の形の検査だけ流し、C# の確認は PC で行うと WORKLOG に書く
- 終わりの条件: 上のテストがすべて通り、`dist/HoloColors.zip` を作り直した

## 版の上げ方
- ホロカラー: 1.2.1 → **1.3.0**(機能の追加)。`holo-colors/src/Core.cs:19` の `AppInfo.Version` と `holo-colors/README.txt` の見出しを同時に。README の変更の記録に 1.3.0
- members.json: `version` 1 → 2、`updated` を調べ終えた日に
- `ytt_core/colors.py` の変更は共通部品なので、ツールの版は上げない(画面・API の形が変わらないため)。WORKLOG に書く
- `docs/ROADMAP.md` の先頭の版の行(ホロカラー 1.3.0)

## 実機で確かめること
- 友人と同じ使い方: 1.2.1 の exe のまま新しい members.json に差し替えて起動できる(落ちない・主な色が出る)
- 1.3.0: 2色以上の人の四角を押してコピー → Resolve に Ctrl+V で貼れる。右クリックのメニューの色
- 「色を直す…」で主な色を変える → アプリを終了・起動しても残る → members.json を差し替えても残る
- 同じ PC で「編集」のパックの配信者の欄にその人を入れる → Text+ の文字がその主な色(入口を起動し直さなくてよいか)
- DPI 125%・150% で札の四角が名前に重ならない

## 決まったこと(2026-09-29 ユーザー。計画を書いたあとに聞いた分)
- 名簿の変化(新しいデビュー・卒業)も**一緒に直す**(ホロカラーの `members.json` だけ。文字起こしの名簿 `hololive-roster.json` は別の作業)
- 「色を直す…」は**友人に渡す exe にも出す**
- 出典で色合いが違う4人と、調べて主な色を変えたほうがよさそうな人: 既定は「今の色のまま、もう1色を2つ目に足す」。調べた結果を一覧にして、主な色を変えるかは段7 の中でユーザーに見せて決める
