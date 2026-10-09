#!/usr/bin/env python3
"""校正にどれだけ手間(時間)がかかっているかを見る道具(マスタープラン Q2 の記録 = 文書の effort の見る手段。「校正を速くする」改善が効いたかを比べる物差し)。

    python dev/eval_effort.py [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--json] [--data-dir 作業データの親フォルダ] [--no-eval] [--no-cer]

- 作業データは**読むだけ**(transcribe の transcripts/<id>.json と <id>.diar.json・<id>.alt.json の有無)。何も書き換えない。--json のときだけ、結果を
  文字起こしの作業データの evals\\effort\\<日時>.json(schema youtube-tools-effort-eval/v1)に残す(置き場所は eval_asr.py(evals\\asr)・eval_speakers.py と同じ「ツールの作業データの下の evals\\<領域>」)。
- 読むもの: 文書の effort = {activeSec, cutSec, sessions, proofedRows, unproofedRows, lastAt}(src/editor/ed_store.py の add_effort・effort_rows。画面は app-learn.js の effortTick)・
  segments(人の最終)・original(機械の出力)・recognition.runs・evalSet・evalReviewed・clip。<id>.diar.json の latest.rows[行 id].speaker(機械が付けた話者)。
  effort の無い文書・時間が 0 の文書・長さが分からない文書は飛ばす(数は skipped)。
- 手間の倍率 = activeSec ÷ 動画の秒(「1 分の動画に何分かかったか」。×12.0 = 1 分の動画に 12 分)。動画の長さ = 文書の長さ(src/editor/ed_store.py の doc_length と同じ決まり:
  範囲の終わり − 始まり → 動画の長さ − 始まり → 最後の行の終わりまで)。校正の時間 = activeSec(1 文字起こし のタブ)、カットとパックの時間 = cutSec(2 カット・3 パック)。
- 「終わった文書」= 評価用(evalSet)は確かめ済み(evalReviewed がある。src/editor/ed_drill.py の drill_is_reviewed と同じ条件)・それ以外は文字のある行が全部校正済み。
  倍率の中央値・四分位・合計は**終わった文書だけ**で出す(途中の文書は、まだ直している途中で時間が短く出る = 倍率に入れると甘く出るので、数だけ別の欄に出す)
- 直しの量(original と segments の比べ。original が無い文書は「分からない」。文字のある行だけで数える。original と segments を、時刻が重なるまとまり(src/editor/ed_learn.py の _groups と同じ)に分ける):
    文字を直した行 = 機械の行と人の行が両方あるまとまりで、空白を除いた文字が違う(まとまりの人の行の数。分けた・つないだだけで文字が同じなら入れない)
    人が足した行 = 人の行だけのまとまり / 人が消した行 = 機械の行だけのまとまり(機械の行の数)
    時刻を直した行 = original のどの行とも始まり・終わりが 0.05 秒以内で合わない行(eval_speakers.py の time_edited_flags と同じ考え方。足した行は「足した行」に数えるのでここには入れない)
    話者を直した行 = <id>.diar.json の latest.rows[行 id].speaker と今の行の speaker が違う行(diar.json が無ければ分からない。noSub の行(字幕に出さない。組み込みの「ゲーム音声など」)は
                     人の判断で機械の話者判別の外れではないので数えない)。noSub の行は、人が印を付けた行として「直した行」に入れ、数を edits.noSub に別に出す
    直した行の割合 = (人が足した ∪ 文字を直した ∪ 時刻を直した ∪ 話者を直した 行の数 + 消した行) ÷ (文字のある行 + 消した行)。動画 1 分あたりの数も出す
  機械の CER = 終わった文書を、eval_asr.py と同じ採点(score_doc・total。機械の出力 original と人の最終 segments の文字の違い)で数えた値。--no-cer なら数えない
  (eval_asr の load_serve で editor の採点の関数だけを読む。0.2 秒ほど)
- 組ごとの比べ(終わった文書の倍率の中央値・文書の数・途中の数): 最初の認識のエンジンとモデル(recognition.runs の kind の無い記録)・出どころ(編集前 / ショート = eval_asr.py の origin_of)・
  評価用かどうか・確かめ済みの付け方(evalReviewed.via = drill / editor)・2つ目のエンジンの候補の有無(<id>.alt.json)・週ごと(effort.lastAt)
- 直しの量と倍率の関係: 終わった文書を直した行の割合で 4 つ(〜25% / 25〜50% / 50〜75% / 75%〜)に区切った組ごとの倍率(どの直しが時間を食うかの目安)
- --since / --until は文書の時期で絞る(effort.lastAt、無ければ updatedAt。until はその日を含む)。終わった文書が 10 本未満のときは「まだ少ない(参考)」と出す。評価用の文書は既定で含める(--no-eval で外す)
- 時間の注意(コードで確かめた記録の決まり): 画面は 30 秒ごとに「最後の操作から 2 分以内なら 30 秒足す」(app.js の setInterval)ので、30 秒刻み・2 分までの離席は入る・
  操作せずに 2 分より長く聞くだけの時間は入らない(動画を全部聞く確かめ済みの文書でも、倍率は聞いた時間より短く出ることがある)。
  1 回の送信(POST /api/effort)は 3600 秒まで(通常は 5 分たまったとき・画面を離れたとき・別の文書を開くときに送る)。送り損ねた分は入らない。簡易版は時間を送らないので外す
"""
import argparse
import bisect
import datetime
import os
import re
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import _evalcommon as C  # noqa: E402  共通の部品(作業データの場所・時期・率・分布・保存。src を sys.path に足す)
from _evalcommon import dist, rate  # noqa: E402
from ytt.schemas import num, plain_int  # noqa: E402  num = 有限の数(bool は除く)なら float、それ以外は None / plain_int = bool 以外の整数か None
import eval_asr  # noqa: E402  出どころ(origin_of)・最初の認識(draft_of)・採点(score_doc・total)は eval_asr.py と同じ決まりを使う

SCHEMA = "youtube-tools-effort-eval/v1"
FEW_DOCS = 10                  # 終わった文書がこれより少ないときは「まだ少ない(参考)」
TIME_TOL = 0.05                # original と行の端が一致したとみなす秒(eval_speakers.py の TIME_TOL と同じ)
GROUP_SLACK = 0.05             # 時刻が重なるまとまり(src/editor/ed_learn.py の _groups と同じ)
MAX_BYTES = C.DOC_BYTES
DOC_RE = re.compile(r"^[0-9a-f]{12}\.json\Z")
MAX_EFFORT_SEC = 3600          # src/editor/ed_store.py の MAX_EFFORT_SEC(1回に足せる秒)。説明の数字(editor は読み込まない)
BUCKETS = ((0.25, "〜25%"), (0.50, "25〜50%"), (0.75, "50〜75%"), (float("inf"), "75%〜"))
GROUPS = (("engine", "最初の認識のエンジン・モデル"), ("origin", "出どころ"), ("eval", "評価用かどうか"),
          ("via", "確かめ済みの付け方"), ("alt", "2つ目のエンジンの候補"), ("week", "週ごと(effort.lastAt)"))
GROUP_FIELD = {"eval": "evalLabel"}   # 組の名前 -> 記録の項目名(同じなら書かない)
EDIT_KEYS = (("text", "文字を直した行"), ("added", "人が足した行"), ("deleted", "人が消した行"), ("time", "時刻を直した行"), ("speaker", "話者を直した行"))


# ---------------------------------------------------------------- 読み込み(読むだけ)

# ---------------------------------------------------------------- 1つの文書(純粋な関数)

def doc_length(d):
    """文書の長さ(秒)。src/editor/ed_store.py の doc_length と同じ決まり: 範囲の終わり − 始まり → 動画の長さ − 始まり → 最後の行の終わり − 始まり"""
    segs = [s for s in (d.get("segments") or []) if isinstance(s, dict)]
    a = num(d.get("start")) or 0.0
    b, dur = num(d.get("end")), num(d.get("duration"))
    if b is not None and b > a:
        return b - a
    if dur is not None and dur > a:
        return dur - a
    return max(0.0, max([num(s.get("end")) or 0.0 for s in segs] or [0.0]) - a)


def doc_effort(doc):
    """文書の effort -> {"activeSec", "cutSec", "sessions", "proofedRows", "unproofedRows", "lastAt"} か None(無い・形が違う)。
    src/editor/ed_store.py の _effort_of と同じく、整数でない値は 0 として読む"""
    ef = doc.get("effort") if isinstance(doc, dict) else None
    if not isinstance(ef, dict):
        return None
    out = {k: max(0, plain_int(ef.get(k)) or 0) for k in ("activeSec", "cutSec", "sessions", "proofedRows", "unproofedRows")}
    out["lastAt"] = ef["lastAt"] if plain_int(ef.get("lastAt")) else None
    return out


def text_rows(items):
    """文字のある行(start・end が数)を時刻の順に -> [dict(元の行 + "start"・"end" を float に)]"""
    out = []
    for g in items or []:
        if not isinstance(g, dict):
            continue
        a, b = num(g.get("start")), num(g.get("end"))
        if a is None or b is None or not re.sub(r"\s+", "", str(g.get("text") or "")):
            continue
        out.append(dict(g, start=a, end=b))
    return sorted(out, key=lambda g: (g["start"], g["end"]))


def pair_groups(orig, segs):
    """機械の行(orig)と人の行(segs)を、時刻が重なるまとまりに分ける -> [([orig の添字], [segs の添字])]。src/editor/ed_learn.py の _groups と同じ"""
    items = sorted([(o["start"], o["end"], 0, i) for i, o in enumerate(orig)] + [(g["start"], g["end"], 1, i) for i, g in enumerate(segs)])
    groups, cur, cur_end = [], None, -1.0
    for a, b, k, i in items:
        if cur is not None and a < cur_end - GROUP_SLACK:
            cur[k].append(i)
            cur_end = max(cur_end, b)
        else:
            if cur is not None:
                groups.append(cur)
            cur = ([], [])
            cur[k].append(i)
            cur_end = b
    if cur is not None:
        groups.append(cur)
    return groups


def _joined(items, idx):
    return re.sub(r"\s+", "", "".join(str(items[i].get("text") or "") for i in idx))


def edit_counts(doc, diar_rows):
    """直しの量(original と segments の比べ)。original に文字のある行が無ければ None(分からない)。
    diar_rows = <id>.diar.json の latest.rows(行 id -> {speaker, …})か None(記録なし = 話者を直した行は分からない)
    -> {"textRows", "text", "added", "deleted", "time", "speaker"(None = 分からない), "edited"(直した行の数。消した行は含まない), "frac"(直した行の割合)}"""
    orig, segs = text_rows(doc.get("original")), text_rows(doc.get("segments"))
    if not orig:
        return None
    text_set, added_set = set(), set()
    deleted = 0
    for go, ge in pair_groups(orig, segs):
        if go and not ge:
            deleted += len(go)
        elif ge and not go:
            added_set.update(ge)
        elif _joined(orig, go) != _joined(segs, ge):
            text_set.update(ge)
    starts = sorted((o["start"], o["end"]) for o in orig)
    keys = [s[0] for s in starts]
    time_set = set()
    for i, g in enumerate(segs):
        if i in added_set:
            continue
        k, same = bisect.bisect_left(keys, g["start"] - TIME_TOL), False
        while k < len(starts) and starts[k][0] <= g["start"] + TIME_TOL:
            if abs(starts[k][1] - g["end"]) <= TIME_TOL:
                same = True
                break
            k += 1
        if not same:
            time_set.add(i)
    ns_set = {i for i, g in enumerate(segs) if g.get("noSub") is True}   # 字幕に出さない行(人が印を付けた = 直した行に数える。話者の判別の誤りには数えない)
    spk_set = None
    if isinstance(diar_rows, dict):
        spk_set = set()
        for i, g in enumerate(segs):
            if i in ns_set:
                continue   # ゲーム音声などの話者・noSub は人の判断で、機械の話者判別の当たり外れではない
            rec = diar_rows.get(str(g.get("id")))
            if isinstance(rec, dict) and str(rec.get("speaker") or "") != str(g.get("speaker") or ""):
                spk_set.add(i)
    edited = added_set | text_set | time_set | (spk_set or set()) | ns_set
    out = {"textRows": len(segs), "text": len(text_set), "added": len(added_set), "deleted": deleted, "time": len(time_set),
           "speaker": None if spk_set is None else len(spk_set), "edited": len(edited), "frac": rate(len(edited) + deleted, len(segs) + deleted)}
    if ns_set:   # noSub の行がある文書だけ(無い文書は今までと同じ形)
        out["noSub"] = len(ns_set)
    return out


def first_run_label(doc):
    """最初の認識(recognition.runs の kind の無い記録)のエンジンとモデル。無ければ「不明(記録なし)」。eval_asr.draft_of と同じ選び方(版は入れない)"""
    dr = eval_asr.draft_of(doc)
    if not dr:
        return eval_asr.DRAFT_NONE
    return " ".join(x for x in (dr["engine"], dr["model"]) if x) or eval_asr.DRAFT_NONE


def week_of(ms):
    if ms is None:
        return "不明"
    y, w, _ = datetime.datetime.fromtimestamp(ms / 1000).isocalendar()
    return "%d-W%02d" % (y, w)


def doc_record(doc, diar_rows=None, has_alt=False):
    """文書 1 件の記録。effort が無い・時間が 0・長さが分からないときは (None, 理由) を返す -> (記録 or None, 飛ばした理由 or "")"""
    ef = doc_effort(doc)
    if ef is None:
        return None, "noEffort"
    dur = doc_length(doc)
    if dur <= 0:
        return None, "noDuration"
    if ef["activeSec"] <= 0:
        return None, "noTime"
    rows = text_rows(doc.get("segments"))
    proofed = sum(1 for g in rows if g.get("proofed") is True)
    ev = doc.get("evalSet") is True
    rv = doc.get("evalReviewed") if isinstance(doc.get("evalReviewed"), dict) else None
    finished = eval_asr.is_reviewed(doc) if ev else bool(rows) and proofed == len(rows)   # 確かめ済み = src/editor/ed_drill.py の drill_is_reviewed と同じ条件
    t = ef["lastAt"] or plain_int(doc.get("updatedAt")) or None
    return {"id": str(doc.get("id") or ""), "title": str(doc.get("title") or "")[:40], "evalSet": ev, "finished": finished,
            "durationSec": round(dur, 2), "activeSec": ef["activeSec"], "cutSec": ef["cutSec"], "sessions": ef["sessions"],
            "ratio": round(ef["activeSec"] / dur, 3), "textRows": len(rows), "proofedRows": proofed, "proofedFrac": rate(proofed, len(rows)),
            "engine": first_run_label(doc), "origin": eval_asr.ORIGIN_NAME.get(eval_asr.origin_of(doc), "?"), "evalLabel": "評価用" if ev else "普段",
            "via": str(rv.get("via") or "不明") if rv else "(確かめ済みの印なし)", "alt": "あり" if has_alt else "なし",
            "lastAt": t, "week": week_of(t), "edits": edit_counts(doc, diar_rows), "cer": None}, ""


def doc_cer(S, doc):
    """機械の出力 original と人の最終 segments の文字の違い(eval_asr.py と同じ採点) -> {"errs", "refChars", "cer"} か None(original が無い・数える所が無い)"""
    orig = [o for o in doc.get("original") or [] if isinstance(o, dict)]
    if not orig:
        return None
    groups = eval_asr.score_doc(S, doc, orig, [], flag_from="ref")
    t = eval_asr.total(groups)
    return {"errs": t["errs"], "refChars": t["refChars"], "cer": t["cer"]} if t["refChars"] else None


# ---------------------------------------------------------------- 集計(純粋な関数)

def ratio_stats(recs):
    """終わった文書の倍率 -> {"n", "ratio": 分布, "sumActiveSec", "sumCutSec", "sumDurationSec", "totalRatio"(合計の秒 ÷ 合計の動画の秒), "sessions"}"""
    dur = sum(r["durationSec"] for r in recs)
    act = sum(r["activeSec"] for r in recs)
    return {"n": len(recs), "ratio": dist([r["ratio"] for r in recs]), "sumActiveSec": act, "sumCutSec": sum(r["cutSec"] for r in recs),
            "sumDurationSec": round(dur, 1), "totalRatio": round(act / dur, 3) if dur else None, "sessions": sum(r["sessions"] for r in recs)}


def group_table(recs, key):
    """組ごとの倍率(終わった文書の中央値・四分位・数と、途中の文書の数)-> [{"key", "finished", "unfinished", "median", "p25", "p75"}]。週は新しい順でなく古い順・ほかは終わった数の多い順"""
    by = {}
    for r in recs:
        by.setdefault(r[GROUP_FIELD.get(key, key)], []).append(r)
    out = []
    for k, rs in by.items():
        fin = [r for r in rs if r["finished"]]
        d = dist([r["ratio"] for r in fin])
        out.append({"key": k, "finished": len(fin), "unfinished": len(rs) - len(fin), "median": d.get("median"), "p25": d.get("p25"), "p75": d.get("p75")})
    if key == "week":
        return sorted(out, key=lambda x: x["key"])
    return sorted(out, key=lambda x: (-x["finished"], -x["unfinished"], x["key"]))


def edit_summary(recs):
    """直しの量(recs = 終わった文書)。分からない文書(original が無い)は数だけ -> {"docs", "unknown", "totals", "perMin", "speakerKnownDocs", "frac": 分布}"""
    known = [r for r in recs if r["edits"]]
    tot = {k: sum(r["edits"][k] for r in known) for k, _ in EDIT_KEYS if k != "speaker"}
    sp = [r for r in known if r["edits"]["speaker"] is not None]
    tot["speaker"] = sum(r["edits"]["speaker"] for r in sp)
    tot["edited"] = sum(r["edits"]["edited"] for r in known)
    if any(r["edits"].get("noSub") for r in known):   # noSub の行がある文書があるときだけ(無ければ今までと同じ形)
        tot["noSub"] = sum(r["edits"].get("noSub", 0) for r in known)
    tot["textRows"] = sum(r["edits"]["textRows"] for r in known)
    minutes = sum(r["durationSec"] for r in known) / 60.0
    sp_min = sum(r["durationSec"] for r in sp) / 60.0
    per = {k: round(tot[k] / minutes, 2) if minutes else None for k in ("text", "added", "deleted", "time", "edited")}
    per["speaker"] = round(tot["speaker"] / sp_min, 2) if sp_min else None
    return {"docs": len(known), "unknown": len(recs) - len(known), "totals": tot, "perMin": per, "speakerKnownDocs": len(sp),
            "frac": dist([r["edits"]["frac"] for r in known]), "perMinRows": round(tot["edited"] / minutes, 2) if minutes else None}


def bucket_table(recs):
    """直した行の割合の区切りごとの倍率(終わった文書のうち直しの量が分かるもの)-> [{"bucket", "docs", "median", "p25", "p75", "perMin"(動画 1 分あたりの直した行)}]"""
    out = []
    lo = 0.0
    for hi, label in BUCKETS:
        rs = [r for r in recs if r["edits"] and r["edits"]["frac"] is not None and lo <= r["edits"]["frac"] < hi]
        if rs:
            d = dist([r["ratio"] for r in rs])
            mins = sum(r["durationSec"] for r in rs) / 60.0
            out.append({"bucket": label, "docs": len(rs), "median": d["median"], "p25": d["p25"], "p75": d["p75"],
                        "perMin": round(sum(r["edits"]["edited"] for r in rs) / mins, 2) if mins else None})
        lo = hi
    return out


def cer_summary(recs):
    """終わった文書の機械の CER(文字の数で合算)-> {"docs", "errs", "refChars", "cer"}"""
    cs = [r["cer"] for r in recs if r.get("cer")]
    errs, ref = sum(c["errs"] for c in cs), sum(c["refChars"] for c in cs)
    return {"docs": len(cs), "errs": errs, "refChars": ref, "cer": rate(errs, ref)}


def summarize(recs):
    """記録の一覧 -> 結果(meta 以外)。終わった文書の倍率・途中の数・直しの量・組ごと・区切りごと"""
    fin = [r for r in recs if r["finished"]]
    unf = [r for r in recs if not r["finished"]]
    few = len(fin) < FEW_DOCS
    return {"finished": dict(ratio_stats(fin), cut=sum(r["cutSec"] for r in fin)),
            "unfinished": {"n": len(unf), "activeSec": sum(r["activeSec"] for r in unf), "ratio": dist([r["ratio"] for r in unf])},
            "few": few, "edits": edit_summary(fin), "cer": cer_summary(fin), "buckets": bucket_table(fin),
            "groups": {k: group_table(recs, k) for k, _ in GROUPS}}


def notes_for(res, skipped):
    n = ["時間は画面が 30 秒ごとに数える(最後の操作から 2 分以内の間だけ 30 秒足す)ので 30 秒刻み。2 分までの離席・考え込みは入り、"
         "操作せず 2 分より長く聞くだけの時間は入らない(倍率は実際に作業した時間そのものではなく、目安)。画面を開いたまま離席した分が入ることがある。"
         "1 回の送信は %d 秒まで(通常は 5 分たまったとき・画面を離れたとき・別の文書を開くときに送る)。送り損ねた分は入らない" % MAX_EFFORT_SEC,
         "倍率は終わった文書だけで出しています。途中の文書は、まだ直している途中で時間が短く出る(入れると甘く出る)ので、数だけ別に出しています",
         "評価用の確かめ済みは動画を全部聞く文書なので、普段の文書より倍率が高く出ます(組ごとの比べで見る)"]
    if skipped.get("noTime"):
        n.append("校正の時間(activeSec)が 0 の文書 %d 件は倍率が出せないので外しました(行の数だけの記録・ほかのタブだけで作業したもの)" % skipped["noTime"])
    if skipped.get("noEffort"):
        n.append("effort(校正の手間の記録)が無い文書 %d 件は飛ばしました(記録を入れる前の文書)" % skipped["noEffort"])
    e = res["edits"]
    if e["unknown"]:
        n.append("original(機械の出力)が無い終わった文書 %d 件は、直しの量が分かりません" % e["unknown"])
    if e["docs"] and e["speakerKnownDocs"] < e["docs"]:
        n.append("話者を直した行は、判別の記録(.diar.json)がある文書 %d 件だけで数えています。人が話者を判別し直すと機械の記録が置き換わるので、少なく出ます" % e["speakerKnownDocs"])
    return n


# ---------------------------------------------------------------- 全体

def evaluate(data_dir=None, since=None, until=None, include_eval=True, cer=True):
    root = C.locate("transcribe", data_dir)
    tdir = os.path.join(root, "transcripts")
    since_ms, until_ms = C.period(since, until)
    skipped = {"broken": 0, "noEffort": 0, "noDuration": 0, "noTime": 0, "evalSet": 0, "outOfRange": 0}
    recs, docs = [], {}
    for name in sorted(os.listdir(tdir)) if os.path.isdir(tdir) else []:
        if not DOC_RE.match(name):
            continue
        tid = name[:-5]
        doc = C.read_json(os.path.join(tdir, name), None, MAX_BYTES)
        if not isinstance(doc, dict):
            skipped["broken"] += 1
            continue
        if doc.get("evalSet") is True and not include_eval:
            skipped["evalSet"] += 1
            continue
        diar = C.read_json(os.path.join(tdir, tid + ".diar.json"), None, MAX_BYTES)
        latest = diar.get("latest") if isinstance(diar, dict) and isinstance(diar.get("latest"), dict) else None
        rows = latest.get("rows") if latest and isinstance(latest.get("rows"), dict) else None
        rec, why = doc_record(doc, rows, os.path.exists(os.path.join(tdir, tid + ".alt.json")))
        if rec is None:
            skipped[why] += 1
            continue
        if not C.in_period(rec["lastAt"], since_ms, until_ms, unknown=False):   # 時期を指定したときは、時刻の分からない文書を外す
            skipped["outOfRange"] += 1
            continue
        recs.append(rec)
        if cer and rec["finished"]:
            docs[tid] = doc   # CER を数える文書(終わった文書)だけ持っておく
    cer_note = ""
    if cer and any(r["finished"] for r in recs):
        S = None
        try:
            S = eval_asr.load_serve("fake")
            for r in recs:
                if r["finished"]:
                    r["cer"] = doc_cer(S, docs[r["id"]])
        except Exception as e:   # 採点の部品が読めなくても、手間の集計は出す
            cer_note = "機械の CER は数えられませんでした(%s: %s)" % (type(e).__name__, e)
            for r in recs:
                r["cer"] = None
        finally:
            tmp = os.environ.get("TRANSCRIBE_DATA_DIR", "")
            if S is not None and tmp and os.path.basename(tmp).startswith("eval_asr_"):
                shutil.rmtree(tmp, ignore_errors=True)   # load_serve が作った一時の置き場
    res = summarize(recs)
    nfin = res["finished"]["n"]
    notes = notes_for(res, skipped)
    if cer_note:
        notes.append(cer_note)
    meta = {"schema": SCHEMA, "at": int(time.time() * 1000), "since": since, "until": until, "includeEval": bool(include_eval), "cer": bool(cer),
            "git": C.git_rev(), "dataDir": root, "docs": len(recs), "finishedDocs": nfin, "unfinishedDocs": res["unfinished"]["n"], "few": res["few"],
            "fewNote": "まだ少ない(参考): 終わった文書が %d 本(%d 本未満)。倍率の変化で改善の良し悪しを決めない" % (nfin, FEW_DOCS) if res["few"] else "",
            "skipped": skipped, "notes": notes}
    res["meta"] = meta
    res["byDoc"] = sorted(recs, key=lambda r: (not r["finished"], -(r["ratio"]), r["id"]))
    return res


# ---------------------------------------------------------------- 表示・保存

def mins(sec):
    return "%.1f分" % (sec / 60.0)


def xr(x):
    return "  -  " if x is None else "×%.1f" % x


def pct(x):
    return C.pct(x, 0)


def print_report(res):
    m = res["meta"]
    rng = C.period_label(m["since"], m["until"])
    print("校正の手間の測定(%s)  文書 %d 件(終わった %d・途中 %d)  作業データ: %s" % (rng, m["docs"], m["finishedDocs"], m["unfinishedDocs"], m["dataDir"]))
    if m["fewNote"]:
        print("★ " + m["fewNote"])
    sk = m["skipped"]
    print("  飛ばした文書: " + "・".join("%s %d" % (k, v) for k, v in sk.items() if v) if any(sk.values()) else "  飛ばした文書: なし")
    if not m["docs"]:
        print("(測れる文書がありません。校正の時間(effort)が貯まると測れます)")
    else:
        f, u = res["finished"], res["unfinished"]
        d = f["ratio"]
        print("  [終わった文書の手間の倍率(校正の時間 ÷ 動画の秒。×12.0 = 1 分の動画に 12 分)]  文書 %d 本" % f["n"])
        if d.get("n"):
            print("    中央値 %s  四分位 %s 〜 %s  最小 %s・最大 %s  合計の倍率 %s(校正 %s ÷ 動画 %s)  カット・パック %s  回数 %d" % (
                xr(d["median"]), xr(d["p25"]), xr(d["p75"]), xr(d["min"]), xr(d["max"]), xr(f["totalRatio"]), mins(f["sumActiveSec"]), mins(f["sumDurationSec"]), mins(f["cut"]), f["sessions"]))
        else:
            print("    (終わった文書がありません)")
        print("  [途中の文書(倍率には入れない)]  %d 本  校正の時間の合計 %s" % (u["n"], mins(u["activeSec"])))
        e = res["edits"]
        print("  [直しの量(終わった文書。機械の出力 original と人の最終の比べ)]  分かる文書 %d 本・分からない %d 本" % (e["docs"], e["unknown"]))
        if e["docs"]:
            t, p = e["totals"], e["perMin"]
            print("    " + "  ".join("%s %d(%s/分)" % (lb, t[k], "-" if p[k] is None else p[k]) for k, lb in EDIT_KEYS))
            if t.get("noSub"):
                print("    うち字幕に出さない(noSub)の行 %d(人が印を付けた行として直した行に入れた。話者を直した行には数えない)" % t["noSub"])
            print("    直した行 %d / 文字のある行 %d  動画 1 分あたり %s 行  直した行の割合(文書ごと) 中央値 %s  四分位 %s 〜 %s" % (
                t["edited"], t["textRows"], e["perMinRows"], pct(e["frac"].get("median")), pct(e["frac"].get("p25")), pct(e["frac"].get("p75"))))
        c = res["cer"]
        if m["cer"]:
            print("  [機械の CER(終わった文書。eval_asr.py と同じ採点)]  %s(誤り %d / 正解の文字 %d・文書 %d 本)" % (pct(c["cer"]), c["errs"], c["refChars"], c["docs"]) if c["docs"] else "  [機械の CER]  数えられる文書がありません")
        if res["buckets"]:
            print("  [直した行の割合の区切りごとの倍率(どの直しが時間を食うかの目安)]")
            for b in res["buckets"]:
                print("    %-8s 文書 %3d 本  倍率 中央値 %s(四分位 %s 〜 %s)  動画 1 分あたりの直した行 %s" % (b["bucket"], b["docs"], xr(b["median"]), xr(b["p25"]), xr(b["p75"]), b["perMin"]))
        for k, label in GROUPS:
            tab = res["groups"][k]
            if not tab:
                continue
            print("  [組ごと: %s]  終わった文書の倍率の中央値(文書の数)・途中の数" % label)
            for g in tab:
                print("    %-52s 終わった %3d 本  中央値 %s(四分位 %s 〜 %s)  途中 %d 本" % (g["key"], g["finished"], xr(g["median"]), xr(g["p25"]), xr(g["p75"]), g["unfinished"]))
        print("  [文書ごと(終わった文書を倍率の高い順に最大 10 件)]")
        for r in [r for r in res["byDoc"] if r["finished"]][:10]:
            ed = r["edits"]
            print("    %s 動画 %s  校正 %s  倍率 %s  直した行の割合 %s  CER %s%s  %s" % (
                r["id"], mins(r["durationSec"]), mins(r["activeSec"]), xr(r["ratio"]), pct(ed["frac"]) if ed else "分からない",
                pct(r["cer"]["cer"]) if r.get("cer") else "-", "  [評価用]" if r["evalSet"] else "", r["title"]))
    for n in m["notes"]:
        print("注意: " + n)


def main(argv=None):
    p = argparse.ArgumentParser(description="校正の手間(時間・直しの量)を見る(作業データは読むだけ)")
    C.add_period_args(p, "この日(YYYY-MM-DD)以後の文書だけ(effort.lastAt、無ければ updatedAt)", "この日(YYYY-MM-DD。この日を含む)までの文書だけ",
                      "同じ形の JSON を 文字起こしの作業データの evals/effort/<日時>.json に残す")
    p.add_argument("--no-eval", action="store_true", help="評価用(evalSet)の文書を外す")
    p.add_argument("--no-cer", action="store_true", help="機械の CER を数えない(eval_asr の採点の部品を読み込まない)")
    args = p.parse_args(argv)
    res = evaluate(args.data_dir, args.since, args.until, not args.no_eval, not args.no_cer)
    print_report(res)
    C.report_saved(res, args.json, res["meta"]["dataDir"], "effort")
    return res


if __name__ == "__main__":
    C.utf8_stdout()
    main()
