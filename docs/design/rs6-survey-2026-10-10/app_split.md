状態(2026-10-10): RS6 の下調べ(Haiku)の報告(サブエージェントが本文で返した報告を、まとめ役がそのまま置いた)

# RS6 下調べ: app/server.py と live/autorun の分割・L2/L3

読むだけの調べ。行番号は grep と部分読みによる。推測は「推測」と書いた。

## 1. src/home/autorun.py(808 行)の分類
| 関数(行) | 分類 | 重なり・メモ |
|---|---|---|
| ToolClient(111)・call/ok(117/150) | app(HTTP の口) | 入口から各ツールの API を呼ぶ。live.py の studio_call(403)も使う |
| _yt_id_ok・_doc_id_ok・live_auto_origin・_busy_reason・_rec_key(157-189) | ① の補助 | 検査と鍵。pipeline/run.py へ寄せられる |
| AutoRunner(195) | app の殻 + ① + 友人 | `class AutoRunner(delivery_mod.Delivery, run_mod.Runner)`。Runner を継ぎ、hook(298-335, 715-799)を埋める |
| _save_active・_restore_active(233/249) | app(起動し直しの記録) | autorun-active.json。入口の作業データ |
| _await_tools(276) | app | ツールの準備待ち |
| _streamer・_auto_streamer・_marks_arg・_pref(298-335) | app(ホームの設定を読む hook) | prefs を読む。run.py の Runner は既定値のみ |
| _enqueue・start・start_new・start_docs・start_request・start_file(342-463) | app(入口の受付) | start_request/start_file は友人の依頼(human/friend)の入口 |
| estimate・_estimate_out(465-534) | ① の見積もり | run.py の段の表と重なる。書き込まない |
| _active_runs・_wake・restart_info・_redo_work・cancel・snapshot・history・_remember・_log・close・_trim(535-658) | app | 記録(runlog)と待ちの一覧 |
| _loop(667) | app(糸) | _execute(719) で ① を呼ぶ |
| _docs・_studio_video・_pick_doc・_checkpoint(711-730) | ① の hook | Runner にも同名あり(run.py 273-296) |
| _deliver_batch_limits・_remember_delivered・_remember_doc_streamer・_friend_length・_remember_styles(735-799) | 友人 | delivery.py の Delivery と重複が見える(推測: 一部は mixin 側へ移し損ね) |

run.py との重なり: Runner(run.py 258〜)に hook の既定(273-322, 410-415)があり、AutoRunner が上書きする。`execute` `_run_steps` `_step_*` `_pack_one` は run.py 側が本体(369〜)。

## 2. src/home/live.py(1236 行)の分類
| 関数(行) | 分類 |
|---|---|
| validate_url(123)・probe_live(151)・_clean・_rec_view・_same_stream・recorder_data_dir・_read_token・is_local_url(145-209) | ingest(録画の入口・URL 検査) |
| studio_review・studio_audio・studio_lag(222-254) | app(画面の読み口) |
| Live 本体(255〜) の __init__ | app(配線)。runner は既定で入口の server.autorun を返す(269) |
| archiver(365)・Archiver 生成(379) | ingest/archive(pipeline/ingest/live_archive.py)。**Runner は使わない** |
| exporter(356) | pipeline/export |
| studio_call(397)・adopt・_studio_adopt_mark・export_studio(784-880) | app → studio API(autorun の ToolClient と同じ形) |
| ytt・_ytt・recent・_relay(918-1003) | app |
| begin・begin_request・active_requests・request_for・auto_deliver_for(607-765) | app + 友人(L3 に近い。_auto_deliver_for 757 は友人届けの判定) |
| _tick・tick・spawn・health・stop_recorder(1097-1200) | app(録画子プロセスの監視) |

結論: **ライブの流れは Runner を使っていない**。配信後の全自動は `live.py`→`live_archive.Archiver`(pipeline/ingest)→ exporter 直で、autorun の run(①)とは別の経路。3 つの経路(autorun 本体・live_archive・live.py)が並ぶ、という計画 5-1 の記述と一致。

## 3. src/home/launch.py(1335 行)・mount.py・prefs.py・start.bat
- launch.py: `_spec`(113)・runtime_dir・ping(141)・port_open・tail・tool_python・signal_stop・Tool(202)・Supervisor(264-550: start/stop/restart/monitor)・PortalHandler(595)・do_GET/do_POST(621/677)・`_post_*`(706-776)・streamer_colors(792)。
  - 外へ出せる物(推測): Supervisor・Tool・ping・port・tail・runtime_dir・tool_python・signal_stop(ツール子プロセスの管理 = app/supervisor 相当)。streamer_colors・_color_entry は ytt/colors 寄り。PortalHandler と _post_* は app/server の HTTP 配線に残る。
- mount.py: tool_modules・check_no_collision・load_serve・make_handler・Mount(184)。ツールの serve を取り込む層。app に残す。
- prefs.py(489 行): Prefs(396)と各 _clean_*(96〜338)。設定の検査。app に残す(ホームの設定)。
- start.bat: `py -3.10 src\home\launch.py %*`。分割するなら start.bat の 1 行を変える(推測: 転送を残せば bat は変えなくてよい)。
- `src/app/` は `__init__.py` と `ui/` のみ(server.py は無い)。

## 4. L2(書き出しのあとの check)・L3(手で届ける)の場所
- L2: run.py の from_ 表(63)。`check` の段(40 行のコメント: 「② check は自分の配信の書き出しのあと(L2)と手で置いた動画・URL が使う」)。
- L3(手で届ける): human/friend/deliver.py(zip 化・preview・group・`write_group_json`・`Job` 系 317〜)と human/friend/delivery.py(Delivery mixin: `_deliver*`・`_pool_*`・`flush_pools`・`_deliver_failure`・`_step_deliver`(87))。画面側は編集の「友人へ届ける」・案件の「採用して届ける」(js/API 名は未確認)。
- 「直したらその段からやり直す(from)」: run.py の `run(client, input, spec, from_=...)`(931)と FROM_MODE(63)が既に入口。必要なもの(推測): (a) 段の名前と状態の保存(Run.saved/restore 162-217 が既にある)、(b) 届ける段の成果物(packs・delivered)の鍵、(c) 友人の pool 状態(delivery._pools_load/_save)。

## 5. 分割案とリスク(推測を含む)
1. 先に AutoRunner の hook 重複を消す: _docs・_studio_video・_pick_doc・_checkpoint・_remember_styles・_remember_doc_streamer・_deliver_batch_limits を run.py の Runner か delivery.py の 1 か所へ。
2. live.py の Archiver 経路を run の 1 本へ寄せるかは後回し(配信後の全自動は本番で動いているため、まず経路の一覧 1 枚を作る)。
3. launch.py から Supervisor・Tool・ping・port 系を app/supervisor.py へ。PortalHandler は app/server.py。
4. 最後に転送を消す(RS5 と同じ手順)。

リスク: 本物の配信(録画中・書き出し中)が動く玄関を割ると、起動し直しで実行の記録(autorun-active.json)と録画の子プロセスが切れる。分割は入口を停止した状態で、テストは test_launch・test_autorun・test_live*・e2e_live*・e2e_autorun で確認し、本番の配信は止まっている時間に行う。Supervisor の子プロセスの後始末(SIGTERM/SIGBREAK)も変えない。
