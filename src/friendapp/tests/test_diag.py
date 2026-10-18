"""src/friendapp/diag.py(診断の記録)と、同期が /診断/ へ上げて 3 日で消す所・道具の記録 ytt/tools.remember のテスト。
本物の Dropbox・GPU の調べ・道具は動かさない(偽の io・gpu_fn・一時フォルダ)。リポジトリ直下で: py -3.10 -m unittest src/friendapp/tests/test_diag.py"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from friendapp import diag as G, inbox as I, sync as S  # noqa: E402
from friendapp.tests.test_sync import FakeIo  # noqa: E402
from ytt import tools as T  # noqa: E402

RID = "20261018-100000-abcdef"
NOW = float(int(time.time()))
ENV = {"USERPROFILE": r"C:\Users\taro", "USERNAME": "taro", "YTT_FRIEND_TOKEN": "f" * 48, "YTT_FRIEND_HOST": "webview2"}


class FakeRun:
    def __init__(self, state="done", error=""):
        t = int(NOW * 1000) - 600000
        self.id, self.request_id, self.state, self.error = "run1", RID, state, error
        self.steps = [{"key": "normalize", "startedAt": t, "finishedAt": t + 120000, "state": "done", "detail": r"C:\Users\taro\Videos\a.mp4 を写しました"},
                      {"key": "transcribe", "startedAt": t + 120000, "finishedAt": t + 420000, "state": "error" if error else "done", "detail": ""},
                      {"key": "pack", "startedAt": None, "finishedAt": None, "state": "pending"}]

    def all_packs(self):
        return ["p1", "p2"]


class MaskTest(unittest.TestCase):
    def test_paths_and_secrets(self):
        home = r"D:\友人\FriendApp"
        s = (r"C:\Users\taro\AppData\x.log と c:/users/taro/Videos と D:\友人\FriendApp\data と C:\Users\hanako\y と taro さん "
             "token=" + "f" * 48 + " AIza" + "x" * 35 + " sl.ABCDEFGHIJKLMNOPQRSTUVWX refresh_token: abc123")
        got = G.mask(s, home, ENV)
        for bad in ("taro", "hanako", "f" * 48, "AIza", "sl.ABC", "abc123", "友人"):
            self.assertNotIn(bad, got)
        self.assertIn("<user>", got)
        self.assertIn(r"<app>\data", got)
        self.assertIn(r"C:\Users\<user>\y", got)

    def test_short_username_kept(self):
        self.assertEqual(G.mask("ab cd", None, {"USERNAME": "ab"}), "ab cd")   # 2 字以下の名前は伏せない(普通の語を壊す)


class DiagTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="frienddiag-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.t = [NOW]
        self.places = {"home": os.path.join(self.tmp, "home"), "data": os.path.join(self.tmp, "data"),
                       "friend": os.path.join(self.tmp, "data", "app", "friendapp"), "outbox": os.path.join(self.tmp, "data", "app", "outbox"),
                       "cases": os.path.join(self.tmp, "作業"), "save": lambda: os.path.join(self.tmp, "save")}
        for k in ("home", "friend", "cases"):
            os.makedirs(self.places[k], exist_ok=True)
        self.gpu_calls = []
        self.d = G.Diag(self.places, clock=lambda: self.t[0], env=dict(ENV), device_fn=lambda: "cuda",
                        gpu_fn=lambda: self.gpu_calls.append(1) or {"name": "NVIDIA GeForce RTX 3060", "vendor": "nvidia", "vramGB": 12.0, "x": 1})

    def files(self):
        return sorted(n for n in os.listdir(self.places["outbox"]) if G.NAME_RE.match(n))

    def read(self, name):
        with open(os.path.join(self.places["outbox"], name), encoding="utf-8") as f:
            return json.load(f)

    def test_run_record(self):
        T.RECENT.clear()
        T.remember([r"C:\Users\taro\tools\yt-dlp.exe", "--secret-arg"], 1, [b"ERROR: Sign in to confirm you're not a bot", b"C:\\Users\\taro\\x"], None,
                   time.monotonic() - 3)
        T.RECENT[-1]["at"] = int(NOW * 1000) - 300000
        T.remember(["ffmpeg"], 0, [b"ok"], None, time.monotonic())
        T.RECENT[-1]["at"] = int(NOW * 1000) - 200000
        path = self.d.run(FakeRun("error", "yt-dlp が失敗しました: Sign in to confirm you're not a bot\n" + r"C:\Users\taro\a"),
                          {"id": RID, "kind": "url", "pc": "this", "form": {"ranges": [[1, 2]], "videoId": "dQw4w9WgXcQ"}},
                          [{"device": "cuda", "backend": "CUDA", "gpu": "RTX 3060", "model": "large", "audioSec": 600.0, "wallSec": 60.0}])
        self.assertEqual(os.path.basename(path), "%s__diag-%013d.diag.json" % (RID, int(NOW * 1000)))
        d = self.read(os.path.basename(path))
        self.assertEqual((d["v"], d["kind"], d["source"], d["requestId"], d["code"]), (1, "run", "python", RID, "bot"))
        self.assertEqual(d["pc"]["gpu"], {"name": "NVIDIA GeForce RTX 3060", "vendor": "nvidia", "vramGB": 12.0})
        self.assertEqual(d["pc"]["device"], "cuda")
        self.assertTrue(d["pc"]["windows"])
        self.assertEqual(d["app"]["host"], "webview2")
        self.assertEqual([(s["key"], s["label"], s["sec"]) for s in d["stages"]], [("normalize", "動画を取得", 120.0), ("transcribe", "文字起こし", 300.0)])
        self.assertEqual(d["totalSec"], 420.0)
        self.assertEqual(d["transcribe"][0]["ratio"], 0.1)
        self.assertEqual(d["request"]["ranges"], 1)
        self.assertEqual([(t["name"], t["code"]) for t in d["tools"]], [("yt-dlp", 1), ("ffmpeg", 0)])
        self.assertEqual(d["tools"][1]["tail"], [])   # うまくいった道具の行は持たない
        text = json.dumps(d, ensure_ascii=False)
        self.assertNotIn("taro", text)
        self.assertNotIn("--secret-arg", text)   # 道具の引数は持たない

    def test_no_gpu_lookup_without_host(self):
        d = G.Diag(self.places, clock=lambda: self.t[0], env={})
        self.assertIsNone(d.pc()["gpu"])
        self.assertEqual(d.host, "browser")

    def test_same_ms_gets_next_name_and_once(self):
        a = self.d.write("error", rid="bad id!", summary="x")
        b = self.d.write("error", summary="y")
        self.assertNotEqual(a, b)
        self.assertTrue(os.path.basename(a).startswith("app__diag-"))
        self.assertIsNotNone(self.d.once("k", 60, "sync", summary="s"))
        self.assertIsNone(self.d.once("k", 60, "sync", summary="s"))
        self.t[0] += 61
        self.assertIsNotNone(self.d.once("k", 60, "sync", summary="s"))

    def test_classify_code_for_errors(self):
        p = self.d.write("error", summary="ネットにつながりません timed out")
        self.assertEqual(self.read(os.path.basename(p))["code"], "net")

    def test_switch_off_and_maker_pc(self):
        self.d.env[G.SWITCH_ENV] = "0"
        self.assertIsNone(self.d.write("error", summary="x"))
        del self.d.env[G.SWITCH_ENV]
        os.makedirs(os.path.join(self.places["data"], "app"), exist_ok=True)
        with open(os.path.join(self.places["data"], "app", "prefs.json"), "w", encoding="utf-8") as f:
            json.dump({"intake": {"folder": "D:/Dropbox/Apps/x"}}, f)
        self.assertIsNone(self.d.write("error", summary="x"))   # ユーザーの PC の作業データでは書かない
        self.assertFalse(os.path.isdir(self.places["outbox"]) and self.files())

    def test_local_prune_3_days(self):
        os.makedirs(self.places["outbox"])
        old = "launcher__diag-%013d.diag.json" % (int(NOW * 1000) - 3 * 86400 * 1000 - 1)
        young = "launcher__diag-%013d.diag.json" % (int(NOW * 1000) - 86400 * 1000)
        for n in (old, young, "%s__x.verdict.json" % RID):
            with open(os.path.join(self.places["outbox"], n), "w") as f:
                f.write("{}")
        self.d.write("error", summary="x")
        left = os.listdir(self.places["outbox"])
        self.assertNotIn(old, left)
        self.assertIn(young, left)
        self.assertIn("%s__x.verdict.json" % RID, left)   # 診断でない物は触らない

    def test_too_big_is_trimmed(self):
        p = self.d.write("error", summary="x", detail="y" * 10000, stages=[{"detail": "z" * 300}] * 1000)
        self.assertLessEqual(os.path.getsize(p), G.MAX_BYTES)
        with open(p, encoding="utf-8") as f:
            json.load(f)

    def test_prune_names(self):
        now = int(NOW * 1000)
        names = ["a__diag-%013d.diag.json" % (now - 3 * 86400 * 1000), "a__diag-%013d.diag.json" % (now - 1000), "x.txt", None]
        self.assertEqual(G.prune_names(names, now), [names[0]])


class SyncDiagTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="frienddiagsync-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.t = [NOW]
        self.places = {"home": os.path.join(self.tmp, "home"), "data": os.path.join(self.tmp, "data"),
                       "friend": os.path.join(self.tmp, "data", "app", "friendapp"), "outbox": os.path.join(self.tmp, "data", "app", "outbox"),
                       "cases": os.path.join(self.tmp, "作業"), "save": lambda: os.path.join(self.tmp, "save")}
        for k in ("home", "friend", "cases", "outbox"):
            os.makedirs(self.places[k], exist_ok=True)
        box = I.Inbox(os.path.join(self.places["friend"], "inbox.json"), self.places["outbox"], self.places["save"], lambda: self.places["cases"],
                      clock=lambda: self.t[0])
        self.io = FakeIo(lambda: self.t[0])
        self.sync = S.Sync(self.places, box, lambda: {}, client_factory=lambda cfg, c: self.io, clock=lambda: self.t[0], env={}, version="0.90.0")
        self.sync.diag = G.Diag(self.places, clock=lambda: self.t[0], env={})

    def test_diag_goes_to_diag_folder_and_old_are_pruned(self):
        now = int(NOW * 1000)
        mine = "launcher__diag-%013d.diag.json" % now
        with open(os.path.join(self.places["outbox"], mine), "w") as f:
            f.write("{}")
        old = "/診断/%s__diag-%013d.diag.json" % (RID, now - 4 * 86400 * 1000)
        self.io.put(old, b"{}")
        self.io.put("/診断/メモ.txt", b"x", age=10 * 86400)
        self.sync._returns(self.io)
        self.assertEqual(self.io.data("/診断/" + mine), b"{}")
        self.assertIsNone(self.io.data("/送り返し/" + mine))
        self.assertIsNone(self.io.data(old))
        self.assertEqual(self.io.data("/診断/メモ.txt"), b"x")   # 診断の名前でない物は消さない
        self.assertEqual(os.listdir(self.places["outbox"]), [])
        self.io.put(old, b"{}")
        self.sync._returns(self.io)
        self.assertEqual(self.io.data(old), b"{}")   # 次に消すのは DIAG_PRUNE_EVERY 秒あと
        self.t[0] += S.DIAG_PRUNE_EVERY
        self.sync._returns(self.io)
        self.assertIsNone(self.io.data(old))

    def test_sync_error_written_once(self):
        def boom(io):
            raise S.SyncError("つながりません timed out")
        self.sync.config = lambda: object()
        self.sync._requests = boom
        self.sync.run_once()
        self.sync.run_once()
        got = [f["data"] for k, f in self.io.files.items() if k.startswith("/診断/")]   # 同じ回の送り返しで /診断/ へ上がる
        self.assertEqual(len(got), 1)
        d = json.loads(got[0].decode("utf-8"))
        self.assertEqual((d["kind"], d["stage"], d["code"]), ("sync", "ユーザーの PC への依頼", "net"))


class ToolsRememberTest(unittest.TestCase):
    def test_run_records_exit_code(self):
        T.RECENT.clear()
        r = T.run([sys.executable, "-c", "import sys; sys.stderr.write('a\\nb\\n'); sys.exit(3)"])
        self.assertEqual(r.code, 3)
        got = T.recent(0)[-1]
        self.assertEqual((got["name"].lower().startswith("python"), got["code"], got["tail"]), (True, 3, ["a", "b"]))

    def test_progress_records(self):
        T.RECENT.clear()
        code, _lines, _why = T.run_progress([sys.executable, "-c", "print('x')"])
        self.assertEqual(code, 0)
        self.assertEqual(T.recent(0)[-1]["tail"], [])


if __name__ == "__main__":
    unittest.main()
