# -*- coding: utf-8 -*-
"""flow/live_adopt(ライブの採用 = マーク + 書き出し。役割で組み直す RS7-2 G1b)のテスト。  py -3.10 -m unittest src/flow/tests/test_live_adopt.py -v

- スタジオなし(LocalMarks): 偽の親(Live を使わない・studio_call を持たない)で、採用 → マークの正本の採用の印 → 書き出しのジョブ →
  (書き出しが済んだ所から).clip.json → まとめて実行へ渡す → 印が「書き出し済み」まで。採用の id・ジョブ・.clip.json の形はスタジオのとき(StudioMarks)と同じ
- 親には「口(livehost.LiveHost)に並べた名前だけを通す」包みを渡す = 口と実際の使い方がずれない
- スタジオのとき(StudioMarks = 今のユーザーの PC)は src/flow/tests/test_live_export.py の test_adopt_server_side などが縛る
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない(一時フォルダだけ)
import json
import shutil
import sys
import tempfile
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> flow -> src
sys.path.insert(0, SRC)
from flow import casebook as CB, live_adopt as LA, live_export as LX, livehost as H, run as R, spec as S  # noqa: E402
from ytt import casefiles as CF, schemas  # noqa: E402

VID = "abcdefghijk"
REC = "20261011-200000-" + VID
URL = "https://www.youtube.com/watch?v=" + VID
FIRST = 1790000000.0   # 録画の頭(最初のセグメントの受信時刻)


class Strict:
    """口 LiveHost に並べた名前だけを親から通す(口に無い名前は落として bad に残す。口にあって親に無い名前は getattr の既定に落ちる)"""

    def __init__(self, target):
        own = vars(H.LiveHost)
        object.__setattr__(self, "_ok", set(own.get("__annotations__", {})) | {k for k, v in own.items() if callable(v) and not k.startswith("__")})
        object.__setattr__(self, "_t", target)
        object.__setattr__(self, "bad", [])

    def __getattr__(self, name):
        if name not in self._ok:
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
    """まとめて実行の代わり(submit だけ)"""

    def __init__(self):
        self.files = []

    def submit(self, env, spec=None, accept=False):
        """② の口(RS7-2 G2b: 書き出しの受け渡しは封筒 kind file + 束)。覚えるのは (動画, flow, 欄) = 以前の start_file の形"""
        run = R.Run.from_envelope(env, spec)
        kw = {k: getattr(run, k) for k in ("cut", "engine", "model") if getattr(run, k)}
        self.files.append((run.source_path, "auto" if run.mode == "file_auto" else "check", kw))
        return {"id": "run-%d" % len(self.files)}


class Host:
    """スタジオなしの親(友人の PC・headless の代わり)。studio_call を持たない"""

    def __init__(self, tmp):
        self.logs = []
        self.log = self.logs.append
        self.requests = Book()
        self.runner = Runner()
        self.ex_view = Strict(self)
        self.exporter = LX.Exporter(self.ex_view, os.path.join(tmp, "live"), lambda: os.path.join(tmp, "out"), runner=lambda: self.runner, log=self.log,
                                    disk_usage=lambda p: (100 * LX.GB, 200 * LX.GB), exported=lambda job, media, archived=False: self.marks.exported(job, media, archived))
        self.exporter.start = lambda: None   # 書き出しは動かさない(ジョブは「録画待ち」のまま。済んだ所はテストが _finish を呼ぶ)
        self.marks = LA.LocalMarks(lambda: self.exporter)

    def auto_cfg(self, rc=None, rec=None):
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
        self.view = Strict(self.host)
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

    def finish(self, job, name):
        """書き出しが済んだ所から(録画元に繋がないので _finish を直に)。-> 書き出した動画のパス"""
        ex = self.host.exporter
        media = os.path.join(self.folder, name)
        open(media, "wb").close()
        ex._finish(next(x for x in ex.jobs if x["id"] == job["id"]), self.host.find("fake"), REC, {"url": URL, "firstPdt": LX.epoch_iso(FIRST)},
                   {"path": media, "title": "テスト配信", "duration": 30.0}, FIRST + 1, FIRST + 31)
        return media

    def test_case_after_first_export(self):
        """RS8 B3-5(決定 3-37 の (r8j)): スタジオなしの採用は書き出しまで正本に置き、初めて書き出したとき録画の採用を全部 案件の 採用.json へ写す。
        そのあとの採用・書き出し済み・読み(G3 の adopted)は 採用.json を通り、正本には採用の印を足さない。片付けは写っていれば正本を消してよい"""
        p = mock.patch.object(CB._fsio, "is_fixed_drive", return_value=True)
        p.start()
        self.addCleanup(p.stop)
        h, ex = self.host, self.host.exporter
        ms, marks = ex.marks, self.host.marks
        out = os.path.join(self.tmp, "out")
        os.makedirs(out)
        self.folder = LX.pick_folder(out, "テスト配信", VID)   # 書き出しと同じ置き場(作業用/.studio-id = 配信の videoId)
        r1 = self.ad.adopt({"recorder": "fake", "recording": REC, "start": 100.0, "end": 130.0, "after": "none"})
        r2 = self.ad.adopt({"recorder": "fake", "recording": REC, "start": 200.0, "end": 230.0, "after": "none"})
        self.assertIsNone(ms.case("fake", REC))
        self.assertEqual([(x["id"], x["status"], x["start"]) for x in marks.adopted("fake", REC)], [(r1["mark"], "adopted", 100.0), (r2["mark"], "adopted", 200.0)])
        self.assertFalse(ms.settled("fake", REC))   # まだ案件に写っていない = 正本を消さない
        m1 = self.finish(r1["job"], "01.mp4")       # 初めて書き出した → 案件へ写す
        root = ms.case("fake", REC)
        self.assertEqual(root, os.path.normpath(self.folder))
        c, a = CF.read(root)
        self.assertEqual((list(a["sources"]), a["sources"][REC]["kind"], a["sources"][REC]["live"]["videoId"]), ([REC], "live", VID))
        self.assertEqual([(x["id"], x["status"], x.get("path"), x.get("file")) for x in a["marks"]],
                         [(r1["mark"], "exported", "01.mp4", "テスト配信/01.mp4"), (r2["mark"], "adopted", None, "")])
        self.assertTrue(ms.settled("fake", REC))
        # そのあとの採用は 採用.json(正本には採用の印を足さない = 書き出しのジョブの入力 upsert だけ)
        r3 = self.ad.adopt({"recorder": "fake", "recording": REC, "start": 50.0, "end": 60.0, "label": "前", "after": "none"})
        self.assertEqual((r3["job"]["n"], r3["job"]["label"]), (1, "前"))   # 番号は案件のマークの開始の順
        self.assertEqual([x["id"] for x in CF.merge(*CF.read(root), REC, root)["marks"]], [r1["mark"], r2["mark"], r3["mark"]])
        self.assertNotIn(r3["mark"], [x["key"] for x in ms.local("fake", REC)])
        self.assertEqual(ms.get("fake", REC, LX.studio_mark_id(r3["mark"]))["src"], "studio")   # ジョブの入力
        again = self.ad.adopt({"recorder": "fake", "recording": REC, "start": 50.3, "end": 59.8, "after": "none"})
        self.assertEqual((again["existing"], again["mark"]), (True, r3["mark"]))
        self.assertEqual(len(CF.merge(*CF.read(root), REC, root)["marks"]), 3)
        # 写したあとの書き出し済みも 採用.json(写す前の採用 r2・写したあとの採用 r3)
        self.finish(r2["job"], "02.mp4")
        m3 = self.finish(r3["job"], "03.mp4")
        got = {x["id"]: x for x in CF.merge(*CF.read(root), REC, root)["marks"]}
        self.assertEqual({k: v["status"] for k, v in got.items()}, {r1["mark"]: "exported", r2["mark"]: "exported", r3["mark"]: "exported"})
        self.assertEqual((got[r1["mark"]]["path"], got[r3["mark"]]["path"]), (m1, m3))
        self.assertEqual(sorted(x["id"] for x in marks.adopted("fake", REC)), sorted(got))   # G3 の読みは案件から
        self.assertTrue(ms.settled("fake", REC))
        # 正本にだけある採用の印(写っていない)があれば消さない
        ms.adopt("fake", REC, "a00000000000f", FIRST, 400.0, 410.0)
        self.assertFalse(ms.settled("fake", REC))
        self.assertTrue(ms.drop("fake", REC))   # drop は settled を見ない(呼ぶ側 = ライブの片付けが確かめる)
        self.assertFalse(os.path.exists(ms.path("fake", REC)))
        self.no_strays()

    def test_case_unseen_refuses(self):
        """案件に写した録画の案件が見えない(フォルダを動かした・ドライブが外れた)→ 採用は 503 で断る((r8d)・(r8o))・読みは正本の印に落ちる"""
        p = mock.patch.object(CB._fsio, "is_fixed_drive", return_value=True)
        p.start()
        self.addCleanup(p.stop)
        out = os.path.join(self.tmp, "out")
        os.makedirs(out)
        self.folder = LX.pick_folder(out, "テスト配信", VID)
        r1 = self.ad.adopt({"recorder": "fake", "recording": REC, "start": 100.0, "end": 130.0, "after": "none"})
        self.finish(r1["job"], "01.mp4")
        shutil.move(self.folder, self.folder + "-moved")
        with self.assertRaises(LX.LiveError) as cm:
            self.ad.adopt({"recorder": "fake", "recording": REC, "start": 300.0, "end": 330.0, "after": "none"})
        self.assertEqual(cm.exception.code, 503)
        self.assertEqual([x["id"] for x in self.host.marks.adopted("fake", REC)], [r1["mark"]])
        self.assertFalse(self.host.exporter.marks.settled("fake", REC))

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
