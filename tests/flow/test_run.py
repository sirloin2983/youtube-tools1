# -*- coding: utf-8 -*-
"""pipeline/run.py(① の経路。RS1-7)のテスト。  py -3.12 -m unittest tests/flow/test_run.py -v
段の中身の細かい動きは tests/app/test_autorun.py(AutoRunner が Runner を継いだ形)で見る。ここは入口の関数・入力の形・hook の既定と、
層の決まり(home を知らずに読める)だけ。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしないが、ほかのテストとそろえる
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")   # tests -> pipeline -> src
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/(testkit)
import testkit  # noqa: E402
from flow import run as R  # noqa: E402
from flow import envelope as E, spec as SP, tools as T  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # 共有の部品 _runfields(Run の欄の形 → 封筒 + 束。RV A2)
import _runfields as RF  # noqa: E402


class FakeClient:
    """「編集」の文字起こしと cut2resolve の API の最小の真似(ジョブを入れる・ジョブの一覧・受け渡しの JSON・パック)。設定(/api/settings)は持たない = 段は読まない"""

    def __init__(self, docs=(), full=()):
        self.calls = []
        self.bodies = {}
        self.docs, self.full = list(docs), list(full)   # GET /api/transcripts の要約・GET /api/transcript の中身

    def call(self, tool, method, path, body=None):
        self.calls.append((tool, method, path))
        self.bodies[path.split("?")[0]] = body
        if path == "/api/transcribe":
            return 200, {"id": "j1"}
        if path == "/api/transcripts":
            return 200, {"items": list(self.docs)}
        if path.startswith("/api/transcript?"):
            d = next((x for x in self.full if path.endswith("=" + x["id"])), None)
            return (200, d) if d else (404, {})
        if path == "/api/jobs":
            return 200, {"jobs": [{"id": "j1", "state": "done", "tid": "t1"}]}
        if path.startswith("/api/edit?"):
            return 200, {"edit": None, "rev": 0}
        if path == "/api/export-file":
            return 200, {"path": "/x/t1.transcript.json"}
        if path == "/api/build":
            return 200, {"job": {"id": "c1", "state": "running"}}
        if path.startswith("/api/job?"):
            return 200, {"id": "c1", "state": "done", "result": {"outDir": "/x/clip_pack", "files": []}}
        return 404, {}

    def ok(self, tool, method, path, body=None):
        st, obj = self.call(tool, method, path, body)
        if st != 200:
            raise R.StepError("HTTP %d" % st)
        return obj


class TestFromInput(unittest.TestCase):
    def test_video(self):
        r = R.Run.from_input({"videoId": "abcdefghijk"})
        self.assertEqual((r.video_id, r.mode, r.top, r.doc_id, r.source_path, r.state), ("abcdefghijk", "full", 3, None, None, "queued"))
        self.assertEqual([s["key"] for s in r.steps], list(R.MODE_STEPS["full"]))
        r = R.Run.from_input({"videoId": "abcdefghijk", "top": 5}, "export")   # 書き出しから全部 = full + run.from export(解析・採用なし)
        self.assertEqual((r.mode, [s["key"] for s in r.steps], r.public()["modeLabel"]), ("full", ["export", "transcribe", "pack"], "書き出しから全部"))
        self.assertEqual(R.Run.from_input({"videoId": "abcdefghijk", "top": 5}, "export").top, 5)
        self.assertEqual(R.Run.from_input({"videoId": "abcdefghijk"}, "transcribe").mode, R.DOC_MODE)
        with self.assertRaises(ValueError):
            R.Run.from_input({"videoId": "abcdefghijk"}, "pack")
        with self.assertRaises(ValueError):
            R.Run.from_input({"videoId": "abcdefghijk", "top": 0})   # 本数は 1 以上(上限なし。10-20)
        self.assertEqual(R.Run.from_input({"videoId": "abcdefghijk", "top": 99}).top, 99)

    def test_doc_and_path(self):
        r = R.Run.from_input({"docId": "d1"})
        self.assertEqual((r.doc_id, r.mode, r.title, r.video_id), ("d1", R.DOC_MODE, "d1", None))
        r = R.Run.from_input({"path": "/x/clip.mp4", "title": "題"})
        self.assertEqual((r.source_path, r.mode, r.title), ("/x/clip.mp4", "file", "題"))
        self.assertEqual(R.Run.from_input({"path": "/x/clip.mp4"}).title, "clip.mp4")
        for bad in ({}, None, {"videoId": ""}, "abc"):
            with self.assertRaises(ValueError, msg=bad):
                R.Run.from_input(bad)

    def test_spec_saved_not_public(self):
        """束は待ちの記録に封筒と一緒に残る(RS7-1 S3。起動し直しで CLI の --spec が消えない)。public には出さない。
        戻すのは封筒 + 束だけ(RV A2。封筒の無い記録は戻さない)・合わない束は置かない(入口が組み直す)"""
        r = R.Run.from_input({"docId": "d1"}, spec={"pack": {"size": "1920x1080"}})
        self.assertEqual(r.spec["pack"]["size"], "1920x1080")
        self.assertNotIn("spec", r.public())
        d = json.loads(json.dumps(r.saved()))
        self.assertEqual(d["envelope"], json.loads(json.dumps(E.check(r.envelope()))))
        self.assertEqual((d["envelope"]["specVersion"], "legacy" in d["envelope"]), (2, False))
        back = R.Run.restore(d)
        self.assertEqual((back.id, back.doc_id, back.spec), (r.id, "d1", r.spec))
        old = {k: v for k, v in d.items() if k not in ("envelope", "spec")}   # RS7-1 より前の形(欄だけ)
        self.assertIsNone(R.Run.restore(old))
        bad = R.Run.restore(dict(d, spec={"pack": {"size": "1x1"}}))
        self.assertEqual((bad.spec, bad.mode, bad.doc_id), (None, R.DOC_MODE, "d1"))
        new_only = {k: d[k] for k in ("id", "envelope", "spec", "state", "steps", "created", "docs")}   # 欄の鍵の無い形
        back = R.Run.restore(new_only)
        self.assertEqual((back.id, back.mode, back.doc_id, back.spec, back.resumed), (r.id, R.DOC_MODE, "d1", r.spec, True))
        self.assertIsNone(R.Run.restore(dict(new_only, envelope=dict(d["envelope"], specVersion=99))))

    def test_deliver_tag_origin_saved_restored(self):
        r = RF.run_of("abcdefghijk", "t", "full", 3, deliver_dir="D:/out", deliver_tag="20261016-120000-abc123", deliver_origin="auto")
        d = json.loads(json.dumps(r.saved()))
        self.assertEqual((d["deliverTag"], d["deliverOrigin"]), ("20261016-120000-abc123", "auto"))
        back = R.Run.restore(d)
        self.assertEqual((back.deliver_tag, back.deliver_origin, back.deliver_dir), ("20261016-120000-abc123", "auto", "D:/out"))
        self.assertEqual([s["key"] for s in back.steps], [s["key"] for s in r.steps])
        self.assertEqual(r.envelope()["deliver"]["origin"], "auto")
        self.assertEqual(R.Run.from_envelope(E.check(r.envelope())).deliver_origin, "auto")
        self.assertIsNone(RF.run_of("abcdefghijk", "t", "full", 3, deliver_tag="").deliver_tag)

    def test_restore_old_record_without_deliver_fields(self):
        """D-SEND より前の待ちの記録(deliverTag・deliverOrigin が無い)も読める。届け先のある request_auto の段は今までどおり"""
        r = RF.run_of("abcdefghijk", "t", "request_auto", 3, request_id="20261001-000000-aaaaaa", deliver_dir="D:/out")
        d = r.saved()
        d.pop("deliverTag"), d.pop("deliverOrigin")
        d["envelope"]["deliver"].pop("origin")
        back = R.Run.restore(d)
        self.assertEqual((back.deliver_tag, back.deliver_origin, back.deliver_dir), (None, None, "D:/out"))
        self.assertEqual([s["key"] for s in back.steps], list(R.MODE_STEPS["request_auto"]) + ["deliver"])
        new_only = {k: d[k] for k in ("id", "envelope", "spec", "state", "steps", "created", "docs")}   # 封筒だけの形(origin の鍵が無い古い封筒)
        self.assertIsNone(R.Run.restore(new_only).deliver_origin)

    def test_restore_skips_removed_post_analyze(self):
        """「あとから解析」(mode post_analyze)は段の並びに無い。legacy つきの封筒の記録は落ちずに読み飛ばす"""
        d = R.Run.from_input({"videoId": "abcdefghijk"}).saved()
        self.assertIsNotNone(R.Run.restore(d))
        self.assertNotIn("post_analyze", R.MODE_STEPS)
        old = dict(d, envelope=dict({k: v for k, v in d["envelope"].items() if k != "specVersion"}, legacy={"mode": "full"}))
        self.assertIsNone(R.Run.restore(old), "版の無い(前の版の)封筒の記録は戻さない")


class TestRestoreGolden(unittest.TestCase):
    """待ちの記録(autorun-active.json の 1 件 = 欄 + 封筒 + 束)を固定の見本にして restore。
    段の並び・済んだ段・名前の頭・配信者・友人の区間の長さ・知らせ・途中の段が待ちに戻る。前に書いていた deliver.batch・note は読んで捨てる"""

    BASE = {"hints": {"ranges": [[10.0, 20.0], [30.0, 40.0]], "people": [{"name": "兎田ぺこら", "color": "#FF0000"}], "streamer": "兎田ぺこら"},
            "analyze": {"wAudio": 1.5, "wChat": 0.5, "wComments": 2.0, "length": 38, "preRatio": 0.61},
            "adopt": {"top": 2}, "transcribe": {"diarize": 2}, "pack": {"cut": "silence", "videoTracks": 3},
            "run": {"from": None, "upto": "pack", "onFail": "stop", "force": False, "repack": True, "requested": ["weights", "cut", "videoTracks"]}}

    def record(self, **kw):
        d = {"id": "0123456789", "videoId": "abcdefghijk", "title": "配信", "mode": "request_auto", "top": 2, "docId": None, "overwrite": True,
             "streamer": "兎田ぺこら", "streamerFrom": None, "marks": ["r1", "r2"], "fresh": {"title": "配信", "channel": "ch"}, "onFail": "stop",
             "sourcePath": None, "requestId": "20261016-120000-abcdef", "deliverDir": "D:/out", "speakers": {"count": 2, "names": ["兎田ぺこら"]},
             "videoTracks": 3, "ranges": [[10.0, 20.0], [30.0, 40.0]], "cut": "silence", "weights": {"wAudio": 1.5, "wChat": 0.5, "wComments": 2.0},
             "duration": 3600.0, "engine": None, "model": None, "friendLength": None, "deliverTag": None, "deliverOrigin": "request",
             "pool": None, "docs": ["t1"], "newDocs": ["t1"], "txBefore": {}, "packs": [], "keptPacks": [], "delivered": [], "packMarks": {}, "force": False,
             "normalize": False, "friendPlan": {"length": 38, "preRatio": 0.61, "file": "flow/lengthhint", "samples": 9, "videos": 3, "base": {"length": 45}},
             "notes": ["「行から」の設定の形が正しくないので、既定の広げ方で作りました"], "created": 1790000000.0, "state": "running", "message": "パック",
             "steps": [{"key": "adopt", "state": "done", "detail": "指定の区間 2 個", "startedAt": 1, "finishedAt": 2},
                       {"key": "export", "state": "done", "detail": "2 本を書き出しました"}, {"key": "transcribe", "state": "done", "detail": ""},
                       {"key": "diarize", "state": "warn", "detail": "一部"}, {"key": "pack", "state": "run", "detail": "1 / 2 本"},
                       {"key": "deliver", "state": "wait", "detail": ""}, {"key": "analyze_later", "state": "wait", "detail": ""}],
             "envelope": {"id": "0123456789", "kind": "url", "input": {"title": "配信", "videoId": "abcdefghijk", "duration": 3600.0,
                                                                     "fresh": {"title": "配信", "channel": "ch"}, "marks": ["r1", "r2"]},
                          "requestId": "20261016-120000-abcdef", "deliver": {"dir": "D:/out", "batch": 3, "pool": None, "origin": "request", "tag": None},
                          "note": "", "createdAt": 1790000000000, "specVersion": 2},   # batch・note = 古い封筒の鍵(読んで捨てる)
             "spec": SP.validate(SP.merge(self.BASE))}
        d.update(kw)
        return json.loads(json.dumps(d))

    def test_request_auto_mid_pack(self):
        back = R.Run.restore(self.record())
        self.assertEqual((back.id, back.mode, back.state, back.resumed), ("0123456789", "request_auto", "queued", True))
        self.assertEqual([(s["key"], s["state"]) for s in back.steps],
                         [("adopt", "done"), ("export", "done"), ("transcribe", "done"), ("diarize", "warn"), ("pack", "wait"), ("deliver", "wait"),
                          ("analyze_later", "wait")])
        self.assertEqual((back.steps[0]["startedAt"], back.steps[0]["finishedAt"]), (1, 2))
        self.assertEqual((back.streamer, back.on_fail, back.top, back.cut, back.video_tracks, back.overwrite, back.marks),
                         ("兎田ぺこら", "stop", 2, "silence", 3, True, ("r1", "r2")))
        self.assertEqual((back.weights, back.speakers["count"], back.ranges), ({"wAudio": 1.5, "wChat": 0.5, "wComments": 2.0}, 2, [(10.0, 20.0), (30.0, 40.0)]))
        self.assertEqual((back.friend_plan["length"], back.notes, back.docs, back.new_docs), (38, self.record()["notes"], ["t1"], ["t1"]))
        self.assertEqual(sorted(back.spec["run"]["requested"]), ["cut", "videoTracks", "weights"])
        self.assertEqual(back.public()["modeLabel"], R.REQUEST_MODES["request_auto"])
        again = json.loads(json.dumps(back.saved()))   # 書き直した記録に batch・note は無く、もう一度戻しても同じ
        self.assertEqual((again["envelope"]["specVersion"], "note" in again["envelope"], "batch" in again["envelope"]["deliver"],
                          again["spec"]["hints"]["streamer"]), (2, False, False, "兎田ぺこら"))
        back2 = R.Run.restore(again)
        self.assertEqual([(s["key"], s["state"]) for s in back2.steps], [(s["key"], s["state"]) for s in back.steps])
        self.assertEqual((back2.mode, back2.streamer, back2.on_fail, back2.deliver_tag), (back.mode, back.streamer, back.on_fail, None))

    def test_full_auto_send_and_file(self):
        """まとめて実行の自動で送る形(full・出どころ auto・名前の頭は封筒の deliver.tag)と動画ファイル(封筒の input.normalize・欄の docId)"""
        env = {"id": "abcdef0123", "kind": "url", "input": {"title": "配信", "videoId": "abcdefghijk", "duration": None, "fresh": None, "marks": None},
               "requestId": None, "deliver": {"dir": None, "pool": None, "origin": "auto", "tag": "20261016-120000-aaaaaa"}, "createdAt": 1790000000000,
               "specVersion": 2}
        d = self.record(id="abcdef0123", envelope=env, mode="full", deliverTag="20261016-120000-aaaaaa", deliverOrigin="auto", requestId=None,
                        steps=[{"key": "analyze", "state": "done", "detail": ""}, {"key": "deliver", "state": "wait", "detail": ""}],
                        spec=SP.validate(SP.merge({"run": {"onFail": "next"}, "hints": {"streamer": ""}})))
        back = R.Run.restore(d)
        self.assertEqual((back.mode, back.deliver_tag, back.deliver_origin, back.deliver_dir, back.streamer), ("full", "20261016-120000-aaaaaa", "auto", None, ""))
        self.assertEqual([s["key"] for s in back.steps], ["analyze", "adopt", "export", "transcribe", "pack", "deliver"])   # 届け先なしの auto = 送らなかった記録を残す段
        fenv = {"id": "fedcba9876", "kind": "file", "input": {"title": "依頼", "path": "C:/x/依頼.mp4", "normalize": True}, "requestId": "rid",
                "deliver": {"dir": "D:/out", "pool": None, "origin": None, "tag": None}, "createdAt": 1790000000000, "specVersion": 2}
        f = self.record(id="fedcba9876", envelope=fenv, mode="file_auto", docId="t9", sourcePath="C:/x/依頼.mp4",
                        steps=[{"key": "normalize", "state": "done", "detail": ""}, {"key": "transcribe", "state": "done", "detail": ""}],
                        spec=SP.validate(SP.merge(None)))
        back = R.Run.restore(f)
        self.assertEqual((back.mode, back.kind(), back.doc_id, back.normalize, back.source_path), ("file_auto", "file", "t9", True, "C:/x/依頼.mp4"))
        self.assertEqual([(s["key"], s["state"]) for s in back.steps], [("normalize", "done"), ("transcribe", "done"), ("pack", "wait"), ("deliver", "wait")])


class TestStepsOf(unittest.TestCase):
    """RV A2: 段の並び = 派生の mode(束の run.from・run.upto・封筒の kind・依頼の id)+ steps_of。8 つの形 × 届け先・出どころ・区間・話す人の総当たりで、
    決まり(MODE_STEPS + 足す決まり)と同じ"""

    @staticmethod
    def old_rule(mode, dir_, origin, ranges, top, diarize, normalize):
        keys = list(R.MODE_STEPS[mode])
        if "normalize" in keys and not normalize:
            keys.remove("normalize")
        if (dir_ or (origin == "auto" and mode == "full")) and "pack" in keys and mode != "doc":   # 届け先があるか、チェックを外したまとめて実行
            keys.append("deliver")
        if mode == "request_auto" and ranges and ranges >= (top or 0):
            keys.remove("analyze")
            keys.append("analyze_later")
        if diarize and "transcribe" in keys:
            keys.insert(keys.index("transcribe") + 1, "diarize")
        return keys

    def test_all_combinations(self):
        import itertools
        n = 0
        for mode, dir_, origin, nr, dz, norm in itertools.product(list(R.MODE_RUN), (None, "D:/out"), (None, "auto", "request"), (0, 1, 3),
                                                                  (None, 2), (False, True)):
            kind = R.MODE_RUN[mode][0]
            kw = {"deliver_dir": dir_, "deliver_origin": origin, "speakers": {"count": dz, "names": []} if dz else None}
            if kind == "url":
                kw["ranges"] = [(i * 10.0, i * 10.0 + 5) for i in range(nr)]
            if kind == "file":
                kw.update(source_path="C:/x/a.mp4", normalize=norm)
            if kind == "docs":
                kw["doc_id"] = "d1"
            if mode == "request_auto":   # adopted(書き出しから・パックまで)は依頼の id があるときだけ(無ければ full = 書き出しから全部)
                kw["request_id"] = "r1"
            run = RF.run_of("abcdefghijk" if kind == "url" else None, "t", mode, 2 if kind == "url" else None, **kw)
            want = self.old_rule(mode, dir_, origin, len(kw.get("ranges") or []), 2 if kind == "url" else None, dz, norm and kind == "file")
            self.assertEqual(run.mode, mode)
            self.assertEqual([s["key"] for s in run.steps], want, (mode, dir_, origin, nr, dz, norm))
            n += 1
        self.assertGreater(n, 350)   # 形 5 つ(full・request_auto・doc・file・file_auto)× 届け先・出どころ・区間・話す人・normalize

    def test_mode_of_matches_mode_run(self):
        """派生の mode と表 MODE_RUN(mode_of の逆)が合う(記録の mode・modeLabel・溜めの鍵・届けた記録の mode が変わらない)"""
        for mode, (kind, frm, upto) in R.MODE_RUN.items():
            b = SP.validate(SP.merge({"run": dict({"upto": upto}, **({"from": frm} if frm else {}))}))
            self.assertEqual(R.mode_of(kind, b, "r1" if mode.startswith("request") else None), mode)
        self.assertIsNone(R.mode_of("url", SP.validate(SP.merge({"run": {"from": "adopt"}}))))
        self.assertIsNone(R.mode_of("url", SP.validate(SP.merge({"run": {"upto": "transcribe"}})), "r1"), "② 軽く確認(配信の頭から文字起こしまで)は消した")
        self.assertIsNone(R.mode_of("docs", SP.validate(SP.merge({"run": {"upto": "transcribe"}}))))

    def test_stream_ended_at(self):
        """配信が終わった時刻(チャットの取り直しが読む): releaseTs + duration。ライブの終わった配信だけ・壊れた値は None"""
        good = {"releaseTs": 1000, "duration": 500}
        cases = [(st, dict(good, liveStatus=st), 1500.0) for st in ("was_live", "post_live")]
        cases += [(repr(a), a, None) for a in (
            None, "x", {}, {"liveStatus": "not_live", "releaseTs": 1000, "duration": 500},
            {"liveStatus": "is_live", "releaseTs": 1000, "duration": 500},
            {"liveStatus": "was_live", "duration": 500}, {"liveStatus": "was_live", "releaseTs": 1000},
            {"liveStatus": "was_live", "releaseTs": 0, "duration": 500}, {"liveStatus": "was_live", "releaseTs": 1000, "duration": 0},
            {"liveStatus": "was_live", "releaseTs": "1000", "duration": 500}, {"liveStatus": "was_live", "releaseTs": True, "duration": 500})]
        for name, a, want in cases:
            with self.subTest(name):
                self.assertEqual(R.stream_ended_at(a), want)
        self.assertEqual(R.stream_ended_at({"liveStatus": "was_live", "releaseTs": 1_790_000_000, "duration": 3600}), 1_790_003_600.0)


class TestRun(unittest.TestCase):
    def setUp(self):
        fd, self.media = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        self.addCleanup(os.remove, self.media)

    def test_file_transcribe(self):
        """動画ファイル → 文字起こし(素の Runner)。要求の設定は束から(RS6 b-0。GET /api/settings は読まない)"""
        c = FakeClient()
        r = R.run(c, {"path": self.media}, spec={"transcribe": {"model": "large-v3"}, "post": {"autoDict": False}},
                  hooks=R.Runner(c, poll=0, sleep=lambda s: None))
        self.assertEqual(r.spec, SP.validate(SP.merge({"transcribe": {"model": "large-v3"}, "post": {"autoDict": False}, "run": {"upto": "transcribe"}})))
        self.assertEqual((r.doc_id, r.docs, r.new_docs), ("t1", ["t1"], ["t1"]))
        self.assertEqual(r.step("transcribe")["state"], "done")
        self.assertEqual(r.message, "完了")
        self.assertIn(("transcribe", "POST", "/api/transcribe"), c.calls)
        self.assertNotIn("/api/settings", [x[2] for x in c.calls])
        self.assertEqual(c.bodies["/api/transcribe"], dict(SP.tx_opts(r.spec), sourcePath=self.media))
        self.assertNotIn("engine", c.bodies["/api/transcribe"])   # 機器から決まるエンジンと同じなら書かない

    def test_bad_spec_does_not_start(self):
        """形の違う束は段を始めない(ValueError。ツールは呼ばない)"""
        c = FakeClient()
        for bad in ({"x": 1}, {"pack": {"size": "1x1"}}, {"transcribe": {"engine": "nai"}}):
            with self.assertRaises(ValueError, msg=bad):
                R.run(c, {"path": self.media}, spec=bad)
        self.assertEqual(c.calls, [])

    def test_doc_pack_reads_spec(self):
        """文書 → パック: パックの作り方は束の pack 節(大きさ・1 段の文字数・音量・カットの方法と無音の値)。画面の値が無ければ fps は固定の 30"""
        media = self.media

        class Docs(R.Runner):
            def _docs(self):
                return [{"id": "d1", "title": "題", "count": 1, "sourcePath": media, "segments": [{"start": 0, "end": 1, "text": "あ"}]}]
        c = FakeClient()
        spec = {"pack": {"size": "1920x1080", "volume": 50, "cut": "silence", "cutSilence": {"noise": -40}, "wrapChars": {"horizontal": 12}}}
        r = R.run(c, R.Run.from_input({"docId": "d1"}), spec=spec, hooks=Docs(c, poll=0, sleep=lambda s: None))
        self.assertEqual(r.step("pack")["state"], "done", r.steps)
        body = c.bodies["/api/build"]
        self.assertEqual(body["spec"], {"video": media, "transcript": "/x/t1.transcript.json", "mode": "silence",
                                        "silence": {"noise": -40, "min": 0.6, "pad": 0.15}, "snapEdges": True})   # 両端を話の切れ目へ詰める(LD-2c。束の pack.snapEdges の既定)
        self.assertEqual(body["output"], {"textplus": True, "textplusWrap": 12, "textplusSize": "1920x1080", "textplusFps": "30",
                                          "speakerColors": True, "loudness": -14.0})   # 音量 % でなく -14 LUFS
        self.assertEqual(r.packs, [os.path.normpath("/x/clip_pack")])

    def test_doc_pack_sends_clip_range(self):
        """LD-2f: 余白つきの切り抜き(.clip.json の export.margin・actualStart)なら、パックへ動画の中のマークの区間 clipRange を送る"""
        media = self.media
        from ytt import schemas as S
        cp = S.clip_path_for(media)
        os.makedirs(os.path.dirname(cp), exist_ok=True)
        self.addCleanup(os.remove, cp)
        with open(cp, "w", encoding="utf-8") as f:
            json.dump(S.build_clip(media, 50.0, {"kind": "youtube", "videoId": "abcdefghijk"}, (110.0, 140.0), {"id": "m1"},
                                   {"mode": "precise", "actualStart": 100.0, "margin": {"before": 10.0, "after": 10.0}}, {"name": "t"}), f)

        class Docs(R.Runner):
            def _docs(self):
                return [{"id": "d1", "title": "題", "count": 1, "sourcePath": media, "segments": [{"start": 0, "end": 1, "text": "あ"}]}]
        c = FakeClient()
        r = R.run(c, R.Run.from_input({"docId": "d1"}), spec={"pack": {"cut": "silence"}}, hooks=Docs(c, poll=0, sleep=lambda s: None))
        self.assertEqual(r.step("pack")["state"], "done", r.steps)
        self.assertEqual(c.bodies["/api/build"]["spec"]["clipRange"], [10.0, 40.0])

    def test_doc_pack_sets_hint(self):
        """文書 → パックも届けた先(切り抜きの動画・スタジオのマーク)を pack_marks に残す(opt-manage 2a-1。無いと届けた印が案件に残らない)"""
        media = self.media
        clip = {"source": {"kind": "live", "live": {"studio": {"video": "rec1", "mark": "s1"}}}}

        class Docs(R.Runner):
            def _docs(self):
                return [{"id": "d1", "title": "題", "count": 1, "sourcePath": media, "clip": clip,
                         "segments": [{"start": 0, "end": 1, "text": "あ"}]}]
        c = FakeClient()
        r = R.run(c, R.Run.from_input({"docId": "d1"}), hooks=Docs(c, poll=0, sleep=lambda s: None))
        self.assertEqual(r.step("pack")["state"], "done", r.steps)
        self.assertEqual(r.pack_marks, {os.path.normpath("/x/clip_pack"): {"path": media, "markId": "s1"}})
        self.assertIsNone(r.pack_hint)

    def test_pack_source_for_friend_verdict(self):
        """パックの元(10-27): 元の配信・区間(.clip.json が無ければマーク)・候補の印(解析の要約の並びとマークの自動の区間を突き合わせる)・版と設定"""
        from ytt import version as V
        h = R.Runner(FakeClient(), poll=0, sleep=lambda s: None)
        run = R.Run.from_input({"videoId": "abcdefghijk"})
        h._video = lambda run: {"marks": [{"id": "m1", "start": 100.0, "end": 145.0, "auto0": [100.0, 145.0]}],
                                "analysis": {"cands": [{"start": 5, "end": 50, "score": 3.0}, {"start": 100.0, "end": 145.0, "score": 2.5, "origin": "heatmap"}],
                                             "spec": {"count": 8, "wAudio": 1.0, "sensitivity": "normal", "noCache": False}}}
        self.assertEqual(h._pack_source(run, {"markId": "m1"}),
                         {"videoId": "abcdefghijk", "range": [100.0, 145.0], "cand": {"rank": 2, "score": 2.5, "origin": "heatmap"},
                          "tool": {"version": V.VERSION, "settings": {"count": 8, "wAudio": 1.0, "sensitivity": "normal"}}})
        h._video = lambda run: (_ for _ in ()).throw(R.StepError("落ちた"))
        self.assertEqual(h._pack_source(run, {"markId": "m1"}), {})   # 引けなくてもパックは作る

    def test_doc_pack_hint_shapes(self):
        """届けた先の形: ライブでない文書・壊れた clip でも path は残し、markId は ""(友人の動画の依頼はスタジオのマークが無い)"""
        self.assertEqual(R.doc_pack_hint({"sourcePath": "/x/a.mp4"}), {"path": "/x/a.mp4", "markId": ""})
        self.assertEqual(R.doc_pack_hint({"sourcePath": "/x/a.mp4", "clip": {"source": "x"}}), {"path": "/x/a.mp4", "markId": ""})
        self.assertEqual(R.doc_pack_hint({"clip": {"source": {"live": {"studio": {"mark": 3}}}}}), {"path": "", "markId": ""})

    def test_missing_file_default_runner(self):
        """hooks なし = 素の Runner。動画が無ければ StepError(ツールは呼ばない)"""
        c = FakeClient()
        with self.assertRaises(R.StepError):
            R.run(c, {"path": self.media + ".nai.mp4"})
        self.assertEqual(c.calls, [])

    def test_doc_nothing_to_do(self):
        """文書 → 文字起こし → パック: 文字起こし済み・パック済みなら両方飛ばして「やることがありませんでした」(hook で文書の一覧だけ渡す)"""
        media = self.media

        class Docs(R.Runner):
            def _docs(self):
                return [{"id": "d1", "title": "題", "count": 3, "sourcePath": media}]
        c = FakeClient()
        rn = Docs(c, poll=0, sleep=lambda s: None, find_pack=lambda p: {"dir": "/packs/x"})
        r = R.run(c, R.Run.from_input({"docId": "d1"}), hooks=rn)
        self.assertEqual([s["state"] for s in r.steps], ["skip", "skip"])
        self.assertTrue(r.nothing)
        self.assertTrue(r.message.startswith(R.NOTHING_MESSAGE))
        self.assertEqual(r.title, "題")


class AdoptTools(T.HttpTools):
    """採用の段だけを見る道具(スタジオの採用の答えを決めて返す。本文を覚える)"""

    def __init__(self, res):
        super().__init__(None)
        self.res, self.bodies = res, []

    def request_marks(self, body):
        self.bodies.append(body)
        return self.res


class TestAdopt(unittest.TestCase):
    """採用の段(F-5。RS6 b-A): 規則はスタジオの 1 つ(request_marks の先)。段は数と余白を束 + Run の欄から渡し、答えを進み具合の文と run.marks にする"""

    def adopt(self, res, mode="full", top=3, ranges=None, spec=None, fresh=None):
        run = RF.run_of("abcdefghijk", "配信", mode, top, ranges=ranges, fresh=fresh)
        RF.respec(run, spec)
        tools = AdoptTools(res)
        rn = R.Runner(None, tools=tools)
        st = run.step("adopt")
        st["state"] = "run"
        out = rn._step_adopt(run, st, {"duration": 1000})
        return out, st, run, tools.bodies[0]

    def test_human_adoption_counts_and_rest_is_filled(self):
        """人が 1 本採用した配信の再実行: 上限までの残り 2 本を自動で足す"""
        out, st, run, body = self.adopt({"rangeIds": [], "humanIds": ["h1"], "autoIds": ["a2", "a3"], "added": ["a2", "a3"]})
        self.assertEqual((out, st["state"], body), (None, "run", {"id": "abcdefghijk", "ranges": [], "top": 3}))
        self.assertEqual(st["detail"], "人が採用した 1 本・自動で 2 本を足しました(点数の高い順)")
        self.assertIsNone(run.marks)   # 配信の全部(区間の依頼でなければ扱う範囲は変えない)

    def test_nothing_new_is_skip(self):
        out, st, _run, _body = self.adopt({"rangeIds": [], "humanIds": ["h1", "h2", "h3"], "autoIds": [], "added": []})
        self.assertEqual((out, st["state"]), (None, "skip"))
        self.assertIn("人が採用した 3 本", st["detail"])
        self.assertIn("新しく採用したものはありません", st["detail"])

    def test_no_candidates_stops(self):
        out, st, run, _body = self.adopt({"rangeIds": [], "humanIds": [], "autoIds": [], "added": []})
        self.assertEqual((out, st["state"], run.message), ("stop", "skip", "採用できる候補がありませんでした"))

    def test_request_ranges_use_bundle_pad_and_set_marks(self):
        """友人の依頼(URL): 区間に束の adopt.pad の余白・扱うマークは区間 ∪ 人の採用 ∪ 自動・足りなければ知らせる"""
        res = {"rangeIds": ["r1"], "humanIds": ["h1"], "autoIds": ["a1"], "added": ["r1", "a1"]}
        out, st, run, body = self.adopt(res, mode="request_auto", top=4, ranges=[(100.0, 120.0)], spec={"adopt": {"pad": 5.0}},
                                        fresh={"title": "題", "channel": "ch"})
        self.assertEqual(body, {"id": "abcdefghijk", "ranges": [[95.0, 125.0]], "top": 4, "title": "題", "channel": "ch"})
        self.assertEqual((out, st["state"], run.marks), (None, "run", ("r1", "h1", "a1")))
        self.assertEqual(st["detail"], "指定の区間 1 個(前後に 5 秒の余白)・人が採用した 1 本・自動で 1 本を足しました(点数の高い順)。候補が足りず 1 本は選べませんでした")

    def test_top_from_bundle_when_run_has_none(self):
        _out, _st, _run, body = self.adopt({"autoIds": ["a1"], "added": ["a1"]}, top=None, spec={"adopt": {"top": 5}})
        self.assertEqual(body["top"], 5)


class TestKeys(unittest.TestCase):
    """鍵を読む段(RS6 b-K2): 文字起こし = 同じ・鍵なしは飛ばす / 違えば飛ばして印 / force で作り直す。パック = 違えば作り直す / 同じは飛ばす / 鍵なしは触らない"""

    def setUp(self):
        fd, self.media = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        self.addCleanup(os.remove, self.media)
        self.video = {"marks": [{"id": "m1", "status": "exported", "path": self.media}]}
        self.doc = {"id": "abcdef012345", "title": "題", "sourcePath": self.media, "count": 2, "updatedAt": 1,
                    "segments": [{"start": 0, "end": 1, "text": "あ"}]}

    def runner(self, c, tx_state="same", pack_state="none", have_pack=False):
        doc = self.doc
        c.full = c.full or [doc]   # 鍵の比べは字幕を書かずに中身を読む(GET /api/transcript。指摘 2)

        class Rn(R.Runner):
            def _docs(self):
                return [doc]

            def _pick_doc(self, docs, video_id, mark_id, path):
                return doc
        rn = Rn(c, poll=0, sleep=lambda s: None, find_pack=lambda p: {"dir": "/p"} if have_pack else None)
        patches = [mock.patch.object(R._keys, "transcribe_state", return_value=tx_state),
                   mock.patch.object(R._keys, "pack_state", side_effect=lambda media, make: (pack_state, make() if pack_state != "none" else None))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return rn

    def step(self, rn, key, force=False, spec=None):
        run = RF.run_of("abcdefghijk", "配信", "export", 3, force=force)
        RF.respec(run, spec)
        st = run.step(key)
        st["state"] = "run"
        getattr(rn, "_step_" + key)(run, st, self.video)
        return st, run

    def test_pack_without_text_rows_makes_whole_clip(self):
        """文字のある行が無い文書(声の無い切り抜き)も、字幕なしで区間の全体をパックにする(行が無いからと 1 本落とさない。配る前の検査の 5 本中 4 本)"""
        c = FakeClient(full=[self.doc])
        rn = R.Runner(c, poll=0, sleep=lambda s: None)
        run = RF.run_of("abcdefghijk", "配信", "export", 3)
        doc = dict(self.doc, segments=[])
        with mock.patch.object(R, "_clip_span", lambda media: (10.0, 20.0)):
            body, keeps, _rev = rn._pack_body(run, doc, self.media, rn._pack_settings(run))
        self.assertEqual((body["spec"], body["output"]["textplus"], keeps), ({"video": self.media, "keeps": [[10.0, 20.0]]}, True, None))   # Text+ の字幕なし(10-23)
        self.assertNotIn(("transcribe", "POST", "/api/export-file"), c.calls)   # 字幕の受け渡しを頼まない

    def test_pack_state_writes_nothing_and_matches_written_key(self):
        """指摘 2: 鍵の比べ(見積もりも同じ関数)は字幕の受け渡しの JSON を書かない。書かずに作った材料の鍵は、書いたファイルから作った鍵と同じ"""
        c = FakeClient(full=[self.doc])
        rn = R.Runner(c, poll=0, sleep=lambda s: None)
        run = RF.run_of("abcdefghijk", "配信", "export", 3)
        opts = rn._pack_settings(run)
        body, _keeps, _rev = rn._pack_body(run, self.doc, self.media, opts, dry=True)
        self.assertNotIn(("transcribe", "POST", "/api/export-file"), c.calls)
        tr = os.path.join(tempfile.mkdtemp(), "t.transcript.json")
        self.addCleanup(shutil.rmtree, os.path.dirname(tr), True)
        with open(tr, "w", encoding="utf-8") as f:   # 書いたファイル(作った日時と道具は版に入らない)
            json.dump(dict(body["contents"]["transcript"], createdAt="2026-10-15T00:00:00Z"), f, ensure_ascii=False, indent=1)
        pack = R._keys.pack_dir(self.media)
        os.makedirs(pack)
        self.addCleanup(shutil.rmtree, pack, True)
        self.assertTrue(R._keys.write_pack(pack, dict(body["spec"], transcript=tr), body["output"]))
        from flow import packrec
        recs = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, recs, True)
        v = os.path.join(pack, "a.mp4")
        with open(v, "wb") as f:
            f.write(b"x")
        with mock.patch.object(packrec, "packs_dir", lambda env=None, c2r_dir=None: recs):   # 作り終えたパック(記録と中身)= 鍵が同じなら same(部品 F3)
            packrec.write_record({"out_dir": pack, "files": [("video", v)]}, self.media, False)
            state, built = rn._pack_state(run, self.doc, self.media, opts)
        self.assertEqual(state, "same")
        self.assertIn("contents", built[0])
        self.assertNotIn(("transcribe", "POST", "/api/export-file"), c.calls)

    def test_skipped_by_key_still_lists_existing_outputs(self):
        """鍵で飛ばした段でも、前のパックと文書を結果(public・結果の束)の packs・docs に載せる。作った物(run.packs)には混ぜない"""
        pack = os.path.normpath(R._keys.pack_dir(self.media))
        os.makedirs(pack)
        self.addCleanup(os.rmdir, pack)
        for pack_state, have in (("same", False), ("none", True)):
            st, run = self.step(self.runner(FakeClient(), pack_state=pack_state, have_pack=have), "pack")
            self.assertEqual(st["state"], "skip")
            self.assertEqual(run.packs, [])
            self.assertEqual(run.kept_packs, [pack])
            self.assertEqual(run.public()["packs"], [pack])
            self.assertEqual(run.docs, [self.doc["id"]])
            self.assertEqual(R._placement.result(run)["packs"], [pack])
            self.assertEqual(R.Run.restore(run.saved()).public()["packs"], [pack])
        st, run = self.step(self.runner(FakeClient(), tx_state="same"), "transcribe")   # 文字起こしを飛ばしたときも文書を載せる
        self.assertEqual((st["state"], run.docs), ("skip", [self.doc["id"]]))
        self.assertEqual(run.new_docs, [])

    def test_force_saved_and_restored(self):
        run = R.Run.from_input({"videoId": "abcdefghijk", "force": True})
        self.assertTrue(run.force)
        self.assertTrue(run.public()["force"])
        self.assertTrue(R.Run.restore(run.saved()).force)
        self.assertFalse(R.Run.from_input({"path": "/x.mp4"}).force)


class TestDefaultDocs(unittest.TestCase):
    """素の Runner の文書の一覧(RS6 b-K2): GET /api/transcripts の要約から名前で絞り、GET /api/transcript で動画のパスを確かめる"""

    def test_pick_doc_by_path(self):
        media = os.path.abspath("/x/clip.mp4")
        full = {"id": "abcdef012345", "title": "題", "sourcePath": media, "updatedAt": 2, "segments": [{"start": 0, "end": 1, "text": "あ"}]}
        other = dict(full, id="abcdef000000", sourcePath=os.path.abspath("/y/clip.mp4"), updatedAt=3)
        items = [{"id": d["id"], "title": "題", "sourceName": "clip.mp4", "updatedAt": d["updatedAt"], "segments": 1} for d in (full, other)]
        c = FakeClient(items, [full, other])
        rn = R.Runner(c)
        docs = rn._docs()
        self.assertNotIn("sourcePath", docs[0])
        got = rn._pick_doc(docs, None, None, media)
        self.assertEqual((got["id"], got["count"], got["sourcePath"]), ("abcdef012345", 1, media))   # 新しい方(別の場所)ではなくパスが同じ物
        self.assertIsNone(rn._pick_doc(docs, None, None, os.path.abspath("/z/nai.mp4")))


class RecTools(T.HttpTools):
    """段の要求の本文を覚える道具(採用・解析・話者分離。ほかは FakeClient の HttpTools)"""

    def __init__(self, client):
        super().__init__(client)
        self.adopt, self.analyze, self.diarize = [], [], []

    def request_marks(self, body):
        self.adopt.append(body)
        return {"rangeIds": [], "humanIds": [], "autoIds": ["a1"], "added": ["a1"]}

    def analyze_add(self, item, settings):
        self.analyze.append((item, settings))
        return {"added": [{"qid": "q1"}]}

    def analyze_items(self):
        return [{"qid": "q1", "status": "done", "marks": 1}]

    def diarize_start(self, body):
        self.diarize.append(body)
        return 500, {"message": "覚えるだけ"}


VID = "abcdefghijk"
SCREEN = {"pack": {"cut": "rows", "videoTracks": 1}, "analyze": {"wAudio": 1.2}, "adopt": {"top": 6}, "transcribe": {"model": "small"}}


class TestFieldsToBundle(unittest.TestCase):
    """RS7-1 S3: Run の中身の欄は束へ写る(段は束を読む)。欄で作った Run と、その封筒 + 束で作った Run(from_envelope)の
    段の要求の本文が同じ(golden)。本文は今までの欄から作った本文と同じ(下の期待値 = 今の決まり)"""

    def setUp(self):
        fd, self.media = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        self.addCleanup(os.remove, self.media)

    def cases(self):
        m = self.media
        return {
            "request": dict(video_id=VID, title="配信", mode="request_auto", top=4, ranges=[(100.0, 120.0)],
                            weights={"wAudio": 1.5, "wChat": 0.5, "wComments": 2.0}, fresh={"title": "題", "channel": "ch"}, duration=1000.0,
                            request_id="r1", deliver_dir="/out", streamer="ぺこら", cut="silence", video_tracks=1,
                            speakers={"count": 2, "names": ["A"], "styles": {"A": {"color": "#112233"}}}),
            "live_file": dict(video_id=None, title="ライブ", mode="file_auto", top=None, source_path=m, engine="whisper.cpp", model="large-v3",
                              cut="none", pool={"key": "k1", "rid": "x"}),
            "engine_same": dict(video_id=None, title="動画", mode="file", top=None, source_path=m, engine="whisper.cpp", model="large-v3"),
            "doc_overwrite": dict(video_id=None, title="文書", mode=R.DOC_MODE, top=None, doc_id="d1", overwrite=True),
            "adopted_force": dict(video_id=VID, title="配信", mode="export", top=5, force=True, marks=("m1",)),
        }

    @staticmethod
    def make(kw, base=None):
        kw = dict(kw)
        return RF.run_of(kw.pop("video_id"), kw.pop("title"), kw.pop("mode"), kw.pop("top"), base=base, **kw)

    def bodies(self, run):
        """段の要求の本文(採用・解析・パック・文字起こし・話者分離)"""
        c = FakeClient()
        tools = RecTools(c)
        rn = R.Runner(c, poll=0, sleep=lambda s: None, tools=tools)
        out = {"force": rn._force(run), "repack": rn._repack(run), "styles": rn._speaker_styles(run)}
        if run.video_id:
            st = {"state": "run", "detail": ""}
            rn._step_adopt(run, st, {"duration": 1000})
            rn._analyze_item(run, st, {"kind": "youtube", "videoId": VID}, VID)
            out.update(adopt=tools.adopt, analyze=tools.analyze, weightsDiffer=rn._weights_differ(run, {"analysis": {"spec": {}}}))
        doc = {"id": "t1", "title": "題", "count": 1, "sourcePath": self.media, "segments": [{"start": 0, "end": 1, "text": "あ"}]}
        out["pack"] = rn._pack_body(run, doc, self.media, rn._pack_settings(run))[0]
        if run.source_path:
            st = {"state": "run", "detail": ""}
            rn._file_transcribe(run, st)
            out["tx"] = c.bodies["/api/transcribe"]
        if any(s["key"] == "diarize" for s in run.steps):
            run.new_docs = ["t1"]
            rn._step_diarize(run, {"state": "run", "detail": ""})
        out["diarize"] = tools.diarize
        return out

    def test_golden(self):
        base = SP.validate(SP.merge(SCREEN))
        got = {}
        for name, kw in self.cases().items():
            r1 = self.make(kw, base)   # 画面の束を土台に欄の差分(flow/order.py)
            env, spec = json.loads(json.dumps(r1.envelope())), json.loads(json.dumps(r1.spec))
            r2 = R.Run.from_envelope(env, spec)
            self.assertEqual(r2.spec, r1.spec, name)
            self.assertEqual([s["key"] for s in r2.steps], [s["key"] for s in r1.steps], name)
            for f in ("id", "mode", "top", "ranges", "weights", "cut", "video_tracks", "speakers", "engine", "model", "overwrite", "force", "streamer",
                      "request_id", "deliver_dir", "pool", "fresh", "duration", "marks", "source_path", "doc_id", "title", "on_fail"):
                self.assertEqual(getattr(r2, f), getattr(r1, f), "%s.%s" % (name, f))
            b1, b2 = self.bodies(r1), self.bodies(r2)
            self.assertEqual(b2, b1, name)
            got[name] = b1
        rq = got["request"]   # 今の決まり: 欄が画面の束より勝つ
        self.assertEqual(rq["adopt"], [{"id": VID, "ranges": [[98.0, 122.0]], "top": 4, "title": "題", "channel": "ch"}])
        self.assertEqual({k: rq["analyze"][0][1][k] for k in SP.WEIGHT_KEYS}, {"wAudio": 1.5, "wChat": 0.5, "wComments": 2.0})
        self.assertTrue(rq["weightsDiffer"])
        self.assertEqual((rq["pack"]["spec"]["mode"], rq["pack"]["output"]["videoTracks"]), ("silence", 1))   # 1 でも書く
        self.assertEqual(rq["pack"]["output"]["speakerStyles"], {"A": {"color": "#112233"}})
        self.assertEqual(rq["diarize"], [{"numSpeakers": 2, "names": ["A"], "recognize": True, "keepRowVoice": True, "tid": "t1"}])
        self.assertEqual((rq["force"], rq["repack"]), (False, False))
        lv = got["live_file"]
        self.assertEqual((lv["tx"]["engine"], lv["tx"]["model"]), ("whisper.cpp", "large-v3"))
        self.assertEqual(lv["pack"]["spec"]["mode"], "list")   # 選んだカット none(画面の rows より強い)
        self.assertNotIn("videoTracks", lv["pack"]["output"])
        self.assertEqual(lv["diarize"], [])   # 話す人の指定が無い = 段が無い
        self.assertEqual(got["engine_same"]["tx"]["engine"], "whisper.cpp")   # 機器から決まるエンジンと同じでも書く
        self.assertEqual((got["doc_overwrite"]["force"], got["doc_overwrite"]["repack"]), (False, True))   # overwrite はパックだけ作り直す
        ad = got["adopted_force"]
        self.assertEqual((ad["force"], ad["repack"], ad["adopt"][0]["top"], ad["weightsDiffer"]), (True, True, 5, False))
        self.assertEqual(ad["pack"]["spec"]["preset"], "transcript-rows")   # カットの指定なし = 画面の rows

    def test_from_envelope_defaults_and_refusals(self):
        r = R.Run.from_envelope({"id": "0123456789", "kind": "url", "input": {"url": "https://www.youtube.com/watch?v=abcdefghijk"}},
                                {"adopt": {"top": 2}, "hints": {"ranges": [[10, 20]]}})
        self.assertEqual((r.id, r.video_id, r.mode, r.top, r.ranges, r.title), ("0123456789", VID, "full", 2, [(10, 20)], VID))
        r = R.Run.from_envelope({"id": "x-1", "kind": "file", "input": {"path": self.media}})
        self.assertEqual((r.mode, r.source_path, len(r.id)), ("file_auto", self.media, 10))   # 10 桁の 16 進でない id は実行の id にしない
        with self.assertRaises(ValueError):   # 封筒の検査の断りは test_envelope.py
            R.Run.from_envelope({"id": "a", "kind": "live", "input": {"videoId": VID}})

    def test_file_from_pack(self):
        """束の run.from = pack(CLI の --from pack を入口に頼んだ形。RS7-1 S4): 文字起こし済みの文書でパックだけ(force でも文字起こしは作り直さない)。
        文書が無ければ止める"""
        doc = {"id": "t9", "title": "題", "count": 1, "sourcePath": self.media, "segments": [{"start": 0, "end": 1, "text": "あ"}]}

        class Docs(R.Runner):
            def _docs(self):
                return list(self.have)
        c = FakeClient()
        rn = Docs(c, poll=0, sleep=lambda s: None)
        rn.have = [doc]
        env = {"id": "0123456789", "kind": "file", "input": {"path": self.media}}
        r = R.Run.from_envelope(env, {"run": {"from": "pack", "force": True}})
        st = {"state": "run", "detail": ""}
        rn._file_transcribe(r, st)
        self.assertEqual((st["state"], r.doc_id, "/api/transcribe" in c.bodies), ("skip", "t9", False))
        rn.have = []
        with self.assertRaisesRegex(R.StepError, "文字起こしの文書がありません"):
            rn._file_transcribe(R.Run.from_envelope(env, {"run": {"from": "pack"}}), {"state": "run", "detail": ""})
        r = R.Run.from_envelope(env, {"run": {"force": True}})   # from が無ければ force で作り直す
        rn.have = [doc]
        rn._file_transcribe(r, {"state": "run", "detail": ""})
        self.assertIn("/api/transcribe", c.bodies)

    def test_resume_after_child_saved_doc_keeps_diarize_target(self):
        """F2: 子が文書を保存した直後・親が結果を見る前に終了しても、再開でその文書を「この実行が作った文書」(new_docs)にする。
        前からある文書は new_docs に入れない(人の話者の直しを守る)。終了の前に頼んだ記録は待ちの記録(saved)に入っている"""
        class Gone(Exception):
            pass
        made = {"id": "t5", "title": "題", "count": 3, "sourcePath": self.media, "segments": [{"start": 0, "end": 1, "text": "あ"}]}
        saved = []

        class Docs(R.Runner):
            def _docs(self):
                return list(self.have)

            def _checkpoint(self, run):
                saved.append(run.saved())

        class Dies(FakeClient):
            def call(self, tool, method, path, body=None):
                if path == "/api/jobs":   # 子は文書を保存した(have に入れる)が、親は結果を見る前に終了
                    rn.have = [made]
                    raise Gone()
                return super().call(tool, method, path, body)
        env = {"id": "0123456789", "kind": "file", "input": {"path": self.media}}
        rn = Docs(Dies(), poll=0, sleep=lambda s: None)
        rn.have = []
        with self.assertRaises(Gone):
            rn._file_transcribe(R.Run.from_envelope(env), {"state": "run", "detail": ""})
        r = R.Run.restore(saved[-1])
        c = FakeClient()
        rn2 = Docs(c, poll=0, sleep=lambda s: None)
        rn2.have = [made]
        st = {"state": "run", "detail": ""}
        rn2._file_transcribe(r, st)
        self.assertEqual((st["state"], r.new_docs, r.doc_id, "/api/transcribe" in c.bodies), ("skip", ["t5"], "t5", False))
        # 頼んでいない実行(前からある文書)は new_docs に入れない
        r = R.Run.from_envelope(env)
        rn2._file_transcribe(r, {"state": "run", "detail": ""})
        self.assertEqual(r.new_docs, [])

    def test_run_keeps_spec_of_envelope_run(self):
        """封筒 + 束で作った Run は、run(spec=None) でもその束のまま(既定に戻さない)"""
        c = FakeClient()
        r = R.Run.from_envelope({"id": "a", "kind": "file", "input": {"path": self.media}},
                                {"transcribe": {"model": "large-v3"}, "run": {"upto": "transcribe"}})
        R.run(c, r, hooks=R.Runner(c, poll=0, sleep=lambda s: None))
        self.assertEqual(c.bodies["/api/transcribe"]["model"], "large-v3")


class TestStepsAndPublic(unittest.TestCase):
    """段の時刻(steps[].startedAt/finishedAt)・public の packs・newDocs・文書単位でも docs(RS7-1 S3)"""

    def test_times_public_saved_restored(self):
        fd, media = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        self.addCleanup(os.remove, media)

        class Docs(R.Runner):
            def _docs(self):
                return [{"id": "d1", "title": "題", "count": 0, "sourcePath": media, "segments": []}]
        c = FakeClient()
        t = iter(range(1000, 100000, 500))
        r = R.run(c, R.Run.from_input({"docId": "d1"}), hooks=Docs(c, poll=0, sleep=lambda s: None, clock=lambda: next(t)))
        tx = r.step("transcribe")
        self.assertEqual(tx["state"], "done")
        self.assertTrue(isinstance(tx["startedAt"], int) and tx["finishedAt"] > tx["startedAt"], tx)
        pub = r.public()
        self.assertEqual((pub["docs"], pub["newDocs"]), (["d1"], ["d1"]))   # 文書単位の実行も文書を出す
        self.assertIn("packs", pub)
        self.assertEqual(pub["steps"][0]["startedAt"], tx["startedAt"])
        self.assertEqual(R._placement.result(r)["steps"][0]["finishedAt"], tx["finishedAt"])
        saved = json.loads(json.dumps(r.saved()))
        back = R.Run.restore(saved)
        self.assertEqual(back.step("transcribe")["startedAt"], tx["startedAt"])

    def test_accept_decisions_saved_and_used(self):
        """RS7-1 S4: 受付で決めた友人の区間の長さ(friend_plan。束の analyze に入れてある)と知らせ(notes)は待ちの記録に残り、
        解析の段は使った印 friend_length と文を出す・パックの段は知らせを文に出し、結果の束にも入る"""
        plan = {"length": 38, "preRatio": 0.61, "file": "x.json", "samples": 20, "videos": 5, "base": {"length": 45, "preRatio": 0.65}}
        r = RF.run_of(VID, "配信", "request_auto", 3, ranges=[(10.0, 20.0)])
        r.friend_plan, r.notes = plan, ["知らせ"]
        RF.respec(r, {"analyze": {"length": 38, "preRatio": 0.61}})
        back = R.Run.restore(json.loads(json.dumps(r.saved())))
        self.assertEqual((back.friend_plan, back.notes), (plan, ["知らせ"]))
        c = FakeClient()
        tools = RecTools(c)
        rn = R.Runner(c, poll=0, sleep=lambda s: None, tools=tools)
        st = {"state": "run", "detail": ""}
        rn._analyze_item(back, st, {"kind": "youtube", "videoId": VID}, VID)
        self.assertEqual((tools.analyze[0][1]["length"], tools.analyze[0][1]["preRatio"]), (38, 0.61))
        self.assertEqual(back.friend_length, {k: v for k, v in plan.items() if k != "base"})
        self.assertIn("長さ 38 秒・山の前 0.61(友人の区間の実績から)", st["detail"])
        self.assertEqual(rn._pack_settings(back)[3], ["知らせ"])
        self.assertEqual(R._placement.result(back)["notes"], ["知らせ"])


class VerdictTest(unittest.TestCase):
    """段の「飛ばすか」の判定(実行と見積もりが同じ関数を呼ぶ。RS8 OPT2)"""

    def test_analyze(self):
        self.assertEqual([R.analyze_verdict(a, w) for a, w in ((False, False), (True, False), (True, True), (False, True))], ["make", "skip", "make", "make"])

    def test_adopted_ids(self):
        self.assertEqual(R.adopted_ids([{"id": "a", "status": "adopted"}, {"id": "b", "status": "exported"}, {"id": "c"}]), ["a"])

    def test_transcribe(self):
        self.assertEqual([R.tx_verdict(h, f) for h, f in ((False, False), (False, True), (True, False), (True, True))], ["make", "make", "skip", "redo"])

    def test_pack(self):
        self.assertEqual(R.pack_verdict(True, "same", True), "remake")        # force は鍵も既存も見ない
        self.assertEqual(R.pack_verdict(False, "differ", True), "remake")     # 鍵が違えば作り直す
        self.assertEqual(R.pack_verdict(False, "same", False), "skip")        # 鍵が同じなら(パックが見つからなくても)飛ばす
        self.assertEqual(R.pack_verdict(False, "none", False), "make")        # 鍵なしでパックが無い
        self.assertEqual(R.pack_verdict(False, "none", True), "skip")         # 鍵なしで既にある


class TestPollStartFailure(unittest.TestCase):
    def test_submit_failure_cancels_submitted_jobs(self):
        """投入(start)の途中で失敗(StepError など中止以外)したら、投入済みの仕事を取り消してから上げる。取り消しの失敗で元の理由を隠さない"""
        rn = R.Runner(None, poll=0, sleep=lambda s: None, tools=object())
        run = RF.run_of(VID, "配信", "full", 1)
        jobs, cancelled = [], []

        def start():
            jobs.append("j1")
            raise R.StepError("2 本目を入れられませんでした")

        def cancel():
            cancelled.extend(jobs)
            raise RuntimeError("取り消しも失敗")
        with self.assertRaisesRegex(R.StepError, "2 本目"):
            rn._poll(run, ("transcribe", jobs), lambda: None, cancel, start=start)
        self.assertEqual((cancelled, run.owned), (["j1"], None))


NOW = 1792330000.0   # 配信が終わって約 1.5 時間後


def analysis_of(chat=True, fill=0, cands=1, at=NOW - 60, ended=NOW - 5400, use_chat=True):
    """スタジオの配信の analysis(flow/batch._apply の形)。ended = 配信が終わった時刻(releaseTs + duration)"""
    return {"at": int(at * 1000), "signals": {"audio": True, "chat": chat, "comments": True},
            "counts": {"chat": 12835 if chat else 0, "cands": cands, "fills": 0}, "warnings": [],
            "spec": {"count": 8, "length": 160, "sensitivity": "low", "fill": fill, "useChat": use_chat},
            "releaseTs": int(ended - 3560), "duration": 3560, "liveStatus": "was_live"}


class ShortTools(T.HttpTools):
    """本数が足りないときの段を見る道具: スタジオの配信 1 本(video)・解析の順番(覚えて、すぐ済み)・採用"""

    def __init__(self, video, after=None):
        super().__init__(None)
        self.v, self.after, self.adds, self.adopt = video, after, [], None

    def video(self, vid):
        return 200, {"video": self.v}

    def analyze_add(self, item, settings):
        self.adds.append((item, settings))
        if self.after is not None:   # 解析が済んだ = 配信の analysis が新しくなる
            self.v = dict(self.v, analysis=self.after)
        return {"added": [{"qid": "q%d" % len(self.adds)}]}

    def analyze_items(self):
        return [{"qid": "q%d" % len(self.adds), "status": "done", "marks": 5}]

    def request_marks(self, body):
        return self.adopt


class TestShortfall(unittest.TestCase):
    """頼まれた本数に届かないとき(配信の約 1.5 時間後でチャットのリプレイが 0 件・山が 1 つで 5 本のうち 1 本、
    同じ依頼の送り直しも「解析済み(前の結果を使います)」で 1 本のまま): 埋める・解析し直す・チャットを取り直す・理由を残す"""

    def setUp(self):
        self.now = [NOW]

    def runner(self, tools):
        self.logs = []
        return R.Runner(None, poll=0, sleep=lambda s: None, tools=tools, clock=lambda: self.now[0], log=self.logs.append)

    def step(self, rn, run, key="analyze", v=None):
        st = run.step(key)
        st["state"] = "run"
        out = getattr(rn, "_step_" + key)(run, st, v if v is not None else rn.tools.v)
        return out, st

    def test_redo_reason(self):
        one = [{"id": "a1", "status": "exported"}]
        self.assertEqual(R.redo_reason(analysis_of(), 5, one, NOW), "short")   # 同じ依頼の 2 回目: 1 本しか無い・埋めていない
        self.assertIsNone(R.redo_reason(analysis_of(fill=5), 5, one, NOW))   # もう埋めた(それでも無い)= 解析し直さない
        self.assertIsNone(R.redo_reason(analysis_of(), 5, one * 5, NOW))   # 足りている
        self.assertIsNone(R.redo_reason(analysis_of(), 2, [{"id": "j", "status": "", "pieces": 2}], NOW))   # つないだ 1 本 = 元の 2 本(足りている)
        self.assertEqual(R.redo_reason(analysis_of(), 5, [{"id": "x", "status": "rejected"}] * 5 + one, NOW), "short")   # 見送りは数えない
        self.assertIsNone(R.redo_reason({"at": 1}, 5, [], NOW))   # 記録の形が無い前の解析は使い回す(今までどおり)
        self.assertIsNone(R.redo_reason(analysis_of(chat=False, fill=5), 5, one, NOW))   # 前の解析から 1 時間たっていない
        late = NOW + R.CHAT_RETRY_SEC
        self.assertEqual(R.redo_reason(analysis_of(chat=False, fill=5), 5, one, late), "chat")
        self.assertIsNone(R.redo_reason(analysis_of(chat=False, fill=5, use_chat=False), 5, one, late))   # チャットを使わない設定
        self.assertIsNone(R.redo_reason(analysis_of(chat=False, fill=5), 5, one, NOW + R.CHAT_RETRY_FRESH + 5400))   # 古い配信

    def test_reused_short_analysis_is_redone_with_fill(self):
        """解析済みでも本数に届かなければ、埋める数(採用の上限)を渡して解析し直す"""
        tools = ShortTools({"id": VID, "kind": "youtube", "analysis": analysis_of(), "marks": [{"id": "a1", "status": "exported"}]},
                           after=dict(analysis_of(fill=5, cands=5), counts={"chat": 12835, "cands": 5, "fills": 4}))
        rn = self.runner(tools)
        run = RF.run_of(VID, "配信", "request_auto", 5)
        _out, st = self.step(rn, run)
        self.assertEqual(len(tools.adds), 1)
        self.assertEqual(tools.adds[0][1]["fill"], 5)
        self.assertTrue(st["detail"].startswith(R.REDO_TEXT["short"] % 5), st["detail"])
        self.assertIn("うち 4 件は本数に届かないので", st["detail"])
        # 埋めた解析のあとは使い回す
        tools.v["marks"] = [{"id": "a1", "status": "exported"}]
        _out, st = self.step(rn, RF.run_of(VID, "配信", "request_auto", 5))
        self.assertEqual((st["state"], len(tools.adds)), ("skip", 1))

    def test_missing_chat_is_retried_by_the_patrol(self):
        """チャットのリプレイが 0 件の新しい配信: 解析のあと、見回りが 1 時間後に解析し直す(後回しの仕事)。使えたら・3 回で・古くなったら終わり"""
        tools = ShortTools({"id": VID, "kind": "youtube", "analysis": None, "marks": []}, after=analysis_of(chat=False, fill=5))
        rn = self.runner(tools)
        _out, st = self.step(rn, RF.run_of(VID, "配信", "request_auto", 5))
        self.assertIn("チャットのリプレイがまだ無いので、60 分後に解析し直します", st["detail"])
        self.assertEqual(rn.chat_retry_tick(), 0)   # まだ時間が来ていない
        self.now[0] += R.CHAT_RETRY_SEC
        self.assertEqual(rn.chat_retry_tick(), 1)
        item, settings = tools.adds[-1]
        self.assertEqual((item, settings["fill"]), ({"kind": "youtube", "videoId": VID, "prio": "later"}, 5))
        self.assertEqual(rn.chat_retry_tick(), 0)   # 次は 1 時間後
        tools.after = None
        tools.v["analysis"] = analysis_of(chat=True, fill=5, at=self.now[0])
        self.now[0] += R.CHAT_RETRY_SEC
        self.assertEqual(rn.chat_retry_tick(), 0)
        self.assertEqual(rn._chat_retry, {})   # チャットが使えた = 待ちから外す
        self.assertTrue(any("チャットが使えました" in m for m in self.logs), self.logs)

    def test_chat_retry_gives_up(self):
        tools = ShortTools({"id": VID, "kind": "youtube", "analysis": None, "marks": []}, after=analysis_of(chat=False, fill=5))
        rn = self.runner(tools)
        self.step(rn, RF.run_of(VID, "配信", "request_auto", 5))
        n = 0
        for _ in range(R.CHAT_RETRY_MAX + 2):
            self.now[0] += R.CHAT_RETRY_SEC
            n += rn.chat_retry_tick()
        self.assertEqual((n, rn._chat_retry), (R.CHAT_RETRY_MAX, {}))
        old = ShortTools({"id": VID, "kind": "youtube", "analysis": None, "marks": []}, after=analysis_of(chat=False, ended=NOW - R.CHAT_RETRY_FRESH - 1))
        rn = self.runner(old)
        _out, st = self.step(rn, RF.run_of(VID, "配信", "request_auto", 5))
        self.assertEqual(rn._chat_retry, {})   # 古い配信は取り直さない
        self.assertNotIn("取り直", st["detail"])

    @mock.patch.object(R._url_pick, "HEAT_ONE_ON", False)   # チャットの無い配信の 1 本減(flow/url_pick)は test_url_pick で見る
    def test_adopt_records_why_short(self):
        """採用の段の文(記録 autorun-runs.jsonl に残る)に、埋めた数と足りなかった理由"""
        marks = [{"id": "a1", "reasons": ["音量が急上昇"]}, {"id": "a2", "reasons": ["音声の変化", R._excite.FILL_REASON]}]
        a = dict(analysis_of(chat=False, fill=5, cands=2), counts={"chat": 0, "cands": 2, "fills": 1})
        tools = ShortTools({"id": VID, "kind": "youtube", "analysis": a, "marks": marks})
        tools.adopt = {"rangeIds": [], "humanIds": [], "autoIds": ["a1", "a2"], "added": ["a1", "a2"]}
        rn = self.runner(tools)
        _out, st = self.step(rn, RF.run_of(VID, "配信", "request_auto", 5), key="adopt", v=dict(tools.v, duration=3560))
        self.assertEqual(st["detail"], "自動で 2 本を足しました(点数の高い順)(うち 1 本は本数に届かないので、点数の低い山で埋めました)。候補が足りず 3 本は選べませんでした"
                                       "(チャットのリプレイが使えなかった(0 件)・盛り上がりの山が 2 個しか見つからなかった(しきい値の下の山で埋めても))")


class TestUrlPick(unittest.TestCase):
    """友人の URL の自動依頼(本数だけ)の採用(flow/url_pick。10-30): 最終の候補の点の順・縮め・heatmap の山を 1 本足す・長い / チャットの無い配信は 1 本減らす"""

    def cands(self):
        return [{"start": 100.0, "end": 200.0, "score": 9.0, "peak": 120.0, "final": 0.5, "settle": 150.0},
                {"start": 300.0, "end": 400.0, "score": 8.0, "peak": 320.0, "final": 2.0},
                {"start": 500.0, "end": 560.0, "score": 1.0, "origin": "heatmap"}]

    def step(self, a, top=3, dur=3560, adopt=None):
        class Tools(ShortTools):
            def request_marks(self, body):
                self.body = body
                return self.adopt
        tools = Tools({"id": VID, "kind": "youtube", "analysis": a, "marks": []})
        tools.adopt = adopt or {"rangeIds": [], "humanIds": [], "autoIds": ["a1", "a2"], "added": ["a1", "a2", "h1"], "extraIds": ["h1"]}
        rn = R.Runner(None, poll=0, sleep=lambda s: None, tools=tools, clock=lambda: NOW, log=lambda *x: None)
        run = RF.run_of(VID, "配信", "request_auto", top)
        st = run.step("adopt")
        st["state"] = "run"
        rn._step_adopt(run, st, dict(tools.v, duration=dur))
        return tools.body, st, run

    def test_pick(self):
        a = dict(analysis_of(), cands=self.cands())
        body, st, run = self.step(a)
        self.assertEqual(body["top"], 3)
        self.assertEqual(body["pref"], {"order": [[300.0, 400.0], [100.0, 200.0]], "ends": [[100.0, 200.0, 150.0]], "extra": [[500.0, 560.0]]})
        self.assertEqual(st["urlPick"], {"final": True, "cut": 1, "low": None, "heat": True})
        self.assertIn("h1", run.marks)   # 足した 1 本も書き出す
        self.assertIn("最終の候補の点の順", st["detail"])
        self.assertIn("よく見られている場面を 1 本足しました", st["detail"])
        body, st, _run = self.step(a, dur=3 * 3600)
        self.assertEqual((body["top"], st["urlPick"]["low"]), (2, "long"))   # 3 時間以上 = 1 本減らす
        self.assertIn("3 時間以上の配信なので 1 本減らしました", st["detail"])
        body, st, _run = self.step(dict(analysis_of(chat=False), cands=self.cands()), top=1)
        self.assertEqual((body["top"], st["urlPick"]["low"]), (1, None))   # 1 本は減らさない
        with mock.patch.object(R._url_pick, "FINAL_ON", False), mock.patch.object(R._url_pick, "HEAT_ONE_ON", False):
            body, st, _run = self.step(dict(analysis_of(chat=False), cands=self.cands()))
            self.assertEqual((body["top"], "pref" in body), (3, False))   # スイッチを切れば前の形


class TestStepNormalize(unittest.TestCase):
    """段 normalize(動画ファイルの実行の最初。opt-human 9a-1): 写しを 30fps に置き換える。
    本物の ffmpeg で lavfi の短い動画を「作業データへ写した動画」にする"""

    def setUp(self):
        self.tmp = testkit.tempdir(self, "run-norm-")
        self.env = mock.patch.dict(os.environ, {"TRANSCRIBE_NORMALIZE": ""})
        self.env.start()
        par = mock.patch.object(R.Runner, "_norm_parallel_ok", lambda self, run: False)   # 段の中で作り直す形 = 付け替えの口が無い LocalTools(並べる形は TestNormalizeParallel)
        par.start()
        self.addCleanup(par.stop)
        self.marks = []

        test = self

        class Hooked(R.Runner):
            def _checkpoint(self, run):
                test.marks.append(run.source_path)
        self.runner = Hooked(FakeClient(), poll=0.01, sleep=lambda s: None)

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self, name, fps, ext=".mp4"):
        from ytt import tools as ytools
        path = os.path.join(self.tmp, name + ext)
        subprocess.run([ytools.find_tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=%s:duration=2" % fps,
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path],
                       check=True, stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return path

    def run_step(self, path, mode="file_auto"):
        run = RF.run_of(None, "依頼", mode, None, source_path=path, request_id="20261016-120000-abcdef", normalize=True)
        st = run.step("normalize")
        self.runner._file_normalize(run, st)
        return run, st

    def test_steps_only_when_asked(self):
        """段を持つのは normalize=True の実行だけ(入口の start_file。ライブの書き出し・CLI・② の口 submit は持たない)・待ちの記録に残る・
        欄の無い古い記録は True で読む"""
        p = os.path.join(self.tmp, "a.mp4")
        r = RF.run_of(None, "a", "file", None, source_path=p, normalize=True)
        d = r.saved()
        self.assertIs(d["normalize"], True)
        self.assertIs(d["envelope"]["input"]["normalize"], True)   # 版 2 は封筒の input.normalize(欄 normalize は版 1 の記録だけ読む = TestRestoreGolden)
        self.assertEqual([s["key"] for s in R.Run.restore(d).steps], ["normalize", "transcribe"])
        self.assertEqual([s["key"] for s in R.Run.restore(dict(d, normalize=False)).steps], ["normalize", "transcribe"])

    def test_30fps_is_skipped(self):
        src = self.make("そのまま", 30)
        run, st = self.run_step(src)
        self.assertEqual((st["state"], st["detail"], run.source_path), ("skip", "30fps 済み", src))
        self.assertEqual(self.marks, [])

    def test_60fps_mov_is_replaced(self):
        """作り直したら run.source_path が新しい写し(.mp4)になり、古い写しは消え、待ちの記録を書き直す"""
        src = self.make("めっきー", 60, ".mov")
        run, st = self.run_step(src)
        self.assertNotIn(st["state"], ("skip", "warn"))   # 段の印(done)は _run_steps が付ける
        self.assertIn("30fps にそろえました", st["detail"])
        self.assertTrue(run.source_path.endswith(".mp4"), run.source_path)
        self.assertEqual(os.path.dirname(run.source_path), self.tmp)
        self.assertFalse(os.path.exists(src), "古い写しは消す")
        self.assertEqual(self.marks, [run.source_path])
        self.assertEqual(run.envelope()["input"]["path"], run.source_path)

    def test_cancel_after_replace_still_saves_new_path(self):
        """置き換えが済んだ直後に中止されても、新しいパスを待ちの記録へ書いてから止まる(再開が消えた元の写しを探さない)"""
        src = os.path.join(self.tmp, "元.mkv")
        open(src, "wb").close()
        new = os.path.join(self.tmp, "元.mp4")
        run = RF.run_of(None, "依頼", "file_auto", None, source_path=src, request_id="20261016-120000-abcdef", normalize=True)

        def fake_run(p, cancelled=None, on_progress=None, on_start=None):
            run.cancel = True   # 作り直しの終わりぎわに中止が来た
            return new, "作り直しました"
        with mock.patch.object(R._norm, "plan", lambda path, replace=True: {"why": ["60fps"]}), mock.patch.object(R._norm, "run", fake_run):
            with self.assertRaises(R.Cancelled):
                self.runner._file_normalize(run, run.step("normalize"))
        self.assertEqual((run.source_path, self.marks), (new, [new]))

    def test_failure_keeps_copy_and_continues(self):
        src = self.make("失敗", 60)
        with open(src, "rb") as f:
            original = f.read()
        from ytt import normalize as vnorm

        def boom(*a, **kw):
            raise vnorm.NormalizeError("作り直しに失敗しました: テスト")
        with mock.patch.object(vnorm, "normalize", boom):
            run, st = self.run_step(src)
        self.assertEqual((st["state"], run.source_path), ("warn", src))
        self.assertIn("30fps にそろえられませんでした", st["detail"])
        with open(src, "rb") as f:
            self.assertEqual(f.read(), original, "写しのまま続ける")

    def test_after_transcribe_is_skipped(self):
        """戻した実行で文字起こしが済んでいれば作り直さない(文書の動画を変えない)"""
        src = self.make("済み", 60)
        run = RF.run_of(None, "依頼", "file_auto", None, source_path=src, normalize=True)
        run.step("transcribe")["state"] = "done"
        st = run.step("normalize")
        self.runner._file_normalize(run, st)
        self.assertEqual((st["state"], run.source_path), ("skip", src))

    def test_waits_for_slot_and_can_be_cancelled(self):
        """重い処理の枠は段の中で取る(実行の糸が待つ = 受付の見回りは止まらない)。待っている間の中止は Cancelled"""
        import threading
        from ytt import jobs as yjobs
        src = self.make("待つ", 60)
        slots = yjobs.HeavySlots(limit=1, reserved={})
        token = slots.acquire("test", "枠を埋める")
        run = RF.run_of(None, "依頼", "file", None, source_path=src, normalize=True)
        st = run.step("normalize")
        got = []

        def go():
            try:
                self.runner._file_normalize(run, st)
                got.append("done")
            except R.Cancelled:
                got.append("cancelled")
        try:
            with mock.patch.object(yjobs, "SLOTS", slots):
                t = threading.Thread(target=go, daemon=True)
                t.start()
                for _ in range(100):
                    if slots.snapshot()["waiting"]:
                        break
                    t.join(0.05)
                self.assertEqual([w["label"] for w in slots.snapshot()["waiting"]], ["30fps にそろえる: 依頼"])
                self.assertEqual(st["detail"], "重い処理の枠が空くのを待っています")
                run.cancel = True
                t.join(30)
        finally:
            slots.release(token)
        self.assertEqual(got, ["cancelled"])
        self.assertEqual(run.source_path, src)


class TestNormalizeParallel(unittest.TestCase):
    """30fps の作り直しと文字起こしを並べる(R.Runner._norm_parallel_ok): 作り直しは裏の糸・元の写しで文字起こし・済んだら付け替えて元を消す"""

    def setUp(self):
        self.tmp = testkit.tempdir(self, "run-normpar-")
        self.src = os.path.join(self.tmp, "依頼.mkv")
        with open(self.src, "wb") as f:
            f.write(b"x")
        self.relinked = []
        test = self

        class Tools(T.HttpTools):
            why = None

            def relink(self, tid, path):
                test.relinked.append((tid, path))
                return self.why
        self.tools = Tools(FakeClient())
        self.runner = R.Runner(FakeClient(), poll=0.01, sleep=lambda s: None, tools=self.tools)
        self.runner._checkpoint = lambda run: None
        self.run = RF.run_of(None, "依頼", "file_auto", None, source_path=self.src, request_id="20261016-120000-abcdef", normalize=True)

    def start(self, out):
        """作り直しを始める(out = 作り直しの結果。パスなら写しを作る)-> 段"""
        def fake_run(plan, cancelled=None, **kw):
            self.plan = plan
            if out[0]:
                with open(plan["dst"], "wb") as f:
                    f.write(b"30")
                return plan["dst"], "作り直しました"
            return out
        def fake_audio(src, dst):
            with open(dst, "wb") as f:
                f.write(b"aac")
            return True
        st = self.run.step("normalize")
        with mock.patch.object(R._norm, "plan", lambda path, replace=True: {"src": path, "dst": os.path.splitext(path)[0] + ".mp4", "why": ["60fps"], "replace": True}), \
                mock.patch.object(R._norm, "run", fake_run), mock.patch.object(R, "_vnorm_audio", fake_audio):
            self.runner._file_normalize(self.run, st)
            self.run.norm_bg["thread"].join(10)
        self.audio = self.run.norm_bg["audio"]
        self.assertTrue(os.path.isfile(self.audio))   # 文字起こしに渡す音(作り直しと同じ AAC)
        return st

    def test_relinks_doc_and_removes_copy(self):
        st = self.start((True,))
        self.assertIs(self.plan["replace"], False)   # 元は付け替えが済むまで消さない(文字起こしが読む)
        self.assertEqual(self.run.source_path, self.src)   # 文字起こしは元の写しで
        self.run.doc_id = "t1"
        self.runner._norm_join(self.run)
        new = os.path.splitext(self.src)[0] + ".mp4"
        self.assertEqual((self.relinked, self.run.source_path), ([("t1", new)], new))
        self.assertFalse(os.path.exists(self.src))
        self.assertFalse(os.path.exists(self.audio))   # 音は片付ける
        self.assertIn("並べて", st["detail"])
        self.assertIsNone(self.run.norm_bg)

    def test_audio_failure_falls_back_inline(self):
        """音を作れなければ並べずに段の中で作り直す(今の形)"""
        st = self.run.step("normalize")
        with mock.patch.object(R._norm, "plan", lambda path, replace=True: {"src": path, "dst": os.path.splitext(path)[0] + ".mp4", "why": ["60fps"], "replace": True}), \
                mock.patch.object(R._norm, "run", lambda plan, **kw: (None, "テストの失敗")), mock.patch.object(R, "_vnorm_audio", lambda s, d: False):
            self.runner._file_normalize(self.run, st)
        self.assertIsNone(self.run.norm_bg)
        self.assertEqual(st["state"], "warn")

    def test_relink_refused_keeps_original(self):
        """付け替えを断られたら、作った写しを消して元の写しのまま(警告)"""
        self.start((True,))
        self.tools.why = "先に更新されています"
        self.run.doc_id = "t1"
        self.runner._norm_join(self.run)
        st = self.run.step("normalize")
        self.assertEqual((st["state"], self.run.source_path), ("warn", self.src))
        self.assertTrue(os.path.exists(self.src))
        self.assertFalse(os.path.exists(os.path.splitext(self.src)[0] + ".mp4"))

    def test_failure_keeps_original(self):
        self.start((None, "30fps にそろえられませんでした(テスト)"))
        self.run.doc_id = "t1"
        self.runner._norm_join(self.run)
        st = self.run.step("normalize")
        self.assertEqual((st["state"], self.run.source_path, self.relinked), ("warn", self.src, []))
        self.assertIn("テスト", st["detail"])

    def test_same_name_gets_other_name(self):
        """元が .mp4(作り直しの名前と同じ)なら別の名前に作る(読んでいる元を上書きしない)"""
        self.src = self.run.source_path = os.path.join(self.tmp, "元.mp4")
        with open(self.src, "wb") as f:
            f.write(b"x")
        self.start((True,))
        self.assertNotEqual(os.path.normcase(self.plan["dst"]), os.path.normcase(self.src))
        self.run.doc_id = "t1"
        self.runner._norm_join(self.run)   # 済んだら元の名前へ戻す(文書は元のパスのまま = 付け替えない)
        self.assertEqual((self.run.source_path, self.relinked), (self.src, []))
        with open(self.src, "rb") as f:
            self.assertEqual(f.read(), b"30")
        self.assertFalse(os.path.exists(self.plan["dst"]))

    def test_no_relink_is_inline(self):
        self.runner.tools = object()   # 付け替えの口が無い(LocalTools)
        self.assertFalse(self.runner._norm_parallel_ok(self.run))


class TestEnvelopeV2(unittest.TestCase):
    """RV A2: 封筒 + 束の run.from・run.upto・run.onFail・hints.streamer から Run の形(mode・段の並び)が決まる"""

    def test_v2_normalize_and_bad_pairs(self):
        for env, spec, why in (({"id": "a", "kind": "docs", "specVersion": 2, "input": {"docId": "d1"}}, {"run": {"upto": "transcribe"}}, "run.upto"),
                               ({"id": "a", "kind": "url", "specVersion": 2, "input": {"videoId": "abcdefghijk"}}, {"run": {"from": "pack"}}, "run.from"),
                               ({"id": "a", "kind": "url", "specVersion": 2, "input": {"videoId": "abcdefghijk", "marks": ["m1"]}}, None, "マーク")):
            with self.assertRaises(ValueError, msg=why) as cm:
                R.Run.from_envelope(env, spec)
            self.assertIn(why, str(cm.exception))


if __name__ == "__main__":
    unittest.main()
