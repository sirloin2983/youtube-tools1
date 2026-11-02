"""「確かめる」の行ごとの話者のカード lines:seg(11-02。ユーザー「誰の声カードでそれぞれの行に話者をあてる形にしてほしい・ついでに行の中身も調整する」)。
誰の声のカード(voice:solo・voice:measure)・コラボの話者(speaker:collab)とは別の種類・別の描き方(cards/lines.js)。

カード 1 枚 = 声の材料の配信の短いかけら(48 秒ほど)。中の行を並べ、行ごとに話者を選び(初めは道具の予想の 1 位)、文字の誤りもその場で直す
= 話者の表の正答率を測る正解(行の話者)と文字起こしの正解(直した文字)を 1 度に作る。かけらと行・予想は研究が作り、作業データに置く
(受け渡しの形は共有メモ 境目-声のカード.md。11-02 予備2 と予備1 で決めた)。
  一覧   <app>/check/speaker-lines.json = {"people": [声を覚えた全員…], "cards": [{key, video, title, who: 配信者, at: 配信の中の秒, sec, part,
         rows: [{id, start, end(かけらの頭からの秒), text, guess: [{name, score}…上から]}]}]}
  音     <app>/check/speaker-lines/<key>.wav(かけらの頭が 0 秒)
  選べる物 行ごとに 声を覚えた全員(一覧の people・配信者・予想の名前)・ほかの人(OTHER_PERSON)・声なし
  答え   {"rows": [{id, speaker?: 名前, none?: true, text?: 直した文字}]}(変えた行だけ。何も変えなければ {} = 全部の行が予想どおり・文字どおり)
         予想の無い行は話者を選ばないと答えられない(画面が止める・サーバーも 400)
  記録   applied = {lines, video, who, at, part, rows: [{id, start, end, guess, guessScore, speaker, none?, text0, text}]}(全部の行。変えなかった行は
         予想の 1 位と元の文字)。文書が無いので実物は書き換えない・**声も覚えない**(評価用は学習に使わない)。採点は研究の側。Z は記録だけ戻す
  一覧のファイルはこの PC の作業データにだけ置く(配る zip には入らない = 友人の PC では出ない)
"""
import os
import random
import re

from human.check import apply as _apply, voice as voice_mod
from ytt import fsio
from . import lineup, sources

KIND, SOURCE = "lines", "seg"
NAME, DIR_NAME = "speaker-lines.json", "speaker-lines"
OTHER_PERSON = "ほかの人"   # 声を覚えた人の誰でもない人の声
MAX_ROWS, MAX_TEXT, MAX_SEC, MAX_GUESS, MAX_PEOPLE = 40, 200, 60.0, 3, 200
MAX_ANSWER_BYTES = 32 * 1024   # 40 行の文字を直しても入る大きさ
KEY_RE = re.compile(r"^[a-z0-9]{1,16}\Z")
VIDEO_RE = re.compile(r"^[A-Za-z0-9_-]{11}\Z")
ROW_RE = re.compile(r"^[A-Za-z0-9_-]{1,16}\Z")
MAX_BYTES = 8 * 1024 * 1024


def _num(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


def _name(x):
    return x.strip() if isinstance(x, str) and x.strip() and len(x.strip()) <= 30 else None


def _rows(c, sec):
    out, seen = [], set()
    for r in c.get("rows") or ():
        if not isinstance(r, dict) or not ROW_RE.match(str(r.get("id") or "")) or r["id"] in seen:
            return None
        a, b = _num(r.get("start")), _num(r.get("end"))
        if a is None or b is None or not 0 <= a < b <= sec + 0.05 or not isinstance(r.get("text"), str):
            return None
        g = [{"name": _name(x.get("name")), "score": _num(x.get("score"))} for x in r.get("guess") or () if isinstance(x, dict) and _name(x.get("name"))]
        seen.add(r["id"])
        out.append({"id": r["id"], "start": round(a, 3), "end": round(min(b, sec), 3), "text": r["text"][:MAX_TEXT], "guess": g[:MAX_GUESS]})
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
            cards.append(dict(c, sec=sec, rows=rows, who=_name(c["who"])))
    people = [p for p in (_name(x) for x in (d.get("people") or ())[:MAX_PEOPLE]) if p]
    return list(dict.fromkeys(people)), cards


def clip_path(app_dir, key):
    """かけらの音のファイル(あれば)か None"""
    if not app_dir or not isinstance(key, str) or not KEY_RE.match(key):
        return None
    p = os.path.join(app_dir, "check", DIR_NAME, key + ".wav")
    return p if os.path.isfile(p) else None


def voice_lines(view):
    app_dir = getattr(view.ctx, "app_dir", "") or ""
    people, cards = load(app_dir)
    out = []
    for c in cards:
        if not clip_path(app_dir, c["key"]):
            continue
        names = list(dict.fromkeys([c["who"]] + people + [g["name"] for r in c["rows"] for g in r["guess"]]))
        out.append({"id": lineup.card_id(KIND, SOURCE, c["video"], c["key"]), "kind": KIND, "source": SOURCE,
                    "case": {"id": c["video"], "title": str(c.get("title") or "")[:120]},
                    "target": {"videoId": c["video"], "lines": c["key"], "docId": None, "row": None},
                    "media": {"url": "api/check/voicelines?key=%s" % c["key"], "start": 0.0, "end": c["sec"], "pad": 0.0, "padEnd": 0.0},
                    "text": "", "who": c["who"], "at": _num(c.get("at")), "part": str(c.get("part") or "")[:8],
                    "rows": [dict(r, guess=(r["guess"][0]["name"] if r["guess"] else None), score=(r["guess"][0]["score"] if r["guess"] else None),
                                  second=(r["guess"][1] if len(r["guess"]) > 1 else None)) for r in c["rows"]],
                    "people": names, "otherPerson": OTHER_PERSON, "guess": None, "score": None, "note": "", "cast": [c["who"]], "measureOnly": True,
                    "_order": [0, c["video"], random.random()]})   # 配信ごとにまとめて出す(同じ人の声が続く = 迷わない)
    return out


def check_answer(ans):
    """答えを整える -> {"rows": [{id, speaker? | none?, text?}]}(空なら {})。違えば ValueError(400)"""
    if not isinstance(ans, dict) or not set(ans) <= {"rows"}:
        raise ValueError("答えは {rows: [{id, speaker?, none?, text?}]} の形で送ってください")
    rows = ans.get("rows", [])
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise ValueError("rows は %d 行までの並びです" % MAX_ROWS)
    out, seen = [], set()
    for r in rows:
        if not isinstance(r, dict) or not set(r) <= {"id", "speaker", "none", "text"} or not ROW_RE.match(str(r.get("id") or "")) or r["id"] in seen:
            raise ValueError("行の答えの形が正しくありません")
        if "speaker" in r and "none" in r:
            raise ValueError("話者と声なしは一緒に送れません")
        one = {"id": r["id"]}
        if "speaker" in r:
            one["speaker"] = voice_mod._check_answer({"name": r["speaker"]})["name"]
        if "none" in r:
            if r["none"] is not True:
                raise ValueError("none は true だけ送れます")
            one["none"] = True
        if "text" in r:
            if not isinstance(r["text"], str) or len(r["text"]) > MAX_TEXT:
                raise ValueError("文字は %d 字までです" % MAX_TEXT)
            one["text"] = r["text"].strip()
        seen.add(r["id"])
        out.append(one)
    return {"rows": out} if out else {}


def _apply_lines(ctx, card, ans):
    """文書が無いので実物は変えない・声も覚えない。-> applied(全部の行の 予想・答えた話者・元の文字・直した文字)。予想の無い行に答えが無ければ ValueError"""
    t, got = card.get("target") or {}, {r["id"]: r for r in ans.get("rows") or ()}
    rows = []
    for r in card.get("rows") or ():
        a = got.get(r["id"], {})
        one = {"id": r["id"], "start": r["start"], "end": r["end"], "guess": r.get("guess"), "guessScore": r.get("score"),
               "speaker": None if a.get("none") else a.get("speaker", r.get("guess")), "text0": r["text"], "text": a.get("text", r["text"])}
        if a.get("none"):
            one["none"] = True
        elif not one["speaker"]:
            raise _apply.Refused("予想の無い行(%s)の話者を選んでください" % r["id"], 400, "bad_request")
        rows.append(one)
    return {"lines": t.get("lines"), "video": t.get("videoId"), "who": card.get("who"), "at": card.get("at"), "part": card.get("part"), "rows": rows}


def _revert_lines(ctx, row):
    return {"lines": (row.get("applied") or {}).get("lines")}


sources.register(KIND, SOURCE, voice_lines)
_apply.register(KIND, SOURCE, _apply_lines, _revert_lines, check_answer, max_bytes=MAX_ANSWER_BYTES)
