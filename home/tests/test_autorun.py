#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""まとめて実行(home/autorun.py)の段取りのテスト。ツールの API は偽物(FakeTools)で、本物の通し確認は home/tests/e2e_autorun.py。
実行(リポジトリ直下): python -m unittest home/tests/test_autorun.py"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
TESTS = os.path.dirname(os.path.abspath(__file__))   # home/tests
HERE = os.path.dirname(TESTS)   # home(入口の部品)
sys.path.insert(0, HERE)
sys.path.insert(0, TESTS)
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


class TestMarks(Base):
    """スタジオのマークの行の「この後を」(docs/archive/followup-2026-09-27.md の 3): そのマークだけ 書き出し → 文字起こし → パック"""
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
        """配信者の名前(字幕の文字の色。docs/archive/followup-2026-09-27.md の 4): 照らし合わせた名前を cut2resolve に渡す。見つからなければ始める前に断る"""
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


class TestNew(Base):
    """スタジオの ① 探す で選んだ配信(docs/archive/followup-2026-09-27.md の 5): まだスタジオに無い配信を「解析から全部」"""
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

    def test_queued_runs_are_cancelled_on_close(self):
        self.tools.hold = True
        self.r.start(VID, "adopted")
        second = self.r.start("zzzzzzzzzzz", "adopted")
        self.r.close()
        got = {x["id"]: x for x in self.r.snapshot()["runs"]}
        self.assertEqual(got[second["id"]]["state"], "cancelled")

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
        import cases
        return A.AutoRunner(self.tools, os.path.join(self.tmp, "repo"), self.env, poll=0, sleep=lambda s: None, find_pack=cases.find_pack,
                            log_dir=kw.pop("log_dir", self.logs), **kw)

    @property
    def path(self):
        return os.path.join(self.logs, A.RUNS_LOG)

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

    def test_close_writes_queued(self):
        self.tools.hold = True
        first = self.r.start(VID, "adopted")
        second = self.r.start("zzzzzzzzzzz", "adopted")
        self.r.close()
        got = {x["id"]: x for x in self.wait_lines(2)}   # 順番待ち(close で書く)+ 実行中(止まったときに書く)
        self.assertEqual((got[second["id"]]["state"], got[second["id"]]["message"]), ("cancelled", "入口を終了しました"))
        self.assertEqual(got[first["id"]]["state"], "cancelled")
        self.assertTrue(got[second["id"]]["finished"])

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


class TestRequests(Base):
    """友人からの依頼(home/intake.py)の形: request = 解析 → 採用 → 書き出し → 文字起こし(パックなし)/ file = 動画を文字起こしだけ"""
    marks = []
    analysis = False

    def setUp(self):
        super().setUp()
        import prefs as P
        from ytt_core import fsio
        self.prefs = P.Prefs(os.path.join(self.tmp, "prefs.json"), fsio.atomic_write)
        self.r.prefs = self.prefs
        self.r.log_path = os.path.join(self.tmp, "logs", A.RUNS_LOG)
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
        recs = A.read_runs_log(self.r.log_path)
        self.assertEqual([(x["kind"], x["sourcePath"]) for x in recs], [("file", media)])
        # もう一度: 文字起こし済みなので飛ばす
        run = self.wait(self.r.start_file(media))
        self.assertEqual(self.states(run), {"transcribe": "skip"})
        with self.assertRaisesRegex(ValueError, "見つかりません"):
            self.r.start_file(os.path.join(self.tmp, "nai.mp4"))

    def zips(self, out):
        import zipfile
        return {n: sorted(zipfile.ZipFile(os.path.join(out, n)).namelist()) for n in os.listdir(out)}

    def test_request_auto_delivers_packs(self):
        """① 全自動(URL): 解析 → 採用 → 書き出し → 文字起こし → パック → zip を 出力\\ へ(友人のアプリの「受け取る」)"""
        self.tools.known = False
        out = os.path.join(self.tmp, "Dropbox", "出力")
        run = self.wait(self.r.start_request([{"id": VID, "top": 2, "title": "配信", "channel": ""}], request_id="20261001-120000-abc123",
                                             flow="auto", deliver_dir=out)["runs"][0])
        self.assertEqual((run["state"], run["mode"]), ("done", "request_auto"), run)
        self.assertEqual(list(self.states(run)), ["analyze", "adopt", "export", "transcribe", "pack", "deliver"])
        self.assertEqual(self.states(run)["deliver"], "done")
        got = self.zips(out)
        self.assertEqual(sorted(got), ["20261001-120000-abc123__a2.zip", "20261001-120000-abc123__a3.zip"])
        self.assertIn("a2_pack/cut-plan.json", got["20261001-120000-abc123__a2.zip"])
        self.assertFalse([n for n in os.listdir(os.path.dirname(self.tools.clip_path("a2"))) if n.startswith(".deliver")], "書きかけの zip が残る")

    def test_file_auto_delivers_and_failure_note(self):
        """① 全自動(動画): 文字起こし → パック → zip。止まったら 出力\\ に理由の .txt"""
        media = os.path.join(self.tmp, "依頼.mp4")
        open(media, "wb").close()
        out = os.path.join(self.tmp, "Dropbox", "出力")
        run = self.wait(self.r.start_file(media, title="依頼", streamer="さくらみこ", request_id="rid1", flow="auto", deliver_dir=out))
        self.assertEqual((run["state"], run["mode"], list(self.states(run))), ("done", "file_auto", ["transcribe", "pack", "deliver"]), run)
        self.assertEqual(self.tools.c2r["body"]["output"].get("streamer"), "さくらみこ")   # 選んだ配信者の色でパック
        self.assertEqual(sorted(self.zips(out)), ["rid1__依頼.zip"])
        media2 = os.path.join(self.tmp, "b.mp4")
        open(media2, "wb").close()
        self.tools.fail_tx = True
        run = self.wait(self.r.start_file(media2, title="二本目", request_id="rid2", flow="auto", deliver_dir=out))
        self.assertEqual(run["state"], "error")
        with open(os.path.join(out, "rid2__二本目.失敗.txt"), encoding="utf-8-sig") as f:
            self.assertIn("モデルが読めません", f.read())

    def test_file_with_speakers_diarizes_new_doc(self):
        """話す人があれば、文字起こしのあとに話者分離(人数と名前を「編集」の /api/diarize へ)"""
        self.tools.h_transcribe_POST_api_diarize = lambda path, body: (self.tools.tx_jobs.setdefault("d1", {"id": "d1", "state": "done", "src": "", "body": body}) and (200, {"id": "d1"}))
        media = os.path.join(self.tmp, "コラボ.mp4")
        open(media, "wb").close()
        run = self.wait(self.r.start_file(media, speakers={"count": 2, "names": ["兎田ぺこら"]}))
        self.assertEqual((run["state"], list(self.states(run))), ("done", ["transcribe", "diarize"]), run)
        body = self.tools.tx_jobs["d1"]["body"]
        self.assertEqual((body["tid"], body["numSpeakers"], body["names"]), ("000000000001", 2, ["兎田ぺこら"]))

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
        run = self.wait(self.r.start_request([{"id": VID, "top": 3}], flow="manual")["runs"][0])
        self.assertEqual((run["state"], list(self.states(run))), ("done", ["analyze"]))
        self.assertFalse(any(c[2] == "/api/video/adopt-top" for c in self.tools.calls))


if __name__ == "__main__":
    unittest.main()
