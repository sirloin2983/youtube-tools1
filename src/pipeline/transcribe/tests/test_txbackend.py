# -*- coding: utf-8 -*-
"""pipeline/transcribe の本物と疑似の差し込み口 backend のテスト(役割で組み直す RS2-2)。

    py -3.10 -m unittest src/pipeline/transcribe/tests/test_txbackend.py -v

編集の serve を読まずに動く(この層は app = serve・ed_state と ④ = eval を読まない)。serve の登録で S.backend_name に合わせて
切り替わることは src/editor/tests/test_names.py(test_metrics から)が確かめる。
RS3-0A に test_txenv.py から名前を変えた(一時の口 txenv は消した = 置き場所は ytt/workdata、外の道具などは持ち主を直に読む。
持ち主が S の差し替えに従うことは test_names.py の TestOwnersFollowServePatches)。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしないが、ほかのテストとそろえる
import subprocess
import sys
import unittest

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> transcribe -> pipeline -> src
sys.path.insert(0, SRC)
from pipeline.transcribe import backend  # noqa: E402


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
        # RS2-9: 話者判別の区間と声の特徴の口
        self.assertEqual(b.diarize("j", {"numSpeakers": 2}, "w", 3.0, lambda job, spec, wav: [(0.0, 1.0, spec["numSpeakers"])]), [(0.0, 1.0, 2)])
        self.assertEqual(b.embed("j", "w", "voxceleb", [[(0, 1)]], lambda job, wav, emb, groups: [emb, len(groups)]), ["voxceleb", 1])

    def test_selector_reads_each_time(self):
        other = backend.Backend()
        flag = {"on": False}
        backend.set_selector(lambda: other if flag["on"] else backend.REAL)
        self.assertIs(backend.select(), backend.REAL)
        flag["on"] = True
        self.assertIs(backend.select(), other)


class TestImportsAlone(unittest.TestCase):
    def test_no_app_or_eval(self):
        """backend は serve・ed_state(app)と eval を読まずに import できる(層の向き)。一時の口 txenv は無い(RS3-0A で消した)"""
        code = ("import sys, importlib.util; sys.path.insert(0, %r); from pipeline.transcribe import backend; "
                "bad = [m for m in sys.modules if m in ('serve', 'ed_state', 'ed_jobs') or m == 'eval' or m.startswith('eval.')]; "
                "bad += ['txenv'] if importlib.util.find_spec('pipeline.transcribe.txenv') else []; "
                "print(bad); sys.exit(1 if bad else 0)") % SRC
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
