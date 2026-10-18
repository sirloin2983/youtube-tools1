"""採用の数・余白・待ちの既定が束(flow/spec.py の DEFAULTS adopt)の 1 か所から来て、今までの値のままであることを固定する(RS6 b-R1)"""
import os
import sys
import unittest

_HOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.dirname(_HOME), _HOME):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from flow import live_detect, spec  # noqa: E402
from app import prefs  # noqa: E402


class AdoptDefaults(unittest.TestCase):
    def test_values_unchanged(self):
        a = spec.DEFAULTS["adopt"]
        self.assertEqual((a["perHour"], a["waitMin"], a["pad"]), (6, 5, 2.0))


if __name__ == "__main__":
    unittest.main()
