# -*- coding: utf-8 -*-
"""「編集」のサーバーの部品: LLM の後処理(提案 P18。plan/llm-postfix.md。編集 0.61.0)。

ねらい: 認識の結果のうち「名簿の呼び名の聞き違い」らしい所だけを、ローカルの LLM(Qwen3-8B。llama-server・Vulkan)に直させて校正を短くする。
  1 選ぶ llm_pick      名簿の呼び名(LLM_MIN_ALIAS 字以上・普通の言葉と重なるものは除く)に、かなに寄せて 1 字違いの所と、名簿の誤りやすい形(misrecognitions)。
                       名簿は、その文書に出る人(題名・動画のパス・話者の名前に名前か呼び名があるメンバー)だけ。カタカナの呼び名に近い所は元の文字にもカタカナがあるときだけ
                       (10-09 の測定: ひらがなの普通の言葉「みるか」を「ポルカ」に変えた)。後処理 A・D が直した行(fill)は選ばない。1 文書 LLM_MAX_PICKS 箇所まで
  2 聞く llm_messages  行ごとに 前後 LLM_CTX_ROWS 行・疑わしい所・候補・出る人を渡し、差分だけを JSON で答えさせる(行を書き直させない。思考はオフ・温度 0)
  3 検査 llm_guard     置き換え前の文字が行にある・候補の呼び名そのものか、かなに寄せた音が近い・字数の差が 2 字か 2 割以内・自信が LLM_MIN_CONF 以上・
                       候補に無い名簿の名前を新しく持ち込まない。1 文書で直す行は LLM_MAX_EDIT_SHARE まで(自信の高い順)
  4 当てる llm_apply   文書の行(segments)の文字を置き換え、fill = {"from": 元の文字, "by": "llm"} と印 LLM_FLAG を付ける(画面の「別の読み」の札で戻せる)。
                       機械の出力 original は変えない(精度の測定の正解との比べ方が変わらない)
決まり(10-08 の「守りを付けて先に入れて様子見」と decisions 3-17):
  - 設定 autoLlm(既定オン。文字起こしの指定 validate_job)。評価用の文書には当てない
  - 選んだ所が無ければ LLM を読み込まない(モデルは 5GB)。読めない・失敗したら文字起こしを失敗にせず、警告を出して認識の結果のまま
  - 生の提案・採否・断った理由は <id>.llm.json(LLM_SCHEMA)、数は recognition.runs[].llm
  - 学習(ed_learn.learn_events)は後処理が直した行(fill)を含むまとまりを材料にしない(機械の直しを「人の直し」として覚えない)
  - 測る道具は dev/eval_llm.py(この部品の規則をそのまま使う)。10-09 に確かめ済み 22 本で CER 13.5 → 13.4%・名前 28 → 34/53
規則の部分(llm_fold 〜 llm_cap)は編集のほかの部品を読まない(dev/eval_llm.py が単独で読む)。組み込みの部分だけが、関数の中で ed_state・ytt/jobs・worker_client・roster を読む。
名前は llm_ / LLM_ で始める(serve.py の _ED_MODULES の最後。ほかの部品と重ならないように)。
"""
import json
import os
import re
import time
import unicodedata

LLM_ENGINE, LLM_MODEL = "llama-text", "qwen3-8b"   # tx_engines.LlamaText と LLAMA_TEXT_MODELS の名前
LLM_SCHEMA = "youtube-tools-llm/v1"
LLM_FLAG = "名簿の呼び名に直した(LLM。元の文字は「別の読み」の札)"   # 頭を ed_fill の FILL_NAME_FLAG とそろえる(画面の「戻す」が同じ規則で印を外す)
LLM_MIN_ALIAS = 3        # 近い所を探す呼び名の最小の文字数(かなに寄せたあと)
LLM_MAX_PICKS = 30       # 1 文書で選ぶ所の上限
LLM_MIN_CONF = 0.5       # LLM の自信がこれ未満の案は当てない
LLM_MAX_EDIT_SHARE = 0.15   # 1 文書で直す行の割合の上限
LLM_CTX_ROWS = 2         # 前後に見せる行の数
LLM_MAX_TOKENS = 400
LLM_MAX_BYTES = 8 * 1024 * 1024
LLM_SYSTEM = ("あなたは日本語の配信(VTuber のゲーム実況・雑談)の文字起こしの校正者です。音声認識の誤りのうち、疑わしい所だけを直します。"
              "確信が持てないときは直しません。行を書き直さず、直す所の差分だけを JSON で答えます。/no_think")
_LLM_KATA = re.compile(r"[ァ-ヶ]")


# ---------- 規則(ほかの部品を読まない) ----------
def llm_fold(text):
    """かなに寄せた比べ方(NFKC・カタカナ → ひらがな・小文字・記号と空白を捨てる。伸ばし ー は残す)"""
    out = []
    for ch in unicodedata.normalize("NFKC", str(text or "")).lower():
        if "ァ" <= ch <= "ヶ":
            ch = chr(ord(ch) - 0x60)
        if unicodedata.category(ch)[0] in "LN" or ch == "ー":
            out.append(ch)
    return "".join(out)


def llm_dist(a, b):
    """編集距離(短い文字どうし)"""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def llm_members(doc, members):
    """その文書に出る人(話者の名前・題名・動画のパスに名前か LLM_MIN_ALIAS 字以上の呼び名があるメンバー)-> [メンバー]"""
    hay = " ".join([str(doc.get("title") or ""), str(doc.get("sourcePath") or "")] + [str(s.get("name") or "") for s in doc.get("speakers") or [] if isinstance(s, dict)])
    out = []
    for m in members:
        keys = [m["name"]] + [a for a in m.get("aliases") or [] if len(a) >= LLM_MIN_ALIAS and a not in (m.get("common") or [])]
        if any(k and k in hay for k in keys):
            out.append(m)
    return out


def llm_targets(mems):
    """近い所を探す呼び名(LLM_MIN_ALIAS 字以上・普通の言葉と重なるものは除く)-> [(かなに寄せた形, 呼び名)]"""
    out = []
    for m in mems:
        for a in [m["name"]] + list(m.get("aliases") or []):
            if a in (m.get("common") or []):
                continue
            f = llm_fold(a)
            if len(f) >= LLM_MIN_ALIAS and (f, a) not in out:
                out.append((f, a))
    return out


def llm_near(text, targets):
    """行の文字の中で、呼び名に 1 字違い(同じ形は除く)の所 -> [(元の文字の一部, 呼び名)]。カタカナの呼び名はカタカナを含む所だけ"""
    found = []
    for f, alias in targets:
        if llm_fold(alias) in llm_fold(text):
            continue
        for n in (len(alias) - 1, len(alias), len(alias) + 1):
            for i in range(0, max(0, len(text) - n) + 1):
                sub = text[i:i + n]
                if _LLM_KATA.search(alias) and not _LLM_KATA.search(sub):
                    continue
                fs = llm_fold(sub)
                if len(fs) >= 2 and fs != f and llm_dist(fs, f) == 1 and (sub, alias) not in found:
                    found.append((sub, alias))
    return found


def llm_pick(rows, members, doc, limit=LLM_MAX_PICKS):
    """疑わしい所 -> [{"row": 行の番号, "span": 元の文字の一部, "why": "mis" | "name", "cands": [候補]}](limit 箇所まで)。
    後処理 A・D が直した行(fill)・文字の無い行は選ばない。同じ行で、ほかの選んだ所に含まれる短い所は外す"""
    mems = llm_members(doc, members)
    targets = llm_targets(mems)
    mis = [(x["wrong"], x["right"]) for m in mems for x in m.get("misrecognitions") or []]
    picks = []
    for i, r in enumerate(rows):
        text = str(r.get("text") or "")
        if not text or isinstance(r.get("fill"), dict):
            continue
        for wrong, right in mis:
            if wrong in text:
                picks.append({"row": i, "span": wrong, "why": "mis", "cands": [right]})
        for sub, alias in llm_near(text, targets):
            picks.append({"row": i, "span": sub, "why": "name", "cands": [alias]})
    picks = [p for p in picks if not any(q is not p and q["row"] == p["row"] and p["span"] in q["span"] and len(q["span"]) > len(p["span"]) for q in picks)]
    picks.sort(key=lambda p: (0 if p["why"] == "mis" else 1, p["row"]))
    return picks[:limit]


def llm_messages(rows, i, picks, people):
    """行 i の問い合わせ(前後 LLM_CTX_ROWS 行・疑わしい所・候補・出る人)-> chat の messages"""
    lo, hi = max(0, i - LLM_CTX_ROWS), min(len(rows), i + LLM_CTX_ROWS + 1)
    ctx = "\n".join(("→ " if k == i else "  ") + str(rows[k].get("text") or "") for k in range(lo, hi))
    lines = ["- 「%s」(%s)" % (p["span"], ("候補: " + "・".join(p["cands"])) if p["cands"] else "認識の自信が低い語") for p in picks]
    user = ("出る人: %s\n\n前後の行(→ が直す行):\n%s\n\n疑わしい所:\n%s\n\n"
            "直す必要がある所だけ、次の形で答えてください。直さない所は書かない。何も直さないなら {\"edits\": []}。\n"
            "{\"edits\": [{\"from\": \"直す行の中の元の文字\", \"to\": \"直した文字\", \"confidence\": 0〜1}]}"
            % ("、".join(people) or "(不明)", ctx, "\n".join(lines)))
    return [{"role": "system", "content": LLM_SYSTEM}, {"role": "user", "content": user}]


def llm_parse(content):
    """LLM の答え -> [{"from", "to", "confidence"}](読めなければ [])。<think> の部分と、JSON の前後の文は捨てる"""
    text = re.sub(r"<think>.*?</think>", "", str(content or ""), flags=re.S)
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        return []
    try:
        data = json.loads(text[a:b + 1])
    except ValueError:
        return []
    out = []
    for e in data.get("edits") or [] if isinstance(data, dict) else []:
        if isinstance(e, dict) and isinstance(e.get("from"), str) and isinstance(e.get("to"), str):
            c = e.get("confidence")
            out.append({"from": e["from"], "to": e["to"], "confidence": float(c) if isinstance(c, (int, float)) and not isinstance(c, bool) else None})
    return out


def llm_names(members):
    """名簿の名前と呼び名(かなに寄せた 2 字以上の形。普通の言葉と重なる呼び名は除く)"""
    out = set()
    for m in members:
        for a in [m["name"]] + list(m.get("aliases") or []):
            if a not in (m.get("common") or []) and len(llm_fold(a)) >= 2:
                out.add(llm_fold(a))
    return sorted(out)


def llm_guard(text, edit, cands, names=()):
    """直しの案を検査する -> None(通す)か 断る理由(notInRow・noChange・lowConfidence・length・newName・farSound)"""
    f, t = edit["from"], edit["to"]
    if not f or f not in text:
        return "notInRow"
    if f == t or not t.strip():
        return "noChange"
    if edit.get("confidence") is not None and edit["confidence"] < LLM_MIN_CONF:
        return "lowConfidence"
    if abs(len(t) - len(f)) > max(2, round(0.2 * len(f))):
        return "length"
    ff, ft = llm_fold(f), llm_fold(t)
    if any(llm_fold(c) == ft for c in cands):
        return None
    if any(n in ft and n not in ff and not any(n in llm_fold(c) for c in cands) for n in names):
        return "newName"
    if llm_dist(ff, ft) > max(1, len(ff) // 3):
        return "farSound"
    return None


def llm_cap(accepted, n_rows):
    """1 文書で直す行を LLM_MAX_EDIT_SHARE までに(自信の高い順。自信の無い案は 0.5 とみる)-> (残す案, 落とした案)。accepted = [(行の番号, 案)]"""
    cap = max(1, int(n_rows * LLM_MAX_EDIT_SHARE))
    rows_kept, keep, drop = set(), [], []
    for i, e in sorted(accepted, key=lambda x: -(x[1]["confidence"] if x[1]["confidence"] is not None else 0.5)):
        if i in rows_kept or len(rows_kept) < cap:
            rows_kept.add(i)
            keep.append((i, e))
        else:
            drop.append((i, e))
    return keep, drop


def llm_apply(rows, keep, mark=True):
    """行に直しを当てる(rows を書き換える)。mark = 文書の行として印を付ける(fill = {from, by: "llm"}・LLM_FLAG)。1 つの行に案が 2 つ以上でも元の文字は最初の 1 回だけ"""
    for i, e in keep:
        r = rows[i]
        if mark and not isinstance(r.get("fill"), dict):
            r["fill"] = {"from": r["text"], "by": "llm"}
            if LLM_FLAG not in str(r.get("flag") or ""):
                r["flag"] = "、".join(x for x in (LLM_FLAG, str(r.get("flag") or "")) if x)[:100]
        r["text"] = r["text"].replace(e["from"], e["to"], 1)
    return rows


def llm_run(rows, members, doc, ask, limit=LLM_MAX_PICKS, mark=True, picks=None):
    """選ぶ → 聞く → 検査 → 当てる(rows を書き換える)。ask = messages -> 答えの文字(選んだ所が無ければ呼ばない)。
    -> 記録 {"picked", "proposed", "applied", "rejected": {理由: 数}, "items": [{row, from, to, confidence, rejected}]}"""
    picks = llm_pick(rows, members, doc, limit) if picks is None else picks
    people = [m["name"] for m in llm_members(doc, members)]
    names = llm_names(members)
    rec = {"picked": len(picks), "proposed": 0, "applied": 0, "rejected": {}, "items": []}
    accepted, item_of = [], {}
    for i in sorted({p["row"] for p in picks}):
        mine = [p for p in picks if p["row"] == i]
        cands = [c for p in mine for c in p["cands"]]
        for e in llm_parse(ask(llm_messages(rows, i, mine, people))):
            why = llm_guard(rows[i]["text"], e, cands, names)
            rec["proposed"] += 1
            rec["items"].append({"row": i, "start": rows[i].get("start"), "end": rows[i].get("end"), "text": rows[i]["text"][:200], **e, "rejected": why})   # 時刻 = あとで人の最終と突き合わせる(dev/eval_fill.py)
            if why:
                rec["rejected"][why] = rec["rejected"].get(why, 0) + 1
            else:
                accepted.append((i, e))
                item_of[id(e)] = rec["items"][-1]
    keep, drop = llm_cap(accepted, len(rows))
    for _i, e in drop:
        item_of[id(e)]["rejected"] = "cap"
    if drop:
        rec["rejected"]["cap"] = len(drop)
    llm_apply(rows, keep, mark)
    rec["applied"] = len(keep)
    return rec


# ---------- run_job から呼ぶ入口(ここからは編集の部品を読む) ----------
def llm_ask_fn(job, spec):
    """問い合わせの関数 messages -> 答えの文字。疑似(TRANSCRIBE_BACKEND=fake)は環境変数 TRANSCRIBE_FAKE_LLM の文字をそのまま返す。
    本物は LLM(tx_engines.LlamaText)を認識ワーカーに読み込み(主のモデルは手放さない = light)、op complete で聞く"""
    import ed_state
    from pipeline.transcribe import worker_client   # 認識ワーカーとモデル(RS2-8a。持ち主から直に読む)
    if ed_state.backend_name() == "fake":
        reply = os.environ.get("TRANSCRIBE_FAKE_LLM", "")
        return lambda messages: reply
    phase = job.get("phase")
    model, dev = worker_client.load_model(LLM_MODEL, job, "auto", engine=LLM_ENGINE)
    job["phase"] = phase
    if worker_client.IN_WORKER:   # 測る道具(このプロセスの中でモデルを読む)
        return lambda messages: model.complete(messages, LLM_MAX_TOKENS)
    args = {"name": LLM_MODEL, "device": dev, "engine": LLM_ENGINE, "max_tokens": LLM_MAX_TOKENS}
    return lambda messages: str((worker_client.WORKER.call("complete", dict(args, messages=messages), job) or {}).get("content") or "")


def llm_after_doc(job, spec, segs):
    """run_job の文書の行(_rows_to_doc のあと・後処理 D のあと)に LLM の直しを当てる(segs を書き換える)。
    -> 記録(recognition.runs[].llm に入れる。設定オフなら None)と、<id>.llm.json に書く中身(記録の items)の組"""
    import ed_state
    from pipeline.transcribe import roster
    from ytt import jobs as _heavy   # 取り消し Cancelled(RS2-8a。持ち主から直に読む)
    if not spec.get("autoLlm"):
        return None, None
    rec = {"engine": LLM_ENGINE, "model": LLM_MODEL, "picked": 0, "proposed": 0, "applied": 0, "rejected": {}}
    try:
        members = list(roster.load(ed_state.ROSTER)["members"].values())
    except (OSError, ValueError, TypeError, KeyError) as e:
        ed_state.log.warning("名簿を読めないので LLM の直しはしません: %s", e)
        return rec, None
    doc = {"title": spec.get("title"), "sourcePath": spec.get("sourcePath")}
    try:   # 出る人は、題名・動画のパスに加えて配信ごとの文脈(チャンネル名・コラボ相手・動画のフォルダ = roster.stream_context)からも(文字起こしの時点では話者がまだいない)
        ctx = roster.stream_context({"clip": spec.get("clip"), "title": spec.get("title"), "sourceName": os.path.basename(str(spec.get("sourcePath") or "")),
                                     "sourcePath": spec.get("sourcePath")}, True)
        doc["speakers"] = [{"name": m["name"]} for m in ctx.get("members") or []]
    except Exception as e:   # 文脈は補助。読めなくても題名とパスで選ぶ
        ed_state.log.warning("配信ごとの文脈を読めませんでした(LLM の後処理は題名とパスだけで): %s", e)
    picks = llm_pick(segs, members, doc)
    rec["picked"] = len(picks)
    if not picks:
        return rec, None   # 選んだ所が無ければ LLM を読み込まない
    phase = job.get("phase")
    try:
        ask = llm_ask_fn(job, spec)
        job["phase"] = "名簿の呼び名を LLM で確かめ中"
        out = llm_run(segs, members, doc, ask, picks=picks)
    except _heavy.Cancelled:
        raise
    except Exception as e:   # LLM は補助。読めない・失敗しても文字起こしは失敗にしない(ApiError・EngineError・ワーカーの失敗)
        ed_state.add_warning(job, "LLM で名前を確かめられませんでした(認識の結果のまま): " + str(getattr(e, "message", e))[:200])
        rec["error"] = str(getattr(e, "message", e))[:200]
        return rec, None
    finally:
        job["phase"] = phase
    rec.update({k: out[k] for k in ("picked", "proposed", "applied", "rejected")})
    return rec, out["items"]


def llm_path(tid):
    import ed_state
    return os.path.join(ed_state.TX_DIR, tid + ".llm.json")


def llm_write(tid, rec, items):
    """生の提案・採否を <id>.llm.json に(書けなくても文字起こしは失敗にしない)"""
    import ed_state
    body = {"schema": LLM_SCHEMA, "id": tid, "engine": rec.get("engine"), "model": rec.get("model"), "at": int(time.time() * 1000), "items": items or []}
    try:
        ed_state.atomic_write(llm_path(tid), json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except OSError as e:
        ed_state.log.warning("LLM の提案を保存できませんでした: %s %s", tid, e)


def read_llm(tid):
    """<id>.llm.json(無い・形が違えば None)"""
    import ed_state
    return ed_state.read_schema_json(llm_path(tid), LLM_MAX_BYTES, LLM_SCHEMA, "items")
