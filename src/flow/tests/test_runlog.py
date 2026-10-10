# -*- coding: utf-8 -*-
"""pipeline/runlog.py(終わった実行の記録の形と読み方。RS3-0B で autorun.py から移した)のテスト。  py -3.10 -m unittest src/flow/tests/test_runlog.py -v
- 壊れた行・形の違う行は飛ばす(途中で切れた行・手で直した行)
- .1(古い)→ 今のファイルの順(書いた順)・max_bytes は末尾からだけ読み、途中から読んだ最初の行は捨てる
- autorun を読み込まずに読める(① の部品が app を読まない = 層の向き)
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")
import json
import shutil
import subprocess
import sys
import tempfile
import unittest

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> pipeline -> src
sys.path.insert(0, SRC)
from flow import runlog  # noqa: E402


def rec(i, **kw):
    d = {"v": runlog.LOG_VERSION, "id": "r%03d" % i, "kind": "video", "videoId": "v%03d" % i, "state": "done", "steps": []}
    d.update(kw)
    return d


def line(d):
    return json.dumps(d, ensure_ascii=False).encode("utf-8") + b"\n"


class TestRunlog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-runlog-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, runlog.RUNS_LOG)

    def write(self, name, data):
        with open(os.path.join(self.tmp, name), "wb") as f:
            f.write(data)

    def test_names(self):
        self.assertEqual((runlog.RUNS_LOG, runlog.LOG_VERSION), ("autorun-runs.jsonl", 1))

    def test_missing_is_empty(self):
        self.assertEqual(runlog.read_runs_log(self.path), [])
        self.assertEqual(runlog.read_runs_log(self.path, 1000), [])

    def test_skips_bad_lines(self):
        good = [rec(1), rec(2, kind="doc", docId="d1", state="error"), rec(3, kind="file", sourcePath="C:/x.mp4", state="cancelled")]
        bad = [b"\n", b"{\n", b"[]\n", b"\xff\xfe\n", line(rec(4, v=2)), line(rec(5, id=5)), line(rec(6, state="running")), line(rec(7, steps=None)),
               line(rec(8, kind="video", videoId=None)), line(rec(9, kind="doc")), line(rec(10, kind="x"))]
        cut_off = b'{"v": 1, "id": "cut off'   # 書いている途中で切れた最後の行(改行なし)
        self.write(runlog.RUNS_LOG, b"".join([line(good[0])] + bad[:6] + [line(good[1])] + bad[6:] + [line(good[2])] + [cut_off]))
        self.assertEqual([r["id"] for r in runlog.read_runs_log(self.path)], ["r001", "r002", "r003"])

    def test_order_old_then_current(self):
        self.write(runlog.RUNS_LOG + ".1", line(rec(1)) + line(rec(2)))
        self.write(runlog.RUNS_LOG, line(rec(3)))
        self.assertEqual([r["id"] for r in runlog.read_runs_log(self.path)], ["r001", "r002", "r003"])

    def test_max_bytes_reads_the_tail_and_drops_the_cut_line(self):
        self.write(runlog.RUNS_LOG + ".1", line(rec(1)) + line(rec(2)))
        self.write(runlog.RUNS_LOG, line(rec(3)) + line(rec(4)))
        one = len(line(rec(4)))
        # 最後の 1 件ぶんより少し多く(途中から読んだ最初の行 = r003 の欠けた後ろは捨てる)。ちょうどの大きさでも先頭の行は捨てる(行の頭かは分からない)
        self.assertEqual([r["id"] for r in runlog.read_runs_log(self.path, one + 5)], ["r004"])
        self.assertEqual(runlog.read_runs_log(self.path, one), [])
        # 今のファイルを全部読んでも大きさが余れば .1 の末尾からも読む(残りの大きさ left は読んだ範囲で減らす)。.1 の先頭の欠けた行(r001)は捨てる
        self.assertEqual([r["id"] for r in runlog.read_runs_log(self.path, one * 3 + 5)], ["r002", "r003", "r004"])
        self.assertEqual([r["id"] for r in runlog.read_runs_log(self.path, one * 2 + one // 2)], ["r003", "r004"])   # .1 は半端な行だけ = 捨てる
        self.assertEqual([r["id"] for r in runlog.read_runs_log(self.path, 10 ** 6)], ["r001", "r002", "r003", "r004"])
        self.assertEqual(runlog.read_runs_log(self.path, 0), [])

    def test_autorun_is_not_needed(self):
        """autorun(app)を読み込まずに読める(ライブの失敗の集約が使う)。別のプロセスで読み込んで、読んだモジュールを調べる"""
        code = ("import sys; sys.path.insert(0, %r); from flow import runlog; "
                "sys.exit(0 if not [m for m in sys.modules if m in ('autorun', 'launch', 'cases', 'prefs')] else 1)" % SRC)
        r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
