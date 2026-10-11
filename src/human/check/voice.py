"""「確かめる」の誰の声のカード(voice:diar)の答えの形・選択肢・反映・声の覚え直し(V1 V2c。docs/design/v1-check-build.md の 3-2・5 節、
設計 docs/design/briefs/rs8-cases/DESIGN_BRIEF.md 2-3 の 3)。

答えの形(画面 cards/voice.js が送る。check_answer が整える):
  {"choice": <文書の話者の id>}   その人の声(文書の speakers[] にいる人)
  {"name": <名前>}               その人の声(覚えた声の登録簿にいて、この文書の speakers[] にまだいない人 = 名前の話者を足す。選択肢の id は "name:<名前>")
  {"choice": "other"}            その他(ゲームの音など)= 組み込みの話者「ゲーム音声など」+ 字幕に出さない(編集の画面で選んだときと同じ)
  {"choice": "mixed"}            声が混ざっている = 行の印 MIXED_FLAG と音のメモ overlap(話者はそのまま)
反映(apply_voice): 保存のロックの中で文書を読み直し、行の speaker・flag(話者の印 SPK_FLAGS を外す / 混ざりは付ける)・tags・noSub を直して
  store.commit(why="check:voice")。**行は proofed にしない**(文字は確かめていない)・時刻は触らない・層(O2)には commit の今の道で載る(hum は渡さない)。
  Z(revert_voice)= 逆の commit(行が答えたあとのままのときだけ。足した話者は誰も使っていなければ外す)。
声の覚え直し(maybe_relearn): 名前で答えた行のうち、1 秒以上・混ざっていない・音のメモ(重なり・BGM・聞き取れない)が無い・評価用でない・
  名前が仮の名前(話者n)や一般的な名前でない行を「覚える材料」(applied.learn)にし、その人の材料の合計(まだ覚えていない分)が
  設定 check.voiceRelearnSec(編集の設定。既定 30 秒)以上になったら、材料のある文書ごとにジョブ voice-learn(by "check"・rows = その行)を足す。
  覚えた行は登録簿 voices/<emb>.json の learnedFrom[{doc, rows, sec, by}] に控える(flow/diar.merge_voice)= 同じ行を 2 度覚えない。
  待っている・動いている覚え直しの行も数えない。失敗しても答えは済んだまま(次の答えでまた数える)。Z で戻した答えは材料から外れる(覚えた後なら声は戻さない)。
③ の層: 文書は human/proof(store・speakers)、声の登録簿とジョブは ② flow(diar・jobs)を通す。① は読まない。
"""
import re
import time
import unicodedata

from ytt import errors as _errors, schemas as _yschemas, settings as _settings, tools as _tools, txbase as _txbase
from flow import diar as _diar, jobs as _heavy
from human.proof import speakers as _speakers, store as _store
from . import answerlog, apply as _apply   # 同じ human/check の兄弟

KIND, SOURCE = "voice", "diar"
OTHER, MIXED = _yschemas.OTHER_SPK_ID, "mixed"   # その他 = 組み込みの話者「ゲーム音声など」の id・混ざり = 答えの印
NAME_PREFIX = "name:"           # 選択肢の id: 登録簿の名前(文書にまだいない人)
MAX_NAMED = 9                   # 名前の選択肢の数(数字キー 1〜9)
NAME_MAX = 30                   # 文書の話者の名前の上限(store.sanitize_transcript と同じ)
MIN_LEARN_SEC = 1.0             # 覚える材料にする行の最短(flow/diar の voice_learn_rows と同じ 1 秒)
RELEARN_SEC_DEFAULT = 30.0      # 覚え直すまでの 1 人の材料の合計(秒。編集の設定 check.voiceRelearnSec で変える)
RELEARN_SEC_RANGE = (5.0, 3600.0)
BUSY_KINDS = ("transcribe", "diarize", "retranscribe", "redo")   # この文書を書き換えるジョブの最中は答えを反映しない(ジョブの結果で消えるため)
SPK_COLORS = _speakers.SPK_COLORS
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")


def name_key(name):
    """名前を比べる鍵(NFKC・空白を寄せる。speakers の字幕の見た目の名前合わせと同じ)"""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(name or ""))).strip()


def learnable_name(name):
    """覚えてよい名前か(仮の名前 話者n・一般的な名前・空は覚えない = speakers.voice_learn_plan と同じ決まり)"""
    n = str(name or "").strip()
    return bool(n) and not _speakers.DEFAULT_SPK_NAME.match(n) and not _speakers.is_generic_speaker_name(n)


def doc_embedding(doc):
    return _diar.embedding(str((doc.get("diarization") or {}).get("embedding") or ""))


def registry(emb, cache=None):
    """覚えた声の登録簿 {名前: 1 人分}(読めなければ {})。cache = 1 回の集めの間の入れ物"""
    if cache is not None and emb in cache:
        return cache[emb]
    try:
        got = _diar.load_voices(emb)
    except Exception:   # 作業データの置き場所が決まっていない(入口だけで編集を取り込んでいない)・壊れている
        got = {}
    if cache is not None:
        cache[emb] = got
    return got


# ---------------------------------------------------------------- 選択肢と予想(⑤ eval/check/sources の voice:diar が呼ぶ)

def options_for(doc, voices):
    """文書の話者(組み込みの「ゲーム音声など」を除く)→ 登録簿にいて文書にいない名前(新しく覚えた順)を 9 人まで + その他 + 混ざり。
    -> [{id, name, voice?: 登録簿に声がある}]"""
    have = {name_key(n) for n in voices}
    out, seen = [], set()
    for s in doc.get("speakers") or ():
        if not isinstance(s, dict) or not s.get("id") or _yschemas.other_speaker(s):
            continue
        n = str(s.get("name") or s.get("id"))
        seen.add(name_key(n))
        out.append({"id": str(s["id"]), "name": n, "voice": name_key(n) in have})
    for n, v in sorted(voices.items(), key=lambda kv: -int(_yschemas.num_or((kv[1] or {}).get("updatedAt"), 0) or 0)):
        if len(out) >= MAX_NAMED:
            break
        if name_key(n) in seen or len(n) > NAME_MAX or not learnable_name(n):
            continue
        seen.add(name_key(n))
        out.append({"id": NAME_PREFIX + n, "name": n, "voice": True})
    return out[:MAX_NAMED] + [{"id": OTHER, "name": "その他"}, {"id": MIXED, "name": "混ざり"}]


def guess_for(doc, speaker, match, options):
    """機械の予想 {id, name}(全部のカードに付ける)。行の話者に名前があればその人・仮の名前(話者n)のままなら照合のいちばん近い声(match.top)が
    選択肢にあればその名前・無ければ仮の名前のまま。話者が無ければ照合の名前か None"""
    names = {s.get("id"): str(s.get("name") or s.get("id")) for s in doc.get("speakers") or () if isinstance(s, dict) and s.get("id")}
    top = str((match or {}).get("top") or "")
    by_name = {name_key(o["name"]): o for o in options if o["id"] not in (OTHER, MIXED)}
    if speaker and speaker in names and learnable_name(names[speaker]):
        return {"id": speaker, "name": names[speaker]}
    if top and name_key(top) in by_name:
        o = by_name[name_key(top)]
        return {"id": o["id"], "name": o["name"]}
    if speaker:
        return {"id": speaker, "name": names.get(speaker, speaker)}
    return None


# ---------------------------------------------------------------- 答えの検査

def check_answer(ans):
    """答えを整える -> {"choice": id} か {"name": 名前}。違えば ValueError(400)"""
    if not isinstance(ans, dict):
        raise ValueError("答えは {choice} か {name} の形で送ってください")
    keys = set(ans)
    if keys == {"choice"} and isinstance(ans["choice"], str):
        c = ans["choice"]
        if c.startswith(NAME_PREFIX):
            return check_answer({"name": c[len(NAME_PREFIX):]})
        if not re.match(r"^[\w-]{1,12}\Z", c):
            raise ValueError("答えの話者の指定が正しくありません")
        return {"choice": c}
    if keys == {"name"} and isinstance(ans["name"], str):
        n = ans["name"].strip()
        if not n or len(n) > NAME_MAX or _CTRL_RE.search(n):
            raise ValueError("名前は 1〜%d 文字で送ってください" % NAME_MAX)
        return {"name": n}
    raise ValueError("答えは {choice} か {name} の形で送ってください")


# ---------------------------------------------------------------- 反映と戻す

def _target(card):
    t = card.get("target") or {}
    tid, rid = str(t.get("docId") or ""), str(t.get("row") or "")
    if not _yschemas.TID_RE.match(tid) or not re.match(r"^[A-Za-z0-9_-]{1,16}\Z", rid):
        raise _apply.Refused("カードの対象(文書・行)が正しくありません", 400, "bad_request")
    return tid, rid


def _read(tid):
    try:
        return _store.read_transcript(tid)
    except _errors.ApiError as e:
        raise _apply.Refused(e.message or "文字起こしを読めません", 409, "gone")


def _row(doc, rid):
    for g in doc.get("segments") or ():
        if isinstance(g, dict) and g.get("id") == rid:
            return g
    raise _apply.Refused("この行はもうありません(行が消えたか分け直されています)", 409, "gone")


def _spk_flag(flag, mixed):
    parts = [x for x in str(flag or "").split("、") if x and x not in _txbase.SPK_FLAGS]
    if mixed:
        parts.append(_txbase.MIXED_FLAG)
    return "、".join(parts)[:100]


def _row_state(g):
    """戻すときに比べる・戻す行の欄(無い欄は None)"""
    return {"speaker": g.get("speaker") or "", "flag": str(g.get("flag") or ""),
            "tags": list(g["tags"]) if isinstance(g.get("tags"), list) else None, "noSub": g.get("noSub") is True}


def _set_row(g, st):
    g["speaker"] = st["speaker"]
    g["flag"] = st["flag"]
    if st["tags"] is None:
        g.pop("tags", None)
    else:
        g["tags"] = list(st["tags"])
    if st["noSub"]:
        g["noSub"] = True
    else:
        g.pop("noSub", None)


def _bump(doc):
    doc["updatedAt"] = max(int(time.time() * 1000), int(_yschemas.num_or(doc.get("updatedAt"), 0) or 0) + 1)


def _speaker_for(doc, ans):
    """答え → (話者の id, 足した話者の id か None)。文書の speakers を書き換える(足すとき)"""
    sps = doc.setdefault("speakers", [])
    if not isinstance(sps, list):
        raise _apply.Refused("文書の話者の表が壊れています", 409, "broken")
    if "name" in ans:
        want = name_key(ans["name"])
        for s in sps:
            if isinstance(s, dict) and not _yschemas.other_speaker(s) and name_key(s.get("name")) == want:
                return str(s["id"]), None
        named = [s for s in sps if isinstance(s, dict) and not _yschemas.other_speaker(s)]
        if len(named) >= _speakers.MAX_SPEAKERS:
            raise _apply.Refused("この文書の話者は %d 人までです(編集の画面で使わない話者を消してください)" % _speakers.MAX_SPEAKERS, 409, "too_many")
        n = len(named) + 1
        ids = {str(s.get("id")) for s in sps if isinstance(s, dict)}
        while "S%d" % n in ids:
            n += 1
        sid = "S%d" % n
        new = {"id": sid, "name": ans["name"], "color": SPK_COLORS[(n - 1) % len(SPK_COLORS)]}
        k = next((i for i, s in enumerate(sps) if _yschemas.other_speaker(s)), None)   # 組み込みの「ゲーム音声など」はいつも最後(画面の addSpeaker と同じ)
        if k is None:
            sps.append(new)
        else:
            sps.insert(k, new)
        return sid, sid
    c = ans["choice"]
    if c == OTHER:
        if not any(_yschemas.other_speaker(s) for s in sps):
            sps.append({"id": OTHER, "name": _yschemas.OTHER_SPK_NAME, "color": _yschemas.OTHER_SPK_COLOR, "builtin": _yschemas.OTHER_SPK_BUILTIN})
            return OTHER, OTHER
        return OTHER, None
    if any(isinstance(s, dict) and s.get("id") == c and not _yschemas.other_speaker(s) for s in sps):
        return c, None
    raise _apply.Refused("その話者はこの文書にいません(画面を読み込み直してください)", 409, "gone")


def _learn_of(doc, g, sid, ans):
    """名前で答えた行が覚える材料になるなら {name, sec, emb}(ならなければ None)"""
    if ans.get("choice") in (OTHER, MIXED) or doc.get("evalSet") is True:
        return None
    a, b = _yschemas.num_or(g.get("start")), _yschemas.num_or(g.get("end"))
    if a is None or b is None or b - a < MIN_LEARN_SEC or _txbase.MIXED_FLAG in str(g.get("flag") or ""):
        return None
    tags = g.get("tags") if isinstance(g.get("tags"), list) else []
    if any(t in tags for t in _speakers.VOICE_LEARN_TAGS):
        return None
    name = next((str(s.get("name") or "").strip() for s in doc.get("speakers") or () if isinstance(s, dict) and s.get("id") == sid), "")
    if not learnable_name(name):
        return None
    return {"name": name[:60], "sec": round(b - a, 2), "emb": doc_embedding(doc)}


def apply_voice(ctx, card, ans):
    """答えを文書の行へ。-> applied {doc, row, before, after, added, updatedAt, learn?, relearn?}"""
    tid, rid = _target(card)
    with _store._save_lock:
        if _heavy.tid_busy(tid, BUSY_KINDS):
            raise _apply.Refused("この文字起こしは処理中です(話者判別・再認識などが終わってから答えてください)", 409, "busy")
        doc = _read(tid)
        if doc.get("evalSet") is True:
            raise _apply.Refused("評価用の文字起こしは確かめるでは直しません(評価ドリルで確かめてください)", 409, "eval_set")
        g = _row(doc, rid)
        before = _row_state(g)
        if ans.get("choice") == MIXED:
            after, added = dict(before, flag=_spk_flag(before["flag"], True),
                                tags=list(dict.fromkeys((before["tags"] or []) + ["overlap"]))), None
        else:
            sid, added = _speaker_for(doc, ans)
            after = dict(before, speaker=sid, flag=_spk_flag(before["flag"], False),
                         noSub=True if sid == OTHER else (before["noSub"] and before["speaker"] != OTHER))
        _set_row(g, after)
        _bump(doc)
        _store.snapshot(tid, False)   # 履歴が残せなくても答えは止めない(編集の画面の保存と同じ)
        _store.commit(tid, doc, why="check:voice")
        applied = {"doc": tid, "row": rid, "before": before, "after": _row_state(g), "added": added, "updatedAt": doc["updatedAt"]}
        learn = _learn_of(doc, g, g["speaker"], ans)
        if learn:
            applied["learn"] = learn
    if learn:
        try:
            applied["relearn"] = maybe_relearn(ctx, extra=[dict(learn, doc=tid, row=rid)])
        except Exception as e:   # 覚え直しが始められなくても答えは済んだまま(次の答えでまた数える)
            _txbase.log.warning("確かめる: 声の覚え直しを始められませんでした: %s %s", e.__class__.__name__, str(e)[:200])
    return applied


def revert_voice(ctx, row):
    """Z。答える前の行に戻す(行が答えたあとのままのときだけ)。-> {doc, row}"""
    a = row.get("applied") or {}
    tid, rid = str(a.get("doc") or ""), str(a.get("row") or "")
    if not _yschemas.TID_RE.match(tid) or not isinstance(a.get("before"), dict) or not isinstance(a.get("after"), dict):
        raise _apply.Refused("この答えは戻せません(記録の形が違います)", 409, "cannot_undo")
    with _store._save_lock:
        if _heavy.tid_busy(tid, BUSY_KINDS):
            raise _apply.Refused("この文字起こしは処理中です(終わってから戻してください)", 409, "busy")
        doc = _read(tid)
        g = _row(doc, rid)
        if _row_state(g) != a["after"]:
            raise _apply.Refused("この行はあとで直されています(編集の画面で直してください)", 409, "changed")
        _set_row(g, a["before"])
        added = a.get("added")
        if added and not any(isinstance(x, dict) and x.get("speaker") == added for x in doc.get("segments") or ()):
            doc["speakers"] = [s for s in doc.get("speakers") or () if not (isinstance(s, dict) and s.get("id") == added)]
        _bump(doc)
        _store.commit(tid, doc, why="check:voice")
    return {"doc": tid, "row": rid}


# ---------------------------------------------------------------- 声の覚え直し

def relearn_sec():
    """覚え直すまでの 1 人の材料の合計(秒)。編集の設定 check.voiceRelearnSec(無い・読めない・範囲の外は既定)"""
    try:
        v = (_settings.load_settings().get("check") or {}).get("voiceRelearnSec")
    except Exception:
        v = None
    v = _yschemas.num_or(v) if not isinstance(v, bool) else None
    lo, hi = RELEARN_SEC_RANGE
    return float(v) if v is not None and lo <= v <= hi else RELEARN_SEC_DEFAULT


def _learned_rows(emb, name, cache):
    """登録簿のその人の learnedFrom の行 -> {(文書, 行)}"""
    v = registry(emb, cache).get(name) or {}
    return {(str(x.get("doc")), str(r)) for x in v.get("learnedFrom") or () if isinstance(x, dict) for r in x.get("rows") or () if isinstance(r, str)}


def _inflight():
    """待っている・動いている覚え直し(by check)の行 -> {(文書, 行)}"""
    out = set()
    with _heavy._jobs_lock:
        for j in _heavy._jobs.values():
            sp = j.get("spec") or {}
            if j.get("kind") == "voice-learn" and j.get("state") in _heavy.ACTIVE_STATES and sp.get("by") == "check":
                out.update((str(sp.get("tid")), str(r)) for r in sp.get("rows") or ())
    return out


def pending(ctx, extra=()):
    """まだ覚えていない材料 -> {(emb, 名前): {文書: {行: 秒}}}。extra = 記録にまだ書いていない今の答えの材料 [{doc, row, name, sec, emb}]"""
    items = []
    for r in answerlog.state(ctx.app_dir).effective():
        if r.get("kind") != KIND or r.get("source") != SOURCE:
            continue
        lr = (r.get("applied") or {}).get("learn")
        if isinstance(lr, dict):
            items.append(dict(lr, doc=(r.get("applied") or {}).get("doc"), row=(r.get("applied") or {}).get("row")))
    items += list(extra)
    cache, busy, out = {}, _inflight(), {}
    for it in items:
        tid, rid, name, emb = str(it.get("doc") or ""), str(it.get("row") or ""), str(it.get("name") or ""), str(it.get("emb") or "")
        sec = _yschemas.num_or(it.get("sec"))
        if not tid or not rid or not name or not emb or not sec or (tid, rid) in busy or (tid, rid) in _learned_rows(emb, name, cache):
            continue
        out.setdefault((emb, name), {}).setdefault(tid, {})[rid] = float(sec)
    return out


def maybe_relearn(ctx, extra=()):
    """材料の合計が relearn_sec() 以上の人がいれば、文書ごとに voice-learn のジョブを足す。-> [{name, doc, job | skipped}](足さなければ [])"""
    if "voice-learn" not in _heavy.JOB_RUNNERS or not _diar.models_ready():
        return []   # 編集を取り込んでいない入口・話者判別の部品が無い = 材料は残して次に
    need = relearn_sec()
    by_doc = {}
    for (emb, name), docs in pending(ctx, extra).items():
        if sum(sum(rows.values()) for rows in docs.values()) < need:
            continue
        for tid, rows in docs.items():
            d = by_doc.setdefault(tid, {"emb": emb, "names": [], "rows": []})
            if d["emb"] == emb:
                d["names"].append(name)
                d["rows"] += list(rows)
    out = []
    for tid, d in sorted(by_doc.items()):
        try:
            out.append(dict(_submit(tid, d), doc=tid))
        except (_errors.ApiError, _apply.Refused, OSError, ValueError) as e:
            out.append({"doc": tid, "names": d["names"], "skipped": getattr(e, "message", None) or str(e)})
    return out


def _submit(tid, d):
    doc = _store.read_transcript(tid)
    if doc.get("evalSet") is True:
        raise _apply.Refused(_speakers.EVAL_SET_VOICE_MSG, 409, "eval_set")
    _tools.check_source(doc.get("sourcePath"))   # 元の動画が無ければ足さない(足しても失敗するだけ = 答えのたびに失敗のジョブを作らない)
    plan = _speakers.voice_learn_plan(doc, d["rows"])
    names = [n for n in d["names"] if n in plan["groups"]]
    if not names:
        raise _apply.Refused("覚えられる行がありません(答えたあとに行・名前が変わった可能性があります)", 409, "no_rows")
    rows = sorted({r for n in names for r in plan["rowIds"].get(n) or ()})
    spec = {"tid": tid, "embedding": d["emb"], "names": names, "confirmSame": names,   # カードで名前を選んだ = 同じ人(confirmSame を省く。5 節)
            "rows": rows, "by": "check", "title": _heavy.job_title("声を覚え直す(確かめる): ", doc)}
    job = _heavy.add_job(spec, "voice-learn")
    return {"names": names, "rows": len(rows), "job": job["id"]}


_apply.register(KIND, SOURCE, apply_voice, revert_voice, check_answer)
