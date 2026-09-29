# 段0: リポジトリのフォルダの整理と置き場所の入れ替え
> 状態(2026-09-30): 未着手。計画は Claude(Cowork)が作成、実施は Claude Code(PC)。線 A の段1 より先にやる(線 B とも同時に進めない)。
> 全体の計画は `docs/ROADMAP.md`。ファイルの数・行は 2026-09-30 の GitHub の main 時点(始める前に今のコードで確かめ直す)。

## 決まったこと(ユーザー 2026-09-30)
- リポジトリの中の並べ替えとフォルダ名の変更を**両方やる**
- Python のパッケージ化(`sys.path` に足して読み込むのをやめ、相対 import にする)は**後回し**。今回は触らない
- 実施は **Claude Code(PC)**。Windows でテストを全部流せるため
- 置き場所は `Desktop\youtube-test` から **`C:\dev\youtube-tools`** に変える(新しい場所に clone し直して入れ替える)
- 動画(`E:\Video\...`)の整理は**保留**(あとでまとめて移す。今回は動画・作業データのパスに触らない)

## 目的
- ルートと各ツールのフォルダを見て、何が本体・テスト・道具・資料かが分かるようにする
- フォルダ名を今の役割(ホーム・スタジオ・編集・パックの部品)に合わせる
- PC の作業フォルダに溜まった git の管理外のファイル(`Claude outputs`・`__pycache__` など)を、clone し直すことで一度に片付ける

## 新しい構成
```
youtube-tools/
├─ README.txt  AGENTS.md  CLAUDE.md
├─ start.bat  start.command  push.bat      ← ダブルクリックするものだけを直下に置く
├─ home/          ← app/
├─ studio/        ← clip-studio/
├─ editor/        ← transcribe-tool/(AGENTS.md・CLAUDE.md・README.txt はこのフォルダに残す)
├─ cut2resolve/   ← そのまま(CLI の名前なので)
│    各ツールの下に tests/ を作り、test_*.py・e2e_*.py・*.cjs とテスト用のデータを移す
├─ ytt_core/      ← そのまま(import の名前なので)
├─ ui-kit/        ← そのまま(e2e_styleguide.py は ui-kit/tests/)
├─ holo-colors/   ← そのまま(e2e_holo_colors.py は tests/ へ。members.json を ytt_core/colors.py が読むので同じリポジトリに残す)
├─ setup/         ← インストールと片付け(ユーザーが実行するもの)
├─ dev/           ← tools/ の開発用の道具とそのテスト
├─ .design/       ← そのまま(design-brief などのスキルが .design/<名前>/ に書く決まりのため)
└─ docs/
     ROADMAP.md  WORKLOG.md  HANDOVER.md
     spec/  plan/  design/  archive/
```

### 設計の判断
- **ツールはルート直下に置いたままにする**(`apps/` の下にはまとめない)
  - 理由: ツールの位置が1段深くなると、「ツールのフォルダの1つ上 = リポジトリ直下」という前提が崩れる。この前提は次の場所で使っている
    - `ytt_core` を探す `_load_core()`(studio/common.py・editor/serve.py・cut2resolve/serve.py)
    - `.runtime` の場所(`ytt_core/runtime.runtime_dir`・`studio/handoff.py`)
    - `home/launch.py` の `ROOT`
  - まとめる場合はこの前提を全部直すことになる。どうせパッケージ化で入口の作り方ごと変えるので、そのときに一緒にやる(同じ場所を2回直さない)
- **フォルダ名と識別子を分ける**
  - 変えるのはフォルダ名だけ。データや通信に書かれる識別子(下の「変えないもの」)は、これまでの文字起こし・案件・作業データとの互換のため変えない
  - フォルダ名の対応を1か所にまとめる: `ytt_core/layout.py` を新しく作り、`TOOL_DIRS = {"app": "home", "studio": "studio", "transcribe": "editor", "cut2resolve": "cut2resolve"}` と `repo_root()` を置く
  - launch・mount・cases・txindex・datadir の以前の場所・sync_ui_kit・e2e がここを読むようにする。次の改名(パッケージ化)のときに直す場所を1つにするため

## 対応表(旧 → 新)
| 旧 | 新 | メモ |
|---|---|---|
| `app/` | `home/` | テスト・e2e は `home/tests/` |
| `clip-studio/` | `studio/` | `ui-kit.css`・`ui-kit.js` の写しはツールの直下に残す |
| `transcribe-tool/` | `editor/` | `tx_worker.py`・`hololive-roster.json` は直下に残す |
| `transcribe-tool/install*.bat` `install*.command` `requirements.txt` | `setup/` | Mac の `.venv` は今までどおり `editor/.venv`(install.command の作る場所と、editor/serve.py・home/launch.py の探す場所をそろえる) |
| `transcribe-tool/TRANSCRIPTION_V2_DESIGN.md` | `docs/archive/` | |
| `cut2resolve/resolve-ui-test/` `resolve_lua_mock.lua` | `cut2resolve/tests/`(データは `tests/fixtures/`) | 日本語の名前のファイル(`友人へ.txt`)があるので、git の `core.quotepath` に注意 |
| `start-all.bat` / `.command` | `start.bat` / `.command` | ユーザーのショートカットも作り直す |
| `tools/cleanup_legacy_data.bat` `.py` | `setup/` | |
| `tools/` のその他(push_helper・removals.txt・sync_ui_kit・eval_asr・baseline_analysis・count_sparse_rows・demo_env・e2e_pipeline・e2e_datadir と test_*) | `dev/`(test_* は `dev/tests/`) | push.bat の中の `tools\` も直す |
| `docs/pipeline.md` `data-location.md` `ui-guidelines.md` `usability-heuristics.md` | `docs/spec/` | |
| `docs/plan/*` `transcription-overhaul-plan.md` `ui-audit-2026-09-28.md` `accuracy/` | `docs/plan/`(accuracy は `docs/plan/accuracy/`) | 監査は段1〜5 が参照しているので plan に置く |
| `docs/integration-plan.md` `edit-tool-design.md` `mockups/` `whole-retranscribe-design.md` `resolve-pack-unification.md` `holo-colors.md` | `docs/design/` | |
| `docs/project/` `review/` `followup-2026-09-27.md` `backlog-ui-2026-09-27.md` | `docs/archive/` | |

## 変えないもの(互換のため。grep で当たっても直さない)
- 作業データのフォルダ名: `%LOCALAPPDATA%\youtube-tools\{app,studio,transcribe,cut2resolve}\`
- 起動の ID: `.runtime/<ID>.json` の ID(`studio`・`transcribe`・`cut2resolve`)、`--only studio,transcribe,cut2resolve`
- `/api/ping` の `app` の値: `"clip-studio"`・`"transcribe-tool"`・`"ytt-launcher"`(`ytt_core/runtime.TOOL_APPS`・`studio/core.js:201`)
- JSON に書く名前: `tool.name`(`"clip-studio"`・`"transcribe-tool"`)、`clip-studio/v1` などの schema
- URL: `/studio/`・`/transcribe/`・`/cut2resolve/`、ポート 8700
- 画面の localStorage のキー、Resolve に置く Lua の名前
- 過去の記録: WORKLOG・`docs/archive/`・`docs/design/` の中の旧パスは書き換えない(WORKLOG と ROADMAP の先頭に、この対応表へのリンクを置く)

## 直す場所(目安。2026-09-30 の grep では、コード側でフォルダ名を含む行が約 400 行・約 70 ファイル。大半は識別子なので1行ずつ仕分ける)
1. フォルダを前提にした場所: `home/launch.py`(`TOOLS` の `dir`・ROOT)・`home/mount.py`(`MOUNTS` の `dir`)・`home/cases.py:47`・`ytt_core/txindex.py:37`・`ytt_core/colors.py:29`・`ytt_core/datadir.py`(以前の場所)・`editor/serve.py:1420`(YTT_CORE_DIR)
2. テストを `tests/` に移すと、読み込み先が1つ上になる
   - 各テストの `HERE` と `sys.path` を直す。テスト用に一時フォルダへ写すものは、写す一覧と除く一覧(`e2e_ui_mounted.py:43`・`home/test_launch.py:610`・`e2e_edit_common.py`)を直す
   - 写したツールに `tests/` を含めない
3. `dev/`: `ROOT = dirname(dirname(__file__))` の形はそのまま使える。`sync_ui_kit.py` の `FILE_TARGETS` と `EMBED_TARGETS`、`push_helper.py` の `ALLOW` とメッセージ、`baseline_analysis.py` の既定の出力先、`test_resolve_pack_contract.py`
4. `.bat` と `.command`: start・push・setup の中のパスと案内文(`(youtube-test)` → `(youtube-tools)`、`start-all.bat` → `start.bat`)。**`.bat` は ASCII だけ**(push.bat の注意書き)
5. 画面の文: `editor/app.js:2758`(`start-all.bat`)など、ユーザーに見せる案内
6. `.gitignore`: 旧フォルダ名を含む行(`cut2resolve/packs/` は同じ)、`.design/*/screenshots/`
7. 資料: `AGENTS.md`(フォルダの表・テストのコマンド・`Desktop\youtube-test` の2か所)・`README.txt`・各ツールの README・`editor/AGENTS.md` のテストの実行・`docs/ROADMAP.md` の 8 の索引・`docs/spec/`・`docs/plan/` の中のパス

## テストの整理
- 版の番号が付いた古い e2e(`e2e_ui_v07/v08/v09/v098.py`・`e2e_eval_v093.py`)
  - 機能の名前に付け替える
  - 「版 v0.9.4」の判定による想定内の失敗(`editor/AGENTS.md`)は、判定を今の版から読む形に直し、全部通る状態にする
  - 中身が他の e2e と重なるものを消すときは、先に一覧をユーザーに見せて確かめる
- 移したあとのテストのコマンドを `AGENTS.md` の表と `editor/AGENTS.md` に書き直す(実行する場所をリポジトリ直下にそろえると迷わない)

## 手順
1. **始める前**
   - WORKLOG に「段0 開始・GPT は作業を止める」を書く
   - `git status` が空であること(他の AI の作業途中が無いこと)を確かめる
   - 今のテストを全部流して、失敗の一覧を控える(整理の前から落ちているものを、整理のせいにしないため)
2. **コミット1: コードの移動と直し**
   - `git mv` とパスの直しを1つのコミットにする(途中で起動できない状態のコミットを作らない)
   - 中身の変更を小さく保ち、git が改名として追えるようにする(`git log --follow` が効くように)
   - `ytt_core/layout.py` もこのコミットで足す
3. 全部のテストと `python dev/e2e_pipeline.py`・`python dev/e2e_datadir.py` を流し、`start.bat` で起動してホーム・スタジオ・編集・パックを開く
4. **コミット2: 資料の移動と索引の直し**(`docs/` と AGENTS・README)。ROADMAP に段0 の行と対応表へのリンクを足す
5. WORKLOG → ユーザーに push.bat を頼む(または Claude Code が push)
6. **入れ替え**(ユーザーの PC。Claude Code が手順を案内する)
   1. 入口を「すべて終了」
   2. `git clone https://github.com/sirloin2983/youtube-tools1 C:\dev\youtube-tools`
   3. `C:\dev\youtube-tools\start.bat` で起動し、作業データ(今までの案件・文字起こし)が見えることを確かめる。作業データは `%LOCALAPPDATA%` にあるので、そのまま引き継がれる
   4. 古いフォルダを消す前に、次を確かめる
      - スタジオの書き出し先(スタジオの設定、または `%LOCALAPPDATA%\youtube-tools\studio\settings.json` の `outDir`)が古いフォルダの中(`clip-studio\exports`)を向いていないか
        - 向いていたら**古いフォルダを消さない**(動画が消える)。動画を移すまで残す(動画の整理は保留中)
      - 古いフォルダで `git status --ignored` を見て、必要なもの(`Claude outputs` の中身など)を残す
   5. 古いフォルダを `youtube-test_old` に改名して、しばらく残す(問題が出なければ、ユーザーが手で消す)
   6. 新しい場所に向け直す: デスクトップのショートカット、Codex(GPT)と Claude Code の作業フォルダ、Cowork でつなぐフォルダ

## 実機で確かめること
- `start.bat` での起動と、Edge の窓で開くこと(Edge の専用プロファイルは作業データの側にあるので、そのまま引き継がれる)
- 今までの案件・文字起こし・パックの一覧が表示されること(作業データとの互換)
- 「編集」からパックを作れること、文字起こしのワーカーが動くこと(GPU・話者判別の部品)
- `push.bat` が新しい場所で動くこと(`dev\push_helper.py`)
- `holo-colors\build.bat`

## リスク
- **テストの読み込み先の直し漏れ**: 移したテストが、古い場所の同じ名前の部品を読んでしまう
  - 対策: 古いフォルダではなく新しく clone した場所でも一度テストを流す
- **識別子を誤って変える**: `/api/ping` の `app` の値などを変えると、入口がツールを見分けられなくなる
  - 対策: 「変えないもの」を grep の前に確かめる
- **スタジオの書き出し先が古いフォルダの中にある**: 古いフォルダを消すと動画を失う
  - 対策: 手順 6-4
- **ほかの AI との同時編集**: 手順 1 で止めてもらい、終わったら WORKLOG で知らせる
