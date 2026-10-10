# -*- coding: utf-8 -*-
"""配信中の盛り上がりの検出の ② の側 src/flow/live_detect.py(Detector)と、その上に載る自動の採用(M11)・配信ごとの記録・友人の依頼のテスト。
入口 home の Live は使わず、ライブ係 flow/livesession.LiveSession(偽の録画元・偽のスタジオ)で組む。ワーカーの中身は
src/pipeline/analyze/tests/test_live_excite_worker.py、設定(prefs)の検査と Live を通す振り分けは src/home/tests/test_live_detect_api.py。

    py -3.10 -m unittest src/flow/tests/test_live_detect.py

確かめること(ワーカーは起動しない。peaks.json・worker.json はテストが置く):
  - GET /live/api/peaks の中身(Detector.api_get。since の差分・series・重ねた決定・無い録画・形の悪い id)/ POST adopt・dismiss・restore
    (マークと decisions.json)/「調子」の detect の行と失敗(kind detect)/ ワーカーの起動・心拍が止まったら起動し直す・止める
  - M11: 確定から waitMin 後に 1 回だけ採用(origin auto・after auto・live_feedback の human false)・見送り・控えは採用しない・スタジオ不通は 5 回で諦めて失敗の文
  - D-13(1 録画の上限・未確認で休む)・D-14(終わったあとの採用)・D-12(配信ごとの記録)・0-10-6(アーカイブとの比べ)・config.json(スタジオの解析の設定)
  - 友人のライブ配信の依頼(docs/spec/friend-intake.md の 2-15): ホームの検出・自動採用がオフでも結びついた録画は動く・依頼の waitMin・pad で自動の採用
  - 配信中の候補の文字起こし(D-11 案 b。本体は test_live_tx.py): 候補の text・textAt・since の差分・応答の tx・採用の記録 live_feedback.jsonl の text
作業データはテストの一時フォルダだけ(YTT_DATA_DIR=inplace)。
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS)
import _livefix as LF  # noqa: E402
from flow import live_detect as D  # noqa: E402
from flow import live_export as LX  # noqa: E402
from pipeline.analyze import live_excite_worker as W  # noqa: E402
from ytt import fsio  # noqa: E402

TOKEN = "k" * 40
T0 = 1790000000.0
VID = "abcdefghijk"
REC = "20261007-200000-" + VID
URL = "https://www.youtube.com/watch?v=" + VID


def iso(t):
    return LX.epoch_iso(t)


class ListRecorder:
    """録画元の代わり(HTTP。合言葉): /live/list と /live/<録画>/status(録画の頭 firstPdt・ライブ端 lastPdt は rel で動かす)"""

    def __init__(self):
        self.rel = 0.0          # ライブ端 = 録画の頭からの秒
        self.active = True
        self.deleted = False
        owner = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _out(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.headers.get("Authorization") != "Bearer " + TOKEN:
                    return self._out(403, {"error": "token"})
                r = {"id": REC, "url": URL, "title": "テスト配信", "active": owner.active, "state": "recording" if owner.active else "ended",
                     "firstPdt": iso(T0), "lastPdt": iso(T0 + owner.rel), "endedAt": None}
                if self.path == "/live/list":
                    return self._out(200, {"recordings": [r]})
                if self.path.startswith("/live/%s/status" % REC):
                    return self._out(200, dict(r, segmentList=[]))
                return self._out(404, {"error": "not_found", "message": "なし"})

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(n)
                if self.headers.get("Authorization") != "Bearer " + TOKEN:
                    return self._out(403, {"error": "token"})
                if self.path == "/live/%s/delete" % REC:   # 録画を消す(src/manage/keep/live_cleanup.py)
                    owner.deleted = True
                    return self._out(200, {"ok": True, "deleted": REC})
                return self._out(404, {"error": "not_found", "message": "なし"})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def peak(pid, start, pk, score, state, confirmed, hour=0):
    return {"id": pid, "start": float(start), "end": float(start + 45), "peak": pk, "score": score, "parts": {"audio": 3.0, "chat": 2.0},
            "reasons": ["音量が急上昇"], "confirmedAt": confirmed, "hour": hour, "state": state, "endPending": False, "origin": None, "seq": 0}


class DetectApiTest(unittest.TestCase):
    """② の側(src/flow/live_detect.py。ライブ係 LiveSession で組む)。ワーカーは起動しない(peaks.json・worker.json はテストが置く)"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-detect-api-")
        self.rec = ListRecorder()
        self.cfg = LF.recorder_cfg(self.rec.url, TOKEN)
        self.logs = []
        self.live = LF.new_session(self.tmp, self.cfg, log=self.logs.append)
        self.studio = LF.FakeStudio()
        self.live.studio_call = self.studio
        self.live.exporter.start = lambda: None   # 書き出しは動かさない(ジョブは「録画待ち」のまま)
        self.det = self.live.detector
        self.folder = os.path.join(self.tmp, "live", "excite", "fake", REC)
        self.put_peaks([peak("p0-302", 272, 302, 12.0, "frame", 336), peak("p1-903", 870, 903, 9.0, "frame", 930),
                        peak("p2-1002", 973, 1002, 6.0, "bench", 1021)], seq=5,
                       changes=[[1, "p0-302", "frame"], [2, "p1-903", "frame"], [3, "p2-1002", "frame"], [4, "p2-1002", "bench"], [5, "p1-903", "frame"]])

    def tearDown(self):
        self.det.stop()
        self.rec.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def put_peaks(self, peaks, seq, changes, dec_n=0, **kw):
        doc = dict({"v": 1, "recorder": "fake", "recording": REC, "seq": seq, "decN": dec_n, "perHour": 6, "counts": {"0": 2}, "lag": 9, "chat": "ok",
                    "behindSec": 4.0, "at": iso(time.time()), "message": "", "peaks": peaks,
                    "changes": [{"seq": a, "id": b, "state": c} for a, b, c in changes]}, **kw)
        os.makedirs(self.folder, exist_ok=True)
        fsio.atomic_write(os.path.join(self.folder, "peaks.json"), json.dumps(doc).encode("utf-8"))

    def get(self, **q):
        return self.det.api_get({k: [str(v)] for k, v in dict({"recorder": "fake", "recording": REC}, **q).items()})

    def post(self, op, pid, **kw):
        return self.det.api_post(dict({"op": op, "recorder": "fake", "recording": REC, "id": pid}, **kw))

    def decisions(self):
        with open(os.path.join(self.folder, "decisions.json"), encoding="utf-8") as f:
            return json.load(f)

    def worker_alive(self):
        """M11 用: ワーカーが動いているふり(心拍 worker.json)と、偽の時計(waitMin は入口が候補を最初に見た時刻から数える)-> 時計の箱"""
        t = [time.time()]
        self.det.clock = lambda: t[0]
        self.det.stale_sec = 10 ** 9   # 時計を進めても心拍が古くならないように
        os.makedirs(self.det.dir, exist_ok=True)
        fsio.atomic_write(os.path.join(self.det.dir, "worker.json"), json.dumps({"v": 1, "pid": 99999, "at": iso(t[0]), "behindSec": 4.0, "memMB": 50.0, "chatRestarts": 0,
                                                                                   "recordings": [{"recorder": "fake", "id": REC, "behindSec": 4.0, "chat": "ok"}], "message": "1 本の録画を見ています", "error": ""}).encode("utf-8"))
        return t

    def test_get_full_since_and_series(self):
        with open(os.path.join(self.folder, "series.jsonl"), "w", encoding="utf-8") as f:
            for m in range(3):
                f.write(json.dumps({"t0": m * 60, "audio": [1.0] * 60, "chat": [0.5] * 60, "total": [float(m)] * 60, "full": [-30.0] * 60}) + "\n")
            f.write(json.dumps({"t0": 60, "audio": [2.0] * 60, "chat": [0.5] * 60, "total": [7.0] * 60}) + "\n")   # 同じ分を書き直した(後が勝つ)
        d = self.get()
        self.assertEqual((d["ok"], d["enabled"], d["seq"], [p["id"] for p in d["peaks"]], d["changes"]), (True, True, 5, ["p0-302", "p1-903", "p2-1002"], []))
        self.assertEqual(d["hour"], {"perHour": 6, "counts": {"0": 2}})
        self.assertEqual(d["autoAdopt"], {"enabled": True, "waitMin": 5})
        self.assertEqual((d["worker"]["running"], d["worker"]["chat"], d["worker"]["behindSec"], d["worker"]["lag"]), (False, "ok", 4.0, 9))
        self.assertEqual((d["series"]["n"], d["series"]["step"], d["series"]["total"][61], d["series"]["total"][150]), (180, 1.0, 7.0, 2.0))
        c = self.get(since=3)
        self.assertNotIn("peaks", c)
        self.assertNotIn("series", c)
        self.assertEqual([(x["seq"], x["id"], x["state"], x["peak"]["start"]) for x in c["changes"]], [(4, "p2-1002", "bench", 973.0), (5, "p1-903", "frame", 870.0)])
        self.assertEqual(self.get(since=5)["changes"], [])
        r = self.get(since=99)   # ワーカーが前の保存から戻った: 全部を取り直す
        self.assertTrue(r["reset"])
        self.assertEqual(len(r["peaks"]), 3)
        self.put_peaks([], seq=900, changes=[[k, "p0-302", "frame"] for k in range(401, 901)])
        self.assertTrue(self.get(since=10)["reset"])   # 古すぎる
        e = self.det.api_get({"recorder": ["fake"], "recording": ["20261007-210000-x"]})   # まだ候補の無い録画
        self.assertEqual((e["ok"], e["peaks"], e["changes"], e["seq"]), (True, [], [], 0))
        for q, code in (({"recorder": ["../x"], "recording": [REC]}, 400), ({"recorder": ["fake"], "recording": ["..x"]}, 400),
                        ({"recorder": ["nope"], "recording": [REC]}, 404), ({"recorder": ["fake"], "recording": [REC], "since": ["x"]}, 400)):
            with self.assertRaises(LX.LiveError, msg=repr(q)) as cm:
                self.det.api_get(q)
            self.assertEqual(cm.exception.code, code)

    def test_post_dismiss_restore_adopt(self):
        r = self.post("dismiss", "p2-1002")
        self.assertEqual((r["ok"], r["peak"]["state"], r["peak"]["pending"]), (True, "dismissed", True))
        self.assertEqual(self.post("dismiss", "p2-1002")["peak"]["state"], "dismissed")   # 二重に押しても 1 件
        self.assertEqual(self.decisions()["n"], 1)
        c = self.get(since=5)   # ワーカーが当てる前でも「変わった」として返す(ほかの窓にもすぐ出る)
        self.assertEqual([(x["id"], x["state"]) for x in c["changes"]], [("p2-1002", "dismissed")])
        self.assertEqual(self.post("restore", "p2-1002")["peak"]["state"], "bench")
        with self.assertRaises(LX.LiveError) as cm:   # 画面の after は Live.adopt が検査する
            self.post("adopt", "p0-302", after="all")
        self.assertEqual(cm.exception.code, 400)
        a = self.post("adopt", "p0-302", after="auto", streamer="テスト配信者")   # 帯の「書き出したあと」と配信者をそのまま M1 へ
        self.assertEqual((a["job"]["after"], a["job"].get("streamer")), ("auto", "テスト配信者"))
        v = self.studio.videos[REC]
        self.assertEqual([(m["status"], m["start"], m["end"]) for m in v["marks"]], [("adopted", 272.0, 317.0)])
        self.assertEqual((a["ok"], a["existing"], a["origin"], a["peak"]["state"], a["peak"]["origin"], a["peak"]["markId"], a["mark"]),
                         (True, False, "manual", "adopted", "manual", v["marks"][0]["id"], v["marks"][0]["id"]))
        self.assertEqual(a["job"]["origin"], "manual")
        dec = self.decisions()
        self.assertEqual([(x["n"], x["id"], x["state"], x.get("origin")) for x in dec["items"]],
                         [(1, "p2-1002", "dismissed", None), (2, "p2-1002", "restore", None), (3, "p0-302", "adopted", "manual")])
        self.assertEqual(dec["items"][-1]["jobId"], a["job"]["id"])
        again = self.post("adopt", "p0-302")   # 同じ候補をもう一度: 書き出しは二重に作らない・決定も増やさない
        self.assertEqual((again["existing"], again["job"]["id"], len(v["marks"]), self.decisions()["n"]), (True, a["job"]["id"], 1, 3))
        with self.assertRaises(LX.LiveError) as cm:
            self.post("dismiss", "p0-302")
        self.assertEqual(cm.exception.code, 409)
        with open(os.path.join(self.tmp, "live", LX.FEEDBACK), encoding="utf-8") as f:
            fb = [json.loads(x) for x in f]
        self.assertEqual([(x["origin"], x["human"]) for x in fb], [("manual", True)])
        # ワーカーが当てたら(decN)、重ねない
        self.put_peaks([dict(peak("p0-302", 272, 302, 12.0, "adopted", 336), origin="manual", markId=a["mark"])], seq=6, changes=[[6, "p0-302", "adopted"]], dec_n=3)
        self.assertNotIn("pending", self.get()["peaks"][0])
        for body, code in (({"op": "x"}, 400), ({"id": "../x"}, 400), ({"id": "p9-9"}, 404), ({"recording": "../x"}, 400), ({"recorder": "nope"}, 404)):
            with self.assertRaises(LX.LiveError, msg=repr(body)) as cm:
                self.det.api_post(dict({"op": "adopt", "recorder": "fake", "recording": REC, "id": "p0-302"}, **body))
            self.assertEqual(cm.exception.code, code, body)

    def test_auto_adopt_m11(self):
        """M11: 確定から waitMin 分たった枠の中の候補を 1 回だけ自動で採用(origin auto・after auto)。控え・見送りは採用しない"""
        LF.patch_cfg(self.cfg, {"autoAdopt": {"enabled": True, "waitMin": 5}})
        self.post("dismiss", "p1-903")
        self.rec.rel = 5000
        self.assertEqual(self.det.auto_tick(), 0)   # ワーカーが動いていない(心拍なし)間は採用しない
        t = self.worker_alive()
        self.assertEqual(self.det.auto_tick(), 0)   # 最初に見た(ここから waitMin を数える)
        t[0] += 299
        self.assertEqual(self.det.auto_tick(), 0)   # まだ 5 分たっていない
        t[0] += 1
        self.assertEqual(self.det.auto_tick(), 1)
        v = self.studio.videos[REC]
        self.assertEqual([(m["status"], m["start"], m["end"]) for m in v["marks"]], [("adopted", 270.0, 319.0)])   # 自動の採用は前後に余白 2 秒(M8。ホームの設定 live.auto.pad)
        dec = self.decisions()["items"][-1]
        self.assertEqual((dec["id"], dec["state"], dec["origin"]), ("p0-302", "adopted", "auto"))
        job = self.live.exporter.snapshot("fake", REC)[0]
        self.assertEqual((job["origin"], job["after"]), ("auto", "auto"))
        self.assertEqual(self.det.auto_tick(), 0)   # 1 回だけ
        self.rec.rel = 5000
        self.assertEqual(self.det.auto_tick(), 0)   # 見送った p1・控えの p2 は採用しない
        with open(os.path.join(self.tmp, "live", LX.FEEDBACK), encoding="utf-8") as f:
            fb = [json.loads(x) for x in f]
        self.assertEqual([(x["origin"], x["human"], x["verdict"]) for x in fb], [("auto", False, None)])   # 自動は「良い」に数えない
        LF.patch_cfg(self.cfg, {"autoAdopt": {"enabled": False}})
        self.put_peaks([peak("p3-4000", 3970, 4000, 9.0, "frame", 4010, hour=1)], seq=7, changes=[[7, "p3-4000", "frame"]])
        self.assertEqual(self.det.auto_tick(), 0)   # オフなら採用しない
        key = ("fake", REC, "p0-302")
        self.assertIn(key, self.det._seen)   # 「最初に見た時刻」は、見かけなくなって(採用した・録画が終わった)1 時間で消す = 増え続けない
        t[0] += D.SEEN_KEEP_SEC + 1
        self.det.auto_tick()
        self.assertNotIn(key, self.det._seen)
        self.assertNotIn(key, self.det._seen_at)

    def test_auto_adopt_retries_then_fails(self):
        """スタジオにつながらない(502)→ 見回りごとにやり直し、5 回で諦めて「調子」の失敗(kind detect)に出す"""
        LF.patch_cfg(self.cfg, {"autoAdopt": {"enabled": True, "waitMin": 1}})
        calls = []

        def down(method, path, body=None):
            calls.append(path)
            return None, {"message": "スタジオが動いていません"}
        self.live.studio_call = down
        self.rec.rel = 1000
        t = self.worker_alive()
        self.assertEqual(self.det.auto_tick(), 0)   # 最初に見た
        t[0] += 60
        for i in range(D.AUTO_TRIES):
            self.assertEqual(self.det.auto_tick(), 0)
            self.assertEqual(self.det.failures() != [], i == D.AUTO_TRIES - 1, i)
        n = len(calls)
        self.det.auto_tick()
        self.assertEqual(len([c for c in calls[n:] if c == "/api/videos/open"]), 0)   # 諦めた候補はもう試さない
        f = [x for x in self.live.health()["failures"] if x["kind"] == "detect"]
        self.assertEqual(len(f), 2, f)   # p0・p1(どちらも枠の中で 1 分たった)
        self.assertIn("自動で採用できませんでした", f[0]["text"])
        self.assertEqual(f[0]["kindLabel"], "盛り上がりの検出")
        det2 = D.Detector(self.live, spawn=False, clock=lambda: t[0])   # 入口を起動し直しても、諦めた候補は試さない(auto_failures.json)
        det2.stale_sec = 10 ** 9
        self.live.studio_call = self.studio
        self.assertEqual(det2.auto_tick(), 0)   # 最初に見た
        t[0] += 60
        self.assertEqual(det2.auto_tick(), 0)   # 待ちが過ぎても試さない

    def test_live_tx_text_on_peaks_and_feedback(self):
        """D-11 案 b(src/flow/live_tx.py): 文字の付いた候補は GET の候補に text・textAt。付けてから RECENT_SEC の間は since の差分(changes)にも入る
        (画面の行に文字が出る)。応答に tx(LiveTx.status)。採用(人・自動)の記録 live_feedback.jsonl に text。失敗の記録は出さない"""
        from flow import live_tx as TX
        tx = self.live.livetx
        t = [time.time()]
        tx.clock = lambda: t[0]
        d = self.get()
        self.assertTrue({"enabled", "ready", "message", "model", "busy", "queued", "done", "failed", "pausedUntil"} <= set(d["tx"]), d["tx"])
        self.assertEqual((d["tx"]["enabled"], d["tx"]["model"]), (True, "large-v3"))
        self.assertFalse(any("text" in p for p in d["peaks"]))
        self.assertEqual(self.get(since=5)["changes"], [])
        tx.record("fake", REC, "p1-903", "\tここで大きな声\n")
        tx._record_error("fake", REC, "p2-1002", "GPU(Vulkan)を使えませんでした")   # 失敗の記録は候補に出さない
        d = self.get()
        by = {p["id"]: p for p in d["peaks"]}
        self.assertEqual(by["p1-903"]["text"], "\tここで大きな声\n")
        self.assertEqual(by["p1-903"]["textAt"], tx.view("fake", REC)["p1-903"]["at"])
        self.assertFalse("text" in by["p0-302"] or "text" in by["p2-1002"] or "textAt" in by["p2-1002"])
        c = self.get(since=5)   # ワーカーの seq は進んでいないが、文字が付いた候補は差分に入る(今の形 = text つき)
        self.assertEqual([(x["seq"], x["id"], x["state"], x["peak"].get("text")) for x in c["changes"]], [(5, "p1-903", "frame", "\tここで大きな声\n")])
        self.assertEqual([x["id"] for x in self.get(since=3)["changes"]], ["p2-1002", "p1-903"], "ワーカーの変更と重なっても 1 回")
        t[0] += TX.RECENT_SEC + 1
        self.assertEqual(self.get(since=5)["changes"], [], "古くなったら差分には入れない")
        self.assertEqual({p["id"]: p.get("text") for p in self.get()["peaks"]}["p1-903"], "\tここで大きな声\n", "全部の答えには残る")
        a = self.post("adopt", "p1-903")   # 人の採用
        self.assertEqual((a["ok"], a["origin"]), (True, "manual"))
        self.post("adopt", "p0-302")   # 文字の無い候補
        with open(os.path.join(self.tmp, "live", LX.FEEDBACK), encoding="utf-8") as f:
            fb = [json.loads(x) for x in f]
        self.assertEqual([(x["event"], x["origin"], x.get("text")) for x in fb], [("adopt", "manual", "ここで大きな声"), ("adopt", "manual", None)],
                         "採用の記録に文字(制御文字は空白・前後の空白は除く)。文字の無い候補は text なし")
        self.assertEqual(fb[0]["studio"]["mark"], a["mark"])
        self.assertNotIn("text", fb[1])
        self.assertEqual(tx.text_for("fake", REC, "p2-1002"), None)

    def test_auto_adopt_keeps_live_tx_text(self):
        """M11 の自動の採用も、配信中の文字起こしの文字を live_feedback.jsonl に残す(human false)"""
        LF.patch_cfg(self.cfg, {"autoAdopt": {"enabled": True, "waitMin": 1}})
        self.live.livetx.record("fake", REC, "p0-302", "自動で採用した候補の文字")
        self.rec.rel = 5000
        t = self.worker_alive()
        self.assertEqual(self.det.auto_tick(), 0)   # 最初に見た
        t[0] += 61
        self.assertEqual(self.det.auto_tick(), 2)   # 枠の p0・p1
        with open(os.path.join(self.tmp, "live", LX.FEEDBACK), encoding="utf-8") as f:
            fb = {x["start"]: x for x in (json.loads(y) for y in f)}
        self.assertEqual([(x["origin"], x["human"], x.get("text")) for _s, x in sorted(fb.items())],
                         [("auto", False, "自動で採用した候補の文字"), ("auto", False, None)])

    def test_adopt_passes_score(self):
        """採用(人・自動)で候補の点数が書き出しのジョブに残る(.clip.json の source.live.score → M9 の一覧)"""
        r = self.post("adopt", "p0-302")
        self.assertEqual(r["ok"], True)
        job = self.live.exporter.snapshot("fake", REC)[0]
        self.assertEqual((job["origin"], job.get("score")), ("manual", 12.0))

    def test_health_row_and_failures(self):
        hb = {"v": 1, "pid": 99999, "at": iso(time.time()), "behindSec": 12.5, "memMB": 80.0, "chatRestarts": 2,
              "recordings": [{"recorder": "fake", "id": REC, "behindSec": 12.5, "chat": "ok"}], "message": "1 本の録画を見ています", "error": ""}
        os.makedirs(self.det.dir, exist_ok=True)
        fsio.atomic_write(os.path.join(self.det.dir, "worker.json"), json.dumps(hb).encode("utf-8"))
        h = self.live.health()["detect"]
        self.assertEqual((h["running"], h["behindSec"], h["memMB"], h["restarts"], h["chat"], h["chatRestarts"]), (True, 12.5, 80.0, 0, "ok", 2))
        self.assertEqual(h["recordings"], [{"recorder": "fake", "id": REC, "peaks": 2, "lag": 9, "chat": "ok", "behindSec": 4.0, "auto": 0, "autoCapped": False}])
        self.assertEqual(self.det.failures(), [])
        hb.update(error="ffmpeg が見つかりません(setup の install.bat で入れてください)", at=iso(time.time() - 600))
        fsio.atomic_write(os.path.join(self.det.dir, "worker.json"), json.dumps(hb).encode("utf-8"))
        self.assertFalse(self.live.health()["detect"]["running"])   # 心拍が止まっている
        self.det.restarts = D.RESTART_WARN + 1
        texts = [x["text"] for x in self.live.health()["failures"] if x["kind"] == "detect"]
        self.assertEqual(len(texts), 2, texts)
        self.assertTrue(any("ffmpeg が見つかりません" in t for t in texts))
        self.assertTrue(any("%d 回起動し直しました" % (D.RESTART_WARN + 1) in t for t in texts))
        LF.patch_cfg(self.cfg, {"detect": {"enabled": False}})
        self.assertIsNone(self.live.health()["detect"])
        self.assertEqual(self.det.failures(), [])

    def peaks3(self):
        return [peak("p0-302", 272, 302, 12.0, "frame", 336), peak("p1-903", 870, 903, 9.0, "frame", 930), peak("p2-1002", 973, 1002, 6.0, "bench", 1021)]

    def test_d13_auto_cap_per_recording(self):
        """D-13: 1 つの録画の自動の採用は AUTO_MAX_PER_REC 本まで(残りの候補は帯に残る = 人が採用できる)。「調子」の行に auto・autoCapped"""
        LF.patch_cfg(self.cfg, {"autoAdopt": {"enabled": True, "waitMin": 1}})
        pks = [peak("p%d-%d" % (i, 100 + i * 200), 70 + i * 200, 100 + i * 200, 10.0 - i * 0.1, "frame", 130 + i * 200) for i in range(D.AUTO_MAX_PER_REC + 2)]
        self.put_peaks(pks, seq=1, changes=[])
        self.rec.rel = 9000
        t = self.worker_alive()
        self.assertEqual(self.det.auto_tick(), 0)
        t[0] += 61
        self.assertEqual(self.det.auto_tick(), D.AUTO_MAX_PER_REC)
        self.assertEqual(self.det.auto_count("fake", REC), D.AUTO_MAX_PER_REC)
        self.assertEqual(self.det.auto_tick(), 0)   # 上限: 残りの 2 本は採用しない
        self.assertEqual(sum(1 for m in self.logs if "上限の %d 本" % D.AUTO_MAX_PER_REC in m), 1)
        self.det.auto_tick()
        self.assertEqual(sum(1 for m in self.logs if "上限の %d 本" % D.AUTO_MAX_PER_REC in m), 1)   # 記録は 1 回
        h = self.live.health()["detect"]
        self.assertEqual((h["recordings"][0]["auto"], h["recordings"][0]["autoCapped"], h["autoAdopt"]["maxPerRecording"], h["autoAdopt"]["pauseUnconfirmed"]),
                         (D.AUTO_MAX_PER_REC, True, D.AUTO_MAX_PER_REC, D.UNCONFIRMED_PAUSE))
        a = self.post("adopt", pks[-1]["id"])   # 人の採用は上限に関係なく通る
        self.assertEqual((a["ok"], self.decisions()["items"][-1]["origin"]), (True, "manual"))
        self.assertEqual(self.det.auto_count("fake", REC), D.AUTO_MAX_PER_REC)   # 人の採用は数えない

    def test_d13_pause_when_unconfirmed(self):
        """D-13: ホームの未確認の自動の切り抜きが UNCONFIRMED_PAUSE 本以上なら、依頼の無い録画の自動の採用を休む(「調子」に理由・記録は 1 回)。
        数は UNCONFIRMED_EVERY 秒ごとに聞き直す。友人の依頼の録画は休まない。数えられなければ休まない(記録に 1 回)"""
        LF.patch_cfg(self.cfg, {"autoAdopt": {"enabled": True, "waitMin": 1}})
        n = [D.UNCONFIRMED_PAUSE]
        self.live.unconfirmed = lambda: n[0]
        self.rec.rel = 5000
        t = self.worker_alive()
        self.assertEqual(self.det.auto_tick(), 0)
        t[0] += 61
        self.assertEqual(self.det.auto_tick(), 0)   # 休む
        self.assertIn("自動の採用を休んでいます", self.live.health()["detect"]["autoAdopt"]["paused"])
        self.det.auto_tick()
        self.assertEqual(sum(1 for m in self.logs if "休んでいます" in m), 1)
        n[0] = D.UNCONFIRMED_PAUSE - 1
        self.assertEqual(self.det.auto_tick(), 0)   # UNCONFIRMED_EVERY 秒は前の数のまま
        t[0] += D.UNCONFIRMED_EVERY + 1
        self.assertEqual(self.det.auto_tick(), 0)   # 休みが明けた: ここから待ちを数える(休んでいる間は「最初に見た」にしない)
        self.assertEqual(self.live.health()["detect"]["autoAdopt"]["paused"], "")
        t[0] += 61
        self.assertEqual(self.det.auto_tick(), 2)   # p0・p1
        # 友人の依頼の録画は、休んでいても採用する
        n[0] = D.UNCONFIRMED_PAUSE + 5
        t[0] += D.UNCONFIRMED_EVERY + 1
        self.put_peaks(self.peaks3() + [peak("p3-4000", 3970, 4000, 9.0, "frame", 4010, hour=1)], seq=7, changes=[])   # p0・p1 は決定(adopted)を重ねて見える
        self.assertEqual(self.det.auto_tick(), 0)
        t[0] += 61
        self.assertEqual(self.det.auto_tick(), 0)   # 休んでいる
        self.live.requests.put("fake", REC, {"rid": "20261008-200000-abc123", "deliverDir": self.tmp, "settings": {"waitMin": 1}})
        self.assertEqual(self.det.auto_tick(), 0)   # 依頼の録画になった: ここから待ちを数える
        t[0] += 61
        self.assertEqual(self.det.auto_tick(), 1)   # p3(依頼の録画)
        self.live.requests.remove("fake", REC)

        def boom():
            raise RuntimeError("x")
        self.live.unconfirmed = boom   # 数えられない → 休まない
        t[0] += D.UNCONFIRMED_EVERY + 1
        self.assertEqual(self.det.paused_why(), "")
        self.assertEqual(sum(1 for m in self.logs if "安全弁は効きません" in m), 1)
        t[0] += D.UNCONFIRMED_EVERY + 1
        self.assertEqual(self.det.paused_why(), "")
        self.assertEqual(sum(1 for m in self.logs if "安全弁は効きません" in m), 1)

    def test_d14_adopt_after_end(self):
        """D-14: 録画が終わっても、ワーカーが帳簿を締めた(peaks.json の ended)あと END_GRACE_SEC の間は、待ち中だった候補を同じ待ちで採用する。
        締める前・終わって END_GRACE_SEC より古い録画は採用しない"""
        LF.patch_cfg(self.cfg, {"autoAdopt": {"enabled": True, "waitMin": 1}})
        t = self.worker_alive()
        self.rec.rel = t[0] - T0 - 100   # ライブ端 = 100 秒前に終わった
        self.rec.active = False
        self.assertEqual(self.det.auto_tick(), 0)   # 締める前
        t[0] += 61
        self.assertEqual(self.det.auto_tick(), 0)
        self.put_peaks(self.peaks3(), seq=6, changes=[], ended=True)
        self.assertEqual(self.det.auto_tick(), 0)   # 最初に見た(締めてから待ちを数える)
        t[0] += 61
        self.assertEqual(self.det.auto_tick(), 2)   # p0・p1(控え p2 は採用しない)
        self.assertEqual([x["origin"] for x in self.decisions()["items"]], ["auto", "auto"])
        self.rec.rel = t[0] - T0 - D.END_GRACE_SEC - 10   # 古い録画は採用しない
        self.put_peaks([peak("p5-7000", 6970, 7000, 9.0, "frame", 7010)], seq=7, changes=[], ended=True, dec_n=2)
        for _ in range(2):
            t[0] += 61
            self.assertEqual(self.det.auto_tick(), 0)

    def test_report_d12(self):
        """D-12: 配信ごとの結果の記録(src/flow/live_report.py)。録画中は EVERY 秒ごとに書き直し(最大値を残す)、終わって締めたら最後に 1 回(state done)"""
        from flow import live_report as R
        rp = self.live.reporter
        t = self.worker_alive()
        rp.clock = lambda: t[0]
        self.rec.rel = t[0] - T0 - 100
        self.live.livetx.record("fake", REC, "p0-302", "文字", sec=3.0)
        self.live.livetx._record_error("fake", REC, "p1-903", "だめ")
        self.post("adopt", "p0-302")
        self.assertEqual(rp.tick(), 1)
        d = rp.load("fake", REC)
        self.assertEqual((d["state"], d["recorder"], d["recording"], d["info"]["title"], d["info"]["hours"] > 1, d["finishedAt"]), ("recording", "fake", REC, "テスト配信", True, None))
        s = d["samples"]
        self.assertEqual((s["ticks"], s["behindMax"], s["memMaxMB"], s["lagMax"], s["chat"], s["restarts"]), (1, 4.0, 50.0, 9, "ok", 0))
        self.assertEqual({k: d["detect"][k] for k in ("frame", "bench", "adopted", "adoptedAuto", "adoptedManual", "givenUp", "ended")},
                         {"frame": 1, "bench": 1, "adopted": 1, "adoptedAuto": 0, "adoptedManual": 1, "givenUp": 0, "ended": False})
        self.assertEqual({k: d["tx"][k] for k in ("ok", "error", "empty", "pending", "secMedian")}, {"ok": 1, "error": 1, "empty": 0, "pending": 1, "secMedian": 3.0})
        self.assertEqual((d["exports"]["total"], d["exports"]["byState"], d["exports"]["origins"], d["exports"]["failures"]), (1, {"wait": 1}, {"manual": 1}, 0))
        self.assertEqual((d["disk"]["state"], d["request"]), ("ok", None))
        self.assertEqual(rp.tick(), 0)   # EVERY 秒は書き直さない
        fsio.atomic_write(os.path.join(self.det.dir, "worker.json"), json.dumps({"v": 1, "pid": 99999, "at": iso(t[0]), "behindSec": 1.0, "memMB": 120.0, "chatRestarts": 1,
                                                                                   "recordings": [{"recorder": "fake", "id": REC, "behindSec": 1.0, "chat": "restarting"}],
                                                                                   "message": "", "error": ""}).encode("utf-8"))
        t[0] += R.EVERY + 1
        self.assertEqual(rp.tick(), 1)
        s = rp.load("fake", REC)["samples"]   # 最大値は残る(遅れが減っても)
        self.assertEqual((s["ticks"], s["behindMax"], s["behindLast"], s["memMaxMB"], s["memLastMB"], s["chatRestarts"], s["chat"]), (2, 4.0, 1.0, 120.0, 120.0, 1, "restarting"))
        self.rec.active = False   # 終わった: 締める前は recording のまま書き直す。締めたら done
        t[0] += R.EVERY + 1
        self.assertEqual(rp.tick(), 1)
        self.assertEqual(rp.load("fake", REC)["state"], "recording")
        self.put_peaks(self.peaks3(), seq=6, changes=[], ended=True, dec_n=1)
        t[0] += R.EVERY + 1
        self.assertEqual(rp.tick(), 1)
        d = rp.load("fake", REC)
        self.assertEqual((d["state"], d["detect"]["ended"], d["finishedAt"] is not None, d["samples"]["ticks"]), ("done", True, True, 4))
        self.assertEqual(sum(1 for m in self.logs if "配信の記録を残しました" in m), 1)
        t[0] += R.EVERY + 1
        self.assertEqual(rp.tick(), 0)   # 済んだ録画は書き直さない
        self.assertEqual([x["recording"] for x in rp.all()], [REC])
        self.assertIn("候補 2(控え 1・見送り 0)・採用 1(自動 0)", R.Reporter.summary(d))
        self.rec.rel = t[0] - T0 - R.END_WINDOW - 10   # 古い録画は見ない
        rp._done.clear()
        os.remove(rp.path("fake", REC))
        t[0] += R.EVERY + 1
        self.assertEqual(rp.tick(), 0)

    def test_compare_after_stream_and_forget(self):
        """0-10-6: 配信後のアーカイブの候補と配信中の候補を比べて live_feedback.jsonl に 1 行 / 録画を消したら検出の記録も消す(forget)"""
        self.assertEqual(self.live.archiver.compare, self.det.compare)   # 配信後の全自動(M7)が呼ぶ
        a = {"t0": T0 - 100.0, "offset": 0.0, "first": T0, "last": T0 + 3600}   # アーカイブの秒 s = 録画の秒 + 100
        marks = [{"src": "auto", "start": 372, "end": 417, "peak": 404, "score": 5},   # 録画の 272〜317(山 304)= p0-302 と重なる
                 {"src": "auto", "start": 1500, "end": 1545, "score": 4},              # 配信中には出ていない
                 {"src": "manual", "start": 0, "end": 10}, {"src": "auto", "start": 9000, "end": 9045}]   # 人のマーク・録画の外は数えない
        row = self.det.compare("fake", REC, a, marks)
        self.assertEqual((row["archive"], row["hit"], row["ratio"], row["diffs"], row["liveFrame"], row["liveBench"], row["liveUnmatched"]),
                         (2, 1, 0.5, [-2.0], 2, 1, 1))
        with open(os.path.join(self.tmp, "live", LX.FEEDBACK), encoding="utf-8") as f:
            last = json.loads(f.read().strip().splitlines()[-1])
        self.assertEqual((last["event"], last["recording"], last["hit"]), ("detect_compare", REC, 1))
        self.assertIsNone(self.det.compare("fake", "20261007-210000-x", a, marks))   # 配信中の候補が無い録画は何もしない
        self.det.forget("fake", REC)   # 録画を消した(manage/keep/live_cleanup が呼ぶ)
        self.assertFalse(os.path.exists(self.folder))
        self.det.forget("..", "x")   # 形の悪い id は何もしない
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, "live")))

    def test_config_and_spec_from_studio(self):
        """config.json: 録画元(合言葉つき)・感度・1 時間の本数・スタジオの解析の設定(範囲外は丸める)。変わったときだけ書く"""
        settings = {"settings": {"analyze": {"length": 300, "preRatio": 0.5, "lag": "x", "wChat": 1.4, "lagAuto": False}}}
        base = self.studio

        def studio(method, path, body=None):
            if path == "/api/settings":
                return 200, settings
            return base(method, path, body)
        self.live.studio_call = studio
        LF.patch_cfg(self.cfg, {"detect": {"sens": "high", "perHour": 3}})
        self.assertEqual(self.det.tick(), "nospawn")
        with open(os.path.join(self.det.dir, "config.json"), encoding="utf-8") as f:
            c = json.load(f)
        self.assertEqual(c["recorders"], [{"id": "fake", "url": self.rec.url, "token": TOKEN}])
        self.assertEqual(c["detect"], {"sens": "high", "perHour": 3})
        self.assertEqual((c["spec"]["length"], c["spec"]["preRatio"], c["spec"]["lag"], c["spec"]["wChat"], c["spec"]["lagAuto"]), (120.0, 0.5, 8.0, 1.4, False))
        self.assertEqual(c["dir"], self.det.dir)
        self.assertFalse(self.det.write_config())   # 変わっていなければ書かない
        LF.patch_cfg(self.cfg, {"detect": {"perHour": 4}})
        self.assertTrue(self.det.write_config())

    def request(self, rec=REC, **settings):
        """友人のライブ配信の依頼を録画に結びつける(src/home/live.py の begin_request が使う Store。2-15)"""
        return self.live.requests.put("fake", rec, {"rid": "20261008-120000-abcd", "deliverDir": os.path.join(self.tmp, "deliver"), "streamer": "友人の推し",
                                                    "settings": settings})

    def test_friend_request_with_detect_off(self):
        """2-15: ホームの検出・自動採用がオフでも、友人のライブ配信の依頼に結びついた録画があれば検出を動かす(config.json の detectAll false と
        録画ごとの requests)。画面の答え(enabled・autoAdopt)も録画ごと。リアルタイム切り抜きがオフなら動かさない"""
        LF.patch_cfg(self.cfg, {"detect": {"enabled": False, "sens": "low", "perHour": 4}, "autoAdopt": {"enabled": False}})
        self.assertFalse(self.det.enabled())
        self.assertEqual(self.det.tick(), "off")
        self.assertIsNone(self.det.health())
        self.request(sens="high", perHour=3, length=30, waitMin=2, pad=1, afterStream=False)
        self.assertTrue(self.det.enabled())
        self.assertEqual(self.det.tick(), "nospawn")
        with open(os.path.join(self.det.dir, "config.json"), encoding="utf-8") as f:
            c = json.load(f)
        self.assertEqual((c["detectAll"], c["detect"]), (False, {"sens": "low", "perHour": 4}))   # ホームの設定はそのまま(ほかの録画は測らない)
        self.assertEqual(c["requests"], {"fake/" + REC: {"sens": "high", "perHour": 3, "length": 30}})
        self.assertEqual(W.clean_requests(c["requests"]), {"fake/" + REC: {"sens": "high", "perHour": 3, "length": 30.0}})   # ワーカーが読む形
        d = self.get()
        self.assertEqual((d["enabled"], d["autoAdopt"]), (True, {"enabled": True, "waitMin": 2}))   # 結びついた録画は依頼の設定
        e = self.det.api_get({"recorder": ["fake"], "recording": ["20261007-210000-x"]})
        self.assertEqual((e["enabled"], e["autoAdopt"]), (False, {"enabled": False, "waitMin": 5}))   # 結びついていない録画はホームの設定のまま
        self.assertIsNotNone(self.det.health())
        LF.patch_cfg(self.cfg, {"detect": {"enabled": True}})
        self.assertTrue(self.det.write_config())
        with open(os.path.join(self.det.dir, "config.json"), encoding="utf-8") as f:
            c = json.load(f)
        self.assertEqual((c["detectAll"], list(c["requests"])), (True, ["fake/" + REC]))
        LF.patch_cfg(self.cfg, {"enabled": False})
        self.assertFalse(self.det.enabled())
        LF.patch_cfg(self.cfg, {"enabled": True, "detect": {"enabled": False}})
        self.assertTrue(self.live.requests.remove("fake", REC))   # 結びつきが消えた(14 日)= 今までどおりオフ
        self.assertFalse(self.det.enabled())
        self.assertEqual(self.det.tick(), "off")

    def test_auto_adopt_friend_request(self):
        """2-15: 自動採用のスイッチがオフでも、友人の依頼に結びついた録画の枠の候補は依頼の waitMin で採用する(余白は依頼の pad・ジョブに依頼 id)。
        結びついていない録画は、ホームの検出がオフなら(ほかの録画の依頼で検出が動いていても)採用しない"""
        LF.patch_cfg(self.cfg, {"detect": {"enabled": False}, "autoAdopt": {"enabled": True, "waitMin": 1}})
        self.request(rec="20261007-210000-x")   # ほかの録画の依頼(これで検出は動く)
        self.rec.rel = 5000
        t = self.worker_alive()
        self.assertTrue(self.det.enabled())
        self.assertEqual(self.det.auto_tick(), 0)
        t[0] += 61
        self.assertEqual(self.det.auto_tick(), 0)   # この録画は結びついていない・ホームの検出はオフ = 自動採用がオンでも採用しない
        self.assertNotIn(REC, self.studio.videos)
        LF.patch_cfg(self.cfg, {"autoAdopt": {"enabled": False}})
        self.request(waitMin=2, pad=1)
        self.assertEqual(self.det.auto_tick(), 0)   # 最初に見た(ここから依頼の waitMin を数える)
        t[0] += 119
        self.assertEqual(self.det.auto_tick(), 0)   # 依頼の 2 分がまだ(ホームの 1 分ではない)
        t[0] += 1
        self.assertEqual(self.det.auto_tick(), 2)   # 枠の p0・p1(控えの p2 は採用しない)
        v = self.studio.videos[REC]
        self.assertEqual(sorted((m["status"], m["start"], m["end"]) for m in v["marks"]), [("adopted", 271.0, 318.0), ("adopted", 869.0, 916.0)])   # 余白は依頼の 1 秒
        jobs = self.live.exporter.snapshot("fake", REC)
        self.assertEqual({(j["origin"], j["after"], j["request"]["rid"], j["request"]["deliverDir"]) for j in jobs},
                         {("auto", "auto", "20261008-120000-abcd", os.path.join(self.tmp, "deliver"))})
        self.assertEqual([x["origin"] for x in self.decisions()["items"]], ["auto", "auto"])
        self.assertEqual(self.det.auto_tick(), 0)   # 1 回だけ

    def test_spawn_heartbeat_restart_and_stop(self):
        """本物のワーカーを起動 → 心拍(worker.json)→ 止める。心拍を出さないワーカーは stale_sec で止めて起動し直す(数える)"""
        det = D.Detector(self.live, spawn=True)
        self.addCleanup(det.stop)
        self.assertEqual(det.tick(), "spawned")
        hb = None
        end = time.time() + 30
        while time.time() < end:
            hb = det.heartbeat()
            if hb and hb.get("pid") == det.proc.pid:
                break
            time.sleep(0.2)
        self.assertEqual((hb or {}).get("pid"), det.proc.pid, hb)
        self.assertTrue(det.running())
        self.assertEqual(det.tick(), "running")
        p = det.proc
        det.stop()
        self.assertIsNotNone(p.poll())
        silent = os.path.join(self.tmp, "silent_worker.py")
        with open(silent, "w", encoding="utf-8") as f:
            f.write("import time\nwhile True:\n    time.sleep(1)\n")
        det2 = D.Detector(self.live, spawn=True, worker=silent, stale_sec=1.0)
        self.addCleanup(det2.stop)
        self.assertEqual(det2.tick(), "spawned")
        first = det2.proc
        time.sleep(1.5)
        self.assertEqual(det2.tick(), "spawned")
        self.assertEqual(det2.restarts, 1)
        self.assertIsNotNone(first.poll())   # 前のワーカーは止めた
        LF.patch_cfg(self.cfg, {"detect": {"enabled": False}})
        q = det2.proc
        self.assertEqual(det2.tick(), "off")   # オフにしたら止める
        self.assertIsNotNone(q.poll())


if __name__ == "__main__":
    unittest.main()
