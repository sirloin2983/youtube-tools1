# コードレビューの依頼書(GPT 向け)2026-10-12

状態(2026-10-12): 依頼書。レビューはまだ。対象は main の今の HEAD・全体の版 0.61.0。**コードは変えない**(読む・小さな再現を一時フォルダで動かす・結果を文書に書く、まで)。

この文書は、GPT(Codex)にこのリポジトリのコードレビューを頼むための前提のまとめ。AGENTS.md は長いので、レビューに要る「構造・層・決まり・既に分かっている物」をここに集めた。細部の正は AGENTS.md・`dev/layer_map.py`・`docs/spec/` で、食い違ったらそちらを正とする。

---

## 1. やってほしいこと・やらないこと

- やること: 不具合(データを失う・壊す・間違った結果を成功と言う・止まる・競合)・層の決まりの破れ・セキュリティの穴・保守性の大きな問題を見つけ、**再現の条件と根拠(ファイル:行)**を付けて書く
- やらないこと:
  - コード・テスト・設定の変更(担当表で src/ は Claude。GPT は調査と文書まで)
  - 本物の作業データ(`%LOCALAPPDATA%\youtube-tools\`)への書き込み。再現は一時フォルダ + `YTT_DATA_DIR=inplace` か、モックで
  - 入口(start.bat で動いているプロセス)を止める・起動し直す
  - `git add -A`・他の AI の未コミットの変更に触る
- 書く先: `docs/design/code-review-<日付>-2.md`(前回の `code-review-2026-10-12.md` と同じ形: 位置・条件・原因・影響・再現・直し方の方針・重さ P1/P2/P3)。`docs/ROADMAP.md` の索引に 1 行、`docs/WORKLOG.md` の末尾に記録(書式は WORKLOG の先頭)。コミットは `[GPT] 要約` で、変えた文書だけ `git add <ファイル>`
- 重さの目安: P1 = 人の作業・データを黙って失う/壊す。P2 = 間違った結果・止まる・再起動まで直らない。P3 = 保守性・決まりの破れ・紛らわしさ

## 2. 何のツールか(30 秒で)

YouTube の配信から切り抜きのショート動画を作るための、**ユーザーの PC だけで動く**ツール群。Python 標準ライブラリ中心のローカル HTTP サーバー(入口 `src/app/server.py`、http://localhost:8700/)+ ブラウザの画面。外部サービスへ動画・音声を送らない方針。

流れ: 配信を探して解析(盛り上がりの候補)→ 候補の区間を選んで書き出す → 文字起こし・校正 → カットを決めて DaVinci Resolve 用のパック(カット + 字幕)を作る。ほかに、配信中に録画してマークする「ライブ」(線 D)、友人の依頼を Dropbox で受けて自動で流す受付、友人の PC で同じ処理を動かす「F1」(送るアプリが ② を子プロセスで起こす)。

利用者は実質 2 人(ユーザーと友人 1 人)。大規模な同時利用や悪意ある利用者は想定外だが、**ローカルのポートに来る他のページ(ブラウザの別タブ)からの攻撃**は想定する(下の 6)。

## 3. 層(いちばん大事な構造)

2026-10-09〜11 に「役割で組み直す」(RS0〜RS8・OPT1・OPT2)をした。`src/` の .py は次の層のどれかに属する(表の正は `dev/layer_map.py`)。

| 層 | フォルダ | 役割 | import してよい相手 |
| --- | --- | --- | --- |
| 基盤 | `src/ytt/` | 語彙・ファイルの読み書き・置き場所・ジョブの表・HTTP の検査など。どこからでも読まれる | なし |
| ① 道具 | `src/pipeline/` | データを加工する(解析・文字起こし・書き出し・パック・録画)。「指定 → 結果」の関数 | ytt |
| ② 管理 | `src/flow/` | ① をいつ・どの順で・どこに置いて・飛ばすかを決める(実行・待ち行列・鍵・置き場所・ライブの段取り)。**変換のコードを書かない・① の別名だけの関数も作らない・画面と案件を知らない** | ytt・pipeline |
| ③ 人 | `src/human/` | 人の操作の側(校正・候補の採用・確かめる・友人) | ytt・flow(**① を直に読まない**) |
| ④ データ | `src/manage/` | 案件・バックアップ・片付け・調子 | ytt・flow・human |
| ⑤ 検証 | `src/eval/` | 精度を測る・確かめるの待ち行列・疑似 | ytt・pipeline・flow・human・manage |
| 入口 | `src/app/`(+ `src/home/` の一部) | HTTP の口・画面・CLI | 全部 |

- 検査: `dev/tests/test_layering.py`(違反 0。`KNOWN_MAX = 0`)。レビューでは「表は通るが精神に反する」物(② に変換が入り込んでいる・③ が ② の薄い包みで ① を事実上直に呼んでいる・ytt に業務の判断がある)を見てほしい
- 旧いフォルダ `src/studio/`・`src/editor/`・`src/cut2resolve/`・`src/home/` に残るのは、HTTP の配線(`serve.py`)・画面の部品の JS/CSS・入口として残した物。**画面の部品の JS・CSS は案件の画面が相対パスで読むので、名前を変えない・消さない**
- 規模(テストを除く .py の行数の目安): ytt 6.0k・pipeline 15.7k・flow 14.0k・human 11.3k・manage 5.3k・eval 12.6k・app 2.6k・home 2.2k・studio 0.9k・editor 1.7k・cut2resolve 0.6k

## 4. 主な流れと、壊れやすい境目

1. **実行(② の中心)**: 依頼は「封筒 + 束」(`flow/envelope.py`)で `POST /api/flow/submit` → 待ち行列と糸 `flow/runqueue.py` → 段の並び `flow/run.py`(文字起こし → 採用 → 書き出し → パック)。段ごとの成果物に**鍵** `*.key.json`(`flow/keys.py`)を付け、同じなら飛ばす。結果の束は案件の `作業用\runs\<実行id>.json`。同じ作業データを 2 つが使わないよう `.flow.lock`(`flow/placement.py`)
2. **CLI**: `src/app/cli.py`。入口が動いていれば submit 1 回で頼んで待つ、無ければ自分で lock を取って ① を直に(`flow/tools.LocalTools`)。終了コード 0/1/2/4/130
3. **ジョブの器**: `flow/jobs.Table` 1 つの上に 解析 `flow/batch`・書き出し `flow/export`・パック `flow/packjobs`・編集の tx。重い処理は `ytt/jobs.SLOTS` を通す。手渡し・中止は `ytt/jobs.Ctl`
4. **案件のファイル**: 候補 `作業用/候補.json`(① の機械の候補)と 採用 `作業用/採用.json`(③ の人の採用)を分けて持つ(`flow/casebook.py`・読む側 `ytt/casefiles.py`)。文書の置き場所は索引 `transcripts/<id>.loc.json` → `ytt/docloc.py`
5. **校正の人の層**: 作り直した文書へ人の直しを時刻の重なりで引き継ぐ(`human/proof/overrides.py`・`layers.py`・`machpick.py`)
6. **確かめる(V1)**: 待ち行列 ⑤ `eval/check/`、答えの反映 ③ `human/check/`。戻せない答え([送る]・[要らない])は 1 枚遅れで確定
7. **ライブ**: `flow/livesession.py`・`live_*`。録画は別プロセス(`pipeline/ingest/`)
8. **F1(友人の PC)**: 入口の `--headless --parent-pid`、`/api/flow/machine`・`/api/flow/outbox`、学習の束 `flow/learning`・`manage/keep/learnpack`、送り返し `flow/outbox`・`human/friend/returns`。送るアプリは C# の `friend-apps/request-sender/`

境目で起きやすいこと(前回の 7 件もこの種類): 保存中の画面の切り替え・応答待ちの間の再変更 / 表示した内容と答えたときの内容の食い違い / 失敗の結果を後から成功で上書き / エラーを表示文で判定 / 設定を変えても動いているプロセスに届かない / 「終わった」と見なす時点が後片付けより早い / ドライブ違い(`os.path.relpath` が ValueError。10-11 に 1 件直した)。

## 5. 守るべき決まり(破れていたら指摘)

- 作業データはリポジトリの外。サーバーを動かすテストは先頭で `os.environ.setdefault("YTT_DATA_DIR", "inplace")`
- 文字起こしのサーバー側のプロセスで numpy・faster_whisper・ctranslate2・sherpa_onnx を import しない(認識は別プロセスのワーカー `pipeline/transcribe/worker.py`)
- データ移行はコピーのみ・元は残す。物には必ず終わり(片付けの日数は既存の 3 日)
- 盛り上がりの式は `pipeline/analyze/excite.py` の 1 か所。Resolve パックは `pipeline/pack/pack.py` だけが作る。紐づけとパックの有無の判定は `manage/cases/txindex.py` だけ
- 画面は相対パスで部品を読み、API の URL は 1 か所の関数で作る(絶対パス `/xxx` を書かない)
- ツール間で同じ名前の .py を作らない
- 子プロセスで窓を出さない(`CREATE_NO_WINDOW`)
- 版は全体で 1 つ(`src/ytt/version.py`)
- 説明文(docstring)にバックスラッシュを書かない・`.bat` は CRLF/ASCII

## 6. セキュリティの前提

- 1 つのポートに全ツールをまとめた = **1 つの画面の XSS で全 API が使える**。守り: CSP `script-src 'self'`(`src/app/server.py` の `PAGE_CSP`・`src/home/mount.py`)・書き込み系の POST に合言葉 `X-YTT-Token`・Host/Origin の検査は `ytt/httpsec` の 1 か所・パスは許可したフォルダの中だけ
- 見てほしい所: 合言葉の要らない口が書き込みをしていないか / パスの検査の抜け(`..`・ドライブ・UNC・シンボリックリンク・短い名前)/ 子プロセスの引数に外の文字列が入る所(yt-dlp・ffmpeg・streamlink の URL)/ 友人の Dropbox から来た zip・JSON をそのまま信じていないか(展開先・大きさ)/ CSP の例外(YouTube の埋め込み)の広さ / API キーのファイルの扱い
- リポジトリは Public の方針。秘密・個人データがコードやテストのデータに入っていないか

## 7. 既に分かっている物(重ねて報告しない)

- 前回のレビュー `docs/design/code-review-2026-10-12.md` の 7 件(カット保存中の切り替え・確かめるの読みの食い違いと残りの候補・CLI の失敗の上書き・既存解析の待ちの文字列判定・学習の同期が動いているプロセスに届かない・送り返しの zip の前に idle)
- 10-08 の見直し `docs/design/code-review-simplify-2026-10-08.md`(簡潔にする指摘 193 件。A〜E は実装済み)
- 見直しメモ `plan/opt-pipeline-flow.md` の「機能ごとの見直しメモ」「② 管理の見直しメモ」と `plan/improvements.md`
- 友人用アプリの要件は見直し中(`plan/f1-friend-requirements.md`。暫定で覆る)= 送るアプリの画面・フォルダの扱いの指摘は不要。既知: 設定の「案件の保存先」は空き容量を測る所が変わるだけ・アプリの更新(robocopy /E)が消えたファイルを消さない・画面なしの ② はまとめ動画を作らない
- WORKLOG の「気づいたこと(直していない)」: スタジオを取り込まない形での書き出し先の確かめの食い違い / `POST /api/queue/add` が HTTP のまま / スタジオの test_api と cut2resolve の test_serve・test_mount を 1 プロセスで混ぜると serve の名前がぶつかる / 作業データの違う画面なしの ② が既定のポートの録画の部品を止めにいく(403 で害なし)
- 決めて選んだ形(不具合ではない): 切り出しは精密・画質の上限なし・fps 30 固定 / `.flow.lock` で 1 つの作業データに 1 つの実行 / ③④ は ① を ② 経由で読む / ラウドネスは消すのを待っている(decisions 3-35)/ 失敗のリスクは低い前提で守りは PC 全体に関わる物だけ(上限は隠さず本人が選ぶ欄に)

## 8. 前回が見ていない所(重点の候補)

前回は `src/app/`・`src/flow/` の実行と同期・`human/check`・`eval/check`・案件の移動/一覧・送るアプリの同期と終了が中心。今回はできれば次から:

1. **① 道具の中身**: `pipeline/transcribe/`(worker・recognize・diarize・fill・retime・llm)・`pipeline/export/exporter.py`・`pipeline/pack/`(pack・resolve_textplus・cut2resolve_core)・`pipeline/analyze/`。時刻の計算の端(0 長・負・重なり・末尾)・30fps の丸め・子プロセスの失敗と中止の後始末
2. **校正の人の層**: `human/proof/`(doc_jobs・rerun・overrides・layers・machpick・store・speakers)。作り直しのときに人の直しを失わないか・同時の保存の競合
3. **ライブ**: `flow/livesession.py`・`flow/live_*`・`pipeline/ingest/`(録画の部品・別プロセス)。長時間・途中で切れた配信・ディスクの空き
4. **基盤の書き込み**: `ytt/fsio`(atomic な書き込み・ロック)・`ytt/docloc`・`ytt/casefiles`・`flow/casebook`。Windows の置き換えの失敗(WinError 5/32)・ロックの取り忘れ・読みのキャッシュの古さ
5. **セキュリティ**: 上の 6
6. **層の精神**: 上の 3 の最後
7. **テストの穴**: 大事な道に unittest が無い所(e2e は少なめの方針なので、unittest で守れていない所)

全部でなくてよい。範囲を絞ったら、見た範囲と見ていない範囲を文書に書く。

## 9. 動かし方(この PC)

- Python は 3.10。`py -3.10` が見つからなければ `C:\Users\<ユーザー名>\AppData\Local\Programs\Python\Python310\python.exe` を直に
- 速い検査: `py -3.10 dev/lint.py`(0 件)・`py -3.10 -m unittest dev/tests/test_layering.py`。各フォルダのテストの組は AGENTS.md の表
- e2e(画面テスト)は流さなくてよい(重い・少なめの方針)
- sandbox の一時領域で atomic replace が WinError 5 になったら製品の不具合と数えない(前回の注意)
- GPU は AMD(CUDA なし)。友人の PC は RTX 3060
- 本物の Dropbox・実配信・GPU 認識は動かさない(モックで)

## 10. GPT に貼る依頼文(例)

```
C:\dev\youtube-tools のコードレビューをしてください。コードは変えません。
最初に AGENTS.md と docs/design/code-review-brief-2026-10-12.md を読み、
docs/WORKLOG.md の最後の数件・git status・git log -5 を見てから始めてください。
重点は依頼書の 8 節(前回が見ていない所)。既知の物(7 節)は重ねないでください。
指摘ごとに 位置(ファイル:行)・条件・原因・影響・再現(一時データかモックで)・直し方の方針・重さ(P1/P2/P3)を書き、
docs/design/code-review-<日付>-2.md にまとめ、ROADMAP の索引と WORKLOG に追記して、
変えた文書だけを "[GPT] 要約" でコミットしてください。サブエージェントは観点ごとに並列で使ってかまいません。
```
