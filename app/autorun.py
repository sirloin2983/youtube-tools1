"""まとめて実行(統合計画の段階5。2026-09-26)。入口の「案件」の画面から、配信1本ぶんの作業を順に自動で流す。

形は3つ(ユーザー決定「選べるようにする」):
  full        解析から全部   … (未解析なら)解析 → 自動マークの上位を採用 → 書き出し → 文字起こし → Resolve パック
  adopted     採用後を全部   … 採用したマークの書き出し → 文字起こし → Resolve パック(切り抜きの良し悪しは人が決める)
  transcribe  文字起こしまで … 採用したマークの書き出し → 文字起こし(パックは校正してから人が作る)

作り:
- 各ツールの**公開している API を HTTP で呼ぶ**(入口と同じ 127.0.0.1。取り込んだツールは入口のポートの /studio/ など、子プロセスのツールはそのポート)。
  ツールの中の関数を直接呼ばないのは、画面から使うときと同じ検査・同じジョブ管理(重い処理の順番待ち ytt_core.jobs を含む)を通すため。
- どの段も「まだ無いものだけ」作る(書き出し済み・文字起こし済み・パック済みは飛ばす)。途中で止めても、もう一度押せば続きから進む。
  文字起こしの有無は ytt_core.txindex(案件の画面・スタジオのセリフと同じ規則)、パックの有無は cases.find_pack で見る。
- 1本ずつ順に処理する(キュー)。同じ配信を2つ同時には入れない。入口を終えると、実行中・順番待ちの分は消える(もう一度押せば続きから)。
- 自動で採用したマークは、人の判定ではないので学習の記録(スタジオの feedback)に入れない(スタジオの /api/video/adopt-top)。
- 解析の設定は既定値(解析の画面の設定はブラウザの中にしか無いため)。書き出しはスタジオの ③ の設定(画質・音量のそろえ方)、
  文字起こしは「編集」(文字起こし)の設定(モデルなど)を使う。パックは、「編集」でカットを決めてあればそのとおり(cut2resolve の spec.keeps。
  作った記録も「編集」に残す = 作り直しの知らせ)、無ければ文字起こしの行だけを残す規則(preset transcript-rows)。どちらも Text+(字幕の元の行が無ければ Text+ なし)。
"""
import http.client
import json
import os
import urllib.parse
import threading
import time
import uuid

from ytt_core import txindex

MODES = {"full": "解析から全部", "adopted": "採用後を全部", "transcribe": "文字起こしまで"}
STEP_LABELS = {"analyze": "解析", "adopt": "採用(自動)", "export": "書き出し", "transcribe": "文字起こし", "pack": "Resolve パック"}
MODE_STEPS = {"full": ("analyze", "adopt", "export", "transcribe", "pack"), "adopted": ("export", "transcribe", "pack"),
              "transcribe": ("export", "transcribe")}
DEFAULT_TOP = 3
MAX_KEEP = 30          # 終わった記録を残す数
MAX_WAITING = 20       # 順番待ちの上限
BUSY_WAIT = 5.0        # スタジオの書き出しが別の書き出しで塞がっているときの待ち間隔
TX_KEYS = ("model", "language", "quality", "device", "vadMode", "boost", "autoDict", "wordSplit", "stripPunct", "autoGloss", "autoLearned", "glossary")


class Cancelled(Exception):
    pass


class StepError(Exception):
    pass


class ToolClient:
    """ツールの API を呼ぶ。endpoint(ツールID) -> (ポート, 場所 "/studio/" など) か None(動いていない)"""

    def __init__(self, endpoint, token="", timeout=60):
        self.endpoint, self.token, self.timeout = endpoint, token, timeout

    def call(self, tool, method, path, body=None):
        """-> (HTTP の状態, JSON)。つながらない・動いていないときは StepError"""
        ep = self.endpoint(tool)
        if not ep:
            raise StepError("%s が動いていません(入口の画面で状態を確かめてください)" % {"studio": "切り抜きスタジオ", "transcribe": "編集",
                                                                                     "cut2resolve": "cut2resolve"}.get(tool, tool))
        port, base = ep
        url = base.rstrip("/") + path
        headers = {"Host": "127.0.0.1:%d" % port}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if method != "GET" and self.token:
            headers["X-YTT-Token"] = self.token
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=self.timeout)
        try:
            conn.request(method, url, body=data, headers=headers)
            r = conn.getresponse()
            raw = r.read()
        except OSError as e:
            raise StepError("ツールにつながりませんでした(%s)" % (e.strerror or e.__class__.__name__))
        finally:
            conn.close()
        try:
            obj = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            obj = {}
        return r.status, obj if isinstance(obj, dict) else {}

    def ok(self, tool, method, path, body=None):
        st, obj = self.call(tool, method, path, body)
        if st != 200:
            raise StepError(obj.get("message") or "エラー(HTTP %d)" % st)
        return obj


class Run:
    def __init__(self, video_id, title, mode, top):
        self.id = uuid.uuid4().hex[:10]
        self.video_id, self.title, self.mode, self.top = video_id, title, mode, top
        self.state = "queued"
        self.message = "順番待ち"
        self.error = ""
        self.created = time.time()
        self.finished = None
        self.cancel = False
        self.steps = [{"key": k, "label": STEP_LABELS[k], "state": "wait", "detail": ""} for k in MODE_STEPS[mode]]

    def step(self, key):
        return next(s for s in self.steps if s["key"] == key)

    def public(self):
        return {"id": self.id, "videoId": self.video_id, "title": self.title, "mode": self.mode, "modeLabel": MODES[self.mode], "top": self.top,
                "state": self.state, "message": self.message, "error": self.error, "created": int(self.created * 1000),
                "finished": int(self.finished * 1000) if self.finished else None, "steps": [dict(s) for s in self.steps]}


class AutoRunner:
    def __init__(self, client, repo_root, env=None, poll=1.0, sleep=None, find_pack=None):
        self.client, self.root, self.env, self.poll = client, repo_root, env, poll
        self.sleep = sleep or time.sleep
        if find_pack is None:
            import cases   # app/cases.py(パックの有無の見方を案件の画面とそろえる)
            find_pack = cases.find_pack
        self.find_pack = find_pack
        self.lock = threading.Lock()
        self.cv = threading.Condition(self.lock)
        self.runs = []
        self.thread = None
        self.closed = False

    # ------------------------------------------------------------ 受付
    def start(self, video_id, mode, top=None):
        if not isinstance(video_id, str) or not (1 <= len(video_id) <= 64) or not all(c.isalnum() or c in "-_" for c in video_id):
            raise ValueError("配信の指定が正しくありません")
        if mode not in MODES:
            raise ValueError("実行の形が正しくありません")
        if top in (None, ""):
            top = DEFAULT_TOP
        if not isinstance(top, int) or isinstance(top, bool) or not (1 <= top <= 30):
            raise ValueError("採用する数は1〜30です")
        with self.cv:
            active = [r for r in self.runs if r.state in ("queued", "running")]
            if any(r.video_id == video_id for r in active):
                raise ValueError("この配信はすでに実行中・順番待ちです")
            if len(active) >= MAX_WAITING:
                raise ValueError("順番待ちが多すぎます(%d本まで)" % MAX_WAITING)
            run = Run(video_id, "", mode, top)
            self.runs.append(run)
            self._trim()
            self.cv.notify_all()
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._loop, name="autorun", daemon=True)
                self.thread.start()
            return run.public()

    def cancel(self, run_id):
        with self.cv:
            run = next((r for r in self.runs if r.id == run_id), None)
            if run is None:
                raise ValueError("その実行はありません")
            if run.state == "queued":
                run.state, run.message, run.finished = "cancelled", "中止しました", time.time()
            elif run.state == "running":
                run.cancel = True
                run.message = "中止しています…"
            return run.public()

    def snapshot(self):
        with self.cv:
            return {"runs": [r.public() for r in reversed(self.runs)], "modes": MODES}

    def close(self):
        """入口の終了: 順番待ちを消し、実行中の分に中止を伝える(ツールの側のジョブもこの後の終了処理で止まる)"""
        with self.cv:
            self.closed = True
            for r in self.runs:
                if r.state == "queued":
                    r.state, r.message = "cancelled", "入口を終了しました"
                elif r.state == "running":
                    r.cancel = True
            self.cv.notify_all()

    def _trim(self):
        done = [r for r in self.runs if r.state not in ("queued", "running")]
        for r in done[:-MAX_KEEP] if len(done) > MAX_KEEP else []:
            self.runs.remove(r)

    def _loop(self):
        while True:
            with self.cv:
                while not self.closed and not any(r.state == "queued" for r in self.runs):
                    self.cv.wait(5)
                if self.closed:
                    return
                run = next(r for r in self.runs if r.state == "queued")
                run.state, run.message = "running", ""
            try:
                self._execute(run)
                run.state = "cancelled" if run.cancel else "done"
                run.message = "中止しました" if run.cancel else (run.message or "完了")
            except Cancelled:
                run.state, run.message = "cancelled", "中止しました"
            except StepError as e:
                run.state, run.error, run.message = "error", str(e), "止まりました"
            except Exception as e:   # 想定外でも、次の配信の処理は続ける
                run.state, run.error, run.message = "error", "内部エラー: %s %s" % (e.__class__.__name__, str(e)[:200]), "止まりました"
            finally:
                run.finished = time.time()
                for s in run.steps:
                    if s["state"] == "run":
                        s["state"] = "error" if run.state == "error" else "skip"
                with self.cv:
                    self._trim()

    # ------------------------------------------------------------ 実行
    def _check(self, run):
        if run.cancel or self.closed:
            raise Cancelled()

    def _wait(self, run, seconds=None):
        self._check(run)
        self.sleep(self.poll if seconds is None else seconds)
        self._check(run)

    def _video(self, run):
        v = self.client.ok("studio", "GET", "/api/video?id=" + run.video_id).get("video") or {}
        run.title = str(v.get("title") or v.get("fileName") or run.video_id)[:120]
        return v

    def _execute(self, run):
        v = self._video(run)
        for key in MODE_STEPS[run.mode]:
            self._check(run)
            st = run.step(key)
            st["state"] = "run"
            run.message = st["label"]
            result = getattr(self, "_step_" + key)(run, st, v)
            if st["state"] == "run":
                st["state"] = "done"
            v = self._video(run)
            if result == "stop":   # 続けても意味がない(採用するマークが無いなど)
                for s in run.steps:
                    if s["state"] == "wait":
                        s["state"], s["detail"] = "skip", s["detail"] or "前の段で止めました"
                return
        run.message = "完了"

    # 解析 -------------------------------------------------------
    def _step_analyze(self, run, st, v):
        if v.get("analysis"):
            st["state"], st["detail"] = "skip", "解析済み"
            return None
        item = {"kind": v.get("kind") or "youtube", "videoId": run.video_id}
        if item["kind"] == "file":
            import cases
            path = (cases.read_studio(cases.locations(self.root, self.env)["studio"]).get(run.video_id) or {}).get("path")
            if not path:
                raise StepError("元の動画ファイルの場所が分かりません")
            item = {"kind": "file", "path": path}
        # 解析の設定はスタジオの画面で保存したもの(/api/settings の settings.analyze。段階7-1)。無ければスタジオの既定値
        saved = (self.client.ok("studio", "GET", "/api/settings").get("settings") or {}).get("analyze")
        saved = saved if isinstance(saved, dict) else {}
        res = self.client.ok("studio", "POST", "/api/queue/add", {"items": [item], "settings": saved})
        added = res.get("added") or []
        qid = added[0]["qid"] if added else None
        if not qid:
            rej = (res.get("rejected") or [{}])[0].get("reason") or ""
            if "すでにキュー" not in rej:
                raise StepError("解析を始められませんでした: %s" % (rej or "理由不明"))
        st["detail"] = "解析中(%s)" % ("スタジオで保存した解析の設定" if saved else "解析の設定は既定値。スタジオの ② で設定を変えると次から使います")
        while True:
            self._wait(run)
            items = self.client.ok("studio", "GET", "/api/queue").get("items") or []
            it = next((i for i in items if (i.get("qid") == qid if qid else i.get("videoId") == run.video_id)), None)
            if it is None:
                raise StepError("解析のキューから消えました")
            st["detail"] = "%s %d%%" % (it.get("phase") or "", round((it.get("progress") or 0) * 100))
            if it.get("status") == "done":
                st["detail"] = "解析しました(候補 %s 件)" % it.get("marks", "?")
                return None
            if it.get("status") in ("error", "cancelled", "skipped"):
                raise StepError("解析が終わりませんでした: %s" % (it.get("error") or it.get("status")))

    # 採用 -------------------------------------------------------
    def _step_adopt(self, run, st, v):
        res = self.client.ok("studio", "POST", "/api/video/adopt-top", {"id": run.video_id, "top": run.top})
        ids = res.get("adopted") or []
        marks = (res.get("video") or {}).get("marks") or []
        if ids:
            st["detail"] = "点数の高い %d 件を採用しました" % len(ids)
            return None
        if any(m.get("status") in ("adopted", "exported") for m in marks):
            st["state"], st["detail"] = "skip", "採用・書き出し済みのマークがあるので、それを使います"
            return None
        st["state"], st["detail"] = "skip", "採用できる候補がありません"
        run.message = "採用できる候補がありませんでした"
        return "stop"

    # 書き出し ---------------------------------------------------
    def _export_body(self, run, ids):
        rv = (self.client.ok("studio", "GET", "/api/settings").get("settings") or {}).get("review") or {}
        n = lambda x, lo, hi, d: x if isinstance(x, (int, float)) and not isinstance(x, bool) and lo <= x <= hi else d
        loud = rv.get("exportLoudness", -14)
        return {"id": run.video_id, "markIds": ids, "precision": "fast" if rv.get("precision") == "fast" else "accurate",
                "maxHeight": rv.get("maxHeight") if rv.get("maxHeight") in (0, 720, 1080, 1440, 2160) else 1080,
                "volume": int(n(rv.get("exportVolume"), 1, 200, 75)), "loudness": loud if loud in (-11, -14, -16, -18) else None}

    def _step_export(self, run, st, v):
        ids = [m["id"] for m in v.get("marks") or [] if m.get("status") == "adopted"]
        if not ids:
            done = sum(1 for m in v.get("marks") or [] if m.get("status") == "exported")
            st["state"], st["detail"] = "skip", ("書き出し済み %d 本(新しく採用したものはありません)" % done if done else "採用したマークがありません")
            return None if done else "stop"
        body = self._export_body(run, ids[:50])
        while True:
            status, res = self.client.call("studio", "POST", "/api/export", body)
            if status == 200:
                break
            if status == 409 and res.get("error") == "busy":
                st["detail"] = "別の書き出しが終わるのを待っています"
                self._wait(run, BUSY_WAIT)
                continue
            raise StepError("書き出しを始められませんでした: %s" % (res.get("message") or "HTTP %d" % status))
        jid = res.get("id")
        try:
            while True:
                self._wait(run)
                j = self.client.ok("studio", "GET", "/api/export?id=" + jid)
                items = j.get("items") or []
                done = sum(1 for i in items if i.get("status") == "done")
                st["detail"] = ("他のツールの重い処理を待っています" if j.get("waiting") else "%d / %d 本" % (done, len(items)))
                if j.get("state") != "running":
                    break
        except Cancelled:
            self.client.call("studio", "POST", "/api/export/cancel", {"id": jid})
            raise
        bad = [i for i in items if i.get("status") == "error"]
        st["detail"] = "%d 本を書き出しました" % done + ("(%d 本失敗)" % len(bad) if bad else "")
        if bad and not done:
            raise StepError("書き出しに失敗しました: %s" % (bad[0].get("error") or ""))
        if bad:
            st["state"] = "warn"
        return None

    # 文字起こし -------------------------------------------------
    def _clips(self, v):
        return [m for m in v.get("marks") or [] if m.get("status") == "exported" and isinstance(m.get("path"), str) and m["path"]
                and os.path.isfile(m["path"])]

    def _step_transcribe(self, run, st, v):
        clips = self._clips(v)
        if not clips:
            st["state"], st["detail"] = "skip", "書き出した切り抜きがありません"
            return "stop"
        docs = txindex.load(txindex.folder(self.root, self.env))
        todo = [m for m in clips if not txindex.pick(docs, run.video_id, m.get("id"), m["path"])[0]]
        if not todo:
            st["state"], st["detail"] = "skip", "%d 本とも文字起こし済み" % len(clips)
            return None
        opts = self.client.ok("transcribe", "GET", "/api/settings")
        opts = {k: opts[k] for k in TX_KEYS if k in opts and isinstance(opts[k], (str, bool, int, float))}
        jobs = []
        try:
            for m in todo:
                self._check(run)
                res = self.client.ok("transcribe", "POST", "/api/transcribe", dict(opts, sourcePath=m["path"]))
                jobs.append(res.get("id"))
            while True:
                self._wait(run)
                all_jobs = {j.get("id"): j for j in self.client.ok("transcribe", "GET", "/api/jobs").get("jobs") or []}
                mine = [all_jobs.get(j) or {"state": "error", "error": "文字起こしのジョブが見つかりません"} for j in jobs]
                fin = [j for j in mine if j.get("state") in ("done", "error", "cancelled")]
                cur = next((j for j in mine if j.get("state") not in ("done", "error", "cancelled", "queued")), None)
                st["detail"] = "%d / %d 本" % (len(fin), len(jobs)) + (" ・ %s %d%%" % (cur.get("phase") or "", round((cur.get("progress") or 0) * 100)) if cur else "")
                if len(fin) == len(jobs):
                    break
        except Cancelled:
            for j in jobs:
                self.client.call("transcribe", "POST", "/api/transcribe/cancel", {"id": j})
            raise
        ok = [j for j in mine if j.get("state") == "done"]
        bad = [j for j in mine if j.get("state") != "done"]
        st["detail"] = "%d 本を文字起こししました" % len(ok) + ("(%d 本失敗)" % len(bad) if bad else "") + "。字幕の校正は文字起こしの画面で"
        if bad and not ok:
            raise StepError("文字起こしに失敗しました: %s" % (bad[0].get("error") or bad[0].get("state")))
        if bad:
            st["state"] = "warn"
        return None

    # パック -----------------------------------------------------
    def _edit_keeps(self, doc):
        """「編集」のカット(残す区間の秒。接している区間 = 分割しただけの所は1つに)と rev。無い・読めなければ (None, 0)"""
        status, res = self.client.call("transcribe", "GET", "/api/edit?id=" + urllib.parse.quote(str(doc["id"])))
        e = res.get("edit") if status == 200 and isinstance(res, dict) else None
        clips = e.get("clips") if isinstance(e, dict) else None
        if not clips:
            return None, 0
        out = []
        for c in clips:
            a, b = float(c["in"]), float(c["out"])
            if out and a <= out[-1][1] + 1e-9:
                out[-1][1] = max(out[-1][1], b)
            else:
                out.append([a, b])
        return out, int(res.get("rev") or 0)

    def _step_pack(self, run, st, v):
        clips = self._clips(v)
        docs = txindex.load(txindex.folder(self.root, self.env))
        todo, no_tx, made = [], 0, 0
        for m in clips:
            doc = txindex.pick(docs, run.video_id, m.get("id"), m["path"])[0]
            if not doc:
                no_tx += 1
            elif not self.find_pack(m["path"]):
                todo.append((m, doc))
        if not todo:
            st["state"], st["detail"] = "skip", ("パック済み" if clips and not no_tx else "文字起こしのある切り抜きがありません")
            return None
        skipped, by_edit = [], 0
        # 行から作るときの端の広げ方は「編集」の「行から」の設定(文字起こしの /api/settings の rowEdge。形は cut2resolve が確かめる)。
        # Text+ 字幕の1段の文字数は字幕の文字数の設定(subtitle.wrapChars.vertical。まとめて実行のパックは縦 = cut2resolve の既定の置き先)
        tx_settings = self.client.ok("transcribe", "GET", "/api/settings")
        row_edge = tx_settings.get("rowEdge")
        sub = tx_settings.get("subtitle") if isinstance(tx_settings.get("subtitle"), dict) else {}
        wrap = (sub.get("wrapChars") or {}).get("vertical") if isinstance(sub.get("wrapChars"), dict) else None
        wrap_out = {"textplusWrap": wrap} if isinstance(wrap, int) and not isinstance(wrap, bool) and 0 <= wrap <= 40 else {}
        for i, (m, doc) in enumerate(todo, 1):
            self._check(run)
            st["detail"] = "%d / %d 本" % (i - 1, len(todo))
            keeps, rev = self._edit_keeps(doc)
            if keeps:   # 「編集」でカットを決めてある: そのとおりに(3 パック のタブのパックと同じ中身)
                captions = any(s.get("text", "").strip() and not s.get("cut") for s in doc.get("segments") or [])
                tr = self.client.ok("transcribe", "POST", "/api/export-file", {"id": doc["id"], "format": "transcript-v1"}) if captions else {}
                spec = dict({"video": m["path"], "keeps": keeps}, **({"transcript": tr.get("path")} if captions else {}))
                body = {"spec": spec, "output": dict({"textplus": captions, "copyVideo": True}, **wrap_out)}
            else:
                tr = self.client.ok("transcribe", "POST", "/api/export-file", {"id": doc["id"], "format": "transcript-v1"})
                spec = {"video": m["path"], "transcript": tr.get("path"), "preset": "transcript-rows"}
                if isinstance(row_edge, (bool, dict)):
                    spec["rowEdge"] = row_edge
                body = {"spec": spec, "output": dict({"textplus": True}, **wrap_out)}
            while True:
                status, res = self.client.call("cut2resolve", "POST", "/api/build", body)
                if not (status == 409 and res.get("error") == "busy"):
                    break
                st["detail"] = "cut2resolve の別の処理が終わるのを待っています"
                self._wait(run, BUSY_WAIT)
            if status == 409 and res.get("error") == "exists":
                skipped.append(os.path.basename(m["path"]))   # 同じ名前のパックがある: 上書きしない(人が作り直したものかもしれない)
                continue
            if status != 200:
                raise StepError("パックを作れませんでした: %s" % (res.get("message") or "HTTP %d" % status))
            jid = (res.get("job") or {}).get("id")
            try:
                while True:
                    self._wait(run)
                    j = self.client.ok("cut2resolve", "GET", "/api/job?id=" + jid)
                    if j.get("state") != "running":
                        break
                    if j.get("message"):
                        st["detail"] = "%d / %d 本 ・ %s" % (i - 1, len(todo), j["message"])
            except Cancelled:
                self.client.call("cut2resolve", "POST", "/api/job/cancel", {"id": jid})
                raise
            if j.get("state") != "done":
                err = j.get("error")
                raise StepError("パックを作れませんでした: %s" % ((err.get("message") if isinstance(err, dict) else err) or j.get("state")))
            made += 1
            if keeps:   # 作った記録(packRev)を「編集」に残す(カット・字幕を直したら「作り直し」と知らせるため)。残せなくてもパックはできている
                r = j.get("result") or {}
                by_edit += 1
                self.client.call("transcribe", "POST", "/api/edit/pack", {"id": doc["id"], "rev": rev, "docUpdatedAt": int(doc.get("updatedAt") or 0),
                                                                          "dir": r.get("outDir") or "", "files": [f.get("name") for f in r.get("files") or [] if isinstance(f, dict)]})
        st["detail"] = "%d 本のパックを作りました" % made + ("(うち %d 本は「編集」のカットのとおり)" % by_edit if by_edit else "") + \
            "。字幕を校正したら「編集」のパックのタブで作り直してください"
        if skipped:
            st["detail"] += "。同じ名前のパックがあるので上書きしなかったもの: %s" % "・".join(skipped[:5])
        return None
