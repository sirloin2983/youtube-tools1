#!/usr/bin/env python3
"""認識のあとの後処理(src/pipeline/transcribe/fill.py・llm.py。A 文字の少ない行を別の読みで埋める・D 名簿の呼び名の 1 字違いを直す・
E LLM の名前直し・C 余分の掃除)を、人が残したか・直したか・戻したかで測る道具(後処理の様子見の物差し。
人の判断 = 「確かめる」の読みのカード read:fill の答え + 普段の校正のついで。追加の校正は要らない)。

    py -3.12 -m eval.tools.eval_fill [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--json] [--data-dir 作業データの親フォルダ]

- 作業データは**読むだけ**(文字起こしの transcripts/<id>.json・whisper の生の結果 <id>.asr.json・<id>.llm.json と、
  入口の作業データ app の check/answers.jsonl = 確かめるの答え。読み方は human/check/answerlog)。何も書き換えない。
  --json のときだけ、結果を文字起こしの作業データの evals/fill/<日時>.json に残す(schema youtube-tools-fill-eval/v1。置き場所の規則は eval_alt.py と同じ)
- 対象 = 評価用でない文書のうち、最初の文字起こしで後処理を当てたもの(params.autoFill・autoLlm。評価用には当てない決まり)。③ の部品は読まない(文書の JSON と答えの記録だけで判定する)
- 人の判断の正は 2 つ。どちらも人が見た物だけを当たり・外れに入れる(人が確認していない行は「未確認」= 率の外):
    1. 確かめるの read:fill の答え(カードの target = 文書の id と行の id)。答えのある行はそれを正にする:
       1 = 残した(後処理の札を残す)/ 2 = 戻した(認識のままに戻す)/ 打った文字 = 直した(読みのカードの反映と同じ意味。カードは 10-31 に消した = 前の答えの記録だけ読む)。
       答えは行を校正済みにしないので、答えの無い行の規則(下の 2)では数えられない。同じカードに何度か答えたときは最後に効いている答え。
       答えの時刻 at が行の時刻になる(--since / --until)。答えた後に行が消えた・分け直された物は追えない(答えは行の id で引く)
    2. 答えの無い行は、今の文書の人の最終で分ける(校正済み proofed の行だけ。下の A・E の規則)
- A(別の読みで埋めた行)の見つけ方: 機械の出力 original のうち、確信度(avg_logprob)を持たない行。埋めた行は確信度を持たない(fill.fill_apply)ので、
  画面の「別の読み」の札で戻して印(行の fill)が消えたあとでも、どこを埋めたかが分かる。その時間に重なる今の行(人の最終)を見て分ける:
    残した … 人の最終が別の読みのまま(寄せた文字が同じ)で、校正済み
    直した … 別の読みとも whisper の文字とも違う文字に直して、校正済み(別の読みは当たらなかったが、手がかりにはなったかもしれない)。
              直した行は、人の最終が別の読みと whisper の文字のどちらに近いか(寄せた文字の編集距離)も数える
    戻した … 人の最終が whisper の文字(行の fill.from。札で戻して印が消えたときは生の結果 asr.json の同じ時間の文字)と同じで、校正済み
    消した … その時間に重なる今の行が無く、前後の隣の行が校正済み(端なら在る側だけ)= 人がその辺りを見て行を消した(別の読みは幻覚だった)
    未確認 … 上のどれでもない = 校正済みでない(人がまだ見ていない。後の機械の処理で行が変わっただけかもしれない)。**率は 未確認 を除いて出す**
  比べるときの文字の寄せ方: ytt.txbase.alt_fold(NFKC・小文字・カタカナ → ひらがな・文字と数字だけ。記号・句読点・空白・伸ばし ー を無視)
- E(LLM が名簿の呼び名に直した行。llm.py): <id>.llm.json の当てた案(行の時刻つき)と同じ時間の今の行で、A と同じく答え → 校正済みの順に分ける
  (戻した = 人の最終が直す前の行のまま。札で戻して印が消えても分かる)。<id>.llm.json に時刻が無い案は数えない
- D(名簿の呼び名に直した行): 印 fill.FILL_NAME_FLAG が残っている行の数・そのうち校正済み・人が whisper の文字に打ち直した数。
  札で戻すと印も元の文字の記録も消え、機械の出力 original は直す前の文字なので、**編集の画面で戻した D は数えられない**(注意に出す)。
  確かめるの答えは別に数える(d.checked。答えに残る反映の前の印 applied.before で D の行と分かる)
- C(余分の掃除)は文書の記録だけ: 最初の認識の記録 recognition.runs[].fill の dup(末尾の重複を捨てた)・diarization.fillDropped(定型の幻覚で捨てた)
- 再認識(範囲・全体・疑わしい所)をした文書は original が置き換わるので、A の数に入れず「再認識あり」として数だけ出す
- --since / --until(原則 4: 時期で分ける)は 行の時刻で絞る(until はその日を含む)。行の時刻 = 答えの時刻(答えのある行)、
  無ければ人の行の校正した時刻 proofedAt、それも無ければ文書の更新時刻 updatedAt
- 判定できた A の行が 30 未満のときは「まだ少ない(参考)」と出す(少ないデータで後処理を残すか決めない。入口の条件 accuracy.GOALS の fill と同じ値)
- 結果の check = 答えの数(期間の中)と、A・E・D のどれに入ったか・行が見つからず数えなかった数(unmatched)
"""
import argparse
import os
import sys

from eval.tools import _evalcommon as C  # noqa: E402  共通の部品(作業データの場所・時期・率・保存。src を sys.path に足す)
from eval.tools._evalcommon import rate, read_json  # noqa: E402
from eval.tools.eval_asr import runs_of  # noqa: E402  文書の認識の記録 recognition.runs
from ytt import docloc  # noqa: E402
from ytt.schemas import num_or  # noqa: E402
from ytt.txbase import alt_fold  # noqa: E402  比べるときの寄せ方(2 つ目のエンジンの候補・eval_alt と同じ)
from pipeline.transcribe.fill import FILL_NAME_FLAG as NAME_FLAG  # noqa: E402  D の印(印の文の持ち主)
from pipeline.transcribe.llm import LLM_SCHEMA, llm_dist  # noqa: E402  <id>.llm.json の形・編集距離(本番の LLM の後処理と同じ)

SCHEMA = "youtube-tools-fill-eval/v1"
FEW_ROWS = 30                      # 判定できた A の行がこれより少ないときは「まだ少ない(参考)」
MAX_DOC_BYTES = 64 * 1024 * 1024
MAX_EDIT_CHARS = 400               # 編集距離を測る文字の上限(長い行は測らない)
OVERLAP_SHARE = 0.5                # 機械の行の長さのこの割合以上重なる今の行を「同じ所」とみなす
KINDS = ("kept", "edited", "reverted", "deleted", "unchecked")
KIND_LABELS = {"kept": "残した", "edited": "直した", "reverted": "戻した", "deleted": "消した", "unchecked": "未確認"}
ANSWER_KIND = {"1": "kept", "2": "reverted", "other": "edited"}   # 確かめるの read:fill の答え -> 分け方(読みのカードの反映。10-31 に消した)
NOTES = ["編集の画面で戻した D(名簿の呼び名)は数えられない(札で戻すと印も元の文字も消えるため。確かめるの答えは d.checked に数える)",
         "A の見つけ方は「機械の出力の行に確信度が無い」こと。再認識した文書は数えていない",
         "答えの無い行は校正済みの行だけを判定する(直した・戻した・消したも、校正済みでなければ未確認)"]


def fold(text):
    """比べるときだけ寄せた文字(ytt.txbase.alt_fold を行の文字全体に)"""
    return alt_fold(str(text or ""))


def edit_distance(a, b):
    """編集距離(どちらかが MAX_EDIT_CHARS を超えたら None)"""
    if len(a) > MAX_EDIT_CHARS or len(b) > MAX_EDIT_CHARS:
        return None
    return llm_dist(a, b)


def rows_of(items):
    """時刻と文字のある行だけ(start・end が数・end > start)"""
    out = []
    for r in items if isinstance(items, list) else []:
        if not isinstance(r, dict):
            continue
        a, b = num_or(r.get("start")), num_or(r.get("end"))
        if a is not None and b is not None and b > a:
            out.append(r)
    return out


def overlap(r, a, b):
    return max(0.0, min(float(r["end"]), b) - max(float(r["start"]), a))


def first_run(doc):
    """最初の認識の記録(recognition.runs の kind の無いもの)と、再認識の記録があるか"""
    runs = runs_of(doc)
    first = next((r for r in runs if not r.get("kind")), None)
    return first, any(r.get("kind") for r in runs)


# ---------------------------------------------------------------- 確かめるの答え(read:fill。読むだけ)

def answer_of(answers, tid, seg):
    return answers.get((tid, str(seg.get("id")))) if answers and seg is not None and seg.get("id") is not None else None


def answer_before(ans):
    """答えの反映の前の行 {text, fill, flag}(戻す・打つのときだけ記録に残る。無ければ {})"""
    b = (ans.get("applied") or {}).get("before") if isinstance(ans.get("applied"), dict) else None
    return b if isinstance(b, dict) else {}


def answer_time(ans):
    t = ans.get("at")
    return t if isinstance(t, (int, float)) and not isinstance(t, bool) else None


def checked_around(segs, a, b):
    """a〜b に重なる今の行が無いとき、前後の隣の行(端なら在る側だけ)がどちらも校正済みか(人がその辺りを見て消した)"""
    m = (a + b) / 2.0
    before = [s for s in segs if (float(s["start"]) + float(s["end"])) / 2.0 < m]
    after = [s for s in segs if (float(s["start"]) + float(s["end"])) / 2.0 >= m]
    near = ([max(before, key=lambda s: float(s["end"]))] if before else []) + ([min(after, key=lambda s: float(s["start"]))] if after else [])
    return bool(near) and all(s.get("proofed") is True for s in near)


def raw_text(raw, a, b):
    """生の結果(asr.json の行)のうち、a〜b に半分以上入る行の文字をつないだもの(無ければ None)"""
    picked = [r for r in raw if overlap(r, a, b) >= OVERLAP_SHARE * (float(r["end"]) - float(r["start"]))]
    return "".join(str(r.get("text") or "") for r in picked) if picked else None


def match_seg(segs, o):
    """機械の行 o と同じ所の今の行(時刻がちょうど同じ行 → いちばん長く重なる行。o の長さの半分以上重なるときだけ)。無ければ None"""
    a, b = float(o["start"]), float(o["end"])
    for s in segs:
        if round(float(s["start"]), 2) == round(a, 2) and round(float(s["end"]), 2) == round(b, 2):
            return s
    best, best_ov = None, OVERLAP_SHARE * (b - a)
    for s in segs:
        ov = overlap(s, a, b)
        if ov >= best_ov:
            best, best_ov = s, ov
    return best


def closer_of(final, filled, whisper):
    """直した行で人の最終が 別の読み / whisper のどちらに近いか("fill" | "whisper" | "same" | None)"""
    if whisper is None:
        return None
    df, dw = edit_distance(final, filled), edit_distance(final, whisper)
    if df is None or dw is None:
        return None
    return "fill" if df < dw else "whisper" if dw < df else "same"


def judge_row(o, seg, raw, answer=None, segs=None):
    """A の 1 行を分ける -> (kind, 近さ)。近さ = closer_of。answer = その行の確かめるの答え(あればそれが正)。
    segs = 今の行(消した行の前後が校正済みかを見る。None なら消したをそのまま数える)"""
    filled = fold(o.get("text"))
    if answer is not None:
        kind = ANSWER_KIND[answer["answer"]["choice"]]
        if kind != "edited":
            return kind, None
        bf = answer_before(answer).get("fill")
        whisper = bf.get("from") if isinstance(bf, dict) and isinstance(bf.get("from"), str) else raw_text(raw, float(o["start"]), float(o["end"]))
        return kind, closer_of(fold(answer["answer"].get("text")), filled, None if whisper is None else fold(whisper))
    if seg is None:
        return ("deleted" if segs is None or checked_around(segs, float(o["start"]), float(o["end"])) else "unchecked"), None
    final = fold(seg.get("text"))
    if final == filled or not seg.get("proofed"):   # 校正済みでない行は、文字が変わっていても人の判断とは限らない(後の機械の処理・見る前)
        return ("kept" if seg.get("proofed") else "unchecked"), None
    fill = seg.get("fill") if isinstance(seg.get("fill"), dict) else None
    whisper = fill.get("from") if fill else raw_text(raw, float(o["start"]), float(o["end"]))
    whisper = None if whisper is None else fold(whisper)
    if whisper is not None and final == whisper:
        return "reverted", None
    return "edited", closer_of(final, filled, whisper)


def row_time(seg, doc):
    t = seg.get("proofedAt") if seg is not None else None
    return t if isinstance(t, (int, float)) and not isinstance(t, bool) else doc.get("updatedAt")


def empty_agg():
    return {"docs": 0, "rows": 0, **{k: 0 for k in KINDS}, "closer": {"fill": 0, "whisper": 0, "same": 0}}


def add_kind(agg, kind, closer):
    agg["rows"] += 1
    agg[kind] += 1
    if closer:
        agg["closer"][closer] += 1


def finish(agg):
    """率(未確認を除いた判定できた行で)を足す"""
    judged = agg["kept"] + agg["edited"] + agg["reverted"] + agg["deleted"]
    agg["judged"] = judged
    agg["keptRate"] = rate(agg["kept"], judged)
    agg["revertRate"] = rate(agg["reverted"] + agg["deleted"], judged)
    agg["editRate"] = rate(agg["edited"], judged)
    agg["few"] = judged < FEW_ROWS
    return agg


def judge_llm_item(it, seg, answer=None, segs=None):
    """E(LLM が直した行)の 1 件を分ける: 答えがあればそれ(ANSWER_KIND)。無ければ 消した(同じ時間の行が無く前後が校正済み)・
    戻した(人の最終が直す前の行のまま)・残した(直した文字が残っている)・直した(それ以外)。どれも校正済みのときだけ(違えば未確認)"""
    if answer is not None:
        return ANSWER_KIND[answer["answer"]["choice"]]
    if seg is None:
        return "deleted" if segs is None or checked_around(segs, float(it["start"]), float(it["end"])) else "unchecked"
    if not seg.get("proofed"):
        return "unchecked"
    final, to = fold(seg.get("text")), fold(it.get("to"))
    if final == fold(it.get("text")):
        return "reverted"
    if to and to in final:
        return "kept"
    return "edited"


def llm_applied(llm_doc):
    """<id>.llm.json(schema youtube-tools-llm/v1)の当てた案(rejected が None・時刻がある)-> [案]"""
    if not isinstance(llm_doc, dict) or llm_doc.get("schema") != LLM_SCHEMA:
        return []
    return [it for it in rows_of(llm_doc.get("items")) if it.get("rejected") is None and isinstance(it.get("to"), str)]


def empty_d():
    return {"rows": 0, "proofed": 0, "retyped": 0, "checked": {"kept": 0, "reverted": 0, "edited": 0}}


def is_name_row(flag, fill):
    """D(名簿の呼び名に直した行)の印か。LLM の印も同じ頭(画面の「戻す」の規則)なので by で分ける = E で数える"""
    fill = fill if isinstance(fill, dict) else {}
    return NAME_FLAG in str(flag or "") and fill.get("by") != "llm"


def judge_doc(doc, raw, since_ms=None, until_ms=None, llm_items=None, answers=None, tid=None):
    """1 本の文書 -> {"a": A の集計, "e": E(LLM)の集計, "d": D の数, "c": C の数, "rerun": 再認識あり, "used": {"a"|"e"|"d": 使った答えの id の集合}}
    (A・E は時期の中の行だけ)。llm_items = <id>.llm.json の当てた案(llm_applied)。answers = read_answers の結果・tid = この文書の id"""
    segs = rows_of(doc.get("segments"))
    tid = str(doc.get("id") or "") if tid is None else tid
    first, rerun = first_run(doc)
    fill_rec = first.get("fill") if first and isinstance(first.get("fill"), dict) else {}
    diar = doc.get("diarization") if isinstance(doc.get("diarization"), dict) else {}
    used = {"a": set(), "e": set(), "d": set()}
    out = {"a": empty_agg(), "rerun": bool(rerun), "used": used,
           "c": {"dup": int(fill_rec.get("dup") or 0), "dropped": int(diar.get("fillDropped") or 0)}, "d": empty_d()}

    def when(seg, ans):
        return answer_time(ans) if ans is not None else row_time(seg, doc)
    for s in segs:
        f = s.get("fill") if isinstance(s.get("fill"), dict) else {}
        ans = answer_of(answers, tid, s)
        bf = answer_before(ans) if ans is not None else {}
        if is_name_row(s.get("flag"), f):
            out["d"]["rows"] += 1
            out["d"]["proofed"] += 1 if s.get("proofed") else 0
            out["d"]["retyped"] += 1 if f and fold(s.get("text")) == fold(f.get("from")) else 0
        elif not (ans is not None and is_name_row(bf.get("flag"), bf.get("fill"))):
            continue
        if ans is not None and C.in_period(answer_time(ans), since_ms, until_ms):   # 確かめるで答えた D(戻す・打つは印が消えているので反映の前の印で分かる)
            out["d"]["checked"][ANSWER_KIND[ans["answer"]["choice"]]] += 1
            used["d"].add(ans["id"])
    out["e"] = empty_agg()
    for it in llm_items or []:
        seg = match_seg(segs, it)
        ans = answer_of(answers, tid, seg)
        if C.in_period(when(seg, ans), since_ms, until_ms):
            add_kind(out["e"], judge_llm_item(it, seg, ans, segs), None)
            if ans is not None:
                used["e"].add(ans["id"])
    if rerun:
        return out
    for o in rows_of(doc.get("original")):
        if "avg_logprob" in o:
            continue
        seg = match_seg(segs, o)
        ans = answer_of(answers, tid, seg)
        if not C.in_period(when(seg, ans), since_ms, until_ms):
            continue
        kind, closer = judge_row(o, seg, raw, ans, segs)
        add_kind(out["a"], kind, closer)
        if ans is not None:
            used["a"].add(ans["id"])
    return out


def iter_docs(tdir):
    """評価用でない・後処理を当てた文書 -> (id, 文書)"""
    for tid, doc in C.iter_docs(os.path.dirname(tdir), limit=MAX_DOC_BYTES):   # tdir = 作業データ/transcripts
        params = doc.get("params") if doc is not None and isinstance(doc.get("params"), dict) else {}
        if doc is None or doc.get("evalSet") or not (params.get("autoFill") or params.get("autoLlm")):
            continue
        yield tid, doc


def evaluate(data_dir=None, since=None, until=None):
    """作業データ全体 -> 結果(JSON にそのまま出せる形)"""
    root = C.locate("transcribe", data_dir)
    tdir = os.path.join(root, "transcripts")
    since_ms, until_ms = C.period(since, until)
    answers = C.read_answers(C.locate("app", data_dir), "read", "fill", ANSWER_KIND)
    in_range = {r["id"] for r in answers.values() if C.in_period(answer_time(r), since_ms, until_ms)}
    used = {"a": set(), "e": set(), "d": set()}
    total, per_doc, e_tot = empty_agg(), [], empty_agg()
    d_tot, c_tot = empty_d(), {"dup": 0, "dropped": 0}
    docs = rerun_docs = 0
    for tid, doc in iter_docs(tdir):
        docs += 1
        asr = read_json(docloc.doc_file(tid, ".asr.json", root), None, MAX_DOC_BYTES)
        raw = rows_of(asr.get("segments")) if isinstance(asr, dict) else []
        items = llm_applied(read_json(docloc.doc_file(tid, ".llm.json", root), None, MAX_DOC_BYTES))
        r = judge_doc(doc, raw, since_ms, until_ms, items, answers, tid)
        rerun_docs += 1 if r["rerun"] else 0
        for k in used:
            used[k] |= r["used"][k]
        if r["e"]["rows"]:
            e_tot["docs"] += 1
            for k in KINDS + ("rows",):
                e_tot[k] += r["e"][k]
        for k in ("rows", "proofed", "retyped"):
            d_tot[k] += r["d"][k]
        for k in d_tot["checked"]:
            d_tot["checked"][k] += r["d"]["checked"][k]
        for k in c_tot:
            c_tot[k] += r["c"][k]
        a = r["a"]
        if a["rows"]:
            total["docs"] += 1
            for k in KINDS:
                total[k] += a[k]
            total["rows"] += a["rows"]
            for k in a["closer"]:
                total["closer"][k] += a["closer"][k]
            per_doc.append({"id": tid, "title": str(doc.get("title") or "")[:60], **finish(a)})
    per_doc.sort(key=lambda x: (x["keptRate"] if x["keptRate"] is not None else 2, -x["rows"]))
    check = {"answers": len(in_range), **{k: len(v) for k, v in used.items()}, "unmatched": len(in_range - used["a"] - used["e"] - used["d"])}
    return {"schema": SCHEMA, "rev": C.git_rev(), "period": C.period_label(since, until), "root": root,
            "docs": docs, "rerunDocs": rerun_docs, "a": finish(total), "e": finish(e_tot), "d": d_tot, "c": c_tot, "check": check,
            "perDoc": per_doc[:10], "notes": NOTES}


def print_report(res):
    a = res["a"]
    print("認識のあとの後処理の様子見(%s・後処理を当てた文書 %d 本・再認識ありで数えない %d 本)" % (res["period"], res["docs"], res["rerunDocs"]))
    print("A 別の読みで埋めた行: %d 行(%d 本)・判定できた %d 行%s" % (a["rows"], a["docs"], a["judged"], "  ※まだ少ない(参考)" if a["few"] else ""))
    for k in KINDS:
        print("  %-4s %5d" % (KIND_LABELS[k], a[k]))
    print("  残した率 %s・戻した/消した率 %s・直した率 %s(未確認を除く)" % (C.pct(a["keptRate"], 0), C.pct(a["revertRate"], 0), C.pct(a["editRate"], 0)))
    cl = a["closer"]
    if a["edited"]:
        print("  直した行で人の最終が近かった方: 別の読み %d・whisper %d・同じ %d" % (cl["fill"], cl["whisper"], cl["same"]))
    e = res["e"]
    print("E LLM が名簿の呼び名に直した行: %d 行(%d 本)・判定できた %d 行%s  残した %d・直した %d・戻した %d・消した %d・未確認 %d" % (
        e["rows"], e["docs"], e["judged"], "  ※まだ少ない(参考)" if e["few"] else "", e["kept"], e["edited"], e["reverted"], e["deleted"], e["unchecked"]))
    d = res["d"]
    print("D 名簿の呼び名に直した行(印が残っているもの): %d 行・校正済み %d・whisper の文字に打ち直した %d" % (d["rows"], d["proofed"], d["retyped"]))
    dc = d["checked"]
    if any(dc.values()):
        print("  確かめるの答え: 残した %d・戻した %d・直した %d" % (dc["kept"], dc["reverted"], dc["edited"]))
    print("C 余分の掃除(記録): 末尾の重複 %d 行・定型の幻覚 %d 行" % (res["c"]["dup"], res["c"]["dropped"]))
    ck = res["check"]
    print("確かめるの答え(read:fill): %d 件・A に入れた %d・E に %d・D に %d・行が見つからず数えなかった %d" % (ck["answers"], ck["a"], ck["e"], ck["d"], ck["unmatched"]))
    if res["perDoc"]:
        print("文書ごと(残した率が低い順):")
        for x in res["perDoc"]:
            print("  %s %-24s 行 %3d 残 %3d 直 %3d 戻 %3d 消 %3d 未 %3d" % (x["id"], x["title"][:24], x["rows"], x["kept"], x["edited"], x["reverted"], x["deleted"], x["unchecked"]))
    for n in res["notes"]:
        print("注意: " + n)


def main(argv=None):
    p = argparse.ArgumentParser(description="認識のあとの後処理(別の読み・名簿の呼び名)を人が残したか・直したか・戻したかで測る(作業データは読むだけ)")
    p.add_argument("--since", help="この日(YYYY-MM-DD)以後だけ(行の時刻 = 校正した時刻 proofedAt、無ければ文書の更新時刻)")
    p.add_argument("--until", help="この日(YYYY-MM-DD。この日を含む)までだけ")
    p.add_argument("--json", action="store_true", help="同じ形の JSON を 文字起こしの作業データの evals/fill/<日時>.json に残す")
    p.add_argument("--data-dir", help="作業データの親フォルダ(既定 %%LOCALAPPDATA%%/youtube-tools。テスト用)")
    args = p.parse_args(argv)
    C.utf8_stdout()
    res = evaluate(args.data_dir, args.since, args.until)
    print_report(res)
    if args.json:
        print("保存: " + C.save(res, res["root"], "fill"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
