# Resolve パックの一本化(2026-09-26)

文字起こしツールの「Resolveパッケージ(zip)」(`transcribe-tool/resolve_export.py`)と、cut2resolve の Text+ パック(`cut2resolve/pack.py`)の
二重実装を、`pack.py` に一本化した。AGENTS.md の【高】リスク「先に契約テストを書いてから寄せる」に沿って進めた記録。

## 決まったこと
- **パックを作るのは `cut2resolve/pack.py` だけ**。`resolve_export.create_package()` は、文書を transcript/v1 に直して
  `pack.plan_cut()` + `pack.build_pack(textplus=True)` を呼び、できたフォルダを zip にするだけ
- 文字起こしの行から残す区間を作る規則は `pack.TRANSCRIPT_ROWS`
  (`base="rows"`・余白 0・最短 0・1フレーム以下の隙間はつなぐ)。旧 resolve_export の結果と同じになる値
- 文字起こし画面のボタンは残す(1クリックで zip)。選ぶのは Resolve で手で作るプロジェクトの fps(24/25/30/50/60)と大きさ(縦・横)
- 切り抜きスタジオの前後の余白つき素材(`<動画名>.edit.json` + `<動画名>_edit.mp4`)は `pack.py` が扱う。
  動画を同梱するパック(Text+・元動画のコピー)で、あれば使う(`Request.edit_media`、CLI は `--no-edit-media` で使わない)。
  区間を余白の分だけ後ろへずらし、字幕の位置(タイムライン)は変えない。試算・画面のタイムラインは元の切り抜きのまま
- cut2resolve のフレームの丸めを四捨五入(0.5 は大きい方へ)にした(`srt2resolve.round_half_up`)

ユーザーの判断(2026-09-26): 一本化の形は「機能が壊れないことを前提で任せる」、余白つき素材は cut2resolve でも使えるようにする。
ボタンを残して中身を差し替える形にしたのは、利用者の手順(1クリックで zip)を変えず、Resolve 側のスクリプトを実機確認済みの Lua 1本にできるため。

## 契約テスト(`tools/test_resolve_pack_contract.py`)
- **A. 一本化の前後で動きが変わらない**: 旧 resolve_export の計算をテストの中に凍結(`LEGACY`。928c3b1 のコードから写し、
  範囲指定・時刻順でない・0.01 秒刻みでない文書を含む 932 件で旧コードと一致を確認済み)し、今の経路と、残す区間・字幕・SRT が同じことを確かめる。
  入力の範囲: 行は時刻順・動画の中・0.02 秒刻み(faster-whisper の時刻の刻み。25fps は除く)・選んだ fps = 動画の fps。乱数の文書 約360件を含む
- **B. 同じ入力から同じパック**: 文字起こしの zip の中身と、同じ文字起こしから cut2resolve で作った Text+ パックが、
  日時の入る cut-plan.json 以外すべてのファイルでバイト単位で同じ(余白つき素材ありを含む)
- **KnownFixes**: A の範囲の外で旧 resolve_export にあった不具合(下の表)。旧の値と今の値を両方固定

先に A を緑にしてから寄せた。A が緑になるまでに cut2resolve 側で直したのは丸めだけ(Python の `round()` は偶数への丸めで、
30fps の 0.15 秒 = 4.5 フレームが 4 に、0.25 秒 = 7.5 フレームが 8 になっていた)。

## 旧 resolve_export との違い(どれも旧の不具合。一本化で直った)
| 入力 | 旧 resolve_export | 今(pack.py) |
| --- | --- | --- |
| ちょうど半フレームの時刻(30fps の 1.45 秒など) | float の誤差で1フレーム下に丸まることがあった | 分数で正確に・0.5 は大きい方へ |
| 動画の終わりをまたぐ行 | 字幕を捨てた | 終わりで切って残す |
| 時刻順でない行 | 字幕を文書の順に並べた(SRT の番号が時刻順でない) | 時刻順(開始が同じなら終わりの早い順) |
| 動画の終わり | 文書の duration × fps(実際のフレーム数を1つ超えることがあった) | ffprobe のフレーム数 |
| 選んだ fps ≠ 動画の fps(60fps の動画で 30) | 選んだ fps でフレームを数えた → **カットが半分の時刻にずれた** | 動画の fps で数える。選んだ fps は Text+ を置くプロジェクトの設定 |

## zip の中身の変化(利用者から見て)
| | 旧 | 今 |
| --- | --- | --- |
| Resolve 側のスクリプト | Python(ResolvePython)。**新しいプロジェクトを作って設定する**。実機確認の記録なし | Lua。開いているプロジェクトに追加するだけ(プロジェクトは手で作る。2026-09-24 の決定どおり)。友人の PC で確認済み |
| タイムライン | CUT_TextPlus・SOURCE_WITH_HANDLES | 同じ2本 |
| 余白つき素材 | 使う | 使う |
| 予備 | timeline.fcpxml・subtitles.srt・cut-plan.json | EDL(と手順書)・SRT・cut-plan.json(FCPXML は無し。cut2resolve の Text+ パックは FCPXML を作らない) |
| 手順書 | はじめに.txt | 友人へ.txt(Text+)・EDL の予備の手順書 |
| zip の形 | ファイルが zip の直下 | `<題名>_pack/` のフォルダ1つ |

## 残っていること
- cut2resolve の `.runtime`・siblings を ytt_core に切り替える(`docs/integration-plan.md` の「段階3-2で決めたこと」。今回はしていない)
- 実機確認: 文字起こし画面の「Resolveパッケージ(zip)」→ 展開 → 友人へ.txt の手順で Resolve に取り込めるか(余白つき素材ありで、クリップの端を延ばせるか)
- 一時フォルダの使用量: zip を作る間、動画のコピー(パックの media/)と zip の2つ分を一時フォルダに使う(旧は zip の1つ分)。
  長い配信を範囲指定で文字起こしした文書では、配信のファイル全体が入る(旧も同じ)
