# コードの地図(目次)

自動で作った物(`python dev/code_map.py`。古いと `python dev/lint.py` の code-map が言う)。手で直さない。
探し方: 画面の言葉なら [words.md](words.md)、`/api/...` の口なら下の表、役目なら層ごとの md を見る。行の番号は作った時点の物。

| 層 | md | ファイル | 行 |
|---|---|---|---|
| ytt(基盤) | [ytt.md](ytt.md) | 52 | 11396 |
| ① pipeline(道具 = データを加工する) | [pipeline.md](pipeline.md) | 75 | 26336 |
| ② flow(管理 = いつ・どの順で・どこに置くか) | [flow.md](flow.md) | 94 | 29869 |
| ③ human(人の操作) | [human.md](human.md) | 62 | 17584 |
| ④ manage(データ) | [manage.md](manage.md) | 41 | 10885 |
| ⑤ eval(検証) | [eval.md](eval.md) | 38 | 16016 |
| src/app(入口と画面) | [app.md](app.md) | 83 | 32433 |
| src/friendapp(友人の玄関) | [friendapp.md](friendapp.md) | 48 | 18990 |
| その他の画面(editor・studio・ui-kit・cut2resolve) | [tools.md](tools.md) | 22 | 11048 |
| dev・setup(開発の道具) | [dev.md](dev.md) | 59 | 16202 |
| friend-apps・chrome-ext(C# のアプリ・拡張) | [apps.md](apps.md) | 19 | 8950 |

## `/api/...` の口(受ける所 → 呼ぶ所)

受ける所は .py の処理(比べる・表の鍵)。呼ぶ所は画面の .js・.cs・ほかの .py(テストは除く)。

- `/api` — dev/code_map.py:208・dev/spec_check.py:103・src/app/live.py:291
- `/api/accuracy` — src/app/server.py:625 ← portal.js
- `/api/accuracy/run` — src/app/server.py:632 ← portal.js
- `/api/archive` — src/app/live.py:322・src/app/live.py:319 ← review.js
- `/api/archive/cancel` — src/app/live.py:319 ← review.js
- `/api/backup` — src/app/server.py:624 ← portal.js
- `/api/backup/run` — src/app/server.py:631 ← portal.js
- `/api/begin` — src/app/live.py:305 ← new.js
- `/api/build` — src/cut2resolve/serve.py:347 ← pack-tab.js・tools.py
- `/api/cases` — src/app/server.py:767 ← cases.js・portal.js
- `/api/cases/auto` — src/app/server.py:628 ← portal.js
- `/api/check/answer` — src/app/server.py:633 ← check.js
- `/api/check/flush` — src/app/server.py:633 ← check.js
- `/api/check/next` — src/app/server.py:761 ← cases.js・check.js・portal.js
- `/api/check/skip` — src/app/server.py:633 ← check.js
- `/api/cleanup` — src/app/server.py:634・src/app/server.py:737 ← portal.js
- `/api/collab/anchor` — src/studio/serve.py:428 ← collab.js
- `/api/collab/group` — src/studio/serve.py:197・src/studio/serve.py:424 ← collab.js・queue.js
- `/api/collab/group/add` — src/studio/serve.py:425 ← collab.js
- `/api/collab/group/delete` — src/studio/serve.py:427 ← collab.js
- `/api/collab/group/remove` — src/studio/serve.py:426 ← collab.js
- `/api/collab/groups` — src/studio/serve.py:196 ← collab.js
- `/api/config` — src/studio/serve.py:431 ← new.js・settings.js・app.js
- `/api/diarize` — src/editor/serve.py:244 ← app-jobs.js・tools.py
- `/api/doc-diarnum` — src/editor/serve.py:266 ← app-jobs.js
- `/api/doc-for` — src/editor/serve.py:218・src/editor/serve.py:152 ← cases.js
- `/api/drill/candidates` — src/editor/serve.py:209 ← app-jobs.js
- `/api/drill/reviewed` — src/editor/serve.py:268 ← app-learn.js
- `/api/drill/status` — src/editor/serve.py:208・src/editor/serve.py:152
- `/api/drill/unreviewed` — src/editor/serve.py:269 ← app-learn.js
- `/api/edit` — src/editor/serve.py:214・src/editor/serve.py:525・src/editor/serve.py:152 ← app-tools.js・app.js・cut.js・pack-tab.js
- `/api/edit/draft` — src/editor/serve.py:215 ← app.js・cut.js
- `/api/edit/pack` — src/editor/serve.py:263 ← pack-tab.js・tools.py
- `/api/edit/pack-readme` — src/editor/serve.py:217 ← pack-tab.js
- `/api/edit/preview` — src/editor/serve.py:264 ← pack-tab.js
- `/api/effort` — src/editor/serve.py:265・src/editor/serve.py:152 ← app-learn.js
- `/api/eval-batch` — src/editor/serve.py:213
- `/api/eval-batch/redo-one` — src/editor/serve.py:260 ← app-learn.js
- `/api/eval-batch/start` — src/editor/serve.py:258
- `/api/eval-batch/stop` — src/editor/serve.py:259
- `/api/eval-folders` — src/editor/serve.py:212 ← app-tools.js
- `/api/eval-folders/organize` — src/editor/serve.py:256 ← app.js
- `/api/eval-folders/settle` — src/editor/serve.py:257 ← app-tools.js
- `/api/export` — src/app/live.py:308・src/studio/serve.py:195・src/studio/serve.py:422 ← review.js・tools.py・value.py
- `/api/export-file` — src/editor/serve.py:253 ← cut.js・app-tools.js・tools.py
- `/api/export/cancel` — src/app/live.py:317・src/studio/serve.py:423 ← review.js・tools.py・value.py
- `/api/exports` — src/app/live.py:257 ← review.js
- `/api/flow/cancel` — src/app/server.py:630・src/friendapp/server.py:487 ← portal.js・review.js
- `/api/flow/estimate` — src/app/server.py:629 ← portal.js・ui-kit.js
- `/api/flow/history` — src/app/server.py:758・src/app/server.py:751 ← portal.js
- `/api/flow/runs` — src/app/server.py:626 ← app-list.js・portal.js・ui-kit.js
- `/api/flow/status` — src/app/server.py:754・src/app/server.py:751・src/friendapp/server.py:327 ← cases.js
- `/api/flow/submit` — src/app/server.py:629・src/friendapp/server.py:478 ← review.js・ui-kit.js
- `/api/friend/cancel` — src/friendapp/server.py:416 ← friend_preflight.py
- `/api/friend/decide` — src/friendapp/server.py:399・src/friendapp/server.py:119 ← friend_preflight.py
- `/api/friend/files` — src/friendapp/server.py:407 ← MainForm.cs
- `/api/friend/inbox` — src/friendapp/server.py:282 ← friend_preflight.py
- `/api/friend/live-settings` — src/friendapp/server.py:418
- `/api/friend/local` — src/friendapp/server.py:420・src/friendapp/server.py:119
- `/api/friend/media` — src/friendapp/server.py:313 ← receive.js
- `/api/friend/notice-seen` — src/friendapp/server.py:468 ← friend_preflight.py
- `/api/friend/open` — src/friendapp/server.py:422・src/friendapp/server.py:428
- `/api/friend/palette` — src/friendapp/server.py:405 ← palette.js
- `/api/friend/peek` — src/friendapp/server.py:298
- `/api/friend/peek-live` — src/friendapp/server.py:303
- `/api/friend/pick-file` — src/friendapp/server.py:391
- `/api/friend/pick-folder` — src/friendapp/server.py:456
- `/api/friend/player` — src/friendapp/server.py:308・src/friendapp/server.py:403
- `/api/friend/prefs` — src/friendapp/server.py:411
- `/api/friend/receive` — src/friendapp/server.py:310 ← friend_preflight.py
- `/api/friend/report` — src/friendapp/server.py:409・src/friendapp/server.py:119
- `/api/friend/retry` — src/friendapp/server.py:414・src/friendapp/server.py:119
- `/api/friend/send` — src/friendapp/server.py:388・src/friendapp/server.py:119 ← friend_preflight.py
- `/api/friend/settings` — src/friendapp/server.py:323・src/friendapp/server.py:445 ← friend_preflight.py
- `/api/friend/settings/key` — src/friendapp/server.py:451
- `/api/friend/setup` — src/friendapp/server.py:292・src/friendapp/server.py:441 ← friend_preflight.py・server.py
- `/api/friend/state` — src/friendapp/server.py:294 ← friend_preflight.py・Launcher.cs
- `/api/friend/streams` — src/friendapp/server.py:325 ← friend_preflight.py・send-list.js
- `/api/friend/streams/refresh` — src/friendapp/server.py:443 ← send-list.js
- `/api/friend/tidy` — src/friendapp/server.py:287・src/friendapp/server.py:433 ← server.py
- `/api/friend/undo` — src/friendapp/server.py:401・src/friendapp/server.py:119 ← friend_preflight.py
- `/api/friend/update` — src/friendapp/server.py:289 ← friend_preflight.py
- `/api/friend/update/apply` — src/friendapp/server.py:435 ← friend_preflight.py
- `/api/friend/upload` — src/friendapp/server.py:342 ← send-form.js
- `/api/health` — src/app/server.py:735 ← portal.js
- `/api/history` — src/editor/serve.py:210 ← app-rows.js
- `/api/info` — dev/ui_audit.py:99・src/app/live.py:269 ← new.js・ui-kit.js
- `/api/intake` — src/app/server.py:623 ← portal.js・rank.js・review.js
- `/api/intake/scan` — src/app/server.py:631 ← portal.js
- `/api/job` — src/cut2resolve/serve.py:332・src/cut2resolve/serve.py:95 ← cut.js
- `/api/job/cancel` — src/cut2resolve/serve.py:347 ← pack-tab.js・tools.py
- `/api/jobs` — src/editor/serve.py:203・src/editor/serve.py:152 ← autorun.py・server.py・app-jobs.js・app.js・pack-tab.js ほか 1
- `/api/jobs/retry` — src/editor/serve.py:271 ← app-jobs.js
- `/api/learned` — src/editor/serve.py:205 ← portal-edit.js
- `/api/live/adopt` — src/studio/serve.py:418 ← live_adopt.py
- `/api/live/exported` — src/studio/serve.py:419 ← review.js・live_export.py
- `/api/log` — src/app/server.py:739 ← portal.js
- `/api/mach-changes` — src/editor/serve.py:219 ← machpick.js
- `/api/mach-changes/pick` — src/editor/serve.py:267 ← machpick.js
- `/api/metrics` — src/editor/serve.py:207 ← portal-edit.js
- `/api/open-folder` — src/cut2resolve/serve.py:347 ← pack-tab.js
- `/api/outdir` — src/studio/serve.py:432 ← settings.js
- `/api/peaks` — src/app/live.py:250・src/app/live.py:315・src/editor/serve.py:431 ← cut.js・review.js
- `/api/pick` — src/editor/serve.py:261 ← app-tools.js
- `/api/ping` — src/app/server.py:723・src/cut2resolve/serve.py:330・src/cut2resolve/serve.py:95 ← server.py・cut.js・app.js・portal.js・livesession.py ほか 2
- `/api/plan` — src/cut2resolve/serve.py:347 ← cut.js
- `/api/queue` — src/friendapp/live_session.py:95・src/studio/serve.py:190 ← autorun.py・queue.js・rank.js・live_archive.py・tools.py
- `/api/queue/add` — src/friendapp/live_session.py:92・src/studio/serve.py:412 ← cand.js・queue.js・live_archive.py・tools.py
- `/api/queue/cancel` — src/studio/serve.py:413 ← queue.js・tools.py
- `/api/queue/clear` — src/studio/serve.py:416 ← queue.js
- `/api/queue/retry` — src/studio/serve.py:415 ← queue.js
- `/api/queue/skipchat` — src/studio/serve.py:414 ← queue.js
- `/api/rank/import-official` — src/studio/serve.py:409 ← rank.js
- `/api/rank/live` — src/studio/serve.py:189 ← rank.js
- `/api/rank/registry` — src/studio/serve.py:187・src/studio/serve.py:434 ← rank.js
- `/api/rank/resolve` — src/studio/serve.py:408 ← rank.js
- `/api/rank/search` — src/studio/serve.py:188・src/studio/serve.py:410 ← rank.js
- `/api/rank/search/cancel` — src/studio/serve.py:411 ← rank.js
- `/api/relink` — src/editor/serve.py:255 ← app.js
- `/api/relink/check` — src/editor/serve.py:254 ← app-tools.js
- `/api/rerun` — src/editor/serve.py:248 ← app-jobs.js・app.js
- `/api/resolve-package` — src/editor/serve.py:468 ← pack-tab.js
- `/api/restore` — src/editor/serve.py:251 ← app.js
- `/api/retime` — src/editor/serve.py:262 ← app-rows.js
- `/api/roster` — src/editor/serve.py:199 ← app-learn.js
- `/api/settings` — src/editor/serve.py:429・src/editor/serve.py:513・src/studio/serve.py:186 ← cand.js・cut.js・app-core.js・pack-tab.js・portal-edit.js ほか 7
- `/api/settings/patch` — src/editor/serve.py:250 ← cut.js・app-core.js・settings.js・ui-kit.js
- `/api/shutdown` — src/app/server.py:634・src/friendapp/server.py:474 ← friend_preflight.py・Launcher.cs・portal.js・host.js
- `/api/siblings` — src/cut2resolve/serve.py:331・src/cut2resolve/serve.py:95・src/editor/serve.py:198 ← app-core.js
- `/api/speakers/sub` — src/editor/serve.py:246 ← autorun.py
- `/api/state` — src/studio/serve.py:185 ← studio-shim.js・settings.js・app.js
- `/api/status` — src/app/server.py:725 ← cases.js・edhost.js・check.js・portal.js・settings.js
- `/api/suggest` — src/editor/serve.py:206 ← app-learn.js
- `/api/suggest/feedback` — src/editor/serve.py:252 ← app-learn.js
- `/api/thumb-ideas` — src/editor/serve.py:216・src/editor/serve.py:249 ← pack-tab.js
- `/api/thumb-ideas/image` — src/editor/serve.py:435 ← pack-tab.js
- `/api/title` — src/studio/serve.py:194 ← review.js
- `/api/tools` — src/editor/serve.py:200 ← app-jobs.js・app.js
- `/api/transcribe` — src/editor/serve.py:243 ← app-jobs.js・tools.py
- `/api/transcribe/cancel` — src/editor/serve.py:270 ← tools.py
- `/api/transcript` — src/editor/serve.py:211・src/editor/serve.py:521・src/editor/serve.py:539 ← cut.js・app-rows.js
- `/api/transcripts` — src/editor/serve.py:204・src/studio/serve.py:193 ← app-list.js・review.js・tools.py
- `/api/video` — src/studio/serve.py:192・src/studio/serve.py:435 ← review.js・value.py・cases.py
- `/api/video/delete` — src/studio/serve.py:420 ← review.js・live_cleanup.py
- `/api/video/request-marks` — src/studio/serve.py:421 ← tools.py
- `/api/videos` — src/studio/serve.py:191 ← collab.js・rank.js・review.js
- `/api/videos/open` — src/studio/serve.py:417 ← new.js・queue.js
- `/api/voices` — src/editor/serve.py:201 ← app-jobs.js
- `/api/voices/delete` — src/editor/serve.py:247 ← app.js
- `/api/voices/learn` — src/editor/serve.py:245 ← app.js
- `/api/voices/preview` — src/editor/serve.py:202 ← app.js
- `/api/window` — src/app/server.py:632 ← portal.js
- `/api/ytt` — src/app/mount.py:45 ← ui_audit.py・ui-kit.js
- `/api/ytt/client-log` — src/friendapp/server.py:493
- `/api/ytt/streamer-colors` — src/friendapp/server.py:491 ← cut.js・app-rows.js・send-form.js
