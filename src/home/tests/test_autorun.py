#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""まとめて実行(src/home/autorun.py)の段取りのテスト。ツールの API は偽物(FakeTools)で、本物の通し確認は src/home/tests/e2e_autorun.py。
実行(リポジトリ直下): python -m unittest src/home/tests/test_autorun.py"""
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
TESTS = os.path.dirname(os.path.abspath(__file__))   # src/home/tests
HERE = os.path.dirname(TESTS)   # home(入口の部品)
sys.path.insert(0, HERE)
sys.path.insert(0, TESTS)
sys.path.insert(0, os.path.dirname(HERE))
import autorun as A  # noqa: E402
from human.friend import deliver as deliver_mod  # noqa: E402  (届ける部品。RS3-3 で AutoRunner の届けは human/friend/delivery.py の Delivery へ)
from human.friend import delivery as DL  # noqa: E402
from human.friend import friend_feedback  # noqa: E402
import prefs as prefs_mod  # noqa: E402
from pipeline import runlog  # noqa: E402
from ytt_core import fsio  # noqa: E402


def _fake_preview(videos, out, labels=None, **kw):
    """まとめ動画は ffmpeg を使うので偽物(中身は test_deliver の PreviewTest で確かめる)。差し替えは Base.setUp で(テストの間だけ。
    モジュールの読み込み時に差し替えると、同じプロセスで流す test_deliver の本物のテストまで偽物になる)"""
    with open(out, "wb") as f:
        f.write(b"PREVIEW")
    return True

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
        self.hold_q = False       # True のあいだ解析だけ進めない(あとから解析を止めるテスト)
        self.review = {"precision": "fast", "maxHeight": 720, "exportVolume": 60, "exportLoudness": -16}
        self.analyze = None       # スタジオの画面で保存した解析の設定(settings.analyze。段階7-1)
        self.row_edge = None      # 「編集」の「行から」の設定(文字起こしの settings.rowEdge。⑥)
        self.subtitle = None      # 字幕の文字数の設定(文字起こしの settings.subtitle。②)
        self.tx_extra = {}        # そのほかの編集の設定(speakerColors・packLoudness・packVolume)
        self.known = True         # False = スタジオにまだ無い配信(① 探す から。解析のキューに入れるとできる)
        self.fail_pack = set()    # この動画のパックは失敗させる(失敗したときの動きのテスト)

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
        if not self.known:
            return 404, {"error": "not_found", "message": "動画が見つかりません"}
        return 200, {"video": json.loads(json.dumps(self.video))}

    def h_studio_GET_api_settings(self, path, body):
        s = {"review": self.review}
        if self.analyze is not None:
            s["analyze"] = self.analyze
        return 200, {"settings": s}

    def h_studio_POST_api_queue_add(self, path, body):
        self.known = True
        qid = "q%d" % (len(self.queue) + 1)
        self.queue.append({"qid": qid, "videoId": VID, "status": "running", "progress": 0.0, "phase": "解析"})
        return 200, {"added": [{"qid": qid, "videoId": VID}], "rejected": []}

    def h_studio_POST_api_queue_cancel(self, path, body):
        for q in self.queue:
            if q["qid"] == body.get("qid") and q["status"] == "running":
                q["status"] = "cancelled"
        return 200, {"ok": True}

    def h_studio_GET_api_queue(self, path, body):
        for q in self.queue:
            if q["status"] == "running" and not self.hold and not self.hold_q:
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

    def h_studio_POST_api_video_request_marks(self, path, body):
        """友人からの依頼: 区間を採用済みの手動マークに(同じ区間は使い回す)+ 自動の上位(区間と重ならないもの)で埋める"""
        self.known = True
        self.request_marks = body
        rids = []
        for s, e in body["ranges"]:
            m = next((x for x in self.video["marks"] if abs(x["start"] - s) <= 0.5 and abs(x["end"] - e) <= 0.5), None)
            if m is None:
                m = {"id": "r%d" % (len(self.video["marks"]) + 1), "src": "manual", "status": "adopted", "score": None, "start": s, "end": e}
                self.video["marks"].append(m)
            elif m["status"] in ("", "rejected"):
                m["status"] = "adopted"
            rids.append(m["id"])
        autos = sorted((m for m in self.video["marks"] if m.get("src") == "auto" and m["status"] != "rejected" and m["id"] not in rids
                        and not any(m["start"] < e and s < m["end"] for s, e in body["ranges"])), key=lambda m: -m["score"])[:body["auto"]]
        for m in autos:
            if m["status"] == "":
                m["status"] = "adopted"
        return 200, {"ok": True, "rangeIds": rids, "autoIds": [m["id"] for m in autos], "video": self.video}

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
        s.update(self.tx_extra)
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
        if not self.hold and self.c2r["body"]["spec"]["video"] in self.fail_pack:
            self.c2r["job"].update(state="error", error={"message": "わざと失敗"})
            return 200, self.c2r["job"]
        if not self.hold:
            self.c2r["job"]["state"] = "done"
            v = self.c2r["body"]["spec"]["video"]
            d = os.path.splitext(v)[0] + "_pack"
            os.makedirs(d, exist_ok=True)
            open(os.path.join(d, "cut-plan.json"), "w").close()
            with open(os.path.join(d, os.path.basename(v)), "wb") as f:   # 切り抜きの動画の写し(まとめ動画の材料)
                f.write(b"v")
            self.c2r["job"]["result"] = {"outDir": d, "files": [{"name": "cut-plan.json"}, {"name": "m1.edl"}]}
        return 200, self.c2r["job"]


class Base(unittest.TestCase):
    marks = [{"id": "m1", "status": "adopted", "start": 1, "end": 5}, {"id": "m2", "status": "", "start": 9, "end": 12}]
    analysis = True

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(setattr, deliver_mod, "make_preview", deliver_mod.make_preview)
        deliver_mod.make_preview = _fake_preview
        self.tools = FakeTools(self.tmp, json.loads(json.dumps(self.marks)), self.analysis)
        self.env = {"TRANSCRIBE_DATA_DIR": os.path.join(self.tmp, "txdata"), "YTT_DATA_DIR": os.path.join(self.tmp, "data")}
        from manage.cases import cases
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


class TestMarks(Base):
    """スタジオのマークの行の「この後を」(git の履歴(679ff01 以前)の docs/archive/followup-2026-09-27.md の 3): そのマークだけ 書き出し → 文字起こし → パック"""
    marks = [{"id": "m1", "status": "adopted", "start": 1, "end": 5}, {"id": "m3", "status": "adopted", "start": 20, "end": 25},
             {"id": "m2", "status": "", "start": 9, "end": 12}]

    def wait(self, run, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            cur = next(x for x in self.r.snapshot()["runs"] if x["id"] == run["id"])
            if cur["state"] not in ("queued", "running"):
                return cur
            time.sleep(0.01)
        self.fail("終わらない")

    def test_only_selected_mark(self):
        run = self.r.start(VID, "adopted", marks=["m3", "m3"])
        self.assertEqual((run["marks"], run["modeLabel"]), (["m3"], "採用後を全部(1本)"))
        run = self.wait(run)
        self.assertEqual(run["state"], "done", run)
        self.assertEqual(self.tools.export_body["markIds"], ["m3"])                                   # 採用した m1 は書き出さない
        self.assertEqual([j["src"] for j in self.tools.tx_jobs.values()], [self.tools.clip_path("m3")])
        self.assertEqual([b["spec"]["video"] for b in self.tools.c2r["bodies"]], [self.tools.clip_path("m3")])
        # 書き出し済みのマークなら、文字起こし → パックだけ(書き出しは飛ばす)
        run = self.wait(self.r.start(VID, "adopted", marks=["m3"]))
        self.assertEqual({s["key"]: s["state"] for s in run["steps"]}["export"], "skip")

    def test_bad_marks(self):
        for bad in ("m1", [1], ["../x"], ["m" * 41], ["m%d" % i for i in range(A.MAX_MARKS + 1)]):
            with self.assertRaisesRegex(ValueError, "マークの指定"):
                self.r.start(VID, "adopted", marks=bad)
        with self.assertRaisesRegex(ValueError, "採用後を全部"):
            self.r.start(VID, "full", marks=["m1"])
        self.assertEqual(self.r.snapshot()["runs"], [])


class TestDocs(Base):
    """文書単位の実行(docs/design/edit-tool-design.md の 12 ⑦(b)): 「編集」の履歴で選んだ文書を、行が無ければ文字起こし → パック"""

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
        self.assertTrue(all(b_["spec"].get("mode") == "list" and "force" not in b_["output"] for b_ in bodies))   # 既定はカットしない(2026-10-01)

    def test_streamer_color_is_passed(self):
        """配信者の名前(字幕の文字の色。git の履歴(679ff01 以前)の docs/archive/followup-2026-09-27.md の 4): 照らし合わせた名前を cut2resolve に渡す。見つからなければ始める前に断る"""
        members = os.path.join(self.tmp, "members.json")
        with open(members, "w", encoding="utf-8") as f:
            json.dump({"groups": [{"name": "3期生", "members": [{"id": "usada-pekora", "name": "兎田ぺこら", "en": "Usada Pekora", "hex": "#7EC2FE"}]}]}, f, ensure_ascii=False)
        self.env["YTT_HOLO_MEMBERS"] = members
        with self.assertRaisesRegex(ValueError, "見つかりません"):
            self.r.start_docs(["bbbbbbbbbbb2"], streamer="だれか")
        self.assertEqual(self.r.snapshot()["runs"], [])
        res = self.r.start_docs(["bbbbbbbbbbb2"], streamer="ぺこら")
        self.assertEqual(res["runs"][0]["streamer"], "兎田ぺこら")
        self.wait_all(res["runs"])
        self.assertEqual(self.tools.c2r["bodies"][-1]["output"]["streamer"], "兎田ぺこら")
        res = self.r.start_docs(["bbbbbbbbbbb2"], overwrite=True)                          # 入れなければ渡さない(黒い文字)
        self.wait_all(res["runs"])
        self.assertNotIn("streamer", self.tools.c2r["bodies"][-1]["output"])
        with self.assertRaisesRegex(ValueError, "見つかりません"):
            self.r.start("vid00000001", "adopted", streamer="だれか")

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
        self._prefs(cut="rows")
        run = self.run_one("adopted")
        self.assertEqual(run["state"], "done", run)
        self.assertEqual(self.tools.c2r["body"]["spec"]["rowEdge"], {"on": False, "after": 0.5, "before": 0.3})

    def test_wrap_setting_is_passed(self):
        """Text+ 字幕の1段の文字数は、字幕の文字数の設定(文字起こしの settings.subtitle.wrapChars.vertical)を cut2resolve に渡す(12 ②)"""
        self.tools.subtitle = {"wrapChars": {"vertical": 9, "horizontal": 14}}
        run = self.run_one("adopted")
        self.assertEqual(run["state"], "done", run)
        self.assertEqual(self.tools.c2r["body"]["output"]["textplusWrap"], 9)

    def test_pack_follows_edit_settings(self):
        """まとめて実行のパックは、編集の設定の話者の色のスイッチ・音量(LUFS か %)に従う(以前は話者の色が常にオン・音量なし)"""
        run = self.run_one("adopted")
        self.assertEqual(run["state"], "done", run)
        out = self.tools.c2r["body"]["output"]
        self.assertEqual((out["speakerColors"], out.get("loudness"), out.get("volume")), (True, None, 30))   # 既定: 色あり・音量 30%(2026-10-01)

    def test_pack_follows_edit_settings_off_and_percent(self):
        self.tools.tx_extra = {"speakerColors": False, "packLoudness": 0, "packVolume": 70}
        run = self.run_one("adopted")
        self.assertEqual(run["state"], "done", run)
        out = self.tools.c2r["body"]["output"]
        self.assertEqual((out["speakerColors"], out.get("loudness"), out["volume"]), (False, None, 70))

    def _prefs(self, **autorun):
        import prefs as PR
        from ytt_core import fsio
        p = PR.Prefs(os.path.join(self.tmp, "prefs.json"), fsio.atomic_write)
        p.patch("autorun", autorun)
        self.r.prefs = p

    def test_cut_method_none_for_docs_without_cut(self):
        """カットを決めていない文書のカットの方法(ホームの設定 autorun.cut): none = 動画全体・カット済の行の字幕も消さない(段3)"""
        self._prefs(cut="none")
        run = self.run_one("adopted")
        self.assertEqual(run["state"], "done", run)
        spec = self.tools.c2r["body"]["spec"]
        self.assertEqual((spec["mode"], spec["listKind"], spec["listText"], spec["dropCutRows"], "preset" in spec), ("list", "drop", "", False, False))

    def test_cut_method_silence_uses_edit_settings(self):
        self._prefs(cut="silence")
        self.tools.tx_extra = {"cutSilence": {"noise": -40, "min": 0.8, "pad": 0.2, "x": 1, "pad2": True}}
        run = self.run_one("adopted")
        self.assertEqual(run["state"], "done", run)
        spec = self.tools.c2r["body"]["spec"]
        self.assertEqual((spec["mode"], spec["silence"]), ("silence", {"noise": -40, "min": 0.8, "pad": 0.2}))

    def test_cut_method_default_is_none(self):
        run = self.run_one("adopted")   # ホームの設定が無いときはカットしない(2026-10-01 ユーザー決定)
        self.assertEqual(self.tools.c2r["body"]["spec"]["mode"], "list")

    def test_adopted_mode_exports_transcribes_and_packs(self):
        self._prefs(cut="rows")
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
            # 何が起きたか + 次にすること(S-19。入口 0.42.0): 「入口の画面で状態を確かめて」ではなく、どこで何を押すか
            self.assertIn("切り抜きスタジオが動いていないので、この段を進められませんでした", got["error"])
            self.assertIn("「詳しく(サーバーの管理)」", got["error"])
            self.assertIn("もう一度実行してください", got["error"])
            self.assertNotIn("入口", got["error"])
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


class TestNew(Base):
    """スタジオの ① 探す で選んだ配信(git の履歴(679ff01 以前)の docs/archive/followup-2026-09-27.md の 5): まだスタジオに無い配信を「解析から全部」"""
    marks = []
    analysis = False

    def setUp(self):
        super().setUp()
        self.tools.known = False

    def wait(self, run, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            cur = next(x for x in self.r.snapshot()["runs"] if x["id"] == run["id"])
            if cur["state"] not in ("queued", "running"):
                return cur
            time.sleep(0.01)
        self.fail("終わらない")

    def test_new_stream_goes_through_everything(self):
        res = self.r.start_new([{"id": VID, "title": " 新しい配信 ", "channel": "ch"}], top=2)
        self.assertEqual(res["skipped"], [])
        run = res["runs"][0]
        self.assertEqual((run["mode"], run["title"], run["fromSearch"], run["top"]), ("full", "新しい配信", True, 2))
        run = self.wait(run)
        self.assertEqual(run["state"], "done", run)
        self.assertEqual(self.states(run), {"analyze": "done", "adopt": "done", "export": "done", "transcribe": "done", "pack": "done"})
        add = [c for c in self.tools.calls if c[2] == "/api/queue/add"]
        self.assertEqual(add[0][3]["items"], [{"kind": "youtube", "videoId": VID, "title": "新しい配信", "channel": "ch"}])   # 題名・配信者も渡す
        self.assertEqual(run["title"], "配信A")   # 解析のあとはスタジオの題名

    def test_already_known_stream_is_the_same_as_full(self):
        """スタジオにもうある(解析済み)配信は、解析を飛ばして続きから"""
        self.tools.known, self.tools.video["analysis"] = True, {"at": 1}
        self.tools.video["marks"] = [{"id": "a1", "src": "auto", "status": "", "score": 3.0, "start": 1, "end": 5}]
        run = self.wait(self.r.start_new([{"id": VID, "title": "x"}])["runs"][0])
        self.assertEqual((run["state"], self.states(run)["analyze"]), ("done", "skip"), run)
        self.assertFalse([c for c in self.tools.calls if c[2] == "/api/queue/add"])

    def test_validation_and_skips(self):
        for bad in (None, [], "abc", [{"id": VID}] * (A.MAX_NEW + 1)):
            with self.subTest(items=bad), self.assertRaisesRegex(ValueError, "配信は"):
                self.r.start_new(bad)
        for top in (0, 31, "3", True):
            with self.subTest(top=top), self.assertRaisesRegex(ValueError, "採用する数"):
                self.r.start_new([{"id": VID}], top=top)
        with self.assertRaisesRegex(ValueError, "見つかりません"):   # 配信者の名前は始める前に照らし合わせる
            self.r.start_new([{"id": VID}], streamer="だれか")
        self.assertEqual(self.r.snapshot()["runs"], [])
        self.tools.hold = True
        res = self.r.start_new([{"id": "../../x"}, "x", {"id": VID, "title": "A"}, {"id": VID, "title": "A2"}, {"id": "bad id 0000"}])
        self.assertEqual(len(res["runs"]), 1)
        self.assertEqual([s["reason"] for s in res["skipped"]],
                         ["配信の指定が正しくありません", "配信の指定が正しくありません", "すでに実行中・順番待ちです", "配信の指定が正しくありません"])
        res = self.r.start_new([{"id": VID}])   # もう順番待ち・実行中
        self.assertEqual((res["runs"], res["skipped"][0]["reason"]), ([], "すでに実行中・順番待ちです"))
        with self.assertRaises(ValueError):
            self.r.start(VID, "adopted")        # 配信の画面からの実行とも重ねない


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

    def test_queued_runs_stay_queued_on_close(self):
        """入口の終了(M5): 順番待ちは消さずに「待ち」のまま(次の起動で続ける)。実行中の段はツールの側も取り消して止める"""
        self.tools.hold = True
        first = self.r.start(VID, "adopted")
        second = self.r.start("zzzzzzzzzzz", "adopted")
        end = time.time() + 5
        while time.time() < end and self.r.snapshot()["runs"][-1]["steps"][0]["state"] != "run":
            time.sleep(0.01)
        self.r.close()
        end = time.time() + 5
        while time.time() < end and any(x["state"] == "running" for x in self.r.snapshot()["runs"]):
            time.sleep(0.01)
        got = {x["id"]: x for x in self.r.snapshot()["runs"]}
        self.assertEqual((got[second["id"]]["state"], got[second["id"]]["message"]), ("queued", "ホームを終了したので、次の起動で続けます"))
        self.assertEqual((got[first["id"]]["state"], got[first["id"]]["steps"][0]["state"]), ("queued", "wait"))   # 途中の段は次の起動で頭から
        self.assertIn(("studio", "POST", "/api/export/cancel", {"id": "e1"}), self.tools.calls)   # ツールの側の書き出しは止める

class TestStage4(Base):
    """気が利く画面へ 段4: パックの設定は編集の設定のとおり・「行から」の形・配信単位の上書き・失敗したとき・やることが無い・見積もり"""
    marks = [{"id": "m1", "status": "adopted", "start": 1, "end": 5}, {"id": "m3", "status": "adopted", "start": 20, "end": 25}]

    def wait(self, run, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            cur = next(x for x in self.r.snapshot()["runs"] if x["id"] == run["id"])
            if cur["state"] not in ("queued", "running"):
                return cur
            time.sleep(0.01)
        self.fail("終わらない")

    def test_pack_uses_all_pack_settings(self):
        self.tools.tx_extra = {"packFps": "60", "packSize": "1920x1080", "packBackup": True}
        self.tools.subtitle = {"wrapChars": {"vertical": 8, "horizontal": 14}}
        run = self.run_one("adopted")
        self.assertEqual(run["state"], "done", run)
        out = self.tools.c2r["body"]["output"]
        self.assertEqual((out["textplusFps"], out["textplusSize"], out["backup"], out["textplusWrap"]), ("60", "1920x1080", True, 14))   # 横なら横の改行

    def test_bad_row_edge_is_reported_not_failed(self):
        self.tools.row_edge = {"on": "yes"}
        run = self.run_one("adopted")
        self.assertEqual(run["state"], "done", run)
        self.assertNotIn("rowEdge", self.tools.c2r["body"]["spec"])
        self.assertIn("「行から」の設定の形が正しくない", next(s for s in run["steps"] if s["key"] == "pack")["detail"])

    def test_nothing_to_do_and_overwrite(self):
        first = self.run_one("adopted")
        self.assertEqual((first["state"], first["nothing"], first["message"]), ("done", False, "完了"))
        self.assertEqual(len(first["docs"]), 2)   # 文字起こし・パックした文書(終わったら「校正を始める」で開く。段4d)
        again = self.run_one("adopted")   # もうパックがある: やることが無い(「完了」と言わない)
        self.assertEqual((again["state"], again["nothing"], again["stateLabel"]), ("done", True, "やることがありませんでした"))
        self.assertTrue(again["message"].startswith("やることがありませんでした"), again["message"])
        n = len(self.tools.c2r["bodies"])
        run = self.wait(self.r.start(A_VID(), "adopted", overwrite=True))   # 配信単位でも作り直せる(S-12)
        self.assertEqual((run["state"], run["overwrite"]), ("done", True), run)
        self.assertEqual(len(self.tools.c2r["bodies"]), n + 2)
        self.assertTrue(all(b["output"].get("force") for b in self.tools.c2r["bodies"][n:]))
        self.assertEqual(next(s for s in run["steps"] if s["key"] == "pack")["stateLabel"], "済み")

    def test_on_fail_next_continues(self):
        self.tools.fail_pack = {self.tools.clip_path("m1")}
        run = self.run_one("adopted")
        self.assertEqual(run["state"], "done", run)
        pk = next(s for s in run["steps"] if s["key"] == "pack")
        self.assertEqual((pk["state"], pk["stateLabel"]), ("warn", "一部失敗"))
        self.assertIn("失敗した 1 本", pk["detail"])

    def test_on_fail_stop(self):
        import prefs as PR
        from ytt_core import fsio
        p = PR.Prefs(os.path.join(self.tmp, "prefs.json"), fsio.atomic_write)
        p.patch("autorun", {"onFail": "stop"})
        self.r.prefs = p
        self.tools.fail_pack = {self.tools.clip_path("m1")}
        run = self.run_one("adopted")
        self.assertEqual((run["state"], run["stateLabel"], run["onFail"]), ("error", "失敗", "stop"), run)
        self.assertIn("わざと失敗", run["error"])

    def test_estimate(self):
        e = self.r.estimate(VID, "adopted")
        self.assertEqual([(s["key"], s["count"]) for s in e["steps"]], [("export", 2), ("transcribe", None), ("pack", None)])   # 書き出しのあとで決まる
        self.assertEqual((e["total"], e["nothing"]), (2, False))
        self.assertEqual(self.tools.c2r, {})                                                                               # 見積もりは何も作らない
        self.run_one("adopted")
        e = self.r.estimate(VID, "adopted")
        self.assertEqual((e["total"], e["nothing"]), (0, True))
        self.assertIn("パック済み", e["reason"])
        e = self.r.estimate(VID, "adopted", overwrite=True)
        self.assertEqual([s["count"] for s in e["steps"]], [0, 0, 2])
        tid = next(d["id"] for d in A.txindex.load(A.txindex.folder(self.r.root, self.env)))
        e = self.r.estimate(doc_ids=[tid])
        self.assertEqual(([s["count"] for s in e["steps"]], e["nothing"]), ([0, 0], True))
        self.assertEqual([s["count"] for s in self.r.estimate(doc_ids=[tid], overwrite=True)["steps"]], [0, 1])
        with self.assertRaises(ValueError):
            self.r.estimate(VID, "nope")


def A_VID():
    return VID

class TestStage5(Base):
    """気が利く画面へ 段5: 配信者を指定しない実行は、覚えた名前 → チャンネル名から自動で。空で送れば色なし"""

    def test_auto_from_channel(self):
        self.tools.video["channel"] = "Pekora Ch. 兎田ぺこら"
        run = self.run_one("adopted")
        self.assertEqual(run["state"], "done", run)
        self.assertEqual((self.tools.c2r["body"]["output"].get("streamer"), run["streamer"], run["streamerFrom"]), ("兎田ぺこら", "兎田ぺこら", "auto"))
        self.assertIn("字幕の色: 兎田ぺこら(自動: チャンネル名から)", next(s for s in run["steps"] if s["key"] == "pack")["detail"])

    def test_explicit_empty_is_no_color(self):
        self.tools.video["channel"] = "Pekora Ch. 兎田ぺこら"
        run = self.r.start(VID, "adopted", streamer="")
        end = time.time() + 10
        while time.time() < end:
            cur = next(x for x in self.r.snapshot()["runs"] if x["id"] == run["id"])
            if cur["state"] not in ("queued", "running"):
                break
            time.sleep(0.01)
        self.assertEqual(cur["state"], "done", cur)
        self.assertNotIn("streamer", self.tools.c2r["body"]["output"])   # 空 = 色なし(チャンネル名からも入れない)

    def test_remembered_name_wins(self):
        import prefs as PR
        from ytt_core import fsio
        p = PR.Prefs(os.path.join(self.tmp, "prefs.json"), fsio.atomic_write)
        p.remember("videos", VID, "さくらみこ")
        self.r.prefs = p
        self.tools.video["channel"] = "Pekora Ch. 兎田ぺこら"
        run = self.run_one("adopted")
        self.assertEqual((self.tools.c2r["body"]["output"].get("streamer"), run["streamerFrom"]), ("さくらみこ", "video"))


class TestRunLog(Base):
    """段2 B-6: 終わった実行を記録のファイル(logs/autorun-runs.jsonl)に残す。入口を起動し直しても前回の結果が見える"""

    def setUp(self):
        super().setUp()
        self.r.close()
        self.logs = os.path.join(self.tmp, "logs")   # テストの記録は一時フォルダ(本物の作業データに書かない)
        self.r = self.runner()

    def runner(self, **kw):
        from manage.cases import cases
        return A.AutoRunner(self.tools, os.path.join(self.tmp, "repo"), self.env, poll=0, sleep=lambda s: None, find_pack=cases.find_pack,
                            log_dir=kw.pop("log_dir", self.logs), **kw)

    @property
    def path(self):
        return os.path.join(self.logs, runlog.RUNS_LOG)

    def lines(self, path=None):
        try:
            with open(path or self.path, encoding="utf-8") as f:
                return [json.loads(x) for x in f if x.strip()]
        except FileNotFoundError:
            return []

    def wait_lines(self, n, timeout=10):
        """実行の状態が変わってから記録を書くまでの間があるので、行が n 行になるまで待つ"""
        end = time.time() + timeout
        while time.time() < end:
            got = self.lines()
            if len(got) >= n:
                return got
            time.sleep(0.01)
        self.fail("記録が %d 行になりません: %s" % (n, self.lines()))

    def test_done_and_error_are_written_once(self):
        run = self.run_one("adopted")
        got = self.wait_lines(1)
        self.assertEqual((got[0]["v"], got[0]["id"], got[0]["state"], got[0]["kind"], got[0]["videoId"]), (1, run["id"], "done", "video", VID))
        self.assertTrue(got[0]["finished"])
        self.tools.fail_tx = True
        run2 = self.run_one("transcribe")
        got = self.wait_lines(2)
        self.assertEqual((got[1]["id"], got[1]["state"]), (run2["id"], run2["state"]))
        # 二重に書かない(同じ実行をもう一度書こうとしても1行のまま・終わった実行の中止も書かない)
        mem = next(r for r in self.r.runs if r.id == run["id"])
        self.r._log(mem)
        with self.assertRaises(ValueError):
            self.r.cancel("nothere")
        self.r.cancel(run["id"])
        time.sleep(0.05)
        self.assertEqual([x["id"] for x in self.lines()], [run["id"], run2["id"]])

    def test_cancel_queued_and_running(self):
        self.tools.hold = True
        first = self.r.start(VID, "adopted")
        second = self.r.start("zzzzzzzzzzz", "adopted")
        self.r.cancel(second["id"])              # 順番待ちの中止はその場で書く
        got = self.wait_lines(1)
        self.assertEqual((got[0]["id"], got[0]["state"], got[0]["message"]), (second["id"], "cancelled", "中止しました"))
        end = time.time() + 5
        while time.time() < end and self.r.snapshot()["runs"][-1]["steps"][0]["state"] != "run":
            time.sleep(0.01)
        self.r.cancel(first["id"])               # 実行中の分は、止まったとき(_loop の終わり)に書く
        got = self.wait_lines(2)
        self.assertEqual((got[1]["id"], got[1]["state"]), (first["id"], "cancelled"))
        self.assertEqual(len(self.lines()), 2)

    def test_close_does_not_write_queued(self):
        """入口の終了(M5): 順番待ち・実行中は「中止」と書かない(次の起動で続ける = 待ちの記録 autorun-active.json に残る)"""
        self.tools.hold = True
        first = self.r.start(VID, "adopted")
        second = self.r.start("zzzzzzzzzzz", "adopted")
        end = time.time() + 5
        while time.time() < end and self.r.snapshot()["runs"][-1]["steps"][0]["state"] != "run":
            time.sleep(0.01)
        self.r.close()
        end = time.time() + 5
        while time.time() < end and any(x["state"] == "running" for x in self.r.snapshot()["runs"]):
            time.sleep(0.01)
        time.sleep(0.05)
        self.assertEqual(self.lines(), [])
        with open(os.path.join(self.logs, A.ACTIVE_FILE), encoding="utf-8") as f:
            saved = json.load(f)["runs"]
        self.assertEqual([(x["id"], x["state"]) for x in saved], [(first["id"], "running"), (second["id"], "queued")])

    def test_restart_shows_past_and_memory_wins(self):
        run = self.run_one("adopted")
        self.wait_lines(1)
        self.assertEqual(self.r.snapshot()["past"], [])          # メモリにある分は past に出さない(重ならない)
        self.r.close()
        self.r = self.runner()                                  # 入口を起動し直した
        snap = self.r.snapshot()
        self.assertEqual(snap["runs"], [])
        self.assertEqual([(p["id"], p["videoId"], p["state"]) for p in snap["past"]], [(run["id"], VID, "done")])
        self.assertIn("steps", snap["past"][0])
        self.assertNotIn("marks", snap["past"][0])              # past は画面に出す項目だけ(問い合わせを重くしない)
        run2 = self.run_one("adopted")                          # 同じ配信をもう一度 = メモリの方を出す
        self.wait_lines(2)
        self.assertEqual(self.r.snapshot()["past"], [])
        h = self.r.history()
        self.assertEqual([x["id"] for x in h["runs"]], [run2["id"], run["id"]])   # 新しい順
        self.assertEqual((h["total"], h["more"]), (2, False))

    def test_past_is_latest_per_target(self):
        recs = [dict(id="r%d" % i, kind="video", videoId="v%d" % (i % 3), docId=None, state="done", steps=[], v=1, finished=i) for i in range(7)]
        recs.append(dict(id="d1", kind="doc", videoId=None, docId="doc1", state="error", error="止まった", steps=[], v=1))
        os.makedirs(self.logs)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("".join(json.dumps(x) + "\n" for x in recs))
        r = self.runner()
        try:
            past = r.snapshot()["past"]
            self.assertEqual([p["id"] for p in past], ["d1", "r6", "r5", "r4"])   # 配信・文書ごとの最後の1件・新しい順
        finally:
            r.close()

    def test_broken_lines_are_skipped(self):
        good = dict(id="ok1", kind="video", videoId=VID, docId=None, state="error", error="理由", steps=[], v=1)
        os.makedirs(self.logs)
        with open(self.path, "wb") as f:
            f.write(b"not json\n" + b"\xff\xfe\n" + json.dumps([1]).encode() + b"\n"
                    + json.dumps(dict(good, v=2)).encode() + b"\n"                 # 知らない版
                    + json.dumps(dict(good, id="run", state="running")).encode() + b"\n"   # 終わっていない
                    + json.dumps(dict(good, kind="video", videoId=None)).encode() + b"\n"
                    + json.dumps(good).encode() + b"\n" + b'{"id": "cut-off", "kind": "vi')   # 途中で切れた最後の行
        r = self.runner()
        try:
            self.assertEqual([p["id"] for p in r.snapshot()["past"]], ["ok1"])
            self.assertEqual([p["id"] for p in r.history()["runs"]], ["ok1"])
        finally:
            r.close()

    def test_rotates_at_limit(self):
        self.r.close()
        self.r = self.runner(log_max=300)   # 1件で超える大きさ
        ids = [self.run_one("adopted")["id"]]
        self.wait_lines(1)
        ids.append(self.run_one("adopted")["id"])
        end = time.time() + 5
        while time.time() < end and not os.path.exists(self.path + ".1"):
            time.sleep(0.01)
        self.assertEqual([x["id"] for x in self.lines(self.path + ".1")], ids[:1])   # 古い方は .1 へ(1世代)
        self.assertEqual([x["id"] for x in self.wait_lines(1)], ids[1:])
        self.assertEqual([x["id"] for x in self.r.history()["runs"]], ids[::-1])   # 記録は .1 と今のファイルの両方から
        ids.append(self.run_one("adopted")["id"])
        end = time.time() + 5
        while time.time() < end and [x["id"] for x in self.lines(self.path + ".1")] != ids[1:2]:
            time.sleep(0.01)
        self.assertEqual([x["id"] for x in self.lines(self.path + ".1")], ids[1:2])   # いちばん古いものは消える(際限なく大きくならない)
        self.assertEqual([x["id"] for x in self.wait_lines(1)], ids[2:])

    def test_read_tail_only_on_start(self):
        rec = lambda i: json.dumps(dict(id="r%04d" % i, kind="video", videoId="v%04d" % i, docId=None, state="done", steps=[], v=1)) + "\n"
        os.makedirs(self.logs)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("".join(rec(i) for i in range(4000)))   # 256KB を超える
        self.assertGreater(os.path.getsize(self.path), A.LOG_READ_BYTES)
        r = self.runner()
        try:
            past = r.snapshot()["past"]
            self.assertEqual(len(past), A.PAST_MAX)
            self.assertEqual(past[0]["id"], "r3999")
            self.assertLess(len(r._past), 4000)   # 起動時は末尾だけ読む
            h = r.history(limit=10 ** 6, offset=-5)   # 上限に丸める
            self.assertEqual((len(h["runs"]), h["offset"], h["total"], h["more"]), (A.HISTORY_MAX, 0, 4000, True))
            h = r.history(limit=0, offset=3990)
            self.assertEqual([x["id"] for x in h["runs"]], ["r%04d" % i for i in range(9, -1, -1)][:1])
            h = r.history(limit="x", offset=3995)
            self.assertEqual((len(h["runs"]), h["more"]), (5, False))
        finally:
            r.close()

    def test_unwritable_folder_does_not_stop_runs(self):
        blocker = os.path.join(self.tmp, "blocker")
        with open(blocker, "w") as f:
            f.write("x")   # フォルダの代わりにファイルがある = 書けない
        self.r.close()
        self.r = self.runner(log_dir=os.path.join(blocker, "logs"))
        run = self.run_one("adopted")
        self.assertEqual(run["state"], "done")
        end = time.time() + 5
        while time.time() < end and not self.r.log_error:
            time.sleep(0.01)
        self.assertTrue(self.r.log_error)
        self.assertEqual(self.r.history()["runs"], [])
        run = self.run_one("adopted")                    # 次の実行も続けられる
        self.assertEqual(run["state"], "done")

    def test_no_log_dir_keeps_memory_only(self):
        self.r.close()
        self.r = self.runner(log_dir=None)
        self.run_one("adopted")
        self.assertFalse(os.path.exists(self.logs))
        self.assertEqual(self.r.history(), {"runs": [], "total": 0, "more": False, "offset": 0})


class TestRestore(Base):
    """線 D の M5: 入口の起動し直しで、まとめて実行の待ち・実行中を戻す(logs/autorun-active.json)。
    同じ run(同じ id)のまま、済んだ段は飛ばして、途中だった段は頭からやり直す。記録(autorun-runs.jsonl)には終わったときの 1 行だけ"""
    marks = [{"id": "m1", "status": "adopted", "start": 1, "end": 5}]

    def setUp(self):
        super().setUp()
        self.r.close()
        self.logs = os.path.join(self.tmp, "logs")
        jobs = self.tools.h_transcribe_GET_api_jobs

        def with_tid(path, body):   # 本物の「編集」のジョブは、できた文書の id(tid)を返す
            st, obj = jobs(path, body)
            for j in obj["jobs"]:
                if j["state"] == "done":
                    j["tid"] = "%012d" % int(j["id"][1:])
            return st, obj
        self.tools.h_transcribe_GET_api_jobs = with_tid
        self.r = self.runner()

    def runner(self):
        from manage.cases import cases
        return A.AutoRunner(self.tools, os.path.join(self.tmp, "repo"), self.env, poll=0, sleep=lambda s: None, find_pack=cases.find_pack, log_dir=self.logs)

    def snap(self, rid):
        return next((x for x in self.r.snapshot()["runs"] if x["id"] == rid), None)

    def until(self, fn, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            v = fn()
            if v:
                return v
            time.sleep(0.01)
        self.fail("待ちきれません")

    def active(self):
        try:
            with open(os.path.join(self.logs, A.ACTIVE_FILE), encoding="utf-8") as f:
                return json.load(f)["runs"]
        except FileNotFoundError:
            return []

    def lines(self):
        return runlog.read_runs_log(os.path.join(self.logs, runlog.RUNS_LOG))

    def restart(self, saved=None):
        """入口を止めて起動し直す。saved: 強制終了のふり(止める前の待ちの記録に戻してから起動する)"""
        self.r.close()
        self.until(lambda: not any(x["state"] == "running" for x in self.r.snapshot()["runs"]))
        if saved is not None:
            with open(os.path.join(self.logs, A.ACTIVE_FILE), "w", encoding="utf-8") as f:
                json.dump({"v": A.ACTIVE_VERSION, "runs": saved}, f, ensure_ascii=False)
        self.r = self.runner()

    def test_file_run_in_transcribe_continues_after_restart(self):
        """リアルタイム切り抜きの書き出し → まとめて実行(文字起こし → パック)の文字起こしの途中で入口を止めて起動し直すと、同じ run が続く"""
        media = os.path.join(self.tmp, "ライブ.mp4")
        open(media, "wb").close()
        self.tools.hold = True
        run = self.r.start_file(media, title="ライブの切り抜き", flow="auto", engine="whisper.cpp", model="large-v3")
        self.until(lambda: (self.snap(run["id"]) or {}).get("steps", [{}])[0].get("state") == "run")
        saved = self.active()
        self.assertEqual([(x["id"], x["state"], x["mode"], x["engine"], x["steps"][0]["state"]) for x in saved],
                         [(run["id"], "running", "file_auto", "whisper.cpp", "run")])
        self.restart()
        self.assertEqual(self.lines(), [])                                    # 入口の終了で止まった分は「中止」と書かない
        got = self.snap(run["id"])
        self.assertIn(got["state"], ("queued", "running"))                     # 同じ id のまま戻って、すぐ続きを始める
        self.assertEqual((got["engine"], got["model"], got["title"], got["mode"]), ("whisper.cpp", "large-v3", "ライブの切り抜き", "file_auto"))
        self.tools.hold = False
        done = self.until(lambda: (lambda x: x if x and x["state"] not in ("queued", "running") else None)(self.snap(run["id"])))
        self.assertEqual((done["state"], done["id"]), ("done", run["id"]), done)
        self.assertEqual(self.states(done), {"transcribe": "done", "pack": "done", "deliver": "skip"})
        tx = [j for j in self.tools.tx_jobs.values() if j["src"] == media]
        self.assertEqual([j["state"] for j in tx], ["cancelled", "done"])      # 止めた文字起こしは取り消して、頭からやり直した
        self.assertEqual((tx[-1]["body"]["engine"], tx[-1]["body"]["model"]), ("whisper.cpp", "large-v3"))   # 実行ごとのエンジン・モデルも戻る
        self.until(lambda: self.lines())
        self.assertEqual([(x["id"], x["state"]) for x in self.lines()], [(run["id"], "done")])   # 記録は終わったときの 1 行だけ
        self.until(lambda: self.active() == [])

    def test_crash_continues_from_saved_steps(self):
        """強制終了(待ちの記録だけが残る): 済んだ段(書き出し)は飛ばし、途中の段(文字起こし)から続ける"""
        tx_hold = {"on": True}   # 文字起こしだけ止めておく(書き出しは進める)
        jobs = self.tools.h_transcribe_GET_api_jobs
        self.tools.h_transcribe_GET_api_jobs = lambda p, b: (200, {"jobs": list(self.tools.tx_jobs.values())}) if tx_hold["on"] else jobs(p, b)
        run = self.r.start(VID, "adopted")
        saved = self.until(lambda: (lambda a: a if a and a[0]["steps"][0]["state"] == "done" else None)(self.active()))
        self.assertEqual([s["state"] for s in saved[0]["steps"]], ["done", "run", "wait"])
        exports = sum(1 for c in self.tools.calls if c[1:3] == ("POST", "/api/export"))
        self.restart(saved=saved)   # 強制終了のふり: 止める前の記録のまま起動する
        tx_hold["on"] = False
        done = self.until(lambda: (lambda x: x if x and x["state"] not in ("queued", "running") else None)(self.snap(run["id"])))
        self.assertEqual((done["state"], self.states(done)), ("done", {"export": "done", "transcribe": "done", "pack": "done"}), done)
        self.assertEqual(sum(1 for c in self.tools.calls if c[1:3] == ("POST", "/api/export")), exports)   # 書き出しはやり直さない
        self.assertEqual(done["steps"][0]["detail"], saved[0]["steps"][0]["detail"])                      # 済んだ段の結果の文もそのまま
        self.assertEqual([(x["id"], x["state"]) for x in self.until(self.lines)], [(run["id"], "done")])

    def test_order_cancel_old_and_broken(self):
        """順番を保って戻す・中止した実行は戻さない・7 日より前の実行は戻さず「中止」と書く・壊れた行は読み飛ばす"""
        self.tools.hold = True
        a = self.r.start(VID, "adopted")
        b = self.r.start("bbbbbbbbbbb", "transcribe")
        c = self.r.start("ccccccccccc", "adopted")
        self.r.cancel(b["id"])
        self.until(lambda: [x["id"] for x in self.active()] == [a["id"], c["id"]])
        saved = self.active()
        old = dict(saved[1], id="0123456789", videoId="ddddddddddd", created=time.time() - A.RESTORE_MAX_AGE - 60)
        self.restart(saved=[saved[0], {"id": "../x", "mode": "adopted"}, {"id": "abcdefabcd", "mode": "nope"}, old, saved[1], "壊れた"])
        got = [x for x in self.r.snapshot()["runs"]]
        self.assertEqual([x["id"] for x in reversed(got) if x["state"] in ("queued", "running")], [a["id"], c["id"]])   # 先に入れた順
        logged = {x["id"]: x for x in self.until(lambda: [x for x in self.lines() if x["id"] == "0123456789"] and self.lines())}
        self.assertEqual(logged["0123456789"]["state"], "cancelled")
        self.assertIn("3 日より前", logged["0123456789"]["message"])
        self.assertNotIn(b["id"], [x["id"] for x in self.active()])
        with self.assertRaisesRegex(ValueError, "すでに"):   # 戻した実行も、同じ配信の二重の登録を断る
            self.r.start(VID, "adopted")

    def test_tools_not_ready_yet(self):
        """起動し直してすぐ: 使うツールが動くまで待ってから始める(入口の起動の直後はまだ準備中のことがある)"""
        ready = {"studio": False}
        self.tools.endpoint = lambda t: (1, "/") if ready.get(t, True) else None
        self.r.close()
        run = A.Run(VID, "配信", "adopted", 3)
        os.makedirs(self.logs, exist_ok=True)
        with open(os.path.join(self.logs, A.ACTIVE_FILE), "w", encoding="utf-8") as f:
            json.dump({"v": A.ACTIVE_VERSION, "runs": [run.saved()]}, f)
        with mock.patch.object(A, "RESUME_WAIT", 30):
            self.r = A.AutoRunner(self.tools, os.path.join(self.tmp, "repo"), self.env, poll=0, sleep=lambda s: time.sleep(0.01),
                                  find_pack=A.cases.find_pack, log_dir=self.logs)
            self.until(lambda: "ツールの準備を待っています(studio)" in ((self.snap(run.id) or {}).get("message") or ""))
            self.assertFalse(any(c[0] == "studio" for c in self.tools.calls))
            ready["studio"] = True
            done = self.until(lambda: (lambda x: x if x and x["state"] not in ("queued", "running") else None)(self.snap(run.id)))
        self.assertEqual(done["state"], "done", done)


class TestRestartInfo(Base):
    """画面の「起動し直す」の材料(restart_info。入口 0.41.0): 待ち・実行中の数と、実行中の段がツールで動かしている仕事(書き出しの段は入れない)"""

    def until(self, fn, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            v = fn()
            if v:
                return v
            time.sleep(0.01)
        self.fail("待ちきれません")

    def step_state(self, key):
        runs = [x for x in self.r.snapshot()["runs"] if x["state"] == "running"]
        return next((s["state"] for s in runs[0]["steps"] if s["key"] == key), None) if runs else None

    def test_idle_and_export(self):
        self.assertEqual(self.r.restart_info(), {"runs": 0, "redo": None})
        self.tools.hold = True
        self.r.start(VID, "adopted")
        self.r.start("zzzzzzzzzzz", "adopted")
        self.until(lambda: self.step_state("export") == "run")
        self.assertEqual(self.r.restart_info(), {"runs": 2, "redo": None})   # 書き出しの段は redo にしない(書き出し中は今までどおり断る)

    def test_transcribe_jobs_and_others(self):
        media = os.path.join(self.tmp, "ライブ.mp4")
        open(media, "wb").close()
        self.tools.hold = True
        self.r.start_file(media, title="ライブの切り抜き")
        self.until(lambda: self.r.restart_info()["redo"])   # ジョブを入れて待ち始めるまで
        jid = next(iter(self.tools.tx_jobs))
        self.tools.tx_jobs[jid]["title"] = "ライブの切り抜き"
        self.assertEqual(self.r.restart_info(), {"runs": 1, "redo": {"tool": "transcribe", "labels": ["ライブの切り抜き"], "others": []}})
        self.tools.tx_jobs["u1"] = {"id": "u1", "state": "running", "title": "人が入れた文字起こし"}
        self.tools.tx_jobs["u2"] = {"id": "u2", "state": "done", "title": "済んだもの"}
        self.assertEqual(self.r.restart_info(timeout=1)["redo"]["others"], ["人が入れた文字起こし"])

    def test_analyze_queue(self):
        self.tools.video["analysis"] = None
        self.tools.hold_q = True
        self.r.start(VID, "full", 2)
        redo = self.until(lambda: self.r.restart_info()["redo"])
        self.assertEqual(redo, {"tool": "studio", "labels": [VID], "others": []})   # 枠の名前は題名か配信の ID(偽のキューには題名が無い)
        self.tools.queue.append({"qid": "q9", "videoId": "zzzzzzzzzzz", "title": "人が入れた解析", "status": "waiting"})
        self.assertEqual(self.r.restart_info()["redo"]["others"], ["人が入れた解析"])

    def test_pack_job(self):
        """パック(cut2resolve は 1 つずつ): この実行のジョブが動いていれば、そのツールの枠すべてがこの実行のもの"""
        self.tools.hold = True
        self.tools.c2r = {"job": {"id": "c1", "state": "running"}, "body": {"spec": {"video": "x"}}}
        self.assertEqual(A.AutoRunner._redo_work(self.tools, "cut2resolve", ["c1"]), {"tool": "cut2resolve", "labels": None, "others": []})
        self.tools.c2r["job"]["state"] = "done"
        self.assertIsNone(A.AutoRunner._redo_work(self.tools, "cut2resolve", ["c1"]))
        self.assertIsNone(A.AutoRunner._redo_work(self.tools, "intake", ["x"]))

    def test_delivered_is_saved_at_once(self):
        """届けたパックはすぐ待ちの記録に残す(段の途中で起動し直しても、同じパックを二度置かない)"""
        logs = os.path.join(self.tmp, "logs")
        self.r.close()
        self.r = A.AutoRunner(self.tools, os.path.join(self.tmp, "repo"), self.env, poll=0, sleep=lambda s: None, log_dir=logs)
        pack = os.path.join(self.tmp, "a_pack")
        os.makedirs(pack)
        open(os.path.join(pack, "cut-plan.json"), "w").close()
        out = os.path.join(self.tmp, "出力")
        run = A.Run(VID, "配信", "request_auto", 1, deliver_dir=out)
        run.state = "running"
        with self.r.cv:
            self.r.runs.append(run)
        self.r._deliver_one(run, pack)
        with open(os.path.join(logs, A.ACTIVE_FILE), encoding="utf-8") as f:
            saved = json.load(f)["runs"]
        self.assertEqual([x["delivered"] for x in saved], [[os.path.normpath(pack)]])
        self.assertEqual(len(os.listdir(out)), 1)


class TestRequests(Base):
    """友人からの依頼(src/home/intake.py)の形: request = 解析 → 採用 → 書き出し → 文字起こし(パックなし)/ file = 動画を文字起こしだけ"""
    marks = []
    analysis = False

    def setUp(self):
        super().setUp()
        import prefs as P
        from ytt_core import fsio
        self.prefs = P.Prefs(os.path.join(self.tmp, "prefs.json"), fsio.atomic_write)
        self.r.prefs = self.prefs
        self.r.log_path = os.path.join(self.tmp, "logs", runlog.RUNS_LOG)
        jobs = self.tools.h_transcribe_GET_api_jobs

        def with_tid(path, body):   # 本物の「編集」のジョブは、できた文書の id(tid)を返す
            st, obj = jobs(path, body)
            for j in obj["jobs"]:
                if j["state"] == "done":
                    j["tid"] = "%012d" % int(j["id"][1:])
            return st, obj
        self.tools.h_transcribe_GET_api_jobs = with_tid

    def wait(self, run, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            cur = next(x for x in self.r.snapshot()["runs"] if x["id"] == run["id"])
            if cur["state"] not in ("queued", "running"):
                return cur
            time.sleep(0.01)
        self.fail("終わらない")

    def test_request_url(self):
        self.tools.known = False
        res = self.r.start_request([{"id": VID, "top": 2, "title": "配信", "channel": "ch"}, {"id": "bad", "top": 2}], request_id="20261001-120000-abc123")
        self.assertEqual(len(res["skipped"]), 1)
        run = self.wait(res["runs"][0])
        self.assertEqual((run["state"], run["mode"], run["modeLabel"], run["requestId"]), ("done", "request", "依頼 ② 軽く確認: 解析 → 文字起こし", "20261001-120000-abc123"))
        self.assertEqual(list(self.states(run)), ["analyze", "adopt", "export", "transcribe"])
        self.assertEqual(sorted(self.tools.export_body["markIds"]), ["a2", "a3"])   # 上位 2 個
        self.assertEqual(self.tools.request_marks, {"id": VID, "ranges": [], "auto": 2, "title": "配信", "channel": "ch"})   # 区間なし = 自動だけ
        self.assertFalse(any(c[2] == "/api/video/adopt-top" for c in self.tools.calls))
        self.assertNotIn("body", self.tools.c2r, "パックは作らない")
        with self.assertRaisesRegex(ValueError, "1〜"):
            self.r.start_request([])

    def test_file(self):
        media = os.path.join(self.tmp, "依頼.mp4")
        open(media, "wb").close()
        run = self.r.start_file(media, title="依頼", streamer="さくらみこ", request_id="rid")
        with self.assertRaisesRegex(ValueError, "すでに"):
            self.r.start_file(media)
        run = self.wait(run)
        self.assertEqual((run["state"], run["kind"], run["sourcePath"], run["modeLabel"]), ("done", "file", media, "依頼 ② 軽く確認: 文字起こし"), run)
        self.assertEqual([j["src"] for j in self.tools.tx_jobs.values()], [media])
        self.assertEqual(run["docs"], ["000000000001"])
        self.assertEqual(self.prefs.get(["streamer"])["streamer"]["docs"], {"000000000001": "さくらみこ"})   # パックのときの字幕の色
        # 記録のファイルに kind file で残り、読み直せる
        recs = runlog.read_runs_log(self.r.log_path)
        self.assertEqual([(x["kind"], x["sourcePath"]) for x in recs], [("file", media)])
        # もう一度: 文字起こし済みなので飛ばす
        run = self.wait(self.r.start_file(media))
        self.assertEqual(self.states(run), {"transcribe": "skip"})
        with self.assertRaisesRegex(ValueError, "見つかりません"):
            self.r.start_file(os.path.join(self.tmp, "nai.mp4"))

    def test_file_engine_and_model(self):
        """リアルタイム切り抜きの live.auto(M2): 実行ごとのエンジン・モデルを文字起こしの要求に入れる(無ければ編集の設定のまま)。形の違う値は使わない"""
        media = os.path.join(self.tmp, "ライブ.mp4")
        open(media, "wb").close()
        run = self.wait(self.r.start_file(media, title="ライブ", engine="whisper.cpp", model="large-v3"))
        self.assertEqual((run["state"], run["engine"], run["model"]), ("done", "whisper.cpp", "large-v3"), run)
        body = list(self.tools.tx_jobs.values())[-1]["body"]
        self.assertEqual((body["engine"], body["model"], body["language"]), ("whisper.cpp", "large-v3", "ja"))   # ほかは編集の設定のまま
        media2 = os.path.join(self.tmp, "ライブ2.mp4")
        open(media2, "wb").close()
        run = self.wait(self.r.start_file(media2, engine="openai", model="../x"))
        self.assertEqual((run["engine"], run["model"]), (None, None))
        body = list(self.tools.tx_jobs.values())[-1]["body"]
        self.assertEqual(("engine" in body, body["model"]), (False, "small"))   # 編集の設定のモデル

    def live_clip(self, name, origin):
        """リアルタイム切り抜きの書き出し(src/home/live_export.py の _finish)と同じ形の .clip.json を置いた動画"""
        from ytt_core import schemas
        media = os.path.join(self.tmp, name)
        open(media, "wb").close()
        clip = {"schema": schemas.CLIP_SCHEMA, "range": {"start": 1200.0, "end": 1245.0}, "mark": {"id": "m1", "status": "exported", "src": "auto"},
                "source": {"kind": "live", "videoId": VID, "live": {"recorder": "local", "recording": "20261007-200000-" + VID, "origin": origin}}}
        path = schemas.clip_path_for(media)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(clip, f)
        return media

    def test_live_auto_clip_pack_is_whole_range(self):
        """線 D の M8: リアルタイム切り抜きの自動の採用(origin auto・archive)の切り抜きは、カットを指定していなければ区間の全体
        (ホームの autorun.cut が rows でも)= パックの区間は候補の区間のまま。人の採用(manual)は今までどおりホームの設定。live.auto.cut(M2)を選べばそれ"""
        self.prefs.patch("autorun", {"cut": "rows"})
        for name, origin, cut, want in (("auto.mp4", "auto", None, "list"), ("archive.mp4", "archive", None, "list"), ("manual.mp4", "manual", None, "preset"),
                                        ("auto-silence.mp4", "auto", "silence", "silence")):
            media = self.live_clip(name, origin)
            run = self.wait(self.r.start_file(media, title=name, flow="auto", cut=cut))
            self.assertEqual((run["state"], run["mode"]), ("done", "file_auto"), run)
            spec = self.tools.c2r["body"]["spec"]
            got = "preset" if "preset" in spec else spec["mode"]
            self.assertEqual(got, want, (name, spec))
            if want == "list":   # 区間の全体(削る区間なし・カット済の行の字幕も消さない)
                self.assertEqual((spec["listKind"], spec["listText"], spec["dropCutRows"], spec["minLen"]), ("drop", "", False, 0))
        self.assertFalse(A.live_auto_origin(os.path.join(self.tmp, "nai.mp4")))

    def zips(self, out):
        import zipfile
        return {n: sorted(zipfile.ZipFile(os.path.join(out, n)).namelist()) for n in os.listdir(out) if n.endswith(".zip")}

    def delivered(self, run):
        """実行が届けたパックのフォルダ(一覧の dict には出ないので Run から)"""
        return next(r for r in self.r.runs if r.id == run["id"]).delivered

    def batch_prefs(self, n):
        """まとめて届ける本数 n(ホームの設定 intake.deliverBatch)"""
        self.r.prefs = prefs_mod.Prefs(os.path.join(self.tmp, "prefs.json"), fsio.atomic_write)
        self.r.prefs.patch("intake", {"deliverBatch": n})

    RID = "20261001-120000-abc123"

    def group_json(self, out, name):
        """組の一覧(<名前>.group.json)を読む。UTF-8・BOM なし(友人のアプリの読み取りの約束。2-16)"""
        with open(os.path.join(out, name), "rb") as f:
            raw = f.read()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), "BOM なし")
        return json.loads(raw.decode("utf-8"))

    def fake_seconds(self, *secs):
        """各パックの切り抜きの長さ(ffprobe の結果)を決めた値にする。偽の動画は読めないので、そのままだと長さは None"""
        self.addCleanup(setattr, deliver_mod, "clip_seconds", deliver_mod.clip_seconds)
        deliver_mod.clip_seconds = lambda dirs, ffprobe=None: list(secs)[:len(dirs)]

    def record_places(self, out):
        """置く順の見張り: zip を作る直前・一覧を書く直前に、そのとき 出力\\ にあるものを控える(友人の同期で欠けないように ① まとめ動画 → ② zip → ③ 一覧)"""
        events = []
        orig_zip, orig_json = deliver_mod.zip_packs, deliver_mod.write_group_json
        self.addCleanup(setattr, deliver_mod, "zip_packs", orig_zip)
        self.addCleanup(setattr, deliver_mod, "write_group_json", orig_json)

        def zip_packs(dirs, *a, **k):
            events.append(("zip", sorted(os.listdir(out)) if os.path.isdir(out) else []))
            return orig_zip(dirs, *a, **k)

        def write_group_json(path, *a, **k):
            events.append(("group", sorted(os.listdir(out))))
            return orig_json(path, *a, **k)
        deliver_mod.zip_packs, deliver_mod.write_group_json = zip_packs, write_group_json
        return events

    def test_request_auto_delivers_packs(self):
        """① 全自動(URL): 解析 → 採用 → 書き出し → 文字起こし → パック → n 本(既定 5)ごとに 組 = まとめ動画 1 本 + 1 本ずつの zip + 組の一覧 を 出力\\ へ
        (友人のアプリの「受け取る」。2-16)。2 本なら実行の終わりに「1-2」の 1 組"""
        self.tools.known = False
        out = os.path.join(self.tmp, "Dropbox", "出力")
        events = self.record_places(out)
        run = self.wait(self.r.start_request([{"id": VID, "top": 2, "title": "配信", "channel": ""}], request_id=self.RID,
                                             flow="auto", deliver_dir=out)["runs"][0])
        self.assertEqual((run["state"], run["mode"]), ("done", "request_auto"), run)
        self.assertEqual(list(self.states(run)), ["analyze", "adopt", "export", "transcribe", "pack", "deliver"])
        self.assertEqual(self.states(run)["deliver"], "done")
        pre = "%s__%s" % (self.RID, run["title"])   # 題名は実行が決める(偽の配信の題名)
        z2, z3 = "%s__a2.zip" % self.RID, "%s__a3.zip" % self.RID   # 1 本ずつの zip は <依頼 id>__<パックの題>.zip(組の名前に 1-2 は付けない)
        self.assertEqual(sorted(os.listdir(out)), sorted([pre + " 1-2.preview.mp4", z2, z3, pre + " 1-2.group.json"]))
        got = self.zips(out)
        for n in ("a2_pack/cut-plan.json", "a2_pack/a2.mp4"):
            self.assertIn(n, got[z2])
        self.assertIn("a3_pack/cut-plan.json", got[z3])
        self.assertEqual([n for n in got[z2] if not n.startswith("a2_pack/")] + [n for n in got[z3] if not n.startswith("a3_pack/")], [], "1 本の zip に 1 本だけ")
        for z in (z2, z3):
            self.assertNotIn(deliver_mod.PREVIEW_NAME, got[z], "まとめ動画は zip の隣だけ(受け取ったあとは要らない。2026-10-08)")
        with open(os.path.join(out, pre + " 1-2.preview.mp4"), "rb") as f:
            self.assertEqual(f.read(), b"PREVIEW")   # 組のまとめ動画(偽物)がそのまま置かれる
        doc = self.group_json(out, pre + " 1-2.group.json")
        self.assertEqual({k: doc[k] for k in ("v", "title", "range", "preview")}, {"v": 1, "title": run["title"], "range": "1-2", "preview": pre + " 1-2.preview.mp4"})
        self.assertRegex(doc["sentAt"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")
        # 偽の動画は長さが読めない: duration は None、previewStart は 1 本目だけ 0.0(2 本目は前の長さが分からないので None)
        self.assertEqual(doc["packs"], [{"n": 1, "zip": z2, "title": "a2", "previewStart": 0.0, "duration": None},
                                        {"n": 2, "zip": z3, "title": "a3", "previewStart": None, "duration": None}])
        # 置く順: 1 本目の zip の前にまとめ動画がある・一覧を書く前に両方の zip が置いてある・書く前に一覧は無い
        self.assertEqual([k for k, _n in events], ["zip", "zip", "group"], events)
        self.assertIn(pre + " 1-2.preview.mp4", events[0][1])
        self.assertNotIn(z2, events[0][1])
        self.assertIn(z2, events[1][1])
        self.assertNotIn(z3, events[1][1])
        self.assertTrue({pre + " 1-2.preview.mp4", z2, z3} <= set(events[2][1]) and pre + " 1-2.group.json" not in events[2][1], events[2][1])
        self.assertEqual(len(self.delivered(run)), 2)
        for z in (z2, z3):   # 友人の「要らない」で引く記録は zip ごと 1 行(パックは 1 つずつ)
            row = friend_feedback.find_delivery(os.path.join(self.tmp, "logs"), z)
            self.assertEqual((row["requestId"], row["videoId"], len(row["packs"])), (self.RID, VID, 1), row)
            self.assertTrue(all(p["markId"] and p["path"].endswith(".mp4") and os.path.isdir(p["dir"]) for p in row["packs"]), row)
        self.assertIsNone(friend_feedback.find_delivery(os.path.join(self.tmp, "logs"), pre + " 1-2.zip"), "n 本を 1 つにした前の形の zip は無い")
        marks = next(r for r in self.r.runs if r.id == run["id"]).pack_marks
        packs = [p for z in (z2, z3) for p in friend_feedback.find_delivery(os.path.join(self.tmp, "logs"), z)["packs"]]
        self.assertEqual(sorted(marks), sorted(p["dir"] for p in packs))
        self.assertEqual(sorted(m["markId"] for m in marks.values()), sorted(p["markId"] for p in packs))
        self.assertFalse([n for n in os.listdir(os.path.dirname(self.tools.clip_path("a2"))) if n.startswith(".deliver")], "書きかけの zip・まとめ動画が残る")

    def test_group_json_has_preview_start_from_clip_lengths(self):
        """組の一覧の previewStart は、まとめ動画の中でそのクリップが始まる秒(前のクリップの長さの積み上げ)・duration はそのクリップの秒"""
        self.tools.known = False
        self.fake_seconds(48.2, 31.456)
        out = os.path.join(self.tmp, "Dropbox", "出力")
        run = self.wait(self.r.start_request([{"id": VID, "top": 2, "title": "配信", "channel": ""}], request_id=self.RID, flow="auto", deliver_dir=out)["runs"][0])
        self.assertEqual(run["state"], "done", run)
        doc = self.group_json(out, "%s__%s 1-2.group.json" % (self.RID, run["title"]))
        self.assertEqual([(p["n"], p["previewStart"], p["duration"]) for p in doc["packs"]], [(1, 0.0, 48.2), (2, 48.2, 31.46)])

    def test_live_clips_pool_across_runs(self):
        """10-09 ユーザー決定(decisions 3-20): ライブの切り抜きは 1 本ごとに別の実行でも、溜め(run.pool)に預けて n 本たまったら組で届ける。
        録画がもう作らない(is_done)・最後に預けてから POOL_IDLE_SEC たったら残りを届ける(1 本なら 1 本の形)。溜めは logs/deliver-pool.json に残る"""
        self.tools.known = False
        out = os.path.join(self.tmp, "Dropbox", "出力")
        self.r.pool_path = os.path.join(self.tmp, "logs", DL.POOL_FILE)   # この組み立ては log_dir なし(log_path だけ)なので、溜めの置き場所も足す
        pool = {"key": "live|%s|local/rec1" % self.RID, "rid": self.RID, "title": "配信", "meta": {"recorder": "local", "recording": "rec1", "phase": "live"}}
        for i in range(3):
            media = self.live_clip("l%d.mp4" % i, "auto")
            run = self.wait(self.r.start_file(media, title="l%d" % i, flow="auto", request_id=self.RID, deliver_dir=out, deliver_batch=2, pool=pool))
            self.assertEqual(run["state"], "done", run)
            names = sorted(os.listdir(out)) if os.path.isdir(out) else []
            if i == 0:
                self.assertEqual((names, self.r.pools()[pool["key"]]["waiting"]), ([], 1))   # 1 本目は溜めるだけ
            elif i == 1:
                pre = "%s__配信 1-2" % self.RID
                self.assertEqual(names, sorted([pre + ".preview.mp4", pre + ".group.json", "%s__l0.zip" % self.RID, "%s__l1.zip" % self.RID]), names)
            else:
                self.assertEqual(len(names), 4)   # 3 本目は溜めるだけ
        self.assertEqual(self.r.pools()[pool["key"]]["waiting"], 1)
        self.assertTrue(os.path.isfile(self.r.pool_path))   # 起動し直しても続く
        later = self.r.clock() + DL.POOL_IDLE_SEC + 1
        self.assertEqual(self.r.flush_pools(lambda meta: False, now=later), 0)   # 録画がまだ作るかもしれない間は待つ
        self.assertEqual(self.r.flush_pools(lambda meta: meta.get("recording") == "rec1", now=later), 1)
        self.assertIn("%s__l2.zip" % self.RID, os.listdir(out))
        self.assertEqual(self.r.pools(), {})

    def test_delivers_one_by_one_when_batch_is_1(self):
        """まとめて届ける本数 1 = 1 本ずつ(<依頼 id>__<パックの題>.zip + 隣にそのクリップの <同じ名前>.preview.mp4。組の一覧は作らない)"""
        self.tools.known = False
        self.batch_prefs(1)
        out = os.path.join(self.tmp, "Dropbox", "出力")
        events = self.record_places(out)
        run = self.wait(self.r.start_request([{"id": VID, "top": 2, "title": "配信", "channel": ""}], request_id=self.RID,
                                             flow="auto", deliver_dir=out)["runs"][0])
        self.assertEqual(run["state"], "done", run)
        got = self.zips(out)
        z2, z3 = "%s__a2.zip" % self.RID, "%s__a3.zip" % self.RID
        self.assertEqual(sorted(os.listdir(out)), sorted(["%s__a2.preview.mp4" % self.RID, z2, "%s__a3.preview.mp4" % self.RID, z3]))
        self.assertIn("a2_pack/cut-plan.json", got[z2])
        self.assertNotIn(deliver_mod.PREVIEW_NAME, got[z2])
        self.assertEqual([k for k, _n in events], ["zip", "zip"], "組の一覧は書かない")
        self.assertIn("%s__a2.preview.mp4" % self.RID, events[0][1], "まとめ動画は zip より先に置く")
        self.assertIn("%s__a3.preview.mp4" % self.RID, events[1][1])
        for z in (z2, z3):   # 1 本ずつでも届けた記録は残す
            self.assertEqual(len(friend_feedback.find_delivery(os.path.join(self.tmp, "logs"), z)["packs"]), 1, z)

    def test_delivers_in_batches_with_remainder(self):
        """n=2 で 3 本: 2 本たまった時点で組「1-2」(まとめ動画 + 2 つの zip + 一覧)、実行の終わりに残りの 1 本は
        1 本の形(<依頼 id>__<パックの題>.zip + <同じ名前>.preview.mp4。組の一覧なし)"""
        self.tools.known = False
        self.batch_prefs(2)
        out = os.path.join(self.tmp, "Dropbox", "出力")
        run = self.wait(self.r.start_request([{"id": VID, "top": 3, "title": "配信", "channel": ""}], request_id=self.RID,
                                             flow="auto", deliver_dir=out)["runs"][0])
        self.assertEqual(run["state"], "done", run)
        pre = "%s__%s" % (self.RID, run["title"])
        names = sorted(os.listdir(out))
        z = ["%s__a%d.zip" % (self.RID, i) for i in (1, 2, 3)]
        self.assertEqual(names, sorted([pre + " 1-2.preview.mp4", pre + " 1-2.group.json", z[0], z[1], "%s__a3.preview.mp4" % self.RID, z[2]]), names)
        got = self.zips(out)
        for name in z:   # どれも 1 本だけの zip
            self.assertEqual(len([n for n in got[name] if n.endswith("cut-plan.json")]), 1, name)
        doc = self.group_json(out, pre + " 1-2.group.json")
        self.assertEqual((doc["range"], [(p["n"], p["zip"]) for p in doc["packs"]]), ("1-2", [(1, z[0]), (2, z[1])]))   # 残りの 3 本目は一覧に入らない
        self.assertEqual(len(self.delivered(run)), 3)
        for name in z:
            self.assertEqual(len(friend_feedback.find_delivery(os.path.join(self.tmp, "logs"), name)["packs"]), 1, name)

    def test_group_without_preview_still_delivers_zips_and_list(self):
        """まとめ動画を作れなくても(ffmpeg が無い・動画が壊れている)zip と一覧は届ける(一覧の preview は null)"""
        self.tools.known = False
        self.addCleanup(setattr, deliver_mod, "make_preview", deliver_mod.make_preview)
        deliver_mod.make_preview = lambda *a, **k: False
        out = os.path.join(self.tmp, "Dropbox", "出力")
        run = self.wait(self.r.start_request([{"id": VID, "top": 2, "title": "配信", "channel": ""}], request_id=self.RID, flow="auto", deliver_dir=out)["runs"][0])
        self.assertEqual(run["state"], "done", run)
        pre = "%s__%s" % (self.RID, run["title"])
        self.assertEqual(sorted(os.listdir(out)), sorted(["%s__a2.zip" % self.RID, "%s__a3.zip" % self.RID, pre + " 1-2.group.json"]))
        doc = self.group_json(out, pre + " 1-2.group.json")
        self.assertIsNone(doc["preview"])
        self.assertEqual([p["n"] for p in doc["packs"]], [1, 2])

    def test_group_name_does_not_overwrite_existing_group(self):
        """同じ名前の組が 出力\\ に残っていたら、末尾に 4 文字足して置く(まとめ動画と一覧は同じ名前でそろえる)。zip はそれぞれ unique_zip"""
        self.tools.known = False
        out = os.path.join(self.tmp, "Dropbox", "出力")
        os.makedirs(out)
        run0 = self.r.start_request([{"id": VID, "top": 2, "title": "配信", "channel": ""}], request_id=self.RID, flow="auto", deliver_dir=out)["runs"][0]
        pre = "%s__%s" % (self.RID, self.wait(run0)["title"])
        before = set(os.listdir(out))
        self.assertIn(pre + " 1-2.group.json", before)
        # 同じ依頼 id・同じ配信をもう一度(送り直し。overwrite の実行)
        run1 = self.wait(self.r.start_request([{"id": VID, "top": 2, "title": "配信", "channel": ""}], request_id=self.RID, flow="auto", deliver_dir=out)["runs"][0])
        self.assertEqual(run1["state"], "done", run1)
        new = set(os.listdir(out)) - before
        groups = sorted(n for n in new if n.endswith(".group.json"))
        self.assertEqual(len(groups), 1, new)
        stem = groups[0][:-len(".group.json")]
        self.assertRegex(stem, r"^%s 1-2-[0-9a-f]{4}$" % re.escape(pre))
        self.assertIn(stem + ".preview.mp4", new)
        self.assertEqual(self.group_json(out, groups[0])["preview"], stem + ".preview.mp4")
        for p in self.group_json(out, groups[0])["packs"]:   # 一覧が指す zip は実際にある(unique_zip で名前が変わっていても一覧は置いた名前)
            self.assertIn(p["zip"], new)

    def make_packs(self, n, sub="packs"):
        """パックのフォルダ n 個(cut2resolve が作った形の最小: cut-plan.json + 切り抜きの動画の写し)-> 実行の並びのパス(run.packs と同じ書き方)"""
        out = []
        for i in range(1, n + 1):
            d = os.path.normpath(os.path.join(self.tmp, sub, "p%d_pack" % i))
            os.makedirs(d)
            open(os.path.join(d, "cut-plan.json"), "w").close()
            with open(os.path.join(d, "p%d.mp4" % i), "wb") as f:
                f.write(b"v")
            out.append(d)
        return out

    def direct_run(self, packs, out, batch=None):
        """段取りを通さずに届ける段(_deliver_pending)だけを動かすための実行(パックは手で用意したもの)"""
        run = A.Run(VID, "配信", "request_auto", None, request_id=self.RID, deliver_dir=out, deliver_batch=batch)
        run.state = "running"
        run.packs = list(packs)
        with self.r.cv:
            self.r.runs.append(run)
        return run

    def fail_zips_after(self, n):
        """zip を作る関数の n 回目より後を「ディスクがいっぱい」(OSError)にする。-> 呼ばれた回数の入れ物"""
        orig = deliver_mod.zip_packs
        calls = {"n": 0}
        self.addCleanup(setattr, deliver_mod, "zip_packs", orig)

        def zip_packs(*a, **k):
            calls["n"] += 1
            if calls["n"] > n:
                raise OSError(28, "No space left on device")
            return orig(*a, **k)
        deliver_mod.zip_packs = zip_packs
        return calls

    def logs_dir(self):
        return os.path.join(self.tmp, "logs")

    def real(self, run):
        """一覧の dict でない、実行そのもの(Run)"""
        return next(r for r in self.r.runs if r.id == run["id"])

    def test_group_numbers_follow_run_order(self):
        """n=2 で 4 本(実行の並び): 組「1-2」と「3-4」。一覧の n は実行の通し番号・previewStart は組ごとに頭から数える"""
        out = os.path.join(self.tmp, "Dropbox", "出力")
        run = self.direct_run(self.make_packs(4), out, batch=2)
        self.fake_seconds(10.0, 20.0)
        self.r._deliver_pending(run, {}, "", final=True)
        pre = "%s__配信" % self.RID
        self.assertEqual(sorted(os.listdir(out)), sorted(["%s__p%d.zip" % (self.RID, i) for i in (1, 2, 3, 4)] +
                                                         [pre + " %s.%s" % (r, e) for r in ("1-2", "3-4") for e in ("preview.mp4", "group.json")]))
        first, second = self.group_json(out, pre + " 1-2.group.json"), self.group_json(out, pre + " 3-4.group.json")
        self.assertEqual([(p["n"], p["zip"], p["title"], p["previewStart"], p["duration"]) for p in first["packs"]],
                         [(1, "%s__p1.zip" % self.RID, "p1", 0.0, 10.0), (2, "%s__p2.zip" % self.RID, "p2", 10.0, 20.0)])
        self.assertEqual([(p["n"], p["zip"], p["previewStart"], p["duration"]) for p in second["packs"]],
                         [(3, "%s__p3.zip" % self.RID, 0.0, 10.0), (4, "%s__p4.zip" % self.RID, 10.0, 20.0)])
        self.assertEqual((first["range"], second["range"], second["preview"]), ("1-2", "3-4", pre + " 3-4.preview.mp4"))
        self.assertEqual(run.delivered, run.packs)

    def test_pending_waits_for_n_unless_final(self):
        """実行の途中(final でない)は n 本たまるまで届けない・終わりに n 本に満たない分は 1 本ずつの形(zip + そのまとめ動画)で届ける"""
        out = os.path.join(self.tmp, "Dropbox", "出力")
        run = self.direct_run(self.make_packs(3), out, batch=2)
        pre = "%s__配信" % self.RID
        self.r._deliver_pending(run, {}, "", final=False)
        self.assertEqual(len(run.delivered), 2)
        self.assertEqual(sorted(n for n in os.listdir(out) if n.endswith((".zip", ".json"))),
                         sorted(["%s__p1.zip" % self.RID, "%s__p2.zip" % self.RID, pre + " 1-2.group.json"]))
        self.r._deliver_pending(run, {}, "", final=False)   # 3 本目だけでは届けない
        self.assertEqual(len(run.delivered), 2)
        self.r._deliver_pending(run, {}, "", final=True)
        self.assertEqual(len(run.delivered), 3)
        self.assertEqual(sorted(os.listdir(out)), sorted(["%s__p%d.zip" % (self.RID, i) for i in (1, 2, 3)] +
                                                         ["%s__p3.preview.mp4" % self.RID, pre + " 1-2.preview.mp4", pre + " 1-2.group.json"]))
        self.r._deliver_pending(run, {}, "", final=True)   # 届け済みは二度置かない
        self.assertEqual(len(os.listdir(out)), 6)

    def test_group_stops_midway_keeps_placed_records_and_no_list(self):
        """組の途中で zip が置けなかった(ディスクがいっぱい): 置けた分の記録(deliveries.jsonl・届けた印)は残る。一覧(.group.json)は書かない
        (友人のアプリは一覧が見えたら組がそろっているとみなす)。置けなかった分の記録・書きかけは残らない"""
        out = os.path.join(self.tmp, "Dropbox", "出力")
        packs = self.make_packs(3)
        run = self.direct_run(packs, out, batch=3)
        calls = self.fail_zips_after(1)
        with self.assertRaisesRegex(A.StepError, "No space left on device"):
            self.r._deliver_pending(run, {}, "", final=True)
        self.assertEqual(calls["n"], 2)
        z1 = "%s__p1.zip" % self.RID
        self.assertEqual(run.delivered, [packs[0]])
        self.assertEqual([n for n in os.listdir(out) if n.endswith((".zip", ".json"))], [z1], "置けた 1 本目だけ・一覧なし")
        pre = "%s__配信" % self.RID
        self.assertTrue(set(n for n in os.listdir(out) if n.endswith(".preview.mp4")) <= {pre + " 1-3.preview.mp4"}, "1 本ずつのまとめ動画は組の中では置かない")
        row = friend_feedback.find_delivery(self.logs_dir(), z1)
        self.assertEqual((row["requestId"], [p["dir"] for p in row["packs"]]), (self.RID, [packs[0]]), row)
        self.assertIsNone(friend_feedback.find_delivery(self.logs_dir(), "%s__p2.zip" % self.RID))
        self.assertFalse([n for n in os.listdir(os.path.dirname(packs[0])) if n.startswith(".deliver")], "書きかけの zip・まとめ動画が残る")

    def test_nothing_placed_leaves_no_preview(self):
        """1 本目から zip が置けなかった: 先に置いたまとめ動画も残さない・記録も届けた印も無い。組(n=3)も 1 本ずつの形(n=1)も同じ"""
        for batch in (3, 1):
            out = os.path.join(self.tmp, "Dropbox%d" % batch, "出力")
            run = self.direct_run(self.make_packs(3, "packs%d" % batch), out, batch=batch)
            self.fail_zips_after(0)
            with self.assertRaisesRegex(A.StepError, "No space left on device"):
                self.r._deliver_pending(run, {}, "", final=True)
            self.assertEqual(os.listdir(out), [], "batch=%d" % batch)
            self.assertEqual(run.delivered, [], "batch=%d" % batch)
            self.assertFalse(os.path.exists(os.path.join(self.logs_dir(), "deliveries.jsonl")), "batch=%d" % batch)
            self.assertFalse([n for n in os.listdir(os.path.join(self.tmp, "packs%d" % batch)) if n.startswith(".deliver")], "書きかけが残る")

    def test_preview_copy_stops_midway_leaves_no_partial_file(self):
        """まとめ動画を 出力 へ写している途中で止まった(ディスクがいっぱい): 書きかけのまとめ動画を残さない。組(n=3)も 1 本ずつの形(n=1)も"""
        def copyfile(src, dst, **_k):
            with open(dst, "wb") as f:
                f.write(b"PART")
            raise OSError(28, "No space left on device")
        for batch in (3, 1):
            out = os.path.join(self.tmp, "Dropbox%d" % batch, "出力")
            run = self.direct_run(self.make_packs(3, "packs%d" % batch), out, batch=batch)
            with mock.patch.object(shutil, "copyfile", copyfile):
                with self.assertRaisesRegex(A.StepError, "No space left on device"):
                    self.r._deliver_pending(run, {}, "", final=True)
            self.assertEqual(os.listdir(out), [], "batch=%d" % batch)
            self.assertEqual(run.delivered, [], "batch=%d" % batch)

    def test_group_stops_the_run_with_failure_note(self):
        """通しで: 組の 2 本目の zip が置けなかった実行は「止まった」(error)。友人の受け取りに失敗の知らせの .txt、1 本目の記録は残る"""
        self.tools.known = False
        out = os.path.join(self.tmp, "Dropbox", "出力")
        self.fail_zips_after(1)
        run = self.wait(self.r.start_request([{"id": VID, "top": 2, "title": "配信", "channel": ""}], request_id=self.RID, flow="auto", deliver_dir=out)["runs"][0])
        self.assertEqual(run["state"], "error", run)
        self.assertEqual(self.states(run)["deliver"], "error")
        self.assertIn("No space left on device", run["error"])
        pre = "%s__%s" % (self.RID, run["title"])
        for _ in range(300):   # 失敗の知らせは状態が error になったあとに置く(状態だけ見て読むと、まだ無いことがある)
            names = os.listdir(out)
            if pre + ".失敗.txt" in names:
                break
            time.sleep(0.01)
        self.assertIn(pre + ".失敗.txt", names)
        self.assertEqual(sorted(n for n in names if n.endswith(".zip")), ["%s__a2.zip" % self.RID])
        self.assertFalse([n for n in names if n.endswith(".group.json")])
        self.assertIsNotNone(friend_feedback.find_delivery(self.logs_dir(), "%s__a2.zip" % self.RID))
        self.assertIsNone(friend_feedback.find_delivery(self.logs_dir(), "%s__a3.zip" % self.RID))

    def test_deliver_batch_per_request_beats_home_setting(self):
        """依頼ごとの届け方 deliver_batch(2-16)は、ホームの設定 intake.deliverBatch より優先する:
        設定が 5 でも依頼が 1 なら 1 本ずつ(組なし)・設定が 1 でも依頼が 2 なら組・依頼が指定しなければホームの設定のまま"""
        self.tools.known = False
        self.batch_prefs(5)
        out = os.path.join(self.tmp, "Dropbox", "出力")
        run = self.wait(self.r.start_request([{"id": VID, "top": 2, "title": "配信", "channel": ""}], request_id=self.RID, flow="auto", deliver_dir=out,
                                             deliver_batch=1)["runs"][0])
        self.assertEqual(run["state"], "done", run)
        self.assertEqual(self.real(run).deliver_batch, 1)
        self.assertEqual(sorted(os.listdir(out)), sorted(["%s__a%d.%s" % (self.RID, i, e) for i in (2, 3) for e in ("zip", "preview.mp4")]), "組の一覧なし")
        self.batch_prefs(1)
        out2 = os.path.join(self.tmp, "Dropbox2", "出力")
        run = self.wait(self.r.start_request([{"id": VID, "top": 2, "title": "配信", "channel": ""}], request_id="20261002-120000-def456", flow="auto",
                                             deliver_dir=out2, deliver_batch=2)["runs"][0])
        self.assertEqual((run["state"], self.real(run).deliver_batch), ("done", 2), run)
        self.assertEqual(sorted(n for n in os.listdir(out2) if n.endswith(".group.json")), ["20261002-120000-def456__%s 1-2.group.json" % run["title"]])
        out3 = os.path.join(self.tmp, "Dropbox3", "出力")   # 指定が無ければ(None)ホームの設定のまま = 1 本ずつ
        run = self.wait(self.r.start_request([{"id": VID, "top": 2, "title": "配信", "channel": ""}], request_id="20261003-120000-aaa111", flow="auto",
                                             deliver_dir=out3)["runs"][0])
        self.assertEqual((run["state"], self.real(run).deliver_batch), ("done", None), run)
        self.assertFalse([n for n in os.listdir(out3) if n.endswith(".group.json")])

    def test_batch_size_priority_and_range(self):
        """_batch_size: 依頼の指定 > ホームの設定 > 既定"""
        run = A.Run(VID, "配信", "request_auto", None)
        self.batch_prefs(3)
        self.assertEqual(self.r._batch_size(run), 3)
        self.assertEqual(self.r._batch_size(A.Run(VID, "配信", "request_auto", None, deliver_batch=7)), 7)
        self.assertEqual(self.r._batch_size(A.Run(VID, "配信", "request_auto", None, deliver_batch=1)), 1)
        self.r.prefs = None
        self.assertEqual(self.r._batch_size(run), prefs_mod.DEFAULTS["intake"]["deliverBatch"])
        self.assertEqual(self.r._batch_size(A.Run(VID, "配信", "request_auto", None, deliver_batch=10)), 10)

    def test_run_deliver_batch_range_and_saved_restore(self):
        """Run の deliver_batch: 1〜10 の整数だけ(範囲の外・bool・文字列・小数は None = ホームの設定)。saved/restore で残る・壊れた値は None に戻る"""
        for bad in (None, 0, -1, 11, 100, True, False, "3", 2.5, [2], {}):
            self.assertIsNone(A.Run(VID, "配信", "request_auto", None, deliver_batch=bad).deliver_batch, repr(bad))
        for good in (1, 2, 5, 10):
            run = A.Run(VID, "配信", "request_auto", None, request_id=self.RID, deliver_dir=self.tmp, deliver_batch=good)
            self.assertEqual(run.deliver_batch, good)
            saved = json.loads(json.dumps(run.saved()))   # 待ちの記録(autorun-active.json)を通した形
            self.assertEqual(saved["deliverBatch"], good)
            back = A.Run.restore(saved)
            self.assertEqual((back.id, back.deliver_batch, back.request_id), (run.id, good, self.RID))
        none = A.Run(VID, "配信", "request_auto", None)
        self.assertIsNone(none.saved()["deliverBatch"])
        self.assertIsNone(A.Run.restore(json.loads(json.dumps(none.saved()))).deliver_batch)
        for broken in (99, 0, "x", True, 3.5, [1]):
            self.assertIsNone(A.Run.restore(dict(none.saved(), deliverBatch=broken)).deliver_batch, repr(broken))
        old = none.saved()
        del old["deliverBatch"]   # 0.46 までの待ちの記録(鍵が無い)も読める
        self.assertIsNone(A.Run.restore(old).deliver_batch)

    def test_start_file_deliver_batch(self):
        """動画の依頼(start_file)にも deliver_batch を渡せる(範囲の外は None)"""
        media = os.path.join(self.tmp, "依頼.mp4")
        open(media, "wb").close()
        out = os.path.join(self.tmp, "Dropbox", "出力")
        run = self.wait(self.r.start_file(media, title="依頼", request_id="rid1", flow="auto", deliver_dir=out, deliver_batch=4))
        self.assertEqual((run["state"], self.real(run).deliver_batch, self.real(run).saved()["deliverBatch"]), ("done", 4, 4), run)
        media2 = os.path.join(self.tmp, "二本目.mp4")
        open(media2, "wb").close()
        run = self.wait(self.r.start_file(media2, title="二本目", request_id="rid2", flow="auto", deliver_dir=out, deliver_batch=99))
        self.assertEqual(self.real(run).deliver_batch, None)
        self.assertEqual(sorted(n for n in os.listdir(out) if n.endswith(".zip")), ["rid1__依頼.zip", "rid2__二本目.zip"])

    def test_file_auto_delivers_and_failure_note(self):
        """① 全自動(動画): 文字起こし → パック → zip。止まったら 出力\\ に理由の .txt"""
        media = os.path.join(self.tmp, "依頼.mp4")
        open(media, "wb").close()
        out = os.path.join(self.tmp, "Dropbox", "出力")
        run = self.wait(self.r.start_file(media, title="依頼", streamer="さくらみこ", request_id="rid1", flow="auto", deliver_dir=out))
        self.assertEqual((run["state"], run["mode"], list(self.states(run))), ("done", "file_auto", ["transcribe", "pack", "deliver"]), run)
        self.assertEqual(self.tools.c2r["body"]["output"].get("streamer"), "さくらみこ")   # 選んだ配信者の色でパック
        self.assertNotIn("videoTracks", self.tools.c2r["body"]["output"])                 # 選ばなければ送らない(= 1)
        self.assertEqual(sorted(self.zips(out)), ["rid1__依頼.zip"])
        media2 = os.path.join(self.tmp, "b.mp4")
        open(media2, "wb").close()
        self.tools.fail_tx = True
        run = self.wait(self.r.start_file(media2, title="二本目", request_id="rid2", flow="auto", deliver_dir=out))
        self.assertEqual(run["state"], "error")
        note = os.path.join(out, "rid2__二本目.失敗.txt")
        for _ in range(300):   # 失敗の知らせは状態が error になったあとに置く
            if os.path.exists(note):
                break
            time.sleep(0.01)
        with open(note, encoding="utf-8-sig") as f:
            self.assertIn("モデルが読めません", f.read())

    def test_file_auto_video_tracks_to_pack(self):
        """友人が選んだ映像トラックの数をパックの output.videoTracks へ"""
        media = os.path.join(self.tmp, "トラック.mp4")
        open(media, "wb").close()
        run = self.wait(self.r.start_file(media, title="トラック", request_id="rid9", flow="auto", deliver_dir=os.path.join(self.tmp, "out9"), video_tracks=4))
        self.assertEqual(run["state"], "done", run)
        self.assertEqual(self.tools.c2r["body"]["output"]["videoTracks"], 4)

    def test_file_with_speakers_diarizes_new_doc(self):
        """話す人があれば、文字起こしのあとに話者分離(人数と名前を「編集」の /api/diarize へ)"""
        self.tools.h_transcribe_POST_api_diarize = lambda path, body: (self.tools.tx_jobs.setdefault("d1", {"id": "d1", "state": "done", "src": "", "body": body}) and (200, {"id": "d1"}))
        media = os.path.join(self.tmp, "コラボ.mp4")
        open(media, "wb").close()
        run = self.wait(self.r.start_file(media, speakers={"count": 2, "names": ["兎田ぺこら"]}))
        self.assertEqual((run["state"], list(self.states(run))), ("done", ["transcribe", "diarize"]), run)
        body = self.tools.tx_jobs["d1"]["body"]
        self.assertEqual((body["tid"], body["numSpeakers"], body["names"]), ("000000000001", 2, ["兎田ぺこら"]))

    def _diarize_fake(self, sub=None):
        """話者分離(done 済みのジョブを返す)と、字幕の色を覚える API(POST /api/speakers/sub)の偽物。sub = (status, 応答) を返す関数(None = 404 = 古い編集)"""
        self.tools.h_transcribe_POST_api_diarize = lambda path, body: (self.tools.tx_jobs.setdefault("d1", {"id": "d1", "state": "done", "src": "", "body": body}) and (200, {"id": "d1"}))
        if sub is not None:
            self.tools.h_transcribe_POST_api_speakers_sub = sub

    STYLES = {"兎田ぺこら": {"color": "#7EC2FE"}}
    SPEAKERS = {"count": 2, "names": ["兎田ぺこら", "B"], "styles": STYLES}

    def test_file_with_styles_remembers_color_in_doc(self):
        """話者分離のあと、指定された字幕の色を文書に覚える(POST /api/speakers/sub {id, styles})。styles が空なら呼ばない"""
        self._diarize_fake(lambda path, body: (200, {"ok": True, "applied": list(body["styles"])}))
        media = os.path.join(self.tmp, "コラボ.mp4")
        open(media, "wb").close()
        run = self.wait(self.r.start_file(media, speakers=dict(self.SPEAKERS)))
        self.assertEqual((run["state"], list(self.states(run))), ("done", ["transcribe", "diarize"]), run)
        subs = [c for c in self.tools.calls if c[2] == "/api/speakers/sub"]
        self.assertEqual([(c[0], c[1], c[3]) for c in subs], [("transcribe", "POST", {"id": "000000000001", "styles": self.STYLES})])
        detail = next(s for s in run["steps"] if s["key"] == "diarize")["detail"]
        self.assertIn("字幕の色を覚えました", detail)
        self.assertNotIn("覚えられませんでした", detail)
        # 色の指定が無い(古い形・styles が空)なら呼ばない
        media2 = os.path.join(self.tmp, "ふたり.mp4")
        open(media2, "wb").close()
        self.tools.calls.clear()
        run = self.wait(self.r.start_file(media2, speakers={"count": 2, "names": ["A", "B"], "styles": {}}))
        self.assertEqual(run["state"], "done", run)
        self.assertFalse([c for c in self.tools.calls if c[2] == "/api/speakers/sub"])
        media3 = os.path.join(self.tmp, "古い.mp4")
        open(media3, "wb").close()
        run = self.wait(self.r.start_file(media3, speakers={"count": 2, "names": ["A", "B"]}))   # styles の鍵そのものが無い
        self.assertEqual(run["state"], "done", run)
        self.assertFalse([c for c in self.tools.calls if c[2] == "/api/speakers/sub"])

    def test_file_styles_not_sent_when_color_invalid(self):
        """実行の作り手が検査をすり抜けた色を渡しても、16 進 6 桁でなければ送らない(画面・Lua に入る前の 2 重の守り)"""
        self._diarize_fake(lambda path, body: (200, {"ok": True, "applied": []}))
        media = os.path.join(self.tmp, "x.mp4")
        open(media, "wb").close()
        run = self.wait(self.r.start_file(media, speakers={"count": 2, "names": ["A", "B"], "styles": {"A": {"color": "red\"); os.exit()"}, "B": {"color": "ff00aa"}}}))
        self.assertEqual(run["state"], "done", run)
        self.assertEqual([c[3]["styles"] for c in self.tools.calls if c[2] == "/api/speakers/sub"], [{"B": {"color": "#FF00AA"}}])

    def test_file_styles_old_editor_does_not_stop_request(self):
        """古い「編集」(sub の API が無く 404)・その他の失敗でも、依頼は止めない(一部失敗にもしない)。段の知らせに足すだけ"""
        self._diarize_fake()   # sub の API なし = 404
        media = os.path.join(self.tmp, "古い編集.mp4")
        open(media, "wb").close()
        run = self.wait(self.r.start_file(media, speakers=dict(self.SPEAKERS), flow="auto", deliver_dir=os.path.join(self.tmp, "出力")))
        self.assertEqual((run["state"], list(self.states(run))), ("done", ["transcribe", "diarize", "pack", "deliver"]), run)
        self.assertEqual(self.states(run)["diarize"], "done")
        self.assertIn("字幕の色を覚えられませんでした", next(s for s in run["steps"] if s["key"] == "diarize")["detail"])
        self.assertEqual(self.tools.c2r["body"]["output"]["speakerStyles"], self.STYLES, "パックには色を渡す")
        for i, res in enumerate(((500, {"error": "x"}), (200, {"ok": False}), (200, "x"))):
            self.tools.h_transcribe_POST_api_speakers_sub = lambda path, body, res=res: res
            m = os.path.join(self.tmp, "n%d.mp4" % i)
            open(m, "wb").close()
            run = self.wait(self.r.start_file(m, speakers=dict(self.SPEAKERS)))
            self.assertEqual((run["state"], self.states(run)["diarize"]), ("done", "done"), run)
        def boom(path, body):
            raise OSError("つながらない")
        self.tools.h_transcribe_POST_api_speakers_sub = boom
        m = os.path.join(self.tmp, "boom.mp4")
        open(m, "wb").close()
        run = self.wait(self.r.start_file(m, speakers=dict(self.SPEAKERS)))
        self.assertEqual((run["state"], self.states(run)["diarize"]), ("done", "done"), run)

    def test_file_styles_not_remembered_when_diarize_fails(self):
        """話者分離が失敗した文書には、色を覚えさせない"""
        self.tools.h_transcribe_POST_api_diarize = lambda path, body: (500, {"message": "話者分離が使えません"})
        self.tools.h_transcribe_POST_api_speakers_sub = lambda path, body: (200, {"ok": True, "applied": []})
        media = os.path.join(self.tmp, "失敗.mp4")
        open(media, "wb").close()
        run = self.wait(self.r.start_file(media, speakers=dict(self.SPEAKERS)))
        self.assertEqual(self.states(run)["diarize"], "warn", run)
        self.assertFalse([c for c in self.tools.calls if c[2] == "/api/speakers/sub"])
        self.tools.h_transcribe_POST_api_diarize = lambda path, body: (self.tools.tx_jobs.setdefault("d2", {"id": "d2", "state": "error", "error": "だめ", "src": "", "body": body}) and (200, {"id": "d2"}))
        media = os.path.join(self.tmp, "失敗2.mp4")
        open(media, "wb").close()
        run = self.wait(self.r.start_file(media, speakers=dict(self.SPEAKERS)))
        self.assertEqual(self.states(run)["diarize"], "warn", run)
        self.assertFalse([c for c in self.tools.calls if c[2] == "/api/speakers/sub"])

    def test_pack_request_has_speaker_styles_only_when_given(self):
        """パックの要求(output.speakerStyles)は、色の指定があるときだけ。無ければ鍵ごと付けない(今までと同じ要求)"""
        self._diarize_fake(lambda path, body: (200, {"ok": True, "applied": []}))
        out = os.path.join(self.tmp, "出力")
        media = os.path.join(self.tmp, "あり.mp4")
        open(media, "wb").close()
        run = self.wait(self.r.start_file(media, request_id="r1", flow="auto", deliver_dir=out, speakers=dict(self.SPEAKERS)))
        self.assertEqual(run["state"], "done", run)
        self.assertEqual(self.tools.c2r["body"]["output"]["speakerStyles"], self.STYLES)
        media = os.path.join(self.tmp, "なし.mp4")
        open(media, "wb").close()
        run = self.wait(self.r.start_file(media, request_id="r2", flow="auto", deliver_dir=out, speakers={"count": 2, "names": ["A"], "styles": {}}))
        self.assertEqual(run["state"], "done", run)
        self.assertNotIn("speakerStyles", self.tools.c2r["body"]["output"])
        media = os.path.join(self.tmp, "話者なし.mp4")
        open(media, "wb").close()
        run = self.wait(self.r.start_file(media, request_id="r3", flow="auto", deliver_dir=out))
        self.assertEqual(run["state"], "done", run)
        self.assertNotIn("speakerStyles", self.tools.c2r["body"]["output"])

    def test_request_url_with_styles_and_streamer(self):
        """URL の依頼(① 全自動): 配信者(streamer)はチャンネル名からの自動より優先・色の指定は文書に覚え、パックにも渡す。streamer が無ければ今までどおり自動"""
        self.tools.known = False
        self._diarize_fake(lambda path, body: (200, {"ok": True, "applied": []}))
        out = os.path.join(self.tmp, "Dropbox", "出力")
        run = self.wait(self.r.start_request([{"id": VID, "top": 1, "title": "配信", "channel": "Pekora Ch. 兎田ぺこら", "ranges": [(50, 60)]}], request_id="rid1", flow="auto",
                                             deliver_dir=out, speakers=dict(self.SPEAKERS), streamer="さくらみこ")["runs"][0])
        self.assertEqual((run["state"], run["streamer"], run["streamerFrom"]), ("done", "さくらみこ", None), run)
        self.assertEqual(list(self.states(run)), ["adopt", "export", "transcribe", "diarize", "pack", "deliver"])
        out_body = self.tools.c2r["body"]["output"]
        self.assertEqual((out_body["streamer"], out_body["speakerStyles"]), ("さくらみこ", self.STYLES))
        self.assertTrue([c for c in self.tools.calls if c[2] == "/api/speakers/sub"])
        # streamer なし / 空 = 今までどおりチャンネル名から自動
        for who in (None, ""):
            run = self.wait(self.r.start_request([{"id": VID, "top": 1, "title": "配信", "channel": "Pekora Ch. 兎田ぺこら", "ranges": [(70, 80)]}], request_id="rid2", flow="auto",
                                                 deliver_dir=out, streamer=who)["runs"][0])
            self.assertEqual((run["state"], run["streamer"], run["streamerFrom"]), ("done", "兎田ぺこら", "auto"), run)
            self.assertEqual(self.tools.c2r["body"]["output"]["streamer"], "兎田ぺこら")
            self.assertNotIn("speakerStyles", self.tools.c2r["body"]["output"])

    def test_file_manual_analyzes_in_studio(self):
        """③ 全部人が行う(動画): スタジオの解析のキューに入れて解析まで"""
        media = os.path.join(self.tmp, "長い.mp4")
        open(media, "wb").close()
        run = self.wait(self.r.start_file(media, title="長い", flow="manual"))
        self.assertEqual((run["state"], run["mode"], list(self.states(run))), ("done", "file_manual", ["analyze"]), run)
        add = next(c for c in self.tools.calls if c[2] == "/api/queue/add")
        self.assertEqual(add[3]["items"], [{"kind": "file", "path": media, "title": "長い"}])
        self.assertEqual(self.tools.tx_jobs, {}, "文字起こしはしない")

    def test_request_manual(self):
        self.tools.known = False
        run = self.wait(self.r.start_request([{"id": VID, "top": 3, "ranges": [(10, 20)]}], flow="manual")["runs"][0])
        self.assertEqual((run["state"], list(self.states(run))), ("done", ["analyze"]))
        self.assertFalse(any(c[2] in ("/api/video/adopt-top", "/api/video/request-marks") for c in self.tools.calls))   # ③ は解析だけ(区間も使わない)
        self.assertIsNone(run["ranges"])

    def test_request_ranges_only_skips_analysis(self):
        """区間が切り抜く数に足りている: 解析なしで、区間(前後に 2 秒の余白)だけを書き出し → 文字起こし"""
        self.tools.known = False
        res = self.r.start_request([{"id": VID, "top": 2, "title": "配信", "channel": "ch", "ranges": [(100, 190), (1, 30)], "duration": 191.0}], request_id="rid")
        run = self.wait(res["runs"][0])
        self.assertEqual((run["state"], list(self.states(run))), ("done", ["adopt", "export", "transcribe"]), run)
        self.assertFalse(any(c[2] == "/api/queue/add" for c in self.tools.calls), "解析しない")
        self.assertEqual(self.tools.request_marks, {"id": VID, "ranges": [[98.0, 191.0], [0.0, 32.0]], "auto": 0, "title": "配信", "channel": "ch"})   # 余白は 0 と配信の長さで切る
        self.assertEqual(len(self.tools.export_body["markIds"]), 2)
        self.assertEqual(run["ranges"], [[100.0, 190.0], [1.0, 30.0]])
        self.assertIn("指定の区間 2 個", next(s for s in run["steps"] if s["key"] == "adopt")["detail"])

    def test_request_ranges_filled_with_auto(self):
        """区間が切り抜く数に足りない: 解析して、足りない分だけ自動の上位(区間と重ならないもの)で埋める。この実行はその分だけを扱う"""
        self.tools.known = False
        self.tools.video["marks"] = [{"id": "old", "src": "manual", "status": "adopted", "score": None, "start": 500, "end": 510}]   # 前からある採用済みのマークは扱わない
        run = self.wait(self.r.start_request([{"id": VID, "top": 3, "ranges": [(18, 23)]}], request_id="rid")["runs"][0])
        self.assertEqual((run["state"], list(self.states(run))), ("done", ["analyze", "adopt", "export", "transcribe"]), run)
        self.assertEqual((self.tools.request_marks["ranges"], self.tools.request_marks["auto"]), ([[16.0, 25.0]], 2))
        by = {m["id"]: m for m in self.tools.video["marks"]}
        got = sorted(self.tools.export_body["markIds"])
        self.assertEqual(sorted((by[i]["start"], by[i]["src"]) for i in got), [(10, "auto"), (16.0, "manual"), (30, "auto")])   # 20〜25 秒の候補(a2)は区間と重なるので飛ばす
        self.assertNotIn("old", got)
        self.assertEqual(len(self.tools.tx_jobs), 3)

    def test_request_cut_and_resend_rebuilds_pack(self):
        """① 全自動: 友人が選んだカット(無音を削る)でパック。同じ配信・同じ区間の送り直しは、切り抜き・文字起こしを使い回してパックだけ作り直して届ける"""
        self.tools.known = False
        out = os.path.join(self.tmp, "Dropbox", "出力")
        item = {"id": VID, "top": 1, "title": "配信", "ranges": [(50, 60)]}
        run = self.wait(self.r.start_request([dict(item)], request_id="rid1", flow="auto", deliver_dir=out, cut="silence", video_tracks=2)["runs"][0])
        self.assertEqual((run["state"], list(self.states(run))), ("done", ["adopt", "export", "transcribe", "pack", "deliver"]), run)
        self.assertEqual((self.tools.c2r["body"]["spec"]["mode"], self.tools.c2r["body"]["output"]["videoTracks"]), ("silence", 2))
        self.assertEqual(len(self.zips(out)), 1)
        jobs = len(self.tools.tx_jobs)
        run = self.wait(self.r.start_request([dict(item)], request_id="rid2", flow="auto", deliver_dir=out, cut="none", video_tracks=3)["runs"][0])
        st = self.states(run)
        self.assertEqual((run["state"], st["export"], st["transcribe"], st["pack"], st["deliver"]), ("done", "skip", "skip", "done", "done"), run)
        self.assertEqual(len(self.tools.tx_jobs), jobs, "文字起こしは使い回す")
        body = self.tools.c2r["body"]
        self.assertEqual((body["spec"].get("mode"), body["spec"].get("listKind"), body["output"]["videoTracks"], body["output"].get("force")), ("list", "drop", 3, True))
        self.assertEqual(len(self.zips(out)), 2, "作り直したパックも届ける")
        # カットの指定が無い依頼(1.4.0 までのアプリ)は、ホームの設定(既定 = カットしない)
        self.wait(self.r.start_request([dict(item, ranges=[(70, 80)])], request_id="rid3", flow="auto", deliver_dir=out)["runs"][0])
        self.assertEqual(self.tools.c2r["body"]["spec"].get("listKind"), "drop")

    def test_request_weights_reanalyze_only_when_different(self):
        """解析の重み: 指定があればその重みで解析。解析済みで同じ重みなら使い回す・違えば解析し直す"""
        w = {"wAudio": 1.5, "wChat": 0.5, "wComments": 0.7}
        self.tools.analyze = {"count": 12, "wAudio": 1.0}
        self.tools.known = False
        run = self.wait(self.r.start_request([{"id": VID, "top": 1}], weights=w)["runs"][0])
        self.assertEqual(self.states(run)["analyze"], "done", run)
        add = [c for c in self.tools.calls if c[2] == "/api/queue/add"]
        self.assertEqual(add[-1][3]["settings"], {"count": 12, "wAudio": 1.5, "wChat": 0.5, "wComments": 0.7})   # ほかの設定はスタジオのまま
        self.tools.video["analysis"] = {"at": 3, "spec": dict(w, count=12)}
        run = self.wait(self.r.start_request([{"id": VID, "top": 1}], weights=dict(w))["runs"][0])
        self.assertEqual(self.states(run)["analyze"], "skip")
        self.tools.queue.clear()
        run = self.wait(self.r.start_request([{"id": VID, "top": 1}], weights=dict(w, wChat=2.0))["runs"][0])
        self.assertEqual(self.states(run)["analyze"], "done", run)
        self.assertEqual(len([c for c in self.tools.calls if c[2] == "/api/queue/add"]), 2)
        run = self.wait(self.r.start_request([{"id": VID, "top": 1}])["runs"][0])   # 指定なし: 解析済みなら使い回す
        self.assertEqual(self.states(run)["analyze"], "skip")
        self.assertIsNone(A.clean_weights({"wAudio": 4, "wChat": 1, "wComments": 1}))
        self.assertIsNone(A.clean_weights({"wAudio": True, "wChat": 1, "wComments": 1}))

    def test_range_helpers(self):
        self.assertEqual(A.pad_range(100, 190), [98.0, 192.0])
        self.assertEqual(A.pad_range(1, 30, 31.0), [0.0, 31.0])
        self.assertEqual(A.pad_range(0, 3600), [0.0, 3600.0])        # 長さの上限いっぱいなら余白は足さない
        self.assertEqual(A.pad_range(10, 3609), [9.5, 3609.5])       # 余白を減らして上限に収める
        self.assertEqual(A.clean_ranges(None), [])
        self.assertEqual(A.clean_ranges([[1, 2.26], (3, 4)]), [(1.0, 2.3), (3.0, 4.0)])
        for bad in ("x", [[1]], [[2, 1]], [[0, 3601]], [[-1, 5]], [["1", 2]], [[True, 2]], [[i, i + 1] for i in range(11)]):
            with self.assertRaises(ValueError, msg=bad):
                A.clean_ranges(bad)
        res = self.r.start_request([{"id": VID, "top": 1, "ranges": [[5, 1]]}])
        self.assertEqual((res["runs"], res["skipped"][0]["reason"]), ([], "区間の指定が正しくありません"))


class TestDeferred(Base):
    """あとから解析(測るため。2026-10-05): 区間だけで終わった依頼(URL)の配信を一覧に足し、待ちが無くなったらスタジオの設定で解析する。
    新しい実行が入ったら止めて一覧に戻す。一覧は logs/autorun-deferred.json(起動し直しても続く)"""
    marks = []
    analysis = False

    def setUp(self):
        super().setUp()
        self.r.close()
        from unittest import mock
        self.env_patch = mock.patch.dict(os.environ)
        self.env_patch.start()
        os.environ.pop(A.DEFER_ENV, None)   # 開発者のシェルで off にしていても、このテストは on で流す
        self.logs = os.path.join(self.tmp, "logs")
        self.tools.analyze = {"count": 12}   # スタジオで保存した解析の設定
        self.r = self.runner()

    def tearDown(self):
        self.r.close()
        self.env_patch.stop()
        super().tearDown()

    def runner(self, **kw):
        from manage.cases import cases
        kw.setdefault("defer_idle", 0)
        kw.setdefault("defer_retry", 0)
        return A.AutoRunner(self.tools, os.path.join(self.tmp, "repo"), self.env, poll=0, sleep=lambda s: None, find_pack=cases.find_pack,
                            log_dir=self.logs, **kw)

    @property
    def defer_path(self):
        return os.path.join(self.logs, A.DEFER_FILE)

    def until(self, fn, msg="", timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            got = fn()
            if got:
                return got
            time.sleep(0.01)
        self.fail("待ちきれません: %s" % msg)

    def lines(self):
        return runlog.read_runs_log(os.path.join(self.logs, runlog.RUNS_LOG))

    def logged(self, run_id):
        """実行の記録に書かれるまで待つ(一覧への足し・外しは記録より先に済んでいる)"""
        return self.until(lambda: next((x for x in self.lines() if x["id"] == run_id), None), "記録 %s" % run_id)

    def posts(self):
        return [r for r in self.r.snapshot()["runs"] if r["mode"] == A.POST_MODE]

    def ranges_request(self, ranges=((50, 60),), **kw):
        self.tools.known = False
        item = {"id": VID, "top": 1, "title": "配信", "channel": "ch", "ranges": list(ranges)}
        return self.r.start_request([item], request_id=kw.pop("request_id", "rid1"), **kw)["runs"][0]

    def write_defer(self, items, **extra):
        os.makedirs(self.logs, exist_ok=True)
        with open(self.defer_path, "w", encoding="utf-8") as f:
            json.dump(dict({"v": 1, "items": items, "dropped": []}, **extra), f, ensure_ascii=False)

    def item(self, **kw):
        return dict({"videoId": VID, "title": "配信", "added": int(time.time() * 1000), "tries": 0, "reason": "", "lastTry": None, "requestId": "rid0"}, **kw)

    def test_ranges_only_request_is_analyzed_later(self):
        """区間だけの依頼が終わる → 一覧に入る → 待ちが無いので解析(スタジオの保存した設定。友人の重みは使わない)→ 一覧から外す。
        友人へは何も届けない・依頼の id を持たない・実行の記録に mode で残る・依頼の行には videoId と ranges(余白の前)"""
        self.tools.hold_q = True
        out = os.path.join(self.tmp, "Dropbox", "出力")
        req = self.ranges_request(flow="auto", deliver_dir=out, weights={"wAudio": 2.0, "wChat": 0.5, "wComments": 0.5})
        rec = self.logged(req["id"])
        self.assertEqual((rec["state"], rec["mode"], rec["videoId"], rec["ranges"]), ("done", "request_auto", VID, [[50.0, 60.0]]), rec)
        self.assertNotIn("analyze", [s["key"] for s in rec["steps"]])
        post = self.until(lambda: next((p for p in self.posts() if p["state"] == "running"), None), "あとから解析が始まる")
        d = self.r.deferred()
        self.assertEqual(([(i["videoId"], i["tries"], i["requestId"]) for i in d["items"]], d["running"]), ([(VID, 0, "rid1")], VID))
        with open(self.defer_path, encoding="utf-8") as f:
            self.assertEqual([i["videoId"] for i in json.load(f)["items"]], [VID], "一覧はファイルにある(解析の最中も残す)")
        self.assertEqual((post["modeLabel"], post["requestId"], post["ranges"], [s["key"] for s in post["steps"]]),
                         ("あとから解析(測るため)", None, None, ["analyze"]))
        self.until(lambda: any(c[2] == "/api/queue/add" for c in self.tools.calls), "解析のキューに入れる")
        add = [c for c in self.tools.calls if c[2] == "/api/queue/add"]
        self.assertEqual(add[-1][3]["settings"], {"count": 12}, "スタジオで保存した設定のまま(友人の重みは使わない)")
        self.tools.hold_q = False
        rec = self.logged(post["id"])
        self.assertEqual((rec["state"], rec["mode"], rec["modeLabel"], rec["requestId"], rec["videoId"]),
                         ("done", A.POST_MODE, "あとから解析(測るため)", None, VID), rec)
        self.assertIn("友人には何も届けません", rec["message"])
        self.assertEqual(self.r.deferred()["items"], [])
        self.assertEqual(sorted(os.listdir(out)), ["rid1__r1.preview.mp4", "rid1__r1.zip"], "あとから解析は届けない(依頼のパック 1 本 = zip とそのまとめ動画だけ)")
        rng = next(m for m in self.tools.video["marks"] if m["id"] == "r1")
        self.assertEqual((rng["src"], rng["status"]), ("manual", "exported"))
        # 案件の行の「前回」は依頼の結果のまま(あとから解析は past に入れない。history には残る)
        self.r.close()
        self.r = self.runner()
        self.assertEqual([(p["mode"], p["state"]) for p in self.r.snapshot()["past"]], [("request_auto", "done")])
        self.assertEqual([x["mode"] for x in self.r.history()["runs"]], [A.POST_MODE, "request_auto"])
        time.sleep(0.1)
        self.assertEqual(self.posts(), [], "一覧が空なら何もしない")

    def test_not_deferred(self):
        """解析した依頼・③・取り消した依頼・区間のマークを作る前に止まった依頼・まとめて実行は一覧に入れない"""
        self.tools.known = False
        r1 = self.r.start_request([{"id": VID, "top": 2, "ranges": [(50, 60)]}], request_id="a")["runs"][0]   # 区間が足りない = 解析あり
        self.assertEqual(self.logged(r1["id"])["steps"][0]["key"], "analyze")
        r2 = self.r.start_request([{"id": VID, "top": 1, "ranges": [(50, 60)]}], flow="manual")["runs"][0]
        self.logged(r2["id"])
        self.tools.hold = True
        r3 = self.ranges_request(ranges=[(70, 80)])   # 新しい区間(書き出しで止まる。前の区間だと書き出し済みですぐ終わる)
        self.until(lambda: next(x for x in self.r.snapshot()["runs"] if x["id"] == r3["id"])["steps"][1]["state"] == "run", "書き出しの途中")
        self.r.cancel(r3["id"])
        self.assertEqual(self.logged(r3["id"])["state"], "cancelled")
        self.tools.hold = False
        self.tools.h_studio_POST_api_video_request_marks = lambda path, body: (400, {"message": "区間がおかしい"})
        r4 = self.ranges_request()
        self.assertEqual(self.logged(r4["id"])["state"], "error")
        self.logged(self.r.start(VID, "adopted")["id"])
        self.assertEqual(self.r.deferred()["items"], [])
        self.assertEqual(self.posts(), [])

    def test_error_after_ranges_is_deferred(self):
        """区間のマークを作ったあとで止まった(一部失敗)依頼は入れる"""
        self.tools.fail_tx = True
        self.tools.hold_q = True
        r = self.ranges_request()
        self.assertEqual(self.logged(r["id"])["state"], "error")
        self.assertEqual([i["videoId"] for i in self.r.deferred()["items"]], [VID])

    def test_off_env(self):
        """YTT_DEFER_ANALYZE=off: 一覧に足さない・残っている一覧も始めない"""
        os.environ[A.DEFER_ENV] = "off"
        self.r.close()
        self.write_defer([self.item(videoId="zzzzzzzzzzz")])
        self.r = self.runner()
        r = self.ranges_request()
        self.logged(r["id"])
        time.sleep(0.1)
        self.assertEqual(([i["videoId"] for i in self.r.deferred()["items"]], self.posts()), (["zzzzzzzzzzz"], []))
        self.assertFalse(self.r.deferred()["on"])

    def test_analyzed_or_missing_is_just_removed(self):
        """スタジオで解析済みなら何もせず外す・スタジオに無ければ外す(どちらも理由を dropped に)"""
        self.r.close()
        self.tools.video["analysis"] = {"at": 9}
        self.write_defer([self.item()])
        self.r = self.runner()
        d = self.until(lambda: (lambda d: d if d["dropped"] else None)(self.r.deferred()), "外れる")
        self.assertEqual((d["items"], d["dropped"][0]["videoId"]), ([], VID))
        self.assertIn("解析済み", d["dropped"][0]["reason"])
        self.r.close()
        self.tools.known = False
        self.write_defer([self.item()])
        self.r = self.runner()
        d = self.until(lambda: (lambda d: d if d["dropped"] else None)(self.r.deferred()), "外れる")
        self.assertIn("スタジオに配信がありません", d["dropped"][0]["reason"])
        self.assertFalse(any(c[2] == "/api/queue/add" for c in self.tools.calls))
        self.assertEqual(self.posts(), [])

    def test_new_run_preempts_and_resumes(self):
        """あとから解析の最中に新しい実行(同じ配信でもよい)が入る → すぐ止めて(スタジオの解析も取り消す)一覧に戻す(回数は増やさない)
        → 新しい実行が先に終わる → また始まる"""
        self.r.close()
        self.write_defer([self.item()])
        self.tools.hold_q = True
        self.r = self.runner()   # 起動し直した入口: 残った一覧を続ける
        first = self.until(lambda: next((p for p in self.posts() if p["state"] == "running"), None), "始まる")
        self.until(lambda: any(q["status"] == "running" for q in self.tools.queue), "解析のキュー")
        new = self.r.start(VID, "adopted")   # あとから解析は「すでに実行中」の理由にしない
        rec = self.logged(first["id"])
        self.assertEqual(rec["state"], "cancelled")
        self.assertIn("新しい実行を先に", rec["message"])
        cancels = [c for c in self.tools.calls if c[2] == "/api/queue/cancel"]
        self.assertEqual([c[3] for c in cancels], [{"qid": "q1"}], "スタジオの解析も取り消す")
        self.assertEqual(self.tools.queue[0]["status"], "cancelled")
        self.assertEqual(self.r.deferred()["items"][0]["tries"], 0, "止めただけでは回数を増やさない")
        new_rec = self.logged(new["id"])
        second = self.until(lambda: next((p for p in self.posts() if p["id"] != first["id"]), None), "また始まる")
        self.assertGreaterEqual(second["created"], new_rec["finished"], "新しい実行が終わってから")
        self.tools.hold_q = False
        self.assertEqual(self.logged(second["id"])["state"], "done")
        self.assertEqual(self.r.deferred()["items"], [])

    def test_close_keeps_list_and_restart_continues(self):
        """入口を終える(解析の最中)→ 一覧に残る(回数はそのまま)→ 起動し直すと続けて解析する"""
        self.tools.hold_q = True
        r = self.ranges_request()
        self.logged(r["id"])
        post = self.until(lambda: next((p for p in self.posts() if p["state"] == "running"), None), "始まる")
        self.until(lambda: any(q["status"] == "running" for q in self.tools.queue), "解析のキュー")
        self.r.close()
        self.assertIn("次に起動したときに続けます", self.logged(post["id"])["message"])
        with open(self.defer_path, encoding="utf-8") as f:
            self.assertEqual([(i["videoId"], i["tries"]) for i in json.load(f)["items"]], [(VID, 0)])
        self.tools.hold_q = False
        self.r = self.runner()
        p2 = self.until(lambda: next((p for p in self.posts() if p["state"] == "done"), None), "続きの解析が終わる")
        self.assertEqual(p2["mode"], A.POST_MODE)
        self.until(lambda: self.r.deferred()["items"] == [] or None, "一覧から外れる")

    def test_three_failures_and_expiry(self):
        """3 回失敗したら捨てる(理由を残す)・失敗は記録に mode post_analyze の失敗として1行ずつ。3 日たったものも捨てる"""
        self.tools.h_studio_POST_api_queue_add = lambda path, body: (200, {"added": [], "rejected": [{"reason": "yt-dlp が見つかりません"}]})
        r = self.ranges_request()
        self.logged(r["id"])
        d = self.until(lambda: (lambda d: d if d["dropped"] else None)(self.r.deferred()), "捨てる")
        self.assertEqual(d["items"], [])
        self.assertIn("3 回失敗したので捨てました", d["dropped"][0]["reason"])
        self.assertIn("yt-dlp が見つかりません", d["dropped"][0]["reason"])
        posts = self.until(lambda: (lambda xs: xs if len(xs) == 3 else None)([x for x in self.lines() if x["mode"] == A.POST_MODE]), "3行")
        self.assertEqual([x["state"] for x in posts], ["error"] * 3)
        self.assertIn("もう解析しません", posts[-1]["message"])
        self.r.close()
        old = int((time.time() - 15 * 86400) * 1000)
        self.write_defer([self.item(added=old)])
        self.r = self.runner()
        d = self.until(lambda: (lambda d: d if d["dropped"] else None)(self.r.deferred()), "捨てる")
        self.assertIn("3 日たったので", d["dropped"][0]["reason"])
        time.sleep(0.1)
        self.assertEqual((len([x for x in self.lines() if x["mode"] == A.POST_MODE]), self.posts()), (3, []), "捨てたものは解析しない")

    def test_stop_for_restart(self):
        """「起動し直す」の前(stop_deferred): 止めて(スタジオの解析も取り消す)止まるまで待つ・回数は増やさない・しばらく次を始めない"""
        self.assertTrue(self.r.stop_deferred(hold=0))   # 動いていなければすぐ
        self.r.close()
        self.write_defer([self.item()])
        self.tools.hold_q = True
        self.r = self.runner()
        post = self.until(lambda: next((p for p in self.posts() if p["state"] == "running"), None), "始まる")
        self.until(lambda: any(q["status"] == "running" for q in self.tools.queue), "解析のキュー")
        self.assertTrue(self.r.stop_deferred(hold=3600))
        cur = next(p for p in self.posts() if p["id"] == post["id"])
        self.assertEqual(cur["state"], "cancelled")
        self.assertIn("起動し直すため止めました", self.logged(post["id"])["message"])
        self.assertEqual(self.tools.queue[0]["status"], "cancelled")
        self.assertEqual(self.r.deferred()["items"][0]["tries"], 0)
        time.sleep(0.1)
        self.assertEqual(len(self.posts()), 1, "しばらく次を始めない")

    def test_user_cancel_counts_as_try(self):
        """人が中止した: 失敗と同じに数えて、少し待ってから試し直す"""
        self.r.close()
        self.write_defer([self.item()])
        self.tools.hold_q = True
        self.r = self.runner(defer_retry=3600)
        post = self.until(lambda: next((p for p in self.posts() if p["state"] == "running"), None), "始まる")
        self.r.cancel(post["id"])
        self.logged(post["id"])
        it, = self.r.deferred()["items"]
        self.assertEqual((it["tries"], it["reason"]), (1, "中止しました"))
        time.sleep(0.1)
        self.assertEqual(len(self.posts()), 1, "すぐには始めない")

    def test_import_old_requests_once(self):
        """この機能の前の依頼: 起動のあと1回、実行の記録(今のファイルと .1)から区間だけで終わった依頼を足す(新しい順に 20 本・30 日以内)"""
        self.r.close()
        now = int(time.time() * 1000)
        step = lambda k, s="done": {"key": k, "state": s}
        base = {"v": 1, "kind": "video", "docId": None, "mode": "request", "state": "done", "ranges": [[1.0, 2.0]], "requestId": "old",
                "steps": [step("adopt"), step("export"), step("transcribe")]}
        recs = [dict(base, id="ok%02d" % i, videoId="v%010d" % i, title="t%d" % i, finished=now - (30 - i) * 3600000) for i in range(25)]
        recs += [dict(base, id="an", videoId="analyzed000", finished=now, steps=[step("analyze")] + base["steps"]),
                 dict(base, id="ca", videoId="cancelled00", finished=now, state="cancelled"),
                 dict(base, id="ol", videoId="tooold00000", finished=now - 31 * 86400000),
                 dict(base, id="ma", videoId="manual00000", finished=now, mode="request_manual", ranges=None, steps=[step("analyze")]),
                 dict(base, id="er", videoId="adopterr000", finished=now, state="error", steps=[step("adopt", "error")]),
                 dict(base, id="nr", videoId="noranges000", finished=now, ranges=None),
                 dict(base, id="fu", videoId="fullrun0000", finished=now, mode="full"),
                 dict(base, id="pe", videoId="parterr0000", finished=now, state="error", steps=[step("adopt"), step("export", "error")])]
        os.makedirs(self.logs)
        log = os.path.join(self.logs, runlog.RUNS_LOG)
        with open(log + ".1", "w", encoding="utf-8") as f:   # 古い方(.1)にもある
            f.write("".join(json.dumps(x) + "\n" for x in recs[:10]))
        with open(log, "w", encoding="utf-8") as f:
            f.write("".join(json.dumps(x) + "\n" for x in recs[10:]))
        self.r = self.runner(defer_idle=3600)   # 始めない(取り込みだけ見る)
        d = self.r.deferred()
        got = [i["videoId"] for i in d["items"]]
        self.assertEqual(len(got), A.DEFER_IMPORT_MAX)
        self.assertEqual(got[0], "parterr0000", "一部失敗も入る・新しい順")
        self.assertEqual(got[1:], ["v%010d" % i for i in range(24, 5, -1)])
        self.assertFalse({"analyzed000", "cancelled00", "tooold00000", "manual00000", "adopterr000", "noranges000", "fullrun0000"} & set(got))
        self.assertEqual((d["items"][1]["title"], d["items"][1]["tries"], d["items"][1]["requestId"]), ("t24", 0, "old"))
        with open(self.defer_path, encoding="utf-8") as f:
            saved = json.load(f)
        self.assertTrue(saved["imported"])
        # 2回目の起動では取り込まない(一覧を空にしておいても戻らない)
        self.r.close()
        self.write_defer([], imported=saved["imported"])
        self.r = self.runner(defer_idle=3600)
        self.assertEqual(self.r.deferred()["items"], [])

    def test_studio_replace_auto_keeps_request_marks(self):
        """スタジオの解析の結果の反映(store.replace_auto)は、依頼の区間のマーク(手動・採用済み・書き出し済み)を残す。
        スタジオの部品は名前が重なるので、別のプロセスで本物の store を動かして確かめる"""
        import subprocess
        src = os.path.dirname(HERE)   # RS3-5: store は human/review に移ったので src を渡す
        code = r'''
import json, os, sys, tempfile
sys.path.insert(0, sys.argv[1])
from human.review import store
from ytt import studio_env
d = tempfile.mkdtemp(); studio_env.set_home(d)
st = store.Store(os.path.join(d, "data.json"))
vid = "reqdefer001"
st.ensure({"kind": "youtube", "videoId": vid, "name": vid}, "t", "c")
rids, _aids, _v = st.request_marks(vid, [[98.0, 192.0], [10.0, 20.0], [300.0, 330.0]], 0)
v = st.get(vid)[0]
os.makedirs(os.path.join(d, "out"), exist_ok=True)
clip = os.path.join(d, "out", "c.mp4"); open(clip, "wb").close()
m = next(x for x in v["marks"] if x["id"] == rids[1])
st.mark_exported(vid, rids[1], "c.mp4", m["start"], m["end"], clip)
before = {x["id"]: (x["src"], x["status"], x["start"], x["end"]) for x in st.get(vid)[0]["marks"]}
cand = lambda s, e, sc: {"start": s, "end": e, "score": sc, "reasons": ["x"], "peak": s + 1, "parts": {}}
n = st.replace_auto(vid, [cand(98.2, 191.8, 9.0), cand(12, 18, 5.0), cand(500, 520, 3.0)], {"spec": {}}, 3600.0, {})
after = {x["id"]: (x["src"], x["status"], x["start"], x["end"]) for x in st.get(vid)[0]["marks"]}
print(json.dumps({"rids": rids, "before": before, "after": after, "n": n, "analysis": bool(st.get(vid)[0].get("analysis"))}))
'''
        env = dict(os.environ, YTT_DATA_DIR="inplace", PYTHONIOENCODING="utf-8")
        p = subprocess.run([sys.executable, "-c", code, src], capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        got = json.loads(p.stdout.strip().splitlines()[-1])
        for rid in got["rids"]:
            self.assertEqual(got["after"][rid], got["before"][rid], "区間のマークはそのまま: %s" % rid)
        self.assertEqual([got["after"][r][:2] for r in got["rids"]], [["manual", "adopted"], ["manual", "exported"], ["manual", "adopted"]])
        self.assertTrue(got["analysis"])
        # 区間と ±0.5 秒で同じ候補(98.2〜191.8)は作られない(測る道具が知っておくこと)・重なるだけの候補(12〜18)と別の所(500〜)は入る
        autos = sorted(v[2:] for k, v in got["after"].items() if v[0] == "auto")
        self.assertEqual((got["n"], autos), (2, [[12.0, 18.0], [500.0, 520.0]]))


class TestFriendLength(Base):
    """友人の区間の長さを、依頼の自動の候補の長さに使う(2026-10-05): dev/eval_marks.py --json の結果の clipLength(友人の区間)を読み、
    依頼(URL)で足りない分を自動で埋めるために解析するときだけ、解析の設定 length・preRatio に重ねる"""
    marks = []
    analysis = False

    def setUp(self):
        super().setUp()
        from unittest import mock
        self.env_patch = mock.patch.dict(os.environ)
        self.env_patch.start()
        os.environ.pop(A.FRIEND_LENGTH_ENV, None)
        self.logs = []
        self.r.log = self.logs.append
        self.tools.analyze = {"count": 12, "length": 45, "preRatio": 0.65}
        self.tools.known = False
        from manage.cases import cases
        self.folder = os.path.join(os.path.dirname(cases.locations(self.r.root, self.env)["studio"]), "evals", "marks")

    def tearDown(self):
        self.env_patch.stop()
        super().tearDown()

    def write_eval(self, n=20, videos=5, p50=38.4, pre_n=10, pre_med=0.6123, age_days=0, raw=None):
        os.makedirs(self.folder, exist_ok=True)
        name = time.strftime("%Y%m%d-%H%M%S", time.localtime(time.time() - age_days * 86400)) + ".json"
        res = {"clipLength": {"samples": {"friend": {"n": n, "videos": videos, "outliers": 0, "length": {"n": n, "p50": p50, "median": p50}}},
                              "peakRatio": {"friend": {"n": pre_n, "median": pre_med}}}}
        with open(os.path.join(self.folder, name), "w", encoding="utf-8") as f:
            f.write(raw if raw is not None else json.dumps(res))
        return name

    def run_request(self, **kw):
        res = self.r.start_request([{"id": VID, "top": 3, "ranges": [(50, 60)]}], request_id="rid", **kw)   # 区間が足りない = 解析あり
        end = time.time() + 10
        while time.time() < end:
            cur = next(x for x in self.r.snapshot()["runs"] if x["id"] == res["runs"][0]["id"])
            if cur["state"] not in ("queued", "running"):
                return cur
            time.sleep(0.01)
        self.fail("終わらない")

    def settings(self):
        adds = [c for c in self.tools.calls if c[2] == "/api/queue/add"]
        return adds[-1][3]["settings"] if adds else None

    def test_used_when_enough(self):
        name = self.write_eval()
        run = self.run_request(weights={"wAudio": 1.5, "wChat": 1.0, "wComments": 1.0})
        self.assertEqual(run["state"], "done", run)
        self.assertEqual(self.settings(), {"count": 12, "length": 38, "preRatio": 0.61, "wAudio": 1.5, "wChat": 1.0, "wComments": 1.0})
        self.assertEqual(run["friendLength"], {"length": 38, "preRatio": 0.61, "file": name, "samples": 20, "videos": 5})
        self.assertIn("長さ 38 秒・山の前 0.61(友人の区間の実績から)", next(s for s in run["steps"] if s["key"] == "analyze")["detail"])

    def test_not_enough(self):
        for n, videos in ((19, 5), (20, 4)):
            self.tools.calls.clear()
            self.tools.queue.clear()
            self.tools.video["analysis"] = None
            for f in os.listdir(self.folder) if os.path.isdir(self.folder) else []:
                os.remove(os.path.join(self.folder, f))
            self.write_eval(n=n, videos=videos)
            run = self.run_request()
            self.assertEqual((self.settings(), run["friendLength"]), ({"count": 12, "length": 45, "preRatio": 0.65}, None), (n, videos))
        self.assertTrue(any("見本がまだ少ない" in x for x in self.logs), self.logs)

    def test_clamp_and_no_pre(self):
        self.write_eval(p50=150, pre_n=9)
        self.assertEqual(self.r._friend_length()["length"], 120)
        self.assertNotIn("preRatio", self.r._friend_length())
        self.write_eval(p50=4.2, pre_n=30, pre_med=0.95)   # 新しいファイルを読む
        fl = self.r._friend_length()
        self.assertEqual((fl["length"], fl["preRatio"]), (10, 0.9))
        self.write_eval(p50=37.5, pre_n=10, pre_med=0.1)
        fl = self.r._friend_length()
        self.assertEqual((fl["length"], fl["preRatio"]), (38, 0.3))   # 四捨五入・0.3〜0.9 に収める

    def test_old_broken_missing(self):
        self.assertIsNone(self.r._friend_length())   # まだ無い
        self.write_eval(age_days=31)
        self.assertIsNone(self.r._friend_length())
        self.assertIn("古い", self.logs[-1])
        for raw in ("{壊れた", json.dumps({"clipLength": {"samples": {"friend": {"n": "20", "videos": 5, "length": {"p50": 30}}}}}),
                    json.dumps({"clipLength": {"samples": {"friend": {"n": 20, "videos": 5, "length": {"p50": "30"}}}}}), json.dumps([1])):
            time.sleep(1.05)   # ファイル名は秒まで(いちばん新しいものを読む)
            self.write_eval(raw=raw)
            self.assertIsNone(self.r._friend_length(), raw)
            self.assertIn("読めない", self.logs[-1])
        run = self.run_request()
        self.assertEqual((run["state"], self.settings()["length"]), ("done", 45))

    def test_only_for_requests(self):
        """ユーザー自身のまとめて実行・あとから解析(測るため)・依頼 ③ には効かない。解析済みなら使い回す(長さが違っても解析し直さない)"""
        self.write_eval()
        self.tools.known = True
        run = self.run_one("full")
        self.assertEqual((run["state"], self.settings()), ("done", {"count": 12, "length": 45, "preRatio": 0.65}))
        self.assertIsNone(run["friendLength"])
        self.tools.video["analysis"] = None
        self.tools.calls.clear()
        post = A.Run(VID, "配信", A.POST_MODE, None)
        self.r._execute(post)
        self.assertEqual((self.settings(), post.friend_length), ({"count": 12, "length": 45, "preRatio": 0.65}, None))
        self.tools.video["analysis"] = None
        self.tools.calls.clear()
        res = self.r.start_request([{"id": VID, "top": 3}], flow="manual")["runs"][0]
        end = time.time() + 10
        while time.time() < end and next(x for x in self.r.snapshot()["runs"] if x["id"] == res["id"])["state"] in ("queued", "running"):
            time.sleep(0.01)
        self.assertEqual(self.settings()["length"], 45)
        # 解析済み(スタジオの設定の長さで)の配信: 依頼でも解析し直さない
        self.tools.video["analysis"] = {"at": 5, "spec": {"length": 45}}
        self.tools.calls.clear()
        run = self.run_request()
        self.assertEqual((self.states(run)["analyze"], self.settings(), run["friendLength"]), ("skip", None, None))

    def test_off(self):
        self.write_eval()
        os.environ[A.FRIEND_LENGTH_ENV] = "off"
        self.assertIsNone(self.r._friend_length())
        del os.environ[A.FRIEND_LENGTH_ENV]
        self.assertEqual(self.r._friend_length()["length"], 38)

        class P:
            def __init__(self, v):
                self.v = v

            def get(self, names):
                return {"autorun": {"friendLength": self.v}}
        self.r.prefs = P(False)
        self.assertIsNone(self.r._friend_length())
        self.r.prefs = P(True)
        self.assertEqual(self.r._friend_length()["length"], 38)


class TestMedia30fps(unittest.TestCase):
    """2026-10-04 Q1: 素材がちょうど 30fps なら、まとめて実行のパックは設定の packFps に関係なく 30"""

    def test_media_is_30fps(self):
        import shutil, subprocess, tempfile
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg が無い")
        d = tempfile.mkdtemp()
        try:
            for fps, want in (("30", True), ("60", False), ("30000/1001", False)):
                p = os.path.join(d, "v%s.mp4" % fps.replace("/", "_"))
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=%s:duration=1" % fps,
                                "-c:v", "libx264", "-pix_fmt", "yuv420p", p], check=True, timeout=60)
                self.assertEqual(A._media_is_30fps(p), want, fps)
            self.assertFalse(A._media_is_30fps(os.path.join(d, "none.mp4")))
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
