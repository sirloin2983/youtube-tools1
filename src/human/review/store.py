"""③ 動画とマークの保存(data.json)。スレッドセーフ・原子的に書き込む。スタジオの `Store` が書き手(スタジオなしの書き手は ② flow/studiobook の StudioBook)。
- 書き方(書く道 _writing・保存 _put・登録 ensure・解析の反映 replace_auto・採用 adopt_marks・書き出し済み mark_exported・案件にする _make_case)は
  ② flow/studiobook の Ledger を継ぐ(StudioBook と 1 つ。OPT-H2 7b-1)。ここは data.json をメモリに持つ行の置き方(_row・_commit)と、
  ③ だけの口(_full のキャッシュと 503・_pub・案件に書いたあとの読み直し _after_put・機械の記録 _on_exported・グラフ _save_series)・人の保存・コラボ・画面の設定

- 動画: youtube(id=YouTube動画ID) / file(id="f"+sha1(絶対パス)[:10])。file のパスはサーバー内部だけが持ち、クライアントには返さない。
- マーク: サーバーが検査・整形する。status / file / src / 点数 / auto0 などのサーバー由来の値はクライアントから書き換えられない。
- 変更は「新しい状態を作る → ディスクに保存 → 成功したらメモリに反映」の順(保存に失敗したらメモリは変わらない)。
- 解析結果の series(盛り上がりグラフ)は cache/series/<動画ID>.json にも保存する(最新 ytt/studiodata.SERIES_KEEP 本まで。再起動後もグラフが出る)。
- マークの status: ""(候補) / "adopted"(採用) / "rejected"(不採用) / "exported"(書き出し済み)。exported はサーバーだけが付ける。
- data.json が壊れていたら data.json.corrupt-<日時> に退避して空で起動し、dataWarning で知らせる。1つ前の世代は data.json.bak。
- **案件にした配信**(決定 3-37 の (r8j)〜(r8q)): 初めて書き出したとき(mark_exported。それまでに書き出したマークが無い配信だけ)に flow/casebook.case_of で案件の根が引けたら、配信を案件の
  `作業用/候補.json`・`作業用/採用.json` に分けて書き、data.json(とメモリ)には索引の行 {id, kind, title, channel, live?, rev, createdAt, updatedAt, case}
  だけを持つ。読む所(list・get・internal・media_path)は案件のファイルを読んで重ねる(ytt/casefiles。更新日時と大きさのキャッシュ)。
  書く所は 採用 → 候補 → data.json の索引の行の順(rev の正は 採用.json・data.json の rev・題は写し)。人の保存は 候補.json を書き換えない
  (消した候補は 採用.json の消した印)・再解析(replace_auto)だけ候補を作り直す。書いたあと同じロックの中で読み直して重ね、違えば警告のログだけ。
  ロックの順はいつも Store.lock → casefiles.lock(root)(逆の順は作らない。② の側は casefiles.lock を持ったままスタジオの API を呼ばない)。
  案件が見えない(ドライブが外れた・フォルダが消えた)とき: 一覧の行は caseUnseen で出す・get・put_video・adopt_marks・mark_exported・ifNoMarks の削除は 503
  (case_unseen)・replace_auto とコラボの転写はログだけで反映しない。削除は索引の行だけ消す(案件のファイルは触らない)。コラボのまとまりは data.json のまま。
  消した配信を同じ URL で入れ直して初めて書き出すと、採用.json にある前の記録に重ねる(flow/casebook.carry_over。丸ごと置き換えない)
- 入口のライブの採用(adopt_live = POST /api/live/adopt): 録画の配信の登録・同じ区間の使い回し・保存を self.lock の中で 1 度に(put_video を通す)。
  案件にした録画の配信も同じ道で 採用.json へ = スタジオの採用もスタジオなしの採用(flow/casebook.live_adopt)も、案件にしたあとは 採用.json を通る
- 警告(案件が読めない・書いたあとの読み直しが違う・data.json の読み飛ばし)は logging の ytt.review.store へ。入口は studio/serve の _WarnToStudioLog で studio.log に残す
- 503 を返す口: get・put_video・adopt_marks・adopt_live・internal・mark_exported・ifNoMarks の削除・題を変える ensure(案件が見えないとき)
"""
import contextlib
import copy
import json
import logging
import math
import os
import shutil
import threading
import time

from ytt import fsio as _fsio, marks as _marks, mediainfo as _media, schemas, settings as _settings, studio_env as _env  # noqa: E402  (マークの検査・整形・同じ区間・手を入れたかは ytt/marks。録画の live の検査は ytt/studiodata.load_live)

from ytt import casefiles as _casefiles  # noqa: E402  案件の 候補.json・採用.json の読み・重ね方・ロック
from ytt import studiodata as _studiodata  # noqa: E402  data.json の行の読み方(load_video)と盛り上がりグラフの書き方(save_series)・形の名前 SCHEMA。flow/studiobook と共有
from flow import studiobook as _studiobook  # noqa: E402  台帳の書き方 Ledger(書く道・保存・登録・解析の反映・採用・書き出し済み・案件にする。StudioBook と 1 つ = OPT-H2 7b-1)
from . import machinelog  # noqa: E402  機械の記録 machine_marks.jsonl(呼ぶたびに machinelog.名前 で読む。人の採否は judgments)
from human import judgments as _judgments  # noqa: E402  人の判断の記録(作業データの app/judgments.jsonl。MARKS-3 S1a)
from ytt import datadir as _datadir  # noqa: E402  作業データの app の場所(入口が登録する。Store の app_dir の既定)
from ytt.errors import ApiError  # noqa: E402

_log = logging.getLogger("ytt.review.store")
_judge_lock = threading.Lock()   # 取り消しの行を書くとき: 読んで・足すを 1 度に(保存の外で書くので Store.lock は取らない)
# 作業データが壊れていたときの戻し方(画面の帯に出す。退避したファイルの名前・フォルダは画面の「詳しく」に出す。見直し M8)
RESTORE_STEPS = "前のデータは退避してあります。戻すには: ホームで「すべて終了」→ 退避したファイルの名前を元に戻す(下の「詳しく」)→ start.bat で起動し直す"
SAVE_ERR = "保存に失敗しました(ディスクの空きなど)"
UI_MAX_BYTES = 32 * 1024   # 画面の設定 settings-ui.json の大きさの上限

# ---- コラボ動画のマーク転写(グループ+オフセット) ----
MAX_GROUPS = 50
MAX_GROUP_MEMBERS = 8
COLLAB_MARGIN = 2.5     # 転写した区間を前後に広げる秒数(反応のタイミングは人によってずれるため)
ANCHOR_A_MIN, ANCHOR_A_MAX = 0.5, 1.5   # アンカー点から求めた傾き(ドリフト補正)の妥当な範囲。外れたら入力ミスの可能性が高い
MIN_ANCHOR_GAP = 20.0   # 2点指定のとき、この動画の時刻でこれ以上離れていることを要求する(近すぎると傾きが不安定)

def _warn(msg):
    """警告のログ(入口は studio.log にも残す = studio/serve の _WarnToStudioLog。7d-2)"""
    _log.warning(msg)


def _origin(video, m):
    """人の判断の出どころ(judgments の origin)。録画は live・手で足したマークは manual・自動の候補(転写・再解析で手動になった物を含む)は auto"""
    if video.get("kind") == "live":
        return "live"
    if m.get("src") == "manual" and not m.get("auto0Orig"):
        return "manual"
    return "auto"


def _ref(video):
    """録画の配信の出どころ(ref.recorder・ref.recording)。録画でなければ None"""
    lv = video.get("live") if video.get("kind") == "live" else None
    return {"recorder": lv.get("recorder"), "recording": lv.get("recording")} if lv else None


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
    """[[この動画の時刻, 基準動画の時刻], …](1〜2点)から {a,b} を求める。1点なら定数オフセット(a=1)。不正なら _marks.BadMark。"""
    if not isinstance(points, list) or not (1 <= len(points) <= 2):
        raise _marks.BadMark("アンカーは1〜2点で指定してください")
    pts = []
    for p in points:
        if not (isinstance(p, (list, tuple)) and len(p) == 2):
            raise _marks.BadMark("アンカーの形式が正しくありません")
        t_this, t_ref = _marks.num_strict(p[0]), _marks.num_strict(p[1])
        if t_this is None or t_ref is None or t_this < 0 or t_ref < 0:
            raise _marks.BadMark("アンカーの時刻が正しくありません")
        pts.append((t_this, t_ref))
    if len(pts) == 1:
        a, b = 1.0, pts[0][1] - pts[0][0]
    else:
        (t1, r1), (t2, r2) = pts
        if abs(t2 - t1) < MIN_ANCHOR_GAP:
            raise _marks.BadMark("2つのアンカーは、この配信の時刻で%d秒以上離してください" % int(MIN_ANCHOR_GAP))   # 用語は「アンカー」(2 周目 S20)
        a = (r2 - r1) / (t2 - t1)
        b = r1 - a * t1
    if not (math.isfinite(a) and math.isfinite(b)):
        raise _marks.BadMark("計算できませんでした(時刻を確認してください)")
    if a < ANCHOR_A_MIN or a > ANCHOR_A_MAX:
        raise _marks.BadMark("傾きが%.1f〜%.1f倍の範囲を外れています。時刻の入力を確認してください" % (ANCHOR_A_MIN, ANCHOR_A_MAX))
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


def _new_id(prefix, existing):
    """まだ使われていない id(prefix + 12 桁の 16 進)"""
    while True:
        nid = prefix + os.urandom(6).hex()
        if nid not in existing:
            return nid


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
    """動画ID → 盛り上がりグラフ。メモリにあればそれを、なければ cache/series のファイルから読む(再起動後も残る)。
    消すのは pop だけ(ファイルも消す)。60 本に減らしたあとも、メモリの辞書は起動し直すまで残る(一覧の hasSeries は真のまま。害は小さい)"""

    def __init__(self, folder):
        super().__init__()
        self.folder = folder

    def _path(self, vid):
        return os.path.join(self.folder, vid + ".json") if isinstance(vid, str) and _marks.ID_RE.match(vid) else None

    def __setitem__(self, vid, val):
        super().__setitem__(vid, val)
        if val is not None:
            _studiodata.save_series(self.folder, vid, val)   # 古いものから消して SERIES_KEEP 本に。保存に失敗してもメモリには残る

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


class Store(_studiobook.Ledger):
    """スタジオの台帳(③。書き手は 1 つ)。data.json をメモリに全部持ち、変えるときは新しい形を作って保存してからメモリを替える。
    案件にした配信は 候補.json・採用.json を読んで重ねる(_full)・書くのは _writing の中(案件の錠)。ロックの順は Store.lock → casefiles.lock(root)。
    人の判断の記録(judgments.jsonl)と機械の記録(machine_marks.jsonl)は保存に成功したあと、ロックの外で書く。スタジオなしの書き手は ② flow/studiobook の StudioBook(同じ形で書く)"""

    def __init__(self, path, app_dir=None):
        self.path = path
        self.app_dir = app_dir or _datadir.resolve("app")   # 人の判断の記録(judgments.jsonl)の置き場所。テストは一時フォルダを渡す
        self.ui_path = os.path.join(os.path.dirname(path), "settings-ui.json")
        self.lock = threading.RLock()
        # 画面の設定(読む・書く・退避・大きさの上限は ytt.settings.SettingsFile。ホーム・編集の設定ファイルと同じ決まり)
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
            parts = [fmt % n for fmt, n in (("配信の記録 %d 件", skipped), ("コラボの記録 %d 件", gskipped)) if n]
            self.warning = "作業データ(マークの記録)の一部(%s)が壊れていたので、読み飛ばしました。" % "・".join(parts) + (RESTORE_STEPS if name else "")
            _warn("data.json の壊れた%sを読み飛ばしました。元のファイルは %s" % ("・".join(parts), name or "(退避に失敗)"))

    _load_video = staticmethod(_studiodata.load_video)   # data.json の行 -> メモリの形(ytt/studiodata。外からこの名前で読む所は無い = 外は ytt を直に)

    @staticmethod
    def _load_group(gid, g):
        if not isinstance(g, dict) or g.get("id") != gid or not isinstance(gid, str) or not _marks.ID_RE.match(gid):
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
        data = json.dumps({"schema": _studiodata.SCHEMA, "videos": videos, "groups": groups}, ensure_ascii=False).encode("utf-8")
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

    def _need(self, vid):
        """登録済みの動画(メモリの行。案件の配信は索引の行 = 全部の形は _full)。無ければ ApiError 404。self.lock を取っていること"""
        v = self.videos.get(str(vid or ""))
        if not v:
            raise ApiError("not_found", "配信が見つかりません", 404)
        return v

    # ---- 案件にした配信(RS8 B3-4b) ----
    def _full(self, v, strict=False):
        """メモリの行 -> 全部の形(読む所)。案件の行は案件の 候補.json・採用.json を読んで重ね(更新日時と大きさのキャッシュ)、印 case を付ける。
        案件が見えない・採用.json にこの配信が無い: strict なら ApiError 503(case_unseen。採用.json が .bak も読めなければ 500 case_broken)、
        でなければ索引の行に caseUnseen・マーク空の形(一覧の行は出す)"""
        root = v.get("case") if v else None
        if not root:
            return v
        try:
            full = _casefiles.merge(*_casefiles.read(root, cached=True), v["id"], root)
        except ApiError as e:
            if strict:
                raise
            _warn("案件を読めません(%s): %s" % (e.code, root))
            full = None
        if full is None:
            if strict:
                raise _casefiles.unseen(root, "案件の採用の記録にこの配信がありません")
            return dict(v, duration=0.0, fileName="", path="", marks=[], analysis=None, caseUnseen=True)
        return _casefiles.fill(full, v, root)

    @staticmethod
    def _after_put(root, body):
        """Ledger の口: 案件に書いた配信を同じロックの中で読み直して重ね、書いた物と違えば警告のログだけ(保存は落とさない)"""
        try:
            got = _casefiles.merge(*_casefiles.read(root), body["id"], root)
        except Exception as e:   # 読めない = 次の読みで分かる(ここでは落とさない)
            _warn("案件に書いた配信を読み直せませんでした(%s): %s" % (e.__class__.__name__, root))
            return
        if got != body:
            diff = sorted(k for k in set(got or {}) | set(body) if (got or {}).get(k) != body.get(k))
            _warn("案件に書いた配信を読み直すと違います(%s。欄: %s): %s" % (body["id"], ",".join(diff)[:200], root))

    # ---- Ledger(② flow/studiobook)の口: 行・書き出し先・初めて書き出したマーク・盛り上がりのグラフ・警告 ----
    def _row(self, vid):
        """メモリの行(案件の配信は索引の行)か None"""
        return self.videos.get(str(vid or ""))

    @staticmethod
    def out_dir():
        """書き出し先(初めて書き出したとき案件を引く)。スタジオのメモリの値 = settings.json を読み直さない(呼ぶたびに ytt/studio_env を読む)"""
        return _env.get_out_dir()

    def _on_exported(self, v, mark):
        """初めて書き出したマーク(自動・手動どちらも)の機械の様子を機械の記録へ(最終の区間と手で直した量つき。ロックの外)"""
        machinelog.record(self._pub(v), dict(mark), "export")

    def _save_series(self, vid, series):
        """解析を反映できたときの盛り上がりのグラフ(メモリと cache/series。前と同じく Store.lock の中で 1 本ずつ)"""
        with self.lock:
            self.series[vid] = series

    _warn = staticmethod(_warn)   # 警告は ytt.review.store のログ(入口は studio.log にも残す)

    # ---- 表現 ----
    @staticmethod
    def _pub(v):
        d = {k: v[k] for k in ("id", "kind", "title", "channel", "duration", "fileName", "analysis", "rev", "createdAt", "updatedAt")}
        d["marks"] = v["marks"]
        if v["kind"] == "live":
            d["live"] = v["live"]
        if v.get("caseUnseen"):
            d["caseUnseen"] = True   # 案件が見えない(マークは空の形。B3-4b)
        return json.loads(json.dumps(d))   # 深いコピー(呼び出し側が書き換えても内部に影響しない)

    def _summary(self, v):
        """一覧の 1 行(v は全部の形 = _full)"""
        g = self._video_group(v["id"])
        d = {"id": v["id"], "kind": v["kind"], "title": v["title"], "channel": v["channel"], "duration": v["duration"], "fileName": v["fileName"],
             "marks": len(v["marks"]), "autoMarks": sum(1 for m in v["marks"] if m["src"] == "auto"), "exported": sum(1 for m in v["marks"] if m["status"] == "exported"),
             "adopted": sum(1 for m in v["marks"] if m["status"] == "adopted"), "candidates": sum(1 for m in v["marks"] if m["status"] == ""),
             "createdAt": v["createdAt"], "updatedAt": v["updatedAt"], "rev": v["rev"], "hasSeries": v["id"] in self.series, "analysis": json.loads(json.dumps(v["analysis"])),
             "groupId": g["id"] if g else None, "groupOffsetSet": (g["base"] == v["id"] or bool(g["offsets"].get(v["id"]))) if g else None}
        if v["kind"] == "live":
            d["live"] = dict(v["live"])
            d["archived"] = sum(1 for m in v["marks"] if m.get("archived"))   # 本番版に入れ替え済みのマークの数(線 D の P4)
        if v.get("caseUnseen"):
            d["caseUnseen"] = True   # 案件が見えない(一覧の行は出す。書きは 503。B3-4b)
        return d

    # ---- 取得 ----
    def list(self):
        with self.lock:
            vs = sorted(self.videos.values(), key=lambda v: -v["updatedAt"])
            return [self._summary(self._full(v)) for v in vs]

    def get(self, vid):
        """(公開用の動画, series or None)。無ければ ApiError 404・案件が見えなければ 503(case_unseen)。"""
        with self.lock:
            v = self._full(self._need(vid), strict=True)
            return self._pub(v), self.series.get(v["id"])

    def internal(self, vid):
        """サーバー内部用(path を含む)のコピー。無ければ None・案件が見えなければ ApiError 503(case_unseen)。"""
        with self.lock:
            v = self.videos.get(str(vid or ""))
            if not v:
                return None
            v = self._full(v, strict=True)
            return dict(self._pub(v), path=v["path"])

    def media_path(self, vid):
        """/media 用: 登録済みの file 動画の実パス。それ以外(案件が見えないときも)は None。"""
        with self.lock:
            v = self._full(self.videos.get(str(vid or "")))
            return v["path"] if v and v["kind"] == "file" and v["path"] else None

    def has(self, vid):
        with self.lock:
            return vid in self.videos

    # ---- 登録・削除 ----
    def ensure(self, src, title="", channel="", probe=False):
        """動画を(なければ作って)返す。src は flow.ingest.probe(analyze.validate_source)の結果。probe=True でファイルの長さを確認(読めなければ 400)。
        登録と題・チャンネル名の決まりは Ledger.ensure(空で消さない・録画は空の欄だけ・変えないなら書かない・案件の配信は 採用.json へ)"""
        dur = 0.0
        if src["kind"] == "file" and probe and not self.has(src["videoId"]):
            d = _media.media_info(src["path"])[0]
            if _env.find_tool("ffmpeg") and d is None:
                raise ApiError("bad_source", "動画・音声として読み取れないファイルです", 400)
            dur = float(d or 0)
        return super().ensure(src, title, channel, dur)

    def delete(self, vid, if_no_marks=False):
        """if_no_marks: マークが1つでもあれば消さない(409。入口の「マークの無い録画を消す」= 線 D の P4。確かめてから消すまでの間に付いたマークを消さない)。
        案件にした配信は索引の行だけ消す(案件のファイルは触らない)。if_no_marks は重ねたマークで決める(案件が見えなければ 503 で消さない)"""
        with self.lock:
            vid = str(vid or "")
            if vid not in self.videos:
                return False
            with self._writing(self.videos[vid]) if if_no_marks else contextlib.nullcontext((None, None)) as (v, _prev):
                if if_no_marks and v.get("marks"):
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
    def put_video(self, vid, title, marks_raw, base_rev=None, judged=True):
        """画面の保存(PUT /api/video): マーク全件を置き換える。-> 公開用の動画。
        baseRev が今の版と違えば 409(解析・書き出し・別タブが先に入っている。何も変えない)・全件を ytt/marks.validate_marks で検査して 1 件でも不正なら 400(何も変えない)。
        サーバーだけが決める値(src・点数・exported・file・path・adoptedBy)は前の値を引き継ぐ。案件の配信は 採用.json の版と比べて 採用.json へ書く。
        保存できたあと、ロックの外で、その時の機械の様子と見逃しの出来事を machine_marks.jsonl へ(human/review/machinelog。採否は書かない。
        録画は書かない)・人の採否・取り消しを judgments.jsonl へ 1 行ずつ(judged=False は書かない = 入口のライブの採用。その行は案件の道が書く)・採用したマークはコラボの相手へ転写する"""
        if not isinstance(marks_raw, list):
            raise ApiError("bad_request", "marks が正しくありません", 400)
        if base_rev is not None and not schemas.is_int(base_rev):
            raise ApiError("bad_request", "baseRev が正しくありません", 400)
        with self.lock, self._writing(self._need(vid)) as (v, prev):   # 案件の配信は案件から読んだ版と比べる(rev の正は 採用.json)
            if base_rev is not None and base_rev != v["rev"]:   # 別の更新(解析・書き出し・別タブ)が先に入っている: 何も変えない
                raise ApiError("conflict", "解析や書き出しで内容が更新されています。最新の内容を読み込み直してください", 409, {"video": self._pub(v), "series": self.series.get(v["id"])})
            new = _marks.validate_marks(marks_raw, v["marks"])   # 1件でも不正なら 400(何も変えない)
            ids = {m["id"] for m in new}
            old_by = {m["id"]: m for m in v["marks"]}
            # 人の採否(judgments = 正)と、その時の機械の様子(machinelog): 採用 = adopt / 不採用 = reject / 候補のまま削除 = reject(event delete)。
            # 自動マークは上の全部。手動マーク(自分で見つけた区間)は、採用・不採用にしたときだけ。
            # それとは別に、見逃しの出来事を機械の記録に残す(Q2。machinelog.MISS_EVENTS):
            # 手で足した = 自動の見逃し(その時いちばん近い自動マークの点数と距離つき)・手で足した候補を消した・採用を取り消した・判定済みを削除した。
            # まとめて実行(adopt_marks・request_marks)は put_video を通らないので書かれない(人の判断ではないため)
            verdicts = []
            extras = []
            for m in v["marks"]:
                if m["id"] in ids:
                    continue
                if m["status"] == "":
                    if m["src"] == "auto" or m.get("auto0Orig"):   # 候補のままの自動マーク(再解析で手動に変わったものも元は自動)
                        verdicts.append((m, "reject", "delete"))
                    elif m["src"] == "manual":
                        extras.append((m, "manual_remove", {}))
                elif m["status"] in ("adopted", "rejected", "exported"):   # 判定済みの削除(採用・不採用の記録は残っているので、取り消しとして1行足す)
                    extras.append((m, "delete_judged", {"prevStatus": m["status"]}))
            for m in new:
                o = old_by.get(m["id"])
                changed = (m["status"] != o["status"]) if o is not None else (m["status"] in ("adopted", "rejected"))
                if changed:   # 画面から来る新しいマークは build_mark で必ず manual なので、o が無くてもここで足りる
                    if m["status"] == "adopted":
                        verdicts.append((m, "adopt", "adopt"))
                    elif m["status"] == "rejected":
                        verdicts.append((m, "reject", "reject"))
                if o is None and m["src"] == "manual":
                    extras.append((m, "manual_add", machinelog.nearest_auto(v["marks"], m["start"], m["end"])))
                elif o is not None and o["status"] in ("adopted", "exported", "rejected") and m["status"] == "":
                    extras.append((m, "unadopt", {"prevStatus": o["status"]}))   # 不採用の取り消しも(prevStatus = rejected。確かめるの Z = 6e-2)
            nv = copy.deepcopy(v)
            nv["marks"] = new
            if isinstance(title, str):   # 空文字はタイトルを消す
                nv["title"] = title.strip()[:120]
            self._bump(nv, prev)   # 保存に成功したときだけ、記録を書く
            snap = self._pub(nv)
        for m, what, event in verdicts:
            ts = time.strftime("%Y-%m-%dT%H:%M:%S")   # 機械の記録の行と judgments の key で同じ時刻
            machinelog.record(snap, m, event, ts=ts)
            if judged and not m.get("adoptedBy"):   # 機械が採用にしたマーク(adoptedBy)は人の判断ではない
                self._judge(snap, m, what, event, ts)
            if event == "adopt":   # コラボグループに入っていれば、他の動画へ候補として転写する
                self._transfer_collab(vid, m)
        for m, event, extra in extras:
            machinelog.record(snap, m, event, extra)
            if judged and event in ("unadopt", "delete_judged"):   # 人の取り消し = 同じ印の最後の採否の行を取り消す(無ければ書かない)
                self._retract_judgment(snap, m)
        return snap

    def _judge(self, snap, m, what, event, ts):
        """人の採否(adopt・reject)を judgments.jsonl に 1 行。key は判定の記録と同じ fb:<ts>:<videoId>:<markId>:<event>。書けなくても保存は落とさない(ログだけ)"""
        try:
            _judgments.record(self.app_dir, who="self", videoId=snap["id"], markId=m["id"], what=what, origin=_origin(snap, m), via="review",
                              start=m["start"], end=m["end"], key="fb:%s:%s:%s:%s" % (ts, snap["id"], m["id"], event), ref=_ref(snap))
        except (ValueError, OSError) as e:
            _warn("人の判断の記録を書けませんでした(%s): %s" % (e.__class__.__name__, snap["id"]))

    def _retract_judgment(self, snap, m):
        """人の取り消し(採用を候補に戻す・判定済みの削除)。同じ印の、まだ取り消していない最後の採否の行を of にして 1 行足す。key は原本の key + ":retract"。
        無ければ何も書かない(機械の採用・書き出しだけだった印など)"""
        vid, mid = snap["id"], m["id"]
        try:
            with _judge_lock:
                rows = _judgments.rows(self.app_dir)
                done = {r.get("of") for r in rows if r["what"] == "retract"}
                hit = None
                for r in rows:
                    if r["who"] == "self" and r["what"] in ("adopt", "reject") and r["videoId"] == vid and r["markId"] == mid and r["id"] not in done:
                        hit = r
                if hit is not None:
                    _judgments.retract(self.app_dir, hit, "self", "review")
        except (ValueError, OSError) as e:
            _warn("人の判断の取り消しを書けませんでした(%s): %s" % (e.__class__.__name__, vid))

    def adopt_live(self, src, title, start, end, label=""):
        """入口のライブの採用(POST /api/live/adopt。flow/live_adopt.py の StudioMarks): 録画の配信(kind live。src は analyze.validate_live)を
        (無ければ)登録し、区間 [start, end](録画の頭からの秒)と同じ区間(±ytt/marks.DUP_TOL 秒)のマークがあれば使い回し(候補・不採用なら採用に)、
        無ければ採用のマークを足す。登録・読み・保存を self.lock の中で 1 度にする。
        保存は put_video(画面の保存と同じ検査。案件にした配信は 採用.json へ)。機械の記録は録画では書かない(machinelog は kind live を記録しない)。
        -> (配信の id, マーク(公開の形), 番号 n = 配信のマークを開始の順に並べた位置)"""
        if not (schemas.is_num(start) and schemas.is_num(end)):
            raise ApiError("bad_request", "start・end は録画の頭からの秒(数)で指定してください", 400)
        a, b = float(start), float(end)
        with self.lock:
            vid = self.ensure(src, title)["id"]
            v = self._full(self._need(vid), strict=True)
            hit = _marks.near_mark(v["marks"], a, b)
            if hit is not None and hit["status"] in ("adopted", "exported"):
                return vid, json.loads(json.dumps(hit)), _marks.order_of(v["marks"], hit["id"])
            if hit is not None:
                want = hit["id"]
                new = [dict(m, status="adopted") if m["id"] == want else m for m in v["marks"]]
            else:
                want = _new_id("m", {m["id"] for m in v["marks"]})
                new = v["marks"] + [{"id": want, "start": a, "end": b, "label": str(label or "")[:120], "status": "adopted"}]
            snap = self.put_video(vid, None, new, base_rev=v["rev"], judged=False)   # 同じロックの中 = 版がぶつからない。人の判断の行は案件の道(S3)が書く
            mark = next(m for m in snap["marks"] if m["id"] == want)
            return vid, mark, _marks.order_of(snap["marks"], want)

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
            members.append({"id": vid, "title": (v["title"] or v.get("fileName") or "") if v else "", "kind": v["kind"] if v else "", "exists": v is not None,
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
            gid = _new_id("g", self.groups)
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
            except _marks.BadMark as e:
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
        重複した候補で一覧が埋まるのを防ぐのが狙い。転写先が案件にした配信で案件が見えなければ、ログだけで反映しない。"""
        with self.lock:
            row = self.videos.get(vid)
            if row:
                self._quietly(row, "コラボの転写", lambda v, prev: self._collab_into(v, prev, from_vid, from_mark_id, s_raw, e_raw))

    def _collab_into(self, v, prev, from_vid, from_mark_id, s_raw, e_raw):
        """_add_collab_candidate の本体(self.lock と、案件なら案件のロックを取っていること)"""
        origin = {"videoId": from_vid, "markId": from_mark_id}   # collabFrom は必ずこの 2 つの鍵だけ(ytt/marks の collab_from)
        already = any(m.get("collabFrom") == origin for m in v["marks"])
        if already:
            return
        try:
            s, e = _marks.check_times(max(0.0, s_raw), e_raw)
        except _marks.BadMark:
            return
        e = _marks.clamp_end(v["duration"], s, e)
        if e is None:
            return
        from_title = (self.videos.get(from_vid) or {}).get("title") or from_vid
        note = ("コラボ転写(元: %s)" % from_title)[:40]
        similar = next((x for x in v["marks"] if _marks.overlaps(s, e, x["start"], x["end"])), None)
        if similar is not None:
            try:
                new_s, new_e = _marks.check_times(min(similar["start"], s), max(similar["end"], e))
            except _marks.BadMark:
                new_s, new_e = similar["start"], similar["end"]   # 広げると長さ上限を超える等の異常時は広げない(安全側)
            moved = abs(new_s - similar["start"]) > _marks.EDIT_TOL or abs(new_e - similar["end"]) > _marks.EDIT_TOL
            note_needed = note not in similar["reasons"]
            if moved or note_needed:
                nv = copy.deepcopy(v)
                target = next(x for x in nv["marks"] if x["id"] == similar["id"])
                target["start"], target["end"] = new_s, new_e
                if note_needed:
                    target["reasons"] = (target["reasons"] + [note])[:6]
                if moved and target["status"] == "exported":
                    target["status"], target["file"] = "adopted", ""
                self._bump(nv, prev)
            return
        if len(v["marks"]) >= _marks.MAX_MARKS:
            return
        m = _marks.new_mark("c", s, e)
        m.update({"src": "collab", "reasons": [note], "collabFrom": {"videoId": from_vid, "markId": from_mark_id}, "auto0": [s, e]})
        nv = copy.deepcopy(v)
        nv["marks"] = sorted(nv["marks"] + [m], key=_marks.by_time)[:_marks.MAX_MARKS]
        self._bump(nv, prev)

    # ---- 画面の設定(不透明な辞書。self.ui_file = ytt.settings.SettingsFile) ----
    def get_ui(self):
        return self.ui_file.read()   # 読めなければ空(呼ぶ側が書き換えるので {} は毎回作る)

    def set_ui_section(self, name, value):
        """画面の設定のうち1つの節(例: review)だけを置き換える。読み込み→書き込みをロックの中で行うので、
        別のタブ・別の画面が同時に別の節を保存しても消し合わない"""
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
