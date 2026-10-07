# HANDOVER — 次のセッションへの引き継ぎ(2026-10-08 0 時台。10-07 夜の作業(線 D の前倒し・送るアプリ 2.3〜2.5・ホーム 0.44〜0.45.1)の資料とソースの整理まで済み)

セッションを切り替えるたびに上書きする。全体の計画と進捗は `plan/index.html`(データ `plan/data.js`)、文書の索引は `docs/ROADMAP.md`、経緯は `docs/WORKLOG.md`、規則は `AGENTS.md`。

## いまの状態
- 作業フォルダは `C:\dev\youtube-tools`(GitHub: https://github.com/sirloin2983/youtube-tools1)。**push はユーザーが `push.bat`**
- **版(コミット済みの最新)**: 入口 **0.45.2**・スタジオ **0.23.1**・編集 0.59.4・cut2resolve 0.22.2・録画 0.3.2・ui-kit v23・送るアプリ **2.5.1**・ホロカラー 1.4.3(正は各ファイル。`plan/data.js` の版の表も同じ)。
  **起動中の入口は 0.45.0**(10-07 23:41 に起動し直し済み。0.45.1 の保存期間 3 日と 0.45.2 の整理はまだ)→ ユーザーが「すべて終了」→ start.bat で 0.45.2 に(10-07 夜の配信 2 本目の M7 が終わってから)
- **10-07 夜に入ったもの(全部 main)**: 線 D の前倒し = L1〜L3・M11・M9 + M12・M8・M10(検出 `live.detect`・自動採用 `live.autoAdopt` は試験中の機能のスイッチで既定オフ。順番と実績 `plan/line-d-detect.md`、仮決め `plan/decisions.md` の 3-7)/
  送るアプリ 2.3.0〜2.5.0 + ホーム 0.44.0〜0.45.1(すべて受け取る・やめる・保存先に展開・n 本ごとに 1 つの zip + 2 倍速のまとめ動画・「まとめ動画を見る」「要らない」・1 日の上限の撤廃・保存期間 3 日。仕様 `docs/spec/friend-intake.md` の 2-12・2-13、保存の方針 `docs/spec/data-location.md`、仮決め 3-9)/
  クラウドの文字起こしの比較の道具 `dev/eval_cloud.py`(3-10。ユーザーのキー待ち)/ I-5 区切りの正解づくり(別セッション。下の節)/ 1 秒丸めの配り直しを既定オフ(編集 0.59.4)
- **10-08 0 時台: 上の継ぎ足しの整理**(ユーザー「今日やった作業を各資料に整理してソースも最適化して。変更した部分の周辺だけでよい」)。資料: 2-12/2-13 を今の仕様に・decisions 3-7/3-9 を話題ごとに(置き換わった仮決めに →)・line-d-detect を実績に・data-location に保存の期限の表・README の v0.43.1 を 1 つに。
  ソース(動きは同じ): 入口 0.45.2(deliver/autorun/cases/cleanup/prefs の重複を 1 か所に・excite/ワーカー/live_detect の継ぎ足しを共通の関数に。式は乱数の配信 40 本で完全一致)・スタジオ 0.23.1(review.js の候補の帯・settings・portal)・送るアプリ 2.5.1(`Receiving.ReceiveOne` に一本化)・eval_cloud(引数の検査・鍵を文に出さない)。詳細は WORKLOG の 10-08 の記録
- **並行セッション(10-08 0 時台に起動。「送るツール競合対応と一括受け取り機能」)**: 送るアプリ 2.6.0(友人の「要らない」を PC に戻す `.feedback.json`・新規 `src/home/friend_feedback.py`・まとめ動画を等速で札をずっと・zip に まとめ.mp4 を入れない)を作っている。こちらのコミットの hash を知らせ、向こうが src/home と共有の文書を HEAD + 自分の置き換えで当てる約束。
  **次のセッションは `git log` でそのコミットが入っているか見る**(入っていれば spec 2-13・decisions (dk)(dl)・README v0.45.0 の「2 倍速・zip の中の まとめ.mp4」が変わっているはず。入っていなければ文書は 10-08 0 時台のまま)
- **ユーザーにしてもらうこと**: ① 「すべて終了」→ start.bat(0.45.2)② `dist\RequestSender\RequestSender.exe` を閉じて `friend-apps\request-sender\build.bat` → zip を友人へ(U8。2.6.0 ができていればそちら)③ 10-18/19 に試験中の機能で「配信中の候補」をオンにして配信 1 本(L4'。自動採用もオンで試してよい = 10-07 夜の決定)④ `plan/decisions.md` の 3-4〜3-10 の仮決めの確認 ⑤ E1 のクラウドのキー 2 つ(`%USERPROFILE%\youtube-tools-keys.txt`)
- **次の AI の作業の候補**: 10-07 夜の配信 2 本目の M7 の結果(`GET /live/api/exports?recorder=local&recording=20261007-193336-kLsldZDUa70` の archiveInfo.afterStream)を WORKLOG と data.js に / `plan/improvements.md` の 12(M8 の余白 2 秒・仮の候補の札・`Detector._seen` が増え続ける件)/ B2 のクラウド比較(キーが来たら `py -3.10 dev/eval_cloud.py run --service … --model …` → 見積もりを見せて確認 → `--send`)
- Linux で前から落ちるテスト(Windows では通る): home の `test_live` 2 件(`E:\` のパス前提)と `test_cleanup.test_move_only_known_and_purge`(一覧の順が OS で違う)、editor の `test_roster` 2 件 + `test_evalaudio` 1 件(Windows のパス前提)

## I-5 区切りの正解づくり(2026-10-07 深夜。別セッション(Opus)。ユーザーが 22 本を直している途中かもしれない)
- 計画と基準: `plan/line-b-row-split.md`(1 答え・2 見比べ・3 机上評価・6 正解の限界・7 手順と基準 P1〜P6・例)。ユーザーは確かめ済み 22 本を、候補の一覧(`D:/backup/youtube-tools-eval/split-draft2-20261007-2157.html`)を横に置いて、分ける・くっつけるだけ直す(文字と時刻は直さない)
- 控え(直す前): `D:/backup/youtube-tools-eval/split-before-20261007-2111.json`。道具の写し: `D:/backup/youtube-tools-eval/tools/`(diff_after.py = 控えとの差分から判断の一覧 / cmpdata.py・compare.py・rules3.py = 人の境目との一致率。元は AI の scratchpad。作業データは読むだけ)
- **ユーザーが「直し終えた」と言ったら**: `py -3.10 D:/backup/youtube-tools-eval/tools/diff_after.py`(判断の一覧 = そのまま・くっつけた・分けた と、境目の無音・句末・長さ)→ `compare.py`・`rules3.py`(sys.path の scratchpad のパスを tools/ に直して)で新しい正解での的中・再現 → 規則を決める(今の候補は「24 文字まで切らない」+ 無音で切る。数字で決める)→ `src/editor/ed_jobs.py` に実装(編集 0.59.5)+ `dev/eval_timing.py` に境目の一致率 + `eval_timing` で ①〜③ を測り直して新しい基準に。文書: `plan/line-b-row-split.md` の 8 と data.js の B3

## 次のセッションに貼る指示文
「AGENTS.md → plan/data.js → docs/HANDOVER.md → docs/WORKLOG.md の末尾 3 件 → git status・git log -10 を見て。10-07 夜の線 D の前倒し(L1〜L3・M11・M8〜M10・M12)と送るアプリ 2.3〜2.5 + ホーム 0.44〜0.45.1 は全部 main に入り、10-08 0 時台に資料とソースを整理した(入口 0.45.2・スタジオ 0.23.1・送るアプリ 2.5.1)。並行セッションの送るアプリ 2.6.0(友人の「要らない」を PC に戻す・まとめ動画を等速)が入っているか git log で確かめる。まず 10-07 夜の配信 2 本目の M7 の結果と、ユーザーが起動し直したかを確かめて WORKLOG と plan/data.js に記録。次に plan/improvements.md の 12 を小さく直し、単体と e2e_live_studio・e2e_portal・ui_audit all --demo で確かめてコミット。ユーザーが検出オンで配信を 1 本試したら、調子・LIVE の帯・live/excite/<rc>/<rec>/peaks.json・excite.log を読んで結果(候補の数・遅れ・チャットの起動し直し・CPU)を WORKLOG に書き、0-10-5 の数を決め直す。迷う点は仮決めして decisions の 3-7 か 3-9 に (do) 以降の記号で。」

## 注意(引き継ぐこと)
- **`friend-apps\request-sender\build.bat` は dist の exe が動いていると [3/4] で止まり、その前に dist の README・members.json・鍵 config.json を消す**(10-08 0 時台に起きた。既存の zip から戻した)。流す前に RequestSender.exe が動いていないか確かめる(AI はユーザーのプロセスを止めない)
- 入口が起動中にフォルダを動かすと、録画の部品(`recorder.py`)のプロセスがフォルダを掴んで移動できない。入口の「すべて終了」では録画の部品が止まらないことがある(10-07)。ユーザーにタスク マネージャーで止めてもらう
- Claude Code のアプリ(Code タブ)から動かす AI は MSIX の中なので、`%LOCALAPPDATA%` への書き込みは写しに入る(`AGENTS.md` の動作環境)。作業データは入口の API を通すか、パッケージの外のプロセスで書く
- 同じ作業フォルダで複数のセッションが動くことがある(10-08 0 時台も)。始めに `ListAgents` で busy なセッションを見て、触るファイルを知らせて担当を分ける。共有の文書は自分の差分だけ index に入れる。`git add -A` は使わない
- クラウドの Claude Code(claude.ai/code)は PC のフォルダを見ない。GitHub のブランチに push するので、PC 側で取り込む。**PC 側でコミットしたら早めに push する**(push していないと、クラウドと同じ版番号・同じ仮決めの記号を付けてしまい、合流で衝突する = 10-07 の合流)。`python` は `python3`・node は `/opt/node22/bin/node`・Segoe UI と Cascadia が無い・YouTube の埋め込みは読めない
- Claude Code のアプリがときどき落ちる(セッションが途中で切れる)。項目ごとにコミットする。再開は「続行」で止まった所から。WORKLOG の「未コミット」と `git status` を突き合わせる
- 2026-09-23 に、Claude が配った zip で GPT の変更が上書きされて消えた。**古い控えからのファイル丸ごとの上書き・zip 配布はしない**
- PC の不安定(i9-13900KF)は 10-04 に CPU を i9-12900KF に替えて解決したとみなす。異常終了は本物の失敗として調べる(入口の「調子」の「異常終了(7 日)」)
