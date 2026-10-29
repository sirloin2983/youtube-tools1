# -*- coding: utf-8 -*-
"""人の判断の記録(judgments.jsonl。MARKS-3 の S1a)。人か友人が切り抜きを判断したときだけ 1 行足す。評価と学習が読む人の判断はここだけ。
1 行 = だれが(self / friend)・どの切り抜き(videoId・markId)・何を(what)・いつ(at ms)・出どころの記録を指す key。パス・点数・解析の信号は入れない。
機械の採用・書き出しなどの起きた事実は ② が、片付けは ④ が持つ(ここには書かない)。置き場所 = 作業データの app/judgments.jsonl(呼ぶ側が app_dir を渡す)。
大きくなったら judgments.jsonl.old の末尾へ足して空にする(fsio.append_line の keep_old。消さない)。ytt だけを読む(③ の中の他の部品は読まない)。

レーン = 採否(who self の adopt・reject)・品質(quality_good・quality_bad・quality_unknown)・友人(who friend の good・bad・unknown と
古い adopt・reject・made_video)。各レーンは時刻順で最後の行が勝つ。retract は of の行を取り消す(その行がレーンの最後のときだけレーンを空に戻す)。
友人の 3 つの物差し(F3-6・notes:plan/done/f1-friend-requirements.md の C-4-1): good = 受け取る / bad = 届かなくてよかった(reason boring・cut)/
unknown = 見送る・3 日の自動(by auto)。古い行は書き換えずに読み替える(friend_value: adopt・made_video = good・reject = unknown)。
reason の札の鍵が AUTO_REASONS・FRIEND_REASONS のどれかは書き手(human/check/value・human/friend/returns)が確かめる(ここは空でない文字列だけ見る)。
"""
import json
import os
import secrets
import threading
import time

from ytt import fsio as _fsio, schemas as _schemas

VERSION = 1
FILE = "judgments.jsonl"
MAX_BYTES = 32 * 1024 * 1024   # 1 行 300 バイト前後。超えたら .old の末尾へ移す(消さない)

WHATS = ("adopt", "reject", "quality_good", "quality_bad", "quality_unknown", "made_video", "good", "bad", "unknown", "retract", "hold", "unhold")
WHOS = ("self", "friend")
ORIGINS = ("request", "auto", "manual", "live")
VIAS = ("review", "cases", "check", "friend_file", "friend_verdict", "migrate")   # migrate = 10-12 の 1 回の写しの行(写しの道具は 10-19 に消した・行は残る)
LANES = ("adopt", "quality", "friend")
REF_KEYS = ("zip", "pack", "requestId", "runId", "recorder", "recording")
_SELF_WHATS = {"adopt": "adopt", "reject": "adopt", "quality_good": "quality", "quality_bad": "quality", "quality_unknown": "quality"}
_FRIEND_WHATS = ("good", "bad", "unknown", "adopt", "reject", "made_video", "hold", "unhold")
NO_LANE = ("hold", "unhold")   # 友人の迷っている物の印を付けた・外した(10-29)。判定ではない = どのレーンにも入れない(fold は畳まない・friend_value は None)
_REASON_WHATS = ("quality_bad", "bad")
FRIEND_REASONS = {"boring": "つまらない", "cut": "切り方が変"}   # 友人の「届かなくてよかった」の理由(boring = 場面の選び方・cut = 区間の決め方)
_FRIEND_VALUE = {"good": "good", "bad": "bad", "unknown": "unknown", "adopt": "good", "made_video": "good", "reject": "unknown"}   # 古い行の読み替え(C-4-1)


def friend_value(row):
    """友人の行 -> good・bad・unknown(古い adopt・made_video は good・reject = 前のアプリの「要らない」は unknown)。友人の行でなければ None"""
    if not isinstance(row, dict) or row.get("who") != "friend":
        return None
    return _FRIEND_VALUE.get(row.get("what"))

_lock = threading.Lock()


def path(app_dir):
    return os.path.join(app_dir, FILE)


def _str(row, name):
    v = row.get(name)
    if not isinstance(v, str) or not v:
        raise ValueError("%s は空でない文字列" % name)
    return v


def _num(row, name):
    v = row.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError("%s は数" % name)
    return v


def _check(row):
    """欄を検査して、書く形の新しい辞書を返す(知らない欄は捨てる。問題があれば ValueError)"""
    what = row.get("what")
    if what not in WHATS:
        raise ValueError("知らない what: %r" % (what,))
    who = row.get("who", "friend" if what == "made_video" else "self")
    if who not in WHOS:
        raise ValueError("知らない who: %r" % (who,))
    if what != "retract" and what not in (_SELF_WHATS if who == "self" else _FRIEND_WHATS):
        raise ValueError("who %s に使えない what: %s" % (who, what))
    if row.get("origin") not in ORIGINS:
        raise ValueError("知らない origin: %r" % (row.get("origin"),))
    if row.get("via") not in VIAS:
        raise ValueError("知らない via: %r" % (row.get("via"),))
    at = row.get("at")
    at = int(time.time() * 1000) if at is None else int(_num(row, "at"))
    ref = row.get("ref")
    if ref is not None and not isinstance(ref, dict):
        raise ValueError("ref は辞書")
    if ref and isinstance(ref.get("pack"), str) and ref.get("pack") and row.get("videoId") == "" and row.get("markId") == "":
        vid, mid = "", ""   # マークの分からない古い届けた記録への友人の返事 = パック名(ref.pack)だけで残す(数えるときはパック名で突き合わせる)
    else:
        vid, mid = _str(row, "videoId"), _str(row, "markId")
    out = {"v": VERSION, "id": row.get("id") or "j%013d-%s" % (at, secrets.token_hex(3)), "at": at, "who": who,
           "videoId": vid, "markId": mid, "what": what}
    if row.get("reason") is not None:
        if what not in _REASON_WHATS:
            raise ValueError("reason は quality_bad・bad だけ")
        out["reason"] = _str(row, "reason")
    if row.get("by") is not None:
        if row.get("by") != "auto":
            raise ValueError("by は auto だけ")
        out["by"] = "auto"   # 人が押したのではなく自動で決まった(友人のアプリの 3 日の見送り)
    if what == "retract":
        out["of"] = _str(row, "of")
    elif row.get("of") is not None:
        raise ValueError("of は retract だけ")
    out["origin"], out["via"] = row["origin"], row["via"]
    for k in ("start", "end"):
        if row.get(k) is not None:
            out[k] = _num(row, k)
    if "score" in row:   # 友人の 5 段階の点(1〜5 か None = 選ばなかった。10-27)
        sc = row["score"]
        if sc is not None and (isinstance(sc, bool) or sc not in (1, 2, 3, 4, 5)):
            raise ValueError("score は 1〜5 か None")
        out["score"] = sc
    src = _schemas.verdict_source({k: row[k] for k in ("cand", "tool") if row.get(k) is not None})   # 友人の PC で処理したパックの候補の印・版と設定(10-27)
    out.update(src)
    out["key"] = _str(row, "key")
    if ref is not None:
        r = {k: ref[k] for k in REF_KEYS if ref.get(k) not in (None, "")}
        if r:
            out["ref"] = r
    return out


def record(app_dir, **row):
    """1 行を検査して足し、書いた行を返す。知らない what・欄の不正は ValueError、書けなければ OSError。
    id・at は省けば付く。who は省けば self(made_video は friend)"""
    out = _check(row)
    line = json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n"
    with _lock:
        _fsio.append_line(path(app_dir), line, MAX_BYTES, keep_old=True)
    return out


def retract(app_dir, hit, who, via, key=None, at=None):
    """行 hit(rows の形。id・videoId・markId・origin・key?・ref?)を取り消す 1 行を足す(取り消しの 1 つの口: スタジオ・確かめるの Z・友人の戻す)。
    key は省けば hit の key(無ければ id)+ ":retract"。同じ key の行がもうあれば書かない(やり直しで二重にしない)-> 書いた行か None"""
    key = key or (hit.get("key") or hit["id"]) + ":retract"
    if key in keys(app_dir):
        return None
    return record(app_dir, who=who, what="retract", of=hit["id"], origin=hit.get("origin"), via=via,
                  videoId=hit["videoId"], markId=hit["markId"], at=at, key=key, ref=hit.get("ref"))


def _read(p):
    try:
        with open(p, "rb") as f:
            data = f.read()
    except OSError:
        return []
    out = []
    for raw in data.split(b"\n"):
        raw = raw.strip()
        if not raw:
            continue
        try:
            r = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue   # 壊れた行(書きかけ)は飛ばす
        if (isinstance(r, dict) and r.get("what") in WHATS and r.get("who") in WHOS and isinstance(r.get("at"), (int, float))
                and isinstance(r.get("id"), str) and isinstance(r.get("videoId"), str) and isinstance(r.get("markId"), str)):
            out.append(r)
    return out


def rows(app_dir):
    """全部の行を古い順(at。同じ時刻は書いた順)で返す。.old → 本体の順に読む・壊れた行は飛ばす・同じ key は最初の 1 つだけ"""
    p = path(app_dir)
    seen, out = set(), []
    for r in _read(p + ".old") + _read(p):
        k = r.get("key")
        if isinstance(k, str) and k:
            if k in seen:
                continue
            seen.add(k)
        out.append(r)
    out.sort(key=lambda r: r["at"])   # sort は安定 = 同じ時刻は書いた順
    return out


def keys(app_dir):
    """書いてある key の集合(取り消しの重複よけ用)"""
    return {r["key"] for r in rows(app_dir) if isinstance(r.get("key"), str)}


def _lane(r):
    if r["what"] in NO_LANE:
        return None
    if r["who"] == "friend":
        return "friend"
    return _SELF_WHATS.get(r["what"])


def fold(rows_):
    """行(rows の形)→ {(videoId, markId): {"adopt": 行 or None, "quality": 行 or None, "friend": 行 or None}}。
    時刻順で最後が勝つ。retract は of の行がレーンの最後のときだけそのレーンを空に戻す(古い行の取り消しで新しい判断を消さない)"""
    ordered = sorted(rows_, key=lambda r: r["at"])
    byid = {r["id"]: r for r in ordered if r["what"] != "retract"}
    out = {}
    for r in ordered:
        if not r["markId"] or r["what"] in NO_LANE:
            continue   # マークの分からない行(パック名だけ)は切り抜きごとに畳まない = 物差しがパック名で突き合わせる。迷っている印はレーンの外
        slot = out.setdefault((r["videoId"], r["markId"]), {"adopt": None, "quality": None, "friend": None})
        if r["what"] == "retract":
            t = byid.get(r.get("of"))
            if t is None:
                continue
            tslot = out.get((t["videoId"], t["markId"]))
            lane = _lane(t)
            if tslot is not None and lane and tslot[lane] is not None and tslot[lane]["id"] == t["id"]:
                tslot[lane] = None
            continue
        lane = _lane(r)
        if lane:
            slot[lane] = r
    return out
