"""文字起こしの文書(文字起こしツールの transcripts/*.json)を、他のツールから**読むだけ**の部品(統合計画の段階4)。

入口の案件の画面(src/manage/cases/cases.py)と、スタジオのセリフの表示(src/manage/cases/txlink.py)が、同じ紐づけの規則を使うためにここに置く:
  切り抜き(スタジオの書き出し済みのマーク)の文字起こし =
    ① 文書の sourcePath が、書き出した mp4 のパスと同じ(30fps にそろえて付け替えた文書は、付け替える前のパス = relinks の why "normalize30" の from も。Q1)
    ② 無ければ、文書の clip(.clip.json の中身)の source.videoId・mark.id が、その配信・マークと同じ(動画を動かした後でも見つかる)
  同じ切り抜きに複数あれば、更新が新しいもの。
文書の行の時刻は切り抜きの中の時刻。元の配信の時刻 = offset + t(offset は .clip.json の export.actualStart → range.start の順。
ytt.schemas.clip_offset)。.clip.json が無ければマークの開始を使う(高速書き出しのずれ(数秒)は直せない)。
文書は大きい(数百行)ので、ファイルの更新日時・大きさが変わったときだけ読み直す。

パックの有無(pack_info・is_pack_dir)もここ1か所で決める。cut2resolve の画面・API のパックはフォルダに cut-plan.json を置かず、
cut2resolve の作業データ packs/ に「パックを作った記録」を残す(記録の形・置き場所・書くのは ② flow/packrec。cut2resolve の API も
入口なしの道(友人のアプリ)も同じ after_build を呼ぶ = OPT-M2。ここは ② の読み口を使うだけ)。記録だけを見る(フォルダの中の cut-plan.json は見ない)。
"""
import os

from flow import packrec as _packrec
from ytt import datadir, docloc, fsio, layout, schemas

NORM_WHY = "normalize30"   # 「編集」が 30fps の写しへ付け替えたときの relinks[].why(manage/cases/relink.py の NORM_WHY と同じ)

MAX_DOC_BYTES = 32 * 1024 * 1024
MAX_TEXT = 500
REPO_ROOT = layout.src_root()   # ツールの親(src)
_cache = fsio.StampCache()   # パス -> 読んだ中身(ファイルの更新日時・大きさが変わったときだけ読み直す。テストが名前で見る)


def folder(repo_root, env=None):
    """文字起こしの文書のフォルダ。置き場所の規則は ytt.datadir.resolve の1か所(起動した「編集」が登録した場所 →
    環境変数 TRANSCRIBE_DATA_DIR → YTT_DATA_DIR・既定の場所)"""
    return os.path.join(datadir.resolve("transcribe", repo_root, env), "transcripts")


def norm(p):
    return os.path.normcase(os.path.abspath(p)) if isinstance(p, str) and p else ""


def _num(x):
    v = schemas.num(x)
    return v if v is not None and abs(v) < 1e9 else None


def _ms(v):
    """更新日時(ms の整数。bool は数えない)。違えば 0"""
    return v if schemas.is_int(v) else 0


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
    aliases = [r["from"] for r in d.get("relinks") or [] if isinstance(r, dict) and r.get("why") == NORM_WHY and isinstance(r.get("from"), str) and r["from"]][-5:]
    src = d.get("sourcePath") if isinstance(d.get("sourcePath"), str) else ""
    return {"id": str(d.get("id") or fallback_id)[:40], "title": str(d.get("title") or "")[:120],
            "sourcePath": src, "aliases": aliases, "_paths": _norm_paths(src, aliases),
            "clip": clip, "segments": segs, "updatedAt": _ms(d.get("updatedAt")), "evalSet": d.get("evalSet") is True,
            "count": len(segs), "proofed": sum(1 for s in segs if s["proofed"]), "cut": sum(1 for s in segs if s["cut"])}


def _norm_paths(source, aliases):
    """紐づけ ① に使うパス(sourcePath と付け替える前のパス)をそろえたもの。読んだときに1回だけ求めてキャッシュと一緒に持つ
    (案件の一覧は マーク × 文書 の数だけ照らし合わせるので、毎回 abspath しない)"""
    return frozenset(n for n in (norm(p) for p in [source, *aliases]) if n)


def _docloc_root(dirpath):
    """dirpath が docloc の根(今の TX_DIR か 作業データ/transcripts)なら (True, data_dir)。それ以外のフォルダは索引を見ない"""
    def same(a, b):
        return bool(a) and bool(b) and os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
    if same(dirpath, docloc.tx_root()):
        return True, None
    if os.path.basename(os.path.normpath(dirpath)) == "transcripts":
        return True, os.path.dirname(os.path.normpath(dirpath))
    return False, None


def doc_paths(dirpath):
    """フォルダの中のファイル名 -> そのパス(OSError はそのまま投げる)。dirpath が文書の根なら、案件の 作業用 に置いた文書
    (索引 .loc.json があるもの)の <id>.json は、その置き場所のパスにして足す。索引が無ければ listdir の名前をそのまま dirpath に付けただけ"""
    out = {n: os.path.join(dirpath, n) for n in os.listdir(dirpath)}
    ok, data_dir = _docloc_root(dirpath)
    if ok:
        for tid, p in docloc.doc_files(data_dir).items():   # 索引は一覧 1 回で 1 回だけ確かめる(PERF O15)
            out[tid + ".json"] = p
    return out


def load(dirpath):
    """フォルダの文書を全部(壊れたもの・形式の違うものは飛ばす)。-> [文書]。返した中身は書き換えないこと(キャッシュと共有)"""
    try:
        found = doc_paths(dirpath)
    except OSError:
        return []
    names = sorted(n for n in found if n.endswith(".json") and len(n) == 17)   # <12文字の id>.json
    paths = [found[n] for n in names]
    docs = [_cache.get(p, lambda p, n=n: _parse(fsio.read_json_or(p, None, MAX_DOC_BYTES), n[:-5])) for p, n in zip(paths, names)]
    _cache.prune(paths, dirpath)   # 消えた文書
    return Docs(d for d in docs if d is not None)


class Docs(list):
    """load の結果(ふつうのリスト)。pick が初めて呼ばれたときに逆引きを作って、この一覧の間だけ使う(PERF O5。
    切り抜きごとに全文書を照らすと 切り抜きの数 × 文書の数 になる)。中身を足し引きすると(長さが変わると)作り直す"""
    _rev = None

    def reverse_index(self):
        if self._rev is None or self._rev[0] != len(self):
            self._rev = (len(self), _reverse(self))
        return self._rev[1]


def _reverse(docs):
    """-> (正規化したパス -> [文書の通し番号], (videoId, markId) -> [文書の通し番号], [逆引きに入れられない文書の通し番号])。
    番号は一覧の順(同じ id の別の文書も別に持つ)。videoId・markId がハッシュにできない値(JSON の配列・オブジェクト)の文書は、毎回 _match で照らす"""
    by_path, by_mark, odd = {}, {}, []
    for i, doc in enumerate(docs):
        for p in doc["_paths"] if "_paths" in doc else _norm_paths(doc.get("sourcePath"), doc.get("aliases") or ()):
            by_path.setdefault(p, []).append(i)
        c = doc.get("clip") or {}
        src = c.get("source") if isinstance(c.get("source"), dict) else {}
        mk = c.get("mark") if isinstance(c.get("mark"), dict) else {}
        v, m = src.get("videoId"), mk.get("id")
        if v and m:   # 照らす側も両方が真のときだけ一致にする(_match)
            try:
                by_mark.setdefault((v, m), []).append(i)
            except TypeError:
                odd.append(i)
    return by_path, by_mark, odd


def summary(doc):
    return {"id": doc["id"], "title": doc["title"], "segments": doc["count"], "proofed": doc["proofed"], "cut": doc["cut"], "updatedAt": doc["updatedAt"]}


def _match(doc, video_id, mark_id, media):
    """media は norm 済みの切り抜きのパス。load を通らずに作った文書(_paths が無い)はここで求める"""
    paths = doc["_paths"] if "_paths" in doc else _norm_paths(doc.get("sourcePath"), doc.get("aliases") or ())
    if media and media in paths:
        return True
    c = doc.get("clip") or {}
    src = c.get("source") if isinstance(c.get("source"), dict) else {}
    mk = c.get("mark") if isinstance(c.get("mark"), dict) else {}
    return bool(video_id) and bool(mark_id) and src.get("videoId") == video_id and mk.get("id") == mark_id


def matches(doc, video_id, mark_id, media_path):
    return _match(doc, video_id, mark_id, norm(media_path))


def pick(docs, video_id, mark_id, media_path):
    """-> (いちばん新しい文書 または None, 紐づいた文書の数, 紐づいた文書の id の一覧)"""
    media = norm(media_path)
    if isinstance(docs, Docs):
        hits = _pick_rev(docs, video_id, mark_id, media)
    else:
        hits = [d for d in docs if _match(d, video_id, mark_id, media)]
    best = max(hits, key=lambda d: d["updatedAt"]) if hits else None
    return best, len(hits), [d["id"] for d in hits]


def _pick_rev(docs, video_id, mark_id, media):
    """逆引きで pick の hits を求める(全部を _match で照らしたのと同じ文書・同じ順)。パスの一致 または 配信とマークの一致の和を、一覧の順に"""
    by_path, by_mark, odd = docs.reverse_index()
    idx = set(by_path.get(media, ())) if media else set()
    if video_id and mark_id:
        try:
            idx.update(by_mark.get((video_id, mark_id), ()))
        except TypeError:   # 照らす側の id がハッシュにできない = 逆引きを使わず全部を照らす
            return [d for d in docs if _match(d, video_id, mark_id, media)]
        idx.update(i for i in odd if _match(docs[i], video_id, mark_id, media))
    return [docs[i] for i in sorted(idx)]


def offset(doc, video_id, media_path, fallback):
    """切り抜きの中の時刻 → 元の配信の時刻 のずれ。-> (offset, 根拠 "clip" | "sidecar" | "mark")
    ① 文書に入っている .clip.json の中身(同じ配信のものだけ)② 書き出した mp4 の .clip.json(作業用/ か隣)③ マークの開始(fallback)"""
    def usable(c):
        """検証できて、同じ配信のもの(videoId が無いものも可)だけ。validate_clip は dict でないもの(None など)に (None, 理由) を返す"""
        c, _ = schemas.validate_clip(c)
        src = c.get("source") if c else None
        return c if c and (not isinstance(src, dict) or src.get("videoId") in (None, "", video_id)) else None
    c = usable(doc.get("clip"))
    if c:
        return schemas.clip_offset(c), "clip"
    if media_path and not fsio.is_network_path(media_path):   # ネットワーク上のパスには触らない(資格情報を送らない)
        cp = schemas.find_clip_path(media_path)   # 作業用/ → 動画の隣
        side, _ = schemas.load_clip_file(cp) if cp else (None, None)
        c = usable(side)
        if c:
            return schemas.clip_offset(c), "sidecar"
    return float(fallback or 0), "mark"


def lines(doc, off, limit=3000):
    """元の配信の時刻にした行。-> [{"start", "end", "text", "speaker", "proofed", "cut"}]"""
    return [dict(s, start=round(s["start"] + off, 2), end=round(s["end"] + off, 2)) for s in doc["segments"][:limit]]


def pack_dir(media_path):
    """切り抜きの隣の <名前>_pack(cut2resolve の既定の出力先)のパス"""
    return os.path.join(os.path.dirname(media_path), os.path.splitext(os.path.basename(media_path))[0] + "_pack")


def pack_info(media_path, env=None):
    """切り抜きのパック(cut2resolve が作る <名前>_pack)があるか。パックを作った記録(④)で決める。
    -> {"dir", "textplus"(Text+ パックか), "updatedAt"(ms)} か None。入口の案件の画面・まとめて実行・文字起こしの一覧が同じ規則で使う(規則はここ1か所)"""
    if not media_path:
        return None
    d = pack_dir(media_path)
    rec = _packrec.read_record(d, env)
    if not rec:
        return None
    return {"dir": d, "textplus": rec.get("textplus") is True, "updatedAt": _ms(rec.get("builtAt"))}


def is_pack_dir(dirpath, env=None, c2r_dir=None):
    """cut2resolve が作ったパックのフォルダか(「フォルダを開く」・前回のパックの手順書を読むのを許すか)。
    パックを作った記録があるか"""
    if not dirpath or not os.path.isdir(str(dirpath)):
        return False
    return bool(_packrec.read_record(dirpath, env, c2r_dir))
