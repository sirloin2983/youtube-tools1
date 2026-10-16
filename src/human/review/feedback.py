"""判定の記録(feedback.jsonl)。確認画面での人の結果(採用・不採用・削除・書き出し)と、人の最終の操作(手で足した・消した・採用の取り消し)を
1 行ずつ残す。盛り上がりの式の見直し(src/eval/tools/eval_marks.py など)の材料。パスは含めない。

解析 = 機械の流れ(①)は人の判定を書かない。書き手は ③ の human/review/store(保存に成功したあとにロックの外で書く)。録画(kind live)は書かない。
大きくなったら feedback.jsonl.old の末尾へ足して空にする(fsio.append_line の keep_old。消さない)。
"""
import json
import threading
import time

from ytt import fsio as _fsio, studio_env as _env

MAX_FEEDBACK_BYTES = 32 * 1024 * 1024   # 1行 500〜800 バイトなので約5万件。超えたら feedback.jsonl.old の末尾へ移す(消さない)
FB_SETTING_KEYS = ("sensitivity", "length", "preRatio", "lag", "lagAuto", "headSec", "wAudio", "wChat", "wComments")


def feedback_path():
    return _env.p("feedback.jsonl")


# ---------- 判定の記録(feedback.jsonl) ----------
_fb_lock = threading.Lock()


def _feedback_row(video, mark, verdict, event, ts=None):
    """feedback.jsonl の1行の共通部分(区間・点数・解析の信号と設定・配信の種類)。
    自動マークは、最初の自動区間(auto0)と手で直した量(dStart / dEnd)も残す。
    再解析で手動マークに変わったもの(auto0 が auto0Orig に移っている)も同じ値で残す(reanalyzed: true)。
    ts: 呼ぶ側が決めた時刻(判断の記録 judgments の key と同じ値にするため)。省けば今の時刻。"""
    an = video.get("analysis") or {}
    sp = an.get("spec") or {}
    row = {"ts": ts or time.strftime("%Y-%m-%dT%H:%M:%S"), "videoId": video.get("id", ""), "kind": video.get("kind"), "start": mark.get("start"), "end": mark.get("end"),
           "peak": mark.get("peak"), "score": mark.get("score"), "parts": mark.get("parts") or {}, "verdict": verdict, "signals": an.get("signals") or {},
           "settings": {k: sp[k] for k in FB_SETTING_KEYS if k in sp}, "source": "review", "src": mark.get("src", "auto"), "event": event,
           "duration": video.get("duration"), "type": an.get("type"), "markId": mark.get("id")}
    if mark.get("adoptedBy"):   # 機械が採用にしたマーク(まとめて実行・依頼)。書き出しの行が人の「よかった」に混ざらないように(Q2)
        row["adoptedBy"] = mark["adoptedBy"]
    a0 = mark.get("auto0")
    if not a0 and mark.get("auto0Orig"):
        a0 = mark["auto0Orig"]
        row["reanalyzed"] = True
    if isinstance(a0, (list, tuple)) and len(a0) == 2:
        row["auto0"] = a0
        try:
            row["dStart"], row["dEnd"] = round(float(mark["start"]) - float(a0[0]), 1), round(float(mark["end"]) - float(a0[1]), 1)
        except (KeyError, TypeError, ValueError):
            pass
    return row


def _feedback_write(row):
    if row.get("kind") == "live":
        # ライブの録画(線 D の P3)は解析していない(自動マークが無い): 手で付けたマークが「自動の見逃し」(manual_add)や
        # 手動の「よかった」として盛り上がりの学習・集計(src/eval/tools/eval_marks.py など)に混ざって数字を変えないように、記録しない
        return False
    path = feedback_path()
    with _fb_lock:
        try:
            _fsio.append_line(path, json.dumps(row, ensure_ascii=False) + "\n", MAX_FEEDBACK_BYTES, keep_old=True)   # 超えたら .old の末尾へ足す(消さない)
        except OSError as e:
            _env.log_failure("feedback.jsonl への記録", e)
            return False
    return True


def feedback_for_mark(video, mark, verdict, event="", ts=None):
    """確認画面での結果(採用・不採用・削除・書き出し)を feedback.jsonl に1行で残す。パスは含めない。
    video: store の動画(id, kind, analysis を使う)、mark: そのマーク。event: adopt / reject / delete / export。
    手動マーク(src=manual)の採用・書き出しも「よかった」として残す。ts: 行の時刻(省けば今)。"""
    if verdict not in ("good", "bad"):
        return False
    return _feedback_write(_feedback_row(video, mark, verdict, event, ts))


# 人の最終の操作の記録(Q2。機械の最初の結果と並べて残すため)。verdict は good / bad 以外の値にする(good・bad だけ数える読み手に混ざらない):
#   manual_add    "miss"     手で足したマーク = 自動の見逃し(nearAuto = その時いちばん近かった自動マーク)
#   manual_remove "unmiss"   手で足した候補のマークを手で消した(足したのは間違いだったかもしれない)
#   unadopt       "retract"  採用(書き出し済みを含む)を候補に戻した(prevStatus)
#   delete_judged "retract"  採用・不採用・書き出し済みのマークを削除した(prevStatus)
FB_EXTRA_EVENTS = {"manual_add": "miss", "manual_remove": "unmiss", "unadopt": "retract", "delete_judged": "retract"}


def nearest_auto(marks, start, end):
    """区間 (start, end) にいちばん近い自動マーク(src=auto)を探す。近さは区間どうしの隙間(重なっていれば 0 秒)。
    -> {"autoCount": 自動マークの数, "nearAuto": None か {"score", "distance", "start", "end", "status"}}"""
    best, n = None, 0
    for m in marks:
        if m.get("src") != "auto":
            continue
        try:
            ms, me = float(m["start"]), float(m["end"])
        except (KeyError, TypeError, ValueError):
            continue
        n += 1
        gap = max(0.0, ms - float(end), float(start) - me)
        key = (gap, -(m.get("score") or 0))
        if best is None or key < best[0]:
            best = (key, m)
    near = None
    if best:
        m = best[1]
        near = {"score": m.get("score"), "distance": round(best[0][0], 1), "start": m.get("start"), "end": m.get("end"), "status": m.get("status", "")}
    return {"autoCount": n, "nearAuto": near}


def feedback_event(video, mark, event, extra=None, ts=None):
    """FB_EXTRA_EVENTS の行(手で足した・手で消した・採用の取り消し・判定済みの削除)を feedback.jsonl に1行で残す。extra の項目は行に足す。"""
    verdict = FB_EXTRA_EVENTS.get(event)
    if not verdict:
        return False
    row = _feedback_row(video, mark, verdict, event, ts)
    if extra:
        row.update(extra)
    return _feedback_write(row)
