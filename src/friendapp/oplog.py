# -*- coding: utf-8 -*-
"""友人のアプリの操作の記録(形の正は notes:plan/友人の不具合の自動対応-1025.md の「操作の記録」)。

- 置き場所: 作業データの diag/ops/YYYY-MM-DD.jsonl(1 日 1 ファイル・1 行 1 件 {at, kind, target, detail})。3 日で消す(friendapp/tidy.prune_old_files)
- kind: nav・click・setting・error は画面(ui/oplog.js)から POST /api/friend/ops でまとめて届く。request・cancel・job_start・job_end は玄関が書く
- target は画面の名前かボタンの id・data 属性(形を TARGET_RE で決める = 画面の文の中身は入らない)
- 書かない物: ログイン・cookie・キー・パスワードの値・入力欄の文の中身(長さ len だけ)。値は SAFE_VALUE の形の短い物か数・真偽だけ
- 直前 OPS_WINDOW 秒の分はメモリにも持つ(状態の書き出しの ops・困っている合図の判定)。書けなくても呼んだ側は止めない
"""
import collections
import json
import os
import re
import threading
import time

from ytt import fsio as _fsio

OPS_DIR = os.path.join("diag", "ops")
UI_KINDS = ("nav", "click", "setting", "error")
APP_KINDS = ("request", "cancel", "job_start", "job_end", "job_retry")   # job_retry = 止まった録画のやり直し(玄関の更新の見回り)
TARGET_RE = re.compile(r"^[#\[\]A-Za-z0-9_.:=>/\- ]{1,100}$")
SAFE_VALUE = re.compile(r"^[0-9A-Za-z_.:\-]{1,40}$")
SECRET_RE = re.compile(r"(?i)key|token|pass|cookie|secret|login|logout|auth")
OPS_WINDOW = 1800                  # 状態の書き出しに入れる直前の秒(30 分)
MEMORY_MAX = 2000                  # メモリに持つ件数の上限
BATCH_MAX = 100                    # 画面から 1 回に受ける件数
FILE_MAX = 4 * 1024 * 1024         # 1 日のファイルの上限(超えたら .1 へ回す)
MESSAGE_MAX = 200


def day_name(t):
    return time.strftime("%Y-%m-%d", time.localtime(t)) + ".jsonl"


def _value(v):
    """設定の値として残してよい物(数・真偽・短い記号の文字)か None"""
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str) and SAFE_VALUE.match(v):
        return v
    return None


def clean_ui(item, mask=None):
    """画面から来た 1 件 -> {kind, target, detail} か None(形が違う)。値と文は決まった形だけ残す"""
    if not isinstance(item, dict) or item.get("kind") not in UI_KINDS:
        return None
    target = item.get("target")
    if not isinstance(target, str) or not TARGET_RE.match(target):
        return None
    raw = item.get("detail") if isinstance(item.get("detail"), dict) else {}
    secret = bool(SECRET_RE.search(target))
    detail = {}
    kind = item["kind"]
    if kind == "setting":
        if secret or raw.get("secret"):
            detail["secret"] = True
        elif "len" not in raw:   # 文の欄は長さだけ
            for k in ("before", "after"):
                if k in raw:
                    v = _value(raw.get(k))
                    if v is not None or raw.get(k) is None:
                        detail[k] = v
        if isinstance(raw.get("len"), int) and not isinstance(raw.get("len"), bool):
            detail["len"] = max(0, min(raw["len"], 100000))
    elif kind == "nav":
        f = raw.get("from")
        if isinstance(f, str) and TARGET_RE.match(f):
            detail["from"] = f
    elif kind == "error":
        msg = raw.get("message")
        if isinstance(msg, str) and msg:
            msg = msg[:MESSAGE_MAX]
            detail["message"] = mask(msg) if mask else msg
        n = raw.get("noResponseSec")
        if isinstance(n, int) and not isinstance(n, bool) and 0 < n < 3600:
            detail["noResponseSec"] = n
        api = raw.get("api")
        if isinstance(api, str) and TARGET_RE.match(api):
            detail["api"] = api
    if kind in ("click", "nav", "setting"):
        view = raw.get("view")
        if isinstance(view, str) and TARGET_RE.match(view):
            detail["view"] = view
    return {"kind": kind, "target": target, "detail": detail}


class OpLog:
    """操作の記録の係(玄関に 1 つ)。root = 作業データの根"""

    def __init__(self, root, clock=time.time, log=None):
        self.dir = os.path.join(root, OPS_DIR)
        self.clock = clock
        self.log = log or (lambda msg: None)
        self._lock = threading.Lock()
        self._recent = collections.deque(maxlen=MEMORY_MAX)
        self._warned = False

    def add(self, kind, target, detail=None, at=None):
        """1 件書く -> 書いた行の dict。target は記号の形に切る"""
        t = self.clock() if at is None else at / 1000.0
        target = str(target or "")[:100]
        if not TARGET_RE.match(target):
            target = "?"
        row = {"at": int(t * 1000), "kind": kind, "target": target, "detail": detail or {}}
        line = json.dumps(row, ensure_ascii=False) + "\n"
        with self._lock:
            self._recent.append(row)
            try:
                _fsio.append_line(os.path.join(self.dir, day_name(t)), line, FILE_MAX)
            except OSError as e:
                if not self._warned:   # 書けない状態が続いても 1 回だけ記録
                    self._warned = True
                    self.log("操作の記録を書けませんでした: %s" % e.__class__.__name__)
        return row

    def add_ui(self, items, mask=None):
        """画面から届いた分 -> 書いた行のリスト(形の違う物は捨てる)。時刻は画面の時刻を今より先にしない"""
        out = []
        now = int(self.clock() * 1000)
        for it in (items if isinstance(items, list) else [])[:BATCH_MAX]:
            c = clean_ui(it, mask)
            if c is None:
                continue
            at = it.get("at")
            at = at if isinstance(at, int) and not isinstance(at, bool) and now - OPS_WINDOW * 1000 < at <= now else now
            out.append(self.add(c["kind"], c["target"], c["detail"], at=at))
        return out

    def recent(self, sec=OPS_WINDOW):
        since = int((self.clock() - sec) * 1000)
        with self._lock:
            return [dict(r) for r in self._recent if r["at"] >= since]
