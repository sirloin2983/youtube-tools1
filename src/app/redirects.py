"""今の画面の URL を、案件の画面(/cases)の URL へ転送する表(RS8 の案件の画面 C0。計画 notes:docs/design/rs8-cases-build.md の 2 節)。

C4(0.59.0)で古い画面(スタジオ・編集のページ)を消したので、転送はいつも有効(スイッチ YTT_CASES_REDIRECT は消した)。
表は純粋な関数 target(path, query, doc_for) だけ(入口の PortalHandler が do_GET の頭で呼ぶ)。
フラグメント(#tab)はブラウザが転送先に引き継ぐので、Location に # が無いときは元の # が残る(/transcribe/?doc=T#cut -> /cases?d=T#cut)。
"""
import urllib.parse

from ytt import schemas

STUDIO_PAGES = ("/studio", "/studio/", "/studio/index.html")
EDITOR_PAGES = ("/transcribe", "/transcribe/", "/transcribe/index.html")
C2R_PAGES = ("/cut2resolve/", "/cut2resolve/index.html")   # 以前の cut2resolve の画面(?video= だけ。引数なしは取り込みの page_to の案内のまま)


def _id_ok(s):
    return isinstance(s, str) and 1 <= len(s) <= 64 and all(ch.isalnum() or ch in "-_" for ch in s)


def _one(q, name):
    v = q.get(name)
    return v[0] if v else ""


def target(path, query, doc_for=None, media_of=None):
    """-> 転送先の Location か None(転送しない)。query は parse_qs の結果。doc_for(動画のパス) -> 文書の id か ""(?media=・?clip= 用)。
    media_of(.clip.json のパス) -> その .clip.json が指す動画のパスか ""(?clip= は .clip.json を指すので、動画に直してから探す)"""
    if path in STUDIO_PAGES:
        vid = _one(query, "video")
        if vid:
            return "/cases?c=%s#cand" % urllib.parse.quote(vid) if _id_ok(vid) else "/"
        if _one(query, "step") == "rank":
            return "/#new"
        if _one(query, "url"):
            return "/#new?url=" + urllib.parse.quote(_one(query, "url"), safe="")
        return "/"
    if path in C2R_PAGES:   # ?video=<動画のパス> は編集の ?media= と同じ行き先へ 1 回で(以前は /transcribe/?media= を挟んで 2 回。RS8 C4)
        return _media_target(_one(query, "video"), doc_for, media_of) if _one(query, "video") else None
    if path in EDITOR_PAGES:
        tid = _one(query, "doc")
        if tid:
            return "/cases?d=%s" % tid if schemas.TID_RE.match(tid) else "/"
        if _one(query, "drill") == "1":
            return "/cases?c=eval#proof"
        media = _one(query, "media") or _one(query, "clip")
        if media:
            return _media_target(media, doc_for, media_of)
        return "/"
    return None


def _media_target(media, doc_for, media_of=None):
    """動画のパス -> その文書の校正か、無ければ新しい案件の動画ファイルの欄。.clip.json のパス(?clip=)は指す動画に直す(直せなければ動画の欄は空のまま)"""
    if media.lower().endswith(".clip.json"):
        media = (media_of(media) if media_of else "") or ""
        if not media:
            return "/"
    found = doc_for(media) if doc_for else ""
    if found and schemas.TID_RE.match(found):
        return "/cases?d=%s#proof" % found
    return "/#new?media=" + urllib.parse.quote(media, safe="")
