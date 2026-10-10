状態(2026-10-10 夕): ユーザーの案「① を道具に徹し、① を管理する ② を新しく作り、旧 ②〜④ を ③〜⑤ にずらす。友人へは ② + α」の検討(Fable。本文で返した物をまとめ役がそのまま置いた)。まだ決定ではない

# 層を 5 つにする案の検討

## 結論
案は採る価値がある。本質は「番号を 1 つずらす」より、今 app(serve 3 本 + AutoRunner)と pipeline/run.py に散っている**段取り**を 1 つの層にし、① から段取りを抜くこと。これで「単体で動かす」の 4 つの詰まり(置き場所・SLOTS とワーカー・登録の口・設定)が全部 ② の責任に収まる。代償は ② の transcribe の段を ③(doc_jobs)なしで動く形にする直し 1 つ(1 の悪 c)。

## 1. 良い所・悪い所
- 良 (a) 今の違反 0 は「向き」だけで「中身の純度」は守れていない。batch.py が ③ store を注入で呼ぶ(`Batch(store)`)、Runner が 4 か所で `GET /api/settings`、serve.py 161-196 が登録 = 段取りが ① と app に半分ずつ。② を作ると持ち主が 1 つになる
- 良 (b) 決まり 2〜6 が強まる: ① は画面・案件に加えジョブ・鍵・設定・上書きも知らない / 人の直しは ② が ytt/schemas の形で読んで重ねるだけ / 鍵は ② が計算して成果物の横に書く(材料 = 束・学習データの版・上流の鍵は全部 ② が持つ)/ ① の記録 = ② の結果の束と runlog / 登録の口は ① に置き ② が登録(⑤ fake は ② の wire に旗で差す)/ 作業データは ② の「置き場所」の compat モード = 当面そのまま
- 良 (c) F-1・F-4・F-5・F-6・F-7・F-8 は「② の仕事」と置ける。F-2(上書きの付け替え)と F-9(案件の表示)は ④
- 良 (d) 精度の輪 (A) = ⑤ が ① を直に純関数で回せる。(B) = ③ 書く → ④ 置く → ② が束に場所と版を入れる → ① 読む
- 良 (e) 単体 = ② + ① だけ。③ の hook(doc_jobs.set_hooks・set_context_namer)は要らなくなる
- 悪 (a) ② が新しい「何でも屋」になる危険 → 鉄則「① = 入力 → 出力の変換(ファイルやワーカーを触っても可)、② = それをいつ・どの順で・どの場所に・飛ばすかだけ。② に変換のコードを書かない」を lint か test_layering で機械的に守る
- 悪 (b) 層が 6 つ(ytt + 5)。移動量は小さい(約 8 ファイル)が、文書と data.js の番号の付け替えは全部に及ぶ
- 悪 (c) transcribe のジョブの本体は ③ `doc_jobs.run_job`。② が ③ を呼べないので「機械の文書を作る」部分(transcribe_rows → fill → llm → _rows_to_doc → _doc_fields → write_doc/words/asr)を ① `pipeline/transcribe/clipjob.py`(仮)へ切り出すのが必須。intoDoc・evalRedo・norm_after・autodiar・alt・ytcap は ③ の run_job が ① を呼んだ後に足す形に残す(O2 は不要。ファイルは同じ `transcripts/<id>.json` のまま、original・recognition・words・asr = ① の持ち分、segments の proofed など = ③ の持ち分と定義する)
- 悪 (d) 実行中の入口を割る点は同じ。AutoRunner・Live は app に残し、中の段取りだけ ② を呼ぶ形

## 2. ① と ② の境目(案)
| 事柄 | ① 道具 | ② 管理 |
| --- | --- | --- |
| 引数 | 入力パス・束の該当の節・出力先のパス(明示)・log・cancel | 束を組む(spec.merge・validate。設定ファイルの dict は app・CLI が渡す) |
| 鍵と使い回し | 知らない | make_key で計算 → .key.json を横に書く・一致なら飛ばす |
| 置き場所 | 受け取ったパスに書く(当面は workdata を読む今の形で可 = ② が set_data_dir する) | 置き場所の持ち主。RS6 は compat(今の作業データ / CLI は --data-dir)、実行ごとのフォルダは後で |
| ジョブの表・SLOTS | HeavySlots は ytt に残す(資源の原始) | 待機列・優先・排他・取り消し・retry・register = ytt/jobs の後半を ② へ。③ が自分の種類を ② の表に登録するのは可 |
| ワーカー | worker.py・protocol・RemoteModel・backend.select()(口) | WorkerClient の起動・停止・idle・優先度・FAKES_MODULE・GPU の調べの結果を束へ |
| 学習データ | 束の場所から読むだけ | 実行の頭で版(ハッシュ)を取り結果の束に書く(F-8) |
| 人の上書き | 見ない | .over.json・data.json の採用と不採用を ytt/schemas の形で読んで重ねる(書く側は ③) |
| ライブ | 1 秒ごとの検出(Online・PeakBook)は ① の純計算 | 配信中ずっと回す・採用のたび export → transcribe → pack・締めの猶予(F-7)。Archiver の swap・handoff も ② |
| 結果の束・記録 | 段ごとの出力の dict を返す | 結果の束を組む・runlog に書く・live_failures・live_report |

② と ④ の境目: ② は書く、④ は読んで解釈する。② = 鍵・結果の束・runlog を書く / ④ = それを読んで案件の状態を出す(F-9)・速報版と本番版の有効化と上書きの付け替え(F-1・F-2)・保管・片付け・調子。④ は ② に「この段からやり直し」を頼める。② は案件を知らない。

## 3. ③ → ① の直呼び
「ファイルを書く・ワーカーを使う・SLOTS が要る」なら必ず ② のジョブ経由、純粋な計算(alt_diffs・retime_candidates・postproc・fill の行単位)は直に呼んでよい。「選んだ行の再認識」はワーカーを使うので ② のジョブ(今も add_job 経由 = 実態は変わらない)。

## 4. 行き先の当たり(フォルダ名は ① = `pipeline/`(残す)・② = `flow/`(新))
- ① に残る: analyze(excite・analyze・live_detect・live_excite_worker)・export(exporter・manifest)・ingest(rec_core・recorder・sources・live_align_worker)・transcribe(tx_engines・txbase・postproc・records・recognize・fill・llm・retime・replace・roster・diarize・worker・backend・live_tx_worker)+ 新 clipjob・pack 全部。worker_client は割る(RemoteModel・protocol は ①・WorkerClient の起動と後始末は ②)
- ② へ: pipeline/run.py・spec.py・batch.py・runlog.py・live_failures.py・live_report.py・export/live_export.py・ingest/live_archive.py・transcribe/live_tx.py・ytt/jobs.py の待機列部分 → flow/jobs.py・新 flow/wire.py(serve 161-188 の登録)・新 flow/keys.py・(後で)flow/placement.py
- 層の表: LAYERS = ytt, pipeline, flow, human, manage, eval, app。app の autorun・live・serve 3 本は app のまま(中の段取りを flow へ呼び替え)

## 5. 友人へ ② + α
- α の候補: (a) CLI + spec.json の雛形 + install.bat(ffmpeg・whisper.cpp Vulkan の prebuilt・モデルは初回に取得)= 第 1 版 / (b) 小さな GUI(request-sender の C# の殻を流用して CLI を起動)/ (c) 学習データの写し = 名簿・置換辞書は同梱、覚えた声は同梱しない(個人を見分ける情報)/ (d) 結果の束を Dropbox に戻してもらい ⑤ で測る(任意)
- 今の流れとの関係: 両立。Dropbox の流れは GPU の無い友人用に残し、② + α は自分の PC で回す友人用。③ friend は渡さない

## 6. ユーザーに確かめる問い
1. 番号と名前: ①〜④ → ①〜⑤ に全部付け替える(推奨)/ 番号は変えず「②' 段取り」を挟む
2. transcribe の段の持ち主: ① に clipjob を切り出し ③ の run_job はそれを呼んで ③ の分を足す(推奨。ファイルは同じ)/ ① の成果物と ③ の文書を別ファイルにする(O2)
3. 単体の置き場所: --data-dir(推奨)/ 実行ごとのフォルダを最初から
4. ③ → ① の直呼びの線: 書く・ワーカー・SLOTS は ② 経由、純計算は直(推奨)/ 全部 ② 経由
5. 友人への α の第 1 版: CLI + spec + install.bat だけ(推奨)/ GUI も。名簿・辞書は同梱・声は同梱しない

RS6 への影響: plan_order の Q1 の A'(CLI が serve 3 本を起こす)は不要になり、B(② が ① を関数で呼ぶ)に寄る。順は「flow/ を作り run・spec・batch・jobs・wire を移す(動きは同じ)→ clipjob を切り出す → 段が束を読む → 鍵(flow/keys)→ CLI」。見積もりは plan_order の 2 日に +1 日(推測)。
