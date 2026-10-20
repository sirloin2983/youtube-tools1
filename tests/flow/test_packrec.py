# -*- coding: utf-8 -*-
"""flow/packrec.py(パックを作った記録)の整理: 記録が MAX_RECORDS を超えたときに消す物・残す物"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parents[1] / "src"))

from flow import packrec  # noqa: E402


class TestPrune(unittest.TestCase):
    def test_removes_missing_folders_and_broken_records_first(self):
        """記録が MAX_RECORDS を超えたら、古い順に見て フォルダの無いもの・読めないもの・形の違うものを消す(フォルダが残っているものは残す)"""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            recs = base / "recs"
            recs.mkdir()
            alive, alive2 = base / "alive_pack", base / "alive2_pack"
            alive.mkdir()
            alive2.mkdir()
            for i, (name, text) in enumerate((("a.json", json.dumps({"dir": str(alive)})), ("b.json", json.dumps({"dir": str(base / "prune_missing_pack")})),
                                              ("c.json", "{broken"), ("d.json", "[1]")), 1):
                (recs / name).write_text(text, encoding="utf-8")
                os.utime(recs / name, (1000 * i, 1000 * i))
            res = {"out_dir": alive2, "files": [("edl", alive2 / "x.edl")], "editMedia": None, "plan": {}}
            with mock.patch.object(packrec, "packs_dir", return_value=str(recs)), mock.patch.object(packrec, "MAX_RECORDS", 2):
                packrec.write_record(res, base / "v.mp4", True)
            left = sorted(p.name for p in recs.iterdir())
            self.assertEqual(len(left), 3, left)              # 新しい記録 + 残したもの a(フォルダがある)・d(最後まで古い順の外)
            self.assertIn("a.json", left)
            self.assertIn("d.json", left)
            self.assertNotIn("b.json", left)
            self.assertNotIn("c.json", left)
            new = [p for p in recs.iterdir() if p.name not in ("a.json", "d.json")][0]
            self.assertEqual(json.loads(new.read_text(encoding="utf-8"))["dir"], str(alive2))
            self.assertTrue(new.read_text(encoding="utf-8").endswith("}\n"))   # indent=1・最後に改行


if __name__ == "__main__":
    unittest.main()
