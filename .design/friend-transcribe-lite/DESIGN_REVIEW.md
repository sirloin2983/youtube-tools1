# Design Review: 友人用 文字起こし簡易版(editor/lite.html・lite.js)

Reviewed against: DESIGN_BRIEF.md
Philosophy: 見直し後の「編集」と同じ明るい落ち着いた仕事道具・次にやることが常に1つだけ目立つ・選ばせるより固定する
Date: 2026-10-02(Claude Code。/frontend-design → /baseline-ui → /design-review の順で行い、見つけた所はその場で直した)

## Screenshots Captured

| Screenshot | Breakpoint | Description |
| --- | --- | --- |
| `screenshots/review-load-empty-desktop-1280.png` | Desktop (1280×800) | 1 読み込み(最初。ドロップの場所が主役) |
| `screenshots/review-load-empty-tablet-768.png` | Tablet (768×1024) | 同上 |
| `screenshots/review-load-empty-mobile-375.png` | Mobile (375×812) | 同上(手順は2段目・入力欄は1列) |
| `screenshots/review-load-empty-dark-mode-desktop-1280.png` | Desktop・暗い | 同上 |
| `screenshots/review-run-*.png` | 3幅 + 暗い | 2 文字起こし(疑似が速く終わるので校正に進んだ後の写真も含む) |
| `screenshots/review-proof-desktop-1280.png` | Desktop (1280×800) | 3 校正(映像の上の字幕の見本・話者・ルール・行) |
| `screenshots/review-proof-tablet-768.png` | Tablet (768×1024) | 同上(1列) |
| `screenshots/review-proof-mobile-375.png` | Mobile (375×812) | 同上(行は 話者を時刻の横・文字を全幅) |
| `screenshots/review-proof-dark-mode-desktop-1280.png` | Desktop・暗い | 同上 |
| `screenshots/review-export-done-*.png` | 3幅 + 暗い | 4 書き出し(できた・送り方・注意) |

> 写真は `.design/friend-transcribe-lite/screenshots/`(`.gitignore` の対象。撮り直すスクリプトはセッションの一時フォルダ。e2e の `editor/tests/e2e_lite.py` と同じ流れ)。
> 2026-10-03: 写真は Windows の入れ直しで PC から消えた(`.gitignore` の対象なので clone でも戻らない)。バックアップ `D:\backup\Desktop\youtube-test\.design\` にある。撮り直しは見本の画面を出す道具 `dev/demo_env.py` で。

## Summary

一本道の4段・ui-kit のトークンだけ・主のボタンは各段で1つ、というブリーフの骨格は満たしている。いちばん大きかった問題は狭い画面(375px)でヘッダーが横にはみ出していたこと(手順の名前が1文字ずつ折れて、ページが 634px に広がっていた)で、直した。
目立たせる1点は「映像の上の字幕の見本」(Resolve に出る字幕と同じ MS ゴシック・話者の文字の色とふちの色・記号を除いた形)で、校正しながら仕上がりが分かる。

## Must Fix(すべて直した)

1. **375px で横にはみ出す**: ヘッダーの手順の名前が折れてページが広がっていた(`review-load-empty-mobile-375.png` の直す前)。_直し: 900px 以下は今の段の名前だけ・640px 以下は手順を2段目・名前は折らない(`white-space:nowrap`)。_
2. **狭い画面の行で話者の選択がつぶれる**(矢印だけになっていた)。_直し: 640px 以下は 確認の丸・時刻・話者 を1段目、文字と行の操作を全幅に。_
3. **小さな文字のコントラスト**: 11〜12px の「未確認」「なくてもよい」などが `--ink-3`(白地で約 4.0:1)。_直し: `--ink-2` に(WCAG AA 4.5:1 以上)。_
4. **主のボタンが2つになる場面**: 書き出しのあと「もう一度書き出す」と「フォルダを開く」が両方とも主のボタンだった。校正では「書き出しへ」がいつも主だった。_直し: 次の一手だけを主に(校正 = 未確認が残る間は「次の未確認へ」・全部済んだら「書き出しへ」/書き出しのあと = 「フォルダを開く」)。_
5. **取り消せない操作に確認がない**: 文字起こしの「やめる」。_直し: `UIKit.dialog.confirm`(danger。既定のフォーカスは「続ける」)。_

## Should Fix(すべて直した)

1. **ブリーフ「長さの警告は数秒で消える軽い表示」**: 10 分超の注意が消えない帯だった。_直し: 6 秒の知らせ。30 分超は始めるときの確認(続けられる)。_
2. **ブリーフ「書き方ルールは畳んで置く」**: 最初から開いていた。_直し: 最初の1回だけ開き、次からは畳む。_
3. **書き出しの注意は軽い通知で**: 一覧と知らせで二重に出ていた。_直し: 知らせ1つ(「気をつけることが n つ」)+ 一覧。_
4. **ドロップで受け取った写しの番号(`fbfce248_`)が名前・題名に出る**。_直し: 画面は元の名前・サーバーは題名から番号を外す。_
5. **動画を選んだあともドロップの場所が大きいまま**。_直し: 選んだら小さく畳む(次の一手 = 配信者を選んで始める)。_
6. **行が0件のとき何も出ない**(声が無い動画)。_直し: 案内と「行を足す」1つ。_
7. **/baseline-ui の指摘**: `100vh`→`100dvh`・字間の変更を戻す・進み具合は幅でなく `transform` で 200ms・数字は `tabular-nums`・見出し/本文の折り返し・色はトークン(`#585c66`・`#888` をやめる)・z-index は ui-kit の段(ヘッダー 40)。

## Could Improve(残し。試用のあとで)

1. 行の時刻の列(150px)は広い画面では余る。試用で行が長いと感じたら 120px に。
2. 1列(タブレット)のとき、映像と行の一覧が縦に離れる。校正は PC の全画面が主(ブリーフ)なので、今は高さを画面の半分までに抑えただけ。
3. 波形表示はブリーフで「最初は付けない」。試用後に判断(保留の1つ)。
4. 字幕の見本の大きさは CSS の目安(`clamp`)。Resolve の Text+ の大きさ 0.08(仮)を実機で確かめたら、見本も合わせる(`docs/plan/friend-lite-realcheck.md`)。

## What Works Well

- 「映像の上の字幕の見本」: 文字の色・ふちの色を変えるとすぐ見本が変わり、`[笑]` を書いても見本には出ない = ルール(聞こえたとおり)と仕上がり(Resolve の字幕)の違いが目で分かる
- 一本道と「続きから」: 閉じても localStorage の段と文書から戻る。読み込みの段の下に前の作業の一覧
- キーボードだけで校正が完結(Enter で確認して次へ・数字で話者・I/O で今を開始/終了・Z/X/C/V で ±0.1 秒・Ctrl+Z/Y)。再生キーは「編集」と同じ割り当て(ホームの設定の keymap.playback)
- 確認済みは色だけでなく ✓ と「確認済み/未確認」の文字でも分かる。チェックのボタンは `aria-pressed` と名前つき
- 時刻は入力のときに前後の行と重ならないように抑え(すでに重なっていた所は悪くしない)、効かないときは理由を知らせる
