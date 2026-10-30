# -*- coding: utf-8 -*-
"""ホームの読み込みの記録(10-30。ユーザー「1 分以上かかってる」: 再現して測るのでなく、本当に開いた時の数を残して原因を見る)。

入口の側(api-timing.jsonl): 読む口・書く口のうち、SLOW_SEC 秒を超えた物と失敗(400 以上・例外)だけ 1 行。
  {t 受け取った時刻, m 方法, p 道(?の後は外す), sec 処理の秒, code 状態の番号, bytes 返した大きさ, inflight 同時に動いていた要求の数,
   waits {名前: 待った秒}(案件の一覧のロックなど), busy {runs まとめて実行の待ち・実行中, rec 録画中の本数}}
画面の側(ui-timing.jsonl): ホームと案件の画面が、中身が出た時(done)・失敗を出した時(failed)・SPAN_STUCK 秒たっても出ない時(stuck)に送る 1 行。
  {t, page, state, ms 開いてからの秒(ミリ秒), calls [[道, 始めたミリ秒, かかったミリ秒(-1 = まだ), 状態の番号か timeout・network・abort]], v 版}
どちらも作業データの logs に置き、MAX_BYTES を超えたら 1 世代だけ回す(fsio.append_line)。画面は POST /api/ui-timing(src/ui-kit/ui-kit.js の loadTiming)
"""
import json
import os
import re
import threading
import time

from ytt import fsio

SLOW_SEC = 0.5
MAX_BYTES = 2 * 1024 * 1024   # 1 本の上限(超えたら .1 へ回す = 遅い行だけなので数日〜数週間ぶん)
API_NAME = "api-timing.jsonl"
UI_NAME = "ui-timing.jsonl"
PAGES = ("home", "cases")
STATES = ("done", "failed", "stuck")
CALLS_MAX = 40
PATH_RE = re.compile(r"[^A-Za-z0-9/_.\-]")

_lock = threading.Lock()
_inflight = [0]


def begin():
    """要求を受け取った -> 受け取った時刻(time.time())。同時に動いている数を 1 足す"""
    with _lock:
        _inflight[0] += 1
    return time.time()


def end():
    """-> 終わる前に同時に動いていた数(この要求を含む)"""
    with _lock:
        n = _inflight[0]
        _inflight[0] = max(0, n - 1)
    return n


def clean_path(p):
    return PATH_RE.sub("", str(p or "").split("?", 1)[0])[:120]


def _write(logs_dir, name, row):
    try:
        fsio.append_line(os.path.join(logs_dir, name), json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n", MAX_BYTES)
    except OSError:
        pass   # 記録が書けなくても口は止めない


def api_record(logs_dir, t, method, path, sec, code, size, inflight, waits=None, busy=None):
    """遅い口・失敗した口だけ 1 行(それ以外は書かない)-> 書いたか"""
    if not (sec > SLOW_SEC or code is None or code >= 400):
        return False
    row = {"t": round(t, 3), "m": method, "p": clean_path(path), "sec": round(sec, 3), "code": code, "bytes": size, "inflight": inflight}
    if waits:
        row["waits"] = {k: round(v, 3) for k, v in waits.items()}
    if busy:
        row["busy"] = busy
    _write(logs_dir, API_NAME, row)
    return True


def _num(x, lo=0, hi=3600000):
    return int(min(hi, max(lo, x))) if isinstance(x, (int, float)) and not isinstance(x, bool) and x == x else None


def ui_record(logs_dir, body, version, now=None):
    """画面から届いた 1 行を確かめて書く -> 書いた行。形が違えば ValueError"""
    if not isinstance(body, dict) or body.get("page") not in PAGES or body.get("state") not in STATES:
        raise ValueError("page・state が違います")
    calls = []
    for c in (body.get("calls") if isinstance(body.get("calls"), list) else [])[:CALLS_MAX]:
        if not (isinstance(c, list) and len(c) == 4):
            continue
        code = c[3] if c[3] in ("timeout", "network", "abort", "") else _num(c[3], 0, 999)
        calls.append([clean_path(c[0]), _num(c[1]), _num(c[2], -1), code])
    row = {"t": round(now if now is not None else time.time(), 3), "page": body["page"], "state": body["state"], "ms": _num(body.get("ms")),
           "calls": calls, "v": str(version)[:20]}
    _write(logs_dir, UI_NAME, row)
    return row
