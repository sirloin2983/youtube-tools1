# -*- coding: utf-8 -*-
"""③ 人の層: 友人のアプリの更新の見張り(ユーザーの PC。友人のアプリの更新の決め・10-25 ユーザーの OK。notes:plan/友人の不具合の自動対応-1025.md の「更新」)。

並べて持つ物(state = <app>\\friend-bugs\\upwatch.json):
- 配った版: 受付のフォルダの `更新\\versions.json` の publishedAt のある一番新しい行(dev/build_friend_zip.py --publish が書く)。無ければ latest.json と更新時刻
- 友人の今の版: `診断\\` の一番新しい心拍 `*__beat-<13 桁>.beat.json`(30 分ごとの 1 行)の appVersion・待っている理由 wait・取ってある版 pending。
  心拍が無い・古ければ、状態の書き出しの記録(human/friend/bugs の appVersion)
- 最後に友人から何か届いた時刻: `診断\\`・`送り返し\\` のファイルの一番新しい更新時刻
知らせ(alerts = <app>\\friend-bugs\\alerts.jsonl。1 つの鍵に 1 回。まとめ役が `py -3.12 dev/friend_bugs.py --alerts` で読む・ログにも 1 行):
- top(最上の急ぎ): 友人の exe・アプリが置く「起動できなかった」「前の版へ戻した」`*__fail-<13 桁>.fail.json`
- warn: 配って STALE_SEC(24 時間)たっても友人の版が変わらず、待っている理由(録画中など)も届いていない = 友人の PC を確かめてもらう
- note(記録だけ): 待っている理由つきの入れ替えの遅れ(ライブで確かめが後回しなど)
片付け: 知らせは KEEP_DAYS(3 日)で消す。標準ライブラリと ytt・flow だけ。intake.scan から scan が 1 行で呼ばれる(失敗しても見回りは止めない)。
"""
import glob
import json
import os
import re
import time

from flow import retention
from ytt import fsio

STATE_NAME, ALERTS_NAME = "upwatch.json", "alerts.jsonl"
IN_DIR, RETURNS_DIR, UPDATE_DIR = "診断", "送り返し", "更新"
BEAT_RE = re.compile(r"^[0-9A-Za-z_-]{1,64}__beat-(\d{13})\.beat\.json\Z")
FAIL_RE = re.compile(r"^[0-9A-Za-z_-]{1,64}__fail-(\d{13})\.fail\.json\Z")
MAX_BYTES = 64 * 1024
STALE_SEC = 24 * 3600               # 配ってこの秒数たっても友人の版が変わらなければ知らせる
KEEP_DAYS = retention.KEEP_DAYS
LEVELS = ("top", "warn", "note")
FAIL_LABELS = {"launch_fail": "新しい版で起動できなかった", "rollback": "前の版へ戻した"}


def _root(app_dir):
    return os.path.join(app_dir, "friend-bugs")


def _ver(v):
    return tuple(int(x) for x in v.split(".")) if isinstance(v, str) and re.fullmatch(r"\d+\.\d+\.\d+", v) else None


def _read(p):
    try:
        if os.path.getsize(p) > MAX_BYTES:
            return None
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def published(sync_folder):
    """配った版 -> {version, at(ミリ秒)} か None"""
    up = os.path.join(sync_folder, UPDATE_DIR)
    rows = ((_read(os.path.join(up, "versions.json")) or {}).get("versions")) or []
    rows = [r for r in rows if isinstance(r, dict) and _ver(r.get("version")) and isinstance(r.get("publishedAt"), int)]
    if rows:
        r = max(rows, key=lambda r: _ver(r["version"]))
        return {"version": r["version"], "at": r["publishedAt"], "important": bool(r.get("important"))}
    lt = os.path.join(up, "latest.json")
    d = _read(lt)
    if d and _ver(d.get("version")):
        return {"version": d["version"], "at": int(os.path.getmtime(lt) * 1000), "important": bool(d.get("important"))}
    return None


def friend_now(sync_folder, app_dir):
    """友人の今の版 -> {version, at, wait, pending, from(beat か state)} か None"""
    best = None
    for p in glob.glob(os.path.join(sync_folder, IN_DIR, "*.beat.json")):
        m = BEAT_RE.match(os.path.basename(p))
        if m and (best is None or int(m.group(1)) > best[0]):
            best = (int(m.group(1)), p)
    beat = _read(best[1]) if best else None
    if beat and _ver(beat.get("appVersion")):
        return {"version": beat["appVersion"], "at": best[0], "wait": str(beat.get("wait") or "")[:40],
                "pending": beat.get("pending") if isinstance(beat.get("pending"), str) else None, "from": "beat"}
    recs = []
    for p in glob.glob(os.path.join(_root(app_dir), "*.json")):
        r = fsio.read_json_or(p, None)
        if isinstance(r, dict) and _ver(r.get("appVersion")) and isinstance(r.get("at"), int):
            recs.append(r)
    if recs:
        r = max(recs, key=lambda r: r["at"])
        return {"version": r["appVersion"], "at": r["at"], "wait": "", "pending": None, "from": "state"}
    return None


def last_seen(sync_folder):
    """最後に友人から何か届いた時刻(ミリ秒。診断\\・送り返し\\ のファイル)か None"""
    t = 0.0
    for d in (os.path.join(sync_folder, IN_DIR), os.path.join(sync_folder, RETURNS_DIR)):
        try:
            for e in os.scandir(d):
                if e.is_file():
                    t = max(t, e.stat().st_mtime)
        except OSError:
            pass
    return int(t * 1000) if t else None


def alerts(app_dir, now=None, days=KEEP_DAYS):
    """知らせの一覧(新しい順。days 日の分)"""
    now = time.time() if now is None else now
    out = [r for r in fsio.iter_jsonl(os.path.join(_root(app_dir), ALERTS_NAME)) if isinstance(r, dict) and now * 1000 - (r.get("at") or 0) <= days * 86400000]
    return sorted(out, key=lambda r: r.get("at") or 0, reverse=True)


def scan(sync_folder, app_dir, clock=None, log=None):
    """見張りの 1 回: 配った版・友人の今の版・最後に届いた時刻を並べて持ち、知らせる物があれば alerts.jsonl に 1 行(1 つの鍵に 1 回)"""
    clock, log = clock or time.time, log or (lambda m: None)
    try:
        _scan(sync_folder, app_dir, clock, log)
    except Exception as e:   # noqa: BLE001  (更新の見張りが壊れても依頼の受付は止めない)
        log("友人のアプリの更新の見張りでエラー: %s %s" % (e.__class__.__name__, str(e)[:200]))


def _scan(sync_folder, app_dir, clock, log):
    root = _root(app_dir)
    os.makedirs(root, exist_ok=True)
    sp = os.path.join(root, STATE_NAME)
    st = fsio.read_json_or(sp, None) or {}
    keys = set(st.get("keys") or [])
    now = int(clock() * 1000)
    pub, fr, seen = published(sync_folder), friend_now(sync_folder, app_dir), last_seen(sync_folder)
    new = []

    def alert(level, key, text, **extra):
        if key not in keys:
            keys.add(key)
            new.append(dict({"at": now, "level": level, "key": key, "text": text}, **extra))

    for p in sorted(glob.glob(os.path.join(sync_folder, IN_DIR, "*.fail.json"))):
        n = os.path.basename(p)
        if not FAIL_RE.match(n):
            continue
        d = _read(p) or {}
        what = FAIL_LABELS.get(d.get("kind"), "起動か更新の失敗")
        alert("top", "fail:" + n, "友人のアプリ: %s(%s → %s)%s" % (what, str(d.get("from") or "?")[:20], str(d.get("to") or "?")[:20],
                                                            ":" + str(d.get("why"))[:300] if d.get("why") else ""), file=n)
    if pub and fr and _ver(fr["version"]) < _ver(pub["version"]) and now - pub["at"] > STALE_SEC * 1000:
        if fr.get("wait") and (fr["at"] >= pub["at"]):
            alert("note", "wait:%s:%s" % (pub["version"], fr["wait"]), "友人の版 %s のまま(配った %s・待っている理由: %s)" % (fr["version"], pub["version"], fr["wait"]))
        else:
            alert("warn", "stale:" + pub["version"], "配って %d 時間たっても友人の版が %s のまま(配った %s)。待っている理由も届いていません。友人の PC を確かめてもらってください"
                  % ((now - pub["at"]) // 3600000, fr["version"], pub["version"]) + ("(最後に届いた: %s)" % time.strftime("%m-%d %H:%M", time.localtime(seen / 1000)) if seen else ""))
    for a in new:
        fsio.append_jsonl(os.path.join(root, ALERTS_NAME), [a])
        log("友人のアプリの更新の知らせ(%s): %s" % (a["level"], a["text"]))
    keep = [a for a in alerts(app_dir, clock())]
    if len(keep) != sum(1 for _ in fsio.iter_jsonl(os.path.join(root, ALERTS_NAME))):
        fsio.atomic_write(os.path.join(root, ALERTS_NAME), "".join(json.dumps(a, ensure_ascii=False) + "\n" for a in reversed(keep)).encode("utf-8"))
    fsio.write_json(sp, {"published": pub, "friend": fr, "lastSeen": seen, "checkedAt": now, "keys": sorted(keys)[-500:]})
