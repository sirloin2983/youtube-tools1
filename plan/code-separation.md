# ツール本体と、AI のテスト・測定のための物を分ける(2026-10-09)

> 状態(2026-10-09 夜): **置き換え済み → `plan/role-restructure.md`**(ユーザー「今の形を完全に変えてもいいから最適な形を考えて」= 役割の層 pipeline / human / manage / eval / app で組み直す)。この文書の棚卸しの数字と「分けられない物」の節は根拠として残す。fake.py・measure.py で中だけ分ける案(S1〜S4)と 5 節の問いは、新しい計画の 2 節・9 節に答えが入っている。
> (元の状態 2026-10-09: 案。ユーザー「ツール側で必要なものと AI のテストに必要なものが混ざってるなら分離はしたい」→ 読むだけのサブエージェント 5 体で `src/` を棚卸しした結果と、分け方の計画。)

## 1. 結論
- **混ざっている**。`src/` の本体(テストを除く約 67,000 行)のうち、AI のテスト・測定のためだけの物が **約 7,400 行(11%)**。ほかに `dev/`(9,700 行 = AI 側の道具)と、テスト 65,500 行がある
- 混ざり方は 3 種類で、分け方が違う
  - **T テストの都合**(約 720 行): 疑似モード(`STUDIO_FAKE`・`TRANSCRIBE_BACKEND=fake` / `worker-fake`)の偽の実装・テストが差し替える口・テスト用の環境変数。本物の経路の中に `if fake:` で差し込んである
  - **M-記録 測定のためだけの記録**(約 2,900 行): 画面は読まず、読むのは `dev/eval_*` だけの記録(入口の `live/reports/`・`live_feedback.jsonl`・「あとから解析(測るため)」・精度の自動測定、スタジオの `feedback.jsonl`・`archive/*.json.gz`・動画の付加情報、編集の `<id>.asr.json`・`recognition.runs` の詳細・校正の手間・たたき台・`<id>.llm.json`・評価用の音声、ytt_core の評価用 zip の形式)
  - **M-画面 画面のある測定の機能**(約 3,400 行 + JS 約 660 行): 評価ドリル・評価用のフォルダの整理とまとめての文字起こし・認識精度のカードと A/B・データの保管・修正データの書き出し・入口の精度の自動測定。ユーザーが画面で使うが、目的は測定だけ
- 読む側が **どこにも無い**物も見つかった(約 600 行): 評価用の音声 `ed_evalaudio.py` 352・再認識の `runs[].replaced` 50・`trim_ends`/`ENGINE_DIR`/重なりの数え方 80・死んだフック(`TRANSCRIBE_FAKE_REDO`・`STUDIO_FAKE_CHAT_DELAY`・`YTT_RECORDER_SOURCE`)・テストだけが呼ぶ別名ほか

## 2. ツールごとの内訳(行数は目安。本体 = tests/ と ui-kit の写しを除く)
| 場所 | 本体 | T | M-記録 | M-画面 | 主なもの |
| --- | ---: | ---: | ---: | ---: | --- |
| src/home | 19,030 | 40 | 1,360(+要確認 170) | (精度の画面 85 は M-記録に含む) | `accuracy.py` 543・`live_report.py` 243・autorun の「あとから解析(測るため)」290・feedback 110。要確認: 友人の区間の長さ `_friend_length`・配信中の長さの目安 `length_hint`(入力が dev の結果) |
| src/studio | 11,365 | 185 | 390 | 0 | rank.py の疑似 YouTube API 109・analyze/serve/exporter の疑似 50・feedback.jsonl 190・archive 52・付加情報 `yt-dlp -J` 126 |
| src/editor(Python) | 16,191 | 350 | 780(+Qwen3 70) | 2,650 | fake 系の分岐 350・`ed_evalaudio` 352・記録(asr.json・runs・effort・draft・llm)約 430・ドリル 426・まとめての文字起こし 881・評価用フォルダ 557・精度のカード 240・保管 315・修正データ 91・A/B 142 |
| src/editor(JS/HTML) | 9,046 | 6 | 31(effort) | 660 | ドリル 306・全行をこの人に 64・評価用フォルダ 138・精度のカード 125 |
| src/ui-kit | 3,617 | 6 | 0 | 0(D 375) | 見本 styleguide 353(ユーザーは開けない。dev の ui_audit と e2e のため) |
| src/ytt_core | 4,144 | 60 | 339 | 0 | `evaldata.py`(評価用 zip の形式。dev だけが使う)・`excite.windowed_scores`(テストだけ) |
| src/cut2resolve | 4,903 | 20 | 0 | 0 | opener の差し込み・start_port=0。要確認: `auto_cut.py` の CLI 48(画面も入口も使わない) |
| src/recorder | 1,259 | 63 | 0 | 0 | 偽の録画元 `direct` と時間を縮める引数 |
| dev | 9,736 | — | — | — | AI 側の道具。例外: `push_helper`・`dropbox_auth`(ユーザーが使う 354 行)と、`accuracy.py` が実行時に子プロセスで呼ぶ `eval_asr/marks/speakers/cut/alt + _evalcommon`(4,694 行 = **本体が dev に依存している唯一の線**) |
| テスト | 65,500 | | | | unittest 44,900・e2e 15,100・node/C# 4,400・偽のプログラム 1,100。`src/<tool>/tests/` に置く理由 = 一時フォルダに写すテストが tests/ を除いて写す |

## 3. 分け方(3 種類で違う)
- **T(テストの都合)→ 疑似の実装を各ツールの `fake.py` 1 つに寄せ、本体は 1 か所の判定だけ**。`tests/` には置けない(一時フォルダに写すテスト・`dev/demo_env.py` が写しを `STUDIO_FAKE=1` で動かす)ので、`src/<tool>/fake.py`(ツールの直下)に置き、`common.fake()` / `ed_state.backend_name()` が真のときだけ import する。環境変数の名前(`STUDIO_FAKE` など。使い手 18〜101 ファイル)は変えない。テストが差し替える口(`exporter._pump`・`live_archive.run_proc`・`unique=`・`popen=`・`start_port=0`)は本番でも使う普通の依存の差し込みなので残す。死んだフックは消す
- **M-記録 → 各ツールに「測定の記録」の部品 `measure.py` を 1 つ置き、本体はそこを呼ぶだけ**(入口 `home/measure.py`・スタジオ `studio/measure.py`・編集 `editor/measure.py`)。設定 `measure.enabled`(既定オン = 今と同じ。オフにすると記録を書かない)。本体の各所に散っている「書く」コード(例: スタジオの `analyze.py:136-262` の feedback・編集の `ed_jobs` の `recognition_run`/`post_record`/`capture_raw`/`write_asr`)が 1 ファイルに集まり、本筋のファイルが軽くなる。**本体が読む記録は本体に残す**(編集 `runs[0]` の engine/model = 別エンジンの候補が読む・`effort.lastAt`・`proofedAt` = ドリルが読む・`evalReviewed` を外す 1 行・スタジオの `auto0`)。`evaldata.py` は `dev/` へ
- **M-画面 → 「測定」を別のツールにして入口が取り込む(`src/eval/`。分析と日報と同じ形)**。編集の画面からは評価ドリル・評価用フォルダ・精度のカード・A/B・保管・修正データを外し、入口の「測定」の画面に移す。編集に残すのは「評価用」の印(`evalSet`・`in_eval_dir` = 学習・辞書・後処理を止める規則。約 60 行を `is_eval()` 1 か所に)だけ。入口の精度の自動測定(`accuracy.py`)もここへ。**ユーザーの操作が変わる**(ドリルを開く場所が編集 → 測定の画面)ので、やるかはユーザー決定
- **dev → そのまま**(すでに分かれている)。直すのは 2 点: `push_helper.py`・`dropbox_auth.py` はユーザーが使うので `setup/` か `src/home/` へ / `accuracy.py` が `dev/` のパスを前提にしているのは、M-画面を `src/eval/` にするときに「測る道具を `src/eval/` に置き、dev からも呼ぶ」形で解消
- **テスト → 置き場所は今のまま**(`src/<tool>/tests/`)。分けるのは「偽の実装」(上の T)だけ。`test_ytt_core.py` 1,920 行は部品ごとに分ける(読みやすさ)

## 4. 順番と目安(AI の作業。実績に合わせた短い見積もり)
| 段 | 中身 | 動きの変化 | 目安 | 減る行数 |
| --- | --- | --- | --- | --- |
| S1 | 読む側の無い物を消す(1 節の約 600 行)+ 死んだフック + `evaldata` → dev + `styleguide` → dev + `windowed_scores` → tests | 無し(`eval-audio/` が増えなくなる・backup の写す指定から外す) | 1〜2 時間 | 本体 −700 |
| S2 | T の寄せ: `src/<tool>/fake.py`(スタジオ・編集・録画)+ 判定を 1 か所に + 環境変数の表を各ツールの 1 か所に | 無し | 2〜3 時間 | 本筋のファイルから −700(行数は fake.py へ移る) |
| S3 | M-記録の寄せ: `measure.py` × 3 + 設定 `measure.enabled` | 無し(既定オン) | 3〜4 時間 | 本筋から −2,200(measure.py へ)。既定オフにするなら記録が止まる |
| S4 | M-画面を `src/eval/` に(ユーザー決定が要る) | **操作が変わる**(ドリル・評価用フォルダ・精度の画面の場所) | 4〜8 時間 | 編集から −3,300(eval へ)。使わない機能を消せばその分が純減 |

S1〜S3 は操作が変わらないので先に進められる。S4 は 5 節の答えで決める。

## 5. 決めてほしいこと
1. **S4(測定の画面を別のツールに)をやるか**。やるなら、その中で**使っていない機能**はあるか: (a) 入口の「精度の自動測定」(夜に dev/eval_* を流して調子に出す) (b) 編集の「設定の比較 A/B」 (c) 「修正データの書き出し」(追加学習用の zip) (d) 「データの保管」(dataset/ に校正の成果と音声を自動で写す) (e) 評価用の音声 `eval-audio/`(読む側が無い = S1 で消す予定)
2. **測定の記録を既定でオンのままにするか**(S3 の `measure.enabled`)。オンなら今と同じ(校正した文書が測定の材料になる)。オフなら本体は軽く動くが、`dev/eval_*` の材料が増えない
3. 要確認の小さい物: 入口の `_friend_length`・`length_hint`(友人の区間・配信中の候補の長さを、dev の測定結果から決めている。本体で直接数える形に直してよいか)/ `auto_cut.py` の CLI(使っているか)/ 入口の設定のエンジン選択肢「Qwen3-ASR(CPU)」(使っているか。消せば `Qwen3Asr` 70 行も)/ スタジオの `export-log.txt`(書き出しごとの映像情報の 1 行。要るか)

## 6. 根拠(棚卸しの報告)
- 読んだのは `src/home`・`src/studio`・`src/editor`(Python と JS)・`src/ui-kit`・`src/cut2resolve`・`src/recorder`・`src/ytt_core`・`dev`・各 tests。**行番号つきの表は `docs/design/code-separation-inventory-2026-10-09.md`**(実装の段で各担当に渡す)
- 環境変数のフック(本体が読む物)の一覧: `YTT_DATA_DIR=inplace`(101 ファイル)・`YTT_RUNTIME_DIR`・`YTT_CORE_DIR`(ytt_core を読む前なので 4 か所の写しは集約できない)・`YTT_CUT2RESOLVE_DIR`・`YTT_HOLO_MEMBERS`・`STUDIO_HOME`・`TRANSCRIBE_DATA_DIR/STUDIO_DATA/MARKER_DATA`・`TRANSCRIBE_BACKEND`(約 30 ファイル)・`TRANSCRIBE_FAKE_*`・`TRANSCRIBE_WORKER_CRASH`・`TRANSCRIBE_YTDLP`・`TRANSCRIBE_NORMALIZE/AUTO_DIARIZE/EVAL_BATCH/EVAL_AUDIO`・`STUDIO_FAKE/_MEDIA/_CHAT/_COMMENTS/_META`・`YTT_APP_BROWSER`・`YTT_DEFER_ANALYZE`
- 分けられない物: `editor/serve.py` の名前の受付(`_ServeModule`。本物のワーカーと入口の取り込みも使う)・`worker-fake`(本物の起動経路を通す)・`YTT_CORE_DIR` の写し・`data-ui-audit-allow` の印(検査の例外は要素に付けるしかない)・`test_review.cjs` が review.js を文字列の境目で切り出す構造(分けるなら review.js のファイル分割 = CSP と IIFE の大工事)
