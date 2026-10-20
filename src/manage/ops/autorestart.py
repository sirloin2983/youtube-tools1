# -*- coding: utf-8 -*-
"""入口の自動の起動し直し(ディスクの版 != 動いている版のとき、何も処理していない間に自分で起動し直す)の判定。

起こし方・後始末は手の「起動し直す」と同じ道(src/app/server.py の restart_self。src/manage/ops/restart.py)。ここは「今やるか」だけを決める。
- 見回りの周期(Supervisor の監視。新しい常駐は作らない)で EVERY 秒ごとに見直す。処理中なら終わるまで待つ
- 1 版につき 1 回だけ: 試す直前に版を作業データ(auto-restart.json)へ書く。起動し直しても新しい版が立たなければ、同じ版でもう自動ではしない
  (赤い帯は出たまま。手の「起動し直す」が残る)= 輪にならない
- 「画面の保存されていない変更」は画面から送られてこないので、編集の画面が EDITOR_IDLE 秒以内に使われていたら待つ(編集の保存は数秒おきに入口へ届く)
"""
import time

from ytt import fsio

EVERY = 30.0          # 見直す間隔(秒)
EDITOR_IDLE = 120.0   # 編集の画面を最後に使ってからこの秒数たつまでは待つ
STATE_NAME = "auto-restart.json"

WAIT, GO, NOTHING = "wait", "go", "nothing"


def read_tried(path):
    """自動で起動し直しを試した版(無ければ "")"""
    d = fsio.read_json_or(path, {}, kind=dict)
    return str(d.get("tried") or "")


def write_tried(path, version, from_version, now=None):
    """試す版を記録する(起動し直しの前に書く。書けなければ OSError = 試さない)"""
    fsio.write_json(path, {"tried": str(version), "from": str(from_version), "at": round(time.time() if now is None else now, 3)})


def decide(disk, running, tried, busy):
    """-> (NOTHING | WAIT | GO, 理由の文)。
    disk: ディスクの版(読めなければ "")/ running: 動いている版 / tried: 試した版(read_tried)/ busy: 処理中の理由の文か None"""
    if not disk or disk == running:
        return NOTHING, ""
    if tried == disk:
        return NOTHING, "v%s は自動で起動し直しを試しました(手の「起動し直す」で入れ替えます)" % disk
    if busy:
        return WAIT, busy
    return GO, ""


def editor_in_use(last_used, now, idle=EDITOR_IDLE):
    """編集の画面を使っている最中か(last_used = 最後に要求を受けた時刻。無ければ None)"""
    return last_used is not None and now - last_used < idle
