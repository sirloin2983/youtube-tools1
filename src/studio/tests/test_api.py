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
import common
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

    def test_localhost_host_ok(self):
        st, *_ = self.req("GET", "/api/ping", host="localhost:%d" % self.port)
        self.assertEqual(st, 200)

    def test_bad_host_rejected_get_and_write(self):   # DNS rebinding
        for h in ("evil.example:%d" % self.port, "127.0.0.1", "localhost", "127.0.0.1:1", ""):
            self.assertEqual(self.req("GET", "/api/ping", host=h)[0], 403, h)
            self.assertEqual(self.req("PUT", "/api/settings", {"settings": {}}, host=h)[0], 403, h)

    def test_sec_fetch_site(self):
        for v, want in (("cross-site", 403), ("same-site", 403), ("same-origin", 200), ("none", 200)):
            self.assertEqual(self.req("GET", "/api/ping", headers={"Sec-Fetch-Site": v})[0], want, v)
        self.assertEqual(self.req("PUT", "/api/settings", {"settings": {}}, headers={"Sec-Fetch-Site": "cross-site"})[0], 403)

    def test_navigation_from_other_tool_opens_page_only(self):
        """他のツールのリンクで画面を開くのは許す(same-site / cross-site でも)。API・静的ファイル・iframe は拒否"""
        nav = {"Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
        st, _, _, r = self.req("GET", "/?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3Dabcdefghijk", headers=nav)
        self.assertEqual(st, 200)
        self.assertEqual(r.getheader("X-Frame-Options"), "DENY")
        self.assertIn("frame-ancestors 'none'", r.getheader("Content-Security-Policy") or "")
        self.assertEqual(self.req("GET", "/", headers=dict(nav, **{"Sec-Fetch-Site": "cross-site"}))[0], 200)
        self.assertEqual(self.req("GET", "/api/state", headers=nav)[0], 403)
        self.assertEqual(self.req("GET", "/core.js", headers=nav)[0], 403)
        self.assertEqual(self.req("GET", "/", headers=dict(nav, **{"Sec-Fetch-Dest": "iframe"}))[0], 403)
        self.assertEqual(self.req("GET", "/", headers=dict(nav, **{"Sec-Fetch-Mode": "cors"}))[0], 403)

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

    def test_get_ignores_origin_but_write_requires_it_to_match(self):
        self.assertEqual(self.req("PUT", "/api/settings", {"settings": {}})[0], 200)   # Origin なし(curl 等)は許可


class TestBody(Base):
    def test_content_type(self):
        st = self.req("PUT", "/api/settings", raw=b"{}", headers={"Content-Type": "text/plain"})[0]
        self.assertEqual(st, 415)
        st = self.req("PUT", "/api/settings", raw=b"{}", headers={})[0]
        self.assertEqual(st, 415)

    def test_sizes(self):
        self.assertEqual(self.req("PUT", "/api/settings", raw=b"", headers={"Content-Type": "application/json"})[0], 413)
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)   # 宣言だけ巨大(本体は送らない)
        c.putrequest("PUT", "/api/settings", skip_host=True)
        c.putheader("Host", self.host)
        c.putheader("Content-Type", "application/json")
        c.putheader("Content-Length", str(serve.MAX_BODY + 1))
        c.endheaders()
        self.assertEqual(c.getresponse().status, 413)
        c.close()

    def test_bad_length_header(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.putrequest("PUT", "/api/settings", skip_host=True)
        c.putheader("Host", self.host)
        c.putheader("Content-Type", "application/json")
        c.putheader("Content-Length", "abc")
        c.endheaders()
        self.assertEqual(c.getresponse().status, 400)
        c.close()

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

    def test_security_headers(self):
        _, _, _, r = self.req("GET", "/api/ping")
        self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff")
        self.assertEqual(r.getheader("Cache-Control"), "no-store")

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
        except common.ApiError:
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

    def test_group_needs_two_videos(self):
        v1, _v2 = self._pair("needtwo")
        st, j, *_ = self.req("POST", "/api/collab/group", {"videoIds": [v1]})
        self.assertEqual((st, j["error"]), (400, "bad_request"))

    def test_group_rejects_video_already_in_another_group(self):
        v1, v2 = self._pair("dupe")
        v3 = hashlib.sha1(b"dupe3").hexdigest()[:11]
        self._open(v3)
        self.req("POST", "/api/collab/group", {"videoIds": [v1, v2]})
        st, j, *_ = self.req("POST", "/api/collab/group", {"videoIds": [v1, v3]})
        self.assertEqual((st, j["error"]), (409, "conflict"))

    def test_anchor_bad_points_rejected(self):
        v1, v2 = self._pair("badanchor")
        g = self.req("POST", "/api/collab/group", {"videoIds": [v1, v2]})[1]["group"]
        st, j, *_ = self.req("POST", "/api/collab/anchor", {"id": g["id"], "videoId": v2, "points": [[0, 0], [1, 400]]})
        self.assertEqual((st, j["error"]), (400, "bad_anchor"))
        st, j, *_ = self.req("POST", "/api/collab/anchor", {"id": g["id"], "videoId": v1, "points": [[0, 0]]})   # 基準の動画
        self.assertEqual(st, 400)

    def test_transfer_via_api(self):
        v1, v2 = self._pair("transfer")
        g = self.req("POST", "/api/collab/group", {"videoIds": [v1, v2]})[1]["group"]
        self.req("POST", "/api/collab/anchor", {"id": g["id"], "videoId": v2, "points": [[100.0, 110.0]]})
        st, j, *_ = self.req("PUT", "/api/video", {"id": v1, "title": "t", "marks": [{"start": 110.0, "end": 120.0, "status": "adopted"}]})
        self.assertEqual(st, 200)
        st, j, *_ = self.req("GET", "/api/video?id=" + v2)
        self.assertEqual(st, 200)
        marks = j["video"]["marks"]
        self.assertEqual(len(marks), 1)
        self.assertEqual((marks[0]["src"], marks[0]["status"]), ("collab", ""))

    def test_transfer_merges_into_existing_overlapping_mark(self):
        """転写先に、既に(手動で)近い位置のマークがある場合は、新規候補を作らずそちらへ統合し、
        開始・終了は両方の区間を覆うように広げる(狭くはしない)。"""
        v1, v2 = self._pair("mergeexisting")
        g = self.req("POST", "/api/collab/group", {"videoIds": [v1, v2]})[1]["group"]
        self.req("POST", "/api/collab/anchor", {"id": g["id"], "videoId": v2, "points": [[100.0, 110.0]]})
        # v2 に先に手動マークを置く(v1 の [110,120] が転写されると、マージン込みで v2 の [97.5, 112.5] になり重なる)
        st, j, *_ = self.req("PUT", "/api/video", {"id": v2, "title": "t2", "marks": [{"start": 98.0, "end": 108.0, "label": "自分で見つけた"}]})
        self.assertEqual(st, 200)
        existing_id = j["video"]["marks"][0]["id"]
        st, j, *_ = self.req("PUT", "/api/video", {"id": v1, "title": "t1", "marks": [{"start": 110.0, "end": 120.0, "status": "adopted"}]})
        self.assertEqual(st, 200)
        st, j, *_ = self.req("GET", "/api/video?id=" + v2)
        self.assertEqual(st, 200)
        marks = j["video"]["marks"]
        self.assertEqual(len(marks), 1)   # 新しい候補は増えていない
        m = marks[0]
        self.assertEqual(m["id"], existing_id)
        self.assertEqual((m["src"], m["label"]), ("manual", "自分で見つけた"))   # 判定・ラベル・src は変わらない
        self.assertEqual((m["start"], m["end"]), (97.5, 112.5))   # 両方の区間を覆うように広がる
        self.assertTrue(any("コラボ転写" in r for r in m["reasons"]))   # 由来も足される

    def test_transfer_merge_reverts_exported_status_when_range_grows(self):
        """統合で範囲が実際に広がったときは、書き出し済みマークも他の時刻編集と同様に「採用」へ戻す
        (書き出し済みファイルは古い範囲のものになり、実体とずれるため)。"""
        v1, v2 = self._pair("mergeexported")
        g = self.req("POST", "/api/collab/group", {"videoIds": [v1, v2]})[1]["group"]
        self.req("POST", "/api/collab/anchor", {"id": g["id"], "videoId": v2, "points": [[100.0, 110.0]]})
        st, j, *_ = self.req("PUT", "/api/video", {"id": v2, "title": "t2", "marks": [{"start": 98.0, "end": 108.0, "label": "書き出し済み"}]})
        mark_id = j["video"]["marks"][0]["id"]
        serve.STORE.mark_exported(v2, mark_id, "f/out.mp4", 98.0, 108.0)
        self.req("PUT", "/api/video", {"id": v1, "title": "t1", "marks": [{"start": 110.0, "end": 120.0, "status": "adopted"}]})
        st, j, *_ = self.req("GET", "/api/video?id=" + v2)
        self.assertEqual(st, 200)
        m = j["video"]["marks"][0]
        self.assertEqual((m["start"], m["end"]), (97.5, 112.5))
        self.assertEqual((m["status"], m["file"]), ("adopted", ""))   # 範囲が変わったので採用に戻る

    def test_transfer_does_not_merge_non_overlapping_mark(self):
        """離れた位置の既存マークとは統合しない(通常どおり新規候補を作る)。"""
        v1, v2 = self._pair("mergefar")
        g = self.req("POST", "/api/collab/group", {"videoIds": [v1, v2]})[1]["group"]
        self.req("POST", "/api/collab/anchor", {"id": g["id"], "videoId": v2, "points": [[100.0, 110.0]]})
        self.req("PUT", "/api/video", {"id": v2, "title": "t2", "marks": [{"start": 500.0, "end": 510.0, "label": "無関係"}]})
        self.req("PUT", "/api/video", {"id": v1, "title": "t1", "marks": [{"start": 110.0, "end": 120.0, "status": "adopted"}]})
        st, j, *_ = self.req("GET", "/api/video?id=" + v2)
        self.assertEqual(st, 200)
        marks = j["video"]["marks"]
        self.assertEqual(len(marks), 2)
        self.assertEqual(sorted(m["src"] for m in marks), ["collab", "manual"])

    def test_remove_and_get_missing_group(self):
        v1, v2 = self._pair("removedel")
        g = self.req("POST", "/api/collab/group", {"videoIds": [v1, v2]})[1]["group"]
        st, j, *_ = self.req("POST", "/api/collab/group/remove", {"id": g["id"], "videoId": v2})
        self.assertEqual((st, j["deleted"]), (200, True))   # 残り1本になるのでグループごと削除
        self.assertEqual(self.req("GET", "/api/collab/group?id=" + g["id"])[0], 404)

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
        with patch.dict(common._env, {"checked": True, "tools": {"ytdlp": {"found": True, "version": "2020.01.01", "ageDays": 2000}}}), \
                patch.object(common.shutil, "disk_usage", return_value=common.shutil._ntuple_diskusage(10, 9, 1024)):
            env = self.req("GET", "/api/state")[1]["env"]
        self.assertTrue(any("yt-dlp -U" in w for w in env["warnings"]), env["warnings"])
        self.assertTrue(any("空きが少なく" in w for w in env["warnings"]), env["warnings"])
        self.assertEqual(env["outDirFree"], 1024)


class TestErrorMessages(Base):
    def test_os_errors_say_what_happened(self):
        denied = PermissionError(13, "Permission denied", os.path.join(self.tmp, "settings-ui.json"))
        with patch.object(serve.STORE, "set_ui", side_effect=denied), patch.object(common, "log_failure") as log:
            st, j, *_ = self.req("PUT", "/api/settings", {"settings": {}})
        self.assertEqual(st, 500)
        self.assertIn("アクセスが拒否", j["message"])
        self.assertIn("settings-ui.json", j["message"])
        log.assert_called_once()
        with patch.object(serve.STORE, "set_ui", side_effect=OSError(28, "No space left on device")), patch.object(common, "log_failure"):
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


@unittest.skipUnless(common.find_tool("ffmpeg"), "ffmpeg が無い環境ではスキップ")
class TestExportApi(Base):
    """POST /api/export → GET /api/export?id= の各ファイルに path(mp4)と manifest(.clip.json)が入る(docs/spec/pipeline.md の 6)。"""
    def test_export_reports_media_and_manifest_paths(self):
        src = os.path.join(self.tmp, "real.mp4")
        ff = common.find_tool("ffmpeg")
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
    """POST /api/video/adopt-top: 入口の「まとめて実行(解析から全部)」が自動マークの上位を採用にする。学習の記録は書かない"""
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
        st, j, *_ = self.req("POST", "/api/video/adopt-top", {"id": vid, "top": 3})
        self.assertEqual((st, j["adopted"]), (200, []))   # 採用済みがあれば何もしない
        for bad in (0, 31, "2", True):
            self.assertEqual(self.req("POST", "/api/video/adopt-top", {"id": vid, "top": bad})[0], 400, bad)
        self.assertEqual(self.req("POST", "/api/video/adopt-top", {"id": "nothere0000", "top": 1})[0], 404)


class TestRequestMarks(Base):
    """POST /api/video/request-marks: 友人からの依頼。時刻で指定した区間を採用済みの手動マークに、足りない分を自動の上位で埋める"""
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
        st, j2, *_ = self.req("POST", "/api/video/request-marks", {"id": vid, "ranges": [[98.3, 192], [10, 20]], "auto": 2})
        self.assertEqual((st, j2["rangeIds"], j2["autoIds"], len(j2["video"]["marks"])), (200, j["rangeIds"], [], 2))   # 同じ区間(±0.5 秒)は使い回す・自動の候補は無い

    def test_fills_with_top_auto_and_reuses(self):
        vid = "reqmarks002"
        serve.STORE.ensure({"kind": "youtube", "videoId": vid}, "t")
        cands = [{"start": s, "end": s + 5, "peak": s + 1, "score": sc, "parts": {}, "reasons": []} for s, sc in ((10, 2.0), (30, 9.0), (50, 5.0), (70, 7.0))]
        serve.STORE.replace_auto(vid, cands, {"at": 1, "signals": {}, "counts": {}, "warnings": [], "spec": {}, "type": None}, 100.0, None)
        fb = feedback.feedback_path()
        before = os.path.getsize(fb) if os.path.exists(fb) else 0
        st, j, *_ = self.req("POST", "/api/video/request-marks", {"id": vid, "ranges": [[28, 40]], "auto": 2})
        self.assertEqual(st, 200, j)
        by = self.marks(j)
        self.assertEqual([by[i]["start"] for i in j["autoIds"]], [70.0, 50.0])   # 点数の高い順。区間と重なる 30 秒の候補は飛ばす
        self.assertEqual(sorted(m["start"] for m in by.values() if m["status"] == "adopted"), [28.0, 50.0, 70.0])
        self.assertEqual(os.path.getsize(fb) if os.path.exists(fb) else 0, before)   # 人の判定ではないので記録しない
        # 送り直し: 採用済みの自動マークも数に入れる(増やさない)。数を増やせば次の候補を足す
        st, j2, *_ = self.req("POST", "/api/video/request-marks", {"id": vid, "ranges": [[28, 40]], "auto": 2})
        self.assertEqual((j2["rangeIds"], j2["autoIds"], j2["video"]["rev"]), (j["rangeIds"], j["autoIds"], j["video"]["rev"]))   # 何も変えない
        st, j3, *_ = self.req("POST", "/api/video/request-marks", {"id": vid, "ranges": [], "auto": 3})
        self.assertEqual([self.marks(j3)[i]["start"] for i in j3["autoIds"]], [30.0, 70.0, 50.0])   # 区間が無ければ 30 秒の候補も入る
        # 区間が動画の長さを超えたら終わりで切る。長さの外から始まる区間は断る
        st, j4, *_ = self.req("POST", "/api/video/request-marks", {"id": vid, "ranges": [[90, 130]], "auto": 0})
        self.assertEqual((st, self.marks(j4)[j4["rangeIds"][0]]["end"]), (200, 100.0))
        self.assertEqual(self.req("POST", "/api/video/request-marks", {"id": vid, "ranges": [[100, 130]], "auto": 0})[0], 400)

    def test_rejects_bad_input(self):
        vid = "reqmarks003"
        ok = {"id": vid, "ranges": [[1, 2]], "auto": 0}
        for bad in ({"ranges": [[5, 5]]}, {"ranges": [[-1, 5]]}, {"ranges": [[0, 3601]]}, {"ranges": [["1", 2]]}, {"ranges": [[1, 2, 3]]}, {"ranges": "x"},
                    {"ranges": [[i, i + 1] for i in range(11)]}, {"auto": -1}, {"auto": 31}, {"auto": "1"}, {"auto": True}, {"id": "../etc"}, {"id": "x" * 30}):
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

    def test_open_twice_keeps_and_fills_empty_title(self):
        rid = "20261005-185301"
        st, j, *_ = self.req("POST", "/api/videos/open", live_body(rid, title=""))
        self.assertEqual((st, j["video"]["title"], j["video"]["live"]["videoId"]), (200, "", "U972n0ncl4k"))
        rev = j["video"]["rev"]
        st, j, *_ = self.req("POST", "/api/videos/open", live_body(rid, title=""))
        self.assertEqual((st, j["video"]["rev"]), (200, rev))   # 何も変えない
        st, j, *_ = self.req("POST", "/api/videos/open", live_body(rid, title="題"))
        self.assertEqual((st, j["video"]["title"]), (200, "題"))
        st, j, *_ = self.req("POST", "/api/videos/open", live_body(rid, title="別の題", url="https://youtu.be/aaaaaaaaaaa"))
        self.assertEqual((st, j["video"]["title"], j["video"]["live"]["videoId"]), (200, "題", "U972n0ncl4k"))   # 既にある題・録画の情報は変えない

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

    def test_channel_live_url_has_empty_video_id(self):
        st, j, *_ = self.req("POST", "/api/videos/open", live_body("20261005-185302", url="https://www.youtube.com/@someone/live"))
        self.assertEqual((st, j["video"]["live"]["videoId"]), (200, ""))

    def test_open_rejects_bad_values(self):
        bads = [dict(recording="abc"), dict(recording="20261005-185300-"), dict(recording="20261005-185300-" + "a" * 25), dict(recording="../x"), dict(recording=None),
                dict(recording=LIVE_ID + "\n"), dict(recorder="Rec"), dict(recorder="1rec"), dict(recorder="a" * 17), dict(recorder=""), dict(recorder=5),
                dict(url="http://www.youtube.com/watch?v=U972n0ncl4k"), dict(url="https://evil.example/watch?v=U972n0ncl4k"), dict(url="youtube.com/watch?v=U972n0ncl4k"),
                dict(url=""), dict(url=None), dict(url="https://www.youtube.com/watch?v=U972n0ncl4k\n"), dict(url="https://www.youtube.com.evil.example/x"),
                dict(title=5), dict(title=["x"])]
        for kw in bads:
            st, j, *_ = self.req("POST", "/api/videos/open", live_body("20261005-185399", **kw) if "recording" not in kw else live_body(**kw))
            self.assertEqual((st, j["error"]), (400, "bad_source"), kw)
        self.assertEqual(self.req("GET", "/api/video?id=20261005-185399")[0], 404)   # 断ったものは登録されない

    def test_id_conflict_with_other_kind(self):
        # YouTube の 11 文字・file の "f…" とは形が違うので重ならない。同じ id が別の種類で既にあれば 409(ensure の既存の規則)
        serve.STORE.ensure({"kind": "youtube", "videoId": "abcdefghijk"}, "t")
        with self.assertRaises(common.ApiError) as c:
            serve.STORE.ensure({"kind": "live", "videoId": "abcdefghijk", "live": {}}, "t")
        self.assertEqual(c.exception.status, 409)

    def _exported_setup(self, rid):
        self.req("POST", "/api/videos/open", live_body(rid))
        st, j, *_ = self.req("PUT", "/api/video", {"id": rid, "marks": [{"id": "m1", "start": 10, "end": 40, "label": "L", "status": "adopted"}]})
        self.assertEqual(st, 200, j)
        d = os.path.join(common.get_out_dir(), "配信中_" + rid)
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
        sneaky = os.path.join(common.get_out_dir(), "..", "outside.mp4")   # 書き出し先の外へ ..
        txt = os.path.join(os.path.dirname(p), "a.txt")
        with open(txt, "wb") as f:
            f.write(b"x")
        for bad in ({"path": outside}, {"path": sneaky}, {"path": os.path.join(os.path.dirname(p), "none.mp4")}, {"path": txt}, {"path": "clip.mp4"}, {"path": ""},
                    {"path": None}, {"path": os.path.dirname(p)}, {"path": common.get_out_dir()}, {"markId": 3}, {"markId": ""}, {"id": 3}):
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

    def test_archived_not_on_non_live(self):
        fid = self.fsrc["videoId"]
        self.req("PUT", "/api/video", {"id": fid, "marks": [{"id": "fm9", "start": 1, "end": 3, "status": "adopted", "archived": True}]})
        self.assertNotIn("archived", self.req("GET", "/api/video?id=" + fid)[1]["video"]["marks"][0])
        p = self._exported_setup("20261005-190650")
        self.assertEqual(self.req("POST", "/api/live/exported", {"id": fid, "markId": "fm9", "path": p, "archived": True})[0], 400)   # live でない配信は断る
        self.assertNotIn("archived", self.req("GET", "/api/video?id=" + fid)[1]["video"]["marks"][0])

    def test_exported_follows_guards(self):
        for kw in ({"host": "evil.example:%d" % self.port}, {"headers": {"Sec-Fetch-Site": "cross-site"}}, {"headers": {"Origin": "http://evil.example"}}):
            self.assertEqual(self.req("POST", "/api/live/exported", {"id": "x", "markId": "m", "path": "/x.mp4"}, **kw)[0], 403, kw)
        self.assertEqual(self.req("GET", "/api/live/exported")[0], 404)

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


@unittest.skipUnless(common.find_tool("ffmpeg"), "ffmpeg が無い環境ではスキップ")
class TestLiveSectionApi(Base):
    """POST /api/live/section(線 D の P4): YouTube の区間を、書き出し先の中の指定の path へ(疑似モード。STUDIO_FAKE_MEDIA を切り出す)。マーク・配信のデータは変えない"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.fake_media = os.path.join(cls.tmp, "fake_src.mp4")
        import subprocess
        subprocess.run([common.find_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=10:duration=12",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=12", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest", cls.fake_media], check=True, stdin=subprocess.DEVNULL)

    def setUp(self):
        p = patch.dict(os.environ, {"STUDIO_FAKE_MEDIA": self.fake_media})
        p.start()
        self.addCleanup(p.stop)
        self.folder = os.path.join(common.get_out_dir(), "配信フォルダ_" + self._testMethodName)   # テストごとに別のフォルダ
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
        fb = common.p("feedback.jsonl")
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
        self.assertAlmostEqual(common.media_info(b["path"])[0], 4.0, delta=0.3)
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
                dict(start=0, end=3601), dict(path=outside), dict(path=os.path.join(common.get_out_dir(), "..", "outside.mp4")), dict(path=existing),
                dict(path=os.path.join(common.get_out_dir(), "nodir", "a.mp4")), dict(path=os.path.join(self.folder, "a.txt")), dict(path="rel.mp4"), dict(path=None)]
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
