# -*- coding: utf-8 -*-
"""友人のアプリの状態の書き出しと、そのきっかけ(形の正は notes:plan/友人の不具合の自動対応-1025.md。受け取り側はユーザーの PC の別の部品)。

- 置き方: すぐ送る物(error・stuck・live_end・crash・ask)は送り返しの箱 <data>/app/outbox/ に <依頼 id か app>__state-<ミリ秒 13 桁>.state.json
  (診断と同じ流れ = 同期 friendapp/sync.py が Dropbox の /診断/ へ上げる)。手元の物(trouble・request_end・periodic)は作業データの diag/local/ に
  <ミリ秒>-<trigger>.state.json で置き、/診断/送って/<id>.ask.json の印に答えるとき(trigger ask)に local の配列でまとめて送って消す
- 同じきっかけ(trigger と依頼 id)は DEDUPE_SEC 秒に 1 回。続いている「固まった」は直るまで 1 回
- 大きさ: 1 つ TARGET_BYTES を目安に、長い所(log.tail・screen.texts・requests・ops・local)から切る。MAX_BYTES を超えない
- 入れない物: cookie・キー・パスワード(診断と同じ mask で伏せる。ログインは時刻だけ)・チャットや文字起こしの全文・ファイルの中身・アプリと関係ない PC の情報
- 重い仕事はしない: きっかけは診断を書いたとき(friendapp/diag の on_write)と画面の操作で印を付けるだけで、書くのは玄関の見回り(tick。10 秒ごと)。
  固まったかの見直しは CHECK_EVERY 秒に 1 回、今ある情報(送った物の段の進み・録画元の録画の秒・受付の待ち・箱の古さ)だけで決める
- スイッチは診断と同じ(YTT_FRIEND_DIAG=0・ユーザーの PC の作業データでは書かない)
"""
import collections
import json
import os
import platform
import re
import shutil
import threading
import time

from ytt import fsio as _fsio, tools as _tools, version as _version, ytcookies as _ytcookies

from . import diag as _diag, oplog as _oplog

V = 1
URGENT = ("error", "stuck", "live_end", "crash", "ask", "update")   # update = 新しい版を取れない・起動しない・確かめに通らない・前の版へ戻した(facts.stage)
LOCAL = ("trouble", "request_end", "periodic")
FULL = ("env", "screen", "requests", "jobs", "live", "sync", "settings", "log", "yt", "inbox")
PARTS = {"live_end": ("env", "live", "requests", "jobs"), "request_end": ("env", "requests", "jobs", "sync"), "periodic": ("jobs", "live")}
CODES = ("ok", "yt_fetch_retry", "yt_fetch_gave_up", "zero_cand_filled", "duplicate", "undelivered", "unknown")
YT_FETCH = ("ytFetch", "bot", "rate")      # YouTube から中身が届かない種類(progress.classify の code)
DEDUPE_SEC = 300
TARGET_BYTES = 100 * 1024
ASK_TARGET = 900 * 1024
MAX_BYTES = 1024 * 1024
LOCAL_DIR = os.path.join("diag", "local")
RUN_MARK = os.path.join("diag", "running.json")   # 動いている印(閉じたときに消す。起動のときに残っていれば前回は途中で落ちた)
OUTBOX_MAX = 50                    # 箱に置く状態の数の上限(上げられない間に積もらない。古い物から消す)
LOCAL_MAX = 100
ASK_DIR = "/診断/送って"
ASK_RE = re.compile(r"^([0-9A-Za-z_-]{1,64})\.ask\.json$")
ASK_CAP = 16 * 1024
CHECK_EVERY = 60
PERIODIC_SEC = 1800
STUCK_PROGRESS_SEC = 1800          # 送った物の段の進みがこれだけ変わらない
REC_STILL_SEC = 60                 # 録画中の録画の秒がこれだけ増えない
DROPBOX_STUCK_SEC = 1800           # 受付の待ち・箱の送り返しがこれだけ残る
TROUBLE_CLICKS, TROUBLE_CLICK_SEC = 3, 10
TROUBLE_CANCEL_SEC = 60
TROUBLE_NAV_SEC = 60
REQUEST_HOURS = 24
LOG_TAIL, LOG_READ = 200, 256 * 1024
LINE_MAX = 300
TEXTS_MAX, TEXT_MAX, DIALOGS_MAX, DISABLED_MAX = 80, 120, 10, 40
DIAG_NAMES_SEC = 1800              # 「同じ時間帯の diag」= 前後この秒
ERROR_WORDS = ("失敗", "エラー", "できません", "止まり", "Error", "Exception", "Traceback")
SAFE_ID = _diag.SAFE_ID
OUT_NAMES = (r"\.zip$", r"\.verdict\.json$", r"\.notice\.json$")   # 友人の物の送り返し(診断・状態は数えない)


def fit(doc, target=TARGET_BYTES, hard=MAX_BYTES):
    """doc を target バイトへ寄せる(長い所から切る)-> JSON のバイト。hard を超えれば中身の欄を落として truncated"""
    def size():
        return len(json.dumps(doc, ensure_ascii=False).encode("utf-8"))
    steps = (("log", "tail", 50), ("screen", "texts", 20), ("requests", None, 10), ("ops", None, 100), ("log", "tail", 0),
             ("screen", "texts", 0), ("requests", None, 3), ("ops", None, 20), ("jobs", None, 5))
    for sec, key, keep in steps:
        if size() <= target:
            break
        box = doc.get(sec) if key else doc
        k = key or sec
        if isinstance(box, dict) and isinstance(box.get(k), list) and len(box[k]) > keep:
            box[k] = box[k][-keep:] if keep else []
            doc["truncated"] = True
    while size() > target and doc.get("local"):   # 手元の分は古い物から
        doc["local"].pop(0)
        doc["truncated"] = True
    if size() > hard:
        for k in FULL + ("local", "ops"):
            doc.pop(k, None)
        doc["truncated"] = True
    return json.dumps(doc, ensure_ascii=False).encode("utf-8")


# 友人の段の名前(progress.FRIEND_OF・動画を取得)-> 受け取り側が見分ける段の名前(plan/友人の不具合の自動対応-1025.md)
STAGE_NAME = {"動画を取得": "fetch", "見どころを探す": "detect", "切り抜き": "export", "文字起こし": "transcribe", "仕上げ": "pack"}


def judge(trigger, row, rows=(), live=None):
    """受け取り側の仕分けの欄 -> (codes, facts)。row = 送った物の行(api.view の形)・live = ライブの材料(diag の live の形)"""
    codes, facts = [], {}
    if row:
        fail = row.get("fail") or {}
        st = row.get("state")
        retrying = bool(fail.get("retrying"))
        if fail.get("code"):
            facts["cause"] = fail["code"]
        label = (row.get("steps") or {}).get("label") if isinstance(row.get("steps"), dict) else ""
        facts["stage"] = STAGE_NAME.get(label, label) or st or ""
        packs = len(row.get("packs") or [])
        if packs or st in ("arrived", "done"):
            facts["delivered"] = True
        elif st == "failed" and not retrying and not row.get("cancelled"):
            facts["delivered"] = False
        if st == "failed":
            facts["retry"] = {"scheduled": retrying, "gaveUp": not retrying and (row.get("autoRetries") or 0) > 0}
        if fail.get("code") in YT_FETCH:
            codes.append("yt_fetch_retry" if retrying else "yt_fetch_gave_up")
        if facts.get("delivered") is False:
            codes.append("undelivered")
        if fail.get("code") == "unknown":
            codes.append("unknown")
        vid = (row.get("source") or {}).get("videoId")
        rg = (row.get("form") or {}).get("ranges")
        if vid and any(o.get("id") != row.get("id") and not o.get("cancelled") and (o.get("source") or {}).get("videoId") == vid
                       and (o.get("form") or {}).get("ranges") == rg for o in rows):
            codes.append("duplicate")
    cands = live_cands(live)
    if cands is not None:
        facts["candidates"] = cands
        if cands == 0 and row and (row.get("packs") or []):
            codes.append("zero_cand_filled")
    if not codes and trigger in ("live_end", "request_end") and facts.get("delivered") is not False and (row or {}).get("state") != "failed":
        codes.append("ok")   # 問題なく終わった(空にすると受け取り側が要対応と読む)
    if not codes and trigger in ("error", "stuck", "crash", "update"):
        codes.append("unknown")
    return codes, facts


def live_cands(live):
    pk = (live or {}).get("peaksDoc") if isinstance(live, dict) else None
    n = pk.get("peaks") if isinstance(pk, dict) else None
    return n if isinstance(n, int) and not isinstance(n, bool) else None


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _boot_at_ms():
    """Windows が起動した時刻(ms)。前のアプリが閉じる途中を通らずに終わったとき、PC の再起動だったかを見分ける材料"""
    if os.name != "nt":
        return None
    try:
        import ctypes
        f = ctypes.windll.kernel32.GetTickCount64
        f.restype = ctypes.c_ulonglong
        return int(time.time() * 1000) - int(f())
    except (AttributeError, OSError):
        return None


def dir_bytes(path, limit=50000):
    total, n = 0, 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            n += 1
            if n > limit:
                return total
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


class Reporter:
    """玄関に 1 つ。app = 玄関(api・inbox・sync・engine・settings を読む。無い物の欄は None)・diag = 診断の係(mask とスイッチ)・ops = 操作の記録"""

    def __init__(self, app, places, diag, ops, clock=time.time, log=None):
        self.app, self.places, self.diag, self.ops = app, places, diag, ops
        self.clock = clock
        self.log = log or (lambda msg: None)
        self._lock = threading.Lock()
        self._pending = []
        self._last = {}
        self._stuck_on = set()
        self._diag_names = collections.deque(maxlen=200)
        self._screen_memo = None
        self._checked = 0.0
        self._busy_since = None
        self._runs = {}
        self._recs = {}
        self._ffmpeg = None
        self._born = clock()   # 起動した時刻(閉じていた間は送り返しの待ちに数えない)

    # ---------------------------------------------------------------- 場所・スイッチ
    def enabled(self):
        return self.diag is not None and self.diag.enabled()

    def local_dir(self):
        return os.path.join(self.places["data"], LOCAL_DIR)

    def mask(self, s):
        return self.diag.mask(s) if self.diag is not None else str(s)

    # ---------------------------------------------------------------- きっかけの印(書くのは tick)
    def mark(self, trigger, rid=None, summary="", **info):
        with self._lock:
            self._pending.append((trigger, rid, summary, info))

    def on_diag(self, kind, doc, path):
        """診断を書いた(friendapp/diag の on_write)-> きっかけの印"""
        name = os.path.basename(path or "")
        if name:
            self._diag_names.append((doc.get("at") or 0, name))
        rid, stage = doc.get("requestId"), doc.get("stage")
        trig = None
        if kind == "run":
            trig = "error" if (doc.get("request") or {}).get("state") == "error" else "request_end"
        elif kind == "live":
            trig = {"close": "live_end", "ended": "live_end", "submit": "error", "blocked": "error", "lost": "stuck"}.get(stage)
        elif kind == "rollback":   # exe が起動できない版を飛ばして前の版で起こした
            trig, stage = "update", "rollback"
        elif (kind == "sync" and stage == "更新") or (kind == "update" and stage == "space"):   # 新しい版を取れない
            trig, stage = "update", "update"
        elif kind in ("error", "sync", "setup", "start", "exception"):
            trig = "error"
        if trig:
            self.mark(trig, rid, doc.get("summary") or "", live=doc.get("live"), code=doc.get("code"), stage=stage)

    def started(self):
        """起動したとき(main だけが呼ぶ): 前回の動いている印が残っていれば crash の印。新しい印を書く"""
        p = os.path.join(self.places["data"], RUN_MARK)
        prev = _fsio.read_json_or(p, None, kind=dict)
        if prev is not None and self.enabled():
            self.mark("crash", None, "前回のアプリ(版 %s)が閉じる途中を通らずに終わっていました" % str(prev.get("version") or "?")[:20],
                      prev={k: prev.get(k) for k in ("at", "version", "pid")})
        try:
            _fsio.write_json(p, {"at": int(self.clock() * 1000), "version": _version.VERSION, "pid": os.getpid()}, indent=None)
        except OSError as e:
            self.log("動いている印を書けませんでした: %s" % e.__class__.__name__)

    def stopped(self):
        _fsio.unlink_quiet(os.path.join(self.places["data"], RUN_MARK))

    # ---------------------------------------------------------------- 画面から
    def ui_ops(self, body):
        """POST /api/friend/ops {ops: [...], screen?: {...}} -> 受けた件数。困っている合図・固まった・画面のエラーの印も付ける"""
        b = body if isinstance(body, dict) else {}
        if isinstance(b.get("screen"), dict):
            self.set_screen(b["screen"])
        rows = self.ops.add_ui(b.get("ops"), mask=self.mask)
        for r in rows:
            d = r.get("detail") or {}
            if r["kind"] == "error" and d.get("noResponseSec"):
                self.mark("stuck", None, "ボタン %s のあと %d 秒返事がありません" % (r["target"], d["noResponseSec"]), why="noResponse")
            elif r["kind"] == "error":
                self.mark("error", None, "画面のエラー: %s" % (d.get("message") or ""), why="screen")
            self._trouble(r)
        return len(rows)

    def app_op(self, kind, target, detail=None):
        """玄関が書く操作(request・cancel・job_start・job_end)"""
        r = self.ops.add(kind, target, detail)
        self._trouble(r)
        return r

    def set_screen(self, s):
        name = s.get("name")

        def texts(v, n, cap):
            return [self.mask(str(x)[:cap]) for x in (v if isinstance(v, list) else []) if isinstance(x, str) and x.strip()][:n]
        dis = []
        for x in (s.get("disabled") if isinstance(s.get("disabled"), list) else [])[:DISABLED_MAX]:
            if isinstance(x, dict) and isinstance(x.get("id"), str) and _oplog.TARGET_RE.match(x["id"]):
                dis.append({"id": x["id"], "why": self.mask(str(x.get("why") or "")[:TEXT_MAX])})
        self._screen_memo = {"name": name if isinstance(name, str) and _oplog.TARGET_RE.match(name) else "?", "at": int(self.clock() * 1000),
                        "texts": texts(s.get("texts"), TEXTS_MAX, TEXT_MAX), "dialogs": texts(s.get("dialogs"), DIALOGS_MAX, 200), "disabled": dis}

    def _trouble(self, r):
        """困っている合図(同じボタンを短い間に何度も・送ってすぐ取り消し・同じ画面の行き来)-> trouble の印"""
        recent = self.ops.recent(TROUBLE_NAV_SEC + 5)
        now = r["at"]
        if r["kind"] == "click":
            same = [x for x in recent if x["kind"] == "click" and x["target"] == r["target"] and now - x["at"] <= TROUBLE_CLICK_SEC * 1000]
            if len(same) >= TROUBLE_CLICKS:
                self.mark("trouble", None, "同じボタン %s を %d 秒に %d 回押しました" % (r["target"], TROUBLE_CLICK_SEC, len(same)), why="clicks")
        elif r["kind"] == "cancel":
            if any(x["kind"] == "request" and 0 <= now - x["at"] <= TROUBLE_CANCEL_SEC * 1000 for x in recent):
                self.mark("trouble", (r.get("detail") or {}).get("id"), "送ってすぐ取り消しました", why="cancel")
        elif r["kind"] == "nav":
            navs = [x["target"] for x in recent if x["kind"] == "nav" and now - x["at"] <= TROUBLE_NAV_SEC * 1000][-4:]
            if len(navs) == 4 and navs[0] == navs[2] and navs[1] == navs[3] and navs[0] != navs[1]:
                self.mark("trouble", None, "画面 %s と %s を行き来しています" % (navs[0], navs[1]), why="nav")

    # ---------------------------------------------------------------- 見回り(玄関の watch から 10 秒ごと)
    def tick(self):
        if not self.enabled():
            with self._lock:
                self._pending = []
            return
        self._job_ops()
        now = self.clock()
        if now - self._checked >= CHECK_EVERY:
            self._checked = now
            for name, fn in (("固まった", self._stuck_checks), ("30 分ごと", self._periodic)):
                try:
                    fn(now)
                except Exception as e:   # noqa: BLE001  (見直しで見回りを止めない)
                    self.log("状態の書き出しの見直し(%s)に失敗: %s" % (name, e.__class__.__name__))
        with self._lock:
            todo, self._pending = self._pending, []
        for trig, rid, summary, info in todo:
            self.fire(trig, rid, summary, **info)

    def _engine(self):
        return getattr(self.app, "engine", None)

    def _job_ops(self):
        """② の実行の始まりと終わりを操作の記録へ(待ち行列の状態の差)"""
        eng = self._engine()
        if eng is None:
            return
        try:
            runs = eng.queue.status().get("runs") or []
        except Exception:   # noqa: BLE001
            return
        for r in runs:
            rid, st = r.get("id"), r.get("state")
            prev = self._runs.get(rid)
            if st == prev or not rid:
                continue
            self._runs[rid] = st
            tgt = str(r.get("kind") or "run")
            if st == "running":
                self.app_op("job_start", tgt, {"runId": rid, "requestId": r.get("requestId")})
            elif prev in ("running", "queued") and st not in ("running", "queued"):
                self.app_op("job_end", tgt, {"runId": rid, "requestId": r.get("requestId"), "result": st})
        if len(self._runs) > 500:
            keep = {r.get("id") for r in runs}
            self._runs = {k: v for k, v in self._runs.items() if k in keep}

    def _stuck(self, key, on, rid, summary, **info):
        """続いている「固まった」は直るまで 1 回だけ印を付ける"""
        if not on:
            self._stuck_on.discard(key)
            return
        if key not in self._stuck_on:
            self._stuck_on.add(key)
            self.mark("stuck", rid, summary, **info)

    def _stuck_checks(self, now):
        api = getattr(self.app, "api", None)
        rows = []
        if api is not None:
            rows = api.view()["rows"]   # 段の進みの覚え(api._stages)も新しくなる
            stages = dict(getattr(api, "_stages", {}) or {})
            for r in rows:
                seen = stages.get(r["id"])
                on = bool(seen) and r.get("state") in ("sent", "making") and now * 1000 - seen[3] >= STUCK_PROGRESS_SEC * 1000
                self._stuck(("progress", r["id"]), on, r["id"], "「%s」の段の進みが %d 分変わりません" % (seen[0] if seen else "", STUCK_PROGRESS_SEC // 60),
                            why="progress")
        live = getattr(self._engine(), "live", None)
        if live is not None:
            inbox = getattr(self.app, "inbox", None)
            by_rec = {(r.get("live") or {}).get("recording"): r["id"] for r in (inbox.live_rows() if inbox is not None else [])}
            seen_ids = set()
            for rec in live.recent() or []:
                key = rec.get("id")
                seen_ids.add(key)
                secs = _num(rec.get("seconds")) or 0
                prev = self._recs.get(key)
                if not rec.get("active"):
                    if prev is not None and prev.get("active"):
                        self.app_op("job_end", "live", {"recording": key, "result": rec.get("state") or ""})
                    self._recs[key] = {"secs": secs, "since": now, "active": False}
                    self._stuck(("rec", key), False, None, "")
                    continue
                if prev is None or not prev.get("active"):
                    self.app_op("job_start", "live", {"recording": key})
                if prev is None or prev["secs"] != secs or not prev.get("active"):
                    self._recs[key] = prev = {"secs": secs, "since": now, "active": True}
                rid = by_rec.get(key)
                self._stuck(("rec", key), now - prev["since"] >= REC_STILL_SEC, rid,
                            "録画が %d 秒増えていません(%s)" % (int(now - prev["since"]), str(rec.get("state") or "")[:40]), why="recording")
            for k in [k for k in self._recs if k not in seen_ids]:
                self._recs.pop(k, None)
        sync = getattr(self.app, "sync", None)
        if sync is not None and sync.has_key():
            inbox = getattr(self.app, "inbox", None)
            for r in (inbox.view() if inbox is not None else []):
                w = inbox.waited(r) if r.get("pc") == "user" else None
                self._stuck(("dropbox", r["id"]), w is not None and w >= DROPBOX_STUCK_SEC, r["id"],
                            "Dropbox に置いた依頼が %d 分受け付けられていません" % ((w or 0) // 60), why="dropbox")
            old = self._outbox_age(now)
            self._stuck(("dropbox", "outbox"), old >= DROPBOX_STUCK_SEC, None, "送り返しが %d 分上がっていません" % (old // 60), why="dropbox")

    def _outbox_age(self, now):
        box = self.places.get("outbox") or ""
        oldest = 0
        try:
            for n in os.listdir(box):
                if any(re.search(p, n) for p in OUT_NAMES) or n.endswith(".voice.zip"):
                    oldest = max(oldest, now - max(os.path.getmtime(os.path.join(box, n)), self._born))
        except OSError:
            return 0
        return int(oldest)

    def _periodic(self, now):
        eng = self._engine()
        busy = False
        if eng is not None:
            try:
                st = eng.queue.status()
                busy = bool(st.get("running"))
            except Exception:   # noqa: BLE001
                busy = False
            live = getattr(eng, "live", None)
            busy = busy or bool(live is not None and live.active_count() > 0)
        if not busy:
            self._busy_since = None
            return
        if self._busy_since is None:
            self._busy_since = now
        elif now - self._busy_since >= PERIODIC_SEC:
            self._busy_since = now
            self.mark("periodic", None, "処理中・録画中の 30 分ごと")

    # ---------------------------------------------------------------- 書く
    def fire(self, trigger, rid=None, summary="", ask=None, local=None, live=None, code=None, stage=None, **extra):
        """1 つ書く -> パスか None(スイッチ・5 分の重複止め・書けない)"""
        if not self.enabled():
            return None
        rid = rid if isinstance(rid, str) and SAFE_ID.match(rid) else None
        now = self.clock()
        key = (trigger, rid or "app", ask or "", (stage or "") if trigger == "stuck" else "")   # 固まったの段違い(録画が止まった・録画をやり直した record)は別に数える
        with self._lock:
            last = self._last.get(key)
            if trigger != "ask" and last is not None and now - last < DEDUPE_SEC:
                return None
            self._last[key] = now
        try:
            doc = self.collect(trigger, rid, summary, ask=ask, local=local, live=live, code=code, stage=stage, extra=extra)
            return self._write(doc)
        except Exception as e:   # noqa: BLE001  (書き出しで玄関を止めない)
            self.log("状態を書き出せませんでした(%s): %s %s" % (trigger, e.__class__.__name__, str(e)[:120]))
            return None

    def _write(self, doc):
        urgent = doc["urgent"]
        data = fit(doc, ASK_TARGET if doc["trigger"] == "ask" else TARGET_BYTES)
        if urgent:
            box = self.places["outbox"]
            fmt = os.path.join(box, "%s__state-%%013d.state.json" % (doc.get("rid") or "app"))
            rx = _diag.STATE_NAME_RE
        else:
            box = self.local_dir()
            fmt = os.path.join(box, "%%013d-%s.state.json" % doc["trigger"])
            rx = re.compile(r"^(\d{13})-[a-z_]+\.state\.json$")
        os.makedirs(box, exist_ok=True)
        with self._lock:
            at = doc["at"]
            while os.path.exists(fmt % at):
                at += 1
            path = fmt % at
            _fsio.atomic_write(path, data)
            got = sorted((int(m.group(m.lastindex)), n) for n in os.listdir(box) for m in [rx.match(n)] if m)
            for _at, n in got[:max(0, len(got) - (OUTBOX_MAX if urgent else LOCAL_MAX))]:
                _fsio.unlink_quiet(os.path.join(box, n))
        self.log("状態を書き出しました: %s(%d KB)" % (os.path.basename(path), len(data) // 1024))
        return path

    def collect(self, trigger, rid=None, summary="", ask=None, local=None, live=None, code=None, stage=None, extra=None):
        """状態の書き出しの dict(資料の形)。読めない欄は None"""
        now_ms = int(self.clock() * 1000)
        urgent = trigger in URGENT
        parts = PARTS.get(trigger, FULL)
        doc = {"v": V, "kind": "state", "at": now_ms, "trigger": trigger, "urgent": urgent, "rid": rid,
               "summary": self.mask(summary)[:_diag.SUMMARY_MAX], "codes": [], "facts": {}, "diag": self._near_diag(now_ms),
               "app": {"version": _version.VERSION, "host": getattr(self.diag, "host", None), "python": platform.python_version()}}
        rows = self._rows() if ("requests" in parts or rid) else []
        live_facts = live if isinstance(live, dict) else None
        for name in parts:
            try:
                doc[name] = getattr(self, "_" + name)(rows=rows, live=live_facts, now_ms=now_ms)
            except Exception as e:   # noqa: BLE001  (1 つの欄が読めなくても残りは書く)
                doc[name] = None
                doc.setdefault("errors", {})[name] = e.__class__.__name__
        row = next((r for r in rows if r.get("id") == rid), None) if rid else None
        codes, facts = judge(trigger, row, rows, live_facts)
        if code and "cause" not in facts:
            facts["cause"] = code
        if stage and "stage" not in facts:
            facts["stage"] = stage
        doc["codes"], doc["facts"] = codes, facts
        if extra:
            doc["detail"] = self.diag.mask_tree(extra) if self.diag is not None else extra
        if urgent:
            doc["ops"] = self.ops.recent(_oplog.OPS_WINDOW)
        doc["shot"] = None
        doc["ask"] = ask
        if trigger == "ask":
            doc["local"] = local or []
        return doc

    def _near_diag(self, now_ms):
        return [n for at, n in list(self._diag_names) if abs(now_ms - at) <= DIAG_NAMES_SEC * 1000][-20:]

    def _rows(self):
        api = getattr(self.app, "api", None)
        return api.view()["rows"] if api is not None else []

    # ---------------------------------------------------------------- 欄
    def _env(self, **_kw):
        disk = {}
        roots = [self.places.get("data"), self.places.get("home"), self.places.get("cases")]
        save = self.places.get("save")
        try:
            roots.append(save() if callable(save) else save)
        except Exception:   # noqa: BLE001
            pass
        for r in roots:
            if not r:
                continue
            drive = os.path.splitdrive(os.path.abspath(r))[0] or "/"
            if drive in disk:
                continue
            try:
                disk[drive] = round(shutil.disk_usage(r if os.path.isdir(r) else os.path.dirname(os.path.abspath(r))).free / 1024 ** 3, 1)
            except OSError:
                disk[drive] = None
        gpu = (self.diag.pc() or {}).get("gpu") if self.diag is not None else None
        try:
            from . import ytdlp_update as _ytdlp_update
            yd = (_ytdlp_update.facts(getattr(self.diag, "env", os.environ)) or {}).get("version")
        except Exception:   # noqa: BLE001
            yd = None
        lt = time.localtime(self.clock())
        return {"ytdlp": yd, "ffmpeg": self._ffmpeg_version(), "diskFreeGB": disk,
                "gpu": {"name": gpu.get("name"), "vramFreeGB": None, "vramGB": gpu.get("vramGB")} if isinstance(gpu, dict) else None,
                "clock": {"local": time.strftime("%Y-%m-%dT%H:%M:%S", lt), "utcOffset": int(lt.tm_gmtoff // 60), "bootAt": _boot_at_ms()}}

    def _ffmpeg_version(self):
        """ffmpeg の版(exe から動いているときだけ・プロセスの中で 1 回。窓は出さない = ytt/tools.tool_version)"""
        if self._ffmpeg is None:
            v = ""
            if getattr(self.diag, "host", "browser") != "browser":
                p = _tools.find_tool("ffmpeg")
                v = _tools.tool_version(p) if p else ""
            self._ffmpeg = v
        return self._ffmpeg or None

    def _screen(self, **_kw):
        return dict(self._screen_memo) if self._screen_memo else None

    def _requests(self, rows=(), now_ms=0, **_kw):
        out = []
        since = now_ms - REQUEST_HOURS * 3600 * 1000
        for r in rows:
            if max(r.get("createdAt") or 0, r.get("updatedAt") or 0) < since:
                continue
            f = r.get("form") or {}
            src = r.get("source") or {}
            run = r.get("run") or {}
            stages = {}
            for s in run.get("steps") or []:
                if isinstance(s, dict) and s.get("startedAt"):
                    stages[str(s.get("key"))] = {"start": s.get("startedAt"), "end": s.get("finishedAt")}
            steps = r.get("steps") if isinstance(r.get("steps"), dict) else {}
            prog = r.get("progress") if isinstance(r.get("progress"), dict) else None
            out.append({"id": r.get("id"), "kind": r.get("kind"), "pc": r.get("pc"), "state": r.get("state"),
                        "url": self.mask(str(f.get("url") or src.get("url") or (f.get("file") or {}).get("name") or ""))[:300],
                        "ranges": f.get("ranges"), "stage": steps.get("label") or "", "progress": prog or (steps.get("text") or None),
                        "retries": r.get("autoRetries") or 0, "lastError": self.mask(str(r.get("error") or ""))[:LINE_MAX],
                        "code": (r.get("fail") or {}).get("code"), "packs": len(r.get("packs") or []), "cancelled": bool(r.get("cancelled")),
                        "createdAt": r.get("createdAt"), "stages": stages})
        return out

    def _jobs(self, **_kw):
        eng = self._engine()
        if eng is None:
            return []
        out = []
        for r in eng.queue.status().get("runs") or []:
            if r.get("state") not in ("running", "queued"):
                continue
            cur = next((s for s in r.get("steps") or [] if s.get("state") == "running"), None) or {}
            out.append({"kind": r.get("kind"), "requestId": r.get("requestId"), "state": r.get("state"), "start": r.get("startedAt"),
                        "progress": cur.get("label") or r.get("stateLabel"), "lastLog": self.mask(str(cur.get("detail") or r.get("message") or ""))[:LINE_MAX],
                        "alive": r.get("state") == "running"})
        try:
            for j in eng.queue.tools.jobs():
                if isinstance(j, dict) and j.get("state") in ("running", "queued"):
                    out.append({"kind": j.get("kind"), "state": j.get("state"), "start": j.get("started") or j.get("createdAt"),
                                "progress": _num(j.get("progress")), "lastLog": self.mask(str(j.get("message") or ""))[:LINE_MAX], "alive": j.get("state") == "running"})
        except Exception:   # noqa: BLE001  (文字起こしの部品が動いていない)
            pass
        return out

    def _live(self, live=None, rows=(), **_kw):
        eng = self._engine()
        lv = getattr(eng, "live", None)
        recs = []
        if lv is not None:
            try:
                recs = lv.recent() or []
            except Exception:   # noqa: BLE001
                recs = []
        rec = next((r for r in recs if r.get("active")), recs[-1] if recs else None)
        if live is None and rec is not None and hasattr(eng, "_live_facts"):   # 材料が渡されていなければ今の録画の物を読む(行を閉じたときの診断と同じ)
            try:
                raw = (lv.recordings(rec.get("recorder")) or {}).get(rec.get("id"))
                live = self.diag.mask_tree(eng._live_facts(rec.get("recorder"), rec.get("id"), raw)) if self.diag is not None else None
            except Exception:   # noqa: BLE001
                live = None
        if live is None and rec is None:
            return None
        pk = (live or {}).get("peaksDoc") or {}
        ci = pk.get("chatInfo") if isinstance(pk.get("chatInfo"), dict) else {}
        size, secs = None, _num((rec or {}).get("seconds"))
        if rec is not None and hasattr(lv, "rec_folder"):
            d = os.path.join(lv.rec_folder(), str(rec.get("id")))
            size = dir_bytes(d) if os.path.isdir(d) else None
        cands = live_cands(live)
        sett = (live or {}).get("settings") or {}
        return {"state": (rec or {}).get("state") or ((live or {}).get("recording") or {}).get("state"), "active": bool((rec or {}).get("active")),
                "seconds": secs, "bytes": size, "bytesPerMin": round(size / (secs / 60.0)) if size and secs else None,
                "chat": {"state": pk.get("chat") if isinstance(pk.get("chat"), str) else ci.get("state"), "count": _num(ci.get("count")),
                         "lastAt": ci.get("lastAt")},
                "cands": cands, "sens": sett.get("sens") if isinstance(sett, dict) else None, "threshold": pk.get("thr"),
                "noCands": cands == 0 if cands is not None else None, "recordings": len(recs)}

    def _sync(self, **_kw):
        s = getattr(self.app, "sync", None)
        if s is None:
            return None
        box = self.places.get("outbox") or ""
        try:
            pending = sum(1 for n in os.listdir(box) if any(re.search(p, n) for p in OUT_NAMES) or n.endswith(".voice.zip"))
        except OSError:
            pending = None
        inbox = getattr(self.app, "inbox", None)
        remote = [r for r in inbox.view() if r.get("pc") == "user" and r.get("state") == "sent"] if inbox is not None else []
        return {"key": s.has_key(), "pending": pending, "remotePending": len(remote), "lastSentAt": s.sent_at, "lastArrivedAt": s.arrived_at,
                "lastRunAt": (s.last or {}).get("at"), "problem": self.mask((s.last or {}).get("problem") or "")[:LINE_MAX]}

    def _settings(self, **_kw):
        out = {}
        api = getattr(self.app, "api", None)
        if api is not None:
            from . import api as _api
            f = api.form()
            for k, v in f.items():
                d = _api.FORM_DEFAULTS.get(k)
                if isinstance(v, dict) and isinstance(d, dict):
                    ch = {kk: vv for kk, vv in v.items() if d.get(kk) != vv}
                    if ch:
                        out[k] = ch
                elif v != d:
                    out[k] = v
        st = getattr(self.app, "settings", None)
        if st is not None:
            v = st.view()
            if not v.get("saveIsDefault"):
                out["saveDir"] = "changed"
            if not v.get("caseIsDefault"):
                out["caseRoot"] = "changed"
            from flow import machine as _machine
            if v.get("diskMinGB") not in (None, _machine.DISK_MIN_GB):
                out["diskMinGB"] = v.get("diskMinGB")
            out["engine"] = v.get("engine")
            out["apiKey"] = bool(v.get("apiKey"))
        return out

    def _log(self, now_ms=0, **_kw):
        path = os.path.join(self.places["friend"], "logs", "friendapp.log")
        try:
            with open(path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - LOG_READ))
                text = f.read().decode("utf-8", "replace")
        except OSError:
            return {"errors30m": [], "tail": []}
        lines = text.splitlines()
        if size > LOG_READ and lines:
            lines = lines[1:]
        since = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now_ms / 1000.0 - 1800))
        errs = [ln for ln in lines if ln[:19] >= since and any(w in ln for w in ERROR_WORDS)][-50:]
        return {"errors30m": [self.mask(x[:LINE_MAX]) for x in errs], "tail": [self.mask(x[:LINE_MAX]) for x in lines[-LOG_TAIL:]]}

    def _inbox(self, **_kw):
        """受け取るの箱の数の要約(友人の判定がどれだけ付いているか。数だけ = friendapp/inbox の summary。10-26)"""
        inbox = getattr(self.app, "inbox", None)
        return inbox.summary() if inbox is not None else None

    def _yt(self, rows=(), **_kw):
        env = getattr(self.diag, "env", os.environ)
        f = _ytcookies.facts((env.get(_tools.COOKIES_ENV) or "").strip()) or {}
        refused = [r for r in rows if (r.get("fail") or {}).get("code") in ("bot", "rate", "age") and r.get("failedAt")]
        last = max(refused, key=lambda r: r["failedAt"]) if refused else None
        return {"login": bool(f.get("loginAt")), "loginAt": f.get("loginAt"), "lostAt": f.get("lostAt"),
                "lastRefusedAt": last.get("failedAt") if last else None, "lastRefused": (last.get("fail") or {}).get("code") if last else None}

    # ---------------------------------------------------------------- 「送って」の印(同期の回の中で)
    def answer_asks(self, io):
        """/診断/送って/ の印 1 つごとに、手元の分を添えた状態を箱へ書き、印と送った手元の物を消す"""
        if not self.enabled():
            return
        entries = io.list_folder(ASK_DIR)
        for e in entries or []:
            name = e.get("name") or ""
            m = ASK_RE.match(name)
            if e.get(".tag", "file") != "file" or not m:
                continue
            got = io.read_small("%s/%s" % (ASK_DIR, name), ASK_CAP)
            d = {}
            if got is not None:
                try:
                    d = json.loads(got[0].decode("utf-8-sig"))
                except (UnicodeDecodeError, ValueError):
                    d = {}
            d = d if isinstance(d, dict) else {}
            aid = d.get("id") if isinstance(d.get("id"), str) and SAFE_ID.match(d["id"]) else m.group(1)
            local, used = self._take_local()
            note = d.get("note") if isinstance(d.get("note"), str) else ""
            path = self.fire("ask", None, "送ってに答えました" + ("(%s)" % note[:200] if note else ""), ask=aid, local=local)
            if path is None:
                continue
            for p in used:
                _fsio.unlink_quiet(p)
            io.delete("%s/%s" % (ASK_DIR, name))
            self.log("送ってに答えました: %s(手元の %d 件)" % (aid, len(used)))

    def _take_local(self):
        """手元に残していた状態(古い順)と、そのファイルのパス。長い所は先に落とす(まとめて 1 MB に収めるため)"""
        d = self.local_dir()
        out, used = [], []
        try:
            names = sorted(n for n in os.listdir(d) if n.endswith(".state.json"))
        except OSError:
            return [], []
        for n in names:
            p = os.path.join(d, n)
            doc = _fsio.read_json_or(p, None, kind=dict)
            used.append(p)
            if doc is None:
                continue
            for k in ("log", "screen", "ops"):
                doc.pop(k, None)
            out.append(doc)
        return out, used
