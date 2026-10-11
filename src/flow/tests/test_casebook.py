"""src/flow/casebook.py(案件の候補と採用のファイル。RS8 B3-3)のテスト。リポジトリ直下で:

    py -3.10 -m unittest src/flow/tests/test_casebook.py

案件のフォルダは一時フォルダに作る(本物の作業データは読まない・書かない)。
"""
import copy
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # src
from flow import casebook as CB  # noqa: E402
from ytt import errors, marks as M, names, schemas  # noqa: E402

VID = "vidAAAAAAAA"
REC = "20261011-120000"


def mark(mid, s, e, **kw):
    """保存済みの形のマーク(ytt/marks.build_mark を通す = Store が読み込んだ形)"""
    d = {"id": mid, "start": s, "end": e, "label": "", "src": "manual", "status": "", "createdAt": 1700000000000}
    d.update(kw)
    return M.build_mark(d, None, True)


def auto(mid, s, e, **kw):
    kw.setdefault("auto0", [s, e])
    kw.setdefault("score", 3.0)
    return mark(mid, s, e, src="auto", **kw)


def video(marks, vid=VID, **kw):
    v = {"id": vid, "kind": "youtube", "title": "題", "channel": "ch", "duration": 3600.0, "fileName": "", "path": "", "marks": marks,
         "analysis": {"at": 1, "spec": {"count": 8}}, "rev": 3, "createdAt": 1700000000000, "updatedAt": 1700000000500}
    v.update(kw)
    return v


def through_json(docs):
    c, a = docs
    return CB.parse_candidates(json.loads(json.dumps(c, ensure_ascii=False))), CB.parse_adoptions(json.loads(json.dumps(a, ensure_ascii=False)))


class SplitMergeTest(unittest.TestCase):
    def sample(self):
        return video([auto("a1", 10, 40), mark("m1", 50, 80, status="adopted"), auto("a2", 100, 130, status="rejected"),
                      auto("a3", 200, 230, label="名前"), auto("a4", 300, 330)])

    def test_split_border_is_touched(self):
        c, a = CB.split(self.sample())
        self.assertEqual(c["schema"], CB.CANDIDATES_SCHEMA)
        self.assertEqual(a["schema"], CB.ADOPTIONS_SCHEMA)
        self.assertEqual([m["id"] for m in c["sources"][VID]["auto"]], ["a1", "a4"])
        self.assertEqual([m["id"] for m in a["marks"]], ["m1", "a2", "a3"])
        self.assertTrue(all(m["source"] == VID for m in a["marks"]))
        self.assertEqual(c["sources"][VID]["duration"], 3600.0)
        self.assertEqual(c["sources"][VID]["analysis"], {"at": 1, "spec": {"count": 8}})
        self.assertNotIn("marks", a["sources"][VID])
        self.assertNotIn("analysis", a["sources"][VID])
        self.assertNotIn("order", a["sources"][VID])   # 時刻の順なら並びは持たない

    def test_round_trip(self):
        v = self.sample()
        self.assertEqual(CB.merge(*through_json(CB.split(v)), VID), v)

    def test_round_trip_keeps_unsorted_order(self):
        v = video([mark("m2", 500, 520), auto("a1", 10, 40), mark("m1", 50, 80, status="adopted")])
        c, a = CB.split(v)
        self.assertEqual(a["sources"][VID]["order"], ["m2", "a1", "m1"])
        self.assertEqual(CB.merge(*through_json((c, a)), VID), v)

    def test_round_trip_live(self):
        live = {"recorder": "rec1", "recording": REC, "url": "https://www.youtube.com/watch?v=" + VID, "videoId": VID}
        v = video([mark("m1", 5, 30, status="adopted", live=True)], vid=REC, kind="live", live=live, analysis=None, duration=0.0)
        self.assertEqual(CB.merge(*through_json(CB.split(v)), REC), v)

    def test_hidden_candidate_stays_on_adoption_side(self):
        """手つかずの自動マークが別のマークと same で重なっている(コラボ転写・手で足した)= 候補の側に置くと隠れるので採用の側に残す"""
        v = video([mark("m1", 10, 40, status="adopted"), auto("a1", 10.3, 40.2), auto("a2", 100, 130)])
        c, a = CB.split(v)
        self.assertEqual([m["id"] for m in c["sources"][VID]["auto"]], ["a2"])
        self.assertIn("a1", [m["id"] for m in a["marks"]])
        self.assertEqual(CB.merge(*through_json((c, a)), VID), v)

    def test_merge_hides_same_and_same_id(self):
        c = {"schema": CB.CANDIDATES_SCHEMA, "sources": {VID: {"analysis": None, "duration": 100.0,
                                                              "auto": [auto("a1", 10, 40), auto("a2", 50, 60), auto("a3", 70, 80)]}}}
        a = CB.empty_adoptions()
        a["sources"][VID] = {"kind": "youtube", "title": "", "channel": "", "fileName": "", "path": "", "rev": 1, "createdAt": 1, "updatedAt": 1}
        a["marks"] = [dict(mark("m1", 10.4, 39.6, status="adopted"), source=VID), dict(auto("a2", 52, 62, label="動かした"), source=VID)]
        v = CB.merge(c, a, VID)
        self.assertEqual([m["id"] for m in v["marks"]], ["m1", "a2", "a3"])   # a1 は same・a2 は同じ id で採用の側が出る
        self.assertEqual(v["marks"][1]["start"], 52)
        self.assertIsNone(CB.merge(c, a, "otherAAAAAA"))

    def test_merge_without_candidates(self):
        a = CB.split(self.sample())[1]
        v = CB.merge(None, a, VID)
        self.assertEqual([m["id"] for m in v["marks"]], ["m1", "a2", "a3"])
        self.assertEqual(v["duration"], 0.0)
        self.assertIsNone(v["analysis"])

    def test_two_sources(self):
        live = {"recorder": "rec1", "recording": REC, "url": "https://www.youtube.com/watch?v=" + VID, "videoId": VID}
        v1 = video([mark("m1", 5, 30, status="exported", file="f/01.mp4")], vid=REC, kind="live", live=live, analysis=None)
        v2 = video([auto("a1", 10, 40), mark("m9", 60, 90, status="adopted")])
        docs = CB.split(v1)
        docs = CB.split(v2, prev=docs)
        c, a = through_json(docs)
        self.assertEqual(set(a["sources"]), {REC, VID})
        self.assertEqual(CB.merge(c, a, REC), v1)
        self.assertEqual(CB.merge(c, a, VID), v2)
        # 片方を分け直しても、もう片方はそのまま
        v2b = copy.deepcopy(v2)
        v2b["marks"][1]["status"] = "rejected"
        c2, a2 = through_json(CB.split(v2b, prev=(c, a)))
        self.assertEqual(CB.merge(c2, a2, REC), v1)
        self.assertEqual(CB.merge(c2, a2, VID), v2b)
        self.assertEqual(sum(1 for m in a2["marks"] if m["source"] == VID), 1)


class RejectedTest(unittest.TestCase):
    def base(self):
        return video([auto("a1", 100, 140), auto("a2", 300, 340), mark("m1", 500, 520, status="adopted")])

    def test_deleted_candidate_gets_a_mark_and_stays_hidden(self):
        v = self.base()
        docs = through_json(CB.split(v))
        v2 = copy.deepcopy(v)
        v2["marks"] = [m for m in v2["marks"] if m["id"] != "a1"]   # 人が候補のまま消した
        c2, a2 = CB.split(v2, prev=docs, keep_candidates=True, at=1800000000000)
        self.assertEqual(c2, docs[0])   # ① の候補は書き換えない
        self.assertEqual(a2["rejected"], [{"source": VID, "id": "a1", "start": 100.0, "end": 140.0, "at": 1800000000000}])
        self.assertEqual(CB.merge(*through_json((c2, a2)), VID), v2)
        # 再解析で時刻が少しずれた(id も新しい)候補にも当たる
        c3 = copy.deepcopy(c2)
        c3["sources"][VID]["auto"] = [auto("b1", 102.5, 143), auto("b2", 300, 340), auto("b3", 700, 720)]
        shown = [m["id"] for m in CB.merge(c3, a2, VID)["marks"]]
        self.assertEqual(shown, ["b2", "m1", "b3"])
        # 離れすぎ(±5 秒を超える)なら当たらない
        c3["sources"][VID]["auto"] = [auto("b1", 106, 146)]
        self.assertIn("b1", [m["id"] for m in CB.merge(c3, a2, VID)["marks"]])

    def test_keep_candidates_without_change_adds_nothing(self):
        v = self.base()
        docs = through_json(CB.split(v))
        c2, a2 = CB.split(v, prev=docs, keep_candidates=True)
        self.assertEqual(a2["rejected"], [])
        self.assertEqual(CB.merge(c2, a2, VID), v)

    def test_marks_carry_over_on_reanalysis_split(self):
        """候補を作り直す split(keep_candidates なし)でも、前の消した印は残る。印に当たる新しい候補は採用の側に残して往復は崩さない"""
        v = self.base()
        docs = through_json(CB.split(v))
        v2 = copy.deepcopy(v)
        v2["marks"] = [m for m in v2["marks"] if m["id"] != "a1"]
        docs2 = CB.split(v2, prev=docs, keep_candidates=True)
        v3 = video([auto("b1", 101, 141), mark("m1", 500, 520, status="adopted")])   # 再解析の後の画面(まだ b1 が出ている形)
        c3, a3 = CB.split(v3, prev=docs2)
        self.assertEqual(len(a3["rejected"]), 1)
        self.assertEqual(CB.merge(*through_json((c3, a3)), VID), v3)


class PathTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="casebook-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.out = os.path.join(self.tmp, "out")
        self.root = os.path.join(self.out, "題")
        os.makedirs(os.path.join(self.root, schemas.WORK_DIR))
        names.write_owner(self.root, VID)

    def exported(self, mid, s, e, path):
        return mark(mid, s, e, status="exported", file="題/" + os.path.basename(path), path=path)

    def test_paths_are_relative_in_the_file(self):
        inside = os.path.join(self.root, "01_x.mp4")
        outside = os.path.join(self.tmp, "elsewhere", "02_y.mp4")
        v = video([self.exported("m1", 10, 40, inside), self.exported("m2", 50, 80, outside)])
        c, a = CB.split(v, self.root)
        got = {m["id"]: m["path"] for m in a["marks"]}
        self.assertEqual(got["m1"], "01_x.mp4")
        self.assertEqual(got["m2"], outside)   # 根の外は絶対のまま
        self.assertEqual(CB.merge(*through_json((c, a)), VID, self.root), v)
        # 案件のフォルダごと動かしても、新しい根で絶対パスに戻る
        moved = os.path.join(self.tmp, "moved")
        self.assertEqual(CB.merge(c, a, VID, moved)["marks"][0]["path"], os.path.join(moved, "01_x.mp4"))

    def test_file_video_path(self):
        src = os.path.join(self.root, "元.mp4")
        v = video([], kind="file", fileName="元.mp4", path=src)
        c, a = CB.split(v, self.root)
        self.assertEqual(a["sources"][VID]["path"], "元.mp4")
        self.assertEqual(CB.merge(c, a, VID, self.root), v)

    def test_path_escaping_root_is_dropped(self):
        a = CB.split(video([self.exported("m1", 10, 40, os.path.join(self.root, "01.mp4"))]), self.root)[1]
        a["marks"][0]["path"] = "../../evil.mp4"
        self.assertNotIn("path", CB.merge(None, a, VID, self.root)["marks"][0])

    def test_case_of(self):
        inside = os.path.join(self.root, "01_x.mp4")
        v = video([self.exported("m1", 10, 40, inside), mark("m2", 50, 80)])
        with mock.patch.object(CB._fsio, "is_fixed_drive", return_value=True):
            self.assertEqual(CB.case_of(v, self.out), os.path.normpath(self.root))
            # 書き出したマークが 作業用 の中を指していても案件の根
            v2 = video([self.exported("m1", 10, 40, os.path.join(self.root, schemas.WORK_DIR, "x_edit.mp4"))])
            self.assertEqual(CB.case_of(v2, self.out), os.path.normpath(self.root))
            self.assertIsNone(CB.case_of(video([mark("m2", 50, 80)]), self.out))     # 書き出していない = 引かない(題で探さない)
            self.assertIsNone(CB.case_of(video(v["marks"], vid="otherAAAAAA"), self.out))   # 持ち主が違う
            self.assertIsNone(CB.case_of(v, os.path.join(self.tmp, "other-out")))    # 書き出し先の下でない
            self.assertIsNone(CB.case_of(v, self.root))                              # 案件の根そのものを書き出し先にしても案件にしない(下だけ)
            # 2 つのフォルダに分かれていれば決めない
            root2 = os.path.join(self.out, "題_2")
            names.write_owner(root2, VID)
            v3 = video([self.exported("m1", 10, 40, inside), self.exported("m3", 90, 99, os.path.join(root2, "03.mp4"))])
            self.assertIsNone(CB.case_of(v3, self.out))
        with mock.patch.object(CB._fsio, "is_fixed_drive", return_value=False):
            self.assertIsNone(CB.case_of(v, self.out))   # 固定ディスクでない
        self.assertIsNone(CB.case_of(v, "//server/share/out"))   # ネットワーク上

    def test_case_of_live_owner(self):
        names.write_owner(self.root, "live-" + REC)
        live = {"recorder": "rec1", "recording": REC, "url": "https://www.youtube.com/@ch/live", "videoId": ""}
        v = video([self.exported("m1", 10, 40, os.path.join(self.root, "01.mp4"))], vid=REC, kind="live", live=live)
        with mock.patch.object(CB._fsio, "is_fixed_drive", return_value=True):
            self.assertEqual(CB.case_of(v, self.out), os.path.normpath(self.root))


class ReadWriteTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="casebook-rw-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.v = video([auto("a1", 10, 40), mark("m1", 50, 80, status="adopted")])

    def path(self, name):
        return CB.work_path(self.root, name)

    def test_empty_when_missing(self):
        c, a = CB.read(self.root)
        self.assertEqual(c, CB.empty_candidates())
        self.assertEqual(a, CB.empty_adoptions())

    def test_write_then_read(self):
        c, a = CB.split(self.v, self.root)
        CB.write(self.root, c, a)
        self.assertTrue(os.path.isfile(self.path(CB.CANDIDATES_NAME)))
        self.assertFalse(os.path.exists(self.path(CB.ADOPTIONS_NAME) + ".bak"))   # 初めては控えなし
        self.assertEqual(CB.merge(*CB.read(self.root), VID, self.root), self.v)
        a2 = copy.deepcopy(a)
        a2["memo"] = "メモ"
        CB.write(self.root, adoptions=a2)
        with open(self.path(CB.ADOPTIONS_NAME) + ".bak", encoding="utf-8") as f:
            self.assertEqual(json.load(f)["memo"], "")   # 1 つ前の世代
        self.assertEqual(CB.read(self.root)[1]["memo"], "メモ")

    def test_write_order_adoptions_first(self):
        seen = []
        real = CB._fsio.write_json
        with mock.patch.object(CB._fsio, "write_json", side_effect=lambda p, *x, **k: (seen.append(os.path.basename(p)), real(p, *x, **k))):
            CB.write(self.root, *CB.split(self.v))
        self.assertEqual(seen, [CB.ADOPTIONS_NAME, CB.CANDIDATES_NAME])

    def test_bad_schema(self):
        with self.assertRaises(ValueError):
            CB.write(self.root, adoptions={"schema": "x"})

    def test_broken_candidates_read_as_empty(self):
        CB.write(self.root, *CB.split(self.v))
        with open(self.path(CB.CANDIDATES_NAME), "w", encoding="utf-8") as f:
            f.write("{壊れた")
        c, a = CB.read(self.root)
        self.assertEqual(c, CB.empty_candidates())
        self.assertEqual([m["id"] for m in CB.merge(c, a, VID)["marks"]], ["m1"])

    def test_broken_adoptions_uses_bak_and_keeps_it(self):
        c, a = CB.split(self.v)
        CB.write(self.root, c, a)
        CB.write(self.root, adoptions=a)   # .bak ができる
        with open(self.path(CB.ADOPTIONS_NAME), "w", encoding="utf-8") as f:
            f.write("{壊れた")
        got = CB.read(self.root)[1]
        self.assertEqual([m["id"] for m in got["marks"]], ["m1"])
        # 壊れた物の上から書いても .bak は壊れた物で上書きしない(退ける)
        a2 = copy.deepcopy(a)
        a2["memo"] = "新"
        CB.write(self.root, adoptions=a2)
        wd = os.path.join(self.root, schemas.WORK_DIR)
        self.assertTrue(any(n.startswith(CB.ADOPTIONS_NAME + ".broken-") for n in os.listdir(wd)))
        with open(self.path(CB.ADOPTIONS_NAME) + ".bak", encoding="utf-8") as f:
            self.assertIsNotNone(CB.parse_adoptions(json.load(f)))

    def test_broken_adoptions_without_bak_refuses(self):
        os.makedirs(os.path.join(self.root, schemas.WORK_DIR))
        with open(self.path(CB.ADOPTIONS_NAME), "w", encoding="utf-8") as f:
            f.write("[]")
        with self.assertRaises(errors.ApiError) as cm:
            CB.read(self.root)
        self.assertEqual((cm.exception.code, cm.exception.status), (CB.BROKEN_CODE, 500))

    def test_parse_skips_broken_marks(self):
        c, a = CB.split(self.v)
        a["marks"].append({"id": "bad id!", "start": 1, "end": 2, "source": VID})
        a["marks"].append(dict(mark("z1", 1, 2), source="unknownAAAA"))   # sources にない配信
        a["rejected"] = [{"source": VID, "id": "a9", "start": 5, "end": 1}, "x"]
        got = CB.parse_adoptions(json.loads(json.dumps(a)))
        self.assertEqual([m["id"] for m in got["marks"]], ["m1"])
        self.assertEqual(got["rejected"], [])
        self.assertIsNone(CB.parse_adoptions({"schema": "x"}))
        self.assertIsNone(CB.parse_candidates({"schema": CB.CANDIDATES_SCHEMA, "sources": []}))

    def test_unseen_root(self):
        gone = os.path.join(self.root, "消えた")
        for call in (lambda: CB.read(gone), lambda: CB.write(gone, *CB.split(self.v)), lambda: CB.read("//server/share/x"),
                     lambda: CB.read("relative/x")):
            with self.assertRaises(errors.ApiError) as cm:
                call()
            self.assertEqual((cm.exception.code, cm.exception.status), (CB.UNSEEN_CODE, 503))
            self.assertIn("reason", cm.exception.extra)
        self.assertFalse(os.path.exists(gone))   # 見えない置き場所にフォルダを作らない

    def test_write_failure_is_api_error(self):
        with mock.patch.object(CB._fsio, "write_json", side_effect=OSError("disk full")):
            with self.assertRaises(errors.ApiError) as cm:
                CB.write(self.root, *CB.split(self.v))
        self.assertEqual(cm.exception.status, 500)

    def test_lock_per_path(self):
        self.assertIs(CB.lock(self.root), CB.lock(self.root + os.sep))
        self.assertIsNot(CB.lock(self.root), CB.lock(os.path.join(self.root, "x")))
        # ほかの糸がロックを持っている間は書けない(読み → 書きを 1 つにできる)
        lk, started, done = CB.lock(self.root), threading.Event(), threading.Event()

        def writer():
            started.set()
            CB.write(self.root, *CB.split(self.v))
            done.set()
        with lk:
            t = threading.Thread(target=writer)
            t.start()
            started.wait(5)
            self.assertFalse(done.wait(0.3))
            self.assertFalse(os.path.exists(self.path(CB.ADOPTIONS_NAME)))
        t.join(5)
        self.assertTrue(done.is_set())


if __name__ == "__main__":
    unittest.main()
