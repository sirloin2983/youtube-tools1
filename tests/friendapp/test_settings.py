"""友人の玄関の ⚙ と初回の準備の口のテスト(src/friendapp/settings.py・setup.py・server.py)。本物のソケットで 127.0.0.1 のポート 0 に起こす。
② は偽物・ネット(取得と API キーの確かめ)は偽物・フォルダを選ぶ窓は偽物(画面を取らない)。リポジトリ直下で: py -3.12 -m unittest tests/friendapp/test_settings.py"""
import hashlib
import http.client
import json
import os
import sys
import threading
import unittest
from collections import namedtuple
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from ytt import tools as YT  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/(testkit)
import testkit  # noqa: E402
from friendapp import places as P, server as S, settings as T  # noqa: E402
from test_server import FakeEngine  # noqa: E402

URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
# push_helper の秘密の検査に当たらないよう分けた偽のキー
KEY = "AIza" + "SyA-abcdefghijklmnopqrstuvwxyz012345"
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


class SettingsBase(unittest.TestCase):
    """⚙ と初回の準備の部品を偽物で組む(サーバーは起こさない)"""

    def setUp(self):
        self.tmp = testkit.tempdir(self, "friendset-")
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
                {"name": "whisper.cpp/large-v3", "file": "m.bin", "url": "https://huggingface.co/x/m.bin", "size": len(self.model),
                 "sha256": hashlib.sha256(self.model).hexdigest(), "base": "data", "dest": "transcribe/models", "unzip": None}]}, f)
        self.places = {"home": home, "data": os.path.join(home, "data"), "friend": os.path.join(home, "data", "app", "friendapp"),
                       "outbox": os.path.join(home, "data", "app", "outbox"), "cases": os.path.join(home, "作業"), "fetch": with_fetch}
        self.places["save"] = lambda: S.save_dir(self.places["friend"])
        os.makedirs(self.places["friend"])
        os.makedirs(self.places["cases"])
        self.app = S.FriendApp(self.places, make_engine=FakeEngine)
        self.dl = FakeDl({"https://huggingface.co/x/m.bin": self.model})
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
        # 初回の準備の道具の確かめ(F3-5)は偽物で: 本物の ffmpeg・whisper.cpp を動かさない・machine.json を書かない・環境変数を変えない
        for sub, exe in (("ffmpeg", "ffmpeg.exe"), ("ffmpeg", "ffprobe.exe"), ("yt-dlp", "yt-dlp.exe"), ("deno", "deno.exe")):
            os.makedirs(os.path.join(home, "tools", sub), exist_ok=True)
            open(os.path.join(home, "tools", sub, exe), "wb").close()
        self.cmds = []
        self.app.setup.run = self.fake_run
        self.app.setup.whisper = lambda device, data_root, wav: None
        self.app.setup.set_device = lambda d: None
        self.app.setup.env = {}
        self.app.prepare()
        self.addCleanup(self.stop_setup)

    def fake_run(self, cmd, timeout):
        self.cmds.append(list(cmd))
        if "lavfi" in cmd:
            with open(cmd[-1], "wb") as f:
                f.write(b"RIFF....WAVE")
        return 0, "tool version 1", None

    def stop_setup(self):
        self.app.setup.cancel()
        self.dl.gate.set()
        self.app.setup.wait(5)

    def upd(self, body):
        """Settings.update を直に呼ぶ(processing・live)"""
        try:
            msg = self.app.settings.update(body)["message"]
        except T.SettingsError as e:
            return 400, {"message": str(e)}
        return 200, {"message": msg, "settings": self.app.settings.view()}


class SettingsServerTest(SettingsBase):
    def setUp(self):
        super().setUp()
        self.srv = S.Server(("127.0.0.1", 0), self.app)
        self.app.server = self.srv
        self.port = self.srv.server_address[1]
        self.thread = threading.Thread(target=self.srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
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

    # ---- YouTube のログイン(notes:docs/spec/friend.md の 13-13。cookie は偽物)
    def test_youtube_login_state_and_logout(self):
        cookies = os.path.join(self.places["friend"], "secrets", "youtube-cookies.txt")
        os.environ[YT.COOKIES_ENV] = cookies
        self.assertEqual(self.get("/api/friend/settings")[1]["settings"]["ytLogin"], {"state": "none", "at": 0})
        os.makedirs(os.path.dirname(cookies))
        with open(cookies, "w", encoding="utf-8") as f:
            f.write("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSAPISID\tfake\n")
        y = self.get("/api/friend/settings")[1]["settings"]["ytLogin"]
        self.assertEqual(y["state"], "ok")
        self.assertGreater(y["at"], 0)
        args = YT.ytdlp_auth_args()   # 呼ぶたびの写しを作っておく(ログアウトで一緒に消える)
        self.assertTrue(os.path.isfile(args[1]))
        raw = self.request("GET", "/api/friend/settings")[1]
        self.assertNotIn(b"fake", raw)   # 中身は画面へ出さない
        st, j = self.post("/api/friend/settings", {"ytLogout": True})
        self.assertEqual(st, 200)
        self.assertIn("ログアウトしました", j["message"])
        self.assertFalse(os.path.exists(cookies) or os.path.exists(args[1]))
        self.assertEqual(j["settings"]["ytLogin"]["state"], "none")
        self.assertIn("ログインしていません", self.post("/api/friend/settings", {"ytLogout": True})[1]["message"])

    # ---- 初回の準備(F3-5。準備だけの画面)
    def test_setup_runs_by_itself_then_main_page(self):
        st, j = self.get("/api/friend/setup")
        self.assertEqual(st, 200)
        self.assertTrue(j["done"], j)
        self.assertEqual(j["setup"]["state"], "done")
        self.assertEqual(len(self.after), 1)   # 取ったあとに道具の場所を教え直した
        self.assertTrue(any("lavfi" in c for c in self.cmds))   # 文字起こしを短い音で確かめた(偽物)
        self.assertEqual(self.request("GET", "/friend/")[0], 200)
        st, j = self.post("/api/friend/send", {"url": URL, "top": 3, "title": "題"})
        self.assertEqual(st, 200, j)

    def test_main_page_goes_to_setup_while_preparing(self):
        self.app.setup.flow = "fetching"
        st, j = self.get("/api/friend/state")
        self.assertTrue(j["setup"] and j["awake"])   # 準備中は exe が閉じるときに確かめ・スリープを止める

    def test_setup_needs_token(self):
        st, j = self.post("/api/friend/setup/start", token=False)
        self.assertEqual(st, 403)
        self.assertFalse(self.app.setup.running())

    def test_user_pc_send_not_blocked_by_parts(self):
        """ユーザーの PC に頼む依頼は、この PC の部品が足りなくても送れる(鍵が無いので別の理由で断る)"""
        cur = self.app.api.form()
        cur["pc"] = "user"   # 処理する PC は ⚙ の値(鍵が無いと prefs では変えられないので、前回の値を直に書く)
        self.app.api._write_form(cur)
        st, j = self.post("/api/friend/send", {"url": URL, "top": 3, "title": "題"})
        self.assertEqual(st, 400)
        self.assertIn("Dropbox", j["message"])
        self.assertNotIn("部品", j["message"])
        self.assertEqual(self.app.inbox.rows, [])   # 行を残さない

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

    def test_engine_is_read_only_disk_cut(self):
        """エンジンは見せるだけ(10-23: 自動で選ぶ = test_setup の AutoDeviceTest)。古い画面の engine・fetchCuda は読まない"""
        st, j = self.post("/api/friend/settings", {"engine": "C", "fetchCuda": True, "diskMinGB": 35, "cut": "silence"})
        self.assertEqual(st, 200, j)
        s = j["settings"]
        self.assertEqual((s["engine"], s["diskMinGB"], s["cut"], "cuda" in s), ("A", 35, "silence", False))
        # カットは送るときの束に入る(しない = 入れない = 今までの束のまま)
        st, j = self.post("/api/friend/send", {"url": URL, "top": 3, "title": "題"})
        self.assertEqual(st, 200, j)
        env, diff = self.app.engine.queue.submitted[-1]
        self.assertEqual(diff["pack"]["cut"], "silence")
        self.post("/api/friend/settings", {"cut": "none"})
        self.post("/api/friend/send", {"url": URL, "top": 3, "title": "題"})
        env, diff = self.app.engine.queue.submitted[-1]
        self.assertNotIn("cut", diff.get("pack") or {})

    def test_bad_values_refused(self):
        for body in ({"diskMinGB": -1}, {"diskMinGB": "abc"}, {"cut": "rows"}):
            st, j = self.post("/api/friend/settings", body)
            self.assertEqual(st, 400, body)
        self.assertFalse(os.path.exists(os.environ["YTT_MACHINE_FILE"]))
        # ---- test_bad_values_write_nothing
        for body in ({"processing": "x"},):
            st, j = self.upd(dict(body, cut="silence"))
            self.assertEqual(st, 400, body)
        self.assertEqual(self.app.api.form()["cut"], "none")

    def test_processing_live_view_and_update(self):
        st, j = self.get("/api/friend/settings")
        s = j["settings"]
        self.assertEqual((s["processing"], s["canRemote"], "weights" in s), ("local", False, False))   # 解析の重みは 10-23 に消した
        self.assertEqual(("live" in s, "liveSensOptions" in s), (False, False))   # ライブの感度・待ち・余白は 10-30 に外した
        self.assertNotIn("oldApp", s)
        st, j = self.upd({"weights": {"wAudio": 3, "wChat": 0, "wComments": 1}, "live": {"sens": "max", "waitMin": 0, "pad": 9}})   # 古い画面が送っても読まない(断らない)
        self.assertEqual(st, 200, j)
        s = j["settings"]
        self.assertEqual(("live" in s, "weights" in s), (False, False))   # 重みも読まない
        form = self.app.api.form()   # 送る係が読む form.json は固定の値
        self.assertEqual((form["live"]["sens"], form["live"]["pad"], form["live"]["perHour"], "weights" in form), ("low", 2.0, 6, False))

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
        # 消す → "" を書く(次の起動でもキーは入らない)
        st, j = self.post("/api/friend/settings/key", {"key": ""})
        self.assertFalse(j["settings"]["apiKey"])
        self.assertNotIn("YTT_YT_API_KEY", os.environ)
        env = {}
        self.assertFalse(P.api_key_env(self.places["data"], env))
        self.assertEqual(env, {})

    def test_api_key_bad(self):
        self.app.settings.probe = lambda key: (400, json.dumps({"error": {"errors": [{"reason": "keyInvalid"}]}}))
        st, j = self.post("/api/friend/settings/key", {"key": KEY})
        self.assertEqual(st, 400)
        self.assertIn("キーが違います", j["message"])
        self.assertFalse(os.path.exists(os.path.join(self.places["data"], "app", "keys.json")))
        st, j = self.post("/api/friend/settings/key", {"key": "short"})
        self.assertIn("形が違います", j["message"])

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
        # ---- test_pick_folder_bad_path
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


class SettingsApiTest(SettingsBase):
    """Settings.update を直に呼ぶ(サーバーを起こさない)"""

    def test_processing_remote_needs_dropbox_key(self):
        st, j = self.upd({"processing": "remote"})
        self.assertEqual(st, 400)
        self.assertIn("Dropbox の鍵", j["message"])
        self.assertEqual(self.app.api.form()["pc"], "this")
        self.app.sync.has_key = lambda: True
        st, j = self.upd({"processing": "remote"})
        self.assertEqual(st, 200, j)
        self.assertEqual((j["settings"]["processing"], j["settings"]["canRemote"], self.app.api.form()["pc"]), ("remote", True, "user"))
        st, j = self.upd({"processing": "local"})
        self.assertEqual(j["settings"]["processing"], "local")


class JudgeTest(unittest.TestCase):
    def test_judge_messages(self):
        self.assertEqual(T.judge(200, ""), (True, "使えます"))
        self.assertIn("つながりません", T.judge(0, "URLError")[1])
        self.assertIn("有効", T.judge(403, json.dumps({"error": {"errors": [{"reason": "accessNotConfigured"}]}}))[1])
        self.assertIn("上限", T.judge(403, json.dumps({"error": {"errors": [{"reason": "quotaExceeded"}]}}))[1])
        self.assertIn("HTTP 500", T.judge(500, "x")[1])


if __name__ == "__main__":
    unittest.main()
