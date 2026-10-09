#!/usr/bin/env python3
"""LLM の後処理(提案 P18。編集の src/editor/ed_llm.py。plan/llm-postfix.md)を、確かめ済みの評価用の文書で測る道具。

    python dev/eval_llm.py [--docs id,id] [--limit 30] [--only name,mis] [--dry] [--label 名前] [--no-save]

- 作業データは**読むだけ**(文字起こしの transcripts/<id>.json・<id>.asr.json)。結果は 文字起こしの作業データの evals/asr/<日時>_llm-base.json と _llm-on.json
  (dev/eval_asr.py compare でそのまま比べられる形)と、提案の中身 evals/llm/<日時>.json に残す(--no-save で残さない)
- 対象: dev/eval_asr.py と同じ選び方(既定は評価用の確かめ済みだけ)。機械の出力 original(評価用には辞書・後処理が当たっていない)に LLM の直しを当てる前と後を、
  eval_asr の採点(score_doc・summarize = 画面の精度の測定と同じ規則)で比べ、最後に compare の対の差(95% の範囲)を出す
- 規則は編集の ed_llm をそのまま使う(選ぶ llm_pick・聞く llm_messages・読む llm_parse・検査 llm_guard・上限 llm_cap・当てる llm_apply = 本番と同じ)。
  この道具だけの選び方: (b) whisper の語の確信度(生の結果 asr.json の words)が LOW_PROB 未満の 2 字以上の語(同じ字の繰り返しは除く)。
  10-09 の測定で外れが多かったので本番には入れていない(--only name,mis で本番と同じ選び方)
- LLM は編集と同じ tx_engines.LlamaText(作業データの models/llm-gguf/ の Qwen3-8B Q4_K_M・bin/llama.cpp-*-vulkan/ の llama-server。大きさと SHA-256 を確かめ、
  無ければ取得する = 編集の初回と同じ)を、このプロセスの中で起動する
- --dry は選ぶだけ(LLM を起動しない)。選んだ所の数を出す
- 当たり: 当てた直しのうち、人の最終(同じ時間の校正済みの行)に置き換え後の文字があり、置き換え前の文字が無いもの
- 10-09 の結果(22 本): 名前の手がかりだけで CER 13.5 → 13.4%・名前 28 → 34/53(plan/llm-postfix.md の 8)
"""
import argparse
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import _evalcommon as C  # noqa: E402  共通の部品(作業データの場所・保存。src を sys.path に足す)
import eval_asr as E  # noqa: E402  選び方と採点(score_doc・summarize・compare)
if C.EDITOR not in sys.path:
    sys.path.insert(0, C.EDITOR)
import ed_llm  # noqa: E402  本番の規則(規則の部分は編集のほかの部品を読まない)

LOW_PROB = 0.35          # whisper の語の確信度がこれ未満なら疑わしい(この道具だけ)
fold = ed_llm.llm_fold
doc_members = ed_llm.llm_members
alias_targets = ed_llm.llm_targets
near_spans = ed_llm.llm_near
build_messages = ed_llm.llm_messages
parse_reply = ed_llm.llm_parse
guard = ed_llm.llm_guard
roster_names = ed_llm.llm_names
cap_edits = ed_llm.llm_cap


def low_prob_words(row, raw):
    """生の結果のうち、行の時間に入る語で確信度が LOW_PROB 未満・2 字以上(同じ字の繰り返しは除く)・行の文字にあるもの -> [語]"""
    out = []
    a, b = float(row["start"]), float(row["end"])
    for seg in raw:
        for w in seg.get("words") or []:
            if not isinstance(w, list) or len(w) < 4 or not isinstance(w[3], (int, float)):
                continue
            t = str(w[2] or "").strip()
            if (w[3] < LOW_PROB and len(set(fold(t))) >= 2 and a - 0.2 <= float(w[0]) and float(w[1]) <= b + 0.2
                    and t in row["text"] and t not in out):
                out.append(t)
    return out


def pick_doc(doc, raw, members, limit=30):
    """疑わしい所 = 本番の llm_pick(名簿の誤りやすい形・呼び名に 1 字違い)+ 確信度の低い語(lowprob)。limit 箇所まで"""
    rows = doc.get("original") or []
    picks = ed_llm.llm_pick(rows, members, doc, 10 ** 6)
    for i, r in enumerate(rows):
        if r.get("text"):
            picks += [{"row": i, "span": w, "why": "lowprob", "cands": []} for w in low_prob_words(r, raw)]
    picks = [p for p in picks if not any(q is not p and q["row"] == p["row"] and p["span"] in q["span"] and len(q["span"]) > len(p["span"]) for q in picks)]
    order = {"mis": 0, "name": 1, "lowprob": 2}
    picks.sort(key=lambda p: (order[p["why"]], p["row"]))
    return picks[:limit]


def apply_edits(rows, accepted):
    """original の写しに直しを当てる(印は付けない)。accepted = [(行の番号, 案)] -> 新しい行の一覧(行の数・時刻は同じ)"""
    return ed_llm.llm_apply([dict(r) for r in rows], accepted, mark=False)


def judge_hit(doc, row, e):
    """当てた直しが人の最終と合うか: "hit"(置き換え後の文字が人の行にあり、前の文字が無い)・"miss"(前の文字が人の行に残る)・"other" """
    a, b = float(row["start"]), float(row["end"])
    final = "".join(str(s.get("text") or "") for s in doc.get("segments") or []
                    if s.get("proofed") and min(b, float(s["end"])) - max(a, float(s["start"])) > 0)
    ff, ft, fin = fold(e["from"]), fold(e["to"]), fold(final)
    if ft and ft in fin and ff not in fin:
        return "hit"
    if ff and ff in fin:
        return "miss"
    return "other"


def run_doc(doc, raw, members, ask, limit, only=None):
    """1 本: 選ぶ → (ask があれば)本番と同じ llm_run -> (新しい行, 記録)。only = 選ぶ手がかりを絞る(例 {"name", "mis"})"""
    orig = doc.get("original") or []
    picks = [p for p in pick_doc(doc, raw, members, 10 ** 6) if not only or p["why"] in only][:limit]
    rec = {"id": doc["id"], "picks": len(picks), "byWhy": {}, "proposed": [], "rejected": {}, "applied": []}
    for p in picks:
        rec["byWhy"][p["why"]] = rec["byWhy"].get(p["why"], 0) + 1
    rows = copy.deepcopy(orig)
    if ask is None or not picks:
        return rows, rec
    out = ed_llm.llm_run(rows, members, doc, ask, mark=False, picks=picks)
    rec["proposed"], rec["rejected"] = out["items"], out["rejected"]
    for it in out["items"]:
        if it["rejected"] is None:
            rec["applied"].append({**it, "judge": judge_hit(doc, orig[it["row"]], it)})
    return rows, rec


def score(S, docs, rows_of, terms, args, data, sel, label):
    """eval_asr と同じ採点 -> 結果(eval_asr compare の形)"""
    groups, nosub = [], {}
    for d in docs:
        groups += E.score_doc(S, d, rows_of[d["id"]], terms, flag_from="ref")
        nosub[d["id"]] = E.doc_nosub(S, d, rows_of[d["id"]])
    meta = E.base_meta("stored", args, docs, data, sel)
    meta["label"] = label
    return {"meta": meta, "summary": E.summarize(groups, docs, S, E.STORED, None, nosub), "groups": groups, "terms": terms}


def print_report(recs, dry):
    picks = sum(r["picks"] for r in recs)
    by = {}
    for r in recs:
        for k, v in r["byWhy"].items():
            by[k] = by.get(k, 0) + v
    print("選んだ所 %d(名簿の誤りやすい形 %d・呼び名に 1 字違い %d・確信度が低い語 %d)" % (picks, by.get("mis", 0), by.get("name", 0), by.get("lowprob", 0)))
    if dry:
        return
    prop = sum(len(r["proposed"]) for r in recs)
    app = [a for r in recs for a in r["applied"]]
    rej = {}
    for r in recs:
        for k, v in r["rejected"].items():
            rej[k] = rej.get(k, 0) + v
    j = {k: sum(1 for a in app if a["judge"] == k) for k in ("hit", "miss", "other")}
    print("LLM の案 %d・当てた %d(当たり %d・外れ %d・どちらとも %d)・断った %s" % (prop, len(app), j["hit"], j["miss"], j["other"], json.dumps(rej, ensure_ascii=False)))
    for a in app[:20]:
        print("  [%s] 「%s」→「%s」(%s)  %s" % (a["judge"], a["from"], a["to"], a["confidence"], a["text"][:40]))


def start_llm(S, data):
    """編集と同じ文字の LLM(tx_engines.LlamaText)をこのプロセスの中で起動する -> エンジン"""
    T = S.tx_engines
    try:
        return T.LlamaText.create(ed_llm.LLM_MODEL, "vulkan", "int8", None, data, {})
    except T.EngineError as e:
        raise SystemExit("LLM を起動できませんでした: %s" % e.message)


def main(argv=None):
    p = argparse.ArgumentParser(description="LLM の後処理(P18)を確かめ済みの評価用の文書で測る(作業データは読むだけ)")
    p.add_argument("--docs", help="文書の id をカンマ区切りで(既定は確かめ済みの評価用すべて)")
    p.add_argument("--limit", type=int, default=30, help="1 文書あたり選ぶ所の上限(既定 30)")
    p.add_argument("--only", help="選ぶ手がかりを絞る(カンマ区切り: mis・name・lowprob。既定は全部。本番と同じは name,mis)")
    p.add_argument("--dry", action="store_true", help="選ぶだけ(LLM を起動しない)")
    p.add_argument("--label", default="", help="結果の名前に付ける")
    p.add_argument("--no-save", action="store_true", help="結果を保存しない")
    p.add_argument("--data", help="文字起こしの作業データのフォルダ(既定 %%LOCALAPPDATA%%/youtube-tools/transcribe)")
    args = p.parse_args(argv)
    C.utf8_stdout()
    ns = argparse.Namespace(docs=[x.strip() for x in args.docs.split(",") if x.strip()] if args.docs else None, scope="eval", source=None,
                            reviewed=None, since=None, until=None, intake=None, label=args.label, group_by=None)
    data = E.real_data_dir(args.data)
    S = E.load_serve()
    settings = C.read_json(os.path.join(data, "settings.json"), {}) or {}
    docs, sel = E.select_docs(data, ns)
    if not docs:
        raise SystemExit("測れる文書がありません")
    members = list(S._roster.load(S.ROSTER)["members"].values())
    terms = E.name_terms(S, settings)
    only = {x.strip() for x in args.only.split(",") if x.strip()} if args.only else None
    llm = None if args.dry else start_llm(S, data)
    ask = (lambda messages: llm.complete(messages, ed_llm.LLM_MAX_TOKENS)) if llm else None
    recs, rows_of = [], {}
    try:
        for n, d in enumerate(docs, 1):
            asr = C.read_json(os.path.join(data, "transcripts", d["id"] + ".asr.json"), None, 64 * 1024 * 1024)
            raw = asr.get("segments") if isinstance(asr, dict) and isinstance(asr.get("segments"), list) else []
            rows_of[d["id"]], rec = run_doc(d, raw, members, ask, args.limit, only)
            recs.append(rec)
            print("(%d/%d) %s 選んだ %d・当てた %d" % (n, len(docs), d["id"], rec["picks"], len(rec["applied"])), flush=True)
    finally:
        if llm:
            llm.close()
    print_report(recs, args.dry)
    if args.dry:
        return 0
    base = score(S, docs, {d["id"]: d.get("original") or [] for d in docs}, terms, ns, data, sel, "llm-base" + args.label)
    on = score(S, docs, rows_of, terms, ns, data, sel, "llm-on" + args.label)
    for name, r in (("基準(直す前)", base), ("LLM の直しのあと", on)):
        o = r["summary"]["overall"]
        print("%s: CER %s(置換 %d・抜け %d・余分 %d)・名前 %d/%d・正解に無い名前 %d" % (name, C.pct(o["cer"], 0), o["sub"], o["del"], o["ins"], o["termHit"], o["termRef"], o["termExtra"]))
    if not args.no_save:
        pa = C.save(base, data, "asr", "_llm-base" + args.label)
        pb = C.save(on, data, "asr", "_llm-on" + args.label)
        print("保存: " + C.save({"schema": "youtube-tools-llm-eval/v1", "model": ed_llm.LLM_MODEL, "docs": recs}, data, "llm"))
        E.cmd_compare(pa, pb)
    return 0


if __name__ == "__main__":
    sys.exit(main())
