"""「確かめる」の声の材料の確かめのカード material:solo と、人が確かめた声の材料だけを製品の登録簿へ入れる見回り(11-02。保管庫 plan/話者の物差し-1101.md の 13 章「カード ア」・要件 4)。

声の材料 = 行ごとの話者の一覧(app/check/voice_lines の speaker-lines.json)のうち material: true のかけら(研究がソロの判定を通した 48 秒ほど。
題名の決まり + 判別で 2 人目 5% 以下)。音は同じ speaker-lines/<key>.wav。
  入れる   見回り tick が、人が「この人だけ」と答えた(sure)かけらのうち登録簿に無い物を BATCH 個ずつジョブ voice-learn-material(human/proof/speakers.run_voice_learn_material)で入れる。
           人が確かめていないかけらは入れない(11-02 午後 ユーザー「人が確かめてないものを追加しないで」。前は全部を「仮」で入れていた)。
           覚えるのはかけらの 1 秒以上の行を配信者(who)の声として。登録簿の learnedFrom の文書の名前は "material:<key>"・sure = True。
           行ごとの特徴の控え(voices/<モデル>.rows.json の "material:<key>#<行>")も残す = 配信ごと・かけらごとに外してまとめ直せる。
           入れられなかったかけらは RETRY_SEC たってから試し直す。覚え直しの一時止め(human/check/voice.RELEARN_PAUSED)の間と入口の手が空いていない間は休む
  カード   配信ごとに 1 枚(PER_VIDEO。まず 1 本 1 枚で始め、混ざりの見つかる割合を見て増やす)。配信のかけらから 1 つ(配信ごとに頭・中・終わりが散るよう選ぶ)・
           その中の行の切れ目の一切れ(6 秒ほど・話す時間がいちばん長い一切れ)。前後の数秒も流せる(画面 cards/material.js)
  答え     {"answer": "only" | "not" | "mixed" | "unusual" | "unknown"} = この人だけ / この人ではない / 別の声が混ざる(客・ゲームのキャラ) /
           声がふだんと違う(BGM 大・叫び・ささやき) / 分からない
  反映     only = そのかけらを「確か」に(= 登録簿へ入れる) / not・mixed = その配信のかけらを全部外す / unusual = そのかけらだけ外す / unknown = 変えない。
           状態は <app>/check/voice-material-state.json({sure: {key: {by, at}}, dropped: {key: {why, by, video, at}}, asked, failed})に書き、
           登録簿への反映は見回りがする: 確かでない(sure に無い・dropped にある)material:* が登録簿にあれば、先にジョブ voice-unlearn でまとめ直して外す
           (前に仮で入れた分・Z で確かを取り消した分も)。Z = その答えで書いた状態を消す
  記録     applied = {material: key, video, who, at, part, piece: [頭, 末](かけらの中の秒), answer, keys: [状態を変えたかけら]}
"""
import os
import threading
import time
import zlib

from flow import diar as _diar, jobs as _heavy
from human.check import apply as _apply, voice as voice_mod
from ytt import fsio
from ytt.textutil import person_key as _person_key
from . import lineup, sources, voice_lines

KIND, SOURCE = "material", "solo"
STATE_NAME = "voice-material-state.json"
ENABLED = True       # スイッチ: 人が確かめた声の材料を登録簿へ入れ、確かでない分を外す見回り(11-02)
PER_VIDEO = 1        # 配信ごとのカードの枚数(まず 1。混ざりの見つかる割合を見て増やす)
BATCH = 10           # 1 つのジョブで入れるかけらの数
RETRY_SEC = 24 * 3600
NEAR_SEC = 5.0       # 「前後も流す」で足す秒
ANSWERS = {"only": "この人だけ", "not": "この人ではない", "mixed": "別の声が混ざる", "unusual": "声がふだんと違う", "unknown": "分からない"}
DOC_PREFIX = "material:"
_lock = threading.Lock()


def _state_path(app_dir):
    return os.path.join(app_dir, "check", STATE_NAME)


def read_state(app_dir):
    d = fsio.read_json_or(_state_path(app_dir), {}, kind=dict) if app_dir else {}
    return {k: d.get(k) if isinstance(d.get(k), dict) else {} for k in ("sure", "dropped", "asked", "failed")}


def _write_state(app_dir, st):
    os.makedirs(os.path.dirname(_state_path(app_dir)), exist_ok=True)
    fsio.write_json(_state_path(app_dir), st, indent=None)


def materials(app_dir):
    """声の材料のかけら(音があるもの)-> [カード](voice_lines.load の形)"""
    _people, cards = voice_lines.load(app_dir)
    return [c for c in cards if c["material"] and voice_lines.clip_path(app_dir, c["key"])]


def learn_rows(c):
    """かけらの覚える行(1 秒以上)-> [(行 id, 頭, 末)]"""
    return [(r["id"], r["start"], r["end"]) for r in c["rows"] if r["end"] - r["start"] >= voice_mod.MIN_LEARN_SEC]


def _pick(cards, video):
    """配信のかけらから 1 つ(配信ごとに場所が散るよう、配信の id で回す)"""
    cs = sorted(cards, key=lambda c: (str(c.get("part") or ""), c["key"]))
    return cs[zlib.crc32(video.encode("utf-8")) % len(cs)]


def _best_piece(c):
    ps = voice_lines.pieces(c["rows"])
    return max(ps, key=lambda rows: sum(r["end"] - r["start"] for r in rows))


def material_cards(view):
    app_dir = getattr(view.ctx, "app_dir", "") or ""
    st = read_state(app_dir)
    by_video = {}
    for c in materials(app_dir):
        if c["key"] not in st["dropped"]:
            by_video.setdefault(c["video"], []).append(c)
    out = []
    for video, cs in by_video.items():
        left = list(cs)
        for n in range(min(PER_VIDEO, len(cs))):
            c = _pick(left, video)
            left.remove(c)
            rows = _best_piece(c)
            a, b = max(0.0, rows[0]["start"] - voice_lines.PIECE_PAD), min(c["sec"], max(r["end"] for r in rows) + voice_lines.PIECE_PAD)
            out.append({"id": lineup.card_id(KIND, SOURCE, video, c["key"]), "kind": KIND, "source": SOURCE,
                        "case": {"id": video, "title": str(c.get("title") or "")[:120]},
                        "target": {"videoId": video, "material": c["key"], "docId": None, "row": None},
                        "media": {"url": "api/check/voicelines?key=%s" % c["key"], "start": round(a, 3), "end": round(b, 3), "pad": 0.0, "padEnd": 0.0},
                        "near": [round(max(0.0, a - NEAR_SEC), 3), round(min(c["sec"], b + NEAR_SEC), 3)],
                        "text": "", "who": c["who"], "at": c.get("at"), "part": str(c.get("part") or "")[:8], "sure": c["key"] in st["sure"],
                        "answers": [[k, v] for k, v in ANSWERS.items()], "sourceLabel": "声の材料", "guess": None, "score": None, "note": "", "cast": [c["who"]],
                        "_order": [-1, zlib.crc32(c["key"].encode("utf-8")), n]})
    return out


def check_answer(ans):
    if not isinstance(ans, dict) or set(ans) != {"answer"} or ans["answer"] not in ANSWERS:
        raise ValueError("答えは {answer: %s} の形で送ってください" % " | ".join(ANSWERS))
    return {"answer": ans["answer"]}


def _apply_material(ctx, card, ans):
    app_dir = getattr(ctx, "app_dir", "") or ""
    t, a, cid = card.get("target") or {}, ans["answer"], card.get("id")
    key, video = t.get("material"), t.get("videoId")
    now = int(time.time() * 1000)
    keys = []
    with _lock:
        st = read_state(app_dir)
        if a == "only":
            st["sure"][key] = {"by": cid, "at": now}
            keys = [key]
        elif a in ("not", "mixed", "unusual"):
            keys = [c["key"] for c in materials(app_dir) if c["video"] == video] if a != "unusual" else [key]
            for k in keys:
                st["dropped"].setdefault(k, {"why": a, "by": cid, "video": video, "at": now})
        if keys:
            _write_state(app_dir, st)
    m = card.get("media") or {}
    return {"material": key, "video": video, "who": card.get("who"), "at": card.get("at"), "part": card.get("part"),
            "piece": [m.get("start"), m.get("end")], "answer": a, "keys": keys}


def _revert_material(ctx, row):
    app_dir = getattr(ctx, "app_dir", "") or ""
    cid = row.get("card") or row.get("id")
    with _lock:
        st = read_state(app_dir)
        changed = False
        for part in ("sure", "dropped"):
            for k in [k for k, v in st[part].items() if isinstance(v, dict) and v.get("by") == cid]:
                del st[part][k]
                changed = True
        if changed:
            _write_state(app_dir, st)
    return {"material": (row.get("applied") or {}).get("material")}


def _registry_docs(voices):
    """登録簿の声の材料の文書 -> {文書: (登録簿の名前, sure)}"""
    out = {}
    for n, v in voices.items():
        for lf in v.get("learnedFrom") or ():
            if isinstance(lf, dict) and str(lf.get("doc") or "").startswith(DOC_PREFIX):
                out[lf["doc"]] = (n, lf.get("sure") is True)
    return out


def tick(app_dir, busy, log, now=None):
    """見回り 1 回: 確かでない材料を外す(voice-unlearn)→ 確かの印 → 確かなかけらでまだ入れていない物を入れる(voice-learn-material)。-> 頼んだジョブの種類か None"""
    if not ENABLED or not app_dir or voice_mod.RELEARN_PAUSED or busy():
        return None
    if "voice-learn-material" not in _heavy.JOB_RUNNERS or not _diar.voice_ready():
        return None
    if _heavy.active_jobs("voice-learn-material") or _heavy.active_jobs("voice-unlearn"):
        return None
    now = time.time() if now is None else now
    emb = _diar.learn_embedding("")
    voices = _diar.load_voices(emb)
    have = _registry_docs(voices)
    with _lock:
        st = read_state(app_dir)
        keep = {k for k in st["sure"] if k not in st["dropped"]}
        drop = {}
        for d, (name, _sure) in have.items():   # 確かでない材料(前に仮で入れた分・外す答え・確かを取り消した分)は外す
            if d[len(DOC_PREFIX):] not in keep:
                drop.setdefault(name, []).append(d)
        if drop:
            name, docs = sorted(drop.items())[0]
            job = _heavy.add_job({"embedding": emb, "name": name, "docs": sorted(docs), "title": "確かでない声の材料を外す: %s %d 個" % (name, len(docs))}, "voice-unlearn")
            log("声の材料: %s の確かでない %d 個を登録簿から外すジョブ %s を足しました(残り %d 人)" % (name, len(docs), job["id"], len(drop) - 1))
            return "voice-unlearn"
        fix = {d for d, (_n, sure) in have.items() if not sure}
        if fix:
            with _diar.voices_edit(emb) as cur:
                for v in cur.values():
                    for lf in v.get("learnedFrom") or ():
                        if isinstance(lf, dict) and lf.get("doc") in fix:
                            lf["sure"] = True
        for k, rec in list(st["asked"].items()):   # 頼んだジョブが終わったのに入っていない = 失敗(RETRY_SEC まで試さない)
            if not any(j["id"] == rec.get("job") for j in _heavy.active_jobs("voice-learn-material")):
                del st["asked"][k]
                if DOC_PREFIX + k not in have:
                    st["failed"][k] = {"at": int(now * 1000)}
        mats = [c for c in materials(app_dir) if c["key"] in keep] if keep else []
        todo = [c for c in mats if DOC_PREFIX + c["key"] not in have and learn_rows(c)
                and (c["key"] not in st["failed"] or now * 1000 - int((st["failed"][c["key"]] or {}).get("at") or 0) >= RETRY_SEC * 1000)][:BATCH]
        if not todo:
            _write_state(app_dir, st)
            return None
        names = {_person_key(n): n for n in voices}
        clips = []
        for c in todo:
            who = names.get(_person_key(c["who"]), c["who"])
            rows = learn_rows(c)
            clips.append({"doc": DOC_PREFIX + c["key"], "clip": voice_lines.clip_path(app_dir, c["key"]), "names": [who],
                          "groups": {who: [[a, b] for _r, a, b in rows]}, "rowIds": {who: [r for r, _a, _b in rows]}, "sure": True, "by": "material"})
        job = _heavy.add_job({"embedding": emb, "clips": clips, "by": "material", "title": "確かめた声の材料を登録簿へ入れる: %d 個" % len(clips)}, "voice-learn-material")
        for c in todo:
            st["asked"][c["key"]] = {"job": job["id"], "at": int(now * 1000)}
        _write_state(app_dir, st)
    left = sum(1 for c in mats if DOC_PREFIX + c["key"] not in have) - len(todo)
    log("声の材料: 確かめた %d 個を登録簿へ入れるジョブ %s を足しました(残り %d 個)" % (len(todo), job["id"], max(0, left)))
    return "voice-learn-material"


sources.register(KIND, SOURCE, material_cards)
_apply.register(KIND, SOURCE, _apply_material, _revert_material, check_answer)
