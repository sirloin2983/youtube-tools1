"""友人のライブ配信の依頼と録画の結びつき(docs/spec/friend-intake.md の 2-15。ホーム 0.47.0)。

依頼の受付(src/home/intake.py)が配信中・配信前の URL の依頼を受け付けると、録画を始めて(src/home/live.py の Live.begin_request)ここに結びつけ、
録画の候補の検出・自動の採用(src/home/live_detect.py・live_excite_worker.py)・採用した切り抜きの書き出しのあと(src/home/live_export.py の _handoff)・
配信後のアーカイブからの追加(src/home/live_archive.py)が、この結びつきを見て友人の設定で動き、パックを友人へ届ける。

置き場所: 入口の作業データの live/requests.json
  {"v": 1, "items": {"<録画元の id>/<録画の id>": {"rid", "deliverDir", "url", "title", "streamer", "speakers", "videoTracks", "cut", "memo",
                                                   "settings": {"sens", "perHour", "length", "waitMin", "pad", "afterStream"}, "createdAt"}}}
settings = 友人のベータの設定(依頼の JSON の live)。範囲の外・無い鍵は既定(SETTINGS_DEFAULT)。
"""
import copy
import threading
import time

from ytt_core import fsio, schemas, tools

SENS = ("high", "normal", "low")
SETTINGS_DEFAULT = {"sens": "normal", "perHour": 6, "length": 45, "waitMin": 5, "pad": 2.0, "afterStream": True}
RANGES = {"perHour": (1, 30), "length": (10, 120), "waitMin": (1, 60), "pad": (0.0, 5.0)}
KEEP_DAYS = 14          # 結びつきを残す日数(録画 12 時間 + 配信後のアーカイブの作り直しに数日)
MAX_SEC = 6 * 3600.0    # D-13(仮の数): 1 依頼の録画の上限(依頼から。超えたら入口が録画を止める = src/home/live.py の stop_long_requests)
MAX_ITEMS = 50
TEXT_MAX = 300


def clean_settings(v):
    """依頼の JSON の live -> 検査済みの設定(無い・範囲の外は既定)"""
    v = v if isinstance(v, dict) else {}
    out = dict(SETTINGS_DEFAULT)
    if v.get("sens") in SENS:
        out["sens"] = v["sens"]
    for k in ("perHour", "length", "waitMin"):
        x = v.get(k)
        lo, hi = RANGES[k]
        if schemas.is_num(x) and lo <= x <= hi:
            out[k] = int(round(x))
    if schemas.is_num(v.get("pad")) and RANGES["pad"][0] <= v["pad"] <= RANGES["pad"][1]:
        out["pad"] = float(v["pad"])
    if isinstance(v.get("afterStream"), bool):
        out["afterStream"] = v["afterStream"]
    return out


def settings_label(s):
    """受付の一覧に出す 1 行"""
    return "ライブの設定: 感度 %s・1 時間 %d 本・長さ %d 秒・待ち %d 分・余白 %g 秒・配信後の追加 %s" % (
        {"high": "高", "normal": "普通", "low": "低"}[s["sens"]], s["perHour"], s["length"], s["waitMin"], s["pad"], "あり" if s["afterStream"] else "なし")


def key_of(rc, rec):
    return "%s/%s" % (rc, rec)


class Store:
    """結びつきの記録(メモリに持ち、変えたときだけ書く)。入口の中の複数のスレッド(受付・見回り・API)から使うので中は lock"""

    def __init__(self, path, clock=time.time, log=None):
        self.path, self.clock, self.log = path, clock, log or (lambda m: None)
        self.lock = threading.Lock()
        self._items = None

    def _load(self):
        if self._items is None:
            d = fsio.read_json_or(self.path, None, 1024 * 1024, kind=dict)
            items = d.get("items") if d else None
            # 読み直した項目も settings は検査済みの形・createdAt は数にそろえる(live.py が settings["pad"] を、prune が引き算をそのまま使う)
            self._items = {k: dict(v, settings=clean_settings(v.get("settings")), createdAt=v["createdAt"] if schemas.is_num(v.get("createdAt")) else 0)
                           for k, v in (items if isinstance(items, dict) else {}).items() if isinstance(v, dict) and isinstance(v.get("rid"), str)}
        return self._items

    def _save(self):
        try:
            fsio.write_json(self.path, {"v": 1, "items": self._items}, indent=None)
        except OSError as e:
            self.log("リアルタイム切り抜き: 友人の依頼の結びつきを書けませんでした(%s)" % tools.why(e))

    def get(self, rc, rec):
        """録画に結びついた依頼(dict の写し)か None"""
        with self.lock:
            v = self._load().get(key_of(rc, rec))
            return copy.deepcopy(v) if v else None

    def all(self):
        with self.lock:
            return copy.deepcopy(self._load())

    def put(self, rc, rec, ctx):
        """録画を依頼に結びつける(同じ録画に 2 つ目の依頼が来たら、新しいほうで置き換える)。-> 残した項目"""
        item = {"rid": str(ctx.get("rid") or "")[:40], "deliverDir": str(ctx.get("deliverDir") or "")[:1024], "url": str(ctx.get("url") or "")[:TEXT_MAX],
                "title": str(ctx.get("title") or "")[:TEXT_MAX], "streamer": str(ctx.get("streamer") or "")[:80],
                "speakers": ctx.get("speakers") if isinstance(ctx.get("speakers"), dict) else None,
                "videoTracks": ctx["videoTracks"] if isinstance(ctx.get("videoTracks"), int) and not isinstance(ctx.get("videoTracks"), bool) else None,
                "cut": ctx.get("cut") if isinstance(ctx.get("cut"), str) and ctx.get("cut") else None,
                "memo": str(ctx.get("memo") or "")[:500], "settings": clean_settings(ctx.get("settings")), "createdAt": self.clock()}
        with self.lock:
            items = self._load()
            items[key_of(rc, rec)] = item
            while len(items) > MAX_ITEMS:
                items.pop(min(items, key=lambda k: items[k].get("createdAt") or 0))
            self._save()
        return dict(item)

    def remove(self, rc, rec):
        with self.lock:
            if self._load().pop(key_of(rc, rec), None) is not None:
                self._save()
                return True
        return False

    def prune(self, keep_days=KEEP_DAYS):
        """古い結びつきを消す(録画と配信後の処理が済んで十分たったもの)。-> 消した数"""
        now = self.clock()
        with self.lock:
            items = self._load()
            old = [k for k, v in items.items() if now - (v.get("createdAt") or 0) > keep_days * 86400]
            for k in old:
                items.pop(k, None)
            if old:
                self._save()
        return len(old)
