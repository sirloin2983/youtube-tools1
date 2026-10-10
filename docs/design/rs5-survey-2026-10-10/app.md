# RS5 下調べ: app 層に残っているファイル

状態(2026-10-10): 下調べ(Haiku)の報告

読むだけの調べ。コードは変えていない。行数は `wc -l`、「配線以外」は関数名からの目安(読んでの精密な数字ではない)。行き先は `plan/role-restructure.md` 7 節の表による。

## 1. app 層の物(`dev/layer_map.py` の FILES で app)と行数

| ファイル | 行数 | 関数・クラス | 配線以外の目安 | 行き先の候補(計画 7 節) |
| --- | ---: | ---: | --- | --- |
| src/home/launch.py | 1344 | 29 | 約 40〜50%(Supervisor・ping・port・streamer_colors・read_json_body 等の起動の補助が混ざる) | app に残す(薄くする)。色の一覧 `streamer_colors` は ytt/colors 寄り |
| src/home/live.py | 1242 | 12 | 約 70%(`validate_url`・`probe_live`・`_rec_view`・`recorder_data_dir`・`studio_review`・`Live` 本体) | pipeline/ingest(録画・検出)・app(配線) |
| src/home/autorun.py | 808 | 7 | 約 80%(`AutoRunner`・`ToolClient`・キューと記録の規則) | pipeline/run.py・pipeline/runlog.py(RS1-7 で一部移した後の残り) |
| src/home/prefs.py | 489 | 23 | 約 90%(`_clean_*` の検査・既定値・読み書き) | ytt/settings(設定 1 ファイル) |
| src/home/appwindow.py | 295 | 13 | 約 80%(Edge の場所・窓の開き方・Opener) | app に残す(窓を開く配線) |
| src/home/mount.py | 226 | 9 | 約 20%(取り込み・名前の衝突検査・CSP・合言葉の注入・HTTP の振り分け) | app に残す |
| src/editor/serve.py | 850 | 27 | 約 50〜60%(`_learned`・`_metrics`・`_transcript`・`_delete_voice`・`_cancel`・`_tools_info`・`studio_data_path`・`choose_data_dir` 等の API の中身) | app(配線)・eval/drill(`_learned`・`_metrics`)・manage/cases(`_transcript` の読み) |
| src/editor/ed_state.py | 192 | 9 | 約 70%(`atomic_write`・`replace_retry`・`now_ms`・`setup_logging`・`write_mark`・`check_previous_run`・`backend_name`) | ytt(fsio・schemas・settings) |
| src/editor/ed_media.py | 155 | 6 | 約 90%(波形のピーク計算 `compute_peaks`・`get_peaks`) | ytt/tools または human/cut |
| src/editor/ed_thumb.py | 87 | 6 | 約 90%(サムネの仕様・`run_thumb`・画像の場所) | human/cut(P5) |
| src/editor/ed_misc.py | 24 | 1 | 殻(転送のみ) | 消す(RS5) |
| src/editor/thumb_ideas.py | 395 | 26 | 約 95%(サムネ案の計算・描画。app 層の一覧には入っていないが、編集の画面と結ぶ) | human/cut(P5) |
| src/studio/serve.py | 673 | 35 | 約 50〜60%(`_export`・`_collab_*`・`_video_delete`・`_put_video`・`_config`・`_settings`・`_adopt_top`・`_request_marks`・`_live_exported` 等) | app(配線)・pipeline/export・manage/cases・collab は human 寄り |
| src/studio/common.py | 126 | 6 | 約 80%(`migrate_old_logs`・`check_tools`・`env_state`) | ytt(tools・procs)・pipeline/ingest/sources(RS3-4 の残り) |
| src/studio/handoff.py | 39 | 4 | 約 90%(`runtime_dir`・`write_runtime`・`remove_runtime`・`siblings`) | ytt(runtime) |
| src/cut2resolve/serve.py | 978 | 41 | 約 60%(`request_from_spec`・`row_edge_from_spec`・`advanced_from_spec`・`keeps_from_spec`・`speaker_color_map`・`apply_speaker_styles`・`classify_warnings`・`write_pack_record`・`is_pack_dir`・`file_info`) | pipeline/pack(パックの作り)・human/cut(カットの読み)・app(配線) |
| src/cut2resolve/cut2resolve.py | 14 | 0 | 殻(.bat 用の転送) | 消す/残す(RS5 で決める) |

app 層の物の合計: **約 7,540 行**(上の 16 ファイルの合計。`thumb_ideas.py` は含めない)。配線以外がいちばん多い 3 つ:

1. `src/home/launch.py`(約 1344 行 × 40〜50% = 約 550〜670 行)。ただし起動の補助は app に残す前提なら実質の移動先は少ない
2. `src/home/live.py`(約 1242 行 × 約 70% = 約 870 行)
3. `src/home/autorun.py`(約 808 行 × 約 80% = 約 650 行)

次いで `src/cut2resolve/serve.py`(約 590 行)と `src/editor/serve.py`(約 430 行)。

## 2. app 層の中の重複(目立つもの)

| 重複 | 場所 | 内容 |
| --- | --- | --- |
| サーバーの骨組み | editor/serve.py・studio/serve.py・cut2resolve/serve.py | `probe`・`_bound`・`make_server`・`prepare`・`busy`・`finish`・`mounted_elsewhere`・`main` が 3 ファイルにほぼ同じ形で並ぶ。1 つの共通の骨組み(app)にまとめられる |
| 読み込みの転送 | editor/serve.py・studio/common.py・cut2resolve/serve.py | `_load_core` が 3 つ |
| 実行中の記録 | studio/handoff.py・cut2resolve/serve.py | `runtime_dir`・`write_runtime`・`remove_runtime`・`siblings` が同じ形で 2 か所(handoff.py は ytt の runtime へ寄せられる) |
| 原子的な書き込み | editor/ed_state.py(`atomic_write`・`replace_retry`) | ytt/fsio にも書き込みがある。ed_state の分は fsio へ寄せられる |
| 時刻 | editor/ed_state.py(`now_ms`) | ytt/schemas に同じ目的の関数がある(RS3-0B で移したもの) |

app の外との重複(参考): `safe_name` が `src/human/friend/deliver.py` と `src/ytt/names.py` に、`_run_ffmpeg` が `deliver.py` と ffmpeg 小道具(`ytt/tools.py`)に分かれている。

## 3. src/app/ の今の中身と、URL の計画

- `src/app/` の中身は `__init__.py`(1 行)と `ui/` の 2 つ。`ui/` の中身はこの調べでは見ていない(未確認)。計画の 7 節では `app/ui/studio/`・`app/ui/editor/`・`app/ui/home/`・`app/ui/kit/` の置き場を決めている。
- 計画 7 節の `app/server.py`(起動・1 つのポート・API の配線・設定の画面の API。薄く)は、RS5 で作る予定。今はまだ無い。
- **URL**: 計画 8 節の 7 番は「作業データの場所と URL は当面そのまま(`/studio/`・`/transcribe/`)。コードの単位とデータの単位を一度に変えない」。URL を変える予定は計画に無い。
- **「旧い URL の転送」の意味は計画の文だけでは決まらない**。7 節の `app/server.py` の行(「旧い URL(/studio/ など)の転送」)と 8 節の 7 番(URL は当面そのまま)が食い違って見える。RS5 の行でも「旧い URL の転送」とある。候補は (a) 旧いモジュールのパス(`tx_worker.py` などの runpy の転送)を指す、(b) URL を新しい形にする予定があり、その旧い URL を残す、の 2 つ。(a) なら既存の転送の話で、URL は変えない。**ユーザーに確かめたい点**。
- RS5 の表の「版 1 つ」「設定 1 ファイル」は app 層とは別の話で、この調べの範囲外。

## 4. 注意

- 行数と「配線以外の割合」は関数名からの目安。精密な計測ではない。
- 転送だけの殻(`src/editor/ed_*.py` の 20 行前後の物、`src/cut2resolve/cut2resolve.py` など)は app 層の一覧には入っていても、中身は無い。RS5 で消す物。
