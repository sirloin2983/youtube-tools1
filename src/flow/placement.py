# -*- coding: utf-8 -*-
"""② 管理の層 flow: 置き場所の持ち主(役割で組み直す RS6 b-B0。2026-10-10。決定 3-29・
docs/design/rs6-survey-2026-10-10/option_b.md の 2 節・7 節の B-0 = 案件ごとのフォルダ(b2)の第 1 段)。

「どこに何があるか」をここ 1 か所で答える。**値は今と同じ**(新しく書くのは 作業用/runs/ と .flow.lock だけ。データは移さない)。

- 案件の根 `case_root(media)`: 配信(スタジオの書き出し)= <書き出し先>/<題名>/(ytt.names の規則。作業用/.studio-id が持ち主)・
  動画ファイル(依頼の動画・文書の元の動画 = 切り抜き)= その動画のあるフォルダ。`work_dir` = <案件>/作業用・`runs_dir` = <案件>/作業用/runs。
  どれも今ある物を引くだけ(作らない)。分からない・まだ無ければ None
- スタジオの data.json `studio_data()`: 規則は ytt.datadir の 1 か所(起動したスタジオが登録した場所 → STUDIO_HOME → YTT_DATA_DIR・既定)。
  読む側 = 案件(manage/cases の locations)と編集(src/editor/serve.py の studio_data_path → ytt/workdata.STUDIO_DATA)。
  スタジオ自身の ytt/studio_env.p("data.json") と workdata.set_root の読み込み直後の既定は ytt の側で flow を読めない(層の向き)ので変えず、
  ここが同じ ytt の値(スタジオの serve が datadir.register する場所)を読む向きにした
- 案件の身分証 `ensure_case(media)`: <案件>/case.json を無いときだけ作る(冪等。write_result が一緒に呼ぶ)。読むだけは `read_case(root)`
- 結果の束 `write_result(run)`: ② の 1 回の実行が終わったら <案件>/作業用/runs/<実行id>.json(形の名前 runlog.RESULT_SCHEMA)を原子的に書く。
  書けなくても実行は失敗にしない。入口の autorun-runs.jsonl の 1 行の resultPath(Run.public)が索引(読むのは runlog.read_result)
- `.flow.lock`: 1 つの作業データに ② は 1 つ。置き場所は作業データの根(ytt.datadir.data_root。inplace なら .runtime)。
  中身 {pid, port, at, token}。pid が動いていなければ取り残し = 無いのと同じ(ポートを書いた物は、そのポートが開いていることも見る =
  pid の使い回しを取り違えない)。入口は起動で acquire・終わるときに release。CLI は lock_info で動いている ② を見つけたらそのポートへ頼む

media(案件を引く手がかり。media_of(run))= {"kind": "video", "videoId", "title", "clips": [切り抜きのパス]} か {"kind": "file", "path": 動画のパス}。
"""
import hashlib
import json
import logging
import os
import secrets
import time

from ytt import datadir as _datadir, fsio as _fsio, layout as _layout, names as _names, procs as _procs, runtime as _runtime, \
    schemas as _schemas, version as _version, workdata as _workdata
from . import keys as _keys, runlog as _runlog

log = logging.getLogger("ytt.flow.placement")

STUDIO_DATA_NAME = "data.json"   # スタジオの全配信の候補・採用(作業データの studio の中)
CASE_NAME = "case.json"          # 案件の身分証(<案件>/case.json。ensure_case が無いときだけ作る)
CASE_SCHEMA = "youtube-tools-case/v1"
CASE_MAX = 64 * 1024
RUNS_DIR = "runs"                # 結果の束のフォルダ(<案件>/作業用/runs)
LOCK_NAME = ".flow.lock"         # ② が 1 つだけ動く印(作業データの根)
LOCK_MAX = 4096                  # 印はこれより大きければ読まない(壊れた物として扱う)
# 結果の束の input に写す Run.public の鍵(何を入れて始めた実行か)
INPUT_KEYS = ("kind", "videoId", "docId", "sourcePath", "title", "mode", "top", "marks", "ranges", "cut", "engine", "model", "overwrite",
              "requestId", "streamer", "onFail")
STEP_TIMES = ("startedAt", "finishedAt")   # 段の始まりと終わりの時刻(flow/run.py の _run_steps が置く。足すだけ = 読み手は無くても動く)


# ---------------------------------------------------------------- スタジオの data.json
def studio_data(repo_root=None, env=None, legacy=False):
    """スタジオの data.json の場所(読むだけの側が使う)。repo_root = ツールの親(src。None = このリポジトリ)・env = 環境変数(テスト用。
    渡したときは登録を見ない)。legacy=True(編集の起動のとき)は、決めた場所に無く・登録も STUDIO_HOME も無ければ以前の場所
    (スタジオのフォルダ = 移す前のデータ)"""
    path = os.path.join(_datadir.resolve("studio", repo_root, env), STUDIO_DATA_NAME)
    if not legacy or os.path.isfile(path) or _datadir.registered("studio") or _datadir.override("studio", env):
        return path
    return os.path.join(_layout.tool_dir("studio", repo_root), STUDIO_DATA_NAME)


# ---------------------------------------------------------------- 案件の根
def _folder_of(path):
    """動画のパス → 置いてあるフォルダ(作業用/ の中の途中のファイル = <名前>_edit.mp4 などは、その上 = 案件の根)"""
    d = os.path.dirname(os.path.abspath(path))
    return os.path.dirname(d) if os.path.basename(d) == _schemas.WORK_DIR else d


def case_root(media, out_dir=None):
    """案件の根(今ある物だけ。作らない)-> フォルダのパスか None。
    video: 書き出した切り抜き(clips)があればそれのあるフォルダ。無ければ <書き出し先>/<題名>/ を書き出しと同じ規則(ytt.names.find_folder)で引く
    (持ち主 videoId の印のあるフォルダだけ)。out_dir = 書き出し先(None = スタジオの設定 = ytt.datadir.studio_out_dir)。
    file: 動画のあるフォルダ"""
    kind = media.get("kind") if isinstance(media, dict) else None
    if kind == "file":
        path = media.get("path")
        d = _folder_of(path) if isinstance(path, str) and path else ""
        return d if d and os.path.isdir(d) else None
    if kind != "video" or not media.get("videoId"):
        return None
    for clip in media.get("clips") or ():
        if isinstance(clip, str) and os.path.isfile(clip):
            return _folder_of(clip)
    vid = str(media["videoId"])
    got = _names.find_folder(out_dir or _datadir.studio_out_dir(), media.get("title") or vid, vid, vid)
    return got[1] if got else None


def work_dir(media, out_dir=None):
    """<案件>/作業用(途中のファイル・鍵・結果の束の置き場)。案件が分からなければ None"""
    root = case_root(media, out_dir)
    return os.path.join(root, _schemas.WORK_DIR) if root else None


def runs_dir(media, out_dir=None):
    """<案件>/作業用/runs(② の結果の束)。案件が分からなければ None"""
    wd = work_dir(media, out_dir)
    return os.path.join(wd, RUNS_DIR) if wd else None


# ---------------------------------------------------------------- case.json(案件の身分証。RS7-2 B-1)
def _case_id(media, root):
    """案件の id = 安定した物。作業用/.studio-id(持ち主の印)があればそれ -> 配信なら videoId -> 動画ファイルならそのパス(正規化)の sha1 の先頭 16 桁に f- を付けた物"""
    owner = _names.read_owner(root)
    if owner:
        return owner[:64]
    if media.get("kind") == "video" and media.get("videoId"):
        return str(media["videoId"])[:64]
    key = _fsio.norm_path(str(media.get("path") or root))
    return "f-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def read_case(root):
    """<案件>/case.json を読む(読むだけ。④ manage もこれで読む)。無い・壊れている・形が違えば None"""
    d = _fsio.read_json_or(os.path.join(root, CASE_NAME), None, max_bytes=CASE_MAX, kind=dict) if root else None
    return d if d and d.get("schema") == CASE_SCHEMA and isinstance(d.get("id"), str) and d["id"] else None


def ensure_case(media, out_dir=None, channel="", root=None):
    """案件のフォルダに case.json(youtube-tools-case/v1)を**無いときだけ**原子的に作る。-> 中身(dict)か None(案件が分からない・書けない)。
    既にあれば読んで返すだけ(上書きしない)。あるのに壊れていれば作り直さずログだけ(人が直せるように残す)。何があっても上げない。
    形 {schema, id, media: {kind, videoId | path}, title, channel, createdAt(ミリ秒), madeBy}。id の決め方は _case_id"""
    try:
        root = root or case_root(media, out_dir)
        if not root:
            return None
        path = os.path.join(root, CASE_NAME)
        if os.path.exists(path):
            got = read_case(root)
            if got is None:
                log.warning("case.json が読めません(上書きしません): %s", path)
            return got
        if media.get("kind") == "video":
            m = {"kind": "video", "videoId": str(media.get("videoId") or "")}
            title = media.get("title") or m["videoId"]
        else:
            m = {"kind": "file", "path": str(media.get("path") or "")}
            title = os.path.splitext(os.path.basename(m["path"]))[0]
        doc = {"schema": CASE_SCHEMA, "id": _case_id(media, root), "media": m, "title": str(title or "")[:120],
               "channel": str(channel or "")[:100], "createdAt": int(time.time() * 1000),
               "madeBy": {"name": "flow", "version": _version.VERSION}}
        _fsio.write_json(path, doc)
        return doc
    except Exception as e:
        log.warning("case.json を作れませんでした: %s %s", e.__class__.__name__, str(e)[:150])
        return None


def _clip_paths(run, video=None):
    """この実行の切り抜き = スタジオの配信の書き出したマーク(マークを選んだ実行ならそれだけ)+ パックの元の切り抜き。同じ物は 1 つ"""
    marks = video.get("marks") if isinstance(video, dict) else None
    out = [m["path"] for m in marks if isinstance(m, dict) and m.get("status") == "exported" and isinstance(m.get("path"), str) and m["path"]
           and (not run.marks or m.get("id") in run.marks)] if isinstance(marks, list) else []
    out += [v["path"] for v in run.pack_marks.values() if isinstance(v, dict) and isinstance(v.get("path"), str) and v["path"]]
    return list(dict.fromkeys(os.path.normpath(p) for p in out))


def media_of(run, docs=(), video=None):
    """実行 → 案件を引く手がかり(media)。docs = 文書の一覧(文書単位の実行の元の動画を引く)・video = スタジオの配信 1 本(書き出した切り抜き)。
    分からなければ None"""
    if run.source_path:
        return {"kind": "file", "path": run.source_path}
    if run.doc_id:
        d = next((x for x in docs or () if isinstance(x, dict) and x.get("id") == run.doc_id), None)
        src = d.get("sourcePath") if d else None
        return {"kind": "file", "path": src} if isinstance(src, str) and src else None
    if run.video_id:
        return {"kind": "video", "videoId": run.video_id, "title": run.title, "clips": _clip_paths(run, video)}
    return None


# ---------------------------------------------------------------- 結果の束
def _existing(path):
    return path if path and os.path.isfile(path) else None


def _doc_key(tid, stage):
    """文書の鍵のパス(あれば)。文書の置き場所が決まっていない(workdata.TX_DIR が None)・id が変なら None"""
    try:
        return _existing(_keys.doc_key_path(tid, stage))
    except (TypeError, ValueError):
        return None


def _doc_path(tid):
    return _existing(os.path.join(_workdata.TX_DIR, tid + ".json")) if _workdata.TX_DIR and _schemas.TID_RE.match(str(tid or "")) else None


def outputs(run, video=None):
    """段ごとの成果物のパスと鍵のパス(鍵は今あるものだけ。無ければ None)"""
    clips = _clip_paths(run, video) if run.video_id else []
    tids = list(dict.fromkeys(list(run.docs) + list(run.new_docs)))
    out = {"export": [{"path": p, "key": _existing(_keys.media_key_path(p, "export"))} for p in clips],
           "transcribe": [{"doc": t, "path": _doc_path(t), "key": _doc_key(t, "transcribe"), "post": _doc_key(t, "post")} for t in tids],
           "pack": [{"path": p, "key": _existing(_keys.pack_key_path(p)), "clip": (run.pack_marks.get(p) or {}).get("path") or None}
                    for p in run.all_packs()]}
    if any(s["key"] == "diarize" for s in run.steps):
        out["diarize"] = [{"doc": t, "key": _doc_key(t, "diar")} for t in dict.fromkeys(run.new_docs)]
    return out


def _outcome(run, exc):
    """終わり方 -> (状態, 理由)。done・cancelled(人が止めた)・stopped(入口の終了で止まった = 次の起動で続く)・error"""
    if exc is None:
        return ("cancelled" if run.cancel else "done"), ""
    from . import run as _run   # run が placement を読むので、呼ぶときに読む(循環させない)
    if isinstance(exc, _run.Cancelled):
        return ("cancelled" if run.cancel else "stopped"), ""
    if isinstance(exc, _run.StepError):
        return "error", str(exc)[:500]
    return "error", "想定外の失敗(%s)" % exc.__class__.__name__   # 原文は入口のログへ(autorun。ここには型だけ)


def result(run, exc=None, video=None, at=None):
    """結果の束(runlog.RESULT_SCHEMA)。exc = 実行を止めた例外(None = 最後まで進んだ)"""
    state, why = _outcome(run, exc)
    pub = run.public()
    open_state = {"error": "error", "stopped": "wait"}.get(state, "skip")   # 途中だった段の行き先(autorun._loop と同じ。続く実行は待ちに)
    steps = [dict({"key": s["key"], "state": open_state if s["state"] == "run" else s["state"], "detail": s["detail"]},
                  **{k: s[k] for k in STEP_TIMES if k in s}) for s in run.steps]   # 段の時刻(ミリ秒。あれば。RS7-1 S3)
    failures = [{"step": s["key"], "state": s["state"], "detail": s["detail"]} for s in run.steps if s["state"] in ("error", "warn")]
    failures += [{"step": s["key"], "state": state, "detail": why or run.error} for s in run.steps if s["state"] == "run" and state in ("error", "stopped")]
    if state == "error" and not any(s["state"] == "run" for s in run.steps):
        failures.append({"step": None, "state": "error", "detail": why or run.error})
    env = run.envelope() if callable(getattr(run, "envelope", None)) else None   # 封筒(RS7-1 S3。足すだけ)
    return {"schema": _runlog.RESULT_SCHEMA, "id": run.id, "input": {k: pub.get(k) for k in INPUT_KEYS}, "envelope": env,
            "spec": run.spec, "state": state, "message": run.message, "error": why or run.error, "nothing": run.nothing,
            "steps": steps, "outputs": outputs(run, video), "packs": run.all_packs(), "failures": failures,
            "notes": list(getattr(run, "notes", None) or []),   # 受付で束を組んだときに直した所の知らせ(RS7-1 S4。以前の画面だけの値 packNotes)
            "created": pub["created"], "at": int((time.time() if at is None else at) * 1000),
            "madeBy": {"name": "flow", "version": _version.VERSION}}


def _context(run, runner):
    """終わったときの手がかり(文書の一覧・スタジオの配信)を Runner の hook から。読めなければ空(束は書けるだけ書く)"""
    docs, video = (), None
    if runner is None:
        return docs, video
    try:
        if run.doc_id and not run.source_path:
            docs = runner._docs()   # Runner の hook(入口は txindex・素の Runner は道具の一覧)
        if run.video_id:
            video = runner._studio_video(run.video_id)   # Runner の hook(入口はスタジオの data.json・素の Runner は {})
    except Exception as e:   # 手がかりが読めなくても束は書く(実行の結果は変えない)
        log.warning("結果の束の手がかりを読めませんでした: %s", e.__class__.__name__)
    return docs, video


def write_result(run, exc=None, runner=None, out_dir=None):
    """② の 1 回の実行が終わったところ(flow/run.run の最後)で呼ぶ: <案件>/作業用/runs/<実行id>.json を原子的に書き、パスを run.result_path に置く
    (入口の記録の 1 行の resultPath = 索引)。-> 書いたパスか None(案件が分からない・まだ無い・書けない)。何があっても上げない(実行は失敗にしない)。
    out_dir = 書き出し先(None = スタジオの設定。入口の Runner の root・env で読む)"""
    try:
        docs, video = _context(run, runner)
        if out_dir is None and run.video_id:
            out_dir = _datadir.studio_out_dir(getattr(runner, "root", None), getattr(runner, "env", None))   # root は入口の AutoRunner だけが持つ
        d = runs_dir(media_of(run, docs, video), out_dir)
        if not d:
            log.info("結果の束を置く案件が分かりません(実行 %s)", run.id)
            return None
        media = media_of(run, docs, video)
        ensure_case(media, out_dir, getattr(run, "streamer", "") or "", root=os.path.dirname(os.path.dirname(d)))   # 実行のたびに案件ができる(無いときだけ)
        path = os.path.join(d, run.id + ".json")
        _fsio.write_json(path, result(run, exc, video))
        run.result_path = path
        return path
    except Exception as e:   # 束が書けなくても実行は止めない(flow/run.run の finally から呼ばれる = 上げると元の例外を隠す)
        log.warning("結果の束を書けませんでした(実行 %s): %s %s", getattr(run, "id", "?"), e.__class__.__name__, str(e)[:150])
        return None


# ---------------------------------------------------------------- .flow.lock(1 つの作業データに ② は 1 つ)
class LockBusy(Exception):
    """ほかの ② が同じ作業データで動いている。info = その印 {pid, port, at}"""

    def __init__(self, info):
        self.info = dict(info or {})
        super().__init__("ほかの管理の処理(pid %s・ポート %s)が同じ作業データで動いています" % (self.info.get("pid"), self.info.get("port") or "なし"))


def lock_path(data_root=None):
    """.flow.lock の場所 = 作業データの根(data_root。None = ytt.datadir.data_root。inplace(テスト)なら .runtime = 環境変数 YTT_RUNTIME_DIR か src/.runtime)"""
    root = data_root or _datadir.data_root() or _runtime.runtime_dir(_layout.tool_dir("app"))
    return os.path.join(root, LOCK_NAME)


def _read_lock(path):
    try:
        obj = _fsio.read_json_file(path, LOCK_MAX)
    except (OSError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _alive(info):
    """印の持ち主の ② が動いているか(pid が動いている。ポートを書いた印は、そのポートが開いていることも見る)"""
    if not info or not _procs.pid_alive(info.get("pid")):
        return False
    port = info.get("port")
    return port is None or _runtime.port_open(port)


def lock_info(data_root=None):
    """動いている ② の印 {pid, port, at} か None(無い・壊れている・持ち主が動いていない = 取り残しは無いのと同じ)"""
    info = _read_lock(lock_path(data_root))
    return {k: info.get(k) for k in ("pid", "port", "at")} if _alive(info) else None


def acquire(port=None, data_root=None):
    """印を取る。-> 持っている印(release に渡す)。ほかの ② が動いていれば LockBusy。取り残し(持ち主が動いていない・壊れている)は消して取り直す。
    port = この ② の HTTP のポート(CLI など無ければ None)"""
    if port is not None and not _runtime.valid_port(port):
        raise ValueError("ポートが正しくありません: %r" % (port,))
    path = lock_path(data_root)
    info = {"pid": os.getpid(), "port": port, "at": int(time.time() * 1000), "token": secrets.token_hex(8)}
    data = json.dumps(info).encode("utf-8")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for _ in range(3):
        if _fsio.create_new(path, data):   # 無いときだけ作る(ほかの ② と同時でも 1 つだけが取れる)
            return {"path": path, "token": info["token"]}
        old = _read_lock(path)
        if _alive(old):
            raise LockBusy(old)
        log.info("取り残された %s を消します(pid %s)", LOCK_NAME, (old or {}).get("pid"))
        _fsio.unlink_quiet(path)
    raise LockBusy(_read_lock(path) or {})


def release(handle):
    """acquire で取った印を返す(自分の印のときだけ消す = ほかの ② が取り直した物は残す)。None・返し済みは何もしない。-> 消したか"""
    if not isinstance(handle, dict) or not handle.get("path"):
        return False
    info = _read_lock(handle["path"])
    if not info or info.get("token") != handle.get("token"):
        return False
    _fsio.unlink_quiet(handle["path"])
    return True
