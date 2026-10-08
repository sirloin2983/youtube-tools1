# コードの見直し(2026-10-08。「もっと簡潔な処理ができないか」)

> 状態(2026-10-08): **資料**。ユーザー指示「40 分でコードの見直し。簡潔な処理ができないかを中心に。コードは変えずに資料として残す」の結果。コードは変えていない。直すときは `docs/spec/code-quality.md` の基準(動きを変えない・テストの件数を減らさない・版を上げて README に「内部の整理。動きは同じ」)に沿って、この文書の「直す順番」から。

## やり方
- 対象: `src/`(home・studio・editor・cut2resolve・recorder・ytt_core・ui-kit)・`dev/`・`chrome-ext/` の .py と .js(テストは除く)。合計 約 78,000 行
- 13 グループに分け、読むだけのサブエージェント 13 体を並列で走らせた(src は Opus、dev の道具は Sonnet。担当のファイルが重ならないように分け、まとめ役が重複と境目を確かめた)。各グループは「実際にコードを読んで行番号を書く・推測なら要確認と書く」が条件
- 見た観点: (a) 同じ処理の繰り返し → 1 つの関数へ(ytt_core・ui-kit・_evalcommon の既存の部品で置き換えられるもの) (b) 長い関数・深い入れ子 → 早期 return・分割・表での分岐 (c) 自前の処理が標準ライブラリで済む (d) 過剰な防御・到達しない分岐・使われない引数 (e) 同じ変換・同じファイルの読み直し・O(n²) (f) 定数の重複・HTML の文字列連結
- `dev/lint.py`(関数 150 行・12 行以上の写し・死んだコード)は今 0 件なので、**lint に当たらないが簡潔にできるもの**を探した
- 行番号は 2026-10-08 の HEAD(856e1f3)のもの

## 1. 結論(まとめ役)
- **壊れている所・危ない所は少なく、設計の芯(表での振り分け・SLOTS・httpsec・txindex・pack.py の一本化・ui-kit)はそろっている**。大きく作り直す必要はない
- 短くできるのは **「3〜10 行の同じ形を、機能を足すたびにその場で書いた」写し**がほとんど。`dev/lint.py` の「同じ 12 行」には届かない長さなので、測る道具に引っかからずに増えている。各グループの目安を足すと **約 3,000 行(全体の約 4%)**。ただし目安の合計で重なりがあり、精度は粗い
- 行数より効くのは **同じファイルの読み直し**(設定ファイルを 1 要求で 11 回・書き出しで `ffmpeg -i` を 1 本に 11 回・編集の文書を最大 3 回)と、**ui-kit の「無いときの予備」が 3 ツールで 140 か所**残っていること
- 写しが増えた根の 1 つは **ytt_core の小道具が「半分」しか無い**こと(G10): 読めなければ既定値の JSON 読み・更新日時と大きさのキャッシュ・優先度つきの creationflags・孫ごと止める・ログの回し、が無いので各ツールが残り半分を自前で書いている(読めなければ既定値の try/except だけで約 45 か所)。lint の基準 4 は関数名で探すので、別名の写し(`ed_state.unlink_quiet`・`_flags`・`low_flags`・`kill_tree`)は当たっていない
- 「直す順番」(3 節)の A〜C だけで、写しの半分以上と読み直しが片づく見込み。F(削除)はユーザーの判断が要る
- 件数: 指摘 193 件(13 グループ × 13〜15 件)+ 他グループとの重複の疑い 約 70 件 + ytt_core への吸い上げの候補 A〜P(G10)・ui-kit で置き換えられる自前の処理 約 30 か所(G11)

## 2. 横断の傾向(複数のグループで同じ形が出たもの)
| # | 傾向 | どこに(グループ-指摘番号) | 置き場所の案 |
| --- | --- | --- | --- |
| T1 | **子プロセスを動かして、取り消し・時間切れで止める**処理が 6 通り以上(normalize._run_ffmpeg・live_export._run・live_archive.run_proc・deliver._run_ffmpeg・accuracy._run・exporter._pump・live_tx._run_worker)。孫ごと止める kill_tree も 4 通り(live・live_excite_worker・studio common.hard_kill・ed_ytcap)。窓を出さない・優先度を下げる creationflags と pythonw → python.exe の置き換えも 5〜6 か所 | G2-1・G3-1・G3-7・G5-1・G6 疑い・G7-12 | `ytt_core/tools.py` に `run(cmd, cancel=, timeout=, log=)`・`kill_tree(pid)`・`no_window_flags(low_priority=)`・`python_exe()` |
| T2 | **JSON の読み書き・一時ファイルの付け替えを手で書いている**(fsio.read_json_file・write_json・atomic_write・unlink_quiet があるのに)。「読めなければ既定値」の形が fsio に無いので try/except が約 45 か所(ytt_core の中の datadir.read_marker・colors._read_json も大きさの上限なしで読む)。2 か所(deliver の組の一覧・cleanup の trash-roots.json)は書きかけを読まれうる。更新日時と大きさで覚えるキャッシュも txindex・colors・editor・home で 9 か所 | G10-2/3・G1-9・G2-6・G3-4・G5-8/10・G6-10・G7-2/8/11・G9-5/7・G12-9・G13-3 | `fsio.read_json_or(path, default)`(dev/_evalcommon.read_json を移す)・`fsio.stamp` + `StampCache` を 1 つ。あとは既存の `ytt_core/fsio.py` を呼ぶだけ(dev/ も) |
| T3 | **fetch の包み**が JS で 13 本(ui-kit 6・studio 3・editor 4・portal 1)。合言葉の付け方・つながらないときの文・エラーの形がそれぞれ違う | G4-1・G8-1・G11-1 | `UIKit.http(url, opt)`(合言葉を付ける 1 か所)+ `UIKit.homeApi`(入口の API) |
| T4 | **ui-kit は必須なのに `window.UIKit &&` の予備の経路**が portal 41・studio 53・editor 49 か所。予備の道に visibilitychange の直接利用(決まりに反する)と window.confirm が残る。ガードの無い呼び出しも既にあるので守りとして効いていない | G4-10・G8-2・G11-3 | 外す。test_document_save.cjs の harness に UIKit の stub を足す |
| T5 | **数の検査**(bool でない整数・有限・範囲)がその場書きで 50 か所超。`schemas.num` があるのに `_num`・`_int_ms`・`plain_int`・`num` が各所にある。exporter._num_sec は巨大な整数で 500 になる穴 | G1-13・G5-9・G7-11・G12-4・G13-4 | `ytt_core/schemas.py` に `num`・`plain_int`・`int_in(lo, hi)` |
| T6 | **HTTP の定型が各 serve.py で写し**: JSON 本文の読み取り(4 か所)・動画の Range 応答(studio と editor で同じ 40 行)・SO_EXCLUSIVEADDRUSE のサーバー(5 か所)・書き込み系の合言葉の検査(入口の中で 3 か所)・do_POST と do_PUT が同じ | G1-1/7・G5-5/6・G7-3・G9-7 疑い | `ytt_core/httpsec.py` に `read_json_body`・`send_file(Range)`・`ExclusiveServer`・`token_ok` |
| T7 | **同じファイルの読み直し**: live の設定を 1 要求で約 11 回(スタジオが 3 秒ごとに呼ぶ API)・書き出しで `ffmpeg -i` を 1 本に約 11 回・編集の文書ごとのキャッシュが 4 つで同じ文書を最大 3 回読む・editor の load_settings を 1 要求で何度も・autorun が同じ動画を 2 回 ffprobe・lint.py が AST を 1 ファイル 5 回 | G2-3・G5-2・G7-2・G6-6・G3-11・G13-2 | 要求の頭で 1 回読んで渡す / (パス・mtime・size) を鍵にしたキャッシュ |
| T8 | **ツールをまたいだ「同じ規則」の写し**: 書き出しの名前の規則(live_export ↔ studio exporter。102 行)・録画の時刻と id(rec_core ↔ live_export ↔ live_excite_worker)・ワーカーが live_export の小道具を写す(一致をテストで守っていない)・ツールの表 5 か所・cut2resolve の既定値 4〜6 か所 | G2-4・G3 疑い・G5 疑い・G9-2 疑い・G1-5 | ytt_core に `names.py`(名前の規則)・録画の受け渡しの小道具。既定値は pack.Request の 1 か所 |
| T9 | **骨組みの写し**(欄ごと・ジョブごと・道具ごとに同じ流れを少しずつ変えて書く): autorun の「待つループ」5 回・編集のジョブの手順(取り消しの確かめ 26 か所・GPU → CPU 3 か所・一時 wav 7 か所)・ed_alt と ed_ytcap の配管・eval_* の入口と出口(7 本)・portal の pollAuto 4 本と 2 つの欄・studio の設定の対応 3 か所・「③ で開く」3 ファイル | G1-3・G6-1/2/3・G7-1・G12-1/3・G13-1・G11-2/4・G4-2/3 | 各ツールの中の小さな関数(`_poll`・`job_temp_wav`・`check_cancel`・`_evalcommon.std_args`・`track()`) |
| T10 | **小さな小道具の多重化**: フォルダの大きさ 4 つ・メモリの測定(ctypes)3 つ・ログの回転 4 つ・「パスがフォルダの中か」6 通り(realpath の有無が違う = セキュリティの決まりが 1 か所でない)・例外 → 文 `(e.strerror or e.__class__.__name__)` 30 か所超・カタカナ → ひらがな 4 つ・esc 3 つ・時刻の書式 5 つ | G1 疑い・G2 疑い・G3-3/6・G6 疑い・G7-15・G8 疑い・G12 疑い | ytt_core / ui-kit に 1 つずつ |
| T11 | **残っている古い経路**: 既定でオフの実験(編集 約 300 行)・auto_cut が pack.py と別にパックを書く・消した画面のための API の指定・evaldata の「書き出し側」(10-04 に簡易版を消したあとも scrub_paths・zip_name・safe_url・raw_links・overlap・RULES が残り、呼ぶのはテストだけ。RULES は `docs/spec/subtitle-notation.md:23` が参照)・ytt_core の使われていない定数と関数・count_sparse_rows.py・handoff のテストのためだけの包み・解析の設定 maxHeight(サーバーで未使用) | G6-4・G9-1/6・G10-1/13・G13-14・G5-14 | **削除はユーザー確認**(既存機能の削除の決まり) |
| T12 | **excite の式の数字**(0.6/0.4・floor・smooth の幅・5/6・±6)が一括と配信中の 2 か所(テストを入れて 3 か所)にあり、区間を静かな所へ合わせる 4 行と冒頭の減点の式も 2 か所ずつ。txindex.use_packs_dir は datadir.prepare と同じ登録の繰り返し | G10-6/7/8 | 定数にまとめる(値と計算の順は変わらないので golden は一致したまま) |

## 3. 直す順番(案。1 つの作業にまとまる単位で)
| 順 | 作業 | 中身(グループ-指摘) | 目安 | 動きが変わるか | 通すテスト |
| --- | --- | --- | --- | --- | --- |
| A | **ytt_core に小道具を足し、各ツールの写しを消す** | T1・T2・T5・T6・T10・T12: tools.run / kill_tree / no_window_flags(low_priority) / python_exe・fsio.read_json_or / stamp / StampCache / is_inside / rotate・schemas.plain_int / int_in・httpsec.read_json_body / send_file / ExclusiveServer / token_ok・dir_size・process_memory_mb・why(e)・excite の定数。**吸い上げ先の一覧は G10 の「吸い上げの候補」A〜P** | 約 500 行(ytt_core の中 約 130 行 + 外 約 400 行) | 原則変わらない。例外: deliver・cleanup の書き込みが原子的になる(安全側)・exporter._num_sec が 400 を返す(500 → 400)・srt2resolve の付け替えのやり直しの規則を fsio にそろえる場合・大きさの上限なしだった JSON 読みに上限が付く | ytt_core・home・studio・editor・cut2resolve・recorder の単体。excite は golden(`src/ytt_core/tests/data/excite_golden.json`)の一致。lint の dup-helper(基準 4)に当たらないよう、写しは消す |
| B | **JS: ui-kit に http / homeApi / copy を置き、予備の経路を外す** | T3・T4: 13 本の fetch を 1 本に・`window.UIKit &&` 140 か所と visibilitychange の予備を外す・esc / 時刻の書式を ui-kit に寄せる | 約 150 行 + 条件 140 か所が短くなる | 変わらない(エラーの形は e.status / e.body にそろえる = portalApi だけ body が無い今の食い違いが直る) | `dev/sync_ui_kit.py` → test_review.cjs(**文字列の境目で切り出すので境目と渡す関数を直す**)・test_document_save.cjs(harness に UIKit の stub)・e2e_portal・e2e_ui・e2e_edit_*・e2e_styleguide・ui_audit Must 0 |
| C | **読み直しを減らす(速さ)** | T7: live の設定を要求の頭で 1 回・exporter.media_info に (パス・mtime・size) のキャッシュか verify_output の結果の使い回し・編集の 4 つのキャッシュを 1 つに(進行度を要約に足す)・ed_learn.load_settings にキャッシュ・autorun の ffprobe を 1 回・lint.py の AST を 1 回 | 約 60 行(行数より速さ) | 変わらない。**時間で覚える形(TTL)にしない**(test_live* は prefs.patch の直後に結果を見る) | test_live*・test_exporter・test_edit(`_summary_cache`・`_drill_cache` の名前はテストが clear するので残す)・lint --json の出力が前後で同じ |
| D | **ツールをまたいだ規則を ytt_core に** | T8: 書き出しの名前の規則・録画の時刻と id・ワーカーの小道具(live_export を読む)・ツールの表の正を 1 つ・cut2resolve の既定値を pack.Request に | 約 200 行 | 変わらない(写しが合っているかを確かめるだけのテストは不要になる) | test_exporter・test_live_detect(EW と LX の一致)・test_recorder・test_launch・test_serve(cut2resolve)・**test_resolve_pack_contract は単独で** |
| E | **各ツールの中の骨組みの共通化** | T9: autorun `_poll`・編集の `job_temp_wav` / `check_cancel` / `add_warning`・GPU → CPU 1 か所・SenseVoice を Qwen3 の子クラスに・ed_alt / ed_ytcap の配管・`_evalcommon` に入口と出口・portal の track() と欄の関数・studio の設定の表と「③ で開く」 | 約 500 行 | ほぼ変わらない。例外: ChunkModel の GPU → CPU は Cancelled まで捕まえているので、そろえると少し変わる(要テスト)・eval の共通化で UNC 回避が全部に広がる(安全側) | test_autorun・test_worker(**GPU → CPU の経路はテストが無いので先に足す**)・test_alt / test_ytcap・dev/tests/test_eval_*・e2e_portal・test_review.cjs・e2e_ui |
| F | **古い経路の削除(ユーザー確認)** | T11: 実験の経路 約 300 行(行の終わりの寄せ・1 秒丸めの配り直し・声の無い行を捨てる)・auto_cut の 2 本目のパック(出力フォルダ名・友人へ.txt・tool.name が変わる)・消した画面のための API の指定・count_sparse_rows.py・handoff の包み・maxHeight の欄 | 約 500 行 | **変わる**(既存機能の削除) | 削除の前に grep(基準 12)。README に「内部の整理」ではなく削除の内容 |

## 4. 簡潔化とは別に見つかった、不具合か食い違いの疑い(要確認。直す前にテストで再現)
| # | 内容 | 場所 |
| --- | --- | --- |
| 1 | 入口の api/ytt/… を Host/Origin で断るとき本文を読み捨てないので、Windows で 403 が届かない形 | G1-1 `src/home/launch.py:1066-1080` |
| 2 | 「すべて終了」で後始末が 2 回走り、Ctrl+C・× の経路では `_autorun.close()` が呼ばれない(M5 の「続きから」に影響の可能性) | G1-2 `src/home/launch.py:1127-1138, 1315-1327` |
| 3 | 友人へ届ける組の一覧と trash-roots.json の書き込みが原子的でない(友人のアプリが書きかけを読むおそれ) | G3-4 `src/home/deliver.py`・`src/home/cleanup.py` |
| 4 | `exporter._num_sec` が巨大な整数で OverflowError → /api/live/section が 500 | G5-9 `src/studio/exporter.py` |
| 5 | `analyze.py:506` の動画 ID の検査に ASCII フラグが無く、common.VID_RE と食い違う | G5-15 |
| 6 | 解析の設定 `maxHeight` はサーバーで読んでいない(画面の「画質の上限」の欄だけある) | G5-14・`src/studio/queue.js:46` |
| 7 | ワーカー(live_excite_worker)が写している live_export の定数・正規表現の一致をテストが守っていない | G2-4 |
| 8 | visibilitychange の直接利用が予備の道に 3 か所(AGENTS.md の決まりに反する。今は通らない道) | `src/studio/review.js:3672`・`src/editor/app.js:98`・`src/home/portal.js:2229` |
| 9 | ui-kit の `lock` アイコンが見本(styleguide.js)とテスト(e2e_styleguide.py)の手書きの一覧に無い | G11-14 `src/ui-kit/ui-kit.js:1589` |
| 10 | cut2resolve の API の試算(api/plan)は SLOTS を通らない(無音の検出は音声を全部読む。編集側の同じ処理は通している) | G9 付記 `src/cut2resolve/serve.py:276-284` |
| 11 | 同時に入れない組み合わせの表 EXCLUSIVE と入口の検査の組がずれている | G6-7 `src/editor/ed_jobs.py` |
| 12 | srt2resolve の付け替えのやり直し規則が fsio と違う(PermissionError なら何でも 6 回 = 読み取り専用でも待つ) | G9 疑い `src/cut2resolve/srt2resolve.py:54-90` |
| 13 | `live_cleanup._replaced_why` の理由が捨てられている | G2-15 |
| 14 | 録画の一覧の行の時刻の型が呼ぶ側で違い、live_archive の「終わった時刻」の求め方が 3 通り(今は合っている) | G3 疑い `src/home/live_archive.py:800, 863, 1085` |

## 5. 直すときの注意(全グループ共通)
- **名前で縛られているもの**はそのまま残す: テストが差し替える `exporter._pump`・`live_archive.run_proc`、clear する `_summary_cache`・`_drill_cache`、`test_review.cjs` が文字列の境目で切り出す review.js の関数名、`test_document_save.cjs` が名前で抜き出す saveDoc・openDoc・readMark
- **数字の意味を変えない**: `dist` の分位点・bootstrap の `rnd.choice`(`choices` に変えると乱数列が変わる)・excite の式(golden と食い違う)
- 意図した写し(`# lint: keep`)は残す: 単独のコマンド(srt2resolve・cut2resolve_core)は ytt_core を読まない・eval_speakers が editor の定数を二重に持つ・`_load_core`(ytt_core を探す関数は ytt_core に置けない)
- 画面とサーバーで同じ規則を二重に持つもの(rowCutFlags ↔ edit_cut_flags・coveredBy ↔ _covered・wbSplit ↔ wb_split・cpApproxSpans ↔ union_spans)は、`tests/subread_cases.json` のように**共通の例で両側を検査する**形にすると食い違いを防げる
- G4 の行番号は、並行セッションの未コミットの差分(settings.js の autoDeliver・core.js 0.23.3)を含んだ状態で書いてある

## 6. 各グループの詳しい指摘(サブエージェントの報告をそのまま。行番号は HEAD 856e1f3)


### G1 home-core(担当: src/home/launch.py・mount.py・autorun.py・cases.py・prefs.py・restart.py・appwindow.py・clientlog.py、合計 約 5,330 行)

#### 全体の傾向
- 8 ファイルは役目ごとに分かれていて、ytt_core(runtime・httpsec・fsio・txindex・datadir)もよく使っている。lint の基準(150 行・12 行の写し)は満たすが、「同じ骨組みを少しずつ変えて何度も書く」所が autorun.py に集まっている(ジョブを待つループ 5 回・あとから解析の条件 2 回・届けるときの後片付け 2 回)。
- launch.py は POST を表(POST_ROUTES)で分けているのに、GET と api/ytt/… は if の連なりのまま。合言葉の検査と終了の後始末は 2〜3 か所に分かれていて、少しずつ食い違い始めている(指摘 1・2)。
- prefs・autorun・cases の入力の検査は「bool でない整数」「ID の形」「制御文字なし」をその場で書く形が約 30 か所ある。小さな共通の述語を 1〜2 個置けば短くなる。
- ツールの表(app 名・フォルダ・prefix)が 5 か所に写してある。互換の識別子を守るには、正を 1 つにしたい。

#### 指摘

##### 1. 書き込み系 API の検査が 3 か所に分かれ、1 か所だけ本文を読み捨てない(優先度: 高・削れる行数の目安: 約 12 行)
- 場所: `src/home/launch.py:682-689`(do_POST)・`src/home/launch.py:1066-1080`(ytt_request)・`src/home/mount.py:147-150`(Mounted.parse_request)
- 今: 「Host/Origin/Sec-Fetch → 合言葉(hmac.compare_digest)→ 本文(read_json_body)」の順の検査を、do_POST と ytt_request が別々に書いている。合言葉の比べ方と断る文「画面を開き直してから…(合言葉が違います)」は 3 か所に同じものがある。ytt_request は断るときに `mount.drain_body` を呼ばない(do_POST と mount は呼ぶ)。取り込んだ画面の `/studio/api/ytt/…` は、mount が合言葉だけを見てから ytt_request へ回す。このため Host/Origin で断るときだけ本文を読み捨てずに閉じる(mount.drain_body の説明にある「Windows で 403 が届かない」形)。入口自身の api/ytt/… は、同じ検査を 2 回通っている。
- 案: 合言葉の比べ方を ytt_core/httpsec に `token_ok(headers, token)` として置く(Host/Origin と同じ 1 か所)。launch には「断るなら本文を読み捨てて (番号, JSON) を返し、通れば本文を返す」関数を 1 つ置き、do_POST と ytt_request の両方が使う。
  ```
  def guard_post(self, h, limit):
      ok = httpsec.host_ok(h.headers, self.allowed_hosts) and httpsec.origin_ok(...) and httpsec.fetch_site_ok(h.headers)
      if not ok or not httpsec.token_ok(h.headers, self.token):
          mount_mod.drain_body(h.headers, h.rfile); return None, (403, FORBIDDEN if not ok else TOKEN_FAIL)
      return read_json_body(h.headers, h.rfile, limit)
  ```
- 理由: 検査の順番・断る文・読み捨てるかどうかが 1 か所で決まる。AGENTS の「Host/Origin 検査は ytt_core の 1 か所」に、合言葉もそろう。
- 影響・リスク: do_POST は Host/Origin で断るとき今は本文 `forbidden` の text/plain を返し、ytt_request は JSON を返す。どちらかにそろえると応答の形が変わる(画面は 403 の番号しか見ていないはずだが要確認)。ytt_request が Host/Origin で断るときにも本文を読み捨てるようになる(良い方向の変化)。
- テスト: test_launch.py(合言葉・Origin の検査)・test_mount.py(test_csrf_token など取り込んだ画面の合言葉)・test_window.py(api/ytt/… の open-window・streamer-colors・prefs)・e2e_portal.py

##### 2. 終了の後始末が 2 か所にあり、「すべて終了」では 2 回走り、Ctrl+C ではまとめて実行を閉じない(優先度: 高・削れる行数の目安: 約 8 行)
- 場所: `src/home/launch.py:1127-1138`(request_shutdown)・`src/home/launch.py:1315-1327`(main の finally)
- 今: request_shutdown は close_watchers → `_autorun.close()` → stop_all → unmount_all → shutdown() を行う。そのあと serve_forever が戻ると、main の finally が close_watchers → sup.close → stop_all → unmount_all をもう一度行う(Mount.stop の `mod.finish()` も 2 回呼ばれる)。Ctrl+C・黒い画面の×の経路は finally だけを通るので、`_autorun.close()` が一度も呼ばれない。
- 案: 後始末を `PortalServer.teardown()` にまとめる(1 回だけ動く。2 回目は何もしない)。`autorun.close()` もその中で stop_all より前に呼ぶ。request_shutdown は「closing を立てて記録を 1 行書き、shutdown() する」だけにして、後始末は finally の teardown() に任せる。
- 理由: 後始末の順番の正が 1 つになる。新しい見張り(live のような部品)を足すときに 2 か所を直さなくてよい。
- 影響・リスク:
  - 要確認: Ctrl+C の経路で autorun.close() が無いのは意図どおりか。無いと、ツールを止めている間に実行中の段が StepError で「失敗」として記録(autorun-runs.jsonl)に書かれ、待ちの記録から外れて次の起動で戻らない可能性がある。M5 の説明(黒い画面を閉じても続く)と食い違う。
  - request_shutdown を軽くすると、順番が「HTTP を止める → ツールを止める」に変わる(今は逆)。新しい入口は server_close でポートが空くのを待つので、ポートが空く時刻は今と同じ。
  - finish() が 2 回呼ばれても安全かどうかは、各ツールの finish 次第(要確認)。
- テスト: test_launch.py の restart_self の 3 つ(request_shutdown を差し替えている)・e2e_portal.py(すべて終了)・test_autorun.py の M5(close のあとは記録しない)

##### 3. まとめて実行の「ツールの仕事が終わるまで待つ」骨組みを 5 回書いている(優先度: 中〜高・削れる行数の目安: 約 20 行)
- 場所: `src/home/autorun.py:1424-1443`(_analyze_item)・`1527-1538`(_step_export)・`1564-1584`(_step_transcribe)・`1710-1723`(_pack_one)・`1806-1822`(_wait_job)
- 今: 5 か所とも次の形を書いている。run.owned を置く → `while True: self._wait(run)` → ツールの一覧を読む → 終わっていれば抜ける。`except Cancelled` ではツールの取り消しを呼んで raise し、`finally` で run.owned を None に戻す。_wait_job はこのうち「編集」の 1 ジョブ用でしかない。
- 案: `_poll(run, owned, read, cancel)` を 1 つ作る。read() は終わったら結果を、まだなら None を返す(進み具合の st["detail"] は read の中で書く)。_wait_job はこれを呼ぶだけになり、書き出し・解析・文字起こしの複数ジョブ・パックも同じ形になる。
  ```
  def _poll(self, run, owned, read, cancel):
      run.owned = owned
      try:
          while True:
              self._wait(run); r = read()
              if r is not None: return r
      except Cancelled: cancel(); raise
      finally: run.owned = None
  ```
- 理由: 「中止したらツールの仕事を取り消す」「起動し直すの材料(owned)を外す」という守りが 1 か所になり、段を足すときに漏れない。
- 影響・リスク: 次の違いを引数で吸収すれば、動きは変えずにできる。
  - 書き出しは今 owned を置かない(REDO_STEPS に export が無い = 書き出し中は起動し直しを断る)。owned=None で呼ぶ。
  - 解析は qid が無いとき(人が入れた解析を待つとき)は取り消さない。
  - 文字起こしは取り消しを全部のジョブへ送る。さらに今は投入のループ(1566-1569)も try の中にあり、投入の途中で中止しても投入済みのジョブを取り消す。投入も同じ守りの中に残す必要がある(投入の部分にも except を残すか、投入を read の初回に入れる)。
- テスト: test_autorun.py(中止・各段・restart_info の owned)・test_launch.py(restart_self の redo)・e2e_autorun.py

##### 4. あとから解析の「足す条件」と「一覧の 1 件の形」を何か所にも書いている(優先度: 中・削れる行数の目安: 約 12 行)
- 場所: `src/home/autorun.py:1053-1061`(_defer_import)・`1164-1182`(_defer_after)・`1007-1013`(_defer_clean)・`855-858` と `869-872`(_wake と stop_deferred で、あとから解析を止める処理)
- 今: 「依頼(URL)で区間がある・配信 ID が正しい・解析の段が無い・採用が done か warn・中止でない」という条件を、_defer_import は記録の行で、_defer_after は Run で、別々に書いている。一覧の 1 件 {videoId, title, added, tries, reason, lastTry, requestId} を組み立てる所も 3 か所ある。あとから解析を止める 3 行(cancel・preempted・message)は、_wake と stop_deferred に同じものがある。
- 案: 記録の行は `Run.public()` に v を足したものなので、`_defer_eligible(rec)` を 1 つにして、_defer_after は `_defer_eligible(run.public())` で呼ぶ(「終わってから 30 日」は _defer_import だけに残す)。1 件は `_defer_item(vid, title, request_id)` で作る。止める処理は `_preempt_deferred(reason, message)` にまとめる。
- 理由: 条件が食い違うと、「起動したあとに記録から取り込む分」と「その場で足す分」がずれる。ずれる余地をなくす。
- 影響・リスク: public() の ranges は空なら None で、終わった時点の state は done・error・cancelled のどれか。このため今の 2 つの条件と同じ結果になる(_defer_after の `state != "cancelled"` と、_defer_import の `state in ("done", "error")` は同じ意味)。
- テスト: test_autorun.py のあとから解析の一連(1931 行目あたりから。一覧の読み書き・取り込み・止める)

##### 5. ツールの表を 5 か所に写している(優先度: 中・削れる行数の目安: 約 6 行 + 食い違いの防止)
- 場所: `src/home/launch.py:110-119`(TOOLS の app・dir・version_file・version_re)・`src/home/mount.py:30-41`(MOUNTS の dir・prefix・alias)・`src/ytt_core/runtime.py:19`(TOOL_APPS)・`src/home/autorun.py:159`(TOOL_NAMES)・`src/home/appwindow.py:99`(local_url の既定の prefixes)
- 今:
  - "clip-studio" などの app 名は launch.TOOLS と runtime.TOOL_APPS の 2 か所にある。
  - dir は各行で layout.TOOL_DIRS[id] を引き直している。
  - mount の prefix "/studio" と alias "ytt_tool_studio" は id から決まるのに、手で書いている。
  - ツールの日本語名は launch.TOOLS と autorun.TOOL_NAMES の 2 か所にある。
  - version_file と version_re は、studio と transcribe で同じ値を 2 回書いている。
  - appwindow の既定の prefixes は、実際には使われていない(Opener.open_url は常に prefixes を渡し、入口は `tuple(self.mounts)` を渡す。launch.py:981)。
- 案: launch に `_spec(tid, name, sub, port, **kw)` を置き、app=runtime.TOOL_APPS[tid]・dir=layout.TOOL_DIRS[tid] を埋める。mount は `_mount_spec(tid, csp, **kw)` で prefix="/"+tid・alias="ytt_tool_"+tid にする。autorun.TOOL_NAMES は launch から渡す(残すなら、cut2resolve だけ文が違う理由を書いておく)。appwindow の既定の prefixes は消す。
- 理由: 互換のための識別子(clip-studio・/studio/ など)の正が 1 か所になり、変えてはいけない値を片方だけ直す事故がなくなる。
- 影響・リスク: できる文字列は今と同じで、識別子は変わらない。テストは L.TOOLS の s["dir"] と MOUNTS[...]["alias"] を読むので、辞書の鍵はそのまま残す。autorun.TOOL_NAMES の cut2resolve は「cut2resolve(パックを作る部品)」で、TOOLS の name とは違う。
- テスト: test_launch.py(L.TOOLS の dir)・test_mount.py(MOUNTS の alias)・test_window.py(local_url は prefixes を明示して呼んでいる)・e2e_portal.py・e2e_window.py

##### 6. autorun の関数の中の `import cases` が 5 回あり、同じ読み方も繰り返している(優先度: 中・削れる行数の目安: 約 10 行)
- 場所:
  - 関数の中の `import cases`: `src/home/autorun.py:279・518・622・1346・1363`
  - `txindex.load(txindex.folder(self.root, self.env))`(6 回): `716・780・1557・1742・1792・2080`
  - `cases.read_studio(cases.locations(...)["studio"])`: `623・1347`
  - launch.py にも同じ形: `src/home/launch.py:877・1025・1029`
- 今: 循環 import を避けるための書き方に見えるが、実は不要。autorun は先頭(53 行目)で friend_feedback を読み、friend_feedback は先頭で cases を読む(friend_feedback.py:17)。このため autorun を読み込む時点で cases はもう読み込み済み。cases が先頭で読む cleanup・live_failures も、autorun を先頭では読まない(live_failures は関数の中で読む)。
- 案: 先頭で `import cases` を 1 行にする。AutoRunner に `_docs()`(= txindex.load(txindex.folder(self.root, self.env)))と `_studio_video(vid)`(= cases.read_studio(...).get(vid) or {})の 2 つを置く。launch の streamer_guess も、cases に小さな関数(例: `cases.doc_by_id(root, id)`)を置いて使う。
- 理由: 読む場所(作業データのどこか)と env の渡し方を、1 か所にまとめられる。
- 影響・リスク: txindex.load は更新時刻でキャッシュしているので、呼ぶ回数を減らしても性能はほぼ変わらない(読みやすさの指摘)。先頭で import しても、今も friend_feedback 経由で読まれているので、読み込まれるものは変わらない。
- テスト: test_autorun.py(文書単位・依頼の動画・配信者の自動)・test_window.py(streamer-guess)

##### 7. 入口の GET と api/ytt/… の分岐が長い if の連なりになっている(優先度: 中・削れる行数の目安: 約 15 行)
- 場所: `src/home/launch.py:621-674`(do_GET。parse_qs を 649・654・667 で 3 回)・`975-1017`(ytt_api 43 行)・`1045-1056`(prefs_api の patch。節ごとの wake を if で 4 つ)
- 今: POST は POST_ROUTES の表で分けているが、GET と ytt_api は if の連なり。prefs_api は intake・backup・accuracy の wake.set() を、節ごとの if で書いている。
- 案:
  - GET も `GET_ROUTES = {"/api/status": "_get_status", ...}` にし、`q = parse_qs(u.query)` は do_GET の頭で 1 回だけにする。
  - ytt_api は `YTT_OPS = {"client-log": ..., "deliver": "_ytt_deliver", "streamer-colors": "_ytt_colors", ...}` と小さなメソッドに分ける(streamer-colors の 10 行は、名前の付いたメソッドにすると読める)。
  - prefs_api は `{"intake": self.intake, "backup": self.backup, "accuracy": self.accuracy}.get(section)` で wake する。
- 理由: POST と同じ形になり、API を足すときは表に 1 行足すだけになる。ytt_api の例外の対応(ValueError → 400 など)は、外側の 1 か所に残る。
- 影響・リスク: 動きは変わらない。live の GET(625 行)・/cases.html の転送・STATIC は、表より前に残す。
- テスト: test_launch.py(GET の API・ログ)・test_window.py(open-window・focus-portal・streamer-colors・prefs)・e2e_portal.py・e2e_keymap.py(prefs)

##### 8. prefs の検査で同じ形を写している(優先度: 中・削れる行数の目安: 約 18 行)
- 場所:
  - 真偽の検査が 4 行ずつ 3 回: `src/home/prefs.py:185-192・197-200`(autoArchive・autoAfterStream・autoDelete)
  - `_int_in`(225 行)があるのに同じ式を書き直している: `97・139・155`
  - 制御文字の検査が 4 回: `121・346・453・478`
  - 「同じ鍵は新しい方へ動かし、上限を超えたら古い順に捨てる」が 2 回: `460-463`(remember)と `486-490`(hide)。autorun.py:954-957 の past も同じ形(OrderedDict)
- 案: 真偽は `LIVE_BOOLS = {"autoArchive": "「自動で本番版に作り直す」", ...}` の表をループで回す。整数は `_int_in(x, lo, hi)` を使う。文字列は `_plain(s, n)`(文字列であること・長さ・制御文字なし)を 1 つ置く。記憶の更新は `_lru_put(m, key, value, limit)` にまとめる。
- 理由: 断る文の形がそろい、鍵を足すときは 1 行で済む。
- 影響・リスク: 断る文(画面に出る)を同じ文のまま表に移せば、動きは変わらない。_clean_backup・_clean_accuracy の `isinstance(x, bool) or not isinstance(x, int)` は、_int_in と同じ意味。
- テスト: test_window.py(Prefs・remember・hide)・test_live.py(live の節)・test_backup.py・test_intake.py・test_accuracy.py

##### 9. JSON の設定ファイルを自前で開いて読む所が、ytt_core.fsio で済む(優先度: 中・削れる行数の目安: 約 12 行)
- 場所: `src/home/prefs.py:387-400`(Prefs._load)・`src/home/prefs.py:123`(ネットワーク上のパスの判定)・`src/home/appwindow.py:129-152`(read_mode と write_mode で同じ読み方を 2 回)・`src/home/launch.py:954-963`(_extra_dirs がスタジオの settings.json を open + json.load で読む)
- 今: どれも open → json.loads と読み、壊れていたら既定に戻す。大きさに上限があるのは prefs だけ。prefs の `f.replace("/", "\\").startswith("\\\\")` は、fsio.is_network_path と同じ式。
- 案: `fsio.read_json_file(path, MAX)` を使い、FileNotFoundError と (OSError, ValueError) を分けて受ける(prefs の「壊れていたか」はこれで分かる)。appwindow は `_read_settings(path) -> dict` を 1 つにして、read_mode と write_mode の両方が使う。prefs._clean_folder は fsio.is_network_path を使う。
- 理由: 巨大なファイル・BOM・NaN の扱いが、他のツールと同じ 1 か所になる。
- 影響・リスク: read_json_file は NaN / Infinity を断る(今の prefs・appwindow は通す)。保存する側は検査済みの値しか書かないので、実害は無いはず。appwindow の settings.json と launch の _extra_dirs に大きさの上限(例: 1MB)が付く。
- テスト: test_window.py(Prefs の壊れたファイルの退避・窓の設定)。_extra_dirs を直接見るテストは無い(「調子」の空き容量の行で間接に通るだけ。要確認)

##### 10. 入口の小さな処理が ytt_core の既存の関数で済む(優先度: 中・削れる行数の目安: 約 12 行)
- 場所: `src/home/restart.py:105-118`(port_free の「つながるか」)・`src/home/launch.py:417-420`(stop の強制終了)・`src/home/launch.py:459-462`(_cleanup_runtime のファイル削除)・`src/home/restart.py:89-102` と `src/home/launch.py:1115-1118`(SO_EXCLUSIVEADDRUSE の付け方が 2 か所)
- 案:
  - port_free は `if runtime.port_open(port, timeout): return False` のあとに `_bind_ok` を呼ぶ。
  - 強制終了は `tools.kill_quiet(proc)` にする。
  - ファイル削除は `fsio.unlink_quiet(runtime.runtime_path(self.rdir, t.id))` にする。
  - 排他の bind は関数を 1 つ(例: `restart.exclusive_bind_opts(sock)`)にして、PortalServer.server_bind と _bind_ok の両方が使う。
- 理由: 同じ規則(127.0.0.1 固定・ポートの範囲・Windows の排他)が 1 か所になる。restart の説明にある「入口と同じ形で bind する」がコードで保証される。
- 影響・リスク:
  - runtime.port_open は 127.0.0.1 固定で、1024 未満のポートは False(= 空いている扱い)を返す。port_free の host 引数は使わなくなる(呼ぶ側はどれも既定の 127.0.0.1)。
  - kill_quiet は先に poll() で終わっていれば kill しない(今は kill して OSError を無視している)。
  - _spawn の CREATE_NEW_PROCESS_GROUP を tools.no_window_flags に替えてはいけない。NO_WINDOW が付くと Ctrl+Break が届かなくなる(restart.py の説明)。
- テスト: test_restart.py(port_free・wait_port_free)・test_launch.py(止める・強制終了・.runtime の後始末)

##### 11. ファイルの末尾を読む処理が 2 つある(優先度: 低・削れる行数の目安: 約 8 行)
- 場所: `src/home/launch.py:154-172`(tail)・`src/home/autorun.py:457-484`(read_runs_log)。ログを回す処理も `src/home/launch.py:145-151`(rotate → .old.log)と `src/home/clientlog.py:26-36`(append_line → .1)の 2 つがある。
- 今: どちらも「末尾 N バイトへ seek → 途中から読んだ最初の行を捨てる」を自前で書いている。
- 案: clientlog(記録のファイルを扱う 1 か所)に `read_tail(path, max_bytes)` を置く。tail はその結果を decode・split し、read_runs_log は .1 と今のファイルに使う。
- 影響・リスク: read_runs_log は残りの大きさ(left)を「読んだ範囲 = size - start」で減らしている。read_tail が bytes だけを返すと、捨てた欠けた行の分だけ数え方がずれる(.1 を少し多めに読む)。(data, 読んだ範囲) を返す形にすれば今と同じになる。rotate と append_line は回したファイルの名前(.old.log と .1)が違い、health・cleanup がその名前を見ているかもしれないので、そろえない(要確認)。
- テスト: test_launch.py:393-398(tail)・test_autorun.py(history・past)

##### 12. busy を待ってやり直すループと、字幕の行があるかの式を 2 回ずつ書いている(優先度: 低・削れる行数の目安: 約 8 行)
- 場所: `src/home/autorun.py:1517-1525` と `1699-1704`(409 busy なら BUSY_WAIT だけ待ってやり直す)・`1672` と `1841`(`any(s.get("text", "").strip() and not s.get("cut") for s in doc.get("segments") or [])`)
- 案: `_call_when_free(run, st, tool, path, body, waiting_msg) -> (status, res)` と `_has_captions(doc)` を置く。
- 影響・リスク: 動きは変わらない。
- テスト: test_autorun.py(書き出しの busy・パックの busy・カットのある文書)

##### 13. 「bool でない整数で範囲内」と「ID の形」の検査を、毎回その場で書いている(優先度: 低・削れる行数の目安: 約 5 行・主に読みやすさ)
- 場所:
  - 整数・数の検査(計 約 20 か所): `src/home/autorun.py:288・309・379・384・747・939-940・1011・1385・1397・1629・1643`、`src/home/prefs.py:97・139・155・364`、`src/home/cases.py:119`、`src/home/clientlog.py:51`
  - ID の形: `src/home/autorun.py:226`(_yt_id_ok)・`229`(_doc_id_ok)・`635`(_marks_arg)・`672`(start)、`src/home/cases.py:325`(_check_case_id)・`65`(MARK_RE)
  - `src/home/autorun.py:390` の `_num(created) or (...)` は、前半が常に偽になる(created はエポック秒で約 1.7e9 あり、_num の上限 1e7 を超える)。
- 案:
  - prefs._int_in を ytt_core/schemas.py の num の隣へ `int_in(x, lo=None, hi=None)` として移し、home の各所で使う。
  - ID は正規表現の定数にする。_marks_arg は cases.MARK_RE と同じ形(ASCII の英数字・-・_ で 40 字まで)なので、それを使える。_yt_id_ok は `[\w-]{11}`(re.ASCII)で書ける。
  - 390 行は `isinstance(c, (int, float)) and not isinstance(c, bool) and c == c` の 1 つの条件にする。
- 影響・リスク: start(672 行)・_doc_id_ok・_check_case_id は `str.isalnum()` を使っていて、全角の英数字やかなも通す。ASCII の正規表現にそろえると、今は通る全角の ID を断るようになる(スタジオ・編集の ID は ASCII なので実害は無いはずだが要確認)。390 行は今 NaN を通す(created が nan になる)ので、そろえると NaN を捨てるようになる。
- テスト: test_autorun.py(restore・start の検査)・test_cases.py(案件の ID)・test_window.py(prefs)

##### 14. launch・mount の細かい重複(優先度: 低・削れる行数の目安: 約 10 行)
- 場所: `src/home/launch.py:309-316`(_find_external の seen)・`465-499`(_tick 35 行。入れ子が深い)・`838-856`(`os.path.dirname(sup.logs_dir)` が 6 回)・`849` と `901`(依頼の受付のフォルダを `prefs.get` と `intake._cfg()` の 2 通りで読む)・`src/home/mount.py:135-140` と `166-171`(301・302 の転送の見出しを 2 回書く)
- 案:
  - seen の代わりに `for p, path in dict.fromkeys(cands):` と書く。
  - _tick は「起動中」と「動作中・別の画面」の 2 つの関数に分ける。
  - `app_dir = os.path.dirname(sup.logs_dir)` を 1 回だけ求める。
  - 受付のフォルダは小さな関数 1 つ(例: `self._intake_folder()`)で読む。cleanup_candidates が Intake の private な `_cfg()` を外から読んでいるので、公開の読み方にそろえる。
  - mount は `_redirect(code, location, extra)` を 1 つ置く。
- 影響・リスク: 動きは変わらない。
- テスト: test_launch.py(別の画面で動いているツールの検出・監視)・test_mount.py(/studio → /studio/ の 301・cut2resolve → 編集の 302)

##### 15. 届けるときの後片付け(try/except/finally)を 2 回書いている(優先度: 低・削れる行数の目安: 約 6 行)
- 場所: `src/home/autorun.py:1994-2014`(_deliver_group)・`2047-2064`(_deliver_one)。あわせて `1890-1899`(_remember_styles)
- 今: 「先に置いたまとめ動画(placed)を失敗したら消す・OSError を StepError(_place_error)に変える・最後に一時の preview を消す」を 2 回書いている。_remember_styles の `except Cancelled: raise` には届かない(client.call は Cancelled を上げない。上げるのは StepError と、OSError から変えたものだけ。テストにも Cancelled を上げる偽物は無い)。
- 案: `contextlib.contextmanager` で `_placing(preview)` を作る(yield で placed を控える箱を渡す)。_remember_styles は `except Exception` だけにする。
- 影響・リスク: 例外の型と片付けの順番を同じにすれば、動きは変わらない。
- テスト: test_autorun.py(① 全自動の届ける段・組・失敗)・test_deliver.py

#### 他のグループとの重複の疑い
- `(e.strerror or e.__class__.__name__)` で理由の文を作る形: 担当の中だけで 8 か所ある(launch.py 385・722・774・931・1016・1063、autorun.py 2028、cases.py 387)。autorun.py 553・974・1081 は "%s %s" の別の形。担当外の accuracy・backup・deliver・intake・live*・friend_feedback にも約 25 か所ある(疑い)。live_excite_worker.py:260 には同じ働きの小さな関数がある。ytt_core に `why(e)` を 1 つ置けば全体で使える。
- 「bool でない整数」の検査: editor/ed_jobs.py(8 か所)・ed_store.py(4)・studio/analyze.py(3)・home の live*・intake にもある(疑い)。指摘 13 の int_in を ytt_core に置くなら、一緒に使える。
- 合言葉の比べ方: recorder/recorder.py:194 も hmac.compare_digest を自前で書いている(合言葉は別物なので、指摘 1 の httpsec.token_ok が使えるかは要確認)。
- 末尾を読む処理: studio/common.py・studio/analyze.py にも SEEK_END を使う読み方がある(疑い。指摘 11 と同じ部品にできるかもしれない)。
- 要求の本文の読み方(read_json_body・drain_body): スタジオ・編集の serve.py にも同じ役目の処理があるはず(疑い。担当外なので読んでいない)。
- `_num`・`_int_ms`・`_ms_ok` に似た小さな関数: txindex._num・live_archive・live_requests・cut2resolve/serve.py・editor/ed_drill.py にも、同じような名前の数の検査がある(疑い)。


### G2 home-live(担当: src/home/live.py・live_detect.py・live_excite_worker.py・live_tx.py・live_tx_worker.py・live_failures.py・live_requests.py・live_align_worker.py・live_cleanup.py、合計 約 4,520 行)

#### 全体の傾向
- 機能を足すたびに「その場で同じ小道具を書く」形が積み重なっている: 子プロセスの起動と止め方(3 通り)・録画元/録画の id の検査(5 か所)・JSON の読み書き(各ファイルで手書き)・LiveError → error 名の対応(4 か所)。どれも lint の「12 行の写し」には届かない 3〜10 行の写しなので、測る道具に引っかからずに増えている。
- ワーカー(live_excite_worker.py)が live_export.py の時刻・id・正規表現・優先度の小道具を写して持っている。値が同じことはテストで守られていない(test_live_detect は EW.ID_RE などを LX と比べていない)。
- 設定(prefs)の読み直しが細かい関数ごとに起きる。スタジオが 3 秒ごとに呼ぶ GET /live/api/peaks 1 回で設定のファイルを約 11 回開いて検査し直している(下の 3)。
- 見回り(Live.tick・health)は「try → note」を 9 回並べた形で長い。関数の長さは基準内だが、分岐の中身は 1 つの小道具で畳める。
- live_align_worker.py・live_failures.py はすでに小さく、指摘はほぼ無い(14 で 1 件だけ)。

#### 指摘

##### 1. 子プロセスの起動(ログ付き)と「孫ごと止める」が 3 通りずつある(優先度: 高・削れる行数の目安: 約 30 行)
- 場所: 起動 `src/home/live.py:1056-1089`(Live.spawn)・`src/home/live_detect.py:264-290`(Detector._spawn)。止め方 `src/home/live.py:139-156`(kill_tree)・`src/home/live_excite_worker.py:488-509`(kill_tree)・`src/home/live_tx.py:223-231`(close の p.kill)・ログを回す `src/home/live_detect.py:274-278`(launch.py:145 の rotate と同じ処理)
- 今: env を作る 3 行(PYTHONIOENCODING・PYTHONUNBUFFERED)・ログの見出しを書く 3 行・`open(log, "ab")` → Popen の並びが Live.spawn と Detector._spawn にそのまま 2 つある。excite.log は 2MB で回すが recorder.log は回さない(どこでも回していない。launch.py の rotate は launcher.log とツールのログだけ)。kill_tree は live.py(PATH の taskkill・wait あり)と ワーカー(System32 の taskkill.exe を直に・非 Windows は killpg)の 2 つ。live_tx.close は `try: p.kill() except OSError` = tools.kill_quiet と同じ。
- 案: live_excite_worker.py(入口もすでに import している軽い部品)に 1 つずつ置く。
  ```
  def start_logged(cmd, log_path, cwd, flags, rotate=LOG_MAX):   # env・回す・見出し・Popen
  def kill_tree(proc, wait=None)                                # System32 の taskkill を直に。wait があれば待つ
  ```
  Live.spawn は CREATE_BREAKAWAY_FROM_JOB の再試行だけを残し、Detector._spawn は 1 行に。live.kill_tree は `EW.kill_tree(proc, wait=5.0)`、live_tx.close は `tools.kill_quiet(p)`。Detector._kill(CTRL_BREAK で状態を保存させる穏やかな止め方)は目的が違うので残す。
- 理由: 起動の約束(env・優先度・ログの回し方)を 1 か所で直せる。taskkill を PATH から探す live.py 側は、PATH の先に置かれた偽の taskkill を拾う余地があるので、ワーカー側の絶対パスにそろえるほうが安全。
- 影響・リスク: recorder.log も 2MB で回るようになる(動きが変わる。録画の部品が自分で回しているかは要確認 = src/recorder は担当外)。テスト: test_live.py の `test_spawn_then_running_then_restart_old_version`・`test_unresponsive_own_process_is_killed`・`test_quit_accepted_but_own_process_does_not_exit_is_killed`、test_live_detect.py の `test_spawn_heartbeat_restart_and_stop`・`test_stop_kills_child_of_ytdlp`、test_live_tx.py。

##### 2. API の振り分けが if の連なりで、LiveError → error 名の対応が 4 か所でばらばら(優先度: 高・削れる行数の目安: 約 20 行)
- 場所: `src/home/live.py:483-535`(handle_get)・`:552-585`(_api_post)・error 名 `:505`・`:522`・`:584`・`:828`・`self._server = h.server` が `:501`・`:508`・`:542` の 3 回
- 今: handle_get は peaks と marks/exports で別々の try/except を持ち、error 名の決め方が `400→bad_request else not_found`(505・828)・`400/404/それ以外 error`(522)・dict で 4 種(584)と 3 通り。_api_post は path の if を 8 つ並べる。
- 案: 
  ```
  ERR_NAMES = {400: "bad_request", 404: "not_found", 409: "conflict", 502: "recorder_down"}
  GET_API = {"/live/api/peaks": "_get_peaks", "/live/api/marks": "_get_marks", "/live/api/exports": "_get_exports", "/live/api/info": "_get_info"}
  fn = GET_API.get(u.path)   # → 1 つの try で h._json(200, getattr(self, fn)(q))、except LiveError → h._fail(e.code, ERR_NAMES.get(e.code, "error"), str(e))
  ```
  POST も同じ表(`/live/api/begin`・`marks`・`export`・`adopt`・`peaks`・`export/cancel`・`archive`・`archive/cancel`)にし、`self._server = h.server` は振り分けの前に 1 回。ytt() の stop も ERR_NAMES を使う。
- 理由: 新しい API を足すときに「表に 1 行 + 関数 1 つ」になる。error 名の食い違い(同じ 409 が GET では not_found/error、POST では conflict)が無くなる。
- 影響・リスク: GET の側で 409・502 の LiveError が出たとき、error 名が `not_found`/`error` から `conflict`/`recorder_down` に変わる(動きが変わる)。スタジオの画面は review.js:442 で `e.code === 'conflict'` を 1 か所見ている(スタジオの API の話で、ここの GET とは別 = 要確認)。テスト: test_live.py の `test_on_page_and_relay`・`test_marks_api`・`test_begin`・`test_export_studio`・`test_ytt_live_status_and_stop`(error 名を 419・523・549・589・633 行で確かめている)、test_live_detect.py の `test_routes_through_live`、test_live_archive.py、e2e_live_studio.py。

##### 3. 1 回の要求で設定のファイルを約 11 回読み直している(優先度: 高・削れる行数の目安: 約 5 行(主な効果は読み込みの回数 11 → 1))
- 場所: `src/home/live.py:322-326`(cfg = 毎回 prefs.get → prefs.py:387-420 でファイルを開いて JSON を読み、live の節を検査)・`:328-340`(enabled・recorders。recorders は毎回 token.txt も読む `:427-432`)、`src/home/live_detect.py:130-143`・`:391-412`、`src/home/live_tx.py:72-111`(ready は毎回 shutil.which で ffmpeg を探す `:99`・`:104`)
- 今: GET /live/api/peaks(録画中のスタジオが 3 秒ごと = review.js:1511・1512)1 回で、live.py:485 の enabled → live_detect.py:394 の find → recorders → `:406` detect_cfg → `:409` enabled(live.enabled + detect_cfg)→ `:412` adopt_for → adopt_cfg → live_tx.py:107 status → ready の中で cfg・live.enabled・paths → cfg、`:109` で cfg を 2 回 = 約 11 回。中継 /live/r/…(hls.js がプレイリスト・セグメントごとに呼ぶ)も find → recorders で毎回 設定 + token.txt を読む。
- 案: 要求の頭(handle_get / _api_post / tick)で `cfg = self.cfg()` を 1 回読んで渡す。`recorders(cfg)` はもう cfg を受け取れる形(live.py:331)なので、`find(rid, cfg=None)`・`Detector.detect_cfg(cfg)`・`adopt_for(req, cfg)`・`LiveTx.status(cfg)` に引数を 1 つ足すだけ。token.txt は (mtime_ns, size) で覚える(live_detect.py:351-354 の series と同じ覚え方)。ffmpeg の場所は LiveTx.tick で探して覚える。
- 理由: 同じ値を何度も検査し直す処理が消える(設定を変えた直後の食い違いも 1 回の要求の中では起きない)。
- 影響・リスク: 時間で覚える形(TTL)にすると、テストが `prefs.patch` の直後に結果を見ている所(test_live.py:894 ほか・test_live_detect.py:901-943)で食い違うので、「1 回の要求の中だけ同じ値」にとどめる。prefs.py 側で覚えるのは担当外。テスト: test_live.py・test_live_detect.py・test_live_tx.py 全体。

##### 4. ワーカーが live_export.py の小道具を写して持っている(テストで一致を守っていない)(優先度: 中・削れる行数の目安: 約 35 行)
- 場所: `src/home/live_excite_worker.py:134-147`(iso_epoch・epoch_iso = live_export.py:126-144)・`:150-156`(video_id = live_export.video_id_of。作りが違う: 正規表現 vs urlsplit)・`:159-161`(child_flags = live_export.low_flags と同じ値)・`:107-109`(ID_RE・REC_RE・SEG_URI_RE = live_export.py:71-75)・`:112-113`(YT_ID_RE・VID_RE)・`:449-479`(RecorderClient._get = live.py:443-476 の request/call と同じ URL の検査・ヘッダー)。REC_RE はさらに live.py:94 の RELAY_POST_RE の中にも写しがある
- 今: 「録画元の id の形」などを変えるときに 3〜4 か所を同時に直す必要があり、test_live_detect.py は EW の値を LX と比べていない。
- 案: ワーカーの頭で `from live_export import iso_epoch, epoch_iso, ID_RE, REC_RE, SEG_URI_RE, low_flags as child_flags` とする(live_export が読むのは clientlog・live_failures・ytt_core の標準ライブラリだけの部品 = numpy を読まない決まりのまま。入口では live_detect が両方をもう読んでいる)。録画元への GET は `Live.request` の中身をワーカーの関数 `open_recorder(rc, method, path, body, timeout) -> (conn, resp)` に移して、Live.request と RecorderClient の両方が呼ぶ。
- 理由: 録画元との約束(id の形・時刻の書き方・合言葉のヘッダー)が 1 か所になる。
- 影響・リスク: video_id はそろえると URL の読み方がわずかに変わる(例: `/live/<id>/xxx` の形。live.validate_url が YouTube の URL を watch?v= にそろえてから録画するので実害は小さい = 要確認)。ワーカーが起動時に読む部品が増える(数十 ms)。テスト: test_live_detect.py の WorkerSimTest・FfmpegTest(`test_hls_segments_through_recorder_api`)・NoNumpyTest、test_live.py の `test_validate_url`(video_id_of)。e2e が一時フォルダに写すファイルの一覧は live_export.py を含んでいるか要確認。

##### 5. 録画元・録画の id の検査が 5 か所(優先度: 中・削れる行数の目安: 約 10 行)
- 場所: `src/home/live.py:588-595`(Live._ids)・`:514`(exports の絞り込み)、`src/home/live_detect.py:66-68`(_ids_ok)・`:385-389`(_check_ids = Live._ids と文・番号まで同じ)、`src/home/live_cleanup.py:77`(check)。担当外では live_archive.py:791 にも
- 今: 同じ 2 つの正規表現と「その録画元はありません 404」を各所で書いている。live_cleanup.check は文字列でない値で `.match` が TypeError になりうる(今は入口の中からしか呼ばれない)。
- 案: `_ids_ok(rc, rec)`(live_detect.py:66 の形)を 1 つだけにして、Live._ids はそれを使う。Detector._check_ids は `self.live._ids(rc, rec)` を呼ぶだけにして消す。live.py:514・live_cleanup.py:77 も `_ids_ok`。
- 理由: 検査の規則と文言が 1 か所になる。
- 影響・リスク: 動きは同じ(文・番号が同じ)。テスト: test_live_detect.py の `test_post_dismiss_restore_adopt`・`test_get_full_since_and_series`、test_live.py の `test_marks_api`、test_live_archive.py(録画を消す)。

##### 6. JSON の読み書きを各ファイルで手書きしている(fsio・EW.read_json で足りる)(優先度: 中・削れる行数の目安: 約 20 行)
- 場所: 読む `src/home/live.py:222-233`(studio_out_dir)・`:242-250`(studio_review)、`src/home/live_tx.py:117-127`(_load)、`src/home/live_requests.py:67-73`(_load)。書く `src/home/live_tx.py:129-135`・`src/home/live_requests.py:79-84`・`src/home/live_detect.py:447`・`:507`・`src/home/live_tx_worker.py:58-61`(.part に書いて os.replace)。書く前の `os.makedirs`(fsio.atomic_write が中で作る = ytt_core/fsio.py:55-56)が `live_detect.py:446`・`live_tx.py:132`・`live_requests.py:81`・`live_excite_worker.py:1067`・`:1422`
- 今: 「開く → json.load → dict でなければ {}」を try/except 込みで 6〜10 行ずつ書いている。live.py の 2 つは大きさの上限も BOM の扱いも無い(fsio.read_json_file は両方ある)。
- 案: 読むのは `EW.read_json(path, max_bytes)`(dict か None。live_detect がすでに使っている)にそろえる: `st = EW.read_json(p, 1 << 20) or {}`。書くのは `fsio.write_json(path, obj, indent=None or 1)`。live_tx_worker は `fsio.atomic_write`(_paths() で src を通したあとなら読める)。makedirs の 5 行は消す。
- 理由: 読み方の守り(大きさの上限・NaN を受けない・BOM)が全部にかかり、各所の try/except が 1 行になる。
- 影響・リスク: 書いた JSON の空白・末尾の改行が少し変わる(読む側は json なので影響なし)。live.py の 2 つは巨大な settings.json を読まなくなる(良い方向の変化)。テスト: test_live.py の `test_defaults_when_unreadable`・`test_follows_studio_settings`・`test_bad_values_fall_back_like_studio`・`test_broken_file`・`test_put_get_all_remove`、test_live_tx.py。

##### 7. 見回り(tick)と「調子」(health)の「try → note」の繰り返し(優先度: 中・削れる行数の目安: 約 15 行)
- 場所: `src/home/live.py:1002-1013`・`:1021-1025`(tick)、`:1115-1139`(health。失敗の一覧を 2 回 sort して切る `:1123`・`:1127`)
- 今: `try: x() except Exception as e: self.note("リアルタイム切り抜き: …: %r" % (e,))` を tick に 4 回・health に 5 回並べている。health は archiver と detector の失敗を足すたびに並べ直す。
- 案: 
  ```
  def _guard(self, what, fn, default=None):
      try: return fn()
      except Exception as e: self.note("リアルタイム切り抜き: %s: %r" % (what, e)); return default
  ```
  health は 3 つの失敗の一覧を集めてから `sorted(...)[:MAX_LIST]` を 1 回(上位 N を 2 回に分けて取っても 1 回で取っても結果は同じ)。tick の「古い版なら起動し直す」(`:1031-1041`)と「置き場所を伝える」(`:1042-1048`)は関数に分けると tick が見回りの順番だけになる。
- 理由: 見回りの順番が一目で読める。新しい見張りを足すのが 1 行になる。
- 影響・リスク: 記録の文が「…の見回りでエラー: …」から少し変わる(what に今の文を入れれば同じにできる)。テスト: test_live.py の `test_health_has_disk`・`test_same_text_in_band_and_health`・`test_off_has_no_failures_and_portal_health`・`test_spawn_then_running_then_restart_old_version`、test_live_detect.py の `test_health_row_and_failures`。

##### 8. adopt と export_studio の前処理が同じ並び・begin の「録画中ならそれ」が 2 回(優先度: 中・削れる行数の目安: 約 10 行)
- 場所: `src/home/live.py:681-694`(export_studio)と `:777-806`(adopt)、`:623-625` と `:634-637`(begin)
- 今: どちらも check_origin → auto_cfg → check_after・check_streamer → _ids → _request_for → _rec_status の順で、最後に `url=st.get("url") if isinstance(...)`・`title=...` を付けて add_studio を呼ぶ。begin は「録画中の同じ配信があればそれを返す」辞書を 2 回組み立てる。
- 案: `_prepare(body) -> (origin, auto, after, streamer, rc_id, rec, req, st, first)` を 1 つ作り両方から呼ぶ(adopt は label・text・score の検査をその前に)。begin は `def found_view(r): return {"live": True, "recorder": rc["id"], "recording": _rec_view(r, ch), "existing": True}` を 1 つ。
- 理由: 「書き出しの検査の順番」(録画元に聞く前に検査する)が 1 か所になり、片方だけ直す事故が無くなる。
- 影響・リスク: export_studio は今 `body.get("url")`・`body.get("title")`(画面の値)、adopt は録画元の状態 st の値を渡している。共通にするのは前処理だけにして、add_studio へ渡す値は今のまま分ける。テスト: test_live.py の `test_export_studio`・`test_adopt_server_side`・`test_adopt_and_export_with_friend_request`・`test_begin`、test_live_detect.py の `test_auto_adopt_m11`。

##### 9. スタジオの解析の設定(spec)の検査が入口とワーカーで 2 通り(優先度: 中・削れる行数の目安: 約 8 行)
- 場所: `src/home/live_detect.py:71-80`(clean_spec。範囲 SPEC_RANGES に丸める)・`src/home/live_excite_worker.py:1162-1169`(load_config。有限の数なら丸めずに使う)
- 今: 感度・枠の検査 clean_detect は「入口が書くときとワーカーが読むときの両方で通す」1 つの関数(EW:286)なのに、spec だけ 2 通り。
- 案: clean_spec を EW に移し、load_config は `spec = clean_spec(d.get("spec"))`、live_detect は `EW.clean_spec`。
- 理由: clean_detect・clean_hint・clean_requests と同じ形にそろう(読む側でも範囲を守る)。
- 影響・リスク: ワーカーが範囲の外の値を丸めるようになる(入口が丸めて書くので、ふだんの値は同じ。手で書いた config.json だけ変わる)。テスト: test_live_detect.py の `test_config_and_spec_from_studio`・`test_bad_numbers`・`test_length_hint_from_human_records`。

##### 10. 友人の依頼の settings は Store が検査済みなのに、読む側で既定を当て直している(優先度: 中・削れる行数の目安: 約 6 行)
- 場所: `src/home/live_detect.py:148-150`(requests_cfg の `.get("sens", "normal")`・`6`・`45`)・`:159-160`(adopt_for の waitMin の型と範囲の検査)。既定は `src/home/live_requests.py:20`(SETTINGS_DEFAULT)にある。live_requests.py:74-75 のコメントのとおり、Store は読み直した項目も clean_settings を通す(put も `:103`)
- 今: 依頼の既定値(6・45・"normal"・5)が live_detect にも写っている(f)。live.py:789 は `req["settings"]["pad"]` をそのまま使っており、扱いがそろっていない。
- 案: `{k: {x: v["settings"][x] for x in ("sens", "perHour", "length")} for k, v in ...}`・`{"enabled": True, "waitMin": req["settings"]["waitMin"]}`。あわせて live_requests.py:90・94 の `json.loads(json.dumps(v))` は `copy.deepcopy(v)`(c)。
- 理由: 既定値と検査が live_requests の 1 か所になる。
- 影響・リスク: 動きは同じ(settings は常に検査済みの全部の鍵を持つ)。テスト: test_live_detect.py の `test_friend_request_with_detect_off`・`test_auto_adopt_friend_request`・`test_friend_request_only_with_its_settings`、test_live.py の `test_put_get_all_remove`・`test_broken_file`。

##### 11. 録画の一覧の取得と形の変換が 3 か所・1 回の見回りで /live/list を 2〜3 回読む(優先度: 中〜低・削れる行数の目安: 約 10 行)
- 場所: `src/home/live.py:406-416`(list_recordings)・`:418-425`(recording_state)・`:840-860`(recent)。呼ぶ側 `src/home/live_detect.py:527`(auto_tick)・`src/home/live_tx.py:183`(tick)・live_archive.py:786(after_tick。担当外)
- 今: どれも `live_export.rec_list(self.call, rc)` → iso_epoch で時刻を数にする、を別々に書く。Live.tick の中で detector.tick と livetx.tick がそれぞれ list_recordings を呼ぶので、30 秒ごとに同じ一覧を 2 回以上取る(ワーカーも 6 秒ごとに別に取る)。
- 案: list_recordings に `rc_id=None` の絞り込みと recent() と同じ短い覚え(STATUS_CACHE 秒)を足し、recording_state は `next((r for r in self.list_recordings(rc_id) if r["id"] == rec), None)` から作る。
- 理由: 録画元の一覧の読み方が 1 か所になる。
- 影響・リスク: recording_state は `active` を `r.get("active") is True` だけで見て、endedAt が無ければ lastPdt を使う(list_recordings は REC_ACTIVE の状態も active に数える)。そろえると「録画が終わったか」の判定が変わりうる(要確認)。覚えを入れると数秒古い一覧を使う。テスト: test_live_archive.py(終わった録画の見回り)・test_live_detect.py の `test_auto_adopt_m11`・test_live_tx.py。

##### 12. live_tx.py の過剰な防御と関数の中の import(優先度: 低・削れる行数の目安: 約 10 行)
- 場所: `src/home/live_tx.py:312-317`(`import shutil` を try/except Exception で包んで `rmtree(ignore_errors=True)` = 上げない関数をさらに包む)・`:322`(関数の中の `import sys`)・`:324-326`(pythonw → python.exe = live_archive.py:294-301 の worker_python と同じ)・`:226-231`(close = tools.kill_quiet)・`:193-194`(view の失敗を黙って continue)
- 今: 上の 4 つは標準ライブラリ・既存の関数で 1 行になる。
- 案: shutil・sys は頭で import、`shutil.rmtree(wdir, ignore_errors=True)` だけにする。`py = live_archive.worker_python(self.python)`。close は `tools.kill_quiet(self.proc)`(None の確かめは残す)。
- 理由: 読む量が減り、pythonw の扱いが 1 か所になる。
- 影響・リスク: 動きは同じ。live_tx が live_archive を import する(循環しないことは要確認: live_archive は live_tx を読んでいない)。テスト: test_live_tx.py。

##### 13. RecState の to_json と from_json が 2 つの手書きの並び(優先度: 低・削れる行数の目安: 約 15 行)
- 場所: `src/home/live_excite_worker.py:805-814`(to_json)・`:816-847`(from_json)。ChatFeed も `:544-560` で同じ形
- 今: 20 個ほどの属性を「書く並び」と「読む並び」で 2 回書く。片方だけに足すと、続きからの再開で値が黙って既定に戻る。
- 案: 単純な属性は表にする(c: 表 + getattr/setattr)。
  ```
  PLAIN = (("seg_since", "segSince", int), ("next_box", "nextBox", int), ("gap_count", "gapCount", int), ("late", "late", int), ...)
  for attr, key, conv in PLAIN: setattr(st, attr, conv(d.get(key) or 0))
  ```
  online・book・fast・mood・next_scan(max を取る)・late_from などの特別なものだけ手で書く。
- 理由: 属性を足すときに 1 行で済み、書き忘れが起きない。
- 影響・リスク: state.json の形は変えない(鍵の名前は表に同じ値を書く)。`d.get(k) or 0` と `int(d["segSince"])`(無ければ KeyError → 初めからやり直す)の違いを残すかは要判断。テスト: test_live_detect.py の `test_restart_three_times_gives_same_peaks`・`test_run_exits_memory_lock_parent`・`test_late_start_has_no_huge_remeasure`。

##### 14. 数の検査と `(doc or {})` の写し・標準ライブラリで済む小さな処理(優先度: 低・削れる行数の目安: 約 8 行)
- 場所: 「int か float で bool でない」の手書きが `src/home/live.py:352`・`:707`・`:785`・`:853`・`:857`、`src/home/live_detect.py:77`・`:160`・`:475`、`src/home/live_requests.py:27`(_num)。bool を除かない版が `live_detect.py:567-568`(compare の num)・`live_cleanup.py:154`(near)・`live_tx.py:151`・`:201`・`live_failures.py:96`。`(doc or {})` が `live_detect.py:380-382`・`:408-413`・`:611-614` で約 11 回。`live_align_worker.py:54-58`(next_pow2 のループ)
- 今: 同じ意味の検査が 3 通り(有限を見る EW._num・bool だけ除く・何も除かない)に分かれている。
- 案: `EW._num`(有限・bool なし。live_detect・live_tx はもう EW を読める)に寄せる。関数の頭で `doc = doc or {}` を 1 回。next_pow2 は `1 << (n - 1).bit_length()`。live_cleanup の `near = lambda …  # noqa: E731` は def に。
- 理由: 「数」の決まりが 1 つになり、JSON に紛れた true が 1 秒として通る所が無くなる。
- 影響・リスク: bool・NaN・無限大を受けなくなる所がある(compare・tx の start/end。どれも本来来ない値)。テスト: test_live_detect.py の `test_bad_numbers`・`test_compare_after_stream_and_forget`、test_live.py の `test_pad_secs`・`test_adopt_server_side`。

##### 15. live_cleanup の _replaced_why の理由が捨てられている(優先度: 低・削れる行数の目安: 約 3 行)
- 場所: `src/home/live_cleanup.py:105-108`(呼ぶ側)・`:138-160`(_replaced_why)
- 今: 「書き出しの途中」「本番版になっていないマークがある」などの理由の文を作るが、呼ぶ側は真偽しか見ず記録にも出さない(d: 使われない戻り値)。同じ関数の hold の理由は `_say` で記録している(`:101-103`)。
- 案: 呼ぶ側を `if why: self._say(rec, "録画はまだ消しません(%s)" % why); return False` にする(_say は同じ文を繰り返さない)か、使わないなら真偽を返す形にして文を消す。
- 理由: 「なぜ消えないのか」を調べるときに材料が残る。今のままだと文を作る行が読む人を迷わせる。
- 影響・リスク: 前者は入口の記録に 1 行ずつ増える(録画ごとに理由が変わったときだけ)。テスト: test_live_archive.py の録画を消すテスト(記録の行数を数えていれば要確認)。

#### 他のグループとの重複の疑い
- 疑い: `src/home/live_excite_worker.py:164-188`(memory_mb)と `src/editor/ed_state.py:226-249`(rss_mb)はほぼ同じ ctypes の処理。ytt_core(tools など)に 1 つ置ける。
- 疑い: 孫ごと止める kill_tree(`live.py:139`・`live_excite_worker.py:488`)と `src/studio/common.py:404`(hard_kill)・`src/editor/ed_ytcap.py:157`(taskkill)。ytt_core.tools に 1 つ置く候補(指摘 1 の延長)。
- 疑い: pythonw → python.exe の置き換えが `src/home/live_archive.py:294`・`src/home/accuracy.py:244`・`src/home/live_tx.py:324` の 3 か所。
- 疑い: ログを回す処理 `src/home/live_detect.py:274-278` と `src/home/launch.py:145`(rotate)。launch を import すると循環するので、ytt_core.fsio に移す候補。
- 疑い: スタジオの書き出し先を読む `src/home/live.py:222-233`(studio_out_dir)と `src/home/launch.py:955-961`(_extra_dirs)。launch.py は live を import しているので live.studio_out_dir を呼べる(isabs の確かめの有無が違う)。
- 疑い: start・end の秒の検査(bool でない・有限・3 桁に丸める・MAX_MARK_SEC)が `src/home/live.py:697-715`(_adopt_secs)と `src/home/live_export.py:314-335`(check_studio)にある。
- 疑い: 1 つの作業データに 1 つの書き手のロック `live_excite_worker.py:220-235`(take_lock)と `src/editor/ed_evalaudio.py:311`(msvcrt.locking)。
- 疑い: /live/list の録画を REC_RE で絞る処理が `live_export.py:224-230`(rec_list)と `live_excite_worker.py:1311-1312` にある(ワーカーは live_export を読めば rec_list の形を使える。指摘 4 の延長)。


### G3 home-ops(担当: src/home/live_archive.py・live_export.py・intake.py・accuracy.py・backup.py・deliver.py・health.py・cleanup.py・friend_feedback.py、合計 約 5,990 行)

#### 全体の傾向(3〜5 行)
- いちばん大きいのは「子プロセスを動かして、取り消し・時間切れで止める」の写しが 5 通りあること(normalize._run_ffmpeg・live_export._run・live_archive.run_proc・deliver._run_ffmpeg・accuracy._run)。ffmpeg の古い版へのやり直しと「30fps・長さ」の確かめも normalize と同じものを 2 か所で持っている。
- ytt_core にある部品(fsio.read_json_file・write_json・unlink_quiet、clientlog.append_line)を使わずに、JSON の読み書き・一時ファイルの後片付けを手で書いている所が 10 か所ほどある。そのうち 2 か所(deliver の組の一覧・cleanup の trash-roots.json)は書きかけを読まれうる書き方(atomic でない)。
- 「パスがフォルダの中か」「フォルダの大きさ」「空き容量(まだ無いフォルダは上へ)」「低い優先度の creationflags」「pythonw → python.exe」が、ファイルごとに少しずつ違う形で写されている。ytt_core に 1 つずつ置けば、G3 の外(studio・editor)の写しもまとめて減らせる。
- live_archive.Archiver は同じ形の小さな処理(記録の更新・「確かめたばかりか」の判定・スタジオへの GET・例外 → 画面の文)が 3〜4 回ずつ出てくる。関数の長さは基準の中だが、読む量が多い。

#### 指摘

##### 1. 子プロセスを「取り消し・時間切れで止める」実行の写しが 4 つ(優先度: 高・削れる行数の目安: 約 50 行)
- 場所: `src/home/live_archive.py:137-185`(run_proc。読み出し用のスレッド 2 本 + 0.3 秒ごとの poll)・`src/home/deliver.py:191-208`(_run_ffmpeg。communicate(timeout=0.5) の繰り返し + check())・`src/home/accuracy.py:334-359`(Accuracy._run。communicate(timeout=1.0) の繰り返し + closed)。G3 の外の `src/home/live_tx.py:319-340` も似た形(1 回の communicate(timeout=)。取り消しは close() が proc を止める)
- 今: どれも「Popen → 少しずつ待つ → 取り消し(または時間切れ)なら kill → 終了コード・標準出力・エラーの末尾を返す」。止まり方の確かめ方(述語・例外)と、エラーの末尾の切り方だけが違う。
- 案: ytt_core/tools.py に 1 つ置く。`poll` は止めるなら例外を投げる関数にすると、deliver の check()・accuracy の closed・live_archive の cancelled を同じ形で渡せる。
  ```
  def run(cmd, timeout, poll=None, **popen_kw):   # -> (code, out_bytes, err_bytes)
      p = Popen(cmd, stdin=DEVNULL, stdout=PIPE, stderr=PIPE, creationflags=no_window_flags(), **popen_kw)
      end = time.monotonic() + timeout
      while True:
          try: out, err = p.communicate(timeout=0.3); return p.returncode, out, err
          except TimeoutExpired: (poll and poll()) ; time.monotonic() > end and (kill_quiet(p), raise TimeoutExpired)   # poll が投げたら kill してから投げ直す
  ```
  run_proc は「エラーの末尾 3 行・ArchiveError への読み替え」だけの薄い関数として名前を残す(テストが `mock.patch.object(A, "run_proc", …)` で差し替えているため。test_live_archive.py:1068-1099)。
- 理由: 読み出し用のスレッドを自前で持つ run_proc は、communicate(timeout=) の繰り返しで同じことができる(CPython の communicate は時間切れのあと呼び直しても途中の出力を失わない)。止め方の不具合を直す場所が 1 つになる。
- 影響・リスク: 動きは同じにできる。違いが出るのは (a) run_proc は stderr を最後の 20 行だけ持つ → communicate は全部を持つ(yt-dlp は --no-progress、ffmpeg は -v error なので小さい)、(b) accuracy は Windows 以外で `preexec_fn=os.nice(10)` を使う → popen_kw で渡す。関係するテスト: test_live_archive(run_proc の差し替え・本物の ffmpeg の照合)・test_deliver の PreviewTest(本物の ffmpeg)・test_accuracy(偽の道具を子プロセスで動かす)・e2e_live_archive。

##### 2. live_export の ffmpeg の動かし方・古い ffmpeg のやり直し・「30fps と長さ」の確かめが normalize の写し(優先度: 高・削れる行数の目安: 約 45 行)
- 場所: `src/home/live_export.py:1095-1130`(Exporter._run)≒ `src/ytt_core/normalize.py:204-246`(_run_ffmpeg)/ `src/home/live_export.py:993-996`(-fps_mode → -vsync のやり直し)≒ `normalize.py:280-285` / 確かめ `src/home/live_export.py:1009-1016`・`src/home/live_archive.py:1358-1365`(_check_media)≒ `normalize.py:292-297`
- 今: Exporter._run は normalize._run_ffmpeg とほぼ同じ行(Popen・見張りのスレッド・-progress の out_time を読む・`=` を含まない行を末尾 20 行)。違いは進み具合の換算(0.2 + 0.8×)と、無出力の時間切れ(idle)が無いことだけ。行ごとに `re.match(r"^out_time_…")` を書いている(1117 行。normalize は `_OUT_TIME` を 1 回だけコンパイル)。「is_30fps → 長さの差が許容より大きければ失敗」も 3 か所に同じ文で書いている。
- 案: normalize の `_run_ffmpeg` を公開の名前(run_ffmpeg)にして、Exporter._run はそれを呼ぶだけにする(`cancelled=lambda: job.get("cancel") or self._halt.is_set()`・`on_progress=lambda v: job.__setitem__("progress", round(0.2 + 0.8 * v, 3))`・`idle_sec` は今と同じにするなら無限大)。やり直しは `normalize.run_with_legacy(run, enc)` のような 3 行の関数に、確かめは `normalize.verify(path, dur, tol, ffprobe, what="作り直した動画") -> info` にまとめ、live_export(LEN_TOL)と live_archive(LX.LEN_TOL)と normalize(DURATION_TOL)が許容だけ変えて呼ぶ。
- 理由: ffmpeg の扱い(進み具合の読み方・古い版への備え)を直すとき 1 か所で済む。live_archive._check_media(8 行)と live_export の確かめ(8 行)が消える。
- 影響・リスク: 起動できないときの例外が LiveError → NormalizeError になるが、Exporter._process は両方を同じ扱い(error=str(e))にしているので画面の文は同じ。確かめの文の言い回し(「本番版が」「区間と違います」)を 1 つにすると画面の文が少し変わる(テストは文を見ていないことを grep で確かめた)。関係するテスト: test_live の ExportTest・ExportPiecesTest(本物の録画の部品 + ffmpeg)・test_live_archive・src/ytt_core/tests/test_normalize.py・e2e_live_studio。

##### 3. 「パスがフォルダの中か」の判定が 3 通り(優先度: 高・削れる行数の目安: 約 10 行(G3 の中))
- 場所: `src/home/live_archive.py:318-330`(inside: realpath + commonpath・同じなら偽・ネットワークのパスは偽)・`src/home/backup.py:44-50`(_inside: abspath + startswith・同じなら真)・`src/home/accuracy.py:378-381`(realpath + startswith)と `accuracy.py:400-404`(realpath の親が同じか)。G3 の外にも `src/studio/common.py:512-517`・`src/editor/ed_relink.py:44-49`・`src/editor/tx_engines.py:646,958`
- 今: 同じ目的(「許可したフォルダの外へ書かない・読まない」)の検査が、realpath を使うか・同じフォルダを中に数えるか・UNC を断るかで少しずつ違う。
- 案: `ytt_core/fsio.py` に `is_inside(path, root, allow_same=False, real=True)` を 1 つ置き(中身は live_archive.inside。ネットワークのパスは偽)、3 ファイルはそれを呼ぶ。backup は `allow_same=True, real=False` で今と同じ。
- 理由: AGENTS.md の「パスは許可したフォルダの中だけ」を守る部品が、Host/Origin 検査(httpsec)と同じく 1 か所になる。startswith 版は `C:\a` と `C:\ab` を取り違えないよう `+ os.sep` を足しているが、そうした細かい注意を各所で繰り返さずに済む。
- 影響・リスク: 引数で今の違いをそのまま残せば動きは変わらない。backup を realpath に揃えるなら、シンボリックリンク越しの指定の扱いが変わる(要確認)。関係するテスト: test_live_archive.py:369(inside)・test_backup.py:162(作業データの中を断る)・test_accuracy.py:311,372(外のファイルを読まない・消さない)。

##### 4. JSON の読み書きを手で書いている(fsio がある)。2 か所は書きかけを読まれうる(優先度: 中〜高・削れる行数の目安: 約 30 行)
- 場所:
  - 読む: `src/home/accuracy.py:283-292`(_load_state)・`accuracy.py:418-424`(_measure_area。getsize → read → json.loads)・`accuracy.py:190-196`(count_daily)・`src/home/backup.py:206-212`・`src/home/cleanup.py:144-149` と `157-162`(同じ trash-roots.json を 2 回同じ形で読む)
  - 書く: `src/home/backup.py:214-222`(.tmp → os.replace を自前で)・`src/home/cleanup.py:163-166`(open "w" で直接)・`src/home/deliver.py:325-326`(write_group_json。open "w" で直接)
  - 1 行足す: `src/home/friend_feedback.py:35-40`・`107-112`(makedirs + open "a" + json.dumps)
- 今: 大きさの上限つきの読み込み・原子的な書き込みを、それぞれが書いている。deliver の組の一覧は「最後に置く = 友人のアプリは一覧が見えたら組がそろっているとみなす」(320-321 行の説明)なのに、書きかけのファイルが Dropbox に乗りうる。
- 案: 読むのは `fsio.read_json_file(path, 上限)`、書くのは `fsio.write_json(path, obj, indent=None)`(json.dump と同じ区切りなので中身は同じバイト列)、1 行足すのは `clientlog.append_line(path, line, 上限)`。cleanup は `_read_roots()` を 1 つ作って 2 か所から呼ぶ。
- 理由: 短くなるうえ、deliver・cleanup の書き込みが原子的になる(途中で落ちても前の内容が残る)。
- 影響・リスク: (a) read_json_file は NaN / Infinity を断る → count_daily で、そうした値を含む文字起こしの文書があれば数えなくなる(普通は無い)。(b) backup.py は `py -3.10 src/home/backup.py --restore` で単独に動かすため、モジュールの先頭では ytt_core を読んでいない(main で sys.path を足してから読む。396-402 行)→ 使うなら sys.path の追加を先頭へ移すか、関数の中で読む。(c) friend_feedback を append_line にすると、上限を超えたとき .1 へ回る → find_delivery は今のファイルの末尾 4MB しか見ないので、上限を MAX_SCAN 以上にすること(cleanup の _logs は `*.jsonl.1` を古いログとして候補に出す)。関係するテスト: test_accuracy・test_backup・test_cleanup・test_deliver の GroupFilesTest(190-207 行。UTF-8・BOM なし・鍵)・test_friend_feedback。

##### 5. friend_feedback.read_text の到達しない分岐(優先度: 中・削れる行数の目安: 約 1 行(読みやすさ))
- 場所: `src/home/friend_feedback.py:121-125`
- 今: `fsio.read_text_file(...) if hasattr(fsio, "read_text_file") else open(path, "rb").read(limit).decode(...)`。fsio に read_text_file は無い(src/ytt_core/fsio.py を確かめた)ので、前半は通らない。後半は with を使わずに開いている(CPython では式の終わりで閉じるので実害は小さいが ResourceWarning が出る。Windows でこのあと 受付済み へ移す流れなので、閉じたことが読み取れる形がよい)。
- 案: `with open(path, "rb") as f: return f.read(limit + 1)` で上限を確かめる形にするか、parse が dict も受け取るようにして `fsio.read_json_file(path, MAX_BYTES)` を使う(getsize の確かめも要らなくなる)。
- 理由: 無い関数を前提にした分岐は、読む人に「どこかにあるはず」と探させる。
- 影響・リスク: 動きは同じ。関係するテスト: test_intake.py:616-635(.feedback.json を読んで渡す・壊れた JSON)・test_friend_feedback。

##### 6. フォルダの大きさ・空き容量の写し(優先度: 中・削れる行数の目安: 約 30 行)
- 場所: 大きさ `src/home/health.py:34-52`(dir_size)・`src/home/cleanup.py:45-59`(_size)・`src/ytt_core/datadir.py:111-123`(_size)/ 空き容量 `src/home/health.py:88-109`(disk_free)・`src/home/live_export.py:699-718`(Exporter.disk の中。702 行のコメントに「health.py の disk_free と同じ」)
- 今: os.walk でリンクのフォルダを除いて大きさを足す処理が 3 つ(cleanup だけはリンクのファイルも数える・数は返さない)。「まだ無いフォルダはある所まで上へ → disk_usage → 同じドライブは 1 行」も 2 つ(ドライブ名を health は小文字、live_export は大文字にしている)。
- 案: ytt_core に `tree_size(path) -> (bytes, files)`(health.dir_size の形。読めないファイルは飛ばす)と `existing_parent(path)` を置き、cleanup は `tree_size(p)[0]`、datadir._size もそれを呼ぶ。Exporter.disk と disk_free は existing_parent を使い、ドライブ名のそろえ方を 1 つにする。
- 理由: 3 つの「大きさ」で数え方がずれている(リンクのファイル)と、片付けの画面と「調子」の画面で同じフォルダの大きさが違って見える。
- 影響・リスク: datadir._size はコピーの確かめ(元と写しの大きさ・数が同じか)に使うので、読めないファイルを黙って飛ばす形にすると確かめが甘くなる → datadir は例外を上げる形のまま(引数で選ぶか、datadir の側は今のまま残す)。cleanup がリンクのファイルを数えなくなる(数字が少し変わりうる)。関係するテスト: test_health.py:35-41(dir_size)・test_cleanup・test_live.py:1575-1628(空きの見張り)・src/ytt_core/tests/test_ytt_core.py(移行)。

##### 7. 低い優先度の creationflags と「pythonw → python.exe」の写し(優先度: 中・削れる行数の目安: 約 15 行(G3 の中))
- 場所: `src/home/live_export.py:1291-1294`(low_flags)・`src/home/accuracy.py:338-341`・`src/ytt_core/normalize.py:273-275`(G3 の外にも `live_excite_worker.py:161`・`editor/ed_jobs.py:149`・`ed_evalaudio.py:132`・`ed_ytcap.py:148`)/ `src/home/accuracy.py:243-250`(_python)・`src/home/live_archive.py:294-301`(worker_python)・`src/home/live_tx.py:324-326`
- 今: 「窓を出さない + 通常より下の優先度」を 7 か所が少しずつ違う書き方で作っている(accuracy は 0x4000・0x08000000 の数字を直接)。pythonw.exe のときに隣の python.exe を探す処理も 3 か所。
- 案: `ytt_core/tools.py` に `no_window_flags(new_group=False, low=False)` の low を足す(または `low_priority_flags()`)と、`console_python(python=None)` を置く。live_export.low_flags は互換のため 1 行の別名で残す。
- 理由: 優先度の決め方(録画は上・書き出しは下)を変えるとき 1 か所で済む。
- 影響・リスク: 動きは同じ。関係するテスト: test_live_tx.py:536(pythonw)・src/editor/tests/test_evalaudio.py:206(flags)・test_accuracy・test_live。

##### 8. backup のフォルダの歩き方が 2 つ・写し方が 2 つ(優先度: 中・削れる行数の目安: 約 25 行)
- 場所: `src/home/backup.py:60-92`(plan)と `315-335`(_walk_backup)/ `124-150`(copy_one)と `338-350`(_put)
- 今: どちらの歩き方も「scandir を名前順 → リンクは飛ばす → フォルダは積む → ファイルは (相対パス, 大きさ, 更新時刻) を返す」で、違いは「どのフォルダに入るか・どのファイルを返すか」だけ。_put は copy_one から「.prev を残す」を除いたもので、一時ファイルの後片付け(146-150 行・346-350 行)も同じ。
- 案: `_scan(root, enter(rel, name, mode) -> 次の mode か None, keep(name, mode) -> bool)` の 1 つの生成器にし、plan と _walk_backup は enter・keep を渡すだけにする。`copy_one(src, dst, day=None)` にして day が None なら .prev を残さない = _put を消す。後片付けは `fsio.unlink_quiet`(項目 4 の (b) の注意と同じ)。
- 理由: 「リンクをたどらない」などの安全の決まりが 1 か所になる。
- 影響・リスク: os.walk に替えると Windows では 1 ファイルごとに stat が増える(DirEntry の stat はフォルダを読んだときの値を使える)ので、scandir のまま 1 つにする。並び順はテストが見ていない(test_backup.py:234 は「含まれるか」だけ)。関係するテスト: test_backup(15 件)・e2e_backup_ui。

##### 9. live_archive.Archiver の同じ形の繰り返し(優先度: 中・削れる行数の目安: 約 35 行)
- 場所:
  - 録画ごとの記録を「ロック → dict を写して足す → 入れる → 保存」: `src/home/live_archive.py:580-584`・`704-706`・`740-744`・`765-773`
  - 「用意できた と確かめたばかりか」: `524`(READY_CACHE)・`590`・`737-748`・`869-875`。auto_tick と _after_begin は `checked and now - checked < self.interval` を 2 回ずつ書いていて読みにくい
  - スタジオの GET /api/video と形の確かめ: `891-892`・`974-975`・`994-995`・`1003-1005`
  - yt-dlp のやり直しを止める条件が、画面の文の中身で決まっている: `212` 行(`"見つからない" in message or "正しくありません" in message`)
- 案: `_info_put(rc, rec, **kw)`(ロック・足す・保存を 1 つに)・`_fresh(i, ttl)`(ready が True で checkedAt が ttl 以内)・`_studio_video(id) -> dict か None`。auto_tick は `recent = _checked_within(i, interval)` を 1 回求めてから分岐する。_probe_once は結果に `"final": True`(やり直しても無駄)を付け、probe_archive はそれを見る。
- 理由: 文言を直したらやり直しの動きが変わる、という結びつきが無くなる。記録の書き方を変えるとき(保存の頻度など)1 か所で済む。
- 影響・リスク: 動きは同じにできる。関係するテスト: test_live_archive(30 件。probe_archive のやり直し 1068-1099 行)・e2e_live_archive。

##### 10. 例外 → 画面の文 の対応が 3 か所に同じ形(優先度: 中・削れる行数の目安: 約 15 行)
- 場所: `src/home/live_export.py:921-933`(Exporter._process)・`src/home/live_archive.py:1190-1207`(Archiver._process)・`src/home/live_archive.py:825-833`(_after_step)
- 今: どこも「LiveError・NormalizeError → str(e)/ OSError → "書けませんでした: strerror"/ それ以外 → ログ + "内部エラー: 名前"」。live_export は LiveError と NormalizeError の except を中身が同じまま 2 つ書いている(925-928 行)。
- 案: live_export に `error_text(e, log, what) -> 文` を置き、3 か所は `except Exception as e: self._set(job, state="error", error=LX.error_text(e, self.log, "書き出し"), …)` の 1 つにする(Cancelled・Halted・Later はその前で受ける)。少なくとも 925-928 行は `except (LiveError, normalize.NormalizeError)` の 1 つにまとめられる。
- 理由: 失敗の文の決まり(M3 の failure_of と組で読まれる)を 1 か所で決められる。
- 影響・リスク: 動きは同じ。関係するテスト: test_live(失敗の文)・test_live_archive・e2e_live_studio。

##### 11. 同じ動画を何度も ffprobe している(優先度: 中〜低・削れる行数の目安: 約 10 行。子プロセスの数が減る)
- 場所: `src/home/live_archive.py:1308`(_align: 速報版の長さ)・`1371`(_build: 速報版の高さ)・`1400`(_residual: 速報版の長さ。_build の 2 回の試しのたびに)/ `src/home/deliver.py:257`(make_preview: 音の有無)と `298-306`(clip_seconds: 長さ)を `src/home/autorun.py:1991-1992` が同じパックに続けて呼ぶ(pack_video の listdir も 2 回)/ `src/home/intake.py:716`(probe_video: 元の動画)と `755`(normalize.probe: 同じ中身の写し)
- 今: 1 本の本番版への作り直しで、変わらない速報版を最大 4 回 ffprobe する。届けるときも N 本 × 2 回。intake は元と写しで 2 回(しかも probe_video は `find_tool("ffprobe")` で、normalize の `YTT_FFPROBE` を見ない)。
- 案: Archiver._process で `speed_info = normalize.probe(speed)` を 1 回だけ求めて _align・_build・_residual に渡す(_ref_span(dur) も 1 回)。deliver は `clip_infos(dirs)` を 1 回求めて preview と seconds の両方に使う。intake は probe_video を `normalize.probe` の結果から作る(ok = 映像があって音声がある・duration)形にし、その結果を写しの needs_normalize にも使う。
- 理由: ffprobe は 1 回 0.1〜数秒かかる(Dropbox のオンラインのみのファイルではもっと)。同じ値を 1 つの変数で持てば読みやすい。
- 影響・リスク: intake は今 probe= と norm_probe= を別々に差し替えてテストしている(test_intake.py:64-68)ので、引数の形を変えるとテストも直す。intake の確かめが「音声がある」だけ → normalize.probe では映像の有無も分かる(映像の無いファイルを断るなら動きが変わる。要確認)。関係するテスト: test_live_archive(ffmpeg)・test_deliver・test_autorun・test_intake。

##### 12. intake: _record の長い引数と、小さな判定の繰り返し(優先度: 低〜中・削れる行数の目安: 約 30 行)
- 場所: `src/home/intake.py:794-812`(_record。位置引数 9 個 + 名前つき 6 個。呼ぶ所が 14 か所)/ 「知らせ以外に受け付けたものがあるか」`698`・`796`・`820` / 同じ名前があれば uuid を足す `729-730`・`762-763`・`844-846` / ファイル名の禁止文字の置き換え `723`・`821`(`src/home/deliver.py:39-44` の BAD_CHARS・`live_export.py:153-155` の safe_name も同じ正規表現)/ yt-dlp の --print の組み立てとタブ区切りの読み取り `intake.py:149-171` ≒ `live_archive.py:218-243`
- 今: 依頼 1 件の「どこから・誰の・どの流れか」(folder・kind・source・moved・streamer・memo・flow・speakers・rid・tracks・cut)を、各 _handle_* が _record・_process_urls・_accept_video に位置引数で渡し直している(例 557-558・564-566・593 行)。
- 案: 依頼 1 件の文脈を dict(または dataclass)1 つにまとめ、`_record(ctx, title, runs, items)` にする。`_accepted(items)`・`_free_name(dir, name)`・`safe_filename(s)`(ytt_core.fsio か deliver に 1 つ)・`ytdlp_print(vid, fields, timeout)`(live_archive と共用)を置く。
- 理由: 引数の並びの取り違え(位置引数の 10 番目が speakers など)が起きにくくなる。
- 影響・リスク: 名前の足し方(-uuid6・_2・(1))はファイル名として友人・人に見えるので、仕組みだけ 1 つにして書式は引数で今のまま残す。関係するテスト: test_intake(49 件)・e2e_intake_ui。

##### 13. 見回りのスレッドと設定の読み方が 3 クラスで同じ形(優先度: 低・削れる行数の目安: 約 30 行)
- 場所: start・close・run_now・_loop `src/home/intake.py:374-393`・`src/home/accuracy.py:431-457`・`src/home/backup.py:231-254` / _cfg(節を読む・読めなければ DEFAULTS の写し)`intake.py:408-413`・`accuracy.py:300-305`・`backup.py:224-229`
- 今: 「最初に first_wait 待つ → closed になるまで tick → 例外は state=error と log → wake を待つ」と「prefs.get([節])[節] を写す・失敗したら prefs.DEFAULTS」が 3 つずつ。
- 案: home に小さな基底クラス(`Periodic`: start・close・run_now・_loop、子は tick と on_error だけ書く)を置く。設定は prefs.py に `Prefs.section(name)`(失敗したら DEFAULTS の深い写し)を足して 3 つの _cfg を 1 行にする(autorun.py:642・1960・live.py:326 も使える)。
- 理由: 新しい見回り(線 D の部品など)を足すときの写しを防ぐ。
- 影響・リスク: Intake の待ち時間は設定の interval で変わる(392 行)・Accuracy は「今すぐ」で間隔が変わる(457 行)ので、待ち秒数を返すメソッドを子が上書きする形にする。関係するテスト: test_intake・test_accuracy・test_backup・e2e_backup_ui。

##### 14. cleanup の小さな重複(優先度: 低・削れる行数の目安: 約 15 行)
- 場所: 日付のフォルダの古さ `src/home/cleanup.py:291-306`(_intake)と `351-370`(_purge_root)/ 一緒に片付ける名前 `30`(SIDECARS)と `375`(_media_stem の一覧)/ `_sidecars` `76-85`
- 今: 「listdir → フォルダ → 名前の頭 10 文字を YYYY-MM-DD として読む → N 日より古いか」が 2 つ。途中のファイルの末尾の一覧も 2 つあり、片方にだけ `.studio-id`・`_edit.clip.json` がある(足し忘れの元)。_sidecars は schemas.sidecar_candidates と同じ候補(作業用/ と動画の隣)を自前で作っている。
- 案: `_old_day_dirs(root, days) -> [(name, path)]` を 1 つ。末尾の一覧は 1 つの定数から作る(_media_stem は長い末尾から順に見る必要があるので、長さの順に並べ替えて使う)。_sidecars は `[p for s in SIDECARS for p in schemas.sidecar_candidates(video, s) if os.path.isfile(p)]`。
- 理由: 片付けは消す処理なので、決まりが 1 か所にあるほうが確かめやすい。
- 影響・リスク: _media_stem に `_edit.clip.json` を足すと、今 `<名前>_edit` として扱われている途中のファイルが `<名前>` に結びつくように変わる(元の動画があれば候補から外れる)。_sidecars は返す順番が変わる(移したものの記録 manifest の行の順だけ)。test_cleanup は 7 件と少ないので、直すなら先にテストを足す。

##### 15. その他の小さな整理(優先度: 低・削れる行数の目安: 約 30 行)
- `src/home/deliver.py:324`・`330-335`: strftime + 自前の _tz_text は `datetime.datetime.fromtimestamp(when).astimezone().isoformat(timespec="seconds")` の 1 行で同じ文字列になる(test_deliver.py:203 が期待値をまさにこの式で作っている。ytt_core.schemas.iso_now も同じ式)。約 7 行。
- `src/home/deliver.py:76-82`(remove_quiet)は `fsio.unlink_quiet` と同じ(None を渡すときだけ先に `if path:`)。`85-133`: zip_pack → _zip_many と zip_packs → _zip_many の 3 層は、zip_pack が `zip_packs([d], …)` を呼ぶ 2 層にできる。約 10 行。
- `src/home/accuracy.py:255`・`271`・`538-539`・`549-552`: 重い測定の箱(heavy_enabled・_heavy)は常に偽・中身が `return None`。画面とテスト(test_accuracy.py:186・416・538)が見るのは snapshot の heavyEnabled: False だけなので、引数と分岐を消して snapshot は定数 False にできる(入れるときの条件は説明文に残す)。約 6 行。設計の意図として残しているなら残してよい(要確認)。
- `src/home/health.py:113`: parse_version_line の name は使っていない。`366-369`・`385-388`・`392-395`: 「呼んで、失敗したら None」が 3 回 → `_try(fn)`。約 6 行。
- `src/home/live_export.py:373-407`(MarkStore.apply)と `409-435`(upsert): url・title の受け取り・マークの数の上限・保存の失敗を LiveError にする部分(約 10 行)が同じ。`_touch(d, url, title)`・`_save_or_raise(d)` に分けられる。`590-600`: busy と _busy_error が同じ条件で jobs を 2 回なめる(add_studio → add で busy を 2 回呼ぶ)。

#### 他のグループとの重複の疑い
- (疑い)`src/home/live_export.py:102-221`(pick_folder・unique_base・safe_name・trim_units・path_units・is_reserved・WIN_RESERVED・.studio-id の読み書き)は、102 行のコメントのとおり `src/studio/exporter.py` の書き出しの名前の規則の写し。「ツールをまたいで import しない」決まりのためなので、ytt_core に名前の規則を移せば両方から読める(スタジオの担当グループと合わせて判断)。
- (疑い)低い優先度の creationflags: `src/home/live_excite_worker.py:161`・`src/editor/ed_jobs.py:149`・`src/editor/ed_evalaudio.py:132`・`src/editor/ed_ytcap.py:148`(項目 7)。pythonw の扱い: `src/home/live_tx.py:324-326`。
- (疑い)フォルダの中かの判定: `src/studio/common.py:512-517`・`src/editor/ed_relink.py:44-49`・`src/editor/ed_misc.py:231`・`src/editor/tx_engines.py:646,958`(項目 3)。
- (疑い)子プロセスの待ち: `src/home/live_tx.py:319-340`(_run_worker。communicate(timeout=) 1 回)も項目 1 の tools.run で書ける。
- (疑い)`src/home/autorun.py:1991-1992` が batch_preview と clip_seconds を続けて呼び、同じパックの動画を 2 回 ffprobe する(項目 11。直す場所は deliver 側でよい)。
- (疑い)録画の一覧の行 r の時刻の型が呼ぶ側で違う: `src/home/live.py:407-415`(list_recordings。endedAt・lastPdt を epoch に直す)を after_tick が、`src/home/live_cleanup.py:119` は録画元の生の行(ISO の文字列)を after_stream_hold(`live_archive.py:1085`)へ渡す。同じ鍵の名前で型が違うので、live_archive の中の「終わった時刻」の求め方が 3 通り(800 行・863 行・1085 行)になっている。今は呼ぶ側と合っているので不具合ではない(要確認)。
- (疑い)`src/home/prefs.py` に節を読む関数が無いため、autorun.py:642・1960・live.py:326・launch.py:849 も `prefs.get([節])[節]` を手で書いている(項目 13)。


### G4 studio-js(担当: src/studio/review.js・rank.js・queue.js・collab.js・core.js・settings.js、合計 約 5,850 行)

行番号は 2026-10-08 の作業フォルダの状態。settings.js は並行セッションの未コミットの差分(autoDeliver の 6 行)を含む番号、core.js は版の行だけ変わっていて番号は同じ。

#### 全体の傾向
- review.js が 3,680 行で全体の 6 割を超える。配信の選択・プレーヤー・ライブの録画・配信中の候補・書き出し・まとめて実行が 1 つの IIFE にあり、状態(S・LV・PKV・PK・AUTO・PLACE)を共有している。
- 重複の多くは「ファイルをまたいだ同じ処理」: fetch の包み、ライブの録画を始めて ③ で開く流れ、押せない理由の付け方、時刻の文字、探し方。core.js に共通の置き場所(Studio.*)はあるのに、各ファイルが自分で書いている。
- 防御が厚すぎる: `window.UIKit &&` が 53 か所、ほかに予備の経路が数か所ある。一方でガードの無い呼び出しもあるので、守りとしては効いていない。XSS は esc の手書きで丁寧に守られている(漏れは数字 1 か所)。
- **直すときの注意**: test_review.cjs は review.js などを文字列の境目(`between('function X(', '/* 次の見出し')`)で切り出して vm で動かし、さらに「関数の中にこの文字列があるか」も見ている。関数を動かす・名前を変える・共通の部品にくくり出すときは、テストの境目と文脈(渡す関数)も同時に直す必要がある(各指摘の「影響・リスク」に書いた)。

#### 指摘

##### 1. API を呼ぶ 3 つの包みを 1 つの request() にする(優先度: 高・削れる行数の目安: 約 18 行)
- 場所: `src/studio/core.js:28-39`(Studio.api)・`core.js:45-54`(Studio.portalApi)・`core.js:65-84`(Studio.live.api)
- 今: 「fetch → 通信の失敗を Error(code 'network')にする → r.json() を try → !r.ok なら message・code・status・detail を付けた Error」を 3 回書いている。違うのは URL の作り方、合言葉の付け方、時間切れ(live だけ)、通信の失敗の文、e.body の有無、j の初期値(null か {})だけ。
- 案: 違いをオプションにした内部の関数 1 つにまとめる。
  ```
  async function request(url, { method, body, signal, timeout, netMsg, emptyBody } = {}) { … }
  Studio.api = (p, o = {}) => request(Studio.url(p), { ...o, netMsg: NET_STUDIO });
  Studio.portalApi = (p, body) => request(new URL('../' + p, location.href).href, { body, netMsg: NET_HOME });
  Studio.live.api = (rest, o = {}) => request(Studio.live.url(rest), { ...o, netMsg: NET_HOME, emptyBody: true, timeout: o.timeout || (GET ? 10000 : 45000) });
  ```
- 理由: 失敗の形(e.code・e.status・e.detail・e.body)が 1 か所で決まる。今は portalApi だけ e.body が無く、e.code の既定値('http')も api だけにある。呼ぶ側が e.body を読むと portalApi のときだけ undefined になる、という食い違いの元になる。
- 影響・リスク: 違いをオプションで残せば動きは同じ。そろえると portalApi にも e.body が付く(害は無い)。live.api の POST は body が無くても `{}` を送り、begin・stop がそれに頼っているので、この違い(emptyBody)は残す。テスト: e2e_ui・e2e_live_studio・e2e_live が通しで使う。test_review.cjs:880 は `Studio.live = {` から `/* 通知。` までを切り出すが、live.api を差し替えてから呼ぶので、request を live の外に置いても壊れない。

##### 2. ③ の設定の「検める・欄へ書く・欄から読む」を 1 つの表にする(優先度: 高・削れる行数の目安: 約 20 行)
- 場所: `src/studio/review.js:64-89`(sanitizeSettings)・`review.js:1129-1144`(syncSettingsUI)・`review.js:1178-1198`(wireSettings)・`review.js:3430-3432`(rvAutoExp・rvAfter・rvDuck は wire() の側)
- 今: 1 つの設定ごとに「検める(sanitize)」「欄へ書く(sync)」「欄から読んで検め直して保存する(wire)」を別の場所に書いている。wire 側の検め方は sanitize とは別の手書きになっている(例: rvLiveMode は値をそのまま入れる。rvExpTarget・rvAfter・rvDuck は includes を書き直している)。設定を 1 つ足すたびに 3 か所を直すことになる。
- 案: 表 `[欄, 設定の鍵, 'value'|'checked', 変えたあとに呼ぶ関数]` を 1 つ作り、読むときは検め方を sanitizeSettings の 1 か所に任せる。
  ```
  const SET_UI = [['#rvLag','lag'], ['#rvLiveMode','liveMode',,updateLive], ['#rvSort','sortBy',,renderList], ['#rvMute','muted','checked',applyToPlayer], …];
  for (const [sel, k, prop = 'value', after] of SET_UI) $(sel).addEventListener('change', e => {
    S.settings[k] = sanitizeSettings({ ...S.settings, [k]: e.target[prop] })[k]; touchSettings(); if (after) after(); });
  ```
  syncSettingsUI も同じ表を回して書く。
- 理由: 設定を足すときに直すのが 2 か所(sanitize と表)で済み、検め方の食い違いが無くなる。
- 影響・リスク:
  - sanitizeSettings は呼ぶたびに autoTxLegacy()(localStorage を読む)を通る。気になるなら、鍵ごとの検め方を小さな表(`SANITIZE[k]`)に分けて両方から使う。
  - 次の 3 つは「after」で残す: rvVol・rvExpVol の input(動かしている間)、output の数字、rvExpLoud のあとの syncSettingsUI(rvExpVol を押せなくする)。
  - テスト: e2e_ui が見ているのは rvMute(1103-1128)と一瞬の前後(685)だけ。rvExpLoud・rvHeight・rvPrecision・rvLag・rvVol には画面のテストが無い。直すなら e2e_ui に「欄を変える → /api/settings の review に入る」を 1 本足す。test_review.cjs:704 は `async function loadSettings(` から `function syncSettingsUI(` までを切り出すので、この 2 つの名前は残す。

##### 3. 「録画を始めて ③ で開く」と「③ を開く(無ければ知らせ)」を core に 1 つずつ(優先度: 高・削れる行数の目安: 約 12 行)
- 場所: `src/studio/queue.js:226-232`(openBegun)・`queue.js:231`・`queue.js:265`・`queue.js:377`、`src/studio/rank.js:631-636`・`rank.js:649`、`src/studio/review.js:700-709`(openFromInput)
- 今: 3 つのファイルが同じ流れを書いている(Studio.live.begin の結果 → 「この配信はもう録画しています…/配信の録画を始めました…」の知らせ → S.review.open(id)。S.review が無ければ「確認画面がまだ読み込まれていません」)。同じ文の知らせが 3 つ、open が無いときの分岐が 5 つある。
- 案: core.js に 2 つ置き、3 つのファイルはそれを呼ぶ。
  - `Studio.openReview(id)`: 無いときの知らせもここだけに置く。
  - `Studio.live.openBegun(b, ms)`: 知らせを出して openReview を呼ぶ。
- 理由: 文を直すときの直し漏れが無くなる。review.js は読み込みの時点(index.html:44-48 の順。onReady より前)で Studio.review を作る。なので「無ければ知らせ」は review.js が読み込みで落ちたときにしか通らず、1 か所にあれば十分。
- 影響・リスク:
  - 知らせの秒数が 5000 と 6000 で違う(review の 706 だけ 5000)。そろえると小さな見た目の違いが出る。
  - review の openFromInput は S.review.open ではなく loadVideo を直接呼ぶ(③ にいるので Studio.go が要らない)。そこは知らせだけを共有する。
  - テスト: test_review.cjs:895-898 は、rank の lvBegin に `S.live.begin(url, { channel: v.channel || '' })` と `S.live.register(` の文字列があることを確かめる。この 2 つは残す。e2e_live_studio(qAdd から録画)と e2e_ui も使う。

##### 4. 押せない理由(disabled・title・data-ui-why)と「変わったときだけ書く」を共通の部品にする(優先度: 高・削れる行数の目安: 約 25 行)
- 場所:
  - rank.js: `src/studio/rank.js:248-255`(syncGo)・`rank.js:436`(setText)
  - settings.js: `src/studio/settings.js:178-182`(syncLivePeaks)・`settings.js:170-174`(古い入口のとき、スイッチと説明を隠す処理が 2 つ並んでいる)
  - queue.js: `src/studio/queue.js:134-141`(syncAdd)・`queue.js:326-327`
  - review.js: `src/studio/review.js:1276-1279`(renderLiveCount)・`review.js:1336`(liveSet)・`review.js:1991-1993`(setTxt・setHidden・setAttr)・`review.js:2013-2017`(peakBtn)・`review.js:2490-2499`(renderExpRun)・`review.js:2501-2518`(renderExpMore)・`review.js:3071-3072`(rvBulkAdopt)
- 今:
  - 「disabled = !!why; title = why か使えるときの説明; data-ui-why を付け外し」を 8 か所以上で手書きしている。data-ui-why を付けるのはそのうち半分だけ(renderExpRun・renderExpMore・bulkAdopt・queue は付けない)。
  - renderExpMore は 3 つのボタンごとに 5 段の三項演算子で理由を選び、disabled の条件は別の式でもう一度書いている。条件と理由の対応がずれやすい。
  - 「変わったときだけ書く」部品も 3 つある(rank の setText、review の liveSet と setTxt)。
- 案: core.js に `Studio.dom = { text, hidden, attr, why(btn, why, okTitle) }` を置き、理由は「最初に当てはまるもの」で選ぶ。
  ```
  const firstWhy = rules => (rules.find(([on]) => on) || [, ''])[1];
  const why = firstWhy([[live, 'ライブの録画を…'], [running, '書き出しの実行中は…'], [S.live, '配信中は…'], [noTool, 'ffmpeg が…'], [!n, '採用にした…']]);
  Studio.dom.why(b, why, '採用にしたマークがある全部の配信を…');
  ```
- 理由: disabled の条件と理由の文が 1 つの表になる。押せないのに理由が無い、理由と条件がずれる、ということが起きなくなる(docs/spec/ui-review-criteria.md の A-34)。
- 影響・リスク:
  - data-ui-why が、今まで付いていなかったボタンにも付く。見た目は同じだが、ui_audit の A-34 の数え方が変わるかもしれないので `py -3.10 dev/ui_audit.py all --demo` を流す。
  - e2e_ui.py:527 は rvExpAll の title の文を見るので、文は変えない。
  - test_review.cjs は liveSet の名前を使っている(切り出しの文脈に渡す)。名前を変えるならテストも直す。

##### 5. マークを作る 3 関数の前置き・「書き出し済みを採用に戻す」・遅れ補正の読み方をまとめる(優先度: 中・削れる行数の目安: 約 12 行)
- 場所:
  - マークを作る 3 関数: `src/studio/review.js:2238-2248`(quickMark)・`review.js:2253-2264`(momentMark)・`review.js:2289-2300`(addClip)
  - 書き出し済みを採用に戻す: `review.js:467-468`・`review.js:2311`・`review.js:3445`(似た形が `review.js:2333`)
  - 遅れ補正を読む所: `review.js:2241`・`review.js:2256`・`review.js:2278`
- 今:
  - 3 つの「マークを作る」関数が同じ前置きを書いている(配信が開いているか、500 件の上限、checkRange、エラーなら知らせ)。
  - `status = 'adopted'; file = ''; path = ''; archived = false` が 4 か所にある。
  - 反応の遅れ補正を読む所が 3 つあり、読み方がそれぞれ違う(下)。欄と設定の二重持ちになっている。
    - quickMark: S.settings.lag
    - momentMark: `Number(S.settings.lag) || 0`
    - markIn: 画面の欄 `$('#rvLag').value`
  - 2333 は `if (st !== 'exported') c.file = ''; c.path = ''; …` で波かっこが無く、読み違えやすい。動きとしては問題ない(ここで exported を選ぶ道は無い)。
- 案: 次の 3 つの小さな関数にまとめる。
  ```
  function tryMark(start, end){ if (!S.cur) …; if (marks().length >= MAX_MARKS) …; const r = checkRange(start, end); if (typeof r === 'string'){ toast(r); return null; } return newMark(r[0], r[1], markLive()); }
  const unexport = (m, st = 'adopted') => Object.assign(m, { status: st, file: '', path: '', archived: false });
  const lagNow = () => Math.max(0, S.now - S.settings.lag);
  ```
- 理由: 上限・範囲の規則を変えるときに直すのが 1 か所になる。markIn だけが欄を読むので、欄がまだ無い・別の値が入っている、というときに食い違う元になる。sanitizeSettings が lag を [0,2,3,5] に限っているので、`Number(...) || 0` も要らない。
- 影響・リスク:
  - addClip は「IN と OUT の両方」の確認を上限の確認より先にしている(知らせが出る順)。この順は保つ。
  - markIn の遅れが欄ではなく設定の値になる(欄は設定から書くので、ふつうは同じ値)。
  - テスト: test_review.cjs:519 は、pushMark に `startLiveExport(new Set([m.id]), { auto: true })` があるかを見る(pushMark は触らない)。e2e_ui に今をマーク・一瞬(685)の確認がある。applyServer は test_review.cjs:679 で切り出して動かすので、unexport を使うなら文脈に渡す。

##### 6. 書き出しを始める 3 関数の POST と「書き出し中か」の判定を 1 つに(優先度: 中・削れる行数の目安: 約 12 行)
- 場所:
  - 書き出しを始める 3 関数: `src/studio/review.js:2557-2572`(startJoin)・`review.js:2690-2707`(startExport)・`review.js:2709-2743`(startExportAll)
  - 書き出し中かの判定: `review.js:2537`・`review.js:2558`・`review.js:2692`・`review.js:2710-2711`・`review.js:3105`(exportRunning)
  - 「配信中は書き出せません」: `review.js:2561`・`review.js:2695`・`review.js:2712`
- 今: startExport と startJoin はほぼ同じ 16 行になっている(下の流れ)。「書き出し中か」は 3105 に exportRunning() があるのに使われておらず、2537・2558・2692 は S.starting を足した式を毎回書いている。
  1. 押せるかを確かめる
  2. S.starting を立てる
  3. flushSave
  4. 配信が切り替わっていないかを確かめる
  5. POST /api/export
  6. S.job と rememberJob
  7. renderJob と pollJob
  8. 失敗の知らせ → finally
- 案:
  - `const exportBusy = () => S.starting || exportRunning();` を置く。
  - `async function postExport(v, markIds, extra, failMsg)` に POST から pollJob までをまとめ、startExport と startJoin はその前の確認だけにする。
- 理由: 書き出しを始める手順(保存 → 切り替わりの確認 → 覚える)を直すとき、1 か所で済む。
- 影響・リスク:
  - test_review.cjs の harness(55-59)は `async function startExport(` から `/* ---------- 描画 ---------- */` までを切り出して動かす。なので postExport はこの範囲(startExport の後ろ)に置く。startJoin は範囲の外なので、startExport の後ろへ動かすか、harness に足す。
  - test_review.cjs:514-515 は「startExport の中で `S.cur.kind === 'live'` が `S.starting` より前にある」を文字で確かめる。exportBusy に置き換えるとこの確認が失敗するので、テストの文字も直す。
  - e2e_ui は rvJoinRun・rvExpAll を押す。

##### 7. 状態の言葉と色の表を 1 つに(優先度: 中・削れる行数の目安: 約 6 行)
- 場所: `src/studio/queue.js:9`(STATUS)、`src/studio/review.js:2396`(EXP_LABEL)・`review.js:2575`・`review.js:2595`(色を選ぶ三項演算子が 2 回)
- 今: コメントには「状態の言葉は 3 画面で同じ(見直し S7)」とあるのに、言葉と色の表を queue と review で別々に持っている。review は色を `done ? 'ok' : error ? 'err' : …` の 4 段の三項演算子で 2 回書く。中身の違いは鍵が waiting か queued かだけ。
- 案: core.js に `Studio.STATUS = { waiting: ['待ち','wait'], queued: ['待ち','wait'], running: ['実行中','run'], done: ['済み','ok'], error: ['失敗','err'], cancelled: ['中止','warn'], skipped: ['飛ばした','wait'] }` を置き、両方から `const [label, cls] = Studio.STATUS[st] || [st, 'wait']` で引く。
- 理由: 「言葉をそろえる」という約束がコードで守られる。
- 影響・リスク: 動きは同じ。review の AUTO_STATE(3556)は cancelled の色が 'wait'(こちらは 'warn')で、言葉は UIKit.autorun.runLabel が出すので、まとめには入れない。テスト: 色の専用の確認は無い(e2e_ui の通しで見えるだけ)。

##### 8. 時刻・相対の日時の文字の作り方を 1 つに(優先度: 中・削れる行数の目安: 約 8 行)
- 場所:
  - 時刻: `src/studio/review.js:2884-2887`(tickLabel)、`src/studio/collab.js:64`・`collab.js:151`(`fmt(v.duration).replace(/\.\d$/, '')`)、`src/studio/queue.js:12`(mmss)・`queue.js:288`・`queue.js:320`、`src/studio/rank.js:11`(fmtDur = UIKit.fmt.dur)
  - 相対の日時: `collab.js:63`・`collab.js:151`・`queue.js:276`・`review.js:565`
- 今: 「時:分:秒(小数なし)」の作り方が 4 通りある。
  - 切り捨て(tickLabel)
  - 0.1 秒に丸めてから小数を消す(collab)
  - m:ss だけ(queue の mmss)
  - UIKit.fmt.dur の四捨五入(rank)
  ほかに、相対の日時に日付の title を付ける span も 4 か所で手書きしている。
- 案: 長さ・経過は UIKit.fmt.dur に一本化する(ui-kit の 1 か所。src/ui-kit/README.md の v3)。core.js に `Studio.agoHtml(ms, prefix = '')`(`<span title="…日付">…前</span>` を返す)を置く。
- 理由: 時刻の見せ方が画面ごとにずれなくなる。
- 影響・リスク:
  - UIKit.fmt.dur は四捨五入、tickLabel は切り捨て。タイムラインの目盛り(整数秒)は同じだが、小数の時刻(候補の時刻・山の札・マウスの位置)は 0.5 秒以上のとき 1 秒先に見える。気になるなら tickLabel だけ残す。
  - mmss(チャット取得の経過)は、1 時間を超えると「60:00」が「1:00:00」になる(良くなる方)。
  - test_review.cjs の候補のテスト(948-1053)は tickLabel を差し替えて渡すので、名前を変えるならテストも直す。

##### 9. 配信の名前・配信者・探し方・まとめ方・YouTube の URL を共通の部品に(優先度: 中・削れる行数の目安: 約 15 行)
- 場所:
  - collab.js: `src/studio/collab.js:57-58`(vlabel・who)・`collab.js:77-84`(matchV)・`collab.js:86-90`(groupsOf)
  - review.js: `src/studio/review.js:539-541`(vLabel・vWho)・`review.js:545-554`(pickMatch)・`review.js:581-583`(配信者ごと)
  - rank.js: `src/studio/rank.js:314`(matchQ)
  - queue.js: `src/studio/queue.js:275`(who)
  - YouTube の ID と URL:
    - rank.js: `rank.js:14`・`rank.js:342`・`rank.js:438-441`・`rank.js:544`・`rank.js:624`
    - queue.js: `queue.js:117`・`queue.js:122`
    - review.js: `review.js:27`・`review.js:765`・`review.js:1326-1327`・`review.js:2825`・`review.js:3367`
- 今:
  - 次の 2 つを collab と review(rank も)で同じ形に書いている。
    - 探し方: 探す文字を空白で分け、全部の語が題名・配信者・ID のどれかに含まれるか。
    - まとめ方: 配信者ごとに Map にまとめる。
  - 配信の名前(title か fileName か id)と配信者の名前(動画ファイル / チャンネル / 不明)も 2〜3 か所にある(ライブの録画を区別するのは review だけ)。
  - `/^[\w-]{11}$/` と `'https://www.youtube.com/watch?v=' + …` が 3 つのファイルで 12 か所に散っている。
- 案: core.js に次を置く。
  - `Studio.matchWords(q, ...fields)`
  - `Studio.groupBy(list, keyFn)`
  - `Studio.vLabel(v)`
  - `Studio.vWho(v)`(review の版 = ライブの録画を区別する)
  - `Studio.ytId(s)`
  - `Studio.watchUrl(id, t)`
- 理由: 一覧が 3 つあるので、探し方の規則(大文字小文字・全角空白など)や URL の形を変えるときに 1 か所で済む。
- 影響・リスク: collab の who はライブの録画を「配信者不明」と出す(review は「ライブの録画」)。review の版にそろえると、コラボの一覧の見出しが変わる(良くなる方。要確認)。テスト: e2e_ui の clQ・rvPickQ。

##### 10. 厚すぎる防御と、互換のための小さな包みを外す(優先度: 中・削れる行数の目安: 約 20 行。ほかに 1 行ずつ短くなる所が多い)
- 場所:
  - `window.UIKit &&` の数: review.js 33・core.js 9・rank.js 7・settings.js 3・queue.js 1
  - 予備の経路(review.js):
    - `src/studio/review.js:3504`: Studio.isTyping が無いときの手書きの判定
    - `review.js:3498`・`review.js:3502`: Studio.overlayOpen・inMenu があるかの確認
    - `review.js:3672`: UIKit.life が無いときの visibilitychange
    - `review.js:3557`・`review.js:3613-3614`: AUTO_STEP と、UIKit.autorun が無いときの言葉
    - `review.js:325-329`: mountSettings
  - 予備の経路(settings.js): `src/studio/settings.js:291-292`(body に足す保険)
  - 小さな包み:
    - `review.js:591-593`(renderVideoSelect): renderPickList を呼ぶだけ(「以前の <select> の名前のまま」)
    - `src/studio/collab.js:11` と `review.js:2319`(armDelete): 中身は同じ 1 行
- 今: ui-kit.js は index.html:9 で core.js より先に同期で読むので、画面では UIKit は必ずある。しかも review.js:2370(UIKit.toast)・review.js:3058(UIKit.timebox.attachAll)・collab.js:11・111・199 はガード無しで呼んでおり、UIKit が無ければどのみち壊れる。つまりガードは守りになっていない。3672 の visibilitychange の予備は、AGENTS.md の「visibilitychange を直接使わない」と食い違う。
- 案: 画面のコード(切り出してテストする関数の外)から、ガードと予備の経路を外す。UIKit は `const K = window.UIKit;` で 1 回受ける。renderVideoSelect と armDelete の包みも外して直接呼ぶ。
- 理由: 「無いときの動き」は実際には試されない分岐で、読む量だけを増やしている(約 50 か所の条件)。
- 影響・リスク:
  - test_review.cjs は関数を文字列で切り出し、UIKit が無い文脈や一部だけの文脈で動かす(例: 776 は window.UIKit に win だけ)。
  - 切り出される関数(openEditor・loadVideo・pollJob・startExportAll など)の中のガードは、テストの文脈に空の UIKit と関数を足してから外す。`typeof X === 'function'`(review.js:663-673・2682・2762。テストの切り出しのためだけの確認)も同じ。
  - test_review.cjs:50 は renderVideoSelect を、252 は armDelete の中身を見るので、名前を変えるならテストも直す。

##### 11. script を読み込む 2 関数を 1 つに(優先度: 中・削れる行数の目安: 約 10 行)
- 場所: `src/studio/review.js:741-758`(loadYTApi)・`review.js:865-877`(loadHls)
- 今: 同じ手順を 2 回書いている: 1 回だけ読む Promise を覚える → 時間切れを決める → 失敗したら前の script を消して覚えを捨てる。違うのは準備の合図だけ(YouTube は onYouTubeIframeAPIReady、hls.js は onload + window.Hls)。
- 案: `function loadScript(key, src, { timeout, ready })` 1 つにする。YouTube は ready に「onYouTubeIframeAPIReady を待つ Promise」を渡す。
- 理由: 読み込みのやり直しの決まり(古い script を消す・覚えを捨てる)が 1 か所になる。
- 影響・リスク: 時間切れ(YouTube 12 秒・hls 15 秒)はそのまま渡す。loadYTApi は時間切れのあとも script を残し、遅れて届いた window.YT を使う(742 のコメント)。loadHls は消す。この違いは残す。テスト: e2e_ui の check_player_unavailable・check_yt_not_ready(YouTube 側)、e2e_live_studio(hls 側)。

##### 12. クリックの振り分けを表にして、同じ入れ物への listener の重複をなくす(優先度: 低・削れる行数の目安: 約 10 行)
- 場所:
  - collab.js: `src/studio/collab.js:272-305`(onGroupClick の if/else が 6 段)
  - rank.js:
    - `src/studio/rank.js:93-133`(regClick)
    - `rank.js:722-737`(#results の click。closest の連鎖が 8 段)
    - `rank.js:716` と `rank.js:739`(#results の change を 2 回登録)
  - review.js:
    - `src/studio/review.js:3198`・`review.js:3227`・`review.js:3237`(#rvList の click を 3 回登録)
    - `review.js:3464`・`review.js:3465`・`review.js:3469`・`review.js:3476`(#rvExpList の click を 3 回 + onCopy)
- 今: 1 つの入れ物に click を何回も登録し、それぞれが closest で自分の分かを確かめている。振り分けは if/else の連鎖になっている。
- 案: 入れ物ごとに listener を 1 つにし、`{ act: fn }` の表で振り分ける。rank の結果欄なら `[['[data-rkopen]', el => S.openSettings(el.dataset.rkopen)], ['[data-rkretry]', startSearch], …]` を順に見る。
- 理由: どのボタンが何をするかが表で一目で分かる。同じ要素に listener が 2 つある(どちらが先かで動きが変わる)、ということも無くなる。
- 影響・リスク: review の #rvList の 3 つの click は順に意味がある(「行を選ぶ」が最後で、ボタンの上では選ばない)ので、表にしても順を保つ。stopPropagation(review 3460)の扱いに注意。テスト: e2e_ui の通し。

##### 13. ① の期間・保存する条件・選んだ事務所の正を 1 つに(優先度: 低・削れる行数の目安: 約 8 行)
- 場所: `src/studio/rank.js:687`・`rank.js:689`・`rank.js:690`・`rank.js:731`(「n 日前〜今日」の期間を 4 回作る)、`rank.js:214`(saveCond のキーの手書き)、`rank.js:212`・`rank.js:236`(事務所の選択を画面のチェックから読む)
- 今:
  - `const e = new Date(), s = new Date(); s.setDate(s.getDate() - (n - 1)); setRange(s, e); saveCond();` が 4 回ある。
  - saveCond は condBody() のうち agencies 以外の 10 個の鍵を書き並べている。
  - condBody と goState は選んだ事務所を `.agc:checked` から読む。同じ値は R.agPick と agChecked(rank.js:461 の lvAgencies)にもあり、画面と変数の二重持ちになっている。
- 案: 次の 3 つにする。
  - 期間: `const lastDays = n => { const s = new Date(); s.setDate(s.getDate() - (n - 1)); setRange(s, new Date()); };`
  - 保存: `const { agencies, ...c } = condBody(); lsSet('cond', c);`
  - 選んだ事務所: lvAgencies() の 1 つにする(名前は pickedAgencies に)。
- 理由: 期間の決め方・保存する鍵・事務所の選び方の正が 1 か所になる。
- 影響・リスク: saveCond で保存する鍵の順だけ変わる(読むときは鍵の名前で読むので同じ)。チェックは agChecked から描き、変えたら R.agPick を直すので、画面から読むのをやめても同じ値になるはず(要確認)。テスト: e2e_ui の data-days・data-yday、test_review.cjs:331-353(agChecked・loadAgPick)。

##### 14. ② の解析の設定の 3 つの並びを 1 つの表にする。古い保存の引き継ぎは消せるか確認(優先度: 低・削れる行数の目安: 約 12 行)
- 場所: `src/studio/queue.js:10`(OPT_IDS)・`queue.js:74-78`(settings())・`queue.js:82-83`(FROM_SETTINGS)・`queue.js:85-98`、古い保存の引き継ぎ: `queue.js:7`・`queue.js:111-112`、`src/studio/rank.js:190-195`(v0.7.0 の 'ags')
- 今: 解析の設定の「画面の欄の id ↔ 送る名前 ↔ 既定値」を 3 つの並びで持っている(pre だけ別の計算)。欄を 1 つ足すと 3 か所を直す。
- 案:
  - `const FIELDS = [['useAudio','useAudio','bool'], ['count','count','num',8], …, ['pre','preRatio','num',65, v => v / 100, v => Math.round(v * 100)]]` を 1 つ作り、settings()・applySettings・OPT_IDS をそこから作る。
  - 古い保存の引き継ぎは消す(要確認: ほかの PC で使っていないか)。段階7-1 の localStorage の opts と v0.7.0 の ags は 10-03 の入れ直しより前のものなので、この PC では起きない。
  - スタジオ 0.22.0(10-07)の autoTxLegacy(review.js:3564)はまだ新しいので残す。
- 理由: 欄と送る名前の対応が 1 つになる。
- 影響・リスク: 解析の設定の画面にはテストが無い(e2e_analyze が確かめるのはサーバーの解析だけ)。直すなら e2e_ui に「欄を変える → /api/settings の analyze」を足す。rank の 'ags' は test_review.cjs:343-349 が確かめているので、消すならテストも直す。

##### 15. esc の手書きを「既定で esc する」テンプレートに(優先度: 低・削れる行数の目安: ほぼ 0 行。1 行ずつ短くなる)
- 場所: esc( の手書きが 146 か所(review 68・rank 31・collab 28・queue 17)、innerHTML が 67 か所。漏れは `src/studio/review.js:2577` の `${c.count}`(つないだ本数。サーバーの値をそのまま入れている)
- 今: 文字列の連結やテンプレート文字列で HTML を組み、外から来る値に 1 つずつ esc を付けている。数字(fmt・toFixed・Number)には esc しない約束で書かれている。調べた範囲では漏れは c.count だけで、サーバーが作る数なので実害は無い。
- 案: core.js に `Studio.html` という tagged template を 1 つ置き、`${}` の値を既定で esc する(HTML をそのまま入れたいときだけ `Studio.raw(…)` で包む)。新しく書く所と描き直す所から順に使う。
- 理由: esc の付け忘れが仕組みの上で起きなくなる。CSP(script-src 'self')があるのでスクリプトは動かない。ただ、タグ・リンク・フォームの差し込み(見た目を壊す・偽のリンク)は CSP では防げない。全ツールが同じオリジンにあるので、AGENTS.md の【高】のリスクに当たる。
- 影響・リスク: 書き換えの量が多いので、一度に全部は直さない。直した所ごとに e2e_ui の check_untrusted_text(XSS_TITLE。823 行あたり)を流す。

#### 他のグループとの重複の疑い
- **合言葉付きの fetch の包み(疑い)**: 指摘 1 の 3 つと同じ形のものが、ほかのグループにもある。ui-kit に 1 つ(例: UIKit.http)置けば、全部がそれを使える疑いがある。
  - src/editor/app-core.js:88・99
  - src/editor/app-list.js:130(Studio.portalApi と同じ形)
  - src/editor/app-tools.js:600
  - src/home/portal.js:63
- **クリップボードへのコピー(疑い)**: 次の 3 つが、それぞれ自分で書いている。ui-kit の 1 か所(例: UIKit.copy)にできる疑いがある。
  - review.js:2457-2463 の copyText(execCommand の予備つき)
  - src/editor/app-core.js:123 の copyPath
  - src/home/portal.js:2176
- **長さの文字(疑い)**: UIKit.fmt.dur があるのに、スタジオの中だけで 3 通りの別の作り方がある(指摘 8)。編集・ホームにも自分で作った「時:分:秒」があるかは、それぞれのグループで確かめる。
- **YouTube の動画 ID の正規表現(疑い)**: src/editor/app-learn.js:116 にも `/^[\w-]{11}$/` がある。指摘 9 の Studio.ytId を作るなら、ui-kit に置く方がよい可能性がある。


### G5 studio-py(担当: src/studio/store.py・exporter.py・analyze.py・rank.py・serve.py・common.py・batch.py・handoff.py・txlink.py、合計 約 5,900 行(実測 5,914 行))

#### 全体の傾向(3〜5 行)
- 設計の芯(store の「作る → 保存 → 成功したら反映」、exporter の書きかけ → promote、SLOTS、httpsec、txindex を呼ぶだけの txlink)はそろっている。URL の振り分けも、もう表(routes・POST_ROUTES・PUT_ROUTES)になっている。大きく作り直す必要はない。
- 短くできる所の多くは、同じ定型を 2〜8 か所に手で書いていること。例: 子プロセスの読み取りループ(run_capture と _pump)、ffmpeg・yt-dlp のコマンドの頭と watch の URL、道具が無いときの ApiError、mtime の古い順に消すキャッシュの掃除、数値の検査。
- ytt_core の部品(runtime.ping・tools.no_window_flags・fsio.unlink_quiet・schemas.num・normalize._OUT_TIME)を使わず、同じ処理を書いている所が 6 か所ほどある。dev/lint.py の dup-helper は関数名(_unlink など)しか見ないので、lint では見つからない。
- 速さに効くのは 1 つだけ。書き出しで同じファイルに `ffmpeg -i` を何度もかけている(1 本あたり約 11 回。うち 5〜6 回は前の結果と同じ)。
- txlink.py(35 行)は txindex を呼ぶだけで、指摘は無い。handoff.py も薄いが、テストのためだけの包みが残っている(#14)。

#### 指摘

##### 1. 書き出しの `_pump` が `common.run_capture` とほぼ同じ処理(優先度: 高・削れる行数の目安: 約 35 行)
- 場所: `src/studio/exporter.py:483-544`(_pump)、`src/studio/common.py:435-492`(run_capture)、`src/studio/exporter.py:512`
- 今: どちらも同じ流れを別々に持っている。spawn → job[slot] に入れる → 0.5 秒ごとの見張りスレッド(中止・出力が無いときに terminate)→ 1 行ずつ読む → wait(30) → hard_kill → wait(5) → finally で done.set・slot を None・hard_kill・forget。違うのは 3 点だけ: stderr を stdout に混ぜるか、投げる例外(Cancelled・ApiError("timeout") か ExportError か)、全体の timeout があるか。512 行の `re.match(r"^out_time_(?:us|ms)=(\d+)$", line) or None` は `ytt_core/normalize.py:41` の `_OUT_TIME` と同じ式で、`or None` も要らない。
- 案: run_capture に `merge_stderr=False` を足す(True なら stderr=STDOUT にして、drain のスレッドは作らない)。_pump は進み具合を読むことと tail を集めることだけにする。
  ```
  def _pump(job, cmd, it, dur, span=(0.0, 1.0)):
      tail = []; on = _progress_reader(it, dur, span, tail)          # out_time(_norm._OUT_TIME)/ time= / tail[-30:]
      try: rc, _ = common.run_capture(job, cmd, on, idle_timeout=EXPORT_IDLE, what="書き出し", merge_stderr=True)
      except common.Cancelled: raise ExportError("中止しました")
      except ApiError as e: raise ExportError(e.message)                # 出力が無いまま時間切れ(文は同じ idle_message)
      if rc != 0: raise ExportError(reason(tail) or "終了コード %s" % rc)
      return tail
  ```
- 理由: 子プロセスの止め方(Windows の taskkill /T・孫の扱い)を直すとき、2 か所を同じに保たなくてよくなる。終了の流れ(shutdown_jobs)の不具合はこの辺りで起きやすい。
- 影響・リスク: 動きは同じにできる(slot の名前は両方 "proc")。違うのは _pump の最後の `proc.stdout.close()`(パイプを明示的に閉じる)だけなので、これは run_capture 側にも入れる。関係するテスト: `test_exporter.py`(225-230・677-682 で _pump を spy で包んでいる = 名前と引数は残す)、`test_robustness.py:441-466`(終了の流れで _pump の子と孫が止まる)、`test_api.py` の書き出し。

##### 2. 書き出しで同じファイルに `ffmpeg -i`(common.media_info)を何度もかける(優先度: 高(速さ)・削れる行数の目安: 約 5〜10 行。行数より速さが目的)
- 場所: `exporter.py:582`(run_ffmpeg。元のファイル。クリップごとと編集用素材ごと)・`120`(verify_output)・`745`(_reencode_audio の前)・`763`(measure_loudness)・`906`(export_edit_media)・`948`・`954`(write_manifests)・`672`(_ytdlp_sections)・`865`(concat_pieces)
- 今: file の 1 本(音量 75%・ラウドネスなし・編集用素材あり)で `ffmpeg -i` を約 11 回動かす。内訳は、元のファイル 2 回、切り抜き本体 4 回(verify → 音量の前 → 音量のあとの verify → .clip.json)、編集用素材 5 回。50 本書き出すと、元のファイルを 100 回読む。11 回のうち 5〜6 回は、直前の verify_output と同じファイル・同じ中身。
- 案(どちらか):
  - (A) `common.media_info` に、(path, st_mtime_ns, st_size) を鍵にした小さな辞書のキャッシュ(上限 64 件くらい)を付ける。呼び出し側は変えない。
  - (B) verify_output が測った長さを返して it["outLen"] に入れ、_reencode_audio と write_manifests はそれを使う。元のファイルの結果は spec["srcInfo"] に 1 回だけ入れる(pspec・wspec は `dict(spec, …)` の写しなので一緒に渡る)。
- 理由: 長い配信の mkv だと 1 回 0.1〜0.5 秒(ネットワークドライブならもっと)。50 本なら数十秒になる。
- 影響・リスク: (A) は、置き換え(replace_file)で mtime と大きさが変わることが前提。FAT32 のように mtime が粗いドライブで「同じ大きさのまま 2 秒以内に書き直す」と、古い値を返す恐れがある。書き出しは必ず一時の名前に書いてから置き換えるので実害は小さいが、気になるなら (B) にする。関係するテスト: `test_exporter.py`(長さの確認 252・663・764)、`test_api.py:930`、`e2e_ui.py`。

##### 3. ffmpeg・yt-dlp のコマンドの頭と watch の URL を各所で手書き(優先度: 中・削れる行数の目安: 約 10 行)
- 場所:
  - ffmpeg の頭 `[ff, "-hide_banner", "-nostdin", ...]` = `common.py:293`、`analyze.py:837`、`exporter.py:591・679・713・746・764・869`
  - `"-progress", "pipe:1", "-nostats"` は `exporter.py:562` に定数 PROGRESS があるのに、`747`・`765` で手書きしている
  - watch の URL `"https://www.youtube.com/watch?v=" + id` = `analyze.py:277・459・722`、`exporter.py:661・696`、`rank.py:596・704`、`serve.py:75`
  - yt-dlp の `"--no-playlist", "--no-warnings"` = `analyze.py:276・459・722`、`exporter.py:658・696`
- 案: common に 3 つ置く。
  - `watch_url(vid)`
  - `ff_args(*args, overwrite=True, protocols="file,pipe")`(→ `[ff, -hide_banner, -nostdin, (-y), -protocol_whitelist, protocols, *args]`)
  - `ytdlp_base(yt)`(→ `[yt, --no-playlist, --no-warnings]`)
  
  exporter の `_ytdlp_cmd()`(テストが偽物に差し替える口)は残し、その後ろに残りの引数を付ける。
- 理由: 1 か所だけの書き漏れを防ぐ。今も `_reencode_audio`(746)・`measure_loudness`(764)・`concat_pieces`(869)にだけ `-protocol_whitelist` が無く、そろっていない(入力は自分で作ったファイルなので実害は無い)。
- 影響・リスク: 引数の並びを変えなければ、動きは同じ。whitelist もそろえて足すと動きが変わる(入力はローカルの mp4 だけなので問題は出ないはず。要確認)。関係するテスト: `test_robustness.py:254`(yt-dlp の -o は必ず common.ytdlp_out を通す、という検査。この検査は残る)、`test_exporter.py`(偽の yt-dlp)、`e2e_analyze.py`。

##### 4. 「道具が無い」「権限が無い」ときのエラーの組み立てがあちこちにある(優先度: 中・削れる行数の目安: 約 12 行)
- 場所:
  - ffmpeg が無い = `batch.py:90-91`、`analyze.py:821-823`、`exporter.py:301-303`(この 1 か所だけ文が違う。見直し S4 の winget の案内つき)
  - yt-dlp が無い = `batch.py:101-102`・`analyze.py:273-275`・`exporter.py:310-312`(3 か所とも同じ文)。理由の文字列を返す形が `analyze.py:456-458`・`717-719`
  - `common.permission_message(e) if isinstance(e, PermissionError) else ...` = `serve.py:159`、`exporter.py:810・1033・1102`。`analyze.py:1071-1073` は except を分けて同じことをしている
- 案: common に 2 つ置く。
  - `need_tool(name)`: パスを返す。無ければ決まった ApiError を投げる。名前ごとの文は辞書 1 つに持つ
  - `os_error_text(e, fallback)`: PermissionError なら permission_message、それ以外は fallback を返す
- 理由: S4 で直した ffmpeg の案内(winget)が exporter にしか入っていない。こういう文の食い違いは、この書き方から生まれる。
- 影響・リスク: 文を 1 つにそろえると、解析とキューの「ffmpeg が見つかりません」が exporter の案内文に変わる。画面の文が変わる(ユーザーに見える)。no_ffmpeg・no_ytdlp を確かめるテストは無い(grep で 0 件)ので、そろえるなら 1 件足す。権限の文は `test_api.py`・`test_file_recovery.py` が見ている。

##### 5. serve の do_POST と do_PUT が同じ。do_GET の例外処理も _guard と同じことを書いている(優先度: 中・削れる行数の目安: 約 15 行)
- 場所: `serve.py:273-282`(do_POST)・`284-293`(do_PUT)・`205-214`(do_GET の try/except)・`152-164`(_guard)
- 今: POST と PUT は、使う表の名前が違うだけで 10 行が同じ。GET は ApiError と Exception を自分で捕まえ、内部エラーの書き方(sys.stderr に redact して出す)は _guard と同じものを書いている。
- 案:
  ```
  def _write(self, routes):
      if not self._write_guard(): return
      fn = routes.get(self.path.split("?", 1)[0])
      if fn is None: return self._send(404, b"not found")
      obj = self._read_json()
      if obj is not None: self._guard(lambda: self._json(200, fn(obj)))
  def do_POST(self): self._write(POST_ROUTES)
  def do_PUT(self): self._write(PUT_ROUTES)
  ```
  GET の最後は `return self._guard(lambda: self._json(200, fn()))` にする。
- 理由: 安全の検査の順番(Host → Sec-Fetch-Site → Origin → 表 → 本文)が 1 か所になる。書き込みの API を足すときに、順番を崩しにくい。
- 影響・リスク: POST と PUT の動きは同じ。GET で OSError が起きたときだけ変わる: 応答が「内部エラー」から「ファイルの読み書きに失敗しました(…)」(error: write)になり、studio-errors.log にも残るようになる。良い方の変化だが、動きは変わる。入口の mount.py が上書きしているのは parse_request と _send だけなので、影響しない(確かめた)。関係するテスト: `test_api.py` 全般、`test_handoff.py:193-`、`test_rank_live.py:217-`、`e2e_ui.py`。

##### 6. serve.probe が ytt_core.runtime.ping と同じ処理(優先度: 中・削れる行数の目安: 約 10 行)
- 場所: `serve.py:483-495`、`src/ytt_core/runtime.py:101-`(ping)
- 今: http.client で 127.0.0.1 の /api/ping を読み、app が "clip-studio" なら版を返す処理を自分で持っている。プロキシを避ける理由の説明まで runtime.ping と同じ。
- 案: `r = ytt_runtime.ping(port, 1); return r["version"] if r and r["app"] == APP_ID else None`。serve の `import http.client` も要らなくなる。
- 理由: ping の作り(Host を固定する・読む大きさの上限・形の検査)は runtime の 1 か所にあり、`src/ytt_core/tests/test_ytt_core.py:249-` で確かめてある。
- 影響・リスク: runtime.ping は、port が 1024〜65535 でなければ問い合わせずに None を返す(今の probe は問い合わせる)。違うのは引数で 1024 未満を指定したときだけで、そのポートはもともと bind できないことが多い。版は 40 文字で切られる(SERVER_VERSION は短いので影響なし)。`test_robustness.py:263-282` が `serve.probe` を差し替えているので、関数の名前は残す。

##### 7. exporter.reason と common.tail_reason が同じ選び方をしている(優先度: 中・削れる行数の目安: 約 6 行)
- 場所: `exporter.py:108-115`、`common.py:157-160`
- 今: どちらも同じ手順: redact して長さを切る → エラーらしい語の正規表現に当たる行を選ぶ → 無ければ全部の行 → 末尾 n 行を / でつなぐ。違うのは次の点だけ。
  - 語の一覧: exporter のほうが多い(410・timed out・Unsupported)。exporter は "Stream #" の行を除く
  - 切る長さ: 200 と 220
  - 空の行を除くかどうか

  tail_reason は呼ぶたびに正規表現を組み立て直すが、re のキャッシュに乗るので速さは問題ない。
- 案: common に 1 つ(`tail_reason(lines, n=2, width=220)`)にまとめる。語の一覧は exporter の広い方に合わせ、"Stream #" は常に除く。exporter は `reason = functools.partial(common.tail_reason, n=3, width=200)` くらいにする。
- 理由: 失敗の理由の出し方を直すとき(例: 新しい yt-dlp のエラー文)、片方だけが直る、を防ぐ。
- 影響・リスク: 解析のエラー文で選ばれる行が少し変わることがある(語が増えるため)。関係するテスト: `test_exporter.py:588`(偽の yt-dlp の "ERROR: fake" が理由に出ること)。解析側を確かめるテストは無い。

##### 8. 古いキャッシュを消す処理が 3 か所にある。チャットの掃除はフォルダを 2 回読む。atomic_write の前に要らない makedirs がある(優先度: 中・削れる行数の目安: 約 15 行)
- 場所:
  - 古いものを消す処理: `analyze.py:299-305`(prune_cache)、`810-812`(save_archive で同じことを手書き)、`store.py:397-399`(SeriesCache で同じことを手書き)
  - prune_chat_cache: `analyze.py:343` と `365` で同じフォルダを 2 回 glob する
  - atomic_write の直前の `os.makedirs`: `store.py:395`、`analyze.py:411・734`、`handoff.py:34`(fsio.write_json → atomic_write)。ytt_core.fsio.atomic_write は自分でフォルダを作るので要らない
- 案:
  - save_archive と SeriesCache は `analyze.prune_cache(folder, pattern, keep)` を呼ぶ(store はもう analyze を import している)
  - prune_chat_cache は、1 回目の glob で `.live_chat.json` を全部 stat して (mtime, size, path, 使用中か) を持ち、合計と件数もそこから数える
  - makedirs の 4 行は消す
- 理由: 「いちばん新しいものは残す」「使っている物は消さない」のような決まりを足すとき、1 か所で済む。チャットのキャッシュは 1GB・数十件あるので、2 回目の glob と stat の分が減る。
- 影響・リスク: save_archive は今、掃除で OSError が出ると False を返す(保存はできているのに失敗扱い)。prune_cache は OSError を握りつぶすので、保存できていれば True になる(良い方の変化)。関係するテスト: `test_robustness.py:143-215`(sig の一時ファイル・合計の上限・件数・使っている物を残す・起動時の掃除)、`test_studio.py:434-441`(series の 60 件)、`test_analyze.py`(archive)。

##### 9. 数値の検査が 4 種類ある。exporter._num_sec は 500 になる穴がある(優先度: 中・削れる行数の目安: 約 10 行)
- 場所: `exporter.py:337-341`(_num_sec)、`store.py:68-75`(_f)・`78-86`(_num_strict)・`51-52`(_pos_int)、`store.py:690・746・774`(`isinstance(x, int) and not isinstance(x, bool)` の手書き)、`ytt_core/schemas.py:23-31`(num)
- 今: _num_sec は schemas.num とほぼ同じだが、OverflowError を捕まえない。たとえば 1 のあとに 0 が 400 個並ぶ巨大な整数を `start` に入れて /api/live/section に送ると、`float(v)` で OverflowError → _guard の「内部エラー」500 になる。schemas.num は、まさにこのために OverflowError を捕まえている。_num_strict は「schemas.num + `abs(x) <= MAX_TIME`」と同じ。
- 案:
  - `_num_sec` は `schemas.num` に置き換える(呼び出しを置き換えるか、`_num_sec = schemas.num`)
  - `_num_strict` は schemas.num の結果に `abs(x) <= MAX_TIME` だけ足す形にする
  - 整数の検査は `_is_int(x)` 1 つにする
  - _f は文字列の数も受け付ける(保存済みの data.json を読むため)ので、別に残す
- 理由: JSON の数の受け付け方の決まりを、ytt_core の 1 か所に寄せられる。
- 影響・リスク: _num_sec を置き換えると、巨大な整数は 500 から 400(「start・end が数値ではありません」)に変わる(直る方向)。この値は入口(home/live_archive)からしか来ないので、実害は小さい。関係するテスト: `test_exporter.py:776-850`(build_section_spec)、`test_studio.py`(check_times・アンカー)。

##### 10. ytt_core の小道具を使わずに書いている所(lint の dup-helper は名前しか見ないので当たらない)(優先度: 中・削れる行数の目安: 約 12 行)
- 場所:
  - `common.py:319`: spawn の creationflags。`tools.no_window_flags(new_group=True)` と同じ
  - `common.py:595-597`: _tool_version が subprocess.run を直に呼び、creationflags も手書きしている
  - `exporter.py:216-222`: _rm は `fsio.unlink_quiet` を繰り返すだけ
  - `exporter.py:556-557`・`687-688`: `if os.path.exists(out): os.unlink(out)`
- 案:
  - spawn: `kw["creationflags"] = kw.get("creationflags", 0) | _tools.no_window_flags(new_group=True)`
  - _tool_version: `run_short([exe] + args, timeout, merge_stderr=True)`(窓を出さない・終了の流れで止まる、が一緒に付いてくる)
  - _rm: `for p in paths: _fsio.unlink_quiet(p)`。exists + unlink の 2 か所は `_rm(out)`
- 理由: 子プロセスの起動と後片付けのやり方を ytt_core とそろえる(code-quality の基準 4 の目的)。
- 影響・リスク:
  - _tool_version を run_short にすると、起動直後の版の確認(yt-dlp --version)も children に入る。その最中に「すべて終了」しても止められる(今は最大 15 秒残る)。
  - _make・_ytdlp_sections の unlink を静かな版にすると、出力を消せないとき(Windows のロック)の結果が変わる。今は PermissionError が ExportError を隠して「内部エラー」になるが、元の理由のまま出るようになる(良い方の変化)。
  - 関係するテスト: `test_robustness.py:385-411`(子の止め方・run_short)、`test_api.py:466-475`(env の版)、`test_exporter.py`。

##### 11. store のマークの整形の定型(部品・理由・並べ替え・長さで切る)(優先度: 低・削れる行数の目安: 約 12 行)
- 場所:
  - parts と reasons の整形: `store.py:128-134`(_clean_server)と `849-850`(replace_auto。1 つの値に `_f(x)` を 2 回呼んでいる)
  - 点数の高い順 `key=lambda m: -(m["score"] or 0)`: `754・811・855`
  - 時刻の順 `key=lambda x: (x["start"], x["end"])`: `817・857・1096`
  - 配信の長さで終わりを切る: `789-795`・`1067-1070`
- 案:
  - `_clean_parts(d)`・`_clean_reasons(v)` を作り、_clean_server と replace_auto で使う
  - `_BY_SCORE = lambda m: -(m["score"] or 0)`・`_BY_TIME = operator.itemgetter("start", "end")`
  - `_clamp_end(v, e)`(切った終わりか None を返す)
- 理由: 自動マークの parts の鍵(PART_KEYS)や、理由の上限(6 件・40 字)を変えるとき、2 か所をそろえなくてよくなる。
- 影響・リスク: 動きは同じ。関係するテスト: `test_studio.py`(replace_auto・request_marks・コラボ)、`test_api.py:587-624`(adopt-top)。

##### 12. コラボのグループを更新する定型と、区分の範囲の判定の重複(優先度: 低・削れる行数の目安: 約 8 行)
- 場所:
  - `store.py:986-990`・`1003-1005`・`1025-1028`: `ng = dict(g, …, updatedAt=now_ms())` → `_commit_group` → `_group_summary` の繰り返し
  - `store.py:315-316` と `342-343`: `(lo is None or t >= lo) and (hi is None or t < hi)`
  - `store.py:1060`: `(m.get("collabFrom") or {})` を 2 回書いている
- 案:
  - `_save_group(g, **changes)`: updatedAt を付けて保存し、要約を返す
  - `_in_piece(pc, t)`
  - 1060 行は `m.get("collabFrom") == {"videoId": from_vid, "markId": from_mark_id}`(_collab_from が必ずこの 2 つの鍵だけの dict にしているので、これで足りる)
- 理由: 読みやすくなる。グループに項目を足すときの書き漏れ(updatedAt の付け忘れなど)を防ぐ。
- 影響・リスク: 動きは同じ。関係するテスト: `test_studio.py`・`test_api.py`(collab)、`e2e_ui.py`。

##### 13. rank の繰り返し(FATAL の投げ直し・キャッシュの手書き・日時の 2 段の解析)(優先度: 低・削れる行数の目安: 約 15 行)
- 場所:
  - 「FATAL なら投げ直す・それ以外は空にする」: `rank.py:317-322`・`360-365`・`553-557`・`739-744`
  - 未解決のチャンネルの dict: `353`・`374`
  - キャッシュ: `_cached`(440-451)があるのに、`fetch_videos`(487-494)と `live_list`(780-786)は _cache を手で引いている
  - `parse_dt`(398-407): strptime を 2 通り試し、だめなら fromisoformat
- 案:
  - `_soft(fn, default, on_err=None)`: FATAL は投げ直し、それ以外は on_err(ex) を呼んで default を返す
  - `_pending(ref)`
  - `_cache_get(key, ttl)` を作り、_cached・fetch_videos・live_list で使う
  - parse_dt は `datetime.fromisoformat(s.replace("Z", "+00:00"))` だけにする(3.10 で "+00:00" と、"Z" を置き換えた形の両方を読める。タイムゾーンも付く)
- 理由: 失敗の扱い(FATAL の一覧)を変えるとき、4 か所を探さなくて済む。
- 影響・リスク: parse_dt は、strptime で読めていた形(秒まで・Z か +00:00)では結果が同じ。小数秒の桁が 3・6 以外の値は、今も読めない(変わらない)。関係するテスト: `test_rank_live.py`(live_row・yt_get の疑似)、`test_api.py` の rank。parse_dt だけを確かめるテストは無い。

##### 14. 使われない値・テストのためだけの包み・そのまま渡すだけの関数(優先度: 低・削れる行数の目安: 約 15 行)
- 場所:
  - `analyze.py:93・99`: 解析の設定の maxHeight。検査して spec に入るが、解析は音声だけを取るので誰も読まない。書き出しの maxHeight は review.js の設定から別に来る(`exporter.py:292-298`)
  - `handoff.py:61-68`: read_runtime_port・ping_app。使っているのは `test_handoff.py:122-222` だけ。serve.mounted_elsewhere は ytt_runtime を直接呼んでいる。同じことは `src/ytt_core/tests/test_ytt_core.py:227-255` でも確かめてある
  - `analyze.py:987-989`: _candidates は excite.candidates をそのまま呼ぶだけ
  - `serve.py:402-403`: _put_registry は rank.put_registry をそのまま呼ぶだけ
  - `batch.py:21-22`: _now_ms は store.now_ms と同じ
  - `batch.py:280`: 候補の鍵を写し直しているが、store.replace_auto が全部を検査し直す
- 案:
  - maxHeight は validate_settings から外す。画面の `queue.js:46` の「画質の上限」の欄は、外すか書き出しに渡すかを別のグループで決める(要確認)
  - handoff の 2 つは消す(ytt_core 側に同じテストがある)
  - そのまま渡すだけの関数は、呼ぶ側から直接呼ぶ(`"/api/rank/registry": rank.put_registry`)
- 理由: 解析の画面に、効かない「画質の上限」が出ていて、利用者を迷わせる。使われない道を残すと、読む人が「どこで使われるのか」を探すことになる。
- 影響・リスク: maxHeight を外しても、画面の欄が残っている間は値が黙って捨てられるだけ(今も効いていないので同じ)。handoff の包みを消すと、`test_handoff.py` の該当のテストを消す必要がある(ytt_core 側に同じテストがあるので件数は実質減らない)。lint の dead-name はテストからの参照も数えるので、lint では見つからない。

##### 15. 定数・正規表現・小さな定型の重複(優先度: 低・削れる行数の目安: 約 15 行)
- 場所:
  - `API_BASE` が 2 か所: `rank.py:26` と `analyze.py:27`
  - 動画 ID の正規表現:
    - `common.VID_RE`(43。ASCII だけ)があるのに、`analyze.py:506` は `re.fullmatch(r"[\w-]{11}", vid)` を使っている。**ASCII のフラグが無い**ので、全角の英字なども通る
    - `rank.py:674` は VID_RE と同じ式を手書きしている
    - `analyze.ARCHIVE_ID_RE`(782)は `store.ID_RE`(25)と同じ
    - `common.parse_video_id` の YouTube のホスト(224)は、`YT_HOSTS`(240)から youtu.be を除いたもの
  - `batch.py:110・158` の「10本まで」は MAX_ACTIVE を使っていない。add と retry の「いっぱい・重複」の判定(108-114 と 156-160)も同じ処理
  - 小さな JSON の読み込み(開く → json.load → dict か確かめる → 例外なら既定の値): `common.py:189-195`・`549-557`、`store.py:407-414`・`1100-1106`、`analyze.py:695-703`
  - ログに 1 行足す処理(ロック → rotate_log → 追記 → 失敗は無視): `serve.py:530-540`、`common.py:137-147`、`exporter.py:95-105`
- 案:
  - 定数と正規表現は common の 1 つを使う(prefetch_chat は `VID_RE.match`)
  - batch は `_admit_error(vid)` を作り、add と retry で使う
  - `common.read_json_dict(path, default=None)` と `common.append_log(path, text, limit)` を 1 つずつ作る
- 理由: 値の食い違いが実際に出ている(ASCII に限るかどうか)。
- 影響・リスク:
  - prefetch_chat の ID の検査を VID_RE にすると、ASCII でない文字を含む 11 文字は先読みしなくなる。ただ validate_source を通った ID はもう ASCII なので、実際の動きは変わらない。
  - read_json_dict に ytt_core.fsio.read_json_file(NaN を断る)を使うと、series の中に NaN があったときに読めなくなる恐れがある。なので json.load のまま作る。
  - 関係するテスト: `test_robustness.py`(ログの回し方 216-249・先読み)、`test_studio.py`、`test_api.py`。

#### 他のグループとの重複の疑い
- (疑い)`src/home/live_export.py:103-170` が、exporter の名前の決まりを丸ごと写している(コメントにも「スタジオの書き出しと同じ規則」とある)。写しているのは compact_ts・safe_name・path_units・trim_units・is_reserved・WIN_RESERVED・MAX_PATH_UNITS・SUFFIX_ROOM・PARTIAL。exporter 側は `exporter.py:37-43・62-92`。WIN_RESERVED は書き方が違うだけで中身は同じ。ytt_core の 1 か所(例: `names.py`)にまとめる候補。
- (疑い)動画の Range 応答: `serve.py:227-264`(_media)と `src/editor/serve.py:475-515` が、Range の読み方・416・チャンクの送り方まで同じ。ytt_core.httpsec に `parse_range(header, size)` と `send_file(handler, path, ctype)` を置ける。
- (疑い)ポートを独り占めするサーバー(SO_EXCLUSIVEADDRUSE・Windows では reuse しない): `serve.py:471-480` の StudioServer、`src/cut2resolve/serve.py:848-855`、`src/home/launch.py:1116`、`src/recorder/recorder.py:315`、`src/home/restart.py:93`。ytt_core の基底クラス 1 つにできる。
- (疑い)JSON の本文の読み取り(Content-Type・Content-Length・上限・dict か): `serve.py:125-150`、`src/editor/serve.py:372-392`、`src/cut2resolve/serve.py:723`、`src/home/launch.py:569`(read_json_body。使う所は 676)。入口の read_json_body を ytt_core.httpsec に移せば、3 つのツールで使える。応答の形はツールごとに違うので、返すのはエラーの番号と文だけにする。
- (疑い)解析の設定の「画質の上限」(`src/studio/queue.js:46・77`。画面のグループの担当)は、#14 のとおりサーバーで使われていない。
- (疑い)`dev/eval_fetch.py:70` に、common.fmt_ts とは別の fmt_ts がある(形が同じかは確かめていない)。


### G6 editor-py-A(担当: src/editor/ed_jobs.py(3,068 行)・src/editor/ed_speakers.py(1,505 行)・src/editor/ed_learn.py(1,329 行)・src/editor/tx_engines.py(1,178 行)・src/editor/tx_worker.py(322 行)、合計 約 7,400 行)

#### 全体の傾向
- ジョブの本体(`run_job`・`run_redo`・`run_retranscribe`・`run_diarize`・`run_voice_learn`)は「一時 wav → 音声の取り出し → モデル → 取り消しの確かめ → 書き込み」という同じ骨組みを、少しずつ違う形で写している。取り消しの確かめ(2 行)が 26 か所、GPU → CPU の切り替えが 3 か所あるなど、同じ規則があちこちに写されている。
- 既定でオフの実験の経路(行の終わりを音の谷へ寄せる・1 秒丸めの配り直し・声の無い所の行を捨てる)が ed_jobs と tx_engines に約 300 行残っている。これが `run_job`・`RangeRecognizer` を読みにくくしている主な原因。
- エンジンは表(`tx_engines.ENGINES`)で選ぶ形になっていて良い。ただ、sherpa-onnx を使う 2 つのエンジン(Qwen3-ASR・SenseVoice)は、取得・区切り・行の作り方を写している。
- JSON・設定・環境変数の読み書きを部品ごとに手で書いていて、ytt_core(fsio・tools)にある部品を使っていない所がある。設定ファイルは 1 回の要求の中で何度も読み直されている。

#### 指摘

##### 1. GPU → CPU の切り替えが 3 か所に写されている(優先度: 高・削れる行数の目安: 約 20 行)
- 場所: `src/editor/ed_jobs.py:1113-1125`(transcribe_real)・`src/editor/ed_jobs.py:2319-2330`(ChunkModel.recognize)・`src/editor/ed_jobs.py:2786-2798`(RangeRecognizer.main)
- 今: 3 か所とも同じ規則を少しずつ違う形で書いている。規則 = 例外が起きたら、device が cuda で処理方式が auto のときは phase・device を書き換えて `load_model(force_cpu=True)` で読み直し、もう一度実行する / cuda 固定なら gpu_failed / それ以外はそのまま上げる。エラーの文も 2 種類ある(install-gpu.bat の案内があるものと無いもの)。
- 案:
  ```python
  def with_cpu_fallback(job, device, pref, run, reload):
      try: return run()
      except (Cancelled, ed_state.ApiError): raise
      except Exception:
          if device != "cuda": raise
          if pref != "auto": raise ed_state.ApiError("gpu_failed", GPU_FAILED_MSG, 500)
          job["phase"], job["device"] = "GPU が使えないため CPU で処理します", "cpu"
          reload(); return run()
  ```
- 理由: 規則を変えるとき(文言・どの例外で CPU に切り替えるか)に直す所が 1 つで済む。3 か所が同じ規則だということも、読めばすぐ分かる。
- 影響・リスク: **動きが少し変わる**。今の ChunkModel は `except Exception` で Cancelled・ApiError も捕まえるので、最初の行で取り消すと CPU のモデルを読みに行く(無駄な動き)。そろえると、取り消しや worker_crashed のときは CPU でやり直さなくなる(良い方向だが確認が要る)。エラーの文はどちらか 1 つに寄せる。**この経路を通るテストは無い**(tests/ に「CPU で処理します」も force_cpu も出てこない)。直すなら、先に test_worker.py に「1 回目だけ例外を出す偽のモデル + device cuda」のテストを足す。

##### 2. ジョブの決まった手順(一時 wav・取り消しの確かめ・注意の足し方)を小さな関数にする(優先度: 高・削れる行数の目安: 約 50 行)
- 場所:
  - 一時 wav(パスを作る → `job_errors(job, wav)` → `os.makedirs(TMP_DIR)`): `ed_jobs.py:2038-2040`・`2682-2684`・`2984-2986`、`ed_speakers.py:572/584-585`・`1380-1382`
  - 取り消し(`if job["cancel"]: raise Cancelled()`): `ed_jobs.py` の 19 か所(723, 1086, 1104, 2007, 2062, 2067, 2525, 2708, 2726, 2818, 2826, 2845, 2960, 2968, 3002, 3014, 3019, 3046, 3060)と 1644(job.get の形)、`ed_speakers.py` の 6 か所(88, 226, 236, 610, 1154, 1402)
  - 注意の足し方が 3 通り: `job["warnings"] = list(job.get("warnings") or []) + [...]` は `ed_jobs.py:2059, 2107`・`ed_speakers.py:944, 946`。`job.setdefault("warnings", []).append(...)` は `ed_jobs.py:2956, 3033, 3036`・`ed_speakers.py:1414`。`spec.setdefault("warnings", []).append(...)` は `ed_jobs.py:2158`
  - 中止の状態(`job["state"], job["phase"] = "cancelled", "中止しました"`): `ed_jobs.py:96, 2185, 2191, 2207`
- 今: 7 つのジョブの本体(担当外の ed_alt・ed_misc を含む)が、毎回同じ 3 行を書いている。取り消しの確かめは 2 行 × 26 か所ある。
- 案: 次の 4 つを作る。
  - `with job_temp_wav(job, cancelled=…, log=…) as wav:`: job_errors を包み、TMP_DIR を作ってからパスを渡す
  - `check_cancel(job)`: 1 行で取り消しを確かめる
  - `add_warning(job, msg)`: 注意を足す(同じ文は重ねない)
  - `set_cancelled(job, phase="中止しました")`: 中止の状態にする
- 理由: 本体の関数が短くなり、決まった手順の抜け(makedirs を忘れる、など)が起きにくくなる。
- 影響・リスク: 動きは同じ。ただし `_doc_fields`(2158)は注意を spec 側に足している。job 側に寄せても `public_job`(672-695)は両方を読むので画面は同じになるが、念のため確かめる。ついでに `ed_speakers.py:576-583`(1 人のときの道)の扱いも見直したい。ここは例外の型の名前を `error` に直接入れていて、内部の文言は errorDetail に入れるという M9 の決まりから外れている。job_errors で包めばそろう(画面に出る文言が変わる)。名前は serve.py が部品から集めるので、ほかの部品と重ならない名前にする。テスト: test_metrics から読むもの全部(test_backend・test_worker・test_voices・test_edit)、test_evalbatch・test_autodiar・test_alt・test_fill・e2e_ui_mounted。

##### 3. tx_engines: SenseVoice と Qwen3-ASR で同じ処理を写している(優先度: 高・削れる行数の目安: 約 40 行)
- 場所:
  - create: `tx_engines.py:717-733` と `844-862`。名前の検査・sherpa_onnx の有無に加え、取得 → 展開 → ファイルがそろったかの確かめ(726-733 と 855-862)が同じ 8 行
  - transcribe: `675-699` と `881-917`。音の大きさ rms の計算(680-682 と 888-890)、区切り・取り消し・進み具合・無音を飛ばす所(686-692 と 895-901)、行を SimpleNamespace にする所(696-698 と 914-916)が同じ
  - スレッド数の式 `max(1, min(8, (os.cpu_count() or 4) // 2))`: 337・754・878 の 3 か所
  - compression_ratio(zlib)付きで行を作る SimpleNamespace: 467・697・915・924 の 4 か所
- 案:
  - `_ensure_tar_model(spec, folder, log, hooks)` で、取得・展開・確かめをまとめる
  - SenseVoice を `_Qwen3Chunked` の子クラスにする。区切りの中の行を作る所だけ `_chunk_rows(x, c0, c1, rms)` として上書きする(Qwen3 は `_decode` + q3_rows、SenseVoice はトークンの時刻 + sv_rows)
  - `HALF_CPU` の定数と `_seg(start, end, text, words=(), lp=None)` を作る
- 理由: sherpa-onnx のエンジンを 3 つ目に足すとき、同じ 40 行を写さずに済む。rms・無音のしきい値・進み具合を直すときも 1 か所で済む。
- 影響・リスク: SenseVoice には `light = True`・`_recognizer(lang)`・FAKE_TEXT の道がある。Qwen3 は hotwords ごとに認識器を作る。上書きする所を間違えなければ動きは同じ。sherpa_onnx が無いときの案内(install.bat / install-diarize.bat)は 2 つで違うので、引数で渡す。ついでに、rms の計算はコマごとに numpy を呼んでいる(682・890)。reshape を使えば 1 回の呼び出しで済み、長い音声で速くなる(最後の半端なコマの平均の取り方だけ注意)。テスト: test_qwen3.py・test_fill.py の TestSenseVoiceEngine・test_whispercpp.py(parse_json)。

##### 4. 既定でオフの実験の経路が約 300 行残っている(優先度: 中・削れる行数の目安: 消せば約 300 行、最小の直しなら数行)
- 場所:
  - ed_jobs の定数: `ed_jobs.py:1268-1291`(PULL_*・END_TRIM)
  - 行の終わりを寄せる部品: `ed_jobs.py:1362-1466`(WavLevels・row_levels・pull_end・trim_ends・pull_ends)
  - 1 秒丸めの配り直し: `ed_jobs.py:1477-1656`(QUANT_*・quant_is_int・quant_windows・quant_retime・_quant_settle・quant_words_provider・_frange)
  - 使っている所: `ed_jobs.py` の 2055-2059・2529・2799-2803・2829・3025・3034-3036
  - tx_engines: `tx_engines.py:320-324, 351-359`(native_vad の切り替え)・`384-388, 473-505`(speech_spans・drop_outside_speech。注記に「測ったら悪くなった」とある)
- 今: どれも環境変数で既定オフになっている(TRANSCRIBE_PULL_ENDS・TRANSCRIBE_END_TRIM=0・TRANSCRIBE_RETIME・TRANSCRIBE_WCPP_SPEECH_FILTER・TRANSCRIBE_WCPP_VAD)。注記には「測り直すとき用」とある。普段の道でも、whisper.cpp のときは毎回 `row_levels` が wav を開いて WavLevels を作る。でも PULL_ENDS_ON が偽なので使われない(2055・2529・2799・2829。担当外の ed_alt.py:174 も同じ)。
- 案:
  - (小さな直し)`row_levels` の先頭に `if not PULL_ENDS_ON: return None` を足す。動きは同じで、4 か所の無駄な wav の読み取りが消える
  - (大きな直し)測るときにしか使わない部品を `ed_experimental.py` か dev/ の側へ移すか、消す。`quant_retime` は既定オフなら行をそのまま返すだけなので、呼んでいる 3 か所(2057・2801・3034)ごと外せる
- 理由: run_job・RangeRecognizer で読むコードが減り、「今どの後処理が効いているか」を追いやすくなる。`post_record`(1704-1709)の記録はそのまま残せる。
- 影響・リスク: **既存機能の削除なので、ユーザーの確認が要る**(AGENTS の決まり)。次のものがこの部品を使っている: dev/eval_asr.py:729-731、dev/eval_timing.py(VARIANTS の END_TRIM・JOIN_GAP)、dev/tests/test_eval_asr.py・test_eval_timing.py、src/editor/tests/test_whispercpp.py。JOIN_GAP(既定 0.5)と join_rows は今も使っているので残す。移す場合は、serve.py の名前の受付(`S.QUANT_ON = …` のような差し替え)も合わせて直す。

##### 5. 話者判別: 行ごとの割合 label_ratio が全区間を毎回数え直す(O(行 × 区間))。同じ並べ直しも 3 回している(優先度: 中・削れる行数の目安: 約 10 行。速くもなる)
- 場所: `ed_speakers.py:246-274`(assign_speakers。二分探索で重なりを数える)・`291-296`(label_ratio。ts を全部見る)・`322`(smooth_speakers が全行で label_ratio を呼ぶ)・`405-408`(build_diar_run が全行で label_ratio を呼ぶ = 判別のたびに必ず通る)。`sorted((a + offset, b + offset, s) for ...)` は 250・405・482 の 3 回
- 今: assign_speakers は行ごとに `ov[ラベル] = 重なりの秒` をもう計算している。それなのに、build_diar_run と smooth_speakers が同じ値を label_ratio で全区間から数え直している。3 時間の配信(行も区間も数千)だと、足し算が数千万回になる。
- 案: 中で使う `_assign(segs, ts)` を作り、`(sp, mixed, weak, ratio)` を返すようにする(ratio = min(1, ov.get(sp, 0) / dur)。重なりが無くて最寄りの区間で代わりにした行は 0)。assign_speakers は今の 3 つ組を返す形のまま `_assign` を包む。_apply_diarization で ts を 1 回だけ作り、smooth_speakers と build_diar_run には ratio の並びを渡す。
- 理由: 割合の数え方が 1 か所になる(二分探索の窓と全区間の 2 通りがたまたま同じ答えになることに頼らなくて済む)。長い配信で、判別が終わるまでの待ちが短くなる。
- 影響・リスク: ratio の値は変わらないはず(重なる区間は、二分探索の窓 [a − 最長, b] に必ず入る)。足す順が変わって浮動小数の値がわずかにずれる可能性はあるが、記録は round(…, 3) なので差は出ない見込み(要確認)。dev/eval_speakers.py:798 と tests/test_smooth.py:89,100 が assign_speakers の戻り値の形を使っているので、形は変えない。label_ratio も test_smooth.py:76-80 が直接呼んでいるので残す。テスト: test_smooth・test_voices(TestDiarRecord)・test_ovdraft。

##### 6. 1 回の要求で設定ファイルを何度も読む。同じ形の判定も写している(優先度: 中・削れる行数の目安: 約 15 行)
- 場所:
  - validate_job: `ed_jobs.py:605-611` で `ed_learn.load_settings()` を最大 4 回呼ぶ。602 の split_chars_for → subtitle_settings でもう 1 回読む
  - 置換辞書の組: `ed_jobs.py:2053` で dict_pairs を 1 回作り、`_doc_fields` → recognition_run → dict_version(1758)でもう 1 回作る(設定と名簿の表を 2 回ずつ作っている)。`_apply_range`(2471 と 2497)・`_apply_retranscribe`(2348 と 2352)も同じ
  - 数の範囲の判定 `isinstance(n, (int, float)) and not isinstance(n, bool) and lo <= n <= hi`: `ed_jobs.py:1152, 1154, 1162, 1175`(似た形が 1667・1903・2603、`ed_learn.py:37, 63` にもある)
  - subtitle_max_chars と split_chars_for の先頭 4 行(1160-1163 と 1173-1176)が同じ
  - 同じく、spec の組み立ての決まった形も写している:
    - 題名 `(str(doc.get("title") or "") or "無題")[:100]`: `ed_jobs.py:2268, 2604`・`ed_speakers.py:534, 930, 1375`
    - device の選び方: `ed_jobs.py:599, 2266`
    - モデル名・言語の検査: `ed_jobs.py:571-576, 2234-2237, 2591-2593, 2600`
- 今: load_settings(`ed_learn.py:26-32`)にはキャッシュが無く、呼ぶたびに config.json を開いて読む。
- 案:
  - validate_job の先頭で `st = ed_learn.load_settings()` を 1 回だけ呼び、`_pref(req, st, "autoAlt")`(要求の真偽値があればそれ、無ければ設定の値)で決める。split_chars_for には st を渡す(引数はもうある)
  - `dict_version(spec, pairs=None)` にして、作った pairs を受け取る
  - 数の範囲は `ed_state.num_in(v, lo, hi)`(plain_int の隣に置く)。題名は `job_title(prefix, doc)` にする
- 理由: 1 回の文字起こしで同じファイルを 5〜7 回読まずに済む。4 つの auto の設定の「要求 → 設定 → 既定」の決め方が、1 行ずつ並んで読める(autoFill だけ既定オン = `is not False` という違いが、引数で見えるようになる)。
- 影響・リスク: 動きは同じ(読んでいる途中で設定が書き換わる食い違いが無くなる分、むしろ安定する)。load_settings そのものに stat のキャッシュを付ける案もある。ただ patch_settings・merge_settings(`ed_learn.py:83-85, 98-109`)が返り値を書き換えて保存しているので、キャッシュするなら写しを返す必要がある(影響が広いので見送りを勧める)。テスト: test_metrics の test_subtitle_settings(118)・test_backend・test_alt(autoAlt)・test_fill(autoFill)・test_autodiar(autoDiarize)・test_records(辞書の版)。

##### 7. 同時に入れない組み合わせの表 EXCLUSIVE と、入口の検査の組がずれている(優先度: 中・削れる行数の目安: 約 6 行)
- 場所: `ed_jobs.py:115-118`(tid_busy)・`618-620`(EXCLUSIVE)・`653`(add_job が tid_busy と同じ検査をロックの中で写している。tid_busy は同じロックを取るので、そのままは呼べない)・`2240`(validate_retranscribe は ("diarize","retranscribe"))・`2596`(redo_spec は EXCLUSIVE["redo"])、`ed_speakers.py:526`(validate_diarize は ("diarize","retranscribe"))・`1372`(validate_voice_learn は 4 つの組。EXCLUSIVE["voice-learn"] の ("diarize","voice-learn") より広い)
- 今: 入口の検査(validate_*)と最後の検査(add_job の EXCLUSIVE)で、断る組み合わせが違う。例: 声を覚えるジョブ(voice-learn)は、validate では再認識中なら断るが、add_job では断らない。判別は、validate では redo を見ないが、add_job では見る(文言が違うだけで、結局は断られる)。
- 案: ロックの中だけで使う `_busy_locked(tid, kinds)` を作り、tid_busy と add_job の両方から呼ぶ。validate_* は `tid_busy(tid, EXCLUSIVE[kind])` にそろえ、EXCLUSIVE["voice-learn"] を今の validate の組まで広げる。
- 理由: 「何と何を同時に動かさないか」の正が 1 つの表になる。
- 影響・リスク: validate_diarize・validate_retranscribe で断るタイミングが少し早くなる(今も add_job で断られるので結果は同じ。文言は変わる)。voice-learn は add_job でも広く断るようになる(違いが出るのは、validate を通った直後に別のジョブが割り込んだときだけ)。テスト: test_voices・test_edit・test_autodiar・test_evalbatch(busy の 409)。`_spksub_busy`(`ed_speakers.py:1467-1470`)は「文書を書き換えない種類だけ除いて、ほか全部」という別の決まりなので、そのままにする。

##### 8. 話者判別のモデルの取得を tx_engines.fetch_file にまとめる(優先度: 中・削れる行数の目安: 約 35 行・要確認)
- 場所: `ed_speakers.py:81-101`(_download_verified)・`104-129`(ensure_diar_models)・`110`(`_have`(72-73)と同じ判定を写している)、`tx_engines.py:182-226`(fetch_file)・`636-648`(_safe_extract)
- 今: 「決まった URL から取り、SHA-256 を確かめ、.part に書いてから置き換える」処理が 2 つある。tx_engines の方は、大きさの一致・https だけ・取り消し・進み具合を確かめる。ed_speakers の方は大きさの上限(max)だけを見て、User-Agent やエラーの code(model_download・model_hash)も独自。
- 案: DIAR_SEG・DIAR_EMBS に大きさ(size)を足し、`tx_engines.fetch_file(item, DIAR_DIR, log, cancelled=lambda: job["cancel"], progress=…)` に置き換える。tar から 1 つだけ取り出す所(115-122)は残すか、`_safe_extract` を使う。少なくとも 110 は `_have(item)` に置き換える。
- 理由: 「取得物は URL・大きさ・SHA-256 で固定する」(tx_engines の冒頭にある決まり)を、すべての取得に同じ強さでかけられる。
- 影響・リスク: **4 つのファイルの正しい大きさを、先に確かめる必要がある(要確認)**。エラーの code と文言は fetch_failed の側に変わる(画面に出る文言が変わる)。tx_engines はサーバー側からも読める(標準ライブラリだけ)ので、numpy などを import しない決まりには当たらない。テスト: test_whispercpp の test_fetch_file_checks_size_and_hash(170)・test_voices(ensure_diar_models を差し替えているので、本物の取得はテストに無い)。

##### 9. doc_metrics の 3 つの分岐を 1 つにし、同じ文字列を 2 回作らないようにする(優先度: 中・削れる行数の目安: 約 8 行)
- 場所: `ed_learn.py:802-823`
- 今: 「機械と人の両方にある / 機械だけにある / 人だけにある」で 3 つに分岐している。最初の分岐では、`_norm(segs, ge)`・`_norm(orig, go)` を norm_cer の中と raw_ref・raw_hyp で 2 回ずつ計算している。
- 案:
  ```python
  if ge and not all(is_ok(segs[i]) for i in ge): continue
  rows = [segs[i] for i in ge] or [orig[i] for i in go]
  a, b = min(r["start"] for r in rows), max(r["end"] for r in rows)
  if not ge and (a < lo - 0.05 or b > hi + 0.05): continue
  raw_ref, raw_hyp = (_norm(segs, ge) if ge else ""), (_norm(orig, go) if go else "")
  ref, hyp, mo = norm_cer(raw_ref), norm_cer(raw_hyp), not ge
  ```
- 理由: 3 つの場合の違い(範囲を確かめるのは機械だけのとき、時刻は人の行を優先する)が 2 行で読める。精度の測定は全文書を見るので、文字列を作る回数が半分になる。
- 影響・リスク: norm_cer("") は "" なので、結果は変わらない。別件で小さいが、`_doc_info`(382-399)も同じ形で 1 回にできる。learn_events と learn_groups(こちらは件数を数えるだけ)が、それぞれ `_prep_main` と `_groups` を計算し直している。テスト: test_metrics(精度)・test_nosub_metrics・test_ovdraft、dev/ の eval_asr 系(doc_metrics を使う道具)。

##### 10. JSON の読み書きの決まった形を ed_state の関数にまとめる(優先度: 中・削れる行数の目安: 約 20 行)
- 場所:
  - 読む所: `ed_learn.py:26-32`(load_settings)・`444-457`(load_feedback)・`880-886`(read_baselines)・`1138-1142`・`1296-1300`(manifest)、`ed_speakers.py:1059-1065`(load_voices)、`ed_jobs.py:2910-2916`(read_resume)、`tx_engines.py:276-282`(WhisperCpp.manifest)
  - 書く所: `ed_jobs.py:1879, 1918, 2926`、`ed_speakers.py:353, 1074`、`ed_learn.py:85, 106-109, 486, 903, 1214, 1218, 1239`
- 今: `try: open → json.load → isinstance → except (OSError, ValueError): 既定の値` を 8 か所で書いている。BOM 付き(utf-8-sig)を読めるものと読めないものが混ざっていて、声・続きの記録・manifest は BOM 付きだと読めない。大きさの上限も無い。書く方も `ed_state.atomic_write(path, json.dumps(obj, ensure_ascii=False, …).encode("utf-8"))` が 12 か所ある。
- 案:
  - 読む: `ed_state.read_json(path, default, kind=dict, max_bytes=…)` を作る。中身は ytt_core.fsio.read_json_file(BOM 可・上限つき・NaN を断る)
  - 書く: `ed_state.write_json(path, obj, indent=None, compact=False)` を作る。fsync つきの atomic_write はそのまま使う
  - tx_engines は ed_state を読めないので、`_fsio.read_json_file` を直接使う
- 理由: 読めないときの扱い・文字コード・大きさの上限が 1 か所で決まる。ytt_core にある部品を使える。
- 影響・リスク: NaN・Infinity を含むファイルや、上限を超えるファイルは「読めない」扱い(既定の値)になる。つまり今より少し厳しくなる。ytt_core.fsio.write_json は indent=2 で fsync もしないので、そのままは使わない(編集の書き込みは fsync 必須 = ed_state.atomic_write の決まり)。テスト: test_backend(設定)・test_voices(声)・test_alt・test_ytcap(feedback)・test_worker(続きの記録)。

##### 11. ovdraft・diar.json の小さな写し(優先度: 低・削れる行数の目安: 約 15 行)
- 場所:
  - 同じラベルの区間を OVDRAFT_JOIN でつなぐ処理が 2 回: `ed_speakers.py:739-752` と `831-836`
  - labelMap を逆引きする式が同じ: `371` と `1012`
  - voices の経過の空の辞書 {top, score, second, secondScore, …} を 3 回書いている: `1013-1014`・`1193`・`1247-1248`
  - `_diar_lock` の中で「read_diar → 書き換え → _diar_put」をする形が 2 回: `364-376` と `1000-1022`
- 案: 次のものを作る。
  - `_join_label_spans(1 つのラベルの区間)`
  - `_label_of(latest)`(逆引き)
  - 定数 `_VOICE_DETAIL`(使うときは dict(...) で写す)
  - `@contextmanager _diar_edit(tid)`(読めなければ None を渡す)
- 理由: ovdraft の 2 種類の候補(重なり・抜け)が同じつなぎ方を使っていることが、コードの形で保証される。
- 影響・リスク: 動きは同じ。ただし ovdraft_candidates は主の話者を除き、ラベルを文字列で比べる。_ovdraft_missing は全部のラベルを使う。なので、まとめる関数は「つなぐ所」だけにする。テスト: test_ovdraft・test_voices(TestDiarRecord)・test_autodiar。

##### 12. tx_worker: 偽の判別の写しと、要求の種類の if の連なり(優先度: 低・削れる行数の目安: 約 12 行)
- 場所:
  - 偽の判別: `tx_worker.py:187-202`(fake_diarize。コメントに「ed_speakers.diarize_fake と同じ」とある)と `ed_speakers.py:231-243`(diarize_fake)
  - 要求の種類の分岐: `tx_worker.py:221-261`(handle の if/elif が 4 つ)
  - wav の形の確かめ: `tx_worker.py:125` と同じ条件が `ed_speakers.py:138, 166`・`tx_engines.py:656`・`ed_jobs.py:1372` にもあり、全部で 5 か所
- 今: fake_diarize は、区間の作り方・進み具合・待ち時間(TRANSCRIBE_FAKE_DELAY)まで diarize_fake と同じ。違いは、wav から長さを読むことと diar_tune で確かめることだけ。
- 案:
  - fake_diarize の中身を `S.diar_tune(...); total = wav の長さ; return S.diarize_fake(job, total, num, threshold)` にする
  - handle は `OPS = {"load": _op_load, "transcribe": _op_transcribe, ...}` の表にして、例外の扱いだけ handle に残す
  - wav の形の確かめは `tx_engines.is_16k_mono(w)`(標準ライブラリだけ)にまとめる
- 理由: 偽物どうしが食い違う心配が無くなる(テストが本物と同じ形を試している、という保証が強くなる)。
- 影響・リスク: diarize_fake は `ed_state.fake_sleep()` で同じ環境変数を読むので、待ち時間は同じ。進み具合も、t/max(total,1e-6) と e/total で同じ値になる。テスト: test_worker(worker-fake での判別)・test_voices・e2e_ui_mounted。

##### 13. ytt_core や標準ライブラリで済む、小さな自前の処理(優先度: 低・削れる行数の目安: 約 20 行)
- `ed_jobs.py:136-140` の `_worker_flags` は `ytt_core.tools.no_window_flags(new_group=True)` と同じ(ed_state が tools をもう読み込んでいる)。
- `ed_jobs.py:262-268` の `WorkerClient.kill` と `720-721`(extract_audio の後始末)は、`tools.kill_quiet(p)` で済む。
- `ed_jobs.py:1910-1914`(write_words でファイルを消す所)と `2937-2941`(drop_resume)は、`ed_state.unlink_quiet` で済む。
- `ed_jobs.py:246-250, 255-259`(_reap の close)の try/except は、`contextlib.suppress(OSError, ValueError)` で済む。
- `ed_jobs.py:1672-1683` の pkg_version で手書きしているキャッシュは、`functools.lru_cache` で済む。
- 環境変数から数を読む処理が `ed_jobs.py:50-53`(MODEL_IDLE_SEC)・`1275-1278`(END_TRIM)・`1281-1284`(JOIN_GAP)・`ed_speakers.py:55-59`(diar_threads)にあり、どれも `tx_engines.py:928-932` の `_env_int` と同じ形。`_env_num(name, default, lo, hi, cast)` を 1 つ作り、tx_engines に置けば、サーバーとワーカーの両方から使える。
- `ed_jobs.py:2333-2338` の replace_original は、`replace_original_multi(orig, a, b, [{"start": a, "end": b, "raw": text}])` と結果が同じ(conf が無いだけ)。
- `ed_jobs.py:1220` の squash の lambda は、1929 の `_squash` と同じ。
- 影響・リスク: ほぼ無い。ただし diar_threads には「0 以下なら CPU の数から決める」という決まりがあり、_env_int の lo=1 とは違うので、引数で合わせる(test_metrics の test_diar_threads(935-940))。WorkerClient の起動と強制終了は test_worker が試している。

##### 14. 認識の記録 recognition_run と record_rerun が同じ組み立てを写している(優先度: 低・削れる行数の目安: 約 8 行)
- 場所: `ed_jobs.py:1691-1701` と `1803-1814`
- 今: どちらも同じ項目を組み立てている: 疑似なら fake・エンジンとその版・model・device・language・settings{beam, vadMode, boost, wordSplit, dict}・at・post。ただ、エンジンの版の取り方を try で包んでいるのは record_rerun だけで、recognition_run は包んでいない。
- 案: `_run_base(spec, device)` を作る。recognition_run はそこに glossaryChars・promptChars・context・audioSec・wallSec・vad を足し、record_rerun は kind・range・replaced・autoDict を足す。
- 理由: 記録の項目を増やすとき(例: 後処理の設定)に、片方だけに足してしまう漏れを防げる(dev/eval_* が runs を読んでいる)。
- 影響・リスク: JSON の鍵の並び順が変わる(読む側は鍵の名前で読むので影響は無い)。recognition_run でも、エンジンの版を取るときの例外を握りつぶすようになる = 版が取れなくても文字起こしが失敗しなくなる(良い方向)。テスト: test_records・test_drill・test_whispercpp。

##### 15. 行ごとの印 make_flags が、毎行同じ下ごしらえをやり直している(優先度: 低・削れる行数の目安: 約 5 行。速くもなる)
- 場所:
  - `ed_jobs.py:780-792`: stock_phrase が、HALLUC_LINE の 17 個すべての `_letters(h)` を毎行計算し直す
  - `795-802`: repeats_in_line が、while の 1 周ごとに `_letters(text)` を計算し直す
  - `738-745`: latin_suspect が、毎行 terms から英字の語を並べ直す
  - `824`: 前の 5 行の `_letters(p)` を毎行計算する
  - `2544`: finish_range_lines が、毎行 `prompt_terms(spec)`(roster.fit)を呼ぶ
  - `1091`: transcribe_vad_fallback が、声の検出をやり直すたびに prompt_terms を呼ぶ
- 案:
  - HALLUC_LINE の `_letters` は、モジュールを読み込むときに 1 回だけ計算する(`_HALLUC_KEYS`)
  - repeats_in_line は、先に `k = _letters(text)` を 1 回だけ計算する
  - prompt_terms はループの外に出す
  - latin_suspect の英字の語の並びは、terms ごとに `functools.lru_cache` で覚える(terms は tuple にする)
- 理由: 長い配信(数千行)や範囲の再認識で、同じ計算を数千回しなくて済む。
- 影響・リスク: 動きは同じ。ただ、テストが ed_state.HALLUC_LINE を差し替えていると、先に計算した値が古いままになる(要確認。今は差し替えていない見込み)。テスト: test_metrics(印)・test_whispercpp・test_roster。

#### 他のグループとの重複の疑い
- (疑い)16kHz・モノラルの音声を作る ffmpeg の引数が 5 か所にある: `ed_jobs.py:702-711`・`ed_learn.py:978-980, 1108-1109`(担当)と `ed_evalaudio.py:138`・`home/live_tx.py:40-42`(担当外)。`-protocol_whitelist file` を付けているのは ed_jobs と ed_learn だけ。ytt_core.tools に `audio_args(ff, src, dst, ss, dur, codec, af)` を作る候補。
- (疑い)creationflags(窓を出さない・優先度を下げる)の組み立てが `ed_jobs.py:136-149` と `ed_evalaudio.py:128-132`・`ed_ytcap.py:148` で同じ。`ytt_core.tools.no_window_flags` に low_priority の引数を足せば 1 つにできる。
- (疑い)フォルダの大きさを測る関数が 4 つある: `ed_learn.py:1120-1128` の `_dir_bytes`、`home/cleanup.py:45` の `_size`、`home/health.py:34` の `dir_size`、`ytt_core/datadir.py:111` の `_size`。
- (疑い)ジョブの一時 wav と job_errors と makedirs の組: `ed_alt.py:160-162`・`ed_misc.py:70-72`。指摘 2 の小道具をそのまま使える。
- (疑い)`job["warnings"] = list(job.get("warnings") or []) + [...]` が `ed_alt.py:206`・`ed_fill.py:252, 275`・`ed_relink.py:367`・`ed_ytcap.py:130` にもある(指摘 2)。
- (疑い)`ed_state.atomic_write(…json.dumps(…).encode("utf-8"))` が ed_alt・ed_evalaudio・ed_evalbatch・ed_media・ed_misc・ed_store(2)・ed_ytcap・serve.py にもある(指摘 10)。
- (疑い)load_settings を同じ要求の中で何度も呼ぶ所が、ed_relink(3 か所)・serve.py(2 か所)などにもある(指摘 6)。
- (疑い)名簿ファイル(hololive-roster.json)の読み方が 3 通りある: `roster.load`(stat でキャッシュ。担当外)、`ed_learn.py:622-634` の load_roster(毎回読み直す。形は roster.load の groups に asOf・note を足したもの)、`ed_jobs.py:1717-1730` の roster_hash(独自のキャッシュ)。roster.load がハッシュと asOf・note も持つようにすれば、1 回読むだけで済む。


### G7 editor-py-B(担当: src/editor/ の ed_store.py・ed_relink.py・ed_evalbatch.py・serve.py・ed_ytcap.py・ed_state.py・ed_misc.py・ed_drill.py・ed_alt.py・ed_evalaudio.py・pipeline_io.py・resolve_export.py・ed_retime.py・ed_fill.py・roster.py・ed_media.py、合計 約 8,300 行(wc -l))

#### 全体の傾向
- 段10 の分割と v0.57.2 の整理で、共通の小道具(write_doc・read_schema_json・file_stamp・alt_cached・GET_API/POST_API の表)はそろっている。ただ、あとから足した部品(ed_alt・ed_ytcap・ed_evalbatch・ed_evalaudio・ed_drill・ed_fill)が、同じ配管を部品ごとに書き直している。重なっているのは、付き物の JSON の書き込みと読み込み・文書ごとのキャッシュ・ジョブの表の走査・状態ファイルの読み書き・パスの正規化。
- ytt_core と ed_state に同じ働きの関数があるのに、使わずに書いている所が多い。対応は fsio.read_json_file・unlink_quiet・plain_int・union_spans・colors.norm_hex・httpsec.send_head。lint の基準 4(dup-helper)は関数名で見つけるので、名前の違う写しは数えられていない(ed_state.unlink_quiet・_flags・_ytcap_kill)。
- 全文書を走査する処理が 3 つある(一覧の要約・進行度・ドリル)。それぞれが別のキャッシュを持つので、更新された文書は最大 3 回 JSON として読まれる。
- 関数はどれも 150 行以下に収まっている。ただし次の 4 つは、入れ子が深いか分岐が多くて読みにくい。
  - alt_diffs(104 行)
  - eval_organize(65 行・入れ子 6 段)
  - _eb_tick_locked(89 行)
  - sanitize_pack_output(63 行)

#### 指摘

##### 1. 2 つ目のエンジン(ed_alt)と YouTube の字幕(ed_ytcap)の配管の写し(優先度: 高・削れる行数の目安: 約 40 行)
- 場所: 次の 5 組が同じ形をしている。
  - 断る理由の確認: `src/editor/ed_alt.py:88-106` の alt_spec と `src/editor/ed_ytcap.py:104-117` の ytcap_spec
  - 文字起こしの続きで足す: `ed_alt.py:199-208` の alt_after_transcribe と `ed_ytcap.py:121-132` の ytcap_after_transcribe
  - ロックの中で文書の存在を確かめて書く: `ed_alt.py:190-195` と `ed_ytcap.py:495-505`
  - 付き物の JSON を読む: `ed_alt.py:125-129` の read_alt と `ed_ytcap.py:479-483` の read_ytcap
  - 候補を作る: `ed_alt.py:406-430` の alt_suggest の頭と `ed_ytcap.py:515-536` の ytcap_suggest
- 今: どちらも次の処理を同じ形で持っている。
  - 断る理由の確認(評価用・評価用のフォルダ・文字なし・同じ文書で実行中)
  - 設定がオンなら add_job し、断られたら warnings、想定外は log
  - _save_lock の中で tx_path の存在を確かめ、compact な JSON を atomic_write して、キャッシュを pop する
  - 候補を作る流れ(evalSet なら空 → file_stamp → read → alt_cached(鍵 = stamp・updatedAt・行の数) → alt_spans_of → alt_skip → 上限で打ち切り)
- 案: ed_alt に、すでにある alt_cached・alt_spans_of・alt_skip と並べて、次の 3 つを足す。
  ```
  def side_guard(tid, kind, what, need_media=False): doc を読み、評価用・フォルダ・文字なし・tid_busy を確かめて返す
  def side_after(job, spec, tid, flag, make_spec, kind, label, quiet=()): 設定オンなら add_job、失敗は warnings へ
  def side_write(tid, path, body, cache, lock, gone_msg): ロック → 文書の存在の確認 → compact な JSON → キャッシュを pop
  ```
  あわせて、suggest の頭(stamp・read・alt_cached まで)を `side_items(tid, doc, path, read, cache, lock, diff)` にまとめる。
- 理由: 3 つ目の候補源(案 A1 の次)を足すときに、決まりの漏れを防げる。たとえば「評価用には出さない」「消された文書には書かない」の書き忘れ。
- 影響・リスク: 断る順番が今と違う。
  - alt: evalSet → 文字なし → check_source(動画が無ければ no_file) → 評価用のフォルダ
  - ytcap: evalSet → 評価用のフォルダ(abspath)→ 文字なし → 範囲
  - ytcap は動画が無くても動くので、need_media で分ける。断る文も部品ごとに渡す。
  - 条件が 2 つ重なったときに返す error の種類が変わることがある。
- テスト: test_alt.py と test_ytcap.py の次のケースが守っている(どちらも test_metrics から読む)。
  - test_refusals・test_doc_deleted_during_job・test_auto_alt / test_auto_ytcap
  - test_suggest_* ・test_eval_and_missing_file
  - 画面は e2e_alt.py。

##### 2. 文書ごとの「更新日時と大きさで覚える」キャッシュが 4 つある。全文書の走査が 3 系統あり、同じ文書を別々に読む(優先度: 高・削れる行数の目安: 約 35 行。あわせて速くなる)
- 場所:
  - `src/editor/ed_store.py:171-208`(transcript_summary と _summary_cache)
  - `ed_store.py:531, 961-976`(edit_summary と _edit_cache)・`ed_store.py:335-337`(消えた文書の分を捨てる)
  - `src/editor/ed_misc.py:277-323`(progress_stats と _prog_cache。自分で open と json.load・自分で捨てる)
  - `src/editor/ed_drill.py:44-45, 122-150`(drill_docs と _drill_cache。自分で open と json.load・自分で捨てる)
  - 汎用の形がすでにある: `src/editor/ed_alt.py:380-389`(alt_cached)
- 今: 4 か所とも、stat から鍵を作り、当たりならその値を返し、外れなら読んで計算して入れる。消えた tid の分を捨てる処理も、それぞれが書いている。
  - 一覧(/api/transcripts)・進行度(/api/progress)・ドリル(/api/drill/status。ed_evalbatch も使う)が、同じ文書を別々に JSON として読む。
  - 「校正済み・聞き取れない印なし」の行の判定(_good)と行の長さ(_dur)が 2 か所に別々にある: `ed_drill.py:56-57, 87-89` と `ed_misc.py:300-302`。
- 案: 次のように 1 つの道具にまとめる。
  ```
  def doc_cached(cache, lock, tid, compute, extra=()):   # ed_store。鍵 = file_stamp(tx_path) + extra
      key = ed_state.file_stamp(tx_path(tid)); return None if key is None else ed_alt.alt_cached(cache, lock, tid, key + extra, lambda: compute(_load_quiet(tid)))
  def prune_cache(cache, seen): ...                      # 消えた文書の分を捨てる(3 か所 → 1 か所)
  ```
  - 進行度に要る値(良い行の秒・行数・未校正の行・全体の秒)は、transcript_summary の要約に足す。そうすれば progress_stats は summaries() を足し合わせるだけになり、文書を読み直さない。
  - alt_cached は ed_state に移す(ed_ytcap・ed_store も使うため)。
- 理由:
  - 保守性: キャッシュの決まり(鍵・ロック・捨て方)が 1 か所になる。_summary_cache にはロックが無く、_drill_cache にはある、というようにばらついている。
  - 性能: 保存のたびに、変わった文書の JSON の読み込みが 3 回から 1〜2 回に減る。数千行の文書では効く。
- 影響・リスク: テストがキャッシュの名前を直接 clear している。辞書の名前(_summary_cache・_drill_cache)は残し、辞書を道具に渡す形にする。
  - S._summary_cache: test_edit.py の 907 行と 913 行
  - DR._drill_cache: test_drill.py の 38 行・test_autodiar.py の 71 行と 81 行
- テスト:
  - test_backend.py の test_summary_cache_and_ranges_without_rereading
  - test_drill.py・test_autodiar.py・test_evalbatch.py
  - /api/progress は e2e_eval_set.py と e2e_folder_marker_range.py だけが通る(単体のテストは無い)。

##### 3. /media の Range の配信がスタジオの写しになっている。zip の応答も自分で見出しを書いている(優先度: 高・削れる行数の目安: 編集で約 40 行、スタジオも入れると約 55 行)
- 場所:
  - `src/editor/serve.py:475-518`(_media)
  - `src/studio/serve.py:227-263`(_media。Range の解釈とコピーの繰り返しが一字一句同じ)
  - `src/editor/serve.py:348-360`(_send_zip)
  - 使える道具: `src/ytt_core/httpsec.py:39-56`(send_head・send)
- 今:
  - 編集の _media は、send_header を 1 行ずつ書いている。スタジオはすでに httpsec.send_head を使っている。
  - _send_zip は、no-store・nosniff を send_head と同じ形で書き写している。
- 案: ytt_core.httpsec に配信の関数を 1 つ置き、両方のツールから呼ぶ。
  ```
  def send_file(h, path, ctype, extra=None):   # ytt_core.httpsec。Range(bytes=a-b / -n / 416)・HEAD・64KB ずつのコピー
      size = os.path.getsize(path); a, b, code = _range(h.headers.get("Range"), size)
      if code == 416: return h._send(416, b"", extra={"Content-Range": "bytes */%d" % size})
      send_head(h, code, ctype, b - a + 1, {"Accept-Ranges": "bytes", **cr, **(extra or {})}); _copy(path, a, b, h)
  ```
  - _send_zip は `httpsec.send_head(self, 200, "application/zip", size, dict(extra, **{"Content-Disposition": ...}))` と copyfileobj の 2 行にする。
  - あわせて serve.py の残りの定型も短くする。
    - `_put`・`_delete` の `(urllib.parse.parse_qs(u.query).get("id") or [""])[0]` が 3 回ある(605・612・625 行)→ `_qid(u)` にする。
    - main の「すでに起動 → ブラウザで開く」が 2 回ある(838-843・847-851 行)→ 1 つの関数にまとめる。
- 理由: Range の端の扱いを 1 か所で直せる。端の扱いとは、416・末尾の n バイト・大きさを超える終わり。スタジオと編集で食い違わなくなる。
- 影響・リスク: 見出しの順番が変わるだけで、中身は同じ(スタジオはもうこの順番)。
  - 416 は今どおり handler._send を通す。入口の mount.py が _send を上書きして CSP を足しているため。
  - 200/206 は今も _send を通っていない。この形は変えない。
- テスト: 編集側の Range は単体で守られていない。test_edit.py の 427 行と 1125 行は、/media の 200 しか見ていない。まとめる前に test_edit に 206・416・HEAD を足しておく。スタジオは src/studio/tests/test_api.py の 194 行に Range のテストがある。

##### 4. 「動いているジョブ」を調べる処理が 10 か所に散らばっている(優先度: 中・削れる行数の目安: 約 15 行)
- 場所:
  - `src/editor/ed_relink.py:144-148`(_doc_busy)・`ed_relink.py:609-612`(_path_busy)
  - `src/editor/ed_drill.py:430-432`(_busy_tids)
  - `src/editor/ed_misc.py:366-372`(_done_and_active)
  - `src/editor/ed_evalbatch.py:126-129`(_eb_jobs)・`ed_evalbatch.py:786-788`
  - `src/editor/ed_evalaudio.py:114-125`(_busy_reason。ロックを取らない)
  - `src/editor/serve.py:805-808`(busy)・`serve.py:813-814`(finish)
- 今: どこも `with ed_jobs._jobs_lock:` で表を見る。「状態が ACTIVE_STATES」かつ「spec の tid / tid / intoDoc / sourcePath が…」の形を、それぞれ少しずつ違う書き方で持っている。
- 案: ed_jobs に 2 つの道具を置き、各所は 1 行の内包にする。
  ```
  def active_jobs(lock=True): with _jobs_lock(lock なら): return [j for j in _jobs.values() if j["state"] in ACTIVE_STATES]
  def job_tid(j): sp = j.get("spec") or {}; return str(sp.get("tid") or j.get("tid") or "")
  ```
  - たとえば _busy_tids は `{job_tid(j) for j in ed_jobs.active_jobs()}` になる。
  - ed_evalaudio は SLOTS の中から呼ぶので、lock=False で呼ぶ。
- 理由:
  - 「処理中の文書」の定義が部品ごとに微妙に違う。_doc_busy は intoDoc を数え、_busy_tids は数えない。1 か所に集めると、この違いが見える。
  - ロックの取り方も 1 か所でそろう。
- 影響・リスク: ed_jobs.py は担当外(G6 の想定)なので、置き場所は相手と相談する。intoDoc を数えるかどうかの違いは、意図したものか要確認。
- テスト:
  - test_normalize30.py(_doc_busy)・test_evalbatch.py(_busy_tids)・test_drill.py
  - test_edit.py の test_organize_skips_busy_and_name_clash

##### 5. パスの正規化 normcase(abspath(...)) が 24 か所ある(優先度: 中・削れる行数の目安: 約 10 行。長い式がなくなる)
- 場所: すでに道具がある: `src/editor/ed_evalbatch.py:84-85`(eb_key)。同じ式を直書きしている所:
  - ed_misc.py: 190・196・360・370・377・381・384・405 行
  - ed_relink.py: 130-138・304・775・830・959・996・1034 行
  - ed_store.py: 997・1036・1039 行
  - ed_evalaudio.py: 64・170 行
  - ed_drill.py: 331 行
  - normcase だけで abspath を付けない所もある: `ed_relink.py:610-612, 792, 925, 936`
- 今: 同じ動画かを比べる鍵を、その場で作っている。
  - `ed_misc.scan_folder` の 358-362 行は、すぐ下の scan_common(399-407 行)と同じ処理の写し。
- 案:
  - eb_key を `ed_state.path_key(p)`(str(p or "") を受ける)に移し、全部それにする。
  - scan_folder は `scan_common([f["path"] for f in found])` の結果を写す形にする。
- 理由:
  - 読みやすさ。
  - 正規化の揺れ(abspath の有無)をなくせる。今は比べる 2 つがどちらも絶対パスなので食い違わないが、片方が相対パスになると黙って一致しなくなる。
- 影響・リスク: abspath を足す所は、相対パスが来たときの結果が変わりうる。今の呼び出し元は絶対パスしか渡していない(要確認)。
- テスト:
  - test_edit.py(付け替え・評価用のフォルダ)・test_backend.py(test_summary_cache_and_ranges_without_rereading・scan_common)
  - test_evalbatch.py・test_evalaudio.py

##### 6. ed_evalbatch の状態ファイルの「読む → 確かめる → 書く」の定型が 12 か所ある(優先度: 中・削れる行数の目安: 約 20 行)
- 場所:
  - `src/editor/ed_evalbatch.py` で `with _eb_state_lock:` が 12 回(183・197・287・294・395・421・439・465・603・613・650・688 行)、_eb_write が 13 回
  - 項目の既定の dict の写し: 358 行と 443 行
  - 理由の数え上げ: 585 行と 591 行
  - json の往復による深い写し: 412 行
  - _eb_now: 482-483 行(ed_drill._now_ms と同じ)
- 今:
  - 毎回 `st = eb_read()` → `if not st["enabled"]: return …` → 書き換え → `_eb_write(st)` の順に書いている。
  - `{"src": p, "tries": 0, "fails": 0, "failJobs": [], "done": False}` を 2 か所で作っている。
  - 理由の数を `reasons[k] = reasons.get(k, 0) + 1` で数えている。
- 案: 次の 3 つに置き換える。
  ```
  @contextlib.contextmanager
  def _eb_edit():   # ロック → 読む → (中で書き換え)→ 変わっていれば書く(_eb_tick_locked の before 比べと同じ)
      with _eb_state_lock: st = eb_read(); before = json.dumps(st, sort_keys=True); yield st; ... _eb_write(st) if 変わった
  def _eb_item(st, path): return st["items"].setdefault(eb_key(path), {...})
  ```
  - 理由の数は collections.Counter にする。
  - 412 行の深い写しは copy.deepcopy にする。
- 理由: 長い _eb_tick_locked(389-477 行)と _eb_redo_pass の本筋が見えやすくなる。
- 影響・リスク: 「変わったときだけ書く」にすると、何も変わらなかった回に状態ファイルの updatedAt が進まなくなる。この値を見ているテスト・画面が無いかは要確認。今と同じにしたいなら、常に書く形のままにする。
- テスト: test_evalbatch.py(28 件)・test_autodiar.py

##### 7. sanitize_pack_output の 63 行を表で書ける(優先度: 中・削れる行数の目安: 約 20 行)
- 場所:
  - `src/editor/ed_store.py:858-930`
  - 同じ値の決まりが担当外にもある: `src/editor/ed_learn.py:36-43` の SETTINGS_PATCH_KEYS(packLoudness・packVolume・packFps・packSize)
- 今: 鍵ごとに if で検査し、だめなら return None としている。この形が 12 回並ぶ。
  - 音量の候補 (0, -11, -14, -16, -18) は、PACK_OUTPUT_LOUDNESS と ed_learn の 2 か所に書かれている。
  - 1〜200 の範囲と大きさの 2 択も同じく 2 か所にある。
- 案: 必須の鍵と任意の鍵を、表(鍵 → 検査)にする。
  ```
  _PACK_REQ = {"fps": _fps_ok, "size": lambda v: v in PACK_SIZES, "wrap": lambda v: ed_state.plain_int(v) is not None and 0 <= v <= 40, **{k: _is_bool for k in BOOL_KEYS}}
  _PACK_OPT = {"streamer": lambda v: _pack_text(v, 200), "loudness": ..., "volume": ...}
  for k, ok in _PACK_REQ.items(): if not ok(o.get(k)): return None ...
  ```
  - advanced と speakerStyles だけは関数のまま残す。
  - 音量・大きさの候補は、ed_learn と共有の定数にする。
- 理由: 項目を足すのが 1 行で済む。画面・設定・記録で値の決まりが食い違わなくなる。
- 影響・リスク: 動きは同じにできる。bool を int として受けない点に注意: plain_int を使い、loudness は bool を先に断る。
- テスト:
  - test_voices.py(sanitize_pack_output)
  - e2e_edit_pack.py(output の記録と outputDiff)

##### 8. pipeline_io の上書きの書き込みと、ポートの記録の薄い包み(優先度: 中・削れる行数の目安: 約 25 行)
- 場所:
  - `src/editor/pipeline_io.py:250-260`(save_beside の上書き)
  - `pipeline_io.py:273-311`(runtime_dir・write_runtime・remove_runtime・ping・siblings の包み)
  - `pipeline_io.py:155-157` と `176-178`(media の dict の写し)
- 今:
  - 上書きの所で temp_in → replace_retry、失敗したら一時ファイルを手で消す、を書いている。これは `fsio.atomic_write(p, data, fsync_required=True)` の中身そのもの。
  - ポートの記録の包みは、docstring だけを持って runtime を呼んでいる。
- 案:
  - 上書きの 9 行を `fsio.atomic_write(p, data, fsync_required=True)` の 1 行にする。
  - `runtime_dir = runtime.runtime_dir` のように別名で公開する。名前は残す。read_runtime_entries と ping は形が違うので関数のまま。
  - media の dict は `_media_of(doc)` にまとめる。
- 理由: 書き込みの決まり(fsync・ロックのやり直し)を ytt_core の 1 か所に寄せられる。
- 影響・リスク:
  - atomic_write はフォルダの makedirs もするが、フォルダはもうあるので動きは同じ。
  - 別名にすると引数の名前が変わる(tool_id → tool・self_id → self_tool)。キーワードで呼ぶ所が無いかは要確認。今見た範囲では位置で呼んでいて、self_path だけ同じ名前。
  - pipeline_io を変えるので、dev/tests/test_resolve_pack_contract.py を単独で流す。
- テスト:
  - test_backend.py(save_beside・read_runtime_entries・export_file)
  - dev/tests/test_resolve_pack_contract.py
  - e2e_ui_handoff.py

##### 9. relink_path と relink_folder の検査の共通部分(優先度: 中・削れる行数の目安: 約 12 行)
- 場所:
  - `src/editor/ed_relink.py:52-79`(relink_path)・`ed_relink.py:433-458`(relink_folder)
  - 同じ形の文字列の検査: `ed_relink.py:527-530`(_eval_dirs_ok)
  - 同じ形の「フォルダの有無を 1 回だけ調べる」: `ed_store.py:290-318`(_files_state)と `ed_relink.py:409-430`(relink_missing)
- 今: 2 つの関数が、次の検査を同じ順番で別々に書いている。
  - strip → 空・長さ・制御文字 → ネットワーク → isabs → abspath → リモートのドライブ → realpath → もう一度ネットワークとリモート → 「:」 → 作業データの中
- 案: 「ファイルか・フォルダか」の検査だけを関数で渡す。
  ```
  def _local_real(raw, what, example, missing, extra_check):   # 順番は今の relink_path と同じ(1 回目 → realpath → 2 回目)
      ...; for resolved in (False, True): …ネットワーク・リモート・「:」・extra_check(p)・_inside(DATA_DIR)
  ```
  - _files_state と relink_missing は、`_exists_by_folder(sp, dirs)` を共有する。
- 理由: 安全の検査が 2 か所にあると、片方だけ直す事故が起きる。AGENTS.md も「パスは許可したフォルダの中だけ」と書いている。
- 影響・リスク: **セキュリティの検査の順番を変えない**こと。
  - relink_folder は今、1 回目に「:」と作業データの中を見ていない。足すと検査が厳しくなる側に動く(ファイルには触らない)。
  - 作業データの中にあって、かつ存在しないフォルダは、返す error が no_dir から bad_path に入れ替わる。この端のケースの error を変えたくなければ、フォルダのときは今の順番にする引数を付ける。
- テスト: test_edit.py の test_relink_path_rejects・test_relink_path_windows_forms・relink_folder のケース・test_check_and_relink

##### 10. eval_organize の深い入れ子と、番号の割り振りの写し(優先度: 中・削れる行数の目安: 約 15 行。読みやすさが主)
- 場所:
  - `src/editor/ed_relink.py:887-951`(eval_organize。903-944 行が for の中の for の中の for の中の try。中に def mtime がある)
  - `ed_relink.py:698-710`(_eval_next_name)
  - `ed_relink.py:782-820`(_eval_staging_pass。入れ子 5 段)
  - `ed_relink.py:793, 796, 997`(結果の dict の `_only` を引数代わりにしている)
- 今:
  - 「この名前の形で使われている番号を集めて、空いている番号を振る」処理が、_eval_next_name と eval_organize の 2 か所にある。
  - _eval_staging_pass は、res["_only"] という結果の dict の鍵で動きを切り替えている。
  - eval_settle と eval_organize の両方が `_evalorg_last.clear(); _evalorg_last.update(res)` を書いている(947-948・983-984 行)。
- 案: 次のように分ける。
  - フォルダ 1 つの名前そろえを `_eval_number_folder(folder, files, by_path, res)` に出す。
  - 番号の集め方を `_eval_used_numbers(prefix, names)` にして 2 か所で使う。
  - `_eval_staging_pass(dirs, by_path, res, only=False)` と、引数ではっきり渡す。
- 理由: 整理は動画の名前を変える処理なので、読み違いが事故につながる。今は名前の重なり・処理中・失敗時に元へ戻す処理が 1 か所に詰まっていて追いにくい。
- 影響・リスク: 動きは同じにできる。mtime の並べ方(番号なし → 古い順 → 名前)を変えないこと。
- テスト: test_edit.py の次のケースが厚く守っている。
  - test_organize_names_numbers_and_relinks・_skips_busy_and_name_clash・_rolls_back_when_relink_fails
  - test_staging_*(4 件)・test_intake_*(4 件)・test_settle_intakes_in_background

##### 11. ytt_core と ed_state の小道具を使っていない所(優先度: 低〜中・削れる行数の目安: 約 25 行)
- 場所と案:
  - `src/editor/ed_store.py:624-639` の read_edit
    - 今: max+1 バイトを読み、utf-8-sig で decode し、NaN を断っている。これは `fsio.read_json_file(path, MAX_EDIT_BYTES)` と同じ。
    - 案: `except FileNotFoundError: return None, False` と `except (OSError, ValueError): return None, True` の形にして、約 5 行減らす。
  - `src/editor/ed_state.py:147-152` の unlink_quiet と 301-305 の clear_mark
    - 今: unlink_quiet は fsio.unlink_quiet の写し。lint の基準 4 は名前 `_unlink_quiet` しか見ないので、数えられていない。
    - 案: `unlink_quiet = _fsio.unlink_quiet` にし、clear_mark は `unlink_quiet(RUN_MARK)` にする。
  - .part や古いファイルを消す try/except の写し
    - 場所: `ed_relink.py:640-645`・`ed_evalaudio.py:155-159, 245-250`・`ed_store.py:393-397`・`ed_ytcap.py:356-366`
    - 案: unlink_quiet にする。
  - `src/editor/ed_misc.py:159-164` の _read_json_file
    - 今: 大きさの上限が無い。使っているのは `ed_store.py:241`(スタジオの data.json)・`ed_media.py:133`・`ed_misc.py:170, 216`。
    - 案: `fsio.read_json_file(path, 上限)` にする。fsio の docstring にも「他のツールが作ったファイルはこれで読む」とある。
  - bool と int を分ける判定(`isinstance(x, bool) or not isinstance(x, int)`)
    - 場所: `ed_store.py:105, 512, 621, 635, 642, 824, 883, 902, 938`・`ed_relink.py:160`
    - 案: すでにある `ed_state.plain_int` を使う。
  - `ed_state.py:124-125` の _reject_json_constant
    - 今: fsio._reject_constant の写し。
- 理由: ytt_core を正本にする方針(AGENTS.md・code-quality の基準 4)に合わせる。lint の網をすり抜けている写しを消せる。
- 影響・リスク:
  - _read_json_file に上限を付けると、上限を超える data.json は「読めない」扱いになる。上限は大きめにする(例: 64MB)。これは動きの変更。
  - read_edit はエラーの分類を今と同じにできる。UnicodeDecodeError は ValueError の仲間なので、同じ except に入る。
  - test_backend.py の 415 行が `S._read_json_file` を直接呼んでいるので、名前は残す。
- テスト:
  - test_edit.py(カットの保存・壊れた edit.json)・test_backend.py・test_evalaudio.py・test_ytcap.py(prune)
  - e2e_edit_cut.py(409・壊れたカット)

##### 12. 子プロセス・時刻・環境変数・ジョブの注意の小さな写し(優先度: 低・削れる行数の目安: 約 15 行)
- 場所と案:
  - 窓を出さず、優先度を下げるフラグが 2 つ同じ
    - 場所: `src/editor/ed_ytcap.py:145-148` の _ytcap_flags と `ed_evalaudio.py:128-132` の _flags
    - 案: tools.no_window_flags に low_priority 引数を足す。これは ytt_core の変更。
  - `ed_ytcap.py:151-163` の _ytcap_kill
    - 今: taskkill /T の部分以外は tools.kill_quiet と同じ。
  - 「off なら止める」の判定が 4 か所
    - 場所: `ed_evalaudio.py:339`・`ed_evalbatch.py:855`・`ed_relink.py:226`(担当外の ed_speakers.py:881 にもある)
    - 案: `ed_state.env_off(name)` にまとめる。
  - `int(time.time() * 1000)` が担当の中だけで 37 回
    - 同じ働きの関数が `ed_drill.py:48`(_now_ms)と `ed_evalbatch.py:482`(_eb_now)の 2 つある。
    - 案: `ed_state.now_ms()` を 1 つにする。
  - `job["warnings"] = list(job.get("warnings") or []) + [...]` が 5 回
    - 場所: `ed_alt.py:206`・`ed_ytcap.py:130`・`ed_fill.py:252, 275`・`ed_relink.py:367`
    - 案: `ed_jobs.add_warning(job, msg)` にする。
  - `ed_fill.py:243-256` の fill_after_rows
    - 今: phase を、例外のときと正常のときに 2 回戻している。
    - 案: fill_agree_doc(268-278 行)と同じ try/finally にする。
- 理由: 決まり(優先度・窓・時刻の単位)を 1 か所で変えられる。
- 影響・リスク:
  - warnings の「新しい list に付け直す」形は、/api/jobs が JSON にしている最中のリストを書き換えない意図かもしれない(要確認)。add_warning も同じ「付け直す」形にしておけば安全。
  - フラグは ytt_core の変更なので、ほかのツールのテストも流す。
- テスト:
  - test_evalaudio.py の test_ffmpeg_flags_and_command
  - test_ytcap.py の test_cancel_and_timeout
  - test_fill.py・test_evalbatch.py・test_normalize30.py

##### 13. 残す区間の検査と書き込みの写し(優先度: 低・削れる行数の目安: 約 15 行)
- 場所:
  - `src/editor/ed_store.py:600-609`(sanitize_draft の keepsSec の検査)と `ed_store.py:745-756`(keeps_arg)
  - `ed_store.py:734-742`(edit_keeps_sec)と `ed_state.py:176-184`(union_spans)
  - edit.json の書き込みの写し: `ed_store.py:848-851` と `957`
  - `src/editor/resolve_export.py:180, 221`(`any(is_kept(g) …)` が 2 回)
  - `resolve_export.py:182-204, 219-242`(mkdtemp と finally の rmtree)
- 今: 区間の並び([a, b] の形・時刻の順・重ならない)を、2 か所で同じように検査している。違いは 2 つだけ。
  - だめなときの扱い: None を返すか、例外を出すか
  - 1e-6 の許し
- 案: 次のように寄せる。
  - `_parse_keeps(v, tol) -> list | None` を作り、keeps_arg は None なら raise、sanitize_draft は None ならそのまま None を返す。
  - edit_keeps_sec は `ed_state.union_spans((c["in"], c["out"]) for c in edit["clips"])` にする。
  - `write_edit(tid, d)` を作り(write_doc と同じ形)、record_pack も上限の検査を通す。
  - resolve_export の 2 か所は `tempfile.TemporaryDirectory(prefix=…, ignore_cleanup_errors=True)`(3.10 で使える)と `_has_kept(doc)` にする。
- 理由: カットの区間の決まりを 1 か所にできる。
- 影響・リスク:
  - union_spans は並べ替えと「a <= 前の終わり」で判定し、今の edit_keeps_sec は +1e-9 を許している。clips は 3 桁に丸めて並んでいるので、結果は変わらないはず(要確認)。
  - record_pack に上限を付けると、巨大な edit.json は 413 で断るようになる(動きの変更)。
  - resolve_export を変えるので、dev/tests/test_resolve_pack_contract.py を単独で流す。
- テスト:
  - test_edit.py(カットの保存・draft)・test_resolve_export.py
  - e2e_edit_cut.py・e2e_edit_pack.py

##### 14. 字幕の色の 16 進の検査が 3 つ、最初の認識の記録の探し方が 3 つある(優先度: 低・削れる行数の目安: 約 12 行)
- 場所:
  - 色: `src/editor/ed_store.py:52-58`(_SUB_HEX_RE・_sub_color)・`src/editor/resolve_export.py:245-261`(_SUB_COLOR_RE)・正本は `src/ytt_core/colors.py:74-77`(norm_hex)
  - 最初の認識: `src/editor/ed_alt.py:79-85`(alt_first_run)・`src/editor/ed_retime.py:269-275`(retime_engine)・`src/editor/ed_evalbatch.py:496-497, 831-832`
  - 使われない分岐: `ed_retime.py:93, 292`(RETIME_END_SKIP = ())
- 今:
  - 「#? と 16 進 6 桁を、大文字の #RRGGBB にする」処理が 3 か所にある。
  - 「recognition.runs のうち kind の無い最初の記録」を探す処理も 3 か所にある。
  - RETIME_END_SKIP は空のタプルなので end_ok は常に True で、retime_candidates の end_ok=False の道には届かない。
- 案:
  - 色は `_sub_color = lambda v: colors.norm_hex(v) if isinstance(v, str) else None` にし、resolve_export も norm_hex を使う。
  - retime_engine は `str((ed_alt.alt_first_run(doc) or {}).get("engine") or "faster-whisper")` にする。ed_evalbatch の 2 か所も alt_first_run を使う。
  - RETIME_END_SKIP は、計測の記録(コメント)を残したまま、効かない引数として印を付けるか消すかを決める。
- 理由: 同じ規則を 3 回書かないで済む。色は Lua に入る値なので、検査は正本 1 つが安全。
- 影響・リスク:
  - norm_hex は str() で文字列に直すので、isinstance の確認を残さないと数値も通ってしまう。
  - resolve_export が ytt_core を読めるのは、pipeline_io か serve が sys.path を足したあとだけ。単独で import するテストがあるので、import は関数の中で行う(要確認)。test_resolve_pack_contract.py も流す。
  - RETIME_END_SKIP を消すのは、計画で「測れたら決め直す」とされている値なので、ユーザーに確認する。
- テスト:
  - test_resolve_export.py(speaker_sub_colors)
  - test_retime.py(retime_engine)
  - test_alt.py・test_evalbatch.py
  - dev/tests/test_resolve_pack_contract.py

##### 15. 文字の寄せ方の写しと、名簿の表記ゆれの O(n²)(優先度: 低・削れる行数の目安: 約 10 行。性能は小さく良くなる)
- 場所:
  - カタカナ → ひらがなの変換: `src/editor/roster.py:26-30`(fold)・`roster.py:194-199`(_hira・_kata)・`src/editor/ed_alt.py:212-222`(alt_fold の中)・`src/editor/ed_fill.py:176-178`(fill_kana は roster の内部の関数 _hira を使っている)
  - 「NFKC にして、文字と数字だけ残す」処理: `ed_fill.py:52-54`(fill_norm)・`src/editor/ed_retime.py:43-45`(subread_chars は len(fill_norm) と同じ)・`roster.py:169-170`(leak_only)
  - 名簿の表記ゆれ: `roster.py:240`
- 今:
  - 同じ変換を 4〜5 か所で書いている。
  - variant_pairs は、別の綴りを 1 つ作るたびに `any(v == a for mm in members.values() for a in mm.get("aliases") or [])` で全員の呼び名をなめている(人数 × 呼び名 × 綴りの数)。
- 案:
  - roster に `to_hira(s)` と `letters(s)`(NFKC + LN)を公開し、ed_alt・ed_fill・ed_retime はそれを使う。ed_retime はすでに ed_alt.alt_fold を使っている。
  - variant_pairs は、ループの前に `all_aliases = {a for mm in members.values() for a in mm.get("aliases") or []}` を 1 回作って in で引く。
- 理由: 寄せ方の違いが、比べ方の違いとして混ざりにくくなる。variant_pairs は文字起こしのたびに ed_jobs.dict_pairs から呼ばれる。
- 影響・リスク:
  - roster.fold は区切りの文字も捨てる。alt_fold は「ー〜」と記号を捨てる。寄せ方が完全に同じではないので、共有するのはカタカナ → ひらがなと LN の判定だけにする。
  - variant_pairs の結果は同じ。
- テスト:
  - test_roster.py(variant_pairs)・test_fill.py・test_retime.py(subread_cases.json で画面と同じ例を固定)・test_alt.py

#### 他のグループとの重複の疑い
- **確認済み**: `src/studio/serve.py:227-263` の _media は、編集の `src/editor/serve.py:475-518` と、Range の解釈とコピーの繰り返しが同じ(指摘 3)。スタジオの担当と一緒に ytt_core.httpsec へ寄せるのがよい。
- 疑い: `src/cut2resolve/serve.py:672-681` の _send が、httpsec.send_head と同じ見出しを手で書いている(Referrer-Policy の 1 行だけ多い)。
- 疑い: `src/editor/ed_learn.py:26-32` の load_settings にはキャッシュが無い。eval_dirs と in_eval_dir が保存・GET /api/transcript・付け替えのたびに呼ぶので、そのたびに settings.json を読み直し、ドライブの種類を ctypes で聞いている。担当の中では、`ed_relink._eval_mark_docs`(1008-1021 行)が文書ごとに dirs を渡さずに呼んでいる。
- 疑い: `src/editor/ed_learn.py:36-43` の SETTINGS_PATCH_KEYS(packLoudness・packVolume・packFps・packSize)が、ed_store の sanitize_pack_output と同じ値の決まりを持っている(指摘 7)。
- 疑い: `src/editor/ed_jobs.py:115-118` の tid_busy と、担当の中の _doc_busy・_busy_tids など(指摘 4)。ed_jobs と ed_speakers にも `job["warnings"] = list(...) + [...]` が 4 か所あり、`ed_speakers.py:881` にも env の off 判定がある(指摘 12)。
- 疑い: カタカナ → ひらがなの変換が、`src/editor/ed_learn.py:126, 670`・`src/cut2resolve/resolve_textplus.py:242`・`src/ytt_core/colors.py:91-96`(_norm_text。roster.fold とほぼ同じで、区切りの文字の集合だけ違う)にもある(指摘 15)。
- 疑い: `src/cut2resolve/cut2resolve_core.py:874` の read_json_file と `src/home/live_excite_worker.py:238` の read_json が、fsio.read_json_file と同じ働きをしている。
- 参考(直せない写し): _load_core が `src/editor/serve.py:84-94`・`src/editor/pipeline_io.py:19-26`・`src/studio/common.py:25`・`src/cut2resolve/serve.py:59` の 4 か所にある。ytt_core を探すための関数なので、ytt_core には置けない。


### G8 editor-js(担当: src/editor/app.js 1376・cut.js 1203・app-rows.js 1060・app-tools.js 729・app-jobs.js 642・app-learn.js 598・pack-tab.js 552・app-core.js 470・app-list.js 271、合計 約 6,900 行)

#### 全体の傾向
- 段10 でファイルを役割ごとに分け、v0.58.1 で app-core.js に小道具(kickJobs・saveFirst・savedFor・showConflict・setUrlParam など)を集めたが、まだ「同じ形を手で書く」所が多い: fetch の包み 4 本・設定の「送ったキーだけ直す」保存 6 か所・ボタンの「押せなくして finally で戻す」約 22 か所・「保存し終えたか/競合/別の文書へ移ったか」の判定 8 か所。どれも 3〜10 行の写しなので lint の重複検査には当たらない。
- ui-kit.js は index.html:8 で head に同期で読み込まれ、`UIKit.dialog.confirm`・`UIKit.timebox`・`UIKit.keybar`・`UIKit.confirmTwice`・`UIKit.drawer` は確認なしで呼んでいる(= ui-kit が無いと画面はすでに動かない)のに、`window.UIKit &&` の確認が 49 か所と、到達しない代わりの経路(toast の直書き・visibilitychange・portalApi など)が残る。cut.js・pack-tab.js の `h.xxx ?`(host の関数があるか)25 か所も同じ。
- innerHTML の組み立て(90 か所)は、文字列は esc( 151 回で守れている(穴は見つからなかった)が「付け忘れない」に頼る形で、サーバーの数値は素のまま入れている。
- 長い関数は pack-tab.js の renderNow(約 90 行)・app-rows.js の openDoc(約 57 行)・app-jobs.js の pollJobs(約 50 行)。中はコメントで節に分かれているので、そのまま分けやすい。
- テストの注意: `tests/test_document_save.cjs` は saveDoc・openDoc・readMark などを「関数の名前で抜き出して」別の環境(window に UIKit が無い・CUT/PACK は null)で動かす。これらの中から新しい小道具を呼ぶように直すときは、harness(context の stub・fnSource)も一緒に直す。

#### 指摘

##### 1. fetch の包みが 4 本(api・apiBlob・c2rApi・portalApi)(優先度: 高・削れる行数の目安: 約 20 行)
- 場所: `src/editor/app-core.js:85-94`(api)・`src/editor/app-core.js:97-103`(apiBlob)・`src/editor/app-tools.js:597-606`(c2rApi)・`src/editor/app-list.js:128-136`(portalApi)
- 今: 4 本がそれぞれ init(cache・method・Content-Type・合言葉)・fetch の失敗の文・JSON の読み・エラーの形を手で書いている。違うのは URL の作り方・つながらないときの文・apiBlob は Response を返す、だけ。
- 案: 中身を 1 本にし、4 本は URL と文を渡す 1 行に。
  ```js
  async function request(url, { method, body, keepalive, raw, offline = NO_SERVER } = {}){
    const m = method || (body === undefined ? 'GET' : 'POST'), headers = { ...(body !== undefined && { 'Content-Type': 'application/json' }), ...(TOKEN && !/^(GET|HEAD)$/.test(m) && { 'X-YTT-Token': TOKEN }) };
    let r; try { r = await fetch(url, { cache: 'no-store', method: m, headers, keepalive: !!keepalive, body: body === undefined ? undefined : JSON.stringify(body) }); } catch { throw Object.assign(new Error(offline), { code: 'network' }); }
    if (raw && r.ok) return r; const j = await r.json().catch(() => ({})); if (!r.ok) throw httpError(r, j); return j; }
  // api = (p, o) => request(apiUrl(p), o) / apiBlob = (p, b) => request(apiUrl(p), { body: b, raw: true }) / c2rApi・portalApi は URL と offline だけ
  ```
- 理由: 合言葉を付ける条件・エラーの形(message・code・status・data)が 1 か所になる(セキュリティの決まり「書き込み系に合言葉」を 1 か所で守れる)。API の URL は今までどおり apiUrl()・c2rUrl() で作るので、前提の「1 か所の関数で作る」は崩れない。
- 影響・リスク: c2rApi はサーバーが message を返さないとき「cut2resolve のエラー(500)」・code の既定 'http'(読んでいる所は無い)→ httpError に寄せると文が「エラー 500」に変わる(必要なら offline と同じく文を渡す)。c2rWait(app-tools.js:614)が見る code 'network' は request が付ける。テスト: 全 e2e が api を通る・e2e_edit_pack.py(c2rApi・zip の apiBlob・まとめて実行の portalApi)・e2e_edit_cut.py(たたき台の c2rApi)。test_document_save.cjs は api を差し替えるので影響なし。

##### 2. ui-kit が必須なのに残る `window.UIKit &&` と到達しない代わりの経路(優先度: 高・削れる行数の目安: 約 25 行)
- 場所: `window.UIKit` 49 か所(app.js 19・app-core.js 8・cut.js 7・app-list.js 6・pack-tab.js 5 など)。代わりの経路の例: `src/editor/app-core.js:28-30`(toast の #toast 直書き)・`src/editor/app.js:98`(onLeave の visibilitychange = AGENTS の「visibilitychange を直接使わない」に反する経路)・`src/editor/app.js:143,153-154,798`(ago・runLabelOf・stepLabelOf・keyText の代わり)・`src/editor/app.js:801-820,845-857` と `src/editor/app-rows.js:901,903,946`(KM・editPlaybackKeys が null のとき)・`src/editor/cut.js:245-249`(confirmReplace の 2 本の枝。h.confirm も中身は UIKit.dialog.confirm = `src/editor/app-tools.js:677-679`)・`src/editor/cut.js:1070`(#cutForce)・`src/editor/app-list.js:103,199-200,226-227`(UIKit.autorun が無いときの portalApi)・`src/editor/pack-tab.js:158,343,443-444,540`・uiIcon の `|| '閉じる'` などの文字の代わり(app-core.js:45,445・app-rows.js:477・app-learn.js:546・app-list.js:120)。host の確認 `h.xxx ?` / `if (h.xxx)`: cut.js:119,122,126,240,477,673,677,701,842-843,1002,1041,1102-1103,1112・pack-tab.js:151 など 25 か所(app.js:1336-1341 で必ず渡している)
- 今: ui-kit.js は index.html:8 で同期に読み込まれ、UIKit.dialog.confirm(約 10 か所)・timebox・keybar・confirmTwice・drawer は確認なしで呼んでいる。e2e も ui-kit.js を必ず写す(e2e_edit_common.py の copy_tool・e2e_row_editing.py:43)。
- 案: 「ui-kit は必須」と決め、`window.UIKit && UIKit.x ? UIKit.x(...) : 代わり` を `UIKit.x(...)` に、代わりの経路を消す。host の関数も「必ず渡す」として `h.capStack ? … : []` などを直接呼びに。
- 理由: 条件が約 75 か所短くなり、「どちらの経路が本物か」を読む手間が消える。visibilitychange の代わりの経路が消えて AGENTS の決まりと一致する。
- 影響・リスク: test_document_save.cjs の harness は window に UIKit を持たず、openDoc の `src/editor/app-rows.js:158`(`window.UIKit && UIKit.streamer`)はその確認で素通りしている → 消すなら harness の context に `UIKit` の stub を足す。`if (CUT)`・`PACK &&`(30 か所)は harness が `CUT: null, PACK: null` で動かしているので残す(消すなら harness に空の物を渡す)。ui-kit.js が読めなかったときに一部だけ動く今の状態は無くなる(すでに確認の窓・時刻の欄が動かないので実害は小さい)。テスト: 全 e2e・test_document_save.cjs。

##### 3. 「保存し終えたか・競合・別の文書へ移ったか」の判定と知らせが 8 か所(優先度: 高・削れる行数の目安: 約 12 行)
- 場所: `src/editor/app-tools.js:570-572`(exportBeside)・`src/editor/app-tools.js:631-635`(cpExport)・`src/editor/app-learn.js:364-366, 386`(markReviewed・unmarkReviewed)・`src/editor/app-learn.js:422-425, 435`(redoOneHere)・`src/editor/app-jobs.js:434-437`(ovdPlace)。409 → 競合の案内: `src/editor/app-learn.js:371, 389, 442`。saveDoc 自身 `src/editor/app-rows.js:54` が showConflict(`src/editor/app-core.js:122`)と同じ 3 文を手で書いている
- 今: 「saveDoc → S.docId が変わった? → !ok || S.dirty || S.saving / S.conflict」を場所ごとに書き分け、知らせ「保存が終わっていないため、◯◯していません(保存の状態を確かめてから、もう一度押してください)」がほぼ同じ文で 5 か所。
- 案:
  ```js
  async function saveGate(id){ const ok = await saveDoc(); return S.docId !== id ? 'switched' : S.conflict ? 'conflict' : (!ok || S.dirty || S.saving) ? 'saving' : ''; }
  const notSaved = what => toast(`保存が終わっていないため、${what}していません(保存の状態を確かめてから、もう一度押してください)`, 6000, 'err');
  // savedFor(id) = !(await saveGate(id))。saveDoc の 409 は showConflict() + 知らせ
  ```
- 理由: 保存の判定の決まり(保存の途中・競合・切り替え)が 1 か所になり、新しいボタンで書き漏らしにくい(v0.40.1 の「保存の表示」のような不具合の芽)。
- 影響・リスク: exportBeside は別の文書へ移ったら黙って戻る・cpExport は code を投げる → 戻り値の文字列で分けるので動きは同じにできる。test_document_save.cjs は saveDoc を名前で抜き出して動かし `#conflictBar` を確かめる(1 本目のテスト)→ saveDoc から showConflict を呼ぶなら harness に `fnSource('showConflict')` を足す(足さないと ReferenceError)。テスト: e2e_ui_handoff.py(data-beside)・e2e_edit_pack.py(cpExport)・e2e_drill.py(drDone・evrRedo)・e2e_row_editing.py(ovdGo)・e2e_edit_cut.py / e2e_proofread_keys.py(conflictBar)。

##### 4. 設定の「送ったキーだけ直す」保存(api/settings/patch)を 6 か所で手書き(優先度: 中・削れる行数の目安: 約 12 行)
- 場所: `src/editor/app.js:386-391`(altEngine)・`src/editor/app.js:1083-1089`(evalDirs)・`src/editor/app-jobs.js:320-325`(diarSmooth)・`src/editor/app-rows.js:894-899`(keymap)・`src/editor/cut.js:330-331`(cutSilence)・`src/editor/pack-tab.js:29-33`(saveLoud)
- 今: 同じ `api('/api/settings/patch', { body: { values: {…} } })` を 6 回。失敗したときの扱いがばらばら: 先に S.settings に入れて失敗で戻す(altEngine・diarSmooth)/成功してから入れる(cutSilence・saveLoud)/戻さない(keymap)/S.settings に入れない(evalDirs)。
- 案: app-core.js に 1 つ置き、cut.js・pack-tab.js へは host で渡す。
  ```js
  async function patchSettings(values, label, opt = {}){
    const old = {}; for (const k in values){ old[k] = S.settings[k]; S.settings[k] = values[k]; }
    try { await api('/api/settings/patch', { body: { values } }); return true; }
    catch (e){ if (!opt.keep) Object.assign(S.settings, old); toast(`${label}を保存できませんでした: ${e.message}`, { kind: 'err', ms: opt.ms ?? 6000, action: opt.retry }); return false; } }
  ```
- 理由: 窓を並べたときに設定を消し合わない決まり(監査 11)を 1 か所で守れ、失敗したときの S.settings の状態がそろう。
- 影響・リスク: 「先に入れる」にそろえると、cutSilence・saveLoud は失敗時に S.settings を戻すようになる(今は入れない = 結果は同じ)。evalDirs は S.settings に持たないので `opt` で入れない選択を残す。keymap の失敗は ms 0(閉じるまで出す)・saveLoud は [もう一度] → 引数で。全体を差分で送る sendSettings/putSettingsNow(app-core.js:310, app-learn.js:36)は役割が違う(用語集など打つ欄)ので残す。テスト: e2e_alt.py(altEngine)・e2e_eval_set.py(evSave)・e2e_edit_voices.py(diarSmooth)・e2e_proofread_keys.py(keymap)・e2e_edit_cut.py(cutNoise)・e2e_edit_pack.py。

##### 5. ボタンを「押せなくして finally で戻す」が約 22 か所(優先度: 中・削れる行数の目安: 約 20 行)
- 場所: `src/editor/app.js:267, 275, 280-281, 303, 316-324, 460-462, 504-510, 991-1004, 1008-1012, 1021-1026, 1091-1101`・`src/editor/app-rows.js:96-106`・`src/editor/app-tools.js:48-54, 136-138, 308-324, 565-581`・`src/editor/app-jobs.js:78-88, 93-97, 258-263`・`src/editor/pack-tab.js:498-509, 526-534`・`src/editor/app-list.js:193-206, 222-231`
- 今: `const b = …; b.disabled = true; try { … } finally { b.disabled = false; }`。文字を「…中」に変えて戻す形も 3 か所(app.js:316・app-tools.js:566・pack-tab.js:526)。
- 案:
  ```js
  async function busy(btn, fn, label){ const t = btn.textContent; btn.disabled = true; if (label) btn.textContent = label;
    try { return await fn(); } finally { btn.disabled = false; if (label) btn.textContent = t; } }
  $('#evRun').addEventListener('click', e => busy(e.currentTarget, organizeEval));
  ```
  finally で押せるかを計算し直す所(diarGo・spAllGo・abGo・rlGo・raBrowse・transcribeInto・evrMark)は `busy(...).finally(renderX)`。
- 理由: 例外で押せないまま残る取りこぼしが起きにくい。ボタンの処理の中身だけが見えるようになる。
- 影響・リスク: finally で `false` ではなく計算値に戻す所に `.finally(render)` を付け忘れると、一瞬押せる状態になる。cut.js・pack-tab.js へは host で渡す。テスト: 各ボタンの e2e(e2e_edit_pack.py・e2e_edit_tabs.py の rlGo/raGo・e2e_eval_set.py・e2e_proofread_accuracy.py の abGo)。

##### 6. ジョブの「進み具合の文」と「種類ごとの終わりの文」が長い三項演算子・if の鎖(優先度: 中・削れる行数の目安: 約 12 行)
- 場所: 進み具合の文 `src/editor/app-jobs.js:250, 272, 296, 336`・`src/editor/app-learn.js:98`。種類で振り分ける if の鎖 `src/editor/app-jobs.js:196-201`(pollJobs)。終わりの知らせの 4 段の三項演算子 `src/editor/app-jobs.js:225-232`。カードの 7 段の三項演算子 `src/editor/app-jobs.js:300`。途中で止まったときの文が 2 か所 `src/editor/app-jobs.js:280` と `297`
- 今: `j.state === 'running' ? pctOf(j) + '%' : STATE_LABEL[j.state] || ''` を 5 回書く(336 だけ `Math.round(j.progress * 100)` で 0〜100 に収めない)。種類ごとの文は 1 行に 7 種類。
- 案:
  ```js
  const jobProg = j => j.state === 'running' ? pctOf(j) + '%' : STATE_LABEL[j.state] || '';
  const JOB_DONE = { 'voice-learn': j => `${(j.learned || []).length}人の声を覚えた`, diarize: j => …, retranscribe: j => `${j.segments}行を更新`, redo: …, normalize: …, alt: … };
  const doneText = j => (JOB_DONE[j.kind] || (j => j.segments + '行'))(j);
  // pollJobs: const by = {}; for (const x of fresh) (by[x.kind] ||= []).push(x);
  ```
- 理由: 種類を足すときに 1 行足すだけになる(今は 3 か所の鎖を直す)。
- 影響・リスク: 336 を pctOf にすると progress が範囲外・NaN のときの表示が変わる(良くなる向き)。「phase + %」の形(296・336・98)と「% か状態」の形(250・272)は 2 つの関数に分ける。テスト: e2e_edit_voices.py(voice-learn)・e2e_alt.py・e2e_edit_tabs.py。ジョブのカードの文そのものを照らすテストは見当たらない(要確認)。

##### 7. 「行に文字があるか」の判定が 3 つの書き方で 36 か所・派生の判定も重複(優先度: 中・削れる行数の目安: 約 10 行)
- 場所: `String(g.text || '').trim()`(app-rows.js:39, 249, 382, 857, 869・cut.js:186, 376, 433, 726, 913, 946 など)/`g.text.trim()`(app.js:426, 451・app-rows.js:823・app-tools.js:354, 413, 624・app-learn.js:175, 536・app-list.js:266)/`(s.text || '').trim()`(app-learn.js:94, 117)。未校正の判定 `!g.proofed && …trim()`: app-rows.js:823, 857, 869・app-learn.js:169, 175。話者の無い行: `src/editor/app-jobs.js:494-496, 505`・`src/editor/app-learn.js:321-322, 352+360`(4 か所で同じ Set を作って数える)・pack-tab.js:37(kept)
- 案:
  ```js
  const hasText = g => !!String(g && g.text || '').trim();
  const isUnproofed = g => !g.proofed && hasText(g);
  const noSpeakerRows = d => { const ids = new Set((d.speakers || []).map(s => s.id)); return d.segments.filter(g => hasText(g) && !ids.has(g.speaker)); };
  ```
- 理由: 「文字のある行」の定義(空白だけは数えない)が 1 か所になる。`g.text.trim()` は text が無い行(手で直した JSON)で落ちる形なので、そろえると落ちなくなる。
- 影響・リスク: 正しい文書では結果は同じ。test_document_save.cjs の readMark のテストは isBlankDraft などを名前で抜き出すので、isBlankDraft が hasText を使うなら `lineSource('const hasText')` を足す。cut.js・pack-tab.js へは host で。テスト: e2e_row_editing.py・e2e_drill.py(話者の無い行)・e2e_edit_pack.py。

##### 8. cut.js の中の写し(M の初期値 2 回・たたき台の取り込み 3 回・undo の積み方 2 回・ドラッグの終わり 3 回)(優先度: 中・削れる行数の目安: 約 15 行)
- 場所: M の初期値 `src/editor/cut.js:26-31` と reset `133-135`・たたき台の応答を区間にする `175-176`(load)・`361-362`(docChanged)・`264-265`(draftRows の origin と noteDraft)・前と比べて undo に積む `102-111`(change)と `894-899`(applyRowEdge)・ドラッグを終える組 `229-230`・`1162-1163`・`1182`・確認の 2 本の枝 `245-249`・同じ判定 `354` と `1174`(`M.pristine && (origin が rows か all)`)
- 今: 同じ代入の並び・同じ 3 行が場所ごとに書かれている。354 は `M.pristine && M.origin === 'rows' || M.pristine && M.origin === 'all'`。
- 案:
  ```js
  const fresh = docId => ({ docId, loaded: false, fps: null, …, rowFlags: [] });   // 作成と reset で共用(pps・snap・mode・shown は外)
  function takeDraft(r){ M.clips = norm(r.keepsSec.map(([a, b]) => [s2f(a), s2f(b)])); M.origin = r.base === 'rows' ? 'rows' : 'all'; noteDraft(M.origin, r.keepsSec, M.origin === 'rows' ? edgeSetting() : {}); }
  const endDrags = c => { if (M.drag) endDrag(c); if (M.rdrag) endRowDrag(c); };
  const redraftable = () => M.pristine && (M.origin === 'rows' || M.origin === 'all');
  ```
  confirmReplace は `h.confirm(...)` の 1 本に(指摘 2)。
- 理由: たたき台の規則(origin の付け方・noteDraft)を直すとき 1 か所で済む。reset で入れ忘れた値が前の文書から残る種類の不具合を防げる。
- 影響・リスク: reset で今は入れていない値(pps・snap・mode・shown・seekingOut・loading)は fresh に入れない(タブの見た目の状態を残す)。applyRowEdge を change に寄せる場合、change → afterChange は選択(M.sel)を外すので、区間の比較と pushCutUndo の部分だけを共用する。テスト: e2e_edit_cut.py。

##### 9. 「元に戻す」付き・「2 カットへ」付きの知らせと、行・履歴のクリックの分岐(優先度: 中・削れる行数の目安: 約 8 行)
- 場所: 「元に戻す」付き `src/editor/app.js:430, 626, 628, 648`・「2 カットへ」付き `src/editor/app.js:429`・`src/editor/app-rows.js:853, 862`・行のボタンの switch `src/editor/app.js:607-653`(sgok/sgno の同じ find が 629-630)・履歴のクリックの if/else の鎖 `src/editor/app.js:1251-1288`(「開いてから◯◯」が 1269 と 1277・メニューを閉じるが 1272 と 1276)
- 案:
  ```js
  const undoToast = (msg, ms = 5000) => toast(msg, { kind: 'ok', ms, action: { label: '元に戻す', fn: () => doUndo('tx') } });
  const TO_CUT = { label: '2 カットへ', fn: () => setEditTab('cut', { focus: true }) };
  const openThen = (id, fn) => (S.docId === id ? Promise.resolve(true) : openDoc(id)).then(ok => { if (ok && S.docId === id) fn(); });
  ```
- 理由: 知らせの次の一手(段7)の文と動きがそろう。switch 自体は読みやすいので表にはしなくてよい(手を入れるのは重複だけ)。
- 影響・リスク: 低。app.js:429-430 は UIKit.toast を直接呼んでいるが toast(msg, obj) と同じ。テスト: e2e_row_editing.py・e2e_proofread_keys.py・e2e_ui_mounted.py(非表示・relink)。行の「別の読み」(unfill)は e2e に無い。

##### 10. 小さな重複(絞り込みを外す・cutState の付け外し・txLimit を空に・今の文書の一覧の項目・URL の引数)(優先度: 低・削れる行数の目安: 約 10 行)
- 場所: 絞り込みを外して行を見せる `src/editor/app-rows.js:871, 1005`・`src/editor/app-jobs.js:453`(と `app-rows.js:151`)/cutState の付け外し `src/editor/app.js:612`・`src/editor/app-tools.js:667, 717`・`src/editor/cut.js:95`/txLimit を空に `src/editor/app.js:167, 172, 1261`・`src/editor/app-tools.js:502`/`S.list.find(x => x.id === S.docId)` app.js:1077・app-tools.js:210, 718・app-list.js:265 ほか/URL の書き換え `src/editor/app-tools.js:496-499` が setUrlParam(`src/editor/app-core.js:128-135`)と同じ replaceState を手で
- 案: `revealRow(i)`(隠れていれば #q・#flagKind を空にして applyFilter)・`setCut(g, on)`・`const txLimit = new Map()` にして `txLimit.clear()`(標準の API・for で delete しない)・`curItem()`・setUrlParam を `{key: value}` で複数受け取れるように。
- 理由: 同じ意味の操作に名前が付き、直す所が 1 か所になる。
- 影響・リスク: 低。txLimit を Map にするなら `src/editor/app-list.js:235` と `src/editor/app.js:1254` の読み書きを get/set に。テスト: e2e_ui_mounted.py(もっと見る・絞り込みを消す・?list=)・e2e_row_editing.py。

##### 11. innerHTML の組み立てを「既定でエスケープ」に(XSS の観点)(優先度: 中・削れる行数の目安: 約 10 行。esc( 約 150 回が消える)
- 場所: innerHTML の代入 90 か所・insertAdjacentHTML 3 か所・esc( 151 回。サーバーの値を素のまま入れている例: `src/editor/app-jobs.js:299-300`(j.segments・j.speakers)・`310`(e.mb)・`575`(x.rows)・`src/editor/app-learn.js:31`(x.count)・`236, 253, 559-561, 581-582`(CER の表の数)・`src/editor/app-rows.js:962`(履歴の x.ts・x.segments・x.proofed・x.chars)。要素を手で組む所: `src/editor/app-core.js:38`(showErr の中だけの el)・`src/editor/app-tools.js:24-36`(renderRlResult)・`123-141`(renderRa)
- 今: 文字列はすべて esc を通しており、穴は見つからなかった。ただし「付け忘れない」に頼る形で、数値の欄は素のまま。編集の CSP(`src/home/mount.py:40` = script-src・object-src・base-uri・form-action・frame-ancestors)は img-src を絞らないので、手で直せる作業データの JSON(voices.json・履歴など)に文字列が入ると、外への画像の要求のような HTML は作れる(スクリプトは CSP で動かない)。
- 案: app-core.js にタグ付きテンプレートを 1 つ置き、`${}` を既定でエスケープ・信頼する断片だけ `raw()` で通す。要素で組む所は showErr の el を app-core.js の `el(tag, cls, text)` に昇格して renderRa・renderRlResult でも使う。
  ```js
  const raw = s => ({ html: String(s) });
  const html = (parts, ...vs) => raw(parts.reduce((o, p, i) => o + p + (i < vs.length ? part(vs[i]) : ''), ''));
  const part = v => v == null ? '' : v.html !== undefined ? v.html : Array.isArray(v) ? v.map(part).join('') : esc(v);
  // box.innerHTML = html`<span class="n">${rows}行</span>`.html
  ```
- 理由: エスケープが既定になり、数値の欄も自動で守られる(同一オリジンにまとめた画面の XSS は全ツールの API に届く = AGENTS の【高】のリスク)。esc( が消えて式が短くなる。
- 影響・リスク: rowTitles の title(`src/editor/app-rows.js:477-478`)や tagsHTML の tt は esc 済みの文字列 → raw で渡さないと二重にエスケープされる。uiIcon の SVG も raw。一度に替えず、新しく書く所・直す所から段階的に。テスト: 画面のすべての e2e と `py -3.10 dev/ui_audit.py all --demo`。

##### 12. 長い関数(pack-tab.js renderNow 約 90 行・openDoc 約 57 行・pollJobs 約 50 行)(優先度: 低・削れる行数の目安: 約 5 行。読みやすさが主)
- 場所: `src/editor/pack-tab.js:205-295`(renderNow。中に「置き先」「これから作るパック」「見積もりの状態」「作る」「zip」の節のコメント)・`src/editor/app-rows.js:109-166`(openDoc。S の初期化の 130 行目は closeDoc `src/editor/app-tools.js:226` と重なる)・`src/editor/app-jobs.js:193-243`(pollJobs)
- 案: 節のコメントをそのまま関数名にして分ける(renderTarget・renderPlanned・renderPvState・renderBuildBtn・renderZip)。openDoc と closeDoc の S の初期化は `resetDocState(d, id)` を共用。pollJobs は指摘 6 の表で短くなる。
- 理由: 1 か所を直すときに読む範囲が狭くなる。closeDoc で初期化し忘れる値(S.sug・S.alt など、openDoc だけが消している)が見える。
- 影響・リスク: test_document_save.cjs は openDoc を名前で抜き出して動かすので、openDoc から呼ぶ新しい関数は harness の context に stub を足すか fnSource で読む。pack-tab.js は IIFE の中なので影響なし。closeDoc に S.sug などの初期化を足すと動きが変わる(良くなる向き・要確認)。テスト: e2e_edit_pack.py・test_document_save.cjs・e2e_ui_mounted.py(削除で閉じる)。

##### 13. 区間をつなぐ・二分探索・文書の長さを自前で複数(優先度: 低・削れる行数の目安: 約 8 行)
- 場所: 区間をつなぐ `src/editor/app-tools.js:623-628`(cpApproxSpans)・`src/editor/pack-tab.js:321`(renderMap)・`src/editor/cut.js:61`(mergedCount は数だけ)/二分探索 `src/editor/app-core.js:138`(segIndexAt)・`src/editor/cut.js:69`(nextClip)・`src/editor/cut.js:82`(rowCutFlags の bis)/文書の長さ `src/editor/app-tools.js:199-204`(docLength)と `src/editor/app-jobs.js:619-623`(docSpan)
- 案: `mergeSpans(spans, eps = 0)` と `upperBound(n, i => 条件)` を 1 つずつ(cut.js・pack-tab.js へは host で)。docLength と docSpan は 1 つに(再生中の動画の長さを使うかを引数で)。
- 理由: 同じ計算の境目の扱い(接している区間をつなぐか・等号)が 1 か所になる。
- 影響・リスク: renderMap は 1e-6 の余裕で接するものもつなぎ、`l[1] = b`(max でない。keeps は重ならない前提)— 共用で max にしても結果は同じ。docSpan は player().duration も見る(docLength は見ない)→ 1 つにすると題名の行の長さが変わりうる(要確認)。テスト: e2e_edit_cut.py・e2e_edit_pack.py(renderMap)・e2e_edit_tabs.py(題名の行)・test_document_save.cjs は segIndexAt を使わない。

##### 14. 書式の小道具・アイコン・入力中の判定・esc が ui-kit と重なる(優先度: 低・削れる行数の目安: 約 8 行)
- 場所: 大きさ `src/editor/app.js:120`(fmtSize)と `514`(mb)/長さ `src/editor/app-core.js:139`(approxLen)・`src/editor/app.js:515`(minStr)・`186`(voiceSec)・`106`(fmtDur)・`src/editor/app-jobs.js:575` が voiceSec と同じ計算を手で/日時 `src/editor/app.js:320-321`(書き出しの名前)・`529`(hhmm)/手書きの SVG `src/editor/app.js:1298-1299`(CLIP_IC・WARN_IC)≒ `UIKit.icon('scissors')`・`UIKit.icon('alert')`(src/ui-kit/ui-kit.js:1552, 1570)/`src/editor/app.js:774`(isTextEntry)≒ `UIKit.keys.isTyping`(src/ui-kit/ui-kit.js:1134)/`src/editor/app.js:4`(esc)≒ `UIKit.esc`(src/ui-kit/ui-kit.js:203)
- 案: 大きさは fmtBytes 1 つ・長さは `fmtLen(sec, { hours })` 1 つに。app-jobs.js:575 は voiceSec を使う。アイコンは uiIcon('scissors')・uiIcon('alert')、isTextEntry = UIKit.keys.isTyping、esc = UIKit.esc。
- 理由: ui-kit の既存の部品で置き換えられ、ツールごとの見た目・判定の食い違いが減る。
- 影響・リスク: 表示が少し変わる(mb は KB を出さない・アイコンの線の太さ 2.4 → 2・はさみの線の形が少し違う)。isTyping は input[type=range] も入力中と数え、contenteditable を親から引き継ぐ(編集の index.html に range は 0 個 = 今は同じ)。UIKit.esc は null を '' にする(今の esc は 'null')。テスト: e2e_ui_handoff.py(元の配信の札)・e2e_proofread_keys.py(キー)・e2e_folder_marker_range.py(fmtSize)。

##### 15. keydown の前置きの判定を共通に(優先度: 低・削れる行数の目安: 約 6 行)
- 場所: window/document の keydown が app.js に 8 本(`src/editor/app.js:72, 709, 837, 858, 882, 890, 911, 1289`)+ `#segs` の 724・`src/editor/cut.js:1081/1110`。`e.isComposing || e.keyCode === 229` が 5 か所(app.js:73, 838, 883, 891・cut.js:1111)。Esc で開いているメニューを閉じる(app.js:72-77)と、Esc で入力欄から抜ける(app.js:882-886)が別の 2 本
- 案: `const imeKey = e => e.isComposing || e.keyCode === 229; const anyMod = e => e.ctrlKey || e.metaKey || e.altKey;` を app-core.js に置き(cut.js へは host で)、前置きの判定を短く。Esc の 2 本は今と同じ順番で 1 本に。
- 理由: 日本語の変換中にキーを奪わない決まりが 1 か所になる。
- 影響・リスク: リスナーの登録の順番と capture(app.js:709 は capture で stopImmediatePropagation)に意味があるので、本数は減らさず前置きだけを共通に。テスト: e2e_proofread_keys.py・e2e_row_editing.py(右クリックのメニュー)・e2e_edit_cut.py・e2e_edit_tabs.py(Alt+数字)。

#### 他のグループとの重複の疑い
- 疑い: `src/studio/core.js:49` の入口の API(`new URL('../' + path, location.href)`・同じ失敗の文)が `src/editor/app-list.js:128-136` の portalApi とほぼ同じ。`Studio.api`(src/studio/core.js:28-34)も api() と同じ形 → 指摘 1 の request を ui-kit に置けば 3 ツールで共用できる。
- 疑い: esc が 3 つ(`src/editor/app.js:4`・`Studio.esc` src/studio/core.js:11・`UIKit.esc`)。null の扱いが違う(編集は 'null'・ほかの 2 つは '')。
- 疑い: 時刻の書式・読み取り `fmtT`・`parseT`(src/editor/app-core.js:8-21)と `parseTime`(src/studio/review.js:16)・`UIKit.timebox.parse/format`・`UIKit.fmt.dur`。
- 疑い(画面とサーバーで同じ規則を二重に持つ。コメントで「同じ」と明記された意図的なもの): `rowCutFlags`(src/editor/cut.js:79)↔ `ed_store.edit_cut_flags`(src/editor/ed_store.py:651。test_edit.py は Python 側だけを検査)・`coveredBy`(src/editor/app-tools.js:437)↔ `ed_misc._covered`(ed_misc.py:194)・`replaceOne`/`boundedAt`/`wbSplit`(app-tools.js:360・app.js:1167-1173)↔ `ed_learn.wb_split`(ed_learn.py:147)・`cpApproxSpans` ↔ `ed_state.union_spans`(ed_state.py:176)。`readMark` ↔ `ed_retime.subread_mark` は共通の例 `tests/subread_cases.json` で両側を検査していて、これがお手本。ほかも同じ形(共通の例の JSON)で縛ると食い違いを防げる。
- 疑い(意図的な差かもしれない): 行の印 `rowSig` が `src/editor/app.js:1320` と `src/editor/cut.js:186` にあり、noSub を入れるかだけ違う(cut.js はたたき台の作り直しの鍵なので noSub を入れないのは意図的の可能性・要確認)。


### G9 cut2resolve+recorder(担当: src/cut2resolve/resolve_textplus.py・cut2resolve_core.py・serve.py・pack.py・srt2resolve.py・auto_cut.py・cut2resolve.py、src/recorder/rec_core.py・recorder.py、合計 約 6,280 行)

#### 全体の傾向(3〜5 行)
- cut2resolve は「画面を消して部品・API・CLI を残す」(v0.11.0・v0.22.0)の途中の形が残っている。パックの出力のフラグ 7 つ(render・copy_video・fcpxml・textplus・backup・plan_file・readme_file)を位置引数で 4 段(serve → planned_outputs → expected_paths → pack_paths)渡し、同じ正規化(`copy_video or textplus`・`fcpxml and not textplus`)を 3 か所でしている。既定値(無音 -35/0.6/0.15・最短 0.3・crf 18・"01:00:00:00"・"AX")も 4〜6 か所に写しがあり、写しが合っているかをテストで確かめている。
- 「パックを作るのは pack.py だけ」の決まりに対して、`auto_cut.write_package` が EDL・FCPXML・SRT・cut-plan.json・友人へ.txt を自分で書く 2 本目の道として残っている。
- 一時ファイルに書いて付け替える処理が 4 か所の手書きで、しかも build_pack の中では二重(build_pack の `.c2r-…` と各関数の中の mkstemp)になっている。Text+ の手順書(readme)は、作るたびに `stack_captions` を 3 回計算し、新しいパックの経路と前のパックの Lua から作り直す経路の 2 本を持っている。
- 単独のコマンドは ytt_core を読まない約束なので、fsio の写し(書き込み・付け替え・JSON の読み込み)は意図したもの。ただし serve.py(ytt_core を読む)と recorder.py は、ytt_core にある部品(httpsec.send・fsio.write_json)を使わずに自分で書いている所がある。
- recorder は全体に短く整っている。大きいのは home の live 系との写し(時刻の変換・録画の id の形)で、他のグループとの重複として下に書く。

#### 指摘

##### 1. auto_cut.py が pack.py と別にパックを書いている(優先度: 高・削れる行数の目安: 約 35 行)
- 場所: `src/cut2resolve/auto_cut.py:201-236`(write_package)・`auto_cut.py:239-261`(run)。同じことをする道 = `src/cut2resolve/pack.py:295`(plan_cut の base "plan")+ `pack.py:630`(build_pack の fcpxml=True)
- 今: auto_cut の CLI は read_cut_plan → build_plan → remap_cues のあと、write_package が EDL・FCPXML・SRT・cut-plan.json・友人へ.txt(固定の短い文)を `S.write_text_atomic` で直接書く。`cut2resolve.py 動画 採用区間.json --fcpxml` は同じ部品(AC.build_plan・AC.build_cut_fcpxml・C.build_edl・AC.finalize_plan)を pack.build_pack 経由で使う。
- 案: run を pack の薄い包みにして write_package を消す(pack が auto_cut を import しているので、pack の import は run の中に置く)。
  ```
  import pack
  req = pack.Request(video=video, sub=sub, plan=selection_path, base="plan", handles=args.handles,
                     min_len=0.0, edit_media=False, src_start_tc=args.src_start_tc)
  pack.build_pack(pack.plan_cut(req), out_dir, copy_video=args.copy_video, fcpxml=True, force=args.force)
  ```
  さらに簡潔にするなら、auto_cut.py の CLI をやめて README の案内を `cut2resolve.py … --plan … --fcpxml` に寄せる(関数 read_cut_plan・build_plan などは pack が使うので残る)。
- 理由: AGENTS.md の「Resolve パックは pack.py だけが作る」に合う。出力の検査・上書きの確認・動画のコピーを飛ばす(E-15)・余白つき素材などの改良が auto_cut の道だけ遅れる、を防ぐ。
- 影響・リスク: **動きが変わる**: 出力の既定のフォルダ名(`_resolve_pack` → `_pack`。`-o` の既定だけ合わせれば同じにできる)・友人へ.txt の中身(固定文 → build_readme の手順書)・cut-plan.json の tool.name("cut2resolve-auto_cut" → "cut2resolve")。pack の既定の min_len 0.3 秒は今の auto_cut に無いので min_len=0 を渡す、余白つき素材は今使っていないので edit_media=False。既存機能の作りの変更なのでユーザー確認が要る。
- テスト: test_cut2resolve.py の test_auto_cut_*(248-290)と test_pack.py:674-676・832-840・1121-1125 が write_package を直接呼ぶので書き直しが要る。pack.py は変えないが、パックの作り方に関わるので dev/tests/test_resolve_pack_contract.py も単独で流す。

##### 2. 既定値の写しが 4〜6 か所(優先度: 高・削れる行数の目安: 約 5 行 + 写しの検査のテスト 1 件)
- 場所: `src/cut2resolve/pack.py:85-96`(Request の既定)・`serve.py:96`(DEFAULTS)・`cut2resolve.py:118-124,136-137`(argparse の default)・`cut2resolve_core.py:381`(detect_silence の noise_db=-35.0, min_sec=0.6, pad_sec=0.15)・`cut2resolve_core.py:470-471,527,650-651`(reel="AX"・rec_start="01:00:00:00"・crf=18)・`pack.py:630`(build_pack の crf=18)・`auto_cut.py:24`(SCHEMA = "youtube-tools-cut-plan/v1" = `cut2resolve_core.py:38` の CUT_PLAN_SCHEMA)
- 今: 同じ数を各所に直書き。合っているかは `src/cut2resolve/tests/test_serve.py:86-93`(test_ping_and_defaults)が DEFAULTS と Request を突き合わせて守っている。"01:00:00:00" は cut2resolve の中に 6 か所。
- 案: 正を pack.Request の既定 1 か所にし、ほかは読む。
  ```
  _D = {f.name: f.default for f in dataclasses.fields(pack.Request)}      # serve.py
  DEFAULTS = {"noise": _D["noise"], "silenceMin": _D["silence_min"], ...}
  ap.add_argument("--noise", type=float, default=_D["noise"], help="… (既定 %(default)s)")   # cut2resolve.py
  ```
  crf は `C.DEFAULT_CRF = 18`、rec_start は `C.DEFAULT_REC_START` を core に置いて Request・build_edl・write_pack・check_timecodes が使う。auto_cut.SCHEMA は `C.CUT_PLAN_SCHEMA` を指す。
- 理由: 既定を変えるときの直し漏れ(CLI と API で既定が食い違う)を無くす。写しを確かめるためだけのテストが要らなくなる。
- 影響・リスク: 値は変わらないので動きは同じ。argparse の help に数を直書きしている所は `%(default)s` にする(表示が "-35.0" のように小数になる程度の違い)。
- テスト: test_serve.py の test_ping_and_defaults(不要になる)。CLI の既定は test_cut2resolve.py の main を通すテストで守られる。

##### 3. Text+ の手順書を 2 回作り、作り方も 2 本ある(優先度: 中・削れる行数の目安: 約 10 行)
- 場所: `src/cut2resolve/resolve_textplus.py:945-965`(write_files: 951 で build_import_plan、958-960 で readme_text)・`resolve_textplus.py:968-972`(readme_text)・`resolve_textplus.py:975-981`(readme_from_script)・`src/cut2resolve/pack.py:754-755`(build_pack がもう一度 TP.readme_text)
- 今: Text+ のパックを作ると、`stack_captions` が build_import_plan(310 行)・write_files の中の readme_text・build_pack の readme_text で 3 回動く(API のときは pack.summary の caption_layout でさらに 1 回)。手順書は「Plan から作る readme_text」と「Lua に埋め込んだ計画から作る readme_from_script」の 2 本で、同じになることをテストで確かめている。
- 案: 埋め込む計画(build_import_plan の結果)から手順書を作る関数 1 つにまとめる。readme_from_script はそれを read_script_plan の結果に当てるだけにする。write_files は `{files…}, readme` を返し、build_pack は 754 行の作り直しをやめてそれを使う。
  ```
  def readme_from_data(d, backup=True):   # 今の readme_from_script の中身(fps "n/d" → meta、captionLanes・videoTracks など)
  def write_files(...):  ip = build_import_plan(...); ...; return files, readme_from_data(ip, backup)
  def readme_from_script(text, backup=True): return readme_from_data(read_script_plan(text), backup)
  ```
- 理由: 段の数・字幕の数・見た目の名前を 1 つの計画から読むので、新しいパックと前のパックの「手順を見る」が必ず同じになる。計算も 1 回で済む。
- 影響・リスク: 中身は同じになる見込み(今もテストで同じと確かめている)。readme_text を消すならテストの呼び出し(test_pack.py:347)を直す。
- テスト: test_pack.py:339-357・1458-1489(readme_from_script と res["readme"] が同じ)。コマンドのときは友人へ.txt を書くので、dev/tests/test_resolve_pack_contract.py の B(パックのファイルのバイト比較)も流す。

##### 4. パックの出力のフラグ 7 つの位置引数の受け渡しと正規化が 3 重(優先度: 中・削れる行数の目安: 約 15 行)
- 場所: `src/cut2resolve/pack.py:533-568`(pack_paths)・`pack.py:613-618`(expected_paths)・`pack.py:621-627`(planned_outputs)・`pack.py:663-664`(build_pack の正規化)・`pack.py:780`(`pack_paths(video, out_dir, True, True, False, True, True)`)・`src/cut2resolve/serve.py:584`(output_from_spec の正規化)・`serve.py:779-781`・`serve.py:794-795`
- 今: render・copy_video・fcpxml・textplus・backup・plan_file・readme_file を、関数ごとに位置引数で並べ直して渡す。`copy_video or textplus`・`fcpxml and not textplus` を serve・expected_paths・build_pack の 3 か所で計算する。780 行は 5 つの真偽値の並びで、何を指しているか読めない。
- 案: 出力の指定を小さな凍結 dataclass にして、正規化は作るとき 1 回だけ。
  ```
  @dataclass(frozen=True)
  class Outputs:
      render: bool = False; copy_video: bool = False; fcpxml: bool = False; textplus: bool = False
      backup: bool = True; plan_file: bool = True; readme_file: bool = True
      def __post_init__(self): ...  # copy_video |= textplus, fcpxml &= not textplus(object.__setattr__)
  ```
  pack_paths・expected_paths・planned_outputs はこれを 1 つ受け取る。build_pack は今のキーワード引数のまま(呼ぶ側が 52 か所あるので外の形は変えない)、中で Outputs を作る。
- 理由: 引数の並び違いのバグを防ぐ・3 か所の正規化を 1 つに・780 行が `Outputs(render=True, fcpxml=True, textplus=True)` と読める。
- 影響・リスク: 動きは同じ。pack_paths・planned_outputs の形が変わるので、テストの呼び出しを直す。build_pack の外の形は変えないので editor の resolve_export・契約テストは変えなくてよい。
- テスト: test_pack.py(pack_paths・planned_outputs を呼ぶ)・test_serve.py(plan・build の outputs と 409 exists)。dev/tests/test_resolve_pack_contract.py も流す。

##### 5. 一時ファイル → 付け替えの手書きが 4 か所、build_pack では二重(優先度: 中・削れる行数の目安: 約 15 行)
- 場所: `src/cut2resolve/cut2resolve_core.py:544-562`(render_rough_cut)・`cut2resolve_core.py:758-767`(copy_video_gain)・`cut2resolve_core.py:846-864`(copy_video)・`src/cut2resolve/srt2resolve.py:66-81`(write_bytes_atomic)。二重 = `src/cut2resolve/pack.py:688-693`(build_pack が `.c2r-<tag>-…` の一時の名前を渡す)
- 今: 4 か所で「mkstemp → 書く → `S._replace_retry` → finally で `_unlink_quiet`」を手で書いている(render_rough_cut は 545 行で fd を閉じてから、copy_video は fd に直接書く、と形も少しずつ違う)。render_rough_cut・copy_video_gain を呼ぶのは build_pack だけで、渡す先がすでに一時の名前なので、中の mkstemp → `.c2r-…` → 本当の名前、と 2 回付け替えている。
- 案: srt2resolve(単独のコマンドも読める側)に context manager を 1 つ置く。
  ```
  @contextlib.contextmanager
  def staged(dst, suffix=".part"):
      fd, tmp = tempfile.mkstemp(dir=arg_path(Path(dst).parent), prefix=".tmp-", suffix=suffix); os.close(fd)
      try: yield tmp; _replace_retry(tmp, str(dst)); tmp = None
      finally: tmp and _unlink_quiet(tmp)
  ```
  4 か所は `with S.staged(out_path, ".mp4") as tmp:` だけになる。さらに進めるなら、build_pack が先に staged へ積んでから render_rough_cut・copy_video_gain を呼び(失敗しても finally で消える)、2 つの関数の中の一時ファイルをやめる。
- 理由: 書きかけを残さない規則が 1 か所になる。付け替えが 1 回減る(Windows では付け替えのたびにウイルス対策のロックで待つことがある)。
- 影響・リスク: context manager だけなら動きは同じ。二重をやめる方は、render_rough_cut を単独で呼んだときの「書きかけを残さない」が無くなる(**関数単体の動きが変わる**)ので、テスト 2 件を build_pack 経由に書き直す必要がある。
- テスト: test_pack.py:1205-1223(取り消し・失敗で何も残らない)・test_pack.py:1037-1038(フォルダに . で始まるファイルが残らない)・test_cut2resolve.py:360-369。

##### 6. API に、消した画面のための指定が残っている(優先度: 中・削れる行数の目安: 約 15 行 + README の説明)
- 場所: `src/cut2resolve/serve.py:417`(spec.silenceExtra)・`serve.py:431-432`(spec.handles)・`serve.py:441-442`(listKind "drop")・`serve.py:452`(spec.joinGap)・`serve.py:584`(output.fcpxml)・`serve.py:593`(output.crf)
- 今: これらは消した cut2resolve の画面(①②③ と「詳しい設定」)の項目。今の呼ぶ側(editor の cut.js・pack-tab.js、home の autorun.py)を探すと、silenceExtra・joinGap・handles・listKind "drop"・output.fcpxml・output.crf を送る所は無い(cut.js:283-290 は mode・silence・listKind 'keep'・listText・minLen・dropCutRows・keepSource だけ)。使っているのはテスト(test_serve.py)と、dev/tests/e2e_pipeline.py:177・195 が既定と同じ値(handles 0・fcpxml false)を送る所だけ。
- 案: これらの鍵を受けるのをやめ、request_from_spec の mode "keep"・"list" の枝と output_from_spec を短くする(知らない鍵は今も黙って無視するので、送ってきても壊れない)。FCPXML・crf・削る区間のリストは CLI(cut2resolve.py)に残る。
- 理由: v0.22.0 で消した API と同じ理由(使う側の無い入口を減らす)。request_from_spec(68 行)が読みやすくなる。
- 影響・リスク: **既存機能の削除**なのでユーザー確認が要る(AGENTS の決まり)。版を上げて README の API の節を直す。e2e_pipeline は既定と同じ値なので鍵を消しても結果は同じ。要確認: friend-apps や手で叩くスクリプトから送っていないか(src・dev・friend-apps の .py・.js・.cs を grep した範囲では無い)。
- テスト: test_serve.py の該当のテストを消す・直す。dev/tests/e2e_pipeline.py は変えなくても通る見込み。

##### 7. serve.py・recorder.py が ytt_core の応答・書き込みの部品を使っていない(優先度: 中・削れる行数の目安: 約 15 行)
- 場所: `src/cut2resolve/serve.py:672-683`(Handler._send)・`serve.py:332`(write_pack_record の書き込み)・`serve.py:336`(`key=lambda n: os.path.getmtime(n)`)・`src/recorder/recorder.py:158-168`(_head・_send)・`recorder.py:84-90`(read_settings)
- 今: `ytt_core/httpsec.send` の説明に「各サーバーの Handler._send はこれを呼ぶだけ」とあり、studio・editor・home はそうしているが、cut2resolve の _send は同じ見出し(Content-Type・Content-Length・no-store・nosniff)を手で書き、Referrer-Policy を足している。write_pack_record は ytt_core を読む serve.py の中で、単独のコマンド用の `S.write_text_atomic(json.dumps(..., indent=1) + "\n")` を使う。recorder の _head は Cache-Control を変えられる(再生リストは no-cache・セグメントは max-age)ので httpsec.send_head をそのまま使えない。
- 案: cut2resolve は `httpsec.send(self, code, body, ctype, dict({"Referrer-Policy": "no-referrer"}, **(extra or {})))` の 1 行に(mount.py の _send の上書きはそのまま効く)。write_pack_record は `fsio.write_json(path, rec, indent=1)`、並べ替えは `key=os.path.getmtime`。recorder は httpsec.send_head に `cache="no-store"` の引数を足してから使う(ytt_core の変更なので全ツールのテストが要る)。read_settings は `fsio.read_json_file(path, 64 * 1024)` で大きさの上限も付く。
- 理由: 応答の見出しの規則(セキュリティ)を ytt_core の 1 か所に集める。
- 影響・リスク: cut2resolve は見出しの中身・順番が同じ(Referrer-Policy は JSON の応答には意味が無いので、案内のページだけに付けてもよい)。fsio.write_json は fsync の失敗を無視する点だけ S.write_text_atomic と違う(記録なので問題ない)。recorder は ytt_core を変えるので、入口・スタジオ・編集の e2e も流す。
- テスト: 見出しを確かめるテストは無い(test_serve.py・test_recorder.py・test_mount.py を "nosniff"・"Cache-Control" で grep して 0 件)。直すなら 1 件足すとよい。write_pack_record は test_serve.py の build のテストと ytt_core の txindex のテスト。

##### 8. 開始タイムコードの ffprobe の読み直しは本番では通らない・ffprobe の呼び方が 3 か所(優先度: 低・削れる行数の目安: 約 12 行)
- 場所: `src/cut2resolve/cut2resolve_core.py:430-443`(read_start_tc の ffprobe の道)・`cut2resolve_core.py:744`・`srt2resolve.py:221-235`(probe)・`srt2resolve.py:210-216`(_exact_frames)・`cut2resolve_core.py:274-280`(_ffmpeg_run)
- 今: read_start_tc は meta が無いとき、probe と同じ ffprobe のコマンドをもう一度動かす。本番の呼び出し(pack.py:302・603、auto_cut.py:256、_gain_copy_opts)はどれも S.probe の結果 meta を渡すので、この道を通るのはテスト(test_cut2resolve.py:496・512)だけ。`subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=…, stdin=DEVNULL)` も 3 か所に同じ形で書いてある。
- 案: read_start_tc を `return (meta or S.probe(video)).get("start_tc")` にする(probe が start_tc を読む 1 か所になる)。subprocess.run の形は srt2resolve に `_run(cmd, timeout)` を 1 つ置いて 3 か所から使う(見つからない・時間切れの文は呼ぶ側で付ける)。
- 理由: 開始タイムコードの読み方が probe の 1 か所になる(今も start_tc_from で共通だが、ffprobe の呼び方が 2 本)。
- 影響・リスク: meta なしで呼んだときに probe の重い数え直し(_exact_frames)まで走る違いがある(テストだけなので問題は小さい)。テストは probe の結果で確かめる形に直す。
- テスト: test_cut2resolve.py:200-205・496-513、test_pack.py:634-637。

##### 9. Lua を作るときの古い計画のための補い(優先度: 低・削れる行数の目安: 約 5 行)
- 場所: `src/cut2resolve/resolve_textplus.py:371-375`(importer_script の setdefault("target")・setdefault("style")・mediaFps の補い)
- 今: importer_script に渡す計画は、本番もテストも全部 build_import_plan の結果(target・style・mediaFps を必ず入れる)。以前の textplus-import.json を読んで Lua を作り直す道は 2026-09-26 に無くなっているので、補いは通らない。
- 案: 5 行を消す。前のパックを読む readme_from_script 側の `d.get(...) or 既定` は、古い Lua を読むので残す。
- 理由: 通らない互換の道を減らす。
- 影響・リスク: 動きは同じ(build_import_plan 以外から呼ぶ所が無いことを src・dev で grep して確かめた)。368 行の `json.loads(json.dumps(plan))` は tuple を list に直す働きもある(lua() は list しか表にしない)ので、copy.deepcopy に替えないこと。
- テスト: test_pack.py の TestResolveTextPlusScript(64-107・231-236・332-391)。

##### 10. auto_cut の計画の形を 2 か所で組み立てている(優先度: 低・削れる行数の目安: 約 6 行)
- 場所: `src/cut2resolve/auto_cut.py:104-112`(build_plan)・`auto_cut.py:126-131`(plan_from_keeps)・`src/cut2resolve/pack.py:842`(summary の removed)
- 今: build_plan の最後の dict は plan_from_keeps と同じ鍵・同じ順番。余白つきの区間 `(max(0, a - handle), min(total, b + handle))` も 104 行と 109 行で 2 回計算する。pack.summary は plan.doc にある removed_frames を `AC.removed_between` でもう一度計算する。
- 案: build_plan の最後を `return plan_from_keeps(keeps, meta, records, handle)` に。余白つきの区間は 1 回計算して records と keeps の両方に使う。summary は `plan.doc["removed_frames"]` を使う。
- 理由: cut-plan の詳細版の形が 1 か所になる。
- 影響・リスク: 動きは同じ(鍵の並びも同じ)。
- テスト: test_cut2resolve.py:248-258(build_plan)・test_pack.py:832-840(読み直し)。

##### 11. 写しを比べる「大きさ・更新日時の秒」の作りが 4 か所(優先度: 低・削れる行数の目安: 約 6 行)
- 場所: `src/cut2resolve/cut2resolve_core.py:778-786`(_file_sig)・`cut2resolve_core.py:804-807`(gain_copy_record)・`cut2resolve_core.py:816-817`(same_gain_copy)・`cut2resolve_core.py:822-831`(same_copy)
- 今: same_copy は _file_sig と同じ比べ方を os.stat で書き直している。`dict(_file_sig(final), name=Path(final).name)` も 2 か所。
- 案: `same_copy = lambda src, dst: (a := _file_sig(src)) is not None and a == _file_sig(dst)`(関数で)。置き場所の印は `_out_sig(final)` 1 つにして gain_copy_record・same_gain_copy から使う。
- 理由: 「同じ写しとみなす」規則が 1 か所(E-15 の判定はここだけ、という README の約束どおり)。
- 影響・リスク: 今の same_copy は src が普通のファイルかを確かめていない。_file_sig は両方を確かめるので、src がフォルダのときだけ違う(呼ぶ側は動画のファイルなので実害なし)。
- テスト: test_pack.py の same_copy・same_gain_copy のテスト(681-742・1101-1150 付近)。

##### 12. srt2resolve と core の小さな写し(ドロップフレームの読み替え・出力の衝突の検査)(優先度: 低・削れる行数の目安: 約 8 行)
- 場所: `src/cut2resolve/cut2resolve_core.py:458-461` と `src/cut2resolve/srt2resolve.py:355-357`(同じ文の警告と `;` → `:`)・`srt2resolve.py:520-527` と `cut2resolve_core.py:680-689`(validate_output_paths)
- 今: ドロップフレームの注意は同じ文が 2 か所。srt2resolve.run は入力との衝突と既存の出力を自分で 4 通りの same_path で調べる(core を読めないため)。
- 案: srt2resolve に `ndf_tc(tc) -> (tc, warns)` を置いて両方から使う。validate_output_paths と OutputExists を srt2resolve へ移し、core は nominal_rate などと同じく別名で出す(`validate_output_paths = S.validate_output_paths`)。
- 理由: core → srt2resolve の向きの共通化は、すでにタイムコードで使っている形(cut2resolve_core.py:412-415)と同じ。
- 影響・リスク: srt2resolve のエラーの文が「…-o で別のフォルダを指定してください。」から core の文に変わる(**表示だけ変わる**)。
- テスト: test_pack.py:634(ドロップフレーム)・test_cut2resolve.py の srt2resolve の main を通すテスト。

##### 13. text_style が hex_rgba と同じ変換を書き直している(優先度: 低・削れる行数の目安: 約 2 行)
- 場所: `src/cut2resolve/resolve_textplus.py:70-78`(hex_rgba)・`resolve_textplus.py:89-92`(text_style)
- 今: text_style は `#RRGGBB` → 0〜1 の rgb を自分で計算する。
- 案: `fill["rgba"] = hex_rgba(color["hex"])`。
- 理由: 色の変換が 1 か所。
- 影響・リスク: 形の違う hex で今は ValueError、案では None になる。color を渡すのは serve.output_from_spec だけで、そこは ytt_core.colors.resolve が検査済みの hex なので実害なし(CLI は色を渡さない)。
- テスト: test_pack.py の text_style のテスト。

##### 14. 小さな整理のまとめ(優先度: 低・削れる行数の目安: 合わせて 約 10 行)
- 場所と案:
  - `src/cut2resolve/cut2resolve_core.py:393-400`: silence_start と silence_end を 1 行に 2 回の re.search → 1 つの正規化表現 `silence_(start|end):\s*(-?[\d.]+)` を先にコンパイルして 1 回で。
  - `src/cut2resolve/pack.py:335-337`: `_check_request` の存在の確かめは `for p in req.inputs():` で同じ(Request.inputs が 103-104 行にある)。
  - `src/cut2resolve/pack.py:454-455`: `* fps[1] / fps[0]` → `C.frames_to_sec`。
  - `src/cut2resolve/serve.py:485`: `isinstance(t, bool) or not isinstance(t, (int, float)) or t != t` → `C.num(t) is None`(無限大も同じ文で断る)。
  - `src/cut2resolve/cut2resolve_core.py:650-677`: write_pack が返す dict にパスと文字列 readme_text が混ざる → `(files, text)` を返す(呼ぶ側は build_pack の 713 行だけ)。
  - `src/recorder/rec_core.py:747`: meta["sessions"] は 736 行で必ず list にしてあるので setdefault は不要。
  - `src/recorder/rec_core.py:428-429`: segments_in が summary の 8 項目を 1 つずつ写す → `{k: s[k] for k in (...)}`。
- 理由: どれも読みやすさ。
- 影響・リスク: 動きは同じ(keeps_from_spec は無限大のときのエラーの文だけ変わる)。
- テスト: test_cut2resolve.py(detect_silence)・test_pack.py・test_serve.py(keeps の検査)・test_recorder.py(復旧・segments)。

##### 15. main() の標準出力の設定とシグナルの登録の写し(優先度: 低・削れる行数の目安: 約 12 行)
- 場所: `src/cut2resolve/cut2resolve.py:98-102`・`srt2resolve.py:559-563`・`serve.py:964-968`・`src/recorder/recorder.py:345-349`(`stream.reconfigure(errors="replace")` のループ)・`serve.py:988-997` と `recorder.py:386-394`(SIGTERM/SIGBREAK の登録)
- 今: 同じ 5 行のループが担当の中に 4 つ(リポジトリ全体で 6 つ)。auto_cut.py の main には無い(Windows の cp932 の画面で文字化けのエラーになりうる)。
- 案: 単独のコマンド 3 本は srt2resolve に `safe_stdio()` を置いて使う(auto_cut にも足す)。serve・recorder のシグナルの登録は ytt_core に 1 つ(他のグループと合わせて。下の重複の疑い)。
- 理由: 写しを減らし、auto_cut の抜けも埋まる。
- 影響・リスク: 動きは同じ(auto_cut は表示できない文字があっても落ちなくなる = 良い方へ変わる)。起動の約束(SIGTERM/SIGBREAK で後始末)は入口が使うので、シグナルの部分を寄せるときは home の test_launch・test_restart も流す。
- テスト: 単独のコマンドの main は test_cut2resolve.py・test_pack.py が呼ぶ。serve の起動・終了は test_serve.py、recorder は test_recorder.py。

#### 他のグループとの重複の疑い
- (疑い)録画の時刻の変換: `src/recorder/rec_core.py:86-120`(_utc_text・now_iso・epoch_iso・iso_epoch)と、`src/home/live_export.py:126-140`(iso_epoch・epoch_iso)・`src/home/live_excite_worker.py:134-147`(iso_epoch。「.」の有無で書式を選ぶ別の書き方)。録画の id の形も `rec_core.py:46`(REC_ID_RE)と `home/live_export.py:72`(REC_RE。コメントに「rec_core の REC_ID_RE と同じ」)。録画の部品はすでに ytt_core を読むので、ytt_core に 1 つ(例: 録画の受け渡しの小道具)置いて 3 か所から使える。
- (疑い)Windows で SO_EXCLUSIVEADDRUSE を付けるサーバーのクラス: `src/cut2resolve/serve.py:846-855`・`src/recorder/recorder.py:305-317`・`src/home/launch.py:1116`・`src/studio/serve.py:478`・`src/home/restart.py:93`。ytt_core.httpsec に `ExclusiveServer` を 1 つ置ける。
- (疑い)ログを 1MB で .old に回して追記: `src/cut2resolve/serve.py:115-126`・`src/recorder/recorder.py:114-136`・`src/editor/ed_jobs.py:208`・`src/home/autorun.py:95`。
- (疑い)JSON の本文の読み取り(Content-Type・Content-Length・上限・dict か): `src/cut2resolve/serve.py:709-731` と `src/recorder/recorder.py:246-267`。studio・editor の serve.py にも同じ形がありそう(要確認)。
- (意図した写し・ただし食い違い)単独のコマンドは ytt_core を読まないので、`srt2resolve.py:54-90`(_replace_retry・write_bytes_atomic)・`cut2resolve_core.py:360-366, 874-887, 919-922`(_unlink_quiet・read_json_file・is_network_path)は ytt_core/fsio の写し(`# lint: keep`)。ただし付け替えのやり直しの規則が違う: srt2resolve は Windows の PermissionError なら何でも 6 回(0.05〜0.25 秒)、fsio は winerror 5・32・33 だけ 4 回(0.1〜0.4 秒)。読み取り専用のフォルダでも srt2resolve は待ってしまう。写しを残すなら規則だけでも fsio にそろえるとよい。
- (付記・簡潔化の外・要確認)`src/cut2resolve/serve.py:276-284`: SLOTS(ytt_core/jobs.py)を通すのは kind "build" だけで、試算(api/plan)は通さない。試算でも mode "silence"(編集の「たたき台: 無音」= cut.js:283)や行の端の無音の検出は動画の音声を全部読む重い処理になる。編集の側(src/editor/resolve_export.py:188-193)は row_edge_pending で SLOTS を通しているので、cut2resolve の API だけ扱いが違う。意図したもの(試算は待たせない)かを確かめたい。


### G10 ytt_core(担当: src/ytt_core/ の __init__.py・colors.py・datadir.py・evaldata.py・excite.py・fsio.py・httpsec.py・jobs.py・layout.py・loudness.py・normalize.py・pick.py・runtime.py・schemas.py・tools.py・txindex.py、合計 約 3,210 行)

#### 全体の傾向
- ytt_core の中身は短い関数が多く、入れ子も浅い(150 行を超える関数は無い)。excite.py(833 行)は「一括の式・窓つきの式・候補の帳簿」に分かれ、式は golden とテストで守られている。大きな作り直しは要らない。性能(e)の問題も見当たらない(excite は窓の分だけ持って捨てる・txindex は紐づけのパスを読んだときに 1 回だけ求めている)。
- 目立つのは 3 つ。① 10-04 に簡易版を消したあと、evaldata に「書き出し側」の関数が残っている。② ytt_core の小道具が半分しかないので、各ツールが残り半分を自前で書いている(読めなければ既定値の JSON 読み・更新日時のキャッシュ・優先度つきの creationflags・孫ごと止める・ログの回し)。③ excite の数字(0.6/0.4・floor・smooth の幅・5/6・±6)が一括と配信中の 2 か所(テストを入れて 3 か所)にある。
- lint の基準 4 は名前(`_unlink`・`_no_window`・`NO_WINDOW`・`KillJob` など)で探すので、別名の写し(editor/ed_state.py の `unlink_quiet`・`_flags`・`low_flags`・`kill_tree`)は当たっていない。
- 動きを変えない整理で削れるのは、ytt_core の中で 約 120〜140 行が目安。吸い上げまで含めると、全体で 約 400 行。

#### 指摘

##### 1. evaldata の書き出し側の関数が使われていない(優先度: 高・削れる行数の目安: 約 45 行 + テスト 約 20 行)
- 場所: `src/ytt_core/evaldata.py:22-27`(RULES)・`:131`(_ABS)・`:140-158`(scrub_paths)・`:184-186`(zip_name)・`:198-203`(safe_url)・`:235-243`(overlap・raw_links)
- 今: 書き出す側(editor/ed_lite.py)は 2026-10-04 に消えたが、書き出し用の関数が残っている。src と dev の本番コードからの呼び出しは 0 件。呼んでいるのは `src/ytt_core/tests/test_evaldata.py` の test_scrub・test_names の一部・test_raw_links だけ。
- 案: 上の 6 つを消し、対応するテストも消す。受け取る側(dev/eval_import.py・dev/eval_asr.py)が使うものは残す: check_zip・extract_zip・read_json_bytes・read_edits・judge・strip_marks・find_abs_paths・work_id_of・safe_part・base_name・FORMAT 系・WORK_ID・FILES・MAX_BYTES。
- 理由: `__init__.py` の説明「形式と取り込みは残す」に中身を合わせる。scrub_paths の 3 つの正規表現(155-156 はコンパイルもしていない)を、読む人が追わずに済む。
- 影響・リスク: 本番の動きは変わらない。`docs/spec/subtitle-notation.md:23` が RULES を「同じ」と参照しているので、RULES を消すならその 1 行も直す(残すなら RULES だけ残す)。書き出し側は git の履歴(cf617a8 まで)に残る。テスト: test_evaldata(消す分以外)・dev/tests/test_eval_import.py・test_eval_asr.py。

##### 2. 「読めなければ既定値」の JSON 読みが fsio に無い(優先度: 高・削れる行数の目安: ytt_core 内 約 8 行・吸い上げ込み 約 150 行)
- 場所: `src/ytt_core/datadir.py:168-174`(read_marker)・`src/ytt_core/colors.py:109-113`(_read_json の読み)。お手本は `dev/_evalcommon.py:32-40` の read_json(path, default, limit)
- 今: fsio.read_json_file(大きさの上限つき・NaN を断る)は、失敗すると例外を上げるだけ。そのため呼ぶ側が毎回 try/except (OSError, UnicodeError, ValueError) と isinstance(dict) を書いている。ytt_core の中でも read_marker と colors._read_json は read_json_file を使わず open + json.load で読んでいて、大きさの上限も無い(colors の my-colors.json・member-colors.json はホロカラーが書く作業データ)。外にも同じ形が約 45 か所ある(下の吸い上げ A)。
- 案: fsio に 1 つ足す。
  ```
  def read_json_or(path, default=None, max_bytes=16 * 2**20, kind=None):
      try: d = read_json_file(path, max_bytes)
      except (OSError, UnicodeError, ValueError): return default
      return d if kind is None or isinstance(d, kind) else default
  ```
  read_marker は `return fsio.read_json_or(os.path.join(d, MARKER), None, 64 * 1024, dict)` の 1 行になる。
- 理由: 例外の種類の書き漏れと大きさの上限の付け忘れを、1 か所で防げる。外の写しは UnicodeError を書いていないものが多く、壊れた UTF-8 のファイルで落ちる形になっている。
- 影響・リスク: read_json_file は utf-8-sig で読むので、open(encoding="utf-8") との違いは「先頭の BOM を許す」だけ(良い方向)。上限を付けると、それより大きいファイルは「読めない」扱いになる。既定の上限は大きめにする。テスト: TestFsio に 1 件足す。TestDatadir(read_marker を通る prepare が 16 件)・TestColors。

##### 3. 更新日時と大きさのキャッシュが 2 か所にある(外にも 7 か所)(優先度: 高・削れる行数の目安: ytt_core 内 約 10 行・外 約 30 行)
- 場所: `src/ytt_core/txindex.py:92-113`(load の中の _cache)・`src/ytt_core/colors.py:100-116`(_read_json の _cache)
- 今: どちらも自前で「os.stat → (st_mtime_ns, st_size) を鍵にする → ロック → 外れたら読む」をしている。colors は鍵にも path を入れている(105 行。辞書の鍵がすでに path なので重複)。外にも同じ形がある(吸い上げ B)。
- 案: fsio に `stamp(path)`(→ (mtime_ns, size) か None。editor/ed_state.file_stamp と同じもの)と、小さなクラス `StampCache` を置く。`get(path, load)` は stamp が変わったときだけ load を呼び、`prune(keep)` で消えたファイルを外す。txindex.load は `_docs.get(p, lambda p: _parse(fsio.read_json_or(p, None, MAX_DOC_BYTES), n[:-5]))`、colors._read_json は `_files.get(path, fsio.read_json_or)` にする。
- 理由: 「ファイルが変わったときだけ読み直す」規則(鍵の作り方・ロック・消えたファイルの扱い)を 1 か所にまとめる。
- 影響・リスク: 鍵は同じ値なので、動きは同じ。txindex の「消えた文書をキャッシュから外す」(112-113 行)は prune で残す。テスト: TestTxIndex(キャッシュの読み直し)・TestColors・home の test_cases・studio の txlink を使うテスト。

##### 4. 子プロセスの優先度の creationflags を各所で組み立てている(優先度: 中・削れる行数の目安: ytt_core 内 2 行・外 約 20 行)
- 場所: `src/ytt_core/normalize.py:273-275`、`src/ytt_core/tools.py:16-21`(no_window_flags)
- 今: no_window_flags が扱うのは「窓なし」と「別グループ」だけ。「通常より下の優先度」は normalize.normalize が自前で `flags |= BELOW_NORMAL_PRIORITY_CLASS` している。外にも同じ組み立てが 8 か所ある(吸い上げ E)。`src/editor/ed_jobs.py:136-140` は no_window_flags(new_group=True) とまったく同じ。名前が `_flags`・`low_flags`・`_ytcap_flags` なので、lint の基準 4 に当たらない。
- 案: `no_window_flags(new_group=False, priority=None)`(priority は "low" か "high")に広げる。normalize は `tools.no_window_flags(new_group=True, priority="low" if priority_low else None)` の 1 行になる。
- 理由: Windows だけにある定数の getattr と os.name の分岐を 1 か所にまとめる。
- 影響・リスク: 値は同じ。テスト: TestTools(no_window_flags の 6 件に priority の分を足す)・test_normalize。lint の DUP_HELPERS に `low_flags`・`_flags` を足すと再発を防げる。

##### 5. 「孫ごと止める」が ytt_core に無く、外に 4 つの実装がある(優先度: 中・削れる行数の目安: 外 約 40 行)
- 場所: `src/ytt_core/tools.py:24-31`(今あるのは kill_quiet だけ)
- 今: yt-dlp(PyInstaller の exe で、中で子を作る)を taskkill /T /F で止める処理が 4 か所にある: `src/home/live.py:139-156`・`src/home/live_excite_worker.py:488-509`・`src/studio/common.py:391-411`・`src/editor/ed_ytcap.py:151-163`。細かいところが違う(System32 の taskkill をフルパスで呼ぶか・POSIX で killpg を使うか・待つ秒数)。kill_quiet の写し(try: p.kill() except OSError)も 8 か所ある(吸い上げ G)。
- 案: tools に `kill_tree(proc, wait=None)` を置く。Windows は System32 の taskkill /T /F のあと kill_quiet、それ以外は killpg(SIGKILL) のあと kill_quiet。wait があれば待つ(TimeoutExpired は握る)。いちばん慎重な live_excite_worker の版(Popen でなければ kill だけ・taskkill のフルパス)を正にする。
- 理由: 「親だけ止めると子が .part に書き続ける」類の直し(live_excite_worker の説明 489-490 行)を、全ツールに効かせられる。
- 影響・リスク: studio の POSIX は SIGTERM → 猶予 → SIGKILL の 2 段なので(common.py:415)、置き換えるのは hard_kill の部分だけ。taskkill をフルパスにすると、PATH を差し替えた環境での動きが変わる(良い方向)。テスト: TestTools に偽の Popen で 1 件足す。home の test_live*・studio の test_robustness・editor の ed_ytcap のテスト。

##### 6. excite の式の数字が一括と配信中の 2 か所にある(優先度: 中・削れる行数の目安: ±0 行(定数の行が増え、写しが消える))
- 場所(一括 ↔ 配信中):
  - 音とチャットの重み・幅・下限: `src/ytt_core/excite.py:84,87`(audio_score の 0.6/0.4・smooth 3・floor 1.5)・`:94,97`(chat_z の smooth 9・floor 0.25) ↔ `:359-361,372,374`(Online の同じ値)
  - 確定した区間の前後: `:173`(pick_clips の -5 / +6) ↔ `:464`(EXCLUDE_BEFORE/AFTER)
  - 山の前後 6 秒: `:201`(candidates の ±6) ↔ `:613,616,674`(PeakBook の ±6)
  - 山を探す前のならし: `:157`(smooth(total, 5)) ↔ `:517-523`(_smooth5)
  - 静かな所を探す幅: `:160`(smooth(level, 3)) ↔ `:679,682,687`(snap_quiet の radius 4 と smooth 3)
- 今: アーカイブと配信中が「同じ式」であることを、同じ数字を 2 か所に書いて保っている。片方だけ直すと golden か test_online_total_and_resume が落ちるので気づけるが、そのテストも同じ数字を自前で持っている(test_excite.py:116・142-147)。数字は全部で 3 か所にある。
- 案: `AUDIO_PARTS = ((3, 0.6), (3, 0.4))`・`AUDIO_FLOOR = 1.5`・`CHAT_SMOOTH, CHAT_FLOOR = 9, 0.25`・`PICK_SMOOTH = 5`・`PARTS_RADIUS = 6`・`SNAP_RADIUS = 4` をファイルの上に並べ、両方から読む。pick_clips は EXCLUDE_BEFORE/AFTER を使う(定義を pick_clips より上へ移す)。テストも定数を読む。
- 理由: 「式は excite.py の 1 か所」(AGENTS.md)をファイルの中でも 1 か所にする。PART_ON・SENS と同じ扱いになる。
- 影響・リスク: 値・加算の順・丸めは変わらないので、golden(excite_golden.json)は一致したまま。テスト: test_excite の TestGolden・TestOnline・TestPeakBook、studio の test_analyze・e2e_analyze、dev/tests/test_eval_marks.py。

##### 7. excite の中の小さな写し(区間を静かな所へ合わせる・冒頭の減点・古い鍵を消すループ)(優先度: 中・削れる行数の目安: 約 12 行)
- 場所: `src/ytt_core/excite.py:168-171` と `:688-691`(区間を合わせる 4 行)、`:139` と `:391-392`(head_ramp の式)、`:334-335・339-340・397-398・604-605・806-807`(`for k in [k for k in d if k < X]: del d[k]` が 5 回)
- 今: 区間の合わせ方(長さの 0.7〜1.3 倍で、山を含む)を pick_clips と PeakBook._snap が別々に書いている。冒頭の減点の 2 乗の式も 2 か所。辞書の古い鍵を消すループは 5 回ある。
- 案:
  ```
  def snap_region(lows, s, e, peak, n, length):
      s2, e2 = snap_quiet(lows, s, n), snap_quiet(lows, e, n)
      return (s2, e2) if length * 0.7 <= e2 - s2 <= length * 1.3 and s2 < peak < e2 else (s, e)
  def ramp(t, head): return min(1.0, t / head) ** 2
  def _drop_before(d, k0):
      for k in [k for k in d if k < k0]: del d[k]
  ```
- 理由: 区間の規則を 1 か所にまとめる(配信中とアーカイブで候補の区間がずれない)。
- 影響・リスク: 浮動小数の計算は同じ順になる(`v * ramp(i, head)` は `v * min(...) ** 2` と同じ)ので、golden は一致したまま。_snap は合わせなかったとき元の start/end(すでに round 済み)をもう一度 round するだけで、値は同じ。テスト: test_excite 全部(golden の snap・TestPeakBook の区間)。

##### 8. txindex.use_packs_dir は datadir.prepare と同じ登録をもう 1 回している(優先度: 中・削れる行数の目安: 約 6 行 + 呼ぶ側 1 行 + テスト 3 行)
- 場所: `src/ytt_core/txindex.py:175-179`(呼ぶ側は `src/cut2resolve/serve.py:912`)
- 今: cut2resolve の _choose_work_dir は、datadir.prepare(env を渡さないので登録もする)の直後に use_packs_dir(base/packs) を呼ぶ。use_packs_dir は dirname で同じ base を datadir.register し直す。prepare の state が inplace・failed のときも、r["dir"] と base は同じ(abspath)。説明にも「今は念のため」とある。
- 案: use_packs_dir を消し、cut2resolve/serve.py:912 も消す。test_ytt_core.py:949・951・958 は datadir.register("cut2resolve", …) に置き換える。
- 理由: 置き場所を登録する入口を datadir.register / prepare の 1 つにする(「置き場所の求め方はここ1か所」)。
- 影響・リスク: 動きは同じ。テスト: TestTxIndex.test_registered_dirs_are_read_by_other_tools(置き換える)・cut2resolve の test_serve(packs_dir を読む 5 件)・editor の e2e_edit_pack。

##### 9. 到達しない except(isfile・isdir は例外を上げない)(優先度: 中・削れる行数の目安: 約 8 行)
- 場所: `src/ytt_core/schemas.py:69-77`(find_sidecar)・`src/ytt_core/pick.py:55-65`(initial_dir のループ)
- 今: os.path.isfile / isdir を try/except (OSError, ValueError) で囲んでいる。Python 3.8 以降の isfile・isdir は OSError と ValueError(NUL を含むパス)を中で握って False を返す(3.10.11 で `os.path.isfile('a\0b')` と isdir が False になることを確認した)。
- 案: find_sidecar は `return next((p for p in sidecar_candidates(media_path, suffix) if os.path.isfile(p)), None)` の 1 行にする。initial_dir は try を外す(`for _ in range(40)` を、親が自分と同じになったら "" を返す `while True` にしてもよい)。
- 理由: 過剰な防御を外し、読む人が「何が起きうるのか」を探さずに済むようにする。
- 影響・リスク: 動きは同じ(abspath も、3.10 の ntpath では ValueError を中で握る)。文字列でないパス(TypeError)は、どちらも元から握っていない。テスト: TestSchemas(find_sidecar 3 件)・TestPick・editor の test_edit。

##### 10. txindex の細かい書き方(優先度: 低・削れる行数の目安: 約 6 行)
- 場所: `src/ytt_core/txindex.py:147-161`(offset の usable と、その呼び方)・`:75` と `:236`(int で bool でなければその値、違えば 0)・`:251-254`(is_pack_dir)
- 今: usable は validate_clip の結果を `(c or {}).get(...) if c else None` → `if c and (...)` と 2 回確かめている。呼ぶ側も `usable(x) if x else None` で None を避けているが、validate_clip は dict でないものに (None, 理由) を返すので、この分岐は要らない。updatedAt / builtAt の「int で bool でない」の判定も 2 か所にある。
- 案:
  ```
  def usable(c):
      c, _ = schemas.validate_clip(c)
      src = c.get("source") if c else None
      return c if c and (not isinstance(src, dict) or src.get("videoId") in (None, "", video_id)) else None
  c = usable(doc.get("clip"))
  ```
  `_ms(v)`(`v if type(v) is int else 0`)を 1 つ置いて、75 行と 236 行から呼ぶ。
- 理由: 紐づけの規則の 1 か所(txindex)を読みやすく保つ。
- 影響・リスク: 動きは同じ(validate_clip(None) は None を返す)。テスト: TestTxIndex の offset(6 件)・pack_info(10 件)・is_pack_dir(4 件)。

##### 11. colors.load の入れ子と、path の関数の写し(優先度: 低・削れる行数の目安: 約 6 行)
- 場所: `src/ytt_core/colors.py:119-151`(load。for → if → for → if → if の 5 段)・`:39-48`(mine_path と member_colors_path)・`:127-128` と `:138-139`(`h, name = norm_hex(...), str(...).strip()` → `if h and name`)
- 今: マイカラーとメンバーの 2 つのループが、同じ「hex と名前を取り出して両方あるか」を書いている。メンバーの側は入れ子が 5 段ある。mine_path と member_colors_path は、ファイル名が違うだけ。
- 案: `_hex_name(m)`(→ (hex, name) か None)と `_member_entry(m, group_name, fixed)`(→ 項目 か None)に分け、load は 2 つの内包表記に近い形にする。`_holo_file(env, name)` を 1 つ置き、2 つの path の関数はそれを呼ぶ。
- 理由: 入れ子を浅くし、字幕の色の優先順位「直した色 > subtitle > hex」を 1 つの関数に収める。
- 影響・リスク: 動きは同じ。テスト: TestColors(load・lookup・speaker_colors・resolve)・cut2resolve の test_pack(色)・home の test_autorun。

##### 12. runtime の読みの写しと self_path の確かめ直し(優先度: 低・削れる行数の目安: 約 5 行)
- 場所: `src/ytt_core/runtime.py:67-72` と `:87-91`(runtime_path → read_json_file → except)・`:146-153`(siblings)
- 今: read_runtime と remove_runtime が同じ読みを書いている。siblings は valid_path(self_path) を 148 行と 153 行で 2 回確かめ、153 行はループの中で毎回確かめる。
- 案: `_load(rdir, tool)`(→ (パス, 中身) か (None, None))を 1 つ置く。siblings は先頭で `self_path = self_path if valid_path(self_path) else "/"` を 1 回だけにする。
- 理由: 「.runtime は誰でも書けるので信用しない」読みを 1 か所にまとめる。
- 影響・リスク: 153 行の比較は正規化したあとの値と同じなので、動きは同じ。テスト: TestRuntime(read_runtime 7 件・remove_runtime 3 件・siblings 9 件)。

##### 13. 使われていない定数・関数(優先度: 低・削れる行数の目安: 約 12 行 + テスト 3 行)
- 場所: `src/ytt_core/normalize.py:33`(TARGET = "30/1"。どこからも読まれない)・`src/ytt_core/excite.py:465`(PEAK_STATES。どこからも読まれない)・`src/ytt_core/colors.py:80-85`(rgb01。呼ぶのはテストだけ。cut2resolve は自前の resolve_textplus.hex_rgba を使う)・`src/ytt_core/loudness.py:49-50`(db_to_pct。呼ぶのはテストだけ)・`src/ytt_core/excite.py:817` と `:825-826`(PeakBook の fast を 1 項目ずつ写している)
- 案: 前の 4 つを消し、rgb01・db_to_pct のテスト(test_ytt_core.py:1079-1081 と 1219 の一部)も消す。PeakBook.to_json の "fast" は `dict(self.fast)` にする。
- 理由: dev/lint.py の死んだ関数の検査はテストからの呼び出しも数えるので、これらは当たらない。
- 影響・リスク: rgb01 は「Resolve の色は 0〜1」という規則の説明も兼ねている。残すなら、先に cut2resolve 側の写し(resolve_textplus.py:90)を hex_rgba に寄せる(cut2resolve は単独のコマンドで ytt_core を読まない決まり)。テスト: TestColors・TestLoudness・test_excite の to_json の往復。

##### 14. evaldata.check_zip の 8 つの「足して continue」(優先度: 低・削れる行数の目安: 約 8 行)
- 場所: `src/ytt_core/evaldata.py:305-332`、`:307-308`(正規表現をその場で書いている。`_PATH_SEP` は 49 行にすでにある)、`:194`(work_id_of の正規表現)
- 今: zip の中身 1 件ごとに、8 種類の検査を `problems.append(...); continue` で並べている。
- 案: `_entry_problem(info, ok)`(→ 最初に当たった問題の文 か None)を出し、ループは「問題があれば足す・無ければ ok に入れる」の 4 行にする。307 行は `_PATH_SEP.split(name)` にする。
- 理由: 検査の順番(危ない名前 → フォルダ → 想定外 → 重複 → 暗号化 → リンク → 大きさ → 圧縮率)が、上から読める関数になる。
- 影響・リスク: 最初に当たった問題だけを足すのも同じなので、動きは同じ。evaldata を使うのは今は dev だけ。テスト: test_evaldata の zip の 4 件・dev/tests/test_eval_import.py。

##### 15. datadir._prepare と normalize._float の小さな整理(優先度: 低・削れる行数の目安: 約 4 行)
- 場所: `src/ytt_core/datadir.py:212-214`、`src/ytt_core/normalize.py:101-106`
- 今: _prepare は、以前の場所の lexists を todo と state の判定で 2 回走査している。_float は `v == v and v not in (inf, -inf)` で有限かを確かめている。
- 案: `present = [n for n in items if lexists(legacy/n)]` → `todo = [n for n in present if not lexists(new/n)]` → `state = "done" if present else "new"` にする。_float は `return v if math.isfinite(v) else None` にする。
- 理由: 読みやすさのため。移行の経路は「コピーのみ・元は残す」のままで、判定の中身も同じ。
- 影響・リスク: 動きは同じ。テスト: TestDatadir(prepare 16 件)・test_normalize。

#### 吸い上げの候補
表記は「ファイル:行 — 説明」。「疑い」は中身や既定値が少し違うので、寄せる前に確かめるもの。「意図的」は寄せない理由があるもの。

**A. 「読めなければ既定値」の JSON 読み**(指摘 2 の fsio.read_json_or。お手本は dev/_evalcommon.py:32 の read_json)
- src/home: appwindow.py:130・142 / backup.py:207 / cleanup.py:144・157 / launch.py:956 / live.py:225・244 / live_tx.py:341 / accuracy.py:190・284・418
- src/editor: ed_drill.py:136 / ed_jobs.py:2912 / ed_learn.py:27・445・624・881・1138・1227・1296 / ed_misc.py:135・160・294 / ed_speakers.py:1061 / ed_state.py:293 / ed_store.py:176・352・405・437 / roster.py:49 / tx_engines.py:277・377
- src/studio: analyze.py:393・695 / common.py:189・549 / rank.py:269・284 / store.py:407・1101
- src/recorder: recorder.py:85
- src/cut2resolve: serve.py:338
- dev: count_sparse_rows.py:35 / eval_fetch.py:239 / eval_import.py:126・309 / eval_split.py:58・136・148・246・365 / _evalcommon.py:34(お手本そのもの → ytt_core へ移す)
- どれも `try: with open(...) as f: json.load(f)` + `except (OSError, ValueError)` の形。AttributeError・TypeError も握っているもの(studio/analyze.py・common.py・store.py:407・dev/eval_split.py)は、`.get` の失敗まで握っている。kind=dict で置き換えられるはず(疑い)

**B. 更新日時と大きさのキャッシュ**(指摘 3 の fsio.stamp / StampCache)
- src/editor/ed_state.py:155-161(file_stamp。editor の中だけにある同じ小道具)
- src/editor/ed_store.py:176-183・235 / src/editor/roster.py:40-48 / src/editor/ed_jobs.py:1720-1730(roster_hash)
- src/home/live_detect.py:347-354(series) / src/home/live_excite_worker.py:400-406(長さの目安)・1154

**C. 一時ファイル + os.replace の自前の書き込み**(fsio.atomic_write / write_json / replace_retry)
- src/home/backup.py:214-220(_save_state → `fsio.write_json(path, obj, indent=None)`)
- src/home/live_tx_worker.py:58-61(結果の json → fsio.write_json。この時点で src は sys.path に入っている)
- src/editor/pipeline_io.py:251-259(_temp_in + _replace_retry + 自前の unlink。中身は fsio.atomic_write と同じ。fsync を必須にしたいなら fsync_required=True)
- src/editor/tx_engines.py:225・src/editor/ed_learn.py:1111(ダウンロードや ffmpeg の出力の .part の置き換え → fsio.replace_retry にすると、Windows の一時的なロックでやり直せる)
- dev/_evalcommon.py:137-140 / dev/eval_cloud.py:257-259 / dev/eval_import.py:141-145 / dev/dropbox_auth.py:108-112(鍵のファイル。mode=0o600 も付けられる) / dev/sync_ui_kit.py:35-39(改行はそのまま = `atomic_write(path, text.encode("utf-8"))`)
- 意図的: src/cut2resolve/srt2resolve.py:54-80(_replace_retry・write_bytes_atomic)・cut2resolve_core.py:545・758・846。cut2resolve の単独のコマンドは ytt_core 無しで動く決まり

**D. ログの 1 世代の回し**(src/home/launch.py:145 の rotate を、fsio.rotate(path, limit, old=None) として ytt_core へ)
- src/cut2resolve/serve.py:121-122 / src/home/clientlog.py:30-34 / src/home/live_detect.py:274-278 / src/recorder/recorder.py:116-121
- 疑い: 回した先の名前が 2 種類ある(.old.log と、clientlog の .1)

**E. creationflags の自前の組み立て**(指摘 4)
- src/editor/ed_evalaudio.py:128-132(_flags = 窓なし + 通常より下) / src/editor/ed_jobs.py:136-140(_worker_flags。no_window_flags(new_group=True) と同じ) / src/editor/ed_ytcap.py:145-148(_ytcap_flags)・157
- src/home/live_export.py:1291-1294(low_flags。tools を使っているが優先度だけ自前。live_detect.py:284 も呼ぶ) / src/home/accuracy.py:339 / src/home/live.py:1074(通常より上)
- src/studio/common.py:319・597 / dev/eval_split.py:107

**F. 孫ごと止める**(指摘 5 の tools.kill_tree)
- src/home/live.py:139-156(kill_tree) / src/home/live_excite_worker.py:488-509(kill_tree) / src/studio/common.py:391-411(_signal_tree・hard_kill) / src/editor/ed_ytcap.py:151-163(_ytcap_kill)

**G. kill_quiet の写し**(try: proc.kill() except OSError: pass)
- src/editor/ed_jobs.py:262-268(kill_quiet とまったく同じ) / src/home/live_tx.py:226-231(同じ) / src/home/launch.py:417-420 / src/home/live_archive.py:163-166 / src/home/live_export.py:1108-1111 / src/recorder/rec_core.py:653-654 / src/studio/common.py:408-411 / src/editor/ed_ytcap.py:160-163
- 意図的: src/cut2resolve/cut2resolve_core.py:304・326(単独のコマンド)

**H. unlink_quiet の写し**
- src/editor/ed_state.py:147-152 — fsio.unlink_quiet と名前も中身も同じ写し。lint の DUP_HELPERS に "unlink_quiet" が無いので当たらない。editor の中の 9 か所が呼んでいる → `unlink_quiet = _fsio.unlink_quiet` にするか、直接呼ぶ
- 同じ try/os.unlink/pass の形: src/editor/ed_evalaudio.py:156・247 / ed_jobs.py:1911(FileNotFoundError だけ)・2938 / ed_relink.py:642 / ed_state.py:302 / ed_store.py:394 / pipeline_io.py:255 / src/home/backup.py:147・347 / intake.py:742・787 / launch.py:459 / src/studio/exporter.py:219 / store.py:426 / dev/eval_fetch.py:227 / dev/eval_speakers.py:909
- 意図的: src/cut2resolve/cut2resolve_core.py:363・srt2resolve.py:77

**I. ffprobe の直書き**(normalize.probe で足りる)
- src/home/intake.py:129-146(probe_video。音声の有無と長さ → probe の has_audio・duration。疑い: 今の flags は窓なしだけで new_group が無く、-show_entries も少ない)
- dev/eval_split.py:99-110(probe_sec → `(normalize.probe(path) or {}).get("duration")`)
- 意図的: src/cut2resolve/srt2resolve.py:210・222・cut2resolve_core.py:437(単独のコマンド)

**J. /api/ping の直書き**
- src/studio/serve.py:483-495(probe → `r = runtime.ping(port, 1); return r["version"] if r and r["app"] == APP_ID else None`。editor/serve.py:648 はすでに runtime.ping を使っている)

**K. httpsec.send / send_head の写し**
- src/cut2resolve/serve.py:672-683(_send → httpsec.send に `extra={"Referrer-Policy": "no-referrer", **(extra or {})}`。疑い: 見出しの順が少し変わる)
- src/editor/serve.py:350-358(_send_zip)・496-504(範囲つきの動画の応答。studio の _media と同じく send_head + extra にできる)
- 疑い: src/recorder/recorder.py:158-164(_head。Cache-Control を変えるので、send_head に cache の引数が要る)

**L. 数の検査(schemas.num の写し)**
- src/studio/exporter.py:337-341(_num_sec。num と同じ) / src/editor/ed_store.py:538-543(_real。num と同じ) / src/home/live_excite_worker.py:263-265(_num) / src/home/live.py:730 / src/home/live_export.py:324 / src/home/accuracy.py:80-81(_int)
- 疑い: src/home/autorun.py:233(上限 1e7 つき)
- 「int で bool でない」の判定は、src と dev に 36 か所ある(`type(v) is int` か schemas.is_int(v) にする)。ytt_core の中でも evaldata.py:224・228・272、txindex.py:75・236

**M. 外部プログラムの場所の環境変数(tools.find_tool の env_var)がばらばら**
- YTT_FFMPEG / YTT_FFPROBE / YTT_YTDLP(home/health.py・live_archive.py・live_detect.py・live_export.py・live_tx.py・recorder/rec_core.py・ytt_core/normalize.py)、TRANSCRIBE_FFMPEG(editor/ed_state.py:310)・TRANSCRIBE_YTDLP(ed_ytcap.py:139)、STUDIO_*(studio/common.py:86-88 が組み立てる)
- 環境変数なしで呼んでいる所: src/home/deliver.py:252 / intake.py:131・153 / live.py:168 / live_archive.py:221・269 / dev/eval_split.py:101。shutil.which を直接使う所: src/cut2resolve/serve.py:985
- 案: find_tool の既定の環境変数を `"YTT_" + name.upper().replace("-", "")` にし、ツール固有の名前は互換として 2 番目に見る。疑い: 今は効いていない所にも YTT_FFPROBE などが効くようになる(テストの偽物の差し替えが効く範囲が広がる)

**N. 作業データや他のツールのデータの置き場所**
- dev/eval_import.py:54-58(default_dest。LOCALAPPDATA・XDG を自前で見ている → datadir.data_root()。疑い: YTT_DATA_DIR=inplace と macOS の扱いが変わる)
- src/home/launch.py:954-963 と src/home/live.py:222-233(スタジオの settings.json の outDir を読む同じ処理が 2 つある。txindex と同じく「他のツールのデータを読むだけ」の部品として ytt_core へ。疑い: launch は isabs を確かめず、読めないときの戻り値も違う)

**O. 途中のファイル(付き物)の名前の一覧**
- src/home/cleanup.py:30(SIDECARS)・375(_media_stem の中の一覧) / src/editor/ed_relink.py:518(EVAL_SIDECARS)→ schemas に 1 つ置く(schemas.py:39-40 の説明にも同じ一覧がある)。疑い: 3 つとも中身が少しずつ違う(_edit.clip.json・.studio-id の有無)
- src/home/cleanup.py:76-85(_sidecars。作業用/ と隣を探す → schemas.sidecar_candidates)

**P. その他**
- src/home/health.py:122-133 と src/studio/common.py:590-601(外部プログラムの版を調べる処理が 2 つある → tools.tool_version)
- dev/demo_env.py:139(txindex.pack_dir の写し) / dev/eval_import.py:148-149(_now。schemas.iso_now と同じ) / dev/eval_timing.py:129-134(_median。疑い: 丸めと空のときの値が excite.median と違う → statistics.median + round)
- src/editor/pipeline_io.py:60-73・213-215・273-311(ytt_core の名前の別名と、runtime への薄い包み。呼ぶ側が ytt_core を直接呼べば消せる。editor の担当)
- src/cut2resolve/resolve_textplus.py:90(同じファイルの hex_rgba(70 行)を使わず、同じ式を書いている。ytt_core.colors.rgb01 とも同じ式)
- 疑い(読みやすさだけ): `os.path.normcase(os.path.abspath(x))` が src に約 35 か所ある(editor/ed_misc.py に 8・ed_relink.py に 8 など)。home/backup.py:44(_norm)も同じ → fsio.path_key(p) にまとめる(txindex.norm は、空のときに "" を返す版)


### G11 portal+ui-kit+chrome-ext(担当: src/home/portal.js 2,234 行・src/ui-kit/ui-kit.js 2,404 行・src/ui-kit/styleguide.js 126 行・chrome-ext/yt-studio-time/main.js 189 行、合計 約 4,950 行)

#### 全体の傾向
- portal.js は「ui-kit が無いときの予備」を今も全部持っている(`window.UIKit &&` が 41 か所。予備の道に visibilitychange の直接利用・window.confirm も)。portal.html:7 で ui-kit.js を同期で読み、portal.js は :10 で defer なので、予備の道には入らない。
- 同じ形の処理を「欄ごとに書き写した」所が多い: まとめて実行の追跡の 4 本のループ・依頼の受付とバックアップの 2 つの欄・案件と単体の文字起こしの「もっと見る」。表か小さな関数 1 つにできる。
- ui-kit は fetch の包みが 6 通りあり(yttPost・txPatch・arHomeApi・packLoud.get・arLoad・restartPing)、さらに各ツールにも「入口の API」の包みが 3 つある(portal・editor・studio)。要素を作る小道具も 3 つ(arEl・liveEl・dialogBtn)が別々。
- 古いブラウザへの備え(CustomEvent の try/catch・window.fetch / BroadcastChannel / MutationObserver の有無・addListener)は、対象が Edge / Chromium だけなので要らない。ui-kit の「ES5 のまま」(ui-kit.js:2)は書き方(var・function)の決まりで、Promise・Object.assign・URL などはもう使っている。下の案は ES5 の書き方のまま書ける。
- XSS(観点 f): portal.js は文字をすべて textContent で入れている(innerHTML は UIKit.icon の決まった SVG だけ: 152・488)。ui-kit の innerHTML(tools.render 236-246・appnav 571-574・datalist 453・keybar 963・keymap 1396-1435)は全部 esc を通している。直すべき所は見つからなかった。chrome-ext は innerHTML を使わない(Trusted Types の対策。AGENTS.md)。

#### 指摘

##### 1. ui-kit の fetch の包みが 6 通り → 1 つにして、入口の API の包みを UIKit.homeApi として出す(優先度: 高・削れる行数の目安: ui-kit で約 20 行 + 各ツールで約 25 行)
- 場所: `src/ui-kit/ui-kit.js:281-290`(yttPost)・`:1618-1622`(txPatch)・`:1656-1658`(packLoud.get)・`:1704-1710`(arHomeApi)・`:1714`(arLoad の中の fetch)・`:1910-1917`(restartPing)。同じ形がツール側にも: `src/editor/app-list.js:128`(portalApi)・`src/studio/core.js:43`(Studio.portalApi)・`src/home/portal.js:61`(api)
- 今: どれも「fetch → `r.json().catch(() => ({}))` → `!r.ok` なら Error(j.message || 'HTTP ' + status) を投げる」を自分で書いている。エラーに付ける項目(status・code・detail)だけが少しずつ違う。arHomeApi・editor の portalApi・Studio.portalApi は「`new URL('../' + path, location.href)` に送る」まで同じ
- 案:
  ```
  function jsonApi(url, body, opt) {   // body が undefined なら GET。opt: {keepalive, timeout}
    var init = { cache: 'no-store', credentials: 'same-origin', method: body === undefined ? 'GET' : 'POST', keepalive: !!(opt && opt.keepalive) };
    if (body !== undefined) { init.headers = { 'Content-Type': 'application/json', 'X-YTT-Token': token() }; init.body = JSON.stringify(body); }
    if (opt && opt.timeout) init.signal = AbortSignal.timeout(opt.timeout);
    return fetch(url, init).then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { if (!r.ok) { var e = new Error(j.message || ('HTTP ' + r.status)); e.status = r.status; e.code = j.error; e.detail = 'HTTP ' + r.status; throw e; } return j; }); });
  }
  ```
  yttPost = `jsonApi('api/ytt/' + name, obj, {keepalive})`、arHomeApi = `jsonApi(new URL('../' + path, location.href).href, body)`。arHomeApi を `UIKit.homeApi` として出せば、editor の portalApi・Studio.portalApi は 1 行の別名にできる
- 理由: エラーの形(status・code・detail)がツールごとにずれる原因が 1 か所に集まる。「合言葉が無いときは送らない」などの決まりも 1 か所になる
- 影響・リスク: エラーの項目を和集合(message・status・code・detail・data)にすれば呼ぶ側は変わらない。ただし接続できなかったときの文言はツールごとに違う(「ホームのサーバーに接続できません…」など)ので、包みの外で付け直す。ui-kit を直したら `py -3.10 dev/sync_ui_kit.py` で写す。テスト: `src/ui-kit/tests/e2e_styleguide.py`(restart 28 か所)・`src/home/tests/e2e_autorun.py`・`src/editor/tests/e2e_edit_pack.py`(packLoud)・`e2e_ui_mounted.py`・`dev/tests/test_ui_kit_sync.py`

##### 2. pollAuto の同じ形の 4 本のループ → 1 つの関数(優先度: 高・削れる行数の目安: 約 14 行)
- 場所: `src/home/portal.js:1693-1718`
- 今: latestF・latestP・latestV・latestD のそれぞれに「active なら anyActive・前は active で今は違えば finished・wasActiveX を更新」を 4 回書いている(違うのは対象の 2 つの表だけ)
- 案:
  ```
  function track(latest, was) { Object.keys(latest).forEach(function (id) {
    var on = active(latest[id]); if (on) anyActive = true; if (was[id] && !on) finished = true; was[id] = on; }); }
  track(latestF, wasActiveFile); track(latestP, wasActivePost); track(latestV, wasActiveVideo); track(latestD, wasActiveDoc);
  ```
- 理由: 実行の種類が増えるたびに 6 行ずつ増える形をやめる。読み手が 4 つの違いを探さなくてよい
- 影響・リスク: 動きは同じ(pollAuto の中の関数にすれば anyActive・finished をそのまま閉じ込められる)。テスト: `e2e_autorun.py`・`e2e_portal.py`(pt-auto-run・pt-auto-cancel)・`e2e_intake_ui.py`(依頼の file の実行)

##### 3. portal.js の「ui-kit が無いとき」の予備を全部外す(優先度: 高・削れる行数の目安: 約 25 行 + 41 か所の条件が短くなる)
- 場所: `src/home/portal.js` の `window.UIKit &&` 41 か所(例: 80・95・122・152・172・315・319・345・374・400・484・488・599・655・658・662・670-671・677・711・713・714・746・793・1042・1229・1250・1319-1321・1327・1553・1585・1816・2147・2153-2162・2187・2193・2215・2228)。予備の道: `:2229`(visibilitychange の直接利用 = AGENTS.md の決まりに反する形)・`:1321`(window.confirm)・`:18` と `:746`(STEP_STATE = ui-kit の AR_STEP の写し)・`:685`・`:1251`・`:1258`(autorun が無いときの直接の POST と知らせ)・`:714`(ago の予備)
- 今: portal.html:7 が `<script src="/ui-kit.js">` を同期で、:10 が portal.js を defer で読むので、portal.js が動くときには必ず window.UIKit がある。予備の道は通らない
- 案: 条件を外して `UIKit.toast(...)`・`UIKit.autorun.start(...)` と直接呼ぶ。`toast()`・`twice()`・`ago()`・`runLabel()` の包みも中身 1 行になる(残すなら名前のためだけ)。STEP_STATE・予備の分岐・visibilitychange・window.confirm は消す
- 理由: 41 か所の条件を読むたびに「予備の道があるのか」を考えなくてよい。AGENTS.md の「visibilitychange を直接使わない」にも合う(今は予備の道にだけ残っている)
- 影響・リスク: ui-kit.js が読めなかったときに「一部が動かない」ではなく「例外で止まる」になる(そのときはヘッダーも描けないので、今も使える状態ではない)。同じ予備は editor(`src/editor/app.js:98`)・studio(`src/studio/review.js:3672`)にもある(下の一覧)。テスト: `e2e_portal.py` 全体・`e2e_autorun.py`・`e2e_window.py`
- 要確認: `TODO_ORDER`(`:1679`)・受付やバックアップの 404 で欄を隠す(`:1829`・`:1910`・`:2071`)も「古いサーバーのとき」の予備だが、ホームの画面とサーバーは同じプロセス・同じ版。テストが機能を切った入口を起動していないかを確かめてから消す

##### 4. 依頼の受付とバックアップの欄が同じ形の書き写し → 共通の小さな関数(優先度: 中・削れる行数の目安: 約 35 行)
- 場所: `src/home/portal.js:1752-1871`(受付)と `:1875-1952`(バックアップ)。開くボタン `:1073-1078` と `:1081-1086`
- 今: 次の組がほぼ同じ形で 2 回ずつある: 状態の札(`:1765-1767` / `:1885-1887`)・読む(404 なら欄を隠す・それ以外は札に「読めません」。`:1827-1832` / `:1907-1913`)・「今すぐ」(busy の旗・ボタン・終わったら札を描き直す。`:1833-1839` / `:1914-1921`)・設定を保存(`api('api/ytt/prefs', patch)`・文・失敗の知らせと [もう一度]。`:1849-1862` / `:1929-1943`)・入力で dirty(`:1868-1870` / `:1949-1951`)・最初の 1 回だけ開く(`:1821-1825` / `:1901-1905`)・開いて最初の欄へ(`openIntakeSettings` / `openBackupSettings` は id だけが違う)
- 案: `pollSection(path, boxSel, pillSel, what, render)`・`savePrefsSection(section, value, msgSel, what, next, onFail)`・`paintStatePill(sel, map, d, onText)`・`openSettingsBox(boxSel, folderSel, switchSel)` の 4 つにして、各欄はその呼び出しと固有の部分(受付の INTAKE_NUMS・バックアップの 30 秒の速い読み直し)だけにする
- 理由: 片方だけ直してもう片方を忘れる形をやめる(例: 保存の失敗でスイッチを戻す処理は、受付は partial のときだけ・バックアップはいつも、と既に少し違う)
- 影響・リスク: 上の「少し違う」所は意図か偶然かを決めてからそろえる(そろえると動きが変わる)。テスト: `src/home/tests/e2e_intake_ui.py`(intakeSave 7 か所)・`e2e_backup_ui.py`

##### 5. ホームの設定の読み書きを 1 か所に・試験中の機能のスイッチを表で(優先度: 中・削れる行数の目安: 約 15 行)
- 場所: `src/home/portal.js:1853`・`:1933`・`:2049`・`:2077`(`api('api/ytt/prefs', 'POST', {op: 'patch', ...})`)・`:2070`(op: 'get')。スイッチの配線 `:2098-2115`
- 今: 同じ要求の形を 5 か所で組み立てている。試験中の機能のチェック(配信後の全自動・配信中の候補・自動の採用)は「checked を読む → saveLiveTop({鍵: on}, on ? 文A : 文B)」を 3 回書いている
- 案: `function prefsPatch(section, value) { return api('api/ytt/prefs', 'POST', { op: 'patch', section: section, value: value }); }`。読むのは `UIKit.prefs.get(['live'])`(応答の prefs を返す部品がもうある)。スイッチは `[['#liveAfterStream', function (on) { return { autoAfterStream: on }; }, '配信が終わったら…', '配信後の…やめました'], …].forEach(...)`
- 理由: 設定の節の書き方が 1 か所になる。スイッチを足すときに表へ 1 行
- 影響・リスク: 書き込み(patch)を `UIKit.prefs.patch` に替えるのは不可: あちらは 400ms まとめてから送り・失敗の知らせを自分で出し・`j.value` を返さないので、知らせが二重になり renderLive(j.value) もできない。ローカルの関数にとどめる。テスト: `e2e_live.py`・`e2e_live_studio.py`(liveAfterStream・liveDetect・liveAutoAdopt)・`e2e_intake_ui.py`・`e2e_backup_ui.py`

##### 6. portal.js の fetch の周り: fetchT を標準の AbortSignal.timeout に・生の fetch 2 か所を api() に・パスの書き方をそろえる(優先度: 中・削れる行数の目安: 約 12 行)
- 場所: `src/home/portal.js:55-59`(fetchT)・`:403`(waitGone)・`:546-553`(markSeen の生の fetch と try/catch)・`:1131-1140`(loadTxList の生の fetchT)・API のパス(絶対 `/api/…` 15 か所と相対 `api/…` 8 か所が混ざっている)
- 今: 時間切れを AbortController と setTimeout・clearTimeout で自分で作っている。markSeen は keepalive のためだけに api() を使わず、合言葉と見出しを書き直している。loadTxList も ok の判定と json を自分で書いている
- 案: `init.signal = AbortSignal.timeout(ms)` で fetchT を消す。api() に `keepalive` の引数を足して markSeen を `api('api/cases/auto', 'POST', {...}, { keepalive: true }).catch(noop)` に。loadTxList は `api('transcribe/api/transcripts')`。パスは相対(`api/…`)にそろえる(ホームは `/` にあるので同じ URL になる・AGENTS.md の「絶対パス /xxx を書かない」に合う)
- 理由: 時間切れ・合言葉・エラーの形が api() の 1 か所になる。markSeen の外側の try/catch(fetch は同期で投げない)も要らなくなる
- 影響・リスク: AbortSignal.timeout の失敗は `AbortError` ではなく `TimeoutError` になるので、`:74` の判定を `e.name === 'TimeoutError' || e.name === 'AbortError'` に直す(忘れると「応答が遅れています」が「つながりませんでした」に変わる)。docHref・studioHref の `/transcribe/`・`/studio/` の直書き(`:760`・`:763`)は `/api/status` を読む前に使うので、今回は触らない(コメント `:854` のとおり別の課題)。テスト: `e2e_portal.py`(次にやること・単体の文字起こし・自動の切り抜きの「見た」)

##### 7. ui-kit の要素を作る小道具が 3 つ+長い createElement の列 → 1 つの mk() と選択肢の小道具(優先度: 中・削れる行数の目安: 約 40 行)
- 場所: `src/ui-kit/ui-kit.js:1748-1753`(arEl)・`:2241`(liveEl)・`:710`(dialogBtn)・`:1002`(addOpt)・`:1754-1759`(arSelect)・`:1681`(packLoud.mount の option のループ)。長い列: `:700-709`(buildDialogShell)・`:1003-1053`(buildGeneralSection)・`:1054-1071`(buildSettingsDrawer)・`:791-812`(toast)・`:2242-2260`(liveEnsure)・`:2294-2310`(liveMakeRow)
- 今: 「createElement → className → setAttribute を何回か → appendChild」を部品ごとに書いている。select の選択肢の作り方も 3 通り(addOpt・arSelect・packLoud.mount のループ)
- 案:
  ```
  function mk(tag, attrs, kids) {   // attrs の class・text・hidden・type は特別扱い、それ以外は setAttribute。kids は要素か文字の配列
    var el = document.createElement(tag); …; return el;
  }
  function fillOptions(sel, pairs) { for (var i = 0; i < pairs.length; i++) sel.appendChild(mk('option', { value: String(pairs[i][0]), text: pairs[i][1] })); return sel; }
  ```
  arEl・liveEl・addOpt・arSelect をこれに置き換える(ES5 の書き方のまま)
- 理由: 設定の引き出し・ダイアログ・録画の札の組み立てが木の形で読める。作る道具が 1 つになる
- 影響・リスク: 作る DOM は同じ(属性の順だけ変わりうる。テストは属性の順を見ていない)。テスト: `e2e_styleguide.py`(toast 48・dialog 13・drawer 9・settings 4・ui-live 42 か所)・`e2e_portal.py`・`dev/tests/test_ui_kit_sync.py`(写したあと)

##### 8. 編集の設定(api/settings)を 2 つの部品が別々に読んでいる → 覚えた 1 つの読み方に(優先度: 中・削れる行数の目安: 約 6 行・開くたびの要求が 1 つ減る)
- 場所: `src/ui-kit/ui-kit.js:1652-1661`(packLoud.get。3 秒覚える)と `:1713-1719`(arLoad。毎回 fetch・loud と vol を同じ loudNorm・volNorm でそろえ直す)
- 今: まとめて実行の「設定を変える」を開くと、arLoad が api/settings を読み、その中の音量の欄(packLoud.mount → loudRefresh)がもう一度 api/settings を読む(`:1879`)
- 案: `txSettings()`(api/settings を 3 秒覚える。今の loudGet の形)を 1 つ作り、packLoud.get は `txSettings().then(function (t) { return { loud: loudNorm(t.packLoudness), vol: volNorm(t.packVolume) }; })`、arLoad もそれを使う。保存(txPatch)のあとは覚えを捨てる
- 理由: 同じ値を 2 回読んで 2 回そろえる形をやめる。値が食い違う隙(片方だけ古い)も無くなる
- 影響・リスク: 動きは同じ(数字は同じ関数でそろえる)。テスト: `src/editor/tests/e2e_edit_pack.py`・`e2e_ui_mounted.py`・`src/home/tests/e2e_portal.py`(まとめて実行の設定)

##### 9. 共通の再生キーの if/else の列 → 操作 → 関数の表(優先度: 中・削れる行数の目安: 約 8 行)
- 場所: `src/ui-kit/ui-kit.js:1229-1246`
- 今: action ごとの else if が 10 段。うち 4 つは `if (media) { try { … } catch (er) { /* 無視 */ } }` を繰り返している
- 案:
  ```
  var ACT = { playPause: function (m) { if (m.paused) playQuiet(m); else m.pause(); }, back1: function () { seek(-1); }, stop: function (m) { m.pause(); m.playbackRate = baseRate(m); }, … };
  var fn = ACT[action]; if (fn && media) { try { fn(media); } catch (er) { /* まだ読み込めていない */ } }
  ```
  (markIn・markOut・frame は media が無くても呼ぶので、表の外か印を付ける)
- 理由: 操作を足すとき・PLAYBACK_ACTIONS と見比べるときに、表 1 つを見ればよい
- 影響・リスク: media が無いときに onIn・onOut・onFrame を呼ぶ今の動きを保つこと。テスト: `e2e_styleguide.py`(偽の media で Space・J・K・L・矢印・, .・I・O)・`src/home/tests/e2e_keymap.py`・編集とスタジオの e2e

##### 10. ui-kit の要らない防御と使われていない公開の名前(優先度: 低〜中・削れる行数の目安: 約 30 行)
- 場所(防御): CustomEvent の try/catch 5 か所 `:465`・`:630`・`:1637`・`:1745`・`:2057`/ `window.fetch` の有無 `:283`・`:1654`・`:1667`・`:2223`/ BroadcastChannel の有無 `:396`・`:409`・`:2368`/ MutationObserver `:190`/ mq.addListener `:113`/ AbortController の有無 `:1911-1917`(→ `AbortSignal.timeout`)/ checkVisibility の予備 `:627`/ setPaths の `typeof loudRefresh === 'function'`・`typeof live !== 'undefined'`(`:213`・`:216`。関数宣言と var は巻き上げられ、setPaths は IIFE が終わってからしか呼べないので常に真)/ hasOwnProperty のループ 11 か所(自分で作った普通のオブジェクト。例 `:2195`・`:2285`・`:2330`・`:2382`・`:2393` → Object.keys)/ kmCreate の `copy()`(`:1347` → `Object.assign({}, x)`。Object.assign は `:856` で既に使っている)/ pad2 と tbPad が同じ(`:252`・`:2013`)
- 場所(使われていない公開の名前。src・dev・chrome-ext とテストのどこからも呼ばれていない): `hide.count`(`:903-907`)・`portal.isOpen`・`keys.derived`・`packLoud.norm`・`autorun.summary`・`autorun.estimateText`・`autorun.STEP/RUN/MODES/CUT`・`restart.band`・`restart.run`・`sound.tool`・`theme.PALETTES`・`theme.syncButtons`(`:249`)・`tools.list`・`keymap.BLOCKED`
- 案: `function emit(target, name, detail, bubbles) { target.dispatchEvent(new CustomEvent(name, { bubbles: !!bubbles, detail: detail })); }` を 1 つにして 5 か所を置き換え。有無の確かめと typeof の条件を外す。使われていない公開の名前は、README.md に「公開の API」として載っているので、消すなら README も一緒に(残すなら今のまま)
- 理由: 「どのブラウザ向けか」が読み取れない防御を減らす。lint はトップレベルの関数しか見ないので、公開の表の中の使われない名前は検出されない
- 影響・リスク: 対象は Edge(アプリモード)と Playwright の chromium だけなので動きは変わらない。要確認: Tab を回す処理(`:678-679`)は drawerFocusables で見えるものを選んだあとに `offsetParent !== null` でもう一度絞っており、position: fixed の要素(offsetParent が null)を外す違いがある。意図か分からないので触らない。テスト: `e2e_styleguide.py` 全体・`dev/tests/test_ui_kit_sync.py`

##### 11. 一覧の描画: 「もっと見る」と件数の文が 2 回ずつ・同じ計算のやり直し(優先度: 低・削れる行数の目安: 約 10 行 + 描くたびの計算が減る)
- 場所: `src/home/portal.js:1020-1027`(案件)と `:1233-1238`(単体の文字起こし。`var rest = restN;` `:1236` は意味の無い写し)/ `:1152-1158`(docSearchList: 絞り込みと並べ替えの比較のたびに mergedDoc を作り直す = 比較の回数だけオブジェクトを作る)/ `:1221` と `:1232`(1 回の renderDocs で docSearchList を 2 回)/ `:935-943`(visible が案件 1 件ごとに #fStatus・#fText の値を DOM から読む。`:1023` でもう一度全件)
- 今: 件数の文「n / 全体 件(m 件を表示)」と「もっと見る(あと n 件)」を 2 か所で同じように組み立てている
- 案: `paintMore(boxSel, btnSel, rest)` と `countText(narrowed, n, total, shown)` の 2 つ。docSearchList は最初に `list.map(function (u) { return { u: u, d: mergedDoc(u) }; })` で 1 回だけ作ってから絞り込み・並べ替え。visible には絞り込みの値をまとめた 1 つのオブジェクトを渡す
- 理由: 同じ文言の 2 か所の食い違いを防ぐ。文書が多いときの並べ替えが軽くなる
- 影響・リスク: 動きは同じ。テスト: 案件の一覧は `e2e_portal.py`(#count・btnMore)で守られているが、**単体の文字起こしの検索・もっと見る・件数(#docSearch・#docMore・#docCount)はどの e2e も触っていない**ので、直すなら確かめを足す

##### 12. renderHealth が 84 行の 1 関数・同じしきい値と札の対応が 2 回(優先度: 低・削れる行数の目安: 約 8 行・読みやすさ)
- 場所: `src/home/portal.js:1376-1459`(renderHealth)・`:1397` と `:1429`(空き容量 10 GB 未満 = bad・30 GB 未満 = warn を 2 回)・`:1349-1350`(healthRow の状態 → 札の色と言葉の入れ子の三項演算子)
- 今: 版・文字起こしの処理・外部プログラム・空き容量・作業データ・エラー・異常終了・録画元・空き・失敗・検出・重い処理・精度を 1 つの関数の中で順に組み立てている
- 案: 節ごとの関数(`versionsRow(h)`・`workerRow(h)`・`diskRows(h)` …)の配列にして `ROWS.forEach(function (f) { [].concat(f(h) || []).forEach(append); })`。`diskState(freeBytes)` を 1 つ。札は表 `{ ok: ['ok', '問題なし'], bad: ['err', '要対応'], warn: ['warn', '注意'], info: ['info', '測定'] }`
- 理由: 節を足す・直すときに関数 1 つだけを見ればよい。しきい値の食い違いを防ぐ
- 影響・リスク: 出す行の順を保てば動きは同じ。テスト: `e2e_portal.py`(#healthList 3 か所)だけで、精度の行・#btnAccuracyNow・録画元の行は画面のテストが無い

##### 13. 録画の札の一覧が自前のポップオーバー(優先度: 低・削れる行数の目安: 約 20 行)
- 場所: `src/ui-kit/ui-kit.js:2257-2262`(外側のクリック・Tab で外へ・Esc で閉じる)・`:2264-2279`(開閉と、左にはみ出したときの置き場所)
- 今: ui-kit 自身にポップオーバーの部品(`details.ui-pop` + 外側のクリックと Esc `:124-137` + 置き場所の直し fitPop `:174-195`)があるのに、録画の一覧だけ同じことを別に書いている
- 案: 札を `<details class="ui-pop">` の summary、一覧を `.ui-pop-body` にする。1 秒ごとの時間の更新は toggle イベントで始めて止める
- 理由: 外側のクリック・Esc・はみ出しの決まりが 1 か所になる(片方だけ直す形をやめる)
- 影響・リスク: **動きが変わる**: 今は button + role=dialog の一覧・aria-expanded・開いたらフォーカスを一覧へ、で、`e2e_styleguide.py:361-378` がそれを確かめている。替えるならテストと読み上げの見直しが要る。押そうとしたボタンを消さないための差分の描き直し(liveRows)はそのまま使える

##### 14. styleguide.js: 見本の引き出しの作り方が 2 回・アイコンの名前の手書きの一覧が既にずれている(優先度: 低・削れる行数の目安: 約 15 行)
- 場所: `src/ui-kit/styleguide.js:28-59`(modal と docked の引き出しを同じ形で 2 回作る)・`:18-21`(ICON_NAMES)
- 今: `if (!drawerModal)` の条件は、styleguide.html に #drawerModalDemo・#drawerDockedDemo が無いので常に真(死んだ分岐)。ICON_NAMES は ui-kit.js の ICONS(`:1545-1594`)の手書きの写しで、**`lock`(ui-kit.js:1589)が抜けている**(見本の一覧に錠のアイコンが出ない)。`src/ui-kit/tests/e2e_styleguide.py:29` の ICON_NAMES にも同じく抜けている
- 案: `demoDrawer(id, title, hint, modal)` を 1 つ作って 2 回呼ぶ(条件は外す)。ui-kit に `icon.names = function () { return Object.keys(ICONS); }` を足し、見本とテストはそれを読む
- 理由: アイコンを足すたびに 3 か所を直す形をやめる(今まさに 1 つずれている)
- 影響・リスク: 見本に lock が増える(見た目が 1 つ増えるだけ)。テスト: `e2e_styleguide.py`(引き出し 589-597・アイコン 337・788)。テストの一覧も直すか、`UIKit.icon.names()` を読む形にする

##### 15. chrome-ext/yt-studio-time/main.js の小さな書き換え(優先度: 低・削れる行数の目安: 約 8 行)
- 場所: `chrome-ext/yt-studio-time/main.js:74-75`(debug() が log を呼ぶたびに localStorage を読む・arguments と apply)・`:113-117`(queryAll)・`:118-120` と `:134-141`(inRow と dateCellOf がそれぞれ「行と shadowRoot」を調べる)・`:90`(then の中で then と catch を入れ子)・`:33-35`(既定の引数を `||` で)・`:189`(`typeof globalThis` の確かめ)
- 今: すでに短いが、ES2015 以降の書き方(const・アロー関数・for…of)と古い書き方(arguments・`visited = visited || new Set()`)が混ざっている
- 案: `const DEBUG = debug(); const log = (...a) => { if (DEBUG) console.log('[' + TAG + ']', ...a); };`(README のとおり「入れて再読み込み」なので読み込み時に 1 回で足りる)/ `const scopes = row => row.shadowRoot ? [row, row.shadowRoot] : [row];` を inRow・dateCellOf で共用 / `queryAll = sel => [...roots].flatMap(r => [...r.querySelectorAll(sel)])` / `p.then(res => res.clone().text()).then(t => capture(url, t), () => {})` / `function harvest(obj, visited = new Set(), depth = 0)` / `})(globalThis);`
- 理由: 行ごとの処理(run が 1 行ずつ log を呼ぶ)で localStorage を読み続けない。shadow DOM の探し方が 1 か所になる
- 影響・リスク: 調べる印(yttStudioTimeDebug)を入れたあと再読み込みが要るようになる(README は既に再読み込みを案内している)。manifest の minimum_chrome_version 111・node 12 以上なので globalThis・flatMap・既定の引数は使える。権限なし・外部との通信なし・world: MAIN・innerHTML を使わない、は変わらない。テスト: `chrome-ext/yt-studio-time/tests/test_main.cjs`(harvest・choose・fmtTime など純粋な部分)・`tests/e2e_fake_studio.py`(画面の側)

#### 各ツールの画面にある、ui-kit の部品で置き換えられそうな自前の処理(ファイル:行 と 1 行の説明。「疑い」は明記)
**ui-kit に同じ部品がある(置き換えられる)**
- `src/studio/core.js:11` Studio.esc — UIKit.esc と中身が同じ(null の扱いも同じ)。`UIKit.esc` の別名にできる
- `src/editor/app.js:4` esc — UIKit.esc とほぼ同じ(疑い: null・undefined を "null"・"undefined" と出す点だけ違う)
- `src/editor/app.js:98` onLeave の予備(visibilitychange を直接)— UIKit.life があるので予備の道は通らない。AGENTS.md の決まりにも反する形
- `src/studio/review.js:3672` 同上(UIKit.life が無いときの visibilitychange)
- `src/home/portal.js:2229` 同上
- `src/home/portal.js:1321` window.confirm の予備 — UIKit.dialog.confirm がいつもある
- `src/editor/app-core.js:30` toast の予備(#toast に自分で文字を入れて消す)— UIKit.toast がいつもあるので通らない
- `src/editor/app.js:71-76` 外側のクリック・Esc で `details.pop[open], details.ui-menu[open]` を閉じる — ui-kit.js:124-137 が ui-menu・ui-pop を同じく閉じる(二重)。古い形の `details.pop` だけは ui-kit が閉じないので、ui-kit の POP_SEL に `details.pop[open]` を足せば消せる(疑い: 中のリンク `.ui-menu-pop a` を押したら閉じる動き・Esc で検索欄を空にする順番は編集だけの決まり)
- `src/home/portal.js:18`・`:746` STEP_STATE — UIKit.autorun.stepLabel(AR_STEP)の写し
- `src/home/portal.js:1679` TODO_ORDER — ui-kit ではなく cases.py の todoOrder の写し(古いサーバーの予備。要確認)
- `src/editor/app-list.js:128` portalApi・`src/studio/core.js:43` Studio.portalApi・`src/home/portal.js:61` api — ui-kit の arHomeApi(ui-kit.js:1704)と同じ形。今は公開していないので、指摘 1 の UIKit.homeApi を出せば置き換えられる
- `src/home/portal.js:55` fetchT と ui-kit.js:1910 restartPing — どちらも自前の時間切れ。標準の AbortSignal.timeout で済む
- `src/editor/app-core.js:150`・`src/studio/collab.js:11`・`src/studio/review.js:2319`・`src/home/portal.js:484` — UIKit.confirmTwice の薄い包みが 4 つ(スタジオの 2 つは中身も既定の文も同じ。Studio に 1 つでよい)
- `src/home/portal.js:181` tc(秒 → 1:23:45)— UIKit.fmt.dur とほぼ同じ(疑い: tc は切り捨て・fmt.dur は四捨五入なので 59.6 秒が 0:59 / 1:00 と変わる)
- `src/studio/review.js:2884` tickLabel — 上の tc と同じ(切り捨て)。UIKit.fmt.dur に寄せられる(疑い: 同じく丸め方)
- `src/studio/queue.js:12` mmss — 分:秒だけ(時を出さない)。UIKit.fmt.dur に寄せると 1 時間を超えたとき「1:02:03」になる(疑い: 経過時間の表示なので変わってよいか確認)
- `src/home/portal.js:186` when(月/日 時:分)— UIKit.fmt.date に近い(疑い: 時を 0 埋めしない・年をまたいでも年を出さない点が違う)
- `src/home/portal.js:1553`・`:1585` `UIKit.fmt.date(x).split(' ')[0]` を 2 か所 — 日付だけの書式を fmt に足すか、portal の中で関数 1 つに
- `src/home/portal.js:1265` fmtAgo(秒)— UIKit.fmt.ago(ミリ秒の時刻)と考え方が同じ(疑い: fmt.ago は「今日 12:34」・fmtAgo は「3 時間前」と出し方が違う)
- `src/studio/rank.js:508` fmtClock(昨日・明日 + 時:分)— UIKit.fmt.ago の「昨日 12:34」に近い(疑い: 明日がある・未来の時刻を扱う)
- `src/editor/app-core.js:24` uiIcon・`src/home/portal.js:152`・`:488` — UIKit.icon の有無を確かめる包み(いつもあるので確かめは要らない)
- `src/studio/core.js:13` Studio.fmtTime(0.1 秒まで)— UIKit.timebox.format(t, 'tenths') に近い(疑い: timebox の形はいつも時を出す・'short' は分が 60 を超えるので、そのままでは同じにならない)

**ui-kit に部品が無い(参考。置き換えではなく、ui-kit に足すなら効く所)**
- デバウンス(clearTimeout → setTimeout)約 20 か所: `src/editor/app-core.js:331`・`:470`・`src/editor/app-learn.js:8`・`:240`・`src/editor/app-rows.js:11`・`:13`・`:369`・`:543`・`src/editor/cut.js:189`・`:356`・`src/editor/pack-tab.js:451`・`src/studio/collab.js:348`・`src/studio/queue.js:105`・`src/studio/rank.js:478`・`src/studio/review.js:421`・`:533`・`:1100`・`:3329`(ui-kit の中にも `ui-kit.js:491`・`:866`)
- バイト数の書式が 3 つ: `src/home/portal.js:1264` fmtBytes・`src/studio/settings.js:68` fmtBytes・`src/editor/app.js:120` fmtSize(区切りと丸めが少しずつ違う)
- 自前の中身を持つダイアログ(showModal を直接): `src/editor/app-rows.js:946`・`src/editor/app-tools.js:20`・`:152`・`src/editor/cut.js:926`・`src/studio/core.js:258` — UIKit.dialog は文だけの確認・お知らせなので置き換えられない(そのままでよい)
- 要素を作る小道具: `src/home/portal.js:99` el・`src/editor/app-core.js:38`(showErr の中の el)— 指摘 7 の mk() を公開すれば共用できる
- ツール自身の API の包み: `src/editor/app-core.js:85` api・`:97` apiBlob・`src/editor/app-tools.js:597` c2rApi・`src/studio/core.js:28` Studio.api — 送り先の作り方がツールごとに違うので部品にはしないが、エラーの形は指摘 1 の jsonApi と同じにできる


### G12 dev-eval-A(担当: dev/eval_asr.py・dev/eval_speakers.py・dev/eval_marks.py・dev/_evalcommon.py・dev/eval_cloud.py・dev/eval_effort.py、合計 約 4,519 行)

調べた範囲: 担当 6 ファイルを全部読み、`src/ytt_core/evaldata.py`・`fsio.py`・`schemas.py` と、関係するテスト(`dev/tests/test_eval_{asr,speakers,marks,effort,cloud}.py` が使う名前)を突き合わせた。コード・テスト・git は触っていない。

#### 全体の傾向
- `_evalcommon.py` に吸い上げる作業は 2 周済みで、作業データの場所・時期・保存・`dist`・`load_serve` はすでに共通。**残っているのは「入口と出口」(引数の定義・保存して「保存: パス」を出す終わり方)と、小さな判定の写し(`num`・`is_reviewed`・`pct(x).strip()`・音声の出どころの選び方・文書フォルダの走査)**で、ファイルごとに 3〜5 個ずつ似た形が並んでいる。
- 一番の肥大は `eval_speakers.py` の `evaluate`(102 行)と `run_evaluate`(123 行)。同じ集計・メモ・meta 組み立てを 2 回書いていて、`dev/lint.py` の「同じ 12 行」には当たらないが、1 つ直すともう 1 つも直す形になっている。次が `eval_marks.build_videos`(125 行・入れ子 4 段・同じ 14 キーの dict を 4 回手書き)。
- 数字の意味に触れずに減らせる量の目安は **担当 4,519 行のうち 260〜300 行(約 6%)**。大きな性能問題は無い(O(D×G) の所はあるが文書 50 本・まとまり数千のサイズなので体感は変わらない)。直す価値は主に「1 か所直せば済む」ことの方。
- 見たが触らない方がよいもの: `hungarian_max`(49 行の手書きだが scipy は依存に無く、依存の追加は要確認。DP 化は人数が増えると遅い)・`dist` の分位点の手書き(`statistics.quantiles` で書けるが、3 桁に丸める境目で値が動きうる = 「測った値の意味は変えない」に反する)・`eval_speakers` が editor の定数(`OTHER_VOICE_*`・`DRAFT_NAME`・`is_reviewed`)を二重に持つこと(editor を読み込まない方針による意図的な写し)・`eval_asr.load_friend_docs`(63 行だが流れが一本道)。
- 注意: bootstrap の `rnd.choice(keys)` を `rnd.choices(keys, k=n)` に「簡潔化」してはいけない(乱数列が変わり、同じ seed でも保存済みの信頼区間と合わなくなる)。

#### 指摘

##### 1. 引数の定義と「保存して表示」の終わり方が 5〜6 ファイルで同じ(優先度: 高・削れる行数の目安: 約 40 行)
- 場所: 引数 `dev/eval_asr.py:1163-1175,1186`・`dev/eval_cloud.py:496-506`・`dev/eval_speakers.py:1078-1088`・`dev/eval_effort.py:460-464`・`dev/eval_marks.py:936-939`(担当外の `eval_alt`・`eval_cut`・`eval_timing` も `--since/--until/--json/--data-dir` を持つ = grep で alt 4・cut 4・timing 4 行)。終わり方 `eval_asr.py:1201-1203`・`eval_cloud.py:522-524`(ラベルの正規表現置換 + `C.save` + 「保存:」)・`eval_speakers.py:1108-1109`・`eval_effort.py:469-470`・`eval_marks.py:944-945`。文書 id の分割 `eval_asr.py:1190`・`eval_cloud.py:510`・`eval_speakers.py:1097`。`eval_asr.py:1208-1211` だけ `C.utf8_stdout()` を使わず `sys.stdout.reconfigure` を手書き。
- 今: `--since/--until/--json/--data-dir/--no-eval` の 4〜5 行(ヘルプ文もほぼ同じ)が 5 ファイル、`--scope/--source/--reviewed/--since/--until/--intake/--docs/--label/--no-save` の 10 行が eval_asr と eval_cloud の両方。終わりは `if args.json: print("\n保存: " + C.save(res, res["meta"]["dataDir"], "<領域>", ...))` が 5 回。
- 案:
  ```python
  # _evalcommon.py
  def add_period_args(p, json_out=True, data_dir=True): ...        # --since/--until/--json/--data-dir
  def split_ids(text): return [x.strip() for x in text.split(",") if x.strip()] or None
  def save_and_report(res, root, area, enabled=True, suffix=""): ...  # if enabled: print("\n保存: " + save(...))
  # eval_asr.py(eval_cloud は E.add_select_args を呼ぶ)
  def add_select_args(p): ...                                        # --scope/--source/--reviewed/--since/--until/--intake/--docs/--label/--no-save
  ```
  eval_asr の末尾は `C.utf8_stdout()` に置き換える(4 行減)。
- 理由: 引数を足す・ヘルプ文を直すとき 5〜6 か所を同時に直す必要がある。eval_cloud のヘルプは「eval_asr.py と同じ」と書いて写しているだけで、既に食い違いやすい形。
- 影響・リスク: `--data`(文字起こしの作業データのフォルダそのもの。eval_asr・eval_cloud)と `--data-dir`(全ツールの親フォルダ。ほか)は**意味が違う**ので名前は揃えない(統合しない)。ヘルプ文が変わるだけで動作は同じ。
- テスト: `test_eval_asr.py`(`E.main` 22 回)・`test_eval_cloud.py`(`EC.main` 19 回)・`test_eval_speakers.py`(`E.main` 8 回)・`test_eval_effort.py`(2 回)・`test_eval_marks.py`(7 回)が main を通すので守られている。

##### 2. 「音声の出どころ(元の動画 → 保管の full.flac)」・ダミーのジョブ dict・一時フォルダの片付けが 3 ファイルで同じ(優先度: 高・削れる行数の目安: 約 30 行)
- 場所: 音声の選び方 `dev/eval_asr.py:710-718`(`recognize_doc`)・`dev/eval_cloud.py:230-239`(`audio_span`)・`dev/eval_speakers.py:773-781`(`doc_audio`)。ジョブ dict `eval_asr.py:719`・`eval_cloud.py:272`・`eval_speakers.py:855`(まったく同じ 6 キー)。一時フォルダ `eval_asr.py:720,741-746`(手書きの `os.listdir` → `unlink` → `rmdir`)・`eval_cloud.py:273-281`(`rmtree`)・`eval_speakers.py:843,909-914`。
- 今: `src` が実在すれば動画、無ければ `dataset/docs/<id>/full.flac`、どちらも無ければ同じ文言の `RuntimeError`、という 8〜10 行の分岐を 3 回。eval_cloud の docstring は「eval_asr.recognize_doc と同じ順」と写しである旨を認めている。eval_asr は一時フォルダの片付けだけ手書きで、同じ作業を eval_cloud・eval_speakers は `shutil.rmtree(tmp, ignore_errors=True)` で 1 行にしている。
- 案:
  ```python
  # _evalcommon.py
  def audio_span(doc, data, doc_id=None, boost=False):  # -> (spec, 行の時刻の基準の秒, "動画"|"保管の音声")。起点の取り方は schemas.num
  def fake_job(): return {"cancel": False, "proc": None, "phase": "", "state": "", "device": "", "progress": 0.0}
  # 呼び出し側: with tempfile.TemporaryDirectory(prefix="eval_asr_wav_", ignore_cleanup_errors=True) as tmp:
  ```
  eval_asr の `finally` 6 行・eval_speakers の `try/finally` と `os.unlink(wav)` 4 行が消える(Python 3.10 の `ignore_cleanup_errors` を使える)。
- 理由: 保管データの置き場所(`dataset/docs/<id>/full.flac`)の規則が 3 か所にあり、変わると 3 か所直し。`extract_audio` が読むのは `job["cancel"]`・`job["proc"]` 程度なので、ジョブ dict も共通化できる。
- 影響・リスク: **eval_speakers の `doc_audio` だけ UNC パス(`\\サーバー\…`・`//`)の動画を読まない**(資格情報を送らない)。共通化すると eval_asr・eval_cloud も同じく UNC を避けるようになる(動きが変わるが安全側。`ytt_core.fsio.is_network_path` が既にある)。eval_speakers の spec には `boost` が無い(`extract_audio` は `spec.get("boost")` なので `boost=False` で同じ)。eval_cloud は `S.num(doc.get("start"), 0.0)` を使っている(editor の `num`)ので、共通版は `schemas.num` で同じ意味になるか 1 件だけテストで確認する(**要確認**)。
- テスト: `test_eval_asr.py`(`E.recognize_doc` 5 回)・`test_eval_speakers.py`(`run_evaluate` と `diarize_once`)・`test_eval_cloud.py`(`main` 経由)。`EC.audio_span` を直接使うテストは無い(grep 済み)。

##### 3. `eval_speakers.evaluate` と `run_evaluate` が同じ組み立てを 2 回書いている(優先度: 高・削れる行数の目安: 約 40 行)
- 場所: `dev/eval_speakers.py:586-687`(102 行)・`dev/eval_speakers.py:818-940`(123 行)。重なる所: 合計の dict と加算(`598-599,621-629` と `841,864-871`)・メモ(`661-674` と `917-925`)・meta(`675-680` と `926-933`)・文書の読み込みと確かめ済みの選別(`595-597` と `829-831`)。
- 今: `totals = {"docs": 0, "drafts": 0, ...}` を手で初期化して `for k in (...): totals[k] += cnt[k]; totals["noSub"] += cnt.get("noSub", 0)` を 2 回。`if totals[k]: notes.append("…%d 行…" % totals[k])` が 5〜7 行ずつ。meta の共通の 10 キー(`schema`・`at`・`since`・`until`・`includeEval`・`includeDraft`・`git`・`dataDir`・`only`・`reviewed` など)も 2 回手書き。さらに、行の正しさを測る計算 3 つがそれぞれ書き直されている: `ok = bool(r["label"]) and mapping.get(r["label"]) == r["human"]` が `eval_speakers.py:336,540,554` の 3 か所、話者の `names = {s.get("id"): str(s.get("name") or "") ...}` が `215,246,287`(ほか `564,805` に `ids` 版)の 5 か所。
- 案:
  ```python
  totals = collections.Counter(); ...; totals.update(cnt)       # 初期化の dict と 5 行の加算が消える(無いキーは 0)
  NOTE_FMT = (("drafts", "仮の名前…%d 行…"), ("machineDraft", "…%d 行…"), ("unverified", "…%d 行…"), ("noSub", "…%d 行…"))
  notes += [fmt % totals[k] for k, fmt in NOTE_FMT if totals[k]]
  def base_meta(root, since, until, include_eval, include_draft, only, rinfo, **extra): ...
  def speaker_names(doc): ...   def is_correct(r, mapping): ...
  ```
  もう 1 つ性能の無駄: `evaluate` の `for r_ in [run] + history:`(`645`)は、先頭の最新回で `human_rows(doc, run["rows"], ...)` を**直前の `620` と同じ引数で再計算**している(`best_mapping` と `add_counts` の結果は `mapping`・`one` と同じ)。最新回は `rows/mapping/one` を再利用し、履歴だけ回せばよい(約 4 行減 + `human_rows` の `time_edited_flags` の bisect 1 回ぶん)。
- 理由: 保守性(新しい除外カテゴリを足すとき 2 関数 + meta + notes の 4 か所)。読みやすさ(関数が 100 行超 → 60 行台)。
- 影響・リスク: `notes` の文言は stored と run で微妙に違う(stored は「…(人が確かめていない下書き。--include-draft で入れる)」、run は machineDraft と unverified を 1 行にまとめている)。揃えると JSON の `meta.notes` が変わる。テストは部分文字列だけ見る(`test_eval_speakers.py:356-357,395,637,647` = 「機械の下書きのまま」「確かめられない」「0 本」「noSub」)ので、その語を残せば通る。meta のキー順・キーは変えない。
- テスト: `test_eval_speakers.py`(`E.evaluate` 3・`E.run_evaluate` 1・`E.main` 8・`E.confirm_map`・`E.stored_smooth_recs`)。

##### 4. 小さな判定・表示の写し(`num`・`is_reviewed`・`pct(x).strip()`・`in_period`・期間のラベル)(優先度: 中・削れる行数の目安: 約 20 行 + 呼び出し約 35 か所が短くなる)
- 場所:
  - `num`: `dev/eval_speakers.py:100-101`(float にせず素通し)・`dev/eval_marks.py:183-184`(float・`abs(x) < 1e9`)・`dev/eval_asr.py:141-142`(`reviewed_sec` の中の関数)・`dev/eval_effort.py:46`(`ytt_core.schemas.num`)。担当外にも `eval_alt.py:124`・`eval_cut.py:55`。`plain_int` は `eval_effort.py:69-70`。
  - `is_reviewed`: `eval_asr.py:128-130` と `eval_speakers.py:199-201`(eval_effort は `eval_asr.is_reviewed` を呼ぶ)。
  - `in_period`: `eval_speakers.py:204-206` は `_evalcommon.in_period`(`:71-77`)と式が同じ(`t = num(proofedAt) or doc_t` で t は None にならない)。
  - 期間のラベル: `eval_speakers.py:1043` は `C.period_label`(`_evalcommon.py:80`)と同じ式。
  - `pct(x).strip()`: eval_speakers 約 15 か所・eval_marks 約 8 か所・eval_asr 約 12 か所。`eval_alt.py:119`・`eval_cut.py:158` は `C.pct(x).strip()` をそれぞれ別名の関数で包み、`eval_effort.py:397` は `C.pct(x, 0)`。
- 今: 「有限の数だけ通す」関数が 4 通り。「詰めた割合の表示」を呼び出しのたびに `.strip()` で作っている。
- 案: `schemas.num` を使う(`eval_effort` と同じ。NaN・巨大整数も弾く)。`_evalcommon` に `is_reviewed(doc)` と `pct_tight(x)`(`"-"` か `"%.0f%%"`)を足し、各ファイルは import するだけにする。eval_asr は 1 桁表示の自前 `pct`(`:769`)が別の見た目なので残し、`.strip()` 用に `pct_t = lambda x: pct(x).strip()` を足す。eval_speakers の `in_period` は `C.in_period(num(sg.get("proofedAt")) or doc_t, since_ms, until_ms)` の 1 行に、`rng = ...` は `C.period_label(...)` に。
- 理由: 「ブール値は数ではない・NaN は数ではない」という判定が 4 通りに分かれていて、直すときに全部見に行く必要がある。表示の詰め方が呼び出しごとに散らばっている。
- 影響・リスク: `eval_marks.num` の `abs(x) < 1e9`(巨大値を弾く)は `schemas.num` に無い。feedback は自分のツールが書くので実害は小さいが「動きが変わる」。`eval_speakers.num` は int を int のまま返しており、float 化しても出力に出る値は変わらない(`human_rows` の start/end は集計にだけ使う)。`pct_tight(None)` は `"-"`(今の `.strip()` 後と同じ)。`eval_effort.pct` は None で `"  -  "`(詰めない)なので、そこだけ揃えると表示が数文字変わる(表示のみ)。
- テスト: `test_eval_marks.py`(`M.main`・`M.evaluate`)・`test_eval_speakers.py`・`test_eval_effort.py`・`test_eval_asr.py` が出力の数を見る。表示の文字列そのものを見るテストは少ない(要確認: `test_eval_asr.py` の `print_summary` 5 回は文字列を assert していないか)。

##### 5. 文書フォルダ(`transcripts/<12 桁>.json`)の走査が 3 か所(優先度: 中・削れる行数の目安: 約 20 行)
- 場所: `dev/eval_asr.py:103-121`(`load_docs`)・`dev/eval_speakers.py:443-460`(`load_docs`)・`dev/eval_effort.py:333-347`(`evaluate` の先頭ループ)。`DOC_RE` が `eval_speakers.py:72`・`eval_effort.py:54`(と担当外の `eval_alt.py:56`・`eval_timing.py:58`)、eval_asr は `re.fullmatch` の文字直書き(`:108`)。
- 今: `os.listdir(tdir)` → 正規表現で名前を絞る → `read_json` → dict でなければ broken を数える → `evalSet` の扱い、を 3 回。eval_effort は diar.json の `latest.rows` を取り出す 3 行(`344-346`)も持ち、eval_speakers の `read_diar`(`91-95`)と同じ読み方。
- 案: `_evalcommon.iter_docs(tdir, only=None, limit=None)` が `(tid, doc or None)` を yield し(None = 壊れている)、各ファイルは `evalSet` の扱いだけを書く。`read_diar(tdir, tid)` も `_evalcommon` に移す(schema と dict の確認つき。eval_effort は schema を見ていないので `latest.rows` を得るだけの薄い版を呼ぶ)。
- 理由: 文書の置き方(ファイル名の形・サイズ上限)が変わったとき 3〜5 か所を追う必要がある。
- 影響・リスク: eval_asr は `only` が指定されたとき全 scope で読む・id を後で絞る、など順序の細部が違うので、単に「走査」だけを共通にし、条件は呼び出し側に残すこと。eval_effort の `MAX_BYTES`(64MB)と eval_speakers の `MAX_DIAR_BYTES`(32MB)は引数で渡す。
- テスト: `test_eval_asr.py`(`E.main` 経由)・`test_eval_speakers.py`(`E.read_diar` 1 回・`E.evaluate`)・`test_eval_effort.py`(`E.evaluate` 3)。

##### 6. `eval_marks.build_videos` が 125 行・入れ子 4 段で、同じ 14 キーの dict を 4 回手書き(優先度: 中・削れる行数の目安: 約 20 行)
- 場所: `dev/eval_marks.py:204-328`。item の dict は `248-251`(data.json)・`261-263`(archive)・`295`(手動マークの feedback)・`303`(自動マークの feedback)の 4 か所。内側の関数 `find`・`by_id`・`in_range` を閉じ込めたまま「1 data.json のマーク」「2 archive」「3 feedback の行」「4 取り消しの数」「5 判定」が 1 本に並ぶ。
- 今: `{"a0": …, "start": s, "end": e, "score": …, "t": …, "src": …, "status": "", "path": "", "markId": …, "events": [], "a0known": …, "adoptedBy": None}` の長い dict リテラルを毎回書き、変えるのは 3〜5 キーだけ。
- 案:
  ```python
  def new_item(a0, s, e, **over):
      it = {"a0": a0, "start": s, "end": e, "score": None, "t": None, "src": "feedback", "status": "", "path": "", "markId": "",
            "events": [], "a0known": False, "adoptedBy": None, "parts": None, "reasons": None, "peak": None}
      return dict(it, **over)
  # build_videos は段ごとの関数に: _data_items(dv) / _archive_items(arch, find) / _feedback_items(V, rv, ...) / _count_retracts(V, rv, in_range)
  ```
  なお `parts`・`reasons`・`peak` は data/archive の item にだけあり、feedback 由来の item には無い。feedback 由来を `None` で持たせてよいかを `group_metrics`・`friend_group` の読み方(`it.get("peak")`・`best.get("parts")` を使っている)で確かめる(**要確認**)。
- 理由: 保守性(item に項目を足すとき 4 か所)・読みやすさ(125 行 → 各 30 行以下)。lint の 150 行基準には当たらないが、いまのままだと 4 段の入れ子の中で変数 `s`・`e`・`t`・`a0` が段ごとに別の意味で再代入される。
- 影響・リスク: 動きは変えない整理。item の dict のキーの有無(`parts` など)を変えると、結果 JSON に出る `friendRanges.items` の形が変わりうるので、キーを増やさないこと。
- テスト: `test_eval_marks.py`(808 行。`M.build_videos` 直接・`M.evaluate` 3・`M.main` 7・`M.load_feedback`・`M.ranked`・`M.friend_hit`)が広く守っている。

##### 7. eval_asr の集計: 文書ごとに全まとまりを何度も走査・信頼区間の写し(優先度: 中・削れる行数の目安: 約 15 行)
- 場所: `dev/eval_asr.py:684`(byDoc で文書ごとに `[g for g in groups if g["doc"] == i]`)・`690`(`g["doc"] in set(v)` が**要素ごとに `set(v)` を作り直す**)・`700`(組ごとに `docs` 全体を走査)・`645-649`(`origin_summary`)・`609-611`(`reviewed_summary`)・`557-577`(`boot_ci` の文書ごとの誤り合計)と `1072-1077`(`cmd_compare` の同じ集計)・`577` と `1092` の分位点の取り方(`vals[int(len*0.025)]`・`vals[min(len-1, int(len*0.975))]`)。
- 今: 同じ `groups` を byDoc・byDraft・byGroup・origins・reviewed のたびに先頭から絞り込む。文書ごとの (誤り, 正解の文字数) の集計も `boot_ci` と `cmd_compare` で別々に書いている。
- 案:
  ```python
  def doc_errs(groups):  # {doc: [errs, refChars]}
      by = {}
      for g in groups: e = by.setdefault(g["doc"], [0, 0]); e[0] += g["sub"] + g["del"] + g["ins"]; e[1] += g["refChars"]
      return by
  def ci95(vals):  vals.sort(); return vals[int(len(vals) * 0.025)], vals[min(len(vals) - 1, int(len(vals) * 0.975))]
  # summarize: by_doc = group_by(groups, lambda g: g["doc"]) を 1 回作って byDoc・byDraft・byGroup・origins に渡す
  ```
- 理由: O(文書 × まとまり) を O(まとまり) に。今は文書 50 本・まとまり数千で体感差は無いが、`set(v)` の作り直しは読み手に誤解を生む書き方。`boot_ci` と `compare` の分位点の取り方が食い違うと CI の意味が変わるので 1 か所にしておく価値がある。
- 影響・リスク: **`rnd.choice` を `rnd.choices` などに置き換えないこと**(乱数の消費が変わり、同じ seed でも信頼区間が変わる = 保存済みの結果と比べられなくなる)。`seed=1`・`BOOT=1000` のまま。`total()` の結果はキーの順まで変えない。
- テスト: `test_eval_asr.py`(`E.main` 22・`E.cmd_compare` 16・`E.doc_text`・`E.gate_of` 7)。`boot_ci` を直接見るテストは無いので、信頼区間の値を固定したテストを 1 件足してから直すと安全(**要確認**)。

##### 8. 手作りの数え上げ・グループ分けを `Counter` / `defaultdict` に(優先度: 中・削れる行数の目安: 約 15 行)
- 場所: `dev/eval_speakers.py:164`(`best_mapping`)・`357`(`majority_name`)・`402`(`Voices.add` の `undecided`)・`425-429`(`_count`)・`499-505`(`speaker_count`)・`260`(`cnt["noSub"]`)・`dev/eval_marks.py:589`(`reasons`)。グループ化の `setdefault(...).append` は `eval_asr.py:595,678,689,697,833`・`eval_marks.py:216,772,794`・`eval_effort.py:245`。
- 今: `cnt[k] = cnt.get(k, 0) + 1` と、`ranked = sorted(cnt.items(), key=lambda kv: -kv[1])` で最多を取る 8 行。
- 案:
  ```python
  def majority_name(rows):
      top = Counter(r["human"] for r in rows).most_common(2)
      return None if not top or (len(top) > 1 and top[0][1] == top[1][1]) else top[0][0]
  best_mapping: cnt = Counter((r["label"], r["human"]) for r in rows if r["label"])
  _count(xs): return dict(sorted(Counter(map(str, xs)).items()))
  ```
  グループ化は `defaultdict(list)` 1 つにするか、`_evalcommon.group_by(items, key)`(3 行)に。
- 理由: `Counter` の同数のときの並びは入れた順(Python 3.7 以降は安定)で、`sorted(key=-count)` と同じ。読みやすさ。
- 影響・リスク: 出力の順序は変えない(`dict(sorted(...))` を残す)。`speaker_count` の `diff` のキーは `str(d)` の昇順ではなく `int` で並べているので、そこだけ現状の `sorted(key=lambda kv: int(kv[0]))` を残す。
- テスト: `test_eval_speakers.py`(`E.best_mapping`・`E.hungarian_max`・`E.evaluate`・`E.main`)。

##### 9. 結果ファイルの原子的な書き込みが 3 通り(優先度: 低・削れる行数の目安: 約 10 行)
- 場所: `dev/_evalcommon.py:137-141`(`save`)・`dev/eval_cloud.py:254-259`(`save_cache`)・担当外の `dev/eval_import.py:144-145`。一方 `eval_fetch.py:248,361`・`eval_split.py:259` は `fsio.atomic_write` を使っている。
- 今: `path + ".tmp"` に `json.dump` → `os.replace`。Windows でウイルス対策ソフトなどが一瞬ファイルを開いていると `os.replace` が `PermissionError` になる(`fsio.replace_retry` はこれを待ってやり直す)。
- 案: `fsio.write_json(path, obj, indent=1)`(UTF-8・BOM なし・fsync・ロック時のやり直しつき)に差し替える。`eval_cloud.save_cache` は `fsio.write_json(path, rec, indent=1)` の 1 行にでき、`C.save` も 4 行が 1 行になる。
- 理由: 同じ目的の書き込みを 1 実装にして、Windows のロック対策を全部に効かせる。
- 影響・リスク: 書いたファイルの末尾に `\n` が付く(`write_json` の仕様)・fsync で保存が少し遅くなる。入口の `src/home/accuracy.py` が読むのは JSON としてなので問題無いはずだが、「最後の行の `保存: <パス>` と名前の形 `<日時>.json` を変えない」という `_evalcommon` の約束には触れない。`eval_timing --out` など `out=` 経路も同じ関数を通す。
- テスト: `test_eval_cloud.py`(応答の控え)・`test_eval_cut.py:316`(`E.save`)・`test_eval_timing.py`・各 `main(["--json"])`。

##### 10. 「original のどの行とも端が 0.05 秒以内で合わない行」の bisect が 2 か所(優先度: 低・削れる行数の目安: 約 12 行)
- 場所: `dev/eval_speakers.py:173-191`(`time_edited_flags`)・`dev/eval_effort.py:150-163`(`edit_counts` の中)。`eval_effort.py:51` のコメントも「eval_speakers.py の TIME_TOL と同じ」と認めている。
- 今: どちらも `starts = [...]`・`bisect_left`・`while starts[k][0] <= a + TOL: …` の同じ形。
- 案: `_evalcommon.edge_unmatched(orig, a, b, tol=0.05)`(`orig` = 始まりでソート済みの `(開始, 終了)`)。`itertools.takewhile` で書く。
  ```python
  k = bisect.bisect_left(orig, (a - tol,))
  return not any(abs(e - b) <= tol for s, e in takewhile(lambda p: p[0] <= a + tol, islice(orig, k, None)))
  ```
- 理由: TIME_TOL・考え方を 1 か所に。
- 影響・リスク: eval_speakers は original の「文字の有無を問わず数のある行」、eval_effort は「文字のある行だけ」を `orig` に渡している。共通化しても渡すリストはそれぞれ作り、**判定の中身(関数)だけ**を共通にすること(渡すリストを揃えると数が変わる)。
- テスト: `test_eval_speakers.py`(`stored` の timeEdited 小計)・`test_eval_effort.py`(`E.edit_counts` 10 回)。

##### 11. eval_marks の指標計算の繰り返し(見逃し・端のずれ)と、`ranked()` の再計算(優先度: 低・削れる行数の目安: 約 15 行)
- 場所: 見逃しの近く `dev/eval_marks.py:422-427` と `572-574`(`near15s`・`farOrNone`・`withNearAuto`・`noAuto` を同じ式で作る)。端のずれの `dist(abs)` と `dist(signed)` の 4 つ組が `428-432` と `603-604`。`ranked(V["auto"])` が `411`(動画ごと)・`618`(友人の区間ごと)・`661`(`clip_samples.add()` のたび = 見本 1 個ごとに同じ動画の候補を毎回並べ直す)。
- 今: 距離の一覧から 4 つの数を出す式、「開始・終了それぞれ絶対値と符号つきの分布」を作る式が 2 回ずつ。
- 案: `near_stats(distances, total_missed)` と `edge_dists(starts, ends)` の小さな関数にする。`clip_samples` は `cands_of` に `functools.lru_cache`(または動画 ID ごとの dict)を付けて 1 動画 1 回だけ並べる。
- 理由: 友人の区間の指標が手で足したマークの指標と「同じ式」であるべき関係が、コピーのままだと崩れやすい。
- 影響・リスク: 動かない整理。`near15s` のしきい値 `NEAR_SEC` は両方同じ定数。`ranked()` はリストを新しく返すので、キャッシュ後に呼び出し側が破壊的に並べ替えていないこと(読んだ限りでは破壊的な変更は無い)。
- テスト: `test_eval_marks.py`(`M.friend_hit`・`M.friend_gap`・`M.ranked`・`M.evaluate` 3)。

##### 12. eval_effort の CER 計算まわり: 例外の握りつぶしと一時フォルダの手動削除(優先度: 低・削れる行数の目安: 約 10 行)
- 場所: `dev/eval_effort.py:357-372`。
- 今: `S = None` → `try: S = eval_asr.load_serve("fake") …` → `except Exception as e: cer_note = …`(全例外を握って全文書の CER を None に)→ `finally:` で `TRANSCRIBE_DATA_DIR` の値の先頭が `eval_asr_` なら `shutil.rmtree`。`_evalcommon.load_serve` は一時フォルダを `atexit.register(shutil.rmtree, tmp, True)` で既に片付ける登録をしている。
- 案: `finally` の手動削除は、`_evalcommon.load_serve` に任せる(`keep_env=False` で環境変数を戻す呼び方にすれば、片付けの登録と環境の復元が 1 か所になる)。`except Exception` は「採点の部品が読めなくても手間の集計は出す」という意図のあるものなので、例外の種類を `ImportError・OSError・RuntimeError` に絞るか、現状のまま残す。
- 理由: 一時フォルダ名の接頭辞(`eval_asr_`)を文字比較で当てにする書き方は、`load_serve` 側の `prefix` の既定が変わると壊れる。`eval_timing` のテスト(`test_eval_timing.py:201-205`)も同じ接頭辞を見ており、3 か所が暗黙に結びついている。
- 影響・リスク: **要確認**。`load_serve("fake")` の後に `TRANSCRIBE_DATA_DIR` が一時フォルダを指したままになる前提(`keep_env=True`)を使う別のテストがあるか、`test_eval_timing.py` が先に消す前提を持つ。変えるなら `keep_env=False` + 既存テストを流してから。
- テスト: `test_eval_effort.py:337-349`(CER あり・なし)・`E.main` 2。CER 算出が失敗する経路(`except` の枝)を踏むテストは無い。

##### 13. eval_asr / eval_cloud / _evalcommon の細かい残り(優先度: 低・削れる行数の目安: 約 15 行)
- 場所と内容:
  - `dev/eval_asr.py:165-170` の `default_intake()`: 先頭の `if HERE not in sys.path: sys.path.insert(0, HERE)` は、ファイル冒頭(`:73-75`)で既に実行済みなので到達しない分岐(3 行)。
  - `eval_asr.py:173-184` の `_iso_ms`: `strptime` を 2 通り試したあと `fromisoformat` に落とす 3 段。Python 3.10 の `fromisoformat` は `+09:00` を読めるが `+0900` を読めないので `strptime(...%z)` は要る。`Z` 終わりと小数秒をどこまで入れているかを確かめたうえで 2 段に減らせる(**要確認**: 取り込み側 `eval_import` がどの形を書くか)。
  - `eval_asr.py:886,908`・`eval_cloud.py:418`・`eval_asr.py:200`: `read_json(path, {}) or {}` が 4 回。`_evalcommon.read_dict(path)`(dict でなければ `{}`)にすれば、`isinstance(…, dict)` の後続の確認も減る(`eval_marks.py:105-106,719-720` にも同じ形)。
  - `eval_asr.py:761` と `eval_cloud.py:419`: `boost` の決め方 `(settings.get("boost") is True) if args.boost is None else args.boost == "on"` が同じ式。
  - `eval_asr.py:1202` と `eval_cloud.py:523`・`227`: 名前を安全にする `re.sub(r"[^\w.-]+", "_", …)` が 3 回(`label` 2 回・`cache_dir` 1 回)。
  - `eval_asr.py:271,281` の `getattr(args, "since", None)` 系: `main` では常に属性がある。テストが Namespace を手で作るための防御かどうかを確かめて、そうであればテストの Namespace 作りを直す方が自然(**要確認**)。
  - `_evalcommon.py:55-63`: `time.mktime(d.timetuple())*1000` は `int(d.timestamp()*1000)` と同じ(ローカル時刻の naive datetime)。
  - `eval_marks.py:365,370`: `exported = st == "exported" and verdict in ("good",)` のあと `bool(exported and verdict == "good")`。後ろで同じ条件をもう一度見ている。
- 理由: 一つずつは小さいが、「同じ判断を 2 か所に持つ」形。
- 影響・リスク: どれも動きは変わらない想定。`_iso_ms` と `getattr` の 2 件は要確認。
- テスト: `test_eval_asr.py`(`E.main` 22・`E.doc_time` 4・`E.load_friend_docs` 1)・`test_eval_cloud.py`・`test_eval_marks.py`。

#### 他のグループとの重複の疑い(担当外のファイルに同じ処理がありそう。どれも「疑い」)
- `dev/eval_alt.py`・`dev/eval_cut.py`・`dev/eval_timing.py`(G13 dev-eval-B と思われる): `num` が `eval_alt.py:124`・`eval_cut.py:55`(担当の `num` とそれぞれ微妙に違う)・`pct` の包み(`eval_alt.py:119`・`eval_cut.py:158` は `C.pct(x).strip()`、`eval_timing.py:388` は別の見た目)・`DOC_RE`(`eval_alt.py:56`・`eval_timing.py:58`)・`--since/--until/--json/--data-dir` の引数(alt 4・cut 4・timing 4 行)・`C.utf8_stdout()`(これは共通化済み)。指摘 1・3・4・5 の共通部品は、この 3 ファイルもまとめて切り替える前提で作ると効果が倍になる。
- `dev/eval_import.py:144-145`: 手書きの原子的な書き込み(`json.dump` + `os.replace`)。指摘 9 の `fsio.write_json` に揃えられる(疑い)。`eval_asr.default_intake()` が `eval_import.default_dest()` を呼んでいる関係もあるので、G13 と調整が要る。
- `src/editor/ed_state.py:228-250`(`rss_mb`)・`src/home/live_excite_worker.py:160-190`(`memory_mb`)・`dev/eval_asr.py:427-449`(`peak_memory_mb`): Windows の `PROCESS_MEMORY_COUNTERS` の ctypes 構造体を 3 か所で書き写している(疑い。`ytt_core` に 1 つ `process_memory_mb(peak=False)` を置けば 3 か所が消える。editor・home の担当グループとの調整が要る)。
- `src/editor/ed_state.py` の `plain_int`・`src/ytt_core/txindex.py:75,236` の `isinstance(x, int) and not isinstance(x, bool)`・`evaldata.py:224,228,272`: 「bool を除く整数・数」の判定がここにも散らばっている(疑い。`schemas.num` と `schemas.plain_int` のような 2 関数に揃えられる)。
- `src/editor/ed_drill.py` の `drill_is_reviewed` と `eval_asr.is_reviewed`・`eval_speakers.is_reviewed`: 「editor を読み込まないため二重に持つ」と明記された意図的な写し。ただし `ytt_core` に置けば 3 つが 1 つになる(疑い。担当は ytt_core / editor 側のグループ)。
- `ed_learn.py:1165` の `{"cancel": False, "proc": None}`(ジョブ風の dict)と指摘 2 の `fake_job()`: 同じ種類のダミー(疑い)。


### G13 dev-tools-B(担当: dev/ui_audit.py・eval_alt.py・eval_timing.py・eval_fetch.py・eval_cut.py・eval_split.py・eval_import.py・lint.py・demo_env.py・push_helper.py・dropbox_auth.py・count_sparse_rows.py・sync_ui_kit.py・run_editor_suite.py・plan_artifact.py、合計 約 4,700 行)

#### 全体の傾向
- 全部読んだ。**関数の長さ・同じ 12 行の写しは lint の基準内で、壊れた所・危ない所は見つからなかった**。削れる量は担当全体で約 230 行(5%)。大きな無駄は無く、効果が出る所が 3 つに絞られる。
- 効果が一番大きいのは **eval_* の「骨組み」の写し**(引数 4 つ・`保存: <パス>` の 1 行・meta の頭・文書の列挙・64MB の定数)。担当の 3 本(alt・cut・timing)に加え担当外の marks・effort・speakers・asr にも同じ形がある。ヘルプ文が少しずつ違うので lint の dup-block(12 行)に掛からず残っている。
- 次に効くのは **lint.py の速さ**(実測 5.7 秒。AST を 1 ファイルあたり 5 回なめる・md5 でハッシュする所だけで約 2.5 秒。見込みは 5.7 → 約 3 秒)。ファイルの読み直し・フォルダの歩き直しは合計 0.03 秒で、問題は別の所(下の 2)。
- ytt_core に `fsio.write_json`・`schemas.num`・`normalize.probe`・`txindex` がすでにあるのに、dev/ の中で自前の原子的な書き込み・数の検査・ffprobe 呼び出しを書き直している所が複数ある(3・4・5)。
- eval_import.py・push_helper.py は検査・関所の部品でテストも厚い。**触る価値は低い**(それぞれ 12 行・数行の軽い整理のみ)。ui_audit.py の JS 字句解析(`scan_code`)は標準ライブラリで置き換えられないので手を付けない。

#### 指摘

##### 1. eval_* の骨組み(引数・保存・meta・文書の列挙・定数)を `_evalcommon` に吸い上げる(優先度: 高・削れる行数の目安: 担当内 約 47 行、`_evalcommon` に約 20 行足して正味 約 27 行。担当外の marks・effort・speakers・asr まで広げると正味 約 60 行)
- 場所:
  - main の尻尾: `dev/eval_alt.py:537-550`・`dev/eval_cut.py:396-407`・`dev/eval_timing.py:445-458`(担当外: `eval_marks.py:934-948`・`eval_effort.py:458-473`・`eval_speakers.py:1074-1109`・`eval_asr.py:1190-1203`)
  - `save(res, root)` の 1 行ラッパー: `eval_alt.py:533-534`・`eval_cut.py:392-393`(担当外: `eval_marks.py:930`・`eval_effort.py:454`)
  - meta の頭 `{"schema","at","since","until","git","dataDir"}`: `eval_alt.py:376,456`・`eval_cut.py:322`・`eval_timing.py:375`
  - 文書の列挙 `for name in sorted(os.listdir(tdir)) if os.path.isdir(tdir) else []: if not RE.match(name): continue`: `eval_alt.py:390-393`・`eval_cut.py:279-283`・`eval_timing.py:345-347`(担当外: `eval_effort.py:333-334`・`eval_speakers.py:446-447`・`eval_asr.py:107`)
  - 定数: `DOC_RE`(`eval_alt.py:56`・`eval_timing.py:58`・`eval_cut.py:49` の EDIT_RE)と 64MB(`eval_alt.py:54`・`eval_cut.py:47`・`eval_timing.py:57`)
- 今: どの道具も `--since --until --json --data-dir` の 4 つを同じ順に書き、`if args.json: print("\n保存: " + save(...))` で終わる。保存の行の頭 `"保存: "` は入口の `src/home/accuracy.py:46` が `SAVED_MARK` として読む約束なのに、道具側は 6 か所が文字列を直書き。
- 案(`_evalcommon.py` に足す。5 行以内の骨):
  ```python
  SAVED_MARK = "保存: "; DOC_BYTES = 64 * 1024 * 1024
  def doc_files(tdir, ext=".json"):   # 12 桁 16 進の <id><ext> を名前順に [(id, path)]。ディレクトリが無ければ []
  def base_parser(desc, since_help):  # --since --until --json --data-dir を足した ArgumentParser(--until の help も共通)
  def meta(schema, root, since, until, root_key="dataDir", **extra): ...  # {"schema","at","since","until","git",root_key} | extra
  def finish(res, args, area, root, **kw):  # if args.json: print("\n" + SAVED_MARK + save(res, root, area, **kw)); return res
  ```
  各道具の main は `p = C.base_parser(...)` → 固有の引数だけ足す → `res = evaluate(...)`; `print_report(res)`; `return C.finish(res, args, "alt", res["meta"]["dataDir"])` の 4 行になる。`doc_files(tdir, ".edit.json")` で eval_cut の EDIT_RE も吸収できる。標準ライブラリだけで書くなら `Path(tdir).glob("[0-9a-f]" * 12 + ".json")` も使えるが、Windows の glob は大文字小文字を区別しないので正規表現のほうが元と同じ。
- 理由: 保存の約束(入口が読む形)が 1 か所になる。道具を足すたびに同じ 12 行を写す必要が無くなる。lint の dup-block に掛からない長さ(8〜11 行)で増え続けている。
- 影響・リスク: 動きは同じ。`test_eval_cut.py:316` が `E.save(...)` を直接呼ぶので、`save` を残すかテストを `C.save(res, root, "cut")` に直す。`eval_marks` の root は `studioDir` なので `root_key` を引数にする。`test_eval_alt.py`・`test_eval_cut.py`・`test_eval_timing.py` が main・print_report の出力まで通る。

##### 2. lint.py: AST を 5 回なめる・md5 でハッシュする・到達しない分岐を整理(優先度: 高・削れる行数の目安: 約 25 行、実行時間 約 5.7 秒 → 約 3 秒(見込み))
- 場所: `dev/lint.py:104-130`(unused_imports)・`:146-154`(long_functions)・`:157-170`(dup_helpers)・`:193-223`(norm_line・dup_blocks)・`:246-293`(main)
- 今(実測。コードは変えず、読むだけの計測を `-c` で流した。lint.py 自体も 1 回流して合計 5.7 秒):
  - 全体 5.7 秒。内訳は ast.parse 2.2 秒・unused_imports 1.7 秒・long_functions 0.6 秒・dup_blocks 1.1〜1.3 秒・Corpus 0.23 秒・ファイルの読み直し 0.02 秒・フォルダ歩き 0.002 秒。
  - `unused_imports` が `ast.walk(tree)` を 3 回(`:109`,`:120`,`:129`)、`long_functions` と `dup_helpers` が各 1 回、つまり 1 ファイルあたり 5 回なめる。
  - `:123-128` の `ast.Attribute` の枝は、`ast.walk` が子の `ast.Name` も別に返すので `used` に何も足さない(**常に空振り**)。
  - `:213` の `len({loc[0] for loc in locs}) + len(locs) > 2` は、`len(locs) >= 2` の下では**常に真**(ファイル数 1 以上 + 2 以上 ≥ 3)。
  - `:209` は窓ごとに 12 行を join → encode → md5(60,168 窓)。
  - `:201-202` のファイル絞り込みは 2 行にまたがる and/or の混在で、`walk(.., (".py", ".js"))` は .css を返さないので `not p.endswith("ui-kit.css")` も不要。
  - `:151` の `getattr(node, "end_lineno", node.lineno)` は 3.10 では常に `end_lineno` がある。
- 案:
  ```python
  nodes = list(ast.walk(tree))                      # main で 1 回。3 つの検査に nodes を渡す(0.52 秒)
  # unused_imports: for n in nodes: if Import/ImportFrom → imported / elif Name → used / elif str の Constant → strs に積む(1 パス。Attribute の枝は削除)
  windows[tuple(texts[i:i + n])].append(...)         # md5・join・encode・hashlib をやめ、文字列のタプルをそのままキーに(衝突も無くなる)
  groups = {h: l for h, l in windows.items() if len(l) >= 2}   # 常に真の条件を外す
  keep = not is_test(p) and (not p.endswith("ui-kit.js") or "/ui-kit/" in rel(p))   # 絞り込みを 1 式に
  ```
  main の `issues["x"].append({"file": rel(p), "line": ln, "name": name})` 7 か所は `add(kind, p, ln, name, **extra)` の 1 関数に(約 6 行減)。
- 理由: lint は「コードを変えたら必ず流す」基準なので、待ち時間の短縮がそのまま毎回の効き目になる。事前に試した見込み(リポジトリのコードは変えず、同じ処理を別計算で): 1 回の walk + 1 パスの本体で約 0.9 秒(今の unused_imports + long_functions は約 2.3 秒で、dup_helpers の walk はさらに別)、tuple キーで約 0.35 秒(今の約 1.1〜1.3 秒から)。合計は約 3 秒の見込み。
- 影響・リスク: lint 自身のテストは無い(`dev/tests` に test_lint が無い)。**測り方の基準は変えない**ので、直す前後で `py -3.10 dev/lint.py --json` の出力が一字違わず同じ(今は 0 件)になることを確かめる。`:213` は「同じファイル内で重なる窓を除く」意図だった可能性もある(今の式はその意図を満たしていない)。意図があるなら基準を変えることになるので、ここは削るだけにして `docs/spec/code-quality.md` の基準 6 の説明と食い違わないか要確認。

##### 3. dev/ の自前の原子的な書き込みを `fsio.write_json` / `fsio.atomic_write` に(優先度: 中・削れる行数の目安: 約 25 行)
- 場所: `dev/eval_import.py:141-145`(`_write_json`)・`dev/dropbox_auth.py:106-112`(`write_config`)・`dev/sync_ui_kit.py:35-39`(`write`)・`dev/eval_split.py:257-259`・`dev/eval_fetch.py:247-248,361`(`fsio.atomic_write(path, json.dumps(...).encode())`)(担当外: `_evalcommon.py:137-140` の `save`)
- 今: tmp に書いて `os.replace` する 5〜7 行が 5 か所にある。`ytt_core/fsio.py:91` に `write_json(path, obj, indent=2)`(UTF-8 BOM なし・フォルダも作る・Windows のロックは `replace_retry` で待つ)が既にある。eval_split と eval_fetch の 3 か所は `atomic_write(path, json.dumps(x, ensure_ascii=False, indent=1).encode("utf-8"))` で、これは `fsio.write_json(path, x, indent=1)` と同じ。
- 案: `fsio.write_json(path, obj, indent=1)`(sync_ui_kit は `fsio.atomic_write(path, text.encode("utf-8"))`。`ytt_core.layout` を既に import しているので追加の依存は無い)。dropbox_auth は標準ライブラリだけを売りにしている(ytt_core の import で `sys.path` を足すので正味は約 3 行減)。
- 理由: Windows のウイルス対策・同期ソフトの一時ロックで `os.replace` が落ちる問題に、自前の書き方だけ対応していない。1 か所の約束に寄せられる。
- 影響・リスク: 書いた JSON の末尾に改行が 1 つ付く(`write_json` の仕様)。`test_eval_import.py`・`test_dropbox_auth.py`・`test_eval_split.py`・`test_eval_fetch.py`・`test_ui_kit_sync.py` が中身を JSON として読むだけなら通る。バイト単位で比べているテストが無いか要確認(sync_ui_kit は `atomic_write` なら改行ごと同じバイト列)。

##### 4. 同じ意味の小道具の複製を既存の関数へ(`num`・`pct`・中央値・期間ラベル)(優先度: 中・削れる行数の目安: 約 25 行)
- 場所:
  - `dev/eval_alt.py:124-125`(`num`)・`dev/eval_cut.py:55-62`(`num`・`ms_of`)・`dev/eval_cut.py:84,106`(`isinstance(.., int) and not isinstance(.., bool)` の連発)→ `ytt_core.schemas.num`(eval_timing は既に `:47` で使用)
  - `dev/eval_alt.py:119-121`・`dev/eval_cut.py:158-160`(`C.pct(x).strip()`)・`dev/eval_timing.py:388-389` → `C.pct`
  - `dev/eval_timing.py:129-134`(`_median`)・`:194`・`:438` → `C.dist(v)["median"]`
  - `dev/eval_timing.py:411`(`C.period_label` と一字違わぬコピー)
  - `dev/eval_timing.py:230`(`num(run.get("at"))` を 4 回呼ぶ 1 行)
  - `dev/eval_timing.py:264-271`(`reapply` の for+append)
- 今: `schemas.num` は有限の数(bool 除く)→ float・巨大な整数の OverflowError も None にする。eval_alt/eval_cut の自前版は同じ検査を別々に書き、eval_cut のは 1e12 の上限も足している。`C.pct(x, 0)` は eval_effort が既に使っているのに、alt/cut は `.strip()` の自前ラッパー。`C.dist` は中央値と平均を持っていて、`_median` は偶数個のとき 2 つの平均で同じ値(round 3 桁)。
- 案:
  ```python
  from ytt_core.schemas import num                 # eval_alt・eval_cut。cut の上限は num(x) の結果に abs(v) < 1e12 を足す 1 行
  def pct(x): return C.pct(x, 0)                   # さらに C.pct の None を "-".center(width + 1) にすれば、3 つのラッパーが全部消える
  d = C.dist(ex); out = {"n": n, "counts": counts, "extraMedian": d.get("median"), "extraMean": d.get("mean")}   # _median と計算を捨てる
  at = next((int(v) for v in (num((run or {}).get("at")), num(doc.get("updatedAt"))) if v), None)
  ```
- 理由: 「有限の数」の定義が dev/ の中で 5 通りある(eval_alt・eval_cut・eval_asr・eval_marks・eval_speakers、ytt_core の `txindex._num` も)。数の検査が揃わないと、NaN・inf・巨大な整数の扱いが道具ごとにずれる。
- 影響・リスク: 動きがわずかに変わる所 — (a) eval_alt の `num` は inf を通し int のまま返すが、`schemas.num` は inf を捨てて float にする(読む値は時刻の ms と秒だけなので実害は無い)。(b) `C.pct(None, 0)` は「  -  」(幅付き)なので、`C.pct` の None を width に合わせる変更をしないと、eval_alt/eval_cut の表示が「-」から「  -  」に変わる(桁の揃え方だけ)。表の出力を文字列で比べるテストが無いか `test_eval_alt.py`・`test_eval_cut.py`・`test_eval_timing.py` で要確認。

##### 5. eval_split.py と eval_fetch.py の「一覧」入出力・JSON の読み書きの写しと、ytt_core の既存関数との重複(優先度: 中・削れる行数の目安: 約 30 行)
- 場所: `dev/eval_split.py:99-110`(`probe_sec`)・`:125-152`(`doc_sources`・`batch_running`)・`:241-259`(`plan_path`・`read_plan`・`write_plan`)・`:363-370`(`default_root`)・`:398-404`(show)/ `dev/eval_fetch.py:234-248`・`:402-408`(show)・`:391-399`(root の検査)
- 今:
  - `try: open → json.load / except (OSError, ValueError)` が eval_split に 4 つ、eval_fetch に 1 つ。`_evalcommon.read_json(path, default, limit)`(BOM 対応・サイズ上限つき)で足りる。
  - `read_plan`/`write_plan`/`plan_path` が 2 つの道具でほぼ同じ(違いは schema と名前と "path" の付与だけ)。`show` の分岐(一覧を読む → 無ければ「先に plan を実行してください」→ print)も一字ずつ同じ。
  - `probe_sec`(ffprobe を自前で呼び、`creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)` を直書き)は `normalize.probe(path)["duration"]`(eval_fetch が既に使っている)と同じ意味。
  - `doc_sources` は transcripts/*.json を**全文**読んで `sourcePath` だけ取り出している。
- 案: `read_plan(root, name=PLAN_NAME, schema=SCHEMA)` と `write_plan` を eval_split に 1 つだけ置いて eval_fetch がそれを呼ぶ(中身は `C.read_json` と `fsio.write_json`)。`def probe_sec(path): return round((normalize.probe(path) or {}).get("duration") or 0.0, 2)` に縮める(名前は残す)。`doc_sources` は `{p for d in txindex.load(folder) for p in d["_paths"]}` を**検討**(AGENTS.md の「紐づけの規則は txindex だけ」に沿い、更新日時のキャッシュも効く)。
- 理由: 2 つの道具の CLI の骨組みが双子で、一方を直すともう一方の見落としが起きる。
- 影響・リスク: `probe_sec` は `test_eval_split.py:112-122` が `E.probe_sec` を差し替えるので、名前を残す。`doc_sources` の置き換えは**要確認**: txindex の `_parse` は `segments` が list でない文書を捨てる(テストの文書が segments を持つか)・`_paths` は付け替える前のパスも含む(「使用中」の判定が広がる = 動画を移さない側に倒れる)。`test_eval_split.py`・`test_eval_fetch.py:110,128,141` が `read_plan` を通る。

##### 6. eval_alt.evaluate_one(85 行)の分割と小さな整理(優先度: 中・削れる行数の目安: 約 15 行(長さより見通しの改善が主))
- 場所: `dev/eval_alt.py:380-464`(evaluate_one)・`:248-255`(group_named の手書きの記憶)・`:294-331`(Agg.add の辞書の数え上げ)・`:364-377`(both で全文書を 2 回読む)
- 今: `evaluate_one` に alt と yt の 2 つの読み方(`:393-418`)・結果の注意文(`:442-455`)・meta(`:456-459`)・採否の記録(`:460-462`)が 1 本に入り、`source == "alt"` の分岐が 6 回出る。`no_alt` は alt と yt で意味が違う数を同じ変数に入れて、最後に `noAlt`/`noYt` の名前だけ変えている(`:457`)。
- 案: `_load_alt(...)`・`_load_yt(...)` を「`(alt, key, diff_fn)` か、数えて飛ばしたときは None」を返す 2 関数にして、ループは `LOADERS[source]` を呼ぶだけ(注意: alt では doc の読み込みの前に `alt.json` の有無を見る順番を保つ。大きい文書を無駄に読まないため)。`group_named` は `functools.lru_cache`、`Agg.stats`・`why` は `collections.Counter`(STAT_KEYS を 0 で初期化して、結果のキーが減らないようにする)。注意文は `_notes(skipped, source, ...)` に出す。
- 理由: 担当内で一番長い関数で、alt/yt の読み分けが後から足された跡が見える。
- 影響・リスク: 動きは同じ。`test_eval_alt.py`(`E.evaluate`・`E.judge_doc`・`E.print_report`・`E.main`)で守られている。both のときに文書を 2 回読むのは、キャッシュ化するなら別の判断(使用頻度が低いので今は触らなくてよい)。

##### 7. eval_timing.apply_variants の二重の後片付け(優先度: 中・削れる行数の目安: 約 8 行)
- 場所: `dev/eval_timing.py:284-334`(特に `:287-288`,`:327-330`)・`dev/_evalcommon.py:171`(`atexit.register(shutil.rmtree, tmp, True)`)
- 今: `own = S is None` で自分で `load_serve("fake")` したときだけ、`finally` の中で環境変数 `TRANSCRIBE_DATA_DIR` の末尾が `eval_asr_` で始まるかを見て一時フォルダを消す。`load_serve` が既に同じフォルダを `atexit` で消す約束を持っている。**名前の接頭辞(`eval_asr_`)に頼った二重の後片付け**。
- 案: `own`・`shutil` の import・`finally` の後半(4 行)を削る。S を渡されたとき(テスト)は元から消さないので、動きは CLI の終了時に消えるタイミングだけ変わる。
- 理由: `load_serve` の接頭辞の約束に黙って依存している。接頭辞を変えると片方だけ消えなくなる(ゴミが残るだけで壊れはしない)。
- 影響・リスク: 一時フォルダが `apply_variants` の終わりではなくプロセスの終わりまで残る(CLI は 1 回で終わるので実害なし)。`test_eval_timing.py:224` は `serve=self.S` を渡すので、この枝は今のテストでは通っていない(`dev/tests/` に CLI の `--apply` を通すテストが無い)。

##### 8. eval_fetch.cmd_fetch のネスト・到達しない行・自前の ffmpeg 呼び出し(優先度: 中・削れる行数の目安: 約 12 行)
- 場所: `dev/eval_fetch.py:320-376`(cmd_fetch)・`:370`(`item.pop("errors", None)`)・`:251-263`(default_since)・`:175-187`(silent_ratio)・`:151-157`(run_cmd)
- 今: cmd_fetch は for item → for cand → for attempt の 3 重ループに `ok`・`errors` の旗が絡み、`if not ok: continue` を挟んでから結果を書く(5 段ネスト)。`item.pop("errors", None)` は `item` に "errors" を書く所が**どこにも無い**(`errors` は局所変数)ので、古い一覧ファイルの名残以外で効かない(**要確認**)。`default_since` は正規表現 + `date()` の try/except で日付を読むが、`datetime.strptime(s[:8], "%y-%m-%d")` で足りる。`silent_ratio` は `run_cmd` と同じ `subprocess.run(..., creationflags=tools.no_window_flags())` をもう一度書いている(標準エラー全体が要るので、`run_cmd(cmd, timeout, tail=3)` に `tail=None` を許せば共通になる)。
- 案: 1 区間の「候補を順に試して `(out, start, ratio)` か失敗の理由を返す」関数 `_fetch_one(item, plan, staging, work, used, fetcher, silence)` を切り出す。`default_since` は `dates = [strptime(...)]` を `contextlib.suppress(ValueError)` で集めて `max()`。`item.pop("errors")` は古い一覧が無いことを確かめてから削る。
- 理由: ネストを 3 段にすると、`used` と `got` の更新点が読める。
- 影響・リスク: 動きは同じ。`test_eval_fetch.py:126,140,146,153`(cmd_fetch)・`:161`(default_since)が注入した fetcher/silence で通す。`strptime("%y-%m-%d")` は 1 桁の月日(`26-5-1`)も通す(元の正規表現は 2 桁だけ)。分け方の一覧の日付は常に 2 桁なので影響しない。

##### 9. ui_audit.py: 同じ意味のまま短くできる箇所と、125 行の JS を別ファイルへ(優先度: 中・削れる行数の目安: Python 約 12 行(+ 任意で LIVE_JS の外出しで `ui_audit.py` から約 130 行))
- 場所: `dev/ui_audit.py:629-635`(run_scene の A-26/A-31)・`:279-281`(A-01)・`:283-288`(A-12)・`:225-230`(html_texts)・`:725-727`(report の uniq)・`:523,533,542`(設定を開く場面の写し)・`:355-479`(LIVE_JS)
- 今:
  - `:629-635` は「light のとき: 1440 幅なら modal ありは check_modal・なしは focus_walk、1440 以外なら modal ありは check_modal」を 2 つの if に分けて書いている。
  - `:279-281` は `each_line` と同じ「行ごとに検索 → allow を見る → add」を手で回している(違いは `data-ui-portal` の行を除くだけ)。
  - `:229` は `for a in HTML_ATTRS: re.finditer('\b%s="..."' % a)` をタグごとに 7 回。
  - `:725` の `uniq` は `setdefault + += 1` の手書きの Counter。
  - 設定を開く場面 3 つは `("click", "[data-ui-settings]"), ("wait", 400)` と `"modal": settings` を毎回書いている。
- 案:
  ```python
  if variant["name"] == "light":                              # :629-635 を 5 行に(動きは同値)
      if scene.get("modal"): check_modal(pg, scene, width, tag, out)
      elif width == 1440: focus_walk(pg, tag, out)
  each_line(text, r"""^(?!.*data-ui-portal).*(?:src|href|action)=["']/(?!/)""", "A-01", path, out, "絶対パス")   # :279-281 を 1 行に(MOUNTED の if の中)
  uniq = Counter((it["id"], re.sub(...), re.sub(...)[:60]) for it in out.items)   # :724-727
  ATTR = re.compile(r'\b(?:%s)="([^"]*)"' % "|".join(HTML_ATTRS))                   # html_texts は 1 回の finditer(返す順が属性名順から位置順に変わる)
  ```
  A-12 の 3 つの if は `(パターン, メッセージ)` の表に。`LIVE_JS`・`FOCUS_JS`・`REDUCED_JS` は `dev/ui_audit_live.js` に出して `Path.read_text` で読む(.js として編集・構文の確認ができる。行数は動くだけで減らない)。
- 理由: 検査のコードは「基準の追加のたびに写して足す」形で太りやすい。まず同値の短縮だけ。
- 影響・リスク: **ui_audit.py にテストが無い**(`dev/tests` に無い)。守るのは `py -3.10 dev/ui_audit.py static --json` の出力が直す前後で同じ(`html_texts` の返す順だけ変わるので、指摘の並びが変わっても件数・id・場所が同じことを確かめる)と、`all --demo` の Must 0 件。`static` は 0.65 秒で流れる。速度は問題ない(実測)ので速くする目的の変更ではない。

##### 10. dropbox_auth.py: 到達しない防御(優先度: 低・削れる行数の目安: 約 7 行)
- 場所: `dev/dropbox_auth.py:33,37-41`(`_UNRESERVED`・`make_verifier`)・`:134-139`(webbrowser の try/except)
- 今: `make_verifier` は `secrets.token_urlsafe(64)[:96]` を作り `assert _UNRESERVED.match(v)`。`token_urlsafe(64)` は 86 文字で `[:96]` は何もせず、文字は `A-Za-z0-9_-` なので assert は**常に通る**。`webbrowser.open(url)` は失敗しても例外を投げず False を返すだけで、`except Exception: pass` は不要(import も try の中にある)。
- 案: `return secrets.token_urlsafe(64)` だけにして `_UNRESERVED` を消す(テスト `test_verifier_shape_and_random` が 43〜128 文字・unreserved の文字を正規表現で見ているので、守りはテストが持つ)。`import webbrowser` を先頭に出して `webbrowser.open(url)` の 1 行に。`write_config` は項目 3。
- 理由: 実行のたびに通る assert と、起きない例外の握りつぶしは読む人に「何かが起きうる」と誤解させる。
- 影響・リスク: 動きは同じ。`test_dropbox_auth.py` が守る。

##### 11. sync_ui_kit.py: 2 つのループの統合と、使われていない js の埋め込み(優先度: 低・削れる行数の目安: 約 12 行)
- 場所: `dev/sync_ui_kit.py:73-106`(main)・`:57-70`(embed)・`:26`(MARKS["js"])
- 今: `main` は「ファイルの写し」と「index.html の中の印の間」の 2 つのループで、それぞれ「読む → 違えば diffs に足す → 書く」を別に書く。`EMBED_TARGETS` に入っているのは css だけで、`MARKS["js"]` と `</script` の検査はテスト(`test_ui_kit_sync.py`)の中でだけ使われる。
- 案: `wanted(k) -> {path: 期待する中身}` を作り(ファイルの写しは `expected_files`、埋め込みは `embed(read(path), ...)` の結果)、`diffs = [p for p, w in wanted.items() if not exists(p) or read(p) != w]` → `--check` でなければ書く、の 1 本に。ValueError は wanted の中で出るので、書き込みの途中で止まる(今は先に写してから埋め込みで止まりうる)ことも避けられる。js の埋め込みを消すかは**ユーザー確認**(テスト 3 件も直す)。
- 理由: 「ずれている写し」の判定が 1 か所になる。
- 影響・リスク: `test_ui_kit_sync.py` が `main(["--check"])`・`embed`・`read` を守る。書き込み側の `main`(--check なし)はテストが無いので、直したあとで `py -3.10 dev/sync_ui_kit.py` → `--check` → `git status` で差分が出ないことを確かめる。

##### 12. eval_import.py の軽い整理(優先度: 低・削れる行数の目安: 約 10 行)
- 場所: `dev/eval_import.py:70-79`(`_git_root`)・`:129`・`:154-167`(`_copy_hash`)・`:54-58`(`default_dest`)・`:141-145`(項目 3)
- 今: `_git_root` は while ループで親を上がる。`except (OSError, UnicodeDecodeError, ValueError)` の `UnicodeDecodeError` は ValueError のサブクラスで余計。`_copy_hash` は `while True: chunk = read(); if not chunk: break`。
- 案: `cur = pathlib.Path(_norm(path)); return next((str(p) for p in (cur, *cur.parents) if os.path.lexists(p / ".git")), None)`(`lexists` なのでリンクの .git も同じ扱い)。`for chunk in iter(lambda: fi.read(1 << 20), b"")`。`default_dest` は `datadir.data_root()` を使うと Mac の置き場所と `YTT_DATA_DIR` の扱いが変わるので**今のまま**でよい。
- 理由: 小さな整理。**この道具は「届いた zip を信用しない」関所なので、削る量より動きの据え置きを優先**する。
- 影響・リスク: `test_eval_import.py`(353 行・約 20 件。symlink・リポジトリ内・git 作業フォルダ内の拒否まで)が強く守る。

##### 13. demo_env.seed(102 行)の JSON 書き込み(優先度: 低・削れる行数の目安: 約 10 行)
- 場所: `dev/demo_env.py:74-78,125-127,139-143,160-164`
- 今: `with open(...,"w") as f: json.dump(x, f, ensure_ascii=False)` が 5 か所、その前に `os.makedirs` が 4 か所。
- 案: `fsio.write_json(path, obj, indent=None)`(フォルダも作る。出力は元と同じバイト列)。`seed` は `segments`・`write_tx` をモジュールの関数に出すと 100 行の関数が 2 つに割れる。
- 理由: 見本データを作るだけの道具だが、`ui_audit live --demo` の土台なので読みやすさを上げる価値はある。
- 影響・リスク: テストは無い。守るのは `ui_audit.py live --demo` が同じ件数で通ること(流す場合は担当外の他のテストと同時にしない)。

##### 14. count_sparse_rows.py は役目を終えた可能性(優先度: 低・削れる行数の目安: 124 行(削除する場合))
- 場所: `dev/count_sparse_rows.py` 全体
- 今: 「長い区間に文字が少ない行」を数える 1 回きりの測定(`docs/design/edit-tool-design.md` の 12 ③-1)。参照は設計書 2 か所だけで、測った結果の規則は `ed_jobs.sparse_row`(本体)と `ed_fill.fill_sparse_row`(0.60.0 の後処理)に入った。テストは無い。`import serve as TX` は `load_serve` を通さず serve.py を読む。
- 案: ユーザーに確認のうえ削除(AGENTS.md の「既存機能の削除は先に確認」)。残すなら `C.load_serve("fake")` を使って他の eval_* と読み込み方をそろえる。
- 理由: 使われない道具は読む量と保守を増やす。
- 影響・リスク: 削除は設計書のリンク切れになる(`docs/design/edit-tool-design.md:289` と `phase0-restructure.md:62` は過去の記録なので書き換えない規則)。

##### 15. push_helper.py: 大きいファイルを全部読み込んでから判定する(優先度: 低・削れる行数の目安: 0 行(安全性の整理))
- 場所: `dev/push_helper.py:117-118`(`staged_blob`)・`:145-159`(`check`)・`:35`(GitHub のトークンの 2 つの正規表現)
- 今: `git show :path` で**ファイルを丸ごと** Python に読み込んでから `len(data) > MAX_BYTES` を見る。この検査は「動画・キャッシュの混入を止める」ためにあるのに、混入した巨大なファイル(数 GB の動画)を先に全部メモリへ読む。1 ファイルごとに git を 1 回起動する(未計測)。
- 案: `git cat-file -s :path` で大きさだけ先に見て、5MB 超なら中身は読まずに「大きすぎる」で止める。`GitHub のトークン` の 2 つの正規表現は 1 つの `(?:gh[pousr]_...|github_pat_...)` に。多数のファイルは `git cat-file --batch` 1 本にまとめられるが、効果は**要実測**。
- 理由: 守りの部品なので、短くするより「最悪の入力で固まらない」ことが価値。
- 影響・リスク: 5MB 超のファイルの中身は秘密情報の検査をしなくなる(どのみち大きさで止まるので結果は変わらない)。`test_push_helper.py` は `check(read=...)` に差し替えを渡す作りなので、`problems_for(path, data)` の形を変えない案(`staged_blob` が最初の `MAX_BYTES + 1` バイトだけ読んで止める)が安全。守りを減らさない範囲で、急がない。

#### 他のグループとの重複の疑い(担当外のファイル。「疑い」・要確認)
- 疑い: 「有限の数」の `num` が担当外にも: `dev/eval_asr.py:141`(入れ子の def)・`dev/eval_marks.py:183`・`dev/eval_speakers.py:100`・`src/ytt_core/txindex.py:47` の `_num`(これは `schemas.num` を呼ぶ形で正しい)。項目 4 を dev/ 全体に広げられる。
- 疑い: eval_* の骨組み(項目 1)は `eval_marks.py`・`eval_effort.py`・`eval_speakers.py`・`eval_asr.py` に同じ形で残っている(行は項目 1 に記載)。`_evalcommon` に足すのは全員が使う前提で、担当のグループ(`_evalcommon` を見る G12 など)と合わせて 1 回で入れたほうが差分が散らからない。
- 疑い: `dev/_evalcommon.py:127-141` の `save` が自前の原子書き込み(項目 3)。`:90-92` の `pct` は None の表示が幅によらず 5 文字固定(項目 4)。`:142-148` の `utf8_stdout` と同じ try/except が `dev/dropbox_auth.py:116-119`・`push_helper.py:163-166`・`run_editor_suite.py:63-66`・`lint.py:253-256` にもある(`contextlib.suppress(AttributeError, ValueError)` の 2 行に揃えられる)。
- 疑い: `dev/eval_split.py:48-52,43`(`fold`・`_SEP`)と `:55-71`(`roster_members` の「3 文字未満・common は種類 2」)は `src/editor/roster.py:21,26-30,80-90`(`_SEP`・`fold`・`_keys`)の写し(コメントにも「同じ」と書いてある)。editor の serve.py を読み込まない方針のための複製だが、`roster.py` は標準ライブラリだけの軽い部品。ただし `src/editor` を `sys.path` の先頭に足すとツール間の同名 .py(serve.py など)と衝突しうるので、`importlib.util.spec_from_file_location` で roster.py だけ読む形を editor 側のグループと相談。
- 疑い: `dev/eval_cut.py:134-153`(`find_pack`)は `src/ytt_core/txindex.py:195-209`(`read_pack_record`)とほぼ同じ読み方(違いは「中のファイルが消えていても記録を使う」)。`read_pack_record(..., require_files=True)` の引数を足せば eval_cut 側の約 8 行が消える(ytt_core の変更なので ytt_core の担当と)。
- 疑い: `dev/demo_env.py:181` が `src/home/tests/test_launch.py` の `_copy_tool` を import している(`e2e_*` と同じ流儀。テストの部品に本番の道具が依存する形)。home のテストのグループが `_copy_tool` を共通の場所に移すなら一緒に。
- 疑い: `dev/count_sparse_rows.py` の規則は `src/editor/ed_jobs.py:754-772`(`sparse_row`)と `ed_fill.py:62`(`fill_sparse_row`)が持つ(項目 14)。

