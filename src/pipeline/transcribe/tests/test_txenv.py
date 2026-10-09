# -*- coding: utf-8 -*-
"""pipeline/transcribe の一時的な口 txenv と、本物と疑似の差し込み口 backend のテスト(役割で組み直す RS2-2)。

    py -3.10 -m unittest src/pipeline/transcribe/tests/test_txenv.py -v

編集の serve を読まずに動く(この層は app = serve・ed_state と ④ = eval を読まない)。serve の登録で S.backend_name に合わせて
切り替わることは src/editor/tests/test_names.py(test_metrics から)が確かめる。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしないが、ほかのテストとそろえる
import subprocess
import sys
import unittest

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> transcribe -> pipeline -> src
sys.path.insert(0, SRC)
from pipeline.transcribe import backend, txenv  # noqa: E402


class TestTxenv(unittest.TestCase):
    def setUp(self):
        self.saved = dict(txenv._providers)
        txenv._providers.clear()

    def tearDown(self):
        txenv._providers.clear()
        txenv._providers.update(self.saved)

    def test_register_and_read_at_call_time(self):
        box = {"dir": "a"}
        txenv.register(TX_DIR=lambda: box["dir"], check_source=lambda: (lambda p: "checked:" + p))
        self.assertEqual(txenv.get("TX_DIR"), "a")
        box["dir"] = "b"   # 登録した関数を呼ぶたびに読む(作業データの切り替え・テストの差し替えが効く)
        self.assertEqual(txenv.TX_DIR, "b")
        self.assertEqual(txenv.check_source("x.mp4"), "checked:x.mp4")

    def test_unregistered_and_unknown(self):
        with self.assertRaises(RuntimeError):
            txenv.get("ROSTER")
        with self.assertRaises(RuntimeError):
            txenv.check()
        with self.assertRaises(TypeError):
            txenv.register(NOT_A_KEY=lambda: 1)
        with self.assertRaises(TypeError):
            txenv.register(TX_DIR="not callable")
        with self.assertRaises(AttributeError):
            txenv.NOT_A_KEY  # noqa: B018
        txenv.register(**{k: (lambda: None) for k in txenv.KEYS})
        txenv.check()

    def test_rs28a_keys(self):
        """RS2-8a で足した鍵: スタジオの配信の情報 studio_stream・モデル名の検査 valid_model・受け渡しの部品 pio(関数を返す鍵はそのまま呼べる)"""
        for k in ("studio_stream", "valid_model", "pio"):
            self.assertIn(k, txenv.KEYS)
        txenv.register(studio_stream=lambda: (lambda vid: {"channel": "ch:" + vid}), valid_model=lambda: (lambda m: m == "small"),
                       pio=lambda: (lambda required=True: "pio" if required else None))
        self.assertEqual(txenv.studio_stream("v1"), {"channel": "ch:v1"})
        self.assertTrue(txenv.valid_model("small"))
        self.assertFalse(txenv.valid_model("../x"))
        self.assertIsNone(txenv.pio(required=False))
        self.assertEqual(txenv.pio(), "pio")
        with self.assertRaises(RuntimeError):
            txenv.check()   # ほかの鍵は登録していない


class TestBackend(unittest.TestCase):
    def tearDown(self):
        backend.set_selector(lambda: backend.REAL)

    def test_real_calls_real(self):
        b = backend.REAL
        self.assertEqual(b.name, "faster-whisper")
        self.assertEqual(b.engine_ids({}, lambda spec: ("e", "1")), ("e", "1"))
        self.assertEqual(b.transcribe("j", "s", "w", 3.0, lambda *a: a), ("j", "s", "w", 3.0))
        self.assertEqual(b.range_main("j", 0.0, 1.0, (0.0, 1.0), lambda a, b_, share: [a, b_]), [0.0, 1.0])
        self.assertEqual(b.range_loose("j", [(0, 1)], lambda spans: spans), [(0, 1)])
        self.assertEqual(b.each_lines("j", "s", [], "w", 0.0, lambda *a: {"ok": 1}), {"ok": 1})
        f = b.redo_recognizer("j", "s", "w", 0.0, lambda *a: (lambda sub, a_, b_: [a_, b_]), None)
        self.assertEqual(f({}, 1.0, 2.0), [1.0, 2.0])

    def test_selector_reads_each_time(self):
        other = backend.Backend()
        flag = {"on": False}
        backend.set_selector(lambda: other if flag["on"] else backend.REAL)
        self.assertIs(backend.select(), backend.REAL)
        flag["on"] = True
        self.assertIs(backend.select(), other)


class TestImportsAlone(unittest.TestCase):
    def test_no_app_or_eval(self):
        """backend・txenv は serve・ed_state(app)と eval を読まずに import できる(層の向き)"""
        code = ("import sys; sys.path.insert(0, %r); from pipeline.transcribe import backend, txenv; "
                "bad = [m for m in sys.modules if m in ('serve', 'ed_state', 'ed_jobs') or m == 'eval' or m.startswith('eval.')]; "
                "print(bad); sys.exit(1 if bad else 0)") % SRC
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
