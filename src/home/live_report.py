# -*- coding: utf-8 -*-
"""配信(録画)ごとの結果の記録(線 D の D-12。10-08 ユーザー決定。長い配信の確かめ U4 と、数の決め直し D-15・当たり具合 L5 の材料)。

入口の見回り(src/home/live.py の Live.tick。30 秒ごと)から tick() が呼ばれ、録画ごとに 1 つの JSON を
入口の作業データの live/reports/<録画元>__<録画の id>.json に置く(書き手はここだけ。読むのは dev/eval_marks.py --live と人)。
  録画中  … EVERY 秒ごとに書き直す(state "recording")。最大値(遅れ・メモリ・ワーカーの遅れ)は見回りのたびに取って残す(入口を起動し直しても前の最大値から続ける)
  終わり  … 録画が終わって、ワーカーが帳簿を締めた(peaks.json の ended)か FINISH_DELAY 秒たったら最後に 1 回書く(state "done")。
            終わって END_WINDOW 秒より古い録画は書かない(昔の録画を見回りのたびに読まない)
中身(数えるだけ。どのファイルも書き換えない。壊れていれば None):
  recorder・recording(id)と info {title, url, firstPdt, lastPdt, endedAt, hours}
  samples    {ticks, behindMax, behindLast, memMaxMB, memLastMB, lagMax, lagLast, restarts, chatRestarts, chat(いちばん悪い状態)}   ← 遅れ・メモリ(D-12)
  detect     {frame, bench, dismissed, adopted, adoptedAuto, adoptedManual, givenUp, gaps, perHour, counts(時間ごとの枠の数), ended}   ← 候補と採用の数
  tx         {ok, error, empty, secMedian, secMax, pending}                                                                   ← 配信中の文字起こしの成否
  exports    {total, byState, failures, waitSecMedian, waitSecMax, origins}   ← 書き出しの待ち(ジョブを作ってから済むまでの秒。done のジョブだけ)
  disk       {state, rows: [{label, drive, freeGB}]}                           ← 空き(最後に見たとき)
  request    {rid, streamer} か None(友人のライブ配信の依頼の録画)
  state・startedAt・updatedAt・finishedAt
dev/eval_marks.py --live はこの JSON と live_feedback.jsonl(採用・届けた・要らない・detect_compare)を合わせて、配信中とアーカイブの候補・採用率を並べる。
"""
import json
import os
import time

from ytt import fsio
import live_export as LX  # noqa: E402
import live_failures  # noqa: E402

REPORT_DIR = "reports"
EVERY = 60.0                 # 録画中に書き直す間隔
END_WINDOW = 2 * 86400.0     # 終わってからこれより古い録画は見ない
FINISH_DELAY = 600.0         # 終わってから、ワーカーが締めていなくても最後に書くまでの秒
CHAT_ORDER = ("none", "restarting", "ok", "off")
DOC_MAX = 4 * 1024 * 1024
MAX_REPORTS = 200            # 残す数(古いものから消す)


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _median(xs):
    xs = sorted(x for x in xs if _num(x))
    return round(xs[len(xs) // 2], 1) if xs else None


def _mx(a, b):
    """最大値(どちらかが無ければある方)"""
    if not _num(a):
        return b if _num(b) else None
    return max(a, b) if _num(b) else a


def _worst_chat(a, b):
    """チャットの状態 2 つのうち悪い方(CHAT_ORDER の先が悪い。知らない値は無視)"""
    xs = [x for x in (a, b) if x in CHAT_ORDER]
    return min(xs, key=CHAT_ORDER.index) if xs else "off"


def key_of(rc, rec):
    return "%s__%s" % (rc, rec)


class Reporter:
    def __init__(self, live, clock=time.time, every=EVERY, end_window=END_WINDOW, finish_delay=FINISH_DELAY):
        """live: src/home/live.py の Live(list_recordings・detector・livetx・exporter・requests・store_dir)。時間はテストで縮める"""
        self.live = live
        self.clock, self.every, self.end_window, self.finish_delay = clock, every, end_window, finish_delay
        self._last = -1e18
        self._done = set()   # 最後まで書いた録画(見回りのたびに読み直さない)

    @property
    def dir(self):
        return os.path.join(self.live.store_dir, REPORT_DIR)

    def path(self, rc, rec):
        return os.path.join(self.dir, key_of(rc, rec) + ".json")

    def load(self, rc, rec):
        d = fsio.read_json_or(self.path(rc, rec), None, DOC_MAX, kind=dict)
        return d if isinstance(d, dict) and d.get("v") == 1 else None

    # ---- 見回り
    def tick(self, force=False):
        """-> 書いた録画の数"""
        if not self.live.enabled():
            return 0
        now = self.clock()
        if not force and now - self._last < self.every:
            return 0
        self._last = now
        n = 0
        for r in self.live.list_recordings():
            if not LX.ID_RE.match(r.get("recorder") or "") or not LX.REC_RE.match(r.get("id") or ""):
                continue
            key = key_of(r["recorder"], r["id"])
            if r.get("active"):
                self._done.discard(key)
                if self._write(r, now, final=False):
                    n += 1
                continue
            if key in self._done:
                continue
            ended = r.get("endedAt") if _num(r.get("endedAt")) else r.get("lastPdt")
            if not _num(ended) or now - ended > self.end_window:
                continue
            prev = self.load(r["recorder"], r["id"])
            if prev is not None and prev.get("state") == "done":
                self._done.add(key)
                continue
            if prev is None and not _num(r.get("firstPdt")):   # 録画の中身が無いまま終わった(何も測っていない)
                self._done.add(key)
                continue
            doc, _peaks, _p = self.live.detector.view(r["recorder"], r["id"])
            final = bool((doc or {}).get("ended")) or now - ended >= self.finish_delay
            if self._write(r, now, final=final):
                n += 1
                if final:
                    self._done.add(key)
        return n

    # ---- 1 本
    def _write(self, r, now, final):
        rc, rec = r["recorder"], r["id"]
        prev = self.load(rc, rec) or {}
        try:
            rep = self.build(r, prev, now, final)
        except Exception as e:   # noqa: BLE001  (記録の不具合で見回りを止めない)
            self.live.note("リアルタイム切り抜き: 配信の記録を作れませんでした(%s): %r" % (rec, e))
            return False
        try:
            os.makedirs(self.dir, exist_ok=True)
            fsio.atomic_write(self.path(rc, rec), json.dumps(rep, ensure_ascii=False, indent=1).encode("utf-8"))
        except OSError as e:
            self.live.note("リアルタイム切り抜き: 配信の記録を書けませんでした(%s): %s" % (rec, e.strerror or e.__class__.__name__))
            return False
        if final:
            self.live.log("リアルタイム切り抜き: 配信の記録を残しました %s(%s)" % (rec, self.summary(rep)))
            self._trim()
        return True

    def build(self, r, prev, now, final):
        rc, rec = r["recorder"], r["id"]
        live = self.live
        doc, peaks, _pending = live.detector.view(rc, rec)
        doc = doc or {}
        hb = live.detector.heartbeat() or {}
        mine = next((x for x in hb.get("recordings") or [] if isinstance(x, dict) and x.get("recorder") == rc and x.get("id") == rec), None)
        ps = prev.get("samples") if isinstance(prev.get("samples"), dict) else {}
        behind = (mine or {}).get("behindSec") if mine else doc.get("behindSec")
        chat = (mine or {}).get("chat") or doc.get("chat") or ps.get("chat") or "off"
        samples = {"ticks": int(ps.get("ticks") or 0) + 1,
                   "behindMax": _mx(ps.get("behindMax"), behind), "behindLast": behind if _num(behind) else ps.get("behindLast"),
                   "memMaxMB": _mx(ps.get("memMaxMB"), hb.get("memMB")), "memLastMB": hb.get("memMB") if _num(hb.get("memMB")) else ps.get("memLastMB"),
                   "lagMax": _mx(ps.get("lagMax"), doc.get("lag")), "lagLast": doc.get("lag") if _num(doc.get("lag")) else ps.get("lagLast"),
                   "restarts": max(int(ps.get("restarts") or 0), int(live.detector.restarts or 0)),
                   "chatRestarts": max(int(ps.get("chatRestarts") or 0), int(hb.get("chatRestarts") or 0)),
                   "chat": _worst_chat(chat, ps.get("chat"))}
        dec = live.detector._decisions(live.detector.folder(rc, rec))["items"]
        adopted = [x for x in dec if x.get("state") == "adopted"]
        fails = [x for x in live.detector._load_fails() if x.get("recorder") == rc and x.get("recording") == rec]
        detect = {"frame": sum(1 for p in peaks if p.get("state") == "frame"), "bench": sum(1 for p in peaks if p.get("state") == "bench"),
                  "dismissed": sum(1 for p in peaks if p.get("state") == "dismissed"), "adopted": sum(1 for p in peaks if p.get("state") == "adopted"),
                  "adoptedAuto": sum(1 for x in adopted if x.get("origin") == "auto"), "adoptedManual": sum(1 for x in adopted if x.get("origin") != "auto"),
                  "givenUp": len(fails), "gaps": doc.get("gaps"), "perHour": doc.get("perHour"), "counts": doc.get("counts") if isinstance(doc.get("counts"), dict) else {},
                  "ended": bool(doc.get("ended")), "measured": doc is not None and bool(doc)}
        txv = live.livetx.items(rc, rec) or {}
        secs = [v.get("sec") for v in txv.values() if isinstance(v, dict) and "error" not in v]
        tx = {"ok": sum(1 for v in txv.values() if isinstance(v, dict) and "error" not in v and (v.get("text") or "").strip()),
              "empty": sum(1 for v in txv.values() if isinstance(v, dict) and "error" not in v and not (v.get("text") or "").strip()),
              "error": sum(1 for v in txv.values() if isinstance(v, dict) and "error" in v),
              "secMedian": _median(secs), "secMax": max([s for s in secs if _num(s)] or [None]) if any(_num(s) for s in secs) else None,
              "pending": sum(1 for p in peaks if p.get("state") in ("frame", "bench", "adopted") and p.get("id") not in txv)}
        jobs = live.exporter.snapshot(rc, rec) if os.path.isfile(os.path.join(live.store_dir, "exports.json")) else []
        waits = []
        for j in jobs:
            if j.get("state") == "done":
                a, b = LX.iso_epoch(j.get("created")), LX.iso_epoch(j.get("updated"))
                if a is not None and b is not None and b >= a:
                    waits.append(round(b - a, 1))
        by_state, origins = {}, {}
        for j in jobs:
            by_state[j.get("state") or "?"] = by_state.get(j.get("state") or "?", 0) + 1
            origins[j.get("origin") or "manual"] = origins.get(j.get("origin") or "manual", 0) + 1
        exports = {"total": len(jobs), "byState": by_state, "origins": origins,
                   "failures": sum(1 for j in jobs if live_failures.failure_of(j) is not None),
                   "waitSecMedian": _median(waits), "waitSecMax": max(waits) if waits else None}
        try:
            d = live.exporter.disk()
            disk = {"state": d.get("state"), "rows": [{"label": x.get("label"), "drive": x.get("drive"), "freeGB": round(float(x.get("freeBytes") or 0) / 2 ** 30, 1)}
                                                     for x in d.get("rows") or []]}
        except Exception:   # noqa: BLE001
            disk = None
        req = live.requests.get(rc, rec)
        first, last = r.get("firstPdt"), r.get("lastPdt")
        ended = r.get("endedAt") if _num(r.get("endedAt")) else (last if not r.get("active") else None)
        hours = round((last - first) / 3600.0, 2) if _num(first) and _num(last) and last >= first else None
        return {"v": 1, "recorder": rc, "recording": rec, "state": "done" if final else "recording",
                "startedAt": prev.get("startedAt") or LX.now_iso(), "updatedAt": LX.now_iso(), "finishedAt": LX.now_iso() if final else None,
                "info": {"title": r.get("title") or "", "url": r.get("url") or "", "firstPdt": LX.epoch_iso(first) if _num(first) else None,
                         "lastPdt": LX.epoch_iso(last) if _num(last) else None, "endedAt": LX.epoch_iso(ended) if _num(ended) else None, "hours": hours},
                "samples": samples, "detect": detect, "tx": tx, "exports": exports, "disk": disk,
                "request": {"rid": req.get("rid"), "streamer": req.get("streamer")} if req else None}

    @staticmethod
    def summary(rep):
        """記録の 1 行(入口の記録・eval_marks --live の表)"""
        s, d, t, e = rep.get("samples") or {}, rep.get("detect") or {}, rep.get("tx") or {}, rep.get("exports") or {}
        h = (rep.get("info") or {}).get("hours")
        return "%s時間・候補 %d(控え %d・見送り %d)・採用 %d(自動 %d)・諦め %d・文字 %d/%d・書き出し %d(失敗 %d。待ち中央 %s 秒)・遅れ最大 %s 秒・メモリ最大 %s MB" % (
            ("%.1f " % h) if _num(h) else "? ", d.get("frame", 0) + d.get("adopted", 0), d.get("bench", 0), d.get("dismissed", 0),
            d.get("adoptedAuto", 0) + d.get("adoptedManual", 0), d.get("adoptedAuto", 0), d.get("givenUp", 0),
            t.get("ok", 0), t.get("ok", 0) + t.get("empty", 0) + t.get("error", 0), e.get("total", 0), e.get("failures", 0),
            e.get("waitSecMedian") if e.get("waitSecMedian") is not None else "-", s.get("behindMax") if s.get("behindMax") is not None else "-",
            s.get("memMaxMB") if s.get("memMaxMB") is not None else "-")

    def _trim(self):
        try:
            names = sorted(n for n in os.listdir(self.dir) if n.endswith(".json"))
        except OSError:
            return
        for n in names[:-MAX_REPORTS] if len(names) > MAX_REPORTS else []:
            try:
                os.remove(os.path.join(self.dir, n))
            except OSError:
                pass

    def all(self):
        """全部の記録(dev/eval_marks.py --live と同じ読み方。新しい順)"""
        out = []
        try:
            names = os.listdir(self.dir)
        except OSError:
            return out
        for n in names:
            if n.endswith(".json"):
                d = fsio.read_json_or(os.path.join(self.dir, n), None, DOC_MAX, kind=dict)
                if isinstance(d, dict) and d.get("v") == 1:
                    out.append(d)
        out.sort(key=lambda x: x.get("startedAt") or "", reverse=True)
        return out
