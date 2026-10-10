# -*- coding: utf-8 -*-
"""flow/tools(段が道具を呼ぶ継ぎ目。役割で組み直す RS6 b-0)のテスト。  py -3.10 -m unittest src/flow/tests/test_tools.py -v

- LocalTools: 入口なしで 動画ファイル → 文字起こし → パック を 1 本(疑似のエンジン。疑似の差し込みはテストの側 = eval/fake/fake_asr の FAKE)
- LocalTools に無い段(配信・解析・採用・書き出し・話者分離)は「入口に頼んでください」の StepError
- HttpTools は今の API をそのまま呼ぶ(呼ぶ API と本文は src/home/tests/test_autorun.py が見る)
- 鍵を読んで飛ばす(RS6 b-K2): 同じ・違う・force と、HttpTools(API の形)と LocalTools で同じ Run.public
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない(一時フォルダだけ)
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> flow -> src
sys.path.insert(0, SRC)
from flow import run as R, tools as T  # noqa: E402
from pipeline.transcribe import backend, records, roster  # noqa: E402
from ytt import workdata  # noqa: E402
from eval.fake import fake_asr  # noqa: E402  (疑似の認識。flow は eval を読めないので、テストの側で差し込む)


def _make_video(path, sec=6):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x284:rate=30:duration=%d" % sec,
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=%d" % sec, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", path], check=True, timeout=120)


class TestHttpTools(unittest.TestCase):
    def test_calls_the_tool_api(self):
        calls = []

        class C:
            def call(self, tool, method, path, body=None):
                calls.append((tool, method, path, body))
                return 200, {"id": "j1", "jobs": [{"id": "j1"}], "items": [{"qid": "q1"}]}

            def ok(self, tool, method, path, body=None):
                return self.call(tool, method, path, body)[1]
        t = T.HttpTools(C())
        self.assertEqual(t.transcribe_start({"model": "small"}, bundle={"x": 1}), "j1")
        self.assertEqual(t.jobs(), [{"id": "j1"}])
        self.assertEqual(t.analyze_items(), [{"qid": "q1"}])
        t.edit("a b")
        self.assertEqual(t.docs(), [])   # 文書の一覧(GET /api/transcripts。id の無い行は読まない)
        self.assertEqual(calls, [("transcribe", "POST", "/api/transcribe", {"model": "small"}), ("transcribe", "GET", "/api/jobs", None),
                                 ("studio", "GET", "/api/queue", None), ("transcribe", "GET", "/api/edit?id=a%20b", None),
                                 ("transcribe", "GET", "/api/transcripts", None)])

    def test_docs_and_doc(self):
        """文書の一覧は要約(場所と行を持たない)・1 つは GET /api/transcript を段の形(doc_row)に"""
        doc = {"id": "abcdef012345", "title": "題", "sourcePath": "/x/c.mp4", "updatedAt": 5, "clip": {"source": {"videoId": "v1"}},
               "segments": [{"start": 0, "end": 1, "text": "あ", "cutState": "cut"}, {"start": 1, "end": 2, "text": "い"}]}

        class C:
            def call(self, tool, method, path, body=None):
                if path == "/api/transcripts":
                    return 200, {"items": [{"id": "abcdef012345", "title": "題", "sourceName": "c.mp4", "videoId": "v1", "updatedAt": 5, "segments": 2}]}
                if path == "/api/transcript?id=abcdef012345":
                    return 200, doc
                return 404, {}

            def ok(self, tool, method, path, body=None):
                return self.call(tool, method, path, body)[1]
        t = T.HttpTools(C())
        self.assertEqual(t.docs(), [{"id": "abcdef012345", "title": "題", "sourceName": "c.mp4", "videoId": "v1", "updatedAt": 5, "count": 2}])
        row = t.doc("abcdef012345")
        self.assertEqual((row["sourcePath"], row["videoId"], row["count"], [g["cut"] for g in row["segments"]]), ("/x/c.mp4", "v1", 2, [True, False]))
        self.assertIsNone(t.doc("nai"))


class TestLocalRefuses(unittest.TestCase):
    def test_steps_that_need_the_portal(self):
        t = T.LocalTools()
        for f in (lambda: t.video("abcdefghijk"), lambda: t.analyze_add({}, {}), lambda: t.request_marks({"id": "v", "ranges": [], "top": 1}), lambda: t.export_start({}),
                  lambda: t.diarize_start({})):
            with self.assertRaisesRegex(R.StepError, "入口"):
                f()
        with self.assertRaisesRegex(R.StepError, "入口"):
            R.run(None, {"videoId": "abcdefghijk"}, tools=T.LocalTools())

    def test_no_data_dir(self):
        """作業データの置き場所が決まっていなければ、文字起こしのジョブは失敗(段は StepError)"""
        with mock.patch.object(workdata, "TX_DIR", None):
            t = T.LocalTools()
            jid = t.transcribe_start({"sourcePath": __file__})
            self.assertEqual(t.jobs()[0]["state"], "error")
            self.assertIn("置き場所", t.jobs()[0]["error"])
            self.assertEqual(t.jobs()[0]["id"], jid)


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg が無い")
class TestLocalTranscribePack(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flowtools_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        data = os.path.join(self.tmp, "data")
        for name, value in (("ROOT", self.tmp), ("DATA_DIR", data), ("TX_DIR", os.path.join(data, "transcripts")), ("TMP_DIR", os.path.join(data, "transcripts", ".tmp")),
                            ("SETTINGS", os.path.join(data, "settings.json"))):
            p = mock.patch.object(workdata, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(roster, "ROSTER", os.path.join(self.tmp, "no-roster.json"))
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.dict(os.environ, {"TRANSCRIBE_FAKE_DELAY": "0"})
        p.start()
        self.addCleanup(p.stop)
        saved = backend._selector[0]
        backend.set_selector(lambda: fake_asr.FAKE)
        self.addCleanup(backend.set_selector, saved)
        self.video = os.path.join(self.tmp, "clip", "切り抜き.mp4")
        os.makedirs(os.path.dirname(self.video))
        _make_video(self.video)

    def test_file_then_pack(self):
        """動画ファイル → 文字起こし(② flow/tx の動詞で文書を書く)→ 同じ道具で 文書 → パック(① build_pack を直に)"""
        tools = T.LocalTools()
        spec = {"post": {"autoLlm": False}, "pack": {"volume": 100}}
        r1 = R.run(None, {"path": self.video}, spec=spec, tools=tools)
        self.assertEqual(r1.step("transcribe")["state"], "done", r1.steps)
        tid = r1.doc_id
        self.assertTrue(os.path.isfile(os.path.join(workdata.TX_DIR, tid + ".json")))
        self.assertTrue(os.path.isfile(os.path.join(workdata.TX_DIR, tid + ".asr.json")))
        doc = tools.docs()[0]
        self.assertEqual((doc["id"], doc["sourcePath"], doc["count"] > 0), (tid, os.path.abspath(self.video), True))
        self.assertTrue(doc["segments"][0]["text"].startswith("テスト文"))
        r2 = R.run(None, {"docId": tid}, spec=spec, tools=tools)
        self.assertEqual([s["state"] for s in r2.steps], ["skip", "done"], r2.steps)
        self.assertEqual(len(r2.packs), 1)
        names = os.listdir(r2.packs[0])
        self.assertTrue(any(n.endswith(".lua") for n in names), names)
        # もう一度: 同じ名前のパックがあるので上書きしない(409 exists = 段は飛ばす)
        r3 = R.run(None, {"docId": tid}, spec=spec, tools=tools)
        self.assertEqual(r3.step("pack")["state"], "skip", r3.steps)

    def test_learning_glossary_and_learned(self):
        """RS7-1 F-k: learning を渡すと用語は ユーザーの語 + 自動の語(glossAuto)・学習済みの置換は autoLearned のときだけ ① へ渡す。無ければ今まで"""
        class L:
            def __init__(self):
                self.calls = []

            def glossary(self, terms):
                self.calls.append(("glossary", list(terms)))
                return ["自動語"]

            def learned(self):
                self.calls.append(("learned",))
                return lambda text: []
        saved = dict(records._dict_inputs)   # 辞書の版の材料の口(CLI は wire.install が入れる。ここでは空で)
        records.set_dict_inputs(pairs=lambda spec: [], learned=lambda: "")
        self.addCleanup(lambda: (records._dict_inputs.clear(), records._dict_inputs.update(saved)))
        seen = []
        real = T._tx.transcribe_clip
        self.addCleanup(setattr, T._tx, "transcribe_clip", real)
        T._tx.transcribe_clip = lambda job, spec, wav, pairs, learned=None: (seen.append((spec, learned)), real(job, spec, wav, pairs, learned))[1]
        for auto_learned in (False, True):
            lg, seen[:] = L(), []
            tools = T.LocalTools(learning=lg)
            jid = tools.transcribe_start({"sourcePath": self.video, "glossary": "ユーザー語"}, T._spec.merge({"post": {"autoLlm": False, "autoLearned": auto_learned}}))
            self.assertEqual(tools.jobs()[0]["state"], "done", tools.jobs())
            spec, learned = seen[0]
            self.assertEqual((spec["glossary"], spec["glossAuto"]), (["ユーザー語", "自動語"], ["自動語"]))
            self.assertEqual(lg.calls[0], ("glossary", ["ユーザー語"]))
            self.assertEqual(("learned",) in lg.calls, auto_learned)
            self.assertEqual(callable(learned), auto_learned)
        seen[:] = []
        tools = T.LocalTools()
        tools.transcribe_start({"sourcePath": self.video, "glossary": "ユーザー語"}, T._spec.merge({"post": {"autoLlm": False, "autoLearned": True}}))
        self.assertEqual((seen[0][0]["glossary"], seen[0][0]["glossAuto"], seen[0][1]), (["ユーザー語"], [], None))   # learning なし = 今まで

    def sequence(self, tools):
        """鍵を読む段の一続き(RS6 b-K2) -> 各実行の (形, [(段, 状態, 詳しさ)]) と最後の文書の id"""
        spec = {"post": {"autoLlm": False}, "pack": {"volume": 100}}
        out = []

        def go(inp, sp=spec):
            r = R.run(None, inp, spec=sp, tools=tools)
            out.append((r.mode, [(st["key"], st["state"], st["detail"]) for st in r.steps]))
            return r
        tid = go({"path": self.video}).doc_id
        go({"path": self.video})                                                   # 同じ = 飛ばす
        go({"path": self.video}, dict(spec, transcribe={"quality": "fast"}))       # 設定が違う = 飛ばして印
        go({"docId": tid})                                                         # パックを作る(鍵を書く)
        go({"docId": tid})                                                         # 同じ = 飛ばす
        go({"docId": tid}, dict(spec, pack={"volume": 100, "wrapChars": {"vertical": 6}}))   # 設定が違う = 作り直す
        r = go({"path": self.video, "force": True})                                # force = 作り直す(新しい文書)
        self.assertNotEqual(r.doc_id, tid)
        return out

    def test_keys_skip_and_force(self):
        out = self.sequence(T.LocalTools())
        states = [[x[1] for x in steps] for _mode, steps in out]
        self.assertEqual(states, [["done"], ["skip"], ["skip"], ["skip", "done"], ["skip", "skip"], ["skip", "done"], ["done"]], out)
        self.assertEqual(out[1][1][0][2], "文字起こし済み")
        self.assertEqual(out[2][1][0][2], "文字起こし済み(%s)" % R.TX_DIFFER)
        self.assertIn(R.PACK_DIFFER, out[5][1][1][2])
        self.assertTrue(out[6][1][0][2].startswith("文字起こしし直しました(force)"))

    def test_http_and_local_give_same_public(self):
        """同じ一続きを HttpTools(API の形。中身は LocalTools へつなぐ)で通しても、段の状態と文は同じ"""
        local = self.sequence(T.LocalTools())
        shutil.rmtree(workdata.TX_DIR, True)
        shutil.rmtree(os.path.dirname(self.video) + os.sep + "切り抜き_pack", True)
        http = self.sequence(T.HttpTools(LocalClient(T.LocalTools(), {"post": {"autoLlm": False}})))
        self.assertEqual(http, local)


class LocalClient:
    """HttpTools が呼ぶ「編集」と cut2resolve の API の形を、LocalTools の動詞へつなぐ(同じ段を HTTP の形で通すテスト用)"""

    def __init__(self, lt, spec):
        self.lt, self.bundle = lt, R._spec.merge(spec)

    def call(self, tool, method, path, body=None):
        p, _, q = path.partition("?")
        arg = urllib.parse.unquote(q.split("=", 1)[1]) if q else None
        if p == "/api/transcribe":
            return 200, {"id": self.lt.transcribe_start(body, bundle=self.bundle)}
        if p == "/api/jobs":
            return 200, {"jobs": self.lt.jobs()}
        if p == "/api/transcripts":
            return 200, {"items": [{"id": d["id"], "title": d["title"], "sourceName": d["sourceName"], "videoId": d["videoId"],
                                    "updatedAt": d["updatedAt"], "segments": d["count"]} for d in self.lt.docs()]}
        if p == "/api/transcript":
            f = os.path.join(workdata.TX_DIR, arg + ".json")
            if not os.path.isfile(f):
                return 404, {}
            with open(f, encoding="utf-8") as fh:
                return 200, json.load(fh)
        if p == "/api/edit":
            return self.lt.edit(arg)
        if p == "/api/export-file":
            return 200, self.lt.transcript_file(body["id"])
        if p == "/api/build":
            return self.lt.pack_start(body)
        if p == "/api/job":
            return 200, self.lt.pack_job(arg)
        return 404, {}

    def ok(self, tool, method, path, body=None):
        st, obj = self.call(tool, method, path, body)
        if st != 200:
            raise R.StepError("HTTP %d" % st)
        return obj


if __name__ == "__main__":
    unittest.main()
