# -*- coding: utf-8 -*-
"""配信中の候補の文字起こし(線 D の D-11 案 b)のテスト。② の側 src/flow/live_tx.py(入口 home の Live は使わず、ライブ係 flow/livesession.LiveSession で組む)。
子プロセス live_tx_worker.py の試験は src/pipeline/transcribe/tests/test_live_tx_worker.py、設定(prefs)との一致と入口が numpy を読まないことは dev/rule_imports.py の C-02・I-02。

    py -3.12 -m unittest src/flow/tests/test_live_tx.py

確かめること:
  - RealWhisperTest(本物の通し): 声の TS セグメント → 見回り → 裏の糸 → 本物の ffmpeg → 本物の whisper.cpp(GPU)→ tx.json → view / text_for /
    recent_ids。最初のセッションだけ・whisper-cli の引数・結果の読み取り
  - 本物では起こせない物(録画元・ffmpeg・認識は偽物): ready() の理由(オフ・whisper-cli やモデルや ffmpeg が無い)・cfg() の壊れた値・status()・
    tick() の選び方(仮・終わり待ち・見送り・済み・2 回失敗・終わった録画・準備が無い・休み)・掲示板・重い処理の枠の待ち・
    _one() の失敗(error と tries・続けて 3 回で pause_until・入口の終了は失敗に数えない)・_run_worker() の壊れた子プロセスと時間切れ
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
import urllib.parse
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS)
import _livefix as LF  # noqa: E402
sys.path.insert(0, os.path.join(LF.SRC, "pipeline", "transcribe", "tests"))
import voice_fixture as VF  # noqa: E402
from ytt import testkit  # noqa: E402
from flow import board as Board  # noqa: E402
from flow import live_export as LX  # noqa: E402
from flow import live_tx as TX  # noqa: E402
from ytt import datadir, fsio  # noqa: E402

TOKEN = "x" * 40
T0 = 1790000000.0
REC = "20261008-200000-abcdefghijk"          # 録画中
REC_ENDED = "20261008-180000-bbbbbbbbbbb"    # 終わった録画


def write_wav(path, sec, rate=16000):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\0\0" * int(rate * sec))


def touch(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def script(folder, name, body):
    """小さな Python のプログラムを置いて、実行できる形のパスを返す(Windows は #! を実行できないので、同じ Python で動かす .bat を挟む)"""
    path = os.path.join(folder, name + ".py")
    with open(path, "w", encoding="utf-8") as f:
        f.write("#!%s\n%s" % (sys.executable, body))
    if os.name != "nt":
        os.chmod(path, 0o755)
        return path
    bat = os.path.join(folder, name + ".bat")
    with open(bat, "w", encoding="ascii", newline="\r\n") as f:
        f.write('@"%s" "%s" %%*\n' % (sys.executable, path))
    return bat


def fake_ffmpeg(folder):
    """偽の ffmpeg: 受けた引数を 1 行の JSON で記録し、最後の引数(出力)に 2 秒の 16kHz モノラルの wav を書く。fail の印があれば何も書かずに 1 で終わる。
    -> (実行できるパス, 記録のファイル, 失敗の印のファイル)"""
    log, flag = os.path.join(folder, "ffmpeg-args.jsonl"), os.path.join(folder, "ffmpeg-fail")
    body = ("import json, os, sys, wave\n"
            "with open(%r, 'a', encoding='utf-8') as f:\n"
            "    f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "if os.path.exists(%r):\n"
            "    sys.stderr.write('fake ffmpeg failed\\n')\n"
            "    sys.exit(1)\n"
            "src = sys.argv[sys.argv.index('-i') + 1]\n"
            "if not os.path.isfile(src):\n"
            "    sys.exit(2)\n"
            "with wave.open(sys.argv[-1], 'wb') as w:\n"
            "    w.setnchannels(1)\n"
            "    w.setsampwidth(2)\n"
            "    w.setframerate(16000)\n"
            "    w.writeframes(b'\\0\\0' * 32000)\n") % (log, flag)
    return script(folder, "fake_ffmpeg", body), log, flag


def read_jsonl(path):
    try:
        with open(path, encoding="utf-8") as f:
            return [json.loads(x) for x in f.read().splitlines() if x.strip()]
    except OSError:
        return []


wait_for = LF.wait_for


def peak(pid, start, state="frame", **kw):
    return dict({"id": pid, "start": float(start), "end": float(start + 8), "peak": int(start + 2), "score": 6.0, "reasons": [], "hour": 0,
                 "state": state, "endPending": False, "origin": None}, **kw)


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class TxRecorder:
    """録画元の代わり(HTTP。合言葉): /live/list(録画中の REC と終わった REC_ENDED)・/live/REC/segments(4 秒のセグメント。split から先は
    session_002 = つなぎ直し)・/live/REC/session_NNN/seg_NNNNNN.ts(ts_files があればその番号の本物のセグメント)。受けた要求を覚える"""

    def __init__(self, first=T0, seg=4.0, count=60):
        self.first, self.seg, self.count = first, seg, count
        self.split = None
        self.empty = False
        self.ts_status = 200
        self.ts_files = None
        self.seen = []
        owner = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _out(self, code, body, ctype="application/json"):
                body = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                owner.seen.append(self.path)
                if self.headers.get("Authorization") != "Bearer " + TOKEN:
                    return self._out(403, {"error": "token"})
                u = urllib.parse.urlsplit(self.path)
                if u.path == "/live/list":
                    return self._out(200, {"recordings": [owner.summary(REC, True), owner.summary(REC_ENDED, False)]})
                if u.path == "/live/%s/segments" % REC:
                    q = urllib.parse.parse_qs(u.query)
                    a, b = LX.iso_epoch(q["start"][0]), LX.iso_epoch(q["end"][0])
                    return self._out(200, dict(owner.summary(REC, True), segments=[] if owner.empty else owner.segments(a, b), gaps=[]))
                if u.path.startswith("/live/%s/session_" % REC) and u.path.endswith(".ts"):
                    if owner.ts_status != 200:
                        return self._out(owner.ts_status, {"error": "broken"})
                    if owner.ts_files:   # 本物の音のセグメント(seg_NNNNNN の番号の物)
                        with open(owner.ts_files[int(u.path[-9:-3])], "rb") as f:
                            return self._out(200, f.read(), "video/mp2t")
                    return self._out(200, b"\x47" * 188 * 20, "video/mp2t")
                return self._out(404, {"error": "not_found", "message": "なし"})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def summary(self, rec, active):
        return {"id": rec, "url": "https://www.youtube.com/watch?v=" + rec[-11:], "title": "テスト配信", "active": active,
                "state": "recording" if active else "ended", "firstPdt": LX.epoch_iso(self.first), "lastPdt": LX.epoch_iso(self.first + self.count * self.seg)}

    def segments(self, a, b):
        out = []
        for i in range(self.count):
            s = self.first + i * self.seg
            if s < b and s + self.seg > a:
                sess = "session_%03d" % (2 if self.split is not None and i >= self.split else 1)
                out.append({"uri": "%s/seg_%06d.ts" % (sess, i), "session": sess, "pdt": LX.epoch_iso(s), "dur": self.seg})
        return out

    def ts_gets(self):
        return [p for p in self.seen if p.endswith(".ts")]

    def close(self):
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None


class LiveTxBase(unittest.TestCase):
    """ライブ係(偽の録画元・設定はテストの一時フォルダの辞書)と、偽の ffmpeg・偽の認識(run)を渡した LiveTx"""

    def setUp(self):
        self.tmp = testkit.tempdir(self, "ytt-livetx-")
        env = {k: v for k, v in os.environ.items() if k != "TRANSCRIBE_DATA_DIR"}   # 編集の作業データ = <root>/editor(datadir の inplace)
        env["YTT_DATA_DIR"] = "inplace"
        for p in (mock.patch.dict(os.environ, env, clear=True), mock.patch.dict(datadir._registered, {}, clear=True)):
            p.start()
            self.addCleanup(p.stop)
        self.rec = TxRecorder()
        self.cfg = LF.recorder_cfg(self.rec.url, TOKEN)
        self.logs = []
        self.live = LF.new_session(self.tmp, self.cfg, log=self.logs.append)
        self.clock = Clock(T0 + 1000)
        self.calls = []
        self.answer = {"ok": True, "text": "ここで大きな声", "rows": [{"start": 0.5, "end": 2.0, "text": "ここで大きな声"}], "sec": 3.2,
                       "gpu": "AMD Radeon RX 7800 XT", "model": "large-v3", "engine": "whisper.cpp"}
        self.ff, self.fflog, self.ffail = fake_ffmpeg(self.tmp)
        self.tx = TX.LiveTx(self.live, log=self.logs.append, clock=self.clock, run=self.fake_run, ffmpeg=self.ff)
        self.live.livetx = self.tx
        self.edir = os.path.join(self.tmp, "editor")

    def tearDown(self):
        self.tx.close()
        if self.tx.thread is not None:
            self.tx.thread.join(5)
        self.live.detector.stop()
        self.rec.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fake_run(self, data_dir, model, wav):
        self.calls.append({"dataDir": data_dir, "model": model, "wav": wav, "size": os.path.getsize(wav) if os.path.isfile(wav) else None})
        a = self.answer
        return a(data_dir, model, wav) if callable(a) else a

    def put_wcpp(self, model="large-v3", exe=True):
        """whisper.cpp とモデルのダミー(ready が見るのはファイルがあるかだけ)"""
        if exe:
            touch(os.path.join(self.edir, "bin", "whisper.cpp-%s-vulkan" % TX.WCPP_VERSION, TX.WCPP_EXE))
        if model:
            touch(os.path.join(self.edir, "models", "whispercpp", TX.WCPP_MODEL_FILES[model]))

    def put_peaks(self, peaks, rec=REC):
        folder = self.live.detector.folder("fake", rec)
        os.makedirs(folder, exist_ok=True)
        fsio.atomic_write(os.path.join(folder, "peaks.json"), json.dumps({"v": 1, "recorder": "fake", "recording": rec, "seq": 1, "peaks": peaks,
                                                                           "changes": []}).encode("utf-8"))

    def items(self, rec=REC):
        try:
            with open(os.path.join(self.live.detector.folder("fake", rec), "tx.json"), encoding="utf-8") as f:
                d = json.load(f)
        except OSError:
            return {}
        self.assertEqual(d["v"], 1)
        return d["items"]


class ReadyTest(LiveTxBase):
    def test_ready_reasons_and_paths(self):
        self.assertEqual(self.tx.data_dir(), self.edir)
        p = self.tx.paths()
        self.assertEqual(p, {"exe": os.path.join(self.edir, "bin", "whisper.cpp-v1.9.4-vulkan", TX.WCPP_EXE),
                             "model": os.path.join(self.edir, "models", "whispercpp", "ggml-large-v3.bin"), "dataDir": self.edir})
        ok, why = self.tx.ready()
        self.assertFalse(ok)
        self.assertTrue(why.startswith("whisper.cpp がありません"), why)
        self.put_wcpp(model=None)
        self.assertEqual(self.tx.ready(), (False, "モデル ggml-large-v3.bin がありません(編集で GPU の文字起こしを 1 回すると取得されます)"))
        self.put_wcpp()
        self.assertEqual(self.tx.ready(), (True, ""))
        bare = TX.LiveTx(self.live)   # ffmpeg を渡さなければ探す(YTT_FFMPEG → PATH)
        with mock.patch.object(TX.tools, "find_tool", lambda *a, **k: None):
            self.assertEqual(bare.ready(), (False, "ffmpeg がありません"))
        with mock.patch.object(TX.tools, "find_tool", lambda *a, **k: "C:/ff/ffmpeg.exe"):
            self.assertEqual((bare.ready(), bare._ffmpeg()), ((True, ""), "C:/ff/ffmpeg.exe"))
        LF.patch_cfg(self.cfg, {"liveTx": {"enabled": False}})
        self.assertEqual(self.tx.ready(), (False, "オフ(設定 live.liveTx)"))
        LF.patch_cfg(self.cfg, {"liveTx": {"enabled": True}, "enabled": False})
        self.assertEqual(self.tx.ready(), (False, "リアルタイム切り抜きがオフ"))

    def test_cfg_and_status(self):
        class FakeLive:
            def __init__(self, v):
                self.v = v

            def cfg(self):
                return {"liveTx": self.v}
        for v, want in (({"enabled": False, "model": "large-v3-turbo"}, {"enabled": False, "model": "large-v3"}),   # 選べないモデルは既定
                        ("x", {"enabled": True, "model": "large-v3"}), (None, {"enabled": True, "model": "large-v3"}),
                        ({"enabled": "no", "model": "small"}, {"enabled": True, "model": "large-v3"}),   # 明示的に false のときだけオフ
                        ({"enabled": False, "model": ["large-v3"]}, {"enabled": False, "model": "large-v3"})):
            self.assertEqual(TX.LiveTx(FakeLive(v)).cfg(), want, v)
        s = self.tx.status()
        self.assertEqual({k: s[k] for k in ("enabled", "ready", "model", "busy", "queued", "done", "failed", "pausedUntil")},
                         {"enabled": True, "ready": False, "model": "large-v3", "busy": False, "queued": 0, "done": 0, "failed": 0, "pausedUntil": None})
        self.assertTrue(s["message"].startswith("whisper.cpp がありません"))
        self.put_wcpp()
        self.tx.pause_until = self.clock() + 60
        s = self.tx.status()
        self.assertEqual((s["ready"], s["message"], s["pausedUntil"]), (True, "", LX.epoch_iso(self.clock() + 60)))
        json.dumps(s)   # 画面へそのまま返せる


class TickTest(LiveTxBase):
    def test_tick_queues_only_settled_peaks_without_text(self):
        self.put_wcpp()
        started = []
        self.tx.start = lambda: started.append(1)   # 裏のスレッドは動かさない(列だけ見る)
        self.put_peaks([peak("p0-12", 10), peak("p1-22", 20, provisional=True), peak("p2-32", 30, endPending=True), peak("p3-42", 40, "dismissed"),
                        peak("p4-52", 50, "bench"), peak("p5-62", 60, "adopted"), peak("p6-72", 70), peak("p7-82", 80), peak("p8-92", 90),
                        peak("p9-102", 100), peak("p10-112", 110, end=None), {"id": 3, "start": 1, "end": 5, "state": "frame"}, "x"])
        self.put_peaks([peak("p0-12", 10)], rec=REC_ENDED)   # 終わった録画には付けない(書き出したあとの文字起こしが正本)
        self.tx.record("fake", REC, "p6-72", "もう付いている")
        self.tx.record("fake", REC, "p9-102", "")   # 認識できたが文字が無い(声の無い区間)= 済み
        self.tx._record_error("fake", REC, "p7-82", "失敗 1")
        self.tx._record_error("fake", REC, "p7-82", "失敗 2")   # 2 回失敗 = もう試さない
        self.tx._record_error("fake", REC, "p8-92", "失敗 1")   # 1 回だけ = もう 1 回
        self.assertEqual(self.tx.tick(), 4)
        self.assertEqual([(q[0], q[1], q[2]["id"], q[3]) for q in self.tx.queue],
                         [("fake", REC, "p0-12", T0), ("fake", REC, "p4-52", T0), ("fake", REC, "p5-62", T0), ("fake", REC, "p8-92", T0)])
        self.assertEqual(self.tx.queued, {("fake", REC, x) for x in ("p0-12", "p4-52", "p5-62", "p8-92")})
        self.assertEqual((started, self.tx.wake.is_set()), ([1], True))
        self.assertEqual(self.tx.tick(), 0)   # 入れたものは二重に入れない
        self.assertEqual(self.tx.status()["queued"], 4)
        self.tx.queue.clear()
        self.tx.queued.clear()
        self.tx.busy = ("fake", REC, "p0-12")   # 処理中のものも入れない
        self.assertEqual(self.tx.tick(), 3)
        self.assertEqual([q[2]["id"] for q in self.tx.queue], ["p4-52", "p5-62", "p8-92"])
        self.tx.busy = None
        self.tx.queue.clear()
        self.tx.queued.clear()
        self.tx.pause_until = self.clock() + 1   # 続けて失敗して休んでいる間は入れない
        self.assertEqual(self.tx.tick(), 0)
        self.clock.t += 2
        self.assertEqual(self.tx.tick(), 4)

    def test_tick_without_ready_does_nothing_and_logs_once(self):
        self.put_peaks([peak("p0-12", 10)])
        self.tx.start = lambda: self.fail("準備が無いのにスレッドを起こした")
        n = len(self.logs)
        self.assertEqual((self.tx.tick(), self.tx.tick()), (0, 0))
        said = [m for m in self.logs[n:] if m.startswith("配信中の文字起こし:")]
        self.assertEqual(len(said), 1, said)
        self.assertIn("whisper.cpp がありません", said[0])
        self.put_wcpp(model=None)
        self.assertEqual(self.tx.tick(), 0)
        self.assertIn("モデル ggml-large-v3.bin がありません", self.logs[-1])   # 理由が変わったらもう 1 回
        n = len(self.logs)
        LF.patch_cfg(self.cfg, {"liveTx": {"enabled": False}})
        self.assertEqual(self.tx.tick(), 0)
        LF.patch_cfg(self.cfg, {"liveTx": {"enabled": True}, "enabled": False})
        self.assertEqual(self.tx.tick(), 0)
        self.assertEqual(self.logs[n:], [], "オフ・リアルタイム切り抜きがオフは記録しない")
        self.assertEqual(self.tx.queue, [])

    def test_recorder_down(self):
        self.put_wcpp()
        self.rec.close()
        self.assertEqual(self.tx.tick(), 0)   # 録画の一覧を読めない: 次の見回りで


class BoardTest(LiveTxBase):
    def test_board_follows_queue_and_result(self):
        """掲示板: 列に入れた・始めた・済んだで lt:<録画元>.<録画>.<候補> がその state で載る・順番待ちは取り消せる"""
        self.put_wcpp()
        b = Board.Board()
        self.tx.attach_board(b)
        self.tx.start = lambda: None   # 裏の糸は動かさない(_step を直に呼ぶ)
        self.put_peaks([peak("p0-12", 10), peak("p4-52", 50, "bench")])
        self.assertEqual(self.tx.tick(), 2)
        jid, other = "lt:fake.%s.p0-12" % REC, "lt:fake.%s.p4-52" % REC
        got = b.get(jid)
        self.assertEqual((got["kind"], got["state"], got["canCancel"], got["target"]), ("live_tx", "queued", True, {"recording": REC}))
        self.assertEqual(b.cancel(other)["state"], "cancelled")
        self.assertEqual(self.tx.tick(), 0)   # 取り消した候補は入れ直さない
        self.assertEqual([q[2]["id"] for q in self.tx.queue], ["p0-12"])
        self.assertIsNone(got["case"])   # 初めて書き出すまでは案件が無い
        root = os.path.abspath(os.path.join(self.tmp, "案件"))
        self.live.exporter.case_of = lambda rc, rec: root if (rc, rec) == ("fake", REC) else None   # 書き出したあと = マークの正本の case
        self.assertTrue(self.tx._step())
        self.assertEqual((b.get(jid)["state"], b.get(jid)["case"]), ("done", Board.norm_case(root)))
        self.assertEqual(self.tx.text_for("fake", REC, "p0-12"), "ここで大きな声")
        with self.assertRaises(Board.Refused):
            b.cancel(jid)   # 終わった物は止められない(掲示板の canCancel が偽)


class OneTest(LiveTxBase):
    def setUp(self):
        super().setUp()
        self.put_wcpp()

    def test_one_waits_for_heavy_slot(self):
        """D-14: 認識は重い処理の順番(SLOTS。tool live-tx)を通す。枠が埋まっていれば待ち(status の slotWait・記録)、空けば認識。
        待っている間に入口が終わったら認識しない・失敗に数えない"""
        from ytt import jobs
        self.tx.slots = jobs.HeavySlots(limit=1, reserved={})
        tok = self.tx.slots.acquire("transcribe", "ほか")
        th = threading.Thread(target=self.tx._one, args=("fake", REC, peak("p0-12", 10), T0), daemon=True)
        th.start()
        for _ in range(200):
            if self.tx.slot_wait:
                break
            time.sleep(0.05)
        self.assertTrue(self.tx.slot_wait)
        self.assertEqual((self.calls, self.tx.status()["slotWait"]), ([], True))
        self.assertEqual([w["tool"] for w in self.tx.slots.snapshot()["waiting"]], ["live-tx"])
        self.tx.slots.release(tok)
        th.join(10)
        self.assertEqual((len(self.calls), self.tx.done, self.tx.slot_wait, self.tx.slots.snapshot()["active"]), (1, 1, False, []))
        self.assertEqual(self.tx.text_for("fake", REC, "p0-12"), "ここで大きな声")
        self.assertTrue(any("他の重い処理が終わるのを待っています" in m for m in self.logs))
        tok = self.tx.slots.acquire("transcribe", "ほか")
        th = threading.Thread(target=self.tx._one, args=("fake", REC, peak("p1-22", 20), T0), daemon=True)
        th.start()
        for _ in range(200):
            if self.tx.slot_wait:
                break
            time.sleep(0.05)
        self.assertTrue(self.tx.slot_wait)
        self.tx.close()   # 入口の終了
        th.join(10)
        self.tx.slots.release(tok)
        self.assertEqual((len(self.calls), self.tx.failed, "p1-22" in self.items(), self.tx.slot_wait), (1, 0, False, False))

    def test_one_failures_tries_and_pause(self):
        self.tx.start = lambda: None
        self.put_peaks([peak("p0-12", 10), peak("p1-22", 20)])
        self.answer = {"ok": False, "reason": "GPU(Vulkan)を使えませんでした"}
        self.tx._one("fake", REC, peak("p0-12", 10), T0)
        it = self.items()["p0-12"]
        self.assertEqual((it["error"], it["tries"], "text" in it), ("GPU(Vulkan)を使えませんでした", 1, False))
        self.assertEqual((self.tx.failed, self.tx.fails, self.tx.done), (1, 1, 0))
        self.assertEqual((self.tx.view("fake", REC), self.tx.text_for("fake", REC, "p0-12"), self.tx.recent_ids("fake", REC)), ({}, None, []))
        self.assertIn("文字を付けられませんでした: GPU(Vulkan)を使えませんでした", self.logs[-1])
        self.tx._one("fake", REC, peak("p0-12", 10), T0)
        self.assertEqual(self.items()["p0-12"]["tries"], 2)
        self.assertEqual(self.tx.tick(), 1)   # 2 回失敗した p0 は入れない(p1 だけ)
        self.assertEqual([q[2]["id"] for q in self.tx.queue], ["p1-22"])
        self.tx.queue.clear()
        self.tx.queued.clear()
        self.answer = None   # 子プロセスが答えない
        self.tx._one("fake", REC, peak("p1-22", 20), T0)
        self.assertEqual(self.items()["p1-22"]["error"], "答えがありません")
        self.assertEqual((self.tx.fails, self.tx.pause_until), (0, self.clock() + TX.PAUSE_SEC))   # 続けて 3 回 = 休む
        self.assertIn("続けて 3 回失敗したので 10 分休みます", self.logs[-1])
        self.assertEqual(self.tx.status()["pausedUntil"], LX.epoch_iso(self.clock() + TX.PAUSE_SEC))
        self.assertEqual(self.tx.tick(), 0)
        self.clock.t += TX.PAUSE_SEC + 1
        self.assertIsNone(self.tx.status()["pausedUntil"])
        self.assertEqual(self.tx.tick(), 1)   # 休みが明けたら、1 回だけ失敗した p1 をもう 1 回
        self.answer = dict(self.answer or {}, ok=True, text="今度は付いた")
        self.tx._one("fake", REC, peak("p1-22", 20), T0)
        self.assertEqual((self.items()["p1-22"].get("error"), self.tx.text_for("fake", REC, "p1-22"), self.tx.fails), (None, "今度は付いた", 0))

    def test_one_other_failures(self):
        cases = []
        self.rec.empty = True
        self.tx._one("fake", REC, peak("p0-12", 10), T0)
        cases.append(("p0-12", "その区間の音がまだありません"))
        self.rec.empty = False
        self.rec.ts_status = 500
        self.tx._one("fake", REC, peak("p1-22", 20), T0)
        cases.append(("p1-22", "セグメントを取れませんでした(HTTP 500)"))
        self.rec.ts_status = 200
        touch(self.ffail)
        self.tx._one("fake", REC, peak("p2-32", 30), T0)
        cases.append(("p2-32", "wav を作れませんでした: fake ffmpeg failed"))
        os.remove(self.ffail)
        self.tx.ffmpeg = os.path.join(self.tmp, "no-such-ffmpeg.exe")
        self.tx._one("fake", REC, peak("p3-42", 40), T0)
        cases.append(("p3-42", "wav を作れませんでした(FileNotFoundError)"))
        self.tx.ffmpeg = self.ff
        self.tx._one("nope", REC, peak("p4-52", 50), T0)
        self.tx._one("fake", "20261008-210000-zzzzzzzzzzz", peak("p5-62", 60), T0)
        got = {k: v["error"] for k, v in self.items().items()}
        self.assertEqual({k: got.get(k) for k, _w in cases}, dict(cases))
        self.assertEqual(self.items("20261008-210000-zzzzzzzzzzz")["p5-62"]["error"], "録画のセグメントを読めません(HTTP 404)")
        self.assertEqual(TX.LiveTx(self.live).view("fake", REC), {})
        self.assertEqual(self.calls, [], "認識の手前で止まった")
        nope = os.path.join(self.live.detector.dir, "nope", REC, "tx.json")
        with open(nope, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["items"]["p4-52"]["error"], "録画元がありません")
        self.assertEqual(self.tx.failed, 6)

    def test_wav_ffmpeg_stops_on_halt_and_timeout(self):
        """wav を作る ffmpeg は ytt/tools.run(入口の終了 _halt で止まる = 失敗に数えない・WAV_TIMEOUT 秒で止める)"""
        seen = []

        def fake_run(why):
            def run(cmd, **kw):
                seen.append((kw.get("timeout"), kw.get("cancelled")))
                return TX.tools.RunResult(1, b"", b"", why)
            return run
        with mock.patch.object(TX.tools, "run", fake_run("cancel")):
            self.assertIsNone(self.tx._one("fake", REC, peak("p0-12", 10), T0))
        with mock.patch.object(TX.tools, "run", fake_run("timeout")):
            self.tx._one("fake", REC, peak("p1-22", 20), T0)
        self.assertEqual(seen, [(TX.WAV_TIMEOUT, self.tx._halt.is_set)] * 2)
        got = {k: v.get("error") for k, v in self.items().items()}
        self.assertEqual((got.get("p0-12"), got.get("p1-22")), (None, "wav を作れませんでした(%d 秒で終わりませんでした)" % TX.WAV_TIMEOUT))
        self.assertEqual(self.calls, [])

    def test_one_failure_without_reason(self):
        self.answer = {"ok": False}   # 理由の無い失敗でも "None" にしない
        self.tx._one("fake", REC, peak("p0-12", 10), T0)
        self.assertEqual((self.items()["p0-12"]["error"], self.items()["p0-12"]["tries"]), ("認識に失敗しました", 1))

    def test_halt_during_run_is_not_a_failure(self):
        def killed(data_dir, model, wav):
            self.tx.close()   # 入口の終了で子プロセスを止めた
            return {"ok": False, "reason": "終了コード 1"}
        self.answer = killed
        self.tx._one("fake", REC, peak("p0-12", 10), T0)
        self.assertEqual((self.items(), self.tx.failed, self.tx.fails), ({}, 0, 0))   # 次の起動の見回りでやり直す


class RealWhisperTest(LiveTxBase):
    """本物の通し(whisper.cpp large-v3・GPU。この束で GPU を使う通しはこれ 1 本): 声の見本の 4 秒の TS セグメントを偽の録画元が出し
    (8 秒から先はつなぎ直し = session_002)、見回り → 裏の糸 → 本物の ffmpeg で wav → live_tx_worker.recognize
    (whisper-cli は編集の作業データから読むだけ)→ tx.json。モデル・whisper.cpp・ffmpeg・日本語の音声合成が無ければ飛ばす"""

    @classmethod
    def setUpClass(cls):
        cls.home = VF.whisper_cpp_large()
        if not (cls.home and LF.FF):
            raise unittest.SkipTest("whisper.cpp と large-v3 か ffmpeg が無い")
        cls.dir = tempfile.mkdtemp(prefix="ytt-livetx-real-")
        wav = VF.make_voice(os.path.join(cls.dir, "voice.wav"))
        if wav is None:
            shutil.rmtree(cls.dir, ignore_errors=True)
            raise unittest.SkipTest("日本語の音声合成が無い")
        LF.ff("-i", wav, "-c:a", "aac", "-f", "segment", "-segment_time", "4", "-segment_format", "mpegts", os.path.join(cls.dir, "seg_%03d.ts"))
        cls.segs = sorted(os.path.join(cls.dir, n) for n in os.listdir(cls.dir) if n.endswith(".ts"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_candidate_through_real_whisper_cpp(self):
        from pipeline.transcribe import live_tx_worker as TW, recognize, tx_engines as te
        self.rec.count, self.rec.ts_files, self.rec.split = len(self.segs), self.segs, 2
        self.put_wcpp()
        self.tx.ffmpeg = LF.FF
        self.tx.run = lambda data_dir, model, wav: TW.recognize(self.home, model, wav)   # 子プロセスの中身をこのプロセスで(引数と行を覗くため)
        args, got, prog, cmds, seen_wav = [], [], [], [], []
        real_args, real_tx, real_run = te.WhisperCpp.args, te.WhisperCpp.transcribe, TX.tools.run

        def spy_args(eng, wav, out_base, kw):
            a = real_args(eng, wav, out_base, kw)
            args.append(list(a))
            return a

        def spy_tx(eng, audio, **kw):
            eng.hooks = {"progress": prog.append}
            seen_wav.append(audio)
            segs, info = real_tx(eng, audio, **kw)
            segs = list(segs)
            got.append((eng, segs, info))
            return iter(segs), info

        def spy_run(cmd, **kw):
            cmds.append(list(cmd))
            return real_run(cmd, **kw)
        saved = list(sys.path)
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), saved))
        self.put_peaks([peak("p0-12", 0, end=12.0)])
        with mock.patch.object(te.WhisperCpp, "args", spy_args), mock.patch.object(te.WhisperCpp, "transcribe", spy_tx), \
                mock.patch.object(TX.tools, "run", spy_run):
            self.assertEqual(self.tx.tick(), 1)
            self.assertTrue(wait_for(lambda: self.tx.text_for("fake", REC, "p0-12") or self.tx.failed, 90), self.logs[-5:])
            self.assertTrue(wait_for(lambda: self.tx.status()["busy"] is False and self.tx.done == 1, 10), self.logs[-5:])
        # 録画の頭からの秒 → 絶対時刻で区間を聞き、候補の始まりのセッションのセグメントだけ取る(つなぎ直しの後は使わない)
        q = urllib.parse.parse_qs(urllib.parse.urlsplit([p for p in self.rec.seen if "/segments" in p][0]).query)
        self.assertEqual((LX.iso_epoch(q["start"][0]), LX.iso_epoch(q["end"][0])), (T0, T0 + 12))
        self.assertEqual(self.rec.ts_gets(), ["/live/%s/session_001/seg_%06d.ts" % (REC, i) for i in (0, 1)])
        ff = cmds[0]
        self.assertEqual(ff[1:], ["-hide_banner", "-loglevel", "error", "-y", "-ss", "0.000", "-i", ff[ff.index("-i") + 1], "-t", "12.000",
                                  "-vn", "-sn", "-dn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-f", "wav", ff[-1]])
        self.assertTrue(ff[ff.index("-i") + 1].endswith("part_00.ts") and ff[-1].endswith("in.wav"), ff)
        # whisper-cli の引数
        a = args[0]
        self.assertEqual([a[a.index(k) + 1] for k in ("-l", "-bs", "-mc")], ["ja", "5", "0"])
        self.assertIn("-nfa", a)                                                  # フラッシュアテンションは既定で使わない
        self.assertNotIn("-ng", a)                                                # GPU(vulkan)
        self.assertFalse({"--vad", "-vm", "-vt", "-vsd", "-vp"} & set(a))          # whisper.cpp 自身の声の検出は使わない
        self.assertEqual(a[a.index("-m") + 1], os.path.join(te.wcpp_model_dir(self.home), "ggml-large-v3.bin"))
        self.assertEqual(seen_wav, [ff[-1]])
        # 結果の読み取り: 行・単語(特別なトークンは単語にしない)・自信の度合い・装置
        eng, segs, info = got[0]
        self.assertEqual(info.language, "ja")
        self.assertAlmostEqual(info.duration, 8.0, delta=0.3)                     # 取ったのは 2 本(8 秒)だけ
        self.assertTrue(segs and all(s.words for s in segs))
        words = [w for s in segs for w in s.words]
        self.assertFalse([w.word for w in words if w.word.startswith("[_")])
        self.assertTrue(all(0.0 <= w.probability <= 1.0 for w in words))
        self.assertTrue(all(s.avg_logprob < 0 and s.no_speech_prob is None and s.compression_ratio > 0 for s in segs))
        d = recognize.seg_to_dict(segs[0])
        self.assertEqual((d["text"], len(d["wordProbs"])), (segs[0].text, len(segs[0].words)))
        self.assertTrue(eng.gpu_name and prog and max(prog) >= 0.9, (eng.gpu_name, prog[-3:]))
        # tx.json と見え方(文字は候補の区間の行)
        it = self.items()["p0-12"]
        self.assertIn("配信", it["text"])
        self.assertNotIn("ゲーム", it["text"])                                    # 3 文目は session_002
        self.assertEqual((it["gpu"], it["model"], "error" in it, it["atEpoch"]), (eng.gpu_name, "large-v3", False, self.clock()))
        self.assertIsInstance(it["sec"], float)
        self.assertTrue(it["rows"] and all(0.0 <= r["start"] < r["end"] <= 8.5 for r in it["rows"]), it["rows"])
        self.assertEqual(list(self.tx.view("fake", REC)), ["p0-12"])
        self.assertEqual((self.tx.text_for("fake", REC, "p9-9"), self.tx.text_for("fake", REC, None)), (None, None))
        self.assertEqual(self.tx.recent_ids("fake", REC), ["p0-12"])
        self.clock.t += TX.RECENT_SEC + 1
        self.assertEqual(self.tx.recent_ids("fake", REC), [])                     # 古くなったら差分には入れない(全部の答えの候補には残る)
        self.assertEqual((self.tx.done, self.tx.failed, self.tx.fails, self.tx.queue, self.tx.queued), (1, 0, 0, [], set()))
        self.assertTrue(any("p0-12 に文字を付けました" in m and eng.gpu_name in m for m in self.logs), self.logs[-5:])
        self.assertEqual(os.listdir(self.live.exporter.work), [])                 # 取ったセグメントと wav は消す
        self.assertEqual(self.tx.tick(), 0)                                       # 済んだものは入れない
        self.assertEqual(TX.LiveTx(self.live).text_for("fake", REC, "p0-12"), it["text"])   # 入口を起動し直しても tx.json から読む
        self.assertEqual(len(self.tx.record("fake", REC, "p1-22", "あ" * (TX.TEXT_MAX + 500))["text"]), TX.TEXT_MAX)
        self.assertEqual(self.tx.view("fake", REC_ENDED), {})
        t = self.tx.thread
        self.tx.close()
        t.join(10)
        self.assertFalse(t.is_alive())


class ShiftRowsTest(unittest.TestCase):
    """LD-2f: 余白つきの wav の行を候補の始まり = 0 秒へずらし、文字は候補の区間にかかる行だけ"""

    def test_shift(self):
        rows = [{"start": 1.0, "end": 4.0, "text": "まえ"}, {"start": 9.0, "end": 12.0, "text": "なか"}, {"start": 26.0, "end": 28.0, "text": "あと"}, "x"]
        out, text = TX.shift_rows(rows, 10.0, 15.0)
        self.assertEqual([(r["start"], r["end"]) for r in out], [(-9.0, -6.0), (-1.0, 2.0), (16.0, 18.0)])
        self.assertEqual(text, "なか")

    def test_session_at(self):
        segs = [{"session": "s1", "pdt": "2026-10-04T05:59:50.000Z", "dur": 4.0}, {"session": "s2", "pdt": "2026-10-04T06:00:00.000Z", "dur": 10.0}]
        self.assertEqual(TX._session_at(segs, LX.iso_epoch("2026-10-04T06:00:02Z")), "s2")   # 余白が前のセッションにかかっても候補のセッション
        self.assertEqual(TX._session_at(segs, LX.iso_epoch("2026-10-04T05:59:51Z")), "s1")


class RunWorkerTest(LiveTxBase):
    """_run_worker: 本物の子プロセスを起動して結果の json を読む(認識はしない = whisper-cli が無い・偽の子プロセス)"""

    def setUp(self):
        super().setUp()
        self.wav = os.path.join(self.tmp, "w", "in.wav")
        write_wav(self.wav, 1.0)
        self.real = TX.LiveTx(self.live, python=sys.executable)

    def test_real_worker_answers(self):
        self.assertEqual(self.real.run.__func__, TX.LiveTx._run_worker)
        r = self.real._run_worker(self.edir, "large-v3", self.wav)
        self.assertEqual(r["ok"], False)
        self.assertIn("whisper.cpp かモデルがありません", r["reason"])
        self.assertIsNone(self.real.proc)

    def test_broken_worker_and_timeout(self):
        boom = os.path.join(self.tmp, "boom.py")
        with open(boom, "w", encoding="utf-8") as f:
            f.write("import sys\nsys.stderr.write('line1\\nline2\\nboom\\n')\nsys.exit(3)\n")
        with mock.patch.object(TX, "WORKER", boom):
            self.assertEqual(self.real._run_worker(self.edir, "large-v3", self.wav), {"ok": False, "reason": "結果を読めませんでした(line1 / line2 / boom)"})
        quiet = os.path.join(self.tmp, "quiet.py")
        with open(quiet, "w", encoding="utf-8") as f:
            f.write("import sys\nsys.exit(5)\n")
        with mock.patch.object(TX, "WORKER", quiet):
            self.assertEqual(self.real._run_worker(self.edir, "large-v3", self.wav), {"ok": False, "reason": "結果を読めませんでした(終了コード 5)"})
        odd = os.path.join(self.tmp, "odd.py")
        with open(odd, "w", encoding="utf-8") as f:
            f.write("import sys\nopen(sys.argv[4], 'w').write('[1, 2]')\n")
        with mock.patch.object(TX, "WORKER", odd):
            self.assertEqual(self.real._run_worker(self.edir, "large-v3", self.wav), {"ok": False, "reason": "結果の形が違います"})
        slow = os.path.join(self.tmp, "slow.py")
        with open(slow, "w", encoding="utf-8") as f:
            f.write("import time\ntime.sleep(30)\n")
        t0 = time.time()
        with mock.patch.object(TX, "WORKER", slow), mock.patch.object(TX, "TX_TIMEOUT", 1.0):
            self.assertEqual(self.real._run_worker(self.edir, "large-v3", self.wav), {"ok": False, "reason": "1 秒で終わりませんでした"})
        self.assertLess(time.time() - t0, 15)
        self.assertIsNone(self.real.proc)
        missing = TX.LiveTx(self.live, python=os.path.join(self.tmp, "no-python.exe"))
        self.assertTrue(missing._run_worker(self.edir, "large-v3", self.wav)["reason"].startswith("子プロセスを起動できませんでした"))


if __name__ == "__main__":
    unittest.main()
