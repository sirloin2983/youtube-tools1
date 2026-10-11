# 役割で組み直す(ツール全体のコードの役割分担。2026-10-09)

> 状態(2026-10-10 夜): **RS6 の実装は済み・本物の確認待ち(入口を起動し直して本物の 1 本・CLI の 1 本。結果は 8 節の「RS6 の結果」)。層を 5 つに組み替え済み(決定 3-29。① 道具 `pipeline/`・② 管理 `flow/`(新)・③ 人 `human/`・④ データ `manage/`・⑤ 検証 `eval/`)。import の向きは `ytt ← pipeline ← flow ← human ← manage ← eval`(`dev/layer_map.py` の ALLOWED。③④ は ① を直に読まず ② を通す・⑤ は ① を直に読んでよい・② に変換のコードを書かない)・違反 0(`KNOWN_MAX` 0)。新機能(鍵・校正の上書き・採用の統一・結果の束・.flow.lock・CLI)は入った。詳しくは `plan/decisions.md` 3-29 と `docs/design/rs6-survey-2026-10-10/`(plan_order_v2.md・layer5_review.md・option_b.md)。3〜7 節は新しい番号に付け替えた。8 節の表と下の経緯(RS0〜RS5 の記録)は当時の番号(① 自動の流れ・② 人・③ データ・④ 検証・`pipeline/run.py` など)のまま。** 以下は 10-10 午後までの状態の記録: **RS0〜RS4 済み・向きの違反 0(`KNOWN_MAX` 0)。RS5 の前半(10-10 午後)済み: 殻 10 本を消した・旧い名前 `ytt_core` の import を `ytt` に・疑似の旗の口・版 1 つ(0.56.0 仮)・友人の依頼の ②③ をやめた(L1)と送るアプリ 2.10.0。次は RS5 の残り(入口を起動し直したあとに旧パスの転送を消す・app を薄く・文書を新しい形に)。RS3・RS4 の結果は 8 節の下(段の表と、計画と違えた所)。RS1〜RS4 の分は入口を起動し直して本物の 1 本の確認が要る。以下は RS3・RS4 に入る前までの状態の記録: RS0・RS1・RS2 済み(RS1 は入口を起動し直して本物の 1 本の確認待ち。RS2 の分も同じ確認が要る)。RS2 は 10-10 に RS2-0〜9 まで済み: RS2-8 で `ed_jobs` を `human/proof` の `doc_jobs`・`rerun` に移して転送の殻(35 行)にし(違反 66 → 59)、RS2-9(早朝)で `ed_speakers` を判別 `pipeline/transcribe/diarize.py` と文書の側 `human/proof/speakers.py` に割り(殻 25 行)・`ed_fill`・`ed_llm`・`ed_retime` の計算・認識ワーカー `tx_worker` を `pipeline/transcribe` へ移した(違反 59 → **49**。仮決めは `plan/decisions.md` 3-24 = 未確認)。次は RS3・RS4 = 10-10 朝に下調べ済み・手順の案と決めてほしいこと(`plan/decisions.md` 3-25)は 8 節の下・下ごしらえ 0A・0B は仮で実施して済み = 違反 49 → 25**。RS1 の結果は 8 節の下。RS0 = 層のフォルダ(空)`src/{ytt,pipeline,human,manage,eval,app}`・ファイルの行き先の表 `dev/layer_map.py`・向きの検査 `dev/tests/test_layering.py`(今ある違反 69 件を KNOWN に。減らすだけ)・関数ごとの行き先 `docs/design/role-restructure-map-2026-10-09.md`。10-09 の議論(セッション「ツール全体のコードの役割分担」)で形まで決めた(`plan/data.js` の RS0〜RS6)。前の案 `plan/code-separation.md`(fake.py・measure.py で中だけ分ける)はこの計画に置き換えた。棚卸しの行番号つきの表 `docs/design/code-separation-inventory-2026-10-09.md` は行き先を決める根拠として使う。

## 1. なぜ組み直すか(ユーザーの言葉)
- 「もともと 1 個ずつ開発して合体したからいびつになっている。今の形を完全に変えてもいいから最適な形を考えて」
- 機能の重要度を 5 つに分ける(10-09 は 4 つ。10-10 夕に ② 管理を足して番号をずらした): **① 解析 → 文字起こし → 話者 → パックの自動の流れ(ライブと動画を含む)を中心にし、これだけで一通り動く(① + α で友人に配れるのが理想)** / ② 管理(10-10 夕に追加。① をいつ・どの順で・どこに置いて・飛ばすかを決める) / ③ 校正・カット・友人の依頼の受付と送信 / ④ データの管理 / ⑤ テストと精度の検証
- 友人用の Windows アプリと Chrome 拡張は置いておく。UI(画面)は後で再考する(この計画は画面の作りを決めない)

## 2. 決めたこと(10-09 の問答の答え)
| 問い | 答え |
| --- | --- |
| 自動と人の役割 | **最終的に自動が中心**。人が操作する理由は (a) 自動の精度を上げるため (b) 確実に切り抜きたい所を指定するため |
| ① の入力 | **URL か動画ファイル + 処理に必要な指定の束**(切り抜く数・長さ・重み・エンジン・パックの設定・API キー)。URL が配信中ならライブの処理。① は案件も画面も知らない |
| 友人の依頼 | 友人の依頼を処理する機能は友人に渡さない。自分の環境でも「送られてきた動画ファイルを ① に流すだけ」= ③ は ① を呼ぶ薄い層 + 届ける |
| API キー | コメントの解析で使うので ① の中。配信の検索(`rank.py`)は ① の外(③) |
| ④ の中身 | 流れの状態(案件・紐づけ)・保管と片付け(バックアップ・ごみ箱・録画の片付け・置き場所)・運用(調子・失敗の集約・分析と日報)**すべて** |
| 友人への配布 | ① + α で少し足せるので、その時に考える |
| 形 | 今のツール分け(工程ごと)をやめ、**役割の層で切る**(3 節)。import の向きをテストで守る |
| 人の作業と ① の関係 | **終わってから直して、その段からやり直す**(4 節)。止めて待つ形は作らない。友人の依頼の「確認してから届ける」の経路は、この実装が終わったら消す |
| 精度の向上 | 2 本立て(6 節): (A) ① のコードを ⑤ の物差しで測って直す / (B) ③ が人の直しから作る学習データを ① が読む |

## 3. 目標の形
```
src/
├─ ytt/        基盤(今の ytt_core から excite を除く。書き込み・検査・置き場所・設定・外部プログラム・30fps)
├─ pipeline/   ① 自動の流れ。段ごとの部品 + 流れ。画面なし。これだけで URL か動画 → パック
│   ├─ ingest/      取り込み: URL か動画ファイルの判定・取得(yt-dlp)・配信中なら録画(今の recorder)
│   ├─ analyze/     解析: 盛り上がりの式(excite)・チャットとコメント・候補・自動採用・配信中の検出
│   ├─ export/      書き出し: 区間 → 動画(exporter・live_export)
│   ├─ transcribe/  文字起こし: 認識(エンジン・ワーカー)・話者・後処理(埋める・LLM・時刻)・名簿と辞書を読む
│   ├─ pack/        パック(今の cut2resolve の pack・textplus・core)
│   ├─ spec.py      指定の束の形と既定値(RS6 で ② flow/spec.py へ移した)
│   └─ run.py       流れ: run(入力, 指定, from=段) → 結果。配信中なら録画しながら。配信後の全自動もここ(RS6 で ② flow/run.py へ移した)
├─ flow/       ② 管理(RS6 で新設)。① をいつ・どの順で・どこに置いて・飛ばすかを決める。変換のコードは書かない(① の別名だけの関数も作らない)。画面と案件を知らない
│   ├─ run・spec・batch・runlog   流れ・指定の束・まとめて解析・実行の記録
│   ├─ tx・diar・pack・ingest・jobs   段ごとの口(③④ は ① を直に読まず、ここを通して使う)
│   ├─ keys・wire・tools   成果物の鍵・登録の口・道具の継ぎ目
│   └─ live_*      ライブの段取り(archive・detect・export・failures・report・tx)
├─ human/      ③ 人の操作。① の成果物とは別に「上書き」を書き、その段からやり直しを頼む。学習データを作る
│   ├─ review/      候補の確認(手動マーク・採用と不採用・端の調整・その記録)
│   ├─ proof/       字幕の校正(文書・別の読み・YouTube の字幕・辞書と名簿と声の学習・校正の記録)
│   ├─ cut/         カット(残す区間・たたき台)
│   ├─ find/        配信の検索(YouTube Data API・事務所の登録)
│   └─ friend/      友人: 受付(Dropbox)→ ① に流す → 届ける。ライブの依頼の結びつき
├─ manage/     ④ データの管理
│   ├─ cases/       案件(配信 1 本の束ね)・紐づけ(切り抜き ↔ 文字起こし ↔ パック)・成果物の鍵の読み取り
│   ├─ keep/        置き場所・バックアップ・ごみ箱・録画の片付け
│   └─ ops/         調子・失敗の集約・起動し直し・エラーの記録・分析と日報
├─ eval/       ⑤ テストと検証
│   ├─ fake/        疑似モード(偽のエンジン・偽の YouTube API・偽の録画元)を登録の口から差し込む
│   ├─ drill/       評価ドリル・評価用フォルダ・精度のカード・A/B・精度の自動測定
│   └─ tools/       今の dev/eval_*(物差し)・_evalcommon・demo_env
├─ app/        入口と画面
│   ├─ server.py    起動・1 つのポート・API の配線・設定の画面の API(薄く)。旧い URL(/studio/ など)の転送
│   └─ ui/          ホーム・確認の画面・校正の画面・ui-kit(作りは後で再考。当面は今の画面をそのまま置く)
dev/           リポジトリの道具だけ残す(lint・ui_audit・push_helper・sync_ui_kit・plan_artifact・dropbox_auth)
```
テストは各パッケージの `tests/` に(今のまま)。`friend-apps/`・`chrome-ext/`・`setup/` は変えない(`start.bat` の起動先だけ `src/app/server.py` に)。

## 4. 守る決まり
1. **import の向き**: `ytt ← pipeline ← flow ← human ← manage ← eval`。`app` は全部を使ってよい。import してよい相手は `dev/layer_map.py` の ALLOWED の表(順位の比較ではない): `pipeline` は ytt だけ・`flow` は ytt と pipeline・`human` は ytt と flow・`manage` は ytt と flow と human・`eval` は pipeline も含めて ytt から manage まで全部。**③ 人 と ④ データ は ① を直に読まず ② を通す**(⑤ は ① を直に読んでよい。本物の作業データへ書くときだけ ②)。**② に変換のコードを書かない**(① の別名だけの関数も作らない = `test_flow_is_not_alias`)。逆向きは**テストで落とす**(各パッケージの import を機械で読み、表と比べる。`dev/tests/test_layering.py`)。移す途中は「今ある違反の一覧」を許し、減らして 0 にする(RS6 a で 0 にした)
2. **① は画面と案件を知らない**。① の結果は「ファイルと JSON(横に鍵の JSON)」だけ。③ と ④ がそれを読む
3. **人の直しは ① の出力を書き換えない**。③ は別の「上書き」として保存し、① はどの段を動かすときも「自動の出力 + 上書き」を読む。① を再実行しても上書きは消えない
4. **成果物には鍵を付ける**(5 節)。同じ鍵の成果物があれば作らない = 使い回し。飛ばす判定は「記録に済みと書いてある」ではなく「鍵が一致する」
5. **① の記録と ③ の記録は別**。① は自分が何をしたか(認識の生の結果・候補の点数・使った指定と版)を結果に残す。③ は人がどう直したか(採用と不採用・校正)を残す。⑤ はその 2 つを読むだけ
6. **実験は指定の違いで**。① のコードに実験用の `if`・疑似モードの `if` を入れない。各段に「エンジンの登録の口」を 1 つ置き、`eval/fake` が偽物を、実験が別の設定を登録する。採用したら既定値を変える
7. **作業データの場所と URL は当面そのまま**(`%LOCALAPPDATA%\youtube-tools\{studio,transcribe,app}\`・`/studio/` `/transcribe/`)。コードの単位とデータの単位を一度に変えない。案件ごとに 1 フォルダにする形(b2)を段で寄せる: RS6 は B-0・B-1 は RS7・B-2 と B-3 は UI の再考と一緒に(別の段)
8. **版は 1 つ**(4 ツールの版と赤い帯の検査は別々に作っていた頃の名残)。**設定は 1 ファイル**(`pipeline / human / manage / eval` の節。旧い 4 ファイルは最初の起動で読み込む = コピーのみ・元は残す)
9. 今までの決まりは続く: 外部へ動画・音声を送らない・CSP `script-src 'self'`・書き込みの API は合言葉・重い処理は `SLOTS`・削除はユーザー確認後・データ移行はコピーのみ

## 5. ① の設計
### 5-1 入口
- `run(入力, 指定, from=None)`。入力 = URL か動画ファイルのパス。指定 = `spec.py` の束(本数・長さ・感度・重み・エンジン・モデル・言語・VAD・後処理・パックの設定・API キー・配信者)。`from` = やり直す段(無ければ最初から)
- 今の 3 つの経路(まとめて実行 `autorun` の本体の経路・配信後の全自動 `live_archive`・ライブの流れ `live.py`)を**この 1 本**にする。URL が配信中なら ingest が録画しながら analyze を 1 秒ごとに回す(今の `live_detect`・`live_excite_worker`)
- 人を待たない。止めて待つ印は作らない

### 5-2 段と成果物と鍵
| 段 | 成果物 1 つの単位 | 鍵に入れるもの | 鍵が変わる操作 |
| --- | --- | --- | --- |
| ingest | 元の動画(か録画) | URL か動画の ID・取得の設定 | — |
| analyze | 候補の一覧(区間と点数)。**自動採用**の結果 | 元の動画の鍵・解析の設定(重み・感度)・学習データの版(長さの目安) | 設定を変える |
| export | 切り抜き 1 本 | 元の動画の ID・区間(開始と終わり)・書き出しの設定(画質・音量・fps) | 候補の端を動かす・区間を足す |
| transcribe(認識。重い) | 切り抜き 1 本の生の認識と話者 | 切り抜きの鍵・エンジン・モデル・言語・VAD | 切り抜きが変わる・エンジンを変える |
| transcribe(後処理。軽い) | 切り抜き 1 本の後処理ずみ | 生の認識の鍵・後処理の設定・辞書と名簿の版 | 辞書が育つ(毎回当て直してよい) |
| pack | 案件 1 つ | 入っている切り抜きの鍵の一覧・有効な字幕の版・カットの上書き・パックの設定 | 字幕やカットを直す(数秒で作り直し) |
- 鍵は成果物の横の小さな JSON(今の `.clip.json` の仲間)に書く。④ の案件はそれを読んで状態(認識ずみ・パックは古い)を出す
- 認識と後処理を分けるのはこのため(今は 1 つの段なので辞書が育つと再認識が要る)
- 第 1 版の使い回しは「切り抜き 1 本まるごと」。「伸びた 2 秒だけ認識して継ぐ」は今の範囲の再認識を使って後から

### 5-3 人の上書き(③)と ① の関係
```
自動:  入力 → 解析 → 書き出し → 文字起こし → パック(ここまで人を待たない)
                ↑                    ↑
人:         候補を直す          字幕を直す・カットを決める
                └── その段からやり直し(run(..., from=段)) ──┘
```
| 段 | ① の出力 | ③ の上書き | 今のデータで言うと |
| --- | --- | --- | --- |
| 解析 | 候補の区間と点数・自動採用 | 手動マーク・採用と不採用・端の調整 | スタジオの自動マーク / 手動マーク・採用 |
| 文字起こし | 認識の生の結果・話者 | 校正した文書・話者の名前の訂正 | `asr.json` / `transcripts/<id>.json` |
| カット | 自動のたたき台 | 残す区間 | `edit.json` |
- 人の操作の 3 つの時機: **前に指定する**(指定の束に「この区間は必ず」「この人は除く」。友人の依頼の区間指定もこれ)/ **動いている最中**(配信中に打つマークも上書き。解析は 1 秒ごとに読むので止めずに反映)/ **終わってから直す**(いちばん多い。直したらその段からやり直し。前のパックは残す)
- 校正の上書きは**切り抜きの鍵**に付ける(認識の実行には付けない)。エンジンを変えて生の認識が変わっても上書きは残り、「古い認識を元にした直し」の印が付く(今は再認識で直しが消える = 改善点)
- この形にする理由: 人がいなくても結果が出る(夜のアーカイブ・友人の依頼・配信中・配った友人の環境)/ 仕組みが 1 つで済む(止めて待つ形は「待っている」状態・再開・期限が要る。今の入口の失敗の状態が増えたのはこのため)/ 自動の出力と人の直しが混ざらない(再認識で直しが消えない・⑤ が生の結果と直しを比べられる・元に戻すのは上書きを消すだけ)/ やり直しが安い(重いのは認識だけ。字幕を直したあとはパックの段だけ)
- 代償: ④ の案件が「自動の結果と人の上書きのどちらが有効か」を持つ / 切り抜き単位の使い回しを ① に作る(今の「済みの段を飛ばす」と紐づけに近い物がある)

### 5-4 ① に渡す物の詳細(指定の束 spec。2026-10-09 夜にユーザーと詰めた = `plan/decisions.md` 1-5)
- **入力**: URL か動画ファイル(1 回に 1 つ)。URL が配信中なら録画しながら
- **固定(束に入れない。今ある設定は消す)**: 常にパックまで(`upto` 無し)/ 1 本が失敗しても続ける(`on_fail` 固定。失敗は結果に理由つきで残す)/ 30fps / 切り出しは精密 / 画質は最大(書き出しの上限 `maxHeight` と録画の `live.quality` の両方)/ `after`(check・auto)無し / **API キーは束の外**(環境変数か鍵のファイル。配った先で JSON に鍵を書かせない)
- **束の決まり**: 既定値と検査は `pipeline/spec.py` の 1 か所。呼ぶ側(画面・友人の受付・CLI)は変えたい所だけ渡す。**① は設定ファイルを読まない**(app が設定の画面の値から束を組み立てる)。配った ① は JSON 1 つで動く

| 節 | 項目 | 鍵に入る |
| --- | --- | --- |
| `hints` 人の指定 | 必ず切り抜く区間 `ranges` / 出る人 `people`(`[{name, color?}]` の並び。**先頭 = 話者の分からない行の字幕の色にする人**。`color` は友人の依頼などで前に指定した字幕の色(無ければ名簿のメンバーカラー → 既定色)。人数だけなら `{count}`。「配信者」の欄は無くす = 配信者は出る人の先頭。配信者ごとの学習データはチャンネルを鍵に。束に無ければ ① がチャンネル名・題名・覚えた名前(④ の学習データ)から推定し、推定した並びを結果の束に書く) | 候補の鍵・色はパックの鍵 |
| `analyze` 解析 | 材料 3 つのオンオフ・重み 3 つ・感度・本数 `count`・長さ `length`・`preRatio`・`headSec`・チャットの遅れ(自動/固定/待ち) | すべて |
| `analyze.adopt` 自動採用 | 上限の本数・前後の余白 `pad`・ライブの `perHour`・`waitMin`。**URL の入力(ライブ・アーカイブ)はオン**。動画ファイル(友人が自分で録画した物が大半)は `ranges` があればそれだけ書き出し、無ければ候補を出して止める(採用は人) | すべて |
| `export` 書き出し | 音量のそろえ方 `loudness`・そろえないときの `volume` | すべて |
| `transcribe` 認識(重い) | `engine`・`model`・`language`・`quality`・`device`・`vadMode`・`boost`・話者判別 `diarize`(人数のヒント) | 認識の鍵 |
| `transcribe.post` 後処理(軽い) | `wordSplit`・字幕の分け方(向き・文字数・分ける文字数)・`stripPunct`・自動の後処理 10 個(`autoDict`・`autoGloss`・`autoContext`・`autoLearned`・`autoRedo`・`redoLarge`・`autoFill`・`stripNames`・`autoLlm`・`diarSmooth`)・**学習データの場所と版**(用語集・置換辞書・名簿・覚えた声のフォルダ。中身は入れない。名簿は ① に同梱の物を既定にし、フォルダにあればそちら) | 後処理の鍵(版が入るので辞書が育てば当て直し) |
| `pack` パック | `fps`(30 固定だが大きさと一緒に持つ)・`size`・`loudness`・`volume`・`backup`・`render`・`speakerColors`・1 段の文字数・行の端(`rowEdge`)・カットの方法と無音の 3 つ・映像トラック数 | すべて |
| `run` 流れ | `from`(どの段からやり直すか)・`force`(同じ鍵でも作り直す) | — |

- **束に入れない物**(見方: その値が変わると ① の成果物の中身が変わるか。変わらない物は外): 届け先・依頼 id・組の溜め・届け方・失敗の通知(③ 友人。① の結果の束(実行 id・パックのフォルダ・失敗と理由)を受けて ③ が zip にして置く)/ 画面の都合(自動再生・次へ・反応の遅れ・キー配置・保管。校正の目標は消す)/ 評価用の印(⑤ の都合。呼ぶ側が後処理の節をオフにした束を渡す。文書への印は ③ に残る)/ `after`(check・auto。消す)/ `fresh`(題名とチャンネルは ingest が取る)/ `marks`(このマークだけ = `run.from=export` + `hints.ranges` で表せる)/ 空き容量のしきい値(① は書けなければ失敗として続けるだけ。始めない判断と見張りは ④)
- **字幕の色は束に入れる**(10-09 夜に見直し。最初は「③ の上書き」と分類して外したが、最初の自動の実行では文書がまだ無く上書きが存在しないので、友人の指定の色がパックに乗らない = 5-3 の「前に指定する」そのもの)。`hints.people[].color`。あとから校正の画面で変えた色は ③ の上書きで、パックの段は「束の色 < 上書きの色」の順に読む。そのうち話者識別で話者ごとに色が付く予定 = 先頭の人の色は「分からない行」の既定だけ
- **① が返す物(結果の束)**: 段ごとの成果物のパスと鍵・使った指定の写しと版・候補の一覧(点数つき)・切り抜きごとの動画と生の認識と後処理ずみ・パックのフォルダ・失敗した切り抜きと理由。③ と ④ はこれを読んで、届ける・案件に束ねる・上書きを重ねる
- 数: 7 つの節・約 60 項目(今の設定の画面 約 90 項目から、固定にした物と ① の外の物を除いた数)

### 5-5 ① のデータの流れの精査(2026-10-09 夜。5-1〜5-4 を通しでたどって見つけた食い違いと、足した決まり)
流れ: 入力 + 束 → **run が「有効な束」を作る**(ingest が取った題名・チャンネル・長さ、束に無い出る人の推定、学習データの版(フォルダの中身のハッシュ = ① が実行の始めに計算)、API キーの有無で `useComments` の実効値)→ 各段が「成果物 + 鍵の JSON」を書く → 結果の束(実行 id・有効な束・段ごとの成果物と鍵・失敗と理由)を ① が自分の記録に残す → ③ が上書きを重ね・④ が案件に束ね・学習データを作る → 次の実行で ① が読む。

| 記号 | 見つけた食い違い | 足した決まり |
| --- | --- | --- |
| F-1 | 配信中の録画から書き出した切り抜き(速報版)と、配信後にアーカイブから作り直した切り抜き(本番版)は、動画 ID と区間が同じなら**鍵が同じになり、使い回しで本番版が飛ばされる** | 切り抜きの鍵に**元の媒体の識別**(録画 id / アーカイブ / 動画ファイルの内容ハッシュ)を入れる。両方が存在し、どちらを有効にするかは ④ の案件(アーカイブ優先)が決める |
| F-2 | 速報版の字幕を人が直したあと本番版に入れ替わると、上書きは速報版の鍵に付いているので**本番版に引き継がれない**(今も「再認識で直しが消える」) | ④ の案件が入れ替えのときに**上書きを本番版の鍵へ付け替える**(同じ動画・時刻合わせ済みの区間)。① は関与しない |
| F-3 | 辞書が育って後処理をやり直すと ① の後処理ずみが新しくなるが、人が直した文書と**どう合わせるか**が決まっていなかった | 上書きは**行の単位**(今の `proofed` の印 = 人が触った行)。有効な文書 = ① の後処理ずみの行に、人の行を**時刻の重なりで対応づけて**上書き。人が触っていない行だけ新しくなる。対応づけられない人の行は「古い認識を元にした直し」の印で残す(RS6 の設計の中心) |
| F-4 | 「出る人」の推定を誰がいつやるか | run が ingest の直後に 1 回(チャンネル名 → 名簿、題名 → 名簿、覚えた名前のファイル)。結果の束の「有効な束」に書く。下流の鍵はこの並びを使う |
| F-5 | 動画ファイルで区間が無いとき(候補だけ出して止める)、人が採用したあとの再実行で ① は何を読むか | **採用の集合 = 自動採用(オンなら)∪ `hints.ranges` ∪ 上書きの採用 − 上書きの不採用**。URL でも動画ファイルでも同じ規則。`run.from=export` で上書きを読んで書き出しから進む |
| F-6 | 話者判別は出る人のヒントと覚えた声に依存するが、認識の鍵に入れると出る人を直すたびに認識(重い)がやり直しになる | 話者判別は**認識とは別の成果物**(`diar`)で、鍵 = 認識の鍵 + 出る人 + 声の版。認識は出る人を含まない |
| F-7 | ライブは「1 本の実行が何時間も続き、途中で切り抜きが増える」 | 段は切り抜き単位で進む(解析は配信中ずっと、採用のたびに export → transcribe → pack)。配信が終わって締めたあとの猶予も同じ実行の中。配信後のアーカイブからの作り直しは**別の実行**(同じ束で入力がアーカイブ URL)で、④ が同じ動画として結ぶ |
| F-8 | 学習データを ③ が実行の途中で書き換えたら | ① は実行の始めに版(ハッシュ)を取り、その実行の中では**最初に読んだ内容**を使う(結果の束に版を書く)。次の実行から新しい版 |
| F-9 | ① の記録(h-3)と ④ の案件の記録の重複 | ① は自分の実行の記録(結果の束)だけ。④ は ① の記録を読んで案件の「前回の結果」を出す。同じ内容を ④ が書き直さない |

## 6. 精度の輪
- **(A) ① のコードを直す(AI)**: ⑤ が人の直しを正解として ① の段を評価用の材料で動かし数字を出す → AI が段のコードか既定値を変える → 同じ材料で測り直す(今の線 B の実験ループと同じ)。段が「入力 → 出力」の純粋な部品なので画面も案件も無しに動かせる。実験の変種は指定の束の違いで渡す(① に `if` を増やさない)
- **(B) 学習したデータを ① が読む(人の直しがそのまま効く)**: ③ が人の上書きから作り、④ の学習データの置き場に置き、① は読むだけ、⑤ が効き目を測る(向きが一方向)

| 人の直し | ③ が作る物 | ① のどの段が読むか |
| --- | --- | --- |
| 字幕の言い直し・名前の訂正 | 用語集・置換辞書・名簿の呼び名と誤認識 | 認識のヒント・後処理 |
| 話者の名前を付ける | 覚えた声 | 話者判別 |
| 候補の採用と不採用・端の調整 | 配信者ごとの長さの目安・重み(今の `lengthHint` の発展) | 解析の自動採用 |
| カットで残した区間 | たたき台の規則の材料 | カットのたたき台 |
- (B) が先(コードを触らず、配った友人の環境でも効く)。(A) は (B) で届かない所。(B) で正解が増えるほど (A) の測定が確かになる(今は 22 本で 95% の幅が広い)

## 7. 今のファイルの行き先(移すときの表。行番号つきの根拠は inventory の文書)
> RS3・RS4(10-10)で移したあとの実際の行き先は `dev/layer_map.py`(FILES・DIRS)が正。この表から変えた行は 8 節の「RS3・RS4 の結果」の「計画と違えた所」に並べた。

| 今 | 行き先 | 備考 |
| --- | --- | --- |
| `ytt_core/*`(excite・evaldata を除く) | `ytt/` | `txindex` は `manage/cases/`。`datadir` は `ytt/`(置き場所の規則)だが管理の操作は `manage/keep/` |
| `ytt_core/excite.py` | `pipeline/analyze/` | golden のテストも一緒に |
| `ytt_core/evaldata.py` | `eval/tools/` | src からの使い手 0 |
| `recorder/*` | `pipeline/ingest/` | 別プロセスのまま(ingest が起動する) |
| `cut2resolve/pack.py`・`resolve_textplus.py`・`cut2resolve_core.py`・`cut2resolve.py`(CLI) | `pipeline/pack/` | `serve.py` の API は `app/server.py` の配線へ。`auto_cut.py` は `human/cut/`(使っていなければ消す)。`srt2resolve.py` は旧い単独 CLI = 消す候補(要確認) |
| `studio/analyze.py`・`batch.py` | `pipeline/analyze/`・`pipeline/run.py`(順番待ち) | feedback.jsonl の書き手は `human/review/` |
| `studio/store.py` | 候補のデータ → `pipeline/analyze/`、手動マーク・採用・コラボの転写 → `human/review/` | 分割 |
| `studio/exporter.py` | `pipeline/export/` | |
| `studio/rank.py` | `human/find/` | API キーの保管は `ytt/settings` |
| `studio/common.py`・`serve.py`・`handoff.py`・`txlink.py` | `app/`(配線)・`manage/cases/`(紐づけ) | 疑似の分岐は `eval/fake/` |
| `studio/*.js`・`*.css`・`index.html` | `app/ui/studio/` | 作りは後で再考 |
| `editor/ed_jobs.py` | 認識と後処理の本筋 → `pipeline/transcribe/`、文書のジョブと進み具合 → `human/proof/` | **いちばん重い分割**(2,800 行) |
| `editor/tx_engines.py`・`tx_worker.py`・`ed_fill.py`・`ed_llm.py`・`ed_retime.py`・`roster.py` | `pipeline/transcribe/` | 偽エンジンは `eval/fake/` |
| `editor/ed_speakers.py` | 判別 → `pipeline/transcribe/`、声の登録 → `human/proof/`(学習データ) | 分割 |
| `editor/ed_store.py`・`ed_alt.py`・`ed_ytcap.py` | `human/proof/` | 文書 = 上書きの置き場 |
| `editor/ed_learn.py` | 辞書と学習 → `human/proof/`、精度の測定と基準 → `eval/drill/`、修正データの書き出しとデータの保管 → `eval/tools/`(使っていなければ消す) | 分割 |
| `editor/ed_relink.py` | 紐づけ → `manage/cases/`、評価用フォルダ → `eval/drill/` | 分割 |
| `editor/ed_misc.py` | A/B → `eval/drill/`、clip-marker 連携・進行度・受け渡し → `manage/cases/`・`app/` | 分割 |
| `editor/ed_drill.py`・`ed_evalbatch.py`・`ed_evalaudio.py` | `eval/drill/`(evalaudio は消す = 読む側が無い) | |
| `editor/resolve_export.py`・`pipeline_io.py` | `pipeline/pack/`・`manage/cases/` | |
| `editor/ed_media.py`・`ed_thumb.py`・`thumb_ideas.py` | `app/`(配信)・`human/cut/`(サムネ案。P5) | |
| `editor/ed_state.py`・`serve.py` | 設定 → `ytt/settings`、名前の受付 → `app/`、`backend_name` → `eval/fake/` の登録 | |
| `editor/*.js`・`index.html` | `app/ui/editor/` | 作りは後で再考 |
| `home/launch.py`・`mount.py`・`appwindow.py`・`prefs.py`・`settings/`・`restart.py` | `app/`(`restart` は `manage/ops/`) | 薄くする |
| `home/autorun.py` | ① の経路 → `pipeline/run.py`、友人の依頼の経路 → `human/friend/`、「あとから解析(測るため)」 → 消す(⑤ の道具で代える) | 分割 |
| `home/live.py`・`live_detect.py`・`live_excite_worker.py`・`live_align_worker.py`・`live_export.py`・`live_tx.py`・`live_tx_worker.py`・`live_archive.py` | `pipeline/`(ingest・analyze・export・transcribe・run) | ライブの流れを run に |
| `home/intake.py`・`deliver.py`・`live_requests.py`・`friend_feedback.py` | `human/friend/` | 「確認してから届ける」の経路は消す |
| `home/cases.py` | `manage/cases/` | |
| `home/backup.py`・`cleanup.py`・`live_cleanup.py` | `manage/keep/` | |
| `home/health.py`・`live_failures.py`・`clientlog.py`・`live_report.py` | `manage/ops/`(`live_report` は `eval/tools/`) | |
| `home/accuracy.py` | `eval/drill/` | |
| `home/portal.*` | `app/ui/home/` | |
| `analytics/*` | `manage/ops/analytics/` | 別件。中身は変えない |
| `ui-kit/*` | `app/ui/kit/` | 写しは `app/ui/` の中で 1 つにできる(sync が不要になる) |
| `dev/eval_*.py`・`_evalcommon.py`・`demo_env.py` | `eval/tools/` | `lint`・`ui_audit`・`push_helper`・`sync_ui_kit`・`plan_artifact`・`dropbox_auth` は `dev/` に残す |

## 8. 移し方(書き直しではなく、移動と分割。各段のあとで全テスト + 入口を起動し直して本物の 1 本)
「移す → 旧い名前を転送(import の別名)で残す → テストが通ったら転送を消す」の繰り返し。コード 10 万行・テスト 6.5 万行は書き直さない。

| 段 | 中身 | 通すもの | 目安 |
| --- | --- | --- | --- |
| RS0(済み) | 全ファイルの行き先の表(7 節を各ファイル・各関数まで)・パッケージの骨組み(空の `src/{ytt,pipeline,human,manage,eval,app}`)・**向きの検査のテスト**(今ある違反の一覧つき)・版 1 つの準備 | 検査のテストが「違反 n 件(一覧と一致)」で通る | 半日 |
| RS1(済み) | ① の骨組み: `ytt_core` → `ytt`(excite を `pipeline/analyze` へ)・`cut2resolve` → `pipeline/pack`・`recorder` → `pipeline/ingest`・`exporter` → `pipeline/export`。`spec.py` と `run.py`(まとめて実行の ① の経路を移して 1 本に)。鍵の JSON の形 | 全 unittest・`test_resolve_pack_contract`(単独)・`e2e_pipeline`・`e2e_live*` | 1 日 |
| RS2(済み) | ① の文字起こし: `ed_jobs` を認識(`pipeline/transcribe`)と文書(`human/proof`)に分割・認識と後処理の段を分ける・エンジンの登録の口・疑似モードを `eval/fake` から差し込む | 編集の unittest と e2e 全部・`test_worker`(サーバー側で numpy を import しない) | 1〜2 日(**いちばん重い。校正の画面が一時的に壊れやすい = 別のセッションで慎重に**) |
| RS3(済み) | ② と ③: home の友人・案件・片付け・調子・ライブを行き先へ、スタジオの検索と手動マーク・採用を `human/review`・`human/find` へ、編集の校正の補助と学習を `human/proof` へ。上書きの置き場を決める | home の unittest と e2e 全部・スタジオの unittest と e2e | 1 日 |
| RS4(済み) | ④: ドリル・評価用フォルダ・A/B・精度の自動測定を `eval/drill`・`dev/eval_*` を `eval/tools`。① の記録と ② の記録を分ける | `eval/` のテスト・`dev/tests/test_eval_*` | 半日 |
| RS5 | `app/` を薄く(配線だけ)・旧い URL の転送・版 1 つ・設定 1 ファイル(旧ファイルを読み込む)・向きの違反 0・転送の別名を消す・文書(AGENTS・README・spec)を新しい形に | 全テスト・lint 0・ui_audit Must 0・`start.bat` で起動して本物の 1 本 | 半日〜1 日 |
| RS6 | 層を 5 つに組み替える(② 管理 `flow/` を新設・語彙を ytt へ下ろす・段取りを flow へ・③④ の ① 直読みを ② 経由に。a)+ 新機能(鍵・校正の上書き・採用の統一・① 単体の CLI など。b)。決定 3-29 | 新しいテスト・`test_layering` 違反 0 + 本物のアーカイブ 1 本と動画ファイル 1 本 | 壁時計 2 日 |
| RS7-1(済み 10-11) | 束と口: この PC の設定 `flow/machine.py`・封筒 `flow/envelope.py`・待ち行列と糸 `flow/runqueue.py`・`POST /api/flow/submit`・束を広げる・画面の欄 3 つを固定に。段の表は下の「RS7-1 の結果」 | 新しいテスト・lint 0・層の違反 0 | 壁時計 1 日 |
| RS7-2(済み 10-11) | 玄関とヘッドレス: ライブ係(封筒の kind `live`・`flow/livesession.py`)・親の口 `livehost`・スタジオなしの採用 `live_adopt`・B-1(`case.json`)・P0・入口の `--headless`。段の表は上の「RS7-2 の結果」。玄関の分割の残り・測る → 速度かコード量は RS8 以降(10 節) | 動きは変えない。全テスト・lint 0 | 1〜2 日 |

**進め方の変更(ユーザー決定 2026-10-10。RS3 の段 D から)**: 時間がかかりすぎているため、(1) 文書(AGENTS.md・editor などの AGENTS・計画・data.js・HANDOVER)は段ごとではなく **RS ごとに 1 回**まとめて直す(WORKLOG は段ごとに短く 1 行でよい)/ (2) 段ごとには **unittest・lint・層の検査だけ**を流し、**e2e の一式は RS の終わりに 1 回**(落ちたら段を絞る)/ (3) コミットは少し大きく = 「移動だけ」と「付け替え」を分けるのは履歴を追う必要がある大きいファイルだけ。小さいファイルは移動と付け替えを 1 コミットに。

RS0 の結果(10-09 夜): 向きの違反は **69 件**。内訳 = pipeline→human 15・pipeline→manage 15・pipeline→app 11・human→app 7・human→manage 7・eval→app 5・manage→app 5・pipeline→eval 3・human→eval 1。多くは「設定と状態の束」(編集 `ed_state`・スタジオ `common`・入口 `prefs`。今は app に置いた)への依存と、認識の本筋 `ed_jobs` から文書・紐づけ・評価への呼び出し。RS1 で設定を `ytt/settings` に寄せ、RS2 で `ed_jobs` を分けると大きく減る見込み。

RS1 の結果(10-09 夜〜10-10。セッション「RS1」。手順はユーザー確認・判断は Fable と相談・RS1-2〜7 はサブエージェントが別の作業フォルダで並列に作りまとめ役が取り込んだ): ytt_core → `ytt`(excite → `pipeline/analyze`・evaldata → `eval/tools`・txindex → `manage/cases`。旧い名前は `src/ytt_core/__init__.py` の転送 = 実体と同じモジュールを sys.modules に登録)/ cut2resolve のパックの部品(pack・resolve_textplus・cut2resolve_core・CLI・**srt2resolve と auto_cut も** = pack の土台と計画の中心だった)→ `pipeline/pack` / 録画 → `pipeline/ingest` / exporter → `pipeline/export`。これら 3 つは旧い場所に**転送のモジュールを置かない**(入口の取り込みの名前の検査が止めるため = ユーザー確認)。読む側を `from pipeline.pack import pack` の形に直し、パスで起動する `cut2resolve.py`(.bat 用)と `recorder.py`(起動中の古い入口用)だけ転送のスクリプト。鍵の JSON の形 `ytt/schemas.make_key` など(形と純粋な関数だけ・書くのは RS6)。`pipeline/spec.py`(束の形・既定値・検査。autorun の検査を移した)。`pipeline/run.py`(`Runner` = ① の段の中身・`run(client, input, spec, from_, hooks)`。`AutoRunner` は Runner を継いでキュー・記録・友人・あとから解析と 12 の口の中身を持つ。ツールは HTTP の client のまま = 段を関数で直接呼ぶのは各段を移したあと)。向きの違反 69 → **68**(pack → auto_cut)。層のテストは入れ子のパッケージ・転送の付け替え・裸の名前の禁止・違反の上限 KNOWN_MAX を持つ。途中で見つけた前からの不具合: 入口の届ける仕事が「届けた」を記録する前に done にしていた(直した)・e2e_window と e2e_ui_handoff は RS1 より前から落ちている(画面の変更の取り残し。別の作業に)。

RS2 の手順と決定(10-10。セッション「RS1」の続き。調べもの 4 体 → Fable と相談 → ユーザー確認 = 4 問とも推奨の案): **範囲** = ed_jobs の分割 + `tx_engines`・`roster` を `pipeline/transcribe` へ(ed_speakers の分割・tx_worker・ed_fill・ed_llm・ed_retime は移さず import の付け替えだけ = RS2-9 か RS3)/ **ジョブの表・待機列・ワーカーの繰り返し・取り消し・登録の口**は `ytt/jobs`(RS0-e のとおり。行き先の表 #1 の human/proof ではなく。判別 ed_speakers が表を読むため)。画面向けの形と編集の排他の値は human/proof が登録 / **置き場所のパス**(TX_DIR など)は `pipeline/transcribe/txenv.py` の一時的な口(app = serve が「呼ぶたびに ed_state の値を返す関数」を登録。RS3 で ytt/settings に置き換えて消す) / **疑似**は ed_jobs の中の分岐だけを差し込み口(`pipeline/transcribe/backend.py`)と `eval/fake/fake_asr.py` へ(どちらを使うかは serve の 1 行。ed_alt・ed_misc・ed_speakers・tx_worker の疑似は移すときに同じ口へ)。**転送**: ed_jobs は最後に中身の無い転送(`ytt/modfwd.py`。serve の名前の受付と同じ仕組み = 読む・書く・消すを本物の持ち主へ)。移した名前を ed_jobs・ed_state に別名で残さない(テストの差し替えが別名に当たって本体に効かなくなる)。段 = RS2-0 転送の仕組みと名前の検査 / RS2-1 ytt へ共通の部品とジョブの表 / RS2-2 txenv と疑似の口 / RS2-3 tx_engines・roster / RS2-4 postproc / RS2-5 records / RS2-6 worker_client / RS2-7 recognize / RS2-8 human/proof(doc_jobs・rerun)。相談の区切りは RS2-2・RS2-7・RS2-8 のあと。 **進み(10-10)**: RS2-0〜9 済み(違反 68 → 66 → 59 → 58 → 55 → 50 → **49**。疑似の死んだフック `TRANSCRIBE_FAKE_REDO` は消した。ed_jobs 2,800 → 1,045 行(文書の側だけ)→ **殻 35 行 + `human/proof/doc_jobs.py` 581 行 + `rerun.py` 464 行**)。**RS2-9 は済み**(次の段落)。殻の ed_jobs・ed_speakers の読み手の付け替えは RS5。RS2-8 で決めたこと(詳細は `plan/decisions.md` 3-23): 8a pipeline の層の部品(ed_speakers・ed_fill・ed_llm・ed_retime)が ed_jobs を読まないよう本物の持ち主へ(`stream_context`・`split_terms` → `roster`、`SPK_FLAGS` → `txbase`、配信の情報・モデル名の検査・clip の読み = txenv の鍵 `studio_stream`・`valid_model`・`pio`)/ 8b `ed_jobs.py` → `human/proof/doc_jobs.py`(git mv)+ 新しい転送だけの殻 / 8c `rerun.py` を割る(境目 = 受付 `validate_retranscribe`・`redo_spec`・`redo_targets` は doc_jobs、本体と反映・`record_rerun` は rerun。向きは rerun → doc_jobs だけ)/ 8d doc_jobs が読んでいた ed_relink(manage)・ed_evalbatch(eval)を serve が登録する口 `doc_jobs.set_hooks`(5 本。登録されていなければ RuntimeError・serve が直後に `check_hooks`)に / 8e 取り出し → 認識 → 整えた行を `recognize.transcribe_rows` へ(RS0-i「計算 = ① / 文書への書き込み = ②」の第 1 歩。ed_fill・ed_llm・辞書と学習の置換は入れていない)。RS2-5〜7 で決めたこと: 辞書の版の入力(置換の組・学習の指紋)は serve が登録する口 `records.set_dict_inputs` / 範囲の行の名前外し(ed_fill)は口 `recognize.set_head_stripper` / GPU の調べ(gpu_ready など)は ed_state に残す(テストが ed_state を直に差し替えるため。worker_client は txenv で読む)/ WORKER_SCRIPT・WORKER_LOG は serve が登録時に入れる。

RS2-9 の結果(10-10 早朝。ユーザー「仮で決定してよい・最後にまとめて確認」。11 コミット c3427a6〜de8b05e。仮決めの詳細は `plan/decisions.md` 3-24 = **まだ確認していない**。違反 59 → 58 → 55 → 50 → **49**。担当: 下調べ Sonnet 3 体・手順の見直し Fable・実装 Opus 2 体と Sonnet 1 体):
- **9a 下ごしらえ**: 文書の形の小道具(`TID_RE`・`OTHER_SPK_*`・`other_speaker`・`no_sub_row`・`ROW_DRAFT_KINDS`・`blank_draft_row`)→ `ytt/schemas.py`、`alt_fold`・`ALT_DROP_CHARS`・`env_off` → `txbase`(ed_state・ed_alt は別名)、txenv に鍵 `worker_has`、判別と声の特徴の疑似は口 `Backend.diarize`・`embed`(本体は `eval/fake/fake_asr.py`)。**不具合の直し(動きが変わる)**: 覚えた声の置き場所 `VOICES_DIR` を呼ぶたびに作業データの `voices` に(以前は入口から起動すると存在しない editor のフォルダの voices を見ていた = 10-01 以降は覚えた声で名前が付かなかった。本物の作業データの `voxceleb.json`(09-30)は次の判別から使われる。判別のモデルの置き場所も同じ形)
- **9b ed_speakers の分割**: 判別の計算・ワーカーの本体(`_diarize_local`・`_embed_local`)・`diar.json` の読み書き・声の特徴と照合 → `pipeline/transcribe/diarize.py`、文書の側(反映・判別のジョブ・空の行の下書き・自動の判別・声を覚える・声の登録簿・字幕の見た目)→ `human/proof/speakers.py`。`src/editor/ed_speakers.py` は転送だけの殻(25 行・RS5 で消す)。ed_drill の名前の候補は serve が登録する口 `speakers.set_context_namer` + `check_context_namer`。voices・ovdraft は今は割らない。human の側が `diar.json` に書き足す所(`update_diar_voices`・`_autodiar_record`)は RS0-h と食い違うが RS6 で
- **9c fill・llm・retime**: `ed_fill` → `pipeline/transcribe/fill.py`・`ed_llm` → `llm.py`(どちらも殻なし)、`ed_retime` の計算 → `retime.py`(`src/editor/ed_retime.py` は文書を読む包み `retime_engine`・`retime_doc` だけ = 層 human。RS3 で `human/proof` へ)
- **9d 認識ワーカー**: `src/editor/tx_worker.py` → `pipeline/transcribe/worker.py`(スクリプトのパスで起動のまま・serve を読まない・`txenv` に `DATA_DIR`・`gpu_ready`・`worker_fake` を自分で登録・`handle(m, out, cancels)`。絶対 import は層の決まりの例外)。旧い場所は起動用の runpy の転送(起動中の古い入口用・RS5 で消す)。GPU の調べ(`setup_cuda_paths`・`cuda_count`・`cuda_libs_ok`・`_gpu_ready_local`)は ed_state から `worker_client` へ。疑似 `install_fakes` → `eval/fake/fake_worker.py` の `install()`(serve が `worker_client.FAKES_MODULE` に名前を入れ、`worker_env` が worker-fake のときだけ `YTT_WORKER_FAKES` で渡す)。`WORKER_SCRIPT` の既定は同じフォルダの worker.py(RS2-6 で決めた「serve が登録時に入れる」は消えた)。プロトコルは同じ
- **気づいたが直していない**: `ed_state._probe_gpu` の判定が空白つきの文字で探していて常に偽(ワーカーの出力は空白なし)= 画面の GPU 表示 `/api/tools` の cuda が CUDA の GPU があっても偽。この PC は AMD なので実害なし(直すなら 1 行)

RS3・RS4 の手順の案(10-10 朝。下調べ Sonnet 3 体 → Fable が突き合わせ。報告そのものと表は `docs/design/rs3-rs4-survey-2026-10-10/`(plan_order.md・survey_*.md)。決めてほしいことは `plan/decisions.md` 3-25 = **まだ確認していない**):
- 違反 49 = 編集 18 + ホームとスタジオ 31。全部の段で **49 → 0**(RS5 の「違反 0」は RS4 の終わりで届く)。見積もりは計画の RS3 = 1 日・RS4 = 半日より大きい = **壁時計 2.5〜3 日**(AI の作業 約 45〜50 時間)
- 段: **0A 下ごしらえ(編集)** = txenv を新しい `ytt/workdata.py` の変数に置き換えて消す・動きのある関数を持ち主へ(ytt/tools・worker_client・txbase・ytt/studiodata・roster)・pio を廃止 / **0B 下ごしらえ(ホームとスタジオ)** = 層の表の 3 行(autorun・live を app に・live_failures を pipeline に)と小さな継ぎ目 8 つ・死んだフック 2 つ(49 → 26)/ **1** 設定の口と評価用の判定を ytt/settings へ(26 → 21)/ **2 波 1** = ed_store・pipeline_io と resolve_export・ed_learn の分割(精度は eval/drill・書き出しと保管は eval/tools)・ライブの葉と転送 3 つ・keep と ops・cases と friend・スタジオの common の分解(21 → 16)/ **3 波 2** = alt・ytcap・retime・ed_relink と ed_misc の分割(評価用の整理と A/B は eval/drill)・スタジオの移動・dev/eval_* を eval/tools へ(16 → 4)/ **4 RS4** = ed_drill・ed_evalbatch を eval/drill へ・ed_evalaudio を消す(4 → 0)/ **5 まとめ**
- 下調べどうしの食い違いの答え: ed_learn・ed_relink・ed_misc の分割は RS3 が eval/ まで運ぶ(同じファイルを 2 回割らない)。txenv に鍵を足さず workdata に置き換える
- **0A と 0B は 10-10 朝に仮のまま実施して済み**(ファイルを動かさない・動きを変えない・どの順でも必ず最初に要る)。0B = 層の表の 3 行・継ぎ目(accuracy・backup・intake の `defaults=`・friend_feedback の `discard=`・live_archive の `pack_info=`・`ytt/fsio.append_line`・`pipeline/runlog.py`・`ytt/schemas.now_ms`)・死んだフック 2 つ(違反 49 → 26)/ 0A = txenv を消して `ytt/workdata.py`(置き場所と版の変数)・`ytt/tools`(動画・音声の小道具)・`worker_client`(GPU・worker_fake・valid_model)・`ytt/studiodata.py`(スタジオの data.json の読み口)・`roster.ROSTER`・pio の廃止(find_clip は ytt/schemas)・ed_store の使っていない import を消して 26 → **25**。波 1 以降(ファイルの移動)はユーザーの確認(3-25)のあと

**RS3・RS4 の結果(10-10。ユーザー確認 = `plan/decisions.md` 3-25。下調べ Sonnet 3 体 → Fable が突き合わせ → 実装は Opus・Sonnet のサブエージェントを別の作業フォルダで並列に作りまとめ役が取り込んだ。報告そのものと表は `docs/design/rs3-rs4-survey-2026-10-10/`)**: 向きの違反 49 → 25(下ごしらえ 0A・0B)→ **0**。コミット約 60 本。**進め方の変更(上の「進め方の変更」)に従い、段ごとは unittest・lint・層の検査だけ、e2e の一式は RS の終わりに 1 回、文書は RS ごとに 1 回**。

| 段 | 中身 | 違反 |
| --- | --- | --- |
| 下ごしらえ 0A・0B | 編集の一時の口 `txenv` を消し `ytt/workdata.py`・`ytt/tools`・`ytt/studiodata.py`・`worker_client` に置き換え / ホームの層の表の 3 行と小さな継ぎ目(`append_line`・`runlog`・`now_ms`・`defaults=`) | 49 → 25 |
| 段 D(編集 0.68.0) | 設定の比較 A/B・修正データの書き出し・データの保管・`ed_evalaudio` を消した(移す量が減る。ユーザー「使用していない」→ 消す) | |
| RS3-E5a・E5c | `ed_store` → `human/proof/store.py`(一覧とパックの有無は `manage/cases/doclist.py`)/ `ed_learn` を `pipeline/transcribe/replace.py`(置換辞書)・`human/proof/learn.py`(学習と提案)・`eval/drill/metrics.py`(精度)に割る | 25 → 18 → 15 |
| RS3-1 | 入口のライブの葉 10 ファイルを `pipeline/export`・`analyze`・`ingest`・`transcribe`・`manage/keep` へ。子プロセスの旧い場所に runpy の転送 3 つ | |
| RS3-2 | `backup`・`cleanup`・`live_cleanup` → `manage/keep`、`health`・`clientlog`・`restart` → `manage/ops` | |
| RS3-3 | `cases` → `manage/cases`、`intake`・`deliver`・`live_requests`・`friend_feedback` → `human/friend`。AutoRunner の友人へ届ける段は `human/friend/delivery.py` の mixin | |
| RS3-4 | スタジオの `common.py` を `ytt`(procs・studio_env・mediainfo・apikey・textutil・errors の `Cancelled`)と `pipeline/ingest/sources.py` に分解し転送だけの殻に | → 8 |
| RS3-E5b | `resolve_export` → `pipeline/pack`(受け渡しの JSON と SRT の組み立て `build_*` も)・`pipeline_io` → `manage/cases`(殻なし) | → 7 |
| RS3-E6 | `ed_alt`・`ed_ytcap`・`ed_retime` → `human/proof/alt.py`・`ytcap.py`・`retime.py`(殻 3 つ)。疑似の 2 つ目のエンジンの行は口 `Backend.alt_rows`(本体 `eval/fake/fake_asr.py`) | → 5 |
| RS3-5 | スタジオの部品: `analyze` → `pipeline/analyze/analyze.py`・`batch` → `pipeline/batch.py`・`store` と `feedback` → `human/review/`・`rank` と `seed.json` → `human/find/`・`txlink` → `manage/cases/txlink.py`。`handoff` は割って `.clip.json` の組み立てを `pipeline/export/manifest.py` へ(`handoff.py` は実行中のポートの共有だけで app に残る) | → 4 |
| RS3-E7 | `ed_relink` → `manage/cases/relink.py`(付け替え・まとめて付け替える・30fps)と `eval/drill/folders.py`(評価用のフォルダの整理)/ `ed_misc` → `manage/cases/handoff_io.py`(clip-marker と受け渡し)・`human/proof/batch.py`(フォルダの一括)。殻 2 つ | → 2 |
| RS4-2 | `ed_drill` → `eval/drill/drill.py`・`ed_evalbatch` → `evalbatch.py`(どちらも殻なし)。`ed_state` の読みを持ち主へ・doc_jobs の口を付け替え | → **0** |
| RS4-4 | 精度の自動測定 `accuracy` → `eval/drill/accuracy.py`・測る道具 `dev/eval_*.py` 13 本と `_evalcommon` とテスト 14 本 → `src/eval/tools/`(旧 `dev/eval_*.py` は runpy の転送) | |
| 段 D2(編集 0.69.0) | 進行度・校正の目標 `goalHours`・`/api/progress`・画面の棒を消した(評価ドリルの欄は「精度」タブの `#drillCard` へ。`ed_misc.progress_stats` 廃止) | |
| RS4 の最後(入口 0.55.0) | 測る道具 `eval_marks.py` に `--analyze-missing [--wait] [--limit N]`(未解析の友人の配信の解析を動いているスタジオに頼む)を足したうえで「あとから解析(測るため)」(autorun の deferred・POST_MODE・portal の札・`YTT_DEFER_ANALYZE`)を消した | |

**計画(上の 7 節の表)と違えた所**:
- `live.py`・`autorun.py` は `pipeline/run`・`human/friend` に割らず **app に残した**(友人へ届ける段だけ `human/friend/delivery.py` の mixin)= 本物の配信が動く玄関を割らない。RS6 で分ける(3-25 c)
- `live_failures`・`live_report` は `manage/ops`・`eval/tools` ではなく **`pipeline/`**(失敗の文と配信の記録を書くのは ① の側。読む `eval_marks --live` は ④)
- `demo_env` は `eval/tools` ではなく **`dev/` に残した**(入口を読むため)
- スタジオの `analyze` は `pipeline/analyze/analyze.py`、`batch` は `pipeline/batch.py`、`handoff` は割った(`.clip.json` は `pipeline/export/manifest.py`)。`common` は 7 つに分けて殻を残した
- `accuracy`(精度の自動測定)は `eval/drill/accuracy.py`
- 殻は `ed_*` と `common` に残した(RS5 で消す)。`ed_drill`・`ed_evalbatch`・`resolve_export`・`pipeline_io` は殻なし。旧パスの runpy の転送は `live_*_worker` 3 つ・`tx_worker`・`dev/eval_*.py` 13 本
- 「あとから解析」を消す代わりの道具 = `eval_marks --analyze-missing`。合言葉は画面の HTML の meta から読む(仮で決めたこと = `plan/decisions.md`)
- 消した物が計画より増えた: 設定の比較 A/B・修正データの書き出し・データの保管(`dataset/` の作業データは消さない)・進行度

**次(RS5)**: 転送だけの殻(`ed_jobs`・`ed_speakers`・`ed_store`・`ed_learn`・`ed_alt`・`ed_ytcap`・`ed_retime`・`ed_relink`・`ed_misc`・`studio/common.py`)と旧パスの転送(`tx_worker.py`・`live_*_worker.py` 3 つ・`dev/eval_*.py` 13 本・`ytt_core` の転送)を消し、読み手を持ち主へ付け替える。app を薄く・旧い URL の転送・版 1 つ・設定 1 ファイル。そのとき入口を起動し直して本物の 1 本を確かめる。

RS0〜RS1 は操作が変わらない。RS2 以降も画面の操作は変えない(画面の作りは後で)。合計の目安は AI の作業で 5〜7 日分(並列にできる段は RS3 と RS4)。

RS5 の前半(10-10 午後): 殻 10 本を消した(編集の `ed_*` 9 本と `src/cut2resolve/cut2resolve.py`・スタジオの `common.py`)。読み手は持ち主を直に読む。旧い名前 `ytt_core` の import は `ytt` に置き換えた(転送の本体は残る)。疑似の旗の口を backend に。版は全体で 1 つ(`ytt/version.py` の 0.56.0 は仮)。友人の依頼の ②③ をやめて全部 ① に(L1)・送るアプリは 2.10.0。残り = 入口を起動し直したあとに旧パスの転送を消す。

RS6 の決定(2026-10-10 夕。`plan/decisions.md` 3-29): ユーザーの案で「① はデータを加工する道具に徹し、① を管理する ② を新しく作る」。番号は全部付け替え = ① 道具 `pipeline/`・② 管理 `flow/`・③ 人 `human/`・④ データ `manage/`・⑤ 検証 `eval/`(3〜7 節は付け替えずみ。この 8 節の表と経緯は当時の番号のまま)。向きは ③④ が ① を直に読まず ② を通す・⑤ は ① を直に読んでよい。RS6 は分けず 1 つ(中の順は a 組み替え → b 新機能)。友人は 1 人で RTX 3060 の PC で動かすのがメイン(= ② + ① は ③④⑤ と画面に頼らず動くことを第一の目標にする)。Q2 の動画ファイルは今のまま(丸ごと 1 本)・Q3 は F-5 に統一・Q4 は認識は印、パックは作り直す。詳しくは decisions 3-29 と `docs/design/rs6-survey-2026-10-10/`(plan_order_v2.md・layer5_review.md・option_b.md)。

**RS6 の結果(10-10 夜。決定 `plan/decisions.md` 3-29。下調べと順番は `docs/design/rs6-survey-2026-10-10/`(plan_order_v2.md・option_b.md))**: 層を 5 つにして(① 道具・② 管理 `flow/`・③ 人・④ データ・⑤ 検証)組み替え、鍵・校正の上書き・採用の統一・結果の束・`.flow.lock`・CLI を入れた。向きの違反は **54 → 0**(`KNOWN_MAX` 0)。仕様は `docs/spec/pipeline.md` 2.4〜2.7・`docs/spec/data-location.md`。

| 段 | 中身 | 違反 |
| --- | --- | --- |
| a-0 | 層 `flow` を足し、向きの検査を許される相手の表 `ALLOWED` に(`dev/layer_map.py`) | 54 |
| a-1 | 語彙を `ytt` へ下ろす(`txbase`・`yturl`・`dictfmt`・`ResolveExportError` → errors・`ids_ok` → schemas) | |
| a-2 | 段取り(run・spec・batch・runlog・live_*)を `src/flow/` へ `git mv`。`ytt/jobs` を枠(SLOTS・Cancelled)と `flow/jobs`(ジョブの表)に分ける | |
| a-3 | ① `clipjob` と ② `flow/tx` を足す・文字の語彙を `ytt/txtext` へ。③ の校正の部品を ② と `ytt` 経由に | |
| a-4 | 話者の判別の半分を ② `flow/diar` へ(判別のジョブの段取り・割り当て・声の特徴と照合・覚えた声の置き場所)。`speakers` は ① を読まない | |
| a-5a | `flow/pack`・`flow/ingest` を足し、`resolve_export` の読みを付け替え。`check_live`・`prune_cache` を `ytt` へ | |
| a-5b | 配線を `flow/wire.install` にまとめ、単語の時刻を `ytt/txwords`・再認識の記録の共通項目を `flow/tx.rerun_base` へ | → **0** |
| b-0 | 段が束(`Run.spec`)を読み `GET /api/settings` をやめる・① の本文の純粋な関数(`spec.export_body` など)・道具の継ぎ目 `flow/tools`(HttpTools・LocalTools)・`AutoRunner.build_spec` | 0 |
| b-K1 | 成果物の鍵を書く(`flow/keys`。export・transcribe・post・diar・pack と F-1 の書き直し)。文書を消すとき鍵も消す | 0 |
| b-O1 | 校正の上書きの第 1 版(`<id>.over.json`。人の行を時刻の重なりで作り直した文書へ引き継ぐ・STALE の印・評価用には当てない・`TRANSCRIBE_CARRY_OVERRIDES=off`)。文書を消すとき一緒に消す | 0 |
| b-R1 | 採用の数・余白・待ちの既定を束(`flow/spec.py` の `adopt`)の 1 か所から読む | 0 |
| b-B0 | 置き場所の持ち主 `flow/placement`・結果の束を案件の `作業用\runs\` へ・`.flow.lock`。CLI のテストの `flow.placement` の差し替えをやめた | 0 |
| b-S1 | ② + ① で動く CLI `src/app/cli.py`(入口が動いていれば頼む・無ければ動画ファイルを LocalTools で・lock・ワーカーの後始末) | 0 |
| b-A | 採用を F-5 の規則 1 つに(区間 ∪ 人の採用 ∪ 自動の上位で上限まで)・採用の段を 1 本に | 0 |
| b-K2 | 鍵を読んで段を飛ばす(文字起こしは違えば印・force で作り直す / パックは違えば作り直す) | 0 |

**計画と違えた所(RS6)**:
- `records`(認識の記録)は ② に移さず **① に残した**
- `live_detect` は ① の `analyze` でなく **`flow/` へ**(配信中の検出は段取りを持つため)
- `tool_slot` は **`flow/jobs`**(重い処理の枠は ② の持ち物)
- `LocalTools`(入口なしで ① を直に動かす道具)は**文字起こしとパックだけ**(解析・採用・書き出しは URL の流れで入口が要る = B-3 まで)
- CLI で動画ファイルを**入口に頼む**ときは 文字起こし → `start-docs` の **2 段**(入口に動画ファイルから始める `start-file` の口が無い。RS7 で玄関 `live.py`・`autorun.py` を分けるときに直す)
- **force は鍵によらず作り直す**(鍵が同じでも違っても。鍵が違うだけなら文字起こしは飛ばして印)
- 入口の起動し直しで古い入口がポートを離さないと、新しい入口が `.flow.lock` で起動を止める(仕様。古い入口が終わるのを待つ)
- 案件ごとのフォルダは **B-0 だけ**(B-1 は RS7・B-2・B-3 は画面の作りの再考と一緒)
- 番号は全部付け替え(① 道具・② 管理・③ 人・④ データ・⑤ 検証。3〜7 節は付け替え済み。8 節の上の表と経緯は当時の番号のまま)

**RS7-1 の結果(束と口。10-11。決定 3-30。調べと順番は `docs/design/rs7-survey-2026-10-10/plan_order_v2.md`)**: ② の入口の形をそろえた。依頼 = 封筒 + 束、この PC の設定は `machine.json`、待ち行列と糸は ② の `Queue`、口は `POST /api/flow/submit`・`GET /api/flow/status`。束は受けたときに組む。仕様は `docs/spec/pipeline.md` 2.8。
意図した動きの変化: 待ちの間に設定を変えても中身が変わらない / 書き出しの画質の上限の既定が 1080 → 上限なし / CLI が入口経由でも自分の束を使う / 編集の設定のデバイスの合わない値は 400。

| 段 | 中身 | 違反 |
| --- | --- | --- |
| 1f | バックアップが案件の `作業用\`(json・runs・`.studio-id`)を `cases\<題名>\作業用\` へ写す(戻すのは手で) | 0 |
| 1d | 起動し直しは古い入口の pid の終了を最大 90 秒待つ・次の番号に逃げず読める文で非 0・`LockBusy` も読める文 | 0 |
| S6a | 束に入れない画面の欄 3 つ(切り出し方式・最大画質・パックの fps)を消し、固定(精密・上限なし・30) | 0 |
| S2 | 束を広げる(hints の検査と読み口・後処理 6 項目・`llmModel`・`post.learning.version`・`run.repack`・`run.pinned`) | 0 |
| 1e | 声の別名をなくす(`match_known_voices`・`voice_learn_rows`)・覚えた声に `learnedFrom`・`eval_speakers --exclude-learned` | 0 |
| S1 | `flow/machine.py`(machine.json・`YTT_MACHINE_*`・overlay)・LLM のモデルを要求で受ける・配信中の文字起こしの機器を machine から | 0 |
| S3 | 封筒 `flow/envelope.py`・Run の欄を束へ写して段は束を読む・`Run.public` に packs・newDocs・段の時刻 | 0 |
| S6b | 編集 ⚙ のデバイスを machine.json へ(`GET/PUT /api/settings` の中で振り分け) | 0 |
| F-k | CLI の小物(スタジオの文脈は作業データの根から・ffmpeg/ffprobe は winget も探す・学習した置換と用語集を learningDir から = `Learning`) | 0 |
| S5 | 待ち行列と糸を `flow/runqueue.py` の `Queue` へ(AutoRunner は受付と hook だけ)・`submit(封筒, 束)`・`status()` | 0 |
| S4 | 受付を変換に(束は受けたときに組む)・`SCREEN` を消す・`POST /api/flow/submit`・待ちの記録を版 2 に・CLI は入口に submit 1 回(古い入口は 2 段) | 0 |

**計画と違えた所(RS7-1)**:
- 「上書き」の名前は束の `run.repack`(S3 の overwrite を言い換え)
- 「このマークだけ」は束でなく**封筒の `input`**(`marks`)
- 待ち行列の置き場の名前は `runqueue`
- 声: `voice_learn_rows`(覚える行を選ぶ)と `match_known_voices`(行から照合まで)
- 計画にあった `serverkit` と `start-file` の口は**外した**(CLI の入口経由は submit 1 回で足りる)
- 「設定を 1 ファイルに」の問いは消えた(機械の都合は `machine.json`、何を作るかは束)
- 8 節の 6 つ目の「CLI で動画ファイルを入口に頼むときは 2 段」は submit 1 回に直った(古い入口だけ 2 段)

**RS7-2 の結果(玄関とヘッドレス。10-11。決定 3-31〜3-33。調べと順番は `docs/design/rs7-survey-2026-10-10/plan_order_v3.md`)**: ライブも ② の封筒 + 束で動かせるようにし、画面と ③ なしの入口(ヘッドレス)を足した。仕様は `docs/spec/pipeline.md` 2.8・`docs/spec/data-location.md`。
意図した動きの変化: 友人のライブ配信の依頼と headless の録画では、検出・採用の待ち・音量・配信後の解析の設定が録画を始めたときの値に固定(仮決定 3-31 の b1・b2)。

| 段 | 中身 | 違反 |
| --- | --- | --- |
| P0 | 鍵で飛ばした段でも結果に前のパックを載せる(`Run.kept_packs`・`all_packs()`・public の `keptPacks`。届ける対象 `run.packs` とは別。飛ばした文書も docs に) | 0 |
| B-1 | 案件フォルダに `case.json`(`flow/placement.ensure_case`。無いときだけ作る。案件の一覧は読むだけ) | 0 |
| G2a | 封筒 kind live の input・束の adopt に `sens`・`afterStream`・`Queue.set_live_hook`(kind live は Run を作らず hook へ) | 0 |
| G5a | 入口の `--headless`(ブラウザ・窓・③ なし・ready の 1 行・終了コード 3)・status に `live` と `idle`・`Queue.set_status_hook` | 0 |
| G0 | ライブの親の口 `flow/livehost.py`(Protocol)・`Live.close` の順を縛るテスト(10-11 の片付けで子ごとの口 5 つを `LiveHost` 1 つにまとめた。満たす側が `LiveSession` 1 つだけのため。CLI の古い入口への 2 段の道も同じ日に消した = 下の「2 段」は当時の形) | 0 |
| G1b | スタジオなしの採用 `flow/live_adopt.py`(`StudioMarks` と `LocalMarks`) | 0 |
| G2b | ライブ係 `flow/livesession.py`(Live から app でない部分を抜き出す・`submit`・`live/bundles.json`・束から検出・解析・音量・書き出したあとの設定・受け渡しは `Queue.submit(kind file)`) | 0 |

**計画と違えた所(RS7-2)**:
- G1a(F-5 を ①)・G3(配信後の作り直しの統合)・`serverkit`・`launch.py` → `app/server.py` の mv・自分の配信も束で・headless の配信後の全自動が `LocalMarks` の採用の印を見ること、は **RS8 へ送った**(10-11: G1a = `pipeline/analyze/adopt.py` と ② の口 `flow/adopt.py`・自分の配信も束で = `livesession.begin_own` は済み)(`plan_order_v3.md`)
- headless の `restart-self` は 409(error `headless`)
- status に `live.exporting` も足した(録画・検出・書き出し)
- 自分の配信(スタジオの URL の欄)は**束にしなかった**(今の読み方のまま。時間の上限で切った。RS8 で)→ 10-11 に RS8 で束にした(`livesession.own_bundle`)
- `live/bundles.json` を**新しく作った**(第 2 版の「新しい保存を作らない」を覆した。録画の途中で設定が変わっても、始めたときの値で最後まで動かすため)

**次**: 入口を「すべて終了」→ start.bat で起動し直して本物の 1 本(RS1〜RS6 の分)・CLI の 1 本(`py -3.10 src/app/cli.py <動画> --out result.json`)。そのあと RS7(整理と最適化。10 節)。

## 9. 実装が終わったら消す物・要確認
> 済み(10-10): 「あとから解析(測るため)」(入口 0.55.0)・`ed_evalaudio.py`(`eval-audio/` の実データは残す)・死んだフック 2 つ(`STUDIO_FAKE_CHAT_DELAY`・`YTT_RECORDER_SOURCE`)・設定の比較 A/B・修正データの書き出し・データの保管(段 D。`dataset/` の実データは残す)・進行度(段 D2)。残りは RS5 以降。
- 消す(決定済み): 友人の依頼の「確認してから届ける」の経路(止めて待つ形)・4 ツール別の版と赤い帯の検査・設定の 4 ファイル(読み込んだあと)・「あとから解析(測るため)」・`ed_evalaudio.py` と `eval-audio/`・疑似モードの `if`(登録の口に置き換え)・`runs[].replaced`・`trim_ends`・死んだフック(`TRANSCRIBE_FAKE_REDO`・`STUDIO_FAKE_CHAT_DELAY`・`YTT_RECORDER_SOURCE`)・`ui-kit` の写しと `sync_ui_kit`(`app/ui/` に 1 つ)
- 要確認(小さい。移すときに聞く): `srt2resolve.py`(旧い単独 CLI)・`auto_cut.py` の CLI・設定の比較 A/B・修正データの書き出し・データの保管(`dataset/`)・エンジンの選択肢「Qwen3-ASR(CPU)」・スタジオの `export-log.txt`・友人の区間の長さと配信中の長さの目安を dev の測定結果から決めている作り(学習データとして ③ に置く形に直す)

## 10. リスクと注意
- **RS2 の `ed_jobs` の分割**: 認識・文書の保存・ジョブの進み具合・評価用の例外が 1 ファイルに絡む。転送の別名で画面を動かしたまま少しずつ移す。`serve.py` の名前の受付(`_ServeModule`)は取り込み(と RS2-9d まで `tx_worker`)が使うので最後まで残す
- **テストの名前**: 多くのテストが `S.xxx` のようにモジュールの名前で関数を取る。転送の別名を残す間は通る。消すのは RS5 で一括
- **一時フォルダに写すテスト**: 写すファイルの一覧(各 e2e の先頭)が新しいパスになる。RS1 で `layout.py` の表を先に直し、写す側はそれを読む形にする
- **作業データ**: 場所は変えないので移行は無し。設定 1 ファイルだけコピーで読み込む(元は残す)
- **並行のセッション**: RS2 と RS3 は触るファイルが重ならないように段で分ける。同じ段を 2 つのセッションで触らない
- 入口が起動中の間はコードを変えても古いまま動く。各段の終わりに「すべて終了 → start.bat」

## 11. 関連
- 棚卸し(行番号つき): `docs/design/code-separation-inventory-2026-10-09.md`
- 前の案(置き換え): `plan/code-separation.md`
- 今の決まり: `AGENTS.md`(取り込みの決まり・担当表)・`docs/spec/pipeline.md`(受け渡しの形式)・`docs/spec/settings.md`(設定)・`docs/spec/data-location.md`(置き場所)
- 10-09 に途中まで動かして止めた「中だけ分ける」案の変更は `git stash`(「WIP: コードの役割分担 S1〜S3 の途中」)に退避してある。この計画では使わない(消してよい)

## 10. RS7 整理と最適化(10-10 追加)
- **RS7 は 2 つに割った**(10-11): RS7-1 = 束と口(済み。8 節の「RS7-1 の結果」)・RS7-2 = 玄関とヘッドレス・ライブ係・B-1(済み 10-11。8 節の「RS7-2 の結果」)。測る → 速度かコード量(以下の手順)は RS8 以降
- 決定(ユーザー): RS7 を入れる。目的は**速度を優先**し、測って効果が小さければコード量(重複の統合)に切り替える。RS5 のあと(RS6 の鍵が入ってから測るのが本筋。RS6 の前に鍵の効果の見積もりだけ先にしてもよい)
- 手順: ① 測る = 段ごとの時間と、鍵で飛ばせる割合(同じ切り抜きの再実行・字幕の直し → パックだけ・辞書更新 → 後処理だけ・評価の流し直し)を、配信ごとの記録 live/reports と評価の道具から数える ② 判断 = 飛ばせる時間が大きければ速度の直し・小さければコード量(`dev/lint.py` に重複の物差しを足して、減る量の大きい順) ③ 動きを変えない直しを 1 つずつ入れ、測って効かなければ戻す
- 避けること: 移動(RS1〜5)と同じ段で直さない(落ちた原因が分からなくなるため)
