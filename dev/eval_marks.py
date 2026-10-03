#!/usr/bin/env python3
"""盛り上がりの検出(スタジオの自動マーク)の当たり具合を、人の判定の記録で測る道具(線 C の土台。docs/plan/master-plan-2026-10.md の Q3・I-4a)。

    python dev/eval_marks.py [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--json] [--data-dir 作業データの親フォルダ] [--status-fallback]

- 作業データは**読むだけ**(スタジオの data.json・feedback.jsonl(と .old)・archive/<動画ID>.json.gz・入口の logs/autorun-runs.jsonl・
  cut2resolve の packs/)。何も書き換えない。--json のときだけ、結果を スタジオの作業データの evals\\marks\\<日時>.json に残す(原則 3: 機械の最初の結果と人の最終を並べる)
- feedback の行は markId(あれば)で突き合わせる。無い以前の行は区間(auto0)で突き合わせる。
- 「自動マーク」の集まり = data.json の自動マーク(再解析で手動に変わったものも含む)+ archive の最後の解析の候補(消えたものを補う)+
  feedback にだけ残っているもの(候補のまま削除した・判定のあと削除した)。同じマークは最初の自動区間(auto0)で突き合わせる(±0.6 秒)。
  点数の順(高い順)に並べ、人の判定を当てる。
- 人の判定 = feedback.jsonl の行を時刻の順に見た最後の結果: adopt・export = 良い / reject・delete = 悪い / unadopt・delete_judged(採用・書き出し済みの削除)= 取り消し(判定なしに戻る)。
  data.json のマークがあれば、いまの status を優先する(候補に戻した・不採用にした、が行に残らない場合がある)
- **まとめて実行(自動採用)・依頼の区間は人の判断ではないので「良い」に数えない**。マークの adoptedBy(auto / request)と、feedback の行の adoptedBy(書き出しの行を含む)で見分ける。
  印の無い以前の記録だけ、近似として入口の実行記録(autorun-runs.jsonl)で、その配信に「採用」の段が実行されていて、人の adopt の行が無いものを「自動採用」とみなす(近似)。
  採用・書き出しの status があるのに行も実行記録も無いものは「記録なし」として別に数える(--status-fallback を付けると人の判定として数える)
- 指標(全体・配信の種類ごと・配信ごと):
    上位 N(5・10・20・全部)の採用率 = 良い ÷ 判定済み(判定なしは分母に入れず、数を別に出す。参考として 良い ÷ N 件 の採用率(全体)も出す)
    書き出し率 = 書き出した ÷ 良い / パックになった率 = パックがある ÷ 書き出した(ytt_core.txindex.pack_info)/ 友人に届けた率 = 届けた ÷ 書き出した(入口の実行記録の deliver の段)
    手で足したマーク(manual_add = 見逃し)= 数・割合(手で足した ÷ (手で足した + 良い自動マーク))・近くの自動マークの点数と距離の分布
    区間の端のずれ = 良い自動マークの dStart・dEnd(人が直した量。秒)の分布と、0.5 秒以上直した率 / 採用の取り消しの数
- --since / --until(原則 4: 時期で分ける)は、マークの作られた日時(data.json は createdAt・archive は解析の日時・feedback だけのものは最初の行の日時)と
  手で足した・取り消した行の日時で絞る(until はその日を含む)。配信が 10 本未満のときは「まだ少ない(参考)」と出す(少ないデータで決めすぎない)
"""
import argparse
import datetime
import gzip
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)
from ytt_core import datadir, txindex  # noqa: E402

SCHEMA = "youtube-tools-marks-eval/v1"
TOPS = (5, 10, 20)
FEW_VIDEOS = 10          # これより少ない配信数のときは「まだ少ない(参考)」
TOL = 0.6                # 同じ区間とみなす秒(studio/store.py の DUP_TOL 0.5 に少し余裕)
EDIT_SEC = 0.5           # これ以上端を動かしたら「直した」
NEAR_SEC = 15.0          # 手で足したマークの近くに自動マークがあったとみなす距離(秒)
MAX_JSONL_BYTES = 256 * 1024 * 1024
HUMAN_EVENTS = ("adopt", "export", "reject", "delete")
RETRACT_EVENTS = ("unadopt", "delete_judged")
ARCHIVE_ID_RE = re.compile(r"^[\w-]{1,40}\Z", re.ASCII)


# ---------------------------------------------------------------- 読み込み(読むだけ)

def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def read_jsonl(path):
    """1行ずつ JSON として読む(壊れた行・書きかけの行は飛ばす)。無ければ []"""
    out = []
    try:
        if os.path.getsize(path) > MAX_JSONL_BYTES:
            return out
        with open(path, "rb") as f:
            for raw in f:
                try:
                    d = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    continue
                if isinstance(d, dict):
                    out.append((raw.strip(), d))
    except OSError:
        pass
    return out


def locate(data_dir=None):
    """-> (env, studio のフォルダ, 入口(app)のフォルダ)。置き場所の規則は ytt_core.datadir の1か所。
    data_dir を渡したとき(テスト)は、そこを全ツールの作業データの親フォルダとして使う(cut2resolve の packs も同じ親の下)"""
    env = {"YTT_DATA_DIR": os.path.abspath(data_dir)} if data_dir else None
    return env, datadir.locate("studio", REPO, env), datadir.locate("app", REPO, env)


def load_feedback(studio):
    """feedback.jsonl.old → feedback.jsonl の行(重複は同じ行の文字列で除く。.old へ移すときの途中停止で重なることがある)。時刻の順"""
    seen, rows = set(), []
    for name in ("feedback.jsonl.old", "feedback.jsonl"):
        for raw, d in read_jsonl(os.path.join(studio, name)):
            if raw in seen or not isinstance(d.get("videoId"), str):
                continue
            seen.add(raw)
            rows.append(d)
    rows.sort(key=lambda r: str(r.get("ts") or ""))   # 同じ時刻なら書いた順のまま(sort は安定)
    return rows


def load_archive(studio, vid):
    """archive/<動画ID>.json.gz の最後の解析 -> {"at", "type", "candidates"} か None"""
    if not ARCHIVE_ID_RE.match(vid):
        return None
    try:
        with gzip.open(os.path.join(studio, "archive", vid + ".json.gz"), "rt", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError, EOFError):
        return None
    runs = d.get("runs") if isinstance(d, dict) and d.get("v") == 1 else None
    run = next((r for r in reversed(runs) if isinstance(r, dict)), None) if isinstance(runs, list) else None
    if not run:
        return None
    return {"at": run.get("at"), "type": run.get("type") or d.get("type"), "candidates": [c for c in run.get("candidates") or [] if isinstance(c, dict)]}


def load_runs(app):
    """入口の実行記録(autorun-runs.jsonl.1 → 今のファイル)-> (自動採用の段が動いた配信の ID の集合, {配信 ID: 友人へ届けたマークの ID の集合}, 届けたがマークの ID が無い実行の数)"""
    machine, delivered, unknown = set(), {}, 0
    for name in ("autorun-runs.jsonl.1", "autorun-runs.jsonl"):
        for _, r in read_jsonl(os.path.join(app, "logs", name)):
            vid = r.get("videoId")
            if not isinstance(vid, str) or not isinstance(r.get("steps"), list):
                continue
            states = {s.get("key"): s.get("state") for s in r["steps"] if isinstance(s, dict)}
            if states.get("adopt") == "done":
                machine.add(vid)
            if states.get("deliver") == "done":
                ids = r.get("marks")
                if isinstance(ids, list) and ids:
                    delivered.setdefault(vid, set()).update(str(x) for x in ids)
                else:
                    unknown += 1
    return machine, delivered, unknown


# ---------------------------------------------------------------- 日時・数の小道具

def day_ms(s, end=False):
    """YYYY-MM-DD(この PC の時刻)-> その日の始まり(end=True なら次の日の始まり)のミリ秒"""
    try:
        d = datetime.datetime.strptime(s, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise SystemExit("日付は YYYY-MM-DD で指定してください: %r" % s)
    if end:
        d += datetime.timedelta(days=1)
    return int(time.mktime(d.timetuple()) * 1000)


def ts_ms(ts):
    try:
        return int(time.mktime(time.strptime(str(ts), "%Y-%m-%dT%H:%M:%S")) * 1000)
    except (ValueError, OverflowError):
        return None


def num(x):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and abs(x) < 1e9 else None


def rate(a, b):
    return round(a / b, 4) if b else None


def pct(x):
    return "  -  " if x is None else "%4.0f%%" % (x * 100)


def dist(values):
    """数のそろいの分布 -> {"n", "min", "p25", "median", "p75", "p90", "max", "mean"}(空なら n だけ)"""
    v = sorted(x for x in values if x is not None)
    if not v:
        return {"n": 0}

    def q(p):
        k = (len(v) - 1) * p
        lo = int(k)
        hi = min(lo + 1, len(v) - 1)
        return round(v[lo] + (v[hi] - v[lo]) * (k - lo), 2)
    return {"n": len(v), "min": round(v[0], 2), "p25": q(0.25), "median": q(0.5), "p75": q(0.75), "p90": q(0.9), "max": round(v[-1], 2), "mean": round(sum(v) / len(v), 2)}


def same(a0, b0):
    return abs(a0[0] - b0[0]) <= TOL and abs(a0[1] - b0[1]) <= TOL


def pair(v):
    if isinstance(v, (list, tuple)) and len(v) == 2 and num(v[0]) is not None and num(v[1]) is not None:
        return (float(v[0]), float(v[1]))
    return None


# ---------------------------------------------------------------- 自動マークの集まりを作る

def build_videos(studio, rows, runs, packs, since=None, until=None, status_fallback=False):
    """-> ({動画 ID: video}, 注意の一覧)。video = {"id", "title", "type", "auto": [item], "manual": [item], "adds": [...], "retracts": n}
    item(自動マーク)= {"a0", "score", "start", "end", "t", "src"(data / archive / feedback), "status", "path", "markId", "events", "verdict", "origin", ...}"""
    machine, delivered, _unknown = runs
    data = read_json(os.path.join(studio, "data.json"), {})
    dvideos = data.get("videos") if isinstance(data, dict) and isinstance(data.get("videos"), dict) else {}
    by_row = {}
    for r in rows:
        by_row.setdefault(r["videoId"], []).append(r)
    videos = {}
    notes = []

    def in_range(t):
        if t is None:
            return True   # 日時が分からないものは落とさない
        return (since is None or t >= since) and (until is None or t < until)

    for vid in sorted(set(dvideos) | set(by_row)):
        dv = dvideos.get(vid) if isinstance(dvideos.get(vid), dict) else {}
        an = dv.get("analysis") if isinstance(dv.get("analysis"), dict) else {}
        arch = load_archive(studio, vid)
        rv = by_row.get(vid, [])
        typ = an.get("type") or next((r.get("type") for r in rv if r.get("type")), None) or (arch or {}).get("type") or "不明"
        V = {"id": vid, "title": str(dv.get("title") or "")[:80], "type": typ, "auto": [], "manual": [], "adds": [], "retracts": 0, "unadopts": 0, "deleteJudged": 0}
        autos = V["auto"]

        def find(a0, rid=""):
            """区間(auto0)で突き合わせる。行に markId があるときは、別の ID を持つマークとは突き合わせない"""
            return next((it for it in autos if same(it["a0"], a0) and (not rid or not it["markId"] or it["markId"] == rid)), None)

        def by_id(lst, rid):
            return next((it for it in lst if it["markId"] == rid), None) if rid else None

        # 1. data.json のマーク
        for m in dv.get("marks") or []:
            if not isinstance(m, dict):
                continue
            s, e = num(m.get("start")), num(m.get("end"))
            if s is None or e is None:
                continue
            a0 = pair(m.get("auto0")) or pair(m.get("auto0Orig"))
            item = {"a0": a0 or (s, e), "start": s, "end": e, "score": num(m.get("score")), "t": m.get("createdAt") if isinstance(m.get("createdAt"), int) else None,
                    "src": "data", "status": m.get("status") or "", "path": m.get("path") or "", "markId": str(m.get("id") or ""), "events": [], "a0known": a0 is not None,
                    "adoptedBy": m.get("adoptedBy") if m.get("adoptedBy") in ("auto", "request") else None}
            if m.get("src") == "auto" or (m.get("src") == "manual" and a0):
                autos.append(item)
            elif m.get("src") == "manual":
                V["manual"].append(item)
        # 2. archive の最後の解析の候補(data.json から消えたものを補う。判定は無い)
        for c in (arch or {}).get("candidates") or []:
            s, e = num(c.get("start")), num(c.get("end"))
            if s is None or e is None or find((s, e)):
                continue
            autos.append({"a0": (s, e), "start": s, "end": e, "score": num(c.get("score")), "t": arch.get("at") if isinstance(arch.get("at"), int) else None, "src": "archive",
                          "status": "", "path": "", "markId": "", "events": [], "a0known": True, "adoptedBy": None})
        # 3. feedback の行
        for r in rv:
            ev = r.get("event") or ""
            s, e = num(r.get("start")), num(r.get("end"))
            t = ts_ms(r.get("ts"))
            rid = r.get("markId") if isinstance(r.get("markId"), str) else ""   # 新しい行は markId で突き合わせる(無い以前の行は区間)
            if ev == "manual_add":
                if in_range(t):
                    near = r.get("nearAuto") if isinstance(r.get("nearAuto"), dict) else None
                    V["adds"].append({"t": t, "start": s, "end": e, "markId": rid, "autoCount": r.get("autoCount"), "cancelled": False,
                                      "nearScore": num((near or {}).get("score")), "nearDistance": num((near or {}).get("distance"))})
                continue
            if ev == "manual_remove":
                for ad in reversed(V["adds"]):   # 手で足したあと同じ区間を消した = 足したのは取り消し
                    if ad["cancelled"]:
                        continue
                    if (rid and ad["markId"] == rid) or (not (rid and ad["markId"]) and s is not None and ad["start"] is not None and abs(ad["start"] - s) <= TOL and abs(ad["end"] - e) <= TOL):
                        ad["cancelled"] = True
                        break
                continue
            if rid and ev in HUMAN_EVENTS + RETRACT_EVENTS:
                hit = by_id(autos, rid) or by_id(V["manual"], rid)
                if hit is not None:
                    hit["events"].append((ev, r))
                    continue
            a0 = pair(r.get("auto0")) if r.get("auto0") else None
            if a0 is None and (r.get("src") != "auto" or s is None or e is None):
                # 手動マークの判定は、手動マークの数え方(manual)にだけ使う(下)
                if ev in HUMAN_EVENTS + RETRACT_EVENTS and s is not None and e is not None:
                    mi = next((x for x in V["manual"] if same((x["start"], x["end"]), (s, e)) and (not rid or not x["markId"] or x["markId"] == rid)), None)
                    if mi is None and in_range(t):
                        mi = {"a0": (s, e), "start": s, "end": e, "score": None, "t": t, "src": "feedback", "status": "", "path": "", "markId": rid, "events": [], "a0known": False, "adoptedBy": None}
                        V["manual"].append(mi)
                    if mi is not None:
                        mi["events"].append((ev, r))
                continue
            a0 = a0 or (s, e)
            it = find(a0, rid)
            if it is None:
                it = {"a0": a0, "start": s, "end": e, "score": num(r.get("score")), "t": t, "src": "feedback", "status": "", "path": "", "markId": rid, "events": [], "a0known": bool(r.get("auto0")), "adoptedBy": None}
                autos.append(it)
            elif rid and not it["markId"]:
                it["markId"] = rid   # archive の候補に、消えたマークの ID を結びつける
            it["events"].append((ev, r))
        # 4. 取り消しの数(日時で絞る)
        for r in rv:
            t = ts_ms(r.get("ts"))
            ev = r.get("event")
            if ev in RETRACT_EVENTS and in_range(t) and (ev == "unadopt" or r.get("prevStatus") in ("adopted", "exported")):
                V["retracts"] += 1
                V["unadopts" if ev == "unadopt" else "deleteJudged"] += 1
        # 5. 判定・書き出し・パック・届けを決める。日時で絞る
        V["auto"] = [it for it in autos if in_range(it["t"] if it["t"] is not None else (ts_ms(it["events"][0][1].get("ts")) if it["events"] else None))]
        V["manual"] = [it for it in V["manual"] if in_range(it["t"])]
        for it in V["auto"] + V["manual"]:
            judge(it, vid in machine, status_fallback)
            if it["verdict"] == "good" and it["exported"]:
                info = txindex.pack_info(it["path"], packs) if it["path"] else None
                it["packed"] = bool(info)
                it["delivered"] = bool(it["markId"]) and it["markId"] in delivered.get(vid, ())
            else:
                it["packed"] = it["delivered"] = False
        if V["auto"] or V["manual"] or V["adds"] or V["retracts"]:
            videos[vid] = V
    return videos, notes


def judge(it, machine_video, status_fallback):
    """item の events(時刻の順)と data.json の status から、人の判定を決める。
    it["verdict"] = good / bad / none(判定なし)/ machine(自動採用)/ unrecorded(status はあるが行も実行記録も無い)
    it["exported"] = 書き出した(良いもののうち)"""
    state, exported, human_adopt = None, False, False
    for ev, r in it["events"]:
        if ev in ("adopt", "export") and r.get("adoptedBy"):
            state, exported = "machine", False   # 機械が採用にしたマークの行(書き出しの行を含む)は人の判定ではない
        elif ev == "adopt":
            state, human_adopt = "good", True
        elif ev == "export":
            state, exported = "good", True
        elif ev in ("reject", "delete"):
            state, exported = "bad", False
        elif ev == "unadopt":
            state, exported = None, False
        elif ev == "delete_judged" and r.get("prevStatus") in ("adopted", "exported"):
            state, exported = None, False
    if any(r.get("markId") for _, r in it["events"]):
        machine_video = False   # markId のある新しい行は adoptedBy で機械の採用を見分けられる。実行記録からの近似は、印の無い以前の記録だけ
    st = it["status"] if it["src"] == "data" else None
    if st is None:   # data.json に無い(削除した・archive だけ): 行だけで決める
        verdict = state or "none"
    elif st in ("adopted", "exported"):
        if it.get("adoptedBy") or state == "machine":   # 機械が採用にした印(人が状態を変えると外れる)。印の無い以前の記録は、下の近似(実行記録)
            verdict = "machine"
        elif state == "good" and not (machine_video and not human_adopt):
            verdict = "good"
        elif machine_video and not human_adopt:
            verdict = "machine"
        elif status_fallback:
            verdict = "good"
        else:
            verdict = "unrecorded"
        exported = st == "exported" and verdict in ("good",)
    elif st == "rejected":
        verdict, exported = "bad", False
    else:
        verdict, exported = "none", False
    it["verdict"], it["exported"] = verdict, bool(exported and verdict == "good")
    # 端のずれ(人が直した量。秒): data のマークの今の区間 − 最初の自動区間。data が無ければ最後の行の dStart・dEnd
    it["dStart"] = it["dEnd"] = None
    if it["a0known"] and it["src"] == "data":
        it["dStart"], it["dEnd"] = round(it["start"] - it["a0"][0], 2), round(it["end"] - it["a0"][1], 2)
    else:
        for ev, r in reversed(it["events"]):
            if num(r.get("dStart")) is not None and num(r.get("dEnd")) is not None:
                it["dStart"], it["dEnd"] = num(r["dStart"]), num(r["dEnd"])
                break


# ---------------------------------------------------------------- 指標

def funnel(items):
    """item の並び -> 採用・書き出し・パック・届けの数と率"""
    n = len(items)
    c = {k: sum(1 for i in items if i["verdict"] == k) for k in ("good", "bad", "none", "machine", "unrecorded")}
    exported = sum(1 for i in items if i["exported"])
    packed = sum(1 for i in items if i["packed"])
    delivered = sum(1 for i in items if i["delivered"])
    judged = c["good"] + c["bad"]
    return {"items": n, "judged": judged, "good": c["good"], "bad": c["bad"], "unjudged": c["none"], "machine": c["machine"], "unrecorded": c["unrecorded"],
            "adoptRate": rate(c["good"], judged), "adoptRateAll": rate(c["good"], n),
            "exported": exported, "exportRate": rate(exported, c["good"]),
            "packed": packed, "packRate": rate(packed, exported),
            "delivered": delivered, "deliveredRate": rate(delivered, exported)}


def ranked(auto):
    """点数の高い順(点数が無いものは後ろ)"""
    return sorted(auto, key=lambda i: (-(i["score"] if i["score"] is not None else -1e9), i["start"] if i["start"] is not None else 0))


def group_metrics(vlist):
    """動画(build_videos の V)の集まり -> 指標。N 件は配信ごとに上位 N を取ってから合わせる(配信を重く見すぎない)"""
    out = {"videos": len(vlist), "judgedVideos": 0}
    tops = {n: [] for n in TOPS}
    tops["all"] = []
    good_items, adds, manual, edits = [], [], [], []
    for V in vlist:
        r = ranked(V["auto"])
        if any(i["verdict"] in ("good", "bad") for i in r) or V["adds"]:
            out["judgedVideos"] += 1
        tops["all"] += r
        for n in TOPS:
            tops[n] += r[:n]
        good_items += [i for i in r if i["verdict"] == "good"]
        adds += [a for a in V["adds"] if not a["cancelled"]]
        manual += V["manual"]
    out["top"] = {("all" if k == "all" else "top%d" % k): funnel(v) for k, v in tops.items()}
    ng = len(good_items)
    na = len(adds)
    near = [a["nearDistance"] for a in adds if a["nearDistance"] is not None]
    out["misses"] = {"added": na, "goodAuto": ng, "missRate": rate(na, na + ng),
                     "nearDistance": dist(near), "nearScore": dist([a["nearScore"] for a in adds]),
                     "withNearAuto": len(near), "noAuto": na - len(near), "near15s": sum(1 for d in near if d <= NEAR_SEC),
                     "farOrNone": na - sum(1 for d in near if d <= NEAR_SEC)}
    abs_all = [abs(x) for i in good_items for x in (i["dStart"], i["dEnd"]) if x is not None]
    both = [i for i in good_items if i["dStart"] is not None]
    out["edits"] = {"items": len(both), "dStart": dist([abs(i["dStart"]) for i in both]), "dEnd": dist([abs(i["dEnd"]) for i in both]),
                    "dStartSigned": dist([i["dStart"] for i in both]), "dEndSigned": dist([i["dEnd"] for i in both]),
                    "editedRate": rate(sum(1 for i in both if abs(i["dStart"]) >= EDIT_SEC or abs(i["dEnd"]) >= EDIT_SEC), len(both)), "absMean": round(sum(abs_all) / len(abs_all), 2) if abs_all else None}
    out["retracts"] = {"unadopt": sum(V["unadopts"] for V in vlist), "deleteJudged": sum(V["deleteJudged"] for V in vlist), "total": sum(V["retracts"] for V in vlist)}
    mg = [m for m in manual if m["verdict"] == "good"]
    out["manualMarks"] = {"marks": len(manual), "good": len(mg), "exported": sum(1 for m in mg if m["exported"]), "packed": sum(1 for m in mg if m["packed"]), "delivered": sum(1 for m in mg if m["delivered"])}
    return out


def evaluate(data_dir=None, since=None, until=None, status_fallback=False):
    """-> 結果の辞書(JSON にする形)。作業データは読むだけ"""
    env, studio, app = locate(data_dir)
    since_ms = day_ms(since) if since else None
    until_ms = day_ms(until, end=True) if until else None
    runs = load_runs(app)
    videos, notes = build_videos(studio, load_feedback(studio), runs, env, since_ms, until_ms, status_fallback)
    vlist = [videos[k] for k in sorted(videos)]
    types = {}
    for V in vlist:
        types.setdefault(V["type"], []).append(V)
    overall = group_metrics(vlist)
    if runs[2]:
        notes.append("友人へ届けた実行のうち %d 件は、マークの ID が実行記録に無く「届けた」に数えていません" % runs[2])
    unrec, mach = overall["top"]["all"]["unrecorded"], overall["top"]["all"]["machine"]
    if unrec:
        notes.append("採用・書き出しの状態があるのに、判定の行も入口の実行記録も無いマークが %d 個あります(記録の前のものか、行が消えた)。--status-fallback で人の判定として数えます" % unrec)
    if mach:
        notes.append("まとめて実行の自動採用とみなして正に数えなかったマークが %d 個あります(自動採用はマークに印が残らないため、実行記録で近似)" % mach)
    few = overall["judgedVideos"] < FEW_VIDEOS
    meta = {"schema": SCHEMA, "at": int(time.time() * 1000), "since": since, "until": until, "statusFallback": bool(status_fallback), "git": git_rev(),
            "studioDir": studio, "videos": len(vlist), "judgedVideos": overall["judgedVideos"], "few": few,
            "fewNote": "まだ少ない(参考): 判定のある配信が %d 本(%d 本未満)。これで既定値を決めない" % (overall["judgedVideos"], FEW_VIDEOS) if few else "", "notes": notes}
    by_video = []
    for V in vlist:
        g = group_metrics([V])
        by_video.append(dict(g, videoId=V["id"], title=V["title"], type=V["type"]))
    return {"meta": meta, "overall": overall, "byType": {k: group_metrics(v) for k, v in sorted(types.items())}, "byVideo": by_video}


def git_rev():
    try:
        return subprocess.run(["git", "-C", REPO, "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


# ---------------------------------------------------------------- 表示・保存

def print_group(title, g):
    print("  [%s]  配信 %d 本(判定あり %d 本)" % (title, g["videos"], g["judgedVideos"]))
    print("    %-7s %5s %5s %5s %6s %6s %5s %5s %6s %5s %6s %5s" % ("上位", "件", "判定", "良い", "採用率", "(全体)", "自動", "書出", "書出率", "パック", "パック率", "届け"))
    for k, f in g["top"].items():
        print("    %-7s %5d %5d %5d %6s %6s %5d %5d %6s %5d %6s %5d" % (k, f["items"], f["judged"], f["good"], pct(f["adoptRate"]), pct(f["adoptRateAll"]), f["machine"],
                                                                f["exported"], pct(f["exportRate"]), f["packed"], pct(f["packRate"]), f["delivered"]))
    f = g["top"]["all"]
    if f["unjudged"] or f["unrecorded"]:
        print("    判定なし %d 個(分母に入れていない)・記録なし %d 個" % (f["unjudged"], f["unrecorded"]))
    m, e, r = g["misses"], g["edits"], g["retracts"]
    nd = m["nearDistance"]
    print("    手で足した(見逃し) %d 個 / 良い自動 %d 個 → 見逃しの割合 %s。近くの自動マーク: 距離の中央値 %s 秒・%d 秒以内 %d 個・遠いか無し %d 個"
          % (m["added"], m["goodAuto"], pct(m["missRate"]).strip(), nd.get("median", "-"), NEAR_SEC, m["near15s"], m["farOrNone"]))
    if e["items"]:
        print("    端のずれ(良い自動 %d 個): 開始 中央値 %s 秒・90%% %s 秒 / 終了 中央値 %s 秒・90%% %s 秒 / %.1f 秒以上直した %s"
              % (e["items"], e["dStart"].get("median"), e["dStart"].get("p90"), e["dEnd"].get("median"), e["dEnd"].get("p90"), EDIT_SEC, pct(e["editedRate"]).strip()))
    print("    採用の取り消し %d(候補に戻した %d・採用したものを削除 %d)" % (r["total"], r["unadopt"], r["deleteJudged"]))


def print_report(res):
    m = res["meta"]
    rng = "%s 〜 %s" % (m["since"] or "最初", m["until"] or "今") if (m["since"] or m["until"]) else "全期間"
    print("盛り上がり検出の測定(%s)  配信 %d 本・判定のある配信 %d 本  スタジオ: %s" % (rng, m["videos"], m["judgedVideos"], m["studioDir"]))
    if m["fewNote"]:
        print("★ " + m["fewNote"])
    if not m["videos"]:
        print("(データがありません。スタジオでマークを判定すると貯まります)")
        return
    print_group("全体", res["overall"])
    for k, g in res["byType"].items():
        print_group("配信の種類: " + k, g)
    print("  [配信ごと(上位10件の採用率)]")
    for v in res["byVideo"]:
        f = v["top"]["top10"]
        print("    %s %-6s 採用率 %s(判定 %d / 件 %d)見逃し %d  %s" % (v["videoId"], v["type"], pct(f["adoptRate"]), f["judged"], f["items"], v["misses"]["added"], v["title"][:30]))
    for n in m["notes"]:
        print("注意: " + n)


def save(res, studio):
    d = os.path.join(studio, "evals", "marks")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "%s.json" % datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return path


def main(argv=None):
    p = argparse.ArgumentParser(description="盛り上がり検出の当たり具合を人の判定の記録で測る(作業データは読むだけ)")
    p.add_argument("--since", help="この日(YYYY-MM-DD)以後のものだけ")
    p.add_argument("--until", help="この日(YYYY-MM-DD。この日を含む)までのものだけ")
    p.add_argument("--json", action="store_true", help="同じ形の JSON を スタジオの作業データの evals/marks/<日時>.json に残す")
    p.add_argument("--data-dir", help="作業データの親フォルダ(既定 %%LOCALAPPDATA%%\\youtube-tools。テスト用)")
    p.add_argument("--status-fallback", action="store_true", help="行も実行記録も無い採用・書き出しの状態を、人の判定として数える")
    args = p.parse_args(argv)
    res = evaluate(args.data_dir, args.since, args.until, args.status_fallback)
    print_report(res)
    if args.json:
        print("\n保存: " + save(res, res["meta"]["studioDir"]))
    return res


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    main()
