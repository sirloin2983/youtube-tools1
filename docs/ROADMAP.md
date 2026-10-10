# ROADMAP(AI 向け: 文書の索引と段の進め方)

> 状態(2026-10-10): **これからの順番・各線の進捗・時間の見積もりは `plan/index.html`(データ `plan/data.js`)(ユーザー向け。正本)**。この文書は「どの文書を読めばよいか」の索引と、段の進め方だけを持つ。
> 2026-10-07 にフォルダを整理した: 動くコードは `src/`(home・studio・editor・cut2resolve・recorder・ui-kit と、役割の層 ytt = 基盤(旧 ytt_core)・pipeline・human・manage・eval)、友人用の Windows アプリは `friend-apps/`(holo-colors・request-sender)、自分用の Chrome 拡張は `chrome-ext/`(yt-studio-time。10-08)、ユーザーが読む計画は `plan/`、AI 向けの記録と仕様は `docs/`。フォルダ名の正は `src/ytt/layout.py`。
> 09-30 の改名(app→home・clip-studio→studio・transcribe-tool→editor)の対応表は `docs/design/phase0-restructure.md`。WORKLOG・design の中の旧いパスは当時のまま。
> 2026-10-10: 役割で組み直す計画(`plan/role-restructure.md`)は RS3・RS4(コードの段。入口・スタジオ・編集の部品を層へ移し、測る道具を `src/eval/tools/` へ)まで済み。import の向きの違反は 0。次は RS5(`app/` を薄くする・旧い名前の転送の殻を消す・文書を新しい形に)。移したファイルの行き先は `dev/layer_map.py`。

## 1. 全体像
```
切り抜きスタジオ ──書き出し──▶ 編集(1 文字起こし → 2 カット → 3 パック)──▶ DaVinci Resolve(Text+ パック)
      ▲                              │
      └──── セリフの表示(文字起こしを返す)┘        入口(ホーム・案件・まとめて実行)が全部を 1 つのプロセス(:8700)で動かす
線 D: 配信 → 録画(recorder) → マーク → 書き出し → 文字起こし → パック(配信後の全自動 M7 は 10-07 に完了。配信中の検出 → 自動採用 → パックは 10-08 の本物の配信で動いた)
別件: 友人の依頼(Dropbox → 入口が自動で流す。ライブ配信の依頼もできる)・ホロカラー(メンバーカラーの常駐アプリ)・Chrome 拡張(YouTube Studio の一覧に投稿時刻を足す)
```
済んだ柱: 3 ツールの統合(段階 0〜7)・「編集」ツール(E1〜E6)・画面の全面見直し・線 A の段 0〜7・9・10・Q0〜Q4・線 D の P1〜P4・M1〜M13・L0〜L4'・D-11(配信中の文字起こし)・行の時刻の案 A(編集 0.57.0)・字幕(行)の分け方(0.59.5 で 16 文字をやめ、0.59.6 で分ける文字数 24 が既定)。
線 D の今: 録画の部品(`live.enabled`)は既定オフ。配信中の検出(`live.detect`)と自動採用(`live.autoAdopt`)は 10-08 から既定オン。10-08 18:31 の配信で検出 → 自動採用 3 → パック 3 まで本物で動いた(L4' 済み)。残りは L5(当たり具合の数字)と U4(長時間の配信)。
これから: `plan/index.html` の「今の状態」「各線の進捗」「これからの順番(フェーズ)」(データは `plan/data.js`)。ユーザーがやること: `plan/user-tasks.html`。決めたこと: `plan/decisions.md`。

## 2. 文書の索引(どれを読むか)

### いつも従う(規則・今の仕様)
| 文書 | 中身 |
|---|---|
| `AGENTS.md`(= `CLAUDE.md`) | AI 全員の共通の前提・規則・担当表・フォルダと通すテスト・動作環境 |
| `src/editor/AGENTS.md` | 「編集」の AI 向けの仕様(今の動き) |
| `src/recorder/AGENTS.md` | 録画の部品の決まり |
| `chrome-ext/yt-studio-time/README.txt`・`AGENTS.md` | Chrome 拡張(YouTube Studio のコンテンツ一覧の日付に投稿時刻を足す)。README = 入れ方・更新・外し方、AGENTS = 作りとテスト |
| 各ツールの `README.txt`・リポジトリ直下の `README.txt` | ユーザー向けの使い方と変更の記録 |
| `docs/spec/pipeline.md` | ツール間の受け渡しの形式と API |
| `docs/spec/data-location.md` | 作業データの置き場所(`%LOCALAPPDATA%\youtube-tools\`)・バックアップ・写し戻し |
| `docs/spec/settings.md` | 設定の決まり(どこに保存するか・⚙ に置くか操作の隣に置くかの基準・今の置き場所の棚卸し・1 つにまとめる段 1〜3 = 計画の S1〜S5) |
| `docs/spec/eval-folder.md` | 評価用のフォルダの規則(仮置き・取り込み・名前) |
| `docs/spec/friend-intake.md` | 友人からの依頼の受付の仕様(Dropbox・送るアプリ・配信者と色・ライブ配信の依頼・組で届けて 1 本ずつ選ぶ) |
| `docs/spec/row-timing-policy.md` | 行(字幕の区間)の時刻の原則(10-07 ユーザー決定)と測る 5 つの数字 |
| `docs/spec/subtitle-notation.md` | 字幕の書き方の規則と、採点で同じとみなす違い |
| `docs/spec/sound-tags.md` | 行の音の状態のメモ(BGM・重なり・聞き取れない)の付け方 |
| `docs/spec/ui-guidelines.md`・`docs/spec/usability-heuristics.md` | 画面の共通のルール(用語集など)・Nielsen の 10 の原則 |
| `docs/spec/code-quality.md` | コードの見直しの合格の基準(13 項目。測るのは `dev/lint.py`) |
| `docs/spec/ui-review-criteria.md` | 画面の見直しの合格の基準(A = 機械で測る `dev/ui_audit.py` / B = 人が見る)。結果は `docs/design/briefs/ux-consistency/DESIGN_REVIEW.md` |
| `src/ui-kit/README.md` | 共通の見た目と画面の共通の動き(部品の仕様) |

### 作業の記録と引き継ぎ
| 文書 | 中身 |
|---|---|
| `docs/WORKLOG.md` | 誰が・いつ・何を変えたか(末尾に追記。10-03 より前は日付ごとの要約) |
| `docs/HANDOVER.md` | 次のセッションへの引き継ぎと、貼るだけの再開用の指示文 |
| `docs/ROADMAP.md` | これ(索引・段の進め方) |

### 計画(`plan/`。ユーザーが読む。順番の正は `plan/index.html`(データ `plan/data.js`))
| 文書 | 中身 |
|---|---|
| `plan/index.html` + `plan/data.js` | 全体の計画(今の状態と残り)・各線の進捗・フェーズ・全工程の表(前提・後続・時間)・依存の図・日程・入口の条件・前提の数字。表示の部品は `plan/plan.js`・`plan/plan.css` |
| `plan/user-tasks.html`(データは同じ `data.js`) | ユーザーがやること(U1〜U13。U6 は欠番。U8 = 送るアプリ 2.8.1 を本物の Dropbox で・U9 = Chrome 拡張を本物の Studio で(10-09 済み)・U10 = 仮決めの確認・U13 = 月報の受け取り(10-09 済み)。ほかに実機で確かめること・決めてほしいこと) |
| `plan/decisions.md` | 決めたこと・やらないこと・AI が仮で決めたこと |
| `plan/improvements.md` | 改善点・追加するとよい機能 |
| `plan/analytics-daily-report.md` | 分析と日報(新しいツール `src/analytics/` の設計。2026-10-08 に決定・10-09 に実装(0.1.1)して日報・週報・月報が LINE に届いた。10-09 に既存の「Youtube日次」(ブックマーク → Apps Script → LINE)を引き継いでツールに移し分析を作り直すと決定。日報・週報・月報で YPP の守り・初動・配信者別などを出す。既存の仕組みの監査と作り直しの方針は 12 節。提案の P24 から) |
| `plan/proposals-2026-10.md` | 今後の機能追加・改善の提案(議論用。2026-10-08。投稿の後の閉ループ・守り・価値を足す仕上げ・検出・校正・運用・友人の 29 件 + 前提の事実と聞きたいこと。3-3・3-4 にユーザーの答えと決定) |
| `plan/llm-postfix.md` | P18 LLM の後処理の設計(疑わしい箇所だけ・差分だけ・上限つき・ワーカーの中・既定オフで 22 本を測ってから。2026-10-08「やってみる」。実装はまだ)+ P28 の訂正と残り |
| `plan/thumb-ideas.md` | P5 サムネの案を数パターン出す設計(完成品ではなく参照の 1 枚 + LLM のキャッチ案。2026-10-08。実装はまだ) |
| `plan/role-restructure.md` | **役割で組み直す計画**(2026-10-09 ユーザー決定。今の工程ごとのツール分けをやめ、役割の層 ytt / pipeline(① 道具)/ flow(② 管理。RS6 で追加)/ human(③ 人の操作)/ manage(④ データ)/ eval(⑤ 検証)/ app(入口と画面)に。import の向きをテストで守る・① は run(入力, 指定) の 1 本・人の直しは上書きでその段からやり直し・成果物に鍵を付けて使い回す・精度の輪は (A) コード (B) 学習データ。今のファイルの行き先の表と移し方 RS0〜RS6。**RS4 までのコードの段は済み(2026-10-10)・次は RS5**) |
| `plan/code-separation.md` | (置き換え済み → role-restructure.md)ツール本体と AI のテスト・測定のための物を分ける前の案(2026-10-09。棚卸しの数字 = src の本体 約 67,000 行のうち約 7,400 行が T / M-記録 / M-画面、と「分けられない物」の節は根拠として残す) |
| `plan/python-migration.md` | O1 = P21 Python 3.10 → 3.12 の下調べ(2026-10-08 済み。yt-dlp は winget の exe で影響なし・固定の版を変えずに移れる。移行は静かな日に 1 晩) |
| `plan/line-a-remaining.md`・`plan/line-a-phase8-multi-clip.md` | 線 A の残り(段 8・12・15)と段 8 の細かい計画 |
| `plan/line-a-proofread-effort.md` | A6 校正の手間: 何が時間を食うかの測定(つなぐ・分けるが最大・機械では境目を選べない)と、キーで直す助けの案(2026-10-09) |
| `plan/line-b-transcription.md` | 線 B の第 2 版(関門 G0〜G3/FT・D0〜E4・FT)。付録に第 1 版の測定 |
| `plan/line-b-row-timing.md` | 行の時刻: 案 A の作りと数字・0.57.1 の計画(7)・測り直し(10-07 夜)・配り直しの既定オフと残るずれ(8) |
| `plan/line-b-row-split.md` | I-5 字幕(行)の分け方: 見比べ・正解づくり(ユーザーが 22 本を直した)・規則の評価・決定「16 文字で分けるのをやめる」(編集 0.59.5。10-08 済み)。0.59.6 で分ける文字数の既定は 24(ユーザー「3 段(24 字)以上はやめてほしい」。精度は 40 と同じ) |
| `plan/ux-stage7-9.md` | 「気が利く画面へ」段 7〜9 の残りの調査と判定(10-07 夜に完了) |
| `plan/line-b-overlap.md` | 「ゲーム音声など」・重なる字幕・同時発話 |
| `plan/line-b-extra-ideas.md` | 精度改善の追加案(条件待ちの 6〜11・やらないもの) |
| `plan/line-bc-master-plan.md` | 線 B・C の I-1〜I-5 の中身・原則・リスク |
| `plan/line-d-auto-pack.md` | 線 D の最終目標と M1〜M13(実装済み。M13 は札だけ)・決定 |
| `plan/line-d-live-clipping.md` | 線 D の録画の部品(P1〜P4 実装済み・P5 = 2 台目は未)、配信中の検出 L0〜L5(L0〜L4' 済み・L5 は配信 数本のあと)、配信中の文字起こし D-11(案 b。10-08 夜に実装) |
| `plan/line-d-detect.md` | 線 D の前倒し(10-07 夜に L1〜L3・M11・M8〜M10・M12 まで実装済み・L4' は 10-08 に済み): 順番・2 本の線・候補の API の約束・実績と残り(L5) |

### 完了した設計(経緯。「なぜそうなっているか」を調べるときに読む)
| 文書 | 中身 |
|---|---|
| `docs/design/integration-plan.md` | 統合計画(段階 0〜7 完了)。正本は Claude Docs「動画編集ツール 統合計画」 |
| `docs/design/edit-tool-design.md` | 「編集」ツールの設計(データ・API・決めごと) |
| `docs/design/resolve-pack-unification.md` | Resolve パックの一本化と Resolve の注意 |
| `docs/design/code-review-simplify-2026-10-08.md` | 10-08 のコードの見直し(「もっと簡潔な処理ができないか」。13 グループ・指摘 193 件・横断の傾向 T1〜T12・直す順番 A〜F・不具合の疑い 14 件。**A〜E は 10-09 に実装済み**(F の削除はユーザー確認待ち = plan/decisions.md 3-18)) |
| `docs/design/code-separation-inventory-2026-10-09.md` | ツール本体に混ざっている AI のテスト・測定のための物の棚卸し(2026-10-09。ツールごとの行番号つきの表。T/M/D と分け方の案。計画は plan/code-separation.md) |
| `docs/design/role-restructure-map-2026-10-09.md` | 役割で組み直す計画の RS0: 分割が要る 33 ファイル(約 31,000 行)の関数・クラス・定数ごとの行き先と理由(読むだけの 3 体の報告)+ 横断する要相談 13 件の仮決め RS0-a〜m(2026-10-09 夜。ファイル単位は dev/layer_map.py) |
| `docs/design/rs3-rs4-survey-2026-10-10/` | 役割で組み直す RS3・RS4 の下調べ(読むだけの報告 `survey_rs3_editor.md`・`survey_rs3_home_studio.md`・`survey_rs4.md` と、それを突き合わせた段の並びとユーザーに決めてもらうこと `plan_order.md`。2026-10-10 朝。済んだ設計・調査の記録。実際の段は `plan/role-restructure.md` と WORKLOG) |
| `docs/design/rs7-survey-2026-10-10/` | 役割で組み直す RS7 の下調べ(`speed.md`・`code_volume.md`・`live_split.md`・`server_settings.md`・`small_items.md`)と段の並び(`plan_order.md` → `plan_order_v2.md` → 第 3 版 `plan_order_v3.md`。RS7-2 の段と RS8 へ送った物。2026-10-10〜11。済んだ設計の記録。実際の段は `plan/role-restructure.md` と WORKLOG) |
| `docs/design/holo-colors.md` | ホロカラーの設計・決めたこと・色の調べ方 |
| `docs/design/phase0-restructure.md` | 09-30 のフォルダ整理(旧 → 新の対応表・変えないもの) |
| `docs/design/briefs/ui-overhaul/` | 画面の全面見直しのブリーフ(承認済み)と実装で決めた細部 |
| `docs/design/briefs/ux-consistency/` | 「気が利く画面へ」のブリーフと依頼書・段 9 の見た目の確認の結果 `DESIGN_REVIEW.md`(段 7〜9 は 10-07 夜に完了) |
| `docs/design/briefs/cyber-theme/` | 見た目のテーマの試作(ui-kit v12 に入れた) |
| `docs/design/mockups/` | 「編集」の画面イメージ |

古い経緯(`docs/archive/`)は 2026-10-07 に消した。必要なら git の履歴(679ff01 以前)で読む。

## 3. 段の進め方(どの段でも)
- 始める前: `AGENTS.md` → `plan/index.html`(データ `plan/data.js`) → `docs/WORKLOG.md` の末尾 → `git status`・`git log -5`。その段の計画(`plan/line-*.md`)の行番号は今のコードで確かめ直す
- 1 つの作業ごとに: 直す → `AGENTS.md` の表のテストを流す → WORKLOG → コミット(`[Claude] 要約`)
- 段の終わり: 版を上げる(serve.py・画面・README の 3 か所)・`plan/index.html`(データ `plan/data.js`) の進捗と `plan/user-tasks.html` の実機の項目を直す・ユーザーに中間報告
- 計画に無い判断(設計の変更・依存の追加・既存機能の削除)が出たら、実装の前にユーザーに聞く。止めないと決めた作業では仮で決めて `plan/decisions.md` の「仮で決めたこと」に並べ、最後にまとめて確認する
