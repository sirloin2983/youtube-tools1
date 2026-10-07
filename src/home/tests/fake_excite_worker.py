# -*- coding: utf-8 -*-
"""偽の検出ワーカー(e2e 用)。本物の src/home/live_excite_worker.py の代わりに入口(live_detect.Detector)が起動し、
テストが置いた指示 <excite>/fake_control.json の候補を、本物と同じ形で peaks.json・worker.json に書く(decisions.json も本物と同じに当てる)。
音・チャット・録画元には触らない(候補の API・帯・採用の道を、ワーカーの計算抜きで通すため)。

指示 fake_control.json: {"recorder": "local", "recording": "<録画 id>", "seq": 10, "peaks": [{id, start, end, peak, score, parts, reasons, confirmedAt, hour, state, endPending}],
                          "set": {"<id>": "<state>"}(テストが途中で変える。seq を進めて changes に出す), "worker": {"behindSec", "chat", "memMB", "message"}}
起動: python fake_excite_worker.py --config <excite>/config.json [--parent <pid>]。入口が止めるまで回る(--parent が消えても終わる。上限 15 分)"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from ytt_core import fsio  # noqa: E402


def iso(now):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)) + ".%03dZ" % int((now % 1) * 1000)


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fsio.atomic_write(path, json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def parent_alive(pid):
    if not pid:
        return True
    if os.name == "nt":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return bool(ok) and code.value == 259   # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--parent", type=int, default=0)
    a = ap.parse_args()
    d = os.path.dirname(os.path.abspath(a.config))
    ctl_path = os.path.join(d, "fake_control.json")
    started = time.time()
    seq, applied, applied_set, changes, peaks, ctl_mtime = 0, 0, {}, [], {}, None
    rc = rec = None
    worker = {}
    heart_at = 0.0
    while time.time() - started < 900 and parent_alive(a.parent):
        now = time.time()
        try:
            m = os.stat(ctl_path).st_mtime
        except OSError:
            m = None
        if m is not None and m != ctl_mtime:
            ctl_mtime = m
            try:
                ctl = fsio.read_json_file(ctl_path, 4 * 1024 * 1024)
            except (OSError, ValueError):
                ctl = None
            if isinstance(ctl, dict):
                rc, rec = ctl.get("recorder"), ctl.get("recording")
                seq = max(seq, int(ctl.get("seq") or 0))
                for p in ctl.get("peaks") or []:
                    if p["id"] not in peaks:
                        seq += 1
                        peaks[p["id"]] = dict(p, seq=seq, origin=p.get("origin"))
                        changes.append({"seq": seq, "id": p["id"], "state": p["state"]})
                for pid, st in (ctl.get("set") or {}).items():
                    if pid in peaks and applied_set.get(pid) != (st, ctl_mtime):
                        applied_set[pid] = (st, ctl_mtime)
                        if peaks[pid]["state"] != st:
                            seq += 1
                            peaks[pid].update(state=st, seq=seq)
                            changes.append({"seq": seq, "id": pid, "state": st})
                worker = ctl.get("worker") or {}
        if rc and rec:
            folder = os.path.join(d, rc, rec)
            try:
                dec = fsio.read_json_file(os.path.join(folder, "decisions.json"), 8 * 1024 * 1024)
            except (OSError, ValueError):
                dec = None
            # 本物の PeakBook.decide を簡単にした当て方(戻すは枠へ。テストが置いた候補だけなので、知らない id は飛ばす)
            for it in sorted((dec or {}).get("items") or [], key=lambda x: x.get("n", 0)):
                if not isinstance(it.get("n"), int) or it["n"] <= applied:
                    continue
                applied = it["n"]
                p = peaks.get(it.get("id"))
                if p is None:
                    continue
                st = it.get("state")
                if st == "adopted":
                    p.update(state="adopted", origin=it.get("origin") or "manual", markId=it.get("markId"), jobId=it.get("jobId"))
                elif st == "dismissed":
                    p.update(state="dismissed", origin=None)
                elif st == "restore":
                    p.update(state="frame", origin=None)
                seq += 1
                p["seq"] = seq
                changes.append({"seq": seq, "id": p["id"], "state": p["state"]})
            counted = sum(1 for p in peaks.values() if p["state"] == "frame" or (p["state"] == "adopted" and p.get("origin") == "auto"))
            doc = {"v": 1, "recorder": rc, "recording": rec, "seq": seq, "decN": applied, "perHour": 6, "counts": {"0": counted} if peaks else {},
                   "lag": 8, "chat": worker.get("chat", "ok"), "behindSec": worker.get("behindSec", 35), "at": iso(now), "first": iso(started),
                   "measuredSec": 0, "scoredSec": 0, "gaps": 0, "skipped": [], "lateChat": 0, "ended": False, "message": "",
                   "peaks": list(peaks.values()), "changes": changes[-500:]}
            write_json(os.path.join(folder, "peaks.json"), doc)
        if now - heart_at >= 1.0:
            heart_at = now
            active = [{"recorder": rc, "id": rec, "behindSec": worker.get("behindSec", 35), "chat": worker.get("chat", "ok")}] if rc and rec else []
            write_json(os.path.join(d, "worker.json"),
                       {"v": 1, "version": "fake", "pid": os.getpid(), "at": iso(now), "started": iso(started), "behindSec": worker.get("behindSec", 35),
                        "memMB": worker.get("memMB", 42), "chatRestarts": 0, "recordings": active,
                        "message": worker.get("message", "1 本の録画を見ています" if active else "録画中の配信はありません"), "error": None})
        time.sleep(0.3)
    return 0


if __name__ == "__main__":
    sys.exit(main())
