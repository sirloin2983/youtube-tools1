"""「確かめる」のソロから声を覚えるカード speaker:solo(11-02。保管庫 plan/話者の物差し-1101.md 14 章 ①・ユーザー「ここまでは実装していい」)。

誰の声のカード(cards/speaker.js・コラボの 10 秒のカード speaker:collab と同じ画面と聞き方)。聞くことは「この 10 秒で話している人は誰?(全員)」の 1 つ。
音は研究(予備1)が取るソロの配信の 48 秒(1 本 2 か所 = 1/3 と 2/3 あたり。ソロの判定 = 2 人目 5% 以下を通った物)。その中で声がいちばん多い 10 秒を選んで流す。
  一覧   <app>/check/speaker-solo.json = {"cards": [{key, video, title, who, at, sec, speech: [[頭, 末]…]}]}(形は共有メモ 境目-声のカード.md の「11-02 夜」)
         音は <app>/check/speaker-solo/<key>.wav。一覧と音はこの PC の作業データにだけ置く(配る zip には入らない = 友人の PC では出ない)
  10 秒  speech(声の有無の検出の区間)といちばん重なる 10 秒(STEP 秒ずつずらして探す)。speech が無ければ真ん中の 10 秒。
         入口はその 10 秒だけを切り出して渡す(clip_piece・GET api/check/voicesolo。プレーヤーも 0:10 と出る = コラボの 10 秒と同じ)
  並び   誰の声のカードの中でランダム(app/check/lineup.SHUFFLE_KINDS)。FIRST_PEOPLE の人のカードは先頭(_first。11-02 ユーザー「こよりとめらを優先して」)
  ボタン コラボの 10 秒と同じ(配信者・名簿の全員を足す欄・誰か分からないメンバー・メンバー以外の人・ゲームの声・BGM が大きい・声色が違う・声なし)
  答え   {"names": [名前…], bgm?, alt?} か {"choice": "other"}(声なし)= コラボの 10 秒と同じ形(voice_collab.check_answer)
  覚える 配信者 1 人だけが選ばれ、印(bgm・alt)が無いときだけ、その 10 秒で製品の登録簿に声を覚える(人が確かめた物だけ。仮では入れない)。
         ほかの人・ゲームの声・印あり・声なし・分からないは覚えない。applied.learn = {name, start, end, sec} か None
  登録簿 入口の見回り tick(voice_fill_loop・1 分ごと)が、効いている答えの learn と登録簿の learnedFrom(doc = "solo:<key>"・sure: true)を突き合わせる:
         無ければジョブ voice-learn-clips(human/proof/speakers.run_voice_learn_clips)で入れ、Z で戻した答えの分が残っていればジョブ voice-unlearn で外してまとめ直す
         (行ごとの特徴の控え "solo:<key>#w" から。外すと何も残らない人は声を消す)。入らなかった物は RETRY_SEC たってから試し直す
  記録   applied = {solo: key, video, who, names, bgm?, alt?, piece: [頭, 末], learn}
  分からない その 10 秒の音と位置を控える(app/check/voice_unknown。11-02 ユーザー「わからないにしたやつ記憶しておいてほしい」)
"""
import io
import os
import re
import threading
import time
import wave

from flow import diar as _diar, jobs as _heavy, voicematerial as _vm
from human.check import answerlog, apply as _apply, voice as voice_mod
from ytt import fsio
from ytt.textutil import person_key as _person_key
from . import lineup, sources, voice_collab, voice_unknown

KIND, SOURCE = "speaker", "solo"
NAME, DIR_NAME, STATE_NAME = "speaker-solo.json", "speaker-solo", "speaker-solo-state.json"
ENABLED = True          # スイッチ: 答えで製品の登録簿に声を覚える・Z で外す見回り(11-02)
PIECE_SEC, STEP = 10.0, 0.5
BATCH = 10              # 1 つのジョブで覚える 10 秒の数
RETRY_SEC = 24 * 3600
DOC_PREFIX = "solo:"
KEY_RE = re.compile(r"^[a-z0-9]{1,16}\Z")
VIDEO_RE = re.compile(r"^[A-Za-z0-9_-]{11}\Z")
MAX_BYTES = 4 * 1024 * 1024
FIRST_PEOPLE = ("博衣こより", "熱千めら")   # 先頭に出す人(11-02 ユーザー「例外でこよりとめらを優先して・今日使いたいらしい」。済んだら空に)
_lock = threading.Lock()


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) < 1e7 else None


def load(app_dir):
    """一覧 -> [カード]。無い・読めなければ []。形の違うカードは飛ばす"""
    d = fsio.read_json_or(os.path.join(app_dir, "check", NAME), {}, max_bytes=MAX_BYTES, kind=dict) if app_dir else {}
    cards = []
    for c in d.get("cards") or ():
        if not isinstance(c, dict) or not KEY_RE.match(str(c.get("key") or "")) or not VIDEO_RE.match(str(c.get("video") or "")):
            continue
        who, sec = str(c.get("who") or "").strip()[:60], _num(c.get("sec"))
        if not who or not sec or sec <= 0:
            continue
        speech = [(a, b) for a, b in ((_num(x[0]), _num(x[1])) for x in c.get("speech") or () if isinstance(x, (list, tuple)) and len(x) == 2)
                  if a is not None and b is not None and b > a]
        cards.append(dict(c, who=who, sec=sec, speech=speech))
    return cards


def clip_path(app_dir, key):
    """48 秒の音のファイル(あれば)か None"""
    if not app_dir or not isinstance(key, str) or not KEY_RE.match(key):
        return None
    p = os.path.join(app_dir, "check", DIR_NAME, key + ".wav")
    return p if os.path.isfile(p) else None


def clip_piece(app_dir, key):
    """カードの 10 秒だけの音(wav のバイト列)か None。10 秒は一覧の speech から piece で決める(カードと同じ)"""
    p = clip_path(app_dir, key)
    c = next((c for c in load(app_dir) if c["key"] == key), None) if p else None
    if not c:
        return None
    a, b = piece(c["sec"], c["speech"])
    try:
        with wave.open(p, "rb") as w:
            rate, n = w.getframerate(), w.getnframes()
            s0, s1 = max(0, min(n, int(round(a * rate)))), max(0, min(n, int(round(b * rate))))
            w.setpos(s0)
            frames, params = w.readframes(s1 - s0), w.getparams()
    except (OSError, EOFError, wave.Error):
        return None
    buf = io.BytesIO()
    with wave.open(buf, "wb") as o:
        o.setparams(params)
        o.writeframes(frames)
    return buf.getvalue()


def piece(sec, speech):
    """声がいちばん多い 10 秒 -> (頭, 末)。speech が無ければ真ん中"""
    if sec <= PIECE_SEC:
        return 0.0, round(sec, 2)
    if not speech:
        a = round((sec - PIECE_SEC) / 2, 2)
        return a, round(a + PIECE_SEC, 2)
    best, best_a, a = -1.0, 0.0, 0.0
    while a + PIECE_SEC <= sec + 1e-9:
        got = sum(max(0.0, min(b, a + PIECE_SEC) - max(s, a)) for s, b in speech)
        if got > best + 1e-9:
            best, best_a = got, a
        a += STEP
    return round(best_a, 2), round(best_a + PIECE_SEC, 2)


def speaker_solo(view):
    app_dir = getattr(view.ctx, "app_dir", "") or ""
    cards = load(app_dir)
    if not cards:
        return []
    members = _vm.roster_people()
    first = {_person_key(n) for n in FIRST_PEOPLE}
    out = []
    for c in cards:
        if not clip_path(app_dir, c["key"]):
            continue
        a, b = piece(c["sec"], c["speech"])
        who = c["who"]
        out.append({"id": lineup.card_id(KIND, SOURCE, c["video"], c["key"]), "kind": KIND, "source": SOURCE,
                    "case": {"id": c["video"], "title": str(c.get("title") or "")[:120]},
                    "target": {"videoId": c["video"], "solo": c["key"], "piece": [a, b], "docId": None, "row": None},
                    "media": {"url": "api/check/voicesolo?key=%s" % c["key"], "start": 0.0, "end": round(b - a, 2), "pad": 0.0, "padEnd": 0.0},   # 音は 10 秒だけ(clip_piece)
                    "text": "", "people": [who], "who": who, "at": _num(c.get("at")),
                    "pick": [n for n in dict.fromkeys(members) if _person_key(n) != _person_key(who)], "otherPerson": voice_collab.OTHER_PERSON,
                    "score": None, "note": "", "cast": [who], "_first": _person_key(who) in first})   # 並びは誰の声の中でランダム(lineup)
    return out


def learn_of(who, ans, a, b):
    """覚えるなら {name, start, end, sec}(配信者 1 人だけ・印なし)。ほかは None"""
    names = list(ans.get("names") or [])
    if len(names) != 1 or _person_key(names[0]) != _person_key(who) or ans.get("bgm") or ans.get("alt"):
        return None
    if a is None or b is None or b - a < voice_mod.MIN_LEARN_SEC:
        return None
    return {"name": who, "start": a, "end": b, "sec": round(b - a, 2)}


def _apply_solo(ctx, card, ans):
    """文書が無いので実物は変えない。覚えるかは applied.learn に書き、登録簿へは見回りが入れる"""
    t = card.get("target") or {}
    a, b = (_num(x) for x in (list(t.get("piece") or ()) + [None, None])[:2])   # 48 秒の音の中の 10 秒(覚えるのはこの 10 秒)
    out = {"solo": t.get("solo"), "video": t.get("videoId"), "who": card.get("who"), "names": list(ans.get("names") or []),
           "piece": [a, b], "learn": learn_of(card.get("who") or "", ans, a, b)}
    for k in ("bgm", "alt"):
        if ans.get(k):
            out[k] = True
    return out


def _revert_solo(ctx, row):
    return {"solo": (row.get("applied") or {}).get("solo")}   # 登録簿から外すのは見回り


# ---- 登録簿の見回り ----

def _state_path(app_dir):
    return os.path.join(app_dir, "check", STATE_NAME)


def read_state(app_dir):
    d = fsio.read_json_or(_state_path(app_dir), {}, kind=dict) if app_dir else {}
    return {k: d.get(k) if isinstance(d.get(k), dict) else {} for k in ("asked", "failed")}


def _write_state(app_dir, st):
    os.makedirs(os.path.dirname(_state_path(app_dir)), exist_ok=True)
    fsio.write_json(_state_path(app_dir), st, indent=None)


def wanted(app_dir):
    """効いている答えのうち覚える物 -> {doc: {key, name, start, end}}"""
    out = {}
    for r in answerlog.state(app_dir).effective():
        if r.get("kind") != KIND or r.get("source") != SOURCE:
            continue
        ap = r.get("applied") or {}
        lr, key = ap.get("learn"), str(ap.get("solo") or "")
        if isinstance(lr, dict) and KEY_RE.match(key) and _num(lr.get("start")) is not None and _num(lr.get("end")) is not None:
            out[DOC_PREFIX + key] = {"key": key, "name": str(lr.get("name") or ""), "start": _num(lr["start"]), "end": _num(lr["end"])}
    return out


def _registry_docs(voices):
    """登録簿のソロの 10 秒の文書 -> {文書: 登録簿の名前}"""
    out = {}
    for n, v in voices.items():
        for lf in v.get("learnedFrom") or ():
            if isinstance(lf, dict) and str(lf.get("doc") or "").startswith(DOC_PREFIX):
                out[lf["doc"]] = n
    return out


def tick(app_dir, busy, log, now=None):
    """見回り 1 回: Z で戻した分を外す(voice-unlearn)→ まだ入れていない答えの 10 秒を入れる(voice-learn-clips)。-> 頼んだジョブの種類か None"""
    if not ENABLED or not app_dir or voice_mod.RELEARN_PAUSED or busy():
        return None
    if "voice-learn-clips" not in _heavy.JOB_RUNNERS or "voice-unlearn" not in _heavy.JOB_RUNNERS or not _diar.voice_ready():
        return None
    if _heavy.active_jobs("voice-learn-clips") or _heavy.active_jobs("voice-unlearn"):
        return None
    now = time.time() if now is None else now
    want = wanted(app_dir)
    emb = _diar.learn_embedding("")
    voices = _diar.load_voices(emb)
    have = _registry_docs(voices)
    with _lock:
        st = read_state(app_dir)
        drop = {}
        for d, name in have.items():
            if d not in want:
                drop.setdefault(name, []).append(d)
        if drop:
            name, docs = sorted(drop.items())[0]
            job = _heavy.add_job({"embedding": emb, "name": name, "docs": sorted(docs), "title": "戻した答えの声を外す(確かめる): %s %d 個" % (name, len(docs))}, "voice-unlearn")
            log("ソロの 10 秒: %s の戻した答え %d 個を登録簿から外すジョブ %s を足しました" % (name, len(docs), job["id"]))
            return "voice-unlearn"
        for d in list(st["asked"]):   # 頼んだジョブが終わったのに入っていない = 失敗(RETRY_SEC まで試さない)
            del st["asked"][d]
            if d not in have:
                st["failed"][d] = {"at": int(now * 1000)}
        for d in [d for d in st["failed"] if d in have or d not in want]:
            del st["failed"][d]
        todo = [(d, w) for d, w in sorted(want.items()) if d not in have and clip_path(app_dir, w["key"])
                and (d not in st["failed"] or now * 1000 - int((st["failed"][d] or {}).get("at") or 0) >= RETRY_SEC * 1000)][:BATCH]
        if not todo:
            _write_state(app_dir, st)
            return None
        names = {_person_key(n): n for n in voices}
        clips = []
        for d, w in todo:
            who = names.get(_person_key(w["name"]), w["name"])
            clips.append({"doc": d, "clip": clip_path(app_dir, w["key"]), "names": [who], "groups": {who: [[w["start"], w["end"]]]},
                          "rowIds": {who: ["w"]}, "sure": True, "by": "check"})
        job = _heavy.add_job({"embedding": emb, "clips": clips, "by": "check", "title": "ソロの 10 秒で声を覚える(確かめる): %d 個" % len(clips)}, "voice-learn-clips")
        for d, _w in todo:
            st["asked"][d] = {"job": job["id"], "at": int(now * 1000)}
        _write_state(app_dir, st)
    log("ソロの 10 秒: %d 個を登録簿へ入れるジョブ %s を足しました" % (len(todo), job["id"]))
    return "voice-learn-clips"


def _unknown_solo(ctx, card, row):
    app_dir = getattr(ctx, "app_dir", "") or ""
    voice_unknown.keep(app_dir, card, row, clip_piece(app_dir, (card.get("target") or {}).get("solo")))


sources.register(KIND, SOURCE, speaker_solo)
_apply.register(KIND, SOURCE, _apply_solo, _revert_solo, voice_collab.check_answer, on_unknown=_unknown_solo)
