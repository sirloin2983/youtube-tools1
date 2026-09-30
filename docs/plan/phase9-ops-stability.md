# 段9: 運用の安定化
> 状態(2026-10-01): **決定済み・着手**(下の「決めてもらうこと」は同じ日にユーザーが決めた: 1 元動画も候補に / 2 ごみ箱フォルダ経由 14 日 / 3 上限は今のまま・受付済みの動画は 14 日で候補に / 4 ②③ でも失敗を知らせる)。裏で自動で動くもの(依頼の受付・まとめて実行)が増えたので、**止まった・失敗した・容量が無い**を画面で分かるようにし、片付けと起動し直しを画面からできるようにする
> 全体の計画は `docs/ROADMAP.md`、元の案は `docs/plan/line-a-after-phase8.md` の 3・5(段9)。行番号は 2026-10-01 時点(始める前に今のコードで確かめ直す)。版はその時点の版から上げる

## 目的
- 「調子」が1か所で分かる: 版(期待と実際)・認識ワーカー・ffmpeg / yt-dlp・空き容量・作業データの大きさ・画面のエラーの件数・依頼の受付・まとめて実行の最近の失敗
- 作業データが増え続けない: 何がどれだけあるかを見せ、片付けの候補を出す(**消すのはユーザーが確かめてから**。自動では消さない)
- 版の赤い帯(画面とサーバーの版が違う)から「起動し直す」で直せる(今は「すべて終了」→ start.bat を手で)
- 依頼の受付を運用の形に: 上限・間隔を設定から変える、受け取った動画の片付け、失敗を友人に知らせる
- 小さな注意の明示: VFR・ドロップフレーム・AV1/H.265

## 含まない
- 自動で消す(片付けは候補 → 確認 → 実行)。外部への通知(メール・LINE)。ライブ録画(線 D。「調子」にはライブ録画の状態の欄だけ空けておく)

## 今の動き(2026-10-01 に調べた)
- 入口 `GET /api/status`(`home/launch.py:268`)= 各ツールの状態(`snapshot`: 版・期待した版・pid・ポート)・`dataDir`・`heavy`(SLOTS)。画面はホームの「詳しく(サーバーの管理)」(`home/portal.html:153-`)に起動状態・作業データの置き場所・窓で開く・すべて終了
- 画面のエラーの記録 `home/clientlog.py`(`app\logs\client-errors.jsonl`。1分あたりの上限・大きさの上限あり)。まとめて実行の記録 `app\logs\autorun-runs.jsonl`(段2 B-6)
- 認識ワーカー: `editor/serve.py` の `WorkerClient`(alive・pid・starts・last_used。時限 `WORKER_SILENCE_TIMEOUT` = 20 分)。ffmpeg などの場所は `ytt_core/tools.py`
- 空き容量: 各所で `shutil.disk_usage`(`editor/serve.py:4875, 6723`・`ytt_core/datadir.py:225`)を個別に見ている。画面には出ない
- 作業データ(`%LOCALAPPDATA%\youtube-tools\`。10-01 の実測): app 1.6GB(Edge の専用プロファイル・logs)・studio 981MB(exports の元動画・作業用)・transcribe 112MB(transcripts・dataset・cache の波形)・cut2resolve 0.2MB・holo-colors 9KB
- 依頼の受付 `home/intake.py`: 上限は設定 `intake`(`dailyMax` 5 件・`maxHours` 8・`maxGB` 20。仮の値)、見る間隔 `INTERVAL` 30 秒(定数)。受け取った動画は `受付済み\` に残る。失敗は ① のときだけ Dropbox の `出力\<依頼>.失敗.txt`(`home/autorun.py`)。友人への知らせはしない(`docs/design/friend-intake.md` 9)
- 版の帯: ui-kit `UIKit.appnav.setVersion`(`ui-kit/ui-kit.js:519`)と各画面の APP_VERSION と `/api/ping` の比較で赤い帯。入口の `Supervisor.restart(tid)`(`home/launch.py:404`)は子プロセスのツールだけ(取り込んだツールは入口ごと起動し直す必要がある)
- VFR の注意は cut2resolve の probe の warnings(`cut2resolve_core.py`)→ 見積もり・パックの結果に入る。ドロップフレームの表記は「ノンドロップとして扱う」の注意(`:422`)。AV1/H.265/10bit は README の注意だけ

## 含む作業と順番
| # | 作業 | 大きさ | 依存 |
| --- | --- | --- | --- |
| 9-1 | 「調子」の API と画面(入口の `GET /api/health` + ホームの「詳しく」の中に「調子」の節) | M | なし |
| 9-2 | 作業データの大きさと片付けの候補・確認して片付ける(ごみ箱フォルダ経由) | M | 9-1(大きさの計算を共有) |
| 9-3 | 版の赤い帯から「起動し直す」(入口ごと起動し直す) | M | なし |
| 9-4 | 依頼の受付の運用: 上限・間隔を設定から・受け取った動画の片付け・失敗を友人に知らせる | S〜M | 9-2(片付けの仕組み) |
| 9-5 | 小さな注意: VFR を画面に・ドロップフレームの扱いを明示・AV1/H.265 の注意をパックの見積もりに | S | なし |
| 9-6 | 版・README・ROADMAP・WORKLOG | S | 全部 |

9-1 → 9-2 → 9-4 の順(片付けの仕組みを受付の片付けが使う)。9-3・9-5 は独立(サブエージェントに分けられる: 9-3 = `home/`(Opus。入口の起動と後始末に絡む)、9-5 = `cut2resolve/`・`editor/pack-tab.js`(Sonnet))

## 各作業の細かい計画

### 9-1 「調子」の API と画面
- API: 入口に `GET /api/health`(読むだけ。合言葉は要らない)。1回の応答にまとめる:
  `{versions: [{tool, expected, actual, ok}], worker: {alive, pid, startedCount, lastUsedAgo, silenceTimeoutSec}, tools: {ffmpeg: {path, version}, ffprobe, ytdlp}, disk: [{label, path, freeBytes, totalBytes}](作業データのドライブ・スタジオの書き出し先のドライブ), data: {root, dirs: [{tool, bytes, items: [{name, bytes}]}]}, errors: {clientLast24h, autorunFailedLast7d}, intake: (今の /api/intake の要約), heavy: SLOTS}`。
  作業データの大きさはフォルダを歩くので重い → 入口の中で 10 分キャッシュ + 「数え直す」ボタン(`?refresh=1`)。数えている間は前回の値と「数えています…」
  - 認識ワーカーの状態は「編集」の `GET /api/ping` の応答に足す(`worker: {alive, pid, lastUsedAgo}`。取り込んだ形なら入口が同じプロセスの `WORKER` を直接読んでもよいが、子プロセスで動いたときも同じ道にするため API 経由)
- 画面: ホームの「詳しく(サーバーの管理)」の先頭に「調子」の節(`.card.flat`)。項目ごとに札(良い / 注意 / 悪い)+ 短い文 + 「開く」(記録のフォルダ・エクスプローラー)。悪いときだけ理由と次の一手(例: 「空き容量が 10GB を切っています → 下の片付け」「版が違います → 起動し直す(9-3)」)
- 変えるファイル: `home/launch.py`(`/api/health`・大きさのキャッシュ)、新規 `home/health.py`(集める部品。テストしやすいように入口から分ける)、`editor/serve.py`(ping にワーカーの状態)、`home/portal.html`・`portal.js`・`portal.css`、`ytt_core/tools.py`(版を読む関数が無ければ足す)
- テスト: 新規 `home/tests/test_health.py`(偽のフォルダで大きさ・空き容量・エラーの件数・版の食い違い)、`home/tests/test_launch.py` に `/api/health` の形、`home/tests/e2e_portal.py` に「調子」の節が出る・悪い項目の札。★`python -m unittest home/tests/test_launch.py home/tests/test_mount.py home/tests/test_cases.py home/tests/test_autorun.py home/tests/test_window.py`・★`python home/tests/e2e_portal.py`
- リスク: フォルダを歩く処理を HTTP のスレッドで走らせない(別スレッド + キャッシュ)。Edge のプロファイル(app\profile)は大きいが「消してよい物」ではない(候補には出さない。大きさは出す)
- 終わりの条件: ホームの「詳しく」で、版・ワーカー・ffmpeg/yt-dlp・空き容量・作業データの大きさ・エラーの件数が1画面で分かる

### 9-2 作業データの大きさと片付け
- 候補の種類(**どれを候補に出すかはユーザー決定**。下の「決めてもらうこと」の 1): (a) スタジオの書き出しの元動画(`exports\`)のうち、パックができている・案件が「投稿済み」「見送り」のもの / (b) `作業用\` の途中のファイル(`.transcript.json`・`.clip.json` など。パックの記録から辿れないもの) / (c) 編集の波形のキャッシュ `cache\peaks`(いつでも作り直せる) / (d) 古いログ(`*.log.old`・`.1`)/ (e) 依頼の受付の `受付済み\`(9-4)
- 消し方(下の 2): 「ごみ箱フォルダ」`<作業データ>\ごみ箱\<日付>\` に**移す**(同じドライブなら一瞬)。14 日たったら入口の起動時に自動で消す(その旨を画面に)。すぐ消す方式は採らない(誤って消したときに戻せない。Windows のごみ箱は標準ライブラリから使えない)
- 画面: 「調子」の下に「片付け」の節。候補を種類ごとに(件数・合計の大きさ・古い順に 20 件と「すべて見る」)。チェックして「ごみ箱フォルダへ移す」→ 確認の dialog(件数・大きさ・戻し方)→ `POST /api/cleanup {items: [{kind, path}]}`(合言葉。パスは候補として出した物だけ = サーバーが候補の一覧を持ち、渡されたパスがその中にあるかを見る)
- 変えるファイル: 新規 `home/cleanup.py`(候補・移す・14 日で消す)、`home/launch.py`(API・起動時の purge)、`home/portal.*`、`docs/spec/data-location.md`(ごみ箱フォルダ)
- テスト: 新規 `home/tests/test_cleanup.py`(候補の判定・候補にない物は断る・移す・14 日の purge・別ドライブは copy+delete)、e2e_portal に候補 → 移す
- リスク: 「パックができている元動画」の判定は `ytt_core/txindex.pack_info` の規則(1か所)を使う。exports の動画を消すとスタジオの「書き出し済み」の行のリンクが切れる → 行に「片付け済み」の札(`studio/` の data.json は書き換えない。存在で判定)
- 終わりの条件: 候補が見え、確認して移せ、14 日後に消える。候補に出していない物は API でも消せない

### 9-3 版の赤い帯から「起動し直す」
- 今の動き: 取り込んだツール(スタジオ・編集・cut2resolve)は入口と同じプロセス。版の帯は「すべて終了 → start.bat」を案内するだけ
- 変えること: 入口に `POST /api/restart-self`(合言葉)。手順: (1) 新しい入口を**別のプロセスグループで**起動(`subprocess.Popen([python, launch.py, "--wait-port"], creationflags=CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS)`)、(2) 自分は「すべて終了」と同じ後始末(子を止める・`.runtime` を消す)、(3) 新しい入口は `--wait-port` でポート 8700 が空くまで最大 30 秒待ってから待ち受け、(4) 画面は「起動し直しています…」→ 数秒ごとに `/api/ping` → 戻ったら再読み込み
  - `start.bat` と同じ環境で起動する(`start.bat` が付ける環境変数・Python の選び方を `home/launch.py` の関数に寄せて、bat と API の両方がそれを使う)
  - 版の帯(ui-kit)に「起動し直す」ボタン(ホームから開いた画面だけ。単体で開いたときは今までの案内)
- 変えるファイル: `home/launch.py`・`start.bat`(共通の起動の関数を呼ぶ)・`ui-kit/ui-kit.js`(帯のボタン → 入口の API)・`ui-kit/README.md` → `python dev/sync_ui_kit.py`
- テスト: `home/tests/test_launch.py` に「restart-self が新しいプロセスを起こし、自分が終わる(偽の python で確かめる)」、`home/tests/e2e_portal.py` か新規 `e2e_restart.py`(本物に起動し直させ、ポートが戻る)
- リスク: 起動し直しの途中で友人の依頼が届く(受付は新しい入口が引き継ぐ。`intake-state.json` はファイルなので落ちない)。まとめて実行の途中なら「実行中の処理があります。終わってから」と断る(`SLOTS` を見る)
- 終わりの条件: 版の帯の「起動し直す」で、画面を閉じずに新しい版の入口に戻る

### 9-4 依頼の受付の運用
- 上限・間隔を設定から: ホームの「依頼の受付」の節に `dailyMax`・`maxHours`・`maxGB`・見る間隔(秒)の欄(値は下の 3 で決める)。`home/prefs.py` の `intake` の検査に範囲を足す
- 受け取った動画の片付け: `受付済み\` の動画は、その依頼のまとめて実行が終わって N 日(下の 3)たったら 9-2 の候補に出す(自動では消さない)
- 失敗を友人に知らせる(下の 4): ①だけの `出力\<依頼>.失敗.txt` を ②③ でも(受け付けなかった理由・途中で止まった理由)。友人のアプリ(request-sender)の「受け取る」がそれを一覧に出す(1.3.0 は `出力\` の一覧を出す仕組みがある)
- 変えるファイル: `home/intake.py`・`home/prefs.py`・`home/autorun.py`・`home/portal.*`・`request-sender/`(必要なら)・`docs/design/friend-intake.md` 9
- テスト: `home/tests/test_intake.py`・`test_autorun.py`・`e2e_intake_ui.py`
- 終わりの条件: 上限を画面から変えられ、失敗が友人に見え、受け取った動画が片付けの候補に出る

### 9-5 小さな注意
- VFR: パックの見積もり(`/api/edit/preview`)の warnings に probe の VFR の注意が入っているか確かめ、無ければ入れる。3 パック の注意に「区間の時刻が数フレームずれることがあります(可変フレームレート)」
- ドロップフレーム: 開始タイムコードにドロップフレームの表記(`;`)を入れたときの注意を、3 パック の詳しい設定の欄の下に出す(今は結果の warnings だけ)
- AV1/H.265/10bit: probe のコーデックを見て見積もりの warnings に「無料版の Resolve では再生できないことがあります」(vp9 と同じ形。`cut2resolve_core.py` の warnings に足す)
- 変えるファイル: `cut2resolve/cut2resolve_core.py`・`editor/pack-tab.js`・`editor/index.html`。テスト: `cut2resolve/tests/test_cut2resolve.py`・`editor/tests/e2e_edit_pack.py`

### 9-6 版・文書
- 入口 0.19.0 → 0.20.0(9-1〜9-4)。編集は ping の形が増える(0.30.0 → 0.31.0)。cut2resolve は 9-5 で注意が増えれば 0.16.0 → 0.16.1。ui-kit は 9-3 で帯のボタンが入れば v10
- `home/README.txt`(調子・片付け・起動し直す・受付の設定)・`docs/spec/data-location.md`(ごみ箱フォルダ)・`docs/design/friend-intake.md` 9・`docs/ROADMAP.md` の段9 の行と 3

## 実機で確かめること
- 「調子」の数字(空き容量・大きさ)がエクスプローラーの表示と合う。数え直すで更新される
- 片付けの候補に出た元動画をごみ箱フォルダへ移し、スタジオの行に「片付け済み」が出る。14 日後(日付を進めるか、設定で日数を短くして)に消える
- 版の帯の「起動し直す」で新しい入口に戻る(まとめて実行の途中なら断られる)
- 依頼の受付の上限を画面から変え、超えた依頼が「明日に回す」になる。失敗の理由が友人のアプリに見える

## 決めてもらうこと(始める前にユーザーに。**2026-10-01 決定済み**: 1 = 入れる、2 = ごみ箱フォルダ(14 日)、3 = 今のまま・14 日、4 = 知らせる)
1. 片付けの候補に**スタジオの書き出しの元動画**(パックができている・案件が投稿済み/見送りのもの)を入れるか(入れないなら、途中のファイル・キャッシュ・古いログだけ)
2. 消し方: ごみ箱フォルダに移して 14 日後に消す(おすすめ)か、確認のあとすぐ消すか
3. 依頼の受付の上限と間隔: 1日 5 件・1本 8 時間・20GB・30 秒ごとのままでよいか。受け取った動画を片付けの候補に出すまでの日数(案: 14 日)
4. 失敗を友人に知らせるか(Dropbox の `出力\` に `失敗.txt` を置く。今は ① だけ)
