"""「確かめる」のカードの出どころ(V1 の V0。notes:docs/design/v1-check-build.md の 2-2)。読むだけ(作業データに書かない)。

出どころは register(kind, source, fn) で登録する(V2 の 4 本が足す・差し替える)。fn(view) -> カードの一覧(lineup.py の形 + `_order`)。
view(View)は 1 回の集め(collect)の間だけ読んだ物を共有する: 案件の一覧(cases.snapshot)・評価用でない文字起こしの文書・.diar.json・
スタジオの data.json・答えの記録(answers)。
**評価用(文書の evalSet・評価用のフォルダ evalDirs の中の動画)は View.docs の 1 か所で外す**(出どころは View.docs だけを使う)。
**元の動画が無い文書(has_media が偽)も View.docs・View.eval_docs で外す**: 文書のカードは動画の口 MEDIA(元の動画 sourcePath を返す)で流すので、
片付けで消えた動画のカードは流せない(10-24: 読みのカード 20 枚中 2 枚)。どの種類も同じ。YouTube の埋め込みで流すカード(value:cand)は文書を見ないので外れない。
V0 で入れた出どころ(細部は V2 で直す):
  value:auto  自動でできた切り抜きの品質(案件の clips[].auto。送った物も送らなかった物も・pending とごみ箱の物と評価用は外す)
  value:cand  候補のまま(スタジオの YouTube の配信で、まだ 1 本も採用・書き出ししていない配信の、状態が空のマーク。点数の高い順)
  read:fill   後処理(fill)が直した行で、校正していない・今の文字と認識のままが違う物
  voice:diar  話者の判別(.diar.json の latest.rows)の行で、1 秒以上・混ざり無し・校正していない物。自信の低い順(照合の弱い話者 → 弱い行 → 声の無い人)。
              選択肢と機械の予想は ③ human/check/voice(答えの形の持ち主。V2c)が組む = 文書の話者 + 覚えた声の登録簿にいて文書にいない人 + その他 + 混ざり
  time:row    文字が決まった行(校正済みか、読みのカードで答えた行)で、時刻のカードにまだ答えていない物
read の「別のエンジン」(alt)は read_sources.py(V2b)が register で足す。
"""
import os
import re
import threading

from human.check import value as value_mod
from human.check import voice as voice_mod
from manage.cases import cases as cases_mod, txindex
from ytt import fsio, settings
from . import lineup   # 同じ app/check の兄弟

DOC_NAME_RE = re.compile(r"^([0-9a-f]{12})\.json\Z")
MAX_DOC_BYTES = 64 * 1024 * 1024
MAX_DIAR_BYTES = 32 * 1024 * 1024
DIAR_SCHEMA = "youtube-tools-diar/v1"   # src/pipeline/transcribe/diarize.py の DIAR_SCHEMA と同じ(test_sources が食い違いを検査)
MAX_PER_SOURCE = 5000                   # 出どころ 1 つから出すカードの上限(並べる前。重くしない)
MIN_VOICE_SEC = 1.0
MEDIA = "transcribe/media?id=%s"        # 画面から相対(入口の直下の /check から取り込んだ編集の動画の口)
YT_EMBED = "https://www.youtube-nocookie.com/embed/%s?start=%d&end=%d"
YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}\Z")
ROW_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,16}\Z")
MARK_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}\Z")
OTHER, MIXED = "other", "mixed"         # 声のカードの「その他」(組み込みの話者 other)・「混ざり」の答えの印

_docs = fsio.StampCache()
_diars = fsio.StampCache()
_SOURCES = {}
_reg_lock = threading.Lock()


def register(kind, source, fn):
    """出どころを足す・差し替える(kind は lineup.KINDS のどれか)"""
    if kind not in lineup.KINDS or not re.match(r"^[a-z]{1,12}\Z", source or ""):
        raise ValueError("種類・出どころの名前が正しくありません")
    with _reg_lock:
        _SOURCES[(kind, source)] = fn


def _unregister(kind, source):
    """テストが足した出どころを外す"""
    with _reg_lock:
        _SOURCES.pop((kind, source), None)


def registered():
    with _reg_lock:
        return sorted(_SOURCES)


def _num(x, default=0.0):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and abs(x) != float("inf") else default


def _load_doc(path):
    try:
        if os.path.getsize(path) > MAX_DOC_BYTES:
            return None
        d = fsio.read_json_file(path, MAX_DOC_BYTES, allow_nan=True)
    except (OSError, UnicodeError, ValueError, RecursionError):
        return None
    return d if isinstance(d, dict) and isinstance(d.get("segments"), list) else None


def has_media(doc):
    """文書の元の動画が手元にあるか(動画の口 MEDIA で流せるか)。ネットワークのパスは見ない(届かないと止まるため)= 無い扱い"""
    p = str(doc.get("sourcePath") or "") if isinstance(doc, dict) else ""
    return bool(p) and not fsio.is_network_path(p) and os.path.isfile(p)


def _load_diar(path):
    return fsio.read_schema_json(path, MAX_DIAR_BYTES, DIAR_SCHEMA, "latest", dict)


class View:
    """1 回の集めで読む物の入れ物。ctx = {root, env, eval_dirs?(評価用のフォルダの一覧。None = 編集の設定から)}・state = 答えの記録(answerlog.State)"""

    def __init__(self, ctx, state=None):
        self.ctx, self.state = ctx, state
        self.root, self.env = getattr(ctx, "root", None), getattr(ctx, "env", None)
        self.errors = []
        self._cases = self._docs = self._eval_dirs = self._doc_case = None

    # ---- 案件
    def cases(self):
        if self._cases is None:
            try:
                self._cases = cases_mod.snapshot(self.root, self.env)
            except Exception as e:   # 読めなくても他の出どころは出す
                self.errors.append("cases: %s" % e.__class__.__name__)
                self._cases = {"cases": [], "virtual": []}
        return self._cases

    def case_of_doc(self, tid):
        """文書 -> {id, title}(案件に紐づかなければ id は "")"""
        if self._doc_case is None:
            m = {}
            res = self.cases()
            for c in (res.get("cases") or []) + (res.get("virtual") or []):
                for cl in c.get("clips") or ():
                    for t in list(cl.get("transcriptIds") or ()) + [((cl.get("transcript") or {}).get("id"))]:
                        if t and t not in m:
                            m[t] = {"id": str(c.get("id") or ""), "title": str(c.get("title") or "")[:120]}
            self._doc_case = m
        return self._doc_case.get(tid)

    # ---- 評価用の判定(ここ 1 か所)
    def eval_dirs(self):
        if self._eval_dirs is None:
            dirs = getattr(self.ctx, "eval_dirs", None)
            if dirs is None:
                try:
                    dirs = settings.eval_dirs()
                except Exception:
                    dirs = []
            self._eval_dirs = list(dirs)
        return self._eval_dirs

    def is_eval(self, doc):
        if not isinstance(doc, dict) or doc.get("evalSet") is True:
            return True
        src = doc.get("sourcePath")
        try:
            return bool(isinstance(src, str) and src and settings.in_eval_dir(src, self.eval_dirs()))
        except Exception:
            return True   # 判定が例外のときは評価用として扱う(出さない側。印の無い評価用の動画を、読みのカードの答えとして学習の記録へ入れない。OPT-E1 3e-1)

    # ---- 文字起こしの文書(評価用は外す)
    def docs(self):
        """[(tid, 文書のパス, 文書)] 評価用でない・元の動画がある物。新しい順(updatedAt)。返した文書は書き換えない(キャッシュと共有)"""
        if self._docs is None:
            out = []
            try:
                folder = txindex.folder(self.root, self.env)
                paths = txindex.doc_paths(folder) if os.path.isdir(folder) else {}
            except Exception as e:
                self.errors.append("docs: %s" % e.__class__.__name__)
                paths = {}
            for name in sorted(paths):
                m = DOC_NAME_RE.match(name)
                if not m or not os.path.isfile(paths[name]):
                    continue
                d = _docs.get(paths[name], _load_doc)
                if d is None or self.is_eval(d) or not has_media(d):
                    continue
                out.append((m.group(1), paths[name], d))
            out.sort(key=lambda x: -_num(x[2].get("updatedAt")))
            self._docs = out
        return self._docs

    def eval_docs(self):
        """[(tid, 文書のパス, 文書)] 評価用の文書だけ(evalSet が True。評価のレーンの区間カード = C-EVAL だけが使う)。新しい順。
        普段の出どころは docs() だけを使う(評価用を外す 1 か所はそのまま)"""
        if getattr(self, "_eval_docs", None) is None:
            out = []
            try:
                folder = txindex.folder(self.root, self.env)
                paths = txindex.doc_paths(folder) if os.path.isdir(folder) else {}
            except Exception as e:
                self.errors.append("docs: %s" % e.__class__.__name__)
                paths = {}
            for name in sorted(paths):
                m = DOC_NAME_RE.match(name)
                if not m or not os.path.isfile(paths[name]):
                    continue
                d = _docs.get(paths[name], _load_doc)
                if d is not None and d.get("evalSet") is True and has_media(d):
                    out.append((m.group(1), paths[name], d))
            out.sort(key=lambda x: -_num(x[2].get("updatedAt")))
            self._eval_docs = out
        return self._eval_docs

    def doc_ids(self):
        """評価用でない文書の id の集合(文書を指すカードはここに無い文書を出さない)"""
        return {t for t, _p, _d in self.docs()}

    def diar(self, tid, doc_path):
        """文書の隣の <id>.diar.json の latest(無ければ None)"""
        d = _diars.get(os.path.join(os.path.dirname(doc_path), tid + ".diar.json"), _load_diar)
        return d.get("latest") if isinstance(d, dict) else None

    # ---- 答えの記録
    def answered(self, kind=None):
        """効いている答えの行(kind で絞る)"""
        if self.state is None:
            return []
        return [r for r in self.state.effective() if kind is None or r.get("kind") == kind]


def _tight(doc, row, a, b, pad):
    """行の文字・声を確かめるカード(読み・誰の声)の区間: 次の行の発言を入れない。
    末の余白 0・末は次の行の頭まで(行が重なっていれば詰める)・頭の余白は pad まで、ただし前の行の終わりより前へ出ない。
    -> (頭, 末, 頭の余白)。並びは文書の segments の順(時刻の順)"""
    segs = [g for g in doc.get("segments") or () if isinstance(g, dict)]
    i = next((k for k, g in enumerate(segs) if g is row), -1)
    if i < 0:
        return a, b, pad
    if i + 1 < len(segs):
        nxt = _num(segs[i + 1].get("start"))
        if a < nxt < b:
            b = nxt
    if i > 0:
        prev_end = _num(segs[i - 1].get("end"))
        pad = max(0.0, min(pad, a - prev_end)) if prev_end > 0 else pad
    return a, b, round(pad, 3)


def _doc_card(view, kind, source, tid, doc, row, pad, extra, tight=False):
    """tight = 行の時刻にきっちり(次の行の発言を入れない。_tight。読み・誰の声のカード)。media.padEnd = 末の余白(無ければ pad と同じ)"""
    case = view.case_of_doc(tid) or {"id": "", "title": str(doc.get("title") or "")[:120]}
    a, b = _num(row.get("start")), _num(row.get("end"))
    media = {"url": MEDIA % tid, "start": a, "end": b, "pad": pad}
    if tight:
        a, b, head = _tight(doc, row, a, b, pad)
        media.update({"end": b, "pad": head, "padEnd": 0.0})
    card = {"id": lineup.card_id(kind, source, tid, row["id"]), "kind": kind, "source": source, "case": case,
            "target": {"docId": tid, "row": row["id"], "videoId": case["id"] or None},
            "media": media, "text": str(row.get("text") or ""),
            "guess": None, "options": [], "score": None, "note": ""}
    card.update(extra)
    return card


def _rows(doc):
    for g in doc.get("segments") or ():
        if isinstance(g, dict) and isinstance(g.get("id"), str) and ROW_ID_RE.match(g["id"]):
            yield g


def _fold(s):
    return re.sub(r"\s+", "", str(s or ""))


# ---------------------------------------------------------------- V0 の出どころ

def value_auto(view):
    """送った後の品質の確認(2-8)。自動でできた切り抜き(clip.auto)のうち、送った物も送らなかった物も出す。
    外すのは ごみ箱へ移した物(exists が偽 = 要らない・日数の片付け)・評価用の文書・読めない文書だけ"""
    out = []
    ok_docs = view.doc_ids()   # 評価用でない・読める文書がある切り抜きだけ
    for c in view.cases().get("cases") or ():
        if c.get("gone"):
            continue
        for cl in c.get("clips") or ():
            tid = (cl.get("transcript") or {}).get("id")
            mid = cl.get("markId") or ""
            if not cl.get("auto") or cl.get("exists") is False or tid not in ok_docs or not MARK_RE.match(mid):
                continue
            if not MARK_RE.match(str(c.get("id") or "")):
                continue
            auto = cl.get("auto") or {}
            out.append({"id": lineup.card_id("value", "auto", c["id"], mid), "kind": "value", "source": "auto",
                        "case": {"id": c["id"], "title": str(c.get("title") or "")[:120]},
                        "target": {"videoId": c["id"], "markId": mid, "docId": tid, "row": None},
                        "media": {"url": MEDIA % tid, "start": 0.0, "end": None, "pad": 0.0}, "text": str(cl.get("label") or ""),
                        "guess": None, "options": list(value_mod.AUTO_CHOICES), "reasons": [{"id": k, "text": t} for k, t in value_mod.AUTO_REASONS.items()],
                        "score": auto.get("score"), "note": str(auto.get("originLabel") or ""),
                        "_order": [0, -_num(c.get("streamedAt")), _num(cl.get("start"))]})
    return out


def value_cand(view):
    out = []
    try:
        videos = cases_mod.read_studio(cases_mod.locations(view.root, view.env)["studio"])
    except Exception as e:
        view.errors.append("studio: %s" % e.__class__.__name__)
        return out
    for vid, v in videos.items():
        if not isinstance(v, dict) or v.get("kind") != "youtube" or not YT_ID_RE.match(str(vid)) or v.get("caseUnseen"):
            continue
        marks = [m for m in v.get("marks") or () if isinstance(m, dict)]
        if any(m.get("status") in ("adopted", "exported") for m in marks):
            continue   # 選び始めた配信の残りは「選ばなかった物」(案件の todo.review と同じ規則)
        for m in marks:
            mid = str(m.get("id") or "")
            if m.get("status") or not MARK_RE.match(mid):
                continue
            a, b = _num(m.get("start")), _num(m.get("end"))
            if b <= a:
                continue
            out.append({"id": lineup.card_id("value", "cand", vid, mid), "kind": "value", "source": "cand",
                        "case": {"id": vid, "title": str(v.get("title") or "")[:120]},
                        "target": {"videoId": vid, "markId": mid, "docId": None, "row": None},
                        "media": {"url": YT_EMBED % (vid, int(a), int(b + 0.999)), "start": a, "end": b, "pad": 0.0},
                        "text": str(m.get("label") or ""), "guess": None, "options": ["adopt", "reject"], "score": m.get("score"), "note": "",
                        "_order": [1, -_num(m.get("score")), a]})
    return out


def read_fill(view):
    out = []
    for tid, _path, doc in view.docs():
        for g in _rows(doc):
            f = g.get("fill")
            if not isinstance(f, dict) or g.get("proofed") is True or not isinstance(f.get("from"), str):
                continue
            if _fold(f["from"]) == _fold(g.get("text")):
                continue
            out.append(_doc_card(view, "read", "fill", tid, doc, g, 0.5, {
                "guess": "1", "options": [{"id": "1", "text": str(g.get("text") or "")}, {"id": "2", "text": f["from"]}],
                "note": str(f.get("by") or ""), "_order": [-_num(doc.get("updatedAt")), _num(g.get("start"))]}, tight=True))
            if len(out) >= MAX_PER_SOURCE:
                return out
    return out


def voice_diar(view):
    out, voices = [], {}
    if not voice_mod.diar_enabled():   # 既定オフ(10-24 声のカードはソロ配信限定 = voice:solo だけ)
        return out
    for tid, path, doc in view.docs():
        latest = view.diar(tid, path)
        rows = latest.get("rows") if isinstance(latest, dict) else None
        if not isinstance(rows, dict):
            continue
        sps = latest.get("voices") if isinstance(latest.get("voices"), dict) else {}
        sps = sps.get("speakers") if isinstance(sps.get("speakers"), dict) else {}
        reg = voice_mod.registry(voice_mod.doc_embedding(doc), voices)
        opts = voice_mod.options_for(doc, reg)
        names = {o["id"]: o for o in opts}
        for g in _rows(doc):
            r = rows.get(g["id"])
            if not isinstance(r, dict) or r.get("mixed") or g.get("proofed") is True or g.get("noSub") is True:
                continue
            if _num(g.get("end")) - _num(g.get("start")) < MIN_VOICE_SEC:
                continue
            sp = r.get("speaker") or g.get("speaker") or ""
            v = sps.get(sp) if isinstance(sps.get(sp), dict) else {}
            low = 0 if v.get("reason") in ("below_match", "margin") else 1   # 声の照合が弱い話者を先に
            margin = _num(v.get("score"), 1.0) - _num(v.get("secondScore"), 0.0)
            novoice = 0 if sp in names and not names[sp].get("voice") else 1   # まだ声を覚えていない人を先に
            out.append(_doc_card(view, "voice", "diar", tid, doc, g, 0.3, {
                "guess": voice_mod.guess_for(doc, sp, v, opts), "options": opts, "score": r.get("ratio"),
                "note": str(v.get("reason") or ""),
                "_order": [low, 0 if r.get("weak") else 1, novoice, _num(r.get("ratio"), 1.0), margin, -_num(doc.get("updatedAt")), _num(g.get("start"))]}, tight=True))
            if len(out) >= MAX_PER_SOURCE:
                return out
    return out


def time_row(view):
    out = []
    decided = {(r.get("target") or {}).get("docId", "") + "#" + str((r.get("target") or {}).get("row")) for r in view.answered("read")}
    for tid, _path, doc in view.docs():
        for g in _rows(doc):
            if g.get("cutState") == "cut" or g.get("noSub") is True or "unclear" in (g.get("tags") or ()):
                continue
            if g.get("proofed") is not True and (tid + "#" + g["id"]) not in decided:
                continue
            if _num(g.get("end")) <= _num(g.get("start")):
                continue
            out.append(_doc_card(view, "time", "row", tid, doc, g, 2.5, {
                "guess": "ok", "options": ["ok", "head", "tail", "both"], "_order": [-_num(doc.get("updatedAt")), _num(g.get("start"))]}))
            if len(out) >= MAX_PER_SOURCE:
                return out
    return out


for _k, _s, _f in (("value", "auto", value_auto), ("value", "cand", value_cand), ("read", "fill", read_fill),
                   ("voice", "diar", voice_diar), ("time", "row", time_row)):
    register(_k, _s, _f)

from . import read_sources   # noqa: E402,F401  read:alt を足す(V2b。read_sources は上の register・_doc_card を読む)


def collect(ctx, state=None, kinds=None):
    """登録した出どころから集める。-> (カードの一覧, View)。kinds を渡すとその種類の出どころだけ。1 つの出どころが失敗しても他は出す"""
    view = View(ctx, state)
    cards = []
    for (kind, source) in registered():
        if kinds and kind not in kinds:
            continue
        with _reg_lock:
            fn = _SOURCES.get((kind, source))
        try:
            got = list(fn(view) or ())[:MAX_PER_SOURCE] if fn else []
        except Exception as e:
            view.errors.append("%s:%s: %s" % (kind, source, e.__class__.__name__))
            continue
        cards.extend(c for c in got if isinstance(c, dict) and lineup.parse_id(c.get("id")) and c.get("kind") == kind)
    return cards, view
from . import speech_sources, eval_sources, cut_sources, voice_solo   # noqa: E402,F401  「この行は声ですか?」(普段)と区間カード(評価)を足す(C-EVAL。register)
