# -*- coding: utf-8 -*-
"""「編集」のサーバーの部品: 音の波形(カットのタイムライン)(段10 で editor/serve.py から分けた。docs/plan/phase10-code-split.md)。

名前は serve.py からも見える(serve.py が受け付けて、この部品へ転送する。テストの S.名前 = … もここに入る)。
ほかの部品の名前は `ed_xxx.名前` の形で呼ぶたびに読む(差し替えが効くように。from … import はしない)。
"""
import array
import bisect
import difflib
import faulthandler
import gc
import hashlib
import itertools
import json
import logging
import logging.handlers
import math
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave

from ytt_core import datadir as _datadir, fsio as _fsio, httpsec, layout as _layout, jobs as _heavy, runtime as _runtime, schemas as _yschemas, tools as _tools  # noqa: E402,F401
import roster as _roster  # noqa: E402,F401
import ed_misc  # noqa: E402,F401
import ed_state  # noqa: E402,F401
import ed_store  # noqa: E402,F401
# ---------- 音の波形(カットのタイムライン用。docs/design/edit-tool-design.md の 5・8) ----------
# ffmpeg で 8kHz・モノラルの 16bit にして、区切りごとの最大の振れ幅を 0〜255(平方根で小さい声も見えるように)の1バイトに。
# numpy は使わない(サーバーのプロセスで読み込まない決まり)。重い処理なので ytt_core.jobs.SLOTS を通し、画面は 202 の間くり返し問い合わせる
PEAKS_VERSION = 1
PEAKS_SR = 8000
PEAKS_TIMEOUT = 600
_peaks_tasks = {}   # 鍵 -> {"sig", "state": waiting|running|done|error, "message", "code", "at"}
_peaks_lock = threading.Lock()
_PEAK_LUT = None


def peaks_rate(duration):
    """1秒あたりの数。長い動画は下げる(10分まで 100 = 10ミリ秒ごと、1時間まで 50、それより長いと 20)"""
    d = duration or 0
    return 100 if d <= 600 else 50 if d <= 3600 else 20


def _peaks_files(path):
    h = hashlib.sha1(os.path.normcase(path).encode("utf-8", "surrogatepass")).hexdigest()[:24]
    d = os.path.join(ed_state.DATA_DIR, "cache", "peaks")
    return d, os.path.join(d, h + ".bin"), os.path.join(d, h + ".json")


def compute_peaks(path, task=None):
    """-> (波形のバイト列, 1秒あたりの数, 長さ秒)。音声が無ければ空のバイト列"""
    global _PEAK_LUT
    ff = ed_state.find_ffmpeg()
    if not ff:
        raise ed_state.ApiError("no_ffmpeg", "ffmpeg が見つかりません(README の準備手順を確認してください)", 400)
    dur, _has_v, has_a = ed_store.probe_media(path)
    rate = peaks_rate(dur)
    if not has_a:
        return b"", rate, dur or 0.0
    if _PEAK_LUT is None:
        _PEAK_LUT = bytes(min(255, int(255 * math.sqrt(v / 32768.0) + 0.5)) for v in range(32769))
    lut, step = _PEAK_LUT, PEAKS_SR // rate
    cmd = [ff, "-hide_banner", "-nostdin", "-loglevel", "error", "-protocol_whitelist", "file", "-i", path,
           "-vn", "-ac", "1", "-ar", str(PEAKS_SR), "-f", "s16le", "-acodec", "pcm_s16le", "-"]
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    err = []
    drain = threading.Thread(target=lambda: err.append(p.stderr.read()[-2000:]), daemon=True)   # エラーの出力でパイプが詰まらないように
    drain.start()
    timer = threading.Timer(PEAKS_TIMEOUT, p.kill)
    timer.start()
    out, buf = bytearray(), b""
    try:
        while True:
            chunk = p.stdout.read(step * 2 * 2000)
            if not chunk:
                break
            buf += chunk
            usable = len(buf) - len(buf) % (step * 2)
            a = array.array("h")
            a.frombytes(buf[:usable])
            buf = buf[usable:]
            if sys.byteorder == "big":
                a.byteswap()
            for i in range(0, len(a), step):
                seg = a[i:i + step]
                out.append(lut[min(32768, max(max(seg), -min(seg)))])
        if len(buf) >= 2:
            a = array.array("h")
            a.frombytes(buf[:len(buf) - len(buf) % 2])
            if sys.byteorder == "big":
                a.byteswap()
            out.append(lut[min(32768, max(max(a), -min(a)))])
        p.wait()
    finally:
        timer.cancel()
        if p.poll() is None:
            p.kill()
            p.wait()
        p.stdout.close()
        drain.join(5)
        p.stderr.close()
    if p.returncode != 0 and not out:
        tail = (err[0] if err else b"").decode("utf-8", "replace").strip().splitlines()[-1:] or [""]
        raise ed_state.ApiError("peaks_failed", "音の波形を作れませんでした: " + tail[0][:200], 500)
    return bytes(out), rate, dur or len(out) / rate


def _peaks_run(key, path, sig, t):
    try:
        with _heavy.SLOTS.slot(ed_state.TOOL_ID, "波形 " + os.path.basename(path)[:40],
                               on_wait=lambda: t.update(state="waiting", message=_heavy.WAIT_MESSAGE)):
            t.update(state="running", message="音の波形を作っています")
            data, rate, dur = compute_peaks(path)
        d, bin_p, meta_p = _peaks_files(path)
        os.makedirs(d, exist_ok=True)
        ed_state.atomic_write(bin_p, data)
        ed_state.atomic_write(meta_p, json.dumps({"sig": sig, "rate": rate, "duration": round(dur, 3), "n": len(data)}).encode("utf-8"))
        t.update(state="done", message="", at=time.time())
    except ed_state.ApiError as e:
        t.update(state="error", code=e.code, message=e.message, at=time.time())
    except Exception as e:   # 想定外でもサーバーは止めない
        ed_state.log.exception("波形の作成で例外")
        t.update(state="error", code="internal", message="内部エラー: %s %s" % (e.__class__.__name__, str(e)[:200]), at=time.time())


def get_peaks(tid):
    """GET /api/peaks?id= -> ("ready", バイト列, 1秒あたりの数, 長さ) か ("busy", {"state", "message"})。
    動画のパスは文書から取る(パスを引数で受けない)。作業データの cache/peaks/ に保存し、動画のパス・大きさ・更新日時が同じなら使い回す"""
    doc = ed_store.read_transcript(tid)
    try:
        path = ed_state.check_source(doc.get("sourcePath"))
        st = os.stat(path)
    except (ed_state.ApiError, OSError):
        raise ed_state.ApiError("source_missing", "元の動画・音声が見つかりません(移動・削除した可能性があります)", 404)
    sig = [os.path.normcase(path), st.st_size, st.st_mtime_ns, PEAKS_VERSION]
    _d, bin_p, meta_p = _peaks_files(path)
    meta = ed_misc._read_json_file(meta_p)
    if isinstance(meta, dict) and meta.get("sig") == sig:
        try:
            with open(bin_p, "rb") as f:
                data = f.read()
            if len(data) == meta.get("n"):
                return "ready", data, meta["rate"], meta["duration"]
        except OSError:
            pass
    key = sig[0]
    with _peaks_lock:
        t = _peaks_tasks.get(key)
        if t and t["sig"] == sig and t["state"] in ("waiting", "running"):
            return "busy", {"state": t["state"], "message": t["message"]}
        if t and t["sig"] == sig and t["state"] == "error" and time.time() - t["at"] < 30:
            raise ed_state.ApiError(t["code"], t["message"], 500 if t["code"] == "internal" else 400)
        t = {"sig": sig, "state": "waiting", "message": "音の波形を作る準備をしています", "code": "", "at": time.time()}
        _peaks_tasks[key] = t
        for k in [k for k, v in _peaks_tasks.items() if v["state"] in ("done", "error") and time.time() - v["at"] > 600]:
            _peaks_tasks.pop(k, None)
    threading.Thread(target=_peaks_run, args=(key, path, sig, t), daemon=True, name="peaks").start()
    return "busy", {"state": t["state"], "message": t["message"]}
