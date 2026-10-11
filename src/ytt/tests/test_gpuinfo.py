# -*- coding: utf-8 -*-
"""ytt/gpuinfo(この PC の GPU の名前と VRAM。F1 F0-2)のテスト。  py -3.10 -m unittest src/ytt/tests/test_gpuinfo.py -v

- nvidia-smi・CIM の出力の読み方(CIM の AdapterRAM の 4GB の頭打ちは None)・GPU の選び方・調べる順と覚え方
- この PC(Windows)で本物を 1 回調べて、形が合うこと(GPU が無い PC では None でよい)
"""
import os
import sys
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> ytt -> src
sys.path.insert(0, SRC)
from ytt import gpuinfo as G  # noqa: E402


class TestParse(unittest.TestCase):
    def test_nvidia_smi(self):
        self.assertEqual(G.parse_nvidia_smi("NVIDIA GeForce RTX 3060, 12288\r\nNVIDIA GeForce RTX 3060 Ti, 8192\n\n"),
                         [{"name": "NVIDIA GeForce RTX 3060", "vramGB": 12.0, "vendor": "nvidia"},
                          {"name": "NVIDIA GeForce RTX 3060 Ti", "vramGB": 8.0, "vendor": "nvidia"}])
        self.assertEqual(G.parse_nvidia_smi("Weird, [N/A]"), [{"name": "Weird", "vramGB": None, "vendor": "nvidia"}])
        self.assertEqual(G.parse_nvidia_smi(None), [])

    def test_cim(self):
        one = '{"Name":"AMD Radeon RX 7800 XT","AdapterRAM":4293918720,"AdapterCompatibility":"Advanced Micro Devices, Inc."}'
        self.assertEqual(G.parse_cim(one), [{"name": "AMD Radeon RX 7800 XT", "vramGB": None, "vendor": "amd"}])   # 4GB の頭打ち = 分からない
        many = ('[{"Name":"Intel(R) UHD Graphics 770","AdapterRAM":2147483648,"AdapterCompatibility":"Intel Corporation"},'
                '{"Name":"NVIDIA GeForce GTX 1050","AdapterRAM":0,"AdapterCompatibility":"NVIDIA"},{"Name":""}]')
        self.assertEqual(G.parse_cim(many), [{"name": "Intel(R) UHD Graphics 770", "vramGB": 2.0, "vendor": "intel"},
                                             {"name": "NVIDIA GeForce GTX 1050", "vramGB": None, "vendor": "nvidia"}])
        for bad in ("", "not json", "3", '"x"', None):
            self.assertEqual(G.parse_cim(bad), [], bad)

    def test_pick_and_vendor(self):
        self.assertIsNone(G.pick([]))
        self.assertIsNone(G.pick([{"name": "Microsoft Basic Display Adapter", "vramGB": None}]))
        gpus = [{"name": "Intel UHD", "vramGB": None}, {"name": "A", "vramGB": 8.0}, {"name": "B", "vramGB": 12.0}, {"name": "C", "vramGB": 12.0}]
        self.assertEqual(G.pick(gpus)["name"], "B")   # 大きい物・同じなら先
        self.assertEqual(G.pick([{"name": "X", "vramGB": None}, {"name": "Y", "vramGB": None}])["name"], "X")
        for name, want in (("NVIDIA GeForce RTX 3060", "nvidia"), ("AMD Radeon RX 7800 XT", "amd"), ("Intel(R) Arc A770", "intel"), ("Foo", "other")):
            self.assertEqual(G.vendor_of(name), want)
        self.assertEqual((G.gb(17163091968), G.gb(0), G.gb("x"), G.gb(None)), (16.0, None, None, None))


class TestProbe(unittest.TestCase):
    def setUp(self):
        G._cache.clear()
        self.addCleanup(G._cache.clear)

    def test_order(self):
        nv = [{"name": "NVIDIA GeForce RTX 3060", "vramGB": 12.0, "vendor": "nvidia"}]
        reg = [{"name": "AMD Radeon RX 7800 XT", "vramGB": 16.0, "vendor": "amd"}]
        cim = [{"name": "AMD Radeon RX 7800 XT", "vramGB": None, "vendor": "amd"}]
        with mock.patch.object(G, "from_nvidia_smi", return_value=nv), mock.patch.object(G, "from_registry", side_effect=AssertionError), \
                mock.patch.object(G, "from_cim", side_effect=AssertionError):
            self.assertEqual(G.probe(), nv[0])   # nvidia-smi で VRAM が分かれば止める
        with mock.patch.object(G, "from_nvidia_smi", return_value=[]), mock.patch.object(G, "from_registry", return_value=reg), \
                mock.patch.object(G, "from_cim", side_effect=AssertionError):
            self.assertEqual(G.probe(), reg[0])
        with mock.patch.object(G, "from_nvidia_smi", return_value=[]), mock.patch.object(G, "from_registry", side_effect=OSError), \
                mock.patch.object(G, "from_cim", return_value=cim):
            self.assertEqual(G.probe(), cim[0])   # レジストリが壊れていても CIM の名前(VRAM は None)
        with mock.patch.object(G, "from_nvidia_smi", return_value=[]), mock.patch.object(G, "from_registry", return_value=[]), \
                mock.patch.object(G, "from_cim", return_value=[]):
            self.assertIsNone(G.probe())

    def test_cached(self):
        with mock.patch.object(G, "probe", return_value={"name": "X", "vramGB": 8.0, "vendor": "nvidia"}) as p:
            a = G.info()
            a["name"] = "changed"   # 返した dict を書き換えても覚えた物は変わらない
            self.assertEqual(G.info()["name"], "X")
            self.assertEqual(p.call_count, 1)
            G.info(refresh=True)
            self.assertEqual(p.call_count, 2)

    def test_child_process_has_no_window_and_timeout(self):
        seen = {}

        def run_short(cmd, timeout):
            seen["cmd"], seen["timeout"] = cmd, timeout
            raise G.subprocess.TimeoutExpired(cmd, timeout)
        with mock.patch.object(G.procs, "run_short", run_short):
            self.assertIsNone(G._run(["nvidia-smi"]))   # 時間切れは「分からない」
        self.assertEqual(seen["timeout"], G.TIMEOUT)   # procs.run_short = spawn(窓なし CREATE_NO_WINDOW)を通る

    def test_real_once(self):
        g = G.probe()
        if g is None:
            self.skipTest("GPU が見つからない PC")
        self.assertEqual(set(g), {"name", "vramGB", "vendor"})
        self.assertTrue(g["name"])
        self.assertTrue(g["vramGB"] is None or g["vramGB"] > 0)


if __name__ == "__main__":
    unittest.main()
