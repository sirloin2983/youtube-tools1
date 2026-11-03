"""app/streamimport(出来事の記録へ古い記録を 1 回だけ取り込む。11-03 段 3)。一時フォルダだけ"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
from app import streamimport as SI  # noqa: E402
from ytt import streamlog  # noqa: E402

REC = "20261102-200617-w5UO1TRxc8c"
T = 1793619000  # 秒


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.app = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.app, True)
        self.p = os.path.join(self.app, "logs", streamlog.NAME)

    def put(self, rel, obj, lines=False):
        p = os.path.join(self.app, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            if lines:
                f.write("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in obj))
            else:
                json.dump(obj, f, ensure_ascii=False)

    def test_import_once_before_first_row_with_guess_marks(self):
        self.put("intake-state.json", {"requests": [{"requestId": "20261102-200502-8d062d", "received": T * 1000, "state": "accepted", "kind": "live",
                                                      "title": "初コラボ", "live": {"recorder": "local", "recording": REC}, "runIds": []}]})
        self.put("live/requests.json", {"v": 1, "items": {"local/" + REC: {"rid": "20261102-200502-8d062d", "createdAt": T + 1, "title": "初コラボ"}}})
        self.put("live/archive.json", {"recordings": {"local__" + REC: {"recorder": "local", "recording": REC, "videoId": "w5UO1TRxc8c",
                                                                         "request": {"rid": "20261102-200502-8d062d", "kind": "friend", "createdAt": T + 1}, "endedAt": T + 9000}}})
        self.put("live/exports.json", {"jobs": [{"state": "done", "recorder": "local", "recording": REC, "markId": "lm-1", "studio": {"mark": "m42"},
                                                 "origin": "auto", "request": {"rid": "20261102-200502-8d062d"}, "path": "E:/a/01.mp4", "runId": "r1",
                                                 "created": "2026-11-02T11:31:00.000Z", "updated": "2026-11-02T11:36:00.000Z"},
                                                {"state": "error", "recording": REC, "created": "2026-11-02T11:30:00.000Z"}]})
        self.put("logs/deliveries.jsonl", [{"at": (T + 2000) * 1000, "zip": "z.zip", "requestId": "20261102-200502-8d062d", "runId": "r1", "videoId": "",
                                            "packs": [{"dir": "E:/a/01_pack", "path": "E:/a/01.mp4", "markId": "m42"}]}], lines=True)
        self.put("logs/autorun-runs.jsonl", [{"id": "r1", "requestId": "20261102-200502-8d062d", "state": "done", "created": (T + 1500) * 1000,
                                              "finished": (T + 1900) * 1000}], lines=True)
        self.put("cases.json", {REC: {"auto": {"m9": {"discardedAt": (T + 3000) * 1000, "tx": "t1"}}}})
        # 段 2 の今の書く所がもう書いた行(この時刻より後は取り込まない)
        streamlog.record("deliver", "w5UO1TRxc8c", now=T + 2500, p=self.p, zip="new.zip")
        n = SI.run(self.app, p=self.p, now=T + 99999)
        rows = streamlog.rows(self.p)
        got = [(r["kind"], r.get("guess", False)) for r in rows]
        self.assertEqual(got, [("deliver", False),   # 先に書いてあった行はそのまま(後ろに足すだけ)
                               ("request", False), ("rec-link", False), ("rec-start", False), ("adopt", True), ("export", True),
                               ("run-start", False), ("run-end", False), ("deliver", False), ("import", False)])
        self.assertEqual(n, 8)   # 終わった録画(T+9000)・要らない(T+3000)は段 2 の最初の行(T+2500)より後 = 取り込まない
        self.assertTrue(all(r["stream"] == "w5UO1TRxc8c" for r in rows if r["kind"] in ("request", "rec-link", "rec-start", "adopt", "export")))
        imported = [r for r in rows[1:-1]]
        self.assertEqual([r["at"] for r in imported], sorted(r["at"] for r in imported))
        self.assertIsNone(SI.run(self.app, p=self.p, now=T + 99999))   # 2 回目は何もしない
        self.assertEqual(len(streamlog.rows(self.p)), len(rows))

    def test_empty_log_imports_everything_up_to_now(self):
        self.put("cases.json", {REC: {"auto": {"m9": {"expiredAt": T * 1000}}}})
        self.assertEqual(SI.run(self.app, p=self.p, now=T + 10), 1)
        r = streamlog.rows(self.p)[0]
        self.assertEqual((r["kind"], r["by"], r["note"], r["mark"]), ("discard", "auto", "日数で片付けた", "m9"))
        self.assertIsNone(SI.run(None, p=self.p))


if __name__ == "__main__":
    unittest.main()
