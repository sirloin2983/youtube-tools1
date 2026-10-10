# -*- coding: utf-8 -*-
"""flow/live_adopt(ライブの採用 = マーク + 書き出し。役割で組み直す RS7-2 G1b)のテスト。  py -3.10 -m unittest src/flow/tests/test_live_adopt.py -v

- スタジオなし(LocalMarks): 偽の親(Live を使わない・studio_call を持たない)で、採用 → マークの正本の採用の印 → 書き出しのジョブ →
  (書き出しが済んだ所から).clip.json → まとめて実行へ渡す → 印が「書き出し済み」まで。採用の id・ジョブ・.clip.json の形はスタジオのとき(StudioMarks)と同じ
- 親には「口(livehost.AdoptHost・ExportHost)に並べた名前だけを通す」包みを渡す = 口と実際の使い方がずれない
- スタジオのとき(StudioMarks = 今のユーザーの PC)は src/home/tests/test_live.py の test_adopt_server_side などが縛る
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない(一時フォルダだけ)
import json
import shutil
import sys
import tempfile
import unittest

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> flow -> src
sys.path.insert(0, SRC)
from flow import live_adopt as LA, live_export as LX, livehost as H, spec as S  # noqa: E402
from ytt import schemas  # noqa: E402

VID = "abcdefghijk"
REC = "20261011-200000-" + VID
URL = "https://www.youtube.com/watch?v=" + VID
FIRST = 1790000000.0   # 録画の頭(最初のセグメントの受信時刻)


class Strict:
    """口(Protocol)に並べた名前だけを親から通す(口に無い名前は落として bad に残す。OPTIONAL は黙って無いことにする)"""

    def __init__(self, proto, target, optional=()):
        object.__setattr__(self, "_ok", set(H.names(proto)))
        object.__setattr__(self, "_opt", set(optional))
        object.__setattr__(self, "_t", target)
        object.__setattr__(self, "bad", [])

    def __getattr__(self, name):
        if name not in self._ok:
            if name not in self._opt:
                self.bad.append(name)
            raise AttributeError("口に無い名前: %s" % name)
        return getattr(self._t, name)


class Book:
    """友人の依頼の結びつき(live_requests.Store の形だけ)"""

    def __init__(self):
        self.items = {}

    def get(self, rc, rec):
        return self.items.get("%s/%s" % (rc, rec))

    def all(self):
        return dict(self.items)


class Runner:
    """まとめて実行の代わり(start_file だけ)"""

    def __init__(self):
        self.files = []

    def start_file(self, media, title=None, streamer=None, flow=None, **kw):
        self.files.append((media, flow, kw))
        return {"id": "run-%d" % len(self.files)}


class Host:
    """スタジオなしの親(友人の PC・headless の代わり)。studio_call を持たない"""

    def __init__(self, tmp):
        self.logs = []
        self.log = self.logs.append
        self.requests = Book()
        self.runner = Runner()
        self.ex_view = Strict(H.ExportHost, self, H.OPTIONAL["Exporter"])
        self.exporter = LX.Exporter(self.ex_view, os.path.join(tmp, "live"), lambda: os.path.join(tmp, "out"), runner=lambda: self.runner, log=self.log,
                                    disk_usage=lambda p: (100 * LX.GB, 200 * LX.GB), exported=lambda job, media, archived=False: self.marks.exported(job, media, archived))
        self.exporter.start = lambda: None   # 書き出しは動かさない(ジョブは「録画待ち」のまま。済んだ所はテストが _finish を呼ぶ)
        self.marks = LA.LocalMarks(lambda: self.exporter)

    def auto_cfg(self):
        return {"after": "check", "cut": "", "engine": "", "model": "", "pad": 2.0}

    def recorders(self, cfg=None):
        return [{"id": "fake", "name": "偽物", "url": "http://127.0.0.1:9", "token": "t"}]

    def find(self, rid):
        return next((r for r in self.recorders() if r["id"] == rid), None)

    def call(self, rc, method, path, body=None, timeout=3.0):
        return None, {"message": "このテストは録画元に繋がない"}

    def request(self, rc, method, path, body=None, timeout=10.0):
        raise OSError("このテストはセグメントを取らない")

    def _ids(self, rc_id, rec):
        if not schemas.ids_ok(rc_id, rec):
            raise LX.LiveError("録画元か録画の指定が正しくありません")
        rc = self.find(rc_id)
        if rc is None:
            raise LX.LiveError("その録画元はありません", 404)
        return rc

    def _rec_status(self, rc, rc_id, rec):
        return {"url": URL, "title": "テスト配信", "firstPdt": LX.epoch_iso(FIRST), "lastPdt": LX.epoch_iso(FIRST + 600)}, FIRST


def feedback(tmp):
    with open(os.path.join(tmp, "live", LX.FEEDBACK), encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


class LocalMarksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-live-adopt-")
        self.host = Host(self.tmp)
        self.view = Strict(H.AdoptHost, self.host)
        self.ad = LA.Adopter(self.view)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def no_strays(self):
        self.assertEqual((self.view.bad, self.host.ex_view.bad), ([], []))

    def test_adopt_to_export_without_studio(self):
        h, ex = self.host, self.host.exporter
        res = self.ad.adopt({"recorder": "fake", "recording": REC, "start": 100.0, "end": 130.0, "origin": "auto", "after": "auto", "score": 9.5, "text": "ここ"})
        key = res["mark"]
        self.assertRegex(key, r"^a[0-9a-f]{12}\Z")
        self.assertEqual((res["video"], res["origin"], res["existing"]), (REC, "auto", False))   # 配信の id = 録画の id(スタジオの kind live と同じ)
        j = res["job"]
        self.assertEqual((j["markId"], j["n"], j["after"], j["origin"], j["score"], j["state"]), (LX.studio_mark_id(key), 1, "auto", "auto", 9.5, "wait"))
        self.assertEqual(j["studio"], {"video": REC, "mark": key, "start": 98.0, "end": 132.0})   # 自動の採用は前後に余白 2 秒(M8)
        self.assertEqual((j["start"], j["end"]), (LX.epoch_iso(FIRST + 98), LX.epoch_iso(FIRST + 132)))
        d = ex.marks.load("fake", REC)
        self.assertEqual((d["url"], d["title"]), (URL, "テスト配信"))
        self.assertEqual([(m["id"], m["key"], m["status"], m["src"], m["sec"], m["n"]) for m in d["marks"]],
                         [(LX.studio_mark_id(key), key, "adopted", "local", [98.0, 132.0], 1)])   # 採用の印
        fb = feedback(self.tmp)
        self.assertEqual([(x["event"], x["origin"], x["human"], x["verdict"], x["studio"], x["text"]) for x in fb],
                         [("adopt", "auto", False, None, {"video": REC, "mark": key}, "ここ")])
        # 同じ区間 ±0.5 秒をもう一度 → 書き出しの途中なので新しく作らない(印も増やさない)
        again = self.ad.adopt({"recorder": "fake", "recording": REC, "start": 100.3, "end": 129.8, "origin": "auto"})
        self.assertEqual((again["existing"], again["job"]["id"], again["mark"], len(ex.marks.load("fake", REC)["marks"])), (True, j["id"], key, 1))
        # 前に人のマーク: 余白なし・番号は開始の順(スタジオと同じ決まり)・人は「良い」
        m2 = self.ad.adopt({"recorder": "fake", "recording": REC, "start": LX.epoch_iso(FIRST + 10), "end": 20.0, "label": "前", "after": "none"})
        self.assertEqual((m2["origin"], m2["job"]["n"], m2["job"]["after"], m2["job"]["studio"]["start"], m2["job"]["label"]), ("manual", 1, "none", 10.0, "前"))
        self.assertEqual(feedback(self.tmp)[-1]["verdict"], "good")
        # 書き出しが済んだ所から(録画元に繋がないので _finish を直に)= .clip.json・まとめて実行・印を「書き出し済み」に
        job = next(x for x in ex.jobs if x["id"] == j["id"])
        media = os.path.join(self.tmp, "out", "テスト配信", "01_00h01m38s-00h02m12s.mp4")
        os.makedirs(os.path.dirname(media))
        open(media, "wb").close()
        ex._finish(job, h.find("fake"), REC, {"url": URL, "firstPdt": LX.epoch_iso(FIRST)}, {"path": media, "title": "テスト配信", "duration": 34.0},
                   FIRST + 98, FIRST + 132)
        self.assertEqual((job["state"], job["runId"], job["warning"]), ("done", "run-1", ""))
        self.assertEqual(h.runner.files, [(media, "auto", {})])
        clip, _w = schemas.load_clip_file(schemas.find_clip_path(media))
        live = clip["source"]["live"]
        self.assertEqual((live["studio"], live["origin"], live["score"], live["markId"], clip["mark"]["src"], clip["range"]),
                         ({"video": REC, "mark": key}, "auto", 9.5, LX.studio_mark_id(key), "auto", {"start": 98.0, "end": 132.0}))
        mk = ex.marks.get("fake", REC, LX.studio_mark_id(key))
        self.assertEqual((mk["status"], mk["path"]), ("exported", media))
        # 済んだ区間をもう一度 → 作らない
        third = self.ad.adopt({"recorder": "fake", "recording": REC, "start": 100.0, "end": 130.0, "origin": "auto"})
        self.assertEqual((third["existing"], third["job"]["id"]), (True, j["id"]))
        self.assertEqual(sum(1 for x in ex.jobs if x["markId"] == LX.studio_mark_id(key)), 1)
        self.no_strays()

    def test_request_and_bad_input(self):
        """友人の依頼の録画は after auto・余白は依頼の設定(2-15)。区間・録画元の検査は今と同じ文"""
        self.host.requests.items["fake/" + REC] = {"rid": "r-1", "deliverDir": "", "streamer": "", "settings": {"pad": 0, "afterStream": False}}
        res = self.ad.adopt({"recorder": "fake", "recording": REC, "start": 50.0, "end": 60.0, "origin": "auto"})
        self.assertEqual((res["job"]["after"], res["job"]["studio"]["start"], res["job"]["request"]["rid"]), ("auto", 50.0, "r-1"))
        self.assertEqual(self.ad.request_for("fake", REC, "archive", "check", "x"), (None, "check", "x"))   # 依頼が配信後の追加を要らないと言う
        self.assertEqual(self.ad.request_for("fake", "20261011-200001-" + VID, "auto", "check", ""), (None, "check", ""))   # 届ける hook が無い = 届けない
        for bad in ({"start": 5.0, "end": 5.2}, {"start": -1, "end": 3}, {"start": "きのう", "end": 3}, {"recording": "../x"}, {"origin": "robot"}):
            with self.assertRaises(LX.LiveError, msg=repr(bad)):
                self.ad.adopt(dict({"recorder": "fake", "recording": REC, "start": 10.0, "end": 12.0}, **bad))
        with self.assertRaises(LX.LiveError) as cm:
            self.ad.adopt({"recorder": "nope", "recording": REC, "start": 10.0, "end": 12.0})
        self.assertEqual(cm.exception.code, 404)
        self.no_strays()

    def test_top_of(self):
        """友人の PC の上限 = 束の adopt.top(親の auto_max が返す)。無い・形が違えば束の既定"""
        self.assertEqual(LA.top_of({"adopt": {"top": 7}}), 7)
        for bad in (None, {}, {"adopt": None}, {"adopt": {"top": 0}}, {"adopt": {"top": "10"}}, {"adopt": {"top": True}}):
            self.assertEqual(LA.top_of(bad), S.DEFAULTS["adopt"]["top"], repr(bad))


if __name__ == "__main__":
    unittest.main()
