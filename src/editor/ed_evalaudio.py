# -*- coding: utf-8 -*-
"""「編集」のサーバーの部品: 評価用の音声(16kHz・モノラルの flac)を作業データに作る(マスタープラン Q0。plan/line-bc-master-plan.md)。

評価用のフォルダ(設定 evalDirs。動画は E:\\ などにしか無い)の中の動画から、文字起こしの精度を測るための音声だけを `eval-audio/` に写す。
動画が無くなっても(外付けのドライブを外した・消した)精度の測定ができるようにするため、作業データの中(= バックアップに入る)に置く。
  - eval-audio/index.json … 元のパス・大きさ・更新時刻・flac の名前・長さ(元が消えたものは gone の印。flac は消さない)
  - eval-audio/<元のパスの sha1 の先頭 12 文字>_<元の名前>.flac
元が変わっていなければ作り直さない。重い処理(ffmpeg)は1本ごとに SLOTS を通し、文字起こしなどのジョブが動いている・待っている間は始めない。
起動の 5 分後と、その後 6 時間ごとに、裏のスレッドで1回まわる(serve.py の prepare が `start_background`)。
単独でも動かせる: リポジトリ直下から `py -3.10 src/editor/ed_evalaudio.py`(作業データの場所は入口と同じ決め方)。

名前は serve.py からも見える(serve.py が受け付けて、この部品へ転送する)。ほかの部品は `ed_xxx.名前` で呼ぶたびに読む。
"""
import os
import sys

if __name__ == "__main__":   # 単独実行: serve.py を読み込み(ytt_core の探し方・作業データの決め方が同じ)、そちらの部品を動かす
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import serve as _serve
    raise SystemExit(_serve.ed_evalaudio.main(sys.argv[1:]))

import contextlib
import hashlib
import json
import re
import subprocess
import threading
import time

from ytt import fsio as _fsio, jobs as _heavy, tools as _tools  # noqa: E402,F401
import ed_relink  # noqa: E402,F401
import ed_state  # noqa: E402,F401

SCHEMA = "ytt-eval-audio/v1"
DIR_NAME = "eval-audio"
INDEX_NAME = "index.json"
FIRST_DELAY_SEC = 5 * 60         # 起動してから最初にまわるまで(起動直後は文字起こしの準備・整理が重なるので待つ)
INTERVAL_SEC = 6 * 3600          # その後のまわる間隔
RETRY_SEC = 10 * 60              # ジョブが動いていて途中でやめたとき、もう一度試すまで
MAKE_TIMEOUT_SEC = 3 * 3600      # 1本の ffmpeg の上限(6 時間の配信でも数分で終わる。止まったものを待ち続けない)
MAX_FAILS = 3                    # 同じ元(大きさ・更新時刻が同じ)で失敗したらあきらめる回数(元が変われば数え直す)
MTIME_TOL = 1.0                  # 同じパスの元が変わっていないとみなす更新時刻の差(秒)
ADOPT_MTIME_TOL = 2.1            # 名前が変わった元を同じ動画とみなす更新時刻の差(別のドライブへのコピーは 2 秒単位に丸まることがある)
INDEX_MAX_BYTES = 64 * 1024 * 1024
_pass_lock = threading.Lock()
_stop = threading.Event()
_bg = []


# ---------------------------------------------------------------- 置き場所・索引

def audio_dir():
    """作業データの eval-audio/(テストは設定の置き場所の隣)"""
    return os.path.join(os.path.dirname(ed_state.SETTINGS), DIR_NAME)


def index_path():
    return os.path.join(audio_dir(), INDEX_NAME)


def path_key(path):
    """元のパスの正規化(大文字小文字・区切りをそろえる)の sha1 の先頭 12 文字"""
    return hashlib.sha1(ed_state.norm_path(path).encode("utf-8", "surrogatepass")).hexdigest()[:12]


def safe_stem(name):
    s = re.sub(r'[\x00-\x1f<>:"/\\|?*]', "_", os.path.splitext(os.path.basename(name))[0]).strip(" .")
    return s[:60] or "audio"


def flac_name(path):
    return "%s_%s.flac" % (path_key(path), safe_stem(path))


def _empty_index():
    return {"schema": SCHEMA, "updatedAt": 0, "scan": None, "lastRun": None, "lastError": None, "items": {}}


def read_index():
    d = _fsio.read_json_or(index_path(), None, INDEX_MAX_BYTES, kind=dict)
    if d is None or not isinstance(d.get("items"), dict):
        return _empty_index()
    return dict(_empty_index(), **{k: d[k] for k in ("scan", "lastRun", "lastError", "items") if k in d})


def _write_index(idx):
    idx["schema"] = SCHEMA
    idx["updatedAt"] = ed_state.now_ms()
    ed_state.atomic_write(index_path(), json.dumps(idx, ensure_ascii=False, indent=1).encode("utf-8"))


# ---------------------------------------------------------------- 状態(GET /api/eval-audio)

def status():
    """-> {enabled, running, total(最後に調べた評価用の動画の本数), made(flac のある本数), remaining(これから作る本数), gone, failed,
    bytes(flac の合計の大きさ), seconds(音声の合計の長さ), lastRun, lastError}。ファイルは探さない(索引を読むだけ)"""
    idx = read_index()
    items = [i for i in idx["items"].values() if isinstance(i, dict)]
    made = [i for i in items if i.get("flac")]
    scan = idx.get("scan") if isinstance(idx.get("scan"), dict) else {}
    return {"enabled": bool(ed_relink.eval_dirs()), "running": _pass_lock.locked(),
            "total": scan.get("found"), "made": len(made), "remaining": scan.get("pending"),
            "gone": sum(1 for i in items if i.get("gone")), "failed": sum(1 for i in items if i.get("error") and not i.get("flac")),
            "bytes": sum(int(i.get("flacSize") or 0) for i in made), "seconds": round(sum(float(i.get("durationSec") or 0) for i in made), 1),
            "lastRun": idx.get("lastRun"), "lastError": idx.get("lastError")}


# ---------------------------------------------------------------- 1回まわる

def _busy_reason():
    """いま始めてはいけない理由(無ければ None)。ジョブが動いている・待っている間と、評価用のフォルダの整理(動画の名前を変える)の間。
    SLOTS の中から呼ばれるので、ジョブの表のロックは取らない(コピーを読むだけ)"""
    try:
        jobs = list(_heavy._jobs.values())
    except RuntimeError:
        jobs = []
    if any(j.get("state") in _heavy.ACTIVE_STATES for j in jobs):
        return "文字起こしなどのジョブが動いています"
    if ed_relink._evalorg_lock.locked():
        return "評価用のフォルダを整理中です"
    return None


def _make(ff, src, dst):
    """src の音声を 16kHz・モノラルの flac にして dst へ(一時名に書いてから改名)。-> None(成功)| エラーの文。
    Windows では黒い画面を出さず「通常より下」の優先度(画面・文字起こしより先に CPU を取らない)"""
    part = dst + ".part"
    cmd = [ff, "-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-i", src, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "flac", "-f", "flac", part]
    try:
        p = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=MAKE_TIMEOUT_SEC,
                           creationflags=_tools.no_window_flags(priority="low"))
    except subprocess.TimeoutExpired:
        err = "ffmpeg が %d 分たっても終わりませんでした" % (MAKE_TIMEOUT_SEC // 60)
    except (OSError, subprocess.SubprocessError) as e:
        err = "ffmpeg を動かせませんでした: %s" % e
    else:
        err = None
        if p.returncode != 0 or not os.path.isfile(part) or os.path.getsize(part) == 0:
            lines = [l for l in (p.stderr or b"").decode("utf-8", "replace").strip().splitlines() if l.strip()]
            err = (lines[-1] if lines else "ffmpeg が失敗しました(終了コード %s)" % p.returncode)[:300]
    if err is None:
        try:
            ed_state.replace_retry(part, dst)
        except OSError as e:
            err = "flac の名前を付けられませんでした: %s" % e
    if err is not None:
        _fsio.unlink_quiet(part)
    return err


def scan_sources():
    """評価用のフォルダの下の動画 [(パス, 大きさ, 更新時刻)](仮置きも含む。作業用/ と _edit の動画は除く)"""
    out, seen = [], set()
    for root in ed_relink.eval_dirs():
        for folder, names in ed_relink._eval_videos(root, skip_staging=False).items():
            for n in names:
                p = os.path.join(folder, n)
                k = ed_state.norm_path(p)
                if k in seen:
                    continue
                seen.add(k)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                out.append((p, st.st_size, st.st_mtime))
    out.sort(key=lambda x: os.path.normcase(x[0]))
    return out


def _same(item, size, mtime):
    return item.get("size") == size and abs(float(item.get("mtime") or 0) - mtime) < MTIME_TOL


def _reconcile(idx, found):
    """見つけた動画と索引を突き合わせる。-> (これから作る [(パス, 大きさ, 更新時刻)], 名前が変わった元を引き継いだ数)。
    元が見つからないものは gone の印(flac は消さない)。評価用の整理で名前を変えた動画は、大きさと更新時刻が同じなら flac を引き継ぐ"""
    items = idx["items"]
    keys = {path_key(p) for p, _s, _m in found}
    todo, adopted = [], 0
    for p, size, mtime in found:
        k = path_key(p)
        it = items.get(k)
        if it is None:
            for ok, old in list(items.items()):   # 名前が変わっただけの動画(元のパスにはもう無い)
                if (ok not in keys and old.get("flac") and old.get("size") == size and abs(float(old.get("mtime") or 0) - mtime) < ADOPT_MTIME_TOL
                        and os.path.isfile(os.path.join(audio_dir(), old["flac"])) and not os.path.exists(str(old.get("src") or ""))):
                    it = items[k] = dict(items.pop(ok), src=p, size=size, mtime=mtime)
                    it.pop("gone", None)
                    adopted += 1
                    break
        if it is not None:
            it.pop("gone", None)
            it.pop("goneAt", None)
            if it.get("flac") and _same(it, size, mtime) and os.path.isfile(os.path.join(audio_dir(), it["flac"])):
                it["src"] = p
                continue
            if it.get("error") and not it.get("flac") and _same(it, size, mtime) and int(it.get("fails") or 0) >= MAX_FAILS:
                continue   # 同じ元で何度も失敗している(元が変わるまで試さない)
        todo.append((p, size, mtime))
    if ed_relink.eval_dirs():   # 評価用のフォルダが見えているときだけ(ドライブを外していると全部消えたことになってしまう)
        now = ed_state.now_ms()
        for k, it in items.items():
            if k not in keys and isinstance(it, dict) and not it.get("gone") and not os.path.exists(str(it.get("src") or "")):
                it["gone"] = True
                it["goneAt"] = now
    return todo, adopted


def run_pass(why="manual", log=None):
    """1回まわる。-> {made, failed, adopted, found, pending, deferred(途中でやめた理由)} か {skipped: 理由}。
    評価用のフォルダが無い・ffmpeg が無い・別の処理が動いているときは何もしない(評価用のフォルダが空なら eval-audio/ も作らない)"""
    log = log or (lambda m: ed_state.log.info("評価用の音声: %s", m))
    if not ed_relink.eval_dirs():
        return {"skipped": "no_eval_dirs"}
    ff = ed_state.find_ffmpeg()
    if not ff:
        return {"skipped": "no_ffmpeg"}
    if not _pass_lock.acquire(blocking=False):
        return {"skipped": "running"}
    try:
        with _file_lock(os.path.join(audio_dir(), ".lock")) as got:
            if not got:
                return {"skipped": "running"}
            return _run_locked(ff, why, log)
    finally:
        _pass_lock.release()


def _run_locked(ff, why, log):
    t0 = time.time()
    folder = audio_dir()
    for n in os.listdir(folder):   # 前回の書きかけ(この関数は _file_lock の中なので、ほかに作っている人はいない)
        if n.endswith(".part"):
            _fsio.unlink_quiet(os.path.join(folder, n))
    idx = read_index()
    found = scan_sources()
    todo, adopted = _reconcile(idx, found)
    idx["scan"] = {"at": ed_state.now_ms(), "found": len(found), "pending": len(todo)}
    _write_index(idx)
    res = {"made": 0, "failed": 0, "adopted": adopted, "found": len(found), "pending": len(todo), "deferred": None}
    err = None
    for p, size, mtime in todo:
        why_not = _busy_reason()
        if why_not:
            res["deferred"] = why_not
            break
        key = path_key(p)
        old = idx["items"].get(key) or {}
        name = old.get("flac") or flac_name(p)
        with _heavy.SLOTS.slot(ed_state.TOOL_ID, "評価用の音声", cancelled=lambda: _busy_reason() is not None or _stop.is_set()) as ok:
            if not ok:
                res["deferred"] = _busy_reason() or "止めました"
                break
            e = _make(ff, p, os.path.join(folder, name))
        if e is None:
            dst = os.path.join(folder, name)
            idx["items"][key] = {"src": p, "size": size, "mtime": mtime, "flac": name, "flacSize": os.path.getsize(dst),
                                 "durationSec": round(ed_state.media_duration(dst) or 0.0, 3), "madeAt": ed_state.now_ms()}
            res["made"] += 1
            log("作りました %s" % os.path.basename(p))
        else:
            fails = int(old.get("fails") or 0) + 1 if _same(old, size, mtime) else 1
            idx["items"][key] = {"src": p, "size": size, "mtime": mtime, "flac": None, "error": e, "fails": fails, "failedAt": ed_state.now_ms()}
            if old.get("flac") and not _same(old, size, mtime):   # 元が変わったのに作り直せなかった: 古い flac は残す(精度の測定の記録として)
                idx["items"][key]["flac"] = old["flac"]
                idx["items"][key]["flacSize"] = old.get("flacSize")
                idx["items"][key]["durationSec"] = old.get("durationSec")
            res["failed"] += 1
            err = {"at": ed_state.now_ms(), "src": os.path.basename(p), "message": e}
            log("失敗 %s: %s" % (os.path.basename(p), e))
        idx["scan"]["pending"] = max(0, idx["scan"]["pending"] - 1)
        if err:
            idx["lastError"] = err
        _write_index(idx)
    if res["deferred"] is None and not any(isinstance(i, dict) and i.get("error") and not i.get("flac") for i in idx["items"].values()):
        idx["lastError"] = None   # 失敗している元が1つも残っていなければ消す(あきらめた元がある間は残す)
    idx["lastRun"] = {"at": ed_state.now_ms(), "why": why, "made": res["made"], "failed": res["failed"], "adopted": adopted,
                      "deferred": res["deferred"], "sec": round(time.time() - t0, 1)}
    _write_index(idx)
    return res


@contextlib.contextmanager
def _file_lock(path):
    """別のプロセス(単独実行と入口)が同時にまわらないための印。ファイルの先頭の 1 バイトを取る(プロセスが終われば自然に外れる)。
    -> 取れたら True、先に誰かが持っていれば False"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    f = open(path, "a+b")
    got = False
    try:
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            got = True
        except OSError:
            got = False
        yield got
    finally:
        if got:
            try:
                if os.name == "nt":
                    import msvcrt
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        f.close()


# ---------------------------------------------------------------- 裏のスレッド・単独実行

def start_background(first_delay=FIRST_DELAY_SEC, interval=INTERVAL_SEC):
    """起動の first_delay 秒後と、その後 interval 秒ごとに1回まわる裏のスレッド(serve.py の prepare から1回だけ)。
    環境変数 TRANSCRIBE_EVAL_AUDIO=off で始めない。ジョブが動いていて途中でやめたときは RETRY_SEC 後にもう一度"""
    if ed_state.env_off("TRANSCRIBE_EVAL_AUDIO") or _bg:
        return None

    def loop():
        delay = first_delay
        while not _stop.wait(delay):
            try:
                r = run_pass("background")
                delay = RETRY_SEC if r.get("deferred") else interval
            except Exception:
                ed_state.log.exception("評価用の音声の作成に失敗")
                delay = interval

    t = threading.Thread(target=loop, daemon=True, name="eval-audio")
    _bg.append(t)
    t.start()
    return t


def main(argv=None):
    """単独実行(py -3.10 src/editor/ed_evalaudio.py)。作業データの場所は入口と同じ決め方。-> 終了コード"""
    import serve
    serve.choose_data_dir()
    r = run_pass("cli", log=lambda m: print(m, flush=True))
    print("評価用の音声:", json.dumps(r, ensure_ascii=False), flush=True)
    s = status()
    print("本数 %s・作った %d・残り %s・消えた元 %d・失敗 %d・合計 %.1f MB" % (s["total"], s["made"], s["remaining"], s["gone"], s["failed"], s["bytes"] / 1048576.0), flush=True)
    return 1 if r.get("failed") else 0
