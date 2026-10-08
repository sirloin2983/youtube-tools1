# LLM の後処理(提案 P18 の設計)+ P28 の訂正

状態: **設計の案・実装はまだ**(2026-10-08。ユーザー「やってみてもいいから具体的にどうするのか知りたい」。計画 `plan/data.js` には未反映。始める前に 6 の確認)

- 経緯: `plan/proposals-2026-10.md` の P18(「LLM での書き直し」の再提案)。10-08 に効いた後処理 D(名簿の表記ゆれ直し)の一般化として、**疑わしい箇所だけ**をローカル LLM に直させる
- 関連: 後処理 A・C・D の作り(`src/editor/ed_fill.py`・`ed_jobs.py`)、2 つ目のエンジン(`tx_engines.py` の `LlamaQwen3`)、守り 4 つ(`plan/decisions.md` 10-08)、サムネの案(`plan/thumb-ideas.md`。LLM の実行部品を共有)
- 調べ方: サブエージェント(Sonnet)がコードを読んで実装点を確認(10-08)。LLM = 大規模言語モデル(文章を扱う AI。ここでは llama.cpp で PC の中だけで動かす)

## 0. 先に: 前提の訂正と、要る確認
- **テキスト用の LLM のモデル(GGUF)はまだ PC に無い**。置いてあるのは Qwen3-ASR 1.7B(音声用)だけ。P18 は新しいモデルの取得(2.5〜5GB)= 依存の追加なので、始める前に確認(6-1)
- **P28 の前提「Qwen3-ASR の context は未測定」は誤り**。10-08 の実験で名簿の名前の列挙を system に渡して測り済み: 基準 CER 16.0%・名前 25/46 → 列挙 16.8%・名前 25/46(変わらず)、文の形 19.2%・余分が 93 → 194。まだ測っていないのは「配信の題名」「直前の行」「かな表記」だけ(7)
- 研究の数字(日本語): プロンプトだけ・n-best だけではほぼ効かない(15.5 → 15.4)。選別なしに全行を直させると 43% を書き換える過剰訂正。選別すると書き換え率 11〜14% で相対 1〜4% の改善。固有名詞の再現率は 44.5 → 82%(微調整した場合)。→ この設計は「疑わしい箇所だけ・差分だけ・上限つき」。**全体の CER より名前の再現率(今 47.5%)が主な効き目**で、期待は控えめ

## 1. 何をするか(1 文書の流れ)
認識(whisper.cpp)→ A・C・D の後処理 → **E(LLM)** → 保存。E の中:
1. **選別**(`llm_pick`): 疑わしい箇所を選ぶ。手がかり = (a) 「別」(Qwen3-ASR)との不一致の語(`ed_alt.alt_diffs`)(b) whisper の語の確信度(`wordProbs`)が低い語 (c) 名簿の呼び名と音が近い語(かな化して編集距離 1〜2)(d) 名簿の `misrecognitions` の wrong(トーイ→トワ など)。1 文書あたり上限(例 30 箇所)。手がかりが無い行は LLM に見せない
2. **問い合わせ**(`llm_prompt`): 箇所ごとに 対象の行 + 前後 2 行 + 候補(別の読み・名簿の近い呼び名)+ 配信の題名・話者 を渡し、「直す必要があれば置換案を JSON で、無ければ null」。few-shot は名簿の `misrecognitions`。出力は**差分だけ** `{row, from, to, reason, confidence}`(行を書き直させない)
3. **検査**(`llm_guard`): `to` が `from` と文字数 ±20% 以内・名簿に無い新しい固有名詞を含まない・行の他の部分を変えていない・置換後がかな化して元の音に近い(編集距離の上限)・confidence のしきい値・1 文書の編集率の上限(例 行の 15%)。落ちた案は適用せず記録だけ
4. **適用**(`llm_apply`): segments の該当の行を置き換え、`fill={"from": 元, "by": "llm"}` の印(A・D と同じ流儀 = 画面の「別の読み」ボタンと `unfill` で 1 クリックで戻せる)。`original` は触らない
5. **記録**: `transcripts/<id>.llm.json`(生の提案・採否・却下理由・モデル・プロンプトの版)と `recognition.runs[-1].llm = {model, picked, proposed, applied, rejected}`

## 2. どこで動かすか
- **ワーカーの中**(`tx_worker.py` に op `complete`)。理由: llama-server の起動と後始末(KillJob・`__del__`)・重いモデルの入れ替え(`_load_model_local`)・取り消し・黙ったワーカーの 20 分の監視・取得ファイルの SHA-256 固定(`fetch_file`)が既にある。サーバー側のプロセスでは動かさない(numpy 等を import しない決まりと同じ理由)。`SLOTS` は文字起こしジョブ(`work_one`)が持つので追加不要
- `tx_engines.py` に `LlamaText`(`LlamaQwen3` と同じ llama-server を `-m` だけ・`--mmproj` なしで起動し、`/v1/chat/completions` に文字を送る)と `LLAMA_TEXT_MODELS`(URL・大きさ・SHA-256)
- モデルの候補(Hugging Face の GGUF): **Qwen3-8B Q4_K_M(約 5GB)** が本命(日本語が強い。RX 7800 XT の Vulkan で 7B 級 Q4 が約 118 トークン/秒の報告)。軽い代案 Qwen3-4B Q4_K_M(約 2.5GB)。思考モードはオフ(`/no_think`)。1 箇所 100〜200 トークン × 30 箇所 ≒ 1 文書 30〜60 秒(推定)
- GPU の取り合い: 認識(whisper.cpp)と同じジョブの中で順に動くので同時にはならない。配信中の文字起こし(`live_tx`)とは別プロセス = D-14 の SLOTS 化に乗る。llama-server は文書ごとに起動し直さず、ワーカーが生きている間は保つ

## 3. スイッチと守り(10-08 の方針の 4 つ)
- スイッチ `autoLlm`(`ed_jobs.validate_job`: 要求 > 保存した設定 > 既定)。**最初の既定はオフ**(モデルの取得が要る・測ってからオン)。評価用の文書(`evalSet`)には当てない(A・C・D と同じ `and not ev`)。画面は ⚙ のチェック(`OPT_CHECKS` に `autoLlm`)
- 印と元の値(`fill` の `by:"llm"`)・1 クリックで戻せる(既存の `unfill`)
- 生の結果(`llm.json`)を残す → あとから同じ文書で「あり/なし」を測れる
- **学習からの除外**: `ed_learn._prep` が今、A・D で置き換えた行(`fill` 付き)を除いていないので、機械の直しを「人が直した」として学習する自己強化が起きうる。E を足すときに `fill` の行(A・D・llm)を学習の材料から除く(別の直しだが一緒に)

## 4. 測り方(採用の条件)
- 新 `dev/eval_llm.py`: `<id>.asr.json` から A・C・D を当て直し(`eval_timing.asr_raw` / `reapply` の形)→ E あり/なし → `eval_asr.score_doc`(CER・名前の再現率 `termRate`・余分の字数)。確かめ済み 22 本の対の差と 95% の範囲
- 採用の条件は `plan/line-b-transcription.md` の方式: 余分が増えない・差の範囲が悪化の側に出ない・名前の再現率が下がらない。加えて、普段の校正で「LLM の置換を人が残した率」を K1(`eval_fill`)の物差しに入れる
- 効かなければオフのまま閉じる(費用 = モデル 5GB と 1 晩)

## 5. 作るもの(大きさ M。1 晩)
- 新 `src/editor/ed_llm.py`(約 250 行): `llm_pick`・`llm_prompt`・`llm_parse`・`llm_guard`・`llm_apply`・`llm_after_doc`・`llm_path`・`read_llm`。`serve.py` に import と `_ED_MODULES`・`_delete` の一覧
- `tx_engines.py`(約 70 行): `LlamaText`・`LLAMA_TEXT_MODELS`。`_start` の `--mmproj` を任意に
- `tx_worker.py`(約 25 行): op `complete`
- `ed_jobs.py`(約 15 行): `validate_job` の `autoLlm`・`run_job` で D の直後に `llm_after_doc`・`params` の記録
- `ed_learn._prep`(約 5 行): `fill` の行を除く
- 画面(約 15 行): ⚙ のチェック・`app-rows.js` の札の文言(`by` で出し分け)
- テスト: `tests/test_llm.py`(約 150 行。選別・検査・適用・戻す・評価用には当てない・ワーカーの op。`fake_llama_server.py` に文字の返答)・e2e 1 本
- `dev/eval_llm.py`(約 200 行)・`dev/tests/test_eval_llm.py`
- 版: 編集 0.61.0・README・`src/editor/AGENTS.md`・WORKLOG

## 6. 決めてほしいこと
1. モデルの取得をしてよいか(Qwen3-8B Q4_K_M 約 5GB。Hugging Face から。SHA-256 固定。置き場所は作業データの `transcribe\models\`)。軽い 4B(約 2.5GB)から始める手もある
2. 既定はオフで、22 本で測ってからオンにする順でよいか
3. 手がかり (a) は「別」(Qwen3-ASR)の結果が要る。`autoAlt`(2 つ目のエンジンを自動で聞く)は今は既定オフなので、E のときだけ「別」も回す(認識が 1 文書あたり数十秒増える)か、(b)〜(d) だけで始めるか

## 7. P28 の訂正と残り(任せる = 1 回測って閉じる)
- 10-08 に測り済み: 名前の列挙を system に渡す → 16.0 → 16.8%(悪化)・名前は 25/46 のまま。文の形は 19.2% で余分が倍。`dev/eval_asr.py run --engine llama.cpp --context none|auto` で再現できる
- 残り: 「配信の題名」「直前の行」「かな表記」を system に渡す形(`_Qwen3Chunked.PARAMS` に `system` を足す 約 10 行 + `eval_asr` に `--q3-system` 約 20 行 + 22 本 × 各 30 秒)。期待は小さい(列挙で効かなかったため)ので、P18 の前に 1 回だけ測り、結果を `plan/line-b-transcription.md` の「効かなかったもの」か「効いたもの」に書いて閉じる
