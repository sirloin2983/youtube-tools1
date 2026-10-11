# -*- coding: utf-8 -*-
"""② 管理の層 flow: スタジオなしの配信の台帳と、URL の段の動詞(RS8 の「URL も CLI で」。2026-10-11。B-3 = スタジオの候補と採用を案件へ、のあと)。

入口(スタジオ)が動いていないとき、コマンド(src/app/cli.py)が URL の段(配信の読み・解析・採用・書き出し)を ② + ① だけで進めるための物。
友人の PC の ② + ① には ③ 人(スタジオの human/review/store)が無いことがあるので、③ を読まずに **スタジオの Store と同じ形** で書く:

- `StudioBook(path)` = 台帳。スタジオの data.json(path)と、案件にした配信の 案件の `作業用/候補.json`・`作業用/採用.json`(flow/casebook)を読み書きする。
  形・決まりはスタジオの Store と同じ 1 つ(ytt に下ろした物を使う): 行の読み方 ytt/studiodata.load_video・解析の反映 ytt/marks.replace_auto・
  採用の規則 F-5 は ② flow/adopt(① pipeline/analyze/adopt)・書き出し済みにする ytt/marks.exported_mark・索引の行 ytt/casefiles.index_row・
  分ける・書く flow/casebook.split・write・案件の引き方 flow/casebook.case_of(初めて書き出したとき = (r8j))。
  data.json はメモリに持たず、変えるたびに読み直して 1 行だけ置き換えて書く(ほかの配信の行・コラボのまとまりはそのまま。1 つ前は .bak・原子的)。
  同じ作業データでスタジオ(入口)と同時に書かないことは .flow.lock が守る(入口は lock を取れなければ起動しない・CLI は入口が動いていれば入口に頼む)。
  data.json が壊れていたら書かない(ApiError 500。直すのは入口 = スタジオの Store が退避して空で起動する)。
  スタジオと違うこと: 学習の記録(③ の feedback)は書かない(人の判定ではない・③ を読まない)。盛り上がりのグラフは cache/series へ書く(画面で出る)。
  コラボのまとまりへの転写はしない(人の採用ではないので Store の adopt_marks もしない)
- `LocalStudio(book)` = 段が頼む動詞(flow/tools の HttpTools の video・analyze_add・analyze_items・analyze_cancel・request_marks・export_start・
  export_job・export_cancel と同じ名前・同じ返す形)。解析の順番は flow/batch.Batch(台帳を store に)・書き出しは ① pipeline/export/exporter
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

from . import adopt as _adopt, batch as _batch, casebook as _casebook, keys as _keys

log = logging.getLogger("ytt.flow.studiobook")

SCHEMA = _sd.SCHEMA              # data.json の形の名前(スタジオの Store と同じ)
SERIES_KEEP = 60                 # 盛り上がりのグラフ cache/series/<配信>.json を残す本数(スタジオの Store と同じ)
STOP_WAIT = 10.0                 # close で解析・書き出しのスレッドが後始末を終えるのを待つ秒


def _unseen(root, why):
    return ApiError(_cf.UNSEEN_CODE, "案件のフォルダが見えません(%s)。ドライブをつないでから、もう一度試してください" % why,
                    503, {"dir": str(root or ""), "reason": why})


def _need(v):
    if not v:
        raise ApiError("not_found", "配信が見つかりません", 404)
    return v


class StudioBook:
    """スタジオなしの配信の台帳(data.json + 案件のファイル)。スレッドから呼んでよい(解析の糸・書き出しの糸・段)。ロックの順は self.lock → casefiles.lock(root)"""

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

    def _save_row(self, vid, row):
        """data.json の 1 行だけを row に置き換えて書く(ほかの行・コラボのまとまりは読んだまま。1 つ前を .bak・原子的 = スタジオの Store と同じ)"""
        d = self._load()
        d["videos"][vid] = row
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

    # ---- 読む ----
    def has(self, vid):
        """登録してあるか(解析の糸が待ちのたびに見る = 上げない。data.json が読めなければ False)"""
        with self.lock:
            try:
                return self._row(vid) is not None
            except ApiError:
                return False

    def _full(self, row):
        """行 -> 全部の形(案件の行は案件のファイルを重ねる。見えなければ ApiError 503)"""
        root = row.get("case")
        if not root:
            return row
        full = _cf.merge(*_cf.read(root), row["id"], root)
        if full is None:
            raise _unseen(root, "案件の採用の記録にこの配信がありません")
        return _cf.fill(full, row, root)

    def get(self, vid):
        """全部の形(path も持つ)の写しか None(無い)。案件が見えなければ ApiError 503"""
        with self.lock:
            row = self._row(vid)
            return copy.deepcopy(self._full(row)) if row else None

    def internal(self, vid):
        """書き出しの指定(exporter.build_spec)が読む形 = get"""
        return self.get(vid)

    # ---- 書く ----
    @contextlib.contextmanager
    def _writing(self, row):
        """書く道の入口(self.lock を取っていること)。案件の配信なら案件のロックを持ったまま読み直して (全部の形, 今の (候補, 採用)) を渡す"""
        root = row.get("case")
        if not root:
            yield row, None
            return
        with _cf.lock(root):
            prev = _cf.read(root)
            full = _cf.merge(*prev, row["id"], root)
            if full is None:
                raise _unseen(root, "案件の採用の記録にこの配信がありません")
            yield _cf.fill(full, row, root), prev

    def _put(self, nv, prev=None, keep=True):
        """1 本を保存(スタジオの Store._put と同じ順: 案件なら 採用 → 候補 → data.json の索引の行。keep=False = 再解析で候補を作り直す)"""
        root = nv.get("case")
        if not root:
            self._save_row(nv["id"], _cf.stored(nv))
            return
        body = _cf.stored(nv)
        cands, adopts = _casebook.split(body, root, prev=prev, keep_candidates=keep)
        _casebook.write(root, None if keep else cands, adopts)
        self._save_row(nv["id"], _cf.index_row(body, root))

    def _bump(self, nv, prev=None, keep=True):
        nv["rev"] += 1
        nv["updatedAt"] = _schemas.now_ms()
        self._put(nv, prev, keep)

    def ensure(self, src, title="", channel=""):
        """配信を(無ければ)登録して全部の形を返す(スタジオの Store.ensure と同じ形。src は analyze.validate_source の結果)。
        題・チャンネル名は空でない新しい値のときだけ入れる(空で消さない)"""
        vid = src["videoId"]
        t, ch = str(title or "").strip()[:120], str(channel or "").strip()[:100]
        with self.lock:
            row = self._row(vid)
            if row is not None and row["kind"] != src["kind"]:
                raise ApiError("conflict", "同じ ID の別の配信があります", 409)
            if row is None:
                now = _schemas.now_ms()
                nv = {"id": vid, "kind": src["kind"], "title": t, "channel": ch, "duration": 0.0, "fileName": "", "path": "", "marks": [], "analysis": None,
                      "rev": 1, "createdAt": now, "updatedAt": now}
                if src["kind"] == "file":
                    nv["fileName"] = os.path.basename(src["path"])[:200]
                    nv["path"] = src["path"]
                    nv["title"] = t or os.path.splitext(nv["fileName"])[0][:120]
                self._put(nv)
                return copy.deepcopy(nv)
            if not ((t and t != row["title"]) or (ch and ch != row["channel"])):
                return copy.deepcopy(self._full(row))
            with self._writing(row) as (v, prev):
                nv = copy.deepcopy(v)
                nv["title"], nv["channel"] = t or nv["title"], ch or nv["channel"]
                self._bump(nv, prev)
                return copy.deepcopy(nv)

    def replace_auto(self, vid, cands, analysis, duration, series):
        """解析の結果を反映する(flow/batch が呼ぶ。スタジオの Store.replace_auto と同じ)。-> 新しい自動マークの数か None(配信が無い・録画・案件が見えない)"""
        with self.lock:
            row = self._row(vid)
            if not row or row["kind"] == "live":
                return None
            try:
                with self._writing(row) as (v, prev):
                    hide = None
                    if prev is not None:   # 案件: 人が消した候補の印に当たる新しい候補は出さない((r8l))
                        gone = [r for r in prev[1]["rejected"] if r.get("source") == vid]
                        hide = lambda autos: _cf.visible(autos, [], gone)   # noqa: E731
                    marks, n = _marks.replace_auto(v["marks"], cands, hide)
                    nv = copy.deepcopy(v)
                    nv["marks"], nv["analysis"] = marks, analysis
                    if duration and duration > 0:
                        nv["duration"] = round(float(duration), 2)
                    self._bump(nv, prev, keep=False)
            except ApiError as e:
                if not row.get("case") or e.code not in (_cf.UNSEEN_CODE, _cf.BROKEN_CODE):
                    raise
                log.warning("解析の結果を案件に反映できませんでした(%s): %s", e.code, row["case"])
                return None
        self._save_series(vid, series)
        return n

    def _save_series(self, vid, series):
        """盛り上がりのグラフ(スタジオの画面が読む cache/series/<配信>.json。最新 SERIES_KEEP 本)。書けなくても上げない"""
        if not isinstance(vid, str) or not _marks.ID_RE.match(vid) or series is None:
            return
        try:
            _fsio.atomic_write(os.path.join(self.series_dir, vid + ".json"), json.dumps(series, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            _fsio.prune_cache(self.series_dir, "*.json", SERIES_KEEP)
        except OSError as e:
            log.info("盛り上がりのグラフを書けませんでした: %s", e)

    def adopt_marks(self, vid, ranges, top):
        """採用の規則 F-5(② flow/adopt)を当てて保存する(スタジオの Store.adopt_marks と同じ)。
        -> {"rangeIds", "humanIds", "autoIds", "added", "video"}"""
        want = _adopt.check(ranges, top)
        with self.lock:
            with self._writing(_need(self._row(vid))) as (v, prev):
                r = _adopt.pick(v, want, top)
                nv = copy.deepcopy(v)
                nv["marks"] = r.pop("marks")
                if r["added"]:
                    self._bump(nv, prev)
                r["video"] = copy.deepcopy(nv)
                return r

    def mark_exported(self, vid, mark_id, relfile, expected_start, expected_end, abspath=None):
        """書き出した区間が今のマークと同じときだけ書き出し済みにする(スタジオの Store.mark_exported と同じ。学習の記録は書かない)。
        初めて書き出した配信は、案件の根が引けたら案件にする(flow/casebook.case_of。(r8j))。-> 記録したか"""
        with self.lock:
            row = self._row(vid)
            if not row:
                return False
            with self._writing(row) as (v, prev):
                m = next((x for x in v["marks"] if x["id"] == mark_id), None)
                if not m or abs(m["start"] - expected_start) > _marks.EDIT_TOL or abs(m["end"] - expected_end) > _marks.EDIT_TOL:
                    return False   # 書き出し中に区間が変わった: 古い区間の動画は結びつけない
                nv = copy.deepcopy(v)
                nm = _marks.exported_mark(m, relfile, abspath, None, live=v["kind"] == "live")
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
            return True

    def _make_case(self, nv, root):
        """初めて書き出した配信を案件にする(スタジオの Store._make_case と同じ: 案件のファイル → data.json の索引の行。案件にできなければ全部の形のまま)"""
        with _cf.lock(root):
            try:
                _casebook.write(root, *_casebook.split(nv, root, prev=_cf.read(root)))
            except ApiError as e:
                log.warning("案件にできませんでした(data.json のまま保存します。%s): %s", e.code, root)
                self._save_row(nv["id"], _cf.stored(nv))
                return
            self._save_row(nv["id"], _cf.index_row(nv, root))


def _step_error(msg):
    from .run import StepError   # run が tools を読み、tools がここを読むので呼ぶときに読む
    return StepError(msg)


class LocalStudio:
    """URL の段の動詞(入口なし)。book = StudioBook。HttpTools の同じ名前の動詞と同じ返す形"""

    def __init__(self, book):
        self.book = book
        self.batch = _batch.Batch(book)
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
        """書き出しを始める -> (HTTP の番号, 応答)。本文はスタジオの POST /api/export と同じ(exporter.build_spec が台帳から組む)"""
        try:
            spec = _exporter.build_spec(self.book, body)

            def on_done(vid, mid, rel, start, end, path=None):
                recorded = self.book.mark_exported(vid, mid, rel, start, end, path)
                _keys.write_studio_export(spec, path, start, end)   # 切り抜きの横に export の鍵(スタジオの serve と同じ。RS6 b-K1)
                return recorded
            return 200, _exporter.job_public(_exporter.start_job(spec, on_done))
        except ApiError as e:
            return e.status, {"error": e.code, "message": e.message}

    def export_job(self, jid):
        try:
            return _exporter.job_public(_exporter.get_job(jid))
        except ApiError as e:
            raise _step_error(e.message)

    def export_cancel(self, jid):
        try:
            _exporter.cancel(jid)
        except ApiError:
            pass

    def close(self, wait=STOP_WAIT):
        """終わるとき(Ctrl+C・失敗でも): 解析の待ちを取り除き、解析・書き出し・チャットの先読みに中止を伝え、子プロセス(ffmpeg・yt-dlp)を孫ごと止め、
        スレッドの後始末を wait 秒まで待つ(スタジオの serve.shutdown_jobs と同じ順)。-> 止めた子プロセスの数"""
        names = self.batch.shutdown()
        exports = _exporter.cancel_all()
        pf = _fetch.cancel_all_prefetch()
        if not (names or exports or pf or _procs.children()):
            return 0
        killed = _procs.stop_children()
        deadline = time.time() + wait
        while time.time() < deadline and (self.batch.running_now() or _exporter.is_busy() or _fetch.PREFETCH):
            time.sleep(0.05)
        return killed + _procs.stop_children(1.0)
