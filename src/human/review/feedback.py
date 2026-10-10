"""判定の記録(feedback.jsonl)。確認画面での人の結果(採用・不採用・削除・書き出し)と、人の最終の操作(手で足した・消した・採用の取り消し)を
1 行ずつ残す。盛り上がりの式の見直し(dev/eval_marks.py など)の材料。パスは含めない。

RS3-5(2026-10-10)で studio/analyze.py から human/review へ割った(解析 = 機械の流れ(①)は人の判定を書かない。書き手は store = ②)。
行の形・記録先(feedback_path)・大きくなったときの .old への移し方は前のまま。
"""
import json
import os
import shutil
import threading
import time

from ytt import studio_env as _env

MAX_FEEDBACK_BYTES = 32 * 1024 * 1024   # 1行 500〜800 バイトなので約5万件。超えたら feedback.jsonl.old の末尾へ移す(消さない)
FB_SETTING_KEYS = ("sensitivity", "length", "preRatio", "lag", "lagAuto", "headSec", "wAudio", "wChat", "wComments")


def feedback_path():
    return _env.p("feedback.jsonl")


# ---------- 判定の記録(feedback.jsonl) ----------
_fb_lock = threading.Lock()


def _feedback_row(video, mark, verdict, event):
    """feedback.jsonl の1行の共通部分(区間・点数・解析の信号と設定・配信の種類)。
    自動マークは、最初の自動区間(auto0)と手で直した量(dStart / dEnd)も残す。
    再解析で手動マークに変わったもの(auto0 が auto0Orig に移っている)も同じ値で残す(reanalyzed: true)。"""
    an = video.get("analysis") or {}
    sp = an.get("spec") or {}
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "videoId": video.get("id", ""), "kind": video.get("kind"), "start": mark.get("start"), "end": mark.get("end"),
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
        # 手動の「よかった」として盛り上がりの学習・集計(dev/eval_marks.py など)に混ざって数字を変えないように、記録しない
        return False
    path = feedback_path()
    with _fb_lock:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if os.path.exists(path) and os.path.getsize(path) > MAX_FEEDBACK_BYTES:
                _move_feedback_to_old(path)
            _append_line(path, json.dumps(row, ensure_ascii=False) + "\n")
        except OSError as e:
            _env.log_failure("feedback.jsonl への記録", e)
            return False
    return True


def feedback_for_mark(video, mark, verdict, event=""):
    """確認画面での結果(採用・不採用・削除・書き出し)を feedback.jsonl に1行で残す。パスは含めない。
    video: store の動画(id, kind, analysis を使う)、mark: そのマーク。event: adopt / reject / delete / export。
    手動マーク(src=manual)の採用・書き出しも「よかった」として残す。"""
    if verdict not in ("good", "bad"):
        return False
    return _feedback_write(_feedback_row(video, mark, verdict, event))


# 人の最終の操作の記録(Q2。機械の最初の結果と並べて残すため)。verdict は good / bad 以外の値にする(good・bad だけ数える読み手に混ざらない):
#   manual_add    "miss"     手で足したマーク = 自動の見逃し(nearAuto = その時いちばん近かった自動マーク)
#   manual_remove "unmiss"   手で足した候補のマークを手で消した(足したのは間違いだったかもしれない)
#   unadopt       "retract"  採用(書き出し済みを含む)を候補に戻した(prevStatus)
#   delete_judged "retract"  採用・不採用・書き出し済みのマークを削除した(prevStatus)
FB_EXTRA_EVENTS = {"manual_add": "miss", "manual_remove": "unmiss", "unadopt": "retract", "delete_judged": "retract"}


def nearest_auto(marks, start, end, skip_id=None):
    """区間 (start, end) にいちばん近い自動マーク(src=auto)を探す。近さは区間どうしの隙間(重なっていれば 0 秒)。
    -> {"autoCount": 自動マークの数, "nearAuto": None か {"score", "distance", "start", "end", "status"}}"""
    best, n = None, 0
    for m in marks:
        if m.get("src") != "auto" or m.get("id") == skip_id:
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


def feedback_event(video, mark, event, extra=None):
    """FB_EXTRA_EVENTS の行(手で足した・手で消した・採用の取り消し・判定済みの削除)を feedback.jsonl に1行で残す。extra の項目は行に足す。"""
    verdict = FB_EXTRA_EVENTS.get(event)
    if not verdict:
        return False
    row = _feedback_row(video, mark, verdict, event)
    if extra:
        row.update(extra)
    return _feedback_write(row)


def _append_line(path, line):
    """1行追記する。前回の行が書きかけ(電源断など)で改行が無ければ、先に改行を足して次の行と繋がらないようにする。"""
    with open(path, "a+b") as f:
        f.seek(0, os.SEEK_END)
        if f.tell() > 0:
            f.seek(-1, os.SEEK_END)
            if f.read(1) != b"\n":
                f.write(b"\n")
        f.write(line.encode("utf-8"))


def _move_feedback_to_old(path):
    """大きくなった feedback.jsonl を feedback.jsonl.old の末尾へ移して空にする。
    以前は .old を上書きしていたため、2回目の切り替えで古い記録が消えていた(精度の見直しに使う大事なデータなので消さない)。"""
    old = path + ".old"
    with open(path, "rb") as src, open(old, "ab") as dst:
        if dst.tell() > 0:
            with open(old, "rb") as chk:
                chk.seek(-1, os.SEEK_END)
                if chk.read(1) != b"\n":
                    dst.write(b"\n")
        shutil.copyfileobj(src, dst)
        dst.flush()
        try:
            os.fsync(dst.fileno())
        except OSError:
            pass
    with open(path, "wb"):
        pass   # 移し終えてから空にする(途中で止まっても記録は消えない。重複は ts で見分けられる)

