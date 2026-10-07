# 「気が利く画面へ」(ux-consistency)の段 7〜9 の残り(2026-10-07 調査)

> 状態(2026-10-07): **実装中**(ユーザー指示「確認だけのものも仮で決めて実装」により、やめてよい 5 項目を外して段 7・8 の残りと段 9 を行う)。元の依頼書は `docs/design/briefs/ux-consistency/REQUEST.md`・設計書は同 `DESIGN_BRIEF.md`(付録 C)。段 1〜6 は 09-29〜30 に済み。
> 調査(読むだけ・Sonnet)で 1 項目ずつコードを確かめた。済み 7・一部 6・未着手 約 22。段 9 は記録なし。

## 1. 段 7(未着手・一部のもの。済みは書かない)
| 項目 | 判定 | 今のコード | やること(担当のフォルダ・大きさ) |
| --- | --- | --- | --- |
| 覚える: 無音の値(E-5) | 一部 | `home/autorun.py` が編集の `cutSilence` を読むが、`cut.js` の 3 欄(`#cutNoise`・`#cutSilMin`・`#cutSilPad`)は保存しない | editor: `cut.js` で保存・復元、`ed_learn.py` の `SETTINGS_PATCH_KEYS` に `cutSilence`(S) |
| 覚える: 話者の人数を文書ごとに(初期値は話者の数)(E-6) | 未着手 | `diarNum` は全文書共通(`app-core.js`・`app-jobs.py`) | editor: 文書ごとに持ち、開くとき既定を話者数に(S) |
| 覚える: 前回の文書とタブ(E-7) | 未着手 | 保存なし。`app.js` の `boot` に復元なし | editor: 空の状態に「前回の続き: ○○」ボタン(S) |
| 覚える: スタジオ ③ の再生位置と選んだマーク(S-8) | 未着手 | `review.js` の localStorage は `clipstudio:rvjob`・`ytt:studio.autoTx` だけ | studio: 配信 ID ごとに位置と選択を保存・復元(M) |
| 次の一手: 文字起こし完了 [開く] | 未着手 | `app-jobs.js` の知らせは文だけ | editor: `UIKit.toast` の `action` で [開く](S) |
| 次の一手: 校正が済んだら [カットへ]・最後の行の文(S-17) | 未着手 | `app-rows.js` が未校正が残っていても「すべて確認しました」 | editor: 残りを数えて出し分け、0 なら [カットへ](S) |
| 次の一手: パック完了 [フォルダを開く] とフォーカス(E-11) | 未着手 | `pack-tab.js` の知らせは文だけ | editor: `action` と `#pkOpen` へのフォーカス(S) |
| 次の一手: 書き出し完了 [編集で開く](S-7) | 未着手 | `review.js` の知らせに `action` なし | studio: 行のリンクと同じ URL を `action` に(S) |
| 次の一手: ホームの「次にやること」に書き出し待ち・文字起こし待ち・確認前の候補(S-6) | 未着手 | `portal.js` は proof と pack だけ。サーバーは export・transcribe を返す | home: `buildTodoCoarse` に種類を足す・候補の数は `cases.py`(M) |
| 押せない札をボタンに: 履歴の札(E-13)・案件の「→ 書き出し 2 本」(S-18) | 未着手 | `app-list.js` の「作り直す」「パックを作る」と `portal.js` の `pt-case-next` が span | editor・home: ボタン化(S) |
| 空の状態に次のボタン(E-9 の CSS 1 行・S-13 ホーム/スタジオ ②/コラボ/③・E-14 行 0 の文書/カットの字幕なし) | 未着手 | 文だけ | editor: `index.html` に `.tt-steps b{display:inline}`・`app-rows.js`・`cut.js` / home: `portal.js` / studio: `queue.js`・`collab.js`・`review.js`(各 S) |
| 二度目の文字起こしは「前に作った文書があります」[開く][作り直す](E-3) | 一部 | `/api/doc-for` は `?media=` と open-video だけ。`startFile` は確認なし | editor: `startFile` の前に `doc-for` → `UIKit.dialog.confirm`(S) |
| パックの作り直し: 同じ場所は確認を省く・ボタン「作り直す(上書き)」(E-15) | 未着手 | 409 のたびに確認 | editor: 同じ `dir` なら `force`(S) |
| 動画のコピーは同じ大きさ・更新日時なら飛ばす(E-15) | 未着手 | `cut2resolve_core.copy_video` は毎回全コピー | cut2resolve: 大きさと更新日時が同じなら飛ばす(音量調整つきは対象外)。契約テスト(M) |
| 札に作り直しが要る理由(E-20) | 一部 | `pack-tab.js` の `isStale` は理由を持たない | editor: 理由つきに(S) |
| 用語: 「入口」→「ホーム」・「Resolve パック」→「パック」・「削る/戻す」→「カットする/残す」(S-22・E-25) | 未着手 | ui-kit・editor・home・studio の多数 | 全部: 文言の置き換え(e2e の期待も)(M。機械的) |
| 理由のない無効・隠れる(E-17・S-25) | 未着手 | `app.js`(TOKEN なしで hidden)・`review.js`(`#rvAuto`)・`portal.js`(`c.gone`) | editor・studio・home: disabled + 理由(S) |

## 2. 段 8(付録 C。やめてよい候補を除く)
| 項目 | 判定 | やること |
| --- | --- | --- |
| リンクの開き方(S-15) | 未着手 | studio・home: `target="_blank"` を `data-ui-portal`(窓の決まり)に(S) |
| 同名の行の副題(S-26) | 一部 | home: 紐づかない単体の文書にファイル名・更新日時(S) |
| スタジオ ② の「追加したあと自動で進める」(S-21) | 未着手 | studio: `queue.js` に `UIKit.autorun`(M)。**保留**(要望が出たら) |
| 元に戻すの対応(E-23 の Ctrl+Shift+Z) | 一部 | **保留**(やり直しの履歴の新設 M。GPT-05 で主な混乱は解決済み) |
| エラーの帯(E-26)・エラー文(S-19) | 未着手 | editor: `showErr` に閉じる・次の一手 / home: `autorun.py` の「入口の画面で…」の文(S) |
| フォーカス(E-27・S-24) | 未着手 | editor: `ask()` の主ボタンにフォーカス / home: 実行 → 中止へ・配信者欄の Enter(S) |
| 「書き出し後の自動文字起こし」の設定が localStorage のまま(依頼書 §1。段 4 の積み残し) | 未着手 | studio: `settings.js`・`review.js` → サーバーの設定へ(S) |

## 3. 段 9(見た目の確認)
- 直した画面を 960・1440・1920 × 明・暗で撮り、Must-fix を直す(Should-fix・Could-improve は `plan/improvements.md` へ)。結果は `docs/design/briefs/ux-consistency/DESIGN_REVIEW.md`
- `docs/spec/ui-guidelines.md` に、まとめて実行の部品(`UIKit.autorun`)・知らせのボタン(`action`)・確認の方式(`confirmTwice`)・キーの一覧(設定)を反映

## 4. やめてよい(仮決め。理由)
1. 出力先を覚える(E-4 の一部): ユーザー決定「別の案件へ間違って出さないため覚えない」(09-29)
2. E-8 用語集の候補(「この配信者の用語を入れる」): 文脈のヒントは測定で悪化し不採用
3. E-19 パックの注意の整理: 名前の注意は EDL のときだけになり、主な不満は解消
4. E-23 の 1 文字起こしのやり直し(Ctrl+Shift+Z): やり直しの履歴の新設 M。要望が出るまで保留
5. E-24 の帯への Alt+数字: ? の一覧に載っている。帯は 5〜7 個までの設計
