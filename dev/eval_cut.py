#!/usr/bin/env python3
"""カットのたたき台(機械の最初の結果)と、人の最終の差を測る道具(マスタープラン Q3・I-3a: 無音のしきい値・行の後の余白の既定を見直す材料)。

    python dev/eval_cut.py [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--json] [--data-dir 作業データの親フォルダ]

- 作業データは**読むだけ**(transcribe の transcripts/<id>.edit.json と <id>.json、cut2resolve の packs/ のパックを作った記録)。何も書き換えない。
  --json のときだけ、結果を文字起こしの作業データの evals\\cut\\<日時>.json に残す(evals の置き場所は eval_speakers.py・eval_marks.py・eval_asr.py と同じ規則)。
- たたき台 = edit.json の draft(初めてのたたき台。{origin, settings, keepsSec, at}。Q2 で入れた。それより前の edit.json には無い = 数だけ出して測らない)。
  origin = rows(行から)・silence(無音)・list(時刻リスト)・plan(スタジオ)・all・whole。種類ごとに分けて測る。
- 人の最終 = パックの記録の cutPlan(パックにした最終)と edit.json の clips(保存したカット)のうち**新しい方**
  (パックの builtAt と edit.json の updatedAt(無ければファイルの更新時刻)を比べる。パックを作ったあとにカットを直したら、直した方が最終)。パックが無ければ clips。
  どちらを使ったかの内訳(パック / 保存したカット)を出す。
  パックの記録は、文書の動画のパス(付け替える前のパスも)から ytt_core.txindex の規則(pack_dir・pack_key)で探す。
- 区間の対応づけ: たたき台の区間と最終の区間を、重なり(0 秒より長い)でつなぎ、つながった塊ごとに見る
    1対1 … 端のずれを測る(開始・終了とも 0.5 コマ未満なら「そのまま」、超えれば「端を動かした」)
    たたき台だけの塊 = 消した区間 / 最終だけの塊 = 足した区間 / n対m(分けた・つないだ)= 形を変えた(外側の端のずれだけ測る)
- 指標: 端のずれ(最終 − たたき台。コマ。30fps で数える。素材の fps が 30 でない文書は、その fps のコマも別に出す)の分布(符号つき・絶対値)・
  「そのまま」の端の割合・5 コマ以上の割合 / 残す秒の差(最終 − たたき台。文書ごと)の分布・長く/短くなった数 /
  直した数(足した・消した・端を動かした・形を変えた区間の数)・まったく直さなかった文書の割合 /
  設定(draft.settings = 行から: on・after・before・padAfter / 無音: noise・min・pad)の組み合わせごと・1つの値ごとの集計
- --since / --until(原則 4: 時期で分ける)は draft.at(無ければ edit.json の更新時刻 updatedAt)で絞る(until はその日を含む)。
  最終がパックの cutPlan の文書が 20 本未満のときは「まだ少ない(参考)」と出す(少ないデータで既定値を決めない)
- 注意: 人はたたき台につられる(迷うと直さずに通す)ので「直さなかった割合」は甘く出る。パックにしていない文書の最終は、保存したカット(途中かもしれない)
"""
import argparse
import bisect
import datetime
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOP = os.path.dirname(HERE)      # リポジトリ直下(git)
REPO = os.path.join(TOP, "src")   # ツールと ytt_core の置き場所
if REPO not in sys.path:
    sys.path.insert(0, REPO)
from ytt_core import datadir, txindex  # noqa: E402

SCHEMA = "youtube-tools-cut-eval/v1"
EDIT_SCHEMA = "youtube-tools-edit/v1"     # src/editor/ed_store.py の EDIT_SCHEMA と同じ(editor は読み込まない)
BASE_FPS = 30                              # 端のずれはまず 30fps のコマで数える(Q1: 素材は 30fps にそろえる)
TOL_FRAMES = 0.5                           # 端のずれがこのコマ数未満なら「そのまま」(フレームの丸めと 0.001 秒の丸めの差を除く)
BIG_FRAMES = 5                             # 「大きく動かした」とみなすコマ数
FEW_PACKS = 20                             # 最終がパックの文書がこれより少ないときは「まだ少ない(参考)」
EPS = 1e-6
MAX_EDIT_BYTES = 8 * 1024 * 1024
MAX_DOC_BYTES = 64 * 1024 * 1024
MAX_PACK_RECORD_BYTES = 16 * 1024 * 1024
EDIT_RE = re.compile(r"^([0-9a-f]{12})\.edit\.json\Z")
ORIGIN_LABELS = {"rows": "行から", "silence": "無音", "list": "時刻リスト", "plan": "スタジオ(cut-plan)", "all": "動画全体(行が無い)", "whole": "カットしない"}


# ---------------------------------------------------------------- 読み込み(読むだけ)

def read_json(path, default=None, limit=None):
    try:
        if limit and os.path.getsize(path) > limit:
            return default
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def env_for(data_dir):
    return {"YTT_DATA_DIR": os.path.abspath(data_dir)} if data_dir else None


def locate(data_dir=None):
    """-> 文字起こしの作業データのフォルダ。置き場所の規則は ytt_core.datadir の1か所(data_dir はテスト用)"""
    return datadir.locate("transcribe", REPO, env_for(data_dir))


def num(x):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and abs(x) < 1e12 else None


def ms_of(x):
    """ミリ秒の時刻(num は秒の範囲の数だけ通すので別に)-> 整数か None"""
    return int(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and 0 < x < 1e15 else None


def read_edit(path):
    """edit.json -> {"fps": 実数, "clips": [(in, out)], "origin", "updatedAt", "draft"(正しければ。無ければ None)} か None(読めない・形が違う)"""
    d = read_json(path, None, MAX_EDIT_BYTES)
    if not isinstance(d, dict) or d.get("schema") != EDIT_SCHEMA or not isinstance(d.get("clips"), list):
        return None
    fps = None
    try:
        n, m = d["sources"][0]["fps"]
        if num(n) and num(m) and 0 < n / m <= 300:
            fps = n / m
    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError):
        pass
    if fps is None:
        return None
    clips = []
    for c in d["clips"]:
        a, b = (num(c.get("in")), num(c.get("out"))) if isinstance(c, dict) else (None, None)
        if a is None or b is None:
            return None
        clips.append((a, b))
    at = d.get("updatedAt") if isinstance(d.get("updatedAt"), int) and not isinstance(d.get("updatedAt"), bool) and d.get("updatedAt") > 0 else 0
    if not at:   # 更新時刻が無い(手で作った・古い)edit.json はファイルの更新時刻
        try:
            at = int(os.path.getmtime(path) * 1000)
        except OSError:
            at = 0
    return {"fps": fps, "clips": clips, "origin": d.get("origin"), "updatedAt": at, "draft": read_draft(d.get("draft"))}


def read_draft(v):
    """draft -> {"origin", "settings", "keeps": [(a, b)], "at"} か None(無い・形が違う)"""
    if not isinstance(v, dict) or not isinstance(v.get("origin"), str) or not isinstance(v.get("keepsSec"), list):
        return None
    keeps = []
    for x in v["keepsSec"]:
        a, b = (num(x[0]), num(x[1])) if isinstance(x, list) and len(x) == 2 else (None, None)
        if a is None or b is None:
            return None
        keeps.append((a, b))
    st = v.get("settings") if isinstance(v.get("settings"), dict) else {}
    at = v.get("at")
    return {"origin": v["origin"], "settings": {str(k): x for k, x in st.items() if isinstance(x, (bool, int, float, str))},
            "keeps": keeps, "at": at if isinstance(at, int) and not isinstance(at, bool) else 0}


def pack_final(rec):
    """パックの記録の cutPlan -> [(開始秒, 終了秒)] か None。segments(最終に残す区間。status が rejected 以外)、無ければ keep_frames ÷ frame_rate"""
    cp = rec.get("cutPlan") if isinstance(rec, dict) else None
    if not isinstance(cp, dict):
        return None
    out = []
    if isinstance(cp.get("segments"), list):
        for s in cp["segments"]:
            if not isinstance(s, dict) or s.get("status") == "rejected":
                continue
            a, b = num(s.get("start")), num(s.get("end"))
            if a is None or b is None:
                return None
            out.append((a, b))
        return out
    kf, fr = cp.get("keep_frames"), cp.get("frame_rate")
    try:
        n, d = (int(x) for x in str(fr).split("/"))
        if isinstance(kf, list) and n > 0 and d > 0:
            return [(x[0] * d / n, x[1] * d / n) for x in kf]
    except (ValueError, TypeError, IndexError):
        pass
    return None


def find_pack(doc, env):
    """文書の動画のパス(付け替える前のパスも)から、パックを作った記録を探す(規則は ytt_core.txindex)。-> 記録 か None。
    複数あれば builtAt が新しいもの。パックのフォルダの中身が消えていても、記録があれば最終として使う(読むだけの測定なので)"""
    if not isinstance(doc, dict):
        return None
    paths = [doc.get("sourcePath")] + [r.get("from") for r in doc.get("relinks") or [] if isinstance(r, dict)]
    best, seen = None, set()
    for p in paths:
        if not isinstance(p, str) or not p or p in seen:
            continue
        seen.add(p)
        d = txindex.pack_dir(p)
        rec = read_json(os.path.join(txindex.packs_dir(env), txindex.pack_key(d)), None, MAX_PACK_RECORD_BYTES)
        if not isinstance(rec, dict) or rec.get("schema") != txindex.PACK_RECORD_SCHEMA or txindex.norm(rec.get("dir")) != txindex.norm(d):
            continue
        if pack_final(rec) is None:
            continue
        if best is None or (ms_of(rec.get("builtAt")) or 0) > (ms_of(best.get("builtAt")) or 0):
            best = rec
    return best


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


def pct(x):
    return "  -  " if x is None else "%4.0f%%" % (x * 100)


def rate(c, n):
    return round(c / n, 4) if n else None


def dist(values):
    """数のそろいの分布 -> {"n", "min", "p25", "median", "p75", "max", "mean"}(空なら n だけ)"""
    v = sorted(x for x in values if x is not None)
    if not v:
        return {"n": 0}

    def q(p):
        k = (len(v) - 1) * p
        lo = int(k)
        hi = min(lo + 1, len(v) - 1)
        return round(v[lo] + (v[hi] - v[lo]) * (k - lo), 3)
    return {"n": len(v), "min": round(v[0], 3), "p25": q(0.25), "median": q(0.5), "p75": q(0.75), "max": round(v[-1], 3), "mean": round(sum(v) / len(v), 3)}


def _d(x, key="median"):
    return "-" if not x.get("n") else "%s" % x.get(key)


# ---------------------------------------------------------------- 区間の突き合わせ

def clean(iv):
    """区間を時刻の順にそろえ、重なる・接する区間は1つにする(1つの区間が複数に分かれて見えて「形を変えた」と数えないため)"""
    out = []
    for a, b in sorted((a, b) for a, b in iv if b > a):
        if out and a <= out[-1][1] + EPS:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def compare(D, F, fps):
    """たたき台 D と最終 F(どちらも [(開始秒, 終了秒)])を重なりでつないで比べる。
    -> {"added", "removed", "moved", "reshaped", "same"(区間の塊の数), "diffs"(端のずれ。最終 − たたき台の秒。符号つき), "keptDiff"(残す秒の差)}"""
    D, F = clean(D), clean(F)
    n, m = len(D), len(F)
    parent = list(range(n + m))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    f_ends = [b for _, b in F]
    for i, (a, b) in enumerate(D):
        j = bisect.bisect_right(f_ends, a + EPS)
        while j < m and F[j][0] < b - EPS:
            parent[find(i)] = find(n + j)
            j += 1
    comps = {}
    for k in range(n + m):
        comps.setdefault(find(k), ([], []))[0 if k < n else 1].append(k if k < n else k - n)
    tol = TOL_FRAMES / fps
    res = {"added": 0, "removed": 0, "moved": 0, "reshaped": 0, "same": 0, "diffs": [],
           "keptDiff": round(sum(b - a for a, b in F) - sum(b - a for a, b in D), 3)}
    for ds, fs in comps.values():
        if not fs:
            res["removed"] += 1
        elif not ds:
            res["added"] += 1
        else:
            da, db = D[min(ds)][0], D[max(ds)][1]
            fa, fb = F[min(fs)][0], F[max(fs)][1]
            res["diffs"] += [fa - da, fb - db]
            if len(ds) == 1 and len(fs) == 1:
                res["same" if abs(fa - da) < tol and abs(fb - db) < tol else "moved"] += 1
            else:
                res["reshaped"] += 1
    return res


# ---------------------------------------------------------------- 集計

class Agg:
    """文書の集まりぶんの集計"""

    def __init__(self):
        self.docs = self.untouched = self.from_pack = self.from_edit = 0
        self.counts = {"added": 0, "removed": 0, "moved": 0, "reshaped": 0, "same": 0}
        self.kept, self.draft_sec, self.final_sec = [], [], []
        self.f30, self.own = [], []        # 端のずれ(コマ。符号つき): 30fps で数えたもの / 30fps でない文書のその fps で数えたもの
        self.other_fps_docs = 0

    def add(self, r):
        self.docs += 1
        self.from_pack += r["finalFrom"] == "pack"
        self.from_edit += r["finalFrom"] == "edit"
        for k in self.counts:
            self.counts[k] += r["counts"][k]
        self.untouched += r["untouched"]
        self.kept.append(r["keptDiff"])
        self.draft_sec.append(r["draftSec"])
        self.final_sec.append(r["finalSec"])
        self.f30 += [x * BASE_FPS for x in r["diffs"]]
        if abs(r["fps"] - BASE_FPS) > 1e-6:
            self.other_fps_docs += 1
            self.own += [x * r["fps"] for x in r["diffs"]]

    @staticmethod
    def edges(frames):
        a = [abs(x) for x in frames]
        return {"n": len(frames), "signed": dist(frames), "abs": dist(a), "sameRate": rate(sum(1 for x in a if x < TOL_FRAMES), len(a)),
                "bigRate": rate(sum(1 for x in a if x >= BIG_FRAMES), len(a))}

    def result(self):
        fixes = sum(self.counts[k] for k in ("added", "removed", "moved", "reshaped"))
        return {"docs": self.docs, "fromPack": self.from_pack, "fromEdit": self.from_edit, "untouched": self.untouched, "untouchedRate": rate(self.untouched, self.docs),
                "intervals": self.counts, "fixes": fixes, "fixesPerDoc": round(fixes / self.docs, 2) if self.docs else None,
                "keptDiffSec": dist(self.kept), "longer": sum(1 for x in self.kept if x > 0.0005), "shorter": sum(1 for x in self.kept if x < -0.0005),
                "draftSec": dist(self.draft_sec), "finalSec": dist(self.final_sec),
                "edges30": self.edges(self.f30), "otherFpsDocs": self.other_fps_docs, "edgesOwnFps": self.edges(self.own) if self.own else None}


def fmt_val(x):
    return "%g" % x if isinstance(x, float) else str(x)


def sig_of(settings):
    return " ".join("%s=%s" % (k, fmt_val(settings[k])) for k in sorted(settings)) or "(設定なし)"


# ---------------------------------------------------------------- 全体

def evaluate(data_dir=None, since=None, until=None):
    root = locate(data_dir)
    env = env_for(data_dir)
    tdir = os.path.join(root, "transcripts")
    since_ms = day_ms(since) if since else None
    until_ms = day_ms(until, end=True) if until else None
    total, by_origin, by_sig, by_key, by_doc = Agg(), {}, {}, {}, []
    skipped = {"broken": 0, "noDraft": 0, "outOfRange": 0}
    for name in sorted(os.listdir(tdir)) if os.path.isdir(tdir) else []:
        m = EDIT_RE.match(name)
        if not m:
            continue
        tid = m.group(1)
        ed = read_edit(os.path.join(tdir, name))
        if ed is None:
            skipped["broken"] += 1
            continue
        dr = ed["draft"]
        t = dr["at"] if dr and dr["at"] else ed["updatedAt"]
        if (since_ms is not None and t < since_ms) or (until_ms is not None and t >= until_ms):
            skipped["outOfRange"] += 1
            continue
        if dr is None:
            skipped["noDraft"] += 1
            continue
        doc = read_json(os.path.join(tdir, tid + ".json"), None, MAX_DOC_BYTES)
        rec = find_pack(doc, env)
        # 最終 = パックの記録(cutPlan)と保存したカット(clips)のうち新しい方(パックを作ったあとにカットを直したら、直した方が人の最終)
        use_pack = bool(rec) and (ms_of(rec.get("builtAt")) or 0) >= ed["updatedAt"]
        final, src = (pack_final(rec), "pack") if use_pack else (ed["clips"], "edit")
        res = compare(dr["keeps"], final, ed["fps"])
        counts = {k: res[k] for k in ("added", "removed", "moved", "reshaped", "same")}
        row = {"id": tid, "title": str((doc or {}).get("title") or "")[:40] if isinstance(doc, dict) else "", "origin": dr["origin"], "settings": dr["settings"],
               "finalFrom": src, "fps": round(ed["fps"], 4), "counts": counts, "diffs": res["diffs"], "keptDiff": res["keptDiff"],
               "untouched": counts["added"] + counts["removed"] + counts["moved"] + counts["reshaped"] == 0,
               "draftSec": round(sum(b - a for a, b in clean(dr["keeps"])), 3), "finalSec": round(sum(b - a for a, b in clean(final)), 3)}
        total.add(row)
        by_origin.setdefault(dr["origin"], Agg()).add(row)
        by_sig.setdefault(dr["origin"], {}).setdefault(sig_of(dr["settings"]), Agg()).add(row)
        for k, v in dr["settings"].items():
            by_key.setdefault(dr["origin"], {}).setdefault("%s=%s" % (k, fmt_val(v)), Agg()).add(row)
        by_doc.append({k: row[k] for k in ("id", "title", "origin", "finalFrom", "fps", "counts", "keptDiff", "untouched")})
    few = total.from_pack < FEW_PACKS
    notes = []
    if skipped["noDraft"]:
        notes.append("たたき台の記録(draft)が無い edit.json が %d 件あります(記録を入れる前に保存したもの。測っていません)" % skipped["noDraft"])
    if skipped["broken"]:
        notes.append("読めない edit.json が %d 件あります" % skipped["broken"])
    if total.from_edit:
        notes.append("最終が保存したカット(パックが無い・パックより後にカットを直した。途中かもしれない)の文書が %d 件あります" % total.from_edit)
    notes.append("人はたたき台につられる(迷うと直さずに通す)ので、直さなかった割合は甘く出ます")
    meta = {"schema": SCHEMA, "at": int(time.time() * 1000), "since": since, "until": until, "git": git_rev(), "dataDir": root,
            "docs": total.docs, "fromPack": total.from_pack, "fromEdit": total.from_edit, "few": few,
            "fewNote": "まだ少ない(参考): 最終がパックの文書が %d 本(%d 本未満)。これで余白・しきい値の既定を決めない" % (total.from_pack, FEW_PACKS) if few else "",
            "skipped": skipped, "tolFrames": TOL_FRAMES, "bigFrames": BIG_FRAMES, "notes": notes}
    return {"meta": meta, "total": total.result(),
            "byOrigin": {k: v.result() for k, v in sorted(by_origin.items())},
            "bySettings": {o: {k: a.result() for k, a in sorted(g.items())} for o, g in sorted(by_sig.items())},
            "bySetting": {o: {k: a.result() for k, a in sorted(g.items())} for o, g in sorted(by_key.items())},
            "byDoc": by_doc}


def git_rev():
    try:
        return subprocess.run(["git", "-C", TOP, "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


# ---------------------------------------------------------------- 表示・保存

def print_agg(title, r, indent="  "):
    print("%s[%s]  文書 %d 件(最終: パック %d・保存したカット %d)" % (indent, title, r["docs"], r["fromPack"], r["fromEdit"]))
    if not r["docs"]:
        return
    iv = r["intervals"]
    print("%s  まったく直さなかった文書 %d(%s)  直した区間 %d(足した %d・消した %d・端を動かした %d・形を変えた %d)  そのまま %d  1文書あたり %s"
          % (indent, r["untouched"], pct(r["untouchedRate"]).strip(), r["fixes"], iv["added"], iv["removed"], iv["moved"], iv["reshaped"], iv["same"], r["fixesPerDoc"]))
    k = r["keptDiffSec"]
    print("%s  残す秒の差(最終 − たたき台): 中央値 %s 秒・平均 %s 秒(最小 %s・最大 %s)  長くなった %d・短くなった %d  たたき台 %s 秒 → 最終 %s 秒(中央値)"
          % (indent, _d(k), _d(k, "mean"), _d(k, "min"), _d(k, "max"), r["longer"], r["shorter"], _d(r["draftSec"]), _d(r["finalSec"])))
    for label, e in (("30fps", r["edges30"]), ("素材の fps", r["edgesOwnFps"])):
        if not e or not e["n"]:
            continue
        print("%s  端のずれ(%s のコマ。最終 − たたき台)%d 端: 中央値 %s・平均 %s(25%% %s・75%% %s・最小 %s・最大 %s)  絶対値の中央値 %s・平均 %s  そのまま %s・%d コマ以上 %s"
              % (indent, label, e["n"], _d(e["signed"]), _d(e["signed"], "mean"), _d(e["signed"], "p25"), _d(e["signed"], "p75"), _d(e["signed"], "min"), _d(e["signed"], "max"),
                 _d(e["abs"]), _d(e["abs"], "mean"), pct(e["sameRate"]).strip(), BIG_FRAMES, pct(e["bigRate"]).strip()))
    if r["otherFpsDocs"]:
        print("%s  (素材が 30fps でない文書 %d 件)" % (indent, r["otherFpsDocs"]))


def print_groups(title, groups, indent="    ", limit=12):
    items = sorted(groups.items(), key=lambda kv: -kv[1]["docs"])
    print("%s%s" % (indent, title))
    for k, r in items[:limit]:
        e = r["edges30"]
        print("%s  %-44s 文書 %3d  直さず %s  直した区間/文書 %s  残す秒の差 中央値 %s  端の絶対値 中央値 %s コマ・そのまま %s"
              % (indent, k, r["docs"], pct(r["untouchedRate"]).strip(), r["fixesPerDoc"], _d(r["keptDiffSec"]), _d(e["abs"]), pct(e["sameRate"]).strip()))
    if len(items) > limit:
        print("%s  …ほか %d 組(--json で全部)" % (indent, len(items) - limit))


def print_report(res):
    m = res["meta"]
    rng = "%s 〜 %s" % (m["since"] or "最初", m["until"] or "今") if (m["since"] or m["until"]) else "全期間"
    print("カットのたたき台と最終の差の測定(%s)  文書 %d 件(最終: パック %d・保存したカット %d)  作業データ: %s" % (rng, m["docs"], m["fromPack"], m["fromEdit"], m["dataDir"]))
    if m["fewNote"]:
        print("★ " + m["fewNote"])
    if not m["docs"]:
        print("(測れる文書がありません。たたき台の記録(draft)つきでカットを保存した文書が貯まると測れます。たたき台の記録なし %d 件)" % m["skipped"]["noDraft"])
    else:
        print_agg("全部", res["total"])
        for o, r in res["byOrigin"].items():
            print()
            print_agg("たたき台 = %s(%s)" % (ORIGIN_LABELS.get(o, o), o), r)
            if len(res["bySettings"].get(o, {})) > 0:
                print_groups("設定の組み合わせごと:", res["bySettings"][o])
            if len(res["bySetting"].get(o, {})) > 0:
                print_groups("設定の値ごと:", res["bySetting"][o])
        print("\n  [文書ごと(直した区間が多い順に10件)]")
        for d in sorted(res["byDoc"], key=lambda d: (-sum(d["counts"][k] for k in ("added", "removed", "moved", "reshaped")), d["id"]))[:10]:
            c = d["counts"]
            print("    %s %-10s 足 %d・消 %d・動 %d・形 %d・そのまま %d  残す秒の差 %+.2f  最終 %s  %s" % (d["id"], d["origin"], c["added"], c["removed"], c["moved"], c["reshaped"], c["same"],
                                                                                         d["keptDiff"], "パック" if d["finalFrom"] == "pack" else "保存", d["title"]))
    for n in m["notes"]:
        print("注意: " + n)


def save(res, root):
    d = os.path.join(root, "evals", "cut")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "%s.json" % datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return path


def main(argv=None):
    p = argparse.ArgumentParser(description="カットのたたき台と人の最終の差を測る(作業データは読むだけ)")
    p.add_argument("--since", help="この日(YYYY-MM-DD)以後だけ(たたき台を作った時刻 draft.at、無ければ edit.json の更新時刻)")
    p.add_argument("--until", help="この日(YYYY-MM-DD。この日を含む)までだけ")
    p.add_argument("--json", action="store_true", help="同じ形の JSON を 文字起こしの作業データの evals/cut/<日時>.json に残す")
    p.add_argument("--data-dir", help="作業データの親フォルダ(既定 %%LOCALAPPDATA%%\\youtube-tools。テスト用)")
    args = p.parse_args(argv)
    res = evaluate(args.data_dir, args.since, args.until)
    print_report(res)
    if args.json:
        print("\n保存: " + save(res, res["meta"]["dataDir"]))
    return res


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    main()
