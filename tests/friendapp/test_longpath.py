"""260 文字を超える深いフォルダでも、zip の展開と受信箱の動かす所(保存先へ・ごみ箱へ・戻す)が通ること(Windows だけ)。
リポジトリ直下で: py -3.12 -m unittest tests/friendapp/test_longpath.py"""
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from friendapp import inbox, sync as S  # noqa: E402
from ytt import fsio  # noqa: E402

RID = "20250615-120000-aaaaaa"
T0 = 1750000000.0


def deep(root, n=300):
    d = root
    while len(d) < n:
        d = os.path.join(d, "d" * 40)
    return d


def zip_file(path, entries):
    with zipfile.ZipFile(path, "w") as z:
        for k, v in entries.items():
            z.writestr(k, v)


@unittest.skipUnless(os.name == "nt", "Windows の長いパスの話")
class LongPathTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lp-")
        self.addCleanup(shutil.rmtree, fsio.long_path(self.tmp), True)
        self.base = deep(self.tmp)
        self.assertGreater(len(self.base), 260)

    def test_long_path_prefix(self):
        self.assertEqual(fsio.long_path("C:\\a\\b"), "\\\\?\\C:\\a\\b")
        self.assertEqual(fsio.long_path("\\\\srv\\sh\\a"), "\\\\?\\UNC\\srv\\sh\\a")
        self.assertEqual(fsio.long_path("\\\\?\\C:\\a"), "\\\\?\\C:\\a")
        self.assertEqual(fsio.long_path(""), "")

    def test_extract_pack_into_deep_folder(self):
        zp = os.path.join(self.tmp, "a.zip")
        zip_file(zp, {"題_pack/create_resolve_textplus_project.lua": "x", "題_pack/sub/clip.mp4": "v"})
        dest = os.path.join(self.base, "save")
        got = S.extract_pack(zp, dest, "fallback")
        self.assertTrue(len(got) > 260)
        self.assertTrue(os.path.isfile(fsio.long_path(os.path.join(got, "create_resolve_textplus_project.lua"))))
        self.assertTrue(os.path.isfile(fsio.long_path(os.path.join(got, "sub", "clip.mp4"))))
        self.assertFalse(os.path.exists(fsio.long_path(got + ".extracting")))

    def test_extract_pack_still_refuses_zip_slip(self):
        zp = os.path.join(self.tmp, "bad.zip")
        zip_file(zp, {"x_pack/ok.txt": "1", "x_pack/../../evil.txt": "2"})
        dest = os.path.join(self.base, "save")
        with self.assertRaises(ValueError):
            S.extract_pack(zp, dest, "fallback")
        self.assertFalse(os.path.exists(fsio.long_path(os.path.join(dest, "evil.txt"))))
        self.assertFalse(os.path.exists(fsio.long_path(os.path.join(self.base, "evil.txt"))))

    def test_update_into_deep_home(self):
        """友人の home が深い: 軽い更新は今の python(深い)から写せる・全部入りも manifest の照合が通る(読む側も長いパスで開く)"""
        import hashlib
        import json
        rel = "python/Lib/site-packages/" + "p" * 60 + "/__init__.py"
        body = {"src/friendapp/server.py": b"# server", "python/python.exe": b"MZpy", rel: b"x = 1\n"}
        files = {k: hashlib.sha256(v).hexdigest() for k, v in body.items()}
        home = deep(self.tmp, 150)   # home は短い(フォルダは普通に作れる)・中の深いファイルで 260 字を超える
        self.assertGreater(len(os.path.join(home, "app-0.2.0.tmp", rel)), 260)
        runtime = os.path.join(home, "app-0.1.0", "python")
        for k, v in body.items():
            if k.startswith("python/"):
                p = fsio.long_path(os.path.join(runtime, *k[len("python/"):].split("/")))
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "wb") as f:
                    f.write(v)
        light = os.path.join(self.tmp, "light.zip")
        zip_file(light, {"src/friendapp/server.py": b"# server", "manifest.json": json.dumps({"files": files, "light": True})})
        got = S.install_update(light, home, "0.2.0", [runtime])
        self.assertTrue(os.path.isfile(fsio.long_path(os.path.join(got, *rel.split("/")))))
        full = os.path.join(self.tmp, "full.zip")
        zip_file(full, dict(body, **{"manifest.json": json.dumps({"files": files})}))
        got = S.install_update(full, home, "0.3.0")
        self.assertTrue(os.path.isfile(fsio.long_path(os.path.join(got, *rel.split("/")))))

    def test_inbox_keep_trash_and_undo_in_deep_folders(self):
        cases = os.path.join(self.base, "cases")
        save = os.path.join(self.base, "save")
        outbox = os.path.join(self.tmp, "outbox")
        box = inbox.Inbox(os.path.join(self.tmp, "friend", "inbox.json"), outbox, lambda: save, lambda: cases, clock=lambda: T0)
        box.add(RID, {"url": "u", "videoId": "dQw4w9WgXcQ", "streamer": ""}, {"url": "u", "videoId": "dQw4w9WgXcQ", "title": "題"}, run_id="run-1")
        case = os.path.join(cases, "案件-" + RID)
        dirs = []
        for n in ("a_pack", "b_pack"):
            d = os.path.join(case, "パック", n)
            os.makedirs(fsio.long_path(d))
            with open(fsio.long_path(os.path.join(d, "clip.mp4")), "wb") as f:
                f.write(b"x")
            dirs.append(d)
        box.finished("run-1", "done", "", [{"dir": d, "seconds": 10.5} for d in dirs], case=case)
        got = box.decide(RID, ["a_pack"], "skip")
        self.assertEqual((got["done"], got["errors"]), (["a_pack"], []))
        self.assertFalse(os.path.exists(fsio.long_path(dirs[0])))
        trash = [p for p in got["row"]["packs"] if p["name"] == "a_pack"][0]["trash"]
        self.assertTrue(os.path.isdir(fsio.long_path(trash)))
        got = box.undo(RID, ["a_pack"])
        self.assertEqual((got["done"], got["errors"]), (["a_pack"], []))
        self.assertTrue(os.path.isfile(fsio.long_path(os.path.join(dirs[0], "clip.mp4"))))
        got = box.decide(RID, ["b_pack"], "keep")
        self.assertEqual((got["done"], got["errors"]), (["b_pack"], []))
        saved = [p for p in got["row"]["packs"] if p["name"] == "b_pack"][0]["savedTo"]
        self.assertGreater(len(saved), 260)
        self.assertTrue(os.path.isfile(fsio.long_path(os.path.join(saved, "clip.mp4"))))


if __name__ == "__main__":
    unittest.main()
