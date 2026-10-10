状態(2026-10-10 夜): 案 b(成果物を実行・案件ごとのフォルダにまとめる)の深掘り(Fable)

# 案 b の深掘り: 成果物を「案件ごとのフォルダ」にまとめる

前提は `plan/decisions.md` 3-29 と `layer5_review.md`(層 ①道具 / ②管理 / ③人 / ④データ / ⑤検証。② が書き ④ が読む・友人の PC で ② + ① がメイン)。置き場所の地図は `places_studio.md`・`places_tx.md`。読むだけで、コードと git は触っていない。「推測」は読んで確かめていない所。

## 0. まず前提をそろえる(今、1 本の配信を流すとファイルはどこにできるか)
今は「成果物の種類ごと」に 3 か所へ散る(URL `https://youtu.be/U972n0ncl4k` を 1 本流した例。この PC の実物で確かめた):
```
E:\Video\切り抜き動画素材\                      ← スタジオの書き出し先(settings.json の outDir)
└─ #2【バイオハザード HDリマスター】やるです。\   ← 配信ごとのフォルダ(names.pick_folder。作業用\.studio-id に videoId = 持ち主)
   ├─ 01_02h38m38s-02h41m02s.mp4               ← 切り抜き(① export)
   ├─ 01_02h38m38s-02h41m02s_pack\             ← パック(① pack)
   └─ 作業用\ 01_….clip.json  01_….edit.json  01_….transcript.json  01_…_edit.mp4  01_…_edit.clip.json
%LOCALAPPDATA%\youtube-tools\
├─ studio\      data.json(全配信の候補・採用がこの 1 ファイル)・feedback.jsonl・cache\(チャット 2GB)・archive\・settings.json・config.json(API キー)
├─ transcribe\  transcripts\<ランダム 12 桁>.json / .asr.json / .words.json / .diar.json / .edit.json / .hist\ / .bak\、dataset\・evals\・voices\・models\・bin\
├─ cut2resolve\ packs\<パックのパスの sha1>.json(パックの記録)
└─ app\         logs\autorun-runs.jsonl(実行の記録)・cases.json(案件の状態・メモ)・live\(録画の採用・reports)・intake\
```
困り事(= 案 b を考える理由): (1) 1 本の配信の成果物が「どれとどれか」を `txindex` が**毎回パスの一致で組み立て直す**(文書の `sourcePath` ↔ mp4。動かすと外れる)。(2) 文書の名前がランダムで、人がエクスプローラーで見ても分からない。(3) 消す・写す・友人に渡す単位が「配信 1 本」なのに、フォルダはそうなっていない(片付けは拡張子の一覧で拾う)。(4) 鍵(RS6-K1)と結果の束を**どこに置くか**が決まっていない。

## 1. 単位の比較(b1 実行ごと / b2 案件ごと / b3 鍵の棚)
| 観点 | b1 実行ごとのフォルダ `runs/<実行id>/` | **b2 案件ごとのフォルダ `<案件>/`(中に実行の記録)** | b3 鍵で引く棚 `store/<hash>/` + 一覧 |
| --- | --- | --- | --- |
| 同じ配信を何度も実行(F-7: 配信中 + アーカイブ + やり直し) | 実行のたびに別フォルダ → 使い回しは**他の実行のフォルダを探す**ことになり、鍵の一覧が別に要る(= 結局 b3) | 同じフォルダに溜まる。鍵が一致する成果物は**同じフォルダの中**にあるので、② の「飛ばす判定」が 1 フォルダの走査で済む | 最も自然(鍵 = 住所)。ただし実行・案件は一覧の JSON だけになる |
| 速報版と本番版(F-1) | 2 つの実行に分かれる。「どちらが有効か」を ④ が実行をまたいで持つ | 同じ案件の中に **媒体の識別の違う 2 本**(鍵の `media` が recording / archive)。有効な方を `case.json` に 1 行。今の `作業用\速報版\` の退避と同じ形 | 両方が棚にある。有効の選択は一覧側 |
| 人の上書き(切り抜きの鍵に付く) | 実行フォルダに置くと、次の実行が**前の実行のフォルダ**を読む = 向きが汚い | 切り抜きの横 `作業用\<切り抜き>.over.json`。① が作り直しても横にあるので O1 の引き継ぎが「同じ名前を探す」だけ | 鍵のフォルダに置く。切り抜きの鍵が変わる(端を動かす)と**迷子**になり付け替えが要る |
| 学習データ(全体で共有) | 外(共有)。どの案でも同じ | 外(共有) | 外(共有) |
| 人が見て分かるか・Resolve に渡せるか・友人に渡せるか | 実行 id のフォルダ = 分からない | **題名のフォルダ = 今と同じ**。フォルダごと zip で渡せる | hash のフォルダ = 分からない。Resolve のパック・動画は読める名前が要るので結局「名前 → hash」の写しが要る |
| 直す量 | 置き場所の持ち主 3 系統 + 直書き 10 件 + 文書 25 件 + 一覧 12 件(地図の 7 節) | 書き出しの側は**今の `<outDir>\<題名>\` がすでに案件フォルダ**。増えるのは文書の移動(25 件)と記録(9 件) | 全部 + 一覧の仕組みを新規 |
| 向かないこと | 実行 = 一時的な物。成果物の正本にすると「どの実行が最新か」を常に引く | 案件の識別が要る(媒体の識別 = `media_identity` の 3 種。すでにある) | 1 人 + 友人 1 人には過剰。バックアップ・片付けが hash 単位になり人が判断できない |

**筋がよいのは b2**。理由: (a) 使い回しの単位(切り抜き 1 本 = 配信 ID + 区間)も、上書きの単位(切り抜き)も、届ける単位(パック)も、消す単位(配信 1 本)も、全部「案件の中」で閉じる。(b) 今の書き出し先の `<題名>\` フォルダ + `作業用\` + `.studio-id`(持ち主 = videoId)が**もう b2 の形**で、足りないのは文書と記録がそこに無いことだけ。(c) b1 は「実行の記録」としては要るので、**b2 の中に `作業用\runs\<実行id>.json`(結果の束)として入れる** = 案 c の「結果の束だけ」をそのまま案件フォルダに置くと b2 の第 1 段になる(7 節)。(d) b3 の良さ「鍵で引く」は、**案件フォルダの中の `.key.json` を ② が走査する索引**として取り込める(棚は作らない)。

## 2. b2 のフォルダの木(提案)
案件の根 = **今のスタジオの書き出し先**(`E:\Video\切り抜き動画素材\`。新しい根を作らない = 動画が 2 か所に分かれない)。作業データ `%LOCALAPPDATA%\youtube-tools\` には**全体で共有する物だけ**を残す。
```
<案件の根>\                                   例 E:\Video\切り抜き動画素材\
├─ .flow.lock                                 ② が 1 つだけ動く印(pid・ポート。CLI は動いている ② があればそこへ HTTP で頼む)
├─ <配信の題名>\                               案件 = 配信 1 本(URL)。持ち主 = 作業用\case.json の media(今の .studio-id の発展)
│  ├─ 01_02h38m38s-02h41m02s.mp4              切り抜き(① export。名前の規則 names.clip_base は変えない)
│  ├─ 01_02h38m38s-02h41m02s_pack\            パック(① pack)+ pack.key.json(入っている切り抜きの鍵・字幕の rev・pack の設定)
│  └─ 作業用\
│     ├─ case.json                            案件の素性(④ が書く): media(archive videoId / file sha256 / recording)・題・チャンネル・有効な版(速報版か本番版か)・状態・メモ(今の cases.json の 1 件分)
│     ├─ 候補.json  候補.analyze.key.json     ① analyze の出力(区間と点数・自動採用)+ 鍵(第 3 段 B-3 で data.json から分ける。それまでは data.json のまま)
│     ├─ 採用.json                            ③ の上書き(手動マーク・採用と不採用・端の調整)(B-3)
│     ├─ 01_….clip.json  01_….export.key.json  切り抜きの素性と鍵(今の .clip.json + RS6-K1)
│     ├─ 01_….tx.json                         文書(今の transcripts\<tid>.json。original・recognition・words・asr = ① の持ち分、segments の人の直し = ③)
│     ├─ 01_….asr.json  .words.json  .diar.json  .llm.json  .alt.json  .ytcap.json   横のファイル(名前を tid → 切り抜き名に)
│     ├─ 01_….transcribe.key.json  .post.key.json  .diar.key.json                     認識・後処理・判別の鍵(RS6-K1)
│     ├─ 01_….edit.json  01_….over.json         カット(③)・校正の上書き(③。RS6-O1)
│     ├─ 01_…_edit.mp4  01_….transcript.json  01_….srt                                受け渡しの途中のファイル(今のまま)
│     ├─ .hist\01_…\<ts>.json  .bak\            文書の履歴・控え(今の transcripts\.hist・.bak を案件の中へ)
│     ├─ 速報版\                                本番版に入れ替えたときの退避(今のまま。live_cleanup が 3 日で消す)
│     └─ runs\<実行id>.json                     ② の結果の束(実行 id・有効な束・段ごとの成果物のパスと鍵・失敗と理由)。① の記録 = これ
├─ <動画ファイルの名前>\                         案件 = 動画ファイル 1 本(友人の依頼)。media = file sha256。中は同じ(切り抜きは 1 本 = 丸ごと)
└─ <配信の題名>\                                 ライブ 1 本: 配信中は recording の鍵で速報版が溜まり、配信後は同じ案件に archive の鍵で本番版。
                                                録画そのもの(HLS)は案件の外(recorder\ の一時物)。live\reports の配信ごとの記録は 作業用\runs\ に
%LOCALAPPDATA%\youtube-tools\(全体で共有)
├─ settings.json(RS7 で 1 ファイル)・prefs・API キー(config.json。鍵は案件に入れない)
├─ learn\   名簿・置換辞書・用語集・learn-feedback.json・voices\(覚えた声)・evals\marks(長さの目安)  = ③ が書き ① が読む学習データ(版 = ハッシュ。F-8)
├─ eval\    dataset\・eval-audio\・evals\・評価用の文書(evalSet の文書は案件へ移さない = ⑤ の材料)
├─ cache\   チャット・音量の署名・波形(作り直せる。案件を消しても残ってよい)、models\・bin\
├─ logs\    入口のログ・client-errors・autorun-runs.jsonl(**索引**: どの案件の runs\ に結果があるか。正本は案件側)
├─ index\   cases.json・data.json(B-1〜B-3 の間は「全案件の一覧のキャッシュ」。案件フォルダを走査して作り直せる物にする)
└─ feedback.jsonl・live_feedback.jsonl・friend_feedback.jsonl(③ の追記だけの記録。learn・eval_marks が全体を読むので共有のまま)
```
名前の決まり: 文書と横のファイルは**切り抜きの名前**を基底にする(`sidecar_path(mp4, ".tx.json")` の形 = 今の `.clip.json` と同じ規則。`find_sidecar` の「作業用\ → 隣」の探し方もそのまま)。文書 id は「案件フォルダ + 切り抜き名」になり、ランダムな tid は要らなくなる(画面の URL `?id=` は当面 tid → パスの対応表で吸収。推測: `store.list` と `TID_RE` の列挙は作り直し)。

## 3. 今の置き場所ごとの行き先(地図の項目 → b2)
| 今の置き場所(地図) | 行き先 | 直す所の目安 | 層 |
| --- | --- | --- | --- |
| studio `data.json`(候補・採用。地図 1) | 第 1〜2 段はそのまま。B-3 で `作業用\候補.json`(①)+ `採用.json`(③)に分け、`index\data.json` は一覧のキャッシュ | 持ち主 3 系統(`studio_env.p`・`workdata.STUDIO_DATA`・`cases.locations`)を `flow/placement.py` の 1 本に = 3 + store.py 12 + review.js(画面) | ② placement / ③ review / 画面 |
| 元動画・チャット・音量の cache(地図 2) | 共有 `cache\` のまま(作り直せる・大きい)。`作業用\archive-<id>`・`build`・`speed` の直書き 3 件は placement 経由に | 直書き 10 件(places_studio 7 節)→ `work_dir()` 経由 | ① ingest/analyze(書く先を受け取るだけ) |
| 書き出し・切り抜き・`作業用\`(地図 3) | **そのまま**(もう案件フォルダ)。`.studio-id` → `case.json` の media に(読む側は両方を見る) | names.py 2・exporter 4・cleanup 2 | ① export(受け取ったパスに書く)/ ④ cases |
| 録画・ライブ(地図 4) | HLS の録画は `recorder\` のまま(一時物)。`live\reports\*.json` → `作業用\runs\`。`live\exports.json`(ジョブ)は ② の表に | live.py 3・live_report 1・live_archive 3・live_export 1 | ② (配信中ずっと回すのは ②) |
| feedback・settings(地図 5) | 共有のまま | 0(placement で場所を返すだけ) | ③ / ytt |
| 文書と横のファイル `TX_DIR`(places_tx 1) | `作業用\<切り抜き名>.tx.json` ほか。`.hist`・`.bak` も案件の中 | **約 25 + テストの `S.TX_DIR = …` の差し替え(数百行。推測)**。`workdata.TX_DIR`(1 つの根)→「切り抜きごとの置き場所」を返す関数へ | ①(asr・words・diar・llm = 受け取ったパスに書く)/ ③(tx・edit・over・alt・ytcap) |
| 一覧と紐づけ txindex 系(places_tx 2) | 紐づけが**同じフォルダの同じ名前**になるので `_match`・`pick`・`offset` は「横のファイルを開く」に縮む。`relink` は「案件フォルダごと動かした」だけを扱う | 約 12 → 多くは削れる | ④ cases |
| パック(places_tx 3) | `<pack>\pack.key.json` + 記録を**パックのフォルダの中**へ(`cut2resolve\packs\<sha1>.json` の外部の記録をやめる)。`pack_info` は鍵を読む 1 か所のまま | pack.py 2・serve 1・txindex 2・cases 3 | ① pack(書く)/ ④(読む) |
| 入口の記録(places_tx 4) | `autorun-runs.jsonl` → 索引。正本は `作業用\runs\<id>.json`。`autorun-active.json`(戻す用)は ② の `flow\` の作業データ | runlog 1・run.py 2・autorun 2・live_failures 1 | ② |
| 学習と評価(places_tx 5) | 共有 `learn\`・`eval\` に名前を寄せる(置き場所を 1 回変えるだけ。中身は同じ) | roster・replace・learn・voices の場所 4 | ③ 書く / ① 読む / ⑤ |
| 保管と片付け(places_tx 6) | バックアップ: 共有は今のまま + **案件の根の `作業用\*.json`・`.hist`・`pack.key.json` を足す**(mp4・pack の中身は写さない)。片付け: 単位が「案件フォルダ」になり、拡張子の一覧(cleanup 30・349)は「案件の中の種類」に | backup 3・cleanup 3 | ④ keep |

## 4. 何がどう変わるか
- **使い回し(鍵)**: ② は案件フォルダの `*.key.json` を走査して「鍵 → 成果物」の索引を作る(起動時 1 回 + 書いたら更新。棚は作らない)。判定は「同じ案件の中に同じ段・同じ hash があるか」。速報版と本番版は hash が違うので両方残り、`case.json` の有効な版で ④ が選ぶ(F-1)。鍵が違うときの既定は 3-29 のとおり(認識は飛ばして印・パックは作り直す・鍵なしは今のまま)。
- **人の上書き**: `作業用\<切り抜き>.over.json`(切り抜きの鍵の hash つき)。① が作り直しても横に残り、O1 が時刻の重なりで引き継ぐ。本番版への入れ替え(F-2)は「同じ切り抜き名で media だけ違う」ので、付け替え = over.json の `clipKey` を書き換えるだけ(今の `_swap` が同じパスに置き換える形と合う)。
- **案件の一覧**: ④ が案件の根を走査して `case.json` + `runs\` + 鍵から状態(認識ずみ・設定が違う・パックが古い)を出す(F-9)。`cases.json` の状態・メモは `case.json` へ(B-1)。走査が遅ければ `index\` にキャッシュ(作り直せる)。
- **画面**: スタジオは配信ごとの一覧 = 案件の一覧になる(data.json の分割 B-3 は UI 再考と一緒。決まり 7)。校正の画面は `?id=<tid>` → `?media=<mp4 のパス>` が主(`/api/doc-for` の形がもうある)。文書の一覧(`app-list.js`)は案件 → 切り抜きの 2 段。
- **バックアップと片付け**: 今は `exports` を**丸ごと写さない**(backup.SKIP_DIRS)ので、文書を案件へ移すと**写されなくなる = 最大のリスク**。写す規則を「案件の根の中は `作業用\*.json`・`.hist\`・`*.key.json`・`case.json` だけ写す」に足してから移す。片付けは「案件ごと(動画 + パック + 作業用)」と「作業用だけ残して動画を消す」の 2 種に。
- **集計**: `feedback.jsonl`・`learn`・`eval_marks` は共有の記録を読むので変わらない。`eval_marks --live` は `live\reports` → 案件の `runs\` を走査(読む側 1 か所)。⑤ の評価用の文書は共有 `eval\` に残す(案件へ移さない)。

## 5. 移行(コピーのみ・元は残す・削除はユーザー確認後)
1. 入口を止める → ② の起動時に `datadir.prepare` と同じ型で 1 回だけ(`.migrated.json` を案件の根に)。
2. 文書: `transcripts\<tid>.json` の `sourcePath`(無ければ `clip` の videoId + mark.id = txindex の規則)で切り抜きを探し、見つかった物だけ `作業用\<切り抜き名>.tx.json` などへ**コピー**(`.hist`・`.bak`・横のファイルも)。`tid → パス` の対応表を `index\tid-map.json` に残す(旧 URL と画面の互換)。見つからない文書・`evalSet` の文書は `transcripts\` に残す(一覧に「案件なし」として出す)。
3. パックの記録 `packs\<sha1>.json` → `<pack>\pack.key.json` + `pack.json`(記録の `dir` が存在する物だけ)。
4. `cases.json` の状態・メモ → 各 `case.json`。`autorun-runs.jsonl` の過去の行は `runs\` に写さない(索引のまま読める)。
5. 確かめ: 案件の一覧と校正の画面で件数が一致 → ユーザーが `transcripts\`・`packs\` をごみ箱へ(`cleanup_legacy_data` と同じ y/N)。空き容量: 文書は小さい(数十 MB)。動画は動かさない。

## 6. 友人の PC がメインであることとの関係
- 友人の PC では ② + ① が `<案件の根>\<題名>\` を作る = **ユーザーの PC と同じ木**。友人が見るのは題名のフォルダ・mp4・パック・`作業用\`(触らなくてよい)。設定と学習データ(名簿・辞書は同梱。声は同梱しない)は `%LOCALAPPDATA%\youtube-tools\` 側。
- 測るために送り返す物 = `作業用\`(文書・asr・鍵・over・runs。動画なしで数 MB)。友人が `作業用\` を zip して Dropbox へ → ⑤ が同じ木の形で読める(`eval_import` の入力をこの形に)。今の「依頼 → ユーザーの PC が処理 → パックの zip を返す」流れは、パックのフォルダが案件の中にあるだけで変わらない(deliver は `<pack>\` を zip)。
- ディスク: 案件 = 動画 + パック(Text+ は動画の写し入り)で動画の 2 倍 + 作業用。消す単位が案件フォルダなので友人でも片付けが簡単(「3 日たったら案件の動画とパックを消す・作業用は残す」の 1 規則)。案件の根は友人が選ぶ(JSON 1 つの `placement.root`)。
- RTX 3060(CUDA)で faster-whisper の GPU が使える = ① の `device` が束で変わるだけ。鍵の `engineVersion`・`device` に入るので、友人の結果とユーザーの結果は鍵で区別できる(同じ切り抜きでも別の成果物)。

## 7. 段の分け方・見積もり・リスク
| 段 | 中身 | 見積(AI の作業) | どの RS |
| --- | --- | --- | --- |
| **B-0** | 案 c をそのまま案件の中へ: ② の結果の束を `作業用\runs\<実行id>.json` に書く(`autorun-runs.jsonl` は索引)・鍵は K1 のとおり横に・`flow/placement.py`(案件の根・切り抜きの置き場所・`.flow.lock`)を作り、置き場所の持ち主 3 系統がそれを呼ぶ(値は今と同じ) | 4〜5h | **RS6**(S1・K1 と同じ波。run.py は 0 のあと) |
| B-1 | `case.json`(media・有効な版・状態・メモ)と ④ の案件の一覧を案件の根の走査に。cases.json → 移行 | 1 日 | RS7(「serve 3 本の骨組み」と同時でよい) |
| B-2 | 文書と横のファイルを案件へ(25 件 + `TX_DIR` → 関数 + テストの差し替え + tid 対応表 + 移行 + バックアップの規則) | 2 日 | **別の RS(UI 再考と一緒。決まり 7)** |
| B-3 | data.json を 候補.json(①)+ 採用.json(③)に分ける・スタジオの一覧 = 案件 | 1〜2 日 | B-2 と同じ RS か次 |
案 c から段階的に寄せる道 = **B-0 がそれ**(案 c の `runs/<id>/result.json` を「app の作業データ」ではなく「案件フォルダ」に置くだけの違い。RS6 で決めるのは置き場所の 1 行)。B-1 以降は後から足せて、B-0 を無駄にしない。

リスク: (1) バックアップが `exports` を飛ばす(4 節。B-2 の前に必ず直す)。(2) 案件の根が外付け(E:)= 抜けていると ② が起動できない → `.flow.lock` と placement で「根が無ければ始めない」。(3) パスの長さ: `作業用\<切り抜き名>.transcribe.key.json`(+20 字)は `SUFFIX_ROOM` 36 に収まるが `.hist\<切り抜き名>\<ts>.json` は超える → `.hist` は短い名前(切り抜き名の sha1 の先頭 8 字。推測で要測定)。(4) 文書 id が名前になるので、切り抜きの改名・30fps の付け替え(relink)が「同名の横のファイルも一緒に動かす」になる(relink は縮むが、案件フォルダごと移すのは OK・中の 1 本だけ改名は禁止 = 画面で止める)。(5) 速報版と本番版が同じ名前で media だけ違う → `.key.json` の読みを間違えると本番版が飛ぶ(K2 のテストに「同名・別 media」を入れる)。(6) 2 つの ② が同じ根を触る(ユーザーの入口 + AI の CLI)→ `.flow.lock`。(7) MSIX の写し(AI の起動は `%LOCALAPPDATA%` が写しになる)は案件の根が E: なら影響しないが、共有側は今までどおり注意。

## 8. ユーザーに確かめる問い
1. **案件の根** = 今のスタジオの書き出し先(`E:\Video\切り抜き動画素材\`)でよいか / 新しい根を作る。**推奨: 書き出し先**(動画が 2 か所に分かれない・`<題名>\` + `作業用\` がもう案件の形)。
2. **RS6 でやる範囲** = B-0 だけ(結果の束を案件の `作業用\runs\` に・placement の 1 本化)/ B-1 も入れる / 案 c(app の作業データに runs)。**推奨: B-0**(RS6 の 2 日に +半日。案 c と置き場所 1 行の違いで、後から B-1〜B-3 に進める)。
3. **文書の置き場**(B-2)= 案件フォルダへ移す(UI 再考と一緒)/ `transcripts\` に残し鍵と結果だけ案件へ。**推奨: 移す**(紐づけが「同じ名前」になり txindex の規則が縮む・友人が送り返す単位が `作業用\` 1 つになる)。ただし B-2 の前にバックアップの規則を直す。
4. **横のファイルの並べ方** = `作業用\` に平らに(今の `.clip.json` と同じ)/ 切り抜きごとにサブフォルダ `作業用\01_…\`。**推奨: 平ら**(`sidecar_path`・`find_sidecar`・直書き 10 件を変えずに済む。1 案件は多くて 10 本 × 12 ファイル = 120 件で見られる範囲)。
5. **共有に残す記録** = `feedback.jsonl`・`live_feedback.jsonl` は共有のまま(③ の追記だけの記録。learn・eval_marks が全体を読む)/ 案件ごとに分ける。**推奨: 共有のまま**(集計側を変えない。案件側には「今の状態」= 採用.json だけ)。
