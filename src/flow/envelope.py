# -*- coding: utf-8 -*-
"""② 管理の層 flow: 依頼の封筒(役割で組み直す RS7-1 S3。2026-10-10。決定 3-30・notes:plan/f1-friend-pc.md の決めたこと 9・
資料の git:cbe1a64:docs/design/surveys/rs7-survey-2026-10-10/plan_order_v2.md の S3)。

依頼 = **封筒**(処理の中身でない物 = 何を入れたか・どの依頼か・届け方・メモ)+ **束**(何を作るか = flow/spec.py)。
② の段は束だけを読み、封筒は記録と届け方(③ の hook)に使う。ここは封筒の形と検査だけ(純粋。ファイル・ネットワークを読まない)。

形(版 2 = RV A2。check が整えて返す。無い項目は既定):
  {"id": 依頼の 1 件の id(英数字と - _ の 64 字まで。10 桁の 16 進なら実行の id にもなる),
   "kind": "url" | "file" | "docs" | "live",
   "input": kind ごとの入力(INPUT_KEYS。url = {videoId か url, title, duration, fresh, marks}・file = {path, title, normalize}・docs = {docId, title}・
            live = {videoId か url, title, recorder}(recorder = 録画の部品の名前。無ければ既定。Queue.submit が live の hook へ回す = RS7-2 G2a)。
            file の normalize = 最初の段で写しを 30fps に置き換える(真偽。既定 false。置き換えは元を消すので、作業データへの写しだけ),
   "requestId": 友人の依頼の id か None,
   "deliver": {"dir", "batch", "pool", "origin", "tag"}(届け先・n 本の組(F3-6 から読まない = 古い依頼のために欄だけ)・ライブの組の溜め・出どころ request|auto|manual・届ける名前の頭。
              どれも None = 届けない・既定・自動で決める),
   "note": メモ, "createdAt": 受けた時刻(ミリ秒), "specVersion": 封筒と束の形の版}
段の並び(どこから・どこまで)・1 本が失敗したとき・字幕の色の配信者は束(run.from・run.upto・run.onFail・hints.streamer)。
版 1(0.87 まで)は一時の欄 legacy {"mode", "onFail", "streamer"} を持っていた。check は版 1 も版 2 も受け、版 1 のまま返す。
upgrade(封筒, 束) が版 1 を版 2 に読み替える(legacy を束へ写す)。書くのは版 2 だけ(作業データの記録は書き換えない = 読むときに読み替える)。
知らない項目・知らない版・形の違う値は理由つきの ValueError(受け口では HTTP の 400 にする)。

import してよいのは標準ライブラリ・ytt・同じ flow の spec だけ(run.py が読むので run を読まない)。
"""
import copy
import re
import time

from ytt import yturl as _yturl
from . import spec as _spec

SPEC_VERSION = 2   # 書く封筒と束の形の版(flow/spec.py の DEFAULTS の形。形を変えたら上げる。2 = RV A2)
ACCEPTED = (1, 2)  # 読める版(1 = legacy つき。upgrade で 2 に読み替える。知らない版は断る)
KINDS = ("url", "file", "docs", "live")
KEYS = {1: ("id", "kind", "input", "requestId", "deliver", "note", "createdAt", "specVersion", "legacy"),
        2: ("id", "kind", "input", "requestId", "deliver", "note", "createdAt", "specVersion")}
INPUT_KEYS = {"url": ("videoId", "url", "title", "duration", "fresh", "marks"), "live": ("videoId", "url", "title", "recorder"),
              "file": ("path", "title", "normalize"), "docs": ("docId", "title")}
DELIVER_KEYS = ("dir", "batch", "pool", "origin", "tag")
DELIVER_ORIGINS = ("request", "auto", "manual")   # 届けるときの出どころ(flow/sendpolicy.ORIGINS と同じ。D-SEND。envelope は sendpolicy を読まない)
LEGACY_KEYS = ("mode", "onFail", "streamer")      # 版 1 の一時の欄
ON_FAIL = _spec.ON_FAIL
# 版 1 の legacy.mode(段の並びの形)-> (kind, 束の run.from, 束の run.upto)。upgrade の読み替えと、派生の mode(flow/run.py の mode_of)の表
LEGACY_MODES = {"full": ("url", None, "pack"), "adopted": ("url", "export", "pack"), "transcribe": ("url", "export", "transcribe"),
                "request": ("url", None, "transcribe"), "request_auto": ("url", None, "pack"), "doc": ("docs", None, "pack"),
                "file": ("file", None, "transcribe"), "file_auto": ("file", None, "pack")}
KIND_DEFAULT_MODE = {"url": "full", "docs": "doc", "file": "file_auto"}   # 版 1 の封筒に legacy.mode が無いとき
ID_RE = re.compile(r"[0-9A-Za-z_-]{1,64}\Z")
VIDEO_ID_RE = re.compile(r"[0-9A-Za-z_-]{1,64}\Z")
DOC_ID_RE = re.compile(r"[0-9A-Za-z_-]{1,40}\Z")
TITLE_MAX, CHANNEL_MAX, PATH_MAX, NOTE_MAX, TAG_MAX = 120, 100, 1000, 1000, 120
BATCH_RANGE = (1, 10)   # 友人の依頼ごとの届け方(n 本の組。F3-6 から届ける段は読まない = 古いアプリの依頼を断らないために検査だけ残す)


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


def _input(kind, inp, ver):
    where = "封筒.input"
    allowed = INPUT_KEYS[kind] if ver >= 2 else tuple(k for k in INPUT_KEYS[kind] if k != "normalize")
    _keys_known(inp, allowed, where)
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
        if ver >= 2:
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


def _deliver(d, ver):
    where = "封筒.deliver"
    d = {} if d is None else d
    _keys_known(d, DELIVER_KEYS if ver >= 2 else DELIVER_KEYS[:-1], where)
    batch = d.get("batch")
    if batch is not None and not batch_ok(batch):
        raise ValueError("%s.batch は %d〜%d の整数にしてください" % ((where,) + BATCH_RANGE))
    pool = d.get("pool")
    if pool is not None:
        pool = clean_pool(pool)
        if pool is None:
            raise ValueError("%s.pool は {key, rid?, title?, meta?} の形にしてください" % where)
    origin = d.get("origin")
    if origin is not None and origin not in DELIVER_ORIGINS:
        raise ValueError("%s.origin は %s のどれかにしてください" % (where, "・".join(DELIVER_ORIGINS)))
    out = {"dir": _str(d.get("dir"), PATH_MAX, where + ".dir", empty=False), "batch": batch, "pool": pool, "origin": origin}
    if ver >= 2:
        out["tag"] = _str(d.get("tag"), TAG_MAX, where + ".tag", empty=False)
    return out


def _legacy(d):
    where = "封筒.legacy"
    d = {} if d is None else d
    _keys_known(d, LEGACY_KEYS, where)
    on_fail = d.get("onFail")
    if on_fail is not None and on_fail not in ON_FAIL:
        raise ValueError("%s.onFail は %s のどれかにしてください" % (where, "・".join(ON_FAIL)))
    return {"mode": _str(d.get("mode"), 20, where + ".mode", empty=False), "onFail": on_fail,
            "streamer": _str(d.get("streamer"), TITLE_MAX, where + ".streamer")}


LEGACY_DEFAULT = 1   # specVersion の無い封筒の版(0.87 までの送るアプリ・記録は書いていなかった = 版 1。今の書き手は必ず書く)


def version_of(env):
    """封筒の版(specVersion。無ければ版 1 = LEGACY_DEFAULT)。読めない版は ValueError(呼ぶ側は版の違いとして断る)"""
    ver = env.get("specVersion", LEGACY_DEFAULT) if isinstance(env, dict) else LEGACY_DEFAULT
    if isinstance(ver, bool) or ver not in ACCEPTED:
        raise ValueError("知らない束の版です: %r(この ② は %s。送る側か ② を新しくしてください)" % (ver, "・".join(map(str, ACCEPTED))))
    return ver


def check(env, now=None):
    """封筒を確かめて整えた新しい dict を返す(無い項目は既定。createdAt が無ければ now(秒。None = 今))。合わなければ理由つきの ValueError。
    版 1 は版 1 の形(legacy つき)・版 2 は版 2 の形のまま返す(版 2 にするのは upgrade)"""
    if not isinstance(env, dict):
        raise ValueError("封筒 は {項目: 値} の形にしてください")
    ver = version_of(env)
    _keys_known(env, KEYS[ver], "封筒")
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
    out = {"id": eid, "kind": kind, "input": _input(kind, env.get("input"), ver), "requestId": rid, "deliver": _deliver(env.get("deliver"), ver),
           "note": _str(env.get("note"), NOTE_MAX, "封筒.note") or "", "createdAt": at, "specVersion": ver}
    if ver == 1:
        out["legacy"] = _legacy(env.get("legacy"))
    return out


def upgrade(env, spec=None):
    """確かめた封筒(check の結果)+ 束(変えたい所だけでもよい)-> (版 2 の封筒, 束)。版 2 はそのまま(写しを返す)。
    版 1 は legacy を束へ写す: mode → run.from・run.upto(LEGACY_MODES。from は書き出しからの形だけ書く = 束の run.from(CLI の --from pack など)を消さない)・
    onFail → run.onFail・streamer → hints.streamer(null = 決めていない = 書かない)。file の input.normalize は false・deliver.tag は null。
    mode が kind に合わなければ理由つきの ValueError。束が辞書でなければそのまま返す(検査は spec.merge)"""
    env = copy.deepcopy(env)
    spec = copy.deepcopy(spec) if spec is not None else {}
    if env.get("specVersion") != 1:
        return env, spec
    lg = env.pop("legacy", None) or {}
    kind = env["kind"]
    if kind == "file":
        env["input"]["normalize"] = False
    env["deliver"]["tag"] = None
    env["specVersion"] = 2
    if kind == "live":
        mode = None
    else:
        mode = lg.get("mode") or KIND_DEFAULT_MODE[kind]
        if LEGACY_MODES.get(mode, (None,))[0] != kind:
            raise ValueError("封筒.legacy.mode は %s のどれかにしてください" % "・".join(m for m, v in LEGACY_MODES.items() if v[0] == kind))
    if not isinstance(spec, dict):
        return env, spec
    run = spec.get("run") if isinstance(spec.get("run"), dict) else None
    if mode is not None:
        _kind, frm, upto = LEGACY_MODES[mode]
        run = dict(run or {}, upto=upto)
        if frm is not None:
            run["from"] = frm
    if lg.get("onFail") is not None:
        run = dict(run or {}, onFail=lg["onFail"])
    if run is not None:
        spec["run"] = run
    if lg.get("streamer") is not None:
        hints = spec.get("hints") if isinstance(spec.get("hints"), dict) else {}
        spec["hints"] = dict(hints, streamer=lg["streamer"])
    return env, spec


def read(env, spec=None, now=None):
    """check + upgrade -> (版 2 の封筒, 束)。受け口・待ちの記録・録画の束の読み手が使う"""
    return upgrade(check(env, now), spec)
