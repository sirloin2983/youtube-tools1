# -*- coding: utf-8 -*-
"""ytt_core/evaldata.py(友人用 文字起こし簡易版の評価データの形式と規則)のテスト。
    python -m unittest ytt_core/tests/test_evaldata.py -v"""
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
from ytt_core import evaldata as E  # noqa: E402


class Marks(unittest.TestCase):
    def test_strip_marks(self):
        self.assertEqual(E.strip_marks("えー [?] そうですね"), "えーそうですね")
        self.assertEqual(E.strip_marks("[笑]"), "")
        self.assertEqual(E.strip_marks("[?][笑]  "), "")
        self.assertEqual(E.strip_marks("[笑]、それで"), "それで")             # 先頭の句読点は詰める
        self.assertEqual(E.strip_marks("うん[?]、。そう"), "うん。そう")       # 続いた句読点は強い方
        self.assertEqual(E.strip_marks("あ、[笑]、いい"), "あ、いい")
        self.assertEqual(E.strip_marks("Hello [笑] world"), "Hello world")
        self.assertEqual(E.strip_marks("そのまま"), "そのまま")

    def test_bad_marks(self):
        for s in ("【笑】", "(笑)", "（笑）", "それなw", "ｗｗｗ", "[わら]", "[？]", "［笑］", "[不明]", "いいね 草"):
            self.assertTrue(E.bad_marks(s), s)
        for s in ("[?]", "[笑]", "えー[?]そう[笑]", "wow", "Windows", "道草", "AWS"):
            self.assertEqual(E.bad_marks(s), [], s)

    def test_fillers_and_tidy(self):
        self.assertEqual(E.count_fillers("えーっと、あのー、えー"), 3)
        self.assertEqual(E.count_fillers("えーと[?]"), 1)
        raw = ["えー、あのー、まあ、なんか"] * 4                    # 16 個
        self.assertEqual(E.tidy_suspect(raw, raw), (False, ""))
        sus, why = E.tidy_suspect(raw, ["そうです"] * 4)
        self.assertTrue(sus)
        self.assertIn("フィラー", why)
        self.assertEqual(E.tidy_suspect(["えー"], [""]), (False, ""))   # 少なすぎる動画は判定しない


class Paths(unittest.TestCase):
    def test_scrub(self):
        home = r"C:\Users\taro"
        obj = {"sourcePath": r"C:\Users\taro\Videos\a b.mp4", "unc": r"\\server\share\x.mp4", "mac": "/Users/taro/v/x.mov",
               "note": r"保存先 C:\Users\taro\Videos\x.mp4 を見る", "list": [r"D:\clips\y.mp4"], "n": 3, "ok": "そのまま",
               "url": "https://www.youtube.com/watch?v=abc", "path_url": "https://example.com/home/x"}
        out = E.scrub_paths(obj, home=home)
        self.assertEqual(out["sourcePath"], "a b.mp4")
        self.assertEqual(out["unc"], "x.mp4")
        self.assertEqual(out["mac"], "x.mov")
        self.assertEqual(out["list"], ["y.mp4"])
        self.assertEqual(out["url"], obj["url"])            # URL はパスではない
        self.assertEqual(out["path_url"], obj["path_url"])
        self.assertNotIn("taro", json.dumps(out, ensure_ascii=False))
        self.assertEqual(E.find_abs_paths(out), [])
        self.assertTrue(E.find_abs_paths(obj))

    def test_names(self):
        self.assertEqual(E.zip_name("2026-10-02", "兎田 ぺこら", "0123456789ab"), "2026-10-02_兎田_ぺこら_0123456789ab.zip")
        self.assertEqual(E.zip_name("2026-10-02", 'a:b*?', "0123456789ab"), "2026-10-02_ab_0123456789ab.zip")
        self.assertNotIn("/", E.zip_name("d", "../x", "0123456789ab"))
        self.assertEqual(E.work_id_of("2026-10-02_x_0123456789ab.zip"), "0123456789ab")
        self.assertIsNone(E.work_id_of("x.zip"))
        self.assertEqual(E.safe_url("https://www.youtube.com/watch?v=abc"), "https://www.youtube.com/watch?v=abc")
        for bad in ("javascript:alert(1)", "file:///C:/x", "https://a b", "x" * 600):
            self.assertEqual(E.safe_url(bad), "")


class Ops(unittest.TestCase):
    def test_sanitize_op(self):
        self.assertIsNone(E.sanitize_op({"op": "rm -rf"}))
        self.assertIsNone(E.sanitize_op("x"))
        o = E.sanitize_op({"op": "confirm", "row": "s1<script>", "played": False, "t": 1.23456, "text": "秘密", "evil": 1})
        self.assertEqual(o, {"op": "confirm", "row": "s1script", "played": False, "t": 1.235})
        self.assertEqual(E.sanitize_op({"op": "time", "edge": "start", "from": 1.0, "to": 1.1, "start": True})["to"], 1.1)


class Judge(unittest.TestCase):
    def test_rows_and_work(self):
        raw = {"segments": [{"start": 0, "end": 2, "text": "えー、あのー、まあ"}, {"start": 2, "end": 4, "text": "なんか、えー、うーん"},
                            {"start": 4, "end": 6, "text": "えーと、あー、その、まあ"}]}
        rows = [{"id": "s1", "start": 0, "end": 2, "text": "えー、あのー、まあ", "checked": True, "raw": [0]},
                {"id": "s2", "start": 2, "end": 4, "text": "なんか(笑)", "checked": True, "raw": [1]},
                {"id": "s3", "start": 4, "end": 6, "text": "えーと", "checked": False, "raw": [2]}]
        j = E.judge({"rows": rows}, raw, [{"op": "confirm", "played": False}, {"op": "confirm", "played": True}])
        use = {r["id"]: r for r in j["rows"]}
        self.assertTrue(use["s1"]["use"])
        self.assertFalse(use["s2"]["use"])
        self.assertIn("記号の形式違い", use["s2"]["reasons"][0])
        self.assertEqual(use["s3"]["reasons"], ["未確認"])
        self.assertEqual(j["notes"], {"confirmedWithoutListening": 1, "badMarkRows": 1, "unchecked": 1})
        self.assertTrue(j["work"]["use"])   # 確認済みの範囲のフィラーは少なすぎて判定しない

    def test_tidy_work(self):
        raw = {"segments": [{"start": i, "end": i + 1, "text": "えー、あのー、まあ、なんか"} for i in range(5)]}
        rows = [{"id": "s%d" % i, "start": i, "end": i + 1, "text": "はい", "checked": True, "raw": [i]} for i in range(5)]
        j = E.judge({"rows": rows}, raw)
        self.assertFalse(j["work"]["use"])
        self.assertFalse(E.judge({"rows": []}, raw)["work"]["use"])

    def test_raw_links(self):
        segs = [{"start": 0, "end": 1}, {"start": 1, "end": 3}, {"start": 5, "end": 6}]
        self.assertEqual(E.raw_links({"start": 0.5, "end": 2}, segs), [0, 1])
        self.assertEqual(E.raw_links({"start": 4, "end": 4.5}, segs), [])


class Zips(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _zip(self, entries, name="a.zip"):
        p = os.path.join(self.d, name)
        with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
            for n, data in entries:
                if isinstance(n, zipfile.ZipInfo):
                    z.writestr(n, data)
                else:
                    z.writestr(n, data)
        return p

    def good(self):
        return [(n, b"{}" if n.endswith(".json") else b"x") for n in E.FILES]

    def test_good_zip_extracts(self):
        p = self._zip(self.good())
        ok, problems = E.check_zip(p)
        self.assertEqual(problems, [])
        out = E.extract_zip(p, os.path.join(self.d, "out"))
        self.assertEqual(sorted(os.path.basename(x) for x in out), sorted(E.FILES))

    def test_bad_names(self):
        for evil in ("../evil.txt", "../../meta.json", "/abs.json", "C:/x/meta.json", "sub\\meta.json", "dir/meta.json", "readme.txt", "a/"):
            p = self._zip(self.good() + [(evil, b"x")], name="b.zip")
            ok, problems = E.check_zip(p)
            self.assertTrue(problems, evil)
            with self.assertRaises(E.BundleError):
                E.extract_zip(p, os.path.join(self.d, "out2"))
            self.assertFalse(os.path.exists(os.path.join(self.d, "evil.txt")))
            self.assertFalse(os.path.exists(os.path.join(self.d, "out2")))

    def test_missing_and_symlink_and_bomb(self):
        p = self._zip([(n, b"{}") for n in E.FILES if n != "meta.json"], name="c.zip")
        self.assertTrue(any("meta.json" in x for x in E.check_zip(p)[1]))
        info = zipfile.ZipInfo("meta.json")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        p = self._zip([e for e in self.good() if e[0] != "meta.json"] + [(info, b"/etc/passwd")], name="d.zip")
        self.assertTrue(any("リンク" in x for x in E.check_zip(p)[1]))
        p = self._zip([e for e in self.good() if e[0] != "final.json"] + [("final.json", b"0" * (5 * 1024 * 1024))], name="e.zip")
        self.assertTrue(any("圧縮率" in x for x in E.check_zip(p)[1]))
        p = os.path.join(self.d, "f.zip")
        with open(p, "wb") as f:
            f.write(b"not a zip")
        self.assertTrue(E.check_zip(p)[1])

    def test_too_many(self):
        p = self._zip([("x%d" % i, b"") for i in range(E.MAX_ENTRIES + 1)], name="g.zip")
        self.assertIn("多すぎ", E.check_zip(p)[1][0])

    def test_read_edits(self):
        data = b'{"op":"confirm","row":"s1","played":true}\nnot json\n{"op":"bad"}\n\n'
        self.assertEqual(E.read_edits(data), [{"op": "confirm", "row": "s1", "played": True}])


if __name__ == "__main__":
    unittest.main()
