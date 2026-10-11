"""src/flow/studiobook.py(スタジオなしの配信の台帳と URL の段の動詞。RS8 の「URL も CLI で」)のテスト。リポジトリ直下で:

    py -3.10 -m unittest src/flow/tests/test_studiobook.py

- 台帳が書く data.json と案件のファイルを、スタジオの Store(③)が同じ形で読める(入口を後から起動したとき画面に出る)
- 初めて書き出したとき案件にする(data.json は索引の行)・ほかの配信の行とコラボのまとまりはそのまま・壊れた data.json には書かない
- LocalStudio の動詞(解析は疑似 = ① の解析を差し替える・ネットワークに出ない)と LocalTools の任せ方
作業データ・書き出し先は一時フォルダ(本物の作業データは読まない・書かない)
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # src
from flow import run as R, studiobook as SB, tools as T  # noqa: E402
from human.review import store as store_mod  # noqa: E402  (台帳の書いた物をスタジオの Store が読めるかを見るだけ。② の本体は ③ を読まない)
from ytt import casefiles as CF, errors, names, studio_env  # noqa: E402

VID = "abcdefghijk"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt_sbook_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "studio")
        self.out = os.path.join(self.tmp, "exports")
        os.makedirs(self.out)
        self.data = os.path.join(self.home, "data.json")
        self.book = SB.StudioBook(self.data, out_dir=lambda: self.out)

    def raw(self):
        with open(self.data, encoding="utf-8") as f:
            return json.load(f)

    def studio(self):
        """スタジオの Store が同じ data.json を読んだ形(書き出し先は台帳と同じ)"""
        with mock.patch.object(studio_env, "get_out_dir", lambda: self.out):
            return store_mod.Store(self.data)

    def analyzed(self):
        """登録 → 解析の反映(自動マーク 3 つ)"""
        self.book.ensure({"kind": "youtube", "videoId": VID, "name": VID}, "題", "ch")
        cands = [{"start": 10, "end": 40, "score": 5, "reasons": ["音量"]}, {"start": 100, "end": 130, "score": 9}, {"start": 200, "end": 230, "score": 1}]
        n = self.book.replace_auto(VID, cands, {"at": 1, "spec": {"count": 3}}, 300.0, {"n": 3, "total": [0, 1, 0]})
        self.assertEqual(n, 3)

    def case_folder(self):
        """書き出しが作る配信のフォルダ(作業用/.studio-id = 持ち主)と切り抜き 1 本"""
        folder = os.path.join(self.out, "題")
        os.makedirs(folder)
        names.write_owner(folder, VID)
        clip = os.path.join(folder, "01_clip.mp4")
        with open(clip, "wb") as f:
            f.write(b"\0")
        return folder, clip


class BookTest(Base):
    def test_ensure_and_analysis_readable_by_studio(self):
        self.analyzed()
        d = self.raw()
        self.assertEqual((d["schema"], list(d["videos"]), d["groups"]), ("clip-studio/v1", [VID], {}))
        v = self.book.get(VID)
        self.assertEqual(([m["src"] for m in v["marks"]], v["duration"], v["rev"]), (["auto"] * 3, 300.0, 2))
        got, series = self.studio().get(VID)
        self.assertEqual((got["title"], got["channel"], len(got["marks"]), got["analysis"]["spec"]), ("題", "ch", 3, {"count": 3}))
        self.assertEqual(series, {"n": 3, "total": [0, 1, 0]}, "盛り上がりのグラフも画面が読む場所に")
        # 題は空で消さない・同じなら版を上げない
        self.assertEqual(self.book.ensure({"kind": "youtube", "videoId": VID}, "", "")["rev"], 2)
        self.assertEqual(self.book.ensure({"kind": "youtube", "videoId": VID}, "新しい題")["rev"], 3)

    def test_adopt_marks_f5(self):
        self.analyzed()
        r = self.book.adopt_marks(VID, [[50, 60]], 2)
        self.assertEqual((len(r["rangeIds"]), len(r["autoIds"]), len(r["added"])), (1, 1, 2))
        marks = {m["id"]: m for m in self.book.get(VID)["marks"]}
        self.assertEqual(marks[r["autoIds"][0]]["start"], 100.0, "点数の高い自動マーク")
        self.assertEqual(marks[r["rangeIds"][0]]["adoptedBy"], "request")
        with self.assertRaises(errors.ApiError):
            self.book.adopt_marks(VID, [], 99)   # 上限の外

    def test_first_export_makes_case(self):
        self.analyzed()
        r = self.book.adopt_marks(VID, [], 1)
        mid = r["autoIds"][0]
        folder, clip = self.case_folder()
        self.assertTrue(self.book.mark_exported(VID, mid, "題/01_clip.mp4", 100.0, 130.0, clip))
        row = self.raw()["videos"][VID]
        self.assertEqual(sorted(row), sorted(CF.INDEX_KEYS + ("case",)), "data.json は索引の行だけ")
        self.assertEqual(os.path.normcase(row["case"]), os.path.normcase(folder))
        self.assertTrue(os.path.isfile(CF.work_path(folder, CF.ADOPTIONS_NAME)) and os.path.isfile(CF.work_path(folder, CF.CANDIDATES_NAME)))
        v = self.book.get(VID)
        got = {m["id"]: m for m in v["marks"]}
        self.assertEqual((got[mid]["status"], got[mid]["path"]), ("exported", clip))
        studio = self.studio()
        sv, _series = studio.get(VID)
        self.assertEqual({m["id"]: m["status"] for m in sv["marks"]}, {m["id"]: m["status"] for m in v["marks"]}, "スタジオの Store も同じマークを読む")
        self.assertEqual(studio.internal(VID)["marks"], [m for m in v["marks"]])
        # 区間が変わった書き出しは結びつけない・2 本目は案件の 採用.json へ
        self.assertFalse(self.book.mark_exported(VID, mid, "題/x.mp4", 0.0, 5.0, clip))
        other = next(m["id"] for m in v["marks"] if m["status"] == "")
        self.book.adopt_marks(VID, [], 2)
        self.assertTrue(self.book.mark_exported(VID, other, "題/02.mp4", *[(m["start"], m["end"]) for m in v["marks"] if m["id"] == other][0]))
        self.assertEqual(self.raw()["videos"][VID]["case"], row["case"])
        self.assertEqual(sum(m["status"] == "exported" for m in self.book.get(VID)["marks"]), 2)

    def test_keeps_other_rows_and_groups(self):
        os.makedirs(self.home)
        other = {"id": "zzzzzzzzzzz", "kind": "youtube", "title": "別", "marks": [], "rev": 4, "extra": "そのまま"}
        with open(self.data, "w", encoding="utf-8") as f:
            json.dump({"schema": "clip-studio/v1", "videos": {other["id"]: other}, "groups": {"g1": {"id": "g1"}}}, f)
        self.analyzed()
        d = self.raw()
        self.assertEqual((d["videos"][other["id"]], d["groups"]), (other, {"g1": {"id": "g1"}}))
        self.assertTrue(os.path.isfile(self.data + ".bak"))

    def test_broken_data_not_written(self):
        os.makedirs(self.home)
        with open(self.data, "w", encoding="utf-8") as f:
            f.write("{壊れた")
        with self.assertRaises(errors.ApiError) as cm:
            self.book.ensure({"kind": "youtube", "videoId": VID})
        self.assertEqual(cm.exception.status, 500)
        self.assertFalse(self.book.has(VID))
        with open(self.data, encoding="utf-8") as f:
            self.assertEqual(f.read(), "{壊れた")


def _fake_run_analyze(job):
    """① の解析の代わり(ネットワーク・ffmpeg に出ない): 候補 2 つ"""
    src = job["spec"]["source"]
    job["result"] = {"source": dict(src, duration=300.0), "series": {"n": 1}, "signals": {}, "counts": {}, "warnings": [], "spec": {"count": 2},
                     "candidates": [{"start": 10, "end": 40, "peak": 20, "score": 3, "parts": {}, "reasons": []},
                                    {"start": 100, "end": 130, "peak": 110, "score": 8, "parts": {}, "reasons": []}]}
    job["state"], job["phase"], job["progress"] = "done", "解析が完了しました", 1.0


class LocalStudioTest(Base):
    def setUp(self):
        super().setUp()
        for p in (mock.patch.dict(os.environ, {"STUDIO_FAKE": "1"}), mock.patch.object(SB._batch.analyze, "run_analyze", _fake_run_analyze)):
            p.start()
            self.addCleanup(p.stop)
        self.ls = SB.LocalStudio(self.book)
        self.addCleanup(self.ls.close, 1.0)

    def wait_analysis(self, qid):
        deadline = time.time() + 20
        while time.time() < deadline:
            it = next(i for i in self.ls.analyze_items() if i["qid"] == qid)
            if it["status"] not in ("waiting", "running"):
                return it
            time.sleep(0.02)
        self.fail("解析が終わらない")

    def test_verbs(self):
        self.assertEqual(self.ls.video(VID)[0], 404)
        res = self.ls.analyze_add({"kind": "youtube", "videoId": VID, "title": "題"}, {})
        it = self.wait_analysis(res["added"][0]["qid"])
        self.assertEqual((it["status"], it["marks"]), ("done", 2))
        st, obj = self.ls.video(VID)
        self.assertEqual((st, obj["video"]["title"], len(obj["video"]["marks"])), (200, "題", 2))
        r = self.ls.request_marks({"id": VID, "ranges": [], "top": 1})
        self.assertEqual(len(r["autoIds"]), 1)
        with self.assertRaises(R.StepError):
            self.ls.request_marks({"id": "x", "ranges": [], "top": 1})   # YouTube の ID の形でない
        st, obj = self.ls.export_start({"id": VID, "markIds": []})
        self.assertEqual((st, obj["error"]), (400, "bad_request"))
        with self.assertRaises(R.StepError):
            self.ls.export_job("none")
        self.ls.export_cancel("none")
        self.ls.analyze_cancel("none")

    def test_request_marks_registers(self):
        """解析なし(区間だけ)の採用でも配信を登録する(スタジオの /api/video/request-marks と同じ)"""
        r = self.ls.request_marks({"id": VID, "ranges": [[5, 15]], "top": 1, "title": "題"})
        self.assertEqual((len(r["rangeIds"]), r["video"]["title"]), (1, "題"))
        self.assertTrue(self.book.has(VID))


class LocalToolsTest(Base):
    def test_without_studio_refuses(self):
        t = T.LocalTools()
        for call in (lambda: t.video(VID), lambda: t.analyze_add({}, {}), lambda: t.request_marks({}), lambda: t.export_start({})):
            with self.assertRaises(R.StepError):
                call()
        self.assertEqual(t.studio_video(VID), {})
        t.analyze_cancel("q")
        t.export_cancel("j")

    def test_with_studio_delegates(self):
        t = T.LocalTools(studio=SB.LocalStudio(self.book))
        self.addCleanup(t.studio.close, 1.0)
        self.assertEqual(t.video(VID)[0], 404)
        t.request_marks({"id": VID, "ranges": [[5, 15]], "top": 1})
        self.assertEqual(t.studio_video(VID)["id"], VID)
        self.assertEqual(len(t.video(VID)[1]["video"]["marks"]), 1)


if __name__ == "__main__":
    unittest.main()
