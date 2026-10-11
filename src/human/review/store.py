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
import shutil
import sys
import threading
import time

from ytt import fsio as _fsio, marks as _marks, mediainfo as _media, schemas, settings as _settings, studio_env as _env, yturl as _yturl  # noqa: E402  (check_live・LIVE_NO_ANALYZE は RS6 a-5a で ytt/yturl へ・prune_cache は ytt/fsio へ)
# マークの純粋な語彙(検査・整形・同じ区間・手を入れたか)は RS8 B3-2 で ytt/marks へ下ろした。下の名前は今までどおり store からも読める
from ytt.marks import BadMark, EDIT_TOL, ID_RE, MAX_MARKS, check_times, load_marks  # noqa: E402,F401

from flow import adopt as _flow_adopt  # noqa: E402  採用の規則 F-5 の口(① pipeline/analyze/adopt。RS8 B3-2 の G1a)
from . import feedback  # noqa: E402  判定の記録(RS3-5 に analyze から隣へ。呼ぶたびに feedback.名前 で読む)
from ytt.errors import ApiError  # noqa: E402
from ytt.textutil import num  # noqa: E402  純粋な関数

SCHEMA = "clip-studio/v1"
# 作業データが壊れていたときの戻し方(画面の帯に出す。退避したファイルの名前・フォルダは画面の「詳しく」に出す。見直し M8)
RESTORE_STEPS = "前のデータは退避してあります。戻すには: ホームで「すべて終了」→ 退避したファイルの名前を元に戻す(下の「詳しく」)→ start.bat で起動し直す"
SERIES_KEEP = 60
SAVE_ERR = "保存に失敗しました(ディスクの空きなど)"
UI_MAX_BYTES = 32 * 1024   # 画面の設定 settings-ui.json の大きさの上限

# ---- コラボ動画のマーク転写(グループ+オフセット) ----
MAX_GROUPS = 50
MAX_GROUP_MEMBERS = 8
COLLAB_MARGIN = 2.5     # 転写した区間を前後に広げる秒数(反応のタイミングは人によってずれるため)
ANCHOR_A_MIN, ANCHOR_A_MAX = 0.5, 1.5   # アンカー点から求めた傾き(ドリフト補正)の妥当な範囲。外れたら入力ミスの可能性が高い
MIN_ANCHOR_GAP = 20.0   # 2点指定のとき、この動画の時刻でこれ以上離れていることを要求する(近すぎると傾きが不安定)


def _warn(msg):
    sys.stderr.write("[store] " + msg + "\n")


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
            c = _marks.build_mark(m, old.get(mid))
        except BadMark as e:
            raise ApiError("bad_marks", "%s(id: %s)が正しくありません: %s" % (where, mid, e), 400)
        seen.add(mid)
        out.append(c)
    return out


# ---- コラボグループの時刻対応(t_ref = a * t_this + b。区分的な配列を持てるが、v0 は要素1つだけ作る) ----
def _load_pieces(raw):
    """保存済みの区分的オフセット配列を検査する。壊れた要素は読み飛ばす。"""
    if not isinstance(raw, list):
        return []
    out = []
    for pc in raw[:20]:
        if not isinstance(pc, dict):
            continue
        a, b = _marks.fnum(pc.get("a")), _marks.fnum(pc.get("b"))
        if a is None or b is None or a == 0:
            continue
        ts, te = _marks.fnum(pc.get("tStart")), _marks.fnum(pc.get("tEnd"))
        out.append({"a": round(a, 6), "b": round(b, 3), "tStart": ts, "tEnd": te})
    return out


def offset_from_anchors(points):
    """[[この動画の時刻, 基準動画の時刻], …](1〜2点)から {a,b} を求める。1点なら定数オフセット(a=1)。不正なら BadMark。"""
    if not isinstance(points, list) or not (1 <= len(points) <= 2):
        raise BadMark("アンカーは1〜2点で指定してください")
    pts = []
    for p in points:
        if not (isinstance(p, (list, tuple)) and len(p) == 2):
            raise BadMark("アンカーの形式が正しくありません")
        t_this, t_ref = _marks.num_strict(p[0]), _marks.num_strict(p[1])
        if t_this is None or t_ref is None or t_this < 0 or t_ref < 0:
            raise BadMark("アンカーの時刻が正しくありません")
        pts.append((t_this, t_ref))
    if len(pts) == 1:
        a, b = 1.0, pts[0][1] - pts[0][0]
    else:
        (t1, r1), (t2, r2) = pts
        if abs(t2 - t1) < MIN_ANCHOR_GAP:
            raise BadMark("2つのアンカーは、この配信の時刻で%d秒以上離してください" % int(MIN_ANCHOR_GAP))   # 用語は「アンカー」(2 周目 S20)
        a = (r2 - r1) / (t2 - t1)
        b = r1 - a * t1
    if not (math.isfinite(a) and math.isfinite(b)):
        raise BadMark("計算できませんでした(時刻を確認してください)")
    if a < ANCHOR_A_MIN or a > ANCHOR_A_MAX:
        raise BadMark("傾きが%.1f〜%.1f倍の範囲を外れています。時刻の入力を確認してください" % (ANCHOR_A_MIN, ANCHOR_A_MAX))
    return {"a": round(a, 6), "b": round(b, 3), "tStart": None, "tEnd": None}


def _in_piece(pc, t):
    """t がオフセットの区分 pc(tStart 以上 tEnd 未満。None は端なし)の中か"""
    lo, hi = pc.get("tStart"), pc.get("tEnd")
    return (lo is None or t >= lo) and (hi is None or t < hi)


def _piece_for(pieces, t):
    if not pieces:
        return None
    for pc in pieces:
        if _in_piece(pc, t):
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
        if _in_piece(pc, t):
            return t
        if best is None:
            best = t
    return best


def _new_group_id(existing):
    while True:
        gid = "g" + os.urandom(6).hex()
        if gid not in existing:
            return gid


def _load_each(raw, out, load, what):
    """data.json の videos / groups を1件ずつ読んで out に入れる。壊れた記録はその1件だけ捨てて続ける。捨てた数を返す"""
    skipped = 0
    for key, val in raw.items():
        try:
            out[key] = load(key, val)
        except Exception as e:
            skipped += 1
            _warn("%s %r を読み込めませんでした(読み飛ばします): %s %s" % (what, str(key)[:20], e.__class__.__name__, str(e)[:80]))
    return skipped


def _replaced(d, key, val):
    """d の写しの key を val にする(val=None なら消す)。メモリの辞書は保存に成功するまで変えない"""
    d = dict(d)
    if val is None:
        d.pop(key, None)
    else:
        d[key] = val
    return d


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
            _fsio.atomic_write(p, json.dumps(val, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))   # フォルダは atomic_write が作る
        except OSError:
            return   # 保存に失敗してもメモリには残る
        _fsio.prune_cache(self.folder, "*.json", SERIES_KEEP)   # 古いものから消して SERIES_KEEP 本に

    def get(self, vid, default=None):
        if super().__contains__(vid):
            return super().get(vid)
        p = self._path(vid)
        d = _fsio.read_json_or(p, kind=dict) if p else None
        if d is not None:
            super().__setitem__(vid, d)
            return d
        return default

    def __contains__(self, vid):
        if super().__contains__(vid):
            return True
        p = self._path(vid)
        return bool(p) and os.path.isfile(p)

    def pop(self, vid, *default):
        p = self._path(vid)
        if p:
            _fsio.unlink_quiet(p)
        return super().pop(vid, *default)


class Store:
    def __init__(self, path):
        self.path = path
        self.ui_path = os.path.join(os.path.dirname(path), "settings-ui.json")
        self.lock = threading.RLock()
        # 画面の設定(読む・書く・退避・大きさの上限は ytt.settings.SettingsFile。ホーム・編集の設定ファイルと同じ決まり。S4 2026-10-09)
        self.ui_file = _settings.SettingsFile(self.ui_path, max_bytes=UI_MAX_BYTES, writer=lambda p, b: _fsio.atomic_write(p, b), indent=None, lock=self.lock)
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
            # 画面に出す文は「何が起きたか + どうすればいいか」。原因・ファイル名はログへ(見直し M8)
            self.warning = "作業データ(マークの記録)を読み込めなかったので、空の状態で起動しました。ほかのソフトがファイルを開いていると起きます。ホームで「すべて終了」を押してから start.bat で起動し直してください"
            _warn("data.json を読み込めませんでした(%s)。空の状態で起動しました" % (e.strerror or e))
            return
        try:
            d = json.loads(raw.decode("utf-8"))
            if not isinstance(d, dict) or not isinstance(d.get("videos"), dict):
                raise ValueError("形式が違います")
        except (ValueError, UnicodeDecodeError) as e:
            name = self._quarantine()
            self.corrupt_backup = name
            self.warning = ("作業データ(マークの記録)が壊れていたので、空の状態で起動しました。" + (RESTORE_STEPS if name else "壊れたファイルを退避できませんでした。マークを付ける前に、ホームで「すべて終了」を押してから start.bat で起動し直してください"))
            _warn("data.json が壊れていたため %s に退避して空の状態で起動しました。原因: %s" % (name or "(退避に失敗)", str(e)[:100]))
            return
        skipped = _load_each(d["videos"], self.videos, self._load_video, "配信の記録")
        groups_raw = d.get("groups")
        gskipped = _load_each(groups_raw, self.groups, self._load_group, "コラボの記録") if isinstance(groups_raw, dict) else 0
        if skipped or gskipped:
            name = self._quarantine(copy_only=True)
            self.corrupt_backup = name
            parts = []
            if skipped:
                parts.append("配信の記録 %d 件" % skipped)
            if gskipped:
                parts.append("コラボの記録 %d 件" % gskipped)
            self.warning = "作業データ(マークの記録)の一部(%s)が壊れていたので、読み飛ばしました。" % "・".join(parts) + (RESTORE_STEPS if name else "")
            _warn("data.json の壊れた%sを読み飛ばしました。元のファイルは %s" % ("・".join(parts), name or "(退避に失敗)"))

    @staticmethod
    def _load_video(vid, v):
        if not isinstance(v, dict) or v.get("id") != vid or v.get("kind") not in ("youtube", "file", "live"):
            raise ValueError("id/kind が正しくありません")
        if v["kind"] == "file" and not isinstance(v.get("path"), str):
            raise ValueError("path がありません")
        live = None
        if v["kind"] == "live":   # ライブの録画: id は録画の id と同じ。形が合わなければこの1件だけ読み飛ばす
            try:
                live = _yturl.check_live(v.get("live"))
            except ApiError as e:
                raise ValueError("live が正しくありません: %s" % e.message)
            if live["recording"] != vid:
                raise ValueError("live の録画 ID が id と違います")
        an = v.get("analysis")
        out = {"id": vid, "kind": v["kind"], "title": str(v.get("title") or "")[:120], "channel": str(v.get("channel") or "")[:100],
               "duration": num(v.get("duration"), 0, 1e6, 0.0), "fileName": str(v.get("fileName") or "")[:200] if v["kind"] == "file" else "",
               "path": v["path"] if v["kind"] == "file" else "", "marks": _marks.drop_archived(load_marks(v.get("marks")), v["kind"]),
               "analysis": an if isinstance(an, dict) else None, "rev": v["rev"] if _marks.pos_int(v.get("rev")) else 1,
               "createdAt": _marks.ms_or_now(v.get("createdAt")), "updatedAt": _marks.ms_or_now(v.get("updatedAt"))}
        if live:
            out["live"] = live   # live のときだけ持つキー(youtube・file の記録の形は変えない)
        return out

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
        return {"id": gid, "name": str(g.get("name") or "")[:120], "base": base, "members": members, "offsets": offsets,
                "createdAt": _marks.ms_or_now(g.get("createdAt")), "updatedAt": _marks.ms_or_now(g.get("updatedAt"))}

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
            _fsio.atomic_write(self.path, data)
        except OSError as e:
            _env.log_failure("動画・マークの保存", e)
            raise ApiError("save_failed", SAVE_ERR, 500)
        self.videos = videos
        self.groups = groups

    def _commit(self, vid, nv):
        """動画1本ぶんの新しい状態を保存する(nv=None で削除)。"""
        self._save(_replaced(self.videos, vid, nv), self.groups)

    def _commit_group(self, gid, ng):
        """グループ1件ぶんの新しい状態を保存する(ng=None で削除)。"""
        self._save(self.videos, _replaced(self.groups, gid, ng))

    def _bump(self, nv):
        """動画の新しい状態(nv)の版を上げて保存する。"""
        nv["rev"] += 1
        nv["updatedAt"] = schemas.now_ms()
        self._commit(nv["id"], nv)

    def _need(self, vid):
        """登録済みの動画(内部の形)。無ければ ApiError 404。self.lock を取っていること"""
        v = self.videos.get(str(vid or ""))
        if not v:
            raise ApiError("not_found", "配信が見つかりません", 404)
        return v

    # ---- 表現 ----
    @staticmethod
    def _pub(v):
        d = {k: v[k] for k in ("id", "kind", "title", "channel", "duration", "fileName", "analysis", "rev", "createdAt", "updatedAt")}
        d["marks"] = v["marks"]
        if v["kind"] == "live":
            d["live"] = v["live"]
        return json.loads(json.dumps(d))   # 深いコピー(呼び出し側が書き換えても内部に影響しない)

    def _summary(self, v):
        g = self._video_group(v["id"])
        d = {"id": v["id"], "kind": v["kind"], "title": v["title"], "channel": v["channel"], "duration": v["duration"], "fileName": v["fileName"],
             "marks": len(v["marks"]), "autoMarks": sum(1 for m in v["marks"] if m["src"] == "auto"), "exported": sum(1 for m in v["marks"] if m["status"] == "exported"),
             "adopted": sum(1 for m in v["marks"] if m["status"] == "adopted"), "candidates": sum(1 for m in v["marks"] if m["status"] == ""),
             "createdAt": v["createdAt"], "updatedAt": v["updatedAt"], "rev": v["rev"], "hasSeries": v["id"] in self.series, "analysis": json.loads(json.dumps(v["analysis"])),
             "groupId": g["id"] if g else None, "groupOffsetSet": (g["base"] == v["id"] or bool(g["offsets"].get(v["id"]))) if g else None}
        if v["kind"] == "live":
            d["live"] = dict(v["live"])
            d["archived"] = sum(1 for m in v["marks"] if m.get("archived"))   # 本番版に入れ替え済みのマークの数(線 D の P4)
        return d

    # ---- 取得 ----
    def list(self):
        with self.lock:
            vs = sorted(self.videos.values(), key=lambda v: -v["updatedAt"])
            return [self._summary(v) for v in vs]

    def get(self, vid):
        """(公開用の動画, series or None)。無ければ ApiError 404。"""
        with self.lock:
            v = self._need(vid)
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
        """動画を(なければ作って)返す。src は flow.ingest.probe(analyze.validate_source)の結果。probe=True でファイルの長さを確認(読めなければ 400)。"""
        vid = src["videoId"]
        dur = 0.0
        if src["kind"] == "file" and probe and not self.has(vid):
            d = _media.media_info(src["path"])[0]
            if _env.find_tool("ffmpeg") and d is None:
                raise ApiError("bad_source", "動画・音声として読み取れないファイルです", 400)
            dur = float(d or 0)
        with self.lock:
            v = self.videos.get(vid)
            if v is not None and v["kind"] != src["kind"]:
                raise ApiError("conflict", "同じ ID の別の配信があります", 409)
            if v is None:
                nv = {"id": vid, "kind": src["kind"], "title": "", "channel": "", "duration": dur, "fileName": "", "path": "", "marks": [], "analysis": None, "rev": 1,
                      "createdAt": schemas.now_ms(), "updatedAt": schemas.now_ms()}
                if src["kind"] == "file":
                    nv["fileName"] = os.path.basename(src["path"])[:200]
                    nv["path"] = src["path"]
                    nv["title"] = os.path.splitext(nv["fileName"])[0][:120]
                elif src["kind"] == "live":
                    nv["live"] = dict(src["live"])
            else:
                nv = copy.deepcopy(v)
            t, ch = str(title or "").strip()[:120], str(channel or "").strip()[:100]
            if v is not None and v["kind"] == "live":   # 録画の登録は何度来てもよい: 既にあれば、題・チャンネル名は空のときだけ新しい値を入れる(録画の情報は変えない)
                t = t if not nv["title"] else ""
                ch = ch if not nv.get("channel") else ""
                if not (t or ch):
                    return self._pub(v)
                nv["rev"] += 1
            elif v is not None and ((t and t != nv["title"]) or (ch and ch != nv["channel"])):
                nv["rev"] += 1
            nv["title"] = t or nv["title"]      # 空のタイトル・チャンネルで既存の値を消さない
            nv["channel"] = ch or nv["channel"]
            self._commit(vid, nv)
            return self._pub(nv)

    def delete(self, vid, if_no_marks=False):
        """if_no_marks: マークが1つでもあれば消さない(409。入口の「マークの無い録画を消す」= 線 D の P4。確かめてから消すまでの間に付いたマークを消さない)"""
        with self.lock:
            vid = str(vid or "")
            if vid not in self.videos:
                return False
            if if_no_marks and self.videos[vid].get("marks"):
                raise ApiError("has_marks", "マークがあるので消しません", 409)
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
        if base_rev is not None and not schemas.is_int(base_rev):
            raise ApiError("bad_request", "baseRev が正しくありません", 400)
        with self.lock:
            v = self._need(vid)
            if base_rev is not None and base_rev != v["rev"]:   # 別の更新(解析・書き出し・別タブ)が先に入っている: 何も変えない
                raise ApiError("conflict", "解析や書き出しで内容が更新されています。最新の内容を読み込み直してください", 409, {"video": self._pub(v), "series": self.series.get(v["id"])})
            new = validate_marks(marks_raw, v["marks"])   # 1件でも不正なら 400(何も変えない)
            ids = {m["id"] for m in new}
            old_by = {m["id"]: m for m in v["marks"]}
            # 判定を記録: 採用 = よかった / 不採用 = ちがう / 候補のまま削除 = ちがう。
            # 自動マークは上の全部。手動マーク(自分で見つけた区間)は、採用・不採用にしたときだけ good / bad。
            # それとは別に、人の最終の操作を記録する(Q2。verdict は miss / unmiss / retract。feedback.FB_EXTRA_EVENTS):
            # 手で足した = 自動の見逃し(その時いちばん近い自動マークの点数と距離つき)・手で足した候補を消した・採用を取り消した・判定済みを削除した。
            # まとめて実行(adopt_top・request_marks)は put_video を通らないので書かれない(人の判断ではないため)
            verdicts = []
            extras = []
            for m in v["marks"]:
                if m["id"] in ids:
                    continue
                if m["status"] == "":
                    if m["src"] == "auto" or m.get("auto0Orig"):   # 候補のままの自動マーク(再解析で手動に変わったものも元は自動)
                        verdicts.append((m, "bad", "delete"))
                    elif m["src"] == "manual":
                        extras.append((m, "manual_remove", {}))
                elif m["status"] in ("adopted", "rejected", "exported"):   # 判定済みの削除(採用・不採用の記録は残っているので、取り消しとして1行足す)
                    extras.append((m, "delete_judged", {"prevStatus": m["status"]}))
            for m in new:
                o = old_by.get(m["id"])
                changed = (m["status"] != o["status"]) if o is not None else (m["status"] in ("adopted", "rejected"))
                if changed and (o is not None or m["src"] == "manual"):
                    if m["status"] == "adopted":
                        verdicts.append((m, "good", "adopt"))
                    elif m["status"] == "rejected":
                        verdicts.append((m, "bad", "reject"))
                if o is None and m["src"] == "manual":
                    extras.append((m, "manual_add", feedback.nearest_auto(v["marks"], m["start"], m["end"])))
                elif o is not None and o["status"] in ("adopted", "exported") and m["status"] == "":
                    extras.append((m, "unadopt", {"prevStatus": o["status"]}))
            nv = copy.deepcopy(v)
            nv["marks"] = new
            if isinstance(title, str):   # 空文字はタイトルを消す
                nv["title"] = title.strip()[:120]
            self._bump(nv)   # 保存に成功したときだけ、feedback を書く
            snap = self._pub(nv)
        for m, verdict, event in verdicts:
            feedback.feedback_for_mark(snap, m, verdict, event)
            if event == "adopt":   # コラボグループに入っていれば、他の動画へ候補として転写する
                self._transfer_collab(vid, m)
        for m, event, extra in extras:
            feedback.feedback_event(snap, m, event, extra)
        return snap

    def adopt_top(self, vid, top):
        """スタジオの「上位 n 本を採用」・まとめて実行用: 採用の規則 adopt_marks(F-5)を区間なし(ranges = [])で呼ぶ。
        人が採用したマークは数に入れ、上限 top までの残りを自動マークの点数の高い順で足す(RS6 b-A。以前は「人が採用済みなら自動は 0」)。
        -> (この呼び出しで採用にしたマークの id(点数の高い順), 公開用の動画)"""
        if schemas.int_in(top, 1, 30) is None:
            raise ApiError("bad_request", "採用する数は1〜30です", 400)
        r = self.adopt_marks(vid, [], top)
        return r["added"], r["video"]

    def adopt_marks(self, vid, ranges, top):
        """採用の規則(F-5。plan/role-restructure.md 5-5・決定 3-29 Q3。スタジオの「上位 n 本を採用」・まとめて実行・友人の依頼で同じ 1 つ)を当てて保存する。
        規則の本体は ① pipeline/analyze/adopt.py(RS8 B3-2 の G1a)。③ は ② flow/adopt を通して呼び、ここは配信を読んで保存するだけ:
        採用の集合 = 区間 ranges のマーク ∪ 人が採用したマーク ∪ 自動マークの点数の高い順(上限 top までの残り)。不採用と、前の 2 つに重なる自動マークは除く。
        人の判定ではないので、学習の記録(feedback)・コラボへの転写はしない。kind live の録画は断る(400)。
        -> {"rangeIds"(ranges の順), "humanIds"(時刻の順), "autoIds"(点数の高い順), "added"(この呼び出しで採用にした id), "video"(公開用の動画)}"""
        want = _flow_adopt.check(ranges, top)   # 区間・上限がだめなら 400(配信を読む前)
        with self.lock:
            v = self._need(vid)
            r = _flow_adopt.pick(v, want, top)
            nv = copy.deepcopy(v)
            nv["marks"] = r.pop("marks")
            if r["added"]:
                self._bump(nv)
            r["video"] = self._pub(nv)
            return r

    def replace_auto(self, vid, cands, analysis, duration, series):
        """解析結果を反映する。手を入れていない・書き出していない自動マークだけを置き換える。
        手を入れた自動マーク(書き出し済み / ラベルあり / 時刻を動かした)は手動マークとして残す(点数・理由は保持)。
        新しい自動マークは、残したマークと同じ区間(±0.5秒)なら作らない。戻り値は新しい自動マークの数(動画が消えていれば None)。"""
        with self.lock:
            v = self.videos.get(vid)
            if not v or v["kind"] == "live":   # live は解析しない(入口で断っているが、念のためここでも反映しない)
                return None
            kept = []
            for m in v["marks"]:
                if m["src"] != "auto":
                    kept.append(m)
                elif _marks.touched(m):
                    k = dict(m, src="manual")
                    a0 = k.pop("auto0", None)
                    if a0:
                        # 手動に変わると auto0 が消えて「機械の最初の結果」が失われるので、マークの側に残す。
                        # マークの側にした理由: 後の採用・書き出しの feedback の行も auto0 と手で直した量(dStart/dEnd)を持てる・
                        # data.json とアーカイブにマークと一緒に残る(feedback の「消えた」行だと、後の行と区間で突き合わせる必要がある)
                        k["auto0Orig"] = a0
                    kept.append(k)
            autos = []
            for c in cands:
                try:
                    s, e = check_times(c["start"], c["end"])   # 手動と同じ規則(長さの上限など)
                except (BadMark, KeyError, TypeError):
                    continue
                m = _marks.new_mark("a", s, e)
                m.update({"src": "auto", "score": _marks.fnum(c.get("score")), "reasons": _marks.clean_reasons(c.get("reasons")), "peak": _marks.fnum(c.get("peak")),
                          "parts": _marks.clean_parts(c.get("parts")), "auto0": [s, e]})
                if any(_marks.same(m, o) for o in kept + autos):
                    continue
                autos.append(m)
            if len(kept) + len(autos) > MAX_MARKS:   # 残したマークを優先し、自動を減らす
                autos = sorted(autos, key=_marks.by_score)[:max(0, MAX_MARKS - len(kept))]
            nv = copy.deepcopy(v)
            nv["marks"] = sorted(kept + autos, key=_marks.by_time)[:MAX_MARKS]
            nv["analysis"] = analysis
            if duration and duration > 0:
                nv["duration"] = round(float(duration), 2)
            self._bump(nv)
            self.series[vid] = series
            return len(autos)

    def mark_exported(self, vid, mark_id, relfile, expected_start, expected_end, abspath=None, archived=None):
        """書き出した区間が今のマークと一致するときだけ、exported にして保存する。abspath: 書き出した mp4 の絶対パス(あれば)。
        archived(live の配信だけ。線 D の P4): True = 本番版に入れ替え済みの印を立てる(既に書き出し済みで path が同じでも立てられる)/
        False = 外す / None = ファイルが同じ(file・path が同じ)なら今の印のまま、違うファイルになったら外す"""
        fb = None
        with self.lock:
            v = self.videos.get(vid)
            m = next((x for x in v["marks"] if x["id"] == mark_id), None) if v else None
            if not m:
                return False
            if abs(m["start"] - expected_start) > EDIT_TOL or abs(m["end"] - expected_end) > EDIT_TOL:
                return False   # 書き出し中の編集を保持する。古い区間の動画は関連付けない
            first = m["status"] != "exported"
            nv = copy.deepcopy(v)
            nm = next(x for x in nv["marks"] if x["id"] == mark_id)
            old_file, old_path = m.get("file") if m["status"] == "exported" else None, m.get("path")
            nm["status"], nm["file"] = "exported", str(relfile)[:300]
            if isinstance(abspath, str) and abspath and len(abspath) <= 600 and os.path.isabs(abspath):
                nm["path"] = abspath
            else:
                nm.pop("path", None)
            same_file = old_file == nm["file"] and old_path == nm.get("path")
            if v["kind"] == "live" and (archived is True or (archived is None and same_file and m.get("archived"))):
                nm["archived"] = True
            else:
                nm.pop("archived", None)
            self._bump(nv)
            if first:   # 自動・手動どちらも、初めて書き出したときに「よかった」(最終の区間と、手で直した量つき)
                fb = (self._pub(nv), dict(nm))
        if fb:
            feedback.feedback_for_mark(fb[0], fb[1], "good", "export")
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
            return self._group_summary(self._need_group(gid))

    def _need_group(self, gid, vid=None):
        """グループ(無ければ ApiError 404)。vid を渡すと、そのグループのメンバーであることも確かめる。self.lock を取っていること"""
        g = self.groups.get(str(gid or ""))
        if not g:
            raise ApiError("not_found", "グループが見つかりません", 404)
        if vid is not None and vid not in g["members"]:
            raise ApiError("not_found", "そのグループにその配信はありません", 404)
        return g

    def _check_free(self, ids):
        """ids の動画がすべて登録済みで、どのコラボグループにも入っていないこと(違えば ApiError)。self.lock を取っていること"""
        for vid in ids:
            v = self.videos.get(vid)
            if not v:
                raise ApiError("not_found", "配信が見つかりません(%s)" % vid, 404)
            if self._video_group(vid):
                raise ApiError("conflict", "「%s」はすでに別のコラボグループに入っています" % (v["title"] or vid), 409)

    @staticmethod
    def _clean_ids(video_ids):
        if not isinstance(video_ids, list):
            raise ApiError("bad_request", "配信を指定してください", 400)
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
            raise ApiError("bad_request", "基準の配信は、選んだ配信の中から指定してください", 400)
        with self.lock:
            if len(self.groups) >= MAX_GROUPS:
                raise ApiError("too_many", "グループは%d件までです" % MAX_GROUPS, 400)
            self._check_free(ids)
            gid = _new_group_id(self.groups)
            now = schemas.now_ms()
            g = {"id": gid, "name": str(name or "").strip()[:120], "base": base, "members": ids,
                 "offsets": {vid: [] for vid in ids if vid != base}, "createdAt": now, "updatedAt": now}
            self._commit_group(gid, g)
            return self._group_summary(g)

    def add_members(self, gid, video_ids):
        ids = self._clean_ids(video_ids)
        with self.lock:
            g = self._need_group(gid)
            new = [v for v in ids if v not in g["members"]]
            if not new:
                raise ApiError("bad_request", "追加する配信がありません", 400)
            if len(g["members"]) + len(new) > MAX_GROUP_MEMBERS:
                raise ApiError("bad_request", "1つのグループにまとめられるのは%d本までです" % MAX_GROUP_MEMBERS, 400)
            self._check_free(new)
            offsets = dict(g["offsets"])
            for vid in new:
                offsets[vid] = []
            return self._save_group(g, members=g["members"] + new, offsets=offsets)

    def remove_member(self, gid, vid):
        """メンバーを外す。基準の動画を外す・残り1本になる場合はグループごと削除する(ズレの基準がなくなるため)。
        すでに転写済みのマークは(既存の動画削除と同様)消さずに残す。戻り値: 残ったグループ(削除したときは None)。"""
        with self.lock:
            vid = str(vid or "")
            g = self._need_group(gid, vid)
            if vid == g["base"] or len(g["members"]) <= 2:
                self._commit_group(g["id"], None)
                return None
            members = [m for m in g["members"] if m != vid]
            offsets = {k: v for k, v in g["offsets"].items() if k != vid}
            return self._save_group(g, members=members, offsets=offsets)

    def _save_group(self, g, **changes):
        """グループ g を changes で変えて保存し(updatedAt を付ける)、要約を返す"""
        ng = dict(g, updatedAt=schemas.now_ms(), **changes)
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
            vid = str(vid or "")
            g = self._need_group(gid, vid)
            if vid == g["base"]:
                raise ApiError("bad_request", "基準の配信にはズレの指定は不要です", 400)
            try:
                piece = offset_from_anchors(points)
            except BadMark as e:
                raise ApiError("bad_anchor", str(e), 400)
            offsets = dict(g["offsets"])
            offsets[vid] = [piece]
            return self._save_group(g, offsets=offsets)

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
            origin = {"videoId": from_vid, "markId": from_mark_id}   # collabFrom は必ずこの 2 つの鍵だけ(ytt/marks の collab_from)
            already = any(m.get("collabFrom") == origin for m in v["marks"])
            if already:
                return
            try:
                s, e = check_times(max(0.0, s_raw), e_raw)
            except BadMark:
                return
            e = _marks.clamp_end(v["duration"], s, e)
            if e is None:
                return
            from_title = (self.videos.get(from_vid) or {}).get("title") or from_vid
            note = ("コラボ転写(元: %s)" % from_title)[:40]
            similar = next((x for x in v["marks"] if _marks.overlaps(s, e, x["start"], x["end"])), None)
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
                    self._bump(nv)
                return
            if len(v["marks"]) >= MAX_MARKS:
                return
            m = _marks.new_mark("c", s, e)
            m.update({"src": "collab", "reasons": [note], "collabFrom": {"videoId": from_vid, "markId": from_mark_id}, "auto0": [s, e]})
            nv = copy.deepcopy(v)
            nv["marks"] = sorted(nv["marks"] + [m], key=_marks.by_time)[:MAX_MARKS]
            self._bump(nv)

    # ---- 画面の設定(不透明な辞書。self.ui_file = ytt.settings.SettingsFile) ----
    def get_ui(self):
        return self.ui_file.read()   # 読めなければ空(呼ぶ側が書き換えるので {} は毎回作る)

    def set_ui_section(self, name, value):
        """画面の設定のうち1つの節(例: review)だけを置き換える。読み込み→書き込みをロックの中で行うので、
        別のタブ・別の画面が同時に別の節を保存しても消し合わない(以前は画面が全体を読んで全体を書いていた)"""
        if not _settings.section_name_ok(name):
            raise ApiError("bad_request", "section の名前が正しくありません", 400)
        if not isinstance(value, dict):
            raise ApiError("bad_request", "value は辞書で指定してください", 400)
        with self.lock:
            d, broken = self.ui_file.load()
            d[name] = value
            self.set_ui(d, broken)

    def set_ui(self, d, broken=False):
        """全体を書く(broken = 読めなかったファイルを `.broken-<日時>` に退避してから)"""
        if not isinstance(d, dict):
            raise ApiError("bad_request", "settings は辞書で指定してください", 400)
        try:
            with self.lock:
                self.ui_file.save(d, broken)
        except _settings.SettingsTooLarge as e:
            raise ApiError("too_large", str(e), 413)
        except _settings.SettingsError as e:
            raise ApiError("bad_request", str(e), 400)
        except OSError:
            raise ApiError("save_failed", SAVE_ERR, 500)
