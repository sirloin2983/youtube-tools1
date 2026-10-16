# -*- coding: utf-8 -*-
"""pipeline/run.py(① の経路。RS1-7)のテスト。  py -3.10 -m unittest src/flow/tests/test_run.py -v
段の中身の細かい動きは src/home/tests/test_autorun.py(AutoRunner が Runner を継いだ形)で見る。ここは入口の関数・入力の形・hook の既定と、
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

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> pipeline -> src
sys.path.insert(0, SRC)
from flow import run as R  # noqa: E402
from flow import envelope as E, spec as SP, tools as T  # noqa: E402


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


class TestImport(unittest.TestCase):
    def test_imports_without_home(self):
        """home(案件・設定・届ける部品)を sys.path に置かずに読める = 層の向き"""
        code = ("import sys; sys.path.insert(0, %r); import flow.run as r; "
                "bad = [m for m in ('autorun', 'cases', 'prefs', 'deliver', 'friend_feedback', 'manage') if m in sys.modules]; "
                "print(bad); sys.exit(1 if bad else 0)") % SRC
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


class TestFromInput(unittest.TestCase):
    def test_from_mode(self):
        self.assertEqual(R.FROM_MODE, {None: "full", "analyze": "full", "export": "adopted", "transcribe": R.DOC_MODE})

    def test_video(self):
        r = R.Run.from_input({"videoId": "abcdefghijk"})
        self.assertEqual((r.video_id, r.mode, r.top, r.doc_id, r.source_path, r.state), ("abcdefghijk", "full", 3, None, None, "queued"))
        self.assertEqual([s["key"] for s in r.steps], list(R.MODE_STEPS["full"]))
        self.assertEqual(R.Run.from_input({"videoId": "abcdefghijk", "top": 5}, "export").mode, "adopted")
        self.assertEqual(R.Run.from_input({"videoId": "abcdefghijk", "top": 5}, "export").top, 5)
        self.assertEqual(R.Run.from_input({"videoId": "abcdefghijk"}, "transcribe").mode, R.DOC_MODE)
        with self.assertRaises(ValueError):
            R.Run.from_input({"videoId": "abcdefghijk"}, "pack")
        with self.assertRaises(ValueError):
            R.Run.from_input({"videoId": "abcdefghijk", "top": 99})

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
        古い形(欄だけ・束なし)も読める・合わない束は置かない"""
        r = R.Run.from_input({"docId": "d1"})
        self.assertIsNone(r.spec)
        self.assertIsNone(r.saved()["spec"])
        self.assertNotIn("spec", r.public())
        r.spec = SP.merge({"pack": {"size": "1920x1080"}})
        d = json.loads(json.dumps(r.saved()))
        self.assertEqual(d["envelope"], json.loads(json.dumps(E.check(r.envelope()))))
        back = R.Run.restore(d)
        self.assertEqual((back.id, back.doc_id, back.spec), (r.id, "d1", r.spec))
        old = {k: v for k, v in d.items() if k not in ("envelope", "spec")}   # RS7-1 より前の形
        self.assertIsNone(R.Run.restore(old).spec)
        self.assertEqual(R.Run.restore(old).doc_id, "d1")
        self.assertIsNone(R.Run.restore(dict(d, spec={"pack": {"size": "1x1"}})).spec)
        new_only = {k: d[k] for k in ("id", "envelope", "spec", "state", "steps", "created", "docs")}   # 欄の鍵の無い新しい形
        back = R.Run.restore(new_only)
        self.assertEqual((back.id, back.mode, back.doc_id, back.spec, back.resumed), (r.id, R.DOC_MODE, "d1", r.spec, True))
        self.assertIsNone(R.Run.restore(dict(new_only, envelope=dict(d["envelope"], specVersion=99))))

    def test_full_with_deliver_dir_adds_deliver_step(self):
        """D-SEND: full で届け先(deliver_dir)があれば末尾に段 deliver。MODE_STEPS の full は変えない・ほかの形は足さない"""
        self.assertEqual(R.MODE_STEPS["full"], ("analyze", "adopt", "export", "transcribe", "pack"))
        keys = lambda r: [s["key"] for s in r.steps]  # noqa: E731
        self.assertEqual(keys(R.Run("abcdefghijk", "t", "full", 3)), list(R.MODE_STEPS["full"]))
        r = R.Run("abcdefghijk", "t", "full", 3, deliver_dir="D:/out")
        self.assertEqual(keys(r), list(R.MODE_STEPS["full"]) + ["deliver"])
        r = R.Run("abcdefghijk", "t", "full", 3, deliver_dir="D:/out", speakers={"count": 2, "names": []})
        self.assertEqual(keys(r), ["analyze", "adopt", "export", "transcribe", "diarize", "pack", "deliver"])
        self.assertEqual(keys(R.Run("abcdefghijk", "t", "adopted", 3, deliver_dir="D:/out")), list(R.MODE_STEPS["adopted"]))
        self.assertEqual(keys(R.Run("abcdefghijk", "t", "request_auto", 3, deliver_dir="D:/out")), list(R.MODE_STEPS["request_auto"]), "二重に足さない")

    def test_deliver_tag_origin_saved_restored(self):
        r = R.Run("abcdefghijk", "t", "full", 3, deliver_dir="D:/out", deliver_tag="20261016-120000-abc123", deliver_origin="auto")
        d = json.loads(json.dumps(r.saved()))
        self.assertEqual((d["deliverTag"], d["deliverOrigin"]), ("20261016-120000-abc123", "auto"))
        back = R.Run.restore(d)
        self.assertEqual((back.deliver_tag, back.deliver_origin, back.deliver_dir), ("20261016-120000-abc123", "auto", "D:/out"))
        self.assertEqual([s["key"] for s in back.steps], [s["key"] for s in r.steps])
        self.assertEqual(r.envelope()["deliver"]["origin"], "auto")
        self.assertEqual(R.Run.from_envelope(E.check(r.envelope())).deliver_origin, "auto")
        self.assertIsNone(R.Run("abcdefghijk", "t", "full", 3, deliver_tag="", deliver_origin="zzz").deliver_tag)
        self.assertIsNone(R.Run("abcdefghijk", "t", "full", 3, deliver_origin="zzz").deliver_origin)

    def test_restore_old_record_without_deliver_fields(self):
        """D-SEND より前の待ちの記録(deliverTag・deliverOrigin が無い)も読める。届け先のある request_auto の段は今までどおり"""
        r = R.Run("abcdefghijk", "t", "request_auto", 3, request_id="20261001-000000-aaaaaa", deliver_dir="D:/out")
        d = r.saved()
        d.pop("deliverTag"), d.pop("deliverOrigin")
        d["envelope"]["deliver"].pop("origin")
        back = R.Run.restore(d)
        self.assertEqual((back.deliver_tag, back.deliver_origin, back.deliver_dir), (None, None, "D:/out"))
        self.assertEqual([s["key"] for s in back.steps], list(R.MODE_STEPS["request_auto"]))
        new_only = {k: d[k] for k in ("id", "envelope", "spec", "state", "steps", "created", "docs")}   # 封筒だけの形(origin の鍵が無い古い封筒)
        self.assertIsNone(R.Run.restore(new_only).deliver_origin)

    def test_restore_skips_removed_post_analyze(self):
        """消した「あとから解析」(mode post_analyze。RS4)が以前の待ちの記録に残っていても、落ちずに読み飛ばす(同じ形の full は戻る)"""
        d = R.Run.from_input({"videoId": "abcdefghijk"}).saved()
        self.assertIsNotNone(R.Run.restore(d))
        self.assertNotIn("post_analyze", R.MODE_STEPS)
        self.assertIsNone(R.Run.restore(dict(d, mode="post_analyze", steps=[{"key": "analyze", "state": "run", "detail": ""}])))


class TestHooks(unittest.TestCase):
    def test_defaults_know_nothing(self):
        rn = R.Runner(FakeClient())
        run = R.Run.from_input({"docId": "d1"})
        run.resumed = True
        rn._await_tools(run)
        self.assertFalse(run.resumed)
        self.assertIsNone(rn._checkpoint(run))
        self.assertEqual(rn._studio_video("abcdefghijk"), {})
        self.assertIsNone(rn._friend_length())
        self.assertEqual(rn._docs(), [])
        self.assertIsNone(rn._pick_doc([], "abcdefghijk", "m1", "/x.mp4"))
        self.assertEqual(rn._pref("cut", "none"), "none")
        self.assertFalse(rn._live_auto_origin("/x.mp4"))
        self.assertIsNone(rn._auto_streamer(run))
        self.assertIsNone(run.streamer)
        self.assertIsNone(rn._after_pack(run, {}, ""))
        self.assertFalse(rn._remember_styles("t1", {"A": {"color": "#112233"}}))
        self.assertFalse(rn._remember_doc_streamer("t1", "A"))
        self.assertIsNone(rn.find_pack("/x.mp4"))
        self.assertFalse(rn.closed)
        self.assertEqual(rn._cut_method(), "none")


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
        self.assertEqual(r.spec, SP.validate(SP.merge({"transcribe": {"model": "large-v3"}, "post": {"autoDict": False}})))
        self.assertEqual((r.doc_id, r.docs, r.new_docs), ("t1", ["t1"], ["t1"]))
        self.assertEqual(r.step("transcribe")["state"], "done")
        self.assertEqual(r.message, "完了")
        self.assertIn(("transcribe", "POST", "/api/transcribe"), c.calls)
        self.assertNotIn("/api/settings", [x[2] for x in c.calls])
        self.assertEqual(c.bodies["/api/transcribe"], dict(SP.tx_opts(r.spec), sourcePath=self.media))
        self.assertEqual((c.bodies["/api/transcribe"]["model"], c.bodies["/api/transcribe"]["autoDict"]), ("large-v3", False))
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
                                        "silence": {"noise": -40, "min": 0.6, "pad": 0.15}})
        self.assertEqual(body["output"], {"textplus": True, "textplusWrap": 12, "textplusSize": "1920x1080", "textplusFps": "30",
                                          "speakerColors": True, "volume": 50})
        self.assertEqual(r.packs, [os.path.normpath("/x/clip_pack")])

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

    def test_doc_pack_hint_shapes(self):
        """届けた先の形: ライブでない文書・壊れた clip でも path は残し、markId は ""(友人の動画の依頼はスタジオのマークが無い)"""
        self.assertEqual(R.doc_pack_hint({"sourcePath": "/x/a.mp4"}), {"path": "/x/a.mp4", "markId": ""})
        self.assertEqual(R.doc_pack_hint({"sourcePath": "/x/a.mp4", "clip": {"source": "x"}}), {"path": "/x/a.mp4", "markId": ""})
        self.assertEqual(R.doc_pack_hint({"clip": {"source": {"live": {"studio": {"mark": 3}}}}}), {"path": "", "markId": ""})

    def test_tools_are_injected(self):
        """段は self.tools に頼む(既定は HttpTools(client)。tools を渡せば client は使わない)"""
        self.assertIsInstance(R.Runner(None).tools, T.HttpTools)
        calls = []

        class Tools(T.HttpTools):
            def docs(self):
                return []

            def transcribe_start(self, req, bundle=None):
                calls.append(("start", req["sourcePath"], bundle["transcribe"]["model"]))
                return "j9"

            def jobs(self):
                return [{"id": "j9", "state": "done", "tid": "t9"}]
        r = R.run(None, {"path": self.media}, tools=Tools(None))
        self.assertEqual((calls, r.doc_id), ([("start", self.media, "large-v3")], "t9"))   # 束の既定のモデル(0.58.0 から large-v3)

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
        run = R.Run("abcdefghijk", "配信", mode, top, ranges=ranges, fresh=fresh)
        run.spec = SP.validate(SP.merge(spec))
        tools = AdoptTools(res)
        rn = R.Runner(None, tools=tools)
        st = run.step("adopt")
        st["state"] = "run"
        out = rn._step_adopt(run, st, {"duration": 1000})
        return out, st, run, tools.bodies[0]

    def test_human_adoption_counts_and_rest_is_filled(self):
        """人が 1 本採用した配信の再実行: 上限までの残り 2 本を自動で足す(以前は「人が採用済みなら自動は 0」で飛ばした)"""
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
        out, st, run, body = self.adopt(res, mode="request", top=4, ranges=[(100.0, 120.0)], spec={"adopt": {"pad": 5.0}},
                                        fresh={"title": "題", "channel": "ch"})
        self.assertEqual(body, {"id": "abcdefghijk", "ranges": [[95.0, 125.0]], "top": 4, "title": "題", "channel": "ch"})
        self.assertEqual((out, st["state"], run.marks), (None, "run", ("r1", "h1", "a1")))
        self.assertEqual(st["detail"], "指定の区間 1 個(前後に 5 秒の余白)・人が採用した 1 本・自動で 1 本を足しました(点数の高い順)。候補が足りず 1 本は選べませんでした")

    def test_top_from_bundle_when_run_has_none(self):
        _out, _st, _run, body = self.adopt({"autoIds": ["a1"], "added": ["a1"]}, top=None, spec={"adopt": {"top": 5}})
        self.assertEqual(body["top"], 5)


class TestKeys(unittest.TestCase):
    """鍵を読む段(RS6 b-K2): 文字起こし = 同じ・鍵なしは飛ばす / 違えば飛ばして印 / force で作り直す。パック = 違えば作り直す / 同じは飛ばす / 鍵なしは今のまま"""

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
        run = R.Run("abcdefghijk", "配信", "adopted", 3, force=force)
        run.spec = SP.validate(SP.merge(spec))
        st = run.step(key)
        st["state"] = "run"
        getattr(rn, "_step_" + key)(run, st, self.video)
        return st, run

    def test_transcribe_same_and_none_skip(self):
        for state in ("same", "none"):
            c = FakeClient()
            st, _run = self.step(self.runner(c, tx_state=state), "transcribe")
            self.assertEqual((st["state"], st["detail"]), ("skip", "1 本とも文字起こし済み"), state)
            self.assertNotIn(("transcribe", "POST", "/api/transcribe"), c.calls)

    def test_transcribe_differ_marks_and_force_redoes(self):
        c = FakeClient()
        st, _run = self.step(self.runner(c, tx_state="differ"), "transcribe")
        self.assertEqual((st["state"], st["detail"]), ("skip", "1 本とも文字起こし済み。うち 1 本は" + R.TX_DIFFER))
        self.assertNotIn(("transcribe", "POST", "/api/transcribe"), c.calls)
        for kw in ({"force": True}, {"spec": {"run": {"force": True}}}):   # Run の force・束の run.force
            c = FakeClient()
            st, run = self.step(self.runner(c, tx_state="differ"), "transcribe", **kw)
            self.assertEqual(st["state"], "run", kw)
            self.assertIn("作り直し(force)", st["detail"])
            self.assertEqual(run.new_docs, ["t1"])

    def test_pack_differ_rebuilds_with_force(self):
        c = FakeClient()
        st, run = self.step(self.runner(c, pack_state="differ", have_pack=True), "pack")
        self.assertEqual(st["state"], "run", st)
        self.assertIn(R.PACK_DIFFER, st["detail"])
        self.assertIs(c.bodies["/api/build"]["output"]["force"], True)
        self.assertEqual(run.packs, [os.path.normpath("/x/clip_pack")])

    def test_pack_same_skips_and_none_keeps_today(self):
        c = FakeClient()
        st, _run = self.step(self.runner(c, pack_state="same"), "pack")   # パックの記録が無くても、鍵が同じなら飛ばす
        self.assertEqual(st["state"], "skip")
        self.assertNotIn("/api/build", c.bodies)
        c = FakeClient()
        st, _run = self.step(self.runner(c, pack_state="none", have_pack=True), "pack")   # 鍵なし + パックあり = 今のまま飛ばす
        self.assertEqual(st["state"], "skip")
        c = FakeClient()
        st, _run = self.step(self.runner(c, pack_state="none"), "pack")   # 鍵なし + パックなし = 作る(上書きはしない)
        self.assertEqual(st["state"], "run")
        self.assertNotIn("force", c.bodies["/api/build"]["output"])

    def test_pack_state_writes_nothing_and_matches_written_key(self):
        """指摘 2: 鍵の比べ(見積もりも同じ関数)は字幕の受け渡しの JSON を書かない。書かずに作った材料の鍵は、書いたファイルから作った鍵と同じ"""
        c = FakeClient(full=[self.doc])
        rn = R.Runner(c, poll=0, sleep=lambda s: None)
        run = R.Run("abcdefghijk", "配信", "adopted", 3)
        run.spec = SP.validate(SP.merge(None))
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
            packrec.write_record({"out_dir": pack, "files": [("video", v)]}, self.media, False, False)
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
                            request_id="r1", deliver_dir="/out", deliver_batch=3, streamer="ぺこら", cut="silence", video_tracks=1,
                            speakers={"count": 2, "names": ["A"], "styles": {"A": {"color": "#112233"}}}),
            "live_file": dict(video_id=None, title="ライブ", mode="file_auto", top=None, source_path=m, engine="whisper.cpp", model="large-v3",
                              cut="none", pool={"key": "k1", "rid": "x"}),
            "engine_same": dict(video_id=None, title="動画", mode="file", top=None, source_path=m, engine="whisper.cpp", model="large-v3"),
            "doc_overwrite": dict(video_id=None, title="文書", mode=R.DOC_MODE, top=None, doc_id="d1", overwrite=True),
            "adopted_force": dict(video_id=VID, title="配信", mode="adopted", top=5, force=True, marks=("m1",)),
        }

    @staticmethod
    def make(kw):
        kw = dict(kw)
        return R.Run(kw.pop("video_id"), kw.pop("title"), kw.pop("mode"), kw.pop("top"), **kw)

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
            r1 = self.make(kw)
            r1.spec = base
            env, spec = json.loads(json.dumps(r1.envelope())), json.loads(json.dumps(r1.spec))
            r2 = R.Run.from_envelope(env, spec)
            self.assertEqual(r2.spec, r1.spec, name)
            self.assertEqual([s["key"] for s in r2.steps], [s["key"] for s in r1.steps], name)
            for f in ("id", "mode", "top", "ranges", "weights", "cut", "video_tracks", "speakers", "engine", "model", "overwrite", "force", "streamer",
                      "request_id", "deliver_dir", "deliver_batch", "pool", "fresh", "duration", "marks", "source_path", "doc_id", "title", "on_fail"):
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
        self.assertEqual(rq["diarize"], [{"numSpeakers": 2, "names": ["A"], "recognize": True, "tid": "t1"}])
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

    def test_no_fields_is_screen_bundle(self):
        """欄の無い Run(画面のまとめて実行・CLI)は束がそのまま(写す物が無い)"""
        base = SP.validate(SP.merge(SCREEN))
        r = R.Run(VID, "", "full", None)
        r.spec = base
        self.assertEqual((r.asked, r.spec), ({}, base))

    def test_long_name_is_cut_and_bad_fields_not_copied(self):
        """束に入らない欄は写さない(壊れた記録など)・41 字以上の名前は束の上限 40 字で切る(友人の受付は 60 字まで)"""
        r = R.Run(VID, "", "full", 99, video_tracks=9, weights={"wAudio": 1}, speakers={"count": 2, "names": ["あ" * 50]})
        self.assertNotIn("adopt", r.asked)
        self.assertNotIn("analyze", r.asked)
        self.assertEqual(r.asked["hints"]["people"], [{"name": "あ" * 40}])
        self.assertNotIn("pack", r.asked)
        r.spec = SP.merge(None)
        self.assertEqual(r.spec["adopt"]["top"], SP.DEFAULTS["adopt"]["top"])

    def test_from_envelope_defaults_and_refusals(self):
        r = R.Run.from_envelope({"id": "0123456789", "kind": "url", "input": {"url": "https://www.youtube.com/watch?v=abcdefghijk"}},
                                {"adopt": {"top": 2}, "hints": {"ranges": [[10, 20]]}})
        self.assertEqual((r.id, r.video_id, r.mode, r.top, r.ranges, r.title), ("0123456789", VID, "full", 2, [(10, 20)], VID))
        r = R.Run.from_envelope({"id": "x-1", "kind": "file", "input": {"path": self.media}})
        self.assertEqual((r.mode, r.source_path, len(r.id)), ("file_auto", self.media, 10))   # 10 桁の 16 進でない id は実行の id にしない
        for env in ({"id": "a", "kind": "live", "input": {"videoId": VID}},
                    {"id": "a", "kind": "docs", "input": {"docId": "d1"}, "legacy": {"mode": "full"}},
                    {"id": "a", "kind": "docs", "input": {"docId": "d1"}, "extra": 1}):
            with self.assertRaises(ValueError, msg=env):
                R.Run.from_envelope(env)

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
        r = R.Run.from_envelope(env, {"run": {"force": True}})   # from が無ければ今までどおり(force で作り直す)
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
        r = R.Run.from_envelope({"id": "a", "kind": "file", "input": {"path": self.media}, "legacy": {"mode": "file"}},
                                {"transcribe": {"model": "large-v3"}})
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
        r = R.Run(VID, "配信", "request", 3, ranges=[(10.0, 20.0)])
        r.friend_plan, r.notes = plan, ["知らせ"]
        r.spec = SP.merge({"analyze": {"length": 38, "preRatio": 0.61}})
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


class TestStepNormalize(unittest.TestCase):
    """段 normalize(動画ファイルの実行の最初。opt-human 9a-1 で友人の受付 intake から移した): 写しを 30fps に置き換える。
    本物の ffmpeg で lavfi の短い動画を「作業データへ写した動画」にする"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="run-norm-")
        self.env = mock.patch.dict(os.environ, {"TRANSCRIBE_NORMALIZE": ""})
        self.env.start()
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
        run = R.Run(None, "依頼", mode, None, source_path=path, request_id="20261016-120000-abcdef", normalize=True)
        st = run.step("normalize")
        self.runner._file_normalize(run, st)
        return run, st

    def test_steps_only_when_asked(self):
        """段を持つのは normalize=True の実行だけ(入口の start_file。ライブの書き出し・CLI・② の口 submit は持たない)・待ちの記録に残る・
        欄の無い古い記録は True で読む"""
        p = os.path.join(self.tmp, "a.mp4")
        self.assertEqual([s["key"] for s in R.Run(None, "a", "file_auto", None, source_path=p, normalize=True).steps],
                         ["normalize", "transcribe", "pack", "deliver"])
        self.assertEqual([s["key"] for s in R.Run(None, "a", "file", None, source_path=p).steps], ["transcribe"])
        self.assertEqual([s["key"] for s in R.Run.from_input({"path": p}).steps], ["transcribe"])
        self.assertEqual([s["key"] for s in R.Run.from_envelope({"id": "0123456789", "kind": "file", "input": {"path": p, "title": "a"}}).steps],
                         ["transcribe", "pack", "deliver"])
        r = R.Run(None, "a", "file", None, source_path=p, normalize=True)
        d = r.saved()
        self.assertIs(d["normalize"], True)
        self.assertEqual([s["key"] for s in R.Run.restore(d).steps], ["normalize", "transcribe"])
        self.assertEqual([s["key"] for s in R.Run.restore(dict(d, normalize=False)).steps], ["transcribe"])
        old = {k: v for k, v in d.items() if k != "normalize"}   # 段 normalize の前の記録
        self.assertEqual([s["key"] for s in R.Run.restore(old).steps], ["normalize", "transcribe"])

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
        from ytt import normalize as vnorm
        self.assertEqual(vnorm.probe(run.source_path)["r_frame_rate"], "30/1")
        self.assertEqual(self.marks, [run.source_path])
        self.assertEqual(run.envelope()["input"]["path"], run.source_path)
        self.assertEqual([n for n in os.listdir(self.tmp) if vnorm.PART in n], [], "途中のファイルは残さない")

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
        run = R.Run(None, "依頼", "file_auto", None, source_path=src, normalize=True)
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
        run = R.Run(None, "依頼", "file", None, source_path=src, normalize=True)
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


if __name__ == "__main__":
    unittest.main()
