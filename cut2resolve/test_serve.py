#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""画面のサーバー(serve.py)の API のテスト。実サーバーを空きポートで別スレッドに起動する。
python -m unittest test_cut2resolve で一緒に走る。単独なら python -m unittest test_serve"""
import http.client
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import serve  # noqa: E402
from test_cut2resolve import HAVE_FFMPEG, make_video, parse_edl  # noqa: E402


class Client:
    def __init__(self, port):
        self.port = port
        self.host = "127.0.0.1:%d" % port

    def req(self, method, path, body=None, headers=None, raw=None, ctype="application/json"):
        h = {"Host": self.host}
        data = None
        if raw is not None:
            data = raw
            h["Content-Type"] = ctype
        elif body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            h["Content-Type"] = ctype
        h.update(headers or {})
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        try:
            conn.request(method, path, body=data, headers=h)
            r = conn.getresponse()
            payload = r.read()
            return r.status, dict(r.getheaders()), payload
        finally:
            conn.close()

    def json(self, method, path, body=None, headers=None):
        st, hd, payload = self.req(method, path, body, headers)
        try:
            return st, json.loads(payload.decode("utf-8"))
        except ValueError:
            return st, payload

    def wait(self, job, timeout=120):
        t0 = time.time()
        while time.time() - t0 < timeout:
            st, j = self.json("GET", "/api/job?id=" + job["id"])
            if j["state"] != "running":
                return j
            time.sleep(0.05)
        raise AssertionError("ジョブが終わりません")


class ServerBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.opened = []
        cls.srv, cls.port = serve.make_server(0, opener=cls.opened.append)
        cls.th = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.th.start()
        cls.c = Client(cls.port)
        cls.upload_patch = mock.patch.object(serve, "UPLOAD_DIR", str(cls.dir / "uploads"))
        cls.upload_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.upload_patch.stop()
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()


class TestGuards(ServerBase):
    def test_ping_and_state(self):
        st, j = self.c.json("GET", "/api/ping")
        self.assertEqual((st, j), (200, {"app": "cut2resolve", "version": serve.SERVER_VERSION}))
        st, j = self.c.json("GET", "/api/state")
        self.assertEqual(st, 200)
        self.assertIn("defaults", j)
        self.assertEqual(j["defaults"]["handlesTranscript"], 0.0)

    def test_host_header_is_checked(self):
        st, _, body = self.c.req("GET", "/api/ping", headers={"Host": "evil.example:%d" % self.port})
        self.assertEqual(st, 403)
        self.assertIn("Host", json.loads(body)["message"])
        st, _, _ = self.c.req("GET", "/api/ping", headers={"Host": "localhost:%d" % self.port})
        self.assertEqual(st, 200)

    def test_cross_site_requests_are_rejected(self):
        for site in ("cross-site", "same-site"):
            st, _, _ = self.c.req("GET", "/api/state", headers={"Sec-Fetch-Site": site})
            self.assertEqual(st, 403, site)
        st, _, _ = self.c.req("GET", "/api/state", headers={"Sec-Fetch-Site": "same-origin"})
        self.assertEqual(st, 200)

    def test_navigation_from_other_tool_is_allowed_but_not_iframe(self):
        nav = {"Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
        st, hd, body = self.c.req("GET", "/?video=C%3A%5Cx.mp4", headers=nav)
        self.assertEqual(st, 200)
        self.assertIn("frame-ancestors 'none'", hd.get("Content-Security-Policy", ""))
        self.assertEqual(hd.get("X-Frame-Options"), "DENY")
        st, _, _ = self.c.req("GET", "/", headers=dict(nav, **{"Sec-Fetch-Dest": "iframe"}))
        self.assertEqual(st, 403)
        st, _, _ = self.c.req("GET", "/api/state", headers=nav)   # API は画面への遷移でも不可
        self.assertEqual(st, 403)
        st, _, _ = self.c.req("GET", "/app.js", headers=dict(nav, **{"Sec-Fetch-Dest": "script", "Sec-Fetch-Mode": "no-cors"}))
        self.assertEqual(st, 403)

    def test_post_origin_and_content_type(self):
        st, _, _ = self.c.req("POST", "/api/inspect", {}, headers={"Origin": "http://evil.example"})
        self.assertEqual(st, 403)
        st, _, _ = self.c.req("POST", "/api/inspect", {}, headers={"Origin": "http://http://127.0.0.1:%d" % self.port})
        self.assertEqual(st, 403)
        st, _, _ = self.c.req("POST", "/api/inspect", {}, headers={"Origin": "http://localhost:%d" % self.port})
        self.assertEqual(st, 200)
        st, _, _ = self.c.req("POST", "/api/inspect", raw=b"{}", ctype="text/plain")
        self.assertEqual(st, 415)
        st, _, _ = self.c.req("POST", "/api/inspect", raw=b'{"video": NaN}')
        self.assertEqual(st, 400)
        st, _, _ = self.c.req("POST", "/api/inspect", raw=b"[]")
        self.assertEqual(st, 400)

    def test_index_has_version_csp_and_no_inline_script(self):
        st, hd, body = self.c.req("GET", "/")
        html = body.decode("utf-8")
        self.assertEqual(st, 200)
        self.assertIn('data-app-version="%s"' % serve.SERVER_VERSION, html)
        self.assertNotIn("__APP_VERSION__", html)
        self.assertIn("script-src 'self'", hd["Content-Security-Policy"])
        import re
        for tag in re.findall(r"<script[^>]*>", html):
            self.assertIn("src=", tag)   # インラインのスクリプトは使わない(CSP)
        self.assertLess(html.index('src="ui-kit.js"'), html.index('href="ui-kit.css"'))   # ui-kit.js は CSS より先(ちらつき防止)
        self.assertIsNone(re.search(r'(?:src|href)="/', html))   # 部品は相対パス(入口に取り込まれた /cut2resolve/ の下でも読める)
        for p in ("/app.js", "/app.css", "/ui-kit.js", "/ui-kit.css"):
            self.assertEqual(self.c.req("GET", p)[0], 200, p)
        self.assertEqual(self.c.req("GET", "/serve.py")[0], 404)
        self.assertEqual(self.c.req("GET", "/../serve.py")[0], 404)


class TestPathsAndUploads(ServerBase):
    def test_clean_path(self):
        self.assertIsNone(serve.clean_path("  ", "video"))
        self.assertEqual(serve.clean_path('"/tmp/a b.mp4"', "video"), os.path.normpath("/tmp/a b.mp4"))
        self.assertEqual(serve.clean_path("file:///tmp/%E5%8B%95%E7%94%BB.mp4", "video"), os.path.normpath("/tmp/動画.mp4"))
        for bad in ("relative/a.mp4", "a.mp4", "/tmp/a\nb.mp4", 12):
            with self.assertRaises(serve.ApiError, msg=repr(bad)):
                serve.clean_path(bad, "video")

    def test_inspect_errors_per_field(self):
        srt = self.dir / "s.srt"
        srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nこんにちは\n", encoding="utf-8")
        st, j = self.c.json("POST", "/api/inspect", {"video": "clip.mp4", "srt": str(srt), "transcript": str(self.dir / "none.json"),
                                                      "plan": str(srt)})
        self.assertEqual(st, 200)
        ins = j["inputs"]
        self.assertFalse(ins["video"]["ok"])
        self.assertIn("完全なパス", ins["video"]["error"])
        self.assertTrue(ins["srt"]["ok"])
        self.assertEqual(ins["srt"]["count"], 1)
        self.assertFalse(ins["transcript"]["ok"])
        self.assertIn("見つかりません", ins["transcript"]["error"])
        self.assertFalse(ins["plan"]["ok"])   # 拡張子が違う
        self.assertIn("拡張子", ins["plan"]["error"])

    def test_inspect_transcript_suggests_video_in_same_folder(self):
        v = self.dir / "clip.mp4"
        v.write_bytes(b"x")
        t = self.dir / "clip.transcript.json"
        t.write_text(json.dumps({"schema": "youtube-tools-transcript/v1", "media": {"path": r"D:\moved\clip.mp4", "name": "clip.mp4"},
                                 "segments": [{"start": 0, "end": 1, "text": "a", "cut": False},
                                              {"start": 1, "end": 2, "text": "b", "cut": True}]}), encoding="utf-8")
        st, j = self.c.json("POST", "/api/inspect", {"transcript": str(t)})
        self.assertEqual(j["inputs"]["transcript"]["kept"], 1)
        self.assertEqual(j["inputs"]["transcript"]["cut"], 1)
        self.assertEqual(j["suggestVideo"], str(v))

    def test_upload(self):
        body = "1\n00:00:01,000 --> 00:00:02,000\nあ\n".encode("cp932")
        st, _, raw = self.c.req("POST", "/api/upload?kind=srt&name=" + "..%2F..%2F%E5%AD%97%E5%B9%95.srt", raw=body, ctype="application/octet-stream")
        self.assertEqual(st, 200, raw)
        j = json.loads(raw)
        p = Path(j["path"])
        self.assertEqual(p.name, "字幕.srt")
        self.assertTrue(str(p).startswith(serve.UPLOAD_DIR))
        self.assertEqual(p.read_bytes(), body)
        st, j = self.c.json("POST", "/api/inspect", {"srt": str(p)})
        self.assertEqual(j["inputs"]["srt"]["count"], 1)   # Shift_JIS のまま読める
        st, _, raw = self.c.req("POST", "/api/upload?kind=srt&name=con.srt", raw=b"x", ctype="application/octet-stream")
        self.assertEqual(json.loads(raw)["name"], "_con.srt")   # Windows の予約名
        st, _, _ = self.c.req("POST", "/api/upload?kind=srt&name=a.exe", raw=b"x", ctype="application/octet-stream")
        self.assertEqual(st, 400)
        st, _, _ = self.c.req("POST", "/api/upload?kind=video&name=a.mp4", raw=b"x", ctype="application/octet-stream")
        self.assertEqual(st, 400)
        st, _, _ = self.c.req("POST", "/api/upload?kind=srt&name=a.srt", raw=b"x")   # application/json では受けない
        self.assertEqual(st, 415)
        with mock.patch.dict(serve.UPLOAD_LIMITS, {"srt": (10, (".srt",))}):
            st, _, _ = self.c.req("POST", "/api/upload?kind=srt&name=a.srt", raw=b"x" * 11, ctype="application/octet-stream")
        self.assertEqual(st, 413)
        st, _, _ = self.c.req("POST", "/api/upload?kind=srt&name=a.srt", raw=b"x", ctype="application/octet-stream",
                              headers={"Origin": "http://evil.example"})
        self.assertEqual(st, 403)

    def test_upload_cleanup_keeps_recent(self):
        for i in range(5):
            serve.save_upload("srt", "a%d.srt" % i, b"x")
            time.sleep(0.01)
        serve.clean_uploads(keep=2)
        self.assertEqual(len(os.listdir(serve.UPLOAD_DIR)), 2)
        serve.clean_uploads(keep=0)
        self.assertEqual(os.listdir(serve.UPLOAD_DIR), [])

    def test_open_folder_only_for_pack_dirs(self):
        st, j = self.c.json("POST", "/api/open-folder", {"path": str(self.dir)})
        self.assertEqual(st, 403)
        st, j = self.c.json("POST", "/api/open-folder", {"path": "relative"})
        self.assertEqual(st, 400)
        self.assertEqual(self.opened, [])

    def test_media_unknown_token(self):
        for tok in ("nope-nope-nope", "..%2Fserve.py", "a"):
            self.assertEqual(self.c.req("GET", "/media/" + tok)[0], 404, tok)


class TestHeavyJobLimit(unittest.TestCase):
    """パックの作成は、他のツールの重い処理と順番を待つ(ytt_core.jobs)。試算は待たない"""

    def test_build_waits_and_can_be_cancelled(self):
        from ytt_core import jobs
        slots = jobs.HeavySlots(1)
        held = slots.acquire("transcribe")
        with mock.patch.object(serve._heavy, "SLOTS", slots):
            app = serve.AppState()
            ran = []
            job = app.start_job("build", lambda task: ran.append(1) or {"ok": True})
            for _ in range(100):
                if job.message == jobs.WAIT_MESSAGE:
                    break
                time.sleep(0.02)
            self.assertEqual((job.state, job.message, ran), ("running", jobs.WAIT_MESSAGE, []))
            plan = serve.AppState().start_job("plan", lambda task: "planned")   # 試算は待たない
            for _ in range(100):
                if plan.state != "running":
                    break
                time.sleep(0.02)
            self.assertEqual(plan.state, "done")
            job.task.cancel()
            for _ in range(200):
                if job.state != "running":
                    break
                time.sleep(0.02)
            self.assertEqual((job.state, ran), ("cancelled", []))
            slots.release(held)
            job2 = app.start_job("build", lambda task: "built")
            for _ in range(200):
                if job2.state != "running":
                    break
                time.sleep(0.02)
            self.assertEqual((job2.state, job2.result, job2.message), ("done", "built", ""))


class TestSiblings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"YTT_RUNTIME_DIR": self.tmp.name})
        self.env.start()
        self.servers = []

    def tearDown(self):
        for s in self.servers:
            s.shutdown()
            s.server_close()
        self.env.stop()
        self.tmp.cleanup()

    def fake(self, app):
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                b = json.dumps({"app": app, "version": "x"}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def log_message(self, *a):
                pass
        s = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=s.serve_forever, daemon=True).start()
        self.servers.append(s)
        return s.server_address[1]

    def put(self, tool, obj):
        Path(self.tmp.name, tool + ".json").write_text(json.dumps(obj), encoding="utf-8")

    def test_siblings_only_answers_matching_apps(self):
        self.put("studio", {"tool": "studio", "port": self.fake("clip-studio")})
        self.put("transcribe", {"tool": "transcribe", "port": self.fake("something-else")})
        t0 = time.monotonic()
        r = serve.siblings(8810)
        self.assertLess(time.monotonic() - t0, 2)
        self.assertEqual(set(r["tools"]), {"studio", "cut2resolve"})
        self.assertEqual(r["tools"]["cut2resolve"], 8810)
        self.put("transcribe", {"tool": "transcribe", "port": True})   # 真偽値は不可
        self.assertNotIn("transcribe", serve.siblings(8810)["tools"])

    def test_runtime_write_and_remove(self):
        path = serve.write_runtime(8811)
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        self.assertEqual((d["tool"], d["port"], d["version"]), ("cut2resolve", 8811, serve.SERVER_VERSION))
        self.assertFalse(serve.remove_runtime(8812))   # 別のポートの記録は消さない
        self.assertTrue(serve.remove_runtime(8811))
        self.assertFalse(os.path.exists(path))
        self.assertNotIn("path", d)   # 単独で動くときは以前と同じ形(path を書かない)

    def test_uses_ytt_core(self):
        """.runtime・siblings・Host/Origin の検査は ytt_core の1か所(2026-09-26。cut2resolve 自身の写しは消した)"""
        from ytt_core import httpsec, runtime
        self.assertIs(serve.TOOL_APPS, runtime.TOOL_APPS)
        self.assertIs(serve.httpsec, httpsec)
        for gone in ("_read_small_json", "RUNTIME_MAX_BYTES"):
            self.assertFalse(hasattr(serve, gone), gone)
        with mock.patch.object(runtime, "ping_app", return_value="clip-studio") as m:
            self.put("studio", {"tool": "studio", "port": 8800})
            self.assertEqual(serve.siblings(8810)["tools"], {"studio": 8800, "cut2resolve": 8810})
            m.assert_called()
        port = self.fake("cut2resolve")
        self.assertEqual(serve.probe(port), "x")
        self.assertIsNone(serve.probe(self.fake("clip-studio")))

    def test_mounted_path_in_runtime_and_siblings(self):
        """入口に取り込まれたとき(段階3-2): .runtime に場所を書き、siblings は自分と他のツールの場所を返す。形の違う場所は "/" として扱う"""
        d = json.loads(Path(serve.write_runtime(8700, "/cut2resolve/")).read_text(encoding="utf-8"))
        self.assertEqual(d["path"], "/cut2resolve/")
        d = json.loads(Path(serve.write_runtime(8700, "//evil.example/")).read_text(encoding="utf-8"))
        self.assertNotIn("path", d)
        self.assertEqual(serve.siblings(8700, self_path="/cut2resolve/"), {"tools": {"cut2resolve": 8700}, "paths": {"cut2resolve": "/cut2resolve/"}})
        self.assertEqual(serve.siblings(8700, self_path="/x/../"), {"tools": {"cut2resolve": 8700}})
        port = self.fake("cut2resolve")
        self.put("cut2resolve", {"tool": "cut2resolve", "port": port, "path": "/cut2resolve/"})
        self.assertEqual(serve.mounted_elsewhere(), "http://localhost:%d/cut2resolve/" % port)   # serve.py を直接起動したときはこれを開くだけ
        self.put("cut2resolve", {"tool": "cut2resolve", "port": port})
        self.assertIsNone(serve.mounted_elsewhere())   # 単独で動いているものは従来どおり(make_server の probe が扱う)
        self.put("cut2resolve", {"tool": "cut2resolve", "port": self.fake("clip-studio"), "path": "/cut2resolve/"})
        self.assertIsNone(serve.mounted_elsewhere())   # 別のアプリが答えるなら開かない


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg が無いためスキップ")
class TestJobs(ServerBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.video = cls.dir / "clip.mp4"
        make_video(cls.video, 10, audio="gaps")
        cls.srt = cls.dir / "clip.srt"
        cls.srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nあ\n\n2\n00:00:05,000 --> 00:00:06,000\nい\n", encoding="utf-8")

    def spec(self, **kw):
        s = {"video": str(self.video), "srt": str(self.srt), "mode": "silence"}
        s.update(kw)
        return s

    def run_job(self, path, body):
        st, j = self.c.json("POST", path, body)
        self.assertEqual(st, 200, j)
        return self.c.wait(j["job"])

    def test_inspect_video_and_media_ranges(self):
        st, j = self.c.json("POST", "/api/inspect", {"video": '"%s"' % self.video})
        v = j["inputs"]["video"]
        self.assertTrue(v["ok"], v)
        self.assertEqual((v["w"], v["h"], v["total"], v["fps"], v["audio"]), (640, 360, 300, [30, 1], True))
        self.assertEqual(v["startTc"], "00:00:00:00")
        url = v["mediaUrl"]
        size = self.video.stat().st_size
        st, hd, body = self.c.req("GET", url, headers={"Range": "bytes=0-99", "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Dest": "video"})
        self.assertEqual((st, len(body), hd["Content-Range"]), (206, 100, "bytes 0-99/%d" % size))
        self.assertEqual(body, self.video.read_bytes()[:100])
        st, hd, body = self.c.req("GET", url, headers={"Range": "bytes=-10"})
        self.assertEqual(body, self.video.read_bytes()[-10:])
        st, hd, _ = self.c.req("GET", url, headers={"Range": "bytes=%d-" % (size + 5)})
        self.assertEqual(st, 416)
        st, hd, body = self.c.req("GET", url)
        self.assertEqual((st, len(body), hd["Content-Type"]), (200, size, "video/mp4"))
        st, _, _ = self.c.req("GET", url, headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Dest": "video"})
        self.assertEqual(st, 403)   # 他のサイトの <video> からは読めない

    def test_plan_modes(self):
        j = self.run_job("/api/plan", {"spec": self.spec()})
        self.assertEqual(j["state"], "done", j)
        r = j["result"]
        self.assertEqual(r["count"], 3)
        self.assertIn("silence", r["drops"])
        self.assertEqual(r["subtitles"]["out"], 2)
        self.assertTrue(r["mediaUrl"].startswith("/media/"))
        self.assertEqual(r["outputs"]["existing"], [])
        self.assertFalse((self.dir / "clip_pack").exists())   # 試算はファイルを作らない
        j = self.run_job("/api/plan", {"spec": self.spec(mode="list", listKind="keep", listText="0:01 0:03\n5 8\n")})
        self.assertEqual(j["result"]["keeps"], [[30, 90], [150, 240]])
        j = self.run_job("/api/plan", {"spec": self.spec(mode="list", listKind="drop", listText="0 1\n")})
        self.assertEqual(j["result"]["keeps"], [[30, 300]])
        j = self.run_job("/api/plan", {"spec": self.spec(mode="list", listKind="drop", listText="", silenceExtra=True)})
        self.assertEqual(j["result"]["count"], 3)
        st, j = self.c.json("POST", "/api/plan", {"spec": self.spec(mode="list", listText="0:05 abc")})
        self.assertEqual((st, j["error"]), (400, "bad_list"))
        self.assertIn("1行目", j["message"])
        st, j = self.c.json("POST", "/api/plan", {"spec": self.spec(mode="keep")})
        self.assertEqual((st, j["error"]), (400, "no_transcript"))
        st, j = self.c.json("POST", "/api/plan", {"spec": self.spec(silence={"noise": 5})})
        self.assertEqual(st, 400)
        j = self.run_job("/api/plan", {"spec": self.spec(mode="list", listText="100 200")})
        self.assertEqual(j["state"], "error")
        self.assertIn("範囲", j["error"]["message"])

    def test_plan_keep_from_transcript_rows(self):
        t = self.dir / "rows.transcript.json"
        t.write_text(json.dumps({"schema": "youtube-tools-transcript/v1", "segments": [
            {"start": 0.5, "end": 1.5, "text": "a", "cut": False}, {"start": 4.0, "end": 5.0, "text": "b", "cut": True},
            {"start": 8.5, "end": 9.5, "text": "c", "cut": False}]}), encoding="utf-8")
        j = self.run_job("/api/plan", {"spec": {"video": str(self.video), "transcript": str(t), "mode": "keep", "keepSource": "transcript"}})
        r = j["result"]
        self.assertEqual(r["keeps"], [[15, 45], [255, 285]])
        self.assertEqual(r["subtitles"]["source"], "transcript")
        self.assertEqual(len(r["transcriptRows"]), 3)
        j = self.run_job("/api/plan", {"spec": {"video": str(self.video), "transcript": str(t), "mode": "list", "listKind": "drop",
                                                "listText": "", "dropCutRows": True}})
        self.assertEqual(j["result"]["keeps"], [[0, 120], [150, 300]])
        j = self.run_job("/api/plan", {"spec": {"video": str(self.video), "transcript": str(t), "mode": "list", "listKind": "drop",
                                                "listText": "", "dropCutRows": False}})
        self.assertEqual(j["result"]["keeps"], [[0, 300]])

    def test_preset_transcript_rows_matches_pack_rule(self):
        """preset transcript-rows(入口のまとめて実行が使う)は pack.TRANSCRIPT_ROWS と同じ区間になる(文字起こしの Resolve パッケージと同じ規則)"""
        t = self.dir / "preset.transcript.json"
        t.write_text(json.dumps({"schema": "youtube-tools-transcript/v1", "segments": [
            {"start": 0.5, "end": 1.5, "text": "a", "cut": False}, {"start": 1.5, "end": 2.0, "text": "b", "cut": False},
            {"start": 8.5, "end": 9.5, "text": "c", "cut": False}]}), encoding="utf-8")
        j = self.run_job("/api/plan", {"spec": {"video": str(self.video), "transcript": str(t), "preset": "transcript-rows",
                                                "mode": "silence", "minLen": 5}})   # preset のときは他の指定を使わない
        want = serve.pack.plan_cut(serve.pack.Request(video=self.video, transcript=t, **serve.pack.TRANSCRIPT_ROWS))
        self.assertEqual(j["result"]["keeps"], [list(k) for k in want.keeps])
        st, j = self.c.json("POST", "/api/plan", {"spec": {"video": str(self.video), "preset": "transcript-rows"}})
        self.assertEqual((st, j["error"]), (400, "no_transcript"))
        st, j = self.c.json("POST", "/api/plan", {"spec": {"video": str(self.video), "transcript": str(t), "preset": "other"}})
        self.assertEqual((st, j["error"]), (400, "bad_value"))

    def test_build_overwrite_confirm_open_folder_and_roughcut(self):
        out = self.dir / "out1"
        body = {"spec": self.spec(), "output": {"dir": str(out), "render": True}}
        j = self.run_job("/api/build", body)
        self.assertEqual(j["state"], "done", j)
        r = j["result"]
        self.assertEqual([f["name"] for f in r["files"]], ["clip.edl", "clip_cut.srt", "友人へ.txt", "cut-plan.json", "clip_roughcut.mp4"])
        self.assertIn("DaVinci Resolve", r["readme"])
        self.assertEqual(len(parse_edl((out / "clip.edl").read_text(encoding="utf-8"))), 3)
        st, hd, data = self.c.req("GET", r["roughcutUrl"], headers={"Range": "bytes=0-3"})
        self.assertEqual(st, 206)
        # 2回目: 上書きの確認
        st, j2 = self.c.json("POST", "/api/build", body)
        self.assertEqual((st, j2["error"]), (409, "exists"))
        self.assertIn("clip.edl", j2["files"])
        self.assertIn("clip_roughcut.mp4", j2["files"])
        before = (out / "clip.edl").stat().st_mtime_ns
        body["output"]["force"] = True
        body["output"]["render"] = False
        j3 = self.run_job("/api/build", body)
        self.assertEqual(j3["state"], "done", j3)
        self.assertNotEqual((out / "clip.edl").stat().st_mtime_ns, before)
        self.assertTrue(any("clip_roughcut.mp4" in w for w in j3["result"]["warnings"]))   # 前の粗編集が残っている注意
        # フォルダを開く(このサーバーが書いたフォルダだけ)
        st, j4 = self.c.json("POST", "/api/open-folder", {"path": str(out)})
        self.assertEqual(st, 200, j4)
        self.assertEqual(self.opened[-1], os.path.realpath(out))

    def test_output_dir_must_not_be_input(self):
        st, j = self.c.json("POST", "/api/build", {"spec": self.spec(), "output": {"dir": str(self.srt)}})
        self.assertEqual((st, j["error"]), (400, "bad_out"))
        # 入力ファイルと同じ名前の出力は force でも断る(字幕を出力フォルダの <動画名>_cut.srt に置いた場合)
        out = self.dir / "collide"
        out.mkdir(exist_ok=True)
        sub = out / "clip_cut.srt"
        sub.write_text(self.srt.read_text(encoding="utf-8"), encoding="utf-8")
        j = self.run_job("/api/build", {"spec": self.spec(srt=str(sub)), "output": {"dir": str(out), "force": True}})
        self.assertEqual(j["state"], "error")
        self.assertIn("入力ファイル", j["error"]["message"])

    def test_cancel_and_busy(self):
        long_v = self.dir / "long.mp4"
        make_video(long_v, 20, size="960x540")
        st, j = self.c.json("POST", "/api/build", {"spec": {"video": str(long_v), "mode": "list", "listKind": "drop", "listText": ""},
                                                   "output": {"dir": str(self.dir / "out_c"), "render": True}})
        self.assertEqual(st, 200, j)
        job = j["job"]
        st, busy = self.c.json("POST", "/api/plan", {"spec": self.spec()})
        self.assertEqual((st, busy["error"]), (409, "busy"))
        for _ in range(200):   # 書き出しが始まる(進み具合が出る)まで待ってから取り消す
            st, cur = self.c.json("GET", "/api/job?id=" + job["id"])
            if cur.get("progress") or cur["state"] != "running":
                break
            time.sleep(0.05)
        st, _ = self.c.json("POST", "/api/job/cancel", {"id": job["id"]})
        self.assertEqual(st, 200)
        end = self.c.wait(job)
        self.assertEqual(end["state"], "cancelled", end)
        left = list((self.dir / "out_c").iterdir()) if (self.dir / "out_c").exists() else []
        self.assertEqual(left, [])
        st, j = self.c.json("GET", "/api/job?id=nothing")
        self.assertEqual(st, 404)



class TestTextPlusTargetOption(unittest.TestCase):
    def test_default_and_explicit_target(self):
        v = Path(tempfile.gettempdir()) / "x.mp4"
        self.assertEqual(serve.output_from_spec({"textplus": True}, v)["textplusTarget"],
                         {"fps": 30, "width": 1080, "height": 1920})
        o = serve.output_from_spec({"textplus": True, "textplusFps": "60", "textplusSize": "1920x1080"}, v)
        self.assertEqual(o["textplusTarget"], {"fps": 60, "width": 1920, "height": 1080})
        self.assertTrue(o["copyVideo"])

    def test_bad_target_is_400(self):
        v = Path(tempfile.gettempdir()) / "x.mp4"
        with self.assertRaises(serve.ApiError) as cm:
            serve.output_from_spec({"textplus": True, "textplusFps": "29"}, v)
        self.assertEqual(cm.exception.code, "bad_textplus")


if __name__ == "__main__":
    unittest.main(verbosity=2)
