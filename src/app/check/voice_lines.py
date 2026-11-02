"""「確かめる」の行ごとの話者と区切りのカード lines:seg(11-02。ユーザー「誰の声カードでそれぞれの行に話者をあてる形にしてほしい・ついでに行の中身も調整する」・
11-02 午後に決め直した形 = 保管庫 plan/話者の物差し-1101.md の 13 章「カード イ」)。
誰の声のカード(voice:solo・voice:measure)・コラボの話者(speaker:collab)とは別の種類・別の描き方(cards/lines.js)。

カード 1 枚 = 短いかけらの一切れ(PIECE_SEC 秒ほど。11-02 ユーザー「48秒は長すぎる。秒数は今の秒数くらいでいい」)。研究が置く 48 秒ほどのかけらは、
ここで行の切れ目で一切れずつに分ける(音のファイルは 1 つのまま・再生の窓だけ変える)。音は友人の依頼のコラボ・声の材料のソロ配信・研究のコラボ
(かけらの from。人・配信・場面を散らすのは置く側)。中の行ごとに話者を選び(初めは道具の予想の 1 位 = つられは気にしない)、行の区切りと文字も直す
= 行ごとの話者の正解(要件 16)と区切りの正解(要件 17)を 1 度に作る。かけらと行・予想は研究が作り、作業データに置く(受け渡しの形は共有メモ 境目-声のカード.md)。
  一覧   <app>/check/speaker-lines.json = {"people": [声を覚えた全員…], "cards": [{key, video, title, who: 配信者, at: 配信の中の秒, sec, part,
         material?: true(ソロの判定を通った声の材料 = app/check/voice_material が登録簿へ仮で入れる・カード ア), from?, scene?, cast?: [出る人…],
         rows: [{id, start, end(かけらの頭からの秒), text, guess: [{name, score}…上から], words?: [{w, start, end}…](Haas の言葉ごとの時刻)}]}]}
  音     <app>/check/speaker-lines/<key>.wav(かけらの頭が 0 秒)
  言葉   行を分ける・言葉を移すのは言葉の切れ目(行の words)。words の無い行は 1 字ずつ・時刻は字数の割合 = 区切りを変えると「時刻は仮」(timeGuess)
  選べる物 行ごとに 出る人・名簿の全員(確かめるのメンバーの表)・声を覚えた全員・打った名前・ほかの人(OTHER_PERSON)・声なし・2 人同時(その 2 人も)・分からない
  答え   {"rows": [{w: [頭, 末)(一切れの言葉の通し番号。全部の行を順に・隙間なく), speaker? | both?: [名前, 名前] | none?: true | unknown?: true, text?}],
          voiceNoRow?: true(行が無い声がある)}。{} = 全部の行が予想どおり・区切りも文字もそのまま。speaker を省いた行は予想の 1 位
  記録   applied = {lines, piece, video, who, at, part, from, scene, cuts0, cuts, voiceNoRow?, rows: [{id, from: [元の行…], start, end, timeGuess?, guess, guessScore,
         speaker, both?, none?, unknown?, text0, text}], doc = "lines:<key>", learn, relearn?}(全部の行)。文書が無いので実物は書き換えない。採点は研究の側
  声     製品の声の登録簿を覚え直す(11-02 ユーザー「答えても正解の行だけ増えて登録簿が増えないのはまずい」)。決まりは誰の声のカードと同じ
         (human/check/voice._maybe_relearn: 名前で答えた 1 秒以上の行・ほかの人・声なし・2 人同時・分からない・時刻が仮の行は除く・初めての人は 10 秒で仮・
         30 秒ごと・learnedFrom で同じ行を 2 度覚えない・Z で材料から外れる)。音はかけらのファイルから(ジョブ voice-learn-clip)
  一覧のファイルはこの PC の作業データにだけ置く(配る zip には入らない = 友人の PC では出ない)
"""
import os
import random
import re

from human.check import apply as _apply, voice as voice_mod
from ytt import fsio, txbase as _txbase
from . import lineup, members, sources

KIND, SOURCE = "lines", "seg"
NAME, DIR_NAME = "speaker-lines.json", "speaker-lines"
OTHER_PERSON = "ほかの人"   # 声を覚えた人の誰でもない人の声
MAX_ROWS, MAX_TEXT, MAX_SEC, MAX_GUESS, MAX_PEOPLE, MAX_WORDS = 40, 200, 60.0, 3, 200, 200
PIECE_SEC = 6.0   # 一切れの長さの目安(行を足してこれを超えるなら次の一切れ。1 行で超える行は 1 行で一切れ)
PIECE_PAD = 0.3   # 一切れの再生の前後の余白(秒)
MAX_ANSWER_BYTES = 48 * 1024   # 分けた行の文字を全部直しても入る大きさ
KEY_RE = re.compile(r"^[a-z0-9]{1,16}\Z")
VIDEO_RE = re.compile(r"^[A-Za-z0-9_-]{11}\Z")
ROW_RE = re.compile(r"^[A-Za-z0-9_-]{1,16}\Z")
FROM_RE = re.compile(r"^[a-z]{1,12}\Z")
MAX_BYTES = 8 * 1024 * 1024


def _num(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


def _name(x):
    return x.strip() if isinstance(x, str) and x.strip() and len(x.strip()) <= 30 else None


def _words(r, a, b):
    """行の言葉の時刻(研究の words)-> [{w, start, end}] か None(無い・形が違う・時刻が行の外・順が逆)"""
    ws = r.get("words")
    if not isinstance(ws, list) or not 0 < len(ws) <= MAX_WORDS:
        return None
    out, last = [], a
    for x in ws:
        s, e = (_num(x.get("start")), _num(x.get("end"))) if isinstance(x, dict) else (None, None)
        if s is None or e is None or not isinstance(x.get("w"), str) or e < s or s < last - 0.05 or s < a - 0.3 or e > b + 0.3:
            return None
        out.append({"w": x["w"][:40], "start": round(min(b, max(a, s)), 3), "end": round(min(b, max(a, e)), 3)})
        last = s
    return out


def _rows(c, sec):
    out, seen = [], set()
    for r in c.get("rows") or ():
        if not isinstance(r, dict) or not ROW_RE.match(str(r.get("id") or "")) or r["id"] in seen:
            return None
        a, b = _num(r.get("start")), _num(r.get("end"))
        if a is None or b is None or not 0 <= a < b <= sec + 0.05 or not isinstance(r.get("text"), str):
            return None
        b = min(b, sec)
        g = [{"name": _name(x.get("name")), "score": _num(x.get("score"))} for x in r.get("guess") or () if isinstance(x, dict) and _name(x.get("name"))]
        seen.add(r["id"])
        one = {"id": r["id"], "start": round(a, 3), "end": round(b, 3), "text": r["text"][:MAX_TEXT], "guess": g[:MAX_GUESS]}
        ws = _words(r, a, b)
        if ws:
            one["words"] = ws
        out.append(one)
    return out if 0 < len(out) <= MAX_ROWS else None


def load(app_dir):
    """一覧 -> (声を覚えた全員, [カード])。無い・読めなければ ([], [])。形の違うカードは飛ばす"""
    d = fsio.read_json_or(os.path.join(app_dir, "check", NAME), {}, max_bytes=MAX_BYTES, kind=dict) if app_dir else {}
    cards = []
    for c in d.get("cards") or ():
        if not isinstance(c, dict) or not KEY_RE.match(str(c.get("key") or "")) or not VIDEO_RE.match(str(c.get("video") or "")) or not _name(c.get("who")):
            continue
        sec = _num(c.get("sec"))
        if sec is None or not 0 < sec <= MAX_SEC:
            continue
        rows = _rows(c, sec)
        if rows:
            who = _name(c["who"])
            cast = [n for n in (_name(x) for x in (c["cast"][:10] if isinstance(c.get("cast"), list) else ())) if n]
            extra = {"from": str(c["from"]) if FROM_RE.match(str(c.get("from") or "")) else "",
                     "scene": str(c["scene"])[:12] if isinstance(c.get("scene"), str) else ""}
            cards.append(dict(c, sec=sec, rows=rows, who=who, material=c.get("material") is True, cast=list(dict.fromkeys([who] + cast)), **extra))
    people = [p for p in (_name(x) for x in (d.get("people") or ())[:MAX_PEOPLE]) if p]
    return list(dict.fromkeys(people)), cards


def clip_path(app_dir, key):
    """かけらの音のファイル(あれば)か None"""
    if not app_dir or not isinstance(key, str) or not KEY_RE.match(key):
        return None
    p = os.path.join(app_dir, "check", DIR_NAME, key + ".wav")
    return p if os.path.isfile(p) else None


def pieces(rows, size=PIECE_SEC):
    """かけらの行(時刻の順)-> [[行…]…] 一切れずつ。行を足すと一切れの頭から size 秒を超えるなら次の一切れへ(行は割らない)"""
    out = []
    for r in sorted(rows, key=lambda r: (r["start"], r["end"])):
        if out and r["end"] - out[-1][0]["start"] <= size:
            out[-1].append(r)
        else:
            out.append([r])
    return out


def words_of(r):
    """行の言葉 -> ([[言葉, 頭, 末]…], 時刻が確かか)。words が無ければ 1 字ずつ(空白は捨てる)・時刻は字数の割合 = 仮。文字が無い行は空の言葉 1 つ"""
    if r.get("words"):
        return [[w["w"], w["start"], w["end"]] for w in r["words"]], True
    chars = [ch for ch in str(r.get("text") or "") if not ch.isspace()][:MAX_WORDS] or [""]
    step = (r["end"] - r["start"]) / len(chars)
    return [[ch, round(r["start"] + i * step, 3), round(r["start"] + (i + 1) * step, 3)] for i, ch in enumerate(chars)], False


def roster_names():
    """名簿の全員(確かめるのメンバーの表の期の順)"""
    idx = members.index()
    out = [n for g in idx["groups"] if isinstance(g, dict) for n in g.get("names") or () if isinstance(n, str)]
    return list(dict.fromkeys(out + [n for n in idx["members"] if isinstance(n, str)]))


def _card_row(r):
    ws, timed = words_of(r)
    return dict({k: v for k, v in r.items() if k != "words"}, guess=(r["guess"][0]["name"] if r["guess"] else None),
                score=(r["guess"][0]["score"] if r["guess"] else None), second=(r["guess"][1] if len(r["guess"]) > 1 else None), words=ws, timed=timed)


def voice_lines(view):
    app_dir = getattr(view.ctx, "app_dir", "") or ""
    people, cards = load(app_dir)
    roster = roster_names() if cards else []
    out = []
    for c in cards:
        if not clip_path(app_dir, c["key"]):
            continue
        at, rnd = _num(c.get("at")), random.random()
        for i, rows in enumerate(pieces(c["rows"])):
            names = list(dict.fromkeys(c["cast"] + [g["name"] for r in rows for g in r["guess"]] + people + roster))
            a, b = max(0.0, rows[0]["start"] - PIECE_PAD), min(c["sec"], max(r["end"] for r in rows) + PIECE_PAD)
            out.append({"id": lineup.card_id(KIND, SOURCE, c["video"], c["key"], i), "kind": KIND, "source": SOURCE,
                        "case": {"id": c["video"], "title": str(c.get("title") or "")[:120]},
                        "target": {"videoId": c["video"], "lines": c["key"], "piece": i, "docId": None, "row": None},
                        "media": {"url": "api/check/voicelines?key=%s" % c["key"], "start": round(a, 3), "end": round(b, 3), "pad": 0.0, "padEnd": 0.0},
                        "clipSec": c["sec"], "text": "", "who": c["who"], "at": at, "part": str(c.get("part") or "")[:8], "from": c["from"], "scene": c["scene"],
                        "rows": [_card_row(r) for r in rows],
                        "people": names, "otherPerson": OTHER_PERSON, "guess": None, "score": None, "note": "", "cast": c["cast"],
                        "_order": [0, c["video"], rnd, i]})   # 配信ごとにまとめ、同じかけらの一切れは続けて頭から出す(同じ人の声が続く = 迷わない)
    return out


def check_answer(ans):
    """答えを整える -> {"rows": [{w, speaker? | both? | none? | unknown?, text?}], voiceNoRow?}(空なら {})。違えば ValueError(400)。
    言葉の範囲が一切れの全部を隙間なく覆うかは、カードを見る _apply_lines が確かめる"""
    if not isinstance(ans, dict) or not set(ans) <= {"rows", "voiceNoRow"}:
        raise ValueError("答えは {rows: [{w, speaker?, both?, none?, unknown?, text?}], voiceNoRow?} の形で送ってください")
    out = {}
    if "voiceNoRow" in ans:
        if ans["voiceNoRow"] is not True:
            raise ValueError("voiceNoRow は true だけ送れます")
        out["voiceNoRow"] = True
    if "rows" not in ans:
        return out
    rows = ans["rows"]
    if not isinstance(rows, list) or not 0 < len(rows) <= MAX_ROWS * 4:
        raise ValueError("rows は %d 行までの並びです" % (MAX_ROWS * 4))
    got = []
    for r in rows:
        if not isinstance(r, dict) or not set(r) <= {"w", "speaker", "both", "none", "unknown", "text"}:
            raise ValueError("行の答えの形が正しくありません")
        w = r.get("w")
        if not isinstance(w, list) or len(w) != 2 or not all(isinstance(x, int) and not isinstance(x, bool) for x in w) or not 0 <= w[0] < w[1]:
            raise ValueError("w は [頭, 末](言葉の通し番号)で送ってください")
        if sum(k in r for k in ("speaker", "both", "none", "unknown")) > 1:
            raise ValueError("話者・2 人同時・声なし・分からないは 1 つだけ送れます")
        one = {"w": list(w)}
        if "speaker" in r:
            one["speaker"] = voice_mod._check_answer({"name": r["speaker"]})["name"]
        if "both" in r:
            b = r["both"]
            if not isinstance(b, list) or len(b) != 2:
                raise ValueError("2 人同時は [名前, 名前] で送ってください")
            one["both"] = [voice_mod._check_answer({"name": n if isinstance(n, str) else ""})["name"] for n in b]
            if one["both"][0] == one["both"][1]:
                raise ValueError("2 人同時は違う 2 人を選んでください")
        for k in ("none", "unknown"):
            if k in r:
                if r[k] is not True:
                    raise ValueError("%s は true だけ送れます" % k)
                one[k] = True
        if "text" in r:
            if not isinstance(r["text"], str) or len(r["text"]) > MAX_TEXT:
                raise ValueError("文字は %d 字までです" % MAX_TEXT)
            one["text"] = r["text"].strip()
        got.append(one)
    out["rows"] = got
    return out


def _flat(card):
    """一切れの言葉の通し -> ([(行の番号, 言葉, 頭, 末)…], 元の区切り = 各行の頭の通し番号)"""
    flat, cuts = [], []
    for i, r in enumerate(card.get("rows") or ()):
        cuts.append(len(flat))
        ws = r.get("words") or [[r.get("text", ""), r["start"], r["end"]]]
        flat += [(i, w[0], w[1], w[2]) for w in ws]
    return flat, cuts


def _segments(card, ans):
    """答えの行 -> (言葉の通し, 元の区切り, [(元の行の番号の並び, 頭の通し番号, 末の通し番号, 答え)])。範囲が隙間なく全部を覆わなければ 400"""
    flat, cuts0 = _flat(card)
    ends = cuts0[1:] + [len(flat)]
    rows = ans.get("rows")
    if not rows:
        return flat, cuts0, [([i], a, b, {}) for i, (a, b) in enumerate(zip(cuts0, ends))]
    pos, out = 0, []
    for r in rows:
        a, b = r["w"]
        if a != pos or b > len(flat):
            raise _apply.Refused("行の区切りが一切れの言葉と合いません(画面を読み込み直してください)", 400, "bad_request")
        out.append((sorted({flat[k][0] for k in range(a, b)}), a, b, r))
        pos = b
    if pos != len(flat):
        raise _apply.Refused("行の区切りが一切れの言葉の終わりまで届いていません", 400, "bad_request")
    return flat, cuts0, out


def _apply_lines(ctx, card, ans):
    """文書が無いので実物は変えない。-> applied(答えたあとの全部の行の 予想・答えた話者・元の文字・直した文字・時刻が仮か + 区切りの前後・覚える材料 learn・覚え直し relearn)。
    予想の無い行に答えが無ければ 400"""
    t, src = card.get("target") or {}, card.get("rows") or []
    flat, cuts0, segs = _segments(card, ans)
    ends = cuts0[1:] + [len(flat)]
    rows, n_sub = [], {}
    for idx, a, b, r in segs:
        head, tail = flat[a][0], flat[b - 1][0]
        main = max(idx, key=lambda i: sum(1 for k in range(a, b) if flat[k][0] == i))   # 言葉の多い元の行の予想を初めの答えにする
        o = src[main]
        whole = idx == [head] and a == cuts0[head] and b == ends[head]
        if a == cuts0[head]:
            rid = src[head]["id"]
        else:
            n_sub[head] = n_sub.get(head, 0) + 1
            rid = "%s.%d" % (src[head]["id"], n_sub[head])
        start = src[head]["start"] if a == cuts0[head] else flat[a][2]
        end = src[tail]["end"] if b == ends[tail] else flat[b - 1][3]
        text0 = o["text"] if whole else "".join(flat[k][1] for k in range(a, b))
        one = {"id": rid, "from": [src[i]["id"] for i in idx], "start": round(start, 3), "end": round(max(end, start), 3), "guess": o.get("guess"),
               "guessScore": o.get("score"), "speaker": None, "text0": text0, "text": r.get("text", text0)}
        if not whole and any(src[i].get("timed") is False for i in idx):   # 区切りを変えた行に字の割合の時刻の行が入る = 時刻は仮
            one["timeGuess"] = True
        if r.get("none"):
            one["none"] = True
        elif r.get("unknown"):
            one["unknown"] = True
        elif r.get("both"):
            one["both"] = list(r["both"])
        else:
            one["speaker"] = r.get("speaker", o.get("guess"))
            if not one["speaker"]:
                raise _apply.Refused("予想の無い行(%s)の話者を選んでください" % rid, 400, "bad_request")
        rows.append(one)
    doc = "%s:%s" % (KIND, t.get("lines"))
    learn = [dict(lr, row=r["id"], start=r["start"], end=r["end"]) for r in rows if r["speaker"] and r["speaker"] != OTHER_PERSON and not r.get("timeGuess")
             for lr in [voice_mod.clip_learn_of(r["speaker"], r["start"], r["end"])] if lr]
    out = {"lines": t.get("lines"), "piece": t.get("piece"), "video": t.get("videoId"), "who": card.get("who"), "at": card.get("at"), "part": card.get("part"),
           "from": card.get("from") or "", "scene": card.get("scene") or "", "cuts0": cuts0, "cuts": [a for _i, a, _b, _r in segs],
           "rows": rows, "doc": doc, "learn": learn}
    if ans.get("voiceNoRow"):
        out["voiceNoRow"] = True
    if learn:
        try:
            out["relearn"] = voice_mod._maybe_relearn(ctx, extra=[dict(lr, doc=doc) for lr in learn])
        except Exception as e:   # 覚え直しが始められなくても答えは済んだまま(次の答えでまた数える)
            _txbase.log.warning("確かめる: かけらの声の覚え直しを始められませんでした: %s %s", e.__class__.__name__, str(e)[:200])
    return out


def _revert_lines(ctx, row):
    return {"lines": (row.get("applied") or {}).get("lines")}


sources.register(KIND, SOURCE, voice_lines)
voice_mod.register_clip(KIND, lambda ctx, key: clip_path(getattr(ctx, "app_dir", "") or "", key))
_apply.register(KIND, SOURCE, _apply_lines, _revert_lines, check_answer, max_bytes=MAX_ANSWER_BYTES)
