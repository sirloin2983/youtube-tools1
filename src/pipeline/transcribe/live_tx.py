"""配信中の候補の文字起こし(線 D の D-11 案 b。ホーム 0.48.0。plan/line-d-live-clipping.md の 0-11。2026-10-08 ユーザー決定「b をやる」)。

配信中の検出(src/home/live_detect.py)の候補が確定するたびに、その区間の音を録画元から取り(書き出し src/home/live_export.py と同じセグメント)、
16kHz モノラルの wav にして子プロセス src/home/live_tx_worker.py(編集の whisper.cpp・Vulkan = GPU)で認識し、
live/excite/<録画元>/<録画>/tx.json に残す({"v": 1, "items": {候補の id: {"text", "rows", "sec", "gpu", "model", "at"} か {"error", "at", "tries"}}})。
候補の API(GET /live/api/peaks。live_detect.Detector.api_get)が候補に text を足してスタジオの帯に出し、採用の記録(live_feedback.jsonl)にも text を残す(C2 の材料)。
**字幕の正本は今までどおり書き出したあとの文字起こし**(短い区切りは精度が落ちる。ここは候補を見て決めるための文字)。

設定(ホームの設定の節 live): liveTx {enabled(既定オン), model(既定 large-v3)}。動くのは リアルタイム切り抜きがオン・whisper.cpp(setup/build-whisper-vulkan.bat)と
モデル(編集の作業データの models/whispercpp/)がある・ffmpeg がある、のときだけ(ready)。無ければ何もしない(候補に文字が付かないだけ)。
守り: 1 本ずつ(同時に 1 つの子プロセス)・1 本 TX_TIMEOUT 秒まで・同じ候補は TX_TRIES 回まで・続けて FAIL_PAUSE_AFTER 回失敗したら PAUSE_SEC 休む(GPU の不調で回り続けない)。
認識(GPU)は重い処理の順番(ytt_core.jobs.SLOTS。tool "live-tx")を通す(D-14。10-08 決定): 書き出し・文字起こし・パックと同じ枠で順番を待つ
(配信中の文字起こしが whisper.cpp の GPU を、書き出したあとの本番の文字起こしと取り合わない)。待っている間は status の slotWait。入口の終了で待ちをやめる。
入口の見回り(Live.tick。30 秒ごと)が tick() で候補を見つけて列に入れ、裏のスレッドが 1 本ずつ処理する。
"""
import os
import shutil
import subprocess
import threading
import time

from ytt import datadir, fsio, jobs, tools
import live_export as LX

WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "live_tx_worker.py")
# whisper.cpp の置き場所(編集の tx_engines.WHISPER_CPP["version"]・wcpp_bin_dir・wcpp_model_dir・WCPP_MODELS と同じ値。入口は編集の部品を import しないので値を持つ。test_live_tx が同じことを確かめる)
WCPP_VERSION = "v1.9.4"
WCPP_EXE = "whisper-cli.exe" if os.name == "nt" else "whisper-cli"
WCPP_MODEL_FILES = {"large-v3": "ggml-large-v3.bin", "large-v3-turbo": "ggml-large-v3-turbo.bin"}
DEFAULT_MODEL = "large-v3"
TX_STATES = ("frame", "bench", "adopted")   # 文字を付ける候補の状態(仮の候補・終わり待ち・見送りは付けない)
TX_TIMEOUT = 240.0        # 子プロセス 1 本の上限(秒。45〜120 秒の音は GPU で 10〜20 秒)
TX_TRIES = 2              # 同じ候補を試す回数
FAIL_PAUSE_AFTER = 3      # 続けてこの回数失敗したら休む
PAUSE_SEC = 600.0         # 休む秒
RECENT_SEC = 120.0        # API の差分(changes)に「文字が付いた候補」として入れる、付けてからの秒
TEXT_MAX = 2000
DOC_MAX = 2 * 1024 * 1024


def wav_args(ffmpeg, src, dst, ss, dur):
    """セグメントをつないだ .ts から、候補の区間の 16kHz モノラルの wav を作る ffmpeg の引数(whisper の入力)"""
    return [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", "%.3f" % max(0.0, ss), "-i", src, "-t", "%.3f" % max(0.5, dur),
            "-vn", "-sn", "-dn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-f", "wav", dst]


class LiveTx:
    def __init__(self, live, log=None, clock=time.time, python=None, run=None, ffmpeg=None, slots=None):
        """live: src/home/live.py の Live(設定・録画元・exporter(セグメントの取得)・detector(候補)・root)。
        run(data_dir, model, wav) -> 子プロセスの結果の dict(テストは偽物に差し替える。既定 = live_tx_worker.py を子プロセスで)。ffmpeg: パス(既定は探す)。
        slots: 重い処理の順番(既定 ytt_core.jobs.SLOTS。テストは小さな HeavySlots を渡す)"""
        self.live = live
        self.log = log or (lambda m: None)
        self.clock = clock
        self.python = python
        self.run = run or self._run_worker
        self.ffmpeg = ffmpeg
        self.slots = slots or jobs.SLOTS
        self.slot_wait = False     # 重い処理の枠を待っている(status の slotWait)
        self.lock = threading.Lock()
        self.queue = []            # [(rc, rec, 候補の dict, first(録画の頭の epoch))]
        self.queued = set()        # (rc, rec, id)
        self.tries = {}            # (rc, rec, id) -> 試した回数(メモリ。tx.json の tries と合わせる)
        self.wake = threading.Event()
        self._halt = threading.Event()
        self.thread = None
        self.proc = None
        self.busy = None           # 処理中の (rc, rec, id)
        self.fails = 0             # 続けて失敗した数
        self.pause_until = 0.0
        self.done = 0
        self.failed = 0
        self._docs = {}            # (rc, rec) -> tx.json の中身(メモリ。書くたびに更新)
        self._ready_note = None

    # ---- 設定・準備
    def cfg(self):
        v = self.live.cfg().get("liveTx")
        v = v if isinstance(v, dict) else {}
        model = v.get("model") if isinstance(v.get("model"), str) and v.get("model") in WCPP_MODEL_FILES else DEFAULT_MODEL   # 形の違う値(list など)でも落ちない
        return {"enabled": v.get("enabled") is not False, "model": model}

    def data_dir(self):
        """編集の作業データ(whisper.cpp とモデルの置き場所。ytt_core.datadir.resolve = txindex.folder と同じ決め方)"""
        return datadir.resolve("transcribe", self.live.root)

    def paths(self):
        d = self.data_dir()
        model = self.cfg()["model"]
        return {"exe": os.path.join(d, "bin", "whisper.cpp-%s-vulkan" % WCPP_VERSION, WCPP_EXE),
                "model": os.path.join(d, "models", "whispercpp", WCPP_MODEL_FILES[model]), "dataDir": d}

    def ready(self):
        """(使えるか, 使えない理由)。オフ・リアルタイム切り抜きがオフ・whisper.cpp が無い・モデルが無い・ffmpeg が無い"""
        if not self.cfg()["enabled"]:
            return False, "オフ(設定 live.liveTx)"
        if not self.live.enabled():
            return False, "リアルタイム切り抜きがオフ"
        p = self.paths()
        if not os.path.isfile(p["exe"]):
            return False, "whisper.cpp がありません(setup\\build-whisper-vulkan.bat で作ります)"
        if not os.path.isfile(p["model"]):
            return False, "モデル %s がありません(編集で GPU の文字起こしを 1 回すると取得されます)" % os.path.basename(p["model"])
        if not self._ffmpeg():
            return False, "ffmpeg がありません"
        return True, ""

    def _ffmpeg(self):
        return self.ffmpeg or tools.find_tool("ffmpeg", "YTT_FFMPEG")

    def status(self):
        ok, why = self.ready()
        with self.lock:
            return {"enabled": self.cfg()["enabled"], "ready": ok, "message": why, "model": self.cfg()["model"], "busy": bool(self.busy),
                    "queued": len(self.queue), "done": self.done, "failed": self.failed, "slotWait": self.slot_wait,
                    "pausedUntil": LX.epoch_iso(self.pause_until) if self.pause_until > self.clock() else None}

    # ---- 記録(tx.json)
    def folder(self, rc, rec):
        return self.live.detector.folder(rc, rec)

    def _load(self, rc, rec):
        key = (rc, rec)
        if key not in self._docs:
            d = fsio.read_json_or(os.path.join(self.folder(rc, rec), "tx.json"), None, DOC_MAX, kind=dict)
            items = d.get("items") if d else None
            self._docs[key] = {k: v for k, v in items.items() if isinstance(v, dict)} if isinstance(items, dict) else {}
        return self._docs[key]

    def _save(self, rc, rec):
        try:
            fsio.write_json(os.path.join(self.folder(rc, rec), "tx.json"), {"v": 1, "items": self._docs[(rc, rec)]}, indent=None)
        except OSError as e:
            self.log("配信中の文字起こし: 記録を書けませんでした(%s)" % tools.why(e))

    def view(self, rc, rec):
        """候補の id -> {"text", "at", ...}(文字の付いたものだけ。API が候補に足す)"""
        with self.lock:
            return {k: dict(v) for k, v in self._load(rc, rec).items() if v.get("text")}

    def items(self, rc, rec):
        """候補の id -> 記録の全部(済み・文字が空・失敗 {"error", "tries"} も。配信ごとの記録 src/home/live_report.py が成否を数える)"""
        with self.lock:
            return {k: dict(v) for k, v in self._load(rc, rec).items()}

    def text_for(self, rc, rec, pid):
        with self.lock:
            v = self._load(rc, rec).get(pid) if isinstance(pid, str) else None
            return v.get("text") if v else None

    def recent_ids(self, rc, rec, within=RECENT_SEC):
        """最近 within 秒に文字が付いた候補の id(API の差分 changes に入れる = 画面の行に文字が出る)"""
        now = self.clock()
        with self.lock:
            return [k for k, v in self._load(rc, rec).items() if v.get("text") and isinstance(v.get("atEpoch"), (int, float)) and now - v["atEpoch"] <= within]

    def record(self, rc, rec, pid, text, rows=None, sec=None, gpu="", model=""):
        """文字を残す(テスト・画面の確認でも使う)"""
        with self.lock:
            items = self._load(rc, rec)
            items[pid] = {"text": str(text)[:TEXT_MAX], "rows": list(rows or [])[:200], "sec": sec, "gpu": gpu or "", "model": model or self.cfg()["model"],
                          "at": LX.now_iso(), "atEpoch": self.clock()}
            self._save(rc, rec)
            return dict(items[pid])

    def _record_error(self, rc, rec, pid, why):
        with self.lock:
            items = self._load(rc, rec)
            prev = items.get(pid) or {}
            items[pid] = {"error": str(why)[:300], "at": LX.now_iso(), "atEpoch": self.clock(), "tries": int(prev.get("tries") or 0) + 1}
            self._save(rc, rec)

    # ---- 見回り(Live.tick から 30 秒ごと)
    def tick(self):
        """録画中の録画の確定した候補のうち、まだ文字の無いものを列に入れて裏のスレッドを起こす。-> 入れた数(オフ・準備なしは 0)"""
        ok, why = self.ready()
        if not ok:
            if why != self._ready_note and self.cfg()["enabled"] and self.live.enabled():
                self.log("配信中の文字起こし: %s" % why)
            self._ready_note = why
            return 0
        self._ready_note = None
        if self.clock() < self.pause_until:
            return 0
        added = 0
        try:
            recs = self.live.list_recordings()
        except Exception as e:   # noqa: BLE001  (録画元につながらない: 次の見回りで)
            self.log("配信中の文字起こし: 録画の一覧を読めませんでした: %r" % (e,))
            return 0
        for r in recs:
            if not r.get("active") or not isinstance(r.get("firstPdt"), (int, float)):
                continue
            rc, rec = r["recorder"], r["id"]
            try:
                _doc, peaks, _p = self.live.detector.view(rc, rec)
            except Exception:   # noqa: BLE001
                continue
            with self.lock:
                items = self._load(rc, rec)
                for pk in peaks:
                    pid = pk.get("id")
                    if not isinstance(pid, str) or pk.get("state") not in TX_STATES or pk.get("provisional") or pk.get("endPending"):
                        continue
                    if not isinstance(pk.get("start"), (int, float)) or not isinstance(pk.get("end"), (int, float)):
                        continue
                    key = (rc, rec, pid)
                    cur = items.get(pid)
                    if (cur and "error" not in cur) or key in self.queued or key == self.busy:   # 済み(認識できた。文字が空 = 声の無い区間も済み)は入れ直さない
                        continue
                    if int((cur or {}).get("tries") or 0) >= TX_TRIES:
                        continue
                    self.queue.append((rc, rec, dict(pk), float(r["firstPdt"])))
                    self.queued.add(key)
                    added += 1
        if added:
            self.start()
            self.wake.set()
        return added

    def start(self):
        if self.thread is None or not self.thread.is_alive():
            self._halt.clear()
            self.thread = threading.Thread(target=self._loop, name="live-tx", daemon=True)
            self.thread.start()

    def close(self):
        self._halt.set()
        self.wake.set()
        p = self.proc
        if p is not None:
            tools.kill_quiet(p)

    def _loop(self):
        while not self._halt.is_set():
            with self.lock:
                item = self.queue.pop(0) if self.queue else None
                if item:
                    self.busy = (item[0], item[1], item[2]["id"])
                    self.queued.discard(self.busy)
            if item is None:
                self.wake.wait(30.0)
                self.wake.clear()
                continue
            rc, rec, pk, first = item
            try:
                self._one(rc, rec, pk, first)
            except Exception as e:   # noqa: BLE001  (1 本の不具合で止めない)
                self.log("配信中の文字起こし: %s の %s でエラー: %r" % (rec, pk.get("id"), e))
                self._after(rc, rec, pk["id"], False, "内部エラー: %s" % e.__class__.__name__)
            finally:
                with self.lock:
                    self.busy = None

    def _after(self, rc, rec, pid, ok, why=""):
        if ok:
            self.fails, self.done = 0, self.done + 1
            return
        self.failed += 1
        self.fails += 1
        self._record_error(rc, rec, pid, why)
        self.log("配信中の文字起こし: %s の候補 %s に文字を付けられませんでした: %s" % (rec, pid, why))
        if self.fails >= FAIL_PAUSE_AFTER:
            self.pause_until = self.clock() + PAUSE_SEC
            self.fails = 0
            self.log("配信中の文字起こし: 続けて %d 回失敗したので %d 分休みます" % (FAIL_PAUSE_AFTER, int(PAUSE_SEC // 60)))

    # ---- 1 本
    def _one(self, rc, rec, pk, first):
        pid = pk["id"]
        ex = self.live.exporter
        rco = self.live.find(rc)
        if rco is None:
            return self._after(rc, rec, pid, False, "録画元がありません")
        a, b = first + float(pk["start"]), first + float(pk["end"])
        code, d = ex._query(rc, rec, a, b)
        if code != 200 or not isinstance(d, dict):
            return self._after(rc, rec, pid, False, "録画のセグメントを読めません(HTTP %s)" % code)
        segs = [s for s in d.get("segments") or [] if isinstance(s, dict) and LX.SEG_URI_RE.match(str(s.get("uri") or ""))]
        if not segs:
            return self._after(rc, rec, pid, False, "その区間の音がまだありません")
        sess = segs[0].get("session")
        segs = [s for s in segs if s.get("session") == sess]   # つなぎ直しをまたがない(最初のセッションの分だけ)
        wdir = os.path.join(ex.work, "tx-%s-%s" % (rec, pid))
        job = {"id": "tx-" + pid, "recorder": rc, "recording": rec}
        try:
            try:
                files = ex._fetch(job, rco, rec, segs, wdir)
            except OSError as e:   # 録画元が途中で答えない・HTTP の失敗(書き出しの _process と同じく理由にする)
                return self._after(rc, rec, pid, False, "セグメントを取れませんでした(%s)" % e)
            if not files:
                return self._after(rc, rec, pid, False, "セグメントを取れませんでした")
            s0 = LX.iso_epoch(segs[0].get("pdt"))
            ss = max(0.0, a - s0) if s0 is not None else 0.0
            wav = os.path.join(wdir, "in.wav")
            cmd = wav_args(self._ffmpeg(), files[0][0], wav, ss, b - a)
            try:
                p = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120,
                                   creationflags=tools.no_window_flags(priority="low"))
            except (OSError, subprocess.TimeoutExpired) as e:   # ffmpeg が消えた・120 秒で終わらない
                return self._after(rc, rec, pid, False, "wav を作れませんでした(%s)" % e.__class__.__name__)
            if p.returncode != 0 or not os.path.isfile(wav) or os.path.getsize(wav) < 1000:
                return self._after(rc, rec, pid, False, "wav を作れませんでした: %s" % p.stderr.decode("utf-8", "replace")[-200:].strip())
            res = self._run_in_slot(rec, wav)
            if self._halt.is_set():   # 入口の終了で子プロセスを止めた・待ちをやめた: 失敗に数えない(次の起動の見回りでやり直す)
                return None
            if not isinstance(res, dict) or not res.get("ok"):
                return self._after(rc, rec, pid, False, (res.get("reason") or "認識に失敗しました") if isinstance(res, dict) else "答えがありません")
            self.record(rc, rec, pid, res.get("text") or "", res.get("rows"), res.get("sec"), res.get("gpu") or "", res.get("model") or "")
            self.log("配信中の文字起こし: %s の候補 %s に文字を付けました(%.1f 秒・%s)" % (rec, pid, float(res.get("sec") or 0), res.get("gpu") or "GPU"))
            self._after(rc, rec, pid, True)
        except (LX.Cancelled, LX.Halted):
            return
        finally:
            shutil.rmtree(wdir, ignore_errors=True)

    def _run_in_slot(self, rec, wav):
        """重い処理の順番(SLOTS)を取ってから認識する(D-14)。待っている間に入口が終わったら None"""
        def on_wait():
            self.slot_wait = True
            self.log("配信中の文字起こし: %s の認識は、他の重い処理が終わるのを待っています" % rec)
        try:
            with self.slots.slot("live-tx", "配信中の文字起こし %s" % rec, cancelled=self._halt.is_set, on_wait=on_wait) as ok:
                self.slot_wait = False
                if not ok:
                    return None
                return self.run(self.paths()["dataDir"], self.cfg()["model"], wav)
        finally:
            self.slot_wait = False

    def _run_worker(self, data_dir, model, wav):
        """子プロセス(live_tx_worker.py)を動かして結果の json を読む"""
        out = wav + ".json"
        cmd = [tools.python_exe(self.python), WORKER, data_dir, model, wav, out]   # 窓の無い pythonw は隣の python.exe(標準出力を返せないことがある)
        try:   # 起動した子は close() が止める(on_start で覚える)
            r = tools.run(cmd, timeout=TX_TIMEOUT, flags=tools.no_window_flags(priority="low"), stdout=False, on_start=lambda p: setattr(self, "proc", p))
        except OSError as e:
            return {"ok": False, "reason": "子プロセスを起動できませんでした: %s" % e}
        finally:
            self.proc = None
        if r.why == "timeout":
            return {"ok": False, "reason": "%d 秒で終わりませんでした" % int(TX_TIMEOUT)}
        d = fsio.read_json_or(out, None)
        if d is None:
            return {"ok": False, "reason": "結果を読めませんでした(%s)" % (" / ".join(r.err_lines(3)) or "終了コード %s" % r.code)}
        return d if isinstance(d, dict) else {"ok": False, "reason": "結果の形が違います"}
