"""録画を自動で消す(src/manage/keep/live_cleanup.py。線 D の P4 の 0-9 の最後)のテスト。消すのは戻せないので、消えない場合を厚く確かめる。

偽の Live(録画元の一覧と delete)と本物の書き出しの管理(flow/live_export の Exporter)で動かす。入口(src/home/live.py)は使わない。
実行(リポジトリ直下から): python -m unittest src/manage/keep/tests/test_live_cleanup.py -v
"""
import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> keep -> manage -> src
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from flow import live_archive as A  # noqa: E402
from flow import live_export as LX  # noqa: E402
from manage.keep import live_cleanup as LC  # noqa: E402
from ytt import fsio, schemas  # noqa: E402

RELEASE = 1790000000.0            # 配信の開始時刻


class FakeExLive:
    """Exporter が使う Live の代わり(このテストは書き出しを動かさない)"""
    def find(self, rid):
        return {"id": rid, "name": rid}


class CleanupLive:
    """Cleaner(src/manage/keep/live_cleanup.py)が使う Live の代わり: 録画元の一覧と delete(呼ばれた順に覚える)・書き出しのジョブ(本物の Exporter)"""

    def __init__(self, store, out):
        self.rc = {"id": "local", "name": "この PC", "url": "http://127.0.0.1:1", "token": ""}
        self.recs = {}          # 録画の id -> 一覧の行
        self.down = False       # 録画元につながらない
        self.refuse = {}        # 録画の id -> (HTTP の番号, JSON)(delete を断る)
        self.calls = []
        self.exporter = LX.Exporter(FakeExLive(), store, lambda: out)

    def recorders(self):
        return [self.rc]

    def find(self, rid):
        return self.rc if rid == "local" else None

    def call(self, rc, method, path, body=None, timeout=3.0):
        self.calls.append((method, path))
        if self.down:
            return None, None
        if method == "GET" and path == "/live/list":
            return 200, {"recordings": [dict(r) for r in self.recs.values()]}
        m = path.split("/")
        if method == "POST" and len(m) == 4 and m[3] == "delete":
            if m[2] in self.refuse:
                return self.refuse[m[2]]
            if m[2] not in self.recs:
                return 404, {"error": "not_found", "message": "その録画はありません"}
            if self.recs[m[2]].get("active"):
                return 409, {"error": "conflict", "message": "録画中"}
            del self.recs[m[2]]
            return 200, {"ok": True, "deleted": m[2]}
        return 404, {"error": "not_found"}

    def add(self, rid, state="stopped", ended_ago=10.0):
        self.recs[rid] = {"id": rid, "state": state, "active": state in ("waiting", "recording", "reconnecting"),
                          "endedAt": None if state in ("waiting", "recording", "reconnecting") else LX.epoch_iso(time.time() - ended_ago)}

    def deleted(self):
        return [p.split("/")[2] for m, p in self.calls if m == "POST" and p.endswith("/delete")]


class CleanupTest(unittest.TestCase):
    """録画を自動で消す(src/manage/keep/live_cleanup.py。P4 の 0-9 の最後)。消すのは戻せないので、消えない場合を厚く確かめる"""
    R1, R2, R3 = "20261005-120000-abcdefghijk", "20261005-130000-abcdefghijk", "20261005-140000-abcdefghijk"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-live-clean-")
        self.out = os.path.join(self.tmp, "out")
        os.makedirs(self.out)
        self.live = CleanupLive(os.path.join(self.tmp, "live"), self.out)
        self.on = True
        self.studio_videos = {}     # 録画の id -> マークの一覧(無い = スタジオに登録なし)
        self.studio_down = False
        self.studio_calls = []
        self.logs = []
        self.cl = LC.Cleaner(self.live, enabled=lambda: self.on, studio=self.studio, log=self.logs.append,
                                                     no_mark_sec=2.0, keep_sec=2.0, interval=0)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def studio(self, method, path, body=None):
        self.studio_calls.append((method, path, body))
        if self.studio_down:
            return None, {"message": "つながりません"}
        if method == "GET" and path.startswith("/api/video?id="):
            vid = path.split("=", 1)[1]
            if vid not in self.studio_videos:
                return 404, {"error": "not_found", "message": "動画が見つかりません"}
            return 200, {"video": {"id": vid, "kind": "live", "marks": [dict(m) for m in self.studio_videos[vid]]}}
        if method == "POST" and path == "/api/video/delete":
            vid = body["id"]
            if vid not in self.studio_videos:
                return 404, {"error": "not_found"}
            if body.get("ifNoMarks") and self.studio_videos[vid]:
                return 409, {"error": "has_marks", "message": "マークがあるので消しません"}
            del self.studio_videos[vid]
            return 200, {"ok": True}
        return 404, {"error": "not_found"}

    def job(self, rec, n, state="done", arc="done", keep=None, at=None, needs=False):
        j = {"id": "lx-%010x" % (n + 100 * len(self.live.exporter.jobs)), "recorder": "local", "recording": rec, "markId": "lm-%012x" % n, "n": n,
             "label": "", "start": LX.epoch_iso(RELEASE + n * 10), "end": LX.epoch_iso(RELEASE + n * 10 + 5), "state": state, "message": "",
             "error": "", "needsArchive": needs, "created": LX.now_iso(), "updated": LX.now_iso(), "path": "",
             "studio": {"video": rec, "mark": "m%d" % n, "start": n * 10.0, "end": n * 10.0 + 5}}
        if arc:
            j["archive"] = {"state": arc, "label": A.LABELS.get(arc, arc), "at": at or LX.now_iso(), "keep": keep}
        self.live.exporter.jobs.append(j)
        return j

    def smark(self, n, status="exported", start=None):
        return {"id": "m%d" % n, "status": status, "start": n * 10.0 if start is None else start, "end": n * 10.0 + 5}

    def test_kept_recordings_are_reported(self):
        """D-14 と 10-09 のユーザー決定: 終わっているのに消せない録画は理由を覚える。理由が「本番版になっていないマークがある」だけなら
        終わって STALE_SEC で消し(スタジオに採用のまま書き出していないマークがあれば消さない)、WARN_SEC から「調子」に予告(delete_notice)。
        ほかの理由(書き出しの途中など)は STALE_SEC より古ければ「調子」の失敗(kind keep。keep_failure)に出し、消さない。録画中は出さない"""
        C = LC
        R4, R5 = "20261005-150000-abcdefghijk", "20261005-160000-abcdefghijk"
        self.live.add(self.R1, ended_ago=C.STALE_SEC + 100)
        self.job(self.R1, 1, state="done", arc="error")     # 本番版になっていない・3 日たった → 消す
        self.live.add(self.R2, ended_ago=C.WARN_SEC + 100)
        self.job(self.R2, 1, state="done", arc="error")     # 本番版になっていない・2 日 → 予告
        self.live.add(self.R3, state="recording")
        self.live.add(R4, ended_ago=C.STALE_SEC + 100)
        self.job(R4, 1, state="encode", arc="wait")         # 書き出しの途中 → 消さずに知らせる
        self.live.add(R5, ended_ago=C.STALE_SEC + 100)
        self.job(R5, 1, state="done", arc="error")
        self.studio_videos[R5] = [self.smark(1), self.smark(2, status="adopted")]   # 採用のまま書き出していないマーク → 消さない
        self.cl.tick(force=True)
        self.assertEqual(self.live.deleted(), [self.R1])
        self.assertTrue(all(j.get("recordingDeleted") for j in self.live.exporter.jobs if j["recording"] == self.R1))
        f = {x["recording"]: x for x in self.cl.kept_failures()}
        self.assertEqual(sorted(f), sorted([self.R2, R4, R5]))
        self.assertEqual((f[self.R2]["kind"], f[self.R2]["kindLabel"], f[self.R2]["at"] is not None), ("keep", "録画の片付け", True))
        for s in ("あと約 23 時間で録画を自動で消します", "録画を自動で消す"):
            self.assertIn(s, f[self.R2]["text"])
        for s in ("書き出しの途中", "3 日", R4, "自動では消えません"):
            self.assertIn(s, f[R4]["text"])
        self.assertIn("採用のまま書き出していないマークがある", f[R5]["text"])
        self.assertNotIn(self.R3, self.cl._kept)
        self.live.exporter.jobs[1]["archive"]["state"] = "done"   # R2 が本番版になったら消えて、予告も消える
        self.studio_videos[self.R2] = [self.smark(1)]
        self.cl.tick(force=True)
        self.assertEqual(self.live.deleted(), [self.R1, self.R2])
        self.assertEqual(sorted(x["recording"] for x in self.cl.kept_failures()), sorted([R4, R5]))

    def test_replaced_recording_is_deleted(self):
        self.live.add(self.R1)
        j1, j2 = self.job(self.R1, 1), self.job(self.R1, 2)
        self.studio_videos[self.R1] = [self.smark(1), self.smark(2), self.smark(3, "rejected"), self.smark(4, "")]   # 不採用・候補は数えない
        self.assertEqual(self.cl.tick()["deleted"], [self.R1])
        self.assertEqual(self.live.deleted(), [self.R1])
        self.assertTrue(j1["recordingDeleted"] and j2["recordingDeleted"])   # 画面が「録画は消しました」と出す印
        saved = fsio.read_json_file(os.path.join(self.tmp, "live", "exports.json"), 1 << 20)
        self.assertTrue(all(j.get("recordingDeleted") for j in saved["jobs"]))
        self.assertTrue(any("録画を消しました" in m and self.R1 in m for m in self.logs), self.logs)
        self.assertEqual(self.cl.tick()["deleted"], [])   # もう一覧に無い

    def test_replaced_but_not_yet(self):
        """1 本でも本番版でない・途中・失敗・取り消し・採用のまま・録画中・スタジオが答えない → 消さない"""
        cases = [
            ("作り直せなかった", lambda r: (self.job(r, 1), self.job(r, 2, arc="error"))),
            ("順番待ち", lambda r: (self.job(r, 1), self.job(r, 2, arc="wait"))),
            ("作り直しの途中", lambda r: (self.job(r, 1), self.job(r, 2, arc="fetch"))),
            ("取り消し", lambda r: (self.job(r, 1), self.job(r, 2, arc="cancelled"))),
            ("まだ試していない", lambda r: (self.job(r, 1), self.job(r, 2, arc=None))),
            ("書き出しの途中", lambda r: (self.job(r, 1), self.job(r, 2, state="wait", arc=None))),
            ("欠けで書き出せず、作り直していない", lambda r: (self.job(r, 1), self.job(r, 2, state="error", arc=None, needs=True))),
            ("最新の書き出しが失敗", lambda r: (self.job(r, 1), self.job(r, 2), self.job(r, 2, state="error", arc=None))),
        ]
        for name, make in cases:
            with self.subTest(name):
                self.live.exporter.jobs[:] = []
                self.live.calls[:] = []
                self.live.add(self.R1)
                self.studio_videos[self.R1] = [self.smark(1), self.smark(2)]
                make(self.R1)
                self.assertEqual(self.cl.tick()["deleted"], [], name)
                self.assertEqual(self.live.deleted(), [], name)
        # 全部本番版でも: 録画中(つなぎ直し中)・採用のまま書き出していないマーク・区間を直して採用に戻したマーク・スタジオにつながらない
        self.live.exporter.jobs[:] = []
        self.job(self.R1, 1)
        self.job(self.R1, 2)
        for name, setup in (("つなぎ直し中", lambda: self.live.add(self.R1, "reconnecting")),
                            ("採用のまま", lambda: self.studio_videos.__setitem__(self.R1, [self.smark(1), self.smark(2), self.smark(5, "adopted")])),
                            ("区間を直した", lambda: self.studio_videos.__setitem__(self.R1, [self.smark(1), self.smark(2, "adopted", start=21.0)])),
                            ("スタジオが答えない", lambda: setattr(self, "studio_down", True))):
            with self.subTest(name):
                self.live.add(self.R1)
                self.studio_down = False
                self.studio_videos[self.R1] = [self.smark(1), self.smark(2)]
                setup()
                self.assertEqual(self.cl.tick()["deleted"], [], name)
                self.assertEqual(self.live.deleted(), [], name)
        self.studio_down = False
        self.studio_videos[self.R1] = [self.smark(1), self.smark(2, "adopted")]   # 作り直した欠けのマーク(書き出し済みにする前の採用)は、同じ区間なら数えない
        self.live.add(self.R1)
        self.assertEqual(self.cl.tick()["deleted"], [self.R1])

    def test_off_and_recorder_down(self):
        self.live.add(self.R1)
        self.job(self.R1, 1)
        self.studio_videos[self.R1] = [self.smark(1)]
        self.live.add(self.R2, ended_ago=99999)   # マークなし・1 日より前
        self.on = False   # 設定オフ: 何も消さない(録画元にも聞かない)
        self.assertEqual(self.cl.tick(), {"deleted": [], "keeps": 0})
        self.assertEqual(self.live.calls, [])
        self.assertFalse(self.cl.check("local", self.R1))
        self.on = True
        self.live.down = True   # 録画元につながらない: 何もしない
        self.assertEqual(self.cl.tick()["deleted"], [])
        self.assertFalse(self.cl.check("local", self.R1))
        self.live.down = False
        self.live.refuse[self.R1] = (409, {"error": "conflict", "message": "使用中のファイルがあるので、録画を消しきれませんでした"})
        self.assertNotIn(self.R1, self.cl.tick()["deleted"])   # 使用中: 印を付けない・次にまたやる
        self.assertNotIn("recordingDeleted", self.live.exporter.jobs[0])
        self.cl.tick()
        self.assertEqual(sum(1 for m in self.logs if "消しきれません" in m), 1)   # 同じ理由は 1 行だけ
        del self.live.refuse[self.R1]
        self.assertTrue(self.cl.check("local", self.R1))   # 1本だけ確かめる(Archiver の after から)
        self.assertFalse(self.cl.check("local", "../x"))

    def test_no_marks(self):
        self.live.add(self.R1, ended_ago=10)       # 終わって 2 秒(縮めた 24 時間)より前 → 消す(スタジオに登録なし)
        self.live.add(self.R2, ended_ago=10)       # スタジオに登録あり・マーク 0 → スタジオの行を消してから録画を消す
        self.studio_videos[self.R2] = []
        self.live.add(self.R3, ended_ago=0.1)      # 終わったばかり → 消さない
        self.live.add("20261005-150000-abcdefghijk", "recording")   # 録画中 → 消さない
        self.live.add("20261005-160000-abcdefghijk", ended_ago=10)  # スタジオにマークがある → 消さない
        self.studio_videos["20261005-160000-abcdefghijk"] = [self.smark(1, "")]
        self.live.add("20261005-170000-abcdefghijk", ended_ago=10)  # 入口のマークの正本に残っている → 消さない
        self.live.exporter.marks.upsert("local", "20261005-170000-abcdefghijk", "lm-000000000001", 1, LX.epoch_iso(RELEASE), LX.epoch_iso(RELEASE + 1))
        got = self.cl.tick()["deleted"]
        self.assertEqual(sorted(got), sorted([self.R1, self.R2]))
        del self.live.recs[self.R3]   # この先で時間がたって消えないように
        self.assertNotIn(self.R2, self.studio_videos)
        self.assertIn(("POST", "/api/video/delete", {"id": self.R2, "ifNoMarks": True}), self.studio_calls)
        self.assertFalse([c for c in self.studio_calls if c[0] == "POST" and c[2]["id"] == self.R1])   # 登録の無い録画のスタジオは触らない
        # スタジオにつながらない・答えが読めない → 消さない
        self.live.add(self.R1, ended_ago=10)
        self.studio_down = True
        self.assertEqual(self.cl.tick()["deleted"], [])
        self.studio_down = False
        orig = self.studio
        self.cl.studio = lambda m, p, b=None: (200, {"video": {"id": "other", "marks": []}})   # 別の配信の答え
        self.assertEqual(self.cl.tick()["deleted"], [])
        self.cl.studio = lambda m, p, b=None: (404, {})   # スタジオの 404 でない(入口の 404 など)
        self.assertEqual(self.cl.tick()["deleted"], [])
        self.cl.studio = orig
        # 調べてから消すまでの間にマークが付いた(スタジオが 409)→ 録画も消さない
        self.studio_videos[self.R1] = []
        real = self.studio

        def late(m, p, b=None):
            if m == "POST":
                self.studio_videos[self.R1] = [self.smark(1, "")]
            return real(m, p, b)
        self.cl.studio = late
        self.assertEqual(self.cl.tick()["deleted"], [])
        self.assertIn(self.R1, self.live.recs)

    def test_after_stream_holds_delete(self):
        """配信後の全自動(M7)がまだの録画は、マークが無くても・入れ替えが全部済んでいても消さない(hold)。済めば消す"""
        hold = {"why": "配信後の自動の切り抜き(アーカイブの解析)がまだです"}
        self.cl.hold = lambda rc, r: hold["why"]
        self.live.add(self.R1, ended_ago=10)                # マークの無い録画
        self.live.add(self.R2)                              # 入れ替えが全部済んだ録画
        self.job(self.R2, 1)
        self.studio_videos[self.R2] = [self.smark(1)]
        self.assertEqual(self.cl.tick()["deleted"], [])
        self.assertTrue(any("まだ消しません" in x and "配信後の自動" in x for x in self.logs), self.logs)
        hold["why"] = ""
        self.assertEqual(sorted(self.cl.tick()["deleted"]), sorted([self.R1, self.R2]))
        self.cl.hold = lambda rc, r: 1 / 0                  # 確かめられなければ消さない
        self.live.add(self.R3, ended_ago=10)
        self.assertEqual(self.cl.tick()["deleted"], [])

    def test_keeps_after_7_days(self):
        folder = os.path.join(self.out, "配信", schemas.WORK_DIR, A.SPEED_DIR)
        os.makedirs(folder)
        old = os.path.join(folder, "01_a.mp4")
        new = os.path.join(folder, "02_b.mp4")
        for p in (old, new):
            with open(p, "wb") as f:
                f.write(b"x")
        outside = os.path.join(self.tmp, "elsewhere", schemas.WORK_DIR, A.SPEED_DIR, "03_c.mp4")
        os.makedirs(os.path.dirname(outside))
        with open(outside, "wb") as f:
            f.write(b"x")
        other = os.path.join(self.out, "配信", "04_d.mp4")   # 作業用\速報版 の外(書き出した本体)
        with open(other, "wb") as f:
            f.write(b"x")
        long_ago = LX.epoch_iso(time.time() - 10)
        j1 = self.job(self.R1, 1, keep=old, at=long_ago)
        j2 = self.job(self.R1, 2, keep=new)            # 入れ替えたばかり
        j3 = self.job(self.R1, 3, keep=outside, at=long_ago)
        j4 = self.job(self.R1, 4, keep=other, at=long_ago)
        j5 = self.job(self.R1, 5, keep=os.path.join(folder, "05_gone.mp4"), at=long_ago)   # 手で消した
        self.on = False
        self.assertEqual(self.cl.tick()["keeps"], 0)
        self.assertTrue(os.path.isfile(old))
        self.on = True
        self.assertEqual(self.cl.tick()["keeps"], 2)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.isfile(new) and os.path.isfile(outside) and os.path.isfile(other))
        self.assertTrue(j1["archive"]["keepDeleted"] and j5["archive"]["keepDeleted"])
        self.assertNotIn("keepDeleted", j2["archive"])
        self.assertNotIn("keepDeleted", j3["archive"])
        self.assertNotIn("keepDeleted", j4["archive"])
        self.assertEqual(self.cl.tick()["keeps"], 0)   # 2 回は消さない


if __name__ == "__main__":
    unittest.main()
