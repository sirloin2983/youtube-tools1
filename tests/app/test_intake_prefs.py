"""入口の設定 prefs の intake の節(src/app/prefs.py。入口の側に残した検査)。intake の本体のテストは tests/human/friend/test_intake.py。

実行(リポジトリ直下から): python -m unittest tests/app/test_intake_prefs.py -v
"""
import os
import sys
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HOME = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src", "app")
ROOT = os.path.dirname(HOME)
for p in (HOME, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from human.friend import intake  # noqa: E402
from app import prefs as prefs_mod  # noqa: E402
from ytt import fsio  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/(testkit)
import testkit  # noqa: E402


class TestPrefs(unittest.TestCase):
    def test_cfg_falls_back_to_given_defaults(self):
        """設定が読めないときの既定は入口が渡す(intake は prefs を読み込まない。RS3-0B)"""
        class Broken:
            def get(self, sections):
                raise OSError("読めない")
        tmp = testkit.tempdir(self, "intake-")
        d = prefs_mod.DEFAULTS["intake"]
        it = intake.Intake(Broken(), lambda: None, tmp, defaults=d)
        self.assertEqual(it._cfg(), d)
        self.assertIsNot(it._cfg(), d)    # 呼ぶ側が書き換えても既定は変わらない
        self.assertEqual(intake.Intake(Broken(), lambda: None, tmp)._cfg(), {})   # 渡さなければ空 = オフ扱い

    def test_folder_and_out_dir(self):
        """受付のフォルダと 出力\\ の読み方の口(入口の手で届ける・片付けの候補・学習の束・ライブの自動の届け先が使う)。オフでもフォルダは返す"""
        tmp = testkit.tempdir(self, "intake-")
        p = prefs_mod.Prefs(os.path.join(tmp, "prefs.json"), fsio.atomic_write)
        it = intake.Intake(p, lambda: None, tmp, defaults=prefs_mod.DEFAULTS["intake"])
        self.assertEqual((it.folder(), it.out_dir()), ("", None))
        box = os.path.join(tmp, "Dropbox")
        p.patch("intake", {"folder": box, "enabled": False})
        self.assertEqual((it.folder(), it.out_dir()), (box, os.path.join(box, intake.OUT_DIR)))
        self.assertEqual(intake.out_dir_of(intake.configured_folder(p)), os.path.join(box, "出力"))

        class Broken:
            def get(self, sections):
                raise OSError("読めない")
        self.assertEqual(intake.Intake(Broken(), lambda: None, tmp, defaults={"folder": box}).folder(), box)
        self.assertEqual(intake.configured_folder(Broken()), "")

    def test_old_delivery_batch_key_is_read_and_dropped(self):
        """前の版の prefs.json(intake.deliverBatch がある)も読める。届け方の鍵は捨てる(届けるのは 1 本ずつ = F3-6)"""
        tmp = testkit.tempdir(self, "intake-")
        box = os.path.join(tmp, "Dropbox")
        path = testkit.write_json(os.path.join(tmp, "prefs.json"), {"intake": {"folder": box, "top": 4, "deliverBatch": 3}})
        p = prefs_mod.Prefs(path, fsio.atomic_write)
        got = p.get(["intake"])["intake"]
        self.assertNotIn("deliverBatch", got)
        self.assertEqual((got["top"], got["folder"]), (4, box))
        self.assertNotIn("deliverBatch", p.patch("intake", {"deliverBatch": 9, "top": 2}))
        self.assertEqual(p.get(["intake"])["intake"]["top"], 2)

    def test_intake_prefs(self):
        p = prefs_mod.Prefs(os.path.join(testkit.tempdir(self, "intake-"), "prefs.json"), fsio.atomic_write)
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


if __name__ == "__main__":
    unittest.main()
