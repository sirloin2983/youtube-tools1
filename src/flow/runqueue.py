# -*- coding: utf-8 -*-
"""② 管理の層 flow: 待ち行列と実行の糸(RS7-1 S5。決定 3-30・
notes:plan/done/f1-friend-pc.md の「RS7(② の側)へ渡すこと」)。

友人の依頼の受付・ユーザーの入口・CLI が同じ ② の口を使えるように、待ち行列と糸をここに置く。
画面なし・③ なしでも動く: Queue(client, log_dir=...) だけで submit → 糸が段を進める → status / snapshot / history で見る。

- Queue は flow/run.py の Runner を継ぐ(段の中身と hook はそのまま)。入口の AutoRunner(src/app/autorun.py)は Queue を継いで、
  hook(案件・ホームの設定・友人へ届ける = ③④ の物)だけを埋める。受付は submit の 1 本(RV A1。欄 → 封筒 + 束の差分は flow/order.py)。
  hook を埋めなければ何もしない(素の Runner の既定 + 下の build_spec・_on_error の既定)= 画面なしの ② の形
- 口: submit(封筒, 束)= 封筒 + 束を受けて Run.from_envelope で積む(束にこの PC の設定 flow/machine.py を重ねる = 受けたときに組んだ束のまま流す)/
  status() = 待ち・実行中の数と進み具合(「終わったら閉じる」のため)/ cancel・snapshot・history・estimate・close。
  HTTP の口は入口の POST /api/flow/submit・GET /api/flow/status(src/app/server.py。RS7-1 S4)
- 束は受けたときに組む(RS7-1 S4): submit は土台(hook の build_spec = 画面の設定 + この PC の設定)+ 受けた差分。hook の _accept(
  友人の区間の長さ・配信者・届ける名前の頭)。待ちの間に設定を変えても、その実行の中身は変わらない
- 糸 _loop: 待ちを 1 本ずつ、優先度の表(flow/prio.py。録画中のライブ > 友人の依頼 > 自分の配信のまとめて実行・同じなら入れた順。PRIO)の順で _execute(Run の束で流す。束の無い Run = 直に積んだ物だけ、ここで hook の build_spec で組む)
- 待ちの記録(起動し直しで戻す。線 D の M5): 待ち・実行中の実行を log_dir/autorun-active.json に Run.saved()(封筒 + 束 + 状態)で残し
  (入れたとき・始めたとき・段が済むたび・終わったとき。一時ファイルから置き換える)、作るときに読んで同じ id のまま「待ち」に戻す。
  版 2(RS7-1 S4)= 束と受付で決めた物が入っている。それより前の版(1)の記録は読まずに捨てる(戻さない。知らせを 1 行)。
  束の無い記録(直に積んだ物)は戻すときに hook の _accept(convert=True) で束を組む(まだ決めていない物だけ決める)。
  RESTORE_MAX_AGE より前に入れた実行は戻さず、記録に「中止」と書く。入口の終了(close)で止まった実行は記録に「中止」と書かない(次の起動で続ける)
- 終わった実行の記録: log_dir/autorun-runs.jsonl に 1 行ずつ(形と読み方は flow/runlog.py。1MB を超えたら .1 へ)。
  結果の束(<案件>/作業用/runs/<id>.json)は flow/run.py の run() の終わりに flow/placement.write_result が書く

import してよいのは標準ライブラリ・ytt・同じ flow だけ(層の向き。home・human・manage は hook で)。
文の中の「ホーム」は今の入口の言葉のまま(画面の JSON と記録の形を変えないため。玄関を分けるとき RS7-2 で見直す)。
"""
import collections
import importlib
import json
import os
import threading
import time
import urllib.parse

from ytt import colors as _colors, fsio, jobs as _yjobs, schemas as _schemas, tools as _ytools
from . import board as _board, envelope as _envelope, learning as _learning, machine as _machine, placement as _placement, prio as _prio, run as run_mod, runlog, spec as _spec
from .run import (DOC_MODE, RUN_STATE_LABELS, STEP_LABELS, Cancelled, Run, StepError,
                  adopted_ids, pack_verdict, tx_verdict)

MAX_KEEP = 30          # 終わった記録を残す数(メモリ。ファイルの記録は runlog.RUNS_LOG)
LOG_MAX_BYTES = 1024 * 1024   # これを超えたら .1 に回す(1件 1〜2KB なので 500〜1000 件ぶん)
LOG_READ_BYTES = 256 * 1024   # 起動時に読む末尾の大きさ(前回の結果 past を作る)
PAST_MAX = 50          # snapshot の past(配信・文書ごとの前回の結果で、メモリに無いもの)の数
PAST_KEEP = 500        # past の元として覚えておく配信・文書の数
HISTORY_DEFAULT, HISTORY_MAX = 50, 200   # history の limit の既定と上限
PAST_KEYS = ("id", "kind", "docId", "videoId", "title", "mode", "modeLabel", "state", "stateLabel", "nothing", "message", "error",
             "created", "finished", "steps")   # past に入れる項目(2〜15 秒ごとの問い合わせを重くしない。全部は history で)
MAX_WAITING = 20       # 順番待ちの上限
CLOSED_MSG = "終了しているところです。起動し直してから入れてください"   # close のあとは新しく積まない(submit)
ACTIVE_FILE = "autorun-active.json"  # 待ち・実行中の実行(log_dir の中。runlog.RUNS_LOG の隣)
ACTIVE_VERSION = 2     # 中身は Run.saved()(封筒 + 束 + 状態)。2 = RS7-1 S4 から(束は受けたときに組んだ物・受付で決めた物も入る)
ACTIVE_READ_MAX = 4 * 1024 * 1024
RESTORE_MAX_AGE = 3 * 86400          # これより前に入れた実行は戻さない(記録に「中止」と書く)
ACTIVE_STATES = ("queued", "running")
STATUS_STEP_KEYS = ("key", "label", "state", "detail", "startedAt", "finishedAt")
GB = 1024 ** 3
DISK_RETRY = 30.0      # 空き容量が下限を切って実行を始めない間、見直す間隔(秒。submit・中止でもすぐ見直す。F1 F0-1)
MACHINE_KEYS = ("engine", "device", "llmModel")   # status の machine 欄に出すこの PC の設定(flow/machine.py)
GPU_FUNCS = ("info", "detect", "probe", "get")    # ytt/gpuinfo(F1 の F0-2)の GPU を調べる関数の名前の候補(先にある物を使う)
ESTIMATE_STEPS = ("analyze", "adopt", "export", "transcribe", "pack", "deliver")   # 見積もりで行にする段(並びは run.steps = run.steps_of の 1 か所)


class SpecVersionError(ValueError):
    """submit の封筒の束の版(specVersion)がこの ② と違う(送る側か ② を新しくする)= 入口は 400 spec_version"""


class BadSpecError(ValueError):
    """submit の束に知らない節・項目・合わない値がある = 入口は 400 bad_spec"""


def check_spec(envelope, spec):
    """submit の前に束の版と形を確かめる(F1 F0-1。アプリが「更新してください」と出せるように、ほかの理由と分ける)。
    版の違い -> SpecVersionError・束の知らない項目・合わない値 -> BadSpecError。封筒そのものの形は Run.from_envelope が確かめる"""
    if isinstance(envelope, dict) and "specVersion" in envelope:
        try:
            _envelope.version_of(envelope)   # 読めるのは今の版だけ
        except ValueError as e:
            raise SpecVersionError(str(e))
    try:
        _spec.validate(_spec.merge(spec))
    except ValueError as e:
        raise BadSpecError(str(e))


def disk_blocked(case_root, min_gb, usage=None):
    """空き容量の下限: case_root(まだ無ければある所まで上へ)のドライブの空きが min_gb(GB)より少なければ {"reason": "disk", "freeGB", "minGB"}、
    足りていれば・測れなければ・下限が 0 以下なら None(測れないときは止めない = 止める側に倒すと何も流れなくなる)"""
    if not _schemas.is_num(min_gb) or min_gb <= 0 or not case_root:
        return None
    try:
        free = int((usage or fsio.disk_space)(case_root)[0])
    except (OSError, ValueError, TypeError):
        return None
    if free >= min_gb * GB:
        return None
    return {"reason": "disk", "freeGB": round(free / GB, 1), "minGB": min_gb}


def gpu_info():
    """GPU の情報(ytt/gpuinfo。F1 の F0-2 が作る)-> {name, vramGB, ...} か None(まだ無い・読めない・調べに失敗)"""
    try:
        gpuinfo = importlib.import_module("ytt.gpuinfo")   # 遅い import(無ければ None。sys.modules の差し替えも効く = テスト)
    except ImportError:
        return None
    fn = next((getattr(gpuinfo, n) for n in GPU_FUNCS if callable(getattr(gpuinfo, n, None))), None)
    try:
        got = fn() if fn else None
    except Exception:   # noqa: BLE001  (GPU を調べられなくても status は返す)
        return None
    return dict(got) if isinstance(got, dict) else None


def busy_reason(active, same, what=""):
    """順番待ちに入れられない理由(入れられれば None)。same(実行) = 同じ配信・文書・動画か。what = 理由の頭(「この配信は」など)"""
    if any(same(r) for r in active):
        return what + "すでに実行中・順番待ちです"
    if len(active) >= MAX_WAITING:
        return "順番待ちが多すぎます(%d本まで)" % MAX_WAITING
    return None


def doc_id_ok(v):
    """文書の id の形(英数字と - _ の 40 字まで)"""
    return isinstance(v, str) and 1 <= len(v) <= 40 and all(c.isalnum() or c in "-_" for c in v)


def _check_media(path):
    """② の口の動画ファイル: 実在する絶対パスで、拡張子が動画・音声(ytt/tools.MEDIA_TYPES)の物だけ。合わなければ理由つきの ValueError"""
    if not isinstance(path, str) or not os.path.isabs(path) or not os.path.isfile(path):
        raise ValueError("封筒.input.path の動画が見つかりません(絶対パスで、ある動画を指してください)")
    if os.path.splitext(path)[1].lower() not in _ytools.MEDIA_TYPES:
        raise ValueError("封筒.input.path は動画・音声ファイルにしてください(対応: %s)" % " ".join(sorted(_ytools.MEDIA_TYPES)))


def _people_streamer(bundle, env=None):
    """束の hints.people の先頭 -> 照らし合わせた配信者の名前(ytt/colors.resolve)か None(出る人が無い・合わない = 実行中に決める)"""
    people = _spec.hint_people(bundle)["people"]
    if not people:
        return None
    try:
        who, _hex = _colors.resolve(people[0]["name"], env=env)
    except ValueError:
        return None
    return who


def _rec_key(rec):
    """記録の 1 行 -> 配信・文書・動画ごとの前回の結果を引くキー(Run.key と同じ形)"""
    if rec.get("kind") == "file":
        return ("file", rec.get("sourcePath"))
    return ("doc", rec.get("docId")) if rec.get("kind") == "doc" else ("video", rec.get("videoId"))


def _status_of(run):
    """status() の 1 件(進み具合だけ。全部は snapshot の public)"""
    steps = [{k: s[k] for k in STATUS_STEP_KEYS if k in s} for s in run.steps]
    started = [s["startedAt"] for s in steps if isinstance(s.get("startedAt"), int)]
    return {"id": run.id, "kind": run.kind(), "title": run.title, "requestId": run.request_id, "state": run.state,
            "stateLabel": RUN_STATE_LABELS["nothing" if run.nothing and run.state == "done" else run.state],
            "message": run.message, "error": run.error, "nothing": run.nothing,
            "step": next((s["key"] for s in steps if s["state"] == "run"), None),
            "created": int(run.created * 1000), "startedAt": min(started) if started else None,
            "finished": int(run.finished * 1000) if run.finished else None, "resultPath": run.result_path, "steps": steps}


BOARD_PREFIX = "run"   # 掲示板(flow/board.py)の id の頭
RETRY_STATES = ("error", "cancelled")   # 掲示板からやり直せる実行の状態


def result_case(path):
    """結果の束のパス <案件>/作業用/runs/<id>.json -> 案件の根か None(形が違う・相対パス)。ファイルには触らない"""
    if not isinstance(path, str) or not os.path.isabs(path):
        return None
    runs = os.path.dirname(path)
    work = os.path.dirname(runs)
    if os.path.basename(runs) != _placement.RUNS_DIR or os.path.basename(work) != _schemas.WORK_DIR:
        return None
    return os.path.dirname(work)


def board_job(run, closed=False):
    """Run -> 掲示板の Job(flow/board.py の形。kind run・steps = status() の steps)。案件の根は結果の束から(まだ無ければ None = 掲示板の case_hook が
    target の動画・文書から引く)。phase = 実行中の段の名前と詳細(無ければ run.message)・progress = 済んだ段の割合(済みは 1)・waiting = 段が SLOTS 待ち"""
    s = _status_of(run)
    steps, state = s["steps"], run.state
    cur = next((x for x in steps if x["state"] == "run"), None)
    detail = (cur.get("detail") or "") if cur else ""
    phase = ("%s %s" % (cur["label"], detail)).strip() if cur else (run.message or "")
    ended = sum(1 for x in steps if x["state"] in run_mod.DONE_STEPS or x["state"] == "error")
    progress = 1.0 if state == "done" else (ended / len(steps) if steps and state == "running" else None)
    return {"id": "%s:%s" % (BOARD_PREFIX, run.id), "kind": "run", "case": result_case(run.result_path),
            "target": {"videoId": run.video_id, "docId": run.doc_id, "path": run.source_path}, "title": run.title or run.id,
            "state": state, "stateLabel": s["stateLabel"], "phase": phase, "progress": progress, "waiting": _yjobs.WAIT_MESSAGE in detail,
            "createdAt": s["created"], "startedAt": s["startedAt"], "finishedAt": s["finished"],
            "error": {"code": "run", "text": run.error, "detail": None} if state == "error" and run.error else None,
            "canCancel": state in ACTIVE_STATES and not run.cancel and not closed, "canRetry": state in RETRY_STATES and not closed, "steps": steps}


class Queue(run_mod.Runner):
    """② の待ち行列と実行の糸(Runner を継ぐ)。log_dir = 待ちの記録と終わった実行の記録を置くフォルダ(None = メモリだけ = 起動し直しで戻さない)。
    hook(継ぐ側が埋める。既定は何も知らない): Runner の hook・build_spec(束を持たない実行の束)・_on_error(失敗で終わった実行)"""

    def __init__(self, client, env=None, poll=1.0, sleep=None, log=None, clock=None, find_pack=None, tools=None, log_dir=None,
                 log_max=LOG_MAX_BYTES):
        """前の起動の待ちの記録があれば読んで戻し、糸を起こす(継ぐ側は、hook が使う値を super().__init__ の前に置く)"""
        super().__init__(client, env=env, poll=poll, sleep=sleep, log=log, clock=clock, find_pack=find_pack, tools=tools)
        self.log_path = os.path.join(log_dir, runlog.RUNS_LOG) if log_dir else None
        self.active_path = os.path.join(log_dir, ACTIVE_FILE) if log_dir else None   # 待ち・実行中の記録(M5)
        self.active_error = ""     # 最後に待ちの記録を書けなかった理由(書けたら空に戻す)
        self._active_lock = threading.Lock()   # 待ちの記録のファイル(これを持ったまま self.cv を取る。逆の順では取らない)
        self.log_max = log_max
        self.log_error = ""        # 最後に記録を書けなかった理由(書けたら空に戻す)
        self._log_lock = threading.Lock()   # 記録のファイルと past(self.cv とは別。self.cv を持ったまま _log を呼ばない)
        self._past = collections.OrderedDict()   # (種類, id) -> 最後の記録(書いた順)
        if self.log_path:
            for rec in runlog.read_runs_log(self.log_path, LOG_READ_BYTES):
                self._remember(rec)
        self.lock = threading.Lock()
        self.cv = threading.Condition(self.lock)
        self.runs = []
        self.pushed = 0         # 積んだ回数(画面が /api/status で比べ、増えたら実行の一覧をすぐ読み直す)
        self.live_hook = None  # ライブの封筒の受け口(set_live_hook)
        self.learning = None    # 学習データの読み手(flow/learning.Learning。入口が machine の learningDir があるときに入れる。束の版を束に入れる。F1 F6a)
        self.finished_hook = None   # 実行が終わって記録を書いたあとに呼ぶ fn(run)(set_finished_hook。画面なしの送り返しの zip。F1 F6a)
        self.thread = None
        self.blocked = None     # 空き容量が下限を切って次の実行を始めていない理由(disk_blocked の形。F1 F0-1)
        self._gpu_lock = threading.Lock()
        self._gpu_thread = None   # GPU を調べる糸(status の machine.gpu。初めて聞かれたときに 1 回)
        self._gpu_value = None
        restored = self._restore_active()   # 前の起動で待ち・実行中だった実行(M5)
        if restored:
            with self.cv:
                self.runs.extend(restored)
                self._wake()
        if self.active_path and os.path.isfile(self.active_path):
            self._save_active()   # 戻さなかった(古い・壊れた)分を記録から外す

    # ------------------------------------------------------------ hook(継ぐ側が埋める)
    def build_spec(self):
        """受付で組む束 -> (束, 知らせの文のリスト)。既定 = 束の既定 + この PC の設定(flow/machine.py)・知らせなし"""
        return _machine.overlay(_spec.validate(_spec.merge(None)), env=self.env), []

    def _check_input(self, run):
        """submit の入力の検査(hook)。既定 = 動画ファイルは実在する動画・音声だけ(_check_media)。入口は文書があるかも見る"""
        if run.kind() == "file":
            _check_media(run.source_path)

    def _base(self):
        """受付の束の土台 -> (束, 知らせ)= build_spec(入口の AutoRunner は 1 回の受付の間だけ覚える)"""
        return self.build_spec()

    def _accept(self, run, convert=False):
        """受けたときに決める物を Run に置く(RS7-1 S4。submit は必ず通す = RV A1)。既定 = 束が無ければ build_spec で組む(知らせは run.notes)・
        配信者が決まっていなければ(束の hints.streamer が null)束の hints.people の先頭を照らし合わせた名前(合わなければ決めない)。
        入口の AutoRunner は友人の区間の長さ・覚えた名前からの配信者・届ける名前の頭も決める。
        convert = 束の無い待ちの記録を戻すとき(まだ決めていない物だけ)"""
        if run.spec is None:
            bundle, notes = self._base()
            run.spec = bundle
            run.notes = list(notes)
        if run.streamer is None and not convert:
            run.streamer = _people_streamer(run.spec, self.env)

    def _on_error(self, run):
        """失敗で終わった実行(記録に書く前。入口は友人へ、できていたパックと失敗の理由を届ける)。既定は何もしない"""

    def _checkpoint(self, run):
        """段の始まりと済んだとき: 待ちの記録に残す(M5。起動し直したらこの段から)"""
        self._save_active()

    # ------------------------------------------------------------ 起動し直しで戻す(M5)
    def _save_active(self):
        """待ち・実行中の実行を autorun-active.json に残す(self.cv の外で呼ぶ)。終了(close)のあとは書かない
        (止めた実行を「次の起動で続ける」形のまま残すため)。人が中止した実行は入れない。書けなくても実行は止めない"""
        if not self.active_path:
            return
        with self._active_lock:
            with self.cv:
                if self.closed:
                    return
                items = [r.saved() for r in self.runs if r.state in ACTIVE_STATES and not r.cancel]
            try:
                fsio.write_json(self.active_path, {"v": ACTIVE_VERSION, "runs": items}, indent=None)
                self.active_error = ""
            except (OSError, TypeError, ValueError) as e:
                self.active_error = "%s %s" % (e.__class__.__name__, getattr(e, "strerror", "") or "")

    def _restore_active(self):
        """前の起動の待ちの記録 -> 戻す Run のリスト(先に入れた順)。古すぎるものは記録に「中止」と書いて戻さない"""
        if not self.active_path:
            return []
        try:
            d = fsio.read_json_file(self.active_path, ACTIVE_READ_MAX)
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as e:
            self.log("まとめて実行: 前の起動の待ちの記録を読めませんでした(%s)。戻さずに続けます" % e.__class__.__name__)
            return []
        ver = d.get("v") if isinstance(d, dict) else None
        items = d.get("runs") if ver == ACTIVE_VERSION else None
        if ver != ACTIVE_VERSION:
            self.log("まとめて実行: 前の起動の待ちの記録は古い形(版 %s)だったので、戻さずに捨てました" % (ver,))
        out, seen = [], set()
        for x in items if isinstance(items, list) else []:
            run = Run.restore(x)
            if run is None:   # 壊れた・今は無い形(消した形の記録など)の記録: 戻さずに、どれを飛ばしたかだけ残す
                d = x if isinstance(x, dict) else {}
                self.log("まとめて実行: 前の起動の待ちの記録を戻せないので飛ばしました(id %s・形 %s・%s)"
                         % (str(d.get("id") or "?")[:20], str(d.get("mode") or "?")[:20], str(d.get("title") or "")[:60]))
                continue
            if run.id in seen:
                continue
            seen.add(run.id)
            if time.time() - run.created > RESTORE_MAX_AGE:
                run.state, run.message, run.finished = "cancelled", "ホームを起動し直したとき、%d 日より前に入れた実行だったので続けませんでした" % (RESTORE_MAX_AGE // 86400), time.time()
                self._log(run)
                continue
            if run.spec is None:   # 束の無い記録: 受付で決める物を今決める
                try:
                    self._accept(run, convert=True)
                except (OSError, ValueError, TypeError, KeyError) as e:   # 決められなくても戻す(束の無い実行は _execute が組む)
                    self.log("まとめて実行: 前の起動の待ちの記録を今の形にできませんでした(%s %s)" % (run.id, e.__class__.__name__))
            out.append(run)
        if out:
            self.log("まとめて実行: ホームを起動し直したので、待ち・実行中だった %d 件を続けます(%s)" % (len(out), "・".join(r.title or r.id for r in out[:5])))
        return out

    # ------------------------------------------------------------ 積む
    def _push(self, run):
        """順番待ちに入れる(呼ぶのは self.cv を持っている間)。-> run.public()"""
        self.runs.append(run)
        self.pushed += 1
        self._trim()
        self._wake()
        return run.public()

    def _bundle_for(self, envelope, spec):
        """封筒 + 束の差分 -> (版 2 の封筒, 受付の束, 知らせ)。土台 = hook の build_spec(_base)に差分を重ね(spec.merge_onto)、
        最後にこの PC の設定(flow/machine.py)を重ねる(差分の機器・エンジンより、この PC の設定が勝つ)"""
        env, diff = _envelope.read(envelope, spec)
        base, notes = self._base()
        bundle = _machine.overlay(_spec.validate(_spec.merge_onto(base, diff)), env=self.env)
        return env, bundle, notes

    def submit(self, envelope, spec=None):
        """② の口(受付はこの 1 本だけ = RV A1。HTTP は POST /api/flow/submit): 封筒(flow/envelope.py)+ 束(flow/spec.py の差分。
        変えたい所だけでよい。全部でもよい)を受けて待ち行列に積む -> run.public()。欄から封筒と差分を作るのは flow/order.py(画面は UIKit.flow.order)。
        束 = 土台(hook の build_spec。素の Queue = 既定 + この PC・入口 = 画面の設定)+ 差分 + この PC の設定 = 受けたときの束のまま流す。
        受けたときに決める物は hook の _accept(必ず通す。配信者・友人の区間の長さ・届ける名前の頭)。
        動画ファイルの封筒(kind file)は、実在する絶対パスで拡張子が動画・音声(ytt/tools.MEDIA_TYPES)の物だけ。届け先が無ければ届けない(既定)。
        配信者: 名前があれば色の一覧と照らし合わせる(ytt/colors.resolve。合わなければ ValueError。友人の依頼(requestId あり)は照らし合わせずそのまま)・空 = 色なし・null = _accept が決める(束の hints.people の先頭 → 入口は覚えた名前・チャンネル名から。決まらなければ実行中に)。
        封筒・束の形が違う・同じ入力(配信・文書・動画)か同じ id が待ち・実行中・待ちが多すぎれば理由つきの ValueError"""
        check_spec(envelope, spec)   # 版の違い・束の形を先に(SpecVersionError・BadSpecError。どちらも ValueError)
        if isinstance(envelope, dict) and envelope.get("kind") == "live":
            return self._submit_live(envelope, spec)
        env, bundle, notes = self._bundle_for(envelope, spec)
        run = Run.from_envelope(env, bundle)
        run.notes = list(notes)
        self._check_input(run)
        if isinstance(run.streamer, str) and run.streamer:
            if not run.streamer.strip():
                run.streamer = ""
            elif not run.request_id:
                run.streamer = _colors.resolve(run.streamer, env=self.env)[0]   # 見つからなければ ValueError(始める前に断る)
        with self.cv:
            if self.closed:
                raise ValueError(CLOSED_MSG)
            why = busy_reason(self._active_runs(), lambda r: r.key() == run.key(), "同じ入力が")
            if why:   # 先に断る物を断る(_accept が読む前に)
                raise ValueError(why)
        self._accept(run)
        with self.cv:
            if self.closed:
                raise ValueError(CLOSED_MSG)
            active = self._active_runs()
            if any(r.id == run.id for r in active):
                raise ValueError("その依頼(id %s)はもう待ち・実行中です" % run.id)
            why = busy_reason(active, lambda r: r.key() == run.key(), "同じ入力が")
            if why:
                raise ValueError(why)
            out = self._push(run)
        self._save_active()
        return out

    def set_finished_hook(self, fn):
        """実行が 1 本終わって(完了・失敗・中止)記録を書いたあとに fn(run) を呼ぶ(糸の中・self.cv の外。失敗してもログだけ)"""
        self.finished_hook = fn

    def _finished(self, run):
        fn = self.finished_hook
        if fn is None:
            return
        try:
            fn(run)
        except Exception as e:   # 終わったあとの物で次の実行を止めない
            self.log("まとめて実行: 終わったあとの処理に失敗しました: %s %s" % (e.__class__.__name__, str(e)[:200]))

    def set_live_hook(self, fn):
        """ライブの封筒(kind live)の受け口を登録する: fn(封筒(検査済み), 束(検査済み)) -> {"id", ...}(ライブ係 = RS7-2 G2。入口が登録)"""
        self.live_hook = fn

    def _submit_live(self, envelope, spec):
        """kind live は Run を作らず(待ち行列に積まない)live の hook へ。hook が無ければ理由つきの ValueError"""
        env, spec = _envelope.read(envelope, spec)
        bundle = _spec.validate(_spec.merge(spec))
        hook = self.live_hook
        if hook is None:
            raise ValueError("ライブの依頼を受ける係がまだ登録されていません")
        return hook(env, bundle)

    # ------------------------------------------------------------ 見積もり(気が利く画面へ 段4)
    def estimate(self, envelope, spec=None):
        """submit と同じ封筒 + 束の差分(RV A1。HTTP は POST /api/flow/estimate {envelope, spec})で、実行と同じ規則の段ごとの本数と飛ばす理由を返す
        (何も書き込まない・積まない)。「飛ばすか」の判定は flow/run.py の _analyze_plan(analyze_verdict・redo_reason)・adopted_ids・tx_verdict・pack_verdict で、実行の段と同じ関数
        (鍵の比べも同じ _pack_state)。実行は実行したときの状態で決めるので、前の段の結果しだいの本数は None(分からない)で返す。
        文書の一覧と紐づけは hook の _docs・_pick_doc。-> {"steps": [{"key", "label", "count" (None = 前の段の結果しだい), "note"}],
        "total": 分かっている本数の合計, "nothing": bool, "reason", "notes"}。配信(まとめて実行・友人の依頼)と文書だけ数える(ほかは段だけ・本数は None)。
        段 deliver(届け先がある)の行は本数 None・note「パックのあとで決まります」。封筒・束の形が違えば理由つきの ValueError"""
        check_spec(envelope, spec)
        env, bundle, _notes = self._bundle_for(envelope, spec)
        run = Run.from_envelope(env, bundle)
        docs = self._docs()
        if run.mode == DOC_MODE:   # 文書単位(文字起こし → パック)
            return self._estimate_docs(docs, run)
        if run.kind() != "url":   # 配信(まとめて実行・友人の依頼)のほか = 段だけ・本数は None
            return self._estimate_out([{"key": s["key"], "label": s["label"], "count": None, "note": ""} for s in run.steps], [])
        video_id, top = run.video_id, run.top
        st, obj = self.tools.video(urllib.parse.quote(str(video_id or "")))
        v = (obj.get("video") or {}) if st == 200 and isinstance(obj, dict) else {}
        mine = self._mine(run, v)
        adopted = adopted_ids(mine)
        clips = self._clips(v, run)
        picked = [(m, self._pick_doc(docs, video_id, m.get("id"), m["path"])) for m in clips]
        no_tx = [m for m, d in picked if tx_verdict(bool(d), self._force(run)) != "skip"]
        opts = self._pack_settings(run)
        packable = [m for m, d in picked if d and self._pack_verdict(run, d, m["path"], opts, v) != "skip"]
        steps = []
        pending = False   # 前の段の結果しだい(解析・採用のあとで本数が決まる)
        for key in [s["key"] for s in run.steps if s["key"] in ESTIMATE_STEPS]:   # 実行と同じ段の並び(run.steps = steps_of。話者分離・あとの解析は数えない)
            label, count, note = STEP_LABELS[key], 0, ""
            if key == "analyze":
                count, note = (0, "解析済み") if self._analyze_plan(run, v)[0] == "skip" else (1, "")   # 足りなければ解析し直すも実行と同じ
                pending = pending or count > 0
            elif key == "adopt":
                if any(m.get("status") in ("adopted", "exported") for m in mine):
                    note = "採用・書き出し済みのマークを使います"
                elif pending:
                    count, note = None, "解析のあとで、点数の高い %d 件" % (top or _spec.DEFAULT_TOP)
                else:
                    cands = [m for m in mine if not m.get("status")]
                    count = min(len(cands), top or _spec.DEFAULT_TOP)
                    note = "" if count else "採用できる候補がありません"
                pending = pending or count is None or bool(count)
            elif key == "export":
                count = None if pending and not adopted else len(adopted)
                note = "" if count else ("採用のあとで決まります" if count is None else "採用したマークがありません" if not clips else "書き出し済み %d 本" % len(clips))
                pending = pending or bool(count)
            elif key == "transcribe":
                count = None if pending else len(no_tx)
                note = "書き出しのあとで決まります" if count is None else ("" if count else ("%d 本とも文字起こし済み" % len(clips) if clips else "書き出した切り抜きがありません"))
                pending = pending or bool(count)
            elif key == "pack":
                count = None if pending else len(packable)
                note = "文字起こしのあとで決まります" if count is None else ("" if count else ("パック済み(「パックがあれば作り直す(上書き)」を選ぶと作り直します)" if clips else "文字起こしのある切り抜きがありません"))
            elif key == "deliver":   # 届け先なし = チェックを外したまとめて実行(送らなかった記録だけ残す)
                count, note = (None, "パックのあとで決まります") if run.deliver_dir else (0, "チェックを外したので送りません")
            steps.append({"key": key, "label": label, "count": count, "note": note})
        return self._estimate_out(steps, [] if st == 200 else ["配信がスタジオに見つかりません"])

    def _estimate_docs(self, docs, run):
        """estimate の文書単位(文字起こし → パック。文書 1 本 = run.doc_id。画面は文書ごとに見積もって足す)"""
        by = {d["id"]: d for d in docs}
        tx, pk, notes = 0, 0, []
        for tid in (run.doc_id,):
            d = by.get(tid) if doc_id_ok(tid) else None
            if not d:
                notes.append("見つからない文書があります")
                continue
            if tx_verdict(bool(d.get("count")), False) != "skip":   # 文書単位は force でも作り直さない
                tx += 1
                pk += 1
                continue
            if pack_verdict(self._repack(run), *self._pack_probe(run, d, d.get("sourcePath") or "", self._pack_settings(run))) != "skip":
                pk += 1
        steps = [{"key": "transcribe", "label": STEP_LABELS["transcribe"], "count": tx, "note": "" if tx else "文字起こし済み"},
                 {"key": "pack", "label": STEP_LABELS["pack"], "count": pk, "note": "" if pk else "パック済み(「パックがあれば作り直す(上書き)」を選ぶと作り直します)"}]
        return self._estimate_out(steps, notes)

    def _pack_probe(self, run, doc, media, opts, v=None):
        """パックの判定に渡す (鍵の比べ, 既定のパックがあるか)。実行と同じ _pack_state(force のときは比べない)。見積もりは失敗しない"""
        if self._repack(run):
            return "none", False
        try:
            full = self._full_doc(doc)
            state = self._pack_state(run, full, media, opts, v)[0] if full else "none"
        except Exception:   # 見積もりの途中の読み損ない(実行の側は段の失敗として扱う)
            state = "none"
        return state, bool(self.find_pack(media))

    def _pack_verdict(self, run, doc, media, opts, v=None):
        """切り抜き 1 本のパックの判定(pack_verdict。実行の _step_pack と同じ材料)"""
        return pack_verdict(self._repack(run), *self._pack_probe(run, doc, media, opts, v))

    @staticmethod
    def _estimate_out(steps, notes):
        known = [s["count"] for s in steps if s["count"] is not None]
        nothing = all(s["count"] == 0 for s in steps)
        reason = "・".join([s["note"] for s in steps if s["note"]] + notes) if nothing else ""
        return {"steps": steps, "total": sum(known), "nothing": nothing, "reason": reason, "notes": notes}

    # ------------------------------------------------------------ 状態
    def _active_runs(self):
        """順番待ち・実行中の実行(呼ぶのは self.cv を持っている間)"""
        return [r for r in self.runs if r.state in ACTIVE_STATES]

    def _wake(self):
        """順番待ちを動かす(呼ぶのは self.cv を持っている間)"""
        self.cv.notify_all()
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self._loop, name="autorun", daemon=True)
            self.thread.start()

    def cancel(self, run_id):
        """待ちの実行はここで「中止」に・実行中の実行は止める印(段が止まったら _loop が終える)。-> run.public()。無い id は ValueError"""
        ended = False
        with self.cv:
            run = next((r for r in self.runs if r.id == run_id), None)
            if run is None:
                raise ValueError("その実行はありません")
            if run.state == "queued":
                run.state, run.message, run.finished = "cancelled", "中止しました", time.time()
                ended = True
            elif run.state == "running":
                run.cancel = True
                run.message = "中止しています…"
            out = run.public()
        if ended:   # 順番待ちの中止はここで終わる(実行中の分は _loop の終わりで書く)
            self._log(run)
        self._save_active()   # 中止した実行は起動し直しても戻さない
        return out

    _status_hook = None   # status() の live 欄を返す関数(set_status_hook。無ければ録画・検出は 0)

    def set_status_hook(self, fn):
        """status() の live 欄の出どころを外から足す(RS7-2 G5a)。Queue はライブ(録画・検出)を知らないので、入口が Live の状態を渡す。
        fn() -> {"recording": 録画中の数, "detecting": 検出中の数, ほかの数の欄...}(どの欄も 0 でなければ idle は偽)。None で外す"""
        self._status_hook = fn

    def _live_status(self):
        """status() の live 欄。hook が無ければ {recording: 0, detecting: 0}。hook が失敗したら数は None と error(idle は偽 = 閉じない側に倒す)"""
        out = {"recording": 0, "detecting": 0}
        fn = self._status_hook
        if fn is None:
            return out
        try:
            got = fn()
        except Exception as e:   # noqa: BLE001  (ライブの状態を読めなくても status は返す)
            return {"recording": None, "detecting": None, "error": "ライブの状態を読めませんでした(%s)" % e.__class__.__name__}
        for k, v in (got or {}).items() if isinstance(got, dict) else ():
            if isinstance(k, str) and (v is None or (isinstance(v, int) and not isinstance(v, bool) and v >= 0)):
                out[k] = v
        return out

    def status(self):
        """待ち・実行中が 0 か と進み具合(画面・CLI が聞く口。HTTP は入口の GET /api/flow/status)。
        -> {"queued", "running", "done"(この起動で終わった数 = 済み・失敗・中止。メモリに残る MAX_KEEP 件まで),
        "idle"(待ち・実行中が 0 かつ live の数がどれも 0), "closed",
        "live": {"recording", "detecting", ...}(set_status_hook の数。録画中・検出中。読めなければ None と error。RS7-2 G5a),
        "runs": [{id, kind, title, requestId, state, stateLabel, message, error, nothing, step(実行中の段), created, startedAt, finished,
        resultPath, steps: [{key, label, state, detail, startedAt?, finishedAt?}]}](入れた順)}"""
        with self.cv:
            runs = [_status_of(r) for r in self.runs]
            closed = self.closed
        live = self._live_status()   # hook は録画元に問い合わせることがあるので self.cv の外で
        n = collections.Counter(r["state"] for r in runs)
        queued, running = n["queued"], n["running"]
        live_idle = all(v == 0 for k, v in live.items() if k != "error") and "error" not in live
        return {"queued": queued, "running": running, "done": len(runs) - queued - running, "idle": queued + running == 0 and live_idle,
                "closed": closed, "live": live, "runs": runs, "blocked": self.blocked, "machine": self.machine_status()}

    def machine_status(self):
        """status の machine 欄: {engine, device, llmModel, gpu}(この PC の設定 flow/machine.py と GPU の情報。F1 F0-1)。
        設定を読めなければ値は None。gpu は初めて聞かれたときに裏で 1 回調べ、済むまで・調べられなければ None"""
        try:
            m = _machine.load(env=self.env)
        except (OSError, ValueError):
            m = {}
        out = {k: m.get(k) for k in MACHINE_KEYS}
        with self._gpu_lock:
            if self._gpu_thread is None:
                self._gpu_thread = threading.Thread(target=self._probe_gpu, name="gpuinfo", daemon=True)
                self._gpu_thread.start()
            out["gpu"] = self._gpu_value
        return out

    def _probe_gpu(self):
        got = gpu_info()
        with self._gpu_lock:
            self._gpu_value = got

    def disk_check(self):
        """次の実行を始める前の空き容量の下限(machine の caseRoot のドライブと diskMinGB)-> disk_blocked の形か None。
        設定を読めなければ None(止めない)。テストは差し替える"""
        try:
            m = _machine.load(env=self.env)
        except (OSError, ValueError):
            return None
        return disk_blocked(m.get("caseRoot"), m.get("diskMinGB"))

    def snapshot(self):
        """runs = メモリの実行(新しい順)・past = 配信・文書ごとの前回の結果のうちメモリに無いもの(記録のファイルから。新しい順・PAST_MAX 件まで)"""
        with self.cv:
            runs = [r.public() for r in reversed(self.runs)]
            keys = {r.key() for r in self.runs}
        with self._log_lock:
            past = [{k: rec.get(k) for k in PAST_KEYS} for key, rec in reversed(self._past.items()) if key not in keys][:PAST_MAX]
        return {"runs": runs, "past": past}   # 形の表 modes は読む画面が無いので返さない(10-19。まとめて実行は解析から全部だけ)

    def history(self, limit=None, offset=0, case=None):
        """終わった実行の記録(今のファイルと .1。新しい順)。-> {"runs", "total", "more", "offset"}。limit・offset は範囲に丸める。
        case = 案件の根(1 行の resultPath の案件がそれの物だけ。比べ方は flow/board.norm_case。RS8 の GET /api/flow/history)"""
        limit = HISTORY_DEFAULT if not isinstance(limit, int) or isinstance(limit, bool) else min(HISTORY_MAX, max(1, limit))
        offset = 0 if not isinstance(offset, int) or isinstance(offset, bool) else max(0, offset)
        if not self.log_path:
            return {"runs": [], "total": 0, "more": False, "offset": offset}
        with self._log_lock:   # 書き込み(.1 へ回す)と重ねない
            recs = runlog.read_runs_log(self.log_path)
        if case is not None:
            want = _board.norm_case(case)
            recs = [r for r in recs if want is not None and _board.norm_case(result_case(r.get("resultPath"))) == want]
        recs.reverse()
        return {"runs": recs[offset:offset + limit], "total": len(recs), "more": offset + limit < len(recs), "offset": offset}

    # ------------------------------------------------------------ 掲示板(RS8 の ② の口 S3。flow/board.py)
    _board_ref = None   # attach_board した掲示板(親子の印を付けるため)

    def attach_board(self, board):
        """掲示板にこの待ち行列の実行を載せる(引く形・頭 run = 問い合わせのたびに board_jobs を読む)。取り消し・やり直しも掲示板の id で
        (board_cancel)。入口(src/app/server.py)が 1 回呼ぶ。器のジョブ(Run.owned)は親の下に畳む印を付ける"""
        self._board_ref = board
        board.register(BOARD_PREFIX, source=self.board_jobs, cancel=self.board_cancel)

    def board_jobs(self):
        """掲示板の引く形: メモリの実行(入れた順)-> [Job]。実行が今待っている器のジョブ(Run.owned = 編集・スタジオの解析・パック)には親の印を付ける"""
        with self.cv:
            closed = self.closed
            items = [(board_job(r, closed), r.owned) for r in self.runs]
        b = self._board_ref
        for job, owned in items if b is not None else ():
            tool, ids = owned if isinstance(owned, tuple) and len(owned) == 2 else (None, ())
            prefix = _board.OWNED_PREFIX.get(tool)
            for i in list(ids or ()) if prefix else ():
                try:
                    b.link("%s:%s" % (prefix, i), job["id"])
                except ValueError:   # 器の id が掲示板の形に合わない(印を付けないだけ)
                    pass
        return [job for job, _ in items]

    def board_cancel(self, run_id):
        """掲示板の取り消し: cancel と同じ(待ちは「中止」・実行中は止める印)。無い id は LookupError"""
        with self.cv:
            if not any(r.id == run_id for r in self.runs):
                raise LookupError("その実行はありません")
        self.cancel(run_id)

    def _remember(self, rec):
        """past の元に入れる(呼ぶのは self._log_lock を持っている間か、__init__ の中)。
        記録に残っている「あとから解析」(mode post_analyze)は入れない(案件の行の「前回」は、依頼・まとめて実行の結果のまま。history には残る)"""
        if rec.get("mode") == "post_analyze":
            return
        k = _rec_key(rec)
        self._past.pop(k, None)
        self._past[k] = rec
        while len(self._past) > PAST_KEEP:
            self._past.popitem(last=False)

    def _log(self, run):
        """終わった実行を記録のファイルに1行で書く(B-6)。1つの実行は1回だけ(run.logged)。self.cv の外で呼ぶ。
        書けなくても実行は止めない(clientlog._write と同じ)。1行 = Run.public() + v"""
        with self._log_lock:
            if run.logged:
                return
            run.logged = True
            rec = dict(run.public(), v=runlog.LOG_VERSION)
            self._remember(rec)
            if not self.log_path:
                return
            try:
                fsio.append_line(self.log_path, json.dumps(rec, ensure_ascii=False) + "\n", self.log_max)   # 記録のファイルに 1 行ずつ書く形は 1 か所(ytt/fsio)
                self.log_error = ""
            except (OSError, TypeError, ValueError) as e:
                self.log_error = "%s %s" % (e.__class__.__name__, getattr(e, "strerror", "") or "")

    def close(self):
        """終了: 実行中の段を止める(self.closed で _check が止める。ツールの側のジョブも取り消す)。
        順番待ち・実行中の実行は、待ちの記録(autorun-active.json)に最後に書いた形のまま残り、次の起動で続く(M5)。記録(autorun-runs.jsonl)には書かない"""
        with self._active_lock:   # 書いている途中の待ちの記録を書き終えてから閉じる(このあとは書かない)
            with self.cv:
                self.closed = True
                for r in self.runs:
                    if r.state == "queued":
                        r.message = "ホームを終了したので、次の起動で続けます"
                self.cv.notify_all()

    def _next_queued(self):
        """次に始める待ちの実行(呼ぶのは self.cv を持っている間): 優先度の表(flow/prio.py)の順 = 録画中のライブ(切り抜きの溜め)> 友人の依頼 >
        自分の配信のまとめて実行、同じなら入れた順(PRIO。動いている実行は止めない)"""
        queued = [r for r in self.runs if r.state == "queued"]
        return min(queued, key=lambda r: _prio.rank(_prio.of_run(r))) if queued else None

    def idle_for_later(self):
        """後回しの仕事(flow/prio.py の later)を始めてよいか: 待ち・実行中の実行が無く、録画中の録画が無い(status の hook の recording)。
        prio.watch が重い処理の枠に入れる(枠の錠の外で呼ばれる)。録画の状態を読めなければ偽"""
        with self.cv:
            if self.closed or self._active_runs():
                return False
        fn = self._status_hook
        if fn is None:
            return True
        try:
            live = fn() or {}
        except Exception:   # noqa: BLE001  (読めない = 空いていない側に倒す)
            return False
        return not live.get("recording")

    def _trim(self):
        done = [r for r in self.runs if r.state not in ACTIVE_STATES]
        for r in done[:-MAX_KEEP] if len(done) > MAX_KEEP else []:
            self.runs.remove(r)

    # ------------------------------------------------------------ 糸
    def _loop(self):
        while True:
            with self.cv:
                while not self.closed and not any(r.state == "queued" for r in self.runs):
                    self.blocked = None   # 待ちが無い = 止めている物も無い
                    self.cv.wait()
                if self.closed:
                    return
            blocked = self.disk_check()   # 空き容量の下限(F1 の決めたこと 7・F0-1。録画の開始と同じ数)。ファイルを読むので self.cv の外で
            with self.cv:
                changed = (blocked is None) != (self.blocked is None)
                self.blocked = blocked
                if blocked is not None:   # 始めない(待ちのまま)。間をおいて・submit・中止・終了で見直す
                    if changed:
                        self.log("まとめて実行: 空き容量が %s GB(下限 %s GB)なので、新しい実行を始めずに待ちます" % (blocked["freeGB"], blocked["minGB"]))
                    self.cv.wait(DISK_RETRY)
                    continue
                if self.closed:
                    return
                run = self._next_queued()
                if run is None:   # 見ている間に中止された
                    continue
                run.state, run.message = "running", ""
            self._save_active()   # 実行中になった(M5)
            try:
                self._execute(run)
                run.state = "cancelled" if run.cancel else "done"
                run.message = "中止しました" if run.cancel else (run.message or "完了")
            except Cancelled:
                run.state, run.message = "cancelled", "中止しました"
            except StepError as e:
                run.state, run.error, run.message = "error", str(e), "止まりました"
            except Exception as e:   # 想定外でも、次の配信の処理は続ける
                self.log("まとめて実行: 内部エラー: %s %s" % (e.__class__.__name__, str(e)[:200]))   # 例外の名前・原文はログへ(UI の見直し M9)
                run.state, run.error, run.message = "error", "ホームの想定外の不具合で止まりました。もう一度「実行」を押してください(済んだ段は飛ばします)。続くときは、詳しくの「ログ」を見てください", "止まりました"
            if self.closed and not run.cancel and run.state != "done":
                # 終了で止まった(M5): 記録には「中止」と書かず、待ちの記録(最後に書いた段の形)のまま次の起動で続ける
                run.state, run.error, run.message = "queued", "", "ホームを終了したので、次の起動で続けます"
                for s in run.steps:
                    if s["state"] == "run":
                        s["state"] = "wait"
                with self.cv:
                    self.cv.notify_all()
                continue
            run.finished = time.time()
            for s in run.steps:
                if s["state"] == "run":
                    s["state"] = "error" if run.state == "error" else "skip"
            if run.state == "error":   # 入口は友人へ、できていたパックと失敗の理由を届ける(hook)
                self._on_error(run)
            self._log(run)   # 記録のファイルへ(self.cv の外。B-6)
            with self.cv:
                self._trim()
                self.cv.notify_all()
            self._save_active()   # 終わった実行を待ちの記録から外す(M5)
            self._finished(run)   # 結果の束が書かれたあと(画面なしの送り返しの zip。F1 F6a)

    def _execute(self, run):
        """1 回の実行(_loop の糸から)。受けたときに組んだ束(Run.spec。RS7-1 S4)で流す。
        束の無い Run(受付を通さずに直に積んだ物)だけ、ここで hook の _accept(= build_spec)で組む"""
        if run.spec is None:
            self._accept(run)
        if self.learning is not None and run.spec is not None:   # 学習の束の版を束の post.learning.version に(束でない・版が既にあればそのまま。F1 F6a)
            run.spec = _learning.stamp(run.spec, self.learning)
        return run_mod.run(self.client, run, hooks=self)
