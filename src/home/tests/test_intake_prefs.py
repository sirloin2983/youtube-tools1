"""入口の設定 prefs の intake の節(src/home/prefs.py。入口の側に残した検査)。intake の本体のテストは src/human/friend/tests/test_intake.py。

実行(リポジトリ直下から): python -m unittest src/home/tests/test_intake_prefs.py -v
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

from human.friend import intake  # noqa: E402
import prefs as prefs_mod  # noqa: E402
from ytt import fsio  # noqa: E402


class TestPrefs(unittest.TestCase):
    def test_cfg_falls_back_to_given_defaults(self):
        """設定が読めないときの既定は入口が渡す(intake は prefs を読み込まない。RS3-0B)"""
        class Broken:
            def get(self, sections):
                raise OSError("読めない")
        tmp = tempfile.mkdtemp(prefix="intake-")
        self.addCleanup(shutil.rmtree, tmp, True)
        d = prefs_mod.DEFAULTS["intake"]
        it = intake.Intake(Broken(), lambda: None, tmp, defaults=d)
        self.assertEqual(it._cfg(), d)
        self.assertIsNot(it._cfg(), d)    # 呼ぶ側が書き換えても既定は変わらない
        self.assertEqual(intake.Intake(Broken(), lambda: None, tmp)._cfg(), {})   # 渡さなければ空 = オフ扱い

    def test_intake_prefs(self):
        tmp = tempfile.mkdtemp()
        try:
            p = prefs_mod.Prefs(os.path.join(tmp, "prefs.json"), fsio.atomic_write)
            self.assertEqual(p.get(["intake"])["intake"], prefs_mod.DEFAULTS["intake"])
            v = p.patch("intake", {"enabled": True, "top": 5, "maxHours": 2.5})
            self.assertEqual((v["enabled"], v["top"], v["maxHours"], v["interval"]), (True, 5, 2.5, 30))
            self.assertNotIn("dailyMax", v)   # 1 日の上限は無い。古いアプリ・古い prefs.json の dailyMax は読み飛ばす
            self.assertNotIn("dailyMax", p.patch("intake", {"dailyMax": 3}))
            self.assertEqual(p.patch("intake", {"interval": 120})["interval"], 120)   # 見る間隔(段9 9-4)
            for bad in ({"top": 11}, {"top": 2.5}, {"maxGB": True}, {"folder": 3}, {"folder": "\\\\server\\share"},
                        {"interval": 5}, {"interval": 601}, {"interval": 30.5},
                        {"folder": "//server/share"}, {"folder": "relative\\dir"}):
                with self.assertRaises(prefs_mod.PrefsError, msg=str(bad)):
                    p.patch("intake", bad)
            if os.name == "nt":
                self.assertEqual(p.patch("intake", {"folder": ' "C:\\Users\\x\\Dropbox" '})["folder"], "C:\\Users\\x\\Dropbox")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
