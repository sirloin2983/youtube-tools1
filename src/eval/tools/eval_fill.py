#!/usr/bin/env python3
"""認識のあとの後処理(編集 0.60.0 の ed_fill。A 文字の少ない行を別の読みで埋める・D 名簿の呼び名の 1 字違いを直す・C 余分の掃除)を、
人が残したか・直したか・戻したかで測る道具(計画の K1「後処理の様子見の物差し」。追加の校正は要らない = 普段の校正のついでに数が貯まる)。

    python src/eval/tools/eval_fill.py [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--json] [--data-dir 作業データの親フォルダ]

- 作業データは**読むだけ**(文字起こしの transcripts/<id>.json と、whisper の生の結果 <id>.asr.json)。何も書き換えない。
  --json のときだけ、結果を文字起こしの作業データの evals/fill/<日時>.json に残す(schema youtube-tools-fill-eval/v1。置き場所の規則は eval_alt.py と同じ)
- 対象 = 評価用でない文書のうち、最初の文字起こしで後処理を当てたもの(params.autoFill。評価用には当てない決まり)。editor の部品は読まない(文書の JSON だけで判定する)
- A(別の読みで埋めた行)の見つけ方: 機械の出力 original のうち、確信度(avg_logprob)を持たない行。埋めた行は確信度を持たない(ed_fill.fill_apply)ので、
  画面の「別の読み」の札で戻して印(行の fill)が消えたあとでも、どこを埋めたかが分かる。その時間に重なる今の行(人の最終)を見て分ける:
    残した … 人の最終が別の読みのまま(寄せた文字が同じ)で、校正済み
    直した … 別の読みとも whisper の文字とも違う文字に直した(人が直した = 別の読みは当たらなかったが、手がかりにはなったかもしれない)。
              直した行は、人の最終が別の読みと whisper の文字のどちらに近いか(寄せた文字の編集距離)も数える
    戻した … 人の最終が whisper の文字(行の fill.from。札で戻して印が消えたときは生の結果 asr.json の同じ時間の文字)と同じ
    消した … その時間に重なる今の行が無い(人が行を消した = 別の読みは幻覚だった)
    未確認 … 別の読みのまま校正済みでない(人がまだ見ていない)。**率は 未確認 を除いて出す**
  比べるときの文字の寄せ方: NFKC・小文字・カタカナ → ひらがな・文字と数字だけ(記号・句読点・空白・伸ばし ー を無視)
- E(LLM が名簿の呼び名に直した行。編集 0.61.0 の ed_llm): <id>.llm.json の当てた案(行の時刻つき)と同じ時間の今の行で、残した・直した・戻した・消した・未確認に分ける
  (戻した = 人の最終が直す前の行のまま。札で戻して印が消えても分かる)。<id>.llm.json に時刻が無い(0.61.0 より前の試し)案は数えない
- D(名簿の呼び名に直した行): 印 FILL_NAME_FLAG が残っている行の数・そのうち校正済み・人が whisper の文字に打ち直した数。
  札で戻すと印も元の文字の記録も消え、機械の出力 original は直す前の文字なので、**戻した D は数えられない**(注意に出す)
- C(余分の掃除)は文書の記録だけ: 最初の認識の記録 recognition.runs[].fill の dup(末尾の重複を捨てた)・diarization.fillDropped(定型の幻覚で捨てた)
- 再認識(範囲・全体・疑わしい所)をした文書は original が置き換わるので、A の数に入れず「再認識あり」として数だけ出す
- --since / --until(原則 4: 時期で分ける)は 行の時刻で絞る(until はその日を含む)。行の時刻 = 人の行の校正した時刻 proofedAt(あれば)、無ければ文書の更新時刻 updatedAt
- 判定できた A の行が 30 未満のときは「まだ少ない(参考)」と出す(少ないデータで後処理を残すか決めない = B4 は G2 の校正と合わせて)
"""
import argparse
import os
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(os.path.dirname(HERE))   # tools -> eval -> src
if not __package__:   # スクリプトとして起動したとき(py -3.10 src/eval/tools/eval_fill.py)だけ。src を先頭に・この道具のフォルダは外す(兄弟は絶対 import で読む。見本 pipeline/transcribe/worker.py)
    sys.path[:] = [SRC] + [p for p in sys.path if os.path.normcase(os.path.abspath(p or os.curdir)) not in (os.path.normcase(HERE), os.path.normcase(SRC))]
from eval.tools import _evalcommon as C  # noqa: E402  共通の部品(作業データの場所・時期・率・保存。src を sys.path に足す)
from eval.tools._evalcommon import rate, read_json  # noqa: E402
from ytt import docloc  # noqa: E402
from pipeline.transcribe.llm import llm_dist  # noqa: E402  編集距離(本番の LLM の後処理と同じ)

SCHEMA = "youtube-tools-fill-eval/v1"
LLM_SCHEMA = "youtube-tools-llm/v1"   # 編集の <id>.llm.json(src/pipeline/transcribe/llm.py の LLM_SCHEMA)
FEW_ROWS = 30                      # 判定できた A の行がこれより少ないときは「まだ少ない(参考)」
MAX_DOC_BYTES = 64 * 1024 * 1024
MAX_EDIT_CHARS = 400               # 編集距離を測る文字の上限(長い行は測らない)
OVERLAP_SHARE = 0.5                # 機械の行の長さのこの割合以上重なる今の行を「同じ所」とみなす
NAME_FLAG = "名簿の呼び名に直した"   # src/pipeline/transcribe/fill.py の FILL_NAME_FLAG の頭(印の文はそちらが正)
KINDS = ("kept", "edited", "reverted", "deleted", "unchecked")
KIND_LABELS = {"kept": "残した", "edited": "直した", "reverted": "戻した", "deleted": "消した", "unchecked": "未確認"}
NOTES = ["戻した D(名簿の呼び名)は数えられない(札で戻すと印も元の文字も消えるため)",
         "A の見つけ方は「機械の出力の行に確信度が無い」こと。再認識した文書は数えていない"]


def fold(text):
    """比べるときだけ寄せた文字(NFKC・小文字・カタカナ → ひらがな・文字と数字だけ。伸ばし ー も捨てる)"""
    out = []
    for ch in unicodedata.normalize("NFKC", str(text or "")).lower():
        if "ァ" <= ch <= "ヶ":
            ch = chr(ord(ch) - 0x60)
        if ch == "ー" or unicodedata.category(ch)[0] not in "LN":
            continue
        out.append(ch)
    return "".join(out)


def edit_distance(a, b):
    """編集距離(どちらかが MAX_EDIT_CHARS を超えたら None)"""
    if len(a) > MAX_EDIT_CHARS or len(b) > MAX_EDIT_CHARS:
        return None
    return llm_dist(a, b)


def num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def rows_of(items):
    """時刻と文字のある行だけ(start・end が数・end > start)"""
    out = []
    for r in items if isinstance(items, list) else []:
        if not isinstance(r, dict):
            continue
        a, b = num(r.get("start")), num(r.get("end"))
        if a is not None and b is not None and b > a:
            out.append(r)
    return out


def overlap(r, a, b):
    return max(0.0, min(float(r["end"]), b) - max(float(r["start"]), a))


def first_run(doc):
    """最初の認識の記録(recognition.runs の kind の無いもの)と、再認識の記録があるか"""
    runs = (doc.get("recognition") or {}).get("runs") if isinstance(doc.get("recognition"), dict) else None
    runs = [r for r in runs if isinstance(r, dict)] if isinstance(runs, list) else []
    first = next((r for r in runs if not r.get("kind")), None)
    return first, any(r.get("kind") for r in runs)


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


def judge_row(o, seg, raw):
    """A の 1 行を分ける -> (kind, 近さ)。近さ = 直した行で人の最終が 別の読み / whisper のどちらに近いか("fill" | "whisper" | "same" | None)"""
    if seg is None:
        return "deleted", None
    filled, final = fold(o.get("text")), fold(seg.get("text"))
    fill = seg.get("fill") if isinstance(seg.get("fill"), dict) else None
    whisper = fill.get("from") if fill else raw_text(raw, float(o["start"]), float(o["end"]))
    whisper = None if whisper is None else fold(whisper)
    if final == filled:
        return ("kept" if seg.get("proofed") else "unchecked"), None
    if whisper is not None and final == whisper:
        return "reverted", None
    if whisper is None:
        return "edited", None
    df, dw = edit_distance(final, filled), edit_distance(final, whisper)
    if df is None or dw is None:
        return "edited", None
    return "edited", ("fill" if df < dw else "whisper" if dw < df else "same")


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


def judge_llm_item(it, seg):
    """E(LLM が直した行)の 1 件を分ける: 消した(同じ時間の行が無い)・戻した(人の最終が直す前の行のまま)・残した / 未確認(直した文字が残っている。校正済みかで分ける)・直した(それ以外)"""
    if seg is None:
        return "deleted"
    final, to = fold(seg.get("text")), fold(it.get("to"))
    if final == fold(it.get("text")):
        return "reverted"
    if to and to in final:
        return "kept" if seg.get("proofed") else "unchecked"
    return "edited"


def llm_applied(llm_doc):
    """<id>.llm.json(schema youtube-tools-llm/v1)の当てた案(rejected が None・時刻がある)-> [案]"""
    if not isinstance(llm_doc, dict) or llm_doc.get("schema") != LLM_SCHEMA:
        return []
    return [it for it in rows_of(llm_doc.get("items")) if it.get("rejected") is None and isinstance(it.get("to"), str)]


def judge_doc(doc, raw, since_ms=None, until_ms=None, llm_items=None):
    """1 本の文書 -> {"a": A の集計, "e": E(LLM)の集計, "d": D の数, "c": C の数, "rerun": 再認識あり}(A・E は時期の中の行だけ)。
    llm_items = <id>.llm.json の当てた案(llm_applied)"""
    segs = rows_of(doc.get("segments"))
    first, rerun = first_run(doc)
    fill_rec = first.get("fill") if first and isinstance(first.get("fill"), dict) else {}
    diar = doc.get("diarization") if isinstance(doc.get("diarization"), dict) else {}
    out = {"a": empty_agg(), "rerun": bool(rerun),
           "c": {"dup": int(fill_rec.get("dup") or 0), "dropped": int(diar.get("fillDropped") or 0)},
           "d": {"rows": 0, "proofed": 0, "retyped": 0}}
    for s in segs:
        f = s.get("fill") if isinstance(s.get("fill"), dict) else {}
        if NAME_FLAG in str(s.get("flag") or "") and f.get("by") != "llm":   # LLM の印も同じ頭(画面の「戻す」の規則)なので by で分ける = E で数える
            out["d"]["rows"] += 1
            out["d"]["proofed"] += 1 if s.get("proofed") else 0
            out["d"]["retyped"] += 1 if f and fold(s.get("text")) == fold(f.get("from")) else 0
    out["e"] = empty_agg()
    for it in llm_items or []:
        seg = match_seg(segs, it)
        if C.in_period(row_time(seg, doc), since_ms, until_ms):
            add_kind(out["e"], judge_llm_item(it, seg), None)
    if rerun:
        return out
    for o in rows_of(doc.get("original")):
        if "avg_logprob" in o:
            continue
        seg = match_seg(segs, o)
        if not C.in_period(row_time(seg, doc), since_ms, until_ms):
            continue
        kind, closer = judge_row(o, seg, raw)
        add_kind(out["a"], kind, closer)
    return out


def iter_docs(tdir):
    """評価用でない・後処理を当てた文書 -> (id, 文書)"""
    root = os.path.dirname(tdir)   # tdir = 作業データ/transcripts
    for tid in docloc.iter_tids(root):   # 案件の 作業用 に置いた文書も(索引があれば)
        doc = read_json(docloc.doc_file(tid, ".json", root), None, MAX_DOC_BYTES)
        params = doc.get("params") if isinstance(doc, dict) and isinstance(doc.get("params"), dict) else {}
        if not isinstance(doc, dict) or doc.get("evalSet") or not (params.get("autoFill") or params.get("autoLlm")):
            continue
        yield tid, doc


def evaluate(data_dir=None, since=None, until=None):
    """作業データ全体 -> 結果(JSON にそのまま出せる形)"""
    root = C.locate("transcribe", data_dir)
    tdir = os.path.join(root, "transcripts")
    since_ms, until_ms = C.period(since, until)
    total, per_doc, e_tot = empty_agg(), [], empty_agg()
    d_tot, c_tot = {"rows": 0, "proofed": 0, "retyped": 0}, {"dup": 0, "dropped": 0}
    docs = rerun_docs = 0
    for tid, doc in iter_docs(tdir):
        docs += 1
        asr = read_json(docloc.doc_file(tid, ".asr.json", root), None, MAX_DOC_BYTES)
        raw = rows_of(asr.get("segments")) if isinstance(asr, dict) else []
        items = llm_applied(read_json(docloc.doc_file(tid, ".llm.json", root), None, MAX_DOC_BYTES))
        r = judge_doc(doc, raw, since_ms, until_ms, items)
        rerun_docs += 1 if r["rerun"] else 0
        if r["e"]["rows"]:
            e_tot["docs"] += 1
            for k in KINDS + ("rows",):
                e_tot[k] += r["e"][k]
        for k in d_tot:
            d_tot[k] += r["d"][k]
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
    return {"schema": SCHEMA, "rev": C.git_rev(), "period": C.period_label(since, until), "root": root,
            "docs": docs, "rerunDocs": rerun_docs, "a": finish(total), "e": finish(e_tot), "d": d_tot, "c": c_tot, "perDoc": per_doc[:10], "notes": NOTES}


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
    print("C 余分の掃除(記録): 末尾の重複 %d 行・定型の幻覚 %d 行" % (res["c"]["dup"], res["c"]["dropped"]))
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
