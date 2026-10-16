# -*- coding: utf-8 -*-
"""友人の玄関のライブの依頼の欄と結びつき(F2-6。notes:plan/f1-friend-requirements.md の A-5・A-5b、docs/spec/friend.md の 2-15)。軽い部品だけ(画面を先に出すため)。

- 6 つの設定の検査の表(check_settings = 送る欄・clean_settings = 記録の読み直し)。長さは 10〜180 秒 = A-5b の仮。LD-2e で「自動(場面ごと)」を足すのは LENGTH の 1 か所
- RequestBook = 友人の依頼と録画の結びつき(③ human の live_requests は読まない = 受信箱の側に持つ。flow/livehost.RequestBook の形 = get・all・put・prune)
② のライブ係 FriendLive は friendapp/live_session.py(flow/livesession を読む重い部品)。
"""
import copy
import os
import threading
import time

from ytt import fsio, schemas, tools

SENS = ("high", "normal", "low")
LENGTH = (10, 180)                  # 切り抜きの長さの範囲(秒。A-5b の仮 = ユーザーの PC の自動の切り抜きの上限と同じ 180。LD-2e で「自動(場面ごと)」を足す所)
SETTINGS_DEFAULT = {"sens": "normal", "perHour": 6, "length": 45, "waitMin": 5, "pad": 2.0, "afterStream": True}
RANGES = {"perHour": (1, 30), "length": LENGTH, "waitMin": (1, 60), "pad": (0.0, 5.0)}
SENS_LABELS = {"high": "高い", "normal": "ふつう", "low": "低い"}
KEEP_DAYS = 3                       # 結びつきを残す日数(録画 12 時間 + 配信後の追加 2 日に足りる。③ の live_requests と同じ)
MAX_ITEMS = 50
TEXT_MAX = 300
STORE_DIR = os.path.join("app", "live")
REQUESTS_NAME = "requests.json"
REC_FOLDER = "ライブの録画"         # 一時保管の中の録画の置き場所(7 章)


def _num_in(v, lo, hi):
    return schemas.is_num(v) and lo <= v <= hi


def check_settings(v):
    """送る欄のライブの 6 つの設定 -> 整えた設定。範囲の外・形の違う値は ValueError(画面にそのまま出す文)"""
    if not isinstance(v, dict):
        raise ValueError("ライブの設定が正しくありません")
    if v.get("sens") not in SENS:
        raise ValueError("感度は 高い・ふつう・低い のどれかにしてください")
    out = {"sens": v["sens"]}
    for key, what, unit in (("perHour", "1 時間の枠", "本"), ("length", "長さ", "秒"), ("waitMin", "待ち", "分")):
        x = v.get(key)
        lo, hi = RANGES[key]
        if not (isinstance(x, int) and not isinstance(x, bool) and lo <= x <= hi):
            raise ValueError("%sは %d〜%d %s にしてください" % (what, lo, hi, unit))
        out[key] = x
    if not _num_in(v.get("pad"), *RANGES["pad"]):
        raise ValueError("余白は 0〜5 秒にしてください")
    out["pad"] = float(v["pad"])
    if not isinstance(v.get("afterStream"), bool):
        raise ValueError("配信後の追加はオンかオフにしてください")
    out["afterStream"] = v["afterStream"]
    return out


def clean_settings(v):
    """記録・前回の値から読んだ設定 -> 検査済みの設定(無い・範囲の外は既定。③ の live_requests.clean_settings と同じ読み方で長さだけ 180 まで)"""
    v = v if isinstance(v, dict) else {}
    out = dict(SETTINGS_DEFAULT)
    if v.get("sens") in SENS:
        out["sens"] = v["sens"]
    for k in ("perHour", "length", "waitMin"):
        x = v.get(k)
        if _num_in(x, *RANGES[k]):
            out[k] = int(round(x))
    if _num_in(v.get("pad"), *RANGES["pad"]):
        out["pad"] = float(v["pad"])
    if isinstance(v.get("afterStream"), bool):
        out["afterStream"] = v["afterStream"]
    return out


def settings_label(s):
    """記録に出す 1 行"""
    return "感度 %s・1 時間 %d 本・長さ %d 秒・待ち %d 分・余白 %g 秒・配信後の追加 %s" % (
        SENS_LABELS[s["sens"]], s["perHour"], s["length"], s["waitMin"], s["pad"], "あり" if s["afterStream"] else "なし")


def _int_or_none(v, lo=None, hi=None):
    if not isinstance(v, int) or isinstance(v, bool) or (lo is not None and not lo <= v <= hi):
        return None
    return v


def request_item(ctx, now):
    """依頼の欄 ctx(engine.live_submit が封筒 + 束 + 送った欄から組む)-> 結びつきの 1 項目。友人の PC は届けない = deliverDir は空"""
    def text(key, n):
        return str(ctx.get(key) or "")[:n]
    cut = ctx.get("cut")
    return {"rid": text("rid", 64), "deliverDir": "", "url": text("url", TEXT_MAX), "title": text("title", TEXT_MAX), "streamer": text("streamer", 80),
            "speakers": ctx["speakers"] if isinstance(ctx.get("speakers"), dict) else None, "videoTracks": _int_or_none(ctx.get("videoTracks")),
            "cut": cut if isinstance(cut, str) and cut else None, "memo": text("memo", 500), "settings": clean_settings(ctx.get("settings")),
            "createdAt": now, "deliverBatch": _int_or_none(ctx.get("deliverBatch"), 1, 10)}


def _read_items(path):
    """requests.json -> {鍵: 項目}(読めない・形の違う項目は捨てる。設定は検査し直す)"""
    d = fsio.read_json_or(path, None, 1024 * 1024, kind=dict) or {}
    raw = d.get("items") if isinstance(d.get("items"), dict) else {}
    out = {}
    for key, v in raw.items():
        if isinstance(v, dict) and isinstance(v.get("rid"), str):
            out[key] = dict(v, settings=clean_settings(v.get("settings")), createdAt=v["createdAt"] if schemas.is_num(v.get("createdAt")) else 0)
    return out


class RequestBook:
    """友人の依頼と録画の結びつき(flow/livehost.RequestBook の形 = get・all・put・prune)。<作業データ>/app/live/requests.json。
    中身の形は ③ の live_requests.Store と同じ {"v": 1, "items": {"<録画元>/<録画>": request_item の形}}(② の検出・採用・配信後の追加が読む)。
    作るときに読み、変えたときだけ書く。中は lock(受付・見回り・画面の糸から使う)"""

    def __init__(self, path, clock=time.time, log=None):
        self.path, self.clock, self.log = path, clock, log or (lambda m: None)
        self.lock = threading.Lock()
        self.items = _read_items(path)

    def _write(self):
        try:
            fsio.write_json(self.path, {"v": 1, "items": self.items}, indent=None)
        except OSError as e:
            self.log("ライブ: 依頼と録画の結びつきを書けませんでした(%s)" % tools.why(e))

    def get(self, rc, rec):
        with self.lock:
            return copy.deepcopy(self.items.get("%s/%s" % (rc, rec)))

    def all(self):
        with self.lock:
            return copy.deepcopy(self.items)

    def put(self, rc, rec, ctx):
        """録画を依頼に結びつける(同じ録画に 2 つ目の依頼が来たら新しいほうで置き換える・多すぎれば古い物から捨てる)-> 残した項目"""
        item = request_item(ctx, self.clock())
        with self.lock:
            self.items["%s/%s" % (rc, rec)] = item
            for key in sorted(self.items, key=lambda k: self.items[k].get("createdAt") or 0)[:max(0, len(self.items) - MAX_ITEMS)]:
                del self.items[key]
            self._write()
        return dict(item)

    def prune(self, keep_days=KEEP_DAYS):
        """古い結びつき(録画と配信後の追加が済んで十分たった物)を消す -> 消した数"""
        limit = self.clock() - keep_days * 86400
        with self.lock:
            keep = {k: v for k, v in self.items.items() if (v.get("createdAt") or 0) >= limit}
            gone = len(self.items) - len(keep)
            if gone:
                self.items = keep
                self._write()
        return gone
