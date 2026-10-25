# -*- coding: utf-8 -*-
"""YouTube の取得の列(ytqueue)が研究の頼みの結果を done/ に書いたら、研究のセッションを起こす知らせ(10-25 ユーザー OK)。

列の done/<id>.json(研究の頼みの結果。音・動画の情報・一覧・字幕・チャット)を見回りのたびに読み、まだ知らせていない物を
STATE の鍵で覚えて BATCH_SEC 秒まとめ、claude.exe -p(haiku)に SendMessage で研究のセッション(TO_ENV / RESEARCH_NAME)へ 1 通送らせる。
中身は「取得の結果が届いた: 種類・本数・動画 id の数」だけ(結果の中身は研究が done を読む)。研究が動いていても送る(届いたら起きればよい)。
送る芯は friend の知らせと同じ human/friend/notify.batch_send(同じ件は 1 回・1 日 DAILY_MAX 回・自分の PID だけ止める・テストの形では起こさない)。
スイッチ: ON = False か 環境変数 YTT_YTQ_NOTIFY=0。呼ぶ所: 入口の列の見回り(app/server.py の voice_fetch_loop)で ytqueue.tick の後に 1 行。
"""
import glob
import os
import time

from human.friend import notify as _notify
from ytt import fsio
from . import ytqueue as _ytq

ON = True
SWITCH_ENV = "YTT_YTQ_NOTIFY"
RESEARCH_NAME = "同時発話の研究(続き)"   # 研究のセッションの名前の既定(-p からは名前で届く)
TO_ENV = "YTT_YTQ_NOTIFY_TO"               # 送り先の名前(研究の題名が変わったらここで直す)
STATE_NAME = "notify.json"
LOG_NAME = "notify.log"
BATCH_SEC = 300          # 5 分のあいだに届いた結果は 1 通にまとめる
DAILY_MAX = 24


def to_name():
    return (os.environ.get(TO_ENV) or "").strip() or RESEARCH_NAME


def _kind(d):
    """結果の種類と動画の数(列の返事の形 = 予備 2 10-25: 字幕 files{動画: 字幕}+ infos{辞書}・音と候補 file + info・
    チャット file + bundle(info なし)・動画の情報 infos[リスト]・一覧 entries・失敗 state error)"""
    if d.get("state") == "error":
        return "失敗", 1
    if isinstance(d.get("files"), dict) and d["files"]:
        return "字幕", len(d["files"])
    if d.get("file"):
        return ("音" if d.get("info") else "チャット"), 1
    if isinstance(d.get("infos"), list) and d["infos"]:
        return "動画の情報", len(d["infos"])
    if isinstance(d.get("entries"), list) and d["entries"]:
        return "一覧", len(d["entries"])
    return "その他", 1


def collect(app_dir):
    """done/ の結果 -> [{key, kind, n}](鍵 = 頼みの id と書いた時刻)"""
    out = []
    for p in glob.glob(_ytq.qdir(app_dir, "done", "*.json")):
        d = fsio.read_json_or(p, None)
        if not isinstance(d, dict) or not d.get("id"):
            continue
        kind, n = _kind(d)
        out.append({"key": "%s@%s" % (d["id"], d.get("at") or 0), "kind": kind, "n": n})
    return out


def message(items):
    """研究へ送る文(種類・本数・動画 id の数だけ)"""
    by = {}
    for it in items:
        k = by.setdefault(it["kind"], [0, 0])
        k[0] += 1
        k[1] += it["n"]
    rows = "・".join("%s %d 本(動画 %d)" % (k, v[0], v[1]) for k, v in sorted(by.items()))
    return "YouTube の取得の結果が届いた(ツールの自動の知らせ・%s): %s。合わせて %d 本。中身は列の done/ を読んでください" % (
        time.strftime("%m-%d %H:%M"), rows, len(items))


def tick(app_dir, clock=None, log=None, spawn=None, claude=None):
    """見回りの 1 回 -> 送った件数(起こさなければ 0)。失敗しても列は止めない"""
    clock, log = clock or time.time, log or (lambda m: None)
    try:
        if not ON or os.environ.get(SWITCH_ENV) == "0":
            return 0
        return _notify.batch_send(_ytq.qdir(app_dir), collect(app_dir), to_name(), message, state_name=STATE_NAME, log_name=LOG_NAME,
                                  label="研究への取得の知らせ", batch_sec=BATCH_SEC, daily_max=DAILY_MAX,
                                  on_fail=lambda cur, now, why: log("研究への取得の知らせが届かなかった(送り先「%s」・%s)" % (to_name(), why)),
                                  clock=clock, log=log, spawn=spawn, claude=claude)
    except Exception as e:   # noqa: BLE001  (知らせが壊れても取得の列は止めない)
        log("研究への取得の知らせでエラー: %s %s" % (e.__class__.__name__, str(e)[:200]))
        return 0
