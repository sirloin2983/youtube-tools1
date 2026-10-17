# -*- coding: utf-8 -*-
"""② 管理の層 flow: 素材を 30fps(H.264・yuv420p・AAC)にそろえる 1 つの段(役割で組み直す OPT-M2 5b-1・2026-10-16。
それまでは ④ manage/cases/relink.py の norm_plan・norm_run などが持っていた。決定は資料 plan/opt-manage.md の 5b)。

30fps にそろえる道は ② のこの段だけ。中身の道具(判定 needs_normalize・作り直し normalize)は ① ytt/normalize。
- plan(src, replace=False) -> None(作り直さない) か {"src", "dst", "reuse", "replace", "why": [理由], "note"?: 作れない理由(作らずに知らせる)}
  スイッチ TRANSCRIBE_NORMALIZE=off・音声だけのファイルは None・ネットワーク上の動画は理由だけ(note)。
  replace=False(既定): 元の隣に <名前>_30fps.mp4(同じ名前があって使えるなら使い回し・使えなければ上書きせず _2〜_9)。元は消さない
  replace=True: 元の動画の置き換え(作業データの中の写し用)。名前は同じ名前の .mp4(重なれば乱数)・できたら元を消す(同じ名前なら上書き)
- run(plan, cancelled, on_progress, on_start) -> (できたパス か None, 知らせ)。書けるか・空き(元の大きさ + 1GB)を見てから作り直す。
  失敗・取り消し・書けない・空きが足りないときはパスが None で知らせに理由(例外にしない)
- run_job(job, swap) = ジョブ kind "normalize" の本体(進み具合は「30fps にそろえています… n%」)。できたら swap(tid, src, dst) で文書を付け替える。
  swap は ④ の norm_swap を呼ぶ側(serve)が渡す(② は ④ を読めない)。-> None(付け替えた) か 付け替えなかった理由
SLOTS(重い処理の枠)は呼ぶ側が持つ(ジョブなら ytt/jobs の work_one。ここで取り直すと上限 1 で自分を待って止まる)。
"""
import os
import shutil
import tempfile

from ytt import fsio as _fsio, normalize as _vnorm, tools as _tools, txbase as _txbase
from . import jobs as _heavy

NORM_SUFFIX = "_30fps"
NORM_PHASE = "動画の 1 秒のコマ数を 30 にそろえています(30fps)…"   # 言葉の説明つき(2 周目 S10)   # 画面は「30fps にそろえています… n%」(ジョブの progress)
NORM_MIN_FREE = 1024 ** 3                 # 作り直しの前に、元の動画の大きさ + これだけの空きを求める
TOL_RATIO = 0.005                         # 使い回す写しの長さの許し(元の長さの 0.5%。付け替えの長さの比べと同じ)


def enabled():
    """TRANSCRIBE_NORMALIZE=off で作り直さない(どの fps でも動くので、困ったときの逃げ道)"""
    return not _txbase.env_off("TRANSCRIBE_NORMALIZE")


def sibling_name(src):
    """隣に作る名前 <名前>_30fps.mp4"""
    d, n = os.path.split(os.path.abspath(src))
    return os.path.join(d, os.path.splitext(n)[0] + NORM_SUFFIX + ".mp4")


def usable(path, info_src):
    """すでにある写しをそのまま使えるか(30fps でそろっていて、長さが元と同じ)"""
    info = _vnorm.probe(path)
    if not info or _vnorm.needs_normalize(info)[0]:
        return False
    a, b = info.get("duration"), (info_src or {}).get("duration")
    return a is not None and (b is None or abs(a - b) <= max(_vnorm.DURATION_TOL, TOL_RATIO * b))


def plan(src, replace=False):
    """作り直しの予定。-> None(作り直さない)か {"src", "dst", "reuse", "replace", "why": [理由], "note"?: 作れない理由(作らずに知らせる)}"""
    if not enabled() or not src:
        return None
    src = os.path.abspath(src)
    ext = os.path.splitext(src)[1].lower()
    if _tools.MEDIA_TYPES.get(ext, "").startswith("audio/"):   # 音声だけのファイル(カバー画像を映像と数えない)
        return None
    if _fsio.is_network_path(src) or _fsio.is_remote_drive(src):
        return {"src": src, "dst": None, "reuse": False, "replace": bool(replace), "why": [],
                "note": "ネットワーク上の動画は 30fps にそろえません(元の動画のまま使います)"}
    info = _vnorm.probe(src)
    if info is None:
        return {"src": src, "dst": None, "reuse": False, "replace": bool(replace), "why": [],
                "note": "動画を調べられなかったため、30fps にそろえませんでした(ffprobe が見つからないか、読めないファイルです)"}
    if not info.get("has_video"):
        return None
    need, why = _vnorm.needs_normalize(info)
    if not need:
        return None
    if replace:
        target = os.path.splitext(src)[0] + ".mp4"
        if os.path.normcase(target) != os.path.normcase(src) and os.path.exists(target):
            target = "%s-%s.mp4" % (os.path.splitext(src)[0], os.urandom(3).hex())
        return {"src": src, "dst": target, "reuse": False, "replace": True, "why": why}
    base = sibling_name(src)
    for p in [base] + [base[:-4] + "_%d.mp4" % i for i in range(2, 10)]:
        # 同じ名前があって使えるならそれを使う。使えない(別の動画・30fps でない)なら上書きせずに次の名前へ
        if os.path.normcase(p) == os.path.normcase(src):
            continue
        if not os.path.exists(p):
            return {"src": src, "dst": p, "reuse": False, "replace": False, "why": why}
        if os.path.isfile(p) and usable(p, info):
            return {"src": src, "dst": p, "reuse": True, "replace": False, "why": why}
    return {"src": src, "dst": None, "reuse": False, "replace": False, "why": why,
            "note": "隣に 30fps の動画を作る名前が空いていないため、元の動画のまま使います(%s)" % os.path.basename(base)}


def room(src, dst):
    """書けるか・空きが足りるか。-> None(書ける)か 書けない理由"""
    d = os.path.dirname(dst)
    try:
        os.makedirs(d, exist_ok=True)
        fd, test_path = tempfile.mkstemp(prefix=".ytt-write-test-", dir=d)
        os.close(fd)
        os.unlink(test_path)
    except OSError:
        return "動画のフォルダに書き込めないため(読み取り専用など)、30fps にそろえられませんでした。文書は元の動画のままです"
    try:
        need = os.path.getsize(src) + NORM_MIN_FREE
        free = shutil.disk_usage(d).free
    except OSError:
        return None
    if free < need:
        return "ディスクの空きが足りないため(%.1f GB 必要)、30fps にそろえられませんでした。文書は元の動画のままです" % (need / 1024 ** 3)
    return None


def run(plan, cancelled=None, on_progress=None, on_start=None):
    """予定どおりに作り直す(SLOTS は呼ぶ側が持つ)。-> (できた動画のパス か None, 知らせの文)。
    パスが None のときの知らせは作らなかった理由(元の動画のまま)。on_start() = 実際に ffmpeg を回す直前(使い回しのときは呼ばない)"""
    src, dst = plan["src"], plan.get("dst")
    if plan.get("note") or not dst:
        return None, plan.get("note") or ""
    if not plan.get("reuse"):
        why = room(src, dst)
        if why:
            return None, why
        if on_start:
            on_start()
        try:
            done = _vnorm.normalize(src, dst, cancelled=cancelled, on_progress=on_progress) or {}
        except _vnorm.Cancelled:
            return None, "30fps にそろえるのを取り消しました。文書は元の動画のままです"
        except (_vnorm.NormalizeError, OSError) as e:
            _txbase.log.warning("30fps の作り直しに失敗: %s %s", src, e)
            return None, "30fps にそろえられませんでした(%s)。文書は元の動画のままです" % str(e)[:200]
        if plan.get("replace") and os.path.normcase(dst) != os.path.normcase(src):
            try:
                os.remove(src)   # 置き換え = 古い写しを消す(消せなくても作り直した動画は使える)
            except OSError:
                pass
        how = ("・%s" % done["how"]) if done.get("how") else ""
        if done.get("failed"):
            _txbase.log.warning("30fps の作り直しで先に失敗した作り方: %s %s", src, " / ".join(done["failed"]))
        return dst, "30fps にそろえた動画 %s を作って付け替えました(元の動画はそのまま残っています%s)" % (os.path.basename(dst), how)
    return dst, "30fps の動画 %s があったので、それに付け替えました" % os.path.basename(dst)


def set_note(job, ok, note):
    """ジョブの知らせ job["normNote"]・job["normOk"](付け替えなかったときは job["warnings"] にも)"""
    if not note:
        return
    job["normNote"], job["normOk"] = note, bool(ok)
    if not ok:
        _txbase.add_warning(job, note)


def run_job(job, swap=None):
    """ジョブ kind "normalize" の本体(選び直しのあとの作り直し。SLOTS は work_one が持っている)。
    job["spec"] = {"tid", "plan"}。job の state・phase・progress を「30fps にそろえています… n%」にする。
    できたら swap(tid, src, dst) -> None か 付け替えなかった理由(④ の norm_swap。serve が渡す)で文書を付け替える"""
    spec = job["spec"]
    try:
        def start():
            job["state"], job["phase"], job["progress"], job["device"] = "running", NORM_PHASE, 0.0, ""
        p = spec["plan"]
        path, note = run(p, cancelled=lambda: bool(job.get("cancel")),
                         on_progress=lambda x: job.__setitem__("progress", round(float(x), 3)), on_start=start)
        ok = bool(path)
        if path and swap:
            why = swap(spec["tid"], p["src"], path)
            if why:
                ok, note = False, why
        set_note(job, ok, note)
        job["progress"], job["state"], job["phase"] = 1.0, "done", "完了" if ok else "元の動画のまま"
    except Exception as e:
        _heavy.set_internal_error(job, e)
