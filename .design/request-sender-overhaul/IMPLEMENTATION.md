# 実装の進め方と引き継ぎ(切り抜き依頼 2.0.0・ホーム 0.23.0)

> 状態(2026-10-02): 実装中。仕様の正は同じフォルダの `DESIGN_BRIEF.md`。この PC は不安定でセッションが落ちるので、**きりのいい所ごとにコミットし、下の「進み具合」を直す**。
> 再開するときの指示文: 「`.design/request-sender-overhaul/IMPLEMENTATION.md` の進み具合の続きから進めて」

## 分け方(担当するファイルが重ならない)
- A. 友人のアプリの画面に依らない部品 … `request-sender/src/TimeCore.cs`(新規)・`Core.cs`・`Sending.cs`・`tests/CoreTests.cs`(まとめ役 = Fable)
- B. 友人のアプリの画面 … `request-sender/src/Theme.cs`・`Controls.cs`・`MainForm*.cs`・`Program.cs`・`README.txt`(サブエージェント Opus。A の API の上に載せる)
- C. PC 側 … `studio/store.py`・`studio/serve.py`・`home/intake.py`・`home/autorun.py`・`home/portal.js`・テスト・文書(まとめ役 = Fable)

## C. PC 側の設計(決めたこと)
- スタジオに依頼用の API `POST /api/video/request-marks` {id, title?, channel?, ranges: [[開始, 終了]…], auto: n}
  - 配信の記録が無ければ作る(YouTube の ID だけ。解析は要らない)
  - ranges = 余白を付けたあとの区間。同じ区間(±0.5 秒)のマークがあればそれを使い、無ければ手動マークを「採用」で足す(不採用だったものは採用に戻す)
  - auto = 自動で埋める数。自動マーク(src auto・不採用でない・ranges と重ならない)を点数の高い順に n 個。まだ候補のものは採用にする。採用・書き出し済みのものも数に入れる(使い回し)
  - 人の判定ではないので、学習の記録(feedback)・コラボへの転写はしない(adopt-top と同じ)
  - 返り値 {rangeIds, autoIds, video}。まとめて実行はこの id だけを扱う(run.marks)
- `home/intake.py`: `items[].ranges`(0〜10 個・秒・0 ≤ 開始 < 終了・長さ 3600 以下。flow manual では捨てる)・`cut`(none / silence。auto だけ)・`weights`(0〜3 の数3つ)を読む。
  配信の URL の重複(「前に受け付けた配信です」)は断らない。区間が配信の長さを超えたら、終了を配信の長さに切り、開始が長さ以上なら断る
- `home/autorun.py`: 依頼(URL)の実行は `Run.ranges`(余白の前)・`Run.cut`・`Run.weights` を持つ。
  - 余白 `RANGE_PAD = 2.0` 秒を前後に付けてスタジオへ(0 より前・配信の長さより後は切る。3600 秒を超えるなら余白を減らす)
  - 段: 自動の分があるとき(top > 区間の数)だけ「解析」→「採用」(request-marks)→ 書き出し → 文字起こし →(話者分離)→ パック → 届ける
  - 解析: 済みで、重みの指定が無いか同じなら飛ばす(使い回し)。重みが違えば解析し直す(音量・チャットのキャッシュを使うので軽い。手を入れたマークは残る = `replace_auto`)
  - パック: 依頼の ① は、同じ名前のパックがあっても今回の設定で作り直す(force)。カットは `Run.cut`(無ければホームの設定)
- ホームの依頼の一覧(`portal.js`): 区間・カット・重みの札

## 進み具合
- [x] A-1 TimeCore.cs(時刻の読み書き・時刻の欄の状態・区間・カット・重み・題名の読み取り・設定)+ テスト + build.bat
- [x] A-2 RequestJson・Sending を新しい形に(items・ranges・cut・weights)
- [ ] B 画面(配色4つ・横2列・配信のカード・時刻の欄・知らせ・--screenshot)
- [ ] C-1 スタジオ request-marks + テスト
- [ ] C-2 intake + テスト
- [ ] C-3 autorun + テスト
- [ ] C-4 portal.js・e2e
- [ ] 版(アプリ 2.0.0・ホーム 0.23.0・スタジオ 0.14.0)・README・friend-intake.md・ROADMAP・WORKLOG
- [ ] Phase 3: 画面の見直し(frontend-design・baseline-ui・design-review)と、ユーザーの依頼「完成したら最後にもう一度 UI を見直して改善点を探す」

## B の進み具合(画面の担当が書く。落ちても続きから進められるように、終えた所を1行ずつ)
