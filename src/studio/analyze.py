"""解析(自動切り抜き ac/serve.py 由来。書き出し・手動の○×は持たない)。

音声(音量・高音域)・チャットのリプレイ・動画コメント欄のタイムスタンプから「盛り上がっている部分」を見つけ、区間の候補にする。
解析ジョブは辞書: state / phase / progress / error / cancel / proc / proc2 / chat / result。batch.py がこれを1本ずつ回す。
  new_job(spec) → run_analyze(job) → job["result"] = {source, candidates, series, signals, counts, warnings, spec}
"""
import glob
import gzip
import json
import math
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import common
from common import ApiError, Cancelled, atomic_write, find_tool, get_api_key, num, redact, run_capture, tail_reason, fmt_ms
from ytt_core import excite, fsio as _fsio  # noqa: E402  盛り上がりの式(線 D の L1 で src/ytt_core/excite.py に移した。配信中の検出と同じ式)
from ytt_core.excite import (CAP, SENS, LAG_MAX, LAG_MIN_CORR, LAG_MIN_CONTRAST, smooth, median, local_baseline, robust_scale, audio_score, chat_z, shift_chat,  # noqa: E402,F401
                             chat_score, estimate_lag, head_ramp, comment_score, pick_clips, snap_quiet, downsample)   # 同じ名前で再公開(batch・テスト・e2e が analyze.X で呼ぶ)

API_BASE = common.YT_API_BASE
CHAT_CACHE_KEEP = 30
# チャットのキャッシュの合計の上限(2026-09-30。件数だけでは、実機で 30 件・2.0GB になっていた)。既定 1GB。環境変数 STUDIO_CHAT_CACHE_MB(MB)で変えられる
CHAT_CACHE_MAX_BYTES = 1024 ** 3
MAX_FEEDBACK_BYTES = 32 * 1024 * 1024   # 1行 500〜800 バイトなので約5万件。超えたら feedback.jsonl.old の末尾へ移す(消さない)
MAX_DURATION = 12 * 3600
AUDIO_DL_IDLE = 600      # 音声のダウンロードで、この秒数まったく出力がなければ中止
AUDIO_LEVEL_IDLE = 900   # 音量の解析(ffmpeg)で同様
MAX_CHAT_BYTES = 400 * 1024 * 1024
HEAD_SEC_DEFAULT = 180   # 冒頭の減点をかける秒数(0で無効)
STREAM_TYPES = ("auto", "ゲーム", "雑談", "歌枠", "その他")
# 配信タイプ別の重みの倍率(試験的・初期値は仮。archive のデータがたまったら見直す)。設定「配信タイプ別の重み」をオンにしたときだけ使う
TYPE_PRESETS = {"歌枠": {"wAudio": 0.6}, "雑談": {"wAudio": 0.8, "wChat": 1.1}, "ゲーム": {}, "その他": {}}
ARCHIVE_KEEP = 2000
META_TTL = 24 * 3600     # 動画の付加情報の再取得までの秒数(再解析のたびに取り直さない)
META_KEEP = 300
META_TIMEOUT = 90
FB_SETTING_KEYS = ("sensitivity", "length", "preRatio", "lag", "lagAuto", "headSec", "typePreset", "wAudio", "wChat", "wComments")
SPEC_KEYS = ("count", "length", "sensitivity", "preRatio", "lag", "lagAuto", "headSec", "typePreset", "wAudio", "wChat", "wComments")   # 結果・archive に残す設定


def work_dir():
    return common.p("work")


def chat_cache_dir():
    return common.p("cache", "chat")


def sig_cache_dir():
    return common.p("cache", "signals")   # 音量の解析結果(動画IDごと)。感度・長さ・重みを変えた再解析で使い回す


def feedback_path():
    return common.p("feedback.jsonl")


# ---------- 入力の検査 ----------
LIVE_NO_ANALYZE = "ライブの録画は解析できません(配信が終わってから、アーカイブのURLを入れてください)"


def validate_live(o):
    """POST /api/videos/open {kind:"live", recorder, recording, url, title} → store.ensure に渡す source 辞書(id = 録画の id)。不正は ApiError。"""
    lv = common.check_live(o)
    return {"kind": "live", "videoId": lv["recording"], "name": lv["recording"], "live": lv}


def validate_source(item):
    """キューに入れる1件({kind:"youtube", url|videoId} / {kind:"file", path}) → source 辞書。不正は ApiError。"""
    if not isinstance(item, dict):
        raise ApiError("bad_source", "入力が正しくありません", 400)
    if item.get("kind") == "file":
        p = common.check_media_path(item.get("path"))
        return {"kind": "file", "path": p, "name": os.path.basename(p), "videoId": common.file_video_id(p)}
    if item.get("kind") == "live" or common.LIVE_ID_RE.match(str(item.get("videoId") or item.get("id") or "")):
        raise ApiError("bad_source", LIVE_NO_ANALYZE, 400)   # ライブの録画は、YouTube としても file としても解析へ進めない(yt-dlp を呼ばない)
    vid = common.parse_video_id(item.get("url") or item.get("videoId"))
    if not vid:
        raise ApiError("bad_source", "YouTube の動画URLではありません(watch?v=… / youtu.be/… / live/…)", 400)
    return {"kind": "youtube", "videoId": vid, "name": vid}


def validate_settings(req):
    """解析の設定(範囲外は丸める)。autoExport は廃止。maxHeight(画質の上限)も 0.24.0 で廃止(解析は音声しか取らず読んでいなかった。保存してある値は読み捨てる)。"""
    req = req if isinstance(req, dict) else {}
    sens = req.get("sensitivity") if req.get("sensitivity") in ("high", "normal", "low") else "normal"
    return {"useAudio": req.get("useAudio") is not False, "useChat": req.get("useChat") is not False,
            "useComments": req.get("useComments") is not False,
            "count": int(num(req.get("count"), 1, 30, 8)), "length": num(req.get("length"), 10, 120, 45), "preRatio": num(req.get("preRatio"), 0.3, 0.9, excite.PRE_RATIO_DEFAULT),
            "lag": num(req.get("lag"), 0, 30, 8), "lagAuto": req.get("lagAuto") is not False, "headSec": num(req.get("headSec"), 0, 600, HEAD_SEC_DEFAULT), "typePreset": req.get("typePreset") is True,
            "typeOverride": req.get("typeOverride") if req.get("typeOverride") in STREAM_TYPES else "auto", "chatTimeout": int(num(req.get("chatTimeout"), 1, 120, 20)), "noCache": req.get("noCache") is True, "sensitivity": sens,
            "wAudio": num(req.get("wAudio"), 0, 3, 1.0), "wChat": num(req.get("wChat"), 0, 3, 1.0), "wComments": num(req.get("wComments"), 0, 3, 0.7)}


def make_spec(src, settings):
    """ファイル入力では、チャット・コメントは使えない。"""
    spec = dict(settings)
    spec["source"] = src
    if src["kind"] != "youtube":
        spec["useChat"] = spec["useComments"] = False
    return spec


# ---------- ジョブ ----------
def new_job(spec):
    return {"id": uuid.uuid4().hex[:10], "kind": "analyze", "state": "running", "phase": "開始", "progress": 0.0, "error": "", "spec": spec, "result": None,
            "cancel": False, "proc": None, "proc2": None, "proc3": None, "chat": None, "meta": None}


def chat_public(c):
    if not c:
        return None
    return {"state": c["state"], "elapsed": int((c["t1"] or time.time()) - c["t0"]), "bytes": c["bytes"]}


def cancel_job(job):
    job["cancel"] = True
    for k in ("proc", "proc2", "proc3"):
        common.terminate(job.get(k))


def skip_chat(job):
    """チャット待ちだけ打ち切る(音声などの解析は続ける)。"""
    c = job.get("chat")
    if c and c["state"] == "running":
        c["skip"] = True
        common.terminate(job.get("proc2"))
        return True
    return False


# ---------- 判定の記録(feedback.jsonl) ----------
_fb_lock = threading.Lock()


def _feedback_row(video, mark, verdict, event):
    """feedback.jsonl の1行の共通部分(区間・点数・解析の信号と設定・配信の種類)。
    自動マークは、最初の自動区間(auto0)と手で直した量(dStart / dEnd)も残す。
    再解析で手動マークに変わったもの(auto0 が auto0Orig に移っている)も同じ値で残す(reanalyzed: true)。"""
    an = video.get("analysis") or {}
    sp = an.get("spec") or {}
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "videoId": video.get("id", ""), "kind": video.get("kind"), "start": mark.get("start"), "end": mark.get("end"),
           "peak": mark.get("peak"), "score": mark.get("score"), "parts": mark.get("parts") or {}, "verdict": verdict, "signals": an.get("signals") or {},
           "settings": {k: sp[k] for k in FB_SETTING_KEYS if k in sp}, "source": "review", "src": mark.get("src", "auto"), "event": event,
           "duration": video.get("duration"), "type": an.get("type"), "markId": mark.get("id")}
    if mark.get("adoptedBy"):   # 機械が採用にしたマーク(まとめて実行・依頼)。書き出しの行が人の「よかった」に混ざらないように(Q2)
        row["adoptedBy"] = mark["adoptedBy"]
    a0 = mark.get("auto0")
    if not a0 and mark.get("auto0Orig"):
        a0 = mark["auto0Orig"]
        row["reanalyzed"] = True
    if isinstance(a0, (list, tuple)) and len(a0) == 2:
        row["auto0"] = a0
        try:
            row["dStart"], row["dEnd"] = round(float(mark["start"]) - float(a0[0]), 1), round(float(mark["end"]) - float(a0[1]), 1)
        except (KeyError, TypeError, ValueError):
            pass
    return row


def _feedback_write(row):
    if row.get("kind") == "live":
        # ライブの録画(線 D の P3)は解析していない(自動マークが無い): 手で付けたマークが「自動の見逃し」(manual_add)や
        # 手動の「よかった」として盛り上がりの学習・集計(dev/eval_marks.py など)に混ざって数字を変えないように、記録しない
        return False
    path = feedback_path()
    with _fb_lock:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if os.path.exists(path) and os.path.getsize(path) > MAX_FEEDBACK_BYTES:
                _move_feedback_to_old(path)
            _append_line(path, json.dumps(row, ensure_ascii=False) + "\n")
        except OSError as e:
            common.log_failure("feedback.jsonl への記録", e)
            return False
    return True


def feedback_for_mark(video, mark, verdict, event=""):
    """確認画面での結果(採用・不採用・削除・書き出し)を feedback.jsonl に1行で残す。パスは含めない。
    video: store の動画(id, kind, analysis を使う)、mark: そのマーク。event: adopt / reject / delete / export。
    手動マーク(src=manual)の採用・書き出しも「よかった」として残す。"""
    if verdict not in ("good", "bad"):
        return False
    return _feedback_write(_feedback_row(video, mark, verdict, event))


# 人の最終の操作の記録(Q2。機械の最初の結果と並べて残すため)。verdict は good / bad 以外の値にする(good・bad だけ数える読み手に混ざらない):
#   manual_add    "miss"     手で足したマーク = 自動の見逃し(nearAuto = その時いちばん近かった自動マーク)
#   manual_remove "unmiss"   手で足した候補のマークを手で消した(足したのは間違いだったかもしれない)
#   unadopt       "retract"  採用(書き出し済みを含む)を候補に戻した(prevStatus)
#   delete_judged "retract"  採用・不採用・書き出し済みのマークを削除した(prevStatus)
FB_EXTRA_EVENTS = {"manual_add": "miss", "manual_remove": "unmiss", "unadopt": "retract", "delete_judged": "retract"}


def nearest_auto(marks, start, end, skip_id=None):
    """区間 (start, end) にいちばん近い自動マーク(src=auto)を探す。近さは区間どうしの隙間(重なっていれば 0 秒)。
    -> {"autoCount": 自動マークの数, "nearAuto": None か {"score", "distance", "start", "end", "status"}}"""
    best, n = None, 0
    for m in marks:
        if m.get("src") != "auto" or m.get("id") == skip_id:
            continue
        try:
            ms, me = float(m["start"]), float(m["end"])
        except (KeyError, TypeError, ValueError):
            continue
        n += 1
        gap = max(0.0, ms - float(end), float(start) - me)
        key = (gap, -(m.get("score") or 0))
        if best is None or key < best[0]:
            best = (key, m)
    near = None
    if best:
        m = best[1]
        near = {"score": m.get("score"), "distance": round(best[0][0], 1), "start": m.get("start"), "end": m.get("end"), "status": m.get("status", "")}
    return {"autoCount": n, "nearAuto": near}


def feedback_event(video, mark, event, extra=None):
    """FB_EXTRA_EVENTS の行(手で足した・手で消した・採用の取り消し・判定済みの削除)を feedback.jsonl に1行で残す。extra の項目は行に足す。"""
    verdict = FB_EXTRA_EVENTS.get(event)
    if not verdict:
        return False
    row = _feedback_row(video, mark, verdict, event)
    if extra:
        row.update(extra)
    return _feedback_write(row)


def _append_line(path, line):
    """1行追記する。前回の行が書きかけ(電源断など)で改行が無ければ、先に改行を足して次の行と繋がらないようにする。"""
    with open(path, "a+b") as f:
        f.seek(0, os.SEEK_END)
        if f.tell() > 0:
            f.seek(-1, os.SEEK_END)
            if f.read(1) != b"\n":
                f.write(b"\n")
        f.write(line.encode("utf-8"))


def _move_feedback_to_old(path):
    """大きくなった feedback.jsonl を feedback.jsonl.old の末尾へ移して空にする。
    以前は .old を上書きしていたため、2回目の切り替えで古い記録が消えていた(精度の見直しに使う大事なデータなので消さない)。"""
    old = path + ".old"
    with open(path, "rb") as src, open(old, "ab") as dst:
        if dst.tell() > 0:
            with open(old, "rb") as chk:
                chk.seek(-1, os.SEEK_END)
                if chk.read(1) != b"\n":
                    dst.write(b"\n")
        shutil.copyfileobj(src, dst)
        dst.flush()
        try:
            os.fsync(dst.fileno())
        except OSError:
            pass
    with open(path, "wb"):
        pass   # 移し終えてから空にする(途中で止まっても記録は消えない。重複は ts で見分けられる)


# ---------- 素材の取得(YouTube) ----------
def download_audio(job, vid, wdir):
    if common.fake():
        return common.fake_media()
    yt = find_tool("yt-dlp")
    if not yt:
        raise ApiError("no_ytdlp", "yt-dlp が見つかりません(README の準備手順を確認してください)")
    cmd = [yt, "--no-playlist", "--no-warnings", "--newline", "--ffmpeg-location", find_tool("ffmpeg") or "", "-f", "ba/b", "-o", common.ytdlp_out(wdir, "audio.%(ext)s"),
           "--", common.watch_url(vid)]

    def on(line):
        m = re.search(r"\[download\]\s+([\d.]+)%", line)
        if m:
            job["progress"] = 0.02 + 0.10 * float(m.group(1)) / 100
    rc, err = run_capture(job, cmd, on, idle_timeout=AUDIO_DL_IDLE, what="音声の取得")
    files = [f for f in glob.glob(glob.escape(os.path.join(wdir, "audio")) + ".*") if not f.endswith((".part", ".ytdl", ".temp"))]
    if rc != 0 or not files:
        raise ApiError("download", "音声を取得できませんでした: " + (tail_reason(err) or "不明なエラー"), 502)
    return files[0]


def chat_cache_path(vid):
    return os.path.join(chat_cache_dir(), vid + ".live_chat.json")


def _usable_chat(path):
    """取得済みのチャット(空でなく、大きすぎない)があるか"""
    return os.path.isfile(path) and 0 < os.path.getsize(path) <= MAX_CHAT_BYTES


def prune_cache(d, pattern, keep=CHAT_CACHE_KEEP):
    try:
        fs = sorted((os.path.getmtime(p), p) for p in glob.glob(os.path.join(glob.escape(d), pattern)))
        for _, p in fs[:-keep]:
            os.remove(p)
    except OSError:
        pass


def chat_cache_limit():
    """チャットのキャッシュの合計の上限(バイト)。環境変数 STUDIO_CHAT_CACHE_MB(1 以上の整数)があればそれ。"""
    try:
        mb = int(str(os.environ.get("STUDIO_CHAT_CACHE_MB") or "0").strip())
    except ValueError:
        mb = 0
    return mb * 1024 * 1024 if mb > 0 else CHAT_CACHE_MAX_BYTES


# 解析が使っているチャットのキャッシュ(動画ID → 数)。キャッシュを消すときはこれと先読み中(PREFETCH)の動画のものを飛ばす。
# 消す処理(prune_chat_cache)と使い始め(use_chat_cache)は同じロックを取る(「使っていないと確かめた直後に使い始めた」を消さない)
_chat_use_lock = threading.Lock()
_chat_in_use = {}


def use_chat_cache(vid, delta):
    """解析がその動画のチャットのキャッシュを使い始める(+1)・使い終える(-1)。"""
    with _chat_use_lock:
        n = _chat_in_use.get(vid, 0) + delta
        if n > 0:
            _chat_in_use[vid] = n
        else:
            _chat_in_use.pop(vid, None)


def prune_chat_cache(limit=None, keep=CHAT_CACHE_KEEP):
    """件数(keep)と合計の大きさ(limit。既定は chat_cache_limit())の両方に収まるまで、最後に使った時刻が古いものから消す。
    解析・先読みが使っている動画のものと、いちばん新しいもの(今入れたもの)は消さない。途中で止まった写し(*.tmp)も消す。消したバイト数を返す"""
    limit = chat_cache_limit() if limit is None else limit
    d = chat_cache_dir()
    freed = 0
    with _chat_use_lock:
        with _pf_lock:
            busy = set(_chat_in_use) | set(PREFETCH)
        files, tmps = [], []
        total, count = 0, 0   # 合計と件数は、使っている最中で飛ばしたものも含めて数える(消せないものの分も上限に入る)
        for p in glob.glob(os.path.join(glob.escape(d), "*.live_chat.json*")):   # フォルダは 1 回だけ読む
            name = os.path.basename(p)
            vid = name.split(".live_chat.json", 1)[0]
            try:
                st = os.stat(p)
            except OSError:
                continue
            if name.endswith(".live_chat.json"):
                total += st.st_size
                count += 1
                if vid not in busy:
                    files.append((st.st_mtime, st.st_size, p))
            elif name.endswith(".live_chat.json.tmp") and vid not in busy:
                tmps.append((st.st_size, p))
        for size, p in tmps:
            try:
                os.remove(p)
                freed += size
            except OSError:
                pass
        files.sort()
        newest = files[-1][2] if files else None
        for _mtime, size, p in files:
            if count <= keep and total <= limit:
                break
            if p == newest:
                break   # いちばん新しいものは残す(今入れたもの。1つで上限を超えていても)
            try:
                os.remove(p)
            except OSError:   # Windows で読み込み中などは消せない → 次の機会に
                continue
            total -= size
            count -= 1
            freed += size
    return freed


def sig_path(vid):
    return os.path.join(sig_cache_dir(), vid + ".json")


def load_sig(vid):
    """保存済みの音量の解析結果(長さ・全帯域・高音域)。無い・壊れている・形が違うなら None。"""
    d = _fsio.read_json_or(sig_path(vid), {}, kind=dict)
    try:
        full, band, dur = d.get("full"), d.get("band"), d.get("dur")
        if d.get("v") != 1 or not isinstance(full, list) or not isinstance(band, list) or not isinstance(dur, (int, float)):
            return None
        if not (20 <= dur <= MAX_DURATION) or len(full) < 20 or len(band) < 20 or abs(len(full) - dur) > 5 or abs(len(band) - dur) > 5:
            return None
        if not all(isinstance(x, (int, float)) and -100 <= x <= 20 for x in full[:: max(1, len(full) // 500)] + band[:: max(1, len(band) // 500)]):
            return None
        os.utime(sig_path(vid), None)
        return {"dur": float(dur), "full": [float(x) for x in full], "band": [float(x) for x in band]}
    except (OSError, ValueError, TypeError):
        return None


def save_sig(vid, dur, full, band):
    try:
        data = {"v": 1, "dur": round(dur, 2), "full": [round(x, 1) for x in full], "band": [round(x, 1) for x in band]}
        atomic_write(sig_path(vid), json.dumps(data, separators=(",", ":")).encode("utf-8"))   # 一時ファイル名を固定しない・Windows のロックは再試行
        prune_cache(sig_cache_dir(), "*.json")
    except OSError:
        pass


def download_chat(job, vid, wdir, timeout):
    """チャットのリプレイ(live_chat)。取れなければ (None, 理由)。
    完走したものは cache/chat/<動画ID> に残す(途中で打ち切ったものは残さない)。"""
    c = job["chat"]
    if common.fake():
        p = os.environ.get("STUDIO_FAKE_CHAT", "")
        delay = float(os.environ.get("STUDIO_FAKE_CHAT_DELAY", "0") or 0)
        t0 = time.time()
        while time.time() - t0 < delay:
            if job["cancel"]:
                raise Cancelled()
            if c["skip"]:
                return None, "チャットは待たずに進めました"
            time.sleep(0.05)
        return (p, "") if os.path.isfile(p) else (None, "疑似モード: チャットなし")
    cp = chat_cache_path(vid)
    if _usable_chat(cp):
        c["cached"] = True
        c["prefetched"] = vid in _pf_done
        _pf_done.discard(vid)
        os.utime(cp, None)
        return cp, ""
    if not job.get("prefetch"):
        with _pf_lock:
            pf = PREFETCH.get(vid)
        if pf:   # 先読みが同じ動画を取得中なら、もう1つ起動せず、その完了を待つ
            while not pf["done"].wait(0.5):
                if job["cancel"] or c["skip"]:
                    cancel_prefetch(vid)
                    if job["cancel"]:
                        raise Cancelled()
                    return None, "チャットは待たずに進めました"
                c["bytes"] = pf["job"]["chat"]["bytes"] if pf["job"].get("chat") else c["bytes"]
            if _usable_chat(cp):
                c["cached"] = c["prefetched"] = True
                return cp, ""
            return None, pf["why"] or "チャットのリプレイを取得できませんでした"
    yt = find_tool("yt-dlp")
    if not yt:
        return None, "yt-dlp が見つからないため、チャットは使えません"
    cmd = [yt, "--no-playlist", "--no-warnings", "--newline", "--skip-download", "--write-subs", "--sub-langs", "live_chat", "-o", common.ytdlp_out(wdir, "chat.%(ext)s"), "--", common.watch_url(vid)]
    stop = threading.Event()

    def watch():   # 出力ファイルの大きさを見せる(yt-dlp は進捗を出さないため、動いている目安になる)
        while not stop.wait(2):
            try:
                c["bytes"] = sum(os.path.getsize(f) for f in glob.glob(glob.escape(os.path.join(wdir, "chat")) + "*"))
            except OSError:
                pass
    threading.Thread(target=watch, daemon=True).start()
    t0 = time.time()
    try:
        rc, err = run_capture(job, cmd, None, timeout=timeout, slot="proc2")
    finally:
        stop.set()
    if c["skip"]:
        return None, "チャットは待たずに進めました"
    if timeout and time.time() - t0 >= timeout:
        return None, "チャットの取得が %d 分を超えたため、チャットは使っていません(設定で待ち時間を延ばせます)" % (timeout // 60)
    files = [f for f in glob.glob(glob.escape(os.path.join(wdir, "chat")) + "*.live_chat.json")]
    if not files:
        return None, "チャットのリプレイを取得できませんでした(チャットが無効・削除されている、または取得に失敗)" + ((": " + tail_reason(err)) if rc != 0 and tail_reason(err) else "")
    if os.path.getsize(files[0]) > MAX_CHAT_BYTES:
        return None, "チャットのファイルが大きすぎます"
    if rc == 0:
        try:
            os.makedirs(chat_cache_dir(), exist_ok=True)
            tmp = cp + ".tmp"
            shutil.copyfile(files[0], tmp)
            common.replace_file(tmp, cp)
            prune_chat_cache()
        except OSError:
            pass
    return files[0], ""


# ---------- チャットの先読み ----------
# チャットの取得は yt-dlp が順番に取るため速くできない。代わりに、バッチの「次の配信」のチャットを、今の配信の解析と並行して取っておく
# (取れたものは cache/chat に入り、その配信の番が来たときは待たずに使える)。同時に取るのは先読み1本まで(YouTube への負荷を増やしすぎない)。
PREFETCH_MAX = 1
_pf_lock = threading.Lock()
_pf_done = set()   # 先読みで取得できた動画ID(画面の文言用)
PREFETCH = {}   # 動画ID -> {"job", "done": Event, "why", "path"}


def prefetch_chat(vid, timeout, on_done=None):
    """"started" / "full"(先読みの枠がいっぱい)/ "skip"(すでに取得済み・取得中、または使えない)。"""
    if common.fake() or not isinstance(vid, str) or not common.VID_RE.match(vid):   # ASCII の 11 文字だけ(以前は全角の英字なども通っていた)
        return "skip"
    with _pf_lock:
        if vid in PREFETCH:
            return "skip"
        if len(PREFETCH) >= PREFETCH_MAX:
            return "full"
        if _usable_chat(chat_cache_path(vid)):
            return "skip"
        if not find_tool("yt-dlp"):
            return "skip"
        pjob = {"cancel": False, "proc": None, "proc2": None, "prefetch": True,
                "chat": {"state": "running", "t0": time.time(), "t1": None, "bytes": 0, "skip": False, "cached": False}}
        pf = {"job": pjob, "done": threading.Event(), "why": "", "path": None}
        PREFETCH[vid] = pf

    def work():
        wdir = os.path.join(work_dir(), "pf_" + vid)
        try:
            os.makedirs(wdir, exist_ok=True)
            pf["path"], pf["why"] = download_chat(pjob, vid, wdir, timeout)
            if pf["path"] and os.path.isfile(chat_cache_path(vid)):
                _pf_done.add(vid)
        except Cancelled:
            pf["why"] = "中止"
        except Exception as e:
            pf["why"] = "チャットの先読みで予期しないエラー: " + redact(str(e))[:160]
        finally:
            shutil.rmtree(wdir, ignore_errors=True)
            with _pf_lock:
                PREFETCH.pop(vid, None)
            pf["done"].set()
            if on_done:
                try:
                    on_done()
                except Exception:
                    pass
    threading.Thread(target=work, daemon=True, name="chat-prefetch").start()
    return "started"


def cancel_prefetch(vid, kill=True):
    with _pf_lock:
        pf = PREFETCH.get(vid)
    if pf:
        pf["job"]["cancel"] = True
        if kill:
            for k in ("proc", "proc2"):
                common.terminate(pf["job"].get(k))


def cancel_all_prefetch():
    """終了の流れ用: 先読みをすべて中止する(止める依頼だけ。子プロセスは common.stop_children がまとめて止める)。中止した数"""
    with _pf_lock:
        vids = list(PREFETCH)
    for vid in vids:
        cancel_prefetch(vid, kill=False)
    return len(vids)


def start_chat(job, vid, wdir, timeout):
    """チャット取得を別スレッドで始める(音声のダウンロード・解析と並行して進める)。"""
    c = {"state": "running", "t0": time.time(), "t1": None, "bytes": 0, "skip": False, "cached": False, "path": None, "why": "", "err": None}
    job["chat"] = c

    def work():
        try:
            c["path"], c["why"] = download_chat(job, vid, wdir, timeout)
        except Cancelled:
            c["why"] = "中止"
        except Exception as e:   # 想定外でも本体の解析は続ける
            c["why"] = "チャットの取得で予期しないエラー: " + redact(str(e))[:160]
        finally:
            c["t1"] = time.time()
            c["state"] = "cached" if c["cached"] and c["path"] else ("done" if c["path"] else "failed")
    th = threading.Thread(target=work, daemon=True)
    c["thread"] = th
    th.start()


TS_RE = re.compile(r"(?<![\d:])(?:(\d{1,2}):)?([0-5]?\d):([0-5]\d)(?![\d:])")


def fetch_comments(vid, dur, texts=None):
    """動画コメント欄から [(秒, いいね数)]。APIキーが無い・失敗のときは (None, 理由)。"""
    if common.fake():
        p = os.environ.get("STUDIO_FAKE_COMMENTS", "")
        if not os.path.isfile(p):
            return None, "疑似モード: コメントなし"
        with open(p, encoding="utf-8") as f:
            threads = json.load(f)
        return stamps_from(threads, dur, texts), ""
    key = get_api_key()[0]
    if not key:
        return None, "APIキーが未設定のため、コメント欄は使っていません(任意)"
    items, token = [], None
    for _ in range(5):
        params = {"part": "snippet", "videoId": vid, "maxResults": 100, "order": "relevance", "textFormat": "plainText", "key": key}
        if token:
            params["pageToken"] = token
        try:
            with urllib.request.urlopen(urllib.request.Request(API_BASE + "commentThreads?" + urllib.parse.urlencode(params), headers={"Accept": "application/json"}), timeout=20) as r:
                d = json.load(r)
        except urllib.error.HTTPError as e:
            try:
                reason = (json.loads(e.read().decode("utf-8", "replace")).get("error", {}).get("errors") or [{}])[0].get("reason", "")
            except ValueError:
                reason = ""
            if reason == "commentsDisabled":
                return None, "この動画はコメントが無効です"
            return None, "コメント欄を取得できませんでした(%s / HTTP %d)" % (reason or "エラー", e.code)
        except (urllib.error.URLError, TimeoutError, OSError):
            return None, "コメント欄を取得できませんでした(接続エラー)"
        for it in d.get("items", []):
            sn = it.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
            items.append({"text": sn.get("textOriginal") or sn.get("textDisplay") or "", "likes": int(sn.get("likeCount") or 0)})
        token = d.get("nextPageToken")
        if not token:
            break
    return stamps_from(items, dur, texts), ""


LIST_MIN = 3   # 1つのコメントに時刻がこの数以上あれば「チャプター一覧」とみなす


def stamps_from(items, dur, texts=None):
    """[(秒, いいね数, 重み)]。チャプター一覧のコメント(時刻が LIST_MIN 個以上)は、1つあたりの重みを 1/個数 に下げる
    (「ここが見どころ」という個別の指定ではなく、一覧に載っているだけなので)。"""
    out = []
    for it in items:
        ts = []
        for m in TS_RE.finditer(str(it.get("text", ""))):
            t = int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            if 0 < t < dur:
                ts.append(t)
        w = 1.0 if len(ts) < LIST_MIN else 1.0 / len(ts)
        likes = int(it.get("likes", 0))
        out.extend((t, likes, w) for t in ts)
        if texts is not None:   # 記録用: 時刻ごとに、そのコメントの先頭60文字
            texts.extend(str(it.get("text", "")).replace("\n", " ")[:60] for _ in ts)
    return out


# ---------- 動画の付加情報(みんなが繰り返し見た場面・チャプター・カテゴリなど。記録用) ----------
def meta_dir():
    return common.p("cache", "meta")


def slim_meta(d):
    """yt-dlp の動画情報(-J)から、記録に使う項目だけを小さく取り出す。形が違えば None。"""
    if not isinstance(d, dict):
        return None

    def s_(k, n=200):
        v = d.get(k)
        return str(v)[:n] if isinstance(v, (str, int, float)) and not isinstance(v, bool) else ""

    def i_(k):
        v = d.get(k)
        return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    def lst(k, n, m):
        v = d.get(k)
        return [str(x)[:n] for x in v[:m]] if isinstance(v, list) else []
    hm, ch = [], []
    for h in d.get("heatmap") or []:   # 「最も再生された場面」: 区間ごとの相対値 0〜1(粗い。再生数が少ない動画・配信直後は無い)
        try:
            hm.append([round(float(h["start_time"]), 1), round(float(h["end_time"]), 1), round(float(h["value"]), 3)])
        except (KeyError, TypeError, ValueError):
            continue
    for c in d.get("chapters") or []:
        try:
            ch.append([round(float(c["start_time"]), 1), round(float(c["end_time"]), 1), str(c.get("title") or "")[:60]])
        except (KeyError, TypeError, ValueError):
            continue
    return {"title": s_("title", 120), "channel": s_("channel", 100) or s_("uploader", 100), "categories": lst("categories", 30, 5), "tags": lst("tags", 30, 30),
            "views": i_("view_count"), "likes": i_("like_count"), "commentCount": i_("comment_count"), "followers": i_("channel_follower_count"),
            "uploadDate": s_("upload_date", 8), "duration": i_("duration"), "liveStatus": s_("live_status", 20),
            "heatmap": hm[:300], "chapters": ch[:100], "fetchedAt": int(time.time())}


def _meta_ok(d):
    """キャッシュの形の確認(classify_stream などが型の違いで落ちて、記録用の情報のせいで解析全体が失敗するのを防ぐ)。"""
    return (isinstance(d, dict) and isinstance(d.get("title", ""), str)
            and all(isinstance(d.get(k) or [], list) and all(isinstance(x, str) for x in (d.get(k) or [])) for k in ("tags", "categories"))
            and all(isinstance(d.get(k) or [], list) for k in ("heatmap", "chapters")))


def load_meta(vid):
    d = _fsio.read_json_or(os.path.join(meta_dir(), vid + ".json"))
    try:
        if _meta_ok(d) and time.time() - float(d.get("fetchedAt") or 0) < META_TTL:
            return d
    except (OSError, ValueError, TypeError):
        pass
    return None


def fetch_meta(job, vid):
    """(付加情報 or None, 理由)。失敗しても解析には影響しない。24時間以内に取得済みならそれを使う。"""
    if common.fake():
        p = os.environ.get("STUDIO_FAKE_META", "")
        if not os.path.isfile(p):
            return None, "疑似モード: 付加情報なし"
        with open(p, encoding="utf-8") as f:
            return slim_meta(json.load(f)), ""
    cached = load_meta(vid)
    if cached:
        return cached, ""
    yt = find_tool("yt-dlp")
    if not yt:
        return None, "yt-dlp が見つかりません"
    buf = []
    try:
        rc, err = run_capture(job, [yt, "--no-playlist", "--no-warnings", "--skip-download", "-J", "--", common.watch_url(vid)],
                              lambda l: buf.append(l) if len(buf) < 20000 else None, timeout=META_TIMEOUT, slot="proc3", what="動画情報の取得")
    except ApiError as e:
        return None, e.message
    if rc != 0:
        return None, tail_reason(err) or "取得できませんでした"
    try:
        m = slim_meta(json.loads("".join(buf)))
    except ValueError:
        return None, "動画情報を読み取れませんでした"
    if m:
        try:
            atomic_write(os.path.join(meta_dir(), vid + ".json"), json.dumps(m, ensure_ascii=False).encode("utf-8"))
            prune_cache(meta_dir(), "*.json", META_KEEP)
        except OSError:
            pass
    return m, ""


def start_meta(job, vid):
    """付加情報の取得を別スレッドで始める(音声などの解析と並行)。結果は job["meta"] = {"data", "why", "thread"}。"""
    r = {"data": None, "why": "", "thread": None}
    job["meta"] = r

    def work():
        try:
            r["data"], r["why"] = fetch_meta(job, vid)
        except Cancelled:
            r["why"] = "中止"
        except Exception as e:   # 記録用なので、何があっても本体の解析は続ける
            r["why"] = "予期しないエラー: " + redact(str(e))[:120]
    th = threading.Thread(target=work, daemon=True)
    r["thread"] = th
    th.start()


TYPE_WORDS = (("歌枠", re.compile(r"歌枠|カラオケ|karaoke|singing|歌ってみ|弾き語り|歌配信|歌謡", re.I)),
              ("雑談", re.compile(r"雑談|朝活|凸待ち|マシュマロ|お便り|フリートーク|お絵描き|作業|告知|報告|ASMR|free ?talk", re.I)))


def classify_stream(meta):
    """配信のタイプの推定(タイトル・タグ・カテゴリから)。歌枠 > 雑談 > ゲーム(カテゴリ Gaming)> その他。付加情報が無ければ None。"""
    if not meta:
        return None
    text = " ".join([meta.get("title", "")] + list(meta.get("tags") or []))
    for name, rx in TYPE_WORDS:
        if rx.search(text):
            return name
    return "ゲーム" if "Gaming" in (meta.get("categories") or []) else "その他"


def apply_type_preset(wts, stream_type):
    """配信タイプ別の倍率を重みにかける(試験的)。(新しい重み, 適用した倍率の辞書)。"""
    mult = TYPE_PRESETS.get(stream_type) or {}
    key = {"audio": "wAudio", "chat": "wChat", "comments": "wComments"}
    return {k: v * mult.get(key[k], 1.0) for k, v in wts.items()}, {k: x for k, x in mult.items() if x != 1.0}


# ---------- 解析データの保存(archive: 後から重みや判定ロジックを実データで見直すための記録) ----------
ARCHIVE_ID_RE = re.compile(r"^[\w-]{1,40}\Z", re.ASCII)


def archive_path(vid):
    return common.p("archive", vid + ".json.gz") if isinstance(vid, str) and ARCHIVE_ID_RE.match(vid) else None


def load_archive(vid):
    p = archive_path(vid)
    try:
        with gzip.open(p, "rt", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and d.get("v") == 1 else None
    except (OSError, ValueError, TypeError, EOFError):
        return None


def save_archive(vid, payload, run, keep=ARCHIVE_KEEP):
    """1秒ごとの材料(音量・チャット・コメントの時刻と文面)と、解析ごとの設定・候補(直近5回分)を cache とは別に残す。壊れたら次の解析で作り直す。"""
    p = archive_path(vid)
    if not p:
        return False
    old = load_archive(vid)
    runs = (old or {}).get("runs")
    runs = [r for r in runs if isinstance(r, dict)] if isinstance(runs, list) else []   # 壊れた履歴で保存が毎回失敗し続けないように
    payload = dict(payload, v=1, videoId=vid, runs=runs[-4:] + [run])
    try:
        atomic_write(p, gzip.compress(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 6))
        fs = sorted((os.path.getmtime(q), q) for q in glob.glob(os.path.join(glob.escape(os.path.dirname(p)), "*.json.gz")))
        for _, q in fs[:-keep]:
            os.remove(q)
        return True
    except OSError:
        return False


# ---------- 解析 ----------
def audio_levels(job, path, dur, hp=None, p0=0.12, p1=0.42):
    """1秒ごとの音量(RMS, dB)を ffmpeg で求める。hp を指定すると、その周波数より上だけを測る。"""
    ff = find_tool("ffmpeg")
    if not ff:
        raise ApiError("no_ffmpeg", "ffmpeg が見つかりません(README の準備手順を確認してください)")
    filt = "aresample=16000," + ("highpass=f=%d," % hp if hp else "") + "asetnsamples=n=16000:p=0,astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-"
    vals = []

    def on(line):
        if line.startswith("lavfi.astats.Overall.RMS_level="):
            v = line.split("=", 1)[1]
            try:
                x = float(v)
            except ValueError:
                x = -90.0
            vals.append(-90.0 if x != x or x < -90 else x)
            if len(vals) % 60 == 0 and dur:
                job["progress"] = p0 + (p1 - p0) * min(1.0, len(vals) / dur)
    rc, err = run_capture(job, [ff, "-hide_banner", "-nostdin", "-protocol_whitelist", "file,pipe", "-i", path, "-vn", "-af", filt, "-f", "null", "-"], on, idle_timeout=AUDIO_LEVEL_IDLE, what="音量の解析")
    if rc != 0 or not vals:
        raise ApiError("audio", "音声を解析できませんでした: " + (tail_reason(err) or "音声トラックがない可能性があります"), 400)
    return vals


def parse_chat(path, n, extra=None):
    """live_chat.json → (1秒ごとの活気, 件数, 「草」などの件数)。extra に辞書を渡すと、1秒ごとの warm(「草」等の件数)/ uniq(発言した人数)/ paid(スパチャ件数)を入れる(記録用)。"""
    act = [0.0] * n
    total = warm_total = 0
    warm_s, paid_s, uniq_s = [0] * n, [0] * n, {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            ra = d.get("replayChatItemAction")
            if not isinstance(ra, dict):
                continue
            try:
                t = int(ra.get("videoOffsetTimeMsec")) / 1000.0
            except (TypeError, ValueError):
                continue
            if t < 0 or t >= n:
                continue
            for a in ra.get("actions") or []:
                item = ((a.get("addChatItemAction") or {}).get("item")) or {}
                kind, r = next(iter(item.items()), (None, None)) if item else (None, None)
                if not isinstance(r, dict):
                    continue
                w, warm, paid = excite.message_weight(kind, excite.message_text(r))   # 重み(「草」+1.5・スパチャ +4)は配信中の検出と同じ 1 か所
                if w is None:
                    continue
                if warm:
                    warm_total += 1
                    warm_s[int(t)] += 1
                if paid:
                    paid_s[int(t)] += 1
                act[int(t)] += w
                total += 1
                au = r.get("authorExternalChannelId")
                if au:
                    uniq_s.setdefault(int(t), set()).add(au)
    if extra is not None:
        extra["warm"], extra["paid"] = warm_s, paid_s
        extra["uniq"] = [len(uniq_s.get(i, ())) for i in range(n)]
    return act, total, warm_total


def _levels(job, spec, src, wdir, warnings):
    """音量(全体・高音域)を 1 秒ごとに。YouTube は前回の結果があれば再利用する。-> (dur, n, full, band)。full・band は長さ n にそろえる"""
    sig = load_sig(src["videoId"]) if src["kind"] == "youtube" and not spec["noCache"] else None
    if sig:   # 前回の音量の解析結果を再利用(ダウンロードも ffmpeg も不要)
        dur, full, band = sig["dur"], sig["full"], sig["band"]
        n = int(math.ceil(dur))
        warnings.append("音量の解析は前回の結果を再利用しました(最初からやり直すには、詳しい設定の「キャッシュを使わない」をオン)")
    else:
        media = src["path"] if src["kind"] == "file" else download_audio(job, src["videoId"], wdir)
        dur, _v, has_audio, _l = common.media_info(media)   # 長さと音声の有無を1回で(ffmpeg が無ければ dur が None になり、下で止まる)
        if not dur or dur < 20:
            raise ApiError("bad_media", "動画の長さを読み取れません(または短すぎます)")
        if dur > MAX_DURATION:
            raise ApiError("too_long", "長すぎます(この動画は %s。解析できるのは %d 時間まで)" % (common.fmt_ts(dur)[:8], MAX_DURATION // 3600))
        if not has_audio:
            raise ApiError("no_audio", "このファイルには音声トラックがありません(音声・チャット・コメントのどれも使えないため、解析できません)")
        n = int(math.ceil(dur))
        job["phase"] = "音量を解析中"
        full = audio_levels(job, media, dur, None, 0.12, 0.30)
        job["phase"] = "高音域(笑い声・叫び)を解析中"
        band = audio_levels(job, media, dur, 2000, 0.30, 0.48)
        full, band = [round(x, 1) for x in full], [round(x, 1) for x in band]   # 保存するのと同じ精度にそろえる(キャッシュの有無で結果が変わらないように)
        dur = round(dur, 2)
        if src["kind"] == "youtube":
            save_sig(src["videoId"], dur, full, band)
    full = (full + [full[-1]] * n)[:n]
    band = (band + [band[-1]] * n)[:n]
    return dur, n, full, band


def _chat_signal(job, spec, n, comps, info, warnings):
    """チャットの取得(start_chat で始めたもの)を待って解析し、30 件以上なら comps["chat"] に入れる。
    -> {"act", "count", "warm", "extra"}(archive に残す材料。取れなければ act は None)"""
    out = {"act": None, "count": 0, "warm": 0, "extra": None}
    c = job["chat"]
    while c["state"] == "running":
        if job["cancel"]:
            raise Cancelled()
        job["phase"], job["progress"] = "チャットのリプレイを取得中(音声の解析は完了、経過 %s)" % fmt_ms(time.time() - c["t0"]), 0.5
        c["thread"].join(0.3)
    path, why = c["path"], c["why"]
    if c["cached"] and path:
        warnings.append("チャットは先読みで取得済みでした" if c.get("prefetched") else "チャットは前回の取得分を再利用しました")
    if not path:
        warnings.append(why)
        return out
    job["phase"] = "チャットを解析中"
    out["extra"] = {}
    out["act"], out["count"], out["warm"] = parse_chat(path, n, out["extra"])
    if out["count"] < 30:
        warnings.append("チャットの件数が少ない(%d件)ため、チャットは使っていません" % out["count"])
        return out
    cz = chat_z(out["act"])
    used_lag = spec["lag"]
    if spec["lagAuto"] and "audio" in comps:
        est, r = estimate_lag(comps["audio"], cz)
        if est is not None:
            used_lag = est
            warnings.append("チャットの遅れを自動推定しました: %d秒(音量との一致度 %.2f。設定の値は使っていません)" % (est, r))
        else:
            warnings.append("チャットの遅れは自動推定できなかったため、設定の%d秒を使いました" % round(used_lag))
    spec["lagUsed"] = used_lag
    comps["chat"] = shift_chat(cz, used_lag)
    info["chat"] = True
    return out


def _comment_signal(job, src, dur, n, comps, info, warnings, ctexts):
    """コメント欄の時刻の書き込み → comps["comments"]。-> 書き込みの一覧(無ければ None)。ctexts に本文が並ぶ(archive 用)"""
    job["phase"], job["progress"] = "コメント欄のタイムスタンプを取得中", 0.56
    st, why = fetch_comments(src["videoId"], dur, ctexts)
    if st is None:
        warnings.append(why)
        return None
    if not st:
        warnings.append("コメント欄に、時刻の書き込みが見つかりませんでした")
        return None
    comps["comments"] = comment_score(st, n)
    info["comments"] = True
    return st


def _weights(job, spec, warnings):
    """材料の重みと配信タイプ。付加情報(start_meta で始めたもの)を待ち、タイプの初期値を使う設定なら重みを掛ける。-> (wts, meta, stream_type)"""
    wts = {"audio": spec["wAudio"], "chat": spec["wChat"], "comments": spec["wComments"]}
    meta = None
    mj = job.get("meta")
    if mj:
        mj["thread"].join(META_TIMEOUT + 5)
        meta = mj["data"]
        if meta is None and mj["why"]:
            warnings.append("動画の付加情報(記録用)を取得できませんでした: %s(解析には影響しません)" % mj["why"])
    stream_type = spec["typeOverride"] if spec["typeOverride"] != "auto" else classify_stream(meta)
    if spec["typePreset"] and stream_type:
        wts, changed = apply_type_preset(wts, stream_type)
        if changed:
            warnings.append("配信タイプ「%s」の重みを使いました(%s。試験的な初期値)" % (stream_type, "・".join("%s×%s" % ({"wAudio": "音声", "wChat": "チャット", "wComments": "コメント"}[k], x) for k, x in changed.items())))
    return wts, meta, stream_type


def _save_record(src, spec, dur, n, levels, chat, stamps, ctexts, meta, stream_type, info, cands):
    """後から実データで見直すための記録(save_archive)。levels = (full, band)・chat = _chat_signal の結果(使わなかったときは None)。失敗しても解析は続ける"""
    try:
        full, band = levels
        payload = {"kind": src["kind"], "duration": round(dur, 1), "n": n, "at": int(time.time() * 1000), "type": stream_type, "meta": meta,
                   "full": [round(x, 1) for x in full], "band": [round(x, 1) for x in band],
                   "chat": ({"act": [round(x, 1) for x in chat["act"]], "count": chat["count"], "warmCount": chat["warm"], **(chat["extra"] or {})} if chat else None),
                   "stamps": ([[t, lk, round(w, 3), (ctexts[i] if i < len(ctexts) else "")] for i, (t, lk, w) in enumerate(stamps)] if stamps else None)}
        run = {"at": payload["at"], "spec": {k: spec[k] for k in SPEC_KEYS},
               "lagUsed": spec.get("lagUsed"), "signals": info, "type": stream_type,
               "candidates": [{"start": c["start"], "end": c["end"], "peak": c["peak"], "score": c["score"], "parts": c["parts"]} for c in cands]}
        save_archive(src["videoId"], payload, run)
    except Exception:
        pass


def _stop_helpers(job, wdir, chat_vid):
    """後始末: 途中で失敗・中止したときに付加情報・チャットの取得を残さない。作業フォルダを消し、チャットのキャッシュの使用中を外す"""
    mj = job.get("meta")
    if mj and mj["thread"].is_alive():
        common.terminate(job.get("proc3"))
        mj["thread"].join(5)
    c = job.get("chat")
    if c and c["state"] == "running":
        c["skip"] = True
        common.terminate(job.get("proc2"))
        c["thread"].join(10)
    shutil.rmtree(wdir, ignore_errors=True)
    if chat_vid:
        use_chat_cache(chat_vid, -1)


def run_analyze(job):
    """解析の 1 ジョブ(裏のスレッド): 素材の取得(音声・チャット・付加情報は同時に)→ 材料ごとの点数 → 重み付きの合計 → 山を区間に。
    結果は job["result"]、状態は job["state"]・job["phase"]・job["progress"]"""
    spec = job["spec"]
    src = spec["source"]
    wdir = os.path.join(work_dir(), job["id"])
    chat_vid = src["videoId"] if src["kind"] == "youtube" and spec["useChat"] else None
    if chat_vid:
        use_chat_cache(chat_vid, +1)   # 解析が終わるまで、この動画のチャットのキャッシュを消させない
    try:
        os.makedirs(wdir, exist_ok=True)
        if job["cancel"]:
            raise Cancelled()
        warnings = []
        job["state"], job["phase"] = "running", "素材を取得中"
        if spec["useChat"]:
            start_chat(job, src["videoId"], wdir, spec["chatTimeout"] * 60)   # 音声の取得・解析と同時に始める
        if src["kind"] == "youtube":
            start_meta(job, src["videoId"])   # 動画の付加情報(記録用)も同時に取得する
        dur, n, full, band = _levels(job, spec, src, wdir, warnings)
        comps, info = {}, {"audio": False, "chat": False, "comments": False}
        if spec["useAudio"]:
            comps["audio"] = audio_score(full, band)
            info["audio"] = True
        chat = _chat_signal(job, spec, n, comps, info, warnings) if spec["useChat"] else {"act": None, "count": 0, "warm": 0, "extra": None}
        ctexts = []
        stamps = _comment_signal(job, src, dur, n, comps, info, warnings, ctexts) if spec["useComments"] else None
        if not comps:
            raise ApiError("no_signal", "使える材料がありません(音声の解析をオンにするか、チャット・コメントが取れる動画を指定してください)")
        job["phase"], job["progress"] = "盛り上がりの区間を決定中", 0.6
        wts, meta, stream_type = _weights(job, spec, warnings)
        total = [sum(wts[k] * comps[k][i] for k in comps) for i in range(n)]
        total = head_ramp(total, spec["headSec"])   # 冒頭は誤検出が多いので、なだらかに減点
        # 材料が重なるほど合計が大きくなる(音声・チャット・コメントが同じ場面を指すと強い)
        cands = excite.candidates(pick_clips(total, full, spec, n), comps)   # 山の前後の材料ごとの点数(parts)と理由の文(配信中の候補と同じ式)
        _save_record(src, spec, dur, n, (full, band), chat if info["chat"] else None, stamps, ctexts, meta, stream_type, info, cands)
        series = {"n": n, "step": max(1.0, n / 600), "total": downsample(total), **{k: downsample(v) for k, v in comps.items()}}
        if job["cancel"]:
            raise Cancelled()
        job["result"] = {"source": {**src, "duration": round(dur, 1)}, "candidates": cands, "series": series, "signals": info,
                         "counts": {"chat": chat["count"], "chatWarm": chat["warm"], "commentStamps": len(stamps) if stamps else 0, "meta": bool(meta), "heatmap": len((meta or {}).get("heatmap") or [])},
                         "type": stream_type, "warnings": warnings, "spec": dict({k: spec[k] for k in SPEC_KEYS}, lag=spec.get("lagUsed", spec["lag"]))}
        job["state"], job["phase"], job["progress"] = "done", "解析が完了しました", 1.0
    except Cancelled:
        job["state"], job["phase"] = "cancelled", "中止しました"
    except ApiError as e:
        job["state"], job["error"], job["phase"] = "error", e.message, "失敗"
    except PermissionError as e:
        common.log_failure("動画解析", e)
        job["state"], job["error"], job["phase"] = "error", common.permission_message(e), "失敗"
    except Exception as e:
        common.log_failure("動画解析", e)
        job["state"], job["error"], job["phase"] = "error", "内部エラー: %s %s" % (e.__class__.__name__, str(e)[:200]), "失敗"
    finally:
        _stop_helpers(job, wdir, chat_vid)
