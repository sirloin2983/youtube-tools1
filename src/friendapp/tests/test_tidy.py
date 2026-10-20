# -*- coding: utf-8 -*-
"""フォルダの整理(friendapp/tidy.py)のテスト。一時フォルダに見本のアプリのフォルダを作る(本物の友人のフォルダ・作業データには触らない)。
許可の一覧に載る形の物だけが候補・載らない物は「分からない」・黙る / 聞くの振り分け・触らない物・ごみ箱と記録・新しい版のあとの 1 回の条件"""
import json
import os
import subprocess
import sys
import time
import unittest

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if SRC not in sys.path:
    sys.path.insert(0, SRC)
os.environ.setdefault("YTT_DATA_DIR", "inplace")

from ytt.tests import testkit  # noqa: E402
from friendapp import tidy as T  # noqa: E402

OLD = time.time() - 10 * 86400


def put(path, data=b"x", old=True):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    if old:
        os.utime(path, (OLD, OLD))
    return path


def age(path):
    """フォルダの中を全部古くする"""
    for root, dirs, files in os.walk(path):
        for f in files:
            os.utime(os.path.join(root, f), (OLD, OLD))
    os.utime(path, (OLD, OLD))


class FakeInbox:
    def __init__(self, path, rows):
        self.path, self.rows = path, rows
        testkit.write_json(path, {"rows": rows})

    def view(self):
        return [r for r in self.rows if r.get("state") != "done"]


class FakeQueue:
    def __init__(self):
        self.idle = True
        self.runs = []

    def status(self):
        return {"idle": self.idle, "runs": self.runs}

    def history(self, limit=None):
        return {"runs": []}


class FakeSetup:
    def __init__(self, data):
        self.data, self.done = data, True

    def awake(self):
        return False

    def items(self):
        return [{"name": "whisper.cpp/large-v3", "file": "ggml-large-v3.bin", "base": "data", "dest": "transcribe/models/whispercpp", "unzip": None},
                {"name": "ffmpeg", "file": "ffmpeg.zip", "base": "app", "dest": "tools/ffmpeg", "unzip": "zip"}]

    def missing(self):
        return []


class FakeSync:
    def __init__(self):
        self.is_busy = False

    def busy(self):
        return self.is_busy

    def status(self):
        return {"at": 1}

    def has_key(self):
        return True


class TidyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "friendtidy-")
        h = self.home = os.path.join(self.tmp, "home")
        self.data = os.path.join(h, "data")
        self.cases = os.path.join(h, "作業")
        self.friend = os.path.join(self.data, "app", "friendapp")
        os.makedirs(self.friend)
        os.makedirs(self.cases)
        # 版のフォルダ: current 0.1.0・previous 0.0.9・古い 0.0.5(exe の消し損ね)・bad 0.0.7
        for v in ("0.1.0", "0.0.9", "0.0.5", "0.0.7"):
            put(os.path.join(h, "app-" + v, "src", "friendapp", "server.py"))
            put(os.path.join(h, "app-" + v, "python", "python.exe"))
        testkit.write_json(os.path.join(h, "app-versions.json"), {"v": 1, "current": "0.1.0", "previous": "0.0.9", "bad": ["0.0.7"]})
        put(os.path.join(h, "FriendApp.exe.old"))
        put(os.path.join(h, "app-0.0.8.tmp", "a.txt"))
        age(os.path.join(h, "app-0.0.8.tmp"))
        put(os.path.join(h, "config.json"), b"{}")
        put(os.path.join(h, "mystuff.txt"))            # 分からない物
        put(os.path.join(h, "src", "ytt", "version.py"), b'VERSION = "0.0.3"\n')   # 前の形(previous より古い)
        put(os.path.join(h, "python", "python.exe"))
        # 作業データ
        put(os.path.join(self.friend, "logs", "friendapp.log.1"))
        put(os.path.join(self.friend, "logs", "friendapp.log"))          # 動いているログは触らない
        put(os.path.join(self.data, "learning", "20261001-000000-0000aaaa.part", "x.json"))
        age(os.path.join(self.data, "learning", "20261001-000000-0000aaaa.part"))
        put(os.path.join(self.data, "learning", "20261001-000000-0000bbbb", "learning.json"))   # 学習の束は触らない
        # モデルと道具
        put(os.path.join(self.data, "transcribe", "models", "whispercpp", "ggml-large-v3.bin"))
        put(os.path.join(self.data, "transcribe", "models", "whispercpp", "ggml-old.bin"), b"o" * 50)
        put(os.path.join(self.data, "transcribe", "models", "whispercpp", "ggml-fresh.bin"), old=False)
        put(os.path.join(h, "tools", "ffmpeg", "ffmpeg.exe"))
        put(os.path.join(h, "tools", "oldtool", "old.exe"))
        age(os.path.join(h, "tools", "oldtool"))
        # 一時保管の作業のフォルダ
        self.orphan = os.path.join(self.cases, "古い配信")
        put(os.path.join(self.orphan, "作業用", "case.json"), b'{"requestId": "x-none"}')
        put(os.path.join(self.orphan, "clip.mp4"), b"v" * 100)
        age(self.orphan)
        self.used = os.path.join(self.cases, "使っている配信")
        put(os.path.join(self.used, "作業用", "case.json"), b"{}")
        age(self.used)
        put(os.path.join(self.cases, "依頼", "req-old", "作業用", ".studio-id"), b"x")
        age(os.path.join(self.cases, "依頼", "req-old"))
        put(os.path.join(self.cases, "友人の物", "a.txt"))   # 印が無い = 分からない
        put(os.path.join(self.cases, "ライブの録画", "rec1", "a.ts"))
        put(os.path.join(self.cases, "ごみ箱", "20261001", "x.bin"))
        put(os.path.join(self.cases, "新しい配信", "作業用", "case.json"), b"{}", old=False)   # 3 日の中
        self.inbox = FakeInbox(os.path.join(self.friend, "inbox.json"), [{"id": "r1", "state": "done", "case": self.used}])
        self.queue = FakeQueue()
        self.setup = FakeSetup(self.data)
        self.sync = FakeSync()
        self.places = {"home": h, "data": self.data, "friend": self.friend, "cases": self.cases}
        self.env = {"YTT_FRIEND_LAUNCHER": "1"}
        self.t = self.tidy()

    def tidy(self, **kw):
        kw = dict(dict(queue_fn=lambda: self.queue, setup=self.setup, sync=self.sync, version="0.1.0", env=self.env), **kw)
        return T.Tidy(self.places, self.inbox, **kw)

    def kinds(self, got):
        return {(it["kind"], os.path.relpath(it["path"], self.home)) for it in got["items"]}

    def test_scan_finds_only_allowed_forms(self):
        got = self.t.scan()
        k = self.kinds(got)
        for want in [("old-exe", "FriendApp.exe.old"), ("update-leftover", "app-0.0.8.tmp"), ("old-version", "app-0.0.5"),
                     ("legacy", "src"), ("legacy", "python"), ("old-log", os.path.join("data", "app", "friendapp", "logs", "friendapp.log.1")),
                     ("learning-part", os.path.join("data", "learning", "20261001-000000-0000aaaa.part")),
                     ("orphan-case", os.path.join("作業", "古い配信")), ("orphan-case", os.path.join("作業", "依頼", "req-old")),
                     ("unused-model", os.path.join("data", "transcribe", "models", "whispercpp", "ggml-old.bin")),
                     ("unused-tool", os.path.join("tools", "oldtool"))]:
            self.assertIn(want, k)
        paths = {p for _k, p in k}
        for never in ("app-0.1.0", "app-0.0.9", "app-0.0.7", "config.json", "mystuff.txt", os.path.join("作業", "使っている配信"),
                      os.path.join("作業", "友人の物"), os.path.join("作業", "ライブの録画"), os.path.join("作業", "ごみ箱"),
                      os.path.join("作業", "新しい配信"), os.path.join("tools", "ffmpeg"),
                      os.path.join("data", "transcribe", "models", "whispercpp", "ggml-large-v3.bin"),
                      os.path.join("data", "transcribe", "models", "whispercpp", "ggml-fresh.bin"),
                      os.path.join("data", "app", "friendapp", "logs", "friendapp.log"),
                      os.path.join("data", "learning", "20261001-000000-0000bbbb")):
            self.assertNotIn(never, paths, never)
        names = {n for n, _s in got["unknown"]}
        self.assertIn("mystuff.txt", names)
        self.assertIn("友人の物", names)
        modes = {it["kind"]: it["mode"] for it in got["items"]}
        self.assertEqual((modes["old-exe"], modes["update-leftover"], modes["old-log"], modes["learning-part"]), ("auto",) * 4)
        self.assertEqual((modes["legacy"], modes["orphan-case"], modes["unused-model"], modes["unused-tool"]), ("ask",) * 4)

    def test_scan_has_no_side_effects(self):
        before = sorted(os.path.relpath(os.path.join(r, f), self.tmp) for r, _d, fs in os.walk(self.tmp) for f in fs)
        self.t.scan()
        after = sorted(os.path.relpath(os.path.join(r, f), self.tmp) for r, _d, fs in os.walk(self.tmp) for f in fs)
        self.assertEqual(before, after)

    def test_case_found_by_request_id_or_queue_is_kept(self):
        self.inbox = FakeInbox(self.inbox.path, [{"id": "x-none", "state": "done"}])
        self.assertNotIn(("orphan-case", os.path.join("作業", "古い配信")), self.kinds(self.tidy().scan()))   # case.json の requestId が受信箱にある
        self.queue.runs = [{"state": "queued", "resultPath": os.path.join(self.cases, "依頼", "req-old", "clip.mp4")}]
        self.assertNotIn(("orphan-case", os.path.join("作業", "依頼", "req-old")), self.kinds(self.t.scan()))   # 待ち行列が指している

    def test_models_only_when_setup_complete(self):
        self.setup.missing = lambda: [{"name": "x"}]
        self.assertFalse([it for it in self.t.scan()["items"] if it["kind"] in ("unused-model", "unused-tool")])
        self.setup.missing = lambda: []
        testkit.write_json(os.path.join(self.friend, "setup.json"), {"model": "ggml-old.bin"})   # 設定に名前がある = 手で選んだ物
        self.assertFalse([it for it in self.t.scan()["items"] if it["kind"] == "unused-model"])

    def test_junction_is_never_followed(self):
        target = os.path.join(self.tmp, "outside")
        put(os.path.join(target, "important.bin"))
        link = os.path.join(self.cases, "リンク")
        r = subprocess.run(["cmd", "/c", "mklink", "/J", link, target], capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode != 0:
            self.skipTest("接合点を作れない")
        put(os.path.join(self.orphan, "inner", "x.bin"))
        inner = os.path.join(self.orphan, "inner", "j")
        subprocess.run(["cmd", "/c", "mklink", "/J", inner, target], capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        age(self.orphan)
        got = self.t.scan()
        paths = {it["path"] for it in got["items"]}
        self.assertNotIn(link, paths)
        self.assertNotIn(self.orphan, paths)   # 中に接合点がある = その物ごと触らない
        self.t.items = got["items"]
        self.t.apply([it for it in got["items"] if it["mode"] == "ask"])
        self.assertTrue(os.path.isfile(os.path.join(target, "important.bin")))

    def test_apply_moves_to_trash_with_manifest_and_deletes_auto(self):
        got = self.t.scan()
        res = self.t.apply(got["items"])
        self.assertFalse(res["failed"], res)
        self.assertFalse(os.path.exists(os.path.join(self.home, "FriendApp.exe.old")))   # 直接消す
        self.assertFalse(os.path.exists(self.orphan))
        day = [n for n in os.listdir(os.path.join(self.cases, "ごみ箱")) if n != "20261001"][0]
        self.assertTrue(os.path.isfile(os.path.join(self.cases, "ごみ箱", day, "整理", "orphan-case", "古い配信", "clip.mp4")))   # 同じドライブのごみ箱へ
        with open(os.path.join(self.cases, "ごみ箱", day, "manifest.jsonl"), encoding="utf-8") as f:
            rows = [json.loads(x) for x in f]
        self.assertIn(self.orphan, [r["from"] for r in rows])
        self.assertTrue(os.path.isdir(os.path.join(self.home, "app-0.1.0")) and os.path.isfile(os.path.join(self.home, "config.json")))
        self.assertTrue(os.path.isfile(os.path.join(self.home, "mystuff.txt")))
        self.assertTrue(os.path.isdir(self.used) and os.path.isdir(os.path.join(self.cases, "ライブの録画")))

    def test_apply_skips_what_cannot_move(self):
        def stuck(a, b):
            raise PermissionError("使用中")
        t = self.tidy(move=stuck)
        got = t.scan()
        res = t.apply(got["items"])
        self.assertTrue(res["failed"])
        self.assertTrue(os.path.isdir(self.orphan))   # 動かせなかった物は残る
        self.assertFalse(os.path.exists(os.path.join(self.home, "FriendApp.exe.old")))   # ほかは続ける

    def test_big_auto_is_asked(self):
        put(os.path.join(self.home, "FriendApp.exe.old"), b"x" * 10)
        orig = T.AUTO_MAX
        T.AUTO_MAX = 5
        self.addCleanup(setattr, T, "AUTO_MAX", orig)
        modes = {it["kind"]: it["mode"] for it in self.t.scan()["items"]}
        self.assertEqual(modes["old-exe"], "ask")

    def test_blocked_while_working(self):
        self.queue.idle = False
        self.assertIn("作っている", self.t.blocked())
        self.queue.idle = True
        self.inbox.rows.append({"id": "r2", "state": "making"})
        self.assertIsNotNone(self.t.blocked())
        self.inbox.rows.pop()
        self.sync.is_busy = True
        self.assertIsNotNone(self.t.blocked())
        self.sync.is_busy = False
        self.assertIsNone(self.t.blocked())

    def test_auto_once_per_version_after_update(self):
        self.t.started -= 1000
        self.assertTrue(self.t.maybe_auto())
        self.t.wait(10)
        self.assertFalse(os.path.exists(os.path.join(self.home, "FriendApp.exe.old")))   # 黙る側は片付いた
        self.assertTrue(os.path.isdir(self.orphan))                                      # 聞く側は残る
        v = self.t.view()
        self.assertTrue(v["ask"] and v["askCount"] >= 4)
        self.assertEqual(v["autoDone"]["count"] >= 4, True)
        self.assertFalse(self.t.maybe_auto())   # 同じ版ではもう走らない
        self.t.later()
        self.assertFalse(self.t.view()["ask"])
        with open(os.path.join(self.friend, T.STATE_NAME), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["version"], "0.1.0")

    def test_auto_waits_for_conditions(self):
        self.t.started -= 1000
        for why, kw in (("exe から動いていない", {"env": {}}), ("戻した版", {"env": dict(self.env, YTT_FRIEND_ROLLBACK="0.2.0")}),
                        ("current でない版", {"version": "0.0.9"})):
            t = self.tidy(**kw)
            t.started -= 1000
            self.assertFalse(t.maybe_auto(), why)
        self.assertFalse(self.tidy().maybe_auto())   # 起動したばかり
        self.queue.idle = False
        self.assertFalse(self.t.maybe_auto())   # 作業中
        self.queue.idle = True
        self.setup.done = False
        self.assertFalse(self.t.maybe_auto())   # 準備が済んでいない

    def test_home_trash_purged_after_3_days(self):
        put(os.path.join(self.home, "ごみ箱", "20200101", "x.bin"))
        put(os.path.join(self.home, "ごみ箱", time.strftime("%Y%m%d"), "y.bin"))
        self.t.purge_home_trash()
        self.assertFalse(os.path.exists(os.path.join(self.home, "ごみ箱", "20200101")))
        self.assertTrue(os.path.exists(os.path.join(self.home, "ごみ箱", time.strftime("%Y%m%d"))))


if __name__ == "__main__":
    unittest.main()
