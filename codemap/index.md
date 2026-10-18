# コードの地図(目次)

自動で作った物(`python dev/code_map.py`。古いと `python dev/lint.py` の code-map が言う)。手で直さない。
探し方: 画面の言葉なら [words.md](words.md)、`/api/...` の口なら下の表、役目なら層ごとの md を見る。行の番号は作った時点の物。

| 層 | md | ファイル | 行 |
|---|---|---|---|
| ytt(基盤) | [ytt.md](ytt.md) | 48 | 11025 |
| ① pipeline(道具 = データを加工する) | [pipeline.md](pipeline.md) | 64 | 24284 |
| ② flow(管理 = いつ・どの順で・どこに置くか) | [flow.md](flow.md) | 87 | 29424 |
| ③ human(人の操作) | [human.md](human.md) | 59 | 17385 |
| ④ manage(データ) | [manage.md](manage.md) | 42 | 11771 |
| ⑤ eval(検証) | [eval.md](eval.md) | 33 | 14728 |
| src/app(入口と画面) | [app.md](app.md) | 92 | 40072 |
| src/friendapp(友人の玄関) | [friendapp.md](friendapp.md) | 48 | 19137 |
| その他の画面(editor・studio・ui-kit・cut2resolve) | [tools.md](tools.md) | 49 | 21695 |
| dev・setup(開発の道具) | [dev.md](dev.md) | 56 | 14425 |
| friend-apps・chrome-ext(C# のアプリ・拡張) | [apps.md](apps.md) | 18 | 8716 |

## `/api/...` の口(受ける所 → 呼ぶ所)

受ける所は .py の処理(比べる・表の鍵)。呼ぶ所は画面の .js・.cs・ほかの .py(テストは除く)。

- `/api` — dev/code_map.py:208・dev/spec_check.py:98・src/app/live.py:318
- `/api/accuracy` — src/app/server.py:653 ← portal.js
- `/api/accuracy/run` — src/app/server.py:661 ← portal.js
- `/api/adopt` — src/app/live.py:342
- `/api/archive` — src/app/live.py:351・src/app/live.py:348 ← review.js
- `/api/archive/cancel` — src/app/live.py:348 ← review.js
- `/api/backup` — src/app/server.py:652 ← portal.js
- `/api/backup/run` — src/app/server.py:660 ← portal.js
- `/api/begin` — src/app/live.py:332 ← new.js
- `/api/build` — src/cut2resolve/serve.py:381 ← pack-tab.js・tools.py
- `/api/cases` — src/app/server.py:829 ← cases.js・portal.js
- `/api/cases/auto` — src/app/server.py:656 ← portal.js
- `/api/check/answer` — src/app/server.py:662 ← check.js
- `/api/check/flush` — src/app/server.py:662 ← check.js
- `/api/check/next` — src/app/server.py:823 ← cases.js・check.js・portal.js
- `/api/check/skip` — src/app/server.py:662 ← check.js
- `/api/cleanup` — src/app/server.py:663・src/app/server.py:792 ← portal.js
- `/api/clip-info` — src/editor/serve.py:240・src/editor/serve.py:193 ← app-tools.js
- `/api/collab/anchor` — src/studio/serve.py:460 ← collab.js
- `/api/collab/group` — src/studio/serve.py:221・src/studio/serve.py:456 ← collab.js・queue.js
- `/api/collab/group/add` — src/studio/serve.py:457 ← collab.js
- `/api/collab/group/delete` — src/studio/serve.py:459 ← collab.js
- `/api/collab/group/remove` — src/studio/serve.py:458 ← collab.js
- `/api/collab/groups` — src/studio/serve.py:220 ← collab.js
- `/api/config` — src/studio/serve.py:463 ← new.js・settings.js・app.js
- `/api/diarize` — src/editor/serve.py:287 ← app-jobs.js・tools.py
- `/api/doc-diarnum` — src/editor/serve.py:312 ← app-jobs.js
- `/api/doc-for` — src/editor/serve.py:261・src/editor/serve.py:193 ← app-jobs.js・app-tools.js
- `/api/drill/candidates` — src/editor/serve.py:252 ← app-jobs.js
- `/api/drill/next` — src/editor/serve.py:251 ← app-learn.js
- `/api/drill/reviewed` — src/editor/serve.py:314 ← app-learn.js
- `/api/drill/status` — src/editor/serve.py:250・src/editor/serve.py:193 ← app-learn.js
- `/api/drill/unreviewed` — src/editor/serve.py:315 ← app-learn.js
- `/api/edit` — src/editor/serve.py:257・src/editor/serve.py:595・src/editor/serve.py:193 ← app-tools.js・app.js・cut.js・pack-tab.js
- `/api/edit/draft` — src/editor/serve.py:258 ← app.js・cut.js
- `/api/edit/pack` — src/editor/serve.py:309 ← pack-tab.js・tools.py
- `/api/edit/pack-readme` — src/editor/serve.py:260 ← pack-tab.js
- `/api/edit/preview` — src/editor/serve.py:310 ← pack-tab.js
- `/api/effort` — src/editor/serve.py:311・src/editor/serve.py:193 ← app-learn.js
- `/api/eval-batch` — src/editor/serve.py:256
- `/api/eval-batch/redo` — src/editor/serve.py:305
- `/api/eval-batch/redo-one` — src/editor/serve.py:306 ← app-learn.js
- `/api/eval-batch/start` — src/editor/serve.py:303
- `/api/eval-batch/stop` — src/editor/serve.py:304
- `/api/eval-folders` — src/editor/serve.py:255 ← app-tools.js
- `/api/eval-folders/organize` — src/editor/serve.py:301 ← app.js
- `/api/eval-folders/settle` — src/editor/serve.py:302 ← app-tools.js
- `/api/export` — src/app/live.py:335・src/studio/serve.py:219・src/studio/serve.py:454 ← review.js・tools.py・value.py
- `/api/export-file` — src/editor/serve.py:296 ← cut.js・app-tools.js・tools.py
- `/api/export/cancel` — src/app/live.py:346・src/studio/serve.py:455 ← review.js・tools.py・value.py
- `/api/exports` — src/app/live.py:284 ← review.js
- `/api/flow/cancel` — src/app/server.py:658・src/friendapp/server.py:505 ← cli.py・app.js・portal.js・review.js
- `/api/flow/estimate` — src/app/server.py:657 ← portal.js・ui-kit.js
- `/api/flow/history` — src/app/server.py:820・src/app/server.py:806 ← portal.js
- `/api/flow/machine` — src/app/server.py:809・src/app/server.py:882
- `/api/flow/outbox` — src/app/server.py:814
- `/api/flow/outbox/done` — src/app/server.py:659
- `/api/flow/retry` — src/app/server.py:658
- `/api/flow/runs` — src/app/server.py:654 ← cli.py・app-list.js・portal.js・rank.js・review.js ほか 1
- `/api/flow/status` — src/app/server.py:816・src/app/server.py:806・src/friendapp/server.py:343 ← cases.js
- `/api/flow/submit` — src/app/server.py:657・src/friendapp/server.py:496 ← cli.py・review.js・ui-kit.js
- `/api/friend/cancel` — src/friendapp/server.py:432
- `/api/friend/decide` — src/friendapp/server.py:415・src/friendapp/server.py:116 ← friend_preflight.py
- `/api/friend/files` — src/friendapp/server.py:423 ← MainForm.cs
- `/api/friend/inbox` — src/friendapp/server.py:291 ← friend_preflight.py
- `/api/friend/live-settings` — src/friendapp/server.py:434
- `/api/friend/local` — src/friendapp/server.py:436・src/friendapp/server.py:116
- `/api/friend/media` — src/friendapp/server.py:321 ← receive.js
- `/api/friend/notice-seen` — src/friendapp/server.py:484 ← friend_preflight.py
- `/api/friend/open` — src/friendapp/server.py:438・src/friendapp/server.py:444
- `/api/friend/palette` — src/friendapp/server.py:421 ← palette.js
- `/api/friend/peek` — src/friendapp/server.py:306
- `/api/friend/peek-live` — src/friendapp/server.py:311
- `/api/friend/pick-file` — src/friendapp/server.py:407
- `/api/friend/pick-folder` — src/friendapp/server.py:472
- `/api/friend/player` — src/friendapp/server.py:316・src/friendapp/server.py:419
- `/api/friend/prefs` — src/friendapp/server.py:427
- `/api/friend/receive` — src/friendapp/server.py:318 ← friend_preflight.py
- `/api/friend/report` — src/friendapp/server.py:425・src/friendapp/server.py:116
- `/api/friend/retry` — src/friendapp/server.py:430・src/friendapp/server.py:116
- `/api/friend/send` — src/friendapp/server.py:404・src/friendapp/server.py:116
- `/api/friend/settings` — src/friendapp/server.py:339・src/friendapp/server.py:461
- `/api/friend/settings/key` — src/friendapp/server.py:467
- `/api/friend/setup` — src/friendapp/server.py:300・src/friendapp/server.py:457 ← friend_preflight.py・server.py
- `/api/friend/state` — src/friendapp/server.py:302 ← friend_preflight.py・Launcher.cs
- `/api/friend/streams` — src/friendapp/server.py:341 ← send-list.js
- `/api/friend/streams/refresh` — src/friendapp/server.py:459 ← send-list.js
- `/api/friend/tidy` — src/friendapp/server.py:296・src/friendapp/server.py:449 ← server.py
- `/api/friend/undo` — src/friendapp/server.py:417・src/friendapp/server.py:116 ← friend_preflight.py
- `/api/friend/update` — src/friendapp/server.py:298 ← friend_preflight.py
- `/api/friend/update/apply` — src/friendapp/server.py:451 ← friend_preflight.py
- `/api/friend/upload` — src/friendapp/server.py:358 ← send-form.js
- `/api/health` — src/app/server.py:790 ← portal.js
- `/api/history` — src/editor/serve.py:253 ← app-rows.js
- `/api/info` — dev/ui_audit.py:94・src/app/live.py:296 ← new.js・ui-kit.js
- `/api/intake` — src/app/server.py:651 ← portal.js・rank.js・review.js
- `/api/intake/scan` — src/app/server.py:660 ← portal.js
- `/api/job` — src/cut2resolve/serve.py:366・src/cut2resolve/serve.py:97 ← cut.js・app-tools.js
- `/api/job/cancel` — src/cut2resolve/serve.py:381 ← pack-tab.js・tools.py
- `/api/jobs` — src/editor/serve.py:245・src/editor/serve.py:193 ← autorun.py・server.py・app-jobs.js・app.js・pack-tab.js ほか 1
- `/api/jobs/retry` — src/editor/serve.py:317 ← app-jobs.js
- `/api/learned` — src/editor/serve.py:247 ← app-learn.js・portal-edit.js
- `/api/live/adopt` — src/studio/serve.py:449 ← live_adopt.py
- `/api/live/exported` — src/studio/serve.py:450 ← review.js・live_export.py
- `/api/live/section` — src/studio/serve.py:451
- `/api/log` — src/app/server.py:794 ← portal.js
- `/api/mach-changes` — src/editor/serve.py:262 ← machpick.js
- `/api/mach-changes/pick` — src/editor/serve.py:313 ← machpick.js
- `/api/metrics` — src/editor/serve.py:249 ← app-learn.js・portal-edit.js
- `/api/open-folder` — src/cut2resolve/serve.py:381 ← pack-tab.js
- `/api/outdir` — src/studio/serve.py:464 ← settings.js
- `/api/peaks` — src/app/live.py:277・src/app/live.py:344・src/editor/serve.py:501 ← cut.js・review.js
- `/api/pick` — src/editor/serve.py:307 ← app-tools.js
- `/api/ping` — src/app/server.py:784・src/cut2resolve/serve.py:364・src/cut2resolve/serve.py:97 ← server.py・cut.js・app.js・portal.js・livesession.py ほか 2
- `/api/plan` — src/cut2resolve/serve.py:381 ← cut.js
- `/api/queue` — src/friendapp/live_session.py:91・src/studio/serve.py:214 ← autorun.py・queue.js・rank.js・live_archive.py・tools.py
- `/api/queue/add` — src/friendapp/live_session.py:88・src/studio/serve.py:443 ← cand.js・queue.js・live_archive.py・tools.py
- `/api/queue/cancel` — src/studio/serve.py:444 ← queue.js・tools.py
- `/api/queue/clear` — src/studio/serve.py:447 ← queue.js
- `/api/queue/retry` — src/studio/serve.py:446 ← queue.js
- `/api/queue/skipchat` — src/studio/serve.py:445 ← queue.js
- `/api/rank/import-official` — src/studio/serve.py:440 ← rank.js
- `/api/rank/live` — src/studio/serve.py:213 ← rank.js
- `/api/rank/registry` — src/studio/serve.py:211・src/studio/serve.py:466 ← rank.js
- `/api/rank/resolve` — src/studio/serve.py:439 ← rank.js
- `/api/rank/search` — src/studio/serve.py:212・src/studio/serve.py:441 ← rank.js
- `/api/rank/search/cancel` — src/studio/serve.py:442 ← rank.js
- `/api/relink` — src/editor/serve.py:298 ← app.js
- `/api/relink/check` — src/editor/serve.py:297 ← app-tools.js
- `/api/relink/find` — src/editor/serve.py:300 ← app-tools.js
- `/api/relink/missing` — src/editor/serve.py:299 ← app-tools.js
- `/api/rerun` — src/editor/serve.py:291 ← app-jobs.js・app.js
- `/api/resolve-package` — src/editor/serve.py:538 ← pack-tab.js
- `/api/restore` — src/editor/serve.py:294 ← app.js
- `/api/retime` — src/editor/serve.py:308 ← app-rows.js
- `/api/roster` — src/editor/serve.py:241 ← app-learn.js
- `/api/settings` — src/editor/serve.py:499・src/editor/serve.py:583・src/studio/serve.py:210 ← cand.js・cut.js・app-core.js・pack-tab.js・portal-edit.js ほか 7
- `/api/settings/patch` — src/editor/serve.py:293 ← cut.js・app-core.js・settings.js・ui-kit.js
- `/api/shutdown` — src/app/server.py:663・src/friendapp/server.py:492 ← friend_preflight.py・Launcher.cs・portal.js・host.js
- `/api/siblings` — src/cut2resolve/serve.py:365・src/cut2resolve/serve.py:97・src/editor/serve.py:239 ← app-core.js
- `/api/speakers/sub` — src/editor/serve.py:289 ← autorun.py
- `/api/state` — src/studio/serve.py:209 ← cand.js・new.js・settings.js・app.js
- `/api/status` — src/app/server.py:786 ← cli.py・cases.js・edhost.js・check.js・portal.js ほか 1
- `/api/suggest` — src/editor/serve.py:248 ← app-learn.js
- `/api/suggest/feedback` — src/editor/serve.py:295 ← app-learn.js
- `/api/thumb-ideas` — src/editor/serve.py:259・src/editor/serve.py:292 ← pack-tab.js
- `/api/thumb-ideas/image` — src/editor/serve.py:505 ← pack-tab.js
- `/api/title` — src/studio/serve.py:218 ← review.js
- `/api/tools` — src/editor/serve.py:242 ← app-jobs.js・app.js・portal.js
- `/api/transcribe` — src/editor/serve.py:286 ← app-jobs.js・tools.py
- `/api/transcribe/cancel` — src/editor/serve.py:316 ← app.js・tools.py
- `/api/transcript` — src/editor/serve.py:254・src/editor/serve.py:591・src/editor/serve.py:609 ← cut.js・app-rows.js・app.js
- `/api/transcripts` — src/editor/serve.py:246・src/studio/serve.py:217 ← app-list.js・review.js・tools.py
- `/api/video` — src/studio/serve.py:216・src/studio/serve.py:467 ← review.js・value.py・cases.py
- `/api/video/delete` — src/studio/serve.py:452 ← review.js・live_cleanup.py
- `/api/video/request-marks` — src/studio/serve.py:453 ← tools.py
- `/api/videos` — src/studio/serve.py:215 ← collab.js・rank.js・review.js
- `/api/videos/open` — src/studio/serve.py:448 ← new.js・queue.js・review.js
- `/api/voices` — src/editor/serve.py:243 ← app-jobs.js
- `/api/voices/delete` — src/editor/serve.py:290 ← app.js
- `/api/voices/learn` — src/editor/serve.py:288 ← app.js
- `/api/voices/preview` — src/editor/serve.py:244 ← app.js
- `/api/window` — src/app/server.py:661 ← portal.js
- `/api/ytt` — src/app/mount.py:46 ← ui_audit.py・ui-kit.js
- `/api/ytt/client-log` — src/friendapp/server.py:511
- `/api/ytt/streamer-colors` — src/friendapp/server.py:509 ← cut.js・app-rows.js・send-form.js
