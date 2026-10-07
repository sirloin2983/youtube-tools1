# ROADMAP(AI 向け: 文書の索引と段の進め方)

> 状態(2026-10-07): **これからの順番・各線の進捗・時間の見積もりは `plan/index.html`(データ `plan/data.js`)(ユーザー向け。正本)**。この文書は「どの文書を読めばよいか」の索引と、段の進め方だけを持つ。
> 2026-10-07 にフォルダを整理した: 動くコードは `src/`(home・studio・editor・cut2resolve・recorder・ytt_core・ui-kit)、友人用の Windows アプリは `friend-apps/`(holo-colors・request-sender)、ユーザーが読む計画は `plan/`、AI 向けの記録と仕様は `docs/`。フォルダ名の正は `src/ytt_core/layout.py`。
> 09-30 の改名(app→home・clip-studio→studio・transcribe-tool→editor)の対応表は `docs/design/phase0-restructure.md`。WORKLOG・design の中の旧いパスは当時のまま。

## 1. 全体像
```
切り抜きスタジオ ──書き出し──▶ 編集(1 文字起こし → 2 カット → 3 パック)──▶ DaVinci Resolve(Text+ パック)
      ▲                              │
      └──── セリフの表示(文字起こしを返す)┘        入口(ホーム・案件・まとめて実行)が全部を 1 つのプロセス(:8700)で動かす
線 D: 配信 → 録画(recorder) → マーク → 書き出し → 文字起こし → パック(配信後の全自動 M7 をこれから作る)
別件: 友人の依頼(Dropbox → 入口が自動で流す)・ホロカラー(メンバーカラーの常駐アプリ)
```
済んだ柱: 3 ツールの統合(段階 0〜7)・「編集」ツール(E1〜E6)・画面の全面見直し・線 A の段 0〜7・9・10・Q0〜Q4・線 D の P1〜P4(既定オフ)・行の時刻の案 A(編集 0.57.0)。
これから: `plan/index.html` の 2(各線の進捗)と 3(フェーズ)(データは `plan/data.js`)。ユーザーがやること: `plan/user-tasks.html`。決めたこと: `plan/decisions.md`。

## 2. 文書の索引(どれを読むか)

### いつも従う(規則・今の仕様)
| 文書 | 中身 |
|---|---|
| `AGENTS.md`(= `CLAUDE.md`) | AI 全員の共通の前提・規則・担当表・フォルダと通すテスト・動作環境 |
| `src/editor/AGENTS.md` | 「編集」の AI 向けの仕様(今の動き) |
| `src/recorder/AGENTS.md` | 録画の部品の決まり |
| 各ツールの `README.txt`・リポジトリ直下の `README.txt` | ユーザー向けの使い方と変更の記録 |
| `docs/spec/pipeline.md` | ツール間の受け渡しの形式と API |
| `docs/spec/data-location.md` | 作業データの置き場所(`%LOCALAPPDATA%\youtube-tools\`)・バックアップ・写し戻し |
| `docs/spec/eval-folder.md` | 評価用のフォルダの規則(仮置き・取り込み・名前) |
| `docs/spec/friend-intake.md` | 友人からの依頼の受付の仕様(Dropbox・送るアプリ・配信者と色) |
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
| `plan/index.html` + `plan/data.js` | 全体の計画・各線の進捗・フェーズ・全工程の表(前提・後続・時間)・依存の図・日程・入口の条件・前提の数字 |
| `plan/user-tasks.html`(データは同じ `data.js`) | ユーザーがやること(U1〜U7・実機で確かめること・決めてほしいこと) |
| `plan/decisions.md` | 決めたこと・やらないこと・AI が仮で決めたこと |
| `plan/improvements.md` | 改善点・追加するとよい機能 |
| `plan/line-a-remaining.md`・`plan/line-a-phase8-multi-clip.md` | 線 A の残り(段 8・12・15)と段 8 の細かい計画 |
| `plan/line-b-transcription.md` | 線 B の第 2 版(関門 G0〜G3/FT・D0〜E4・FT)。付録に第 1 版の測定 |
| `plan/line-b-row-timing.md` | 行の時刻: 案 A の作りと数字・0.57.1 の計画(7)・測り直し(10-07 夜)・配り直しの既定オフと残るずれ(8) |
| `plan/line-b-row-split.md` | I-5 字幕(行)の分け方: 人の分け方との見比べ・規則の机上評価・採る案「24 文字まで切らない」(10-07 深夜) |
| `plan/ux-stage7-9.md` | 「気が利く画面へ」段 7〜9 の残りの調査と判定(10-07 夜に完了) |
| `plan/line-b-overlap.md` | 「ゲーム音声など」・重なる字幕・同時発話 |
| `plan/line-b-extra-ideas.md` | 精度改善の追加案(条件待ちの 6〜11・やらないもの) |
| `plan/line-bc-master-plan.md` | 線 B・C の I-1〜I-5 の中身・原則・リスク |
| `plan/line-d-auto-pack.md` | 線 D の最終目標と M1〜M13・決定 |
| `plan/line-d-live-clipping.md` | 線 D の録画の部品(P1〜P5)と配信中の検出 L0〜L5 |
| `plan/line-d-detect.md` | 線 D の前倒し(10-07 夜に L1〜L3・M11・M8〜M10・M12 まで実装済み): 順番・2 本の線・候補の API の約束・実績と残り(L4'・L5) |

### 完了した設計(経緯。「なぜそうなっているか」を調べるときに読む)
| 文書 | 中身 |
|---|---|
| `docs/design/integration-plan.md` | 統合計画(段階 0〜7 完了)。正本は Claude Docs「動画編集ツール 統合計画」 |
| `docs/design/edit-tool-design.md` | 「編集」ツールの設計(データ・API・決めごと) |
| `docs/design/resolve-pack-unification.md` | Resolve パックの一本化と Resolve の注意 |
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
