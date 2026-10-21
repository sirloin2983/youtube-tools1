# -*- coding: utf-8 -*-
"""配る前の検査(dev/friend_preflight.py・dev/friend_preflight_shim.py)と、build_friend_zip.py --publish の関所のテスト。
本物の exe・ネット・Dropbox は使わない(通信の差し替えは一時フォルダ・publish は build と検査を差し替える)。
実行(リポジトリ直下): py -3.12 -m unittest tests/dev/test_friend_preflight.py"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 全テストの決まり(作業データに触らない)
import json
import sys
import unittest
import urllib.error
import urllib.request
import zipfile
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
DEV = os.path.join(os.path.dirname(os.path.dirname(TESTS)), "dev")
sys.path.insert(0, DEV)
sys.path.insert(0, os.path.join(os.path.dirname(DEV), "src"))
import build_friend_zip as B  # noqa: E402
import friend_preflight as P  # noqa: E402
import friend_preflight_shim as S  # noqa: E402  YTT_PREFLIGHT_SHIM が無ければ何も差し替えない
from friendapp import dropbox as DBX  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/(testkit)
import testkit  # noqa: E402


class ShimTest(unittest.TestCase):
    """urllib の https を差し替えた形で、取得(Range)・Dropbox の API・断る、が本物の呼び手(friendapp/dropbox.Client)から動く"""

    def setUp(self):
        self.tmp = testkit.tempdir(self, "pf-shim-")
        self.src = os.path.join(self.tmp, "tool.zip")
        with open(self.src, "wb") as f:
            f.write(b"0123456789" * 100)
        self.box = os.path.join(self.tmp, "dropbox")
        os.makedirs(os.path.join(self.box, "出力"))
        self.log = os.path.join(self.tmp, "net.log")
        self.shim = S._Shim({"mirror": {"https://example.invalid/tool.zip": self.src}, "dropbox": self.box, "log": self.log})
        orig = urllib.request.HTTPSHandler.https_open
        shim = self.shim
        urllib.request.HTTPSHandler.https_open = lambda h, req: shim.https(req)
        self.addCleanup(setattr, urllib.request.HTTPSHandler, "https_open", orig)

    def test_mirror_and_range(self):
        with urllib.request.urlopen("https://example.invalid/tool.zip") as r:
            self.assertEqual(r.status, 200)
            self.assertEqual(len(r.read()), 1000)
        req = urllib.request.Request("https://example.invalid/tool.zip", headers={"Range": "bytes=990-"})
        with urllib.request.urlopen(req) as r:
            self.assertEqual(r.status, 206)
            self.assertEqual(r.read(), b"0123456789")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(urllib.request.Request("https://example.invalid/tool.zip", headers={"Range": "bytes=1000-"}))
        self.assertEqual(cm.exception.code, 416)

    def test_other_net_is_blocked_and_logged(self):
        with self.assertRaises(urllib.error.URLError):
            urllib.request.urlopen("https://www.youtube.com/feeds/videos.xml?channel_id=x")
        with open(self.log, encoding="utf-8") as f:
            self.assertIn("blocked", f.read())

    def test_dropbox_client_round_trip(self):
        c = DBX.Client(DBX.Config("k", "t"), sleep=lambda s: None)
        self.assertIsNone(c.list_folder("/無い"))
        self.assertEqual(c.upload_bytes(b"abc", "/送り返し/a.verdict.json"), "a.verdict.json")
        self.assertEqual(c.upload_bytes(b"xyz", "/送り返し/a.verdict.json"), "a.verdict (1).json")   # add は同じ名前を避ける(Dropbox と同じく最後の拡張子の前に (1))
        names = sorted(e["name"] for e in c.list_folder("/送り返し"))
        self.assertEqual(names, ["a.verdict (1).json", "a.verdict.json"])
        self.assertEqual(c.read_small("/送り返し/a.verdict.json"), (b"abc", False))
        part = os.path.join(self.tmp, "got.part")
        self.assertTrue(c.download("/送り返し/a.verdict.json", part))
        with open(part, "rb") as f:
            self.assertEqual(f.read(), b"abc")
        self.assertTrue(c.delete("/送り返し/a.verdict.json"))
        self.assertFalse(c.delete("/送り返し/a.verdict.json"))
        self.assertIsNone(c.get_metadata("/送り返し/a.verdict.json"))
        meta = c.get_metadata("/送り返し/a.verdict (1).json")
        self.assertEqual(meta["content_hash"], DBX.content_hash(os.path.join(self.box, "送り返し", "a.verdict (1).json")))

    def test_upload_session(self):
        big = os.path.join(self.tmp, "big.bin")
        with open(big, "wb") as f:
            f.write(os.urandom(1000))
        c = DBX.Client(DBX.Config("k", "t"), sleep=lambda s: None)
        with mock.patch.object(DBX, "SINGLE_LIMIT", 100), mock.patch.object(DBX, "CHUNK", 300):
            self.assertEqual(c.upload(big, "/学習/big.bin"), "big.bin")
        with open(big, "rb") as a, open(os.path.join(self.box, "学習", "big.bin"), "rb") as b:
            self.assertEqual(a.read(), b.read())

    def test_paths_cannot_leave_the_folder(self):
        c = DBX.Client(DBX.Config("k", "t"), sleep=lambda s: None)
        with self.assertRaises(Exception):
            c.upload_bytes(b"x", "/../外.txt")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "外.txt")))


class ToolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "pf-tool-")

    def test_friend_env_has_no_dev_things(self):
        with mock.patch.dict(os.environ, {"YTT_DATA_DIR": "x", "PYTHONPATH": "y", "PATH": r"C:\Python310;C:\ffmpeg\bin;C:\Windows\System32"}):
            env = P.friend_env(self.tmp, 9222, "shim.json")
        self.assertFalse([k for k in env if k.startswith("YTT_") and k not in ("YTT_FRIEND_SHOTS", "YTT_FRIEND_SHOT_STEPS", P.SHIM_ENV)])
        self.assertNotIn("PYTHONPATH", env)
        self.assertNotIn("Python310", env["PATH"])
        self.assertNotIn("ffmpeg", env["PATH"].lower())
        self.assertTrue(env["USERPROFILE"].startswith(self.tmp) and env["LOCALAPPDATA"].startswith(self.tmp) and env["TEMP"].startswith(self.tmp))
        self.assertEqual(env[P.SHIM_ENV], "shim.json")
        self.assertIn("--remote-debugging-port=9222", env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"])

    def test_break_removes_the_row(self):
        with open(os.path.join(self.tmp, "fetch.json"), "w", encoding="utf-8") as f:
            json.dump({"items": [{"name": "ffmpeg"}, {"name": "deno"}]}, f)
        P.break_fetch(self.tmp, "ffmpeg")
        with open(os.path.join(self.tmp, "fetch.json"), encoding="utf-8") as f:
            self.assertEqual([i["name"] for i in json.load(f)["items"]], ["deno"])

    def test_update_zip_keeps_manifest_true(self):
        """版を上げた更新の zip: version.py と差し替えを足しても manifest の SHA-256 が合う(友人のアプリが確かめる)"""
        src = os.path.join(self.tmp, "a.zip")
        ver = b'VERSION = "1.2.3"\n'
        man = {"version": "1.2.3", "files": {"src/ytt/version.py": B.hashlib.sha256(ver).hexdigest()}}
        with zipfile.ZipFile(src, "w") as z:
            z.writestr("src/ytt/version.py", ver)
            z.writestr("python/python.exe", b"MZ")
            z.writestr("tools/t.txt", b"t")
            z.writestr("manifest.json", json.dumps(man))
        os.makedirs(os.path.join(self.tmp, "dropbox", "更新"))
        P.make_update(src, self.tmp, "1.2.4")
        with open(os.path.join(self.tmp, "dropbox", "更新", "latest.json"), encoding="utf-8") as f:
            latest = json.load(f)
        self.assertEqual(latest["version"], "1.2.4")
        with zipfile.ZipFile(os.path.join(self.tmp, "dropbox", "更新", latest["light"]["file"])) as zl:   # 軽い zip: python/・tools/ なし・manifest は同じ files + light
            self.assertEqual(sorted(zl.namelist()), ["manifest.json", "src/ytt/version.py"])
            ml = json.loads(zl.read("manifest.json"))
            self.assertTrue(ml["light"])
            self.assertIn("python/Lib/site-packages/sitecustomize.py", ml["files"])
        self.assertEqual(latest["light"]["sha256"], B.sha256_file(os.path.join(self.tmp, "dropbox", "更新", latest["light"]["file"])))
        with zipfile.ZipFile(os.path.join(self.tmp, "dropbox", "更新", latest["file"])) as z:
            self.assertIn("python/python.exe", z.namelist())
            self.assertEqual([z.read(n) for n in ("python/python.exe", "tools/t.txt")], [b"MZ", b"t"])   # 2 つの zip へ書いても全部読める
            self.assertIsNone(z.testzip())
            m = json.loads(z.read("manifest.json"))
            self.assertEqual(m["version"], "1.2.4")
            for rel, sha in m["files"].items():
                self.assertEqual(B.hashlib.sha256(z.read(rel)).hexdigest(), sha, rel)
            self.assertIn(b'"1.2.4"', z.read("src/ytt/version.py"))


class PublishGateTest(unittest.TestCase):
    """--publish は検査に通ったときだけ更新の置き場所へ写す(落ちたら何も置かない)"""

    def setUp(self):
        self.tmp = testkit.tempdir(self, "pf-pub-")
        self.out = os.path.join(self.tmp, "更新")

    def fake_build(self, out_dir, *a, **k):
        p = os.path.join(out_dir, "FriendApp-9.9.9.zip")
        with open(p, "wb") as f:
            f.write(b"zip")
        with open(os.path.join(out_dir, "FriendApp-9.9.9-light.zip"), "wb") as f:
            f.write(b"l")
        with open(os.path.join(out_dir, "latest.json"), "w", encoding="utf-8") as f:
            json.dump({"version": "9.9.9", "file": "FriendApp-9.9.9.zip"}, f)
        light = {"file": "FriendApp-9.9.9-light.zip", "size": 1, "sha256": "y"}
        return {"zip": p, "size": 3, "sha256": "x", "files": 1, "light": dict(light, zip=os.path.join(out_dir, light["file"])),
                "row": {"version": "9.9.9", "builtAt": "t", "notes": "", "file": "FriendApp-9.9.9.zip", "size": 3, "sha256": "x", "light": light, "runtime": "r"}}

    def args(self, skip=False):
        return B.argparse.Namespace(cache="c", wcpp="w", no_fetch=True, notes="", launcher_build="l", skip_preflight=skip)

    def test_failed_preflight_places_nothing(self):
        with mock.patch.object(B, "build", self.fake_build), mock.patch.object(P, "preflight_zip", return_value=False) as pf:
            with self.assertRaises(B.BuildError):
                B.publish(self.args(), self.out)
        pf.assert_called_once()
        self.assertFalse(os.path.exists(self.out))

    def test_passed_preflight_places_zip_then_latest(self):
        with mock.patch.object(B, "build", self.fake_build), mock.patch.object(P, "preflight_zip", return_value=True):
            got = B.publish(self.args(), self.out)
        self.assertEqual(sorted(os.listdir(self.out)), ["FriendApp-9.9.9-light.zip", "FriendApp-9.9.9.zip", "latest.json", "versions.json"])
        self.assertEqual(got["zip"], os.path.join(self.out, "FriendApp-9.9.9.zip"))

    def test_publish_prunes_old_zips_and_nulls_their_rows(self):
        os.makedirs(self.out)
        rows = []
        for n in range(1, 5):   # 置いてある全部入り 4 版(0.9.1〜0.9.4)に今回の 9.9.9 が加わる = 全部入りは 3 版・古い 2 版が消える
            v = "0.9.%d" % n
            for name in ("FriendApp-%s.zip" % v, "FriendApp-%s-light.zip" % v):
                open(os.path.join(self.out, name), "wb").close()
            rows.append({"version": v, "builtAt": "t", "notes": "", "file": "FriendApp-%s.zip" % v, "size": 0, "sha256": "s",
                         "light": {"file": "FriendApp-%s-light.zip" % v, "size": 0, "sha256": "l"}, "runtime": "r"})
        with open(os.path.join(self.out, "versions.json"), "w", encoding="utf-8") as f:
            json.dump({"v": 1, "versions": rows}, f)
        with mock.patch.object(B, "build", self.fake_build), mock.patch.object(P, "preflight_zip", return_value=True):
            B.publish(self.args(), self.out)
        zips = sorted(n for n in os.listdir(self.out) if n.endswith(".zip") and not n.endswith("-light.zip"))
        self.assertEqual(zips, ["FriendApp-0.9.3.zip", "FriendApp-0.9.4.zip", "FriendApp-9.9.9.zip"])
        with open(os.path.join(self.out, "versions.json"), encoding="utf-8") as f:
            got = {r["version"]: r for r in json.load(f)["versions"]}
        self.assertEqual(list(got), ["9.9.9", "0.9.4", "0.9.3", "0.9.2", "0.9.1"])
        self.assertIsNone(got["0.9.2"]["file"])
        self.assertIsNone(got["0.9.1"]["file"])
        self.assertIsNotNone(got["0.9.4"]["file"])
        self.assertIsNotNone(got["0.9.1"]["light"])   # 軽いのは 10 版まで残る

    def test_skip_only_when_asked(self):
        with mock.patch.object(B, "build", self.fake_build), mock.patch.object(P, "preflight_zip") as pf:
            B.publish(self.args(skip=True), self.out)
        pf.assert_not_called()
        with self.assertRaises(SystemExit):
            B.main(["--out", self.tmp, "--skip-preflight"])   # --publish のときだけ


if __name__ == "__main__":
    unittest.main()
