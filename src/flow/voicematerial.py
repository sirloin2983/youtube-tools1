# -*- coding: utf-8 -*-
"""② 管理の層 flow: 声を覚える材料の選び方と切り出し(10-24 夜。ユーザー「誰の声をメンバー全員分」)。

ユーザーの PC の誰の声のカード(app/check/voice_solo)と、友人の PC から送る声の材料(friendapp/voicesend → human/friend/returns)の
両方が同じ決まりで選ぶので、ここに置く(友人のアプリは ytt・pipeline・flow しか読めない)。
  ソロの見分け  solo_person(名簿の配信の文脈で出る人がちょうど 1 人・題名にコラボの印が無い・グループの配信でない・話者が 2 人以上いない)
  歌を外す      song_title(題名に歌の配信の印)・song_row(文字に音符)。歌の声は話し声と響きが違い、伴奏も入る
  行の決まり    row_ok(1 秒以上 MAX_ROW_SEC 以下・混ざりの印・音のメモ overlap/bgm/unclear が無い・字幕に出さない行とゲームの音の話者でない)
  行の並び      pick(GOOD_SEC に近い順)
  切り出し      cut(行の前後 PAD 秒を 16kHz・モノラル・16bit の wav に。認識の音と同じ形)
標準ライブラリと ytt・pipeline だけ。
"""
import os
import re

from pipeline.transcribe import roster
from ytt import schemas as _yschemas, studiodata as _studiodata, tools as _tools, txbase as _txbase

SONG_RE = re.compile(r"歌枠|歌配信|歌ってみた|歌唱|カラオケ|弾き語り|うたわく|歌リレー|歌雑|歌謡|karaoke|singing|\bsing\b|\bcover\b|unarchived", re.I)
NOTE_RE = re.compile(r"[♪♫♬♩]")
COLLAB_RE = re.compile(r"コラボ|collab|\bwith\b|[×✕✖]|凸|ゲスト|guest|対談|参加型|合同|オフ会|みんなで|\bfeat|\bft\.", re.I)   # みんなで = 10-24 に足した(「ホロドリみんなで遊ぼ!」)
BLOCK_RE = re.compile(r"【([^】]{1,80})】")
ROW_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,16}\Z")
MIN_LEARN_SEC = 1.0      # 覚える材料にする行の最短(flow/diar の voice_learn_rows と同じ 1 秒)
LEARN_TAGS = ("overlap", "bgm", "unclear")   # この印の行は覚えない(声が重なる・BGM が大きい・聞き取れない。監査17)
MAX_ROW_SEC = 12.0       # 長すぎる行は聞くのが重いので出さない
GOOD_SEC = 4.0           # この長さに近い行を先に(短すぎず・長すぎず)
PAD = 1.0                # 切り出す行の前後に足す秒(カードの余白 0.3 秒・覚える行の時刻の揺れの分)
RATE = 16000
CUT_TIMEOUT = 60.0
MAX_CUT_SEC = 30.0       # これより長い行は切り出さない


def num(x, default=0.0):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and abs(x) != float("inf") else default


def rows(doc):
    """文書の行(id の形が正しい物)"""
    for g in (doc or {}).get("segments") or ():
        if isinstance(g, dict) and isinstance(g.get("id"), str) and ROW_ID_RE.match(g["id"]):
            yield g


def song_title(titles):
    """題名(の一覧)に歌の配信の印があるか"""
    return any(SONG_RE.search(str(t or "")) for t in (titles if isinstance(titles, (list, tuple)) else [titles]))


def song_row(g):
    """歌の行か(文字に音符がある)"""
    return bool(NOTE_RE.search(str((g or {}).get("text") or "")))


def titles(doc):
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


def _group_names(r):
    """名簿のグループ・ユニット・番組の名前(照らし合わせる形。ユニットの組 units の名前と、ほかの組の見出しの括弧の前)"""
    out = set()
    for g in r.get("groups") or ():
        names = g.get("names") if g.get("id") == "units" else [re.sub(r"[(（].*$", "", str(g.get("label") or ""))]
        out.update(roster.fold(n) for n in names if len(roster.fold(n)) >= 3)
    return out


def group_block(title, r):
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
    ts = titles(doc)
    if len(mem) != 1 or any(COLLAB_RE.search(t) for t in ts):
        return None
    who = mem[0]
    r = roster.load(roster.ROSTER)
    if any(group_block(t, r) for t in ts):
        return None
    for s in doc.get("speakers") or ():
        if isinstance(s, dict) and not _yschemas.other_speaker(s):
            hit = roster.match_name(str(s.get("name") or ""), r)
            if hit and hit != who:
                return None   # 名簿のほかの人の名前の話者がいる = コラボ
    used = {g.get("speaker") for g in rows(doc) if g.get("speaker") and g.get("speaker") != _yschemas.OTHER_SPK_ID}
    return who if len(used) <= 1 else None


def roster_file():
    """今読む名簿のファイル(見分けの答えを覚える側が、名簿が変わったら見直すための印)"""
    return roster.ROSTER


def member(name):
    """名簿のメンバーの名前(名簿の書き方に直す)か None(名簿に無い・名簿が決まっていない)"""
    if roster.ROSTER is None or not isinstance(name, str) or not name.strip():
        return None
    try:
        return roster.match_name(name, roster.load(roster.ROSTER))
    except Exception:
        return None


def row_ok(g):
    """覚える材料になりうる行か(字幕に出さない行・ゲームの音の話者でない・1 秒以上 MAX_ROW_SEC 以下・混ざりの印と音のメモが無い・歌でない)"""
    if _yschemas.no_sub_row(g) or g.get("speaker") == _yschemas.OTHER_SPK_ID or not str(g.get("text") or "").strip() or song_row(g):
        return False
    a, b = num(g.get("start")), num(g.get("end"))
    if b - a < MIN_LEARN_SEC or b - a > MAX_ROW_SEC or _yschemas.has_flag(g.get("flag"), _txbase.MIXED_FLAG):
        return False
    tags = g.get("tags") if isinstance(g.get("tags"), list) else []
    return not any(t in tags for t in LEARN_TAGS)


def pick(doc, ok=None):
    """文書の覚える材料の行を GOOD_SEC に近い順に(ok があればそれにも合う物だけ)"""
    return sorted((g for g in rows(doc) if row_ok(g) and (ok is None or ok(g))),
                  key=lambda g: (abs(num(g.get("end")) - num(g.get("start")) - GOOD_SEC), num(g.get("start"))))


def cut(ff, src, start, end, out):
    """行(元の動画の秒 start〜end)の前後 PAD 秒を out へ wav で切り出す。-> 切り出した所 (a, b) か None。
    ffmpeg が起こせないときは OSError のまま(呼び手が止める)"""
    if end <= start or end - start > MAX_CUT_SEC:
        return None
    a, b = max(0.0, start - PAD), end + PAD
    cmd = [ff, "-hide_banner", "-nostdin", "-y", "-v", "error", "-ss", "%.3f" % a, "-i", src, "-t", "%.3f" % (b - a),
           "-vn", "-ac", "1", "-ar", str(RATE), "-c:a", "pcm_s16le", "-f", "wav", out + ".part"]   # 認識の音と同じ形(16kHz・モノラル・16bit)
    r = _tools.run(cmd, timeout=CUT_TIMEOUT, flags=_tools.no_window_flags(priority="low"), stdout=False, err_tail=5)
    if r.why or r.code != 0 or not os.path.isfile(out + ".part"):
        try:
            os.remove(out + ".part")
        except OSError:
            pass
        return None
    os.replace(out + ".part", out)
    return round(a, 3), round(b, 3)
