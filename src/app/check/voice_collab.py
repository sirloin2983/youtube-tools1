"""「確かめる」のコラボの話者のカード speaker:collab(11-01。誰の声のカードと同じ形で、種類だけ別 = 501 枚の誰の声に混ざらない。ユーザー「確かめる物がないから自分が確認するから、確かめるのカードにしてほしい」・
「今の誰の声のカードをベースにしてほしい」)。

コラボの配信で、話者分離(Nemotron 3 Diarization と今の判別)の分かれ方を測る正解を集める行。文書の行ではなく、研究が
Haas の言葉と話者分離の区間から作った行の短い音(C:\\dev\\speech-cpp\\work\\nemodiar\\make_cards.py が作業データの <app>/check/voice-collab/ に置く)。
  一覧   <app>/check/voice-collab.json = {"cards": [{key, video, title, sec, people: [その配信に出る人…]}]}
         行の選び方(研究の側): 1 配信 20 行ほど・2 つの話者分離が食い違う行・声の重なる行・短い行・ふつうの行をまぜる
  ボタン その配信に出る人の名前 + その他の人 + 混ざり(2 人以上)。分からない(W)は殻のボタン。**道具の予想は出さない**(答えが寄らないように)
  答え   今の誰の声のカードと同じ形(human/check/voice._check_answer。答えの記録の kind は speaker)。文書が無いので実物は書き換えない・**声も覚えない**(試す専用の正解 =
         声の登録簿に入れない)。採点は研究の側(答えの記録の applied.collab = 行の key)。Z は記録だけ戻す
  一覧のファイルはこの PC の作業データにだけ置く(配る zip には入らない = 友人の PC では出ない)
"""
import os
import random
import re

from flow import voicematerial as _vm
from human.check import apply as _apply, voice as voice_mod
from ytt import fsio
from . import lineup, sources

KIND, SOURCE = "speaker", "collab"   # 種類 speaker(画面の札「コラボの話者」・描き方は cards/voice.js が兼ねる)
NAME, DIR_NAME = "voice-collab.json", "voice-collab"
OTHER_PERSON = "その他の人"   # 出る人の誰でもない人(名前は付けない)
MAX_PEOPLE = 4                # 名前のボタン(+ その他の人 = 数字キー 1〜5)
KEY_RE = re.compile(r"^[a-z0-9]{1,16}\Z")
VIDEO_RE = re.compile(r"^[A-Za-z0-9_-]{11}\Z")
MAX_BYTES = 4 * 1024 * 1024
NAME_PREFIX = voice_mod.NAME_PREFIX


def load(app_dir):
    """一覧 -> [カード]。無い・読めなければ []。形の違うカードは飛ばす"""
    d = fsio.read_json_or(os.path.join(app_dir, "check", NAME), {}, max_bytes=MAX_BYTES, kind=dict) if app_dir else {}
    cards = []
    for c in d.get("cards") or ():
        if not isinstance(c, dict) or not KEY_RE.match(str(c.get("key") or "")) or not VIDEO_RE.match(str(c.get("video") or "")):
            continue
        people = [p for p in c.get("people") or () if isinstance(p, str) and p.strip()][:MAX_PEOPLE]
        if not people:
            continue
        cards.append(dict(c, people=people))
    return cards


def clip_path(app_dir, key):
    """行の音のファイル(あれば)か None"""
    if not app_dir or not isinstance(key, str) or not KEY_RE.match(key):
        return None
    p = os.path.join(app_dir, "check", DIR_NAME, key + ".wav")
    return p if os.path.isfile(p) else None


def voice_collab(view):
    app_dir = getattr(view.ctx, "app_dir", "") or ""
    cards = load(app_dir)
    if not cards:
        return []
    members = _vm.roster_people()
    out = []
    for c in cards:
        if not clip_path(app_dir, c["key"]):
            continue
        names = list(dict.fromkeys(c["people"]))
        opts = [{"id": NAME_PREFIX + n, "name": n} for n in names + [OTHER_PERSON]] + [{"id": voice_mod.MIXED, "name": "混ざり"}]
        sec = float(c.get("sec") or 0) or None
        out.append({"id": lineup.card_id(KIND, SOURCE, c["video"], c["key"]), "kind": KIND, "source": SOURCE,
                    "case": {"id": c["video"], "title": str(c.get("title") or "")[:120]},
                    "target": {"videoId": c["video"], "collab": c["key"], "docId": None, "row": None},
                    "media": {"url": "api/check/voicecollab?key=%s" % c["key"], "start": 0.0, "end": sec, "pad": 0.0, "padEnd": 0.0},
                    "text": "この配信に出る人: %s" % "・".join(names),
                    "guess": None, "buttons": len(names) + 1, "learn": False,
                    "options": opts,
                    "people": [{"id": NAME_PREFIX + n, "name": n} for n in dict.fromkeys(names + list(members))],
                    "score": None, "note": SOURCE,
                    "_order": [-2, 0, random.random()]})
    return out


def _apply_collab(ctx, card, ans):
    """文書が無いので実物は変えない・声も覚えない。-> applied {collab, video}(採点用)"""
    t = card.get("target") or {}
    return {"collab": t.get("collab"), "video": t.get("videoId")}


def _revert_collab(ctx, row):
    return {"collab": (row.get("applied") or {}).get("collab")}


sources.register(KIND, SOURCE, voice_collab)
_apply.register(KIND, SOURCE, _apply_collab, _revert_collab, voice_mod._check_answer)
