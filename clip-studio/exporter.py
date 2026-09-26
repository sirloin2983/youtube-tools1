"""③ 書き出し(クリップマーカー cm/serve.py 由来): store の動画・マークから ffmpeg / yt-dlp でクリップを mp4 にする。

- file 動画は元ファイルを ffmpeg で切り出す。youtube 動画は yt-dlp(疑似モードでは STUDIO_FAKE_MEDIA を ffmpeg で切り出す)。
- 出力先は <出力先>/<動画名>/ (動画ごとのフォルダ)。1度に1ジョブ。
- 各 item が成功した時点で on_done(video_id, mark_id, "フォルダ/ファイル.mp4", 開始, 終了) を呼ぶ(store がマークを exported にする)。
- 書き出した mp4 ごとに、隣へ youtube-tools-clip/v1 の <名前>.clip.json を書く(docs/pipeline.md の 2.1。書けなくても書き出しは成功扱いで、警告だけ出す)。
"""
import glob
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import uuid

import common
import handoff
from common import ApiError, VID_RE, find_tool, redact, fmt_ts
from ytt_core import jobs  # common が ytt_core を読めるようにしてある

MAX_EXPORT_CLIPS = 50
MAX_CLIP_SEC = 3600
EXPORT_IDLE = 600   # 書き出しのコマンドが、この秒数まったく出力しなければ中止
DEFAULT_EXPORT_VOLUME = 75   # 書き出しの音量(%)。元の音量(100)だと大きすぎるとのことで既定は下げ気味
MIN_EXPORT_VOLUME, MAX_EXPORT_VOLUME = 1, 200
# ラウドネス(聞こえ方の音量。LUFS)をそろえる(2026-09-26。音量(%)の代わりに選べる)。YouTube は再生時に約 -14 LUFS に下げるので、それを目安にする
LOUDNESS_CHOICES = (-11.0, -14.0, -16.0, -18.0)
TRUE_PEAK_CEIL = -1.0   # 上げたときに音が割れないよう、ピーク(トゥルーピーク)をこれより上げない(dBTP)
MAX_GAIN_DB = 20.0      # 静かすぎる切り抜きを持ち上げすぎない(雑音まで大きくなる)
EDIT_HANDLE_SEC = 10.0
# Windows の MAX_PATH(260)より少し短く抑える。長いパスを有効にしていない PC や、ffmpeg・yt-dlp の一時ファイル名(.part など)の分の余裕。
# UTF-16 の単位で数える(Windows のパスの長さの数え方。絵文字などは2つ分)
MAX_PATH_UNITS = 240
SUFFIX_ROOM = 24    # base のあとに付く最長の名前(_edit.clip.json / _edit.mp4.vol.mp4 / yt-dlp の .f399.mp4.part など)
BASE_ROOM = 26      # 01_00h00m00s-00h00m00s(22文字)+ 連番 _NN の分。ラベルは余った分だけ付ける
LOG_MAX = 200000    # export-log.txt がこれを超えたら export-log.old.txt に回す
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
    s = re.sub(r'[\\/:*?"<>|%\x00-\x1f]+', "_", str(s or ""))
    return s[:n].strip(" ._")


# Windows の予約名(拡張子を付けても・後ろに空白があっても使えない)。上付き数字の COM¹ などと CONIN$ / CONOUT$ も予約されている
_RES_DIGITS = [str(i) for i in range(1, 10)] + ["\u00b9", "\u00b2", "\u00b3"]
WIN_RESERVED = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {"COM" + d for d in _RES_DIGITS} | {"LPT" + d for d in _RES_DIGITS}


def is_reserved(name):
    return name.split(".", 1)[0].rstrip(" ").upper() in WIN_RESERVED


def path_units(s):
    """Windows のパスの長さ(UTF-16 の単位)。"""
    return len(str(s).encode("utf-16-le", "surrogatepass")) // 2


def trim_units(s, n):
    """UTF-16 の単位で n 以下になるよう後ろを削る(削った後の末尾の空白・ドット・_ も除く)。"""
    s = str(s)
    while s and path_units(s) > n:
        s = s[:-1]
    return s.rstrip(" ._")


def log_export(note, cmd, tail):
    """失敗の切り分け用に、実行コマンドとツールの出力を <出力先>/export-log.txt に残す。"""
    try:
        d = common.get_out_dir()
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "export-log.txt")
        if os.path.exists(p) and os.path.getsize(p) > LOG_MAX:   # 消さずに1世代残す(失敗の直後に大きくなって消える、を防ぐ)
            common.replace_file(p, os.path.join(d, "export-log.old.txt"))
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
    # 出力先が長いときは、フォルダ名を短くしてファイル名(BASE_ROOM + ラベル + SUFFIX_ROOM)の分を残す
    room = MAX_PATH_UNITS - path_units(root) - 1 - 3 - 1 - BASE_ROOM - SUFFIX_ROOM
    name = trim_units(safe_name(spec["title"], 60), max(8, min(60, room))) or spec["videoId"]
    if is_reserved(name):
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
    """フォルダ内で使われていない名前。<名前>.* だけでなく、同時に作る <名前>_edit.* も空いていることを確かめる
    (前回の編集用素材だけが残っていると、ffmpeg の -y で上書き・yt-dlp は取得済みとして古い物を使ってしまうため)。"""
    def used(name):
        return any(glob.glob(glob.escape(os.path.join(folder, n)) + ".*") for n in (name, name + "_edit"))
    name, i = base, 2
    while used(name):
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
    loud = req.get("loudness")
    if loud in (None, False, 0):
        loud = None
    else:
        try:
            loud = float(loud)
        except (TypeError, ValueError):
            raise bad("loudness が正しくありません")
        if loud not in LOUDNESS_CHOICES:
            raise bad("loudness は %s のどれかです" % " / ".join("%g" % x for x in LOUDNESS_CHOICES))
    by_id = {m["id"]: m for m in v["marks"]}
    clips, seen = [], set()
    for i in ids:
        m = by_id.get(i)
        if m is None or i in seen:
            continue
        seen.add(i)
        clips.append({"id": i, "start": m["start"], "end": m["end"], "title": m["label"] or compact_ts(m["start"]), "label": m["label"],
                      "src": m.get("src") or "manual", "markStatus": m.get("status") or ""})
    if not clips:
        raise bad("書き出せるマークがありません(削除されたか、範囲が正しくありません)")
    if not find_tool("ffmpeg"):
        raise ApiError("no_ffmpeg", "ffmpeg が見つかりません。インストールして PATH に通してください", 400)
    try:
        mh = int(req.get("maxHeight") or 0)
    except (TypeError, ValueError):
        mh = 0
    spec = {"videoId": v["id"], "title": v["title"] or v["fileName"] or v["id"], "clips": clips, "fast": prec == "fast",
            "maxHeight": mh if mh in (480, 720, 1080, 1440, 2160) else 0, "volume": vol, "loudness": loud,
            # .clip.json 用(元の配信の情報)。元のファイルのパスは file のときだけ入れる
            "kind": v["kind"], "sourceTitle": v["title"] or v.get("fileName") or "", "sourceFile": v["path"] if v["kind"] == "file" else None,
            "sourceDuration": v.get("duration") or 0}
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
        if not VID_RE.match(str(v["id"])):   # yt-dlp に渡す URL は、検査済みの動画IDだけから組み立てる(data.json を手で直された場合の備え)
            raise ApiError("bad_request", "YouTube の動画IDが正しくありません", 400)
        if not find_tool("yt-dlp"):
            raise ApiError("no_ytdlp", "yt-dlp が見つかりません(README の準備手順を確認してください)", 400)
        spec["mode"] = "url"
    return spec


PUBLIC_PATHS = ("path", "manifest", "editPath", "editManifest")


def job_public(job):
    """GET /api/export の中身。各 item の path(書き出した mp4 の絶対パス)と manifest(隣の .clip.json の絶対パス。書けなければ null)は
    完了した item だけに入る(画面の「編集で開く」リンク ?media=<path> 用)。editPath / editManifest は前後10秒の編集用素材。"""
    def paths(it):
        done = it["status"] == "done"
        return {k: (it.get(k) if done else None) for k in PUBLIC_PATHS}
    return {"id": job["id"], "state": job["state"], "outDir": job.get("outDir", common.get_out_dir()), "folder": job.get("folder", ""),
            "waiting": bool(job.get("waiting")),   # 他のツールの重い処理が終わるのを待っている(ytt_core.jobs)
            "items": [{**{k: it[k] for k in ("id", "start", "end", "title", "status", "progress", "file", "error")},
                       "warning": it.get("warning", ""), "loudness": it.get("loudness"), **paths(it)} for it in job["items"]]}


def start_job(spec, on_done=None):
    # 出力先の変更(common.set_out_dir)と同時に走らないよう、同じロックの下で登録する
    with common._out_lock, _jobs_lock:
        if any(j["state"] == "running" for j in _jobs.values()):
            raise ApiError("busy", "別の書き出しが実行中です。完了または中止してから始めてください", 409)
        job = {"id": uuid.uuid4().hex[:12], "videoId": spec["videoId"], "state": "running", "cancel": False, "proc": None, "created": time.time(),
               "outDir": common.get_out_dir(),
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
        if proc.poll() is not None:
            proc.stdout.close()
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
    it["srcLen"] = src_len
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
            it["method"] = "copy" if spec.get("fast") and n == 1 else "encode"   # copy はキーフレーム単位(開始が前にずれる)
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


def expected_len(spec, it):
    """書き出しで期待する長さ。元の長さ(分かれば)を超える分は含めない(元の末尾をまたぐマークは末尾までになるため)。"""
    lim = spec.get("sourceDuration") or 0
    end = min(it["end"], lim) if lim and lim > it["start"] else it["end"]
    return end - it["start"]


def _fsel(spec):
    mh = spec["maxHeight"]
    return "bv*+ba/b" if not mh else "bv*[height<=%d]+ba/b[height<=%d]/b" % (mh, mh)


def _ytdlp_sections(job, spec, it, base):
    """方法1: yt-dlp の区間ダウンロード(必要な部分だけ取得し、切れ目で再エンコード)。"""
    cmd = [find_tool("yt-dlp"), "--no-playlist", "--no-warnings", "--newline", "--ffmpeg-location", find_tool("ffmpeg"), "--download-sections", "*%s-%s" % (fmt_ts(it["start"]), fmt_ts(it["end"]))]
    if not spec.get("fast"):   # 高速のときは切れ目で再エンコードしない(キーフレーム単位)
        cmd.append("--force-keyframes-at-cuts")
    cmd += ["-f", _fsel(spec), "--merge-output-format", "mp4", "-o", common.ytdlp_out(spec["outDir"], base + ".%(ext)s"), "--", "https://www.youtube.com/watch?v=" + spec["videoId"]]
    tail = []
    try:
        tail = _pump(job, cmd, it, expected_len(spec, it))
        files = [f for f in glob.glob(glob.escape(os.path.join(spec["outDir"], base)) + ".*") if not f.endswith((".part", ".ytdl", ".temp"))]
        if not files:
            raise ExportError("出力ファイルが見つかりませんでした")
        out = sorted(files)[0]
        verify_output(out, expected_len(spec, it), tail)
        it["method"] = "copy" if spec.get("fast") else "encode"   # --force-keyframes-at-cuts なし = キーフレーム単位
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
    dur = expected_len(spec, it)
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
        it["method"] = "encode"
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


def _reencode_audio(job, it, path, afilter, what):
    """映像は無劣化のまま(-c:v copy)、音声だけフィルタをかけて再エンコードし、元のファイルと置き換える。"""
    tmp = path + ".vol.mp4"
    # 期待する長さは、切り出した動画そのものの長さ(マークの終了が元の末尾を超えると、切り出しは末尾で止まって短くなるため。
    # 以前はマークの長さと比べていて、末尾をまたぐマークが「短すぎます」で失敗していた)
    dur = common.media_info(path)[0] or (it["end"] - it["start"])
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-i", path, "-c:v", "copy", "-af", afilter,
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", tmp]
    tail = []
    try:
        tail = _pump(job, cmd, it, dur)
        verify_output(tmp, dur, tail)
    except ExportError as e:
        log_export("%s 失敗: %s" % (what, e), cmd, tail)
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    common.replace_file(tmp, path)


def apply_volume(job, spec, it, rel_file):
    """書き出したクリップの音量を調整する(file/url どちらの方式で切り出したかによらず、常に最後にこの一手間をかける)。
    volume が100(調整なし)・ラウドネスをそろえるとき(apply_loudness が行う)は何もしない。"""
    vol = spec.get("volume", 100)
    if vol == 100 or spec.get("loudness"):
        return
    _reencode_audio(job, it, os.path.join(spec["outDir"], os.path.basename(rel_file)), "volume=%.3f" % (vol / 100), "音量調整")


def measure_loudness(job, it, path):
    """(統合ラウドネス LUFS, トゥルーピーク dBTP)。無音・測れないときは (None, None)。ffmpeg の loudnorm で測るだけ(書き換えない)"""
    dur = common.media_info(path)[0] or (it["end"] - it["start"])
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-i", path, "-vn", "-af", "loudnorm=print_format=json",
           "-f", "null", "-", "-progress", "pipe:1", "-nostats"]
    tail = _pump(job, cmd, it, dur)
    text = "\n".join(tail)
    vals = {}
    for key in ("input_i", "input_tp"):
        m = re.search(r'"%s"\s*:\s*"([^"]+)"' % key, text)
        try:
            vals[key] = float(m.group(1)) if m else None
        except ValueError:
            vals[key] = None
    i, tp = vals["input_i"], vals["input_tp"]
    if i is None or not (-70.0 <= i <= 10.0) or tp is None or tp != tp or abs(tp) == float("inf"):
        return None, None
    return i, tp


def apply_loudness(job, spec, it):
    """切り抜き(と前後10秒つきの編集用素材)の聞こえ方の音量を spec["loudness"](LUFS)にそろえる。
    切り抜き本体で測った分だけ、両方に**同じ量**だけ音量をかける(Resolve で切り抜きと編集用素材を差し替えても音量が変わらないように)。
    上げる量は、どちらのピークも TRUE_PEAK_CEIL を超えない・MAX_GAIN_DB を超えない範囲まで(音が割れない・雑音を持ち上げすぎない)。
    -> it["loudness"] = {"target", "measured", "gainDb"}(無音で測れないときは skipped)"""
    target = spec.get("loudness")
    if not target:
        return
    main = it["path"]
    i, tp = measure_loudness(job, it, main)
    if i is None:
        it["loudness"] = {"target": target, "skipped": "音声が無いか、無音のため測れませんでした"}
        return
    gain = min(target - i, TRUE_PEAK_CEIL - tp, MAX_GAIN_DB)
    edit = it.get("editPath")
    if edit and os.path.isfile(edit):
        _ei, etp = measure_loudness(job, it, edit)
        if etp is not None:
            gain = min(gain, TRUE_PEAK_CEIL - etp)
    gain = round(gain, 2)
    if abs(gain) >= 0.1:
        for path in [main] + ([edit] if edit and os.path.isfile(edit) else []):
            _reencode_audio(job, it, path, "volume=%.2fdB" % gain, "ラウドネス調整")
    it["loudness"] = {"target": target, "measured": round(i, 1), "gainDb": gain}


def export_edit_media(job, spec, it, base, runner):
    """Create an additional media file with trim handles and a portable sidecar."""
    edit_it = dict(it)
    edit_it["start"] = max(0.0, float(it["start"]) - EDIT_HANDLE_SEC)
    edit_it["end"] = float(it["end"]) + EDIT_HANDLE_SEC
    edit_it["progress"] = 0.0
    rel = runner(job, spec, edit_it, base + "_edit")
    apply_volume(job, spec, edit_it, rel)
    media_path = os.path.join(spec["outDir"], os.path.basename(rel))
    actual, _v, _a, _line = common.media_info(media_path)
    selection_in = float(it["start"]) - edit_it["start"]
    selected = float(it["end"]) - float(it["start"])
    expected = edit_it["end"] - edit_it["start"]
    handle_after = max(0.0, (actual if actual is not None else expected) - selection_in - selected)
    sidecar = os.path.join(spec["outDir"], base + ".edit.json")
    data = {"schema": "clip-studio/edit-media/v1", "media": os.path.basename(media_path),
            "selectionIn": round(selection_in, 3), "handleBefore": round(selection_in, 3),
            "handleAfter": round(handle_after, 3), "sourceStart": edit_it["start"], "sourceEnd": edit_it["end"]}
    common.atomic_write(sidecar, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))   # Windows の一時的なロックは再試行
    it["editPath"] = media_path
    it["editRange"] = (edit_it["start"], edit_it["end"])
    it["editMethod"] = edit_it.get("method")
    it["editSrcLen"] = edit_it.get("srcLen")
    return rel


# ---------- youtube-tools-clip/v1(.clip.json) ----------
def _ffprobe_json(args, timeout=30):
    fp = find_tool("ffprobe")
    if not fp:
        return None
    try:
        r = subprocess.run([fp, "-v", "error", "-of", "json"] + args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return json.loads(r.stdout or "null") if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def copy_actual_start(source, start, output):
    """速度優先(コピー)で切り出した動画の 0 秒が、元の動画の何秒かを求める。分からなければ None。
    ffmpeg は入力側の -ss で「start 以前で最後のキーフレーム」から切り出すので、ffprobe でそのキーフレームを探し、
    出力側の映像の開始時刻(B フレームの遅延ぶん。例 0.2 秒)を引く。ffprobe が無い・読めない形式なら諦める(推定値は入れない)。"""
    fmt = _ffprobe_json(["-show_entries", "format=start_time", source])
    if not isinstance(fmt, dict):
        return None
    base = _num((fmt.get("format") or {}).get("start_time")) or 0.0   # .ts などは 0 から始まらない。-ss はこの値からの相対
    lo = max(0.0, start - 60)
    pk = _ffprobe_json(["-select_streams", "v:0", "-read_intervals", "%.3f%%%.3f" % (base + lo, base + start + 0.05),
                        "-show_entries", "packet=pts_time,flags", source])
    keys = []
    for pkt in (pk or {}).get("packets") or []:
        t = _num(pkt.get("pts_time"))
        if t is not None and "K" in str(pkt.get("flags") or "") and t - base <= start + 0.001:
            keys.append(t - base)
    if not keys:
        return None
    out = _ffprobe_json(["-select_streams", "v:0", "-show_entries", "stream=start_time", output])
    streams = (out or {}).get("streams") or []
    vstart = _num(streams[0].get("start_time")) if streams else None
    return round(max(0.0, max(keys) - (vstart or 0.0)), 3)


def _clip_export_info(spec, method, source_ok, rng_start, media_path, loudness=None):
    info = {"mode": "fast" if method == "copy" else "precise"}
    if spec.get("loudness"):
        info["loudness"] = loudness or {"target": spec["loudness"]}   # そろえたラウドネス(音量(%)は使っていない)
    else:
        info["volume"] = spec.get("volume", 100)
    if method == "copy" and source_ok:
        a = copy_actual_start(spec["sourcePath"], rng_start, media_path)
        if a is not None:
            info["actualStart"] = a
    return info


def write_manifests(spec, it, mark_status):
    """書き出した mp4(と編集用素材)の隣に .clip.json を書く。range は元の配信の秒(元の長さを超える分は切り詰める)。"""
    kind = spec.get("kind") or ("file" if spec.get("mode") == "file" else "youtube")
    source = {"kind": kind, "videoId": spec.get("videoId"), "title": spec.get("sourceTitle") or "", "path": spec.get("sourceFile")}
    mark = {"id": it.get("id"), "label": it.get("label"), "status": mark_status, "src": it.get("src")}
    # 元の長さが分かれば、終了をそこで切り詰める(ffmpeg は元の末尾で止まる)
    local_src = spec.get("mode") == "file" and bool(spec.get("sourcePath"))

    def end_of(end, src_len):
        lim = src_len or spec.get("sourceDuration") or 0
        return min(end, lim) if lim and lim > 0 else end
    media = it["path"]
    dur = common.media_info(media)[0]
    it["manifest"] = handoff.write_clip_manifest(media, duration=dur, source=source, mark=mark,
                                                 rng=(it["start"], end_of(it["end"], it.get("srcLen"))),
                                                 export=_clip_export_info(spec, it.get("method"), local_src, it["start"], media, it.get("loudness")))
    if it.get("editPath") and it.get("editRange"):
        es, ee = it["editRange"]
        edur = common.media_info(it["editPath"])[0]
        ex = _clip_export_info(spec, it.get("editMethod"), local_src, es, it["editPath"], it.get("loudness"))
        ex.update(purpose="edit-handles", selection={"start": it["start"], "end": it["end"]})   # 切り抜き本体の範囲(元の配信の秒)
        it["editManifest"] = handoff.write_clip_manifest(it["editPath"], duration=edur, source=source, mark=mark,
                                                         rng=(es, end_of(ee, it.get("editSrcLen"))), export=ex)


def run_job(job, spec, on_done=None):
    """重い処理の同時実行数の上限(ytt_core.jobs)の順番を待ってから書き出す。待っている間は job["waiting"] が真"""
    with jobs.SLOTS.slot("studio", "書き出し %d 本" % len(job["items"]), cancelled=lambda: job["cancel"],
                         on_wait=lambda: job.update(waiting=True)) as ok:
        job["waiting"] = False
        if not ok:
            for it in job["items"]:
                if it["status"] == "queued":
                    it["status"] = "cancelled"
            job["state"] = "cancelled"
            return
        _run_job(job, spec, on_done)


def _run_job(job, spec, on_done=None):
    try:
        os.makedirs(common.get_out_dir(), exist_ok=True)
        spec["folder"], spec["outDir"] = pick_folder(spec)
    except (ExportError, OSError) as e:
        common.log_failure("書き出し先の準備", e)
        for it in job["items"]:
            it["status"], it["error"] = "error", common.permission_message(e) if isinstance(e, PermissionError) else str(e)[:200]
        job["state"] = "error"
        return
    job["folder"] = spec["folder"]
    for idx, it in enumerate(job["items"], 1):
        if job["cancel"]:
            it["status"] = "cancelled"
            continue
        it["status"] = "running"
        try:
            head = "%02d_%s-%s" % (idx, compact_ts(it["start"]), compact_ts(it["end"]))
            # ラベルは、出力先+ファイル名が MAX_PATH_UNITS に収まる分だけ付ける(連番 _NN と SUFFIX_ROOM の分を残す)
            room = MAX_PATH_UNITS - SUFFIX_ROOM - 3 - 1 - path_units(os.path.join(spec["outDir"], head))
            label = trim_units(safe_name(it["label"], 30), max(0, room))
            base = unique_base(head + ("_" + label if label else ""), spec["outDir"])
            runner = run_ytdlp if spec["mode"] == "url" else run_ffmpeg
            it["file"] = runner(job, spec, it, base)
            it["path"] = os.path.join(spec["outDir"], os.path.basename(it["file"]))
            apply_volume(job, spec, it, it["file"])
            warnings = []
            try:
                it["editFile"] = export_edit_media(job, spec, it, base, runner)
            except Exception as e:
                common.log_failure("Resolve edit media", e)
                it.pop("editPath", None)
                warnings.append("Resolve用の前後10秒素材を作れませんでした: %s" % str(e)[:180])
            apply_loudness(job, spec, it)   # 編集用素材ができてから、両方に同じ量をかける
            recorded = False
            if on_done:
                try:
                    recorded = bool(on_done(spec["videoId"], it["id"], it["file"], it["start"], it["end"], it.get("path")))
                except Exception as e:   # 動画はできているが、マークへの記録失敗は通知する
                    common.log_failure("書き出し済みマークの保存", e)
                    warnings.append("動画は保存できましたが、書き出し済みの記録に失敗しました。再実行前に出力ファイルを確認してください。")
            try:
                # 書き出し中にマークを動かした等で記録されなかったときは、書き出しを始めた時点の判定を入れる
                write_manifests(spec, it, "exported" if recorded else (it.get("markStatus") or ""))
            except Exception as e:   # 受け渡し用の情報が書けなくても、書き出した動画はそのまま使える
                common.log_failure("切り抜きの情報ファイル(.clip.json)の保存", e)
                it["manifest"] = None
                warnings.append("切り抜きの情報ファイル(.clip.json)を保存できませんでした(動画はそのまま使えます): %s"
                                % (common.permission_message(e) if isinstance(e, PermissionError) else str(e)[:160]))
            if warnings:
                it["warning"] = " / ".join(warnings)
            it["status"], it["progress"] = "done", 1.0
        except ExportError as e:
            it["status"] = "cancelled" if job["cancel"] else "error"
            it["error"] = None if job["cancel"] else str(e)[:400]
        except PermissionError as e:
            common.log_failure("クリップ書き出し", e)
            it["status"], it["error"] = "error", common.permission_message(e)
        except Exception as e:  # 想定外の失敗でもジョブ全体は止めない
            common.log_failure("クリップ書き出し", e)
            it["status"], it["error"] = "error", "内部エラー: %s(詳細は studio-errors.log)" % e.__class__.__name__
    job["state"] = "cancelled" if job["cancel"] else ("error" if any(i["status"] == "error" for i in job["items"]) else "done")
