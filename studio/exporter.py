"""③ 書き出し(クリップマーカー cm/serve.py 由来): store の動画・マークから ffmpeg / yt-dlp でクリップを mp4 にする。

- file 動画は元ファイルを ffmpeg で切り出す。youtube 動画は yt-dlp(疑似モードでは STUDIO_FAKE_MEDIA を ffmpeg で切り出す)。
- 書き出す動画はいつも 30fps(H.264・yuv420p・AAC。2026-10-04 Q1。作り直しの設定は ytt_core/normalize.py の1か所)。
  「精密」= veryfast・「高速」= ultrafast で作り直す(どちらも crf 18・位置ちょうど。以前の「高速」= コピーは fps を変えられないのでやめた)。
- 出力先は <出力先>/<動画名>/ (動画ごとのフォルダ)。1度に1ジョブ。
- 各 item が成功した時点で on_done(video_id, mark_id, "フォルダ/ファイル.mp4", 開始, 終了) を呼ぶ(store がマークを exported にする)。
- 書き出した mp4 ごとに、隣へ youtube-tools-clip/v1 の <名前>.clip.json を書く(docs/spec/pipeline.md の 2.1。書けなくても書き出しは成功扱いで、警告だけ出す)。
"""
import glob
import json
import os
import re
import subprocess
import threading
import time
import uuid

import common
import handoff
from common import ApiError, VID_RE, find_tool, redact, fmt_ts
from ytt_core import jobs, loudness as _loud, normalize as _norm, schemas  # common が ytt_core を読めるようにしてある

MAX_EXPORT_CLIPS = 50
MAX_CLIP_SEC = 3600
EXPORT_IDLE = 600   # 書き出しのコマンドが、この秒数まったく出力しなければ中止
DEFAULT_EXPORT_VOLUME = 75   # 書き出しの音量(%)。元の音量(100)だと大きすぎるとのことで既定は下げ気味
MIN_EXPORT_VOLUME, MAX_EXPORT_VOLUME = 1, 200
# ラウドネス(聞こえ方の音量。LUFS)をそろえる(2026-09-26。音量(%)の代わりに選べる)。YouTube は再生時に約 -14 LUFS に下げるので、それを目安にする
# 選べる値・ピークの上限・上げる量の上限と、測った結果の読み方は ytt_core/loudness.py の1か所(パック作りと共通。2026-09-29)
LOUDNESS_CHOICES = _loud.CHOICES
TRUE_PEAK_CEIL = _loud.TRUE_PEAK_CEIL   # 上げたときに音が割れないよう、ピーク(トゥルーピーク)をこれより上げない(dBTP)
MAX_GAIN_DB = _loud.MAX_GAIN_DB         # 静かすぎる切り抜きを持ち上げすぎない(雑音まで大きくなる)
EDIT_HANDLE_SEC = 10.0
# Windows の MAX_PATH(260)より少し短く抑える。長いパスを有効にしていない PC や、ffmpeg・yt-dlp の一時ファイル名(.part など)の分の余裕。
# UTF-16 の単位で数える(Windows のパスの長さの数え方。絵文字などは2つ分)
MAX_PATH_UNITS = 240
SUFFIX_ROOM = 36    # base のあとに付く最長の名前(作業用/ + _edit.partial.mp4.vol.mp4 / yt-dlp の区間取得の 作業用/ + _edit_dl.partial.f399.mp4.part など)
BASE_ROOM = 26      # 01_00h00m00s-00h00m00s(22文字)+ 連番 _NN の分。ラベルは余った分だけ付ける
LOG_MAX = 200000    # export-log.txt がこれを超えたら export-log.old.txt に回す
# 書きかけの印(2026-09-30。設計レビュー studio の 4)。書き出しは <base>.partial.mp4 に書き、音量・ラウドネスまで仕上がったら <base>.mp4 へ置き換える
# (途中で止まった・落ちたときに、壊れた・仕上がっていないファイルが完成品と同じ名前で残らないように)。拡張子は .mp4 のまま(ffmpeg は拡張子で形式を決める)
PARTIAL = ".partial"
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


def _marker(path):
    """フォルダの持ち主の印 .studio-id を書く場所(作業用/。途中のファイルは直下に置かない。2026-09-27)"""
    return os.path.join(path, schemas.WORK_DIR, ".studio-id")


def _read_owner(path):
    """印を読む(作業用/ → 以前の置き方 = フォルダの直下)。無ければ None"""
    for m in (_marker(path), os.path.join(path, ".studio-id")):
        try:
            with open(m, encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            continue
    return None


def _write_owner(path, video_id):
    os.makedirs(os.path.join(path, schemas.WORK_DIR), exist_ok=True)
    with open(_marker(path), "w", encoding="utf-8") as f:
        f.write(video_id)


def pick_folder(spec):
    """動画ごとの保存先フォルダ(<出力先>/<動画名>/)を決める。
    フォルダ内の 作業用/.studio-id(以前はフォルダの直下)に動画IDを記録し、同名の別動画とは混ざらないよう連番を付ける。"""
    root = common.get_out_dir()
    # 出力先が長いときは、フォルダ名を短くしてファイル名(BASE_ROOM + ラベル + SUFFIX_ROOM)の分を残す
    room = MAX_PATH_UNITS - path_units(root) - 1 - 3 - 1 - BASE_ROOM - SUFFIX_ROOM
    name = trim_units(safe_name(spec["title"], 60), max(8, min(60, room))) or spec["videoId"]
    if is_reserved(name):
        name = "_" + name
    for i in range(1, 100):
        cand = name if i == 1 else "%s_%d" % (name, i)
        path = os.path.join(root, cand)
        if not os.path.exists(path):
            os.makedirs(path)
            _write_owner(path, spec["videoId"])
            return cand, path
        if os.path.isdir(path):
            owner = _read_owner(path)
            if owner == spec["videoId"]:
                return cand, path
            if owner is None:  # 手で作られたフォルダは、その動画のものとして使う
                _write_owner(path, spec["videoId"])
                return cand, path
    raise ExportError("保存先フォルダを作れませんでした")


def unique_base(base, folder):
    """フォルダ内で使われていない名前。<名前>.* だけでなく、同時に作る <名前>_edit.* も空いていることを確かめる
    (前回の編集用素材だけが残っていると、ffmpeg の -y で上書き・yt-dlp は取得済みとして古い物を使ってしまうため)。
    途中のファイルの 作業用/ の中も見る(2026-09-27 から .clip.json・_edit.mp4 などはそこ。以前の置き方の直下も見る)"""
    def used(name):
        return any(glob.glob(glob.escape(os.path.join(d, n)) + ".*")
                   for d in (folder, os.path.join(folder, schemas.WORK_DIR)) for n in (name, name + "_edit"))
    name, i = base, 2
    while used(name):
        name = "%s_%d" % (base, i)
        i += 1
    return name


def partial_path(folder, base, ext=".mp4"):
    """書きかけのファイルの場所(同じフォルダ・<base>.partial.mp4。置き換えが同じドライブの中で済む)。"""
    return os.path.join(folder, base + PARTIAL + ext)


def is_partial(path):
    return os.path.splitext(os.path.basename(str(path or "")))[0].endswith(PARTIAL)


def final_path(path):
    """<base>.partial.<拡張子> → <base>.<拡張子>(書きかけでなければそのまま)。"""
    if not is_partial(path):
        return path
    d, n = os.path.split(path)
    root, ext = os.path.splitext(n)
    return os.path.join(d, root[:-len(PARTIAL)] + ext)


def promote(path):
    """仕上がった書きかけのファイルを本当の名前へ置き換える(ytt_core.fsio.replace_retry。一時的な共有違反は再試行)。本当の名前を返す。"""
    if not is_partial(path):
        return path
    final = final_path(path)
    common.replace_file(path, final)
    return final


def drop_partial(path):
    """失敗・中止のときに書きかけを消す(音量の調整の途中の .vol.mp4 も)。書きかけでない(仕上がった)ファイルは消さない。"""
    if not path or not is_partial(path):
        return
    for p in (path, path + ".vol.mp4"):
        try:
            os.unlink(p)
        except OSError:
            pass


def clean_partials(root=None):
    """前回の途中で残った書きかけ(<出力先>/<動画>/ と その 作業用/ の *.partial.*)を消す(起動時に裏で1回)。
    スタジオの印(.studio-id)のあるフォルダだけ(利用者が手で置いたファイルは触らない)。消した数を返す"""
    root = root or common.get_out_dir()
    n = 0
    try:
        folders = [e.path for e in os.scandir(root) if e.is_dir()]
    except OSError:
        return 0
    for folder in folders:
        if _read_owner(folder) is None:
            continue
        for d in (folder, os.path.join(folder, schemas.WORK_DIR)):
            for f in glob.glob(glob.escape(d) + os.sep + "*" + PARTIAL + ".*"):
                if is_busy():   # 起動の直後に書き出しが始まったら、その書きかけを消さないようにやめる
                    return n
                try:
                    os.unlink(f)
                    n += 1
                except OSError:
                    pass
    return n


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
    combine = req.get("combine") is True   # 選んだマークを時刻の順につないで1本の mp4 に(2026-09-28 ユーザー要望)
    if combine:
        if len(clips) < 2:
            raise bad("つなげるマークを2つ以上選んでください")
        clips.sort(key=lambda c: c["start"])
        if sum(c["end"] - c["start"] for c in clips) > MAX_COMBINE_SEC:
            raise bad("つなげた長さが長すぎます(%d分まで)" % (MAX_COMBINE_SEC // 60))
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
            "sourceDuration": v.get("duration") or 0, "combine": combine}
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
                       "warning": it.get("warning", ""), "loudness": it.get("loudness"), **paths(it)} for it in job["items"]],
            "combined": _combined_public(job.get("combined"))}


def _combined_public(c):
    """つないだ1本(combine のときだけ)。path は出来上がったときだけ"""
    if not c:
        return None
    done = c.get("status") == "done"
    return {"status": c.get("status"), "progress": c.get("progress", 0.0), "file": c.get("file") if done else None, "path": c.get("path") if done else None,
            "error": c.get("error"), "loudness": c.get("loudness"), "count": c.get("count", 0), "seconds": round(float(c.get("end") or 0), 1)}


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


def cancel_all():
    """終了の流れ用(serve.shutdown_jobs): 実行中の書き出しに中止を伝える(待たない)。子プロセスは common.stop_children がまとめて止める。
    中止したジョブの一覧を返す。ジョブは「中止」で終わり、終了のためであることは job["interrupted"] に残す"""
    with _jobs_lock:
        running = [j for j in _jobs.values() if j["state"] == "running"]
    for j in running:
        j["interrupted"] = True
        j["cancel"] = True
    return running


def _pump(job, cmd, it, dur, span=(0.0, 1.0)):
    """コマンドを実行して出力を読み、進捗(0〜1)を更新する。失敗時は ExportError。
    EXPORT_IDLE 秒のあいだ出力がなければ止める。中止・時間切れでは子プロセスごと止める。
    span: 2段で作るとき(YouTube の区間取得 → 切り出し)に、この段の進み具合を全体のどこに当てるか"""
    lo, hi = span
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
                it["progress"] = min(0.99, lo + (hi - lo) * min(1.0, int(m.group(1)) / 1e6 / dur))
                continue
            m = re.search(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)", line)
            if m and dur > 0:
                it["progress"] = min(0.99, lo + (hi - lo) * min(1.0, (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))) / dur))
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
        common.forget(proc)
        if proc.poll() is not None:
            proc.stdout.close()
    if job["cancel"]:
        raise ExportError("中止しました")
    if idle[0]:
        raise ExportError(common.idle_message("書き出し", EXPORT_IDLE))
    if proc.returncode != 0:
        raise ExportError(reason(tail) or "終了コード %s" % proc.returncode)
    return tail


# 書き出しの作り直しの設定は ytt_core/normalize.py の1か所(30fps・libx264 crf 18・yuv420p・AAC 192k・faststart。2026-10-04 Q1)
PROGRESS = ["-progress", "pipe:1", "-nostats"]
ENC = _norm.ENC_ARGS + PROGRESS              # 精密(veryfast)
ENC_FAST = _norm.ENC_FAST_ARGS + PROGRESS    # 高速(ultrafast。画質の設定 crf は同じで、ファイルが大きくなる代わりに速い)
SECTION_PAD = 2.0   # YouTube の区間取得で、前後に足す秒数(yt-dlp ではそのまま取り、正確な区間は ffmpeg で切る)
DL_TAG = "_dl"      # 区間取得の途中のファイルの名前(<base>_dl.partial.mp4。作業用/ に置き、切り出したら消す)


def _enc(spec):
    return ENC_FAST if spec.get("fast") else ENC


def _method(spec):
    """.clip.json の export.mode に使う(fast = 高速の設定で作り直した。どちらも位置ちょうどなので actualStart は無い)"""
    return "fast" if spec.get("fast") else "encode"


def run_ffmpeg(job, spec, it, base):
    """戻り値は書きかけ(<base>.partial.mp4)の "フォルダ/名前"。本当の名前へは、仕上げのあと呼び出し側が promote で置き換える"""
    out = partial_path(spec["outDir"], base)
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
    # 1) -ss を -i の前に置く高速シーク(作り直すのでフレーム精度で切れる)
    # 2) 出力が空になるファイル向けの予備: -i の後に置く精密シーク(先頭から読むので遅いが確実)
    # 高速・精密のどちらも 30fps に作り直す(高速は x264 の速い設定。コピーでは fps を変えられないため。2026-10-04 Q1)
    enc = _enc(spec)
    attempts = [base_cmd + ["-ss", ts, "-i", spec["sourcePath"], "-t", "%.3f" % dur] + enc + [out],
                base_cmd + ["-i", spec["sourcePath"], "-ss", ts, "-t", "%.3f" % dur] + enc + [out]]
    last = None
    for n, cmd in enumerate(attempts, 1):
        tail = []
        try:
            tail = _pump(job, cmd, it, dur)
            verify_output(out, dur, tail)
            it["method"] = _method(spec)
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


def _ytdlp_cmd():
    """yt-dlp を起動するコマンドの先頭(テストで偽物の yt-dlp に差し替える)"""
    return [find_tool("yt-dlp")]


def _work_dir(spec):
    """途中のファイルを置く 作業用/(編集用素材・つなぐ部品は、spec の出力先がもともと 作業用/)"""
    d = spec["outDir"]
    return d if os.path.basename(os.path.normpath(d)) == schemas.WORK_DIR else os.path.join(d, schemas.WORK_DIR)


def _drop_glob(prefix):
    for f in glob.glob(glob.escape(prefix) + ".*"):
        try:
            os.unlink(f)
        except OSError:
            pass


def _ytdlp_sections(job, spec, it, base):
    """方法1: 2段で作る(2026-10-04 Q1)。
    1) yt-dlp で区間を**そのまま**取る(作り直さない・前後に SECTION_PAD 秒の余裕。作業用/<base>_dl.partial.mp4)
    2) ffmpeg で正確な区間に切り、30fps に作り直す(書き出しと同じ ENC。crf 18)。取った区間のファイルは最後に消す。
    以前は yt-dlp の --force-keyframes-at-cuts に作り直しを任せていて、画質の設定(crf 18)を通っていなかった。
    yt-dlp は区間を ffmpeg の入力側の -ss + コピーで取るので、取ったファイルの 0 秒 = 頼んだ開始(手前のキーフレームからの分は
    mp4 の edit list で隠れる)。万一、頼んだより長い(手前のキーフレームから見えている)ときは位置が分からないので、方法2(直接指定)に回す"""
    lim = spec.get("sourceDuration") or 0
    dl_start = max(0.0, float(it["start"]) - SECTION_PAD)
    dl_end = float(it["end"]) + SECTION_PAD
    if lim and lim > it["start"]:
        dl_end = min(dl_end, lim)
    dl_len = dl_end - dl_start
    work = _work_dir(spec)
    os.makedirs(work, exist_ok=True)
    raw_base = os.path.join(work, base + DL_TAG + PARTIAL)   # yt-dlp の途中のファイル .f399.mp4.part なども、この名前から始まる
    _drop_glob(raw_base)   # 前回の残り(yt-dlp は同じ名前があると取得済みとして使ってしまう)
    out = partial_path(spec["outDir"], base)
    ff = find_tool("ffmpeg")
    cmd = _ytdlp_cmd() + ["--no-playlist", "--no-warnings", "--newline", "--ffmpeg-location", ff,
                          "--download-sections", "*%s-%s" % (fmt_ts(dl_start), fmt_ts(dl_end)),
                          "-f", _fsel(spec), "--merge-output-format", "mp4", "-o", common.ytdlp_out(work, os.path.basename(raw_base) + ".%(ext)s"),
                          "--", "https://www.youtube.com/watch?v=" + spec["videoId"]]
    tail = []
    try:
        tail = _pump(job, cmd, it, dl_len, span=(0.0, 0.5))
        files = [f for f in glob.glob(glob.escape(raw_base) + ".*")
                 if not f.endswith((".part", ".ytdl", ".temp")) and ".temp." not in os.path.basename(f)]
        if not files:
            raise ExportError("出力ファイルが見つかりませんでした")
        raw = raw_base + ".mp4" if raw_base + ".mp4" in files else sorted(files)[0]
        need = expected_len(spec, it)
        verify_output(raw, need, tail)
        raw_len = common.media_info(raw)[0]
        if raw_len is not None and raw_len > dl_len + 1.0:
            raise ExportError("取った区間の開始の位置が分かりません(頼んだ %.1f 秒より長い %.1f 秒)" % (dl_len, raw_len))
        off = float(it["start"]) - dl_start   # 取ったファイルの中での開始
        dur = min(need, raw_len - off) if raw_len is not None else need
        if dur < 0.5:
            raise ExportError("取った区間が短すぎます(%.1f 秒)" % (raw_len or 0))
        cmd = [ff, "-hide_banner", "-nostdin", "-y", "-protocol_whitelist", "file,pipe", "-ss", "%.3f" % off, "-i", raw, "-t", "%.3f" % dur] + _enc(spec) + [out]
        tail = []
        tail = _pump(job, cmd, it, dur, span=(0.5, 1.0))
        verify_output(out, dur, tail)
        it["method"] = _method(spec)
        return out
    except ExportError as e:
        log_export("yt-dlp 区間取得 → 切り出し 失敗: %s" % e, cmd, tail)
        if os.path.exists(out):
            os.unlink(out)
        raise
    finally:
        _drop_glob(raw_base)   # 取った区間は、成功・失敗のどちらでも残さない


def stream_urls(spec):
    """yt-dlp -g で映像/音声の直接URLを得る(取得だけで、ダウンロードはしない)。"""
    cmd = _ytdlp_cmd() + ["--no-playlist", "--no-warnings", "-g", "-f", _fsel(spec), "--", "https://www.youtube.com/watch?v=" + spec["videoId"]]
    try:
        p = common.run_short(cmd, timeout=90)   # spawn を通す(終了の流れで止められる・窓を出さない)
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
    out = partial_path(spec["outDir"], base)
    dur = expected_len(spec, it)
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-protocol_whitelist", "file,http,https,tcp,tls,crypto"]
    for u in urls:
        cmd += ["-ss", fmt_ts(it["start"]), "-i", u]
    if len(urls) == 2:
        cmd += ["-map", "0:v:0", "-map", "1:a:0"]
    cmd += ["-t", "%.3f" % dur] + _enc(spec) + [out]
    tail = []
    try:
        tail = _pump(job, cmd, it, dur)
        verify_output(out, dur, tail)
        it["method"] = _method(spec)
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
    return _loud.parse("\n".join(tail))


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
    edit = it.get("editPath")
    etp = measure_loudness(job, it, edit)[1] if edit and os.path.isfile(edit) else None
    gain = _loud.gain(target, i, tp, etp)
    if abs(gain) >= _loud.MIN_GAIN_DB:
        for path in [main] + ([edit] if edit and os.path.isfile(edit) else []):
            _reencode_audio(job, it, path, "volume=%.2fdB" % gain, "ラウドネス調整")
    it["loudness"] = {"target": target, "measured": round(i, 1), "gainDb": gain}


MAX_COMBINE_SEC = 3600   # つないだ長さの上限(秒)


def _run_combine(job, spec):
    """選んだマークを1本ずつ 作業用/ に切り出し(音量の調整も)、時刻の順につないで出力先の直下に1本の mp4 を作る。切り出した部品は最後に消す。
    つないだ動画は元の配信の1つの区間ではないので、.clip.json は書かず、マークにも「書き出し済み」を付けない
    (.clip.json の時刻 = 元の配信の時刻 の約束を崩さないため。文字起こしは画面の「編集で開く」から)。ラウドネスは、つないだ1本で測ってそろえる"""
    work = os.path.join(spec["outDir"], schemas.WORK_DIR)
    os.makedirs(work, exist_ok=True)
    pspec = dict(spec, outDir=work, folder=spec["folder"] + "/" + schemas.WORK_DIR)
    comb = job["combined"] = {"status": "queued", "progress": 0.0, "file": None, "path": None, "error": None, "start": 0.0, "end": 0.0,
                              "count": len(job["items"])}
    pieces = []
    try:
        for idx, it in enumerate(job["items"], 1):
            if job["cancel"]:
                it["status"] = "cancelled"
                continue
            it["status"] = "running"
            try:
                base = unique_base("つなぐ_%02d_%s-%s" % (idx, compact_ts(it["start"]), compact_ts(it["end"])), work)
                runner = run_ytdlp if spec["mode"] == "url" else run_ffmpeg
                rel = runner(job, pspec, it, base)
                apply_volume(job, pspec, it, rel)
                pieces.append(os.path.join(work, os.path.basename(rel)))
                it["status"], it["progress"] = "done", 1.0
            except ExportError as e:
                it["status"] = "cancelled" if job["cancel"] else "error"
                it["error"] = None if job["cancel"] else str(e)[:400]
            except PermissionError as e:
                common.log_failure("つなぐ部品の書き出し", e)
                it["status"], it["error"] = "error", common.permission_message(e)
            except Exception as e:
                common.log_failure("つなぐ部品の書き出し", e)
                it["status"], it["error"] = "error", "内部エラー: %s(詳細は studio-errors.log)" % e.__class__.__name__
        if job["cancel"] or any(i["status"] != "done" for i in job["items"]):
            comb["status"] = "cancelled" if job["cancel"] else "error"
            comb["error"] = None if job["cancel"] else "切り出せなかった区間があるので、つなぎませんでした"
            job["state"] = "cancelled" if job["cancel"] else "error"
            return
        comb["status"] = "running"
        items = job["items"]
        base = unique_base("つなぎ_%s-%s_%d本" % (compact_ts(items[0]["start"]), compact_ts(items[-1]["end"]), len(items)), spec["outDir"])
        out = partial_path(spec["outDir"], base)   # 書きかけに書いて、ラウドネスまで済んだら本当の名前へ
        comb["path"] = out
        concat_pieces(job, comb, pieces, out)
        apply_loudness(job, spec, comb)
        comb["path"] = promote(out)
        comb["file"] = spec["folder"] + "/" + os.path.basename(comb["path"])
        comb["status"], comb["progress"] = "done", 1.0
        job["state"] = "done"
    except ExportError as e:
        comb["status"] = "cancelled" if job["cancel"] else "error"
        comb["error"] = None if job["cancel"] else str(e)[:400]
        job["state"] = "cancelled" if job["cancel"] else "error"
    except PermissionError as e:
        common.log_failure("つなぐ", e)
        comb["status"], comb["error"], job["state"] = "error", common.permission_message(e), "error"
    except Exception as e:
        common.log_failure("つなぐ", e)
        comb["status"], comb["error"], job["state"] = "error", "内部エラー: %s(詳細は studio-errors.log)" % e.__class__.__name__, "error"
    finally:
        for p in pieces:
            for q in (p, p + ".vol.mp4"):
                try:
                    os.unlink(q)
                except OSError:
                    pass
        if comb.get("status") != "done":
            drop_partial(comb.get("path"))


def concat_pieces(job, it, pieces, out):
    """部品の mp4 を時刻の順につなぐ(再エンコード。つなぎ目で絵と音がずれないように concat フィルタ。音声の無い部品があれば映像だけ)"""
    infos = [common.media_info(p) for p in pieces]
    has_a = all(i[2] for i in infos)
    total = sum(float(i[0] or 0) for i in infos)
    it["end"] = total
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-y"]
    for p in pieces:
        cmd += ["-i", p]
    # 部品はもう 30fps だが、つないだ1本も確実に 30fps の固定にする(-filter_complex と -vf は一緒に使えないので、fps はグラフの中で)
    fc = "".join("[%d:v:0]setsar=1,%s[v%d];" % (k, _norm.fps_filter(), k) for k in range(len(pieces)))
    fc += "".join("[v%d]%s" % (k, "[%d:a:0]" % k if has_a else "") for k in range(len(pieces)))
    fc += "concat=n=%d:v=1:a=%d[v]%s" % (len(pieces), 1 if has_a else 0, "[a]" if has_a else "")
    cmd += ["-filter_complex", fc, "-map", "[v]"] + (["-map", "[a]"] if has_a else []) + _norm.encode_args(in_graph=True) + PROGRESS + [out]
    tail = []
    try:
        tail = _pump(job, cmd, it, total)
        verify_output(out, total, tail)
    except ExportError as e:
        log_export("つなぐ 失敗: %s" % e, cmd, tail)
        if os.path.exists(out):
            os.unlink(out)
        raise


def _drop_edit(it):
    """編集用素材を諦めるとき: 書きかけの素材と、その .edit.json を消す(仕上がった素材は消さない)。"""
    path = it.pop("editPath", None)
    if path and is_partial(path):
        drop_partial(path)
        side = it.pop("editSidecar", None)
        if side:
            try:
                os.unlink(side)
            except OSError:
                pass


def export_edit_media(job, spec, it, base, runner):
    """Create an additional media file with trim handles and a portable sidecar."""
    edit_it = dict(it)
    edit_it["start"] = max(0.0, float(it["start"]) - EDIT_HANDLE_SEC)
    edit_it["end"] = float(it["end"]) + EDIT_HANDLE_SEC
    edit_it["progress"] = 0.0
    # 編集用素材と .edit.json は途中のファイルなので 作業用/ に書く(出力先の直下はパックと元動画だけ。2026-09-27)
    wspec = dict(spec, outDir=os.path.join(spec["outDir"], schemas.WORK_DIR), folder=spec.get("folder", "") + "/" + schemas.WORK_DIR)
    os.makedirs(wspec["outDir"], exist_ok=True)
    rel = runner(job, wspec, edit_it, base + "_edit")   # 書きかけ(<base>_edit.partial.mp4)
    media_path = os.path.join(wspec["outDir"], os.path.basename(rel))
    try:
        apply_volume(job, wspec, edit_it, rel)
    except BaseException:
        drop_partial(media_path)
        raise
    actual, _v, _a, _line = common.media_info(media_path)
    selection_in = float(it["start"]) - edit_it["start"]
    selected = float(it["end"]) - float(it["start"])
    expected = edit_it["end"] - edit_it["start"]
    handle_after = max(0.0, (actual if actual is not None else expected) - selection_in - selected)
    sidecar = os.path.join(wspec["outDir"], base + ".edit.json")
    # 素材はまだ書きかけ(<base>_edit.partial.mp4)。仕上げのあと _run_job が本当の名前へ置き換えるので、そちらの名前を書く
    data = {"schema": "clip-studio/edit-media/v1", "media": os.path.basename(final_path(media_path)),
            "selectionIn": round(selection_in, 3), "handleBefore": round(selection_in, 3),
            "handleAfter": round(handle_after, 3), "sourceStart": edit_it["start"], "sourceEnd": edit_it["end"]}
    it["editPath"] = media_path   # 先に覚える(.edit.json が書けなかったときも、書きかけを呼び出し側が消せるように)
    it["editSidecar"] = sidecar
    common.atomic_write(sidecar, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))   # Windows の一時的なロックは再試行
    it["editRange"] = (edit_it["start"], edit_it["end"])
    it["editMethod"] = edit_it.get("method")
    it["editSrcLen"] = edit_it.get("srcLen")
    return rel


# ---------- youtube-tools-clip/v1(.clip.json) ----------
def _clip_export_info(spec, method, loudness=None):
    """.clip.json の export。mode は fast(高速の設定で作り直した)/ precise。どちらも位置ちょうど(range.start が 0 秒)なので actualStart は付けない
    (以前の「高速」= コピーはキーフレームへずれたので actualStart を付けていた。2026-10-04 Q1 で作り直しに変えた)"""
    info = {"mode": "fast" if method in ("fast", "copy") else "precise"}
    if spec.get("loudness"):
        info["loudness"] = loudness or {"target": spec["loudness"]}   # そろえたラウドネス(音量(%)は使っていない)
    else:
        info["volume"] = spec.get("volume", 100)
    return info


def write_manifests(spec, it, mark_status):
    """書き出した mp4(と編集用素材)の .clip.json を 作業用/ に書く。range は元の配信の秒(元の長さを超える分は切り詰める)。"""
    kind = spec.get("kind") or ("file" if spec.get("mode") == "file" else "youtube")
    source = {"kind": kind, "videoId": spec.get("videoId"), "title": spec.get("sourceTitle") or "", "path": spec.get("sourceFile")}
    mark = {"id": it.get("id"), "label": it.get("label"), "status": mark_status, "src": it.get("src")}
    # 元の長さが分かれば、終了をそこで切り詰める(ffmpeg は元の末尾で止まる)

    def end_of(end, src_len):
        lim = src_len or spec.get("sourceDuration") or 0
        return min(end, lim) if lim and lim > 0 else end
    media = it["path"]
    dur = common.media_info(media)[0]
    it["manifest"] = handoff.write_clip_manifest(media, duration=dur, source=source, mark=mark,
                                                 rng=(it["start"], end_of(it["end"], it.get("srcLen"))),
                                                 export=_clip_export_info(spec, it.get("method"), it.get("loudness")))
    if it.get("editPath") and it.get("editRange"):
        es, ee = it["editRange"]
        edur = common.media_info(it["editPath"])[0]
        ex = _clip_export_info(spec, it.get("editMethod"), it.get("loudness"))
        ex.update(purpose="edit-handles", selection={"start": it["start"], "end": it["end"]})   # 切り抜き本体の範囲(元の配信の秒)
        it["editManifest"] = handoff.write_clip_manifest(it["editPath"], duration=edur, source=source, mark=mark,
                                                         rng=(es, end_of(ee, it.get("editSrcLen"))), export=ex)


def run_job(job, spec, on_done=None):
    """重い処理の同時実行数の上限(ytt_core.jobs)の順番を待ってから書き出す。待っている間は job["waiting"] が真。
    想定外の例外でも、ジョブを「実行中」のまま残さない(残ると is_busy が真のままで、次の書き出し・出力先の変更・動画の削除が
    サーバーを起動し直すまで 409 になり、終了の流れも止まるのを待ち続ける)"""
    try:
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
    except BaseException as e:
        common.log_failure("書き出し(ジョブ全体)", e)
        raise
    finally:
        _settle(job)


def _settle(job):
    """ジョブが「実行中」のまま終わったら、終わりの状態を付ける(中止を伝えていれば中止、そうでなければ失敗)。"""
    if job["state"] != "running":
        return
    stop = bool(job["cancel"])
    for it in job["items"] + ([job["combined"]] if job.get("combined") else []):
        if it.get("status") in ("queued", "running"):
            it["status"] = "cancelled" if stop else "error"
            if not stop and not it.get("error"):
                it["error"] = "内部エラーで止まりました(詳細は studio-errors.log)"
    job["waiting"] = False
    job["state"] = "cancelled" if stop else "error"


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
    if spec.get("combine"):
        return _run_combine(job, spec)
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
            it["file"] = runner(job, spec, it, base)   # 書きかけ(<base>.partial.mp4)
            it["path"] = os.path.join(spec["outDir"], os.path.basename(it["file"]))
            apply_volume(job, spec, it, it["file"])
            warnings = []
            try:
                it["editFile"] = export_edit_media(job, spec, it, base, runner)
            except Exception as e:
                _drop_edit(it)
                if job["cancel"]:   # 中止(終了の流れを含む)なら、本体も仕上げずに止める(書きかけは下の finally で消える)
                    raise ExportError("中止しました")
                common.log_failure("Resolve edit media", e)
                warnings.append("Resolve用の前後10秒素材を作れませんでした: %s" % str(e)[:180])
            apply_loudness(job, spec, it)   # 編集用素材ができてから、両方に同じ量をかける
            # 仕上がったので本当の名前へ(ここまでに止まったら、書きかけは下の finally で消える)。切り抜き本体 → 編集用素材の順
            it["path"] = promote(it["path"])
            it["file"] = spec["folder"] + "/" + os.path.basename(it["path"])
            if it.get("editPath"):
                try:
                    it["editPath"] = promote(it["editPath"])
                    it["editFile"] = spec["folder"] + "/" + schemas.WORK_DIR + "/" + os.path.basename(it["editPath"])
                except OSError as e:   # 本体はできているので、編集用素材だけ諦める(作れなかったときと同じ扱い)
                    common.log_failure("Resolve edit media の仕上げ", e)
                    _drop_edit(it)
                    warnings.append("Resolve用の前後10秒素材を仕上げられませんでした: %s" % (e.strerror or e.__class__.__name__))
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
        finally:
            if it["status"] != "done":   # 失敗・中止: 書きかけを残さない(仕上がって本当の名前になったものは消さない)
                drop_partial(it.get("path"))
                _drop_edit(it)
    job["state"] = "cancelled" if job["cancel"] else ("error" if any(i["status"] == "error" for i in job["items"]) else "done")
