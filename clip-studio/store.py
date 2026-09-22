"""③ 動画とマークの保存(data.json)。スレッドセーフ・原子的に書き込む。

- 動画: youtube(id=YouTube動画ID) / file(id="f"+sha1(絶対パス)[:10])。file のパスはサーバー内部だけが持ち、クライアントには返さない。
- マーク: サーバーが検査・整形する。status / file / src / 点数 / auto0 などのサーバー由来の値はクライアントから書き換えられない。
- 変更は「新しい状態を作る → ディスクに保存 → 成功したらメモリに反映」の順(保存に失敗したらメモリは変わらない)。
- 解析結果の series(盛り上がりグラフ)は cache/series/<動画ID>.json にも保存する(最新60本まで。再起動後もグラフが出る)。
- マークの status: ""(候補) / "adopted"(採用) / "rejected"(不採用) / "exported"(書き出し済み)。exported はサーバーだけが付ける。
- data.json が壊れていたら data.json.corrupt-<日時> に退避して空で起動し、dataWarning で知らせる。1つ前の世代は data.json.bak。
"""
import copy
import json
import math
import os
import re
import shutil
import sys
import threading
import time

import analyze
import common
from common import ApiError, atomic_write

SCHEMA = "clip-studio/v1"
ID_RE = re.compile(r"^[\w-]{1,40}\Z", re.ASCII)
MAX_MARKS = 500
MAX_MARK_SEC = 3600
MAX_TIME = 1e7          # 秒。これを超える値は不正(巨大な数値対策)
PART_KEYS = ("audio", "chat", "comments")
STATUS_CLIENT = ("", "adopted", "rejected")   # クライアントが設定できる状態(exported はサーバーだけ)
SERIES_KEEP = 60
DUP_TOL = 0.5           # 自動マークが既存マークとこれ以内のずれなら「同じ区間」
EDIT_TOL = 0.05         # 書き出し済みマークの時刻がこれより動いたら「書き出し済み」を外す
SAVE_ERR = "保存に失敗しました(ディスクの空きなど)"

# ---- コラボ動画のマーク転写(グループ+オフセット) ----
MAX_GROUPS = 50
MAX_GROUP_MEMBERS = 8
COLLAB_MARGIN = 2.5     # 転写した区間を前後に広げる秒数(反応のタイミングは人によってずれるため)
ANCHOR_A_MIN, ANCHOR_A_MAX = 0.5, 1.5   # アンカー点から求めた傾き(ドリフト補正)の妥当な範囲。外れたら入力ミスの可能性が高い
MIN_ANCHOR_GAP = 20.0   # 2点指定のとき、この動画の時刻でこれ以上離れていることを要求する(近すぎると傾きが不安定)


def now_ms():
    return int(time.time() * 1000)


def _warn(msg):
    sys.stderr.write("[store] " + msg + "\n")


class BadMark(Exception):
    pass


def _f(v):
    if isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _num_strict(v):
    """JSON の数値(int/float)だけを受け付ける。文字列・真偽値・NaN・Infinity・巨大な値は None。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        x = float(v)
    except (OverflowError, ValueError):
        return None
    return x if math.isfinite(x) and abs(x) <= MAX_TIME else None


def check_times(s_raw, e_raw):
    """開始・終了(秒)を検査して、小数1桁に丸めた (start, end) を返す。不正なら BadMark(理由)。"""
    s, e = _num_strict(s_raw), _num_strict(e_raw)
    if s is None or e is None:
        raise BadMark("開始・終了が数値ではありません(または大きすぎます)")
    if s < 0:
        raise BadMark("開始が0秒より前です")
    s, e = round(s, 1), round(e, 1)
    if e <= s:
        raise BadMark("終了が開始より後になっていません")
    if e - s > MAX_MARK_SEC:
        raise BadMark("長さが%d秒を超えています" % MAX_MARK_SEC)
    return s, e


def _auto0(v):
    if isinstance(v, (list, tuple)) and len(v) == 2:
        a, b = _f(v[0]), _f(v[1])
        if a is not None and b is not None:
            return [round(a, 1), round(b, 1)]
    return None


def _collab_from(v):
    """コラボ転写マークの由来({videoId, markId})を検査する。不正なら None。"""
    if isinstance(v, dict):
        vid, mid = v.get("videoId"), v.get("markId")
        if isinstance(vid, str) and ID_RE.match(vid) and isinstance(mid, str) and ID_RE.match(mid):
            return {"videoId": vid, "markId": mid}
    return None


def _clean_server(d):
    """サーバーだけが決める項目(src, 点数, 理由, 書き出し状態, auto0, collabFrom)を、型を整えて取り出す。"""
    st = d.get("status") if d.get("status") in ("", "adopted", "rejected", "exported") else ""
    f = str(d.get("file") or "")[:300] if st == "exported" and isinstance(d.get("file"), str) else ""
    score, peak = _f(d.get("score")), _f(d.get("peak"))
    reasons = [str(r)[:40] for r in d.get("reasons")[:6]] if isinstance(d.get("reasons"), list) else []
    parts = {}
    if isinstance(d.get("parts"), dict):
        for k in PART_KEYS:
            x = _f(d["parts"].get(k))
            if x is not None:
                parts[k] = round(x, 2)
    ca = d.get("createdAt")
    src = d.get("src") if d.get("src") in ("auto", "collab") else "manual"
    return {"src": src, "score": None if score is None else round(score, 2), "reasons": reasons, "parts": parts,
            "peak": None if peak is None else round(peak, 1), "status": st, "file": f if st == "exported" else "",
            "createdAt": ca if isinstance(ca, int) and not isinstance(ca, bool) and ca > 0 else now_ms(),
            "auto0": _auto0(d.get("auto0")) if src in ("auto", "collab") else None,
            "collabFrom": _collab_from(d.get("collabFrom")) if src == "collab" else None}


def _build_mark(m, old, trusted=False):
    """1件のマークを検査して整形する。不正なら BadMark。old: 同じ id の既存マーク(サーバー由来の値を引き継ぐ)。id は呼び出し側で検査済み。"""
    s, e = check_times(m.get("start"), m.get("end"))
    if old is not None:
        srv = _clean_server(old)
        cs = m.get("status") if m.get("status") in STATUS_CLIENT else None   # クライアントが決められる状態(exported・未指定は無視)
        moved = abs(s - old["start"]) > EDIT_TOL or abs(e - old["end"]) > EDIT_TOL
        if srv["status"] == "exported":
            # 書き出し済みのマークの開始・終了を動かしたら、書き出し済みの扱いを外す(ファイルは別物になるため)。採用済みだった扱いに戻す
            if cs is not None:
                srv["status"], srv["file"] = cs, ""
            elif moved:
                srv["status"], srv["file"] = "adopted", ""
        elif cs is not None:
            srv["status"] = cs
    elif trusted:
        srv = _clean_server(m)
    else:
        srv = _clean_server({})   # クライアントが作る新しいマークは、必ず手動・未書き出し(状態は 候補/採用/不採用 だけ指定できる)
        if m.get("status") in STATUS_CLIENT:
            srv["status"] = m["status"]
        ca = m.get("createdAt")
        if isinstance(ca, int) and not isinstance(ca, bool) and ca > 0:
            srv["createdAt"] = ca
    label = m.get("label")
    d = {"id": m["id"], "start": s, "end": e, "label": label.strip()[:120] if isinstance(label, str) else "", "src": srv["src"], "score": srv["score"],
         "reasons": srv["reasons"], "parts": srv["parts"], "peak": srv["peak"], "live": bool(m.get("live")), "status": srv["status"], "file": srv["file"],
         "createdAt": srv["createdAt"]}
    if srv["auto0"]:
        d["auto0"] = srv["auto0"]
    if srv.get("collabFrom"):
        d["collabFrom"] = srv["collabFrom"]
    return d


def load_marks(raw):
    """保存済み(信頼できる)マークの読み込み。壊れた1件は読み飛ばす(ログに残す)。"""
    out, seen = [], set()
    for m in raw if isinstance(raw, list) else []:
        try:
            if not isinstance(m, dict) or not isinstance(m.get("id"), str) or not ID_RE.match(m["id"]) or m["id"] in seen:
                raise BadMark("id")
            c = _build_mark(m, None, True)
        except Exception as e:
            _warn("壊れたマークを読み飛ばしました: %s" % str(e)[:80])
            continue
        seen.add(c["id"])
        out.append(c)
        if len(out) >= MAX_MARKS:
            break
    return out


def validate_marks(raw, old_marks):
    """PUT /api/video のマークを厳しく検査する。1件でも不正なら ApiError 400 bad_marks(何も変えない)。id の無い新しいマークにはサーバーが id を付ける。"""
    if len(raw) > MAX_MARKS:
        raise ApiError("bad_marks", "マークは%d件までです(いま%d件)" % (MAX_MARKS, len(raw)), 400)
    old = {m["id"]: m for m in old_marks}
    ids = {m.get("id") for m in raw if isinstance(m, dict) and isinstance(m.get("id"), str)}
    out, seen = [], set()
    for i, m in enumerate(raw):
        where = "%d番目のマーク" % (i + 1)
        if not isinstance(m, dict):
            raise ApiError("bad_marks", where + "が正しくありません(オブジェクトではありません)", 400)
        mid = m.get("id")
        if mid is None or mid == "":
            while True:
                mid = "m" + os.urandom(6).hex()
                if mid not in ids and mid not in seen and mid not in old:
                    break
            m = dict(m, id=mid)
        elif not isinstance(mid, str) or not ID_RE.match(mid):
            raise ApiError("bad_marks", where + "の id が正しくありません(英数字・_・- の1〜40文字)", 400)
        if mid in seen:
            raise ApiError("bad_marks", "%s(id: %s)は id が重複しています" % (where, mid), 400)
        try:
            c = _build_mark(m, old.get(mid))
        except BadMark as e:
            raise ApiError("bad_marks", "%s(id: %s)が正しくありません: %s" % (where, mid, e), 400)
        seen.add(mid)
        out.append(c)
    return out


def _same(a, b):
    return abs(a["start"] - b["start"]) <= DUP_TOL and abs(a["end"] - b["end"]) <= DUP_TOL


def _overlaps(a_s, a_e, b_s, b_e):
    """2つの区間が少しでも重なっているか。コラボ転写で「既に同じような部分にマークがある」の判定に使う
    (_same の完全一致・±0.5秒より緩い基準。転写側は COLLAB_MARGIN で前後に広げてあるので、単純な重なりで十分)。"""
    return a_s < b_e and b_s < a_e


def _touched(m):
    """ユーザーが手を入れた自動マークか(採用・不採用・書き出し済み / ラベルあり / 時刻を動かした)。"""
    a0 = m.get("auto0")
    return (m["status"] != "" or bool(m["label"]) or not a0 or abs(m["start"] - a0[0]) > EDIT_TOL or abs(m["end"] - a0[1]) > EDIT_TOL)


# ---- コラボグループの時刻対応(t_ref = a * t_this + b。区分的な配列を持てるが、v0 は要素1つだけ作る) ----
def _load_pieces(raw):
    """保存済みの区分的オフセット配列を検査する。壊れた要素は読み飛ばす。"""
    if not isinstance(raw, list):
        return []
    out = []
    for pc in raw[:20]:
        if not isinstance(pc, dict):
            continue
        a, b = _f(pc.get("a")), _f(pc.get("b"))
        if a is None or b is None or a == 0:
            continue
        ts, te = _f(pc.get("tStart")), _f(pc.get("tEnd"))
        out.append({"a": round(a, 6), "b": round(b, 3), "tStart": ts, "tEnd": te})
    return out


def offset_from_anchors(points):
    """[[この動画の時刻, 基準動画の時刻], …](1〜2点)から {a,b} を求める。1点なら定数オフセット(a=1)。不正なら BadMark。"""
    if not isinstance(points, list) or not (1 <= len(points) <= 2):
        raise BadMark("アンカー点は1〜2点で指定してください")
    pts = []
    for p in points:
        if not (isinstance(p, (list, tuple)) and len(p) == 2):
            raise BadMark("アンカー点の形式が正しくありません")
        t_this, t_ref = _num_strict(p[0]), _num_strict(p[1])
        if t_this is None or t_ref is None or t_this < 0 or t_ref < 0:
            raise BadMark("アンカー点の時刻が正しくありません")
        pts.append((t_this, t_ref))
    if len(pts) == 1:
        a, b = 1.0, pts[0][1] - pts[0][0]
    else:
        (t1, r1), (t2, r2) = pts
        if abs(t2 - t1) < MIN_ANCHOR_GAP:
            raise BadMark("2つのアンカー点は、この動画の時刻で%d秒以上離してください" % int(MIN_ANCHOR_GAP))
        a = (r2 - r1) / (t2 - t1)
        b = r1 - a * t1
    if not (math.isfinite(a) and math.isfinite(b)):
        raise BadMark("計算できませんでした(時刻を確認してください)")
    if a < ANCHOR_A_MIN or a > ANCHOR_A_MAX:
        raise BadMark("傾きが%.1f〜%.1f倍の範囲を外れています。時刻の入力を確認してください" % (ANCHOR_A_MIN, ANCHOR_A_MAX))
    return {"a": round(a, 6), "b": round(b, 3), "tStart": None, "tEnd": None}


def _piece_for(pieces, t):
    if not pieces:
        return None
    for pc in pieces:
        lo, hi = pc.get("tStart"), pc.get("tEnd")
        if (lo is None or t >= lo) and (hi is None or t < hi):
            return pc
    return pieces[-1]   # 境界が噛み合わない場合は最後の要素で近似する


def _to_ref(g, vid, t):
    """このグループの vid の時刻 t を、基準動画の時刻に変換する。オフセット未設定なら None。"""
    if vid == g["base"]:
        return t
    pc = _piece_for(g["offsets"].get(vid) or [], t)
    return None if pc is None else pc["a"] * t + pc["b"]


def _from_ref(g, vid, t_ref):
    """基準動画の時刻 t_ref を、vid の時刻に変換する(_to_ref の逆)。オフセット未設定なら None。"""
    if vid == g["base"]:
        return t_ref
    pcs = g["offsets"].get(vid) or []
    if not pcs:
        return None
    best = None
    for pc in pcs:
        a = pc["a"]
        if not a:
            continue
        t = (t_ref - pc["b"]) / a
        lo, hi = pc.get("tStart"), pc.get("tEnd")
        if (lo is None or t >= lo) and (hi is None or t < hi):
            return t
        if best is None:
            best = t
    return best


def _new_group_id(existing):
    while True:
        gid = "g" + os.urandom(6).hex()
        if gid not in existing:
            return gid


class SeriesCache(dict):
    """動画ID → 盛り上がりグラフ。メモリにあればそれを、なければ cache/series のファイルから読む(再起動後も残る)。"""

    def __init__(self, folder):
        super().__init__()
        self.folder = folder

    def _path(self, vid):
        return os.path.join(self.folder, vid + ".json") if isinstance(vid, str) and ID_RE.match(vid) else None

    def __setitem__(self, vid, val):
        super().__setitem__(vid, val)
        p = self._path(vid)
        if not p or val is None:
            return
        try:
            os.makedirs(self.folder, exist_ok=True)
            atomic_write(p, json.dumps(val, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            files = sorted((os.path.getmtime(os.path.join(self.folder, f)), f) for f in os.listdir(self.folder) if f.endswith(".json"))
            for _, f in files[:-SERIES_KEEP]:
                os.remove(os.path.join(self.folder, f))
        except OSError:
            pass   # 保存に失敗してもメモリには残る

    def get(self, vid, default=None):
        if super().__contains__(vid):
            return super().get(vid)
        p = self._path(vid)
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                super().__setitem__(vid, d)
                return d
        except (OSError, ValueError, TypeError):
            pass
        return default

    def __contains__(self, vid):
        if super().__contains__(vid):
            return True
        p = self._path(vid)
        return bool(p) and os.path.isfile(p)

    def pop(self, vid, *default):
        p = self._path(vid)
        if p:
            try:
                os.remove(p)
            except OSError:
                pass
        return super().pop(vid, *default)


class Store:
    def __init__(self, path):
        self.path = path
        self.ui_path = os.path.join(os.path.dirname(path), "settings-ui.json")
        self.lock = threading.RLock()
        self.videos = {}
        self.groups = {}   # コラボグループ: グループID → {id, name, base, members, offsets, createdAt, updatedAt}
        self.series = SeriesCache(os.path.join(os.path.dirname(path), "cache", "series"))   # 動画ID → 盛り上がりグラフ(ファイルにも保存)
        self.warning = ""          # 起動時に見つかった問題(画面に一度だけ知らせる)
        self.corrupt_backup = ""
        self._load()

    # ---- 永続化 ----
    def _quarantine(self, copy_only=False):
        ts = time.strftime("%Y%m%d-%H%M%S")
        name, n = self.path + ".corrupt-" + ts, 0
        while os.path.exists(name):   # 既存の退避ファイルは上書きしない
            n += 1
            name = "%s.corrupt-%s-%d" % (self.path, ts, n)
        try:
            (shutil.copyfile if copy_only else os.replace)(self.path, name)
        except OSError as e:
            _warn("壊れた data.json を退避できませんでした: %s" % e)
            return ""
        return os.path.basename(name)

    def _load(self):
        try:
            with open(self.path, "rb") as f:
                raw = f.read()
        except FileNotFoundError:
            return
        except OSError as e:
            self.warning = "data.json を読み込めませんでした(%s)。空の状態で起動しました。" % (e.strerror or e)
            _warn(self.warning)
            return
        try:
            d = json.loads(raw.decode("utf-8"))
            if not isinstance(d, dict) or not isinstance(d.get("videos"), dict):
                raise ValueError("形式が違います")
        except (ValueError, UnicodeDecodeError) as e:
            name = self._quarantine()
            self.corrupt_backup = name
            self.warning = "data.json が壊れていたため、%s に退避して空の状態で起動しました(data.json.bak に1つ前の内容が残っている場合があります)。" % (name or "(退避に失敗)")
            _warn(self.warning + " 原因: %s" % str(e)[:100])
            return
        skipped = 0
        for vid, v in d["videos"].items():
            try:
                self.videos[vid] = self._load_video(vid, v)
            except Exception as e:   # 壊れた記録1件だけ捨てて続ける
                skipped += 1
                _warn("動画の記録 %r を読み込めませんでした(読み飛ばします): %s %s" % (str(vid)[:20], e.__class__.__name__, str(e)[:80]))
        gskipped = 0
        groups_raw = d.get("groups")
        if isinstance(groups_raw, dict):
            for gid, g in groups_raw.items():
                try:
                    self.groups[gid] = self._load_group(gid, g)
                except Exception as e:   # 壊れたグループ1件だけ捨てて続ける
                    gskipped += 1
                    _warn("コラボグループの記録 %r を読み込めませんでした(読み飛ばします): %s %s" % (str(gid)[:20], e.__class__.__name__, str(e)[:80]))
        if skipped or gskipped:
            name = self._quarantine(copy_only=True)
            self.corrupt_backup = name
            parts = []
            if skipped:
                parts.append("動画の記録%d件" % skipped)
            if gskipped:
                parts.append("コラボグループの記録%d件" % gskipped)
            self.warning = "data.json の壊れた%sを読み飛ばしました。元のファイルは %s に残してあります。" % ("・".join(parts), name or "(退避に失敗)")

    @staticmethod
    def _load_video(vid, v):
        if not isinstance(v, dict) or v.get("id") != vid or v.get("kind") not in ("youtube", "file"):
            raise ValueError("id/kind が正しくありません")
        if v["kind"] == "file" and not isinstance(v.get("path"), str):
            raise ValueError("path がありません")
        an = v.get("analysis")
        rev = v.get("rev")
        ci = lambda x: x if isinstance(x, int) and not isinstance(x, bool) and x > 0 else now_ms()
        return {"id": vid, "kind": v["kind"], "title": str(v.get("title") or "")[:120], "channel": str(v.get("channel") or "")[:100],
                "duration": common.num(v.get("duration"), 0, 1e6, 0.0), "fileName": str(v.get("fileName") or "")[:200] if v["kind"] == "file" else "",
                "path": v["path"] if v["kind"] == "file" else "", "marks": load_marks(v.get("marks")),
                "analysis": an if isinstance(an, dict) else None, "rev": rev if isinstance(rev, int) and not isinstance(rev, bool) and rev >= 1 else 1,
                "createdAt": ci(v.get("createdAt")), "updatedAt": ci(v.get("updatedAt"))}

    @staticmethod
    def _load_group(gid, g):
        if not isinstance(g, dict) or g.get("id") != gid or not isinstance(gid, str) or not ID_RE.match(gid):
            raise ValueError("id が正しくありません")
        members = g.get("members")
        if not isinstance(members, list) or not (2 <= len(members) <= MAX_GROUP_MEMBERS):
            raise ValueError("members が正しくありません")
        members = [str(m) for m in members]
        if len(set(members)) != len(members):
            raise ValueError("members が重複しています")
        base = g.get("base")
        if base not in members:
            raise ValueError("base が members にありません")
        offsets_raw = g.get("offsets") if isinstance(g.get("offsets"), dict) else {}
        offsets = {vid: _load_pieces(offsets_raw.get(vid)) for vid in members if vid != base}
        ci = lambda x: x if isinstance(x, int) and not isinstance(x, bool) and x > 0 else now_ms()
        return {"id": gid, "name": str(g.get("name") or "")[:120], "base": base, "members": members, "offsets": offsets,
                "createdAt": ci(g.get("createdAt")), "updatedAt": ci(g.get("updatedAt"))}

    def take_warning(self):
        """起動時の問題を1度だけ返す((メッセージ, 退避ファイル名) / ("", ""))。"""
        with self.lock:
            w, b = self.warning, self.corrupt_backup
            self.warning = self.corrupt_backup = ""
            return w, b

    def _save(self, videos, groups):
        """videos・groups をまとめて data.json に書き込み、成功したらメモリに反映する。失敗時は ApiError 500 でメモリは変えない。"""
        data = json.dumps({"schema": SCHEMA, "videos": videos, "groups": groups}, ensure_ascii=False).encode("utf-8")
        try:
            if os.path.exists(self.path):
                try:
                    shutil.copyfile(self.path, self.path + ".bak")   # 1つ前の世代(できなくても保存は続ける)
                except OSError:
                    pass
            atomic_write(self.path, data)
        except OSError:
            raise ApiError("save_failed", SAVE_ERR, 500)
        self.videos = videos
        self.groups = groups

    def _commit(self, vid, nv):
        """動画1本ぶんの新しい状態を保存する(nv=None で削除)。"""
        videos = dict(self.videos)
        if nv is None:
            videos.pop(vid, None)
        else:
            videos[vid] = nv
        self._save(videos, self.groups)

    def _commit_group(self, gid, ng):
        """グループ1件ぶんの新しい状態を保存する(ng=None で削除)。"""
        groups = dict(self.groups)
        if ng is None:
            groups.pop(gid, None)
        else:
            groups[gid] = ng
        self._save(self.videos, groups)

    # ---- 表現 ----
    @staticmethod
    def _pub(v):
        d = {k: v[k] for k in ("id", "kind", "title", "channel", "duration", "fileName", "analysis", "rev", "createdAt", "updatedAt")}
        d["marks"] = v["marks"]
        return json.loads(json.dumps(d))   # 深いコピー(呼び出し側が書き換えても内部に影響しない)

    def _summary(self, v):
        g = self._video_group(v["id"])
        return {"id": v["id"], "kind": v["kind"], "title": v["title"], "channel": v["channel"], "duration": v["duration"], "fileName": v["fileName"],
                "marks": len(v["marks"]), "autoMarks": sum(1 for m in v["marks"] if m["src"] == "auto"), "exported": sum(1 for m in v["marks"] if m["status"] == "exported"),
                "adopted": sum(1 for m in v["marks"] if m["status"] == "adopted"), "candidates": sum(1 for m in v["marks"] if m["status"] == ""),
                "updatedAt": v["updatedAt"], "rev": v["rev"], "hasSeries": v["id"] in self.series, "analysis": json.loads(json.dumps(v["analysis"])),
                "groupId": g["id"] if g else None, "groupOffsetSet": (g["base"] == v["id"] or bool(g["offsets"].get(v["id"]))) if g else None}

    # ---- 取得 ----
    def list(self):
        with self.lock:
            vs = sorted(self.videos.values(), key=lambda v: -v["updatedAt"])
            return [self._summary(v) for v in vs]

    def get(self, vid):
        """(公開用の動画, series or None)。無ければ ApiError 404。"""
        with self.lock:
            v = self.videos.get(str(vid or ""))
            if not v:
                raise ApiError("not_found", "動画が見つかりません", 404)
            return self._pub(v), self.series.get(v["id"])

    def internal(self, vid):
        """サーバー内部用(path を含む)のコピー。無ければ None。"""
        with self.lock:
            v = self.videos.get(str(vid or ""))
            return None if not v else dict(self._pub(v), path=v["path"])

    def media_path(self, vid):
        """/media 用: 登録済みの file 動画の実パス。それ以外は None。"""
        with self.lock:
            v = self.videos.get(str(vid or ""))
            return v["path"] if v and v["kind"] == "file" and v["path"] else None

    def has(self, vid):
        with self.lock:
            return vid in self.videos

    # ---- 登録・削除 ----
    def ensure(self, src, title="", channel="", probe=False):
        """動画を(なければ作って)返す。src は analyze.validate_source の結果。probe=True でファイルの長さを確認(読めなければ 400)。"""
        vid = src["videoId"]
        dur = 0.0
        if src["kind"] == "file" and probe and not self.has(vid):
            d, has_v, has_a, _l = common.media_info(src["path"])
            if common.find_tool("ffmpeg") and d is None:
                raise ApiError("bad_source", "動画・音声として読み取れないファイルです", 400)
            dur = float(d or 0)
        with self.lock:
            v = self.videos.get(vid)
            if v is not None and v["kind"] != src["kind"]:
                raise ApiError("conflict", "同じIDの別の動画があります", 409)
            if v is None:
                nv = {"id": vid, "kind": src["kind"], "title": "", "channel": "", "duration": dur, "fileName": "", "path": "", "marks": [], "analysis": None, "rev": 1,
                      "createdAt": now_ms(), "updatedAt": now_ms()}
                if src["kind"] == "file":
                    nv["fileName"] = os.path.basename(src["path"])[:200]
                    nv["path"] = src["path"]
                    nv["title"] = os.path.splitext(nv["fileName"])[0][:120]
            else:
                nv = copy.deepcopy(v)
            t, ch = str(title or "").strip()[:120], str(channel or "").strip()[:100]
            if v is not None and ((t and t != nv["title"]) or (ch and ch != nv["channel"])):
                nv["rev"] += 1
            nv["title"] = t or nv["title"]      # 空のタイトル・チャンネルで既存の値を消さない
            nv["channel"] = ch or nv["channel"]
            self._commit(vid, nv)
            return self._pub(nv)

    def delete(self, vid):
        with self.lock:
            vid = str(vid or "")
            if vid not in self.videos:
                return False
            self._commit(vid, None)
            self.series.pop(vid, None)
            g = self._video_group(vid)
            if g:
                try:
                    self.remove_member(g["id"], vid)   # コラボグループからも外す(転写済みマークは他の動画に残す)
                except ApiError:
                    pass
            return True

    # ---- マークの置き換え(確認画面からの保存) ----
    def put_video(self, vid, title, marks_raw, base_rev=None):
        if not isinstance(marks_raw, list):
            raise ApiError("bad_request", "marks が正しくありません", 400)
        if base_rev is not None and (not isinstance(base_rev, int) or isinstance(base_rev, bool)):
            raise ApiError("bad_request", "baseRev が正しくありません", 400)
        with self.lock:
            v = self.videos.get(str(vid or ""))
            if not v:
                raise ApiError("not_found", "動画が見つかりません", 404)
            if base_rev is not None and base_rev != v["rev"]:   # 別の更新(解析・書き出し・別タブ)が先に入っている: 何も変えない
                raise ApiError("conflict", "解析や書き出しで内容が更新されています。最新の内容を読み込み直してください", 409, {"video": self._pub(v), "series": self.series.get(v["id"])})
            new = validate_marks(marks_raw, v["marks"])   # 1件でも不正なら 400(何も変えない)
            ids = {m["id"] for m in new}
            old_by = {m["id"]: m for m in v["marks"]}
            # 判定を記録: 採用 = よかった / 不採用 = ちがう / 候補のまま削除 = ちがう(判定済みの削除は二重に記録しない)。
            # 自動マークは上の全部。手動マーク(自分で見つけた区間)は、採用・不採用にしたときだけ(手動の削除は記録しない)
            verdicts = []
            for m in v["marks"]:
                if m["src"] == "auto" and m["id"] not in ids and m["status"] == "":
                    verdicts.append((m, "bad", "delete"))
            for m in new:
                o = old_by.get(m["id"])
                changed = (m["status"] != o["status"]) if o is not None else (m["status"] in ("adopted", "rejected"))
                if changed and (o is not None or m["src"] == "manual"):
                    if m["status"] == "adopted":
                        verdicts.append((m, "good", "adopt"))
                    elif m["status"] == "rejected":
                        verdicts.append((m, "bad", "reject"))
            nv = copy.deepcopy(v)
            nv["marks"] = new
            if isinstance(title, str):   # 空文字はタイトルを消す
                nv["title"] = title.strip()[:120]
            nv["rev"] += 1
            nv["updatedAt"] = now_ms()
            self._commit(nv["id"], nv)   # 保存に成功したときだけ、feedback を書く
            snap = self._pub(nv)
        for m, verdict, event in verdicts:
            analyze.feedback_for_mark(snap, m, verdict, event)
            if event == "adopt":   # コラボグループに入っていれば、他の動画へ候補として転写する
                self._transfer_collab(vid, m)
        return snap

    def set_title(self, vid, title):
        with self.lock:
            v = self.videos.get(vid)
            if v and title and not v["title"]:
                nv = copy.deepcopy(v)
                nv["title"] = str(title)[:120]
                nv["rev"] += 1
                self._commit(vid, nv)

    def replace_auto(self, vid, cands, analysis, duration, series):
        """解析結果を反映する。手を入れていない・書き出していない自動マークだけを置き換える。
        手を入れた自動マーク(書き出し済み / ラベルあり / 時刻を動かした)は手動マークとして残す(点数・理由は保持)。
        新しい自動マークは、残したマークと同じ区間(±0.5秒)なら作らない。戻り値は新しい自動マークの数(動画が消えていれば None)。"""
        with self.lock:
            v = self.videos.get(vid)
            if not v:
                return None
            kept = []
            for m in v["marks"]:
                if m["src"] != "auto":
                    kept.append(m)
                elif _touched(m):
                    k = dict(m, src="manual")
                    k.pop("auto0", None)
                    kept.append(k)
            autos = []
            for c in cands:
                try:
                    s, e = check_times(c["start"], c["end"])   # 手動と同じ規則(長さの上限など)
                except (BadMark, KeyError, TypeError):
                    continue
                m = _build_mark({"id": "a" + os.urandom(5).hex(), "start": s, "end": e, "label": "", "live": False, "createdAt": now_ms()}, None)
                m.update({"src": "auto", "score": _f(c.get("score")), "reasons": [str(r)[:40] for r in (c.get("reasons") or [])][:6], "peak": _f(c.get("peak")),
                          "parts": {k: round(_f(x), 2) for k, x in (c.get("parts") or {}).items() if k in PART_KEYS and _f(x) is not None}, "auto0": [s, e]})
                if any(_same(m, o) for o in kept + autos):
                    continue
                autos.append(m)
            if len(kept) + len(autos) > MAX_MARKS:   # 残したマークを優先し、自動を減らす
                autos = sorted(autos, key=lambda m: -(m["score"] or 0))[:max(0, MAX_MARKS - len(kept))]
            nv = copy.deepcopy(v)
            nv["marks"] = sorted(kept + autos, key=lambda m: (m["start"], m["end"]))[:MAX_MARKS]
            nv["analysis"] = analysis
            nv["rev"] += 1
            if duration and duration > 0:
                nv["duration"] = round(float(duration), 2)
            nv["updatedAt"] = now_ms()
            self._commit(vid, nv)
            self.series[vid] = series
            return len(autos)

    def mark_exported(self, vid, mark_id, relfile):
        """書き出し成功: マークを exported にして保存。自動マークで初めての成功なら「よかった」を記録。"""
        fb = None
        with self.lock:
            v = self.videos.get(vid)
            m = next((x for x in v["marks"] if x["id"] == mark_id), None) if v else None
            if not m:
                return False
            first = m["status"] != "exported"
            nv = copy.deepcopy(v)
            nm = next(x for x in nv["marks"] if x["id"] == mark_id)
            nm["status"], nm["file"] = "exported", str(relfile)[:300]
            nv["rev"] += 1
            nv["updatedAt"] = now_ms()
            self._commit(vid, nv)
            if first:   # 自動・手動どちらも、初めて書き出したときに「よかった」(最終の区間と、手で直した量つき)
                fb = (self._pub(nv), dict(nm))
        if fb:
            analyze.feedback_for_mark(fb[0], fb[1], "good", "export")
        return True

    # ---- コラボ動画のマーク転写(グループ) ----
    def _video_group(self, vid):
        """vid が入っているグループ(なければ None)。呼び出し側で self.lock を取っていること。"""
        for g in self.groups.values():
            if vid in g["members"]:
                return g
        return None

    def _group_summary(self, g):
        members = []
        for vid in g["members"]:
            v = self.videos.get(vid)
            is_base = vid == g["base"]
            pcs = None if is_base else (g["offsets"].get(vid) or None)
            off = {"a": pcs[0]["a"], "b": pcs[0]["b"]} if pcs else None
            members.append({"id": vid, "title": (v["title"] or v["fileName"]) if v else "", "kind": v["kind"] if v else "", "exists": v is not None,
                             "isBase": is_base, "offsetSet": is_base or off is not None, "offset": off})
        return {"id": g["id"], "name": g["name"], "base": g["base"], "members": members,
                "allSet": all(m["offsetSet"] for m in members), "createdAt": g["createdAt"], "updatedAt": g["updatedAt"]}

    def list_groups(self):
        with self.lock:
            return [self._group_summary(g) for g in sorted(self.groups.values(), key=lambda g: -g["updatedAt"])]

    def get_group(self, gid):
        with self.lock:
            g = self.groups.get(str(gid or ""))
            if not g:
                raise ApiError("not_found", "グループが見つかりません", 404)
            return self._group_summary(g)

    @staticmethod
    def _clean_ids(video_ids):
        if not isinstance(video_ids, list):
            raise ApiError("bad_request", "動画を指定してください", 400)
        out, seen = [], set()
        for x in video_ids:
            x = str(x or "") if not isinstance(x, bool) else ""
            if x and x not in seen:
                seen.add(x)
                out.append(x)
        return out

    def create_group(self, video_ids, name="", base=None):
        ids = self._clean_ids(video_ids)
        if len(ids) < 2:
            raise ApiError("bad_request", "コラボにまとめるには2本以上選んでください", 400)
        if len(ids) > MAX_GROUP_MEMBERS:
            raise ApiError("bad_request", "1つのグループにまとめられるのは%d本までです" % MAX_GROUP_MEMBERS, 400)
        base = str(base or "") or ids[0]
        if base not in ids:
            raise ApiError("bad_request", "基準の動画は選んだ動画の中から指定してください", 400)
        with self.lock:
            if len(self.groups) >= MAX_GROUPS:
                raise ApiError("too_many", "グループは%d件までです" % MAX_GROUPS, 400)
            for vid in ids:
                v = self.videos.get(vid)
                if not v:
                    raise ApiError("not_found", "動画が見つかりません(%s)" % vid, 404)
                if self._video_group(vid):
                    raise ApiError("conflict", "「%s」はすでに別のコラボグループに入っています" % (v["title"] or vid), 409)
            gid = _new_group_id(self.groups)
            now = now_ms()
            g = {"id": gid, "name": str(name or "").strip()[:120], "base": base, "members": ids,
                 "offsets": {vid: [] for vid in ids if vid != base}, "createdAt": now, "updatedAt": now}
            self._commit_group(gid, g)
            return self._group_summary(g)

    def add_members(self, gid, video_ids):
        ids = self._clean_ids(video_ids)
        with self.lock:
            g = self.groups.get(str(gid or ""))
            if not g:
                raise ApiError("not_found", "グループが見つかりません", 404)
            new = [v for v in ids if v not in g["members"]]
            if not new:
                raise ApiError("bad_request", "追加する動画がありません", 400)
            if len(g["members"]) + len(new) > MAX_GROUP_MEMBERS:
                raise ApiError("bad_request", "1つのグループにまとめられるのは%d本までです" % MAX_GROUP_MEMBERS, 400)
            for vid in new:
                v = self.videos.get(vid)
                if not v:
                    raise ApiError("not_found", "動画が見つかりません(%s)" % vid, 404)
                other = self._video_group(vid)
                if other:
                    raise ApiError("conflict", "「%s」はすでに別のコラボグループに入っています" % (v["title"] or vid), 409)
            ng = dict(g, members=g["members"] + new, offsets=dict(g["offsets"]), updatedAt=now_ms())
            for vid in new:
                ng["offsets"][vid] = []
            self._commit_group(g["id"], ng)
            return self._group_summary(ng)

    def remove_member(self, gid, vid):
        """メンバーを外す。基準の動画を外す・残り1本になる場合はグループごと削除する(ズレの基準がなくなるため)。
        すでに転写済みのマークは(既存の動画削除と同様)消さずに残す。戻り値: 残ったグループ(削除したときは None)。"""
        with self.lock:
            g = self.groups.get(str(gid or ""))
            if not g:
                raise ApiError("not_found", "グループが見つかりません", 404)
            vid = str(vid or "")
            if vid not in g["members"]:
                raise ApiError("not_found", "そのグループにその動画はありません", 404)
            if vid == g["base"] or len(g["members"]) <= 2:
                self._commit_group(g["id"], None)
                return None
            members = [m for m in g["members"] if m != vid]
            offsets = {k: v for k, v in g["offsets"].items() if k != vid}
            ng = dict(g, members=members, offsets=offsets, updatedAt=now_ms())
            self._commit_group(g["id"], ng)
            return self._group_summary(ng)

    def delete_group(self, gid):
        with self.lock:
            gid = str(gid or "")
            if gid not in self.groups:
                return False
            self._commit_group(gid, None)
            return True

    def set_anchor(self, gid, vid, points):
        with self.lock:
            g = self.groups.get(str(gid or ""))
            if not g:
                raise ApiError("not_found", "グループが見つかりません", 404)
            vid = str(vid or "")
            if vid not in g["members"]:
                raise ApiError("not_found", "そのグループにその動画はありません", 404)
            if vid == g["base"]:
                raise ApiError("bad_request", "基準の動画にはズレの指定は不要です", 400)
            try:
                piece = offset_from_anchors(points)
            except BadMark as e:
                raise ApiError("bad_anchor", str(e), 400)
            ng = dict(g, offsets=dict(g["offsets"]), updatedAt=now_ms())
            ng["offsets"][vid] = [piece]
            self._commit_group(g["id"], ng)
            return self._group_summary(ng)

    def _transfer_collab(self, vid, mark):
        """採用されたマークを、同じグループの他の動画へ「候補」として転写する(自動採用はしない)。"""
        with self.lock:
            g = self._video_group(vid)
            if not g:
                return
            t_ref_s, t_ref_e = _to_ref(g, vid, mark["start"]), _to_ref(g, vid, mark["end"])
            if t_ref_s is None or t_ref_e is None:   # この動画のズレが未設定なら転写できない
                return
            targets = []
            for other in g["members"]:
                if other == vid:
                    continue
                ts, te = _from_ref(g, other, t_ref_s), _from_ref(g, other, t_ref_e)
                if ts is None or te is None:   # 相手のズレが未設定
                    continue
                targets.append((other, ts - COLLAB_MARGIN, te + COLLAB_MARGIN))
        for other, s, e in targets:
            self._add_collab_candidate(other, vid, mark["id"], s, e)

    def _add_collab_candidate(self, vid, from_vid, from_mark_id, s_raw, e_raw):
        """転写先に候補マークを1件作る。ただし、その位置に既にマーク(手動・自動・採用済みなど何でもよい)が
        あるなら、新規には作らず既存のマークへ統合する: 開始・終了は両方の区間を覆うように広げ(狭める方向には
        動かさない)、由来を理由欄に足す。判定(採用/不採用)は変えない。ただし書き出し済みマークは、範囲が
        実際に広がった場合は他の時刻編集と同様に「採用」へ戻す(書き出し済みファイルは古い範囲のものになるため)。
        重複した候補で一覧が埋まるのを防ぐのが狙い。"""
        with self.lock:
            v = self.videos.get(vid)
            if not v:
                return
            already = any((m.get("collabFrom") or {}).get("markId") == from_mark_id and (m.get("collabFrom") or {}).get("videoId") == from_vid for m in v["marks"])
            if already:
                return
            try:
                s, e = check_times(max(0.0, s_raw), e_raw)
            except BadMark:
                return
            if v["duration"] and v["duration"] > 0:
                e = min(e, round(float(v["duration"]), 1))
                if e <= s:
                    return
            from_title = (self.videos.get(from_vid) or {}).get("title") or from_vid
            note = ("コラボ転写(元: %s)" % from_title)[:40]
            similar = next((x for x in v["marks"] if _overlaps(s, e, x["start"], x["end"])), None)
            if similar is not None:
                try:
                    new_s, new_e = check_times(min(similar["start"], s), max(similar["end"], e))
                except BadMark:
                    new_s, new_e = similar["start"], similar["end"]   # 広げると長さ上限を超える等の異常時は広げない(安全側)
                moved = abs(new_s - similar["start"]) > EDIT_TOL or abs(new_e - similar["end"]) > EDIT_TOL
                note_needed = note not in similar["reasons"]
                if moved or note_needed:
                    nv = copy.deepcopy(v)
                    target = next(x for x in nv["marks"] if x["id"] == similar["id"])
                    target["start"], target["end"] = new_s, new_e
                    if note_needed:
                        target["reasons"] = (target["reasons"] + [note])[:6]
                    if moved and target["status"] == "exported":
                        target["status"], target["file"] = "adopted", ""
                    nv["rev"] += 1
                    nv["updatedAt"] = now_ms()
                    self._commit(vid, nv)
                return
            if len(v["marks"]) >= MAX_MARKS:
                return
            m = _build_mark({"id": "c" + os.urandom(5).hex(), "start": s, "end": e, "label": "", "live": False, "createdAt": now_ms()}, None)
            m.update({"src": "collab", "reasons": [note], "collabFrom": {"videoId": from_vid, "markId": from_mark_id}, "auto0": [s, e]})
            nv = copy.deepcopy(v)
            nv["marks"] = sorted(nv["marks"] + [m], key=lambda x: (x["start"], x["end"]))[:MAX_MARKS]
            nv["rev"] += 1
            nv["updatedAt"] = now_ms()
            self._commit(vid, nv)

    # ---- 画面の設定(不透明な辞書) ----
    def get_ui(self):
        try:
            with open(self.ui_path, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def set_ui(self, d):
        if not isinstance(d, dict):
            raise ApiError("bad_request", "settings は辞書で指定してください", 400)
        raw = json.dumps(d, ensure_ascii=False).encode("utf-8")
        if len(raw) > 32 * 1024:
            raise ApiError("too_large", "設定が大きすぎます(32KBまで)", 413)
        with self.lock:
            try:
                atomic_write(self.ui_path, raw)
            except OSError:
                raise ApiError("save_failed", SAVE_ERR, 500)
