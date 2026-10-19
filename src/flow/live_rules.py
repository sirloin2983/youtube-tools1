# -*- coding: utf-8 -*-
"""友人のライブ配信の依頼の設定の決まりと、依頼と録画の結びつきの記録(notes:docs/spec/friend.md の 2-15)。範囲・既定・読み直しの 1 か所。

結びつきの記録 RequestBook(flow/livehost.RequestBook の形)はここの 1 つ: 入口(src/app/live.py。ユーザーの PC)と友人の玄関(friendapp/live_session.py)が作る。
置き場所は作業データの live/requests.json
  {"v": 1, "items": {"<録画元>/<録画>": {"rid", "deliverDir", "url", "title", "streamer", "speakers", "videoTracks", "cut",
                                          "settings": clean_settings の形, "createdAt"}}}
を ② の検出・採用・配信後の追加が読む。設定の文の言葉(感度の言い方)は読む側(human/friend/live_requests・friendapp/live)が持つ。
長さの上限 180 秒 = A-5b の仮(ユーザーの PC の自動の切り抜きの上限と同じ)。
長さ「自動(場面ごと)」(友人の玄関の C-2-11)は settings の lengthMode "auto"(無い = 固定の長さ)。検出のワーカーが場面ごとの形で切る(長さは場面が取れないときの長さ)。
軽い部品だけ(友人の玄関が画面を先に出すため。ytt と標準ライブラリだけを読む・ファイルは結びつきの記録だけ)。
"""
import copy
import threading
import time

from ytt import fsio, schemas, tools

SENS = ("high", "normal", "low")
LENGTH = (10, 180)      # 切り抜きの長さの範囲(秒)
SETTINGS_DEFAULT = {"sens": "normal", "perHour": 6, "length": 45, "waitMin": 5, "pad": 2.0, "afterStream": True}
RANGES = {"perHour": (1, 30), "length": LENGTH, "waitMin": (1, 60), "pad": (0.0, 5.0)}
KEEP_DAYS = 3           # 結びつきを残す日数(録画 12 時間 + 配信後の全自動 live_archive.AFTER_MAX_AGE 2 日に足りる)
MAX_ITEMS = 50          # 結びつきの数の上限(多すぎれば古い物から捨てる)
TEXT_MAX = 300          # url・題名を残す長さ


def num_in(v, lo, hi):
    return schemas.is_num(v) and lo <= v <= hi


def clean_settings(v):
    """依頼・記録・前回の値から読んだ設定 -> 検査済みの設定(無い・範囲の外は既定)"""
    v = v if isinstance(v, dict) else {}
    out = dict(SETTINGS_DEFAULT)
    if v.get("sens") in SENS:
        out["sens"] = v["sens"]
    for k in ("perHour", "length", "waitMin"):
        x = v.get(k)
        if num_in(x, *RANGES[k]):
            out[k] = int(round(x))
    if num_in(v.get("pad"), *RANGES["pad"]):
        out["pad"] = float(v["pad"])
    if isinstance(v.get("afterStream"), bool):
        out["afterStream"] = v["afterStream"]
    if v.get("lengthMode") == "auto":
        out["lengthMode"] = "auto"
    return out


def settings_text(s, sens_labels):
    """検査済みの設定 -> 「感度 …・1 時間 … 本・長さ …・待ち … 分・余白 … 秒・配信後の追加 …」(感度の言葉は読む側の画面に合わせて渡す)"""
    size = "長さ 自動(場面ごと)" if s.get("lengthMode") == "auto" else "長さ %d 秒" % s["length"]
    return "感度 %s・1 時間 %d 本・%s・待ち %d 分・余白 %g 秒・配信後の追加 %s" % (
        sens_labels[s["sens"]], s["perHour"], size, s["waitMin"], s["pad"], "あり" if s["afterStream"] else "なし")


def _key(rc, rec):
    return "%s/%s" % (rc, rec)


class RequestBook:
    """友人の依頼と録画の結びつき(説明は先頭)。get・all・put・remove・update・prune。メモリに持ち、初めて使うときに読み、変えたときだけ書く。
    中は lock(受付・見回り・画面の糸から使う)。deliver=False = 届けない PC(友人の玄関。deliverDir はいつも空)"""

    def __init__(self, path, clock=time.time, log=None, deliver=True):
        self.path, self.clock, self.log, self.deliver = path, clock, log or (lambda m: None), deliver
        self.lock = threading.Lock()
        self._items = None

    def _load(self):
        if self._items is None:
            d = fsio.read_json_or(self.path, None, 1024 * 1024, kind=dict)
            items = d.get("items") if d else None
            # 読み直した項目も settings は検査済みの形・createdAt は数にそろえる(検出が settings["pad"] を、prune が引き算をそのまま使う)
            self._items = {k: dict(v, settings=clean_settings(v.get("settings")), createdAt=v["createdAt"] if schemas.is_num(v.get("createdAt")) else 0)
                           for k, v in (items if isinstance(items, dict) else {}).items() if isinstance(v, dict) and isinstance(v.get("rid"), str)}
        return self._items

    def _save(self):
        try:
            fsio.write_json(self.path, {"v": 1, "items": self._items}, indent=None)
        except OSError as e:
            self.log("ライブ: 友人の依頼と録画の結びつきを書けませんでした(%s)" % tools.why(e))

    def _item(self, ctx):
        """依頼の欄 ctx -> 結びつきの 1 項目(形の違う値は入れない)"""
        def text(key, n):
            return str(ctx.get(key) or "")[:n]
        vt, cut = ctx.get("videoTracks"), ctx.get("cut")
        return {"rid": text("rid", 64), "deliverDir": text("deliverDir", 1024) if self.deliver else "", "url": text("url", TEXT_MAX),
                "title": text("title", TEXT_MAX), "streamer": text("streamer", 80),
                "speakers": ctx["speakers"] if isinstance(ctx.get("speakers"), dict) else None,
                "videoTracks": vt if isinstance(vt, int) and not isinstance(vt, bool) else None,
                "cut": cut if isinstance(cut, str) and cut else None, "settings": clean_settings(ctx.get("settings")), "createdAt": self.clock()}

    def get(self, rc, rec):
        """録画に結びついた依頼(dict の写し)か None"""
        with self.lock:
            v = self._load().get(_key(rc, rec))
            return copy.deepcopy(v) if v else None

    def all(self):
        with self.lock:
            return copy.deepcopy(self._load())

    def put(self, rc, rec, ctx):
        """録画を依頼に結びつける(同じ録画に 2 つ目の依頼が来たら新しいほうで置き換える・多すぎれば古い物から捨てる)-> 残した項目"""
        item = self._item(ctx)
        with self.lock:
            items = self._load()
            items[_key(rc, rec)] = item
            while len(items) > MAX_ITEMS:
                items.pop(min(items, key=lambda k: items[k].get("createdAt") or 0))
            self._save()
        return dict(item)

    def remove(self, rc, rec):
        with self.lock:
            if self._load().pop(_key(rc, rec), None) is not None:
                self._save()
                return True
        return False

    def update(self, rc, rec, settings):
        """録画中に依頼の設定を差し替える(C-2-11。今の設定に重ねて読み直す = 範囲の外は既定)-> 残した項目か None(結びつきが無い)"""
        with self.lock:
            item = self._load().get(_key(rc, rec))
            if item is None:
                return None
            item["settings"] = clean_settings(dict(item.get("settings") or {}, **settings))
            self._save()
            return copy.deepcopy(item)

    def prune(self, keep_days=KEEP_DAYS):
        """古い結びつき(録画と配信後の処理が済んで十分たった物)を消す -> 消した数"""
        now = self.clock()
        with self.lock:
            items = self._load()
            old = [k for k, v in items.items() if now - (v.get("createdAt") or 0) > keep_days * 86400]
            for k in old:
                items.pop(k, None)
            if old:
                self._save()
        return len(old)
