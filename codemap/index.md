# コードの地図(目次)

自動で作った物(`python dev/code_map.py`。古いと `python dev/lint.py` の code-map が言う)。手で直さない。
探し方: 画面の言葉なら [words.md](words.md)、`/api/...` の口なら下の表、役目なら層ごとの md を見る。行の番号は作った時点の物。

| 層 | md | ファイル | 行 |
|---|---|---|---|
| ytt(基盤) | [ytt.md](ytt.md) | 53 | 11685 |
| ① pipeline(道具 = データを加工する) | [pipeline.md](pipeline.md) | 80 | 27354 |
| ② flow(管理 = いつ・どの順で・どこに置くか) | [flow.md](flow.md) | 94 | 30647 |
| ③ human(人の操作) | [human.md](human.md) | 62 | 17536 |
| ④ manage(データ) | [manage.md](manage.md) | 43 | 11115 |
| ⑤ eval(検証) | [eval.md](eval.md) | 37 | 15562 |
| src/app(入口と画面) | [app.md](app.md) | 87 | 32297 |
| src/friendapp(友人の玄関) | [friendapp.md](friendapp.md) | 48 | 19062 |
| その他の画面(editor・studio・ui-kit・cut2resolve) | [tools.md](tools.md) | 19 | 10261 |
| dev・setup(開発の道具) | [dev.md](dev.md) | 61 | 16618 |
| friend-apps・chrome-ext(C# のアプリ・拡張) | [apps.md](apps.md) | 19 | 9060 |

## `/api/...` の口(受ける所 → 呼ぶ所)

受ける所は .py の処理(比べる・表の鍵)。呼ぶ所は画面の .js・.cs・ほかの .py(テストは除く)。

- `/api` — dev/code_map.py:208・dev/spec_check.py:103・src/app/live.py:292
- `/api/accuracy` — src/app/server.py:625 ← portal.js
- `/api/accuracy/run` — src/app/server.py:632 ← portal.js
- `/api/archive` — src/app/live.py:323・src/app/live.py:320 ← review.js
- `/api/archive/cancel` — src/app/live.py:320 ← review.js
- `/api/backup` — src/app/server.py:624 ← portal.js
- `/api/backup/run` — src/app/server.py:631 ← portal.js
- `/api/begin` — src/app/live.py:306 ← new.js
- `/api/build` — src/cut2resolve/serve.py:347 ← pack-tab.js・tools.py
- `/api/cases` — src/app/server.py:765 ← cases.js・portal.js
- `/api/cases/auto` — src/app/server.py:628 ← portal.js
- `/api/check/answer` — src/app/server.py:633 ← check.js
- `/api/check/flush` — src/app/server.py:633 ← check.js
- `/api/check/next` — src/app/server.py:759 ← cases.js・check.js・portal.js
- `/api/check/skip` — src/app/server.py:633 ← check.js
- `/api/collab/anchor` — src/studio/serve.py:428 ← collab.js
- `/api/collab/group` — src/studio/serve.py:197・src/studio/serve.py:424 ← collab.js・queue.js
- `/api/collab/group/add` — src/studio/serve.py:425 ← collab.js
- `/api/collab/group/delete` — src/studio/serve.py:427 ← collab.js
- `/api/collab/group/remove` — src/studio/serve.py:426 ← collab.js
- `/api/collab/groups` — src/studio/serve.py:196 ← collab.js
- `/api/config` — src/studio/serve.py:431 ← new.js・settings.js・app.js
- `/api/diarize` — src/editor/serve.py:228 ← app-jobs.js・tools.py
- `/api/doc-diarnum` — src/editor/serve.py:249 ← app-jobs.js
- `/api/doc-for` — src/editor/serve.py:206・src/editor/serve.py:147 ← cases.js
- `/api/drill/candidates` — src/editor/serve.py:198 ← app-jobs.js
- `/api/drill/reviewed` — src/editor/serve.py:251 ← app-learn.js
- `/api/drill/status` — src/app/server.py:148・src/editor/serve.py:197・src/editor/serve.py:147
- `/api/drill/unreviewed` — src/editor/serve.py:252 ← app-learn.js
- `/api/edit` — src/editor/serve.py:203・src/editor/serve.py:467・src/editor/serve.py:147 ← app-tools.js・app.js・cut.js・pack-tab.js
- `/api/edit/draft` — src/editor/serve.py:204 ← app.js・cut.js
- `/api/edit/pack` — src/editor/serve.py:246 ← pack-tab.js・tools.py
- `/api/edit/pack-readme` — src/editor/serve.py:205 ← pack-tab.js
- `/api/edit/preview` — src/editor/serve.py:247 ← pack-tab.js
- `/api/effort` — src/editor/serve.py:248・src/editor/serve.py:147 ← app-learn.js
- `/api/eval-batch` — src/app/server.py:148・src/editor/serve.py:202
- `/api/eval-batch/redo-one` — src/editor/serve.py:243 ← app-learn.js
- `/api/eval-batch/start` — src/editor/serve.py:241
- `/api/eval-batch/stop` — src/editor/serve.py:242
- `/api/eval-folders` — src/editor/serve.py:201 ← app-tools.js
- `/api/eval-folders/organize` — src/editor/serve.py:239 ← app.js
- `/api/eval-folders/settle` — src/editor/serve.py:240 ← app-tools.js
- `/api/export` — src/app/live.py:309・src/studio/serve.py:195・src/studio/serve.py:422 ← review.js・tools.py・value.py
- `/api/export-file` — src/editor/serve.py:236 ← cut.js・app-tools.js・tools.py
- `/api/export/cancel` — src/app/live.py:318・src/studio/serve.py:423 ← review.js・tools.py・value.py
- `/api/exports` — src/app/live.py:258 ← review.js
- `/api/flow/cancel` — src/app/server.py:630・src/friendapp/server.py:481 ← portal.js・review.js
- `/api/flow/estimate` — src/app/server.py:629 ← portal.js・ui-kit.js
- `/api/flow/history` — src/app/server.py:756・src/app/server.py:749 ← portal.js
- `/api/flow/runs` — src/app/server.py:626 ← app-list.js・portal.js・ui-kit.js
- `/api/flow/status` — src/app/server.py:752・src/app/server.py:749・src/friendapp/server.py:323 ← cases.js
- `/api/flow/submit` — src/app/server.py:629・src/friendapp/server.py:472 ← review.js・ui-kit.js
- `/api/friend/cancel` — src/friendapp/server.py:410 ← friend_preflight.py
- `/api/friend/decide` — src/friendapp/server.py:395・src/friendapp/server.py:116 ← friend_preflight.py
- `/api/friend/files` — src/friendapp/server.py:401 ← MainForm.cs
- `/api/friend/inbox` — src/friendapp/server.py:277 ← friend_preflight.py
- `/api/friend/live-settings` — src/friendapp/server.py:412
- `/api/friend/local` — src/friendapp/server.py:414・src/friendapp/server.py:116
- `/api/friend/media` — src/friendapp/server.py:308 ← receive.js
- `/api/friend/notice-seen` — src/friendapp/server.py:462 ← friend_preflight.py
- `/api/friend/open` — src/friendapp/server.py:416・src/friendapp/server.py:422
- `/api/friend/peek` — src/friendapp/server.py:293
- `/api/friend/peek-live` — src/friendapp/server.py:298
- `/api/friend/pick-file` — src/friendapp/server.py:387
- `/api/friend/pick-folder` — src/friendapp/server.py:450
- `/api/friend/player` — src/friendapp/server.py:303・src/friendapp/server.py:399
- `/api/friend/prefs` — src/friendapp/server.py:405
- `/api/friend/receive` — src/friendapp/server.py:305 ← friend_preflight.py
- `/api/friend/report` — src/friendapp/server.py:403・src/friendapp/server.py:116
- `/api/friend/retry` — src/friendapp/server.py:408・src/friendapp/server.py:116
- `/api/friend/send` — src/friendapp/server.py:384・src/friendapp/server.py:116 ← friend_preflight.py
- `/api/friend/settings` — src/friendapp/server.py:319・src/friendapp/server.py:439 ← friend_preflight.py
- `/api/friend/settings/key` — src/friendapp/server.py:445
- `/api/friend/setup` — src/friendapp/server.py:287・src/friendapp/server.py:435 ← friend_preflight.py・server.py
- `/api/friend/state` — src/friendapp/server.py:289 ← friend_preflight.py・Launcher.cs
- `/api/friend/streams` — src/friendapp/server.py:321 ← friend_preflight.py・send-list.js
- `/api/friend/streams/refresh` — src/friendapp/server.py:437 ← send-list.js
- `/api/friend/tidy` — src/friendapp/server.py:282・src/friendapp/server.py:427 ← server.py
- `/api/friend/undo` — src/friendapp/server.py:397・src/friendapp/server.py:116 ← friend_preflight.py
- `/api/friend/update` — src/friendapp/server.py:284 ← friend_preflight.py
- `/api/friend/update/apply` — src/friendapp/server.py:429 ← friend_preflight.py
- `/api/friend/upload` — src/friendapp/server.py:338 ← send-form.js
- `/api/health` — src/app/server.py:735 ← portal.js
- `/api/history` — src/editor/serve.py:199 ← app-rows.js
- `/api/info` — dev/ui_audit.py:99・src/app/live.py:270 ← new.js・ui-kit.js
- `/api/intake` — src/app/server.py:623 ← portal.js・rank.js・review.js
- `/api/intake/scan` — src/app/server.py:631 ← portal.js
- `/api/job` — src/cut2resolve/serve.py:332・src/cut2resolve/serve.py:95 ← cut.js
- `/api/job/cancel` — src/cut2resolve/serve.py:347 ← pack-tab.js・tools.py
- `/api/jobs` — src/editor/serve.py:193・src/editor/serve.py:147 ← autorun.py・server.py・app-jobs.js・app.js・tools.py
- `/api/jobs/retry` — src/editor/serve.py:254 ← app-jobs.js
- `/api/live/adopt` — src/studio/serve.py:418 ← live_adopt.py
- `/api/live/exported` — src/studio/serve.py:419 ← review.js・live_export.py
- `/api/log` — src/app/server.py:737 ← portal.js
- `/api/mach-changes` — src/editor/serve.py:207 ← machpick.js
- `/api/mach-changes/pick` — src/editor/serve.py:250 ← machpick.js
- `/api/metrics` — src/editor/serve.py:196 ← portal-edit.js
- `/api/open-folder` — src/cut2resolve/serve.py:347 ← pack-tab.js
- `/api/outdir` — src/studio/serve.py:432 ← settings.js
- `/api/peaks` — src/app/live.py:251・src/app/live.py:316・src/editor/serve.py:408 ← cut.js・review.js
- `/api/pick` — src/editor/serve.py:244 ← app-tools.js
- `/api/ping` — src/app/server.py:723・src/app/server.py:148・src/cut2resolve/serve.py:330 ← server.py・cut.js・app.js・portal.js・livesession.py ほか 2
- `/api/plan` — src/cut2resolve/serve.py:347 ← cut.js
- `/api/queue` — src/friendapp/live_session.py:94・src/studio/serve.py:190 ← autorun.py・queue.js・rank.js・live_archive.py・tools.py
- `/api/queue/add` — src/friendapp/live_session.py:91・src/studio/serve.py:412 ← cand.js・queue.js・live_archive.py・tools.py
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
- `/api/relink` — src/editor/serve.py:238 ← app.js・tools.py
- `/api/relink/check` — src/editor/serve.py:237 ← app-tools.js
- `/api/rerun` — src/editor/serve.py:232 ← app-jobs.js・app.js
- `/api/restore` — src/editor/serve.py:234 ← app.js
- `/api/retime` — src/editor/serve.py:245 ← app-rows.js
- `/api/roster` — src/editor/serve.py:189 ← app-learn.js
- `/api/settings` — src/editor/serve.py:406・src/editor/serve.py:455・src/studio/serve.py:186 ← cand.js・cut.js・app-core.js・settings.js・queue.js ほか 4
- `/api/settings/patch` — src/editor/serve.py:233 ← cut.js・app-core.js・settings.js
- `/api/shutdown` — src/app/server.py:634・src/friendapp/server.py:468 ← friend_preflight.py・Launcher.cs・portal.js・host.js
- `/api/siblings` — src/cut2resolve/serve.py:331・src/cut2resolve/serve.py:95・src/editor/serve.py:188 ← app-core.js
- `/api/speakers/sub` — src/editor/serve.py:230 ← autorun.py
- `/api/state` — src/studio/serve.py:185 ← studio-shim.js・settings.js・app.js
- `/api/status` — src/app/server.py:725 ← cases.js・edhost.js・check.js・portal.js・settings.js
- `/api/suggest` — src/editor/serve.py:195 ← app-learn.js
- `/api/suggest/feedback` — src/editor/serve.py:235 ← app-learn.js
- `/api/title` — src/studio/serve.py:194 ← review.js
- `/api/tools` — src/editor/serve.py:190 ← app-jobs.js・app.js
- `/api/transcribe` — src/editor/serve.py:227 ← app-jobs.js・tools.py
- `/api/transcribe/cancel` — src/editor/serve.py:253 ← tools.py
- `/api/transcript` — src/editor/serve.py:200・src/editor/serve.py:463・src/editor/serve.py:481 ← cut.js・app-rows.js
- `/api/transcripts` — src/editor/serve.py:194・src/studio/serve.py:193 ← app-list.js・review.js・tools.py
- `/api/video` — src/studio/serve.py:192・src/studio/serve.py:435 ← review.js・value.py・cases.py
- `/api/video/delete` — src/studio/serve.py:420 ← review.js・live_cleanup.py
- `/api/video/request-marks` — src/studio/serve.py:421 ← tools.py
- `/api/videos` — src/studio/serve.py:191 ← collab.js・rank.js・review.js
- `/api/videos/open` — src/studio/serve.py:417 ← new.js・queue.js
- `/api/voices` — src/editor/serve.py:191 ← app-jobs.js
- `/api/voices/delete` — src/editor/serve.py:231 ← app.js
- `/api/voices/learn` — src/editor/serve.py:229 ← app.js
- `/api/voices/preview` — src/editor/serve.py:192 ← app.js
- `/api/ytt` — src/app/mount.py:45 ← ui_audit.py・ui-kit.js
- `/api/ytt/client-log` — src/friendapp/server.py:487
- `/api/ytt/streamer-colors` — src/friendapp/server.py:485 ← cut.js・app-rows.js・send-form.js
