# -*- coding: utf-8 -*-
"""配信中の盛り上がりの検出(線 D の L2)のワーカー src/pipeline/analyze/live_excite_worker.py のテスト(子プロセスの中身を直に)。
② の側(flow/live_detect.py。API・自動の採用 M11・友人の依頼など)は src/flow/tests/test_live_detect.py、設定の検査と入口を通す分は src/home/tests/test_live_detect_api.py。

    py -3.10 -m unittest src/pipeline/analyze/tests/test_live_excite_worker.py

確かめること:
  - ワーカーをクラスのまま(プロセスを起動せずに)、偽の録画元・偽の「音を測る」・注入した時計で 12 時間を早送り: 状態が増え続けない・候補が出る・
    1 時間の枠を超えない / 途中で 3 回止めて state.json から続けても同じ候補 / 欠け(セグメントが飛ぶ)は前後の山を捨てる / 遅れたら古い所を飛ばして、
    配信が終わったら測り直す / チャットなしでも動く / 人の決定(decisions.json)を帳簿に当てる / 配信が終わったら締める
  - チャット: 偽の yt-dlp(fake_ytdlp_chat.py。本物のプロセス)で 読む・止まったら起動し直す・間隔・403 は最大の間隔から・64MB(小さくして)で回す・
    1 時間に何回もなら諦める・最初から「チャットが無い」
  - 本物の ffmpeg: 音を測る関数(src/pipeline/analyze/levels.py の asplit で 1 回)がスタジオの analyze.audio_levels と同じ値・以前の 2 回のデコードと ±0.1 dB・hls_fixture の 1 秒セグメントを偽の録画元(HTTP。合言葉と Host)から測る
  - 入口のプロセスで numpy を import しない
  - 仮の候補が山から 60 秒以内に出て本番(同じ id・本番の候補は仮の候補なしと同じ)に置き換わる・同時に 2 本まで(3 本目は順番待ち →
    1 本目が終わったら次へ・順番待ちのうちに終わった録画は音だけで締める)・雰囲気の変わり目のあと 60 秒はしきい値 1.3 倍・M10 の長さの目安(length_hint・
    clean_hint・新しく受け持つ録画だけ)・止まらない・溜めない(yt-dlp を子ごと止める・改行の無い末尾で止まらない・途中から受け持つと測り直さない・
    測り直しを 60 秒分ずつ・心拍・上限・1 本の例外で止めない・まだ無い候補の決定は待つ・壊れた値)
  - 友人のライブ配信の依頼(docs/spec/friend-intake.md の 2-15): ホームの検出・自動採用がオフでも結びついた録画は動く(config.json の detectAll・requests・
    画面の答えは録画ごと)・依頼の waitMin・pad で自動の採用(結びついていない録画は採用しない)・ワーカーは detectAll false なら依頼の録画だけ・
    感度・枠・長さは依頼の値(lengthFrom friend・起動し直しても)・clean_requests の検査
本物の YouTube にはつながない。作業データはテストの一時フォルダだけ(YTT_DATA_DIR=inplace)。
"""
import http.client
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)

TESTS = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(os.path.dirname(os.path.dirname(TESTS)))   # tests -> analyze -> pipeline -> src
HERE = os.path.join(SRC, "home")                                  # 入口(NoNumpyTest が子プロセスで読む)
if SRC not in sys.path:   # src(層のパッケージ pipeline・ytt。launch.py と同じく後ろに)
    sys.path.append(SRC)
from pipeline.analyze import live_excite_worker as W  # noqa: E402
from flow import live_export as LX  # noqa: E402   (SameAsExportTest が flow の写しと比べる)
from pipeline.analyze import excite, levels  # noqa: E402
from ytt import fsio, procs, tools  # noqa: E402

TOKEN = "k" * 40
T0 = 1790000000.0
VID = "abcdefghijk"
REC = "20261007-200000-" + VID
URL = "https://www.youtube.com/watch?v=" + VID
FAKE_CHAT = os.path.join(TESTS, "fake_ytdlp_chat.py")
FF = tools.find_tool("ffmpeg", "YTT_FFMPEG")


def iso(t):
    return W.epoch_iso(t)


def level(sec):
    """偽の音(dB): ふだん -32 前後の揺れ + 10 分ごとに 12 秒の山(全帯域 +14・高音域 +18)。決まった値(乱数の種なし)"""
    h = math.sin(sec * 12.9898) * 43758.5453
    noise = (h - math.floor(h)) * 2.0 - 1.0
    burst = (sec % 600) in range(300, 312) or (sec % 1800) in range(1000, 1010)
    full = -32.0 + 2.0 * math.sin(sec / 37.0) + noise + (14.0 if burst else 0.0)
    return full, full - 12.0 + (6.0 if burst else 0.0) + noise * 0.5


def chat_rate(sec):
    """偽のチャット(1 秒あたりの件数): ふだん 0〜1 件 + 山の 8 秒あとに 20 秒ほど増える"""
    if (sec % 600) in range(308, 330):
        return 6
    return 1 if int(sec) % 3 == 0 else 0


def chat_line(ts, text="草"):
    r = {"message": {"runs": [{"text": text}]}, "timestampUsec": str(int(round(ts * 1e6))), "authorExternalChannelId": "UC1"}
    return json.dumps({"isLive": True, "replayChatItemAction": {"actions": [{"addChatItemAction": {"item": {"liveChatTextMessageRenderer": r}}}]},
                       "videoOffsetTimeMsec": "0"}, ensure_ascii=False) + "\n"


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class SimRecorder:
    """録画元の代わり(プロセスの中。HTTP なし): 時計が進むほどセグメント(4 秒。jitter で 3.98/4.02)が増える。gaps の秒の間は届かない(繋ぎ直し = 次のセッション)"""

    def __init__(self, clock, first=T0, seg=4.0, jitter=False, gaps=(), end=None, rec=REC, url=URL):
        self.clock, self.first, self.seg, self.jitter, self.gaps, self.end, self.rec, self.url = clock, first, seg, jitter, list(gaps), end, rec, url
        self.all = []        # 作った分のセグメント
        self._t, self._i, self._sess = first, 0, 1
        self.down = False
        self.measured = 0

    def _grow(self):
        limit = self.clock() if self.end is None else min(self.clock(), self.first + self.end)
        while True:
            dur = self.seg + ((0.02 if self._i % 2 else -0.02) if self.jitter else 0.0)
            if self._t + dur > limit:
                return
            rel = self._t - self.first
            g = next((g for g in self.gaps if g[0] <= rel < g[1]), None)
            if g is not None:   # 欠け: そこまで届かない。戻ったら次のセッション
                self._t = self.first + g[1]
                self._sess += 1
                continue
            self.all.append({"uri": "session_%03d/seg_%06d.ts" % (self._sess, self._i), "dur": dur, "pdt": iso(self._t)})
            self._t += dur
            self._i += 1

    def active(self):
        return self.end is None or self.clock() < self.first + self.end + 1

    def get_json(self, path):
        if self.down:
            return None, None
        self._grow()
        last = (W.iso_epoch(self.all[-1]["pdt"]) + self.all[-1]["dur"]) if self.all else None
        if path == "/live/list":
            return 200, {"recordings": [{"id": self.rec, "url": self.url, "active": self.active(), "state": "recording" if self.active() else "ended",
                                         "firstPdt": self.all[0]["pdt"] if self.all else None, "lastPdt": iso(last) if last else None}]}
        if path.startswith("/live/%s/status?since=" % self.rec):
            n = int(path.rsplit("=", 1)[1])
            return 200, {"since": n, "active": self.active(), "firstPdt": self.all[0]["pdt"] if self.all else None, "lastPdt": iso(last) if last else None,
                         "segmentList": self.all[n:n + 5000]}
        return 404, {"message": "なし"}

    def get_bytes(self, path):
        return 404, b""

    def measure(self, client, rec, batch):
        """偽の「音を測る」: 1 本目の受信時刻の秒から round(長さ) 秒分の値(ffmpeg なし)"""
        self.measured += 1
        b0 = int(round(W.iso_epoch(batch[0]["pdt"]) - self.first)) if "pdt" in batch[0] else int(round(batch[0]["t"] - self.first))
        k = int(round(sum(x["dur"] for x in batch)))
        vals = [level(b0 + i) for i in range(k)]
        return [v[0] for v in vals], [v[1] for v in vals]


class FakeProc:
    def __init__(self, sim, path):
        self.sim, self.path, self.alive, self.pid = sim, path, True, 4242
        self.returncode = None

    def poll(self):
        return None if self.alive else (self.returncode if self.returncode is not None else 0)

    def kill(self):
        self.alive = False
        self.returncode = -9

    def wait(self, t=None):
        return self.returncode


class SimChat:
    """yt-dlp の代わり(launcher に渡す): 生きている「プロセス」の .live_chat.json.part へ、時計までのメッセージを書く(delay 秒遅れて)"""

    def __init__(self, clock, first=T0, delay=10.0, rate=chat_rate):
        self.clock, self.first, self.delay, self.rate = clock, first, delay, rate
        self.written = first - 30.0   # ここまでの時刻のメッセージは書いた
        self.procs = []

    def launch(self, cmd, logf):
        out = cmd[cmd.index("-o") + 1].replace(".%(ext)s", ".live_chat.json.part")
        p = FakeProc(self, out)
        self.procs.append(p)
        return p

    def pump(self):
        live = [p for p in self.procs if p.alive]
        upto = self.clock() - self.delay
        if not live or upto <= self.written:
            return
        lines = []
        s = int(math.floor(self.written)) + 1
        while s <= upto:
            for k in range(self.rate(s - self.first)):
                lines.append(chat_line(s + (k + 0.5) / 10.0, "草" if k % 2 else "hello"))
            s += 1
        self.written = s - 1
        with open(live[-1].path, "a", encoding="utf-8") as f:
            f.writelines(lines)

    def kill_all(self):
        for p in self.procs:
            p.kill()


def write_config(folder, ytdlp=None, **kw):
    cfg = dict({"v": 1, "dir": folder, "recorders": [{"id": "fake", "url": "http://127.0.0.1:1", "token": TOKEN}],
                "detect": {"sens": "normal", "perHour": 6}, "spec": dict(W.SPEC_DEFAULT), "ffmpeg": FF, "ytdlp": ytdlp,
                "chatLimitBytes": W.CHAT_LIMIT, "chatStallSec": W.CHAT_STALL}, **kw)
    os.makedirs(folder, exist_ok=True)
    fsio.atomic_write(os.path.join(folder, "config.json"), json.dumps(cfg).encode("utf-8"))
    return os.path.join(folder, "config.json")


def make_worker(cfg, clock, sim, chat=None, **kw):
    opts = dict(clock=clock, client_factory=lambda rc: sim, measure_batch=sim.measure, launcher=chat.launch if chat else None, log=lambda m: None,
                save_sec=300.0, heart_sec=600.0)
    opts.update(kw)
    return W.Worker(cfg, **opts)


def run_until(w, clock, sim, t_end, step=30.0, chat=None):
    while clock.t < t_end:
        clock.t += step
        if chat is not None:
            chat.pump()
        w.tick()


def peaks_of(folder):
    with open(os.path.join(folder, "fake", REC, "peaks.json"), encoding="utf-8") as f:
        d = json.load(f)
    return d


def key_of(p):
    return (p["id"], p["start"], p["end"], p["peak"], p["score"], p["state"], p["confirmedAt"])


class WorkerSimTest(unittest.TestCase):
    """ワーカーの中身を早送りで(ffmpeg も yt-dlp もプロセスを起動しない)"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-detect-")
        self.dir = os.path.join(self.tmp, "excite")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_twelve_hours_fast_forward(self):
        """12 時間を早送り: 状態(state.json・Online・PeakBook の中の辞書)が増え続けない・候補が出る・1 時間の枠を超えない・チャットも数える"""
        clock = Clock(T0)
        sim = SimRecorder(clock)
        chat = SimChat(clock)
        cfg = write_config(self.dir, ytdlp="fake-yt-dlp")
        w = make_worker(cfg, clock, sim, chat)
        sizes = {}
        for hours in (1, 6, 12):
            run_until(w, clock, sim, T0 + hours * 3600, chat=chat)
            st = w.recs[("fake", REC)]
            w._save_rec(st, clock.t)
            sizes[hours] = os.path.getsize(os.path.join(self.dir, "fake", REC, "state.json"))
            on = st.online
            for ch in (on.ch_full, on.ch_band, on.ch_chat):
                self.assertLess(len(ch.raw), 600, hours)
                self.assertLess(len(ch.sm), 600, hours)
                self.assertLess(len(ch.dev), excite.ONLINE_WINDOW + 200, hours)
                self.assertLess(len(ch.med) + len(ch.scale), 40, hours)
            self.assertLess(len(on.full) + len(on.band) + len(on.chat), 200, hours)
            self.assertLess(len(st.book.total) + len(st.book.level), 1300, hours)
            self.assertLess(len(st.book.changes), excite.CHANGES_KEEP + 1)
            self.assertLess(len(st.audio) + len(st.raw) + len(st.chat_bins), 400, hours)
            self.assertLessEqual(len(st.lag_a), W.LAG_SPAN + 120)
        self.assertLess(sizes[12], sizes[1] + 200 * 1024, sizes)   # 増えるのは候補の数の分だけ(1 時間 10 本前後 × 数百バイト)
        self.assertLess(sizes[12], 2 * 1024 * 1024, sizes)
        d = peaks_of(self.dir)
        frame = [p for p in d["peaks"] if p["state"] == "frame"]
        self.assertGreaterEqual(len(frame), 12 * 4, d["counts"])   # 10 分ごとの山の多くが候補になる
        for h, n in d["counts"].items():
            self.assertLessEqual(n, 6, d["counts"])
        self.assertEqual(d["chat"], "ok")
        self.assertGreater(st.online.lag, 0)
        self.assertTrue(any(p["parts"].get("chat", 0) >= 1.0 for p in frame), "チャットの点数が効いていない")
        self.assertTrue(all(abs((p["peak"] % 600) - 305) < 40 or abs((p["peak"] % 1800) - 1004) < 40 for p in frame), [p["peak"] for p in frame][:20])
        with open(os.path.join(self.dir, "fake", REC, "series.jsonl"), encoding="utf-8") as f:
            rows = [json.loads(x) for x in f]
        self.assertGreater(len(rows), 700)
        self.assertEqual(len(rows[5]["total"]), 60)
        with open(os.path.join(self.dir, "worker.json"), encoding="utf-8") as f:
            hb = json.load(f)
        self.assertEqual(hb["recordings"][0]["id"], REC)
        w.close()

    def test_restart_three_times_gives_same_peaks(self):
        """途中で 3 回止めて(保存は 5 分ごと = 最後の保存より後は消える)state.json から続けても、止めなかったときと同じ候補・同じ番号"""
        def run(crash_at):
            folder = os.path.join(self.tmp, "run%d" % len(crash_at))
            clock = Clock(T0)
            sim, chat = SimRecorder(clock, jitter=True), SimChat(clock)
            cfg = write_config(folder, ytdlp="fake-yt-dlp")
            w = make_worker(cfg, clock, sim, chat)
            for t in list(crash_at) + [T0 + 3 * 3600]:
                run_until(w, clock, sim, t, chat=chat)
                if t in crash_at:   # 落ちた(close も呼ばない)。yt-dlp もワーカーと一緒に消える
                    chat.kill_all()
                    w = make_worker(cfg, clock, sim, chat)
            w.close()
            return peaks_of(folder)
        a = run(())
        b = run((T0 + 50 * 60 + 7, T0 + 100 * 60 + 13, T0 + 150 * 60 + 29))
        self.assertGreaterEqual(len(a["peaks"]), 12)
        self.assertEqual([key_of(p) for p in a["peaks"]], [key_of(p) for p in b["peaks"]])
        self.assertEqual((a["seq"], a["counts"], a["lag"]), (b["seq"], b["counts"], b["lag"]))
        self.assertEqual(sorted(os.listdir(os.path.join(self.tmp, "run3", "chat")))[:1], [VID + ".4.live_chat.json.part"])   # 前の起動のファイルは読み切って消した

    def test_gap_drops_nearby_peaks_and_recording_end(self):
        """欠け(繋ぎ直しで 40 秒届かない)の前後 GAP_MARGIN 秒には山を作らない / 配信が終わったら終わり待ちを確定して締め、生のチャットを消す"""
        clock = Clock(T0)
        sim = SimRecorder(clock, gaps=[(1795, 1835)], end=2500)   # 1800 秒の山(1800 % 600 = 0 なので 2100 の山の前)と、1000 秒台の山とは別
        chat = SimChat(clock)
        cfg = write_config(self.dir, ytdlp="fake-yt-dlp")
        w = make_worker(cfg, clock, sim, chat)
        sim.gaps = [(2095, 2135)]   # 2100 秒の山(2100 % 600 = 300)の上に欠け
        run_until(w, clock, sim, T0 + 2700, chat=chat)
        d = peaks_of(self.dir)
        self.assertTrue(d["ended"], d["message"])
        self.assertFalse(any(2095 - W.GAP_MARGIN <= p["peak"] < 2135 + W.GAP_MARGIN for p in d["peaks"]), [p["peak"] for p in d["peaks"]])
        self.assertTrue(any(abs(p["peak"] - 1502) < 5 for p in d["peaks"]))   # 欠けの前の山は残る
        self.assertGreaterEqual(d["gaps"], 1)
        self.assertFalse(any(p["endPending"] for p in d["peaks"]))
        self.assertEqual([x for x in os.listdir(os.path.join(self.dir, "chat")) if x.startswith(VID)], [])   # 配信が終わったら生のチャットは消す
        self.assertNotIn(("fake", REC), w.recs)
        n = sim.measured
        run_until(w, clock, sim, T0 + 2800, chat=chat)   # 終わった録画はもう触らない
        self.assertEqual(sim.measured, n)
        w.close()

    def test_behind_skips_then_remeasures_after_end(self):
        """ライブ端から 10 分超遅れたら古い所を飛ばす(欠けとして覚える)→ 配信が終わったら飛ばした区間の音だけ測り直して skipped.jsonl へ。チャットなし(yt-dlp が無い)でも動く"""
        clock = Clock(T0)
        sim = SimRecorder(clock, end=3600)
        cfg = write_config(self.dir, ytdlp=None)
        w = make_worker(cfg, clock, sim)
        run_until(w, clock, sim, T0 + 600)
        sim.down = True                       # 録画元につながらない間に遅れがたまる
        run_until(w, clock, sim, T0 + 1500)
        sim.down = False
        clock.t += 30
        w.tick()
        st = w.recs[("fake", REC)]
        self.assertEqual(len(st.skipped), 1, st.message)
        sk = st.skipped[0]
        self.assertLess(sk["from"], 700)
        self.assertGreater(sk["to"], 1300)
        self.assertIn("飛ばして", st.message)
        self.assertLess(st.behind, 120)
        self.assertEqual(st.chat_state, "off")
        run_until(w, clock, sim, T0 + 3700)
        with open(os.path.join(self.dir, "fake", REC, "skipped.jsonl"), encoding="utf-8") as f:
            rows = [json.loads(x) for x in f]
        self.assertGreater(sum(len(r["full"]) for r in rows), sk["to"] - sk["from"] - 10)
        self.assertEqual(rows[0]["t0"], sk["from"])
        self.assertEqual(rows[0]["full"][0], round(level(sk["from"])[0], 1))
        d = peaks_of(self.dir)
        self.assertTrue(d["ended"])
        self.assertEqual(d["skipped"][0]["done"], True)
        self.assertFalse(any(sk["from"] - W.GAP_MARGIN <= p["peak"] < sk["to"] + W.GAP_MARGIN for p in d["peaks"]))
        w.close()

    def test_decisions_are_applied_and_detect_settings(self):
        """入口が書いた decisions.json(人の採用・見送り・自動の採用)を帳簿に当てる(decN)・感度と 1 時間の本数の変更は途中から効く"""
        clock = Clock(T0)
        sim = SimRecorder(clock)
        cfg = write_config(self.dir)
        w = make_worker(cfg, clock, sim)
        run_until(w, clock, sim, T0 + 1300)
        d = peaks_of(self.dir)
        ids = [p["id"] for p in d["peaks"]]
        self.assertGreaterEqual(len(ids), 2)
        dec = {"v": 1, "n": 3, "items": [{"n": 1, "id": ids[0], "state": "adopted", "origin": "manual", "markId": "m1", "jobId": "lx-1"},
                                         {"n": 2, "id": ids[1], "state": "dismissed"}, {"n": 3, "id": "p99-1", "state": "adopted"}]}
        fsio.atomic_write(os.path.join(self.dir, "fake", REC, "decisions.json"), json.dumps(dec).encode("utf-8"))
        clock.t += 6
        w.tick()
        d = peaks_of(self.dir)
        by = {p["id"]: p for p in d["peaks"]}
        self.assertEqual((by[ids[0]]["state"], by[ids[0]]["origin"], by[ids[0]]["markId"], by[ids[1]]["state"], d["decN"]), ("adopted", "manual", "m1", "dismissed", 3))
        self.assertEqual(d["counts"].get("0", 0), sum(1 for p in d["peaks"] if p["state"] == "frame" and p["hour"] == 0))   # 人の採用・見送りは枠に数えない
        write_config(self.dir, detect={"sens": "low", "perHour": 2})
        w.cfg_checked = -1e18
        clock.t += 6
        w.tick()
        st = w.recs[("fake", REC)]
        self.assertEqual((st.book.thr, st.book.per_hour), (excite.SENS["low"], 2))
        w.close()

    def test_run_exits_memory_lock_parent(self):
        """常駐の終わり方: メモリが上限を超えたら状態を保存して終了コード 3(入口が起動し直す)・ほかのワーカーが動いていれば 4・ホームが終わったら 0"""
        clock = Clock(T0 + 1200)
        sim = SimRecorder(clock)
        cfg = write_config(self.dir)
        lock = W.take_lock(os.path.join(self.dir, "worker.lock"))
        self.assertIsNotNone(lock)
        self.assertEqual(make_worker(cfg, clock, sim, sleep=lambda s: None).run(), W.EXIT_LOCKED)   # 書き手は 1 つ
        lock.close()
        w = make_worker(cfg, clock, sim, sleep=lambda s: None, mem_limit_mb=1)
        self.assertEqual(w.run(), W.EXIT_MEM)
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "fake", REC, "state.json")))   # 終わる前に保存した
        with open(os.path.join(self.dir, "worker.json"), encoding="utf-8") as f:
            hb = json.load(f)
        self.assertEqual(hb["message"], "止まりました")
        self.assertGreater(hb["memMB"], 1)
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        w = make_worker(cfg, clock, sim, sleep=lambda s: None, parent=dead.pid)
        self.assertEqual(w.run(), 0)


class ChatFeedTest(unittest.TestCase):
    """チャットの読み方(偽の yt-dlp = 本物のプロセス。時間は縮める)"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-detect-chat-")
        self.folder = os.path.join(self.tmp, "chat")
        self.log = os.path.join(self.tmp, "launch.log")
        self.spec = os.path.join(self.tmp, "spec.json")
        self.env = dict(os.environ)
        os.environ["FAKE_YTDLP_CHAT"] = self.spec
        self.feeds = []

    def tearDown(self):
        for f in self.feeds:
            f.close()
        os.environ.clear()
        os.environ.update(self.env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def feed(self, runs, **kw):
        with open(self.spec, "w", encoding="utf-8") as f:
            json.dump({"log": self.log, "t0": T0, "runs": runs}, f)
        opts = dict(limit=W.CHAT_LIMIT, stall=1.0, backoff=(0.3, 0.6, 4.0), max_per_hour=6)
        opts.update(kw)
        f = W.ChatFeed(VID, URL, self.folder, FAKE_CHAT, log=lambda m: None, **opts)
        self.feeds.append(f)
        return f

    def drive(self, f, until, timeout=20.0):
        """until(feed, msgs) が真になるまで step を回す -> 読んだメッセージ"""
        msgs, end = [], time.time() + timeout
        while time.time() < end:
            msgs += f.step(time.time())
            if until(f, msgs):
                return msgs
            time.sleep(0.05)
        self.fail("時間内に終わりませんでした: state=%s launches=%d msgs=%d reason=%s" % (f.state, f.launches, len(msgs), f.reason))

    def launches(self):
        with open(self.log, encoding="utf-8") as fh:
            return [json.loads(x) for x in fh]

    def test_stall_restarts_with_backoff_and_new_file(self):
        """5 行書いて黙って止まる → chatStallSec(1 秒)で止めて間隔をあけて起動し直す(新しいファイル)・前のファイルは読み切って消す・行は重ねない"""
        f = self.feed([{"mode": "stall", "lines": 5, "interval": 0.02}, {"mode": "write", "interval": 0.05}])
        msgs = self.drive(f, lambda f, m: f.launches >= 2 and len(m) >= 10)
        self.assertEqual(f.total_restarts, 1)
        self.assertEqual(f.state, "ok")
        self.assertEqual(len(msgs), len({t for t, _w in msgs}))   # 重ねて数えない
        self.assertEqual(msgs[0], (T0, 2.5))   # 「草」= 1 + 1.5
        args = self.launches()
        self.assertEqual(len(args), 2)
        self.assertIn("--skip-download", args[0])
        self.assertEqual(args[0][args[0].index("--sub-langs") + 1], "live_chat")
        self.assertEqual(args[0][-2:], ["--", URL])
        self.assertTrue(args[1][args[1].index("-o") + 1].endswith(VID + ".2.%(ext)s"))
        self.assertFalse(os.path.exists(os.path.join(self.folder, VID + ".1.live_chat.json.part")))   # 前の起動のファイルは消した
        self.assertEqual(f.view_state(), "ok")

    def test_403_waits_longest_then_gives_up(self):
        """403 が出たら最大の間隔から・1 時間に max_per_hour を超えたら諦める(音だけ = state none)"""
        f = self.feed([{"mode": "403", "lines": 2, "interval": 0.01}])
        self.drive(f, lambda f, m: f.state == "restarting")
        self.assertGreater(f.next_at - time.time(), 3.0)   # 最大の間隔(4 秒)
        g = self.feed([{"mode": "exit", "lines": 1, "code": 1}], max_per_hour=2, backoff=(0.1, 0.2))
        self.drive(g, lambda f, m: f.state == "none")
        self.assertEqual(g.launches, 3)
        self.assertIn("音だけ", g.reason)
        self.assertEqual(g.view_state(), "none")

    def test_no_restart_after_recording_ended(self):
        """録画が終わった(alive=False)あとは、yt-dlp が終わっても起動し直さない(残りは読む)"""
        f = self.feed([{"mode": "exit", "lines": 2, "code": 0}], backoff=(0.1,))
        f.step(time.time())
        self.assertEqual(f.launches, 1)
        f.proc.wait(10)
        msgs, end = [], time.time() + 1.0
        while time.time() < end:
            msgs += f.step(time.time(), alive=False)
            time.sleep(0.05)
        self.assertEqual((f.launches, len(msgs), f.total_restarts), (1, 2, 0))

    def test_no_chat_on_first_run_gives_up_at_once(self):
        f = self.feed([{"mode": "nochat"}])
        self.drive(f, lambda f, m: f.state == "none")
        self.assertEqual(f.launches, 1)
        self.assertIn("チャットを取れません", f.reason)

    def test_size_limit_rotates_without_counting(self):
        """ファイルが上限(64MB を小さくして 4KB)を超えたら新しいファイルへ(起動し直しの数に入れない・待たない)・古い方は読み切ってから消す"""
        f = self.feed([{"mode": "write", "interval": 0.01, "pad": 300}], limit=4000)
        msgs = self.drive(f, lambda f, m: f.launches >= 3 and len(m) > 40)
        self.assertEqual(f.total_restarts, 0)
        self.assertEqual(len(msgs), len({t for t, _w in msgs}))
        left = [x for x in os.listdir(self.folder) if ".live_chat" in x]
        self.assertLessEqual(len(left), 2, left)   # 今のファイル(と、読み切る前の 1 つ)だけ
        self.assertNotIn(VID + ".1.live_chat.json.part", left)

    def child_pids(self):
        try:
            with open(self.log + ".pids", encoding="utf-8") as fh:
                return [int(x) for x in fh if x.strip()]
        except OSError:
            return []

    def wait_dead(self, pid, timeout=10.0):
        end = time.time() + timeout
        while time.time() < end:
            if not procs.pid_alive(pid):
                return True
            time.sleep(0.1)
        return False

    def test_stop_kills_child_of_ytdlp(self):
        """本物の yt-dlp(PyInstaller の 1 ファイルの exe)は起動すると子を作る: 止めたら子も終わる(前の番号の .part に書き続けない)"""
        f = self.feed([{"mode": "stall", "lines": 3, "interval": 0.02, "child": True}, {"mode": "write", "interval": 0.05, "child": True}])
        msgs = self.drive(f, lambda f, m: f.launches >= 2 and len(m) >= 6 and len(self.child_pids()) >= 2)
        pids = self.child_pids()
        self.assertTrue(self.wait_dead(pids[0]), "止まった yt-dlp の子が残っている")
        self.assertEqual(len(msgs), len({t for t, _w in msgs}))
        f.close()
        self.assertTrue(self.wait_dead(pids[1]), "閉じたあと yt-dlp の子が残っている")

    def test_partial_tail_does_not_block_restart(self):
        """止めた yt-dlp のファイルの末尾に改行の無い行があっても、TAIL_IDLE 秒増えなければ読み終えたことにして起動し直す(数えた行は重ねない)"""
        os.makedirs(self.folder)
        with open(os.path.join(self.folder, VID + ".1.live_chat.json.part"), "w", encoding="utf-8") as fh:
            fh.write(chat_line(T0) + chat_line(T0 + 1) + chat_line(T0 + 2)[:40])
        launched = []
        f = W.ChatFeed(VID, URL, self.folder, "fake-yt-dlp", launcher=lambda cmd, logf: launched.append(cmd) or FakeProc(None, ""), log=lambda m: None,
                       backoff=(0.1,))
        self.feeds.append(f)
        f.gen, f.files, f.state, f.next_at, f.ever_grew = 1, [[1, 0]], "restarting", 0.0, True
        now = time.time()
        self.assertEqual(len(f.step(now)), 2)
        self.assertEqual(launched, [], "読みかけの行があるうちは起動しない")
        self.assertEqual(f.step(now + 5), [])
        self.assertEqual(launched, [])
        f.step(now + 5 + W.TAIL_IDLE)
        self.assertEqual(len(launched), 1, "末尾が増えなければ読み終えたことにして起動し直す")
        self.assertFalse(os.path.exists(os.path.join(self.folder, VID + ".1.live_chat.json.part")), "前のファイルは読み終えたので消す")

    def test_worker_falls_back_to_audio_only(self):
        """ワーカーの中で: チャットが無い配信 → 録画を音だけ(Online を作り直す)にして続ける・peaks.json の chat は none"""
        with open(self.spec, "w", encoding="utf-8") as fh:
            json.dump({"log": self.log, "runs": [{"mode": "nochat"}]}, fh)
        clock = Clock(T0)
        sim = SimRecorder(clock)
        folder = os.path.join(self.tmp, "excite")
        w = make_worker(write_config(folder, ytdlp=FAKE_CHAT), clock, sim, launcher=None)
        try:
            end = time.time() + 20
            while time.time() < end:
                clock.t += 30
                w.tick()
                st = w.recs.get(("fake", REC))
                if st is not None and not st.use_chat:
                    break
                time.sleep(0.2)
            self.assertFalse(st.use_chat)
            self.assertIsNone(st.online.ch_chat)
            run_until(w, clock, sim, clock.t + 900)
            d = peaks_of(folder)
            self.assertEqual(d["chat"], "none")
            self.assertGreaterEqual(len(d["peaks"]), 1)   # 音だけでも候補は出る
        finally:
            w.close()


class SegRecorder:
    """録画元の代わり(HTTP。合言葉と Host を確かめる): hls_fixture の 1 秒セグメントを session_001/seg_00000N.ts として出す(active で録画中・終わり)"""

    def __init__(self, folder, segs, first):
        self.folder, self.segs, self.first = folder, segs, first
        self.seen = []
        self.active = True
        owner = self
        t, self.lst = first, []
        for i, (_name, dur) in enumerate(segs):
            self.lst.append({"uri": "session_001/seg_%06d.ts" % i, "dur": dur, "pdt": iso(t)})
            t += dur
        self.last = t

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _out(self, code, body, ctype="application/json"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                owner.seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "host": self.headers.get("Host")})
                if self.headers.get("Authorization") != "Bearer " + TOKEN:
                    return self._out(403, b'{"error":"token"}')
                path = self.path.split("?")[0]
                if path == "/live/list":
                    return self._out(200, json.dumps({"recordings": [{"id": REC, "url": URL, "active": owner.active, "state": "recording" if owner.active else "ended", "firstPdt": owner.lst[0]["pdt"],
                                                                      "lastPdt": iso(owner.last)}]}).encode())
                if path == "/live/%s/status" % REC:
                    n = int(self.path.rsplit("=", 1)[1])
                    return self._out(200, json.dumps({"since": n, "active": owner.active, "firstPdt": owner.lst[0]["pdt"], "lastPdt": iso(owner.last),
                                                      "segmentList": owner.lst[n:]}).encode())
                if path.startswith("/live/%s/session_001/seg_" % REC):
                    i = int(path.rsplit("_", 1)[1].split(".")[0])
                    with open(os.path.join(owner.folder, owner.segs[i][0]), "rb") as f:
                        return self._out(200, f.read(), "video/mp2t")
                return self._out(404, b'{"error":"not_found"}')

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@unittest.skipUnless(FF, "ffmpeg が見つかりません")
class FfmpegTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-detect-ff-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_measure_matches_studio_audio_levels(self):
        """同じ wav を、ワーカーの measure_levels とスタジオの analyze.audio_levels(どちらも levels.py の asplit で 1 回)で測ると同じ値で、
        以前のスタジオの測り方(同じフィルターを帯域ごとに 2 回のデコード)とも ±0.1 dB(OPT1 で 1 回にした)"""
        wav = os.path.join(self.tmp, "t.wav")
        subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "anoisesrc=d=14:c=pink:r=48000:a=0.3",
                        "-f", "lavfi", "-i", "sine=f=300:d=14:r=48000", "-filter_complex",
                        "[0:a][1:a]amix=inputs=2,volume='0.1+0.9*abs(sin(t*0.7))':eval=frame[o]", "-map", "[o]", wav],
                       check=True, creationflags=tools.no_window_flags())
        full, band = W.measure_levels(FF, wav, self.tmp)
        from pipeline.analyze import analyze   # スタジオの解析(RS3-5 で pipeline/analyze へ。読むのはテストだけ)
        job = {"cancel": False}
        self.assertEqual(analyze.audio_levels(job, wav, 14.0, self.tmp), (full, band))
        self.assertEqual(sorted(os.listdir(self.tmp)), ["t.wav"])   # 結果のファイルは読んだら消す

        def two_pass(hp):   # 以前の analyze.audio_levels(帯域ごとに 1 回。標準出力に出す)
            filt = "aresample=16000," + ("highpass=f=%d," % hp if hp else "") + levels.STATS + ":file=-"
            out = subprocess.run([FF, "-hide_banner", "-nostdin", "-i", wav, "-vn", "-af", filt, "-f", "null", "-"], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True, creationflags=tools.no_window_flags()).stdout
            return [levels.level(x.split("=", 1)[1]) for x in out.decode("utf-8", "replace").splitlines() if x.startswith(levels.LEVEL_KEY)]
        a, b = two_pass(None), two_pass(levels.HIGHPASS)
        self.assertEqual((len(full), len(band)), (len(a), len(b)))
        self.assertEqual(len(full), 14)
        self.assertLessEqual(max(abs(x - y) for x, y in zip(full, a)), 0.1)
        self.assertLessEqual(max(abs(x - y) for x, y in zip(band, b)), 0.1)
        self.assertGreater(max(full) - min(full), 6.0)   # 音量が動く音で比べた

    def test_hls_segments_through_recorder_api(self):
        """hls_fixture の 1 秒セグメント 24 本を、偽の録画元(HTTP)から合言葉つきで取り、3 本ずつ ffmpeg で測って 1 秒の箱へ → 終わった録画を締める"""
        sys.path.insert(0, os.path.join(SRC, "pipeline", "ingest", "tests"))
        import hls_fixture
        src = os.path.join(self.tmp, "src")
        segs = hls_fixture.make_source(src, 24, seg=1)
        rec = SegRecorder(src, segs, T0)
        try:
            folder = os.path.join(self.tmp, "excite")
            cfg = write_config(folder, recorders=[{"id": "fake", "url": rec.url, "token": TOKEN}])
            w = W.Worker(cfg, log=lambda m: None, save_sec=0, heart_sec=0, tick_budget=120)
            w.tick()
            self.assertEqual(w.recs[("fake", REC)].next_box, 24)   # 録画中: 3 本ずつ全部測った
            rec.active = False
            w.tick()
            self.assertIn(("fake", REC), w.done)
            with open(os.path.join(folder, "fake", REC, "state.json"), encoding="utf-8") as f:
                st = json.load(f)
            total = sum(d for _n, d in segs)
            self.assertEqual(st["nextBox"], int(round(total)))   # 受信時刻からの 1 秒の箱(数で数えない・3 本ずつの丸めのずれを合わせ直す)
            self.assertEqual(st["gapCount"], 0)
            self.assertEqual(st["errors"], 0)
            seg_gets = [x for x in rec.seen if ".ts" in x["path"]]
            self.assertEqual(len(seg_gets), len(segs))
            self.assertTrue(all(x["auth"] == "Bearer " + TOKEN and x["host"] == rec.url[7:] for x in rec.seen))
            lv = [v for v in st["online"]["ch_full"]["raw"]]
            self.assertTrue(all(-60 < v < -5 for v in lv), lv[:5])   # 440Hz の音(-90 の無音ではない)
            w.close()
        finally:
            rec.close()


REC_B = "20261007-200100-bbbbbbbbbbb"
REC_C = "20261007-200200-ccccccccccc"


class MultiSim:
    """録画元の代わり(録画 3 本。中身は録画ごとの SimRecorder)"""

    def __init__(self, sims):
        self.sims = {s.rec: s for s in sims}

    def get_json(self, path):
        if path == "/live/list":
            recs = []
            for s in self.sims.values():
                recs += s.get_json(path)[1]["recordings"]
            return 200, {"recordings": recs}
        return self.sims[path.split("/")[2]].get_json(path)

    def get_bytes(self, path):
        return 404, b""

    def measure(self, client, rec, batch):
        return self.sims[rec].measure(client, rec, batch)


class ShiftRecorder(SimRecorder):
    """音が 1500 秒から +10dB(雰囲気の変わり目)"""

    def measure(self, client, rec, batch):
        full, band = SimRecorder.measure(self, client, rec, batch)
        b0 = int(round(batch[0]["t"] - self.first))
        return [v + (10.0 if b0 + i >= 1500 else 0.0) for i, v in enumerate(full)], [v + (10.0 if b0 + i >= 1500 else 0.0) for i, v in enumerate(band)]


def first_seen(w, clock, sim, chat, t_end, step=6.0, key=("fake", REC)):
    """周期 step 秒で回し、候補ごとに最初に出た時刻・本番になった時刻(録画の頭からの秒)を覚える -> ({id: (時刻, 仮か)}, {id: 時刻}, RecState)"""
    seen, final, st = {}, {}, None
    while clock.t < t_end:
        clock.t += step
        if chat is not None:
            chat.pump()
        w.tick()
        st = w.recs.get(key) or st
        for pid, p in (st.book.peaks.items() if st else []):
            now = clock.t - T0
            seen.setdefault(pid, (now, bool(p.get("provisional"))))
            if not p.get("provisional") and not p.get("expired"):
                final.setdefault(pid, now)
    return seen, final, st


class WorkerRestTest(unittest.TestCase):
    """ワーカーの 仮の候補(遅れの短縮)・同時に 2 本まで・雰囲気の変わり目・M10 の長さ・止まらない作り(測り直しを分ける・
    途中から受け持つ・1 本の例外で止めない・まだ無い候補の決定・壊れた値)"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-detect-rest-")
        self.dir = os.path.join(self.tmp, "excite")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_provisional_comes_first_and_final_is_unchanged(self):
        """仮の候補は山から 60 秒以内に出て、本番(チャット込み・90 秒ほど)に同じ id で置き換わる。本番の候補は仮の候補なしのときと同じ"""
        out = {}
        for prov in (True, False):
            clock = Clock(T0)
            sim, chat = SimRecorder(clock), SimChat(clock, delay=21.0)   # yt-dlp の書き出しの遅れ約 21 秒(L0 の実測)
            w = make_worker(write_config(os.path.join(self.dir, str(prov)), ytdlp="fake-yt-dlp", provisional=prov), clock, sim, chat)
            seen, final, st = first_seen(w, clock, sim, chat, T0 + 1700)
            w.close()
            out[prov] = (seen, final, st.book.list())
        seen, final, peaks = out[True]
        self.assertGreaterEqual(len(peaks), 3)
        for p in peaks:
            self.assertFalse(p.get("expired"), p)
            self.assertTrue(seen[p["id"]][1], "まず仮の候補で出る")
            self.assertLessEqual(seen[p["id"]][0] - p["peak"], 60, (p["id"], seen[p["id"]], p["peak"]))
            self.assertGreaterEqual(final[p["id"]] - p["peak"], 80, (p["id"], final[p["id"]], p["peak"]))
        keys = ("start", "end", "peak", "score", "state", "hour", "confirmedAt", "parts")
        self.assertEqual([[p[k] for k in keys] for p in peaks], [[p[k] for k in keys] for p in out[False][2]])
        self.assertTrue(all(not seen_[1] for seen_ in out[False][0].values()))

    def test_two_at_a_time_then_next(self):
        """録画中が 3 本: 古い 2 本だけ測り、3 本目は順番待ち(peaks.json の queued・message と worker.json)。1 本目が終わったら次へ。
        順番待ちのうちに配信が終わった録画も、あとで音だけ測って締める"""
        clock = Clock(T0)
        a = SimRecorder(clock, end=1800)
        b = SimRecorder(clock, first=T0 + 60, rec=REC_B, url="https://www.youtube.com/watch?v=bbbbbbbbbbb")
        c = SimRecorder(clock, first=T0 + 120, end=1380, rec=REC_C, url="https://www.youtube.com/watch?v=ccccccccccc")
        sim = MultiSim([a, b, c])
        w = make_worker(write_config(self.dir), clock, sim, heart_sec=0.0)
        most = 0
        while clock.t < T0 + 1200:
            clock.t += 30
            w.tick()
            most = max(most, len(w.recs))
        self.assertEqual(sorted(k[1] for k in w.recs), sorted([REC, REC_B]))
        with open(os.path.join(self.dir, "fake", REC_C, "peaks.json"), encoding="utf-8") as f:
            q = json.load(f)
        self.assertEqual((q["queued"], q["queuePos"], q["peaks"]), (True, 1, []))
        self.assertIn("順番待ち", q["message"])
        with open(os.path.join(self.dir, "worker.json"), encoding="utf-8") as f:
            hb = json.load(f)
        self.assertEqual([x["id"] for x in hb["queued"]], [REC_C])
        self.assertIn("順番待ち", hb["message"])
        while clock.t < T0 + 2600:
            clock.t += 30
            w.tick()
            most = max(most, len(w.recs))
        self.assertLessEqual(most, 2)
        self.assertIn(("fake", REC_C), w.done, "1 本目が終わったら次へ(順番待ちのうちに終わった録画は音だけで測って締める)")
        with open(os.path.join(self.dir, "fake", REC_C, "peaks.json"), encoding="utf-8") as f:
            d = json.load(f)
        self.assertTrue(d["ended"])
        self.assertNotIn("queued", d)
        self.assertEqual(d["chat"], "off")
        self.assertGreaterEqual(len([p for p in d["peaks"] if p["state"] == "frame"]), 2, [p["peak"] for p in d["peaks"]])
        with open(os.path.join(self.dir, "worker.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["queued"], [])
        w.close()

    def test_mood_shift_raises_threshold_for_a_minute(self):
        """音の 5 分の中央値が前の 5 分より 10dB 上がった → 1 回だけ変わり目(新しい値が半分を超えた所)・その後 60 秒はしきい値 1.3 倍"""
        clock = Clock(T0)
        sim = ShiftRecorder(clock)
        w = make_worker(write_config(self.dir), clock, sim)
        run_until(w, clock, sim, T0 + 1700, step=6.0)
        st = w.recs[("fake", REC)]
        self.assertEqual(st.mood_shifts, 1)
        self.assertEqual(len(st.book.boost), 1, st.book.boost)
        b = st.book.boost[0]
        self.assertTrue(1645 <= b[0] <= 1670 and b[1] - b[0] == 60 and b[2] == 1.3, b)
        run_until(w, clock, sim, T0 + 2400)
        d = peaks_of(self.dir)
        self.assertEqual(d["moodShifts"], 1)
        self.assertEqual(st.book.boost, [], "過ぎた区間は捨てる")
        w.close()

    def test_length_hint_from_human_records(self):
        """M10: 入口が src/eval/tools/eval_marks.py --json の結果(スタジオの作業データ evals/marks/)から目安を作る(length_hint)→ config.json の lengthHint →
        見本が足りれば新しく受け持つ録画の長さ・前の割合をそれに(lengthFrom human)、足りなければスタジオの設定(45 秒)"""
        env = {"YTT_DATA_DIR": os.path.join(self.tmp, "data")}
        marks = os.path.join(self.tmp, "data", "studio", "evals", "marks")
        os.makedirs(marks)

        def result(name, **suggest):
            s = dict({"length": 123, "preRatio": 0.55, "samples": 24, "videos": 6, "enough": True}, **suggest)
            with open(os.path.join(marks, name), "w", encoding="utf-8") as f:
                json.dump({"clipLength": {"suggest": s}}, f)
        now = time.time()
        self.assertIsNone(W.length_hint(env=env))   # 結果がまだ無い
        result(time.strftime("%Y%m%d-%H%M%S", time.localtime(now - 40 * 86400)) + ".json")
        self.assertIsNone(W.length_hint(env=env, now=now))   # 30 日より古い
        result(time.strftime("%Y%m%d-%H%M%S", time.localtime(now - 3600)) + "_auto.json")
        h = W.length_hint(env=env, now=now)
        self.assertEqual((h["length"], h["preRatio"], h["samples"], h["videos"], h["enough"]), (123.0, 0.55, 24, 6, True))
        self.assertIsNone(W.length_hint(env=dict(env, YTT_LIVE_LENGTH="off"), now=now))
        self.assertEqual(W.clean_hint(h), {"length": 120.0, "preRatio": 0.55, "samples": 24, "videos": 6, "file": h["file"]})   # 120 秒に丸める
        for bad in (dict(h, enough=False), dict(h, samples=19), dict(h, videos=4), dict(h, length="x"), dict(h, samples=True), None, [1]):
            self.assertIsNone(W.clean_hint(bad), bad)
        self.assertEqual(W.clean_hint(dict(h, length=3, preRatio=None)), {"length": 10.0, "samples": 24, "videos": 6, "file": h["file"]})
        for hint, want_len, want_pre, src in ((dict(h, length=96.4), 96.0, 0.55, "human"), (dict(h, samples=6, enough=False), 45.0, excite.PRE_RATIO_DEFAULT, "studio")):
            folder = os.path.join(self.tmp, "w-" + src)
            clock = Clock(T0)
            sim = SimRecorder(clock)
            w = make_worker(write_config(folder, lengthHint=hint), clock, sim)
            run_until(w, clock, sim, T0 + 1300)
            st = w.recs[("fake", REC)]
            self.assertEqual((st.book.length, st.book.pre, st.spec["lengthFrom"]), (want_len, want_pre, src))
            d = peaks_of(folder)
            self.assertEqual((d["length"], d["lengthFrom"]), (want_len, src))
            p = [x for x in d["peaks"] if not x["endPending"]][0]
            self.assertLess(abs((p["end"] - p["start"]) - want_len), want_len * 0.31, p)   # 候補の区間 ≈ その長さ(静かな所に合わせる分だけずれる)
            write_config(folder, lengthHint=dict(h, length=30))   # 受け持っている録画の長さは途中で変えない
            w.cfg_checked = -1e18
            clock.t += 6
            w.tick()
            self.assertEqual(w.recs[("fake", REC)].book.length, want_len)
            w.close()

    def test_late_start_has_no_huge_remeasure(self):
        """録画の途中(3 時間目)で受け持つ: 頭から今までを「飛ばした区間」にしない(測り直さない)・1 周期は短く、心拍が出る"""
        clock = Clock(T0 + 3 * 3600)
        sim = SimRecorder(clock, end=3 * 3600 + 600)
        w = make_worker(write_config(self.dir), clock, sim, heart_sec=0.0)
        t0 = time.time()
        w.tick()
        self.assertLess(time.time() - t0, 10.0)
        st = w.recs[("fake", REC)]
        self.assertEqual(st.skipped, [])
        self.assertTrue(3 * 3600 - 120 <= st.late_from <= 3 * 3600, st.late_from)
        self.assertIn("途中", st.message)
        with open(os.path.join(self.dir, "worker.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["at"], W.epoch_iso(clock.t))
        run_until(w, clock, sim, T0 + 3 * 3600 + 900)
        d = peaks_of(self.dir)
        self.assertTrue(d["ended"])
        self.assertEqual((d["skipped"], d["lateFrom"]), ([], st.late_from))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "fake", REC, "skipped.jsonl")))
        self.assertTrue(all(p["peak"] > st.late_from for p in d["peaks"]), [p["peak"] for p in d["peaks"]])
        w.close()

    def test_remeasure_in_chunks_with_heartbeat(self):
        """飛ばした区間の測り直しは 60 秒分ずつ: 時間切れ(1 周期 20 秒)で戻って次の周期で続き(pos)・まとまりごとに心拍・行は重ならない"""
        clock = Clock(T0)
        sim = SimRecorder(clock, end=3000)
        slow = {"on": False}
        w = make_worker(write_config(self.dir), clock, sim)
        real, beat = sim.measure, w.heartbeat
        beats = []

        def measure(client, rec, batch):   # 配信が終わってからの測り直しは 1 回 6 秒かかる(時計を進める)
            if slow["on"]:
                clock.t += 6.0
            return real(client, rec, batch)

        def heartbeat(now, force=False, message=None):
            if force:
                beats.append(now)
            return beat(now, force, message)
        w._measure, w.heartbeat = measure, heartbeat
        run_until(w, clock, sim, T0 + 600)
        sim.down = True
        run_until(w, clock, sim, T0 + 1500)
        sim.down = False
        run_until(w, clock, sim, T0 + 2950)
        st = w.recs[("fake", REC)]
        self.assertEqual(len(st.skipped), 1)
        slow["on"] = True
        ticks, partial = 0, 0
        while ("fake", REC) in w.recs and ticks < 40:
            clock.t += 30
            start = clock.t
            w.tick()
            ticks += 1
            self.assertLessEqual(clock.t - start, W.TICK_BUDGET + 12, "1 周期は時間切れで戻る")
            if not st.skipped[0]["done"] and st.skipped[0].get("pos"):
                partial += 1
        self.assertGreaterEqual(partial, 2, "何周期かに分けて測り直した(進み pos を残して)")
        self.assertGreaterEqual(len(beats), 12, "まとまりごとに心拍")
        self.assertLessEqual(max([b - a for a, b in zip(beats, beats[1:]) if b - a < 25] or [99.0]), 6.5)
        self.assertIn(("fake", REC), w.done)
        with open(os.path.join(self.dir, "fake", REC, "skipped.jsonl"), encoding="utf-8") as f:
            rows = [json.loads(x) for x in f]
        t0s = [r["t0"] for r in rows]
        self.assertEqual(len(t0s), len(set(t0s)), "同じまとまりを 2 回書かない")
        self.assertEqual(t0s, sorted(t0s))
        sk = st.skipped[0]
        self.assertGreater(sum(len(r["full"]) for r in rows), sk["to"] - sk["from"] - 10)
        w.close()

    def test_remeasure_is_capped(self):
        """1 つの飛ばした区間で測り直すのは REMEASURE_MAX_SEC(30 分)まで(capped)"""
        sk = {"from": 0, "to": 4000, "since": 0, "until": 1000, "done": False}
        clock = Clock(T0 + 4200)
        sim = SimRecorder(clock)
        w = make_worker(write_config(self.dir), clock, sim)
        st = W.RecState(os.path.join(self.dir, "fake", REC), "fake", REC, URL, T0, dict(W.SPEC_DEFAULT), {"sens": "normal", "perHour": 6}, False)
        self.assertTrue(w._remeasure(st, sim, sk, clock.t + 3600))
        self.assertTrue(sk["done"] and sk["capped"], sk)
        self.assertTrue(W.REMEASURE_MAX_SEC <= sk["sec"] <= W.REMEASURE_MAX_SEC + W.BIG_BATCH_SEC + 8, sk)
        w.close()

    def test_one_broken_recording_does_not_stop_others(self):
        """1 本の録画で思わぬ例外 → その録画の message と心拍の error に出し、ほかの録画は進める。同じエラーのログは 1 回だけ"""
        clock = Clock(T0)
        a, b = SimRecorder(clock), SimRecorder(clock, first=T0 + 30, rec=REC_B, url="https://www.youtube.com/watch?v=bbbbbbbbbbb")
        sim = MultiSim([a, b])
        logs = []

        def measure(client, rec, batch):
            if rec == REC_B:
                raise RuntimeError("こわれた")
            return a.measure(client, rec, batch)
        w = make_worker(write_config(self.dir), clock, sim, measure_batch=measure, log=logs.append, heart_sec=0.0)
        run_until(w, clock, sim, T0 + 1300)
        self.assertGreaterEqual(len(peaks_of(self.dir)["peaks"]), 2)   # 1 本目は進む
        st = w.recs[("fake", REC_B)]
        self.assertIn("こわれた", st.message)
        self.assertGreater(st.errors, 5)
        self.assertEqual(len([m for m in logs if "こわれた" in m]), 1, "同じエラーは 1 回だけログ")
        with open(os.path.join(self.dir, "worker.json"), encoding="utf-8") as f:
            self.assertIn("こわれた", json.load(f)["error"])
        w.close()

    def test_decision_for_peak_not_yet_seen_waits(self):
        """まだ帳簿に無い候補(すぐ先の番号)の決定では decN を進めない(起動し直して候補が出ていないうちに人が決めた分を消さない)。
        候補がその番号を越えて出てきたら(= 形の違う決定)飛ばして先へ"""
        clock = Clock(T0)
        sim = SimRecorder(clock)
        w = make_worker(write_config(self.dir), clock, sim)
        run_until(w, clock, sim, T0 + 1300)
        st = w.recs[("fake", REC)]
        known = st.book.order[0]
        dec = {"v": 1, "n": 2, "items": [{"n": 1, "id": "p%d-99999" % st.book.n_ids, "state": "dismissed"}, {"n": 2, "id": known, "state": "dismissed"}]}
        fsio.atomic_write(os.path.join(self.dir, "fake", REC, "decisions.json"), json.dumps(dec).encode("utf-8"))
        clock.t += 6
        w.tick()
        self.assertEqual((st.dec_n, st.book.peaks[known]["state"] == "dismissed"), (0, False))
        run_until(w, clock, sim, T0 + 2600)   # 候補が増えて番号を越えた
        self.assertEqual((st.dec_n, st.book.peaks[known]["state"]), (2, "dismissed"))
        w.close()

    def test_bad_numbers(self):
        self.assertEqual([levels.level(x) for x in ("nan", "inf", "-inf", "1e400", "50", "-12.5", "-120", "x")], [-90.0, -90.0, -90.0, -90.0, levels.LEVEL_MAX, -12.5, -90.0, -90.0])
        with self.assertRaises(ValueError):
            W.write_json(os.path.join(self.tmp, "x.json"), {"a": float("nan")})
        self.assertEqual((tools.why(ValueError("nan")), tools.why(OSError(28, "空きがありません"))), ("ValueError", "空きがありません"))   # 書けなかった理由(ValueError には strerror が無い)
        self.assertEqual(W.clean_requests({"fake/" + REC: {"length": 10 ** 400}}), {"fake/" + REC: {"sens": "normal", "perHour": 6, "length": None}})   # float にできない巨大な数は「無い」(schemas.is_num)
        st = W.RecState(self.tmp, "fake", REC, URL, T0, dict(W.SPEC_DEFAULT), {}, False)
        st.place(T0 + 10 ** 7, 4.0, [-30.0] * 4, [-40.0] * 4)   # 受信時刻が何年も先: 埋めずに続けて置く
        self.assertEqual(st.next_box, 4)
        st.fill(10 ** 9)
        self.assertEqual(st.next_box, 4 + W.FILL_MAX)

    def test_friend_request_only_with_its_settings(self):
        """2-15: detectAll false = 友人の依頼の録画(requests)だけ受け持つ。感度・枠・長さはその依頼の値(peaks.json の perHour・length・lengthFrom friend)。
        detectAll true にすれば、ほかの録画はホームの設定で・依頼の録画は依頼の設定のまま(読み直しでも)。false に戻せば、ほかの録画は保存して手放す"""
        clock = Clock(T0)
        a = SimRecorder(clock)
        b = SimRecorder(clock, first=T0 + 60, rec=REC_B, url="https://www.youtube.com/watch?v=bbbbbbbbbbb")
        sim = MultiSim([a, b])
        home = {"sens": "low", "perHour": 5}
        reqs = {"fake/" + REC_B: {"sens": "high", "perHour": 2, "length": 30}}
        cfg = write_config(self.dir, detect=home, detectAll=False, requests=reqs)
        w = make_worker(cfg, clock, sim)
        run_until(w, clock, sim, T0 + 1300)
        self.assertEqual(sorted(w.recs), [("fake", REC_B)])
        self.assertFalse(os.path.exists(os.path.join(self.dir, "fake", REC)))   # ほかの録画は測らない(peaks.json も置かない)
        self.assertEqual(a.measured, 0)
        st = w.recs[("fake", REC_B)]
        self.assertEqual((st.book.thr, st.book.per_hour, st.book.length, st.spec["lengthFrom"]), (excite.SENS["high"], 2, 30.0, "friend"))
        with open(os.path.join(self.dir, "fake", REC_B, "peaks.json"), encoding="utf-8") as f:
            d = json.load(f)
        self.assertEqual((d["perHour"], d["length"], d["lengthFrom"]), (2, 30.0, "friend"))
        self.assertGreaterEqual(len([p for p in d["peaks"] if p["state"] == "frame"]), 1, d["counts"])
        self.assertTrue(all(n <= 2 for n in d["counts"].values()), d["counts"])
        p = [x for x in d["peaks"] if not x["endPending"]][0]
        self.assertLess(abs((p["end"] - p["start"]) - 30.0), 30.0 * 0.31, p)   # 候補の区間 ≈ 依頼の長さ
        w.close()
        w = make_worker(cfg, clock, sim)   # 起動し直しても(state.json から)依頼の感度・枠のまま
        run_until(w, clock, sim, T0 + 1330)
        st = w.recs[("fake", REC_B)]
        self.assertEqual((st.book.thr, st.book.per_hour, st.book.length), (excite.SENS["high"], 2, 30.0))
        # ホームの検出もオンにした: ほかの録画はホームの設定(低・5 本・スタジオの長さ)で受け持ち、依頼の録画は依頼の設定のまま
        write_config(self.dir, detect=home, detectAll=True, requests=reqs)
        w.cfg_checked = -1e18
        run_until(w, clock, sim, T0 + 1400)
        sa = w.recs[("fake", REC)]
        self.assertEqual((sa.book.thr, sa.book.per_hour, sa.book.length, sa.spec["lengthFrom"]), (excite.SENS["low"], 5, 45.0, "studio"))
        self.assertEqual((st.book.thr, st.book.per_hour), (excite.SENS["high"], 2))
        # 依頼の設定が変わった(読み直し): 感度・枠は途中から、長さは受け持っている録画では変えない
        write_config(self.dir, detect=home, detectAll=True, requests={"fake/" + REC_B: {"sens": "normal", "perHour": 4, "length": 60}})
        w.cfg_checked = -1e18
        clock.t += 6
        w.tick()
        self.assertEqual((st.book.thr, st.book.per_hour, st.book.length), (excite.SENS["normal"], 4, 30.0))
        self.assertEqual((sa.book.thr, sa.book.per_hour), (excite.SENS["low"], 5))
        # ホームの検出をオフに戻した(detectAll false): ほかの録画は保存して手放す。依頼の録画は続ける
        write_config(self.dir, detect=home, detectAll=False, requests=reqs)
        w.cfg_checked = -1e18
        n = a.measured
        clock.t += 6
        w.tick()
        self.assertEqual(sorted(w.recs), [("fake", REC_B)])
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "fake", REC, "state.json")))   # オンに戻せば続きから
        run_until(w, clock, sim, T0 + 1500)
        self.assertEqual(a.measured, n)
        self.assertEqual(sorted(w.recs), [("fake", REC_B)])
        w.close()

    def test_worker_bundles(self):
        """RS7-2 G2b: 束のある録画(config.json の bundles)は録画を始めたときの束の解析の設定(spec)・感度・枠で受け持つ。
        友人の依頼の録画は依頼の感度・枠が先・束の無い録画はホームの設定とスタジオの設定のまま"""
        clock = Clock(T0)
        a = SimRecorder(clock)
        b = SimRecorder(clock, first=T0 + 60, rec=REC_B, url="https://www.youtube.com/watch?v=bbbbbbbbbbb")
        sim = MultiSim([a, b])
        home = {"sens": "low", "perHour": 5}
        bundles = {"fake/" + REC: {"spec": dict(W.SPEC_DEFAULT, length=30.0, lagAuto=False), "sens": "high", "perHour": 2}}
        cfg = write_config(self.dir, detect=home, bundles=bundles)
        w = make_worker(cfg, clock, sim)
        run_until(w, clock, sim, T0 + 300)
        sa, sb = w.recs[("fake", REC)], w.recs[("fake", REC_B)]
        self.assertEqual((sa.book.thr, sa.book.per_hour, sa.book.length, sa.spec["lagAuto"]), (excite.SENS["high"], 2, 30.0, False))
        self.assertEqual((sb.book.thr, sb.book.per_hour, sb.book.length, sb.spec["lagAuto"]), (excite.SENS["low"], 5, 45.0, True))
        write_config(self.dir, detect=home, bundles=bundles, requests={"fake/" + REC: {"sens": "normal", "perHour": 4, "length": 60}})
        w.cfg_checked = -1e18
        clock.t += 6
        w.tick()
        self.assertEqual((sa.book.thr, sa.book.per_hour), (excite.SENS["normal"], 4))   # 友人の依頼の設定が先
        w.close()
        k = "fake/" + REC
        self.assertEqual(W.clean_bundles({k: {"spec": {"length": 50, "lagAuto": "x"}, "sens": "nope", "perHour": "3"}}),
                         {k: {"spec": dict(W.SPEC_DEFAULT, length=50.0), "sens": "normal", "perHour": 6}})
        for bad in (None, [], "x", {"noslash": {}}, {5: {}}, {k: "x"}, {k: None}):
            self.assertEqual(W.clean_bundles(bad), {}, bad)

    def test_clean_requests(self):
        """config.json の requests の検査: 鍵は「録画元/録画」の文字列・中身は辞書だけ。感度・枠は clean_detect と同じ、長さは 10〜120 秒(外は None = スタジオの長さ)"""
        k = "fake/" + REC
        self.assertEqual(W.clean_requests({k: {"sens": "high", "perHour": 3, "length": 30}}), {k: {"sens": "high", "perHour": 3, "length": 30.0}})
        for bad in (None, [], "x", 5, {"noslash": {"sens": "high"}}, {5: {"sens": "high"}}, {k: "x"}, {k: None}, {k: [1]}):
            self.assertEqual(W.clean_requests(bad), {}, bad)
        got = W.clean_requests({"fake/a": {"sens": "max", "perHour": True, "length": 9.9}, "fake/b": {"perHour": 2.5, "length": 121},
                                "fake/c": {"length": 10}, "fake/d": {"length": 120.0}, "fake/e": {"length": float("nan")}, "fake/f": {"length": "45"},
                                "fake/g": {"length": True}, "fake/h": {}})
        self.assertEqual(got, {"fake/a": {"sens": "normal", "perHour": 6, "length": None}, "fake/b": {"sens": "normal", "perHour": 6, "length": None},
                               "fake/c": {"sens": "normal", "perHour": 6, "length": 10.0}, "fake/d": {"sens": "normal", "perHour": 6, "length": 120.0},
                               "fake/e": {"sens": "normal", "perHour": 6, "length": None}, "fake/f": {"sens": "normal", "perHour": 6, "length": None},
                               "fake/g": {"sens": "normal", "perHour": 6, "length": None}, "fake/h": {"sens": "normal", "perHour": 6, "length": None}})
        cfg = write_config(self.dir, requests={k: {"sens": "low", "perHour": 1, "length": 200}, "broken": {"sens": "high"}})   # 読み込みでも通す
        w = make_worker(cfg, Clock(T0), SimRecorder(Clock(T0)))
        self.assertEqual((w.cfg["requests"], w.cfg["detectAll"]), ({k: {"sens": "low", "perHour": 1, "length": None}}, True))   # detectAll が無い = 全部(今までどおり)
        self.assertEqual((w._detect_for("fake", REC), w._detect_for("fake", REC_B)), ({"sens": "low", "perHour": 1}, {"sens": "normal", "perHour": 6}))
        w.close()


class SameAsExportTest(unittest.TestCase):
    """ワーカー(live_excite_worker。別のプロセス)と入口の live_export が、録画元との約束(id の形・時刻の書き方・動画の id)に
    同じ物(ytt/recproto.py)を使う(以前は写しを持っていて、値の一致をここで確かめていた。docs/design/code-review-simplify-2026-10-08.md の
    4 節の 7・T8)。値そのものの検査は src/ytt/tests/test_ytt_core.py の RecprotoTest"""

    def test_same_objects(self):
        from ytt import recproto
        for w, lx, core in ((W.ID_RE, LX.ID_RE, recproto.RECORDER_ID_RE), (W.REC_RE, LX.REC_RE, recproto.REC_ID_RE),
                            (W.SEG_URI_RE, LX.SEG_URI_RE, recproto.SEG_URI_RE), (W.iso_epoch, LX.iso_epoch, recproto.iso_epoch),
                            (W.epoch_iso, LX.epoch_iso, recproto.epoch_iso), (W.video_id, LX.video_id_of, recproto.video_id_of)):
            self.assertIs(w, core)
            self.assertIs(lx, core)


class NoNumpyTest(unittest.TestCase):
    def test_no_numpy_in_portal_or_worker(self):
        """入口のプロセス(live・live_detect)とワーカー(live_excite_worker)は numpy を読まない(0-10-2)"""
        code = "import sys; sys.path[:0] = [%r, %r]; import live, launch; import flow.live_detect, pipeline.analyze.live_excite_worker; print('numpy' in sys.modules)" % (HERE, SRC)
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=60, env=dict(os.environ, YTT_DATA_DIR="inplace"))
        self.assertEqual(r.stdout.decode().strip().splitlines()[-1], "False", r.stderr.decode("utf-8", "replace"))


if __name__ == "__main__":
    unittest.main()
