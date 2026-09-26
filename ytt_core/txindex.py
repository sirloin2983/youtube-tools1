"""文字起こしの文書(文字起こしツールの transcripts/*.json)を、他のツールから**読むだけ**の部品(統合計画の段階4)。

入口の案件の画面(app/cases.py)と、スタジオのセリフの表示(clip-studio/txlink.py)が、同じ紐づけの規則を使うためにここに置く:
  切り抜き(スタジオの書き出し済みのマーク)の文字起こし =
    ① 文書の sourcePath が、書き出した mp4 のパスと同じ
    ② 無ければ、文書の clip(.clip.json の中身)の source.videoId・mark.id が、その配信・マークと同じ(動画を動かした後でも見つかる)
  同じ切り抜きに複数あれば、更新が新しいもの。
文書の行の時刻は切り抜きの中の時刻。元の配信の時刻 = offset + t(offset は .clip.json の export.actualStart → range.start の順。
ytt_core.schemas.clip_offset)。.clip.json が無ければマークの開始を使う(高速書き出しのずれ(数秒)は直せない)。
文書は大きい(数百行)ので、ファイルの更新日時・大きさが変わったときだけ読み直す。

パックの有無(pack_info・is_pack_dir)もここ1か所で決める。2026-09-26(④)から cut2resolve の画面・API のパックはフォルダに cut-plan.json を置かず、
cut2resolve の作業データ packs/ に「パックを作った記録」を残す(書くのは cut2resolve の serve.py。ここは読むだけ)。
記録が無ければ、以前のパック(フォルダの中の cut-plan.json)を見る。
"""
import hashlib
import os
import threading

from . import datadir, fsio, schemas

MAX_DOC_BYTES = 32 * 1024 * 1024
MAX_TEXT = 500
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACK_RECORD_SCHEMA = "youtube-tools-pack-record/v1"
MAX_PACK_RECORD_BYTES = 16 * 1024 * 1024
TEXTPLUS_SCRIPT = "create_resolve_textplus_project.lua"
OLD_TEXTPLUS_PLAN = "textplus-import.json"
CUT_PLAN_SCHEMA = "youtube-tools-cut-plan/v1"
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


def pack_dir(media_path):
    """切り抜きの隣の <名前>_pack(cut2resolve の既定の出力先)のパス"""
    return os.path.join(os.path.dirname(media_path), os.path.splitext(os.path.basename(media_path))[0] + "_pack")


_packs_dir_used = None   # 起動した cut2resolve が知らせた記録のフォルダ(入口の中では同じプロセスの他のツールもここを読む)


def use_packs_dir(path):
    """cut2resolve の serve.py が起動したときに、自分の記録のフォルダを知らせる(テストがツールを一時フォルダに写して動かしても、
    書く場所と読む場所がずれないように)"""
    global _packs_dir_used
    _packs_dir_used = os.path.abspath(path) if path else None


def packs_dir(env=None, c2r_dir=None):
    """パックを作った記録のフォルダ(cut2resolve の作業データの packs。YTT_DATA_DIR=inplace なら cut2resolve のフォルダの中)。
    起動した cut2resolve が知らせた場所(use_packs_dir)があればそれ(env を渡したときは使わない = テスト)。
    c2r_dir: cut2resolve のコードのフォルダ(serve.py が自分の場所を渡す。無ければ環境変数 YTT_CUT2RESOLVE_DIR → リポジトリの cut2resolve)"""
    if _packs_dir_used and env is None:
        return _packs_dir_used
    env = os.environ if env is None else env
    legacy = c2r_dir or env.get("YTT_CUT2RESOLVE_DIR") or os.path.join(REPO_ROOT, "cut2resolve")
    return os.path.join(datadir.tool_dir("cut2resolve", legacy, env), "packs")


def pack_key(dirpath):
    """パックのフォルダ → 記録のファイル名(フォルダのパスの大文字小文字をそろえたハッシュ)"""
    return hashlib.sha1(norm(str(dirpath)).encode("utf-8")).hexdigest()[:20] + ".json"


def read_pack_record(dirpath, env=None, c2r_dir=None):
    """パックを作った記録(cut2resolve の packs/)。フォルダがあり、記録した中身のファイルが1つでも残っているときだけ返す
    (フォルダを消した・作り直した後の古い記録で「パック済み」にしない)。-> 記録 か None"""
    if not dirpath:
        return None
    try:
        rec = fsio.read_json_file(os.path.join(packs_dir(env, c2r_dir), pack_key(dirpath)), MAX_PACK_RECORD_BYTES)
    except (OSError, UnicodeError, ValueError):
        return None
    if not isinstance(rec, dict) or rec.get("schema") != PACK_RECORD_SCHEMA or norm(rec.get("dir")) != norm(str(dirpath)):
        return None
    files = [f for f in rec.get("files") or [] if isinstance(f, str) and f and not os.path.isabs(f) and ".." not in f.replace("\\", "/").split("/")]
    if not any(os.path.isfile(os.path.join(str(dirpath), f)) for f in files):
        return None
    return rec


def _old_cut_plan(dirpath):
    """以前のパック(2026-09-26 まで。フォルダの中の cut-plan.json)。-> (更新日時 ms, 中身 or None) か None"""
    p = os.path.join(str(dirpath), "cut-plan.json")
    try:
        mt = int(os.path.getmtime(p) * 1000)
    except OSError:
        return None
    try:
        d = fsio.read_json_file(p, 4 * 1024 * 1024)
    except (OSError, UnicodeError, ValueError):
        d = None
    return mt, d if isinstance(d, dict) else None


def pack_info(media_path, env=None):
    """切り抜きのパック(cut2resolve が作る <名前>_pack)があるか。パックを作った記録(④)か、以前のパックならフォルダの中の cut-plan.json。
    -> {"dir", "textplus"(Text+ パックか), "updatedAt"(ms)} か None。入口の案件の画面・まとめて実行・文字起こしの一覧が同じ規則で使う(規則はここ1か所)"""
    if not media_path:
        return None
    d = pack_dir(media_path)
    rec = read_pack_record(d, env)
    if rec:
        at = rec.get("builtAt")
        return {"dir": d, "textplus": rec.get("textplus") is True,
                "updatedAt": at if isinstance(at, int) and not isinstance(at, bool) else 0}
    old = _old_cut_plan(d)
    if not old:
        return None
    textplus = any(os.path.isfile(os.path.join(d, n)) for n in (OLD_TEXTPLUS_PLAN, TEXTPLUS_SCRIPT))
    return {"dir": d, "textplus": textplus, "updatedAt": old[0]}


def is_pack_dir(dirpath, env=None, c2r_dir=None):
    """cut2resolve が作ったパックのフォルダか(「フォルダを開く」・前回のパックの手順書を読むのを許すか)。
    パックを作った記録があるか、以前のパックなら中の cut-plan.json が cut2resolve の書いた youtube-tools-cut-plan"""
    if not dirpath or not os.path.isdir(str(dirpath)):
        return False
    if read_pack_record(dirpath, env, c2r_dir):
        return True
    old = _old_cut_plan(dirpath)
    d = old[1] if old else None
    tool = d.get("tool") if d else None
    return bool(d) and d.get("schema") == CUT_PLAN_SCHEMA and isinstance(tool, dict) and tool.get("name") == "cut2resolve"
