"""入口の中で動く「分析と日報」: 見張り(新しい raw を受け取って分析し LINE へ)・画面と API(/analytics/)。

流れ(plan/analytics-daily-report.md の先頭の決定):
1. iPhone でブックマークをタップ → 既存の Apps Script が Drive の raw/<日付>.json に置く
2. ここが連携(gas/Code.gs)から合言葉付きで新しい raw を受け取り、作業データ analytics/raw/ に保存
3. 日付ごとにいちばん新しい raw で日報を作り、連携へ送り返す(→ LINE)。送ったあとに同じ日の新しい raw が来たら作り直して送り直す
4. 週報は確定した週が変わったら・月報は確定した月が変わったら、同じ流れで送る
5. 画面の「今すぐ」でも同じこと(手動)。PC が止まっていた日は、起動したときに最新の分だけ送る

作業データ(%LOCALAPPDATA%/youtube-tools/analytics/。YTT_DATA_DIR=inplace なら src/analytics/data/):
- config.json: {"url", "secret", "enabled"}(合言葉は画面へ返さない)
- raw/<名前>__<ファイルID>.json: 受け取った raw(そのまま)
- reports/<kind>/<期間>.json・.html・.txt: 作った報告(画面で見る)
- state.json: 受け取った記録・送った記録・最後の実行
"""
import datetime
import json
import os
import re
import threading
import time
import traceback

from . import VERSION, bridge as bridge_mod, calc, data, render

CHECK_EVERY = 300        # 新しい raw を見る間隔(秒)
FIRST_WAIT = 45          # 起動してから最初に見るまで(秒。ツールの起動とぶつけない)
DEFAULT_PLAN = 28        # 予定の週のショートの本数の既定(ユーザー 10-09「週 28 付近を維持するつもり」)
RAW_KEEP = 400          # 受け取った raw を残す数(古いものから消す。1 つ 約 0.5MB)
NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,200}$")
PERIOD_RE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
STATIC = {"/analytics/": ("index.html", "text/html; charset=utf-8"), "/analytics/index.html": ("index.html", "text/html; charset=utf-8"),
          "/analytics/app.js": ("app.js", "application/javascript; charset=utf-8"),
          "/analytics/app.css": ("app.css", "text/css; charset=utf-8")}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-src 'self'; "
       "object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
# 報告の HTML(画面の中の枠で見る): スクリプトは無い・スタイルは HTML の中だけ
REPORT_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
STATE_LABELS = {"off": "連携の設定がまだです", "idle": "動いています", "running": "分析しています…", "error": "止まっています"}
KIND_NAMES = {"daily": "日報", "weekly": "週報", "monthly": "月報"}


def data_dir(legacy=None):
    """作業データのフォルダ(ytt_core.datadir の規則。inplace なら src/analytics/data)"""
    from ytt_core import datadir
    legacy = legacy or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    return datadir.tool_dir("analytics", legacy)


class Service:
    def __init__(self, base_dir=None, log=None, members=None, bridge_factory=None, clock=None, sims=calc.SIMS,
                 check_every=CHECK_EVERY, first_wait=FIRST_WAIT, write=None, token=None):
        self.dir = base_dir or data_dir()
        self.log = log or (lambda msg: None)
        self.members = members           # 題名 → [メンバー](無ければ最初に使うときに ytt_core.colors から作る)
        self.bridge_factory = bridge_factory or bridge_mod.Bridge
        self.clock = clock or time.time
        self.sims = sims
        self.check_every, self.first_wait = check_every, first_wait
        self.write = write or _atomic_write
        self.token = token               # 入口の合言葉(画面に渡す。入口の inject_token と同じ)
        self.lock = threading.Lock()     # 分析・送信は 1 つずつ
        self.wake = threading.Event()
        self.closed = False
        self.thread = None
        self.state, self.message = "off", ""
        self.pending = None              # 手動の依頼 {"kind", "send", "force"}
        self.st = self._read_json("state.json") or {}
        self.st.setdefault("seen", {})       # ファイル ID → updated
        self.st.setdefault("sent", {})       # kind → {期間: {"rawId", "rawUpdated", "at", "url"}}
        self.st.setdefault("runs", [])

    # ---------------------------------------------------------------- ファイル
    def path(self, *parts):
        return os.path.join(self.dir, *parts)

    def _read_json(self, *parts):
        try:
            with open(self.path(*parts), "rb") as f:
                return json.loads(f.read(64 * 1024 * 1024).decode("utf-8-sig"))
        except (OSError, ValueError):
            return None

    def _write_json(self, obj, *parts):
        os.makedirs(os.path.dirname(self.path(*parts)), exist_ok=True)
        self.write(self.path(*parts), json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8"))

    def config(self):
        c = self._read_json("config.json") or {}
        return c if isinstance(c, dict) else {}

    def configured(self):
        c = self.config()
        return bool(c.get("url") and c.get("secret"))

    def set_config(self, url=None, secret=None, enabled=None, plan=None, boundary=None):
        """画面から。合言葉は空なら今のまま(画面へは返さないので、URL だけ直すときに入れ直さなくてよい)。
        plan = 予定の週のショートの本数(見込みの「予定」の行と YPP の判定に使う。1〜140)"""
        c = self.config()
        if url is not None:
            c["url"] = bridge_mod.check_url(url)
        if secret:
            c["secret"] = bridge_mod.check_secret(secret)
        if enabled is not None:
            c["enabled"] = bool(enabled)
        if plan is not None:
            if isinstance(plan, bool) or not isinstance(plan, (int, float)) or not 1 <= plan <= 140:
                raise ValueError("予定の本数は 1〜140 の数で入れてください")
            c["planPerWeek"] = int(plan)
        if boundary is not None:
            try:
                d = datetime.date.fromisoformat(str(boundary))
            except ValueError:
                raise ValueError("境目の日は YYYY-MM-DD で入れてください")
            if not datetime.date(2026, 1, 1) <= d <= datetime.date(2030, 12, 31):
                raise ValueError("境目の日が正しくありません")
            c["boundary"] = d.isoformat()
        c.setdefault("enabled", True)
        self._write_json(c, "config.json")
        self.wake.set()
        return self.public_config()

    def public_config(self):
        c = self.config()
        return {"url": c.get("url") or "", "hasSecret": bool(c.get("secret")), "enabled": c.get("enabled", True),
                "planPerWeek": c.get("planPerWeek", DEFAULT_PLAN), "boundary": c.get("boundary") or calc.BOUNDARY.isoformat()}

    def bridge(self):
        c = self.config()
        return self.bridge_factory(c.get("url"), c.get("secret"))

    def _matcher(self):
        if self.members is None:
            try:
                from ytt_core import colors
                self.members = data.member_matcher(colors.load())
            except Exception as e:   # 一覧が読めなくても分析は続ける(配信者の列が空になるだけ)
                self.log("分析: メンバーの一覧を読めませんでした: %s" % e.__class__.__name__)
                self.members = lambda title: []
        return self.members

    # ---------------------------------------------------------------- 見張り
    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._loop, name="analytics", daemon=True)
            self.thread.start()

    def close(self):
        self.closed = True
        self.wake.set()

    def run_now(self, kind=None, send=True):
        """画面の「今すぐ」: 受け取り → kind(None なら期限の来たもの全部)を作り直す → send なら LINE へ(同じ raw でも送り直す)"""
        if kind is not None and kind not in calc.KINDS:
            raise ValueError("kind は daily・weekly・monthly のどれか")
        self.pending = {"kind": kind, "send": bool(send), "force": True}
        self.wake.set()
        if self.thread is None:   # テストなど、見張りを動かしていないとき
            self.tick()
        return self.snapshot()

    def _loop(self):
        self.wake.wait(self.first_wait)
        while not self.closed:
            self.wake.clear()
            try:
                self.tick()
            except Exception as e:   # 想定外でも止めない(次の回でやり直す)
                self.state, self.message = "error", "分析が途中で止まりました。次の回でもう一度試します(詳しくは入口のログ)"
                self.log("分析: 内部エラー: %s %s" % (e.__class__.__name__, traceback.format_exc()[-600:]))
            self.wake.wait(self.check_every)

    def tick(self):
        req, self.pending = self.pending, None
        if not self.configured():
            self.state, self.message = "off", "Apps Script の連携の URL と合言葉を入れてください"
            return None
        if not self.config().get("enabled", True) and not req:
            self.state, self.message = "off", "自動の実行はオフです(画面の「今すぐ」は使えます)"
            return None
        with self.lock:
            self.state, self.message = "running", ""
            out = {"fetched": [], "sent": [], "errors": []}
            try:
                b = self.bridge()
                out["fetched"] = self.fetch(b)
                for kind in calc.KINDS:
                    if req and req["kind"] not in (None, kind):
                        continue
                    r = self.process(b, kind, force=bool(req and req["force"]), send=req["send"] if req else True)
                    if r:
                        out["sent"].append(r)
                self.state, self.message = "idle", ""
            except bridge_mod.BridgeError as e:
                self.state, self.message = "error", e.message
                out["errors"].append(e.message)
                self.log("分析: 連携: %s" % e.message)
            except data.DataError as e:
                self.state, self.message = "error", "受け取ったデータの形が違います: %s" % e
                out["errors"].append(str(e))
            self.st["runs"] = ([{"at": int(self.clock() * 1000), "manual": bool(req), "fetched": len(out["fetched"]),
                                 "sent": [s["kind"] + ":" + s["period"] for s in out["sent"]], "errors": out["errors"]}] + self.st["runs"])[:30]
            self._write_json(self.st, "state.json")
            return out

    def fetch(self, b):
        """新しい・更新された raw を受け取って保存する。-> 保存した名前の一覧"""
        since = self.st.get("listedUntil")
        files = b.list_raw(since)
        got = []
        for f in files:
            fid, name, upd = str(f.get("id") or ""), str(f.get("name") or ""), str(f.get("updated") or "")
            if not ID_RE.match(fid) or not NAME_RE.match(name) or self.st["seen"].get(fid) == upd:
                continue
            r = b.get_raw(fid)
            try:
                raw = json.loads(r["content"])
            except ValueError:
                self.log("分析: raw が JSON として読めません: %s" % name)
                continue
            data.parse(raw)   # 形の検査(違えば DataError で止める = 送らない)
            raw["_bridge"] = {"id": fid, "name": name, "updated": upd}
            self._write_json(raw, "raw", "%s__%s.json" % (name[:-5], fid))
            self.st["seen"][fid] = upd
            got.append(name)
            if upd and upd > (self.st.get("listedUntil") or ""):
                self.st["listedUntil"] = upd
        self._prune_raw()
        if got:
            self.log("分析: データを受け取りました: %s" % ", ".join(got))
        return got

    def _prune_raw(self):
        try:
            names = sorted(n for n in os.listdir(self.path("raw")) if n.endswith(".json"))
        except OSError:
            return
        for n in names[:max(0, len(names) - RAW_KEEP)]:
            try:
                os.remove(self.path("raw", n))
            except OSError:
                pass

    def latest_raw(self):
        """いちばん新しい raw(日付の新しいもの・同じ日なら更新の新しいもの)-> (dict, meta) か (None, None)"""
        best = None
        try:
            names = os.listdir(self.path("raw"))
        except OSError:
            return None, None
        for n in names:
            m = re.match(r"^(\d{4}-\d{2}-\d{2})__([A-Za-z0-9_-]+)\.json$", n)
            if not m:
                continue
            raw = self._read_json("raw", n)
            if not isinstance(raw, dict):
                continue
            meta = raw.get("_bridge") or {"id": m.group(2), "name": m.group(1) + ".json", "updated": ""}
            key = (m.group(1), str(meta.get("updated") or ""), str(raw.get("fetched_at") or ""))
            if best is None or key > best[0]:
                best = (key, raw, meta)
        return (best[1], best[2]) if best else (None, None)

    def process(self, b, kind, force=False, send=True):
        """kind の報告が要るか決めて、要れば作って(send なら)送る。-> {"kind", "period", "url"?} か None"""
        raw, meta = self.latest_raw()
        if raw is None:
            if force:
                self.message = "まだデータがありません(iPhone でブックマークをタップしてください)"
            return None
        ds = data.parse(raw, self._matcher())
        period = calc.period_key(ds, kind)
        sent = self.st["sent"].setdefault(kind, {})
        prev = sent.get(period)
        if kind == "daily":
            due = prev is None or prev.get("rawId") != meta.get("id") or prev.get("rawUpdated") != meta.get("updated")
            if prev is None and period < max(sent.keys(), default=""):
                due = False   # もっと新しい日の日報を送ったあと(古い日の分は送らない)
        else:
            due = prev is None and period > max(sent.keys(), default="")   # 週・月は区切りが変わったときに 1 回だけ
        if not (due or force):
            return None
        t0 = self.clock()
        cfg = self.public_config()
        boundary = datetime.date.fromisoformat(cfg["boundary"])
        ledger = self.st.setdefault("ledger", [])

        def work():
            r = calc.report(ds, kind, sims=self.sims, plan=cfg["planPerWeek"], boundary=boundary, ledger=ledger)
            if kind == "daily":   # ⑥ 今日の見込みを記録(同じ確定日の分は置き換える)。あとで実際と比べる
                row = calc.ledger_row(ds, calc.confirmed(ds), r["outlook"])
                ledger[:] = [x for x in ledger if x.get("made") != row["made"]][-400:] + [row]
            return r
        r = _heavy(work, "%sの計算" % KIND_NAMES[kind])
        text, html = {"daily": render.daily_parts, "weekly": render.weekly_parts, "monthly": render.monthly_parts}[kind](r)
        self._save_report(kind, period, r, text, html, meta)
        out = {"kind": kind, "period": period, "seconds": round(self.clock() - t0, 1)}
        if send:
            res = b.report(kind, period, text, html, {"rawId": meta.get("id"), "rawUpdated": meta.get("updated"), "fetched": r["fetched"],
                                                      "tool": VERSION})
            sent[period] = {"rawId": meta.get("id"), "rawUpdated": meta.get("updated"), "at": int(self.clock() * 1000), "url": res.get("url") or ""}
            out["url"] = res.get("url") or ""
            self.log("分析: %s(%s)を LINE に送りました" % (KIND_NAMES[kind], period))
        return out

    def _save_report(self, kind, period, r, text, html, meta):
        r = dict(r, source=meta, text=text, savedAt=int(self.clock() * 1000))
        self._write_json(r, "reports", kind, period + ".json")
        os.makedirs(self.path("reports", kind), exist_ok=True)
        self.write(self.path("reports", kind, period + ".html"), html.encode("utf-8"))

    # ---------------------------------------------------------------- 画面
    def reports(self):
        out = {}
        for kind in calc.KINDS:
            try:
                names = sorted((n[:-5] for n in os.listdir(self.path("reports", kind)) if n.endswith(".html")), reverse=True)
            except OSError:
                names = []
            sent = self.st["sent"].get(kind, {})
            out[kind] = [{"period": n, "sent": bool(sent.get(n)), "sentAt": (sent.get(n) or {}).get("at"), "url": (sent.get(n) or {}).get("url") or ""}
                         for n in names[:60]]
        return out

    def snapshot(self):
        raw, meta = self.latest_raw()
        latest = None
        if raw:
            latest = {"name": meta.get("name"), "fetchedAt": raw.get("fetched_at"), "updated": meta.get("updated")}
        state = self.state
        if state == "off" and self.configured() and self.config().get("enabled", True):
            state = "idle"   # 設定は済んで、まだ 1 回も見ていないだけ
        return {"version": VERSION, "state": state, "stateLabel": STATE_LABELS.get(state, ""), "message": self.message,
                "config": self.public_config(), "latestRaw": latest, "runs": self.st.get("runs", [])[:10], "reports": self.reports(),
                "busy": self.lock.locked()}

    def handle_get(self, h, u):
        """入口の do_GET から(/analytics/…)。受け持ったら True"""
        p = u.path
        if p == "/analytics":
            h._send(301, b"", "text/plain; charset=utf-8", {"Location": "/analytics/"})
            return True
        if p in STATIC:
            name, ctype = STATIC[p]
            try:
                with open(os.path.join(WEB_DIR, name), "rb") as f:
                    body = f.read()
            except OSError:
                h._send(404, b"not found")
                return True
            extra = None
            if name.endswith(".html"):
                if self.token:
                    body = _inject_token(body, self.token)
                extra = {"Content-Security-Policy": CSP, "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer"}
            h._send(200, body, ctype, extra)
            return True
        if p == "/analytics/api/state":
            h._json(200, self.snapshot())
            return True
        m = re.match(r"^/analytics/report/(daily|weekly|monthly)/([0-9-]{7,10})\.(html|json)$", p)
        if m:
            kind, period, ext = m.groups()
            if not PERIOD_RE.match(period):
                h._json(404, {"error": "not_found", "message": "その報告はありません"})
                return True
            try:
                with open(self.path("reports", kind, period + "." + ext), "rb") as f:
                    body = f.read()
            except OSError:
                h._json(404, {"error": "not_found", "message": "その報告はありません"})
                return True
            if ext == "html":
                h._send(200, body, "text/html; charset=utf-8", {"Content-Security-Policy": REPORT_CSP, "X-Frame-Options": "SAMEORIGIN"})
            else:
                h._send(200, body, "application/json; charset=utf-8")
            return True
        if p.startswith("/analytics/"):
            h._json(404, {"error": "not_found", "message": "その操作はありません"})
            return True
        return False

    def handle_post(self, h, u, body):
        """入口の do_POST から(合言葉・Origin の検査と本文の読み取りは済んでいる)"""
        p = u.path
        try:
            if p == "/analytics/api/config":
                return h._json(200, {"config": self.set_config(body.get("url"), body.get("secret"), body.get("enabled"), body.get("plan"),
                                                               body.get("boundary"))})
            if p == "/analytics/api/run":
                if self.lock.locked():
                    return h._json(409, {"error": "busy", "message": "分析の途中です。終わってからもう一度押してください"})
                return h._json(200, self.run_now(body.get("kind"), body.get("send") is not False))
            if p == "/analytics/api/ping":
                if not self.configured():
                    return h._json(400, {"error": "off", "message": "連携の URL と合言葉を入れてください"})
                r = self.bridge().ping()
                return h._json(200, {"ok": True, "folder": r.get("folder"), "remote": r.get("version")})
        except bridge_mod.BridgeError as e:
            return h._json(400, {"error": e.code, "message": e.message})
        except (ValueError, OSError) as e:
            return h._json(400, {"error": "bad_request", "message": str(e)})
        return h._json(404, {"error": "not_found", "message": "その操作はありません"})


def _heavy(fn, label):
    """見込みの計算(数秒〜十数秒)は、他のツールの重い処理と順番を待つ(ytt_core.jobs.SLOTS。AGENTS.md の決まり)"""
    try:
        from ytt_core import jobs
    except ImportError:
        return fn()
    with jobs.SLOTS.slot("analytics", label) as ok:
        if not ok:
            raise data.DataError("取り消されました")
        return fn()


def _inject_token(body, token):
    tag = ('<meta name="ytt-token" content="%s">' % token).encode("ascii")
    i = body.find(b"</head>")
    return body[:i] + tag + body[i:] if i >= 0 else tag + body


def _atomic_write(path, data_bytes):
    try:
        from ytt_core import fsio
        fsio.atomic_write(path, data_bytes)
    except ImportError:
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data_bytes)
        os.replace(tmp, path)


