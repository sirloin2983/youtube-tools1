# -*- coding: utf-8 -*-
"""録画の知らせ(10-30 まとめ役。ユーザー「3 は任せる」): 録画が始まらない・途中で止まって戻らない・欠けが大きい とき、
友人の依頼の録画なら友人の Dropbox の 出力 に .失敗.txt を 1 つ(flow/deliver.write_failure)、どの録画も「調子」の失敗の一覧(live_failures の record)に出す。

出来事(録画ごと・出来事ごとに 1 回だけ。覚えは入口の作業データの live/rec-alerts.json):
  a  録画が始まらなかった(1 つも録れないまま終わった = 録画元の記録の endKind notStarted か、セグメント 0 で終わった)
  b  録画が途中で終わって戻らなかった(endKind blocked・disk・crash・resume、録れた後のエラー、録画元が NOANSWER_SEC 答えないまま)。
     データが来ないまま IDLE_END で終わった(idle)は数えない(この PC の録画の部品の記録で 27 回中 22 回がふつうの配信の終わりだった。10-30)
  c  録画は終わったが、欠け(録画済みの範囲の間)の合計が GAP_SEC 以上
手で止めた(stopped)録画は知らせない。この仕組みを入れる前に終わった録画は知らせない(覚えの since より前)。
友人の画面: a は「失敗」(friendapp/progress の liveNoRec。自動のやり直しはしない)、b・c は行の知らせ(REC_NOTE_HEAD で始まる文 = 行の状態は変えない)
"""
import datetime
import os
import threading
import time

from ytt import fsio, recproto
from . import deliver as _deliver
from . import live_failures

ON = True                    # 戻すスイッチ(偽 = 知らせない。plan/スイッチの台帳.md)
GAP_SEC = 300                # c の目安: 欠けの合計がこれ以上(5 分。根拠と測り直しは decisions の 10-30)
NOANSWER_SEC = 600           # b: 録画中の録画の録画元がこの秒答えないまま(録画の部品の IDLE_END と同じ 10 分)
KEEP_SEC = 7 * 24 * 3600     # 覚えを残す期間(調子に出す期間 live_failures.WINDOW_SEC と同じ)
RETRY_SEC = 24 * 3600        # Dropbox のフォルダが見えないとき、置くのを試し続ける期間
HOLES_SHOW = 3               # 友人の文に書く欠けの数(長い順)
REC_NOTE_HEAD = "ライブ(録画の知らせ):"      # b・c の文の頭(友人のアプリはこの頭の .失敗.txt を行の知らせにする = friendapp/inbox)
NO_REC_HEAD = "ライブ(録画が始まらない):"   # a の文の頭(友人のアプリの失敗の種類 liveNoRec = friendapp/progress)
BAD_END = ("blocked", "disk", "crash", "resume")
FILE = "rec-alerts.json"


def clock_text(t):
    """epoch -> 「10/30 21:05」(地方時)"""
    d = datetime.datetime.fromtimestamp(t)
    return "%d/%d %02d:%02d" % (d.month, d.day, d.hour, d.minute)


def event_of(r):
    """録画元の一覧の 1 行(livesession.list_recordings の形。終わった録画)-> ("a" | "b" | None, 理由)"""
    kind, state = r.get("endKind"), r.get("state")
    if kind == "stopped" or state == "stopped" or r.get("active"):
        return None, ""
    why = str(r.get("message") or "").strip()
    if kind == "notStarted" or (state in ("ended", "error") and not r.get("segments")):
        return "a", why
    if kind in BAD_END or state == "error":
        return "b", why
    return None, ""


def holes_of(r):
    """終わった録画の欠け -> (合計の秒, [(から, まで)](epoch・長い順))。録画元が古い版で数えていなければ (None, [])"""
    if not isinstance(r.get("holeSec"), (int, float)):
        return None, []
    out = []
    for h in r.get("holes") or []:
        a, b = recproto.iso_epoch((h or {}).get("from")), recproto.iso_epoch((h or {}).get("to"))
        if a is not None and b is not None and b > a:
            out.append((a, b))
    return float(r["holeSec"]), out


def friend_text(ev, title, why, r, holes=None, since=None):
    """友人が読む文(.失敗.txt の中身)。ev = a・b・c。r = 録画元の一覧の行"""
    name = "「%s」" % title if title else "この配信"
    if ev == "a":
        t0 = r.get("created")
        return ("%s %sの録画が始まりませんでした%s。\r\n録れていない時間: %sから全部\r\nこの配信の切り抜きは届きません(アーカイブが出たら URL で送ると切り抜けます)。"
                % (NO_REC_HEAD, name, "(%s)" % why if why else "", clock_text(t0) + " " if t0 else "録画を頼んだ時"))
    if ev == "b":
        t0 = since or r.get("lastPdt")
        return ("%s %sの録画が途中で止まり、戻りませんでした%s。\r\n録れていない時間: %sから配信の終わりまで\r\nこの間の切り抜きは届かないので、届くパックが少なくなります。"
                % (REC_NOTE_HEAD, name, "(%s)" % why if why else "", clock_text(t0) + " " if t0 else "途中"))
    sec, spans = holes
    shown = "、".join("%s〜%s" % (clock_text(a), clock_text(b)[-5:]) for a, b in spans[:HOLES_SHOW])
    more = "(ほか %d か所)" % (len(spans) - HOLES_SHOW) if len(spans) > HOLES_SHOW else ""
    return ("%s %sの録画に、合わせて約 %d 分の欠けがありました。\r\n録れていない時間: %s%s\r\nこの間の切り抜きは届かないので、届くパックが少なくなります。"
            % (REC_NOTE_HEAD, name, round(sec / 60), shown, more))


class RecAlerts:
    """録画の知らせの見回り(入口の見回りから tick)。読むのは録画元の一覧と友人の依頼の結びつき、書くのは rec-alerts.json と友人の 出力 の .失敗.txt だけ"""

    def __init__(self, store_dir, request, log=None, clock=time.time, write=None, outbox_ok=None):
        """request(録画元, 録画) -> 友人の依頼(live_rules.RequestBook の項目 {rid, deliverDir, title, …})か None。
        write(出力のフォルダ, 名前, 文) -> 置けたか(既定 deliver.write_failure)。テストは偽物の口にする(本物の Dropbox へ置かない)"""
        self.path = os.path.join(store_dir, FILE)
        self.request = request
        self.log = log or (lambda m: None)
        self.clock = clock
        self.write = write or _deliver.write_failure
        self.outbox_ok = outbox_ok or _deliver.outbox_ok
        self.lock = threading.Lock()
        self._data = None
        self._down = {}   # 録画元 -> 答えなくなった時刻(この入口の間だけ)

    def _load(self):
        if self._data is None:
            d = fsio.read_json_or(self.path, None, max_bytes=2 * 1024 * 1024, kind=dict)
            self._data = d if isinstance(d, dict) and isinstance(d.get("items"), dict) else {"v": 1, "since": None, "items": {}}
        return self._data

    def _save(self):
        fsio.write_json(self.path, self._data)

    def tick(self, recs, down=()):
        """recs = livesession.list_recordings の一覧・down = 答えなかった録画元の id -> 新しく知らせた数"""
        if not ON:
            return 0
        now = self.clock()
        with self.lock:
            d = self._load()
            changed = False
            if d.get("since") is None:   # 入れる前に終わった録画は知らせない
                d["since"], changed = now, True
            items = d["items"]
            for rc in list(self._down):
                if rc not in down:
                    self._down.pop(rc)
            for rc in down:
                self._down.setdefault(rc, now)
            new = 0
            for r in recs:
                key = "%s/%s" % (r.get("recorder"), r.get("id"))
                it = items.get(key)
                if r.get("active"):
                    if it is None or not it.get("active"):
                        items[key] = dict(it or {"recorder": r.get("recorder"), "recording": r.get("id"), "done": {}}, active=True, title=r.get("title") or "")
                        changed = True
                    items[key]["seenAt"] = now   # 覚えの中だけ(書くのは変わったとき)
                    continue
                ended = r.get("endedAt") or r.get("lastPdt") or now
                if it is None:
                    if ended < d["since"]:
                        continue
                    it = items[key] = {"recorder": r.get("recorder"), "recording": r.get("id"), "done": {}}
                    changed = True
                if it.get("active") or "ended" not in it:
                    it.update(active=False, ended=ended, title=r.get("title") or it.get("title") or "")
                    changed = True
                ev, why = event_of(r)
                if ev and ev not in it["done"] and not (ev == "a" and "b" in it["done"]):
                    new += self._raise(it, ev, why, r, now)
                    changed = True
                if ev != "a" and "c" not in it["done"]:
                    sec, spans = holes_of(r)
                    if sec is not None and sec >= GAP_SEC:
                        new += self._raise(it, "c", "", r, now, holes=(sec, spans))
                        changed = True
                    elif sec is not None:
                        it["done"]["c"] = {"at": now, "none": True}   # 欠けは小さい(数え直さない)
                        changed = True
            for key, it in items.items():   # 録画中だった録画の録画元が答えないまま
                rc = it.get("recorder")
                if it.get("active") and rc in self._down and now - self._down[rc] >= NOANSWER_SEC and "b" not in it["done"]:
                    t0 = max(self._down[rc], 0)
                    new += self._raise(it, "b", "録画元が %d 分以上答えません" % (NOANSWER_SEC // 60), {"recorder": rc, "id": it.get("recording")}, now, since=t0)
                    changed = True
            changed = self._resend(items, now) or changed
            for key in [k for k, it in items.items() if not it.get("active") and now - (it.get("ended") or now) > KEEP_SEC]:
                items.pop(key)
                changed = True
            if changed:
                self._save()
            return new

    def _raise(self, it, ev, why, r, now, holes=None, since=None):
        """出来事を 1 つ記録する(友人の依頼なら .失敗.txt も置く)-> 1"""
        title = it.get("title") or r.get("title") or ""
        req = self.request(it.get("recorder"), it.get("recording")) or {}
        text = friend_text(ev, title, why, r, holes=holes, since=since)
        out = {"at": now, "text": text, "friend": bool(req.get("rid")), "sent": False}
        if req.get("rid") and req.get("deliverDir"):
            out.update(rid=req["rid"], dir=req["deliverDir"], name=_deliver.delivery_name(req["rid"], "%s(録画の知らせ %s)" % (title or "ライブ", ev)))
            out["sent"] = self._put(out)
        it["done"][ev] = out
        self.log("リアルタイム切り抜き: 録画 %s の知らせ(%s): %s" % (it.get("recording"), ev, " ".join(text.split())[:200]))
        return 1

    def _put(self, out):
        if not self.outbox_ok(out["dir"]):
            return False
        try:
            return bool(self.write(out["dir"], out["name"], out["text"]))
        except OSError:
            return False

    def _resend(self, items, now):
        """Dropbox のフォルダが見えなくて置けなかった知らせを置き直す(RETRY_SEC まで)"""
        changed = False
        for it in items.values():
            for ev in it["done"].values():
                if ev.get("dir") and not ev.get("sent") and now - ev.get("at", now) <= RETRY_SEC and self._put(ev):
                    ev["sent"] = changed = True
        return changed

    def failures(self, now=None):
        """「調子」の失敗の一覧に足す分(live_failures.record_failure の形・新しい物から)"""
        now = self.clock() if now is None else now
        with self.lock:
            items = [dict(i, done=dict(i.get("done") or {})) for i in self._load()["items"].values()]
        out = []
        for it in items:
            for ev, x in it["done"].items():
                if x.get("none") or now - x.get("at", 0) > live_failures.WINDOW_SEC:
                    continue
                out.append(live_failures.record_failure(ev, x.get("text") or "", it.get("recorder") or "", it.get("recording") or "",
                                                         friend=x.get("friend"), sent=x.get("sent"),
                                                         at=recproto.epoch_iso(x["at"]) if isinstance(x.get("at"), (int, float)) else ""))
        return out
