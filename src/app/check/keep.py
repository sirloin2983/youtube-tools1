"""自動の片付けが残す動画を、確かめるのカードから選ぶ(入口の PortalServer.clean_inputs が材料を集めて渡す。10-24 の直し)。

残す = 確かめるにまだ出ているカード(種類に関わらず = 声・読み・時刻・声かどうか・価値・カット)の文書の切り抜きの動画と、
「切り抜く価値」で答えを待っている自動の切り抜き(答えは精度の材料)と、評価用の文書の動画(案件の一覧の virtual の eval)。
読むだけ(案件の一覧・答えの記録・カードは入口が集める)。manage/keep に置かないのは、app/check と human を読むため(層の決まり)。
"""
import re

from human.proof import voiceclips   # 誰の声のカードの行の短い音(残してあれば動画が片付いても流せる)
from . import lineup   # 同じ app/check の兄弟

_MEDIA_ID = re.compile(r"[?&]id=([0-9a-f]{12})\b")


def answered_ids(st, cards):
    """答えた・[分からない] のカードの id の集合(= もう出ない)。st = human/check/answerlog の State"""
    return set(st.by_card) | {c.get("id") for c in cards if isinstance(c, dict) and st.closed(c)}


def pending_docs(cards, answered):
    """確かめるにまだ出ているカード(答えていない)が見ている文書の id の集合(target.docId と、動画の口 transcribe/media?id= の id)。
    自動の片付けがこの文書の切り抜きの動画とパックを残す(10-24)。切り出した行の音で流すカード・行の音を残してある誰の声のカード(voiceclips)は
    動画が片付いても音で流せるので数えない(動画があるうちは映像つきで流す)"""
    out = set()
    for c in cards or ():
        if not isinstance(c, dict) or c.get("id") in answered:
            continue
        media = c.get("media") if isinstance(c.get("media"), dict) else {}
        url = media.get("url")
        if str(url or "").startswith("api/check/voiceclip"):
            continue
        tg = c.get("target") if isinstance(c.get("target"), dict) else {}
        tid = tg.get("docId")
        if c.get("kind") == "voice" and tid and voiceclips.clip_path(str(tid), str(tg.get("row") or "")):
            continue
        if isinstance(tid, str) and tid:
            out.add(tid)
        m = _MEDIA_ID.search(url) if isinstance(url, str) else None
        if m:
            out.add(m.group(1))
    return out


def keep_paths(snap, cards, answered):
    """案件の一覧(manage/cases の snapshot)・カード・答えたカードの id -> 残す切り抜きの動画のパスの一覧"""
    docs = pending_docs(cards, answered)
    keep = []
    for c in (snap.get("cases") or []) + (snap.get("virtual") or []):
        for cl in (c.get("clips") or ()) if isinstance(c, dict) else ():
            if not isinstance(cl, dict) or not cl.get("path"):
                continue
            tids = set(cl.get("transcriptIds") or ()) | {(cl.get("transcript") or {}).get("id")}
            if tids & docs or (cl.get("auto") and lineup.card_id("value", "auto", c.get("id"), cl.get("markId") or "") not in answered):
                keep.append(cl["path"])
    for v in snap.get("virtual") or ():
        if isinstance(v, dict) and v.get("caseKind") == "eval":
            keep += [cl["path"] for cl in v.get("clips") or () if isinstance(cl, dict) and cl.get("path")]
    return keep
