"""「確かめる」の誰の声のカードの出どころ voice:solo(10-23。ユーザーが自分の声の答えで声を覚えさせるため)。

ホームの道は話者を判別しない(決定 3-47 Q7)ので、判別の記録から作る voice:diar は判別した文書にしか出ない。こちらは **ソロ配信の文書** の行から出す:
  ソロの見分け  名簿の配信の文脈(① roster.stream_context = チャンネル名・コラボ相手・話者の名前・題名)で出る人がちょうど 1 人・
               題名にコラボの印(COLLAB_RE)が無い・行の話者が 2 人以上いない・名簿のほかの人の名前の話者がいない。評価用は View.docs が外す。
               判別の記録の行がある文書は voice:diar が出すので出さない(同じ行を 2 度聞かない)
  行の選び方    覚える材料の決まり(human/check/voice の _learn_of と同じ = 1 秒以上・混ざりの印・音のメモ overlap/bgm/unclear が無い・
               字幕に出さない行とゲームの音の話者でない)に合う行。1 本の文書から PER_DOC 行まで・文書を順に 1 行ずつ回して、いろいろな配信から取る
  量            材料の少ない人から MAX_PEOPLE 人。まだ覚えていない人(登録簿の sec が設定 check.voiceRelearnSec × MARGIN に届かない人)は、
               「覚えた秒 + 名前で答えた行の秒 + まだ答えていないカードの秒」がそれに届くまで(MAX_PER_PERSON 枚まで)。
               混ざり・その他・別の人で答えた行は数えないので、足りない分だけ次の行が出る。
               覚えた人も止めない(10-24 夜の決め直し = 配信ごとのマイク・部屋の違いも平均に入れる): LEARNED_CARDS × 届く秒 / 覚えた秒 枚
               (材料が多いほど少ない。端数はくじ)。どの人も、まだ材料に入っていない配信(文書)の行が先。
               覚え直しは新しい行だけを前の声に混ぜる(flow/diar.merge_voice・前の重みは 1 時間まで)ので、材料が増えても 1 回の重さは変わらない = 上限は置かない
答えの形・反映・覚え直しは voice:diar と同じ(human/check/voice。予想 = 配信者・選択肢 = 配信者 + ほかの対象の人 + その他 + 混ざり。
名前のボタンは配信者から BUTTONS 人・ほかの人は「メンバーを選ぶ」の欄 = people(名簿の全員・打った名前も)。分からないときは画面の [分からない])。カードは voice:diar より先に並ぶ(`_order` の頭 -1)。人をまたいでランダムに混ぜる
(同じ人が続くと聞き分けにならない。集め直すたびに混ざる)。
古い版の文字起こしの文書(① records.output_old)は後回し: 1 人ぶんの枠は今の版の文書の行から埋め、カードの並びも同じ回りでは今の版が先
(古い版は夜の作り直し app/check/refresh で今の版になる)。
行の音(10-24 夜。ユーザー「誰の声をメンバー全員分」): カードに出す行の音は、元の動画があるうちに短く切り出して作業データに残す
(human/proof/voiceclips。clip_targets が選んだ行を入口の voice_clips_tick が切り出す)。音があるカードはその音で再生するので、
元の動画が片付いた文書の行もカードになる。人の並びは、まだ覚えていない人(登録簿の秒が足りない人)が先・全員(MAX_PEOPLE まで)。
歌は外す(10-24 夜。ユーザー「歌のシーンはどうする?」= 歌の声は話し声と響きが違い、伴奏も入る): 題名に歌の印(SONG_RE)がある配信の文書と、
文字に音符(♪♫♬♩)がある行。外した数は LAST_SKIPS(入口の voice_clips_tick が記録に 1 行)。友人の PC から受け取る声の材料も同じ決まり(song_title・song_row)。
"""
import os
import random
import time

from flow import voicematerial as _vm
from human.check import voice as voice_mod
from human.proof import voiceclips as _voiceclips
from pipeline.transcribe import records
from ytt import schemas as _yschemas
from ytt.textutil import person_key as _person_key
from . import sources, voicefill   # 同じ app/check の兄弟(register・_doc_card・_rows・View を読む)

SOURCE = "solo"
MAX_PEOPLE = 80          # 対象の人数(まだ覚えていない人が先・ソロの文書の多い順。10-24 夜に 10 → 80 = ホロライブのメンバー全員)
MAX_PER_PERSON = 15      # 1 人ぶんのカードの上限
LEARNED_CARDS = 3        # 覚えた人(届く秒ちょうど)のカードの数。覚えた秒が 2 倍なら半分(端数はくじ)
PER_DOC = 3              # 1 本の文書から出す行の上限
MARGIN = 1.5             # 覚え直す秒(check.voiceRelearnSec)に掛ける余裕(覚えるジョブが重心を作れる量に、少し多めに)
MAX_ROW_SEC = _vm.MAX_ROW_SEC
GOOD_SEC = _vm.GOOD_SEC
SONG_RE, NOTE_RE, COLLAB_RE = _vm.SONG_RE, _vm.NOTE_RE, _vm.COLLAB_RE   # 選び方の決まりは ② flow/voicematerial(友人の PC と同じ)
LAST_SKIPS = {"songDocs": 0, "songRows": 0}   # 最後の選びで歌として外した文書と行の数(記録用)
song_title, song_row, solo_person, _titles = _vm.song_title, _vm.song_row, _vm.solo_person, _vm.titles


def _options(doc, who, others):
    """配信者(文書にその名前の話者がいればその id・いなければ name:)→ ほかの対象の人(name:)→ その他 → 混ざり。-> (選択肢, 予想)"""
    sid = next((str(s["id"]) for s in doc.get("speakers") or () if isinstance(s, dict) and s.get("id") and not _yschemas.other_speaker(s)
                and _person_key(s.get("name")) == _person_key(who)), None)
    me = {"id": sid or voice_mod.NAME_PREFIX + who, "name": who, "voice": False}
    opts = [me] + [{"id": voice_mod.NAME_PREFIX + n, "name": n, "voice": False} for n in others if n != who][:voice_mod.MAX_NAMED - 1]
    return opts + [{"id": voice_mod.OTHER, "name": "その他"}, {"id": voice_mod.MIXED, "name": "混ざり"}], {"id": me["id"], "name": who}


def _playable_fn(tid, doc):
    """行を聞けるかの関数: 元の動画がある(文書ごとに 1 回だけ確かめる)か、切り出して残した音がある(voiceclips の索引を 1 回読む)。
    行ごとにファイルを確かめると、確かめるの集めが遅かった(10-25 測った: 4,400 行で 0.6 秒)"""
    if sources.has_media(doc):
        return lambda g: True
    have = set(_voiceclips.index(tid))
    return lambda g: g["id"] in have


SOLO_CACHE_SEC = 3600.0   # ソロの見分けを覚えておく秒(文書が書き換わる・名簿が変わる・この秒が過ぎたら見直す)
_solo_cache = {}          # 文書のパス -> (印, (名前か None, 歌の配信か))


def _solo_of(path, doc):
    """(ソロの配信者の名前か None, 歌の配信か)。名簿の照らし合わせが重い(10-25 測った: 185 本で 2.8 秒)ので、文書のファイルの更新時刻と大きさ・
    名簿のファイルが同じあいだは覚えた答えを使う"""
    try:
        stt = os.stat(path)
        stamp = (stt.st_mtime_ns, stt.st_size, _vm.roster_file())
    except (OSError, TypeError):
        stamp = None
    now = time.monotonic()
    hit = _solo_cache.get(path) if stamp else None
    if hit and hit[0] == stamp and now - hit[1] < SOLO_CACHE_SEC:
        return hit[2]
    who = solo_person(doc)
    got = (who, bool(who) and song_title(_titles(doc)))
    if stamp:
        if len(_solo_cache) > 20000:
            _solo_cache.clear()
        _solo_cache[path] = (stamp, now, got)
    return got


def _learned_quota(sec, need):
    """覚えた人のカードの数(LEARNED_CARDS × need / sec。端数はくじ)"""
    q = LEARNED_CARDS * need / max(sec, need)
    return int(q) + (1 if random.random() < q - int(q) else 0)


_bgm_seen = {}   # (文書, 行) -> BGM らしさか None(音がまだ無い行は次の集めで測り直さないよう None も覚える。切り出しの見回りで行の音ができたら voice_clips_tick が消す)
GOOD_BAND = (3.0, 8.0)   # 長めの行(声の特徴が取りやすい)= 先に出す(10-25: 答え 214 枚でも覚えた人が 6 人だけ・混ざりとその他が 4 割)


def _later(tid, g):
    """後ろに回す度合い(0 = 先): 長めの行(GOOD_BAND)でなければ +1・BGM・効果音らしさ(切り出した行の音の目安 voiceclips.bgm)× 2。
    並びはランダムのまま、この重みでランダムの幅を広げる = 長めで BGM の少ない行が先に出やすい"""
    sec = sources._num(g.get("end")) - sources._num(g.get("start"))
    band = 0.0 if GOOD_BAND[0] <= sec <= GOOD_BAND[1] else 1.0
    key = (tid, g["id"])
    if key not in _bgm_seen:   # 1 行 1 回だけ(索引に覚え、ここでも覚える = 集めを遅くしない)
        if len(_bgm_seen) > 50000:
            _bgm_seen.clear()
        _bgm_seen[key] = _voiceclips.bgm(tid, g["id"]) if _voiceclips.clip_path(tid, g["id"]) else None
    b = _bgm_seen[key]
    return band + 2.0 * (b or 0.0)


def _select(view):
    """カードに出す行を選ぶ(並び・量の決まりは先頭の説明)-> [(rank, 名前, 人の一覧, 文書 id, 文書, 行, i)]。聞けない行(音も動画も無い)は飛ばす"""
    by_person, skips = {}, {"songDocs": 0, "songRows": 0}
    for tid, path, doc in view.docs(need_media=False):
        latest = view.diar(tid, path)
        if isinstance(latest, dict) and isinstance(latest.get("rows"), dict) and latest["rows"]:
            continue   # voice:diar が出す
        if voicefill.eval_like(doc.get("sourcePath")):
            continue   # 評価用データの写し(学習用データに混ざっていた)は声の材料にしない
        who, song = _solo_of(path, doc)
        if who and song:
            skips["songDocs"] += 1   # 歌の配信(声を覚える材料にしない)
            continue
        if who:
            by_person.setdefault(who, []).append((tid, doc))
    answered = {}   # (文書, 行) -> 答えの記録の applied(どの出どころの答えでも)
    for r in view.answered("voice"):
        a = r.get("applied") or {}
        answered[(str(a.get("doc") or ""), str(a.get("row") or ""))] = a
    need = voice_mod._relearn_sec() * MARGIN
    cache, info = {}, {}
    for who, docs in by_person.items():
        docs = sorted(docs, key=lambda x: records.output_old(x[1]))   # 今の版の文字起こしの文書から(古い版は夜の作り直し app/check/refresh を待つ)
        reg = voice_mod.registry(voice_mod.doc_embedding(docs[0][1]), cache)
        mine = next((v for n, v in reg.items() if _person_key(n) == _person_key(who)), {}) or {}
        info[who] = (docs, sources._num(mine.get("sec")),
                     {(str(x.get("doc")), str(r)) for x in mine.get("learnedFrom") or () if isinstance(x, dict) for r in x.get("rows") or ()},
                     {str(x.get("doc")) for x in mine.get("learnedFrom") or () if isinstance(x, dict)})
    foreign = _vm.foreign_members()
    for n in [n for n in info if n in foreign]:   # EN・ID の人のカードは出さない(10-25 ユーザー「EN・ID は外す」。取った音は消さない)
        info.pop(n)
    people = sorted(info, key=lambda n: (info[n][1] >= need, info[n][1], -len(info[n][0]), n))[:MAX_PEOPLE]   # まだ覚えていない人・材料の少ない人が先
    out = []
    for rank, who in enumerate(people):
        docs, got, learned, seen = info[who]   # seen = 材料に入っている配信(登録簿の learnedFrom の文書)
        done = got >= need
        limit = _learned_quota(got, need) if done else MAX_PER_PERSON
        picks = []   # 文書ごとの行(GOOD_SEC に近い順)。まだ材料に入っていない配信が先
        for tid, doc in sorted(docs, key=lambda x: x[0] in seen):
            skips["songRows"] += sum(1 for g in sources._rows(doc) if song_row(g))
            rows = sorted(_vm.pick(doc, _playable_fn(tid, doc)), key=lambda g: _later(tid, g))   # 長めの行・BGM の少ない行が先(10-25)
            picks.append((tid, doc, rows[:PER_DOC]))
        n = 0
        for i in range(PER_DOC):   # 文書を順に 1 行ずつ回す(いろいろな配信から)
            for tid, doc, rows in picks:
                if (not done and got >= need) or n >= limit:
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
                out.append((rank, who, people, tid, doc, g, i))
                got += sec
                n += 1
    LAST_SKIPS.update(skips)
    return out


def stream_counts(view):
    """{名前: 手元の配信の材料の本数}(ソロと見た配信の文書。ショート・評価用・YouTube から取った音の文書は数えない)。voicefetch が取る人を選ぶ"""
    out = {}
    for tid, path, doc in view.docs(need_media=False):
        src = doc.get("sourcePath")
        if voicefill.eval_like(src) or voicefill.in_learn_dir(src):
            continue
        who, song = _solo_of(path, doc)
        if who and not song:
            out[who] = out.get(who, 0) + 1
    return out


def people(view):
    """誰の声の材料のある人の名前(ソロと見た文書の配信者・覚えた声の登録簿の人)。voicefetch が材料の無い人を選ぶ"""
    out = set()
    for tid, path, doc in view.docs(need_media=False):
        who, song = _solo_of(path, doc)
        if who and not song:
            out.add(who)
    for n in voice_mod.registry(voice_mod.doc_embedding({})):
        out.add(_vm.member(n) or n)
    return out


def clip_targets(view):
    """まだ切り出していない、カードに出す行 -> [(文書 id, 文書, [行…])](元の動画がある文書だけ。入口の voice_clips_tick が切り出す)"""
    by_doc = {}
    for _rank, _who, _people, tid, doc, g, _i in _select(view):
        if sources.has_media(doc) and not _voiceclips.clip_path(tid, g["id"]):
            by_doc.setdefault(tid, (doc, []))[1].append(g)
    return [(tid, doc, rows) for tid, (doc, rows) in by_doc.items()]


def voice_solo(view):
    out, members = [], _vm.roster_people()
    for rank, who, people, tid, doc, g, i in _select(view):
        opts, guess = _options(doc, who, people)
        card = sources._doc_card(view, "voice", SOURCE, tid, doc, g, 0.3, {
            "guess": guess, "options": voice_mod.buttons(opts, [guess["id"]]),
            "people": voice_mod.people_for(doc, {}, [who] + list(people) + members), "note": SOURCE,
            "_order": [-1, random.random() * (1.0 + _later(tid, g)), rank, i, int(records.output_old(doc)), -sources._num(doc.get("updatedAt")), sources._num(g.get("start"))]}, tight=True)
        clip = None if sources.has_media(doc) else _voiceclips.media(tid, g["id"], card["media"]["start"], card["media"]["end"])
        if clip:   # 元の動画が無い(片付いた・友人から届いた)ときだけ、切り出して残した行の音で再生する。動画があれば映像つきのまま(10-25 直し)
            card["media"] = dict(card["media"], **clip)
        out.append(card)
    return out


sources.register("voice", SOURCE, voice_solo)
