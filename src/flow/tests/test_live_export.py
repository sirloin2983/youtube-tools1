# -*- coding: utf-8 -*-
"""マークと書き出し(線 D の P2。② の src/flow/live_export.py の Exporter)・採用(M1)・失敗の集約(M3。src/flow/live_failures.py)・ディスク・重い処理の枠のテスト。
入口 home の Live は使わず、ライブ係 flow/livesession.LiveSession(本物の録画の部品 --source direct・偽のまとめて実行・偽のスタジオ)で組む。

    py -3.10 -m unittest src/flow/tests/test_live_export.py

  - 本物の録画の部品(--source direct)で配信中のふりの HLS を録り、マーク → 録画待ち → 届いたら取得 → 30fps → スタジオと同じ置き場所・名前・.clip.json →
    文字起こしへ(偽のまとめて実行)・取り消し・録画が先に終わった・録画元が落ちた・欠け・起動し直したらやり直す・書き出しの音量(スタジオと同じ)
  - 採用 POST /live/api/adopt の中身(LiveSession.adopt。スタジオのマーク → 正本 → 書き出し → 書き出し済み)・前後の余白 pad_secs
  - 失敗の集約: LIVE の帯と「調子」(health の failures)に同じ文・空き容量の行
  - 名前・フォルダの選び方・再起動で動いていたジョブを待ちに戻す・繋ぎ直しをまたぐ書き出し・空き容量不足で待つ→再開・アーカイブ待ち(hold)・
    友人の依頼の受け渡し・重い処理の枠(録画中は 1 つ空ける)・欠け = アーカイブが要る
"""
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)

TESTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(TESTS))   # tests -> flow -> src
sys.path.insert(0, TESTS)
import _livefix as FIX  # noqa: E402
from flow import live_adopt as LA  # noqa: E402
from flow import live_export as LX  # noqa: E402
from flow import live_failures as LF  # noqa: E402
from flow import run as RunMod  # noqa: E402
from human.friend import live_requests as LR  # noqa: E402
from ytt import fsio, jobs, loudness, normalize, schemas, tools  # noqa: E402

TOKEN = FIX.TOKEN


def wait_for(fn, timeout=20.0, step=0.2):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return fn()


def handed(env, spec):
    """② の口 submit に渡った封筒 + 束 -> 以前の start_file の引数の形 (動画, 題, flow, 配信者, kw)(RS7-2 G2b: 書き出しの受け渡しは submit に。中身は同じ実行)"""
    run = RunMod.Run.from_envelope(env, spec)
    kw = {k: getattr(run, k) for k in ("cut", "engine", "model") if getattr(run, k)}
    if run.request_id:
        kw.update(request_id=run.request_id, deliver_dir=run.deliver_dir, speakers=run.speakers, video_tracks=run.video_tracks,
                  deliver_batch=run.deliver_batch, pool=run.pool)
    return run.source_path, run.title, "auto" if run.mode == "file_auto" else "check", run.streamer, kw


class FakeRunner:
    """まとめて実行の代わり(文字起こしへ渡した動画を覚える)"""

    def __init__(self):
        self.files = []
        self.streamers = []   # submit に渡った配信者の名前(files と同じ順)
        self.accepts = []     # submit の accept(受付と同じ決め方 = 以前の start_file)

    def submit(self, env, spec=None, accept=False):
        self.accepts.append(accept)
        path, title, flow, streamer, kw = handed(env, spec)
        return self.start_file(path, title, flow, streamer, **kw)

    def start_file(self, path, title="", flow="check", streamer=None, **kw):
        if getattr(self, "fail", None):
            raise ValueError(self.fail)
        self.files.append((path, title, flow))
        self.streamers.append(streamer)
        self.kws = getattr(self, "kws", []) + [kw]   # 書き出したあとの設定(live.auto の cut・engine・model。M2)
        return {"id": "run-%d" % len(self.files)}

    def snapshot(self):
        return {"runs": [{"id": "run-%d" % (i + 1), "state": "queued", "stateLabel": "待ち",
                          "steps": [{"key": "transcribe", "label": "文字起こし", "state": "wait", "stateLabel": "待ち", "detail": ""}]}
                         for i in range(len(self.files))]}


class FailuresTest(unittest.TestCase):
    """M3: 失敗の集約(src/flow/live_failures.py)。書き出し・まとめて実行へ渡す・文字起こし・パックの失敗を 1 つの関数で文にして、
    LIVE の帯(GET /live/api/exports のジョブ)と「調子」(Live.health の failures)に同じ文で出す。exports.json と autorun-runs.jsonl を読むだけ"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-live-fail-")
        self.fake = FIX.FakeRecorder()
        self.cfg = FIX.live_cfg(recorders=[{"id": "local", "name": "この PC", "url": self.fake.url, "token": TOKEN}])
        self.logs = os.path.join(self.tmp, "logs")
        os.makedirs(self.logs)
        now = LX.now_iso()
        old = LX.epoch_iso(time.time() - 8 * 86400)

        def job(i, **kw):
            return dict({"id": "lx-%010d" % i, "recorder": "local", "recording": "20261004-000000-a", "markId": "lm-%012d" % i, "n": i, "label": "",
                         "start": now, "end": now, "state": "done", "message": "", "error": "", "warning": "", "path": "", "runId": "",
                         "created": now, "updated": now}, **kw)
        jobs = [job(1, state="error", error="録画が区間まで届きませんでした(録画は「ended」です)", label="山1"),
                job(2, path=os.path.join(self.tmp, "out", "02_渡せない.mp4"), handoffError="パックへ渡せませんでした: まとめて実行が使えません"),
                job(3, path=os.path.join(self.tmp, "out", "03_パック.mp4"), runId="r-pack"),
                job(4, path=os.path.join(self.tmp, "out", "04_文字.mp4"), runId="r-tx", warning="録画の終わりまでで切りました"),
                job(5, path=os.path.join(self.tmp, "out", "05_ok.mp4"), runId="r-ok"),
                job(6, state="cancelled", message="取り消しました"),
                job(7, state="error", error="古い失敗", updated=old, created=old)]   # 7 日より前は「調子」に出さない
        os.makedirs(os.path.join(self.tmp, "live"))
        with open(os.path.join(self.tmp, "live", "exports.json"), "w", encoding="utf-8") as f:
            json.dump({"schema": LX.JOBS_SCHEMA, "jobs": jobs}, f, ensure_ascii=False)

        def run(rid, state, steps, error=""):
            return {"v": 1, "id": rid, "kind": "file", "sourcePath": "x.mp4", "state": state, "error": error, "created": 1, "mode": "file_auto",
                    "steps": [{"key": k, "label": k, "state": s, "detail": ""} for k, s in steps]}
        with open(os.path.join(self.logs, "autorun-runs.jsonl"), "w", encoding="utf-8") as f:
            for r in (run("r-pack", "error", [("transcribe", "done"), ("pack", "error")], "パックを作れませんでした: 字幕がありません"),
                      run("r-tx", "error", [("transcribe", "error"), ("pack", "wait")], "文字起こしに失敗しました: モデルがありません"),
                      run("r-ok", "done", [("transcribe", "done"), ("pack", "done")])):
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        self.live = FIX.new_session(self.tmp, self.cfg, root=REPO)

    def tearDown(self):
        self.fake.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_same_text_in_band_and_health(self):
        snap = {j["id"]: j for j in self.live.exporter.snapshot()}
        f = {jid: (j.get("failure") or {}) for jid, j in snap.items()}
        self.assertEqual({jid: x.get("kind") for jid, x in f.items() if x},
                         {"lx-0000000001": "export", "lx-0000000002": "handoff", "lx-0000000003": "pack", "lx-0000000004": "transcribe", "lx-0000000007": "export"})
        self.assertEqual(f["lx-0000000001"]["text"], "「山1」: 書き出しに失敗しました: 録画が区間まで届きませんでした(録画は「ended」です)")
        self.assertEqual(f["lx-0000000002"]["text"], "02_渡せない.mp4: パックへ渡せませんでした: まとめて実行が使えません")
        self.assertEqual(f["lx-0000000003"]["text"], "03_パック.mp4: パックを作れませんでした: 字幕がありません")   # 理由が段の名前で始まるなら重ねない
        self.assertEqual(f["lx-0000000004"]["text"], "04_文字.mp4: 文字起こしに失敗しました: モデルがありません")
        self.assertEqual(LF.failure_of({"state": "done", "label": "x", "runId": "r"}, {"state": "error", "error": "つながりません", "steps": [{"key": "pack", "state": "error"}]})["text"],
                         "「x」: パックに失敗しました: つながりません")
        self.assertIsNone(LF.failure_of({"state": "done", "runId": "r"}, {"state": "cancelled", "steps": []}))   # 人の中止は失敗ではない
        # 帯が出す欄に同じ文: 書き出しの失敗は error、それ以外は warning(前からの警告は残す)
        self.assertEqual(snap["lx-0000000001"]["error"], f["lx-0000000001"]["text"])
        self.assertEqual(snap["lx-0000000004"]["warning"], "録画の終わりまでで切りました / " + f["lx-0000000004"]["text"])
        for jid in ("lx-0000000002", "lx-0000000003"):
            self.assertEqual(snap[jid]["warning"], f[jid]["text"])
        # 「調子」: 7 日より前・取り消し・成功は出さない。文は帯と同じ
        h = self.live.health()
        self.assertEqual(sorted(x["text"] for x in h["failures"]), sorted(f[jid]["text"] for jid in ("lx-0000000001", "lx-0000000002", "lx-0000000003", "lx-0000000004")))
        self.assertEqual({x["kind"] for x in h["failures"]}, {"export", "handoff", "pack", "transcribe"})
        # 書き出しの記録は書き換えない(読むだけ)
        with open(os.path.join(self.tmp, "live", "exports.json"), encoding="utf-8") as fh:
            self.assertNotIn("failure", fh.read())

    def test_off_has_no_failures_and_portal_health(self):
        FIX.patch_cfg(self.cfg, {"enabled": False})
        self.assertIsNone(self.live.health())                                # オフなら「調子」に出さない(今までどおり)

    def test_health_has_disk(self):
        """M4: 「調子」に書き出し先・パック・live\\work の空き(state・行・しきい値)"""
        self.live.exporter.disk_usage = lambda p: (4 * LX.GB, 100 * LX.GB)
        self.live.exporter.disk_poll = 0
        d = self.live.health()["disk"]
        self.assertEqual((d["state"], d["lowBytes"], d["warnBytes"]), ("low", 5 * LX.GB, 20 * LX.GB))
        self.assertTrue(d["rows"] and all(r["state"] == "low" and r["freeBytes"] == 4 * LX.GB for r in d["rows"]))
        self.assertIn("5 GB 以上空くと続けます", d["message"])


_SRC = {}


def source(seconds=60):
    if seconds not in _SRC:
        d = tempfile.mkdtemp(prefix="ytt-live-src-")
        _SRC[seconds] = (d, FIX.hls_fixture().make_source(d, seconds))
    return _SRC[seconds]


class ExportTest(unittest.TestCase):
    """本物の録画の部品(--source direct)で配信中のふりの HLS を録り、マーク → 書き出す"""

    @classmethod
    def setUpClass(cls):
        cls.src_dir, cls.segs = source(60)

    @classmethod
    def tearDownClass(cls):
        for d, _ in _SRC.values():
            shutil.rmtree(d, ignore_errors=True)
        _SRC.clear()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-live-export-")
        self.src = FIX.hls_fixture().LiveServer(self.src_dir, self.segs, start=3, rate=1.0)
        self.src.end = False
        self.port = FIX.free_port()
        self.rdata = os.path.join(self.tmp, "recdata")
        self.proc = subprocess.Popen([sys.executable, os.path.join(REPO, "pipeline", "ingest", "recorder.py"), "--port", str(self.port), "--data-dir", self.rdata,
                                      "--folder", os.path.join(self.tmp, "live-rec"), "--source", "direct", "--hls-time", "1", "--quiet"],
                                     env=dict(os.environ, PYTHONIOENCODING="utf-8"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        self.assertTrue(wait_for(lambda: os.path.isfile(os.path.join(self.rdata, "token.txt")), 20))
        time.sleep(0.2)
        with open(os.path.join(self.rdata, "token.txt"), encoding="ascii") as f:
            token = f.read().strip()
        self.cfg = FIX.live_cfg(recorders=[{"id": "local", "name": "この PC", "url": "http://127.0.0.1:%d" % self.port, "token": token}])
        self.runner = FakeRunner()
        self.out = os.path.join(self.tmp, "out")
        self.audio = {"volume": 100, "loudness": None}   # 既定の書き出しは音量そのまま(音量の確認は test_audio_like_studio)
        self.live = FIX.new_session(self.tmp, self.cfg, root=REPO, out_dir=lambda: self.out, runner=lambda: self.runner, audio=lambda: self.audio)
        self.rc = self.live.find("local")
        self.assertTrue(wait_for(lambda: self.live.ping(self.rc), 20))
        self.ex = self.live.exporter
        self.ex.poll, self.ex.down_sec = 0.3, 3.0

    def tearDown(self):
        self.live.close()
        try:
            for r in (self.live.call(self.rc, "GET", "/live/list")[1] or {}).get("recordings") or []:
                if r.get("active"):
                    self.live.call(self.rc, "POST", "/live/%s/stop" % r["id"], {}, timeout=40)
            self.live.call(self.rc, "POST", "/live/quit", {})
            self.proc.wait(20)
        except Exception:
            self.proc.kill()
        self.src.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def start_rec(self, n=4):
        code, d = self.live.call(self.rc, "POST", "/live/start", {"url": self.src.url, "title": "テストの配信"}, timeout=10)
        self.assertEqual(code, 200, d)
        rid = d["recording"]["id"]
        self.assertTrue(wait_for(lambda: (self.live.call(self.rc, "GET", "/live/%s/status" % rid)[1] or {}).get("segments", 0) >= n, 40))
        return rid

    def status(self, rid):
        return self.live.call(self.rc, "GET", "/live/%s/status" % rid)[1]

    def mark(self, rid, start, end, label=""):
        m, _ = self.ex.marks.apply("local", rid, {"op": "add", "start": LX.epoch_iso(start), "end": LX.epoch_iso(end), "label": label,
                                                  "url": self.src.url, "title": "テストの配信"})
        return m

    def job(self, jid):
        return next(j for j in self.ex.snapshot() if j["id"] == jid)

    def wait_state(self, jid, states, timeout=60):
        return wait_for(lambda: self.job(jid)["state"] in states and self.job(jid), timeout, 0.3)

    def test_mark_wait_export_transcribe_cancel(self):
        rid = self.start_rec()
        st = self.status(rid)
        first, last = LX.iso_epoch(st["firstPdt"]), LX.iso_epoch(st["lastPdt"])
        # 録画中: 終わりがまだ録れていない所までのマーク → 録画待ち → 届いたら書き出す
        a, b = first + 1.5, last + 3.0
        m = self.mark(rid, a, b, "見どころ: 1")
        j = self.ex.add("local", rid, m["id"], transcribe=True)
        self.assertEqual(j["state"], "wait")
        self.assertTrue(wait_for(lambda: "待っています" in (self.job(j["id"]).get("message") or "") or self.job(j["id"])["state"] != "wait", 10))
        done = self.wait_state(j["id"], ("done", "error"), 90)
        self.assertEqual(done["state"], "done", done)
        path = done["path"]
        self.assertTrue(os.path.isfile(path), path)
        self.assertEqual(os.path.dirname(os.path.dirname(path)), self.out)   # 書き出し先\<配信の名前>\
        self.assertEqual(os.path.basename(os.path.dirname(path)), "テストの配信")
        self.assertRegex(os.path.basename(path), r"^01_00h00m0\ds-00h00m\d\ds_見どころ_ 1\.mp4$")
        info = normalize.probe(path)
        self.assertTrue(normalize.is_30fps(info), info)
        self.assertAlmostEqual(info["duration"], b - a, delta=0.1)
        self.assertFalse([n for n in os.listdir(os.path.dirname(path)) if ".partial" in n])   # 書きかけは残さない
        clip, warn = schemas.load_clip_file(schemas.find_clip_path(path))
        self.assertIsNone(warn)
        self.assertEqual(clip["source"]["kind"], "live")
        self.assertIsNone(clip["source"]["url"])
        self.assertEqual((clip["source"]["live"]["recording"], clip["source"]["live"]["recorder"]), (rid, "local"))
        self.assertEqual(clip["source"]["live"]["start"], LX.epoch_iso(a))
        self.assertAlmostEqual(clip["range"]["start"], a - LX.iso_epoch(clip["source"]["live"]["base"]), delta=0.01)
        self.assertAlmostEqual(clip["range"]["end"] - clip["range"]["start"], b - a, delta=0.01)
        self.assertEqual((clip["mark"]["id"], clip["mark"]["label"], clip["export"]["mode"]), (m["id"], "見どころ: 1", "precise"))
        self.assertEqual(self.runner.files, [(path, os.path.splitext(os.path.basename(path))[0], "check")])   # 文字起こしへ(まとめて実行の文字起こしだけ)
        self.assertEqual(self.runner.streamers, [None])   # 配信者の名前が無い = まとめて実行が自動で決める
        self.assertEqual((done["runId"], done["after"], done["streamer"]), ("run-1", "check", ""))
        self.assertEqual(self.job(j["id"])["tx"]["state"], "queued")
        self.assertEqual([x["key"] for x in self.job(j["id"])["tx"]["steps"]], ["transcribe"])   # 段ごとの進み具合も(画面が全自動の進み具合を出す)
        self.assertFalse(os.listdir(os.path.join(self.tmp, "live", "work")))   # 取ったセグメントは片付ける
        # 文字起こしなし・同じマークをもう一度 → 別の名前
        j2 = self.ex.add("local", rid, m["id"], transcribe=False)
        d2 = self.wait_state(j2["id"], ("done", "error"), 90)
        self.assertEqual(d2["state"], "done", d2)
        self.assertNotEqual(d2["path"], path)
        self.assertEqual(len(self.runner.files), 1)
        self.assertEqual(d2["after"], "none")   # transcribe=False は「何もしない」
        # 全自動(文字起こし → パック)+ 配信者の名前(照らし合わせて渡す)
        j4 = self.ex.add("local", rid, m["id"], after="auto", streamer="ぺこら")
        d4 = self.wait_state(j4["id"], ("done", "error"), 90)
        self.assertEqual((d4["state"], d4["after"], d4["transcribe"], d4["streamer"]), ("done", "auto", True, "ぺこら"), d4)
        self.assertEqual(self.runner.files[-1][2], "auto")
        self.assertEqual(self.runner.streamers[-1], "兎田ぺこら")   # 色の一覧の名前にそろえて渡す
        self.assertIn("パック", d4["message"])
        # 色の一覧に合わない名前: 書き出しは止めず、色なし(None)で渡して知らせる
        j5 = self.ex.add("local", rid, m["id"], after="check", streamer="だれでもない人")
        d5 = self.wait_state(j5["id"], ("done", "error"), 90)
        self.assertEqual((d5["state"], self.runner.files[-1][2], self.runner.streamers[-1]), ("done", "check", None), d5)
        self.assertIn("字幕の色なし", d5["warning"])
        # 取り消し(録画待ちの間)
        far = self.mark(rid, last + 100, last + 110)
        j3 = self.ex.add("local", rid, far["id"])
        with self.assertRaises(LX.LiveError):
            self.ex.add("local", rid, far["id"])   # 同じマークは途中のものがあれば断る
        self.assertEqual(self.ex.cancel(j3["id"])["state"], "cancelled")
        # 記録は exports.json に残る(起動し直しても見える)
        again = LX.Exporter(self.live, os.path.join(self.tmp, "live"), lambda: self.out)
        self.assertEqual({x["id"]: x["state"] for x in again.jobs}, {j["id"]: "done", j2["id"]: "done", j3["id"]: "cancelled", j4["id"]: "done", j5["id"]: "done"})

    def test_pad_secs(self):
        """M8: 自動・アーカイブの採用の区間を前後 pad 秒だけ広げる。0 より前・録れている範囲(lastPdt)の外・1 つのマークの上限の外へは広げない"""
        first = 1_700_000_000.0
        st = lambda rel: {"lastPdt": LX.epoch_iso(first + rel)}
        self.assertEqual(LA.pad_secs(10.0, 20.0, 2, st(100), first), (8.0, 22.0))   # 本体は flow/live_adopt.py(RS7-2 G1b)
        self.assertEqual(LA.pad_secs(1.0, 20.0, 2, st(21), first), (0.0, 21.0))      # 頭は 0 まで・後ろは録れている所まで
        self.assertEqual(LA.pad_secs(10.0, 20.0, 2, st(19), first), (8.0, 20.0))     # 終わりがまだ録れていない = 後ろは足さない
        self.assertEqual(LA.pad_secs(10.0, 20.0, 1.5, {}, first), (8.5, 21.5))     # lastPdt が無ければ両側に
        self.assertEqual(LA.pad_secs(0.0, LX.MAX_MARK_SEC, 2, {}, first), (0.0, float(LX.MAX_MARK_SEC)))

    def test_adopt_server_side(self):
        """M1: POST /live/api/adopt の中身(Live.adopt)。画面なしで スタジオのマーク(採用)→ 正本 → 書き出し → スタジオのマークを「書き出し済み」。
        origin を .clip.json と live_feedback.jsonl に残す・同じ区間は二重に作らない・live.auto(M2)をまとめて実行へ渡す"""
        studio = FIX.FakeStudio()
        studio.conflicts = 1                                                  # 1 回目の保存は画面の保存とぶつかる → 読み直して入れる
        self.live.studio_call = studio
        FIX.patch_cfg(self.cfg, {"auto": {"after": "auto", "cut": "silence", "engine": "whisper.cpp", "model": "large-v3"}})
        rid = self.start_rec(8)
        first = LX.iso_epoch(self.status(rid)["firstPdt"])
        res = self.live.adopt({"recorder": "local", "recording": rid, "start": 1.04, "end": 4.0, "label": "自動の山", "origin": "auto"})
        self.assertEqual((res["video"], res["origin"], res["existing"]), (rid, "auto", False))
        j = res["job"]
        self.assertEqual((j["origin"], j["after"], j["auto"], j["studio"]["mark"], j["studio"]["start"]),
                         ("auto", "auto", {"cut": "silence", "engine": "whisper.cpp", "model": "large-v3"}, res["mark"], 0.0))   # 自動の採用は前後に余白 2 秒(M8。0 より前には広げない)。区間はスタジオが丸めた値
        v = studio.videos[rid]
        self.assertEqual([(m["status"], m["label"], m["start"], m["end"]) for m in v["marks"]], [("adopted", "自動の山", 0.0, 6.0)])   # 1.04 − 2 → 0・4 + 2 = 6(録画は 8 秒以上ある)
        d = self.wait_state(j["id"], ("done", "error"), 90)
        self.assertEqual(d["state"], "done", d)
        self.assertEqual(self.runner.files[-1][2], "auto")
        self.assertEqual(self.runner.kws[-1], {"cut": "silence", "engine": "whisper.cpp", "model": "large-v3"})   # M2: live.auto をまとめて実行へ
        self.assertTrue(wait_for(lambda: v["marks"][0]["status"] == "exported", 5))   # 入口が自分で「書き出し済み」にする(画面なし)
        self.assertEqual(os.path.normcase(v["marks"][0]["path"]), os.path.normcase(d["path"]))
        clip, _w = schemas.load_clip_file(schemas.find_clip_path(d["path"]))
        self.assertEqual((clip["source"]["live"]["origin"], clip["mark"]["src"]), ("auto", "auto"))
        self.assertAlmostEqual(LX.iso_epoch(clip["source"]["live"]["start"]) - first, 0.0, delta=0.01)   # 秒は録画の頭(firstPdt)から
        with open(os.path.join(self.tmp, "live", LX.FEEDBACK), encoding="utf-8") as f:
            fb = [json.loads(x) for x in f if x.strip()]
        self.assertEqual([(x["event"], x["origin"], x["human"], x["verdict"], x["jobId"]) for x in fb], [("adopt", "auto", False, None, j["id"])])   # 自動は「良い」に数えない
        # 同じ区間をもう一度(余白を足しても同じマーク)→ 済んでいるので新しく作らない(スタジオのマークも増やさない)
        again = self.live.adopt({"recorder": "local", "recording": rid, "start": 1.0, "end": 4.02, "origin": "auto"})
        self.assertEqual((again["existing"], again["job"]["id"], len(v["marks"])), (True, j["id"], 1))
        # 絶対時刻(UTC の文字列)でも頼める・人の採用(manual)は「良い」・after を指定すれば設定より優先
        m2 = self.live.adopt({"recorder": "local", "recording": rid, "start": LX.epoch_iso(first + 5.0), "end": LX.epoch_iso(first + 7.0), "after": "none"})
        self.assertEqual((m2["origin"], m2["job"]["after"], m2["job"]["studio"]["start"]), ("manual", "none", 5.0))
        self.assertEqual(self.wait_state(m2["job"]["id"], ("done", "error"), 90)["state"], "done")
        with open(os.path.join(self.tmp, "live", LX.FEEDBACK), encoding="utf-8") as f:
            self.assertEqual(json.loads(f.read().strip().splitlines()[-1])["verdict"], "good")
        for bad in ({"origin": "robot"}, {"start": 5.0, "end": 5.2}, {"start": -1, "end": 3}, {"start": "きのう", "end": 3}, {"start": True, "end": 3},
                    {"after": "all"}, {"recording": "../x"}):
            with self.assertRaises(LX.LiveError, msg=repr(bad)):
                self.live.adopt(dict({"recorder": "local", "recording": rid, "start": 10.0, "end": 12.0}, **bad))
        studio_down = lambda m, p, b=None: (None, {"message": "スタジオが動いていません"})
        self.live.studio_call = studio_down
        with self.assertRaises(LX.LiveError) as cm:
            self.live.adopt({"recorder": "local", "recording": rid, "start": 10.0, "end": 12.0})
        self.assertEqual(cm.exception.code, 502)

    def test_handoff_failure_is_collected(self):
        """M3: まとめて実行へ渡せなかった失敗が、LIVE の帯(ジョブの warning と failure)と「調子」(health の failures)に同じ文で出る"""
        self.runner.fail = "順番待ちが多すぎます(20本まで)"
        rid = self.start_rec()
        first = LX.iso_epoch(self.status(rid)["firstPdt"])
        m = self.mark(rid, first + 0.5, first + 2.5, "失敗する")
        j = self.ex.add("local", rid, m["id"], after="check")
        d = self.wait_state(j["id"], ("done", "error"), 90)
        self.assertEqual(d["state"], "done", d)
        f = d["failure"]
        self.assertEqual(f["kind"], "handoff")
        self.assertIn("文字起こしへ渡せませんでした: 順番待ちが多すぎます", f["text"])
        self.assertIn(os.path.basename(d["path"]), f["text"])
        self.assertIn(f["text"], d["warning"])                               # 帯は warning の行に出す(今の画面のまま)
        h = self.live.health()
        self.assertEqual([x["text"] for x in h["failures"]], [f["text"]])     # 「調子」に同じ文
        self.assertEqual(h["failures"][0]["jobId"], j["id"])

    def loud_of(self, path):
        """書き出した動画の聞こえ方の音量(LUFS)とピーク(dBTP)。ffmpeg の loudnorm で測るだけ"""
        r = subprocess.run([tools.find_tool("ffmpeg", "YTT_FFMPEG"), "-hide_banner", "-nostdin", "-i", path, "-vn", "-af", "loudnorm=print_format=json",
                            "-f", "null", "-"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return loudness.parse(r.stdout.decode("utf-8", "replace"))

    def test_audio_like_studio(self):
        """書き出しの音量はスタジオと同じ扱い: ラウドネスをそろえる(測って音声だけ作り直し・.clip.json に結果)/ 音量(%)/ 変えない。30fps・長さはそのまま"""
        rid = self.start_rec(10)
        first = LX.iso_epoch(self.status(rid)["firstPdt"])
        a, b = first + 1.0, first + 7.0
        m = self.mark(rid, a, b)

        def run(audio):
            self.audio = audio
            j = self.ex.add("local", rid, m["id"], transcribe=False)
            d = self.wait_state(j["id"], ("done", "error"), 90)
            self.assertEqual(d["state"], "done", d)
            info = normalize.probe(d["path"])
            self.assertTrue(normalize.is_30fps(info), info)
            self.assertAlmostEqual(info["duration"], b - a, delta=0.2)
            self.assertEqual(info["acodec"], "aac")
            self.assertFalse([n for n in os.listdir(os.path.dirname(d["path"])) if ".partial" in n or ".vol" in n])
            return d["path"], schemas.load_clip_file(schemas.find_clip_path(d["path"]))[0]["export"]
        p0, ex0 = run({"volume": 100, "loudness": None})
        self.assertEqual(ex0["volume"], 100)
        base_i, _tp = self.loud_of(p0)
        p1, ex1 = run({"volume": 50, "loudness": None})   # 50% = -6 dB
        self.assertEqual((ex1["volume"], "loudness" in ex1), (50, False))
        self.assertAlmostEqual(self.loud_of(p1)[0], base_i - 6.02, delta=0.6)
        p2, ex2 = run({"volume": 75, "loudness": -14.0})   # ラウドネスがあるときは音量(%)は使わない
        self.assertNotIn("volume", ex2)
        self.assertEqual(ex2["loudness"]["target"], -14.0)
        self.assertAlmostEqual(ex2["loudness"]["measured"], base_i, delta=0.6)   # 測った値 = そろえる前の聞こえ方
        self.assertAlmostEqual(ex2["loudness"]["gainDb"], -14.0 - base_i, delta=0.6)
        self.assertAlmostEqual(self.loud_of(p2)[0], -14.0, delta=1.0)             # そろった
        self.assertEqual(os.path.dirname(p0), os.path.dirname(p2))

    def test_cancel_while_encoding(self):
        rid = self.start_rec(12)
        st = self.status(rid)
        first = LX.iso_epoch(st["firstPdt"])
        m = self.mark(rid, first + 0.5, first + 10.0)
        real = normalize.encode_args
        with mock.patch.object(normalize, "encode_args", lambda *a, **k: [x if x != "veryfast" else "veryslow" for x in real(*a, **k)]):
            j = self.ex.add("local", rid, m["id"])
            self.assertTrue(self.wait_state(j["id"], ("encode", "done", "error"), 60))
            self.ex.cancel(j["id"])
            got = self.wait_state(j["id"], ("cancelled", "done", "error"), 30)
        self.assertEqual(got["state"], "cancelled", got)
        folder = os.path.join(self.out, "テストの配信")
        self.assertFalse([n for n in os.listdir(folder) if n.endswith(".mp4")] if os.path.isdir(folder) else [])   # 書きかけも残さない

    def test_recording_ended_and_recorder_down(self):
        rid = self.start_rec()
        self.live.call(self.rc, "POST", "/live/%s/stop" % rid, {}, timeout=40)
        st = self.status(rid)
        first, last = LX.iso_epoch(st["firstPdt"]), LX.iso_epoch(st["lastPdt"])
        # 録画が先に終わった: 録れた所までで切る
        m = self.mark(rid, first + 0.5, last + 20)
        j = self.ex.add("local", rid, m["id"], transcribe=False)
        d = self.wait_state(j["id"], ("done", "error"), 90)
        self.assertEqual(d["state"], "done", d)
        self.assertIn("録画の終わり", d["warning"])
        self.assertAlmostEqual(normalize.probe(d["path"])["duration"], last - (first + 0.5), delta=0.15)
        # 区間に録画が無い(録画より後)→ 失敗と理由
        m2 = self.mark(rid, last + 30, last + 40)
        j2 = self.ex.add("local", rid, m2["id"])
        d2 = self.wait_state(j2["id"], ("done", "error"), 30)
        self.assertEqual(d2["state"], "error")
        self.assertIn("届きませんでした", d2["error"])
        # 録画元が落ちた → 録画待ちのまま down_sec 秒 → 失敗と理由
        self.live.call(self.rc, "POST", "/live/quit", {})
        self.proc.wait(20)
        m3 = self.mark(rid, first + 1, first + 3)
        j3 = self.ex.add("local", rid, m3["id"])
        d3 = self.wait_state(j3["id"], ("done", "error"), 30)
        self.assertEqual(d3["state"], "error", d3)
        self.assertIn("つながりませんでした", d3["error"])


class ExportPiecesTest(unittest.TestCase):
    tearDownClass = ExportTest.tearDownClass   # lavfi の HLS(source)を片付ける

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-live-pieces-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_names_like_studio(self):
        self.assertEqual(LX.compact_ts(3725.9), "01h02m05s")
        self.assertEqual(LX.safe_name('a/b:c*?"<>|%d', 30), "a_b_c_d")
        self.assertEqual(LX.video_id_of("https://www.youtube.com/watch?v=abcdefghijk"), "abcdefghijk")
        self.assertEqual(LX.video_id_of("https://youtu.be/abcdefghij-"), "abcdefghij-")
        self.assertEqual(LX.video_id_of("https://www.youtube.com/@x/live", "20261004-000000-ab-defghijk"), "ab-defghijk")
        self.assertEqual(LX.video_id_of("http://127.0.0.1:1/live.m3u8", "20261004-000000-a1b2c3"), "")
        root = os.path.join(self.tmp, "out")
        os.makedirs(root)
        p1 = LX.pick_folder(root, "配信:1", "abcdefghijk")
        self.assertEqual(os.path.basename(p1), "配信_1")
        self.assertEqual(LX.pick_folder(root, "配信:1", "abcdefghijk"), p1)        # 同じ配信は同じフォルダ
        self.assertEqual(os.path.basename(LX.pick_folder(root, "配信:1", "live-x")), "配信_1_2")   # 同じ名前の別の配信とは混ぜない
        with open(os.path.join(p1, schemas.WORK_DIR, ".studio-id"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "abcdefghijk")   # スタジオと同じ持ち主の印
        open(os.path.join(p1, "01_x.mp4"), "wb").close()
        os.makedirs(os.path.join(p1, schemas.WORK_DIR), exist_ok=True)
        open(os.path.join(p1, schemas.WORK_DIR, "01_x_2_edit.mp4"), "wb").close()
        self.assertEqual(LX.unique_base("01_x", p1), "01_x_3")

    def test_restart_resets_running_jobs(self):
        folder = os.path.join(self.tmp, "live")
        os.makedirs(os.path.join(folder, "work", "lx-0123456789"))
        jobs_ = [{"id": "lx-0123456789", "state": "encode", "recorder": "local", "recording": "20261004-000000-a", "markId": "lm-0123456789"},
                 {"id": "lx-9876543210", "state": "done", "recorder": "local", "recording": "20261004-000000-a", "markId": "lm-0123456789"},
                 {"id": "bad", "state": "wait"}]
        fsio.write_json(os.path.join(folder, "exports.json"), {"schema": LX.JOBS_SCHEMA, "jobs": jobs_})
        ex = LX.Exporter(mock.Mock(), folder, lambda: self.tmp)
        self.assertEqual([(j["id"], j["state"]) for j in ex.jobs], [("lx-0123456789", "wait"), ("lx-9876543210", "done")])
        self.assertIn("やり直します", ex.jobs[0]["message"])
        self.assertFalse(os.path.exists(os.path.join(folder, "work")))   # 前回の取りかけは消す
        self.assertTrue(ex.pending())

    def test_encode_across_sessions(self):
        """繋ぎ直しをまたぐ(欠けは無い)区間: セッションごとのファイルを concat でつないで、区間の長さ・30/1 で書き出す"""
        src_dir, segs = source(60)
        folder = os.path.join(self.tmp, "live")
        ex = LX.Exporter(mock.Mock(), folder, lambda: os.path.join(self.tmp, "out"))
        wdir = os.path.join(folder, "work", "lx-0000000001")
        os.makedirs(wdir)
        files = []
        for k, part in enumerate((segs[2:5], segs[5:9])):
            p = os.path.join(wdir, "part_%02d.ts" % k)
            with open(p, "wb") as f:
                for name, _ in part:
                    with open(os.path.join(src_dir, name), "rb") as g:
                        f.write(g.read())
            files.append((p, "session_%03d" % (k + 1)))
        a = LX.iso_epoch("2026-10-04T06:00:00Z")
        seg_list = [{"uri": "session_001/seg_000000.ts", "session": "session_001", "pdt": LX.epoch_iso(a - 0.5), "dur": 1.0}]
        job = {"id": "lx-0000000001", "n": 3, "label": "", "recorder": "local", "recording": "20261004-000000-a"}
        d = {"url": "https://www.youtube.com/watch?v=abcdefghijk", "title": "またぐ", "firstPdt": LX.epoch_iso(a - 60)}
        out, tmp = ex._encode(job, {"id": "local"}, job["recording"], d, seg_list, files, a, a + 5.0, wdir)
        self.assertIsNone(tmp)
        self.assertTrue(normalize.is_30fps(out))
        self.assertAlmostEqual(out["duration"], 5.0, delta=0.1)
        self.assertEqual(os.path.basename(out["path"]), "03_00h01m00s-00h01m05s.mp4")   # 名前の時刻は録画の頭(firstPdt)からの秒
        self.assertEqual(os.path.basename(os.path.dirname(out["path"])), "またぐ")

    def _pieces_exporter(self, free, runner=None, slots=None):
        """録画元に繋がない Exporter(録画元の答えは _query を差し替える)。free: {"v": 空きのバイト数}"""
        live = mock.Mock()
        live.find.return_value = {"id": "local", "name": "この PC"}
        live.recorders.return_value = [{"id": "local", "name": "この PC"}]
        live.studio_call = None
        logs = []
        ex = LX.Exporter(live, os.path.join(self.tmp, "live"), lambda: os.path.join(self.tmp, "out"), runner=(lambda: runner) if runner else None,
                         log=logs.append, slots=slots, disk_usage=lambda p: (free["v"], 200 * LX.GB), disk_poll=0)
        ex.close()   # 見回りは止めて、ここで 1 本ずつ動かす
        ex._halt.clear()
        return ex, logs

    def test_disk_low_waits_then_resumes(self):
        """M4: 書き出し先・live\\work の空きが 5 GB 未満なら、新しい書き出しを「空き待ち」にして録画元にも問い合わせない。空くと続ける。
        書き出しが済んだあとの まとめて実行への受け渡しも空くまで待つ(済んだら渡す)。20 GB 未満は注意だけ。変わったときだけ記録する"""
        free = {"v": 3 * LX.GB}
        runner = FakeRunner()
        ex, logs = self._pieces_exporter(free, runner)
        rec = "20261004-000000-a"
        m, _ = ex.marks.apply("local", rec, {"op": "add", "start": "2026-10-04T06:00:00Z", "end": "2026-10-04T06:00:05Z"})
        ex.add("local", rec, m["id"], after="check")
        j = ex.jobs[0]
        ans = {"url": "https://www.youtube.com/watch?v=abcdefghijk", "state": "recording", "active": True, "lastPdt": "2026-10-04T06:10:00.000Z",
               "firstPdt": "2026-10-04T05:00:00.000Z", "segments": [], "gaps": []}
        with mock.patch.object(ex, "_query", return_value=(200, ans)) as q:
            self.assertIsNone(ex._next_ready())
            q.assert_not_called()                                            # 空き待ちの間は録画元に問い合わせない
            self.assertTrue(j["diskWait"])
            self.assertIn("空き容量が少ないので、新しい書き出し・文字起こしを止めて待っています", j["message"])
            self.assertIn("3.0 GB", j["message"])
            d = ex.disk()
            self.assertEqual((d["state"], d["lowBytes"], d["warnBytes"]), ("low", 5 * LX.GB, 20 * LX.GB))
            self.assertEqual(len(d["rows"]), 1)                              # 書き出し先と live\work は同じドライブ = 1 行
            self.assertIn("書き出し先・パック", d["rows"][0]["label"])
            self.assertIn("作業用", d["rows"][0]["label"])
            self.assertIs(ex._next_ready(), None)
            free["v"] = 12 * LX.GB                                           # 空いた(20 GB 未満 = 注意だけ)
            self.assertIs(ex._next_ready(), j)
            self.assertNotIn("diskWait", j)
        self.assertEqual(ex.disk()["state"], "warn")
        self.assertEqual(len([x for x in logs if "空き容量が少ない" in x]), 1)   # 変わったときだけ記録する
        self.assertTrue(any("20 GB を切りました" in x for x in logs), logs)
        # 書き出しが済んだが空きが少ない → まとめて実行へは渡さずに待つ → 空いたら渡す
        free["v"] = 1 * LX.GB
        media = os.path.join(self.tmp, "out", "01_x.mp4")
        os.makedirs(os.path.dirname(media))
        with open(media, "wb") as f:
            f.write(b"x")
        a, b = LX.iso_epoch(j["start"]), LX.iso_epoch(j["end"])
        ex._finish(j, {"id": "local"}, rec, ans, {"path": media, "duration": 5.0, "title": "配信"}, a, b)
        self.assertEqual((j["state"], j["handoffWait"], j["runId"], runner.files), ("done", "disk", "", []))
        self.assertIn("空き容量が少ないので、空くまで文字起こしへ渡すのを待っています", j["message"])
        self.assertIsNone(LX.live_failures.failure_of(j))                    # 待ちは失敗ではない
        self.assertTrue(ex.pending())                                        # 起動し直したら見回りが続ける
        self.assertEqual(ex._retry_handoffs(), 0)
        free["v"] = 30 * LX.GB
        self.assertEqual(ex._retry_handoffs(), 1)
        self.assertEqual((j["handoffWait"], j["runId"], runner.files[0][0], runner.files[0][2]), ("", "run-1", media, "check"))
        self.assertIn("文字起こしの順番に入れました", j["message"])
        self.assertFalse(ex.pending())
        self.assertEqual(ex.disk()["state"], "ok")
        again = LX.Exporter(mock.Mock(), os.path.join(self.tmp, "live"), lambda: os.path.join(self.tmp, "out"))   # 記録に残る
        self.assertEqual((again.jobs[0]["handoffWait"], again.jobs[0]["runId"]), ("", "run-1"))

    def test_hold_for_archive_then_release(self):
        """M7: holdFor archive のジョブは、書き出したあと まとめて実行へすぐ渡さず、本番版にしてから(release_hold)渡す。空きが少なければ空き待ちに"""
        free = {"v": 50 * LX.GB}
        runner = FakeRunner()
        ex, _logs = self._pieces_exporter(free, runner)
        rec = "20261004-000000-a"
        m, _ = ex.marks.apply("local", rec, {"op": "add", "start": "2026-10-04T06:00:00Z", "end": "2026-10-04T06:00:05Z"})
        ex.add("local", rec, m["id"], after="auto", hold="archive")

        j = ex.jobs[0]
        self.assertEqual(j["holdFor"], "archive")
        media = os.path.join(self.tmp, "out", "02_y.mp4")
        os.makedirs(os.path.dirname(media))
        with open(media, "wb") as f:
            f.write(b"x")
        ans = {"url": "https://www.youtube.com/watch?v=abcdefghijk", "firstPdt": "2026-10-04T05:00:00.000Z"}
        a, b = LX.iso_epoch(j["start"]), LX.iso_epoch(j["end"])
        ex._finish(j, {"id": "local"}, rec, ans, {"path": media, "duration": 5.0, "title": "配信"}, a, b)
        self.assertEqual((j["handoffWait"], runner.files), ("archive", []))
        self.assertIn("本番版に入れ替えてから、文字起こし → パックへ渡します", j["message"])
        self.assertFalse(ex.pending())                                       # 本番版の待ちは Archiver が受け持つ
        free["v"] = 1 * LX.GB
        self.assertEqual(ex.release_hold(j), "")                             # 空きが少ない → 空き待ちへ
        self.assertEqual(j["handoffWait"], "disk")
        self.assertEqual(ex.release_hold(j), "")                             # もう本番版の待ちではない
        free["v"] = 50 * LX.GB
        ex._retry_handoffs()
        self.assertEqual((j["handoffWait"], j["runId"], runner.files[-1][2]), ("", "run-1", "auto"))
        # アーカイブから作った本番版(欠けのマーク)はすぐ渡す
        j2 = dict(j, id="lx-00000000b2", handoffWait="", runId="")
        ex.jobs.append(j2)
        ex._finish(j2, {"id": "local"}, rec, ans, {"path": media, "duration": 5.0, "title": "配信"}, a, b, archive={"videoId": "abcdefghijk"})
        self.assertEqual((j2["handoffWait"], j2["runId"]), ("", "run-2"))

    def test_handoff_with_friend_request(self):
        """友人のライブ配信の依頼の録画(2-15): 書き出したら まとめて実行の start_file に 依頼 id・届け先・話者・トラック・カット(依頼のものが live.auto より先)と
        deliver_batch=1(1 本ずつ届ける)を渡す。ジョブの request は記録に残る(起動し直しても届け先が分かる)。依頼の無いジョブには渡さない"""
        free = {"v": 50 * LX.GB}
        runner = FakeRunner()
        ex, _logs = self._pieces_exporter(free, runner)
        rec = "20261004-000000-a"
        deliver = os.path.join(self.tmp, "Dropbox", "切り抜き依頼", "出力")
        req = {"rid": "20261008-200000-abc123", "deliverDir": deliver, "url": "https://www.youtube.com/watch?v=abcdefghijk", "title": "配信", "streamer": "兎田ぺこら",
               "speakers": {"count": 2, "names": ["兎田ぺこら", "宝鐘マリン"], "styles": {}}, "videoTracks": 2, "cut": "silence", "memo": "",
               "settings": dict(LR.SETTINGS_DEFAULT), "createdAt": 1.0}
        auto = {"cut": "none", "engine": "whisper.cpp", "model": "large-v3"}
        media = os.path.join(self.tmp, "out", "03_z.mp4")
        os.makedirs(os.path.dirname(media))
        with open(media, "wb") as f:
            f.write(b"x")
        ans = {"url": "https://www.youtube.com/watch?v=abcdefghijk", "firstPdt": "2026-10-04T05:00:00.000Z"}

        def run(start, request):
            m, _ = ex.marks.apply("local", rec, {"op": "add", "start": start, "end": start[:-3] + "05Z"})
            job = ex.add("local", rec, m["id"], after="auto", streamer="兎田ぺこら", auto=auto, request=request)
            j = next(x for x in ex.jobs if x["id"] == job["id"])
            ex._finish(j, {"id": "local"}, rec, ans, {"path": media, "duration": 5.0, "title": "配信"}, LX.iso_epoch(j["start"]), LX.iso_epoch(j["end"]))
            return j
        j = run("2026-10-04T06:00:00Z", req)
        self.assertEqual(j["request"], {"rid": req["rid"], "deliverDir": deliver, "speakers": req["speakers"], "videoTracks": 2, "cut": "silence"})   # 要るものだけ
        self.assertEqual((j["state"], j["runId"], j["handoffError"]), ("done", "run-1", ""))
        self.assertEqual((runner.files[-1][0], runner.files[-1][2], runner.streamers[-1]), (media, "auto", "兎田ぺこら"))
        self.assertEqual(runner.kws[-1], {"cut": "silence", "engine": "whisper.cpp", "model": "large-v3", "request_id": req["rid"], "deliver_dir": deliver,
                                          "speakers": req["speakers"], "video_tracks": 2, "deliver_batch": None, "pool": LX.deliver_pool(j, j["request"])})
        self.assertEqual(LX.deliver_pool(j, j["request"])["key"], "live|%s|local/%s" % (req["rid"], rec))   # 溜めは 依頼 × 段 × 録画(10-09 ユーザー決定)
        # 依頼にカットの指定が無ければ live.auto のカット・届け先が空なら None(まとめて実行が断る = 失敗として見える)
        j = run("2026-10-04T06:01:00Z", dict(req, cut=None, deliverDir="", speakers=None, videoTracks=None))
        self.assertEqual(runner.kws[-1], {"cut": "none", "engine": "whisper.cpp", "model": "large-v3", "request_id": req["rid"], "deliver_dir": None,
                                          "speakers": None, "video_tracks": None, "deliver_batch": None, "pool": LX.deliver_pool(j, j["request"])})
        # 依頼 id の無い request・依頼なし: 今までどおり(依頼の引数を渡さない)
        for k, bad in enumerate((dict(req, rid=""), None, "x")):
            j = run("2026-10-04T06:0%d:00Z" % (2 + k), bad)
            self.assertNotIn("request", j)
            self.assertEqual(runner.kws[-1], auto)
        self.assertEqual(len(runner.files), 5)
        again = LX.Exporter(mock.Mock(), os.path.join(self.tmp, "live"), lambda: os.path.join(self.tmp, "out"))   # 記録に残る
        self.assertEqual([x.get("request", {}).get("rid") for x in again.jobs][:2], [req["rid"], req["rid"]])

    def test_reserved_slot_while_recording(self):
        """M6: 録画中のライブの書き出しは用途つきの枠も使う = 文字起こし 2 本で上限が埋まっていても待たない。録画が終わったあとは普通の枠で待つ"""
        slots = jobs.HeavySlots(2)
        held = [slots.acquire("transcribe", "文字起こし 1"), slots.acquire("transcribe", "文字起こし 2")]
        free = {"v": 50 * LX.GB}
        ex, _logs = self._pieces_exporter(free, slots=slots)
        rec = "20261004-000000-a"
        seen = []

        def encode(job, rc, rec_, d, segs, files, a, b, wdir):
            seen.append(slots.snapshot())
            return {"path": os.path.join(self.tmp, "x.mp4"), "duration": b - a, "title": "t"}, None

        stack = contextlib.ExitStack()   # 待っている書き出しのスレッドが終わるまで、差し替えを戻さない
        self.addCleanup(stack.close)
        ans = {"active": True}
        stack.enter_context(mock.patch.object(ex, "_sources", side_effect=lambda job, a, b: [({"id": "local", "name": "この PC"}, rec, dict(ans))]))
        stack.enter_context(mock.patch.object(ex, "_fetch", return_value=[("part.ts", "session_001")]))
        stack.enter_context(mock.patch.object(ex, "_encode", side_effect=encode))
        stack.enter_context(mock.patch.object(ex, "_finish", side_effect=lambda job, *a, **k: ex._set(job, state="done")))

        def run(active):
            m, _ = ex.marks.apply("local", rec, {"op": "add", "start": "2026-10-04T06:00:00Z", "end": "2026-10-04T06:00:05Z"})
            job = ex.add("local", rec, m["id"], after="none")
            j = next(x for x in ex.jobs if x["id"] == job["id"])
            ans.clear()
            ans.update({"active": active, "firstPdt": "2026-10-04T05:00:00.000Z", "gaps": [],
                        "segments": [{"uri": "session_001/seg_000000.ts", "session": "session_001", "pdt": "2026-10-04T05:59:58.000Z", "dur": 8.0}]})
            t = threading.Thread(target=ex._process, args=(j,), daemon=True)
            t.start()
            t.join(1.0)
            return t, j
        t, j = run(True)
        self.assertFalse(t.is_alive())
        self.assertEqual(j["state"], "done", j)
        self.assertEqual(sorted((x["tool"], x.get("extra", False)) for x in seen[0]["active"]), [("live", True), ("transcribe", False), ("transcribe", False)])
        self.assertEqual([(x["tool"], x.get("extra", False)) for x in slots.snapshot()["active"]], [("transcribe", False), ("transcribe", False)])   # 枠は返した
        # 録画が終わったあと: 用途つきの枠は使わない(普通の枠が空くまで待つ)
        t, j = run(False)
        self.assertTrue(t.is_alive())
        self.assertIn("ほかの重い処理", j["message"])
        self.assertEqual(len(seen), 1)
        slots.release(held[0])
        t.join(5)
        self.assertFalse(t.is_alive())
        self.assertEqual(j["state"], "done")
        self.assertEqual(sorted((x["tool"], x.get("extra", False)) for x in seen[1]["active"]), [("live", False), ("transcribe", False)])
        slots.release(held[1])

    def test_reserved_slots_rules(self):
        """ytt.jobs の用途つきの枠(M6): 普通の枠が埋まっているときだけ・同じ用途の中では先に来た順・reserved を渡さない人は使えない・数は RESERVED"""
        self.assertEqual(jobs.RESERVED, {"live": 1})
        s = jobs.HeavySlots(1)
        a = s.acquire("transcribe")
        flag = []
        self.assertIsNone(s.acquire("live", cancelled=lambda: bool(flag.append(1)) or len(flag) > 2, poll=0.01))   # reserved なし = 待つ
        b = s.acquire("live", reserved=True)                                  # 用途つきの枠
        self.assertEqual([x.get("extra", False) for x in s.snapshot()["active"]], [False, True])
        flag.clear()
        self.assertIsNone(s.acquire("live", reserved=True, cancelled=lambda: bool(flag.append(1)) or len(flag) > 2, poll=0.01))   # 用途つきの枠は 1 つだけ
        flag.clear()
        self.assertIsNone(s.acquire("transcribe", reserved=True, cancelled=lambda: bool(flag.append(1)) or len(flag) > 2, poll=0.01))   # 用途の違う人は使えない
        s.release(b)
        got = []
        t = threading.Thread(target=lambda: got.append(s.acquire("transcribe", poll=0.01)))
        t.start()
        time.sleep(0.05)
        c = s.acquire("live", reserved=True, poll=0.01)                       # 前で待つ人がいても、用途つきの枠はすぐ使える
        self.assertIsNotNone(c)
        self.assertEqual(got, [])
        s.release(a)
        t.join(5)
        self.assertEqual(len(got), 1)                                          # 普通の枠は先に来た順のまま
        s.release(c)
        s.release(got[0])
        self.assertEqual(s.snapshot(), {"limit": 1, "active": [], "waiting": []})
        none = jobs.HeavySlots(1, reserved={})
        h = none.acquire("x")
        flag.clear()
        self.assertIsNone(none.acquire("live", reserved=True, cancelled=lambda: bool(flag.append(1)) or len(flag) > 2, poll=0.01))   # 枠を持たない
        none.release(h)

    def test_gap_means_needs_archive(self):
        """区間に欠け(繋ぎ直しの間)があれば、書き出さずに「要差し替え」"""
        folder = os.path.join(self.tmp, "live")
        live = mock.Mock()
        live.find.return_value = {"id": "local", "name": "この PC"}
        live.recorders.return_value = [{"id": "local", "name": "この PC"}]
        ex = LX.Exporter(live, folder, lambda: os.path.join(self.tmp, "out"))
        m, _ = ex.marks.apply("local", "20261004-000000-a", {"op": "add", "start": "2026-10-04T06:00:00Z", "end": "2026-10-04T06:00:20Z"})
        job = ex.add("local", "20261004-000000-a", m["id"])
        ex.close()   # 見回りは止めて、ここで1本だけ動かす
        ex._halt.clear()
        ans = {"url": "https://www.youtube.com/watch?v=abcdefghijk", "state": "recording", "active": True, "lastPdt": "2026-10-04T06:10:00.000Z",
               "firstPdt": "2026-10-04T05:00:00.000Z", "segments": [{"uri": "session_001/seg_000000.ts", "session": "session_001",
                                                                     "pdt": "2026-10-04T05:59:58.000Z", "dur": 4.0}],
               "gaps": [{"from": "2026-10-04T06:00:02.000Z", "to": "2026-10-04T06:00:12.000Z", "sec": 10.0}]}
        with mock.patch.object(ex, "_query", return_value=(200, ans)):
            j = ex.jobs[0]
            self.assertIs(ex._next_ready(), j)
            ex._process(j)
        self.assertEqual(j["state"], "error")
        self.assertTrue(j["needsArchive"])
        self.assertIn("要差し替え", j["error"])
        self.assertIn("06:00:02", j["error"])
        live.request.assert_not_called()   # 欠けのある録画は取りに行かない
        self.assertEqual(job["id"], j["id"])


if __name__ == "__main__":
    unittest.main()
