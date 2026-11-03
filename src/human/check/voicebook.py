"""声の登録簿を「確かめる」の答えから作り直す(11-03 情報をまとめる所の 1。ユーザー「すすめていい」「全部入れる」)。

正は答えの記録 answers.jsonl(answerlog。回さない)だけ。登録簿 voices/<emb>.json と行ごとの特徴の控え voices/<emb>.rows.json は、答えから作り直せる写し:
  材料 = 効いている答えの applied.learn(誰の声のカード voice:diar・voice:solo の行と、ソロの 10 秒 speaker:solo)。
         コラボだった見込みの文書の行(voice.collab_docs)と、まとめ直しで外した行(登録簿の excluded)は入れない
  声   = 材料の行ごとの特徴(控えに無ければ音から取って控える)を、行の秒で重みを付けて平均し長さ 1 に(ショート由来は SHORT_WEIGHT 倍。voicerebuild と同じ)
  learnedFrom = その人の材料の答えの id だけ(答えの古い順)
守り(登録簿には人が確かめた物だけ・勝手に減らさない):
  - 今の登録簿にあって、答えがまだ効いている材料の特徴が取れない(音が無い)ときは書かない(BuildRefused)
  - 答えの無い人(文書の「声を覚える」など by が check でない材料を持つ人)は触らない(そのまま残す)
  - 書く前の登録簿は voices/<emb>.json.bak-<時刻> に写す
呼ぶ所: ジョブ voice-rebuild(入口の見回り = human/check/voice._maybe_relearn・app/check/speaker_solo.tick が頼む)と dev/voice_registry_rebuild.py(空回しで差を見る)
"""
import math
import os
import shutil
import time

from flow import diar as _diar, jobs as _heavy, voicematerial as _vm
from ytt import errors as _errors, fsio, schemas as _yschemas
from ytt.textutil import person_key as _person_key
from human.proof import store as _store, voicerebuild as _rebuild
from . import answerlog

KIND = "voice-rebuild"
SOLO_KIND, SOLO_SOURCE, SOLO_PREFIX = "speaker", "solo", "solo:"   # ソロの 10 秒(app/check/speaker_solo)の答えの形
VOICE_KIND, VOICE_SOURCES = "voice", ("diar", "solo")             # 誰の声のカード(human/check/voice)の答えの形
SOLO_DIR = os.path.join("check", "speaker-solo")                  # ソロの 10 秒の音 <app>/check/speaker-solo/<key>.wav


class BuildRefused(Exception):
    """作り直すと今の登録簿から人が確かめた材料が消える(音が無くて特徴が取れない)= 書かない"""


def materials(app_dir, rows=None):
    """効いている答えの声の材料 -> [{answer, at, name, emb, doc, row, sec, clip?: (wav, 頭, 末)}](答えの古い順)。emb が空なら声の名前付けのモデル"""
    from . import voice as _voice   # voice が voicebook を読むので、ここで読む
    rows = answerlog.state(app_dir).effective() if rows is None else rows
    collab = _voice.collab_docs(app_dir, rows)
    out = []
    for r in rows:
        ap = r.get("applied") or {}
        lr = ap.get("learn")
        if not isinstance(lr, dict) or not str(lr.get("name") or "").strip():
            continue
        sec = _yschemas.num_or(lr.get("sec"))
        if r.get("kind") == SOLO_KIND and r.get("source") == SOLO_SOURCE and ap.get("solo"):
            a, b = _yschemas.num_or(lr.get("start")), _yschemas.num_or(lr.get("end"))
            if a is None or b is None or b <= a:
                continue
            key = str(ap["solo"])
            out.append({"answer": r["id"], "at": r.get("at"), "name": str(lr["name"]), "emb": "", "doc": SOLO_PREFIX + key, "row": "w",
                        "sec": round(b - a, 2), "clip": (os.path.join(app_dir, SOLO_DIR, key + ".wav"), a, b)})
        elif r.get("kind") == VOICE_KIND and r.get("source") in VOICE_SOURCES and ap.get("doc") and ap.get("row") and sec:
            if str(ap["doc"]) in collab:
                continue
            out.append({"answer": r["id"], "at": r.get("at"), "name": str(lr["name"]), "emb": str(lr.get("emb") or ""), "doc": str(ap["doc"]),
                        "row": str(ap["row"]), "sec": float(sec)})
    return out


def learned_answers(entry):
    """登録簿の 1 人分の learnedFrom のうち答えの id(新しい形 = 文字列)の集まり"""
    return {x for x in (entry or {}).get("learnedFrom") or () if isinstance(x, str)}


def learned_rows(entry, by_answer):
    """登録簿の 1 人分が覚えた (文書, 行) の集まり。古い形({doc, rows})と新しい形(答えの id。by_answer = {答えの id: 材料})の両方を読む"""
    out = set()
    for x in (entry or {}).get("learnedFrom") or ():
        if isinstance(x, str):
            it = by_answer.get(x)
            if it:
                out.add((it["doc"], it["row"]))
        elif isinstance(x, dict):
            out.update((str(x.get("doc")), str(r)) for r in x.get("rows") or () if isinstance(r, str))
    return out


def _foreign(entry):
    """答えから作れない材料(by が check でない古い形の learnedFrom = 文書の「声を覚える」など)を持つか"""
    return any(isinstance(x, dict) and x.get("by") != "check" for x in (entry or {}).get("learnedFrom") or ())


def _unit(v):
    s = math.sqrt(sum(x * x for x in v)) or 0.0
    return [x / s for x in v] if s > 0 else None


def _doc_vectors(emb, tid, items, job):
    """文書の行の特徴を音から取る -> {行 id: (特徴, 秒, short)}"""
    try:
        doc = _store.read_transcript(tid)
    except _errors.ApiError:
        return {}
    rows = _rebuild._doc_rows(doc, None, [it["row"] for it in items])
    got = _rebuild.row_vectors(emb, tid, rows, job=job) if rows else {}
    short = bool(_vm.is_short(doc.get("sourcePath")))
    return {r: (got[r], round(b - a, 2), short) for r, a, b in rows if r in got}


def _clip_vector(emb, it, job):
    wav, a, b = it["clip"]
    if not os.path.isfile(wav):
        return None
    with _heavy.job_temp_wav(job) as tmp:
        vecs = _diar.embed(job, {"embedding": emb}, tmp, [[(a, b)]], {"sourcePath": wav, "start": 0.0})
    return vecs[0] if vecs else None


def build(app_dir, emb=None, job=None, now=None, voices=None, cache=None, rows=None, embed_doc=None, embed_clip=None):
    """答えから登録簿を作る(書かない)-> {"voices": 新しい登録簿, "cache": 控え(取った特徴を足した物), "added": 新しく取った特徴の数,
    "missing": [材料(特徴が取れない)], "kept": [触らなかった人]}。embed_doc(emb, tid, items, job)・embed_clip(emb, it, job) はテストの差し替え"""
    emb = emb or _diar.learn_embedding("")
    now = time.time() if now is None else now
    job = job if job is not None else {"id": "voicebook-%d" % int(now * 1000), "state": "running", "progress": 0.0, "cancel": False}
    voices = _diar.load_voices(emb) if voices is None else voices
    cache = fsio.read_json_or(_diar.row_vectors_path(emb), {}, kind=dict) if cache is None else cache
    embed_doc, embed_clip = embed_doc or _doc_vectors, embed_clip or _clip_vector
    names = {_person_key(n): n for n in voices}
    excluded = {n: set(v.get("excluded") or ()) for n, v in voices.items()}
    kept = sorted(n for n, v in voices.items() if _foreign(v))
    by_name = {}
    for it in materials(app_dir, rows):
        if it["emb"] and it["emb"] != emb:
            continue
        name = names.setdefault(_person_key(it["name"]), it["name"][:60])
        if name in kept or "%s#%s" % (it["doc"], it["row"]) in excluded.get(name, ()):
            continue
        by_name.setdefault(name, []).append(it)
    flat = {}   # 控えはどの名前の下でも使う(名前の書き方が変わった人)
    for n, d in cache.items():
        if isinstance(d, dict):
            for k, x in d.items():
                if isinstance(x, dict) and isinstance(x.get("vec"), list):
                    flat.setdefault(k, x)
    need_doc, missing, added = {}, [], 0
    for name, items in by_name.items():
        for it in items:
            k = "%s#%s" % (it["doc"], it["row"])
            if k in flat:
                continue
            if it.get("clip"):
                v = embed_clip(emb, it, job)
                if v:
                    flat[k] = {"vec": [round(x, 6) for x in v], "sec": it["sec"], "short": False}
                    cache.setdefault(name, {})[k] = flat[k]
                    added += 1
            else:
                need_doc.setdefault(it["doc"], []).append((name, it))
    for tid, pairs in need_doc.items():
        got = embed_doc(emb, tid, [it for _n, it in pairs], job)
        for name, it in pairs:
            g = got.get(it["row"])
            if g:
                k = "%s#%s" % (tid, it["row"])
                flat[k] = {"vec": [round(x, 6) for x in g[0]], "sec": g[1], "short": bool(g[2])}
                cache.setdefault(name, {})[k] = flat[k]
                added += 1
    out = {n: v for n, v in voices.items() if n in kept}
    for name, items in by_name.items():
        acc, total, short_sec, used = None, 0.0, 0.0, []
        for it in items:
            x = flat.get("%s#%s" % (it["doc"], it["row"]))
            if not x:
                missing.append(it)
                continue
            sec = float(x.get("sec") or it["sec"])
            w = sec * (_diar.SHORT_WEIGHT if x.get("short") else 1.0)
            acc = [w * a for a in x["vec"]] if acc is None else [p + w * a for p, a in zip(acc, x["vec"])]
            total += sec
            short_sec += sec if x.get("short") else 0.0
            used.append(it["answer"])
        vec = _unit(acc) if acc else None
        if not vec:
            continue
        e = {"vec": [round(a, 6) for a in vec], "rows": len(used), "sec": round(total, 1), "updatedAt": int(now * 1000), "rebuiltAt": int(now * 1000),
             "learnedFrom": used}
        if short_sec:
            e["shortSec"] = round(short_sec, 1)
        if excluded.get(name):
            e["excluded"] = sorted(excluded[name])
        out[name] = e
    return {"voices": out, "cache": cache, "added": added, "missing": missing, "kept": kept}


def lost(app_dir, cur, new, rows=None):
    """今の登録簿にあって答えがまだ効いている材料のうち、新しい登録簿に入らない物 -> [(名前, 文書, 行)]"""
    by_answer = {it["answer"]: it for it in materials(app_dir, rows)}
    live = {(it["doc"], it["row"]) for it in by_answer.values()}
    out = []
    for n, v in cur.items():
        had = learned_rows(v, by_answer) & live
        now = learned_rows(new.get(n), by_answer)
        out += [(n, d, r) for d, r in sorted(had - now)]
    return out


def diff(cur, new):
    """人ごとの差 -> [{name, before: {rows, sec}, after: {rows, sec}, cos}](cos = 前と後の声の近さ。片方に無ければ None)"""
    out = []
    for n in sorted(set(cur) | set(new)):
        a, b = cur.get(n) or {}, new.get(n) or {}
        va, vb = a.get("vec"), b.get("vec")
        cos = round(sum(x * y for x, y in zip(va, vb)), 4) if va and vb and len(va) == len(vb) else None
        out.append({"name": n, "before": {"rows": a.get("rows"), "sec": a.get("sec")}, "after": {"rows": b.get("rows"), "sec": b.get("sec")}, "cos": cos})
    return out


def rebuild(app_dir, emb=None, job=None, log=None, now=None, **kw):
    """答えから作り直して登録簿と控えを書く -> build の結果に "backup" を足した物。今の登録簿の材料が消えるなら BuildRefused(何も書かない)"""
    log = log or (lambda m: None)
    emb = emb or _diar.learn_embedding("")
    now = time.time() if now is None else now
    cur = _diar.load_voices(emb)
    res = build(app_dir, emb, job=job, now=now, voices=cur, **kw)
    gone = lost(app_dir, cur, res["voices"])
    if gone:
        raise BuildRefused("今の登録簿の材料 %d 個の声の特徴が取れません(音が無い見込み。例 %s %s#%s)" % ((len(gone),) + gone[0]))
    fsio.write_json(_diar.row_vectors_path(emb), res["cache"], indent=None)
    res["backup"] = None
    if os.path.isfile(_diar.voices_path(emb)):
        res["backup"] = _diar.voices_path(emb) + ".bak-%d" % int(now)
        shutil.copyfile(_diar.voices_path(emb), res["backup"])
    with _diar.voices_edit(emb) as v:
        v.clear()
        v.update(res["voices"])
    log("声の登録簿を確かめるの答えから作り直しました(%d 人・新しく取った特徴 %d・取れない材料 %d・前の写し %s)"
        % (len(res["voices"]), res["added"], len(res["missing"]), os.path.basename(res["backup"] or "-")))
    return res


def pending(app_dir, emb=None, rows=None):
    """まだ登録簿に入っていない材料 -> [材料](答えの古い順)と、登録簿にあるが答えが戻された(効いていない)答えの id の数"""
    emb = emb or _diar.learn_embedding("")
    voices = _diar.load_voices(emb)
    items = materials(app_dir, rows)
    by_answer = {it["answer"]: it for it in items}
    have, stale, excluded = set(), 0, set()
    for v in voices.values():
        have |= learned_rows(v, by_answer)
        stale += len(learned_answers(v) - set(by_answer))   # 戻した答え = 作り直すと外れる
        excluded |= {str(k) for k in v.get("excluded") or ()}
    todo = [it for it in items if (it["doc"], it["row"]) not in have and "%s#%s" % (it["doc"], it["row"]) not in excluded]
    return todo, stale


def request(app_dir, title, log=None):
    """作り直しのジョブ voice-rebuild を足す(待っている・動いている物があれば足さない)-> ジョブか None"""
    if KIND not in _heavy.JOB_RUNNERS or _heavy.active_jobs(KIND):
        return None
    job = _heavy.add_job({"appDir": app_dir, "embedding": _diar.learn_embedding(""), "by": "check", "title": title}, KIND)
    if log:
        log("声の登録簿を答えから作り直すジョブ %s を足しました(%s)" % (job["id"], title))
    return job


def run_job(job):
    """ジョブ voice-rebuild の本体(editor/serve が登録する)"""
    spec = job["spec"]
    with _heavy.job_temp_wav(job):
        if not _diar.voice_ready():
            raise _errors.ApiError("no_sherpa", "声を覚えるには声の照合の部品(sherpa-onnx)が要ります。フォルダ内の install-diarize.bat を実行してください", 400)
        try:
            res = rebuild(spec["appDir"], spec.get("embedding") or None, job=job)
        except BuildRefused as e:
            raise _errors.ApiError("voice_lost", "声の登録簿を作り直せませんでした: %s" % e, 400)
        job["speakers"] = len(res["voices"])
        job["missing"] = len(res["missing"])
        _heavy.job_done(job, None)
