"""スタジオのマークの機械の記録(machine_marks.jsonl。10-19 ③ の統合 Q2 で feedback.jsonl から名前を変えた)。
人がマークを触ったときの**機械の様子**(区間・点数・点数の内訳・解析の設定と信号・最初の自動区間 auto0・手で直した量 dStart / dEnd・機械の採用の印 adoptedBy)と、
**見逃しの出来事**(手で足した manual_add・手で足した候補を消した manual_remove・採用の取り消し unadopt・判定済みの削除 delete_judged)を 1 行ずつ残す。
盛り上がりの式の見直し(src/eval/tools/eval_marks.py)の材料。パスは含めない。

**人の採否(採用・不採用・削除)はここに書かない**: 正は人の判断の記録 judgments.jsonl(human/judgments。書き手は human/review/store)。
ここの採否のきっかけの行(event adopt・reject・delete・export)は、その時の機械の様子だけを残す(verdict の欄は持たない。前の名前のころの行は verdict を持つが、読み手は使わない)。
前の名前 feedback.jsonl の行は machine_marks.jsonl.old の末尾へ写してある(元のファイルは消さない・読まない)。

解析 = 機械の流れ(①)は書かない。書き手は ③ の human/review/store(保存に成功したあとにロックの外で書く)。録画(kind live)は書かない。
大きくなったら machine_marks.jsonl.old の末尾へ足して空にする(fsio.append_line の keep_old。消さない)。
"""
import json
import threading
import time

from ytt import fsio as _fsio, studio_env as _env

FILE = "machine_marks.jsonl"
MAX_BYTES = 32 * 1024 * 1024   # 1行 500〜800 バイトなので約5万件。超えたら .old の末尾へ移す(消さない)
SETTING_KEYS = ("sensitivity", "length", "preRatio", "lag", "lagAuto", "headSec", "wAudio", "wChat", "wComments")
JUDGED_EVENTS = ("adopt", "reject", "delete", "export")   # 機械の様子を残すきっかけ(採否の正は judgments。export は書き出した = 起きた事実)
# 見逃しの出来事(Q2 = 資料の git:before-1028-cleanup:plan/line-bc-master-plan.md の Q2。機械の最初の結果と人の最終の操作を並べるため):
#   manual_add     手で足したマーク = 自動の見逃し(nearAuto = その時いちばん近かった自動マーク)
#   manual_remove  手で足した候補のマークを手で消した(足したのは間違いだったかもしれない)
#   unadopt        採用(書き出し済みを含む)・不採用を候補に戻した(prevStatus)
#   delete_judged  採用・不採用・書き出し済みのマークを削除した(prevStatus)
MISS_EVENTS = ("manual_add", "manual_remove", "unadopt", "delete_judged")

_lock = threading.Lock()


def path():
    return _env.p(FILE)


def _row(video, mark, event, ts=None):
    """1 行の共通部分(区間・点数・解析の信号と設定・配信の種類)。
    自動マークは、最初の自動区間(auto0)と手で直した量(dStart / dEnd)も残す。
    再解析で手動マークに変わったもの(auto0 が auto0Orig に移っている)も同じ値で残す(reanalyzed: true)。
    ts: 呼ぶ側が決めた時刻(人の判断の記録 judgments の key と同じ値にするため)。省けば今の時刻。"""
    an = video.get("analysis") or {}
    sp = an.get("spec") or {}
    row = {"ts": ts or time.strftime("%Y-%m-%dT%H:%M:%S"), "videoId": video.get("id", ""), "kind": video.get("kind"), "start": mark.get("start"), "end": mark.get("end"),
           "peak": mark.get("peak"), "score": mark.get("score"), "parts": mark.get("parts") or {}, "signals": an.get("signals") or {},
           "settings": {k: sp[k] for k in SETTING_KEYS if k in sp}, "source": "review", "src": mark.get("src", "auto"), "event": event,
           "duration": video.get("duration"), "type": an.get("type"), "markId": mark.get("id")}
    if mark.get("adoptedBy"):   # 機械が採用にしたマーク(まとめて実行・依頼)。書き出しの行が人の判断と混ざらないように(Q2)
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


def record(video, mark, event, extra=None, ts=None):
    """機械の様子を 1 行残す。video: store の動画(id, kind, analysis を使う)、mark: そのマーク。
    event: JUDGED_EVENTS(adopt / reject / delete / export)か MISS_EVENTS。extra の項目は行に足す(nearAuto・prevStatus など)。ts: 行の時刻(省けば今)。
    ライブの録画(kind live。線 D の P3)は解析していない(自動マークが無い)ので書かない = 手で付けたマークが「自動の見逃し」に混ざらない。-> 書いたか"""
    if event not in JUDGED_EVENTS + MISS_EVENTS or video.get("kind") == "live":
        return False
    row = _row(video, mark, event, ts)
    if extra:
        row.update(extra)
    with _lock:
        try:
            _fsio.append_line(path(), json.dumps(row, ensure_ascii=False) + "\n", MAX_BYTES, keep_old=True)   # 超えたら .old の末尾へ足す(消さない)
        except OSError as e:
            _env.log_failure("%s への記録" % FILE, e)
            return False
    return True


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
