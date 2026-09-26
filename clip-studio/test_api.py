"""serve.py の HTTP 層のテスト(疑似モード・実サーバーを別スレッドで起動)。 実行: python3 test_api.py"""
import hashlib
import http.client
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ["STUDIO_FAKE"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze
import common
import serve

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
    """POST /api/export → GET /api/export?id= の各ファイルに path(mp4)と manifest(.clip.json)が入る(docs/pipeline.md の 6)。"""
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
        self.assertEqual(it["manifest"], os.path.splitext(it["path"])[0] + ".clip.json")
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
        fb = analyze.feedback_path() if hasattr(analyze, "feedback_path") else os.path.join(self.tmp, "feedback.jsonl")
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


if __name__ == "__main__":
    unittest.main(verbosity=1)
