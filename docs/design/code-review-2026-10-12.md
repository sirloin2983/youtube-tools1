# コードレビュー 2026-10-12

状態(2026-10-12): レビュー済み。指摘 7 件、修正は未着手。対象 HEAD `b077d954`、全体の版 0.61.0。開始時の未コミット変更なし。

ユーザーの依頼「このフォルダのツールのコードレビューをしたい。重要なポイントはアストラに聞いてもよい」に基づく。既存の RV 下調べとは別に、動作・保存・処理の境界を確認した。GPT が案件データ・HTTP・カット保存、Astra が実行・中止・CLI、通常モデルのサブエージェント 2 体が確認/校正と友人向け同期を担当。実装・本物の作業データは変更していない。

重点範囲: `src/app/` の入口・CLI・案件/確認画面、`src/flow/` の実行と結果・同期、`src/human/check/`・`src/eval/check/`、案件データの移動/一覧、友人用アプリの同期と終了。全ファイル・全機能の網羅を保証するレビューではない。既に WORKLOG にある友人アプリの暫定要件は重複報告から外した。

## 指摘

### 1. [P1] カット保存中の切り替えで最後の変更を失う

- 位置: `src/app/ui/cases/panels/cut.js:587–591`、関連 `src/editor/cut.js:207–220,1204–1209`。
- 条件: 1 回目のカット保存の応答を待っている間にさらにカットを変更し、別の切り抜き/タブへ移る。
- 原因: teardown は `cut.onHidden()` で保存を呼ぶが完了を待たず `cut.dispose()` を呼ぶ。既存の保存中は `save()` がその Promise を返すだけ。dispose が `M.docId=null` にするため、先の応答が返っても `save` は ID 不一致で戻り、2 回目の変更を送るループへ進まない。保存タイマーも消される。殻に track するのは文書の saveDoc だけで、カットの保存は含まれない。
- 影響: 最後に編集した区間が保存されず、開き直すと前の区間へ戻る。
- 再現: 実際の `cut.js` の `save` 関数を Node VM で動かし、応答待ち中の再変更→onHidden 相当の save→dispose の ID 無効化を実行。送信は最初の変更 1 件だけ、最後の状態は `dirty=true, docId=null`。
- 修正方針: パネルを閉じる際に `CUT.flush()` の完了を待ち、保存を殻に track してから dispose する。保存失敗/競合時の未保存状態も失わないようにする。

### 2. [P2] 確認画面で表示した読みとは別の読みを採用する

- 位置: `src/app/server.py:935–938`。
- 条件: 確認カードを表示/先読みした後、別エンジンの再実行などで `.alt.json` の候補が変わり、そのカードで「2」を選ぶ。
- 原因: 回答時は同じ ID からカードを再生成するが、表示時の選択肢/版との一致を検査しない。回答には選択肢の番号だけが渡る。読み反映の文字照合も再生成後の候補を使うので防げない。
- 再現: 表示時は 1=`AAA BBB CCC`、2=`AAA XXX CCC`。alt を `AAA YYY CCC` に変えて `deck.find → apply.answer(choice="2")` を実行すると成功し、`AAA YYY CCC` が保存される。
- 修正方針: 候補/表示内容の fingerprint を ID または回答の版に含め、変わったカードへの回答は再読み込みを要求する。

### 3. [P2] 同じ行の残りの読み候補が確認対象から消える

- 位置: `src/eval/check/read_sources.py:82–85`、関連 `src/eval/check/deck.py:69–70`。
- 条件: 同じ行に alt/yt の相違が複数ある状態で、最初の候補に回答する。
- 原因: 候補には別々の `_cand` が付くがカード ID は種類/出どころ/文書/行だけ。次の候補も回答済み ID と一致して除外される。
- 再現: 本文 `Today is sunny. Tomorrow is rainy.`、alt `Today is cloudy. Tomorrow is snowy.`。最初の候補を「今の字幕」で却下後、sources は別の候補を生成するが `deck.next_cards(kind="read")` は空。再読み込みでも出ない。
- 修正方針: 候補ごとの識別子を使う。項目 2 と合わせて候補の fingerprint を導入すれば両方を解決できる。

### 4. [P2] CLI の失敗/中止の結果を成功として上書きする

- 位置: `src/app/cli.py:410`、呼び出し `:464`、関連 `src/flow/placement.py:303`。
- 条件: 入口を介さない CLI 実行で StepError または Ctrl+C が発生する。
- 原因: flow.run が例外つきで失敗結果を保存した後、CLI が例外を None にして保存し直す。placement._outcome は run.state を見ず、例外なし/run.cancel が偽なら done と判定する。
- 再現: 実 `run_local → run.run → placement.result`、認識・ロック・保存だけ mock。`exitCode=1, publicState=error, firstSavedState=error, finalSavedState=done, finalSavedFailures=[]`。失敗中の文字起こし段も skip へ変わる。
- 影響: 終了コードと画面への応答は失敗だが、案件に残る結果の束は成功になり、失敗理由を失う。
- 修正方針: 重複保存をなくすか、例外/中止状態を最後の保存まで保持する。

### 5. [P2] 既に解析中の配信を全自動へ進めると待たず失敗する

- 位置: `src/flow/run.py:774`、関連 `src/flow/batch.py:23`。
- 条件: 同じ配信が手動解析中/順番待ちのとき、まとめて実行を頼む。
- 原因: 既存解析を待つ判定は拒否文に「すでにキュー」が含まれるかを見る。現在の DUP_MSG は「すでに解析の順番待ちにあります」で一致しない。
- 再現: 実際の batch.DUP_MSG を返す道具で `_analyze_item` を実行すると StepError、既存解析を待つ analyze_items の呼び出しは 0 回。
- 修正方針: 表示文ではなく duplicate のエラーコードなどで判定する。

### 6. [P2] 学習同期の成功が実行中の処理へ反映されない

- 位置: `src/app/server.py:902–904`、関連 `friend-apps/request-sender/src/Sync.cs:173–207`。
- 条件: 友人PCの入口が起動した後、学習の束を初回または新版へ同期する。
- 原因: PUT /api/flow/machine は learningDir を保存するだけで、起動時の wire_learning の読み手・辞書・名簿・声の参照を更新しない。送るアプリは 200 を受けて applied=true とし同版の適用を再試行しない。
- 再現: 一時の有効な learning.json/learned-rules.json で実 `_put_machine` を呼ぶと、200 と新しい保存先が返る一方、`doc_jobs._learning[0]` は None、`workdata.SETTINGS` は不変。
- 影響: 再起動まで学習が使われない。同期が 4 版以上進むと整理で参照中の旧版も消され得る。
- 修正方針: 処理の安全な境目で学習を適用し、適用済み版を返す。参照中の版を整理対象から外す。

### 7. [P2] 送り返し完成前に「終わったら閉じる」で終了できる

- 位置: `src/flow/runqueue.py:752–757`、関連 `friend-apps/request-sender/src/Progress.cs:412–416`。
- 条件: 友人PCで「終わったら閉じる」が有効で、処理後の送り返し zip を作っている間に status が読まれる。
- 原因: 実行を done にし待ちの記録から外した後、zip を作る終了 hook を呼ぶ。この時点で idle は真。アプリは idle で閉じて入口を終了する。終了 hook の糸は daemon、Queue.close はその完了を待たない。
- 再現: 実 Queue の終了 hook を Event で待たせると `idle=true, daemon=true`、active 記録は `{"v":2,"runs":[]}`。close は即戻り、糸は生存したまま。アプリの Close→StopBackend→shutdown の呼び出し経路も確認。
- 影響: zip 作成が途中で終了し得る。待ちの記録からは削除済みなので次の起動でも作り直されない。
- 修正方針: 終了 hook の完了まで idle を偽にするか、終了時に hook を待つ。送り返しを再試行できる永続記録を持つ。

## 検証と限界

- `dev/lint.py`: 0 件。
- Python 3.10.11 で `dev/tests/test_layering.py`・`src/ytt/tests/test_docloc.py`・`src/manage/cases/tests/test_docmove.py`・`test_markmove.py`・`test_cases.py`・`test_docloc_listing.py`: 計 138 件 OK。
- `py -3.10` はこのシェルでは Python を発見できず、インストール済みの Python310/python.exe を直接使用した。
- 最初の unittest は sandbox の一時領域の atomic replace が WinError 5 で失敗。同じ検査を許可された通常権限で再実行するとすべて成功したため、最初の失敗は製品の不具合に数えていない。
- 指摘の再現は一時データ/モックで実施。実配信・GPU認識・本物のDropbox・実ブラウザの遅延再現・e2e一式は実施していない。
- セキュリティ境界も調べたが、今回確証を得た追加のセキュリティ指摘はない。安全性の保証を意味しない。
