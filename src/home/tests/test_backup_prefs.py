"""設定 prefs の backup の節(src/home/prefs.py。入口の側に残した検査)。バックアップの本体のテストは src/manage/keep/tests/test_backup.py。

実行(リポジトリ直下から): python -m unittest src/home/tests/test_backup_prefs.py -v
"""
import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HOME = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ROOT = os.path.dirname(HOME)
for p in (HOME, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import prefs as prefs_mod  # noqa: E402
from ytt import fsio  # noqa: E402


class BackupPrefsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-backup-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.dst = os.path.join(self.tmp, "外付け", "backup")

    def test_prefs_shape(self):
        p = prefs_mod.Prefs(os.path.join(self.tmp, "p.json"), fsio.atomic_write)
        self.assertEqual(p.get(["backup"])["backup"], {"enabled": False, "folder": "", "everyHours": 1})
        for bad in ({"enabled": True}, {"folder": "\\\\srv\\share"}, {"folder": "rel"}, {"everyHours": 0}, {"everyHours": 1.5}, {"everyHours": True}):
            with self.assertRaises(prefs_mod.PrefsError, msg=bad):
                p.patch("backup", bad)
        self.assertEqual(p.patch("backup", {"enabled": True, "folder": self.dst, "everyHours": 6, "x": 1}),
                         {"enabled": True, "folder": self.dst, "everyHours": 6})
        self.assertEqual(p.get(["intake"])["intake"]["enabled"], False)   # ほかの節はそのまま


if __name__ == "__main__":
    unittest.main()
