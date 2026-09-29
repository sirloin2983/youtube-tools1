# HANDOVER — 次のセッションへの引き継ぎ(2026-09-29・編集 0.21.0 のあと)

セッションを切り替えるたびに上書きする。詳しい経緯は `docs/WORKLOG.md`、ルールは `AGENTS.md`、画面の共通のルールは `docs/ui-guidelines.md` と
`docs/usability-heuristics.md`(Nielsen の 10 の原則)、ユーザー向けの使い方はリポジトリ直下の `README.txt`。

## 今の状態
- 版: 入口 0.12.0・スタジオ 0.10.0・編集 0.21.0・cut2resolve 0.14.0・ui-kit v6
- 統合計画(`docs/integration-plan.md`。正本は Claude Docs「動画編集ツール 統合計画」)は段階0〜7 まで実装済み。
  Edge のアプリの窓を既定(pywebview は使わない)・新着配信の監視はやらない(09-27 ユーザー決定)。残る未決はポート番号だけ
- 「編集」E1〜E6・追加機能 ①〜⑦・実機の確認のあとの要望(`docs/followup-2026-09-27.md`)・画面の全面見直し(`.design/ui-overhaul/`)・
  バックログ(`docs/backlog-ui-2026-09-27.md`。A-1〜A-3・B-1〜B-11)は実装済み
- 文字起こしの大幅改善(`docs/transcription-overhaul-plan.md`):
  - 段0 の AI 側は実装済み(編集 0.20.1)。自信の度合い(`original` の各行)・`recognition.runs`・モデルを手元から読む・精度を測る道具 `tools/eval_asr.py`
  - 編集 0.21.0(09-28。`docs/whole-retranscribe-design.md`): 動画全体の再認識・声の検出が捨てすぎたら自動で緩める(標準→弱め→なし)・0 文字の所は元の行を残す・映像の上の字幕に話者の色
  - **同じ音声でも回ごとに結果がかなり違う**(Whisper の温度のフォールバック)。精度は複数回か評価用の量で比べる
- UI 追加監査(GPT・09-28。`docs/ui-audit-2026-09-28.md`)の 20 項目: **未実装・ユーザーの優先順位待ち**。
  ユーザーの方針は「自明な部分以外は確認してから」。優先度が高いのは 01(パック設定の引き出しを開いたまま Alt+1 で操作が塞がる)と 02(評価用でも「声を覚える」ができる。UI と API の両方で断る)

## 残りの作業
1. **ユーザーの作業(改善計画の律速)**: 評価用の校正(合計 15〜30 分・話者 4 人以上・配信 3 本以上。重なり声・BGM・呼び名の多い場面)と、
   字幕の書き方の規則(`docs/accuracy/USER_INPUT.md` の 7。おすすめ = つなぎ言葉は残す・算用数字・笑いは書かない・伸ばしは「ー」を伝えた段階)。
   そろったら `python tools/eval_asr.py stored` と `run` で基準を取り直す
2. **改善計画の段1(呼び名)**: 名簿に aliases と誤りやすい形 → 配信ごとの文脈をプロンプトへ → 出る人に限った置き換え。評価セットを待たずに作れる(効果の判定はセットのあと)
3. **UI 監査の 20 項目**: ユーザーに優先順位を聞いてから。`.design/ui-overhaul/DESIGN_REVIEW.md` の「Should Fix(残り)」「Could Improve」とはまだ突き合わせていない
4. 提案だけ(ユーザー確認待ち): 声の検出を Silero から pyannote の区切りのモデルに替える/併用(`docs/whole-retranscribe-design.md` の 4-3。段3・段5 とまとめて評価用で比べる)

## 実機で確かめること(クラウドでは確かめられない)
- 話者の名前から決めた字幕の色が Resolve の Text+ に入るか(Lua の SetInput)
- 「声を覚える」の照らし合わせの精度(しきい値 0.60・差 0.08 は仮)
- スタジオの ① 探す → 選んだ配信をまとめて実行(`docs/followup-2026-09-27.md` の 5。置き場所・中身は質問せずに決めた)
- 盛り上がりのグラフと山の札(見本のデータでは出ない)
- Edge の窓の中のリンクの行き先・YouTube の埋め込み(専用のプロファイルは未ログイン)・書き出し中に落ちないか

## 保留・未決(ユーザー決定。言い出されたら進める)
- ⑥ 語頭・語尾の聞き比べ(語尾がまだ切れるなら後の余白を 0.3 秒に)・③-2 の6か所の確認
- 声の分離は入れない(09-27)。改善計画の段3・段5 の評価で効けば再検討
- 複数の切り抜きをつなげる画面・字幕のトラックで行の時刻をドラッグで直す(`docs/edit-tool-design.md` の「10. 未決」)
- ホームの「単体の文字起こし」と編集の履歴で入口が2つ(どちらを主にするか未決)
- 校正のあとでパックを作り直す・まとめて実行の記録を残す(候補・未着手)
- まとめて実行の入口が5か所で見せ方が違う(`docs/usability-heuristics.md` の「気づいたこと」。原則に沿った見直しは Cowork)
- 動画の移動・改名で切れた参照を画面から付け直す機能(「動画を選び直す」。監査の 19 と同じ)
- 1回目の文字起こしが遅かった件(43 秒に 502 秒)。0.20.1 のモデルを手元から読むで直った可能性。再現したら serve.log を見る

## 作業データの別件
- 26-06-11_夏色まつり(042eed22f3d8)の動画 `Dropbox\切り抜き動画\完成品デモ\26-06-11_夏色まつり.mov` がフォルダごと見つからない(ユーザーに移した先を聞く)
- 教師データ＿夏色まつり 01〜05 は作業データの参照を直した(09-28)。保管データ(`dataset/docs/<id>/`)とスタジオの書き出しの記録は古い名前のまま(起動中のスタジオが上書きするので触っていない)

## 注意: PC が不安定な可能性(2026-09-27 に調べた)
- テスト中に、関係の無いプログラムがランダムに異常終了する(ffmpeg・Python・Playwright の node・chromium)。dwm.exe が 3 日で 256 回異常終了。
  i9-13900KF・マイクロコード 0x10B・BIOS 1.10(2022-09)。13/14世代の不安定さと症状が合う(断定はできない)。BIOS の更新を案内済み(やったかは未確認)
- → **テストが1回だけ異常終了・ありえないエラーで落ちたら、まず流し直す**

## Claude Code(PC)で作業するときの注意
- git はそのまま使える: 始める前に `git status`・`git log -5 --oneline`、段ごとに `git add <変えたファイル> docs/WORKLOG.md` → `git commit -m "[Claude] 要約"`。
  **push はユーザーの push.bat**。自分が変えていない未コミットの変更は add しない(`git add -A` を使わない)
- テストの流し方: 単体テスト(unittest)には `PYTHONIOENCODING=utf-8` を付けない・画面テスト(e2e)には付ける。契約テスト `tools/test_resolve_pack_contract.py` は単独で。
  **node は bash から見えない → Playwright 同梱の `C:\Users\you11\miniconda3\Lib\site-packages\playwright\driver\node.exe` で `--test clip-studio/test_review.cjs`**
- **説明文(docstring)にバックスラッシュを書かない**(`作業用\ ` は Python の不正なエスケープの警告 → 将来エラー)。パスの例は `/` で書く
- パッチを当てるときは、書き換える前の文字列がファイルにちょうど1回あることを確かめる(今日の作業はスクラッチの Python スクリプトでこの形にした)
- テスト用のサーバーは `CREATE_NEW_PROCESS_GROUP` で起動して Ctrl+Break で止める。Python は miniconda(`C:\Users\you11\miniconda3`。Playwright・lua もここ)
- Playwright 同梱の chromium は H.264 を再生できない(webm VP9)。CSP のある画面では `page.wait_for_function` が動かない(`evaluate` で待つ `wait_js`)
- サーバーを動かすテストは先頭で `os.environ.setdefault("YTT_DATA_DIR", "inplace")`。画面テストで配信者の色の一覧を使うときは `YTT_HOLO_MEMBERS`(ytt_core を写しても
  リポジトリの `holo-colors/members.json` を読む)
- `.bat` は CRLF・ASCII だけ

## 要点(詳しくは設計書・`docs/followup-2026-09-27.md`)
- 途中のファイルの置き場所の規則は `ytt_core/schemas.py`(`WORK_DIR`・`sidecar_path`・`find_sidecar`)の1か所。cut2resolve は `cut2resolve_core.WORK_DIR`(同じ名前か test_serve が確かめる)
- 名前 → メンバーカラーは `ytt_core/colors.py` の1か所(画面は名前のまま送る)。Text+ の色は `resolve_textplus.text_style`
- 入口へ戻るリンクは `a[data-ui-portal]`(ui-kit v5 の `UIKit.portal`)。窓を前に出すのは `app/appwindow.focus_window`
- パックは `cut2resolve/pack.py` だけが作る(変えたら契約テスト)。画面・API のパックは `readme_file=False`・`plan_file=False`・`backup` は選択
- 行の「カット済」の規則は serve.py の `edit_cut_flags` と cut.js の `rowCutFlags` の2か所

## 次のセッションに貼る指示文(Claude Code 用)
```
リポジトリは今いるフォルダ(C:\Users\you11\Desktop\youtube-test。GitHub: https://github.com/sirloin2983/youtube-tools1)。
docs/HANDOVER.md、AGENTS.md、docs/WORKLOG.md の最後の数件、docs/transcription-overhaul-plan.md、docs/ui-audit-2026-09-28.md を先に読んでから始めて。
応答は日本語で、10〜20 分ごとに中間報告して。

■ 現在地(2026-09-29)
- 版: 入口 0.12.0 / スタジオ 0.10.0 / 編集 0.21.0 / cut2resolve 0.14.0 / ui-kit v6。統合計画は段階0〜7 まで実装済み
- 文字起こしの改善は段0(AI 側)と動画全体の再認識まで済み。評価用の校正は私の作業
- UI 追加監査の 20 項目は未実装
- PC が不安定な可能性あり(HANDOVER の「注意」)。テストが1回だけ異常終了で落ちたら、まず流し直して

■ やること
- 次に何をするか(改善計画の段1 / UI 監査のどの項目から / 実機の確認の結果)を私に聞いて
- 設計の変更・依存の追加・既存機能の削除は、始める前に私に聞いて
```
