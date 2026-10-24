"""「確かめる」の誰の声のカードの出どころ voice:solo(10-23。ユーザーが自分の声の答えで声を覚えさせるため)。

ホームの道は話者を判別しない(決定 3-47 Q7)ので、判別の記録から作る voice:diar は判別した文書にしか出ない。こちらは **ソロ配信の文書** の行から出す:
  ソロの見分け  名簿の配信の文脈(① roster.stream_context = チャンネル名・コラボ相手・話者の名前・題名)で出る人がちょうど 1 人・
               題名にコラボの印(COLLAB_RE)が無い・行の話者が 2 人以上いない・名簿のほかの人の名前の話者がいない。評価用は View.docs が外す。
               判別の記録の行がある文書は voice:diar が出すので出さない(同じ行を 2 度聞かない)
  行の選び方    覚える材料の決まり(human/check/voice の _learn_of と同じ = 1 秒以上・混ざりの印・音のメモ overlap/bgm/unclear が無い・
               字幕に出さない行とゲームの音の話者でない)に合う行。1 本の文書から PER_DOC 行まで・文書を順に 1 行ずつ回して、いろいろな配信から取る
  量            ソロの文書の多い人から MAX_PEOPLE 人。1 人ぶんは「覚えた秒(登録簿の sec)+ 名前で答えた行の秒 + まだ答えていないカードの秒」が
               設定 check.voiceRelearnSec × MARGIN に届くまで(MAX_PER_PERSON 枚まで)。覚え終われば(登録簿の sec が届けば)その人のカードは出ない。
               混ざり・その他・別の人で答えた行は数えないので、足りない分だけ次の行が出る
答えの形・反映・覚え直しは voice:diar と同じ(human/check/voice。予想 = 配信者・選択肢 = 配信者 + ほかの対象の人 + その他 + 混ざり。
分からないときは画面の [飛ばす])。カードは voice:diar より先に並ぶ(`_order` の頭 -1)。
古い版の文字起こしの文書(① records.output_old)は後回し: 1 人ぶんの枠は今の版の文書の行から埋め、カードの並びも同じ回りでは今の版が先
(古い版は夜の作り直し app/check/refresh で今の版になる)。
"""
import os
import re

from human.check import voice as voice_mod
from human.proof import speakers as _speakers
from pipeline.transcribe import records, roster
from ytt import schemas as _yschemas, studiodata as _studiodata, txbase as _txbase
from ytt.textutil import person_key as _person_key
from . import sources   # 同じ app/check の兄弟(register・_doc_card・_rows・View を読む)

SOURCE = "solo"
MAX_PEOPLE = 10          # 対象の人数(ソロの文書の多い順)
MAX_PER_PERSON = 15      # 1 人ぶんのカードの上限
PER_DOC = 3              # 1 本の文書から出す行の上限
MARGIN = 1.5             # 覚え直す秒(check.voiceRelearnSec)に掛ける余裕(覚えるジョブが重心を作れる量に、少し多めに)
MAX_ROW_SEC = 12.0       # 長すぎる行は聞くのが重いので出さない
GOOD_SEC = 4.0           # この長さに近い行を先に(短すぎず・長すぎず)
COLLAB_RE = re.compile(r"コラボ|collab|\bwith\b|[×✕✖]|凸|ゲスト|guest|対談|参加型|合同|オフ会|みんなで|\bfeat|\bft\.", re.I)   # みんなで = 10-24 に足した(「ホロドリみんなで遊ぼ!」)


def _titles(doc):
    """ソロの見分けに使う題名の文字(切り抜きの元の配信の題名・スタジオの配信の題名・文書の題名・元の名前・動画の入ったフォルダ)"""
    clip = doc.get("clip") if isinstance(doc.get("clip"), dict) else {}
    src = clip.get("source") if isinstance(clip.get("source"), dict) else {}
    info = None
    if src.get("videoId"):
        try:
            info = _studiodata.studio_stream(src.get("videoId"))
        except Exception:   # スタジオの情報が読めなくても、ほかの題名で見る
            info = None
    path = str(doc.get("sourcePath") or "")
    return [str(t or "") for t in (src.get("title"), (info or {}).get("title"), doc.get("title"), doc.get("sourceName"),
                                    os.path.basename(os.path.dirname(path)) if path else "")]


BLOCK_RE = re.compile(r"【([^】]{1,80})】")


def _group_names(r):
    """名簿のグループ・ユニット・番組の名前(照らし合わせる形。ユニットの組 units の名前と、ほかの組の見出しの括弧の前)"""
    out = set()
    for g in r.get("groups") or ():
        names = g.get("names") if g.get("id") == "units" else [re.sub(r"[(（].*$", "", str(g.get("label") or ""))]
        out.update(roster.fold(n) for n in names if len(roster.fold(n)) >= 3)
    return out


def _group_block(title, r):
    """題名の【】の中に名簿のグループの名前があり、メンバーの名前が無い = グループの配信(10-24: 「【アソビ★まわり隊!】クイズ!」がソロに混ざった)。
    【宙科そぴあ/ホロライブ/アソビ★まわり隊!】のような所属の札はメンバーの名前があるので当たらない"""
    groups = _group_names(r)
    for blk in BLOCK_RE.findall(str(title or "")):
        f = roster.fold(blk)
        if any(g in f for g in groups) and not roster.find_in_text(blk, r):
            return True
    return False


def solo_person(doc):
    """ソロ配信と見た文書の配信者の名前か None(見分けの決まりは先頭の説明)"""
    if roster.ROSTER is None:   # 名簿が決まっていない(編集を取り込んでいない入口)= 見分けない
        return None
    try:
        ctx = roster.stream_context(doc)
    except Exception:
        return None
    mem = [m["name"] for m in ctx.get("members") or ()]
    titles = _titles(doc)
    if len(mem) != 1 or any(COLLAB_RE.search(t) for t in titles):
        return None
    who = mem[0]
    r = roster.load(roster.ROSTER)
    if any(_group_block(t, r) for t in titles):
        return None
    for s in doc.get("speakers") or ():
        if isinstance(s, dict) and not _yschemas.other_speaker(s):
            hit = roster.match_name(str(s.get("name") or ""), r)
            if hit and hit != who:
                return None   # 名簿のほかの人の名前の話者がいる = コラボ
    used = {g.get("speaker") for g in sources._rows(doc) if g.get("speaker") and g.get("speaker") != _yschemas.OTHER_SPK_ID}
    return who if len(used) <= 1 else None


def _row_ok(g):
    """覚える材料になりうる行か(human/check/voice の _learn_of と同じ決まり + 字幕に出さない行・ゲームの音の話者でない・長すぎない)"""
    if _yschemas.no_sub_row(g) or g.get("speaker") == _yschemas.OTHER_SPK_ID or not str(g.get("text") or "").strip():
        return False
    a, b = sources._num(g.get("start")), sources._num(g.get("end"))
    if b - a < voice_mod.MIN_LEARN_SEC or b - a > MAX_ROW_SEC or _yschemas.has_flag(g.get("flag"), _txbase.MIXED_FLAG):
        return False
    tags = g.get("tags") if isinstance(g.get("tags"), list) else []
    return not any(t in tags for t in _speakers.VOICE_LEARN_TAGS)


def _options(doc, who, others):
    """配信者(文書にその名前の話者がいればその id・いなければ name:)→ ほかの対象の人(name:)→ その他 → 混ざり。-> (選択肢, 予想)"""
    sid = next((str(s["id"]) for s in doc.get("speakers") or () if isinstance(s, dict) and s.get("id") and not _yschemas.other_speaker(s)
                and _person_key(s.get("name")) == _person_key(who)), None)
    me = {"id": sid or voice_mod.NAME_PREFIX + who, "name": who, "voice": False}
    opts = [me] + [{"id": voice_mod.NAME_PREFIX + n, "name": n, "voice": False} for n in others if n != who][:voice_mod.MAX_NAMED - 1]
    return opts + [{"id": voice_mod.OTHER, "name": "その他"}, {"id": voice_mod.MIXED, "name": "混ざり"}], {"id": me["id"], "name": who}


def voice_solo(view):
    by_person = {}
    for tid, path, doc in view.docs():
        latest = view.diar(tid, path)
        if isinstance(latest, dict) and isinstance(latest.get("rows"), dict) and latest["rows"]:
            continue   # voice:diar が出す
        src = str(doc.get("sourcePath") or "")
        if not src or not os.path.isfile(src):
            continue   # 元の動画が無い文書は聞けないので出さない(10-24: 片付け・前の入れ替えで消えた動画のカードが 120 枚中 120 枚で再生できなかった)
        who = solo_person(doc)
        if who:
            by_person.setdefault(who, []).append((tid, doc))
    people = sorted(by_person, key=lambda n: (-len(by_person[n]), n))[:MAX_PEOPLE]
    answered = {}   # (文書, 行) -> 答えの記録の applied(どの出どころの答えでも)
    for r in view.answered("voice"):
        a = r.get("applied") or {}
        answered[(str(a.get("doc") or ""), str(a.get("row") or ""))] = a
    need = voice_mod._relearn_sec() * MARGIN
    cache, out = {}, []
    for rank, who in enumerate(people):
        docs = sorted(by_person[who], key=lambda x: records.output_old(x[1]))   # 今の版の文字起こしの文書から(古い版は夜の作り直し app/check/refresh を待つ)
        reg = voice_mod.registry(voice_mod.doc_embedding(docs[0][1]), cache)
        mine = next((v for n, v in reg.items() if _person_key(n) == _person_key(who)), {}) or {}
        got = sources._num(mine.get("sec"))
        learned = {(str(x.get("doc")), str(r)) for x in mine.get("learnedFrom") or () if isinstance(x, dict) for r in x.get("rows") or ()}
        picks = []   # 文書ごとの行(GOOD_SEC に近い順)
        for tid, doc in docs:
            rows = sorted((g for g in sources._rows(doc) if _row_ok(g)),
                          key=lambda g: (abs(sources._num(g.get("end")) - sources._num(g.get("start")) - GOOD_SEC), sources._num(g.get("start"))))
            picks.append((tid, doc, rows[:PER_DOC]))
        n = 0
        for i in range(PER_DOC):   # 文書を順に 1 行ずつ回す(いろいろな配信から)
            for tid, doc, rows in picks:
                if got >= need or n >= MAX_PER_PERSON:
                    break
                if i >= len(rows) or (tid, rows[i]["id"]) in learned:
                    continue
                g = rows[i]
                sec = sources._num(g.get("end")) - sources._num(g.get("start"))
                a = answered.get((tid, g["id"]))
                if a is not None:   # 答えた行: その人の名前で覚える材料になった分だけ数える(カードは出さない = 答えた物は並びが外す)
                    lr = a.get("learn") if isinstance(a.get("learn"), dict) else {}
                    if _person_key(lr.get("name")) == _person_key(who):
                        got += sources._num(lr.get("sec"))
                    continue
                opts, guess = _options(doc, who, people)
                out.append(sources._doc_card(view, "voice", SOURCE, tid, doc, g, 0.3, {
                    "guess": guess, "options": opts, "note": SOURCE,
                    "_order": [-1, rank, i, int(records.output_old(doc)), -sources._num(doc.get("updatedAt")), sources._num(g.get("start"))]}, tight=True))
                got += sec
                n += 1
    return out


sources.register("voice", SOURCE, voice_solo)
