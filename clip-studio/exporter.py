"""③ 書き出し(クリップマーカー cm/serve.py 由来): store の動画・マークから ffmpeg / yt-dlp でクリップを mp4 にする。

- file 動画は元ファイルを ffmpeg で切り出す。youtube 動画は yt-dlp(疑似モードでは STUDIO_FAKE_MEDIA を ffmpeg で切り出す)。
- 出力先は <出力先>/<動画名>/ (動画ごとのフォルダ)。1度に1ジョブ。
- 各 item が成功した時点で on_done(video_id, mark_id, "フォルダ/ファイル.mp4") を呼ぶ(store がマークを exported にする)。
"""
import glob
import math
import os
import re
import subprocess
import sys
import threading
import time
import uuid

import common
from common import ApiError, find_tool, redact, fmt_ts

MAX_EXPORT_CLIPS = 50
MAX_CLIP_SEC = 3600
EXPORT_IDLE = 600   # 書き出しのコマンドが、この秒数まったく出力しなければ中止
DEFAULT_EXPORT_VOLUME = 75   # 書き出しの音量(%)。元の音量(100)だと大きすぎるとのことで既定は下げ気味
MIN_EXPORT_VOLUME, MAX_EXPORT_VOLUME = 1, 200
_jobs = {}
_jobs_lock = threading.Lock()


class ExportError(Exception):
    pass


def is_busy():
    with _jobs_lock:
        return any(j["state"] == "running" for j in _jobs.values())


def is_busy_for(video_id):
    with _jobs_lock:
        return any(j["state"] == "running" and j.get("videoId") == video_id for j in _jobs.values())


def compact_ts(t):
    s = int(t)
    return "%02dh%02dm%02ds" % (s // 3600, s % 3600 // 60, s % 60)


def safe_name(s, n):
    # パス区切り・予約文字・制御文字と、yt-dlp の出力テンプレートで意味を持つ % を除く
    s = re.sub(r'[\\/:*?"<>|%\x00-\x1f]+', "_", str(s or "")).strip(" ._")
    return s[:n]


WIN_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {"COM%d" % i for i in range(1, 10)} | {"LPT%d" % i for i in range(1, 10)}


def log_export(note, cmd, tail):
    """失敗の切り分け用に、実行コマンドとツールの出力を <出力先>/export-log.txt に残す。"""
    try:
        d = common.get_out_dir()
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "export-log.txt")
        if os.path.exists(p) and os.path.getsize(p) > 200000:
            os.unlink(p)
        with open(p, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n  cmd: %s\n  out: %s\n\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), note, redact(" ".join(map(str, cmd))), " | ".join(redact(l) for l in tail[-12:])))
    except OSError:
        pass


_ERR_RE = re.compile(r"error|fail|forbidden|denied|invalid|not found|unable|HTTP|403|404|410|timed out|Unsupported|ERROR", re.I)


def reason(tail, n=3):
    """ツールの出力から、失敗の理由らしい行を選ぶ(なければ末尾)。"""
    lines = [redact(l)[:200] for l in (tail or [])]
    key = [l for l in lines if _ERR_RE.search(l) and "Stream #" not in l]
    return " / ".join((key or lines)[-n:])


def verify_output(path, expected, tail=None):
    """出力が空・壊れていないかを確認する。ffmpeg は開始位置が元動画の長さを超えても正常終了(空ファイル)するため必須。"""
    dur, has_v, _a, vline = common.media_info(path)
    log_export("出力の映像情報: " + os.path.basename(path), [], [vline])
    if not has_v or dur is None or dur < max(0.5, expected * 0.5):
        detail = (" 詳細: " + reason(tail, 2)[:300]) if tail else ""
        raise ExportError("書き出したファイルが空か短すぎます(長さ %s 秒 / 期待 %.0f 秒)。%s" % ("不明" if dur is None else "%.1f" % dur, expected, detail))


def pick_folder(spec):
    """動画ごとの保存先フォルダ(<出力先>/<動画名>/)を決める。
    フォルダ内の .studio-id に動画IDを記録し、同名の別動画とは混ざらないよう連番を付ける。"""
    root = common.get_out_dir()
    name = safe_name(spec["title"], 60) or spec["videoId"]
    if name.upper() in WIN_RESERVED:
        name = "_" + name
    for i in range(1, 100):
        cand = name if i == 1 else "%s_%d" % (name, i)
        path = os.path.join(root, cand)
        marker = os.path.join(path, ".studio-id")
        if not os.path.exists(path):
            os.makedirs(path)
            with open(marker, "w", encoding="utf-8") as f:
                f.write(spec["videoId"])
            return cand, path
        if os.path.isdir(path):
            try:
                with open(marker, encoding="utf-8") as f:
                    owner = f.read().strip()
            except OSError:
                owner = None
            if owner == spec["videoId"]:
                return cand, path
            if owner is None:  # 手で作られたフォルダは、その動画のものとして使う
                with open(marker, "w", encoding="utf-8") as f:
                    f.write(spec["videoId"])
                return cand, path
    raise ExportError("保存先フォルダを作れませんでした")


def unique_base(base, folder):
    name, i = base, 2
    while glob.glob(glob.escape(os.path.join(folder, name)) + ".*"):
        name = "%s_%d" % (base, i)
        i += 1
    return name


# ---------- 依頼の検査 → spec ----------
def build_spec(store, req):
    """クライアントからは {id, markIds, precision, maxHeight} だけを受け取り、パス・タイトル・時刻はサーバーが store から組み立てる。"""
    bad = lambda m: ApiError("bad_request", m, 400)
    v = store.internal(req.get("id"))
    if not v:
        raise ApiError("not_found", "動画が見つかりません", 404)
    ids = req.get("markIds")
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
        raise bad("書き出すマークを選んでください")
    if len(ids) > MAX_EXPORT_CLIPS:
        raise bad("書き出すマークは1度に%d件までです" % MAX_EXPORT_CLIPS)
    prec = req.get("precision")
    if prec not in (None, "accurate", "fast"):
        raise bad("precision が正しくありません")
    vol = req.get("volume", DEFAULT_EXPORT_VOLUME)
    if vol is None:
        vol = DEFAULT_EXPORT_VOLUME
    try:
        vol = int(vol)
    except (TypeError, ValueError):
        raise bad("volume が正しくありません")
    if not (MIN_EXPORT_VOLUME <= vol <= MAX_EXPORT_VOLUME):
        raise bad("volume は%d〜%dの範囲で指定してください" % (MIN_EXPORT_VOLUME, MAX_EXPORT_VOLUME))
    by_id = {m["id"]: m for m in v["marks"]}
    clips, seen = [], set()
    for i in ids:
        m = by_id.get(i)
        if m is None or i in seen:
            continue
        seen.add(i)
        clips.append({"id": i, "start": m["start"], "end": m["end"], "title": m["label"] or compact_ts(m["start"]), "label": m["label"]})
    if not clips:
        raise bad("書き出せるマークがありません(削除されたか、範囲が正しくありません)")
    if not find_tool("ffmpeg"):
        raise ApiError("no_ffmpeg", "ffmpeg が見つかりません。インストールして PATH に通してください", 400)
    try:
        mh = int(req.get("maxHeight") or 0)
    except (TypeError, ValueError):
        mh = 0
    spec = {"videoId": v["id"], "title": v["title"] or v["fileName"] or v["id"], "clips": clips, "fast": prec == "fast",
            "maxHeight": mh if mh in (480, 720, 1080, 1440, 2160) else 0, "volume": vol}
    if v["kind"] == "file":
        if not os.path.isfile(v["path"]):
            raise ApiError("no_file", "元の動画ファイルが見つかりません(移動・削除されていないか確認してください)", 400)
        spec.update(mode="file", sourcePath=v["path"])
    elif common.fake():
        fm = os.environ.get("STUDIO_FAKE_MEDIA", "")
        if not os.path.isfile(fm):
            raise ApiError("fake", "STUDIO_FAKE_MEDIA が指定されていません", 500)
        spec.update(mode="file", sourcePath=fm)
    else:
        if not find_tool("yt-dlp"):
            raise ApiError("no_ytdlp", "yt-dlp が見つかりません(pip install -U yt-dlp)", 400)
        spec["mode"] = "url"
    return spec


def job_public(job):
    return {"id": job["id"], "state": job["state"], "outDir": common.get_out_dir(), "folder": job.get("folder", ""),
            "items": [{k: it[k] for k in ("id", "start", "end", "title", "status", "progress", "file", "error")} for it in job["items"]]}


def start_job(spec, on_done=None):
    # 出力先の変更(common.set_out_dir)と同時に走らないよう、同じロックの下で登録する
    with common._out_lock, _jobs_lock:
        if any(j["state"] == "running" for j in _jobs.values()):
            raise ApiError("busy", "別の書き出しが実行中です。完了または中止してから始めてください", 409)
        job = {"id": uuid.uuid4().hex[:12], "videoId": spec["videoId"], "state": "running", "cancel": False, "proc": None, "created": time.time(),
               "items": [dict(c, status="queued", progress=0.0, file=None, error=None) for c in spec["clips"]]}
        _jobs[job["id"]] = job
        for old in sorted(_jobs.values(), key=lambda j: j["created"])[:-20]:
            if old["state"] != "running":
                _jobs.pop(old["id"], None)
    threading.Thread(target=run_job, args=(job, spec, on_done), daemon=True).start()
    return job


def get_job(jid):
    j = _jobs.get(str(jid or ""))
    if not j:
        raise ApiError("not_found", "ジョブが見つかりません", 404)
    return j


def cancel(jid):
    j = get_job(jid)
    j["cancel"] = True
    common.terminate(j.get("proc"))


def _pump(job, cmd, it, dur):
    """コマンドを実行して出力を読み、進捗(0〜1)を更新する。失敗時は ExportError。
    EXPORT_IDLE 秒のあいだ出力がなければ止める。中止・時間切れでは子プロセスごと止める。"""
    proc = common.spawn(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", bufsize=1)
    job["proc"] = proc
    tail = []
    last = [time.time()]
    idle = [False]
    done = threading.Event()

    def watchdog():
        while not done.wait(0.5):
            if job["cancel"]:
                common.terminate(proc)
                return
            if time.time() - last[0] > EXPORT_IDLE:
                idle[0] = True
                common.terminate(proc)
                return
    threading.Thread(target=watchdog, daemon=True).start()
    try:
        for line in proc.stdout:
            last[0] = time.time()
            if job["cancel"]:
                common.terminate(proc)
                break
            line = line.strip()
            m = re.match(r"^out_time_(?:us|ms)=(\d+)$", line) or None
            if m and dur > 0:
                it["progress"] = min(0.99, int(m.group(1)) / 1e6 / dur)
                continue
            m = re.search(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)", line)
            if m and dur > 0:
                it["progress"] = min(0.99, (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))) / dur)
            if line and not line.startswith(("out_time", "frame=", "fps=", "stream_", "bitrate=", "total_size=", "dup_frames", "drop_frames", "speed=", "progress=")):
                tail.append(line)
                tail = tail[-30:]
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            common.hard_kill(proc)
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                pass
    finally:
        done.set()
        job["proc"] = None
        if proc.poll() is None:
            common.hard_kill(proc)
    if job["cancel"]:
        raise ExportError("中止しました")
    if idle[0]:
        raise ExportError(common.idle_message("書き出し", EXPORT_IDLE))
    if proc.returncode != 0:
        raise ExportError(reason(tail) or "終了コード %s" % proc.returncode)
    return tail


ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats"]
COPY = ["-c", "copy", "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats"]


def run_ffmpeg(job, spec, it, base):
    out = os.path.join(spec["outDir"], base + ".mp4")
    dur = it["end"] - it["start"]
    src_len, has_v, _a, _l = common.media_info(spec["sourcePath"])
    if not has_v:
        raise ExportError("指定したファイルから映像を読み取れません(動画ファイルか、壊れていないか確認してください)")
    if src_len is not None:
        if it["start"] >= src_len - 0.5:
            raise ExportError("開始 %s が、このファイルの長さ %s を超えています。別の動画ファイルを指定していませんか" % (fmt_ts(it["start"])[:8], fmt_ts(src_len)[:8]))
        dur = min(it["end"], src_len) - it["start"]  # 終了が元動画の末尾を超えるときは末尾まで
    ts, ff = fmt_ts(it["start"]), find_tool("ffmpeg")
    base_cmd = [ff, "-hide_banner", "-nostdin", "-y", "-protocol_whitelist", "file,pipe"]
    # 1) -ss を -i の前に置く高速シーク(再エンコードするのでフレーム精度で切れる)
    # 2) 出力が空になるファイル向けの予備: -i の後に置く精密シーク(先頭から読むので遅いが確実)
    attempts = [base_cmd + ["-ss", ts, "-i", spec["sourcePath"], "-t", "%.3f" % dur] + ENC + [out],
                base_cmd + ["-i", spec["sourcePath"], "-ss", ts, "-t", "%.3f" % dur] + ENC + [out]]
    if spec.get("fast"):
        # 高速: 再エンコードなしのコピー(キーフレーム単位)。コーデックの都合で失敗・空になったら精密方式に自動で切り替える
        attempts.insert(0, base_cmd + ["-ss", ts, "-i", spec["sourcePath"], "-t", "%.3f" % dur] + COPY + [out])
    last = None
    for n, cmd in enumerate(attempts, 1):
        tail = []
        try:
            tail = _pump(job, cmd, it, dur)
            verify_output(out, dur, tail)
            return spec["folder"] + "/" + os.path.basename(out)
        except ExportError as e:
            last = e
            log_export("ffmpeg 方法%d 失敗: %s" % (n, e), cmd, tail)
            if os.path.exists(out):
                os.unlink(out)
            if job["cancel"]:
                raise
            it["progress"] = 0
    raise last


def _fsel(spec):
    mh = spec["maxHeight"]
    return "bv*+ba/b" if not mh else "bv*[height<=%d]+ba/b[height<=%d]/b" % (mh, mh)


def _ytdlp_sections(job, spec, it, base):
    """方法1: yt-dlp の区間ダウンロード(必要な部分だけ取得し、切れ目で再エンコード)。"""
    cmd = [find_tool("yt-dlp"), "--no-playlist", "--no-warnings", "--newline", "--ffmpeg-location", find_tool("ffmpeg"), "--download-sections", "*%s-%s" % (fmt_ts(it["start"]), fmt_ts(it["end"]))]
    if not spec.get("fast"):   # 高速のときは切れ目で再エンコードしない(キーフレーム単位)
        cmd.append("--force-keyframes-at-cuts")
    cmd += ["-f", _fsel(spec), "--merge-output-format", "mp4", "-o", os.path.join(spec["outDir"], base + ".%(ext)s"), "--", "https://www.youtube.com/watch?v=" + spec["videoId"]]
    tail = []
    try:
        tail = _pump(job, cmd, it, it["end"] - it["start"])
        files = [f for f in glob.glob(glob.escape(os.path.join(spec["outDir"], base)) + ".*") if not f.endswith((".part", ".ytdl", ".temp"))]
        if not files:
            raise ExportError("出力ファイルが見つかりませんでした")
        out = sorted(files)[0]
        verify_output(out, it["end"] - it["start"], tail)
        return out
    except ExportError as e:
        log_export("yt-dlp 区間ダウンロード失敗: %s" % e, cmd, tail)
        raise
    finally:
        if sys.exc_info()[0] is not None:
            for f in glob.glob(glob.escape(os.path.join(spec["outDir"], base)) + ".*"):
                try:
                    os.unlink(f)
                except OSError:
                    pass


def stream_urls(spec):
    """yt-dlp -g で映像/音声の直接URLを得る(取得だけで、ダウンロードはしない)。"""
    cmd = [find_tool("yt-dlp"), "--no-playlist", "--no-warnings", "-g", "-f", _fsel(spec), "--", "https://www.youtube.com/watch?v=" + spec["videoId"]]
    try:
        p = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", timeout=90)
    except (OSError, subprocess.SubprocessError):
        raise ExportError("yt-dlp を実行できませんでした")
    urls = [l.strip() for l in (p.stdout or "").splitlines() if l.strip()]
    if p.returncode != 0 or not urls or len(urls) > 2 or not all(u.startswith(("https://", "http://")) for u in urls):
        log_export("yt-dlp -g 失敗", cmd, ((p.stderr or "").strip().splitlines() or [""])[-3:])
        raise ExportError("ストリームのURLを取得できません: " + redact(((p.stderr or "").strip().splitlines() or ["不明"])[-1])[:200])
    return urls


def _ytdlp_stream(job, spec, it, base):
    """方法2(予備): 直接URLを ffmpeg に渡して、その区間だけ読み込む。方法1で空になる場合に有効。"""
    urls = stream_urls(spec)
    out = os.path.join(spec["outDir"], base + ".mp4")
    dur = it["end"] - it["start"]
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-protocol_whitelist", "file,http,https,tcp,tls,crypto"]
    for u in urls:
        cmd += ["-ss", fmt_ts(it["start"]), "-i", u]
    if len(urls) == 2:
        cmd += ["-map", "0:v:0", "-map", "1:a:0"]
    cmd += ["-t", "%.3f" % dur] + ENC + [out]
    tail = []
    try:
        tail = _pump(job, cmd, it, dur)
        verify_output(out, dur, tail)
        return out
    except ExportError as e:
        log_export("ストリーム直接指定 失敗: %s" % e, ["ffmpeg", "...(URLは省略)..."], tail)
        if os.path.exists(out):
            os.unlink(out)
        raise


def run_ytdlp(job, spec, it, base):
    try:
        out = _ytdlp_sections(job, spec, it, base)
    except ExportError as e1:
        if job["cancel"]:
            raise
        it["progress"] = 0
        try:
            out = _ytdlp_stream(job, spec, it, base)
        except ExportError as e2:
            if job["cancel"]:
                raise
            raise ExportError("方法1(区間取得): %s / 方法2(直接指定): %s" % (str(e1)[:200], str(e2)[:200]))
    return spec["folder"] + "/" + os.path.basename(out)


def apply_volume(job, spec, it, rel_file):
    """書き出したクリップの音量を調整する(file/url どちらの方式で切り出したかによらず、常に最後にこの一手間をかける)。
    映像は無劣化のまま(-c:v copy)、音声だけ volume フィルタをかけて再エンコードする。
    volume が100(調整なし)ならこの手間自体を省く。"""
    vol = spec.get("volume", 100)
    if vol == 100:
        return
    path = os.path.join(spec["outDir"], os.path.basename(rel_file))
    tmp = path + ".vol.mp4"
    dur = it["end"] - it["start"]
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-i", path, "-c:v", "copy", "-af", "volume=%.3f" % (vol / 100),
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", tmp]
    tail = []
    try:
        tail = _pump(job, cmd, it, dur)
        verify_output(tmp, dur, tail)
    except ExportError as e:
        log_export("音量調整 失敗: %s" % e, cmd, tail)
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    os.replace(tmp, path)


def run_job(job, spec, on_done=None):
    try:
        os.makedirs(common.get_out_dir(), exist_ok=True)
        spec["folder"], spec["outDir"] = pick_folder(spec)
    except (ExportError, OSError) as e:
        for it in job["items"]:
            it["status"], it["error"] = "error", str(e)[:200]
        job["state"] = "error"
        return
    job["folder"] = spec["folder"]
    for idx, it in enumerate(job["items"], 1):
        if job["cancel"]:
            it["status"] = "cancelled"
            continue
        it["status"] = "running"
        label = safe_name(it["label"], 30)
        base = unique_base("%02d_%s-%s%s" % (idx, compact_ts(it["start"]), compact_ts(it["end"]), "_" + label if label else ""), spec["outDir"])
        try:
            it["file"] = (run_ytdlp if spec["mode"] == "url" else run_ffmpeg)(job, spec, it, base)
            apply_volume(job, spec, it, it["file"])
            it["status"], it["progress"] = "done", 1.0
            if on_done:
                try:
                    on_done(spec["videoId"], it["id"], it["file"])
                except Exception:   # 保存の失敗で書き出し自体は失敗にしない
                    pass
        except ExportError as e:
            it["status"] = "cancelled" if job["cancel"] else "error"
            it["error"] = None if job["cancel"] else str(e)[:400]
        except Exception as e:  # 想定外の失敗でもジョブ全体は止めない
            it["status"], it["error"] = "error", "内部エラー: %s" % e.__class__.__name__
    job["state"] = "cancelled" if job["cancel"] else ("error" if any(i["status"] == "error" for i in job["items"]) else "done")
