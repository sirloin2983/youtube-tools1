"""「確かめる」の誰の声のカードの出どころ voice:measure(11-01。ユーザー「人が答える物は確かめるに作る」・話者の物差しの手順 ①)。

覚えた声から「誰の声か」を当てられるかを測る行。文書の行ではなく、ショートの元の配信(ソロ)の音から研究が切り出した短い音
(C:\\dev\\overlap-research\\tools\\speaker_listen_build.py が作業データの <app>/check/voice-measure/ に置く)。
  一覧   <app>/check/voice-measure.json = {"people": [先に出す人…], "cards": [{key, who: 配信者, video, title, sec, guess: [{name, score}×2]}]}
         行の選び方(研究の側で決めた): 判別で 2 人目 5% 以下の配信だけ・1 人 3 配信以上・1 配信 10 行まで・1 秒以上・BGM の弱い順
  予想   道具の予想 = その行の配信を覚える側に入れずに、声を覚えた全員から当てた 1 位と 2 位(guess)。カードの予想(Enter)は 1 位・
         2 位は文に出す。答えの記録の guess に両方残る(正答率の数え = 研究の側)
  量     測る分の枠(保管庫 plan/話者の物差し-1101.md の 7 章の案 1): 配信者ごとに「この人」と答えた行が TARGET_ROWS 行・TARGET_STREAMS 配信に
         届くまで出す。並びは voice:solo より先(_order の頭 -2)・一覧の people の人が先・その中は人をまたいでランダムに混ぜる
  答え   今の誰の声のカードと同じ形(human/check/voice._check_answer)。文書が無いので実物は書き換えない・声も覚えない(測る行を覚える材料に
         入れない = 評価用は学習に使わない決まりと同じ)。Z は記録だけ戻す
"""
import os
import random
import re

from flow import voicematerial as _vm
from human.check import apply as _apply, voice as voice_mod
from ytt import fsio
from ytt.textutil import person_key as _person_key
from . import lineup, sources

SOURCE = "measure"
NAME, DIR_NAME = "voice-measure.json", "voice-measure"
TARGET_ROWS, TARGET_STREAMS = 30, 3
KEY_RE = re.compile(r"^[a-z0-9]{1,16}\Z")
VIDEO_RE = re.compile(r"^[A-Za-z0-9_-]{11}\Z")
MAX_BYTES = 4 * 1024 * 1024
NAME_PREFIX = voice_mod.NAME_PREFIX


def _app_dir(view):
    return getattr(view.ctx, "app_dir", "") or ""


def load(app_dir):
    """一覧 -> (先に出す人, [カード])。無い・読めなければ ([], [])。形の違うカードは飛ばす"""
    d = fsio.read_json_or(os.path.join(app_dir, "check", NAME), {}, max_bytes=MAX_BYTES, kind=dict) if app_dir else {}
    cards = []
    for c in d.get("cards") or ():
        if not isinstance(c, dict) or not KEY_RE.match(str(c.get("key") or "")) or not VIDEO_RE.match(str(c.get("video") or "")):
            continue
        g = [x for x in c.get("guess") or () if isinstance(x, dict) and isinstance(x.get("name"), str) and x["name"]]
        if not isinstance(c.get("who"), str) or not c["who"] or len(g) < 2:
            continue
        cards.append(dict(c, guess=g[:2]))
    return [p for p in d.get("people") or () if isinstance(p, str)], cards


def clip_path(app_dir, key):
    """行の音のファイル(あれば)か None"""
    if not app_dir or not isinstance(key, str) or not KEY_RE.match(key):
        return None
    p = os.path.join(app_dir, "check", DIR_NAME, key + ".wav")
    return p if os.path.isfile(p) else None


def _reached(view):
    """{配信者の person_key}: 「この人」と答えた行が目標に届いた人(BGM 大・別の声もの答えは数えない)"""
    rows, streams = {}, {}
    for r in view.answered("voice"):
        if r.get("source") != SOURCE:
            continue
        a, who = r.get("answer") or {}, str((r.get("applied") or {}).get("who") or "")
        if not who or a.get("bgm") or a.get("others") or _person_key(a.get("name")) != _person_key(who):
            continue
        k = _person_key(who)
        rows[k] = rows.get(k, 0) + 1
        streams.setdefault(k, set()).add((r.get("target") or {}).get("videoId"))
    return {k for k, n in rows.items() if n >= TARGET_ROWS and len(streams[k]) >= TARGET_STREAMS}


def voice_measure(view):
    app_dir = _app_dir(view)
    first, cards = load(app_dir)
    if not cards:
        return []
    done, members = _reached(view), _vm.roster_people()
    lead = {_person_key(p) for p in first}
    out = []
    for c in cards:
        if _person_key(c["who"]) in done or not clip_path(app_dir, c["key"]):
            continue
        g1, g2 = c["guess"]
        names = list(dict.fromkeys([g1["name"], c["who"], g2["name"]]))
        opts = [{"id": NAME_PREFIX + n, "name": n} for n in names] + [{"id": voice_mod.OTHER, "name": "その他"}, {"id": voice_mod.MIXED, "name": "混ざり"}]
        sec = float(c.get("sec") or 0) or None
        out.append({"id": lineup.card_id("voice", SOURCE, c["video"], c["key"]), "kind": "voice", "source": SOURCE,
                    "case": {"id": c["video"], "title": str(c.get("title") or "")[:120]},
                    "target": {"videoId": c["video"], "measure": c["key"], "docId": None, "row": None},
                    "media": {"url": "api/check/voicemeasure?key=%s" % c["key"], "start": 0.0, "end": sec, "pad": 0.0, "padEnd": 0.0},
                    "text": "配信者: %s ・ 道具の予想 1 位 %s(%.2f)・2 位 %s(%.2f)" % (c["who"], g1["name"], g1.get("score") or 0, g2["name"], g2.get("score") or 0),
                    "guess": {"id": NAME_PREFIX + g1["name"], "name": g1["name"], "score": g1.get("score"), "second": dict(g2)},
                    "options": voice_mod.buttons(opts, [NAME_PREFIX + g1["name"], NAME_PREFIX + c["who"]]),
                    "people": [{"id": NAME_PREFIX + n, "name": n} for n in dict.fromkeys(names + list(members))],
                    "score": None, "note": SOURCE, "who": c["who"],
                    "_order": [-2, 0 if _person_key(c["who"]) in lead else 1, random.random()]})
    return out


def _apply_measure(ctx, card, ans):
    """文書が無いので実物は変えない。-> applied {measure, who, video}(正答率の数えと「この人」の数え用)"""
    t = card.get("target") or {}
    return {"measure": t.get("measure"), "who": card.get("who"), "video": t.get("videoId")}


def _revert_measure(ctx, row):
    return {"measure": (row.get("applied") or {}).get("measure")}


sources.register("voice", SOURCE, voice_measure)
_apply.register("voice", SOURCE, _apply_measure, _revert_measure, voice_mod._check_answer)
