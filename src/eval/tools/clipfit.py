#!/usr/bin/env python3
"""自動の区間が友人の区間にどれだけ合うかの物差し(LD-2a。notes:plan/done/ld2-clip-length.md の L-2)。⑤ eval_marks が表示に使い、単独でも動く。

    python src/eval/tools/clipfit.py [--json] [--grid] [--data-dir 作業データの親フォルダ]

- 友人の区間 = 入口の実行記録の ranges(友人が指定したまま。② flow/lengthhint.friend_ranges と同じ読み方)
- 自動の区間 = スタジオの archive/<配信>.json.gz の 1 秒ごとの素材(音量・チャット・コメントの時刻)から合計の点数を解析と同じ式で作り直し
  (保存されている系列は約 10 秒刻みで粗いため)、① excite.pick_clips で区間を選ぶ。形は variants で選ぶ(固定の長さ・場面ごと。本番のスイッチ excite.SHAPE_DEFAULT は見ない)
- 数えるのは、友人の区間の中に自動の候補の山がある物だけ(山を拾えたかは eval_marks の「拾えた率」で別に測る)。その中でいちばん点数の高い候補を当てる
- 覆えた割合 cover = 友人の区間のうち自動の区間に入った秒 ÷ 友人の区間の秒(足りないと Resolve で伸ばせない = 大事なほう)
  余分 extra = 自動の区間のうち友人の区間の外の秒(友人が詰める手間)
- 覚え込みの心配(友人の区間は少ない)があるので、配信を 2 組(配信 ID の順に交互)に分けた数も出す。--grid は場面の形の数を片方の組で選び、もう片方で確かめる
- 端が話にかかっている割合(LD-2c。結果の edges): 文字起こしの作業データの切り抜きの文書(動画まるごと・長さのあるもの)で、始まり・終わりの近く
  (breaks.MIN_GAP 秒)まで声の行がある = 言葉の途中で切れている割合と、パックの段で話の切れ目へ詰めた(pack.snap_base)あとの割合・落とした秒
- 作業データは読むだけ。--json のときだけ結果を スタジオの作業データの evals/marks/<日時>-clipfit.json に残す
"""
import argparse
import glob
import gzip
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(os.path.dirname(HERE))   # tools -> eval -> src
if not __package__:   # スクリプトとして起動したときだけ(見本 eval_marks.py)
    sys.path[:] = [SRC] + [p for p in sys.path if os.path.normcase(os.path.abspath(p or os.curdir)) not in (os.path.normcase(HERE), os.path.normcase(SRC))]
from eval.tools import _evalcommon as C  # noqa: E402
from flow import lengthhint  # noqa: E402  友人の区間の読み方と、長さの目安(固定の長さの基準)
from flow import runlog  # noqa: E402
from pipeline.analyze import breaks, excite  # noqa: E402
from pipeline.pack import pack  # noqa: E402  話の切れ目へ詰める規則(本番と同じ関数)
from ytt import schemas  # noqa: E402  余白つきの切り抜きの印(LD-2f)

SCHEMA = "youtube-tools-clip-fit/v1"
ARCHIVE_MAX = 256 * 1024 * 1024   # archive の 1 本の上限(展開後)
COUNT = 20                        # 選ぶ候補の数(形どうしで同じにする。本番の既定 8 より多め = 友人の区間の中の山を拾いやすく)
BASE_LENGTH, BASE_PRE = 160.0, 0.68   # 長さの目安が出せないときの固定の長さ(10-16 の目安 = 基準の数字を取った値)
GRID = {"rise": (0.1, 0.2, 0.3, 0.5), "settle": (0.1, 0.2, 0.3, 0.5), "lead": (15.0, 30.0, 60.0, 90.0), "tail": (27.0, 45.0, 60.0, 90.0)}


def load_material(studio, vid):
    """archive/<配信>.json.gz -> 1 秒ごとの素材 {"n", "full", "band", "act", "stamps", "spec", "lag", "signals"} か None(無い・壊れた・素材が無い)"""
    if not lengthhint.ARCHIVE_ID_RE.match(vid):
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
    full, band, n = d.get("full") if run else None, d.get("band"), d.get("n")
    if not (isinstance(full, list) and isinstance(band, list) and isinstance(n, int) and n > 0 and full):
        return None
    chat = d.get("chat") if isinstance(d.get("chat"), dict) else {}
    return {"n": n, "full": full, "band": band, "act": chat.get("act") if isinstance(chat.get("act"), list) else None,
            "stamps": d.get("stamps") if isinstance(d.get("stamps"), list) else None,
            "spec": run.get("spec") if isinstance(run.get("spec"), dict) else {}, "lag": run.get("lagUsed"),
            "signals": run.get("signals") if isinstance(run.get("signals"), dict) else {}}


def rebuild(m):
    """素材 -> (合計の点数, 音量 full)(src/pipeline/analyze/analyze.py の run と同じ足し方・同じ順)"""
    n, sp, sig = m["n"], m["spec"], m["signals"]
    full = (list(m["full"]) + [m["full"][-1]] * n)[:n]
    band = (list(m["band"]) + [m["band"][-1]] * n)[:n]
    comps = {}
    if sig.get("audio", True):
        comps["audio"] = excite.audio_score(full, band)
    if sig.get("chat") and m["act"]:
        act = (list(m["act"]) + [0.0] * n)[:n]
        lag = m["lag"] if isinstance(m["lag"], (int, float)) else sp.get("lag", 8)
        comps["chat"] = excite.shift_chat(excite.chat_z(act), lag)
    if sig.get("comments") and m["stamps"]:
        comps["comments"] = excite.comment_score([s[:3] for s in m["stamps"] if isinstance(s, list) and len(s) >= 3], n)
    if not comps:
        return None, full
    wts = {"audio": sp.get("wAudio", 1.0), "chat": sp.get("wChat", 1.0), "comments": sp.get("wComments", 0.7)}
    total = [sum(wts[k] * comps[k][i] for k in comps) for i in range(n)]
    return excite.head_ramp(total, sp.get("headSec", 180)), full


def picks(total, full, m, variant, count=COUNT):
    """1 本の配信の自動の区間(variant = {"shape", "length", "pre", "scene"?})"""
    sp = m["spec"]
    spec = {"length": float(variant.get("length") or BASE_LENGTH), "preRatio": float(variant.get("pre") or BASE_PRE),
            "sensitivity": sp.get("sensitivity") if sp.get("sensitivity") in excite.SENS else "normal", "count": count,
            "shape": variant.get("shape", "fixed"), "scene": variant.get("scene")}
    return excite.pick_clips(total, full, spec, m["n"])


def fit(rng, cands):
    """友人の区間 rng と、その中に山がある自動の候補(いちばん点数の高いもの)-> {"cover", "extra", "length", "shape"} か None(中に山が無い)"""
    a, b = rng
    inside = [c for c in cands if a <= c["peak"] <= b]
    if not inside or b <= a:
        return None
    c = max(inside, key=lambda x: x["score"])
    ov = max(0.0, min(b, c["end"]) - max(a, c["start"]))
    return {"cover": round(ov / (b - a), 4), "extra": round((c["end"] - c["start"]) - ov, 1), "length": round(c["end"] - c["start"], 1),
            "shape": c.get("shape", "fixed"), "start": c["start"], "end": c["end"], "peak": c["peak"]}


def summarize(rows):
    """fit の行(None は「中に山が無い」)-> 数"""
    got = [r for r in rows if r]
    covers = [r["cover"] for r in got]
    out = {"ranges": len(rows), "counted": len(got), "cover": C.dist(covers), "extra": C.dist([r["extra"] for r in got], p90=True),
           "length": C.dist([r["length"] for r in got]), "coverMean": round(sum(covers) / len(covers), 4) if covers else None,
           "fullCover": sum(1 for x in covers if x >= 0.95), "fallback": sum(1 for r in got if r["shape"] != "scene")}
    return out


def default_variants(hint=None):
    """固定の長さ(長さの目安。無ければ BASE_LENGTH)と場面ごと(excite.SCENE の数)"""
    u = lengthhint.usable(hint) or {}
    length, pre = float(u.get("length") or BASE_LENGTH), float(u.get("preRatio") or BASE_PRE)
    return [{"name": "fixed", "shape": "fixed", "length": length, "pre": pre},
            {"name": "scene", "shape": "scene", "length": length, "pre": pre}]


def friend_material(studio, app, records=None):
    """-> [(配信 ID, [友人の区間], 素材, 合計, 音量)](素材の無い配信は素材 None)と、組 {配信 ID: "A" | "B"}"""
    recs = runlog.read_runs_log(os.path.join(app, "logs", runlog.RUNS_LOG)) if records is None else records
    out = []
    for vid, rgs in sorted(lengthhint.friend_ranges(recs).items()):
        m = load_material(studio, vid)
        total, full = rebuild(m) if m else (None, None)
        out.append((vid, sorted(rgs), m if total else None, total, full))
    halves = {vid: "AB"[i % 2] for i, (vid, _r, m, _t, _f) in enumerate([x for x in out if x[2]])}
    return out, halves


def evaluate(studio, app, variants=None, records=None, hint=None, with_edges=True, data_dir=None):
    """-> 結果(形ごとの数・組 A / B の数・区間ごとの行)。作業データは読むだけ"""
    hint = lengthhint.compute(studio, app) if hint is None else hint
    variants = variants or default_variants(hint)
    mats, halves = friend_material(studio, app, records)
    res = {"schema": SCHEMA, "count": COUNT, "variants": [], "edges": edge_speech(C.locate("transcribe", data_dir)) if with_edges else None, "ranges": sum(len(r) for _v, r, *_ in mats),
           "withMaterial": sum(len(r) for _v, r, m, *_ in mats if m), "videos": sum(1 for x in mats if x[2]), "items": []}
    per = {v["name"]: [] for v in variants}
    half = {v["name"]: {"A": [], "B": []} for v in variants}
    for vid, rgs, m, total, full in mats:
        if not m:
            continue
        for v in variants:
            cands = picks(total, full, m, v)
            for rg in rgs:
                f = fit(rg, cands)
                per[v["name"]].append(f)
                half[v["name"]][halves[vid]].append(f)
                res["items"].append({"variant": v["name"], "videoId": vid, "start": rg[0], "end": rg[1], "fit": f})
    for v in variants:
        res["variants"].append(dict({k: v[k] for k in v if k != "name"}, name=v["name"], all=summarize(per[v["name"]]),
                                    A=summarize(half[v["name"]]["A"]), B=summarize(half[v["name"]]["B"])))
    return res


DOC_MAX = 16 * 1024 * 1024   # 文書 1 本の上限
EDGE_FPS = (30, 1)            # 詰めた量を測るときのフレーム(パックの既定と同じ 30fps)


SIM_MARGIN = 10.0            # 余白の物差し(LD-2f)で、文書の両端から内側へこの秒をマークの区間とみなす(= 書き出しの余白の既定)


def _docs(tx_root):
    """文字起こしの作業データの切り抜きの文書(動画まるごと・長さのあるもの)-> [(文書, 長さ, 声の行)]"""
    out = []
    for f in sorted(glob.glob(os.path.join(tx_root, "transcripts", "*.json"))):
        if os.path.basename(f).count(".") != 1:   # <id>.json だけ(.words.json・.loc.json は飛ばす)
            continue
        try:
            if os.path.getsize(f) > DOC_MAX:
                continue
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        dur = d.get("duration") if isinstance(d, dict) else None
        if d.get("whole") is False or not isinstance(dur, (int, float)) or dur <= 0:
            continue
        rows = [g for g in d.get("segments") or [] if isinstance(g, dict) and str(g.get("text") or "").strip()
                and isinstance(g.get("start"), (int, float)) and isinstance(g.get("end"), (int, float)) and g.get("cutState") != "cut"]
        if rows:
            out.append((d, float(dur), rows))
    return out


def _touch(x, rows, lo, hi):
    """x の近く(breaks.MIN_GAP 秒)まで声の行がある = 言葉の途中で切れている(動画の外 [lo, hi] の外は見ない)"""
    near = breaks.MIN_GAP
    return any(r["start"] < min(hi, x + near) and r["end"] > max(lo, x - near) for r in rows)


def edge_speech(tx_root):
    """文字起こしの作業データの切り抜きの文書 -> 端が話にかかっている割合(詰める前・後)と落とした秒(LD-2c)。
    余白つき(LD-2f。.clip.json の export.margin)の文書は数えない(評価に余白を当てない = 今までの数と比べられるように。数は margined)。
    sim = 余白の見積もり(LD-2f): 余白つきでない文書の両端から SIM_MARGIN 秒内側をマークとみなし、詰めるだけ(マークだけの動画 = 今)と
    余白の中の切れ目へ外へも寄せる(LD-2f)の端が話にかかっている割合・落とした秒・足した秒を比べる"""
    n = touch_in = touch_out = after_in = after_out = 0
    cut_sec, evalset, margined = [], 0, 0
    sim = {"docs": 0, "touchIn": 0, "touchOut": 0, "nowIn": 0, "nowOut": 0, "marginIn": 0, "marginOut": 0, "nowCut": [], "marginCut": [], "marginAdd": []}
    for d, dur, rows in _docs(tx_root):
        if schemas.clip_mark_span(d.get("clip")):
            margined += 1
            continue
        n += 1
        evalset += d.get("evalSet") is True
        ti, to = _touch(0.0, rows, 0.0, dur), _touch(dur, rows, 0.0, dur)
        total = int(round(dur * EDGE_FPS[0]))
        base = pack.snap_base([(0, total)], rows, EDGE_FPS, total, [])
        a, b = base[0][0], base[-1][1]
        touch_in, touch_out = touch_in + ti, touch_out + to
        after_in += ti and a == 0
        after_out += to and b == total
        cut_sec.append(round((a + total - b) / EDGE_FPS[0], 1))
        if dur >= 2 * SIM_MARGIN + 20:
            _simulate(sim, dur, rows)
    k = sim["docs"]
    out_sim = {"margin": SIM_MARGIN, "docs": k, "touchIn": C.rate(sim["touchIn"], k), "touchOut": C.rate(sim["touchOut"], k),
               "nowIn": C.rate(sim["nowIn"], k), "nowOut": C.rate(sim["nowOut"], k), "marginIn": C.rate(sim["marginIn"], k), "marginOut": C.rate(sim["marginOut"], k),
               "nowCut": C.dist(sim["nowCut"], p90=True), "marginCut": C.dist(sim["marginCut"], p90=True), "marginAdd": C.dist(sim["marginAdd"], p90=True)}
    return {"docs": n, "evalSet": evalset, "margined": margined, "touchIn": C.rate(touch_in, n), "touchOut": C.rate(touch_out, n),
            "afterIn": C.rate(after_in, n), "afterOut": C.rate(after_out, n), "cutSec": C.dist(cut_sec, p90=True), "sim": out_sim}


def _simulate(sim, dur, rows):
    """余白の見積もり 1 本(edge_speech の sim)。マーク = [SIM_MARGIN, dur − SIM_MARGIN]。端が話にかかっているかは文書の全部の行で見る"""
    m = SIM_MARGIN
    x0, x1 = m, dur - m
    fps = EDGE_FPS[0]
    sim["docs"] += 1
    sim["touchIn"] += _touch(x0, rows, 0.0, dur)
    sim["touchOut"] += _touch(x1, rows, 0.0, dur)
    # 今 = マークだけの動画(行は動画の中だけ・0 秒 = マークの始まり)を詰めるだけ
    crop = [dict(r, start=max(r["start"], x0) - x0, end=min(r["end"], x1) - x0) for r in rows if r["end"] > x0 and r["start"] < x1]
    t1 = int(round((x1 - x0) * fps))
    nb = pack.snap_base([(0, t1)], crop, EDGE_FPS, t1, [])
    na, nb_ = x0 + nb[0][0] / fps, x0 + nb[-1][1] / fps
    # LD-2f = 余白つきの動画で、余白の中の切れ目へ外へも寄せる
    total = int(round(dur * fps))
    mb = pack.snap_base([(0, total)], rows, EDGE_FPS, total, [], span=(x0, x1))
    ma, mb_ = mb[0][0] / fps, mb[-1][1] / fps
    sim["nowIn"] += _touch(na, rows, 0.0, dur)
    sim["nowOut"] += _touch(nb_, rows, 0.0, dur)
    sim["marginIn"] += _touch(ma, rows, 0.0, dur)
    sim["marginOut"] += _touch(mb_, rows, 0.0, dur)
    sim["nowCut"].append(round((na - x0) + (x1 - nb_), 1))
    sim["marginCut"].append(round(max(0.0, ma - x0) + max(0.0, x1 - mb_), 1))
    sim["marginAdd"].append(round(max(0.0, x0 - ma) + max(0.0, mb_ - x1), 1))


def scene_only(total, full, m, peaks_, params):
    """grid 用の速い近似: 決まった山(固定の長さの候補の山)ごとに場面の区間だけを作る(山の選び直しはしない)"""
    work = excite.smooth(total, excite.PICK_SMOOTH)
    lows = excite.smooth(full, excite.LEVEL_SMOOTH)
    out = []
    for c in peaks_:
        r = excite.scene_region(work, c["peak"], m["n"], params)
        if r is None or r["open"]:
            out.append(dict(c, shape="fixed"))
            continue
        s, e = excite.snap_region(lows, r["start"], r["end"], c["peak"], m["n"], r["end"] - r["start"])
        out.append(dict(c, start=s, end=e, shape="scene"))
    return out


def grid(studio, app, records=None, hint=None, fit_half="A"):
    """場面の形の数(GRID の組み合わせ)を組 fit_half で比べ、もう片方の組で確かめる -> 上位の組み合わせ(cover の中央値が高い順・同じなら extra が少ない順)"""
    hint = lengthhint.compute(studio, app) if hint is None else hint
    base = default_variants(hint)[0]
    mats, halves = friend_material(studio, app, records)
    pre = []
    for vid, rgs, m, total, full in mats:
        if m:
            pre.append((vid, rgs, m, total, full, picks(total, full, m, base)))
    combos = [dict(rise=a, settle=b, lead=c, tail=d) for a in GRID["rise"] for b in GRID["settle"] for c in GRID["lead"] for d in GRID["tail"]]
    rows = []
    for p in combos:
        params = excite.scene_params(p)
        got = {"A": [], "B": []}
        for vid, rgs, m, total, full, cands in pre:
            sc = scene_only(total, full, m, cands, params)
            for rg in rgs:
                got[halves[vid]].append(fit(rg, sc))
        other = "B" if fit_half == "A" else "A"
        rows.append({"params": p, "fit": summarize(got[fit_half]), "check": summarize(got[other])})
    rows.sort(key=lambda r: (-(r["fit"]["cover"].get("median") or 0), r["fit"]["extra"].get("median") or 1e9))
    return {"schema": SCHEMA + "#grid", "fitHalf": fit_half, "combos": len(combos), "top": rows[:15]}


def _line(name, s, scene=False):
    if not s["counted"]:
        return "  %-6s 数えた区間 0 / %d" % (name, s["ranges"])
    return "  %-6s 数えた %d / %d 個: 覆えた割合 中央値 %s・平均 %s・全部覆えた %d 個 / 余分 中央値 %s 秒・90%% %s 秒 / 長さ 中央値 %s 秒%s" % (
        name, s["counted"], s["ranges"], C.pct(s["cover"]["median"]).strip(), C.pct(s["coverMean"]).strip(), s["fullCover"],
        s["extra"].get("median"), s["extra"].get("p90"), s["length"].get("median"), "・固定の長さに戻った %d" % s["fallback"] if scene and s["fallback"] else "")


def print_fit(res):
    """eval_marks の節と単独の表示"""
    print("")
    print("区間の合い方(LD-2a。友人の区間の中に自動の候補の山がある物だけ。素材から 1 秒ごとに作り直し・候補 %d 本)" % res["count"])
    print("  友人の区間 %d 個のうち、解析の素材がある %d 個(配信 %d 本)" % (res["ranges"], res["withMaterial"], res["videos"]))
    for v in res["variants"]:
        desc = "固定 %g 秒・山の前 %.2f" % (v["length"], v["pre"]) if v["shape"] == "fixed" else "場面ごと(%s)" % ", ".join(
            "%s %g" % (k, x) for k, x in sorted(excite.scene_params(v.get("scene")).items()))
        print("  [%s] %s" % (v["name"], desc))
        for k, label in (("all", "全部"), ("A", "組A"), ("B", "組B")):
            print(_line(label, v[k], v["shape"] == "scene"))
    e = res.get("edges")
    if e and e["docs"]:
        print("  端が話にかかっている(言葉の途中で切れている)切り抜きの文書 %d 本(うち評価用 %d): 始まり %s → 詰めたあと %s・終わり %s → %s / 落とした秒 中央値 %s・90%% %s" % (
            e["docs"], e["evalSet"], C.pct(e["touchIn"]).strip(), C.pct(e["afterIn"]).strip(), C.pct(e["touchOut"]).strip(), C.pct(e["afterOut"]).strip(),
            e["cutSec"].get("median"), e["cutSec"].get("p90")))
        if e.get("margined"):
            print("  (余白つきの文書 %d 本は数えていません)" % e["margined"])
        sm = e.get("sim") or {}
        if sm.get("docs"):
            print("  余白 %g 秒の見積もり(LD-2f。文書 %d 本の両端から %g 秒内側をマークとみなす): 端が話にかかっている 始まり %s → 詰めるだけ %s・余白の中へも寄せる %s /"
                  " 終わり %s → %s・%s / 落とした秒 中央値 %s → %s・90%% %s → %s / 足した秒 中央値 %s・90%% %s" % (
                      sm["margin"], sm["docs"], sm["margin"], C.pct(sm["touchIn"]).strip(), C.pct(sm["nowIn"]).strip(), C.pct(sm["marginIn"]).strip(),
                      C.pct(sm["touchOut"]).strip(), C.pct(sm["nowOut"]).strip(), C.pct(sm["marginOut"]).strip(),
                      sm["nowCut"].get("median"), sm["marginCut"].get("median"), sm["nowCut"].get("p90"), sm["marginCut"].get("p90"),
                      sm["marginAdd"].get("median"), sm["marginAdd"].get("p90")))


def main(argv=None):
    p = argparse.ArgumentParser(description="自動の区間が友人の区間にどれだけ合うか(LD-2a。作業データは読むだけ)")
    p.add_argument("--json", action="store_true", help="結果を スタジオの作業データの evals/marks/<日時>-clipfit.json に残す")
    p.add_argument("--grid", action="store_true", help="場面の形の数を組 A で選び組 B で確かめる")
    p.add_argument("--data-dir", help="作業データの親フォルダ(テスト用)")
    a = p.parse_args(argv)
    studio, app = C.locate("studio", a.data_dir), C.locate("app", a.data_dir)
    if a.grid:
        for half in ("A", "B"):
            g = grid(studio, app, fit_half=half)
            print("組 %s で選んだ上位(%d 通り。右 = もう片方の組で確かめた数)" % (half, g["combos"]))
            for r in g["top"][:8]:
                print("  %s  覆えた %s・余分 %s 秒 | 確かめ: 覆えた %s・余分 %s 秒" % (
                    " ".join("%s=%g" % kv for kv in r["params"].items()), C.pct(r["fit"]["cover"].get("median")).strip(), r["fit"]["extra"].get("median"),
                    C.pct(r["check"]["cover"].get("median")).strip(), r["check"]["extra"].get("median")))
        return None
    res = evaluate(studio, app, data_dir=a.data_dir)
    print_fit(res)
    C.report_saved(res, a.json, studio, "marks", "-clipfit")
    return res


if __name__ == "__main__":
    C.utf8_stdout()
    main()
