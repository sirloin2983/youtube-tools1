"""「確かめる」のコラボの話者のカード speaker:collab(11-01。ユーザー「確かめる物がないから自分が確認するから、確かめるのカードにしてほしい」・
「ただ分けるんじゃなくて、ボタンも適切にして」・11-01 夜に形を決め直した)。誰の声のカード(501 枚)とは別の種類・別の描き方(cards/speaker.js)。

カード 1 枚 = コラボの配信の 10 秒の区間。話している人を全員選ぶ(何人でも・順番は聞かない)= 話者分離の「区間の中に何人いるか」を測る正解
(名前の答えは、あとの時刻の確かめと名前を当てる段の正解にも残す)。区間は研究が、話者分離と関係の無い声の有無の検出(silero-vad)だけで選び、
作業データの <app>/check/speaker-collab/ に置く(C:\\dev\\speech-cpp\\work\\nemodiar\\make_segments.py)。道具の出力は選び方にもカードにも入れない。
  一覧   <app>/check/speaker-collab.json = {"cards": [{key, video, title, sec, people: [その配信に出る人…]}]}
         (11-01 の行の単位の 100 枚 = voice-collab.json は .off に名前を変えて外した。このモジュールはもう読まない)
  ボタン その配信に出る人の全員(名簿の順 = 配信者を先頭にしない・配信ごとに固定。数字キーで選ぶ / 外す)・その他の人(メンバー以外の声。X)。
         候補にいない人は「ほかの人を選ぶ」の欄(名簿の全員)で足す。声なし(O)。分からない(W)は殻のボタン。**道具の予想は出さない**
  答え   {"names": [選んだ名前…]}(1 人以上。その他の人も 1 人)か {"choice": "other"}(声なし)。文書が無いので実物は書き換えない・**声も覚えない**
         (11-02: 誰の声と 1 つの「話者」カード cards/speaker.js にまとめた。名前の代わりに札 誰か分からないメンバー・ゲームの声も選べ、
         "bgm": true(BGM が大きい)・"alt": true(声色が違う)を足せる。「メンバー以外の人」の札はこの種類では OTHER_PERSON の名前で送る = 前の答えと同じ。
         カードには測る専用の札 measureOnly(画面に出さない))
         (試す専用の正解 = 声の登録簿に入れない)。答えの記録の applied = {collab: 区間の key, video, names}。採点は研究の側(score_segments.py)。Z は記録だけ戻す
  一覧のファイルはこの PC の作業データにだけ置く(配る zip には入らない = 友人の PC では出ない)
"""
import os
import re

from flow import voicematerial as _vm
from human.check import apply as _apply, voice as voice_mod
from ytt import fsio
from ytt.textutil import person_key as _person_key
from . import lineup, sources

KIND, SOURCE = "speaker", "collab"   # 種類 speaker(画面の札「コラボの話者」・描き方は cards/speaker.js)
NAME, DIR_NAME = "speaker-collab.json", "speaker-collab"   # 10 秒の区間(行の単位の voice-collab.json は外した)
OTHER_PERSON = "その他の人"   # メンバー以外の声(1 人と数える)
OTHER = voice_mod.OTHER        # 声なし
MAX_PEOPLE, MAX_NAMES = 6, 8
KEY_RE = re.compile(r"^[a-z0-9]{1,16}\Z")
VIDEO_RE = re.compile(r"^[A-Za-z0-9_-]{11}\Z")
MAX_BYTES = 4 * 1024 * 1024


def load(app_dir):
    """一覧 -> [カード]。無い・読めなければ []。形の違うカードは飛ばす"""
    d = fsio.read_json_or(os.path.join(app_dir, "check", NAME), {}, max_bytes=MAX_BYTES, kind=dict) if app_dir else {}
    cards = []
    for c in d.get("cards") or ():
        if not isinstance(c, dict) or not KEY_RE.match(str(c.get("key") or "")) or not VIDEO_RE.match(str(c.get("video") or "")):
            continue
        people = list(dict.fromkeys(p.strip() for p in c.get("people") or () if isinstance(p, str) and p.strip()))[:MAX_PEOPLE]
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


def ordered(people, members):
    """出る人を名簿の順に(名簿に無い人は後ろ・元の順)= 配信者を先頭にしない・同じ配信のカードはいつも同じ並び"""
    rank = {_person_key(n): i for i, n in enumerate(members)}
    return sorted(people, key=lambda n: (rank.get(_person_key(n), len(rank)), people.index(n)))


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
        names = ordered([n for n in c["people"] if n != OTHER_PERSON], members)
        shown = {_person_key(x) for x in names}
        sec = float(c.get("sec") or 0) or None
        out.append({"id": lineup.card_id(KIND, SOURCE, c["video"], c["key"]), "kind": KIND, "source": SOURCE,
                    "case": {"id": c["video"], "title": str(c.get("title") or "")[:120]},
                    "target": {"videoId": c["video"], "collab": c["key"], "docId": None, "row": None},
                    "media": {"url": "api/check/voicecollab?key=%s" % c["key"], "start": 0.0, "end": sec, "pad": 0.0, "padEnd": 0.0},
                    "text": "", "people": names,
                    "pick": [n for n in dict.fromkeys(members) if _person_key(n) not in shown], "otherPerson": OTHER_PERSON,
                    "score": None, "note": "", "cast": names, "measureOnly": True,
                    "_order": [0]})   # 並びは誰の声のカードの中でランダム(lineup.SHUFFLE_KINDS。11-02 ユーザー「後出る順番らんだむにして」)
    return out


def check_answer(ans):
    """答えを整える -> {"names": [名前…]} か {"choice": "other"}。違えば ValueError(400)"""
    if not isinstance(ans, dict):
        raise ValueError("答えは {names} か {choice} の形で送ってください")
    if set(ans) == {"choice"} and ans["choice"] == OTHER:
        return {"choice": OTHER}
    if "names" in ans and set(ans) <= {"names", "bgm", "alt"} and isinstance(ans["names"], list) and 1 <= len(ans["names"]) <= MAX_NAMES:
        if not all(isinstance(n, str) for n in ans["names"]):
            raise ValueError("名前は文字で送ってください")
        out = {"names": list(dict.fromkeys(voice_mod._check_answer({"name": n})["name"] for n in ans["names"]))}
        for k in ("bgm", "alt"):
            if k in ans:
                if ans[k] is not True:
                    raise ValueError("%s は true だけ送れます" % k)
                out[k] = True
        return out
    raise ValueError("答えは {names: [名前…]}(1〜%d 人)か {choice: \"other\"} の形で送ってください" % MAX_NAMES)


def _apply_collab(ctx, card, ans):
    """文書が無いので実物は変えない・声も覚えない。-> applied {collab, video, names}(採点用)"""
    t = card.get("target") or {}
    return {"collab": t.get("collab"), "video": t.get("videoId"), "names": list(ans.get("names") or [])}


def _revert_collab(ctx, row):
    return {"collab": (row.get("applied") or {}).get("collab")}


sources.register(KIND, SOURCE, voice_collab)
_apply.register(KIND, SOURCE, _apply_collab, _revert_collab, check_answer)
