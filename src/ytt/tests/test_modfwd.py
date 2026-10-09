#!/usr/bin/env python3
"""ytt/modfwd.py(モジュールの名前の転送。役割で組み直す RS2-0)のテスト。

    python -m unittest src/ytt/tests/test_modfwd.py
"""
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # src
from ytt import modfwd  # noqa: E402


def _module(name, **values):
    m = types.ModuleType(name)
    m.__dict__.update(values)
    return m


class TestModfwd(unittest.TestCase):
    def setUp(self):
        self.a = _module("modfwd_test_a", X=1, shared="a")
        self.b = _module("modfwd_test_b", Y=2, shared="b")
        self.front = _module("modfwd_test_front", OWN=0)
        sys.modules[self.front.__name__] = self.front
        self.addCleanup(sys.modules.pop, self.front.__name__, None)
        self.find = modfwd.install(vars(self.front), (self.a, self.b))

    def test_read_from_first_owner(self):
        self.assertEqual((self.front.X, self.front.Y, self.front.shared), (1, 2, "a"))
        self.assertIs(self.find("Y"), self.b)
        self.assertIsNone(self.find("nothing"))
        with self.assertRaises(AttributeError):
            getattr(self.front, "nothing")

    def test_write_and_delete_go_to_owner(self):
        self.front.Y = 5
        self.assertEqual(self.b.Y, 5)
        self.assertNotIn("Y", vars(self.front))
        del self.front.Y
        self.assertFalse(hasattr(self.b, "Y"))

    def test_patch_object_restores_owner(self):
        with mock.patch.object(self.front, "X", 9):
            self.assertEqual(self.a.X, 9)
        self.assertEqual(self.a.X, 1)
        self.assertNotIn("X", vars(self.front))

    def test_own_and_new_names_stay_local(self):
        self.front.OWN = 3
        self.front.NEW = 4
        self.assertEqual((vars(self.front)["OWN"], vars(self.front)["NEW"]), (3, 4))

    def test_reinstall_does_not_stack(self):
        modfwd.install(vars(self.front), (self.b,))
        self.front.shared = "x"
        self.assertEqual((self.a.shared, self.b.shared), ("a", "x"))
        self.assertIs(type(self.front).__mro__[1], types.ModuleType)

    def test_unregistered_module_only_reads(self):
        loose = _module("modfwd_test_loose")
        modfwd.install(vars(loose), (self.a,))
        self.assertEqual(loose.X, 1)
        self.assertIs(type(loose), types.ModuleType)

    def test_duplicates(self):
        self.assertEqual(modfwd.duplicates((self.a, self.b)), {"shared": ["modfwd_test_a", "modfwd_test_b"]})
        self.assertEqual(modfwd.duplicates((self.a, _module("m2", os=os))), {})


if __name__ == "__main__":
    unittest.main()
