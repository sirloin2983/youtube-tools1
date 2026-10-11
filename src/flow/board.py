# -*- coding: utf-8 -*-
"""② 管理の層 flow: ジョブの掲示板(RS8 の ② の口 S1。2026-10-11。形は docs/spec/pipeline.md 2.9・設計 docs/design/rs8-flow-api.md)。

新しい画面(入口・案件の画面)が「今・何が・どこまで動いているか」を 1 つの形(Job)で読むための表。プロセスに 1 つ(default())。
画面が読むのは入口の GET /api/flow/status の jobs・cases・rev(src/app/server.py)。取り消し・やり直しも id 1 つで(POST /api/flow/cancel・retry)。

器(② の Run・編集のジョブ・解析・書き出し・パック・ライブ・③ の届ける・検索)は次の 2 つのどちらかの形で載せる(器の本体と今の API は変えない):
- 押す形 upsert(job): 器が状態を変える所で 1 行呼ぶ。器が忘れた物も、終わった直近 RECENT_MAX 件までは掲示板に残る
- 引く形 register(頭, source=fn): 問い合わせ(snapshot)のたびに fn() -> [job] を読んで写す(器が自分の状態を持ち、変わる所が多い物向け。② の Run はこれ =
  flow/runqueue.Queue.attach_board)。fn が返さなくなった待ち・実行中の物は消す(器が忘れた)・終わった物は残す
取り消し・やり直しは register(頭, cancel=fn, retry=fn) の fn(器の中の id) へ id の頭(PREFIXES)で振り分ける。
親子: link(子の id, 親の id) = ② の実行が頼んだ器のジョブ(Run.owned)を親の下に畳むための印。子が親なしで載ったら親を足す。
案件: Job の case は案件の根(fsio.norm_path)。器が知らなければ set_case_hook(fn) の fn(job) -> 根か None で引く(既定は無し。入口は guess_case を登録)。
① の器(書き出し・パック)は flow を読めない(層の向き)ので、呼び手(app の serve)が器の on_change の hook で upsert する。

import してよいのは標準ライブラリ・ytt・同じ flow だけ。表はメモリだけ(ファイル・ネットワークに触らない。guess_case だけは呼ばれたときに
flow/placement・ytt/docloc を読む)。
"""
import collections
import math
import os
import re
import threading
import time

from ytt import fsio
from .run import RUN_STATE_LABELS

# id の頭 -> 器(id = "<頭>:<器の中の id>"。器をまたいで衝突しない・取り消しの振り分けの鍵)
PREFIXES = {"run": "② の実行(flow/runqueue)", "tx": "編集のジョブ(文字起こし・話者・再認識。flow/jobs)", "an": "解析(flow/batch)",
            "ex": "書き出し(pipeline/export/exporter)", "pk": "パック(pipeline/pack/cut2resolve_core)", "lx": "ライブの書き出し(flow/live_export)",
            "la": "ライブの作り直し(flow/live_archive)", "lt": "配信中の候補の文字起こし(flow/live_tx)", "dl": "届ける(human/friend/deliver)",
            "se": "配信の検索(human/find/rank)"}
# Run.owned のツールの ID -> 頼んだ器の id の頭(親子の印。runqueue が使う)
OWNED_PREFIX = {"transcribe": "tx", "studio": "an", "cut2resolve": "pk"}
# 段の語彙(flow/run.STEP_LABELS の鍵 + 器の種類)。増やすときはここに足す
KINDS = ("run", "analyze", "adopt", "export", "transcribe", "diarize", "pack", "deliver", "rerun", "search", "live_export", "live_archive", "live_tx")
STATES = ("queued", "running", "done", "error", "cancelled", "skipped")
ACTIVE = ("queued", "running")
STATE_LABELS = dict({k: RUN_STATE_LABELS[k] for k in ("queued", "running", "done", "error", "cancelled")}, skipped="飛ばしました")
TARGET_KEYS = ("videoId", "docId", "markId", "path", "recording")
STEP_KEYS = ("key", "label", "state", "detail", "startedAt", "finishedAt")
FIELDS = ("id", "kind", "parent", "case", "target", "title", "state", "stateLabel", "phase", "progress", "waiting",
          "createdAt", "startedAt", "finishedAt", "error", "canCancel", "canRetry", "steps")
RECENT_MAX = 30          # 終わったジョブを残す数(新しい物から)
TEXT_MAX = 200           # title・phase・stateLabel・target の値の長さ
ERROR_MAX = 2000         # error の text・detail の長さ
LINK_MAX = 500           # 親子の印を覚える数
CASE_RETRY_SEC = 30.0    # case_hook が根を引けなかった物を引き直すまでの秒(案件のフォルダは書き出しのあとにできる)
ID_RE = re.compile(r"^([a-z]{2,3}):([A-Za-z0-9._-]{1,80})\Z")


class NotFound(LookupError):
    """その id のジョブが掲示板に無い(入口は 404)"""


class Refused(Exception):
    """今はできない(入口は 409)。code = cannot_cancel / cannot_retry"""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def split_id(jid):
    """"<頭>:<器の中の id>" -> (頭, 器の中の id)。形が違う・知らない頭は理由つきの ValueError"""
    m = ID_RE.match(jid) if isinstance(jid, str) else None
    if not m or m.group(1) not in PREFIXES:
        raise ValueError("ジョブの id は「頭:id」の形にしてください(頭は %s)" % "・".join(PREFIXES))
    return m.group(1), m.group(2)


def norm_case(p):
    """案件の根の比べ方(fsio.norm_path)。絶対パスの文字でなければ None"""
    return fsio.norm_path(p) if isinstance(p, str) and p and len(p) <= 1000 and os.path.isabs(p) else None


def _text(v, limit=TEXT_MAX):
    return v[:limit] if isinstance(v, str) else ""


def _ms(v):
    """時刻(ミリ秒の整数)か None。小数は切り捨て"""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or (isinstance(v, float) and not math.isfinite(v)):
        return None
    return int(v) if v >= 0 else None


def _progress(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or (isinstance(v, float) and not math.isfinite(v)):
        return None
    return min(1.0, max(0.0, float(v)))


def _error(v):
    """error: None / 文字 / {code, text, detail} -> None か {code, text, detail}"""
    if v is None or v == "":
        return None
    if isinstance(v, str):
        return {"code": None, "text": v[:ERROR_MAX], "detail": None}
    if not isinstance(v, dict):
        raise ValueError("Job.error は文字か {code, text, detail} にしてください")
    code = v.get("code")
    return {"code": code[:64] if isinstance(code, str) and code else None, "text": _text(v.get("text"), ERROR_MAX),
            "detail": v["detail"][:ERROR_MAX] if isinstance(v.get("detail"), str) and v["detail"] else None}


def _target(v):
    if v is None:
        return {}
    if not isinstance(v, dict):
        raise ValueError("Job.target は辞書にしてください")
    out = {}
    for k in TARGET_KEYS:
        x = v.get(k)
        if isinstance(x, str) and x:
            out[k] = x[:1000] if k == "path" else x[:TEXT_MAX]
        elif isinstance(x, int) and not isinstance(x, bool):
            out[k] = x
    return out


def _steps(v):
    if v is None:
        return None
    if not isinstance(v, list):
        raise ValueError("Job.steps はリストにしてください(kind run だけ)")
    return [{k: s[k] for k in STEP_KEYS if k in s} for s in v if isinstance(s, dict)]


def normalize(job, now_ms=None):
    """器が渡した Job -> 整えた新しい dict(docs/spec/pipeline.md 2.9 の形)。知らない項目・語彙の外の kind / state・形の違う id は理由つきの ValueError。
    無い項目は既定(parent・case・progress・時刻・error・steps = None・target = {}・文字 = ""・真偽 = False・stateLabel = STATE_LABELS)。
    canCancel は待ち・実行中のときだけ・canRetry は終わったときだけ真にできる。createdAt が無ければ now_ms(掲示板は None で渡し、置くときに最初の時刻)"""
    if not isinstance(job, dict):
        raise ValueError("Job は辞書にしてください")
    extra = [k for k in job if k not in FIELDS]
    if extra:
        raise ValueError("Job に知らない項目があります: %s(足すときは flow/board.py の FIELDS へ)" % "・".join(sorted(map(str, extra))))
    split_id(job.get("id"))
    kind, state = job.get("kind"), job.get("state")
    if kind not in KINDS:
        raise ValueError("Job.kind は %s のどれかにしてください: %r" % ("・".join(KINDS), kind))
    if state not in STATES:
        raise ValueError("Job.state は %s のどれかにしてください: %r" % ("・".join(STATES), state))
    parent = job.get("parent")
    if parent is not None:
        split_id(parent)
    active = state in ACTIVE
    created = _ms(job.get("createdAt"))
    return {"id": job["id"], "kind": kind, "parent": parent, "case": norm_case(job.get("case")), "target": _target(job.get("target")),
            "title": _text(job.get("title")), "state": state, "stateLabel": _text(job.get("stateLabel")) or STATE_LABELS[state],
            "phase": _text(job.get("phase")), "progress": _progress(job.get("progress")), "waiting": job.get("waiting") is True and active,
            "createdAt": created if created is not None else now_ms, "startedAt": _ms(job.get("startedAt")), "finishedAt": _ms(job.get("finishedAt")),
            "error": _error(job.get("error")), "canCancel": job.get("canCancel") is True and active,
            "canRetry": job.get("canRetry") is True and not active, "steps": _steps(job.get("steps")) if kind == "run" else None}


class Board:
    """ジョブの掲示板(表 {id: Job}・rev・器の登録)。糸をまたいで使える(self._lock)。器の関数(source・cancel・retry・case_hook)は lock の外で呼ぶ"""

    def __init__(self, recent=RECENT_MAX, clock=None, log=None):
        self.recent = recent
        self.clock = clock or time.time
        self.log = log or (lambda msg: None)
        self._lock = threading.Lock()
        self._jobs = collections.OrderedDict()   # id -> Job(入れた順)
        self._rev = 0
        self._handlers = {}                       # 頭 -> {"source", "cancel", "retry"}
        self._parents = collections.OrderedDict()  # 子の id -> 親の id
        self._case_hook = None
        self._case_cache = {}                     # (id, target の鍵) -> (根か None, 引いた時刻)

    # ------------------------------------------------------------ 登録
    def register(self, prefix, source=None, cancel=None, retry=None):
        """器を登録する(頭ごとに 1 つ。登録し直すと置き換える)。source() -> [Job](引く形)・cancel(器の中の id)・retry(器の中の id) -> 新しい Job。
        cancel は None か止めたあとの Job・retry は新しい Job を返す。できなければ ValueError(Refused になる)・無ければ LookupError(NotFound になる)を上げる"""
        if prefix not in PREFIXES:
            raise ValueError("知らない頭です: %r(%s)" % (prefix, "・".join(PREFIXES)))
        with self._lock:
            self._handlers[prefix] = {"source": source, "cancel": cancel, "retry": retry}

    def unregister(self, prefix):
        with self._lock:
            self._handlers.pop(prefix, None)

    def set_case_hook(self, fn):
        """case が無い Job の案件の根を引く fn(Job) -> 根か None(None で外す)。引けなかった物は CASE_RETRY_SEC ごとに引き直す"""
        with self._lock:
            self._case_hook = fn
            self._case_cache.clear()

    def link(self, child, parent):
        """子のジョブ(器のジョブ)を親(② の実行)の下に畳む印。子が載っていて親が無ければ今足す。形が違えば ValueError"""
        split_id(child)
        split_id(parent)
        with self._lock:
            self._parents.pop(child, None)
            self._parents[child] = parent
            while len(self._parents) > LINK_MAX:
                self._parents.popitem(last=False)
            j = self._jobs.get(child)
            if j is not None and j["parent"] is None:
                self._jobs[child] = dict(j, parent=parent)
                self._rev += 1

    # ------------------------------------------------------------ 載せる
    def _prepare(self, job):
        """lock の外: 整えて、親の印と案件の根を足す"""
        j = normalize(job)
        if j["parent"] is None:
            with self._lock:
                j["parent"] = self._parents.get(j["id"])
        if j["case"] is None:
            j["case"] = self._guess_case(j)
        return j

    def _guess_case(self, j):
        hook = self._case_hook
        if hook is None or not j["target"]:
            return None
        key = (j["id"], tuple(sorted(j["target"].items())))
        now = self.clock()
        with self._lock:
            got = self._case_cache.get(key)
        if got and (got[0] is not None or now - got[1] < CASE_RETRY_SEC):
            return got[0]
        try:
            root = norm_case(hook(j))
        except Exception as e:   # noqa: BLE001  (根を引けなくても載せる)
            self.log("掲示板: 案件の根を引けませんでした(%s %s)" % (j["id"], e.__class__.__name__))
            root = None
        with self._lock:
            if len(self._case_cache) > LINK_MAX:
                self._case_cache.clear()
            self._case_cache[key] = (root, now)
        return root

    def _put(self, j):
        """lock の中: 置く(createdAt が無ければ前の値)。変わったら真"""
        old = self._jobs.get(j["id"])
        if j["createdAt"] is None:   # 器が時刻を持たない: 最初に載せた時刻のまま(引く形で毎回変わらないように)
            j["createdAt"] = old["createdAt"] if old is not None else int(self.clock() * 1000)
        if old == j:
            return False
        self._jobs[j["id"]] = j
        return True

    def upsert(self, job):
        """押す形: Job を置く(同じ id は置き換え。並びは最初に入れた順のまま)。-> 整えた Job の写し。中身が同じなら rev は増えない"""
        j = self._prepare(job)
        with self._lock:
            if self._put(j):
                self._rev += 1
                self._trim()
            return dict(j)

    def remove(self, jid):
        """消す(無ければ何もしない)"""
        with self._lock:
            if self._jobs.pop(jid, None) is not None:
                self._rev += 1

    def sync(self, prefix, jobs):
        """引く形: 頭 prefix の器の今のジョブ jobs で置き換える(どれも prefix の頭の id)。jobs に無い待ち・実行中の物は消す・終わった物は残す。
        形の違う 1 件は飛ばしてログに 1 行(ほかは載せる)。-> 変わったら真"""
        ready = []
        for job in jobs or ():
            try:
                j = self._prepare(job)
                if split_id(j["id"])[0] != prefix:
                    raise ValueError("頭が %s でない id です: %s" % (prefix, j["id"]))
            except ValueError as e:
                self.log("掲示板: %s の器のジョブを載せられませんでした(%s)" % (prefix, e))
                continue
            ready.append(j)
        seen = {j["id"] for j in ready}
        changed = False
        with self._lock:
            for j in ready:
                changed = self._put(j) or changed
            for jid in [k for k, v in self._jobs.items() if k.startswith(prefix + ":") and k not in seen and v["state"] in ACTIVE]:
                del self._jobs[jid]
                changed = True
            if changed:
                self._rev += 1
                self._trim()
        return changed

    def refresh(self, prefix=None):
        """引く形の器を読み直す(prefix を付ければその器だけ)。器が失敗しても止めない(ログに 1 行)"""
        with self._lock:
            sources = [(p, h["source"]) for p, h in self._handlers.items() if h["source"] and (prefix is None or p == prefix)]
        for p, fn in sources:
            try:
                jobs = fn()
            except Exception as e:   # noqa: BLE001  (1 つの器が読めなくても掲示板は返す)
                self.log("掲示板: %s の器を読めませんでした(%s)" % (p, e.__class__.__name__))
                continue
            self.sync(p, jobs)

    def _trim(self):
        """lock の中: 終わったジョブを新しい RECENT_MAX 件まで(古い = 終わった時刻の早い物から消す)"""
        done = [j for j in self._jobs.values() if j["state"] not in ACTIVE]
        if len(done) <= self.recent:
            return
        done.sort(key=lambda j: (j["finishedAt"] or j["createdAt"] or 0))
        for j in done[:len(done) - self.recent]:
            del self._jobs[j["id"]]

    # ------------------------------------------------------------ 読む
    @property
    def rev(self):
        with self._lock:
            return self._rev

    def get(self, jid):
        with self._lock:
            j = self._jobs.get(jid)
            return dict(j) if j else None

    def list(self, case=None):
        """ジョブ(入れた順)。case = 案件の根(その案件だけ。norm_case で比べる)"""
        want = norm_case(case) if case is not None else None
        with self._lock:
            return [dict(j) for j in self._jobs.values() if case is None or (want is not None and j["case"] == want)]

    def cases(self):
        """案件ごとのまとめ {根: {active: 待ち・実行中の数, lastState: 最後に終わったジョブの state か None, lastFinished: その時刻か None}}"""
        out = {}
        with self._lock:
            jobs = list(self._jobs.values())
        for j in jobs:
            if not j["case"]:
                continue
            c = out.setdefault(j["case"], {"active": 0, "lastState": None, "lastFinished": None})
            if j["state"] in ACTIVE:
                c["active"] += 1
            elif (j["finishedAt"] or 0) >= (c["lastFinished"] or 0):
                c["lastState"], c["lastFinished"] = j["state"], j["finishedAt"]
        return out

    def snapshot(self, case=None):
        """入口の GET /api/flow/status に足す物: 引く形の器を読み直してから {rev, jobs(case で絞る), cases(絞らない)}"""
        self.refresh()
        jobs = self.list(case)
        return {"rev": self.rev, "jobs": jobs, "cases": self.cases()}

    # ------------------------------------------------------------ 取り消し・やり直し
    def _handler(self, jid, what):
        prefix, inner = split_id(jid)
        self.refresh(prefix)
        job = self.get(jid)
        if job is None:
            raise NotFound("そのジョブはありません: %s" % jid)
        with self._lock:
            fn = (self._handlers.get(prefix) or {}).get(what)
        return prefix, inner, job, fn

    def cancel(self, jid):
        """id のジョブを止める(器の cancel へ振り分ける)。-> 止めたあとの Job。無い id は NotFound・canCancel が偽・器に cancel が無いは Refused"""
        prefix, inner, job, fn = self._handler(jid, "cancel")
        if not job["canCancel"] or fn is None:
            raise Refused("cannot_cancel", "このジョブは今は止められません(%s)" % job["stateLabel"])
        try:
            got = fn(inner)
        except LookupError as e:
            raise NotFound(str(e) or "そのジョブはありません")
        except ValueError as e:
            raise Refused("cannot_cancel", str(e))
        if isinstance(got, dict):
            self.upsert(got)
        self.refresh(prefix)
        return self.get(jid) or job

    def retry(self, jid):
        """id のジョブを同じ指定で入れ直す(器の retry へ)。-> 新しい Job。無い id は NotFound・canRetry が偽・器に retry が無いは Refused"""
        prefix, inner, job, fn = self._handler(jid, "retry")
        if not job["canRetry"] or fn is None:
            raise Refused("cannot_retry", "このジョブは今はやり直せません(%s)" % job["stateLabel"])
        try:
            got = fn(inner)
        except LookupError as e:
            raise NotFound(str(e) or "そのジョブはありません")
        except ValueError as e:
            raise Refused("cannot_retry", str(e))
        if not isinstance(got, dict):
            raise Refused("cannot_retry", "やり直したジョブが分かりません")
        new = self.upsert(got)
        self.refresh(prefix)
        return self.get(new["id"]) or new


_default = None
_default_lock = threading.Lock()


def default():
    """プロセスに 1 つの掲示板(入口と、器を包む所が同じ物を使う)"""
    global _default
    with _default_lock:
        if _default is None:
            _default = Board()
        return _default


def guess_case(job):
    """入口が set_case_hook に渡す既定: Job の target -> 案件の根か None(引けた物だけ。作らない)。
    path = 動画のあるフォルダ(作業用/ の中なら 1 つ上。flow/placement.case_root)・docId = 文書の索引の 作業用 の 1 つ上(ytt/docloc.placed)・
    videoId = 書き出した切り抜きか書き出し先の題のフォルダ(placement.case_root)。ファイルを読むので、掲示板が CASE_RETRY_SEC ごとにだけ呼ぶ"""
    from ytt import docloc
    from . import placement
    t = job.get("target") or {}
    if t.get("path"):
        root = placement.case_root({"kind": "file", "path": t["path"]})
        if root:
            return root
    if t.get("docId"):
        try:
            wd = docloc.placed(t["docId"])
        except ValueError:
            wd = None
        if wd:
            return os.path.dirname(wd)
    if t.get("videoId"):
        return placement.case_root({"kind": "video", "videoId": t["videoId"], "clips": [t["path"]] if t.get("path") else []})
    return None
