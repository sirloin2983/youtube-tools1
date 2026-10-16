"""友人の玄関の ⚙ と初回の準備の口のテスト(F2-5。src/friendapp/settings.py・setup.py・server.py)。本物のソケットで 127.0.0.1 のポート 0 に起こす。
② は偽物・ネット(取得と API キーの確かめ)は偽物・フォルダを選ぶ窓は偽物(画面を取らない)。リポジトリ直下で: py -3.10 -m unittest src/friendapp/tests/test_settings.py"""
import hashlib
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from collections import namedtuple
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from friendapp import places as P, server as S, settings as T, setup as SU  # noqa: E402
from friendapp.tests.test_server import FakeEngine  # noqa: E402

URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
KEY = "AIzaSyA-abcdefghijklmnopqrstuvwxyz012345"
Usage = namedtuple("Usage", "total used free")


class FakeDl:
    def __init__(self, files):
        self.files = files
        self.gate = threading.Event()
        self.gate.set()

    def get(self, url, part, expect, progress, cancelled):
        self.gate.wait(5)
        os.makedirs(os.path.dirname(part), exist_ok=True)
        with open(part, "wb") as f:
            f.write(self.files[url])
        progress(len(self.files[url]))


class SettingsServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="friendset-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ, {"YTT_MACHINE_FILE": os.path.join(self.tmp, "machine.json"), "USERPROFILE": os.path.join(self.tmp, "user")})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("YTT_YT_API_KEY", None)
        home = os.path.join(self.tmp, "home")
        self.model = b"model" * 20
        with_fetch = os.path.join(home, "fetch.json")
        os.makedirs(home)
        with open(with_fetch, "w", encoding="utf-8") as f:
            json.dump({"version": "0.93.0", "items": [
                {"name": "whisper.cpp/large-v3", "file": "m.bin", "url": "https://h/m.bin", "size": len(self.model),
                 "sha256": hashlib.sha256(self.model).hexdigest(), "base": "data", "dest": "transcribe/models", "unzip": None}]}, f)
        self.places = {"home": home, "data": os.path.join(home, "data"), "friend": os.path.join(home, "data", "app", "friendapp"),
                       "outbox": os.path.join(home, "data", "app", "outbox"), "cases": os.path.join(home, "作業"), "fetch": with_fetch}
        self.places["save"] = lambda: S.save_dir(self.places["friend"])
        os.makedirs(self.places["friend"])
        os.makedirs(self.places["cases"])
        self.app = S.FriendApp(self.places, make_engine=FakeEngine)
        self.dl = FakeDl({"https://h/m.bin": self.model})
        self.app.setup.downloader = self.dl
        self.app.setup.disk_usage = lambda p: Usage(10 ** 13, 0, 10 ** 13)
        self.app.setup.cuda = lambda: None
        self.app.setup.after = lambda res: self.after.append(res)   # 本物の道具の場所の教え直し(環境変数)はしない
        self.after = []
        self.picked = []
        self.pick_answer = None
        self.app.pick_folder = lambda what: (self.picked.append(what), self.pick_answer)[1]   # 本物の窓を出さない
        self.outdirs = []
        self.app.settings.set_out_dir = self.outdirs.append
        self.probes = []
        self.app.settings.probe = lambda key: (self.probes.append(key), (200, "{}"))[1]
        self.app.api.fetch = lambda vid: {"title": "題", "channel": "ch"}
        self.app.prepare()
        self.srv = S.Server(("127.0.0.1", 0), self.app)
        self.app.server = self.srv
        self.port = self.srv.server_address[1]
        self.thread = threading.Thread(target=self.srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.app.setup.cancel()
        self.dl.gate.set()
        self.app.setup.wait(5)
        self.srv.shutdown()
        self.thread.join(10)
        self.srv.server_close()

    def request(self, method, path, body=None, token=True):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": "127.0.0.1:%d" % self.port}
        if token:
            h[S.TOKEN_HEADER] = self.srv.token
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            h["Content-Type"] = "application/json"
        try:
            conn.request(method, path, body=data, headers=h)
            r = conn.getresponse()
            raw = r.read()
            return r.status, raw
        finally:
            conn.close()

    def get(self, path):
        st, raw = self.request("GET", path)
        return st, json.loads(raw.decode("utf-8")) if raw[:1] == b"{" else raw

    def post(self, path, body=None, token=True):
        st, raw = self.request("POST", path, body if body is not None else {}, token)
        return st, json.loads(raw.decode("utf-8"))

    # ---- 初回の準備(9-1)
    def test_setup_flow_blocks_send_until_fetched(self):
        st, j = self.get("/api/friend/inbox")
        s = j["setup"]
        self.assertTrue(s["active"])
        self.assertEqual(s["count"], 1)
        self.assertTrue(s["canStart"])
        self.assertEqual(s["places"][0]["path"], self.places["data"])
        # [送る](この PC)は断る・理由つき
        st, j = self.post("/api/friend/send", {"url": URL, "top": 3, "title": "題"})
        self.assertEqual(st, 400)
        self.assertIn("[取ってくる]", j["message"])
        # [あとで] → 帯
        st, j = self.post("/api/friend/setup/later")
        self.assertTrue(j["setup"]["later"])
        st, j = self.post("/api/friend/setup/open")
        self.assertFalse(j["setup"]["later"])
        # [始める] → 取り終える → 送れる
        self.dl.gate.clear()
        st, j = self.post("/api/friend/setup/start")
        self.assertEqual(st, 200)
        self.assertTrue(j["setup"]["running"])
        st, j = self.post("/api/friend/send", {"url": URL, "top": 3, "title": "題"})
        self.assertEqual(st, 400)
        self.assertIn("取っています", j["message"])
        st, j = self.post("/api/friend/setup/start")
        self.assertEqual(st, 409)   # 2 つ目は断る
        self.dl.gate.set()
        self.app.setup.wait(5)
        st, j = self.get("/api/friend/inbox")
        self.assertEqual(j["setup"]["count"], 0)
        self.assertTrue(j["setup"]["result"]["ok"])
        self.assertEqual(len(self.after), 1)
        st, j = self.post("/api/friend/send", {"url": URL, "top": 3, "title": "題"})
        self.assertEqual(st, 200, j)

    def test_setup_needs_token(self):
        st, j = self.post("/api/friend/setup/start", token=False)
        self.assertEqual(st, 403)
        self.assertFalse(self.app.setup.running())

    def test_setup_space_short(self):
        self.app.setup.disk_usage = lambda p: Usage(100, 99, 1)
        st, j = self.post("/api/friend/setup/start")
        self.assertEqual(st, 409)
        self.assertIn("空きが足りません", j["message"])

    def test_user_pc_send_not_blocked_by_parts(self):
        """ユーザーの PC に頼む依頼は、この PC の部品が足りなくても送れる(鍵が無いので別の理由で断る)"""
        st, j = self.post("/api/friend/send", {"url": URL, "top": 3, "title": "題", "pc": "user"})
        self.assertEqual(st, 400)
        self.assertIn("Dropbox", j["message"])

    # ---- ⚙
    def test_settings_view_defaults(self):
        st, j = self.get("/api/friend/settings")
        s = j["settings"]
        self.assertEqual(s["engine"], "A")
        self.assertFalse(s["apiKey"])
        self.assertEqual(s["apiKeyHelp"], T.KEY_HELP)
        self.assertEqual(s["cut"], "none")
        self.assertTrue(s["saveIsDefault"])
        self.assertTrue(s["caseIsDefault"])
        self.assertEqual(s["diskMinGB"], 20)

    def test_engine_disk_cut(self):
        st, j = self.post("/api/friend/settings", {"engine": "C", "diskMinGB": 35, "cut": "silence"})
        self.assertEqual(st, 200, j)
        s = j["settings"]
        self.assertEqual((s["engine"], s["diskMinGB"], s["cut"]), ("C", 35, "silence"))
        with open(os.environ["YTT_MACHINE_FILE"], encoding="utf-8") as f:
            m = json.load(f)
        self.assertEqual((m["device"], m["diskMinGB"]), ("cuda", 35))
        # カットは送るときの束に入る(しない = 入れない = 今までの束のまま)
        self.app.setup.checked = False   # 部品の確かめを外す(このテストは束を見る)
        st, j = self.post("/api/friend/send", {"url": URL, "top": 3, "title": "題"})
        self.assertEqual(st, 200, j)
        env, diff = self.app.engine.queue.submitted[-1]
        self.assertEqual(diff["pack"]["cut"], "silence")
        self.post("/api/friend/settings", {"cut": "none"})
        self.post("/api/friend/send", {"url": URL, "top": 3, "title": "題"})
        env, diff = self.app.engine.queue.submitted[-1]
        self.assertNotIn("cut", diff.get("pack") or {})

    def test_bad_values_refused(self):
        for body in ({"engine": "B"}, {"diskMinGB": -1}, {"diskMinGB": "abc"}, {"cut": "rows"}):
            st, j = self.post("/api/friend/settings", body)
            self.assertEqual(st, 400, body)
        self.assertFalse(os.path.exists(os.environ["YTT_MACHINE_FILE"]))

    def test_engine_c_fetches_cuda_part(self):
        blob = b"cuda-zip"
        item = {"name": SU.CUDA_NAME, "file": "c.zip", "url": "https://h/c.zip", "sha256": hashlib.sha256(blob).hexdigest(), "base": "data",
                "dest": "transcribe/bin", "unzip": "wcpp", "top": "", "member": "", "size": len(blob), "maxBytes": 0, "parts": []}
        self.dl.files["https://h/c.zip"] = blob
        self.app.setup.cuda = lambda: item
        self.app.setup.wcpp = lambda it, archive, root: None
        with mock.patch.object(SU, "_wcpp_ready", lambda root: False):
            st, j = self.post("/api/friend/settings", {"engine": "C"})
            self.assertEqual(st, 200)
            self.assertIn("取ってきます", j["message"])
            self.app.setup.wait(5)
            self.assertEqual(self.app.setup.result["done"], [SU.CUDA_NAME])   # C の部品だけ(ほかの足りない物は確認してから)

    def test_api_key_saved_and_never_returned(self):
        st, j = self.post("/api/friend/settings/key", {"key": "  " + KEY + "\n"})
        self.assertEqual(st, 200, j)
        self.assertEqual(self.probes, [KEY])
        self.assertTrue(j["settings"]["apiKey"])
        self.assertNotIn(KEY, json.dumps(j))
        st, raw = self.request("GET", "/api/friend/settings")
        self.assertNotIn(KEY.encode(), raw)
        with open(os.path.join(self.places["data"], "app", "keys.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["youtubeApiKey"], KEY)
        self.assertEqual(os.environ.get("YTT_YT_API_KEY"), KEY)
        # 消す → "" を書く(前のアプリのキーへ戻らない)
        st, j = self.post("/api/friend/settings/key", {"key": ""})
        self.assertFalse(j["settings"]["apiKey"])
        self.assertNotIn("YTT_YT_API_KEY", os.environ)
        old = os.path.join(self.tmp, "old")
        os.makedirs(os.path.join(old, "app"))
        with open(os.path.join(old, "app", "keys.json"), "w", encoding="utf-8") as f:
            json.dump({"youtubeApiKey": KEY}, f)
        env = {}
        self.assertFalse(P.api_key_env([self.places["data"], old], env))
        self.assertEqual(env, {})

    def test_api_key_bad(self):
        self.app.settings.probe = lambda key: (400, json.dumps({"error": {"errors": [{"reason": "keyInvalid"}]}}))
        st, j = self.post("/api/friend/settings/key", {"key": KEY})
        self.assertEqual(st, 400)
        self.assertIn("キーが違います", j["message"])
        self.assertFalse(os.path.exists(os.path.join(self.places["data"], "app", "keys.json")))
        st, j = self.post("/api/friend/settings/key", {"key": "short"})
        self.assertIn("形が違います", j["message"])

    def test_judge_messages(self):
        self.assertEqual(T.judge(200, ""), (True, "使えます"))
        self.assertIn("つながりません", T.judge(0, "URLError")[1])
        self.assertIn("有効", T.judge(403, json.dumps({"error": {"errors": [{"reason": "accessNotConfigured"}]}}))[1])
        self.assertIn("上限", T.judge(403, json.dumps({"error": {"errors": [{"reason": "quotaExceeded"}]}}))[1])
        self.assertIn("HTTP 500", T.judge(500, "x")[1])

    def test_pick_folder_save_and_cases(self):
        target = os.path.join(self.tmp, "受け取り先")
        self.pick_answer = target
        st, j = self.post("/api/friend/pick-folder", {"what": "save"})
        self.assertEqual(st, 200, j)
        self.assertTrue(j["chosen"])
        self.assertEqual(j["settings"]["saveDir"], target)
        self.assertFalse(j["settings"]["saveIsDefault"])
        self.assertEqual(self.places["save"](), target)
        cases = os.path.join(self.tmp, "D", "一時")
        self.pick_answer = cases
        st, j = self.post("/api/friend/pick-folder", {"what": "cases"})
        self.assertEqual(j["settings"]["caseRoot"], cases)
        self.assertEqual(self.places["cases"], cases)   # 新しい物からここ(受信箱・送るは places["cases"] をそのつど読む)
        self.assertEqual(self.outdirs, [cases])
        with open(os.environ["YTT_MACHINE_FILE"], encoding="utf-8") as f:
            self.assertEqual(json.load(f)["caseRoot"], cases)
        self.assertEqual(self.picked, ["save", "cases"])
        # やめた = 何も変えない
        self.pick_answer = None
        st, j = self.post("/api/friend/pick-folder", {"what": "save"})
        self.assertFalse(j["chosen"])
        self.assertEqual(j["settings"]["saveDir"], target)
        # 既定に戻す
        st, j = self.post("/api/friend/settings", {"reset": "save"})
        self.assertTrue(j["settings"]["saveIsDefault"])
        st, j = self.post("/api/friend/settings", {"reset": "cases"})
        self.assertTrue(j["settings"]["caseIsDefault"])
        # 知らない場所は断る
        st, j = self.post("/api/friend/pick-folder", {"what": "data"})
        self.assertEqual(st, 400)

    def test_pick_folder_bad_path(self):
        self.pick_answer = "relative\\path"
        st, j = self.post("/api/friend/pick-folder", {"what": "save"})
        self.assertEqual(st, 400)
        self.pick_answer = os.path.splitdrive(self.tmp)[0] + "\\"
        st, j = self.post("/api/friend/pick-folder", {"what": "cases"})
        self.assertEqual(st, 400)
        self.assertIn("直下", j["message"])

    def test_settings_writes_need_token(self):
        for path in ("/api/friend/settings", "/api/friend/settings/key", "/api/friend/pick-folder"):
            st, j = self.post(path, {"what": "save", "key": KEY, "cut": "silence"}, token=False)
            self.assertEqual(st, 403, path)
        self.assertEqual(self.picked, [])
        self.assertEqual(self.probes, [])

    def test_guide_page_served(self):
        st, raw = self.request("GET", "/friend/guide.html")
        if os.path.isfile(os.path.join(S.UI_DIR, "guide.html")):
            self.assertEqual(st, 200)
            for sec in ("send", "receive", "settings", "setup", "close"):
                self.assertIn(('id="%s"' % sec).encode(), raw)
        else:
            self.assertEqual(st, 404)

    def test_page_has_help_links(self):
        st, raw = self.request("GET", "/friend/")
        page = raw.decode("utf-8")
        for sec in ("send", "settings", "setup", "close"):
            self.assertIn('href="guide.html#%s"' % sec, page)
        with open(os.path.join(S.UI_DIR, "friend.js"), encoding="utf-8") as f:
            self.assertIn("helpLink('receive'", f.read())


if __name__ == "__main__":
    unittest.main()
