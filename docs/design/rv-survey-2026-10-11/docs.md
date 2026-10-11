# RV 下調べ 5: 資料(docs/・plan/・AGENTS・README)と R1

状態(2026-10-11): 読むだけの下調べ(Sonnet の報告を Opus がまとめた)。数え方のスクリプトと全 100 本の表は残していない(やり直すときは同じ方法 = 文書の中のバッククォートのパスを実在と突き合わせる)。

## 1. 全体
- 文書は 100 本。大きい物: `docs/WORKLOG.md` **3,588 行・923KB**(見出し 240)・`plan/decisions.md` 639 行・196KB・`docs/design/code-review-simplify-2026-10-08.md` 2,747 行・`role-restructure-map-2026-10-09.md` 1,758 行・`src/editor/README.txt` 1,408 行・`src/home/README.txt` 860 行・`src/editor/AGENTS.md` 613 行。
- **ROADMAP・HANDOVER・直下 README のリンク切れは 0 件**。
- AGENTS.md は 148 行だが最長の行が **約 6,900 文字**(「フォルダの並び」の `src/` の行に RS0〜RS7-2 の経緯)。

## 2. 索引(`docs/ROADMAP.md`)に無い文書
- `docs/design/rs8-cases-build.md`・`rs8-flow-api.md`・`v1-check-build.md`
- `plan/f1-friend-pc.md`・`plan/rs8-cases-ui.md`
- `docs/design/briefs/rs8-cases/`(DESIGN_BRIEF・grill・inventory・mock/preview.html。mock/index.html だけ載る)
- `docs/design/rs5-survey-2026-10-10/` の 4 本・`rs6-survey-2026-10-10/` の 9 本(plan_order だけ載る)

## 3. 今の実装と食い違う記述(経緯の文書 = WORKLOG・docs/design は除く)

| 文書 | 食い違い | おすすめ |
| --- | --- | --- |
| `AGENTS.md` | 版「仮に 0.58.0」(実際 0.59.0)・`src/` の行の経緯 約 6,900 文字・表の「RS3 で〜へ移した」の列挙・CLI の終了コードなど仕様の詳細 | 直す(優先)。今の決まり(層 5 つ・向き・禁止)だけにし、経緯は `plan/role-restructure.md` 8 節へリンク 1 本。テストのコマンドの列挙は `dev/run_*` か各フォルダの README へ。**7 割ほど削れる** |
| `src/editor/AGENTS.md`(613 行) | 「現在 v0.69.0」・消えた `ed_*.py`・`ed_lite.py`・`drill.html`・`index.html`・`e2e_edit_*.py` など 84 件・無いフォルダ `docs/plan/`・無い文書 3 本 | 直す(優先)。今の仕様書なのでずれが害になる。画面のページが消えた今、`src/editor/` に残る物(画面の部品と serve)だけの短い文書に |
| `docs/HANDOVER.md` | 版 0.58.0・「次」に RS8 を始める手順が残る | 直す |
| `docs/spec/pipeline.md` | `pipeline/batch.py`・`runlog.py`・`run.py`・`live_failures.py`・`live_report.py`・`src/home/live_export.py`(今は `flow/`)・`/studio/?video=` を今の URL のように | 直す |
| `docs/spec/settings.md` | 消えた e2e(`e2e_edit_cut.py`・`e2e_ui.py`)・`ed_learn.py`・`test_review.cjs` | 直す |
| `docs/spec/data-location.md`・`friend-intake.md` | `src/home/tests/test_backup.py`・`dev/eval_marks.py` | 直す |
| `src/ui-kit/README.md` | `src/ytt_core/colors.py`・`editor/lite.html`・`/cases.html` | 直す |
| `src/home`・`src/studio`・`src/editor` の README.txt | `/studio/?video=`・`/transcribe/?doc=` を今の画面のように(今は 302)・`dev/eval_*`・`ytt_core`・`ed_jobs`・`tx_worker` が各 17 件ほど | 直す。ユーザー向けの README を直下の 1 本 + 画面ごとの短い説明に寄せるかを相談 |
| `plan/improvements.md` | `dev/eval_*.py`・`src/editor/ed_ytcap.py`・`studio/analyze.py` | 直す(R1 と一緒に) |
| コードの説明文 | 古い層の番号(`human/proof/` の先頭が「② 人の操作の層」)・「転送だけの殻。RS5 で消す」・計画の記号(flow だけで M○ 139・0-○-○ 77・RS7-2 G○ 39 など。`plan/opt-pipeline-flow.md` の「説明文の中の記号」) | 直す。説明は「今どう動くか・なぜか」だけ。効く決まり(決定 3-○・仮決め)の参照は残す。記号の早見表を ROADMAP の近くに 1 枚 |

## 4. `plan/data.js` の整合
1. V1 が `todo` のまま(V2b〜V3 が入っている)→ `doing`(V4 中のセッションが直す可能性あり。触る前に確認)
2. `userTasks.provisional` が空 = decisions 3-40・3-41・`docs/design/rs8-flow-api.md` の「仮」「ユーザー未確認」と食い違う(AGENTS の決まり「仮決めを足したら provisional にも」)
3. U8(送るアプリ 2.9.0 を本物で)は本文に「10-11 に外した」とあるのに `todo` → `wait` か F1 へ
4. U5 が tasks と userTasks の 2 か所
5. 衝突表(206 行あたり)の `src/ytt_core/excite.py`・`src/studio/analyze.py` は古いパス
6. R1 の本文「やり方を確認してから」→ 下の 5 の案で聞く

## 5. R1(資料の整理)のやり方の案(AI 2〜3 時間)
1. **WORKLOG を日ごとに**(1 時間): `docs/worklog/YYYY-MM-DD.md` に機械で割る(改行を保つ Python 1 本)。`docs/WORKLOG.md` は書式・最後の数日・各日へのリンクだけ。注意: AGENTS・HANDOVER・テストが「WORKLOG の末尾に追記」を前提にしている → 追記先の決まりを変える(「その日のファイルの末尾」)/ 並行セッションの追記を巻き込まないよう、静かなときに 1 コミットで。
   - 代わりの案: 分けずに「10-07 と同じ圧縮」(古い日を 1 件 1 行に)を 10-03〜10-09 に当てる。追記の決まりは変わらない。**おすすめはこちら**(決まりもテストも変えずに 3,588 → 1,000 行ほど)。
2. **decisions を未確認だけに**(1 時間): 確定した 1・2・3 節は `docs/design/decisions-archive.md` へそのまま移し、`plan/decisions.md` には未確認(3-40・3-41・rs8-flow-api の案)と「やらないこと」の短い表。番号(3-33 など)は data.js・WORKLOG・コードから引かれているので**変えない**・移した先にも同じ見出し。
3. **line-*.md を残りだけに**(30 分〜1 時間): 済んだ物(line-a-proofread-effort・line-a-remaining・line-b-extra-ideas・line-b-overlap・line-b-row-split・ux-stage7-9・code-separation)は `docs/design/` へ移すか「残り」の節だけに。進行中(line-b-transcription・line-d-*)は「残り」を先頭へ。
4. 同じ作業で: ROADMAP に 2 の文書を足す・provisional を埋める・AGENTS を削る。

## 6. 統合・消す候補(経緯の文書)

| 対象 | 行 | おすすめ |
| --- | --- | --- |
| `docs/design/rs3〜rs7-survey-*`(約 35 本) | 約 4,000 | 各 RS の plan_order(最終版)だけ残し、報告そのままの下調べは git の履歴へ。消す前に決定の根拠が decisions 3-○・`plan/role-restructure.md` 8 節に残っているかを確かめる |
| `docs/design/rs8-cases-build.md`・`rs8-flow-api.md`・`v1-check-build.md` | 約 400 | V1 が済んだら決めたことの要約 1 本に |
| `docs/design/code-review-simplify-2026-10-08.md`・`role-restructure-map-2026-10-09.md`・`code-separation-inventory-2026-10-09.md` | 約 4,700 | 結論の数行を残して消す |
| `plan/code-separation.md` | — | 消す(自分で「置き換え済み」と書いてある) |
| `docs/design/briefs/ui-overhaul`・`ux-consistency` | 約 1,450 | DESIGN_REVIEW だけ残して短く |
| `docs/design/mockups/edit-mock.html`・`briefs/cyber-theme/board.*` | — | 消す(参照元が無い試作) |
| `docs/spec/` の規則(code-quality・subtitle-notation・row-timing-policy・usability-heuristics・ui-review-criteria・sound-tags・eval-folder) | 小 | 残す |
| `phase0-restructure`・`resolve-pack-unification`・`integration-plan`・`holo-colors` | 各 60〜200 | 残す(軽い・状態の行あり) |
