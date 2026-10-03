#!/usr/bin/env python3
"""話者の判別(と覚えた声の照合)の当たり具合を、人が直した最終で測る道具(線 B の話者の評価。docs/plan/master-plan-2026-10.md の Q3・I-2a)。

    python dev/eval_speakers.py [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--json] [--data-dir 作業データの親フォルダ] [--no-eval] [--include-draft]

- 作業データは**読むだけ**(transcribe の transcripts/<id>.json と <id>.diar.json)。何も書き換えない。--json のときだけ、結果を
  文字起こしの作業データの evals\\speakers\\<日時>.json に残す(evals の置き場所は eval_asr.py(evals\\asr)・eval_marks.py と同じ「ツールの作業データの下の evals\\<領域>」)。
- 人の最終 = 文書の行の speaker(id)→ speakers[].name。機械 = <id>.diar.json の latest(rows[行 id].speaker = その回の S1/S2…・voices = 声の照合)。
  行 id で突き合わせる(人が分けた・つないだ行は新しい id で、機械の記録が無い = 「記録なし」として別に数える)。
- **仮の名前(話者1・話者2…)のままの行は既定で測らない**(人が確かめていない機械の下書きそのままで、測ると甘く出る。--include-draft で入れる)。
  声の照合が付けた名前を人が直さなかった行は区別できない(下書きへのつられ = 計画の 8)。「校正済みの行だけ」の数も並べて見る
- 指標(行の集まり = 話者つきの行 / 校正済みの行だけ / 人が時刻を直した行だけ。どれも同じ書き方で数える):
    行ごとの正しさ: 文書ごとに、機械のラベル(S1/S2…)と人の名前を1対1で最もよく対応させる(ハンガリア法。行数で重み。分けすぎた話者は対応できず間違いになる)→
      合っている行 ÷ 行(人が話者を付けていない行は入れない。機械が付けなかった行は間違いに数え、数も別に出す)。声が混ざっている(mixed)行・不確か(weak)行・それ以外で別に出す
    声の照合: decided(しきい値か消去法で付いた名前)が、その機械の話者の行に人が付けた名前(多い方)と同じ割合 / 付けなかった話者の理由の内訳 /
      正しかった名前・間違った名前の点数と2位との差の分布 / 付けなかったが、1位が人の名前だった(しきい値で取りこぼした)数 /
      しきい値(点数・差)を変えたら決まる数・正しい数がどう変わるかの表(記録された点数と差からの計算。VOICE_MATCH 0.60・VOICE_MARGIN 0.08 の見直しの材料)
    話者の数: 機械の数 − 人の数(文書ごと)の分布と、ちょうど当たった割合
    判別の回(履歴を含む)ごとの行の正しさ: エンジン・埋め込み・クラスタのしきい値ごとにまとめる(設定を変えた前後の比較)
- 人が時刻を直した行 = original(機械の出力。行の id が無いので時刻で突き合わせる)のどの行とも、始まりと終わりが 0.05 秒以内で一致しない行。
  行を分けた・つないだ行も入る。original が無い文書の行は分からないので入れない
- --since / --until(原則 4: 時期で分ける)は行の時刻で絞る(until はその日を含む)。行の時刻 = 校正した時刻 proofedAt(あれば)、無ければ文書の更新時刻 updatedAt
  (proofedAt を作る前に校正済みになった行は時刻が無いので更新時刻になる)。
- 話者つきの行が 200 未満のときは「まだ少ない(参考)」と出す(少ないデータで決めすぎない)。評価用(evalSet)の文書は既定で含める(--no-eval で外す)
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
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)
from ytt_core import datadir  # noqa: E402

SCHEMA = "youtube-tools-speakers-eval/v1"
DIAR_SCHEMA = "youtube-tools-diar/v1"     # editor/ed_speakers.py の DIAR_SCHEMA と同じ(editor は読み込まない)
FEW_ROWS = 200                            # 話者つきの行がこれより少ないときは「まだ少ない(参考)」
TIME_TOL = 0.05                           # original と行の端が一致したとみなす秒
MAX_DIAR_BYTES = 32 * 1024 * 1024
DRAFT_NAME = re.compile(r"^話者\d+$")     # editor/ed_speakers.py の DEFAULT_SPK_NAME(話者判別が付けた仮の名前)と同じ
DOC_RE = re.compile(r"^[0-9a-f]{12}\.json\Z")
SUBSETS = (("all", "話者つきの行"), ("proofed", "校正済みの行だけ"), ("timeEdited", "人が時刻を直した行だけ"))
SWEEP_MATCH = (0.40, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80)
SWEEP_MARGIN = (0.0, 0.04, 0.08, 0.12)
REASONS = {"no_feature": "特徴が取れない", "no_voices": "比べる声が無い", "below_match": "しきい値に届かない", "margin": "2位との差が足りない",
           "name_taken": "同じ名前を別の人が先に取った", "already_named": "人が先に名前を付けていた", "name_in_use": "その名前を別の人が使っている", "no_rows": "行が無い"}


# ---------------------------------------------------------------- 読み込み(読むだけ)

def read_json(path, default=None, limit=None):
    try:
        if limit and os.path.getsize(path) > limit:
            return default
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def locate(data_dir=None):
    """-> 文字起こしの作業データのフォルダ。置き場所の規則は ytt_core.datadir の1か所。
    data_dir を渡したとき(テスト)は、そこを全ツールの作業データの親フォルダとして使う(<data_dir>/transcribe)"""
    env = {"YTT_DATA_DIR": os.path.abspath(data_dir)} if data_dir else None
    return datadir.locate("transcribe", REPO, env)


def read_diar(tdir, tid):
    d = read_json(os.path.join(tdir, tid + ".diar.json"), None, MAX_DIAR_BYTES)
    if not isinstance(d, dict) or d.get("schema") != DIAR_SCHEMA or not isinstance(d.get("latest"), dict):
        return None
    return d


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


def num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


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


def norm_name(s):
    return unicodedata.normalize("NFKC", str(s or "")).strip().casefold()


def hungarian_max(w):
    """重みの表 w(行 × 列)を、1行に1列まで・1列に1行までで、合計がいちばん大きくなるように対応させる -> {行: 列}(重み 0 の対応は除く)"""
    n_r = len(w)
    n_c = len(w[0]) if w else 0
    n = max(n_r, n_c)
    if not n:
        return {}
    cost = [[0] * (n + 1) for _ in range(n + 1)]
    for i in range(n_r):
        for j in range(n_c):
            cost[i + 1][j + 1] = -w[i][j]
    INF = float("inf")
    u, v, p, way = [0] * (n + 1), [0] * (n + 1), [0] * (n + 1), [0] * (n + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], INF, 0
            for j in range(1, n + 1):
                if not used[j]:
                    cur = cost[i0][j] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if not j0:
                break
    out = {}
    for j in range(1, n + 1):
        i = p[j] - 1
        if 0 <= i < n_r and j - 1 < n_c and w[i][j - 1] > 0:
            out[i] = j - 1
    return out


def best_mapping(rows):
    """rows の (機械のラベル, 人の名前) の組を数えて、ラベル → 名前の1対1の対応(合う行が最大になるもの)を返す。機械のラベルが空の行は数えない"""
    cnt = {}
    for r in rows:
        if r["label"]:
            cnt[(r["label"], r["human"])] = cnt.get((r["label"], r["human"]), 0) + 1
    labels = sorted({k[0] for k in cnt})
    names = sorted({k[1] for k in cnt})
    pairs = hungarian_max([[cnt.get((lb, nm), 0) for nm in names] for lb in labels])
    return {labels[i]: names[j] for i, j in pairs.items()}


# ---------------------------------------------------------------- 1つの文書

def time_edited_flags(doc, rows):
    """行ごとに「人が時刻を直した」か。original が無ければ None(分からない)"""
    orig = sorted((num(o.get("start")), num(o.get("end"))) for o in (doc.get("original") or []) if isinstance(o, dict)
                  and num(o.get("start")) is not None and num(o.get("end")) is not None)
    if not orig:
        return [None] * len(rows)
    starts = [o[0] for o in orig]
    out = []
    for r in rows:
        a, b = r["start"], r["end"]
        k = bisect.bisect_left(starts, a - TIME_TOL)
        same = False
        while k < len(orig) and orig[k][0] <= a + TIME_TOL:
            if abs(orig[k][1] - b) <= TIME_TOL:
                same = True
                break
            k += 1
        out.append(not same)
    return out


def human_rows(doc, runrows, since_ms, until_ms, include_draft):
    """人の最終の話者がある行 -> ([{id, start, end, human, label, mixed, weak, proofed, edited}], 仮の名前のままで除いた行の数, 機械の記録が無い行の数)。
    runrows = 判別の記録の rows(行 id → {label, speaker, mixed, weak})。label は「機械がその回に付けた S1/S2…」(付けなかった行は空)"""
    names = {s.get("id"): str(s.get("name") or "") for s in doc.get("speakers") or [] if isinstance(s, dict)}
    doc_t = num(doc.get("updatedAt")) or 0
    out, drafts, norec, base = [], 0, 0, []
    for sg in doc.get("segments") or []:
        if not isinstance(sg, dict):
            continue
        name = names.get(sg.get("speaker")) if sg.get("speaker") else None
        a, b = num(sg.get("start")), num(sg.get("end"))
        if not name or a is None or b is None:
            continue
        t = num(sg.get("proofedAt")) or doc_t
        if (since_ms is not None and t < since_ms) or (until_ms is not None and t >= until_ms):
            continue
        if DRAFT_NAME.match(name) and not include_draft:
            drafts += 1
            continue
        base.append((sg, name, a, b))
    edited = time_edited_flags(doc, [{"start": a, "end": b} for _, _, a, b in base])
    for (sg, name, a, b), ed in zip(base, edited):
        rec = runrows.get(str(sg.get("id")))
        if not isinstance(rec, dict):
            norec += 1
            continue
        out.append({"id": sg.get("id"), "start": a, "end": b, "human": name, "label": str(rec.get("speaker") or ""), "mixed": bool(rec.get("mixed")),
                    "weak": bool(rec.get("weak")), "proofed": sg.get("proofed") is True, "edited": ed})
    return out, drafts, norec


def new_counts():
    return {"rows": 0, "correct": 0, "unassigned": 0, "plain": [0, 0], "weak": [0, 0], "mixed": [0, 0]}


def add_counts(total, rows, mapping):
    """rows を mapping(機械のラベル → 人の名前)で採点して total に足す。mixed(声が混ざっている)・weak(不確か。mixed でないもの)・plain(それ以外)に分けて数える"""
    for r in rows:
        ok = bool(r["label"]) and mapping.get(r["label"]) == r["human"]
        total["rows"] += 1
        total["correct"] += ok
        if not r["label"]:
            total["unassigned"] += 1
        k = "mixed" if r["mixed"] else "weak" if r["weak"] else "plain"
        total[k][0] += 1
        total[k][1] += ok


def finish_counts(c):
    return {"rows": c["rows"], "correct": c["correct"], "rate": rate(c["correct"], c["rows"]), "unassigned": c["unassigned"],
            "plain": {"rows": c["plain"][0], "correct": c["plain"][1], "rate": rate(c["plain"][1], c["plain"][0])},
            "weak": {"rows": c["weak"][0], "correct": c["weak"][1], "rate": rate(c["weak"][1], c["weak"][0])},
            "mixed": {"rows": c["mixed"][0], "correct": c["mixed"][1], "rate": rate(c["mixed"][1], c["mixed"][0])}}


def majority_name(rows):
    """その機械の話者の行に人が付けた名前(多い方)。同数なら None(決められない)"""
    cnt = {}
    for r in rows:
        cnt[r["human"]] = cnt.get(r["human"], 0) + 1
    if not cnt:
        return None
    ranked = sorted(cnt.items(), key=lambda kv: -kv[1])
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None
    return ranked[0][0]


def voice_records(run, rows):
    """最新の回の声の照合 -> [{"label", "info", "human"(人が付けた名前。行が無い・決められないなら None), "rows"}]。単独指定(by=request)は測らない"""
    vs = (run.get("voices") or {}).get("speakers") if (run.get("voices") or {}).get("checked") else None
    out = []
    for sid, info in sorted((vs or {}).items()):
        if not isinstance(info, dict) or info.get("by") == "request":
            continue
        mine = [r for r in rows if r["label"] == sid]
        out.append({"label": sid, "info": info, "human": majority_name(mine), "rows": len(mine)})
    return out


class Voices:
    """声の照合の集計(1つの行の集まりぶん)"""

    def __init__(self):
        self.decided = self.unverified = 0
        self.correct, self.wrong = [], []             # (点数 or None, 2位との差 or None)
        self.undecided = {}                            # 理由 -> 数
        self.missed = []                               # 付けなかったが1位が人の名前だった: (点数, 理由)
        self.checked = []                              # しきい値の表の元: (点数, 2位の点数 or None, 1位の名前, 人の名前)

    def add(self, recs):
        for v in recs:
            i, human = v["info"], v["human"]
            top, score, second = i.get("top"), num(i.get("score")), num(i.get("secondScore"))
            if human is not None and score is not None and top:
                self.checked.append((score, second, top, human))
            if i.get("decided"):
                if human is None:
                    self.unverified += 1
                    continue
                self.decided += 1
                ok = norm_name(i["decided"]) == norm_name(human)
                (self.correct if ok else self.wrong).append((score, None if score is None or second is None else round(score - second, 3), i.get("by")))
            else:
                self.undecided[i.get("reason") or "unknown"] = self.undecided.get(i.get("reason") or "unknown", 0) + 1
                if human is not None and top and norm_name(top) == norm_name(human):
                    self.missed.append((score, i.get("reason")))

    def result(self):
        scores = lambda xs: dist([x[0] for x in xs])      # noqa: E731
        margins = lambda xs: dist([x[1] for x in xs])     # noqa: E731
        sweep = []
        for m in SWEEP_MATCH:
            for g in SWEEP_MARGIN:
                dec = cor = 0
                for score, second, top, human in self.checked:
                    if score >= m and (second is None or score - second >= g):
                        dec += 1
                        cor += norm_name(top) == norm_name(human)
                sweep.append({"match": m, "margin": g, "decided": dec, "correct": cor, "wrong": dec - cor, "precision": rate(cor, dec)})
        return {"decided": self.decided, "correct": len(self.correct), "wrong": len(self.wrong), "rate": rate(len(self.correct), self.decided),
                "unverified": self.unverified, "undecided": dict(sorted(self.undecided.items())), "undecidedTotal": sum(self.undecided.values()),
                "missed": {"n": len(self.missed), "score": dist([x[0] for x in self.missed]), "byReason": _count([x[1] for x in self.missed])},
                "correctScore": scores(self.correct), "wrongScore": scores(self.wrong), "correctMargin": margins(self.correct), "wrongMargin": margins(self.wrong),
                "sweep": sweep}


def _count(xs):
    out = {}
    for x in xs:
        out[str(x)] = out.get(str(x), 0) + 1
    return dict(sorted(out.items()))


def engine_key(run):
    e = run.get("engine") if isinstance(run.get("engine"), dict) else {}
    return "%s / %s / クラスタ %s / 人数 %s" % (e.get("name", "?"), e.get("embedding") or "-", e.get("clusterThreshold", "-"), e.get("requested", "-"))


def is_single(run):
    return (run.get("engine") or {}).get("name") == "single" if isinstance(run.get("engine"), dict) else False


# ---------------------------------------------------------------- 全体

def evaluate(data_dir=None, since=None, until=None, include_eval=True, include_draft=False):
    tdir_root = locate(data_dir)
    tdir = os.path.join(tdir_root, "transcripts")
    since_ms = day_ms(since) if since else None
    until_ms = day_ms(until, end=True) if until else None
    subs = {k: {"counts": new_counts(), "voices": Voices()} for k, _ in SUBSETS}
    engines, by_doc = {}, []
    diffs = []
    skipped = {"noDiar": 0, "single": 0, "noRows": 0, "evalSet": 0, "broken": 0}
    totals = {"docs": 0, "drafts": 0, "noRecord": 0, "evalDocs": 0}
    for name in sorted(os.listdir(tdir)) if os.path.isdir(tdir) else []:
        if not DOC_RE.match(name):
            continue
        tid = name[:-5]
        doc = read_json(os.path.join(tdir, name))
        if not isinstance(doc, dict):
            skipped["broken"] += 1
            continue
        if doc.get("evalSet") is True and not include_eval:
            skipped["evalSet"] += 1
            continue
        diar = read_diar(tdir, tid)
        if not diar:
            skipped["noDiar"] += 1
            continue
        run = diar["latest"]
        if is_single(run):
            skipped["single"] += 1
            continue
        runrows = run.get("rows") if isinstance(run.get("rows"), dict) else {}
        rows, drafts, norec = human_rows(doc, runrows, since_ms, until_ms, include_draft)
        totals["drafts"] += drafts
        totals["noRecord"] += norec
        if not rows:
            skipped["noRows"] += 1
            continue
        totals["docs"] += 1
        totals["evalDocs"] += doc.get("evalSet") is True
        mapping = best_mapping(rows)
        picks = {"all": rows, "proofed": [r for r in rows if r["proofed"]], "timeEdited": [r for r in rows if r["edited"] is True]}
        for k, sel in picks.items():
            add_counts(subs[k]["counts"], sel, mapping)
            subs[k]["voices"].add(voice_records(run, sel))
        one = new_counts()
        add_counts(one, rows, mapping)
        m_cnt = num(run.get("speakers"))
        machine = int(m_cnt) if m_cnt is not None else len({r["label"] for r in rows if r["label"]})
        human = len({r["human"] for r in rows})
        diffs.append(machine - human)
        by_doc.append({"id": tid, "title": str(doc.get("title") or "")[:40], "evalSet": doc.get("evalSet") is True, "engine": engine_key(run),
                       "machineSpeakers": machine, "humanSpeakers": human, "rows": one["rows"], "correct": one["correct"], "rate": rate(one["correct"], one["rows"])})
        # 判別の回ごと(最新 + 履歴): その回の rows を、その回自身の対応で採点する(行の id が消えた回は、残っている行だけ)
        for r_ in [run] + [h for h in diar.get("history") or [] if isinstance(h, dict)]:
            if is_single(r_) or not isinstance(r_.get("rows"), dict):
                continue
            hr, _, _ = human_rows(doc, r_["rows"], since_ms, until_ms, include_draft)
            if not hr:
                continue
            c = new_counts()
            add_counts(c, hr, best_mapping(hr))
            e = engines.setdefault(engine_key(r_), {"runs": 0, "docs": set(), "counts": new_counts()})
            e["runs"] += 1
            e["docs"].add(tid)
            for k in ("rows", "correct", "unassigned"):
                e["counts"][k] += c[k]
    nrows = subs["all"]["counts"]["rows"]
    few = nrows < FEW_ROWS
    notes = []
    if totals["drafts"]:
        notes.append("仮の名前(話者1…)のままの行 %d 行は測っていません(人が確かめていない下書き。--include-draft で入れる)" % totals["drafts"])
    if totals["noRecord"]:
        notes.append("機械の記録が無い行(判別のあとに分けた・つないだ行)%d 行は測っていません" % totals["noRecord"])
    if skipped["noDiar"]:
        notes.append("判別の記録(.diar.json)が無い文書が %d 件あります(記録を入れる前に判別したもの)" % skipped["noDiar"])
    if skipped["single"]:
        notes.append("「話す人が1人」の指定の文書が %d 件あります(機械の判別ではないので測っていません)" % skipped["single"])
    notes.append("声の照合が付けた名前を人が直さなかった行は、機械の下書きのままと区別できないので甘く出ます(校正済みの行だけの数も見る)")
    dc = {}
    for d in diffs:
        dc[str(d)] = dc.get(str(d), 0) + 1
    meta = {"schema": SCHEMA, "at": int(time.time() * 1000), "since": since, "until": until, "includeEval": bool(include_eval), "includeDraft": bool(include_draft),
            "git": git_rev(), "dataDir": tdir_root, "docs": totals["docs"], "evalDocs": totals["evalDocs"], "rows": nrows, "few": few,
            "fewNote": "まだ少ない(参考): 話者つきの行が %d 行(%d 行未満)。これで既定値(しきい値 0.60・差 0.08 など)を決めない" % (nrows, FEW_ROWS) if few else "",
            "skipped": skipped, "draftRows": totals["drafts"], "noRecordRows": totals["noRecord"], "notes": notes}
    return {"meta": meta,
            "subsets": {k: dict(finish_counts(v["counts"]), voices=v["voices"].result()) for k, v in subs.items()},
            "speakerCount": {"docs": len(diffs), "exact": dc.get("0", 0), "exactRate": rate(dc.get("0", 0), len(diffs)), "diff": dict(sorted(dc.items(), key=lambda kv: int(kv[0]))),
                             "meanDiff": round(sum(diffs) / len(diffs), 2) if diffs else None, "over": sum(1 for d in diffs if d > 0), "under": sum(1 for d in diffs if d < 0)},
            "byEngine": {k: {"runs": v["runs"], "docs": len(v["docs"]), "rows": v["counts"]["rows"], "correct": v["counts"]["correct"],
                             "rate": rate(v["counts"]["correct"], v["counts"]["rows"]), "unassigned": v["counts"]["unassigned"]} for k, v in sorted(engines.items())},
            "byDoc": by_doc}


def git_rev():
    try:
        return subprocess.run(["git", "-C", REPO, "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


# ---------------------------------------------------------------- 表示・保存

def _d(x, key="median"):
    return "-" if not x.get("n") else "%s" % x.get(key)


def print_subset(title, s):
    print("  [%s]  %d 行" % (title, s["rows"]))
    if not s["rows"]:
        return
    print("    行ごとの正しさ %s(%d / %d)  機械が付けなかった行 %d" % (pct(s["rate"]).strip(), s["correct"], s["rows"], s["unassigned"]))
    for k, label in (("plain", "ふつうの行"), ("weak", "不確か(weak)の行"), ("mixed", "声が混ざる(mixed)の行")):
        g = s[k]
        print("      %-18s %5d 行  正しさ %s" % (label, g["rows"], pct(g["rate"]).strip()))
    v = s["voices"]
    if not (v["decided"] or v["undecidedTotal"] or v["unverified"]):
        return
    print("    声の照合: 付いた名前 %d(人の最終と同じ %d・違う %d → %s)・確かめられない %d・付けなかった %d"
          % (v["decided"], v["correct"], v["wrong"], pct(v["rate"]).strip(), v["unverified"], v["undecidedTotal"]))
    if v["undecided"]:
        print("      付けなかった理由: " + "・".join("%s %d" % (REASONS.get(k, k), n) for k, n in v["undecided"].items()))
    print("      点数 正しい: 中央値 %s(最小 %s・%d 個) / 間違い: 中央値 %s(最大 %s・%d 個)"
          % (_d(v["correctScore"]), _d(v["correctScore"], "min"), v["correctScore"]["n"], _d(v["wrongScore"]), _d(v["wrongScore"], "max"), v["wrongScore"]["n"]))
    print("      2位との差 正しい: 中央値 %s(最小 %s) / 間違い: 中央値 %s(最大 %s)" % (_d(v["correctMargin"]), _d(v["correctMargin"], "min"), _d(v["wrongMargin"]), _d(v["wrongMargin"], "max")))
    print("      取りこぼし(付けなかったが1位が人の名前だった): %d 個%s" % (v["missed"]["n"], "  点数 中央値 %s" % _d(v["missed"]["score"]) if v["missed"]["n"] else ""))
    if v["sweep"] and any(x["decided"] for x in v["sweep"]):
        print("      しきい値を変えたら(決まる数 / 正しい数。記録の点数と差からの計算):")
        print("        点数\\差 " + "".join("%12s" % ("差 %.2f" % g) for g in SWEEP_MARGIN))
        for m in SWEEP_MATCH:
            cells = [x for x in v["sweep"] if x["match"] == m]
            print("        %.2f    " % m + "".join("%12s" % ("%d / %d" % (c["decided"], c["correct"])) for c in cells))


def print_report(res):
    m = res["meta"]
    rng = "%s 〜 %s" % (m["since"] or "最初", m["until"] or "今") if (m["since"] or m["until"]) else "全期間"
    print("話者の判別の測定(%s)  文書 %d 件(うち評価用 %d)・話者つきの行 %d  作業データ: %s" % (rng, m["docs"], m["evalDocs"], m["rows"], m["dataDir"]))
    if m["fewNote"]:
        print("★ " + m["fewNote"])
    if not m["docs"]:
        print("(測れる文書がありません。話者を判別して名前を付けた文書(.diar.json つき)が貯まると測れます)")
    else:
        for k, label in SUBSETS:
            print_subset(label, res["subsets"][k])
        c = res["speakerCount"]
        print("  [話者の数(機械 − 人)]  文書 %d 件  ちょうど当たり %d(%s)  多すぎ %d・少なすぎ %d  平均 %s  分布 %s"
              % (c["docs"], c["exact"], pct(c["exactRate"]).strip(), c["over"], c["under"], c["meanDiff"], c["diff"]))
        if res["byEngine"]:
            print("  [判別の回ごとの行の正しさ(最新と履歴の全部。設定の比較)]")
            for k, e in res["byEngine"].items():
                print("    %-60s 回 %3d・文書 %3d・行 %6d  正しさ %s" % (k, e["runs"], e["docs"], e["rows"], pct(e["rate"]).strip()))
        print("  [文書ごと(悪い順に10件)]")
        for d in sorted(res["byDoc"], key=lambda d: (d["rate"] if d["rate"] is not None else 2, d["id"]))[:10]:
            print("    %s 機械 %d 人・人 %d 人  行 %4d  正しさ %s%s  %s" % (d["id"], d["machineSpeakers"], d["humanSpeakers"], d["rows"], pct(d["rate"]).strip(),
                                                                    "  [評価用]" if d["evalSet"] else "", d["title"]))
    for n in m["notes"]:
        print("注意: " + n)


def save(res, root):
    d = os.path.join(root, "evals", "speakers")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "%s.json" % datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return path


def main(argv=None):
    p = argparse.ArgumentParser(description="話者の判別と声の照合の当たり具合を、人が直した最終で測る(作業データは読むだけ)")
    p.add_argument("--since", help="この日(YYYY-MM-DD)以後の行だけ(行の校正した時刻 proofedAt、無ければ文書の更新時刻)")
    p.add_argument("--until", help="この日(YYYY-MM-DD。この日を含む)までの行だけ")
    p.add_argument("--json", action="store_true", help="同じ形の JSON を 文字起こしの作業データの evals/speakers/<日時>.json に残す")
    p.add_argument("--data-dir", help="作業データの親フォルダ(既定 %%LOCALAPPDATA%%\\youtube-tools。テスト用)")
    p.add_argument("--no-eval", action="store_true", help="評価用(evalSet)の文書を外す")
    p.add_argument("--include-draft", action="store_true", help="仮の名前(話者1…)のままの行も測る(機械の下書きそのまま = 甘く出る)")
    args = p.parse_args(argv)
    res = evaluate(args.data_dir, args.since, args.until, not args.no_eval, args.include_draft)
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
