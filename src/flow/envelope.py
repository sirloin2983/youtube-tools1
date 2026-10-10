# -*- coding: utf-8 -*-
"""② 管理の層 flow: 依頼の封筒(役割で組み直す RS7-1 S3。2026-10-10。決定 3-30・plan/f1-friend-pc.md の決めたこと 9・
docs/design/rs7-survey-2026-10-10/plan_order_v2.md の S3)。

依頼 = **封筒**(処理の中身でない物 = 何を入れたか・どの依頼か・届け方・メモ)+ **束**(何を作るか = flow/spec.py)。
② の段は束だけを読み、封筒は記録と届け方(③ の hook)に使う。ここは封筒の形と検査だけ(純粋。ファイル・ネットワークを読まない)。

形(check が整えて返す。無い項目は既定):
  {"id": 依頼の 1 件の id(英数字と - _ の 64 字まで。10 桁の 16 進なら実行の id にもなる),
   "kind": "url" | "file" | "docs" | "live",
   "input": kind ごとの入力(INPUT_KEYS。url = {videoId か url, title, duration, fresh, marks}・file = {path, title}・docs = {docId, title}・
            live = {videoId か url, title}(ライブ係は RS7-2。今は形だけ)),
   "requestId": 友人の依頼の id か None, "deliver": {"dir", "batch", "pool"}(届け先・n 本の組・ライブの組の溜め。どれも None = 届けない・既定),
   "note": メモ, "createdAt": 受けた時刻(ミリ秒), "specVersion": 束の形の版(SPEC_VERSION),
   "legacy": {"mode", "onFail", "streamer"}(一時。今の Run の欄で、まだ束に写せない物 = 段の並びの形・1 本が失敗したとき・字幕の色の配信者。
             配信者は受付で決めた名前(RS7-1 S4。"" = 色なし・null = 決めていない)。null のとき ② の口 submit は束の hints.people の先頭を照らし合わせて
             配信者にする(flow/runqueue.py)。段の並びの形と onFail を束(run.from)か固定へ移すのは RS7-2 のあと)}
知らない項目・知らない版・形の違う値は理由つきの ValueError(受け口では HTTP の 400 にする)。

import してよいのは標準ライブラリ・ytt・同じ flow の spec だけ(run.py が読むので run を読まない)。
"""
import re
import time

from ytt import yturl as _yturl
from . import spec as _spec

SPEC_VERSION = 1   # 束の形の版(flow/spec.py の DEFAULTS の形。形を変えたら上げる。知らない版は断る)
KINDS = ("url", "file", "docs", "live")
KEYS = ("id", "kind", "input", "requestId", "deliver", "note", "createdAt", "specVersion", "legacy")
INPUT_KEYS = {"url": ("videoId", "url", "title", "duration", "fresh", "marks"), "live": ("videoId", "url", "title"),
              "file": ("path", "title"), "docs": ("docId", "title")}
DELIVER_KEYS = ("dir", "batch", "pool")
LEGACY_KEYS = ("mode", "onFail", "streamer")
ON_FAIL = ("next", "stop")
ID_RE = re.compile(r"[0-9A-Za-z_-]{1,64}\Z")
VIDEO_ID_RE = re.compile(r"[0-9A-Za-z_-]{1,64}\Z")
DOC_ID_RE = re.compile(r"[0-9A-Za-z_-]{1,40}\Z")
TITLE_MAX, CHANNEL_MAX, PATH_MAX, NOTE_MAX = 120, 100, 1000, 1000
BATCH_RANGE = (1, 10)   # 友人の依頼ごとの届け方(n 本の組。src/home/prefs.py の intake.deliverBatch の範囲と同じ)


def clean_pool(p):
    """組の溜めの指定 {key, rid, title, meta: {recorder, recording, phase}} を検査した形か None(live_export._handoff が作る。run.py から移した)"""
    if not isinstance(p, dict) or not isinstance(p.get("key"), str) or not 0 < len(p["key"]) <= 200:
        return None
    meta = p.get("meta") if isinstance(p.get("meta"), dict) else {}
    return {"key": p["key"], "rid": str(p.get("rid") or "")[:120], "title": str(p.get("title") or "")[:120],
            "meta": {k: str(meta[k])[:120] for k in ("recorder", "recording", "phase") if isinstance(meta.get(k), str)}}


def batch_ok(v):
    return isinstance(v, int) and not isinstance(v, bool) and BATCH_RANGE[0] <= v <= BATCH_RANGE[1]


def _keys_known(d, allowed, where):
    if not isinstance(d, dict):
        raise ValueError("%s は {項目: 値} の形にしてください" % where)
    for k in d:
        if k not in allowed:
            raise ValueError("知らない項目です: %s.%s(使えるのは %s)" % (where, k, "・".join(allowed)))


def _str(v, n, where, empty=True):
    if v is None:
        return None
    if not isinstance(v, str) or len(v) > n or (not empty and not v):
        raise ValueError("%s は %d 字までの文字にしてください" % (where, n))
    return v


def _video_id(inp, where):
    vid = inp.get("videoId")
    if vid is None and inp.get("url") is not None:
        vid = _yturl.parse_video_id(str(inp["url"]))
        if not vid:
            raise ValueError("%s.url は YouTube の動画の URL にしてください" % where)
    if not isinstance(vid, str) or not VIDEO_ID_RE.match(vid):
        raise ValueError("%s.videoId(か url)がありません・形が違います" % where)
    return vid


def _input(kind, inp):
    where = "封筒.input"
    _keys_known(inp, INPUT_KEYS[kind], where)
    out = {"title": (_str(inp.get("title"), TITLE_MAX, where + ".title") or "")}
    if kind in ("url", "live"):
        out["videoId"] = _video_id(inp, where)
        if inp.get("url") is not None:
            out["url"] = _str(inp["url"], PATH_MAX, where + ".url")
    if kind == "url":
        dur = inp.get("duration")
        if dur is not None and not (_spec.num_ok(dur) and dur > 0):
            raise ValueError("%s.duration は秒の数にしてください" % where)
        out["duration"] = dur
        fresh = inp.get("fresh")
        if fresh is not None:
            _keys_known(fresh, ("title", "channel"), where + ".fresh")
            fresh = {"title": _str(fresh.get("title"), TITLE_MAX, where + ".fresh.title") or "",
                     "channel": _str(fresh.get("channel"), CHANNEL_MAX, where + ".fresh.channel") or ""}
        out["fresh"] = fresh
        marks = _spec.marks_arg(inp.get("marks"))   # 形が違えば ValueError(このマークだけ)
        out["marks"] = list(marks) if marks else None
    elif kind == "file":
        out["path"] = _str(inp.get("path"), PATH_MAX, where + ".path", empty=False)
        if out["path"] is None:
            raise ValueError("%s.path(動画のパス)がありません" % where)
    elif kind == "docs":
        tid = inp.get("docId")
        if not isinstance(tid, str) or not DOC_ID_RE.match(tid):
            raise ValueError("%s.docId(文書の id)がありません・形が違います" % where)
        out["docId"] = tid
    return out


def _deliver(d):
    where = "封筒.deliver"
    d = {} if d is None else d
    _keys_known(d, DELIVER_KEYS, where)
    batch = d.get("batch")
    if batch is not None and not batch_ok(batch):
        raise ValueError("%s.batch は %d〜%d の整数にしてください" % ((where,) + BATCH_RANGE))
    pool = d.get("pool")
    if pool is not None:
        pool = clean_pool(pool)
        if pool is None:
            raise ValueError("%s.pool は {key, rid?, title?, meta?} の形にしてください" % where)
    return {"dir": _str(d.get("dir"), PATH_MAX, where + ".dir", empty=False), "batch": batch, "pool": pool}


def _legacy(d):
    where = "封筒.legacy"
    d = {} if d is None else d
    _keys_known(d, LEGACY_KEYS, where)
    on_fail = d.get("onFail")
    if on_fail is not None and on_fail not in ON_FAIL:
        raise ValueError("%s.onFail は %s のどれかにしてください" % (where, "・".join(ON_FAIL)))
    return {"mode": _str(d.get("mode"), 20, where + ".mode", empty=False), "onFail": on_fail,
            "streamer": _str(d.get("streamer"), TITLE_MAX, where + ".streamer")}


def check(env, now=None):
    """封筒を確かめて整えた新しい dict を返す(無い項目は既定。createdAt が無ければ now(秒。None = 今))。合わなければ理由つきの ValueError"""
    _keys_known(env, KEYS, "封筒")
    ver = env.get("specVersion", SPEC_VERSION)
    if ver != SPEC_VERSION or isinstance(ver, bool):
        raise ValueError("知らない束の版です: %r(この ② は %d。送る側か ② を新しくしてください)" % (ver, SPEC_VERSION))
    eid = env.get("id")
    if not isinstance(eid, str) or not ID_RE.match(eid):
        raise ValueError("封筒.id は英数字と - _ の 64 字までにしてください")
    kind = env.get("kind")
    if kind not in KINDS:
        raise ValueError("封筒.kind は %s のどれかにしてください" % "・".join(KINDS))
    rid = env.get("requestId")
    if rid is not None and (not isinstance(rid, str) or not 0 < len(rid) <= 120):
        raise ValueError("封筒.requestId は 120 字までの文字にしてください")
    at = env.get("createdAt")
    if at is None:
        at = int((time.time() if now is None else now) * 1000)
    elif not isinstance(at, int) or isinstance(at, bool) or at < 0:
        raise ValueError("封筒.createdAt はミリ秒の整数にしてください")
    return {"id": eid, "kind": kind, "input": _input(kind, env.get("input")), "requestId": rid, "deliver": _deliver(env.get("deliver")),
            "note": _str(env.get("note"), NOTE_MAX, "封筒.note") or "", "createdAt": at, "specVersion": SPEC_VERSION,
            "legacy": _legacy(env.get("legacy"))}
