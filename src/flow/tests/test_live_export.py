# -*- coding: utf-8 -*-
"""マークと書き出し(線 D の P2。② の src/flow/live_export.py の Exporter)・採用(M1)・失敗の集約(M3。src/flow/live_failures.py)・ディスク・重い処理の枠のテスト。
入口 home の Live は使わず、ライブ係 flow/livesession.LiveSession(本物の録画の部品 --source direct・偽のまとめて実行・偽のスタジオ)で組む。

    py -3.12 -m unittest src/flow/tests/test_live_export.py

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
import urllib.request
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)

TESTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(TESTS))   # tests -> flow -> src
sys.path.insert(0, TESTS)
import _livefix as FIX  # noqa: E402
from ytt import testkit  # noqa: E402
from flow import board as Board  # noqa: E402
from flow import live_adopt as LA  # noqa: E402
from flow import live_export as LX  # noqa: E402
from flow import live_failures as LF  # noqa: E402
from flow import run as RunMod  # noqa: E402
from human.friend import live_requests as LR  # noqa: E402
from ytt import fsio, jobs, loudness, normalize, schemas, tools  # noqa: E402

TOKEN = FIX.TOKEN


def wait_for(fn, timeout=20.0, step=0.05):
    return FIX.wait_for(fn, timeout, step)


def handed(env, spec):
    """② の口 submit に渡った封筒 + 束 -> 動画ファイルの実行の引数の形 (動画, 題, flow, 配信者, kw)"""
    run = RunMod.Run.from_envelope(env, spec)
    kw = {k: getattr(run, k) for k in ("cut", "engine", "model") if getattr(run, k)}
    if run.request_id:
        kw.update(request_id=run.request_id, deliver_dir=run.deliver_dir, speakers=run.speakers, video_tracks=run.video_tracks,
                  pool=run.pool)
    return run.source_path, run.title, "auto" if run.mode == "file_auto" else "check", run.streamer, kw


class FakeRunner:
    """まとめて実行の代わり(文字起こしへ渡した動画を覚える)"""

    def __init__(self):
        self.files = []
        self.streamers = []   # submit に渡った配信者の名前(files と同じ順)
        self.accepts = []     # submit の accept(受付と同じ決め方)

    def submit(self, env, spec=None, accept=False):
        self.accepts.append(accept)
        self.envs = getattr(self, "envs", []) + [env]
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
        self.tmp = testkit.tempdir(self, "ytt-live-fail-")
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
        testkit.write_json(os.path.join(self.tmp, "live", "exports.json"), {"schema": LX.JOBS_SCHEMA, "jobs": jobs})

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
        self.fake.close()   # 一時フォルダは testkit.tempdir が後で消す

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


def clear_source():
    for d, _ in _SRC.values():
        shutil.rmtree(d, ignore_errors=True)
    _SRC.clear()


def source(seconds=60):
    if seconds not in _SRC:
        d = tempfile.mkdtemp(prefix="ytt-live-src-")
        _SRC[seconds] = (d, FIX.hls_fixture().make_source(d, seconds))
    return _SRC[seconds]


class ExportTest(unittest.TestCase):
    """本物の録画の部品(--source direct)で配信中のふりの HLS を録り、マーク → 書き出す。録画の部品はクラスで 1 回だけ起こし、
    テストごとに録画を始めて終わりに止める"""

    @classmethod
    def setUpClass(cls):
        cls.src_dir, cls.segs = source(60)
        cls.rec_tmp = tempfile.mkdtemp(prefix="ytt-live-recorder-")
        cls.port = FIX.free_port()
        cls.rdata = os.path.join(cls.rec_tmp, "recdata")
        cls.proc = subprocess.Popen([sys.executable, os.path.join(REPO, "pipeline", "ingest", "recorder.py"), "--port", str(cls.port), "--data-dir", cls.rdata,
                                     "--folder", os.path.join(cls.rec_tmp, "live-rec"), "--source", "direct", "--hls-time", "1", "--quiet"],
                                    env=dict(os.environ, PYTHONIOENCODING="utf-8"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        token_file = os.path.join(cls.rdata, "token.txt")
        if not wait_for(lambda: os.path.isfile(token_file), 20):
            cls.proc.kill()
            raise RuntimeError("録画の部品が起動しませんでした")
        time.sleep(0.2)
        with open(token_file, encoding="ascii") as f:
            cls.token = f.read().strip()

    @classmethod
    def tearDownClass(cls):
        try:
            if cls.proc.poll() is None:
                urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:%d/live/quit" % cls.port, data=b"{}", method="POST",
                                                              headers={"Authorization": "Bearer " + cls.token, "Content-Type": "application/json"}), timeout=10).read()
                cls.proc.wait(20)
        except Exception:
            cls.proc.kill()
        shutil.rmtree(cls.rec_tmp, ignore_errors=True)
        clear_source()

    def setUp(self):
        self.tmp = testkit.tempdir(self, "ytt-live-export-")
        self.src = FIX.hls_fixture().LiveServer(self.src_dir, self.segs, start=3, rate=1.0)
        self.src.end = False
        self.cfg = FIX.live_cfg(recorders=[{"id": "local", "name": "この PC", "url": "http://127.0.0.1:%d" % self.port, "token": self.token}])
        self.runner = FakeRunner()
        self.out = os.path.join(self.tmp, "out")
        self.audio = {"volume": 100, "loudness": None}   # 既定の書き出しは音量そのまま(音量の確認は test_audio_like_studio)
        self.live = FIX.new_session(self.tmp, self.cfg, root=REPO, out_dir=lambda: self.out, runner=lambda: self.runner, audio=lambda: self.audio)
        self.rc = self.live.find("local")
        self.assertTrue(wait_for(lambda: self.live.ping(self.rc), 20))
        self.ex = self.live.exporter
        self.ex.poll, self.ex.down_sec = 0.1, 3.0

    def tearDown(self):
        self.live.close()
        try:
            for r in (self.live.call(self.rc, "GET", "/live/list")[1] or {}).get("recordings") or []:
                if r.get("active"):
                    self.live.call(self.rc, "POST", "/live/%s/stop" % r["id"], {}, timeout=40)
        except Exception:
            pass
        self.src.close()   # 一時フォルダは testkit.tempdir が後で消す

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
        return wait_for(lambda: self.job(jid)["state"] in states and self.job(jid), timeout, 0.05)

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
        # 取り消し(録画待ちの間)
        far = self.mark(rid, last + 100, last + 110)
        j3 = self.ex.add("local", rid, far["id"])
        with self.assertRaises(LX.LiveError):
            self.ex.add("local", rid, far["id"])   # 同じマークは途中のものがあれば断る
        self.assertEqual(self.ex.cancel(j3["id"])["state"], "cancelled")
        # 記録は exports.json に残る(起動し直しても見える)
        again = LX.Exporter(self.live, os.path.join(self.tmp, "live"), lambda: self.out)
        self.assertEqual({x["id"]: x["state"] for x in again.jobs}, {j["id"]: "done", j2["id"]: "done", j3["id"]: "cancelled"})

    def test_adopt_server_side(self):
        """M1: POST /live/api/adopt の中身(Live.adopt)。画面なしで スタジオのマーク(採用)→ 正本 → 書き出し → スタジオのマークを「書き出し済み」。
        origin を .clip.json と live_feedback.jsonl に残す・同じ区間は二重に作らない・live.auto(M2)をまとめて実行へ渡す"""
        studio = FIX.FakeStudio()
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
        for bad in ({"start": True, "end": 3}, {"after": "all"}):   # 区間・録画の id・origin の悪い値は test_live_adopt.py
            with self.assertRaises(LX.LiveError, msg=repr(bad)):
                self.live.adopt(dict({"recorder": "local", "recording": rid, "start": 10.0, "end": 12.0}, **bad))
        studio_down = lambda m, p, b=None: (None, {"message": "スタジオが動いていません"})
        self.live.studio_call = studio_down
        with self.assertRaises(LX.LiveError) as cm:
            self.live.adopt({"recorder": "local", "recording": rid, "start": 10.0, "end": 12.0})
        self.assertEqual(cm.exception.code, 502)

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
        FIX.patch_cfg(self.cfg, {"recorders": [dict(self.rc, url="http://127.0.0.1:%d" % FIX.free_port())]})   # 閉じたポート = 落ちた録画元(self.rc は元のまま)
        m3 = self.mark(rid, first + 1, first + 3)
        j3 = self.ex.add("local", rid, m3["id"])
        d3 = self.wait_state(j3["id"], ("done", "error"), 30)
        self.assertEqual(d3["state"], "error", d3)
        self.assertIn("つながりませんでした", d3["error"])


class ExportPiecesTest(unittest.TestCase):
    tearDownClass = classmethod(lambda cls: clear_source())   # lavfi の HLS(source)を片付ける

    def setUp(self):
        self.tmp = testkit.tempdir(self, "ytt-live-pieces-")

    def media(self, name):
        """書き出し先(out)に書き出し済みの動画のふり(中身 1 バイト)を置く"""
        path = os.path.join(self.tmp, "out", name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        testkit.write_text(path, "x")
        return path

    def mark_job(self, ex, rec, start, end, **kw):
        """マークを足して書き出しのジョブに入れる -> ジョブ(記録の dict そのもの)"""
        m, _ = ex.marks.apply("local", rec, {"op": "add", "start": start, "end": end})
        job = ex.add("local", rec, m["id"], **kw)
        return next(x for x in ex.jobs if x["id"] == job["id"])

    def test_pad_secs(self):
        """M8: 自動・アーカイブの採用の区間を前後 pad 秒だけ広げる。0 より前・録れている範囲(lastPdt)の外・1 つのマークの上限の外へは広げない
        (録画の部品は使わない = 部品のクラスで)"""
        first = 1_700_000_000.0
        st = lambda rel: {"lastPdt": LX.epoch_iso(first + rel)}
        self.assertEqual(LA.pad_secs(10.0, 20.0, 2, st(100), first), (8.0, 22.0))   # 本体は flow/live_adopt.py
        self.assertEqual(LA.pad_secs(1.0, 20.0, 2, st(21), first), (0.0, 21.0))      # 頭は 0 まで・後ろは録れている所まで
        self.assertEqual(LA.pad_secs(10.0, 20.0, 2, st(19), first), (8.0, 20.0))     # 終わりがまだ録れていない = 後ろは足さない
        self.assertEqual(LA.pad_secs(10.0, 20.0, 1.5, {}, first), (8.5, 21.5))     # lastPdt が無ければ両側に
        self.assertEqual(LA.pad_secs(0.0, LX.MAX_MARK_SEC, 2, {}, first), (0.0, float(LX.MAX_MARK_SEC)))

    def test_pick_folder_owner_default(self):
        """配信の名前(題)が空のときの持ち主の既定名(規則の本体は ytt.names。ytt/tests/test_ytt_core.py の TestNames)"""
        root = os.path.join(self.tmp, "out")
        os.makedirs(root)
        self.assertEqual(os.path.basename(LX.pick_folder(root, "", "abcdefghijk")), "abcdefghijk")
        self.assertEqual(os.path.basename(LX.pick_folder(root, "", "")), "live")

    def test_board_follows_jobs(self):
        """掲示板: 状態が変わったら lx:<ジョブの id> がその state で載る・掲示板の id で取り消せる"""
        ex = LX.Exporter(mock.Mock(), os.path.join(self.tmp, "live"), lambda: self.tmp)
        ex.start = lambda: None   # 裏の糸は動かさない(状態は _set で進める)
        b = Board.Board()
        ex.attach_board(b)
        rec, mid, t = "20261004-000000-a", "lm-0123456789", 1790000000.0
        ex.marks.upsert("local", rec, mid, 1, LX.epoch_iso(t), LX.epoch_iso(t + 30), "大きな声")
        j1 = ex.add("local", rec, mid, transcribe=False)
        got = b.get("lx:" + j1["id"])
        self.assertEqual((got["kind"], got["state"], got["canCancel"], got["target"]["markId"]), ("live_export", "queued", True, mid))
        self.assertIn("大きな声", got["title"])
        ex._set(ex.jobs[0], state="encode", progress=0.5, message="30fps に作り直しています")
        got = b.get("lx:" + j1["id"])
        self.assertEqual((got["state"], got["progress"], got["phase"]), ("running", 0.5, "30fps に作り直しています"))
        media = os.path.join(self.tmp, "01_x.mp4")
        ex._set(ex.jobs[0], state="done", progress=1.0, path=media)
        got = b.get("lx:" + j1["id"])
        self.assertEqual((got["state"], got["target"]["path"], got["canCancel"]), ("done", media, False))
        self.assertIsNotNone(got["finishedAt"])
        j2 = ex.add("local", rec, mid, transcribe=False)
        self.assertEqual(b.cancel("lx:" + j2["id"])["state"], "cancelled")   # 録画待ちはすぐ取り消し
        self.assertEqual(ex.jobs[-1]["state"], "cancelled")
        with self.assertRaises(Board.NotFound):
            b.cancel("lx:lx-ffffffffff")
        b2 = Board.Board()
        LX.Exporter(mock.Mock(), os.path.join(self.tmp, "live"), lambda: self.tmp).attach_board(b2)   # 起動し直し: 記録のジョブも載る
        self.assertEqual([(j["id"], j["state"]) for j in b2.list()], [("lx:" + j1["id"], "done"), ("lx:" + j2["id"], "cancelled")])

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

    def test_encode_args_unchanged(self):
        """作り直しの ffmpeg の引数の列(区間・concat・古い ffmpeg の -vsync のやり直し)と concat の一覧"""
        folder = os.path.join(self.tmp, "live")
        ex = LX.Exporter(mock.Mock(), folder, lambda: os.path.join(self.tmp, "out"), ffmpeg="FF")
        wdir = os.path.join(folder, "work", "lx-0000000002")
        os.makedirs(wdir)
        a = LX.iso_epoch("2026-10-04T06:00:00Z")
        seg_list = [{"uri": "session_001/seg_000000.ts", "session": "session_001", "pdt": LX.epoch_iso(a - 2.25), "dur": 1.0}]
        job = {"id": "lx-0000000002", "n": 4, "label": "", "recorder": "local", "recording": "20261004-000000-a"}
        d = {"url": "https://www.youtube.com/watch?v=abcdefghijk", "title": "引数", "firstPdt": LX.epoch_iso(a - 60)}
        cmds, answers = [], []

        def run(job_, cmd, dur, flags):
            cmds.append(list(cmd))
            return answers.pop(0) if answers else (0, [], None)
        one = [(os.path.join(wdir, "part_00.ts"), "session_001")]
        two = one + [(os.path.join(wdir, "it's_01.ts"), "session_002")]
        with mock.patch.object(ex, "_run", side_effect=run), mock.patch.object(ex, "_adjust_audio", return_value={"volume": 100}), \
                mock.patch.object(LX.normalize, "verify", return_value={}), mock.patch.object(LX.fsio, "replace_retry"):
            ex._encode(job, {"id": "local"}, job["recording"], d, seg_list, one, a, a + 5.5, wdir)
            answers.append((1, ["Unrecognized option 'fps_mode'."], None))
            ex._encode(job, {"id": "local"}, job["recording"], d, seg_list, two, a, a + 5.5, wdir)
        head = ["FF", "-hide_banner", "-nostdin", "-y", "-v", "error", "-ss", "2.250", "-t", "6.500"]
        tail = ["-t", "5.500", "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn", "-vf", "fps=30", "-fps_mode", "cfr", "-c:v", "libx264",
                "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                "-progress", "pipe:1", "-nostats"]
        lst = os.path.join(wdir, "parts.txt")
        cat = head + ["-f", "concat", "-safe", "0", "-i", lst] + tail
        self.assertEqual(len(cmds), 3)
        self.assertEqual(cmds[0], head + ["-i", one[0][0]] + tail + [cmds[0][-1]])
        self.assertEqual(cmds[1], cat + [cmds[1][-1]])
        self.assertEqual(cmds[2], ["-vsync" if x == "-fps_mode" else x for x in cat] + [cmds[1][-1]])   # 5.1 より古い ffmpeg: 同じ書きかけへ 1 回だけ
        self.assertTrue(cmds[0][-1].endswith(".mp4") and os.path.dirname(cmds[0][-1]) == os.path.dirname(cmds[1][-1]), cmds[0][-1])
        with open(lst, encoding="utf-8") as f:
            self.assertEqual(f.read(), "file '%s'\nfile '%s'\n" % (one[0][0].replace("\\", "/"), two[1][0].replace("\\", "/").replace("'", "'\\''")))

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
        j = self.mark_job(ex, rec, "2026-10-04T06:00:00Z", "2026-10-04T06:00:05Z", after="check")
        ans ={"url": "https://www.youtube.com/watch?v=abcdefghijk", "state": "recording", "active": True, "lastPdt": "2026-10-04T06:10:00.000Z",
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
        media = self.media("01_x.mp4")
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

    def test_hold_for_archive(self):
        """M7(LD-1): hold archive のジョブは from archive の印で、録画からは書き出さない(_next_ready が飛ばす・pending に数えない = Archiver が受け持つ)。
        アーカイブから書き出したものはすぐ渡す"""
        free = {"v": 50 * LX.GB}
        runner = FakeRunner()
        ex, _logs = self._pieces_exporter(free, runner)
        rec = "20261004-000000-a"
        j = self.mark_job(ex, rec, "2026-10-04T06:00:00Z", "2026-10-04T06:00:05Z", after="auto", hold="archive")
        self.assertEqual((j["from"], j["state"], "holdFor" in j), ("archive", "wait", False))
        self.assertIn("アーカイブから書き出します", j["message"])
        self.assertFalse(ex.pending())                                       # アーカイブから書き出すのは Archiver が受け持つ
        self.assertIsNone(ex._next_ready())                                  # 録画元に聞かない
        self.assertEqual(ex.snapshot("local", rec)[0]["stateLabel"], "アーカイブ待ち")
        ans = {"url": "https://www.youtube.com/watch?v=abcdefghijk", "firstPdt": "2026-10-04T05:00:00.000Z"}
        a, b = LX.iso_epoch(j["start"]), LX.iso_epoch(j["end"])
        ex._finish(j, {"id": "local"}, rec, ans, {"path": self.media("02_y.mp4"), "duration": 5.0, "title": "配信"}, a, b, archive={"videoId": "abcdefghijk"})
        self.assertEqual((j["handoffWait"], j["runId"], j["state"], runner.files[-1][2]), ("", "run-1", "done", "auto"))   # アーカイブから書き出したものはすぐ渡す

    def test_streamer_name_and_handoff_failure(self):
        """書き出したあとの渡し方(_finish → まとめて実行): 配信者の名前は色の一覧にそろえて渡す・合わなければ色なし(None)で渡して知らせる(書き出しは止めない)。
        渡せなかった失敗は帯のジョブの warning と failure に集める(同じ文を「調子」にも出すのは FailuresTest)"""
        runner = FakeRunner()
        ex, _logs = self._pieces_exporter({"v": 50 * LX.GB}, runner)
        rec = "20261004-000000-a"
        ans = {"url": "https://www.youtube.com/watch?v=abcdefghijk", "firstPdt": "2026-10-04T05:00:00.000Z"}

        def finish(k, **kw):
            j = self.mark_job(ex, rec, "2026-10-04T06:0%d:00Z" % k, "2026-10-04T06:0%d:05Z" % k, **kw)
            ex._finish(j, {"id": "local"}, rec, ans, {"path": self.media("0%d_x.mp4" % k), "duration": 5.0, "title": "配信"}, LX.iso_epoch(j["start"]), LX.iso_epoch(j["end"]))
            return j
        j = finish(1, after="auto", streamer="ぺこら")   # 全自動(文字起こし → パック)
        self.assertEqual((j["state"], j["after"], j["transcribe"], j["streamer"]), ("done", "auto", True, "ぺこら"), j)
        self.assertEqual(runner.files[-1][2], "auto")
        self.assertEqual(runner.streamers[-1], "兎田ぺこら")   # 色の一覧の名前にそろえて渡す
        self.assertIn("パック", j["message"])
        j = finish(2, after="check", streamer="だれでもない人")
        self.assertEqual((j["state"], runner.files[-1][2], runner.streamers[-1]), ("done", "check", None), j)
        self.assertIn("字幕の色なし", j["warning"])
        runner.fail = "順番待ちが多すぎます(20本まで)"
        j = finish(3, after="check")
        self.assertEqual(j["state"], "done", j)
        row = next(x for x in ex.snapshot() if x["id"] == j["id"])
        f = row["failure"]
        self.assertEqual(f["kind"], "handoff")
        self.assertIn("文字起こしへ渡せませんでした: 順番待ちが多すぎます", f["text"])
        self.assertIn(os.path.basename(j["path"]), f["text"])
        self.assertIn(f["text"], row["warning"])   # 帯は warning の行に出す

    def test_handoff_with_friend_request(self):
        """友人のライブ配信の依頼の録画(2-15): 書き出したら まとめて実行の start_file に 依頼 id・届け先・話者・トラック・カット(依頼のものが live.auto より先)と
        溜めの指定を渡す。ジョブの request は記録に残る(起動し直しても届け先が分かる)。依頼の無いジョブには渡さない"""
        free = {"v": 50 * LX.GB}
        runner = FakeRunner()
        ex, _logs = self._pieces_exporter(free, runner)
        rec = "20261004-000000-a"
        deliver = os.path.join(self.tmp, "Dropbox", "切り抜き依頼", "出力")
        req = {"rid": "20261008-200000-abc123", "deliverDir": deliver, "url": "https://www.youtube.com/watch?v=abcdefghijk", "title": "配信", "streamer": "兎田ぺこら",
               "speakers": {"count": 2, "names": ["兎田ぺこら", "宝鐘マリン"], "styles": {}}, "videoTracks": 2, "cut": "silence",
               "settings": dict(LR.SETTINGS_DEFAULT), "createdAt": 1.0}
        auto = {"cut": "none", "engine": "whisper.cpp", "model": "large-v3"}
        media = self.media("03_z.mp4")
        ans = {"url": "https://www.youtube.com/watch?v=abcdefghijk", "firstPdt": "2026-10-04T05:00:00.000Z"}

        def run(start, request):
            j = self.mark_job(ex, rec, start, start[:-3] + "05Z", after="auto", streamer="兎田ぺこら", auto=auto, request=request)
            ex._finish(j, {"id": "local"}, rec, ans, {"path": media, "duration": 5.0, "title": "配信"}, LX.iso_epoch(j["start"]), LX.iso_epoch(j["end"]))
            return j
        j = run("2026-10-04T06:00:00Z", req)
        self.assertEqual(j["request"], {"rid": req["rid"], "deliverDir": deliver, "speakers": req["speakers"], "videoTracks": 2, "cut": "silence"})   # 要るものだけ
        self.assertEqual(runner.envs[-1]["deliver"]["origin"], "request")   # 出どころ(D-SEND 2-7): 友人の依頼
        self.assertEqual((j["state"], j["runId"], j["handoffError"]), ("done", "run-1", ""))
        self.assertEqual((runner.files[-1][0], runner.files[-1][2], runner.streamers[-1]), (media, "auto", "兎田ぺこら"))
        self.assertEqual(runner.kws[-1], {"cut": "silence", "engine": "whisper.cpp", "model": "large-v3", "request_id": req["rid"], "deliver_dir": deliver,
                                          "speakers": req["speakers"], "video_tracks": 2, "pool": LX.deliver_pool(j, j["request"])})
        self.assertEqual(LX.deliver_pool(j, j["request"])["key"], "live|%s|local/%s" % (req["rid"], rec))   # 溜めは 依頼 × 段 × 録画
        # 依頼にカットの指定が無ければ live.auto のカット・届け先が空なら None(まとめて実行が断る = 失敗として見える)
        j = run("2026-10-04T06:01:00Z", dict(req, cut=None, deliverDir="", speakers=None, videoTracks=None))
        self.assertEqual(runner.kws[-1], {"cut": "none", "engine": "whisper.cpp", "model": "large-v3", "request_id": req["rid"], "deliver_dir": None,
                                          "speakers": None, "video_tracks": None, "pool": LX.deliver_pool(j, j["request"])})
        # 依頼 id の無い request・依頼なし: 今までどおり(依頼の引数を渡さない)
        for k, bad in enumerate((dict(req, rid=""), None, "x")):
            j = run("2026-10-04T06:0%d:00Z" % (2 + k), bad)
            self.assertNotIn("request", j)
            self.assertEqual(runner.kws[-1], auto)
        self.assertEqual(len(runner.files), 5)
        run("2026-10-04T06:09:00Z", dict(req, autoDeliver=True))   # 自分の配信の自動の切り抜き(live.autoDeliver)= 出どころ auto(友人の札「依頼なし」)
        self.assertEqual(runner.envs[-1]["deliver"]["origin"], "auto")
        again = LX.Exporter(mock.Mock(), os.path.join(self.tmp, "live"), lambda: os.path.join(self.tmp, "out"))   # 記録に残る
        self.assertEqual([x.get("request", {}).get("rid") for x in again.jobs][:2], [req["rid"], req["rid"]])

    def test_margin_window_and_fallback(self):
        """LD-2f: 束の余白があれば前後に余白つきで取り(名前はマーク)・_finish に実際の始まり・終わり。余白の所に欠けがあればマークの区間だけで書き出す"""
        ex, _logs = self._pieces_exporter({"v": 50 * LX.GB})
        rec = "20261004-000000-a"
        got = {}

        def encode(job, rc, rec_, d, segs, files, a, b, wdir, mark=None):
            got.update(window=(a, b), mark=mark)
            return {"path": os.path.join(self.tmp, "x.mp4"), "duration": b - a, "title": "t"}, None

        def finish(job, *a, **k):
            got["span"] = k.get("clip_span")
            ex._set(job, state="done")
        gaps = {"pad": []}

        def sources(job, a, b):
            pad = b - a > 6
            return [({"id": "local", "name": "この PC"}, rec, {"active": False, "firstPdt": "2026-10-04T05:00:00.000Z", "gaps": gaps["pad"] if pad else [],
                     "segments": [{"uri": "session_001/seg_000000.ts", "session": "session_001", "pdt": "2026-10-04T05:59:40.000Z", "dur": 40.0}]})]
        with mock.patch.object(ex, "margin", return_value=10.0), mock.patch.object(ex, "_sources", side_effect=sources), \
                mock.patch.object(ex, "_fetch", return_value=[("part.ts", "session_001")]), \
                mock.patch.object(ex, "_encode", side_effect=encode), mock.patch.object(ex, "_finish", side_effect=finish):
            for k, gap in enumerate(([], [{"from": "2026-10-04T05:59:50.000Z", "to": "2026-10-04T05:59:55.000Z", "sec": 5}])):
                gaps["pad"] = gap
                j = self.mark_job(ex, rec, "2026-10-04T06:00:0%dZ" % k, "2026-10-04T06:00:0%dZ" % (k + 5), after="none")
                ex._process(j)
                a = LX.iso_epoch(j["start"])
                if not gap:
                    self.assertEqual((got["window"], got["mark"]), ((a - 10, a + 15), (a, a + 5)))
                    self.assertEqual(got["span"], (a - 10, a + 15))
                else:   # 余白の所に欠け = マークの区間だけ(今までと同じ呼び方)
                    self.assertEqual((got["window"], got["mark"], got["span"]), ((a, a + 5), None, None))
                self.assertEqual(j["state"], "done")

    def test_clip_marks(self):
        """LD-2f: 余白つきの動画の実際の始まり・終わりを、スタジオのマークの秒(clip_secs)と正本のマーク(clipFrom・clipTo)へ"""
        job = {"start": "2026-10-04T06:00:10.000Z", "end": "2026-10-04T06:00:40.000Z",
               "clip": {"from": "2026-10-04T06:00:00.000Z", "to": "2026-10-04T06:00:50.000Z"}}
        self.assertEqual(LX.clip_secs(job, {"start": 610.0, "end": 640.0}), (600.0, 650.0))
        self.assertEqual(LX.clip_secs(job, {"start": 5.0, "end": 35.0})[0], 0.0)   # 0 秒より前へは出さない
        self.assertIsNone(LX.clip_secs(dict(job, clip=None), {"start": 610.0, "end": 640.0}))
        ex, _logs = self._pieces_exporter({"v": 50 * LX.GB})
        rec = "20261004-000000-a"
        m, _ = ex.marks.apply("local", rec, {"op": "add", "start": job["start"], "end": job["end"]})
        self.assertTrue(ex.marks.mark_exported("local", rec, m["id"], "C:/x.mp4", clip=job["clip"]))
        got = ex.marks.get("local", rec, m["id"])
        self.assertEqual((got["clipFrom"], got["clipTo"], got["start"]), (job["clip"]["from"], job["clip"]["to"], job["start"]))   # マークの区間は変えない
        self.assertTrue(ex.marks.mark_exported("local", rec, m["id"], "C:/x.mp4"))
        self.assertNotIn("clipFrom", ex.marks.get("local", rec, m["id"]))

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
            j = self.mark_job(ex, rec, "2026-10-04T06:00:00Z", "2026-10-04T06:00:05Z", after="none")
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


class MarkStoreTest(unittest.TestCase):
    """マークの正本 MarkStore.apply(書き出しの API の入力): 押すたびに fsync して置き換える・値の検査・時刻は 3 桁の ms に丸める"""

    def test_apply(self):
        tmp = testkit.tempdir(self, "ytt-markstore-")
        ms = LX.MarkStore(os.path.join(tmp, "marks"))
        rec = "20261004-000000-a"
        m, _ = ms.apply("fake", rec, {"op": "add", "start": "2026-10-04T06:00:00.000Z", "url": "https://www.youtube.com/watch?v=abcdefghijk", "title": "配信<b>"})
        self.assertEqual((m["n"], m["start"], m["end"]), (1, "2026-10-04T06:00:00.000Z", None))
        with open(os.path.join(tmp, "marks", "fake__%s.json" % rec), encoding="utf-8") as f:   # 正本
            saved = json.load(f)
        self.assertEqual((saved["schema"], saved["title"], len(saved["marks"])), (LX.MARKS_SCHEMA, "配信<b>", 1))
        d = ms.load("fake", rec)
        self.assertEqual(([x["id"] for x in d["marks"]], d["title"]), ([m["id"]], "配信<b>"))
        for bad in ({"op": "update", "id": m["id"], "end": "2026-10-04T05:59:59.000Z"},     # 開始より前
                    {"op": "update", "id": m["id"], "end": "2026-10-04T07:00:01.000Z"},     # 1 時間を超える
                    {"op": "update", "id": m["id"], "end": "x"}, {"op": "add"}, {"op": "add", "start": "2026-13-01T00:00:00Z"},
                    {"op": "nope"}):
            with self.assertRaises(LX.LiveError, msg=repr(bad)) as cm:
                ms.apply("fake", rec, bad)
            self.assertEqual(cm.exception.code, 400, bad)
        with self.assertRaises(LX.LiveError) as cm:
            ms.apply("fake", rec, {"op": "update", "id": "lm-0000000000", "label": "x"})
        self.assertEqual(cm.exception.code, 404)
        with self.assertRaises(LX.LiveError):
            ms.apply("fake", "../x", {"op": "add", "start": m["start"]})
        m2, _ = ms.apply("fake", rec, {"op": "update", "id": m["id"], "end": "2026-10-04T06:00:30.5Z", "label": "見どころ\n"})
        self.assertEqual((m2["end"], m2["label"]), ("2026-10-04T06:00:30.500Z", "見どころ"))
        self.assertEqual(ms.apply("fake", rec, {"op": "delete", "id": m["id"]})[1], [])


class AudioCfgTest(unittest.TestCase):
    """書き出しの音量の設定が形の違う値・読めない値でも「変えない」(100 %・そろえない)になる"""

    def test_exporter_ignores_bad_audio(self):
        tmp = testkit.tempdir(self, "ytt-audiocfg-")
        for bad, want in ((None, (100, None)), ({"volume": 50, "loudness": None}, (50, None)), ({"volume": 75, "loudness": -14}, (75, -14.0)),
                          ({"volume": 999, "loudness": -3}, (100, None)), ("x", (100, None))):
            ex = LX.Exporter(mock.Mock(), os.path.join(tmp, "live"), lambda: tmp, audio=(lambda b=bad: b) if bad is not None else None)
            self.assertEqual(ex._audio_cfg(), want, bad)
        self.assertEqual(LX.Exporter(mock.Mock(), os.path.join(tmp, "live"), lambda: tmp, audio=mock.Mock(side_effect=OSError))._audio_cfg(), (100, None))


if __name__ == "__main__":
    unittest.main()
