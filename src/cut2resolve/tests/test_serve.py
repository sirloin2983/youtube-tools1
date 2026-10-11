#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""画面のサーバー(serve.py)の API のテスト。実サーバーを空きポートで別スレッドに起動する。
python -m unittest src/cut2resolve/tests/test_serve.py(パックの部品のテストは src/pipeline/pack/tests。RS1-2 で分かれた)"""
import http.client
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent))   # cut2resolve/(部品)
sys.path.insert(0, str(TESTS))
sys.path.append(str(TESTS.parents[1] / "pipeline" / "pack" / "tests"))   # test_cut2resolve の道具(RS1-2 で pipeline/pack/tests へ移した)
import serve  # noqa: E402
from pipeline.pack import request  # noqa: E402
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
        cls.data_patch = mock.patch.dict(os.environ, {"YTT_DATA_DIR": str(cls.dir / "data")})   # パックを作った記録(packs/)を一時フォルダへ
        cls.data_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.data_patch.stop()
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()


class TestGuards(ServerBase):
    def test_ping_and_defaults(self):
        st, j = self.c.json("GET", "/api/ping")
        self.assertEqual((st, j), (200, {"app": "cut2resolve", "version": serve.SERVER_VERSION}))
        # 指定を省いたときの値は pack.Request(コマンドと同じ)の既定と同じ(/api/state で画面に見せていたもの。0.22.0 で api/state は消した)
        r = serve.pack.Request(video=Path("x.mp4"))
        self.assertEqual({k: serve.DEFAULTS[k] for k in ("noise", "silenceMin", "silencePad", "minLen", "recStart")},
                         {"noise": r.noise, "silenceMin": r.silence_min, "silencePad": r.silence_pad, "minLen": r.min_len,
                          "recStart": r.rec_start})
        self.assertFalse({"joinGap", "crf"} & set(serve.DEFAULTS))   # 0.23.0: spec.joinGap・output.crf は受けないので既定も持たない

    def test_host_header_is_checked(self):
        st, _, body = self.c.req("GET", "/api/ping", headers={"Host": "evil.example:%d" % self.port})
        self.assertEqual(st, 403)
        self.assertIn("Host", json.loads(body)["message"])
        st, _, _ = self.c.req("GET", "/api/ping", headers={"Host": "localhost:%d" % self.port})
        self.assertEqual(st, 200)

    def test_post_origin_and_content_type(self):
        st, _, _ = self.c.req("POST", "/api/plan", {}, headers={"Origin": "http://evil.example"})
        self.assertEqual(st, 403)
        st, _, _ = self.c.req("POST", "/api/plan", {}, headers={"Origin": "http://http://127.0.0.1:%d" % self.port})
        self.assertEqual(st, 403)
        st, _, body = self.c.req("POST", "/api/plan", {}, headers={"Origin": "http://localhost:%d" % self.port})
        self.assertEqual((st, json.loads(body)["error"]), (400, "bad_request"))   # 検査を通って、指定の中身の検査まで届く
        st, _, _ = self.c.req("POST", "/api/plan", raw=b"{}", ctype="text/plain")
        self.assertEqual(st, 415)
        st, _, body = self.c.req("POST", "/api/plan", raw=b'{"spec": NaN}')
        self.assertEqual((st, json.loads(body)["error"]), (400, "bad_json"))
        st, _, body = self.c.req("POST", "/api/plan", raw=b"[]")
        self.assertEqual((st, json.loads(body)["error"]), (400, "bad_json"))

    def test_page_moved_to_edit_tool(self):
        """画面は「編集」に統合した(2026-09-26)。/ は案内だけ(スクリプトなし・CSP つき)。前の画面の部品は無い"""
        st, hd, body = self.c.req("GET", "/")
        html = body.decode("utf-8")
        self.assertEqual(st, 200)
        self.assertIn("「編集」に統合しました", html)
        self.assertNotIn("<script", html)
        self.assertIn("script-src 'self'", hd["Content-Security-Policy"])
        for path in ("/app.js", "/app.css", "/ui-kit.js", "/ui-kit.css"):
            st, _, _ = self.c.req("GET", path)
            self.assertEqual(st, 404, path)
        self.assertEqual(self.c.req("GET", "/serve.py")[0], 404)
        self.assertEqual(self.c.req("GET", "/../serve.py")[0], 404)


class TestPaths(ServerBase):
    def test_clean_path(self):
        self.assertIsNone(serve.clean_path("  ", "video"))
        self.assertEqual(serve.clean_path('"/tmp/a b.mp4"', "video"), os.path.normpath("/tmp/a b.mp4"))
        self.assertEqual(serve.clean_path("file:///tmp/%E5%8B%95%E7%94%BB.mp4", "video"), os.path.normpath("/tmp/動画.mp4"))
        for bad in ("relative/a.mp4", "a.mp4", "/tmp/a\nb.mp4", 12):
            with self.assertRaises(serve.ApiError, msg=repr(bad)):
                serve.clean_path(bad, "video")

    def test_input_path_errors_per_field(self):
        """入力のパスの検査(欄ごとの拡張子・完全なパス・有無)。以前は /api/inspect で欄ごとに見せていた(0.22.0 で消した)。plan・build も同じ検査"""
        srt = self.dir / "s.srt"
        srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nこんにちは\n", encoding="utf-8")
        self.assertEqual(serve.input_path(str(srt), "srt"), srt)
        self.assertIsNone(serve.input_path("", "transcript"))
        for value, field, code, words in (("clip.mp4", "video", "bad_path", "完全なパス"),
                                          (str(self.dir / "none.json"), "transcript", "not_found", "見つかりません"),
                                          (str(srt), "plan", "bad_ext", "拡張子")):
            with self.assertRaises(serve.ApiError, msg=field) as cm:
                serve.input_path(value, field)
            self.assertEqual(cm.exception.code, code)
            self.assertIn(words, cm.exception.message)
        st, j = self.c.json("POST", "/api/plan", {"spec": {"video": str(self.dir / "clip.mp4"), "plan": str(srt)}})
        self.assertEqual((st, j["error"]), (400, "not_found"))   # 動画から順に確かめる

    def test_removed_apis_answer_404(self):
        """消した画面のための API(0.22.0 で消した): api/state・api/inspect・api/upload・media/。検査(Origin)は消す前と同じく先に効く"""
        for method, path, kw in (("GET", "/api/state", {}), ("POST", "/api/inspect", {"body": {}}),
                                 ("POST", "/api/upload?kind=srt&name=a.srt", {"raw": b"x", "ctype": "application/octet-stream"})):
            st, _, body = self.c.req(method, path, **kw)
            self.assertEqual((st, json.loads(body)["error"]), (404, "not_found"), path)
        st, _, _ = self.c.req("POST", "/api/inspect", {}, headers={"Origin": "http://evil.example"})
        self.assertEqual(st, 403)

    def test_removed_helpers_are_gone(self):
        for gone in ("inspect_inputs", "sibling_suggestions", "save_upload", "clean_uploads", "safe_upload_name", "UPLOAD_DIR",
                     "UPLOAD_LIMITS", "MEDIA_TYPES", "AC"):
            self.assertFalse(hasattr(serve, gone), gone)
        for gone in ("register_media", "media_path"):
            self.assertFalse(hasattr(serve.AppState, gone), gone)
        self.assertFalse(hasattr(serve.C, "resolve_media_path"))

    def test_startup_makes_no_upload_folder(self):
        """起動の準備(_startup): 作業用のフォルダにアップロードの置き場を作らない・消さない。.runtime とログは今までどおり"""
        work = self.dir / "work_startup"
        with mock.patch.object(serve, "WORK_DIR", str(work)), mock.patch.object(serve, "LOG_PATH", str(work / "serve.log")), \
                mock.patch.object(serve, "BASE_PATH", "/"), mock.patch.dict(os.environ, {"YTT_RUNTIME_DIR": str(self.dir / "rt")}):
            rt = serve._startup(8899)
            try:
                self.assertTrue(rt and os.path.isfile(rt))
                self.assertTrue((work / "serve.log").is_file())
                self.assertFalse((work / "uploads").exists())
            finally:
                serve.remove_runtime(8899)

    def test_work_dir_matches_ytt_core(self):
        """途中のファイルの下のフォルダの名前は ytt と同じ(コマンドは ytt を読まないので cut2resolve_core にも持つ)"""
        from ytt import schemas as ys
        self.assertEqual(serve.C.WORK_DIR, ys.WORK_DIR)

    def test_open_folder_only_for_pack_dirs(self):
        st, j = self.c.json("POST", "/api/open-folder", {"path": str(self.dir)})
        self.assertEqual(st, 403)
        # 記録はあるが、中身のファイルがもう無いフォルダは開けない(古い記録で許さない)
        gone = self.dir / "gone_pack"
        gone.mkdir(exist_ok=True)
        d = Path(serve._txi.packs_dir(c2r_dir=serve.CODE_DIR))
        d.mkdir(parents=True, exist_ok=True)
        (d / serve._txi.pack_key(gone)).write_text(json.dumps({"schema": serve._txi.PACK_RECORD_SCHEMA, "dir": str(gone), "files": ["友人へ.txt"]}), encoding="utf-8")
        st, j = self.c.json("POST", "/api/open-folder", {"path": str(gone)})
        self.assertEqual(st, 403)
        (gone / "友人へ.txt").write_text("x", encoding="utf-8")
        st, j = self.c.json("POST", "/api/open-folder", {"path": str(gone)})
        self.assertEqual(st, 200)
        self.opened.clear()
        old = self.dir / "old_pack"   # 前のセッションで作ったパック(cut2resolve の cut-plan.json がある)は開ける
        old.mkdir(exist_ok=True)
        (old / "cut-plan.json").write_text(json.dumps({"schema": "youtube-tools-cut-plan/v1", "tool": {"name": "cut2resolve"}, "segments": []}), encoding="utf-8")
        st, j = self.c.json("POST", "/api/open-folder", {"path": str(old)})
        self.assertEqual((st, self.opened[-1:]), (200, [os.path.realpath(str(old))]))
        self.opened.clear()
        other = self.dir / "other_plan"   # 他のツールの cut-plan.json だけのフォルダは開けない
        other.mkdir(exist_ok=True)
        (other / "cut-plan.json").write_text(json.dumps({"schema": "youtube-tools-cut-plan/v1", "tool": {"name": "transcribe"}, "segments": []}), encoding="utf-8")
        st, j = self.c.json("POST", "/api/open-folder", {"path": str(other)})
        self.assertEqual(st, 403)
        st, j = self.c.json("POST", "/api/open-folder", {"path": "relative"})
        self.assertEqual(st, 400)
        self.assertEqual(self.opened, [])

    def test_pack_record_prune_removes_missing_folders_and_broken_records_first(self):
        """パックを作った記録が MAX_PACK_RECORDS を超えたら、古い順に見て フォルダの無いもの・読めないもの・形の違うものを消す(フォルダが残っているものは残す)"""
        import types
        recs = self.dir / "recs"
        recs.mkdir()
        alive, alive2 = self.dir / "alive_pack", self.dir / "alive2_pack"
        alive.mkdir()
        alive2.mkdir()
        for i, (name, text) in enumerate((("a.json", json.dumps({"dir": str(alive)})), ("b.json", json.dumps({"dir": str(self.dir / "prune_missing_pack")})),
                                          ("c.json", "{broken"), ("d.json", "[1]")), 1):
            (recs / name).write_text(text, encoding="utf-8")
            os.utime(recs / name, (1000 * i, 1000 * i))
        res = {"out_dir": alive2, "files": [("edl", alive2 / "x.edl")], "editMedia": None, "plan": {}}
        plan = types.SimpleNamespace(video=self.dir / "v.mp4")
        with mock.patch.object(serve._txi, "packs_dir", return_value=str(recs)), mock.patch.object(serve, "MAX_PACK_RECORDS", 2):
            serve.write_pack_record(res, plan, True, False)
        left = sorted(p.name for p in recs.iterdir())
        self.assertEqual(len(left), 3, left)              # 新しい記録 + 残したもの a(フォルダがある)・d(最後まで古い順の外)
        self.assertIn("a.json", left)
        self.assertIn("d.json", left)
        self.assertNotIn("b.json", left)
        self.assertNotIn("c.json", left)
        new = [p for p in recs.iterdir() if p.name not in ("a.json", "d.json")][0]
        self.assertEqual(json.loads(new.read_text(encoding="utf-8"))["dir"], str(alive2))
        self.assertTrue(new.read_text(encoding="utf-8").endswith("}\n"))   # 今までと同じ形(indent=1・最後に改行)

    def test_media_unknown_token(self):
        for tok in ("nope-nope-nope", "..%2Fserve.py", "a"):
            self.assertEqual(self.c.req("GET", "/media/" + tok)[0], 404, tok)


class TestHeavyJobLimit(unittest.TestCase):
    """パックの作成は、他のツールの重い処理と順番を待つ(ytt.jobs)。試算は、無音の検出が要るとき(heavy が真)だけ待つ
    (API を通した確かめは TestJobs.test_plan_with_detection_waits_for_heavy_slot)"""

    def test_build_waits_and_can_be_cancelled(self):
        from ytt import jobs
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


class TestBoard(unittest.TestCase):
    """② の掲示板(flow/board)に頭 pk で見える(RS8 の ② の口 S2)"""

    def _wait(self, job):
        for _ in range(200):
            if job.state != "running":
                break
            time.sleep(0.02)

    def test_job_state_reaches_board(self):
        from flow import board as B
        b = B.Board()
        b.register("pk", source=serve.board_jobs, cancel=serve.board_cancel)
        gate = threading.Event()
        with mock.patch.object(serve, "MOUNT", serve.MountContext(0, {"localhost"})):
            app = serve.MOUNT.app
            job = app.start_job("build", lambda task: gate.wait(5) and (task.check() or {"outDir": "D:/x/pack"}))
            got = b.snapshot()["jobs"]
            self.assertEqual([(j["id"], j["kind"], j["state"], j["canCancel"]) for j in got], [("pk:" + job.id, "pack", "running", True)])
            self.assertEqual(b.cancel("pk:" + job.id)["id"], "pk:" + job.id)
            gate.set()
            self._wait(job)
            j = b.snapshot()["jobs"][0]
            self.assertEqual((j["state"], j["canCancel"], j["finishedAt"] is not None), ("cancelled", False, True))
            done = app.start_job("plan", lambda task: {"outDir": "D:/x/pack"})
            self._wait(done)
            b.snapshot()
            d = b.get("pk:" + done.id)
            self.assertEqual((d["state"], d["target"]), ("done", {"path": "D:/x/pack"}))
            with self.assertRaises(B.NotFound):
                b.cancel("pk:nothere")


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

    def test_uses_ytt_core(self):
        """.runtime・siblings・Host/Origin の検査は ytt の1か所(2026-09-26。cut2resolve 自身の写しは消した)"""
        from ytt import httpsec, runtime
        self.assertIs(serve.TOOL_APPS, runtime.TOOL_APPS)
        self.assertIs(serve.httpsec, httpsec)
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

    def test_plan_reports_video_info_without_media_url(self):
        """試算の結果に動画の情報(fps・長さ・開始タイムコード)。動画は配信しない(0.22.0 で media/ と mediaUrl を消した)。
        Windows の「パスのコピー」の "…" つきのパスも受け付ける"""
        j = self.run_job("/api/plan", {"spec": {"video": '"%s"' % self.video, "mode": "list", "listKind": "drop", "listText": ""}})
        r = j["result"]
        self.assertEqual((r["fps"], r["total"], r["durationSec"], r["srcStart"]), ([30, 1], 300, 10.0, "00:00:00:00"))
        self.assertNotIn("mediaUrl", r)
        self.assertEqual(self.c.req("GET", "/media/" + "a" * 16)[0], 404)

    def test_plan_modes(self):
        j = self.run_job("/api/plan", {"spec": self.spec()})
        self.assertEqual(j["state"], "done", j)
        r = j["result"]
        self.assertEqual(r["count"], 3)
        self.assertIn("silence", r["drops"])
        self.assertEqual(r["subtitles"]["out"], 2)
        self.assertNotIn("mediaUrl", r)   # 動画は配信しない(0.22.0)
        self.assertEqual(r["outputs"]["existing"], [])
        self.assertFalse((self.dir / "clip_pack").exists())   # 試算はファイルを作らない
        j = self.run_job("/api/plan", {"spec": self.spec(mode="list", listKind="keep", listText="0:01 0:03\n5 8\n")})
        self.assertEqual(j["result"]["keeps"], [[30, 90], [150, 240]])
        j = self.run_job("/api/plan", {"spec": self.spec(mode="list", listKind="drop", listText="0 1\n")})
        self.assertEqual(j["result"]["keeps"], [[30, 300]])
        j = self.run_job("/api/plan", {"spec": self.spec(mode="list", listKind="drop", listText="", silenceExtra=True)})
        self.assertEqual(j["result"]["keeps"], [[0, 300]])        # 0.23.0: silenceExtra(③に無音を重ねる)は受けない = 黙って無視する
        self.assertNotIn("silence", j["result"]["drops"])
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

    def test_plan_with_detection_waits_for_heavy_slot(self):
        """無音の検出が要る試算(動画の音声を全部読む)は、パックの作成と同じく他のツールの重い処理と順番を待つ(ytt.jobs。0.22.3)。
        検出が要らない試算・検出結果が覚えてある試算は待たない。待っている間は取り消せる"""
        from ytt import jobs
        slots = jobs.HeavySlots(1)
        held = slots.acquire("transcribe")
        try:
            with mock.patch.object(serve._heavy, "SLOTS", slots):
                j = self.run_job("/api/plan", {"spec": self.spec(mode="list", listKind="keep", listText="0:01 0:03")})
                self.assertEqual(j["state"], "done")   # 検出が要らない試算は待たない
                st, j = self.c.json("POST", "/api/plan", {"spec": self.spec(silence={"noise": -41.5})})   # 覚えていない設定 = 検出が要る
                self.assertEqual(st, 200, j)
                job = j["job"]
                for _ in range(200):
                    st, cur = self.c.json("GET", "/api/job?id=" + job["id"])
                    if cur["message"] == jobs.WAIT_MESSAGE:
                        break
                    time.sleep(0.02)
                self.assertEqual((cur["state"], cur["message"]), ("running", jobs.WAIT_MESSAGE))
                self.c.json("POST", "/api/job/cancel", {"id": job["id"]})
                self.assertEqual(self.c.wait(job)["state"], "cancelled")
            slots.release(held)
            held = None
            j = self.run_job("/api/plan", {"spec": self.spec(silence={"noise": -41.5})})   # 空いたら通る(以後は覚えるので、次の試算は待たない)
            self.assertEqual(j["state"], "done", j)
            held = slots.acquire("transcribe")
            with mock.patch.object(serve._heavy, "SLOTS", slots):
                j = self.run_job("/api/plan", {"spec": self.spec(silence={"noise": -41.5})})
                self.assertEqual(j["state"], "done", j)
        finally:
            slots.release(held)

    def test_plan_keep_from_transcript_rows(self):
        t = self.dir / "rows.transcript.json"
        t.write_text(json.dumps({"schema": "youtube-tools-transcript/v1", "segments": [
            {"start": 0.5, "end": 1.5, "text": "a", "cut": False}, {"start": 4.0, "end": 5.0, "text": "b", "cut": True},
            {"start": 8.5, "end": 9.5, "text": "c", "cut": False}]}), encoding="utf-8")
        j = self.run_job("/api/plan", {"spec": {"video": str(self.video), "transcript": str(t), "mode": "keep", "keepSource": "transcript"}})
        r = j["result"]
        # 行の端を声の止まる所まで広げる(pack.ROW_EDGE。動画の音は 0-2 秒・4-6 秒・8-10 秒): 1.5 → 無音の始まり 2.0、ほかは決まった余白
        self.assertEqual(r["keeps"], [[12, 60], [252, 291]])
        j = self.run_job("/api/plan", {"spec": {"video": str(self.video), "transcript": str(t), "mode": "keep", "keepSource": "transcript",
                                                "rowEdge": False}})
        self.assertEqual(j["result"]["keeps"], [[15, 45], [255, 285]])   # 広げない
        j = self.run_job("/api/plan", {"spec": {"video": str(self.video), "transcript": str(t), "mode": "keep", "keepSource": "transcript",
                                                "rowEdge": False, "handles": 3, "joinGap": 10}})
        self.assertEqual(j["result"]["keeps"], [[15, 45], [255, 285]])   # 0.23.0: handles(余白)・joinGap(つなぐ隙間)は受けない = 無視する
        j = self.run_job("/api/plan", {"spec": {"video": str(self.video), "transcript": str(t), "preset": "transcript-rows",
                                                "rowEdge": {"after": 0, "before": 0}}})
        self.assertEqual(j["result"]["keeps"], [[15, 45], [255, 285]])   # 上限 0 = 広げない(決まった余白も上限の中)
        st, j = self.c.json("POST", "/api/plan", {"spec": {"video": str(self.video), "transcript": str(t), "preset": "transcript-rows",
                                                           "rowEdge": {"after": 9}}})
        self.assertEqual((st, j["error"]), (400, "bad_value"))
        # padAfter: 無音が見つからない端(3 行目の後ろ)の決まった余白だけ 0.2 → 0.4 秒(6 → 12 フレーム)。無音で止まる端は変わらない
        j = self.run_job("/api/plan", {"spec": {"video": str(self.video), "transcript": str(t), "mode": "keep", "keepSource": "transcript",
                                                "rowEdge": {"padAfter": 0.4}}})
        self.assertEqual(j["result"]["keeps"], [[12, 60], [252, 297]])
        j = self.run_job("/api/plan", {"spec": {"video": str(self.video), "transcript": str(t), "mode": "keep", "keepSource": "transcript",
                                                "rowEdge": {"on": False, "padAfter": 0.4}}})
        self.assertEqual(j["result"]["keeps"], [[15, 45], [255, 285]])   # オフなら広げない
        st, j = self.c.json("POST", "/api/plan", {"spec": {"video": str(self.video), "transcript": str(t), "preset": "transcript-rows",
                                                           "rowEdge": {"padAfter": 3}}})
        self.assertEqual((st, j["error"]), (400, "bad_value"))
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

    def test_keeps_from_edit_tool(self):
        """「編集」のタイムラインの残す区間(spec.keeps)のとおりに作る(pack.EDIT_KEEPS): 余白・最短の長さ・無音・カット済の行で変えない"""
        t = self.dir / "keeps.transcript.json"
        t.write_text(json.dumps({"schema": "youtube-tools-transcript/v1", "segments": [
            {"start": 0.5, "end": 1.5, "text": "a", "cut": False}, {"start": 1.6, "end": 1.9, "text": "b", "cut": True},
            {"start": 8.5, "end": 9.5, "text": "c", "cut": False}]}), encoding="utf-8")
        spec = {"video": str(self.video), "transcript": str(t), "keeps": [[0.5, 1.5], [1.5, 2.0], [4.0, 4.2], [8.5, 9.5]],
                "mode": "silence", "silenceExtra": True, "minLen": 5, "handles": 3}
        r = self.run_job("/api/plan", {"spec": spec})["result"]
        self.assertEqual(r["keeps"], [[15, 60], [120, 126], [255, 285]])   # 接する区間は1つに・短い区間も捨てない・カット済の行で削らない
        self.assertEqual(r["keepsSec"], [[0.5, 2.0], [4.0, 4.2], [8.5, 9.5]])
        self.assertEqual(r["drops"], {})                                      # 無音・カット済の行を重ねない
        self.assertTrue(any("0.5 秒より短い区間が 1 か所" in w and "0:04.00〜0:04.20" in w for w in r["warnings"]), r["warnings"])
        self.assertEqual(r["subtitles"]["out"], 2)                            # 字幕は残す行(a・c)
        r = self.run_job("/api/plan", {"spec": dict(spec, keeps=[[9.0, 12.0]])})["result"]
        self.assertEqual(r["keeps"], [[270, 300]])                            # 動画の長さを超える分は切って知らせる
        self.assertTrue(any("動画の長さを超える" in w for w in r["warnings"]), r["warnings"])
        j = self.run_job("/api/plan", {"spec": {"video": str(self.video), "keeps": [[1, 2]], "advanced": {"reel": "B1"}}})
        self.assertEqual(j["result"]["keeps"], [[30, 60]])                    # 文字起こしが無くても作れる(字幕なし)
        for keeps in ([], [[1, 1]], [[2, 1]], [[-1, 1]], [[0, 1], [0.5, 2]], [[3, 4], [0, 1]], [[0, "1"]], [[0, True]], [[0, 1, 2]],
                      [0, 1], "0 1", {"a": 1}, [[0, 1e9]], [[i, i + 0.5] for i in range(5001)]):
            st, e = self.c.json("POST", "/api/plan", {"spec": dict(spec, keeps=keeps)})
            self.assertEqual((st, e["error"]), (400, "bad_keeps"), str(keeps)[:40])
        st, e = self.c.json("POST", "/api/plan", {"spec": dict(spec, preset="transcript-rows")})
        self.assertEqual((st, e["error"]), (400, "bad_value"))                 # どちらかを黙って使わない
        req = serve.request_from_spec(dict(spec, advanced={"reel": "B1", "recStart": "00:00:00:00"}))
        self.assertEqual((req.base, req.handles, req.min_len, req.join_frames, req.silence, req.drop_cut_rows, req.warn_short, req.reel, req.rec_start),
                         ("list", 0.0, 0.0, 0, False, False, 0.5, "B1", "00:00:00:00"))

    def test_build_overwrite_confirm_open_folder_and_roughcut(self):
        out = self.dir / "out1"
        # fcpxml・crf は 0.23.0 から受けない(送っても無視する: FCPXML は作らない・範囲外の crf でも 400 にしない)
        body = {"spec": self.spec(), "output": {"dir": str(out), "render": True, "fcpxml": True, "crf": 99}}
        j = self.run_job("/api/build", body)
        self.assertEqual(j["state"], "done", j)
        r = j["result"]
        # cut-plan.json はフォルダに置かず、作業データの packs/ に記録する(④)
        self.assertEqual([f["name"] for f in r["files"]], ["clip.edl", "clip_cut.srt", "clip_roughcut.mp4"])   # 手順書は書かない(画面で見る)
        self.assertFalse((out / "cut-plan.json").exists())
        self.assertFalse((out / "友人へ.txt").exists())
        rec = json.loads((Path(serve._txi.packs_dir(c2r_dir=serve.CODE_DIR)) / serve._txi.pack_key(out)).read_text(encoding="utf-8"))
        self.assertEqual((rec["schema"], os.path.normcase(rec["dir"]), rec["textplus"], rec["cutPlan"]["schema"]),
                         ("youtube-tools-pack-record/v1", os.path.normcase(str(out)), False, "youtube-tools-cut-plan/v1"))
        self.assertEqual(sorted(rec["files"]), sorted(["clip.edl", "clip_cut.srt", "clip_roughcut.mp4"]))
        self.assertIn("DaVinci Resolve", r["readme"])
        self.assertEqual(len(parse_edl((out / "clip.edl").read_text(encoding="utf-8"))), 3)
        self.assertGreater((out / "clip_roughcut.mp4").stat().st_size, 0)
        self.assertFalse({"mediaUrl", "roughcutUrl"} & set(r))   # 動画は配信しない(0.22.0)
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
        with mock.patch.object(serve.AppState, "out_dir_allowed", lambda self, p: False):   # 起動し直した後も、記録があれば開ける
            st, j5 = self.c.json("POST", "/api/open-folder", {"path": str(out)})
        self.assertEqual(st, 200, j5)

    def test_build_textplus_minimal_and_backup(self):
        """Text+ パックは最小限(④)。output.backup で予備(EDL・予備の手順書・SRT)も入れる。記録は textplus: true"""
        out = self.dir / "tp_min"
        spec = {"video": str(self.video), "srt": str(self.srt), "keeps": [[0.5, 2.5], [4.5, 6.5]]}
        j = self.run_job("/api/build", {"spec": spec, "output": {"dir": str(out), "textplus": True}})
        self.assertEqual(j["state"], "done", j)
        rec = json.loads((Path(serve._txi.packs_dir(c2r_dir=serve.CODE_DIR)) / serve._txi.pack_key(out)).read_text(encoding="utf-8"))
        self.assertEqual((rec["textplus"], rec["backup"], "clip.mp4" in rec["files"]), (True, False, True))
        st, e = self.c.json("POST", "/api/build", {"spec": spec, "output": {"dir": str(out), "textplus": True, "backup": True}})
        self.assertEqual((st, e["error"]), (409, "exists"))                      # 上書きの確認
        self.assertNotIn("clip.edl", e["files"])                                  # まだ無いもの(予備)は並べない
        j = self.run_job("/api/build", {"spec": spec, "output": {"dir": str(out), "textplus": True, "backup": True, "force": True}})
        names = sorted(f["name"] for f in j["result"]["files"])
        self.assertIn("clip.edl", names)
        self.assertIn("clip.mp4", names)
        # E-15: 前に写した同じ動画(大きさ・更新日時)はコピーを飛ばし、注意に 1 行(ただの案内 = info)
        r = j["result"]
        skip = serve.C.COPY_SKIPPED.format("clip.mp4")
        self.assertIn(skip, r["warnings"])
        self.assertEqual(r["warningLevels"][r["warnings"].index(skip)], "info")
        self.assertFalse((out / "textplus-import.json").exists())
        self.assertFalse((out / "cut-plan.json").exists())
        # 配信者の名前 → 文字の色(git の履歴(679ff01 以前)の docs/archive/followup-2026-09-27.md の 4)。照らし合わせは ytt/colors.py。見つからなければ 400
        members = self.dir / "members.json"
        members.write_text(json.dumps({"groups": [{"name": "0期生", "members": [{"id": "sakura-miko", "name": "さくらみこ", "en": "Sakura Miko", "hex": "#FF8FDF"}]}]},
                                      ensure_ascii=False), encoding="utf-8")
        with mock.patch.dict(os.environ, {"YTT_HOLO_MEMBERS": str(members)}):
            out2 = self.dir / "tp_color"
            j = self.run_job("/api/build", {"spec": spec, "output": {"dir": str(out2), "textplus": True, "streamer": "ミコ"}})
            self.assertEqual(j["state"], "done", j)
            rec = json.loads((Path(serve._txi.packs_dir(c2r_dir=serve.CODE_DIR)) / serve._txi.pack_key(out2)).read_text(encoding="utf-8"))
            self.assertEqual((rec["textColor"], rec["streamer"]), ("#FF8FDF", "さくらみこ"))
            st, e = self.c.json("POST", "/api/build", {"spec": spec, "output": {"dir": str(self.dir / "tp_x"), "textplus": True, "streamer": "だれか"}})
            self.assertEqual((st, e["error"]), (400, "bad_streamer"))
            self.assertIn("見つかりません", e["message"])
        st, e = self.c.json("POST", "/api/build", {"spec": spec, "output": {"dir": str(out), "textplus": True, "textplusWrap": 99}})
        self.assertEqual((st, e["error"]), (400, "bad_value"))                  # 字幕の1段の文字数は 0〜40
        # 映像トラックの数(友人の依頼の ① 全自動。字幕はその上のトラック)
        out3 = self.dir / "tp_tracks"
        j = self.run_job("/api/build", {"spec": spec, "output": {"dir": str(out3), "textplus": True, "videoTracks": 4}})
        self.assertEqual(j["state"], "done", j)
        self.assertEqual(serve.TP.read_script_plan((out3 / "create_resolve_textplus_project.lua").read_text(encoding="utf-8"))["videoTracks"], 4)
        self.assertIn("V5 Text+ 字幕(一番上)", j["result"]["readme"])
        st, e = self.c.json("POST", "/api/build", {"spec": spec, "output": {"dir": str(self.dir / "tp_t6"), "textplus": True, "videoTracks": 6}})
        self.assertEqual((st, e["error"]), (400, "bad_tracks"))

    def test_build_volume_copy_skipped_second_time(self):
        """E-15 の続き(0.22.2): 音量をかけて写した動画(「編集」の既定 30%)は、パックの記録(packs/ の videoCopy)と条件が同じなら
        2 回目は作り直さない(ffmpeg を動かさない = 速い)。注意は info。量を変えたら作り直す。記録の形は鍵を足しただけ(txindex がそのまま読む)"""
        out = self.dir / "tp_vol"
        spec = {"video": str(self.video), "srt": str(self.srt), "keeps": [[0.5, 2.5], [4.5, 6.5]]}
        body = {"spec": spec, "output": {"dir": str(out), "textplus": True, "volume": 30}}
        j = self.run_job("/api/build", body)
        self.assertEqual(j["state"], "done", j)
        gain = j["result"]["loudness"]["gainDb"]
        rec_path = Path(serve._txi.packs_dir(c2r_dir=serve.CODE_DIR)) / serve._txi.pack_key(out)
        vc = json.loads(rec_path.read_text(encoding="utf-8"))["videoCopy"]
        self.assertEqual((vc["volume"], vc["gainDb"], vc["source"]["name"], vc["output"]["name"]), (30, round(gain, 2), "clip.mp4", "clip.mp4"))
        dst = out / "clip.mp4"
        before = dst.stat().st_mtime_ns
        body["output"]["force"] = True
        with mock.patch.object(serve.C, "copy_video_gain", wraps=serve.C.copy_video_gain) as cg:
            t0 = time.monotonic()
            j2 = self.run_job("/api/build", body)
            took = time.monotonic() - t0
            self.assertEqual(j2["state"], "done", j2)
            self.assertFalse(cg.called, took)                                       # 作り直していない
        self.assertEqual(dst.stat().st_mtime_ns, before)
        r = j2["result"]
        skip = serve.C.GAIN_COPY_SKIPPED.format("clip.mp4", gain)
        self.assertIn(skip, r["warnings"])
        self.assertEqual(r["warningLevels"][r["warnings"].index(skip)], "info")
        self.assertIn("clip.mp4", [f["name"] for f in r["files"]])
        rec = serve._txi.read_pack_record(str(out), c2r_dir=serve.CODE_DIR)       # txindex の読み取りはそのまま(鍵を足しただけ)
        self.assertEqual((rec["textplus"], rec["videoCopy"]), (True, vc))
        body["output"]["volume"] = 40                                                # 量を変えたら作り直す
        with mock.patch.object(serve.C, "copy_video_gain", wraps=serve.C.copy_video_gain) as cg:
            j3 = self.run_job("/api/build", body)
            self.assertTrue(cg.called)
        self.assertFalse(any("コピーを飛ばしました" in w for w in j3["result"]["warnings"]))
        self.assertEqual(serve._txi.read_pack_record(str(out), c2r_dir=serve.CODE_DIR)["videoCopy"]["volume"], 40)

    def test_overlap_nosub_and_speaker_styles(self):
        """重なる字幕の段・字幕に出さない行(noSub)・話者ごとの色の指定(speakerStyles)を API で。見積もり(api/plan)に段の数など"""
        doc = {"schema": "youtube-tools-transcript/v1", "tool": {"name": "transcribe-tool", "version": "0"}, "media": {},
               "speakers": [{"id": 0, "name": "兎田ぺこら"}, {"id": 1, "name": "話者2"}],
               "segments": [{"id": "a", "start": 0.5, "end": 2.0, "text": "一", "speaker": 0},
                            {"id": "b", "start": 1.0, "end": 2.5, "text": "二", "speaker": 1},
                            {"id": "c", "start": 3.0, "end": 4.0, "text": "ゲーム", "speaker": 1, "noSub": True},
                            {"id": "d", "start": 4.5, "end": 5.5, "text": "三", "speaker": 0}]}
        tr = self.dir / "styles.transcript.json"
        tr.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        spec = {"video": str(self.video), "transcript": str(tr), "keeps": [[0.5, 6.0]]}
        out = self.dir / "tp_styles"
        output = {"dir": str(out), "textplus": True, "speakerColors": False,
                  "speakerStyles": {"兎田ぺこら": {"color": "ff0000", "font": "x"}, "だれか": {"color": "#00FF00"}, "話者2": "bad"}}
        p = self.run_job("/api/plan", {"spec": spec, "output": output})
        self.assertEqual(p["state"], "done", p)
        r = p["result"]
        self.assertEqual((r["captionLanes"], r["captionsStacked"], r["captionsTrimmed"], r["noSubRows"]), (2, 1, 0, 1))
        self.assertEqual(r["subtitles"]["out"], 3)
        j = self.run_job("/api/build", {"spec": spec, "output": output})
        self.assertEqual(j["state"], "done", j)
        ip = serve.TP.read_script_plan((out / "create_resolve_textplus_project.lua").read_text(encoding="utf-8"))
        self.assertEqual([c["text"] for c in ip["captions"]], ["一", "二", "三"])
        self.assertEqual([c.get("fill") for c in ip["captions"]], [[1.0, 0.0, 0.0, 1.0], None, [1.0, 0.0, 0.0, 1.0]])   # speakerColors が false でも効く
        self.assertEqual([c.get("trackUp") for c in ip["captions"]], [None, 1, None])
        self.assertEqual(j["result"]["speakerColors"], [{"speaker": "兎田ぺこら", "name": "兎田ぺこら", "hex": "#FF0000", "from": "speakerStyles"}])
        self.assertEqual((j["result"]["summary"]["captionLanes"], j["result"]["summary"]["noSubRows"]), (2, 1))
        self.assertIn("V2〜V3 Text+ 字幕", j["result"]["readme"])

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

    def test_warning_levels_classify_actionable_vs_info(self):
        """問題5: 対処が要る警告(warn)とただの案内(info)を区別できるよう warningLevels を足す。
        既存の warnings(文字列の配列)はそのまま・互換のため足すだけ"""
        t = self.dir / "note.transcript.json"
        t.write_text(json.dumps({"schema": "youtube-tools-transcript/v1",
                                  "segments": [{"start": 0.5, "end": 1.5, "text": "a", "cut": False}]}), encoding="utf-8")
        j = self.run_job("/api/plan", {"spec": self.spec(transcript=str(t))})   # srt と transcript の両方 → SRT を使った案内(info)
        r = j["result"]
        self.assertEqual(len(r["warningLevels"]), len(r["warnings"]))
        msg = "字幕は SRT のほうを使いました(文字起こしはカットの判断にだけ使います)。"
        self.assertEqual(r["warningLevels"][r["warnings"].index(msg)], "info")

        j = self.run_job("/api/plan", {"spec": self.spec(mode="list", listKind="drop", listText="")})   # カットの指定なし → warn
        r = j["result"]
        self.assertEqual(r["warnings"], ["カットの指定がありません。動画全体を1区間として出力します。"])
        self.assertEqual(r["warningLevels"], ["warn"])

        # /api/build の結果は、パック作成そのものの警告(warnings 本体)と、試算からの注意(summary の中。
        # 「カットの指定がありません」はこちら)の両方に、それぞれ warningLevels が付く
        out = self.dir / "out_wl"
        j = self.run_job("/api/build", {"spec": self.spec(mode="list", listKind="drop", listText=""), "output": {"dir": str(out)}})
        r = j["result"]
        self.assertEqual(len(r["warningLevels"]), len(r["warnings"]))
        self.assertEqual(r["summary"]["warnings"], ["カットの指定がありません。動画全体を1区間として出力します。"])
        self.assertEqual(r["summary"]["warningLevels"], ["warn"])

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

    def test_removed_output_keys_are_ignored(self):
        """0.23.0: 消した画面のための output.fcpxml・output.crf は受けない。送っても黙って無視する(形が違っても 400 にしない)"""
        v = Path(tempfile.gettempdir()) / "x.mp4"
        for o in ({"fcpxml": True, "crf": 99}, {"fcpxml": "yes", "crf": "bad"}):
            got = serve.output_from_spec(o, v)
            self.assertFalse({"fcpxml", "crf"} & set(got))
            self.assertEqual(got, serve.output_from_spec({}, v))
        self.assertTrue(serve.output_from_spec({"copyVideo": True, "fcpxml": True}, v)["copyVideo"])

    def test_output_loudness_and_volume(self):
        """output.loudness(LUFS)と output.volume(%)。LUFS があれば % は使わない"""
        v = Path(tempfile.gettempdir()) / "x.mp4"
        self.assertEqual((serve.output_from_spec({}, v)["loudness"], serve.output_from_spec({}, v)["volume"]), (None, None))
        o = serve.output_from_spec({"loudness": -14, "volume": 50}, v)
        self.assertEqual((o["loudness"], o["volume"]), (-14.0, None))
        o = serve.output_from_spec({"loudness": 0, "volume": 50}, v)
        self.assertEqual((o["loudness"], o["volume"]), (None, 50))
        self.assertIsNone(serve.output_from_spec({"volume": 100}, v)["volume"])
        for bad in ({"loudness": -20}, {"loudness": "x"}, {"loudness": True}, {"volume": 0}, {"volume": 201}, {"volume": 7.5}, {"volume": True}):
            with self.assertRaises(serve.ApiError, msg=bad) as cm:
                serve.output_from_spec(bad, v)
            self.assertEqual(cm.exception.code, "bad_loudness")

    def test_output_video_tracks(self):
        """output.videoTracks: 省略 = 1・1〜5 だけ"""
        v = Path(tempfile.gettempdir()) / "x.mp4"
        self.assertEqual(serve.output_from_spec({}, v)["videoTracks"], 1)
        self.assertEqual(serve.output_from_spec({"videoTracks": 5}, v)["videoTracks"], 5)
        for bad in (0, 6, True, "x", 2.5):
            with self.assertRaises(serve.ApiError, msg=bad) as cm:
                serve.output_from_spec({"videoTracks": bad}, v)
            self.assertEqual(cm.exception.code, "bad_tracks")

    def test_bad_target_is_400(self):
        v = Path(tempfile.gettempdir()) / "x.mp4"
        with self.assertRaises(serve.ApiError) as cm:
            serve.output_from_spec({"textplus": True, "textplusFps": "29"}, v)
        self.assertEqual(cm.exception.code, "bad_textplus")



class SpeakerColorMapTest(unittest.TestCase):
    """A-2: 話者の名前 → メンバーカラー。1人に決まる名前だけ(ytt/colors.py の規則)。話者の区間が無ければ空"""

    def test_map(self):
        with tempfile.TemporaryDirectory() as d:
            members = Path(d) / "members.json"
            members.write_text(json.dumps({"groups": [{"name": "0期生", "members": [
                {"id": "sakura-miko", "name": "さくらみこ", "en": "Sakura Miko", "hex": "#FF8FDF"}]}]}, ensure_ascii=False), encoding="utf-8")
            plan = mock.Mock(speaker_spans=[(0, 1, "みこ"), (1, 2, "話者2"), (2, 3, "みこ")])
            with mock.patch.dict(os.environ, {"YTT_HOLO_MEMBERS": str(members)}):
                m, shown = serve.speaker_color_map(plan)
            self.assertEqual(m, {"みこ": "#FF8FDF"})
            self.assertEqual(shown, [{"speaker": "みこ", "name": "さくらみこ", "hex": "#FF8FDF"}])
            self.assertEqual(serve.speaker_color_map(mock.Mock(speaker_spans=None)), ({}, []))
        self.assertTrue(serve.output_from_spec({"textplus": True}, Path("x.mp4"))["speakerColors"])          # 既定はオン
        self.assertFalse(serve.output_from_spec({"textplus": True, "speakerColors": False}, Path("x.mp4"))["speakerColors"])


class SpeakerStylesTest(unittest.TestCase):
    """話者ごとの字幕の見た目の指定 output.speakerStyles(docs/spec/friend-intake.md の 6)。
    検査は鍵ごとの許可の一覧(今は color だけ)。知らない鍵・形の違う値はその項目だけ捨てる。全体の形が違えば無かったことにする"""

    def test_sanitize(self):
        f = serve.speaker_styles_from
        self.assertEqual(f(None), {})
        for bad in ([], "x", 1, True, [{"color": "#FF0000"}]):
            self.assertEqual(f(bad), {}, bad)
        self.assertEqual(f({"みこ": {"color": "ff8fdf"}, " すいせい ": {"color": "#0047ab"}}),
                         {"みこ": {"color": "#FF8FDF"}, "すいせい": {"color": "#0047AB"}})
        got = f({"a": {"color": "#FF0000", "font": "Comic", "size": 3},   # 知らない鍵は捨てる(色は効く)
                 "b": {"color": "red"}, "c": {"color": "#FFF"}, "d": {"color": 0xFF0000}, "e": {"color": "#GG0000"},   # 形の違う色 → その人ごと(鍵が残らない)
                 "f": "#FF0000", "": {"color": "#FF0000"}, "x" * 61: {"color": "#FF0000"}, "x" * 60: {"color": "#00ff00"}})
        self.assertEqual(got, {"a": {"color": "#FF0000"}, "x" * 60: {"color": "#00FF00"}})
        many = {"人%d" % i: {"color": "#000000"} for i in range(70)}
        self.assertEqual(len(f(many)), 50)
        self.assertEqual(list(f(many))[:2], ["人0", "人1"])
        self.assertEqual(f({"a": {"color": "#ff0000"}, "a ": {"color": "#00ff00"}}), {"a": {"color": "#FF0000"}})   # 同じ名前は先のもの
        self.assertEqual(set(request.SPEAKER_STYLE_KEYS), {"color"})
        o = serve.output_from_spec({"textplus": True, "speakerStyles": {"みこ": {"color": "#ff0000", "x": 1}}}, Path("x.mp4"))
        self.assertEqual(o["speakerStyles"], {"みこ": {"color": "#FF0000"}})
        self.assertEqual(serve.output_from_spec({"speakerStyles": "bad"}, Path("x.mp4"))["speakerStyles"], {})

    def test_priority_over_member_colors(self):
        """指定の色がメンバーカラーより先。名前は ytt.colors.normalize でそろえて同じなら合う(部分一致はしない)"""
        plan = mock.Mock(speaker_spans=[(0, 1, "さくら みこ"), (1, 2, "話者2"), (2, 3, "ぺこら"), (3, 4, "サクラミコ")])
        base = ({"さくら みこ": "#FF8FDF", "ぺこら": "#7EC2FE"}, [{"speaker": "さくら みこ", "name": "さくらみこ", "hex": "#FF8FDF"},
                                                              {"speaker": "ぺこら", "name": "兎田ぺこら", "hex": "#7EC2FE"}])
        styles = serve.speaker_styles_from({"さくらみこ": {"color": "#111111"}, "話者２": {"color": "#222222"}, "ぺこ": {"color": "#333333"}})
        m, shown = serve.apply_speaker_styles(plan, styles, *base)
        self.assertEqual(m, {"さくら みこ": "#111111", "サクラミコ": "#111111", "話者2": "#222222", "ぺこら": "#7EC2FE"})
        self.assertEqual([x["speaker"] for x in shown], ["ぺこら", "さくら みこ", "サクラミコ", "話者2"])
        self.assertEqual(shown[1], {"speaker": "さくら みこ", "name": "さくら みこ", "hex": "#111111", "from": "speakerStyles"})
        self.assertEqual(base[0]["さくら みこ"], "#FF8FDF")                                # 渡した対応は書き換えない
        self.assertEqual(serve.apply_speaker_styles(plan, {}, *base), base)

if __name__ == "__main__":
    unittest.main(verbosity=2)
