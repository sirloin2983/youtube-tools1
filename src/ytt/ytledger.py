# -*- coding: utf-8 -*-
"""YouTube への問い合わせの帳簿(10-25 夜。ユーザー OK「取得の列の間隔を縮め、ほかの YouTube への問い合わせと調整する」)。

製品が YouTube に問い合わせるたびに 1 行(時刻・種類・重み・成否・当たりの種類・出どころ)を <データの根>\\app\\logs\\yt-ledger.jsonl に足す。
取得の列(app/check/ytqueue)はこれを読み、直近 WINDOW_SEC の重みの合計が上限を超えていれば音の回を延ばし(製品が先・列が譲る)、
ほかの誰かが当たれば(429・ボット確認)同じ休みに入る。KEEP_DAYS 日より古い行は prune で消す。キー・cookie・URL の値は書かない(種類と動画 id の有無だけ)。
重み: 動画の取得 1・字幕や情報 0.2(API・RSS・-j・--skip-download など)・録画中のライブ 1 本 0.5(始まりの行 live から終わりの行 live-end まで)。
書く口: ytt/tools.remember(tools.run・run_progress・procs を通る yt-dlp を自動で)と、別の道の 1 行(列の voicefetch._run・録画の streamlink・
ライブのチャット・ytapi・RSS)。YTT_DATA_DIR=inplace(テスト・見本)では書かない。書けなくても呼び手は止めない。
"""
import json
import os
import threading
import time

from . import datadir

NAME = "yt-ledger.jsonl"
WINDOW_SEC = 30 * 60
KEEP_DAYS = 3
LIVE_MAX_SEC = 12 * 3600          # 終わりの行が無いライブは、始まりからこの秒で数えない
W_FETCH, W_LIGHT, W_LIVE = 1.0, 0.2, 0.5
LIGHT_ARGS = ("--skip-download", "-j", "--dump-json", "-J", "--dump-single-json", "--simulate", "-s", "-g", "--get-url", "--print",
              "--flat-playlist", "--list-subs", "--write-auto-subs")
_lock = threading.Lock()


def path(env=None):
    """帳簿のパス(YTT_DATA_DIR=inplace = テスト・見本なら None)"""
    root = datadir.data_root(env)
    return os.path.join(root, "app", "logs", NAME) if root else None


def classify(text):
    """失敗の文 -> "rate"(429・速すぎ)| "bot"(ボット確認・ログインを求められた)| None"""
    e = str(text or "").lower()
    if "429" in e or "too many requests" in e:
        return "rate"
    if any(w in e for w in ("not a bot", "sign in to confirm", "login required", "confirm you")):
        return "bot"
    return None


def record(kind, weight, ok=True, err="", src="", now=None, p=None, **extra):
    """1 行足す。kind = 取得の種類(fetch・light・api・rss・live・live-end・chat など)。err は当たりの種類を見るだけ(文は書かない)。
    extra = 短い印(録画の id など。値は 40 字まで)"""
    p = p or path()
    if not p:
        return
    row = {"at": round(time.time() if now is None else now, 1), "kind": str(kind)[:20], "w": round(float(weight), 2), "ok": bool(ok),
           "src": str(src)[:20]}
    row.update({k: str(v)[:40] for k, v in extra.items()})
    hit = classify(err) if not ok else None
    if hit:
        row["hit"] = hit
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with _lock, open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


def ytdlp_weight(cmd):
    """yt-dlp の引数 -> 重み(動画の取得 1・情報や字幕だけ 0.2)か None(--version など問い合わせない物)"""
    args = [str(a) for a in cmd[1:]] if isinstance(cmd, (list, tuple)) else []
    if not args or any(a in ("--version", "-U", "--update", "--help") for a in args):
        return None
    return W_LIGHT if any(a in LIGHT_ARGS for a in args) else W_FETCH


def is_ytdlp(cmd):
    name = os.path.basename(str(cmd[0] if isinstance(cmd, (list, tuple)) and cmd else cmd or "")).lower()
    return name.startswith("yt-dlp") or name.startswith("yt_dlp")


def from_run(cmd, code, lines, why, src="tools"):
    """tools.remember から: yt-dlp なら 1 行(重みは引数から・成否・当たり)"""
    if not is_ytdlp(cmd):
        return
    w = ytdlp_weight(cmd)
    if w is None:
        return
    text = "\n".join((x.decode("utf-8", "replace") if isinstance(x, bytes) else str(x)) for x in list(lines or [])[-20:])
    record("fetch" if w >= W_FETCH else "light", w, ok=not code and not why, err=text, src=src)


def rows(since, p=None):
    """since(秒)より新しい行(読めない行は飛ばす)"""
    p = p or path()
    out = []
    if not p or not os.path.isfile(p):
        return out
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(r, dict) and (r.get("at") or 0) >= since:
                    out.append(r)
    except OSError:
        pass
    return out


def load(now, exclude_src=(), p=None):
    """直近の重みの合計と当たり -> {"weight": 直近 WINDOW_SEC の重み(録画中のライブは 1 本 W_LIVE), "hits": [(時刻, 種類, 出どころ)], "lives": 本数}。
    exclude_src の出どころは数えない(列が自分の分を外す)"""
    rs = [r for r in rows(now - max(WINDOW_SEC, LIVE_MAX_SEC), p) if r.get("src") not in exclude_src]
    open_lives = {}
    for r in rs:
        if r.get("kind") == "live":
            open_lives[r.get("src") + str(r.get("id", ""))] = r["at"]
        elif r.get("kind") == "live-end":
            open_lives.pop(r.get("src") + str(r.get("id", "")), None)
    lives = sum(1 for at in open_lives.values() if now - at < LIVE_MAX_SEC)
    recent = [r for r in rs if now - (r.get("at") or 0) <= WINDOW_SEC and r.get("kind") not in ("live", "live-end")]
    return {"weight": round(sum(float(r.get("w") or 0) for r in recent) + lives * W_LIVE, 2),
            "hits": [(r["at"], r["hit"], r.get("src", "")) for r in recent if r.get("hit")], "lives": lives}


def day_counts(day_start, day_end, p=None):
    """[day_start, day_end) の出どころ・種類ごとの数と当たりの数 -> {"by": {"src:kind": 数}, "hits": {"src:hit": 数}}"""
    by, hits = {}, {}
    for r in rows(day_start, p):
        if (r.get("at") or 0) >= day_end:
            continue
        k = "%s:%s" % (r.get("src"), r.get("kind"))
        by[k] = by.get(k, 0) + 1
        if r.get("hit"):
            h = "%s:%s" % (r.get("src"), r["hit"])
            hits[h] = hits.get(h, 0) + 1
    return {"by": by, "hits": hits}


def prune(now, p=None):
    """KEEP_DAYS 日より古い行を消す(列が日に 1 回呼ぶ)"""
    p = p or path()
    if not p or not os.path.isfile(p):
        return
    keep = rows(now - KEEP_DAYS * 86400, p)
    try:
        with _lock:
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in keep)
            os.replace(tmp, p)
    except OSError:
        pass
