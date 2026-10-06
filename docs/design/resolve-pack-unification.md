# Resolve パックの一本化(2026-09-26)

> 状態(2026-10-07): **済み**(09-26)。パックを作るのは今も `src/cut2resolve/pack.py` だけで、契約テスト `dev/tests/test_resolve_pack_contract.py` が二重実装への逆戻りを防ぐ(`cut2resolve/` か `resolve_export.py`・`pipeline_io.py` を変えたら**単独で**流す)。下の「残っていたこと」はすべて済み・扱いが決まった。

文字起こしツールの「Resolveパッケージ(zip)」(当時の `transcribe-tool/resolve_export.py`。今は `src/editor/resolve_export.py`)と、cut2resolve の Text+ パック(`src/cut2resolve/pack.py`)の
二重実装を、`pack.py` に一本化した。AGENTS.md の【高】リスク「先に契約テストを書いてから寄せる」に沿って進めた記録。

## 決まったこと
- **パックを作るのは `src/cut2resolve/pack.py` だけ**。`resolve_export.create_package()` は、文書を transcript/v1 に直して
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

## 契約テスト(`dev/tests/test_resolve_pack_contract.py`)
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

## 残っていたこと(2026-10-07 の時点でどれも済み・扱いが決まった)
- cut2resolve の `.runtime`・siblings を ytt_core に切り替える → **09-26 に済み**(`docs/design/integration-plan.md` の「段階3-2で決めたこと」)
- 実機確認(Resolve に取り込めるか): Text+ のパックは 09-25 に友人の PC で確認済み。重なる字幕・60fps の素材・余白つき素材などの Resolve の実機の確認は `plan/user-tasks.md` の U2(この PC に Lua が無く、AI は Lua を実行して確かめられない)
- 一時フォルダの使用量(仕様として残す注意): zip を作る間、動画のコピー(パックの media/)と zip の 2 つ分を一時フォルダに使う(旧は zip の 1 つ分)。長い配信を範囲指定で文字起こしした文書では、配信のファイル全体が入る(旧も同じ)

## Resolve の注意(2026-09-25 の cut2resolve v0.4.0 / Text+ の作業で分かったこと)
- **スクリプト(Lua)にプロジェクトを作らせない・設定を変えさせない**。プロジェクトは画面から手で作る(30fps・縦横の解像度・入力スケーリング「最短辺をマッチ: 他をクロップ」)。API の `CreateProject` で作ったプロジェクトでだけ編集ページのタイムラインの音が割れた(設定の既定値が画面から作ったものと違う。原因の断定はしていない)。スクリプトは開いているプロジェクトにタイムラインを足すだけで、fps・解像度が違えば止まる
- **Resolve 無料版では、スクリプトの `print` がコンソールに出ず、`io.open` での書き出しもできない**。結果の表示はタイムラインのマーカー(緑 = 完了 / 黄 = 一部失敗。メモに件数・字体)と「C2R_エラー_理由」タイムラインで行う。設定の確認はプロジェクトのデータベース(Project.db の SM_Config。zstd + protobuf)を読む。`GetSetting("timelineInputResMismatchBehavior")` は画面の設定と一致しないことがあり、参考表示だけ
- **字幕のフォントは Fusion の `GetFontList()` から Windows 標準の日本語フォントを選ぶ**(名前の決め打ちは Font Not Found)。字幕の位置は「区間ごとの相対コマ × (タイムライン fps / 動画 fps)」で、60fps → 30fps でも一致した(実機確認)
- **実行直後はインスペクタの数値変更が反映されないことがある**(10〜20 秒待つ)。cut2resolve の画面・入口はコード更新後に起動し直さないと古いコードでパックを作る
- 動画は再圧縮せず元の fps のまま渡し、縦・30fps はプロジェクト側で作る方式が実機で成功した(2026-10-04 からは素材そのものを 30fps にそろえる = `src/ytt_core/normalize.py`)
