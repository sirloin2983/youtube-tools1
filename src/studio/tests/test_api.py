"""serve.py の HTTP 層のテスト(疑似モード・実サーバーを別スレッドで起動)。 実行: python3 test_api.py"""
import hashlib
import http.client
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ["STUDIO_FAKE"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # ツールのフォルダ(studio/)
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # src(解析などは ytt・pipeline を読む。RS3-4 から common を読まない)
import startup  # noqa: E402  (src を sys.path に足し、スタジオのフォルダを ytt/studio_env に知らせる)
from ytt import errors, mediainfo, studio_env  # noqa: E402
import serve
from human.review import feedback
from pipeline.analyze import analyze

VID = "abcdefghijk"
PORT0 = 0   # OS に空きポートを選ばせる(他のエージェント・テストと同時に走らせてもぶつからない。以前は 18800 固定)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        serve.init(cls.tmp)
        cls.srv, cls.port = serve.make_server(PORT0)
        assert cls.srv is not None
        cls.th = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.th.start()
        cls.host = "127.0.0.1:%d" % cls.port
        # file 動画(内容は既知のバイト列)
        cls.media = os.path.join(cls.tmp, "clip.mp4")
        cls.data = bytes(range(256)) * 4   # 1024 bytes
        with open(cls.media, "wb") as f:
            f.write(cls.data)
        cls.fsrc = analyze.validate_source({"kind": "file", "path": cls.media})
        serve.STORE.ensure(cls.fsrc)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def req(self, method, path, body=None, headers=None, host=None, raw=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Host": self.host if host is None else host}
        if body is not None:
            raw = json.dumps(body).encode("utf-8")
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        c.request(method, path, body=raw, headers=h)   # Host を渡すので自動追加されない
        r = c.getresponse()
        data = r.read()
        c.close()
        try:
            j = json.loads(data)
        except ValueError:
            j = None
        return r.status, j, data, r


class TestGuards(Base):
    def test_ping_ok(self):
        st, j, *_ = self.req("GET", "/api/ping")
        self.assertEqual((st, j["app"], j["version"]), (200, "clip-studio", serve.SERVER_VERSION))

    def test_bad_host_rejected_get_and_write(self):   # DNS rebinding
        for h in ("evil.example:%d" % self.port, "127.0.0.1", "localhost", "127.0.0.1:1", ""):
            self.assertEqual(self.req("GET", "/api/ping", host=h)[0], 403, h)
            self.assertEqual(self.req("PUT", "/api/settings", {"settings": {}}, host=h)[0], 403, h)

    def test_settings_section_update_keeps_other_sections(self):
        self.assertEqual(self.req("PUT", "/api/settings", {"settings": {"other": {"a": 1}, "review": {"volume": 10}}})[0], 200)
        self.assertEqual(self.req("PUT", "/api/settings", {"section": "review", "value": {"volume": 55}})[0], 200)
        st, j = self.req("GET", "/api/settings")[:2]
        self.assertEqual(j["settings"], {"other": {"a": 1}, "review": {"volume": 55}})
        for bad in ({"section": "../x", "value": {}}, {"section": "review", "value": [1]}, {"section": 3, "value": {}}):
            self.assertEqual(self.req("PUT", "/api/settings", bad)[0], 400, bad)

    def test_origin_on_writes(self):
        ok = "http://" + self.host
        for o, want in ((ok, 200), ("http://localhost:%d" % self.port, 200), ("http://evil.example", 403), ("null", 403),
                        ("https://" + self.host, 403), ("http://" + self.host + ".evil.example", 403),
                        ("http://http://" + self.host, 403), ("http://" + self.host + "/", 403), ("HTTP://" + self.host, 403)):   # 完全一致だけ
            st = self.req("PUT", "/api/settings", {"settings": {}}, headers={"Origin": o})[0]
            self.assertEqual(st, want, o)


class TestBody(Base):
    def test_content_type(self):
        st = self.req("PUT", "/api/settings", raw=b"{}", headers={"Content-Type": "text/plain"})[0]
        self.assertEqual(st, 415)
        st = self.req("PUT", "/api/settings", raw=b"{}", headers={})[0]
        self.assertEqual(st, 415)

    def test_bad_json_and_non_object(self):
        h = {"Content-Type": "application/json"}
        self.assertEqual(self.req("PUT", "/api/settings", raw=b"{oops", headers=h)[0], 400)
        self.assertEqual(self.req("PUT", "/api/settings", raw=b"[1,2]", headers=h)[0], 400)
        self.assertEqual(self.req("PUT", "/api/settings", raw=b"\xff\xfe", headers=h)[0], 400)
        # 本文の規則は ytt.httpsec.read_json_body(2026-10-09): UTF-8 の JSON だけ。BOM・UTF-16・NaN / Infinity は 400(以前の json.loads(bytes) は通していた)
        for raw in (b"\xef\xbb\xbf{}", '{"settings": {}}'.encode("utf-16"), b'{"settings": {"a": NaN}}', b'{"settings": {"a": -Infinity}}'):
            st, _j, data, _r = self.req("PUT", "/api/settings", raw=raw, headers=h)
            self.assertEqual((st, data), (400, b"invalid json"), raw)
        self.assertEqual(self.req("PUT", "/api/settings", raw=b'{"settings": {}}', headers={"Content-Type": "application/json; charset=utf-8"})[0], 200)
        self.assertEqual(self.req("GET", "/api/settings")[1]["settings"], {})   # 断った本文は保存していない

    def test_settings_too_large(self):
        st, j, *_ = self.req("PUT", "/api/settings", {"settings": {"x": "a" * 40000}})
        self.assertEqual((st, j["error"]), (413, "too_large"))

    def test_settings_not_dict(self):
        st, j, *_ = self.req("PUT", "/api/settings", {"settings": [1]})
        self.assertEqual((st, j["error"]), (400, "bad_request"))


class TestRouting(Base):
    def test_unknown_paths(self):
        self.assertEqual(self.req("GET", "/nope")[0], 404)
        self.assertEqual(self.req("POST", "/nope", {})[0], 404)
        self.assertEqual(self.req("PUT", "/nope", {})[0], 404)
        self.assertEqual(self.req("POST", "/api/settings", {})[0], 404)   # PUT 専用
        self.assertEqual(self.req("PUT", "/api/export", {})[0], 404)      # POST 専用

    def test_static_only_whitelist(self):
        self.assertEqual(self.req("GET", "/")[0], 200)
        self.assertEqual(self.req("GET", "/core.js")[0], 200)
        for p in ("/serve.py", "/store.py", "/data.json", "/../serve.py", "/%2e%2e/serve.py", "/feedback.jsonl", "/studio.log", "/seed.json"):
            self.assertEqual(self.req("GET", p)[0], 404, p)

    def test_query_string_ignored_for_post_route(self):
        self.assertEqual(self.req("PUT", "/api/settings?x=1", {"settings": {}})[0], 200)

    def test_server_survives_garbage(self):
        import socket
        s = socket.create_connection(("127.0.0.1", self.port), timeout=3)
        s.sendall(b"\x00\x01garbage\r\n\r\n")
        s.close()
        self.assertEqual(self.req("GET", "/api/ping")[0], 200)


class TestMedia(Base):
    def get(self, rng=None, vid=None, method="GET"):
        h = {"Range": rng} if rng else {}
        return self.req(method, "/media?id=" + (self.fsrc["videoId"] if vid is None else vid), headers=h)

    def test_full(self):
        st, _, data, r = self.get()
        self.assertEqual((st, data, r.getheader("Accept-Ranges")), (200, self.data, "bytes"))

    def test_ranges(self):
        d = self.data
        cases = [("bytes=0-3", 206, d[0:4], "bytes 0-3/1024"), ("bytes=1000-", 206, d[1000:], "bytes 1000-1023/1024"),
                 ("bytes=-4", 206, d[-4:], "bytes 1020-1023/1024"), ("bytes=10-99999", 206, d[10:], "bytes 10-1023/1024"),
                 ("bytes=-99999", 206, d, "bytes 0-1023/1024")]
        for rng, code, body, cr in cases:
            st, _, data, r = self.get(rng)
            self.assertEqual((st, data, r.getheader("Content-Range")), (code, body, cr), rng)

    def test_unsatisfiable_and_garbage(self):
        for rng in ("bytes=2000-", "bytes=5-2", "bytes=-0"):
            st, _, _, r = self.get(rng)
            self.assertEqual((st, r.getheader("Content-Range")), (416, "bytes */1024"), rng)
        for rng in ("bytes=", "bytes=-", "items=0-1", "bytes=0-1,5-6", "bytes=a-b"):
            self.assertEqual(self.get(rng)[0:3:2], (200, self.data), rng)   # 解釈できない Range は全体を返す

    def test_head_has_no_body(self):
        st, _, data, r = self.get(method="HEAD")
        self.assertEqual((st, data, r.getheader("Content-Length")), (200, b"", "1024"))

    def test_unknown_and_youtube_ids_404(self):
        self.assertEqual(self.get(vid="zzzzzzzzzzz")[0], 404)
        self.assertEqual(self.get(vid="")[0], 404)
        serve.STORE.ensure({"kind": "youtube", "videoId": VID, "name": VID})
        self.assertEqual(self.get(vid=VID)[0], 404)

    def test_no_client_supplied_path(self):
        st, *_ = self.req("GET", "/media?id=" + self.media)
        self.assertEqual(st, 404)
        st, *_ = self.req("GET", "/media?path=" + self.media)
        self.assertEqual(st, 404)

    def test_symlink_to_non_media_refused(self):
        secret = os.path.join(self.tmp, "secret.txt")
        with open(secret, "w") as f:
            f.write("SECRET")
        link = os.path.join(self.tmp, "link.mp4")
        try:
            os.symlink(secret, link)
        except OSError as e:
            if getattr(e, "winerror", None) == 1314:
                self.skipTest("Windows のシンボリックリンク作成権限がありません")
            raise
        # 登録後に差し替えられた場合を想定して、ストアへ直接入れる(validate_source が弾く場合はそれも防御として可)
        try:
            src = analyze.validate_source({"kind": "file", "path": link})
        except errors.ApiError:
            return
        serve.STORE.ensure(src)
        st, _, data, _ = self.get(vid=src["videoId"])
        self.assertEqual(st, 404)
        self.assertNotIn(b"SECRET", data)

    def test_deleted_file_404(self):
        p = os.path.join(self.tmp, "gone.mp4")
        with open(p, "wb") as f:
            f.write(b"x" * 10)
        src = analyze.validate_source({"kind": "file", "path": p})
        serve.STORE.ensure(src)
        os.remove(p)
        self.assertEqual(self.get(vid=src["videoId"])[0], 404)


class TestVideoApi(Base):
    def open_yt(self):
        return self.req("POST", "/api/videos/open", {"kind": "youtube", "url": "https://youtu.be/" + VID})

    def test_open_and_get(self):
        st, j, *_ = self.open_yt()
        self.assertEqual((st, j["video"]["id"]), (200, VID))
        st, j, *_ = self.req("GET", "/api/video?id=" + VID)
        self.assertEqual(st, 200)
        self.assertIn("series", j)

    def test_open_bad_url(self):
        for u in ("https://evil.example/watch?v=" + VID, "notaurl", "", None, 5):
            st, j, *_ = self.req("POST", "/api/videos/open", {"kind": "youtube", "url": u})
            self.assertEqual((st, j["error"]), (400, "bad_source"), u)

    def test_get_unknown_video(self):
        self.assertEqual(self.req("GET", "/api/video?id=nope")[0], 404)
        self.assertEqual(self.req("GET", "/api/video")[0], 404)

    def test_file_path_never_leaks(self):
        st, j, data, _ = self.req("GET", "/api/video?id=" + self.fsrc["videoId"])
        self.assertEqual(st, 200)
        self.assertNotIn(self.media.encode(), data)
        self.assertNotIn(self.tmp.encode(), data)
        self.assertNotIn("path", j["video"])
        _, _, data, _ = self.req("GET", "/api/videos")
        self.assertNotIn(self.tmp.encode(), data)

    def test_file_open_rejects_bad_paths(self):
        for p in ("/etc/passwd", "/nonexistent/x.mp4", os.path.join(self.tmp, "clip.txt"), "", None, "../x.mp4"):
            st, j, *_ = self.req("POST", "/api/videos/open", {"kind": "file", "path": p})
            self.assertEqual(st, 400, p)

    def test_put_marks_and_conflict(self):
        self.open_yt()
        rev = self.req("GET", "/api/video?id=" + VID)[1]["video"]["rev"]
        st, j, *_ = self.req("PUT", "/api/video", {"id": VID, "title": "t", "marks": [{"start": 1, "end": 9, "status": "adopted"}], "baseRev": rev})
        self.assertEqual((st, j["video"]["marks"][0]["status"]), (200, "adopted"))
        st, j, *_ = self.req("PUT", "/api/video", {"id": VID, "title": "t", "marks": [], "baseRev": rev})   # 古い rev
        self.assertEqual((st, j["error"], len(j["video"]["marks"])), (409, "conflict", 1))
        st, j, *_ = self.req("PUT", "/api/video", {"id": VID, "title": "t", "marks": [{"start": 9, "end": 1}]})
        self.assertEqual((st, j["error"]), (400, "bad_marks"))
        st, j, *_ = self.req("PUT", "/api/video", {"id": VID, "marks": "x"})
        self.assertEqual(st, 400)
        st, j, *_ = self.req("PUT", "/api/video", {"id": "nope", "marks": []})
        self.assertEqual(st, 404)

    def test_delete(self):
        self.open_yt()
        self.assertEqual(self.req("POST", "/api/video/delete", {"id": VID})[0], 200)
        self.assertEqual(self.req("POST", "/api/video/delete", {"id": VID})[0], 404)
        self.assertEqual(self.req("GET", "/api/video?id=" + VID)[0], 404)

    def test_title_validates_id(self):
        self.assertEqual(self.req("GET", "/api/title?v=..%2f..%2fetc")[0], 400)
        st, j, *_ = self.req("GET", "/api/title?v=" + VID)
        self.assertEqual(st, 200)


class TestCollabApi(Base):
    """コラボ動画のマーク転写の HTTP 層(グループ作成・アンカー指定・採用時の転写)。"""

    def _open(self, vid):
        st, j, *_ = self.req("POST", "/api/videos/open", {"kind": "youtube", "url": "https://youtu.be/" + vid})
        self.assertEqual(st, 200, j)
        return j["video"]

    def _pair(self, tag):
        """テストごとに固有の(重複しない)動画ID2本を開いて返す。"""
        v1, v2 = (hashlib.sha1((tag + n).encode()).hexdigest()[:11] for n in "12")
        self._open(v1)
        self._open(v2)
        return v1, v2

    def test_group_create_list_and_anchor(self):
        v1, v2 = self._pair("create")
        st, j, *_ = self.req("POST", "/api/collab/group", {"videoIds": [v1, v2]})
        self.assertEqual(st, 200)
        g = j["group"]
        self.assertEqual(g["base"], v1)
        self.assertFalse(g["allSet"])
        st, j, *_ = self.req("GET", "/api/collab/groups")
        self.assertEqual(st, 200)
        self.assertTrue(any(x["id"] == g["id"] for x in j["groups"]))
        st, j, *_ = self.req("POST", "/api/collab/anchor", {"id": g["id"], "videoId": v2, "points": [[100, 110]]})
        self.assertEqual(st, 200)
        self.assertTrue(j["group"]["allSet"])

    def test_group_and_anchor_not_found(self):
        self.assertEqual(self.req("GET", "/api/collab/group?id=nope")[0], 404)
        self.assertEqual(self.req("POST", "/api/collab/anchor", {"id": "nope", "videoId": "x", "points": [[0, 1]]})[0], 404)


class TestApiKey(Base):
    def test_state_never_returns_key(self):
        key = "A" * 39
        self.req("PUT", "/api/config", {"apiKey": key})
        _, j, data, _ = self.req("GET", "/api/state")
        self.assertNotIn(key.encode(), data)
        self.assertIn("hasKey", j)

    def test_bad_key_format_rejected(self):
        st, *_ = self.req("PUT", "/api/config", {"apiKey": "short"})
        self.assertGreaterEqual(st, 400)


class TestStateEnv(Base):
    def test_state_has_env_check(self):
        st, j, *_ = self.req("GET", "/api/state")
        self.assertEqual(st, 200)
        env = j["env"]
        self.assertEqual(set(env) >= {"checked", "python", "tools", "outDirFree", "warnings"}, True)
        self.assertIsInstance(env["warnings"], list)
        for k in ("hasKey", "ffmpeg", "ytdlp", "outDir", "defaultOutDir", "quota"):   # 既存の項目はそのまま
            self.assertIn(k, j)

    def test_old_ytdlp_and_low_disk_warn(self):
        with patch.dict(startup._env, {"checked": True, "tools": {"ytdlp": {"found": True, "version": "2020.01.01", "ageDays": 2000}}}), \
                patch.object(startup.shutil, "disk_usage", return_value=startup.shutil._ntuple_diskusage(10, 9, 1024)):
            env = self.req("GET", "/api/state")[1]["env"]
        self.assertTrue(any("yt-dlp -U" in w for w in env["warnings"]), env["warnings"])
        self.assertTrue(any("空きが少なく" in w for w in env["warnings"]), env["warnings"])
        self.assertEqual(env["outDirFree"], 1024)


class TestErrorMessages(Base):
    def test_os_errors_say_what_happened(self):
        denied = PermissionError(13, "Permission denied", os.path.join(self.tmp, "settings-ui.json"))
        with patch.object(serve.STORE, "set_ui", side_effect=denied), patch.object(studio_env, "log_failure") as log:
            st, j, *_ = self.req("PUT", "/api/settings", {"settings": {}})
        self.assertEqual(st, 500)
        self.assertIn("アクセスが拒否", j["message"])
        self.assertIn("settings-ui.json", j["message"])
        log.assert_called_once()
        with patch.object(serve.STORE, "set_ui", side_effect=OSError(28, "No space left on device")), patch.object(studio_env, "log_failure"):
            j = self.req("PUT", "/api/settings", {"settings": {}})[1]
        self.assertIn("No space left", j["message"])


class TestExportValidation(Base):
    def test_export_bad_input(self):
        for body in ({}, {"id": "nope", "marks": ["x"]}, {"id": VID, "markIds": "x"}):
            st, j, *_ = self.req("POST", "/api/export", body)
            self.assertIn(st, (400, 404), body)
            self.assertIsNotNone(j)

    def test_export_bad_volume_rejected(self):
        vid = "volumetst1x"
        st, j, *_ = self.req("POST", "/api/videos/open", {"kind": "youtube", "url": "https://youtu.be/" + vid})
        self.assertEqual(st, 200, j)
        for vol in (0, 201, -5, "abc"):
            st, j, *_ = self.req("POST", "/api/export", {"id": vid, "markIds": ["m1"], "volume": vol})
            self.assertEqual(st, 400, vol)
            self.assertEqual(j["error"], "bad_request")


@unittest.skipUnless(studio_env.find_tool("ffmpeg"), "ffmpeg が無い環境ではスキップ")
class TestExportApi(Base):
    """POST /api/export → GET /api/export?id= の各ファイルに path(mp4)と manifest(.clip.json)が入る(docs/spec/pipeline.md の 6)。"""
    def test_export_reports_media_and_manifest_paths(self):
        src = os.path.join(self.tmp, "real.mp4")
        ff = studio_env.find_tool("ffmpeg")
        import subprocess
        subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=10:duration=8",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=8", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest", src], check=True)
        st, j, *_ = self.req("POST", "/api/videos/open", {"kind": "file", "path": src})
        self.assertEqual(st, 200, j)
        vid = j["video"]["id"]
        st, j, *_ = self.req("PUT", "/api/video", {"id": vid, "marks": [{"id": "m1", "start": 1, "end": 3, "label": "テスト", "status": "adopted"}]})
        self.assertEqual(st, 200, j)
        st, job, *_ = self.req("POST", "/api/export", {"id": vid, "markIds": ["m1"], "precision": "accurate"})
        self.assertEqual(st, 200, job)
        for _ in range(300):
            st, job, *_ = self.req("GET", "/api/export?id=" + job["id"])
            if job["state"] != "running":
                break
            time.sleep(0.1)
        self.assertEqual(job["state"], "done", job)
        it = job["items"][0]
        self.assertTrue(os.path.isabs(it["path"]) and os.path.isfile(it["path"]))
        self.assertEqual(it["path"], os.path.join(job["outDir"], *it["file"].split("/")))   # file(相対)と同じもの
        self.assertEqual(it["manifest"], os.path.join(os.path.dirname(it["path"]), "作業用", os.path.splitext(os.path.basename(it["path"]))[0] + ".clip.json"))
        with open(it["manifest"], encoding="utf-8") as f:
            d = json.load(f)
        self.assertEqual((d["schema"], d["range"], d["mark"]["status"], d["source"]["kind"], d["source"]["path"]),
                         ("youtube-tools-clip/v1", {"start": 1.0, "end": 3.0}, "exported", "file", os.path.abspath(src)))
        self.assertEqual(d["tool"], {"name": "clip-studio", "version": serve.SERVER_VERSION})
        self.assertTrue(os.path.isfile(it["editManifest"]))
        v = self.req("GET", "/api/video?id=" + vid)[1]["video"]
        self.assertEqual(v["marks"][0]["status"], "exported")


class TestTranscripts(Base):
    """GET /api/transcripts: 書き出したマークに、その切り抜きの文字起こし(文字起こしツールのデータ)を元の配信の時刻で返す"""
    def test_lines_in_source_time(self):
        vid = self.fsrc["videoId"]
        st, j, *_ = self.req("PUT", "/api/video", {"id": vid, "marks": [{"id": "tx1", "start": 5, "end": 9, "status": "adopted"},
                                                                         {"id": "tx2", "start": 20, "end": 30, "status": "adopted"}]})
        self.assertEqual(st, 200, j)
        clip = os.path.join(self.tmp, "out", "01_セリフ.mp4")
        os.makedirs(os.path.dirname(clip), exist_ok=True)
        with open(clip, "wb") as f:
            f.write(b"x")
        self.assertTrue(serve.STORE.mark_exported(vid, "tx1", "01_セリフ.mp4", 5, 9, abspath=clip))
        txdir = os.path.join(self.tmp, "txdata", "transcripts")
        os.makedirs(txdir)
        doc = {"id": "aaaaaaaaaaaa", "title": "セリフ", "sourcePath": clip, "updatedAt": 3, "speakers": [{"id": "S1", "name": "話者1"}],
               "segments": [{"id": "s1", "start": 0.5, "end": 1.5, "text": "<b>やった</b>", "speaker": "S1", "proofed": True},
                            {"id": "s2", "start": 2.0, "end": 3.0, "text": "えーと", "cutState": "cut"}]}
        with open(os.path.join(txdir, "aaaaaaaaaaaa.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
        with patch.dict(os.environ, {"TRANSCRIBE_DATA_DIR": os.path.dirname(txdir)}):
            st, j, *_ = self.req("GET", "/api/transcripts?id=" + vid)
            self.assertEqual(st, 200, j)
            self.assertEqual((j["linked"], list(j["marks"])), (1, ["tx1"]))   # 書き出していないマークは無い
            t = j["marks"]["tx1"]
            self.assertEqual((t["id"], t["segments"], t["proofed"], t["offset"], t["offsetFrom"]), ("aaaaaaaaaaaa", 2, 1, 5.0, "mark"))
            self.assertEqual([(x["start"], x["end"], x["text"], x["speaker"], x["cut"]) for x in t["lines"]],
                             [(5.5, 6.5, "<b>やった</b>", "話者1", False), (7.0, 8.0, "えーと", "", True)])   # 文字はそのまま(画面が esc する)
            self.assertEqual(self.req("GET", "/api/transcripts?id=nothere0000")[0], 404)
        with open(os.path.join(txdir, "aaaaaaaaaaaa.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), doc)   # 文字起こしのデータは書き換えない
        self.assertEqual(self.req("GET", "/api/transcripts?id=" + vid, headers={"Sec-Fetch-Site": "cross-site"})[0], 403)


class TestAdoptTop(Base):
    """POST /api/video/adopt-top: スタジオの「上位 n 本を採用」。採用の規則 F-5(区間なしの adopt_marks)で、上限までの残りを自動マークの上位で採用にする。学習の記録は書かない"""
    def test_adopt_top(self):
        vid = "adopttop001"
        serve.STORE.ensure({"kind": "youtube", "videoId": vid}, "t")
        cands = [{"start": s, "end": s + 5, "peak": s + 1, "score": sc, "parts": {}, "reasons": []} for s, sc in ((10, 2.0), (30, 9.0), (50, 5.0))]
        serve.STORE.replace_auto(vid, cands, {"at": 1, "signals": {}, "counts": {}, "warnings": [], "spec": {}, "type": None}, 100.0, None)
        fb = feedback.feedback_path() if hasattr(feedback, "feedback_path") else os.path.join(self.tmp, "feedback.jsonl")
        before = os.path.getsize(fb) if os.path.exists(fb) else 0
        st, j, *_ = self.req("POST", "/api/video/adopt-top", {"id": vid, "top": 2})
        self.assertEqual(st, 200, j)
        by = {m["id"]: m for m in j["video"]["marks"]}
        self.assertEqual(sorted(by[i]["start"] for i in j["adopted"]), [30.0, 50.0])   # 点数の高い2件
        self.assertEqual(sum(1 for m in by.values() if m["status"] == "adopted"), 2)
        self.assertEqual(os.path.getsize(fb) if os.path.exists(fb) else 0, before)   # 人の判定ではないので記録しない
        st, j, *_ = self.req("POST", "/api/video/adopt-top", {"id": vid, "top": 2})
        self.assertEqual((st, j["adopted"]), (200, []))   # 前に機械が採用した 2 本で上限 = 何もしない
        st, j, *_ = self.req("POST", "/api/video/adopt-top", {"id": vid, "top": 3})
        self.assertEqual((st, [{m["id"]: m for m in j["video"]["marks"]}[i]["start"] for i in j["adopted"]]), (200, [10.0]))   # 上限を増やせば残りを足す(F-5)
        for bad in (0, 31, "2", True):
            self.assertEqual(self.req("POST", "/api/video/adopt-top", {"id": vid, "top": bad})[0], 400, bad)
        self.assertEqual(self.req("POST", "/api/video/adopt-top", {"id": "nothere0000", "top": 1})[0], 404)


class TestRequestMarks(Base):
    """POST /api/video/request-marks: まとめて実行・友人からの依頼。時刻で指定した区間を採用済みの手動マークに、上限 top までの残りを自動の上位で埋める(F-5)"""
    def marks(self, j):
        return {m["id"]: m for m in j["video"]["marks"]}

    def test_ranges_without_analysis(self):
        """解析していない配信でも、区間だけで使える(配信の記録を作る・題名とチャンネルを覚える)"""
        vid = "reqmarks001"
        st, j, *_ = self.req("POST", "/api/video/request-marks", {"id": vid, "title": "題", "channel": "ch", "ranges": [[98, 192.04], [10, 20]], "auto": 0})
        self.assertEqual(st, 200, j)
        by = self.marks(j)
        self.assertEqual([(by[i]["start"], by[i]["end"], by[i]["status"], by[i]["src"]) for i in j["rangeIds"]],
                         [(98.0, 192.0, "adopted", "manual"), (10.0, 20.0, "adopted", "manual")])   # ranges の順・小数1桁
        self.assertEqual((j["autoIds"], j["video"]["title"], j["video"]["channel"], j["video"]["analysis"]), ([], "題", "ch", None))
        st, j2, *_ = self.req("POST", "/api/video/request-marks", {"id": vid, "ranges": [[98.3, 192], [10, 20]], "top": 4})
        self.assertEqual((st, j2["rangeIds"], j2["autoIds"], len(j2["video"]["marks"])), (200, j["rangeIds"], [], 2))   # 同じ区間(±0.5 秒)は使い回す・自動の候補は無い

    def test_fills_with_top_auto_and_reuses(self):
        vid = "reqmarks002"
        serve.STORE.ensure({"kind": "youtube", "videoId": vid}, "t")
        cands = [{"start": s, "end": s + 5, "peak": s + 1, "score": sc, "parts": {}, "reasons": []} for s, sc in ((10, 2.0), (30, 9.0), (50, 5.0), (70, 7.0))]
        serve.STORE.replace_auto(vid, cands, {"at": 1, "signals": {}, "counts": {}, "warnings": [], "spec": {}, "type": None}, 100.0, None)
        fb = feedback.feedback_path()
        before = os.path.getsize(fb) if os.path.exists(fb) else 0
        st, j, *_ = self.req("POST", "/api/video/request-marks", {"id": vid, "ranges": [[28, 40]], "top": 3})
        self.assertEqual(st, 200, j)
        by = self.marks(j)
        self.assertEqual([by[i]["start"] for i in j["autoIds"]], [70.0, 50.0])   # 点数の高い順。区間と重なる 30 秒の候補は飛ばす
        self.assertEqual(sorted(m["start"] for m in by.values() if m["status"] == "adopted"), [28.0, 50.0, 70.0])
        self.assertEqual(os.path.getsize(fb) if os.path.exists(fb) else 0, before)   # 人の判定ではないので記録しない
        # 送り直し: 採用済みの自動マークも数に入れる(増やさない)。数を増やせば次の候補を足す
        st, j2, *_ = self.req("POST", "/api/video/request-marks", {"id": vid, "ranges": [[28, 40]], "auto": 2})   # 古い本文(auto)= top は区間の数 + auto
        self.assertEqual((j2["rangeIds"], j2["autoIds"], j2["added"], j2["video"]["rev"]), (j["rangeIds"], j["autoIds"], [], j["video"]["rev"]))   # 何も変えない
        st, j3, *_ = self.req("POST", "/api/video/request-marks", {"id": vid, "ranges": [], "top": 3})
        self.assertEqual([self.marks(j3)[i]["start"] for i in j3["autoIds"]], [30.0, 70.0, 50.0])   # 区間が無ければ 30 秒の候補も入る
        # 区間が動画の長さを超えたら終わりで切る。長さの外から始まる区間は断る
        st, j4, *_ = self.req("POST", "/api/video/request-marks", {"id": vid, "ranges": [[90, 130]], "top": 0})
        self.assertEqual((st, self.marks(j4)[j4["rangeIds"][0]]["end"]), (200, 100.0))
        self.assertEqual(self.req("POST", "/api/video/request-marks", {"id": vid, "ranges": [[100, 130]], "top": 0})[0], 400)

    def test_rejects_bad_input(self):
        vid = "reqmarks003"
        ok = {"id": vid, "ranges": [[1, 2]], "auto": 0}
        for bad in ({"ranges": [[5, 5]]}, {"ranges": [[-1, 5]]}, {"ranges": [[0, 3601]]}, {"ranges": [["1", 2]]}, {"ranges": [[1, 2, 3]]}, {"ranges": "x"},
                    {"ranges": [[i, i + 1] for i in range(11)]}, {"auto": -1}, {"auto": 31}, {"auto": "1"}, {"auto": True}, {"id": "../etc"}, {"id": "x" * 30},
                    {"top": -1}, {"top": 31}, {"top": "1"}, {"top": True}, {"top": None}):
            self.assertEqual(self.req("POST", "/api/video/request-marks", dict(ok, **bad))[0], 400, bad)


LIVE_ID = "20261005-185300-U972n0ncl4k"


def live_body(rid=LIVE_ID, **kw):
    b = {"kind": "live", "recorder": "rec", "recording": rid, "url": "https://www.youtube.com/watch?v=U972n0ncl4k", "title": "配信中"}
    b.update(kw)
    return b


class TestLiveApi(Base):
    """kind "live"(録画の部品で録っている配信): 登録・一覧と1本の形・書き出し済みの記録・解析とスタジオの書き出しを断る(線 D の P3)"""

    def test_open_and_shape(self):
        st, j, *_ = self.req("POST", "/api/videos/open", live_body())
        self.assertEqual(st, 200, j)
        v = j["video"]
        self.assertEqual((v["id"], v["kind"], v["title"], v["marks"]), (LIVE_ID, "live", "配信中", []))
        self.assertEqual(v["live"], {"recorder": "rec", "recording": LIVE_ID, "url": "https://www.youtube.com/watch?v=U972n0ncl4k", "videoId": "U972n0ncl4k"})
        st, j, data, _ = self.req("GET", "/api/video?id=" + LIVE_ID)
        self.assertEqual((st, j["video"]["live"], j["video"]["kind"]), (200, v["live"], "live"))
        row = next(x for x in self.req("GET", "/api/videos")[1]["videos"] if x["id"] == LIVE_ID)
        self.assertEqual((row["kind"], row["live"]), ("live", v["live"]))
        self.assertNotIn("live", next(x for x in self.req("GET", "/api/videos")[1]["videos"] if x["id"] == self.fsrc["videoId"]))   # 既存の種類には live を足さない
        self.assertEqual(self.req("GET", "/media?id=" + LIVE_ID)[0], 404)

    def test_open_sets_channel_once(self):
        """channel(入口の begin が yt-dlp から取ったチャンネル名。配信者の名前 = 字幕の色を決める): 空なら入れない・既にあれば上書きしない・制御文字を落とす・100 文字まで"""
        rid = "20261005-185303"
        st, j, *_ = self.req("POST", "/api/videos/open", live_body(rid))
        self.assertEqual((st, j["video"]["channel"]), (200, ""))
        rev = j["video"]["rev"]
        st, j, *_ = self.req("POST", "/api/videos/open", live_body(rid, channel=""))
        self.assertEqual((j["video"]["channel"], j["video"]["rev"]), ("", rev))   # 空は入れない(何も変えない)
        st, j, *_ = self.req("POST", "/api/videos/open", live_body(rid, channel="Pekora\x07 Ch.\n 兎田ぺこら"))
        self.assertEqual((st, j["video"]["channel"], j["video"]["title"]), (200, "Pekora Ch. 兎田ぺこら", "配信中"))
        st, j, *_ = self.req("POST", "/api/videos/open", live_body(rid, channel="別のチャンネル"))
        self.assertEqual(j["video"]["channel"], "Pekora Ch. 兎田ぺこら")   # 既にあれば上書きしない
        self.assertEqual(self.req("GET", "/api/video?id=" + rid)[1]["video"]["channel"], "Pekora Ch. 兎田ぺこら")
        row = next(x for x in self.req("GET", "/api/videos")[1]["videos"] if x["id"] == rid)
        self.assertEqual(row["channel"], "Pekora Ch. 兎田ぺこら")
        st, j, *_ = self.req("POST", "/api/videos/open", live_body("20261005-185304", channel="c" * 300))   # 新しく登録するときも入れる
        self.assertEqual((st, j["video"]["channel"]), (200, "c" * 100))
        for bad in (5, ["x"], {"a": 1}):
            st, j, *_ = self.req("POST", "/api/videos/open", live_body("20261005-185305", channel=bad))
            self.assertEqual((st, j["error"]), (400, "bad_source"), bad)

    def test_open_rejects_bad_values(self):
        # 値ごとの形の検査は yturl.check_live(human/review/tests/test_studio.py の TestCheckLive)。ここは API が 400 にして登録しないことと、title の型
        bads = [dict(recording="abc"), dict(recorder="Rec"), dict(url="http://www.youtube.com/watch?v=U972n0ncl4k"), dict(title=5), dict(title=["x"])]
        for kw in bads:
            st, j, *_ = self.req("POST", "/api/videos/open", live_body("20261005-185399", **kw) if "recording" not in kw else live_body(**kw))
            self.assertEqual((st, j["error"]), (400, "bad_source"), kw)
        self.assertEqual(self.req("GET", "/api/video?id=20261005-185399")[0], 404)   # 断ったものは登録されない

    def test_live_adopt(self):
        """入口のライブの採用 POST /api/live/adopt(RS8 B3-5。flow/live_adopt.py の StudioMarks): 登録 + 同じ区間の使い回し + 採用のマークを 1 回で"""
        rid = "20261005-185310"
        body = dict(live_body(rid), start=100.04, end=130.0, label="山")
        body.pop("kind")
        st, j, *_ = self.req("POST", "/api/live/adopt", body)
        self.assertEqual(st, 200, j)
        self.assertEqual((j["video"], j["n"], j["mark"]["start"], j["mark"]["status"], j["mark"]["label"]), (rid, 1, 100.0, "adopted", "山"))
        st, j2, *_ = self.req("POST", "/api/live/adopt", dict(body, start=100.3, end=129.8, label=""))
        self.assertEqual((st, j2["mark"]["id"]), (200, j["mark"]["id"]))   # 同じ区間 ±0.5 秒は使い回し
        v = self.req("GET", "/api/video?id=" + rid)[1]["video"]
        self.assertEqual((v["kind"], v["title"], [m["id"] for m in v["marks"]]), ("live", "配信中", [j["mark"]["id"]]))
        for bad in (dict(body, url="http://evil.example/"), dict(body, start="x"), dict(body, end=None), dict(body, title=5), dict(body, label=["x"]),
                    dict(body, start=50.0, end=40.0)):
            self.assertEqual(self.req("POST", "/api/live/adopt", bad)[0], 400, bad)

    def _exported_setup(self, rid):
        self.req("POST", "/api/videos/open", live_body(rid))
        st, j, *_ = self.req("PUT", "/api/video", {"id": rid, "marks": [{"id": "m1", "start": 10, "end": 40, "label": "L", "status": "adopted"}]})
        self.assertEqual(st, 200, j)
        d = os.path.join(studio_env.get_out_dir(), "配信中_" + rid)
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "clip.mp4")
        with open(p, "wb") as f:
            f.write(b"x" * 10)
        return p

    def test_exported_marks_mark_as_exported(self):
        rid = "20261005-190000"
        p = self._exported_setup(rid)
        st, j, *_ = self.req("POST", "/api/live/exported", {"id": rid, "markId": "m1", "path": p})
        self.assertEqual((st, j["ok"]), (200, True), j)
        m = j["video"]["marks"][0]
        self.assertEqual((m["status"], m["file"], m["path"]), ("exported", "配信中_%s/clip.mp4" % rid, os.path.abspath(p)))
        self.assertEqual(self.req("GET", "/api/video?id=" + rid)[1]["video"]["marks"][0]["status"], "exported")
        st, j, *_ = self.req("POST", "/api/live/exported", {"id": rid, "markId": "m1", "path": p})   # 重ねて呼んでも落ちない
        self.assertEqual((st, j["ok"]), (200, True))
        st, j, *_ = self.req("POST", "/api/live/exported", {"id": rid, "markId": "nomark", "path": p})   # マークが無い: 記録しない(mark_exported と同じ)
        self.assertEqual((st, j["ok"]), (200, False))

    def test_exported_rejects_bad_requests(self):
        rid = "20261005-190100"
        p = self._exported_setup(rid)
        ok = {"id": rid, "markId": "m1", "path": p}
        outside = os.path.join(self.tmp, "outside.mp4")
        with open(outside, "wb") as f:
            f.write(b"x")
        sneaky = os.path.join(studio_env.get_out_dir(), "..", "outside.mp4")   # 書き出し先の外へ ..
        txt = os.path.join(os.path.dirname(p), "a.txt")
        with open(txt, "wb") as f:
            f.write(b"x")
        for bad in ({"path": outside}, {"path": sneaky}, {"path": os.path.join(os.path.dirname(p), "none.mp4")}, {"path": txt}, {"path": "clip.mp4"}, {"path": ""},
                    {"path": None}, {"path": os.path.dirname(p)}, {"path": studio_env.get_out_dir()}, {"markId": 3}, {"markId": ""}, {"id": 3}):
            st, j, *_ = self.req("POST", "/api/live/exported", dict(ok, **bad))
            self.assertEqual(st, 400, bad)
        self.assertEqual(self.req("GET", "/api/video?id=" + rid)[1]["video"]["marks"][0]["status"], "adopted")   # 断ったものは記録されない
        self.assertEqual(self.req("POST", "/api/live/exported", dict(ok, id="20261005-199999"))[0], 404)
        # live でない配信は断る
        fid = self.fsrc["videoId"]
        self.req("PUT", "/api/video", {"id": fid, "marks": [{"id": "fm1", "start": 1, "end": 3, "status": "adopted"}]})
        st, j, *_ = self.req("POST", "/api/live/exported", {"id": fid, "markId": "fm1", "path": p})
        self.assertEqual(st, 400)
        self.assertEqual(self.req("GET", "/api/video?id=" + fid)[1]["video"]["marks"][0]["status"], "adopted")

    def test_exported_archived_flag(self):
        """archived(本番版に入れ替え済みの印。線 D の P4): exported の archived: true だけが立てる(画面の PUT では立てられず・保たれ・時刻を変えると消える)"""
        rid = "20261005-190600"
        p = self._exported_setup(rid)
        body = {"id": rid, "markId": "m1", "path": p}
        st, j, *_ = self.req("POST", "/api/live/exported", body)   # 省略 = 今までどおり(印なし)
        self.assertEqual((st, j["ok"], "archived" in j["video"]["marks"][0]), (200, True, False))
        st, j, *_ = self.req("POST", "/api/live/exported", dict(body, archived=True))   # 既に書き出し済み・path も同じでも印だけ立つ
        m = j["video"]["marks"][0]
        self.assertEqual((st, j["ok"], m["archived"], m["status"], m["path"]), (200, True, True, "exported", os.path.abspath(p)))
        self.assertEqual(next(x for x in self.req("GET", "/api/videos")[1]["videos"] if x["id"] == rid)["archived"], 1)
        self.assertTrue(self.req("GET", "/api/video?id=" + rid)[1]["video"]["marks"][0]["archived"])
        # 画面の PUT: 立てられない(新しいマーク)・外せない(今のマーク)
        st, j, *_ = self.req("PUT", "/api/video", {"id": rid, "marks": [dict(m, archived=False), {"start": 100, "end": 120, "status": "adopted", "archived": True}]})
        self.assertEqual(st, 200, j)
        self.assertEqual([x.get("archived") for x in j["video"]["marks"]], [True, None])
        # 省略の exported は今の印を保つ
        st, j, *_ = self.req("POST", "/api/live/exported", body)
        self.assertTrue(j["video"]["marks"][0]["archived"])
        # 時刻を変えたら書き出し済み(path も)と一緒に消える
        st, j, *_ = self.req("PUT", "/api/video", {"id": rid, "marks": [dict(j["video"]["marks"][0], start=11)]})
        m = j["video"]["marks"][0]
        self.assertEqual((m["status"], m["file"], "archived" in m, "path" in m), ("adopted", "", False, False))
        # false で外せる・形が違えば 400
        self.req("POST", "/api/live/exported", dict(body, archived=True))
        self.assertEqual(self.req("POST", "/api/live/exported", dict(body, archived="yes"))[0], 400)
        self.assertEqual(self.req("POST", "/api/live/exported", dict(body, archived=1))[0], 400)
        self.assertTrue(self.req("GET", "/api/video?id=" + rid)[1]["video"]["marks"][0]["archived"])   # 断ったものは変えない
        st, j, *_ = self.req("POST", "/api/live/exported", dict(body, archived=False))
        self.assertNotIn("archived", j["video"]["marks"][0])

    def test_analysis_refused(self):
        rid = "20261005-190200"
        self.req("POST", "/api/videos/open", live_body(rid))
        for item in ({"kind": "live", "recording": rid}, {"kind": "live", "url": "https://www.youtube.com/watch?v=U972n0ncl4k"}, {"videoId": rid}, {"url": rid}, {"kind": "youtube", "videoId": rid}):
            st, j, *_ = self.req("POST", "/api/queue/add", {"items": [item], "settings": {}})
            self.assertEqual(st, 200, item)
            self.assertEqual((j["added"], len(j["rejected"])), ([], 1), item)
        self.assertEqual(self.req("GET", "/api/queue")[1]["items"], [])
        st, j, *_ = self.req("POST", "/api/video/adopt-top", {"id": rid, "top": 2})
        self.assertEqual(st, 400, j)
        st, j, *_ = self.req("POST", "/api/video/request-marks", {"id": rid, "ranges": [[1, 5]], "auto": 0})
        self.assertEqual(st, 400, j)
        st, j, *_ = self.req("POST", "/api/video/request-marks", {"id": "20261005-190299", "ranges": [[1, 5]], "auto": 0})   # 未登録の録画の id でも YouTube として登録しない
        self.assertEqual(st, 400, j)
        self.assertEqual(self.req("GET", "/api/video?id=20261005-190299")[0], 404)
        self.assertIsNone(serve.STORE.replace_auto(rid, [], {}, 0, {}))

    def test_studio_export_refused(self):
        rid = "20261005-190300"
        self.req("POST", "/api/videos/open", live_body(rid))
        self.req("PUT", "/api/video", {"id": rid, "marks": [{"id": "m1", "start": 10, "end": 40, "status": "adopted"}]})
        with patch.object(serve.exporter, "start_job") as sj:
            st, j, *_ = self.req("POST", "/api/export", {"id": rid, "markIds": ["m1"]})
        self.assertEqual((st, j["error"]), (400, "bad_request"))
        self.assertIn("ライブ", j["message"])
        sj.assert_not_called()

    def test_marks_and_delete_work_like_other_videos(self):
        rid = "20261005-190400"
        self.req("POST", "/api/videos/open", live_body(rid))
        st, j, *_ = self.req("PUT", "/api/video", {"id": rid, "title": "t", "marks": [{"start": 5, "end": 30}]})
        self.assertEqual((st, len(j["video"]["marks"]), j["video"]["live"]["recording"]), (200, 1, rid))
        st, j, *_ = self.req("POST", "/api/video/delete", {"id": rid, "ifNoMarks": True})   # 入口の「マークの無い録画を消す」(P4): マークがあれば消さない
        self.assertEqual((st, j["error"]), (409, "has_marks"))
        self.assertEqual(self.req("GET", "/api/video?id=" + rid)[0], 200)
        self.assertEqual(self.req("POST", "/api/video/delete", {"id": rid})[0], 200)
        self.assertEqual(self.req("GET", "/api/video?id=" + rid)[0], 404)
        self.assertEqual(self.req("POST", "/api/video/delete", {"id": rid})[0], 404)
        rid2 = "20261005-190401"
        self.req("POST", "/api/videos/open", live_body(rid2))
        self.assertEqual(self.req("POST", "/api/video/delete", {"id": rid2, "ifNoMarks": True})[0], 200)   # マークが無ければ消す
        self.assertEqual(self.req("GET", "/api/video?id=" + rid2)[0], 404)

    def test_live_in_collab_group_and_transcripts(self):
        rid = "20261005-190500"
        self.req("POST", "/api/videos/open", live_body(rid))
        self.req("POST", "/api/videos/open", {"kind": "youtube", "url": "https://youtu.be/livecollab1"})
        st, j, *_ = self.req("POST", "/api/collab/group", {"videoIds": [rid, "livecollab1"]})
        self.assertEqual(st, 200, j)
        self.assertEqual(sorted(m["kind"] for m in j["group"]["members"]), ["live", "youtube"])
        self.assertEqual(self.req("GET", "/api/transcripts?id=" + rid)[0], 200)
        self.assertEqual(self.req("GET", "/api/collab/groups")[0], 200)
        self.assertEqual(self.req("POST", "/api/video/delete", {"id": rid})[0], 200)   # グループからも外れる


@unittest.skipUnless(studio_env.find_tool("ffmpeg"), "ffmpeg が無い環境ではスキップ")
class TestLiveSectionApi(Base):
    """POST /api/live/section(線 D の P4): YouTube の区間を、書き出し先の中の指定の path へ(疑似モード。STUDIO_FAKE_MEDIA を切り出す)。マーク・配信のデータは変えない"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.fake_media = os.path.join(cls.tmp, "fake_src.mp4")
        import subprocess
        subprocess.run([studio_env.find_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=10:duration=12",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=12", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest", cls.fake_media], check=True, stdin=subprocess.DEVNULL)

    def setUp(self):
        p = patch.dict(os.environ, {"STUDIO_FAKE_MEDIA": self.fake_media})
        p.start()
        self.addCleanup(p.stop)
        self.folder = os.path.join(studio_env.get_out_dir(), "配信フォルダ_" + self._testMethodName)   # テストごとに別のフォルダ
        os.makedirs(self.folder, exist_ok=True)

    def body(self, name="01_本番版.mp4", **kw):
        return dict({"videoId": "zzzzzzzzzzz", "start": 2, "end": 6, "path": os.path.join(self.folder, name)}, **kw)

    def wait(self, jid):
        for _ in range(300):
            st, job, *_ = self.req("GET", "/api/export?id=" + jid)
            if job["state"] != "running":
                return job
            time.sleep(0.1)
        self.fail("ジョブが終わらない")

    def snapshot(self):
        with open(serve.STORE.path, "rb") as f:
            data = f.read()
        fb = studio_env.p("feedback.jsonl")
        return (data, self.req("GET", "/api/videos")[2], os.path.getsize(fb) if os.path.exists(fb) else None)

    def test_makes_exactly_the_path_and_changes_no_data(self):
        rid = "20261005-191000"
        self.req("POST", "/api/videos/open", live_body(rid))
        self.req("PUT", "/api/video", {"id": rid, "marks": [{"id": "m1", "start": 10, "end": 40, "status": "adopted"}]})
        before = self.snapshot()
        b = self.body()
        st, j, *_ = self.req("POST", "/api/live/section", b)
        self.assertEqual(st, 200, j)
        self.assertTrue(j["id"])
        job = self.wait(j["id"])
        self.assertEqual(job["state"], "done", job)
        it = job["items"][0]
        self.assertEqual((it["status"], it["path"], it["manifest"]), ("done", b["path"], None))
        self.assertTrue(os.path.isfile(b["path"]))
        self.assertAlmostEqual(mediainfo.media_info(b["path"])[0], 4.0, delta=0.3)
        from ytt import normalize
        probe = normalize.probe(b["path"])
        if probe:
            self.assertEqual(probe["r_frame_rate"], "30/1")
        names = [n for d, _ds, ns in os.walk(self.folder) for n in ns]
        self.assertEqual(names, ["01_本番版.mp4"])   # .clip.json・編集用素材・書きかけは無い
        self.assertEqual(self.snapshot(), before)   # マーク・配信のデータ・学習の記録は一切変えない
        self.assertEqual(self.req("GET", "/api/video?id=zzzzzzzzzzz")[0], 404)   # スタジオに登録の無い videoId でも動き、登録もしない
        # もう同じ path は作れない(上書きしない)
        self.assertEqual(self.req("POST", "/api/live/section", b)[0], 400)

    def test_options_pass_the_same_checks_as_export(self):
        for kw in ({"volume": 0}, {"volume": 201}, {"volume": "abc"}, {"loudness": -13}, {"precision": "x"}):
            st, j, *_ = self.req("POST", "/api/live/section", self.body("o.mp4", **kw))
            self.assertEqual((st, j["error"]), (400, "bad_request"), kw)
        st, j, *_ = self.req("POST", "/api/live/section", self.body("opt.mp4", volume=100, precision="fast", maxHeight=720))
        self.assertEqual(st, 200, j)
        self.assertEqual(self.wait(j["id"])["state"], "done")

    def test_bad_requests_are_400_and_start_nothing(self):
        outside = os.path.join(self.tmp, "outside.mp4")
        existing = os.path.join(self.folder, "already.mp4")
        with open(existing, "wb") as f:
            f.write(b"keep")
        bads = [dict(videoId="bad"), dict(videoId="zzzzzzzzzz\n"), dict(videoId=None), dict(start=-1), dict(start=6), dict(start="2"), dict(end=0), dict(end=None),
                dict(start=0, end=3601), dict(path=outside), dict(path=os.path.join(studio_env.get_out_dir(), "..", "outside.mp4")), dict(path=existing),
                dict(path=os.path.join(studio_env.get_out_dir(), "nodir", "a.mp4")), dict(path=os.path.join(self.folder, "a.txt")), dict(path="rel.mp4"), dict(path=None)]
        with patch.object(serve.exporter, "start_job") as sj:
            for kw in bads:
                st, j, *_ = self.req("POST", "/api/live/section", self.body("bad.mp4", **kw))
                self.assertEqual((st, j["error"]), (400, "bad_request"), kw)
            raw = json.dumps(dict(self.body("nan.mp4"), end=float("nan"))).encode()   # NaN・Infinity の JSON
            self.assertEqual(self.req("POST", "/api/live/section", headers={"Content-Type": "application/json"}, raw=raw)[0], 400)
            self.assertEqual(self.req("POST", "/api/live/section", dict(self.body("inf.mp4"), end=1e999))[0], 400)
            raw = json.dumps(self.body("big.mp4")).replace('"end": ', '"end": 1' + "0" * 400 + ', "x": ', 1).encode()   # float にできない巨大な整数(以前は 500)
            st, j, *_ = self.req("POST", "/api/live/section", headers={"Content-Type": "application/json"}, raw=raw)
            self.assertEqual((st, j["error"]), (400, "bad_request"))
        sj.assert_not_called()
        self.assertFalse(os.path.exists(outside))
        with open(existing, "rb") as f:
            self.assertEqual(f.read(), b"keep")   # 既にあるファイルは上書きしない

    def test_follows_guards(self):
        for kw in ({"host": "evil.example:%d" % self.port}, {"headers": {"Sec-Fetch-Site": "cross-site"}}, {"headers": {"Origin": "http://evil.example"}}):
            self.assertEqual(self.req("POST", "/api/live/section", self.body("g.mp4"), **kw)[0], 403, kw)
        self.assertEqual(self.req("GET", "/api/live/section")[0], 404)
        self.assertFalse(os.path.exists(os.path.join(self.folder, "g.mp4")))

    def test_busy_and_cancel(self):
        def slow(job, *a, **kw):
            for _ in range(300):
                if job["cancel"]:
                    raise serve.exporter.ExportError("中止しました")
                time.sleep(0.05)
        with patch.object(serve.exporter, "run_ffmpeg", side_effect=slow):
            st, j, *_ = self.req("POST", "/api/live/section", self.body("c1.mp4"))
            self.assertEqual(st, 200, j)
            st, j2, *_ = self.req("POST", "/api/live/section", self.body("c2.mp4"))   # 今の書き出しと同じ: 実行中は 409
            self.assertEqual((st, j2["error"]), (409, "busy"))
            st, k, *_ = self.req("POST", "/api/export/cancel", {"id": j["id"]})
            self.assertEqual((st, k["ok"]), (200, True))
            job = self.wait(j["id"])
        self.assertEqual((job["state"], job["items"][0]["status"]), ("cancelled", "cancelled"))
        self.assertFalse(os.path.exists(os.path.join(self.folder, "c1.mp4")))
        self.assertEqual([n for n in os.listdir(self.folder) if n.startswith("c1")], [])


class TestRankSearch(Base):
    """① 探す: 「10分以上の動画だけ」(minDur。2026-10-04)の検査と絞り込み(疑似の YouTube API)"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from human.find import rank
        cls.rank = rank
        rank.import_official_channels("hololive")
        rank.resolve("hololive")

    def run_search(self, **kw):
        req = dict({"start": "2000-01-01", "end": "2100-12-31", "agencies": ["hololive"], "top": 100, "archiveOnly": False, "noShorts": False}, **kw)
        req["end"] = time.strftime("%Y-%m-%d")
        req["start"] = time.strftime("%Y-%m-%d", time.localtime(time.time() - 700 * 86400))
        job = {"id": "t", "state": "running", "phase": "", "progress": 0.0, "cancel": False, "error": "", "result": None}
        self.rank.run_search(job, self.rank.validate_search(req))
        self.assertEqual(job["state"], "done", job.get("error"))
        return [it["dur"] for a in job["result"]["agencies"] for it in a["items"]]

    def test_validate_min_dur(self):
        base = {"start": "2026-01-01", "end": "2026-01-31", "agencies": ["hololive"]}
        self.assertEqual(self.rank.validate_search(base)["minDur"], 0)   # 送らなければ絞らない(以前の画面・CLI)
        self.assertEqual(self.rank.validate_search(dict(base, minDur=600))["minDur"], 600)
        self.assertEqual(self.rank.validate_search(dict(base, minDur="600"))["minDur"], 600)
        for bad in (-1, 86401, "x", [1]):
            with self.assertRaises(self.rank.ApiError, msg=bad):
                self.rank.validate_search(dict(base, minDur=bad))

    def test_min_dur_filters_short_videos(self):
        all_durs = self.run_search(minDur=0)
        self.assertTrue(any(d < 600 for d in all_durs) and any(d >= 600 for d in all_durs), all_durs)   # 疑似データに両方ある(確かめの前提)
        long_durs = self.run_search(minDur=600)
        self.assertTrue(long_durs and all(d >= 600 for d in long_durs), long_durs)
        self.assertGreaterEqual(len(long_durs), sum(1 for d in all_durs if d >= 600))   # 10分以上のものは減らない(上位 top 本で切るので、短いものが抜けた分だけ増えうる)


if __name__ == "__main__":
    unittest.main(verbosity=1)
