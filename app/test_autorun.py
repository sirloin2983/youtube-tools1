#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""まとめて実行(app/autorun.py)の段取りのテスト。ツールの API は偽物(FakeTools)で、本物の通し確認は app/e2e_autorun.py。
実行(リポジトリ直下): python -m unittest app/test_autorun.py"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import autorun as A  # noqa: E402

VID = "abcdefghijk"


class FakeTools:
    """3ツールの API の最小の真似。ジョブは poll のたびに1段進む"""

    def __init__(self, tmp, marks, analysis=True):
        self.tmp = tmp
        self.txdir = os.path.join(tmp, "txdata", "transcripts")
        os.makedirs(self.txdir)
        self.video = {"id": VID, "kind": "youtube", "title": "配信A", "analysis": {"at": 1} if analysis else None, "marks": marks}
        self.calls = []
        self.export_busy = 0      # この回数だけ 409 busy を返す
        self.export_job = None
        self.queue = []
        self.tx_jobs = {}
        self.c2r = {}
        self.edits = {}           # 「編集」のカット(文書の id → GET /api/edit の応答)
        self.packed = []          # POST /api/edit/pack
        self.fail_tx = False
        self.hold = False         # True のあいだジョブを進めない(中止のテスト)
        self.review = {"precision": "fast", "maxHeight": 720, "exportVolume": 60, "exportLoudness": -16}
        self.analyze = None       # スタジオの画面で保存した解析の設定(settings.analyze。段階7-1)
        self.row_edge = None      # 「編集」の「行から」の設定(文字起こしの settings.rowEdge。⑥)
        self.subtitle = None      # 字幕の文字数の設定(文字起こしの settings.subtitle。②)

    def clip_path(self, mid):
        return os.path.join(self.tmp, "out", mid + ".mp4")

    def call(self, tool, method, path, body=None):
        self.calls.append((tool, method, path, json.loads(json.dumps(body)) if body is not None else None))
        key = (tool, method, path.split("?")[0])
        h = getattr(self, "h_%s_%s_%s" % (tool, method, path.split("?")[0].strip("/").replace("/", "_").replace("-", "_")), None)
        if h is None:
            return 404, {"error": "not_found", "message": "なし %s" % (key,)}
        return h(path, body)

    def ok(self, tool, method, path, body=None):
        st, obj = self.call(tool, method, path, body)
        if st != 200:
            raise A.StepError(obj.get("message"))
        return obj

    # studio
    def h_studio_GET_api_video(self, path, body):
        return 200, {"video": json.loads(json.dumps(self.video))}

    def h_studio_GET_api_settings(self, path, body):
        s = {"review": self.review}
        if self.analyze is not None:
            s["analyze"] = self.analyze
        return 200, {"settings": s}

    def h_studio_POST_api_queue_add(self, path, body):
        self.queue.append({"qid": "q1", "videoId": VID, "status": "running", "progress": 0.0, "phase": "解析"})
        return 200, {"added": [{"qid": "q1", "videoId": VID}], "rejected": []}

    def h_studio_GET_api_queue(self, path, body):
        for q in self.queue:
            if q["status"] == "running" and not self.hold:
                q["status"], q["marks"] = "done", 3
                self.video["analysis"] = {"at": 2}
                self.video["marks"] += [{"id": "a%d" % i, "src": "auto", "status": "", "score": s, "start": i * 10, "end": i * 10 + 5}
                                        for i, s in ((1, 2.0), (2, 9.0), (3, 5.0))]
        return 200, {"items": self.queue}

    def h_studio_POST_api_video_adopt_top(self, path, body):
        if any(m["status"] in ("adopted", "exported") for m in self.video["marks"]):
            return 200, {"adopted": [], "video": self.video}
        c = sorted((m for m in self.video["marks"] if m.get("src") == "auto" and m["status"] == ""), key=lambda m: -m["score"])[:body["top"]]
        for m in c:
            m["status"] = "adopted"
        return 200, {"adopted": [m["id"] for m in c], "video": self.video}

    def h_studio_POST_api_export(self, path, body):
        if self.export_busy:
            self.export_busy -= 1
            return 409, {"error": "busy", "message": "別の書き出しが実行中です"}
        self.export_body = body
        self.export_job = {"id": "e1", "state": "running", "items": [{"id": i, "status": "queued"} for i in body["markIds"]]}
        return 200, self.export_job

    def h_studio_GET_api_export(self, path, body):
        j = self.export_job
        if j["state"] == "running" and not self.hold:
            for it in j["items"]:
                it["status"] = "done"
                p = self.clip_path(it["id"])
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "wb") as f:
                    f.write(b"x")
                m = next(m for m in self.video["marks"] if m["id"] == it["id"])
                m.update(status="exported", path=p)
            j["state"] = "done"
        return 200, j

    def h_studio_POST_api_export_cancel(self, path, body):
        self.export_job["state"] = "cancelled"
        return 200, {"ok": True}

    # transcribe
    def h_transcribe_GET_api_settings(self, path, body):
        s = {"model": "small", "language": "ja", "boost": True, "secret": "使わない", "goalHours": 3}
        if self.row_edge is not None:
            s["rowEdge"] = self.row_edge
        if self.subtitle is not None:
            s["subtitle"] = self.subtitle
        return 200, s

    def h_transcribe_POST_api_transcribe(self, path, body):
        jid = "t%d" % (len(self.tx_jobs) + 1)
        self.tx_jobs[jid] = {"id": jid, "state": "queued", "src": body["sourcePath"], "body": body}
        return 200, {"id": jid}

    def h_transcribe_GET_api_jobs(self, path, body):
        for j in self.tx_jobs.values():
            if j["state"] in ("queued", "running") and not self.hold:
                if self.fail_tx:
                    j["state"], j["error"] = "error", "モデルが読めません"
                    continue
                j["state"] = "done"
                tid = j["body"].get("intoDoc") or ("%012d" % int(j["id"][1:]))   # intoDoc = 行の無い文書に入れる(⑦(b))
                with open(os.path.join(self.txdir, tid + ".json"), "w", encoding="utf-8") as f:
                    json.dump({"id": tid, "title": "題" + tid[-1], "sourcePath": j["src"], "updatedAt": 1, "segments": [{"start": 0, "end": 1, "text": "a"}]}, f)
        return 200, {"jobs": list(self.tx_jobs.values())}

    def h_transcribe_POST_api_transcribe_cancel(self, path, body):
        self.tx_jobs[body["id"]]["state"] = "cancelled"
        return 200, {"ok": True}

    def h_transcribe_POST_api_export_file(self, path, body):
        return 200, {"path": os.path.join(self.tmp, body["id"] + ".transcript.json")}

    def h_transcribe_GET_api_edit(self, path, body):
        tid = path.split("id=", 1)[1]
        return 200, self.edits.get(tid, {"edit": None, "rev": 0})

    def h_transcribe_POST_api_edit_pack(self, path, body):
        self.packed.append(body)
        return 200, {"ok": True, "packRev": body["rev"]}

    # cut2resolve
    def h_cut2resolve_POST_api_build(self, path, body):
        self.c2r["body"] = body
        self.c2r.setdefault("bodies", []).append(body)
        self.c2r["job"] = {"id": "c1", "state": "running"}
        return 200, {"job": self.c2r["job"]}

    def h_cut2resolve_GET_api_job(self, path, body):
        if not self.hold:
            self.c2r["job"]["state"] = "done"
            v = self.c2r["body"]["spec"]["video"]
            d = os.path.splitext(v)[0] + "_pack"
            os.makedirs(d, exist_ok=True)
            open(os.path.join(d, "cut-plan.json"), "w").close()
            self.c2r["job"]["result"] = {"outDir": d, "files": [{"name": "cut-plan.json"}, {"name": "m1.edl"}]}
        return 200, self.c2r["job"]


class Base(unittest.TestCase):
    marks = [{"id": "m1", "status": "adopted", "start": 1, "end": 5}, {"id": "m2", "status": "", "start": 9, "end": 12}]
    analysis = True

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tools = FakeTools(self.tmp, json.loads(json.dumps(self.marks)), self.analysis)
        self.env = {"TRANSCRIBE_DATA_DIR": os.path.join(self.tmp, "txdata"), "YTT_DATA_DIR": os.path.join(self.tmp, "data")}
        import cases
        self.r = A.AutoRunner(self.tools, os.path.join(self.tmp, "repo"), self.env, poll=0, sleep=lambda s: None, find_pack=cases.find_pack)

    def tearDown(self):
        self.r.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_one(self, mode, top=None, timeout=10):
        run = self.r.start(VID, mode, top)
        end = time.time() + timeout
        while time.time() < end:
            cur = next(x for x in self.r.snapshot()["runs"] if x["id"] == run["id"])
            if cur["state"] not in ("queued", "running"):
                return cur
            time.sleep(0.01)
        self.fail("終わらない: %s" % cur)

    def states(self, run):
        return {s["key"]: s["state"] for s in run["steps"]}


class TestDocs(Base):
    """文書単位の実行(docs/edit-tool-design.md の 12 ⑦(b)): 「編集」の履歴で選んだ文書を、行が無ければ文字起こし → パック"""

    def setUp(self):
        super().setUp()
        self.media = {}
        for tid, rows in (("aaaaaaaaaaa1", []), ("bbbbbbbbbbb2", [{"start": 0, "end": 2, "text": "こんにちは"}])):
            m = os.path.join(self.tmp, tid + ".mp4")
            open(m, "wb").close()
            self.media[tid] = m
            with open(os.path.join(self.tools.txdir, tid + ".json"), "w", encoding="utf-8") as f:
                json.dump({"id": tid, "title": "文書" + tid[-1], "sourcePath": m, "updatedAt": 5, "segments": rows}, f, ensure_ascii=False)

    def wait_all(self, runs, timeout=10):
        ids = {r["id"] for r in runs}
        end = time.time() + timeout
        while time.time() < end:
            cur = [x for x in self.r.snapshot()["runs"] if x["id"] in ids]
            if all(x["state"] not in ("queued", "running") for x in cur):
                return {x["docId"]: x for x in cur}
            time.sleep(0.01)
        self.fail("終わりません")

    def test_transcribe_then_pack(self):
        res = self.r.start_docs(["aaaaaaaaaaa1", "bbbbbbbbbbb2", "aaaaaaaaaaa1"])   # 同じ id を二度渡しても1つ
        self.assertEqual((len(res["runs"]), res["skipped"]), (2, []))
        self.assertEqual((res["runs"][0]["kind"], res["runs"][0]["modeLabel"]), ("doc", "文字起こし → パック"))
        got = self.wait_all(res["runs"])
        a, b = got["aaaaaaaaaaa1"], got["bbbbbbbbbbb2"]
        self.assertEqual((a["state"], [s["state"] for s in a["steps"]]), ("done", ["done", "done"]), a)
        self.assertEqual([s["state"] for s in b["steps"]], ["skip", "done"], b)          # 行がある文書は文字起こしを飛ばす
        tx = next(j for j in self.tools.tx_jobs.values())
        self.assertEqual(tx["body"]["intoDoc"], "aaaaaaaaaaa1")                           # 同じ文書に入れる
        self.assertEqual(tx["body"]["model"], "small")                                     # 新規の設定で
        bodies = self.tools.c2r["bodies"]
        self.assertEqual(sorted(b_["spec"]["video"] for b_ in bodies), sorted(self.media.values()))
        self.assertTrue(all(b_["spec"].get("preset") == "transcript-rows" and "force" not in b_["output"] for b_ in bodies))

    def test_duplicate_and_bad_ids(self):
        self.tools.hold = True
        first = self.r.start_docs(["aaaaaaaaaaa1"])
        res = self.r.start_docs(["aaaaaaaaaaa1", "bbbbbbbbbbb2", "zzzz", "../x"])
        self.assertEqual([x["docId"] for x in res["runs"]], ["bbbbbbbbbbb2"])
        self.assertEqual([(x["id"], x["reason"]) for x in res["skipped"]],
                         [("aaaaaaaaaaa1", "すでに実行中・順番待ちです"), ("zzzz", "文書が見つかりません"), ("../x", "文書が見つかりません")])
        for bad in ([], "abc", [1] * 21):
            with self.assertRaises(ValueError):
                self.r.start_docs(bad)
        for r in first["runs"] + res["runs"]:
            self.r.cancel(r["id"])
        self.tools.hold = False

    def test_existing_pack_is_skipped_unless_overwrite(self):
        d = os.path.splitext(self.media["bbbbbbbbbbb2"])[0] + "_pack"
        os.makedirs(d)
        with open(os.path.join(d, "cut-plan.json"), "w") as f:
            f.write("{}")
        got = self.wait_all(self.r.start_docs(["bbbbbbbbbbb2"])["runs"])
        st = got["bbbbbbbbbbb2"]["steps"][1]
        self.assertEqual(st["state"], "skip")
        self.assertIn("パック済み", st["detail"])
        self.assertNotIn("bodies", self.tools.c2r)
        got = self.wait_all(self.r.start_docs(["bbbbbbbbbbb2"], overwrite=True)["runs"])
        self.assertEqual(got["bbbbbbbbbbb2"]["steps"][1]["state"], "done")
        self.assertTrue(self.tools.c2r["bodies"][-1]["output"]["force"])                  # 作り直す = 上書き

    def test_cut_is_used(self):
        """カットがある文書はカットのとおり(ユーザー決定 2026-09-27)"""
        self.tools.edits["bbbbbbbbbbb2"] = {"edit": {"clips": [{"in": 0.5, "out": 1.0}, {"in": 1.0, "out": 1.5}]}, "rev": 3}
        got = self.wait_all(self.r.start_docs(["bbbbbbbbbbb2"])["runs"])
        self.assertEqual(got["bbbbbbbbbbb2"]["state"], "done")
        self.assertEqual(self.tools.c2r["bodies"][-1]["spec"]["keeps"], [[0.5, 1.5]])
        self.assertEqual(self.tools.packed[-1]["rev"], 3)

    def test_missing_media_stops(self):
        os.unlink(self.media["bbbbbbbbbbb2"])
        got = self.wait_all(self.r.start_docs(["bbbbbbbbbbb2"])["runs"])
        self.assertEqual(got["bbbbbbbbbbb2"]["state"], "error")
        self.assertIn("元の動画が見つかりません", got["bbbbbbbbbbb2"]["error"])


class TestModes(Base):
    def test_row_edge_setting_is_passed(self):
        """行から作るときの端の広げ方は「編集」の「行から」の設定(文字起こしの settings.rowEdge)を cut2resolve に渡す"""
        self.tools.row_edge = {"on": False, "after": 0.5, "before": 0.3}
        run = self.run_one("adopted")
        self.assertEqual(run["state"], "done", run)
        self.assertEqual(self.tools.c2r["body"]["spec"]["rowEdge"], {"on": False, "after": 0.5, "before": 0.3})

    def test_wrap_setting_is_passed(self):
        """Text+ 字幕の1段の文字数は、字幕の文字数の設定(文字起こしの settings.subtitle.wrapChars.vertical)を cut2resolve に渡す(12 ②)"""
        self.tools.subtitle = {"wrapChars": {"vertical": 9, "horizontal": 14}}
        run = self.run_one("adopted")
        self.assertEqual(run["state"], "done", run)
        self.assertEqual(self.tools.c2r["body"]["output"]["textplusWrap"], 9)

    def test_adopted_mode_exports_transcribes_and_packs(self):
        run = self.run_one("adopted")
        self.assertEqual(run["state"], "done", run)
        self.assertEqual(self.states(run), {"export": "done", "transcribe": "done", "pack": "done"})
        self.assertEqual(self.tools.export_body, {"id": VID, "markIds": ["m1"], "precision": "fast", "maxHeight": 720, "volume": 60, "loudness": -16})   # スタジオの設定を使う
        tx = self.tools.tx_jobs["t1"]["body"]
        self.assertEqual(tx, {"model": "small", "language": "ja", "boost": True, "sourcePath": self.tools.clip_path("m1")})   # 知らない設定は渡さない
        self.assertEqual(self.tools.c2r["body"]["spec"]["preset"], "transcript-rows")
        self.assertNotIn("rowEdge", self.tools.c2r["body"]["spec"])   # 設定が無ければ cut2resolve の既定(端を広げる)
        self.assertTrue(self.tools.c2r["body"]["output"]["textplus"])
        # もう一度押しても、作り直さない(まだ無いものだけ)
        n = len(self.tools.calls)
        again = self.run_one("adopted")
        self.assertEqual(self.states(again), {"export": "skip", "transcribe": "skip", "pack": "skip"})
        self.assertFalse(any(c[1] == "POST" for c in self.tools.calls[n:]), "2回目は何も作らない")

    def test_pack_follows_edit_cut(self):
        """「編集」でカットを決めてある文書は、そのカットのとおりに作る(spec.keeps。接している区間は1つに)・作った記録を「編集」に残す"""
        self.run_one("transcribe")   # 書き出し・文字起こしまで
        tid = "%012d" % 1
        self.tools.edits[tid] = {"rev": 3, "edit": {"clips": [{"src": 0, "in": 0.5, "out": 1.0}, {"src": 0, "in": 1.0, "out": 2.0}, {"src": 0, "in": 3.0, "out": 4.0}]}}
        run = self.run_one("adopted")
        self.assertEqual(self.states(run)["pack"], "done", run)
        b = self.tools.c2r["body"]
        self.assertEqual((b["spec"]["keeps"], "preset" in b["spec"], b["spec"]["transcript"].endswith(tid + ".transcript.json"), b["output"]["textplus"]),
                         ([[0.5, 2.0], [3.0, 4.0]], False, True, True))
        self.assertEqual([(p["id"], p["rev"], p["files"]) for p in self.tools.packed], [(tid, 3, ["cut-plan.json", "m1.edl"])])
        self.assertIn("カットのとおり", next(s for s in run["steps"] if s["key"] == "pack")["detail"])

    def test_transcribe_mode_stops_before_pack(self):
        run = self.run_one("transcribe")
        self.assertEqual(self.states(run), {"export": "done", "transcribe": "done"})
        self.assertNotIn("body", self.tools.c2r)

    def test_nothing_adopted_stops_early(self):
        for m in self.tools.video["marks"]:
            m["status"] = ""
        run = self.run_one("adopted")
        self.assertEqual(run["state"], "done")
        self.assertEqual(self.states(run), {"export": "skip", "transcribe": "skip", "pack": "skip"})

    def test_waits_while_studio_export_is_busy(self):
        self.tools.export_busy = 3
        run = self.run_one("adopted")
        self.assertEqual(run["state"], "done")
        self.assertEqual(sum(1 for c in self.tools.calls if c[2] == "/api/export" and c[1] == "POST"), 4)

    def test_transcribe_failure_stops_the_run(self):
        self.tools.fail_tx = True
        run = self.run_one("adopted")
        self.assertEqual((run["state"], self.states(run)["transcribe"], self.states(run)["pack"]), ("error", "error", "wait"))
        self.assertIn("モデルが読めません", run["error"])

    def test_tool_not_running(self):
        r = A.AutoRunner(A.ToolClient(lambda t: None), self.tmp, self.env, poll=0, sleep=lambda s: None, find_pack=lambda p: None)
        try:
            run = r.start(VID, "adopted")
            end = time.time() + 5
            while time.time() < end and r.snapshot()["runs"][0]["state"] in ("queued", "running"):
                time.sleep(0.01)
            got = r.snapshot()["runs"][0]
            self.assertEqual(got["state"], "error")
            self.assertIn("切り抜きスタジオ が動いていません", got["error"])
        finally:
            r.close()


class TestFull(Base):
    marks = []
    analysis = False

    def test_full_mode_analyzes_and_adopts_top(self):
        run = self.run_one("full", top=2)
        self.assertEqual(run["state"], "done", run)
        self.assertEqual(self.states(run), {"analyze": "done", "adopt": "done", "export": "done", "transcribe": "done", "pack": "done"})
        self.assertEqual(sorted(self.tools.export_body["markIds"]), ["a2", "a3"])   # 点数の高い2件(9.0・5.0)
        add = [c for c in self.tools.calls if c[2] == "/api/queue/add"]
        self.assertEqual(add[0][3], {"items": [{"kind": "youtube", "videoId": VID}], "settings": {}})   # 保存した設定が無ければ既定値

    def test_full_mode_uses_saved_analysis_settings(self):
        """スタジオの画面で保存した解析の設定(settings.analyze)で解析する(段階7-1)"""
        self.tools.analyze = {"count": 5, "length": 30, "sensitivity": "high", "useChat": False}
        run = self.run_one("full", top=2)
        self.assertEqual(run["state"], "done", run)
        add = [c for c in self.tools.calls if c[2] == "/api/queue/add"]
        self.assertEqual(add[0][3]["settings"], {"count": 5, "length": 30, "sensitivity": "high", "useChat": False})


class TestControl(Base):
    def test_validation(self):
        for args in (("../x", "adopted"), (VID, "all"), (VID, "full", 0), (VID, "full", 31), (VID, "full", "3"), (None, "adopted")):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.r.start(*args)

    def test_same_video_twice_is_refused_and_cancel(self):
        self.tools.hold = True
        run = self.r.start(VID, "adopted")
        with self.assertRaises(ValueError):
            self.r.start(VID, "transcribe")
        end = time.time() + 5
        while time.time() < end and self.r.snapshot()["runs"][0]["steps"][0]["state"] != "run":
            time.sleep(0.01)
        self.r.cancel(run["id"])
        end = time.time() + 5
        while time.time() < end and self.r.snapshot()["runs"][0]["state"] == "running":
            time.sleep(0.01)
        got = self.r.snapshot()["runs"][0]
        self.assertEqual(got["state"], "cancelled")
        self.assertIn(("studio", "POST", "/api/export/cancel", {"id": "e1"}), self.tools.calls)   # ツールの側の書き出しも止める
        with self.assertRaises(ValueError):
            self.r.cancel("nothere")

    def test_queued_runs_are_cancelled_on_close(self):
        self.tools.hold = True
        self.r.start(VID, "adopted")
        second = self.r.start("zzzzzzzzzzz", "adopted")
        self.r.close()
        got = {x["id"]: x for x in self.r.snapshot()["runs"]}
        self.assertEqual(got[second["id"]]["state"], "cancelled")


if __name__ == "__main__":
    unittest.main()
