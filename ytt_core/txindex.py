"""文字起こしの文書(文字起こしツールの transcripts/*.json)を、他のツールから**読むだけ**の部品(統合計画の段階4)。

入口の案件の画面(app/cases.py)と、スタジオのセリフの表示(clip-studio/txlink.py)が、同じ紐づけの規則を使うためにここに置く:
  切り抜き(スタジオの書き出し済みのマーク)の文字起こし =
    ① 文書の sourcePath が、書き出した mp4 のパスと同じ
    ② 無ければ、文書の clip(.clip.json の中身)の source.videoId・mark.id が、その配信・マークと同じ(動画を動かした後でも見つかる)
  同じ切り抜きに複数あれば、更新が新しいもの。
文書の行の時刻は切り抜きの中の時刻。元の配信の時刻 = offset + t(offset は .clip.json の export.actualStart → range.start の順。
ytt_core.schemas.clip_offset)。.clip.json が無ければマークの開始を使う(高速書き出しのずれ(数秒)は直せない)。
文書は大きい(数百行)ので、ファイルの更新日時・大きさが変わったときだけ読み直す。
"""
import os
import threading

from . import datadir, fsio, schemas

MAX_DOC_BYTES = 32 * 1024 * 1024
MAX_TEXT = 500
_cache = {}          # パス -> ((更新日時ns, 大きさ), 読んだ中身)
_lock = threading.Lock()


def folder(repo_root, env=None):
    """文字起こしの文書のフォルダ。文字起こしツールと同じ規則(環境変数 TRANSCRIBE_DATA_DIR → ytt_core.datadir)"""
    env = os.environ if env is None else env
    home = env.get("TRANSCRIBE_DATA_DIR") or datadir.tool_dir("transcribe", os.path.join(repo_root, "transcribe-tool"), env)
    return os.path.join(home, "transcripts")


def norm(p):
    return os.path.normcase(os.path.abspath(p)) if isinstance(p, str) and p else ""


def _num(x):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and abs(x) < 1e9 else None


def _parse(d, fallback_id):
    if not isinstance(d, dict) or not isinstance(d.get("segments"), list):
        return None
    names = {}
    for s in d.get("speakers") or []:
        if isinstance(s, dict) and isinstance(s.get("id"), str):
            names[s["id"]] = str(s.get("name") or s["id"])[:30]
    segs = []
    for s in d["segments"]:
        if not isinstance(s, dict):
            continue
        a, b = _num(s.get("start")), _num(s.get("end"))
        if a is None or b is None or a < 0 or b < a:
            continue
        segs.append({"start": a, "end": b, "text": str(s.get("text") or "")[:MAX_TEXT],
                     "speaker": names.get(s.get("speaker"), "") if isinstance(s.get("speaker"), str) else "",
                     "proofed": s.get("proofed") is True, "cut": s.get("cutState") == "cut"})
    clip = d.get("clip") if isinstance(d.get("clip"), dict) else None
    up = d.get("updatedAt")
    return {"id": str(d.get("id") or fallback_id)[:40], "title": str(d.get("title") or "")[:120],
            "sourcePath": d.get("sourcePath") if isinstance(d.get("sourcePath"), str) else "",
            "clip": clip, "segments": segs, "updatedAt": up if isinstance(up, int) and not isinstance(up, bool) else 0,
            "count": len(segs), "proofed": sum(1 for s in segs if s["proofed"]), "cut": sum(1 for s in segs if s["cut"])}


def load(dirpath):
    """フォルダの文書を全部(壊れたもの・形式の違うものは飛ばす)。-> [文書]。返した中身は書き換えないこと(キャッシュと共有)"""
    try:
        names = sorted(n for n in os.listdir(dirpath) if n.endswith(".json") and len(n) == 17)   # <12文字の id>.json
    except OSError:
        return []
    out, seen = [], set()
    with _lock:
        for n in names:
            p = os.path.join(dirpath, n)
            seen.add(p)
            try:
                st = os.stat(p)
            except OSError:
                continue
            key = (st.st_mtime_ns, st.st_size)
            hit = _cache.get(p)
            if hit and hit[0] == key:
                doc = hit[1]
            else:
                try:
                    doc = _parse(fsio.read_json_file(p, MAX_DOC_BYTES), n[:-5])
                except (OSError, UnicodeError, ValueError):
                    doc = None
                _cache[p] = (key, doc)
            if doc is not None:
                out.append(doc)
        for p in [p for p in _cache if os.path.dirname(p) == dirpath and p not in seen]:
            del _cache[p]   # 消えた文書
    return out


def summary(doc):
    return {"id": doc["id"], "title": doc["title"], "segments": doc["count"], "proofed": doc["proofed"], "cut": doc["cut"], "updatedAt": doc["updatedAt"]}


def matches(doc, video_id, mark_id, media_path):
    media = norm(media_path)
    if media and norm(doc["sourcePath"]) == media:
        return True
    c = doc.get("clip") or {}
    src = c.get("source") if isinstance(c.get("source"), dict) else {}
    mk = c.get("mark") if isinstance(c.get("mark"), dict) else {}
    return bool(video_id) and bool(mark_id) and src.get("videoId") == video_id and mk.get("id") == mark_id


def pick(docs, video_id, mark_id, media_path):
    """-> (いちばん新しい文書 または None, 紐づいた文書の数, 紐づいた文書の id の一覧)"""
    hits = [d for d in docs if matches(d, video_id, mark_id, media_path)]
    best = max(hits, key=lambda d: d["updatedAt"]) if hits else None
    return best, len(hits), [d["id"] for d in hits]


def offset(doc, video_id, media_path, fallback):
    """切り抜きの中の時刻 → 元の配信の時刻 のずれ。-> (offset, 根拠 "clip" | "sidecar" | "mark")
    ① 文書に入っている .clip.json の中身(同じ配信のものだけ)② 書き出した mp4 の隣の .clip.json ③ マークの開始(fallback)"""
    def usable(c):
        c, _ = schemas.validate_clip(c)
        src = (c or {}).get("source") if c else None
        if c and (not isinstance(src, dict) or src.get("videoId") in (None, "", video_id)):
            return c
        return None
    c = usable(doc.get("clip")) if doc.get("clip") else None
    if c:
        return schemas.clip_offset(c), "clip"
    if media_path and not fsio.is_network_path(media_path):   # ネットワーク上のパスには触らない(資格情報を送らない)
        side, _ = schemas.load_clip_file(schemas.clip_path_for(media_path))
        c = usable(side) if side else None
        if c:
            return schemas.clip_offset(c), "sidecar"
    return float(fallback or 0), "mark"


def lines(doc, off, limit=3000):
    """元の配信の時刻にした行。-> [{"start", "end", "text", "speaker", "proofed", "cut"}]"""
    return [dict(s, start=round(s["start"] + off, 2), end=round(s["end"] + off, 2)) for s in doc["segments"][:limit]]
