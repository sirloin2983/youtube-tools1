# -*- coding: utf-8 -*-
"""友人のアプリの診断の記録(ユーザー決定。notes:docs/spec/friend.md の 13-11)。友人の PC でしか出ない不具合を、伝聞でなく記録で追うため。

- 依頼 1 件ごと(② の実行が終わったとき = kind run。確認用の動画を作り終えたとき = preview。ライブの行を閉じたとき・ライブの受付に失敗したとき = live)と、
  エラーのとき(error・sync・setup・start・rollback・token・exception・update)に、JSON 1 つを送り返しの箱 <data>/app/outbox/ へ
  <依頼 id か app>__diag-<at ミリ秒 13 桁>.diag.json で書く。
  live の中身: stage(close = 行を閉じた・submit = 受付の失敗)・outcome(行の状態・パックの数・理由の種類 cause・切り抜きの実行の失敗)・
  live(friendapp/live_session.FriendLive.live_facts を mask_tree で伏せた物 = 録画の長さ・候補と採用の数・検出の記録・心拍・チャット・諦めた採用・
  書き出しの失敗・配信後の追加・依頼の設定)
  exe(FriendApp.exe)も同じ箱へ launcher__diag-<at>.diag.json を書く(起動・更新の失敗。Core.cs の Diag)。
  上げるのは同期(friendapp/sync.py の 4 送り返し)で、置き場所だけ Dropbox の /診断/(送り返しの受付 human/friend/returns は読まない)
- 中身: アプリの版・Windows の版・GPU の名前・文字起こしの機器・各段の始めと終わりと秒・文字起こしの装置と実時間比・エラーの種類(progress.classify)と要約・
  外の道具(yt-dlp・ffmpeg など。ytt/tools.recent)の終了コードと失敗の最後の数行
- 入れない物: Windows のユーザー名を含むパス(mask で <user>・アプリのフォルダは <app>)・合言葉・Dropbox の鍵・API キー(mask で伏せる)・動画の中身。道具の引数も持たない
- 片付け: 書くたびに箱の 3 日より古い診断を消す(上げられなかった物も。inbox.KEEP_DAYS)。Dropbox の /診断/ の 3 日より古い物は同期が消す(prune_names)
- スイッチ: 環境変数 YTT_FRIEND_DIAG=0 で書かない。ユーザーの PC の作業データ(places.is_maker_data)でも書かない
読むのはユーザーの PC の dev/friend_diag.py(最新の数件を段ごとの秒・エラーで一覧)。
"""
import json
import os
import platform
import re
import sys
import threading
import time

from ytt import fsio as _fsio, tools as _tools, version as _version, ytcookies as _ytcookies

from . import inbox as _inbox, places as _places, progress as _progress

V = 1
SWITCH_ENV = "YTT_FRIEND_DIAG"
NAME_RE = re.compile(r"^([0-9A-Za-z_-]{1,64})__diag-(\d{13})\.diag\.json$")
SAFE_ID = re.compile(r"^[0-9A-Za-z_-]{1,64}$")
MAX_BYTES = 128 * 1024              # 1 つの大きさの上限(超えたら道具の行と詳しい文を削る)
DETAIL_MAX = 4000
SUMMARY_MAX = 300
LOCAL_MAX = 300                     # 箱に置く診断の数の上限(古い物から消す)
TOOLS_MAX = 30
EXPORTS_MAX = 20   # 書き出しの記録(1 本ずつの作り方・元の形・秒)の数の上限
KEEP_SEC = _inbox.KEEP_DAYS * _inbox.DAY

_USERS = re.compile(r"(?i)([A-Z]:[\\/]+(?:Users|Documents and Settings)[\\/]+)[^\\/\"'<>|\r\n\t]+")
_SECRETS = (
    (re.compile(r"AIza[0-9A-Za-z_-]{30,}"), "<key>"),                                     # YouTube の API キー
    (re.compile(r"\bsl\.[0-9A-Za-z_-]{20,}"), "<token>"),                                 # Dropbox の access token
    (re.compile(r"(?i)(refresh_token|access_token|appKey|refreshToken|X-YTT-Token|Authorization)([\"'\s:=]+)(Bearer\s+)?[^\s\"',}]+"), r"\1\2<secret>"),
    (re.compile(r"\b[0-9a-f]{48}\b"), "<token>"),                                         # exe の合言葉の形(24 バイトの 16 進)
)


def _env_secrets(env):
    out = []
    for k in ("YTT_FRIEND_TOKEN", "YTT_YT_API_KEY"):
        v = (env.get(k) or "").strip()
        if len(v) >= 8:
            out.append(v)
    return out


def mask(text, home=None, env=None):
    """文から個人の情報と秘密を伏せる: アプリのフォルダ -> <app>・%USERPROFILE% と C:\\Users\\<名前> -> <user>・ユーザー名 -> <user>・
    合言葉・鍵・API キー -> <secret> など。文でない物は str にする"""
    env = os.environ if env is None else env
    s = "" if text is None else str(text)
    for v in _env_secrets(env):
        s = s.replace(v, "<secret>")
    for pat, rep in _SECRETS:
        s = pat.sub(rep, s)
    if home:
        for h in {home, home.replace("\\", "/")}:
            s = re.sub(re.escape(h), "<app>", s, flags=re.I)
    prof = env.get("USERPROFILE") or ""
    if len(prof) > 3:
        for h in {prof, prof.replace("\\", "/")}:
            s = re.sub(re.escape(h), "<user>", s, flags=re.I)
    s = _USERS.sub(r"\1<user>", s)
    user = (env.get("USERNAME") or "").strip()
    if len(user) >= 3:
        s = re.sub(r"(?i)(?<![0-9A-Za-z])%s(?![0-9A-Za-z])" % re.escape(user), "<user>", s)
    return s


def windows_text():
    """Windows の版(例: "Windows 10.0.26100"。build 22000 以上は 11)"""
    try:
        if os.name == "nt":
            w = sys.getwindowsversion()
            return "Windows %s %d.%d.%d" % ("11" if w.build >= 22000 else str(w.major), w.major, w.minor, w.build)
        return "%s %s" % (platform.system(), platform.release())
    except Exception:   # noqa: BLE001
        return "?"


def stage_rows(steps, mask_fn):
    """② の steps -> [{key, label(友人の段), start, end, sec, state, detail}]。始まらなかった段は入れない"""
    out = []
    for s in steps or []:
        a, b = s.get("startedAt"), s.get("finishedAt")
        if not isinstance(a, int) or isinstance(a, bool):
            continue
        b = b if isinstance(b, int) and not isinstance(b, bool) else None
        out.append({"key": s.get("key"), "label": _progress.FRIEND_OF.get(s.get("key")) or "", "start": a, "end": b,
                    "sec": round(max(0, b - a) / 1000.0, 1) if b is not None else None, "state": s.get("state") or "",
                    "detail": mask_fn(str(s.get("detail") or "")[:300]),
                    **({"early": s["early"]} if isinstance(s.get("early"), int) and s["early"] else {})})   # 書き出しの最中に先に済ませた本数(流れ作業)
    return out


def transcribe_rows(recs):
    """文書の認識の記録(engine.transcribe_records)-> [{device, backend, gpu, engine, model, audioSec, wallSec, ratio}]"""
    out = []
    for r in recs or []:
        audio, wall = r.get("audioSec"), r.get("wallSec")
        ok = isinstance(audio, (int, float)) and isinstance(wall, (int, float)) and audio > 0
        out.append({"device": r.get("device"), "backend": r.get("backend"), "gpu": r.get("gpu"), "engine": r.get("engine"),
                    "engineVersion": r.get("engineVersion"), "model": r.get("model"), "audioSec": audio, "wallSec": wall,
                    "ratio": round(wall / audio, 2) if ok else None,
                    **{k: r[k] for k in ("secs", "engineTiming") if isinstance(r.get(k), dict)}})   # 内訳(段ごとの秒・whisper.cpp の時間)
    return out


def probe_only(row):
    """「ffmpeg -i で中を読むだけ」の呼び出し(出力が無いので終了コード 1 が決まり。失敗に数えない)か"""
    tail = row.get("tail") or []
    return row.get("name") == "ffmpeg" and row.get("code") == 1 and bool(tail) and "At least one output file must be specified" in str(tail[-1])


def prune_names(names, now_ms):
    """Dropbox の /診断/ の名前のうち、消す物(3 日より古い・名前が違う物は触らない)"""
    out = []
    for n in names:
        m = NAME_RE.match(n or "")
        if m and now_ms - int(m.group(2)) >= KEEP_SEC * 1000:
            out.append(n)
    return out


class Diag:
    """診断を書く係(玄関に 1 つ)。書けなくても呼んだ側は止めない(-> パスか None)"""

    def __init__(self, places, clock=time.time, log=None, env=None, gpu_fn=None, device_fn=None, host=None):
        self.places, self.clock = places, clock
        self.log = log or (lambda msg: None)
        self.env = os.environ if env is None else env
        self.gpu_fn, self.device_fn = gpu_fn, device_fn
        self.host = host if host is not None else (self.env.get("YTT_FRIEND_HOST") or "").strip() or "browser"
        self._pc = None
        self._lock = threading.Lock()
        self._once = {}

    @property
    def box(self):
        return self.places["outbox"]

    def enabled(self):
        if (self.env.get(SWITCH_ENV) or "").strip().lower() in ("0", "off", "false", "no"):
            return False
        try:
            return not _places.is_maker_data(self.places["data"])
        except Exception:   # noqa: BLE001
            return True

    def mask(self, text):
        return mask(text, self.places.get("home"), self.env)

    def mask_tree(self, obj, depth=0):
        """dict・list の中の文を全部伏せた写し(数・真偽・None はそのまま。深さは 8 まで)"""
        if isinstance(obj, str):
            return self.mask(obj)
        if depth >= 8:
            return None
        if isinstance(obj, dict):
            return {str(k): self.mask_tree(v, depth + 1) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [self.mask_tree(v, depth + 1) for v in obj]
        return obj if obj is None or isinstance(obj, (bool, int, float)) else self.mask(str(obj))

    def pc(self):
        """{windows, gpu: {name, vendor, vramGB} か None, device}。GPU はプロセスの中で 1 回だけ調べる(ytt/gpuinfo = 黒い窓なし。exe から動いているときだけ)"""
        if self._pc is None:
            gpu = None
            try:
                if self.gpu_fn is not None:
                    gpu = self.gpu_fn()
                elif self.host != "browser":   # exe から動いているときだけ調べる(開発の PC とテストでは子プロセスを起こさない)
                    from ytt import gpuinfo as _gpuinfo
                    gpu = _gpuinfo.info()
            except Exception:   # noqa: BLE001
                gpu = None
            self._pc = {"windows": windows_text(), "gpu": {k: gpu.get(k) for k in ("name", "vendor", "vramGB")} if isinstance(gpu, dict) else None}
        out = dict(self._pc)
        try:
            out["device"] = self.device_fn() if self.device_fn is not None else None
        except Exception:   # noqa: BLE001
            out["device"] = None
        return out

    def base(self, kind, rid=None):
        return {"v": V, "kind": kind, "source": "python", "at": int(self.clock() * 1000), "requestId": rid if rid and SAFE_ID.match(rid) else None,
                "app": {"version": _version.VERSION, "host": self.host, "python": platform.python_version()}, "pc": self.pc(), "yt": self.yt()}

    def yt(self):
        """YouTube の取得の様子: ログインした時刻・切れた時刻・cookie の書き戻しの数(ytt/ytcookies.facts。値は入れない)・取り替えた yt-dlp の版"""
        out = {"login": _ytcookies.facts((self.env.get(_tools.COOKIES_ENV) or "").strip())}
        try:
            from . import ytdlp_update as _ytdlp_update
            out["ytdlp"] = _ytdlp_update.facts(self.env)
        except Exception:   # noqa: BLE001
            out["ytdlp"] = None
        return out

    def write(self, kind, rid=None, summary="", detail="", code=None, **fields):
        """1 つ書く。summary / detail は伏せてから入れる。fields はそのまま(作る側で伏せる)"""
        if not self.enabled():
            return None
        try:
            doc = self.base(kind, rid)
            doc["summary"] = self.mask(summary)[:SUMMARY_MAX]
            if detail:
                doc["detail"] = self.mask(detail)[:DETAIL_MAX]
            if code is None and kind != "run" and (summary or detail):
                code = _progress.classify("%s\n%s" % (summary, detail), "url").get("code")
            if code:
                doc["code"] = code
            doc.update(fields)
            return self._put(doc)
        except Exception as e:   # noqa: BLE001  (診断で玄関を止めない)
            self.log("診断を書けませんでした: %s" % e.__class__.__name__)
            return None

    def once(self, key, every_sec, kind, **kw):
        """同じ key は every_sec 秒に 1 回だけ書く(同期の失敗が 3 分おきに続くとき・合言葉の違い)"""
        now = self.clock()
        with self._lock:
            last = self._once.get(key)
            if last is not None and now - last < every_sec:
                return None
            self._once[key] = now
        return self.write(kind, **kw)

    def tools_since(self, since_ms):
        rows = [r for r in _tools.recent(since_ms) if not probe_only(r)][-TOOLS_MAX:]
        for r in rows:
            r["tail"] = [self.mask(x) for x in r.get("tail") or []]
        return rows

    def run(self, run, row=None, transcribe=None, exports=None):
        """② の実行 1 本が終わった(依頼 1 件ごと)。row = 受信箱の行(kind・区間・pc)"""
        steps = getattr(run, "steps", None) or []
        starts = [s.get("startedAt") for s in steps if isinstance(s.get("startedAt"), int)]
        t0 = min(starts) if starts else int(self.clock() * 1000) - 3600 * 1000
        state = getattr(run, "state", "") or ""
        err = str(getattr(run, "error", "") or "") if state == "error" else ""
        form = (row or {}).get("form") or {}
        kind = (row or {}).get("kind") or "url"
        req = {"kind": kind, "ranged": bool(form.get("ranges")), "ranges": len(form.get("ranges") or []), "pc": (row or {}).get("pc"),
               "videoId": form.get("videoId"), "runId": getattr(run, "id", None), "state": state,
               "packs": len(run.all_packs()) if state == "done" and hasattr(run, "all_packs") else 0}
        stages = stage_rows(steps, self.mask)
        ends = [s["end"] for s in stages if s["end"]]
        total = round((max(ends) - t0) / 1000.0, 1) if ends else None
        code = _progress.classify(err, kind).get("code") if err else None
        rid = (row or {}).get("id") or getattr(run, "request_id", None)
        return self.write("run", rid=rid, summary=err.splitlines()[0] if err else "%s(%s 秒)" % (state, total), detail=err, code=code,
                          request=req, totalSec=total, stages=stages, transcribe=transcribe_rows(transcribe), tools=self.tools_since(t0 - 1000),
                          exports=[dict(x, gpuError=self.mask(x["gpuError"])[:300]) if x.get("gpuError") else x for x in (exports or [])][:EXPORTS_MAX])

    def _put(self, doc):
        data = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        if len(data) > MAX_BYTES:
            for t in doc.get("tools") or []:
                t["tail"] = t.get("tail", [])[-2:]
            doc["detail"] = (doc.get("detail") or "")[:1000]
            for s in doc.get("stages") or []:
                s["detail"] = s.get("detail", "")[:80]
            data = json.dumps(doc, ensure_ascii=False).encode("utf-8")[:MAX_BYTES]
            if len(data) >= MAX_BYTES:
                doc = {k: doc[k] for k in ("v", "kind", "source", "at", "requestId", "app", "pc", "summary", "code") if k in doc}
                doc["truncated"] = True
                data = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        who = doc.get("requestId") or "app"
        os.makedirs(self.box, exist_ok=True)
        with self._lock:
            at = doc["at"]
            while True:
                path = os.path.join(self.box, "%s__diag-%013d.diag.json" % (who, at))
                if not os.path.exists(path):
                    break
                at += 1
            _fsio.atomic_write(path, data)
            self._prune_local()
        return path

    def _prune_local(self):
        """箱の診断の片付け: 3 日より古い物と、LOCAL_MAX を超えた古い物を消す(exe が書いた物も)"""
        now_ms = int(self.clock() * 1000)
        got = []
        for n in os.listdir(self.box):
            m = NAME_RE.match(n)
            if m:
                got.append((int(m.group(2)), n))
        got.sort()
        for i, (at, n) in enumerate(got):
            if now_ms - at >= KEEP_SEC * 1000 or i < len(got) - LOCAL_MAX:
                _fsio.unlink_quiet(os.path.join(self.box, n))
