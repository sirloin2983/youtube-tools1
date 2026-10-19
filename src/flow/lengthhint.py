# -*- coding: utf-8 -*-
"""② 管理の層 flow: 自動の切り抜きの長さの目安(友人が依頼で指定した区間の長さから。OPT-E2 7f-1・7f-2。決定 3-49 の Q1)。
LD-2d(notes:plan/done/ld2-clip-length.md): 区間は場面ごと(① excite の scene_region。スイッチ excite.SHAPE_DEFAULT)なので、
この目安の役目は「場面が取れないとき(点数が無い・山が平ら)の固定の長さ」と、スイッチを fixed に戻したときの長さ。

本番の読み手 2 つ(依頼の解析 = src/app/autorun.py・ライブの新しい録画 = src/flow/live_detect.py)は、使うときにここでその場で数える
(作業データを読むだけ。スタジオの data.json・archive/<配信>.json.gz・入口の実行記録)。
⑤ eval_marks はこれを読んで表示するだけ。

見本 = 入口の実行記録(logs/autorun-runs.jsonl と .1)の ranges(友人が指定した区間。余白を足す前)。同じ配信の同じ区間(±TOL 秒)は 1 つ。
外れ値(OUTLIER_MIN 秒未満・OUTLIER_MAX 秒超)は数だけ。長さ = 見本の中央値を LENGTH_MIN〜LENGTH_MAX に丸める。
上限は 300 秒(LD-2 の L-3 = 長さの守り 60〜300 秒に合わせた。決定 3-49 Q1)。山の前の割合 preRatio = 区間の中にある自動の候補の山の位置 (山 − 開始) ÷ 長さ の中央値(見本 PRE_MIN_SAMPLES 個から)。
enough = 見本 ENOUGH_SAMPLES 個以上かつ配信 ENOUGH_VIDEOS 本以上(読み手はこのときだけ使う)。
同じ入力(data.json と実行記録の大きさ・更新の時刻)なら覚えた結果を返す(ライブの設定は数秒ごとに作り直すため)。

切り替わり(使う ⇄ 使わない・長さが変わった)は呼ぶ側が change で見て、ログと調子に 1 行出す。
標準ライブラリと ytt・flow/runlog だけ(作業データは読むだけ)。
"""
import gzip
import json
import os
import re
import threading

from ytt import studiodata as _studiodata
from . import runlog as _runlog

SCHEMA = "youtube-tools-length-hint/v1"
LENGTH_MIN, LENGTH_MAX = 10, 300       # 目安の長さの範囲(秒。解析の設定 length の範囲 = pipeline/analyze/analyze.py・flow/spec.py と同じ)
PRE_MIN, PRE_MAX = 0.3, 0.9            # 目安の preRatio の範囲(解析の設定 preRatio の範囲)
OUTLIER_MIN, OUTLIER_MAX = 5.0, 600.0  # 見本の外れ値(この外は数だけ。目安に入れない)
PRE_MIN_SAMPLES = 10                   # 山の位置の見本がこれ未満なら preRatio は出さない(None)
ENOUGH_SAMPLES, ENOUGH_VIDEOS = 20, 5  # enough: 見本 20 個以上かつ配信 5 本以上
PRE_DEFAULT = 0.65                     # 解析の記録に preRatio が無いときの山の位置(pipeline/analyze/excite.PRE_RATIO_DEFAULT と同じ値。② は ① の解析を読まない)
TOL = 0.6                              # 同じ区間とみなす秒
ARCHIVE_ID_RE = re.compile(r"^[\w-]{1,40}\Z", re.ASCII)
ARCHIVE_MAX = 64 * 1024 * 1024         # archive の 1 本の上限(展開後。これより大きければ読まない)

_CACHE = {}
_LOCK = threading.Lock()


def _num(x):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and abs(x) != float("inf") else None


def _pair(v):
    if isinstance(v, (list, tuple)) and len(v) == 2:
        a, b = _num(v[0]), _num(v[1])
        if a is not None and b is not None:
            return a, b
    return None


def _median(v):
    v = sorted(v)
    n = len(v)
    if not n:
        return None
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def _quantile(v, p):
    v = sorted(v)
    if not v:
        return None
    k = (len(v) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(v) - 1)
    return round(v[lo] + (v[hi] - v[lo]) * (k - lo), 2)


def run_ranges(r):
    """実行記録の 1 行 -> その配信で友人が指定したままの区間 [(開始, 終了)](0 ≦ 開始 < 終了。形の違うものは飛ばす。videoId か ranges が無ければ [])。
    ⑤ eval_marks・clipfit も同じ判定で読む"""
    if not isinstance(r, dict) or not isinstance(r.get("videoId"), str) or not isinstance(r.get("ranges"), list):
        return []
    return [p for p in map(_pair, r["ranges"]) if p and p[1] > p[0] >= 0]


def friend_ranges(records):
    """実行記録の行 -> {配信 ID: [(開始, 終了)]}(友人が指定したままの区間。同じ区間 ±TOL は 1 つ)"""
    per = {}
    for r in records:
        for p in run_ranges(r):
            lst = per.setdefault(r["videoId"], [])
            if not any(abs(p[0] - a) <= TOL and abs(p[1] - b) <= TOL for a, b in lst):
                lst.append(p)
    return per


def read_archive(studio, vid):
    """スタジオの archive/<配信>.json.gz -> (中身, 最後の解析の記録) か None(無い・壊れた・大きすぎる・解析の記録が無い)。⑤ eval_marks・clipfit も読む"""
    if not ARCHIVE_ID_RE.match(vid):
        return None
    try:
        with gzip.open(os.path.join(studio, "archive", vid + ".json.gz"), "rb") as f:
            raw = f.read(ARCHIVE_MAX + 1)
        if len(raw) > ARCHIVE_MAX:
            return None
        d = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, EOFError, UnicodeDecodeError):
        return None
    runs = d.get("runs") if isinstance(d, dict) and d.get("v") == 1 else None
    run = next((r for r in reversed(runs) if isinstance(r, dict)), None) if isinstance(runs, list) else None
    return (d, run) if run else None


def load_archive(studio, vid):
    """スタジオの archive/<配信>.json.gz の最後の解析 -> {"at", "type", "spec", "candidates"} か None"""
    got = read_archive(studio, vid)
    if not got:
        return None
    d, run = got
    return {"at": run.get("at"), "type": run.get("type") or d.get("type"), "spec": run.get("spec") if isinstance(run.get("spec"), dict) else {},
            "candidates": [c for c in run.get("candidates") or [] if isinstance(c, dict)]}


def candidates(dv, arch):
    """配信の自動の候補(点数の高い順)-> ([{"a0", "score", "peak"}], その解析の preRatio)。data.json のマーク(自動・自動の区間のある手動)+
    archive の最後の解析の候補(data.json から消えたものを補う)"""
    an = dv.get("analysis") if isinstance(dv.get("analysis"), dict) else {}
    spec = an.get("spec") if isinstance(an.get("spec"), dict) else (arch or {}).get("spec") or {}
    pre = _num(spec.get("preRatio")) or PRE_DEFAULT
    out = []
    for m in dv.get("marks") or []:
        if not isinstance(m, dict):
            continue
        s, e = _num(m.get("start")), _num(m.get("end"))
        a0 = _pair(m.get("auto0")) or _pair(m.get("auto0Orig"))
        if s is None or e is None or not (m.get("src") == "auto" or (m.get("src") == "manual" and a0)):
            continue
        out.append({"a0": a0 or (s, e), "score": _num(m.get("score")), "peak": _num(m.get("peak"))})
    for c in (arch or {}).get("candidates") or []:
        s, e = _num(c.get("start")), _num(c.get("end"))
        if s is None or e is None or any(abs(x["a0"][0] - s) <= TOL and abs(x["a0"][1] - e) <= TOL for x in out):
            continue
        out.append({"a0": (s, e), "score": _num(c.get("score")), "peak": _num(c.get("peak"))})
    out.sort(key=lambda c: (-(c["score"] if c["score"] is not None else -1e9), c["a0"][0]))
    return out, pre


def peak_ratio(s, e, cands, pre):
    """区間 (s, e) の中にある自動の候補の山(点数の高いものを優先)の位置 = (山 − 開始) ÷ 長さ。無ければ None。
    山 = 候補の peak。無ければ最初の自動区間 a0 に preRatio を当てて戻す"""
    if e <= s:
        return None
    for c in cands:
        p = c["peak"] if c["peak"] is not None else c["a0"][0] + (c["a0"][1] - c["a0"][0]) * pre
        if s <= p <= e:
            return round((p - s) / (e - s), 4)
    return None


def samples(studio, records, dvideos=None, archive=None):
    """見本 -> [{"videoId", "type", "start", "end", "length", "ratio"}](外れ値も含む)。dvideos = スタジオの data.json の videos・
    archive = 配信 ID -> load_archive の結果(読んであれば渡す。無ければここで読む)"""
    dvideos = _studiodata.videos(os.path.join(studio, "data.json")) if dvideos is None else dvideos
    archive = archive or (lambda vid: load_archive(studio, vid))
    out = []
    for vid, rgs in sorted(friend_ranges(records).items()):
        dv = dvideos.get(vid) if isinstance(dvideos.get(vid), dict) else {}
        arch = archive(vid)
        an = dv.get("analysis") if isinstance(dv.get("analysis"), dict) else {}
        typ = an.get("type") or (arch or {}).get("type") or "不明"
        cands, pre = candidates(dv, arch)
        for s, e in sorted(rgs):
            out.append({"videoId": vid, "type": typ, "start": s, "end": e, "length": round(e - s, 2), "ratio": peak_ratio(s, e, cands, pre)})
    return out


def suggest(lst):
    """見本(外れ値を含む)-> 目安 {"length", "preRatio", "samples", "videos", "enough", "outliers", "p25", "p50", "p75", "preSamples"}"""
    used = [x for x in lst if OUTLIER_MIN <= x["length"] <= OUTLIER_MAX]
    lens = [x["length"] for x in used]
    ratios = [x["ratio"] for x in used if x["ratio"] is not None]
    vids = {x["videoId"] for x in used}
    med = _median(lens)
    pm = _median(ratios)
    return {"length": int(round(min(LENGTH_MAX, max(LENGTH_MIN, med)))) if lens else None,
            "preRatio": round(min(PRE_MAX, max(PRE_MIN, pm)), 2) if len(ratios) >= PRE_MIN_SAMPLES else None,
            "samples": len(used), "videos": len(vids), "enough": len(used) >= ENOUGH_SAMPLES and len(vids) >= ENOUGH_VIDEOS,
            "outliers": len(lst) - len(used), "p25": _quantile(lens, 0.25), "p50": round(med, 2) if lens else None, "p75": _quantile(lens, 0.75),
            "preSamples": len(ratios)}


def _stat(path):
    try:
        st = os.stat(path)
        return st.st_mtime_ns, st.st_size
    except OSError:
        return None


def compute(studio, app, by_type=False):
    """スタジオの作業データ studio・入口の作業データ app -> 目安(suggest の形 + "schema"。by_type なら配信の種類ごとの目安 "byType" も)。
    作業データは読むだけ。同じ入力なら覚えた結果(写し)を返す"""
    runs_log = os.path.join(app, "logs", _runlog.RUNS_LOG)
    key = (os.path.abspath(studio), os.path.abspath(app), by_type, _stat(os.path.join(studio, "data.json")), _stat(runs_log), _stat(runs_log + ".1"))
    with _LOCK:
        if _CACHE.get("key") == key:
            return json.loads(_CACHE["value"])
    lst = samples(studio, _runlog.read_runs_log(runs_log))
    out = dict(suggest(lst), schema=SCHEMA)
    if by_type:
        types = {}
        for x in lst:
            types.setdefault(x["type"], []).append(x)
        out["byType"] = {t: suggest(v) for t, v in sorted(types.items())}
    with _LOCK:
        _CACHE.update(key=key, value=json.dumps(out))
    return out


def usable(hint):
    """compute の結果 -> 解析の設定に重ねる {"length", "preRatio"?} か None(enough でない・長さが無い)"""
    if not isinstance(hint, dict) or hint.get("enough") is not True or hint.get("length") is None:
        return None
    out = {"length": hint["length"]}
    if hint.get("preRatio") is not None:
        out["preRatio"] = hint["preRatio"]
    return out


def describe(hint):
    """ログ・調子の 1 行(使う・使わないと数)"""
    u = usable(hint)
    if u:
        return "長さの目安を使います(場面が取れないときの長さ): %d 秒%s(友人の区間 %d 個・配信 %d 本)" % (
            u["length"], "・山の前 %.2f" % u["preRatio"] if "preRatio" in u else "", hint["samples"], hint["videos"])
    if not isinstance(hint, dict):
        return "長さの目安を使いません(数えられませんでした)"
    return "長さの目安を使いません: 友人の区間がまだ少ない(%d 個・配信 %d 本。%d 個・%d 本から)" % (
        hint.get("samples") or 0, hint.get("videos") or 0, ENOUGH_SAMPLES, ENOUGH_VIDEOS)


def change(prev, hint):
    """前に使った目安 prev(usable の形か None)から変わったか -> (変わったか, 今の usable)"""
    u = usable(hint)
    return u != prev, u


OFF_WORDS = ("off", "0", "false", "no")
_UNSET = object()


class Tracker:
    """読み手(依頼の解析 = app/autorun・ライブの新しい録画 = flow/live_detect)ごとの殻: 止める環境変数・その場で数える・
    最初と切り替わり(使う ⇄ 使わない・長さが変わった)に note へ「<head>: <describe>」を 1 行(7f-2)"""

    def __init__(self, env_name, head, note):
        self.env_name, self.head, self.note = env_name, head, note
        self.used = _UNSET   # 前に使った目安(usable の形か None。_UNSET = まだ一度も数えていない = 最初は必ず 1 行出す)

    def off(self, *envs):
        """止める環境変数(env_name)が off・0・false・no か(渡した辞書と本物の環境変数の両方を見る)"""
        return any(str(e.get(self.env_name) or "").strip().lower() in OFF_WORDS for e in envs + (os.environ,) if e)

    def read(self, studio, app, *envs):
        """-> compute の結果か None(止めてある・数えられない)"""
        if self.off(*envs):
            return None
        try:
            h = compute(studio, app)
        except Exception as e:   # noqa: BLE001  (数えられなくても読み手は止めない)
            self.note("%s: 数えられないので使いません(%s)" % (self.head, e.__class__.__name__))
            return None
        changed, used = change(None if self.used is _UNSET else self.used, h)
        if changed or self.used is _UNSET:
            self.used = used
            self.note("%s: %s" % (self.head, describe(h)))
        return h
