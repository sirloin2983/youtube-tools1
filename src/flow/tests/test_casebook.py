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
from ytt import casefiles as CF, errors, studiodata, marks as M, names, schemas  # noqa: E402

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
    return CF.parse_candidates(json.loads(json.dumps(c, ensure_ascii=False))), CF.parse_adoptions(json.loads(json.dumps(a, ensure_ascii=False)))


class SplitMergeTest(unittest.TestCase):
    def sample(self):
        return video([auto("a1", 10, 40), mark("m1", 50, 80, status="adopted"), auto("a2", 100, 130, status="rejected"),
                      auto("a3", 200, 230, label="名前"), auto("a4", 300, 330)])

    def test_split_border_is_touched(self):
        c, a = CB.split(self.sample())
        self.assertEqual(c["schema"], CF.CANDIDATES_SCHEMA)
        self.assertEqual(a["schema"], CF.ADOPTIONS_SCHEMA)
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
        self.assertEqual(CF.merge(*through_json(CB.split(v)), VID), v)

    def test_round_trip_keeps_unsorted_order(self):
        v = video([mark("m2", 500, 520), auto("a1", 10, 40), mark("m1", 50, 80, status="adopted")])
        c, a = CB.split(v)
        self.assertEqual(a["sources"][VID]["order"], ["m2", "a1", "m1"])
        self.assertEqual(CF.merge(*through_json((c, a)), VID), v)

    def test_round_trip_live(self):
        live = {"recorder": "rec1", "recording": REC, "url": "https://www.youtube.com/watch?v=" + VID, "videoId": VID}
        v = video([mark("m1", 5, 30, status="adopted", live=True)], vid=REC, kind="live", live=live, analysis=None, duration=0.0)
        self.assertEqual(CF.merge(*through_json(CB.split(v)), REC), v)

    def test_hidden_candidate_stays_on_adoption_side(self):
        """手つかずの自動マークが別のマークと same で重なっている(コラボ転写・手で足した)= 候補の側に置くと隠れるので採用の側に残す"""
        v = video([mark("m1", 10, 40, status="adopted"), auto("a1", 10.3, 40.2), auto("a2", 100, 130)])
        c, a = CB.split(v)
        self.assertEqual([m["id"] for m in c["sources"][VID]["auto"]], ["a2"])
        self.assertIn("a1", [m["id"] for m in a["marks"]])
        self.assertEqual(CF.merge(*through_json((c, a)), VID), v)

    def test_merge_hides_same_and_same_id(self):
        c = {"schema": CF.CANDIDATES_SCHEMA, "sources": {VID: {"analysis": None, "duration": 100.0,
                                                              "auto": [auto("a1", 10, 40), auto("a2", 50, 60), auto("a3", 70, 80)]}}}
        a = CF.empty_adoptions()
        a["sources"][VID] = {"kind": "youtube", "title": "", "channel": "", "fileName": "", "path": "", "rev": 1, "createdAt": 1, "updatedAt": 1}
        a["marks"] = [dict(mark("m1", 10.4, 39.6, status="adopted"), source=VID), dict(auto("a2", 52, 62, label="動かした"), source=VID)]
        v = CF.merge(c, a, VID)
        self.assertEqual([m["id"] for m in v["marks"]], ["m1", "a2", "a3"])   # a1 は same・a2 は同じ id で採用の側が出る
        self.assertEqual(v["marks"][1]["start"], 52)
        self.assertIsNone(CF.merge(c, a, "otherAAAAAA"))

    def test_merge_without_candidates(self):
        a = CB.split(self.sample())[1]
        v = CF.merge(None, a, VID)
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
        self.assertEqual(CF.merge(c, a, REC), v1)
        self.assertEqual(CF.merge(c, a, VID), v2)
        # 片方を分け直しても、もう片方はそのまま
        v2b = copy.deepcopy(v2)
        v2b["marks"][1]["status"] = "rejected"
        c2, a2 = through_json(CB.split(v2b, prev=(c, a)))
        self.assertEqual(CF.merge(c2, a2, REC), v1)
        self.assertEqual(CF.merge(c2, a2, VID), v2b)
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
        self.assertEqual(CF.merge(*through_json((c2, a2)), VID), v2)
        # 再解析で時刻が少しずれた(id も新しい)候補にも当たる
        c3 = copy.deepcopy(c2)
        c3["sources"][VID]["auto"] = [auto("b1", 102.5, 143), auto("b2", 300, 340), auto("b3", 700, 720)]
        shown = [m["id"] for m in CF.merge(c3, a2, VID)["marks"]]
        self.assertEqual(shown, ["b2", "m1", "b3"])
        # 離れすぎ(±5 秒を超える)なら当たらない
        c3["sources"][VID]["auto"] = [auto("b1", 106, 146)]
        self.assertIn("b1", [m["id"] for m in CF.merge(c3, a2, VID)["marks"]])

    def test_keep_candidates_without_change_adds_nothing(self):
        v = self.base()
        docs = through_json(CB.split(v))
        c2, a2 = CB.split(v, prev=docs, keep_candidates=True)
        self.assertEqual(a2["rejected"], [])
        self.assertEqual(CF.merge(c2, a2, VID), v)

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
        self.assertEqual(CF.merge(*through_json((c3, a3)), VID), v3)


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
        self.assertEqual(CF.merge(*through_json((c, a)), VID, self.root), v)
        # 案件のフォルダごと動かしても、新しい根で絶対パスに戻る
        moved = os.path.join(self.tmp, "moved")
        self.assertEqual(CF.merge(c, a, VID, moved)["marks"][0]["path"], os.path.join(moved, "01_x.mp4"))

    def test_file_video_path(self):
        src = os.path.join(self.root, "元.mp4")
        v = video([], kind="file", fileName="元.mp4", path=src)
        c, a = CB.split(v, self.root)
        self.assertEqual(a["sources"][VID]["path"], "元.mp4")
        self.assertEqual(CF.merge(c, a, VID, self.root), v)

    def test_path_escaping_root_is_dropped(self):
        a = CB.split(video([self.exported("m1", 10, 40, os.path.join(self.root, "01.mp4"))]), self.root)[1]
        a["marks"][0]["path"] = "../../evil.mp4"
        self.assertNotIn("path", CF.merge(None, a, VID, self.root)["marks"][0])

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
        return CF.work_path(self.root, name)

    def test_empty_when_missing(self):
        c, a = CF.read(self.root)
        self.assertEqual(c, CF.empty_candidates())
        self.assertEqual(a, CF.empty_adoptions())

    def test_write_then_read(self):
        c, a = CB.split(self.v, self.root)
        CB.write(self.root, c, a)
        self.assertTrue(os.path.isfile(self.path(CF.CANDIDATES_NAME)))
        self.assertFalse(os.path.exists(self.path(CF.ADOPTIONS_NAME) + ".bak"))   # 初めては控えなし
        self.assertEqual(CF.merge(*CF.read(self.root), VID, self.root), self.v)
        a2 = copy.deepcopy(a)
        a2["memo"] = "メモ"
        CB.write(self.root, adoptions=a2)
        with open(self.path(CF.ADOPTIONS_NAME) + ".bak", encoding="utf-8") as f:
            self.assertEqual(json.load(f)["memo"], "")   # 1 つ前の世代
        self.assertEqual(CF.read(self.root)[1]["memo"], "メモ")

    def test_write_order_adoptions_first(self):
        seen = []
        real = CB._fsio.write_json
        with mock.patch.object(CB._fsio, "write_json", side_effect=lambda p, *x, **k: (seen.append(os.path.basename(p)), real(p, *x, **k))):
            CB.write(self.root, *CB.split(self.v))
        self.assertEqual(seen, [CF.ADOPTIONS_NAME, CF.CANDIDATES_NAME])

    def test_bad_schema(self):
        with self.assertRaises(ValueError):
            CB.write(self.root, adoptions={"schema": "x"})

    def test_broken_candidates_read_as_empty(self):
        CB.write(self.root, *CB.split(self.v))
        with open(self.path(CF.CANDIDATES_NAME), "w", encoding="utf-8") as f:
            f.write("{壊れた")
        c, a = CF.read(self.root)
        self.assertEqual(c, CF.empty_candidates())
        self.assertEqual([m["id"] for m in CF.merge(c, a, VID)["marks"]], ["m1"])

    def test_broken_adoptions_uses_bak_and_keeps_it(self):
        c, a = CB.split(self.v)
        CB.write(self.root, c, a)
        CB.write(self.root, adoptions=a)   # .bak ができる
        with open(self.path(CF.ADOPTIONS_NAME), "w", encoding="utf-8") as f:
            f.write("{壊れた")
        got = CF.read(self.root)[1]
        self.assertEqual([m["id"] for m in got["marks"]], ["m1"])
        # 壊れた物の上から書いても .bak は壊れた物で上書きしない(退ける)
        a2 = copy.deepcopy(a)
        a2["memo"] = "新"
        CB.write(self.root, adoptions=a2)
        wd = os.path.join(self.root, schemas.WORK_DIR)
        self.assertTrue(any(n.startswith(CF.ADOPTIONS_NAME + ".broken-") for n in os.listdir(wd)))
        with open(self.path(CF.ADOPTIONS_NAME) + ".bak", encoding="utf-8") as f:
            self.assertIsNotNone(CF.parse_adoptions(json.load(f)))

    def test_broken_adoptions_without_bak_refuses(self):
        os.makedirs(os.path.join(self.root, schemas.WORK_DIR))
        with open(self.path(CF.ADOPTIONS_NAME), "w", encoding="utf-8") as f:
            f.write("[]")
        with self.assertRaises(errors.ApiError) as cm:
            CF.read(self.root)
        self.assertEqual((cm.exception.code, cm.exception.status), (CF.BROKEN_CODE, 500))

    def test_parse_skips_broken_marks(self):
        c, a = CB.split(self.v)
        a["marks"].append({"id": "bad id!", "start": 1, "end": 2, "source": VID})
        a["marks"].append(dict(mark("z1", 1, 2), source="unknownAAAA"))   # sources にない配信
        a["rejected"] = [{"source": VID, "id": "a9", "start": 5, "end": 1}, "x"]
        got = CF.parse_adoptions(json.loads(json.dumps(a)))
        self.assertEqual([m["id"] for m in got["marks"]], ["m1"])
        self.assertEqual(got["rejected"], [])
        self.assertIsNone(CF.parse_adoptions({"schema": "x"}))
        self.assertIsNone(CF.parse_candidates({"schema": CF.CANDIDATES_SCHEMA, "sources": []}))

    def test_unseen_root(self):
        gone = os.path.join(self.root, "消えた")
        for call in (lambda: CF.read(gone), lambda: CB.write(gone, *CB.split(self.v)), lambda: CF.read("//server/share/x"),
                     lambda: CF.read("relative/x")):
            with self.assertRaises(errors.ApiError) as cm:
                call()
            self.assertEqual((cm.exception.code, cm.exception.status), (CF.UNSEEN_CODE, 503))
            self.assertIn("reason", cm.exception.extra)
        self.assertFalse(os.path.exists(gone))   # 見えない置き場所にフォルダを作らない

    def test_write_failure_is_api_error(self):
        with mock.patch.object(CB._fsio, "write_json", side_effect=OSError("disk full")):
            with self.assertRaises(errors.ApiError) as cm:
                CB.write(self.root, *CB.split(self.v))
        self.assertEqual(cm.exception.status, 500)

    def test_lock_per_path(self):
        self.assertIs(CF.lock(self.root), CF.lock(self.root + os.sep))
        self.assertIsNot(CF.lock(self.root), CF.lock(os.path.join(self.root, "x")))
        # ほかの糸がロックを持っている間は書けない(読み → 書きを 1 つにできる)
        lk, started, done = CF.lock(self.root), threading.Event(), threading.Event()

        def writer():
            started.set()
            CB.write(self.root, *CB.split(self.v))
            done.set()
        with lk:
            t = threading.Thread(target=writer)
            t.start()
            started.wait(5)
            self.assertFalse(done.wait(0.3))
            self.assertFalse(os.path.exists(self.path(CF.ADOPTIONS_NAME)))
        t.join(5)
        self.assertTrue(done.is_set())


class StudiodataCaseTest(unittest.TestCase):
    """ytt/studiodata の読み口: data.json の行が case を持つ配信は 候補.json・採用.json を重ねて返す(B3-4a)"""
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="casebook-sd-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.v = video([auto("a1", 10, 40), mark("m1", 50, 80, status="adopted")])
        CB.write(self.root, *CB.split(self.v, self.root))
        self.data = os.path.join(self.root, "data.json")

    def put(self, videos):
        with open(self.data, "w", encoding="utf-8") as f:
            json.dump({"schema": "clip-studio/v1", "videos": videos, "groups": {}}, f, ensure_ascii=False)

    def index_row(self, **kw):
        r = {k: self.v[k] for k in ("id", "kind", "title", "channel", "rev", "createdAt", "updatedAt")}
        r["case"] = self.root
        r.update(kw)
        return r

    def test_case_row_is_merged_and_plain_row_untouched(self):
        plain = video([mark("p1", 1, 9)], vid="plainAAAAAA")
        self.put({VID: self.index_row(marks=[mark("zzz", 1, 2)]), "plainAAAAAA": plain})
        got = studiodata.videos(self.data)
        self.assertEqual([m["id"] for m in got[VID]["marks"]], ["a1", "m1"])   # 行の marks は見ない
        self.assertEqual(got[VID]["case"], self.root)
        self.assertEqual(got[VID]["duration"], 3600.0)
        self.assertNotIn("caseUnseen", got[VID])
        self.assertEqual(got["plainAAAAAA"], plain)
        self.assertEqual(studiodata.video(VID, self.data)["rev"], 3)
        self.assertEqual(studiodata.load_all(self.data)["videos"][VID]["marks"], got[VID]["marks"])

    def test_unseen_case(self):
        gone = os.path.join(self.root, "消えた")
        self.put({VID: self.index_row(case=gone)})
        v = studiodata.videos(self.data)[VID]
        self.assertTrue(v["caseUnseen"])
        self.assertEqual(v["marks"], [])
        self.assertEqual(v["title"], "題")   # 一覧の行は出す
        other = video([], vid="otherAAAAAA")   # 採用.json にこの配信が無い
        self.put({"otherAAAAAA": dict(self.index_row(), id="otherAAAAAA")})
        self.assertTrue(studiodata.videos(self.data)["otherAAAAAA"]["caseUnseen"])
        self.assertEqual(other["id"], "otherAAAAAA")

    def test_cached_read_follows_file_changes(self):
        self.put({VID: self.index_row()})
        self.assertEqual(len(studiodata.videos(self.data)[VID]["marks"]), 2)
        v2 = video([auto("a1", 10, 40), mark("m1", 50, 80, status="adopted"), mark("m2", 100, 130, status="adopted")])
        CB.write(self.root, *CB.split(v2, self.root, prev=CF.read(self.root)))
        self.assertEqual(len(studiodata.videos(self.data)[VID]["marks"]), 3)
        calls = []
        real = CF._fsio.read_json_or
        with mock.patch.object(CF._fsio, "read_json_or", side_effect=lambda *a, **k: (calls.append(a[0]), real(*a, **k))[1]):
            studiodata.videos(self.data)
        self.assertEqual([c for c in calls if CF.CANDIDATES_NAME in c or CF.ADOPTIONS_NAME in c], [])   # 変わっていないファイルは読み直さない

    def test_returned_video_is_a_copy(self):
        self.put({VID: self.index_row()})
        studiodata.videos(self.data)[VID]["marks"][0]["label"] = "いじった"
        self.assertEqual(studiodata.videos(self.data)[VID]["marks"][0]["label"], "")


class LiveCaseTest(unittest.TestCase):
    """スタジオなしのライブの録画を案件の 採用.json に持つ(RS8 B3-5。決定 3-37 の (r8j)): 初めて書き出したとき写す・そのあとの採用と書き出し済み・読み"""
    URL = "https://www.youtube.com/watch?v=" + VID

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="casebook-live-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.out = os.path.join(self.tmp, "out")
        self.root = os.path.join(self.out, "配信")
        os.makedirs(os.path.join(self.root, schemas.WORK_DIR))
        names.write_owner(self.root, VID)   # ライブの書き出しの持ち主 = 配信の videoId(flow/live_export の target)
        p = mock.patch.object(CB._fsio, "is_fixed_drive", return_value=True)
        p.start()
        self.addCleanup(p.stop)

    def local(self, key, s, e, status="adopted", path=None):
        """マークの正本のスタジオなしの採用の印(flow/live_export.MarkStore.adopt の形)"""
        m = {"id": "lm-" + key, "key": key, "sec": [s, e], "label": "", "status": status, "src": "local", "start": "x", "end": "y"}
        if path:
            m.update(path=path, file="配信/" + os.path.basename(path))
        return m

    def test_live_mark(self):
        media = os.path.join(self.root, "01.mp4")
        m = CB.live_mark(self.local("a000000000001", 10.04, 40.0, "exported", media))
        self.assertEqual((m["id"], m["start"], m["end"], m["status"], m["src"], m["file"], m["path"]), ("a000000000001", 10.0, 40.0, "exported", "manual", "配信/01.mp4", media))
        self.assertEqual(CB.live_mark(self.local("a000000000002", 10, 40, "exported"))["status"], "adopted")   # 動画の分からない書き出し済みは採用のまま
        for bad in ({"key": "a1", "sec": [1, 2], "status": ""}, {"sec": [1, 2], "status": "adopted"}, {"key": "a1", "sec": [5, 1], "status": "adopted"},
                    {"key": "../x", "sec": [1, 2], "status": "adopted"}, {"key": "a1", "sec": "1-2", "status": "adopted"}, None):
            self.assertIsNone(CB.live_mark(bad), bad)

    def test_into_then_adopt_export_read(self):
        media = os.path.join(self.root, "01.mp4")
        v = CB.live_video("rc1", REC, self.URL, "配信の題", [CB.live_mark(self.local("a000000000001", 10, 40, "exported", media)),
                                                            CB.live_mark(self.local("a000000000002", 100, 130))])
        self.assertEqual(v["live"], {"recorder": "rc1", "recording": REC, "url": self.URL, "videoId": VID})
        self.assertIsNone(CB.live_into(v, os.path.join(self.tmp, "other")))   # 書き出し先の下でない = 案件にしない(正本のまま)
        self.assertEqual(CB.live_into(v, self.out), os.path.normpath(self.root))
        c, a = CF.read(self.root)
        self.assertEqual((list(a["sources"]), [m["id"] for m in a["marks"]], a["marks"][0]["path"]), ([REC], ["a000000000001", "a000000000002"], "01.mp4"))
        self.assertEqual(c["sources"], {})   # 候補.json(① の物)は書かない
        self.assertEqual(CF.merge(c, a, REC, self.root)["title"], "配信の題")
        # 写したあとの採用: 同じ区間 ±0.5 秒は使い回し・新しい区間は足す(番号は開始の順)
        m, n = CB.live_adopt(self.root, REC, 100.3, 129.8, "x", "a000000000009")
        self.assertEqual((m["id"], n), ("a000000000002", 2))
        m, n = CB.live_adopt(self.root, REC, 50.04, 60.0, "ラベル", "a000000000003")
        self.assertEqual((m["id"], m["start"], m["status"], m["label"], n), ("a000000000003", 50.0, "adopted", "ラベル", 2))
        self.assertEqual(CF.merge(*CF.read(self.root), REC, self.root)["rev"], 2)
        # 書き出し済み(本番版の印は同じファイルのあいだ残る・違うファイルで外れる)
        m3 = os.path.join(self.root, "03.mp4")
        self.assertTrue(CB.live_exported(self.root, REC, "a000000000003", "配信/03.mp4", m3, archived=True))
        got = {x["id"]: x for x in CF.merge(*CF.read(self.root), REC, self.root)["marks"]}
        self.assertEqual((got["a000000000003"]["status"], got["a000000000003"]["path"], got["a000000000003"].get("archived")), ("exported", m3, True))
        CB.live_exported(self.root, REC, "a000000000003", "配信/03.mp4", m3)
        self.assertTrue(next(x for x in CF.merge(*CF.read(self.root), REC, self.root)["marks"] if x["id"] == "a000000000003").get("archived"))
        CB.live_exported(self.root, REC, "a000000000003", "配信/04.mp4", os.path.join(self.root, "04.mp4"))
        self.assertNotIn("archived", next(x for x in CF.merge(*CF.read(self.root), REC, self.root)["marks"] if x["id"] == "a000000000003"))
        self.assertFalse(CB.live_exported(self.root, REC, "nope", "x.mp4", m3))
        # 読み(G3)・写ったか(片付け)
        self.assertEqual([(x["id"], x["status"]) for x in CB.live_marks(self.root, REC)],
                         [("a000000000001", "exported"), ("a000000000002", "adopted"), ("a000000000003", "exported")])   # 足した順(スタジオと同じ)
        self.assertTrue(CB.live_has(self.root, REC, ["a000000000001", "a000000000002"]))
        self.assertFalse(CB.live_has(self.root, REC, ["a000000000001", "a00000000000f"]))
        self.assertFalse(CB.live_has(os.path.join(self.tmp, "gone"), REC, ["a000000000001"]))   # 見えない = 写っていない扱い(消さない)
        # 2 回目の live_into(同じ録画): id の同じマークは置き換え・無いマークは足す・題は空のときだけ・ほかのマークは残す
        v2 = CB.live_video("rc1", REC, self.URL, "別の題", [CB.live_mark(self.local("a000000000002", 100, 130, "exported", os.path.join(self.root, "02.mp4"))),
                                                          CB.live_mark(self.local("a000000000004", 200, 230))])
        self.assertEqual(CB.live_into(v2, self.out), os.path.normpath(self.root))
        got = CF.merge(*CF.read(self.root), REC, self.root)
        self.assertEqual(got["title"], "配信の題")
        self.assertEqual({x["id"]: x["status"] for x in got["marks"]},
                         {"a000000000001": "exported", "a000000000002": "exported", "a000000000003": "exported", "a000000000004": "adopted"})

    def test_unseen_and_missing_recording(self):
        for fn in (lambda: CB.live_adopt(self.root, REC, 1, 5, "", "a1"), lambda: CB.live_exported(self.root, REC, "a1", "x", None),
                   lambda: CB.live_marks(self.root, REC)):
            with self.assertRaises(errors.ApiError) as cm:   # 録画が 採用.json に無い = 指し先が切れた(503)
                fn()
            self.assertEqual((cm.exception.code, cm.exception.status), (CF.UNSEEN_CODE, 503))
        with self.assertRaises(errors.ApiError) as cm:
            CB.live_marks(os.path.join(self.tmp, "gone"), REC)
        self.assertEqual(cm.exception.status, 503)

    def test_too_many_marks(self):
        media = os.path.join(self.root, "01.mp4")
        marks = [CB.live_mark(self.local("a%012x" % i, i * 2.0, i * 2.0 + 1, "exported" if i == 0 else "adopted", media if i == 0 else None))
                 for i in range(M.MAX_MARKS)]
        CB.live_into(CB.live_video("rc1", REC, self.URL, "", marks), self.out)
        with self.assertRaises(errors.ApiError) as cm:
            CB.live_adopt(self.root, REC, 5000.0, 5010.0, "", "afffffffffff")
        self.assertEqual(cm.exception.status, 409)


if __name__ == "__main__":
    unittest.main()
