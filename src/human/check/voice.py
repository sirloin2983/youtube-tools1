"""「確かめる」の誰の声のカード(voice:diar)の答えの形・選択肢・反映・声の覚え直し(資料の git:before-1028-cleanup:docs/design/v1-check-build.md の 3-2・5 節、
設計 資料の git:before-1028-cleanup-2:docs/design/briefs/rs8-cases/DESIGN_BRIEF.md 2 の 6)。

答えの形(画面 cards/voice.js が送る。_check_answer が整える):
  {"choice": <文書の話者の id>}   その人の声(文書の speakers[] にいる人)
  {"name": <名前>}               その人の声(この文書の speakers[] にまだいない人 = 名前の話者を足す。登録簿の人・名簿の人(選択肢の id は "name:<名前>")と、
                                 画面の「メンバーを選ぶ」の欄で打った名簿に無い名前。覚える材料にするかは _learnable_name の決まり)
  カードの選択肢(options)= 名前のボタン BUTTONS 人(機械の見立てに近い順。buttons)+ その他 + 混ざり・people = 「メンバーを選ぶ」の欄の候補(people_for)
  {"choice": "other"}            その他(ゲームの音など)= 組み込みの話者「ゲーム音声など」+ 字幕に出さない(編集の画面で選んだときと同じ)
  {"choice": "mixed"}            声が混ざっている = 行の印 MIXED_FLAG と音のメモ overlap(話者はそのまま)
  上のどれにも "bgm": true を足せる  ゲーム音・BGM が大きい = 行の音のメモ bgm も付ける(覚える材料にしない。Z で音のメモも戻る)
  名前の答えに "others": true を足せる  別の声も入っている(V。後ろに別の人の声が小さく)= 行の音のメモ overlap(覚える材料にしない・混ざりの印は付けない。10-25)
  {"names": [名前…]}(11-02 の「話者」カード cards/speaker.js。話している人を全部選んで決める)。名前の代わりに札 SPECIALS
                                 (誰か分からないメンバー・メンバー以外の人・ゲームの声)も選べる。"bgm": true(BGM が大きい)・"alt": true(声色が違う = 真似・笑い・歌)を足せる。
                                 反映は前の形に直して同じ道(_effective): 2 人以上 = 混ざり / ゲームの声だけ = その他 / 1 人 = その人の名前(札の人は文書の話者に足すが覚えない)。
                                 声の材料にするのは、測る専用の札(カードの measureOnly)が無く、選んだ人が 1 人だけ・印(bgm・alt)が無いとき
  ソロの配信の守り(collab_docs): ソロの行のカード(voice:solo)で 1 枚でも 2 人以上か配信者以外の人と答えられた文書は、実はコラボだった見込み =
                                 その文書の行は声の材料に数えない(_pending)・その文書から新しいカードも出さない(app/check/voice_solo)
反映(_apply_voice): _doc.edit_row(保存の錠・処理中と評価用は断る・履歴は 10 分に 1 つ)の中で、行の speaker・flag(話者の印 SPK_FLAGS を外す /
  混ざりは付ける)・tags・noSub を直して why="check:voice"。**行は proofed にしない**(文字は確かめていない)・時刻は触らない・層(O2)には commit の今の道で載る(hum は渡さない)。
  Z(_revert_voice)= 逆の commit(行が答えたあとのままのときだけ。もう答える前のままなら書かない。足した話者は誰も使っていなければ外す)。
  名前は ytt.textutil.person_key で比べる(全角半角・大文字小文字・空白・ひらがなとカタカナの違いを無視。声を覚える・字幕の色の名前合わせと同じ)。
声の覚え直し(_maybe_relearn): 名前で答えた行のうち、1 秒以上・混ざっていない・音のメモ(重なり・BGM・聞き取れない)が無い・評価用でない・
  名前が仮の名前(話者n)や一般的な名前でない行を「覚える材料」(applied.learn)にする。登録簿は答えから作り直す写し(human/check/voicebook。11-03):
  まだ入っていない材料があれば、答えたらすぐ(待ちの秒は無い)ジョブ voice-rebuild を足し、登録簿の learnedFrom は答えの id になる。
  失敗しても答えは済んだまま。音が無く特徴の取れない材料は入れない(voicebook の missing)。Z で戻した答えは作り直しで登録簿からも外れる。
  check.voiceRelearnSec(_relearn_sec)は、ソロの配信の行のカードを出す数の目安(app/check/voice_solo)にだけ使う。
③ の層: 文書は human/check/_doc と human/proof(store・speakers)、声の登録簿とジョブは ② flow(diar・jobs)を通す。① は読まない。
"""
import re

from ytt import schemas as _yschemas, settings as _settings, txbase as _txbase
from ytt.textutil import person_key as _person_key
from flow import diar as _diar, jobs as _heavy, voicematerial as _vm
from human.proof import speakers as _speakers
from . import _doc, answerlog, apply as _apply   # 同じ human/check の兄弟

KIND, SOURCE = "voice", "diar"
SOURCES = (SOURCE, "solo")   # 答えの形・反映が同じ出どころ(solo = ソロ配信の行。入口 app/check/voice_solo。10-23)
OTHER, MIXED = _yschemas.OTHER_SPK_ID, "mixed"   # その他 = 組み込みの話者「ゲーム音声など」の id・混ざり = 答えの印
NAME_PREFIX = "name:"           # 選択肢の id: 登録簿の名前(文書にまだいない人)
MAX_NAMED = 9                   # 予想を選ぶ前に集める名前の選択肢の数(カードのボタンは buttons で BUTTONS 人に絞る)
BUTTONS = 3                     # カードの名前のボタンの数(数字キー 1〜3。ほかの人は「メンバーを選ぶ」の欄 = card.people)
MAX_PEOPLE = 400                # 「メンバーを選ぶ」の欄の候補の上限(名簿の全員が入る数)
NAME_MAX = 30                   # 文書の話者の名前の上限(store.sanitize_transcript と同じ)
MIN_LEARN_SEC = 1.0             # 覚える材料にする行の最短(flow/diar の voice_learn_rows と同じ 1 秒)
RELEARN_SEC_DEFAULT = 30.0      # 覚え直すまでの 1 人の材料の合計(秒。編集の設定 check.voiceRelearnSec で変える)
RELEARN_PAUSED = False         # 10-25 ユーザーの答えで再開(外した行 excluded は数えない決まりのまま)。スイッチ: 声の覚え直しを一時止める(10-25 ユーザーの方針「間違った正解で学習しないように」・戻るまでの守り。
                                # 資料の git:before-1028-cleanup:plan/間違った正解のリスク-1025.md。カードの答え・友人の PC の声の材料・研究の音からの覚え直しは、どれもこの道。False で元に戻す)
FIRST_SEC = 10.0                # まだ声が無い人は、この秒で「仮」の声として覚える(初回だけ。10-25: 答え 214 枚で覚えた人が 6 人だけだった)
RELEARN_SEC_RANGE = (5.0, 3600.0)
DIAR_SETTING, DIAR_ENV = "checkVoiceDiarOn", "YTT_CHECK_VOICE_DIAR"   # 判別の記録から作る声のカード(voice:diar)のスイッチ(既定オフ)
SPK_COLORS = _speakers.SPK_COLORS
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
UNKNOWN_MEMBER, OUTSIDER, GAME_VOICE = "誰か分からないメンバー", "メンバー以外の人", "ゲームの声"   # 話者カードの人と同じく選べる札(11-02)
SPECIALS = (UNKNOWN_MEMBER, OUTSIDER, GAME_VOICE)
MAX_NAMES = 8                   # 話者カードで選べる人の数


def diar_enabled():
    """判別の記録から作る誰の声のカード(voice:diar)を出すか。既定オフ(10-24 ユーザー「声のカードはソロ配信限定」: コラボの声は混ざりやすく、
    覚える声を汚すおそれがある・覚えた声が 0 人の今はソロ(voice:solo)から覚えるのが先)。環境変数 YTT_CHECK_VOICE_DIAR の on 系か、
    編集の設定 checkVoiceDiarOn を明示でオンにしたときだけ出す。カードの作り方・答えの反映は残す"""
    import os
    v = str(os.environ.get(DIAR_ENV) or "").strip().lower()
    if v in ("1", "on", "true", "yes"):
        return True
    if v in ("0", "off", "false", "no"):
        return False
    try:
        return _settings.load_settings().get(DIAR_SETTING) is True
    except Exception:
        return False


def _learnable_name(name):
    """覚えてよい名前か(仮の名前 話者n・一般的な名前・空は覚えない = speakers.voice_learn_plan と同じ決まり)"""
    n = str(name or "").strip()
    return bool(n) and n not in SPECIALS and not _speakers.DEFAULT_SPK_NAME.match(n) and not _speakers.is_generic_speaker_name(n)


def doc_embedding(doc):
    """カードで覚える・登録簿を見るモデル(判別の記録のモデル → ② の learn_embedding = 声の名前付けのモデル VOICE_EMB)"""
    return _diar.learn_embedding(str((doc.get("diarization") or {}).get("embedding") or ""))


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


# ---------------------------------------------------------------- 選択肢と予想(入口 app/check/sources の voice:diar が呼ぶ)

def options_for(doc, voices):
    """文書の話者(組み込みの「ゲーム音声など」を除く)→ 登録簿にいて文書にいない名前(新しく覚えた順)を 9 人まで + その他 + 混ざり。
    -> [{id, name, voice?: 登録簿に声がある}]"""
    have = {_person_key(n) for n in voices}
    out, seen = [], set()
    for s in doc.get("speakers") or ():
        if not isinstance(s, dict) or not s.get("id") or _yschemas.other_speaker(s):
            continue
        n = str(s.get("name") or s.get("id"))
        seen.add(_person_key(n))
        out.append({"id": str(s["id"]), "name": n, "voice": _person_key(n) in have})
    for n, v in sorted(voices.items(), key=lambda kv: -int(_yschemas.num_or((kv[1] or {}).get("updatedAt"), 0) or 0)):
        if len(out) >= MAX_NAMED:
            break
        if _person_key(n) in seen or len(n) > NAME_MAX or not _learnable_name(n):
            continue
        seen.add(_person_key(n))
        out.append({"id": NAME_PREFIX + n, "name": n, "voice": True})
    return out[:MAX_NAMED] + [{"id": OTHER, "name": "その他"}, {"id": MIXED, "name": "混ざり"}]


def guess_for(doc, speaker, match, options):
    """機械の予想 {id, name}(全部のカードに付ける)。行の話者に名前があればその人・仮の名前(話者n)のままなら照合のいちばん近い声(match.top)が
    選択肢にあればその名前・無ければ仮の名前のまま。話者が無ければ照合の名前か None"""
    names = {s.get("id"): str(s.get("name") or s.get("id")) for s in doc.get("speakers") or () if isinstance(s, dict) and s.get("id")}
    top = str((match or {}).get("top") or "")
    by_name = {_person_key(o["name"]): o for o in options if o["id"] not in (OTHER, MIXED)}
    if speaker and speaker in names and _learnable_name(names[speaker]):
        return {"id": speaker, "name": names[speaker]}
    if top and _person_key(top) in by_name:
        o = by_name[_person_key(top)]
        return {"id": o["id"], "name": o["name"]}
    if speaker:
        return {"id": speaker, "name": names.get(speaker, speaker)}
    return None


def buttons(options, first=()):
    """カードのボタンにする選択肢 = 名前の選択肢を機械の見立てに近い順(first = 予想・2 番目に近い人の id。ほかは options の順)に
    BUTTONS 人 + その他 + 混ざり。外れた人は people(「メンバーを選ぶ」の欄)から選ぶ"""
    named = [o for o in options if o.get("id") not in (OTHER, MIXED)]
    rank = {fid: i for i, fid in enumerate(x for x in first if x)}
    named.sort(key=lambda o: rank.get(o["id"], len(rank)))   # sort は安定 = first に無い人は元の順
    return named[:BUTTONS] + [o for o in options if o.get("id") in (OTHER, MIXED)]


def people_for(doc, voices, roster_names=()):
    """「メンバーを選ぶ」の欄の候補 [{id, name}] = 文書の話者(id は話者の id = 答えは {choice})→ 覚えた声の登録簿の人 → 名簿の全員
    (id は name:<名前> = 答えは {name})。同じ人(person_key)は 1 つ・仮の名前や一般的な名前・長すぎる名前は名簿と登録簿からは入れない"""
    out, seen = [], set()
    for s in doc.get("speakers") or ():
        if not isinstance(s, dict) or not s.get("id") or _yschemas.other_speaker(s):
            continue
        n = str(s.get("name") or s.get("id"))
        if _person_key(n) not in seen:
            seen.add(_person_key(n))
            out.append({"id": str(s["id"]), "name": n})
    for n in list(voices or ()) + list(roster_names or ()):
        n = str(n or "").strip()
        if not n or _person_key(n) in seen or len(n) > NAME_MAX or not _learnable_name(n):
            continue
        seen.add(_person_key(n))
        out.append({"id": NAME_PREFIX + n, "name": n})
    return out[:MAX_PEOPLE]


# ---------------------------------------------------------------- 答えの検査

def _check_answer(ans):
    """答えを整える -> {"choice": id} か {"name": 名前}(+ "bgm": True・"others": True)。違えば ValueError(400)。
    others = 「別の声も入っている」(V。後ろに別の人の声が小さく入る = 行の音のメモ overlap・覚えない・混ざりの印 MIXED_FLAG は付けない。10-25)"""
    if not isinstance(ans, dict):
        raise ValueError("答えは {choice} か {name} の形で送ってください")
    if "names" in ans:   # 話者カード(11-02): 話している人を全部
        extra = set(ans) - {"names", "bgm", "alt"}
        if extra or not isinstance(ans["names"], list) or not 1 <= len(ans["names"]) <= MAX_NAMES:
            raise ValueError("答えは {names: [名前…]}(1〜%d 人。bgm・alt を足せる)の形で送ってください" % MAX_NAMES)
        out = {"names": list(dict.fromkeys(_check_answer({"name": n if isinstance(n, str) else ""})["name"] for n in ans["names"]))}
        for k in ("bgm", "alt"):
            if k in ans:
                if ans[k] is not True:
                    raise ValueError("%s は true だけ送れます" % k)
                out[k] = True
        return out
    if "others" in ans:
        if ans["others"] is not True:
            raise ValueError("others は true だけ送れます")
        got = _check_answer({k: v for k, v in ans.items() if k != "others"})
        if got.get("choice") in (OTHER, MIXED):
            raise ValueError("別の声も入っている(V)は、名前と一緒に送ってください")
        return dict(got, others=True)
    if "bgm" in ans:
        if ans["bgm"] is not True:
            raise ValueError("bgm は true だけ送れます")
        return dict(_check_answer({k: v for k, v in ans.items() if k != "bgm"}), bgm=True)
    keys = set(ans)
    if keys == {"choice"} and isinstance(ans["choice"], str):
        c = ans["choice"]
        if c.startswith(NAME_PREFIX):
            return _check_answer({"name": c[len(NAME_PREFIX):]})
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

_ROW_RE = re.compile(r"^[A-Za-z0-9_-]{1,16}\Z")


def _spk_flag(flag, mixed):
    parts = [x for x in _yschemas.flag_parts(flag) if x not in _txbase.SPK_FLAGS]
    if mixed:
        parts.append(_txbase.MIXED_FLAG)
    return _yschemas.join_flags(*parts)


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


def _with_tags(tags, *add):
    return list(dict.fromkeys(list(tags or []) + list(add)))


def _speaker_for(doc, ans):
    """答え → (話者の id, 足した話者の id か None)。文書の speakers を書き換える(足すとき)"""
    sps = doc.setdefault("speakers", [])
    if not isinstance(sps, list):
        raise _apply.Refused("文書の話者の表が壊れています", 409, "broken")
    if "name" in ans:
        want = _person_key(ans["name"])
        for s in sps:
            if isinstance(s, dict) and not _yschemas.other_speaker(s) and _person_key(s.get("name")) == want:
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


def _effective(ans):
    """話者カードの答え {names} → 前の形の答え(反映の道は同じ)。ほかの形はそのまま。
    2 人以上 = 混ざり / ゲームの声だけ = その他 / 1 人 = その人の名前(札の人も名前の話者 = 覚えない)。bgm はそのまま・alt は覚えないだけ"""
    if "names" not in ans:
        return ans
    names = ans["names"]
    out = {"choice": MIXED} if len(names) >= 2 else {"choice": OTHER} if names == [GAME_VOICE] else {"name": names[0]}
    if ans.get("bgm"):
        out["bgm"] = True
    return out


def answer_names(row):
    """答えの記録 1 行 → 話している人の名前 [..](声なし・ゲームの声だけ = [])か None(読めない)。混ざり(前の形)は 2 人と数える。
    前の形の {choice: 話者の id} は、予想(guess)の人の id なら予想の名前・違えば「予想と違う人」"""
    a, g = row.get("answer") or {}, row.get("guess") or {}
    if isinstance(a.get("names"), list):
        return [n for n in a["names"] if n != GAME_VOICE]
    if a.get("name"):
        return [a["name"]]
    c = a.get("choice")
    if c == MIXED:
        return ["?", "??"]
    if c == OTHER:
        return []
    if isinstance(c, str) and c:
        return [g.get("name")] if c == g.get("id") and g.get("name") else ["(予想と違う人)"]
    return None


def collab_docs(app_dir, rows=None):
    """ソロの配信の守り(11-02 ユーザー): ソロの行のカード(voice:solo)で 2 人以上か配信者(= カードの予想 guess の人)以外と答えた文書 id の集まり"""
    out = set()
    for r in rows if rows is not None else answerlog.state(app_dir).effective():
        if r.get("kind") != KIND or r.get("source") != "solo":
            continue
        who, names = (r.get("guess") or {}).get("name"), answer_names(r)
        tid = ((r.get("target") or {}).get("docId")) or ((r.get("applied") or {}).get("doc"))
        if not tid or names is None or not who:
            continue
        if len(names) >= 2 or any(_person_key(n) != _person_key(who) for n in names):
            out.add(str(tid))
    return out


def _learn_of(doc, g, sid, ans):
    """名前で答えた行が覚える材料になるなら {name, sec, emb}(ならなければ None)。ans は前の形(_effective の後)"""
    if ans.get("choice") in (OTHER, MIXED) or ans.get("alt") or doc.get("evalSet") is True:
        return None
    a, b = _yschemas.num_or(g.get("start")), _yschemas.num_or(g.get("end"))
    if a is None or b is None or b - a < MIN_LEARN_SEC or _yschemas.has_flag(g.get("flag"), _txbase.MIXED_FLAG):
        return None
    if any(_yschemas.has_flag(g.get("flag"), f) for f in _vm.NOT_FOR_VOICE_FLAGS):
        return None   # 文字起こしの印「自信が低い」「音声でない可能性(BGMなど)」= これから入る材料に使わない(答えたときに 1 回だけ = もう覚えた材料は外さない。10-25)
    tags = g.get("tags") if isinstance(g.get("tags"), list) else []
    if any(t in tags for t in _speakers.VOICE_LEARN_TAGS):
        return None
    name = next((str(s.get("name") or "").strip() for s in doc.get("speakers") or () if isinstance(s, dict) and s.get("id") == sid), "")
    if not _learnable_name(name):
        return None
    return {"name": name[:60], "sec": round(b - a, 2), "emb": doc_embedding(doc)}


def _apply_voice(ctx, card, ans):
    """答えを文書の行へ。-> applied {doc, row, before, after, added, updatedAt, learn?, relearn?}"""
    tid, rid = _doc.row_target(card, "カードの対象(文書・行)が正しくありません", _ROW_RE)
    picked, ans = ans, _effective(ans)
    if picked.get("alt"):
        ans = dict(ans, alt=True)   # 声色が違う = 覚えないだけ(行の音のメモには無い印)

    def change(doc, g, before):
        if ans.get("choice") == MIXED:
            after, added = dict(before, flag=_spk_flag(before["flag"], True), tags=_with_tags(before["tags"], "overlap")), None
        else:
            sid, added = _speaker_for(doc, ans)
            after = dict(before, speaker=sid, flag=_spk_flag(before["flag"], False),
                         noSub=True if sid == OTHER else (before["noSub"] and before["speaker"] != OTHER))
        if ans.get("bgm"):   # ゲーム音・BGM が大きい = 音のメモ bgm(この印の行は _learn_of が覚える材料から外す)
            after["tags"] = _with_tags(after["tags"], "bgm")
        if ans.get("others"):   # 別の声も入っている = 音のメモ overlap(覚える材料から外す・混ざりの印は付けない = 話者はその人のまま。10-25)
            after["tags"] = _with_tags(after["tags"], "overlap")
        _set_row(g, after)
        learn = None if card.get("measureOnly") or tid in collab_docs(getattr(ctx, "app_dir", "")) else _learn_of(doc, g, g["speaker"], ans)   # 測る専用の札・コラボだった見込みの配信は覚えない
        return added, learn, doc
    before, after, (added, learn, doc) = _doc.edit_fields(tid, rid, "check:voice", _row_state, change)
    applied = {"doc": tid, "row": rid, "before": before, "after": after, "added": added, "updatedAt": doc.get("updatedAt")}
    if "names" in picked:
        applied["names"] = list(picked["names"])
    if learn:
        applied["learn"] = learn
        try:
            applied["relearn"] = _maybe_relearn(ctx, extra=[dict(learn, doc=tid, row=rid)])
        except Exception as e:   # 覚え直しが始められなくても答えは済んだまま(次の答えでまた数える)
            _txbase.log.warning("確かめる: 声の覚え直しを始められませんでした: %s %s", e.__class__.__name__, str(e)[:200])
    return applied


def _revert_voice(ctx, row):
    """Z。答える前の行に戻す(行が答えたあとのままのときだけ。もう答える前のままなら書かない)。-> {doc, row}"""
    a = row.get("applied") or {}
    tid, rid = str(a.get("doc") or ""), str(a.get("row") or "")
    if not _yschemas.TID_RE.match(tid) or not isinstance(a.get("before"), dict) or not isinstance(a.get("after"), dict):
        raise _apply.Refused("この答えは戻せません(記録の形が違います)", 409, "cannot_undo")

    def put(doc, g):
        _set_row(g, a["before"])
        added = a.get("added")
        if added and not any(isinstance(x, dict) and x.get("speaker") == added for x in doc.get("segments") or ()):
            doc["speakers"] = [s for s in doc.get("speakers") or () if not (isinstance(s, dict) and s.get("id") == added)]
    _doc.revert_fields(tid, rid, "check:voice", _row_state, lambda now: now == a["before"], lambda now: now == a["after"], put,
                       "この行はあとで直されています(編集の画面で直してください)")
    return {"doc": tid, "row": rid}


# ---------------------------------------------------------------- 声の覚え直し

def _relearn_sec():
    """覚え直すまでの 1 人の材料の合計(秒)。編集の設定 check.voiceRelearnSec(無い・読めない・範囲の外は既定)"""
    try:
        v = (_settings.load_settings().get("check") or {}).get("voiceRelearnSec")
    except Exception:
        v = None
    v = _yschemas.num_or(v) if not isinstance(v, bool) else None
    lo, hi = RELEARN_SEC_RANGE
    return float(v) if v is not None and lo <= v <= hi else RELEARN_SEC_DEFAULT


def _pending(ctx, extra=()):
    """まだ登録簿に入っていない材料 -> [材料](human/check/voicebook.pending。答えの古い順)。extra = 記録にまだ書いていない今の答えの材料"""
    from . import voicebook   # voicebook が voice を読むので、ここで読む
    todo, _stale = voicebook.pending(ctx.app_dir)
    return todo + list(extra)


def _maybe_relearn(ctx, extra=()):
    """まだ登録簿に入っていない材料か、戻した答えの材料が登録簿にあれば、登録簿を答えから作り直すジョブ voice-rebuild を足す(11-03 情報をまとめる所の 1)。
    -> [{names, job}](足さなければ [])。待っている・動いている作り直しがあれば足さない(そのジョブが読む答えに今の答えも入る見込み = 漏れても次の見回りで拾う)。
    RELEARN_PAUSED の間は足さない(答えの記録とカードはそのまま = 材料は貯まり、戻せば作り直しで入る)"""
    from . import voicebook
    if RELEARN_PAUSED or voicebook.KIND not in _heavy.JOB_RUNNERS or not _diar.voice_ready():
        return []
    todo, stale = voicebook.pending(ctx.app_dir)
    todo += list(extra)
    if not todo and not stale:
        return []
    names = sorted({str(it.get("name") or "") for it in todo} - {""})
    job = voicebook.request(ctx.app_dir, "声の登録簿を答えから作り直す(確かめる): 新しい材料 %d 個・外す答え %d 個" % (len(todo), stale))
    return [{"names": names, "job": job["id"]}] if job else []


for _src in SOURCES:
    _apply.register(KIND, _src, _apply_voice, _revert_voice, _check_answer)
