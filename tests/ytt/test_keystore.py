# -*- coding: utf-8 -*-
"""ytt/keystore(鍵の置き場。11-07)のテスト。  py -3.12 -m unittest tests/ytt/test_keystore.py -v
名前で書く・読む・消す・同じ値は書かない・名前の検査・例外の文に値を入れない。"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")
import json
import shutil
import sys
import tempfile
import unittest

REPO = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")
sys.path.insert(0, REPO)
from ytt import keystore  # noqa: E402

VALUE = "v" * 43


class KeystoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = keystore.path_for(os.path.join(self.tmp, "app"))

    def test_put_get_delete(self):
        self.assertEqual(keystore.get(self.path, "a.b"), "")   # 無ければ空
        self.assertTrue(keystore.put(self.path, "a.b", VALUE))
        self.assertFalse(keystore.put(self.path, "a.b", VALUE))   # 同じ値は書かない
        self.assertEqual(keystore.get(self.path, "a.b"), VALUE)
        self.assertTrue(keystore.has(self.path, "a.b"))
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"v": 1, "keys": {"a.b": VALUE}})
        self.assertTrue(keystore.put(self.path, "a.b", ""))   # 空 = 消す
        self.assertEqual(keystore.get(self.path, "a.b"), "")

    def test_beside_and_names(self):
        self.assertEqual(keystore.beside(os.path.join(self.tmp, "analytics")), self.path)   # 同じ親の app/secrets/keys.json
        for bad in ("", "A", "x y", "../x", None):
            self.assertEqual(keystore.get(self.path, bad), "")
            with self.assertRaises(ValueError) as c:
                keystore.put(self.path, bad, VALUE)
            self.assertNotIn(VALUE, str(c.exception))
        self.assertIsNone(keystore.stamp(self.path))
        keystore.put(self.path, "x", VALUE)
        self.assertIsNotNone(keystore.stamp(self.path))


if __name__ == "__main__":
    unittest.main()
