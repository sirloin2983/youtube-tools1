"""今の画面の URL を、案件の画面(/cases)の URL へ転送する表(RS8 の案件の画面 C0。計画 docs/design/rs8-cases-build.md の 2 節)。

C4(0.59.0)で古い画面(スタジオ・編集のページ)を消したので、転送はいつも有効(スイッチ YTT_CASES_REDIRECT は消した)。
表は純粋な関数 target(path, query, doc_for) だけ(入口の PortalHandler が do_GET の頭で呼ぶ)。
フラグメント(#tab)はブラウザが転送先に引き継ぐので、Location に # が無いときは元の # が残る(/transcribe/?doc=T#cut -> /cases?d=T#cut)。
"""
import urllib.parse

from ytt import schemas

STUDIO_PAGES = ("/studio", "/studio/", "/studio/index.html")
EDITOR_PAGES = ("/transcribe", "/transcribe/", "/transcribe/index.html")


def _id_ok(s):
    return isinstance(s, str) and 1 <= len(s) <= 64 and all(ch.isalnum() or ch in "-_" for ch in s)


def _one(q, name):
    v = q.get(name)
    return v[0] if v else ""


def target(path, query, doc_for=None):
    """-> 転送先の Location か None(転送しない)。query は parse_qs の結果。doc_for(動画のパス) -> 文書の id か ""(?media=・?clip= 用)"""
    if path in STUDIO_PAGES:
        vid = _one(query, "video")
        if vid:
            return "/cases?c=%s#cand" % urllib.parse.quote(vid) if _id_ok(vid) else "/"
        if _one(query, "step") == "rank":
            return "/#new"
        if _one(query, "url"):
            return "/#new?url=" + urllib.parse.quote(_one(query, "url"), safe="")
        return "/"
    if path in EDITOR_PAGES:
        tid = _one(query, "doc")
        if tid:
            return "/cases?d=%s" % tid if schemas.TID_RE.match(tid) else "/"
        if _one(query, "drill") == "1":
            return "/cases?c=eval#proof"
        media = _one(query, "media") or _one(query, "clip")
        if media:
            found = doc_for(media) if doc_for else ""
            if found and schemas.TID_RE.match(found):
                return "/cases?d=%s#proof" % found
            return "/#new?media=" + urllib.parse.quote(media, safe="")
        return "/"
    return None
