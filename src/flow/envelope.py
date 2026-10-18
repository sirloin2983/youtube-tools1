# -*- coding: utf-8 -*-
"""② 管理の層 flow: 依頼の封筒(役割で組み直す RS7-1 S3。2026-10-10。決定 3-30・notes:plan/f1-friend-pc.md の決めたこと 9・
資料の git:cbe1a64:docs/design/surveys/rs7-survey-2026-10-10/plan_order_v2.md の S3)。

依頼 = **封筒**(処理の中身でない物 = 何を入れたか・どの依頼か・届け先)+ **束**(何を作るか = flow/spec.py)。
② の段は束だけを読み、封筒は記録と届け先(③ の hook)に使う。ここは封筒の形と検査だけ(純粋。ファイル・ネットワークを読まない)。

形(版 2。check が整えて返す。無い項目は既定):
  {"id": 依頼の 1 件の id(英数字と - _ の 64 字まで。10 桁の 16 進なら実行の id にもなる),
   "kind": "url" | "file" | "docs" | "live",
   "input": kind ごとの入力(INPUT_KEYS。url = {videoId か url, title, duration, fresh, marks}・file = {path, title, normalize}・docs = {docId, title}・
            live = {videoId か url, title, recorder}(recorder = 録画の部品の名前。無ければ既定。Queue.submit が live の hook へ回す = RS7-2 G2a)。
            file の normalize = 最初の段で写しを 30fps に置き換える(真偽。既定 false。置き換えは元を消すので、作業データへの写しだけ),
   "requestId": 友人の依頼の id か None,
   "deliver": {"dir", "pool", "origin", "tag"}(届け先・ライブの切り抜きの溜め・出どころ request|auto|manual・届ける名前の頭。
              どれも None = 届けない・既定・自動で決める),
   "createdAt": 受けた時刻(ミリ秒), "specVersion": 封筒と束の形の版}
段の並び(どこから・どこまで)・1 本が失敗したとき・字幕の色の配信者は束(run.from・run.upto・run.onFail・hints.streamer)。
知らない項目・知らない版・形の違う値は理由つきの ValueError(受け口では HTTP の 400 にする)。

import してよいのは標準ライブラリ・ytt・同じ flow の spec だけ(run.py が読むので run を読まない)。
"""
import copy
import re
import time

from ytt import yturl as _yturl
from . import spec as _spec

SPEC_VERSION = 2   # 封筒と束の形の版(flow/spec.py の DEFAULTS の形。形を変えたら上げる。これ以外の版は断る)
KINDS = ("url", "file", "docs", "live")
KEYS = ("id", "kind", "input", "requestId", "deliver", "createdAt", "specVersion")
INPUT_KEYS = {"url": ("videoId", "url", "title", "duration", "fresh", "marks"), "live": ("videoId", "url", "title", "recorder"),
              "file": ("path", "title", "normalize"), "docs": ("docId", "title")}
DELIVER_KEYS = ("dir", "pool", "origin", "tag")
# 10-25 以降に消す(保存済みの封筒は待ちの列 3 日・録画の束 7 日で入れ替わる): 前に書いていた鍵。読んで捨てる(断らない・出力に入れない)
DROPPED_KEYS, DROPPED_DELIVER_KEYS = ("note",), ("batch",)
DELIVER_ORIGINS = ("request", "auto", "manual")   # 届けるときの出どころ(flow/sendpolicy.ORIGINS と同じ。D-SEND。envelope は sendpolicy を読まない)
ID_RE = re.compile(r"[0-9A-Za-z_-]{1,64}\Z")
VIDEO_ID_RE = re.compile(r"[0-9A-Za-z_-]{1,64}\Z")
DOC_ID_RE = re.compile(r"[0-9A-Za-z_-]{1,40}\Z")
TITLE_MAX, CHANNEL_MAX, PATH_MAX, TAG_MAX = 120, 100, 1000, 120


def clean_pool(p):
    """ライブの切り抜きの溜めの指定 {key, rid, title, meta: {recorder, recording, phase}} を検査した形か None(live_export._handoff が作る)"""
    if not isinstance(p, dict) or not isinstance(p.get("key"), str) or not 0 < len(p["key"]) <= 200:
        return None
    meta = p.get("meta") if isinstance(p.get("meta"), dict) else {}
    return {"key": p["key"], "rid": str(p.get("rid") or "")[:120], "title": str(p.get("title") or "")[:120],
            "meta": {k: str(meta[k])[:120] for k in ("recorder", "recording", "phase") if isinstance(meta.get(k), str)}}


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
    if kind == "live":
        out["recorder"] = _str(inp.get("recorder"), CHANNEL_MAX, where + ".recorder", empty=False)
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
        norm = inp.get("normalize")
        if norm is not None and not isinstance(norm, bool):
            raise ValueError("%s.normalize は true か false にしてください" % where)
        out["normalize"] = norm is True
    elif kind == "docs":
        tid = inp.get("docId")
        if not isinstance(tid, str) or not DOC_ID_RE.match(tid):
            raise ValueError("%s.docId(文書の id)がありません・形が違います" % where)
        out["docId"] = tid
    return out


def _deliver(d):
    where = "封筒.deliver"
    d = {} if d is None else d
    _keys_known(d, DELIVER_KEYS + DROPPED_DELIVER_KEYS, where)
    pool = d.get("pool")
    if pool is not None:
        pool = clean_pool(pool)
        if pool is None:
            raise ValueError("%s.pool は {key, rid?, title?, meta?} の形にしてください" % where)
    origin = d.get("origin")
    if origin is not None and origin not in DELIVER_ORIGINS:
        raise ValueError("%s.origin は %s のどれかにしてください" % (where, "・".join(DELIVER_ORIGINS)))
    return {"dir": _str(d.get("dir"), PATH_MAX, where + ".dir", empty=False), "pool": pool, "origin": origin,
            "tag": _str(d.get("tag"), TAG_MAX, where + ".tag", empty=False)}


def version_of(env):
    """封筒の版(specVersion。無ければ今の版)。SPEC_VERSION でなければ ValueError(呼ぶ側は版の違いとして断る)"""
    ver = env.get("specVersion", SPEC_VERSION) if isinstance(env, dict) else None
    if isinstance(ver, bool) or ver != SPEC_VERSION:
        raise ValueError("知らない束の版です: %r(この ② は %d。送る側か ② を新しくしてください)" % (ver, SPEC_VERSION))
    return ver


def check(env, now=None):
    """封筒を確かめて整えた新しい dict を返す(無い項目は既定。createdAt が無ければ now(秒。None = 今))。合わなければ理由つきの ValueError"""
    if not isinstance(env, dict):
        raise ValueError("封筒 は {項目: 値} の形にしてください")
    ver = version_of(env)
    _keys_known(env, KEYS + DROPPED_KEYS, "封筒")
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
            "createdAt": at, "specVersion": ver}


def read(env, spec=None, now=None):
    """check + 束の写し -> (封筒, 束)。受け口・待ちの記録・録画の束の読み手が使う(束が None なら {})"""
    return check(env, now), (copy.deepcopy(spec) if spec is not None else {})
