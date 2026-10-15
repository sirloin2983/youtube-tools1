# -*- coding: utf-8 -*-
"""② 管理の層 flow: スタジオなしの配信の台帳と、URL の段の動詞(RS8 の「URL も CLI で」。2026-10-11。B-3 = スタジオの候補と採用を案件へ、のあと)。

入口(スタジオ)が動いていないとき、コマンド(src/app/cli.py)が URL の段(配信の読み・解析・採用・書き出し)を ② + ① だけで進めるための物。
友人の PC の ② + ① には ③ 人(スタジオの human/review/store)が無いことがあるので、③ を読まずに **スタジオの Store と同じ形** で書く:

- `Ledger` = 採用の台帳の書き方の 1 つ(書く道 _writing・保存 _put・登録 ensure・解析の反映 replace_auto・採用 adopt_marks・書き出し済み mark_exported・
  案件にする _make_case)。行の置き方(行を読む _row・1 行を書く _commit)は継ぐ側が付ける。人の操作(学習の記録・自己検査)は継ぐ側の口(既定は何もしない)。
  今は StudioBook が継ぐ(スタジオの Store が継ぐのは次の段 = OPT-H2 7b-1 の続き)
- `StudioBook(path)` = 台帳(Ledger + data.json の 1 行の置き方)。スタジオの data.json(path)と、案件にした配信の 案件の `作業用/候補.json`・`作業用/採用.json`(flow/casebook)を読み書きする。
  形・決まりはスタジオの Store と同じ 1 つ(ytt に下ろした物を使う): 行の読み方 ytt/studiodata.load_video・解析の反映 ytt/marks.replace_auto・
  採用の規則 F-5 は ② flow/adopt(① pipeline/analyze/adopt)・書き出し済みにする ytt/marks.exported_mark・索引の行 ytt/casefiles.index_row・
  分ける・書く flow/casebook.split・write・案件の引き方 flow/casebook.case_of(初めて書き出したとき = (r8j))。
  data.json はメモリに持たず、変えるたびに読み直して 1 行だけ置き換えて書く(ほかの配信の行・コラボのまとまりはそのまま。1 つ前は .bak・原子的)。
  同じ作業データでスタジオ(入口)と同時に書かないことは .flow.lock が守る(入口は lock を取れなければ起動しない・CLI は入口が動いていれば入口に頼む)。
  data.json が壊れていたら書かない(ApiError 500。直すのは入口 = スタジオの Store が退避して空で起動する)。
  スタジオと違うこと: 学習の記録(③ の feedback)は書かない(人の判定ではない・③ を読まない)。盛り上がりのグラフは cache/series へ書く(画面で出る)。
  コラボのまとまりへの転写はしない(人の採用ではないので Store の adopt_marks もしない)
- `LocalStudio(book)` = 段が頼む動詞(flow/tools の HttpTools の video・analyze_add・analyze_items・analyze_cancel・request_marks・export_start・
  export_job・export_cancel と同じ名前・同じ返す形)。解析の順番は flow/batch.Batch(台帳を store に)・書き出しは ② の器 flow/export(中身は ① pipeline/export/exporter)
  (書き出した 1 本ごとに台帳の mark_exported と flow/keys の export の鍵 = スタジオの serve の /api/export と同じ)。`close()` で解析・書き出し・子プロセスを止める
置き場所(スタジオの作業データ・書き出し先)は呼ぶ側(app の CLI)が ytt/studio_env に入れてから作る。
"""
import contextlib
import copy
import json
import logging
import os
import shutil
import threading
import time

from pipeline.analyze import analyze as _analyze, fetch as _fetch
from pipeline.export import exporter as _exporter
from ytt import casefiles as _cf, fsio as _fsio, marks as _marks, procs as _procs, schemas as _schemas, studio_env as _env, studiodata as _sd
from ytt import version as _version
from ytt.errors import ApiError

from . import adopt as _adopt, batch as _batch, casebook as _casebook, export as _export, keys as _keys

log = logging.getLogger("ytt.flow.studiobook")

SCHEMA = _sd.SCHEMA              # data.json の形の名前(スタジオの Store と同じ)
STOP_WAIT = 10.0                 # close で解析・書き出しのスレッドが後始末を終えるのを待つ秒


def _need(v):
    if not v:
        raise ApiError("not_found", "配信が見つかりません", 404)
    return v


class Ledger:
    """採用の台帳の書き方(② の 1 つ)。行の置き方は継ぐ側が付ける。ロックの順は self.lock → casefiles.lock(root)。
    継ぐ側が付ける物: self.lock(RLock)・self.out_dir()(書き出し先。初めて書き出したとき案件を引く)・
    _row(vid) = 行(メモリの形 = 全部の形か索引の行)か None・_commit(vid, row) = 1 行を data.json の形で書く。
    継ぐ側が替えてよい口(既定のまま = StudioBook): _full(row) = 全部の形・_pub(v) = 返す形・_after_put(root, body) = 案件に書いたあと・
    _on_exported(v, mark) = 初めて書き出したマーク(ロックの外)・_save_series(vid, series) = 盛り上がりのグラフ・_warn(msg) = 警告のログ。
    友人の PC の ② + ① で動く物だけを持つ(③ の学習の記録・コラボ・画面の設定は継ぐ側の口で足す)"""

    # ---- 継ぐ側が付ける口 ----
    def _row(self, vid):
        raise NotImplementedError

    def _commit(self, vid, row):
        raise NotImplementedError

    # ---- 継ぐ側が替えてよい口 ----
    def _full(self, row):
        """行 -> 全部の形(案件の行は案件のファイルを重ねる。見えなければ ApiError 503)"""
        root = row.get("case")
        if not root:
            return row
        full = _cf.merge(*_cf.read(root), row["id"], root)
        if full is None:
            raise _cf.unseen(root, "案件の採用の記録にこの配信がありません")
        return _cf.fill(full, row, root)

    @staticmethod
    def _pub(v):
        """書く動詞が返す形(既定 = 全部の形の写し)"""
        return copy.deepcopy(v)

    def _after_put(self, root, body):
        """案件に配信 body を書いたあと(同じロックの中・data.json の索引の行を書く前)。既定は何もしない"""

    def _on_exported(self, v, mark):
        """初めて書き出したマーク(v = 保存した全部の形)。ロックの外で呼ぶ。既定は何もしない(学習の記録は書かない)"""

    def _save_series(self, vid, series):
        """解析の結果を反映できたときの盛り上がりのグラフ(ロックの外で呼ぶ)。既定は何もしない"""

    @staticmethod
    def _warn(msg):
        log.warning(msg)

    # ---- 書く ----
    @contextlib.contextmanager
    def _writing(self, row):
        """書く道の入口(self.lock を取っていること)。案件の配信なら案件のロックを持ったまま読み直して (全部の形, 今の (候補, 採用)) を渡す。
        案件でなければ (row, None)。案件が見えなければ ApiError 503(case_unseen)・採用.json が .bak も読めなければ 500(case_broken)"""
        root = row.get("case")
        if not root:
            yield row, None
            return
        with _cf.lock(root):
            prev = _cf.read(root)
            full = _cf.merge(*prev, row["id"], root)
            if full is None:
                raise _cf.unseen(root, "案件の採用の記録にこの配信がありません")
            yield _cf.fill(full, row, root), prev

    def _quietly(self, row, what, fn):
        """_writing の中で fn(全部の形, prev) を呼ぶ。案件が見えない・採用.json が読めないときは上げずにログして反映しない(None)。
        ほかの ApiError(保存の失敗など)はそのまま上げる。self.lock を取っていること"""
        try:
            with self._writing(row) as (v, prev):
                return fn(v, prev)
        except ApiError as e:
            if not row.get("case") or e.code not in (_cf.UNSEEN_CODE, _cf.BROKEN_CODE):
                raise
            self._warn("%sを案件に反映できませんでした(%s): %s" % (what, e.code, row["case"]))
            return None

    def _put(self, nv, prev=None, keep=True):
        """1 本を保存する(_writing の中で呼ぶ)。案件の配信は 採用 → 候補 → data.json の索引の行の順。
        keep=True(人の保存・書き出しの記録・題): 候補.json は書き換えない。keep=False(再解析): 候補を作り直す"""
        root = nv.get("case")
        if not root:
            self._commit(nv["id"], _cf.stored(nv))
            return
        body = _cf.stored(nv)
        cands, adopts = _casebook.split(body, root, prev=prev, keep_candidates=keep)
        _casebook.write(root, None if keep else cands, adopts)
        self._after_put(root, body)
        self._commit(nv["id"], _cf.index_row(body, root))

    def _bump(self, nv, prev=None, keep=True):
        """版を上げて保存する(prev・keep は _put)"""
        nv["rev"] += 1
        nv["updatedAt"] = _schemas.now_ms()
        self._put(nv, prev, keep)

    def ensure(self, src, title="", channel="", duration=0.0):
        """配信を(無ければ)登録して返す(_pub の形。src は analyze.validate_source の結果。duration = 新しい行の長さ)。
        題・チャンネル名は空でない新しい値のときだけ入れる(空で消さない)。録画(kind live)は空の欄だけ埋める(録画の情報は変えない)。
        変えないなら書かない・変えたら版を上げる(案件の配信は 採用.json へ。題を変えるとき案件が見えなければ 503)"""
        vid = src["videoId"]
        t, ch = str(title or "").strip()[:120], str(channel or "").strip()[:100]
        with self.lock:
            row = self._row(vid)
            if row is not None and row["kind"] != src["kind"]:
                raise ApiError("conflict", "同じ ID の別の配信があります", 409)
            if row is None:
                now = _schemas.now_ms()
                nv = {"id": vid, "kind": src["kind"], "title": t, "channel": ch, "duration": float(duration or 0), "fileName": "", "path": "", "marks": [],
                      "analysis": None, "rev": 1, "createdAt": now, "updatedAt": now}
                if src["kind"] == "file":
                    nv["fileName"] = os.path.basename(src["path"])[:200]
                    nv["path"] = src["path"]
                    nv["title"] = t or os.path.splitext(nv["fileName"])[0][:120]
                elif src["kind"] == "live":
                    nv["live"] = dict(src["live"])
                self._put(nv)
                return self._pub(nv)
            if row["kind"] == "live":
                t, ch = (t if not row["title"] else ""), (ch if not row["channel"] else "")
            else:
                t, ch = (t if t != row["title"] else ""), (ch if ch != row["channel"] else "")
            if not (t or ch):
                return self._pub(self._full(row))
            with self._writing(row) as (v, prev):
                nv = copy.deepcopy(v)
                nv["title"], nv["channel"] = t or nv["title"], ch or nv["channel"]
                self._bump(nv, prev)
                return self._pub(nv)

    def replace_auto(self, vid, cands, analysis, duration, series):
        """解析の結果を反映する(flow/batch が呼ぶ)。手を入れていない・書き出していない自動マークだけを置き換える(ytt/marks.replace_auto)。
        案件の配信は 候補.json を作り直す(人が消した候補の印に当たる新しい候補は出さない = (r8l))。
        -> 新しい自動マークの数か None(配信が無い・録画・案件が見えない = ログだけ)"""
        with self.lock:
            row = self._row(vid)
            if not row or row["kind"] == "live":
                return None
            n = self._quietly(row, "解析の結果", lambda v, prev: self._replace_auto(v, prev, cands, analysis, duration))
        if n is not None:
            self._save_series(vid, series)
        return n

    def _replace_auto(self, v, prev, cands, analysis, duration):
        """replace_auto の本体(self.lock と、案件なら案件のロックを取っていること)"""
        hide = None
        if prev is not None:   # 案件: 人が消した候補の印に当たる新しい候補は出さない((r8l))
            gone = [r for r in prev[1]["rejected"] if r.get("source") == v["id"]]
            hide = lambda autos: _cf.visible(autos, [], gone)   # noqa: E731
        marks, n = _marks.replace_auto(v["marks"], cands, hide)
        nv = copy.deepcopy(v)
        nv["marks"], nv["analysis"] = marks, analysis
        if duration and duration > 0:
            nv["duration"] = round(float(duration), 2)
        self._bump(nv, prev, keep=False)
        return n

    def adopt_marks(self, vid, ranges, top):
        """採用の規則 F-5(② flow/adopt)を当てて保存する(人の判定ではない = 学習の記録・コラボへの転写はしない)。
        -> {"rangeIds", "humanIds", "autoIds", "added", "video"(_pub の形)}"""
        want = _adopt.check(ranges, top)   # 区間・上限がだめなら 400(配信を読む前)
        with self.lock:
            with self._writing(_need(self._row(vid))) as (v, prev):
                r = _adopt.pick(v, want, top)
                nv = copy.deepcopy(v)
                nv["marks"] = r.pop("marks")
                if r["added"]:
                    self._bump(nv, prev)
                r["video"] = self._pub(nv)
                return r

    def mark_exported(self, vid, mark_id, relfile, expected_start, expected_end, abspath=None, archived=None):
        """書き出した区間が今のマークと同じときだけ書き出し済みにする(ytt/marks.exported_mark。archived は録画の本番版の印 = 同じ所の説明)。
        初めて書き出した配信は、案件の根が引けたら案件にする(flow/casebook.case_of。(r8j))。
        初めて書き出したマークはロックの外で _on_exported へ。-> 記録したか"""
        with self.lock:
            row = self._row(vid)
            if not row:
                return False
            with self._writing(row) as (v, prev):
                m = next((x for x in v["marks"] if x["id"] == mark_id), None)
                if not m or abs(m["start"] - expected_start) > _marks.EDIT_TOL or abs(m["end"] - expected_end) > _marks.EDIT_TOL:
                    return False   # 書き出し中に区間が変わった: 古い区間の動画は結びつけない
                first = m["status"] != "exported"
                nv = copy.deepcopy(v)
                nm = _marks.exported_mark(m, relfile, abspath, archived, live=v["kind"] == "live")
                nv["marks"] = [copy.deepcopy(nm) if x["id"] == mark_id else x for x in nv["marks"]]
                root = None
                if prev is None and not any(x["status"] == "exported" for x in v["marks"]):
                    root = _casebook.case_of(nv, out_dir=self.out_dir())
                if root:
                    nv["rev"] += 1
                    nv["updatedAt"] = _schemas.now_ms()
                    self._make_case(nv, root)
                else:
                    self._bump(nv, prev)
        if first:
            self._on_exported(nv, nm)
        return True

    def _make_case(self, nv, root):
        """初めて書き出した配信(nv = 全部の形)を案件 root にする: 案件のファイル(split(prev) = 同じ案件のほかの配信は引き継ぐ)→ data.json の索引の行。
        案件のファイルを書けなければ全部の形のまま data.json へ(書き出しの記録を落とさない。次の書き出しでもう一度試す)"""
        with _cf.lock(root):
            try:
                prev = _cf.read(root)
                nv = _casebook.carry_over(prev, nv, root)   # 消して入れ直した配信は 採用.json の前の記録に重ねる(7c-1)
                _casebook.write(root, *_casebook.split(nv, root, prev=prev))
            except ApiError as e:
                self._warn("案件にできませんでした(data.json のまま保存します。%s): %s" % (e.code, root))
                self._commit(nv["id"], _cf.stored(nv))
                return
            self._after_put(root, nv)
            self._commit(nv["id"], _cf.index_row(nv, root))


class StudioBook(Ledger):
    """スタジオなしの配信の台帳(data.json + 案件のファイル)。書き方は Ledger・ここは data.json の 1 行の置き方(毎回読み直して 1 行だけ書く)。
    スレッドから呼んでよい(解析の糸・書き出しの糸・段)。ロックの順は self.lock → casefiles.lock(root)"""

    def __init__(self, path, out_dir=None):
        """path = スタジオの data.json・out_dir() = 書き出し先(案件を引く。None = ytt/studio_env.get_out_dir)"""
        self.path = path
        self.out_dir = out_dir or _env.get_out_dir
        self.series_dir = os.path.join(os.path.dirname(path), "cache", "series")
        self.lock = threading.RLock()

    # ---- data.json ----
    def _load(self):
        """data.json の中身(書き換えてよい新しい dict)。無ければ空の形。壊れていれば ApiError 500(書かない)"""
        if not os.path.exists(self.path):
            return {"schema": SCHEMA, "videos": {}, "groups": {}}
        d = _fsio.read_json_or(self.path, None, _sd.STUDIO_JSON_MAX, kind=dict, allow_nan=True)
        if d is None or not isinstance(d.get("videos"), dict):
            raise ApiError("studio_data_broken", "スタジオの作業データ(data.json)を読めません。入口(start.bat)を起動すると退避して直します", 500,
                           {"path": self.path})
        return d

    def _commit(self, vid, row):
        """data.json の 1 行だけを row に置き換えて書く(ほかの行・コラボのまとまりは読んだまま。1 つ前を .bak・原子的 = スタジオの Store と同じ)"""
        d = self._load()
        d["videos"][vid] = row
        self._write(d)

    def set_cases(self, roots):
        """案件の根だけを付け替える(書き出し先を変えたあとの繋ぎ直し・手の繋ぎ直し)。roots = {配信の id: 案件の根}。
        行が無い id は飛ばす。data.json は 1 回だけ書く(ほかの行・コラボのまとまりは読んだまま)。-> 付け替えた本数"""
        with self.lock:
            d = self._load()
            n = 0
            for vid, root in roots.items():
                row = d["videos"].get(vid)
                if isinstance(row, dict):
                    d["videos"][vid] = dict(row, case=root)
                    n += 1
            if n:
                self._write(d)
            return n

    def _write(self, d):
        """data.json を d(videos・groups)の形で書く(1 つ前を .bak・原子的)"""
        data = json.dumps({"schema": SCHEMA, "videos": d["videos"], "groups": d.get("groups") if isinstance(d.get("groups"), dict) else {}},
                          ensure_ascii=False).encode("utf-8")
        try:
            if os.path.exists(self.path):
                try:
                    shutil.copyfile(self.path, self.path + ".bak")
                except OSError:
                    pass
            _fsio.atomic_write(self.path, data, fsync_required=True)
        except OSError as e:
            log.warning("data.json を書けませんでした: %s", e)
            raise ApiError("save_failed", "保存に失敗しました(ディスクの空きなど)", 500)

    def _row(self, vid):
        """メモリの形の行(全部の形か索引の行)か None。行が壊れていれば ApiError 500"""
        raw = self._load()["videos"].get(str(vid or ""))
        if raw is None:
            return None
        try:
            return _sd.load_video(str(vid), raw)
        except ValueError as e:
            raise ApiError("studio_data_broken", "スタジオの作業データの配信 %s が壊れています: %s" % (vid, e), 500)

    def _save_series(self, vid, series):
        """盛り上がりのグラフ(スタジオの画面が読む cache/series/<配信>.json。最新 ytt/studiodata.SERIES_KEEP 本)。書けなくても上げない"""
        _sd.save_series(self.series_dir, vid, series)

    # ---- 読む ----
    def has(self, vid):
        """登録してあるか(解析の糸が待ちのたびに見る = 上げない。data.json が読めなければ False)"""
        with self.lock:
            try:
                return self._row(vid) is not None
            except ApiError:
                return False

    def get(self, vid):
        """全部の形(path も持つ)の写しか None(無い)。案件が見えなければ ApiError 503"""
        with self.lock:
            row = self._row(vid)
            return copy.deepcopy(self._full(row)) if row else None

    def internal(self, vid):
        """書き出しの指定(flow/export.build_spec)が読む形 = get"""
        return self.get(vid)


def _step_error(msg):
    from .run import StepError   # run が tools を読み、tools がここを読むので呼ぶときに読む
    return StepError(msg)


class LocalStudio:
    """URL の段の動詞(入口なし)。book = StudioBook。HttpTools の同じ名前の動詞と同じ返す形。
    入口の FlowTools の口にも使う(OPT2 後半 J7): book = スタジオの Store・batch = スタジオの serve の Batch(入口が渡す。② は ③ を読まない)"""

    def __init__(self, book, batch=None):
        self.book = book
        self.batch = batch if batch is not None else _batch.Batch(book)
        if not _exporter.TOOL.get("version"):   # .clip.json の tool の版(スタジオの serve と同じく全体の版)
            _exporter.TOOL["version"] = _version.VERSION

    def video(self, vid):
        """配信 1 本 -> (HTTP の番号, {"video"})(無ければ 404・案件が見えなければ 503)"""
        try:
            v = self.book.get(vid)
        except ApiError as e:
            return e.status, {"error": e.code, "message": e.message}
        if v is None:
            return 404, {"error": "not_found", "message": "配信が見つかりません"}
        return 200, {"video": v}

    def analyze_add(self, item, settings):
        """解析の順番に入れる -> {"added", "rejected"}(順番は flow/batch。道具が無い配信は rejected の理由に出る)"""
        try:
            return self.batch.add([item], settings)
        except ApiError as e:
            raise _step_error(e.message)

    def analyze_items(self):
        return self.batch.snapshot()["items"]

    def analyze_cancel(self, qid):
        try:
            self.batch.cancel(qid)
        except ApiError:
            pass

    def request_marks(self, body):
        """採用(F-5。スタジオの /api/video/request-marks と同じ: 配信が無ければ YouTube の ID の形だけ受けて登録してから)"""
        try:
            vid = str(body.get("id") or "")
            if not self.book.has(vid):
                src = _analyze.validate_source({"kind": "youtube", "videoId": vid})
                self.book.ensure(src, body.get("title") if isinstance(body.get("title"), str) else "",
                                 body.get("channel") if isinstance(body.get("channel"), str) else "")
                vid = src["videoId"]
            r = self.book.adopt_marks(vid, body.get("ranges"), body.get("top"))
        except ApiError as e:
            raise _step_error(e.message)
        return r

    def export_start(self, body):
        """書き出しを始める -> (HTTP の番号, 応答)。本文はスタジオの POST /api/export と同じ(flow/export.build_spec が台帳から組む)"""
        try:
            spec = _export.build_spec(self.book, body)

            def on_done(vid, mid, rel, start, end, path=None):
                recorded = self.book.mark_exported(vid, mid, rel, start, end, path)
                _keys.write_studio_export(spec, path, start, end)   # 切り抜きの横に export の鍵(スタジオの serve と同じ。RS6 b-K1)
                return recorded
            exports = _export.default()   # 書き出しの器(② の flow/export。スタジオの serve と同じ物 = 同時 1 本。OPT2 の J2)
            return 200, exports.public_of(exports.start(spec, on_done))
        except ApiError as e:
            return e.status, {"error": e.code, "message": e.message}

    def export_job(self, jid):
        try:
            return _export.default().public(jid)
        except ApiError as e:
            raise _step_error(e.message)

    def export_cancel(self, jid):
        try:
            _export.default().cancel(jid)
        except ApiError:
            pass

    @staticmethod
    def export_free(timeout):
        """書き出しの器(プロセスに 1 つ)が空くまで待つ(timeout 秒まで)-> 空いたか(J7。Runner の 409 busy の待ち)"""
        t = _export.default().table
        return t.wait(lambda: not t.active(), timeout)

    def close(self, wait=STOP_WAIT):
        """終わるとき(Ctrl+C・失敗でも): 解析の待ちを取り除き、解析・書き出し・チャットの先読みに中止を伝え、子プロセス(ffmpeg・yt-dlp)を孫ごと止め、
        スレッドの後始末を wait 秒まで待つ(スタジオの serve.shutdown_jobs と同じ順)。-> 止めた子プロセスの数"""
        names = self.batch.shutdown()
        exports = _export.default().cancel_all()
        pf = _fetch.cancel_all_prefetch()
        if not (names or exports or pf or _procs.children()):
            return 0
        killed = _procs.stop_children()
        deadline = time.time() + wait
        while time.time() < deadline and (self.batch.running_now() or _export.default().is_busy() or _fetch.PREFETCH):
            time.sleep(0.05)
        return killed + _procs.stop_children(1.0)
