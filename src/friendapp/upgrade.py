# -*- coding: utf-8 -*-
"""友人のアプリの更新の決まり(いつ入れ替えるか・重要な直し・新しい版の確かめと戻し・心拍・固まり)。
形の正は notes:plan/友人の不具合の自動対応-1025.md の「更新(友人側)」。入れ替える・戻すのは exe(friend-apps/launcher)で、ここは決めて
GET /api/friend/state の swap・verify・rollback で exe に伝えるだけ(前の exe はこの欄を知らない = 作業が無いときだけ入れ替える前の決まりのまま)。

- 入れ替える時機(wait_reason): ふだんは 録画中でない・待機中の配信の枠が無い・依頼が処理中でも順番待ちでもない・Dropbox への上げ下ろしが無い、の全部。
  画面に触っているかは見ない。重要な直し(latest.json の important)は 録画中だけ待つ(止まった録画は待たない)・処理中はその 1 本が終わるまで・
  順番待ちは入れ替えて起動後に続きから。[今すぐ]・[今すぐ更新] は録画中だけ待つ
- 重要な直しの直す対象(fixes.requests の依頼 id): 直しの版で動き始めたら、失敗のままの行を 1 回だけ自動でやり直す(引き継いだ行・作る人の PC の行は除く)。
  もう 1 回失敗したら自動のやり直しは使い切り(gaveUp)= 問題 1 の引き継ぎへ
- 確かめ(verify): 確かに動いた版(app-versions.json の good)でない版は、同期が 1 周通る・画面が返事をする・起動の失敗と思わぬ例外が出ない、を
  録画していない時間で VERIFY_SEC そろえて ok。だめなら fail で、戻す先があれば rollback を頼む(録画中は待つ)。同期が通らないだけなら pending のまま
- 戻す印(/診断/戻して/<id>.rollback.json {v, id, at, to, why}): 受け取り側が置く。to が null なら確かに動いた版へ。戻す先が無ければ戻さず fail.json で返す
- 配布の取り消し: latest.json の版が取ってある版より下がった・cancel に入った・latest.json が無くなった(フォルダは読めた)なら、その版は捨てる
- 心拍(30 分ごと 1KB)と失敗の知らせ(.fail.json)は送り返しの箱へ(同期が /診断/ へ上げる)。スイッチは診断と同じ
- 固まり: 依頼の段が、ふだんの時間(段の時間の記録の中央値)の STUCK_FACTOR 倍を超えて進まなければ、その実行を止めて失敗にする(自動のやり直しへ)
"""
import json
import os
import re
import shutil
import statistics
import time

from ytt import fsio as _fsio, version as _version

from . import diag as _diag, report as _report

V = 1
STATE_NAME = "upgrade.json"
VERSIONS_NAME = "app-versions.json"
LAUNCHER_ENV = "YTT_FRIEND_LAUNCHER"
APP_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
NORMAL, IMPORTANT, NOW = "normal", "important", "now"
RECORDING, BUSY, DOWNLOADING = "recording", "busy", "downloading"
BEAT_EVERY = 1800
BEAT_MAX = 1024
VERIFY_SEC = 600
VERIFY_SEC_ENV = "YTT_FRIEND_VERIFY_SEC"   # 確かめの秒を短くする(本物の exe での通しの確かめ用。無い・数でない・10 未満は VERIFY_SEC)
OVERDUE_SEC = 24 * 3600
STUCK_EVERY = 60
STUCK_FACTOR = 3
STUCK_FLOOR = 600                  # ふだんが短い段でもこの秒より前には止めない
STATS_MIN = 3                      # 段の時間の記録がこれより少なければ目安を作らない(止めない)
ROLLBACK_DIR = "/診断/戻して"
ROLLBACK_RE = re.compile(r"^([0-9A-Za-z_-]{1,64})\.rollback\.json$")
ROLLBACK_CAP = 16 * 1024
WHY_MAX = 300
VERIFY_ERRORS = ("start", "exception")   # 確かめで数える診断(依頼の失敗・通信の失敗は版のせいとは限らないので数えない)
STUCK_TEXT = "処理の段が、ふだんの %d 倍(%d 分)たっても進まなくなりました(固まり)。自動でやり直します"
WAIT_LABEL = {RECORDING: "ライブを録画しています", BUSY: "処理しています", DOWNLOADING: "新しい版を取っています"}


def vt(v):
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return (0,)


def wait_reason(st, mode, stalled=0, busy=False):
    """入れ替えを待つ理由(RECORDING・BUSY)か ""(今入れ替えてよい)。st = 玄関の state()・stalled = 1 分増えない録画の数・busy = 玄関の busy()"""
    if max(0, (st.get("recording") or 0) - stalled) > 0:
        return RECORDING
    if mode == NOW:
        return ""
    if st.get("setup"):
        return BUSY
    if mode == IMPORTANT:
        return BUSY if st.get("making") else ""
    if st.get("reserved"):
        return RECORDING
    if st.get("making") or st.get("waiting") or busy:
        return BUSY
    return ""


def verify_sec(env):
    try:
        n = int(str(env.get(VERIFY_SEC_ENV) or "").strip())
    except ValueError:
        return VERIFY_SEC
    return n if n >= 10 else VERIFY_SEC


def typical(vals):
    """段の時間の記録の目安(中央値)。少なければ None"""
    xs = [float(v) for v in vals or [] if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0]
    return statistics.median(xs) if len(xs) >= STATS_MIN else None


def beat_doc(at_ms, version, pending, wait, live_state, rid, stage):
    doc = {"v": V, "kind": "beat", "at": at_ms, "appVersion": version, "pending": pending, "wait": wait,
           "live": {"state": live_state}, "request": {"id": rid, "stage": stage}}
    data = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    if len(data) > BEAT_MAX:
        doc["request"] = {"id": None, "stage": None}
        data = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    return data


class Upgrade:
    """玄関に 1 つ。app = 玄関(state・busy・update_version・api・inbox・sync・engine・report・diag を読む)"""

    def __init__(self, app, places, clock=time.time, log=None, env=None):
        self.app, self.places, self.clock = app, places, clock
        self.log = log or (lambda msg: None)
        self.env = os.environ if env is None else env
        self.version = _version.VERSION
        self.path = os.path.join(places["friend"], STATE_NAME)
        self.state = _fsio.read_json_or(self.path, {}, kind=dict)
        self.now_pressed = False
        self.rollback = None          # exe に頼む戻し {to, why}(録画中は待ってから渡す)
        self.screen_at = None
        self.verify = "pending" if self._verifying() else ("ok" if self.good() == self.version and self._launched() else "")
        self.verify_why = ""
        self.verify_sec = verify_sec(self.env)
        self._v_clock, self._v_last = 0.0, None
        self._v_errors = []
        self._v_sync_noted = False
        self._beat_at = 0.0
        self._stuck_at = 0.0
        self._stopped = set()

    # ---------------------------------------------------------------- 場所と記録
    def home(self):
        return self.places.get("home") or ""

    def _launched(self):
        return (self.env.get(LAUNCHER_ENV) or "").strip() == "1" and os.path.isdir(os.path.join(self.home(), "app-" + self.version))

    def record(self):
        return _fsio.read_json_or(os.path.join(self.home(), VERSIONS_NAME), {}, kind=dict) if self.home() else {}

    def good(self):
        g = self.record().get("good")
        return g if isinstance(g, str) and APP_VERSION_RE.match(g) else ""

    def _verifying(self):
        return self._launched() and self.good() != self.version

    def _save(self):
        try:
            _fsio.write_json(self.path, self.state, indent=None)
        except OSError as e:
            self.log("更新の記録を書けませんでした: %s" % e.__class__.__name__)

    def enabled(self):
        d = getattr(self.app, "diag", None)
        return d is not None and d.enabled()

    def installed(self, v):
        d = os.path.join(self.home(), "app-" + v)
        return os.path.isfile(os.path.join(d, "src", "friendapp", "server.py")) and os.path.isfile(os.path.join(d, "python", "python.exe"))

    # ---------------------------------------------------------------- latest.json(同期が sync.state["latest"] に写す)
    def latest(self):
        s = getattr(self.app, "sync", None)
        d = (getattr(s, "state", None) or {}).get("latest") if s is not None else None
        return d if isinstance(d, dict) else {}

    def important(self, v):
        lt = self.latest()
        return bool(v) and lt.get("version") == v and lt.get("important") is True

    def fixes(self):
        lt = self.latest()
        f = lt.get("fixes") if lt.get("version") == self.version and isinstance(lt.get("fixes"), dict) else {}
        reqs = f.get("requests") if isinstance(f.get("requests"), list) else []
        return [r for r in reqs if isinstance(r, str) and _diag.SAFE_ID.match(r)]

    def notes(self):
        """「最近の更新」(latest.json の notes [{v, at, items}]。新しい順・無ければ [])= ⚙ の節に出すだけ(知らせ・印は出さない)"""
        n = self.latest().get("notes")
        return n if isinstance(n, list) else []

    def cancelled(self, v):
        """取ってある版 v を捨てるか: latest.json が無くなった(フォルダは読めた)・latest.json の版が v より下・cancel に v"""
        lt = self.latest()
        if not lt:
            return False
        if lt.get("gone"):
            return True
        cancel = lt.get("cancel") if isinstance(lt.get("cancel"), list) else []
        lv = lt.get("version")
        return v in cancel or (isinstance(lv, str) and APP_VERSION_RE.match(lv) is not None and vt(lv) < vt(v))

    def downloading(self):
        """latest.json に今より新しい版があり、まだ入れていない(取っている途中・空きを待っている)"""
        lv = self.latest().get("version")
        if not (isinstance(lv, str) and APP_VERSION_RE.match(lv)) or vt(lv) <= vt(self.version) or self.cancelled(lv):
            return False
        return lv not in (self.record().get("bad") or []) and not self.installed(lv)

    def discard_cancelled(self):
        """取り消された版のフォルダを捨てる(入れ替えない)-> 捨てた版"""
        home = self.home()
        gone = []
        if not home or not os.path.isdir(home):
            return gone
        for n in os.listdir(home):
            v = n[4:] if n.startswith("app-") else ""
            if not APP_VERSION_RE.match(v) or vt(v) <= vt(self.version) or not self.cancelled(v):
                continue
            shutil.rmtree(os.path.join(home, n), ignore_errors=True)
            if not os.path.exists(os.path.join(home, n)):
                gone.append(v)
                self.log("配布が取り消された版 %s を捨てました(入れ替えません)" % v)
        if gone and self.app.update_requested and not self.app.update_version():
            self.app.update_requested = False
        return gone

    # ---------------------------------------------------------------- いつ入れ替えるか
    def stalled(self):
        rep = getattr(self.app, "report", None)
        return sum(1 for k in getattr(rep, "_stuck_on", ()) if isinstance(k, tuple) and k and k[0] == "rec")

    def mode(self, pending):
        if self.now_pressed:
            return NOW
        return IMPORTANT if self.important(pending) else NORMAL

    def wait_code(self, st, pending):
        if not pending:   # まだ取っていない: 録画中で重い zip を後にしているなら recording
            return (getattr(self.app.sync, "update_wait", None) or DOWNLOADING) if self.downloading() else ""
        return wait_reason(st, self.mode(pending), self.stalled(), self.app.busy() if self.mode(pending) == NORMAL else False)

    def swap(self, st):
        """exe が今入れ替えてよいか(頼まれていて、待つ理由が無い)"""
        pending = st.get("update") or ""
        return bool(pending and self.app.update_requested and not self.rollback and self.wait_code(st, pending) == "")

    def rollback_due(self, st):
        """今 exe に渡す戻し(録画中・処理中の 1 本は待つ)か None"""
        if not self.rollback or wait_reason(st, IMPORTANT, self.stalled()):
            return None
        return dict(self.rollback)

    def overdue(self, pending):
        seen = (self.state.get("seen") or {}).get(pending) if pending else None
        return bool(seen) and self.clock() * 1000 - seen >= OVERDUE_SEC * 1000

    def press_now(self):
        """[今すぐ](重要な直し)・[今すぐ更新](溜まっている): 録画中だけ待つ"""
        if not self.app.update_version():
            raise ValueError("新しい版はありません")
        self.now_pressed = True
        self.app.update_requested = True
        self.log("[今すぐ] を押されました(%s)" % self.app.update_version())

    def view(self, pending):
        return {"important": self.important(pending), "overdue": self.overdue(pending), "now": self.now_pressed}

    # ---------------------------------------------------------------- 確かめ
    def saw_screen(self):
        if self.screen_at is None:
            self.screen_at = self.clock()

    def on_diag(self, kind, doc, path):
        if self.verify == "pending" and kind in VERIFY_ERRORS:
            self._v_errors.append(str((doc or {}).get("summary") or kind)[:200])

    def _verify_tick(self, now, recording):
        if self.verify != "pending":
            return
        if self._v_last is not None and not recording:   # 録画中は確かめを止める(ライブの後に続ける)
            self._v_clock += max(0.0, now - self._v_last)
        self._v_last = now
        if self._v_errors:
            return self._verify_fail("新しい版 %s で起動の失敗か思わぬ例外が出ました: %s" % (self.version, self._v_errors[0]))
        if self._v_clock < self.verify_sec:
            return
        if self.screen_at is None:
            return self._verify_fail("新しい版 %s で画面が %d 分のあいだ返事をしませんでした" % (self.version, max(1, self.verify_sec // 60)))
        sync = getattr(self.app, "sync", None)
        if sync is not None and sync.has_key() and not getattr(sync, "passes", 0):
            if not self._v_sync_noted:
                self._v_sync_noted = True
                self.log("新しい版の確かめ: 同期がまだ 1 周通っていないので待ちます")
            return
        self.verify = "ok"
        self.log("新しい版 %s の確かめが済みました(確かに動いた版にします)" % self.version)

    def _verify_fail(self, why):
        self.verify, self.verify_why = "fail", why
        self.log(why)
        rep = getattr(self.app, "report", None)
        if rep is not None:
            rep.mark("update", None, why, stage="verify")
        target, err = self.rollback_target(None)
        if target is None:
            self.write_fail("rollback", self.version, None, "戻せませんでした: %s(%s)" % (err, why))
            return
        self.rollback = {"to": target, "why": why}

    def rollback_target(self, to):
        """-> (戻す先, "") か (None, 理由)。to が無ければ確かに動いた版(無ければ previous)"""
        rec = self.record()
        t = to or self.good() or rec.get("previous") or ""
        if not (isinstance(t, str) and APP_VERSION_RE.match(t)):
            return None, "戻す先の確かに動いた版がありません"
        if t == self.version:
            return None, "もう版 %s で動いています" % t
        if not self.installed(t):
            return None, "戻す先の版 %s が残っていません" % t
        return t, ""

    def take_marks(self, io):
        """/診断/戻して/ の印(同期の回の中で)-> 戻すと決めた数。印は受けたら消す(戻すのは exe・結果は exe の fail.json)"""
        n = 0
        for e in io.list_folder(ROLLBACK_DIR) or []:
            name = e.get("name") or ""
            if e.get(".tag", "file") != "file" or not ROLLBACK_RE.match(name):
                continue
            path = "%s/%s" % (ROLLBACK_DIR, name)
            got = io.read_small(path, ROLLBACK_CAP)
            try:
                d = json.loads(got[0].decode("utf-8-sig")) if got else {}
            except (UnicodeDecodeError, ValueError):
                d = {}
            d = d if isinstance(d, dict) else {}
            to = d.get("to")
            why = _diag_mask(self.app, str(d.get("why") or "戻す印"))[:WHY_MAX]
            if to is not None and not (isinstance(to, str) and APP_VERSION_RE.match(to)):
                self.write_fail("rollback", self.version, None, "戻せませんでした: 戻す印の版の形が違います(%s)" % why)
            else:
                target, err = self.rollback_target(to)
                if target is None:
                    self.write_fail("rollback", self.version, to, "戻せませんでした: %s(%s)" % (err, why))
                else:
                    self.rollback = {"to": target, "why": why}
                    self.log("戻す印を受けました: 版 %s へ(%s)" % (target, why))
                    n += 1
            io.delete(path)
        return n

    # ---------------------------------------------------------------- 送り返しの箱(心拍・失敗の知らせ)
    def write_fail(self, kind, frm, to, why):
        if not self.enabled():
            return None
        at = int(self.clock() * 1000)
        doc = {"v": V, "kind": kind, "at": at, "from": frm or None, "to": to or None, "why": _diag_mask(self.app, why)[:WHY_MAX]}
        return self._put("app__fail-%013d.fail.json", at, json.dumps(doc, ensure_ascii=False).encode("utf-8"))

    def _put(self, fmt, at, data):
        box = self.places["outbox"]
        os.makedirs(box, exist_ok=True)
        while os.path.exists(os.path.join(box, fmt % at)):
            at += 1
        path = os.path.join(box, fmt % at)
        _fsio.atomic_write(path, data)
        return path

    def beat(self, now):
        """30 分ごとの 1 行(箱には一番新しい 1 つだけ)"""
        if not self.enabled():
            return None
        st = self.app.state()
        pending = st.get("update") or None
        stalled = self.stalled()
        rec = st.get("recording") or 0
        live = "recording" if rec > stalled else "stalled" if rec else "reserved" if st.get("reserved") else ""
        rid = stage = None
        eng = getattr(self.app, "engine", None)
        if eng is not None:
            run = next((r for r in eng.queue.status().get("runs") or [] if r.get("state") == "running"), None)
            rid = (run or {}).get("requestId")
            seen = (getattr(getattr(self.app, "api", None), "_stages", None) or {}).get(rid) if rid else None
            stage = _report.STAGE_NAME.get(seen[0], seen[0]) if seen else None
        at = int(now * 1000)
        data = beat_doc(at, self.version, pending, self.wait_code(st, pending), live, rid, stage)
        box = self.places["outbox"]
        path = self._put("app__beat-%013d.beat.json", at, data)
        for n in os.listdir(box):
            if _diag.BEAT_NAME_RE.match(n) and os.path.join(box, n) != path:
                _fsio.unlink_quiet(os.path.join(box, n))
        return path

    # ---------------------------------------------------------------- 直しの版のやり直し
    def fix_retries(self):
        reqs = self.fixes()
        if not reqs or getattr(self.app, "engine", None) is None:
            return []
        done = self.state.setdefault("fixed", {})
        out = []
        for rid in reqs:
            if done.get(rid) == self.version:
                continue
            r = self.app.inbox.row(rid)
            if r is not None and r["state"] in ("sent", "making", "recording", "waiting"):
                continue   # まだ動いている = この版で作っている(終わってから見る)
            done[rid] = self.version
            if r is None or r["state"] != "failed" or r.get("cancelled") or r.get("takeover") or r.get("pc") == "user" or not r.get("form"):
                continue
            try:
                self.app.api.retry(rid, final=True)
                out.append(rid)
                self.log("直しの版 %s で失敗していた依頼 %s を 1 回やり直します" % (self.version, rid))
            except Exception as e:   # noqa: BLE001  (1 行の失敗で見回りを止めない)
                self.log("直しの版のやり直しに失敗しました %s: %s %s" % (rid, e.__class__.__name__, str(e)[:160]))
        self._save()
        return out

    # ---------------------------------------------------------------- 固まり(依頼の段)
    def stuck_check(self, now):
        api, eng, inbox = getattr(self.app, "api", None), getattr(self.app, "engine", None), getattr(self.app, "inbox", None)
        if api is None or eng is None or inbox is None:
            return []
        stats = inbox.stage_stats()
        out = []
        for rid, seen in list((getattr(api, "_stages", None) or {}).items()):
            label, start, _raw, last = seen
            base = typical(stats.get(label))
            if base is None or rid in self._stopped:
                continue
            limit = max(STUCK_FLOOR, STUCK_FACTOR * base)
            if now * 1000 - max(start, last) < limit * 1000:
                continue
            r = inbox.row(rid)
            if r is None or r["state"] not in ("sent", "making"):
                continue
            self._stopped.add(rid)
            inbox.fail(rid, STUCK_TEXT % (STUCK_FACTOR, int(limit // 60)))
            if r.get("runId"):
                try:
                    eng.queue.cancel(r["runId"])   # その実行と、その実行が起こした子だけを止める
                except Exception as e:   # noqa: BLE001  (もう終わっていた)
                    self.log("固まった実行を止められませんでした %s: %s" % (rid, e.__class__.__name__))
            self.log("依頼 %s の段「%s」が %d 分進まないので止めて失敗にしました" % (rid, label, int(limit // 60)))
            out.append(rid)
        return out

    # ---------------------------------------------------------------- 見回り(玄関の watch から 10 秒ごと)
    def tick(self):
        now = self.clock()
        self.discard_cancelled()
        st = self.app.state()
        pending = st.get("update") or ""
        if pending:
            seen = self.state.setdefault("seen", {})
            if pending not in seen:
                seen[pending] = int(now * 1000)
                self.state["seen"] = {k: v for k, v in seen.items() if vt(k) > vt(self.version)}
                self._save()
            if self.important(pending) and not self.app.update_requested:
                self.app.update_requested = True
                self.log("重要な直しの版 %s が届きました。今の処理が終わったら入れ替えます" % pending)
        self._verify_tick(now, (st.get("recording") or 0) > self.stalled())
        self.fix_retries()
        if now - self._stuck_at >= STUCK_EVERY:
            self._stuck_at = now
            self.stuck_check(now)
        if now - self._beat_at >= BEAT_EVERY:
            self._beat_at = now
            self.beat(now)


def _diag_mask(app, s):
    d = getattr(app, "diag", None)
    return d.mask(s) if d is not None else str(s)
